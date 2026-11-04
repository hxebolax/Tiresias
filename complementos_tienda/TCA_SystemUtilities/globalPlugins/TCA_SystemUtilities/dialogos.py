"""Diálogos de TCA SystemUtilities (llamar en el hilo de la interfaz).

- :func:`preguntar`: pregunta Sí/No con el cuadro de mensaje de Tiresias.
- :func:`pedirTexto`: cuadro para escribir el nombre de una aplicación.
- :class:`DialogoPerfilLimpieza`: aviso del perfil de limpieza de disco.
- :class:`DialogoConsolas`: lanzador de consolas.
"""

from __future__ import annotations

from contextlib import contextmanager

import wx

#: Respuestas del diálogo del perfil de limpieza.
CREAR_PERFIL = "crear"
LIMPIAR = "limpiar"


@contextmanager
def _emergente():
	"""Pone la ventana de Tiresias en primer plano mientras dura el diálogo."""
	from tiresias import gui

	marco = getattr(gui, "mainFrame", None)
	try:
		vivo = marco is not None and bool(gui.isAlive(marco))
	except Exception:
		vivo = marco is not None
	if vivo:
		marco.prePopup()
	try:
		yield marco if vivo else None
	finally:
		if vivo:
			marco.postPopup()


def preguntar(texto: str, titulo: str) -> bool:
	from tiresias import gui

	return gui.messageBox(texto, titulo, wx.YES_NO | wx.ICON_QUESTION) == wx.YES


def pedirTexto(texto: str, titulo: str) -> str | None:
	"""El texto escrito, o ``None`` si se cancela."""
	with _emergente() as marco:
		dlg = wx.TextEntryDialog(marco, texto, titulo)
		try:
			dlg.Raise()
			if dlg.ShowModal() != wx.ID_OK:
				return None
			return dlg.GetValue()
		finally:
			dlg.Destroy()


class DialogoPerfilLimpieza(wx.Dialog):
	"""Primera vez de «Limpiar disco»: crear el perfil de limpieza o limpiar ya."""

	TEXTO = (
		"Si es la primera vez que ejecuta esta acción, es necesario crear un perfil de limpieza; solo debe hacerlo una vez.\n"
		"En el perfil marque las casillas de todo lo que quiera limpiar y pulse Aceptar; después empieza la limpieza.\n"
		"Puede pulsar «Crear perfil» también si desea modificar uno existente, o marcar la casilla para no volver a mostrar este mensaje."
	)

	def __init__(self, parent) -> None:
		super().__init__(parent, title="Limpiar disco")
		self.respuesta: str | None = None
		sizer = wx.BoxSizer(wx.VERTICAL)
		texto = wx.TextCtrl(self, value=self.TEXTO, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_NO_VSCROLL, size=(460, 110))
		texto.SetName("Aviso")
		sizer.Add(texto, 0, wx.ALL | wx.EXPAND, 8)
		self.noMostrar = wx.CheckBox(self, label="&No volver a mostrar este mensaje")
		sizer.Add(self.noMostrar, 0, wx.LEFT | wx.RIGHT, 8)
		botones = wx.BoxSizer(wx.HORIZONTAL)
		self.btnCrear = wx.Button(self, wx.ID_OK, "&Crear perfil")
		self.btnLimpiar = wx.Button(self, wx.ID_ANY, "&Limpiar sin crear perfil")
		self.btnCancelar = wx.Button(self, wx.ID_CANCEL, "Cancelar")
		for b in (self.btnCrear, self.btnLimpiar, self.btnCancelar):
			botones.Add(b, 0, wx.ALL, 4)
		sizer.Add(botones, 0, wx.ALL | wx.ALIGN_RIGHT, 4)
		self.SetSizerAndFit(sizer)
		self.btnCrear.SetDefault()
		self.btnCrear.Bind(wx.EVT_BUTTON, lambda e: self._fin(CREAR_PERFIL))
		self.btnLimpiar.Bind(wx.EVT_BUTTON, lambda e: self._fin(LIMPIAR))
		self.btnCancelar.Bind(wx.EVT_BUTTON, lambda e: self._fin(None))
		self.SetEscapeId(wx.ID_CANCEL)
		self.CentreOnScreen()
		texto.SetFocus()

	def _fin(self, respuesta: str | None) -> None:
		self.respuesta = respuesta
		self.EndModal(wx.ID_OK if respuesta else wx.ID_CANCEL)


def perfilLimpieza() -> tuple[str | None, bool]:
	"""(respuesta, no volver a mostrar)."""
	with _emergente() as marco:
		dlg = DialogoPerfilLimpieza(marco)
		try:
			dlg.Raise()
			dlg.ShowModal()
			return dlg.respuesta, dlg.noMostrar.GetValue()
		finally:
			dlg.Destroy()


class DialogoConsolas(wx.Dialog):
	"""Lista de consolas: Intro abre la elegida y Escape cierra."""

	def __init__(self, parent, opciones: list, carpeta: str) -> None:
		super().__init__(parent, title="Lanzador de consolas")
		self.opciones = list(opciones)
		self.elegida = None
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(wx.StaticText(self, label=f"&Consolas (se abren en {carpeta}):"), 0, wx.ALL, 6)
		self.lista = wx.ListBox(self, choices=[o.etiqueta for o in self.opciones], style=wx.LB_SINGLE, size=(380, 180))
		if self.opciones:
			self.lista.SetSelection(0)
		sizer.Add(self.lista, 1, wx.ALL | wx.EXPAND, 6)
		botones = wx.StdDialogButtonSizer()
		self.btnAbrir = wx.Button(self, wx.ID_OK, "&Abrir")
		self.btnCancelar = wx.Button(self, wx.ID_CANCEL, "Cancelar")
		botones.AddButton(self.btnAbrir)
		botones.AddButton(self.btnCancelar)
		botones.Realize()
		sizer.Add(botones, 0, wx.ALL | wx.EXPAND, 6)
		self.SetSizerAndFit(sizer)
		self.btnAbrir.SetDefault()
		self.btnAbrir.Bind(wx.EVT_BUTTON, self.onAbrir)
		self.lista.Bind(wx.EVT_LISTBOX_DCLICK, self.onAbrir)
		self.lista.Bind(wx.EVT_CHAR_HOOK, self.onTecla)
		self.CentreOnScreen()
		self.lista.SetFocus()

	def onTecla(self, evt) -> None:
		if evt.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
			self.onAbrir(evt)
			return
		evt.Skip()

	def onAbrir(self, evt=None) -> None:
		i = self.lista.GetSelection()
		if i == wx.NOT_FOUND:
			return
		self.elegida = self.opciones[i]
		self.EndModal(wx.ID_OK)


def elegirConsola(opciones: list, carpeta: str):
	"""La opción elegida, o ``None`` si se cierra el diálogo."""
	with _emergente() as marco:
		dlg = DialogoConsolas(marco, opciones, carpeta)
		try:
			dlg.Raise()
			dlg.ShowModal()
			return dlg.elegida
		finally:
			dlg.Destroy()
