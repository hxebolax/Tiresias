"""Órdenes de audio: mezclador, micrófono, dispositivos, sonidos de controles y voces Piper.

:func:`install` las añade a ``GlobalCommands`` (como hace el soporte
táctil), así aparecen en «Gestos de entrada», la ayuda de entrada y la
paleta de órdenes y se pueden reasignar.
"""

from __future__ import annotations

from ..baseobject import normalizeGestureId, script
from ..config import conf
from ..i18n import _
from ..log import getLogger

log = getLogger("audioCommands")

CAT_AUDIO = _("Audio")


def _say(text: str) -> None:
	from .. import speech

	speech.speakMessage(text)


def _guarded(func):
	"""Las órdenes de audio nunca deben romper el núcleo si Core Audio falla."""

	def wrapper(self, gesture) -> None:
		try:
			func(self, gesture)
		except Exception:
			log.exception("Error en la orden de audio %s", func.__name__)
			_say(_("No se pudo acceder al audio del sistema"))

	wrapper.__name__ = func.__name__
	wrapper.__doc__ = func.__doc__
	return wrapper


# ---------------------------------------------------------------- órdenes
@_guarded
def script_audio_showMixer(self, gesture) -> None:
	from .. import gui
	from ..gui import audio_dialogs

	gui.runOnGui(audio_dialogs.showMixer)


@_guarded
def script_audio_otherAppsVolumeUp(self, gesture) -> None:
	from . import mixer

	_say(_("Otras aplicaciones {vol} por ciento").format(vol=mixer.changeOtherAppsVolume(1)))


@_guarded
def script_audio_otherAppsVolumeDown(self, gesture) -> None:
	from . import mixer

	_say(_("Otras aplicaciones {vol} por ciento").format(vol=mixer.changeOtherAppsVolume(-1)))


@_guarded
def script_audio_toggleOtherAppsMute(self, gesture) -> None:
	from . import mixer, tones

	muted = mixer.toggleOtherAppsMute()
	tones.playSound("muted" if muted else "unmuted")
	_say(_("Otras aplicaciones silenciadas") if muted else _("Otras aplicaciones con sonido"))


def _focusApp():
	from . import mixer

	app = mixer.foregroundApp()
	if app is None:
		_say(_("Esta aplicación no está reproduciendo sonido"))
	return app


@_guarded
def script_audio_focusAppVolumeUp(self, gesture) -> None:
	from . import mixer

	app = _focusApp()
	if app is not None:
		_say(_("{name} {vol} por ciento").format(name=app.name, vol=mixer.changeAppVolume(app, 1)))


@_guarded
def script_audio_focusAppVolumeDown(self, gesture) -> None:
	from . import mixer

	app = _focusApp()
	if app is not None:
		_say(_("{name} {vol} por ciento").format(name=app.name, vol=mixer.changeAppVolume(app, -1)))


@_guarded
def script_audio_toggleFocusAppMute(self, gesture) -> None:
	from . import tones

	app = _focusApp()
	if app is not None:
		mute = not app.muted()
		app.setMute(mute)
		tones.playSound("muted" if mute else "unmuted")
		_say(_("{name} silenciada").format(name=app.name) if mute else _("{name} con sonido").format(name=app.name))


@_guarded
def script_audio_toggleMicMute(self, gesture) -> None:
	import comtypes

	from . import mixer

	try:
		muted = mixer.toggleMicMute()
	except (OSError, comtypes.COMError):
		# Sin micrófono, GetDefaultAudioEndpoint lanza COMError (no OSError).
		_say(_("No hay ningún micrófono"))
		return
	mixer.announceMicState(muted)


@_guarded
def script_audio_nextTiresiasOutput(self, gesture) -> None:
	from . import mixer, tones

	msg = mixer.cycleTiresiasOutput(1)
	_say(msg)
	tones.playSound("deviceChange")


@_guarded
def script_audio_nextSystemOutput(self, gesture) -> None:
	from . import mixer, tones

	_say(mixer.cycleDefaultOutput(1))
	tones.playSound("deviceChange")


@_guarded
def script_audio_masterVolumeUp(self, gesture) -> None:
	from . import mixer

	_say(_("Volumen general {vol} por ciento").format(vol=mixer.changeMasterVolume(1)))


@_guarded
def script_audio_masterVolumeDown(self, gesture) -> None:
	from . import mixer

	_say(_("Volumen general {vol} por ciento").format(vol=mixer.changeMasterVolume(-1)))


@_guarded
def script_audio_toggleMasterMute(self, gesture) -> None:
	from . import mixer, tones

	muted = mixer.toggleMasterMute()
	tones.playSound("muted" if muted else "unmuted")
	_say(_("Sonido del sistema silenciado") if muted else _("Sonido del sistema activado"))


@_guarded
def script_audio_muteKey(self, gesture) -> None:
	from . import mixer

	_say(mixer.handleMuteKey())


@_guarded
def script_audio_reportStatus(self, gesture) -> None:
	from . import mixer
	from .wave_player import OutputSettings

	parts = [mixer.describeMaster()]
	try:
		_vol, micMuted = mixer.getMicState()
		parts.append(_("micrófono silenciado") if micMuted else _("micrófono activado"))
	except Exception:
		parts.append(_("sin micrófono"))
	device = OutputSettings.deviceName or _("predeterminado de Windows")
	parts.append(_("salida de Tiresias: {name}").format(name=device))
	_say(". ".join(parts))


@_guarded
def script_audio_cycleOutputMode(self, gesture) -> None:
	from .wave_player import OUTPUT_MODES

	cur = conf["audio"]["outputMode"]
	nxt = OUTPUT_MODES[(OUTPUT_MODES.index(cur) + 1) % len(OUTPUT_MODES)] if cur in OUTPUT_MODES else OUTPUT_MODES[0]
	conf["audio"]["outputMode"] = nxt
	_say(_("Salida de audio WASAPI") if nxt == "wasapi" else _("Salida de audio waveOut"))


def script_earcons_cycleMode(self, gesture) -> None:
	from . import earcons

	_say(earcons.cycleMode())


def script_earcons_togglePositional(self, gesture) -> None:
	val = not conf["earcons"]["positional"]
	conf["earcons"]["positional"] = val
	_say(_("Audio posicional activado") if val else _("Audio posicional desactivado"))


def script_piper_showVoiceManager(self, gesture) -> None:
	from .. import gui
	from ..gui import piper_dialog

	gui.runOnGui(piper_dialog.showVoiceManager)


# (función, descripción, gestos)
_SCRIPTS = [
	(script_audio_showMixer, _("Abre el mezclador de audio"), ("kb:tiresias+alt+a",)),
	(script_audio_otherAppsVolumeUp, _("Sube el volumen de todas las aplicaciones menos Tiresias"), ("kb:tiresias+alt+pageUp",)),
	(script_audio_otherAppsVolumeDown, _("Baja el volumen de todas las aplicaciones menos Tiresias"), ("kb:tiresias+alt+pageDown",)),
	(script_audio_toggleOtherAppsMute, _("Silencia o devuelve el sonido a todas las aplicaciones menos Tiresias"), ("kb:tiresias+alt+delete",)),
	(script_audio_focusAppVolumeUp, _("Sube el volumen de la aplicación en primer plano"), ("kb:tiresias+control+alt+pageUp",)),
	(script_audio_focusAppVolumeDown, _("Baja el volumen de la aplicación en primer plano"), ("kb:tiresias+control+alt+pageDown",)),
	(script_audio_toggleFocusAppMute, _("Silencia o devuelve el sonido a la aplicación en primer plano"), ("kb:tiresias+alt+shift+delete",)),
	(script_audio_toggleMicMute, _("Silencia o activa el micrófono, con confirmación sonora"), ("kb:tiresias+alt+shift+m",)),
	(script_audio_nextTiresiasOutput, _("Cambia el dispositivo de salida de Tiresias"), ("kb:tiresias+alt+o",)),
	(script_audio_nextSystemOutput, _("Cambia el dispositivo de salida predeterminado de Windows"), ("kb:tiresias+alt+shift+o",)),
	(script_audio_masterVolumeUp, _("Sube el volumen general del sistema"), ()),
	(script_audio_masterVolumeDown, _("Baja el volumen general del sistema"), ()),
	(script_audio_toggleMasterMute, _("Silencia o activa el sonido general del sistema"), ()),
	(script_audio_muteKey, _("Tecla Silenciar del teclado: pide una segunda pulsación antes de silenciar el equipo"), ("kb:volumeMute",)),
	(script_audio_reportStatus, _("Anuncia el volumen general, el micrófono y la salida de Tiresias"), ()),
	(script_audio_cycleOutputMode, _("Cambia la salida de audio entre WASAPI y waveOut"), ()),
	(script_earcons_cycleMode, _("Cambia el modo de los sonidos de los controles (desactivados, con voz o en lugar del rol)"), ("kb:tiresias+alt+shift+s",)),
	(script_earcons_togglePositional, _("Activa o desactiva el audio posicional de los sonidos de los controles"), ()),
	(script_piper_showVoiceManager, _("Abre el gestor de voces neuronales Piper"), ()),
]

_installed: set = set()


def install(cls: type) -> None:
	"""Añade las órdenes de audio a ``cls`` (``GlobalCommands``)."""
	if cls in _installed:
		return
	_installed.add(cls)
	gestures = cls.__dict__.get("_classGestures")
	if gestures is None:
		gestures = {}
		cls._classGestures = gestures  # type: ignore[attr-defined]
	for func, description, keys in _SCRIPTS:
		name = func.__name__
		if name not in cls.__dict__:
			setattr(cls, name, script(description=description, category=CAT_AUDIO, gestures=keys)(func))
		for g in keys:
			gestures.setdefault(normalizeGestureId(g), name[7:])
