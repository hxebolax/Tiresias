"""Validación de tipos y rangos de la configuración.

Los archivos de configuración se escriben a mano a veces (o se corrompen,
o vienen de versiones antiguas). Antes de usarlos se comprueba cada valor
contra el valor por defecto del esquema:

- el tipo tiene que coincidir (con conversiones razonables: ``"true"`` o
  ``1`` para una casilla, ``"12"`` para un número...);
- los números se ajustan al rango permitido (:data:`RANGES`);
- los textos con valores fijos tienen que estar en la lista (:data:`CHOICES`).

Un valor que no se puede arreglar se elimina, así que vuelve a valer el
valor por defecto. Las claves desconocidas se conservan: pueden ser de un
complemento que todavía no se ha cargado.
"""

from __future__ import annotations

from typing import Any

#: Rangos de los valores numéricos: {(sección, clave): (mínimo, máximo)}.
RANGES: dict[tuple[str, str], tuple[float, float]] = {
	("speech", "symbolLevel"): (0, 300),
	("speech", "capitalPitchChange"): (-100, 100),
	("speech", "delayedCharacterDescriptionsDelay"): (100, 10000),
	("speech", "sayAllRateOffset"): (-100, 100),
	("speech", "repeatedSymbolsThreshold"): (2, 100),
	("speech", "speechHistorySize"): (10, 10000),
	("audio", "soundVolume"): (0, 100),
	("audio", "duckingLevel"): (0, 100),
	("audio", "keepAudioAwakeSeconds"): (0, 3600),
	("keyboard", "multiPressTimeout"): (100, 2000),
	("keyboard", "layerTimeout"): (1, 60),
	("mouse", "audioCoordinatesMinPitch"): (50, 10000),
	("mouse", "audioCoordinatesMaxPitch"): (50, 10000),
	("mouse", "reportDelay"): (0, 5000),
	("touch", "multiTapTimeout"): (100, 2000),
	("presentation", "progressBarSpeechInterval"): (1, 100),
	("presentation", "progressBarBeepInterval"): (1, 100),
	("presentation", "progressBarBeepMinHz"): (20, 2000),
	("browseMode", "maxLineLength"): (10, 1000),
	("browseMode", "linesPerPage"): (5, 500),
	("objects", "maxLengthWarningThreshold"): (1, 1000),
	("documentNavigation", "textParagraphMinLength"): (0, 1000),
	("braille", "cursorBlinkRate"): (100, 2000),
	("braille", "messageTimeout"): (1, 60),
	("braille", "numCellsForViewer"): (10, 120),
	("vision", "highlightThickness"): (1, 30),
	("magnifier", "level"): (1.0, 16.0),
	("magnifier", "step"): (0.1, 4.0),
	("magnifier", "panStep"): (1, 50),
	("ocr", "autoRefreshInterval"): (250, 60000),
	("clipboard", "historySize"): (1, 1000),
	("uia", "connectionTimeout"): (100, 30000),
	("advanced", "watchdogTimeout"): (2, 120),
	("advanced", "watchdogRestartTimeout"): (5, 600),
	("advanced", "eventCoalesceMs"): (0, 1000),
	("update", "intervalHours"): (1, 24 * 30),
	# Los mismos límites que los cuadros numéricos del cuadro de Opciones.
	("speech", "beepSpeechModePitch"): (50, 5000),
	("speech", "sayAllRateStep"): (1, 50),
	("audio", "whiteNoiseVolume"): (0, 100),
	("audio", "mixerVolumeStep"): (1, 50),
	("audio", "startupVolumeLevel"): (5, 100),
	("braille", "autoScrollRate"): (1, 20),
	("braille", "cursorShapeFocus"): (1, 255),
	("braille", "cursorShapeReview"): (1, 255),
	("braille", "pcKeyboardDots"): (6, 8),
	("brailleViewer", "hoverDwellTime"): (200, 5000),
	("vision", "highlightPadding"): (0, 30),
	("vision", "highlightRefreshInterval"): (0, 10000),
	("magnifier", "overviewSeconds"): (1, 30),
	("magnifier", "dockSize"): (10, 70),
	("magnifier", "lensWidth"): (100, 2000),
	("magnifier", "lensHeight"): (60, 1500),
	("magnifier", "spotlightOpacity"): (10, 95),
	("mouseKeys", "step"): (1, 500),
	("touch", "edgeMargin"): (4, 200),
	("presentation", "tutorMessagesDelay"): (0, 10000),
	("objects", "slowProviderThresholdMs"): (100, 10000),
	("terminal", "maxLinesPerUpdate"): (1, 1000),
	("ocr", "continuousInterval"): (300, 60000),
	("ocr", "continuousSimilarity"): (50, 100),
	("ocr", "pdfScale"): (1, 4),
	("ocr", "pdfMaxPages"): (0, 5000),
	("ai", "timeout"): (10, 600),
	("ai", "maxContextChars"): (1000, 2000000),
	("ai", "localMaxContextChars"): (1000, 2000000),
	("ai", "agentMaxSteps"): (1, 100),
	("ai", "autoLabelMaxPerHour"): (1, 500),
	("ai", "altTextMaxImages"): (1, 200),
	("ai", "captchaDuckVolume"): (0, 100),
	("ai", "captchaDuckSeconds"): (3, 120),
	("officeExcel", "watchedCellsInterval"): (250, 60000),
	("chatApps", "historySize"): (10, 1000),
	("charts", "toneDuration"): (30, 1000),
	("notifications", "historySize"): (10, 5000),
	("watch", "maxWatches"): (1, 10),
	("watch", "intervalMs"): (250, 10000),
	("remote", "connectTimeout"): (3, 120),
	("remote", "reconnectDelay"): (2, 120),
	("coexist", "hangTimeout"): (5, 600),
}

# Voces por contexto: cambios relativos (porcentaje) y nivel de puntuación propio.
for _ctx in ("Caret", "Review", "Typing", "Message", "Menu", "Dialog"):
	RANGES[("speech", f"context{_ctx}Rate")] = (-80, 200)
	RANGES[("speech", f"context{_ctx}Pitch")] = (-80, 80)
	RANGES[("speech", f"context{_ctx}Volume")] = (-90, 0)
	RANGES[("speech", f"context{_ctx}SymbolLevel")] = (-1, 300)
del _ctx

#: Valores permitidos de las opciones de texto con una lista fija.
CHOICES: dict[tuple[str, str], tuple[str, ...]] = {
	("general", "logLevel"): ("OFF", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
	("speech", "speechMode"): ("talk", "onDemand", "beeps", "off"),
	("speech", "sayAllUnit"): ("line", "sentence", "paragraph"),
	("speech", "sayAllRateMode"): ("sayAll", "temporary", "global"),
	("keyboard", "layout"): ("desktop", "laptop"),
	("keyboard", "speakTypedCharacters"): ("off", "always", "editOnly"),
	("keyboard", "speakTypedWords"): ("off", "always", "editOnly"),
	("keyboard", "gestureLayout"): ("tiresias", "jaws"),
	("mouse", "mouseTextUnit"): ("character", "word", "line", "paragraph"),
	("presentation", "progressBarOutputMode"): ("off", "speak", "beep", "both"),
	("documentFormatting", "reportLineIndentation"): ("off", "speech", "tones", "both"),
	("documentFormatting", "reportCellBorders"): ("off", "styles", "colorsAndStyles"),
	("documentFormatting", "colorFormat"): ("name", "nameAndRgb", "nameAndHex"),
	("documentNavigation", "paragraphQuickNav"): ("role", "text", "both"),
	("documentNavigation", "paragraphStyle"): ("application", "singleLineBreak", "multiLineBreak"),
	("browseMode", "loadingIndicator"): ("off", "beep", "speech"),
	("objects", "maxLengthWarning"): ("off", "threshold", "countdown"),
	("braille", "showMessages"): ("disabled", "timeout", "always"),
	("braille", "tetherTo"): ("auto", "focus", "review"),
	("braille", "focusContextPresentation"): ("fill", "changedContext", "scroll"),
	("uia", "eventRegistration"): ("selective", "global"),
	("advanced", "watchdogRecovery"): ("off", "cancel", "restart"),
	# Las mismas listas que las listas desplegables del cuadro de Opciones (las que
	# dependen del equipo, como dispositivos, tablas, voces o idiomas, no se fijan).
	("speech", "languageDetection"): ("off", "script", "full"),
	("speech", "reportNotSupportedLanguage"): ("speech", "beep", "off"),
	("speech", "numberReading"): ("full", "digits", "pairs", "triples"),
	("speech", "capitalsInSayAll"): ("off", "initial", "allCaps"),
	("presentation", "verbosity"): ("beginner", "normal", "expert"),
	("presentation", "tutorMessages"): ("off", "complex", "all"),
	("audio", "outputMode"): ("wasapi", "waveOut"),
	("audio", "bufferSize"): ("low", "normal", "high"),
	("audio", "soundSplitMode"): ("off", "leftRight", "rightLeft", "leftBoth", "rightBoth", "bothLeft", "bothRight"),
	("audio", "duckingMode"): ("off", "speaking", "always"),
	("audio", "volumeChangeFeedback"): ("off", "sound", "speech", "both"),
	("earcons", "mode"): ("off", "withSpeech", "insteadOfSpeech"),
	("braille", "mode"): ("followCursors", "speechOutput"),
	("braille", "reviewRoutingMovesSystemCaret"): ("never", "onlyWhenAutoTethered", "always"),
	("braille", "paragraphStartMarker"): ("", " ", "¶"),
	("braille", "textWrap"): ("none", "markWordCuts", "wordBoundaries", "syllableBoundaries"),
	("braille", "fontFormattingDisplay"): ("off", "liblouis", "dots78"),
	("braille", "undefinedCharacters"): ("hex", "allDots", "questionMark", "omit"),
	("braille", "splitView"): ("off", "speech", "review", "title", "clock"),
	("magnifier", "view"): ("fullscreen", "docked", "lens", "spotlight"),
	("magnifier", "filter"): ("none", "invert", "grayscale", "grayscaleInverted", "sepia", "yellowOnBlack"),
	("magnifier", "lastFilter"): ("invert", "grayscale", "grayscaleInverted", "sepia", "yellowOnBlack"),
	("magnifier", "trackingMode"): ("center", "edge", "relative"),
	("magnifier", "dockPosition"): ("top", "bottom", "left", "right"),
	("mouseKeys", "coordinates"): ("screen", "window"),
	("touch", "textUnit"): ("character", "word", "line", "paragraph"),
	("ocr", "engine"): ("windows", "tesseract"),
	("clipboard", "appendSeparator"): ("newline", "blankLine", "space", "none"),
	("terminal", "diffAlgorithm"): ("characters", "lines"),
	("update", "channel"): ("estable", "beta"),
	("update", "origin"): ("ambos", "servidor", "github", "propio"),
	("math", "verbosity"): ("breve", "normal", "detallado"),
	("math", "style"): ("natural", "estructural"),
	("math", "browseMode"): ("speech", "interactive"),
	("math", "copyFormat"): ("mathml", "latex", "text"),
	("ai", "provider"): ("anthropic", "openai", "gemini", "local"),
	("ai", "captchaDuckMode"): ("lower", "mute", "off"),
	("officeExcel", "readLineFrom"): ("start", "current"),
	("mail", "openMessageReading"): ("body", "none", "full"),
	("chatApps", "alertMode"): ("all", "beep", "off"),
}

#: Valores permitidos de los elementos de las opciones que son listas (los que no
#: están se quitan de la lista).
LIST_CHOICES: dict[tuple[str, str], tuple[Any, ...]] = {
	("speech", "excludedSpeechModes"): CHOICES[("speech", "speechMode")],
	("audio", "includedSoundSplitModes"): CHOICES[("audio", "soundSplitMode")],
	("presentation", "propertyOrder"): ("name", "role", "value", "states", "description", "shortcut", "position", "level"),
	("braille", "propertyOrder"): ("name", "role", "value", "states", "level", "position", "itemCount", "table", "placeholder", "description", "shortcut"),
	("braille", "hiddenProperties"): ("name", "role", "value", "states", "level", "position", "itemCount", "table", "placeholder", "description", "shortcut"),
}

#: Tipo de los elementos de las listas que empiezan vacías (en las demás, el de
#: los elementos del valor por defecto).
LIST_TYPES: dict[tuple[str, str], type] = {
	("speechViewer", "position"): int,
	("advanced", "debugCategories"): str,
	("addons", "disabled"): str,
	("addons", "overrideCompatibility"): str,
	("brailleDisplays", "excludedFromAuto"): str,
	("objects", "msaaClasses"): str,
	("objects", "uiaClasses"): str,
	("appModules", "sleepApps"): str,
}

#: Secciones cuyo contenido es libre (no se valida clave a clave).
FREE_SECTIONS = {("speech", "synths")}


class Issue:
	"""Un problema encontrado (y corregido) en un valor."""

	def __init__(self, path: tuple[str, ...], message: str) -> None:
		self.path = path
		self.message = message

	def __str__(self) -> str:
		return f"{'.'.join(self.path)}: {self.message}"

	def __repr__(self) -> str:
		return f"Issue({self})"


_MISSING = object()
_TRUE = {"true", "sí", "si", "yes", "1", "on"}
_FALSE = {"false", "no", "0", "off"}


def coerce(value: Any, default: Any, path: tuple[str, ...] = ()) -> Any:
	"""Convierte ``value`` al tipo de ``default``; devuelve ``_MISSING`` si no puede."""
	if isinstance(default, bool):
		if isinstance(value, bool):
			return value
		if isinstance(value, (int, float)) and value in (0, 1):
			return bool(value)
		if isinstance(value, str) and value.strip().lower() in _TRUE | _FALSE:
			return value.strip().lower() in _TRUE
		return _MISSING
	if isinstance(default, int):
		if isinstance(value, bool):
			return _MISSING
		if isinstance(value, int):
			result: Any = value
		elif isinstance(value, float) and value.is_integer():
			result = int(value)
		elif isinstance(value, str):
			try:
				result = int(value.strip())
			except ValueError:
				return _MISSING
		else:
			return _MISSING
		return _clamp(result, path)
	if isinstance(default, float):
		if isinstance(value, bool):
			return _MISSING
		if isinstance(value, (int, float)):
			result = float(value)
		elif isinstance(value, str):
			try:
				result = float(value.strip().replace(",", "."))
			except ValueError:
				return _MISSING
		else:
			return _MISSING
		return _clamp(result, path)
	if isinstance(default, str):
		if not isinstance(value, str):
			return _MISSING
		allowed = CHOICES.get(path[-2:]) if len(path) >= 2 else None
		if allowed and value not in allowed:
			# Mayúsculas y minúsculas distintas en los niveles de registro.
			for a in allowed:
				if a.lower() == value.lower():
					return a
			return _MISSING
		return value
	if isinstance(default, list):
		if isinstance(value, list):
			items = value
		elif isinstance(value, tuple):
			items = list(value)
		elif isinstance(value, str):
			items = [p.strip() for p in value.split(",") if p.strip()]
		else:
			return _MISSING
		return _coerceItems(items, default, path)
	if isinstance(default, dict):
		return value if isinstance(value, dict) else _MISSING
	return value


def _coerceItems(items: list, default: list, path: tuple[str, ...]) -> list:
	"""Elementos válidos de una opción de tipo lista (los demás se quitan)."""
	key = path[-2:] if len(path) >= 2 else None
	itemType = LIST_TYPES.get(key) if key else None
	if itemType is None and default:
		types = {type(d) for d in default}
		itemType = types.pop() if len(types) == 1 else None
	allowed = LIST_CHOICES.get(key) if key else None
	if itemType is None and allowed is None:
		return items
	out = []
	for item in items:
		if itemType is str:
			if not isinstance(item, str):
				continue
		elif itemType is int:
			if isinstance(item, bool):
				continue
			if isinstance(item, float) and item.is_integer():
				item = int(item)
			elif isinstance(item, str):
				try:
					item = int(item.strip())
				except ValueError:
					continue
			elif not isinstance(item, int):
				continue
		if allowed is not None and item not in allowed:
			continue
		out.append(item)
	return out


def _clamp(value: Any, path: tuple[str, ...]) -> Any:
	rng = RANGES.get(path[-2:]) if len(path) >= 2 else None
	if rng is None:
		return value
	lo, hi = rng
	return type(value)(min(max(value, lo), hi))


def validate(data: dict, defaults: dict, path: tuple[str, ...] = ()) -> list[Issue]:
	"""Corrige ``data`` en el sitio según ``defaults``. Devuelve los problemas encontrados."""
	issues: list[Issue] = []
	if path in FREE_SECTIONS:
		return issues
	for key in list(data):
		value = data[key]
		default = defaults.get(key, _MISSING) if isinstance(defaults, dict) else _MISSING
		sub = path + (key,)
		if default is _MISSING:
			continue
		if isinstance(default, dict):
			if not isinstance(value, dict):
				issues.append(Issue(sub, "se esperaba una sección; se usa el valor por defecto"))
				del data[key]
				continue
			issues.extend(validate(value, default, sub))
			continue
		fixed = coerce(value, default, sub)
		if fixed is _MISSING:
			issues.append(Issue(sub, f"valor no válido {value!r}; se usa el valor por defecto"))
			del data[key]
		elif fixed != value or type(fixed) is not type(value):
			issues.append(Issue(sub, f"valor {value!r} corregido a {fixed!r}"))
			data[key] = fixed
	return issues


def isValidValue(section: str, key: str, value: Any, defaults: dict) -> bool:
	"""``True`` si ``value`` es aceptable para ``section.key`` sin cambiarlo."""
	default = defaults.get(section, {}).get(key, _MISSING) if isinstance(defaults.get(section), dict) else _MISSING
	if default is _MISSING:
		return True
	fixed = coerce(value, default, (section, key))
	return fixed is not _MISSING and fixed == value
