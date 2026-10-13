"""Arranque y cierre de las funciones de audio que no dependen de un sintetizador.

El núcleo llama a :func:`initializeEarly` antes del sonido de inicio (para
quitar el silencio del sistema si hace falta, #3049), a :func:`initialize`
cuando el resto está listo y a :func:`terminate` al cerrar.
"""

from __future__ import annotations

from .. import queue_handler
from ..log import getLogger

log = getLogger("audioManager")

_startupMessage: str | None = None


def initializeEarly() -> None:
	global _startupMessage
	from . import mixer

	try:
		_startupMessage = mixer.ensureAudible()
		if _startupMessage:
			log.info(_startupMessage)
	except Exception:
		log.exception("Error comprobando el volumen al arrancar")
	# La sesión de audio propia no existe hasta que se abre el primer flujo:
	# entonces se le vuelve a quitar el silencio (en el hilo de sesiones).
	from . import core_audio, wave_player

	wave_player.onFirstStream(lambda: core_audio.runInSessionThread(mixer.ensureOwnSessionAudible))


def initialize() -> None:
	from . import earcons, mixer  # noqa: F401 (earcons registra sus sonidos al importarse)

	mixer.startVolumeNotifications()
	if _startupMessage:
		from .. import speech

		msg = _startupMessage
		queue_handler.callLater(1200, lambda: speech.speakMessage(msg))
	try:
		from .. import gui
		from ..gui import audio_dialogs

		gui.runOnGui(audio_dialogs.register)
	except Exception:
		log.debug("No se pudieron registrar las categorías de audio", exc_info=True)


def terminate() -> None:
	from . import mixer

	mixer.terminate()
