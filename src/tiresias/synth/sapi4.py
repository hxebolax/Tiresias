"""Voces SAPI 4 (Microsoft Speech API versión 4), como el ``sapi4_32`` de NVDA 2026.1.

SAPI 4 solo existe en 32 bits: los motores se cargan en el auxiliar
``tiresiasSapi32.exe`` (ver :mod:`._sapi32host`), que les da un destino de
audio propio (``IAudio``/``IAudioDest``) en memoria, convierte lo que generan
a 22050 Hz, 16 bits, mono y lo devuelve a Tiresias.

Si el equipo no tiene SAPI 4 o no tiene ningún motor SAPI 4 registrado,
:meth:`SynthDriver.check` devuelve ``False`` y el sintetizador no aparece.
"""

from __future__ import annotations

import os
from collections import OrderedDict

from ..i18n import _
from ..speech.commands import (
	BreakCommand,
	CharacterModeCommand,
	PhonemeCommand,
	PitchCommand,
	RateCommand,
	VolumeCommand,
)
from ._sapi32host import Host32SynthDriver, hostPath, probeVoices, sapi4Registry
from .base import PitchSetting, RateSetting, VoiceInfo, VoiceSetting, VolumeSetting
from .sapi5 import _lcidToLocale


def parseRanges(info: str) -> dict[str, tuple[int, ...]]:
	"""``"rate=10,300,150;pitch=50,200,100;volume=0,65535;"`` -> ``{"rate": (10, 300, 150), ...}``."""
	out: dict[str, tuple[int, ...]] = {}
	for part in (info or "").split(";"):
		if "=" not in part:
			continue
		key, _sep, values = part.partition("=")
		try:
			nums = tuple(int(v) for v in values.split(","))
		except ValueError:
			continue
		if len(nums) >= 2 and nums[1] > nums[0]:
			out[key.strip()] = nums
	return out


def percentToParam(percent: int, low: int, high: int) -> int:
	percent = max(0, min(100, int(percent)))
	return low + round(percent * (high - low) / 100)


class SynthDriver(Host32SynthDriver):
	name = "sapi4"
	description = _("Microsoft Speech API versión 4")
	supportedSettings = (VoiceSetting(), RateSetting(50), PitchSetting(50), VolumeSetting())
	hostMode = "sapi4"

	@classmethod
	def check(cls) -> bool:
		if not os.path.isfile(hostPath()):
			return False
		try:
			registry = sapi4Registry()
		except Exception:
			return False
		if registry is False:
			return False
		return bool(probeVoices("sapi4"))

	def __init__(self) -> None:
		#: Márgenes de la voz actual: ``rate``/``pitch`` (mín., máx., por omisión) y ``volume`` (mín., máx.).
		self._ranges: dict[str, tuple[int, ...]] = {}
		super().__init__()

	def _voicesFromList(self, entries) -> OrderedDict[str, VoiceInfo]:
		voices: OrderedDict[str, VoiceInfo] = OrderedDict()
		for modeId, name, langHex, _features in entries:
			if not modeId or modeId in voices:
				continue
			try:
				lang = _lcidToLocale(int(langHex, 16)) if langHex else None
			except ValueError:
				lang = None
			voices[modeId] = VoiceInfo(modeId, name or modeId, lang)
		return voices

	def _onVoiceApplied(self, hr: int, info: str) -> None:
		self._ranges = parseRanges(info) if hr >= 0 else {}

	def _param(self, kind: str, percent: int) -> int | None:
		r = self._ranges.get(kind)
		if not r:
			return None
		return percentToParam(percent, r[0], r[1])

	def _buildRequest(self, items: list) -> tuple[str, int | None, int | None]:
		# (La voz ya está elegida: los márgenes de self._ranges son los suyos.)
		rate =int(self._settings.get("rate", 50))
		pitch = int(self._settings.get("pitch", 50))
		baseRate = self._param("rate", rate)
		basePitch = self._param("pitch", pitch)
		out: list[str] = []
		charMode = False
		prosody = False
		for it in items:
			if isinstance(it, str):
				# La barra inversa abre las etiquetas de SAPI 4: se duplica.
				out.append(it.replace("\\", "\\\\"))
			elif isinstance(it, CharacterModeCommand):
				out.append("\\RmS=1\\" if it.state else "\\RmS=0\\")
				charMode = bool(it.state)
			elif isinstance(it, BreakCommand):
				out.append(f"\\Pau={int(it.time)}\\")
			elif isinstance(it, PitchCommand):
				val = self._param("pitch", it.applyTo(pitch))
				if val is not None:
					out.append(f"\\Pit={val}\\")
					prosody = True
			elif isinstance(it, RateCommand):
				val = self._param("rate", it.applyTo(rate))
				if val is not None:
					out.append(f"\\Spd={val}\\")
					prosody = True
			elif isinstance(it, VolumeCommand):
				# El volumen del usuario lo aplica el reproductor: aquí solo el cambio relativo.
				val = self._param("volume", it.applyTo(100))
				if val is not None:
					out.append(f"\\Vol={val}\\")
					prosody = True
			elif isinstance(it, PhonemeCommand):
				out.append((it.text or "").replace("\\", "\\\\"))
		if prosody:
			# Algunos motores SAPI 4 no deshacen los cambios de prosodia: se
			# vuelve a los valores normales al final (NVDA #15500).
			if baseRate is not None:
				out.append(f"\\Spd={baseRate}\\")
			if basePitch is not None:
				out.append(f"\\Pit={basePitch}\\")
			vol = self._param("volume", 100)
			if vol is not None:
				out.append(f"\\Vol={vol}\\")
		if charMode:
			out.append("\\RmS=0\\")
		return "".join(out), baseRate, basePitch
