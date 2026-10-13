"""Visor braille: muestra en pantalla lo que aparecería en la línea braille.

Cada celda se dibuja con el texto que le corresponde justo debajo (alineado
celda a celda, también con braille contraído o caracteres de varias celdas).
Un clic en una celda equivale a su tecla de enrutamiento; opcionalmente
también se enruta al dejar el puntero quieto sobre una celda. La posición de
la ventana se recuerda.
"""

from __future__ import annotations

import wx

from .. import queue_handler
from ..config import conf
from ..i18n import _
from ..log import getLogger
from .helpers import isAlive, runOnGui

log = getLogger("gui.brailleViewer")

BLANK = chr(0x2800)

# Opciones del visor: sección «brailleViewer» (se registran en braille/presenter.py).


class _CellsPanel(wx.Panel):
	"""Celdas braille y su texto, dibujados en una cuadrícula."""

	def __init__(self, parent: wx.Window, numCells: int) -> None:
		super().__init__(parent, style=wx.WANTS_CHARS)
		self.numCells = max(1, numCells)
		self.cells: list[int] = [0] * self.numCells
		self.labels: list[str] = [""] * self.numCells
		self.brailleFont = wx.Font(22, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, faceName="Segoe UI Symbol")
		self.textFont = wx.Font(11, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
		dc = wx.ClientDC(self)
		dc.SetFont(self.brailleFont)
		bw, bh = dc.GetTextExtent(BLANK)
		dc.SetFont(self.textFont)
		tw, th = dc.GetTextExtent("W")
		self.cellWidth = max(bw, tw) + 6
		self.brailleHeight = bh
		self.textHeight = th
		self.hoverCell = -1
		self.SetMinSize((self.cellWidth * self.numCells + 8, bh + th + 16))
		self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
		self.Bind(wx.EVT_PAINT, self.onPaint)
		self.Bind(wx.EVT_LEFT_DOWN, self.onClick)
		self.Bind(wx.EVT_MOTION, self.onMotion)
		self.Bind(wx.EVT_LEAVE_WINDOW, self.onLeave)
		self._dwellTimer = wx.Timer(self)
		self.Bind(wx.EVT_TIMER, self.onDwell, self._dwellTimer)
		self._dwellCell = -1

	def setContent(self, cells: list[int], labels: list[str]) -> None:
		self.cells = (list(cells) + [0] * self.numCells)[: self.numCells]
		self.labels = (list(labels) + [""] * self.numCells)[: self.numCells]
		self.Refresh(False)
		# Texto accesible (para quien use el visor con un lector de pantalla).
		self.SetName("".join(chr(0x2800 + (c & 0xFF)) for c in self.cells) + " " + "".join(self.labels).strip())

	def cellAt(self, x: int) -> int:
		idx = (x - 4) // self.cellWidth
		return idx if 0 <= idx < self.numCells else -1

	def onPaint(self, evt: wx.PaintEvent) -> None:
		dc = wx.AutoBufferedPaintDC(self)
		bg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
		fg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)
		dc.SetBackground(wx.Brush(bg))
		dc.Clear()
		dc.SetTextForeground(fg)
		y2 = self.brailleHeight + 8
		for i in range(self.numCells):
			x = 4 + i * self.cellWidth
			if i == self.hoverCell:
				dc.SetBrush(wx.Brush(wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)))
				dc.SetPen(wx.TRANSPARENT_PEN)
				dc.DrawRectangle(x, 2, self.cellWidth, y2 + self.textHeight)
			dc.SetFont(self.brailleFont)
			glyph = chr(0x2800 + (self.cells[i] & 0xFF))
			gw, _gh = dc.GetTextExtent(glyph)
			dc.DrawText(glyph, x + (self.cellWidth - gw) // 2, 4)
			label = self.labels[i]
			if label:
				dc.SetFont(self.textFont)
				# Si el texto de la celda no cabe (braille contraído), se recorta.
				shown = label
				while shown and dc.GetTextExtent(shown)[0] > self.cellWidth * max(1, self._spanFor(i)):
					shown = shown[:-1]
				dc.DrawText(shown, x + 2, y2)
		dc.SetPen(wx.Pen(wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT)))
		dc.DrawLine(2, y2 - 3, 4 + self.numCells * self.cellWidth, y2 - 3)

	def _spanFor(self, i: int) -> int:
		"""Celdas ocupadas por el texto de la celda ``i`` (las vacías que siguen)."""
		n = 1
		while i + n < self.numCells and not self.labels[i + n] and self.cells[i + n]:
			n += 1
		return n

	def onClick(self, evt: wx.MouseEvent) -> None:
		cell = self.cellAt(evt.GetX())
		if cell >= 0:
			_route(cell)

	def onMotion(self, evt: wx.MouseEvent) -> None:
		cell = self.cellAt(evt.GetX())
		if cell != self.hoverCell:
			self.hoverCell = cell
			self.Refresh(False)
			if conf["brailleViewer"]["routeOnHover"] and cell >= 0:
				self._dwellCell = cell
				self._dwellTimer.StartOnce(max(200, int(conf["brailleViewer"]["hoverDwellTime"])))
			else:
				self._dwellTimer.Stop()
		evt.Skip()

	def onLeave(self, evt: wx.MouseEvent) -> None:
		self.hoverCell = -1
		self._dwellTimer.Stop()
		self.Refresh(False)
		evt.Skip()

	def onDwell(self, evt: wx.TimerEvent) -> None:
		if self._dwellCell >= 0 and self._dwellCell == self.hoverCell:
			_route(self._dwellCell)


def _route(cell: int) -> None:
	from .. import braille

	queue_handler.queueFunction(braille.handler.routeTo, cell)


class BrailleViewerFrame(wx.Frame):
	def __init__(self, numCells: int) -> None:
		super().__init__(
			None,
			title=_("Visor braille"),
			style=wx.CAPTION | wx.CLOSE_BOX | wx.SYSTEM_MENU | wx.STAY_ON_TOP | wx.FRAME_NO_TASKBAR | wx.FRAME_TOOL_WINDOW,
		)
		self.numCells = max(1, numCells)
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.panel = _CellsPanel(self, self.numCells)
		sizer.Add(self.panel, 1, wx.EXPAND | wx.ALL, 2)
		self.SetSizer(sizer)
		sizer.Fit(self)
		self._userClosed = True
		self.Bind(wx.EVT_CLOSE, self.onClose)

	def update(self, cells: list[int], text: str, labels: list[str] | None = None) -> None:
		if labels is None:
			# Sin correspondencia celda a texto: un carácter por celda.
			labels = list((text or "").replace("\n", " ")[: self.numCells])
		self.panel.setContent(cells, labels)

	def onClose(self, evt: wx.CloseEvent) -> None:
		global _frame
		try:
			x, y = self.GetPosition()
			conf["brailleViewer"]["x"] = int(x)
			conf["brailleViewer"]["y"] = int(y)
		except Exception:
			log.debug("No se pudo guardar la posición del visor", exc_info=True)
		_frame = None
		userClosed = self._userClosed
		self.Destroy()
		if userClosed:
			# El usuario cerró la ventana: desactivar el visor como línea braille.
			queue_handler.queueFunction(_switchToNoBraille)


def _switchToNoBraille() -> None:
	from .. import braille

	braille.handler.setViewer(False)


_frame: BrailleViewerFrame | None = None


def isActive() -> bool:
	return isAlive(_frame)


def _placeFrame(frame: wx.Frame) -> None:
	x = int(conf["brailleViewer"]["x"])
	y = int(conf["brailleViewer"]["y"])
	w, h = frame.GetSize()
	if x >= 0 and y >= 0:
		# Solo si la posición guardada sigue dentro de alguna pantalla.
		for i in range(wx.Display.GetCount()):
			if wx.Display(i).GetGeometry().Contains(wx.Point(x + 10, y + 10)):
				frame.SetPosition((x, y))
				return
	area = wx.Display(0).GetClientArea()
	frame.SetPosition((area.x + max(0, (area.width - w) // 2), area.y))


def show(numCells: int) -> None:
	"""Abre el visor con ``numCells`` celdas (seguro desde cualquier hilo)."""

	def _show() -> None:
		global _frame
		if isAlive(_frame):
			if _frame.numCells == numCells:
				return
			_frame._userClosed = False
			_frame.Close()
		_frame = BrailleViewerFrame(numCells)
		_placeFrame(_frame)
		_frame.ShowWithoutActivating()

	runOnGui(_show)


def update(cells: list[int], text: str, labels: list[str] | None = None) -> None:
	"""Actualiza las celdas y el texto mostrados (seguro desde cualquier hilo)."""
	cells = list(cells)
	labels = list(labels) if labels is not None else None

	def _update() -> None:
		if isAlive(_frame):
			_frame.update(cells, text, labels)

	runOnGui(_update)


def close() -> None:
	"""Cierra el visor (seguro desde cualquier hilo)."""

	def _close() -> None:
		global _frame
		if isAlive(_frame):
			_frame._userClosed = False
			_frame.Close()
		_frame = None

	runOnGui(_close)
