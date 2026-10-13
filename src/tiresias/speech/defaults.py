"""Valores por defecto de las opciones del núcleo de voz y lectura.

Se registran con :func:`tiresias.config.registerDefaults` al importar el
paquete :mod:`tiresias.speech`, de modo que existen antes de que se abra el
diálogo de opciones o se procese la primera frase.
"""

from __future__ import annotations

from ..config import registerDefaults

SPEECH_DEFAULTS: dict = {
	# Modos de voz que se saltan al cambiar de modo con Tiresias+S.
	"excludedSpeechModes": [],
	# Tono (Hz) del pitido del modo de voz «pitidos».
	"beepSpeechModePitch": 800,
	# Cancelar lo pendiente de un foco que ya no está (voz obsoleta).
	"cancelExpiredFocusSpeech": True,
	# Idioma: anunciar los cambios y qué hacer si la voz no admite el idioma.
	"reportLanguage": False,
	"reportNotSupportedLanguage": "speech",  # speech, beep, off
	# Detección automática del idioma: off, script (guion Unicode), full (guion y n-gramas).
	"languageDetection": "script",
	# Lectura de números: full, digits, pairs, triples.
	"numberReading": "full",
	# Separar letras y números en palabras mixtas («abc123» -> «abc 123»).
	"splitAlphanumeric": False,
	# Leer entidades HTML («&amp;», «&#233;») como el carácter que representan.
	"decodeHtmlEntities": True,
	# Leer por su nombre Unicode los símbolos que no están en la tabla.
	"reportUnknownSymbols": True,
	# Teclas de acceso habladas letra a letra («Alt+F» -> «Alt efe»).
	"spellAccessKeys": True,
	# Lectura continua.
	"sayAllUnit": "line",  # line, sentence, paragraph (foros 2.1)
	"sayAllWithoutPauses": True,
	"capitalsInSayAll": "off",  # off, initial, allCaps
	"sayAllNavigationKeys": False,
	"sayAllRateStep": 5,
	# Qué cambian Re Pág y Av Pág durante la lectura continua (foros 2.1):
	# "sayAll" (velocidad propia de la lectura continua, se recuerda),
	# "temporary" (solo esa lectura; al acabar vuelve a la normal) o
	# "global" (la velocidad de la voz, como antes).
	"sayAllRateMode": "sayAll",
	# Velocidad propia de la lectura continua: puntos sobre la de la voz.
	"sayAllRateOffset": 0,
	# Esquema de voz y sonido activo ("" = ninguno).
	"voiceScheme": "",
	# El esquema también fuera del modo exploración: controles con el foco y
	# texto editable (foros 2.4).
	"voiceSchemeEverywhere": True,
	# Voces por contexto: cambios relativos (porcentaje) de velocidad, tono y
	# volumen; además, otra voz del sintetizador ("" = la misma) y otro nivel de
	# puntuación (-1 = el general) por contexto (foros 2.3).
	"voiceContexts": False,
	"contextCaretRate": 0,
	"contextCaretPitch": 0,
	"contextCaretVolume": 0,
	"contextReviewRate": 0,
	"contextReviewPitch": 0,
	"contextReviewVolume": 0,
	"contextTypingRate": 0,
	"contextTypingPitch": 0,
	"contextTypingVolume": 0,
	"contextMessageRate": 0,
	"contextMessagePitch": 0,
	"contextMessageVolume": 0,
	"contextMenuRate": 0,
	"contextMenuPitch": 0,
	"contextMenuVolume": 0,
	"contextDialogRate": 0,
	"contextDialogPitch": 0,
	"contextDialogVolume": 0,
	"contextCaretVoice": "",
	"contextReviewVoice": "",
	"contextTypingVoice": "",
	"contextMessageVoice": "",
	"contextMenuVoice": "",
	"contextDialogVoice": "",
	"contextCaretSymbolLevel": -1,
	"contextReviewSymbolLevel": -1,
	"contextTypingSymbolLevel": -1,
	"contextMessageSymbolLevel": -1,
	"contextMenuSymbolLevel": -1,
	"contextDialogSymbolLevel": -1,
}

KEYBOARD_DEFAULTS: dict = {
	# Al editar una palabra existente, el eco dice la palabra completa (#8065).
	"speakWholeEditedWord": True,
}

PRESENTATION_DEFAULTS: dict = {
	# Nivel de verbosidad (#46): beginner (principiante), normal (intermedio), expert.
	"verbosity": "normal",
	# Mensajes de tutor: off, complex (solo controles complejos), all.
	"tutorMessages": "off",
	"tutorMessagesDelay": 1500,
	# Orden de las propiedades al anunciar un objeto (#7232).
	"propertyOrder": ["name", "role", "value", "states", "description", "shortcut", "position"],
	# Plantillas por rol: {"button": "{name} {role}"} (vacío = orden general).
	"roleTemplates": {},
}


def register() -> None:
	registerDefaults("speech", SPEECH_DEFAULTS)
	registerDefaults("keyboard", KEYBOARD_DEFAULTS)
	registerDefaults("presentation", PRESENTATION_DEFAULTS)


register()
