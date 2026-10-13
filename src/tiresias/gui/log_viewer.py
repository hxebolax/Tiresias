"""Visor del registro de Tiresias."""

from __future__ import annotations

import wx

from . import message_dialog
from ..i18n import _
from ..log import getLogger
from .helpers import addLabel, bringToFront, isAlive, runOnGui, speakMessage

log = getLogger("gui.logViewer")


class LogViewerDialog(wx.Dialog):
	def __init__(self) -> None:
		super().__init__(None, title=_("Visor de registro"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, _("&Registro:"))
		self.text = wx.TextCtrl(self, size=(760, 460), style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.TE_DONTWRAP)
		sizer.Add(self.text, 1, wx.EXPAND | wx.ALL, 6)
		buttons = wx.BoxSizer(wx.HORIZONTAL)
		refresh = wx.Button(self, label=_("&Actualizar"))
		refresh.Bind(wx.EVT_BUTTON, lambda evt: self.refresh(True))
		save = wx.Button(self, label=_("&Guardar como..."))
		save.Bind(wx.EVT_BUTTON, lambda evt: self.saveAs())
		close = wx.Button(self, wx.ID_CANCEL, _("&Cerrar"))
		for b in (refresh, save, close):
			buttons.Add(b, 0, wx.ALL, 4)
		sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.Close(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, self.onClose)
		self.Bind(wx.EVT_CHAR_HOOK, self.onCharHook)
		self.CentreOnScreen()
		self.refresh()

	def refresh(self, focusText: bool = False) -> None:
		from .. import log as logModule

		self.text.SetValue(logModule.getLogText())
		# Lo más reciente está al final: el cursor va al principio de la última línea.
		last = self.text.GetLastPosition()
		lineNo = max(0, self.text.GetNumberOfLines() - 1)
		pos = self.text.XYToPosition(0, lineNo)
		self.text.SetInsertionPoint(pos if pos >= 0 else last)
		self.text.ShowPosition(last)
		if focusText:
			self.text.SetFocus()

	def onCharHook(self, evt: wx.KeyEvent) -> None:
		key = evt.GetKeyCode()
		if key == wx.WXK_F5 and not evt.HasAnyModifiers():
			self.refresh(True)
			return
		if evt.GetModifiers() == wx.MOD_CONTROL and key in (ord("A"), ord("a")) and self.FindFocus() is self.text:
			self.text.SelectAll()
			return
		evt.Skip()

	def saveAs(self) -> None:
		with wx.FileDialog(
			self,
			_("Guardar el registro"),
			defaultFile="tiresias.log",
			wildcard=_("Archivos de registro (*.log)|*.log|Archivos de texto (*.txt)|*.txt"),
			style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
		) as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			path = dlg.GetPath()
		try:
			with open(path, "w", encoding="utf-8") as f:
				f.write(self.text.GetValue())
		except OSError as e:
			message_dialog.messageBox(_("No se pudo guardar el archivo:\n{error}").format(error=e), _("Error"), wx.OK | wx.ICON_ERROR, self)
			return
		speakMessage(_("Registro guardado"))

	def onClose(self, evt: wx.CloseEvent) -> None:
		global _dialog
		_dialog = None
		self.Destroy()


_dialog: LogViewerDialog | None = None


def show() -> None:
	"""Abre el visor de registro (seguro desde cualquier hilo)."""
	from ..config import policy as _pol

	if not _pol.isAllowed("logViewer"):
		# Modo seguro (escritorio seguro): el registro tiene lo dicho en la sesión.
		speakMessage(_pol.blockedMessage())
		return

	def _show() -> None:
		global _dialog
		if isAlive(_dialog):
			_dialog.refresh()
		else:
			_dialog = LogViewerDialog()
			_dialog.Show()
		bringToFront(_dialog)
		_dialog.text.SetFocus()

	runOnGui(_show)
