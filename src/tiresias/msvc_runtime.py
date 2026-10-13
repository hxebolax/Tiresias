"""Carga temprana de una biblioteca de Visual C++ (msvcp140.dll) moderna.

El paquete ``winrt`` (voces OneCore, OCR...) trae su propia ``msvcp140.dll``
antigua (14.29). Si se carga primero, cualquier extensión compilada con un
Visual C++ reciente que use la misma DLL (onnxruntime, que usan las voces
Piper) se cuelga o cierra el proceso al usar ``std::mutex``. Windows reutiliza
la primera ``msvcp140.dll`` cargada, así que basta con cargar antes la más
moderna disponible (la de la carpeta del programa en la versión compilada o
la de System32). La biblioteca es compatible hacia atrás, así que ``winrt``
funciona igual con ella.

:func:`preload` se llama al importar el paquete ``tiresias``.
"""

from __future__ import annotations

import ctypes
import os
import sys

#: Versión mínima que necesita onnxruntime (Visual C++ 2022 17.10).
MIN_VERSION = (14, 40)
_loaded: str | None = None


def fileVersion(path: str) -> tuple[int, int, int, int] | None:
	try:
		v = ctypes.windll.version
		size = v.GetFileVersionInfoSizeW(path, None)
		if not size:
			return None
		buf = ctypes.create_string_buffer(size)
		if not v.GetFileVersionInfoW(path, 0, size, buf):
			return None
		ptr = ctypes.c_void_p()
		n = ctypes.c_uint()
		if not v.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(n)) or not ptr.value:
			return None
		info = (ctypes.c_uint32 * 13).from_address(ptr.value)
		return (info[2] >> 16, info[2] & 0xFFFF, info[3] >> 16, info[3] & 0xFFFF)
	except Exception:
		return None


def loadedPath() -> str | None:
	"""Ruta de la ``msvcp140.dll`` ya cargada en el proceso (o ``None``)."""
	try:
		k32 = ctypes.windll.kernel32
		k32.GetModuleHandleW.restype = ctypes.c_void_p
		h = k32.GetModuleHandleW("msvcp140.dll")
		if not h:
			return None
		buf = ctypes.create_unicode_buffer(1024)
		k32.GetModuleFileNameW(ctypes.c_void_p(h), buf, 1024)
		return buf.value or None
	except Exception:
		return None


def _candidates() -> list[str]:
	dirs = []
	if getattr(sys, "frozen", False):
		dirs.append(os.path.dirname(os.path.abspath(sys.executable)))
	dirs.append(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32"))
	return [os.path.join(d, "msvcp140.dll") for d in dirs if os.path.isfile(os.path.join(d, "msvcp140.dll"))]


def preload() -> str | None:
	"""Carga la ``msvcp140.dll`` más moderna si aún no hay ninguna cargada."""
	global _loaded
	if sys.platform != "win32":
		return None
	current = loadedPath()
	if current:
		return current
	best = None
	bestVersion: tuple = ()
	for path in _candidates():
		ver = fileVersion(path) or ()
		if ver > bestVersion:
			best, bestVersion = path, ver
	if best:
		try:
			ctypes.WinDLL(best)
			folder = os.path.dirname(best)
			extra = os.path.join(folder, "msvcp140_1.dll")
			if os.path.isfile(extra):
				ctypes.WinDLL(extra)
			_loaded = best
		except OSError:
			return None
	return best


def isModernEnough() -> bool:
	"""``True`` si la ``msvcp140.dll`` del proceso sirve para onnxruntime."""
	path = loadedPath() or preload()
	if not path:
		return False
	ver = fileVersion(path)
	return bool(ver) and ver[:2] >= MIN_VERSION
