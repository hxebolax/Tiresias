"""Resaltado visual: rectángulos de color alrededor de los objetos.

Cada rectángulo se dibuja con cuatro ventanas finas sin borde, siempre
encima, que no reciben el foco ni los clics del ratón y que no salen en las
capturas de pantalla (así no estorban al OCR). Puede haber varios a la vez,
identificados por grupo (``focus``, ``navigator``, ``browseMode``, ``mouse``).
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

import wx

from ..log import getLogger
from .helpers import isAlive, runOnGui

log = getLogger("gui.highlighter")

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
_user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
_user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
_user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
_user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
_user32.SetWindowPos.restype = wintypes.BOOL
_user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
LWA_ALPHA = 0x2
HWND_TOPMOST = -1
SWP_NOACTIVATE = 0x0010
SWP_NOOWNERZORDER = 0x0200

DEFAULT_COLOR = "#FF0000"
DEFAULT_GROUP = "focus"


class _Edge(wx.Frame):
	"""Uno de los cuatro lados de un rectángulo."""

	def __init__(self) -> None:
		super().__init__(None, title="", size=(1, 1), style=wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP | wx.BORDER_NONE)
		self.Enable(False)
		hwnd = self.GetHandle()
		try:
			ex = _user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
			_user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
			_user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
		except OSError:
			log.debug("No se pudo hacer transparente al ratón el resaltado", exc_info=True)
		try:
			from .. import imaging

			imaging.excludeFromCapture(int(hwnd))
		except Exception:
			pass

	def place(self, x: int, y: int, w: int, h: int, colour: wx.Colour) -> None:
		if self.GetBackgroundColour() != colour:
			self.SetBackgroundColour(colour)
			self.Refresh()
		if not self.IsShown():
			self.ShowWithoutActivating()
		# Coordenadas físicas exactas, sin escalado de wx y sin activar.
		_user32.SetWindowPos(self.GetHandle(), HWND_TOPMOST, int(x), int(y), max(1, int(w)), max(1, int(h)), SWP_NOACTIVATE | SWP_NOOWNERZORDER)


_groups: dict[str, list[_Edge]] = {}


def _ensureEdges(group: str) -> list[_Edge]:
	edges = _groups.get(group, [])
	if len(edges) != 4 or not all(isAlive(e) for e in edges):
		for e in edges:
			if isAlive(e):
				e.Destroy()
		edges = [_Edge() for _i in range(4)]
		_groups[group] = edges
	return edges


def parseColour(color: str) -> wx.Colour:
	c = wx.Colour(color) if color else wx.Colour(DEFAULT_COLOR)
	if not c.IsOk():
		c = wx.Colour(DEFAULT_COLOR)
	return c


def edgeRects(rect: tuple[int, int, int, int], t: int) -> list[tuple[int, int, int, int]]:
	"""Rectángulos de los cuatro lados (arriba, abajo, izquierda, derecha)."""
	x, y, w, h = rect
	return [(x - t, y - t, w + 2 * t, t), (x - t, y + h, w + 2 * t, t), (x - t, y, t, h), (x + w, y, t, h)]


def show(rect: tuple[int, int, int, int], color: str = DEFAULT_COLOR, thickness: int = 4, group: str = DEFAULT_GROUP) -> None:
	"""Dibuja un rectángulo alrededor de ``rect`` = (x, y, ancho, alto). Seguro desde cualquier hilo."""
	try:
		x, y, w, h = (int(v) for v in rect)
	except (TypeError, ValueError):
		return
	t = max(1, int(thickness))

	def _show() -> None:
		if w <= 0 or h <= 0:
			_hide(group)
			return
		colour = parseColour(color)
		for edge, r in zip(_ensureEdges(group), edgeRects((x, y, w, h), t)):
			edge.place(*r, colour)

	runOnGui(_show)


def _hide(group: str | None) -> None:
	for name, edges in _groups.items():
		if group is not None and name != group:
			continue
		for e in edges:
			if isAlive(e) and e.IsShown():
				e.Hide()


def hide(group: str | None = DEFAULT_GROUP) -> None:
	"""Oculta un rectángulo (seguro desde cualquier hilo)."""
	runOnGui(_hide, group)


def hideAll() -> None:
	runOnGui(_hide, None)


def destroy() -> None:
	"""Destruye las ventanas del resaltado (al cerrar Tiresias)."""

	def _destroy() -> None:
		for edges in _groups.values():
			for e in edges:
				if isAlive(e):
					e.Destroy()
		_groups.clear()

	runOnGui(_destroy)
