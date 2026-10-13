"""Voces SAPI 5 de 32 bits (como el ``sapi5_32`` de NVDA 2026.1).

Tiresias es de 64 bits y su controlador ``sapi5`` solo ve las voces SAPI 5 de
64 bits. Muchas voces antiguas o de terceros solo existen en 32 bits; este
controlador las usa a través del auxiliar ``tiresiasSapi32.exe`` (ver
:mod:`._sapi32host`), que sintetiza en memoria y devuelve el audio a
Tiresias. El texto se envía en el mismo XML de SAPI que usa ``sapi5``
(velocidad, tono, deletreo, pausas y cambio de idioma con ``<lang>``).

Voces duplicadas: como NVDA, este controlador muestra todas las voces de 32
bits, aunque alguna tenga también versión de 64 bits (Helena, Zira, las de
Eloquence...). Son sintetizadores distintos, cada uno con su propia lista sin
repeticiones y sus propios ajustes guardados, y el nombre del sintetizador
indica «32 bits». En la lista automática de sintetizadores va detrás de
todos los demás.
"""

from __future__ import annotations

from collections import OrderedDict

from ..i18n import _
from . import sapi5
from ._sapi32host import Host32SynthDriver, hostPath, sapi5Registry32
from .base import (
	PitchSetting,
	RateBoostSetting,
	RateSetting,
	VoiceInfo,
	VoiceSetting,
	VolumeSetting,
)


class SynthDriver(Host32SynthDriver):
	name = "sapi5_32"
	description = _("Microsoft Speech API versión 5 (32 bits)")
	supportedSettings = (VoiceSetting(), RateSetting(50), RateBoostSetting(), PitchSetting(50), VolumeSetting())
	hostMode = "sapi5"

	@classmethod
	def check(cls) -> bool:
		import os

		if not os.path.isfile(hostPath()):
			return False
		try:
			return sapi5Registry32()
		except Exception:
			return False

	def _voicesFromList(self, entries) -> OrderedDict[str, VoiceInfo]:
		voices: OrderedDict[str, VoiceInfo] = OrderedDict()
		for voiceId, name, langAttr, _extra in entries:
			if not voiceId or voiceId in voices:
				continue
			info = VoiceInfo(voiceId, name or voiceId, sapi5._langFromAttribute(langAttr))
			info.lcids = sapi5._lcidsFromAttribute(langAttr)  # type: ignore[attr-defined]
			voices[voiceId] = info
		return voices

	# El XML (tono, deletreo, pausas, <lang>...) es el de sapi5.
	_installedLcids = sapi5.SynthDriver._installedLcids
	_buildXml = sapi5.SynthDriver._buildXml

	def _buildRequest(self, items: list) -> tuple[str, int | None, int | None]:
		"""XML de SAPI y velocidad base de la voz (-10..10), que el auxiliar
		aplica con ``ISpVoice::SetRate`` (como sapi5: ver su ``_buildXml``)."""
		return self._buildXml(items), sapi5.sapiRate(int(self._settings.get("rate", 50))), None

	def _wantsWholeSegment(self) -> bool:
		# Con el aumento de velocidad se acelera el trozo entero (como sapi5).
		return bool(self._settings.get("rateBoost"))

	def _postProcess(self, data: bytes) -> bytes:
		if self._settings.get("rateBoost"):
			from ..audio import timestretch

			return timestretch.stretch(data, self.sampleRate, sapi5.boostFactor(int(self._settings.get("rate", 50))))
		return data
