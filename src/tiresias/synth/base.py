"""Clases base para los controladores de sintetizador.

Para crear un sintetizador nuevo (en el núcleo o en un complemento) basta con
heredar de :class:`AudioSynthDriver` e implementar :meth:`_synthesizeSegment`,
que recibe una lista de cadenas y órdenes y debe producir audio PCM de 16
bits llamando a ``emit(bytes)``. La clase base se encarga del hilo de trabajo,
la cola, la cancelación inmediata, los índices, el volumen y la división del
sonido.

Los sintetizadores que gestionan su propio audio pueden heredar directamente
de :class:`SynthDriver`.
"""

from __future__ import annotations

import array
import queue
import re
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

from ..audio.wave_player import WavePlayer
from ..extension_points import Action
from ..i18n import _
from ..log import getLogger
from ..speech.commands import (
	BreakCommand,
	CharacterModeCommand,
	IndexCommand,
	LangChangeCommand,
	PitchCommand,
	RateCommand,
	VolumeCommand,
)

log = getLogger("synth")

#: Se notifica cuando un sintetizador alcanza un índice: ``synth``, ``index``.
synthIndexReached = Action()
#: Se notifica cuando un sintetizador termina todo lo pendiente: ``synth``.
synthDoneSpeaking = Action()
#: Se notifica cuando un sintetizador falla repetidamente en plena sesión: ``synth``, ``error``.
synthFailed = Action()

#: Fallos seguidos a partir de los que se considera que el sintetizador no funciona.
MAX_CONSECUTIVE_ERRORS = 2
#: Amplitud (16 bits) por debajo de la cual una muestra se considera silencio.
SILENCE_THRESHOLD = 96
#: Margen que se conserva antes del primer sonido al recortar el silencio (ms).
SILENCE_MARGIN_MS = 6
#: Órdenes que cambian el estado de la voz: se repiten delante de cada trozo
#: de un texto largo (las pausas y los fonemas no, porque se oirían otra vez).
STATE_COMMANDS = (CharacterModeCommand, LangChangeCommand, PitchCommand, RateCommand, VolumeCommand)
#: Segundos de audio que el sintetizador puede adelantarse al reproductor. Por
#: encima, el hilo de síntesis espera (contrapresión, como el ``feed`` de NVDA):
#: así un texto enorme no se convierte entero en audio en memoria.
MAX_BUFFERED_SECONDS = 20.0

#: Caracteres que no se pueden codificar ni pasar a un sintetizador: surrogates
#: sueltos (texto de UIA o IAccessible cortado a mitad de un emoji), los
#: no-caracteres U+FFFE/U+FFFF y los caracteres de control salvo tabulador y
#: saltos de línea (un NUL cortaría el texto en las bibliotecas de C).
_unspeakable = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")


def sanitizeText(text: str) -> str:
	"""Sustituye por espacios los caracteres que harían fallar a un sintetizador."""
	if not text:
		return text
	return _unspeakable.sub(" ", text)


def trimLeadingSilence(data: bytes, sampleRate: int, channels: int = 1, threshold: int = SILENCE_THRESHOLD) -> tuple[bytes, bool]:
	"""Quita el silencio inicial de PCM de 16 bits.

	Devuelve ``(datos, encontrado)``: ``encontrado`` es ``False`` si todo el
	bloque era silencio (y entonces ``datos`` está vacío).
	"""
	samples = array.array("h")
	samples.frombytes(data[: len(data) - (len(data) % 2)])
	for i, v in enumerate(samples):
		if v > threshold or v < -threshold:
			margin = int(sampleRate * SILENCE_MARGIN_MS / 1000) * channels
			start = max(0, i - margin)
			start -= start % channels
			return samples[start:].tobytes(), True
	return b"", False


def trimTrailingSilence(data: bytes, sampleRate: int, channels: int = 1, keepMs: int = 20, threshold: int = SILENCE_THRESHOLD) -> bytes:
	"""Quita el silencio final de PCM de 16 bits dejando ``keepMs`` milisegundos."""
	samples = array.array("h")
	samples.frombytes(data[: len(data) - (len(data) % 2)])
	end = len(samples)
	while end > 0 and -threshold <= samples[end - 1] <= threshold:
		end -= 1
	if end == 0:
		return b""
	end = min(len(samples), end + int(sampleRate * keepMs / 1000) * channels)
	end -= end % channels
	return samples[:end].tobytes()


def _trimLeadingEnabled() -> bool:
	try:
		from ..config import conf

		return bool(conf["speech"]["trimLeadingSilence"])
	except Exception:
		return True


class VoiceInfo:
	def __init__(self, id: str, displayName: str, language: str | None = None) -> None:
		self.id = id
		self.displayName = displayName
		self.language = language

	def __repr__(self) -> str:
		return f"VoiceInfo({self.id!r}, {self.displayName!r}, {self.language!r})"


class SynthSetting:
	"""Descripción de un ajuste configurable de un sintetizador."""

	def __init__(
		self,
		id: str,
		displayName: str,
		kind: str = "numeric",
		minVal: int = 0,
		maxVal: int = 100,
		defaultVal: Any = 50,
		normalStep: int = 1,
		largeStep: int = 10,
		availableInRing: bool = True,
	) -> None:
		self.id = id
		self.displayName = displayName
		self.kind = kind
		self.minVal = minVal
		self.maxVal = maxVal
		self.defaultVal = defaultVal
		self.normalStep = normalStep
		self.largeStep = largeStep
		self.availableInRing = availableInRing


def VoiceSetting() -> SynthSetting:
	return SynthSetting("voice", _("Voz"), kind="choice", defaultVal=None)


def VariantSetting() -> SynthSetting:
	return SynthSetting("variant", _("Variante"), kind="choice", defaultVal=None)


def RateSetting(default: int = 50) -> SynthSetting:
	return SynthSetting("rate", _("Velocidad"), defaultVal=default)


def RateBoostSetting() -> SynthSetting:
	return SynthSetting("rateBoost", _("Aumento de velocidad"), kind="boolean", defaultVal=False)


def PitchSetting(default: int = 50) -> SynthSetting:
	return SynthSetting("pitch", _("Tono"), defaultVal=default)


def InflectionSetting(default: int = 50) -> SynthSetting:
	return SynthSetting("inflection", _("Entonación"), defaultVal=default)


def VolumeSetting(default: int = 100) -> SynthSetting:
	return SynthSetting("volume", _("Volumen"), defaultVal=default, normalStep=5)


class SynthDriver:
	"""Clase base abstracta de un sintetizador."""

	#: Identificador único (nombre del módulo).
	name = ""
	#: Nombre descriptivo para la interfaz.
	description = ""
	#: Ajustes que admite este sintetizador.
	supportedSettings: tuple[SynthSetting, ...] = ()

	@classmethod
	def check(cls) -> bool:
		"""``True`` si el sintetizador puede usarse en este equipo."""
		return False

	def __init__(self) -> None:
		self._settings: dict[str, Any] = {}
		for s in self.supportedSettings:
			if s.defaultVal is not None:
				self._settings[s.id] = s.defaultVal

	# --------------------------------------------------- ajustes
	def isSupported(self, settingId: str) -> bool:
		return any(s.id == settingId for s in self.supportedSettings)

	def getSettingInfo(self, settingId: str) -> SynthSetting | None:
		for s in self.supportedSettings:
			if s.id == settingId:
				return s
		return None

	def getSetting(self, settingId: str) -> Any:
		getter = getattr(self, "_get_" + settingId, None)
		if getter:
			return getter()
		return self._settings.get(settingId)

	def setSetting(self, settingId: str, value: Any) -> None:
		info = self.getSettingInfo(settingId)
		if info and info.kind == "numeric":
			value = max(info.minVal, min(info.maxVal, int(value)))
		elif info and info.kind == "boolean":
			value = bool(value)
		setter = getattr(self, "_set_" + settingId, None)
		self._settings[settingId] = value
		if setter:
			setter(value)

	def getChoices(self, settingId: str) -> "OrderedDict[str, VoiceInfo | str]":
		"""Opciones disponibles de un ajuste de tipo ``choice``."""
		getter = getattr(self, "_getAvailable_" + settingId, None)
		if getter:
			return getter()
		return OrderedDict()

	@property
	def availableVoices(self) -> "OrderedDict[str, VoiceInfo]":
		return self.getChoices("voice")  # type: ignore[return-value]

	@property
	def language(self) -> str | None:
		voices = self.availableVoices
		v = voices.get(self.getSetting("voice") or "")
		return v.language if isinstance(v, VoiceInfo) else None

	def saveableSettings(self) -> dict[str, Any]:
		return {s.id: self.getSetting(s.id) for s in self.supportedSettings}

	def loadSettings(self, values: dict[str, Any]) -> None:
		# La voz primero: otros ajustes pueden depender de ella.
		order = sorted(self.supportedSettings, key=lambda s: 0 if s.id == "voice" else 1)
		for s in order:
			if s.id in values and values[s.id] is not None:
				try:
					self.setSetting(s.id, values[s.id])
				except Exception:
					log.exception("No se pudo aplicar %s=%r en %s", s.id, values[s.id], self.name)

	# --------------------------------------------------- voz
	def speak(self, sequence: list) -> None:
		raise NotImplementedError

	def cancel(self) -> None:
		raise NotImplementedError

	def pause(self, switch: bool) -> None:
		pass

	def terminate(self) -> None:
		pass

	# --------------------------------------------------- notificaciones
	def _notifyIndex(self, index: int) -> None:
		synthIndexReached.notify(synth=self, index=index)

	def _notifyDone(self) -> None:
		synthDoneSpeaking.notify(synth=self)


_sentenceSplit = re.compile(r"(?<=[.!?;:\n])\s+")


def splitLongText(text: str, maxLen: int = 280) -> list[str]:
	"""Divide un texto largo en frases para reducir la latencia."""
	if len(text) <= maxLen:
		return [text]
	parts = _sentenceSplit.split(text)
	out: list[str] = []
	cur = ""
	for p in parts:
		if cur and len(cur) + len(p) + 1 > maxLen:
			out.append(cur)
			cur = p
		else:
			cur = f"{cur} {p}" if cur else p
	if cur:
		out.append(cur)
	# Frases demasiado largas: se cortan por espacios.
	final: list[str] = []
	for chunk in out:
		while len(chunk) > maxLen * 2:
			cut = chunk.rfind(" ", 0, maxLen * 2)
			if cut <= 0:
				cut = maxLen * 2
			final.append(chunk[:cut])
			chunk = chunk[cut:]
		final.append(chunk)
	return final


class AudioSynthDriver(SynthDriver):
	"""Sintetizador que produce PCM y lo reproduce con :class:`WavePlayer`."""

	#: Frecuencia de muestreo del audio que produce :meth:`_synthesizeSegment`.
	sampleRate = 22050
	channels = 1
	#: Número del último enunciado recibido (speak): el aviso de fin lleva el
	#: número del último procesado y solo vale si no ha llegado nada después.
	_speakCount = 0

	@property
	def _feedLock(self) -> threading.Lock:
		"""Une la comprobación «¿cancelado?» y el envío al reproductor: sin él,
		un trozo comprobado justo antes de callar se encolaba después del
		``stop`` y sonaba tras pulsar Control. (Se crea al usarlo si una
		subclase no llamó a este ``__init__``.)"""
		lock = self.__dict__.get("_feedLockObj")
		if lock is None:
			lock = self.__dict__.setdefault("_feedLockObj", threading.Lock())
		return lock

	def __init__(self) -> None:
		super().__init__()
		self._generation = 0
		self._queue: queue.Queue[tuple[int, list] | None] = queue.Queue()
		self._player = WavePlayer(self.sampleRate, self.channels, name=self.name or "synth")
		self._player.volume = self._settings.get("volume", 100) / 100.0
		self._speaking = False
		self._worker = threading.Thread(target=self._run, name=f"Synth-{self.name}", daemon=True)
		self._workerStarted = False
		self._errorCount = 0
		self._busySince = 0.0
		self._failed = False
		self._speakCount = 0
		self._feedLockObj = threading.Lock()

	def _ensureWorker(self) -> None:
		if not self._workerStarted:
			self._workerStarted = True
			self._worker.start()

	# --------------------------------------------------- para subclases
	def _initInWorker(self) -> None:
		"""Se ejecuta una vez en el hilo de síntesis (p. ej. inicializar COM)."""

	def _terminateInWorker(self) -> None:
		"""Se ejecuta en el hilo de síntesis al terminar."""

	def _synthesizeSegment(self, items: list, emit: Callable[[bytes], None], isCancelled: Callable[[], bool]) -> None:
		"""Sintetiza ``items`` (cadenas y órdenes de voz, sin índices)."""
		raise NotImplementedError

	def _cancelSynthesis(self) -> None:
		"""Detiene la síntesis en curso lo antes posible (opcional)."""

	# --------------------------------------------------- volumen
	def _set_volume(self, value: int) -> None:
		self._player.volume = value / 100.0

	# --------------------------------------------------- API
	def speak(self, sequence: list) -> None:
		self._ensureWorker()
		self._speaking = True
		self._speakCount += 1
		self._queue.put((self._generation, list(sequence), self._speakCount))

	def runInWorker(self, func: Callable[[], None]) -> None:
		"""Ejecuta ``func`` en el hilo de síntesis (p. ej. exportar a WAV con ``_synthesizeSegment``)."""
		self._ensureWorker()
		self._queue.put(func)

	def cancel(self) -> None:
		with self._feedLock:
			# Con el cerrojo: ningún trozo comprobado antes de este punto puede
			# llegar al reproductor después del stop().
			self._generation += 1
			self._player.stop()
		# Se descarta la voz pendiente, pero no los trabajos de runInWorker
		# (exportar a WAV): si se perdieran, quien espera no terminaría nunca.
		jobs = []
		try:
			while True:
				item = self._queue.get_nowait()
				if item is None or callable(item):
					# None: la orden de terminar el hilo tampoco se pierde.
					jobs.append(item)
		except queue.Empty:
			pass
		for job in jobs:
			self._queue.put(job)
		try:
			self._cancelSynthesis()
		except Exception:
			log.exception("Error cancelando síntesis")
		self._speaking = False

	def _feed(self, data: bytes | None, callback: Callable[[], None] | None, gen: int) -> bool:
		"""Envía audio o una retrollamada al reproductor si ``gen`` sigue vigente."""
		with self._feedLock:
			if gen != self._generation:
				return False
			self._player.feed(data, callback)
			return True

	def _waitForPlayer(self, gen: int) -> None:
		"""Contrapresión: espera mientras el reproductor tenga demasiado audio pendiente.

		Mientras el reproductor avanza (o está en pausa) se renueva la marca del
		vigilante: esperar a que suene lo ya generado no es estar colgado. Si el
		reproductor deja de avanzar, la marca no se renueva y el vigilante actúa.
		"""
		queued = getattr(self._player, "queuedSeconds", None)
		if queued is None:
			return
		last = None
		while gen == self._generation:
			try:
				pending = queued()
			except Exception:
				return
			if pending <= MAX_BUFFERED_SECONDS:
				return
			if last is None or pending < last or getattr(self._player, "isPaused", lambda: False)():
				self._busySince = time.monotonic()
			last = pending
			time.sleep(0.05)

	def pause(self, switch: bool) -> None:
		self._player.pause(switch)

	def terminate(self) -> None:
		self.cancel()
		if self._workerStarted:
			self._queue.put(None)
			# Si el hilo está bloqueado (sintetizador colgado) no se espera.
			self._worker.join(0.2 if self.isStalled() else 3)
		self._player.terminate()

	# --------------------------------------------------- estado
	def isStalled(self, timeout: float = 20.0) -> bool:
		"""``True`` si lleva más de ``timeout`` segundos sintetizando un mismo bloque."""
		busy = self._busySince
		return bool(busy) and time.monotonic() - busy > timeout

	def _reportFailure(self, error: BaseException | None) -> None:
		if self._failed:
			return
		self._failed = True
		synthFailed.notify(synth=self, error=error)

	# --------------------------------------------------- hilo de trabajo
	def _run(self) -> None:
		try:
			self._initInWorker()
		except Exception:
			log.exception("Error inicializando el hilo de %s", self.name)
		while True:
			item = self._queue.get()
			if item is None:
				break
			if callable(item):
				# Trabajo propio en el hilo de síntesis (ver runInWorker).
				try:
					item()
				except Exception:
					log.exception("Error en un trabajo del hilo de %s", self.name)
				continue
			gen, sequence = item[0], item[1]
			number = item[2] if len(item) > 2 else self._speakCount
			if gen != self._generation:
				continue
			self._busySince = time.monotonic()
			try:
				self._processSequence(gen, sequence)
				self._errorCount = 0
			except Exception as e:
				log.exception("Error de síntesis en %s", self.name)
				# Un texto que no se puede codificar es un problema del texto,
				# no del sintetizador: no cuenta para cambiar de sintetizador.
				if not isinstance(e, UnicodeError):
					self._errorCount += 1
					if self._errorCount >= MAX_CONSECUTIVE_ERRORS:
						self._reportFailure(e)
			finally:
				self._busySince = 0.0
			if gen == self._generation and not self._speechPending():
				self._feed(None, lambda g=gen, n=number: self._onAllDone(g, n), gen)
		try:
			self._terminateInWorker()
		except Exception:
			log.exception("Error terminando %s", self.name)

	def _speechPending(self) -> bool:
		"""``True`` si quedan enunciados en la cola (los trabajos de runInWorker no cuentan)."""
		with self._queue.mutex:
			return any(isinstance(item, tuple) for item in self._queue.queue)

	def _onAllDone(self, gen: int, number: int | None = None) -> None:
		# Solo es el final de todo si después del último enunciado procesado no
		# ha llegado otro: si el núcleo envió uno nuevo mientras sonaba el
		# anterior, el hilo ya lo ha sacado de la cola (no está «pendiente») pero
		# aún no ha sonado, y su propio aviso de fin llegará después.
		if number is not None and number != self._speakCount:
			return
		if gen == self._generation and not self._speechPending():
			self._speaking = False
			self._notifyDone()

	def _processSequence(self, gen: int, sequence: list) -> None:
		def isCancelled() -> bool:
			return gen != self._generation

		# Recorte del silencio inicial de cada enunciado (trimLeadingSilence),
		# salvo si empieza con una pausa pedida a propósito.
		trim = [_trimLeadingEnabled() and not (sequence and isinstance(sequence[0], BreakCommand))]

		def emit(data: bytes) -> None:
			if not data or isCancelled():
				return
			if trim[0]:
				data, found = trimLeadingSilence(data, self.sampleRate, self.channels)
				if not found:
					return
				trim[0] = False
			# Hay progreso: el vigilante no debe confundir un texto largo con un cuelgue.
			# (Aquí no se espera al reproductor: algunos controladores llaman a
			# emit desde un hilo propio que no debe bloquearse, como Eloquence.)
			self._busySince = time.monotonic()
			self._feed(data, None, gen)

		segment: list = []

		def synthesize(items: list) -> None:
			# Contrapresión entre trozos (como mucho ~280 caracteres cada uno):
			# si el reproductor ya tiene mucho audio pendiente, se espera.
			self._waitForPlayer(gen)
			if isCancelled():
				return
			self._busySince = time.monotonic()
			self._synthesizeSegment(items, emit, isCancelled)

		def flush() -> None:
			nonlocal segment
			if not any(isinstance(i, str) and i.strip() for i in segment):
				segment = [c for c in segment if not isinstance(c, str)]
				if not segment:
					return
			# Divide textos largos para empezar a sonar antes.
			expanded: list = []
			for it in segment:
				if isinstance(it, str):
					expanded.extend(splitLongText(sanitizeText(it)))
				else:
					expanded.append(it)
			# Cada trozo de texto se sintetiza por separado manteniendo las
			# órdenes previas (prosodia, idioma) que le afectan.
			pending: list = []
			for it in expanded:
				if isCancelled():
					return
				if isinstance(it, str):
					pending.append(it)
					if len(it) > 120:
						synthesize(pending)
						# Solo se conservan las órdenes de estado: una pausa
						# (o un fonema) no se repite delante del trozo siguiente.
						pending = [c for c in pending if isinstance(c, STATE_COMMANDS)]
				else:
					pending.append(it)
			if any(isinstance(i, str) for i in pending) and not isCancelled():
				synthesize(pending)
			segment = []

		for item in sequence:
			if isCancelled():
				return
			if isinstance(item, IndexCommand):
				flush()
				idx = item.index
				self._feed(None, lambda i=idx, g=gen: g == self._generation and self._notifyIndex(i), gen)
			else:
				segment.append(item)
		flush()
