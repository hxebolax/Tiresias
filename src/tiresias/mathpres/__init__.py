"""Matemáticas en Tiresias: lectura, braille y navegación de fórmulas.

Motor propio (sin MathCAT):

- :mod:`.mathml`: análisis tolerante y normalización de MathML.
- :mod:`.content`: MathML de contenido a presentación.
- :mod:`.latex`: LaTeX → MathML y MathML → LaTeX.
- :mod:`.omml`: ecuaciones de Word (OMML) → MathML.
- :mod:`.speech_es`: lectura natural en español (estilos natural y estructural).
- :mod:`.braille_cmu`: signografía matemática española (CMU de la ONCE).
- :mod:`.navigation`: navegación por la estructura de la fórmula.
- :mod:`.providers`: obtención del MathML (navegadores, Word, portapapeles).
- :mod:`.interaction`: modo de exploración interactiva de una fórmula.

API principal::

	from tiresias import mathpres
	text = mathpres.getSpeechText("<math>...</math>")
	cells = mathpres.getBrailleCells("<math>...</math>")
	mathpres.interactWithMathMl("<math>...</math>")
"""

from __future__ import annotations

from ..config import conf
from ..log import getLogger

log = getLogger("mathpres")

#: Valores por defecto de la sección ``math`` de la configuración.
DEFAULTS = {
	# breve, normal o detallado
	"verbosity": "normal",
	# natural (al estilo ClearSpeak) o estructural (al estilo MathSpeak)
	"style": "natural",
	# Decir «mayúscula» detrás de las letras mayúsculas.
	"sayCapitals": True,
	# Hacer pausas en la lectura (en los cambios de estructura).
	"pauses": True,
	# Cómo se presentan las fórmulas en modo exploración: «speech» (se leen
	# como texto en la línea) o «interactive» (se anuncian y se exploran con
	# Intro o con la orden de explorar).
	"browseMode": "speech",
	# Anunciar «matemáticas» antes de cada fórmula en modo exploración.
	"announceMathRole": True,
	# Mostrar las fórmulas en braille matemático (CMU) en lugar del texto.
	"brailleMath": True,
	# Formato de Control+C en la exploración: mathml, latex o text.
	"copyFormat": "mathml",
	# Al entrar en una fórmula, leerla completa.
	"speakOnEnter": True,
}
conf.registerDefaults("math", DEFAULTS)


def options():
	"""Opciones de voz según la configuración actual."""
	from .speech_es import SpeechOptions

	m = conf["math"]
	verbosity = m["verbosity"] if m["verbosity"] in ("breve", "normal", "detallado") else "normal"
	style = m["style"] if m["style"] in ("natural", "estructural") else "natural"
	return SpeechOptions(verbosity=verbosity, style=style, sayCapitals=bool(m["sayCapitals"]))


def parse(mathMl: str):
	from . import mathml

	return mathml.parse(mathMl)


def getSpeechForMathMl(mathMl: str) -> list:
	"""Secuencia de voz (cadenas y órdenes de pausa) para un MathML."""
	from . import speech_es

	tree = parse(mathMl)
	return speech_es.toSpeechSequence(speech_es.speakNode(tree, options()), conf["math"]["pauses"])


def getSpeechText(mathMl: str, pauses: bool = True) -> str:
	"""Texto hablado (las pausas se escriben como comas)."""
	from . import speech_es

	return speech_es.toText(speech_es.speakNode(parse(mathMl), options()), pauses)


def getBrailleCells(mathMl: str) -> list[int]:
	from . import braille_cmu

	return braille_cmu.translate(parse(mathMl)).cells


def getBrailleForMathMl(mathMl: str) -> str:
	"""Braille matemático (CMU) como caracteres Unicode braille."""
	from . import braille_cmu

	return braille_cmu.toUnicode(getBrailleCells(mathMl))


def mathMlFromLatex(latex: str) -> str:
	from . import latex as latexMod

	return latexMod.latexToMathML(latex)


def interactWithMathMl(mathMl: str, sourceObj=None) -> None:
	"""Empieza a explorar una fórmula (llamar desde una orden, en el núcleo)."""
	from . import interaction

	interaction.start(mathMl, sourceObj)


def isInteracting() -> bool:
	from . import interaction

	return interaction.getInteractor() is not None


_initialized = False


def initialize() -> None:
	"""Registra el complemento incorporado y el panel de opciones."""
	global _initialized
	if _initialized:
		return
	_initialized = True
	from ..plugins import handler as pluginHandler
	from .plugin import MathGlobalPlugin

	pluginHandler.registerBuiltin(MathGlobalPlugin)
	try:
		from .settings_panel import registerPanel

		registerPanel()
	except Exception:
		log.exception("No se pudo registrar el panel de matemáticas")
