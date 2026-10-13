"""Opciones del Monitor de recursos (sección ``resourceMonitor`` de la configuración)."""

from __future__ import annotations

SECTION = "resourceMonitor"
#: Identificador de la categoría en el cuadro de Opciones.
PANEL_ID = "resourceMonitor"
PANEL_TITLE = "Monitor de recursos"

DEFAULTS = {
	# Unidad de la temperatura de la GPU: «celsius» o «fahrenheit».
	"gpuTempUnit": "celsius",
	# Aviso de conexión y desconexión de la wifi: «off», «message», «sound» o «both».
	"wifiStatusNotification": "both",
}

GPU_TEMP_UNITS = [("celsius", "Celsius"), ("fahrenheit", "Fahrenheit")]
WIFI_NOTIFICATIONS = [
	("off", "Desactivado"),
	("message", "Mensaje"),
	("sound", "Sonido"),
	("both", "Mensaje y sonido"),
]


def registerDefaults() -> None:
	from tiresias.config import conf

	conf.registerDefaults(SECTION, DEFAULTS)


def get(key: str):
	"""Valor de una opción (el de fábrica si el guardado no es válido)."""
	from tiresias.config import conf

	try:
		value = conf[SECTION][key]
	except KeyError:
		return DEFAULTS[key]
	valid = {"gpuTempUnit": GPU_TEMP_UNITS, "wifiStatusNotification": WIFI_NOTIFICATIONS}.get(key)
	if valid is not None and value not in [v for v, _l in valid]:
		return DEFAULTS[key]
	return value


def panelClass():
	"""Categoría «Monitor de recursos» del cuadro de Opciones (se crea al usarla: necesita wx)."""
	from tiresias.gui import settings as S

	class ResourceMonitorPanel(S.ConfigPanel):
		title = PANEL_TITLE
		section = SECTION
		fields = [
			S.Choice("gpuTempUnit", "Unidad de &temperatura de la GPU:", GPU_TEMP_UNITS),
			S.Choice("wifiStatusNotification", "Aviso de conexión y desconexión de la &wifi:", WIFI_NOTIFICATIONS),
		]

	return ResourceMonitorPanel


def registerPanel() -> None:
	from tiresias.gui import settings as S

	cls = panelClass()
	S.registerPanel(PANEL_ID, PANEL_TITLE, cls)


def unregisterPanel() -> None:
	from tiresias.gui import settings as S

	S.unregisterPanel(PANEL_ID)
