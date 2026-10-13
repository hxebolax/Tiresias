"""Lista de posiciones del ratón guardadas para la aplicación actual."""

from __future__ import annotations

import wx

from .. import queue_handler
from ..i18n import _
from .helpers import addLabel, bringToFront, isAlive, runOnGui


class PositionsDialog(wx.Dialog):
	def __init__(self, app: str, names: list[str]) -> None:
		super().__init__(None, title=_("Posiciones guardadas en {app}").format(app=app))
		self.app = app
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, _("&Posiciones:"))
		self.list = wx.ListBox(self, choices=names, size=(320, 200))
		if names:
			self.list.SetSelection(0)
		sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 6)
		row = wx.BoxSizer(wx.HORIZONTAL)
		buttons = [
			(_("&Ir"), None),
			(_("&Clic"), "left"),
			(_("Clic &derecho"), "right"),
			(_("D&oble clic"), "double"),
		]
		for label, click in buttons:
			b = wx.Button(self, label=label)
			b.Bind(wx.EVT_BUTTON, lambda evt, c=click: self.go(c))
			row.Add(b, 0, wx.RIGHT, 4)
		delete = wx.Button(self, label=_("&Borrar"))
		delete.Bind(wx.EVT_BUTTON, lambda evt: self.delete())
		row.Add(delete, 0, wx.RIGHT, 4)
		close = wx.Button(self, wx.ID_CANCEL, _("C&errar"))
		row.Add(close, 0)
		sizer.Add(row, 0, wx.ALL, 6)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		# Escape, Cerrar y la X destruyen el diálogo (antes solo lo ocultaban).
		self.Bind(wx.EVT_BUTTON, lambda evt: self.Destroy(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, lambda evt: self.Destroy())
		self.list.Bind(wx.EVT_LISTBOX_DCLICK, lambda evt: self.go(None))
		self.list.Bind(wx.EVT_KEY_DOWN, self.onKey)
		self.CentreOnScreen()

	def onKey(self, evt: wx.KeyEvent) -> None:
		if evt.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
			self.go(None)
		elif evt.GetKeyCode() == wx.WXK_DELETE:
			self.delete()
		else:
			evt.Skip()

	def _selected(self) -> str | None:
		i = self.list.GetSelection()
		return self.list.GetString(i) if i != wx.NOT_FOUND else None

	def go(self, click: str | None) -> None:
		name = self._selected()
		if name is None:
			wx.Bell()
			return
		app = self.app
		self.Destroy()
		from .. import mouse_keys

		# Se espera a que el foco vuelva a la aplicación antes de mover o hacer clic.
		queue_handler.callLater(250, mouse_keys.jumpTo, name, click, app)

	def delete(self) -> None:
		name = self._selected()
		if name is None:
			wx.Bell()
			return
		from .. import mouse_keys

		app = self.app
		queue_handler.queueFunction(mouse_keys.deletePosition, name, app)
		self.list.Delete(self.list.GetSelection())
		if self.list.GetCount():
			self.list.SetSelection(0)
		from .helpers import speakMessage

		speakMessage(_("Posición {name} borrada").format(name=name))


_dialog: PositionsDialog | None = None


def show(app: str, names: list[str]) -> None:
	def _show() -> None:
		global _dialog
		if isAlive(_dialog):
			_dialog.Destroy()
		_dialog = PositionsDialog(app, names)
		_dialog.Show()
		bringToFront(_dialog)
		_dialog.list.SetFocus()

	runOnGui(_show)
