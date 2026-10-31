"""Diálogo «Elementos del historial de voz» del Explorador del historial de voz.

Lista de los elementos recientes (el más reciente primero) con búsqueda,
selección múltiple, cuadro de solo lectura con el texto completo de lo
seleccionado y botones Copiar elemento, Copiar todo, Limpiar historial,
Actualizar y Cerrar. La lista no se actualiza sola: hay que pulsar Actualizar
o volver a abrir el diálogo, como en el original.
"""

from __future__ import annotations

import wx

from tiresias import queue_handler
from tiresias.gui.helpers import addLabel, bringToFront, isAlive, matchesAll, normalizeForSearch, runOnGui

from . import clearHistory, copyText, historyTexts

TITLE = "Elementos del historial de voz"
#: Caracteres de cada elemento que se muestran en la lista (el texto completo va en el cuadro de abajo).
PREVIEW_CHARS = 100
CONFIRM_CLEAR = "¿Limpiar todo el historial de voz de Tiresias?"


def preview(text: str) -> str:
	line = " ".join(text.split())
	return line if len(line) <= PREVIEW_CHARS else line[:PREVIEW_CHARS] + "…"


def filterHistory(items: list[str], query: str) -> list[str]:
	"""Elementos que contienen todas las palabras de ``query`` (sin distinguir mayúsculas ni tildes)."""
	query = query.strip()
	if not query:
		return list(items)
	return [it for it in items if matchesAll(normalizeForSearch(it), query)]


class HistoryDialog(wx.Dialog):
	def __init__(self, plugin=None) -> None:
		super().__init__(None, title=TITLE, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
		#: El complemento (para olvidar la posición de navegación al limpiar).
		self.plugin = plugin
		#: Historial completo, el más reciente primero.
		self.history: list[str] = []
		#: Elementos que se muestran (resultado de la búsqueda actual).
		self.visible: list[str] = []
		#: Elemento enfocado en cada búsqueda, para volver a él.
		self.searches: dict[str, int] = {"": 0}
		self.curSearch = ""
		self.closed = False

		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, "&Buscar:")
		self.search = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
		self.search.Bind(wx.EVT_TEXT_ENTER, self.onSearch)
		self.search.Bind(wx.EVT_KILL_FOCUS, self.onSearch)
		sizer.Add(self.search, 0, wx.EXPAND | wx.ALL, 6)

		addLabel(self, sizer, "&Lista del historial (el más reciente primero):")
		self.list = wx.ListCtrl(self, size=(640, 260), style=wx.LC_REPORT | wx.LC_NO_HEADER)
		# Una sola columna; la cabecera no se ve (LC_NO_HEADER).
		self.list.InsertColumn(0, "Elemento")
		self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda evt: self.updateSelection())
		self.list.Bind(wx.EVT_LIST_ITEM_DESELECTED, lambda evt: self.updateSelection())
		self.list.Bind(wx.EVT_SIZE, self.onListSize)
		sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 6)

		addLabel(self, sizer, "&Texto de los elementos seleccionados:")
		self.full = wx.TextCtrl(self, size=(640, 120), style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
		sizer.Add(self.full, 0, wx.EXPAND | wx.ALL, 6)

		buttons = wx.BoxSizer(wx.HORIZONTAL)
		self.copyButton = wx.Button(self, label="Copiar &elemento")
		self.copyButton.Bind(wx.EVT_BUTTON, lambda evt: self.copySelected())
		self.copyButton.SetDefault()
		self.copyAllButton = wx.Button(self, label="Copiar t&odo")
		self.copyAllButton.Bind(wx.EVT_BUTTON, lambda evt: self.copyAll())
		self.clearButton = wx.Button(self, label="Li&mpiar historial")
		self.clearButton.Bind(wx.EVT_BUTTON, lambda evt: self.clear())
		self.refreshButton = wx.Button(self, label="&Actualizar")
		self.refreshButton.Bind(wx.EVT_BUTTON, lambda evt: self.reload())
		close = wx.Button(self, wx.ID_CANCEL, "Cerrar")
		for b in (self.copyButton, self.copyAllButton, self.clearButton, self.refreshButton, close):
			buttons.Add(b, 0, wx.ALL, 4)
		sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 4)

		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.Close(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, self.onClose)
		self.CentreOnScreen()
		self.reload()
		self.list.SetFocus()

	# ---------------------------------------------------------------- datos
	def reload(self) -> None:
		"""Vuelve a leer el historial de Tiresias y aplica la búsqueda actual."""
		self.history = list(reversed(historyTexts()))
		self.applySearch(self.curSearch)

	def applySearch(self, query: str) -> None:
		self.visible = filterHistory(self.history, query)
		self.list.DeleteAllItems()
		for i, text in enumerate(self.visible):
			self.list.InsertItem(i, preview(text))
		self.fitColumn()
		if self.visible:
			index = min(self.searches.get(query, 0), len(self.visible) - 1)
			self.list.Select(index)
			self.list.Focus(index)
		self.updateSelection()

	def selectedIndexes(self) -> list[int]:
		out: list[int] = []
		i = self.list.GetFirstSelected()
		while i != -1:
			out.append(i)
			i = self.list.GetNextSelected(i)
		return out

	def selectedText(self) -> str:
		return "\n".join(self.visible[i] for i in self.selectedIndexes() if 0 <= i < len(self.visible))

	def updateSelection(self) -> None:
		text = self.selectedText()
		self.full.SetValue(text)
		self.copyButton.Enable(bool(text))
		self.copyAllButton.Enable(bool(self.visible))

	# ---------------------------------------------------------------- eventos
	def onListSize(self, evt: wx.SizeEvent) -> None:
		evt.Skip()
		self.fitColumn()

	def fitColumn(self) -> None:
		width = self.list.GetClientSize().width
		if width > 0:
			self.list.SetColumnWidth(0, width)

	def onSearch(self, evt: wx.Event) -> None:
		evt.Skip()
		query = self.search.GetValue().strip()
		if query == self.curSearch:
			return
		focused = self.list.GetFocusedItem()
		self.searches[self.curSearch] = focused if focused >= 0 else 0
		self.curSearch = query
		self.applySearch(query)

	def copySelected(self) -> None:
		text = self.full.GetValue()
		if not text:
			wx.Bell()
			return
		queue_handler.queueFunction(copyText, text)

	def copyAll(self) -> None:
		"""Copia todos los elementos de la lista (solo los encontrados si hay una búsqueda), uno por línea."""
		if not self.visible:
			wx.Bell()
			return
		queue_handler.queueFunction(copyText, "\n".join(self.visible))

	def confirmClear(self) -> bool:
		from tiresias.gui import message_dialog

		return message_dialog.messageBox(CONFIRM_CLEAR, "Confirmar", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self) == wx.YES

	def clear(self) -> None:
		"""Limpia el historial de Tiresias (previa confirmación) y cierra el diálogo, como el original."""
		if not self.confirmClear():
			return
		queue_handler.queueFunction(clearHistory)
		if self.plugin is not None:
			self.plugin.resetPosition()
		self.searches = {"": 0}
		self.Close()

	def onClose(self, evt: wx.CloseEvent) -> None:
		global _dialog
		self.closed = True
		if _dialog is self:
			_dialog = None
		self.Destroy()


_dialog: HistoryDialog | None = None


def showHistoryDialog(plugin=None) -> None:
	"""Muestra el diálogo (seguro desde cualquier hilo); si ya está abierto lo actualiza y lo trae al frente."""

	def _show() -> None:
		global _dialog
		if isAlive(_dialog):
			_dialog.reload()
		else:
			_dialog = HistoryDialog(plugin)
			_dialog.Show()
		bringToFront(_dialog)
		_dialog.list.SetFocus()

	runOnGui(_show)


def closeDialog() -> None:
	"""Cierra el diálogo si está abierto (al descargar el complemento)."""

	def _close() -> None:
		if isAlive(_dialog):
			_dialog.Close()

	runOnGui(_close)
