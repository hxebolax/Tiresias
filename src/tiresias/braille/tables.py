"""Tablas de traducción braille.

Cada celda se representa como un entero con un bit por punto (punto 1 = 0x01
... punto 8 = 0x80), igual que el bloque Unicode de braille (U+2800 + valor).

Hay dos familias de tablas:

- **liblouis** (``data/louis``): más de 250 tablas de todos los idiomas,
  integrales y contraídas, de salida y de entrada. El catálogo se construye
  leyendo los metadatos de cada tabla (``#+language``, ``#+contraction``...)
  y se muestra con nombres en español (#11298, #20736).
- **Propias** (alternativa si liblouis no se puede cargar):

  - ``es-comp8``: braille informático de 8 puntos (las mayúsculas llevan el
    punto 7; acentos y eñe según el braille español).
  - ``es-g1``: braille literario español de 6 puntos (signo de mayúscula 46 y
    signo de número 3456).
  - tablas JSON en ``data/brailleTables/<nombre>.json``::

	{"name": "Mi tabla", "cells": {"a": "1", "€": "15-1236"}, "eightDot": true}

La función :func:`translate` añade lo que no hacen las tablas por sí solas:
normalización Unicode, descripción de emojis y representación configurable
de los caracteres no definidos, conservando siempre la correspondencia entre
caracteres y celdas (cursor, enrutamiento, selección).
"""

from __future__ import annotations

import json
import os
import threading
import unicodedata
from dataclasses import dataclass, field
from typing import Sequence

from .. import paths
from ..i18n import _
from ..log import getLogger
from . import liblouis

log = getLogger("brailleTables")

AUTO = "auto"


def dots(spec: str) -> int:
	"""``"1246"`` -> máscara de bits. Admite celdas separadas por guion."""
	val = 0
	for ch in spec:
		if ch.isdigit() and ch != "0":
			val |= 1 << (int(ch) - 1)
	return val


def cellsFromSpec(spec: str) -> list[int]:
	return [dots(part) for part in spec.split("-")] if spec else [0]


def dotsLabel(cell: int) -> str:
	"""``0x0B`` -> ``"124"`` (para anunciar celdas)."""
	return "".join(str(i + 1) for i in range(8) if cell & (1 << i))


_LETTERS = {
	"a": "1",
	"b": "12",
	"c": "14",
	"d": "145",
	"e": "15",
	"f": "124",
	"g": "1245",
	"h": "125",
	"i": "24",
	"j": "245",
	"k": "13",
	"l": "123",
	"m": "134",
	"n": "1345",
	"o": "135",
	"p": "1234",
	"q": "12345",
	"r": "1235",
	"s": "234",
	"t": "2345",
	"u": "136",
	"v": "1236",
	"w": "2456",
	"x": "1346",
	"y": "13456",
	"z": "1356",
	"á": "12356",
	"é": "2346",
	"í": "34",
	"ó": "346",
	"ú": "23456",
	"ü": "1256",
	"ñ": "12456",
	"ç": "12346",
	"à": "12356",
	"è": "2346",
	"ì": "34",
	"ò": "346",
	"ù": "23456",
}

# Braille ASCII norteamericano (para símbolos en la tabla informática).
_BRAILLE_ASCII = {
	" ": "",
	"!": "2346",
	'"': "5",
	"#": "3456",
	"$": "1246",
	"%": "146",
	"&": "12346",
	"'": "3",
	"(": "12356",
	")": "23456",
	"*": "16",
	"+": "346",
	",": "6",
	"-": "36",
	".": "46",
	"/": "34",
	"0": "356",
	"1": "2",
	"2": "23",
	"3": "25",
	"4": "256",
	"5": "26",
	"6": "235",
	"7": "2356",
	"8": "236",
	"9": "35",
	":": "156",
	";": "56",
	"<": "126",
	"=": "123456",
	">": "345",
	"?": "1456",
	"@": "47",
	"[": "2467",
	"\\": "12567",
	"]": "124567",
	"^": "457",
	"_": "456",
	"`": "4",
	"{": "246",
	"|": "1256",
	"}": "12456",
	"~": "45",
}

# Puntuación del braille español (6 puntos).
_ES_PUNCT = {
	" ": "",
	",": "2",
	".": "3",
	";": "23",
	":": "25",
	"¿": "26",
	"?": "26",
	"¡": "235",
	"!": "235",
	'"': "236",
	"«": "236",
	"»": "236",
	"“": "236",
	"”": "236",
	"(": "126",
	")": "345",
	"[": "12356",
	"]": "23456",
	"-": "36",
	"'": "3",
	"*": "35",
	"/": "6-2",
	"@": "5",
	"&": "12346",
	"%": "456-356",
	"+": "235",
	"=": "2356",
	"€": "4-15",
	"$": "4-234",
}

_DIGIT_LETTERS = {"1": "a", "2": "b", "3": "c", "4": "d", "5": "e", "6": "f", "7": "g", "8": "h", "9": "i", "0": "j"}
_LETTER_DIGITS = {v: k for k, v in _DIGIT_LETTERS.items()}

CAPITAL_SIGN = dots("46")
NUMBER_SIGN = dots("3456")
UNKNOWN_CELL = dots("12345678")


@dataclass
class Translation:
	cells: list[int]
	#: Para cada carácter del texto, índice de su primera celda.
	rawToBraille: list[int] = field(default_factory=list)
	#: Para cada celda, índice del carácter de texto.
	brailleToRaw: list[int] = field(default_factory=list)
	#: Celda del cursor (si se pidió); en braille contraído la calcula liblouis.
	cursorPos: int | None = None

	def cellForRaw(self, raw: int) -> int:
		"""Celda que corresponde al carácter ``raw`` (o el final)."""
		if 0 <= raw < len(self.rawToBraille):
			return self.rawToBraille[raw]
		return len(self.cells)


class Table:
	"""Tabla de traducción.

	``kind``: ``"computer"`` o ``"literary"``; ``contracted``: braille
	contraído; ``forInput`` / ``forOutput``: sentidos en que se puede usar.
	"""

	source = "tiresias"

	def __init__(self, name: str, displayName: str, eightDot: bool) -> None:
		self.name = name
		self.displayName = displayName
		self.eightDot = eightDot
		self.contracted = False
		self.kind = "computer" if eightDot else "literary"
		self.language = "es"
		self.forInput = True
		self.forOutput = True
		self.map: dict[str, list[int]] = {}

	def translate(self, text: str, cursor: int | None = None, expandAtCursor: bool = False, typeform: Sequence[int] | None = None) -> Translation:
		raise NotImplementedError

	def backTranslate(self, cells: Sequence[int]) -> str:
		raise NotImplementedError

	def isDefined(self, ch: str) -> bool:
		return ch in self.map or ch.lower() in self.map or ch.isspace()

	def __repr__(self) -> str:
		return f"<{type(self).__name__} {self.name}>"


def _reverseMap(table: Table) -> dict[int, str]:
	"""Celda -> carácter (para la entrada). Gana el primer carácter definido."""
	out: dict[int, str] = {}
	for ch, cells in table.map.items():
		if len(ch) == 1 and len(cells) == 1 and cells[0] not in out and not ch.isupper():
			out[cells[0]] = ch
	return out


class Computer8Table(Table):
	def __init__(self) -> None:
		super().__init__("es-comp8", _("Español, braille informático de 8 puntos (tabla propia)"), True)
		for ch, spec in _LETTERS.items():
			self.map[ch] = [dots(spec)]
			self.map[ch.upper()] = [dots(spec) | 0x40]
		for ch, spec in _BRAILLE_ASCII.items():
			self.map.setdefault(ch, [dots(spec)])
		self.map["¿"] = [dots("267")]
		self.map["¡"] = [dots("2357")]
		self.map["€"] = [dots("1578")]
		self.map["º"] = [dots("1358")]
		self.map["ª"] = [dots("18")]
		self.map["\t"] = [0]
		self._reverse: dict[int, str] | None = None

	def translate(self, text: str, cursor: int | None = None, expandAtCursor: bool = False, typeform: Sequence[int] | None = None) -> Translation:
		cells: list[int] = []
		raw2b: list[int] = []
		b2raw: list[int] = []
		for i, ch in enumerate(text):
			raw2b.append(len(cells))
			c = self.map.get(ch)
			if c is None:
				low = ch.lower()
				base = self.map.get(low)
				c = [base[0] | 0x40] if base and ch != low else [UNKNOWN_CELL if not ch.isspace() else 0]
			for cell in c:
				cells.append(cell)
				b2raw.append(i)
		return Translation(cells, raw2b, b2raw)

	def backTranslate(self, cells: Sequence[int]) -> str:
		if self._reverse is None:
			self._reverse = _reverseMap(self)
		out = []
		for cell in cells:
			ch = self._reverse.get(cell)
			if ch is None and cell & 0x40:
				# Punto 7 sin carácter propio: mayúscula de la letra (y solo de letras).
				base = self._reverse.get(cell & ~0x40)
				if base is not None and base.isalpha():
					ch = base.upper()
			if ch is None and cell == 0:
				ch = " "
			if ch is not None:
				out.append(ch)
		return "".join(out)


class Grade1SpanishTable(Table):
	def __init__(self) -> None:
		super().__init__("es-g1", _("Español, braille literario de 6 puntos (tabla propia)"), False)
		for ch, spec in _LETTERS.items():
			self.map[ch] = [dots(spec)]
		for ch, spec in _ES_PUNCT.items():
			self.map[ch] = cellsFromSpec(spec)
		self._reverse: dict[int, str] | None = None

	def isDefined(self, ch: str) -> bool:
		return super().isDefined(ch) or ch in _DIGIT_LETTERS

	def translate(self, text: str, cursor: int | None = None, expandAtCursor: bool = False, typeform: Sequence[int] | None = None) -> Translation:
		cells: list[int] = []
		raw2b: list[int] = []
		b2raw: list[int] = []
		inNumber = False
		for i, ch in enumerate(text):
			raw2b.append(len(cells))
			out: list[int] = []
			if ch.isdigit() and ch in _DIGIT_LETTERS:
				if not inNumber:
					out.append(NUMBER_SIGN)
					inNumber = True
				out.append(dots(_LETTERS[_DIGIT_LETTERS[ch]]))
			else:
				if inNumber and ch in ".,":
					# Separadores dentro de números: punto 3 y punto 2.
					out.append(dots("3") if ch == "." else dots("2"))
				else:
					inNumber = False
					low = ch.lower()
					if ch != low and low in self.map:
						out.append(CAPITAL_SIGN)
						out.extend(self.map[low])
					elif ch in self.map:
						out.extend(self.map[ch])
					elif ch.isspace():
						out.append(0)
					else:
						out.append(dots("123456"))
			for cell in out:
				cells.append(cell)
				b2raw.append(i)
		return Translation(cells, raw2b, b2raw)

	def backTranslate(self, cells: Sequence[int]) -> str:
		"""Braille literario a texto: signo de número, de mayúscula y de
		palabra en mayúsculas (46-46)."""
		if self._reverse is None:
			self._reverse = {}
			for ch, spec in _LETTERS.items():
				self._reverse.setdefault(dots(spec), ch)
			for ch, spec in _ES_PUNCT.items():
				c = cellsFromSpec(spec)
				if len(c) == 1 and c[0]:
					self._reverse.setdefault(c[0], ch)
		out: list[str] = []
		number = False
		capNext = False
		capWord = False
		i = 0
		cells = [c & 0x3F for c in cells]
		while i < len(cells):
			c = cells[i]
			if c == 0:
				out.append(" ")
				number = capNext = capWord = False
			elif c == NUMBER_SIGN:
				number = True
			elif c == CAPITAL_SIGN:
				if i + 1 < len(cells) and cells[i + 1] == CAPITAL_SIGN:
					capWord = True
					i += 1
				else:
					capNext = True
			else:
				ch = self._reverse.get(c)
				if number:
					if ch in _LETTER_DIGITS:
						out.append(_LETTER_DIGITS[ch])
						i += 1
						continue
					if c in (dots("3"), dots("2")):
						out.append("." if c == dots("3") else ",")
						i += 1
						continue
					number = False
				if ch is not None:
					if capNext or capWord:
						ch = ch.upper()
					capNext = False
					out.append(ch)
			i += 1
		return "".join(out)


class JsonTable(Computer8Table):
	"""Tabla definida por el usuario (se basa en la informática de 8 puntos)."""

	def __init__(self, name: str, data: dict) -> None:
		super().__init__()
		self.name = name
		self.displayName = data.get("name", name)
		self.eightDot = bool(data.get("eightDot", True))
		for ch, spec in data.get("cells", {}).items():
			self.map[ch] = cellsFromSpec(str(spec))


# ---------------------------------------------------------------------- liblouis
_LANG_NAMES = {
	"af": "afrikáans",
	"akk": "acadio",
	"ar": "árabe",
	"arc": "arameo",
	"as": "asamés",
	"awa": "awadhi",
	"ba": "baskir",
	"be": "bielorruso",
	"bg": "búlgaro",
	"bh": "bihari",
	"bn": "bengalí",
	"bo": "tibetano",
	"bra": "braj",
	"ca": "catalán",
	"chr": "cheroqui",
	"ckb": "kurdo central",
	"cmn": "chino mandarín",
	"cop": "copto",
	"cs": "checo",
	"cy": "galés",
	"da": "danés",
	"de": "alemán",
	"dra": "dravídico",
	"el": "griego",
	"elx": "elamita",
	"en": "inglés",
	"eo": "esperanto",
	"es": "español",
	"et": "estonio",
	"fa": "persa",
	"fi": "finés",
	"fil": "filipino",
	"fr": "francés",
	"ga": "irlandés",
	"gd": "gaélico escocés",
	"gez": "ge'ez",
	"gon": "gondi",
	"grc": "griego antiguo",
	"gu": "guyaratí",
	"haw": "hawaiano",
	"hbo": "hebreo antiguo",
	"he": "hebreo",
	"hi": "hindi",
	"hit": "hitita",
	"hr": "croata",
	"ht": "criollo haitiano",
	"hu": "húngaro",
	"hy": "armenio",
	"is": "islandés",
	"it": "italiano",
	"iu": "inuktitut",
	"ja": "japonés",
	"jpa": "arameo palestino judío",
	"ka": "georgiano",
	"kha": "khasi",
	"kk": "kazajo",
	"km": "jemer",
	"kmr": "kurdo septentrional",
	"kn": "canarés",
	"ko": "coreano",
	"kok": "konkaní",
	"kru": "kurukh",
	"lg": "luganda",
	"lo": "lao",
	"lt": "lituano",
	"lv": "letón",
	"mi": "maorí",
	"mk": "macedonio",
	"ml": "malayalam",
	"mn": "mongol",
	"mni": "manipurí",
	"mr": "maratí",
	"ms": "malayo",
	"mt": "maltés",
	"mun": "munda",
	"mwr": "marwari",
	"my": "birmano",
	"nb": "noruego bokmål",
	"ne": "nepalí",
	"nl": "neerlandés",
	"nn": "noruego nynorsk",
	"no": "noruego",
	"nso": "sotho septentrional",
	"ny": "chichewa",
	"oar": "arameo antiguo",
	"obm": "moabita",
	"or": "oriya",
	"ovd": "dalecarliano",
	"pa": "panyabí",
	"peo": "persa antiguo",
	"phn": "fenicio",
	"pi": "pali",
	"pl": "polaco",
	"pt": "portugués",
	"ro": "rumano",
	"ru": "ruso",
	"rw": "kinyarwanda",
	"sa": "sánscrito",
	"sah": "yakuto",
	"sd": "sindhi",
	"sk": "eslovaco",
	"sl": "esloveno",
	"smi": "sami",
	"sr": "serbio",
	"st": "sotho meridional",
	"sux": "sumerio",
	"sv": "sueco",
	"sw": "suajili",
	"syc": "siríaco clásico",
	"syr": "siríaco",
	"ta": "tamil",
	"te": "telugu",
	"th": "tailandés",
	"tlg": "tagalo",
	"tn": "setsuana",
	"tr": "turco",
	"tt": "tártaro",
	"uga": "ugarítico",
	"uk": "ucraniano",
	"ur": "urdu",
	"uz": "uzbeko",
	"ve": "venda",
	"vi": "vietnamita",
	"xdm": "edomita",
	"xeb": "eblaíta",
	"xh": "xhosa",
	"xhu": "hurrita",
	"xlu": "luvita",
	"xur": "urartiano",
	"yi": "yidis",
	"yue": "cantonés",
	"zh": "chino",
	"zu": "zulú",
	"*": "fonética",
}

_REGION_NAMES = {
	"US": "Estados Unidos",
	"GB": "Reino Unido",
	"CA": "Canadá",
	"NZ": "Nueva Zelanda",
	"KE": "Kenia",
	"CN": "China",
	"TW": "Taiwán",
	"HK": "Hong Kong",
	"IL": "Israel",
	"FI": "Finlandia",
	"ES": "España",
	"NO": "Noruega",
	"BE": "Bélgica",
	"CH": "Suiza",
	"AT": "Austria",
	"BR": "Brasil",
	"PT": "Portugal",
	"FR": "Francia",
	"DE": "Alemania",
	"IN": "India",
}

_SYSTEM_NAMES = {
	"ueb": "inglés unificado (UEB)",
	"ueb-nz": "UEB de Nueva Zelanda",
	"ebae": "inglés americano (EBAE)",
	"nabcc": "NABCC",
	"ddp": "informático danés",
	"thai": "tailandés",
	"vietnam": "vietnamita",
}

_VARIANT_NAMES = {
	"detailed": "detallada",
	"normal": "normal",
	"phonetics": "fonética",
	"no-tone": "sin tonos",
	"fallback-6dot": "con 6 puntos de reserva",
	"decomposed": "descompuesta",
	"composed": "compuesta",
	"compact": "compacta",
}

#: Tablas sin metadatos que merece la pena ofrecer (nombre en español).
_EXTRA_TABLES = {
	"es-g1.ctb": ("es", _("Español, braille literario integral (grado 1, tabla anterior)"), "literary", False, 6, "both"),
	"en-us-comp8-ext.utb": ("en", _("Inglés (Estados Unidos), braille informático de 8 puntos ampliado"), "computer", False, 8, "both"),
	"en-us-g2.ctb": ("en", _("Inglés (Estados Unidos), braille contraído (grado 2, EBAE)"), "literary", True, 6, "forward"),
	"en-GB-g2.ctb": ("en", _("Inglés (Reino Unido), braille contraído (grado 2)"), "literary", True, 6, "forward"),
	"ca-g1.ctb": ("ca", _("Catalán, braille integral (grado 1)"), "literary", False, 6, "both"),
	"Pt-Pt-g1.utb": ("pt", _("Portugués, braille integral (grado 1)"), "literary", False, 6, "both"),
	"Pt-Pt-g2.ctb": ("pt", _("Portugués, braille contraído (grado 2)"), "literary", True, 6, "forward"),
	"unicode-braille.utb": ("", _("Braille Unicode (los caracteres braille se muestran tal cual)"), "computer", False, 8, "both"),
}

#: Diccionario de división silábica por idioma (para el ajuste por sílabas).
_HYPHENATION = {
	"cs": "hyph_cs_CZ.dic",
	"da": "hyph_da_DK.dic",
	"de": "hyph_de_DE.dic",
	"en": "hyph_en_US.dic",
	"eo": "hyph_eo.dic",
	"es": "hyph_es_ES.dic",
	"fr": "hyph_fr_FR.dic",
	"hu": "hyph_hu_HU.dic",
	"it": "hyph_it_IT.dic",
	"nb": "hyph_nb_NO.dic",
	"no": "hyph_nb_NO.dic",
	"nl": "hyph_nl_NL.dic",
	"nn": "hyph_nn_NO.dic",
	"pl": "hyph_pl_PL.dic",
	"pt": "hyph_pt_PT.dic",
	"ru": "hyph_ru.dic",
	"sv": "hyph_sv_SE.dic",
}

_METADATA_EXTS = (".ctb", ".utb", ".tbl", ".dis")


def readMetadata(path: str) -> dict[str, str]:
	"""Metadatos ``#+clave: valor`` y ``#-clave: valor`` de una tabla de liblouis.

	Las claves visibles para las búsquedas (``#+``) se guardan tal cual; las
	informativas (``#-``) con el prefijo ``-`` (``-display-name``).
	"""
	meta: dict[str, str] = {}
	try:
		with open(path, encoding="utf-8", errors="replace") as f:
			for n, line in enumerate(f):
				if n > 400:
					break
				line = line.strip()
				if not line.startswith("#"):
					if line and meta:
						break
					continue
				if len(line) > 2 and line[1] in "+-" and ":" in line:
					key, _sep, value = line[2:].partition(":")
					key = key.strip().lower()
					if not key or " " in key:
						continue
					k = key if line[1] == "+" else "-" + key
					meta.setdefault(k, value.strip())
	except OSError:
		pass
	return meta


def _languageName(code: str) -> str:
	if not code:
		return _("sin idioma")
	parts = code.replace("_", "-").split("-")
	base = parts[0].lower()
	name = _LANG_NAMES.get(base, base)
	extra = []
	for p in parts[1:]:
		if p.upper() in _REGION_NAMES:
			extra.append(_REGION_NAMES[p.upper()])
		elif p == "Latn":
			extra.append(_("transliterado"))
		elif p in ("Xsux",):
			extra.append(_("cuneiforme"))
		elif p in ("Cyrl",):
			extra.append(_("cirílico"))
		elif p in ("Hans",):
			extra.append(_("simplificado"))
		elif p:
			extra.append(p)
	name = name[:1].upper() + name[1:]
	return f"{name} ({', '.join(extra)})" if extra else name


def spanishTableName(fileName: str, meta: dict[str, str]) -> str:
	"""Nombre en español a partir de los metadatos de la tabla."""
	lang = _languageName(meta.get("language", ""))
	region = meta.get("region", "")
	regionName = ""
	if region:
		code = region.replace("_", "-").split("-")[-1]
		regionName = _REGION_NAMES.get(code.upper(), "")
	if regionName and regionName not in lang:
		lang = f"{lang} ({regionName})"
	kind = meta.get("type", "")
	contraction = meta.get("contraction", "")
	grade = meta.get("grade", "")
	dotsN = meta.get("dots", "")
	parts: list[str] = []
	if kind == "computer":
		parts.append(_("braille informático"))
	elif contraction == "full":
		parts.append(_("braille contraído"))
	elif contraction == "partial":
		parts.append(_("braille parcialmente contraído"))
	elif contraction == "no" or kind == "literary":
		parts.append(_("braille integral") if contraction in ("no", "") else _("braille literario"))
	else:
		parts.append(_("braille"))
	if grade:
		parts[-1] += " " + _("(grado {grade})").format(grade=grade.replace(".", ","))
	if dotsN:
		parts[-1] += " " + _("de {n} puntos").format(n=dotsN)
	system = meta.get("system", "")
	if system:
		parts.append(_SYSTEM_NAMES.get(system, system))
	variant = meta.get("variant", "")
	if variant:
		parts.append(_("variante {v}").format(v=_VARIANT_NAMES.get(variant, variant)))
	version = meta.get("version", "")
	if version:
		parts.append(_("versión {v}").format(v=version))
	return f"{lang}, {', '.join(parts)}"


class LouisTable(Table):
	"""Tabla de liblouis (``fileName`` dentro de ``louis/tables``)."""

	source = "liblouis"

	def __init__(self, fileName: str, displayName: str, meta: dict[str, str]) -> None:
		eightDot = meta.get("dots") == "8" or meta.get("type") == "computer"
		super().__init__(fileName, displayName, eightDot)
		self.fileName = fileName
		self.meta = meta
		self.kind = meta.get("type", "literary") or "literary"
		self.contracted = meta.get("contraction") in ("full", "partial")
		self.language = meta.get("language", "").split("-")[0].lower()
		direction = meta.get("direction", "both")
		self.forInput = direction in ("both", "backward")
		self.forOutput = direction in ("both", "forward")
		self._defined: dict[str, bool] = {}
		# Los caracteres braille Unicode del texto se muestran como sus puntos.
		self.tableList = [fileName, "braille-patterns.cti"] if fileName != "unicode-braille.utb" else [fileName]
		self._broken = False

	def translate(self, text: str, cursor: int | None = None, expandAtCursor: bool = False, typeform: Sequence[int] | None = None) -> Translation:
		mode = 0
		if expandAtCursor and cursor is not None:
			mode |= liblouis.COMPBRL_AT_CURSOR
		cells, b2r, r2b, cur = liblouis.translate(self.tableList, text, typeform=typeform, cursorPos=cursor, mode=mode)
		return Translation(cells, r2b, b2r, cur)

	def backTranslate(self, cells: Sequence[int]) -> str:
		return liblouis.backTranslate(self.tableList, cells)

	def isDefined(self, ch: str) -> bool:
		if ch.isspace():
			return True
		val = self._defined.get(ch)
		if val is None:
			try:
				cells = liblouis.translate(self.tableList, ch, mode=liblouis.NO_UNDEFINED)[0]
				val = bool(cells)
			except liblouis.LouisError:
				val = True
			if len(self._defined) > 4000:
				self._defined.clear()
			self._defined[ch] = val
		return val

	def hyphenationTables(self) -> list[str] | None:
		dic = _HYPHENATION.get(self.language)
		if not dic or not os.path.isfile(os.path.join(liblouis.TABLES_DIR, dic)):
			return None
		return [self.fileName, dic]


# ---------------------------------------------------------------------- catálogo
_tables: dict[str, Table] = {}
_louisNames: list[str] = []
_loadLock = threading.RLock()
_loaded = False


def _loadLouisCatalog() -> None:
	if not liblouis.isAvailable() or not os.path.isdir(liblouis.TABLES_DIR):
		return
	entries: list[LouisTable] = []
	try:
		files = sorted(os.listdir(liblouis.TABLES_DIR), key=str.lower)
	except OSError:
		return
	for fn in files:
		if not fn.lower().endswith(_METADATA_EXTS):
			continue
		if fn in _EXTRA_TABLES:
			lang, name, kind, contracted, dotsN, direction = _EXTRA_TABLES[fn]
			meta = {"language": lang, "type": kind, "contraction": "full" if contracted else "no", "dots": str(dotsN), "direction": direction}
			entries.append(LouisTable(fn, name, meta))
			continue
		meta = readMetadata(os.path.join(liblouis.TABLES_DIR, fn))
		if "-display-name" not in meta or "language" not in meta:
			continue
		entries.append(LouisTable(fn, spanishTableName(fn, meta), meta))
	# Nombres repetidos: se añade el nombre del archivo para distinguirlos.
	counts: dict[str, int] = {}
	for t in entries:
		counts[t.displayName] = counts.get(t.displayName, 0) + 1
	for t in entries:
		if counts[t.displayName] > 1:
			t.displayName = f"{t.displayName} [{t.fileName}]"
	entries.sort(key=lambda t: (t.language != "es", unicodedata.normalize("NFD", t.displayName.lower())))
	for t in entries:
		_tables[t.name] = t
		_louisNames.append(t.name)


def _load() -> None:
	global _loaded
	if _loaded:
		return
	with _loadLock:
		if _loaded:
			return
		try:
			_loadLouisCatalog()
		except Exception:
			log.exception("No se pudo leer el catálogo de tablas de liblouis")
		for t in (Computer8Table(), Grade1SpanishTable()):
			_tables[t.name] = t
		folder = paths.brailleTablesDir()
		try:
			for fn in sorted(os.listdir(folder)):
				if fn.lower().endswith(".json"):
					try:
						with open(os.path.join(folder, fn), encoding="utf-8") as f:
							data = json.load(f)
						name = fn[:-5]
						_tables[name] = JsonTable(name, data)
					except (OSError, ValueError):
						log.exception("Tabla braille no válida: %s", fn)
		except OSError:
			pass
		_loaded = True


def reload() -> None:
	"""Vuelve a leer el catálogo (p. ej. tras añadir tablas JSON)."""
	global _loaded
	with _loadLock:
		_tables.clear()
		_louisNames.clear()
		_loaded = False
	_load()


def louisAvailable() -> bool:
	_load()
	return bool(_louisNames)


def _uiLanguage() -> str:
	try:
		from .. import i18n

		return (i18n.LANGUAGE or "es").split("_")[0].lower()
	except Exception:
		return "es"


def autoTableName(forInput: bool = False) -> str:
	"""Tabla que se usa con «Automática»: braille informático de 8 puntos del
	idioma de la interfaz (como el resto de lectores), o la propia si liblouis
	no está disponible."""
	_load()
	lang = _uiLanguage()
	if lang == "es" and "Es-Es-G0.utb" in _tables:
		return "Es-Es-G0.utb"
	best = None
	for name in _louisNames:
		t = _tables[name]
		if t.language != lang or (forInput and not t.forInput):
			continue
		score = (t.kind == "computer", t.eightDot, not t.contracted)
		if best is None or score > best[0]:
			best = (score, name)
	if best is not None:
		return best[1]
	return "es-comp8"


def resolveName(name: str, forInput: bool = False) -> str:
	if not name or name == AUTO:
		return autoTableName(forInput)
	return name


def getTable(name: str, forInput: bool = False) -> Table:
	"""Tabla por nombre (``"auto"`` resuelve la automática).

	Si la tabla no existe (p. ej. liblouis no se pudo cargar) se usa la
	alternativa propia equivalente.
	"""
	_load()
	real = resolveName(name, forInput)
	t = _tables.get(real)
	if t is not None and not getattr(t, "_broken", False):
		return t
	if t is not None:
		log.debug("Tabla %s no disponible: se usa la propia", real)
	# Alternativa propia: braille literario si la tabla pedida lo era.
	fallback = "es-g1" if (t is not None and not t.eightDot) else "es-comp8"
	return _tables.get(fallback) or Computer8Table()


def markBroken(table: Table) -> None:
	"""Marca una tabla de liblouis que ha fallado (se usará la propia) y lo dice una vez."""
	if getattr(table, "_broken", False):
		return
	table._broken = True  # type: ignore[attr-defined]
	log.warning("La tabla braille %s ha fallado; se usa la tabla propia", table.name)
	_announceBroken(table)


def _announceBroken(table: Table) -> None:
	"""Avisa por voz (en el hilo del núcleo) de que la tabla ha dejado de usarse."""
	msg = _("La tabla braille {table} ha fallado. Hasta reiniciar Tiresias se usa la tabla propia de Tiresias.").format(table=table.displayName)
	try:
		from .. import queue_handler, speech

		queue_handler.queueFunction(speech.speakMessage, msg)
	except Exception:
		log.debug("No se pudo avisar de la tabla rota", exc_info=True)


def listTables(forInput: bool | None = None, includeAuto: bool = False) -> list[tuple[str, str]]:
	"""``[(nombre, nombre visible)]``. ``forInput``: solo de entrada (True) o
	de salida (False)."""
	_load()
	out: list[tuple[str, str]] = []
	if includeAuto:
		auto = getTable(AUTO, bool(forInput))
		out.append((AUTO, _("Automática ({table})").format(table=auto.displayName)))
	for t in _tables.values():
		if forInput is True and not t.forInput:
			continue
		if forInput is False and not t.forOutput:
			continue
		out.append((t.name, t.displayName))
	return out


def cellsToUnicode(cells: Sequence[int]) -> str:
	return "".join(chr(0x2800 + (c & 0xFF)) for c in cells)


# ---------------------------------------------------------------------- traducción con opciones
#: Representaciones de los caracteres que la tabla no define.
UNDEFINED_MODES = ("hex", "allDots", "questionMark", "omit")


def _emojiMatcher():
	try:
		from ..speech import symbols

		proc = symbols.processor
		proc.ensureLoaded()
		return proc
	except Exception:
		log.debug("Sin tabla de emojis", exc_info=True)
		return None


def _clusters(text: str) -> list[tuple[int, int]]:
	"""Grupos (inicio, fin) de carácter base más marcas combinadas."""
	out: list[tuple[int, int]] = []
	i = 0
	n = len(text)
	while i < n:
		j = i + 1
		while j < n and (unicodedata.combining(text[j]) or text[j] in "‍️"):
			j += 1
		out.append((i, j))
		i = j
	return out


def _segments(table: Table, text: str, normalize: bool, emoji: bool, undefined: str) -> list[tuple[int, int, str, str]]:
	"""Divide el texto en tramos ``(inicio, fin, texto, tipo)``.

	``tipo``: ``"text"`` (se traduce y cada carácter conserva su posición),
	``"replace"`` (se traduce y todas sus celdas apuntan a ``inicio``) o
	``"undefined"`` (carácter no definido en la tabla).
	"""
	segs: list[tuple[int, int, str, str]] = []
	plainStart = 0
	proc = _emojiMatcher() if emoji else None
	emojiRe = getattr(proc, "_emojiRe", None) if proc is not None else None
	emojiSpans: dict[int, tuple[int, str]] = {}
	if emojiRe is not None:
		for m in emojiRe.finditer(text):
			emojiSpans[m.start()] = (m.end(), proc.emoji.get(m.group(0), ""))
	checkUndefined = undefined != "hex" or isinstance(table, (Computer8Table, Grade1SpanishTable))
	needNormalize = normalize and not text.isascii()

	def flush(upTo: int) -> None:
		if upTo > plainStart:
			segs.append((plainStart, upTo, text[plainStart:upTo], "text"))

	i = 0
	n = len(text)
	clusters = _clusters(text) if needNormalize else None
	ci = 0
	while i < n:
		if i in emojiSpans:
			end, name = emojiSpans[i]
			if name:
				flush(i)
				segs.append((i, end, f":{name}:", "replace"))
				i = end
				plainStart = i
				continue
		ch = text[i]
		if needNormalize:
			while ci < len(clusters) and clusters[ci][0] < i:
				ci += 1
			if ci < len(clusters) and clusters[ci][0] == i:
				a, b = clusters[ci]
				cluster = text[a:b]
				norm = unicodedata.normalize("NFKC", cluster)
				if norm != cluster:
					flush(i)
					segs.append((a, b, norm, "replace"))
					i = b
					plainStart = i
					continue
		if ch == "\xad":
			# Guion blando (#9343): no se muestra; su posición apunta a la celda siguiente.
			flush(i)
			segs.append((i, i + 1, ch, "hidden"))
			i += 1
			plainStart = i
			continue
		if 0x2800 <= ord(ch) <= 0x28FF:
			# Braille Unicode (p. ej. matemáticas en CMU): se muestra tal cual.
			flush(i)
			segs.append((i, i + 1, ch, "braille"))
			i += 1
			plainStart = i
			continue
		if checkUndefined and not ch.isascii() and not table.isDefined(ch):
			flush(i)
			segs.append((i, i + 1, ch, "undefined"))
			i += 1
			plainStart = i
			continue
		i += 1
	flush(n)
	return segs


def _undefinedCells(table: Table, ch: str, mode: str) -> list[int]:
	if mode == "omit":
		return []
	if mode == "allDots":
		return [0xFF if table.eightDot else 0x3F]
	if mode == "questionMark":
		try:
			return table.translate("?").cells or [UNKNOWN_CELL]
		except Exception:
			return [UNKNOWN_CELL]
	# «hex»: \x seguido del código del carácter (como hace liblouis).
	code = f"\\x{ord(ch):04x}"
	if isinstance(table, LouisTable):
		try:
			return table.translate(ch).cells or table.translate(code).cells
		except Exception:
			return [UNKNOWN_CELL]
	return table.translate(code).cells if isinstance(table, Computer8Table) else [UNKNOWN_CELL & 0x3F]


def translate(
	table: Table,
	text: str,
	cursor: int | None = None,
	expandAtCursor: bool = False,
	typeform: Sequence[int] | None = None,
	normalize: bool = False,
	emoji: bool = False,
	undefined: str = "hex",
) -> Translation:
	"""Traduce ``text`` con ``table`` aplicando las opciones de presentación.

	Si la tabla de liblouis falla, se marca como rota y se usa la propia.
	"""
	if not text:
		return Translation([], [], [], 0 if cursor is not None else None)
	try:
		return _translate(table, text, cursor, expandAtCursor, typeform, normalize, emoji, undefined)
	except liblouis.LouisError:
		markBroken(table)
		fallback = getTable("es-g1" if not table.eightDot else "es-comp8")
		return _translate(fallback, text, cursor, expandAtCursor, None, normalize, emoji, undefined)


def _translate(table: Table, text: str, cursor: int | None, expandAtCursor: bool, typeform, normalize: bool, emoji: bool, undefined: str) -> Translation:
	segs = _segments(table, text, normalize, emoji, undefined)
	if len(segs) == 1 and segs[0][3] == "text":
		return _translateRun(table, text, cursor, expandAtCursor, typeform)
	cells: list[int] = []
	raw2b = [0] * len(text)
	b2raw: list[int] = []
	cursorCell: int | None = None
	for start, end, segText, kind in segs:
		base = len(cells)
		if kind == "text":
			local = cursor - start if cursor is not None and start <= cursor < end else None
			tf = typeform[start:end] if typeform is not None else None
			t = _translateRun(table, segText, local, expandAtCursor, tf)
			for i in range(end - start):
				raw2b[start + i] = base + t.rawToBraille[i] if i < len(t.rawToBraille) else base + len(t.cells)
			b2raw.extend(start + r for r in t.brailleToRaw)
			cells.extend(t.cells)
			if local is not None and t.cursorPos is not None:
				cursorCell = base + t.cursorPos
		else:
			if kind == "hidden":
				segCells = []
			elif kind == "braille":
				segCells = [ord(segText) - 0x2800]
			elif kind == "undefined":
				segCells = _undefinedCells(table, segText, undefined)
			else:
				segCells = table.translate(segText).cells
			for i in range(start, end):
				raw2b[i] = base
			cells.extend(segCells)
			b2raw.extend([start] * len(segCells))
	if cursor is not None and cursorCell is None:
		cursorCell = raw2b[cursor] if cursor < len(raw2b) else len(cells)
	return Translation(cells, raw2b, b2raw, cursorCell)


def _translateRun(table: Table, text: str, cursor: int | None, expandAtCursor: bool, typeform) -> Translation:
	if isinstance(table, LouisTable):
		t = table.translate(text, cursor, expandAtCursor, typeform)
	elif expandAtCursor and cursor is not None and table.name != "es-comp8":
		t = _expandOwn(table, text, cursor)
	else:
		t = table.translate(text)
	if cursor is not None and t.cursorPos is None:
		t.cursorPos = t.rawToBraille[cursor] if cursor < len(t.rawToBraille) else len(t.cells)
	return t


def _expandOwn(table: Table, text: str, cursor: int) -> Translation:
	"""Tablas propias: la palabra del cursor se muestra en braille informático
	(sin signos de número ni de mayúscula) para leerla exacta."""
	start = cursor
	while start > 0 and not text[start - 1].isspace():
		start -= 1
	end = cursor
	while end < len(text) and not text[end].isspace():
		end += 1
	comp = getTable("es-comp8")
	parts = [(text[:start], table, 0), (text[start:end], comp, start), (text[end:], table, end)]
	cells: list[int] = []
	raw2b: list[int] = []
	b2raw: list[int] = []
	for chunk, tbl, offset in parts:
		if not chunk:
			continue
		t = tbl.translate(chunk)
		base = len(cells)
		raw2b.extend(base + p for p in t.rawToBraille)
		b2raw.extend(offset + r for r in t.brailleToRaw)
		cells.extend(t.cells)
	return Translation(cells, raw2b, b2raw)


def hyphenationPoints(table: Table, word: str) -> list[int]:
	"""Puntos de división silábica de ``word`` (vacío si no hay diccionario)."""
	if not isinstance(table, LouisTable) or len(word) < 4:
		return []
	tables = table.hyphenationTables()
	if not tables:
		return []
	try:
		return liblouis.hyphenate(tables, word)
	except Exception:
		return []
