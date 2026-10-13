"""Módulo «Notas rápidas» de zUtilidades (interfaz wx)."""

from __future__ import annotations

import wx

from . import comun, datos, estado, sistema
from .comun import DialogoValidado, botonesAceptarCancelar, etiqueta, mensaje

MSG_NOMBRE_VACIO = "El campo no puede quedar en blanco.\n\nIntroduzca un nombre para añadir una Nota."
MSG_TEXTO_VACIO = "El campo no puede quedar en blanco.\n\nIntroduzca un texto para guardar la nota."


def validarNota(nombre: str, texto: str, existentes: list[str], actual: str | None = None) -> tuple[str, str] | None:
	"""Error de una nota como (mensaje, campo) o ``None`` si vale.

	``campo`` es ``"nombre"`` o ``"texto"`` (dónde poner el foco).
	"""
	if nombre == "":
		return MSG_NOMBRE_VACIO, "nombre"
	if texto == "":
		return MSG_TEXTO_VACIO, "texto"
	if datos.nombreDuplicado(nombre, existentes, actual):
		return datos.MSG_DUPLICADO_NOTA, "nombre"
	return None


# ====================================================================== añadir / editar
class DialogoNota(DialogoValidado):
	def __init__(self, parent, existentes: list[str], actual: list | None = None) -> None:
		super().__init__(parent, "Editar Nota" if actual else "Añadir Nota", size=(800, 560), redimensionable=True)
		self.existentes = existentes
		self.actual = actual
		s = wx.BoxSizer(wx.VERTICAL)
		etiqueta(self, s, "Introduzca el &nombre de la Nota:")
		self.textoNombre = wx.TextCtrl(self)
		s.Add(self.textoNombre, 0, wx.EXPAND | wx.ALL, 6)
		etiqueta(self, s, "C&ontenido de la Nota:")
		self.textoNota = wx.TextCtrl(self, style=wx.TE_MULTILINE)
		s.Add(self.textoNota, 1, wx.EXPAND | wx.ALL, 6)
		botonesAceptarCancelar(self, s)
		if actual:
			self.textoNombre.SetValue(actual[1])
			self.textoNota.SetValue(actual[2])
		self.SetSizer(s)
		self.Layout()
		self.CentreOnScreen()
		self.textoNombre.SetFocus()

	def validar(self) -> bool:
		nombre, texto = self.textoNombre.GetValue(), self.textoNota.GetValue()
		err = validarNota(nombre, texto, self.existentes, self.actual[1] if self.actual else None)
		if err:
			self.aviso(err[0], self.textoNombre if err[1] == "nombre" else self.textoNota)
			return False
		self.resultado = [datos.TIPO_NOTA, nombre, texto]
		return True


class DialogoVerNota(wx.Dialog):
	"""Muestra el contenido de una nota (solo lectura)."""

	def __init__(self, parent, titulo: str, texto: str) -> None:
		super().__init__(parent, title=titulo, size=(800, 560), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		s = wx.BoxSizer(wx.VERTICAL)
		etiqueta(self, s, "C&ontenido de la Nota:")
		self.textoNota = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY)
		self.textoNota.SetValue(texto)
		self.textoNota.SetInsertionPoint(0)
		s.Add(self.textoNota, 1, wx.EXPAND | wx.ALL, 6)
		cerrar = wx.Button(self, wx.ID_CANCEL, "&Cerrar")
		s.Add(cerrar, 0, wx.EXPAND | wx.ALL, 6)
		self.SetEscapeId(wx.ID_CANCEL)
		self.SetSizer(s)
		self.Layout()
		self.CentreOnScreen()
		self.textoNota.SetFocus()


# ====================================================================== ventana principal
class VentanaNotas(comun.VentanaBase):
	modulo = datos.NOTAS
	titulo = "Notas rápidas"
	etiquetaElementos = "&Lista notas:"
	vacio = "Sin notas"
	extensionCopia = ".zut-zn"
	esNota = True
	textoRestaurar = (
		"*** ADVERTENCIA ***\n\nEsto borrara toda la base de datos de Notas rápidas\n\n"
		"Toda la base de datos será sustituida por la copia de seguridad.\n\n"
		"El complemento restaurara la copia de seguridad y se cerrara.\n\nEsta acción no es reversible.\n\n¿Desea continuar con el proceso?"
	)
	textoBorrarTodo = (
		"*** ADVERTENCIA ***\n\nEsto borrara toda la base de datos de Notas rápidas\n\n"
		"El complemento borrara la base de datos y se cerrara.\n\nEsta acción no es reversible.\n\n¿Desea continuar con el proceso?"
	)

	def entradasElementos(self) -> list:
		return [
			("&Añadir Nota", self.añadir),
			("&Editar Nota", self.editar),
			("&Borrar Nota", self.borrarElemento),
			("&Mover Nota", self.moverACategoria),
		]

	def entradaSubmenuElementos(self):
		return ("&Notas", self.entradasElementos())

	def entradasOpciones(self) -> list:
		return [
			("&Opciones", self.opciones),
			("&Volver a valores por defecto Notas rápidas", self.borrarValores),
		]

	# ------------------------------------------------------------------ notas
	def añadir(self) -> None:
		if not self.comprobarCategoria():
			return
		dlg = DialogoNota(self, [e[1] for e in self.elementos])
		try:
			if dlg.ShowModal() == wx.ID_OK and dlg.resultado:
				self.guardarNuevo(dlg.resultado)
		finally:
			dlg.Destroy()

	def editar(self) -> None:
		if not self.comprobarCategoria() or not self.comprobarElemento("editar"):
			return
		i = self.elemActual()
		dlg = DialogoNota(self, [e[1] for e in self.elementos], self.elementos[i])
		try:
			if dlg.ShowModal() == wx.ID_OK and dlg.resultado:
				self.guardarEditado(i, dlg.resultado)
		finally:
			dlg.Destroy()

	def opciones(self) -> None:
		dlg = comun.DialogoOpciones(self)
		try:
			dlg.ShowModal()
		finally:
			dlg.Destroy()
		self.enfocarInicial()

	# ------------------------------------------------------------------ teclas
	def activar(self, indice: int) -> None:
		"""Espacio: ver la nota en una ventana."""
		dlg = DialogoVerNota(self, self.elementos[indice][1], self.elementos[indice][2])
		try:
			dlg.ShowModal()
		finally:
			dlg.Destroy()
		self.lstElementos.SetFocus()

	def teclaElemento(self, code: int, indice: int) -> bool:
		elem = self.elementos[indice]
		if code == wx.WXK_F1:
			# Lee el contenido de la nota.
			sistema.mensaje(elem[2])
			return True
		if code == wx.WXK_F2:
			if sistema.copiarAlPortapapeles(elem[2]):
				sistema.mensaje("Se ha copiado la nota {} al portapapeles.".format(elem[1]))
			else:
				sistema.mensaje("No se ha podido copiar la nota {} al portapapeles.".format(elem[1]))
			return True
		if code == wx.WXK_F3:
			# Cierra la ventana y pega la nota donde estaba el foco.
			texto = elem[2]
			self.cerrar()
			from tiresias import queue_handler

			queue_handler.queueFunction(sistema.pegarEnFoco, texto, 400)
			return True
		return False


def abrir() -> VentanaNotas | None:
	"""Abre la ventana de notas rápidas (hilo de la interfaz)."""
	from tiresias.gui.helpers import bringToFront

	if estado.ventanaAbierta:
		sistema.mensaje(estado.MSG_INSTANCIA)
		return None
	v = VentanaNotas()
	bringToFront(v)
	v.enfocarInicial()
	return v


# ====================================================================== nota rápida desde cualquier sitio
class DialogoNotaRapida(wx.Dialog):
	"""«Agregar nota rápida del texto seleccionado» o «Añadir una nueva nota rápida»."""

	def __init__(self, texto: str | None, titulo: str | None, nueva: bool) -> None:
		super().__init__(None, title="Añadir una nueva nota rápida" if nueva else "Agregar nota rápida del texto seleccionado", size=(800, 600), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.base = datos.BaseDatos(datos.NOTAS)
		self.base.comprobar()
		self.categorias = self.base.nombresCategorias()
		self.cerrada = False
		estado.ventanaAbierta = True
		s = wx.BoxSizer(wx.VERTICAL)
		etiqueta(self, s, "&Seleccione una categoría donde guardar la nota rápida:")
		self.choice = wx.Choice(self, choices=self.categorias)
		self.choice.SetSelection(0)
		s.Add(self.choice, 0, wx.EXPAND | wx.ALL, 6)
		etiqueta(self, s, "Introduzca el &nombre de la Nota:")
		self.textoNombre = wx.TextCtrl(self)
		if titulo is not None:
			self.textoNombre.SetValue(titulo)
		s.Add(self.textoNombre, 0, wx.EXPAND | wx.ALL, 6)
		etiqueta(self, s, "C&ontenido de la Nota:")
		self.textoNota = wx.TextCtrl(self, style=wx.TE_MULTILINE)
		if texto:
			self.textoNota.SetValue(texto)
		s.Add(self.textoNota, 1, wx.EXPAND | wx.ALL, 6)
		botonesAceptarCancelar(self, s)
		self.Bind(wx.EVT_BUTTON, self.onAceptar, id=wx.ID_OK)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.cerrar(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, lambda evt: self.cerrar())
		self.Bind(wx.EVT_CHAR_HOOK, self.onTecla)
		self.SetSizer(s)
		self.Layout()
		self.CentreOnScreen()
		self.choice.SetFocus()

	def onTecla(self, evt) -> None:
		if evt.GetKeyCode() == wx.WXK_ESCAPE and not evt.HasAnyModifiers():
			self.cerrar()
			return
		evt.Skip()

	def onAceptar(self, evt) -> None:
		cat = self.choice.GetSelection()
		existentes = self.base.nombresElementos(cat) if cat >= 0 else []
		err = validarNota(self.textoNombre.GetValue(), self.textoNota.GetValue(), existentes)
		if err:
			mensaje(self, err[0])
			(self.textoNombre if err[1] == "nombre" else self.textoNota).SetFocus()
			return
		self.base.añadirElemento(cat, [datos.TIPO_NOTA, self.textoNombre.GetValue(), self.textoNota.GetValue()])
		self.cerrar()

	def cerrar(self) -> None:
		if self.cerrada:
			return
		self.cerrada = True
		estado.ventanaAbierta = False
		self.Hide()
		self.Destroy()


MSG_SIN_CATEGORIAS = "No hay categorías para añadir una nota rápida.\n\nAgregue una categoría antes para poder {}."


def abrirNotaRapida(texto: str | None, titulo: str | None, nueva: bool) -> DialogoNotaRapida | None:
	"""Abre el diálogo de nota rápida (hilo de la interfaz)."""
	from tiresias.gui.helpers import bringToFront

	if estado.ventanaAbierta:
		sistema.mensaje(estado.MSG_INSTANCIA)
		return None
	base = datos.BaseDatos(datos.NOTAS)
	base.comprobar()
	if not base.nombresCategorias():
		sistema.mensaje(MSG_SIN_CATEGORIAS.format("crear una nota rápida" if nueva else "copiar un texto a una nota rápida"))
		return None
	d = DialogoNotaRapida(texto, titulo, nueva)
	bringToFront(d)
	d.choice.SetFocus()
	return d
