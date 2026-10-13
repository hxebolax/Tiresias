"""Transformaciones de texto previas a los símbolos: números y entidades.

- Lectura de números: completa (la hace el sintetizador), por dígitos, por
  pares o por grupos de tres.
- Lectura alfanumérica: separa letras y números en palabras mixtas para que
  el sintetizador no las lea como una sola palabra («abc123» -> «abc 123»).
- Entidades HTML (#3805): «&amp;», «&#233;» o «&#x20AC;» se leen como el
  carácter que representan.
"""

from __future__ import annotations

import html
import re

NUMBER_FULL = "full"
NUMBER_DIGITS = "digits"
NUMBER_PAIRS = "pairs"
NUMBER_TRIPLES = "triples"
NUMBER_MODES = (NUMBER_FULL, NUMBER_DIGITS, NUMBER_PAIRS, NUMBER_TRIPLES)

_digitRun = re.compile(r"\d{2,}")
_alnumBoundary = re.compile(r"(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])")
_entity = re.compile(r"&(#\d{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});")


def _groups(digits: str, size: int) -> str:
	return " ".join(digits[i : i + size] for i in range(0, len(digits), size))


#: Idiomas cuyo separador decimal es el punto (y la coma separa los miles).
#: En el resto (español, francés, alemán…) es al revés.
_DECIMAL_POINT_LANGUAGES = frozenset({"en", "ja", "zh", "ko", "he", "th", "hi", "ta", "ms", "fil", "sw", "ga", "mt"})
#: Palabra del separador decimal cuando no es el nombre del carácter
#: («point» en inglés, no «dot»).
_DECIMAL_WORDS = {"en": "point"}
#: Cifras unidas por puntos o comas: «1.500», «1,5», «1.500,25», «192.168.1.1».
_separatedNumber = re.compile(r"(?<!\d)\d+(?:[.,]\d+)+")


def _baseLanguage(language: str | None) -> str:
	return (language or "es").replace("-", "_").split("_")[0].lower() or "es"


def _separators(language: str | None) -> tuple[str, str]:
	"""``(decimal, miles)`` del idioma."""
	if _baseLanguage(language) in _DECIMAL_POINT_LANGUAGES:
		return ".", ","
	return ",", "."


def _separatorName(ch: str, language: str | None) -> str:
	"""Nombre del separador en el idioma de lectura (o el carácter, si no hay tabla)."""
	try:
		from .symbols import getProcessor

		proc = getProcessor(_baseLanguage(language))
		if proc is not None:
			return proc.characterName(ch)
	except Exception:
		pass
	return ch


def _isThousands(groups: list[str]) -> bool:
	"""``True`` si los grupos son de miles: 1 a 3 cifras y luego grupos de 3."""
	return 1 <= len(groups[0]) <= 3 and all(len(g) == 3 for g in groups[1:])


def _render(digits: str, mode: str) -> str:
	if mode == NUMBER_DIGITS:
		return " ".join(digits)
	if mode == NUMBER_PAIRS:
		return _groups(digits, 2)
	return _groups(digits, 3)


def _renderInteger(groups: list[str], mode: str) -> str:
	"""Parte entera escrita con separadores de miles (que no se leen)."""
	if mode == NUMBER_TRIPLES:
		# Los grupos que escribió el autor: «1.500» -> «1 500».
		return " ".join(groups)
	return _render("".join(groups), mode)


def _renderSeparated(m: re.Match, mode: str, language: str | None) -> str:
	token = m.group(0)
	groups = re.split(r"[.,]", token)
	seps = re.findall(r"[.,]", token)
	dec, thousands = _separators(language)
	# Solo separadores de miles: «1.500» (español) o «1,500» (inglés).
	if all(s == thousands for s in seps) and _isThousands(groups):
		return _renderInteger(groups, mode)
	# Decimal al final, con miles o sin ellos delante: «1,5», «1.500,25», «3.14» (inglés).
	if seps[-1] == dec and all(s == thousands for s in seps[:-1]) and (len(groups) == 2 or _isThousands(groups[:-1])):
		word = _DECIMAL_WORDS.get(_baseLanguage(language)) or _separatorName(dec, language)
		return f"{_renderInteger(groups[:-1], mode)} {word} {_render(groups[-1], mode)}"
	# Otra cosa (versiones, direcciones IP, fechas, «3.14» en español): cada
	# separador se dice por su nombre, para que la voz no lea un decimal.
	out = [_render(groups[0], mode)]
	for sep, g in zip(seps, groups[1:]):
		out.append(_separatorName(sep, language))
		out.append(_render(g, mode))
	return " ".join(out)


def applyNumberMode(text: str, mode: str, language: str | None = None) -> str:
	"""Agrupa las cifras según ``mode`` (ver ``NUMBER_MODES``).

	Las cifras unidas por puntos o comas se interpretan con las convenciones de
	``language`` (el idioma en que se leerá; español si es ``None``): en
	español el punto separa los miles y la coma los decimales, y en inglés al
	revés. Los separadores de miles no se leen; el decimal se dice con su
	nombre («1,5» -> «1 coma 5»). Antes «1.500» quedaba «1.5 0 0» y la voz lo
	leía como un decimal.
	"""
	if mode not in (NUMBER_DIGITS, NUMBER_PAIRS, NUMBER_TRIPLES):
		return text
	if "." in text or "," in text:
		text = _separatedNumber.sub(lambda m: _renderSeparated(m, mode, language), text)
	return _digitRun.sub(lambda m: _render(m.group(0), mode), text)


def splitAlphanumeric(text: str) -> str:
	"""Inserta un espacio entre letras y cifras contiguas."""
	return _alnumBoundary.sub(" ", text)


def decodeEntities(text: str) -> str:
	"""Sustituye las entidades HTML válidas por su carácter."""
	if "&" not in text:
		return text

	def _sub(m: re.Match) -> str:
		raw = m.group(0)
		decoded = html.unescape(raw)
		return decoded if decoded != raw else raw

	return _entity.sub(_sub, text)


def effectiveNumberMode(sp) -> str:
	"""Modo de lectura de números (``speech.numberReading``; ``full`` si no es válido)."""
	try:
		mode = sp["numberReading"]
	except KeyError:
		mode = NUMBER_FULL
	if mode not in NUMBER_MODES:
		mode = NUMBER_FULL
	return mode
