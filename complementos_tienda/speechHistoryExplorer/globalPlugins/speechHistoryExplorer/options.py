"""Opciones del Explorador del historial de voz (sección ``speechHistoryExplorer`` de la configuración).

El tamaño máximo del historial no es una opción propia: es la de Tiresias
(``conf["speech"]["speechHistorySize"]``, categoría Voz de las Opciones). El
panel del complemento la muestra también, leyendo y escribiendo esa misma
opción, para que esté a mano como en el complemento original de NVDA.
"""

from __future__ import annotations

SECTION = "speechHistoryExplorer"
#: Identificador de la categoría en el cuadro de Opciones.
PANEL_ID = "speechHistoryExplorer"
PANEL_TITLE = "Explorador del historial de voz"

#: Sección y clave de la opción de Tiresias con el tamaño del historial de voz.
HISTORY_SIZE_SECTION = "speech"
HISTORY_SIZE_KEY = "speechHistorySize"
HISTORY_SIZE_MIN = 10
HISTORY_SIZE_MAX = 10000

DEFAULTS = {
	# Quitar los espacios en blanco del principio del texto al copiarlo.
	"trimWhitespaceFromStart": False,
	# Quitar los espacios en blanco del final del texto al copiarlo.
	"trimWhitespaceFromEnd": True,
	# Pitar al copiar y al llegar al principio o al final del historial.
	"beepWhenPerformingActions": True,
	# El pitido de los extremos suena a la izquierda (no hay más antiguos) o a la derecha (no hay más recientes).
	"beepPanning": True,
}

#: Etiquetas de las opciones (con tecla de acceso) tal como salen en el panel.
LABELS = {
	HISTORY_SIZE_KEY: "Número &máximo de elementos del historial (opción «Tamaño del historial de voz» de Tiresias):",
	"trimWhitespaceFromStart": "Recortar los espacios del &principio al copiar el texto",
	"trimWhitespaceFromEnd": "Recortar los espacios del &final al copiar el texto",
	"beepWhenPerformingActions": "Pitar al realizar &acciones",
	"beepPanning": "Pitido a la &izquierda o a la derecha cuando no hay más elementos anteriores o siguientes",
}


def registerDefaults() -> None:
	from tiresias.config import conf

	conf.registerDefaults(SECTION, DEFAULTS)


def get(key: str) -> bool:
	"""Valor de una opción propia (el de fábrica si el guardado no es válido)."""
	from tiresias.config import conf

	try:
		value = conf[SECTION][key]
	except KeyError:
		return DEFAULTS[key]
	if not isinstance(value, bool):
		return DEFAULTS[key]
	return value


def getHistorySize() -> int:
	"""Tamaño máximo del historial de voz de Tiresias."""
	from tiresias.config import conf

	try:
		return int(conf[HISTORY_SIZE_SECTION][HISTORY_SIZE_KEY])
	except (KeyError, TypeError, ValueError):
		return 500


def panelClass():
	"""Categoría «Explorador del historial de voz» del cuadro de Opciones (se crea al usarla: necesita wx)."""
	from tiresias.gui import settings as S

	class SpeechHistoryExplorerPanel(S.ConfigPanel):
		title = PANEL_TITLE
		section = SECTION
		fields = [
			S.Int(HISTORY_SIZE_KEY, LABELS[HISTORY_SIZE_KEY], HISTORY_SIZE_MIN, HISTORY_SIZE_MAX, section=HISTORY_SIZE_SECTION),
			S.Bool("trimWhitespaceFromStart", LABELS["trimWhitespaceFromStart"]),
			S.Bool("trimWhitespaceFromEnd", LABELS["trimWhitespaceFromEnd"]),
			S.Bool("beepWhenPerformingActions", LABELS["beepWhenPerformingActions"]),
			S.Bool("beepPanning", LABELS["beepPanning"]),
		]

	return SpeechHistoryExplorerPanel


def registerPanel() -> None:
	from tiresias.gui import settings as S

	S.registerPanel(PANEL_ID, PANEL_TITLE, panelClass())


def unregisterPanel() -> None:
	from tiresias.gui import settings as S

	S.unregisterPanel(PANEL_ID)
