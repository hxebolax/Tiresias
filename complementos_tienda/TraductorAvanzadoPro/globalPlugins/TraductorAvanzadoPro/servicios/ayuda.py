"""Ayuda contextual de los controles (Control+H) en los diálogos del complemento."""

from __future__ import annotations

import wx


class AyudaDialogo(wx.Dialog):
	"""Muestra el texto de ayuda de un control en un campo de solo lectura."""

	def __init__(self, parent: wx.Window | None, titulo: str, mensaje: str) -> None:
		super().__init__(parent, title=titulo, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(wx.StaticText(self, label="&Ayuda:"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
		self.texto = wx.TextCtrl(self, value=mensaje, size=(420, 140), style=wx.TE_MULTILINE | wx.TE_READONLY)
		sizer.Add(self.texto, 1, wx.EXPAND | wx.ALL, 10)
		aceptar = wx.Button(self, wx.ID_OK, "&Aceptar")
		aceptar.SetDefault()
		sizer.Add(aceptar, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_OK)
		self.CentreOnParent()
		self.texto.SetFocus()


class GestorAyuda:
	"""Asocia textos de ayuda a controles; Control+H los muestra."""

	def __init__(self) -> None:
		self.ayudas: dict[int, str] = {}

	def agregar_ayuda(self, widget: wx.Window, mensaje: str) -> None:
		self.ayudas[id(widget)] = mensaje
		widget.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

	def ayuda_existe(self, widget: wx.Window) -> bool:
		return id(widget) in self.ayudas

	def texto_ayuda(self, widget: wx.Window) -> str:
		return self.ayudas.get(id(widget), "No hay ayuda disponible para este elemento.")

	def mostrar_ayuda(self, widget: wx.Window) -> None:
		dlg = AyudaDialogo(wx.GetTopLevelParent(widget), "Ayuda", self.texto_ayuda(widget))
		dlg.ShowModal()
		dlg.Destroy()
		try:
			widget.SetFocus()
		except RuntimeError:
			pass

	def _on_char_hook(self, event: wx.KeyEvent) -> None:
		if event.GetKeyCode() in (ord("H"), ord("h")) and event.GetModifiers() == wx.MOD_CONTROL:
			self.mostrar_ayuda(event.GetEventObject())
			return
		event.Skip()
