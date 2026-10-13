"""Historiales: lo que Tiresias ha dicho y lo que se ha copiado."""

from __future__ import annotations

import time

import wx

from . import message_dialog
from .. import queue_handler
from ..i18n import _
from ..log import getLogger
from .helpers import addLabel, bringToFront, isAlive, matchesAll, normalizeForSearch, runOnGui, speakMessage

log = getLogger("gui.history")

PREVIEW_CHARS = 200


def _preview(text: str) -> str:
	line = " ".join(text.split())
	return line if len(line) <= PREVIEW_CHARS else line[:PREVIEW_CHARS] + "…"


def _originOf(item) -> str:
	return item[2] if len(item) > 2 else "other"


def _clock(timestamp: float) -> str:
	return time.strftime("%H:%M:%S", time.localtime(timestamp))


def _copyText(text: str) -> None:
	"""Copia al portapapeles desde la interfaz y lo anuncia."""
	from .. import api

	queue_handler.queueFunction(api.copyToClip, text, True)


# ------------------------------------------------------------------ voz
class SpeechHistoryDialog(wx.Dialog):
	def __init__(self) -> None:
		super().__init__(None, title=_("Historial de voz"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
		self.items: list[tuple[float, str]] = []
		self.visible: list[tuple[float, str]] = []
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, _("&Buscar:"))
		self.search = wx.TextCtrl(self)
		self.search.Bind(wx.EVT_TEXT, lambda evt: self.refilter())
		self.search.Bind(wx.EVT_KEY_DOWN, self.onSearchKey)
		sizer.Add(self.search, 0, wx.EXPAND | wx.ALL, 6)
		# Filtro por origen: foco, notificaciones, escritura, mensajes...
		from ..speech import api as speechApi

		self._origins = [None] + list(speechApi.ORIGIN_LABELS)
		addLabel(self, sizer, _("&Mostrar:"))
		self.originCtrl = wx.Choice(self, choices=[_("Todo")] + [speechApi.ORIGIN_LABELS[o] for o in self._origins[1:]])
		self.originCtrl.SetSelection(0)
		self.originCtrl.Bind(wx.EVT_CHOICE, lambda evt: self.refilter())
		sizer.Add(self.originCtrl, 0, wx.ALL, 6)
		addLabel(self, sizer, _("&Entradas (la más reciente primero):"))
		self.list = wx.ListBox(self, size=(620, 260), style=wx.LB_SINGLE)
		self.list.Bind(wx.EVT_LISTBOX, lambda evt: self.showSelected())
		sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 6)
		addLabel(self, sizer, _("Texto com&pleto:"))
		self.full = wx.TextCtrl(self, size=(620, 120), style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
		sizer.Add(self.full, 0, wx.EXPAND | wx.ALL, 6)
		buttons = wx.BoxSizer(wx.HORIZONTAL)
		self.copyButton = wx.Button(self, label=_("&Copiar"))
		self.copyButton.Bind(wx.EVT_BUTTON, lambda evt: self.copySelected())
		self.copyButton.SetDefault()
		copyAll = wx.Button(self, label=_("Copiar &todo"))
		copyAll.Bind(wx.EVT_BUTTON, lambda evt: self.copyAll())
		export = wx.Button(self, label=_("E&xportar..."))
		export.Bind(wx.EVT_BUTTON, lambda evt: self.export())
		clear = wx.Button(self, label=_("Borrar &historial"))
		clear.Bind(wx.EVT_BUTTON, lambda evt: self.clear())
		close = wx.Button(self, wx.ID_CANCEL, _("Cerrar"))
		for b in (self.copyButton, copyAll, export, clear, close):
			buttons.Add(b, 0, wx.ALL, 4)
		sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.Close(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, self.onClose)
		self.CentreOnScreen()
		self.reload()
		self.list.SetFocus()

	def reload(self) -> None:
		from ..speech import api as speechApi

		self.items = list(reversed(speechApi.getHistory()))
		self.refilter()

	def refilter(self) -> None:
		from ..speech import api as speechApi

		query = self.search.GetValue().strip()
		sel = self.originCtrl.GetSelection()
		origin = self._origins[sel] if 0 <= sel < len(self._origins) else None
		self.visible = [
			it
			for it in self.items
			if (not query or matchesAll(normalizeForSearch(it[1]), query)) and (origin is None or _originOf(it) == origin)
		]
		self.list.Set([f"{_clock(it[0])} {speechApi.ORIGIN_LABELS.get(_originOf(it), '')}: {_preview(it[1])}" for it in self.visible])
		if self.visible:
			self.list.SetSelection(0)
		self.showSelected()

	def onSearchKey(self, evt: wx.KeyEvent) -> None:
		if evt.GetKeyCode() in (wx.WXK_DOWN, wx.WXK_NUMPAD_DOWN) and not evt.HasAnyModifiers() and self.visible:
			self.list.SetFocus()
			return
		evt.Skip()

	def selected(self) -> tuple[float, str] | None:
		sel = self.list.GetSelection()
		if sel == wx.NOT_FOUND or not (0 <= sel < len(self.visible)):
			return None
		return self.visible[sel]

	def showSelected(self) -> None:
		item = self.selected()
		self.full.SetValue(item[1] if item else "")
		self.copyButton.Enable(item is not None)

	def copySelected(self) -> None:
		item = self.selected()
		if item is None:
			wx.Bell()
			return
		_copyText(item[1])

	def copyAll(self) -> None:
		if not self.visible:
			wx.Bell()
			return
		_copyText("\n".join(it[1] for it in reversed(self.visible)))

	def export(self) -> None:
		if not self.visible:
			wx.Bell()
			return
		with wx.FileDialog(
			self,
			_("Exportar el historial de voz"),
			defaultFile=_("historial de voz.txt"),
			wildcard=_("Archivos de texto (*.txt)|*.txt"),
			style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
		) as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			path = dlg.GetPath()
		try:
			from ..speech import api as speechApi

			# Hora, origen y texto separados por tabuladores.
			speechApi.exportHistory(path, list(reversed(self.visible)))
		except OSError as e:
			message_dialog.messageBox(_("No se pudo guardar el archivo:\n{error}").format(error=e), _("Error"), wx.OK | wx.ICON_ERROR, self)
			return
		speakMessage(_("Historial exportado"))

	def clear(self) -> None:
		if message_dialog.messageBox(_("¿Borrar todo el historial de voz?"), _("Confirmar"), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self) != wx.YES:
			return
		from ..speech import api as speechApi

		speechApi.clearHistory()
		self.reload()
		self.list.SetFocus()

	def onClose(self, evt: wx.CloseEvent) -> None:
		global _speechDialog
		_speechDialog = None
		self.Destroy()


_speechDialog: SpeechHistoryDialog | None = None


def showSpeechHistory() -> None:
	"""Muestra el historial de voz (seguro desde cualquier hilo)."""

	def _show() -> None:
		global _speechDialog
		if isAlive(_speechDialog):
			_speechDialog.reload()
		else:
			_speechDialog = SpeechHistoryDialog()
			_speechDialog.Show()
		bringToFront(_speechDialog)
		_speechDialog.list.SetFocus()

	runOnGui(_show)


# ------------------------------------------------------------------ portapapeles
class ClipboardHistoryDialog(wx.Dialog):
	def __init__(self) -> None:
		super().__init__(None, title=_("Historial del portapapeles"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
		#: Pares (índice en ``clipboard.history``, texto), el más reciente primero.
		self.items: list[tuple[int, str]] = []
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, _("&Elementos copiados (el más reciente primero):"))
		self.list = wx.ListBox(self, size=(620, 260), style=wx.LB_SINGLE)
		self.list.Bind(wx.EVT_LISTBOX, lambda evt: self.showSelected())
		self.list.Bind(wx.EVT_LISTBOX_DCLICK, lambda evt: self.copySelected())
		self.list.Bind(wx.EVT_KEY_DOWN, self.onListKey)
		sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 6)
		addLabel(self, sizer, _("Texto co&mpleto:"))
		self.full = wx.TextCtrl(self, size=(620, 140), style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
		sizer.Add(self.full, 0, wx.EXPAND | wx.ALL, 6)
		buttons = wx.BoxSizer(wx.HORIZONTAL)
		self.copyButton = wx.Button(self, label=_("&Copiar al portapapeles"))
		self.copyButton.SetDefault()
		self.copyButton.Bind(wx.EVT_BUTTON, lambda evt: self.copySelected())
		self.deleteButton = wx.Button(self, label=_("E&liminar"))
		self.deleteButton.Bind(wx.EVT_BUTTON, lambda evt: self.deleteSelected())
		self.clearButton = wx.Button(self, label=_("&Vaciar"))
		self.clearButton.Bind(wx.EVT_BUTTON, lambda evt: self.clearAll())
		close = wx.Button(self, wx.ID_CANCEL, _("Cerrar"))
		for b in (self.copyButton, self.deleteButton, self.clearButton, close):
			buttons.Add(b, 0, wx.ALL, 4)
		sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.Close(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, self.onClose)
		self.CentreOnScreen()
		self.reload()
		self.list.SetFocus()

	def reload(self, keepSelection: int = 0) -> None:
		from .. import clipboard

		history = list(clipboard.history)
		self.items = [(i, history[i][1]) for i in range(len(history) - 1, -1, -1)]
		self.list.Set([_preview(text) for _i, text in self.items])
		if self.items:
			self.list.SetSelection(min(max(0, keepSelection), len(self.items) - 1))
		self.showSelected()

	def selected(self) -> tuple[int, str] | None:
		sel = self.list.GetSelection()
		if sel == wx.NOT_FOUND or not (0 <= sel < len(self.items)):
			return None
		return self.items[sel]

	def showSelected(self) -> None:
		item = self.selected()
		self.full.SetValue(item[1] if item else "")
		self.copyButton.Enable(item is not None)
		self.deleteButton.Enable(item is not None)
		self.clearButton.Enable(bool(self.items))

	def onListKey(self, evt: wx.KeyEvent) -> None:
		if evt.GetKeyCode() in (wx.WXK_DELETE, wx.WXK_NUMPAD_DELETE) and not evt.HasAnyModifiers():
			self.deleteSelected()
			return
		evt.Skip()

	def copySelected(self) -> None:
		item = self.selected()
		if item is None:
			wx.Bell()
			return
		index, text = item
		self.Close()
		from .. import clipboard

		def _copy() -> None:
			# El índice puede haber cambiado si se copió algo entretanto.
			idx = index
			if not (0 <= idx < len(clipboard.history)) or clipboard.history[idx][1] != text:
				idx = next((i for i in range(len(clipboard.history) - 1, -1, -1) if clipboard.history[i][1] == text), -1)
			if idx >= 0:
				clipboard.copyEntry(idx)
			else:
				from .. import api

				api.copyToClip(text)
			from .. import speech

			speech.speakMessage(_("Copiado al portapapeles"))

		queue_handler.queueFunction(_copy)

	def deleteSelected(self) -> None:
		item = self.selected()
		if item is None:
			wx.Bell()
			return
		index, text = item
		pos = self.list.GetSelection()
		from .. import clipboard

		def _delete() -> None:
			if 0 <= index < len(clipboard.history) and clipboard.history[index][1] == text:
				del clipboard.history[index]
			wx.CallAfter(self._afterChange, pos)

		queue_handler.queueFunction(_delete)

	def clearAll(self) -> None:
		if not self.items:
			return
		if message_dialog.messageBox(_("¿Vaciar el historial del portapapeles?"), _("Confirmar"), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self) != wx.YES:
			return
		from .. import clipboard

		def _clear() -> None:
			clipboard.history.clear()
			wx.CallAfter(self._afterChange, 0)

		queue_handler.queueFunction(_clear)

	def _afterChange(self, pos: int) -> None:
		if isAlive(self):
			self.reload(pos)
			self.list.SetFocus()

	def onClose(self, evt: wx.CloseEvent) -> None:
		global _clipboardDialog
		_clipboardDialog = None
		self.Destroy()


_clipboardDialog: ClipboardHistoryDialog | None = None


def showClipboardHistory() -> None:
	"""Muestra el historial del portapapeles (seguro desde cualquier hilo)."""

	def _show() -> None:
		global _clipboardDialog
		if isAlive(_clipboardDialog):
			_clipboardDialog.reload()
		else:
			_clipboardDialog = ClipboardHistoryDialog()
			_clipboardDialog.Show()
		bringToFront(_clipboardDialog)
		_clipboardDialog.list.SetFocus()

	runOnGui(_show)
