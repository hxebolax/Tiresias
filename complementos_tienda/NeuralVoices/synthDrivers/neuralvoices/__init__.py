"""Voces neuronales de Microsoft (Speech SDK, síntesis local) para Tiresias.

Controlador de sintetizador para las voces neuronales naturales de Microsoft
que funcionan sin conexión. Las voces se instalan como complementos aparte
(``NeuralVoices-voz-...`` o, como en NVDA, ``NeuralVoices-voice-...``), cada
uno con su carpeta ``data`` y la licencia (``SynthModel.license``) o clave
(``SynthModel.key``) del modelo.

Funciones:

- Todas las voces de todos los paquetes instalados y activados.
- Velocidad, tono y volumen propios de cada voz.
- Voz preferida para cada idioma (diálogo «Voces neuronales: voz de cada
  idioma» y categoría de Opciones del complemento).
- Cambio automático de voz cuando cambia el idioma del texto, y detección
  opcional del idioma por la escritura Unicode (latina, cirílica, han...)
  con el idioma elegido para las escrituras latina, cirílica y CJK.
- Índices (marcas SSML sincronizadas con el audio), pausas, deletreo,
  fonemas y cambios de tono, velocidad y volumen dentro del texto.

Basado en el complemento NeuralVoices para NVDA de Kvark (Alexander Linkov),
con licencia GPL. El envoltorio de la API C del Speech SDK es propio
(``_speechsdk.py``, con ctypes).
"""

from __future__ import annotations

import os
import re
import threading
from collections import OrderedDict
from typing import Any, Callable

from tiresias.i18n import _
from tiresias.log import getLogger
from tiresias.speech.commands import (
	BreakCommand,
	CharacterModeCommand,
	IndexCommand,
	LangChangeCommand,
	PhonemeCommand,
	PitchCommand,
	RateCommand,
	VolumeCommand,
)
from tiresias.synth.base import (
	AudioSynthDriver,
	PitchSetting,
	RateSetting,
	SynthSetting,
	VoiceInfo,
	VoiceSetting,
	VolumeSetting,
	trimLeadingSilence,
)

from . import _speechsdk as sdk
from . import languageDetection

log = getLogger("neuralvoices")

#: Nombre del controlador (el de esta carpeta).
DRIVER_NAME = "neuralvoices"

# Escala de la prosodia SSML que corresponde a los valores 0-100 de los
# ajustes (50 es el centro de cada escala, como en el complemento original).
MIN_RATE, MAX_RATE = -100, 200
MIN_PITCH, MAX_PITCH = -100, 100
MIN_VOLUME, MAX_VOLUME = -100, 100

#: Prefijos (en minúsculas) de los complementos que traen voces.
VOICE_PACKAGE_PREFIXES = ("neuralvoices-voz", "neuralvoices-voice")

#: Audio (en bytes) que se retiene mientras quedan marcas por llegar: el SDK
#: avisa de cada marca un poco después de entregar el audio que la contiene.
MARK_LOOKBEHIND = 16000

_invalidXmlChars = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿\ud800-\udfff]")


def percentToParam(percent: int, minVal: int, maxVal: int) -> int:
	"""Convierte un valor 0-100 a la escala ``minVal``-``maxVal``."""
	return int(round(float(percent) / 100 * (maxVal - minVal) + minVal))


def xmlEscape(text: str, quote: bool = False) -> str:
	"""Escapa texto para SSML y quita los caracteres que XML no admite."""
	text = _invalidXmlChars.sub(" ", text)
	text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
	if quote:
		text = text.replace('"', "&quot;")
	return text


def baseLanguage(lang: str | None) -> str:
	"""``es-ES`` o ``es_ES`` -> ``es``."""
	return (lang or "").replace("_", "-").split("-")[0].lower()


def localeTag(lang: str | None) -> str:
	"""``es_es`` -> ``es-ES`` (forma de las voces del SDK)."""
	parts = (lang or "").replace("_", "-").split("-")
	parts[0] = parts[0].lower()
	if len(parts) > 1 and len(parts[1]) == 2:
		parts[1] = parts[1].upper()
	return "-".join(p for p in parts if p)


def languageDescription(lang: str) -> str:
	"""«Español (España) - es-ES» (como el original: descripción y código)."""
	try:
		from tiresias.i18n import languageName

		desc = languageName(lang)
	except Exception:
		desc = ""
	if desc and desc.lower() != lang.lower():
		return f"{desc[:1].upper()}{desc[1:]} - {lang}"
	return lang


def interfaceLanguage() -> str:
	"""Idioma de la interfaz de Tiresias (``es``)."""
	try:
		from tiresias import i18n

		return baseLanguage(i18n.LANGUAGE) or "es"
	except Exception:
		return "es"


def _addonUsable(addon) -> bool:
	try:
		if not addon.isEnabled:
			return False
	except Exception:
		return False
	try:
		if addon.isBlocked or not addon.isCompatible:
			return False
	except Exception:
		pass
	return True


def getVoicePackages() -> list[tuple[str, str]]:
	"""Paquetes de voces de los complementos de Tiresias: ``[(clave o licencia, carpeta de la voz)]``.

	Cada complemento cuyo identificador empieza por ``NeuralVoices-voz`` (o
	``NeuralVoices-voice``) aporta las voces de su carpeta ``data`` (cada
	carpeta con un ``Tokens.xml``), con su ``SynthModel.key`` o, si no hay
	clave, su ``SynthModel.license``.
	"""
	try:
		from tiresias import addons
	except Exception:
		return []
	out: list[tuple[str, str]] = []
	for addon in addons.getAddons():
		if not str(addon.id).lower().startswith(VOICE_PACKAGE_PREFIXES) or not _addonUsable(addon):
			continue
		data = os.path.join(addon.path, "data")
		if not os.path.isdir(data):
			continue
		key = os.path.join(addon.path, "SynthModel.key")
		license = os.path.join(addon.path, "SynthModel.license")
		if os.path.isfile(key):
			keyFile = key
		elif os.path.isfile(license):
			keyFile = license
		else:
			continue
		for root, _dirs, files in sorted(os.walk(data)):
			if "Tokens.xml" in files:
				out.append((keyFile, root))
	return out


def readModelKey(path: str) -> str:
	"""Texto de la clave o licencia; las claves (``.key``) llevan delante «Key:»."""
	with open(path, encoding="utf-8") as f:
		text = f.read()
	if path.lower().endswith(".key"):
		text = f"Key:{text}"
	return text


def _displayName(v: sdk.SDKVoice) -> str:
	"""«Álvaro (español (España))» a partir de los datos de la voz."""
	name = v.localName.strip()
	if not name:
		short = v.shortName or ""
		if v.locale and short.lower().startswith(v.locale.lower() + "-"):
			short = short[len(v.locale) + 1 :]
		if not short:
			m = re.search(r"\(([^,()]+),\s*([^()]+)\)\s*$", v.name)
			short = m.group(2) if m else v.name
		name = re.sub(r"(?i)(Multilingual)?Neural$", "", short) or short
	try:
		from tiresias.i18n import languageName

		langName = languageName(v.locale) if v.locale else ""
	except Exception:
		langName = ""
	return f"{name} ({langName})" if langName else name


class VoiceSettings:
	"""Velocidad, tono y volumen de una voz (0-100; 50 es el valor normal)."""

	__slots__ = ("rate", "pitch", "volume")

	def __init__(self, rate: int = 50, pitch: int = 50, volume: int = 50) -> None:
		self.rate = rate
		self.pitch = pitch
		self.volume = volume

	def asDict(self) -> dict[str, int]:
		return {"rate": int(self.rate), "pitch": int(self.pitch), "volume": int(self.volume)}


class _Run:
	"""Estado de una síntesis (un SSML): reparte el audio y las marcas.

	El audio se entrega al reproductor según llega; mientras quedan índices
	por llegar se retienen los últimos :data:`MARK_LOOKBEHIND` bytes, porque
	el SDK avisa de cada marca después de entregar el audio que la contiene.
	Cada índice se coloca en su posición exacta del audio.
	"""

	def __init__(self, driver: "SynthDriver", gen: int, indexes: list[int], trim: list[bool]) -> None:
		self.driver = driver
		self.gen = gen
		self.expected = list(indexes)
		self.trim = trim
		self.buf = bytearray()
		self.fedPos = 0  # bytes del SDK ya entregados (o descartados) del principio
		self.received = 0
		self.marks: list[tuple[int, list[int]]] = []
		self.lock = threading.Lock()

	def cancelled(self) -> bool:
		return self.gen != self.driver._generation

	# ------------------------------------------------ desde los hilos del SDK
	def onAudio(self, data: bytes) -> None:
		with self.lock:
			if self.cancelled():
				return
			self.buf += data
			self.received += len(data)
			self._flush(final=False)

	def onBookmark(self, name: str, pos: int) -> None:
		with self.lock:
			if self.cancelled():
				return
			try:
				index = int(name)
			except ValueError:
				return
			if index not in self.expected:
				# El SDK a veces repite una marca: ya se ha tenido en cuenta.
				return
			k = self.expected.index(index)
			fire, self.expected = self.expected[: k + 1], self.expected[k + 1 :]
			pos = max(pos, self.fedPos, self.marks[-1][0] if self.marks else 0)
			self.marks.append((pos, fire))
			self._flush(final=False)

	# ------------------------------------------------ hilo de síntesis
	def finish(self) -> None:
		"""Entrega todo lo pendiente (al terminar la síntesis)."""
		with self.lock:
			if self.cancelled():
				return
			if self.expected:
				self.marks.append((max(self.received, self.fedPos), self.expected))
				self.expected = []
			self._flush(final=True)

	def _flush(self, final: bool) -> None:
		while self.marks and self.marks[0][0] <= self.fedPos + len(self.buf):
			pos, indexes = self.marks.pop(0)
			self._feed(pos - self.fedPos)
			for i in indexes:
				self.driver._feedIndex(i, self.gen)
		if final or not self.expected:
			self._feed(len(self.buf))
		else:
			safe = self.received - MARK_LOOKBEHIND
			if safe > self.fedPos:
				self._feed(safe - self.fedPos)

	def _feed(self, n: int) -> None:
		n = max(0, min(n, len(self.buf)))
		n -= n % 2
		if n <= 0:
			return
		data = bytes(self.buf[:n])
		del self.buf[:n]
		self.fedPos += n
		if self.trim[0]:
			data, found = trimLeadingSilence(data, sdk.SAMPLE_RATE, 1)
			if not found:
				return
			self.trim[0] = False
		self.driver._player.feed(data)


class SynthDriver(AudioSynthDriver):
	name = DRIVER_NAME
	description = _("Voces neuronales de Microsoft")
	sampleRate = sdk.SAMPLE_RATE

	#: Ajustes fijos (los de idioma de las escrituras se añaden si hay varios idiomas).
	_baseSettings = (
		VoiceSetting(),
		RateSetting(50),
		PitchSetting(50),
		VolumeSetting(50),
		SynthSetting("useUnicodeLanguageDetection", _("Detectar el idioma según la escritura Unicode"), kind="boolean", defaultVal=False),
		SynthSetting("ignoreNumbersInLanguageDetection", _("Ignorar los números en la detección del idioma"), kind="boolean", defaultVal=False),
	)
	supportedSettings = _baseSettings

	@classmethod
	def check(cls) -> bool:
		return sdk.isAvailable() and bool(getVoicePackages())

	def __init__(self) -> None:
		self._synths: list[sdk.SpeechSynthesizer] = []
		self._voices: OrderedDict[str, VoiceInfo] = OrderedDict()
		try:
			for keyFile, folder in getVoicePackages():
				try:
					synth = sdk.SpeechSynthesizer(readModelKey(keyFile), [folder])
				except Exception:
					log.exception("No se pudo cargar la voz de %s", folder)
					continue
				self._synths.append(synth)
				for v in synth.voices:
					info = VoiceInfo(v.name, _displayName(v), (v.locale or "").replace("-", "_") or None)
					info.locale = v.locale or ""  # type: ignore[attr-defined]
					info.synth = synth  # type: ignore[attr-defined]
					self._voices[v.name] = info
			if not self._voices:
				raise RuntimeError("No hay voces neuronales instaladas")
		except Exception:
			self._closeSynths()
			raise
		#: Ajustes de cada voz: {id de voz: VoiceSettings}.
		self._voiceSettings: dict[str, VoiceSettings] = {}
		#: Voz preferida de cada idioma: {"es-ES" o "es": id de voz}.
		self._languageVoices: dict[str, str] = {}
		#: Idioma de cada escritura Unicode para la detección del idioma.
		self._scriptLanguages: dict[str, str] = dict(languageDetection.DEFAULT_SCRIPT_LANGUAGES)
		self._voice: VoiceInfo = self.getVoiceForLanguage(None) or next(iter(self._voices.values()))
		self._activeSynth: sdk.SpeechSynthesizer | None = None
		self._activeRun: _Run | None = None
		self._chooseDefaultScriptLanguages()
		self.supportedSettings = self._buildSupportedSettings()
		super().__init__()
		self._settings["voice"] = self._voice.id
		# El volumen va en el SSML de cada voz: el reproductor siempre al 100 %.
		self._player.volume = 1.0
		log.info("Voces neuronales cargadas: %s", ", ".join(v.displayName for v in self._voices.values()))

	# ------------------------------------------------------------ ajustes dinámicos
	def _languagesFor(self, langs: tuple[str, ...]) -> "OrderedDict[str, str]":
		"""Idiomas de ``langs`` con alguna voz instalada: {código: descripción}."""
		out: OrderedDict[str, str] = OrderedDict()
		for voice in self._voices.values():
			lang = baseLanguage(voice.locale)  # type: ignore[attr-defined]
			if lang in langs and lang not in out:
				out[lang] = languageDescription(lang)
		return out

	def _getAvailable_latinLanguage(self):
		return self._languagesFor(languageDetection.LATIN)

	def _getAvailable_cyrillicLanguage(self):
		return self._languagesFor(languageDetection.CYRILLIC)

	def _getAvailable_CJKLanguage(self):
		return self._languagesFor(languageDetection.CJK)

	def _chooseDefaultScriptLanguages(self) -> None:
		"""Idioma inicial de las escrituras latina, cirílica y han.

		Como en el original, inglés para la latina, ruso para la cirílica y
		chino para la han, pero solo si hay voz de ese idioma; para la latina
		se prefiere antes el idioma de la interfaz de Tiresias (español).
		"""
		ui = interfaceLanguage()
		for script, getter, preferred in (
			("Latin", self._getAvailable_latinLanguage, (ui, "en")),
			("Cyrillic", self._getAvailable_cyrillicLanguage, (ui, "ru")),
			("Han", self._getAvailable_CJKLanguage, (ui, "zh")),
		):
			langs = getter()
			if not langs:
				continue
			for lang in preferred:
				if lang in langs:
					self._scriptLanguages[script] = lang
					break
			else:
				self._scriptLanguages[script] = next(iter(langs))

	def _buildSupportedSettings(self) -> tuple[SynthSetting, ...]:
		settings = list(self._baseSettings)
		if len(self._getAvailable_latinLanguage()) > 1:
			settings.append(SynthSetting("latinLanguage", _("Idioma de la escritura latina"), kind="choice", defaultVal=self._scriptLanguages["Latin"]))
		if len(self._getAvailable_cyrillicLanguage()) > 1:
			settings.append(SynthSetting("cyrillicLanguage", _("Idioma de la escritura cirílica"), kind="choice", defaultVal=self._scriptLanguages["Cyrillic"]))
		if len(self._getAvailable_CJKLanguage()) > 1:
			settings.append(SynthSetting("CJKLanguage", _("Idioma de los caracteres CJK"), kind="choice", defaultVal=self._scriptLanguages["Han"]))
		return tuple(settings)

	# ------------------------------------------------------------ voces
	def _getAvailable_voice(self):
		return self._voices

	def _get_voice(self) -> str:
		return self._voice.id

	def _set_voice(self, value: str) -> None:
		voice = self._voices.get(str(value))
		if voice is not None:
			self._voice = voice
		self._settings["voice"] = self._voice.id

	@property
	def currentVoice(self) -> VoiceInfo:
		return self._voice

	def voiceSettings(self, voiceId: str) -> VoiceSettings:
		s = self._voiceSettings.get(voiceId)
		if s is None:
			s = self._voiceSettings[voiceId] = VoiceSettings()
		return s

	def getVoiceForLanguage(self, lang: str | None) -> VoiceInfo | None:
		"""Voz para el idioma ``lang`` (``es``, ``es_ES``, ``es-ES``...).

		Orden: la voz elegida para ese idioma exacto o para su idioma base en
		el diálogo de voces por idioma; una voz de ese mismo idioma y país; la
		voz actual si es del mismo idioma base; la primera voz de ese idioma.
		Sin ``lang`` se usa el idioma de la interfaz de Tiresias.
		"""
		if not lang:
			lang = interfaceLanguage()
		tag = localeTag(lang)
		base = baseLanguage(tag)
		mapping = {k.lower(): v for k, v in self._languageVoices.items()}
		for key in (tag.lower(), base):
			voiceId = mapping.get(key)
			if voiceId and voiceId in self._voices:
				return self._voices[voiceId]
		if "-" in tag:
			for voice in self._voices.values():
				if voice.locale.lower() == tag.lower():  # type: ignore[attr-defined]
					return voice
		current = getattr(self, "_voice", None)
		if current is not None and baseLanguage(current.locale) == base:  # type: ignore[attr-defined]
			return current
		for voice in self._voices.values():
			if baseLanguage(voice.locale) == base:  # type: ignore[attr-defined]
				return voice
		return None

	# --- voz de cada idioma (diálogo del complemento global)
	def getLanguageVoices(self) -> dict[str, str]:
		return dict(self._languageVoices)

	def setLanguageVoices(self, mapping: dict[str, str | None]) -> None:
		"""Cambia la voz preferida de cada idioma (``None`` o vacío = automática)."""
		for lang, voiceId in mapping.items():
			if voiceId and voiceId in self._voices:
				self._languageVoices[lang] = voiceId
			else:
				self._languageVoices.pop(lang, None)

	def languagesForMapping(self) -> list[str]:
		"""Idiomas que se pueden asignar: el de cada voz con país y sin él (``es-ES``, ``es``)."""
		langs: list[str] = []
		for voice in self._voices.values():
			loc = voice.locale  # type: ignore[attr-defined]
			for lang in (loc, baseLanguage(loc)):
				if lang and lang not in langs:
					langs.append(lang)
		return langs

	# ------------------------------------------------------------ velocidad, tono, volumen (por voz)
	def _get_rate(self) -> int:
		return self.voiceSettings(self._voice.id).rate

	def _set_rate(self, value: int) -> None:
		self.voiceSettings(self._voice.id).rate = int(value)

	def _get_pitch(self) -> int:
		return self.voiceSettings(self._voice.id).pitch

	def _set_pitch(self, value: int) -> None:
		self.voiceSettings(self._voice.id).pitch = int(value)

	def _get_volume(self) -> int:
		return self.voiceSettings(self._voice.id).volume

	def _set_volume(self, value: int) -> None:
		# No se toca el reproductor: el volumen de cada voz va en el SSML.
		self.voiceSettings(self._voice.id).volume = int(value)

	# ------------------------------------------------------------ idioma de las escrituras
	def _get_latinLanguage(self) -> str:
		return self._scriptLanguages["Latin"]

	def _set_latinLanguage(self, lang: str) -> None:
		if lang in self._getAvailable_latinLanguage():
			self._scriptLanguages["Latin"] = lang

	def _get_cyrillicLanguage(self) -> str:
		return self._scriptLanguages["Cyrillic"]

	def _set_cyrillicLanguage(self, lang: str) -> None:
		if lang in self._getAvailable_cyrillicLanguage():
			self._scriptLanguages["Cyrillic"] = lang

	def _get_CJKLanguage(self) -> str:
		return self._scriptLanguages["Han"]

	def _set_CJKLanguage(self, lang: str) -> None:
		if lang in self._getAvailable_CJKLanguage():
			self._scriptLanguages["Han"] = lang

	# ------------------------------------------------------------ guardar y cargar
	def saveableSettings(self) -> dict[str, Any]:
		values = super().saveableSettings()
		values["voices"] = {vid: s.asDict() for vid, s in self._voiceSettings.items()}
		values["languages"] = {lang: {"voice": vid} for lang, vid in self._languageVoices.items()}
		return values

	def loadSettings(self, values: dict[str, Any]) -> None:
		voices = values.get("voices")
		if isinstance(voices, dict):
			for vid, data in voices.items():
				if not isinstance(data, dict):
					continue
				s = self.voiceSettings(str(vid))
				for key in ("rate", "pitch", "volume"):
					try:
						if key in data:
							setattr(s, key, max(0, min(100, int(data[key]))))
					except (TypeError, ValueError):
						pass
		languages = values.get("languages")
		if isinstance(languages, dict):
			for lang, data in languages.items():
				voiceId = data.get("voice") if isinstance(data, dict) else data
				if isinstance(voiceId, str) and voiceId:
					self._languageVoices[str(lang)] = voiceId
		# Sin la voz guardada, la elegida para el idioma de la interfaz.
		if not values.get("voice") and self._languageVoices:
			voice = self.getVoiceForLanguage(None)
			if voice is not None:
				self._voice = voice
				self._settings["voice"] = voice.id
		# Velocidad, tono y volumen generales: los de la voz guardada (si la
		# voz ya tiene los suyos en «voices», mandan esos).
		general = dict(values)
		voiceId = str(values.get("voice") or self._voice.id)
		if isinstance(voices, dict) and isinstance(voices.get(voiceId), dict):
			for key in ("rate", "pitch", "volume"):
				if key in voices[voiceId]:
					general.pop(key, None)
		general.pop("voices", None)
		general.pop("languages", None)
		super().loadSettings(general)

	# ------------------------------------------------------------ SSML
	def _prosody(self, settings: VoiceSettings, rate: int, pitch: int, volume: int) -> str:
		r = percentToParam(rate, MIN_RATE, MAX_RATE)
		p = percentToParam(pitch, MIN_PITCH, MAX_PITCH)
		v = percentToParam(volume, MIN_VOLUME, MAX_VOLUME)
		return f'<prosody rate="{r:+d}%" pitch="{p:+d}%" volume="{v:+d}%">'

	def buildSsml(self, voice: VoiceInfo, items: list) -> tuple[str, list[int], bool]:
		"""SSML de ``items`` con la voz ``voice``: ``(ssml, índices, hay texto)``."""
		settings = self.voiceSettings(voice.id)
		locale = voice.locale or "en-US"  # type: ignore[attr-defined]
		rate, pitch, volume = settings.rate, settings.pitch, settings.volume
		parts = [
			f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{xmlEscape(locale, True)}">',
			f'<voice name="{xmlEscape(voice.id, True)}">',
			self._prosody(settings, rate, pitch, volume),
		]
		indexes: list[int] = []
		hasText = False
		charMode = False
		for item in items:
			if isinstance(item, str):
				text = xmlEscape(item)
				if not text:
					continue
				if text.strip():
					hasText = True
				if charMode and text.strip():
					parts.append(f'<say-as interpret-as="characters">{text}</say-as>')
				else:
					parts.append(text)
			elif isinstance(item, IndexCommand):
				indexes.append(int(item.index))
				parts.append(f'<mark name="{int(item.index)}"/>')
			elif isinstance(item, BreakCommand):
				parts.append(f'<break time="{max(0, int(item.time))}ms"/>')
			elif isinstance(item, CharacterModeCommand):
				charMode = bool(item.state)
			elif isinstance(item, PhonemeCommand):
				text = xmlEscape(item.text or "")
				if item.ipa:
					parts.append(f'<phoneme alphabet="ipa" ph="{xmlEscape(item.ipa, True)}">{text or " "}</phoneme>')
					hasText = True
				elif text:
					parts.append(text)
					hasText = hasText or bool(text.strip())
			elif isinstance(item, (RateCommand, PitchCommand, VolumeCommand)):
				# Cambio relativo a los ajustes de la voz: se cierra la prosodia
				# y se abre otra con los valores nuevos.
				if isinstance(item, RateCommand):
					rate = item.applyTo(settings.rate)
				elif isinstance(item, PitchCommand):
					pitch = item.applyTo(settings.pitch)
				else:
					volume = item.applyTo(settings.volume)
				parts.append("</prosody>")
				parts.append(self._prosody(settings, rate, pitch, volume))
		parts.append("</prosody></voice></speak>")
		return "".join(parts), indexes, hasText

	# ------------------------------------------------------------ síntesis
	def splitByVoice(self, sequence: list) -> list[tuple[VoiceInfo, list]]:
		"""Divide la secuencia en tramos de una misma voz según los cambios de idioma.

		Como en el original, un cambio a un idioma sin voz o a una voz del
		mismo idioma no cambia nada; ``LangChangeCommand(None)`` vuelve a la
		voz elegida. Las órdenes de prosodia y deletreo vigentes pasan al tramo
		siguiente.
		"""
		runs: list[tuple[VoiceInfo, list]] = []
		voice = self._voice
		cur: list = []
		state: dict[type, Any] = {}
		hasText = False
		for item in sequence:
			if isinstance(item, LangChangeCommand):
				newVoice = self.getVoiceForLanguage(item.lang) if item.lang else self._voice
				if newVoice is None or newVoice.locale == voice.locale:  # type: ignore[attr-defined]
					continue
				if hasText:
					runs.append((voice, cur))
					cur = list(state.values())
					hasText = False
				voice = newVoice
				continue
			if isinstance(item, str):
				if item.strip():
					hasText = True
			elif isinstance(item, (RateCommand, PitchCommand, VolumeCommand, CharacterModeCommand)):
				state[type(item)] = item
			cur.append(item)
		runs.append((voice, cur))
		return runs

	def _detectLanguages(self, sequence: list) -> list:
		if not self._settings.get("useUnicodeLanguageDetection"):
			return sequence
		return list(
			languageDetection.addDetectedLanguageCommands(
				sequence,
				baseLanguage(self._voice.locale),  # type: ignore[attr-defined]
				self._scriptLanguages,
				bool(self._settings.get("ignoreNumbersInLanguageDetection")),
			)
		)

	def _feedIndex(self, index: int, gen: int) -> None:
		self._player.feed(None, lambda i=index, g=gen: g == self._generation and self._notifyIndex(i))

	def _processSequence(self, gen: int, sequence: list) -> None:
		def isCancelled() -> bool:
			return gen != self._generation

		try:
			from tiresias.synth.base import _trimLeadingEnabled

			trimOn = _trimLeadingEnabled()
		except Exception:
			trimOn = True
		sequence = self._detectLanguages(list(sequence))
		trim = [trimOn and not (sequence and isinstance(sequence[0], BreakCommand))]
		for voice, items in self.splitByVoice(sequence):
			if isCancelled():
				return
			self._speakRun(gen, voice, items, trim, isCancelled)

	def _speakRun(self, gen: int, voice: VoiceInfo, items: list, trim: list[bool], isCancelled: Callable[[], bool]) -> None:
		ssml, indexes, hasText = self.buildSsml(voice, items)
		if not hasText:
			# Solo órdenes: los índices se cumplen cuando suene lo anterior.
			for i in indexes:
				self._feedIndex(i, gen)
			return
		synth: sdk.SpeechSynthesizer = voice.synth  # type: ignore[attr-defined]
		run = _Run(self, gen, indexes, trim)
		synth.onAudio = run.onAudio
		synth.onBookmark = run.onBookmark
		self._activeSynth = synth
		self._activeRun = run
		try:
			if isCancelled():
				return
			reason, detail = synth.speakSsml(ssml)
		finally:
			synth.onAudio = None
			synth.onBookmark = None
			self._activeSynth = None
			self._activeRun = None
		if isCancelled():
			return
		run.finish()
		if reason == sdk.ResultReason_Canceled and detail:
			raise RuntimeError(f"Las voces neuronales no pudieron sintetizar: {detail}")

	def _cancelSynthesis(self) -> None:
		# Desde el núcleo: la síntesis en curso se detiene enseguida (la base
		# ya ha cambiado la generación, así que su audio se descarta).
		synth = self._activeSynth
		if synth is not None:
			try:
				synth.stop()
			except Exception:
				log.debug("No se pudo detener la síntesis", exc_info=True)

	def synthesizeToMemory(self, items: list, isCancelled: Callable[[], bool] | None = None) -> bytes:
		"""Sintetiza ``items`` y devuelve el PCM (24 kHz, 16 bits, mono) sin reproducirlo.

		Se ejecuta en el hilo que llama: no debe usarse a la vez que la voz.
		"""
		out = bytearray()
		self._synthesizeSegment(list(items), out.extend, isCancelled or (lambda: False))
		return bytes(out)

	def _synthesizeSegment(self, items, emit, isCancelled) -> None:
		"""Síntesis directa a ``emit`` (exportar a WAV, pruebas): sin reproductor."""
		for voice, run in self.splitByVoice(self._detectLanguages(list(items))):
			if isCancelled():
				return
			ssml, _indexes, hasText = self.buildSsml(voice, run)
			if not hasText:
				continue
			synth: sdk.SpeechSynthesizer = voice.synth  # type: ignore[attr-defined]
			chunks: list[bytes] = []
			synth.onAudio = chunks.append
			synth.onBookmark = None
			try:
				reason, detail = synth.speakSsml(ssml)
			finally:
				synth.onAudio = None
			if reason == sdk.ResultReason_Canceled and detail:
				raise RuntimeError(f"Las voces neuronales no pudieron sintetizar: {detail}")
			for c in chunks:
				if isCancelled():
					return
				emit(c)

	# ------------------------------------------------------------ fin
	def _closeSynths(self) -> None:
		synths, self._synths = self._synths, []
		for s in synths:
			try:
				s.close()
			except Exception:
				log.debug("Error cerrando una voz neuronal", exc_info=True)

	def terminate(self) -> None:
		try:
			super().terminate()
		finally:
			if self._workerStarted and self._worker.is_alive():
				# El hilo de síntesis sigue dentro del SDK: liberar ahora sus
				# objetos podría romper el proceso. Se dejan (se liberan al salir).
				log.warning("El hilo de las voces neuronales no terminó a tiempo; no se liberan sus recursos")
			else:
				self._closeSynths()
