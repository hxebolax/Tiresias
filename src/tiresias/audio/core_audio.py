"""Acceso a Core Audio (dispositivos, volumen y sesiones de audio).

Envuelve con comtypes las interfaces de Windows que usa Tiresias:

- ``IMMDeviceEnumerator``/``IMMDevice``: dispositivos de salida y entrada con
  su nombre completo (no los 31 caracteres de waveOut).
- ``IAudioEndpointVolume``: volumen general y silencio de un dispositivo
  (altavoces o micrófono).
- ``IAudioSessionManager2``: sesiones de audio de cada aplicación (volumen,
  silencio y balance; lo usan el mezclador, la división del sonido y la
  atenuación).
- ``IAudioClient``/``IAudioRenderClient``: salida WASAPI en modo compartido.
- ``IPolicyConfig`` (interfaz no documentada, presente desde Windows 7):
  cambiar el dispositivo predeterminado del sistema.

Todas las funciones crean sus objetos COM en el hilo que las llama, que debe
tener COM inicializado (el hilo del núcleo y los hilos de audio lo hacen).
"""

from __future__ import annotations

import ctypes
import os
import queue
import threading
from ctypes import HRESULT, POINTER, c_float, c_int, c_longlong, c_uint, c_void_p
from ctypes.wintypes import BOOL, DWORD, LPCWSTR, WORD

import comtypes
import comtypes.client
from comtypes import COMMETHOD, GUID, IUnknown

from ..log import getLogger

log = getLogger("coreAudio")

CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
CLSID_PolicyConfigClient = GUID("{870af99c-171d-4f9e-af0d-e63df40c2bc9}")

# EDataFlow
eRender = 0
eCapture = 1
eAll = 2
# ERole
eConsole = 0
eMultimedia = 1
eCommunications = 2

DEVICE_STATE_ACTIVE = 0x1
CLSCTX_ALL = 23
STGM_READ = 0
VT_LPWSTR = 31

ole32 = ctypes.WinDLL("ole32")
ole32.PropVariantClear.argtypes = [c_void_p]
ole32.CoTaskMemFree.argtypes = [c_void_p]


def takeString(ptr) -> str:
	"""Lee y libera una cadena que Core Audio reserva con CoTaskMemAlloc.

	Las salidas de cadena (``GetId``, ``GetDisplayName``,
	``GetSessionIdentifier``...) se declaran como punteros: si se declaran como
	``LPWSTR``, comtypes copia el texto pero nunca libera la memoria, y como
	la atenuación y la división del sonido recorren las sesiones cada pocos
	segundos, se perdían cientos de megabytes al día.
	"""
	if not ptr:
		return ""
	try:
		return ctypes.wstring_at(ptr)
	finally:
		ole32.CoTaskMemFree(ptr)


def deviceId(device) -> str:
	"""Identificador de un ``IMMDevice`` (liberando la cadena)."""
	return takeString(device.GetId())


class PROPERTYKEY(ctypes.Structure):
	_fields_ = [("fmtid", GUID), ("pid", DWORD)]


class PROPVARIANT(ctypes.Structure):
	_fields_ = [
		("vt", ctypes.c_ushort),
		("reserved1", WORD),
		("reserved2", WORD),
		("reserved3", WORD),
		("data", c_void_p),
		("data2", c_void_p),
	]


def _pkey(fmtid: str, pid: int) -> PROPERTYKEY:
	k = PROPERTYKEY()
	k.fmtid = GUID(fmtid)
	k.pid = pid
	return k


#: Nombre completo del dispositivo («Altavoces (Realtek High Definition Audio)»).
PKEY_Device_FriendlyName = _pkey("{a45c254e-df1c-4efd-8020-67d146a850e0}", 14)
#: Descripción corta («Altavoces»).
PKEY_Device_DeviceDesc = _pkey("{a45c254e-df1c-4efd-8020-67d146a850e0}", 2)


class WAVEFORMATEX(ctypes.Structure):
	_fields_ = [
		("wFormatTag", WORD),
		("nChannels", WORD),
		("nSamplesPerSec", DWORD),
		("nAvgBytesPerSec", DWORD),
		("nBlockAlign", WORD),
		("wBitsPerSample", WORD),
		("cbSize", WORD),
	]


# ---------------------------------------------------------------- interfaces
class IAudioSessionControl(IUnknown):
	_iid_ = GUID("{F4B1A599-7266-4319-A8CA-E70ACB11E8CD}")
	_methods_ = [
		COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(c_int), "pRetVal")),
		COMMETHOD([], HRESULT, "GetDisplayName", (["out"], POINTER(c_void_p),"pRetVal")),
		COMMETHOD([], HRESULT, "SetDisplayName", (["in"], LPCWSTR, "Value"), (["in"], POINTER(GUID), "EventContext")),
		COMMETHOD([], HRESULT, "GetIconPath", (["out"], POINTER(c_void_p),"pRetVal")),
		COMMETHOD([], HRESULT, "SetIconPath", (["in"], LPCWSTR, "Value"), (["in"], POINTER(GUID), "EventContext")),
		COMMETHOD([], HRESULT, "GetGroupingParam", (["out"], POINTER(GUID), "pRetVal")),
		COMMETHOD([], HRESULT, "SetGroupingParam", (["in"], POINTER(GUID), "Override"), (["in"], POINTER(GUID), "EventContext")),
		COMMETHOD([], HRESULT, "RegisterAudioSessionNotification", (["in"], POINTER(IUnknown), "NewNotifications")),
		COMMETHOD([], HRESULT, "UnregisterAudioSessionNotification", (["in"], POINTER(IUnknown), "NewNotifications")),
	]


class IAudioSessionControl2(IAudioSessionControl):
	_iid_ = GUID("{bfb7ff88-7239-4fc9-8fa2-07c950be9c6d}")
	_methods_ = [
		COMMETHOD([], HRESULT, "GetSessionIdentifier", (["out"], POINTER(c_void_p),"pRetVal")),
		COMMETHOD([], HRESULT, "GetSessionInstanceIdentifier", (["out"], POINTER(c_void_p),"pRetVal")),
		COMMETHOD([], HRESULT, "GetProcessId", (["out"], POINTER(DWORD), "pRetVal")),
		COMMETHOD([], HRESULT, "IsSystemSoundsSession"),
		COMMETHOD([], HRESULT, "SetDuckingPreference", (["in"], BOOL, "optOut")),
	]


class ISimpleAudioVolume(IUnknown):
	_iid_ = GUID("{87CE5498-68D6-44E5-9215-6DA47EF883D8}")
	_methods_ = [
		COMMETHOD([], HRESULT, "SetMasterVolume", (["in"], c_float, "fLevel"), (["in"], POINTER(GUID), "EventContext")),
		COMMETHOD([], HRESULT, "GetMasterVolume", (["out"], POINTER(c_float), "pfLevel")),
		COMMETHOD([], HRESULT, "SetMute", (["in"], BOOL, "bMute"), (["in"], POINTER(GUID), "EventContext")),
		COMMETHOD([], HRESULT, "GetMute", (["out"], POINTER(BOOL), "pbMute")),
	]


class IChannelAudioVolume(IUnknown):
	_iid_ = GUID("{1C158861-B533-4B30-B1CF-E853E51C59B8}")
	_methods_ = [
		COMMETHOD([], HRESULT, "GetChannelCount", (["out"], POINTER(c_uint), "pdwCount")),
		COMMETHOD([], HRESULT, "SetChannelVolume", (["in"], c_uint, "dwIndex"), (["in"], c_float, "fLevel"), (["in"], POINTER(GUID), "EventContext")),
		COMMETHOD([], HRESULT, "GetChannelVolume", (["in"], c_uint, "dwIndex"), (["out"], POINTER(c_float), "pfLevel")),
		COMMETHOD([], HRESULT, "SetAllVolumes", (["in"], c_uint, "dwCount"), (["in"], POINTER(c_float), "pfVolumes"), (["in"], POINTER(GUID), "EventContext")),
		COMMETHOD([], HRESULT, "GetAllVolumes", (["in"], c_uint, "dwCount"), (["out"], POINTER(c_float), "pfVolumes")),
	]


class IAudioSessionEnumerator(IUnknown):
	_iid_ = GUID("{E2F5BB11-0570-40CA-ACDD-3AA01277DEE8}")
	_methods_ = [
		COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(c_int), "SessionCount")),
		COMMETHOD([], HRESULT, "GetSession", (["in"], c_int, "SessionCount"), (["out"], POINTER(POINTER(IAudioSessionControl)), "Session")),
	]


class IAudioSessionManager(IUnknown):
	_iid_ = GUID("{BFA971F1-4D5E-40BB-935E-967039BFBEE4}")
	_methods_ = [
		COMMETHOD([], HRESULT, "GetAudioSessionControl", (["in"], POINTER(GUID), "AudioSessionGuid"), (["in"], DWORD, "StreamFlags"), (["out"], POINTER(POINTER(IAudioSessionControl)), "SessionControl")),
		COMMETHOD([], HRESULT, "GetSimpleAudioVolume", (["in"], POINTER(GUID), "AudioSessionGuid"), (["in"], DWORD, "StreamFlags"), (["out"], POINTER(POINTER(ISimpleAudioVolume)), "AudioVolume")),
	]


class IAudioSessionManager2(IAudioSessionManager):
	_iid_ = GUID("{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}")
	_methods_ = [
		COMMETHOD([], HRESULT, "GetSessionEnumerator", (["out"], POINTER(POINTER(IAudioSessionEnumerator)), "SessionEnum")),
		COMMETHOD([], HRESULT, "RegisterSessionNotification", (["in"], POINTER(IUnknown), "SessionNotification")),
		COMMETHOD([], HRESULT, "UnregisterSessionNotification", (["in"], POINTER(IUnknown), "SessionNotification")),
		COMMETHOD([], HRESULT, "RegisterDuckNotification", (["in"], LPCWSTR, "sessionID"), (["in"], POINTER(IUnknown), "duckNotification")),
		COMMETHOD([], HRESULT, "UnregisterDuckNotification", (["in"], POINTER(IUnknown), "duckNotification")),
	]


class IAudioEndpointVolume(IUnknown):
	_iid_ = GUID("{5CDF2C82-841E-4546-9722-0CF74078229A}")
	_methods_ = [
		COMMETHOD([], HRESULT, "RegisterControlChangeNotify", (["in"], POINTER(IUnknown), "pNotify")),
		COMMETHOD([], HRESULT, "UnregisterControlChangeNotify", (["in"], POINTER(IUnknown), "pNotify")),
		COMMETHOD([], HRESULT, "GetChannelCount", (["out"], POINTER(c_uint), "pnChannelCount")),
		COMMETHOD([], HRESULT, "SetMasterVolumeLevel", (["in"], c_float, "fLevelDB"), (["in"], POINTER(GUID), "pguidEventContext")),
		COMMETHOD([], HRESULT, "SetMasterVolumeLevelScalar", (["in"], c_float, "fLevel"), (["in"], POINTER(GUID), "pguidEventContext")),
		COMMETHOD([], HRESULT, "GetMasterVolumeLevel", (["out"], POINTER(c_float), "pfLevelDB")),
		COMMETHOD([], HRESULT, "GetMasterVolumeLevelScalar", (["out"], POINTER(c_float), "pfLevel")),
		COMMETHOD([], HRESULT, "SetChannelVolumeLevel", (["in"], c_uint, "nChannel"), (["in"], c_float, "fLevelDB"), (["in"], POINTER(GUID), "pguidEventContext")),
		COMMETHOD([], HRESULT, "SetChannelVolumeLevelScalar", (["in"], c_uint, "nChannel"), (["in"], c_float, "fLevel"), (["in"], POINTER(GUID), "pguidEventContext")),
		COMMETHOD([], HRESULT, "GetChannelVolumeLevel", (["in"], c_uint, "nChannel"), (["out"], POINTER(c_float), "pfLevelDB")),
		COMMETHOD([], HRESULT, "GetChannelVolumeLevelScalar", (["in"], c_uint, "nChannel"), (["out"], POINTER(c_float), "pfLevel")),
		COMMETHOD([], HRESULT, "SetMute", (["in"], BOOL, "bMute"), (["in"], POINTER(GUID), "pguidEventContext")),
		COMMETHOD([], HRESULT, "GetMute", (["out"], POINTER(BOOL), "pbMute")),
		COMMETHOD([], HRESULT, "GetVolumeStepInfo", (["out"], POINTER(c_uint), "pnStep"), (["out"], POINTER(c_uint), "pnStepCount")),
		COMMETHOD([], HRESULT, "VolumeStepUp", (["in"], POINTER(GUID), "pguidEventContext")),
		COMMETHOD([], HRESULT, "VolumeStepDown", (["in"], POINTER(GUID), "pguidEventContext")),
		COMMETHOD([], HRESULT, "QueryHardwareSupport", (["out"], POINTER(DWORD), "pdwHardwareSupportMask")),
		COMMETHOD([], HRESULT, "GetVolumeRange", (["out"], POINTER(c_float), "pflVolumeMindB"), (["out"], POINTER(c_float), "pflVolumeMaxdB"), (["out"], POINTER(c_float), "pflVolumeIncrementdB")),
	]


class IPropertyStore(IUnknown):
	_iid_ = GUID("{886d8eeb-8cf2-4446-8d02-cdba1dbdcf99}")
	_methods_ = [
		COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(DWORD), "cProps")),
		COMMETHOD([], HRESULT, "GetAt", (["in"], DWORD, "iProp"), (["out"], POINTER(PROPERTYKEY), "pkey")),
		COMMETHOD([], HRESULT, "GetValue", (["in"], POINTER(PROPERTYKEY), "key"), (["in"], POINTER(PROPVARIANT), "pv")),
		COMMETHOD([], HRESULT, "SetValue", (["in"], POINTER(PROPERTYKEY), "key"), (["in"], POINTER(PROPVARIANT), "propvar")),
		COMMETHOD([], HRESULT, "Commit"),
	]


class IMMDevice(IUnknown):
	_iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
	_methods_ = [
		COMMETHOD([], HRESULT, "Activate", (["in"], POINTER(GUID), "iid"), (["in"], DWORD, "dwClsCtx"), (["in"], c_void_p, "pActivationParams"), (["out"], POINTER(POINTER(IUnknown)), "ppInterface")),
		COMMETHOD([], HRESULT, "OpenPropertyStore", (["in"], DWORD, "stgmAccess"), (["out"], POINTER(POINTER(IPropertyStore)), "ppProperties")),
		COMMETHOD([], HRESULT, "GetId", (["out"], POINTER(c_void_p),"ppstrId")),
		COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(DWORD), "pdwState")),
	]


class IMMDeviceCollection(IUnknown):
	_iid_ = GUID("{0BD7A1BE-7A1A-44DB-8397-CC5392387B5E}")
	_methods_ = [
		COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(c_uint), "pcDevices")),
		COMMETHOD([], HRESULT, "Item", (["in"], c_uint, "nDevice"), (["out"], POINTER(POINTER(IMMDevice)), "ppDevice")),
	]


class IMMDeviceEnumerator(IUnknown):
	_iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
	_methods_ = [
		COMMETHOD([], HRESULT, "EnumAudioEndpoints", (["in"], c_int, "dataFlow"), (["in"], DWORD, "dwStateMask"), (["out"], POINTER(POINTER(IMMDeviceCollection)), "ppDevices")),
		COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint", (["in"], c_int, "dataFlow"), (["in"], c_int, "role"), (["out"], POINTER(POINTER(IMMDevice)), "ppEndpoint")),
		COMMETHOD([], HRESULT, "GetDevice", (["in"], LPCWSTR, "pwstrId"), (["out"], POINTER(POINTER(IMMDevice)), "ppDevice")),
		COMMETHOD([], HRESULT, "RegisterEndpointNotificationCallback", (["in"], POINTER(IUnknown), "pClient")),
		COMMETHOD([], HRESULT, "UnregisterEndpointNotificationCallback", (["in"], POINTER(IUnknown), "pClient")),
	]


class IAudioClient(IUnknown):
	_iid_ = GUID("{1CB9AD4C-DBFA-4c32-B178-C2F568A703B2}")
	_methods_ = [
		COMMETHOD([], HRESULT, "Initialize", (["in"], c_int, "ShareMode"), (["in"], DWORD, "StreamFlags"), (["in"], c_longlong, "hnsBufferDuration"), (["in"], c_longlong, "hnsPeriodicity"), (["in"], POINTER(WAVEFORMATEX), "pFormat"), (["in"], POINTER(GUID), "AudioSessionGuid")),
		COMMETHOD([], HRESULT, "GetBufferSize", (["out"], POINTER(c_uint), "pNumBufferFrames")),
		COMMETHOD([], HRESULT, "GetStreamLatency", (["out"], POINTER(c_longlong), "phnsLatency")),
		COMMETHOD([], HRESULT, "GetCurrentPadding", (["out"], POINTER(c_uint), "pNumPaddingFrames")),
		COMMETHOD([], HRESULT, "IsFormatSupported", (["in"], c_int, "ShareMode"), (["in"], POINTER(WAVEFORMATEX), "pFormat"), (["out"], POINTER(POINTER(WAVEFORMATEX)), "ppClosestMatch")),
		COMMETHOD([], HRESULT, "GetMixFormat", (["out"], POINTER(POINTER(WAVEFORMATEX)), "ppDeviceFormat")),
		COMMETHOD([], HRESULT, "GetDevicePeriod", (["out"], POINTER(c_longlong), "phnsDefaultDevicePeriod"), (["out"], POINTER(c_longlong), "phnsMinimumDevicePeriod")),
		COMMETHOD([], HRESULT, "Start"),
		COMMETHOD([], HRESULT, "Stop"),
		COMMETHOD([], HRESULT, "Reset"),
		COMMETHOD([], HRESULT, "SetEventHandle", (["in"], c_void_p, "eventHandle")),
		COMMETHOD([], HRESULT, "GetService", (["in"], POINTER(GUID), "riid"), (["out"], POINTER(POINTER(IUnknown)), "ppv")),
	]


class IAudioRenderClient(IUnknown):
	_iid_ = GUID("{F294ACFC-3146-4483-A7BF-ADDCA7C260E2}")
	_methods_ = [
		COMMETHOD([], HRESULT, "GetBuffer", (["in"], c_uint, "NumFramesRequested"), (["out"], POINTER(POINTER(ctypes.c_byte)), "ppData")),
		COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], c_uint, "NumFramesWritten"), (["in"], DWORD, "dwFlags")),
	]


class IPolicyConfig(IUnknown):
	"""Interfaz no documentada de Windows para el dispositivo predeterminado.

	Solo se usa ``SetDefaultEndpoint``; los métodos anteriores se declaran
	para respetar el orden de la tabla virtual.
	"""

	_iid_ = GUID("{f8679f50-850a-41cf-9c72-430f290290c8}")
	_methods_ = [
		COMMETHOD([], HRESULT, "GetMixFormat", (["in"], LPCWSTR, "a"), (["in"], c_void_p, "b")),
		COMMETHOD([], HRESULT, "GetDeviceFormat", (["in"], LPCWSTR, "a"), (["in"], c_int, "b"), (["in"], c_void_p, "c")),
		COMMETHOD([], HRESULT, "ResetDeviceFormat", (["in"], LPCWSTR, "a")),
		COMMETHOD([], HRESULT, "SetDeviceFormat", (["in"], LPCWSTR, "a"), (["in"], c_void_p, "b"), (["in"], c_void_p, "c")),
		COMMETHOD([], HRESULT, "GetProcessingPeriod", (["in"], LPCWSTR, "a"), (["in"], c_int, "b"), (["in"], c_void_p, "c"), (["in"], c_void_p, "d")),
		COMMETHOD([], HRESULT, "SetProcessingPeriod", (["in"], LPCWSTR, "a"), (["in"], c_void_p, "b")),
		COMMETHOD([], HRESULT, "GetShareMode", (["in"], LPCWSTR, "a"), (["in"], c_void_p, "b")),
		COMMETHOD([], HRESULT, "SetShareMode", (["in"], LPCWSTR, "a"), (["in"], c_void_p, "b")),
		COMMETHOD([], HRESULT, "GetPropertyValue", (["in"], LPCWSTR, "a"), (["in"], c_void_p, "b"), (["in"], c_void_p, "c")),
		COMMETHOD([], HRESULT, "SetPropertyValue", (["in"], LPCWSTR, "a"), (["in"], c_void_p, "b"), (["in"], c_void_p, "c")),
		COMMETHOD([], HRESULT, "SetDefaultEndpoint", (["in"], LPCWSTR, "wszDeviceId"), (["in"], c_int, "eRole")),
		COMMETHOD([], HRESULT, "SetEndpointVisibility", (["in"], LPCWSTR, "a"), (["in"], c_int, "b")),
	]


OWN_PID = os.getpid()


# ---------------------------------------------------------------- utilidades
def ensureCom() -> None:
	"""Inicializa COM (multihilo) en el hilo actual si aún no lo está."""
	try:
		comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
	except OSError:
		# Ya inicializado (quizá como STA): sirve igualmente.
		pass


def _enumerator() -> IMMDeviceEnumerator:
	return comtypes.client.CreateObject(CLSID_MMDeviceEnumerator, interface=IMMDeviceEnumerator)


def _deviceName(device: IMMDevice) -> str:
	try:
		store = device.OpenPropertyStore(STGM_READ)
		pv = PROPVARIANT()
		store.GetValue(ctypes.byref(PKEY_Device_FriendlyName), ctypes.byref(pv))
		try:
			if pv.vt == VT_LPWSTR and pv.data:
				return ctypes.wstring_at(pv.data)
		finally:
			ole32.PropVariantClear(ctypes.byref(pv))
	except (comtypes.COMError, OSError):
		log.debug("No se pudo leer el nombre del dispositivo", exc_info=True)
	return ""


class Device:
	"""Dispositivo de audio (punto final) con su identificador y nombre completo."""

	def __init__(self, id: str, name: str, flow: int, isDefault: bool = False) -> None:
		self.id = id
		self.name = name
		self.flow = flow
		self.isDefault = isDefault

	def __repr__(self) -> str:
		return f"Device({self.name!r}, default={self.isDefault})"


def getDefaultDeviceId(flow: int = eRender, role: int = eConsole) -> str:
	try:
		return deviceId(_enumerator().GetDefaultAudioEndpoint(flow, role))
	except (comtypes.COMError, OSError):
		return ""


def getDevices(flow: int = eRender) -> list[Device]:
	"""Dispositivos activos de salida (``eRender``) o de entrada (``eCapture``)."""
	try:
		enum = _enumerator()
		coll = enum.EnumAudioEndpoints(flow, DEVICE_STATE_ACTIVE)
		count = coll.GetCount()
	except (comtypes.COMError, OSError):
		log.debug("No se pudieron enumerar los dispositivos", exc_info=True)
		return []
	default = getDefaultDeviceId(flow)
	out: list[Device] = []
	for i in range(count):
		try:
			dev = coll.Item(i)
			devId = deviceId(dev)
			out.append(Device(devId, _deviceName(dev) or devId, flow, devId == default))
		except comtypes.COMError:
			continue
	return out


def findDevice(name: str, flow: int = eRender) -> Device | None:
	"""Busca un dispositivo por su nombre completo.

	También acepta los nombres cortados a 31 caracteres que guardaban
	versiones anteriores (nombres de waveOut).
	"""
	if not name:
		return None
	devices = getDevices(flow)
	for d in devices:
		if d.name == name or d.id == name:
			return d
	if len(name) >= 31:
		for d in devices:
			if d.name.startswith(name):
				return d
	return None


def getIMMDevice(deviceId: str | None, flow: int = eRender, role: int = eConsole) -> IMMDevice:
	enum = _enumerator()
	if deviceId:
		return enum.GetDevice(deviceId)
	return enum.GetDefaultAudioEndpoint(flow, role)


def endpointVolume(deviceId: str | None = None, flow: int = eRender) -> IAudioEndpointVolume:
	dev = getIMMDevice(deviceId, flow)
	unk = dev.Activate(ctypes.byref(IAudioEndpointVolume._iid_), CLSCTX_ALL, None)
	return unk.QueryInterface(IAudioEndpointVolume)


def setDefaultDevice(deviceId: str) -> None:
	"""Hace que ``deviceId`` sea el dispositivo predeterminado del sistema (todas las funciones)."""
	policy = comtypes.client.CreateObject(CLSID_PolicyConfigClient, interface=IPolicyConfig)
	for role in (eConsole, eMultimedia, eCommunications):
		policy.SetDefaultEndpoint(deviceId, role)


# ---------------------------------------------------------------- hilo de sesiones
# Recorrer las sesiones de audio de todos los dispositivos puede tardar
# decenas de milisegundos (y más si un controlador va lento): la atenuación,
# la división del sonido y lo que se hace al abrir el primer flujo de audio
# lo hacen en este hilo propio, con COM inicializado, y nunca en el núcleo.
_sessionQueue: "queue.Queue" = queue.Queue()
_sessionThread: threading.Thread | None = None
_sessionThreadLock = threading.Lock()


def _sessionWorker() -> None:
	ensureCom()
	while True:
		func, args = _sessionQueue.get()
		try:
			func(*args)
		except Exception:
			log.exception("Error en el hilo de sesiones de audio")
		finally:
			_sessionQueue.task_done()


def runInSessionThread(func, *args) -> None:
	"""Ejecuta ``func(*args)`` en el hilo de sesiones de audio (en orden de llegada)."""
	global _sessionThread
	with _sessionThreadLock:
		if _sessionThread is None or not _sessionThread.is_alive():
			_sessionThread = threading.Thread(target=_sessionWorker, name="SesionesAudio", daemon=True)
			_sessionThread.start()
	_sessionQueue.put((func, args))


def waitSessionThread(timeout: float = 3.0) -> bool:
	"""Espera a que el hilo de sesiones termine lo pendiente (al cerrar y en pruebas)."""
	if threading.current_thread() is _sessionThread:
		return True
	done = threading.Event()
	runInSessionThread(done.set)
	return done.wait(timeout)


# ---------------------------------------------------------------- sesiones
class Session:
	def __init__(self, control2, pid: int, identifier: str, deviceId: str = "", sessionIdentifier: str = "") -> None:
		self.control2 = control2
		self.pid = pid
		#: Identificador de la instancia (incluye el PID: cambia al reiniciar la aplicación).
		self.identifier = identifier
		#: Identificador estable de la sesión (aplicación y dispositivo, sin PID):
		#: es la clave con la que Windows recuerda el volumen y el balance.
		self.sessionIdentifier = sessionIdentifier or identifier
		self.deviceId = deviceId

	def simpleVolume(self) -> ISimpleAudioVolume:
		return self.control2.QueryInterface(ISimpleAudioVolume)

	def channelVolume(self) -> IChannelAudioVolume:
		return self.control2.QueryInterface(IChannelAudioVolume)

	def displayName(self) -> str:
		try:
			return takeString(self.control2.GetDisplayName())
		except comtypes.COMError:
			return ""

	def isSystemSounds(self) -> bool:
		try:
			# S_OK (0) si es la sesión de los sonidos del sistema; S_FALSE (1) si no.
			return self.control2.IsSystemSoundsSession() == 0
		except comtypes.COMError:
			return False

	def state(self) -> int:
		"""0 inactiva, 1 activa, 2 caducada."""
		try:
			return int(self.control2.GetState())
		except comtypes.COMError:
			return 2


def _sessionsOf(device: IMMDevice, deviceId: str = "") -> list[Session]:
	try:
		unk = device.Activate(ctypes.byref(IAudioSessionManager2._iid_), CLSCTX_ALL, None)
		manager = unk.QueryInterface(IAudioSessionManager2)
		sessionEnum = manager.GetSessionEnumerator()
		count = sessionEnum.GetCount()
	except (comtypes.COMError, OSError):
		log.debug("Core Audio no disponible", exc_info=True)
		return []
	out = []
	for i in range(count):
		try:
			ctl = sessionEnum.GetSession(i)
			ctl2 = ctl.QueryInterface(IAudioSessionControl2)
			pid = ctl2.GetProcessId()
			ident = takeString(ctl2.GetSessionInstanceIdentifier())
			try:
				stable = takeString(ctl2.GetSessionIdentifier())
			except comtypes.COMError:
				stable = ""
			out.append(Session(ctl2, pid, ident, deviceId, stable))
		except comtypes.COMError:
			continue
	return out


def getSessions(allDevices: bool = False) -> list[Session]:
	"""Sesiones de audio del dispositivo de salida por defecto (o de todos)."""
	try:
		enumerator = _enumerator()
		if not allDevices:
			device = enumerator.GetDefaultAudioEndpoint(eRender, eMultimedia)
			return _sessionsOf(device, deviceId(device))
		coll = enumerator.EnumAudioEndpoints(eRender, DEVICE_STATE_ACTIVE)
		count = coll.GetCount()
	except (comtypes.COMError, OSError):
		log.debug("Core Audio no disponible", exc_info=True)
		return []
	out: list[Session] = []
	for i in range(count):
		try:
			dev = coll.Item(i)
			out.extend(_sessionsOf(dev, deviceId(dev)))
		except comtypes.COMError:
			continue
	return out
