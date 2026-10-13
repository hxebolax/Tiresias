"""Ventana principal de la Audiocinemateca.

Pestañas (Alt+1 a Alt+8): General, Películas, Series, Documentales,
Cortometrajes, Favoritos, Historial y Listas. Debajo, los controles del
reproductor (solo visibles mientras algo suena o está en pausa) y el botón
Menú. Teclas: Intro abre la ficha, F1 a F12 controlan el reproductor,
Control+I/F/C, Retroceso, Suprimir y Mayúsculas+F10 (o tecla Aplicaciones)
para el filtro de búsqueda.
"""

from __future__ import annotations

import os
import threading

import wx

from . import ajustes, catalogo, dialogos
from .control import hablar, informar
from .reproductor import REPRODUCIENDO

NOMBRES_PESTANAS = ["General", "Películas", "Series", "Documentales", "Cortometrajes", "Favoritos", "Historial", "Listas"]
FORMATOS_BUSQUEDA = [
	"&Buscar películas por {}:",
	"&Buscar series por {}:",
	"&Buscar documentales por {}:",
	"&Buscar cortometrajes por {}:",
]
ETIQUETAS_LISTA = ["&Lista de películas:", "&Lista de series:", "&Lista de documentales:", "&Lista de cortometrajes:"]
SIN_RESULTADOS = "Sin resultados"


def _etiqueta(parent, sizer, texto) -> wx.StaticText:
	st = wx.StaticText(parent, label=texto)
	sizer.Add(st, 0, wx.LEFT | wx.RIGHT | wx.TOP, 4)
	return st


class VentanaPrincipal(wx.Dialog):
	def __init__(self, complemento) -> None:
		super().__init__(None, title="Audiocinemateca", size=(820, 640), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX | wx.MINIMIZE_BOX)
		self.complemento = complemento
		self.control = complemento.control
		ajustes.estado.ventanaAbierta = True
		self._cerrada = False
		self.colecciones = [self.control.catalogo.coleccion(c) for c in ajustes.CLAVES_CATEGORIA]
		# Estado de la búsqueda de cada pestaña de categoría.
		self.filtro = [0, 0, 0, 0]
		self.resultados: list[list[dict] | None] = [None, None, None, None]
		self._ultimos: list[dict] = []
		self._globales: list[tuple[dict, str]] = []
		self._favoritos: list[dict] = []
		self._historial: list[dict] = []
		self._itemsLista: list[dict] = []

		self.panel = wx.Panel(self)
		general = wx.BoxSizer(wx.VERTICAL)
		self.notebook = wx.Notebook(self.panel)
		general.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 4)
		self._crearGeneral()
		self.txtBusqueda: list[wx.TextCtrl] = []
		self.lblBusqueda: list[wx.StaticText] = []
		self.listCategoria: list[wx.ListBox] = []
		for i, (clave, plural, _s) in enumerate(ajustes.CATEGORIAS):
			self._crearCategoria(i, f"{plural} (Alt+{i + 2})")
		self._crearFavoritos()
		self._crearHistorial()
		self._crearListas()

		# Controles del reproductor.
		self.sizerRepro = wx.BoxSizer(wx.HORIZONTAL)
		self.btnAtrasar = wx.Button(self.panel, label="Atrasar")
		self.btnReproducir = wx.Button(self.panel, label="Reproducir")
		self.btnAdelantar = wx.Button(self.panel, label="Adelantar")
		self.btnDetener = wx.Button(self.panel, label="Detener")
		for b in (self.btnAtrasar, self.btnReproducir, self.btnAdelantar, self.btnDetener):
			self.sizerRepro.Add(b, 1, wx.EXPAND | wx.ALL, 2)
		general.Add(self.sizerRepro, 0, wx.EXPAND)
		self.sizerControles = wx.BoxSizer(wx.HORIZONTAL)
		self.lblVolumen = wx.StaticText(self.panel, label="&Volumen:")
		self.sliderVolumen = wx.Slider(self.panel, value=ajustes.get("volumen"), minValue=0, maxValue=100)
		self.lblVelocidad = wx.StaticText(self.panel, label="Ve&locidad:")
		self.choiceVelocidad = wx.Choice(self.panel, choices=ajustes.LISTA_VELOCIDAD)
		self.choiceVelocidad.SetSelection(ajustes.get("velocidad"))
		self.sizerControles.Add(self.lblVolumen, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
		self.sizerControles.Add(self.sliderVolumen, 1, wx.EXPAND | wx.ALL, 2)
		self.sizerControles.Add(self.lblVelocidad, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
		self.sizerControles.Add(self.choiceVelocidad, 0, wx.ALL, 2)
		general.Add(self.sizerControles, 0, wx.EXPAND)
		self.controlesReproductor = [
			self.btnAtrasar, self.btnReproducir, self.btnAdelantar, self.btnDetener,
			self.lblVolumen, self.sliderVolumen, self.lblVelocidad, self.choiceVelocidad,
		]
		self.btnMenu = wx.Button(self.panel, label="&Menú")
		general.Add(self.btnMenu, 0, wx.EXPAND | wx.ALL, 4)
		self.panel.SetSizer(general)
		self._vincular()
		self.CentreOnScreen()
		self._cargarInicio()

	# ================================================================ construcción
	def _crearGeneral(self) -> None:
		p = wx.Panel(self.notebook)
		self.notebook.AddPage(p, "General (Alt+1)")
		s = wx.BoxSizer(wx.VERTICAL)
		_etiqueta(p, s, "Últimos &contenidos agregados:")
		self.choiceUltimos = wx.Choice(p, choices=[c[1] for c in ajustes.CATEGORIAS])
		self.choiceUltimos.SetSelection(0)
		s.Add(self.choiceUltimos, 0, wx.EXPAND | wx.ALL, 2)
		_etiqueta(p, s, "&Lista de las últimas entradas:")
		self.listUltimos = wx.ListBox(p)
		s.Add(self.listUltimos, 1, wx.EXPAND | wx.ALL, 2)
		self.btnAleatorio = wx.Button(p, label="¿No sabes qué ver? &Pulsa aquí y te ofreceré algo.")
		s.Add(self.btnAleatorio, 0, wx.EXPAND | wx.ALL, 2)
		_etiqueta(p, s, "Búsqueda &global:")
		self.txtGlobal = wx.TextCtrl(p)
		s.Add(self.txtGlobal, 0, wx.EXPAND | wx.ALL, 2)
		_etiqueta(p, s, "&Resultados de búsqueda global:")
		self.listGlobal = wx.ListBox(p)
		s.Add(self.listGlobal, 1, wx.EXPAND | wx.ALL, 2)
		p.SetSizer(s)

	def _crearCategoria(self, i: int, tituloPestana: str) -> None:
		p = wx.Panel(self.notebook)
		self.notebook.AddPage(p, tituloPestana)
		s = wx.BoxSizer(wx.VERTICAL)
		self.lblBusqueda.append(_etiqueta(p, s, FORMATOS_BUSQUEDA[i].format(ajustes.LISTA_FILTROS[self.filtro[i]])))
		txt = wx.TextCtrl(p)
		s.Add(txt, 0, wx.EXPAND | wx.ALL, 2)
		self.txtBusqueda.append(txt)
		_etiqueta(p, s, ETIQUETAS_LISTA[i])
		lst = wx.ListBox(p)
		s.Add(lst, 1, wx.EXPAND | wx.ALL, 2)
		self.listCategoria.append(lst)
		p.SetSizer(s)

	def _crearFavoritos(self) -> None:
		p = wx.Panel(self.notebook)
		self.notebook.AddPage(p, "Favoritos (Alt+6)")
		s = wx.BoxSizer(wx.HORIZONTAL)
		izq = wx.BoxSizer(wx.VERTICAL)
		_etiqueta(p, izq, "&Categorías:")
		self.treeFavoritos = wx.TreeCtrl(p, style=wx.TR_HAS_BUTTONS | wx.TR_SINGLE)
		izq.Add(self.treeFavoritos, 1, wx.EXPAND | wx.ALL, 2)
		der = wx.BoxSizer(wx.VERTICAL)
		_etiqueta(p, der, "&Favoritos:")
		self.listFavoritos = wx.ListBox(p)
		der.Add(self.listFavoritos, 1, wx.EXPAND | wx.ALL, 2)
		s.Add(izq, 1, wx.EXPAND | wx.ALL, 4)
		s.Add(der, 2, wx.EXPAND | wx.ALL, 4)
		p.SetSizer(s)
		raiz = self.treeFavoritos.AddRoot("Favoritos")
		self.treeFavoritos.SetItemData(raiz, None)
		for clave, plural, _s in ajustes.CATEGORIAS:
			item = self.treeFavoritos.AppendItem(raiz, plural)
			self.treeFavoritos.SetItemData(item, clave)
		self.treeFavoritos.Expand(raiz)
		self.treeFavoritos.SelectItem(raiz)
		self.listFavoritos.Set(["Seleccione una categoría"])
		self.listFavoritos.SetSelection(0)

	def _crearHistorial(self) -> None:
		p = wx.Panel(self.notebook)
		self.notebook.AddPage(p, "Historial (Alt+7)")
		s = wx.BoxSizer(wx.VERTICAL)
		_etiqueta(p, s, "&Filtrar por categoría:")
		self.choiceHistorial = wx.Choice(p, choices=["Todas"] + [c[1] for c in ajustes.CATEGORIAS])
		self.choiceHistorial.SetSelection(0)
		s.Add(self.choiceHistorial, 0, wx.EXPAND | wx.ALL, 2)
		_etiqueta(p, s, "&Historial de reproducción:")
		self.listHistorial = wx.ListBox(p)
		s.Add(self.listHistorial, 1, wx.EXPAND | wx.ALL, 2)
		p.SetSizer(s)

	def _crearListas(self) -> None:
		p = wx.Panel(self.notebook)
		self.notebook.AddPage(p, "Listas (Alt+8)")
		s = wx.BoxSizer(wx.VERTICAL)
		botones = wx.BoxSizer(wx.HORIZONTAL)
		self.btnNuevaLista = wx.Button(p, label="&Nueva lista")
		self.btnEliminarLista = wx.Button(p, label="&Eliminar lista")
		self.btnRenombrarLista = wx.Button(p, label="&Renombrar lista")
		for b in (self.btnNuevaLista, self.btnEliminarLista, self.btnRenombrarLista):
			botones.Add(b, 1, wx.EXPAND | wx.ALL, 2)
		s.Add(botones, 0, wx.EXPAND)
		_etiqueta(p, s, "M&is listas:")
		self.listNombres = wx.ListBox(p)
		s.Add(self.listNombres, 1, wx.EXPAND | wx.ALL, 2)
		_etiqueta(p, s, "&Contenidos de la lista:")
		self.listContenido = wx.ListBox(p)
		s.Add(self.listContenido, 1, wx.EXPAND | wx.ALL, 2)
		p.SetSizer(s)

	def _vincular(self) -> None:
		self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self._onCambioPestana)
		self.choiceUltimos.Bind(wx.EVT_CHOICE, lambda e: self._rellenarUltimos())
		self.choiceVelocidad.Bind(wx.EVT_CHOICE, self._onVelocidad)
		self.sliderVolumen.Bind(wx.EVT_SLIDER, self._onVolumen)
		self.btnAtrasar.Bind(wx.EVT_BUTTON, lambda e: self._atrasar())
		self.btnReproducir.Bind(wx.EVT_BUTTON, lambda e: self._reproducirPausar())
		self.btnAdelantar.Bind(wx.EVT_BUTTON, lambda e: self._adelantar())
		self.btnDetener.Bind(wx.EVT_BUTTON, lambda e: self._detener())
		self.btnAleatorio.Bind(wx.EVT_BUTTON, self._onAleatorio)
		self.btnMenu.Bind(wx.EVT_BUTTON, self._onMenu)
		self.treeFavoritos.Bind(wx.EVT_TREE_SEL_CHANGED, lambda e: self._actualizarFavoritos())
		self.choiceHistorial.Bind(wx.EVT_CHOICE, lambda e: self._actualizarHistorial())
		self.btnNuevaLista.Bind(wx.EVT_BUTTON, self._onNuevaLista)
		self.btnEliminarLista.Bind(wx.EVT_BUTTON, self._onEliminarLista)
		self.btnRenombrarLista.Bind(wx.EVT_BUTTON, self._onRenombrarLista)
		self.listNombres.Bind(wx.EVT_LISTBOX, lambda e: self._mostrarLista())
		for lst in [self.listUltimos, self.listGlobal, self.listFavoritos, self.listHistorial, self.listContenido] + self.listCategoria:
			lst.Bind(wx.EVT_LISTBOX_DCLICK, lambda e, l=lst: self._abrirDesdeLista(l))
		self.Bind(wx.EVT_CHAR_HOOK, self._onTecla)
		self.Bind(wx.EVT_CLOSE, lambda e: self.cerrar())

	# ================================================================ carga
	def _cargarInicio(self) -> None:
		hayReproduccion = self.control.hayReproduccion()
		estabaSonando = self.control.estaSonando()
		if estabaSonando:
			self.control.reproductor.pausar()
			informar("Pausando la reproducción hasta que cargue la interfaz.", 0)
		self._rellenarUltimos()
		for i in range(4):
			self._rellenarCategoria(i)
		self._actualizarHistorial()
		self._actualizarNombresListas()
		if estabaSonando:
			self.control.reproductor.reproducir()
			informar("Reanudando la reproducción.", 0.6)
		self.actualizarEstadoBotones()
		self._focoInicial = self.btnReproducir if hayReproduccion else self.listUltimos

	def enfocarInicio(self) -> None:
		ctrl = getattr(self, "_focoInicial", None) or self.listUltimos
		if ctrl.IsShown():
			ctrl.SetFocus()

	def _rellenar(self, lista: wx.ListBox, textos: list[str], vacio: str | None = None) -> None:
		if not textos and vacio:
			textos = [vacio]
		lista.Set(textos)
		if lista.GetCount():
			lista.SetSelection(0)

	def _rellenarUltimos(self) -> None:
		sel = self.choiceUltimos.GetSelection()
		col = self.colecciones[sel] if 0 <= sel < 4 else None
		self._ultimos = col.ultimos(ajustes.cantidadResultados()) if col else []
		self._rellenar(self.listUltimos, [catalogo.titulo(d) for d in self._ultimos])

	def _rellenarCategoria(self, i: int) -> None:
		col = self.colecciones[i]
		self.resultados[i] = None
		self._rellenar(self.listCategoria[i], col.titulos() if col else [])

	def _datosCategoria(self, i: int, sel: int) -> dict | None:
		if self.resultados[i] is not None:
			res = self.resultados[i]
			return res[sel] if 0 <= sel < len(res) else None
		col = self.colecciones[i]
		return col.get(sel) if col and 0 <= sel < len(col) else None

	# ================================================================ reproductor
	def actualizarEstadoBotones(self) -> None:
		if self._cerrada:
			return
		activo = self.control.hayReproduccion()
		foco = wx.Window.FindFocus()
		for c in self.controlesReproductor:
			c.Show(activo)
		if activo:
			self.btnReproducir.SetLabel("Pausar" if self.control.reproductor.estado() == REPRODUCIENDO else "Reproducir")
		elif foco in self.controlesReproductor:
			# El control con el foco se ha ocultado: el foco va al botón Menú.
			self.btnMenu.SetFocus()
		self.panel.Layout()

	def _reproducirPausar(self) -> None:
		if not self.control.reproductorCreado() or not self.control.reproductor.tieneFlujo():
			hablar("Sin nada en reproducción")
			return
		self.control.reproducirPausar()
		self.actualizarEstadoBotones()

	def _atrasar(self) -> None:
		if self.control.hayReproduccion():
			self.control.atrasar()

	def _adelantar(self) -> None:
		if self.control.hayReproduccion():
			self.control.adelantar()

	def _detener(self) -> None:
		self.control.detener()
		self.actualizarEstadoBotones()

	def _onVolumen(self, evt) -> None:
		self.control.ponerVolumen(self.sliderVolumen.GetValue())

	def _onVelocidad(self, evt) -> None:
		self.control.ponerVelocidad(self.choiceVelocidad.GetSelection())

	def _cambiarVolumen(self, delta: int) -> None:
		nuevo = max(0, min(100, ajustes.get("volumen") + delta))
		self.control.ponerVolumen(nuevo)
		self.sliderVolumen.SetValue(nuevo)
		hablar(f"Volumen {nuevo}%")

	def _cambiarVelocidad(self, delta: int) -> None:
		nuevo = max(0, min(len(ajustes.LISTA_VELOCIDAD) - 1, ajustes.get("velocidad") + delta))
		self.control.ponerVelocidad(nuevo)
		self.choiceVelocidad.SetSelection(nuevo)
		hablar(f"Velocidad {ajustes.LISTA_VELOCIDAD[nuevo]}")

	def _anunciarInfo(self) -> None:
		if not self.control.hayReproduccion():
			hablar("Sin nada en reproducción")
			return
		transcurrido, total = self.control.textoTiempos()
		hablar(f"Tiempo: {transcurrido} / {total}")

	def _alternarHablar(self) -> None:
		nuevo = not ajustes.hablarActivo()
		ajustes.put("hablar", nuevo)
		hablar("Mensajes de información activados" if nuevo else "Mensajes de información desactivados")

	def iniciarReproduccion(self, enlace: str, titulo: str = "", idContenido="", categoria: str = "") -> None:
		"""Carga el contenido en un hilo (conecta con el servidor) y luego lo reproduce."""
		informar("Cargando el contenido…", 0)

		def trabajo():
			resultado = self.control.prepararContenido(enlace, titulo, idContenido, categoria)
			wx.CallAfter(self._trasPreparar, resultado, True)

		threading.Thread(target=trabajo, name="AudiocinematecaCarga", daemon=True).start()

	def reproducirArchivo(self, item) -> None:
		"""Reproduce sin conexión una descarga completada (desde el diálogo Descargas)."""

		def trabajo():
			resultado = self.control.prepararArchivo(item.rutaCompleta, item.url, item.titulo)
			wx.CallAfter(self._trasPreparar, resultado, False, item.titulo)

		threading.Thread(target=trabajo, name="AudiocinematecaCarga", daemon=True).start()

	def _trasPreparar(self, resultado, preguntarPosicion: bool, tituloOffline: str | None = None) -> None:
		ok, posicion, error = resultado
		if not ok:
			hablar("Error al cargar el contenido." if tituloOffline is None else "Error al cargar el archivo.")
			if error:
				dialogos.mensaje(f"No se pudo cargar el contenido.\n\n{error}", "Error", wx.OK | wx.ICON_ERROR, self if not self._cerrada else None)
			if not self._cerrada:
				self.actualizarEstadoBotones()
			return
		desde = None
		if preguntarPosicion and posicion is not None and posicion >= 1:
			texto = f"Hay una posición guardada en {self.control.reproductor.formatoTiempo(posicion)}.\n¿Desea continuar desde ahí?"
			if dialogos.preguntar(texto, self if not self._cerrada else None):
				desde = posicion
		self.control.comenzar(desde)
		if tituloOffline is not None:
			hablar(f"Reproduciendo: {tituloOffline}")
		if self._cerrada:
			return
		# Se muestran aunque el flujo de Internet aún esté llenando el búfer.
		for c in self.controlesReproductor:
			c.Show(True)
		self.btnReproducir.SetLabel("Pausar")
		self.panel.Layout()
		self._actualizarHistorial()
		wx.CallAfter(self._enfocarReproductor)

	def _enfocarReproductor(self) -> None:
		if not self._cerrada and self.btnReproducir.IsShown():
			self.btnReproducir.SetFocus()

	# ================================================================ pestañas
	def _onCambioPestana(self, evt) -> None:
		evt.Skip()
		self._ponerTitulo(evt.GetSelection())

	def _ponerTitulo(self, idx: int) -> None:
		if 0 <= idx < len(NOMBRES_PESTANAS):
			self.SetTitle(f"Audiocinemateca - {NOMBRES_PESTANAS[idx]}")

	def irAPestana(self, idx: int) -> None:
		if not 0 <= idx < self.notebook.GetPageCount():
			return
		self.notebook.ChangeSelection(idx)
		focos = [self.listUltimos] + self.listCategoria + [self.treeFavoritos, self.listHistorial, self.listNombres]
		focos[idx].SetFocus()
		self._ponerTitulo(idx)

	# ================================================================ fichas
	def abrirFicha(self, categoria: str, datos: dict | None) -> None:
		if not datos:
			return
		dlg = dialogos.DialogoFicha(self, self.control, datos, categoria)
		try:
			resultado = dlg.ShowModal()
			enlace, titulo = dlg.enlaceElegido, dlg.tituloElegido
		finally:
			dlg.Destroy()
		if resultado == dialogos.ID_REPRODUCIR:
			self.iniciarReproduccion(enlace, titulo, datos.get("id", ""), categoria)
		elif resultado == dialogos.ID_DESCARGAR:
			self.descargarContenido(enlace, titulo)
		# Los favoritos y las listas pueden haber cambiado.
		self._actualizarFavoritos()
		self._actualizarNombresListas(conservar=True)

	def _abrirDesdeLista(self, lista: wx.ListBox) -> None:
		sel = lista.GetSelection()
		if sel < 0:
			return
		if lista is self.listUltimos:
			if sel < len(self._ultimos):
				self.abrirFicha(ajustes.CLAVES_CATEGORIA[self.choiceUltimos.GetSelection()], self._ultimos[sel])
		elif lista in self.listCategoria:
			i = self.listCategoria.index(lista)
			if lista.GetString(sel) == SIN_RESULTADOS and self.resultados[i] == []:
				return
			self.abrirFicha(ajustes.CLAVES_CATEGORIA[i], self._datosCategoria(i, sel))
		elif lista is self.listGlobal:
			if sel < len(self._globales):
				datos, cat = self._globales[sel]
				self.abrirFicha(cat, datos)
		elif lista is self.listFavoritos:
			if sel < len(self._favoritos):
				self.abrirFicha(self._categoriaFavoritos(), self._favoritos[sel])
		elif lista is self.listHistorial:
			if sel < len(self._historial):
				self._abrirPorId(self._historial[sel])
		elif lista is self.listContenido:
			if sel < len(self._itemsLista):
				self._abrirPorId(self._itemsLista[sel])

	def _abrirPorId(self, entrada: dict) -> None:
		cat = entrada.get("categoria")
		datos = self.control.catalogo.buscarId(cat, entrada.get("id"))
		if datos is None:
			hablar("Este contenido ya no está en el catálogo.")
			return
		self.abrirFicha(cat, datos)

	def _onAleatorio(self, evt) -> None:
		res = self.control.catalogo.aleatorio()
		if res is None:
			return
		cat, datos = res
		self.abrirFicha(cat, datos)

	def descargarContenido(self, enlace: str, titulo: str = "") -> None:
		url = catalogo.urlContenido(enlace)
		carpeta = ajustes.get("carpetaDescargas") or os.path.join(os.path.expanduser("~"), "Downloads")
		with wx.DirDialog(self, "Seleccione un directorio donde guardar:", defaultPath=carpeta if os.path.isdir(carpeta) else "", style=wx.DD_DEFAULT_STYLE) as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			directorio = dlg.GetPath()
		ajustes.put("carpetaDescargas", directorio)
		self.control.descargas.encolar(url, directorio, titulo)
		informar(f"Descarga encolada: {titulo}", 0)

	# ================================================================ búsqueda
	def buscarEnCategoria(self, i: int) -> None:
		texto = self.txtBusqueda[i].GetValue().lower().strip()
		lista = self.listCategoria[i]
		col = self.colecciones[i]
		if not texto:
			if self.resultados[i] is not None:
				informar("Cargando todos los títulos…", 0)
			self._rellenarCategoria(i)
		else:
			campo = ajustes.CAMPOS_FILTRO[self.filtro[i]]
			res = col.buscar(texto, campo) if col else []
			self.resultados[i] = res
			self._rellenar(lista, [catalogo.titulo(d) for d in res], SIN_RESULTADOS)
			self.control.historialBusqueda.registrar(texto, ajustes.LISTA_FILTROS[self.filtro[i]], i, self.filtro[i])
		lista.SetFocus()

	def buscarGlobal(self) -> None:
		texto = self.txtGlobal.GetValue().lower().strip()
		self._globales = []
		if not texto:
			self._rellenar(self.listGlobal, ["Escriba un texto y pulse Intro para buscar."])
			return
		self._globales = self.control.catalogo.buscarGlobal(texto)
		textos = [f"{catalogo.titulo(d)} [{ajustes.nombreCategoria(c)}]" for d, c in self._globales]
		self._rellenar(self.listGlobal, textos, SIN_RESULTADOS)
		self.listGlobal.SetFocus()
		self.control.historialBusqueda.registrar(texto, "Global", -1, 0)

	def ponerFiltro(self, i: int, indice: int) -> None:
		self.filtro[i] = indice
		self.lblBusqueda[i].SetLabel(FORMATOS_BUSQUEDA[i].format(ajustes.LISTA_FILTROS[indice]))

	def _menuFiltro(self, i: int) -> None:
		menu = wx.Menu()
		ids = {}
		for j, nombre in enumerate(ajustes.LISTA_FILTROS):
			item = menu.AppendRadioItem(wx.ID_ANY, nombre)
			item.Check(j == self.filtro[i])
			ids[item.GetId()] = j

		def alElegir(e):
			j = ids.get(e.GetId())
			if j is not None:
				self.ponerFiltro(i, j)
				informar(f"Filtro: {ajustes.LISTA_FILTROS[j]}", 0.2)

		menu.Bind(wx.EVT_MENU, alElegir)
		self.txtBusqueda[i].PopupMenu(menu)
		menu.Destroy()

	def limpiarBusqueda(self, i: int) -> None:
		if self.resultados[i] is not None:
			informar("Limpiando la búsqueda.", 0)
		self.txtBusqueda[i].Clear()
		self.buscarEnCategoria(i)

	def repetirBusqueda(self, entrada: dict) -> None:
		"""Repite una búsqueda del historial de búsqueda."""
		cat = entrada.get("categoria", -1)
		texto = str(entrada.get("texto", ""))
		if cat == -1:
			self.irAPestana(0)
			self.txtGlobal.SetValue(texto)
			self.buscarGlobal()
			return
		if not 0 <= cat < 4:
			return
		indice = entrada.get("indiceFiltro")
		if not isinstance(indice, int) or not 0 <= indice < len(ajustes.LISTA_FILTROS):
			nombre = entrada.get("filtro", "")
			indice = ajustes.LISTA_FILTROS.index(nombre) if nombre in ajustes.LISTA_FILTROS else 0
		self.irAPestana(cat + 1)
		self.ponerFiltro(cat, indice)
		self.txtBusqueda[cat].SetValue(texto)
		self.buscarEnCategoria(cat)

	# ================================================================ favoritos
	def _categoriaFavoritos(self) -> str | None:
		item = self.treeFavoritos.GetSelection()
		return self.treeFavoritos.GetItemData(item) if item and item.IsOk() else None

	def _actualizarFavoritos(self) -> None:
		cat = self._categoriaFavoritos()
		self._favoritos = []
		if not cat:
			self._rellenar(self.listFavoritos, ["Seleccione una categoría"])
			return
		ids = set(map(str, self.control.favoritos.obtener(cat)))
		col = self.control.catalogo.coleccion(cat)
		if col is not None:
			self._favoritos = [d for d in col.elementos if str(d.get("id")) in ids]
		self._rellenar(self.listFavoritos, [catalogo.titulo(d) for d in self._favoritos], "No hay favoritos")

	# ================================================================ historial
	def _actualizarHistorial(self) -> None:
		if self._cerrada:
			return
		sel = self.choiceHistorial.GetSelection()
		h = self.control.historial
		self._historial = h.obtener() if sel <= 0 else h.obtenerPorCategoria(ajustes.CLAVES_CATEGORIA[sel - 1])
		textos = [f"{e.get('titulo', '')} [{ajustes.nombreCategoria(e.get('categoria', ''))}] - {e.get('fecha', '')}" for e in self._historial]
		self._rellenar(self.listHistorial, textos, "No hay historial")

	# ================================================================ listas
	def _nombreListaSeleccionada(self) -> str | None:
		nombres = self.control.listas.nombres()
		sel = self.listNombres.GetSelection()
		return nombres[sel] if 0 <= sel < len(nombres) else None

	def _actualizarNombresListas(self, conservar: bool = False) -> None:
		anterior = self.listNombres.GetSelection() if conservar else 0
		nombres = self.control.listas.nombres()
		textos = [f"{n} ({len(self.control.listas.items(n))})" for n in nombres]
		self._rellenar(self.listNombres, textos, "No hay listas")
		if conservar and 0 <= anterior < self.listNombres.GetCount():
			self.listNombres.SetSelection(anterior)
		self._mostrarLista()

	def _mostrarLista(self) -> None:
		nombre = self._nombreListaSeleccionada()
		self._itemsLista = self.control.listas.items(nombre) if nombre else []
		textos = [f"{i.get('titulo', '')} [{ajustes.nombreCategoria(i.get('categoria', ''))}]" for i in self._itemsLista]
		if nombre is None:
			self.listContenido.Set([])
		else:
			self._rellenar(self.listContenido, textos, "Lista vacía")

	def _onNuevaLista(self, evt) -> None:
		with wx.TextEntryDialog(self, "Nombre de la nueva lista:", "Nueva lista") as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			nombre = dlg.GetValue().strip()
		if not nombre:
			return
		if self.control.listas.crearLista(nombre):
			self._actualizarNombresListas()
			self.listNombres.SetSelection(self.control.listas.nombres().index(nombre))
			self._mostrarLista()
			informar(f"Lista creada: {nombre}", 0.2)
		else:
			hablar("Ya existe una lista con ese nombre.")

	def _onEliminarLista(self, evt) -> None:
		nombre = self._nombreListaSeleccionada()
		if nombre is None:
			return
		if dialogos.preguntar(f"¿Desea eliminar la lista '{nombre}'?", self):
			self.control.listas.eliminarLista(nombre)
			self._actualizarNombresListas()

	def _onRenombrarLista(self, evt) -> None:
		actual = self._nombreListaSeleccionada()
		if actual is None:
			return
		with wx.TextEntryDialog(self, "Nuevo nombre para la lista:", "Renombrar lista", actual) as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			nuevo = dlg.GetValue().strip()
		if nuevo and nuevo != actual:
			if self.control.listas.renombrarLista(actual, nuevo):
				self._actualizarNombresListas(conservar=True)
			else:
				hablar("No se pudo renombrar la lista.")

	def _quitarDeLista(self) -> None:
		nombre = self._nombreListaSeleccionada()
		sel = self.listContenido.GetSelection()
		if nombre is None or not 0 <= sel < len(self._itemsLista):
			return
		item = self._itemsLista[sel]
		self.control.listas.quitarItem(nombre, item.get("id"), item.get("categoria"))
		self._actualizarNombresListas(conservar=True)
		if self.listContenido.GetCount():
			self.listContenido.SetSelection(min(sel, self.listContenido.GetCount() - 1))
		informar(f"Quitado de la lista: {item.get('titulo', '')}", 0.2)

	# ================================================================ menú
	def _onMenu(self, evt) -> None:
		menu = wx.Menu()
		acciones = [
			("&Actualizar base de datos", self._actualizarBaseDatos),
			("Eliminar &marcas de visualización", self._eliminarMarcas),
			("Eliminar &favoritos", self._eliminarFavoritos),
			("Eliminar &historial", self._eliminarHistorial),
			("&Ecualizador", self.abrirEcualizador),
			("&Temporizador de sueño", self._abrirTemporizador),
			("&Descargas", self._abrirDescargas),
			("E&stadísticas", self._abrirEstadisticas),
			("Historial de &búsqueda", self._abrirHistorialBusqueda),
			None,
			("&Opciones", self.complemento.abrirOpciones),
			("&Volver a valores por defecto", lambda: self.complemento.restaurarDefecto(self)),
			("Documentación del com&plemento", self.complemento.abrirDocumentacion),
			None,
			("A&cerca de", self._abrirAcercaDe),
			("Do&nar a la Audiocinemateca", lambda: dialogos.abrirWeb(ajustes.URL_DONACIONES)),
			("Ce&rrar", self.cerrar),
		]
		ids = {}
		for a in acciones:
			if a is None:
				menu.AppendSeparator()
				continue
			item = menu.Append(wx.ID_ANY, a[0])
			ids[item.GetId()] = a[1]

		def alElegir(e):
			accion = ids.get(e.GetId())
			if accion is not None:
				wx.CallAfter(accion)

		menu.Bind(wx.EVT_MENU, alElegir)
		self.btnMenu.PopupMenu(menu)
		menu.Destroy()

	def _actualizarBaseDatos(self) -> None:
		dlg = dialogos.DialogoDescarga(self, dialogos.DialogoDescarga.ACTUALIZAR, versionLocal=self.control.catalogo.cargarVersion())
		try:
			resultado = dlg.ShowModal()
		finally:
			dlg.Destroy()
		if resultado == dialogos.ID_ACTUALIZADO:
			self.cerrar(recargar=True)

	def _eliminarMarcas(self) -> None:
		if dialogos.preguntar("Se eliminarán todas las marcas de visualización.\n¿Desea continuar?", self):
			self.control.visualizacion.vaciar()

	def _eliminarFavoritos(self) -> None:
		if dialogos.preguntar("Se eliminarán todos los favoritos.\n¿Desea continuar?", self):
			self.control.favoritos.vaciar()
			self._actualizarFavoritos()

	def _eliminarHistorial(self) -> None:
		if dialogos.preguntar("Se eliminarán el historial de reproducción y el de búsqueda.\n¿Desea continuar?", self):
			self.control.historial.vaciar()
			self.control.historialBusqueda.vaciar()
			self._actualizarHistorial()

	def abrirEcualizador(self) -> None:
		dlg = dialogos.DialogoEcualizador(self)
		try:
			dlg.ShowModal()
		finally:
			dlg.Destroy()
		self.control.aplicarEcualizadorActual()

	def _abrirTemporizador(self) -> None:
		dlg = dialogos.DialogoTemporizador(self)
		try:
			if dlg.ShowModal() != wx.ID_OK:
				return
			minutos = dlg.obtenerMinutos()
		finally:
			dlg.Destroy()
		if minutos > 0:
			self.control.iniciarTemporizador(minutos)
		else:
			self.control.cancelarTemporizador()
			informar("Temporizador de sueño desactivado", 0.2)

	def _abrirDescargas(self) -> None:
		dlg = dialogos.DialogoDescargas(self, self.control, alReproducir=self._reproducirDesdeDescargas)
		try:
			dlg.ShowModal()
		finally:
			dlg.Destroy()

	def _reproducirDesdeDescargas(self, item) -> None:
		self.reproducirArchivo(item)

	def _abrirEstadisticas(self) -> None:
		dlg = dialogos.DialogoEstadisticas(self, self.control)
		try:
			dlg.ShowModal()
		finally:
			dlg.Destroy()

	def _abrirHistorialBusqueda(self) -> None:
		dlg = dialogos.DialogoHistorialBusqueda(self, self.control)
		try:
			ok = dlg.ShowModal() == wx.ID_OK
			elegida = dlg.elegida
		finally:
			dlg.Destroy()
		if ok and elegida:
			self.repetirBusqueda(elegida)

	def _abrirAcercaDe(self) -> None:
		dlg = dialogos.DialogoAcercaDe(self, self.control.catalogo.version or self.control.catalogo.cargarVersion())
		try:
			dlg.ShowModal()
		finally:
			dlg.Destroy()

	def aplicarOpciones(self) -> None:
		"""Refleja en la ventana las opciones cambiadas desde fuera (Opciones, valores por defecto)."""
		if self._cerrada:
			return
		self.sliderVolumen.SetValue(ajustes.get("volumen"))
		self.choiceVelocidad.SetSelection(ajustes.get("velocidad"))
		self._rellenarUltimos()

	# ================================================================ teclado
	def _onTecla(self, evt: wx.KeyEvent) -> None:
		codigo = evt.GetKeyCode()
		foco = wx.Window.FindFocus()
		mods = evt.GetModifiers()
		listasContenido = [self.listUltimos] + self.listCategoria
		if codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and mods == wx.MOD_NONE:
			if foco in listasContenido or foco in (self.listFavoritos, self.listHistorial, self.listContenido, self.listGlobal):
				wx.CallAfter(self._abrirDesdeLista, foco)
				return
			if foco in self.txtBusqueda:
				wx.CallAfter(self.buscarEnCategoria, self.txtBusqueda.index(foco))
				return
			if foco is self.txtGlobal:
				wx.CallAfter(self.buscarGlobal)
				return
		if codigo == wx.WXK_ESCAPE and mods == wx.MOD_NONE:
			self.cerrar()
			return
		if (codigo == wx.WXK_WINDOWS_MENU and mods == wx.MOD_NONE) or (codigo == wx.WXK_F10 and mods == wx.MOD_SHIFT):
			if foco in self.txtBusqueda:
				wx.CallAfter(self._menuFiltro, self.txtBusqueda.index(foco))
				return
		if codigo == wx.WXK_BACK and mods == wx.MOD_NONE and foco in self.listCategoria:
			self.limpiarBusqueda(self.listCategoria.index(foco))
			return
		if codigo == wx.WXK_DELETE and mods == wx.MOD_NONE and foco is self.listContenido:
			wx.CallAfter(self._quitarDeLista)
			return
		if mods == wx.MOD_ALT and ord("1") <= codigo <= ord("8"):
			self.irAPestana(codigo - ord("1"))
			return
		teclas = {
			wx.WXK_F1: self._atrasar,
			wx.WXK_F2: self._reproducirPausar,
			wx.WXK_F3: self._adelantar,
			wx.WXK_F4: self._detener,
			wx.WXK_F5: lambda: self._cambiarVolumen(-1),
			wx.WXK_F6: lambda: self._cambiarVolumen(1),
			wx.WXK_F7: lambda: self._cambiarVelocidad(-1),
			wx.WXK_F8: lambda: self._cambiarVelocidad(1),
			wx.WXK_F9: self._anunciarInfo,
			wx.WXK_F10: self.abrirEcualizador,
			wx.WXK_F11: lambda: hablar(self.control.infoTemporizador()),
			wx.WXK_F12: self._alternarHablar,
		}
		if codigo in teclas and mods == wx.MOD_NONE:
			if codigo == wx.WXK_F10:
				wx.CallAfter(teclas[codigo])
			else:
				teclas[codigo]()
			return
		if mods == wx.MOD_CONTROL and codigo == ord("I") and foco in listasContenido:
			sel = foco.GetSelection()
			if sel >= 0:
				hablar(f"Resultado {sel + 1} de {foco.GetCount()}")
			return
		if mods == wx.MOD_CONTROL and codigo == ord("F") and foco in listasContenido:
			wx.CallAfter(self._irAPosicion, foco)
			return
		if mods == wx.MOD_CONTROL and codigo == ord("C") and foco in self.listCategoria:
			wx.CallAfter(self._copiarInfo, self.listCategoria.index(foco))
			return
		evt.Skip()

	def _irAPosicion(self, lista: wx.ListBox) -> None:
		total = lista.GetCount()
		if total <= 0:
			return
		dlg = dialogos.DialogoPosicion(self, total)
		try:
			if dlg.ShowModal() == wx.ID_OK:
				lista.SetSelection(dlg.numero - 1)
				lista.SetFocus()
				hablar(lista.GetString(dlg.numero - 1))
		finally:
			dlg.Destroy()

	def _copiarInfo(self, i: int) -> None:
		datos = self._datosCategoria(i, self.listCategoria[i].GetSelection())
		if datos is None:
			return
		if dialogos.copiarAlPortapapeles(catalogo.textoCopiar(datos, ajustes.CLAVES_CATEGORIA[i])):
			hablar("Información copiada al portapapeles")
		else:
			hablar("No se pudo acceder al portapapeles")

	# ================================================================ cierre
	def cerrar(self, recargar: bool = False) -> None:
		if self._cerrada:
			return
		self._cerrada = True
		ajustes.estado.ventanaAbierta = False
		self.control.catalogo.limpiar()
		self.complemento.ventanaCerrada(self, recargar)
		self.Destroy()
