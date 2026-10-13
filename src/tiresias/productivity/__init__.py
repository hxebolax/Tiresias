"""Funciones de productividad de Tiresias.

- :mod:`.text_analyzer`: incoherencias de escritura (paréntesis sin cerrar,
  espacios dobles, mayúsculas tras punto, formato...), con orden para saltar
  a la siguiente/anterior y aviso sonoro opcional al pasar por una línea.
- :mod:`.notifications`: historial de notificaciones, avisos de Windows y
  regiones vivas, con reglas por aplicación y expresión regular.
- :mod:`.watch`: vigilancia de objetos o regiones de pantalla.
- :mod:`.window_find`: buscar texto en cualquier ventana.
- :mod:`.text_bookmarks`: marcadores de posición en cualquier texto.
- :mod:`.plugin`: órdenes y manejo de eventos (complemento incorporado).

Las opciones están en las secciones ``textAnalyzer``, ``notifications``,
``watch`` y ``windowFind`` y en el panel «Productividad» de Opciones.
"""

from __future__ import annotations

import os

from ..log import getLogger

log = getLogger("productivity")

TEXT_ANALYZER_DEFAULTS = {
	"brackets": True,
	"quotes": True,
	"spanishMarks": True,
	"doubleSpace": True,
	"spaceBeforePunct": True,
	"lowercaseAfterPeriod": True,
	"repeatedWord": True,
	"mixedCase": False,
	"format": True,
	# Al moverse por líneas: sonido y/o descripción de las incidencias.
	"lineSound": False,
	"lineSpeak": False,
}

NOTIFICATIONS_DEFAULTS = {
	"keepHistory": True,
	"historySize": 300,
	"recordNotifications": True,
	"recordToasts": True,
	"recordLiveRegions": True,
	"applyRules": True,
}

WATCH_DEFAULTS = {
	"maxWatches": 5,
	"intervalMs": 1000,
	"playSound": True,
	"onlyNewText": True,
	"onlyWhenAppInForeground": False,
	"announceSlot": True,
	"showInBraille": False,
}

WINDOW_FIND_DEFAULTS = {
	"moveFocus": True,
	"caseSensitive": False,
	"includeOffscreen": True,
}

_initialized = False
notificationStore = None
watchManager = None
windowFinder = None
bookmarkStore = None


def registerDefaults() -> None:
	from ..config import conf

	conf.registerDefaults("textAnalyzer", TEXT_ANALYZER_DEFAULTS)
	conf.registerDefaults("notifications", NOTIFICATIONS_DEFAULTS)
	conf.registerDefaults("watch", WATCH_DEFAULTS)
	conf.registerDefaults("windowFind", WINDOW_FIND_DEFAULTS)
	# El panel «Programas externos» se registra aquí: sus opciones deben existir
	# aunque la API de control no haya podido arrancar.
	from .. import controller

	controller.registerDefaults()


def rulesFile() -> str:
	from .. import paths

	return os.path.join(paths.configDir(), "reglas_notificaciones.json")


def bookmarksFile() -> str:
	from .. import paths

	return os.path.join(paths.configDir(), "marcadores_texto.json")


def _registerSounds() -> None:
	from ..audio import tones

	tones.registerSound("textIssue", [(330, 35), (0, 15), (262, 45)])
	tones.registerSound("watchChange", [(784, 40), (988, 40), (784, 40)])


def initialize() -> None:
	"""Prepara los módulos (hilo del núcleo, antes de cargar los complementos)."""
	global _initialized, notificationStore, watchManager, windowFinder, bookmarkStore
	if _initialized:
		return
	from ..config import conf
	from ..plugins import handler as pluginHandler
	from .notifications import NotificationStore
	from .plugin import ProductivityGlobalPlugin
	from .text_bookmarks import BookmarkStore
	from .watch import WatchManager
	from .window_find import WindowFinder

	registerDefaults()
	_registerSounds()
	notificationStore = NotificationStore(rulesFile(), conf["notifications"]["historySize"])
	notificationStore.loadRules()
	watchManager = WatchManager()
	windowFinder = WindowFinder()
	bookmarkStore = BookmarkStore(bookmarksFile())
	pluginHandler.registerBuiltin(ProductivityGlobalPlugin)
	try:
		from ..gui import productivity_dialogs

		productivity_dialogs.registerSettingsPanels()
	except Exception:
		log.exception("No se pudieron registrar los paneles de productividad")
	_initialized = True


def terminate() -> None:
	global _initialized
	if watchManager is not None:
		watchManager.clear()
	_initialized = False
