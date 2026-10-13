"""Credenciales de la cuenta de la Audiocinemateca, cifradas en disco.

Se cifran con la protección de datos de Windows (DPAPI, ``CryptProtectData``):
solo la misma cuenta de Windows, en el mismo equipo, puede descifrarlas. El
archivo (``credenciales.bin``) está en la carpeta de datos del complemento.
"""

from __future__ import annotations

import ctypes
import json
import os
from ctypes import wintypes

from . import ajustes

ARCHIVO = "credenciales.bin"
_ENTROPIA = b"Tiresias-Audiocinemateca"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DATA_BLOB(ctypes.Structure):
	_fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


_crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_crypt32.CryptProtectData.argtypes = [
	ctypes.POINTER(_DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(_DATA_BLOB),
	ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
]
_crypt32.CryptProtectData.restype = wintypes.BOOL
_crypt32.CryptUnprotectData.argtypes = [
	ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p, ctypes.POINTER(_DATA_BLOB),
	ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
]
_crypt32.CryptUnprotectData.restype = wintypes.BOOL
_kernel32.LocalFree.argtypes = [ctypes.c_void_p]
_kernel32.LocalFree.restype = ctypes.c_void_p


def _blob(datos: bytes) -> tuple[_DATA_BLOB, ctypes.Array]:
	buf = ctypes.create_string_buffer(datos, len(datos))
	return _DATA_BLOB(len(datos), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def cifrar(datos: bytes) -> bytes:
	entrada, _b1 = _blob(datos)
	entropia, _b2 = _blob(_ENTROPIA)
	salida = _DATA_BLOB()
	if not _crypt32.CryptProtectData(ctypes.byref(entrada), "Audiocinemateca", ctypes.byref(entropia), None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(salida)):
		raise OSError(ctypes.get_last_error(), "CryptProtectData")
	try:
		return ctypes.string_at(salida.pbData, salida.cbData)
	finally:
		_kernel32.LocalFree(salida.pbData)


def descifrar(datos: bytes) -> bytes:
	entrada, _b1 = _blob(datos)
	entropia, _b2 = _blob(_ENTROPIA)
	salida = _DATA_BLOB()
	if not _crypt32.CryptUnprotectData(ctypes.byref(entrada), None, ctypes.byref(entropia), None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(salida)):
		raise OSError(ctypes.get_last_error(), "CryptUnprotectData")
	try:
		return ctypes.string_at(salida.pbData, salida.cbData)
	finally:
		_kernel32.LocalFree(salida.pbData)


def _ruta() -> str:
	return ajustes.rutaDatos(ARCHIVO)


def guardar(usuario: str, contrasena: str) -> None:
	"""Guarda las credenciales cifradas y las deja en el estado de la sesión."""
	datos = json.dumps({"usuario": usuario, "contrasena": contrasena}).encode("utf-8")
	tmp = _ruta() + ".tmp"
	with open(tmp, "wb") as f:
		f.write(cifrar(datos))
	os.replace(tmp, _ruta())
	ajustes.estado.usuario = usuario
	ajustes.estado.contrasena = contrasena


def cargar() -> tuple[str, str]:
	"""Lee las credenciales guardadas (``("", "")`` si no hay o no se pueden leer)."""
	try:
		with open(_ruta(), "rb") as f:
			datos = json.loads(descifrar(f.read()).decode("utf-8"))
		usuario = str(datos.get("usuario", ""))
		contrasena = str(datos.get("contrasena", ""))
	except Exception:
		usuario = contrasena = ""
	ajustes.estado.usuario = usuario
	ajustes.estado.contrasena = contrasena
	return usuario, contrasena


def borrar() -> None:
	"""Olvida las credenciales (en disco y en la sesión)."""
	try:
		os.remove(_ruta())
	except OSError:
		pass
	ajustes.estado.usuario = ""
	ajustes.estado.contrasena = ""
