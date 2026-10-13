"""Controlador para las voces OneCore de Windows 10/11 (las de Narrador)."""

from __future__ import annotations

import asyncio
import io
import re
import wave
from collections import OrderedDict

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
	PitchSetting,
	RateBoostSetting,
	RateSetting,
	SynthSetting,
	VoiceInfo,
	VoiceSetting,
	VolumeSetting,
	trimTrailingSilence,
)

log = getLogger("onecore")


def _xmlEscape(text: str) -> str:
	text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
	return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)


def _attrEscape(text: str) -> str:
	return _xmlEscape(text).replace('"', "&quot;")


#: Pausas tras la puntuación final de un bloque (ms a velocidad normal, #11876).
SENTENCE_PAUSE_MS = 320
CLAUSE_PAUSE_MS = 160
_sentenceEnd = re.compile(r"[.!?…:;]['\"»”)\]]*\s*$")
_clauseEnd = re.compile(r",['\"»”)\]]*\s*$")


def punctuationPauseMs(text: str, speed: float = 1.0) -> int:
	"""Pausa natural que corresponde al final de ``text`` (0 si no acaba en puntuación)."""
	if _sentenceEnd.search(text):
		base = SENTENCE_PAUSE_MS
	elif _clauseEnd.search(text):
		base = CLAUSE_PAUSE_MS
	else:
		return 0
	return int(base / max(0.5, speed))


class SynthDriver(AudioSynthDriver):
	name = "onecore"
	description = _("Voces OneCore de Windows")
	supportedSettings = (
		VoiceSetting(),
		RateSetting(50),
		RateBoostSetting(),
		PitchSetting(50),
		VolumeSetting(),
		SynthSetting("punctuationPause", _("Pausa natural tras la puntuación"), kind="boolean", defaultVal=True, availableInRing=False),
	)
	# Las voces OneCore generan WAV a 16 kHz o 24 kHz; se remuestrea si hace falta.
	sampleRate = 24000

	@classmethod
	def check(cls) -> bool:
		try:
			from winrt.windows.media.speechsynthesis import SpeechSynthesizer

			return len(SpeechSynthesizer.all_voices) > 0
		except Exception:
			return False

	def __init__(self) -> None:
		from winrt.windows.media.speechsynthesis import SpeechSynthesizer

		self._voices: OrderedDict[str, VoiceInfo] = OrderedDict()
		for v in SpeechSynthesizer.all_voices:
			self._voices[v.id] = VoiceInfo(v.id, f"{v.display_name} ({v.language})", v.language.replace("-", "_"))
		super().__init__()
		default = next((k for k, v in self._voices.items() if (v.language or "").startswith("es")), None)
		self._settings["voice"] = default or next(iter(self._voices), "")
		self._synth = None
		self._loop: asyncio.AbstractEventLoop | None = None
		self._voiceDirty = True

	def _getAvailable_voice(self) -> "OrderedDict[str, VoiceInfo]":
		return self._voices

	def _set_voice(self, value: str) -> None:
		self._voiceDirty = True

	def _initInWorker(self) -> None:
		self._loop = asyncio.new_event_loop()

	def _terminateInWorker(self) -> None:
		if self._loop:
			self._loop.close()

	def _prepare(self) -> None:
		from winrt.windows.media.speechsynthesis import SpeechSynthesizer

		if self._synth is None:
			self._synth = SpeechSynthesizer()
		if self._voiceDirty:
			self._voiceDirty = False
			for v in SpeechSynthesizer.all_voices:
				if v.id == self._settings.get("voice"):
					self._synth.voice = v
					break
		self._synth.options.speaking_rate = self._speed()
		self._synth.options.audio_pitch = int(self._settings.get("pitch", 50)) / 50.0
		self._synth.options.audio_volume = 1.0

	def _speed(self) -> float:
		"""Velocidad de OneCore: 0..100 -> 0,5..3,0 (hasta 6,0 con aumento de velocidad)."""
		rate = int(self._settings.get("rate", 50))
		top = 6.0 if self._settings.get("rateBoost") else 3.0
		return 0.5 + (top - 0.5) * rate / 100.0

	def _buildSsml(self, items: list) -> str:
		lang = (self._voices.get(self._settings.get("voice") or "") or VoiceInfo("", "", "es_ES")).language or "es_ES"
		out: list[str] = []
		closing: list[str] = []
		for it in items:
			if isinstance(it, str):
				out.append(_xmlEscape(it))
			elif isinstance(it, CharacterModeCommand):
				if it.state:
					out.append('<say-as interpret-as="characters">')
					closing.append("</say-as>")
				elif "</say-as>" in closing:
					closing.remove("</say-as>")
					out.append("</say-as>")
			elif isinstance(it, BreakCommand):
				out.append(f'<break time="{int(it.time)}ms"/>')
			elif isinstance(it, PitchCommand):
				# Mismo criterio que eSpeak: cada punto del ajuste es un 2 %.
				base = int(self._settings.get("pitch", 50))
				pct = int((it.applyTo(base) - base) * 2)
				out.append(f'<prosody pitch="{pct:+d}%">')
				closing.append("</prosody>")
			elif isinstance(it, VolumeCommand):
				# El volumen del usuario lo aplica el reproductor: aquí solo el cambio relativo.
				out.append(f'<prosody volume="{it.applyTo(100)}">')
				closing.append("</prosody>")
			elif isinstance(it, PhonemeCommand):
				if it.ipa:
					out.append(f'<phoneme alphabet="ipa" ph="{_attrEscape(it.ipa)}">{_xmlEscape(it.text or "")}</phoneme>')
				else:
					out.append(_xmlEscape(it.text or ""))
			elif isinstance(it, RateCommand):
				# OneCore entiende el porcentaje como cambio relativo con signo:
				# «80%» no es el 80 % de la velocidad sino un 80 % más rápido (y
				# «0%» no cambia nada). Se envía «-20%», «+10%»...
				out.append(f'<prosody rate="{max(-90, int(it.offset)):+d}%">')
				closing.append("</prosody>")
			elif isinstance(it, LangChangeCommand) and it.lang:
				out.append(f'<lang xml:lang="{it.lang.replace("_", "-")}">')
				closing.append("</lang>")
		body = "".join(out) + "".join(reversed(closing))
		return (
			'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
			f'xml:lang="{lang.replace("_", "-")}">{body}</speak>'
		)

	async def _synthAsync(self, ssml: str) -> bytes:
		from winrt.windows.storage.streams import DataReader

		stream = await self._synth.synthesize_ssml_to_stream_async(ssml)
		reader = DataReader(stream.get_input_stream_at(0))
		n = await reader.load_async(stream.size)
		buf = bytearray(n)
		reader.read_bytes(buf)
		return bytes(buf)

	def _synthesizeSegment(self, items, emit, isCancelled) -> None:
		self._prepare()
		data = self._loop.run_until_complete(self._synthAsync(self._buildSsml(items)))
		if isCancelled() or not data:
			return
		try:
			with wave.open(io.BytesIO(data), "rb") as w:
				frames = w.readframes(w.getnframes())
				rate = w.getframerate()
				channels = w.getnchannels()
		except wave.Error:
			log.exception("WAV no válido de OneCore")
			return
		if channels != 1:
			import array

			a = array.array("h")
			a.frombytes(frames)
			frames = a[0::channels].tobytes()
		if rate != self.sampleRate:
			frames = _resample(frames, rate, self.sampleRate)
		# OneCore añade mucho silencio al final de cada bloque: se recorta (#17780)
		# y se sustituye por una pausa natural si el bloque acaba en puntuación (#11876).
		frames = trimTrailingSilence(frames, self.sampleRate)
		if self._settings.get("punctuationPause", True):
			text = "".join(i for i in items if isinstance(i, str))
			pause = punctuationPauseMs(text, self._speed())
			if pause and frames:
				frames += bytes(int(self.sampleRate * pause / 1000) * 2)
		emit(frames)


def _resample(frames: bytes, src: int, dst: int) -> bytes:
	import array

	a = array.array("h")
	a.frombytes(frames)
	if not a:
		return b""
	ratio = src / dst
	n = int(len(a) / ratio)
	out = array.array("h", bytes(n * 2))
	last = len(a) - 1
	for i in range(n):
		pos = i * ratio
		j = int(pos)
		frac = pos - j
		k = j + 1 if j < last else last
		out[i] = int(a[j] * (1 - frac) + a[k] * frac)
	return out.tobytes()
