"""Protección de la pantalla de bloqueo de Windows (Windows+L).

Con la sesión bloqueada, la copia de Tiresias del usuario sigue funcionando
para leer la pantalla de bloqueo, pero nadie debe poder usarla para ver lo
que hay detrás sin desbloquear el equipo (como el modo de pantalla de
bloqueo de NVDA, ``utils.security.getSafeScripts``):

- :func:`filterScript` (lo llama ``InputManager.findScript``): solo se
  ejecutan las órdenes de una lista blanca (foco, navegación de objetos y
  revisión, braille, ratón, ajustes de voz, lupa, hora y batería). Las demás
  (menú, consola de Python, historiales de voz y del portapapeles, leer el
  portapapeles, OCR, IA...) no se ejecutan: la tecla pasa a Windows.
- :func:`allowGuiCall` (lo llama ``gui.helpers.runOnGui``): no se abren
  ventanas; sí se permite cerrar u ocultar y lo que necesitan la lupa, el
  resaltado, la cortina y la convivencia.
- :func:`startMonitor` (en el hilo de la interfaz): oculta el visor de voz, el
  visor braille y la consola de Python al bloquear y los vuelve a mostrar al
  desbloquear.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from .log import getLogger

log = getLogger("lockGuard")

#: Órdenes globales permitidas con la sesión bloqueada (nombre sin ``script_``).
SAFE_SCRIPTS = frozenset(
	{
		"reportCurrentFocus",
		"title",
		"speakForeground",
		"reportCurrentLine",
		"reportCurrentSelection",
		"sayAll",
		"dateTime",
		"sayBatteryStatus",
		"toggleInputHelp",
		"speechMode",
		"cycleSpeechSymbolLevel",
		"increaseSynthSetting",
		"decreaseSynthSetting",
		"increaseLargeSynthSetting",
		"decreaseLargeSynthSetting",
		"nextSynthSetting",
		"previousSynthSetting",
		"firstValueSynthRing",
		"lastValueSynthRing",
		"leftMouseClick",
		"rightMouseClick",
		"moveMouseToNavigatorObject",
		"moveNavigatorObjectToMouse",
		"mouseScrollUp",
		"mouseScrollDown",
		"mouseScrollLeft",
		"mouseScrollRight",
		"caretPos_currentDimensions",
		"reportFocusObjectLocation",
		"reportCurrentNavigatorObjectLocation",
		"reportReviewCursorLocation",
		"reportCaretLocation",
		"toggleMagnifier",
		"magnifierZoomIn",
		"magnifierZoomOut",
		"magnifierPanLeft",
		"magnifierPanRight",
		"magnifierPanUp",
		"magnifierPanDown",
		"magnifierLeftEdge",
		"magnifierRightEdge",
		"magnifierTopEdge",
		"magnifierBottomEdge",
		"magnifierInvertColors",
		"toggleScreenCurtain",
		"reportScreenCurtainState",
		"toggleFocusHighlight",
	}
)
#: Prefijos permitidos (navegación de objetos, revisión y braille).
SAFE_PREFIXES = ("navigatorObject_", "review_", "reviewMode_", "braille_")
#: Dentro de los prefijos, las que copian al portapapeles no se permiten.
UNSAFE_NAMES = frozenset({"review_copy", "review_markStartForCopy", "review_moveToStartMarkedForCopy"})

#: Módulos cuyas tareas de interfaz se permiten con la sesión bloqueada.
GUI_SAFE_MODULES = (
	"tiresias.magnifier",
	"tiresias.vision",
	"tiresias.gui.highlighter",
	"tiresias.coexist.ui",
	"tiresias.lock_guard",
)
#: Nombres de tareas de interfaz que solo cierran, ocultan o actualizan ventanas ya abiertas.
GUI_SAFE_NAMES = frozenset(
	{"_close", "close", "_hide", "hide", "_destroy", "destroy", "_exit", "exitMainLoop", "_update", "update", "_sync", "updateState", "_unregisterHotkey"}
)

_lastAnnounce = 0.0


def isLocked() -> bool:
	"""``True`` con la pantalla de bloqueo activa (nunca lanza excepciones)."""
	try:
		from .a11y import system

		return bool(system.isLockScreenActive())
	except Exception:
		log.debug("No se pudo saber si la sesión está bloqueada", exc_info=True)
		return False


def _scriptName(func: Any) -> str:
	name = getattr(func, "__name__", "") or ""
	return name[7:] if name.startswith("script_") else name


def _ownerIsLockScreen(func: Any) -> bool:
	"""Órdenes de un objeto o módulo de aplicación de la propia pantalla de bloqueo."""
	owner = getattr(func, "__self__", None)
	pid = getattr(owner, "processID", 0) if owner is not None else 0
	if not pid:
		return False
	try:
		from . import winapi
		from .a11y import system

		return winapi.getProcessName(int(pid)) in system.LOCK_SCREEN_PROCESSES
	except Exception:
		return False


def isScriptAllowedWhenLocked(func: Callable) -> bool:
	if func is None:
		return True
	if getattr(func, "allowOnLockScreen", False):
		return True
	name = _scriptName(func)
	if name in UNSAFE_NAMES:
		return False
	if name in SAFE_SCRIPTS or name.startswith(SAFE_PREFIXES):
		return True
	return _ownerIsLockScreen(func)


def _announceBlocked() -> None:
	global _lastAnnounce
	now = time.monotonic()
	if now - _lastAnnounce < 2.0:
		return
	_lastAnnounce = now
	try:
		from . import queue_handler, speech
		from .i18n import _

		queue_handler.queueFunction(speech.speakMessage, _("No disponible con el equipo bloqueado"))
	except Exception:
		pass


def filterScript(func: Callable | None, locked: Callable[[], bool] | None = None) -> Callable | None:
	"""Devuelve ``func`` o ``None`` si la sesión está bloqueada y la orden no es segura.

	Solo consulta el bloqueo cuando hay una orden (las teclas normales no pagan nada).
	"""
	if func is None:
		return None
	try:
		if not (locked or isLocked)():
			return func
		if isScriptAllowedWhenLocked(func):
			return func
	except Exception:
		log.debug("Error comprobando la orden con la sesión bloqueada", exc_info=True)
		return func
	log.info("Orden %s bloqueada: sesión bloqueada", _scriptName(func))
	_announceBlocked()
	return None


def allowGuiCall(func: Callable, locked: Callable[[], bool] | None = None) -> bool:
	"""``False`` si con la sesión bloqueada ``func`` podría abrir una ventana."""
	try:
		if not (locked or isLocked)():
			return True
	except Exception:
		return True
	if getattr(func, "allowOnLockScreen", False):
		return True
	target = getattr(func, "__func__", func)
	module = getattr(target, "__module__", "") or ""
	if module.startswith(GUI_SAFE_MODULES):
		return True
	qual = getattr(target, "__qualname__", "") or getattr(target, "__name__", "")
	if qual.rsplit(".", 1)[-1] in GUI_SAFE_NAMES:
		return True
	log.info("Ventana no abierta con la sesión bloqueada: %s.%s", module, qual)
	return False


# ------------------------------------------------------------------ visores
#: Ventanas ocultadas al bloquear (se vuelven a mostrar al desbloquear).
_hidden: list[Any] = []
_lockedState = False
_timer = None
CHECK_MS = 1000


def _viewerWindows() -> list[Any]:
	out = []
	for modName in ("speech_viewer", "braille_viewer", "python_console"):
		try:
			import importlib

			mod = importlib.import_module(f"tiresias.gui.{modName}")
			win = getattr(mod, "_frame", None)
			if win is not None and win.IsShown():
				out.append(win)
		except Exception:
			continue
	return out


def onLockStateChanged(locked: bool) -> None:
	"""Oculta (al bloquear) o vuelve a mostrar (al desbloquear) los visores. Hilo de la interfaz."""
	global _hidden
	if locked:
		for win in _viewerWindows():
			try:
				win.Hide()
				_hidden.append(win)
			except Exception:
				pass
		if _hidden:
			log.info("Sesión bloqueada: %d ventanas ocultas", len(_hidden))
		return
	windows, _hidden = _hidden, []
	for win in windows:
		try:
			if win and not win.IsBeingDeleted():
				win.ShowWithoutActivating()
		except Exception:
			pass


def _check() -> None:
	global _lockedState
	locked = isLocked()
	if locked != _lockedState:
		_lockedState = locked
		onLockStateChanged(locked)


def startMonitor() -> None:
	"""Vigila el bloqueo de la sesión (hilo de la interfaz, tras crear la ventana principal)."""
	global _timer
	try:
		from .config import policy

		if policy.policy.secureMode:
			# Los cuadros de archivos de wx se protegen ahora que wx está cargado.
			from . import secure_env

			secure_env.installSecureModeGuards()
	except Exception:
		log.debug("No se pudieron instalar las guardas del modo seguro", exc_info=True)
	if _timer is not None:
		return
	try:
		import wx

		_timer = wx.Timer()
		_timer.Bind(wx.EVT_TIMER, lambda evt: _check())
		_timer.Start(CHECK_MS)
	except Exception:
		log.exception("No se pudo vigilar el bloqueo de la sesión")
		_timer = None


def stopMonitor() -> None:
	global _timer
	if _timer is not None:
		try:
			_timer.Stop()
		except Exception:
			pass
		_timer = None
