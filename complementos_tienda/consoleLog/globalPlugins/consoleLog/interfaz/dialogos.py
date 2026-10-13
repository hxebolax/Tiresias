"""Diálogos auxiliares: resultados de las herramientas, listas, claves, instrucciones y regiones."""

from __future__ import annotations

import wx

from tiresias.gui.helpers import speakMessage

from ..definiciones_ventana import MODOS_VALIDOS, NOMBRES_MODOS, DefinicionVentana, GestorDefinicionesVentana, clave_desde_nombre


def _copiar(texto: str) -> bool:
	from tiresias import api

	try:
		return bool(api.copyToClip(texto))
	except Exception:
		return False


def _etiqueta(padre: wx.Window, sizer: wx.Sizer, texto: str) -> None:
	sizer.Add(wx.StaticText(padre, label=texto), 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)


class DialogoTexto(wx.Dialog):
	"""Texto de solo lectura recorrible con las flechas (resultados y ayuda)."""

	def __init__(self, parent, titulo: str, mensaje: str, etiqueta: str = "&Contenido:", copiar: bool = True) -> None:
		super().__init__(parent, title=titulo, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
		self._mensaje = mensaje
		sizer = wx.BoxSizer(wx.VERTICAL)
		_etiqueta(self, sizer, etiqueta)
		self.txt = wx.TextCtrl(self, size=(620, 420), style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.TE_NOHIDESEL)
		self.txt.SetValue(mensaje)
		sizer.Add(self.txt, 1, wx.EXPAND | wx.ALL, 8)
		botones = wx.BoxSizer(wx.HORIZONTAL)
		if copiar:
			b = wx.Button(self, label="Co&piar todo")
			b.Bind(wx.EVT_BUTTON, self._alCopiar)
			botones.Add(b, 0, wx.ALL, 4)
			g = wx.Button(self, label="&Guardar como...")
			g.Bind(wx.EVT_BUTTON, self._alGuardar)
			botones.Add(g, 0, wx.ALL, 4)
		aceptar = wx.Button(self, wx.ID_OK, "&Aceptar")
		aceptar.SetDefault()
		botones.Add(aceptar, 0, wx.ALL, 4)
		sizer.Add(botones, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_OK)
		self.CentreOnParent()
		self.txt.SetInsertionPoint(0)
		wx.CallAfter(self.txt.SetFocus)

	def _alCopiar(self, _evt) -> None:
		speakMessage("Copiado al portapapeles" if _copiar(self._mensaje) else "No se pudo copiar")

	def _alGuardar(self, _evt) -> None:
		guardar_texto(self, self._mensaje)


def guardar_texto(parent, texto: str, titulo: str = "Guardar contenido", nombre: str = "consola.txt") -> bool:
	"""Guarda ``texto`` en UTF-8 con un diálogo de archivo."""
	with wx.FileDialog(parent, titulo, defaultFile=nombre, wildcard="Archivos de texto (*.txt)|*.txt|Todos los archivos (*.*)|*.*", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
		if dlg.ShowModal() != wx.ID_OK:
			return False
		ruta = dlg.GetPath()
	try:
		with open(ruta, "w", encoding="utf-8", newline="\n") as f:
			f.write(texto)
	except OSError as e:
		from tiresias.gui import messageBox

		messageBox("No se pudo guardar el archivo:\n{}".format(e), "Error", wx.OK | wx.ICON_ERROR, parent)
		return False
	speakMessage("Archivo guardado")
	return True


class DialogoLista(wx.Dialog):
	"""Lista de resultados: Intro o «Copiar» copia el elemento elegido."""

	def __init__(self, parent, titulo: str, mensaje: str, elementos: list[str], valor=None) -> None:
		super().__init__(parent, title=titulo, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._elementos = list(elementos)
		self._valor = valor or (lambda e: e)
		self.copiado = ""
		sizer = wx.BoxSizer(wx.VERTICAL)
		_etiqueta(self, sizer, "&Filtrar:")
		self.filtro = wx.TextCtrl(self)
		sizer.Add(self.filtro, 0, wx.EXPAND | wx.ALL, 8)
		_etiqueta(self, sizer, mensaje)
		self.lista = wx.ListBox(self, choices=self._elementos, size=(620, 320), style=wx.LB_SINGLE | wx.LB_HSCROLL)
		sizer.Add(self.lista, 1, wx.EXPAND | wx.ALL, 8)
		_etiqueta(self, sizer, "&Detalle del elemento:")
		self.detalle = wx.TextCtrl(self, size=(620, 100), style=wx.TE_MULTILINE | wx.TE_READONLY)
		sizer.Add(self.detalle, 0, wx.EXPAND | wx.ALL, 8)
		botones = wx.BoxSizer(wx.HORIZONTAL)
		copiar = wx.Button(self, wx.ID_OK, "&Copiar")
		copiar.SetDefault()
		todo = wx.Button(self, label="Copiar &todos")
		cerrar = wx.Button(self, wx.ID_CANCEL, "Ce&rrar")
		for b in (copiar, todo, cerrar):
			botones.Add(b, 0, wx.ALL, 4)
		sizer.Add(botones, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		copiar.Bind(wx.EVT_BUTTON, self._alCopiar)
		todo.Bind(wx.EVT_BUTTON, self._alCopiarTodos)
		self.lista.Bind(wx.EVT_LISTBOX_DCLICK, self._alCopiar)
		self.lista.Bind(wx.EVT_LISTBOX, self._alElegir)
		self.filtro.Bind(wx.EVT_TEXT, self._alFiltrar)
		if self._elementos:
			self.lista.SetSelection(0)
			self._alElegir(None)
		self.CentreOnParent()
		wx.CallAfter(self.lista.SetFocus)

	def _visibles(self) -> list[str]:
		return list(self.lista.GetStrings())

	def _alFiltrar(self, _evt) -> None:
		consulta = self.filtro.GetValue().strip().lower()
		self.lista.Set([e for e in self._elementos if consulta in e.lower()] if consulta else self._elementos)
		if self.lista.GetCount():
			self.lista.SetSelection(0)
		self._alElegir(None)

	def _alElegir(self, _evt) -> None:
		i = self.lista.GetSelection()
		self.detalle.SetValue(self.lista.GetString(i) if i != wx.NOT_FOUND else "")

	def _alCopiar(self, _evt) -> None:
		i = self.lista.GetSelection()
		if i == wx.NOT_FOUND:
			return
		texto = self._valor(self.lista.GetString(i))
		if _copiar(texto):
			self.copiado = texto
			self.EndModal(wx.ID_OK)

	def _alCopiarTodos(self, _evt) -> None:
		texto = "\n".join(self._valor(e) for e in self._visibles())
		if texto and _copiar(texto):
			self.copiado = texto
			self.EndModal(wx.ID_OK)


class DialogoJSON(wx.Dialog):
	"""Un bloque JSON formateado; «Siguiente» pasa al siguiente bloque."""

	def __init__(self, parent, bloques: list[str]) -> None:
		super().__init__(parent, title="JSON formateado", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
		self._bloques = list(bloques)
		self._indice = 0
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.etiqueta = wx.StaticText(self, label="")
		sizer.Add(self.etiqueta, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
		self.txt = wx.TextCtrl(self, size=(620, 420), style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.TE_DONTWRAP)
		sizer.Add(self.txt, 1, wx.EXPAND | wx.ALL, 8)
		botones = wx.BoxSizer(wx.HORIZONTAL)
		self.anterior = wx.Button(self, label="&Anterior")
		self.siguiente = wx.Button(self, label="&Siguiente")
		copiar = wx.Button(self, label="&Copiar este bloque")
		cerrar = wx.Button(self, wx.ID_CANCEL, "Ce&rrar")
		for b in (self.anterior, self.siguiente, copiar, cerrar):
			botones.Add(b, 0, wx.ALL, 4)
		sizer.Add(botones, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.anterior.Bind(wx.EVT_BUTTON, lambda e: self._ir(-1))
		self.siguiente.Bind(wx.EVT_BUTTON, lambda e: self._ir(1))
		copiar.Bind(wx.EVT_BUTTON, self._alCopiar)
		self._mostrar()
		self.CentreOnParent()
		wx.CallAfter(self.txt.SetFocus)

	def _mostrar(self) -> None:
		total = len(self._bloques)
		self.etiqueta.SetLabel("&JSON detectado ({} de {}):".format(self._indice + 1, total))
		self.txt.SetName("JSON {} de {}".format(self._indice + 1, total))
		self.txt.SetValue(self._bloques[self._indice])
		self.txt.SetInsertionPoint(0)
		self.SetTitle("JSON formateado ({}/{})".format(self._indice + 1, total))
		self.anterior.Enable(self._indice > 0)
		self.siguiente.Enable(self._indice < total - 1)

	def _ir(self, paso: int) -> None:
		nuevo = self._indice + paso
		if 0 <= nuevo < len(self._bloques):
			self._indice = nuevo
			self._mostrar()
			speakMessage("Bloque {} de {}".format(nuevo + 1, len(self._bloques)))
			self.txt.SetFocus()

	def _alCopiar(self, _evt) -> None:
		speakMessage("JSON copiado al portapapeles" if _copiar(self._bloques[self._indice]) else "No se pudo copiar")


class DialogoTextoEditable(wx.Dialog):
	"""Texto de varias líneas para editar (claves, instrucciones de sistema)."""

	def __init__(self, parent, titulo: str, etiqueta: str, valor: str, defecto: str | None = None, ocultar: bool = False, ayuda: str = "") -> None:
		super().__init__(parent, title=titulo, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._defecto = defecto
		sizer = wx.BoxSizer(wx.VERTICAL)
		if ayuda:
			sizer.Add(wx.StaticText(self, label=ayuda), 0, wx.ALL, 8)
		_etiqueta(self, sizer, etiqueta)
		self.txt = wx.TextCtrl(self, value=valor, size=(520, 240), style=wx.TE_MULTILINE)
		sizer.Add(self.txt, 1, wx.EXPAND | wx.ALL, 8)
		botones = wx.BoxSizer(wx.HORIZONTAL)
		if defecto is not None:
			restablecer = wx.Button(self, label="&Restablecer por defecto")
			restablecer.Bind(wx.EVT_BUTTON, lambda e: self.txt.SetValue(self._defecto or ""))
			botones.Add(restablecer, 0, wx.ALL, 4)
		botones.AddStretchSpacer()
		guardar = wx.Button(self, wx.ID_OK, "&Guardar")
		guardar.SetDefault()
		cancelar = wx.Button(self, wx.ID_CANCEL, "&Cancelar")
		botones.Add(guardar, 0, wx.ALL, 4)
		botones.Add(cancelar, 0, wx.ALL, 4)
		sizer.Add(botones, 0, wx.EXPAND | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.CentreOnParent()
		wx.CallAfter(self.txt.SetFocus)

	def GetValue(self) -> str:
		return self.txt.GetValue()


def editar_claves_google(parent) -> bool:
	"""Diálogo de claves de Google AI (una por línea). Devuelve ``True`` si se guardan."""
	from .. import ia

	dlg = DialogoTextoEditable(
		parent,
		"Gestionar claves de API",
		"&Claves de API de Google AI Studio (una por línea):",
		"\n".join(ia.cargar_claves()),
		ayuda="Si una clave falla por autenticación o por cuota se prueba la siguiente. Se guardan cifradas para su cuenta de Windows.",
	)
	try:
		if dlg.ShowModal() != wx.ID_OK:
			return False
		try:
			ia.guardar_claves(ia.separar_claves(dlg.GetValue()))
		except Exception as e:  # noqa: BLE001
			from tiresias.gui import messageBox

			messageBox("No se pudieron guardar las claves: {}".format(e), "Error", wx.OK | wx.ICON_ERROR, parent)
			return False
		speakMessage("Claves guardadas")
		return True
	finally:
		dlg.Destroy()


# ====================================================================== definiciones de ventana
class EditarDefinicionDialog(wx.Dialog):
	def __init__(self, parent, definicion: DefinicionVentana | None = None) -> None:
		super().__init__(parent, title="Editar región" if definicion else "Nueva región")
		d = definicion or DefinicionVentana("", 1, 24, 1, 80)
		sizer = wx.BoxSizer(wx.VERTICAL)
		rejilla = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)

		def fila(etiqueta: str, control: wx.Window) -> wx.Window:
			rejilla.Add(wx.StaticText(self, label=etiqueta), 0, wx.ALIGN_CENTER_VERTICAL)
			rejilla.Add(control, 1, wx.EXPAND)
			return control

		self.nombre = fila("&Nombre:", wx.TextCtrl(self, value=d.nombre, size=(260, -1)))
		self.descripcion = fila("&Descripción:", wx.TextCtrl(self, value=d.descripcion, size=(260, -1)))
		self.fila_sup = fila("Fila &superior:", wx.SpinCtrl(self, min=1, max=100000, initial=d.fila_superior))
		self.fila_inf = fila("Fila &inferior:", wx.SpinCtrl(self, min=1, max=100000, initial=d.fila_inferior))
		self.col_izq = fila("Columna i&zquierda:", wx.SpinCtrl(self, min=1, max=10000, initial=d.columna_izquierda))
		self.col_der = fila("Columna &derecha:", wx.SpinCtrl(self, min=1, max=10000, initial=d.columna_derecha))
		self.modo = fila("&Modo de lectura:", wx.Choice(self, choices=[NOMBRES_MODOS[m] for m in MODOS_VALIDOS]))
		self.modo.SetSelection(MODOS_VALIDOS.index(d.modo))
		sizer.Add(rejilla, 1, wx.EXPAND | wx.ALL, 10)
		self.habilitada = wx.CheckBox(self, label="Región &activa")
		self.habilitada.SetValue(d.habilitada)
		sizer.Add(self.habilitada, 0, wx.LEFT | wx.RIGHT, 10)
		sizer.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, 10)
		self.SetSizerAndFit(sizer)
		self.CentreOnParent()
		self.Bind(wx.EVT_BUTTON, self._alAceptar, id=wx.ID_OK)
		wx.CallAfter(self.nombre.SetFocus)

	def _alAceptar(self, evt) -> None:
		if not self.nombre.GetValue().strip():
			from tiresias.gui import messageBox

			messageBox("Escriba un nombre para la región.", "Región", wx.OK | wx.ICON_WARNING, self)
			self.nombre.SetFocus()
			return
		evt.Skip()

	def definicion(self) -> DefinicionVentana:
		return DefinicionVentana(
			self.nombre.GetValue().strip(),
			self.fila_sup.GetValue(),
			self.fila_inf.GetValue(),
			self.col_izq.GetValue(),
			self.col_der.GetValue(),
			MODOS_VALIDOS[max(0, self.modo.GetSelection())],
			self.habilitada.GetValue(),
			self.descripcion.GetValue().strip(),
		)


class DefinicionesDialog(wx.Dialog):
	"""Gestión de las definiciones de ventana (regiones) y su informe."""

	def __init__(self, parent, gestor: GestorDefinicionesVentana, texto: str = "") -> None:
		super().__init__(parent, title="Definiciones de ventana", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._gestor = gestor
		self._texto = texto
		sizer = wx.BoxSizer(wx.VERTICAL)
		_etiqueta(self, sizer, "&Regiones (marque las activas):")
		self.lista = wx.CheckListBox(self, size=(560, 260))
		sizer.Add(self.lista, 1, wx.EXPAND | wx.ALL, 8)
		botones = wx.BoxSizer(wx.HORIZONTAL)
		self.b_nueva = wx.Button(self, label="&Nueva...")
		self.b_editar = wx.Button(self, label="&Editar...")
		self.b_eliminar = wx.Button(self, label="E&liminar")
		self.b_informe = wx.Button(self, label="&Informe sobre el texto del visor")
		self.b_cerrar = wx.Button(self, wx.ID_CANCEL, "Ce&rrar")
		for b in (self.b_nueva, self.b_editar, self.b_eliminar, self.b_informe, self.b_cerrar):
			botones.Add(b, 0, wx.ALL, 4)
		sizer.Add(botones, 0, wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.b_nueva.Bind(wx.EVT_BUTTON, self._alNueva)
		self.b_editar.Bind(wx.EVT_BUTTON, self._alEditar)
		self.b_eliminar.Bind(wx.EVT_BUTTON, self._alEliminar)
		self.b_informe.Bind(wx.EVT_BUTTON, self._alInforme)
		self.lista.Bind(wx.EVT_CHECKLISTBOX, self._alMarcar)
		self.lista.Bind(wx.EVT_LISTBOX_DCLICK, self._alEditar)
		self._claves: list[str] = []
		self._recargar()
		self.CentreOnParent()
		wx.CallAfter(self.lista.SetFocus)

	def _recargar(self, seleccion: str | None = None) -> None:
		self._claves = self._gestor.listar_definiciones()
		elementos = []
		for clave in self._claves:
			d = self._gestor.obtener_definicion(clave)
			elementos.append(d.obtener_descripcion() if d else clave)
		self.lista.Set(elementos)
		for i, clave in enumerate(self._claves):
			d = self._gestor.obtener_definicion(clave)
			self.lista.Check(i, bool(d and d.habilitada))
		if self._claves:
			i = self._claves.index(seleccion) if seleccion in self._claves else 0
			self.lista.SetSelection(i)
		hay = bool(self._claves)
		self.b_editar.Enable(hay)
		self.b_eliminar.Enable(hay)

	def _clave(self) -> str | None:
		i = self.lista.GetSelection()
		return self._claves[i] if 0 <= i < len(self._claves) else None

	def _guardar(self) -> None:
		self._gestor.guardar_definiciones()

	def _alMarcar(self, evt) -> None:
		i = evt.GetInt()
		if 0 <= i < len(self._claves):
			activa = self.lista.IsChecked(i)
			self._gestor.habilitar_definicion(self._claves[i], activa)
			self._guardar()
			d = self._gestor.obtener_definicion(self._claves[i])
			self.lista.SetString(i, d.obtener_descripcion() if d else self._claves[i])
			self.lista.Check(i, activa)
			speakMessage("activada" if activa else "desactivada")

	def _alNueva(self, _evt) -> None:
		dlg = EditarDefinicionDialog(self)
		try:
			if dlg.ShowModal() == wx.ID_OK:
				d = dlg.definicion()
				clave = clave_desde_nombre(d.nombre)
				base, n = clave, 2
				while clave in self._claves:
					clave = "{}_{}".format(base, n)
					n += 1
				self._gestor.agregar_definicion(clave, d)
				self._guardar()
				self._recargar(clave)
		finally:
			dlg.Destroy()
		self.lista.SetFocus()

	def _alEditar(self, _evt) -> None:
		clave = self._clave()
		d = self._gestor.obtener_definicion(clave) if clave else None
		if d is None:
			return
		dlg = EditarDefinicionDialog(self, d)
		try:
			if dlg.ShowModal() == wx.ID_OK:
				self._gestor.agregar_definicion(clave, dlg.definicion())
				self._guardar()
				self._recargar(clave)
		finally:
			dlg.Destroy()
		self.lista.SetFocus()

	def _alEliminar(self, _evt) -> None:
		clave = self._clave()
		d = self._gestor.obtener_definicion(clave) if clave else None
		if d is None:
			return
		from tiresias.gui import messageBox

		if messageBox("¿Eliminar la región «{}»?".format(d.nombre), "Eliminar región", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self) != wx.YES:
			return
		self._gestor.eliminar_definicion(clave)
		self._guardar()
		self._recargar()
		speakMessage("Región eliminada")
		self.lista.SetFocus()

	def _alInforme(self, _evt) -> None:
		from ..herramientas.definiciones_ventana import informe_definiciones

		dlg = DialogoTexto(self, "Informe de definiciones de ventana", informe_definiciones(self._gestor, self._texto))
		dlg.ShowModal()
		dlg.Destroy()
