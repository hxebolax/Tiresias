"""Envoltorio de liblouis (``data\\louis\\liblouis.dll``) con ctypes.

Solo expone lo que necesita Tiresias: traducir texto a celdas braille con la
correspondencia de posiciones (para el cursor y el enrutamiento), traducir
celdas a texto (entrada braille) y buscar puntos de división de palabras
(guiones). liblouis no es segura entre hilos: todas las llamadas pasan por un
cerrojo.

Las tablas se indican por nombre de archivo (``"es.tbl"``); el envoltorio las
convierte en rutas completas dentro de ``louis\\tables``. Si la carpeta tiene
caracteres que no se pueden representar en la página de códigos de Windows,
se usa su nombre corto (8.3).
"""

from __future__ import annotations

import ctypes
import os
import threading
from typing import Sequence

from .. import paths
from ..log import getLogger

log = getLogger("brailleTables")

#: Modos de traducción de liblouis.
NO_CONTRACTIONS = 1
COMPBRL_AT_CURSOR = 2
DOTS_IO = 4
COMPBRL_LEFT_CURSOR = 32
UC_BRL = 64
NO_UNDEFINED = 128
PARTIAL_TRANS = 256

#: Tipos de letra (``typeform``) para el énfasis.
PLAIN_TEXT = 0x0000
ITALIC = 0x0001
UNDERLINE = 0x0002
BOLD = 0x0004
COMPUTER_BRAILLE = 0x0400
NO_CONTRACT = 0x1000

LOU_DOTS = 0x8000

#: liblouis va en ``data\louis`` (todo lo que Tiresias necesita está en data).
FOLDER = paths.louisDir()
TABLES_DIR = os.path.join(FOLDER, "tables")
DLL_PATH = os.path.join(FOLDER, "liblouis.dll")

_lock = threading.RLock()
_dll: ctypes.CDLL | None = None
_loadError: str | None = None
_charSize = 4
_tablesDirBytes = b""
_logCallback = None
_LOG_CALLBACK_TYPE = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_char_p)


def _encodePath(path: str) -> bytes:
	"""Ruta en la codificación ANSI de Windows (o su nombre corto 8.3)."""
	try:
		return path.encode("mbcs", errors="strict")
	except UnicodeEncodeError:
		pass
	buf = ctypes.create_unicode_buffer(1024)
	try:
		n = ctypes.windll.kernel32.GetShortPathNameW(path, buf, len(buf))
	except Exception:
		n = 0
	if n:
		try:
			return buf.value.encode("mbcs", errors="strict")
		except UnicodeEncodeError:
			pass
	return path.encode("mbcs", errors="replace")


def _onLog(level: int, message: bytes) -> None:
	try:
		text = message.decode("utf-8", errors="replace") if message else ""
	except Exception:
		text = repr(message)
	if level >= 40000:
		log.warning("liblouis: %s", text)
	else:
		log.debug("liblouis: %s", text)


def load() -> bool:
	"""Carga la biblioteca (solo una vez). Devuelve ``True`` si está disponible."""
	global _dll, _loadError, _charSize, _tablesDirBytes, _logCallback
	with _lock:
		if _dll is not None:
			return True
		if _loadError is not None:
			return False
		try:
			if not os.path.isfile(DLL_PATH):
				raise OSError(f"No existe {DLL_PATH}")
			dll = ctypes.CDLL(DLL_PATH)
			dll.lou_version.restype = ctypes.c_char_p
			dll.lou_charSize.restype = ctypes.c_int
			for fn in ("lou_translate", "lou_backTranslate"):
				f = getattr(dll, fn)
				f.restype = ctypes.c_int
				f.argtypes = [
					ctypes.c_char_p,
					ctypes.c_void_p,
					ctypes.POINTER(ctypes.c_int),
					ctypes.c_void_p,
					ctypes.POINTER(ctypes.c_int),
					ctypes.c_void_p,
					ctypes.c_char_p,
					ctypes.c_void_p,
					ctypes.c_void_p,
					ctypes.POINTER(ctypes.c_int),
					ctypes.c_int,
				]
			dll.lou_hyphenate.restype = ctypes.c_int
			dll.lou_hyphenate.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
			dll.lou_checkTable.restype = ctypes.c_int
			dll.lou_checkTable.argtypes = [ctypes.c_char_p]
			dll.lou_setLogLevel.argtypes = [ctypes.c_int]
			dll.lou_free.restype = None
			_charSize = int(dll.lou_charSize())
			_logCallback = _LOG_CALLBACK_TYPE(_onLog)
			dll.lou_registerLogCallback(_logCallback)
			dll.lou_setLogLevel(40000)
			_tablesDirBytes = _encodePath(TABLES_DIR)
			_dll = dll
			log.info("liblouis %s cargada (caracteres de %d bytes)", version(), _charSize)
			return True
		except Exception as e:
			_loadError = str(e)
			log.warning("No se pudo cargar liblouis: %s", e)
			return False


def isAvailable() -> bool:
	return load()


def loadError() -> str | None:
	return _loadError


def version() -> str:
	if _dll is None:
		return ""
	try:
		return (_dll.lou_version() or b"").decode("ascii", errors="replace")
	except Exception:
		return ""


def terminate() -> None:
	"""Libera las tablas compiladas."""
	global _dll
	with _lock:
		if _dll is not None:
			try:
				_dll.lou_free()
			except Exception:
				pass


def tableListBytes(tables: Sequence[str]) -> bytes:
	"""Lista de tablas separada por comas con rutas completas."""
	parts = []
	for t in tables:
		if not t:
			continue
		if os.path.isabs(t):
			parts.append(_encodePath(t))
		else:
			parts.append(_tablesDirBytes + b"\\" + t.encode("ascii", errors="replace"))
	return b",".join(parts)


def checkTable(tables: Sequence[str]) -> bool:
	"""``True`` si liblouis puede compilar la lista de tablas."""
	if not load():
		return False
	with _lock:
		try:
			return bool(_dll.lou_checkTable(tableListBytes(tables)))
		except Exception:
			log.debug("Error comprobando la tabla %s", tables, exc_info=True)
			return False


# ---------------------------------------------------------------------- caracteres
def _encode(text: str) -> tuple[ctypes.Array, list[int]]:
	"""Texto como ``widechar`` de liblouis.

	Devuelve el búfer y, para cada unidad del búfer, el índice del carácter
	de Python del que procede (solo difiere con caracteres de 2 bytes y
	caracteres fuera del plano básico).
	"""
	if _charSize == 4:
		buf = (ctypes.c_uint32 * max(1, len(text)))(*[ord(c) for c in text])
		return buf, list(range(len(text)))
	units: list[int] = []
	owner: list[int] = []
	for i, c in enumerate(text):
		cp = ord(c)
		if cp > 0xFFFF:
			cp -= 0x10000
			units += [0xD800 + (cp >> 10), 0xDC00 + (cp & 0x3FF)]
			owner += [i, i]
		else:
			units.append(cp)
			owner.append(i)
	buf = (ctypes.c_uint16 * max(1, len(units)))(*units)
	return buf, owner


def _newBuffer(size: int) -> ctypes.Array:
	return (ctypes.c_uint32 * size)() if _charSize == 4 else (ctypes.c_uint16 * size)()


def _decode(buf: ctypes.Array, length: int) -> str:
	vals = list(buf[:length])
	if _charSize == 4:
		return "".join(chr(v) for v in vals if v < 0x110000)
	data = b"".join(int(v).to_bytes(2, "little") for v in vals)
	return data.decode("utf-16-le", errors="replace")


class LouisError(RuntimeError):
	pass


def translate(
	tables: Sequence[str],
	text: str,
	typeform: Sequence[int] | None = None,
	cursorPos: int | None = None,
	mode: int = 0,
) -> tuple[list[int], list[int], list[int], int | None]:
	"""Traduce ``text`` a celdas braille.

	Devuelve ``(celdas, brailleToRaw, rawToBraille, cursor)``: para cada
	celda, el índice del carácter de origen; para cada carácter, la primera
	celda que le corresponde; y la posición del cursor en las celdas.
	"""
	if not load():
		raise LouisError(_loadError or "liblouis no disponible")
	if not text:
		return [], [], [], (0 if cursorPos is not None else None)
	inbuf, owner = _encode(text)
	inLen = len(owner)
	tf = None
	if typeform is not None:
		vals = []
		for i in range(inLen):
			src = owner[i]
			vals.append(int(typeform[src]) if src < len(typeform) else 0)
		tf = (ctypes.c_uint16 * inLen)(*vals)
	unitCursor = None
	cursorAtEnd = False
	if cursorPos is not None:
		cursorPos = max(0, min(cursorPos, len(text)))
		if cursorPos < len(text):
			unitCursor = owner.index(cursorPos)
		else:
			# Cursor detrás del último carácter: liblouis no admite una posición
			# fuera del texto (devuelve 0 o 1). Va detrás de la última celda.
			cursorAtEnd = True
	size = inLen * 4 + 32
	with _lock:
		tableList = tableListBytes(tables)
		for _attempt in range(6):
			outbuf = _newBuffer(size)
			inlen = ctypes.c_int(inLen)
			outlen = ctypes.c_int(size)
			outputPos = (ctypes.c_int * inLen)()
			inputPos = (ctypes.c_int * size)()
			cur = ctypes.c_int(unitCursor) if unitCursor is not None else None
			tfCopy = (ctypes.c_uint16 * inLen)(*tf) if tf is not None else None
			ok = _dll.lou_translate(
				tableList,
				inbuf,
				ctypes.byref(inlen),
				outbuf,
				ctypes.byref(outlen),
				tfCopy,
				None,
				outputPos,
				inputPos,
				ctypes.byref(cur) if cur is not None else None,
				mode | DOTS_IO,
			)
			if not ok:
				raise LouisError(f"lou_translate falló con {tables}")
			if inlen.value >= inLen or outlen.value < size:
				break
			size *= 2
	n = outlen.value
	cells = [int(c) & 0xFF if int(c) & LOU_DOTS else 0 for c in outbuf[:n]]
	b2r = [owner[min(max(0, inputPos[i]), inLen - 1)] for i in range(n)]
	r2b = [0] * len(text)
	seen = [False] * len(text)
	for i in range(inLen):
		src = owner[i]
		if not seen[src]:
			seen[src] = True
			r2b[src] = max(0, min(int(outputPos[i]), max(0, n - 1))) if n else 0
	cursorOut = None
	if cursorAtEnd:
		cursorOut = n
	elif cur is not None:
		cursorOut = max(0, min(int(cur.value), n))
	return cells, b2r, r2b, cursorOut


def backTranslate(tables: Sequence[str], cells: Sequence[int], mode: int = 0) -> str:
	"""Traduce celdas braille (máscaras de puntos) a texto."""
	if not load():
		raise LouisError(_loadError or "liblouis no disponible")
	if not cells:
		return ""
	inLen = len(cells)
	inbuf = _newBuffer(inLen)
	for i, c in enumerate(cells):
		inbuf[i] = LOU_DOTS | (int(c) & 0xFF)
	size = inLen * 8 + 32
	with _lock:
		tableList = tableListBytes(tables)
		for _attempt in range(5):
			outbuf = _newBuffer(size)
			inlen = ctypes.c_int(inLen)
			outlen = ctypes.c_int(size)
			ok = _dll.lou_backTranslate(tableList, inbuf, ctypes.byref(inlen), outbuf, ctypes.byref(outlen), None, None, None, None, None, mode | DOTS_IO)
			if not ok:
				raise LouisError(f"lou_backTranslate falló con {tables}")
			if inlen.value >= inLen or outlen.value < size:
				break
			size *= 2
	return _decode(outbuf, outlen.value)


def hyphenate(tables: Sequence[str], word: str) -> list[int]:
	"""Posiciones de ``word`` antes de las que se puede partir la palabra.

	``tables`` debe incluir un diccionario de guiones (``hyph_es_ES.dic``).
	Devuelve una lista vacía si no se puede dividir.
	"""
	if not word or not load():
		return []
	inbuf, owner = _encode(word)
	inLen = len(owner)
	hyphens = ctypes.create_string_buffer(inLen + 1)
	with _lock:
		try:
			ok = _dll.lou_hyphenate(tableListBytes(tables), inbuf, inLen, hyphens, 0)
		except Exception:
			log.debug("Error dividiendo %r", word, exc_info=True)
			return []
	if not ok:
		return []
	out = []
	raw = hyphens.raw
	for i in range(1, inLen):
		if raw[i : i + 1] == b"1":
			out.append(owner[i])
	return sorted(set(p for p in out if 0 < p < len(word)))

