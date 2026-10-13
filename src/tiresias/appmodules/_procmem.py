"""Memoria en otro proceso para mensajes de ventana que devuelven datos.

Algunos controles (Scintilla, barras de estado clásicas) solo devuelven texto
escribiéndolo en un búfer cuya dirección se pasa en el mensaje. Ese búfer
tiene que estar en el proceso del control: se reserva con ``VirtualAllocEx``
y se lee con ``ReadProcessMemory``. Todas las llamadas usan
``SendMessageTimeout`` para no colgarse si la aplicación no responde.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from .. import winapi

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
kernel32.VirtualAllocEx.restype = ctypes.c_void_p
kernel32.VirtualFreeEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD]
kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04
SMTO_ABORTIFHUNG = 0x0002

#: Tiempo máximo de cada mensaje (ms).
TIMEOUT_MS = 400


class ProcessMemoryError(Exception):
	pass


def sendMessage(hwnd: int, msg: int, wParam: int = 0, lParam: int = 0, timeout: int = TIMEOUT_MS) -> int:
	"""``SendMessageTimeout``; lanza :class:`ProcessMemoryError` si no responde."""
	result = winapi.ULONG_PTR()
	ok = winapi.user32.SendMessageTimeoutW(hwnd, msg, wParam, lParam, SMTO_ABORTIFHUNG, timeout, ctypes.byref(result))
	if not ok:
		raise ProcessMemoryError("la ventana no responde")
	value = int(result.value)
	if value >= 1 << 63:
		value -= 1 << 64
	return value


class RemoteBuffer:
	"""Búfer reservado en el proceso de una ventana (úsese con ``with``)."""

	def __init__(self, hwnd: int, size: int) -> None:
		self.size = max(1, int(size))
		pid = winapi.getWindowProcessId(hwnd)
		self.process = kernel32.OpenProcess(PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE, False, pid)
		if not self.process:
			raise ProcessMemoryError("no se pudo abrir el proceso")
		self.address = kernel32.VirtualAllocEx(self.process, None, self.size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
		if not self.address:
			kernel32.CloseHandle(self.process)
			raise ProcessMemoryError("no se pudo reservar memoria")

	def read(self, size: int | None = None) -> bytes:
		size = self.size if size is None else min(size, self.size)
		buf = ctypes.create_string_buffer(size)
		read = ctypes.c_size_t()
		if not kernel32.ReadProcessMemory(self.process, self.address, buf, size, ctypes.byref(read)):
			raise ProcessMemoryError("no se pudo leer la memoria")
		return buf.raw[: read.value]

	def write(self, data: bytes) -> None:
		written = ctypes.c_size_t()
		if not kernel32.WriteProcessMemory(self.process, self.address, data, len(data), ctypes.byref(written)):
			raise ProcessMemoryError("no se pudo escribir la memoria")

	def close(self) -> None:
		if self.address:
			kernel32.VirtualFreeEx(self.process, self.address, 0, MEM_RELEASE)
			self.address = None
		if self.process:
			kernel32.CloseHandle(self.process)
			self.process = None

	def __enter__(self) -> "RemoteBuffer":
		return self

	def __exit__(self, *exc) -> None:
		self.close()
