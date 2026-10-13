"""Opciones del complemento.

Las mismas opciones están en dos sitios:

- la categoría «Visor de consola» del cuadro de Opciones de Tiresias;
- el diálogo de opciones del visor (Archivo, Opciones o Control+P), con una
  pestaña por grupo como en el original (Visual, Procesamiento, Lanzador,
  Plugins, Alertas e Inteligencia artificial).
"""

from __future__ import annotations

import wx

from tiresias.gui import settings as S

from .. import configuracion as cfg

GRUPO_VISUAL = "Visual y seguimiento"
GRUPO_PROCESAMIENTO = "Procesamiento de texto"
GRUPO_LANZADOR = "Lanzador"
GRUPO_HERRAMIENTAS = "Plugins (herramientas del visor)"
GRUPO_ALERTAS = "Alertas"
GRUPO_IA = "Inteligencia artificial"
GRUPOS = [GRUPO_VISUAL, GRUPO_PROCESAMIENTO, GRUPO_LANZADOR, GRUPO_HERRAMIENTAS, GRUPO_ALERTAS, GRUPO_IA]
#: Título de cada pestaña del diálogo del visor.
PESTANAS = {
	GRUPO_VISUAL: "Visual",
	GRUPO_PROCESAMIENTO: "Procesamiento",
	GRUPO_LANZADOR: "Lanzador",
	GRUPO_HERRAMIENTAS: "Plugins",
	GRUPO_ALERTAS: "Alertas",
	GRUPO_IA: "IA",
}

#: Complemento global en marcha (lo fija el complemento al iniciarse).
complemento = None


def _opcionesHerramientas() -> list:
	from ..herramientas import GestorHerramientas

	return GestorHerramientas().opciones_lista()


def campos(grupo: str) -> list:
	if grupo == GRUPO_VISUAL:
		return [
			S.Int("tamanoFuente", "&Tamaño de la fuente:", 8, 30),
			S.Bool("fuenteMonoespaciada", "Usar fuente &monoespaciada (Consolas)"),
			S.Bool("recordarTamano", "&Recordar tamaño y posición de la ventana"),
			S.Bool("sonidosSeguimiento", "Emitir sonidos al activar o desactivar el &seguimiento"),
			S.Bool("sonidosAlActualizar", "Emitir sonidos cada vez que el contenido se act&ualice"),
			S.Bool("proteccionRafagas", "&Proteger la voz frente a ráfagas de salida de las consolas"),
			S.Int("intervaloSeguimiento", "Seguimiento cada (m&ilisegundos):", cfg.INTERVALO_MIN, cfg.INTERVALO_MAX),
			S.Bool("conservarHistorial", "Conservar en el visor las líneas que salgan del &búfer de la consola"),
			S.Int("limiteMilesCaracteres", "&Límite del visor (miles de caracteres, 0 sin límite):", 0, 50000),
			S.Bool("categorizarHerramientas", "Agrupar las herramientas del menú Plugins por &categorías"),
		]
	if grupo == GRUPO_PROCESAMIENTO:
		return [
			S.Bool("habilitarProcesamiento", "&Procesar el texto capturado con las opciones siguientes"),
			S.Bool("limpiarAnsi", "Eliminar los códigos de color &ANSI"),
			S.Bool("condensarSimbolos", "Condensar &símbolos repetidos («=====» se lee «5 igual»)"),
			S.Text("simbolosACondensar", "Símbolos que se &condensan:"),
			S.Bool("procesarBidi", "Reordenar el texto &bidireccional (árabe, hebreo)"),
			S.Bool("procesarEmoji", "Tener en cuenta las secuencias de &emoji en los anchos de columna"),
			S.Bool("detectarIndentacion", "Anunciar la &indentación al moverse por las líneas del visor"),
			S.Choice("nivelPuntuacion", "&Nivel de puntuación de los anuncios del visor:", cfg.NIVELES_PUNTUACION),
			S.Bool("detectarTerminal", "&Detectar automáticamente el tipo de terminal"),
			S.Bool("usarPerfilTerminal", "Aplicar el p&erfil de la terminal detectada"),
		]
	if grupo == GRUPO_LANZADOR:
		return [
			S.Bool("lanzadorRecordarUltima", "Recordar la última consola &seleccionada"),
			S.Bool("lanzadorMostrarNoDisponibles", "Mostrar consolas &no instaladas en la lista"),
		]
	if grupo == GRUPO_HERRAMIENTAS:
		return [S.Field("herramientasHabilitadas", "Seleccione los &plugins que desea activar:", "checklist", choices=_opcionesHerramientas)]
	if grupo == GRUPO_ALERTAS:
		return [
			S.Bool("alertasHabilitadas", "Habilitar el sistema de &alertas y marcadores"),
			S.Bool("alertasVoz", "Avisar por &voz al detectar un patrón"),
			S.Bool("alertasSonido", "Reproducir un &sonido al detectar un patrón"),
		]
	if grupo == GRUPO_IA:
		return [
			S.Choice("iaProveedor", "&Proveedor de IA del chat y de los informes:", cfg.PROVEEDORES_IA),
			S.Text("iaModeloGoogle", "&Modelo de Google AI:"),
			S.Bool("iaMantenerHistorial", "Mantener el &historial de la conversación (enviar los turnos anteriores)"),
		]
	return []


class PanelConsoleLog(S.ConfigPanel):
	"""Panel de opciones; ``grupos`` decide qué grupos muestra."""

	title = "Visor de consola"
	section = cfg.SECCION
	grupos: list[str] = GRUPOS
	cajas = True

	def getFields(self) -> list:
		salida = []
		for grupo in self.grupos:
			for f in campos(grupo):
				if self.cajas:
					f.group = grupo
				salida.append(f)
		return salida

	def _constructor(self, grupo: str, raiz):
		if not self.cajas:
			return raiz
		b = getattr(self, "_groups", {}).get(grupo)
		return b or raiz.group(grupo)

	def makeExtraSettings(self, builder) -> None:
		self._patrones = None
		self._prompt = None
		if GRUPO_ALERTAS in self.grupos:
			b = self._constructor(GRUPO_ALERTAS, builder)
			self._patrones = b.addLabeledControl(
				"&Patrones de alerta (uno por línea; no distingue mayúsculas):",
				lambda p: wx.TextCtrl(p, value="\n".join(cfg.patronesAlerta()), size=(360, 120), style=wx.TE_MULTILINE),
				vertical=True,
			)
			b.addStaticText("Solo se analiza el texto nuevo de cada captura del seguimiento.")
		if GRUPO_IA in self.grupos:
			b = self._constructor(GRUPO_IA, builder)
			self._prompt = b.addLabeledControl(
				"&Instrucciones de sistema:",
				lambda p: wx.TextCtrl(p, value=str(cfg.valor("iaPromptSistema") or ""), size=(360, 90), style=wx.TE_MULTILINE),
				vertical=True,
			)
			restablecer = b.addButton("&Restablecer las instrucciones por defecto")
			restablecer.Bind(wx.EVT_BUTTON, lambda e: self._prompt.SetValue(cfg.PROMPT_SISTEMA_DEFECTO))
			claves = b.addButton("Gestionar las &claves de Google AI...")
			claves.Bind(wx.EVT_BUTTON, self._alClaves)

	def _alClaves(self, _evt) -> None:
		from .dialogos import editar_claves_google

		editar_claves_google(self)

	def resetExtraToFactory(self) -> None:
		if self._patrones is not None:
			self._patrones.SetValue("\n".join(cfg.DEFAULTS["alertasPatrones"]))
		if self._prompt is not None:
			self._prompt.SetValue(cfg.PROMPT_SISTEMA_DEFECTO)

	def onSave(self) -> None:
		super().onSave()
		cambios = {}
		if self._patrones is not None:
			patrones = [p.strip() for p in self._patrones.GetValue().splitlines() if p.strip()]
			if patrones != cfg.patronesAlerta():
				cfg.establecer("alertasPatrones", patrones)
				cambios[(cfg.SECCION, "alertasPatrones")] = (None, patrones)
		if self._prompt is not None:
			prompt = self._prompt.GetValue().strip() or cfg.PROMPT_SISTEMA_DEFECTO
			if prompt != cfg.valor("iaPromptSistema"):
				cfg.establecer("iaPromptSistema", prompt)
				cambios[(cfg.SECCION, "iaPromptSistema")] = (None, prompt)
		if cambios:
			self.afterSave(cambios)

	def afterSave(self, changes) -> None:
		if complemento is not None:
			try:
				complemento.aplicar_configuracion(set(k for _s, k in changes))
			except Exception:
				from tiresias.log import getLogger

				getLogger("consoleLog").exception("consoleLog: error aplicando las opciones")


def panel_para(grupo: str) -> type:
	"""Clase de panel con un solo grupo y sin caja (pestañas del diálogo del visor)."""
	return type("Panel_" + "".join(c for c in grupo if c.isalnum()), (PanelConsoleLog,), {"grupos": [grupo], "cajas": False, "title": PESTANAS.get(grupo, grupo)})


class AjustesDialog(wx.Dialog):
	"""Opciones del visor de consola en pestañas (Control+P en el visor)."""

	def __init__(self, parent) -> None:
		super().__init__(parent, title="Opciones de Visor de consola", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.notebook = wx.Notebook(self)
		self.paneles: list = []
		for grupo in GRUPOS:
			panel = panel_para(grupo)(self.notebook)
			self.notebook.AddPage(panel, PESTANAS[grupo])
			self.paneles.append(panel)
		sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 6)
		sizer.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, 8)
		self.SetSizerAndFit(sizer)
		self.SetSize((max(620, self.GetSize().width), max(560, self.GetSize().height)))
		self.CentreOnParent()
		self.Bind(wx.EVT_BUTTON, self._alAceptar, id=wx.ID_OK)
		wx.CallAfter(self.notebook.SetFocus)

	def _alAceptar(self, evt) -> None:
		for i, panel in enumerate(self.paneles):
			if not panel.isValid():
				self.notebook.SetSelection(i)
				return
		for panel in self.paneles:
			panel.onSave()
		evt.Skip()


def registrar_panel() -> None:
	S.registerPanel(cfg.ADDON_ID, PanelConsoleLog.title, PanelConsoleLog)


def retirar_panel() -> None:
	S.unregisterPanel(cfg.ADDON_ID)
