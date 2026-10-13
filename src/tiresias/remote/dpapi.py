"""Cifrado de las claves de conexión con DPAPI de Windows (ámbito del usuario).

Solo el mismo usuario de Windows, en el mismo equipo, puede descifrar lo que
se cifra aquí. Si la carpeta ``data`` se copia a otro equipo o usuario, las
claves cifradas no se pueden recuperar (habrá que volver a escribirlas).
"""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes

PREFIX = "dpapi:"
_ENTROPY = b"Tiresias acceso remoto"
CRYPTPROTECT_UI_FORBIDDEN = 0x01


class DATA_BLOB(ctypes.Structure):
	_fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


_crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_crypt32.CryptProtectData.argtypes = [
	ctypes.POINTER(DATA_BLOB),
	wintypes.LPCWSTR,
	ctypes.POINTER(DATA_BLOB),
	ctypes.c_void_p,
	ctypes.c_void_p,
	wintypes.DWORD,
	ctypes.POINTER(DATA_BLOB),
]
_crypt32.CryptProtectData.restype = wintypes.BOOL
_crypt32.CryptUnprotectData.argtypes = [
	ctypes.POINTER(DATA_BLOB),
	ctypes.c_void_p,
	ctypes.POINTER(DATA_BLOB),
	ctypes.c_void_p,
	ctypes.c_void_p,
	wintypes.DWORD,
	ctypes.POINTER(DATA_BLOB),
]
_crypt32.CryptUnprotectData.restype = wintypes.BOOL
_kernel32.LocalFree.argtypes = [ctypes.c_void_p]
_kernel32.LocalFree.restype = ctypes.c_void_p


def _blob(data: bytes) -> tuple[DATA_BLOB, ctypes.Array]:
	buf = ctypes.create_string_buffer(data, len(data))
	return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _take(blob: DATA_BLOB) -> bytes:
	try:
		return ctypes.string_at(blob.pbData, blob.cbData)
	finally:
		_kernel32.LocalFree(ctypes.cast(blob.pbData, ctypes.c_void_p))


def protect(text: str) -> str:
	"""Texto -> ``"dpapi:<base64>"``. Lanza :class:`OSError` si falla."""
	data, _b1 = _blob(text.encode("utf-8"))
	entropy, _b2 = _blob(_ENTROPY)
	out = DATA_BLOB()
	if not _crypt32.CryptProtectData(ctypes.byref(data), "Tiresias", ctypes.byref(entropy), None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
		raise ctypes.WinError(ctypes.get_last_error())
	return PREFIX + base64.b64encode(_take(out)).decode("ascii")


def unprotect(value: str) -> str:
	"""``"dpapi:<base64>"`` -> texto. Lanza :class:`OSError` o :class:`ValueError` si falla."""
	if not isProtected(value):
		raise ValueError("No es un valor cifrado con DPAPI")
	raw = base64.b64decode(value[len(PREFIX) :].encode("ascii"), validate=True)
	data, _b1 = _blob(raw)
	entropy, _b2 = _blob(_ENTROPY)
	out = DATA_BLOB()
	if not _crypt32.CryptUnprotectData(ctypes.byref(data), None, ctypes.byref(entropy), None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
		raise ctypes.WinError(ctypes.get_last_error())
	return _take(out).decode("utf-8")


def isProtected(value: object) -> bool:
	return isinstance(value, str) and value.startswith(PREFIX)
