"""Conexión USB bulk a través de WinUSB (``winusb.sys``, incluido en Windows).

Las líneas HIMS antiguas usan un controlador propio (``himsusb.sys``) que
Windows 11 ya no deja instalar. HIMS publica un paquete con un INF de WinUSB
que expone la línea con su propio GUID de interfaz; con él se habla con la
misma línea por los extremos bulk sin controlador del fabricante (NVDA
#20555).

- :func:`listDevices` enumera los dispositivos presentes con esa interfaz.
- :class:`WinUsbDevice` es una conexión (:class:`hwio.Transport`) con E/S
  solapada sobre ``winusb.dll``: busca los extremos bulk de entrada y de
  salida, lee en un hilo propio y avisa una sola vez si la línea se pierde.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Any, Callable

from ...log import getLogger
from . import hwio

log = getLogger("braille.winusb")

#: GUID de interfaz que declara el INF de WinUSB de HIMS (``hims_winusb.inf``).
GUID_HIMS_WINUSB = "{78A1C341-4539-11D3-B88D-00C04FAD5171}"

#: ``USBD_PIPE_TYPE``: extremo bulk.
PIPE_TYPE_BULK = 2
#: Bit de dirección de los extremos de entrada.
ENDPOINT_IN = 0x80


class USB_INTERFACE_DESCRIPTOR(ctypes.Structure):
	_pack_ = 1
	_fields_ = [
		("bLength", ctypes.c_ubyte),
		("bDescriptorType", ctypes.c_ubyte),
		("bInterfaceNumber", ctypes.c_ubyte),
		("bAlternateSetting", ctypes.c_ubyte),
		("bNumEndpoints", ctypes.c_ubyte),
		("bInterfaceClass", ctypes.c_ubyte),
		("bInterfaceSubClass", ctypes.c_ubyte),
		("bInterfaceProtocol", ctypes.c_ubyte),
		("iInterface", ctypes.c_ubyte),
	]


class WINUSB_PIPE_INFORMATION(ctypes.Structure):
	_fields_ = [
		("PipeType", ctypes.c_int),
		("PipeId", ctypes.c_ubyte),
		("MaximumPacketSize", wintypes.USHORT),
		("Interval", ctypes.c_ubyte),
	]


_lib: Any = None
_libLock = threading.Lock()


def winUsbLibrary() -> Any:
	"""``winusb.dll`` con los prototipos declarados (se carga la primera vez)."""
	global _lib
	with _libLock:
		if _lib is None:
			lib = ctypes.WinDLL("winusb", use_last_error=True)
			handle = ctypes.c_void_p
			lpOv = ctypes.POINTER(hwio.OVERLAPPED)
			lib.WinUsb_Initialize.argtypes = [wintypes.HANDLE, ctypes.POINTER(handle)]
			lib.WinUsb_Initialize.restype = wintypes.BOOL
			lib.WinUsb_Free.argtypes = [handle]
			lib.WinUsb_Free.restype = wintypes.BOOL
			lib.WinUsb_QueryInterfaceSettings.argtypes = [handle, ctypes.c_ubyte, ctypes.POINTER(USB_INTERFACE_DESCRIPTOR)]
			lib.WinUsb_QueryInterfaceSettings.restype = wintypes.BOOL
			lib.WinUsb_QueryPipe.argtypes = [handle, ctypes.c_ubyte, ctypes.c_ubyte, ctypes.POINTER(WINUSB_PIPE_INFORMATION)]
			lib.WinUsb_QueryPipe.restype = wintypes.BOOL
			for name in ("WinUsb_ReadPipe", "WinUsb_WritePipe"):
				fn = getattr(lib, name)
				fn.argtypes = [handle, ctypes.c_ubyte, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG), lpOv]
				fn.restype = wintypes.BOOL
			lib.WinUsb_AbortPipe.argtypes = [handle, ctypes.c_ubyte]
			lib.WinUsb_AbortPipe.restype = wintypes.BOOL
			lib.WinUsb_GetOverlappedResult.argtypes = [handle, lpOv, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
			lib.WinUsb_GetOverlappedResult.restype = wintypes.BOOL
			_lib = lib
		return _lib


# ================================================================ enumeración
def listDevices(guid: str = GUID_HIMS_WINUSB) -> list:
	"""Dispositivos presentes con la interfaz WinUSB indicada (``DeviceInfo`` con ``kind="winusb"``)."""
	from . import ports

	out = []
	try:
		for info, devinfo, path in ports._iterInterfaces(ports.GUID.fromString(guid)):
			hwId = ports._regProperty(info, devinfo, ports.SPDRP_HARDWAREID)
			out.append(
				ports.DeviceInfo(
					"winusb",
					path,
					usbId=ports.normalizeUsbId(hwId) or ports.normalizeUsbId(path),
					hardwareId=hwId,
					friendlyName=ports._regProperty(info, devinfo, ports.SPDRP_DEVICEDESC),
				)
			)
	except Exception:
		log.debug("Error enumerando los dispositivos WinUSB", exc_info=True)
	return out


# ================================================================== conexión
class WinUsbDevice(hwio.Transport):
	"""Dispositivo USB abierto con WinUSB (extremos bulk de entrada y salida)."""

	kind = "winusb"

	def __init__(
		self,
		path: str,
		onReceive: Callable[[bytes], None],
		onError: Callable[[int], None] | None = None,
		readSize: int = 64,
		info: dict | None = None,
		lib: Any = None,
	) -> None:
		self.port = path
		self.info = info or {}
		self._lib = lib if lib is not None else winUsbLibrary()
		self._onReceive = onReceive
		self._onError = onError
		self._readSize = max(1, readSize)
		self._closed = False
		self._errorReported = False
		self._writeFailures = 0
		self._writeLock = threading.Lock()
		self._file = hwio._openFile(path, hwio.GENERIC_READ | hwio.GENERIC_WRITE, hwio.FILE_SHARE_READ | hwio.FILE_SHARE_WRITE)
		self._usb = ctypes.c_void_p()
		if not self._lib.WinUsb_Initialize(self._file, ctypes.byref(self._usb)):
			err = hwio._winError("WinUsb_Initialize")
			hwio.kernel32.CloseHandle(self._file)
			raise err
		try:
			#: Direcciones de los extremos bulk (la de entrada lleva el bit 0x80).
			self.pipeIn, self.pipeOut = self._findPipes()
		except Exception:
			self._lib.WinUsb_Free(self._usb)
			hwio.kernel32.CloseHandle(self._file)
			raise
		self._stopEvent = hwio.kernel32.CreateEventW(None, True, False, None)
		self._writeEvent = hwio.kernel32.CreateEventW(None, True, False, None)
		self._thread = threading.Thread(target=self._readLoop, name="braille-winusb", daemon=True)
		self._thread.start()

	def _findPipes(self) -> tuple[int, int]:
		desc = USB_INTERFACE_DESCRIPTOR()
		if not self._lib.WinUsb_QueryInterfaceSettings(self._usb, 0, ctypes.byref(desc)):
			raise hwio._winError("WinUsb_QueryInterfaceSettings")
		pipeIn = pipeOut = None
		for index in range(desc.bNumEndpoints):
			pipe = WINUSB_PIPE_INFORMATION()
			if not self._lib.WinUsb_QueryPipe(self._usb, 0, index, ctypes.byref(pipe)):
				continue
			if pipe.PipeType != PIPE_TYPE_BULK:
				continue
			if pipe.PipeId & ENDPOINT_IN:
				if pipeIn is None:
					pipeIn = pipe.PipeId
			elif pipeOut is None:
				pipeOut = pipe.PipeId
		if pipeIn is None or pipeOut is None:
			raise hwio.IoError(0, f"El dispositivo WinUSB no tiene extremos bulk de entrada y salida ({pipeIn}, {pipeOut})")
		return pipeIn, pipeOut

	# ------------------------------------------------------------- lectura
	def _readLoop(self) -> None:
		k32 = hwio.kernel32
		readEvent = k32.CreateEventW(None, True, False, None)
		handles = (wintypes.HANDLE * 2)(self._stopEvent, readEvent)
		buf = ctypes.create_string_buffer(self._readSize)
		try:
			while not self._closed:
				ov = hwio.OVERLAPPED()
				ov.hEvent = readEvent
				k32.ResetEvent(readEvent)
				count = wintypes.ULONG()
				ok = self._lib.WinUsb_ReadPipe(self._usb, self.pipeIn, buf, self._readSize, ctypes.byref(count), ctypes.byref(ov))
				if not ok:
					err = ctypes.get_last_error()
					if err != hwio.ERROR_IO_PENDING:
						self._reportError(err, "lectura")
						return
					res = k32.WaitForMultipleObjects(2, handles, False, hwio.INFINITE)
					done = wintypes.DWORD()
					if res == hwio.WAIT_OBJECT_0 or self._closed:
						self._lib.WinUsb_AbortPipe(self._usb, self.pipeIn)
						self._lib.WinUsb_GetOverlappedResult(self._usb, ctypes.byref(ov), ctypes.byref(done), True)
						return
					if not self._lib.WinUsb_GetOverlappedResult(self._usb, ctypes.byref(ov), ctypes.byref(done), False):
						self._reportError(ctypes.get_last_error(), "lectura")
						return
					count.value = done.value
				if count.value and not self._closed:
					try:
						self._onReceive(buf.raw[: count.value])
					except Exception:
						log.exception("Error procesando datos de la línea braille")
		finally:
			k32.CloseHandle(readEvent)

	def _reportError(self, code: int, what: str) -> None:
		if self._closed or self._errorReported:
			return
		self._errorReported = True
		log.info("Fallo de %s en la línea braille WinUSB (%s): %s", what, self.port, ctypes.FormatError(code).strip())
		if self._onError is not None:
			try:
				self._onError(code)
			except Exception:
				log.exception("Error avisando de la desconexión")

	# ------------------------------------------------------------ escritura
	def write(self, data: bytes) -> None:
		if self._closed:
			raise hwio.IoError(0, "Conexión cerrada")
		data = bytes(data)
		k32 = hwio.kernel32
		try:
			with self._writeLock:
				buf = ctypes.create_string_buffer(data, len(data))
				ov = hwio.OVERLAPPED()
				ov.hEvent = self._writeEvent
				k32.ResetEvent(self._writeEvent)
				written = wintypes.ULONG()
				if not self._lib.WinUsb_WritePipe(self._usb, self.pipeOut, buf, len(data), ctypes.byref(written), ctypes.byref(ov)):
					err = ctypes.get_last_error()
					if err != hwio.ERROR_IO_PENDING:
						self._writeFailed(err)
					done = wintypes.DWORD()
					if k32.WaitForSingleObject(self._writeEvent, hwio.WRITE_TIMEOUT_MS) == hwio.WAIT_TIMEOUT:
						self._lib.WinUsb_AbortPipe(self._usb, self.pipeOut)
						self._lib.WinUsb_GetOverlappedResult(self._usb, ctypes.byref(ov), ctypes.byref(done), True)
						self._writeFailed(hwio.ERROR_OPERATION_ABORTED)
					if not self._lib.WinUsb_GetOverlappedResult(self._usb, ctypes.byref(ov), ctypes.byref(done), False):
						self._writeFailed(ctypes.get_last_error())
				self._writeFailures = 0
		finally:
			# Fuera del cerrojo: el aviso cierra la conexión y close() toma
			# ese mismo cerrojo (no reentrante) en este hilo.
			code = self._pendingWriteError
			if code is not None:
				self._pendingWriteError = None
				self._reportError(code, "escritura")

	#: Error de escritura pendiente de avisar cuando se suelte el cerrojo.
	_pendingWriteError: int | None = None

	def _writeFailed(self, code: int) -> None:
		self._writeFailures += 1
		if self._writeFailures >= hwio.MAX_WRITE_FAILURES:
			self._pendingWriteError = code
		raise hwio._winError("Error escribiendo en la línea braille (WinUSB)", code)

	# --------------------------------------------------------------- cierre
	def close(self) -> None:
		if self._closed:
			return
		self._closed = True
		k32 = hwio.kernel32
		k32.SetEvent(self._stopEvent)
		if self._thread.is_alive() and self._thread is not threading.current_thread():
			self._thread.join(2)
		with self._writeLock:
			if self._usb:
				self._lib.WinUsb_Free(self._usb)
				self._usb = ctypes.c_void_p()
			if self._file:
				k32.CloseHandle(self._file)
				self._file = 0
			k32.CloseHandle(self._stopEvent)
			k32.CloseHandle(self._writeEvent)
