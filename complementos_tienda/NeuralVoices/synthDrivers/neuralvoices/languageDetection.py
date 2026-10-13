"""Detección del idioma del texto según la escritura Unicode de cada carácter.

Divide las cadenas de una secuencia de voz en trozos de una misma escritura
(latina, cirílica, árabe, han...) y antepone a cada trozo un
:class:`LangChangeCommand` con el idioma asignado a esa escritura. Así el
sintetizador cambia a la voz de ese idioma.

Basado en ``languageDetection.py`` del complemento NeuralVoices de Alexander
Linkov (GPL).
"""

from __future__ import annotations

import unicodedata
from io import StringIO
from typing import Iterable, Iterator, Mapping

from tiresias.speech.commands import LangChangeCommand

from .scripts import scriptOf

#: Idiomas que se escriben con el alfabeto latino.
LATIN = (
	"en", "ha", "so", "id", "la", "sw", "eu",
	"nr", "zu", "xh", "ss", "st", "tn", "ts",
	"cs", "af", "pl", "hr", "ro", "sk", "sl", "tr", "hu", "az",
	"et", "sq", "ca", "es", "gl", "fr", "de", "nl", "it", "da", "is", "nb", "sv",
	"fi", "lv", "pt", "ve", "lt", "tl", "cy", "vi", "no", "uz",
)  # fmt: skip

#: Idiomas que se escriben con el alfabeto cirílico.
CYRILLIC = ("ru", "uk", "be", "kk", "tt", "uz", "mn", "sr", "mk", "bg", "ky")
#: Idiomas que se escriben con el alfabeto árabe.
ARABIC = ("ar", "fa", "ps", "ur")
#: Idiomas que se escriben en devanagari.
DEVANAGARI = ("hi", "sa", "mr", "ne")
#: Idiomas que usan los caracteres han (chino, japonés, coreano).
CJK = ("zh", "ja", "ko")

#: Idioma de cada escritura por defecto (las latina, cirílica y han se pueden cambiar).
DEFAULT_SCRIPT_LANGUAGES = {
	"Latin": "en",
	"Cyrillic": "ru",
	"Arabic": "ar",
	"Devanagari": "hi",
	"Han": "zh",
	"Armenian": "hy",
	"Hebrew": "he",
	"Bengali": "bn",
	"Gurmukhi": "pa",
	"Greek": "el",
	"Gujarati": "gu",
	"Oriya": "or",
	"Tamil": "ta",
	"Telugu": "te",
	"Kannada": "kn",
	"Malayalam": "ml",
	"Sinhala": "si",
	"Thai": "th",
	"Lao": "lo",
	"Tibetan": "bo",
	"Georgian": "ka",
	"Mongolian": "mn",
	"Khmer": "km",
	"Hiragana": "ja",
	"Katakana": "ja",
	"Hangul": "ko",
}


def addDetectedLanguageCommands(
	speechSequence: Iterable,
	defaultLang: str,
	scriptLanguages: Mapping[str, str],
	ignoreNumbersInLanguageDetection: bool,
) -> Iterator:
	"""Devuelve la secuencia con un cambio de idioma delante de cada trozo de texto.

	``defaultLang`` es el idioma de la voz actual (también el de los números,
	salvo que ``ignoreNumbersInLanguageDetection`` sea verdadero: entonces
	los números se leen en el idioma del texto que los rodea). Los cambios de
	idioma que ya trae la secuencia se respetan.
	"""
	curScript = None
	curLang = defaultLang
	for command in speechSequence:
		if isinstance(command, LangChangeCommand):
			curLang = defaultLang if command.lang is None else command.lang
			curScript = None
		elif isinstance(command, str):
			sb = StringIO()
			for c in command:
				newScript = scriptOf(ord(c))
				newLang = curLang
				if newScript == "Common":
					category = unicodedata.category(c)
					if category.startswith("N") and not ignoreNumbersInLanguageDetection:
						newLang = defaultLang
					else:
						newScript = None
				elif newScript is not None and newScript != curScript:
					newLang = scriptLanguages.get(newScript, curLang)
				if curLang != newLang:
					if curScript is not None and sb.tell() > 0:
						yield LangChangeCommand(curLang)
						yield sb.getvalue()
						sb = StringIO()
					curLang = newLang
				if newScript is not None:
					curScript = newScript
				sb.write(c)
			# Lo que quede de la cadena, con su idioma.
			if sb.tell() > 0:
				yield LangChangeCommand(curLang)
				yield sb.getvalue()
		else:
			yield command
