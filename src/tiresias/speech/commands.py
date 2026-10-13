"""Órdenes que pueden intercalarse en una secuencia de voz.

Una secuencia de voz es una lista de cadenas y objetos de este módulo, por
ejemplo::

	["Botón", PitchCommand(30), "A", PitchCommand(0), BreakCommand(200)]
"""

from __future__ import annotations

from typing import Callable


class SpeechCommand:
	"""Clase base de las órdenes de voz."""

	def __repr__(self) -> str:
		attrs = ", ".join(f"{k}={v!r}" for k, v in vars(self).items())
		return f"{type(self).__name__}({attrs})"


class SynthCommand(SpeechCommand):
	"""Orden que debe interpretar el sintetizador."""


class IndexCommand(SynthCommand):
	"""Marca de posición: el sintetizador avisa cuando llega a ella."""

	def __init__(self, index: int) -> None:
		self.index = index


class CharacterModeCommand(SynthCommand):
	"""Activa o desactiva el deletreo carácter a carácter."""

	def __init__(self, state: bool) -> None:
		self.state = state


class LangChangeCommand(SynthCommand):
	"""Cambia el idioma (``None`` vuelve al idioma por defecto)."""

	def __init__(self, lang: str | None) -> None:
		self.lang = lang


class BreakCommand(SynthCommand):
	"""Pausa en milisegundos."""

	def __init__(self, time: int) -> None:
		self.time = time


class _ProsodyCommand(SynthCommand):
	"""Cambio relativo de prosodia en porcentaje (0 = valor normal)."""

	settingName = ""

	def __init__(self, offset: int = 0, multiplier: float = 1.0) -> None:
		self.offset = offset
		self.multiplier = multiplier

	def applyTo(self, base: int) -> int:
		return max(0, min(100, int(base * self.multiplier + self.offset)))


class PitchCommand(_ProsodyCommand):
	settingName = "pitch"


class RateCommand(_ProsodyCommand):
	settingName = "rate"


class VolumeCommand(_ProsodyCommand):
	settingName = "volume"


class VoiceCommand(SpeechCommand):
	"""Voz del sintetizador con la que se dice el enunciado (voces por
	contexto, foros 2.3). La consume el gestor de voz: cambia de voz entre
	enunciados (nunca a mitad de uno) y vuelve a la normal después."""

	def __init__(self, voice: str) -> None:
		self.voice = voice


class SymbolLevelCommand(SpeechCommand):
	"""Nivel de puntuación de las cadenas que siguen (``None`` = el general).

	Lo aplica ``speech._processSequence`` salvo que la llamada indique un
	nivel propio (deletreo, eco de caracteres)."""

	def __init__(self, level: int | None) -> None:
		self.level = level


class PhonemeCommand(SynthCommand):
	def __init__(self, ipa: str, text: str = "") -> None:
		self.ipa = ipa
		self.text = text


class EndUtteranceCommand(SpeechCommand):
	"""Separa enunciados dentro de una misma secuencia."""


class CallbackCommand(SpeechCommand):
	"""Llama a una función cuando la voz llega a este punto."""

	def __init__(self, callback: Callable[[], None]) -> None:
		self.callback = callback


class BeepCommand(SpeechCommand):
	"""Emite un pitido en este punto de la voz."""

	def __init__(self, hz: float, length: int, left: int = 50, right: int = 50) -> None:
		self.hz = hz
		self.length = length
		self.left = left
		self.right = right


class WaveFileCommand(SpeechCommand):
	"""Reproduce un sonido con nombre en este punto de la voz."""

	def __init__(self, name: str) -> None:
		self.name = name


SpeechSequence = list  # list[str | SpeechCommand]
