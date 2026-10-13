"""Módulo «Lanzador de Aplicaciones» de zUtilidades (interfaz wx)."""

from __future__ import annotations

import os
import threading

import wx

from . import comun, datos, estado, sistema
from .comun import DialogoValidado, botonesAceptarCancelar, etiqueta, mensaje

MSG_DUPLICADO = datos.MSG_DUPLICADO_ACCION
_FD_NO_FOLLOW = getattr(wx, "FD_NO_FOLLOW", 0)


def _campoRuta(dlg: wx.Dialog, s: wx.Sizer, textoEtiqueta: str, textoBoton: str, accion) -> tuple[wx.TextCtrl, wx.Button]:
	etiqueta(dlg, s, textoEtiqueta)
	fila = wx.BoxSizer(wx.HORIZONTAL)
	texto = wx.TextCtrl(dlg, size=(-1, 50), style=wx.TE_MULTILINE | wx.TE_READONLY)
	boton = wx.Button(dlg, label=textoBoton)
	boton.Bind(wx.EVT_BUTTON, accion)
	fila.Add(texto, 1, wx.EXPAND | wx.RIGHT, 6)
	fila.Add(boton, 0)
	s.Add(fila, 0, wx.EXPAND | wx.ALL, 6)
	return texto, boton


class DialogoAccion(DialogoValidado):
	"""Base de los diálogos de añadir o editar una acción."""

	def __init__(self, parent, titulo: str, existentes: list[str], actual: list | None) -> None:
		super().__init__(parent, titulo)
		self.existentes = existentes
		self.actual = actual
		self.resultado: list | None = None

	def comprobarNombre(self, nombre: str) -> bool:
		if datos.nombreDuplicado(nombre, self.existentes, self.actual[1] if self.actual else None):
			self.aviso(MSG_DUPLICADO, self.textoNombre)
			return False
		return True


# ====================================================================== aplicación
class DialogoAplicacion(DialogoAccion):
	def __init__(self, parent, existentes: list[str], actual: list | None = None) -> None:
		super().__init__(parent, "Editar aplicación" if actual else "Añadir aplicación", existentes, actual)
		s = wx.BoxSizer(wx.VERTICAL)
		etiqueta(self, s, "Introduzca el &nombre de la aplicación:")
		self.textoNombre = wx.TextCtrl(self)
		s.Add(self.textoNombre, 0, wx.EXPAND | wx.ALL, 6)
		self.textoDirectorio, self.directorioBTN = _campoRuta(self, s, "&Ruta de la aplicación:", "&Seleccionar archivo", self.archivoPulsar)
		self.chkParametro = wx.CheckBox(self, label="&Usar parámetros adicionales")
		self.chkParametro.Bind(wx.EVT_CHECKBOX, self.onParametro)
		s.Add(self.chkParametro, 0, wx.ALL, 6)
		etiqueta(self, s, "Introduzca los &parámetros para la aplicación:")
		self.textoParametro = wx.TextCtrl(self)
		s.Add(self.textoParametro, 0, wx.EXPAND | wx.ALL, 6)
		self.chkAdministrador = wx.CheckBox(self, label="Ejecutar como a&dministrador")
		s.Add(self.chkAdministrador, 0, wx.ALL, 6)
		botonesAceptarCancelar(self, s)
		if actual:
			self.textoNombre.SetValue(actual[1])
			self.textoDirectorio.SetValue(actual[2])
			self.chkParametro.SetValue(bool(actual[3]))
			self.textoParametro.SetValue(actual[4])
			self.chkAdministrador.SetValue(bool(actual[5]))
		self.textoParametro.Enable(self.chkParametro.GetValue())
		self.terminar(s, 600)
		self.textoNombre.SetFocus()

	def onParametro(self, evt) -> None:
		activo = self.chkParametro.GetValue()
		if not activo:
			self.textoParametro.Clear()
		self.textoParametro.Enable(activo)

	def archivoPulsar(self, evt) -> None:
		comodin = "Todos los archivos ejecutables (*.exe, *.com, *.bat)|*.exe;*.com;*.bat|Todos los ficheros (*.*)|*.*"
		actual = self.textoDirectorio.GetValue()
		dlg = wx.FileDialog(self, message="Seleccione un archivo", defaultDir=os.path.dirname(actual) if actual else "", wildcard=comodin, style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
		try:
			if dlg.ShowModal() == wx.ID_OK:
				self.textoDirectorio.SetValue(dlg.GetPath())
				self.textoDirectorio.SetFocus()
			else:
				self.directorioBTN.SetFocus()
		finally:
			dlg.Destroy()

	def validar(self) -> bool:
		nombre = self.textoNombre.GetValue()
		if nombre == "":
			self.aviso("El campo no puede quedar en blanco.\n\nIntroduzca un nombre para añadir una aplicación.", self.textoNombre)
			return False
		if self.textoDirectorio.GetValue() == "":
			self.aviso("El campo no puede quedar en blanco.\n\nSeleccione una aplicación para poder continuar.", self.directorioBTN)
			return False
		if not self.comprobarNombre(nombre):
			return False
		usa = self.chkParametro.GetValue()
		self.resultado = [datos.TIPO_APP, nombre, self.textoDirectorio.GetValue(), usa, self.textoParametro.GetValue() if usa else "", self.chkAdministrador.GetValue()]
		return True


# ====================================================================== CMD
ETIQUETA_CMD = "Introduzca los &comandos de CMD. Puede usar el símbolo (et = Shift+6) para usar más de una línea de comandos:"


class DialogoCMD(DialogoAccion):
	def __init__(self, parent, existentes: list[str], actual: list | None = None) -> None:
		super().__init__(parent, "Editar CMD" if actual else "Añadir CMD", existentes, actual)
		s = wx.BoxSizer(wx.VERTICAL)
		etiqueta(self, s, "Introduzca un &nombre para identificar el comando CMD:")
		self.textoNombre = wx.TextCtrl(self)
		s.Add(self.textoNombre, 0, wx.EXPAND | wx.ALL, 6)
		etiqueta(self, s, ETIQUETA_CMD)
		self.textoParametro = wx.TextCtrl(self)
		s.Add(self.textoParametro, 0, wx.EXPAND | wx.ALL, 6)
		self.chkParametro = wx.CheckBox(self, label="&Pausar la consola de CMD al finalizar el comando. Evitara que se cierre al terminar")
		s.Add(self.chkParametro, 0, wx.ALL, 6)
		self.chkAdministrador = wx.CheckBox(self, label="Ejecutar como a&dministrador")
		s.Add(self.chkAdministrador, 0, wx.ALL, 6)
		botonesAceptarCancelar(self, s)
		if actual:
			self.textoNombre.SetValue(actual[1])
			self.textoParametro.SetValue(actual[2])
			self.chkParametro.SetValue(bool(actual[3]))
			self.chkAdministrador.SetValue(bool(actual[4]))
		self.terminar(s, 700)
		self.textoNombre.SetFocus()

	def validar(self) -> bool:
		nombre = self.textoNombre.GetValue()
		if nombre == "":
			self.aviso("El campo (Introduzca un nombre para identificar el comando CMD) no puede quedar en blanco.\n\nIntroduzca un nombre para poder identificar el comando.", self.textoNombre)
			return False
		if self.textoParametro.GetValue() == "":
			self.aviso(
				"El campo (Introduzca los comandos de CMD. Puede usar el símbolo (et = Shift+6) para usar más de una línea de comandos) no puede quedar en blanco.\n\nEscriba una línea de comandos para continuar.",
				self.textoParametro,
			)
			return False
		if not self.comprobarNombre(nombre):
			return False
		self.resultado = [datos.TIPO_CMD, nombre, self.textoParametro.GetValue(), self.chkParametro.GetValue(), self.chkAdministrador.GetValue()]
		return True


# ====================================================================== carpeta
class DialogoCarpeta(DialogoAccion):
	def __init__(self, parent, existentes: list[str], actual: list | None = None) -> None:
		super().__init__(parent, "Editar carpeta" if actual else "Añadir carpeta", existentes, actual)
		s = wx.BoxSizer(wx.VERTICAL)
		etiqueta(self, s, "Introduzca el &nombre de la carpeta:")
		self.textoNombre = wx.TextCtrl(self)
		s.Add(self.textoNombre, 0, wx.EXPAND | wx.ALL, 6)
		self.textoDirectorio, self.directorioBTN = _campoRuta(self, s, "&Ruta de la carpeta:", "&Seleccionar carpeta", self.carpetaPulsar)
		botonesAceptarCancelar(self, s)
		if actual:
			self.textoNombre.SetValue(actual[1])
			# Si la carpeta ya no existe, el campo queda vacío para elegir otra.
			if os.path.isdir(actual[2]):
				self.textoDirectorio.SetValue(actual[2])
		self.terminar(s, 600)
		self.textoNombre.SetFocus()

	def carpetaPulsar(self, evt) -> None:
		dlg = wx.DirDialog(self, "Seleccione una carpeta:", defaultPath=self.textoDirectorio.GetValue(), style=wx.DD_DEFAULT_STYLE)
		try:
			if dlg.ShowModal() == wx.ID_OK:
				self.textoDirectorio.SetValue(dlg.GetPath())
				self.textoDirectorio.SetFocus()
		finally:
			dlg.Destroy()

	def validar(self) -> bool:
		nombre = self.textoNombre.GetValue()
		if nombre == "":
			self.aviso("El campo no puede quedar en blanco.\n\nIntroduzca un nombre para identificar una carpeta.", self.textoNombre)
			return False
		if self.textoDirectorio.GetValue() == "":
			self.aviso("El campo no puede quedar en blanco.\n\nSeleccione una carpeta para poder continuar.", self.directorioBTN)
			return False
		if not self.comprobarNombre(nombre):
			return False
		self.resultado = [datos.TIPO_CARPETA, nombre, self.textoDirectorio.GetValue()]
		return True


# ====================================================================== acceso directo
class DialogoAcceso(DialogoAccion):
	def __init__(self, parent, existentes: list[str], actual: list | None = None) -> None:
		super().__init__(parent, "Editar acceso directo" if actual else "Añadir acceso directo", existentes, actual)
		s = wx.BoxSizer(wx.VERTICAL)
		etiqueta(self, s, "Introduzca el &nombre del acceso directo:")
		self.textoNombre = wx.TextCtrl(self)
		s.Add(self.textoNombre, 0, wx.EXPAND | wx.ALL, 6)
		self.textoDirectorio, self.directorioBTN = _campoRuta(self, s, "&Ruta del acceso directo:", "&Seleccionar acceso directo", self.accesoPulsar)
		self.chkAdministrador = wx.CheckBox(self, label="Ejecutar como a&dministrador")
		s.Add(self.chkAdministrador, 0, wx.ALL, 6)
		botonesAceptarCancelar(self, s)
		if actual:
			self.textoNombre.SetValue(actual[1])
			if os.path.isfile(actual[2]):
				self.textoDirectorio.SetValue(actual[2])
			self.chkAdministrador.SetValue(bool(actual[3]))
		self.terminar(s, 600)
		self.textoNombre.SetFocus()

	def accesoPulsar(self, evt) -> None:
		# FD_NO_FOLLOW: se guarda el acceso directo, no el programa al que apunta.
		dlg = wx.FileDialog(self, message="Seleccione un acceso directo", wildcard="Accesos directos (*.lnk)|*.lnk", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | _FD_NO_FOLLOW)
		try:
			if dlg.ShowModal() == wx.ID_OK:
				self.textoDirectorio.SetValue(dlg.GetPath())
				self.textoDirectorio.SetFocus()
			else:
				self.directorioBTN.SetFocus()
		finally:
			dlg.Destroy()

	def validar(self) -> bool:
		nombre = self.textoNombre.GetValue()
		if nombre == "":
			self.aviso("El campo no puede quedar en blanco.\n\nIntroduzca un nombre para identificar un acceso directo.", self.textoNombre)
			return False
		if self.textoDirectorio.GetValue() == "":
			self.aviso("El campo no puede quedar en blanco.\n\nSeleccione un acceso directo para poder continuar.", self.directorioBTN)
			return False
		if not self.comprobarNombre(nombre):
			return False
		self.resultado = [datos.TIPO_ACCESO, nombre, self.textoDirectorio.GetValue(), self.chkAdministrador.GetValue()]
		return True


# ====================================================================== aplicación instalada
INFO_INSTALADA = """En el siguiente campo combinado tendrá todas las aplicaciones instaladas.

Esto incluye las aplicaciones instaladas desde la tienda, por el usuario y aquellos accesos que las aplicaciones instalan junto a la aplicación en sí.

También tiene aplicaciones del sistema las cuales también se pueden añadir.

Advertencia:

Las aplicaciones añadidas desde este apartado no pueden ser editadas en el lanzador, por lo que si sufren cambios tendrá que eliminar la entrada en el lanzador y volver a elegir de nuevo la aplicación y añadirla.

Igualmente si la aplicación ha sido desinstalada tendrá que borrar el acceso en el lanzador."""

PRIMERA_OPCION = "Seleccione algo para añadir al lanzador."
CARGANDO = "Obteniendo la lista de aplicaciones instaladas..."


class DialogoInstalada(DialogoAccion):
	def __init__(self, parent, existentes: list[str], obtener=None) -> None:
		super().__init__(parent, "Añadir aplicación instalada", existentes, None)
		self.listaApps: list[tuple[str, str]] = []
		s = wx.BoxSizer(wx.VERTICAL)
		etiqueta(self, s, "&Información importante:")
		self.textoinfo = wx.TextCtrl(self, size=(-1, 160), style=wx.TE_MULTILINE | wx.TE_READONLY)
		self.textoinfo.SetValue(INFO_INSTALADA)
		self.textoinfo.SetInsertionPoint(0)
		s.Add(self.textoinfo, 1, wx.EXPAND | wx.ALL, 6)
		etiqueta(self, s, "&Aplicaciones instaladas:")
		self.choiceApps = wx.Choice(self, choices=[CARGANDO])
		self.choiceApps.SetSelection(0)
		self.choiceApps.Bind(wx.EVT_CHOICE, self.onChoiceApp)
		s.Add(self.choiceApps, 0, wx.EXPAND | wx.ALL, 6)
		etiqueta(self, s, "Introduzca el &nombre de la aplicación:")
		self.textoNombre = wx.TextCtrl(self)
		s.Add(self.textoNombre, 0, wx.EXPAND | wx.ALL, 6)
		self.chkAdministrador = wx.CheckBox(self, label="Ejecutar como a&dministrador")
		s.Add(self.chkAdministrador, 0, wx.ALL, 6)
		botonesAceptarCancelar(self, s)
		self.terminar(s, 650)
		self.textoinfo.SetFocus()
		obtener = obtener or sistema.obtenerAplicaciones
		threading.Thread(target=self._cargar, args=(obtener,), name="zUtilidadesStartApps", daemon=True).start()

	def _cargar(self, obtener) -> None:
		try:
			apps = obtener()
		except Exception:
			from tiresias.log import getLogger

			getLogger("zUtilidades").debug("No se pudo obtener la lista de aplicaciones", exc_info=True)
			apps = []
		wx.CallAfter(self.cargarLista, apps)

	def cargarLista(self, apps: list[tuple[str, str]]) -> None:
		if not self:
			return
		self.listaApps = list(apps)
		self.choiceApps.Set([PRIMERA_OPCION] + [a[0] for a in self.listaApps])
		self.choiceApps.SetSelection(0)
		if not self.listaApps:
			sistema.mensaje("No se pudo obtener la lista de aplicaciones instaladas")

	def onChoiceApp(self, evt) -> None:
		i = self.choiceApps.GetSelection()
		if i <= 0 or not self.listaApps:
			self.textoNombre.Clear()
		else:
			self.textoNombre.SetValue(self.listaApps[i - 1][0])

	def validar(self) -> bool:
		i = self.choiceApps.GetSelection()
		if i <= 0 or not self.listaApps:
			self.aviso("Tiene que elegir una aplicación del cuadro combinado para poder añadirla.", self.choiceApps)
			return False
		nombre = self.textoNombre.GetValue()
		if nombre == "":
			self.aviso("El campo no puede quedar en blanco.\n\nIntroduzca un nombre para identificar un acceso.", self.textoNombre)
			return False
		if not self.comprobarNombre(nombre):
			return False
		self.resultado = [datos.TIPO_INSTALADA, nombre, self.listaApps[i - 1][1], self.chkAdministrador.GetValue()]
		return True


DIALOGOS_EDICION = {
	datos.TIPO_APP: DialogoAplicacion,
	datos.TIPO_CMD: DialogoCMD,
	datos.TIPO_CARPETA: DialogoCarpeta,
	datos.TIPO_ACCESO: DialogoAcceso,
}


# ====================================================================== ventana principal
class VentanaLanzador(comun.VentanaBase):
	modulo = datos.LANZADOR
	titulo = "Lanzador de Aplicaciones"
	etiquetaElementos = "&Lista acciones:"
	vacio = "Sin acciones"
	extensionCopia = ".zut-zl"
	esNota = False
	textoRestaurar = (
		"*** ADVERTENCIA ***\n\nEsto borrara toda la base de datos del lanzador de aplicaciones\n\n"
		"Toda la base de datos será sustituida por la copia de seguridad.\n\n"
		"El complemento restaurara la copia de seguridad y se cerrara.\n\nEsta acción no es reversible.\n\n¿Desea continuar con el proceso?"
	)
	textoBorrarTodo = (
		"*** ADVERTENCIA ***\n\nEsto borrara toda la base de datos del lanzador de aplicaciones\n\n"
		"El complemento borrara la base de datos y se cerrara.\n\nEsta acción no es reversible.\n\n¿Desea continuar con el proceso?"
	)

	# ------------------------------------------------------------------ menús
	def entradasAñadir(self) -> list:
		return [
			("Añadir &aplicación", lambda: self.añadir(DialogoAplicacion)),
			("Añadir comando &CMD", lambda: self.añadir(DialogoCMD)),
			("Añadir accesos a car&petas", lambda: self.añadir(DialogoCarpeta)),
			("Añadir ejecutar accesos directos de &Windows", lambda: self.añadir(DialogoAcceso)),
			("Añadir aplicación &instalada", lambda: self.añadir(DialogoInstalada)),
		]

	def entradasElementos(self) -> list:
		return [
			("&Añadir acción", self.entradasAñadir()),
			("&Editar acción", self.editar),
			("&Borrar acción", self.borrarElemento),
			("&Mover acción", self.moverACategoria),
		]

	def entradaSubmenuElementos(self):
		return ("&Acciones", self.entradasElementos())

	def entradasOpciones(self) -> list:
		return [("&Volver a valores por defecto el lanzador de aplicaciones", self.borrarValores)]

	# ------------------------------------------------------------------ acciones
	def añadir(self, clase) -> None:
		if not self.comprobarCategoria():
			return
		dlg = clase(self, [e[1] for e in self.elementos])
		try:
			if dlg.ShowModal() == wx.ID_OK and dlg.resultado:
				self.guardarNuevo(dlg.resultado)
		finally:
			dlg.Destroy()

	def editar(self, indice: int | None = None) -> bool:
		if not self.comprobarCategoria() or not self.comprobarElemento("editar"):
			return False
		i = self.elemActual() if indice is None else indice
		elem = self.elementos[i]
		if elem[0] == datos.TIPO_INSTALADA:
			mensaje(self, "Esta acción no es editable.\n\nSi lo desea puede eliminarla y volver a añadir otra.")
			return False
		clase = DIALOGOS_EDICION.get(elem[0])
		if clase is None:
			return False
		dlg = clase(self, [e[1] for e in self.elementos], elem)
		try:
			if dlg.ShowModal() == wx.ID_OK and dlg.resultado:
				self.guardarEditado(i, dlg.resultado)
				return True
		finally:
			dlg.Destroy()
		return False

	def activar(self, indice: int) -> None:
		self.ejecutar(indice)

	def ejecutar(self, indice: int) -> None:
		elem = self.elementos[indice]
		if sistema.rutaNoEncontrada(elem):
			if comun.preguntar(self, sistema.mensajeRutaNoEncontrada(elem, True), "Aviso", noPorDefecto=False):
				self.editar(indice)
			return
		self.cerrar()
		sistema.ejecutar(elem, alError=lambda texto: wx.CallAfter(mensaje, None, texto, "Error", True))


def abrir() -> VentanaLanzador | None:
	"""Abre la ventana del lanzador (hilo de la interfaz)."""
	from tiresias.gui.helpers import bringToFront

	if estado.ventanaAbierta:
		sistema.mensaje(estado.MSG_INSTANCIA)
		return None
	v = VentanaLanzador()
	bringToFront(v)
	v.enfocarInicial()
	return v
