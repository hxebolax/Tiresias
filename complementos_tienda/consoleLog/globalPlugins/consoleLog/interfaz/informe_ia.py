"""Informe de análisis IA: el Markdown de la respuesta como documento HTML navegable."""

from __future__ import annotations

import os

import wx

from tiresias.gui.helpers import speakMessage

from .. import configuracion as cfg
from ..markdown_html import documento_html, markdown_a_html
from .dialogos import guardar_texto
from .webview import WebViewAccesible

TITULO = "Informe de análisis IA"


class InformeIADialog(wx.Dialog):
	"""Documento web con botones nativos; F6 alterna entre ambos y Escape cierra."""

	def __init__(self, parent, informe: str, usar_webview: bool = True) -> None:
		super().__init__(parent, title=TITULO, size=(760, 620), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
		self._informe = informe
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.vista = WebViewAccesible(self, titulo=TITULO, al_volver=self._enfocar_botones, al_cerrar=self._cerrar, contenido_inicial=markdown_a_html(informe), usar_webview=usar_webview)
		sizer.Add(self.vista.control, 1, wx.EXPAND | wx.ALL, 8)
		botones = wx.BoxSizer(wx.HORIZONTAL)
		self.btn_copiar = wx.Button(self, label="&Copiar Markdown")
		self.btn_guardar = wx.Button(self, label="&Guardar...")
		self.btn_navegador = wx.Button(self, label="Abrir en el &navegador")
		self.btn_cerrar = wx.Button(self, wx.ID_CANCEL, "Ce&rrar")
		for b in (self.btn_copiar, self.btn_guardar, self.btn_navegador, self.btn_cerrar):
			botones.Add(b, 0, wx.ALL, 4)
		sizer.Add(botones, 0, wx.ALIGN_CENTER | wx.BOTTOM, 6)
		self.SetSizer(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.btn_copiar.Bind(wx.EVT_BUTTON, self._alCopiar)
		self.btn_guardar.Bind(wx.EVT_BUTTON, lambda e: guardar_texto(self, self._informe, "Guardar el informe", "informe_ia.md"))
		self.btn_navegador.Bind(wx.EVT_BUTTON, lambda e: abrir_en_navegador(TITULO, markdown_a_html(self._informe), "informe_ia.html"))
		self.Bind(wx.EVT_CHAR_HOOK, self._al_tecla)
		self.CentreOnParent()
		wx.CallAfter(self.vista.enfocar)

	def _enfocar_botones(self) -> None:
		self.btn_cerrar.SetFocus()

	def _al_tecla(self, evento) -> None:
		if evento.GetKeyCode() == wx.WXK_F6 and not evento.HasAnyModifiers():
			if self.vista.control.HasFocus() or self.FindFocus() is self.vista.control:
				self._enfocar_botones()
			else:
				self.vista.enfocar()
			return
		evento.Skip()

	def _alCopiar(self, _evt) -> None:
		from tiresias import api

		speakMessage("Informe copiado" if api.copyToClip(self._informe) else "No se pudo copiar")

	def _cerrar(self) -> None:
		from tiresias.gui.helpers import isAlive

		if not isAlive(self):
			return
		if self.IsModal():
			self.EndModal(wx.ID_CANCEL)
		elif self.IsShown():
			self.Close()

	@classmethod
	def mostrar(cls, parent, informe: str) -> None:
		dlg = cls(parent, informe)
		dlg.ShowModal()
		dlg.Destroy()


def abrir_en_navegador(titulo: str, cuerpo_html: str, nombre: str) -> str | None:
	"""Escribe una página HTML en la carpeta de datos del complemento y la abre."""
	try:
		ruta = cfg.rutaDatos(nombre)
		with open(ruta, "w", encoding="utf-8") as f:
			f.write(documento_html(titulo, cuerpo_html))
		os.startfile(ruta)
		return ruta
	except OSError:
		speakMessage("No se pudo abrir el documento HTML")
		return None
