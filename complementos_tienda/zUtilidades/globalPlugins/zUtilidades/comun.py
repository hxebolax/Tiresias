"""Ventanas y diálogos comunes del lanzador de aplicaciones y de las notas
rápidas (interfaz wx, solo en el hilo de la interfaz).
"""

from __future__ import annotations

import os
import threading

import wx

from . import copias, datos, estado, sistema

TITULO_INFO = "Información"
TITULO_PREGUNTA = "Pregunta"


# ====================================================================== utilidades
def mensaje(parent, texto: str, titulo: str = TITULO_INFO, error: bool = False) -> None:
	"""Cuadro de mensaje con un botón Aceptar (el de Tiresias)."""
	from tiresias import gui

	gui.messageBox(texto, titulo, wx.OK | (wx.ICON_ERROR if error else wx.ICON_INFORMATION), parent)


def preguntar(parent, texto: str, titulo: str = TITULO_PREGUNTA, noPorDefecto: bool = True) -> bool:
	"""Pregunta Sí/No. Devuelve ``True`` si se contesta Sí."""
	from tiresias import gui

	estilo = wx.YES_NO | wx.ICON_QUESTION | (wx.NO_DEFAULT if noPorDefecto else 0)
	return gui.messageBox(texto, titulo, estilo, parent) == wx.YES


def carpetaDocumentos() -> str:
	p = os.path.join(os.path.expanduser("~"), "Documents")
	return p if os.path.isdir(p) else os.path.expanduser("~")


def etiqueta(parent: wx.Window, sizer: wx.Sizer, texto: str) -> wx.StaticText:
	"""Etiqueta creada justo antes del control que nombra (orden de tabulación)."""
	st = wx.StaticText(parent, label=texto)
	sizer.Add(st, 0, wx.LEFT | wx.RIGHT | wx.TOP, 6)
	return st


def botonesAceptarCancelar(dlg: wx.Dialog, sizer: wx.Sizer, aceptar: str = "&Aceptar", cancelar: str = "&Cancelar") -> tuple[wx.Button, wx.Button]:
	fila = wx.BoxSizer(wx.HORIZONTAL)
	ok = wx.Button(dlg, wx.ID_OK, aceptar)
	cancel = wx.Button(dlg, wx.ID_CANCEL, cancelar)
	fila.Add(ok, 1, wx.ALL | wx.EXPAND, 4)
	fila.Add(cancel, 1, wx.ALL | wx.EXPAND, 4)
	sizer.Add(fila, 0, wx.EXPAND | wx.ALL, 4)
	ok.SetDefault()
	dlg.SetEscapeId(wx.ID_CANCEL)
	return ok, cancel


class DialogoValidado(wx.Dialog):
	"""Diálogo modal con Aceptar (que valida antes de cerrar) y Cancelar/Escape."""

	def __init__(self, parent, titulo: str, size=(-1, -1), redimensionable: bool = False) -> None:
		estilo = wx.DEFAULT_DIALOG_STYLE | (wx.RESIZE_BORDER if redimensionable else 0)
		super().__init__(parent, title=titulo, size=size, style=estilo)
		self.resultado = None
		self.Bind(wx.EVT_BUTTON, self._onAceptar, id=wx.ID_OK)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.EndModal(wx.ID_CANCEL), id=wx.ID_CANCEL)

	def _onAceptar(self, evt) -> None:
		if self.validar():
			self.EndModal(wx.ID_OK)

	def validar(self) -> bool:
		return True

	def aviso(self, texto: str, control: wx.Window | None = None) -> None:
		mensaje(self, texto)
		if control is not None:
			control.SetFocus()

	def terminar(self, sizer: wx.Sizer, minAncho: int = 500) -> None:
		self.SetSizer(sizer)
		sizer.Fit(self)
		w, h = self.GetSize()
		self.SetSize((max(w, minAncho), h))
		self.CentreOnScreen()


# ====================================================================== categorías
class DialogoCategoria(DialogoValidado):
	"""Añadir o editar una categoría (un campo de texto)."""

	def __init__(self, parent, existentes: list[str], actual: str | None = None) -> None:
		super().__init__(parent, "Editar categoría" if actual is not None else "Añadir categoría")
		self.existentes = existentes
		self.actual = actual
		s = wx.BoxSizer(wx.VERTICAL)
		etiqueta(self, s, "&Introduzca el nombre de la categoría:")
		self.texto = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
		self.texto.Bind(wx.EVT_TEXT_ENTER, self._onAceptar)
		if actual is not None:
			self.texto.SetValue(actual)
		s.Add(self.texto, 0, wx.EXPAND | wx.ALL, 6)
		botonesAceptarCancelar(self, s)
		self.terminar(s, 420)
		self.texto.SetFocus()

	def validar(self) -> bool:
		err = datos.validarCategoria(self.texto.GetValue(), self.existentes, self.actual)
		if err:
			self.aviso(err, self.texto)
			return False
		self.resultado = self.texto.GetValue()
		return True


# ====================================================================== mover
class DialogoMover(DialogoValidado):
	"""Mover una acción o una nota a otra categoría.

	Si en la categoría de destino ya hay uno con el mismo nombre se activa el
	campo para darle otro.
	"""

	def __init__(self, parent, base: datos.BaseDatos, catOrigen: int, indice: int, esNota: bool) -> None:
		self.base = base
		self.catOrigen = catOrigen
		self.indice = indice
		self.esNota = esNota
		self.nombre = base.elementos(catOrigen)[indice][1]
		que = "nota" if esNota else "acción"
		super().__init__(parent, ("Mover la nota {} a otra categoría" if esNota else "Mover la acción  {} a otra categoría").format(self.nombre))
		cats = base.nombresCategorias()
		self.destinos = [i for i in range(len(cats)) if i != catOrigen]
		s = wx.BoxSizer(wx.VERTICAL)
		etiqueta(self, s, f"&Seleccione una categoría donde mover la {que}:")
		self.choice = wx.Choice(self, choices=[cats[i] for i in self.destinos])
		self.choice.SetSelection(0)
		self.choice.Bind(wx.EVT_CHOICE, self.onChoice)
		s.Add(self.choice, 0, wx.EXPAND | wx.ALL, 6)
		etiqueta(self, s, f"Introduzca un &nuevo nombre a la {que}:")
		self.textoNombre = wx.TextCtrl(self)
		self.textoNombre.Disable()
		s.Add(self.textoNombre, 0, wx.EXPAND | wx.ALL, 6)
		self.banderaTexto = False
		botonesAceptarCancelar(self, s)
		self.terminar(s, 500)
		self.choice.SetFocus()

	def onChoice(self, evt) -> None:
		self.textoNombre.Clear()
		self.textoNombre.Disable()
		self.banderaTexto = False

	def validar(self) -> bool:
		destino = self.destinos[self.choice.GetSelection()]
		nombres = self.base.nombresElementos(destino)
		nuevo = self.textoNombre.GetValue() if self.banderaTexto else self.nombre
		if datos.estaEnLista(nombres, nuevo) or (self.banderaTexto and not nuevo):
			self.aviso(datos.MSG_DUPLICADO_NOTA if self.esNota else datos.MSG_DUPLICADO_ACCION)
			self.textoNombre.Enable()
			self.banderaTexto = True
			self.textoNombre.SetValue(self.nombre)
			self.textoNombre.SetFocus()
			self.textoNombre.SelectAll()
			return False
		self.base.moverACategoria(self.catOrigen, self.indice, destino, nuevo if self.banderaTexto else None)
		self.resultado = destino
		return True


# ====================================================================== copias de seguridad
class DialogoCopia(wx.Dialog):
	"""Progreso de una copia de seguridad o de su restauración (en un hilo)."""

	def __init__(self, parent, titulo: str, modulo: str, archivo: str, restaurar: bool = False) -> None:
		super().__init__(parent, title=titulo, style=wx.CAPTION | wx.SYSTEM_MENU)
		self.modulo = modulo
		self.archivo = archivo
		self.restaurar = restaurar
		self.terminado = False
		self.exito = False
		s = wx.BoxSizer(wx.VERTICAL)
		etiqueta(self, s, "Progreso:")
		self.progressBar = wx.Gauge(self, range=100, style=wx.GA_HORIZONTAL)
		s.Add(self.progressBar, 0, wx.EXPAND | wx.ALL, 6)
		etiqueta(self, s, "&Estado:")
		self.textorefresco = wx.TextCtrl(self, size=(460, 90), style=wx.TE_MULTILINE | wx.TE_READONLY)
		s.Add(self.textorefresco, 1, wx.EXPAND | wx.ALL, 6)
		fila = wx.BoxSizer(wx.HORIZONTAL)
		self.AceptarTRUE = wx.Button(self, wx.ID_OK, "&Aceptar")
		self.AceptarTRUE.Disable()
		self.AceptarFALSE = wx.Button(self, wx.ID_CLOSE, "&Cerrar")
		self.AceptarFALSE.Disable()
		fila.Add(self.AceptarTRUE, 1, wx.ALL, 4)
		fila.Add(self.AceptarFALSE, 1, wx.ALL, 4)
		s.Add(fila, 0, wx.EXPAND | wx.ALL, 4)
		self.AceptarTRUE.Bind(wx.EVT_BUTTON, lambda evt: self.EndModal(wx.ID_OK))
		self.AceptarFALSE.Bind(wx.EVT_BUTTON, lambda evt: self.EndModal(wx.ID_CANCEL))
		self.Bind(wx.EVT_CLOSE, self.onCerrar)
		self.Bind(wx.EVT_CHAR_HOOK, self.onTecla)
		self.SetSizerAndFit(s)
		self.CentreOnScreen()
		self.textorefresco.SetFocus()
		self.textorefresco.SetValue("Restaurando copia de seguridad..." if restaurar else "Haciendo copia de seguridad...")
		self.hilo = threading.Thread(target=self._trabajo, name="zUtilidadesCopia", daemon=True)
		self.hilo.start()

	def _progreso(self, pct: int, texto: str) -> None:
		wx.CallAfter(self._actualizar, pct, texto)

	def _actualizar(self, pct: int, texto: str) -> None:
		if not self:
			return
		self.progressBar.SetValue(max(0, min(100, pct)))
		if texto:
			self.textorefresco.SetValue(texto)

	def _trabajo(self) -> None:
		try:
			if self.restaurar:
				copias.restaurarCopia(self.modulo, self.archivo, self._progreso)
				texto = "Se completo la restauración correctamente.\nYa puede cerrar esta ventana."
			else:
				copias.hacerCopia(self.modulo, self.archivo, self._progreso)
				texto = "La copia de seguridad fue un éxito.\nYa puede cerrar esta ventana."
			wx.CallAfter(self.done, texto)
		except Exception:
			from tiresias.log import getLogger

			getLogger("zUtilidades").debug("Error en la copia de seguridad", exc_info=True)
			wx.CallAfter(self.error, "Algo salió mal.\nInténtelo de nuevo.\nYa puede cerrar esta ventana.")

	def done(self, texto: str) -> None:
		if not self:
			return
		self.terminado = True
		self.exito = True
		sistema.sonidoAviso(False)
		self.progressBar.SetValue(100)
		self.AceptarTRUE.Enable()
		self.textorefresco.SetValue(texto)
		self.textorefresco.SetInsertionPoint(0)
		self.textorefresco.SetFocus()
		sistema.mensaje(texto.split("\n")[0])

	def error(self, texto: str) -> None:
		if not self:
			return
		self.terminado = True
		self.exito = False
		sistema.sonidoAviso(True)
		self.AceptarFALSE.Enable()
		self.textorefresco.SetValue(texto)
		self.textorefresco.SetInsertionPoint(0)
		self.textorefresco.SetFocus()
		sistema.mensaje(texto.split("\n")[0])

	def onCerrar(self, evt) -> None:
		# No se puede cerrar mientras se trabaja.
		if self.terminado:
			self.EndModal(wx.ID_OK if self.exito else wx.ID_CANCEL)
		elif evt.CanVeto():
			evt.Veto()

	def onTecla(self, evt) -> None:
		if evt.GetKeyCode() == wx.WXK_ESCAPE:
			if self.terminado:
				self.EndModal(wx.ID_OK if self.exito else wx.ID_CANCEL)
			return
		evt.Skip()


# ====================================================================== opciones
class DialogoOpciones(DialogoValidado):
	"""Opciones de las notas rápidas (las mismas que la categoría de Opciones de Tiresias)."""

	def __init__(self, parent) -> None:
		super().__init__(parent, "Opciones")
		s = wx.BoxSizer(wx.VERTICAL)
		self.casillas = {}
		for clave, texto in estado.ETIQUETAS:
			c = wx.CheckBox(self, label=texto)
			c.SetValue(estado.opcion(clave))
			s.Add(c, 0, wx.ALL, 6)
			self.casillas[clave] = c
		self.chkTitulo = self.casillas["tituloCaptura"]
		self.chkURL = self.casillas["urlCaptura"]
		botonesAceptarCancelar(self, s)
		self.terminar(s, 560)
		self.chkTitulo.SetFocus()

	def validar(self) -> bool:
		for clave, c in self.casillas.items():
			estado.ponerOpcion(clave, c.GetValue())
		return True


# ====================================================================== ventana principal
NO_HAY_CATEGORIAS = "No hay categorías"


class VentanaBase(wx.Dialog):
	"""Pantalla principal de un módulo: categorías, elementos y botón Menú."""

	modulo = datos.LANZADOR
	titulo = ""
	etiquetaElementos = "&Lista acciones:"
	vacio = "Sin acciones"
	extensionCopia = ".zut-zl"
	textoBorrarTodo = ""
	textoRestaurar = ""
	esNota = False

	def __init__(self) -> None:
		super().__init__(None, title=self.titulo, size=(900, 600), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX | wx.MINIMIZE_BOX)
		self.base = datos.BaseDatos(self.modulo)
		self.sesion = estado.sesiones[self.modulo]
		self.elementos: list[list] = []
		self.cerrada = False
		estado.ventanaAbierta = True

		principal = wx.BoxSizer(wx.HORIZONTAL)
		izq = wx.BoxSizer(wx.VERTICAL)
		etiqueta(self, izq, "&Categorías:")
		self.lstCategorias = wx.ListBox(self, size=(260, -1), style=wx.LB_SINGLE)
		izq.Add(self.lstCategorias, 1, wx.EXPAND | wx.ALL, 6)
		der = wx.BoxSizer(wx.VERTICAL)
		etiqueta(self, der, self.etiquetaElementos)
		self.lstElementos = wx.ListBox(self, style=wx.LB_SINGLE)
		der.Add(self.lstElementos, 1, wx.EXPAND | wx.ALL, 6)
		self.menuBTN = wx.Button(self, label="&Menú")
		der.Add(self.menuBTN, 0, wx.EXPAND | wx.ALL, 6)
		principal.Add(izq, 0, wx.EXPAND)
		principal.Add(der, 1, wx.EXPAND)
		self.SetSizer(principal)

		self.lstCategorias.Bind(wx.EVT_LISTBOX, lambda evt: self.refrescarElementos())
		self.lstCategorias.Bind(wx.EVT_CONTEXT_MENU, self.menuCategoria)
		self.lstCategorias.Bind(wx.EVT_KEY_DOWN, self.onTeclasCategoria)
		self.lstElementos.Bind(wx.EVT_CONTEXT_MENU, self.menuElementos)
		self.lstElementos.Bind(wx.EVT_KEY_DOWN, self.onTeclasElementos)
		self.menuBTN.Bind(wx.EVT_BUTTON, self.menuBoton)
		for nombre, ctrl in (("categorias", self.lstCategorias), ("elementos", self.lstElementos), ("menu", self.menuBTN)):
			ctrl.Bind(wx.EVT_SET_FOCUS, lambda evt, n=nombre: (setattr(self.sesion, "foco", n), evt.Skip()))
		self.Bind(wx.EVT_CHAR_HOOK, self.onTeclaVentana)
		self.Bind(wx.EVT_CLOSE, self.onSalir)
		self._hwnd = self.GetHandle()
		self.Bind(wx.EVT_WINDOW_DESTROY, self._onDestroy)

		self.base.comprobar()
		self.cargarCategorias(self.sesion.posicion[0], self.sesion.posicion[1])
		self.CentreOnScreen()

	# ------------------------------------------------------------------ foco
	def enfocarInicial(self) -> None:
		ctrl = {"categorias": self.lstCategorias, "elementos": self.lstElementos, "menu": self.menuBTN}.get(self.sesion.foco, self.lstCategorias)
		ctrl.SetFocus()

	def _onDestroy(self, evt) -> None:
		evt.Skip()
		# Durante la destrucción el objeto del evento puede ser otro envoltorio:
		# se compara por la ventana de Windows.
		obj = evt.GetEventObject()
		try:
			mismo = obj is self or (obj is not None and obj.GetHandle() == self._hwnd)
		except Exception:
			mismo = False
		if mismo:
			self.cerrada = True
			estado.ventanaAbierta = False

	# ------------------------------------------------------------------ listas
	@property
	def hayCategorias(self) -> bool:
		return bool(self.categoriasNombres)

	def catActual(self) -> int:
		i = self.lstCategorias.GetSelection()
		return i if self.hayCategorias and 0 <= i < len(self.categoriasNombres) else -1

	def elemActual(self) -> int:
		i = self.lstElementos.GetSelection()
		return i if self.elementos and 0 <= i < len(self.elementos) else -1

	def cargarCategorias(self, seleccion: int = 0, seleccionElemento: int = 0) -> None:
		self.categoriasNombres = self.base.nombresCategorias()
		self.lstCategorias.Clear()
		if not self.categoriasNombres:
			self.lstCategorias.Append(NO_HAY_CATEGORIAS)
			self.lstCategorias.SetSelection(0)
		else:
			self.lstCategorias.Append(self.categoriasNombres)
			self.lstCategorias.SetSelection(max(0, min(seleccion, len(self.categoriasNombres) - 1)))
		self.refrescarElementos(seleccionElemento)

	def refrescarElementos(self, seleccion: int = 0) -> None:
		cat = self.catActual()
		self.elementos = self.base.elementos(cat) if cat >= 0 else []
		self.lstElementos.Clear()
		if not self.elementos:
			self.lstElementos.Append(self.vacio)
			self.lstElementos.SetSelection(0)
		else:
			self.lstElementos.Append([e[1] for e in self.elementos])
			self.lstElementos.SetSelection(max(0, min(seleccion, len(self.elementos) - 1)))

	# ------------------------------------------------------------------ teclas
	def onTeclaVentana(self, evt) -> None:
		if evt.GetKeyCode() == wx.WXK_ESCAPE and not evt.HasAnyModifiers():
			self.onSalir(None)
			return
		evt.Skip()

	def onTeclasCategoria(self, evt) -> None:
		code = evt.GetKeyCode()
		if evt.AltDown() and not evt.ControlDown() and code in (wx.WXK_UP, wx.WXK_DOWN) and self.catActual() >= 0:
			self.moverCategoria(-1 if code == wx.WXK_UP else 1)
			return
		evt.Skip()

	def onTeclasElementos(self, evt) -> None:
		code = evt.GetKeyCode()
		i = self.elemActual()
		if i < 0:
			evt.Skip()
			return
		if evt.AltDown() and not evt.ControlDown() and code in (wx.WXK_UP, wx.WXK_DOWN):
			self.moverElemento(-1 if code == wx.WXK_UP else 1)
			return
		if not evt.HasAnyModifiers():
			if code == wx.WXK_SPACE:
				self.activar(i)
				return
			if self.teclaElemento(code, i):
				return
		evt.Skip()

	def teclaElemento(self, code: int, indice: int) -> bool:
		"""Teclas propias del módulo en la lista de elementos (``True`` si se atiende)."""
		return False

	def activar(self, indice: int) -> None:
		"""Espacio en la lista de elementos."""

	# ------------------------------------------------------------------ mover con Alt+flechas
	def moverCategoria(self, delta: int) -> None:
		i = self.catActual()
		nuevo = self.base.moverCategoria(i, delta)
		if nuevo is None:
			sistema.pitido(100 if delta < 0 else 200, 150)
			return
		self.cargarCategorias(nuevo)

	def moverElemento(self, delta: int) -> None:
		cat, i = self.catActual(), self.elemActual()
		nuevo = self.base.moverElemento(cat, i, delta)
		if nuevo is None:
			sistema.pitido(100 if delta < 0 else 200, 150)
			return
		self.refrescarElementos(nuevo)

	# ------------------------------------------------------------------ menús
	def _menu(self, entradas) -> wx.Menu:
		"""``entradas``: (etiqueta, función), (etiqueta, [submenú]) o ``None``."""
		menu = wx.Menu()
		for e in entradas:
			if e is None:
				menu.AppendSeparator()
				continue
			texto, destino = e
			if isinstance(destino, list):
				menu.AppendSubMenu(self._menu(destino), texto)
			else:
				item = menu.Append(wx.ID_ANY, texto)
				# Se enlaza al propio menú: desaparece con él al destruirlo.
				menu.Bind(wx.EVT_MENU, lambda evt, f=destino: wx.CallAfter(f), item)
		return menu

	def entradasCategoria(self) -> list:
		return [
			("&Añadir categoría", self.añadirCategoria),
			("&Editar categoría", self.editarCategoria),
			("&Borrar categoría", self.borrarCategoria),
		]

	def entradasElementos(self) -> list:
		raise NotImplementedError

	def entradasOpciones(self) -> list:
		raise NotImplementedError

	def entradasMenu(self) -> list:
		return [
			("&Categorías", self.entradasCategoria()),
			self.entradaSubmenuElementos(),
			("&Hacer o restaurar copias de seguridad", [("&Hacer copia de seguridad", self.hacerCopia), ("&Restaurar copia de seguridad", self.restaurarCopia)]),
			("&Opciones", self.entradasOpciones()),
			("&Salir", lambda: self.onSalir(None)),
		]

	def entradaSubmenuElementos(self):
		raise NotImplementedError

	def menuBoton(self, evt) -> None:
		menu = self._menu(self.entradasMenu())
		self.PopupMenu(menu, self.menuBTN.GetPosition())
		menu.Destroy()

	def menuCategoria(self, evt) -> None:
		menu = self._menu(self.entradasCategoria())
		self.lstCategorias.PopupMenu(menu)
		menu.Destroy()

	def menuElementos(self, evt) -> None:
		menu = self._menu(self.entradasElementos())
		self.lstElementos.PopupMenu(menu)
		menu.Destroy()

	# ------------------------------------------------------------------ categorías
	def añadirCategoria(self) -> None:
		dlg = DialogoCategoria(self, self.base.nombresCategorias())
		try:
			if dlg.ShowModal() == wx.ID_OK:
				pos = self.base.añadirCategoria(dlg.resultado)
				self.cargarCategorias(pos)
		finally:
			dlg.Destroy()
		self.lstCategorias.SetFocus()

	def editarCategoria(self) -> None:
		i = self.catActual()
		if i < 0:
			mensaje(self, "No tiene ninguna categoría para Editar.\n\nAgregue antes una para llevar a cabo esta acción.")
			return
		nombres = self.base.nombresCategorias()
		dlg = DialogoCategoria(self, nombres, nombres[i])
		try:
			if dlg.ShowModal() == wx.ID_OK:
				self.base.renombrarCategoria(i, dlg.resultado)
				self.cargarCategorias(i)
		finally:
			dlg.Destroy()
		self.lstCategorias.SetFocus()

	def borrarCategoria(self) -> None:
		i = self.catActual()
		if i < 0:
			mensaje(self, "No tiene ninguna categoría para Borrar.\n\nAgregue antes una para llevar a cabo esta acción.")
			return
		que = "las notas" if self.esNota else "las aplicaciones"
		texto = (
			"ADVERTENCIA:\n\nEsta acción no es reversible.\n\nVa a borrar la categoría:\n\n{}\n\n"
			"Tenga en cuenta que al borrar la categoría se eliminaran {} que estuvieran en dicha categoría.\n\n¿Esta seguro que desea continuar?"
		).format(self.categoriasNombres[i], que)
		if preguntar(self, texto):
			self.base.borrarCategoria(i)
			self.cargarCategorias(0)
		self.lstCategorias.SetFocus()

	# ------------------------------------------------------------------ comunes a los elementos
	def comprobarCategoria(self, verbo: str = "añadir") -> bool:
		if self.catActual() < 0:
			que = "una Nota" if self.esNota else "una acción"
			mensaje(self, f"No tiene ninguna categoría.\n\nAgregue una categoría antes para poder {verbo} {que}.")
			return False
		return True

	def comprobarElemento(self, verbo: str) -> bool:
		if self.elemActual() < 0:
			que = "ninguna Nota" if self.esNota else "ninguna acción"
			mensaje(self, f"No tiene {que}.\n\nAgregue una antes para poder {verbo}.")
			return False
		return True

	def borrarElemento(self) -> None:
		if not self.comprobarCategoria() or not self.comprobarElemento("borrar"):
			return
		cat, i = self.catActual(), self.elemActual()
		que = "la Nota" if self.esNota else "la acción"
		texto = "ADVERTENCIA:\n\nEsta acción no es reversible.\n\nVa a borrar {}:\n\n{}\n\n¿Esta seguro que desea continuar?".format(que, self.elementos[i][1])
		if preguntar(self, texto):
			self.base.borrarElemento(cat, i)
			self.refrescarElementos(i)
		self.lstElementos.SetFocus()

	def moverACategoria(self) -> None:
		if not self.comprobarCategoria("mover") or not self.comprobarElemento("mover"):
			return
		if len(self.categoriasNombres) < 2:
			mensaje(self, "No hay categorías suficientes.\n\nPara mover entre categorías es necesario al menos dos categorías.")
			return
		cat, i = self.catActual(), self.elemActual()
		dlg = DialogoMover(self, self.base, cat, i, self.esNota)
		try:
			if dlg.ShowModal() == wx.ID_OK:
				self.refrescarElementos(i)
		finally:
			dlg.Destroy()
		self.lstElementos.SetFocus()

	def guardarNuevo(self, elemento: list) -> None:
		pos = self.base.añadirElemento(self.catActual(), elemento)
		self.refrescarElementos(pos)
		self.lstElementos.SetFocus()

	def guardarEditado(self, indice: int, elemento: list) -> None:
		self.base.sustituirElemento(self.catActual(), indice, elemento)
		self.refrescarElementos(indice)
		self.lstElementos.SetFocus()

	# ------------------------------------------------------------------ copias
	def hacerCopia(self) -> None:
		comodin = "Archivo copia de seguridad zUtilidades (*{0})|*{0}".format(self.extensionCopia)
		dlg = wx.FileDialog(self, message="Guardar en...", defaultDir=carpetaDocumentos(), defaultFile=copias.nombrePorDefecto() + self.extensionCopia, wildcard=comodin, style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
		try:
			if dlg.ShowModal() != wx.ID_OK:
				return
			ruta = dlg.GetPath()
		finally:
			dlg.Destroy()
		if not ruta.lower().endswith(self.extensionCopia):
			ruta += self.extensionCopia
		prog = DialogoCopia(self, "Haciendo copia de seguridad...", self.modulo, ruta)
		try:
			prog.ShowModal()
		finally:
			prog.Destroy()
		self.enfocarInicial()

	def restaurarCopia(self) -> None:
		if not preguntar(self, self.textoRestaurar):
			return
		comodin = "Archivo copia de seguridad zUtilidades (*{0})|*{0}".format(self.extensionCopia)
		dlg = wx.FileDialog(self, message="Seleccione un archivo de copia de seguridad", defaultDir=carpetaDocumentos(), wildcard=comodin, style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
		try:
			if dlg.ShowModal() != wx.ID_OK:
				self.enfocarInicial()
				return
			ruta = dlg.GetPath()
		finally:
			dlg.Destroy()
		prog = DialogoCopia(self, "Restaurando copia de seguridad...", self.modulo, ruta, restaurar=True)
		try:
			res = prog.ShowModal()
		finally:
			prog.Destroy()
		if res == wx.ID_OK:
			# El módulo se cierra; al volver a abrirlo ya tiene la copia restaurada.
			self.sesion.reiniciar()
			self.cerrar(guardarPosicion=False)
		else:
			self.enfocarInicial()

	def borrarValores(self) -> None:
		if not preguntar(self, self.textoBorrarTodo):
			return
		self.base.borrarTodo()
		self.sesion.reiniciar()
		self.cerrar(guardarPosicion=False)

	# ------------------------------------------------------------------ cerrar
	def guardarPosicion(self) -> None:
		self.sesion.posicion = [max(0, self.lstCategorias.GetSelection()), max(0, self.lstElementos.GetSelection())]

	def cerrar(self, guardarPosicion: bool = True) -> None:
		if self.cerrada:
			return
		self.cerrada = True
		if guardarPosicion:
			self.guardarPosicion()
		estado.ventanaAbierta = False
		self.Hide()
		self.Destroy()

	def onSalir(self, evt) -> None:
		self.cerrar()
