"""Diálogo de progreso de operaciones largas (descarga del audio, etc.)."""

from __future__ import annotations

from typing import Callable

import wx


class DialogoProgreso(wx.Dialog):
	"""Barra de progreso con porcentaje y botón Cancelar.

	:meth:`actualizar` se puede llamar desde cualquier hilo.
	"""

	def __init__(self, parent: wx.Window | None, titulo: str = "Progreso", mensaje: str = "Procesando...", maximo: int = 100, cancelable: bool = True) -> None:
		super().__init__(parent, title=titulo, style=wx.DEFAULT_DIALOG_STYLE)
		self.maximo = maximo
		self.cancelable = cancelable
		self._cancelado = False
		self._callback_cancelar: Callable[[], None] | None = None
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.lbl_mensaje = wx.StaticText(self, label=mensaje)
		sizer.Add(self.lbl_mensaje, 0, wx.ALL, 10)
		self.barra_progreso = wx.Gauge(self, range=maximo, size=(400, 25))
		self.barra_progreso.SetName(mensaje)
		sizer.Add(self.barra_progreso, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
		self.lbl_porcentaje = wx.StaticText(self, label="0%")
		sizer.Add(self.lbl_porcentaje, 0, wx.ALIGN_CENTER | wx.ALL, 5)
		if cancelable:
			self.btn_cancelar = wx.Button(self, wx.ID_CANCEL, "&Cancelar")
			self.btn_cancelar.Bind(wx.EVT_BUTTON, self._on_cancelar)
			sizer.Add(self.btn_cancelar, 0, wx.ALIGN_CENTER | wx.ALL, 10)
			self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, self._on_cerrar_ventana)
		self.SetSizerAndFit(sizer)
		self.CentreOnParent()

	def actualizar(self, valor: int, mensaje: str | None = None) -> bool:
		"""Pone el progreso (0-``maximo``). ``False`` si se ha cancelado."""
		if self._cancelado:
			return False
		if not wx.IsMainThread():
			wx.CallAfter(self.actualizar, valor, mensaje)
			return True
		try:
			self.barra_progreso.SetValue(max(0, min(int(valor), self.maximo)))
			self.lbl_porcentaje.SetLabel(f"{int(valor * 100 / self.maximo)}%")
			if mensaje:
				self.lbl_mensaje.SetLabel(mensaje)
		except RuntimeError:
			return False
		return True

	def actualizar_porcentaje(self, porcentaje: float, mensaje: str | None = None) -> bool:
		return self.actualizar(int(porcentaje / 100 * self.maximo), mensaje)

	def establecer_callback_cancelar(self, callback: Callable[[], None]) -> None:
		self._callback_cancelar = callback

	def _on_cancelar(self, event: wx.CommandEvent | None) -> None:
		self._cancelado = True
		if self._callback_cancelar:
			try:
				self._callback_cancelar()
			except Exception:
				pass
		if self.IsModal():
			self.EndModal(wx.ID_CANCEL)
		else:
			self.Destroy()

	def _on_cerrar_ventana(self, event: wx.CloseEvent) -> None:
		if self.cancelable:
			self._on_cancelar(None)
		else:
			event.Veto()

	@property
	def fue_cancelado(self) -> bool:
		return self._cancelado

	def cerrar(self) -> None:
		"""Cierra el diálogo tras terminar (desde cualquier hilo)."""
		if not wx.IsMainThread():
			wx.CallAfter(self.cerrar)
			return
		try:
			if self.IsModal():
				self.EndModal(wx.ID_OK)
			else:
				self.Destroy()
		except RuntimeError:
			pass
