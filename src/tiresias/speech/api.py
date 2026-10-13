"""API principal de voz de Tiresias.

Funciones más usadas::

	from tiresias import speech
	speech.speakMessage("Hola")
	speech.speakSpelling("abc")
	speech.cancelSpeech()

Prioridades (:class:`Priority`):

- ``NORMAL``: se encola detrás de lo que se esté diciendo.
- ``NEXT``: se dice en cuanto termine el enunciado actual, antes que lo
  ``NORMAL`` pendiente.
- ``NOW``: interrumpe lo de menor prioridad, que se **reanuda** después
  desde el último punto alcanzado.

Cada llamada a :func:`speak` crea un enunciado. El gestor (:class:`SpeechManager`)
envía al sintetizador un enunciado (y, como mucho, el siguiente de la misma
prioridad para no dejar huecos) y espera su índice final antes de enviar el
resto. Así puede reordenar, reanudar y descartar la voz obsoleta: lo que se
encoló para un foco que ya no está se elimina al cambiar el foco
(``cancelExpiredFocusSpeech``).

El historial guarda cada enunciado con su **origen** (foco, notificación,
escritura, mensaje, lectura continua...). El origen lo fija el contexto
:func:`speechOrigin` o el parámetro ``origin`` de :func:`speak`.
"""

from __future__ import annotations

import collections
import contextlib
import enum
import re
import threading
import time
import unicodedata
from typing import Any, Callable, Iterable, NamedTuple

from .. import queue_handler
from ..config import conf
from ..extension_points import Action, Filter
from ..i18n import _
from ..log import getLogger
from . import dictionaries, languages, numbers
from .commands import (
	BeepCommand,
	BreakCommand,
	CallbackCommand,
	CharacterModeCommand,
	EndUtteranceCommand,
	IndexCommand,
	LangChangeCommand,
	PitchCommand,
	RateCommand,
	SpeechCommand,
	SymbolLevelCommand,
	VoiceCommand,
	VolumeCommand,
	WaveFileCommand,
	_ProsodyCommand,
)
from .symbols import LEVEL_CHAR, LEVEL_NONE, getProcessor, processor as symbolProcessor

log = getLogger("speech")


class SpeechMode(str, enum.Enum):
	off = "off"
	beeps = "beeps"
	talk = "talk"
	onDemand = "onDemand"


SPEECH_MODE_LABELS = {
	SpeechMode.off: _("voz desactivada"),
	SpeechMode.beeps: _("voz en pitidos"),
	SpeechMode.talk: _("voz activada"),
	SpeechMode.onDemand: _("voz a demanda"),
}

#: Orden del ciclo de modos de voz (Tiresias+S).
SPEECH_MODE_ORDER = [SpeechMode.talk, SpeechMode.onDemand, SpeechMode.beeps, SpeechMode.off]


class Priority(enum.IntEnum):
	NORMAL = 0
	NEXT = 1
	NOW = 2


# ------------------------------------------------------------------ orígenes
ORIGIN_OTHER = "other"
ORIGIN_FOCUS = "focus"
ORIGIN_NOTIFICATION = "notification"
ORIGIN_TYPING = "typing"
ORIGIN_MESSAGE = "message"
ORIGIN_SAYALL = "sayAll"
ORIGIN_CARET = "caret"
ORIGIN_REVIEW = "review"
ORIGIN_CHANGE = "change"
ORIGIN_REMOTE = "remote"

ORIGIN_LABELS = {
	ORIGIN_FOCUS: _("Foco"),
	ORIGIN_NOTIFICATION: _("Notificaciones"),
	ORIGIN_TYPING: _("Escritura"),
	ORIGIN_MESSAGE: _("Mensajes de Tiresias"),
	ORIGIN_SAYALL: _("Lectura continua"),
	ORIGIN_CARET: _("Cursor del sistema"),
	ORIGIN_REVIEW: _("Cursor de revisión"),
	ORIGIN_CHANGE: _("Cambios en los controles"),
	ORIGIN_REMOTE: _("Equipo remoto"),
	ORIGIN_OTHER: _("Otros"),
}


#: Antes de hablar: ``sequence`` (lista final que irá al sintetizador).
pre_speech = Action()
#: Al cancelar la voz.
pre_speechCanceled = Action()
#: Tras pausar o reanudar la voz: ``switch`` (``True`` = en pausa).
post_speechPaused = Action()
#: Permite a complementos modificar el texto antes de procesarlo.
filter_speechText = Filter()
#: Permite a complementos modificar la secuencia completa (cadenas y órdenes)
#: antes de procesarla: el manejador recibe ``value`` (lista) y devuelve otra lista.
filter_speechSequence = Filter()
#: Tras encolar un enunciado: ``speechSequence`` y ``priority``.
pre_speechQueued = Action()
#: Se ha pedido hablar (aunque la voz esté desactivada): ``text`` sin procesar.
#: Lo usa el modo braille «mostrar voz».
post_speechRequested = Action()


class HistoryEntry(NamedTuple):
	time: float
	text: str
	origin: str = ORIGIN_OTHER


_lastSpokenText = ""
_history: collections.deque[HistoryEntry] = collections.deque(maxlen=500)
_historyLock = threading.Lock()
_onDemandAllowed = False
_isPaused = False
_beenCanceled = True
#: Tiresias en espera porque otro lector de pantalla tiene preferencia: no habla nada.
_suspended = False

_originStack: list[str] = []
_validatorStack: list[Callable[[], bool]] = []


def setSuspended(value: bool) -> None:
	"""Silencia por completo la voz de Tiresias (modo en espera, :mod:`tiresias.coexist`)."""
	global _suspended
	_suspended = bool(value)


def isSuspended() -> bool:
	return _suspended


def getSpeechMode() -> SpeechMode:
	try:
		return SpeechMode(conf["speech"]["speechMode"])
	except (ValueError, KeyError):
		return SpeechMode.talk


def setSpeechMode(mode: SpeechMode) -> None:
	if mode != SpeechMode.talk:
		cancelSpeech()
	conf["speech"]["speechMode"] = mode.value


def nextSpeechMode(current: SpeechMode | None = None) -> SpeechMode:
	"""Siguiente modo del ciclo saltando los excluidos (``excludedSpeechModes``)."""
	cur = current or getSpeechMode()
	try:
		excluded = set(conf["speech"]["excludedSpeechModes"])
	except KeyError:
		excluded = set()
	order = SPEECH_MODE_ORDER
	i = order.index(cur) if cur in order else 0
	for step in range(1, len(order) + 1):
		cand = order[(i + step) % len(order)]
		if cand.value not in excluded or cand == cur:
			return cand
	return cur


class _OnDemand:
	"""Contexto que permite hablar en modo «a demanda» (lo usan las órdenes)."""

	def __enter__(self):
		global _onDemandAllowed
		self._prev = _onDemandAllowed
		_onDemandAllowed = True

	def __exit__(self, *exc):
		global _onDemandAllowed
		_onDemandAllowed = self._prev


allowOnDemand = _OnDemand


@contextlib.contextmanager
def speechOrigin(origin: str):
	"""Todo lo que se diga dentro del bloque se marca con ``origin`` en el historial."""
	_originStack.append(origin)
	try:
		yield
	finally:
		_originStack.pop()


@contextlib.contextmanager
def validWhile(validator: Callable[[], bool]):
	"""Lo que se diga dentro del bloque se descarta si ``validator()`` deja de ser cierto."""
	_validatorStack.append(validator)
	try:
		yield
	finally:
		_validatorStack.pop()


def currentOrigin() -> str:
	return _originStack[-1] if _originStack else ORIGIN_OTHER


def focusValidator(obj: Any) -> Callable[[], bool]:
	"""Validador «el foco sigue en ``obj``» para descartar voz obsoleta."""
	from .. import api

	def _valid() -> bool:
		try:
			focus = api.getFocusObject()
			return focus is obj or focus == obj
		except Exception:
			return True

	return _valid


# ------------------------------------------------------------------ gestor
class Utterance:
	"""Un enunciado pendiente o en curso."""

	__slots__ = ("items", "priority", "isValid", "pos", "indexMap", "endIndex", "origin", "seq", "voice")

	def __init__(self, items: list, priority: Priority, isValid: Callable[[], bool] | None = None, origin: str = ORIGIN_OTHER, voice: str | None = None) -> None:
		self.items = items
		self.priority = priority
		self.isValid = isValid
		#: Posición desde la que hay que (re)empezar.
		self.pos = 0
		#: índice del sintetizador -> posición alcanzada al llegar a él.
		self.indexMap: dict[int, int] = {}
		self.endIndex = 0
		self.origin = origin
		#: Número de envío al sintetizador (para el aviso de fin de voz).
		self.seq = 0
		#: Voz propia del enunciado (voces por contexto); ``None`` = la normal.
		self.voice = voice

	def valid(self) -> bool:
		if self.isValid is None:
			return True
		try:
			return bool(self.isValid())
		except Exception:
			return True


#: Máximo de enunciados enviados al sintetizador a la vez (el segundo evita huecos).
MAX_IN_FLIGHT = 2
#: Caracteres de texto entre puntos de reanudación dentro de un enunciado.
RESUME_GRANULARITY = 150
_sentenceEndRe = re.compile(r"[.!?;:…][\"'»”’)\]]*\s*$")
_STATE_COMMANDS = (PitchCommand, RateCommand, VolumeCommand, LangChangeCommand, CharacterModeCommand)


class SpeechManager:
	"""Colas por prioridad, reanudación, voz obsoleta y órdenes intercaladas."""

	def __init__(self) -> None:
		self._nextIndex = 1
		self._sendSeq = 0
		self._lock = threading.RLock()
		self._queues: dict[Priority, collections.deque[Utterance]] = {p: collections.deque() for p in Priority}
		self._sent: list[Utterance] = []
		#: índice -> (enunciado, acción) de llamadas, pitidos y sonidos.
		self._actions: dict[int, Callable[[], None]] = {}
		#: índice -> enunciado (para saber a quién pertenece cada índice).
		self._owners: dict[int, Utterance] = {}
		from .. import synth as synthHandler
		from ..synth import base

		base.synthIndexReached.register(self._onIndexReached)
		base.synthDoneSpeaking.register(self._onDone)
		synthHandler.synthChanged.register(self._onSynthChanged)
		self.doneCallbacks: list[Callable[[], None]] = []
		# Voces por contexto (foros 2.3): voz puesta por el gestor (``None`` =
		# la normal), la voz normal que había antes y el sintetizador.
		self._appliedVoice: str | None = None
		self._normalVoice: str | None = None
		self._voiceSynth: Any = None
		self._voiceIdsCache: tuple[Any, frozenset] = (None, frozenset())

	# --------------------------------------------------- utilidades
	def _allocIndex(self) -> int:
		with self._lock:
			i = self._nextIndex
			self._nextIndex = 1 if i > 1_000_000 else i + 1
			return i

	@property
	def isSpeaking(self) -> bool:
		return bool(self._sent) or any(self._queues.values())

	def pendingCount(self) -> int:
		return len(self._sent) + sum(len(q) for q in self._queues.values())

	# --------------------------------------------------- API
	def speak(self, sequence: list, priority: Priority = Priority.NORMAL, isValid: Callable[[], bool] | None = None, origin: str = ORIGIN_OTHER) -> None:
		"""Encola una secuencia ya procesada (cadenas y órdenes de voz)."""
		from ..synth.base import sanitizeText

		voice: str | None = None
		plain: list = []
		for item in sequence:
			if isinstance(item, VoiceCommand):
				# Una sola voz por enunciado: la primera que aparezca.
				voice = voice or item.voice or None
				continue
			if isinstance(item, str):
				# Surrogates sueltos, NUL... harían fallar al sintetizador (y, dos
				# veces seguidas, se cambiaría de sintetizador por un emoji roto).
				item = sanitizeText(item)
			plain.append(item)
		items = _splitLongStrings(plain)
		if not items:
			return
		utt = Utterance(items, Priority(priority), isValid, origin, voice)
		with self._lock:
			if utt.priority == Priority.NOW and self._sent and any(u.priority < Priority.NOW for u in self._sent):
				self._interrupt()
			self._queues[utt.priority].append(utt)
			self._pushMore()

	def cancel(self) -> None:
		from .. import synth as synthHandler

		with self._lock:
			for q in self._queues.values():
				q.clear()
			self._sent.clear()
			self._actions.clear()
			self._owners.clear()
			self.doneCallbacks.clear()
		synth = synthHandler.getSynth()
		if synth:
			synth.cancel()
		if self._appliedVoice is not None:
			self._applyVoice(None)

	def removeExpired(self) -> None:
		"""Descarta los enunciados cuyo validador ya no se cumple."""
		with self._lock:
			for q in self._queues.values():
				keep = [u for u in q if u.valid()]
				if len(keep) != len(q):
					q.clear()
					q.extend(keep)
			if any(not u.valid() for u in self._sent):
				self._interrupt(dropInvalid=True)
				self._pushMore()

	# --------------------------------------------------- interno
	def _interrupt(self, dropInvalid: bool = False) -> None:
		"""Corta lo que está sonando y devuelve a su cola lo que sigue siendo válido."""
		from .. import synth as synthHandler

		sent, self._sent = self._sent, []
		for u in sent:
			for idx in list(u.indexMap):
				self._actions.pop(idx, None)
				self._owners.pop(idx, None)
			u.indexMap.clear()
		synth = synthHandler.getSynth()
		if synth:
			synth.cancel()
		for u in reversed(sent):
			if dropInvalid and not u.valid():
				continue
			if u.pos < len(u.items):
				self._queues[u.priority].appendleft(u)

	def _nextCandidate(self) -> Utterance | None:
		for p in sorted(Priority, reverse=True):
			q = self._queues[p]
			while q:
				u = q[0]
				if not u.valid():
					q.popleft()
					continue
				return u
		return None

	def _pushMore(self) -> None:
		while len(self._sent) < MAX_IN_FLIGHT:
			cand = self._nextCandidate()
			if cand is None:
				break
			if self._sent:
				# Solo se adelanta un enunciado de la misma prioridad que el actual.
				if cand.priority != self._sent[-1].priority:
					break
			target = self._voiceTarget(cand.voice)
			if target != self._appliedVoice:
				# Cambio de voz (voces por contexto): solo entre enunciados, cuando
				# el sintetizador ha terminado lo anterior.
				if self._sent:
					break
				self._applyVoice(target)
			self._queues[cand.priority].popleft()
			self._send(cand)
		if not self._sent and not any(self._queues.values()):
			if self._appliedVoice is not None:
				self._applyVoice(None)
			self._fireDone()

	# --------------------------------------------------- voces por contexto
	def _voiceIds(self, synth: Any) -> frozenset:
		cached, ids = self._voiceIdsCache
		if cached is not synth:
			try:
				ids = frozenset(synth.availableVoices)
			except Exception:
				ids = frozenset()
			self._voiceIdsCache = (synth, ids)
		return ids

	def _voiceTarget(self, voice: str | None) -> str | None:
		"""Voz que hay que poner para un enunciado (``None`` = la normal)."""
		if not voice:
			return None
		from .. import synth as synthHandler

		synth = synthHandler.getSynth()
		if synth is None or not synth.isSupported("voice"):
			return None
		try:
			if self._appliedVoice is not None and self._voiceSynth is synth:
				normal = self._normalVoice
			else:
				normal = synth.getSetting("voice")
		except Exception:
			return None
		if voice == normal or voice not in self._voiceIds(synth):
			return None
		return voice

	def _applyVoice(self, target: str | None) -> None:
		"""Pone la voz ``target`` o vuelve a la normal (``None``) sin guardar nada."""
		from .. import synth as synthHandler

		synth = synthHandler.getSynth()
		if synth is None:
			self._appliedVoice = None
			return
		if self._voiceSynth is not synth:
			self._voiceSynth = synth
			self._appliedVoice = None
			self._normalVoice = None
		try:
			cur = synth.getSetting("voice")
			if self._appliedVoice is not None and cur != self._appliedVoice:
				# Alguien cambió la voz (anillo de ajustes): esa es ahora la normal.
				self._appliedVoice = None
				self._normalVoice = None
				if target is None or target == cur:
					return
			if target is None:
				if self._appliedVoice is not None and self._normalVoice:
					_setVoiceKeepingProsody(synth, self._normalVoice)
				self._appliedVoice = None
				return
			if self._appliedVoice is None:
				self._normalVoice = cur
			_setVoiceKeepingProsody(synth, target)
			self._appliedVoice = target
		except Exception:
			log.exception("No se pudo cambiar la voz del contexto")
			self._appliedVoice = None

	def savedSettings(self, synth: Any, settings: dict) -> dict:
		"""Ajustes que se guardan: con la voz normal aunque suene la de un contexto."""
		if self._appliedVoice is None or self._voiceSynth is not synth or not self._normalVoice:
			return settings
		if settings.get("voice") == self._appliedVoice:
			settings = dict(settings)
			settings["voice"] = self._normalVoice
		return settings

	def _send(self, utt: Utterance) -> None:
		from .. import synth as synthHandler

		out = _stateAt(utt.items, utt.pos)
		sinceIndex = 0
		prevEndsSentence = False
		for pos in range(utt.pos, len(utt.items)):
			item = utt.items[pos]
			needsIndex = isinstance(item, (CallbackCommand, BeepCommand, WaveFileCommand))
			if isinstance(item, str):
				# Puntos de reanudación cada cierto texto y solo entre frases (no
				# en cada cadena: cada índice parte el segmento que sintetiza el
				# sintetizador y, a mitad de frase, se oiría una pausa).
				if sinceIndex >= RESUME_GRANULARITY and prevEndsSentence:
					needsIndex = True
				sinceIndex += len(item)
				prevEndsSentence = bool(_sentenceEndRe.search(item))
			if not needsIndex:
				if isinstance(item, EndUtteranceCommand):
					out.append(BreakCommand(1))
				elif not isinstance(item, IndexCommand):
					out.append(item)
				continue
			sinceIndex = len(item) if isinstance(item, str) else 0
			idx = self._allocIndex()
			utt.indexMap[idx] = pos
			self._owners[idx] = utt
			if isinstance(item, CallbackCommand):
				self._actions[idx] = item.callback
				out.append(IndexCommand(idx))
				continue
			if isinstance(item, BeepCommand):
				hz, length, l, r = item.hz, item.length, item.left, item.right

				def _beep(hz=hz, length=length, l=l, r=r) -> None:
					from ..audio import tones

					tones.beep(hz, length, l, r)

				self._actions[idx] = _beep
				out.append(IndexCommand(idx))
				continue
			if isinstance(item, WaveFileCommand):
				name = item.name

				def _wave(name=name) -> None:
					from ..audio import tones

					tones.playSound(name)

				self._actions[idx] = _wave
				out.append(IndexCommand(idx))
				continue
			out.append(IndexCommand(idx))
			out.append(item)
		utt.endIndex = self._allocIndex()
		self._owners[utt.endIndex] = utt
		utt.indexMap[utt.endIndex] = len(utt.items)
		out.append(IndexCommand(utt.endIndex))
		self._sendSeq += 1
		utt.seq = self._sendSeq
		self._sent.append(utt)
		synth = synthHandler.getSynth()
		if synth is None:
			# Sin sintetizador: se ejecutan las acciones directamente.
			for item in out:
				if isinstance(item, IndexCommand):
					self._indexReached(item.index)
			return
		synth.speak(_normalizeForSynth(out, self._allocIndex))

	def _indexReached(self, index: int) -> None:
		with self._lock:
			utt = self._owners.pop(index, None)
			action = self._actions.pop(index, None)
			if utt is None:
				return
			pos = utt.indexMap.pop(index, None)
			if pos is not None:
				utt.pos = max(utt.pos, pos)
			finished = index == utt.endIndex
		if action:
			try:
				action()
			except Exception:
				log.exception("Error en acción de voz")
		if finished:
			with self._lock:
				# Lo anterior a este enunciado también ha terminado.
				while self._sent:
					u = self._sent.pop(0)
					for idx in list(u.indexMap):
						self._owners.pop(idx, None)
						self._actions.pop(idx, None)
					if u is utt:
						break
				self._pushMore()

	@staticmethod
	def _isCurrentSynth(synth) -> bool:
		"""Como NVDA: los avisos de un sintetizador que ya no es el actual se ignoran."""
		from .. import synth as synthHandler

		cur = synthHandler.getSynth()
		return synth is None or cur is None or synth is cur

	def _onIndexReached(self, synth, index: int) -> None:
		if not self._isCurrentSynth(synth):
			return
		queue_handler.queueFunction(self._indexReached, index)

	def _onDone(self, synth) -> None:
		if not self._isCurrentSynth(synth):
			return
		# Solo cuenta para lo enviado antes de este aviso.
		queue_handler.queueFunction(self._doneFromSynth, self._sendSeq)

	def _onSynthChanged(self, synth=None, **kwargs) -> None:
		"""Se ha cargado otro sintetizador (cambio pedido o por fallo del anterior).

		Lo enviado al anterior ya no avisará de sus índices: si se quedara «en
		vuelo», el gestor no enviaría nada más y Tiresias se quedaría mudo
		(tampoco se oiría el aviso del cambio de sintetizador). Se devuelve a
		su cola para decirlo con el nuevo desde el último punto alcanzado.
		"""
		with self._lock:
			sent, self._sent = self._sent, []
			for u in sent:
				for idx in list(u.indexMap):
					self._actions.pop(idx, None)
					self._owners.pop(idx, None)
				u.indexMap.clear()
			for u in reversed(sent):
				if u.pos < len(u.items) and u.valid():
					self._queues[u.priority].appendleft(u)
			# La voz de contexto puesta era del sintetizador anterior.
			self._appliedVoice = None
			self._normalVoice = None
			self._voiceSynth = synth
		# Se envía en la siguiente vuelta del núcleo: si el cambio es por un
		# fallo, el aviso («El sintetizador X ha fallado», prioridad «ahora»)
		# se encola antes y se oye primero.
		queue_handler.queueFunction(self._pushPending)

	def _pushPending(self) -> None:
		with self._lock:
			if any(self._queues.values()):
				self._pushMore()

	def _doneFromSynth(self, upToSeq: int) -> None:
		"""El sintetizador terminó todo: lo que quedara sin índice se da por dicho."""
		with self._lock:
			sent = [u for u in self._sent if u.seq <= upToSeq]
		for u in sent:
			# Ejecuta en orden las acciones pendientes del enunciado.
			for idx in sorted(u.indexMap, key=lambda i: u.indexMap[i]):
				self._indexReached(idx)

	def _fireDone(self) -> None:
		callbacks, self.doneCallbacks = self.doneCallbacks, []
		for cb in callbacks:
			try:
				cb()
			except Exception:
				log.exception("Error en fin de voz")


def _setVoiceKeepingProsody(synth: Any, voice: str) -> None:
	"""Cambia de voz conservando velocidad, tono, volumen y entonación (algunos
	sintetizadores los reinician al cambiar de voz)."""
	keep: dict[str, Any] = {}
	for sid in ("rate", "pitch", "volume", "inflection", "rateBoost"):
		try:
			if synth.isSupported(sid):
				keep[sid] = synth.getSetting(sid)
		except Exception:
			pass
	synth.setSetting("voice", voice)
	for sid, value in keep.items():
		if value is not None:
			try:
				synth.setSetting(sid, value)
			except Exception:
				log.debug("No se pudo restablecer %s tras cambiar de voz", sid, exc_info=True)


def savedSynthSettings(synth: Any, settings: dict) -> dict:
	"""Lo usa ``synth.saveCurrentSettings``: no guarda la voz de un contexto."""
	if _manager is None:
		return settings
	return _manager.savedSettings(synth, settings)


def _stateAt(items: list, pos: int) -> list:
	"""Órdenes de estado (idioma, prosodia, deletreo) vigentes en ``pos``."""
	state: dict[type, SpeechCommand] = {}
	for item in items[:pos]:
		if isinstance(item, _STATE_COMMANDS):
			state[type(item)] = item
	return [c for c in state.values() if not _isNeutral(c)]


def _isNeutral(cmd: SpeechCommand) -> bool:
	if isinstance(cmd, _ProsodyCommand):
		return cmd.offset == 0 and cmd.multiplier == 1.0
	if isinstance(cmd, LangChangeCommand):
		return cmd.lang is None
	if isinstance(cmd, CharacterModeCommand):
		return not cmd.state
	return False


def _normalizeForSynth(seq: list, allocIndex: Callable[[], int]) -> list:
	"""Hace que los cambios de prosodia e idioma sean absolutos.

	Los sintetizadores abren una etiqueta por cada orden y no saben volver al
	valor anterior dentro de un mismo segmento. Cada cambio de idioma o
	prosodia se convierte en un corte de segmento (un índice auxiliar)
	seguido del estado completo vigente.
	"""
	out: list = []
	state: dict[type, SpeechCommand] = {}
	for item in seq:
		if isinstance(item, (PitchCommand, RateCommand, VolumeCommand, LangChangeCommand)):
			prev = state.get(type(item))
			if prev is not None and _sameCommand(prev, item):
				continue
			if prev is None and _isNeutral(item):
				continue
			state[type(item)] = item
			out.append(IndexCommand(allocIndex()))
			# El estado completo; la orden que vuelve al valor normal también se envía.
			out.extend(c for c in state.values() if not _isNeutral(c) or c is item)
			continue
		if isinstance(item, CharacterModeCommand):
			state[CharacterModeCommand] = item
		out.append(item)
		if isinstance(item, IndexCommand):
			# Tras cada índice el sintetizador empieza un segmento nuevo: se
			# repite el estado vigente.
			out.extend(c for c in state.values() if not _isNeutral(c))
	return out


def _sameCommand(a: SpeechCommand, b: SpeechCommand) -> bool:
	if isinstance(a, _ProsodyCommand) and isinstance(b, _ProsodyCommand):
		return a.offset == b.offset and a.multiplier == b.multiplier
	if isinstance(a, LangChangeCommand) and isinstance(b, LangChangeCommand):
		return a.lang == b.lang
	return False


_sentenceSplit = re.compile(r"(?<=[.!?;:…])\s+")


def _splitLongStrings(items: list, maxLen: int = 300) -> list:
	"""Parte las cadenas largas por frases: así la reanudación es más precisa."""
	out: list = []
	for item in items:
		if isinstance(item, str) and len(item) > maxLen:
			parts = _sentenceSplit.split(item)
			cur = ""
			for p in parts:
				if cur and len(cur) + len(p) + 1 > maxLen:
					out.append(cur + " ")
					cur = p
				else:
					cur = f"{cur} {p}" if cur else p
			if cur:
				out.append(cur)
		else:
			out.append(item)
	return out


_manager: SpeechManager | None = None


def getManager() -> SpeechManager:
	global _manager
	if _manager is None:
		_manager = SpeechManager()
	return _manager


def isSpeaking() -> bool:
	return _manager is not None and _manager.isSpeaking


# ------------------------------------------------------------------ historial
def _addToHistory(text: str, origin: str | None = None) -> None:
	global _lastSpokenText
	text = text.strip()
	if not text:
		return
	_lastSpokenText = text
	with _historyLock:
		maxLen = conf["speech"]["speechHistorySize"]
		if _history.maxlen != maxLen:
			items = list(_history)[-maxLen:]
			_history.__init__(items, maxlen=maxLen)  # type: ignore[misc]
		_history.append(HistoryEntry(time.time(), text, origin or currentOrigin()))


def getHistory() -> list[HistoryEntry]:
	"""Entradas ``(hora, texto, origen)``; ``entrada[1]`` sigue siendo el texto."""
	with _historyLock:
		return list(_history)


def clearHistory() -> None:
	with _historyLock:
		_history.clear()


def getLastSpokenText() -> str:
	return _lastSpokenText


def exportHistory(path: str, entries: Iterable[HistoryEntry] | None = None, withOrigin: bool = True) -> int:
	"""Guarda el historial (o ``entries``) en un archivo de texto UTF-8."""
	rows = list(entries) if entries is not None else getHistory()
	# errors="replace": un surrogate suelto en el historial no impide exportarlo.
	with open(path, "w", encoding="utf-8", errors="replace") as f:
		for e in rows:
			stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e[0]))
			origin = e[2] if len(e) > 2 else ORIGIN_OTHER
			if withOrigin:
				f.write(f"{stamp}\t{ORIGIN_LABELS.get(origin, origin)}\t{e[1]}\n")
			else:
				f.write(f"{stamp} {e[1]}\n")
	return len(rows)


# ------------------------------------------------------------------ proceso
def processText(text: str, symbolLevel: int | None = None, language: str | None = None) -> str:
	"""Aplica filtros, diccionarios, números y símbolos a un texto.

	``language`` es el idioma en que se leerá (el de la voz si es ``None``):
	se usa su tabla de símbolos.
	"""
	text = filter_speechText.apply(text)
	if "\xad" in text and text.strip("\xad"):
		# Los guiones blandos no se leen: partirían las palabras (#9343, foros 1.20).
		text = text.replace("\xad", "")
	sp = conf["speech"]
	if sp["decodeHtmlEntities"]:
		text = numbers.decodeEntities(text)
	if sp["unicodeNormalization"]:
		text = unicodedata.normalize("NFKC", text)
	text = dictionaries.processText(text)
	if sp["splitAlphanumeric"]:
		text = numbers.splitAlphanumeric(text)
	mode = numbers.effectiveNumberMode(sp)
	if mode != numbers.NUMBER_FULL:
		# Con las convenciones del idioma en que se leerá («1.500» en español, «3.14» en inglés).
		text = numbers.applyNumberMode(text, mode, readingLanguage(language))
	level = sp["symbolLevel"] if symbolLevel is None else symbolLevel
	proc = _processorFor(language)
	if proc is None:
		# No hay tabla para el idioma en que se lee: solo se conserva la
		# puntuación (los nombres en español no sirven a otra voz).
		proc = symbolProcessor
		level = min(level, LEVEL_NONE) if level < LEVEL_CHAR else level
	return proc.process(
		text,
		level,
		condenseRepeats=sp["condenseRepeatedSymbols"],
		repeatThreshold=sp["repeatedSymbolsThreshold"],
		emoji=sp["speakEmojiNames"],
		unknownSymbols=sp["reportUnknownSymbols"],
	)


def _processorFor(language: str | None):
	"""Tabla de símbolos que corresponde al idioma de lectura."""
	sp = conf["speech"]
	if not sp["trustVoiceLanguage"]:
		return symbolProcessor
	lang = language or languages.voiceLanguage()
	return getProcessor(lang)


def readingLanguage(language: str | None = None) -> str:
	"""Idioma de los nombres de caracteres y descripciones."""
	if language:
		return language
	if conf["speech"]["trustVoiceLanguage"]:
		return languages.voiceLanguage()
	return languages.interfaceLanguage()


def _shouldSpeak(origin: str | None = None) -> bool:
	mode = getSpeechMode()
	if mode == SpeechMode.talk:
		return True
	if mode == SpeechMode.onDemand:
		if _onDemandAllowed:
			return True
		# Como en NVDA: la lectura continua empezada con una orden sigue
		# hablando aunque sus siguientes trozos se encolen fuera de la orden.
		if origin == ORIGIN_SAYALL:
			from . import sayall

			return sayall.startedOnDemand()
	return False


class _LangState:
	"""Estado de idioma mientras se procesa una secuencia."""

	def __init__(self) -> None:
		self.voiceLang = languages.voiceLanguage()
		self.current: str | None = None  # idioma activo en el sintetizador (None = el de la voz)
		self.explicit: str | None = None  # idioma marcado por el documento
		self.supported = None
		self.reported: set[str] = set()
		self.sp = conf["speech"]

	def _supported(self) -> set | None:
		if self.supported is None:
			self.supported = languages.supportedLanguages() or set()
		return self.supported or None

	def switch(self, lang: str | None, out: list, explicit: bool) -> None:
		"""Añade a ``out`` el cambio a ``lang`` (con avisos) si hace falta."""
		target = languages.resolveSwitch(lang, self.voiceLang) if lang else None
		if target and not languages.isSupported(target, self._supported()):
			if explicit and target not in self.reported:
				self.reported.add(target)
				out.extend(languages.notSupportedSequence(target))
			target = None
		if target == self.current:
			return
		if target and self.sp["reportLanguage"] and (explicit or self.sp["languageDetection"] != "off"):
			out.append(languages.languageName(target))
		elif target is None and self.current is not None and self.sp["reportLanguage"]:
			out.append(languages.languageName(self.voiceLang))
		out.append(LangChangeCommand(target))
		self.current = target


def _processSequence(seq: list, symbolLevel: int | None) -> list:
	"""Procesa cadenas (símbolos, diccionarios...) y cambios de idioma."""
	sp = conf["speech"]
	switching = sp["autoLanguageSwitching"]
	detection = sp["languageDetection"] if switching else "off"
	state = _LangState()
	processed: list = []
	charMode = False
	# Nivel de puntuación: el de la llamada o el que marque el contexto de voz.
	level = symbolLevel
	for item in seq:
		if isinstance(item, SymbolLevelCommand):
			if symbolLevel is None:
				level = item.level
			continue
		if isinstance(item, LangChangeCommand):
			if not switching:
				continue
			state.explicit = languages.normalize(item.lang)
			state.switch(state.explicit, processed, explicit=True)
			continue
		if isinstance(item, str):
			if not item:
				continue
			if charMode:
				processed.append(item)
				continue
			if state.explicit is None and detection != "off":
				from . import langdetect

				segments = langdetect.detectSegments(item, state.voiceLang, useNgrams=detection == "full")
				for text, lang in segments:
					state.switch(lang, processed, explicit=False)
					processed.append(processText(text, level, state.current))
				continue
			processed.append(processText(item, level, state.current))
			continue
		if isinstance(item, CharacterModeCommand):
			charMode = item.state
		processed.append(item)
	if state.current is not None:
		processed.append(LangChangeCommand(None))
	return processed


def speak(
	sequence: Iterable,
	symbolLevel: int | None = None,
	priority: Priority = Priority.NORMAL,
	force: bool = False,
	origin: str | None = None,
	isValid: Callable[[], bool] | None = None,
) -> None:
	"""Habla una secuencia de cadenas y órdenes de voz.

	``force`` hace que se hable aunque la voz esté desactivada o en pitidos
	(se usa para anunciar el propio cambio de modo). ``origin`` marca la
	entrada del historial. ``isValid`` permite descartar el enunciado si deja
	de tener sentido antes de decirse (por defecto, el validador del contexto
	:func:`validWhile`).
	"""
	global _beenCanceled
	if _suspended:
		# En espera: otro lector tiene preferencia (ni voz, ni historial, ni braille de la voz).
		return
	seq = list(sequence)
	if not seq:
		return
	if len(filter_speechSequence):
		try:
			seq = list(filter_speechSequence.apply(seq))
		except Exception:
			log.exception("Error en filter_speechSequence")
	origin = origin or currentOrigin()
	if isValid is None and _validatorStack and conf["speech"]["cancelExpiredFocusSpeech"]:
		isValid = _validatorStack[-1]
	texts = [s for s in seq if isinstance(s, str)]
	_addToHistory(" ".join(t for t in texts if t), origin)
	if len(post_speechRequested):
		post_speechRequested.notify(text=" ".join(t for t in texts if t))
	mode = SpeechMode.talk if force else getSpeechMode()
	if mode == SpeechMode.beeps:
		from ..audio import tones

		if any(t.strip() for t in texts):
			tones.beep(conf["speech"]["beepSpeechModePitch"], 20)
		return
	if not force and not _shouldSpeak(origin):
		return
	if _isPaused:
		# Como en NVDA: hablar con la voz en pausa descarta lo pausado y quita
		# la pausa (si no, lo nuevo quedaría en silencio hasta reanudar).
		cancelSpeech()
	processed = _processSequence(seq, symbolLevel)
	if not any(isinstance(i, str) and i.strip() for i in processed) and not any(
		isinstance(i, (CallbackCommand, BeepCommand, WaveFileCommand)) for i in processed
	):
		return
	_beenCanceled = False
	if log.isEnabledFor(10):
		log.debug("Voz: %s", " ".join(i for i in processed if isinstance(i, str)))
	pre_speech.notify(sequence=processed)
	getManager().speak(processed, priority, isValid, origin)
	pre_speechQueued.notify(speechSequence=processed, priority=priority)


def contextSequence(context: str, items: list) -> list:
	"""Envuelve ``items`` con la prosodia de un contexto de voz (ver :mod:`voice_schemes`)."""
	from . import voice_schemes

	return voice_schemes.wrapContext(context, items)


def speakMessage(text: str, priority: Priority = Priority.NORMAL) -> None:
	"""Habla un mensaje de Tiresias (en el idioma de la interfaz)."""
	if not text or _suspended:
		# En espera tampoco se muestra en braille (la línea es del otro lector).
		return
	seq: list = [text]
	sp = conf["speech"]
	ui = languages.interfaceLanguage()
	if sp["autoLanguageSwitching"] and languages.base(languages.voiceLanguage()) != languages.base(ui):
		# La voz habla otro idioma: los mensajes van en el de la interfaz.
		seq = [LangChangeCommand(ui), text, LangChangeCommand(None)]
	origin = _originStack[-1] if _originStack else ORIGIN_MESSAGE
	speak(contextSequence("message", seq), priority=priority, origin=origin)
	_brailleMessage(text)


def _brailleMessage(text: str) -> None:
	"""Los mensajes de Tiresias también se muestran en la línea braille."""
	try:
		from .. import braille

		if queue_handler.isCoreThread():
			braille.handler.message(text)
		else:
			queue_handler.queueFunction(braille.handler.message, text)
	except Exception:
		log.debug("No se pudo mostrar el mensaje en braille", exc_info=True)


def speakText(text: str, symbolLevel: int | None = None, priority: Priority = Priority.NORMAL) -> None:
	if text:
		speak([text], symbolLevel=symbolLevel, priority=priority)


def cancelSpeech() -> None:
	global _beenCanceled, _isPaused
	cancelDelayedDescription()
	pre_speechCanceled.notify()
	getManager().cancel()
	_beenCanceled = True
	_isPaused = False


def cancelExpiredSpeech() -> None:
	"""Descarta lo pendiente que ya no es válido (se llama al cambiar el foco)."""
	if _manager is not None and conf["speech"]["cancelExpiredFocusSpeech"]:
		_manager.removeExpired()


def pauseSpeech(switch: bool) -> None:
	global _isPaused
	from .. import synth as synthHandler

	synth = synthHandler.getSynth()
	if synth:
		synth.pause(switch)
	_isPaused = switch
	post_speechPaused.notify(switch=switch)


def isPaused() -> bool:
	return _isPaused


def whenDoneSpeaking(callback: Callable[[], None]) -> None:
	mgr = getManager()
	if not mgr.isSpeaking:
		queue_handler.queueFunction(callback)
		return
	mgr.doneCallbacks.append(callback)


# ------------------------------------------------------------------ deletreo
def _capitalSequence(ch: str) -> tuple[list, list]:
	sp = conf["speech"]
	before: list = []
	after: list = []
	if ch.isupper() and ch.lower() != ch:
		if sp["beepForCapitals"]:
			before.append(BeepCommand(2000, 50))
		if sp["capitalPitchChange"]:
			before.append(PitchCommand(offset=sp["capitalPitchChange"]))
			after.append(PitchCommand(0))
		if sp["sayCapitalForCapitals"]:
			before.append(_("mayúscula") + " ")
	return before, after


def getSpellingSequence(text: str, useCharacterDescriptions: bool = False, language: str | None = None) -> list:
	from .symbols import characterDescription

	lang = readingLanguage(language)
	proc = getProcessor(lang) or symbolProcessor
	seq: list = []
	useSynthSpelling = conf["speech"]["useSpellingFunctionality"]
	for i, ch in enumerate(text):
		before, after = _capitalSequence(ch)
		seq.extend(before)
		desc = characterDescription(ch, lang) if useCharacterDescriptions else None
		if desc:
			seq.append(desc)
		elif ch.isalpha() and len(ch) == 1 and useSynthSpelling and ch.lower() not in "ñ":
			seq.append(CharacterModeCommand(True))
			seq.append(ch)
			seq.append(CharacterModeCommand(False))
		else:
			seq.append(proc.characterName(ch))
		seq.extend(after)
		if i < len(text) - 1:
			seq.append(EndUtteranceCommand())
	return seq


def _wrapLanguage(seq: list, language: str | None) -> list:
	if language and conf["speech"]["autoLanguageSwitching"]:
		return [LangChangeCommand(language)] + seq + [LangChangeCommand(None)]
	return seq


def speakSpelling(text: str, useCharacterDescriptions: bool = False, language: str | None = None, priority: Priority = Priority.NORMAL) -> None:
	cancelDelayedDescription()
	if not text:
		speak([_("en blanco")])
		return
	seq = getSpellingSequence(text, useCharacterDescriptions, language)
	# El deletreo no debe procesar símbolos otra vez: se marca nivel carácter.
	speak(_wrapLanguage(seq, language), symbolLevel=LEVEL_CHAR, priority=priority)


_delayedTimer: int | None = None


def cancelDelayedDescription() -> None:
	"""Cancela la descripción fonética retardada pendiente (al moverse)."""
	global _delayedTimer
	if _delayedTimer is not None:
		try:
			queue_handler.cancelCallLater(_delayedTimer)
		except Exception:
			pass
		_delayedTimer = None


def _speakDelayedDescription(desc: str, language: str | None) -> None:
	global _delayedTimer
	_delayedTimer = None
	speak(_wrapLanguage([desc], language))


def speakCharacter(ch: str, language: str | None = None) -> None:
	"""Anuncia un carácter (navegación por caracteres)."""
	global _delayedTimer
	cancelDelayedDescription()
	if ch in ("\n", "\r", "\r\n", ""):
		speak([_("en blanco")])
		return
	sp = conf["speech"]
	if sp["unicodeNormalization"]:
		normalized = unicodedata.normalize("NFKC", ch)
		if normalized != ch:
			seq = getSpellingSequence(normalized, language=language)
			if sp["reportNormalizedForCharacterNavigation"]:
				seq.append(" " + _("normalizado"))
			speak(_wrapLanguage(seq, language), symbolLevel=LEVEL_CHAR)
			return
	speakSpelling(ch, language=language)
	if sp["delayedCharacterDescriptions"]:
		from .symbols import characterDescription

		desc = characterDescription(ch, readingLanguage(language))
		if desc:
			delay = sp["delayedCharacterDescriptionsDelay"]
			_delayedTimer = queue_handler.callLater(delay, _speakDelayedDescription, desc, language)


def speakTypedCharacter(ch: str) -> None:
	with speechOrigin(ORIGIN_TYPING):
		if ch.isspace():
			name = (getProcessor(readingLanguage()) or symbolProcessor).characterName(ch)
			speak(contextSequence("typing", [name]), symbolLevel=LEVEL_CHAR)
			return
		seq = getSpellingSequence(ch)
		speak(contextSequence("typing", seq), symbolLevel=LEVEL_CHAR)


def speakTypedWord(word: str) -> None:
	with speechOrigin(ORIGIN_TYPING):
		speak(contextSequence("typing", [word]))


def speakLanguage(lang: str | None) -> list:
	return [LangChangeCommand(lang)]


# ------------------------------------------------------------------ mayúsculas en texto
_wordRe = re.compile(r"\w+|\W+")


def capitalizedTextSequence(text: str, mode: str) -> list:
	"""Marca las palabras en mayúsculas de un texto (#3286).

	``mode``: ``initial`` (palabras que empiezan por mayúscula) o ``allCaps``
	(solo palabras enteras en mayúsculas). Usa las mismas indicaciones que el
	deletreo (pitido, cambio de tono y «mayúscula»).
	"""
	if mode not in ("initial", "allCaps") or not any(c.isupper() for c in text):
		return [text]
	from . import voice_schemes

	schemeStyle = voice_schemes.attributeStyle("capital")
	out: list = []
	buf = ""
	for m in _wordRe.finditer(text):
		w = m.group(0)
		isCap = False
		if w[:1].isalpha():
			if mode == "initial":
				isCap = w[0].isupper()
			else:
				isCap = len(w) > 1 and w.isupper()
		if not isCap:
			buf += w
			continue
		if buf:
			out.append(buf)
			buf = ""
		if schemeStyle:
			# El esquema de voz activo define cómo suenan las mayúsculas.
			before, after, _l = voice_schemes.decorate("capital", w)
		else:
			before, after = _capitalSequence(w[0])
		out.extend(before)
		out.append(w)
		out.extend(after)
	if buf:
		out.append(buf)
	return out
