"""Procesamiento de símbolos, puntuación y emojis, por idioma.

Cada idioma tiene su tabla en ``data/symbols/<idioma>.json`` (``es`` y ``en``
se distribuyen con Tiresias) y, opcionalmente, sus emojis en
``data/symbols/emoji_<idioma>.json``. Los cambios del usuario se guardan en
``data/config/symbols_user.json`` (español) o
``data/config/symbols_user_<idioma>.json`` (resto), desde el diálogo
«Puntuación y símbolos».

:data:`processor` es la tabla en español (la del idioma de la interfaz);
:func:`getProcessor` devuelve la de cualquier idioma disponible. Así, cuando
la voz habla otro idioma o el texto cambia de idioma, los símbolos se leen
con los nombres de ese idioma en lugar de quitarlos.

También contiene las descripciones fonéticas de caracteres (alfabeto
fonético) por idioma, editables por el usuario
(``data/config/characterDescriptions_<idioma>.json``).
"""

from __future__ import annotations

import json
import os
import re
import threading
import unicodedata
from dataclasses import asdict, dataclass

from .. import paths
from ..i18n import _
from ..log import getLogger

log = getLogger("symbols")


def _jsonObject(f) -> dict:
	"""Lee un JSON cuya raíz debe ser un objeto (si no, ``ValueError``, que se registra)."""
	data = json.load(f)
	if not isinstance(data, dict):
		raise ValueError("el archivo de símbolos no contiene un objeto JSON")
	return data

LEVEL_NONE = 0
LEVEL_SOME = 100
LEVEL_MOST = 200
LEVEL_ALL = 300
LEVEL_CHAR = 1000

LEVEL_NAMES = {
	LEVEL_NONE: _("ninguno"),
	LEVEL_SOME: _("algunos"),
	LEVEL_MOST: _("la mayoría"),
	LEVEL_ALL: _("todos"),
	LEVEL_CHAR: _("carácter"),
}
SPEECH_LEVELS = [LEVEL_NONE, LEVEL_SOME, LEVEL_MOST, LEVEL_ALL]

PRESERVE_NEVER = "never"
PRESERVE_ALWAYS = "always"
PRESERVE_NOREP = "norep"

DEFAULT_LANGUAGE = "es"


@dataclass
class Symbol:
	symbol: str
	name: str
	level: int = LEVEL_ALL
	preserve: str = PRESERVE_NEVER

	def toDict(self) -> dict:
		return asdict(self)


# ------------------------------------------------------------------ alfabetos fonéticos
#: Descripciones fonéticas de fábrica por idioma.
BUILTIN_CHARACTER_DESCRIPTIONS: dict[str, dict[str, str]] = {
	# Alfabeto telefónico español.
	"es": {
		"a": "Antonio",
		"b": "Barcelona",
		"c": "Carmen",
		"d": "Dolores",
		"e": "Enrique",
		"f": "Francia",
		"g": "Gerona",
		"h": "Historia",
		"i": "Inés",
		"j": "José",
		"k": "Kilo",
		"l": "Lorenzo",
		"m": "Madrid",
		"n": "Navarra",
		"ñ": "Ñoño",
		"o": "Oviedo",
		"p": "París",
		"q": "Querido",
		"r": "Ramón",
		"s": "Sábado",
		"t": "Toledo",
		"u": "Úrsula",
		"v": "Valencia",
		"w": "Washington",
		"x": "Xilófono",
		"y": "Yegua",
		"z": "Zaragoza",
		"á": "a con tilde",
		"é": "e con tilde",
		"í": "i con tilde",
		"ó": "o con tilde",
		"ú": "u con tilde",
		"ü": "u con diéresis",
		"ç": "ce cedilla",
		"0": "cero",
		"1": "uno",
		"2": "dos",
		"3": "tres",
		"4": "cuatro",
		"5": "cinco",
		"6": "seis",
		"7": "siete",
		"8": "ocho",
		"9": "nueve",
	},
	# Alfabeto radiotelefónico internacional.
	"en": {
		"a": "Alfa",
		"b": "Bravo",
		"c": "Charlie",
		"d": "Delta",
		"e": "Echo",
		"f": "Foxtrot",
		"g": "Golf",
		"h": "Hotel",
		"i": "India",
		"j": "Juliett",
		"k": "Kilo",
		"l": "Lima",
		"m": "Mike",
		"n": "November",
		"o": "Oscar",
		"p": "Papa",
		"q": "Quebec",
		"r": "Romeo",
		"s": "Sierra",
		"t": "Tango",
		"u": "Uniform",
		"v": "Victor",
		"w": "Whiskey",
		"x": "X-ray",
		"y": "Yankee",
		"z": "Zulu",
		"0": "zero",
		"1": "one",
		"2": "two",
		"3": "three",
		"4": "four",
		"5": "five",
		"6": "six",
		"7": "seven",
		"8": "eight",
		"9": "nine",
	},
}

#: Compatibilidad: tabla española.
CHARACTER_DESCRIPTIONS = BUILTIN_CHARACTER_DESCRIPTIONS["es"]

#: Idiomas «de la misma familia» que pueden prestar sus descripciones (#13519).
_DESCRIPTION_FAMILIES = {
	"ca": "es",
	"gl": "es",
	"eu": "es",
	"ast": "es",
}

# Nombres de letras al deletrear en español (las vocales y algunas
# consonantes se pronuncian mal aisladas en ciertos sintetizadores).
LETTER_NAMES = {
	"b": "be",
	"c": "ce",
	"d": "de",
	"f": "efe",
	"g": "ge",
	"h": "hache",
	"j": "jota",
	"k": "ka",
	"l": "ele",
	"m": "eme",
	"n": "ene",
	"ñ": "eñe",
	"p": "pe",
	"q": "cu",
	"r": "erre",
	"s": "ese",
	"t": "te",
	"v": "uve",
	"w": "uve doble",
	"x": "equis",
	"y": "i griega",
	"z": "zeta",
}

_LETTER_NAMES_BY_LANG = {"es": LETTER_NAMES}


def baseLanguage(lang: str | None) -> str:
	return (lang or DEFAULT_LANGUAGE).replace("-", "_").split("_")[0].lower() or DEFAULT_LANGUAGE


def _descriptionsFile(lang: str) -> str:
	return os.path.join(paths.configDir(), f"characterDescriptions_{lang}.json")


_userDescriptions: dict[str, dict[str, str]] = {}
_descLock = threading.Lock()


def loadUserDescriptions(lang: str) -> dict[str, str]:
	"""Descripciones del usuario para ``lang`` (se leen una vez y se guardan en memoria)."""
	lang = baseLanguage(lang)
	with _descLock:
		if lang not in _userDescriptions:
			data: dict[str, str] = {}
			try:
				with open(_descriptionsFile(lang), encoding="utf-8") as f:
					raw = json.load(f)
				if isinstance(raw, dict):
					data = {str(k).lower(): str(v) for k, v in raw.items() if k}
			except FileNotFoundError:
				pass
			except (OSError, ValueError):
				log.exception("Alfabeto fonético del usuario no válido (%s)", lang)
			_userDescriptions[lang] = data
		return _userDescriptions[lang]


def getCharacterDescriptions(lang: str) -> dict[str, str]:
	"""Tabla efectiva (fábrica + usuario) de un idioma. Puede estar vacía."""
	lang = baseLanguage(lang)
	table = dict(BUILTIN_CHARACTER_DESCRIPTIONS.get(lang, {}))
	table.update(loadUserDescriptions(lang))
	# Las descripciones vacías del usuario anulan las de fábrica.
	return {k: v for k, v in table.items() if v}


def saveUserDescriptions(lang: str, table: dict[str, str]) -> None:
	"""Guarda solo lo que difiere de la tabla de fábrica."""
	lang = baseLanguage(lang)
	builtin = BUILTIN_CHARACTER_DESCRIPTIONS.get(lang, {})
	diff = {k: v for k, v in table.items() if builtin.get(k) != v}
	for k in builtin:
		if k not in table:
			diff[k] = ""
	os.makedirs(paths.configDir(), exist_ok=True)
	with open(_descriptionsFile(lang), "w", encoding="utf-8") as f:
		json.dump(diff, f, ensure_ascii=False, indent="\t", sort_keys=True)
	with _descLock:
		_userDescriptions[lang] = diff


def descriptionLanguages() -> list[str]:
	return sorted(set(BUILTIN_CHARACTER_DESCRIPTIONS) | set(availableLanguages()))


def characterDescription(ch: str, lang: str | None = None) -> str | None:
	"""Descripción fonética de ``ch`` en ``lang``.

	Si el idioma (o su dialecto) no tiene descripción para ese carácter se
	prueba con el idioma base (``es_MX`` -> ``es``) y con el idioma de la
	misma familia (``ca`` -> ``es``) (#13519).
	"""
	key = ch.lower()
	b = baseLanguage(lang)
	for candidate in (b, _DESCRIPTION_FAMILIES.get(b)):
		if not candidate:
			continue
		desc = getCharacterDescriptions(candidate).get(key)
		if desc:
			return desc
	return None


# ------------------------------------------------------------------ procesador
_EMOJI_RANGES = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF))


#: Marcas (plano de uso privado 15) que guardan el sitio de los nombres ya
#: puestos mientras se sustituyen los símbolos del resto del texto.
_NAME_MARK = 0xF0000
_NAME_MARK_RE = re.compile("[\U000F0000-\U000FFFFD]")


def _isEmojiLike(ch: str) -> bool:
	cp = ord(ch)
	return any(a <= cp <= b for a, b in _EMOJI_RANGES)


class SymbolProcessor:
	def __init__(self, language: str = DEFAULT_LANGUAGE) -> None:
		self.language = baseLanguage(language)
		self._lock = threading.Lock()
		self.symbols: dict[str, Symbol] = {}
		self.defaults: dict[str, Symbol] = {}
		self.emoji: dict[str, str] = {}
		self._symbolRe: re.Pattern | None = None
		self._emojiRe: re.Pattern | None = None
		self._repeatRe: re.Pattern | None = None
		self._loaded = False

	# ---------------------------------------------------------------- carga
	@property
	def tableFile(self) -> str:
		return os.path.join(paths.symbolsDir(), f"{self.language}.json")

	@property
	def userFile(self) -> str:
		name = "symbols_user.json" if self.language == DEFAULT_LANGUAGE else f"symbols_user_{self.language}.json"
		return os.path.join(paths.configDir(), name)

	def load(self) -> None:
		with self._lock:
			self.defaults = {}
			try:
				with open(self.tableFile, encoding="utf-8") as f:
					for item in _jsonObject(f).get("symbols", []):
						s = Symbol(item["symbol"], item["name"], int(item.get("level", 300)), item.get("preserve", "never"))
						self.defaults[s.symbol] = s
			except FileNotFoundError:
				log.warning("No hay tabla de símbolos para %s", self.language)
			except (OSError, ValueError, KeyError, TypeError, AttributeError):
				log.exception("No se pudieron cargar los símbolos (%s)", self.language)
			self.symbols = {k: Symbol(**asdict(v)) for k, v in self.defaults.items()}
			try:
				with open(self.userFile, encoding="utf-8") as f:
					user = _jsonObject(f)
				for item in user.get("symbols", []):
					s = Symbol(item["symbol"], item["name"], int(item.get("level", 300)), item.get("preserve", "never"))
					self.symbols[s.symbol] = s
				for removed in user.get("removed", []):
					self.symbols.pop(removed, None)
			except FileNotFoundError:
				pass
			except (OSError, ValueError, KeyError, TypeError, AttributeError):
				log.exception("Símbolos de usuario no válidos")
			try:
				with open(os.path.join(paths.symbolsDir(), f"emoji_{self.language}.json"), encoding="utf-8") as f:
					self.emoji = dict(_jsonObject(f).get("emoji", {}))
			except FileNotFoundError:
				self.emoji = {}
			except (OSError, ValueError, TypeError, AttributeError):
				log.exception("No se pudieron cargar los emojis")
				self.emoji = {}
			self._compile()
			self._loaded = True

	def saveUser(self) -> None:
		changed = []
		for k, s in self.symbols.items():
			d = self.defaults.get(k)
			if d is None or asdict(d) != asdict(s):
				changed.append(s.toDict())
		removed = [k for k in self.defaults if k not in self.symbols]
		os.makedirs(os.path.dirname(self.userFile), exist_ok=True)
		with open(self.userFile, "w", encoding="utf-8") as f:
			json.dump({"symbols": changed, "removed": removed}, f, ensure_ascii=False, indent="\t")
		self._compile()

	def _compile(self) -> None:
		keys = sorted((k for k in self.symbols if k), key=len, reverse=True)
		self._symbolRe = re.compile("|".join(re.escape(k) for k in keys)) if keys else None
		singles = "".join(re.escape(k) for k in self.symbols if len(k) == 1 and not k.isspace())
		# Cualquier repetición (dos o más): el mínimo lo decide ``repeatThreshold``
		# en :meth:`process` (la opción admite de 2 a 100).
		self._repeatRe = re.compile(rf"([{singles}])\1+") if singles else None
		ekeys = sorted(self.emoji, key=len, reverse=True)
		self._emojiRe = re.compile("|".join(re.escape(k) for k in ekeys)) if ekeys else None

	def replaceSymbols(self, table: dict[str, Symbol]) -> None:
		"""Sustituye la tabla (hilo del núcleo): las expresiones se compilan
		antes del cambio, para que :meth:`process` nunca use una expresión vieja
		con la tabla nueva."""
		tmp = SymbolProcessor.__new__(SymbolProcessor)
		tmp.symbols = dict(table)
		tmp.emoji = self.emoji
		tmp._compile()
		self.symbols, self._symbolRe, self._repeatRe = tmp.symbols, tmp._symbolRe, tmp._repeatRe

	def ensureLoaded(self) -> None:
		if not self._loaded:
			self.load()

	# ---------------------------------------------------------------- consulta
	def characterName(self, ch: str) -> str:
		"""Nombre con el que se anuncia un carácter al deletrear."""
		self.ensureLoaded()
		s = self.symbols.get(ch)
		if s:
			return s.name
		if ch in self.emoji:
			return self.emoji[ch]
		low = ch.lower()
		letters = _LETTER_NAMES_BY_LANG.get(self.language, {})
		if low in letters:
			return letters[low]
		if ch.isalnum():
			return ch
		try:
			return unicodedata.name(ch).lower()
		except ValueError:
			if self.language == "en":
				return f"character {ord(ch):04X}"
			return f"carácter {ord(ch):04X}"

	def characterDescription(self, ch: str) -> str | None:
		return characterDescription(ch, self.language)

	def _unknownSymbolName(self, ch: str) -> str | None:
		"""Nombre Unicode de un símbolo que no está en la tabla (#3805)."""
		cat = unicodedata.category(ch)
		if not cat.startswith("S"):
			return None
		try:
			return unicodedata.name(ch).lower()
		except ValueError:
			return None

	# ---------------------------------------------------------------- proceso
	def process(
		self,
		text: str,
		level: int,
		condenseRepeats: bool = True,
		repeatThreshold: int = 4,
		emoji: bool = True,
		unknownSymbols: bool = False,
	) -> str:
		self.ensureLoaded()
		if not text:
			return text
		if level >= LEVEL_CHAR and len(text) > 1:
			# A nivel carácter solo llegan caracteres sueltos y los nombres que
			# ya ha puesto el deletreo («dos puntos», «barra invertida», «uve
			# doble»): procesarlos otra vez leía sus espacios y sus signos
			# («dos espacio puntos»).
			return text
		# Los nombres que se ponen aquí (emojis, repeticiones, símbolos
		# desconocidos) se apartan hasta el final: si no, sus signos se leían
		# otra vez («bandera: España» decía «bandera dos puntos España»).
		names: list[str] = []
		if _NAME_MARK_RE.search(text):
			# Caracteres de uso privado del plano 15 en el propio texto: se
			# confundirían con las marcas de abajo y se leería un nombre ajeno.
			text = _NAME_MARK_RE.sub(" ", text)

		def _keep(name: str) -> str:
			names.append(name)
			return f" {chr(_NAME_MARK + len(names) - 1)} "

		if emoji:
			if self._emojiRe:
				text = self._emojiRe.sub(lambda m: _keep(self.emoji[m.group(0)]), text)
			elif self.language != DEFAULT_LANGUAGE:
				# Sin tabla de emojis en este idioma: nombre Unicode (en inglés).
				text = "".join(_keep(unicodedata.name(c, c).lower()) if _isEmojiLike(c) and c not in self.symbols else c for c in text)
		if condenseRepeats and self._repeatRe:
			def _rep(m: re.Match) -> str:
				ch = m.group(1)
				count = len(m.group(0))
				# Una repetición que es un símbolo propio («...») se lee por su nombre.
				if count < repeatThreshold or m.group(0) in self.symbols:
					return m.group(0)
				s = self.symbols.get(ch)
				name = s.name if s else ch
				return _keep(f"{count} {name}")
			text = self._repeatRe.sub(_rep, text)
		if unknownSymbols and level >= LEVEL_SOME:
			out: list[str] = []
			for c in text:
				if c in self.symbols or c.isalnum() or c.isspace() or ord(c) < 0x80:
					out.append(c)
					continue
				name = None if _NAME_MARK <= ord(c) < _NAME_MARK + len(names) else self._unknownSymbolName(c)
				out.append(_keep(name) if name else c)
			text = "".join(out)

		def _sub(m: re.Match) -> str:
			sym = m.group(0)
			s = self.symbols.get(sym)
			if s is None:
				return sym
			start, end = m.start(), m.end()
			# Separadores decimales y de miles dentro de números: se dejan
			# para que el sintetizador lea el número correctamente.
			if sym in ".,:" and level < LEVEL_CHAR:
				if start > 0 and end < len(text) and text[start - 1].isdigit() and text[end].isdigit():
					return sym
			if sym.isspace() and level < LEVEL_CHAR:
				return sym
			if level >= s.level:
				return f" {s.name} " + (sym if s.preserve == PRESERVE_ALWAYS else " ")
			if s.preserve in (PRESERVE_ALWAYS, PRESERVE_NOREP):
				return sym
			return " "

		if self._symbolRe:
			text = self._symbolRe.sub(_sub, text)
		if names:
			text = _NAME_MARK_RE.sub(lambda m: names[ord(m.group(0)) - _NAME_MARK] if ord(m.group(0)) - _NAME_MARK < len(names) else m.group(0), text)
		return re.sub(r"[ 	]{2,}", " ", text)

processor = SymbolProcessor(DEFAULT_LANGUAGE)
_processors: dict[str, SymbolProcessor] = {DEFAULT_LANGUAGE: processor}
_procLock = threading.Lock()
#: Idiomas sin tabla: así no se lee la carpeta de símbolos en cada frase de
#: una voz (o un tramo detectado) sin tabla. Se vacía en :func:`reloadAll`.
_missing: set[str] = set()


def availableLanguages() -> list[str]:
	"""Idiomas con tabla de símbolos en ``data/symbols``."""
	try:
		names = os.listdir(paths.symbolsDir())
	except OSError:
		return [DEFAULT_LANGUAGE]
	langs = sorted({n[:-5] for n in names if n.endswith(".json") and not n.startswith("emoji_")})
	return langs or [DEFAULT_LANGUAGE]


def hasTable(lang: str | None) -> bool:
	return baseLanguage(lang) in availableLanguages()


def getProcessor(lang: str | None) -> SymbolProcessor | None:
	"""Procesador del idioma (o de su idioma base). ``None`` si no hay tabla."""
	b = baseLanguage(lang)
	with _procLock:
		p = _processors.get(b)
		if p is None:
			if b in _missing:
				return None
			if not hasTable(b):
				_missing.add(b)
				return None
			p = SymbolProcessor(b)
			_processors[b] = p
	p.ensureLoaded()
	return p


def reloadAll() -> None:
	"""Vuelve a leer todas las tablas cargadas (tras editar los archivos)."""
	with _procLock:
		procs = list(_processors.values())
		_missing.clear()
	for p in procs:
		p.load()
	with _descLock:
		_userDescriptions.clear()
