"""Elección de la API de accesibilidad para cada ventana: UIA, MSAA/IA2 o Java.

Tiresias usa UI Automation siempre que puede. Algunas ventanas se leen
mejor con MSAA (IAccessible) o IAccessible2, y las aplicaciones Java con
Java Access Bridge. La decisión se toma por ventana y se guarda en caché:

1. Ventanas Java (``SunAwt*``) con Java Access Bridge disponible → ``java``.
2. Clases que el usuario fuerza a UIA (``objects.uiaClasses``) → ``uia``.
3. Clases conocidas cuyo proveedor UIA es peor que MSAA (lista
   ``BAD_UIA_CLASSES`` más ``objects.msaaClasses``), la consola clásica si no se
   prefiere UIA en las consolas y la cinta de Office 2013 o anterior → ``msaa``.
4. Ventanas sin proveedor UIA propio (``UiaHasServerSideProvider``) cuyo
   objeto MSAA implementa IAccessible2 (LibreOffice, Qt, Thunderbird…), si la
   opción ``objects.useIA2`` está activa → ``msaa``. Se excluyen los documentos
   de Chromium y Firefox, porque el modo exploración trabaja con UIA.
5. El resto → ``uia``.

Las ventanas del propio proceso (diálogos de Tiresias) se leen siempre con
MSAA, igual que hace NVDA: UIA dentro del mismo proceso es lento y repite
eventos (ver :mod:`uia_handler`, que descarta los eventos UIA propios).

La caché se puede leer desde cualquier hilo (diccionario de solo lectura
para el hilo de ganchos); solo el hilo del núcleo la rellena.
"""

from __future__ import annotations

import ctypes
import os
import re
import time
from ctypes import wintypes

from ..config import conf
from ..log import getLogger

log = getLogger("apiChoice")

API_UIA = "uia"
API_MSAA = "msaa"
API_JAVA = "java"

user32 = ctypes.windll.user32
user32.IsWindow.argtypes = [wintypes.HWND]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetForegroundWindow.restype = wintypes.HWND

try:
	_uiaCore = ctypes.windll.UIAutomationCore
	_uiaCore.UiaHasServerSideProvider.argtypes = [wintypes.HWND]
	_uiaCore.UiaHasServerSideProvider.restype = wintypes.BOOL
except (OSError, AttributeError):
	_uiaCore = None

#: Clases de ventana cuyo proveedor UIA (casi siempre el puente MSAA del sistema)
#: es peor que leerlas directamente con MSAA.
BAD_UIA_CLASSES = (
	# La ventana de candidatos del IME envía eventos UIA que estorban a los de MSAA.
	"Microsoft.IME.CandidateWindow.View",
	# Listas de detalles: MSAA da cada fila con sus columnas y una selección fiable.
	"SysListView32",
	"WuDuiListView",
	"CommonPlacesWrapperWndClass",
	"SysMonthCal32",
	# Lista de mensajes de Outlook 2010.
	"SUPERGRID",
	# El proveedor UIA de Foxit está incompleto.
	"FoxitDocWnd",
)

#: Documentos web que siempre usan UIA (el modo exploración es UIA).
UIA_DOCUMENT_CLASSES = (
	"Chrome_RenderWidgetHostHWND",
	"Chrome_WidgetWin_0",
	"Chrome_WidgetWin_1",
	"MozillaWindowClass",
	"MozillaDialogClass",
	"MozillaContentWindowClass",
	"MozillaDropShadowWindowClass",
	"Internet Explorer_Server",
)

#: Controles comunes de Windows: el puente UIA del sistema los conoce y
#: nunca implementan IAccessible2 (así no se pregunta por cada uno).
WIN32_COMMON_CLASSES = {
	"button",
	"static",
	"edit",
	"combobox",
	"comboboxex32",
	"listbox",
	"combolbox",
	"scrollbar",
	"systreeview32",
	"systabcontrol32",
	"sysheader32",
	"syslink",
	"toolbarwindow32",
	"rebarwindow32",
	"msctls_statusbar32",
	"msctls_progress32",
	"msctls_trackbar32",
	"msctls_updown32",
	"msctls_hotkey32",
	"tooltips_class32",
	"#32770",
	"richedit20w",
	"richedit50w",
	"directuihwnd",
	"shelldll_defview",
	"windows.ui.core.corewindow",
	"applicationframewindow",
	"shell_traywnd",
	"progman",
	"workerw",
}

#: Menús Win32 clásicos (contextuales, desplegables de la barra, submenús y menú
#: del sistema), de cualquier proceso. Se leen con MSAA, como hace NVDA:
#: - Windows avisa del elemento marcado con EVENT_OBJECT_FOCUS en la propia
#:   ventana del menú, mientras el foco del teclado (``hwndFocus``) sigue en el
#:   control que lo abrió;
#: - UIA no sigue ese foco desde otro proceso: ``GetFocusedElement`` devuelve
#:   el control de debajo (la lista), y si ese control se lee con MSAA
#:   (``SysListView32``: el escritorio, la Papelera, SocialRSS…) sus eventos de
#:   foco UIA se descartaban. Con UIA, los menús sobre una lista no decían nada.
MENU_CLASS = "#32768"

JAVA_CLASS_PREFIX = "SunAwt"

#: hwnd -> (api, clase, instante)
_cache: dict[int, tuple[str, str, float]] = {}
_officeVersionCache: dict[int, int] = {}
_ownPid = os.getpid()


def getClassName(hwnd: int) -> str:
	buf = ctypes.create_unicode_buffer(256)
	if not hwnd or not user32.GetClassNameW(hwnd, buf, 256):
		return ""
	return buf.value


def _pidOf(hwnd: int) -> int:
	pid = wintypes.DWORD()
	user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
	return pid.value


#: GUITHREADINFO.flags: el hilo está en un menú (barra o desplegable) o en un menú emergente.
GUI_INMENUMODE = 0x4
GUI_POPUPMENUMODE = 0x10


def focusWindow(element: object | None = None) -> int:
	"""Ventana del foco en el hilo en primer plano.

	Normalmente es la del foco del teclado (``hwndFocus``). Con un menú Win32
	abierto (barra de menús, contextual, submenú o menú del sistema), el foco
	del teclado sigue en el control que lo abrió, pero lo que tiene el foco es
	un elemento del menú: cuenta el menú desplegado (#32768) y, si solo está
	activa la barra de menús, la ventana de ``element`` (el objeto de un
	evento de foco) o la dueña de la barra.
	"""
	from .. import winapi

	fg = user32.GetForegroundWindow() or 0
	if not fg:
		return 0
	threadId = winapi.getWindowThreadId(fg)
	info = winapi.getGUIThreadInfo(threadId)
	if info is not None and info.flags & (GUI_INMENUMODE | GUI_POPUPMENUMODE):
		menu = activeMenuWindow(threadId)
		if menu:
			# Hay un menú desplegado: el foco está en él (UIA aún avisa a veces del
			# elemento de la barra que lo abrió).
			return menu
		if element is not None:
			try:
				hwnd = int(getattr(element, "windowHandle", 0) or 0)
			except Exception:
				hwnd = 0
			if hwnd:
				return hwnd
		if info.hwndMenuOwner:
			# Solo la barra de menús: sus elementos son de la ventana dueña.
			return int(info.hwndMenuOwner)
	if info is not None and info.hwndFocus:
		return int(info.hwndFocus)
	return int(fg)


_EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def activeMenuWindow(threadId: int) -> int:
	"""Menú Win32 (#32768) visible más alto del hilo, o 0.

	Los submenús quedan por encima del menú del que salen, así que el primero
	en orden Z es el que tiene el elemento marcado.
	"""
	found: list[int] = []

	def cb(hwnd, _lParam):
		if user32.IsWindowVisible(hwnd) and getClassName(hwnd) == MENU_CLASS:
			found.append(int(hwnd))
			return False
		return True

	try:
		user32.EnumThreadWindows(threadId, _EnumProc(cb), 0)
	except Exception:
		return 0
	return found[0] if found else 0


def cachedAPI(hwnd: int) -> str | None:
	"""API ya decidida para ``hwnd`` (sin llamadas; seguro en cualquier hilo)."""
	entry = _cache.get(hwnd)
	return entry[0] if entry else None


def _classList(key: str) -> set[str]:
	try:
		values = conf["objects"][key]
	except KeyError:
		return set()
	return {str(v).strip().lower() for v in values or () if str(v).strip()}


def _officeMajorVersion(pid: int) -> int:
	ver = _officeVersionCache.get(pid)
	if ver is not None:
		return ver
	ver = 0
	try:
		from .. import winapi

		path = winapi.getProcessImagePath(pid)
		if path:
			ver = _fileMajorVersion(path)
	except Exception:
		ver = 0
	_officeVersionCache[pid] = ver
	return ver


def _fileMajorVersion(path: str) -> int:
	version = ctypes.windll.version
	size = version.GetFileVersionInfoSizeW(path, None)
	if not size:
		return 0
	buf = ctypes.create_string_buffer(size)
	if not version.GetFileVersionInfoW(path, 0, size, buf):
		return 0
	ptr = ctypes.c_void_p()
	length = wintypes.UINT()
	if not version.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)) or not ptr.value:
		return 0
	# VS_FIXEDFILEINFO: dwSignature, dwStrucVersion, dwFileVersionMS...
	ms = ctypes.c_uint32.from_address(ptr.value + 8).value
	return ms >> 16


#: ``WindowsForms10.SysListView32.app.0.141b42a_r9_ad1`` es un ``SysListView32``.
_WINFORMS_CLASS = re.compile(r"^WindowsForms\d*\.(.+?)\.app\.")


def normalizeClassName(className: str) -> str:
	"""Clase real de un control de Windows Forms o ATL (NVDA #21051, #20891)."""
	m = _WINFORMS_CLASS.match(className)
	if m:
		return m.group(1)
	return className[4:] if className.startswith("ATL:") else className


def isJavaWindowClass(className: str) -> bool:
	return className.startswith(JAVA_CLASS_PREFIX)


def _decide(hwnd: int, className: str) -> str:
	className = normalizeClassName(className)
	lower = className.lower()
	if isJavaWindowClass(className):
		try:
			from . import jab

			if jab.isJavaWindow(hwnd):
				return API_JAVA
		except Exception:
			log.debug("Error consultando Java Access Bridge", exc_info=True)
	if lower in _classList("uiaClasses"):
		return API_UIA
	if className in BAD_UIA_CLASSES or className == MENU_CLASS or lower in _classList("msaaClasses"):
		return API_MSAA
	if className == "ConsoleWindowClass" and not conf["uia"]["preferUIAForConsoles"]:
		return API_MSAA
	if className == "NetUIHWND":
		# La cinta de Office 2013 y anteriores funciona mejor con MSAA.
		major = _officeMajorVersion(_pidOf(hwnd))
		if 0 < major <= 15:
			return API_MSAA
	if className in UIA_DOCUMENT_CLASSES or lower in WIN32_COMMON_CLASSES:
		return API_UIA
	try:
		useIA2 = conf["objects"]["useIA2"]
	except KeyError:
		useIA2 = True
	if useIA2 and _uiaCore is not None:
		try:
			native = bool(_uiaCore.UiaHasServerSideProvider(hwnd))
		except Exception:
			native = True
		if not native and _supportsIA2(hwnd):
			return API_MSAA
	return API_UIA


def _supportsIA2(hwnd: int) -> bool:
	from . import msaa

	acc = msaa.accessibleObjectFromWindow(hwnd)
	if acc is None:
		return False
	return msaa.queryIAccessible2(acc) is not None


def chooseAPI(hwnd: int) -> str:
	"""API que se usa para ``hwnd`` (en el hilo del núcleo)."""
	if not hwnd:
		return API_UIA
	entry = _cache.get(hwnd)
	className = getClassName(hwnd)
	if entry is not None and entry[1] == className:
		return entry[0]
	if not className:
		api = API_UIA
	elif _pidOf(hwnd) == _ownPid:
		# Ventanas del propio Tiresias (diálogos wx): siempre MSAA. UIA dentro del
		# mismo proceso marshala cada llamada al hilo de la interfaz y, con los
		# proxies Win32, multiplica los eventos (decenas de selecciones por cada
		# flecha en un cuadro combinado): el anuncio llegaba con 0,5 s de retraso.
		api = API_MSAA
	else:
		try:
			api = _decide(hwnd, className)
		except Exception:
			log.debug("Error decidiendo la API de %x", hwnd, exc_info=True)
			api = API_UIA
	if len(_cache) > 4000:
		cleanup()
	_cache[hwnd] = (api, className, time.monotonic())
	if api != API_UIA:
		log.debug("Ventana %x (%s): API %s", hwnd, className, api)
	return api


def chooseAPIForFocus(element: object | None = None) -> tuple[str, int]:
	"""API y ventana del foco (ver :func:`focusWindow`; ``element``: objeto de un evento de foco)."""
	hwnd = focusWindow(element)
	return chooseAPI(hwnd), hwnd


def invalidate(hwnd: int | None = None) -> None:
	"""Olvida la decisión de una ventana (o de todas, si ``hwnd`` es ``None``)."""
	if hwnd is None:
		_cache.clear()
		_officeVersionCache.clear()
	else:
		_cache.pop(hwnd, None)


def cleanup() -> None:
	"""Quita de la caché las ventanas que ya no existen."""
	for hwnd in list(_cache):
		try:
			if not user32.IsWindow(hwnd):
				_cache.pop(hwnd, None)
		except Exception:
			_cache.pop(hwnd, None)
	if len(_officeVersionCache) > 200:
		_officeVersionCache.clear()
