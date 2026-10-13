"""Acceso a la red inalámbrica (API «Native Wifi» de Windows, ``wlanapi.dll``).

- :class:`WlanClient` abre una sesión con el servicio de configuración
  automática de WLAN, informa de la red conectada (nombre, intensidad de la
  señal y tipo de seguridad) y avisa de las conexiones, desconexiones y de
  los adaptadores que se activan o desactivan.
- Las versiones de Windows Server anteriores a 2025 no traen ``wlanapi.dll``:
  entonces :data:`available` es ``False`` y se informa de que no hay
  dispositivos inalámbricos.

Las notificaciones llegan en un hilo del sistema; ``onEvent(tipo, ssid)`` se
llama en ese hilo y el complemento las pasa al núcleo con la cola.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable

from tiresias.log import getLogger

log = getLogger("resourceMonitor.wlan")

try:
	_dll = ctypes.WinDLL("wlanapi.dll")
	available = True
except OSError:
	_dll = None
	available = False

ERROR_SUCCESS = 0
CLIENT_VERSION_WINDOWS_VISTA_OR_LATER = 2

WLAN_NOTIFICATION_SOURCE_NONE = 0
WLAN_NOTIFICATION_SOURCE_ACM = 0x00000008
wlan_notification_acm_connection_complete = 0x0000000A
wlan_notification_acm_interface_arrival = 0x0000000D
wlan_notification_acm_interface_removal = 0x0000000E
wlan_notification_acm_disconnected = 0x00000015

WLAN_AVAILABLE_NETWORK_CONNECTED = 1
wlan_interface_state_connected = 1
wlan_intf_opcode_current_connection = 7

DOT11_AUTH_ALGO_80211_OPEN = 1
DOT11_AUTH_ALGO_80211_SHARED_KEY = 2
DOT11_AUTH_ALGO_WPA = 3
DOT11_AUTH_ALGO_WPA_PSK = 4
DOT11_AUTH_ALGO_WPA_NONE = 5
DOT11_AUTH_ALGO_RSNA = 6
DOT11_AUTH_ALGO_RSNA_PSK = 7
DOT11_AUTH_ALGO_WPA3_ENT_192 = 8
DOT11_AUTH_ALGO_WPA3_SAE = 9
DOT11_AUTH_ALGO_OWE = 10
DOT11_AUTH_ALGO_WPA3_ENT = 11

SECURITY_TYPE = {
	DOT11_AUTH_ALGO_80211_OPEN: "sin autenticación (abierta)",
	DOT11_AUTH_ALGO_80211_SHARED_KEY: "WEP",
	DOT11_AUTH_ALGO_WPA: "WPA-Enterprise",
	DOT11_AUTH_ALGO_WPA_PSK: "WPA-PSK",
	DOT11_AUTH_ALGO_WPA_NONE: "WPA-None",
	DOT11_AUTH_ALGO_RSNA: "WPA2-Enterprise",
	DOT11_AUTH_ALGO_RSNA_PSK: "WPA2-PSK",
	DOT11_AUTH_ALGO_WPA3_ENT_192: "WPA3-Enterprise-192bit",
	DOT11_AUTH_ALGO_WPA3_SAE: "WPA3-SAE",
	DOT11_AUTH_ALGO_OWE: "OWE",
	DOT11_AUTH_ALGO_WPA3_ENT: "WPA3-Enterprise",
}

#: Tipos de aviso que recibe ``onEvent``.
EVENT_CONNECTED = "connected"
EVENT_DISCONNECTED = "disconnected"
EVENT_INTERFACE_ARRIVAL = "arrival"
EVENT_INTERFACE_REMOVAL = "removal"


class GUID(ctypes.Structure):
	_fields_ = [
		("Data1", wintypes.DWORD),
		("Data2", wintypes.WORD),
		("Data3", wintypes.WORD),
		("Data4", ctypes.c_ubyte * 8),
	]


class DOT11_SSID(ctypes.Structure):
	_fields_ = [
		("SSIDLength", ctypes.c_ulong),
		("SSID", ctypes.c_ubyte * 32),
	]


class WLAN_CONNECTION_NOTIFICATION_DATA(ctypes.Structure):
	_fields_ = [
		("wlanConnectionMode", ctypes.c_uint),
		("strProfileName", ctypes.c_wchar * 256),
		("dot11Ssid", DOT11_SSID),
		("dot11BssType", ctypes.c_uint),
		("bSecurityEnabled", wintypes.BOOL),
		("wlanReasonCode", wintypes.DWORD),
		("dwFlags", wintypes.DWORD),
		("strProfileXml", ctypes.c_wchar * 1),
	]


class WLAN_NOTIFICATION_DATA(ctypes.Structure):
	_fields_ = [
		("NotificationSource", wintypes.DWORD),
		("NotificationCode", wintypes.DWORD),
		("InterfaceGuid", GUID),
		("dwDataSize", wintypes.DWORD),
		("pData", ctypes.c_void_p),
	]


class WLAN_AVAILABLE_NETWORK(ctypes.Structure):
	_fields_ = [
		("strProfileName", ctypes.c_wchar * 256),
		("dot11Ssid", DOT11_SSID),
		("dot11BssType", ctypes.c_uint),
		("uNumberOfBssids", ctypes.c_ulong),
		("bNetworkConnectable", wintypes.BOOL),
		("wlanNotConnectableReason", wintypes.DWORD),
		("uNumberOfPhyTypes", ctypes.c_ulong),
		("dot11PhyTypes", ctypes.c_uint * 8),
		("bMorePhyTypes", wintypes.BOOL),
		("wlanSignalQuality", ctypes.c_ulong),
		("bSecurityEnabled", wintypes.BOOL),
		("dot11DefaultAuthAlgorithm", ctypes.c_uint),
		("dot11DefaultCipherAlgorithm", ctypes.c_uint),
		("dwFlags", wintypes.DWORD),
		("dwReserved", wintypes.DWORD),
	]


class WLAN_AVAILABLE_NETWORK_LIST(ctypes.Structure):
	_fields_ = [
		("dwNumberOfItems", wintypes.DWORD),
		("dwIndex", wintypes.DWORD),
		("Network", WLAN_AVAILABLE_NETWORK * 1),
	]


class WLAN_INTERFACE_INFO(ctypes.Structure):
	_fields_ = [
		("InterfaceGuid", GUID),
		("strInterfaceDescription", ctypes.c_wchar * 256),
		("isState", ctypes.c_uint),
	]


class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
	_fields_ = [
		("dwNumberOfItems", wintypes.DWORD),
		("dwIndex", wintypes.DWORD),
		("InterfaceInfo", WLAN_INTERFACE_INFO * 1),
	]


class WLAN_ASSOCIATION_ATTRIBUTES(ctypes.Structure):
	_fields_ = [
		("dot11Ssid", DOT11_SSID),
		("dot11BssType", ctypes.c_uint),
		("dot11Bssid", ctypes.c_ubyte * 6),
		("dot11PhyType", ctypes.c_uint),
		("uDot11PhyIndex", ctypes.c_ulong),
		("wlanSignalQuality", ctypes.c_ulong),
		("ulRxRate", ctypes.c_ulong),
		("ulTxRate", ctypes.c_ulong),
	]


class WLAN_SECURITY_ATTRIBUTES(ctypes.Structure):
	_fields_ = [
		("bSecurityEnabled", wintypes.BOOL),
		("bOneXEnabled", wintypes.BOOL),
		("dot11AuthAlgorithm", ctypes.c_uint),
		("dot11CipherAlgorithm", ctypes.c_uint),
	]


class WLAN_CONNECTION_ATTRIBUTES(ctypes.Structure):
	_fields_ = [
		("isState", ctypes.c_uint),
		("wlanConnectionMode", ctypes.c_uint),
		("strProfileName", ctypes.c_wchar * 256),
		("wlanAssociationAttributes", WLAN_ASSOCIATION_ATTRIBUTES),
		("wlanSecurityAttributes", WLAN_SECURITY_ATTRIBUTES),
	]


WLAN_NOTIFICATION_CALLBACK = ctypes.WINFUNCTYPE(None, ctypes.POINTER(WLAN_NOTIFICATION_DATA), ctypes.c_void_p)

if _dll is not None:
	_dll.WlanOpenHandle.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.HANDLE)]
	_dll.WlanOpenHandle.restype = wintypes.DWORD
	_dll.WlanCloseHandle.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
	_dll.WlanCloseHandle.restype = wintypes.DWORD
	_dll.WlanEnumInterfaces.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(WLAN_INTERFACE_INFO_LIST))]
	_dll.WlanEnumInterfaces.restype = wintypes.DWORD
	_dll.WlanGetAvailableNetworkList.argtypes = [wintypes.HANDLE, ctypes.POINTER(GUID), wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(WLAN_AVAILABLE_NETWORK_LIST))]
	_dll.WlanGetAvailableNetworkList.restype = wintypes.DWORD
	_dll.WlanQueryInterface.argtypes = [wintypes.HANDLE, ctypes.POINTER(GUID), ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
	_dll.WlanQueryInterface.restype = wintypes.DWORD
	_dll.WlanFreeMemory.argtypes = [ctypes.c_void_p]
	_dll.WlanFreeMemory.restype = None
	_dll.WlanRegisterNotification.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, WLAN_NOTIFICATION_CALLBACK, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
	_dll.WlanRegisterNotification.restype = wintypes.DWORD


def _check(result: int) -> None:
	if result != ERROR_SUCCESS:
		raise ctypes.WinError(result)


def decodeSSID(ssid: DOT11_SSID) -> str:
	length = min(int(ssid.SSIDLength), 32)
	return bytes(ssid.SSID[:length]).decode("utf-8", errors="replace")


def _array(first, count: int):
	"""Vista de ``count`` elementos de una matriz de longitud variable (``X * 1``)."""
	return (first._type_ * count).from_address(ctypes.addressof(first))


NO_DEVICES = "No hay dispositivos de red inalámbrica"
NO_CONNECTIONS = "No hay conexiones de red inalámbrica"
ERROR_MESSAGE = "No se pudo obtener la información de la red inalámbrica"


def connectedText(ssid: str, quality: int, auth: int) -> str:
	return "Conectado a {ssid}, intensidad de la señal: {q}%, tipo de seguridad: {sec}".format(
		ssid=ssid, q=quality, sec=SECURITY_TYPE.get(auth, "desconocido")
	)


class WlanClient:
	"""Sesión con el servicio WLAN y avisos de conexión."""

	def __init__(self, onEvent: Callable[[str, str], None] | None = None) -> None:
		self.onEvent = onEvent
		self.handle: wintypes.HANDLE | None = None
		self._callback = WLAN_NOTIFICATION_CALLBACK(self._onNotification)
		self._registered = False

	# ------------------------------------------------------------ ciclo de vida
	def open(self) -> bool:
		if _dll is None:
			return False
		negotiated = wintypes.DWORD()
		handle = wintypes.HANDLE()
		try:
			_check(_dll.WlanOpenHandle(CLIENT_VERSION_WINDOWS_VISTA_OR_LATER, None, ctypes.byref(negotiated), ctypes.byref(handle)))
		except OSError:
			log.debug("No se pudo abrir el servicio WLAN", exc_info=True)
			return False
		self.handle = handle
		if self.onEvent is not None:
			try:
				_check(_dll.WlanRegisterNotification(handle, WLAN_NOTIFICATION_SOURCE_ACM, True, self._callback, None, None, None))
				self._registered = True
			except OSError:
				log.debug("No se pudieron registrar los avisos WLAN", exc_info=True)
		return True

	def close(self) -> None:
		handle = self.handle
		if not handle or _dll is None:
			return
		if self._registered:
			try:
				_check(_dll.WlanRegisterNotification(handle, WLAN_NOTIFICATION_SOURCE_NONE, True, self._callback, None, None, None))
			except OSError:
				pass
			self._registered = False
		try:
			_dll.WlanCloseHandle(handle, None)
		except OSError:
			pass
		self.handle = None

	@property
	def isOpen(self) -> bool:
		return bool(self.handle)

	# ------------------------------------------------------------ avisos
	def _onNotification(self, pData, pContext) -> None:
		try:
			event = self.translateNotification(pData.contents)
			if event is not None and self.onEvent is not None:
				self.onEvent(*event)
		except Exception:
			log.debug("Error en el aviso WLAN", exc_info=True)

	@staticmethod
	def translateNotification(data: WLAN_NOTIFICATION_DATA) -> tuple[str, str] | None:
		"""(tipo, ssid) de una notificación ACM, o ``None`` si no interesa."""
		if data.NotificationSource != WLAN_NOTIFICATION_SOURCE_ACM:
			return None
		code = data.NotificationCode
		if code in (wlan_notification_acm_connection_complete, wlan_notification_acm_disconnected):
			if not data.pData:
				return None
			info = WLAN_CONNECTION_NOTIFICATION_DATA.from_address(data.pData)
			if code == wlan_notification_acm_connection_complete:
				if info.wlanReasonCode != ERROR_SUCCESS:
					return None
				return EVENT_CONNECTED, decodeSSID(info.dot11Ssid)
			return EVENT_DISCONNECTED, decodeSSID(info.dot11Ssid)
		if code == wlan_notification_acm_interface_arrival:
			return EVENT_INTERFACE_ARRIVAL, ""
		if code == wlan_notification_acm_interface_removal:
			return EVENT_INTERFACE_REMOVAL, ""
		return None

	# ------------------------------------------------------------ información
	def _currentConnection(self, guid: GUID) -> str | None:
		size = wintypes.DWORD()
		data = ctypes.c_void_p()
		if _dll.WlanQueryInterface(self.handle, ctypes.byref(guid), wlan_intf_opcode_current_connection, None, ctypes.byref(size), ctypes.byref(data), None) != ERROR_SUCCESS:
			return None
		try:
			if not data.value:
				return None
			attrs = WLAN_CONNECTION_ATTRIBUTES.from_address(data.value)
			if attrs.isState != wlan_interface_state_connected:
				return None
			assoc = attrs.wlanAssociationAttributes
			return connectedText(decodeSSID(assoc.dot11Ssid), assoc.wlanSignalQuality, attrs.wlanSecurityAttributes.dot11AuthAlgorithm)
		finally:
			if data.value:
				_dll.WlanFreeMemory(data)

	def getInfo(self) -> str:
		"""Red conectada (nombre, intensidad y seguridad) o el motivo de que no haya."""
		if not self.handle or _dll is None:
			return NO_DEVICES
		ifaces = ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
		try:
			if _dll.WlanEnumInterfaces(self.handle, None, ctypes.byref(ifaces)) != ERROR_SUCCESS:
				return ERROR_MESSAGE
			count = ifaces.contents.dwNumberOfItems
			if count == 0:
				return NO_DEVICES
			info = NO_CONNECTIONS
			for iface in _array(ifaces.contents.InterfaceInfo, count):
				if iface.isState != wlan_interface_state_connected:
					continue
				networks = ctypes.POINTER(WLAN_AVAILABLE_NETWORK_LIST)()
				if _dll.WlanGetAvailableNetworkList(self.handle, ctypes.byref(iface.InterfaceGuid), 0, None, ctypes.byref(networks)) != ERROR_SUCCESS:
					current = self._currentConnection(iface.InterfaceGuid)
					if current:
						return current
					return ERROR_MESSAGE
				try:
					for net in _array(networks.contents.Network, networks.contents.dwNumberOfItems):
						if net.dwFlags & WLAN_AVAILABLE_NETWORK_CONNECTED:
							return connectedText(decodeSSID(net.dot11Ssid), net.wlanSignalQuality, net.dot11DefaultAuthAlgorithm)
				finally:
					if networks:
						_dll.WlanFreeMemory(networks)
				# La red conectada no estaba en la lista (p. ej. red oculta): se pregunta directamente.
				current = self._currentConnection(iface.InterfaceGuid)
				if current:
					return current
			return info
		finally:
			if ifaces:
				_dll.WlanFreeMemory(ifaces)
