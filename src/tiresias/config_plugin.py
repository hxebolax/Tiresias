"""Órdenes del área de configuración e interfaz (complemento global incorporado).

- Ajustes rápidos: buscar cualquier opción por su nombre y cambiarla.
- Teclas por capas: ``Tiresias+Alt+Espacio`` y después una letra abre una
  capa (voz, ventanas, herramientas, configuración...). Dentro de cada capa,
  ``?`` dice sus teclas y Escape la cierra. ``Tiresias+Espacio`` no se usa
  porque en los documentos cambia entre modo exploración y modo foco.
- Referencia rápida de órdenes, novedades, gestor de etiquetas, tutorial,
  buscar actualizaciones y tienda de complementos.
"""

from __future__ import annotations

from typing import Any

from . import queue_handler, speech
from .baseobject import script
from .config import conf
from .i18n import _
from .log import getLogger
from .plugins import GlobalPlugin as _Base

log = getLogger("configPlugin")

CAT_CONFIG = _("Configuración")
CAT_TOOLS = _("Herramientas")
CAT_LAYERS = _("Teclas por capas")

#: Instancia en ejecución (la usan los mapas de gestos alternativos).
instance: "GlobalPlugin | None" = None

#: Capas: {tecla: (nombre, {tecla: (descripción, destino)})}. El destino es
#: "global:<orden>" (órdenes globales), "config:<orden>" (este complemento) o
#: "gui:<función>" (función de :mod:`tiresias.gui`).
LAYERS: dict[str, tuple[str, dict[str, tuple[str, str]]]] = {
	"v": (
		_("voz"),
		{
			"s": (_("modo de voz"), "global:speechMode"),
			"p": (_("nivel de puntuación"), "global:cycleSpeechSymbolLevel"),
			"r": (_("repetir lo último dicho"), "global:repeatLastSpokenInformation"),
			"c": (_("copiar lo último dicho"), "global:copyLastSpokenInformation"),
			"h": (_("historial de voz"), "global:speechHistory"),
			"o": (_("opciones de voz"), "global:activateVoiceDialog"),
			"t": (_("seleccionar sintetizador"), "global:activateSynthesizerDialog"),
			"d": (_("cambios dinámicos de contenido"), "global:toggleReportDynamicContentChanges"),
		},
	),
	"w": (
		_("ventanas"),
		{
			"t": (_("título"), "global:title"),
			"l": (_("lista de ventanas"), "global:windowList"),
			"b": (_("leer la ventana"), "global:speakForeground"),
			"f": (_("objeto con foco"), "global:reportCurrentFocus"),
			"e": (_("barra de estado"), "global:reportStatusLine"),
			"a": (_("aplicación actual"), "global:reportAppModuleInfo"),
		},
	),
	"b": (
		_("braille"),
		{
			"t": (_("seguimiento del braille"), "global:braille_toggleTether"),
			"v": (_("visor braille"), "gui:toggleBrailleViewer"),
			"o": (_("opciones de braille"), "global:activateBrailleSettingsDialog"),
		},
	),
	"h": (
		_("herramientas"),
		{
			"p": (_("paleta de órdenes"), "global:commandPalette"),
			"c": (_("historial del portapapeles"), "global:clipboardHistory"),
			"o": (_("reconocer texto"), "global:recognizeWithOcr"),
			"r": (_("visor de registro"), "gui:showLogViewer"),
			"e": (_("etiquetas personalizadas"), "config:labelsManager"),
			"s": (_("visor de voz"), "gui:toggleSpeechViewer"),
		},
	),
	"c": (
		_("configuración"),
		{
			"a": (_("ajustes rápidos"), "config:quickSettings"),
			"o": (_("opciones generales"), "global:activateGeneralSettingsDialog"),
			"p": (_("perfiles de configuración"), "global:activateConfigProfilesDialog"),
			"g": (_("gestos de entrada"), "gui:showInputGestures"),
			"s": (_("guardar la configuración"), "global:saveConfiguration"),
			"k": (_("referencia rápida de órdenes"), "config:keyCommandsReference"),
		},
	),
	"a": (
		_("ayuda"),
		{
			"m": (_("manual de usuario"), "gui:showUserManual"),
			"n": (_("novedades"), "gui:showNews"),
			"t": (_("tutorial de primeros pasos"), "config:tutorial"),
			"e": (_("ayuda de entrada"), "global:toggleInputHelp"),
			"u": (_("buscar actualizaciones"), "config:checkForUpdates"),
		},
	),
	"m": (
		_("lupa y visión"),
		{
			"l": (_("lupa"), "global:toggleMagnifier"),
			"c": (_("cortina de pantalla"), "global:toggleScreenCurtain"),
			"r": (_("resaltado visual"), "global:toggleFocusHighlight"),
		},
	),
}


class GlobalPlugin(_Base):
	scriptCategory = CAT_CONFIG

	def __init__(self) -> None:
		super().__init__()
		global instance
		instance = self
		self._layer: dict[str, tuple[str, Any]] | None = None
		self._layerName = ""
		self._layerGen = 0
		self._captureRef = None

	def terminate(self) -> None:
		global instance
		self._stopLayer()
		if instance is self:
			instance = None

	def getScript(self, gesture):
		func = super().getScript(gesture)
		if func is None:
			return None
		# Las teclas del mapa compatible con JAWS (Tiresias+Espacio, Tiresias+V...)
		# ceden ante el documento, la aplicación y el foco, como las globales.
		from . import gesture_layouts

		if gesture_layouts.yieldsToLater(self, gesture):
			return None
		return func

	# --------------------------------------------------------- órdenes
	@script(description=_("Ajustes rápidos: busca cualquier opción por su nombre y la cambia"), category=CAT_CONFIG, gesture="kb:tiresias+control+q")
	def script_quickSettings(self, gesture) -> None:
		from . import gui

		gui.showQuickSettings()

	@script(description=_("Muestra la referencia rápida con todas las órdenes y sus teclas"), category=CAT_CONFIG)
	def script_keyCommandsReference(self, gesture) -> None:
		from . import gui

		gui.showKeyCommandsReference()

	@script(description=_("Abre el gestor de etiquetas personalizadas"), category=CAT_TOOLS)
	def script_labelsManager(self, gesture) -> None:
		from . import gui

		gui.showLabelsManager()

	@script(description=_("Inicia el tutorial interactivo de primeros pasos"), category=CAT_CONFIG)
	def script_tutorial(self, gesture) -> None:
		from . import gui

		gui.showTutorial()

	@script(description=_("Busca una actualización de Tiresias"), category=CAT_CONFIG)
	def script_checkForUpdates(self, gesture) -> None:
		from . import updates

		updates.checkNow(manual=True)

	@script(description=_("Abre la tienda de complementos"), category=CAT_CONFIG)
	def script_addonStore(self, gesture) -> None:
		from . import gui

		gui.showAddonStore()

	@script(description=_("Actualiza la información del objeto con foco y del documento"), category=CAT_TOOLS)
	def script_refreshScreen(self, gesture) -> None:
		from . import api, baseobject, events

		baseobject.invalidateCaches()
		focus = api.getFocusObject()
		ti = getattr(focus, "treeInterceptor", None) if focus is not None else None
		refresh = getattr(ti, "script_refreshBuffer", None) if ti is not None else None
		if refresh is not None:
			refresh(gesture)
			return
		try:
			from .objects.uia import getFocusObject

			obj = getFocusObject()
		except Exception:
			obj = None
		if obj is not None:
			api.setFocusObject(None)
			events.executeEvent("gainFocus", obj)
		else:
			speech.speakMessage(_("No se pudo actualizar"))

	# --------------------------------------------------------- capas
	@script(
		description=_("Teclas por capas: pulse después una letra (v voz, w ventanas, b braille, h herramientas, c configuración, a ayuda, m lupa; ? para la lista)"),
		category=CAT_LAYERS,
		gesture="kb:tiresias+alt+space",
	)
	def script_layerKey(self, gesture) -> None:
		if not conf["keyboard"]["layersEnabled"]:
			speech.speakMessage(_("Las teclas por capas están desactivadas"))
			return
		self._startLayer(None, _("capas"))

	def _startLayer(self, layer: dict | None, name: str) -> None:
		from .audio import tones
		from .input import core as inputCore

		self._layer = layer
		self._layerName = name
		self._layerGen += 1
		gen = self._layerGen

		def capture(gesture) -> bool:
			if self._captureRef is not capture:
				# Captura antigua: se pulsaron dos teclas antes de atender la
				# primera. La tecla es para la capa que esté abierta ahora.
				current = inputCore.manager.captureFunc
				if current is not None and current is not capture:
					return current(gesture)
				if hasattr(gesture, "send"):
					# Ya no hay capa: la tecla no se pierde.
					gesture.send()
				return True
			if inputCore.manager.captureFunc is capture:
				inputCore.manager.captureFunc = None
			self._captureRef = None
			self._onLayerKey(gesture)
			return True

		self._captureRef = capture
		inputCore.manager.captureFunc = capture
		tones.beep(660, 40)
		timeout = max(1, int(conf["keyboard"]["layerTimeout"])) * 1000
		queue_handler.callLater(timeout, lambda: self._layerTimeout(gen))

	def _layerTimeout(self, gen: int) -> None:
		if gen == self._layerGen and self._captureRef is not None:
			self._stopLayer()
			from .audio import tones

			tones.beep(330, 40)

	def _stopLayer(self) -> None:
		try:
			from .input import core as inputCore

			if self._captureRef is not None and inputCore.manager.captureFunc is self._captureRef:
				inputCore.manager.captureFunc = None
		except Exception:
			pass
		self._captureRef = None
		self._layer = None

	def _currentEntries(self) -> dict:
		if self._layer is None:
			return {k: (name, sub) for k, (name, sub) in LAYERS.items()}
		return self._layer

	def describeLayer(self) -> str:
		entries = self._currentEntries()
		parts = [f"{k}: {v[0]}" for k, v in entries.items()]
		return _("Capa {name}. ").format(name=self._layerName) + ", ".join(parts)

	def _onLayerKey(self, gesture) -> None:
		key = (getattr(gesture, "char", None) or getattr(gesture, "mainKeyName", "") or "").lower()
		layer = self._layer
		self._layer = None
		if key in ("escape", ""):
			speech.speakMessage(_("Capa cerrada"))
			return
		self._layer = layer
		entries = self._currentEntries()
		if key == "?":
			speech.speakMessage(self.describeLayer())
			# Se sigue en la misma capa.
			self._startLayer(layer, self._layerName)
			return
		entry = entries.get(key)
		self._layer = None
		if entry is None:
			from .audio import tones

			tones.playSound("error")
			speech.speakMessage(_("La tecla {key} no está en la capa {name}").format(key=key, name=self._layerName))
			return
		name, target = entry
		if isinstance(target, dict):
			speech.speakMessage(name)
			self._startLayer(target, name)
			return
		self.runTarget(target, gesture)

	def runTarget(self, target: str, gesture: Any = None) -> bool:
		kind, _sep, name = target.partition(":")
		if kind == "gui":
			from . import gui

			func = getattr(gui, name, None)
			if func is None:
				return False
			gui.runOnGui(func)
			return True
		obj: Any = self
		if kind == "global":
			from .global_commands import commands

			obj = commands
		func = getattr(obj, "script_" + name, None)
		if func is None:
			speech.speakMessage(_("Orden no disponible"))
			return False
		from .input import core as inputCore

		inputCore.manager._executeScript(func, gesture)
		return True


def layerTargets() -> list[str]:
	"""Todos los destinos de las capas (para las pruebas)."""
	return [target for _n, sub in LAYERS.values() for _d, target in sub.values()]
