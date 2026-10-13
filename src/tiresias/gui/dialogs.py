"""Diálogos sencillos: pedir un texto y mostrar un mensaje navegable."""

from __future__ import annotations

import html
import html.parser
import re
from typing import Callable

import wx

from ..i18n import _
from ..log import getLogger
from .helpers import addLabel, bringToFront, isAlive, runOnGui

log = getLogger("gui.dialogs")


# ------------------------------------------------------------------ pedir texto
class AskTextDialog(wx.Dialog):
	"""Diálogo no modal con una etiqueta, un campo de texto y Aceptar/Cancelar."""

	def __init__(self, title: str, prompt: str, default: str, callback: Callable[[str], None], onCancel: Callable[[], None] | None = None) -> None:
		super().__init__(None, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._callback = callback
		self._onCancel = onCancel
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, prompt)
		self.text = wx.TextCtrl(self, value=default or "", size=(380, -1))
		sizer.Add(self.text, 0, wx.EXPAND | wx.ALL, 6)
		buttons = wx.BoxSizer(wx.HORIZONTAL)
		ok = wx.Button(self, wx.ID_OK, _("Aceptar"))
		ok.SetDefault()
		cancel = wx.Button(self, wx.ID_CANCEL, _("Cancelar"))
		buttons.Add(ok, 0, wx.ALL, 4)
		buttons.Add(cancel, 0, wx.ALL, 4)
		sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_BUTTON, self.onOk, id=wx.ID_OK)
		self.Bind(wx.EVT_BUTTON, self.onCancel, id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, self.onCancel)
		self.CentreOnScreen()
		self.text.SetFocus()
		self.text.SelectAll()

	def onOk(self, evt: wx.CommandEvent) -> None:
		value = self.text.GetValue()
		callback = self._callback
		self.Destroy()
		try:
			callback(value)
		except Exception:
			log.exception("Error en la respuesta del diálogo de texto")

	def onCancel(self, evt: wx.Event) -> None:
		onCancel = self._onCancel
		self._onCancel = None
		self.Destroy()
		if onCancel is not None:
			try:
				onCancel()
			except Exception:
				log.exception("Error al cancelar el diálogo de texto")


def askText(title: str, prompt: str, default: str, callback: Callable[[str], None], onCancel: Callable[[], None] | None = None) -> None:
	"""Pide un texto al usuario (seguro desde cualquier hilo).

	``callback(texto)`` se llama en el hilo de la interfaz y solo si se
	pulsa Aceptar; ``onCancel()``, también en ese hilo, si se cancela.
	"""

	def _show() -> None:
		dlg = AskTextDialog(title, prompt, default, callback, onCancel)
		dlg.Show()
		bringToFront(dlg)
		dlg.text.SetFocus()

	runOnGui(_show)


# ------------------------------------------------------------------ HTML a texto
class _HtmlToText(html.parser.HTMLParser):
	_BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol", "pre", "blockquote", "section", "article", "header", "footer", "dt", "dd", "hr"}
	_SKIP = {"script", "style", "head", "title"}

	def __init__(self) -> None:
		super().__init__(convert_charrefs=True)
		self.parts: list[str] = []
		self._skip = 0

	def handle_starttag(self, tag, attrs) -> None:
		if tag in self._SKIP:
			self._skip += 1
		elif tag in self._BLOCK:
			self.parts.append("\n")
		if tag == "li":
			self.parts.append("• ")
		elif tag in ("td", "th"):
			self.parts.append("\t")

	def handle_endtag(self, tag) -> None:
		if tag in self._SKIP:
			self._skip = max(0, self._skip - 1)
		elif tag in self._BLOCK and tag not in ("li", "tr", "dt", "dd", "br"):
			self.parts.append("\n")

	def handle_data(self, data) -> None:
		if not self._skip:
			self.parts.append(data)


def htmlToText(source: str) -> str:
	"""Convierte HTML en texto plano legible (sin etiquetas)."""
	parser = _HtmlToText()
	try:
		parser.feed(source)
		parser.close()
		text = "".join(parser.parts)
	except Exception:
		text = html.unescape(re.sub(r"<[^>]+>", "", source))
	lines = [" ".join(line.split()) if "\t" not in line else line.strip() for line in text.splitlines()]
	text = "\n".join(lines)
	return re.sub(r"\n{3,}", "\n\n", text).strip()


# ------------------------------------------------------------------ mensaje navegable
class BrowseableMessageDialog(wx.Dialog):
	"""Muestra un texto de solo lectura que se puede recorrer con las flechas."""

	def __init__(self, text: str, title: str) -> None:
		super().__init__(None, title=title or _("Tiresias"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.label = addLabel(self, sizer, title or _("Mensaje"))
		self.text = wx.TextCtrl(self, value=text, size=(560, 360), style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
		sizer.Add(self.text, 1, wx.EXPAND | wx.ALL, 6)
		close = wx.Button(self, wx.ID_CANCEL, _("&Cerrar"))
		sizer.Add(close, 0, wx.ALIGN_RIGHT | wx.ALL, 6)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.Close(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, self.onClose)
		self.Bind(wx.EVT_CHAR_HOOK, self.onCharHook)
		self.CentreOnScreen()
		self._placeCaret()

	def setContent(self, text: str, title: str) -> None:
		self.SetTitle(title or _("Tiresias"))
		self.label.SetLabel(title or _("Mensaje"))
		self.text.SetValue(text)
		self._placeCaret()

	def _placeCaret(self) -> None:
		self.text.SetInsertionPoint(0)
		self.text.ShowPosition(0)
		self.text.SetFocus()

	def onCharHook(self, evt: wx.KeyEvent) -> None:
		key = evt.GetKeyCode()
		if key == wx.WXK_ESCAPE and not evt.HasAnyModifiers():
			self.Close()
			return
		if evt.GetModifiers() == wx.MOD_CONTROL and key in (ord("A"), ord("a")) and self.FindFocus() is self.text:
			self.text.SelectAll()
			return
		evt.Skip()

	def onClose(self, evt: wx.CloseEvent) -> None:
		global _browseable
		_browseable = None
		self.Destroy()


_browseable: BrowseableMessageDialog | None = None


def showBrowseableMessage(text: str, title: str = "", isHtml: bool = False) -> None:
	"""Muestra ``text`` en una ventana navegable (seguro desde cualquier hilo).

	Si ya hay una abierta se reutiliza con el nuevo contenido.
	"""
	if isHtml:
		text = htmlToText(text)

	def _show() -> None:
		global _browseable
		if isAlive(_browseable):
			_browseable.setContent(text, title)
		else:
			_browseable = BrowseableMessageDialog(text, title)
			_browseable.Show()
		bringToFront(_browseable)
		_browseable.text.SetFocus()

	runOnGui(_show)


class ChooseDialog(wx.Dialog):
	"""Elegir un elemento de una lista con filtro."""

	def __init__(self, parent, title: str, prompt: str, items: list[str], callback) -> None:
		super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._items = list(items)
		self._callback = callback
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(wx.StaticText(self, label=_("&Filtrar:")), 0, wx.LEFT | wx.TOP, 8)
		self.filter = wx.TextCtrl(self)
		sizer.Add(self.filter, 0, wx.EXPAND | wx.ALL, 8)
		sizer.Add(wx.StaticText(self, label=prompt), 0, wx.LEFT, 8)
		self.list = wx.ListBox(self, choices=self._items, size=(500, 300))
		sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 8)
		btns = self.CreateButtonSizer(wx.OK | wx.CANCEL)
		sizer.Add(btns, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
		self.SetSizerAndFit(sizer)
		if self._items:
			self.list.SetSelection(0)
		self.filter.Bind(wx.EVT_TEXT, self._onFilter)
		self.filter.Bind(wx.EVT_KEY_DOWN, self._onFilterKey)
		self.list.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._accept())
		self.Bind(wx.EVT_BUTTON, lambda e: self._accept(), id=wx.ID_OK)
		self.Bind(wx.EVT_BUTTON, lambda e: self.Destroy(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)
		self.list.SetFocus()

	def _onCharHook(self, evt) -> None:
		if evt.GetKeyCode() == wx.WXK_ESCAPE:
			self.Destroy()
		elif evt.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and wx.Window.FindFocus() in (self.filter, self.list):
			# Solo desde el filtro o la lista: con el foco en Cancelar, Intro cancela.
			self._accept()
		else:
			evt.Skip()

	def _onFilterKey(self, evt) -> None:
		if evt.GetKeyCode() == wx.WXK_DOWN and self.list.GetCount():
			self.list.SetFocus()
		else:
			evt.Skip()

	def _onFilter(self, evt) -> None:
		text = self.filter.GetValue().lower()
		shown = [i for i in self._items if text in i.lower()]
		self.list.Set(shown)
		if shown:
			self.list.SetSelection(0)

	def _accept(self) -> None:
		sel = self.list.GetStringSelection()
		callback = self._callback
		self.Destroy()
		if not sel:
			return

		def run() -> None:
			try:
				callback(sel)
			except Exception:
				log.exception("Error en la acción elegida de la lista")

		# Se espera a que el foco vuelva a la ventana anterior: el OCR o la IA
		# actúan sobre ella, no sobre esta lista.
		wx.CallLater(200, run)


_chooseDialog: ChooseDialog | None = None


def chooseFromList(title: str, prompt: str, items: list[str], callback) -> None:
	"""Muestra una lista para elegir (llamar en el hilo de la interfaz).

	Solo hay una a la vez; al cerrarla se vuelve a la ventana anterior.
	"""
	global _chooseDialog
	if isAlive(_chooseDialog):
		_chooseDialog.Destroy()
	_chooseDialog = ChooseDialog(None, title, prompt, items, callback)
	_chooseDialog.Show()
	bringToFront(_chooseDialog)
	_chooseDialog.list.SetFocus()
