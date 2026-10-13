"""Enumeración de dispositivos: USB, HID y puertos serie (incluido Bluetooth).

Las funciones devuelven :class:`DeviceInfo`, que es lo que la detección
automática compara con los identificadores de cada controlador.
"""

from __future__ import annotations

import ctypes
import re
import threading
import winreg
from ctypes import wintypes
from dataclasses import dataclass, field

from ...log import getLogger
from . import hwio

log = getLogger("braille.ports")

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
try:
	bthprops = ctypes.WinDLL("bthprops.cpl", use_last_error=True)
except OSError:
	bthprops = None

DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
SPDRP_HARDWAREID = 0x01
SPDRP_FRIENDLYNAME = 0x0C
SPDRP_DEVICEDESC = 0x00
DICS_FLAG_GLOBAL = 1
DIREG_DEV = 1
KEY_READ = 0x20019

#: Servicios Bluetooth en los identificadores de hardware de los dispositivos HID.
BT_HID_SERVICES = ("{00001124-0000-1000-8000-00805f9b34fb}", "{00001812-0000-1000-8000-00805f9b34fb}")


class GUID(ctypes.Structure):
	_fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

	@classmethod
	def fromString(cls, text: str) -> "GUID":
		text = text.strip("{}")
		a, b, c, d, e = text.split("-")
		tail = bytes.fromhex(d + e)
		return cls(int(a, 16), int(b, 16), int(c, 16), (ctypes.c_ubyte * 8)(*tail))


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
	_fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID), ("Flags", wintypes.DWORD), ("Reserved", ctypes.c_size_t)]


class SP_DEVINFO_DATA(ctypes.Structure):
	_fields_ = [("cbSize", wintypes.DWORD), ("ClassGuid", GUID), ("DevInst", wintypes.DWORD), ("Reserved", ctypes.c_size_t)]


class DEVPROPKEY(ctypes.Structure):
	_fields_ = [("fmtid", GUID), ("pid", wintypes.ULONG)]


class SYSTEMTIME(ctypes.Structure):
	_fields_ = [(n, wintypes.WORD) for n in ("wYear", "wMonth", "wDayOfWeek", "wDay", "wHour", "wMinute", "wSecond", "wMilliseconds")]


class BLUETOOTH_DEVICE_INFO(ctypes.Structure):
	_fields_ = [
		("dwSize", wintypes.DWORD),
		("Address", ctypes.c_ulonglong),
		("ulClassofDevice", wintypes.ULONG),
		("fConnected", wintypes.BOOL),
		("fRemembered", wintypes.BOOL),
		("fAuthenticated", wintypes.BOOL),
		("stLastSeen", SYSTEMTIME),
		("stLastUsed", SYSTEMTIME),
		("szName", wintypes.WCHAR * 248),
	]


setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [wintypes.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(SP_DEVINFO_DATA)]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
setupapi.SetupDiGetDeviceRegistryPropertyW.argtypes = [wintypes.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
setupapi.SetupDiGetDeviceRegistryPropertyW.restype = wintypes.BOOL
setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [wintypes.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA), wintypes.LPWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
setupapi.SetupDiGetDeviceInstanceIdW.restype = wintypes.BOOL
setupapi.SetupDiGetDevicePropertyW.argtypes = [wintypes.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA), ctypes.POINTER(DEVPROPKEY), ctypes.POINTER(wintypes.ULONG), ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
setupapi.SetupDiGetDevicePropertyW.restype = wintypes.BOOL
setupapi.SetupDiOpenDevRegKey.argtypes =[wintypes.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA), wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
setupapi.SetupDiOpenDevRegKey.restype = wintypes.HANDLE
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
advapi32.RegCloseKey.argtypes = [wintypes.HANDLE]
if bthprops is not None:
	bthprops.BluetoothGetDeviceInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(BLUETOOTH_DEVICE_INFO)]
	bthprops.BluetoothGetDeviceInfo.restype = wintypes.DWORD

GUID_DEVINTERFACE_USB_DEVICE = GUID.fromString("{A5DCBF10-6530-11D2-901F-00C04FB951ED}")
GUID_DEVINTERFACE_COMPORT = GUID.fromString("{86E0D1E0-8089-11D0-9CE4-08003E301F73}")
GUID_DEVINTERFACE_HID = GUID.fromString("{4D1E55B2-F16F-11CF-88CB-001111000030}")
#: Descripción del dispositivo que da el bus USB (la Caiku Albatross se reconoce por ella).
DEVPKEY_Device_BusReportedDeviceDesc = DEVPROPKEY(GUID.fromString("{540b947e-8b40-45bc-a8a2-6a0b894cbda2}"), 4)

_USB_ID = re.compile(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", re.I)
#: En los dispositivos HID Bluetooth: ``..._VID&0002xxxx_PID&yyyy``.
_BT_HID_ID = re.compile(r"_VID&[0-9A-F]{4}([0-9A-F]{4})_PID&([0-9A-F]{4})", re.I)


@dataclass
class DeviceInfo:
	"""Un dispositivo encontrado en el sistema."""

	#: ``"hid"``, ``"usb"`` (dispositivo USB, para bulk) o ``"serial"``.
	kind: str
	#: Ruta del dispositivo (HID, USB) o nombre del puerto (``COM3``).
	path: str
	#: ``VID_xxxx&PID_xxxx`` en mayúsculas o cadena vacía.
	usbId: str = ""
	bluetooth: bool = False
	bluetoothName: str = ""
	bluetoothAddress: int = 0
	friendlyName: str = ""
	hardwareId: str = ""
	product: str = ""
	manufacturer: str = ""
	usagePage: int = 0
	usage: int = 0
	extra: dict = field(default_factory=dict)

	def asInfo(self) -> dict:
		"""Diccionario para :attr:`Transport.info`."""
		return {
			"usbId": self.usbId,
			"bluetooth": self.bluetooth,
			"bluetoothName": self.bluetoothName,
			"friendlyName": self.friendlyName,
			"product": self.product,
			"usagePage": self.usagePage,
		}


def normalizeUsbId(text: str) -> str:
	m = _USB_ID.search(text or "")
	return f"VID_{m.group(1).upper()}&PID_{m.group(2).upper()}" if m else ""


def _iterInterfaces(guid: GUID):
	"""Rutas e información de los dispositivos presentes de una interfaz."""
	info = setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
	if not info or info == hwio.INVALID_HANDLE_VALUE:
		return
	try:
		for index in range(512):
			did = SP_DEVICE_INTERFACE_DATA()
			did.cbSize = ctypes.sizeof(did)
			if not setupapi.SetupDiEnumDeviceInterfaces(info, None, ctypes.byref(guid), index, ctypes.byref(did)):
				break
			size = wintypes.DWORD()
			setupapi.SetupDiGetDeviceInterfaceDetailW(info, ctypes.byref(did), None, 0, ctypes.byref(size), None)
			if not size.value:
				continue
			buf = ctypes.create_string_buffer(size.value + 2)
			# cbSize de SP_DEVICE_INTERFACE_DETAIL_DATA_W: 8 en 64 bits, 6 en 32.
			ctypes.memmove(buf, ctypes.byref(wintypes.DWORD(8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6)), 4)
			devinfo = SP_DEVINFO_DATA()
			devinfo.cbSize = ctypes.sizeof(devinfo)
			if not setupapi.SetupDiGetDeviceInterfaceDetailW(info, ctypes.byref(did), buf, size, None, ctypes.byref(devinfo)):
				continue
			path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
			yield info, devinfo, path
	finally:
		setupapi.SetupDiDestroyDeviceInfoList(info)


def _regProperty(info, devinfo, prop: int) -> str:
	buf = ctypes.create_unicode_buffer(1024)
	if setupapi.SetupDiGetDeviceRegistryPropertyW(info, ctypes.byref(devinfo), prop, None, buf, ctypes.sizeof(buf) - 2, None):
		return buf.value
	return ""


def _instanceId(info, devinfo) -> str:
	buf = ctypes.create_unicode_buffer(1024)
	if setupapi.SetupDiGetDeviceInstanceIdW(info, ctypes.byref(devinfo), buf, 1024, None):
		return buf.value
	return ""


def _busReportedDescription(info, devinfo) -> str:
	"""Descripción que da el bus USB para el dispositivo (cadena vacía si no hay)."""
	buf = ctypes.create_unicode_buffer(512)
	propType = wintypes.ULONG()
	try:
		if setupapi.SetupDiGetDevicePropertyW(info, ctypes.byref(devinfo), ctypes.byref(DEVPKEY_Device_BusReportedDeviceDesc), ctypes.byref(propType), buf, ctypes.sizeof(buf) - 2, None, 0):
			return buf.value
	except Exception:
		log.debug("No se pudo leer la descripción del bus", exc_info=True)
	return ""


def bluetoothName(address: int) -> str:
	"""Nombre de un dispositivo Bluetooth emparejado (cadena vacía si no se sabe)."""
	if bthprops is None or not address:
		return ""
	dev = BLUETOOTH_DEVICE_INFO()
	dev.dwSize = ctypes.sizeof(dev)
	dev.Address = address
	if bthprops.BluetoothGetDeviceInfo(None, ctypes.byref(dev)) != 0:
		return ""
	return dev.szName


def parseBluetoothAddress(text: str) -> int:
	"""Dirección Bluetooth de un ``Bluetooth_UniqueID`` o un identificador de instancia.

	Ejemplos: ``{...}#0012F3A1B2C3_C00000000`` o ``BTHENUM\\{...}\\8&2A&0&0012F3A1B2C3_C00000000``.
	"""
	m = re.search(r"[#&]([0-9A-F]{12})_", text or "", re.I)
	return int(m.group(1), 16) if m else 0


# ------------------------------------------------------------------- USB
def listUsbDevices() -> list[DeviceInfo]:
	out = []
	try:
		for info, devinfo, path in _iterInterfaces(GUID_DEVINTERFACE_USB_DEVICE):
			hwId = _regProperty(info, devinfo, SPDRP_HARDWAREID)
			usbId = normalizeUsbId(hwId) or normalizeUsbId(path)
			if not usbId:
				continue
			extra = {"instanceId": _instanceId(info, devinfo), "busReportedDeviceDescription": _busReportedDescription(info, devinfo)}
			out.append(DeviceInfo("usb", path, usbId=usbId, hardwareId=hwId, friendlyName=_regProperty(info, devinfo, SPDRP_DEVICEDESC), extra=extra))
	except Exception:
		log.debug("Error enumerando USB", exc_info=True)
	return out


# ------------------------------------------------------------------- HID
_hidCache: dict[str, dict] = {}
_hidLock = threading.Lock()


def _hidDetails(path: str) -> dict:
	"""Atributos de un HID (se guardan en caché: abrir dispositivos cuesta)."""
	with _hidLock:
		cached = _hidCache.get(path)
	if cached is not None:
		return cached
	details: dict = {}
	handle = hwio.kernel32.CreateFileW(path, 0, hwio.FILE_SHARE_READ | hwio.FILE_SHARE_WRITE, None, hwio.OPEN_EXISTING, 0, None)
	if not handle or handle == hwio.INVALID_HANDLE_VALUE:
		return details
	try:
		attrs = hwio.HIDD_ATTRIBUTES()
		attrs.Size = ctypes.sizeof(attrs)
		if hwio.hid.HidD_GetAttributes(handle, ctypes.byref(attrs)):
			details["vendorId"] = attrs.VendorID
			details["productId"] = attrs.ProductID
		buf = ctypes.create_unicode_buffer(128)
		if hwio.hid.HidD_GetProductString(handle, buf, ctypes.sizeof(buf)):
			details["product"] = buf.value
		if hwio.hid.HidD_GetManufacturerString(handle, buf, ctypes.sizeof(buf)):
			details["manufacturer"] = buf.value
		pd = ctypes.c_void_p()
		if hwio.hid.HidD_GetPreparsedData(handle, ctypes.byref(pd)):
			try:
				caps = hwio.HIDP_CAPS()
				if hwio.hid.HidP_GetCaps(pd, ctypes.byref(caps)) == hwio.HIDP_STATUS_SUCCESS:
					details["usagePage"] = caps.UsagePage
					details["usage"] = caps.Usage
			finally:
				hwio.hid.HidD_FreePreparsedData(pd)
	finally:
		hwio.kernel32.CloseHandle(handle)
	with _hidLock:
		_hidCache[path] = details
	return details


def listHidDevices() -> list[DeviceInfo]:
	out = []
	try:
		for info, devinfo, path in _iterInterfaces(GUID_DEVINTERFACE_HID):
			hwId = _regProperty(info, devinfo, SPDRP_HARDWAREID)
			low = (hwId + path).lower()
			isBt = any(s in low for s in BT_HID_SERVICES)
			details = _hidDetails(path)
			usbId = ""
			if "vendorId" in details:
				usbId = f"VID_{details['vendorId']:04X}&PID_{details['productId']:04X}"
			elif not isBt:
				usbId = normalizeUsbId(hwId) or normalizeUsbId(path)
			else:
				m = _BT_HID_ID.search(hwId)
				if m:
					usbId = f"VID_{m.group(1).upper()}&PID_{m.group(2).upper()}"
			product = details.get("product", "")
			out.append(
				DeviceInfo(
					"hid",
					path,
					usbId=usbId,
					bluetooth=isBt,
					bluetoothName=product if isBt else "",
					hardwareId=hwId,
					product=product,
					manufacturer=details.get("manufacturer", ""),
					usagePage=details.get("usagePage", 0),
					usage=details.get("usage", 0),
					friendlyName=product,
				)
			)
	except Exception:
		log.debug("Error enumerando HID", exc_info=True)
	return out


# ------------------------------------------------------------ puertos serie
def _portName(info, devinfo) -> tuple[str, str]:
	key = setupapi.SetupDiOpenDevRegKey(info, ctypes.byref(devinfo), DICS_FLAG_GLOBAL, 0, DIREG_DEV, KEY_READ)
	if not key or key == hwio.INVALID_HANDLE_VALUE:
		return "", ""
	try:
		port = unique = ""
		try:
			port = winreg.QueryValueEx(key, "PortName")[0]
		except OSError:
			pass
		try:
			unique = winreg.QueryValueEx(key, "Bluetooth_UniqueID")[0]
		except OSError:
			pass
		return port, unique
	finally:
		advapi32.RegCloseKey(key)


def listComPorts() -> list[DeviceInfo]:
	"""Puertos serie presentes, con su nombre Bluetooth si lo tienen."""
	out: list[DeviceInfo] = []
	seen: set[str] = set()
	try:
		for info, devinfo, path in _iterInterfaces(GUID_DEVINTERFACE_COMPORT):
			port, unique = _portName(info, devinfo)
			if not port or not port.upper().startswith("COM"):
				continue
			hwId = _regProperty(info, devinfo, SPDRP_HARDWAREID)
			friendly = _regProperty(info, devinfo, SPDRP_FRIENDLYNAME) or port
			dev = DeviceInfo("serial", port.upper(), hardwareId=hwId, friendlyName=friendly)
			upper = hwId.upper()
			if upper.startswith("BTHENUM\\"):
				dev.bluetooth = True
				dev.bluetoothAddress = parseBluetoothAddress(unique) or parseBluetoothAddress(_instanceId(info, devinfo))
				dev.bluetoothName = bluetoothName(dev.bluetoothAddress)
			else:
				instance = _instanceId(info, devinfo)
				dev.extra["instanceId"] = instance
				dev.usbId = normalizeUsbId(hwId)
				if not dev.usbId and "FTDIBUS" in upper:
					dev.usbId = normalizeUsbId(instance)
			seen.add(dev.path)
			out.append(dev)
	except Exception:
		log.debug("Error enumerando puertos COM", exc_info=True)
	# Puertos que no publican la interfaz COMPORT (algunos adaptadores antiguos).
	try:
		with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM") as key:
			i = 0
			while True:
				try:
					_name, value, _t = winreg.EnumValue(key, i)
				except OSError:
					break
				i += 1
				if isinstance(value, str) and value.upper() not in seen:
					seen.add(value.upper())
					out.append(DeviceInfo("serial", value.upper(), friendlyName=value.upper()))
	except OSError:
		pass
	out.sort(key=lambda d: int(re.sub(r"\D", "", d.path) or 0))
	return out


def listAll() -> list[DeviceInfo]:
	return listUsbDevices() + listHidDevices() + listComPorts()
