"""Sintetizador mudo: no produce voz (útil con braille o para pruebas)."""

from __future__ import annotations

from ..i18n import _
from ..speech.commands import IndexCommand
from .base import SynthDriver as _Base


class SynthDriver(_Base):
	name = "silence"
	description = _("Sin voz")
	supportedSettings = ()

	@classmethod
	def check(cls) -> bool:
		return True

	def speak(self, sequence: list) -> None:
		for item in sequence:
			if isinstance(item, IndexCommand):
				self._notifyIndex(item.index)
		self._notifyDone()

	def cancel(self) -> None:
		pass
