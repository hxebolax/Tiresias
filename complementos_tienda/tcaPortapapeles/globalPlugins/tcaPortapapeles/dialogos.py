"""Ventanas de TCA-Portapapeles: historial y selector de trozos de texto.

Solo puede haber una abierta a la vez (como en el original). Se crean y se
manejan en el hilo de la interfaz; lo que toca el portapapeles se hace en el
hilo del núcleo o en el del complemento.
"""

from __future__ import annotations

import wx

from tiresias import queue_handler
from tiresias.gui.helpers import addLabel, bringToFront, isAlive, runOnGui

from . import texto as textoMod

TITULO_HISTORIAL = "Historial de TCA-Portapapeles"
TITULO_PARTES = "Selector de trozos de texto para copiar al portapapeles"
#: Caracteres de cada elemento que se muestran en la lista.
PREVISTA = 300
MSG_NINGUNA = "No tiene seleccionada ninguna palabra.\n\nSeleccione al menos una para copiar al portapapeles."
MSG_CONFIRMAR_BORRAR = "¿Borrar todas las entradas del historial de TCA-Portapapeles?"

#: Ventana abierta (historial o selector de trozos).
_ventana: wx.Dialog | None = None


def prevista(texto: str) -> str:
	linea = " ".join(texto.split())
	return linea if len(linea) <= PREVISTA else linea[:PREVISTA] + "…"


def hayVentana() -> bool:
	return isAlive(_ventana)


def ventanaAbierta():
	return _ventana if isAlive(_ventana) else None


def _hablar(texto: str) -> None:
	from tiresias import speech

	queue_handler.queueFunction(speech.speakMessage, texto)


# ====================================================================== historial
class HistorialDialogo(wx.Dialog):
	def __init__(self, plugin) -> None:
		super().__init__(None, title=TITULO_HISTORIAL, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
		self.plugin = plugin
		#: Elementos mostrados (el más reciente primero).
		self.elementos: list = []
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, "&Historial:")
		self.lista = wx.ListBox(self, size=(640, 320), style=wx.LB_SINGLE | wx.LB_NEEDED_SB)
		self.lista.Bind(wx.EVT_LISTBOX_DCLICK, lambda evt: self.pegar())
		sizer.Add(self.lista, 1, wx.EXPAND | wx.ALL, 6)
		botones = wx.BoxSizer(wx.HORIZONTAL)
		self.pegarBTN = wx.Button(self, label="&Pegar en el foco")
		self.pegarBTN.Bind(wx.EVT_BUTTON, lambda evt: self.pegar())
		self.borrarBTN = wx.Button(self, label="&Borrar")
		self.borrarBTN.Bind(wx.EVT_BUTTON, lambda evt: self.borrar())
		self.borrarTodoBTN = wx.Button(self, label="Borrar &todo")
		self.borrarTodoBTN.Bind(wx.EVT_BUTTON, lambda evt: self.borrarTodo())
		self.refrescarBTN = wx.Button(self, label="&Refrescar")
		self.refrescarBTN.Bind(wx.EVT_BUTTON, lambda evt: self.refrescar())
		self.cerrarBTN = wx.Button(self, wx.ID_CANCEL, "&Cerrar")
		for b in (self.pegarBTN, self.borrarBTN, self.borrarTodoBTN, self.refrescarBTN, self.cerrarBTN):
			botones.Add(b, 0, wx.ALL, 4)
		sizer.Add(botones, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.Close(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, self.alCerrar)
		self.Bind(wx.EVT_CHAR_HOOK, self.alPulsarTecla)
		self.CentreOnScreen()
		self.refrescar()

	def refrescar(self, posicion: int = 0) -> None:
		"""Vuelve a leer el historial (cierra la ventana si se ha quedado vacío)."""
		self.elementos = self.plugin.historial.elementos
		if not self.elementos:
			self.Close()
			return
		self.lista.Set([prevista(e.texto) for e in self.elementos])
		self.lista.SetSelection(min(max(0, posicion), len(self.elementos) - 1))
		self.lista.SetFocus()

	def seleccionado(self):
		sel = self.lista.GetSelection()
		if sel == wx.NOT_FOUND or not (0 <= sel < len(self.elementos)):
			return None
		return self.elementos[sel]

	def alPulsarTecla(self, evt: wx.KeyEvent) -> None:
		tecla = evt.GetKeyCode()
		if wx.Window.FindFocus() is self.lista and not evt.HasAnyModifiers():
			if tecla in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
				self.pegar()
				return
			if tecla in (wx.WXK_DELETE, wx.WXK_NUMPAD_DELETE):
				self.borrar()
				return
		evt.Skip()

	def pegar(self) -> None:
		"""Pega el elemento elegido en la aplicación que estaba detrás de la ventana."""
		el = self.seleccionado()
		if el is None:
			wx.Bell()
			return
		self.Close()
		self.plugin.pegarElemento(el)

	def borrar(self) -> None:
		el = self.seleccionado()
		if el is None:
			wx.Bell()
			return
		pos = self.lista.GetSelection()
		self.plugin.historial.borrar(el)
		self.refrescar(pos)

	def borrarTodo(self) -> None:
		from tiresias.gui import message_dialog

		if message_dialog.messageBox(MSG_CONFIRMAR_BORRAR, "Confirmar", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self) != wx.YES:
			self.lista.SetFocus()
			return
		self.plugin.historial.borrarTodo()
		self.refrescar()

	def alCerrar(self, evt) -> None:
		global _ventana
		if _ventana is self:
			_ventana = None
		self.Destroy()


# ====================================================================== trozos de texto
class PartesDialogo(wx.Dialog):
	def __init__(self, plugin, texto: str) -> None:
		super().__init__(None, title=TITULO_PARTES, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
		self.plugin = plugin
		self.texto = texto
		self.palabras = textoMod.trocear(texto)
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, "&Texto para seleccionar:")
		self.lista = wx.CheckListBox(self, size=(480, 320), choices=self.palabras)
		sizer.Add(self.lista, 1, wx.EXPAND | wx.ALL, 6)
		self.signos = wx.CheckBox(self, label="Conservar los &signos de puntuación")
		self.signos.Bind(wx.EVT_CHECKBOX, lambda evt: self.cambiarSignos())
		sizer.Add(self.signos, 0, wx.ALL, 6)
		botones = wx.BoxSizer(wx.HORIZONTAL)
		self.copiarBTN = wx.Button(self, label="&Copiar al portapapeles lo seleccionado")
		self.copiarBTN.Bind(wx.EVT_BUTTON, lambda evt: self.copiar())
		self.cerrarBTN = wx.Button(self, wx.ID_CANCEL, "Cerrar")
		botones.Add(self.copiarBTN, 0, wx.ALL, 4)
		botones.Add(self.cerrarBTN, 0, wx.ALL, 4)
		sizer.Add(botones, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.Close(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, self.alCerrar)
		self.CentreOnScreen()
		if self.palabras:
			self.lista.SetSelection(0)
		self.lista.SetFocus()

	def marcadas(self) -> list[int]:
		return [i for i in range(self.lista.GetCount()) if self.lista.IsChecked(i)]

	def cambiarSignos(self) -> None:
		"""Vuelve a trocear el texto con o sin los signos (se pierden las marcas)."""
		self.palabras = textoMod.trocear(self.texto, self.signos.GetValue())
		self.lista.Set(self.palabras)
		if self.palabras:
			self.lista.SetSelection(0)

	def copiar(self) -> None:
		marcadas = self.marcadas()
		if not marcadas:
			from tiresias.gui import message_dialog

			message_dialog.messageBox(MSG_NINGUNA, "Información", wx.OK | wx.ICON_INFORMATION, self)
			self.lista.SetFocus()
			return
		resultado = textoMod.unirSeleccion(self.palabras, marcadas)
		self.Close()
		queue_handler.queueFunction(self.plugin.copiarTexto, resultado)

	def alCerrar(self, evt) -> None:
		global _ventana
		if _ventana is self:
			_ventana = None
		self.Destroy()


# ====================================================================== apertura
def _mostrar(crear) -> None:
	global _ventana
	if isAlive(_ventana):
		bringToFront(_ventana)
		return
	v = crear()
	if not isAlive(v):
		return
	_ventana = v
	bringToFront(v)
	v.lista.SetFocus()


def mostrarHistorial(plugin) -> None:
	runOnGui(_mostrar, lambda: HistorialDialogo(plugin))


def mostrarPartes(plugin, texto: str) -> None:
	runOnGui(_mostrar, lambda: PartesDialogo(plugin, texto))


def cerrarVentanas() -> None:
	def _cerrar() -> None:
		global _ventana
		v, _ventana = _ventana, None
		if isAlive(v):
			v.Destroy()

	runOnGui(_cerrar)
