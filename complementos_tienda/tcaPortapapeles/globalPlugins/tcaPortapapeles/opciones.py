"""Opciones de TCA-Portapapeles (sección ``tcaPortapapeles`` de la configuración)."""

from __future__ import annotations

SECCION = "tcaPortapapeles"
#: Identificador de la categoría en el cuadro de Opciones.
PANEL_ID = "tcaPortapapeles"
PANEL_TITULO = "TCA-Portapapeles"

#: Intervalos del monitor del portapapeles (milisegundos), como en el original.
INTERVALOS = [
	(100, "1 décima de segundo"),
	(200, "2 décimas de segundo"),
	(300, "3 décimas de segundo"),
	(400, "4 décimas de segundo"),
	(500, "5 décimas de segundo"),
	(1000, "1 segundo"),
]

#: Idiomas de destino de la traducción del modo juego (los del original).
IDIOMAS = [
	("de", "Alemán"),
	("ar", "Árabe"),
	("hr", "Croata"),
	("es", "Español"),
	("fr", "Francés"),
	("en", "Inglés"),
	("it", "Italiano"),
	("pl", "Polaco"),
	("pt", "Portugués"),
	("ru", "Ruso"),
	("tr", "Turco"),
	("uk", "Ucraniano"),
]

#: Acciones de las teclas del portapapeles: (clave de la opción, acción, etiqueta).
TECLAS = [
	("teclasSeleccionarTodo", "selectAll", "Teclas de &seleccionar todo:"),
	("teclasCopiar", "copy", "Teclas de &copiar:"),
	("teclasCortar", "cut", "Teclas de c&ortar:"),
	("teclasPegar", "paste", "Teclas de &pegar:"),
	("teclasDeshacer", "undo", "Teclas de &deshacer:"),
	("teclasRehacer", "redo", "Teclas de &rehacer:"),
]

DEFAULTS = {
	# Anuncios de las teclas del portapapeles (se activan y desactivan con la capa).
	"activado": True,
	"voz": True,
	"audio": True,
	# Historial propio (con formatos y archivos) y su monitor.
	"historial": True,
	"intervalo": 200,
	"sonidoHistorial": True,
	# El original lo traía activado; aquí no, porque Tiresias ya anuncia lo copiado.
	"vozCopiado": False,
	# Modo juego: traduce lo que llega al portapapeles.
	"modoJuego": False,
	"intervaloJuego": 200,
	"idiomaJuego": "es",
	# Teclas que disparan cada anuncio (distribuciones de teclado distintas).
	"teclasSeleccionarTodo": ["control+a", "control+e"],
	"teclasCopiar": ["control+c"],
	"teclasCortar": ["control+x"],
	"teclasPegar": ["control+v"],
	"teclasDeshacer": ["control+z"],
	"teclasRehacer": ["control+y"],
}

_VALIDAS = {
	"intervalo": [v for v, _l in INTERVALOS],
	"intervaloJuego": [v for v, _l in INTERVALOS],
	"idiomaJuego": [v for v, _l in IDIOMAS],
}


def registerDefaults() -> None:
	from tiresias.config import conf

	conf.registerDefaults(SECCION, DEFAULTS)


def get(clave: str):
	"""Valor de una opción (el de fábrica si el guardado no es válido)."""
	from tiresias.config import conf

	try:
		valor = conf[SECCION][clave]
	except KeyError:
		return DEFAULTS[clave]
	validas = _VALIDAS.get(clave)
	if validas is not None and valor not in validas:
		return DEFAULTS[clave]
	defecto = DEFAULTS[clave]
	if isinstance(defecto, bool):
		return bool(valor)
	if isinstance(defecto, list):
		if isinstance(valor, str):
			valor = [p for p in valor.split(",")]
		if not isinstance(valor, (list, tuple)):
			return list(defecto)
		return [str(v).strip() for v in valor if str(v).strip()]
	return valor


def guardar(clave: str, valor) -> None:
	from tiresias.config import conf

	conf[SECCION][clave] = valor


def nombreIdioma(codigo: str) -> str:
	return dict(IDIOMAS).get(codigo, codigo)


def panelClass():
	"""Categoría «TCA-Portapapeles» del cuadro de Opciones (se crea al usarla: necesita wx)."""
	from tiresias.gui import settings as S

	class PanelTCAPortapapeles(S.ConfigPanel):
		title = PANEL_TITULO
		section = SECCION
		fields = [
			S.Bool("activado", "&Activar los anuncios de las teclas del portapapeles", group="Anuncios"),
			S.Bool("voz", "Anunciar con &voz las teclas del portapapeles", group="Anuncios"),
			S.Bool("audio", "Reproducir &sonidos al usar las teclas del portapapeles", group="Anuncios"),
			S.Bool("historial", "Activar el &historial de TCA-Portapapeles", group="Historial"),
			S.Choice("intervalo", "&Tiempo de actualización del monitor del portapapeles:", INTERVALOS, group="Historial"),
			S.Bool("sonidoHistorial", "&Notificar con un sonido cada vez que se agregue algo al historial", group="Historial"),
			S.Bool("vozCopiado", "&Leer el texto completo de lo que se agrega al historial", group="Historial"),
			S.Choice("intervaloJuego", "Tiempo de actualización del monitor del portapapeles en el &modo juego:", INTERVALOS, group="Modo juego"),
			S.Choice("idiomaJuego", "&Idioma de destino de la traducción en el modo juego:", IDIOMAS, group="Modo juego"),
		] + [S.ListText(clave, etiqueta, group="Teclas del portapapeles (separadas por comas)") for clave, _a, etiqueta in TECLAS]

		def afterSave(self, changes) -> None:
			from tiresias import queue_handler

			plugin = _pluginActivo
			if plugin is not None:
				queue_handler.queueFunction(plugin.aplicarOpciones)

	return PanelTCAPortapapeles


#: Complemento en marcha (para aplicar las opciones al guardarlas).
_pluginActivo = None


def registerPanel(plugin=None) -> None:
	global _pluginActivo
	from tiresias.gui import settings as S

	_pluginActivo = plugin
	S.registerPanel(PANEL_ID, PANEL_TITULO, panelClass())


def unregisterPanel() -> None:
	global _pluginActivo
	from tiresias.gui import settings as S

	_pluginActivo = None
	S.unregisterPanel(PANEL_ID)
