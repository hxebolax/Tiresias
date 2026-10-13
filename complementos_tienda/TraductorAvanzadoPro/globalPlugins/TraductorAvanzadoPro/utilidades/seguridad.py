"""Seguridad del Traductor Avanzado Pro.

Las claves de API se guardan cifradas con DPAPI de Windows
(``CryptProtectData``, ligada a la cuenta del usuario): solo el mismo usuario
en el mismo equipo puede descifrarlas. El complemento original solo las
ocultaba con base64 invertido; ese formato se sigue leyendo (prefijo
``b64:`` o sin prefijo) por si se importa un archivo antiguo, pero al guardar
se cifra siempre con DPAPI. Si DPAPI no está disponible (no debería ocurrir
en Windows) se recurre al formato antiguo para no perder la clave.
"""

from __future__ import annotations

import base64
import ctypes
import threading
from ctypes import wintypes

PREFIJO_DPAPI = "dpapi:"
PREFIJO_B64 = "b64:"
_ENTROPIA = b"Tiresias-TraductorAvanzadoPro-v1"
_SIN_INTERFAZ = 0x01  # CRYPTPROTECT_UI_FORBIDDEN
_bloqueo = threading.Lock()


class _BLOB(ctypes.Structure):
	_fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


try:
	_crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
	_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
	_crypt32.CryptProtectData.argtypes = [ctypes.POINTER(_BLOB), wintypes.LPCWSTR, ctypes.POINTER(_BLOB), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_BLOB)]
	_crypt32.CryptProtectData.restype = wintypes.BOOL
	_crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(_BLOB), ctypes.c_void_p, ctypes.POINTER(_BLOB), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_BLOB)]
	_crypt32.CryptUnprotectData.restype = wintypes.BOOL
	_kernel32.LocalFree.argtypes = [ctypes.c_void_p]
	_kernel32.LocalFree.restype = ctypes.c_void_p
	_HAY_DPAPI = True
except (OSError, AttributeError):  # pragma: no cover - solo fuera de Windows
	_HAY_DPAPI = False


def _blob(datos: bytes) -> tuple[_BLOB, ctypes.Array]:
	buf = ctypes.create_string_buffer(datos, len(datos))
	return _BLOB(len(datos), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _tomar(blob: _BLOB) -> bytes:
	try:
		return ctypes.string_at(blob.pbData, blob.cbData)
	finally:
		_kernel32.LocalFree(ctypes.cast(blob.pbData, ctypes.c_void_p))


def _cifrar(datos: bytes) -> bytes:
	entrada, _b1 = _blob(datos)
	entropia, _b2 = _blob(_ENTROPIA)
	salida = _BLOB()
	with _bloqueo:
		ok = _crypt32.CryptProtectData(ctypes.byref(entrada), "TraductorAvanzadoPro", ctypes.byref(entropia), None, None, _SIN_INTERFAZ, ctypes.byref(salida))
	if not ok:
		raise ctypes.WinError(ctypes.get_last_error())
	return _tomar(salida)


def _descifrar(datos: bytes) -> bytes:
	entrada, _b1 = _blob(datos)
	entropia, _b2 = _blob(_ENTROPIA)
	salida = _BLOB()
	with _bloqueo:
		ok = _crypt32.CryptUnprotectData(ctypes.byref(entrada), None, ctypes.byref(entropia), None, None, _SIN_INTERFAZ, ctypes.byref(salida))
	if not ok:
		raise ctypes.WinError(ctypes.get_last_error())
	return _tomar(salida)


def _codificar_b64(api_key: str) -> str:
	"""Formato del complemento original: cadena invertida en base64."""
	return base64.b64encode(api_key[::-1].encode("utf-8")).decode("ascii")


def codificar_api_key(api_key: str) -> str:
	"""Cifra una clave de API para guardarla en disco (cadena vacía si no hay clave)."""
	if not api_key:
		return ""
	if _HAY_DPAPI:
		try:
			return PREFIJO_DPAPI + base64.b64encode(_cifrar(api_key.encode("utf-8"))).decode("ascii")
		except OSError:
			pass
	return PREFIJO_B64 + _codificar_b64(api_key)


def decodificar_api_key(codificada: str) -> str:
	"""Recupera la clave en claro. Cadena vacía si no se puede descifrar."""
	if not codificada:
		return ""
	try:
		if codificada.startswith(PREFIJO_DPAPI):
			if not _HAY_DPAPI:
				return ""
			return _descifrar(base64.b64decode(codificada[len(PREFIJO_DPAPI):])).decode("utf-8")
		if codificada.startswith(PREFIJO_B64):
			codificada = codificada[len(PREFIJO_B64):]
		return base64.b64decode(codificada.encode("ascii")).decode("utf-8")[::-1]
	except Exception:
		return ""


def censurar(clave: str) -> str:
	"""Versión visible de una clave: las 4 primeras y las 4 últimas letras."""
	if len(clave) > 8:
		return clave[:4] + "*" * (len(clave) - 8) + clave[-4:]
	return "*" * len(clave)


def es_modo_seguro() -> bool:
	"""``True`` si Tiresias se ha iniciado en modo seguro (``--secure``)."""
	try:
		from tiresias.config import policy

		return bool(policy.policy.secureMode)
	except Exception:
		return False
