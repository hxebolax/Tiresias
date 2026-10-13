"""Diccionarios de pronunciación.

Hay cuatro diccionarios que se aplican en este orden:

1. Temporal (solo hasta que se cierra Tiresias).
2. Del perfil de configuración activo
   (``data/speechDicts/profiles/<perfil>.json``).
3. De voz (``data/speechDicts/voices/<sintetizador>-<voz>.json``). Se
   recarga solo cuando cambia la voz, se cambie desde donde se cambie
   (opciones, anillo de ajustes, complementos...).
4. Por defecto (``data/speechDicts/default.json``).

Cada entrada tiene ``pattern``, ``replacement``, ``caseSensitive``,
``type``, ``comment`` y ``enabled``. Tipos (#19506):

- ``anywhere``: en cualquier lugar;
- ``word``: palabra completa;
- ``startOfWord``: al principio de una palabra;
- ``endOfWord``: al final de una palabra;
- ``partOfWord``: solo dentro de una palabra (nunca como palabra suelta);
- ``regex``: expresión regular.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import asdict, dataclass, field

from .. import paths
from ..log import getLogger

log = getLogger("speechDict")

TYPE_ANYWHERE = "anywhere"
TYPE_WORD = "word"
TYPE_START = "startOfWord"
TYPE_END = "endOfWord"
TYPE_PART = "partOfWord"
TYPE_REGEX = "regex"
TYPES = (TYPE_ANYWHERE, TYPE_WORD, TYPE_START, TYPE_END, TYPE_PART, TYPE_REGEX)


def buildPattern(pattern: str, kind: str) -> str:
	"""Expresión regular equivalente a un patrón literal de cierto tipo."""
	if kind == TYPE_REGEX:
		return pattern
	lit = re.escape(pattern)
	if kind == TYPE_WORD:
		return rf"(?<!\w){lit}(?!\w)"
	if kind == TYPE_START:
		return rf"(?<!\w){lit}"
	if kind == TYPE_END:
		return rf"{lit}(?!\w)"
	if kind == TYPE_PART:
		return rf"(?:(?<=\w){lit}|{lit}(?=\w))"
	return lit


@dataclass
class Entry:
	pattern: str
	replacement: str
	caseSensitive: bool = False
	type: str = TYPE_ANYWHERE
	comment: str = ""
	enabled: bool = True
	_compiled: re.Pattern | None = field(default=None, repr=False, compare=False)

	def compile(self) -> re.Pattern | None:
		flags = 0 if self.caseSensitive else re.IGNORECASE
		try:
			self._compiled = re.compile(buildPattern(self.pattern, self.type if self.type in TYPES else TYPE_ANYWHERE), flags)
		except re.error:
			log.warning("Patrón de diccionario no válido: %r", self.pattern)
			self._compiled = None
		return self._compiled

	def apply(self, text: str) -> str:
		if not self.enabled:
			return text
		rx = self._compiled or self.compile()
		if not rx:
			return text
		try:
			if self.type == TYPE_REGEX:
				return rx.sub(self.replacement, text)
			return rx.sub(lambda m: self.replacement, text)
		except (re.error, IndexError):
			return text

	def toDict(self) -> dict:
		d = asdict(self)
		d.pop("_compiled", None)
		return d

	def copy(self) -> "Entry":
		return Entry(self.pattern, self.replacement, self.caseSensitive, self.type, self.comment, self.enabled)


def entryFromDict(item: dict) -> Entry:
	return Entry(
		str(item.get("pattern", "")),
		str(item.get("replacement", "")),
		bool(item.get("caseSensitive", False)),
		item.get("type", TYPE_ANYWHERE) if item.get("type") in TYPES else TYPE_ANYWHERE,
		str(item.get("comment", "")),
		bool(item.get("enabled", True)),
	)


class SpeechDict(list):
	def __init__(self, fileName: str | None = None) -> None:
		super().__init__()
		self.fileName = fileName

	def load(self, fileName: str | None = None) -> None:
		if fileName:
			self.fileName = fileName
		self.clear()
		if not self.fileName or not os.path.isfile(self.fileName):
			return
		try:
			self.extend(readEntries(self.fileName))
		except (OSError, ValueError):
			log.exception("No se pudo cargar el diccionario %s", self.fileName)

	def save(self) -> None:
		if not self.fileName:
			return
		writeEntries(self.fileName, list(self))

	def apply(self, text: str) -> str:
		for e in self:
			text = e.apply(text)
		return text


def readEntries(fileName: str) -> list[Entry]:
	"""Lee las entradas de un archivo JSON de diccionario (lanza OSError/ValueError)."""
	with open(fileName, encoding="utf-8") as f:
		data = json.load(f)
	if not isinstance(data, dict):
		raise ValueError("Formato de diccionario no válido")
	out: list[Entry] = []
	for item in data.get("entries", []):
		if not isinstance(item, dict):
			continue
		e = entryFromDict(item)
		if e.pattern:
			e.compile()
			out.append(e)
	return out


def writeEntries(fileName: str, entries: list[Entry]) -> None:
	os.makedirs(os.path.dirname(fileName), exist_ok=True)
	tmp = fileName + ".tmp"
	with open(tmp, "w", encoding="utf-8") as f:
		json.dump({"entries": [e.toDict() for e in entries]}, f, ensure_ascii=False, indent="\t")
	os.replace(tmp, fileName)


defaultDict = SpeechDict()
voiceDict = SpeechDict()
tempDict = SpeechDict()
profileDict = SpeechDict()

_lock = threading.Lock()
#: (sintetizador, voz) del diccionario de voz cargado.
_voiceKey: tuple[str, str] | None = None
#: Perfil del diccionario de perfil cargado ("" = configuración base).
_profileKey: str | None = None


def _safeName(s: str) -> str:
	return re.sub(r"[^\w.-]+", "_", s)[:120]


def loadDefault() -> None:
	defaultDict.load(os.path.join(paths.speechDictsDir(), "default.json"))


def voiceDictFile(synthName: str, voiceId: str | None) -> str:
	name = f"{_safeName(synthName)}-{_safeName(voiceId or 'default')}.json"
	return os.path.join(paths.speechDictsDir(), "voices", name)


def loadVoiceDict(synthName: str, voiceId: str | None) -> None:
	global _voiceKey
	with _lock:
		voiceDict.load(voiceDictFile(synthName, voiceId))
		_voiceKey = (synthName, str(voiceId or ""))


def ensureVoiceDict() -> None:
	"""Recarga el diccionario de voz si la voz ha cambiado desde la última vez."""
	try:
		from .. import synth

		s = synth.getSynth()
		if s is None:
			return
		key = (s.name, str(s.getSetting("voice") or ""))
	except Exception:
		return
	if key != _voiceKey:
		loadVoiceDict(key[0], key[1] or None)


def profileDictFile(profileName: str) -> str:
	return os.path.join(paths.speechDictsDir(), "profiles", _safeName(profileName) + ".json")


def activeProfileName() -> str | None:
	try:
		from ..config import conf

		return conf.activeProfileName
	except Exception:
		return None


def ensureProfileDict() -> None:
	"""Carga el diccionario del perfil activo (vacío si no hay perfil activo)."""
	global _profileKey
	name = activeProfileName() or ""
	if name == _profileKey:
		return
	with _lock:
		_profileKey = name
		if name:
			profileDict.load(profileDictFile(name))
		else:
			profileDict.clear()
			profileDict.fileName = None


def saveProfileDict(profileName: str, entries: list[Entry]) -> None:
	"""Guarda el diccionario de ``profileName``, esté activo o no (lanza ``OSError``).

	Si ese perfil es el del diccionario cargado ahora, se actualiza también en
	memoria; si no, se leerá del archivo cuando el perfil se active.
	"""
	if not profileName:
		raise OSError("No hay ningún perfil al que pertenezca el diccionario")
	entries = list(entries)
	writeEntries(profileDictFile(profileName), entries)
	with _lock:
		if _profileKey == profileName:
			profileDict[:] = entries
			profileDict.fileName = profileDictFile(profileName)


def processText(text: str) -> str:
	ensureVoiceDict()
	ensureProfileDict()
	if tempDict:
		text = tempDict.apply(text)
	if profileDict:
		text = profileDict.apply(text)
	if voiceDict:
		text = voiceDict.apply(text)
	if defaultDict:
		text = defaultDict.apply(text)
	return text
