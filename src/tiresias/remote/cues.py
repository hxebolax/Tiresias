"""Sonidos y mensajes del acceso remoto.

Los sonidos se sintetizan como el resto de sonidos de Tiresias; se pueden
sustituir poniendo un ``.wav`` con el mismo nombre en ``data/sounds``.
"""

from __future__ import annotations

from ..audio import tones
from ..config import conf
from ..i18n import _

SOUNDS: dict[str, list[tuple[float, int]]] = {
	"remoteConnected": [(523.25, 60), (783.99, 60), (1046.5, 110)],
	"remoteDisconnected": [(1046.5, 60), (783.99, 60), (523.25, 110)],
	"remoteControlled": [(659.25, 70), (0, 30), (659.25, 70), (987.77, 110)],
	"remoteControlling": [(880, 50), (1318.5, 90)],
	"remoteClientLeft": [(659.25, 60), (440, 100)],
	"remoteClipboardPush": [(1318.5, 30), (1760, 40)],
	"remoteClipboardReceive": [(1760, 30), (1318.5, 40)],
}

#: Sonidos de NVDA (``waves/<nombre>.wav``) -> sonido equivalente de Tiresias.
NVDA_WAVES = {
	"browsemode": "browseMode",
	"focusmode": "focusMode",
	"error": "error",
	"texterror": "textError",
	"screencurtainon": "screenCurtainOn",
	"screencurtainoff": "screenCurtainOff",
	"start": "start",
	"exit": "exit",
	"suggestionsopened": "suggestion",
	"suggestionsclosed": "suggestion",
	"connected": "remoteConnected",
	"disconnected": "remoteDisconnected",
	"controlled": "remoteControlled",
	"controlling": "remoteControlling",
	"clipboardpush": "remoteClipboardPush",
	"clipboardreceive": "remoteClipboardReceive",
}
#: Sonido de Tiresias -> archivo de NVDA (para que un NVDA que controla lo oiga).
TIRESIAS_TO_NVDA = {
	"browseMode": "browseMode",
	"focusMode": "focusMode",
	"error": "error",
	"textError": "textError",
	"screenCurtainOn": "screenCurtainOn",
	"screenCurtainOff": "screenCurtainOff",
	"suggestion": "suggestionsOpened",
}


def registerSounds() -> None:
	for name, notes in SOUNDS.items():
		tones.registerSound(name, notes)


def _play(name: str) -> None:
	try:
		if conf["remote"]["playSounds"]:
			tones.playSound(name)
	except KeyError:
		tones.playSound(name)


def _say(text: str) -> None:
	from .. import speech

	speech.speakMessage(text)


def connected() -> None:
	_play("remoteConnected")


def connectedAsFollower() -> None:
	_play("remoteControlled")
	_say(_("Conectado como equipo controlado"))


def disconnected() -> None:
	_play("remoteDisconnected")
	_say(_("Desconectado del acceso remoto"))


def clientJoined() -> None:
	_play("remoteControlling")


def clientLeft() -> None:
	_play("remoteClientLeft")


def clipboardPushed() -> None:
	_play("remoteClipboardPush")
	_say(_("Portapapeles enviado"))


def clipboardReceived() -> None:
	_play("remoteClipboardReceive")
	_say(_("Portapapeles recibido"))
