"""Ventana con el resultado de una traducción (opción «Mostrar resultados en ventana»)."""

from __future__ import annotations

from typing import Any

import wx

from tiresias.gui.helpers import bringToFront


class DialogoResultado(wx.Dialog):
	def __init__(self, parent: wx.Window | None, texto_original: str, texto_traducido: str, portapapeles: Any = None) -> None:
		super().__init__(parent, title="Resultado de la traducción", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.texto_original = texto_original
		self.texto_traducido = texto_traducido
		self.portapapeles = portapapeles
		sizer = wx.BoxSizer(wx.VERTICAL)
		# La traducción primero: es lo que se quiere leer al abrirse.
		sizer.Add(wx.StaticText(self, label="&Traducción:"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
		self.txt_traducido = wx.TextCtrl(self, value=texto_traducido, size=(560, 140), style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
		sizer.Add(self.txt_traducido, 1, wx.EXPAND | wx.ALL, 8)
		sizer.Add(wx.StaticText(self, label="Texto &original:"), 0, wx.LEFT | wx.RIGHT, 8)
		self.txt_original = wx.TextCtrl(self, value=texto_original, size=(560, 120), style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
		sizer.Add(self.txt_original, 1, wx.EXPAND | wx.ALL, 8)
		botones = wx.BoxSizer(wx.HORIZONTAL)
		self.btn_copiar_traduccion = wx.Button(self, label="&Copiar traducción")
		self.btn_copiar_original = wx.Button(self, label="Copiar ori&ginal")
		self.btn_cerrar = wx.Button(self, wx.ID_CLOSE, "C&errar")
		for b in (self.btn_copiar_traduccion, self.btn_copiar_original):
			botones.Add(b, 0, wx.ALL, 4)
		botones.AddStretchSpacer()
		botones.Add(self.btn_cerrar, 0, wx.ALL, 4)
		sizer.Add(botones, 0, wx.EXPAND | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CLOSE)
		self.btn_copiar_original.Bind(wx.EVT_BUTTON, lambda e: self._copiar(self.texto_original))
		self.btn_copiar_traduccion.Bind(wx.EVT_BUTTON, lambda e: self._copiar(self.texto_traducido))
		self.btn_cerrar.Bind(wx.EVT_BUTTON, lambda e: self.Close())
		self.Bind(wx.EVT_CLOSE, lambda e: self.Destroy())
		self.CentreOnScreen()

	def _copiar(self, texto: str) -> None:
		if self.portapapeles:
			ok = self.portapapeles.establecer_texto(texto)
		else:
			ok = False
			if wx.TheClipboard.Open():
				try:
					ok = wx.TheClipboard.SetData(wx.TextDataObject(texto))
				finally:
					wx.TheClipboard.Close()
		from ..utilidades import lector

		lector.mensaje("Copiado al portapapeles" if ok else "No se pudo copiar")

	def mostrar(self) -> None:
		self.Show()
		bringToFront(self)
		self.txt_traducido.SetFocus()
