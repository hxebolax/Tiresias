"""Monitor de recursos para Tiresias.

Anuncia la carga de la CPU, la memoria, los discos, la batería, la red
inalámbrica, la versión de Windows, el tiempo de actividad y la GPU. Cada
orden, pulsada dos veces, copia la información al portapapeles. Avisa además
de las conexiones y desconexiones de la wifi (con mensaje, sonido o ambos).

Las órdenes se usan sobre todo desde una capa: Tiresias+Mayúsculas+0 y
después una letra (C, M, D, W, O, U, G, Mayúsculas+G, B o Espacio). Escape
sale de la capa; cualquier otra tecla sale y llega a la aplicación.

Basado en Resource Monitor para NVDA, de Alex Hall, Joseph Lee, Kefas Lungu,
Beqa Gozalishvili, Tuukka Ojala, Ethin Probst, Kevin Derome y otros
colaboradores (licencia GPL). Código propio para Tiresias.
"""

from __future__ import annotations

import os
import threading
from typing import Callable

from tiresias import queue_handler
from tiresias.baseobject import normalizeGestureId, script
from tiresias.log import getLogger
from tiresias.plugins import GlobalPlugin as _BaseGlobalPlugin

from . import gpu, info, options, wlan

log = getLogger("resourceMonitor")

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
CATEGORY = "Monitor de recursos"

#: Gesto que activa la capa de órdenes. El original usa NVDA+Mayúsculas+E, que
#: en Tiresias es «IA: explora la página»; se usa Tiresias+Mayúsculas+0, junto
#: a las órdenes heredadas Tiresias+Mayúsculas+1 a 7.
LAYER_ENTRY_GESTURE = "kb:tiresias+shift+0"

#: Teclas de la capa → orden.
LAYER_GESTURES = {
	"kb:space": "announceResourceSummary",
	"kb:c": "announceProcessorInfo",
	"kb:m": "announceRamInfo",
	"kb:d": "announceDriveInfo",
	"kb:w": "wlanStatusReport",
	"kb:o": "announceWinVer",
	"kb:u": "announceUptime",
	"kb:g": "announceGpuInfo",
	"kb:shift+g": "announceGpuMemoryInfo",
	"kb:b": "announceBatteryInfo",
	"kb:escape": "layerExit",
}

WIFI_MESSAGES = {
	wlan.EVENT_CONNECTED: ("Conectado a {ssid}", "connect.wav"),
	wlan.EVENT_DISCONNECTED: ("Desconectado de {ssid}", "disconnect.wav"),
	wlan.EVENT_INTERFACE_ARRIVAL: ("Se ha habilitado un dispositivo de red inalámbrica", "connect.wav"),
	wlan.EVENT_INTERFACE_REMOVAL: ("Se ha deshabilitado un dispositivo de red inalámbrica", "disconnect.wav"),
}


def isSecureMode() -> bool:
	"""Tiresias se ejecuta en modo seguro (pantallas de inicio de sesión, UAC...)."""
	try:
		from tiresias.config.policy import policy

		return bool(policy.secureMode)
	except Exception:
		return False


def isSecureContext() -> bool:
	"""Modo seguro o pantalla de bloqueo: no se copia nada al portapapeles."""
	if isSecureMode():
		return True
	try:
		from tiresias.a11y import system

		return bool(system.isLockScreenActive())
	except Exception:
		return False


def _speak(text: str) -> None:
	from tiresias import speech

	# Las órdenes se pueden oír también en el modo de voz «a demanda».
	with speech.allowOnDemand():
		speech.speakMessage(text)


def _repeatCount() -> int:
	from tiresias.input import core as inputCore

	return inputCore.getLastScriptRepeatCount()


class GlobalPlugin(_BaseGlobalPlugin):
	scriptCategory = CATEGORY
	#: Las consultas se hacen en un hilo aparte (las pruebas lo desactivan).
	runInThread = True

	def __init__(self) -> None:
		super().__init__()
		self._terminated = False
		self._isLayerActive = False
		self._layerIds = frozenset(normalizeGestureId(g) for g in (*LAYER_GESTURES, LAYER_ENTRY_GESTURE))
		self._gpuProviders: list[gpu.BaseGpuProvider] = gpu.getGpuProviders()
		options.registerDefaults()
		info.primeCpu()
		try:
			options.registerPanel()
		except Exception:
			log.debug("No se pudo añadir la categoría del Monitor de recursos", exc_info=True)
		try:
			from tiresias.input import core as inputCore

			inputCore.decide_executeGesture.register(self._decideExecuteGesture)
		except Exception:
			log.debug("No se pudo registrar la capa de órdenes", exc_info=True)
		self._wlan = wlan.WlanClient(self._onWlanEvent)
		if not self._wlan.open():
			self._wlan = None

	def terminate(self) -> None:
		self._terminated = True
		try:
			from tiresias.input import core as inputCore

			inputCore.decide_executeGesture.unregister(self._decideExecuteGesture)
		except Exception:
			pass
		self._finishLayer()
		try:
			options.unregisterPanel()
		except Exception:
			pass
		self._gpuProviders.clear()
		if self._wlan is not None:
			self._wlan.close()
			self._wlan = None
		super().terminate()

	# ================================================================ capa de órdenes
	def _decideExecuteGesture(self, gesture) -> bool:
		"""Sale de la capa antes de resolver una tecla que no es de la capa.

		Se llama en el hilo de los ganchos: solo quita las asignaciones (rápido)
		y deja que la tecla siga su camino (llega a la aplicación).
		"""
		if self._isLayerActive and not getattr(gesture, "isModifier", False):
			ids = {normalizeGestureId(i) for i in getattr(gesture, "identifiers", ()) or ()}
			if self._layerIds.isdisjoint(ids):
				self._finishLayer()
		return True

	def _finishLayer(self) -> None:
		self._isLayerActive = False
		inst = self.__dict__.get("_instanceGestures")
		if inst is None:
			return
		for gestureId in LAYER_GESTURES:
			inst.pop(gestureId, None)

	@property
	def isLayerActive(self) -> bool:
		return self._isLayerActive

	@script(
		description="Entra en la capa de órdenes del Monitor de recursos",
		category=CATEGORY,
		gesture=LAYER_ENTRY_GESTURE,
	)
	def script_layerEntry(self, gesture) -> None:
		if self._isLayerActive:
			return
		self.bindGestures(LAYER_GESTURES)
		self._isLayerActive = True
		from tiresias.audio import tones

		tones.beep(100, 10)
		try:
			from tiresias import braille

			braille.handler.message(CATEGORY)
		except Exception:
			pass

	@script(
		description="Sale de la capa de órdenes del Monitor de recursos",
		category=CATEGORY,
		allowInSleepMode=True,
	)
	def script_layerExit(self, gesture) -> None:
		self._finishLayer()
		from tiresias.audio import tones

		tones.beep(120, 100)

	# ================================================================ presentación
	def _report(self, getter: Callable[[], str], failure: str | None = None) -> None:
		"""Obtiene la información (en un hilo) y la anuncia; dos pulsaciones la copian."""
		repeat = _repeatCount()

		def work() -> None:
			try:
				text, ok = getter(), True
			except Exception:
				log.debug("Error obteniendo la información de recursos", exc_info=True)
				text, ok = failure or "No se pudo obtener la información.", False
			if self.runInThread:
				queue_handler.queueFunction(self._present, text, repeat, ok)
			else:
				self._present(text, repeat, ok)

		if self.runInThread:
			threading.Thread(target=work, name="resourceMonitor", daemon=True).start()
		else:
			work()

	def _present(self, text: str, repeat: int, ok: bool = True) -> None:
		if self._terminated:
			return
		if repeat == 0 or not ok:
			_speak(text)
			return
		if isSecureContext():
			_speak("No se puede copiar la información al portapapeles en una pantalla segura.")
			return
		from tiresias import api, speech

		with speech.allowOnDemand():
			api.copyToClip(text, notify=True)

	# ================================================================ órdenes
	@script(
		description="Anuncia la RAM utilizada, la carga media del procesador y la batería si la hay. Pulsado dos veces, copia la información al portapapeles",
		category=CATEGORY,
		speakOnDemand=True,
	)
	def script_announceResourceSummary(self, gesture) -> None:
		self._report(info.getSummary)

	@script(
		description="Anuncia la carga media del procesador y la de cada núcleo. Pulsado dos veces, copia la información al portapapeles",
		gesture="kb:tiresias+shift+1",
		category=CATEGORY,
		speakOnDemand=True,
	)
	def script_announceProcessorInfo(self, gesture) -> None:
		self._report(info.getCpuInfo)

	@script(
		description="Anuncia el espacio utilizado y total de la RAM física y virtual. Pulsado dos veces, copia la información al portapapeles",
		gestures=("kb:tiresias+shift+2", "kb:tiresias+shift+5"),
		category=CATEGORY,
		speakOnDemand=True,
	)
	def script_announceRamInfo(self, gesture) -> None:
		self._report(info.getRamInfo)

	@script(
		description="Anuncia el espacio utilizado y total de las unidades fijas, extraíbles y de red. Pulsado dos veces, copia la información al portapapeles",
		gesture="kb:tiresias+shift+3",
		category=CATEGORY,
		speakOnDemand=True,
	)
	def script_announceDriveInfo(self, gesture) -> None:
		self._report(info.getDriveInfo)

	def getWlanInfo(self) -> str:
		client = self._wlan
		if client is None:
			return wlan.NO_DEVICES
		return client.getInfo()

	@script(
		description="Anuncia el nombre de la red inalámbrica (SSID), la intensidad de la señal y el tipo de seguridad. Pulsado dos veces, copia la información al portapapeles",
		gesture="kb:tiresias+shift+4",
		category=CATEGORY,
		speakOnDemand=True,
	)
	def script_wlanStatusReport(self, gesture) -> None:
		self._report(self.getWlanInfo, wlan.ERROR_MESSAGE)

	@script(
		description="Anuncia la versión de Windows, la arquitectura y la compilación. Pulsado dos veces, copia la información al portapapeles",
		gesture="kb:tiresias+shift+6",
		category=CATEGORY,
		speakOnDemand=True,
	)
	def script_announceWinVer(self, gesture) -> None:
		self._report(info.getWinVer)

	@script(
		description="Anuncia el tiempo de actividad del sistema. Pulsado dos veces, copia la información al portapapeles",
		gesture="kb:tiresias+shift+7",
		category=CATEGORY,
		speakOnDemand=True,
	)
	def script_announceUptime(self, gesture) -> None:
		self._report(info.getUptime, "No se pudo obtener el tiempo de actividad del sistema.")

	@script(
		description="Anuncia el uso y la temperatura de la GPU (no disponible en modo seguro). Pulsado dos veces, copia la información al portapapeles",
		category=CATEGORY,
		speakOnDemand=True,
	)
	def script_announceGpuInfo(self, gesture) -> None:
		# Los datos de NVIDIA vienen de otro programa: no se consultan en modo seguro.
		if isSecureMode():
			_speak("Esta función no está disponible en modo seguro.")
			return
		providers = list(self._gpuProviders)
		self._report(lambda: gpu.getGpuInfo(providers, options.get("gpuTempUnit")), "Error al obtener la información de la GPU.")

	@script(
		description="Anuncia el uso de la memoria de la GPU (no disponible en modo seguro). Pulsado dos veces, copia la información al portapapeles",
		category=CATEGORY,
		speakOnDemand=True,
	)
	def script_announceGpuMemoryInfo(self, gesture) -> None:
		if isSecureMode():
			_speak("Esta función no está disponible en modo seguro.")
			return
		providers = list(self._gpuProviders)
		self._report(lambda: gpu.getGpuMemoryInfo(providers), "Error al obtener la información de la memoria de la GPU.")

	@script(
		description="Anuncia el porcentaje de la batería, si se está cargando, el tiempo restante y un aviso si está baja o en nivel crítico. Pulsado dos veces, copia la información al portapapeles",
		category=CATEGORY,
		speakOnDemand=True,
	)
	def script_announceBatteryInfo(self, gesture) -> None:
		self._report(info.getBatteryInfo)

	# ================================================================ avisos de la wifi
	def _onWlanEvent(self, kind: str, ssid: str) -> None:
		"""Llega en un hilo del servicio WLAN: se pasa al núcleo."""
		if self._terminated:
			return
		queue_handler.queueFunction(self.notifyWifi, kind, ssid)

	def notifyWifi(self, kind: str, ssid: str = "") -> None:
		if self._terminated or kind not in WIFI_MESSAGES:
			return
		template, fileName = WIFI_MESSAGES[kind]
		mode = options.get("wifiStatusNotification")
		if mode in ("message", "both"):
			from tiresias import speech

			speech.speakMessage(template.format(ssid=ssid))
		if mode in ("sound", "both"):
			path = os.path.join(MODULE_DIR, fileName)
			if os.path.isfile(path):
				from tiresias.audio import tones

				tones.playWaveFile(path)
