"""Categoría «Traductor Avanzado Pro» del cuadro de Opciones de Tiresias.

Reúne lo que en el original era el diálogo de configuración con pestañas:

- General: servicio activo, idiomas y casillas (caché, historial, ventana de
  resultados, sonidos).
- Servicios: lista de servicios con su información.
- Claves API: gestionar las claves y configurar el modelo y los prompts de las IA.
- Avanzado: intercambio automático de idioma, información y mantenimiento.
- Además: volumen de los sonidos, reproductor de audio y plugins activos.
"""

from __future__ import annotations

import os
from typing import Any

import wx

from tiresias.gui import settings as S

from ..nucleo.configuracion import SECCION
from ..utilidades import lector
from ..utilidades.modelos_ia import SERVICIOS_IA
from .reproductor import TIEMPOS_TEXTO, VELOCIDADES

PANEL_ID = "TraductorAvanzadoPro"
TITULO = "Traductor Avanzado Pro"
VERSION = "1.0.0"

#: Instancia del complemento (la pone el GlobalPlugin al iniciarse).
plugin: Any = None

G_GENERAL = "General"
G_OPCIONES = "Opciones"
G_AVANZADO = "Avanzado"
G_REPRODUCTOR = "Reproductor de audio («Escuchar»)"


def _servicios() -> list[tuple[str, str]]:
	if plugin is None or plugin.gestor_traductores is None:
		return [("google_api_free", "Google Translate (API Gratuita)")]
	return [(t["id"], t["nombre"] + ("" if t["api_configurada"] else " (sin clave)")) for t in plugin.gestor_traductores.listar_traductores()]


def _idiomas(auto: bool) -> list[tuple[str, str]]:
	if plugin is None or plugin.gestor_idiomas is None:
		from ..servicios.idiomas import IDIOMAS_COMUNES

		return [(c, n) for c, n in IDIOMAS_COMUNES.items() if auto or c != "auto"]
	return plugin.gestor_idiomas.obtener_lista_idiomas(incluir_auto=auto)


class PanelTraductor(S.ConfigPanel):
	title = TITULO
	section = SECCION

	def getFields(self) -> list[S.Field]:
		return [
			S.Choice("servicio_activo", "&Servicio activo:", _servicios, group=G_GENERAL),
			S.Choice("idioma_origen", "Idioma de &origen:", lambda: _idiomas(True), group=G_GENERAL),
			S.Choice("idioma_destino", "Idioma de &destino:", lambda: _idiomas(False), group=G_GENERAL),
			S.Choice("idioma_destino_alternativo", "Idioma a&lternativo:", lambda: _idiomas(False), group=G_GENERAL),
			S.Bool("cache_habilitada", "Habilitar &caché de traducciones", group=G_OPCIONES),
			S.Bool("historial_habilitado", "Guardar &historial de traducciones", group=G_OPCIONES),
			S.Bool("mostrar_resultados", "Mostrar &resultados en ventana", group=G_OPCIONES),
			S.Bool("sonidos_habilitados", "Reproducir so&nidos", group=G_OPCIONES),
			S.Slider("volumen_sonido", "&Volumen de los sonidos:", 0, 100, group=G_OPCIONES, lineSize=5),
			S.Bool("intercambio_automatico_idioma", "Intercambio a&utomático de idioma si el origen coincide con el destino", group=G_AVANZADO),
			S.Slider("volumen_reproductor", "Volumen del re&productor:", 0, 100, group=G_REPRODUCTOR, lineSize=5),
			S.Choice("velocidad_audio", "Velocidad del reproductor:", [(i, f"{v}x") for i, v in enumerate(VELOCIDADES)], group=G_REPRODUCTOR),
			S.Choice("salto_atras", "Salto al retroceder:", list(enumerate(TIEMPOS_TEXTO)), group=G_REPRODUCTOR),
			S.Choice("salto_adelante", "Salto al adelantar:", list(enumerate(TIEMPOS_TEXTO)), group=G_REPRODUCTOR),
		]

	# ------------------------------------------------------------ controles propios
	def makeExtraSettings(self, builder: S.SettingsBuilder) -> None:
		self._crear_servicios(builder.group("Servicios"))
		self._crear_apis(builder.group("Claves API"))
		self._crear_plugins(builder.group("Plugins de extensión"))
		self._crear_mantenimiento(builder.group("Información y mantenimiento"))

	def _crear_servicios(self, g: S.SettingsBuilder) -> None:
		self._traductores = plugin.gestor_traductores.listar_traductores() if plugin and plugin.gestor_traductores else []
		self.lista_servicios = g.addLabeledControl("Servicios d&isponibles:", lambda p: wx.ListBox(p, choices=[f"{t['nombre']}{' [API]' if t['requiere_api'] else ''}" for t in self._traductores], size=(380, 120)), vertical=True)
		self.txt_info_servicio = g.addLabeledControl("Información del servicio:", lambda p: wx.TextCtrl(p, size=(380, 100), style=wx.TE_MULTILINE | wx.TE_READONLY), vertical=True)
		self.lista_servicios.Bind(wx.EVT_LISTBOX, self._on_seleccionar_servicio)
		if self._traductores:
			self.lista_servicios.SetSelection(0)
			self._on_seleccionar_servicio(None)

	def _on_seleccionar_servicio(self, event: Any) -> None:
		i = self.lista_servicios.GetSelection()
		if not 0 <= i < len(self._traductores):
			return
		t = self._traductores[i]
		sc = plugin.configuracion.obtener_api(t["id"]) if plugin else None
		configurada = (not t["requiere_api"]) or bool(sc and sc.claves) or t["id"] == "libretranslate"
		lineas = [
			f"Nombre: {t['nombre']}",
			f"Descripción: {t['descripcion']}",
			f"Requiere API: {'Sí' if t['requiere_api'] else 'No'}",
			f"API configurada: {'Sí' if configurada else 'No'}",
			f"Detección de idioma: {'Sí' if t.get('soporta_deteccion') else 'No'}",
			f"Versión: {t.get('version', 'N/A')}",
		]
		if t.get("es_ia") and sc and sc.modelo:
			lineas.append(f"Modelo: {sc.modelo}")
		self.txt_info_servicio.SetValue("\n".join(lineas))

	def _crear_apis(self, g: S.SettingsBuilder) -> None:
		self._resumenes: dict[str, wx.StaticText] = {}
		self._botones_ia: dict[str, wx.Button] = {}
		for t in self._traductores:
			if not t["requiere_api"]:
				continue
			sid, nombre = t["id"], t["nombre"]
			fila = wx.BoxSizer(wx.HORIZONTAL)
			resumen = wx.StaticText(g.parent, label=f"{nombre}: sin configurar")
			fila.Add(resumen, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
			btn = wx.Button(g.parent, label=f"Gestionar claves de {nombre}...")
			btn.Bind(wx.EVT_BUTTON, lambda e, s=sid, n=nombre: self._on_gestionar_api(s, n))
			fila.Add(btn, 0, wx.RIGHT, 4)
			if sid in SERVICIOS_IA or t.get("es_ia"):
				bia = wx.Button(g.parent, label=f"Configurar {nombre}...")
				bia.Bind(wx.EVT_BUTTON, lambda e, s=sid, n=nombre: self._on_configurar_ia(s, n))
				fila.Add(bia, 0)
				self._botones_ia[sid] = bia
			g.sizer.Add(fila, 0, wx.EXPAND | wx.BOTTOM, 4)
			self._resumenes[sid] = resumen
		self._actualizar_resumenes()

	def _actualizar_resumenes(self) -> None:
		for sid, resumen in self._resumenes.items():
			t = next((x for x in self._traductores if x["id"] == sid), None)
			nombre = t["nombre"] if t else sid
			sc = plugin.configuracion.obtener_api(sid) if plugin else None
			if sc and sc.claves:
				rot = " (rotación activa)" if sc.usar_rotacion else ""
				resumen.SetLabel(f"{nombre}: {len(sc.claves)} clave(s) configurada(s){rot}")
			else:
				resumen.SetLabel(f"{nombre}: sin configurar")
			if sid in self._botones_ia:
				self._botones_ia[sid].Enable(bool(sc and sc.claves))
		self.Layout()

	def _on_gestionar_api(self, sid: str, nombre: str) -> None:
		from .dialogos import DialogoGestionAPI

		traductor = plugin.gestor_traductores.obtener_traductor(sid) if plugin else None
		dlg = DialogoGestionAPI(self, plugin.configuracion, sid, nombre, traductor)
		if dlg.ShowModal() == wx.ID_OK:
			self._actualizar_resumenes()
			self._traductores = plugin.gestor_traductores.listar_traductores()
			self.updateChoices("servicio_activo", _servicios())
			self._on_seleccionar_servicio(None)
		dlg.Destroy()

	def _on_configurar_ia(self, sid: str, nombre: str) -> None:
		from .dialogos import DialogoConfiguracionIA

		traductor = plugin.gestor_traductores.obtener_traductor(sid) if plugin else None
		dlg = DialogoConfiguracionIA(self, plugin.configuracion, sid, nombre, getattr(traductor, "MODELO_DEFECTO", ""))
		if dlg.ShowModal() == wx.ID_OK:
			self._on_seleccionar_servicio(None)
		dlg.Destroy()

	def _crear_plugins(self, g: S.SettingsBuilder) -> None:
		self._plugins = plugin.gestor_plugins.listar_plugins() if plugin and plugin.gestor_plugins else []
		desactivados = set(getattr(plugin.configuracion.config, "plugins_desactivados", []) or []) if plugin else set()
		self.lista_plugins = g.addLabeledControl("Plugins &activos:", lambda p: wx.CheckListBox(p, choices=[pl["nombre"] for pl in self._plugins], size=(380, 110)), vertical=True)
		for i, pl in enumerate(self._plugins):
			self.lista_plugins.Check(i, pl["id"] not in desactivados)
		self.txt_info_plugin = g.addLabeledControl("Descripción del plugin:", lambda p: wx.TextCtrl(p, size=(380, 60), style=wx.TE_MULTILINE | wx.TE_READONLY), vertical=True)
		self.lista_plugins.Bind(wx.EVT_LISTBOX, self._on_seleccionar_plugin)
		if self._plugins:
			self.lista_plugins.SetSelection(0)
			self._on_seleccionar_plugin(None)

	def _on_seleccionar_plugin(self, event: Any) -> None:
		i = self.lista_plugins.GetSelection()
		if 0 <= i < len(self._plugins):
			pl = self._plugins[i]
			self.txt_info_plugin.SetValue(f"{pl['descripcion']}\nTipo: {pl['tipo']}. Versión: {pl['version']}. Autor: {pl['autor']}.")

	def _crear_mantenimiento(self, g: S.SettingsBuilder) -> None:
		ruta = plugin.configuracion.ruta_config if plugin else ""
		info = f"Versión del complemento: {VERSION}\nCarpeta de datos (caché, historial, claves): {ruta}"
		errores = []
		if plugin:
			errores = (plugin.gestor_traductores.errores if plugin.gestor_traductores else []) + (plugin.gestor_plugins.errores if plugin.gestor_plugins else [])
		if errores:
			info += "\nNo se pudieron cargar: " + "; ".join(f"{a} ({m})" for a, m in errores)
		g.addLabeledControl("Información del sistema:", lambda p: wx.TextCtrl(p, value=info, size=(380, 70), style=wx.TE_MULTILINE | wx.TE_READONLY), vertical=True)
		fila = wx.BoxSizer(wx.HORIZONTAL)
		for etiqueta, accion in (
			("Limpiar caché", self._on_limpiar_cache),
			("Limpiar historial", self._on_limpiar_historial),
			("Restablecer configuración", self._on_restablecer),
			("Abrir carpeta de datos", self._on_abrir_carpeta),
		):
			b = wx.Button(g.parent, label=etiqueta)
			b.Bind(wx.EVT_BUTTON, accion)
			fila.Add(b, 0, wx.RIGHT, 4)
		g.sizer.Add(fila, 0, wx.BOTTOM, 4)

	def _on_limpiar_cache(self, event: Any) -> None:
		if plugin and plugin.cache and S.askYesNo("¿Borrar todas las traducciones guardadas en la caché?", "Confirmar", self):
			plugin.cache.limpiar()
			S.message_dialog.messageBox("Caché limpiada correctamente.", "Información", wx.OK | wx.ICON_INFORMATION, self)

	def _on_limpiar_historial(self, event: Any) -> None:
		if plugin and plugin.historial and S.askYesNo("¿Está seguro de que desea limpiar todo el historial?", "Confirmar", self):
			plugin.historial.limpiar()
			S.message_dialog.messageBox("Historial limpiado correctamente.", "Información", wx.OK | wx.ICON_INFORMATION, self)

	def _on_restablecer(self, event: Any) -> None:
		if S.askYesNo("¿Poner los valores de fábrica en esta categoría? Las claves de API no se borran. Los cambios se guardan al pulsar Aceptar o Aplicar.", "Restablecer configuración", self):
			self.resetToFactory()
			lector.mensaje("Valores de fábrica puestos. Pulse Aceptar para guardarlos.")

	def resetExtraToFactory(self) -> None:
		for i in range(self.lista_plugins.GetCount()):
			self.lista_plugins.Check(i, True)

	def _on_abrir_carpeta(self, event: Any) -> None:
		if plugin:
			try:
				os.startfile(plugin.configuracion.ruta_config)  # type: ignore[attr-defined]
			except OSError:
				wx.Bell()

	# ------------------------------------------------------------ guardar
	def onSave(self) -> None:
		super().onSave()
		if plugin is None:
			return
		desactivados = [pl["id"] for i, pl in enumerate(self._plugins) if not self.lista_plugins.IsChecked(i)]
		from tiresias.config import conf

		if list(conf[SECCION]["plugins_desactivados"] or []) != desactivados:
			conf[SECCION]["plugins_desactivados"] = desactivados
		if plugin.gestor_plugins:
			plugin.gestor_plugins.aplicar_desactivados()

	def afterSave(self, changes: dict) -> None:
		if plugin is None:
			return
		if (SECCION, "cache_habilitada") in changes and plugin.cache:
			if changes[(SECCION, "cache_habilitada")][1]:
				plugin.cache.cargar()
			else:
				plugin.cache.guardar_todo()


def registrar() -> None:
	S.registerPanel(PANEL_ID, TITULO, PanelTraductor)


def desregistrar() -> None:
	S.unregisterPanel(PANEL_ID)
