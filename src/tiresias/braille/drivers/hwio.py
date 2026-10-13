"""Entrada y salida de bajo nivel para las líneas braille (Win32 con ctypes).

Tres tipos de conexión, todos con E/S solapada y un hilo de lectura propio:

- :class:`SerialPort`: puertos serie (COM), incluidos los virtuales de USB y
  los de Bluetooth (perfil de puerto serie).
- :class:`HidDevice`: dispositivos HID (USB o Bluetooth).
- :class:`BulkDevice`: dispositivos USB con extremos «bulk» de un controlador
  del fabricante (Freedom Scientific, HIMS antiguos).

Cada conexión llama a ``onReceive(datos)`` desde su hilo de lectura con los
bytes que lleguen (un informe completo en HID; un trozo cualquiera del flujo
en serie y bulk) y a ``onError(código)`` una sola vez si la lectura o la
escritura fallan de forma definitiva (dispositivo desconectado).

:class:`MemoryTransport` imita una conexión en memoria para las pruebas.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

from ...log import getLogger

log = getLogger("braille.hwio")

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
hid = ctypes.WinDLL("hid", use_last_error=True)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 1
FILE_SHARE_WRITE = 2
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
ERROR_IO_PENDING = 997
ERROR_OPERATION_ABORTED = 995
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102
INFINITE = 0xFFFFFFFF
MAXDWORD = 0xFFFFFFFF
PURGE_TXCLEAR = 0x4
PURGE_RXCLEAR = 0x8
SETRTS = 3
CLRRTS = 4
SETDTR = 5
CLRDTR = 6

#: Tiempo máximo de una escritura (ms) antes de darla por fallida.
WRITE_TIMEOUT_MS = 3000
#: Escrituras fallidas seguidas que se consideran desconexión.
MAX_WRITE_FAILURES = 3


class OVERLAPPED(ctypes.Structure):
	_fields_ = [
		("Internal", ctypes.c_size_t),
		("InternalHigh", ctypes.c_size_t),
		("Offset", wintypes.DWORD),
		("OffsetHigh", wintypes.DWORD),
		("hEvent", wintypes.HANDLE),
	]


class DCB(ctypes.Structure):
	_fields_ = [
		("DCBlength", wintypes.DWORD),
		("BaudRate", wintypes.DWORD),
		("fBinary", wintypes.DWORD, 1),
		("fParity", wintypes.DWORD, 1),
		("fOutxCtsFlow", wintypes.DWORD, 1),
		("fOutxDsrFlow", wintypes.DWORD, 1),
		("fDtrControl", wintypes.DWORD, 2),
		("fDsrSensitivity", wintypes.DWORD, 1),
		("fTXContinueOnXoff", wintypes.DWORD, 1),
		("fOutX", wintypes.DWORD, 1),
		("fInX", wintypes.DWORD, 1),
		("fErrorChar", wintypes.DWORD, 1),
		("fNull", wintypes.DWORD, 1),
		("fRtsControl", wintypes.DWORD, 2),
		("fAbortOnError", wintypes.DWORD, 1),
		("fDummy2", wintypes.DWORD, 17),
		("wReserved", wintypes.WORD),
		("XonLim", wintypes.WORD),
		("XoffLim", wintypes.WORD),
		("ByteSize", ctypes.c_ubyte),
		("Parity", ctypes.c_ubyte),
		("StopBits", ctypes.c_ubyte),
		("XonChar", ctypes.c_char),
		("XoffChar", ctypes.c_char),
		("ErrorChar", ctypes.c_char),
		("EofChar", ctypes.c_char),
		("EvtChar", ctypes.c_char),
		("wReserved1", wintypes.WORD),
	]


class COMMTIMEOUTS(ctypes.Structure):
	_fields_ = [
		("ReadIntervalTimeout", wintypes.DWORD),
		("ReadTotalTimeoutMultiplier", wintypes.DWORD),
		("ReadTotalTimeoutConstant", wintypes.DWORD),
		("WriteTotalTimeoutMultiplier", wintypes.DWORD),
		("WriteTotalTimeoutConstant", wintypes.DWORD),
	]


class HIDP_CAPS(ctypes.Structure):
	_fields_ = [
		("Usage", wintypes.USHORT),
		("UsagePage", wintypes.USHORT),
		("InputReportByteLength", wintypes.USHORT),
		("OutputReportByteLength", wintypes.USHORT),
		("FeatureReportByteLength", wintypes.USHORT),
		("Reserved", wintypes.USHORT * 17),
		("NumberLinkCollectionNodes", wintypes.USHORT),
		("NumberInputButtonCaps", wintypes.USHORT),
		("NumberInputValueCaps", wintypes.USHORT),
		("NumberInputDataIndices", wintypes.USHORT),
		("NumberOutputButtonCaps", wintypes.USHORT),
		("NumberOutputValueCaps", wintypes.USHORT),
		("NumberOutputDataIndices", wintypes.USHORT),
		("NumberFeatureButtonCaps", wintypes.USHORT),
		("NumberFeatureValueCaps", wintypes.USHORT),
		("NumberFeatureDataIndices", wintypes.USHORT),
	]


class HIDD_ATTRIBUTES(ctypes.Structure):
	_fields_ = [("Size", wintypes.ULONG), ("VendorID", wintypes.USHORT), ("ProductID", wintypes.USHORT), ("VersionNumber", wintypes.USHORT)]


class _Range(ctypes.Structure):
	_fields_ = [
		("UsageMin", wintypes.USHORT),
		("UsageMax", wintypes.USHORT),
		("StringMin", wintypes.USHORT),
		("StringMax", wintypes.USHORT),
		("DesignatorMin", wintypes.USHORT),
		("DesignatorMax", wintypes.USHORT),
		("DataIndexMin", wintypes.USHORT),
		("DataIndexMax", wintypes.USHORT),
	]


class _NotRange(ctypes.Structure):
	_fields_ = [
		("Usage", wintypes.USHORT),
		("Reserved1", wintypes.USHORT),
		("StringIndex", wintypes.USHORT),
		("Reserved2", wintypes.USHORT),
		("DesignatorIndex", wintypes.USHORT),
		("Reserved3", wintypes.USHORT),
		("DataIndex", wintypes.USHORT),
		("Reserved4", wintypes.USHORT),
	]


class _RangeUnion(ctypes.Union):
	_fields_ = [("Range", _Range), ("NotRange", _NotRange)]


class HIDP_BUTTON_CAPS(ctypes.Structure):
	_anonymous_ = ("u",)
	_fields_ = [
		("UsagePage", wintypes.USHORT),
		("ReportID", ctypes.c_ubyte),
		("IsAlias", ctypes.c_ubyte),
		("BitField", wintypes.USHORT),
		("LinkCollection", wintypes.USHORT),
		("LinkUsage", wintypes.USHORT),
		("LinkUsagePage", wintypes.USHORT),
		("IsRange", ctypes.c_ubyte),
		("IsStringRange", ctypes.c_ubyte),
		("IsDesignatorRange", ctypes.c_ubyte),
		("IsAbsolute", ctypes.c_ubyte),
		("ReportCount", wintypes.USHORT),
		("Reserved2", wintypes.USHORT),
		("Reserved", wintypes.ULONG * 9),
		("u", _RangeUnion),
	]


class HIDP_VALUE_CAPS(ctypes.Structure):
	_anonymous_ = ("u",)
	_fields_ = [
		("UsagePage", wintypes.USHORT),
		("ReportID", ctypes.c_ubyte),
		("IsAlias", ctypes.c_ubyte),
		("BitField", wintypes.USHORT),
		("LinkCollection", wintypes.USHORT),
		("LinkUsage", wintypes.USHORT),
		("LinkUsagePage", wintypes.USHORT),
		("IsRange", ctypes.c_ubyte),
		("IsStringRange", ctypes.c_ubyte),
		("IsDesignatorRange", ctypes.c_ubyte),
		("IsAbsolute", ctypes.c_ubyte),
		("HasNull", ctypes.c_ubyte),
		("Reserved", ctypes.c_ubyte),
		("BitSize", wintypes.USHORT),
		("ReportCount", wintypes.USHORT),
		("Reserved2", wintypes.USHORT * 5),
		("UnitsExp", wintypes.ULONG),
		("Units", wintypes.ULONG),
		("LogicalMin", wintypes.LONG),
		("LogicalMax", wintypes.LONG),
		("PhysicalMin", wintypes.LONG),
		("PhysicalMax", wintypes.LONG),
		("u", _RangeUnion),
	]


class HIDP_DATA(ctypes.Structure):
	_fields_ = [("DataIndex", wintypes.USHORT), ("Reserved", wintypes.USHORT), ("RawValue", wintypes.ULONG)]


HidP_Input = 0
HidP_Output = 1
HIDP_STATUS_SUCCESS = 0x00110000

kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]
kernel32.ReadFile.restype = wintypes.BOOL
kernel32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]
kernel32.WriteFile.restype = wintypes.BOOL
kernel32.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED), ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
kernel32.GetOverlappedResult.restype = wintypes.BOOL
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.WaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL, wintypes.DWORD]
kernel32.WaitForMultipleObjects.restype = wintypes.DWORD
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.SetEvent.argtypes = [wintypes.HANDLE]
kernel32.ResetEvent.argtypes = [wintypes.HANDLE]
kernel32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED)]
kernel32.CancelIoEx.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.GetCommState.argtypes = [wintypes.HANDLE, ctypes.POINTER(DCB)]
kernel32.SetCommState.argtypes = [wintypes.HANDLE, ctypes.POINTER(DCB)]
kernel32.SetCommTimeouts.argtypes = [wintypes.HANDLE, ctypes.POINTER(COMMTIMEOUTS)]
kernel32.SetupComm.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
kernel32.PurgeComm.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.EscapeCommFunction.argtypes = [wintypes.HANDLE, wintypes.DWORD]
hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
hid.HidD_GetPreparsedData.restype = wintypes.BOOLEAN
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
hid.HidD_GetAttributes.restype = wintypes.BOOLEAN
hid.HidD_GetProductString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetProductString.restype = wintypes.BOOLEAN
hid.HidD_GetManufacturerString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetManufacturerString.restype = wintypes.BOOLEAN
hid.HidD_SetOutputReport.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_SetOutputReport.restype = wintypes.BOOLEAN
hid.HidD_GetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetFeature.restype = wintypes.BOOLEAN
hid.HidD_SetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_SetFeature.restype = wintypes.BOOLEAN
hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
hid.HidP_GetCaps.restype = wintypes.LONG
hid.HidP_GetButtonCaps.argtypes = [ctypes.c_int, ctypes.POINTER(HIDP_BUTTON_CAPS), ctypes.POINTER(wintypes.USHORT), ctypes.c_void_p]
hid.HidP_GetButtonCaps.restype = wintypes.LONG
hid.HidP_GetValueCaps.argtypes = [ctypes.c_int, ctypes.POINTER(HIDP_VALUE_CAPS), ctypes.POINTER(wintypes.USHORT), ctypes.c_void_p]
hid.HidP_GetValueCaps.restype = wintypes.LONG
hid.HidP_SetUsageValueArray.argtypes = [ctypes.c_int, wintypes.USHORT, wintypes.USHORT, wintypes.USHORT, ctypes.c_char_p, wintypes.USHORT, ctypes.c_void_p, ctypes.c_char_p, wintypes.ULONG]
hid.HidP_SetUsageValueArray.restype = wintypes.LONG
hid.HidP_GetData.argtypes = [ctypes.c_int, ctypes.POINTER(HIDP_DATA), ctypes.POINTER(wintypes.ULONG), ctypes.c_void_p, ctypes.c_char_p, wintypes.ULONG]
hid.HidP_GetData.restype = wintypes.LONG
hid.HidP_MaxDataListLength.argtypes = [ctypes.c_int, ctypes.c_void_p]
hid.HidP_MaxDataListLength.restype = wintypes.ULONG


class IoError(OSError):
	"""Error de E/S de una línea braille."""


def _winError(msg: str, code: int | None = None) -> IoError:
	code = ctypes.get_last_error() if code is None else code
	return IoError(code, f"{msg}: {ctypes.FormatError(code).strip()} ({code})")


def _openFile(path: str, access: int, share: int) -> int:
	handle = kernel32.CreateFileW(path, access, share, None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
	if not handle or handle == INVALID_HANDLE_VALUE:
		raise _winError(f"No se pudo abrir {path}")
	return handle


class Transport:
	"""Interfaz común de las conexiones (real o simulada)."""

	#: Tipo de conexión: ``"serial"``, ``"hid"``, ``"bulk"`` o ``"memory"``.
	kind = ""
	#: Ruta o puerto abierto.
	port = ""
	#: Datos del dispositivo (identificador USB, nombre Bluetooth...).
	info: dict = {}

	def write(self, data: bytes) -> None:
		raise NotImplementedError

	def close(self) -> None:
		raise NotImplementedError

	@property
	def isBluetooth(self) -> bool:
		return bool(self.info.get("bluetooth"))


class _OverlappedIo(Transport):
	"""Base de las conexiones Win32 con lectura en segundo plano."""

	def __init__(
		self,
		readHandle: int,
		writeHandle: int | None,
		readSize: int,
		onReceive: Callable[[bytes], None],
		onError: Callable[[int], None] | None,
		name: str,
	) -> None:
		self._readHandle = readHandle
		self._writeHandle = writeHandle if writeHandle is not None else readHandle
		self._readSize = max(1, readSize)
		self._onReceive = onReceive
		self._onError = onError
		self._stopEvent = kernel32.CreateEventW(None, True, False, None)
		self._writeEvent = kernel32.CreateEventW(None, True, False, None)
		self._writeLock = threading.Lock()
		self._closed = False
		self._errorReported = False
		self._writeFailures = 0
		self._thread = threading.Thread(target=self._readLoop, name=f"braille-{name}", daemon=True)

	def start(self) -> None:
		self._thread.start()

	# ------------------------------------------------------------- lectura
	def _readLoop(self) -> None:
		readEvent = kernel32.CreateEventW(None, True, False, None)
		handles = (wintypes.HANDLE * 2)(self._stopEvent, readEvent)
		buf = ctypes.create_string_buffer(self._readSize)
		try:
			while not self._closed:
				ov = OVERLAPPED()
				ov.hEvent = readEvent
				kernel32.ResetEvent(readEvent)
				count = wintypes.DWORD()
				ok = kernel32.ReadFile(self._readHandle, buf, self._readSize, ctypes.byref(count), ctypes.byref(ov))
				if not ok:
					err = ctypes.get_last_error()
					if err != ERROR_IO_PENDING:
						self._reportError(err, "lectura")
						return
					res = kernel32.WaitForMultipleObjects(2, handles, False, INFINITE)
					if res == WAIT_OBJECT_0 or self._closed:
						kernel32.CancelIoEx(self._readHandle, ctypes.byref(ov))
						kernel32.GetOverlappedResult(self._readHandle, ctypes.byref(ov), ctypes.byref(count), True)
						return
					if not kernel32.GetOverlappedResult(self._readHandle, ctypes.byref(ov), ctypes.byref(count), False):
						self._reportError(ctypes.get_last_error(), "lectura")
						return
				if count.value and not self._closed:
					data = buf.raw[: count.value]
					try:
						self._onReceive(data)
					except Exception:
						log.exception("Error procesando datos de la línea braille")
		finally:
			kernel32.CloseHandle(readEvent)

	def _reportError(self, code: int, what: str) -> None:
		if self._closed or self._errorReported:
			return
		self._errorReported = True
		log.info("Fallo de %s en la línea braille (%s): %s", what, self.port, ctypes.FormatError(code).strip())
		if self._onError is not None:
			try:
				self._onError(code)
			except Exception:
				log.exception("Error avisando de la desconexión")

	# ------------------------------------------------------------ escritura
	def _prepareWrite(self, data: bytes) -> bytes:
		return data

	def write(self, data: bytes) -> None:
		if self._closed:
			raise IoError(0, "Conexión cerrada")
		data = self._prepareWrite(bytes(data))
		try:
			with self._writeLock:
				buf = ctypes.create_string_buffer(data, len(data))
				ov = OVERLAPPED()
				ov.hEvent = self._writeEvent
				kernel32.ResetEvent(self._writeEvent)
				written = wintypes.DWORD()
				ok = kernel32.WriteFile(self._writeHandle, buf, len(data), ctypes.byref(written), ctypes.byref(ov))
				if not ok:
					err = ctypes.get_last_error()
					if err != ERROR_IO_PENDING:
						self._writeFailed(err)
					if kernel32.WaitForSingleObject(self._writeEvent, WRITE_TIMEOUT_MS) == WAIT_TIMEOUT:
						kernel32.CancelIoEx(self._writeHandle, ctypes.byref(ov))
						kernel32.GetOverlappedResult(self._writeHandle, ctypes.byref(ov), ctypes.byref(written), True)
						self._writeFailed(ERROR_OPERATION_ABORTED)
					if not kernel32.GetOverlappedResult(self._writeHandle, ctypes.byref(ov), ctypes.byref(written), False):
						self._writeFailed(ctypes.get_last_error())
				self._writeFailures = 0
		finally:
			# Fuera del cerrojo: el aviso cierra la conexión y el cierre toma
			# ese mismo cerrojo (no reentrante) en este hilo.
			self._flushWriteError()

	#: Error de escritura pendiente de avisar cuando se suelte el cerrojo.
	_pendingWriteError: int | None = None

	def _writeFailed(self, code: int) -> None:
		self._writeFailures += 1
		if self._writeFailures >= MAX_WRITE_FAILURES:
			self._pendingWriteError = code
		raise _winError("Error escribiendo en la línea braille", code)

	def _flushWriteError(self) -> None:
		code = self._pendingWriteError
		if code is not None:
			self._pendingWriteError = None
			self._reportError(code, "escritura")

	# --------------------------------------------------------------- cierre
	def close(self) -> None:
		if self._closed:
			return
		self._closed = True
		kernel32.SetEvent(self._stopEvent)
		if self._thread.is_alive() and self._thread is not threading.current_thread():
			self._thread.join(2)
		with self._writeLock:
			self._closeHandles()
			kernel32.CloseHandle(self._stopEvent)
			kernel32.CloseHandle(self._writeEvent)

	def _closeHandles(self) -> None:
		if self._writeHandle and self._writeHandle != self._readHandle:
			kernel32.CloseHandle(self._writeHandle)
		if self._readHandle:
			kernel32.CloseHandle(self._readHandle)
		self._readHandle = self._writeHandle = 0


# ======================================================================= serie
PARITY = {"N": 0, "O": 1, "E": 2, "M": 3, "S": 4}
STOPBITS = {1: 0, 1.5: 1, 2: 2}


class SerialPort(_OverlappedIo):
	"""Puerto serie (COMx) con E/S solapada.

	La lectura devuelve en cuanto llega cualquier byte, así que el flujo
	llega en trozos de tamaño variable que el protocolo debe reensamblar.
	"""

	kind = "serial"

	def __init__(
		self,
		port: str,
		baudrate: int,
		onReceive: Callable[[bytes], None],
		onError: Callable[[int], None] | None = None,
		parity: str = "N",
		byteSize: int = 8,
		stopBits: float = 1,
		rtscts: bool = False,
		dtr: bool = True,
		rts: bool = True,
		info: dict | None = None,
	) -> None:
		self.port = port
		self.info = info or {}
		path = port if port.startswith("\\\\") else "\\\\.\\" + port
		handle = _openFile(path, GENERIC_READ | GENERIC_WRITE, 0)
		try:
			kernel32.SetupComm(handle, 4096, 4096)
			self._handleForConfig = handle
			self._parity = parity
			self._byteSize = byteSize
			self._stopBits = stopBits
			self._rtscts = rtscts
			self._dtr = dtr
			self._rts = rts
			self._configure(baudrate)
			timeouts = COMMTIMEOUTS()
			# Devuelve en cuanto haya algún byte; si no llega nada, a los 500 ms.
			timeouts.ReadIntervalTimeout = MAXDWORD
			timeouts.ReadTotalTimeoutMultiplier = MAXDWORD
			timeouts.ReadTotalTimeoutConstant = 500
			timeouts.WriteTotalTimeoutConstant = WRITE_TIMEOUT_MS
			if not kernel32.SetCommTimeouts(handle, ctypes.byref(timeouts)):
				raise _winError("SetCommTimeouts")
			kernel32.PurgeComm(handle, PURGE_RXCLEAR | PURGE_TXCLEAR)
		except Exception:
			kernel32.CloseHandle(handle)
			raise
		super().__init__(handle, None, 4096, onReceive, onError, port)
		self.start()

	def _configure(self, baudrate: int) -> None:
		dcb = DCB()
		dcb.DCBlength = ctypes.sizeof(DCB)
		if not kernel32.GetCommState(self._handleForConfig, ctypes.byref(dcb)):
			raise _winError("GetCommState")
		dcb.BaudRate = baudrate
		dcb.fBinary = 1
		dcb.fParity = 1 if self._parity != "N" else 0
		dcb.fOutxCtsFlow = 1 if self._rtscts else 0
		dcb.fOutxDsrFlow = 0
		dcb.fDtrControl = 1 if self._dtr else 0
		dcb.fDsrSensitivity = 0
		dcb.fOutX = 0
		dcb.fInX = 0
		dcb.fNull = 0
		dcb.fErrorChar = 0
		dcb.fAbortOnError = 0
		dcb.fRtsControl = 2 if self._rtscts else (1 if self._rts else 0)
		dcb.ByteSize = self._byteSize
		dcb.Parity = PARITY[self._parity]
		dcb.StopBits = STOPBITS[self._stopBits]
		if not kernel32.SetCommState(self._handleForConfig, ctypes.byref(dcb)):
			raise _winError("SetCommState")
		self.baudrate = baudrate

	def setBaudRate(self, baudrate: int) -> None:
		with self._writeLock:
			self._configure(baudrate)

	def setDtr(self, on: bool) -> None:
		kernel32.EscapeCommFunction(self._readHandle, SETDTR if on else CLRDTR)

	def setRts(self, on: bool) -> None:
		kernel32.EscapeCommFunction(self._readHandle, SETRTS if on else CLRRTS)

	def purge(self) -> None:
		kernel32.PurgeComm(self._readHandle, PURGE_RXCLEAR | PURGE_TXCLEAR)


# ========================================================================= HID
def _hidCheck(status: int, what: str) -> None:
	if status != HIDP_STATUS_SUCCESS:
		raise IoError(status & 0xFFFFFFFF, f"{what}: estado HID {status & 0xFFFFFFFF:#x}")


class HidDevice(_OverlappedIo):
	"""Dispositivo HID abierto (USB o Bluetooth)."""

	kind = "hid"

	def __init__(
		self,
		path: str,
		onReceive: Callable[[bytes], None],
		onError: Callable[[int], None] | None = None,
		exclusive: bool = False,
		info: dict | None = None,
		start: bool = True,
	) -> None:
		self.port = path
		self.info = info or {}
		share = 0 if exclusive else FILE_SHARE_READ | FILE_SHARE_WRITE
		handle = _openFile(path, GENERIC_READ | GENERIC_WRITE, share)
		self._pd = ctypes.c_void_p()
		if not hid.HidD_GetPreparsedData(handle, ctypes.byref(self._pd)):
			kernel32.CloseHandle(handle)
			raise _winError("HidD_GetPreparsedData")
		self.caps = HIDP_CAPS()
		try:
			_hidCheck(hid.HidP_GetCaps(self._pd, ctypes.byref(self.caps)), "HidP_GetCaps")
		except IoError:
			hid.HidD_FreePreparsedData(self._pd)
			kernel32.CloseHandle(handle)
			raise
		self.usagePage = self.caps.UsagePage
		self.usage = self.caps.Usage
		self.inputSize = self.caps.InputReportByteLength
		self.outputSize = self.caps.OutputReportByteLength
		self.featureSize = self.caps.FeatureReportByteLength
		attrs = HIDD_ATTRIBUTES()
		attrs.Size = ctypes.sizeof(attrs)
		if hid.HidD_GetAttributes(handle, ctypes.byref(attrs)):
			self.vendorId, self.productId = attrs.VendorID, attrs.ProductID
		else:
			self.vendorId = self.productId = 0
		buf = ctypes.create_unicode_buffer(128)
		self.product = buf.value if hid.HidD_GetProductString(handle, buf, ctypes.sizeof(buf)) else ""
		super().__init__(handle, None, max(1, self.inputSize), onReceive, onError, "hid")
		if start:
			self.start()

	def _prepareWrite(self, data: bytes) -> bytes:
		if self.outputSize and len(data) < self.outputSize:
			data = data + bytes(self.outputSize - len(data))
		if self.outputSize and len(data) > self.outputSize:
			raise IoError(0, f"Informe de salida demasiado largo ({len(data)} > {self.outputSize})")
		return data

	def setOutputReport(self, report: bytes) -> None:
		"""Escribe un informe de salida con ``HidD_SetOutputReport`` (algunas líneas lo necesitan)."""
		report = self._prepareWrite(bytes(report))
		buf = ctypes.create_string_buffer(report, len(report))
		try:
			if not hid.HidD_SetOutputReport(self._writeHandle, buf, len(report)):
				self._writeFailed(ctypes.get_last_error())
			self._writeFailures = 0
		finally:
			self._flushWriteError()

	def getFeature(self, reportId: int) -> bytes:
		buf = ctypes.create_string_buffer(max(1, self.featureSize))
		buf[0] = reportId
		if not hid.HidD_GetFeature(self._readHandle, buf, len(buf)):
			raise _winError("HidD_GetFeature")
		return buf.raw

	def setFeature(self, report: bytes) -> None:
		report = bytes(report)
		if self.featureSize and len(report) < self.featureSize:
			report += bytes(self.featureSize - len(report))
		buf = ctypes.create_string_buffer(report, len(report))
		if not hid.HidD_SetFeature(self._readHandle, buf, len(report)):
			raise _winError("HidD_SetFeature")

	# Capacidades (para el estándar HID Braille).
	def valueCaps(self, reportType: int) -> list[HIDP_VALUE_CAPS]:
		n = self.caps.NumberOutputValueCaps if reportType == HidP_Output else self.caps.NumberInputValueCaps
		if not n:
			return []
		arr = (HIDP_VALUE_CAPS * n)()
		count = wintypes.USHORT(n)
		_hidCheck(hid.HidP_GetValueCaps(reportType, arr, ctypes.byref(count), self._pd), "HidP_GetValueCaps")
		return list(arr[: count.value])

	def buttonCaps(self, reportType: int = HidP_Input) -> list[HIDP_BUTTON_CAPS]:
		n = self.caps.NumberInputButtonCaps if reportType == HidP_Input else self.caps.NumberOutputButtonCaps
		if not n:
			return []
		arr = (HIDP_BUTTON_CAPS * n)()
		count = wintypes.USHORT(n)
		_hidCheck(hid.HidP_GetButtonCaps(reportType, arr, ctypes.byref(count), self._pd), "HidP_GetButtonCaps")
		return list(arr[: count.value])

	def getData(self, report: bytes) -> list[tuple[int, int]]:
		"""Pares (índice de datos, valor) de un informe de entrada."""
		maxData = hid.HidP_MaxDataListLength(HidP_Input, self._pd)
		data = (HIDP_DATA * max(1, maxData))()
		count = wintypes.ULONG(maxData)
		report = bytes(report)
		if len(report) < self.inputSize:
			report += bytes(self.inputSize - len(report))
		status = hid.HidP_GetData(HidP_Input, data, ctypes.byref(count), self._pd, report, len(report))
		_hidCheck(status, "HidP_GetData")
		return [(d.DataIndex, d.RawValue) for d in data[: count.value]]

	def makeOutputReport(self, reportId: int, values: list[tuple[int, int, int, bytes]]) -> bytes:
		"""Construye un informe de salida con matrices de valores.

		``values``: tuplas (página de uso, colección, uso, bytes).
		"""
		size = self.outputSize
		report = ctypes.create_string_buffer(size)
		report[0] = reportId
		for usagePage, link, usage, data in values:
			raw = ctypes.create_string_buffer(bytes(data), len(data))
			status = hid.HidP_SetUsageValueArray(HidP_Output, usagePage, link, usage, raw, len(data), self._pd, report, size)
			_hidCheck(status, "HidP_SetUsageValueArray")
		return report.raw

	def _closeHandles(self) -> None:
		if self._pd:
			hid.HidD_FreePreparsedData(self._pd)
			self._pd = ctypes.c_void_p()
		super()._closeHandles()


# ======================================================================== bulk
class BulkDevice(_OverlappedIo):
	"""Dispositivo USB con extremos bulk (``ruta\\extremo``)."""

	kind = "bulk"

	def __init__(
		self,
		path: str,
		epIn: int | str,
		epOut: int | str,
		onReceive: Callable[[bytes], None],
		onError: Callable[[int], None] | None = None,
		readSize: int = 64,
		info: dict | None = None,
	) -> None:
		self.port = path
		self.info = info or {}
		readHandle = _openFile(f"{path}\\{epIn}", GENERIC_READ, 0)
		try:
			writeHandle = _openFile(f"{path}\\{epOut}", GENERIC_WRITE, 0)
		except IoError:
			kernel32.CloseHandle(readHandle)
			raise
		super().__init__(readHandle, writeHandle, readSize, onReceive, onError, "bulk")
		self.start()


# ===================================================================== memoria
class MemoryTransport(Transport):
	"""Conexión simulada: guarda lo escrito y permite inyectar datos.

	Útil para las pruebas de los protocolos sin hardware. ``responder`` es una
	función opcional que recibe cada escritura y devuelve los bytes que la
	«línea» contestaría (o ``None``).
	"""

	kind = "memory"

	def __init__(
		self,
		onReceive: Callable[[bytes], None] | None = None,
		onError: Callable[[int], None] | None = None,
		responder: Callable[[bytes], bytes | list[bytes] | None] | None = None,
		kind: str = "memory",
		port: str = "memoria",
		info: dict | None = None,
		outputSize: int = 0,
	) -> None:
		self.onReceive = onReceive
		self.onError = onError
		self.responder = responder
		self.kind = kind
		self.port = port
		self.info = info or {}
		self.outputSize = outputSize
		self.inputSize = 0
		self.writes: list[bytes] = []
		self.features: list[bytes] = []
		self.closed = False

	def write(self, data: bytes) -> None:
		if self.closed:
			raise IoError(0, "Conexión cerrada")
		data = bytes(data)
		if self.outputSize and len(data) < self.outputSize:
			data += bytes(self.outputSize - len(data))
		self.writes.append(data)
		if self.responder is not None:
			reply = self.responder(data)
			if reply:
				for chunk in reply if isinstance(reply, list) else [reply]:
					self.feed(chunk)

	setOutputReport = write

	def setFeature(self, report: bytes) -> None:
		self.features.append(bytes(report))
		if self.responder is not None:
			reply = self.responder(b"FEATURE" + bytes(report))
			if reply:
				for chunk in reply if isinstance(reply, list) else [reply]:
					self.feed(chunk)

	def getFeature(self, reportId: int) -> bytes:
		"""Informe de características simulado: lo da ``responder`` con ``b"GETFEATURE" + id``."""
		if self.responder is not None:
			reply = self.responder(b"GETFEATURE" + bytes([reportId]))
			if reply:
				return bytes(reply if not isinstance(reply, list) else reply[0])
		return bytes([reportId])

	def feed(self, data: bytes) -> None:
		"""Simula la llegada de datos desde la línea."""
		if self.onReceive is not None and not self.closed:
			self.onReceive(bytes(data))

	def fail(self, code: int = 1167) -> None:
		"""Simula una desconexión (1167 = dispositivo no conectado)."""
		if self.onError is not None:
			self.onError(code)

	def close(self) -> None:
		self.closed = True
