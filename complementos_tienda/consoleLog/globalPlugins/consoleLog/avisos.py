"""Mensajes por voz y braille y sonidos del complemento.

Todo se encola en el hilo del núcleo de Tiresias, así que estas funciones se
pueden llamar desde cualquier hilo (interfaz, lectura de consolas, red).
"""

from __future__ import annotations

import ctypes

from tiresias.log import getLogger

log = getLogger("consoleLog")

#: Último mensaje anunciado (para repetirlo).
_ultimo = ""


def _enNucleo(funcion, *args) -> None:
	from tiresias import queue_handler

	queue_handler.queueFunction(funcion, *args)


def anunciar(texto: str, inmediato: bool = False) -> None:
	"""Habla un mensaje (y lo muestra en braille)."""
	global _ultimo
	if not texto:
		return
	_ultimo = texto

	def hablar() -> None:
		from tiresias import speech

		if inmediato:
			speech.cancelSpeech()
		speech.speakMessage(texto)

	_enNucleo(hablar)
	log.debug("consoleLog: %s", texto)


def anunciarError(texto: str) -> None:
	anunciar("Error: {}".format(texto), inmediato=True)
	log.error("consoleLog: %s", texto)


def anunciarAdvertencia(texto: str) -> None:
	anunciar("Advertencia: {}".format(texto))
	log.warning("consoleLog: %s", texto)


def repetirUltimo() -> None:
	if _ultimo:
		anunciar(_ultimo)


def ultimoMensaje() -> str:
	return _ultimo


def pitido(hz: float, ms: int) -> None:
	"""Pitido con el volumen de sonidos de Tiresias."""

	def sonar() -> None:
		try:
			from tiresias.audio import tones

			tones.beep(hz, ms)
		except Exception:
			log.debug("No se pudo emitir el pitido", exc_info=True)

	_enNucleo(sonar)


def sonidoAlerta() -> None:
	"""Sonido «Exclamación» del esquema de sonidos de Windows (como el original)."""
	try:
		MB_ICONEXCLAMATION = 0x30
		ctypes.windll.user32.MessageBeep(MB_ICONEXCLAMATION)
	except Exception:
		pitido(880, 120)
