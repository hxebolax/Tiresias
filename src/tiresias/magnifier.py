"""Lupa (API de ampliación de Windows).

Vistas:

- ``fullscreen``: amplía toda la pantalla (``MagSetFullscreenTransform``).
- ``docked``: ventana de lupa acoplada a un borde de la pantalla; reserva su
  espacio como barra de aplicación para que las ventanas no queden debajo.
- ``lens``: lente flotante que acompaña al punto seguido sin taparlo.
- ``spotlight`` (foco): la zona del punto seguido se amplía en su sitio y el
  resto de la pantalla se oscurece.

Las vistas en ventana usan el control «Magnifier» de Magnification.dll y se
refrescan con un temporizador. Filtros de color: invertir, escala de grises,
grises invertidos, sepia y amarillo sobre negro (con un conmutador para
quitarlos y recuperarlos, #20418).

Seguimiento, cada uno con su conmutador: foco del sistema, cursor del sistema
(también el del modo exploración), cursor de revisión, objeto navegador y
ratón (#20360: foco y cursor por separado). Modos de seguimiento en pantalla
completa y en las ventanas: centrado, por bordes o relativo.

Además: llevar el ratón al centro de la vista (#20127), vista general de toda
la pantalla y desplazamiento con el teclado.
"""

from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

from . import api, speech
from .config import conf, registerDefaults
from .i18n import _
from .log import getLogger

log = getLogger("magnifier")

registerDefaults(
	"magnifier",
	{
		"level": 2.0,
		"followFocus": True,
		"followCaret": True,
		"followReview": True,
		"followNavigator": True,
		"followMouse": True,
		"step": 0.5,
		"panStep": 10,
		"enableAtStartup": False,
		"view": "fullscreen",
		"trackingMode": "edge",
		"filter": "none",
		#: Último filtro distinto de «ninguno» (para el conmutador de filtros).
		"lastFilter": "invert",
		"dockPosition": "top",
		"dockSize": 33,
		"lensWidth": 480,
		"lensHeight": 270,
		"spotlightOpacity": 75,
		"showMouseCursor": True,
		"overviewSeconds": 4,
	},
)

LEVELS_MIN = 1.0
LEVELS_MAX = 16.0

VIEWS = ("fullscreen", "docked", "lens", "spotlight")
VIEW_LABELS = {
	"fullscreen": _("pantalla completa"),
	"docked": _("ventana acoplada"),
	"lens": _("lente"),
	"spotlight": _("foco"),
}
TRACKING_MODES = ("center", "edge", "relative")
TRACKING_LABELS = {"center": _("centrado"), "edge": _("por bordes"), "relative": _("relativo")}
DOCK_POSITIONS = {"top": _("arriba"), "bottom": _("abajo"), "left": _("a la izquierda"), "right": _("a la derecha")}
FOLLOW_KEYS = ("followFocus", "followCaret", "followReview", "followNavigator", "followMouse")
FOLLOW_LABELS = {
	"followFocus": _("foco del sistema"),
	"followCaret": _("cursor del sistema"),
	"followReview": _("cursor de revisión"),
	"followNavigator": _("objeto navegador"),
	"followMouse": _("ratón"),
}

user32 = ctypes.WinDLL("user32")
gdi32 = ctypes.WinDLL("gdi32")


class MAGCOLOREFFECT(ctypes.Structure):
	_fields_ = [("transform", ctypes.c_float * 25)]


class MAGTRANSFORM(ctypes.Structure):
	_fields_ = [("v", ctypes.c_float * 9)]


class RECT(ctypes.Structure):
	_fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


def _matrix(values: list[float]) -> MAGCOLOREFFECT:
	return MAGCOLOREFFECT((ctypes.c_float * 25)(*values))


# Matrices de color 5x5 (filas: entrada R, G, B, A, desplazamiento; columnas: salida).
_GRAY_R, _GRAY_G, _GRAY_B = 0.3, 0.59, 0.11
FILTER_MATRICES: dict[str, list[float]] = {
	"none": [1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1],
	"invert": [-1, 0, 0, 0, 0, 0, -1, 0, 0, 0, 0, 0, -1, 0, 0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1],
	"grayscale": [_GRAY_R, _GRAY_R, _GRAY_R, 0, 0, _GRAY_G, _GRAY_G, _GRAY_G, 0, 0, _GRAY_B, _GRAY_B, _GRAY_B, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1],
	"grayscaleInverted": [-_GRAY_R, -_GRAY_R, -_GRAY_R, 0, 0, -_GRAY_G, -_GRAY_G, -_GRAY_G, 0, 0, -_GRAY_B, -_GRAY_B, -_GRAY_B, 0, 0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1],
	"sepia": [0.393, 0.349, 0.272, 0, 0, 0.769, 0.686, 0.534, 0, 0, 0.189, 0.168, 0.131, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1],
	# Amarillo sobre negro: luminancia invertida en rojo y verde, azul a cero.
	"yellowOnBlack": [-_GRAY_R, -_GRAY_R, 0, 0, 0, -_GRAY_G, -_GRAY_G, 0, 0, 0, -_GRAY_B, -_GRAY_B, 0, 0, 0, 0, 0, 0, 1, 0, 1, 1, 0, 0, 1],
}
FILTER_LABELS = {
	"none": _("sin filtro"),
	"invert": _("colores invertidos"),
	"grayscale": _("escala de grises"),
	"grayscaleInverted": _("grises invertidos"),
	"sepia": _("sepia"),
	"yellowOnBlack": _("amarillo sobre negro"),
}
_IDENTITY = _matrix(FILTER_MATRICES["none"])


def filterEffect(name: str) -> MAGCOLOREFFECT:
	return _matrix(FILTER_MATRICES.get(name, FILTER_MATRICES["none"]))


def applyMatrix(name: str, r: float, g: float, b: float) -> tuple[float, float, float]:
	"""Aplica una matriz de filtro a un color (0-1). Para las pruebas y la vista previa."""
	m = FILTER_MATRICES[name]
	vec = (r, g, b, 1.0, 1.0)
	out = []
	for col in range(3):
		v = sum(vec[row] * m[row * 5 + col] for row in range(5))
		out.append(max(0.0, min(1.0, v)))
	return out[0], out[1], out[2]


class _MagApi:
	"""Inicialización compartida de Magnification.dll (lupa y cortina)."""

	def __init__(self) -> None:
		self._dll = None
		self._refs = 0
		self._lock = threading.Lock()

	def dll(self):
		if self._dll is None:
			d = ctypes.WinDLL("Magnification")
			d.MagInitialize.restype = wintypes.BOOL
			d.MagUninitialize.restype = wintypes.BOOL
			d.MagSetFullscreenTransform.argtypes = [ctypes.c_float, ctypes.c_int, ctypes.c_int]
			d.MagSetFullscreenTransform.restype = wintypes.BOOL
			d.MagSetFullscreenColorEffect.argtypes = [ctypes.POINTER(MAGCOLOREFFECT)]
			d.MagSetFullscreenColorEffect.restype = wintypes.BOOL
			d.MagSetWindowSource.argtypes = [wintypes.HWND, RECT]
			d.MagSetWindowSource.restype = wintypes.BOOL
			d.MagSetWindowTransform.argtypes = [wintypes.HWND, ctypes.POINTER(MAGTRANSFORM)]
			d.MagSetWindowTransform.restype = wintypes.BOOL
			d.MagSetColorEffect.argtypes = [wintypes.HWND, ctypes.POINTER(MAGCOLOREFFECT)]
			d.MagSetColorEffect.restype = wintypes.BOOL
			d.MagSetWindowFilterList.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_int, ctypes.POINTER(wintypes.HWND)]
			d.MagSetWindowFilterList.restype = wintypes.BOOL
			self._dll = d
		return self._dll

	def acquire(self) -> bool:
		with self._lock:
			if self._refs == 0 and not self.dll().MagInitialize():
				return False
			self._refs += 1
			return True

	def release(self) -> None:
		with self._lock:
			if self._refs <= 0:
				return
			self._refs -= 1
			if self._refs == 0:
				self.dll().MagUninitialize()


magApi = _MagApi()


# ====================================================================== geometría
def computeViewOrigin(
	point: tuple[int, int],
	viewSize: tuple[float, float],
	screen: tuple[int, int, int, int],
	mode: str,
	current: tuple[float, float] | None,
	margin: float = 0.15,
) -> tuple[float, float]:
	"""Esquina superior izquierda de la zona ampliada para seguir a ``point``.

	``screen`` es (x, y, ancho, alto) de la zona ampliable y ``current`` la
	esquina actual (``None`` si aún no hay). Modos:

	- ``center``: el punto siempre queda en el centro.
	- ``edge``: la vista solo se mueve cuando el punto se acerca a un borde.
	- ``relative``: el punto ocupa en la vista la misma posición relativa que en la pantalla.
	"""
	px, py = point
	vw, vh = viewSize
	sx, sy, sw, sh = screen
	if mode == "relative":
		fx = (px - sx) / sw if sw else 0.5
		fy = (py - sy) / sh if sh else 0.5
		left, top = px - fx * vw, py - fy * vh
	elif mode == "edge" and current is not None:
		left, top = current
		mx, my = vw * margin, vh * margin
		if px < left + mx:
			left = px - mx
		elif px > left + vw - mx:
			left = px - vw + mx
		if py < top + my:
			top = py - my
		elif py > top + vh - my:
			top = py - vh + my
	else:
		left, top = px - vw / 2, py - vh / 2
	left = min(max(sx, left), sx + sw - vw)
	top = min(max(sy, top), sy + sh - vh)
	return left, top


def lensRect(point: tuple[int, int], size: tuple[int, int], screen: tuple[int, int, int, int], centered: bool) -> tuple[int, int, int, int]:
	"""Rectángulo de la lente: centrada en el punto (foco) o desplazada para no taparlo."""
	px, py = point
	w, h = size
	sx, sy, sw, sh = screen
	if centered:
		x, y = px - w // 2, py - h // 2
	else:
		gap = 24
		x = px + gap
		y = py + gap
		if x + w > sx + sw:
			x = px - gap - w
		if y + h > sy + sh:
			y = py - gap - h
	x = min(max(sx, x), sx + sw - w)
	y = min(max(sy, y), sy + sh - h)
	return int(x), int(y), int(w), int(h)


def _screenRect() -> tuple[int, int, int, int]:
	return 0, 0, user32.GetSystemMetrics(0) or 1, user32.GetSystemMetrics(1) or 1


# ====================================================================== ventanas de lupa
GWL_EXSTYLE = -20
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOPMOST = 0x00000008
LWA_ALPHA = 0x2
MS_SHOWMAGNIFIEDCURSOR = 0x0001
MW_FILTERMODE_EXCLUDE = 0
HWND_TOPMOST = -1
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
RGN_DIFF = 4

user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL]
user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
gdi32.CreateRectRgn.restype = wintypes.HRGN
gdi32.CreateRectRgn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
gdi32.CombineRgn.argtypes = [wintypes.HRGN, wintypes.HRGN, wintypes.HRGN, ctypes.c_int]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_kernel32 = ctypes.WinDLL("kernel32")
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_shell32 = ctypes.WinDLL("shell32")


class APPBARDATA(ctypes.Structure):
	_fields_ = [
		("cbSize", wintypes.DWORD),
		("hWnd", wintypes.HWND),
		("uCallbackMessage", wintypes.UINT),
		("uEdge", wintypes.UINT),
		("rc", RECT),
		("lParam", wintypes.LPARAM),
	]


_shell32.SHAppBarMessage.argtypes = [wintypes.DWORD, ctypes.POINTER(APPBARDATA)]
_shell32.SHAppBarMessage.restype = ctypes.c_size_t
ABM_NEW, ABM_REMOVE, ABM_QUERYPOS, ABM_SETPOS = 0, 1, 2, 3
_ABE = {"left": 0, "top": 1, "right": 2, "bottom": 3}


def _setExStyle(hwnd: int, add: int) -> None:
	ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
	user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex | add)


class _MagWindow:
	"""Ventana anfitriona (wx) con un control de ampliación dentro. Solo en el hilo de la interfaz."""

	def __init__(self, clickThrough: bool) -> None:
		import wx

		self.frame = wx.Frame(None, title="Tiresias - " + _("Lupa"), size=(10, 10), style=wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP | wx.BORDER_NONE)
		self.hwnd = int(self.frame.GetHandle())
		_setExStyle(self.hwnd, WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | (WS_EX_TRANSPARENT if clickThrough else 0))
		user32.SetLayeredWindowAttributes(self.hwnd, 0, 255, LWA_ALPHA)
		style = WS_CHILD | WS_VISIBLE | (MS_SHOWMAGNIFIEDCURSOR if conf["magnifier"]["showMouseCursor"] else 0)
		self.mag = user32.CreateWindowExW(0, "Magnifier", "MagnifierWindow", style, 0, 0, 10, 10, self.hwnd, None, _kernel32.GetModuleHandleW(None), None)
		if not self.mag:
			self.frame.Destroy()
			raise OSError("No se pudo crear el control de ampliación")
		self.rect = (0, 0, 10, 10)
		self._excluded: list[int] = []

	def place(self, rect: tuple[int, int, int, int]) -> None:
		if rect == self.rect and self.frame.IsShown():
			return
		self.rect = rect
		x, y, w, h = rect
		if not self.frame.IsShown():
			self.frame.ShowWithoutActivating()
		user32.SetWindowPos(self.hwnd, HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW)
		user32.MoveWindow(self.mag, 0, 0, w, h, True)

	def exclude(self, hwnds: list[int]) -> None:
		if hwnds == self._excluded:
			return
		self._excluded = list(hwnds)
		arr = (wintypes.HWND * len(hwnds))(*hwnds)
		magApi.dll().MagSetWindowFilterList(self.mag, MW_FILTERMODE_EXCLUDE, len(hwnds), arr)

	def setSource(self, src: tuple[int, int, int, int], level: float) -> None:
		d = magApi.dll()
		t = MAGTRANSFORM((ctypes.c_float * 9)(level, 0, 0, 0, level, 0, 0, 0, 1))
		d.MagSetWindowTransform(self.mag, ctypes.byref(t))
		x, y, w, h = src
		d.MagSetWindowSource(self.mag, RECT(int(x), int(y), int(x + w), int(y + h)))
		user32.InvalidateRect(self.mag, None, True)

	def setFilter(self, name: str) -> None:
		magApi.dll().MagSetColorEffect(self.mag, ctypes.byref(filterEffect(name)))

	def hide(self) -> None:
		if self.frame.IsShown():
			self.frame.Hide()

	def destroy(self) -> None:
		try:
			user32.DestroyWindow(self.mag)
		except Exception:
			pass
		try:
			self.frame.Destroy()
		except Exception:
			pass


class _DimOverlay:
	"""Velo oscuro sobre toda la pantalla con un hueco (vista de foco)."""

	def __init__(self) -> None:
		import wx

		self.frame = wx.Frame(None, title="", size=(10, 10), style=wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP | wx.BORDER_NONE)
		self.frame.SetBackgroundColour(wx.Colour(0, 0, 0))
		self.hwnd = int(self.frame.GetHandle())
		_setExStyle(self.hwnd, WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
		self.screen = _screenRect()
		self.hole: tuple[int, int, int, int] | None = None
		self.setOpacity(int(conf["magnifier"]["spotlightOpacity"]))

	def setOpacity(self, percent: int) -> None:
		user32.SetLayeredWindowAttributes(self.hwnd, 0, int(255 * max(10, min(95, percent)) / 100), LWA_ALPHA)

	def setHole(self, hole: tuple[int, int, int, int]) -> None:
		if hole == self.hole and self.frame.IsShown():
			return
		self.hole = hole
		sx, sy, sw, sh = self.screen
		if not self.frame.IsShown():
			self.frame.ShowWithoutActivating()
		user32.SetWindowPos(self.hwnd, HWND_TOPMOST, sx, sy, sw, sh, SWP_NOACTIVATE | SWP_SHOWWINDOW)
		hx, hy, hw, hh = hole
		full = gdi32.CreateRectRgn(0, 0, sw, sh)
		cut = gdi32.CreateRectRgn(hx - sx, hy - sy, hx - sx + hw, hy - sy + hh)
		gdi32.CombineRgn(full, full, cut, RGN_DIFF)
		gdi32.DeleteObject(cut)
		# El sistema se queda con la región: no se libera.
		user32.SetWindowRgn(self.hwnd, full, True)

	def destroy(self) -> None:
		try:
			self.frame.Destroy()
		except Exception:
			pass


# ====================================================================== lupa
class Magnifier:
	REFRESH_MS = 33

	def __init__(self) -> None:
		self.active = False
		self.center: tuple[int, int] | None = None
		self._origin: tuple[float, float] | None = None
		self._lastMouse: tuple[int, int] | None = None
		self.point: tuple[int, int] | None = None
		self.lastTracked = ""
		self._window: _MagWindow | None = None
		self._overlay: _DimOverlay | None = None
		self._appBar: APPBARDATA | None = None
		#: Última reserva de la barra acoplada: ((rectángulo pedido, posición), rectángulo concedido).
		self._dockReserved: tuple[tuple, tuple[int, int, int, int]] | None = None
		self._timer = None
		self._overviewUntil = 0.0
		self._overviewTimer = None
		self._fullscreenApplied = False

	# --------------------------------------------------------- utilidades
	@staticmethod
	def _screen() -> tuple[int, int]:
		return user32.GetSystemMetrics(0) or 1, user32.GetSystemMetrics(1) or 1

	@property
	def level(self) -> float:
		try:
			return max(LEVELS_MIN, min(LEVELS_MAX, float(conf["magnifier"]["level"])))
		except (TypeError, ValueError):
			return 2.0

	@property
	def view(self) -> str:
		v = conf["magnifier"]["view"]
		return v if v in VIEWS else "fullscreen"

	def altersScreen(self) -> bool:
		"""``True`` si lo que se ve en el monitor no es la pantalla real (para las capturas)."""
		# El filtro de color a pantalla completa lo aplica el compositor al
		# mostrar la imagen: las capturas siguen viendo los colores reales.
		return self.active and self.view == "fullscreen"

	def _run(self, func, *args) -> None:
		from . import gui

		gui.runOnGui(func, *args)

	def _levelText(self) -> str:
		lvl = self.level
		return str(int(lvl)) if float(lvl).is_integer() else f"{lvl:.1f}".replace(".", ",")

	def inOverview(self) -> bool:
		return time.monotonic() < self._overviewUntil

	# --------------------------------------------------------- aplicar (hilo de la interfaz)
	def _viewSize(self) -> tuple[float, float]:
		"""Tamaño de la zona de pantalla que se amplía."""
		level = self.level
		if self.view == "fullscreen":
			w, h = self._screen()
			return w / level, h / level
		if self._window is not None:
			_x, _y, w, h = self._window.rect
			return w / level, h / level
		return 100.0, 100.0

	def _apply(self) -> bool:
		"""Aplica la vista actual; ``False`` si Windows no la ha aceptado."""
		if not self.active:
			return False
		try:
			if self.view == "fullscreen":
				return self._applyFullscreen()
			return self._applyWindowed()
		except OSError:
			log.exception("Error aplicando la lupa")
			return False

	def _applyFullscreen(self) -> bool:
		w, h = self._screen()
		if self.inOverview():
			ok = bool(magApi.dll().MagSetFullscreenTransform(1.0, 0, 0))
			self._fullscreenApplied = True
			return ok
		level = self.level
		vw, vh = w / level, h / level
		point = self.center or (w // 2, h // 2)
		left, top = computeViewOrigin(point, (vw, vh), (0, 0, w, h), "center", None)
		self._origin = (left, top)
		self.center = (int(left + vw / 2), int(top + vh / 2))
		ok = bool(magApi.dll().MagSetFullscreenTransform(level, int(left), int(top)))
		self._fullscreenApplied = True
		return ok

	def _windowRectForView(self) -> tuple[int, int, int, int]:
		m = conf["magnifier"]
		sx, sy, sw, sh = _screenRect()
		view = self.view
		if view == "docked":
			pos = m["dockPosition"]
			frac = max(10, min(70, int(m["dockSize"]))) / 100.0
			if pos in ("left", "right"):
				ww = int(sw * frac)
				return (sx if pos == "left" else sx + sw - ww, sy, ww, sh)
			hh = int(sh * frac)
			return (sx, sy if pos == "top" else sy + sh - hh, sw, hh)
		size = (max(100, int(m["lensWidth"])), max(60, int(m["lensHeight"])))
		point = self.point or (sw // 2, sh // 2)
		return lensRect(point, size, (sx, sy, sw, sh), centered=(view == "spotlight"))

	def _ensureWindow(self) -> bool:
		view = self.view
		if self._window is None:
			try:
				self._window = _MagWindow(clickThrough=view != "docked")
			except OSError:
				log.exception("No se pudo crear la ventana de la lupa")
				return False
			self._window.setFilter(conf["magnifier"]["filter"])
			from . import imaging

			imaging.excludeFromCapture(self._window.hwnd)
		if view == "spotlight" and self._overlay is None:
			self._overlay = _DimOverlay()
			from . import imaging

			imaging.excludeFromCapture(self._overlay.hwnd)
		if view != "spotlight" and self._overlay is not None:
			self._overlay.destroy()
			self._overlay = None
		if self._timer is None:
			import wx

			self._timer = wx.Timer()
			self._timer.Bind(wx.EVT_TIMER, lambda evt: self._tick())
			self._timer.Start(self.REFRESH_MS)
		return True

	def _applyWindowed(self) -> bool:
		if not self._ensureWindow():
			return False
		win = self._window
		if self.inOverview():
			win.hide()
			if self._overlay is not None:
				self._overlay.frame.Hide()
			return True
		rect = self._windowRectForView()
		if self.view == "docked":
			rect = self._reserveDock(rect)
		win.place(rect)
		excluded = [win.hwnd] + ([self._overlay.hwnd] if self._overlay is not None else [])
		win.exclude(excluded)
		if self._overlay is not None:
			self._overlay.setHole(rect)
		level = self.level
		sx, sy, sw, sh = _screenRect()
		vw, vh = rect[2] / level, rect[3] / level
		point = self.point or self.center or (sw // 2, sh // 2)
		if self.view in ("lens", "spotlight"):
			mode = "center"
		else:
			mode = conf["magnifier"]["trackingMode"]
		left, top = computeViewOrigin(point, (vw, vh), (sx, sy, sw, sh), mode, self._origin)
		self._origin = (left, top)
		self.center = (int(left + vw / 2), int(top + vh / 2))
		win.setSource((left, top, vw, vh), level)
		return True

	def _tick(self) -> None:
		"""Refresco periódico del contenido de la ventana de lupa."""
		if not self.active or self._window is None or self.view == "fullscreen" or self.inOverview():
			return
		try:
			if self._origin is not None:
				vw, vh = self._viewSize()
				self._window.setSource((self._origin[0], self._origin[1], vw, vh), self.level)
		except Exception:
			log.debug("Error refrescando la lupa", exc_info=True)

	def _reserveDock(self, rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
		"""Registra la ventana acoplada como barra de aplicación (reserva su espacio).

		Solo se vuelve a negociar con el shell cuando cambian el rectángulo o la
		posición: cada ABM_SETPOS hace que Windows recoloque las ventanas
		maximizadas, y ``_applyWindowed`` se llama al mover el foco o el ratón.
		"""
		pos = conf["magnifier"]["dockPosition"]
		key = (tuple(rect), pos)
		if self._appBar is not None and self._dockReserved is not None and self._dockReserved[0] == key:
			return self._dockReserved[1]
		abd = self._appBar
		if abd is None:
			abd = APPBARDATA()
			abd.cbSize = ctypes.sizeof(APPBARDATA)
			abd.hWnd = self._window.hwnd
			abd.uCallbackMessage = 0x0400 + 77
			if not _shell32.SHAppBarMessage(ABM_NEW, ctypes.byref(abd)):
				return rect
			self._appBar = abd
		x, y, w, h = rect
		abd.uEdge = _ABE.get(pos, 1)
		abd.rc = RECT(x, y, x + w, y + h)
		_shell32.SHAppBarMessage(ABM_QUERYPOS, ctypes.byref(abd))
		# Se recupera el tamaño pedido desde el borde elegido.
		if pos == "top":
			abd.rc.bottom = abd.rc.top + h
		elif pos == "bottom":
			abd.rc.top = abd.rc.bottom - h
		elif pos == "left":
			abd.rc.right = abd.rc.left + w
		else:
			abd.rc.left = abd.rc.right - w
		_shell32.SHAppBarMessage(ABM_SETPOS, ctypes.byref(abd))
		r = abd.rc
		granted = (r.left, r.top, r.right - r.left, r.bottom - r.top)
		self._dockReserved = (key, granted)
		return granted

	def _releaseDock(self) -> None:
		if self._appBar is not None:
			try:
				_shell32.SHAppBarMessage(ABM_REMOVE, ctypes.byref(self._appBar))
			except Exception:
				pass
			self._appBar = None
		self._dockReserved = None

	def _destroyWindows(self) -> None:
		if self._timer is not None:
			try:
				self._timer.Stop()
			except Exception:
				pass
			self._timer = None
		self._releaseDock()
		if self._overlay is not None:
			self._overlay.destroy()
			self._overlay = None
		if self._window is not None:
			self._window.destroy()
			self._window = None

	def _resetFullscreen(self) -> None:
		if self._fullscreenApplied:
			magApi.dll().MagSetFullscreenTransform(1.0, 0, 0)
			self._fullscreenApplied = False

	def _applyColors(self) -> None:
		from . import vision

		name = conf["magnifier"]["filter"] if self.active else "none"
		if self._window is not None:
			self._window.setFilter(name)
		if vision.handler.curtainActive:
			return
		fsName = name if (self.active and self.view == "fullscreen") else "none"
		magApi.dll().MagSetFullscreenColorEffect(ctypes.byref(filterEffect(fsName)))

	def _rebuildView(self) -> None:
		"""Cambia de vista conservando el estado (hilo de la interfaz)."""
		if not self.active:
			return
		self._destroyWindows()
		self._resetFullscreen()
		self._origin = None
		self._apply()
		self._applyColors()

	# --------------------------------------------------------- órdenes
	def setActive(self, active: bool, announce: bool = True) -> None:
		"""Activa o desactiva la lupa y lo anuncia según lo que haya pasado de verdad."""
		from . import queue_handler

		def apply() -> None:
			ok = True
			try:
				if active and not self.active:
					if not magApi.acquire():
						ok = False
					else:
						self.active = True
						self._origin = None
						if self._apply():
							self._applyColors()
						else:
							# Windows no aceptó la ampliación: se deshace todo.
							ok = False
							self._destroyWindows()
							self._resetFullscreen()
							self.active = False
							magApi.release()
				elif not active and self.active:
					self._destroyWindows()
					self._resetFullscreen()
					self.active = False
					self._applyColors()
					magApi.release()
			except OSError:
				log.exception("API de ampliación no disponible")
				ok = False
			if announce or not ok:
				queue_handler.queueFunction(self._announceActive, active, ok)

		self._run(apply)

	def _announceActive(self, active: bool, ok: bool) -> None:
		if not ok:
			speech.speakMessage(_("No se pudo activar la lupa") if active else _("No se pudo desactivar la lupa"))
		elif self.active:
			speech.speakMessage(_("Lupa activada, {view}, nivel {level}").format(view=VIEW_LABELS[self.view], level=self._levelText()))
		else:
			speech.speakMessage(_("Lupa desactivada"))

	def toggle(self) -> None:
		self.setActive(not self.active)

	def zoom(self, direction: int) -> None:
		if not self.active:
			self.setActive(True)
			return
		try:
			step = float(conf["magnifier"]["step"]) or 0.5
		except (TypeError, ValueError):
			step = 0.5
		new = round(max(LEVELS_MIN, min(LEVELS_MAX, self.level + direction * step)), 2)
		conf["magnifier"]["level"] = new
		self._run(self._apply)
		speech.speakMessage(_("Ampliación {level}").format(level=self._levelText()))

	def pan(self, dx: int, dy: int) -> None:
		if not self.active:
			return
		w, h = self._screen()
		pct = int(conf["magnifier"]["panStep"]) / 100.0
		cx, cy = self.center or (w // 2, h // 2)
		new = (int(cx + dx * w * pct / self.level), int(cy + dy * h * pct / self.level))
		self.center = new
		self.point = new
		self._origin = None
		self._run(self._apply)

	def panToEdge(self, edge: str) -> None:
		if not self.active:
			return
		w, h = self._screen()
		cx, cy = self.center or (w // 2, h // 2)
		new = {"left": (0, cy), "right": (w, cy), "top": (cx, 0), "bottom": (cx, h)}[edge]
		self.center = new
		self.point = new
		self._origin = None
		self._run(self._apply)
		speech.speakMessage({"left": _("borde izquierdo"), "right": _("borde derecho"), "top": _("borde superior"), "bottom": _("borde inferior")}[edge])

	def setFilter(self, name: str, announce: bool = True) -> None:
		if name not in FILTER_MATRICES:
			return
		conf["magnifier"]["filter"] = name
		if name != "none":
			conf["magnifier"]["lastFilter"] = name
		self._run(self._applyColors)
		if announce:
			speech.speakMessage(FILTER_LABELS[name])

	def cycleFilter(self) -> None:
		names = list(FILTER_MATRICES)
		cur = conf["magnifier"]["filter"]
		i = names.index(cur) if cur in names else 0
		self.setFilter(names[(i + 1) % len(names)])

	def toggleColorFilter(self) -> None:
		"""Quita el filtro o recupera el último usado (#20418)."""
		if conf["magnifier"]["filter"] != "none":
			self.setFilter("none", announce=False)
			speech.speakMessage(_("Filtro de color desactivado"))
		else:
			last = conf["magnifier"]["lastFilter"]
			self.setFilter(last if last in FILTER_MATRICES and last != "none" else "invert", announce=False)
			speech.speakMessage(_("Filtro de color activado: {name}").format(name=FILTER_LABELS[conf["magnifier"]["filter"]]))

	def toggleInvert(self) -> None:
		self.setFilter("none" if conf["magnifier"]["filter"] == "invert" else "invert", announce=False)
		speech.speakMessage(_("Colores invertidos") if conf["magnifier"]["filter"] == "invert" else _("Colores normales"))

	def cycleView(self) -> None:
		cur = self.view
		new = VIEWS[(VIEWS.index(cur) + 1) % len(VIEWS)]
		conf["magnifier"]["view"] = new
		self._run(self._rebuildView)
		speech.speakMessage(_("Vista de la lupa: {view}").format(view=VIEW_LABELS[new]))

	def cycleTrackingMode(self) -> None:
		cur = conf["magnifier"]["trackingMode"]
		new = TRACKING_MODES[(TRACKING_MODES.index(cur) + 1) % len(TRACKING_MODES)] if cur in TRACKING_MODES else "center"
		conf["magnifier"]["trackingMode"] = new
		self._origin = None
		speech.speakMessage(_("Seguimiento {mode}").format(mode=TRACKING_LABELS[new]))

	def toggleFollow(self, key: str) -> None:
		v = not conf["magnifier"][key]
		conf["magnifier"][key] = v
		label = FOLLOW_LABELS[key]
		speech.speakMessage((_("La lupa sigue al {what}") if v else _("La lupa no sigue al {what}")).format(what=label))

	def toggleAllFollow(self) -> None:
		anyOn = any(conf["magnifier"][k] for k in FOLLOW_KEYS)
		for k in FOLLOW_KEYS:
			conf["magnifier"][k] = not anyOn
		speech.speakMessage(_("Seguimiento de la lupa desactivado") if anyOn else _("Seguimiento de la lupa activado"))

	def moveMouseToView(self) -> None:
		"""Lleva el puntero al centro de la zona ampliada (#20127)."""
		if not self.active:
			speech.speakMessage(_("La lupa no está activada"))
			return
		w, h = self._screen()
		cx, cy = self.center or (w // 2, h // 2)
		from . import mouse

		self._lastMouse = (cx, cy)
		mouse.moveTo(cx, cy)
		speech.speakMessage(_("Ratón en el centro de la vista"))

	def showOverview(self) -> None:
		"""Muestra un momento toda la pantalla sin ampliar; otra pulsación vuelve antes."""
		if not self.active:
			speech.speakMessage(_("La lupa no está activada"))
			return
		if self.inOverview():
			self._overviewUntil = 0.0
			self._run(self._apply)
			speech.speakMessage(_("Fin de la vista general"))
			return
		secs = max(1, int(conf["magnifier"]["overviewSeconds"]))
		self._overviewUntil = time.monotonic() + secs
		self._run(self._apply)
		speech.speakMessage(_("Vista general de la pantalla"))
		from . import queue_handler

		if self._overviewTimer is not None:
			queue_handler.cancelCallLater(self._overviewTimer)
		self._overviewTimer = queue_handler.callLater(secs * 1000 + 50, self._endOverview)

	def _endOverview(self) -> None:
		self._overviewTimer = None
		if self.active and not self.inOverview():
			self._run(self._apply)

	def reportState(self) -> None:
		if not self.active:
			speech.speakMessage(_("Lupa desactivada"))
			return
		follows = [FOLLOW_LABELS[k] for k in FOLLOW_KEYS if conf["magnifier"][k]]
		msg = _("Lupa {view}, nivel {level}, {filter}").format(view=VIEW_LABELS[self.view], level=self._levelText(), filter=FILTER_LABELS.get(conf["magnifier"]["filter"], ""))
		if follows:
			msg += ". " + _("Sigue a: {list}").format(list=", ".join(follows))
		speech.speakMessage(msg)

	# --------------------------------------------------------- seguimiento
	def follow(self, x: int, y: int, source: str) -> None:
		"""Lleva la vista a (x, y) según el modo de seguimiento."""
		if not self.active:
			return
		self.point = (int(x), int(y))
		self.lastTracked = source
		if self.view == "fullscreen":
			w, h = self._screen()
			level = self.level
			vw, vh = w / level, h / level
			mode = conf["magnifier"]["trackingMode"]
			current = None
			if self.center is not None:
				current = (self.center[0] - vw / 2, self.center[1] - vh / 2)
			left, top = computeViewOrigin((x, y), (vw, vh), (0, 0, w, h), mode, current)
			newCenter = (int(left + vw / 2), int(top + vh / 2))
			if newCenter == self.center:
				return
			self.center = newCenter
		# Un solo «aplicar» pendiente a la vez: con el ratón llegan decenas de
		# movimientos por segundo y cada uno era un wx.CallAfter.
		pendingSince = getattr(self, "_followPending", 0.0)
		if pendingSince and time.monotonic() - pendingSince < 1.0:
			return
		self._followPending = time.monotonic()
		self._run(self._applyFollow)

	def _applyFollow(self) -> None:
		"""Aplica la última posición seguida (hilo de la interfaz)."""
		self._followPending = 0.0
		self._apply()

	def centerOn(self, x: int, y: int) -> None:
		self.follow(x, y, "other")

	def onFocus(self, obj=None) -> None:
		if not self.active or not conf["magnifier"]["followFocus"] or obj is None:
			return
		try:
			loc = obj.location
		except Exception:
			loc = None
		if loc:
			x, y, w, h = loc
			self.follow(x + min(w // 2, 200), y + h // 2, "focus")

	def onNavigator(self, obj=None) -> None:
		if not self.active or not conf["magnifier"]["followNavigator"] or obj is None:
			return
		try:
			if obj == api.getFocusObject():
				return
			loc = obj.location
		except Exception:
			loc = None
		if loc:
			x, y, w, h = loc
			self.follow(x + min(w // 2, 200), y + h // 2, "navigator")

	def onReview(self, info=None, isCaret: bool = False) -> None:
		if not self.active or info is None:
			return
		key = "followCaret" if isCaret else "followReview"
		if not conf["magnifier"][key]:
			return
		try:
			pt = info.pointAtStart
		except Exception:
			pt = None
		if pt is not None:
			self.follow(pt.x, pt.y, "caret" if isCaret else "review")

	def onEvent(self, eventName: str = "", obj=None, **kwargs) -> None:
		if eventName != "caret" or not self.active or not conf["magnifier"]["followCaret"] or obj is None:
			return
		pt = self._caretPoint(obj)
		if pt is not None:
			self.follow(pt[0], pt[1], "caret")

	@staticmethod
	def _caretPoint(obj) -> tuple[int, int] | None:
		from . import textinfo, winapi

		try:
			info = obj.makeTextInfo(textinfo.POSITION_CARET)
			pt = info.pointAtStart
			if pt is not None:
				return pt.x, pt.y
		except Exception:
			pass
		# Cursor Win32 clásico.
		try:
			gti = winapi.getGUIThreadInfo(winapi.getWindowThreadId(winapi.getForegroundWindow()))
			if gti is not None and gti.hwndCaret:
				p = winapi.POINT(gti.rcCaret.left, gti.rcCaret.top)
				user32.ClientToScreen(gti.hwndCaret, ctypes.byref(p))
				return p.x, p.y
		except Exception:
			pass
		return None

	def onMouse(self, x: int, y: int) -> None:
		if not self.active or not conf["magnifier"]["followMouse"]:
			return
		if self._lastMouse == (x, y):
			return
		self._lastMouse = (x, y)
		self.follow(x, y, "mouse")

	# --------------------------------------------------------- ciclo de vida
	def applyConfiguration(self) -> None:
		"""Reaplica la configuración (perfil nuevo u opciones restauradas)."""
		if self.active:
			self._run(self._rebuildView)

	def initialize(self) -> None:
		from . import events

		api.post_focusChange.register(self.onFocus)
		api.post_reviewMove.register(self.onReview)
		api.post_navigatorObjectChange.register(self.onNavigator)
		events.post_event.register(self.onEvent)
		if conf["magnifier"]["enableAtStartup"]:
			self.setActive(True, announce=False)

	def terminate(self) -> None:
		if not self.active:
			return

		def stop() -> None:
			try:
				self._destroyWindows()
				self._resetFullscreen()
				magApi.dll().MagSetFullscreenColorEffect(ctypes.byref(_IDENTITY))
				magApi.release()
			except Exception:
				log.debug("Error cerrando la lupa", exc_info=True)
			self.active = False

		runOnGuiAndWait(stop)


def runOnGuiAndWait(func, timeout: float = 3.0) -> None:
	"""Ejecuta ``func`` en el hilo de la interfaz y espera a que termine (o al tiempo límite)."""
	try:
		import wx
	except ImportError:
		func()
		return
	if wx.GetApp() is None or wx.IsMainThread():
		func()
		return
	done = threading.Event()

	def run() -> None:
		try:
			func()
		finally:
			done.set()

	wx.CallAfter(run)
	if not done.wait(timeout):
		log.warning("La interfaz no respondió a tiempo al cerrar %r", func)


magnifier = Magnifier()
