"""Controlador para voces neuronales locales Piper (modelos VITS en ONNX).

Funciona sin conexión: el texto se convierte en fonemas IPA con eSpeak NG
(:mod:`piper_phonemizer`) y el modelo ``.onnx`` de la voz se ejecuta con
onnxruntime (código propio de inferencia, sin el paquete «piper»).

Las voces se instalan con el gestor de voces (Preferencias > Gestor de voces
neuronales Piper) en ``data/voices``; ver :mod:`piper_voices`.

Ajustes: voz, hablante (voces con varios hablantes), velocidad (y aumento de
velocidad), tono (se desplaza el audio sin cambiar la duración), entonación
(la variabilidad del modelo, ``noise_scale``) y volumen.

Órdenes admitidas: pausas, cambios de velocidad, tono y volumen, deletreo y
fonemas IPA (``PhonemeCommand``, que se pasan al modelo tal cual). El cambio
de idioma no se admite: cada voz Piper habla un solo idioma.
"""

from __future__ import annotations

import json
import os
import sys
from collections import OrderedDict

from ..i18n import _
from ..log import getLogger
from ..speech.commands import (
	BreakCommand,
	CharacterModeCommand,
	PhonemeCommand,
	PitchCommand,
	RateCommand,
	VolumeCommand,
)
from . import piper_voices
from .base import (
	AudioSynthDriver,
	InflectionSetting,
	PitchSetting,
	RateBoostSetting,
	RateSetting,
	SynthSetting,
	VoiceInfo,
	VoiceSetting,
	VolumeSetting,
)

log = getLogger("piper")

#: Velocidad máxima que se pide al modelo; por encima se acelera el audio (WSOLA).
MAX_MODEL_SPEED = 2.2
#: Pausa entre frases (ms).
SENTENCE_SILENCE_MS = 120


def speedForRate(rate: int, boost: bool = False) -> float:
	"""Velocidad relativa: 0 -> 0,5; 50 -> 1; 100 -> 2,5 (hasta 5 con aumento)."""
	rate = max(0, min(100, int(rate)))
	if rate <= 50:
		speed = 0.5 + 0.5 * rate / 50.0
	else:
		speed = 1.0 + 1.5 * (rate - 50) / 50.0
	if boost:
		speed *= 1.0 + rate / 100.0
	return speed


def pitchFactor(pitch: int) -> float:
	"""Factor de tono: 0 -> 0,71 (media octava abajo); 50 -> 1; 100 -> 1,41."""
	pitch = max(0, min(100, int(pitch)))
	return 2.0 ** ((pitch - 50) / 100.0)


def _runtimeAvailable() -> bool:
	from .. import msvc_runtime

	if "onnxruntime" not in sys.modules and not msvc_runtime.isModernEnough():
		# Con una msvcp140.dll antigua cargada, onnxruntime cerraría el proceso.
		log.warning("Las voces Piper necesitan Visual C++ 2015-2022 actualizado (msvcp140.dll 14.40 o posterior)")
		return False
	try:
		import numpy  # noqa: F401
		import onnxruntime  # noqa: F401
	except Exception:
		return False
	from .espeak import findLibrary

	return findLibrary() is not None


class _Voice:
	"""Modelo cargado de una voz."""

	def __init__(self, info: piper_voices.InstalledVoice) -> None:
		import onnxruntime as ort

		self.info = info
		with open(info.config, encoding="utf-8") as f:
			self.config = json.load(f)
		self.idMap: dict[str, list[int]] = self.config.get("phoneme_id_map") or {}
		self.espeakVoice = (self.config.get("espeak") or {}).get("voice") or "es"
		self.sampleRate = int((self.config.get("audio") or {}).get("sample_rate") or 22050)
		inf = self.config.get("inference") or {}
		self.noiseScale = float(inf.get("noise_scale", 0.667))
		self.lengthScale = float(inf.get("length_scale", 1.0))
		self.noiseW = float(inf.get("noise_w", 0.8))
		self.speakers: dict[str, int] = dict(self.config.get("speaker_id_map") or {})
		opts = ort.SessionOptions()
		opts.intra_op_num_threads = max(1, min(4, (os.cpu_count() or 2) - 1))
		opts.log_severity_level = 3
		self.session = ort.InferenceSession(info.model, sess_options=opts, providers=["CPUExecutionProvider"])
		self.inputNames = {i.name for i in self.session.get_inputs()}

	def infer(self, ids: list[int], lengthScale: float, noiseScale: float, speaker: int | None):
		import numpy as np

		feed = {
			"input": np.array([ids], dtype=np.int64),
			"input_lengths": np.array([len(ids)], dtype=np.int64),
			"scales": np.array([noiseScale, lengthScale, self.noiseW], dtype=np.float32),
		}
		if "sid" in self.inputNames:
			feed["sid"] = np.array([speaker or 0], dtype=np.int64)
		audio = self.session.run(None, feed)[0]
		return audio.reshape(-1)


class SynthDriver(AudioSynthDriver):
	name = "piper"
	description = _("Voces neuronales Piper (sin conexión)")
	supportedSettings = (
		VoiceSetting(),
		SynthSetting("speaker", _("Hablante"), kind="choice", defaultVal=None),
		RateSetting(50),
		RateBoostSetting(),
		PitchSetting(50),
		InflectionSetting(50),
		VolumeSetting(),
	)
	#: Todas las voces se convierten a esta frecuencia (así el reproductor no cambia).
	sampleRate = 22050

	@classmethod
	def check(cls) -> bool:
		return _runtimeAvailable() and bool(piper_voices.installedVoices())

	def __init__(self) -> None:
		self._installed = OrderedDict((v.key, v) for v in piper_voices.installedVoices())
		if not self._installed:
			raise RuntimeError("No hay voces Piper instaladas")
		super().__init__()
		default = next((k for k, v in self._installed.items() if v.language == "es_ES"), None)
		default = default or next((k for k, v in self._installed.items() if v.language.startswith("es")), None)
		self._settings["voice"] = default or next(iter(self._installed))
		self._settings["speaker"] = ""
		self._voice: _Voice | None = None
		self._phonemizer = None

	# ------------------------------------------------------------ ajustes
	def _getAvailable_voice(self) -> "OrderedDict[str, VoiceInfo]":
		return OrderedDict((k, VoiceInfo(k, v.displayName, v.language)) for k, v in self._installed.items())

	def _getAvailable_speaker(self) -> "OrderedDict[str, str]":
		v = self._installed.get(self._settings.get("voice") or "")
		out: OrderedDict[str, str] = OrderedDict()
		if not v or not v.speakers:
			out[""] = _("Único")
			return out
		for name in sorted(v.speakers, key=lambda n: v.speakers[n]):
			out[name] = name
		return out

	def _set_voice(self, value: str) -> None:
		if value not in self._installed:
			# Voz desinstalada: se vuelve a la primera disponible.
			self._settings["voice"] = next(iter(self._installed))
		speakers = self._getAvailable_speaker()
		if self._settings.get("speaker") not in speakers:
			self._settings["speaker"] = next(iter(speakers))

	def refreshVoices(self) -> None:
		"""Vuelve a leer las voces instaladas (tras usar el gestor de voces)."""
		installed = OrderedDict((v.key, v) for v in piper_voices.installedVoices())
		if installed:
			self._installed = installed
			self._set_voice(self._settings.get("voice") or "")

	# ------------------------------------------------------------ hilo de síntesis
	def _ensureVoice(self) -> _Voice:
		key = self._settings.get("voice") or ""
		if self._voice is None or self._voice.info.key != key:
			info = self._installed.get(key) or next(iter(self._installed.values()))
			log.info("Cargando la voz Piper %s", info.key)
			self._voice = _Voice(info)
		if self._phonemizer is None:
			from .piper_phonemizer import Phonemizer

			self._phonemizer = Phonemizer()
		return self._voice

	def _render(self, voice: _Voice, phonemes: str, rate: int, pitch: int, volume: int) -> bytes:
		import numpy as np

		from ..audio import timestretch
		from .piper_phonemizer import phonemesToIds

		ids = phonemesToIds(phonemes, voice.idMap)
		if len(ids) <= 3:
			return b""
		speed = speedForRate(rate, bool(self._settings.get("rateBoost")))
		modelSpeed = min(speed, MAX_MODEL_SPEED)
		p = pitchFactor(pitch)
		# Para subir el tono se genera más largo y se remuestrea más corto (y al revés).
		lengthScale = voice.lengthScale / modelSpeed * p
		inflection = int(self._settings.get("inflection", 50))
		noiseScale = voice.noiseScale * (inflection / 50.0)
		speaker = voice.speakers.get(self._settings.get("speaker") or "")
		audio = voice.infer(ids, lengthScale, noiseScale, speaker)
		# Remuestreo a 22 050 Hz combinado con el desplazamiento de tono.
		ratio = (self.sampleRate / voice.sampleRate) / p
		n = max(1, int(len(audio) * ratio))
		if n != len(audio):
			audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio)
		audio = audio * (max(0, min(100, volume)) / 100.0)
		pcm = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16).tobytes()
		if speed > modelSpeed:
			pcm = timestretch.stretch(pcm, self.sampleRate, speed / modelSpeed)
		return pcm

	def _silence(self, ms: int) -> bytes:
		return bytes(int(self.sampleRate * ms / 1000) * 2)

	def _synthesizeSegment(self, items, emit, isCancelled) -> None:
		voice = self._ensureVoice()
		baseRate = int(self._settings.get("rate", 50))
		basePitch = int(self._settings.get("pitch", 50))
		rate, pitch, volume = baseRate, basePitch, 100
		charMode = False
		pending: list[str] = []  # trozos de fonemas o texto marcados

		def flush() -> None:
			nonlocal pending
			text = "".join(pending)
			pending = []
			if not text.strip():
				return
			sentences = self._phonemize(voice, text)
			for i, ph in enumerate(sentences):
				if isCancelled():
					return
				pcm = self._render(voice, ph, rate, pitch, volume)
				if pcm:
					emit(pcm)
				if i < len(sentences) - 1:
					emit(self._silence(SENTENCE_SILENCE_MS))

		for it in items:
			if isCancelled():
				return
			if isinstance(it, str):
				pending.append(" ".join(it) if charMode else it)
			elif isinstance(it, CharacterModeCommand):
				charMode = bool(it.state)
			elif isinstance(it, BreakCommand):
				flush()
				emit(self._silence(int(it.time)))
			elif isinstance(it, RateCommand):
				flush()
				rate = it.applyTo(baseRate)
			elif isinstance(it, PitchCommand):
				flush()
				pitch = it.applyTo(basePitch)
			elif isinstance(it, VolumeCommand):
				flush()
				volume = it.applyTo(100)
			elif isinstance(it, PhonemeCommand):
				# Fonemas IPA directos al modelo (se marcan para no pasarlos por eSpeak).
				pending.append("\x01" + (it.ipa or "") + "\x02" if it.ipa else (it.text or ""))
		flush()

	def _phonemize(self, voice: _Voice, text: str) -> list[str]:
		"""Fonemas por frase; los tramos ``\\x01...\\x02`` ya son IPA."""
		if "\x01" not in text:
			return self._phonemizer.phonemize(text, voice.espeakVoice)
		out = ""
		rest = text
		while rest:
			start = rest.find("\x01")
			if start < 0:
				before, ipa, rest = rest, "", ""
			else:
				end = rest.find("\x02", start)
				end = end if end >= 0 else len(rest)
				before, ipa, rest = rest[:start], rest[start + 1 : end], rest[end + 1 :]
			if before.strip():
				out += " ".join(self._phonemizer.phonemize(before, voice.espeakVoice)) + " "
			if ipa:
				out += ipa + " "
		out = out.strip()
		return [out] if out else []

	def _terminateInWorker(self) -> None:
		self._voice = None
