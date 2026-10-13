"""Controlador para eSpeak NG (biblioteca ``espeak-ng.dll``).

La biblioteca se busca, por este orden, en:

1. ``<programa>/data/synthDrivers/espeak`` (la versión compilada lo trae
   siempre; desde el código, si existe, tiene preferencia),
2. el paquete ``espeakng_loader`` instalado con pip (ejecución desde código),
3. ``C:\\Program Files\\eSpeak NG``.
"""

from __future__ import annotations

import ctypes
import os
import re
from collections import OrderedDict
from ctypes import c_char_p, c_int, c_short, c_uint, c_void_p
from typing import Callable

from .. import paths
from ..i18n import _
from ..log import getLogger
from ..speech.commands import (
	BreakCommand,
	CharacterModeCommand,
	LangChangeCommand,
	PhonemeCommand,
	PitchCommand,
	RateCommand,
	VolumeCommand,
)
from .base import (
	AudioSynthDriver,
	InflectionSetting,
	PitchSetting,
	RateBoostSetting,
	RateSetting,
	VariantSetting,
	VoiceInfo,
	VoiceSetting,
	VolumeSetting,
)

log = getLogger("espeak")

AUDIO_OUTPUT_SYNCHRONOUS = 2
espeakCHARS_UTF8 = 1
espeakSSML = 0x10
POS_CHARACTER = 1
espeakRATE = 1
espeakVOLUME = 2
espeakPITCH = 3
espeakRANGE = 4
espeakPUNCTUATION = 5
espeakCAPITALS = 6
espeakWORDGAP = 7
EE_OK = 0

MIN_RATE = 80
MAX_RATE = 450


class espeak_VOICE(ctypes.Structure):
	_fields_ = [
		("name", c_char_p),
		("languages", c_void_p),
		("identifier", c_char_p),
		("gender", ctypes.c_ubyte),
		("age", ctypes.c_ubyte),
		("variant", ctypes.c_ubyte),
		("xx1", ctypes.c_ubyte),
		("score", c_int),
		("spare", c_void_p),
	]


SYNTH_CALLBACK = ctypes.CFUNCTYPE(c_int, ctypes.POINTER(c_short), c_int, c_void_p)


def _candidateDirs() -> list[str]:
	dirs = [paths.espeakDir()]
	if not paths.FROZEN:
		# La versión compilada no incluye el paquete: su eSpeak está en data.
		try:
			import espeakng_loader  # type: ignore

			dirs.append(os.path.dirname(espeakng_loader.__file__))
		except Exception:
			pass
	for env in ("ProgramFiles", "ProgramFiles(x86)"):
		base = os.environ.get(env)
		if base:
			dirs.append(os.path.join(base, "eSpeak NG"))
	return dirs


def findLibrary() -> tuple[str, str] | None:
	"""Devuelve (ruta de la DLL, carpeta que contiene espeak-ng-data)."""
	for d in _candidateDirs():
		for dllName in ("espeak-ng.dll", "libespeak-ng.dll"):
			dll = os.path.join(d, dllName)
			if os.path.isfile(dll) and os.path.isdir(os.path.join(d, "espeak-ng-data")):
				return dll, d
	return None


def _xmlEscape(text: str) -> str:
	text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
	# Caracteres de control no permitidos en XML.
	return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)


class SynthDriver(AudioSynthDriver):
	name = "espeak"
	description = "eSpeak NG"
	supportedSettings = (
		VoiceSetting(),
		VariantSetting(),
		RateSetting(45),
		RateBoostSetting(),
		PitchSetting(40),
		InflectionSetting(75),
		VolumeSetting(),
	)

	@classmethod
	def check(cls) -> bool:
		return findLibrary() is not None

	def __init__(self) -> None:
		found = findLibrary()
		if not found:
			raise RuntimeError("No se encontró eSpeak NG")
		self._dllPath, self._dataParent = found
		os.add_dll_directory(os.path.dirname(self._dllPath))
		self._dll = ctypes.CDLL(self._dllPath)
		d = self._dll
		d.espeak_Initialize.argtypes = [c_int, c_int, c_char_p, c_int]
		d.espeak_Initialize.restype = c_int
		d.espeak_SetSynthCallback.argtypes = [SYNTH_CALLBACK]
		d.espeak_Synth.argtypes = [c_void_p, ctypes.c_size_t, c_uint, c_int, c_uint, c_uint, ctypes.POINTER(c_uint), c_void_p]
		d.espeak_Synth.restype = c_int
		d.espeak_SetParameter.argtypes = [c_int, c_int, c_int]
		d.espeak_SetVoiceByName.argtypes = [c_char_p]
		d.espeak_SetVoiceByName.restype = c_int
		d.espeak_ListVoices.argtypes = [c_void_p]
		d.espeak_ListVoices.restype = ctypes.POINTER(ctypes.POINTER(espeak_VOICE))
		d.espeak_Cancel.restype = c_int
		d.espeak_Terminate.restype = c_int
		dataPath = self._dataParent.encode("mbcs")
		rate = d.espeak_Initialize(AUDIO_OUTPUT_SYNCHRONOUS, 300, dataPath, 0x8000)
		if rate <= 0:
			raise RuntimeError("eSpeak NG no pudo inicializarse")
		self.sampleRate = rate
		self._cancelFlag = False
		self._emit: Callable[[bytes], None] | None = None
		self._callback = SYNTH_CALLBACK(self._onSynth)
		d.espeak_SetSynthCallback(self._callback)
		self._voices = self._listVoices()
		self._variants = self._listVariants()
		self._voiceDirty = False
		self._paramsDirty = False
		super().__init__()
		self._settings["voice"] = "es" if "es" in self._voices else next(iter(self._voices), "en")
		self._settings["variant"] = "max" if "max" in self._variants else ""
		self._applyVoice()
		self._applyNumeric()

	# --------------------------------------------------------- voces
	def _listVoices(self) -> "OrderedDict[str, VoiceInfo]":
		voices: OrderedDict[str, VoiceInfo] = OrderedDict()
		#: Identificador de la voz -> archivo de eSpeak («es-419» -> «roa\es-419»).
		#: Se elige la voz por el archivo: algunos idiomas («en-gb», «fr-fr») no
		#: son nombres válidos para espeak_SetVoiceByName.
		self._identifiers: dict[str, str] = {}
		arr = self._dll.espeak_ListVoices(None)
		i = 0
		while arr and arr[i]:
			v = arr[i].contents
			ident = (v.identifier or b"").decode("utf-8", "replace")
			name = (v.name or b"").decode("utf-8", "replace")
			lang = ""
			if v.languages:
				raw = ctypes.string_at(v.languages + 1)
				lang = raw.decode("utf-8", "replace")
			if ident and not ident.startswith("mb/"):
				voiceId = lang or ident
				if voiceId not in voices:
					voices[voiceId] = VoiceInfo(voiceId, f"{name} ({voiceId})", lang)
					self._identifiers[voiceId] = ident
			i += 1
		return OrderedDict(sorted(voices.items(), key=lambda kv: kv[1].displayName.lower()))

	def _listVariants(self) -> "OrderedDict[str, str]":
		variants: OrderedDict[str, str] = OrderedDict()
		variants[""] = _("Ninguna")
		vdir = os.path.join(self._dataParent, "espeak-ng-data", "voices", "!v")
		try:
			for fn in sorted(os.listdir(vdir)):
				path = os.path.join(vdir, fn)
				if not os.path.isfile(path):
					continue
				display = fn
				try:
					with open(path, encoding="utf-8", errors="replace") as f:
						for line in f:
							if line.startswith("name "):
								display = line[5:].strip() or fn
								break
				except OSError:
					pass
				variants[fn] = display
		except OSError:
			pass
		return variants

	def _getAvailable_voice(self) -> "OrderedDict[str, VoiceInfo]":
		return self._voices

	def _getAvailable_variant(self) -> "OrderedDict[str, str]":
		return self._variants

	def _resolveVoice(self, value: str | None) -> str | None:
		"""Identificador de Tiresias de ``value``, que también puede ser el de NVDA.

		NVDA guarda el nombre del archivo de la voz («es-419», «en») o, si
		nunca se cambió la voz, el identificador completo con la barra de
		Windows («roa\\es-419»).
		"""
		if not value:
			return None
		if value in self._voices:
			return value
		low = value.strip().lower().replace("\\", "/")
		for voiceId in self._voices:
			if voiceId.lower() == low:
				return voiceId
		for voiceId, ident in self._identifiers.items():
			ident = ident.lower().replace("\\", "/")
			if low == ident or low == ident.rsplit("/", 1)[-1]:
				return voiceId
		return None

	def _voiceForLanguage(self, lang: str) -> str | None:
		"""Archivo de eSpeak de la voz de ``lang`` («en-us» -> «gmw\\en-US») o ``None``."""
		low = lang.lower()
		for voiceId, ident in self._identifiers.items():
			if voiceId.lower() == low:
				return ident
		return None

	def _voiceName(self, ident: str | None = None) -> bytes:
		"""Nombre para espeak_SetVoiceByName: el archivo de la voz (la elegida si no se indica) y la variante."""
		if ident is None:
			voice = self._settings.get("voice") or "es"
			ident = self._identifiers.get(voice, voice)
		variant = self._settings.get("variant") or ""
		name = f"{ident}+{variant}" if variant else ident
		return name.encode("utf-8")

	def _setVoiceName(self, name: bytes) -> None:
		if self._dll.espeak_SetVoiceByName(name) != EE_OK and self._dll.espeak_SetVoiceByName(self._voiceName()) != EE_OK:
			self._dll.espeak_SetVoiceByName(b"es")
		self._activeVoice = name
		self._applyNumeric()

	def _applyVoice(self) -> None:
		self._setVoiceName(self._voiceName())

	def _set_voice(self, value: str) -> None:
		resolved = self._resolveVoice(value)
		if resolved:
			self._settings["voice"] = resolved
		else:
			log.warning("Voz de eSpeak desconocida: %r", value)
		self._voiceDirty = True

	def _set_variant(self, value: str) -> None:
		self._voiceDirty = True

	# --------------------------------------------------------- parámetros
	def _rateValue(self, percent: int) -> int:
		val = MIN_RATE + (MAX_RATE - MIN_RATE) * percent / 100.0
		if self._settings.get("rateBoost"):
			val *= 3
		return int(val)

	def _applyNumeric(self) -> None:
		s = self._settings
		self._dll.espeak_SetParameter(espeakRATE, self._rateValue(s.get("rate", 45)), 0)
		self._dll.espeak_SetParameter(espeakPITCH, int(s.get("pitch", 40)), 0)
		self._dll.espeak_SetParameter(espeakRANGE, int(s.get("inflection", 75)), 0)
		self._dll.espeak_SetParameter(espeakVOLUME, 100, 0)

	def _set_rate(self, value: int) -> None:
		self._paramsDirty = True

	def _set_rateBoost(self, value: bool) -> None:
		self._paramsDirty = True

	def _set_pitch(self, value: int) -> None:
		self._paramsDirty = True

	def _set_inflection(self, value: int) -> None:
		self._paramsDirty = True

	# --------------------------------------------------------- síntesis
	def _onSynth(self, wav, numSamples, events) -> int:
		if self._cancelFlag:
			return 1
		if numSamples > 0 and self._emit:
			self._emit(ctypes.string_at(wav, numSamples * 2))
		return 0

	def _cancelSynthesis(self) -> None:
		self._cancelFlag = True

	def _buildRuns(self, items: list) -> list[tuple[str | None, str]]:
		"""Divide ``items`` en tramos ``(idioma, SSML)``; ``None`` es el idioma de la voz.

		Cada idioma se sintetiza aparte y la voz se elige con
		espeak_SetVoiceByName, no con etiquetas <voice> ni la etiqueta raíz
		<speak>: al volver de ellas eSpeak elige la voz por idioma y cambia,
		por ejemplo, el español de Latinoamérica (es-419) por el de España.
		Las etiquetas abiertas (prosodia, deletreo) se repiten en cada tramo.
		"""
		runs: list[tuple[str | None, str]] = []
		stack: list[tuple[str, str]] = []  # etiquetas abiertas: (apertura, cierre)
		lang: str | None = None
		out: list[str] = []
		hasContent = False

		def open_(tag: str, close: str) -> None:
			out.append(tag)
			stack.append((tag, close))

		for it in items:
			if isinstance(it, str):
				out.append(_xmlEscape(it))
				hasContent = hasContent or bool(it.strip())
			elif isinstance(it, CharacterModeCommand):
				if it.state:
					open_('<say-as interpret-as="characters">', "</say-as>")
				else:
					for i in range(len(stack) - 1, -1, -1):
						if stack[i][1] == "</say-as>":
							del stack[i]
							out.append("</say-as>")
							break
			elif isinstance(it, BreakCommand):
				out.append(f'<break time="{int(it.time)}ms"/>')
				hasContent = True
			elif isinstance(it, PitchCommand):
				base = int(self._settings.get("pitch", 40))
				val = it.applyTo(base)
				pct = int((val - base) * 2)
				open_(f'<prosody pitch="{pct:+d}%">', "</prosody>")
			elif isinstance(it, RateCommand):
				open_(f'<prosody rate="{100 + it.offset}%">', "</prosody>")
			elif isinstance(it, VolumeCommand):
				open_(f'<prosody volume="{100 + it.offset}%">', "</prosody>")
			elif isinstance(it, LangChangeCommand):
				new = (it.lang or "").replace("_", "-").lower() or None
				if new != lang:
					if hasContent:
						runs.append((lang, "".join(out) + "".join(c for _o, c in reversed(stack))))
					lang = new
					out = [o for o, _c in stack]
					hasContent = False
			elif isinstance(it, PhonemeCommand):
				out.append(_xmlEscape(it.text or ""))
				hasContent = hasContent or bool((it.text or "").strip())
		if hasContent:
			runs.append((lang, "".join(out) + "".join(c for _o, c in reversed(stack))))
		return runs

	def _synthesizeSegment(self, items, emit, isCancelled) -> None:
		# Los cambios de ajustes se aplican en el hilo de síntesis para no
		# llamar a eSpeak desde dos hilos a la vez.
		if self._voiceDirty:
			self._voiceDirty = False
			self._paramsDirty = False
			self._applyVoice()
		elif self._paramsDirty:
			self._paramsDirty = False
			self._applyNumeric()
		self._cancelFlag = False
		self._emit = emit
		try:
			for lang, ssml in self._buildRuns(items):
				if self._cancelFlag or isCancelled():
					break
				ident = self._voiceForLanguage(lang) if lang else None
				if lang and ident is None:
					# Sin voz propia para ese idioma: que eSpeak elija la más parecida.
					ssml = f'<voice xml:lang="{lang}">{ssml}</voice>'
				name = self._voiceName(ident)
				if name != self._activeVoice:
					self._setVoiceName(name)
				# errors="replace": un surrogate suelto (p. ej. en un fonema) no hace
				# fallar el enunciado entero (el texto ya llega saneado de la base).
				data = ssml.encode("utf-8", "replace") + b"\0"
				self._dll.espeak_Synth(
					data, len(data), 0, POS_CHARACTER, 0, espeakCHARS_UTF8 | espeakSSML, None, None
				)
				if "<voice" in ssml:
					# Al cerrar </voice> eSpeak ha podido cambiar de voz.
					self._activeVoice = None
		finally:
			self._emit = None
			if isCancelled():
				self._cancelFlag = True

	def terminate(self) -> None:
		super().terminate()
		if self._workerStarted and self._worker.is_alive():
			# El hilo de síntesis sigue dentro de eSpeak (colgado o terminando):
			# liberar la biblioteca ahora provocaría una violación de acceso que
			# cerraría Tiresias. Se deja sin liberar.
			log.warning("eSpeak sigue ocupado: no se libera la biblioteca")
			return
		try:
			self._dll.espeak_Terminate()
		except Exception:
			pass
