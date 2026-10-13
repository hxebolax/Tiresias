"""Claves de los servicios de IA, cifradas con DPAPI.

Cada clave se cifra con ``CryptProtectData`` (ligada a la cuenta de Windows
del usuario) y se guarda en ``data/config/aiKeys.json`` en base64. Si se
copia la carpeta de datos a otro equipo o a otra cuenta, las claves no se
pueden descifrar y hay que volver a escribirlas.

Si no hay clave guardada se usa la variable de entorno habitual del servicio
(``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``, ``GEMINI_API_KEY``).
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import threading
from ctypes import wintypes

from .. import paths
from ..log import getLogger

log = getLogger("ai.keys")

ENV_VARS = {
	"anthropic": ("ANTHROPIC_API_KEY",),
	"openai": ("OPENAI_API_KEY",),
	"gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
	"local": (),
}

#: Texto que acompaña a los datos cifrados (descripción del blob).
_DESCRIPTION = "Tiresias AI key"
_ENTROPY = b"Tiresias-AI-v1"


class DATA_BLOB(ctypes.Structure):
	_fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


_crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32")
_crypt32.CryptProtectData.argtypes = [ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
_crypt32.CryptProtectData.restype = wintypes.BOOL
_crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
_crypt32.CryptUnprotectData.restype = wintypes.BOOL
_kernel32.LocalFree.argtypes = [ctypes.c_void_p]
CRYPTPROTECT_UI_FORBIDDEN = 0x1

_lock = threading.Lock()


def _blob(data: bytes) -> tuple[DATA_BLOB, ctypes.Array]:
	buf = ctypes.create_string_buffer(data, len(data))
	return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def protect(data: bytes) -> bytes:
	"""Cifra con DPAPI para el usuario actual."""
	inBlob, _keep = _blob(data)
	entropy, _keep2 = _blob(_ENTROPY)
	out = DATA_BLOB()
	if not _crypt32.CryptProtectData(ctypes.byref(inBlob), _DESCRIPTION, ctypes.byref(entropy), None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
		raise OSError(ctypes.get_last_error() or "CryptProtectData")
	try:
		return ctypes.string_at(out.pbData, out.cbData)
	finally:
		_kernel32.LocalFree(out.pbData)


def unprotect(data: bytes) -> bytes:
	"""Descifra datos de :func:`protect`."""
	inBlob, _keep = _blob(data)
	entropy, _keep2 = _blob(_ENTROPY)
	out = DATA_BLOB()
	if not _crypt32.CryptUnprotectData(ctypes.byref(inBlob), None, ctypes.byref(entropy), None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
		raise OSError(ctypes.get_last_error() or "CryptUnprotectData")
	try:
		return ctypes.string_at(out.pbData, out.cbData)
	finally:
		_kernel32.LocalFree(out.pbData)


def _file() -> str:
	return os.path.join(paths.configDir(), "aiKeys.json")


def _load() -> dict[str, str]:
	try:
		with open(_file(), encoding="utf-8") as f:
			data = json.load(f)
		return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
	except FileNotFoundError:
		return {}
	except (OSError, ValueError):
		log.exception("Archivo de claves de IA no válido")
		return {}


def _save(data: dict[str, str]) -> None:
	os.makedirs(paths.configDir(), exist_ok=True)
	tmp = _file() + ".tmp"
	with open(tmp, "w", encoding="utf-8") as f:
		json.dump(data, f, indent="\t")
	os.replace(tmp, _file())


#: Espacios, saltos de línea y caracteres invisibles que se cuelan al copiar
#: una clave de una web o de un correo (ninguna clave los lleva).
_JUNK_RE = re.compile(r"[\s ­᠎​-‏ -  -⁯﻿]")


class InvalidKeyError(ValueError):
	"""La clave tiene caracteres que no pueden ir en una clave (el mensaje no la incluye)."""


def cleanKey(key: str | None) -> str:
	"""Clave sin espacios, saltos de línea ni caracteres invisibles."""
	return _JUNK_RE.sub("", key or "")


def isValidKey(key: str) -> bool:
	"""Una clave solo tiene caracteres ASCII visibles."""
	return bool(key) and key.isascii() and key.isprintable()


def setKey(provider: str, key: str | None) -> None:
	"""Guarda (cifrada) o borra la clave de un proveedor.

	Lanza :class:`InvalidKeyError` si, quitados los espacios y los caracteres
	invisibles, quedan caracteres que no pueden formar parte de una clave.
	"""
	key = cleanKey(key)
	if key and not isValidKey(key):
		raise InvalidKeyError("clave con caracteres no válidos")
	with _lock:
		data = _load()
		if key:
			data[provider] = base64.b64encode(protect(key.encode("utf-8"))).decode("ascii")
		else:
			data.pop(provider, None)
		_save(data)


def envKeyVariable(provider: str) -> str:
	"""Variable de entorno de la que sale la clave (cadena vacía si ninguna)."""
	for var in ENV_VARS.get(provider, ()):
		if cleanKey(os.environ.get(var)):
			return var
	return ""


def hasStoredKey(provider: str) -> bool:
	with _lock:
		return provider in _load()


def getKey(provider: str) -> str:
	"""Clave del proveedor (guardada o de la variable de entorno); cadena vacía si no hay."""
	from ..config import policy as _pol

	if not _pol.isAllowed("ai"):
		# Modo seguro (escritorio seguro): no se envía nada a servicios de IA.
		return ""
	with _lock:
		stored = _load().get(provider)
	if stored:
		try:
			return cleanKey(unprotect(base64.b64decode(stored)).decode("utf-8"))
		except (OSError, ValueError):
			log.warning("No se pudo descifrar la clave de %s (¿otro usuario u otro equipo?)", provider)
	for var in ENV_VARS.get(provider, ()):
		val = cleanKey(os.environ.get(var))
		if val:
			return val
	return ""
