"""Importador de la configuración de NVDA.

Lee la configuración de NVDA del usuario y la convierte a la de Tiresias para
que el lector se sienta familiar desde el primer momento:

- ``nvda.ini`` (formato configobj, con un lector propio: no hace falta el
  paquete ``configobj``), los perfiles (``profiles/*.ini``) y sus
  disparadores (``profileTriggers.ini``);
- ``gestures.ini`` (gestos de entrada);
- ``speechDicts/*.dic`` (diccionario por defecto, temporal y de voz);
- ``symbols-<idioma>.dic`` (símbolos personalizados);
- las etiquetas de complementos, si las hay (se informa de ellas).

Funciona con NVDA instalado (``%APPDATA%\\nvda``) y con NVDA portable (la
carpeta ``userConfig`` que hay junto al ejecutable).

Flujo:

1. :class:`NvdaConfig` lee la carpeta de NVDA (solo lectura: nunca se escribe
   nada en ella).
2. :func:`buildPlan` calcula los cambios (:class:`Plan`): opciones, perfiles,
   gestos, diccionarios y símbolos, con los avisos de lo que no tiene
   equivalente. Nada se escribe todavía (vista previa).
3. :func:`applyPlan` hace una copia de seguridad de la configuración de
   Tiresias, aplica las categorías elegidas, guarda y escribe el informe
   (``informe_importacion_nvda.txt``) y la copia exportada
   (``configuracion_desde_nvda.json``) en la carpeta de configuración.
4. :func:`undoLastImport` deshace la última importación con esa copia.

Desde la línea de órdenes: ``--import-nvda-config [carpeta]``,
``--import-nvda-profile <nombre>`` y ``--undo-nvda-import``.
"""

from __future__ import annotations

import copy
import datetime
import fnmatch
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from typing import Any, Callable

from . import paths
from .i18n import _
from .log import getLogger

log = getLogger("nvdaImport")

# ---------------------------------------------------------------------- categorías
CAT_SPEECH = "speech"
CAT_KEYBOARD = "keyboard"
CAT_BRAILLE = "braille"
CAT_OTHER = "other"
CAT_PROFILES = "profiles"
CAT_GESTURES = "gestures"
CAT_DICTS = "dictionaries"
CAT_SYMBOLS = "symbols"
CATEGORIES = (CAT_SPEECH, CAT_KEYBOARD, CAT_BRAILLE, CAT_OTHER, CAT_PROFILES, CAT_GESTURES, CAT_DICTS, CAT_SYMBOLS)
#: Categorías que son opciones de la configuración (las demás son archivos aparte).
SETTING_CATEGORIES = (CAT_SPEECH, CAT_KEYBOARD, CAT_BRAILLE, CAT_OTHER)


def categoryLabel(cat: str) -> str:
	return {
		CAT_SPEECH: _("Voz"),
		CAT_KEYBOARD: _("Teclado"),
		CAT_BRAILLE: _("Braille"),
		CAT_OTHER: _("Otras opciones (ratón, revisión, presentación, modo exploración, formato, visión, audio, avanzadas)"),
		CAT_PROFILES: _("Perfiles de configuración"),
		CAT_GESTURES: _("Gestos de entrada"),
		CAT_DICTS: _("Diccionarios de voz"),
		CAT_SYMBOLS: _("Símbolos personalizados"),
	}.get(cat, cat)


def _shortCategory(cat: str) -> str:
	return {
		CAT_SPEECH: _("Voz"),
		CAT_KEYBOARD: _("Teclado"),
		CAT_BRAILLE: _("Braille"),
		CAT_OTHER: _("Otras opciones"),
		CAT_PROFILES: _("Perfiles"),
		CAT_GESTURES: _("Gestos"),
		CAT_DICTS: _("Diccionarios"),
		CAT_SYMBOLS: _("Símbolos"),
		"": _("General"),
	}.get(cat, cat)


#: Archivos que deja la importación en la carpeta de configuración.
REPORT_FILE = "informe_importacion_nvda.txt"
EXPORT_FILE = "configuracion_desde_nvda.json"
#: Carpeta (dentro de la de configuración) con las copias de seguridad.
BACKUP_DIR = "backup_antes_importar"
MANIFEST_FILE = "importacion.json"
#: Copias de seguridad que se conservan (las más antiguas se borran).
MAX_BACKUPS = 5

_MISSING = object()


class ImportError_(Exception):
	"""Error que se muestra al usuario tal cual."""


# ====================================================================== lector de configobj
def _stripComment(value: str) -> str:
	"""Quita un comentario ``# ...`` que esté fuera de comillas."""
	quote = None
	for i, ch in enumerate(value):
		if quote:
			if ch == quote:
				quote = None
		elif ch in "\"'":
			quote = ch
		elif ch == "#":
			return value[:i].rstrip()
	return value


def _unquote(text: str) -> str:
	text = text.strip()
	if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
		return text[1:-1]
	return text


def _splitList(value: str) -> list[str] | None:
	"""Divide por comas fuera de comillas; ``None`` si no hay ninguna coma."""
	parts: list[str] = []
	cur = ""
	quote = None
	found = False
	for ch in value:
		if quote:
			cur += ch
			if ch == quote:
				quote = None
		elif ch in "\"'":
			quote = ch
			cur += ch
		elif ch == ",":
			found = True
			parts.append(cur)
			cur = ""
		else:
			cur += ch
	if not found:
		return None
	parts.append(cur)
	return [_unquote(p) for p in parts if p.strip()]


def _parseValue(value: str) -> str | list[str]:
	value = _stripComment(value.strip())
	items = _splitList(value)
	if items is not None:
		return items
	return _unquote(value)


def parseIni(text: str) -> dict:
	"""Lee un archivo de configobj (el formato de ``nvda.ini``).

	Devuelve un diccionario anidado: las secciones (``[a]``, ``[[b]]``...)
	son diccionarios y los valores son cadenas o listas de cadenas (una lista
	cuando el valor lleva comas fuera de comillas, como hace configobj).
	"""
	root: dict = {}
	stack: list[tuple[int, dict]] = [(0, root)]
	lines = text.splitlines()
	i = 0
	while i < len(lines):
		line = lines[i].strip()
		i += 1
		if not line or line.startswith("#"):
			continue
		if line.startswith("["):
			m = re.match(r"^(\[+)\s*(.*?)\s*(\]+)\s*(#.*)?$", line)
			if not m:
				continue
			depth = len(m.group(1))
			name = _unquote(m.group(2))
			while len(stack) > 1 and stack[-1][0] >= depth:
				stack.pop()
			parent = stack[-1][1]
			section = parent.get(name)
			if not isinstance(section, dict):
				section = {}
				parent[name] = section
			stack.append((depth, section))
			continue
		key, sep, value = line.partition("=")
		if not sep:
			continue
		key = _unquote(key.strip())
		value = value.strip()
		if value[:3] in ('"""', "'''"):
			quote = value[:3]
			rest = value[3:]
			if quote in rest:
				stack[-1][1][key] = rest[: rest.index(quote)]
				continue
			parts = [rest]
			while i < len(lines):
				nxt = lines[i]
				i += 1
				if quote in nxt:
					parts.append(nxt[: nxt.index(quote)])
					break
				parts.append(nxt)
			stack[-1][1][key] = "\n".join(parts)
			continue
		stack[-1][1][key] = _parseValue(value)
	return root


def readIni(path: str) -> dict:
	with open(path, encoding="utf-8-sig", errors="replace") as f:
		return parseIni(f.read())


# ====================================================================== conversiones
class _NoEquivalent(Exception):
	"""El valor de NVDA no tiene equivalente en Tiresias (el mensaje dice por qué)."""


class _Silent(Exception):
	"""Valor que se deja como está sin avisar (p. ej. «por defecto» en un indicador)."""


def _text(v: Any) -> str:
	if isinstance(v, list):
		return ", ".join(v)
	return str(v)


def toBool(v: Any) -> bool:
	s = _text(v).strip().lower()
	if s in ("true", "yes", "on", "1", "sí", "si"):
		return True
	if s in ("false", "no", "off", "0"):
		return False
	raise ValueError(f"no es un valor lógico: {v!r}")


def toInt(v: Any) -> int:
	s = _text(v).strip()
	try:
		return int(s)
	except ValueError:
		return int(round(float(s.replace(",", "."))))


def toFloat(v: Any) -> float:
	return float(_text(v).strip().replace(",", "."))


def toList(v: Any) -> list[str]:
	if isinstance(v, list):
		return [x for x in (str(i).strip() for i in v) if x]
	s = str(v).strip()
	return [x.strip() for x in s.split(",") if x.strip()] if s else []


def _flagName(v: Any) -> str:
	"""Valor de un indicador de NVDA normalizado: «AT_WORD_BOUNDARIES» -> «atwordboundaries»."""
	return _text(v).strip().lower().replace("_", "").replace(" ", "")


def _clampInt(lo: int, hi: int) -> Callable[[Any], int]:
	def conv(v: Any) -> int:
		return max(lo, min(hi, toInt(v)))

	return conv


def _choice(mapping: dict[str, Any], what: str = "") -> Callable[[Any], Any]:
	"""Convierte con un diccionario (claves en minúsculas, sin guiones bajos)."""

	def conv(v: Any) -> Any:
		key = _flagName(v)
		if key == "default":
			raise _Silent()
		if key in mapping:
			result = mapping[key]
			if isinstance(result, Exception):
				raise result
			return result
		raise _NoEquivalent(_("el valor «{value}» no existe en Tiresias").format(value=_text(v)))

	return conv


_BOOL_FLAG = _choice({"enabled": True, "disabled": False, "true": True, "false": False})


def _triState(v: Any) -> bool:
	"""Indicadores numéricos de NVDA: 0 = por defecto, 1 = sí, 2 = no."""
	n = toInt(v)
	if n == 0:
		raise _Silent()
	return n == 1


def _intChoice(values: dict[int, Any]) -> Callable[[Any], Any]:
	def conv(v: Any) -> Any:
		s = _text(v).strip().lower()
		if s in ("true", "false"):
			# Versiones antiguas guardaban una casilla.
			n = 1 if s == "true" else 0
		else:
			n = toInt(v)
		if n not in values:
			raise _NoEquivalent(_("el valor {value} no existe en Tiresias").format(value=n))
		result = values[n]
		if isinstance(result, Exception):
			raise result
		return result

	return conv


# ---------------------------------------------------------------------- tablas
#: Valores de «anunciar caracteres/palabras escritos» (0: no, 1: en edición, 2: siempre).
_TYPED = {0: "off", 1: "editOnly", 2: "always"}

#: Modos de voz de NVDA (``SpeechMode``).
_SPEECH_MODES = {0: "off", 1: "beeps", 2: "talk", 3: "onDemand"}

#: División del sonido de NVDA (``SoundSplitState``) -> modo de Tiresias.
_SOUND_SPLIT = {
	0: "off",
	1: None,  # NVDA y aplicaciones en ambos canales: equivale a no dividir.
	2: "leftRight",
	3: "leftBoth",
	4: "rightLeft",
	5: "rightBoth",
	6: "bothLeft",
	7: "bothRight",
}


def _soundSplit(v: Any) -> str:
	n = toInt(v)
	if n not in _SOUND_SPLIT:
		raise _NoEquivalent(_("modo de división desconocido ({value})").format(value=n))
	return _SOUND_SPLIT[n] or "off"


def _soundSplitList(v: Any) -> list[str]:
	out: list[str] = []
	for item in toList(v):
		mode = _SOUND_SPLIT.get(toInt(item))
		if mode and mode not in out:
			out.append(mode)
	if "off" not in out:
		out.insert(0, "off")
	return out


def _typedEcho(v: Any) -> str:
	"""Eco de caracteres o palabras: 0 no, 1 en edición, 2 siempre (antes, una casilla: sí = siempre)."""
	s = _text(v).strip().lower()
	if s in ("true", "false"):
		return "always" if s == "true" else "off"
	n = toInt(v)
	if n not in _TYPED:
		raise _NoEquivalent(_("el valor {value} no existe en Tiresias").format(value=n))
	return _TYPED[n]


def _excludedModes(v: Any) -> list[str]:
	return [_SPEECH_MODES[toInt(i)] for i in toList(v) if toInt(i) in _SPEECH_MODES]


def _logLevel(v: Any) -> str:
	s = _text(v).strip().upper()
	if s in ("DEBUG", "DEBUG_UNREDACTED", "IO", "DEBUGWARNING"):
		return "DEBUG"
	if s in ("INFO", "OFF", "WARNING", "ERROR", "CRITICAL"):
		return s
	raise _NoEquivalent(_("nivel de registro desconocido"))


def _language(v: Any) -> str:
	s = _text(v).strip()
	if not s or s.lower() == "windows":
		return "auto"
	try:
		from . import i18n

		available = i18n.availableLanguages()
	except Exception:
		available = ["es"]
	if s in available:
		return s
	base = s.split("_")[0]
	if base in available:
		return base
	raise _NoEquivalent(_("Tiresias no está traducido a ese idioma ({lang}); se mantiene el idioma actual").format(lang=s))


def _symbolDictionaries(v: Any) -> bool:
	return "cldr" in [x.lower() for x in toList(v)]


def _maxLength(v: Any) -> int:
	return max(10, min(1000, toInt(v)))


def _linesPerPage(v: Any) -> int:
	return max(5, min(500, toInt(v)))


def _regex(v: Any) -> str:
	s = _text(v)
	try:
		re.compile(s)
	except re.error:
		raise _NoEquivalent(_("la expresión regular no es válida en Tiresias")) from None
	return s


def _ducking(v: Any) -> str:
	return _intChoice({0: "off", 1: "speaking", 2: "always"})(v)


def _brailleShowMessages(v: Any) -> str:
	return _intChoice({0: "disabled", 1: "timeout", 2: "always"})(v)


def _autoScrollRate(v: Any) -> int:
	return max(1, min(20, int(round(toFloat(v)))))


def _uiaEventRegistration(v: Any) -> str:
	s = _text(v).strip().lower()
	if s in ("auto", "selective"):
		return "selective"
	if s == "global":
		return "global"
	raise _NoEquivalent(_("valor desconocido"))


def _winConsole(v: Any) -> bool:
	s = _text(v).strip().lower()
	if s == "legacy":
		return False
	return True


def _diffAlgo(v: Any) -> str:
	s = _text(v).strip().lower()
	if s == "difflib":
		return "lines"
	return "characters"


def _addonUpdates(v: Any) -> bool:
	return _text(v).strip().lower() != "disabled"


def _mathVerbosity(v: Any) -> str:
	return _choice({"terse": "breve", "medium": "normal", "verbose": "detallado"})(v)


def _mathStyle(v: Any) -> str:
	return _choice(
		{
			"clearspeak": "natural",
			"simplespeak": "natural",
			"mathspeak": "estructural",
			"nemeth": _NoEquivalent(_("Tiresias no tiene el estilo de voz Nemeth")),
		}
	)(v)


def _mathCopy(v: Any) -> str:
	return _choice(
		{
			"mathml": "mathml",
			"latex": "latex",
			"asciimath": "text",
			"speech": "text",
		}
	)(v)


def _magnifierFilter(v: Any) -> str:
	return _choice({"normal": "none", "grayscale": "grayscale", "inverted": "invert", "invert": "invert"})(v)


def _magnifierView(v: Any) -> str:
	return _choice({"fullscreen": "fullscreen", "docked": "docked", "lens": "lens", "spotlight": "spotlight"})(v)


def _magnifierTracking(v: Any) -> str:
	return _choice({"center": "center", "relative": "relative", "border": "edge"})(v)


def _zoomLevel(v: Any) -> float:
	return max(1.0, min(16.0, toInt(v) / 100.0))


def _hoverMs(v: Any) -> int:
	return max(100, int(round(toFloat(v) * 1000)))


def _cellCount(v: Any) -> int:
	return max(10, min(120, toInt(v)))


def _fontAttributeMode(v: Any) -> int:
	"""``documentFormatting.fontAttributeReporting`` de NVDA: 0 no, 1 voz, 2 braille, 3 los dos."""
	n = toInt(v)
	if n not in (0, 1, 2, 3):
		raise _NoEquivalent(_("el valor {value} no existe en Tiresias").format(value=n))
	return n


#: Fila de la tabla de equivalencias:
#: (categoría, ruta de la sección de NVDA, clave de NVDA, ruta de Tiresias,
#: conversión, valor por defecto de NVDA o ``None`` si solo se importa cuando
#: está escrito en el archivo). Un indicador escrito como «DEFAULT» toma ese
#: valor por defecto de NVDA (``behaviorOfDefault`` en su configSpec).
_Row = tuple[str, str, str, str, Callable[[Any], Any], "str | None"]

_O, _S, _K, _B = CAT_OTHER, CAT_SPEECH, CAT_KEYBOARD, CAT_BRAILLE
_bool = toBool
_int = toInt

ROWS: list[_Row] = [
	# --- generales
	(_O, "general", "language", "general.language", _language, "Windows"),
	(_O, "general", "saveConfigurationOnExit", "general.saveConfigurationOnExit", _bool, "True"),
	(_O, "general", "askToExit", "general.askToExit", _bool, "True"),
	(_O, "general", "playStartAndExitSounds", "general.playStartAndExitSounds", _bool, "True"),
	(_O, "general", "loggingLevel", "general.logLevel", _logLevel, "INFO"),
	(_O, "general", "showWelcomeDialogAtStartup", "general.showWelcomeDialogAtStartup", _bool, "True"),
	(_O, "general", "preventDisplayTurningOff", "general.preventDisplayTurningOff", _bool, "True"),
	# --- voz
	(_S, "speech", "symbolLevel", "speech.symbolLevel", _clampInt(0, 300), "100"),
	(_S, "speech", "trustVoiceLanguage", "speech.trustVoiceLanguage", _bool, "True"),
	(_S, "speech", "unicodeNormalization", "speech.unicodeNormalization", _BOOL_FLAG, "enabled"),
	(_S, "speech", "reportNormalizedForCharacterNavigation", "speech.reportNormalizedForCharacterNavigation", _bool, "True"),
	(_S, "speech", "symbolDictionaries", "speech.speakEmojiNames", _symbolDictionaries, "cldr"),
	# NVDA admite de 50 a 11025 Hz (10000 por defecto); el panel de Voz de Tiresias, de 50 a 5000.
	(_S, "speech", "beepSpeechModePitch", "speech.beepSpeechModePitch", _clampInt(50, 5000), "10000"),
	(_S, "speech", "autoLanguageSwitching", "speech.autoLanguageSwitching", _bool, "True"),
	(_S, "speech", "autoDialectSwitching", "speech.autoDialectSwitching", _bool, "False"),
	(_S, "speech", "reportLanguage", "speech.reportLanguage", _bool, None),
	(_S, "speech", "reportNotSupportedLanguage", "speech.reportNotSupportedLanguage", _choice({"speech": "speech", "beep": "beep", "off": "off"}), None),
	(_S, "speech", "delayedCharacterDescriptions", "speech.delayedCharacterDescriptions", _bool, "False"),
	(_S, "speech", "excludedSpeechModes", "speech.excludedSpeechModes", _excludedModes, ""),
	(_S, "speech", "trimLeadingSilence", "speech.trimLeadingSilence", _bool, "True"),
	(_S, "speech", "sayAllReadingUnit", "speech.sayAllUnit", _choice({"line": "line", "sentence": "sentence", "paragraph": "paragraph"}), "sentence"),
	(_S, "featureFlag", "cancelExpiredFocusSpeech", "speech.cancelExpiredFocusSpeech", _triState, None),
	# --- audio
	(_O, "audio", "audioDuckingMode", "audio.duckingMode", _ducking, "0"),
	(_O, "audio", "soundVolumeFollowsVoice", "audio.soundVolumeFollowsVoice", _bool, "False"),
	(_O, "audio", "soundVolume", "audio.soundVolume", _clampInt(0, 100), "100"),
	(_O, "audio", "audioAwakeTime", "audio.keepAudioAwakeSeconds", _clampInt(0, 3600), "30"),
	(_O, "audio", "whiteNoiseVolume", "audio.whiteNoiseVolume", _clampInt(0, 100), "0"),
	(_O, "audio", "soundSplitState", "audio.soundSplitMode", _soundSplit, "0"),
	(_O, "audio", "includedSoundSplitModes", "audio.includedSoundSplitModes", _soundSplitList, "0, 2, 3"),
	# --- braille
	(_B, "braille", "mode", "braille.mode", _choice({"followcursors": "followCursors", "speechoutput": "speechOutput"}), "followCursors"),
	(_B, "braille", "expandAtCursor", "braille.expandAtCursor", _bool, "True"),
	(_B, "braille", "showCursor", "braille.showCursor", _bool, "True"),
	(_B, "braille", "cursorBlink", "braille.cursorBlink", _bool, "True"),
	(_B, "braille", "cursorBlinkRate", "braille.cursorBlinkRate", _clampInt(100, 2000), "500"),
	(_B, "braille", "cursorShapeFocus", "braille.cursorShapeFocus", _clampInt(1, 255), "192"),
	(_B, "braille", "cursorShapeReview", "braille.cursorShapeReview", _clampInt(1, 255), "128"),
	(_B, "braille", "showMessages", "braille.showMessages", _brailleShowMessages, "1"),
	(_B, "braille", "messageTimeout", "braille.messageTimeout", _clampInt(1, 60), "4"),
	(_B, "braille", "autoScrollRate", "braille.autoScrollRate", _autoScrollRate, "10"),
	(_B, "braille", "tetherTo", "braille.tetherTo", _choice({"auto": "auto", "focus": "focus", "review": "review"}), "auto"),
	(
		_B,
		"braille",
		"reviewRoutingMovesSystemCaret",
		"braille.reviewRoutingMovesSystemCaret",
		_choice({"never": "never", "always": "always", "onlywhenautotethered": "onlyWhenAutoTethered"}),
		"never",
	),
	(_B, "braille", "readByParagraph", "braille.readByParagraph", _bool, "False"),
	(_B, "braille", "paragraphStartMarker", "braille.paragraphStartMarker", lambda v: _text(v) if _text(v) in ("", " ", "¶") else "", None),
	(_B, "braille", "unicodeNormalization", "braille.unicodeNormalization", _BOOL_FLAG, "disabled"),
	(_B, "braille", "focusContextPresentation", "braille.focusContextPresentation", _choice({"changedcontext": "changedContext", "fill": "fill", "scroll": "scroll"}), "changedContext"),
	(_B, "braille", "interruptSpeechWhileScrolling", "braille.interruptSpeechWhileScrolling", _BOOL_FLAG, "enabled"),
	(_B, "braille", "speakOnRouting", "braille.speakOnRouting", _bool, None),
	(_B, "braille", "speakOnNavigatingByUnit", "braille.speakOnNavigatingByUnit", _bool, None),
	(_B, "braille", "showSelection", "braille.showSelection", _BOOL_FLAG, "enabled"),
	(_B, "braille", "reportLiveRegions", "braille.reportLiveRegions", _BOOL_FLAG, "enabled"),
	(
		_B,
		"braille",
		"fontFormattingDisplay",
		"braille.fontFormattingDisplay",
		_choice({"liblouis": "liblouis", "tags": _NoEquivalent(_("Tiresias no muestra el formato con etiquetas; usa los signos de la tabla o los puntos 7 y 8"))}),
		None,
	),
	(_B, "brailleViewer", "showBrailleViewerAtStartup", "brailleViewer.showAtStartup", _bool, "False"),
	(_B, "brailleViewer", "shouldHoverRouteToCell", "brailleViewer.routeOnHover", _bool, "False"),
	(_B, "brailleViewer", "secondsOfHoverToActivate", "brailleViewer.hoverDwellTime", _hoverMs, "1.0"),
	(_B, "brailleViewer", "defaultCellCount", "braille.numCellsForViewer", _cellCount, "40"),
	# --- teclado
	(_K, "keyboard", "keyboardLayout", "keyboard.layout", _choice({"desktop": "desktop", "laptop": "laptop"}), "desktop"),
	(_K, "keyboard", "speakTypedCharacters", "keyboard.speakTypedCharacters", _typedEcho, "1"),
	(_K, "keyboard", "speakTypedWords", "keyboard.speakTypedWords", _typedEcho, "0"),
	(_K, "keyboard", "beepForLowercaseWithCapslock", "keyboard.beepForLowercaseWithCapsLock", _bool, "True"),
	(_K, "keyboard", "speakCommandKeys", "keyboard.speakCommandKeys", _bool, "False"),
	(_K, "keyboard", "speechInterruptForCharacters", "keyboard.speechInterruptForCharacters", _bool, "True"),
	(_K, "keyboard", "speechInterruptForEnter", "keyboard.speechInterruptForEnter", _bool, "True"),
	(_K, "keyboard", "allowSkimReadingInSayAll", "keyboard.allowSkimReadingInSayAll", _bool, "False"),
	(_K, "keyboard", "alertForSpellingErrors", "keyboard.alertForSpellingErrors", _bool, "True"),
	(_K, "keyboard", "handleInjectedKeys", "keyboard.handleInjectedKeys", _bool, "True"),
	(_K, "keyboard", "multiPressTimeout", "keyboard.multiPressTimeout", _clampInt(100, 2000), "500"),
	# --- ratón
	(_O, "mouse", "enableMouseTracking", "mouse.enableMouseTracking", _bool, "True"),
	(_O, "mouse", "mouseTextUnit", "mouse.mouseTextUnit", _choice({"character": "character", "word": "word", "line": "line", "paragraph": "paragraph"}), "paragraph"),
	(_O, "mouse", "reportObjectRoleOnMouseEnter", "mouse.reportObjectRoleOnMouseEnter", _bool, "False"),
	(_O, "mouse", "audioCoordinatesOnMouseMove", "mouse.audioCoordinatesOnMouseMove", _bool, "False"),
	(_O, "mouse", "audioCoordinates_minPitch", "mouse.audioCoordinatesMinPitch", _clampInt(50, 10000), "220"),
	(_O, "mouse", "audioCoordinates_maxPitch", "mouse.audioCoordinatesMaxPitch", _clampInt(50, 10000), "880"),
	(_O, "mouse", "reportMouseShapeChanges", "mouse.reportMouseShapeChanges", _bool, "False"),
	(_O, "mouse", "ignoreInjectedMouseInput", "mouse.ignoreInjectedMouseInput", _bool, "False"),
	# --- cursor de revisión
	(_O, "reviewCursor", "simpleReviewMode", "reviewCursor.simpleReviewMode", _bool, "True"),
	(_O, "reviewCursor", "followFocus", "reviewCursor.followFocus", _bool, "True"),
	(_O, "reviewCursor", "followCaret", "reviewCursor.followCaret", _bool, "True"),
	(_O, "reviewCursor", "followMouse", "reviewCursor.followMouse", _bool, "False"),
	# --- presentación de objetos y barras de progreso
	(_O, "presentation", "reportKeyboardShortcuts", "presentation.reportKeyboardShortcuts", _bool, "True"),
	(_O, "presentation", "reportObjectPositionInformation", "presentation.reportObjectPositionInformation", _bool, "True"),
	(_O, "presentation", "guessObjectPositionInformationWhenUnavailable", "presentation.guessObjectPositionInformationWhenUnavailable", _bool, "False"),
	(_O, "presentation", "reportMultiSelect", "presentation.reportMultiSelect", _bool, "False"),
	(_O, "presentation", "reportTooltips", "presentation.reportTooltips", _bool, "False"),
	(_O, "presentation", "reportHelpBalloons", "presentation.reportHelpBalloons", _bool, "True"),
	(_O, "presentation", "reportObjectDescriptions", "presentation.reportObjectDescriptions", _bool, "True"),
	(_O, "presentation", "reportDynamicContentChanges", "presentation.reportDynamicContentChanges", _bool, "True"),
	(_O, "presentation", "reportAutoSuggestionsWithSound", "presentation.reportAutoSuggestionsWithSound", _bool, "True"),
	(_O, "presentation/progressBarUpdates", "reportBackgroundProgressBars", "presentation.reportBackgroundProgressBars", _bool, "False"),
	(_O, "presentation/progressBarUpdates", "progressBarOutputMode", "presentation.progressBarOutputMode", _choice({"off": "off", "speak": "speak", "beep": "beep", "both": "both"}), "beep"),
	(_O, "presentation/progressBarUpdates", "speechPercentageInterval", "presentation.progressBarSpeechInterval", _clampInt(1, 100), "10"),
	(_O, "presentation/progressBarUpdates", "beepPercentageInterval", "presentation.progressBarBeepInterval", _clampInt(1, 100), "1"),
	(_O, "presentation/progressBarUpdates", "beepMinHZ", "presentation.progressBarBeepMinHz", _clampInt(20, 2000), "110"),
	# --- modo exploración
	(_O, "virtualBuffers", "maxLineLength", "browseMode.maxLineLength", _maxLength, "100"),
	(_O, "virtualBuffers", "linesPerPage", "browseMode.linesPerPage", _linesPerPage, "25"),
	(_O, "virtualBuffers", "useScreenLayout", "browseMode.useScreenLayout", _bool, "True"),
	(_O, "virtualBuffers", "autoPassThroughOnFocusChange", "browseMode.autoPassThroughOnFocusChange", _bool, "True"),
	(_O, "virtualBuffers", "autoPassThroughOnCaretMove", "browseMode.autoPassThroughOnCaretMove", _bool, "False"),
	(_O, "virtualBuffers", "passThroughAudioIndication", "browseMode.passThroughAudioIndication", _bool, "True"),
	(_O, "virtualBuffers", "autoSayAllOnPageLoad", "browseMode.autoSayAllOnPageLoad", _bool, "True"),
	(_O, "virtualBuffers", "trapNonCommandGestures", "browseMode.trapNonCommandGestures", _bool, "True"),
	(_O, "virtualBuffers", "enableOnPageLoad", "browseMode.enableOnPageLoad", _bool, "True"),
	(_O, "virtualBuffers", "autoFocusFocusableElements", "browseMode.autoFocusFocusableElements", _bool, None),
	(_O, "virtualBuffers", "nativeSelectionMode", "browseMode.nativeSelectionMode", _BOOL_FLAG, "disabled"),
	(_O, "virtualBuffers", "textParagraphRegex", "documentNavigation.textParagraphRegex", _regex, None),
	(_O, "documentFormatting", "includeLayoutTables", "browseMode.includeLayoutTables", _bool, "False"),
	# --- formato de documento
	(_O, "documentFormatting", "detectFormatAfterCursor", "documentFormatting.detectFormatAfterCursor", _bool, "False"),
	(_O, "documentFormatting", "reportFontName", "documentFormatting.reportFontName", _bool, "False"),
	(_O, "documentFormatting", "reportFontSize", "documentFormatting.reportFontSize", _bool, "False"),
	# 0 no, 1 voz, 2 braille, 3 voz y braille (la parte del braille, en _documentFormattingSpecial).
	(_O, "documentFormatting", "fontAttributeReporting", "documentFormatting.reportFontAttributes", lambda v: _fontAttributeMode(v) in (1, 3), "0"),
	(_O, "documentFormatting", "reportFontAttributes", "documentFormatting.reportFontAttributes", _bool, None),
	(_O, "documentFormatting", "reportRevisions", "documentFormatting.reportRevisions", _bool, "True"),
	(_O, "documentFormatting", "reportEmphasis", "documentFormatting.reportEmphasis", _bool, "False"),
	(_O, "documentFormatting", "reportHighlight", "documentFormatting.reportHighlight", _bool, "True"),
	(_O, "documentFormatting", "reportSuperscriptsAndSubscripts", "documentFormatting.reportSuperscriptsAndSubscripts", _bool, "False"),
	(_O, "documentFormatting", "reportColor", "documentFormatting.reportColor", _bool, "False"),
	(_O, "documentFormatting", "reportAlignment", "documentFormatting.reportAlignment", _bool, "False"),
	(_O, "documentFormatting", "reportLineSpacing", "documentFormatting.reportLineSpacing", _bool, "False"),
	(_O, "documentFormatting", "reportStyle", "documentFormatting.reportStyle", _bool, "False"),
	(_O, "documentFormatting", "reportSpellingErrors", "documentFormatting.reportSpellingErrors", _bool, None),
	(_O, "documentFormatting", "reportPage", "documentFormatting.reportPage", _bool, "True"),
	(_O, "documentFormatting", "reportLineNumber", "documentFormatting.reportLineNumber", _bool, "False"),
	(_O, "documentFormatting", "reportLineIndentation", "documentFormatting.reportLineIndentation", _intChoice({0: "off", 1: "speech", 2: "tones", 3: "both"}), "0"),
	(_O, "documentFormatting", "ignoreBlankLinesForRLI", "documentFormatting.ignoreBlankLinesForRLI", _bool, "False"),
	(_O, "documentFormatting", "reportParagraphIndentation", "documentFormatting.reportParagraphIndentation", _bool, "False"),
	(_O, "documentFormatting", "reportTables", "documentFormatting.reportTables", _bool, "True"),
	(_O, "documentFormatting", "reportTableCellCoords", "documentFormatting.reportTableCellCoords", _bool, "True"),
	(_O, "documentFormatting", "reportCellBorders", "documentFormatting.reportCellBorders", _intChoice({0: "off", 1: "styles", 2: "colorsAndStyles"}), "0"),
	(_O, "documentFormatting", "reportLinks", "documentFormatting.reportLinks", _bool, "True"),
	(_O, "documentFormatting", "reportLinkType", "documentFormatting.reportLinkType", _bool, None),
	(_O, "documentFormatting", "reportGraphics", "documentFormatting.reportGraphics", _bool, "True"),
	(_O, "documentFormatting", "reportComments", "documentFormatting.reportComments", _bool, "True"),
	(_O, "documentFormatting", "reportLists", "documentFormatting.reportLists", _bool, "True"),
	(_O, "documentFormatting", "reportHeadings", "documentFormatting.reportHeadings", _bool, "True"),
	(_O, "documentFormatting", "reportBlockQuotes", "documentFormatting.reportBlockQuotes", _bool, "True"),
	(_O, "documentFormatting", "reportGroupings", "documentFormatting.reportGroupings", _bool, "True"),
	(_O, "documentFormatting", "reportLandmarks", "documentFormatting.reportLandmarks", _bool, "True"),
	(_O, "documentFormatting", "reportArticles", "documentFormatting.reportArticles", _bool, "False"),
	(_O, "documentFormatting", "reportFrames", "documentFormatting.reportFrames", _bool, "True"),
	(_O, "documentFormatting", "reportFigures", "documentFormatting.reportFigures", _bool, None),
	(_O, "documentFormatting", "reportClickable", "documentFormatting.reportClickable", _bool, "True"),
	(_O, "annotations", "reportDetails", "documentFormatting.reportDetails", _bool, None),
	(
		_O,
		"documentNavigation",
		"paragraphStyle",
		"documentNavigation.paragraphStyle",
		_choice({"application": "application", "singlelinebreak": "singleLineBreak", "multilinebreak": "multiLineBreak"}),
		"application",
	),
	# --- interacción táctil
	(_O, "touch", "enabled", "touch.enabled", _bool, "True"),
	(_O, "touch", "touchTyping", "touch.touchTyping", _bool, "False"),
	(_O, "touch", "edgeGestures", "touch.edgeGestures", _bool, None),
	# --- UIA, consolas y avanzadas
	(_O, "UIA", "eventRegistration", "uia.eventRegistration", _uiaEventRegistration, None),
	(_O, "UIA", "winConsoleImplementation", "uia.preferUIAForConsoles", _winConsole, None),
	(_O, "terminals", "speakPasswords", "terminal.speakPasswords", _bool, "False"),
	(_O, "terminals", "diffAlgo", "terminal.diffAlgorithm", _diffAlgo, None),
	(_O, "development", "enableScratchpadDir", "advanced.enableScratchpad", _bool, "False"),
	(_O, "featureFlag", "playErrorSound", "advanced.playErrorSound", _triState, None),
	# --- composición de entrada
	(_O, "inputComposition", "autoReportAllCandidates", "inputComposition.autoReportAllCandidates", _bool, "True"),
	(_O, "inputComposition", "announceSelectedCandidate", "inputComposition.announceSelectedCandidate", _bool, "True"),
	(_O, "inputComposition", "reportCompositionStringChanges", "inputComposition.reportCompositionStringChanges", _bool, "True"),
	# --- reconocimiento de texto (OCR de Windows)
	(_O, "uwpOcr", "language", "ocr.language", lambda v: _text(v).strip(), None),
	(_O, "uwpOcr", "autoRefresh", "ocr.autoRefresh", _bool, "False"),
	(_O, "uwpOcr", "autoRefreshInterval", "ocr.autoRefreshInterval", _clampInt(250, 60000), "1500"),
	(_O, "uwpOcr", "autoSayAllOnResult", "ocr.autoSayAll", _bool, "False"),
	# --- actualizaciones y complementos
	(_O, "update", "autoCheck", "update.autoCheck", _bool, "True"),
	(_O, "addonStore", "automaticUpdates", "addons.autoCheckUpdates", _addonUpdates, None),
	# --- acceso remoto
	(_O, "remote/ui", "confirmDisconnectAsFollower", "remote.confirmDisconnectAsFollower", _bool, None),
	(_O, "remote/ui", "muteOnLocalControl", "remote.muteOnLocalControl", _bool, None),
	# --- matemáticas
	(_O, "math/speech", "verbosity", "math.verbosity", _mathVerbosity, None),
	# El estilo de voz está en math/speech/<idioma>/speechStyle: lo lee _Mapper._mathSpeechStyle.
	(_O, "math/navigation", "copyAs", "math.copyFormat", _mathCopy, None),
	# --- visor de voz
	(_O, "speechViewer", "showSpeechViewerAtStartup", "speechViewer.showAtStartup", _bool, "False"),
	# --- cortina de pantalla
	(_O, "screenCurtain", "enabled", "vision.screenCurtain", _bool, None),
	(_O, "screenCurtain", "warnOnLoad", "vision.curtainWarnOnEnable", _bool, None),
	(_O, "screenCurtain", "playToggleSounds", "vision.curtainPlaySounds", _bool, None),
	(_O, "vision/screenCurtain", "enabled", "vision.screenCurtain", _bool, None),
	(_O, "vision/screenCurtain", "warnOnLoad", "vision.curtainWarnOnEnable", _bool, None),
	(_O, "vision/screenCurtain", "playToggleSounds", "vision.curtainPlaySounds", _bool, None),
	# --- lupa
	(_O, "magnifier", "enabled", "magnifier.enableAtStartup", _bool, None),
	(_O, "magnifier", "magnifiedView", "magnifier.view", _magnifierView, None),
	(_O, "magnifier", "zoom", "magnifier.level", _zoomLevel, None),
	(_O, "magnifier", "filter", "magnifier.filter", _magnifierFilter, None),
	(_O, "magnifier", "followMouse", "magnifier.followMouse", _bool, None),
	(_O, "magnifier", "followSystemFocus", "magnifier.followFocus", _bool, None),
	(_O, "magnifier", "followReviewCursor", "magnifier.followReview", _bool, None),
	(_O, "magnifier", "followNavigatorObject", "magnifier.followNavigator", _bool, None),
	(_O, "magnifier", "panStep", "magnifier.panStep", _clampInt(1, 50), None),
	(_O, "magnifier", "fullscreenMode", "magnifier.trackingMode", _magnifierTracking, "center"),
]

#: Claves que se leen con un tratamiento propio (no se avisa de ellas como «sin equivalente»).
_SPECIAL_KEYS = {
	("speech", "synth"),
	("speech", "speechDictionaries"),
	("keyboard", "NVDAModifierKeys"),
	("braille", "display"),
	("braille", "translationTable"),
	("braille", "inputTable"),
	("braille", "wordWrap"),
	("braille", "textWrap"),
	("audio", "outputDevice"),
	("speech", "outputDevice"),
	("documentFormatting", "reportSpellingErrors2"),
	("documentFormatting", "reportTableHeaders"),
	("speechViewer", "autoPositionWindow"),
	("speechViewer", "x"),
	("speechViewer", "y"),
	("speechViewer", "width"),
	("speechViewer", "height"),
	("brailleViewer", "autoPositionWindow"),
	("brailleViewer", "x"),
	("brailleViewer", "y"),
}

#: Claves que no tienen sentido en Tiresias y se ignoran sin avisar.
_QUIET_KEYS = {
	("", "schemaVersion"),
	("update", "allowUsageStats"),
	("update", "askedAllowUsageStats"),
	("update", "serverURL"),
	("speechViewer", "displays"),
	("brailleViewer", "displays"),
	("documentFormatting", "autoLanguageSwitching"),
	("addonStore", "baseServerURL"),
	("remote", "enabled"),
}
#: Secciones que se ignoran sin avisar (datos internos o de estado).
_QUIET_SECTIONS = {
	"remote/connections",
	"remote/seenMOTDs",
	"remote/trustedCertificates",
	"debugLog",
}

#: Secciones de nvda.ini que pertenecen al propio NVDA (las demás son de complementos).
_NVDA_SECTIONS = {
	"general",
	"speech",
	"audio",
	"braille",
	"vision",
	"magnifier",
	"presentation",
	"mouse",
	"speechViewer",
	"brailleViewer",
	"keyboard",
	"virtualBuffers",
	"touch",
	"documentFormatting",
	"documentNavigation",
	"reviewCursor",
	"UIA",
	"annotations",
	"terminals",
	"update",
	"inputComposition",
	"debugLog",
	"uwpOcr",
	"editableText",
	"development",
	"featureFlag",
	"addonStore",
	"remote",
	"math",
	"screenCurtain",
}

# ---------------------------------------------------------------------- sintetizadores
#: Controladores de NVDA basados en Eloquence (IBMTTS): todos van al complemento
#: Eloquence de Tiresias, que se llama ``ibmtts``.
ELOQUENCE_DRIVERS = ("ibmeci", "ibmtts", "eloquence", "eloquence64pro", "ibmttsprofesional64", "voiceibmtts64", "openevv64", "openevv", "eci")
#: Nombres del controlador SAPI 4 en NVDA (``sapi4_32`` desde 2026.1): van a ``sapi4``.
SAPI4_DRIVERS = ("sapi4_32", "sapi4")
#: Controladores de NVDA cuya escala de velocidad coincide con la de Tiresias (40 a 156).
_ELOQUENCE_SAME_SCALE = ("ibmeci", "ibmtts")


def tiresiasSynthName(nvdaName: str) -> str | None:
	"""Sintetizador de Tiresias equivalente a uno de NVDA (``None`` si no lo hay)."""
	low = (nvdaName or "").strip().lower()
	if low in ELOQUENCE_DRIVERS:
		return "ibmtts"
	if low in ("espeak", "espeak-ng", "espeakng"):
		return "espeak"
	if low == "onecore":
		return "onecore"
	if low in ("sapi5", "sapi5_64"):
		return "sapi5"
	# NVDA 2026.1: voces SAPI 5 de 32 bits y SAPI 4 (antes «sapi4») con un proceso de 32 bits.
	if low == "sapi5_32":
		return "sapi5_32"
	if low in SAPI4_DRIVERS:
		return "sapi4"
	if low in ("silence", "nullsynth"):
		return "silence"
	if low == "auto":
		return "auto"
	return None


def synthDisplayName(name: str) -> str:
	return {
		"ibmtts": "Eloquence (IBMTTS)",
		"espeak": "eSpeak NG",
		"onecore": _("Voces de Windows OneCore"),
		"sapi5": "Microsoft SAPI 5",
		"sapi5_32": "Microsoft SAPI 5 (32 bits)",
		"sapi4": "Microsoft SAPI 4",
		"silence": _("Sin voz"),
		"auto": _("Automático"),
	}.get(name, name)


#: Idiomas de Eloquence: código de archivo -> (código ECI, idioma).
ECI_LANGUAGES = {
	"esp": (0x00020000, "es_ES"),
	"esm": (0x00020001, "es_MX"),
	"enu": (0x00010000, "en_US"),
	"eng": (0x00010001, "en_GB"),
	"fra": (0x00030000, "fr_FR"),
	"frc": (0x00030001, "fr_CA"),
	"deu": (0x00040000, "de_DE"),
	"ita": (0x00050000, "it_IT"),
	"chs": (0x00060000, "zh_CN"),
	"ptb": (0x00070000, "pt_BR"),
	"jpn": (0x00080000, "ja_JP"),
	"fin": (0x00090000, "fi_FI"),
	"kor": (0x000A0000, "ko_KR"),
	"ctt": (0x000B0001, "zh_HK"),
	"nor": (0x000D0000, "nb_NO"),
	"swe": (0x000E0000, "sv_SE"),
	"dan": (0x000F0000, "da_DK"),
}
#: Palabras de los nombres visibles de las voces de Eloquence (inglés y español).
_ECI_NAME_WORDS = (
	("castil", "esp"),
	("spain", "esp"),
	("españa", "esp"),
	("latin", "esm"),
	("latino", "esm"),
	("mexic", "esm"),
	("british", "eng"),
	("británico", "eng"),
	("american english", "enu"),
	("estadounidense", "enu"),
	("canad", "frc"),
	("french", "fra"),
	("francés", "fra"),
	("german", "deu"),
	("alemán", "deu"),
	("italian", "ita"),
	("italiano", "ita"),
	("portug", "ptb"),
	("finn", "fin"),
	("finés", "fin"),
	("chinese", "chs"),
	("chino", "chs"),
	("cantonese", "ctt"),
	("cantonés", "ctt"),
	("japanese", "jpn"),
	("japonés", "jpn"),
	("korean", "kor"),
	("coreano", "kor"),
	("norweg", "nor"),
	("noruego", "nor"),
	("swed", "swe"),
	("sueco", "swe"),
	("danish", "dan"),
	("danés", "dan"),
	("english", "enu"),
	("inglés", "enu"),
	("spanish", "esp"),
	("español", "esp"),
)


def eciVoice(raw: Any) -> str | None:
	"""Voz de Eloquence de NVDA («131072», «131072:1», «esp», «es_ES»...) -> código ECI."""
	s = _text(raw).strip()
	if not s:
		return None
	if ":" in s and s.split(":", 1)[0].isdigit():
		s = s.split(":", 1)[0]
	if s.isdigit():
		return s
	low = s.lower()
	if low in ECI_LANGUAGES:
		return str(ECI_LANGUAGES[low][0])
	norm = low.replace("-", "_")
	for num, loc in ECI_LANGUAGES.values():
		if loc.lower() == norm:
			return str(num)
	base = norm.split("_")[0]
	for num, loc in ECI_LANGUAGES.values():
		if loc.lower().split("_")[0] == base:
			return str(num)
	return None


def eciVoiceFromDisplayName(name: str) -> str | None:
	"""Voz de Eloquence a partir del nombre visible («Castilian Spanish»...)."""
	direct = eciVoice(name)
	if direct:
		return direct
	low = (name or "").lower()
	for word, code in _ECI_NAME_WORDS:
		if word in low:
			return str(ECI_LANGUAGES[code][0])
	return None


def _eciSampleRate(v: Any) -> str:
	s = _text(v).strip()
	if s in ("0", "1"):
		return s
	try:
		n = toInt(s)
	except ValueError:
		raise _NoEquivalent(_("frecuencia desconocida")) from None
	if n in (8000,):
		return "0"
	if n in (11025, 1):
		return "1"
	raise _NoEquivalent(_("Eloquence en Tiresias funciona a 8 u 11 kHz; se usa 11 kHz"))


def _espeakVoice(v: Any) -> str:
	"""Voz de eSpeak de NVDA («roa/pt-BR», «roa\\es-419») -> identificador de Tiresias («pt-br»).

	NVDA guarda el identificador completo con la barra de Windows si nunca se
	cambió la voz. El controlador de eSpeak de Tiresias también reconoce los
	nombres de archivo de NVDA que no coinciden con el idioma («en» -> «en-gb»).
	"""
	return _text(v).strip().replace("\\", "/").split("/")[-1].lower()


#: Ajustes de los controladores de Eloquence: clave de NVDA -> (clave de Tiresias, conversión).
_ECI_KEYS: dict[str, tuple[str, Callable[[Any], Any]]] = {
	"variant": ("variant", lambda v: str(toInt(v))),
	"rate": ("rate", _clampInt(0, 100)),
	"pitch": ("pitch", _clampInt(0, 100)),
	"inflection": ("inflection", _clampInt(0, 100)),
	"volume": ("volume", _clampInt(0, 100)),
	"rateboost": ("rateBoost", toBool),
	"hsz": ("headSize", _clampInt(0, 100)),
	"headsize": ("headSize", _clampInt(0, 100)),
	"rgh": ("roughness", _clampInt(0, 100)),
	"roughness": ("roughness", _clampInt(0, 100)),
	"bth": ("breathiness", _clampInt(0, 100)),
	"breathiness": ("breathiness", _clampInt(0, 100)),
	"samplerate": ("sampleRate", _eciSampleRate),
	"pausemode": ("pauseMode", lambda v: str(max(0, min(2, toInt(v))))),
	"phraseprediction": ("phrasePrediction", toBool),
	"abrdict": ("abbreviationDictionary", toBool),
	"abbreviationexpansion": ("abbreviationDictionary", toBool),
	"abbreviationdictionary": ("abbreviationDictionary", toBool),
	"backquotevoicetags": ("backquoteVoiceTags", toBool),
	"backquotetags": ("backquoteVoiceTags", toBool),
}
_ESPEAK_KEYS: dict[str, tuple[str, Callable[[Any], Any]]] = {
	# «roa/pt-BR» en NVDA; en Tiresias las voces de eSpeak son los idiomas en minúsculas («pt-br»).
	"voice": ("voice", _espeakVoice),
	"variant": ("variant", lambda v: _text(v).strip()),
	"rate": ("rate", _clampInt(0, 100)),
	"pitch": ("pitch", _clampInt(0, 100)),
	"inflection": ("inflection", _clampInt(0, 100)),
	"volume": ("volume", _clampInt(0, 100)),
	"rateboost": ("rateBoost", toBool),
}
_ONECORE_KEYS: dict[str, tuple[str, Callable[[Any], Any]]] = {
	"voice": ("voice", lambda v: _text(v).strip()),
	"rate": ("rate", _clampInt(0, 100)),
	"pitch": ("pitch", _clampInt(0, 100)),
	"volume": ("volume", _clampInt(0, 100)),
	"rateboost": ("rateBoost", toBool),
	"punctuationsilence": ("punctuationPause", toBool),
}
_SAPI5_KEYS: dict[str, tuple[str, Callable[[Any], Any]]] = {
	"voice": ("voice", lambda v: _text(v).strip()),
	"rate": ("rate", _clampInt(0, 100)),
	"pitch": ("pitch", _clampInt(0, 100)),
	"volume": ("volume", _clampInt(0, 100)),
	"rateboost": ("rateBoost", toBool),
}
#: SAPI 4: la voz es el GUID del modo («{...}»), en mayúsculas como lo da el auxiliar.
_SAPI4_KEYS: dict[str, tuple[str, Callable[[Any], Any]]] = {
	"voice": ("voice", lambda v: _text(v).strip().upper()),
	"rate": ("rate", _clampInt(0, 100)),
	"pitch": ("pitch", _clampInt(0, 100)),
	"volume": ("volume", _clampInt(0, 100)),
}
#: Ajustes de mayúsculas, que en NVDA son de cada sintetizador y en Tiresias generales.
_CAPITAL_KEYS = (
	("capPitchChange", "speech.capitalPitchChange", _clampInt(-100, 100), "30"),
	("sayCapForCapitals", "speech.sayCapitalForCapitals", toBool, "False"),
	("beepForCapitals", "speech.beepForCapitals", toBool, "False"),
	("useSpellingFunctionality", "speech.useSpellingFunctionality", toBool, "True"),
)
_CAPITAL_NVDA_KEYS = {k.lower() for k, *_rest in _CAPITAL_KEYS}

# ---------------------------------------------------------------------- braille
#: Controladores de líneas braille de NVDA con otro nombre en Tiresias.
_BRAILLE_DRIVER_NAMES = {
	"hidbraillestandard": "hidBraille",
	"seikantk": "seikaNotetaker",
	"papenmeier_serial": "papenmeier",
	"virtualbraille": "viewer",
	"nobraille": "noBraille",
	"auto": "auto",
}
#: Tablas de liblouis que NVDA ha renombrado (nombre antiguo -> nuevo).
_RENAMED_TABLES = {
	"ar-fa.utb": "fa-ir-g1.utb",
	"da-dk-g16.utb": "da-dk-g16.ctb",
	"da-dk-g18.utb": "da-dk-g18.ctb",
	"de-de-g0.utb": "de-g0.utb",
	"de-de-g1.ctb": "de-g1.ctb",
	"de-de-g2.ctb": "de-g2.ctb",
	"en-us-comp8.ctb": "en-us-comp8-ext.utb",
	"fr-ca-g1.utb": "fr-bfu-comp6.utb",
	"fr-ca-g2.ctb": "fr-bfu-g2.ctb",
	"gr-gr-g1.utb": "el.ctb",
	"he.ctb": "he-IL-comp8.utb",
	"hr.ctb": "hr-comp8.utb",
	"lt.ctb": "lt-8dot.utb",
	"nl-be-g0.utb": "nl-NL-g0.utb",
	"nl-nl-g1.ctb": "nl-NL-g0.utb",
	"no-no.ctb": "no-no-8dot.utb",
	"no-no-comp8.ctb": "no-no-8dot.utb",
	"ru-compbrl.ctb": "ru-comp6.utb",
	"ru.ctb": "ru-comp8.utb",
	"se-se-g1.utb": "sv-g0.utb",
	"sk-sk-g1.utb": "sk-g1.ctb",
	"uebc-g1.ctb": "en-ueb-g1.ctb",
	"uebc-g2.ctb": "en-ueb-g2.ctb",
	"vi-g1.ctb": "vi-vn-g1.ctb",
}


def _brailleDriverNames() -> list[str]:
	try:
		from .braille import drivers

		return list(drivers.DRIVER_NAMES)
	except Exception:
		return [
			"alva",
			"baum",
			"brailleNote",
			"brailliantB",
			"brltty",
			"eurobraille",
			"freedomScientific",
			"handyTech",
			"hidBraille",
			"hims",
			"papenmeier",
			"seika",
			"seikaNotetaker",
		]


def tiresiasBrailleDriver(nvdaName: str) -> str | None:
	low = (nvdaName or "").strip().lower()
	if low in _BRAILLE_DRIVER_NAMES:
		return _BRAILLE_DRIVER_NAMES[low]
	for name in _brailleDriverNames():
		if name.lower() == low:
			return name
	return None


def _louisTableFiles() -> dict[str, str]:
	"""{nombre en minúsculas: nombre real} de las tablas de liblouis de Tiresias."""
	try:
		from .braille import liblouis

		folder = liblouis.TABLES_DIR
	except Exception:
		folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "braille", "louis", "tables")
	try:
		return {fn.lower(): fn for fn in os.listdir(folder)}
	except OSError:
		return {}


def tiresiasBrailleTable(nvdaName: str) -> str | None:
	"""Tabla de Tiresias para una tabla de NVDA (los dos usan liblouis)."""
	name = (nvdaName or "").strip()
	if not name or name.lower() == "auto":
		return "auto"
	name = _RENAMED_TABLES.get(name.lower(), name)
	files = _louisTableFiles()
	if name.lower() in files:
		return files[name.lower()]
	# Tablas JSON propias del usuario de Tiresias con el mismo nombre.
	stem = os.path.splitext(name)[0]
	if os.path.isfile(os.path.join(paths.brailleTablesDir(), stem + ".json")):
		return stem
	return None


# ====================================================================== lectura de NVDA
def defaultNvdaFolder() -> str:
	"""Carpeta de configuración de NVDA instalado."""
	return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "nvda")


def resolveFolder(path: str | None = None) -> str | None:
	"""Carpeta con ``nvda.ini``.

	Admite la carpeta de configuración, la carpeta de NVDA portable (con
	``userConfig``), el propio ``nvda.ini`` o ``nvda.exe``. Sin ``path``, la de
	NVDA instalado.
	"""
	candidates: list[str] = []
	if path:
		p = os.path.abspath(os.path.expandvars(path.strip().strip('"')))
		if os.path.isfile(p):
			p = os.path.dirname(p)
		candidates += [p, os.path.join(p, "userConfig")]
	else:
		candidates.append(defaultNvdaFolder())
	for c in candidates:
		if os.path.isfile(os.path.join(c, "nvda.ini")):
			return c
	return None


def findNvdaConfig() -> str | None:
	"""Carpeta de configuración de NVDA instalado, si existe."""
	return resolveFolder(None)


@dataclass
class DictFile:
	kind: str  # "default", "temp" o "voice"
	path: str
	synth: str = ""
	voiceName: str = ""


class NvdaConfig:
	"""Configuración de NVDA leída de una carpeta (sin modificar nada)."""

	def __init__(self, folder: str) -> None:
		self.folder = folder
		self.isPortable = os.path.basename(os.path.normpath(folder)).lower() == "userconfig"
		self.errors: list[str] = []
		self.ini: dict = self._read("nvda.ini") or {}
		self.profiles: dict[str, dict] = {}
		profDir = os.path.join(folder, "profiles")
		if os.path.isdir(profDir):
			for fn in sorted(os.listdir(profDir)):
				if fn.lower().endswith(".ini"):
					data = self._read(os.path.join("profiles", fn))
					if data is not None:
						self.profiles[fn[:-4]] = data
		triggers = self._read("profileTriggers.ini") or {}
		section = triggers.get("triggersToProfiles", {})
		self.triggers: dict[str, str] = {k: _text(v) for k, v in section.items() if not isinstance(v, dict)} if isinstance(section, dict) else {}
		self.gestures: dict = self._read("gestures.ini") or {}
		self.dicts: list[DictFile] = self._findDicts()
		self.symbolFiles: list[tuple[str, str]] = []
		for fn in sorted(os.listdir(folder)):
			m = re.match(r"^symbols-(.+)\.dic$", fn, re.I)
			if m:
				self.symbolFiles.append((m.group(1), os.path.join(folder, fn)))
		self.addons: list[tuple[str, bool]] = self._findAddons()
		self.labelNotes: list[str] = self._findLabels()

	def _read(self, rel: str) -> dict | None:
		path = os.path.join(self.folder, rel)
		if not os.path.isfile(path):
			return None
		try:
			return readIni(path)
		except OSError as e:
			self.errors.append(_("No se pudo leer {file}: {error}").format(file=rel, error=e))
			return None

	def _findDicts(self) -> list[DictFile]:
		out: list[DictFile] = []
		base = os.path.join(self.folder, "speechDicts")
		if not os.path.isdir(base):
			return out
		for fn in sorted(os.listdir(base)):
			path = os.path.join(base, fn)
			if not os.path.isfile(path) or not fn.lower().endswith(".dic"):
				continue
			low = fn.lower()
			if low == "default.dic":
				out.append(DictFile("default", path))
			elif low == "temp.dic":
				out.append(DictFile("temp", path))
			elif low == "builtin.dic":
				continue
			elif "-" in fn:
				# Formato antiguo: speechDicts\<sintetizador>-<voz>.dic
				synth, voice = fn[:-4].split("-", 1)
				out.append(DictFile("voice", path, synth, voice))
		for sub in ("voiceDicts.v1", "voiceDicts"):
			vdir = os.path.join(base, sub)
			if not os.path.isdir(vdir):
				continue
			for synth in sorted(os.listdir(vdir)):
				sdir = os.path.join(vdir, synth)
				if not os.path.isdir(sdir):
					continue
				for fn in sorted(os.listdir(sdir)):
					if not fn.lower().endswith(".dic"):
						continue
					stem = fn[:-4]
					voice = stem[len(synth) + 1 :] if stem.lower().startswith(synth.lower() + "-") else stem
					out.append(DictFile("voice", os.path.join(sdir, fn), synth, voice))
			break
		return out

	def _findAddons(self) -> list[tuple[str, bool]]:
		folder = os.path.join(self.folder, "addons")
		disabled: set[str] = set()
		try:
			with open(os.path.join(self.folder, "addonsState.json"), encoding="utf-8") as f:
				disabled = {str(x).lower() for x in json.load(f).get("disabledAddons", [])}
		except (OSError, ValueError, AttributeError):
			pass
		out = []
		if os.path.isdir(folder):
			for fn in sorted(os.listdir(folder), key=str.lower):
				if os.path.isfile(os.path.join(folder, fn, "manifest.ini")):
					out.append((fn, fn.lower() in disabled))
		return out

	def _findLabels(self) -> list[str]:
		"""Etiquetas de complementos: se buscan y se informa de ellas."""
		notes: list[str] = []
		try:
			entries = sorted(os.listdir(self.folder))
		except OSError:
			return notes
		for fn in entries:
			low = fn.lower()
			if not ("label" in low or "etiqueta" in low):
				continue
			path = os.path.join(self.folder, fn)
			target = None
			if os.path.isfile(path) and low.endswith(".json"):
				try:
					with open(path, encoding="utf-8") as f:
						data = json.load(f)
					if isinstance(data, dict):
						target = next((v for v in data.values() if isinstance(v, str) and v.lower().endswith((".json", ".ini"))), None)
				except (OSError, ValueError):
					pass
			if target:
				state = _("existe") if os.path.isfile(target) else _("no existe")
				notes.append(_("{file}: indica el archivo de etiquetas {target} ({state})").format(file=fn, target=target, state=state))
			else:
				notes.append(fn)
		return notes

	# --------------------------------------------------------------- resumen
	def summaryLines(self) -> list[str]:
		lines = [
			_("Carpeta: {folder}").format(folder=self.folder),
			_("Tipo: {kind}").format(kind=_("NVDA portable") if self.isPortable else _("NVDA instalado")),
		]
		if self.ini:
			lines.append(_("nvda.ini: sí ({count} secciones)").format(count=len([k for k, v in self.ini.items() if isinstance(v, dict)])))
			synth = self.ini.get("speech", {}).get("synth") if isinstance(self.ini.get("speech"), dict) else None
			if synth:
				lines.append(_("Sintetizador de NVDA: {synth}").format(synth=_text(synth)))
		else:
			lines.append(_("nvda.ini: no se ha podido leer"))
		lines.append(_("Perfiles: {count}").format(count=len(self.profiles)) + (" (" + ", ".join(self.profiles) + ")" if self.profiles else ""))
		lines.append(_("Disparadores de perfiles: {count}").format(count=len(self.triggers)))
		nGest = sum(len([k for k, v in sec.items() if not isinstance(v, dict)]) for sec in self.gestures.values() if isinstance(sec, dict))
		lines.append(_("Gestos personalizados (gestures.ini): {count} en {sections} secciones").format(count=nGest, sections=len(self.gestures)))
		kinds = {"default": _("por defecto"), "temp": _("temporal"), "voice": _("de voz")}
		if self.dicts:
			for d in self.dicts:
				extra = f" ({d.synth} - {d.voiceName})" if d.kind == "voice" else ""
				lines.append(_("Diccionario {kind}{extra}: {count} entradas").format(kind=kinds[d.kind], extra=extra, count=len(parseSpeechDict(d.path)[0])))
		else:
			lines.append(_("Diccionarios de voz: ninguno"))
		if self.symbolFiles:
			lines.append(_("Símbolos personalizados: {files}").format(files=", ".join(os.path.basename(p) for _l, p in self.symbolFiles)))
		else:
			lines.append(_("Símbolos personalizados: ninguno"))
		if self.labelNotes:
			lines.append(_("Etiquetas de complementos: {items}").format(items="; ".join(self.labelNotes)))
		else:
			lines.append(_("Etiquetas de complementos: ninguna"))
		enabled = [n for n, dis in self.addons if not dis]
		lines.append(_("Complementos de NVDA instalados: {count} ({enabled} activados)").format(count=len(self.addons), enabled=len(enabled)))
		lines.extend(self.errors)
		return lines


# ====================================================================== diccionarios y símbolos
#: Tipos de entrada de los diccionarios de NVDA -> tipos de Tiresias.
_DICT_TYPES = {0: "anywhere", 1: "regex", 2: "word", 3: "partOfWord", 4: "startOfWord", 5: "endOfWord"}


def parseSpeechDict(path: str) -> tuple[list[dict], list[str]]:
	"""Lee un diccionario de NVDA. Devuelve (entradas de Tiresias, problemas)."""
	entries: list[dict] = []
	problems: list[str] = []
	try:
		with open(path, encoding="utf-8-sig", errors="replace") as f:
			lines = f.read().splitlines()
	except OSError as e:
		return entries, [str(e)]
	comment = ""
	for line in lines:
		if not line.strip():
			comment = ""
			continue
		if line.startswith("#"):
			comment = (comment + " " if comment else "") + line[1:]
			continue
		parts = line.split("\t")
		if len(parts) != 4:
			problems.append(_("línea no válida: {line}").format(line=line[:60]))
			comment = ""
			continue
		pattern = parts[0].replace("\\#", "#")
		replacement = parts[1].replace("\\#", "#")
		try:
			caseSensitive = bool(int(parts[2]))
			kind = int(parts[3])
		except ValueError:
			problems.append(_("línea no válida: {line}").format(line=line[:60]))
			comment = ""
			continue
		if kind == 6:
			# Comodines de la consola de Unix (* ? [..]): se convierten a expresión regular.
			pattern, tType = _wildcardToRegex(pattern), "regex"
			# En NVDA el reemplazo de estas entradas es literal; en una expresión
			# regular de Tiresias las barras invertidas serían referencias (\1...).
			replacement = replacement.replace("\\", "\\\\")
		else:
			tType = _DICT_TYPES.get(kind, "anywhere")
		if tType == "regex":
			try:
				re.compile(pattern)
			except re.error:
				problems.append(_("expresión regular no válida en Tiresias: {pattern}").format(pattern=pattern[:60]))
				comment = ""
				continue
		entries.append({"pattern": pattern, "replacement": replacement, "caseSensitive": caseSensitive, "type": tType, "comment": comment.strip(), "enabled": True})
		comment = ""
	return entries, problems


def _wildcardToRegex(pattern: str) -> str:
	"""Comodines de Unix -> expresión regular que busca en cualquier parte del texto.

	``fnmatch.translate`` ancla el final con ``\\Z`` (o con ``\\z`` desde
	Python 3.14); se quita el ancla, como hace NVDA con estas entradas.
	"""
	translated = fnmatch.translate(pattern)
	for suffix in ("\\Z", "\\z"):
		if translated.endswith(suffix):
			return translated[: -len(suffix)]
	return translated


_SYMBOL_ESCAPES = {"0": "\0", "t": "\t", "n": "\n", "r": "\r", "f": "\f", "v": "\v", "#": "#", "\\": "\\"}
_SYMBOL_LEVELS = {"none": 0, "some": 100, "most": 200, "all": 300, "char": 1000}
_SYMBOL_PRESERVE = ("never", "always", "norep")


def parseSymbolsFile(path: str) -> tuple[list[dict], list[str], set[str]]:
	"""Lee ``symbols-<idioma>.dic`` de NVDA.

	Devuelve (símbolos, problemas, identificadores complejos). Cada símbolo es
	``{"symbol", "name", "level", "preserve", "displayName"}``; ``None`` en
	``name``, ``level`` o ``preserve`` significa «heredar» (``-`` en NVDA). Un
	nombre vacío (``""``) es «no decir nada», como en NVDA.
	"""
	symbols: list[dict] = []
	problems: list[str] = []
	complexIds: set[str] = set()
	try:
		with open(path, encoding="utf-8-sig", errors="replace") as f:
			lines = f.read().splitlines()
	except OSError as e:
		return symbols, [str(e)], complexIds
	section = None
	for line in lines:
		if not line or line.startswith("#"):
			continue
		stripped = line.strip()
		if stripped in ("complexSymbols:", "symbols:"):
			section = stripped[:-1]
			continue
		if section == "complexSymbols":
			ident = line.split("\t", 1)[0]
			if ident:
				complexIds.add(ident)
			continue
		if section != "symbols":
			continue
		fields = line.split("\t")
		display = ""
		if len(fields) > 1 and fields[-1].startswith("#"):
			display = fields.pop()[1:].strip()
		if len(fields) < 2 or not fields[0]:
			problems.append(_("línea no válida: {line}").format(line=line[:60]))
			continue
		ident = fields[0]
		if ident.startswith("\\") and len(ident) >= 2:
			ident = _SYMBOL_ESCAPES.get(ident[1], ident[1]) + ident[2:]

		name = _symbolField(fields, 1)
		levelRaw = _symbolField(fields, 2)
		preserveRaw = _symbolField(fields, 3)
		level = _SYMBOL_LEVELS.get(levelRaw.lower()) if levelRaw else None
		preserve = preserveRaw.lower() if preserveRaw and preserveRaw.lower() in _SYMBOL_PRESERVE else None
		symbols.append({"symbol": ident, "name": name, "level": level, "preserve": preserve, "displayName": display})
	return symbols, problems, complexIds


def _symbolField(fields: list[str], i: int) -> str | None:
	"""Campo ``i`` de una línea de símbolos de NVDA; ``None`` (hereda) si falta o es «-».

	Un campo vacío no es «heredar»: en el nombre significa «no decir nada».
	"""
	if i >= len(fields):
		return None
	v = fields[i]
	return None if v == "-" else v


def _isComplexIdentifier(ident: str, complexIds: set[str]) -> bool:
	"""Los símbolos «complejos» de NVDA («sentence ending», «decimal point»...) son
	expresiones regulares con nombre; Tiresias solo tiene símbolos literales."""
	if ident in complexIds:
		return True
	return len(ident) > 1 and " " in ident and any(c.isalpha() for c in ident)


# ====================================================================== plan
@dataclass
class Change:
	category: str
	path: tuple[str, ...]
	value: Any
	source: str
	fromDefault: bool = False
	old: Any = _MISSING

	@property
	def changes(self) -> bool:
		return self.old is _MISSING or self.old != self.value


@dataclass
class Notice:
	category: str
	text: str


@dataclass
class GestureChange:
	classKey: str
	gesture: str
	script: str
	source: str
	replaces: str | None = None


@dataclass
class DictImport:
	kind: str  # "default" o "voice"
	target: str  # ruta relativa a la carpeta speechDicts
	entries: list[dict]
	source: str
	label: str


@dataclass
class SymbolImport:
	language: str
	target: str  # nombre del archivo en la carpeta de configuración
	symbols: list[dict]
	source: str


@dataclass
class ProfileImport:
	name: str
	changes: list[Change]
	triggers: list[str]
	exists: bool = False


@dataclass
class Plan:
	folder: str
	isPortable: bool
	summary: list[str] = field(default_factory=list)
	changes: list[Change] = field(default_factory=list)
	profiles: list[ProfileImport] = field(default_factory=list)
	gestures: list[GestureChange] = field(default_factory=list)
	dicts: list[DictImport] = field(default_factory=list)
	symbols: list[SymbolImport] = field(default_factory=list)
	notices: list[Notice] = field(default_factory=list)
	useNvdaDefaults: bool = True

	def note(self, category: str, text: str) -> None:
		self.notices.append(Notice(category, text))

	def count(self, category: str) -> int:
		if category in SETTING_CATEGORIES:
			return len([c for c in self.changes if c.category == category and c.changes])
		if category == CAT_PROFILES:
			return len(self.profiles)
		if category == CAT_GESTURES:
			return len(self.gestures)
		if category == CAT_DICTS:
			return sum(len(d.entries) for d in self.dicts)
		if category == CAT_SYMBOLS:
			return sum(len(s.symbols) for s in self.symbols)
		return 0

	def toJson(self, categories: set[str] | None = None) -> dict:
		"""Copia exportada de lo que se importa (``configuracion_desde_nvda.json``)."""
		cats = set(CATEGORIES) if categories is None else categories
		base: dict = {}
		for c in self.changes:
			if c.category in cats:
				_setPath(base, c.path, c.value)
		return {
			"origen": self.folder,
			"nvdaPortable": self.isPortable,
			"fecha": datetime.datetime.now().isoformat(timespec="seconds"),
			"configuracion": base,
			"perfiles": {p.name: {"disparadores": p.triggers, "configuracion": _changesDict(p.changes)} for p in self.profiles} if CAT_PROFILES in cats else {},
			"gestos": [{"clase": g.classKey, "gesto": g.gesture, "orden": g.script, "origen": g.source} for g in self.gestures] if CAT_GESTURES in cats else [],
			"diccionarios": [{"tipo": d.kind, "destino": d.target, "entradas": d.entries} for d in self.dicts] if CAT_DICTS in cats else [],
			"simbolos": [{"idioma": s.language, "destino": s.target, "simbolos": s.symbols} for s in self.symbols] if CAT_SYMBOLS in cats else [],
			"avisos": [{"categoria": n.category, "texto": n.text} for n in self.notices if not n.category or n.category in cats],
		}


def _changesDict(changes: list[Change]) -> dict:
	out: dict = {}
	for c in changes:
		_setPath(out, c.path, c.value)
	return out


def _setPath(d: dict, path: tuple[str, ...], value: Any) -> None:
	node = d
	for key in path[:-1]:
		nxt = node.get(key)
		if not isinstance(nxt, dict):
			nxt = {}
			node[key] = nxt
		node = nxt
	node[path[-1]] = copy.deepcopy(value)


def _getPath(d: dict, path: tuple[str, ...]) -> Any:
	node: Any = d
	for key in path:
		if not isinstance(node, dict) or key not in node:
			return _MISSING
		node = node[key]
	return node


# ---------------------------------------------------------------------- lectura de secciones
def _section(data: dict, secPath: str) -> dict:
	node: Any = data
	if not secPath:
		return data
	for part in secPath.split("/"):
		if not isinstance(node, dict):
			return {}
		node = node.get(part)
	return node if isinstance(node, dict) else {}


class _Mapper:
	"""Convierte un nvda.ini (o un perfil) en cambios de Tiresias."""

	def __init__(self, data: dict, plan: Plan, isProfile: bool, useDefaults: bool, label: str = "", baseSynth: str = "", baseMathLang: str = "") -> None:
		self.data = data
		self.plan = plan
		self.isProfile = isProfile
		self.useDefaults = useDefaults and not isProfile
		self.label = label
		#: Sintetizador de la configuración normal (un perfil puede no indicarlo).
		self.baseSynth = baseSynth
		#: Idioma de las matemáticas de la configuración normal (ídem).
		self.baseMathLang = baseMathLang
		self.changes: list[Change] = []
		self.consumed: set[tuple[str, str]] = set()

	def note(self, category: str, text: str) -> None:
		self.plan.note(category, f"{self.label}: {text}" if self.label else text)

	def raw(self, secPath: str, key: str) -> Any:
		sec = _section(self.data, secPath)
		v = sec.get(key, _MISSING)
		if isinstance(v, dict):
			return _MISSING
		return v

	def add(self, category: str, tPath: str | tuple[str, ...], value: Any, source: str, fromDefault: bool = False) -> None:
		path = tuple(tPath.split(".")) if isinstance(tPath, str) else tPath
		# Una misma opción de Tiresias puede venir de dos claves (nueva y antigua):
		# gana la escrita en el archivo sobre el valor por defecto.
		for i, c in enumerate(self.changes):
			if c.path == path:
				if c.fromDefault and not fromDefault:
					self.changes[i] = Change(category, path, value, source, fromDefault)
				return
		self.changes.append(Change(category, path, value, source, fromDefault))

	def run(self) -> list[Change]:
		for cat, secPath, key, tPath, conv, default in ROWS:
			self._row(cat, secPath, key, tPath, conv, default)
		self._synths()
		self._keyboardModifiers()
		self._braille()
		self._audioDevice()
		self._documentFormattingSpecial()
		self._mathSpeechStyle()
		self._viewerPositions()
		self._vision()
		self._unknownKeys()
		return self.changes

	def _row(self, cat: str, secPath: str, key: str, tPath: str, conv: Callable, default: str | None) -> None:
		self.consumed.add((secPath, key))
		raw = self.raw(secPath, key)
		fromDefault = False
		if raw is _MISSING:
			if default is None or not self.useDefaults:
				return
			raw, fromDefault = default, True
		elif default is not None and _flagName(raw) == "default":
			# Indicador «DEFAULT» escrito: es el comportamiento por defecto de NVDA.
			# En la configuración normal se aplica si se piden los valores por
			# defecto; en un perfil, siempre (tapa el valor de la configuración normal).
			if not (self.useDefaults or self.isProfile):
				return
			raw, fromDefault = default, True
		source = f"{secPath.replace('/', '.')}.{key}"
		try:
			value = conv(raw)
		except _Silent:
			return
		except _NoEquivalent as e:
			self.note(cat, _("{key} = {value}: {reason}").format(key=source, value=_text(raw), reason=e))
			return
		except (ValueError, TypeError):
			self.note(cat, _("{key} = {value}: valor no válido, no se importa").format(key=source, value=_text(raw)))
			return
		self.add(cat, tPath, value, source, fromDefault)

	# ------------------------------------------------------------ voz
	def _synths(self) -> None:
		speech = _section(self.data, "speech")
		nvdaSynth = speech.get("synth")
		subsections = {k: v for k, v in speech.items() if isinstance(v, dict)}
		if isinstance(nvdaSynth, str) and nvdaSynth:
			tName = tiresiasSynthName(nvdaSynth)
			if tName:
				self.add(CAT_SPEECH, "speech.synth", tName, "speech.synth")
			else:
				self.note(
					CAT_SPEECH,
					_("el sintetizador «{synth}» de NVDA no existe en Tiresias: se mantiene el de Tiresias (en automático, Eloquence si está disponible)").format(synth=nvdaSynth),
				)
		elif self.useDefaults:
			self.add(CAT_SPEECH, "speech.synth", "auto", "speech.synth", True)
		# Controlador de Eloquence que se usa (puede haber varios).
		eloquence = [k for k in subsections if k.lower() in ELOQUENCE_DRIVERS]
		chosen = None
		if isinstance(nvdaSynth, str) and nvdaSynth in eloquence:
			chosen = nvdaSynth
		elif eloquence:
			chosen = sorted(eloquence, key=lambda k: ELOQUENCE_DRIVERS.index(k.lower()))[0]
		# SAPI 4 puede estar como «sapi4» (NVDA antiguo) y «sapi4_32» (2026.1): se usa el
		# activo o, si no, el más reciente.
		sapi4 = sorted((k for k in subsections if k.lower() in SAPI4_DRIVERS), key=lambda k: SAPI4_DRIVERS.index(k.lower()))
		chosen4 = nvdaSynth if isinstance(nvdaSynth, str) and nvdaSynth in sapi4 else (sapi4[0] if sapi4 else None)
		for name, sec in subsections.items():
			tName = tiresiasSynthName(name)
			if tName in (None, "auto", "silence"):
				self.note(CAT_SPEECH, _("ajustes del sintetizador «{synth}» de NVDA: no existe en Tiresias").format(synth=name))
				continue
			if tName == "ibmtts" and name != chosen:
				self.note(CAT_SPEECH, _("ajustes de «{synth}» (otro controlador de Eloquence): se usan los de «{chosen}»").format(synth=name, chosen=chosen))
				continue
			if tName == "sapi5" and name.lower() != "sapi5" and any(k.lower() == "sapi5" for k in subsections):
				self.note(CAT_SPEECH, _("ajustes de «{synth}»: se usan los de «sapi5»").format(synth=name))
				continue
			if tName == "sapi4" and name != chosen4:
				self.note(CAT_SPEECH, _("ajustes de «{synth}»: se usan los de «{chosen}»").format(synth=name, chosen=chosen4))
				continue
			self._synthSettings(name, tName, sec)
		# Mayúsculas: en NVDA son del sintetizador activo.
		if not isinstance(nvdaSynth, str) or not nvdaSynth:
			nvdaSynth = self.baseSynth
		active = subsections.get(nvdaSynth) if nvdaSynth else None
		for nKey, tPath, conv, default in _CAPITAL_KEYS:
			raw = (active or {}).get(nKey, _MISSING)
			fromDefault = False
			if raw is _MISSING or isinstance(raw, dict):
				if not self.useDefaults:
					continue
				raw, fromDefault = default, True
			try:
				self.add(CAT_SPEECH, tPath, conv(raw), f"speech.{nvdaSynth}.{nKey}", fromDefault)
			except (ValueError, TypeError):
				self.note(CAT_SPEECH, _("speech.{synth}.{key}: valor no válido").format(synth=nvdaSynth, key=nKey))

	def _synthSettings(self, nvdaName: str, tName: str, sec: dict) -> None:
		keys = {"ibmtts": _ECI_KEYS, "espeak": _ESPEAK_KEYS, "onecore": _ONECORE_KEYS, "sapi5": _SAPI5_KEYS, "sapi5_32": _SAPI5_KEYS, "sapi4": _SAPI4_KEYS}[tName]
		ignored: list[str] = []
		values: dict[str, Any] = {}
		for key, raw in sec.items():
			if isinstance(raw, dict):
				continue
			low = key.lower()
			if low in _CAPITAL_NVDA_KEYS:
				continue
			if tName == "ibmtts" and low == "voice":
				voice = eciVoice(raw)
				if voice is None:
					self.note(CAT_SPEECH, _("{synth}: voz «{voice}» desconocida en Eloquence").format(synth=nvdaName, voice=_text(raw)))
					continue
				values["voice"] = voice
				# «131072:1»: la variante va detrás de la voz.
				s = _text(raw)
				if ":" in s and "variant" not in {k.lower() for k in sec}:
					values["variant"] = s.split(":", 1)[1].strip()
				continue
			if low not in keys:
				ignored.append(key)
				continue
			tKey, conv = keys[low]
			try:
				values[tKey] = conv(raw)
			except _NoEquivalent as e:
				self.note(CAT_SPEECH, f"speech.{nvdaName}.{key} = {_text(raw)}: {e}")
				if tKey == "sampleRate":
					values[tKey] = "1"
			except (ValueError, TypeError):
				self.note(CAT_SPEECH, _("speech.{synth}.{key}: valor no válido").format(synth=nvdaName, key=key))
		if tName == "ibmtts" and nvdaName.lower() not in _ELOQUENCE_SAME_SCALE and "rate" in values:
			self.note(CAT_SPEECH, _("{synth}: la escala de velocidad de este controlador puede ser distinta de la de Tiresias; revisa la velocidad").format(synth=nvdaName))
		if ignored:
			self.note(CAT_SPEECH, _("{synth}: sin equivalente en Tiresias: {keys}").format(synth=nvdaName, keys=", ".join(ignored)))
		for k, v in values.items():
			self.add(CAT_SPEECH, ("speech", "synths", tName, k), v, f"speech.{nvdaName}.{k}")

	# ------------------------------------------------------------ teclado
	def _keyboardModifiers(self) -> None:
		raw = self.raw("keyboard", "NVDAModifierKeys")
		fromDefault = False
		if raw is _MISSING:
			if not self.useDefaults:
				return
			raw, fromDefault = "6", True
		try:
			bits = toInt(raw)
		except ValueError:
			self.note(CAT_KEYBOARD, _("keyboard.NVDAModifierKeys: valor no válido"))
			return
		src = "keyboard.NVDAModifierKeys"
		self.add(CAT_KEYBOARD, "keyboard.useCapsLockAsModifier", bool(bits & 1), src, fromDefault)
		self.add(CAT_KEYBOARD, "keyboard.useNumpadInsertAsModifier", bool(bits & 2), src, fromDefault)
		self.add(CAT_KEYBOARD, "keyboard.useInsertAsModifier", bool(bits & 4), src, fromDefault)

	# ------------------------------------------------------------ braille
	def _braille(self) -> None:
		raw = self.raw("braille", "display")
		fromDefault = False
		if raw is _MISSING and self.useDefaults:
			raw, fromDefault = "auto", True
		if raw is not _MISSING:
			driver = tiresiasBrailleDriver(_text(raw))
			if driver:
				self.add(CAT_BRAILLE, "braille.display", driver, "braille.display", fromDefault)
				if _text(raw).lower() == "virtualbraille":
					self.note(CAT_BRAILLE, _("la línea braille virtual del complemento de NVDA se sustituye por el visor braille en pantalla de Tiresias"))
			else:
				self.note(CAT_BRAILLE, _("la línea braille «{driver}» de NVDA no tiene controlador en Tiresias").format(driver=_text(raw)))
		for key, tPath in (("translationTable", "braille.translationTable"), ("inputTable", "braille.inputTable")):
			raw = self.raw("braille", key)
			fromDefault = False
			if raw is _MISSING:
				if not self.useDefaults:
					continue
				raw, fromDefault = "auto", True
			table = tiresiasBrailleTable(_text(raw))
			if table:
				self.add(CAT_BRAILLE, tPath, table, f"braille.{key}", fromDefault)
			else:
				self.note(CAT_BRAILLE, _("la tabla braille «{table}» no está en Tiresias; se mantiene la actual").format(table=_text(raw)))
		# Ajuste del texto: «textWrap» (nuevo) o «wordWrap» (antiguo).
		raw = self.raw("braille", "textWrap")
		if raw is not _MISSING and _flagName(raw) != "default":
			value = {"none": "none", "markwordcuts": "markWordCuts", "atwordboundaries": "wordBoundaries", "atwordorsyllableboundaries": "syllableBoundaries"}.get(_flagName(raw))
			if value:
				self.add(CAT_BRAILLE, "braille.textWrap", value, "braille.textWrap")
			else:
				self.note(CAT_BRAILLE, _("braille.textWrap = {value}: sin equivalente").format(value=_text(raw)))
		else:
			raw = self.raw("braille", "wordWrap")
			if raw is not _MISSING:
				try:
					self.add(CAT_BRAILLE, "braille.textWrap", "wordBoundaries" if toBool(raw) else "none", "braille.wordWrap")
				except ValueError:
					pass
		# Puertos de cada línea y líneas excluidas de la detección automática.
		braille = _section(self.data, "braille")
		for name, sec in braille.items():
			if not isinstance(sec, dict):
				continue
			if name == "auto":
				excluded = sec.get("excludedDisplays")
				if excluded is not None:
					names = [tiresiasBrailleDriver(n) for n in toList(excluded)]
					self.add(CAT_BRAILLE, "brailleDisplays.excludedFromAuto", [n for n in names if n and n not in ("auto", "noBraille", "viewer")], "braille.auto.excludedDisplays")
				continue
			port = sec.get("port")
			driver = tiresiasBrailleDriver(name)
			if port is None or isinstance(port, dict) or not _text(port).strip():
				continue
			if driver in (None, "auto", "noBraille", "viewer"):
				continue
			self.add(CAT_BRAILLE, ("brailleDisplays", "ports", driver), _text(port).strip(), f"braille.{name}.port")

	# ------------------------------------------------------------ audio
	def _audioDevice(self) -> None:
		raw = self.raw("audio", "outputDevice")
		if raw is _MISSING:
			raw = self.raw("speech", "outputDevice")
		if raw is _MISSING:
			return
		value = _text(raw).strip()
		if not value or value.lower() in ("default", "microsoft sound mapper"):
			self.add(CAT_OTHER, "audio.outputDevice", "", "audio.outputDevice")
			return
		name = _deviceName(value)
		if name:
			self.add(CAT_OTHER, "audio.outputDevice", name, "audio.outputDevice")
		else:
			self.note(CAT_OTHER, _("el dispositivo de salida de audio de NVDA no está conectado ahora; se mantiene el predeterminado de Windows"))

	# ------------------------------------------------------------ formato de documento
	def _fontAttributesBraille(self) -> None:
		"""Atributos de fuente en braille: solo con ``fontAttributeReporting`` 2 o 3.

		Con 0 o 1 NVDA no los muestra en braille, aunque la tabla pueda; si
		ninguna otra fila ha fijado ya el formato en braille, se desactiva.
		"""
		raw = self.raw("documentFormatting", "fontAttributeReporting")
		fromDefault = False
		if raw is _MISSING:
			old = self.raw("documentFormatting", "reportFontAttributes")
			if old is not _MISSING:
				# Versiones antiguas: una casilla para la voz y el braille a la vez.
				try:
					raw = "3" if toBool(old) else "0"
				except ValueError:
					return
			elif self.useDefaults:
				raw, fromDefault = "0", True
			else:
				return
		try:
			mode = _fontAttributeMode(raw)
		except (_NoEquivalent, ValueError):
			return
		src = "documentFormatting.fontAttributeReporting"
		if mode in (0, 1):
			self.add(CAT_BRAILLE, "braille.fontFormattingDisplay", "off", src, fromDefault)
			return
		shown = self.raw("braille", "fontFormattingDisplay")
		if shown is _MISSING or _flagName(shown) == "default":
			# Comportamiento por defecto de NVDA: los indicadores de la tabla (liblouis).
			self.add(CAT_BRAILLE, "braille.fontFormattingDisplay", "liblouis", src, fromDefault)

	def _mathSpeechStyle(self) -> None:
		"""Estilo de voz de las matemáticas: ``math/speech/<idioma>/speechStyle``.

		El idioma es ``math/speech/language`` («en» por defecto; «Auto» es «en»).
		"""
		speech = _section(self.data, "math/speech")
		lang = speech.get("language", _MISSING)
		if lang is _MISSING or isinstance(lang, dict):
			lang = self.baseMathLang or "en"
		lang = _text(lang).strip() or "en"
		if lang.lower() == "auto":
			lang = "en"
		sec = next((v for k, v in speech.items() if isinstance(v, dict) and k.lower() == lang.lower()), None)
		if sec is None:
			return
		raw = sec.get("speechStyle", _MISSING)
		if raw is _MISSING or isinstance(raw, dict) or not _text(raw).strip():
			# Vacío: NVDA elige ClearSpeak, que es el estilo natural de Tiresias.
			return
		source = f"math.speech.{lang}.speechStyle"
		try:
			self.add(CAT_OTHER, "math.style", _mathStyle(raw), source)
		except _NoEquivalent as e:
			self.note(CAT_OTHER, _("{key} = {value}: {reason}").format(key=source, value=_text(raw), reason=e))
		except _Silent:
			pass

	def _documentFormattingSpecial(self) -> None:
		self._fontAttributesBraille()
		raw = self.raw("documentFormatting", "reportSpellingErrors2")
		fromDefault = False
		if raw is _MISSING and self.raw("documentFormatting", "reportSpellingErrors") is _MISSING and self.useDefaults:
			raw, fromDefault = "1", True
		if raw is not _MISSING:
			try:
				bits = toInt(raw)
				self.add(CAT_OTHER, "documentFormatting.reportSpellingErrors", bool(bits & 3), "documentFormatting.reportSpellingErrors2", fromDefault)
				self.add(CAT_BRAILLE, "braille.showSpellingErrors", bool(bits & 4), "documentFormatting.reportSpellingErrors2", fromDefault)
				if bits & 2 and not fromDefault:
					self.note(CAT_OTHER, _("errores ortográficos con sonido: Tiresias los anuncia con voz (y con braille si se elige)"))
			except ValueError:
				self.note(CAT_OTHER, _("documentFormatting.reportSpellingErrors2: valor no válido"))
		raw = self.raw("documentFormatting", "reportTableHeaders")
		fromDefault = False
		if raw is _MISSING and self.useDefaults:
			raw, fromDefault = "1", True
		if raw is not _MISSING:
			try:
				s = _text(raw).strip().lower()
				n = 1 if s == "true" else 0 if s == "false" else toInt(raw)
				self.add(CAT_OTHER, "documentFormatting.reportTableHeaders", n != 0, "documentFormatting.reportTableHeaders", fromDefault)
				if n in (2, 3):
					self.note(CAT_OTHER, _("encabezados de tabla solo de filas o solo de columnas: Tiresias anuncia los dos"))
			except ValueError:
				self.note(CAT_OTHER, _("documentFormatting.reportTableHeaders: valor no válido"))

	# ------------------------------------------------------------ visores
	def _viewerPositions(self) -> None:
		sv = _section(self.data, "speechViewer")
		try:
			if "autoPositionWindow" in sv and not toBool(sv["autoPositionWindow"]):
				pos = [toInt(sv[k]) for k in ("x", "y", "width", "height")]
				self.add(CAT_OTHER, "speechViewer.rememberPosition", True, "speechViewer.autoPositionWindow")
				self.add(CAT_OTHER, "speechViewer.position", pos, "speechViewer.x/y/width/height")
		except (KeyError, ValueError):
			pass
		bv = _section(self.data, "brailleViewer")
		try:
			if "autoPositionWindow" in bv and not toBool(bv["autoPositionWindow"]):
				self.add(CAT_BRAILLE, "brailleViewer.x", toInt(bv["x"]), "brailleViewer.x")
				self.add(CAT_BRAILLE, "brailleViewer.y", toInt(bv["y"]), "brailleViewer.y")
		except (KeyError, ValueError):
			pass

	# ------------------------------------------------------------ visión
	def _vision(self) -> None:
		hl = _section(self.data, "vision/NVDAHighlighter")
		if not hl:
			return
		try:
			enabled = toBool(hl.get("enabled", "False"))
			for key in ("highlightFocus", "highlightNavigator", "highlightBrowseMode"):
				value = enabled and toBool(hl.get(key, "True"))
				self.add(CAT_OTHER, ("vision", key), value, f"vision.NVDAHighlighter.{key}")
		except ValueError:
			self.note(CAT_OTHER, _("vision.NVDAHighlighter: valor no válido"))

	# ------------------------------------------------------------ claves sin equivalente
	def _unknownKeys(self) -> None:
		addonSections: list[str] = []
		synthInternals: list[str] = []

		def walk(node: dict, prefix: str) -> None:
			for key, value in node.items():
				if isinstance(value, dict):
					sub = f"{prefix}/{key}" if prefix else key
					if not prefix and key not in _NVDA_SECTIONS:
						if key.lower() in ELOQUENCE_DRIVERS or key.lower() in ("ibmeci",):
							synthInternals.append(key)
						else:
							addonSections.append(key)
						continue
					if sub in _QUIET_SECTIONS or sub.startswith(("speech/", "math/", "remote/controlServer", "vision/")):
						# speech/<sintetizador> y la visión se tratan aparte; math y remote, en parte.
						if sub.startswith("math/") or sub.startswith("remote/controlServer"):
							self._noteMath(sub, value)
						continue
					if prefix == "braille":
						continue
					walk(value, sub)
					continue
				if (prefix, key) in self.consumed or (prefix, key) in _SPECIAL_KEYS or (prefix, key) in _QUIET_KEYS:
					continue
				cat = _categoryForSection(prefix)
				self.note(cat, _("{key} = {value}: sin equivalente en Tiresias").format(key=f"{prefix.replace('/', '.')}.{key}" if prefix else key, value=_text(value)))

		walk(self.data, "")
		if synthInternals:
			self.note(CAT_SPEECH, _("datos internos de los controladores de voz de NVDA ({sections}): no hacen falta en Tiresias").format(sections=", ".join(synthInternals)))
		if addonSections:
			self.note(
				CAT_OTHER,
				_("configuración de complementos de NVDA sin equivalente en Tiresias (no se importa): {sections}").format(sections=", ".join(addonSections)),
			)

	def _noteMath(self, sub: str, value: dict) -> None:
		if sub.startswith("remote/controlServer"):
			if _text(value.get("host", "")).strip():
				self.note(CAT_OTHER, _("servidor de acceso remoto de NVDA: configúralo en las opciones de acceso remoto de Tiresias"))
			return
		if sub.count("/") == 1:
			for key, raw in value.items():
				if isinstance(raw, dict) or (sub, key) in self.consumed:
					continue
				self.note(CAT_OTHER, _("{key} = {value}: sin equivalente en Tiresias").format(key=f"{sub.replace('/', '.')}.{key}", value=_text(raw)))


def _categoryForSection(prefix: str) -> str:
	top = prefix.split("/", 1)[0]
	if top == "speech":
		return CAT_SPEECH
	if top == "keyboard":
		return CAT_KEYBOARD
	if top in ("braille", "brailleViewer"):
		return CAT_BRAILLE
	return CAT_OTHER


def _deviceName(value: str) -> str | None:
	"""Nombre del dispositivo de audio (Tiresias guarda el nombre; NVDA, el identificador)."""
	try:
		from .audio import core_audio

		devices = core_audio.getDevices(core_audio.eRender)
	except Exception:
		log.debug("No se pudieron enumerar los dispositivos de audio", exc_info=True)
		return None
	for d in devices:
		if d.id.lower() == value.lower() or d.name.lower() == value.lower():
			return d.name
	return None


# ====================================================================== gestos
#: Órdenes de NVDA con otro nombre en Tiresias.
SCRIPT_ALIASES = {
	"say_battery_status": "sayBatteryStatus",
	"reportOrShowFormattingAtCaret": "reportFormatting",
	"recognizeWithUwpOcr": "recognizeWithOcr",
	"toggleAutomaticRefreshOfRecogResult": "toggleOcrAutoRefresh",
	"navigatorObject_devInfo": "navigatorObjectDevInfo",
	"readStatusLine": "reportStatusLine",
	"toggleVirtualBufferPassThrough": "toggleFocusMode",
	"toggleBrailleMode": "braille_toggleMode",
	"toggleBrailleAutoScroll": "braille_toggleAutoScroll",
	"increaseBrailleAutoScrollRate": "braille_increaseAutoScrollRate",
	"decreaseBrailleAutoScrollRate": "braille_decreaseAutoScrollRate",
	"braille_toggleNVDAKey": "braille_toggleTiresiasKey",
	"braille_toggleFocusContextPresentation": "braille_cycleFocusContextPresentation",
	"braille_cycleShowSelection": "braille_toggleShowSelection",
	"braille_cycleUnicodeNormalization": "braille_toggleUnicodeNormalization",
	"toggleTouchSupport": "touch_toggleSupport",
	"zoomIn": "magnifierZoomIn",
	"zoomOut": "magnifierZoomOut",
	"panLeft": "magnifierPanLeft",
	"panRight": "magnifierPanRight",
	"panUp": "magnifierPanUp",
	"panDown": "magnifierPanDown",
	"panToLeftEdge": "magnifierLeftEdge",
	"panToRightEdge": "magnifierRightEdge",
	"panToTopEdge": "magnifierTopEdge",
	"panToBottomEdge": "magnifierBottomEdge",
	"cycleFilters": "magnifierCycleFilter",
	"cycleTrackingModes": "magnifierCycleTrackingMode",
	"toggleFollowMouse": "magnifierToggleFollowMouse",
	"toggleFollowNavigatorObject": "magnifierToggleFollowNavigator",
	"toggleFollowReview": "magnifierToggleFollowReview",
	"toggleFollowSystemFocus": "magnifierToggleFollowFocus",
	"toggleAllFollow": "magnifierToggleAllFollow",
	"moveMouseToView": "magnifierMoveMouseToView",
	"showEntireScreenOverview": "magnifierOverview",
	"connectToRemote": "remoteConnect",
	"disconnectFromRemote": "remoteDisconnect",
	"sendSAS": "sendRemoteSAS",
	"toggleMonitoringKeyboard": "toggleRemoteControl",
}
#: Tipos de la navegación rápida de NVDA que se llaman distinto.
_QUICKNAV_TYPES = {"TextParagraph": "Paragraph"}

#: Clase de Tiresias que corresponde a cada sección de gestures.ini (por prefijo).
_SECTION_CLASSES = (
	("globalCommands.", "global"),
	("browseMode.", "browse"),
	("virtualBuffers.", "browse"),
	("cursorManager.", "browse"),
	("treeInterceptorHandler.", "browse"),
	("documentBase.", "browse"),
	("NVDAObjects.behaviors.EditableText", "edit"),
	("editableText.", "edit"),
	("_remoteClient.", "remote"),
	("remoteClient.", "remote"),
	("mathPres.", "math"),
)


def _gestureTargets() -> dict[str, tuple[str, type]]:
	"""{tipo: (clave de clase, clase)} de las clases de Tiresias con órdenes."""
	out: dict[str, tuple[str, type]] = {}

	def add(kind: str, getter: Callable[[], type]) -> None:
		try:
			cls = getter()
			out[kind] = (f"{cls.__module__}.{cls.__qualname__}", cls)
		except Exception:
			log.debug("No se pudo cargar la clase de órdenes %s", kind, exc_info=True)

	def _global():
		from .global_commands import GlobalCommands

		return GlobalCommands

	def _browse():
		from .browse.document import BrowseModeDocument

		return BrowseModeDocument

	def _edit():
		from .objects.behaviors import EditableText

		return EditableText

	def _remote():
		from .remote.plugin import RemoteGlobalPlugin

		return RemoteGlobalPlugin

	def _math():
		from .mathpres.interaction import MathInteractor

		return MathInteractor

	for kind, getter in (("global", _global), ("browse", _browse), ("edit", _edit), ("remote", _remote), ("math", _math)):
		add(kind, getter)
	return out


def tiresiasScriptName(nvdaName: str, exists: Callable[[str], bool] | None = None) -> str:
	"""Orden de Tiresias equivalente a una de NVDA.

	``exists(nombre)`` dice si Tiresias tiene una orden con ese nombre: si la
	hay con el mismo nombre que en NVDA (``nextSynthSetting``...), se usa esa
	antes de convertir los nombres de la navegación rápida.
	"""
	if nvdaName in SCRIPT_ALIASES:
		return SCRIPT_ALIASES[nvdaName]
	if exists is not None and exists(nvdaName):
		return nvdaName
	m = re.match(r"^(next|previous)([A-Z]\w*)$", nvdaName)
	if m:
		kind = _QUICKNAV_TYPES.get(m.group(2), m.group(2))
		if kind == "NotLinkBlock":
			return "quickNavNotLinkBlock" if m.group(1) == "next" else "quickNavNotLinkBlockPrev"
		return ("quickNavNext" if m.group(1) == "next" else "quickNavPrev") + kind
	return nvdaName


def _hasScript(cls: type, name: str) -> bool:
	return callable(getattr(cls, "script_" + name, None))


def _sameGesture(a: str, b: str) -> bool:
	pa, _s, ka = a.partition(":")
	pb, _s2, kb = b.partition(":")
	if ka != kb:
		return False
	fa, fb = pa.split("(", 1)[0], pb.split("(", 1)[0]
	if fa != fb:
		return False
	la = pa[pa.index("(") + 1 : -1] if "(" in pa else None
	lb = pb[pb.index("(") + 1 : -1] if "(" in pb else None
	return la is None or lb is None or la == lb


def _reservedKeys() -> dict[str, str]:
	try:
		from .gui.gesture_tools import RESERVED

		return dict(RESERVED)
	except Exception:
		return {}


#: Teclas de líneas braille que Tiresias nombra distinto que NVDA, por
#: controlador de Tiresias (nombres en minúsculas, como quedan normalizados).
_BRAILLE_KEY_ALIASES: dict[str, dict[str, str]] = {
	# NVDA llama «secondRouting» a la fila superior; Tiresias, «routing2».
	"albatross": {"secondrouting": "routing2", "multisecondrouting": "multirouting2"},
	# NVDA llama «route» al enrutamiento de la Lilli; Tiresias, «routing».
	"lilli": {"route": "routing"},
}


def _brailleKeys(tDriver: str, keys: str) -> str:
	"""Teclas de un gesto braille de NVDA con los nombres de Tiresias."""
	aliases = _BRAILLE_KEY_ALIASES.get(tDriver)
	if not aliases:
		return keys
	return "+".join(aliases.get(k.lower(), k) for k in keys.split("+"))


def translateGesture(gid: str) -> tuple[str | None, str | None]:
	"""Identificador de NVDA -> (identificador de Tiresias, motivo si no se puede)."""
	from .baseobject import normalizeGestureId

	gid = gid.strip()
	if ":" not in gid:
		return None, _("gesto no válido")
	prefix = gid.split(":", 1)[0].lower()
	family = prefix.split("(", 1)[0]
	if family == "kb":
		norm = normalizeGestureId(gid)
		keysPart = norm.split(":", 1)[1]
		main = [p for p in keysPart.split("+") if p not in ("tiresias", "control", "shift", "alt", "windows")]
		if len(main) != 1:
			return None, _("combinación de teclas no válida")
		try:
			from .input import keys

			if len(main[0]) > 1 and keys.vkFromName(main[0]) is None:
				return None, _("tecla desconocida «{key}»").format(key=main[0])
		except Exception:
			pass
		return norm, None
	if family == "br":
		driver = prefix[3:-1] if prefix.startswith("br(") and prefix.endswith(")") else ""
		# «br(freedomScientific.focus40):...»: el modelo no forma parte del controlador.
		driver = driver.split(".", 1)[0]
		tDriver = tiresiasBrailleDriver(driver)
		if not tDriver or tDriver in ("auto", "noBraille", "viewer"):
			return None, _("la línea braille «{driver}» no tiene controlador en Tiresias").format(driver=driver)
		return normalizeGestureId(f"br({tDriver}):" + _brailleKeys(tDriver, gid.split(":", 1)[1])), None
	if family in ("ts", "bk"):
		return normalizeGestureId(gid), None
	return None, _("tipo de gesto sin equivalente en Tiresias")


def _mapGestures(nvda: NvdaConfig, plan: Plan) -> None:
	if not nvda.gestures:
		return
	targets = _gestureTargets()
	try:
		from .input import gestures as gesturesModule

		userMap = gesturesModule.UserGestureMap()
		userMap.load()
		state = userMap.userBindings()
	except Exception:
		state = {}
	reserved = _reservedKeys()
	menu = targets.get("global")
	menuGestures: list[str] = []
	if menu:
		classKey, cls = menu
		defaults = dict(cls.iterClassGestures()) if hasattr(cls, "iterClassGestures") else {}
		user = state.get(classKey, {})
		for g in list(defaults) + list(user):
			target = user.get(g, defaults.get(g))
			if target == "showGui" and g not in menuGestures:
				menuGestures.append(g)
	menuLabel = ", ".join(_gestureLabel(g) for g in menuGestures) or _("ninguna")
	for section, scripts in nvda.gestures.items():
		if not isinstance(scripts, dict):
			continue
		kind = next((k for prefix, k in _SECTION_CLASSES if section.startswith(prefix)), None)
		count = sum(len(toList(v)) for v in scripts.values() if not isinstance(v, dict))
		if kind is None or kind not in targets:
			what = section.split(".")
			if section.startswith("globalPlugins.") and len(what) > 1:
				plan.note(CAT_GESTURES, _("complemento de NVDA «{name}»: {count} gestos sin equivalente en Tiresias").format(name=what[1], count=count))
			elif section.startswith("appModules.") and len(what) > 1:
				plan.note(CAT_GESTURES, _("módulo de aplicación «{name}» de NVDA: {count} gestos sin equivalente en Tiresias").format(name=what[1], count=count))
			else:
				plan.note(CAT_GESTURES, _("sección «{section}»: {count} gestos sin equivalente en Tiresias").format(section=section, count=count))
			continue
		classKey, cls = targets[kind]
		classDefaults = dict(cls.iterClassGestures()) if hasattr(cls, "iterClassGestures") else {}
		userBindings = state.get(classKey, {})
		for nvdaScript, value in scripts.items():
			if isinstance(value, dict):
				continue
			ids = toList(value)
			if nvdaScript == "None":
				plan.note(
					CAT_GESTURES,
					_("{section}: NVDA quita {gestures}; no se quita nada en Tiresias porque sus teclas por defecto son otras").format(section=section, gestures=", ".join(ids)),
				)
				continue
			tScript = tiresiasScriptName(nvdaScript, lambda n: any(_hasScript(c, n) for _k, c in targets.values()))
			targetKey, targetCls = classKey, cls
			if not _hasScript(cls, tScript):
				other = next(((k, c) for k, c in targets.values() if _hasScript(c, tScript)), None)
				if other is None:
					plan.note(CAT_GESTURES, _("orden «{script}» de NVDA ({gestures}): no existe en Tiresias").format(script=nvdaScript, gestures=", ".join(ids)))
					continue
				targetKey, targetCls = other
			for gid in ids:
				tGid, reason = translateGesture(gid)
				if tGid is None:
					plan.note(CAT_GESTURES, f"{nvdaScript} = {gid}: {reason}")
					continue
				label = _gestureLabel(tGid)
				if tScript == "showGui":
					plan.note(
						CAT_GESTURES,
						_("{gesture} (menú de NVDA): no se importa; el menú de Tiresias se abre con {menu}").format(gesture=gid, menu=menuLabel),
					)
					continue
				if any(_sameGesture(tGid, m) for m in menuGestures):
					plan.note(CAT_GESTURES, _("{gesture} para «{script}»: es la tecla del menú de Tiresias; no se cambia").format(gesture=label, script=tScript))
					continue
				keysOnly = tGid.split(":", 1)[1]
				if tGid.startswith("kb") and keysOnly in reserved:
					plan.note(CAT_GESTURES, _("{gesture} para «{script}»: tecla reservada ({reason}); no se importa").format(gesture=label, script=tScript, reason=reserved[keysOnly]))
					continue
				tDefaults = classDefaults if targetCls is cls else dict(targetCls.iterClassGestures())
				tUser = userBindings if targetCls is cls else state.get(targetKey, {})
				current = tUser.get(tGid, tDefaults.get(tGid))
				if current == tScript:
					continue
				replaces = current if current else None
				if replaces:
					plan.note(CAT_GESTURES, _("{gesture}: ahora hace «{script}» en lugar de «{old}»").format(gesture=label, script=tScript, old=replaces))
				plan.gestures.append(GestureChange(targetKey, tGid, tScript, f"[{section}] {nvdaScript} = {gid}", replaces))


def _gestureLabel(gid: str) -> str:
	try:
		from .input.keys import labelForGesture

		return labelForGesture(gid)
	except Exception:
		return gid


# ====================================================================== diccionarios y símbolos del plan
def _voiceIdFor(dictFile: DictFile, tSynth: str, ini: dict) -> str | None:
	"""Voz de Tiresias de un diccionario de voz de NVDA (``None`` si no se sabe)."""
	if tSynth == "ibmtts":
		return eciVoiceFromDisplayName(dictFile.voiceName)
	speech = ini.get("speech", {}) if isinstance(ini.get("speech"), dict) else {}
	sec = speech.get(dictFile.synth, {})
	configured = _text(sec.get("voice", "")) if isinstance(sec, dict) else ""
	if not configured:
		return None
	if tSynth == "espeak":
		configured = _espeakVoice(configured)
	elif tSynth == "sapi4":
		configured = configured.upper()
	# El nombre visible de la voz tiene que coincidir con alguna palabra del identificador.
	words = [w for w in re.split(r"[^A-Za-zÀ-ÿ]+", dictFile.voiceName) if len(w) > 2 and w.lower() not in ("microsoft", "desktop", "voice", "speech", "server", "text", "spanish", "english")]
	low = configured.lower()
	if any(w.lower() in low for w in words) or dictFile.voiceName.lower() == configured.lower():
		return configured
	return None


def _mapDicts(nvda: NvdaConfig, plan: Plan) -> None:
	from .speech import dictionaries

	base = paths.speechDictsDir()
	for d in nvda.dicts:
		entries, problems = parseSpeechDict(d.path)
		for p in problems:
			plan.note(CAT_DICTS, f"{os.path.basename(d.path)}: {p}")
		if d.kind == "temp":
			plan.note(CAT_DICTS, _("el diccionario temporal de NVDA ({count} entradas) no se importa: en los dos lectores dura solo hasta que se cierra").format(count=len(entries)))
			continue
		if not entries:
			continue
		if d.kind == "default":
			plan.dicts.append(DictImport("default", "default.json", entries, d.path, _("Diccionario por defecto")))
			continue
		tSynth = tiresiasSynthName(d.synth)
		if tSynth in (None, "auto", "silence"):
			plan.note(CAT_DICTS, _("diccionario de la voz «{voice}» de «{synth}»: ese sintetizador no existe en Tiresias").format(voice=d.voiceName, synth=d.synth))
			continue
		voice = _voiceIdFor(d, tSynth, nvda.ini)
		if not voice:
			plan.note(CAT_DICTS, _("diccionario de la voz «{voice}» de «{synth}»: no se sabe a qué voz de Tiresias corresponde; no se importa").format(voice=d.voiceName, synth=d.synth))
			continue
		target = os.path.relpath(dictionaries.voiceDictFile(tSynth, voice), base)
		plan.dicts.append(
			DictImport("voice", target, entries, d.path, _("Diccionario de la voz {voice} ({synth})").format(voice=d.voiceName, synth=synthDisplayName(tSynth)))
		)


def _tiresiasSymbolDefaults(lang: str) -> dict[str, dict]:
	try:
		with open(os.path.join(paths.symbolsDir(), f"{lang}.json"), encoding="utf-8") as f:
			return {s["symbol"]: s for s in json.load(f).get("symbols", []) if isinstance(s, dict) and "symbol" in s}
	except (OSError, ValueError, KeyError):
		return {}


def _mapSymbols(nvda: NvdaConfig, plan: Plan) -> None:
	for locale, path in nvda.symbolFiles:
		lang = locale.split("_")[0].lower()
		symbols, problems, complexIds = parseSymbolsFile(path)
		for p in problems:
			plan.note(CAT_SYMBOLS, f"{os.path.basename(path)}: {p}")
		if not symbols:
			continue
		if not os.path.isfile(os.path.join(paths.symbolsDir(), f"{lang}.json")):
			plan.note(CAT_SYMBOLS, _("{file}: Tiresias no tiene tabla de símbolos en ese idioma ({lang})").format(file=os.path.basename(path), lang=lang))
			continue
		defaults = _tiresiasSymbolDefaults(lang)
		out: list[dict] = []
		for s in symbols:
			ident = s["symbol"]
			if _isComplexIdentifier(ident, complexIds):
				plan.note(CAT_SYMBOLS, _("símbolo complejo «{symbol}»: Tiresias no tiene símbolos definidos por expresiones regulares").format(symbol=ident))
				continue
			base = defaults.get(ident, {})
			name = s["name"] if s["name"] is not None else base.get("name")
			if name is None:
				plan.note(CAT_SYMBOLS, _("símbolo «{symbol}»: no tiene nombre ni hay uno de fábrica en Tiresias").format(symbol=ident))
				continue
			level = s["level"] if s["level"] is not None else int(base.get("level", 300))
			preserve = s["preserve"] if s["preserve"] is not None else base.get("preserve", "never")
			out.append({"symbol": ident, "name": name, "level": level, "preserve": preserve})
		if out:
			target = "symbols_user.json" if lang == "es" else f"symbols_user_{lang}.json"
			plan.symbols.append(SymbolImport(lang, target, out, path))


# ====================================================================== construir el plan
def _ensureDefaults() -> None:
	"""Registra los valores por defecto de los módulos (para validar y comparar)."""
	import importlib

	# La mayoría registra sus valores al importarse; estos dos, con una función.
	explicit = {"tiresias.speech.defaults": "register", "tiresias.remote": "registerDefaults"}
	for mod in (
		"tiresias.speech.defaults",
		"tiresias.synth",
		"tiresias.audio",
		"tiresias.braille.presenter",
		"tiresias.vision",
		"tiresias.magnifier",
		"tiresias.a11y",
		"tiresias.mathpres",
		"tiresias.ocr",
		"tiresias.remote",
	):
		try:
			m = importlib.import_module(mod)
			if mod in explicit:
				getattr(m, explicit[mod])()
		except Exception:
			log.debug("No se pudieron registrar los valores por defecto de %s", mod, exc_info=True)


def buildPlan(folder: str, useNvdaDefaults: bool = True, configManager: Any = None) -> Plan:
	"""Lee la configuración de NVDA de ``folder`` y calcula lo que se importaría."""
	from .config import conf as globalConf, validation

	cm = configManager or globalConf
	_ensureDefaults()
	nvda = NvdaConfig(folder)
	plan = Plan(folder, nvda.isPortable, summary=nvda.summaryLines(), useNvdaDefaults=useNvdaDefaults)
	if not nvda.ini:
		plan.note("", _("No se ha podido leer nvda.ini"))
	mapper = _Mapper(nvda.ini, plan, isProfile=False, useDefaults=useNvdaDefaults)
	changes = mapper.run()
	plan.changes = _validated(changes, cm, plan, validation)
	for c in plan.changes:
		c.old = _effective(cm, c.path, includeProfiles=False)
	# Perfiles.
	baseSynth = _text(_section(nvda.ini, "speech").get("synth", ""))
	baseMathLang = _section(nvda.ini, "math/speech").get("language", "")
	baseMathLang = "" if isinstance(baseMathLang, dict) else _text(baseMathLang)
	for nvdaName, data in nvda.profiles.items():
		pm = _Mapper(data, plan, isProfile=True, useDefaults=False, label=_("perfil «{name}»").format(name=nvdaName), baseSynth=baseSynth, baseMathLang=baseMathLang)
		pChanges = _validated(pm.run(), cm, plan, validation)
		triggers = [t for t, p in nvda.triggers.items() if p == nvdaName]
		# En Windows «Lectura» y «lectura» son el mismo archivo: es el mismo perfil.
		existing = findProfileName(cm, nvdaName)
		name = existing or nvdaName
		plan.profiles.append(ProfileImport(name, pChanges, triggers, exists=existing is not None))
		if existing is not None and cm.isProfileReadOnly(existing):
			plan.note(CAT_PROFILES, _("el perfil «{name}» de Tiresias es de solo lectura: no se modifica").format(name=existing))
		elif existing is not None:
			plan.note(CAT_PROFILES, _("el perfil «{name}» ya existe en Tiresias: se le añaden los ajustes de NVDA").format(name=existing))
	for trig, name in nvda.triggers.items():
		if name not in nvda.profiles:
			plan.note(CAT_PROFILES, _("el disparador «{trigger}» apunta al perfil «{name}», que no existe").format(trigger=trig, name=name))
		elif not (trig.startswith("app:") or trig == "sayAll"):
			plan.note(CAT_PROFILES, _("disparador «{trigger}»: Tiresias no tiene ese tipo de disparador").format(trigger=trig))
	_mapGestures(nvda, plan)
	_mapDicts(nvda, plan)
	_mapSymbols(nvda, plan)
	# Diccionarios activados en NVDA.
	enabledDicts = _section(nvda.ini, "speech").get("speechDictionaries")
	if enabledDicts is not None:
		active = {x.lower() for x in toList(enabledDicts)}
		for kind, label in (("default", _("por defecto")), ("voice", _("de voz"))):
			if kind not in active:
				plan.note(CAT_DICTS, _("en NVDA el diccionario {kind} está desactivado; en Tiresias siempre se aplica").format(kind=label))
	if nvda.labelNotes:
		plan.note(
			"",
			_("etiquetas de complementos de NVDA ({items}): no tienen equivalente directo, porque Tiresias identifica los controles de otra forma; ponlas desde Preferencias > Etiquetas personalizadas").format(
				items="; ".join(nvda.labelNotes)
			),
		)
	if nvda.addons:
		eloq = [n for n, _d in nvda.addons if n.lower() in ("ibmtts", "eloquence", "eloquence64pro", "voiceibmtts64", "ibmttsprofesional64", "openevv", "openevv64")]
		others = [n for n, dis in nvda.addons if n not in eloq and not dis]
		if eloq:
			plan.note(CAT_SPEECH, _("complementos de Eloquence de NVDA ({names}): Tiresias trae su propio complemento Eloquence").format(names=", ".join(eloq)))
		if others:
			plan.note("", _("complementos de NVDA activados que no se importan (son de NVDA): {names}").format(names=", ".join(others)))
	return plan


def findProfileName(cm: Any, name: str) -> str | None:
	"""Nombre del perfil de Tiresias que se llama ``name`` sin distinguir mayúsculas.

	Los perfiles son archivos y en Windows «Lectura.json» y «lectura.json» son
	el mismo: crear el segundo sobrescribiría el primero.
	"""
	if name in cm.profiles:
		return name
	low = name.casefold()
	return next((n for n in cm.profiles if n.casefold() == low), None)


def _validated(changes: list[Change], cm: Any, plan: Plan, validation: Any) -> list[Change]:
	"""Quita (con aviso) los valores que la validación de Tiresias no acepta."""
	out: list[Change] = []
	for c in changes:
		if len(c.path) == 2:
			section, key = c.path
			default = cm.defaults.get(section, {}).get(key, _MISSING) if isinstance(cm.defaults.get(section), dict) else _MISSING
			if default is not _MISSING:
				fixed = validation.coerce(c.value, default, c.path)
				if fixed is validation._MISSING:
					plan.note(c.category, _("{key}: el valor {value!r} no es válido en Tiresias").format(key=".".join(c.path), value=c.value))
					continue
				c.value = fixed
		out.append(c)
	return out


def _effective(cm: Any, path: tuple[str, ...], includeProfiles: bool = False) -> Any:
	"""Valor actual en Tiresias (configuración base o, si no está, el de fábrica)."""
	layers = [cm.base, cm.defaults] if not includeProfiles else list(reversed(cm._layers()))
	for layer in layers:
		v = _getPath(layer, path)
		if v is not _MISSING:
			return v
	return _MISSING


# ====================================================================== descripciones
_settingLabels: dict[tuple[str, str], Any] | None = None

def _synthSettingLabel(key: str) -> str:
	return {
		"voice": _("Voz"),
		"variant": _("Variante"),
		"rate": _("Velocidad"),
		"rateBoost": _("Aumento de velocidad"),
		"pitch": _("Tono"),
		"inflection": _("Entonación"),
		"volume": _("Volumen"),
		"headSize": _("Tamaño de cabeza"),
		"roughness": _("Aspereza"),
		"breathiness": _("Respiración"),
		"sampleRate": _("Frecuencia de muestreo"),
		"pauseMode": _("Pausas"),
		"phrasePrediction": _("Predicción de frases"),
		"abbreviationDictionary": _("Expandir abreviaturas"),
		"backquoteVoiceTags": _("Etiquetas de voz con acento grave"),
		"punctuationPause": _("Pausa natural tras la puntuación"),
	}.get(key, key)


def _labels() -> dict[tuple[str, str], Any]:
	global _settingLabels
	if _settingLabels is None:
		_settingLabels = {}
		try:
			from .gui.system_dialogs import collectSettings

			for entry in collectSettings():
				_settingLabels.setdefault((entry.section, entry.field.key), entry)
		except Exception:
			log.debug("No se pudieron leer los nombres de las opciones", exc_info=True)
	return _settingLabels


def _fallbackLabel(path: tuple[str, ...]) -> str | None:
	"""Nombres de las opciones que no están en un panel declarativo de Opciones."""
	return {
		("speech", "synth"): _("Voz › Sintetizador"),
		("speech", "trustVoiceLanguage"): _("Voz › Confiar en el idioma de la voz para los símbolos"),
		("speech", "autoLanguageSwitching"): _("Voz › Cambio automático de idioma"),
		("speech", "autoDialectSwitching"): _("Voz › Cambio automático de dialecto"),
		("speech", "reportLanguage"): _("Voz › Anunciar los cambios de idioma"),
		("speech", "reportNotSupportedLanguage"): _("Voz › Idioma que la voz no admite"),
		("speech", "beepSpeechModePitch"): _("Voz › Tono del modo de voz «pitidos» (Hz)"),
		("speech", "excludedSpeechModes"): _("Voz › Modos de voz que se saltan"),
		("speech", "cancelExpiredFocusSpeech"): _("Voz › Cancelar la voz de un foco que ya no está"),
		("speech", "sayAllUnit"): _("Voz › Unidad de la lectura continua"),
		("audio", "includedSoundSplitModes"): _("Audio › Modos de la orden de división del sonido"),
		("brailleDisplays", "excludedFromAuto"): _("Braille › Líneas excluidas de la detección automática"),
		("brailleViewer", "x"): _("Visor braille › Posición horizontal"),
		("brailleViewer", "y"): _("Visor braille › Posición vertical"),
		("speechViewer", "position"): _("Visor de voz › Posición y tamaño"),
		("math", "verbosity"): _("Matemáticas › Detalle"),
		("math", "style"): _("Matemáticas › Estilo de lectura"),
		("math", "copyFormat"): _("Matemáticas › Formato al copiar"),
		("remote", "confirmDisconnectAsFollower"): _("Acceso remoto › Confirmar la desconexión del equipo controlado"),
		("remote", "muteOnLocalControl"): _("Acceso remoto › Silenciar el equipo remoto al controlar el local"),
		("terminal", "speakPasswords"): _("Consolas › Leer las contraseñas escritas"),
		("terminal", "diffAlgorithm"): _("Consolas › Lectura del texto nuevo"),
		("touch", "enabled"): _("Interacción táctil › Activada"),
		("touch", "touchTyping"): _("Interacción táctil › Escritura táctil"),
		("touch", "edgeGestures"): _("Interacción táctil › Gestos de borde"),
	}.get(path)


def _cleanLabel(text: str) -> str:
	return text.replace("&", "").rstrip(":").strip()


def describeValue(value: Any) -> str:
	if value is _MISSING:
		return _("(sin valor)")
	if isinstance(value, bool):
		return _("activado") if value else _("desactivado")
	if isinstance(value, list):
		return ", ".join(str(v) for v in value) or _("(vacío)")
	if value == "":
		return _("(vacío)")
	return str(value)


def describeChange(c: Change) -> str:
	"""Texto legible de un cambio: «Voz › Velocidad: 55 (antes: 40)»."""
	path = c.path
	if len(path) == 4 and path[:2] == ("speech", "synths"):
		synthName = synthDisplayName(path[2])
		label = _synthSettingLabel(path[3])
		name = f"{synthName} › {label}"
		value = describeValue(c.value)
		old = describeValue(c.old)
	elif len(path) == 2:
		entry = _labels().get(path)
		if entry is not None:
			name = f"{entry.panelTitle} › {_cleanLabel(entry.field.label)}"
			try:
				value = entry.valueText(c.value)
				old = entry.valueText(c.old) if c.old is not _MISSING else describeValue(c.old)
			except Exception:
				value, old = describeValue(c.value), describeValue(c.old)
		else:
			name = _fallbackLabel(path) or ".".join(path)
			value, old = describeValue(c.value), describeValue(c.old)
		if path == ("speech", "synth"):
			value = synthDisplayName(c.value)
			old = synthDisplayName(c.old) if isinstance(c.old, str) else old
	else:
		name = ".".join(path)
		value, old = describeValue(c.value), describeValue(c.old)
	text = f"{name}: {value}"
	if c.old is not _MISSING and c.changes:
		text += " " + _("(antes: {old})").format(old=old)
	if c.fromDefault:
		text += " " + _("[valor por defecto de NVDA]")
	return text


def previewLines(plan: Plan, categories: set[str]) -> list[str]:
	lines: list[str] = []
	for cat in SETTING_CATEGORIES:
		if cat not in categories:
			continue
		items = [c for c in plan.changes if c.category == cat and c.changes]
		if not items:
			continue
		lines.append(f"[{_shortCategory(cat)}] " + _("{count} cambios").format(count=len(items)))
		lines.extend("  " + describeChange(c) for c in items)
	if CAT_PROFILES in categories and plan.profiles:
		lines.append(f"[{_shortCategory(CAT_PROFILES)}]")
		for p in plan.profiles:
			trig = ", ".join(p.triggers) or _("sin disparador")
			lines.append("  " + _("Perfil «{name}» ({triggers}): {count} ajustes").format(name=p.name, triggers=trig, count=len(p.changes)))
			lines.extend("    " + describeChange(c) for c in p.changes)
	if CAT_GESTURES in categories and plan.gestures:
		lines.append(f"[{_shortCategory(CAT_GESTURES)}] " + _("{count} gestos").format(count=len(plan.gestures)))
		for g in plan.gestures:
			lines.append("  " + _("{gesture}: {script}").format(gesture=_gestureLabel(g.gesture), script=g.script))
	if CAT_DICTS in categories and plan.dicts:
		lines.append(f"[{_shortCategory(CAT_DICTS)}]")
		for d in plan.dicts:
			lines.append("  " + _("{label}: {count} entradas").format(label=d.label, count=len(d.entries)))
	if CAT_SYMBOLS in categories and plan.symbols:
		lines.append(f"[{_shortCategory(CAT_SYMBOLS)}]")
		for s in plan.symbols:
			lines.append("  " + _("Idioma {lang}: {count} símbolos").format(lang=s.language, count=len(s.symbols)))
			for sym in s.symbols:
				lines.append(f"    {sym['symbol']!r} → {sym['name']}")
	unchanged = len([c for c in plan.changes if c.category in categories and not c.changes])
	if unchanged:
		lines.append(_("Opciones que ya coincidían con NVDA: {count}").format(count=unchanged))
	if not lines:
		lines.append(_("No hay nada que cambiar."))
	return lines


def noticeLines(plan: Plan, categories: set[str]) -> list[str]:
	order = {c: i for i, c in enumerate(CATEGORIES)}
	out = []
	for n in sorted(plan.notices, key=lambda n: order.get(n.category, len(order))):
		if n.category and n.category not in categories:
			continue
		out.append(f"[{_shortCategory(n.category)}] {n.text}")
	return out or [_("Ninguno.")]


# ====================================================================== copia de seguridad y deshacer
def backupRoot() -> str:
	return os.path.join(paths.configDir(), BACKUP_DIR)


def _copyTree(src: str, dst: str, skip: set[str]) -> list[str]:
	"""Copia ``src`` en ``dst`` (sin las carpetas de ``skip``). Devuelve las rutas relativas."""
	copied: list[str] = []
	if not os.path.isdir(src):
		return copied
	for root, dirs, files in os.walk(src):
		rel = os.path.relpath(root, src)
		dirs[:] = [d for d in dirs if os.path.normcase(os.path.join(root, d)) not in skip]
		for fn in files:
			if fn.endswith(".tmp"):
				continue
			relFile = os.path.normpath(os.path.join(rel, fn))
			target = os.path.join(dst, relFile)
			os.makedirs(os.path.dirname(target), exist_ok=True)
			shutil.copy2(os.path.join(root, fn), target)
			copied.append(relFile)
	return copied


def makeBackup(sourceFolder: str = "") -> str:
	"""Copia la configuración de Tiresias (y los diccionarios) antes de importar."""
	stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
	# Siempre detrás de las copias del mismo segundo (aunque se hayan borrado
	# las más antiguas), para que la nueva sea la más reciente.
	counts = [c for s, c in map(_backupOrder, _backupNames()) if s == stamp]
	n = max(counts) + 1 if counts else 1
	folder = os.path.join(backupRoot(), stamp if n == 1 else f"{stamp}-{n}")
	while os.path.exists(folder):
		n += 1
		folder = os.path.join(backupRoot(), f"{stamp}-{n}")
	os.makedirs(folder)
	skip = {os.path.normcase(backupRoot())}
	configFiles = _copyTree(paths.configDir(), os.path.join(folder, "config"), skip)
	dictFiles = _copyTree(paths.speechDictsDir(), os.path.join(folder, "speechDicts"), set())
	manifest = {
		"fecha": datetime.datetime.now().isoformat(timespec="seconds"),
		"origen": sourceFolder,
		"config": configFiles,
		"speechDicts": dictFiles,
		"escritos": [],
		"deshecha": False,
	}
	_writeManifest(folder, manifest)
	_pruneBackups(keep=MAX_BACKUPS)
	return folder


def _backupNames() -> list[str]:
	"""Carpetas de las copias de seguridad, de la más reciente a la más antigua."""
	root = backupRoot()
	try:
		names = [n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))]
	except OSError:
		return []

	return sorted(names, key=_backupOrder, reverse=True)


def _backupOrder(name: str) -> tuple[str, int]:
	"""(fecha, número) de una copia: «20261007-120000» y, en el mismo segundo, «20261007-120000-2»."""
	stamp, _sep, n = name.partition("-")[2].partition("-")
	count = int(n) if n.isdigit() else 1
	return name.split("-", 1)[0] + "-" + stamp, count


def _pruneBackups(keep: int) -> None:
	"""Borra las copias más antiguas y deja solo las ``keep`` más recientes."""
	root = backupRoot()
	names = [n for n in _backupNames() if os.path.isfile(os.path.join(root, n, MANIFEST_FILE))]
	for name in names[keep:]:
		shutil.rmtree(os.path.join(root, name), ignore_errors=True)


def _writeManifest(folder: str, data: dict) -> None:
	with open(os.path.join(folder, MANIFEST_FILE), "w", encoding="utf-8") as f:
		json.dump(data, f, ensure_ascii=False, indent="\t")


def _readManifest(folder: str) -> dict | None:
	try:
		with open(os.path.join(folder, MANIFEST_FILE), encoding="utf-8") as f:
			data = json.load(f)
		return data if isinstance(data, dict) else None
	except (OSError, ValueError):
		return None


def lastBackup() -> str | None:
	"""Copia de la última importación que todavía se puede deshacer."""
	root = backupRoot()
	for name in _backupNames():
		folder = os.path.join(root, name)
		m = _readManifest(folder)
		if m is not None and not m.get("deshecha") and m.get("escritos"):
			return folder
	return None


def canUndo() -> bool:
	return lastBackup() is not None


def undoLastImport(configManager: Any = None) -> str:
	"""Deshace la última importación. Devuelve la carpeta de la copia usada."""
	from .config import conf as globalConf

	cm = configManager or globalConf
	if cm.readOnly:
		raise ImportError_(_("La configuración es de solo lectura (modo seguro)."))
	folder = lastBackup()
	if folder is None:
		raise ImportError_(_("No hay ninguna importación que deshacer."))
	m = _readManifest(folder) or {}
	roots = {"config": paths.configDir(), "speechDicts": paths.speechDictsDir()}
	for item in m.get("escritos", []):
		kind, _sep, rel = item.partition("/")
		if kind not in roots or not rel:
			continue
		current = os.path.join(roots[kind], rel)
		saved = os.path.join(folder, kind, rel)
		if os.path.isfile(saved):
			os.makedirs(os.path.dirname(current), exist_ok=True)
			shutil.copy2(saved, current)
		else:
			for fn in (current, current + ".bak"):
				try:
					os.remove(fn)
				except OSError:
					pass
	m["deshecha"] = True
	m["fechaDeshecha"] = datetime.datetime.now().isoformat(timespec="seconds")
	_writeManifest(folder, m)
	return folder


# ====================================================================== aplicar
@dataclass
class ApplyResult:
	backup: str
	settings: int = 0
	profiles: int = 0
	gestures: int = 0
	dictEntries: int = 0
	symbols: int = 0
	skipped: list[str] = field(default_factory=list)
	report: str = ""
	export: str = ""


def applyPlan(plan: Plan, categories: set[str] | None = None, targetProfile: str | None = None, configManager: Any = None) -> ApplyResult:
	"""Aplica el plan: copia de seguridad, opciones, perfiles, gestos, diccionarios y símbolos."""
	from .config import conf as globalConf, isValidProfileName

	cm = configManager or globalConf
	cats = set(CATEGORIES) if categories is None else set(categories)
	if cm.readOnly:
		raise ImportError_(_("La configuración es de solo lectura (modo seguro): no se puede importar."))
	if targetProfile is not None:
		targetProfile = targetProfile.strip()
		if not isValidProfileName(targetProfile):
			raise ImportError_(_("El nombre del perfil no es válido."))
		existing = findProfileName(cm, targetProfile)
		if existing is not None:
			raise ImportError_(_("Ya existe un perfil llamado «{name}».").format(name=existing))
	# Lo que haya en memoria se guarda antes de la copia, para que deshacer vuelva aquí.
	try:
		cm.save()
	except OSError:
		log.exception("No se pudo guardar la configuración antes de importar")
	backup = makeBackup(plan.folder)
	result = ApplyResult(backup)
	# Lo que se va a escribir se anota en el manifiesto antes de tocar nada: si
	# la importación falla a medias, se puede deshacer igualmente.
	written = _plannedWrites(plan, cats, targetProfile, cm)
	_updateManifest(backup, written, targetProfile, cats, complete=False)
	complete = False
	try:
		_applyChanges(plan, cats, targetProfile, cm, result, written)
		complete = True
	finally:
		_updateManifest(backup, written, targetProfile, cats, complete)
	# ---- informe y copia exportada
	result.export = os.path.join(paths.configDir(), EXPORT_FILE)
	with open(result.export, "w", encoding="utf-8") as f:
		json.dump(plan.toJson(cats), f, ensure_ascii=False, indent="\t", default=str)
	result.report = os.path.join(paths.configDir(), REPORT_FILE)
	with open(result.report, "w", encoding="utf-8") as f:
		f.write(buildReport(plan, cats, result, targetProfile))
	return result


def _plannedWrites(plan: Plan, cats: set[str], targetProfile: str | None, cm: Any) -> set[str]:
	"""Archivos (relativos a la copia de seguridad) que puede escribir la importación."""
	written: set[str] = {"config/config.json", "config/profileTriggers.json", "config/profileMeta.json"}
	if targetProfile is not None:
		written.add(f"config/profiles/{targetProfile}.json")
	if CAT_PROFILES in cats:
		for p in plan.profiles:
			name = findProfileName(cm, p.name) or p.name
			if not (name in cm.profiles and cm.isProfileReadOnly(name)):
				written.add(f"config/profiles/{name}.json")
	if CAT_GESTURES in cats and plan.gestures:
		written.add("config/gestures.json")
	if CAT_DICTS in cats:
		for d in plan.dicts:
			written.add("speechDicts/" + d.target.replace(os.sep, "/"))
	if CAT_SYMBOLS in cats:
		for s in plan.symbols:
			written.add("config/" + s.target)
	return written


def _updateManifest(backup: str, written: set[str], targetProfile: str | None, cats: set[str], complete: bool) -> None:
	m = _readManifest(backup) or {}
	m["escritos"] = sorted(written)
	m["destino"] = targetProfile or ""
	m["categorias"] = sorted(cats)
	m["completa"] = complete
	_writeManifest(backup, m)


class _UnreadableFile(Exception):
	"""Un archivo de Tiresias que habría que completar no se puede leer: no se toca."""


def _applyChanges(plan: Plan, cats: set[str], targetProfile: str | None, cm: Any, result: ApplyResult, written: set[str]) -> None:
	from .config import isValidProfileName

	# ---- opciones
	settingChanges = [c for c in plan.changes if c.category in cats and c.changes]
	with cm._lock:
		if targetProfile is not None:
			profile = cm.createProfile(targetProfile)
			layer = profile.data
			written.add(f"config/profiles/{targetProfile}.json")
		else:
			profile = None
			layer = cm.base
		for c in settingChanges:
			if cm.isLocked(c.path[0], c.path[1] if len(c.path) > 1 else None):
				result.skipped.append(_("{key}: bloqueada por la política del equipo").format(key=".".join(c.path)))
				continue
			_setPath(layer, c.path, c.value)
			result.settings += 1
		if profile is not None:
			profile.dirty = True
		else:
			cm.baseDirty = True
		# ---- perfiles de NVDA
		if CAT_PROFILES in cats:
			for p in plan.profiles:
				# Mismo perfil aunque cambien las mayúsculas (es el mismo archivo).
				name = findProfileName(cm, p.name) or p.name
				prof = cm.profiles.get(name)
				if prof is not None and cm.isProfileReadOnly(name):
					result.skipped.append(_("perfil «{name}»: es de solo lectura en Tiresias; no se modifica").format(name=name))
					continue
				if prof is None:
					if not isValidProfileName(name):
						result.skipped.append(_("perfil «{name}»: nombre no válido").format(name=name))
						continue
					prof = cm.createProfile(name)
				for c in p.changes:
					_setPath(prof.data, c.path, c.value)
				prof.dirty = True
				for trig in p.triggers:
					if trig.startswith("app:") or trig == "sayAll":
						cm.setTrigger(trig, name)
				written.add(f"config/profiles/{name}.json")
				result.profiles += 1
	cm.save()
	# ---- gestos
	if CAT_GESTURES in cats and plan.gestures:
		from .input import gestures as gesturesModule

		userMap = gesturesModule.userMap
		userMap.load()
		written.add("config/gestures.json")
		for g in plan.gestures:
			userMap.bind(g.classKey, g.gesture, g.script)
			result.gestures += 1
		userMap.save()
	# ---- diccionarios
	if CAT_DICTS in cats:
		base = paths.speechDictsDir()
		for d in plan.dicts:
			path = os.path.join(base, d.target)
			written.add("speechDicts/" + d.target.replace(os.sep, "/"))
			try:
				result.dictEntries += _mergeDict(path, d.entries)
			except _UnreadableFile as e:
				result.skipped.append(_("{label}: no se importa porque el diccionario actual de Tiresias ({file}) no se puede leer ({error}); no se ha tocado").format(label=d.label, file=path, error=e))
	# ---- símbolos
	if CAT_SYMBOLS in cats:
		for s in plan.symbols:
			path = os.path.join(paths.configDir(), s.target)
			written.add("config/" + s.target)
			try:
				result.symbols += _mergeSymbols(path, s.symbols)
			except _UnreadableFile as e:
				result.skipped.append(_("símbolos ({lang}): no se importan porque el archivo actual de Tiresias ({file}) no se puede leer ({error}); no se ha tocado").format(lang=s.language, file=path, error=e))


def _mergeDict(path: str, entries: list[dict]) -> int:
	from .speech import dictionaries

	existing: list = []
	if os.path.isfile(path):
		try:
			existing = dictionaries.readEntries(path)
		except (OSError, ValueError) as e:
			# Un diccionario estropeado no se sobrescribe en silencio: se pierden sus entradas.
			raise _UnreadableFile(str(e)) from e
	index = {(e.pattern, e.type, e.caseSensitive): i for i, e in enumerate(existing)}
	added = 0
	for item in entries:
		e = dictionaries.entryFromDict(item)
		key = (e.pattern, e.type, e.caseSensitive)
		if key in index:
			old = existing[index[key]]
			if old.replacement == e.replacement:
				continue
			existing[index[key]] = e
		else:
			index[key] = len(existing)
			existing.append(e)
		added += 1
	dictionaries.writeEntries(path, existing)
	return added


def _mergeSymbols(path: str, symbols: list[dict]) -> int:
	data: dict = {"symbols": [], "removed": []}
	if os.path.isfile(path):
		try:
			with open(path, encoding="utf-8") as f:
				loaded = json.load(f)
			if not isinstance(loaded, dict):
				raise ValueError(_("formato no válido"))
			data = {"symbols": list(loaded.get("symbols", [])), "removed": list(loaded.get("removed", []))}
		except (OSError, ValueError, TypeError) as e:
			# Los símbolos propios estropeados no se sobrescriben en silencio.
			raise _UnreadableFile(str(e)) from e
	bySymbol = {s.get("symbol"): i for i, s in enumerate(data["symbols"]) if isinstance(s, dict)}
	count = 0
	for s in symbols:
		item = {"symbol": s["symbol"], "name": s["name"], "level": int(s["level"]), "preserve": s["preserve"]}
		if s["symbol"] in bySymbol:
			data["symbols"][bySymbol[s["symbol"]]] = item
		else:
			bySymbol[s["symbol"]] = len(data["symbols"])
			data["symbols"].append(item)
		if s["symbol"] in data["removed"]:
			data["removed"].remove(s["symbol"])
		count += 1
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "w", encoding="utf-8") as f:
		json.dump(data, f, ensure_ascii=False, indent="\t")
	return count


# ====================================================================== informe
def buildReport(plan: Plan, categories: set[str], result: ApplyResult | None = None, targetProfile: str | None = None) -> str:
	now = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
	lines = [
		_("INFORME DE LA IMPORTACIÓN DE LA CONFIGURACIÓN DE NVDA"),
		"=" * 56,
		_("Fecha: {date}").format(date=now),
		_("Origen: {folder} ({kind})").format(folder=plan.folder, kind=_("NVDA portable") if plan.isPortable else _("NVDA instalado")),
		_("Destino: {target}").format(target=_("perfil «{name}»").format(name=targetProfile) if targetProfile else _("configuración normal de Tiresias ({folder})").format(folder=paths.configDir())),
		_("Valores por defecto de NVDA aplicados: {answer}").format(answer=_("sí") if plan.useNvdaDefaults else _("no")),
		_("Categorías: {cats}").format(cats=", ".join(_shortCategory(c) for c in CATEGORIES if c in categories)),
	]
	if result is not None:
		lines.append(_("Copia de seguridad: {folder}").format(folder=result.backup))
		lines.append(_("Para deshacerla: Herramientas > Importar configuración de NVDA > Deshacer la última importación, o «Tiresias.exe --undo-nvda-import»."))
	lines += ["", _("LO QUE SE HA ENCONTRADO"), "-" * 40]
	lines += ["  " + s for s in plan.summary]
	lines += ["", _("LO QUE SE HA IMPORTADO"), "-" * 40]
	lines += ["  " + s for s in previewLines(plan, categories)]
	if result is not None:
		lines += [
			"",
			_("Resumen: {settings} opciones, {profiles} perfiles, {gestures} gestos, {dicts} entradas de diccionario y {symbols} símbolos.").format(
				settings=result.settings, profiles=result.profiles, gestures=result.gestures, dicts=result.dictEntries, symbols=result.symbols
			),
		]
		for s in result.skipped:
			lines.append("  " + s)
	same = [c for c in plan.changes if c.category in categories and not c.changes]
	if same:
		lines += ["", _("YA COINCIDÍAN (no ha hecho falta cambiarlas)"), "-" * 40]
		lines += ["  " + describeChange(c) for c in same]
	lines += ["", _("LO QUE NO SE HA IMPORTADO Y POR QUÉ"), "-" * 40]
	lines += ["  " + s for s in noticeLines(plan, categories)]
	skippedCats = [c for c in CATEGORIES if c not in categories]
	if skippedCats:
		lines.append("  " + _("Categorías no elegidas: {cats}").format(cats=", ".join(_shortCategory(c) for c in skippedCats)))
	lines.append("")
	return "\r\n".join(lines)


# ====================================================================== tras importar (en ejecución)
def reloadAfterImport(announce: str | None = None, then=None, activateProfile: str | None = None) -> None:
	"""Vuelve a leer lo importado y lo aplica (con Tiresias en marcha).

	Todo se hace en el hilo del núcleo, que es quien usa la configuración, los
	gestos, los diccionarios y los símbolos (antes se recargaban en el hilo de
	la interfaz mientras el núcleo hablaba). Después de aplicar la
	configuración (el sintetizador puede cambiar en caliente) se dice
	``announce`` con la voz nueva y se llama a ``then()`` (en el núcleo), pase
	lo que pase. ``activateProfile``: perfil nuevo de la importación, que se
	activa a mano para probarlo (se desactiva desde Perfiles de configuración).
	"""
	from . import queue_handler

	queue_handler.queueFunction(_reloadOnCore, announce, then, activateProfile)


def _synthSettingsSnapshot(cm: Any) -> list[tuple[dict, Any]]:
	"""Copia de ``speech.synths`` de la configuración normal y de cada perfil."""
	layers = [cm.base] + [p.data for p in cm.profiles.values()]
	out: list[tuple[dict, Any]] = []
	for layer in layers:
		value = _getPath(layer, ("speech", "synths"))
		# ``_MISSING`` no se copia: la copia sería otro objeto y dejaría de reconocerse.
		out.append((layer, value if value is _MISSING else copy.deepcopy(value)))
	return out


def _restoreSynthSettings(snapshot: list[tuple[dict, Any]]) -> None:
	"""Deja ``speech.synths`` como en la copia (lo leído del disco tras importar).

	Al cambiar de sintetizador, el anterior guarda sus valores en memoria en la
	configuración (``synth.saveCurrentSettings``) y taparía los importados.
	"""
	for layer, saved in snapshot:
		if saved is _MISSING:
			speech = layer.get("speech")
			if isinstance(speech, dict):
				speech.pop("synths", None)
			continue
		if _getPath(layer, ("speech", "synths")) != saved:
			_setPath(layer, ("speech", "synths"), saved)


def _reloadOnCore(announce: str | None, then, activateProfile: str | None = None) -> None:
	try:
		_reloadSteps(announce, activateProfile)
	finally:
		if then is not None:
			# Sin esperar a la voz: el resumen (un diálogo) se lee al aparecer, ya
			# con la voz nueva, y así no se cuela antes la ventana que quedó debajo.
			try:
				then()
			except Exception:
				log.exception("Error tras aplicar la configuración importada")


def _reloadSteps(announce: str | None, activateProfile: str | None) -> None:
	from . import core
	from .config import conf

	if activateProfile:
		# Se conserva al volver a leer la configuración (si el perfil existe).
		conf.manualProfile = activateProfile
	try:
		conf.revertToSaved()
	except Exception:
		log.exception("No se pudo volver a leer la configuración importada")
	snapshot = _synthSettingsSnapshot(conf)
	try:
		from .input import gestures

		gestures.userMap.load()
	except Exception:
		log.exception("No se pudieron recargar los gestos")
	try:
		from .speech import dictionaries

		dictionaries.loadDefault()
		dictionaries._voiceKey = None
		dictionaries._profileKey = None
	except Exception:
		log.exception("No se pudieron recargar los diccionarios")
	try:
		from .speech import symbols

		symbols.reloadAll()
	except Exception:
		log.exception("No se pudieron recargar los símbolos")
	try:
		core.applyConfiguration()
	except Exception:
		log.exception("No se pudo aplicar la configuración importada")
	try:
		from . import synth

		# El sintetizador anterior ha guardado sus valores en memoria al
		# cerrarse: se vuelven a poner los importados y se le aplican al actual
		# (también si se ha vuelto a cargar el mismo controlador).
		_restoreSynthSettings(snapshot)
		s = synth.getSynth()
		if s is not None:
			section = conf["speech"]["synths"].get(s.name)
			if section is not None:
				s.loadSettings(section.dict() if hasattr(section, "dict") else dict(section))
		log.info("Configuración importada aplicada (sintetizador: %s)", s.name if s is not None else "ninguno")
	except Exception:
		log.exception("No se pudieron restaurar los ajustes importados del sintetizador")
	if announce:
		try:
			from . import speech

			speech.speakMessage(announce)
		except Exception:
			log.exception("No se pudo anunciar la importación")


# ====================================================================== línea de órdenes
def _print(text: str) -> None:
	try:
		print(text)
	except Exception:
		pass


def runFromCommandLine(folder: str | None, profile: str | None = None, args: Any = None) -> int:
	"""``--import-nvda-config [carpeta]``: importa sin interfaz y sale."""
	from . import startup
	from .config import conf

	paths.ensureDataDirs()
	if not conf.readOnly:
		# Política, datos de la copia instalada y configuración actual.
		startup.prepareConfiguration(args)
	if conf.readOnly:
		_print(_("La configuración es de solo lectura (modo seguro): no se puede importar."))
		return 2
	nvdaFolder = resolveFolder(folder or None)
	if nvdaFolder is None:
		_print(_("No se ha encontrado la configuración de NVDA en {folder}.").format(folder=folder or defaultNvdaFolder()))
		return 1
	try:
		from . import core

		if core.isRunning():
			_print(_("Aviso: Tiresias está en ejecución. Si guarda la configuración al salir, sustituirá a la importada; ciérralo antes o usa la importación desde su menú Herramientas."))
	except Exception:
		pass
	from . import first_run

	if first_run.currentStep() == first_run.STEP_NVDA:
		# Ya se ha importado: el primer arranque no volverá a preguntarlo (la importación lo guarda).
		first_run.setStep(first_run.STEP_WELCOME, save=False)
	try:
		plan = buildPlan(nvdaFolder)
		result = applyPlan(plan, None, profile)
	except ImportError_ as e:
		_print(str(e))
		return 2
	except OSError as e:
		_print(_("No se pudo importar: {error}").format(error=e))
		return 1
	_print(
		_("Importada la configuración de NVDA de {folder}: {settings} opciones, {profiles} perfiles, {gestures} gestos, {dicts} entradas de diccionario y {symbols} símbolos.").format(
			folder=nvdaFolder, settings=result.settings, profiles=result.profiles, gestures=result.gestures, dicts=result.dictEntries, symbols=result.symbols
		)
	)
	_print(_("Informe: {file}").format(file=result.report))
	_print(_("Copia exportada: {file}").format(file=result.export))
	_print(_("Copia de seguridad: {folder}").format(folder=result.backup))
	return 0


def undoFromCommandLine() -> int:
	"""``--undo-nvda-import``: deshace la última importación y sale."""
	from .config import conf

	try:
		folder = undoLastImport(conf)
	except ImportError_ as e:
		_print(str(e))
		return 1
	except OSError as e:
		_print(_("No se pudo deshacer: {error}").format(error=e))
		return 1
	_print(_("Importación deshecha con la copia {folder}.").format(folder=folder))
	return 0
