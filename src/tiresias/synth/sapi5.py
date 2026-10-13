"""Controlador para voces SAPI 5 (incluye adaptadores de voces naturales).

La voz se genera en un flujo de memoria y se reproduce con el reproductor
propio de Tiresias, lo que permite cortar al instante, aplicar volumen y
dividir el sonido.
"""

from __future__ import annotations

import re
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
from .base import AudioSynthDriver, PitchSetting, RateBoostSetting, RateSetting, VoiceInfo, VoiceSetting, VolumeSetting

log = getLogger("sapi5")

SVSFlagsAsync = 1
#: SVSFPurgeBeforeSpeak: descarta lo que SAPI tenga pendiente (al callar).
_PURGE_BEFORE_SPEAK = 2
SVSFIsXML = 8
SAFT22kHz16BitMono = 22
_LCID_TO_LANG = {
	0x0C0A: "es_ES",
	0x040A: "es_ES",
	0x080A: "es_MX",
	0x2C0A: "es_AR",
	0x240A: "es_CO",
	0x340A: "es_CL",
	0x280A: "es_PE",
	0x200A: "es_VE",
	0x540A: "es_US",
	0x0409: "en_US",
	0x0809: "en_GB",
	0x0407: "de_DE",
	0x040C: "fr_FR",
	0x0C0C: "fr_CA",
	0x0410: "it_IT",
	0x0416: "pt_BR",
	0x0816: "pt_PT",
	0x040B: "fi_FI",
	0x0411: "ja_JP",
	0x0412: "ko_KR",
	0x0804: "zh_CN",
	0x0403: "ca_ES",
	0x042D: "eu_ES",
	0x0456: "gl_ES",
}


def _xmlEscape(text: str) -> str:
	text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
	return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)


def _localeToLcid(lang: str) -> int | None:
	"""LCID de Windows de un código de idioma (``es_419`` -> 0x580A); ``None`` si no lo hay."""
	try:
		import ctypes

		lcid = ctypes.windll.kernel32.LocaleNameToLCID(lang.replace("_", "-"), 0)
	except Exception:
		return None
	# 0 = desconocido; 0x1000 = LOCALE_CUSTOM_UNSPECIFIED (nombre válido sin LCID propio).
	return lcid if lcid and lcid != 0x1000 else None


def _lcidToLocale(lcid: int) -> str | None:
	"""Código de idioma (``es_MX``) de un LCID, con la tabla propia o con Windows."""
	if lcid in _LCID_TO_LANG:
		return _LCID_TO_LANG[lcid]
	try:
		import ctypes

		buf = ctypes.create_unicode_buffer(85)
		if ctypes.windll.kernel32.LCIDToLocaleName(lcid, buf, 85, 0) and buf.value:
			return buf.value.replace("-", "_")
	except Exception:
		pass
	return None


def _lcidForLang(lang: str, installed: "list[int] | None" = None, current: str | None = None) -> int | None:
	"""LCID para la etiqueta ``<lang>`` de SAPI (que cambia a una voz de ese idioma).

	``installed`` son los LCID de las voces instaladas y ``current`` el idioma
	de la voz elegida. Si el dialecto pedido no tiene voz y el idioma base es
	el de la voz actual, no se cambia de voz (``None``): así un texto «es-419»
	no pasa una voz mexicana a una de España. Sin ``installed`` se usa la
	tabla propia (comportamiento anterior).
	"""
	lang = (lang or "").replace("-", "_")
	if not lang:
		return None
	base = lang.split("_")[0].lower()
	if installed is not None:
		exact = _localeToLcid(lang)
		if exact is not None and exact in installed:
			return exact
		for lcid in installed:
			loc = _lcidToLocale(lcid) or ""
			if loc.lower() == lang.lower():
				return lcid
		if current and current.replace("-", "_").split("_")[0].lower() == base:
			return None
		for lcid in installed:
			if (_lcidToLocale(lcid) or "").split("_")[0].lower() == base:
				return lcid
		return None
	for lcid, code in _LCID_TO_LANG.items():
		if code.lower() == lang.lower():
			return lcid
	for lcid, code in _LCID_TO_LANG.items():
		if code.split("_")[0].lower() == base:
			return lcid
	return None


def sapiRate(rate: int) -> int:
	"""Velocidad de Tiresias (0..100) en la escala de SAPI 5 (-10..10)."""
	return round((max(0, min(100, int(rate))) - 50) / 5)


def boostFactor(rate: int) -> float:
	"""Aceleración extra con el aumento de velocidad: de 1 (velocidad 0) a 3 (velocidad 100)."""
	return 1.0 + 2.0 * max(0, min(100, int(rate))) / 100.0


def _lcidsFromAttribute(attr: str) -> list[int]:
	out: list[int] = []
	for part in (attr or "").split(";"):
		try:
			out.append(int(part.strip(), 16))
		except ValueError:
			continue
	return out


def _langFromAttribute(attr: str) -> str | None:
	"""Idioma de una voz a partir de su atributo «Language» (LCID en hexadecimal).

	Las voces cuyo LCID no está en la tabla propia (ruso, polaco, neerlandés...)
	también tienen idioma: si no, Tiresias las trataba como si hablaran el
	idioma de la interfaz (símbolos, números y avisos de idioma equivocados).
	"""
	lcids = _lcidsFromAttribute(attr) if isinstance(attr, str) else []
	if not lcids:
		return None
	return _lcidToLocale(lcids[0])


class SynthDriver(AudioSynthDriver):
	name = "sapi5"
	description = _("Microsoft Speech API versión 5 (SAPI 5)")
	supportedSettings = (VoiceSetting(), RateSetting(50), RateBoostSetting(), PitchSetting(50), VolumeSetting())
	sampleRate = 22050

	@classmethod
	def check(cls) -> bool:
		try:
			import comtypes.client

			v = comtypes.client.CreateObject("SAPI.SpVoice")
			return v.GetVoices().Count > 0
		except Exception:
			return False

	def __init__(self) -> None:
		import comtypes.client

		probe = comtypes.client.CreateObject("SAPI.SpVoice")
		self._voices = self._listVoices(probe)
		del probe
		super().__init__()
		default = next((k for k, v in self._voices.items() if (v.language or "").startswith("es")), None)
		self._settings["voice"] = default or next(iter(self._voices), "")
		self._voice = None
		self._stream = None
		self._voiceDirty = True
		self._ensureWorker()

	@staticmethod
	def _listVoices(spVoice) -> "OrderedDict[str, VoiceInfo]":
		voices: OrderedDict[str, VoiceInfo] = OrderedDict()
		tokens = spVoice.GetVoices()
		for i in range(tokens.Count):
			t = tokens.Item(i)
			try:
				attr = t.GetAttribute("Language")
			except Exception:
				attr = ""
			info = VoiceInfo(t.Id, t.GetDescription(), _langFromAttribute(attr))
			info.lcids = _lcidsFromAttribute(attr)  # type: ignore[attr-defined]
			voices[t.Id] = info
		return voices

	def _installedLcids(self) -> list[int]:
		out: list[int] = []
		for v in self._voices.values():
			for lcid in getattr(v, "lcids", ()):
				if lcid not in out:
					out.append(lcid)
		return out

	def _getAvailable_voice(self) -> "OrderedDict[str, VoiceInfo]":
		return self._voices

	def _set_voice(self, value: str) -> None:
		self._voiceDirty = True

	# ------------------------------------------------------------ hilo
	def _initInWorker(self) -> None:
		import comtypes

		comtypes.CoInitialize()

	def _terminateInWorker(self) -> None:
		self._voice = None
		self._stream = None
		import comtypes

		comtypes.CoUninitialize()

	def _prepare(self) -> None:
		import comtypes.client

		if self._voice is None:
			self._voice = comtypes.client.CreateObject("SAPI.SpVoice")
			self._fmt = comtypes.client.CreateObject("SAPI.SpAudioFormat")
			self._fmt.Type = SAFT22kHz16BitMono
		if self._voiceDirty:
			self._voiceDirty = False
			wanted = self._settings.get("voice")
			tokens = self._voice.GetVoices()
			for i in range(tokens.Count):
				t = tokens.Item(i)
				if t.Id == wanted:
					try:
						self._voice.Voice = t
					except Exception:
						log.exception("No se pudo seleccionar la voz %s", wanted)
					break

	def _buildXml(self, items: list) -> str:
		"""XML de SAPI sin la velocidad base (esa va en la voz: :func:`sapiRate`).

		Hay motores que no atienden ``<rate>`` en el XML (Eloquence) y otros
		que suman la velocidad de la voz y la del XML (las de Microsoft): por
		eso un cambio de velocidad dentro del texto se expresa como diferencia
		respecto de la velocidad base.
		"""
		rate = int(self._settings.get("rate", 50))
		pitch = int(self._settings.get("pitch", 50))
		base = sapiRate(rate)
		out: list[str] = []
		closing: list[str] = []
		for it in items:
			if isinstance(it, str):
				out.append(_xmlEscape(it))
			elif isinstance(it, CharacterModeCommand):
				if it.state:
					out.append("<spell>")
					closing.append("</spell>")
				elif "</spell>" in closing:
					closing.remove("</spell>")
					out.append("</spell>")
			elif isinstance(it, BreakCommand):
				out.append(f'<silence msec="{int(it.time)}"/>')
			elif isinstance(it, PitchCommand):
				p = it.applyTo(pitch)
				out.append(f'<pitch absmiddle="{round((p - 50) / 5)}">')
				closing.append("</pitch>")
			elif isinstance(it, RateCommand):
				out.append(f'<rate absspeed="{sapiRate(it.applyTo(rate)) - base}">')
				closing.append("</rate>")
			elif isinstance(it, VolumeCommand):
				# El volumen del usuario lo aplica el reproductor: aquí solo el cambio relativo.
				out.append(f'<volume level="{it.applyTo(100)}">')
				closing.append("</volume>")
			elif isinstance(it, LangChangeCommand):
				voices = getattr(self, "_voices", None) or {}
				cur = voices.get(self._settings.get("voice") or "")
				lcid = _lcidForLang(it.lang or "", self._installedLcids() if voices else None, cur.language if cur else None)
				if lcid is not None:
					out.append(f'<lang langid="{lcid:x}">')
					closing.append("</lang>")
			elif isinstance(it, PhonemeCommand):
				# SAPI 5 no acepta IPA: se dice el texto alternativo.
				out.append(_xmlEscape(it.text or ""))
		body = "".join(out) + "".join(reversed(closing))
		return f'<pitch absmiddle="{round((pitch - 50) / 5)}">{body}</pitch>'

	def _synthesizeSegment(self, items, emit, isCancelled) -> None:
		import comtypes.client

		self._prepare()
		stream = comtypes.client.CreateObject("SAPI.SpMemoryStream")
		stream.Format = self._fmt
		self._voice.AudioOutputStream = stream
		# Velocidad base en la voz (ISpVoice::SetRate), no en el XML (ver _buildXml).
		self._voice.Rate = sapiRate(int(self._settings.get("rate", 50)))
		# Asíncrono y esperando a trozos: al callar (Control) se purga lo que
		# queda en lugar de esperar a que la voz termine de generar el trozo
		# entero (con voces naturales, cientos de milisegundos o más).
		self._voice.Speak(self._buildXml(items), SVSFlagsAsync | SVSFIsXML)
		while not self._voice.WaitUntilDone(20):
			if isCancelled():
				try:
					self._voice.Speak("", SVSFlagsAsync | _PURGE_BEFORE_SPEAK)
					self._voice.WaitUntilDone(1000)
				except Exception:
					log.debug("No se pudo purgar SAPI", exc_info=True)
				return
		if isCancelled():
			return
		data = stream.GetData()
		if data:
			data = bytes(data)
			if self._settings.get("rateBoost"):
				# Aumento de velocidad: SAPI ya habla a su velocidad y se acelera
				# el audio sin cambiar el tono.
				from ..audio import timestretch

				data = timestretch.stretch(data, self.sampleRate, boostFactor(int(self._settings.get("rate", 50))))
			emit(data)
