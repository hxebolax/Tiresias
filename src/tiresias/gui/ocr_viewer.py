"""Visor del resultado del OCR.

La ventana muestra el texto reconocido en un cuadro de solo lectura. Tiresias
la lee como un documento en modo exploración (``ocr_document.OcrDocument``):
flechas, palabras, búsqueda, marcadores, leer todo y cursor de revisión.
Con Tiresias+Espacio se pasa a modo foco y se navega por el cuadro de texto
normal. En los dos modos Intro hace clic sobre la palabra en pantalla y
Escape cierra el visor.
"""

from __future__ import annotations

from typing import Any

import wx

from .. import queue_handler
from ..i18n import _
from ..log import getLogger
from .helpers import addLabel, bringToFront, isAlive, runOnGui

log = getLogger("gui.ocrViewer")

#: Espera antes de hacer clic, para que el foco vuelva a la ventana de debajo.
CLICK_DELAY_MS = 150


def _resultText(result: Any) -> tuple[str, list[list[tuple[int, int, Any]]]]:
	"""Texto del visor y, por línea, (columna inicial, columna final, palabra).

	Debe coincidir carácter a carácter con el búfer de ``OcrBuffer``.
	"""
	textLines: list[str] = []
	mapping: list[list[tuple[int, int, Any]]] = []
	lastPage = None
	for line in getattr(result, "lines", []):
		page = getattr(line, "page", None)
		if page is not None and page != lastPage:
			lastPage = page
			textLines.append(_("Página {n}").format(n=page))
			mapping.append([])
		words = getattr(line, "words", ())
		if not words:
			continue
		col = 0
		parts: list[str] = []
		entries: list[tuple[int, int, Any]] = []
		for word in words:
			if parts:
				col += 1
			wordText = str(word.text)
			entries.append((col, col + len(wordText), word))
			parts.append(wordText)
			col += len(wordText)
		textLines.append(" ".join(parts))
		mapping.append(entries)
	return "\n".join(textLines), mapping


class OcrViewerDialog(wx.Dialog):
	def __init__(self, result: Any) -> None:
		super().__init__(None, title=getattr(result, "title", "") or _("Resultado del OCR"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
		self.result = result
		self.document = None
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, _("&Texto reconocido (Intro hace clic en la palabra):"))
		self.text = wx.TextCtrl(self, size=(640, 420), style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
		sizer.Add(self.text, 1, wx.EXPAND | wx.ALL, 6)
		close = wx.Button(self, wx.ID_CANCEL, _("&Cerrar"))
		sizer.Add(close, 0, wx.ALIGN_RIGHT | wx.ALL, 6)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.Close(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, self.onClose)
		self.Bind(wx.EVT_CHAR_HOOK, self.onCharHook)
		self.setResult(result, resetCaret=True)
		self.CentreOnScreen()

	def setResult(self, result: Any, resetCaret: bool = False) -> None:
		self.result = result
		self.SetTitle(getattr(result, "title", "") or _("Resultado del OCR"))
		pos = self.text.GetInsertionPoint()
		text, self._map = _resultText(result)
		self.text.SetValue(text)
		if resetCaret:
			self.text.SetInsertionPoint(0)
			self.text.ShowPosition(0)
		else:
			self.text.SetInsertionPoint(min(pos, self.text.GetLastPosition()))

	def syncCaret(self, offset: int) -> None:
		"""Sitúa el cursor del cuadro donde está el cursor del modo exploración."""
		from ..ocr_document import caretToLineCol

		line, col = caretToLineCol(self.text.GetValue(), offset)
		pos = self.text.XYToPosition(col, line)
		if pos >= 0:
			self.text.SetInsertionPoint(pos)
			self.text.ShowPosition(pos)

	def wordAtCaret(self) -> Any | None:
		ok, col, lineNo = self.text.PositionToXY(self.text.GetInsertionPoint())
		if not ok or not (0 <= lineNo < len(self._map)):
			return None
		entries = self._map[lineNo]
		if not entries:
			return None
		for start, end, word in entries:
			if start <= col < end:
				return word
		# Entre palabras o al final: la última que empieza antes del cursor.
		best = entries[0][2]
		for start, _end, word in entries:
			if start <= col:
				best = word
		return best

	def onCharHook(self, evt: wx.KeyEvent) -> None:
		key = evt.GetKeyCode()
		if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and not evt.HasAnyModifiers() and wx.Window.FindFocus() is self.text:
			# Solo en el texto: con el foco en Cerrar, Intro cierra.
			self.activate()
			return
		if key == wx.WXK_ESCAPE and not evt.HasAnyModifiers():
			self.Close()
			return
		evt.Skip()

	def activate(self) -> None:
		word = self.wordAtCaret()
		src = getattr(self.result, "source", ())
		if word is None or not src or src[0] != "rect":
			wx.Bell()
			return
		x = int(word.x + word.w // 2)
		y = int(word.y + word.h // 2)
		self.Close()
		from .. import mouse

		queue_handler.callLater(CLICK_DELAY_MS, mouse.click, x, y)

	def onClose(self, evt: wx.CloseEvent) -> None:
		global _dialog, _dialogHwnd
		doc = self.document
		if doc is not None:
			queue_handler.queueFunction(doc.close)
		if _dialog is self:
			_dialog = None
			_dialogHwnd = 0
		self.Destroy()


_dialog: OcrViewerDialog | None = None
#: HWND del visor abierto (0 si no hay): lo consulta el núcleo sin tocar wx.
_dialogHwnd = 0


def isOpen() -> bool:
	"""¿Está abierto el visor? Desde otro hilo solo se mira el HWND (sin wx)."""
	if wx.IsMainThread():
		return isAlive(_dialog)
	from .. import winapi

	hwnd = _dialogHwnd
	return bool(hwnd) and bool(winapi.user32.IsWindow(hwnd))


def _makeDocument(result: Any):
	from ..ocr_document import OcrDocument

	return OcrDocument(result)


def show(result: Any) -> None:
	"""Muestra un ``OcrResult`` (llamar desde el hilo del núcleo)."""
	doc = _makeDocument(result)

	def _create() -> None:
		global _dialog, _dialogHwnd
		if isAlive(_dialog):
			old = _dialog
			oldDoc = old.document
			old.document = None
			if oldDoc is not None:
				queue_handler.queueFunction(oldDoc.close)
			_dialog = None
			old.Destroy()
		dlg = OcrViewerDialog(result)
		dlg.document = doc
		_dialog = dlg
		hwnd = int(dlg.GetHandle())
		_dialogHwnd = hwnd
		# El visor no debe salir en sus propias capturas (F5 o el refresco
		# automático reconocen la pantalla con él delante).
		try:
			from .. import imaging

			imaging.excludeFromCapture(hwnd)
		except Exception:
			log.debug("No se pudo excluir el visor del OCR de las capturas", exc_info=True)
		doc.onCaretMoved = lambda off: runOnGui(_sync, off)
		# El documento se registra en el núcleo antes de mostrar la ventana, para
		# que el primer evento de foco ya lo encuentre.
		queue_handler.queueFunction(_registerThenShow, doc, hwnd)

	runOnGui(_create)


def _registerThenShow(doc, hwnd: int) -> None:
	doc.register(hwnd)

	def _show() -> None:
		if isAlive(_dialog) and _dialog.document is doc:
			_dialog.Show()
			bringToFront(_dialog)
			_dialog.text.SetFocus()

	runOnGui(_show)


def _sync(offset: int) -> None:
	if isAlive(_dialog):
		_dialog.syncCaret(offset)


def update(result: Any) -> None:
	"""Refresca el visor con un resultado nuevo (llamar desde el hilo del núcleo)."""

	def _update() -> None:
		if isAlive(_dialog):
			_dialog.setResult(result)
			doc = _dialog.document
			if doc is not None:
				queue_handler.queueFunction(doc.updateResult, result)

	runOnGui(_update)


def close() -> None:
	"""Cierra el visor (seguro desde cualquier hilo)."""

	def _close() -> None:
		if isAlive(_dialog):
			_dialog.Close()

	runOnGui(_close)
