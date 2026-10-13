"""Diálogo del lanzador de consolas."""

from __future__ import annotations

import wx

from tiresias.gui.helpers import speakMessage

from .. import configuracion as cfg
from ..lanzador import GestorLanzador, OpcionConsola


class LanzadorDialogo(wx.Dialog):
	def __init__(self, parent, gestor: GestorLanzador, directorio: str) -> None:
		super().__init__(parent, title="Lanzador de consolas", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._gestor = gestor
		self._directorio = directorio
		self._opciones: list[OpcionConsola] = gestor.opciones(bool(cfg.valor("lanzadorMostrarNoDisponibles")))
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.etiqueta_dir = wx.StaticText(self, label="Directorio: {}".format(directorio))
		sizer.Add(self.etiqueta_dir, 0, wx.ALL | wx.EXPAND, 10)
		sizer.Add(wx.StaticText(self, label="&Seleccione una consola:"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
		self.lista = wx.ListBox(self, choices=[o.nombre for o in self._opciones], size=(420, 260), style=wx.LB_SINGLE)
		sizer.Add(self.lista, 1, wx.EXPAND | wx.ALL, 10)
		botones = wx.BoxSizer(wx.HORIZONTAL)
		self.boton_abrir = wx.Button(self, wx.ID_OK, "&Abrir")
		self.boton_abrir.SetDefault()
		self.boton_cancelar = wx.Button(self, wx.ID_CANCEL, "&Cancelar")
		botones.Add(self.boton_abrir, 0, wx.RIGHT, 5)
		botones.Add(self.boton_cancelar)
		sizer.Add(botones, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.CentreOnScreen()
		if self._opciones:
			self.lista.SetSelection(self._seleccion_inicial())
		self.boton_abrir.Bind(wx.EVT_BUTTON, self._al_abrir)
		self.lista.Bind(wx.EVT_LISTBOX_DCLICK, self._al_abrir)
		self.Bind(wx.EVT_CHAR_HOOK, self._al_tecla)
		wx.CallAfter(self.lista.SetFocus)

	def _seleccion_inicial(self) -> int:
		if not cfg.valor("lanzadorRecordarUltima"):
			return 0
		ultima = str(cfg.valor("lanzadorUltimaOpcion") or "")
		for i, o in enumerate(self._opciones):
			if o.clave == ultima:
				return i
		return 0

	def _al_tecla(self, evento) -> None:
		if evento.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and self.FindFocus() is self.lista:
			self.ejecutar_seleccion()
			return
		evento.Skip()

	def _al_abrir(self, _evento) -> None:
		self.ejecutar_seleccion()

	def opcion_seleccionada(self) -> OpcionConsola | None:
		i = self.lista.GetSelection()
		return self._opciones[i] if 0 <= i < len(self._opciones) else None

	def ejecutar_seleccion(self) -> bool:
		from tiresias.gui import messageBox

		opcion = self.opcion_seleccionada()
		if opcion is None:
			return False
		if not opcion.disponible:
			messageBox("Esta consola no está instalada en el equipo.", "Lanzador de consolas", wx.OK | wx.ICON_INFORMATION, self)
			return False
		if cfg.valor("lanzadorRecordarUltima"):
			cfg.establecer("lanzadorUltimaOpcion", opcion.clave)

		def alError(mensaje: str) -> None:
			speakMessage("Error al abrir la consola: {}".format(mensaje))

		try:
			self._gestor.abrir_consola(opcion.tipo, self._directorio, opcion.como_admin, opcion.script_vs, alError)
		except Exception as e:  # noqa: BLE001
			messageBox("Error al abrir la consola: {}".format(e), "Error", wx.OK | wx.ICON_ERROR, self)
			return False
		self.EndModal(wx.ID_OK)
		return True
