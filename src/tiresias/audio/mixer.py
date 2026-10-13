"""Mezclador de audio: volumen general, aplicaciones, micrófono y dispositivos.

Funciones para las órdenes y el diálogo «Mezclador de audio»:

- volumen y silencio generales del dispositivo de salida predeterminado;
- volumen y silencio por aplicación (agrupando las sesiones de audio por
  ejecutable: un navegador con varios procesos es una sola aplicación) y de
  «todas las aplicaciones menos Tiresias» (#16052);
- silenciar o activar el micrófono con confirmación sonora (#16056);
- cambiar el dispositivo de salida de Tiresias y el predeterminado del
  sistema (#8801);
- al arrancar, quitar el silencio y subir el volumen general si está a 0 (#3049);
- avisos de cambio de volumen y confirmación de la tecla Silenciar (#6427).

Todas las funciones usan COM y deben llamarse en el hilo del núcleo (o en
otro hilo con COM inicializado), nunca en el de la interfaz.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import HRESULT, c_float, c_void_p
from ctypes.wintypes import BOOL, UINT

import comtypes
from comtypes import COMMETHOD, GUID, IUnknown

from .. import queue_handler
from ..config import conf
from ..i18n import _
from ..log import getLogger
from . import core_audio

log = getLogger("mixer")

#: Contexto de los cambios que hace Tiresias (para no anunciarlos dos veces).
EVENT_CONTEXT = GUID("{6d1f2a8e-4a5b-4e1e-9c0b-7a3e5f2c1d90}")
SYSTEM_SOUNDS_KEY = "*system*"


def _ctx():
	return ctypes.byref(EVENT_CONTEXT)


def _percent(level: float) -> int:
	return int(round(max(0.0, min(1.0, level)) * 100))


def _step() -> float:
	try:
		return max(1, min(50, int(conf["audio"]["mixerVolumeStep"]))) / 100.0
	except (KeyError, TypeError, ValueError):
		return 0.05


# ---------------------------------------------------------------- volumen general
def getMasterVolume() -> tuple[int, bool]:
	"""(volumen 0-100, silenciado) del dispositivo de salida predeterminado."""
	ev = core_audio.endpointVolume(None, core_audio.eRender)
	return _percent(ev.GetMasterVolumeLevelScalar()), bool(ev.GetMute())


def setMasterVolume(percent: int) -> int:
	ev = core_audio.endpointVolume(None, core_audio.eRender)
	level = max(0, min(100, int(percent))) / 100.0
	ev.SetMasterVolumeLevelScalar(level, _ctx())
	return _percent(level)


def changeMasterVolume(direction: int) -> int:
	vol, _muted = getMasterVolume()
	return setMasterVolume(vol + direction * round(_step() * 100))


def setMasterMute(mute: bool) -> None:
	core_audio.endpointVolume(None, core_audio.eRender).SetMute(bool(mute), _ctx())


def toggleMasterMute() -> bool:
	_vol, muted = getMasterVolume()
	setMasterMute(not muted)
	return not muted


def describeMaster() -> str:
	vol, muted = getMasterVolume()
	if muted:
		return _("Volumen general {vol} por ciento, silenciado").format(vol=vol)
	return _("Volumen general {vol} por ciento").format(vol=vol)


# ---------------------------------------------------------------- micrófono
def getMicState(deviceId: str | None = None) -> tuple[int, bool]:
	"""(volumen 0-100, silenciado) del micrófono (predeterminado si no se indica)."""
	ev = core_audio.endpointVolume(deviceId, core_audio.eCapture)
	return _percent(ev.GetMasterVolumeLevelScalar()), bool(ev.GetMute())


def setMicMute(mute: bool, deviceId: str | None = None) -> None:
	"""Silencia el micrófono indicado o el predeterminado (y el de comunicaciones)."""
	if deviceId:
		core_audio.endpointVolume(deviceId, core_audio.eCapture).SetMute(bool(mute), _ctx())
		return
	ids = []
	for role in (core_audio.eConsole, core_audio.eCommunications):
		devId = core_audio.getDefaultDeviceId(core_audio.eCapture, role)
		if devId and devId not in ids:
			ids.append(devId)
	if not ids:
		raise OSError("No hay micrófono")
	for devId in ids:
		core_audio.endpointVolume(devId, core_audio.eCapture).SetMute(bool(mute), _ctx())


def setMicVolume(percent: int, deviceId: str | None = None) -> int:
	ev = core_audio.endpointVolume(deviceId, core_audio.eCapture)
	level = max(0, min(100, int(percent))) / 100.0
	ev.SetMasterVolumeLevelScalar(level, _ctx())
	return _percent(level)


def toggleMicMute() -> bool:
	"""Cambia el silencio del micrófono predeterminado; devuelve si queda silenciado."""
	_vol, muted = getMicState()
	setMicMute(not muted)
	return not muted


def announceMicState(muted: bool) -> None:
	from .. import speech
	from . import tones

	if conf["audio"]["micMuteSounds"]:
		tones.playSound("micMuted" if muted else "micUnmuted")
	speech.speakMessage(_("Micrófono silenciado") if muted else _("Micrófono activado"))


# ---------------------------------------------------------------- aplicaciones
class App:
	"""Aplicación con audio: todas las sesiones de un mismo ejecutable."""

	def __init__(self, key: str, name: str) -> None:
		self.key = key
		self.name = name
		self.sessions: list[core_audio.Session] = []
		self.pids: set[int] = set()

	@property
	def isOwn(self) -> bool:
		return core_audio.OWN_PID in self.pids

	def volume(self) -> int:
		"""Volumen sin la atenuación: si la aplicación está atenuada, el que recuperará."""
		from . import ducking

		levels = []
		for s in self.sessions:
			try:
				levels.append(ducking.sessionVolume(s))
			except comtypes.COMError:
				continue
		return _percent(max(levels)) if levels else 0

	def muted(self) -> bool:
		states = []
		for s in self.sessions:
			try:
				states.append(bool(s.simpleVolume().GetMute()))
			except comtypes.COMError:
				continue
		return bool(states) and all(states)

	def setVolume(self, percent: int) -> int:
		"""Cambia el volumen; si la aplicación está atenuada, cambia el que recuperará."""
		from . import ducking

		level = max(0, min(100, int(percent))) / 100.0
		for s in self.sessions:
			try:
				ducking.setSessionVolume(s, level, _ctx())
			except comtypes.COMError:
				continue
		return _percent(level)

	def setMute(self, mute: bool) -> None:
		for s in self.sessions:
			try:
				s.simpleVolume().SetMute(bool(mute), _ctx())
			except comtypes.COMError:
				continue

	def describe(self) -> str:
		text = _("{name}: {vol} por ciento").format(name=self.name, vol=self.volume())
		if self.muted():
			text += ", " + _("silenciada")
		return text


def _appKey(pid: int) -> tuple[str, str]:
	from .. import winapi

	if pid == 0:
		return SYSTEM_SOUNDS_KEY, _("Sonidos del sistema")
	if pid == core_audio.OWN_PID:
		from .. import APP_NAME

		return "*own*", APP_NAME
	exe = winapi.getProcessName(pid) or str(pid)
	return exe, exe[:1].upper() + exe[1:]


def listApps() -> list[App]:
	"""Aplicaciones con sesiones de audio en cualquier salida activa."""
	apps: dict[str, App] = {}
	for s in core_audio.getSessions(allDevices=True):
		if s.state() == 2:  # caducada
			continue
		key, name = _appKey(s.pid)
		app = apps.get(key)
		if app is None:
			app = apps[key] = App(key, name)
		display = s.displayName()
		if display and not display.startswith("@") and s.pid not in (0, core_audio.OWN_PID):
			app.name = display
		app.sessions.append(s)
		app.pids.add(s.pid)
	return sorted(apps.values(), key=lambda a: (a.key in (SYSTEM_SOUNDS_KEY, "*own*"), a.name.lower()))


def findApp(key: str) -> App | None:
	for app in listApps():
		if app.key == key:
			return app
	return None


def foregroundApp() -> App | None:
	"""Aplicación con audio que corresponde a la ventana en primer plano."""
	from .. import winapi

	hwnd = winapi.getForegroundWindow()
	pid = winapi.getWindowProcessId(hwnd) if hwnd else 0
	if not pid:
		return None
	key, _name = _appKey(pid)
	apps = listApps()
	for app in apps:
		if pid in app.pids or app.key == key:
			return app
	# Aplicaciones de la Tienda: la ventana es de ApplicationFrameHost.
	try:
		import psutil

		children = {p.pid for p in psutil.Process(pid).children(recursive=True)}
	except Exception:
		children = set()
	for app in apps:
		if app.pids & children:
			return app
	return None


def changeAppVolume(app: App, direction: int) -> int:
	return app.setVolume(app.volume() + direction * round(_step() * 100))


def otherApps() -> list[App]:
	"""Las demás aplicaciones, sin los sonidos del sistema ni otros lectores de
	pantalla: Windows recuerda el silencio y el volumen de cada programa, y
	silenciar «las demás» dejaba mudo a NVDA aunque se reiniciara."""
	from .ducking import NEVER_DUCK

	return [
		a
		for a in listApps()
		if not a.isOwn and a.key != SYSTEM_SOUNDS_KEY and str(a.key).lower() not in NEVER_DUCK
	]


def changeOtherAppsVolume(direction: int) -> int:
	"""Sube o baja todas las aplicaciones salvo Tiresias. Devuelve el volumen máximo resultante."""
	result = 0
	for app in otherApps():
		result = max(result, changeAppVolume(app, direction))
	return result


def toggleOtherAppsMute() -> bool:
	apps = otherApps()
	mute = not all(a.muted() for a in apps) if apps else True
	for app in apps:
		app.setMute(mute)
	return mute


# ---------------------------------------------------------------- dispositivos
def outputDevices() -> list[core_audio.Device]:
	return core_audio.getDevices(core_audio.eRender)


def inputDevices() -> list[core_audio.Device]:
	return core_audio.getDevices(core_audio.eCapture)


def setDefaultOutput(deviceId: str) -> None:
	core_audio.setDefaultDevice(deviceId)


def setDefaultInput(deviceId: str) -> None:
	core_audio.setDefaultDevice(deviceId)


def cycleDefaultOutput(direction: int = 1) -> str:
	"""Pasa al siguiente dispositivo de salida predeterminado del sistema."""
	devices = outputDevices()
	if not devices:
		return _("No hay dispositivos de salida")
	if len(devices) == 1:
		return _("Solo hay un dispositivo de salida: {name}").format(name=devices[0].name)
	cur = next((i for i, d in enumerate(devices) if d.isDefault), -1)
	nxt = devices[(cur + direction) % len(devices)]
	setDefaultOutput(nxt.id)
	return _("Salida predeterminada del sistema: {name}").format(name=nxt.name)


def tiresiasOutputChoices() -> list[tuple[str, str]]:
	"""[(valor de ``audio.outputDevice``, nombre)] empezando por el predeterminado."""
	items = [("", _("Predeterminado de Windows"))]
	items += [(d.name, d.name) for d in outputDevices()]
	return items


def setTiresiasOutput(name: str) -> None:
	"""Cambia el dispositivo de salida de Tiresias (voz y sonidos) al instante."""
	from .wave_player import OutputSettings

	conf["audio"]["outputDevice"] = name
	OutputSettings.deviceName = name


def cycleTiresiasOutput(direction: int = 1) -> str:
	choices = tiresiasOutputChoices()
	values = [v for v, _n in choices]
	cur = conf["audio"]["outputDevice"]
	i = values.index(cur) if cur in values else 0
	value, name = choices[(i + direction) % len(choices)]
	setTiresiasOutput(value)
	return _("Salida de Tiresias: {name}").format(name=name)


# ---------------------------------------------------------------- arranque (#3049)
def ensureAudible() -> str | None:
	"""Quita el silencio del sistema y sube el volumen general si está a 0.

	También quita el silencio de la propia sesión de Tiresias (Windows
	recuerda el volumen de cada programa). Devuelve un mensaje si cambió algo.
	"""
	if not conf["audio"]["unmuteOnStartup"]:
		return None
	changed = []
	try:
		ev = core_audio.endpointVolume(None, core_audio.eRender)
		if ev.GetMute():
			ev.SetMute(False, _ctx())
			changed.append(_("se ha quitado el silencio"))
		if ev.GetMasterVolumeLevelScalar() < 0.005:
			level = max(5, min(100, int(conf["audio"]["startupVolumeLevel"])))
			ev.SetMasterVolumeLevelScalar(level / 100.0, _ctx())
			changed.append(_("se ha subido el volumen al {vol} por ciento").format(vol=level))
	except (comtypes.COMError, OSError):
		log.debug("No se pudo comprobar el volumen general", exc_info=True)
	# Al arrancar, la sesión propia aún no existe (Windows la crea al abrir el
	# primer flujo de audio): se repite entonces (ensureOwnSessionAudible).
	ensureOwnSessionAudible()
	if not changed:
		return None
	return _("Sonido del sistema: {changes}").format(changes=", ".join(changed))


def ensureOwnSessionAudible() -> bool:
	"""Quita el silencio de la sesión de audio de Tiresias y la sube si está a 0.

	Windows recuerda el volumen de cada programa, así que la sesión propia
	puede empezar silenciada. Devuelve ``True`` si cambió algo.
	"""
	if not conf["audio"]["unmuteOnStartup"]:
		return False
	changed = False
	try:
		for s in core_audio.getSessions(allDevices=True):
			if s.pid != core_audio.OWN_PID:
				continue
			sv = s.simpleVolume()
			if sv.GetMute():
				sv.SetMute(False, _ctx())
				changed = True
			if sv.GetMasterVolume() < 0.005:
				sv.SetMasterVolume(1.0, _ctx())
				changed = True
			try:
				# Balance a cero en todos los canales (lo dejó otro programa, p.
				# ej. la división de sonido de otro lector): también es silencio.
				cv = s.channelVolume()
				n = cv.GetChannelCount()
				if n and all(cv.GetChannelVolume(ch) < 0.005 for ch in range(n)):
					for ch in range(n):
						cv.SetChannelVolume(ch, 1.0, _ctx())
					changed = True
			except (comtypes.COMError, OSError):
				pass
	except (comtypes.COMError, OSError):
		log.debug("No se pudo comprobar la sesión propia", exc_info=True)
	if changed:
		log.info("Se ha quitado el silencio de la sesión de audio de Tiresias")
	return changed


# ---------------------------------------------------------------- avisos de volumen (#6427)
class AUDIO_VOLUME_NOTIFICATION_DATA(ctypes.Structure):
	_fields_ = [
		("guidEventContext", GUID),
		("bMuted", BOOL),
		("fMasterVolume", c_float),
		("nChannels", UINT),
		("afChannelVolumes", c_float * 1),
	]


class IAudioEndpointVolumeCallback(IUnknown):
	_iid_ = GUID("{657804FA-D6AD-4496-8A60-352752AF4F89}")
	_methods_ = [COMMETHOD([], HRESULT, "OnNotify", (["in"], c_void_p, "pNotify"))]


class _VolumeCallback(comtypes.COMObject):
	_com_interfaces_ = [IAudioEndpointVolumeCallback]

	def OnNotify(self, pNotify) -> int:  # noqa: N802 (nombre COM)
		try:
			data = AUDIO_VOLUME_NOTIFICATION_DATA.from_address(pNotify)
			if data.guidEventContext != EVENT_CONTEXT:
				_onExternalVolumeChange(_percent(data.fMasterVolume), bool(data.bMuted))
		except Exception:
			log.debug("Error en el aviso de volumen", exc_info=True)
		return 0


_callback: _VolumeCallback | None = None
_callbackVolume = None
_lastState: tuple[int, bool] | None = None
_pendingReport: int | None = None
_reportLock = threading.Lock()


def _onExternalVolumeChange(vol: int, muted: bool) -> None:
	"""Llega desde un hilo de Windows: se agrupa y se anuncia en el núcleo."""
	global _lastState
	with _reportLock:
		_lastState = (vol, muted)
	queue_handler.queueFunction(_scheduleReport)


def _scheduleReport() -> None:
	global _pendingReport
	if _pendingReport is not None:
		queue_handler.cancelCallLater(_pendingReport)
	_pendingReport = queue_handler.callLater(150, _report)


def _report() -> None:
	global _pendingReport
	_pendingReport = None
	mode = conf["audio"]["volumeChangeFeedback"]
	with _reportLock:
		state = _lastState
	if state is None or mode == "off":
		return
	from .. import speech
	from . import tones

	vol, muted = state
	if mode in ("sound", "both"):
		tones.playSound("muted" if muted else "volumeChange")
	if mode in ("speech", "both"):
		speech.speakMessage(_("silenciado") if muted else _("{vol} por ciento").format(vol=vol))


def startVolumeNotifications() -> None:
	"""Empieza a recibir los cambios del volumen general (dispositivo predeterminado)."""
	global _callback, _callbackVolume, _callbackDevice, _wanted
	stopVolumeNotifications()
	_wanted = True
	try:
		ev = core_audio.endpointVolume(None, core_audio.eRender)
		cb = _VolumeCallback()
		ev.RegisterControlChangeNotify(cb)
		_callback, _callbackVolume = cb, ev
		_callbackDevice = core_audio.getDefaultDeviceId(core_audio.eRender)
	except (comtypes.COMError, OSError):
		log.debug("No se pudieron registrar los avisos de volumen", exc_info=True)
	_scheduleDeviceWatch()


#: Dispositivo cuyo volumen se vigila y temporizador que comprueba si cambió
#: el predeterminado (auriculares conectados o desconectados): los avisos se
#: registran sobre un dispositivo concreto y dejaban de llegar.
_callbackDevice = ""
_wanted = False
_watchTimer: int | None = None
DEVICE_WATCH_MS = 5000


def _scheduleDeviceWatch() -> None:
	global _watchTimer
	if _watchTimer is None:
		_watchTimer = queue_handler.callLater(DEVICE_WATCH_MS, _watchDevice)


def _watchDevice() -> None:
	global _watchTimer
	_watchTimer = None
	if not _wanted:
		return
	try:
		current = core_audio.getDefaultDeviceId(core_audio.eRender)
	except Exception:
		current = ""
	# Otro dispositivo predeterminado, o el registro falló (servicio de audio
	# reiniciándose): se vuelve a registrar.
	if current and (current != _callbackDevice or _callback is None):
		log.debug("Cambió el dispositivo predeterminado: se registran de nuevo los avisos de volumen")
		startVolumeNotifications()
		return
	_scheduleDeviceWatch()


def stopVolumeNotifications() -> None:
	global _callback, _callbackVolume, _pendingReport, _watchTimer, _callbackDevice, _wanted
	_wanted = False
	if _callback is not None and _callbackVolume is not None:
		try:
			_callbackVolume.UnregisterControlChangeNotify(_callback)
		except (comtypes.COMError, OSError):
			pass
	_callback = _callbackVolume = None
	_callbackDevice = ""
	if _pendingReport is not None:
		queue_handler.cancelCallLater(_pendingReport)
		_pendingReport = None
	if _watchTimer is not None:
		queue_handler.cancelCallLater(_watchTimer)
		_watchTimer = None


# ---------------------------------------------------------------- tecla Silenciar (#6427)
_muteArmedUntil = 0.0


def handleMuteKey() -> str:
	"""Tecla Silenciar del teclado: con confirmación, la primera pulsación solo avisa."""
	global _muteArmedUntil
	import time

	_vol, muted = getMasterVolume()
	if muted or not conf["audio"]["confirmSystemMute"]:
		nowMuted = toggleMasterMute()
		_muteArmedUntil = 0.0
		return _("Sonido del sistema silenciado") if nowMuted else _("Sonido del sistema activado")
	now = time.monotonic()
	if now < _muteArmedUntil:
		_muteArmedUntil = 0.0
		setMasterMute(True)
		return _("Sonido del sistema silenciado")
	_muteArmedUntil = now + 3.0
	return _("Pulsa otra vez Silenciar para quitar el sonido del equipo")


def terminate() -> None:
	stopVolumeNotifications()
