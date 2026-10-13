"""Registro (log) de Tiresias.

Usa el módulo ``logging`` estándar con un archivo rotativo en ``data/logs`` y
un búfer en memoria para el visor de registro.
"""

from __future__ import annotations

import atexit
import collections
import logging
import logging.handlers
import os
import queue
import sys
import threading
import time

from . import paths

log = logging.getLogger("tiresias")

_memoryBuffer: collections.deque[str] = collections.deque(maxlen=5000)
_bufferLock = threading.Lock()
#: Número total de mensajes guardados desde el arranque (no se reinicia
#: aunque el búfer descarte los antiguos) y marca para copiar un fragmento.
_totalMessages = 0
_markPosition: int | None = None


class _MemoryHandler(logging.Handler):
	def emit(self, record: logging.LogRecord) -> None:
		global _totalMessages
		try:
			msg = self.format(record)
		except Exception:
			return
		with _bufferLock:
			_memoryBuffer.append(msg)
			_totalMessages += 1


class _ErrorSoundHandler(logging.Handler):
	"""Sonido «error» cuando se registra un error (opción ``advanced.playErrorSound``).

	Como en NVDA: cualquier error del registro, no solo los de las órdenes. El
	sonido se encola en el núcleo (nunca bloquea al hilo que registra) y se
	reproduce como mucho una vez cada :data:`MIN_INTERVAL` segundos.
	"""

	MIN_INTERVAL = 1.0

	def __init__(self) -> None:
		super().__init__(logging.ERROR)
		self._last = 0.0
		self._busy = threading.local()

	def emit(self, record: logging.LogRecord) -> None:
		if getattr(self._busy, "on", False):
			return
		self._busy.on = True
		try:
			now = time.monotonic()
			if now - self._last < self.MIN_INTERVAL or not _errorSoundWanted():
				return
			self._last = now
			from . import queue_handler

			queue_handler.queueFunction(_playErrorSound)
		except Exception:
			pass
		finally:
			self._busy.on = False


def _errorSoundWanted() -> bool:
	try:
		from .config import conf

		return bool(conf["advanced"]["playErrorSound"])
	except Exception:
		return False


def _playErrorSound() -> None:
	try:
		from .audio import tones

		tones.playSound("error")
	except Exception:
		# Sin registrar el error: volvería a sonar.
		pass


def getLogText() -> str:
	with _bufferLock:
		return "\n".join(_memoryBuffer)


def markStart() -> None:
	"""Marca la posición actual del registro (para copiar un fragmento)."""
	global _markPosition
	with _bufferLock:
		_markPosition = _totalMessages


def hasMark() -> bool:
	return _markPosition is not None


def clearMark() -> None:
	global _markPosition
	_markPosition = None


def getTextSinceMark() -> str:
	"""Mensajes registrados desde :func:`markStart` (todo el búfer si no hay marca)."""
	with _bufferLock:
		items = list(_memoryBuffer)
		total = _totalMessages
	mark = _markPosition if _markPosition is not None else total - len(items)
	# Índice en el búfer: los mensajes más antiguos pueden haberse descartado.
	start = max(0, len(items) - (total - mark))
	return "\n".join(items[start:])


LEVELS = {
	"DEBUG": logging.DEBUG,
	"INFO": logging.INFO,
	"WARNING": logging.WARNING,
	"ERROR": logging.ERROR,
	"CRITICAL": logging.CRITICAL,
	# Registro desactivado (como «desactivado» en NVDA; también al importar su configuración).
	"OFF": logging.CRITICAL + 10,
}


#: Escritor del archivo de registro en su propio hilo (ver :func:`initialize`).
_listener: logging.handlers.QueueListener | None = None
_fileQueue: "queue.Queue[logging.LogRecord] | None" = None


def _stopListener() -> None:
	"""Escribe lo pendiente en el archivo y detiene su hilo (idempotente)."""
	global _listener
	listener = _listener
	_listener = None
	if listener is None:
		return
	try:
		listener.stop()
	except Exception:
		pass
	for h in listener.handlers:
		try:
			h.close()
		except Exception:
			pass


# Al salir, antes del ``logging.shutdown`` que registra el propio ``logging``
# (``atexit`` llama a las funciones en orden inverso).
atexit.register(_stopListener)


def flush(timeout: float = 2.0) -> None:
	"""Espera (como mucho ``timeout`` s) a que el archivo tenga todo lo registrado.

	Para los cierres de emergencia y los fallos graves (``crash_log``), en los
	que el proceso termina sin pasar por :func:`shutdown`.
	"""
	q = _fileQueue
	if q is None or _listener is None:
		return
	deadline = time.monotonic() + timeout
	while getattr(q, "unfinished_tasks", 0) and time.monotonic() < deadline:
		time.sleep(0.01)


def shutdown() -> None:
	"""Vacía la cola del registro y cierra el archivo (salida del proceso)."""
	_stopListener()
	logging.shutdown()


#: Carpeta donde se escribe de verdad el registro (``None`` si no hay archivo).
_activeLogsDir: str | None = None
#: Carpeta de registro alternativa usada porque ``data\\logs`` no admite escritura.
fallbackLogsDir: str | None = None


def fallbackLogsDirCandidate() -> str:
	"""Carpeta alternativa si la de datos no se puede escribir (``%TEMP%\\Tiresias\\logs``)."""
	import tempfile

	return os.path.join(tempfile.gettempdir(), "Tiresias", "logs")


def logsDir() -> str:
	"""Carpeta del registro en uso (la de datos o, si no se podía escribir, la alternativa)."""
	return _activeLogsDir or paths.logsDir()


def _openLogFile(folder: str, fmt: logging.Formatter) -> logging.Handler:
	"""Crea la carpeta y abre ``tiresias.log`` en ella (lanza ``OSError`` si no se puede)."""
	os.makedirs(folder, exist_ok=True)
	fh = logging.handlers.RotatingFileHandler(
		os.path.join(folder, "tiresias.log"),
		maxBytes=2 * 1024 * 1024,
		backupCount=3,
		encoding="utf-8",
	)
	fh.setFormatter(fmt)
	return fh


class _ForwardHandler(logging.Handler):
	"""Lleva al registro de Tiresias los avisos de bibliotecas (comtypes...).

	Sin esto se perdían: el registrador raíz no tiene manejadores y, en el
	ejecutable sin consola, ``sys.stderr`` es ``None``.
	"""

	def emit(self, record: logging.LogRecord) -> None:
		try:
			log.handle(record)
		except Exception:
			pass


#: Bibliotecas cuyos avisos (WARNING o más) se copian al registro de Tiresias.
FORWARDED_LIBRARIES = ("comtypes",)


def _forwardLibraryLogs() -> None:
	for name in FORWARDED_LIBRARIES:
		lib = logging.getLogger(name)
		for h in list(lib.handlers):
			if isinstance(h, _ForwardHandler):
				lib.removeHandler(h)
		fwd = _ForwardHandler(logging.WARNING)
		lib.addHandler(fwd)
		if lib.level == logging.NOTSET or lib.level > logging.WARNING:
			lib.setLevel(logging.WARNING)


def _unraisableHook(unraisable) -> None:
	"""Excepciones «ignoradas» (retrollamadas de ctypes, ``__del__``...): al registro."""
	try:
		try:
			obj = repr(unraisable.object)
		except Exception:
			obj = "?"
		msg = getattr(unraisable, "err_msg", None) or "Excepción ignorada"
		log.error(
			"%s: %s",
			msg,
			obj[:300],
			exc_info=(unraisable.exc_type, unraisable.exc_value, unraisable.exc_traceback) if unraisable.exc_type else None,
		)
	except Exception:
		pass


def initialize(level: str = "INFO", toConsole: bool = False) -> None:
	global _listener, _fileQueue, _activeLogsDir, fallbackLogsDir
	fmt = logging.Formatter(
		"%(asctime)s %(levelname)s [%(threadName)s] %(name)s.%(funcName)s:%(lineno)d: %(message)s"
	)
	log.setLevel(LEVELS.get(level.upper(), logging.INFO))
	_stopListener()
	for h in log.handlers:
		try:
			h.close()
		except Exception:
			pass
	log.handlers.clear()
	_activeLogsDir = None
	fallbackLogsDir = None
	# Si la carpeta de datos no admite escritura (copia portable en Archivos de
	# programa sin elevar, memoria USB de solo lectura...) no se deja de
	# arrancar: el registro va a una carpeta temporal y se avisa al usuario.
	fh = None
	for folder in (paths.logsDir(), fallbackLogsDirCandidate()):
		try:
			fh = _openLogFile(folder, fmt)
		except OSError:
			continue
		_activeLogsDir = folder
		if folder != paths.logsDir():
			fallbackLogsDir = folder
		break
	if fh is not None:
		# El archivo se escribe en un hilo propio: escribir en disco (y rotar el
		# archivo) puede tardar segundos si el disco está ocupado o un antivirus
		# lo examina, y no debe bloquear el hilo del núcleo ni los ganchos de
		# teclado (el vigilante llegó a ver el núcleo 6 s parado en ``tell()``).
		_fileQueue = queue.Queue()
		log.addHandler(logging.handlers.QueueHandler(_fileQueue))
		_listener = logging.handlers.QueueListener(_fileQueue, fh)
		_listener.start()
	mh = _MemoryHandler()
	mh.setFormatter(fmt)
	log.addHandler(mh)
	log.addHandler(_ErrorSoundHandler())
	if toConsole and sys.stderr:
		sh = logging.StreamHandler(sys.stderr)
		sh.setFormatter(fmt)
		log.addHandler(sh)
	log.propagate = False

	def _excepthook(excType, value, tb):
		log.critical("Excepción no controlada", exc_info=(excType, value, tb))
		try:
			# DLL bloqueada por Smart App Control o WDAC: se explica al usuario.
			from . import app_control

			if app_control.isBlockedError(value):
				app_control.report(value, log)
		except Exception:
			pass

	sys.excepthook = _excepthook

	def _threadExcepthook(args):
		log.error(
			"Excepción no controlada en el hilo %s",
			args.thread.name if args.thread else "?",
			exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
		)

	threading.excepthook = _threadExcepthook
	# Errores en retrollamadas de ctypes (ganchos, WinEvents, ventanas propias)
	# y en finalizadores: Python los manda aquí y no a sys.excepthook.
	sys.unraisablehook = _unraisableHook
	_forwardLibraryLogs()


def setLevel(level: str) -> None:
	log.setLevel(LEVELS.get(level.upper(), logging.INFO))


def getLogger(name: str) -> logging.Logger:
	"""Devuelve un registrador hijo (``tiresias.<name>``)."""
	return log.getChild(name)


#: Categorías de depuración -> registradores afectados.
DEBUG_CATEGORIES = {
	"eventos": ("events", "uiaHandler", "winEvents"),
	"entrada": ("inputCore", "hooks", "gestures"),
	"voz": ("speech", "sayAll", "symbols", "speechDict"),
	"uia": ("uia", "uiaObjects", "uiaText", "uiaHandler"),
	"exploracion": ("browseMode", "vbuf"),
	"sintetizador": ("synth", "synthHandler", "espeak", "sapi5", "onecore", "eloquence", "audio"),
	"braille": ("braille", "brailleTables"),
	"complementos": ("addons", "appModuleHandler", "pluginHandler", "appModule"),
	"ocr": ("ocr",),
}
_ALIASES = {
	"events": "eventos",
	"input": "entrada",
	"speech": "voz",
	"browse": "exploracion",
	"exploración": "exploracion",
	"synth": "sintetizador",
	"addons": "complementos",
}


def applyDebugCategories(categories: list[str]) -> None:
	"""Activa el registro detallado solo de ciertas partes del lector."""
	for names in DEBUG_CATEGORIES.values():
		for n in names:
			log.getChild(n).setLevel(logging.NOTSET)
	if isinstance(categories, str):
		categories = categories.split(",")
	if not isinstance(categories, (list, tuple, set)):
		categories = []
	for cat in categories:
		if not isinstance(cat, str):
			# Valor no válido escrito a mano en config.json: se ignora.
			continue
		key = _ALIASES.get(cat.strip().lower(), cat.strip().lower())
		for n in DEBUG_CATEGORIES.get(key, ()):
			log.getChild(n).setLevel(logging.DEBUG)
