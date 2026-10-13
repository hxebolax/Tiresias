"""Diálogos del Traductor Avanzado Pro.

- :class:`DialogoHistorial`: historial con búsqueda, filtros, exportación y estadísticas.
- :class:`DialogoIdiomas`: elegir el idioma de origen o de destino.
- :class:`DialogoGestionAPI`: claves de API de un servicio (varias, con rotación).
- :class:`DialogoConfiguracionIA`: modelo y prompts de OpenAI, Gemini, DeepSeek y Claude.
- :class:`DialogoTraduccion`: interfaz de traducción manual (con «Escuchar» y «Pegar al foco»).
- :class:`DialogoSeleccionRapida`: cambio rápido de servicio, modelo e idiomas.

La configuración general está en la categoría «Traductor Avanzado Pro» de las
Opciones de Tiresias (``panel_opciones``). Todo se crea en el hilo de la
interfaz; las ventanas principales no son modales y se traen al frente como
las de Tiresias.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

import wx

from tiresias.gui.helpers import bringToFront, isAlive, normalizeForSearch
from tiresias.log import getLogger

from ..nucleo.configuracion import ConfiguracionServicio
from ..servicios.ayuda import GestorAyuda
from ..traductores._comun import PROMPTS_DEFECTO
from ..utilidades import lector, seguridad
from ..utilidades.modelos_ia import SERVICIOS_IA, ListadorModelosIA
from .progreso import DialogoProgreso

log = getLogger("TraductorAvanzadoPro")

#: Ventanas abiertas (una de cada tipo).
_abiertos: dict[str, wx.Window] = {}


def _mensaje(texto: str, titulo: str = "Información", estilo: int = wx.OK | wx.ICON_INFORMATION, padre: wx.Window | None = None) -> int | None:
	from tiresias import gui

	return gui.messageBox(texto, titulo, estilo, padre)


def _preguntar(texto: str, titulo: str, padre: wx.Window | None = None) -> bool:
	return _mensaje(texto, titulo, wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, padre) == wx.YES


def _etiqueta(padre: wx.Window, sizer: wx.Sizer, texto: str) -> wx.StaticText:
	"""Etiqueta justo antes del control que nombra (orden de tabulación correcto)."""
	st = wx.StaticText(padre, label=texto)
	sizer.Add(st, 0, wx.LEFT | wx.RIGHT | wx.TOP, 6)
	return st


def _seleccionar_codigo(ctrl: wx.Choice, codigo: str | None) -> None:
	for i in range(ctrl.GetCount()):
		if ctrl.GetClientData(i) == codigo:
			ctrl.SetSelection(i)
			return
	if ctrl.GetCount() and ctrl.GetSelection() == wx.NOT_FOUND:
		ctrl.SetSelection(0)


def _codigo(ctrl: wx.Choice) -> Any:
	i = ctrl.GetSelection()
	return ctrl.GetClientData(i) if i != wx.NOT_FOUND else None


def mostrar_unico(clave: str, crear: Callable[[], wx.Window], foco: Callable[[wx.Window], None] | None = None) -> wx.Window:
	"""Muestra la ventana ``clave`` (la crea si no está abierta) y la trae al frente."""
	dlg = _abiertos.get(clave)
	if not isAlive(dlg):
		dlg = crear()
		_abiertos[clave] = dlg
		hwnd = dlg.GetHandle()

		def al_destruir(evento: wx.WindowDestroyEvent, c: str = clave) -> None:
			evento.Skip()
			obj = evento.GetEventObject()
			try:
				propio = obj is not None and obj.GetHandle() == hwnd
			except Exception:
				propio = False
			if propio:
				_abiertos.pop(c, None)

		dlg.Bind(wx.EVT_WINDOW_DESTROY, al_destruir)
	dlg.Show()
	bringToFront(dlg)
	if foco:
		foco(dlg)
	return dlg


def cerrar_todos() -> None:
	"""Cierra las ventanas del complemento (al descargarlo)."""
	for dlg in list(_abiertos.values()):
		if isAlive(dlg):
			try:
				dlg.Destroy()
			except RuntimeError:
				pass
	_abiertos.clear()


# ====================================================================== historial
class DialogoHistorial(wx.Dialog):
	def __init__(self, plugin: Any) -> None:
		super().__init__(None, title="Historial de traducciones", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
		self.plugin = plugin
		self.historial = plugin.historial
		self.visibles: list[Any] = []
		sizer = wx.BoxSizer(wx.VERTICAL)
		_etiqueta(self, sizer, "&Buscar:")
		self.txt_buscar = wx.TextCtrl(self)
		sizer.Add(self.txt_buscar, 0, wx.EXPAND | wx.ALL, 6)
		filtros = wx.BoxSizer(wx.HORIZONTAL)
		filtros.Add(wx.StaticText(self, label="&Idioma de destino:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
		self.ch_idioma = wx.Choice(self)
		filtros.Add(self.ch_idioma, 0, wx.ALL, 4)
		filtros.Add(wx.StaticText(self, label="Ser&vicio:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
		self.ch_servicio = wx.Choice(self)
		filtros.Add(self.ch_servicio, 0, wx.ALL, 4)
		sizer.Add(filtros, 0, wx.LEFT | wx.RIGHT, 2)
		_etiqueta(self, sizer, "Tra&ducciones (la más reciente primero):")
		self.lista = wx.ListCtrl(self, size=(720, 260), style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
		for i, (titulo, ancho) in enumerate((("Original", 240), ("Traducción", 240), ("Idiomas", 80), ("Servicio", 120), ("Fecha", 140))):
			self.lista.InsertColumn(i, titulo, width=ancho)
		sizer.Add(self.lista, 1, wx.EXPAND | wx.ALL, 6)
		_etiqueta(self, sizer, "Texto co&mpleto:")
		self.txt_completo = wx.TextCtrl(self, size=(720, 110), style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
		sizer.Add(self.txt_completo, 0, wx.EXPAND | wx.ALL, 6)
		botones = wx.BoxSizer(wx.HORIZONTAL)
		self.btn_copiar_original = wx.Button(self, label="Copiar &original")
		self.btn_copiar_traduccion = wx.Button(self, label="Copiar &traducción")
		self.btn_eliminar = wx.Button(self, label="&Eliminar")
		self.btn_exportar = wx.Button(self, label="E&xportar...")
		self.btn_estadisticas = wx.Button(self, label="E&stadísticas")
		self.btn_limpiar = wx.Button(self, label="&Limpiar todo")
		self.btn_cerrar = wx.Button(self, wx.ID_CLOSE, "&Cerrar")
		for b in (self.btn_copiar_original, self.btn_copiar_traduccion, self.btn_eliminar, self.btn_exportar, self.btn_estadisticas, self.btn_limpiar, self.btn_cerrar):
			botones.Add(b, 0, wx.ALL, 3)
		sizer.Add(botones, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CLOSE)
		self.txt_buscar.Bind(wx.EVT_TEXT, lambda e: self.refiltrar())
		self.ch_idioma.Bind(wx.EVT_CHOICE, lambda e: self.refiltrar())
		self.ch_servicio.Bind(wx.EVT_CHOICE, lambda e: self.refiltrar())
		self.lista.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda e: self._mostrar_seleccion())
		self.lista.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self._copiar(False))
		self.btn_copiar_original.Bind(wx.EVT_BUTTON, lambda e: self._copiar(True))
		self.btn_copiar_traduccion.Bind(wx.EVT_BUTTON, lambda e: self._copiar(False))
		self.btn_eliminar.Bind(wx.EVT_BUTTON, self._on_eliminar)
		self.btn_exportar.Bind(wx.EVT_BUTTON, self._on_exportar)
		self.btn_estadisticas.Bind(wx.EVT_BUTTON, self._on_estadisticas)
		self.btn_limpiar.Bind(wx.EVT_BUTTON, self._on_limpiar)
		self.btn_cerrar.Bind(wx.EVT_BUTTON, lambda e: self.Close())
		self.Bind(wx.EVT_CLOSE, lambda e: self.Destroy())
		self.CentreOnScreen()
		self.recargar()

	def _nombre_servicio(self, sid: str) -> str:
		t = self.plugin.gestor_traductores.obtener_traductor(sid) if self.plugin.gestor_traductores else None
		return t.nombre if t else sid

	def recargar(self) -> None:
		entradas = self.historial.listar_todos() if self.historial else []
		idiomas = sorted({e.idioma_destino for e in entradas if e.idioma_destino})
		servicios = sorted({e.servicio for e in entradas if e.servicio})
		for ctrl, valores, nombre in ((self.ch_idioma, idiomas, self.plugin.gestor_idiomas.obtener_nombre_idioma), (self.ch_servicio, servicios, self._nombre_servicio)):
			actual = _codigo(ctrl)
			ctrl.Clear()
			ctrl.Append("Todos", None)
			for v in valores:
				ctrl.Append(nombre(v), v)
			_seleccionar_codigo(ctrl, actual)
		self.refiltrar()

	def refiltrar(self) -> None:
		plugin_hist = self.plugin.gestor_plugins.obtener_plugin("historial_inteligente") if self.plugin.gestor_plugins else None
		filtros = {}
		if _codigo(self.ch_idioma):
			filtros["idioma"] = _codigo(self.ch_idioma)
		if _codigo(self.ch_servicio):
			filtros["servicio"] = _codigo(self.ch_servicio)
		consulta = self.txt_buscar.GetValue().strip()
		if plugin_hist:
			entradas = plugin_hist.buscar_avanzado("", filtros)
		else:
			entradas = [e for e in self.historial.listar_todos() if (not filtros.get("idioma") or e.idioma_destino == filtros["idioma"]) and (not filtros.get("servicio") or e.servicio == filtros["servicio"])]
		if consulta:
			palabras = normalizeForSearch(consulta).split()
			entradas = [e for e in entradas if all(p in normalizeForSearch(e.texto_original + " " + e.texto_traducido) for p in palabras)]
		self.visibles = entradas
		self.lista.DeleteAllItems()
		for i, e in enumerate(entradas):
			idx = self.lista.InsertItem(i, " ".join(e.texto_original.split())[:150])
			self.lista.SetItem(idx, 1, " ".join(e.texto_traducido.split())[:150])
			self.lista.SetItem(idx, 2, f"{e.idioma_origen} → {e.idioma_destino}")
			self.lista.SetItem(idx, 3, self._nombre_servicio(e.servicio))
			self.lista.SetItem(idx, 4, e.fecha.replace("T", " ")[:19])
		if entradas:
			self.lista.Select(0)
			self.lista.Focus(0)
		self._mostrar_seleccion()

	def _seleccionada(self) -> Any:
		i = self.lista.GetFirstSelected()
		return self.visibles[i] if 0 <= i < len(self.visibles) else None

	def _mostrar_seleccion(self) -> None:
		e = self._seleccionada()
		self.txt_completo.SetValue(f"Original:\n{e.texto_original}\n\nTraducción:\n{e.texto_traducido}" if e else "")
		for b in (self.btn_copiar_original, self.btn_copiar_traduccion, self.btn_eliminar):
			b.Enable(e is not None)

	def _copiar(self, original: bool) -> None:
		e = self._seleccionada()
		if e is None:
			wx.Bell()
			return
		if self.plugin.monitor_portapapeles.establecer_texto(e.texto_original if original else e.texto_traducido):
			lector.mensaje("Original copiado" if original else "Traducción copiada")

	def _on_eliminar(self, event: wx.CommandEvent) -> None:
		e = self._seleccionada()
		if e is None:
			return
		i = self.lista.GetFirstSelected()
		self.historial.eliminar(e)
		self.recargar()
		if self.visibles:
			i = min(i, len(self.visibles) - 1)
			self.lista.Select(i)
			self.lista.Focus(i)
		self.lista.SetFocus()

	def _on_exportar(self, event: wx.CommandEvent) -> None:
		plugin_hist = self.plugin.gestor_plugins.obtener_plugin("historial_inteligente") if self.plugin.gestor_plugins else None
		if plugin_hist is None:
			_mensaje("El plugin «Historial Inteligente» está desactivado.", "Exportar", padre=self)
			return
		if not self.visibles:
			wx.Bell()
			return
		from ..plugins.historial_inteligente import carpeta_documentos

		with wx.FileDialog(
			self,
			"Exportar el historial",
			defaultDir=carpeta_documentos(),
			defaultFile="traducciones",
			wildcard="Hoja de cálculo CSV (*.csv)|*.csv|Datos JSON (*.json)|*.json",
			style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
		) as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			ruta, indice = dlg.GetPath(), dlg.GetFilterIndex()
		es_json = ruta.lower().endswith(".json") or (indice == 1 and not ruta.lower().endswith(".csv"))
		if es_json and not ruta.lower().endswith(".json"):
			ruta += ".json"
		elif not es_json and not ruta.lower().endswith(".csv"):
			ruta += ".csv"
		hecho = plugin_hist.exportar_json(ruta, self.visibles) if es_json else plugin_hist.exportar_csv(ruta, self.visibles)
		if hecho:
			_mensaje(f"Se han exportado {len(self.visibles)} traducciones a:\n{hecho}", "Historial exportado", padre=self)
		else:
			_mensaje("No se pudo exportar el historial.", "Error", wx.OK | wx.ICON_ERROR, self)

	def _on_estadisticas(self, event: wx.CommandEvent) -> None:
		plugin_hist = self.plugin.gestor_plugins.obtener_plugin("historial_inteligente") if self.plugin.gestor_plugins else None
		if plugin_hist is None:
			_mensaje("El plugin «Historial Inteligente» está desactivado.", "Estadísticas", padre=self)
			return
		texto = plugin_hist.obtener_resumen_texto(self.plugin.gestor_idiomas.obtener_nombre_idioma, self._nombre_servicio)
		cache = self.plugin.cache.obtener_estadisticas() if self.plugin.cache else None
		if cache:
			texto += f"\n\n=== Caché ===\n\nTraducciones guardadas: {cache['total_entradas']}\nContextos (aplicación e idioma): {cache['total_contextos']}"
		lector.mensaje_navegable("Estadísticas del historial", texto)

	def _on_limpiar(self, event: wx.CommandEvent) -> None:
		if _preguntar("¿Está seguro de que desea limpiar todo el historial?", "Confirmar", self):
			self.historial.limpiar()
			self.recargar()
			self.txt_buscar.SetFocus()


# ====================================================================== idiomas
class DialogoIdiomas(wx.Dialog):
	"""Elegir el idioma de destino o de origen de la traducción."""

	def __init__(self, plugin: Any, tipo: str = "destino") -> None:
		titulo = "Seleccionar idioma de destino" if tipo == "destino" else "Seleccionar idioma de origen"
		super().__init__(None, title=titulo, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.plugin = plugin
		self.tipo = tipo
		self.idioma_seleccionado: str | None = None
		sizer = wx.BoxSizer(wx.VERTICAL)
		_etiqueta(self, sizer, "&Buscar:")
		self.txt_busqueda = wx.TextCtrl(self)
		sizer.Add(self.txt_busqueda, 0, wx.EXPAND | wx.ALL, 6)
		_etiqueta(self, sizer, "&Idiomas:")
		self.lista_idiomas = wx.ListBox(self, size=(360, 300), style=wx.LB_SINGLE)
		sizer.Add(self.lista_idiomas, 1, wx.EXPAND | wx.ALL, 6)
		botones = self.CreateButtonSizer(wx.OK | wx.CANCEL)
		sizer.Add(botones, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
		self.SetSizerAndFit(sizer)
		self.txt_busqueda.Bind(wx.EVT_TEXT, lambda e: self._cargar_idiomas(self.txt_busqueda.GetValue()))
		self.txt_busqueda.Bind(wx.EVT_KEY_DOWN, self._on_tecla_busqueda)
		self.lista_idiomas.Bind(wx.EVT_LISTBOX_DCLICK, self._on_aceptar)
		self.Bind(wx.EVT_BUTTON, self._on_aceptar, id=wx.ID_OK)
		self.Bind(wx.EVT_BUTTON, lambda e: self.Close(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, lambda e: self.Destroy())
		self._cargar_idiomas()
		self.CentreOnScreen()

	def _actual(self) -> str:
		c = self.plugin.configuracion
		return c.idioma_destino if self.tipo == "destino" else c.idioma_origen

	def _cargar_idiomas(self, filtro: str = "") -> None:
		self.lista_idiomas.Clear()
		consulta = normalizeForSearch(filtro)
		for codigo, nombre in self.plugin.gestor_idiomas.obtener_lista_idiomas(incluir_auto=self.tipo == "origen"):
			if consulta and consulta not in normalizeForSearch(nombre) and consulta != codigo.lower():
				continue
			self.lista_idiomas.Append(nombre, codigo)
		if self.lista_idiomas.GetCount():
			sel = 0
			for i in range(self.lista_idiomas.GetCount()):
				if self.lista_idiomas.GetClientData(i) == self._actual():
					sel = i
					break
			self.lista_idiomas.SetSelection(sel)

	def _on_tecla_busqueda(self, event: wx.KeyEvent) -> None:
		if event.GetKeyCode() in (wx.WXK_DOWN, wx.WXK_UP) and self.lista_idiomas.GetCount():
			self.lista_idiomas.SetFocus()
			return
		event.Skip()

	def _on_aceptar(self, event: Any) -> None:
		i = self.lista_idiomas.GetSelection()
		if i == wx.NOT_FOUND:
			wx.Bell()
			return
		codigo = self.lista_idiomas.GetClientData(i)
		self.idioma_seleccionado = codigo
		if self.tipo == "destino":
			self.plugin.configuracion.idioma_destino = codigo
		else:
			self.plugin.configuracion.idioma_origen = codigo
		lector.mensaje(f"Idioma de {self.tipo}: {self.lista_idiomas.GetString(i)}")
		self.Close()


# ====================================================================== claves de API
class DialogoGestionAPI(wx.Dialog):
	"""Varias claves por servicio, en orden de uso, con rotación automática."""

	#: Servicios en los que se puede indicar la dirección del servidor.
	CON_URL = {"libretranslate": "&URL del servidor (vacío: servidores públicos):", "openai": "&URL de una API compatible (vacío: OpenAI):"}

	def __init__(self, parent: wx.Window | None, configuracion: Any, servicio_id: str, nombre: str | None = None, traductor: Any = None) -> None:
		super().__init__(parent, title=f"Gestionar claves para {nombre or servicio_id}", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.configuracion = configuracion
		self.servicio_id = servicio_id
		self.traductor = traductor
		self.servicio_config = configuracion.obtener_api(servicio_id) or ConfiguracionServicio()
		self.claves: list[str] = self.servicio_config.claves_planas()
		sizer = wx.BoxSizer(wx.VERTICAL)
		_etiqueta(self, sizer, "C&laves configuradas (se usan en este orden):")
		self.lista_claves = wx.ListBox(self, size=(420, 140), style=wx.LB_SINGLE)
		sizer.Add(self.lista_claves, 1, wx.EXPAND | wx.ALL, 6)
		fila = wx.BoxSizer(wx.HORIZONTAL)
		self.btn_subir = wx.Button(self, label="&Subir")
		self.btn_bajar = wx.Button(self, label="&Bajar")
		self.btn_eliminar = wx.Button(self, label="&Eliminar")
		for b in (self.btn_subir, self.btn_bajar, self.btn_eliminar):
			fila.Add(b, 0, wx.ALL, 3)
		sizer.Add(fila, 0, wx.ALIGN_CENTER)
		_etiqueta(self, sizer, "&Nueva clave:")
		fila2 = wx.BoxSizer(wx.HORIZONTAL)
		self.txt_nueva_clave = wx.TextCtrl(self, style=wx.TE_PASSWORD | wx.TE_PROCESS_ENTER)
		self.btn_anadir = wx.Button(self, label="&Añadir")
		fila2.Add(self.txt_nueva_clave, 1, wx.EXPAND | wx.ALL, 3)
		fila2.Add(self.btn_anadir, 0, wx.ALL, 3)
		sizer.Add(fila2, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 3)
		self.chk_rotacion = wx.CheckBox(self, label="Habilitar &rotación automática de claves (usar la siguiente si una falla)")
		self.chk_rotacion.SetValue(self.servicio_config.usar_rotacion)
		sizer.Add(self.chk_rotacion, 0, wx.ALL, 8)
		self.txt_url = None
		if servicio_id in self.CON_URL:
			_etiqueta(self, sizer, self.CON_URL[servicio_id])
			self.txt_url = wx.TextCtrl(self, value=self.servicio_config.api_url or "")
			sizer.Add(self.txt_url, 0, wx.EXPAND | wx.ALL, 6)
		self.btn_uso = None
		if servicio_id == "deepl_api":
			self.btn_uso = wx.Button(self, label="Consultar el &uso de la clave actual")
			sizer.Add(self.btn_uso, 0, wx.ALL, 6)
			self.btn_uso.Bind(wx.EVT_BUTTON, self._on_uso)
		finales = wx.StdDialogButtonSizer()
		self.btn_ok = wx.Button(self, wx.ID_OK, "&Guardar")
		self.btn_cancel = wx.Button(self, wx.ID_CANCEL, "&Cancelar")
		finales.AddButton(self.btn_ok)
		finales.AddButton(self.btn_cancel)
		finales.Realize()
		sizer.Add(finales, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
		self.SetSizerAndFit(sizer)
		self.btn_anadir.Bind(wx.EVT_BUTTON, self._on_anadir)
		self.txt_nueva_clave.Bind(wx.EVT_TEXT_ENTER, self._on_anadir)
		self.btn_eliminar.Bind(wx.EVT_BUTTON, self._on_eliminar)
		self.btn_subir.Bind(wx.EVT_BUTTON, lambda e: self._mover(-1))
		self.btn_bajar.Bind(wx.EVT_BUTTON, lambda e: self._mover(1))
		self.btn_ok.Bind(wx.EVT_BUTTON, self._on_guardar)
		self._refrescar()
		self.CentreOnParent()

	def _refrescar(self, seleccion: int | None = None) -> None:
		self.lista_claves.Set([f"{i + 1}. {seguridad.censurar(c)}" for i, c in enumerate(self.claves)])
		if self.claves:
			self.lista_claves.SetSelection(max(0, min(seleccion if seleccion is not None else 0, len(self.claves) - 1)))
		for b in (self.btn_subir, self.btn_bajar, self.btn_eliminar):
			b.Enable(bool(self.claves))

	def _on_anadir(self, event: Any) -> None:
		nueva = self.txt_nueva_clave.GetValue().strip()
		if not nueva:
			wx.Bell()
			return
		if nueva in self.claves:
			_mensaje("Esta clave ya ha sido añadida.", "Error", wx.OK | wx.ICON_ERROR, self)
			return
		self.claves.append(nueva)
		self.txt_nueva_clave.Clear()
		self._refrescar(len(self.claves) - 1)
		lector.mensaje("Clave añadida")

	def _on_eliminar(self, event: Any) -> None:
		i = self.lista_claves.GetSelection()
		if i == wx.NOT_FOUND:
			return
		del self.claves[i]
		self._refrescar(i)
		lector.mensaje("Clave eliminada")
		(self.lista_claves if self.claves else self.txt_nueva_clave).SetFocus()

	def _mover(self, paso: int) -> None:
		i = self.lista_claves.GetSelection()
		j = i + paso
		if i == wx.NOT_FOUND or not 0 <= j < len(self.claves):
			wx.Bell()
			return
		self.claves[i], self.claves[j] = self.claves[j], self.claves[i]
		self._refrescar(j)

	def _on_uso(self, event: Any) -> None:
		if self.traductor is None or not hasattr(self.traductor, "obtener_uso"):
			return
		self.btn_uso.Disable()

		def consultar() -> None:
			uso = self.traductor.obtener_uso()

			def mostrar() -> None:
				if isAlive(self.btn_uso):
					self.btn_uso.Enable()
				if uso and "character_limit" in uso:
					usados, limite = int(uso.get("character_count", 0)), int(uso.get("character_limit", 0) or 0)
					resto = max(0, limite - usados)
					_mensaje(f"Caracteres usados: {usados:,}\nLímite: {limite:,}\nQuedan: {resto:,}".replace(",", "."), "Uso de DeepL", padre=self)
				else:
					_mensaje(f"No se pudo consultar el uso. {getattr(self.traductor, 'ultimo_error', '') or 'Guarde antes la clave.'}", "Uso de DeepL", wx.OK | wx.ICON_ERROR, self)

			wx.CallAfter(mostrar)

		threading.Thread(target=consultar, daemon=True).start()

	def _on_guardar(self, event: Any) -> None:
		pendiente = self.txt_nueva_clave.GetValue().strip()
		if pendiente and pendiente not in self.claves:
			# Se escribió una clave y se pulsó Guardar sin «Añadir»: se añade.
			self.claves.append(pendiente)
		codificadas = [seguridad.codificar_api_key(c) for c in self.claves]
		self.configuracion.establecer_api(
			self.servicio_id,
			claves=codificadas,
			usar_rotacion=self.chk_rotacion.GetValue(),
			api_url=self.txt_url.GetValue() if self.txt_url is not None else None,
		)
		self.configuracion.guardar()
		self.EndModal(wx.ID_OK)


# ====================================================================== modelo y prompts de IA
class DialogoConfiguracionIA(wx.Dialog):
	PROMPTS_DEFECTO = PROMPTS_DEFECTO

	def __init__(self, parent: wx.Window | None, configuracion: Any, servicio_id: str, nombre: str | None = None, modelo_defecto: str = "") -> None:
		super().__init__(parent, title=f"Configuración de IA: {nombre or servicio_id}", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.configuracion = configuracion
		self.servicio_id = servicio_id
		self.servicio_config = configuracion.obtener_api(servicio_id) or ConfiguracionServicio()
		self.listador = ListadorModelosIA(configuracion.ruta_modelos)
		self.modelo_defecto = modelo_defecto
		sizer = wx.BoxSizer(wx.VERTICAL)
		_etiqueta(self, sizer, f"&Modelo (vacío: {modelo_defecto or 'el predeterminado'}):")
		fila = wx.BoxSizer(wx.HORIZONTAL)
		self.combo_modelo = wx.ComboBox(self, style=wx.CB_DROPDOWN)
		self.btn_actualizar_modelos = wx.Button(self, label="&Actualizar lista")
		fila.Add(self.combo_modelo, 1, wx.EXPAND | wx.ALL, 3)
		fila.Add(self.btn_actualizar_modelos, 0, wx.ALL, 3)
		sizer.Add(fila, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 3)
		self.lbl_estado = wx.StaticText(self, label="")
		sizer.Add(self.lbl_estado, 0, wx.ALL, 6)
		_etiqueta(self, sizer, "Prompt de &sistema:")
		self.txt_sistema = wx.TextCtrl(self, size=(520, 90), style=wx.TE_MULTILINE)
		sizer.Add(self.txt_sistema, 1, wx.EXPAND | wx.ALL, 6)
		_etiqueta(self, sizer, "Prompt de &usuario (use {idioma_destino} y {texto} como marcadores):")
		self.txt_usuario = wx.TextCtrl(self, size=(520, 110), style=wx.TE_MULTILINE)
		sizer.Add(self.txt_usuario, 1, wx.EXPAND | wx.ALL, 6)
		self.btn_restablecer = wx.Button(self, label="&Restablecer los prompts predeterminados")
		sizer.Add(self.btn_restablecer, 0, wx.ALL, 6)
		finales = wx.StdDialogButtonSizer()
		self.btn_ok = wx.Button(self, wx.ID_OK, "&Guardar")
		self.btn_cancel = wx.Button(self, wx.ID_CANCEL, "&Cancelar")
		finales.AddButton(self.btn_ok)
		finales.AddButton(self.btn_cancel)
		finales.Realize()
		sizer.Add(finales, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
		self.SetSizerAndFit(sizer)
		self.btn_actualizar_modelos.Bind(wx.EVT_BUTTON, self._on_actualizar_modelos)
		self.btn_restablecer.Bind(wx.EVT_BUTTON, self._on_restablecer)
		self.btn_ok.Bind(wx.EVT_BUTTON, self._on_guardar)
		self._cargar_datos()
		self.CentreOnParent()

	def _cargar_datos(self) -> None:
		if self.servicio_config.modelo:
			self.combo_modelo.SetValue(self.servicio_config.modelo)
		self.txt_sistema.SetValue(self.servicio_config.prompt_sistema or PROMPTS_DEFECTO["sistema"])
		self.txt_usuario.SetValue(self.servicio_config.prompt_usuario or PROMPTS_DEFECTO["usuario"])
		self._obtener_modelos_en_hilo()

	def _obtener_modelos_en_hilo(self) -> None:
		api_key = self.servicio_config.api_key
		if not api_key:
			self.lbl_estado.SetLabel("Sin clave de API: no se puede descargar la lista de modelos.")
			return
		self.lbl_estado.SetLabel("Obteniendo la lista de modelos...")
		self.btn_actualizar_modelos.Disable()

		def obtener() -> None:
			modelos = self.listador.obtener_modelos(self.servicio_id, api_key)
			wx.CallAfter(self._actualizar_combo_modelos, modelos)

		threading.Thread(target=obtener, daemon=True).start()

	def _actualizar_combo_modelos(self, modelos: list[str]) -> None:
		if not isAlive(self):
			return
		actual = self.combo_modelo.GetValue()
		self.combo_modelo.Set(modelos)
		self.combo_modelo.SetValue(actual)
		self.btn_actualizar_modelos.Enable()
		if modelos:
			self.lbl_estado.SetLabel(f"{len(modelos)} modelos disponibles.")
		else:
			self.lbl_estado.SetLabel(f"No se pudo obtener la lista de modelos. {self.listador.ultimo_error or ''}".strip())

	def _on_actualizar_modelos(self, event: Any) -> None:
		self.listador.borrar_cache(self.servicio_id)
		self._obtener_modelos_en_hilo()

	def _on_restablecer(self, event: Any) -> None:
		self.txt_sistema.SetValue(PROMPTS_DEFECTO["sistema"])
		self.txt_usuario.SetValue(PROMPTS_DEFECTO["usuario"])
		lector.mensaje("Prompts restablecidos")

	def _on_guardar(self, event: Any) -> None:
		modelo = self.combo_modelo.GetValue().strip()
		sistema = self.txt_sistema.GetValue().strip()
		usuario = self.txt_usuario.GetValue().strip()
		if not usuario or "{idioma_destino}" not in usuario or "{texto}" not in usuario:
			if not _preguntar("El prompt de usuario debe contener los marcadores {idioma_destino} y {texto}. ¿Desea guardar de todas formas?", "Advertencia", self):
				return
		self.configuracion.establecer_api(
			self.servicio_id,
			modelo=modelo,
			prompt_sistema=sistema if sistema != PROMPTS_DEFECTO["sistema"] else None,
			prompt_usuario=usuario if usuario != PROMPTS_DEFECTO["usuario"] else None,
			claves=self.servicio_config.claves,
			usar_rotacion=self.servicio_config.usar_rotacion,
		)
		self.configuracion.guardar()
		self.EndModal(wx.ID_OK)


# ====================================================================== traducción manual
class DialogoTraduccion(wx.Dialog):
	def __init__(self, plugin: Any, texto: str = "") -> None:
		super().__init__(None, title="Interfaz de traducción", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
		from ..utilidades.tts import GestorTTSGoogle

		self.plugin = plugin
		self.configuracion = plugin.configuracion
		self.texto_inicial = texto
		self.audio_obtenido: bytes | None = None
		self.texto_audio_anterior = ""
		self.lang_audio_anterior = ""
		self.gestor_tts = GestorTTSGoogle()
		self.ayuda = getattr(plugin, "gestor_ayuda", None) or GestorAyuda()
		self._crear_interfaz()
		self._cargar_datos()
		self._actualizar_titulo()
		self.CentreOnScreen()

	def _crear_interfaz(self) -> None:
		sizer = wx.BoxSizer(wx.VERTICAL)
		_etiqueta(self, sizer, "Texto de origen (Alt+1):")
		self.txt_origen = wx.TextCtrl(self, size=(640, 150), style=wx.TE_MULTILINE | wx.TE_RICH2)
		sizer.Add(self.txt_origen, 1, wx.EXPAND | wx.ALL, 6)
		_etiqueta(self, sizer, "Texto de destino (Alt+2):")
		self.txt_destino = wx.TextCtrl(self, size=(640, 150), style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
		sizer.Add(self.txt_destino, 1, wx.EXPAND | wx.ALL, 6)
		fila = wx.BoxSizer(wx.HORIZONTAL)
		fila.Add(wx.StaticText(self, label="Origen (Alt+3):"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
		self.combo_origen = wx.Choice(self)
		fila.Add(self.combo_origen, 1, wx.ALL, 4)
		fila.Add(wx.StaticText(self, label="Destino (Alt+4):"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
		self.combo_destino = wx.Choice(self)
		fila.Add(self.combo_destino, 1, wx.ALL, 4)
		fila.Add(wx.StaticText(self, label="Caracteres (Alt+5):"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
		self.lbl_contador = wx.TextCtrl(self, value="0", size=(70, -1), style=wx.TE_READONLY)
		fila.Add(self.lbl_contador, 0, wx.ALL, 4)
		sizer.Add(fila, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)
		acciones = wx.BoxSizer(wx.HORIZONTAL)
		self.btn_traducir = wx.Button(self, label="&Traducir")
		self.btn_escuchar = wx.Button(self, label="&Escuchar")
		self.btn_intercambiar = wx.Button(self, label="&Intercambiar")
		self.btn_limpiar = wx.Button(self, label="&Limpiar")
		self.btn_pegar = wx.Button(self, label="&Pegar al foco")
		self.btn_cerrar = wx.Button(self, wx.ID_CLOSE, "&Cerrar")
		for b in (self.btn_traducir, self.btn_escuchar, self.btn_intercambiar, self.btn_limpiar, self.btn_pegar, self.btn_cerrar):
			acciones.Add(b, 0, wx.ALL, 4)
		sizer.Add(acciones, 0, wx.ALIGN_CENTER | wx.ALL, 6)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CLOSE)
		ids = [wx.NewIdRef() for _ in range(5)]
		self.SetAcceleratorTable(wx.AcceleratorTable([(wx.ACCEL_ALT, ord(str(i + 1)), ids[i]) for i in range(5)]))
		for idr, ctrl in zip(ids, (self.txt_origen, self.txt_destino, self.combo_origen, self.combo_destino, self.lbl_contador)):
			self.Bind(wx.EVT_MENU, lambda e, c=ctrl: c.SetFocus(), id=idr)
		self.btn_traducir.Bind(wx.EVT_BUTTON, self._on_traducir)
		self.btn_escuchar.Bind(wx.EVT_BUTTON, self._on_escuchar)
		self.btn_intercambiar.Bind(wx.EVT_BUTTON, self._on_intercambiar)
		self.btn_limpiar.Bind(wx.EVT_BUTTON, self._on_limpiar)
		self.btn_pegar.Bind(wx.EVT_BUTTON, self._on_pegar)
		self.btn_cerrar.Bind(wx.EVT_BUTTON, lambda e: self.Close())
		self.txt_origen.Bind(wx.EVT_TEXT, lambda e: self._actualizar_contador())
		self.Bind(wx.EVT_CLOSE, self._on_cerrar)
		self.Bind(wx.EVT_CHAR_HOOK, self._on_tecla)
		a = self.ayuda
		a.agregar_ayuda(self.txt_origen, "Introduce el texto que deseas traducir. Puedes escribir o pegar el texto aquí. Control+Intro traduce.")
		a.agregar_ayuda(self.txt_destino, "El resultado de la traducción se mostrará aquí. Este campo es de solo lectura.")
		a.agregar_ayuda(self.combo_origen, "Selecciona el idioma de origen para la traducción.")
		a.agregar_ayuda(self.combo_destino, "Selecciona el idioma de destino para la traducción.")
		a.agregar_ayuda(self.btn_traducir, "Presiona este botón para traducir el texto de origen al idioma de destino.")
		a.agregar_ayuda(self.btn_escuchar, "Presiona este botón para escuchar la traducción verbalizada.")
		a.agregar_ayuda(self.btn_intercambiar, "Intercambia los idiomas de origen y destino.")
		a.agregar_ayuda(self.btn_limpiar, "Limpia los campos de texto de origen y destino.")
		a.agregar_ayuda(self.btn_pegar, "Pega el texto traducido en la ventana que estaba activa antes de abrir este diálogo.")
		a.agregar_ayuda(self.lbl_contador, "Muestra el número de caracteres en el campo de texto de origen.")

	def _on_tecla(self, event: wx.KeyEvent) -> None:
		if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and event.GetModifiers() == wx.MOD_CONTROL:
			self._on_traducir(None)
			return
		event.Skip()

	def _cargar_datos(self) -> None:
		gi = self.plugin.gestor_idiomas
		for cod, nom in gi.obtener_lista_idiomas(incluir_auto=True):
			self.combo_origen.Append(nom, cod)
		for cod, nom in gi.obtener_lista_idiomas(incluir_auto=False):
			self.combo_destino.Append(nom, cod)
		config = self.configuracion.config
		_seleccionar_codigo(self.combo_origen, getattr(config, "gui_idioma_origen", "auto") or "auto")
		_seleccionar_codigo(self.combo_destino, getattr(config, "gui_idioma_destino", "") or self.configuracion.idioma_destino)
		if self.texto_inicial:
			self.txt_origen.SetValue(self.texto_inicial)
		self._actualizar_contador()

	def _actualizar_contador(self) -> None:
		self.lbl_contador.SetValue(str(len(self.txt_origen.GetValue())))

	def _actualizar_titulo(self) -> None:
		t = self.plugin.gestor_traductores.obtener_traductor_activo()
		if t:
			self.SetTitle(f"Interfaz de traducción - {t.nombre}")

	def _on_traducir(self, event: Any) -> None:
		texto = self.txt_origen.GetValue().strip()
		if not texto:
			wx.Bell()
			self.txt_origen.SetFocus()
			return
		origen, destino = _codigo(self.combo_origen), _codigo(self.combo_destino)
		self.btn_traducir.Disable()
		self.txt_destino.SetValue("Traduciendo...")
		lector.mensaje("Traduciendo...")

		def traducir() -> None:
			res, error = self.plugin._traducir_manual(texto, origen, destino)

			def finalizar() -> None:
				if not isAlive(self):
					return
				self.btn_traducir.Enable()
				if res:
					self.txt_destino.SetValue(res)
					lector.hablar_texto(res)
				else:
					self.txt_destino.SetValue("Error en la traducción" + (f": {error}" if error else ""))
					lector.mensaje(self.txt_destino.GetValue())

			wx.CallAfter(finalizar)

		threading.Thread(target=traducir, name="TraductorAvanzadoPro-Manual", daemon=True).start()

	def _on_escuchar(self, event: Any) -> None:
		texto = self.txt_destino.GetValue().strip()
		if not texto or texto == "Traduciendo..." or texto.startswith("Error en la traducción"):
			lector.mensaje("No hay traducción para escuchar")
			return
		idioma = _codigo(self.combo_destino) or self.configuracion.idioma_destino
		if texto == self.texto_audio_anterior and idioma == self.lang_audio_anterior and self.audio_obtenido:
			self._abrir_reproductor(texto, self.audio_obtenido)
			return
		progreso = DialogoProgreso(self, "Obteniendo audio...", "Descargando el audio de la traducción...")
		progreso.establecer_callback_cancelar(self.gestor_tts.detener)

		def obtener() -> None:
			audio = self.gestor_tts.obtener_audio(texto, idioma, callback_progreso=progreso.actualizar)

			def finalizar() -> None:
				if isAlive(progreso) and progreso.IsModal():
					progreso.EndModal(wx.ID_OK if not progreso.fue_cancelado else wx.ID_CANCEL)
				if not isAlive(self) or progreso.fue_cancelado:
					return
				if audio:
					self.audio_obtenido = audio
					self.texto_audio_anterior = texto
					self.lang_audio_anterior = idioma
					self._abrir_reproductor(texto, audio)
				else:
					_mensaje(f"Error al obtener el audio: {self.gestor_tts.ultimo_error or 'respuesta vacía'}", "Error TTS", wx.OK | wx.ICON_ERROR, self)

			wx.CallAfter(finalizar)

		threading.Thread(target=obtener, name="TraductorAvanzadoPro-TTS", daemon=True).start()
		progreso.ShowModal()
		progreso.Destroy()

	def _abrir_reproductor(self, texto: str, audio: bytes) -> None:
		from .reproductor import DialogoReproductor

		def abrir() -> None:
			try:
				dlg = DialogoReproductor(self, self.plugin, texto, audio)
			except Exception as e:
				log.exception("No se pudo abrir el reproductor")
				_mensaje(f"Error al inicializar el reproductor multimedia:\n{e}", "Error", wx.OK | wx.ICON_ERROR, self)
				return
			dlg.ShowModal()
			if isAlive(dlg):
				dlg.Destroy()

		wx.CallAfter(abrir)

	def _on_intercambiar(self, event: Any) -> None:
		origen, destino = _codigo(self.combo_origen), _codigo(self.combo_destino)
		if origen is None or destino is None:
			return
		if origen == "auto":
			_mensaje("No se puede intercambiar cuando el origen es automático", "Información", padre=self)
			return
		_seleccionar_codigo(self.combo_origen, destino)
		_seleccionar_codigo(self.combo_destino, origen)
		traducido = self.txt_destino.GetValue()
		if traducido and traducido != "Traduciendo..." and not traducido.startswith("Error en la traducción"):
			# Como en los traductores web: el resultado pasa a ser el texto de origen.
			self.txt_origen.SetValue(traducido)
			self.txt_destino.Clear()
		lector.mensaje(f"Origen: {self.combo_origen.GetStringSelection()}. Destino: {self.combo_destino.GetStringSelection()}")

	def _on_limpiar(self, event: Any) -> None:
		self.txt_origen.Clear()
		self.txt_destino.Clear()
		self._actualizar_contador()
		self.txt_origen.SetFocus()

	def _on_pegar(self, event: Any) -> None:
		texto = self.txt_destino.GetValue()
		if not texto or texto == "Traduciendo..." or texto.startswith("Error en la traducción"):
			wx.Bell()
			return
		self.plugin._pegar_en_foco(texto)
		self.Close()

	def _on_cerrar(self, event: Any) -> None:
		config = self.configuracion.config
		if _codigo(self.combo_origen):
			config.gui_idioma_origen = _codigo(self.combo_origen)
		if _codigo(self.combo_destino):
			config.gui_idioma_destino = _codigo(self.combo_destino)
		self.gestor_tts.detener()
		self.Destroy()


# ====================================================================== cambio rápido
class DialogoSeleccionRapida(wx.Dialog):
	"""Servicio, modelo de IA, idioma de origen y de destino en un solo diálogo."""

	def __init__(self, plugin: Any) -> None:
		super().__init__(None, title="Cambio rápido de configuración", style=wx.DEFAULT_DIALOG_STYLE)
		self.plugin = plugin
		self.configuracion = plugin.configuracion
		self.listador = ListadorModelosIA(self.configuracion.ruta_modelos)
		self.ayuda = getattr(plugin, "gestor_ayuda", None) or GestorAyuda()
		sizer = wx.BoxSizer(wx.VERTICAL)
		_etiqueta(self, sizer, "&Servicio:")
		self.combo_servicio = wx.Choice(self)
		sizer.Add(self.combo_servicio, 0, wx.EXPAND | wx.ALL, 6)
		self.lbl_modelo = _etiqueta(self, sizer, "&Modelo:")
		self.combo_modelo = wx.Choice(self)
		sizer.Add(self.combo_modelo, 0, wx.EXPAND | wx.ALL, 6)
		_etiqueta(self, sizer, "Idioma de &origen:")
		self.combo_origen = wx.Choice(self)
		sizer.Add(self.combo_origen, 0, wx.EXPAND | wx.ALL, 6)
		_etiqueta(self, sizer, "Idioma de &destino:")
		self.combo_destino = wx.Choice(self)
		sizer.Add(self.combo_destino, 0, wx.EXPAND | wx.ALL, 6)
		botones = wx.StdDialogButtonSizer()
		self.btn_aceptar = wx.Button(self, wx.ID_OK, "&Aceptar")
		self.btn_cancelar = wx.Button(self, wx.ID_CANCEL, "&Cancelar")
		self.btn_aceptar.SetDefault()
		botones.AddButton(self.btn_aceptar)
		botones.AddButton(self.btn_cancelar)
		botones.Realize()
		sizer.Add(botones, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
		self.SetSizer(sizer)
		self.SetMinSize((420, -1))
		self.Fit()
		self.combo_servicio.Bind(wx.EVT_CHOICE, self._on_servicio_cambiado)
		self.Bind(wx.EVT_BUTTON, self._on_aceptar, id=wx.ID_OK)
		self.Bind(wx.EVT_BUTTON, lambda e: self.Close(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, lambda e: self.Destroy())
		self.ayuda.agregar_ayuda(self.combo_servicio, "Selecciona el motor de traducción que deseas utilizar.")
		self.ayuda.agregar_ayuda(self.combo_origen, "Selecciona el idioma original del texto.")
		self.ayuda.agregar_ayuda(self.combo_destino, "Selecciona el idioma al que deseas traducir.")
		self.ayuda.agregar_ayuda(self.combo_modelo, "Selecciona el modelo específico de la IA (si está disponible).")
		self._cargar_datos()
		self.CentreOnScreen()

	def _cargar_datos(self) -> None:
		for t in self.plugin.gestor_traductores.listar_traductores():
			etiqueta = t["nombre"] + ("" if t["api_configurada"] else " (sin clave)")
			self.combo_servicio.Append(etiqueta, t["id"])
		_seleccionar_codigo(self.combo_servicio, self.configuracion.servicio_activo)
		gi = self.plugin.gestor_idiomas
		for cod, nom in gi.obtener_lista_idiomas(incluir_auto=True):
			self.combo_origen.Append(nom, cod)
		for cod, nom in gi.obtener_lista_idiomas(incluir_auto=False):
			self.combo_destino.Append(nom, cod)
		_seleccionar_codigo(self.combo_origen, self.configuracion.idioma_origen)
		_seleccionar_codigo(self.combo_destino, self.configuracion.idioma_destino)
		self._on_servicio_cambiado(None)

	def obtener_valores(self) -> dict[str, Any]:
		valores = {"servicio": _codigo(self.combo_servicio), "origen": _codigo(self.combo_origen), "destino": _codigo(self.combo_destino), "modelo": None}
		if self.combo_modelo.IsEnabled() and self.combo_modelo.GetSelection() != wx.NOT_FOUND:
			valores["modelo"] = self.combo_modelo.GetStringSelection()
		return valores

	def _on_servicio_cambiado(self, event: Any) -> None:
		servicio = _codigo(self.combo_servicio)
		self.combo_modelo.Clear()
		if servicio in SERVICIOS_IA:
			self._cargar_modelos(servicio)
		else:
			self.lbl_modelo.Disable()
			self.combo_modelo.Disable()
		self.Layout()

	def _cargar_modelos(self, servicio: str) -> None:
		sc = self.configuracion.obtener_api(servicio)
		if not sc or not sc.api_key:
			self.lbl_modelo.Disable()
			self.combo_modelo.Disable()
			return
		self.lbl_modelo.Enable()
		self.combo_modelo.Enable()
		if sc.modelo:
			self.combo_modelo.Append(sc.modelo)
			self.combo_modelo.SetSelection(0)
		api_key = sc.api_key

		def obtener() -> None:
			modelos = self.listador.obtener_modelos(servicio, api_key)
			wx.CallAfter(self._actualizar_combo_modelos, servicio, modelos, sc.modelo)

		threading.Thread(target=obtener, daemon=True).start()

	def _actualizar_combo_modelos(self, servicio: str, modelos: list[str], modelo_actual: str | None) -> None:
		if not isAlive(self) or _codigo(self.combo_servicio) != servicio or not modelos:
			return
		if modelo_actual and modelo_actual not in modelos:
			modelos = [modelo_actual] + modelos
		self.combo_modelo.Set(modelos)
		if modelo_actual and modelo_actual in modelos:
			self.combo_modelo.SetSelection(modelos.index(modelo_actual))
		else:
			self.combo_modelo.SetSelection(0)

	def _on_aceptar(self, event: Any) -> None:
		self.plugin._aplicar_seleccion_rapida(self.obtener_valores())
		self.Close()
