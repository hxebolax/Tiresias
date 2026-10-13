"""Órdenes y enganches del núcleo de voz y lectura.

Se registra como complemento global incorporado (:func:`initialize`, antes
de cargar los complementos) y aporta:

- leer todo en una fila o columna de tabla;
- teclas de navegación durante la lectura continua (opción
  ``speech/sayAllNavigationKeys``): Re Pág y Av Pág cambian la velocidad
  (propia de la lectura continua, solo de esa lectura o de la voz, según
  ``speech/sayAllRateMode``), flechas izquierda y derecha saltan frases,
  arriba y abajo párrafos, sin detener la lectura (#4944, foros 2.1);
- conmutadores de voz sin gesto asignado (se asignan en Gestos de entrada o
  se usan desde la paleta de órdenes);
- enganches: voz obsoleta al cambiar el foco, fin de la palabra del eco de
  teclado al ejecutar órdenes de movimiento.
"""

from __future__ import annotations

from ..baseobject import script
from ..config import conf
from ..i18n import _
from ..log import getLogger
from ..plugins import GlobalPlugin
from . import api as speech

log = getLogger("speech.plugin")

CAT_SPEECH = _("Voz")

#: Teclas activas solo durante la lectura continua (si la opción está activada).
SAYALL_KEYS = {
	"kb:pageup": "sayAllFaster",
	"kb:pagedown": "sayAllSlower",
	"kb:rightarrow": "sayAllNextSentence",
	"kb:leftarrow": "sayAllPreviousSentence",
	"kb:downarrow": "sayAllNextParagraph",
	"kb:uparrow": "sayAllPreviousParagraph",
}


def _noInterrupt(func):
	func.noSpeechInterrupt = True
	return func


def _cycleSetting(key: str, values: list[tuple[str, str]], section: str = "speech") -> None:
	cur = conf[section][key]
	keys = [v for v, _l in values]
	i = keys.index(cur) if cur in keys else -1
	nxt = values[(i + 1) % len(values)]
	conf[section][key] = nxt[0]
	speech.speakMessage(nxt[1])


NUMBER_LABELS = [
	("full", _("números completos")),
	("digits", _("números dígito a dígito")),
	("pairs", _("números por pares")),
	("triples", _("números por grupos de tres")),
]
DETECTION_LABELS = [
	("off", _("detección de idioma desactivada")),
	("script", _("detección de idioma por alfabeto")),
	("full", _("detección de idioma por alfabeto y por palabras")),
]
CAPITALS_LABELS = [
	("off", _("mayúsculas en lectura continua desactivadas")),
	("initial", _("indicar palabras que empiezan por mayúscula")),
	("allCaps", _("indicar palabras en mayúsculas")),
]
SAYALL_UNIT_LABELS = [
	("line", _("leer todo por líneas")),
	("sentence", _("leer todo por frases")),
	("paragraph", _("leer todo por párrafos")),
]


class SpeechGlobalPlugin(GlobalPlugin):
	scriptCategory = CAT_SPEECH

	def getScript(self, gesture):
		from . import sayall

		if conf["speech"]["sayAllNavigationKeys"] and sayall.isRunning():
			for gid in getattr(gesture, "identifiers", ()):
				gid = gid.lower()
				name = SAYALL_KEYS.get(gid) or SAYALL_KEYS.get("kb:" + gid.split(":", 1)[-1] if gid.startswith("kb(") else "")
				if name:
					return getattr(self, "script_" + name)
		return super().getScript(gesture)

	# ------------------------------------------------------------ tablas
	@script(description=_("Lee la columna de la tabla desde la celda actual hacia abajo (lectura continua en tabla)"), category=CAT_SPEECH, gesture="kb:tiresias+control+alt+downArrow", speakOnDemand=True)
	def script_sayAllInTableColumn(self, gesture) -> None:
		from . import sayall

		sayall.readTable(1, 0)

	@script(description=_("Lee la fila de la tabla desde la celda actual hacia la derecha (lectura continua en tabla)"), category=CAT_SPEECH, gesture="kb:tiresias+control+alt+rightArrow", speakOnDemand=True)
	def script_sayAllInTableRow(self, gesture) -> None:
		from . import sayall

		sayall.readTable(0, 1)

	# ------------------------------------------------------------ lectura continua
	def _changeRate(self, direction: int) -> None:
		from . import sayall

		# Velocidad propia de la lectura continua, solo de esta lectura o de la
		# voz, según speech/sayAllRateMode (foros 2.1).
		sayall.changeRate(direction)

	@_noInterrupt
	@script(description=_("Durante la lectura continua: aumenta la velocidad sin detener la lectura"), category=CAT_SPEECH)
	def script_sayAllFaster(self, gesture) -> None:
		from . import sayall

		if sayall.isRunning():
			self._changeRate(1)
		else:
			gesture.send() if hasattr(gesture, "send") else None

	@_noInterrupt
	@script(description=_("Durante la lectura continua: reduce la velocidad sin detener la lectura"), category=CAT_SPEECH)
	def script_sayAllSlower(self, gesture) -> None:
		from . import sayall

		if sayall.isRunning():
			self._changeRate(-1)
		else:
			gesture.send() if hasattr(gesture, "send") else None

	def _skip(self, gesture, unit: str, direction: int) -> None:
		from . import sayall

		if not sayall.isRunning():
			if hasattr(gesture, "send"):
				gesture.send()
			return
		sayall.skip(unit, direction)

	@_noInterrupt
	@script(description=_("Durante la lectura continua: salta a la frase siguiente sin detener la lectura"), category=CAT_SPEECH)
	def script_sayAllNextSentence(self, gesture) -> None:
		from .. import textinfo

		self._skip(gesture, textinfo.UNIT_SENTENCE, 1)

	@_noInterrupt
	@script(description=_("Durante la lectura continua: vuelve a la frase anterior sin detener la lectura"), category=CAT_SPEECH)
	def script_sayAllPreviousSentence(self, gesture) -> None:
		from .. import textinfo

		self._skip(gesture, textinfo.UNIT_SENTENCE, -1)

	@_noInterrupt
	@script(description=_("Durante la lectura continua: salta al párrafo siguiente sin detener la lectura"), category=CAT_SPEECH)
	def script_sayAllNextParagraph(self, gesture) -> None:
		from .. import textinfo

		self._skip(gesture, textinfo.UNIT_PARAGRAPH, 1)

	@_noInterrupt
	@script(description=_("Durante la lectura continua: vuelve al párrafo anterior sin detener la lectura"), category=CAT_SPEECH)
	def script_sayAllPreviousParagraph(self, gesture) -> None:
		from .. import textinfo

		self._skip(gesture, textinfo.UNIT_PARAGRAPH, -1)

	# ------------------------------------------------------------ conmutadores
	@script(description=_("Cambia la forma de leer los números: completos, dígito a dígito, por pares o por grupos de tres"), category=CAT_SPEECH)
	def script_cycleNumberReading(self, gesture) -> None:
		_cycleSetting("numberReading", NUMBER_LABELS)

	@script(description=_("Activa o desactiva la lectura alfanumérica (separar letras y números)"), category=CAT_SPEECH)
	def script_toggleSplitAlphanumeric(self, gesture) -> None:
		val = not conf["speech"]["splitAlphanumeric"]
		conf["speech"]["splitAlphanumeric"] = val
		speech.speakMessage(_("lectura alfanumérica activada") if val else _("lectura alfanumérica desactivada"))

	@script(description=_("Cambia la detección automática del idioma: desactivada, por alfabeto, o por alfabeto y palabras"), category=CAT_SPEECH)
	def script_cycleLanguageDetection(self, gesture) -> None:
		_cycleSetting("languageDetection", DETECTION_LABELS)

	@script(description=_("Activa o desactiva el anuncio del idioma al cambiar de idioma"), category=CAT_SPEECH)
	def script_toggleReportLanguage(self, gesture) -> None:
		val = not conf["speech"]["reportLanguage"]
		conf["speech"]["reportLanguage"] = val
		speech.speakMessage(_("anunciar idioma activado") if val else _("anunciar idioma desactivado"))

	@script(description=_("Cambia cómo se indican las mayúsculas en la lectura continua"), category=CAT_SPEECH)
	def script_cycleCapitalsInSayAll(self, gesture) -> None:
		_cycleSetting("capitalsInSayAll", CAPITALS_LABELS)

	@script(description=_("Cambia la unidad de la lectura continua: por líneas, por frases o por párrafos"), category=CAT_SPEECH)
	def script_cycleSayAllUnit(self, gesture) -> None:
		# foros 2.1: leer todo por frase o por párrafo, como en JAWS.
		_cycleSetting("sayAllUnit", SAYALL_UNIT_LABELS)

	@script(description=_("Cambia el nivel de verbosidad: principiante, intermedio o experto"), category=CAT_SPEECH)
	def script_cycleVerbosity(self, gesture) -> None:
		from . import verbosity

		cur = verbosity.level()
		keys = [k for k, _l in verbosity.LEVEL_CHOICES]
		nxt = verbosity.LEVEL_CHOICES[(keys.index(cur) + 1) % len(keys)]
		conf["presentation"]["verbosity"] = nxt[0]
		speech.speakMessage(_("verbosidad {level}").format(level=nxt[1].lower()))

	@script(description=_("Cambia el esquema de voz y sonido"), category=CAT_SPEECH)
	def script_cycleVoiceScheme(self, gesture) -> None:
		from . import voice_schemes

		_cycleSetting("voiceScheme", [(k, _("esquema {name}").format(name=lbl)) for k, lbl in voice_schemes.schemeChoices()])

	@script(description=_("Activa o desactiva las voces por contexto (cursor, revisión, teclado, mensajes, menús y diálogos)"), category=CAT_SPEECH)
	def script_toggleVoiceContexts(self, gesture) -> None:
		val = not conf["speech"]["voiceContexts"]
		conf["speech"]["voiceContexts"] = val
		speech.speakMessage(_("voces por contexto activadas") if val else _("voces por contexto desactivadas"))

	@script(description=_("Activa o desactiva el esquema de voz y sonido fuera del modo exploración (controles y texto editable)"), category=CAT_SPEECH)
	def script_toggleVoiceSchemeEverywhere(self, gesture) -> None:
		# foros 2.4: el esquema también en los controles y el texto editable.
		val = not conf["speech"]["voiceSchemeEverywhere"]
		conf["speech"]["voiceSchemeEverywhere"] = val
		speech.speakMessage(_("esquema de voz también fuera del modo exploración") if val else _("esquema de voz solo en el modo exploración"))

	@script(description=_("Cambia los mensajes de tutor: desactivados, solo controles complejos o todos"), category=CAT_SPEECH)
	def script_cycleTutorMessages(self, gesture) -> None:
		_cycleSetting(
			"tutorMessages",
			[("off", _("mensajes de tutor desactivados")), ("complex", _("mensajes de tutor en controles complejos")), ("all", _("mensajes de tutor en todos los controles"))],
			section="presentation",
		)


# ---------------------------------------------------------------------- enganches
def _onFocusChange(obj=None) -> None:
	try:
		speech.cancelExpiredSpeech()
	except Exception:
		log.debug("Error descartando voz obsoleta", exc_info=True)


def _onScriptExecuted(script=None, gesture=None) -> None:
	# Una orden (mover el cursor, cambiar de control...) termina la palabra
	# que se estaba escribiendo: el eco no debe unir lo anterior con lo nuevo.
	try:
		from .. import typing_echo

		typing_echo.resetWord()
	except Exception:
		pass


_initialized = False


def initialize() -> None:
	"""Registra el complemento y los enganches (hilo del núcleo, una vez)."""
	global _initialized
	if _initialized:
		return
	_initialized = True
	from .. import api
	from ..input import core as inputCore
	from ..plugins import handler as pluginHandler

	# speech.reportNumbersAsDigits pasa a speech.numberReading en config/migrations.py (v3).
	pluginHandler.registerBuiltin(SpeechGlobalPlugin)
	api.post_focusChange.register(_onFocusChange)
	inputCore.post_scriptExecuted.register(_onScriptExecuted)
	try:
		from ..gui import speech_settings

		speech_settings.registerPanels()
	except Exception:
		log.exception("No se pudieron registrar los paneles de voz")
