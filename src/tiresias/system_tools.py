"""Herramientas de sistema: bandeja del sistema, ventanas abiertas y procesos.

- :func:`listTrayIcons` enumera los iconos del área de notificación (también
  los ocultos, abriendo un momento el desplegable «Mostrar iconos ocultos») y
  :func:`activateTrayIcon` los pulsa con clic izquierdo, derecho o doble.
- :func:`listWindows` enumera las ventanas de nivel superior visibles y
  :func:`switchToWindow` / :func:`closeWindow` actúan sobre ellas.
- :func:`listProcesses` enumera los procesos (con memoria, uso de CPU y la
  ventana principal) y :func:`endProcess` los finaliza.

Las funciones que tocan objetos accesibles se ejecutan en el hilo del núcleo;
las listas de ventanas y procesos se pueden pedir desde cualquier hilo.
"""

from __future__ import annotations

import ctypes
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import winapi
from .i18n import _
from .log import getLogger

log = getLogger("systemTools")

#: Procesos que no se deben finalizar nunca desde la lista.
CRITICAL_PROCESSES = {
	"system",
	"registry",
	"smss",
	"csrss",
	"wininit",
	"winlogon",
	"services",
	"lsass",
	"lsaiso",
	"fontdrvhost",
	"dwm",
	"memory compression",
	"secure system",
	"system idle process",
}


# ================================================================ bandeja del sistema
@dataclass
class TrayIcon:
	name: str
	hidden: bool = False
	#: Identificador para volver a encontrar el icono (nombre normalizado).
	key: str = ""
	element: Any = None

	@property
	def label(self) -> str:
		text = " ".join(self.name.split())
		return _("{name} (oculto)").format(name=text) if self.hidden else text


#: AutomationId de los iconos de la bandeja en Windows 11.
_TRAY_AIDS = ("NotifyItemIcon",)
#: Botones del sistema que no son iconos de aplicaciones.
_TRAY_SYSTEM_AIDS = ("SystemTrayIcon",)
_OVERFLOW_CLASSES = ("TopLevelWindowForOverflowXamlIsland", "NotifyIconOverflowWindow")


def _normalizeKey(name: str) -> str:
	return " ".join(name.split()).lower()


def _uiaObjects(root, maxDepth: int = 8) -> list:
	"""Recorre el árbol de control de ``root`` (objeto UIA) hasta ``maxDepth``."""
	out: list = []

	def walk(obj, depth: int) -> None:
		if depth > maxDepth or len(out) > 600:
			return
		for child in obj.children:
			out.append(child)
			walk(child, depth + 1)

	try:
		walk(root, 0)
	except Exception:
		log.debug("Error recorriendo la bandeja", exc_info=True)
	return out


def isTrayIconObject(obj) -> bool:
	"""``True`` si el objeto es un icono de aplicación del área de notificación."""
	from .objects.roles import Role

	try:
		if obj.role not in (Role.BUTTON, Role.MENUITEM, Role.TOGGLEBUTTON):
			return False
		aid = getattr(obj, "UIAAutomationId", "")
		if aid in _TRAY_AIDS:
			return True
		# Windows 10: botones de la barra de herramientas de la bandeja.
		cls = winapi.getClassName(obj.windowHandle)
		if cls == "ToolbarWindow32":
			parent = winapi.user32.GetParent(obj.windowHandle)
			pcls = winapi.getClassName(parent)
			return pcls in ("SysPager", "NotifyIconOverflowWindow", "TrayNotifyWnd")
	except Exception:
		return False
	return False


def _findWindow(className: str) -> int:
	fn = winapi.user32.FindWindowW
	fn.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
	fn.restype = ctypes.c_void_p
	return int(fn(className, None) or 0)


def _trayRoot():
	from .objects.uia import getObjectFromHandle

	h = _findWindow("Shell_TrayWnd")
	return getObjectFromHandle(h) if h else None


def _overflowButton(objs: list):
	"""Botón «Mostrar iconos ocultos» (chevron) de la bandeja."""
	for o in objs:
		try:
			aid = getattr(o, "UIAAutomationId", "")
			cls = getattr(o, "UIAClassName", "")
			if aid in _TRAY_SYSTEM_AIDS and cls == "SystemTray.NormalButton":
				return o
			if aid == "1502":  # Windows 10: «Mostrar iconos ocultos».
				return o
		except Exception:
			continue
	return None


def _findOverflowWindow() -> int:
	found: list[int] = []

	def enum(hwnd, lParam):
		if winapi.getClassName(hwnd) in _OVERFLOW_CLASSES and winapi.user32.IsWindowVisible(hwnd):
			found.append(hwnd)
			return False
		return True

	winapi.user32.EnumWindows(winapi.WNDENUMPROC(enum), 0)
	return found[0] if found else 0


def _overflowIcons() -> list:
	from .objects.uia import getObjectFromHandle

	hwnd = _findOverflowWindow()
	if not hwnd:
		return []
	root = getObjectFromHandle(hwnd)
	if root is None:
		return []
	return [o for o in _uiaObjects(root) if isTrayIconObject(o) and o.name]


def listVisibleTrayIcons() -> list[TrayIcon]:
	root = _trayRoot()
	if root is None:
		return []
	icons = []
	for o in _uiaObjects(root):
		if isTrayIconObject(o) and o.name:
			icons.append(TrayIcon(o.name, False, _normalizeKey(o.name), o))
	return icons


def openOverflow() -> bool:
	"""Abre el desplegable de iconos ocultos. Devuelve ``True`` si se pudo."""
	if _findOverflowWindow():
		return True
	root = _trayRoot()
	if root is None:
		return False
	btn = _overflowButton(_uiaObjects(root, 3))
	if btn is None:
		return False
	try:
		return bool(btn.doAction())
	except Exception:
		return False


def closeOverflow() -> None:
	hwnd = _findOverflowWindow()
	if hwnd:
		root = _trayRoot()
		btn = _overflowButton(_uiaObjects(root, 3)) if root is not None else None
		if btn is not None:
			try:
				btn.doAction()
				return
			except Exception:
				pass
		winapi.user32.ShowWindow(hwnd, winapi.SW_HIDE)


def listTrayIcons(includeHidden: bool = True, waitSeconds: float = 0.6) -> list[TrayIcon]:
	"""Iconos de la bandeja (versión síncrona, para pruebas y herramientas).

	En el hilo del núcleo se debe usar :func:`collectTrayIcons`, que no espera.
	"""
	icons = listVisibleTrayIcons()
	if includeHidden:
		wasOpen = bool(_findOverflowWindow())
		if wasOpen or openOverflow():
			deadline = time.monotonic() + waitSeconds
			hidden: list = []
			while time.monotonic() < deadline:
				hidden = _overflowIcons()
				if hidden:
					break
				time.sleep(0.05)
			_mergeHidden(icons, hidden)
			if not wasOpen:
				closeOverflow()
	return icons


def _mergeHidden(icons: list[TrayIcon], hidden: list) -> None:
	seen = {i.key for i in icons}
	for o in hidden:
		key = _normalizeKey(o.name)
		if key not in seen:
			seen.add(key)
			icons.append(TrayIcon(o.name, True, key, None))


def collectTrayIcons(callback: Callable[[list[TrayIcon]], None], attempts: int = 8) -> None:
	"""Reúne los iconos (también los ocultos) sin bloquear el núcleo.

	Abre el desplegable de iconos ocultos, espera a que aparezca con
	temporizadores del núcleo, lo cierra y llama a ``callback(iconos)``.
	"""
	from . import queue_handler

	icons = listVisibleTrayIcons()
	wasOpen = bool(_findOverflowWindow())
	if not (wasOpen or openOverflow()):
		callback(icons)
		return
	state = {"left": attempts}

	def poll() -> None:
		hidden = _overflowIcons()
		state["left"] -= 1
		if not hidden and state["left"] > 0:
			queue_handler.callLater(80, poll)
			return
		_mergeHidden(icons, hidden)
		if not wasOpen:
			closeOverflow()
		callback(icons)

	queue_handler.callLater(80, poll)


def activateTrayIcon(icon: TrayIcon, button: str = "left", double: bool = False, callback: Callable[[bool], None] | None = None, attempts: int = 10) -> None:
	"""Pulsa un icono de la bandeja (``left``, ``right`` o doble clic) sin bloquear.

	Si el icono está oculto se abre antes el desplegable. ``callback(ok)``
	recibe si se pudo pulsar.
	"""
	from . import queue_handler

	def done(ok: bool) -> None:
		if callback is not None:
			callback(ok)

	for i in listVisibleTrayIcons():
		if i.key == icon.key:
			done(_click(i.element, button, double))
			return
	if not openOverflow():
		done(False)
		return
	state = {"left": attempts}

	def poll() -> None:
		for o in _overflowIcons():
			if _normalizeKey(o.name) == icon.key:
				done(_click(o, button, double))
				return
		state["left"] -= 1
		if state["left"] > 0:
			queue_handler.callLater(80, poll)
		else:
			done(False)

	queue_handler.callLater(80, poll)


def _click(obj, button: str, double: bool) -> bool:
	from . import mouse

	if obj is None:
		return False
	if button == "left" and not double:
		# La invocación UIA equivale al clic izquierdo y no mueve el ratón.
		try:
			if obj.doAction():
				return True
		except Exception:
			pass
	loc = obj.location
	if not loc:
		return False
	x, y, w, h = loc
	mouse.click(x + w // 2, y + h // 2, button=button, double=double)
	return True


# ================================================================ ventanas
@dataclass
class WindowInfo:
	hwnd: int
	title: str
	processName: str
	pid: int
	minimized: bool = False

	@property
	def label(self) -> str:
		state = _(" (minimizada)") if self.minimized else ""
		return f"{self.title} — {self.processName}{state}"


def listWindows() -> list[WindowInfo]:
	"""Ventanas de nivel superior visibles con título (como Alt+Tab)."""
	windows: list[WindowInfo] = []
	shell = winapi.user32.GetShellWindow()
	ownPid = os.getpid()

	def enum(hwnd, lParam):
		try:
			if hwnd == shell or not winapi.user32.IsWindowVisible(hwnd) or winapi.user32.GetWindow(hwnd, 4):
				return True
			title = winapi.getWindowText(hwnd)
			exStyle = winapi.user32.GetWindowLongW(hwnd, -20)
			if not title or exStyle & 0x80 or title == "Program Manager":
				return True
			if _isCloaked(hwnd):
				return True
			pid = winapi.getWindowProcessId(hwnd)
			if pid == ownPid:
				return True
			windows.append(WindowInfo(hwnd, title, winapi.getProcessName(pid), pid, bool(winapi.user32.IsIconic(hwnd))))
		except Exception:
			pass
		return True

	winapi.user32.EnumWindows(winapi.WNDENUMPROC(enum), 0)
	return windows


def _isCloaked(hwnd: int) -> bool:
	"""Ventanas «encubiertas» (de otro escritorio virtual o aplicaciones suspendidas)."""
	try:
		val = ctypes.c_int(0)
		ctypes.windll.dwmapi.DwmGetWindowAttribute(ctypes.c_void_p(hwnd), 14, ctypes.byref(val), ctypes.sizeof(val))
		return bool(val.value)
	except Exception:
		return False


def switchToWindow(hwnd: int) -> bool:
	if not winapi.user32.IsWindow(hwnd):
		return False
	if winapi.user32.IsIconic(hwnd):
		winapi.user32.ShowWindow(hwnd, winapi.SW_RESTORE)
	return winapi.setForegroundWindow(hwnd)


def closeWindow(hwnd: int) -> bool:
	"""Pide a la ventana que se cierre (como Alt+F4: la aplicación puede preguntar)."""
	if not winapi.user32.IsWindow(hwnd):
		return False
	return bool(winapi.user32.PostMessageW(hwnd, winapi.WM_CLOSE, 0, 0))


# ================================================================ procesos
@dataclass
class ProcessInfo:
	pid: int
	name: str
	memoryMB: float = 0.0
	cpu: float = 0.0
	windowTitle: str = ""
	hwnd: int = 0
	user: str = ""
	extra: dict = field(default_factory=dict)

	@property
	def label(self) -> str:
		parts = [self.name, _("PID {pid}").format(pid=self.pid), _("{mb} MB").format(mb=round(self.memoryMB))]
		if self.cpu >= 0.5:
			parts.append(_("CPU {cpu} %").format(cpu=round(self.cpu)))
		if self.windowTitle:
			parts.append(self.windowTitle)
		return ", ".join(parts)


def _mainWindows() -> dict[int, tuple[int, str]]:
	out: dict[int, tuple[int, str]] = {}
	for w in listWindows():
		out.setdefault(w.pid, (w.hwnd, w.title))
	return out


def listProcesses(sampleSeconds: float = 0.3) -> list[ProcessInfo]:
	"""Procesos del sistema ordenados por nombre (no llamar en el hilo del núcleo)."""
	try:
		import psutil
	except ImportError:
		return []
	procs = []
	for p in psutil.process_iter(["pid", "name", "memory_info"]):
		try:
			p.cpu_percent(None)
			procs.append(p)
		except (psutil.NoSuchProcess, psutil.AccessDenied):
			procs.append(p)
		except Exception:
			continue
	if sampleSeconds:
		time.sleep(sampleSeconds)
	windows = _mainWindows()
	cpuCount = psutil.cpu_count() or 1
	out: list[ProcessInfo] = []
	for p in procs:
		try:
			info = p.info
			name = info.get("name") or ""
			if not name:
				continue
			mem = info.get("memory_info")
			memMB = (mem.rss / (1024 * 1024)) if mem else 0.0
			try:
				cpu = p.cpu_percent(None) / cpuCount
			except Exception:
				cpu = 0.0
			hwnd, title = windows.get(info["pid"], (0, ""))
			out.append(ProcessInfo(info["pid"], os.path.splitext(name)[0], memMB, cpu, title, hwnd))
		except Exception:
			continue
	out.sort(key=lambda i: (i.name.lower(), i.pid))
	return out


def canEndProcess(info: ProcessInfo) -> tuple[bool, str]:
	"""Si se puede finalizar el proceso y, si no, por qué."""
	if info.pid in (0, 4) or info.name.lower() in CRITICAL_PROCESSES:
		return False, _("{name} es un proceso esencial de Windows y no se puede finalizar.").format(name=info.name)
	if info.pid == os.getpid():
		return False, _("Para cerrar Tiresias usa la opción Salir del menú.")
	return True, ""


def endProcess(pid: int, timeout: float = 3.0) -> bool:
	"""Finaliza un proceso (primero amablemente; si no termina, a la fuerza)."""
	try:
		import psutil

		p = psutil.Process(pid)
		p.terminate()
		try:
			p.wait(timeout)
		except psutil.TimeoutExpired:
			p.kill()
			p.wait(timeout)
		return True
	except Exception:
		log.debug("No se pudo finalizar el proceso %d", pid, exc_info=True)
		return False
