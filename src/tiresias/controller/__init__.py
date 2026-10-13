"""API de control: que los juegos y programas hablen a través de Tiresias.

Tiresias atiende por RPC local las mismas llamadas que el «NVDA Controller
Client» (``nvdaControllerClient.dll``), que traen muchísimos audiojuegos,
mods y bibliotecas como Tolk, SRAL o accessible_output2, además de su
propia API (``tiresiasControllerClient.dll``). Así esos programas hablan y
muestran braille con Tiresias aunque NVDA no esté instalado.

Piezas:

- ``controller/src``: servidor y cliente nativos (C + MIDL) y ``build.py``,
  que deja los binarios en ``data/controller/<arq>`` (:func:`.server.controllerDir`).
- :mod:`.server`: carga del servidor nativo y retrollamadas.
- :mod:`.ssml`: interpretación del SSML de ``speakSsml``.
- Este módulo: qué hace Tiresias con cada llamada (voz, braille, filtros por
  aplicación, silencio temporal) y la ventana de compatibilidad opcional.

Documentación para desarrolladores: ``docs/api_control.md``.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import queue
import threading
import time
from dataclasses import dataclass

from .. import queue_handler
from ..log import getLogger
from . import ssml as ssmlModule
from .server import ERROR_SERVICE_NOT_ACTIVE, NVDA_PREFIX, RPC_S_OK, TIRESIAS_PREFIX, ControllerServer, Handlers

log = getLogger("controller")

DEFAULTS = {
	# Atender a los programas (si no, responden como si no hubiera lector).
	"enabled": True,
	# Atender también en el punto de conexión de NVDA (nvdaControllerClient).
	"nvdaCompatible": True,
	# Cortar lo que se esté diciendo con cada texto nuevo de un programa.
	"interrupt": False,
	# Mostrar en braille los textos que los programas mandan hablar.
	"speechToBraille": False,
	# Mostrar los mensajes braille que mandan los programas.
	"allowBraille": True,
	# Solo atender al programa que está en primer plano.
	"onlyForeground": False,
	# Ventana oculta «NVDA» para programas que buscan esa ventana.
	"nvdaWindow": True,
}

#: Longitud máxima de un texto recibido (lo que sobra se descarta).
MAX_TEXT = 20000
#: Cada cuánto se reintenta ocupar el punto de conexión de NVDA (ms).
RETRY_NVDA_MS = 15000
#: Tiempo máximo que espera un speakSsml síncrono (s).
SSML_SYNC_TIMEOUT = 120.0

TIRESIAS_SPEAK_INTERRUPT = 0x1
TIRESIAS_SPEAK_SPELL = 0x2
TIRESIAS_SPEAK_BRAILLE = 0x4

SPEECH_PRIORITY_NOW = 2
SYMBOL_LEVEL_UNCHANGED = -1


@dataclass
class ClientInfo:
	pid: int
	name: str
	firstSeen: float
	lastSeen: float
	calls: int = 0


_server: ControllerServer | None = None
_initialized = False
_muted = False
_clients: dict[int, ClientInfo] = {}
_clientsLock = threading.Lock()
_speakingFlag = False
_nvdaRetryTimer: int | None = None
_nvdaBusyLogged = False
#: Auxiliar ``tiresiasNvdaWindow.exe`` (subprocess.Popen): ventana «NVDA» y punto de conexión de NVDA.
_helper = None
#: Lo que ofrece el auxiliar en ejecución: (ventana, punto de conexión).
_helperOptions: tuple[bool, bool] = (False, False)
_helperLock = threading.Lock()
_ownPid = os.getpid()


def _conf():
	from ..config import conf

	return conf["controller"]


def registerDefaults() -> None:
	from ..config import conf

	conf.registerDefaults("controller", DEFAULTS)


# ------------------------------------------------------------------ utilidades
def _processName(pid: int) -> str:
	try:
		import psutil

		return psutil.Process(pid).name()
	except Exception:
		return str(pid) if pid else "?"


def foregroundPid() -> int:
	"""Proceso de la ventana en primer plano (Win32 puro: vale en cualquier hilo)."""
	u32 = ctypes.windll.user32
	u32.GetForegroundWindow.restype = wt.HWND
	hwnd = u32.GetForegroundWindow()
	if not hwnd:
		return 0
	pid = wt.DWORD(0)
	u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
	return pid.value


def getClients() -> list[ClientInfo]:
	"""Programas que han usado la API en esta sesión (el más reciente primero)."""
	with _clientsLock:
		return sorted(_clients.values(), key=lambda c: c.lastSeen, reverse=True)


def _touchClient(pid: int) -> None:
	now = time.time()
	with _clientsLock:
		info = _clients.get(pid)
		if info is None:
			info = _clients[pid] = ClientInfo(pid, _processName(pid), now, now)
			log.info("Programa usando la API de control: %s (PID %d)", info.name, pid)
		info.lastSeen = now
		info.calls += 1


def isMuted() -> bool:
	return _muted


def setMuted(value: bool) -> None:
	global _muted
	_muted = bool(value)


def isSpeaking() -> bool:
	from .. import synth

	s = synth.getSynth()
	val = getattr(s, "_speaking", None) if s is not None else None
	if isinstance(val, bool):
		return val
	return _speakingFlag


def _onPreSpeech(sequence=None, **kw) -> None:
	global _speakingFlag
	_speakingFlag = True


def _onSpeechStopped(**kw) -> None:
	global _speakingFlag
	_speakingFlag = False


def _clip(text: str) -> str:
	return text[:MAX_TEXT] if len(text) > MAX_TEXT else text


# ------------------------------------------------------------------ acciones (núcleo)
#: Origen de la voz en el historial de voz.
ORIGIN = "external"


def _origin():
	"""Marca la voz como «Programas externos» en el historial (si la API lo admite)."""
	import contextlib

	from ..speech import api as speechApi

	labels = getattr(speechApi, "ORIGIN_LABELS", None)
	if isinstance(labels, dict) and ORIGIN not in labels:
		from ..i18n import _

		labels[ORIGIN] = _("Programas externos")
	ctx = getattr(speechApi, "speechOrigin", None)
	return ctx(ORIGIN) if ctx is not None else contextlib.nullcontext()


def _priority(value: int):
	from ..speech import api as speechApi

	try:
		return speechApi.Priority(int(value))
	except Exception:
		return speechApi.Priority.NORMAL


def _speakOnCore(text: str, interrupt: bool, toBraille: bool) -> None:
	from .. import speech

	if interrupt:
		speech.cancelSpeech()
	with _origin():
		speech.speak([text])
	if toBraille:
		_brailleOnCore(text)


def _brailleOnCore(text: str) -> None:
	try:
		from .. import braille

		if braille.handler is not None:
			braille.handler.message(text)
	except Exception:
		log.debug("No se pudo mostrar el mensaje en braille", exc_info=True)


def _cancelOnCore() -> None:
	from .. import speech

	speech.cancelSpeech()


def _spellOnCore(text: str, interrupt: bool, toBraille: bool) -> None:
	from .. import speech

	if interrupt:
		speech.cancelSpeech()
	with _origin():
		speech.speakSpelling(text)
	if toBraille:
		_brailleOnCore(text)


def buildSequence(items: list, onMark=None) -> list:
	"""Convierte la lista de :func:`ssml.parse` en una secuencia de voz.

	``onMark(nombre)`` se llama cuando la voz llega a cada marca.
	"""
	from ..speech import api as speechApi
	from ..speech.commands import BreakCommand, CallbackCommand, LangChangeCommand, PhonemeCommand, PitchCommand, RateCommand, VolumeCommand

	prosody = {"pitch": PitchCommand, "rate": RateCommand, "volume": VolumeCommand}
	seq: list = []
	for it in items:
		if isinstance(it, str):
			seq.append(it)
			continue
		kind = it[0]
		if kind == "break":
			seq.append(BreakCommand(int(it[1])))
		elif kind == "mark":
			if onMark is not None:
				seq.append(CallbackCommand(lambda n=it[1]: onMark(n)))
		elif kind in prosody:
			seq.append(prosody[kind](multiplier=float(it[1])))
		elif kind == "lang":
			seq.append(LangChangeCommand(it[1]))
		elif kind == "spell":
			seq.extend(speechApi.getSpellingSequence(it[1]))
		elif kind == "phoneme":
			seq.append(PhonemeCommand(it[1], it[2]))
	return seq


def _ssmlOnCore(items: list, symbolLevel: int | None, priority: int, interrupt: bool, toBraille: bool, onMark, onDone, queued: threading.Event) -> None:
	from .. import speech
	from ..speech.commands import CallbackCommand

	try:
		if interrupt:
			speech.cancelSpeech()
		seq = buildSequence(items, onMark)
		if onDone is not None:
			seq.append(CallbackCommand(onDone))
		with _origin():
			speech.speak(seq, symbolLevel=symbolLevel, priority=_priority(priority))
		if toBraille:
			text = ssmlModule.plainText(items)
			if text:
				_brailleOnCore(text)
	finally:
		queued.set()


# ------------------------------------------------------------------ manejadores RPC
class TiresiasHandlers(Handlers):
	"""Se ejecutan en hilos del RPC: solo encolan trabajo en el núcleo."""

	def _check(self, pid: int) -> int | None:
		"""``None`` si la llamada se atiende; si no, el código que se devuelve."""
		c = _conf()
		if not c["enabled"] or _inStandby():
			# En espera (otro lector tiene preferencia): las bibliotecas pasan a ese lector.
			return ERROR_SERVICE_NOT_ACTIVE
		_touchClient(pid)
		if _muted:
			return 0
		if c["onlyForeground"] and pid and pid != _ownPid and pid != foregroundPid():
			return 0
		return None

	def testIfRunning(self, pid: int) -> int:
		return 0 if _conf()["enabled"] and not _inStandby() else ERROR_SERVICE_NOT_ACTIVE

	def speakText(self, pid: int, text: str) -> int:
		res = self._check(pid)
		if res is not None:
			return res
		c = _conf()
		queue_handler.queueFunction(_speakOnCore, _clip(text), bool(c["interrupt"]), bool(c["speechToBraille"]))
		return 0

	def cancelSpeech(self, pid: int) -> int:
		res = self._check(pid)
		if res is not None:
			return res
		queue_handler.queueFunction(_cancelOnCore)
		return 0

	def brailleMessage(self, pid: int, text: str) -> int:
		res = self._check(pid)
		if res is not None:
			return res
		if _conf()["allowBraille"]:
			queue_handler.queueFunction(_brailleOnCore, _clip(text))
		return 0

	def speakTextEx(self, pid: int, text: str, flags: int) -> int:
		res = self._check(pid)
		if res is not None:
			return res
		c = _conf()
		interrupt = bool(flags & TIRESIAS_SPEAK_INTERRUPT) or bool(c["interrupt"])
		toBraille = (bool(flags & TIRESIAS_SPEAK_BRAILLE) and bool(c["allowBraille"])) or bool(c["speechToBraille"])
		if flags & TIRESIAS_SPEAK_SPELL:
			queue_handler.queueFunction(_spellOnCore, _clip(text), interrupt, toBraille)
		else:
			queue_handler.queueFunction(_speakOnCore, _clip(text), interrupt, toBraille)
		return 0

	def pauseSpeech(self, pid: int, pause: bool) -> int:  # NVDA #12945
		res = self._check(pid)
		if res is not None:
			return res
		from .. import speech

		queue_handler.queueFunction(speech.pauseSpeech, bool(pause))
		return 0

	def isSpeaking(self, pid: int) -> tuple[int, bool]:  # NVDA #20179
		if not _conf()["enabled"] or _inStandby():
			return ERROR_SERVICE_NOT_ACTIVE, False
		return 0, isSpeaking()

	def speakSsml(self, pid: int, ssml: str, symbolLevel: int, priority: int, asynchronous: bool) -> int:
		res = self._check(pid)
		if res is not None:
			return res
		c = _conf()
		items = ssmlModule.parse(_clip(ssml))
		if not items:
			return 0
		level = None if symbolLevel == SYMBOL_LEVEL_UNCHANGED or symbolLevel not in (0, 100, 200, 300, 1000) else symbolLevel
		interrupt = bool(c["interrupt"])
		toBraille = bool(c["speechToBraille"])
		queued = threading.Event()
		if asynchronous:
			queue_handler.queueFunction(_ssmlOnCore, items, level, priority, interrupt, toBraille, None, None, queued)
			return 0
		events: queue.Queue = queue.Queue()
		queue_handler.queueFunction(
			_ssmlOnCore,
			items,
			level,
			priority,
			interrupt,
			toBraille,
			lambda name: events.put(("mark", name)),
			lambda: events.put(("done", None)),
			queued,
		)
		return self._waitSsml(events, queued)

	def _waitSsml(self, events: queue.Queue, queued: threading.Event) -> int:
		"""Espera en este hilo RPC a que termine la voz y reenvía las marcas."""
		start = time.monotonic()
		idleSince: float | None = None
		while time.monotonic() - start < SSML_SYNC_TIMEOUT:
			if _server is None or not _initialized:
				break
			try:
				kind, value = events.get(timeout=0.1)
			except queue.Empty:
				if not queued.is_set():
					continue
				# Voz desactivada, cancelada o sin sintetizador: no llegarán más avisos.
				if isSpeaking():
					idleSince = None
				elif idleSince is None:
					idleSince = time.monotonic()
				elif time.monotonic() - idleSince > 0.4:
					break
				continue
			idleSince = None
			if kind == "done":
				break
			if kind == "mark" and _server is not None:
				status = _server.markReached(value)
				if status not in (0, 120):
					log.debug("El cliente no aceptó la marca %s (estado %d)", value, status)
		return 0


# ------------------------------------------------------------------ auxiliar de compatibilidad con NVDA
def _findNvdaWindow() -> int:
	u32 = ctypes.windll.user32
	u32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
	u32.FindWindowW.restype = wt.HWND
	return u32.FindWindowW("wxWindowClassNR", "NVDA") or 0


def _windowHelperPath() -> str:
	from .server import controllerDir

	return os.path.join(controllerDir(), "x64", "tiresiasNvdaWindow.exe")


def _inStandby() -> bool:
	"""Tiresias está en espera porque otro lector de pantalla tiene preferencia."""
	try:
		from .. import coexist

		return coexist.isStandby()
	except Exception:
		return False


def _nvdaRunning() -> bool:
	"""¿Hay un NVDA de verdad en ejecución (no el auxiliar de Tiresias)?"""
	try:
		from ..coexist import detect

		return detect.isNvdaRunning(excludePids={_helper.pid} if _helper is not None else None)
	except Exception:
		log.debug("No se pudo comprobar si NVDA está en ejecución", exc_info=True)
		return bool(_findNvdaWindow()) and not hasNvdaWindow()


def _wantedHelper() -> tuple[bool, bool]:
	"""``(ventana, punto de conexión)`` que debe ofrecer ahora el auxiliar."""
	if not _initialized or _server is None:
		return False, False
	c = _conf()
	if not (c["enabled"] and c["nvdaCompatible"]) or _inStandby():
		return False, False
	return bool(c["nvdaWindow"]), _server.supportsRelay


def _updateWindow() -> None:
	"""Arranca, reinicia o cierra el auxiliar ``tiresiasNvdaWindow.exe``.

	El auxiliar ofrece, en un proceso aparte, la ventana oculta «NVDA» (Tolk y
	otras bibliotecas la buscan antes de usar nvdaControllerClient) y el punto
	de conexión de NVDA (``NvdaCtlr.<sesión>.<escritorio>``), reenviando las
	llamadas a Tiresias. Va aparte porque un proceso no puede soltar un punto
	de conexión ncalrpc sin terminar, y NVDA lo necesita libre: al arrancar,
	NVDA cierra el proceso dueño de la ventana «NVDA» (el auxiliar) y
	Tiresias, además, lo cierra en cuanto ve aparecer NVDA. Nunca se arranca
	mientras NVDA está en ejecución ni con Tiresias en espera.
	"""
	global _helper, _helperOptions, _nvdaBusyLogged
	window, serve = _wantedHelper()
	want = window or serve
	with _helperLock:
		alive = _helper is not None and _helper.poll() is None
		if alive:
			_nvdaBusyLogged = False
		if _helper is not None and not alive:
			code = _helper.returncode
			if code == 4:
				if not _nvdaBusyLogged:
					log.info("El punto de conexión de NVDA está ocupado (probablemente NVDA está en ejecución). Se reintentará.")
					_nvdaBusyLogged = True
			elif code not in (0, 1, None):
				log.warning("El auxiliar de compatibilidad con NVDA terminó con el código %s", code)
			_helper = None
	if alive and (not want or _helperOptions != (window, serve) or _nvdaRunning()):
		_stopWindow()
		alive = False
	if not want or alive:
		return
	if _nvdaRunning():
		# NVDA tiene su propia ventana y su punto de conexión: no se le quitan.
		return
	path = _windowHelperPath()
	if not os.path.isfile(path):
		log.warning("No se encuentra %s", path)
		return
	import subprocess

	args = [path, str(_ownPid)]
	if window:
		args.append("/window")
	if serve:
		args += ["/serve", NVDA_PREFIX + _server.namespace, TIRESIAS_PREFIX + _server.namespace]
	try:
		proc = subprocess.Popen(args, close_fds=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
	except OSError:
		log.exception("No se pudo iniciar %s", path)
		return
	if serve:
		_server.setRelayPid(proc.pid)
	with _helperLock:
		_helper = proc
		_helperOptions = (window, serve)
	log.info("Auxiliar de compatibilidad con NVDA iniciado (PID %d; ventana: %s; punto de conexión de NVDA: %s)", proc.pid, window, serve)


def _stopWindow() -> None:
	"""Cierra el auxiliar: la ventana «NVDA» desaparece y el punto de conexión queda libre."""
	global _helper
	with _helperLock:
		proc, _helper = _helper, None
	if _server is not None:
		_server.setRelayPid(0)
	if proc is None or proc.poll() is not None:
		return
	try:
		proc.terminate()
		proc.wait(2)
		log.info("Auxiliar de compatibilidad con NVDA cerrado (PID %d)", proc.pid)
	except Exception:
		log.debug("No se pudo cerrar el auxiliar de compatibilidad", exc_info=True)


def releaseNvdaEndpoint(reason: str = "") -> bool:
	"""Suelta al instante el punto de conexión de NVDA (cualquier hilo).

	Lo llama la vigilancia de lectores en cuanto ve arrancar NVDA, para que
	NVDA pueda abrir su punto de conexión. Devuelve ``True`` si había auxiliar.
	"""
	if _helper is None or _helper.poll() is not None:
		return False
	log.info("Se suelta el punto de conexión de NVDA%s", f" ({reason})" if reason else "")
	_stopWindow()
	return True


def hasNvdaWindow() -> bool:
	h = _helper
	return h is not None and h.poll() is None and _helperOptions[0]


def _periodicCheck() -> None:
	"""Repone el auxiliar si hace falta (por ejemplo, cuando NVDA se cierra)."""
	global _nvdaRetryTimer
	_nvdaRetryTimer = None
	if not _initialized:
		return
	_updateWindow()
	_nvdaRetryTimer = queue_handler.callLater(RETRY_NVDA_MS, _periodicCheck)


# ------------------------------------------------------------------ ciclo de vida
def isServingNvda() -> bool:
	h = _helper
	return h is not None and h.poll() is None and _helperOptions[1]


def isServingTiresias() -> bool:
	return _server is not None and _server.isListening(TIRESIAS_PREFIX)


def applyConfiguration() -> None:
	"""Aplica las opciones (hilo del núcleo)."""
	if not _initialized:
		return
	_updateWindow()


def initialize() -> None:
	"""Arranca el servidor (hilo del núcleo)."""
	global _server, _initialized
	if _initialized:
		return
	registerDefaults()
	from .. import speech
	from ..synth import base as synthBase

	speech.pre_speech.register(_onPreSpeech)
	speech.pre_speechCanceled.register(_onSpeechStopped)
	synthBase.synthDoneSpeaking.register(_onSpeechStopped)
	server = ControllerServer(TiresiasHandlers())
	try:
		status = server.start()
	except OSError:
		log.exception("No se pudo cargar el servidor de la API de control")
		return
	if status != RPC_S_OK:
		return
	_server = server
	_initialized = True
	st = server.listen(TIRESIAS_PREFIX)
	if st != RPC_S_OK:
		log.warning("No se pudo abrir el punto de conexión de Tiresias (estado %d)", st)
	_periodicCheck()


def terminate() -> None:
	global _server, _initialized, _nvdaRetryTimer
	if _nvdaRetryTimer is not None:
		queue_handler.cancelCallLater(_nvdaRetryTimer)
		_nvdaRetryTimer = None
	_initialized = False
	_stopWindow()
	if _server is not None:
		_server.stop()
	_server = None
	try:
		from .. import speech
		from ..synth import base as synthBase

		speech.pre_speech.unregister(_onPreSpeech)
		speech.pre_speechCanceled.unregister(_onSpeechStopped)
		synthBase.synthDoneSpeaking.unregister(_onSpeechStopped)
	except Exception:
		pass


def statusText() -> str:
	"""Resumen del estado para la orden de información y el panel."""
	from ..i18n import _

	if not _initialized or _server is None:
		return _("La API de control no está disponible (falta la biblioteca nativa o no se pudo iniciar).")
	parts = []
	if not _conf()["enabled"]:
		parts.append(_("La API de control está desactivada."))
	elif _inStandby():
		parts.append(_("La API de control está en espera: Tiresias cede ante otro lector de pantalla y los programas hablan con ese lector."))
	else:
		parts.append(_("La API de control está activa."))
	if _muted:
		parts.append(_("Los programas externos están silenciados."))
	# Con la API desactivada no hay compatibilidad con NVDA (ni se reintenta).
	if _conf()["enabled"] and _conf()["nvdaCompatible"]:
		if isServingNvda():
			parts.append(_("Compatibilidad con NVDA: activa."))
		elif _nvdaRunning():
			parts.append(_("Compatibilidad con NVDA: en espera (NVDA está en ejecución)."))
		elif not _inStandby():
			parts.append(_("Compatibilidad con NVDA: no disponible por ahora (se reintentará)."))
	clients = getClients()
	if clients:
		parts.append(_("Programas en esta sesión: {names}.").format(names=", ".join(f"{c.name} ({c.calls})" for c in clients[:8])))
	else:
		parts.append(_("Ningún programa la ha usado en esta sesión."))
	return " ".join(parts)
