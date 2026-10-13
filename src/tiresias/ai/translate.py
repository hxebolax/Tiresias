"""Traducción con IA.

- Traducir la selección, el portapapeles o lo último que se dijo al idioma
  elegido en las opciones. Los textos largos se traducen por trozos.
- Modo «traducir todo lo que se dice»: cada texto que Tiresias va a decir se
  traduce antes de hablar. Las traducciones se guardan en memoria; mientras
  llega una traducción nueva no se dice nada y, al llegar, se lee.

Modo «traducir todo» (revisión 1.0.11):

- Una sola cola y un solo hilo: los textos se traducen y se dicen en el orden
  en que se iban a decir, sin lanzar decenas de peticiones a la vez.
- Al cancelar la voz (cambio de foco, Control...) sube la *generación*: lo
  que quedaba en la cola se descarta y las traducciones que lleguen después
  se guardan pero no se dicen (ya no vienen a cuento).
- Espera corta (``SPEECH_TIMEOUT``) y sin reintentos: si el servicio tarda,
  se dice el texto original en lugar de dejar al usuario en silencio.
- Sin red, sin respuesta o con el límite de uso agotado se dice el original y
  se deja de pedir traducciones durante ``PAUSE_SECONDS`` (con un aviso).
  Si la clave, el permiso o el saldo fallan, el modo se desactiva y se avisa.
"""

from __future__ import annotations

import collections
import re
import threading
import time

from .. import api, queue_handler, speech, textinfo
from ..config import conf
from ..i18n import _
from ..log import getLogger
from .providers import AIError, Message, configMessage, getProvider

log = getLogger("ai.translate")

LANGUAGES = [
	("es", _("español")),
	("en", _("inglés")),
	("fr", _("francés")),
	("de", _("alemán")),
	("it", _("italiano")),
	("pt", _("portugués")),
	("ca", _("catalán")),
	("gl", _("gallego")),
	("eu", _("euskera")),
	("nl", _("neerlandés")),
	("ru", _("ruso")),
	("zh", _("chino")),
	("ja", _("japonés")),
	("ar", _("árabe")),
]
_NAMES = dict(LANGUAGES)

#: Tamaño de cada trozo de un texto largo (caracteres).
CHUNK_CHARS = 6000
#: Límite de salida de cada trozo (incluye el razonamiento de los modelos que razonan).
CHUNK_MAX_TOKENS = 16000
#: Espera máxima de una traducción para la voz (segundos).
SPEECH_TIMEOUT = 8.0
#: Pausa del modo «traducir todo» tras quedarse sin red o sin respuesta.
PAUSE_SECONDS = 60.0
#: Máximo de textos esperando turno en la cola de la voz.
MAX_QUEUE = 40

INCOMPLETE_NOTE = _("[Traducción incompleta: el texto era demasiado largo.]")

#: Hilo actual traduciendo para la voz (espera corta y sin reintentos).
_tls = threading.local()


def targetLanguage() -> str:
	code = conf["ai"]["translateTo"]
	return _NAMES.get(code, code or _("español"))


def translationPrompt(text: str) -> str:
	return (
		f"Traduce al {targetLanguage()} el texto que va entre etiquetas <texto>. "
		"Si ya está en ese idioma, devuélvelo igual. Responde solo con la traducción, sin comentarios ni comillas.\n"
		f"<texto>\n{text}\n</texto>"
	)


_BREAKS = (re.compile(r"\n\s*\n"), re.compile(r"\n"), re.compile(r"(?<=[.!?;:])\s+"), re.compile(r"\s+"))


def splitText(text: str, size: int = CHUNK_CHARS) -> list[str]:
	"""Trozos de como mucho ``size`` caracteres, cortados por párrafos, líneas o frases."""
	out: list[str] = []
	rest = text
	while len(rest) > size:
		cut = -1
		for rx in _BREAKS:
			for m in rx.finditer(rest, 0, size + 1):
				if m.end() <= size:
					cut = m.end()
			if cut > size // 3:
				break
		if cut <= 0:
			cut = size
		out.append(rest[:cut])
		rest = rest[cut:]
	if rest:
		out.append(rest)
	return out


def translateText(text: str) -> str:
	"""Traduce (bloquea: usar en un hilo). Los textos largos van por trozos."""
	provider = getProvider()
	forSpeech = bool(getattr(_tls, "speech", False))
	parts: list[str] = []
	incomplete = False
	for chunk in splitText(text) or [text]:
		# Tarea corta: poco razonamiento (responde antes, sobre todo al traducir la voz).
		kwargs = {"timeout": SPEECH_TIMEOUT, "retries": 0} if forSpeech else {}
		reply = provider.chat([Message("user", translationPrompt(chunk))], "Eres un traductor. Respondes solo con la traducción.", maxTokens=CHUNK_MAX_TOKENS, effort="low", **kwargs)
		parts.append(reply.text.strip())
		incomplete = incomplete or bool(getattr(reply, "truncated", False))
	result = "\n".join(p for p in parts if p)
	if incomplete:
		result += "\n" + INCOMPLETE_NOTE
	return result


def _translateAsync(text: str, what: str) -> None:
	text = text.strip()
	if not text:
		speech.speakMessage(_("No hay {what} que traducir").format(what=what))
		return
	provider = getProvider()
	problem = configMessage(provider)
	if problem:
		speech.speakMessage(problem)
		return
	speech.speakMessage(_("Traduciendo"))

	def worker() -> None:
		try:
			result = translateText(text)
		except AIError as e:
			queue_handler.queueFunction(speech.speakMessage, str(e))
			return
		except Exception as e:
			log.exception("Error traduciendo")
			queue_handler.queueFunction(speech.speakMessage, _("Error inesperado al traducir ({kind}). El detalle está en el registro.").format(kind=type(e).__name__))
			return
		queue_handler.queueFunction(_deliver, result)

	threading.Thread(target=worker, name="IA-traducción", daemon=True).start()


#: Última traducción (para copiarla).
lastTranslation = ""


def _deliver(result: str) -> None:
	global lastTranslation
	lastTranslation = result
	_passthrough.add(result)
	speech.cancelSpeech()
	speech.speakText(result)


def selectedText() -> str:
	obj = api.getCaretObject()
	if obj is None:
		return ""
	try:
		info = obj.makeTextInfo(textinfo.POSITION_SELECTION)
		return info.text if not info.isCollapsed else ""
	except Exception:
		return ""


def translateSelection() -> None:
	_translateAsync(selectedText(), _("texto seleccionado"))


def translateClipboard() -> None:
	from .. import winapi

	_translateAsync(winapi.getClipboardText() or "", _("texto en el portapapeles"))


def translateLastSpoken() -> None:
	_translateAsync(speech.getLastSpokenText(), _("texto dicho"))


def copyLastTranslation() -> None:
	if not lastTranslation:
		speech.speakMessage(_("Todavía no hay ninguna traducción"))
		return
	api.copyToClip(lastTranslation, notify=True)


def cycleTargetLanguage() -> None:
	codes = [c for c, _n in LANGUAGES]
	cur = conf["ai"]["translateTo"]
	new = codes[(codes.index(cur) + 1) % len(codes)] if cur in codes else codes[0]
	conf["ai"]["translateTo"] = new
	with _lock:
		_cache.clear()
	speech.speakMessage(_("Traducir al {lang}").format(lang=_NAMES[new]))


# ====================================================================== traducir todo
_cache: collections.OrderedDict[str, str] = collections.OrderedDict()
_CACHE_SIZE = 2000
#: Textos que ya son traducciones: no se vuelven a traducir.
_passthrough: set[str] = set()
_pending: set[str] = set()
#: Textos cuya traducción falló hace poco (texto -> instante): se dicen tal
#: cual sin volver a pedirla hasta pasado ``_RETRY_AFTER``. Las traducciones
#: fallidas no se guardan en la caché.
_failed: dict[str, float] = {}
_RETRY_AFTER = 60.0
_lock = threading.Lock()
_cond = threading.Condition(_lock)
#: Cola de la voz: (texto, generación).
_queue: collections.deque[tuple[str, int]] = collections.deque()
_worker: threading.Thread | None = None
#: Generación de la voz: sube cada vez que se cancela.
_gen = 0
#: Sin red o sin respuesta: no se piden traducciones hasta este instante (monotónico).
_pausedUntil = 0.0


def _worthTranslating(text: str) -> bool:
	t = text.strip()
	return len(t) >= 2 and any(ch.isalpha() for ch in t)


def _ensureWorker() -> None:
	"""Arranca el hilo de la cola si no está en marcha (con ``_lock`` tomado)."""
	global _worker
	if _worker is None or not _worker.is_alive():
		_worker = threading.Thread(target=_workerLoop, name="IA-traducción-voz", daemon=True)
		_worker.start()


def speechFilter(value: str) -> str:
	"""Filtro de voz del modo «traducir todo lo que se dice»."""
	if not conf["ai"]["translateSpeech"] or not _worthTranslating(value):
		return value
	if value in _passthrough:
		return value
	with _lock:
		if time.monotonic() < _pausedUntil:
			return value
		failedAt = _failed.get(value)
		if failedAt is not None:
			if time.monotonic() - failedAt < _RETRY_AFTER:
				return value
			del _failed[value]
		cached = _cache.get(value)
		if cached is not None:
			_cache.move_to_end(value)
			return cached
		if value in _pending:
			return ""
		_pending.add(value)
		_queue.append((value, _gen))
		while len(_queue) > MAX_QUEUE:
			old, _g = _queue.popleft()
			_pending.discard(old)
		_ensureWorker()
		_cond.notify()
	return ""


def _onSpeechCanceled(**kwargs) -> None:
	"""Se canceló la voz: lo que esperaba turno ya no viene a cuento."""
	global _gen
	with _lock:
		_gen += 1
		for text, _g in _queue:
			_pending.discard(text)
		_queue.clear()


def _workerLoop() -> None:
	_tls.speech = True
	while True:
		with _cond:
			while not _queue:
				_cond.wait()
			text, gen = _queue.popleft()
			if gen != _gen:
				_pending.discard(text)
				continue
		try:
			_translateForSpeech(text, gen)
		except Exception:
			log.exception("Error en la cola de traducción de la voz")


def _speakIfCurrent(text: str, gen: int, original: bool = False) -> None:
	"""Dice ``text`` si la voz no se ha cancelado desde que se pidió (hilo del núcleo).

	Una traducción ya no se dice si entretanto se desactivó el modo; el texto
	original (``original``, cuando la traducción falló) se dice siempre.
	"""
	if gen == _gen and (original or conf["ai"]["translateSpeech"]):
		speech.speakText(text)


def _translateForSpeech(text: str, gen: int | None = None) -> None:
	global _pausedUntil
	if gen is None:
		gen = _gen
	old = getattr(_tls, "speech", False)
	_tls.speech = True
	try:
		result = translateText(text)
	except Exception as e:
		log.warning("No se pudo traducir para la voz: %s", e)
		# No se guarda en la caché: se dice el original y se podrá volver a
		# intentar más tarde.
		pauseNow = isinstance(e, AIError) and e.kind in ("network", "timeout", "quota", "overloaded", "server")
		with _lock:
			_pending.discard(text)
			_failed[text] = time.monotonic()
			if len(_failed) > _CACHE_SIZE:
				_failed.clear()
				_failed[text] = time.monotonic()
			startPause = pauseNow and time.monotonic() >= _pausedUntil
			if pauseNow:
				_pausedUntil = time.monotonic() + PAUSE_SECONDS
		if isinstance(e, AIError) and e.isAccountProblem:
			queue_handler.queueFunction(_disableForError, str(e))
		elif startPause:
			queue_handler.queueFunction(speech.speakMessage, _("Traducción de la voz en pausa un minuto: {err}").format(err=str(e).rstrip(".")))
		queue_handler.queueFunction(_speakIfCurrent, text, gen, True)
		return
	finally:
		_tls.speech = old
	with _lock:
		_pending.discard(text)
		_cache[text] = result
		while len(_cache) > _CACHE_SIZE:
			_cache.popitem(last=False)
		_passthrough.add(result)
		if len(_passthrough) > _CACHE_SIZE * 2:
			_passthrough.clear()
			_passthrough.update(_cache.values())
	queue_handler.queueFunction(_speakIfCurrent, result, gen)


def _disableForError(error: str) -> None:
	"""La clave, el permiso o el saldo fallan: el modo se desactiva y se avisa una vez."""
	if not conf["ai"]["translateSpeech"]:
		return
	conf["ai"]["translateSpeech"] = False
	speech.speakMessage(_("Traducción de la voz desactivada: {err}").format(err=error))


def toggleTranslateSpeech() -> None:
	global _pausedUntil
	provider = getProvider()
	v = not conf["ai"]["translateSpeech"]
	problem = configMessage(provider) if v else ""
	if problem:
		speech.speakMessage(problem)
		return
	if v:
		with _lock:
			_pausedUntil = 0.0
			_failed.clear()
		speech.speakMessage(_("Se traducirá al {lang} todo lo que se dice").format(lang=targetLanguage()))
		conf["ai"]["translateSpeech"] = True
	else:
		conf["ai"]["translateSpeech"] = False
		_onSpeechCanceled()
		speech.speakMessage(_("Traducción de la voz desactivada"))


def _cancelHook():
	return getattr(getattr(speech, "api", None), "pre_speechCanceled", None)


def initialize() -> None:
	speech.filter_speechText.register(speechFilter)
	hook = _cancelHook()
	if hook is not None:
		hook.register(_onSpeechCanceled)


def terminate() -> None:
	speech.filter_speechText.unregister(speechFilter)
	hook = _cancelHook()
	if hook is not None:
		hook.unregister(_onSpeechCanceled)
