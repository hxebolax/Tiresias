"""Acceso al portapapeles de Windows con todos sus formatos.

El historial de TCA-Portapapeles no guarda solo el texto: guarda todos los
formatos que tenga lo copiado (texto con formato, HTML, RTF, imágenes en DIB,
archivos y carpetas...) y al pegarlo los restaura tal cual.

Se usan instancias propias de ``user32``, ``kernel32`` y ``shell32``
(``ctypes.WinDLL``): así los tipos de argumentos que se fijan aquí no cambian
los de ``ctypes.windll`` que usan Tiresias y otros complementos.
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from dataclasses import dataclass, field

CF_TEXT = 1
CF_BITMAP = 2
CF_METAFILEPICT = 3
CF_OEMTEXT = 7
CF_DIB = 8
CF_PALETTE = 9
CF_UNICODETEXT = 13
CF_ENHMETAFILE = 14
CF_HDROP = 15
CF_DIBV5 = 17
CF_OWNERDISPLAY = 0x80
CF_DSPBITMAP = 0x82
CF_DSPMETAFILEPICT = 0x83
CF_DSPENHMETAFILE = 0x8E

#: Formatos cuyo dato no es memoria global (objetos GDI, metarchivos...): no se pueden copiar byte a byte.
FORMATOS_NO_GLOBALES = frozenset({CF_BITMAP, CF_METAFILEPICT, CF_PALETTE, CF_ENHMETAFILE, CF_OWNERDISPLAY, CF_DSPBITMAP, CF_DSPMETAFILEPICT, CF_DSPENHMETAFILE})
#: Formatos registrados que solo valen dentro del programa que los puso (punteros OLE).
FORMATOS_PRIVADOS = frozenset({"DataObject", "Ole Private Data", "OlePrivateData"})
#: Tamaño máximo de un formato y de un elemento completo (bytes).
MAX_FORMATO = 10 * 1024 * 1024
MAX_ELEMENTO = 32 * 1024 * 1024

#: Textos que algunos procesos de limpieza dejan en el portapapeles (``echo off | clip``).
TEXTOS_DE_LIMPIEZA = frozenset({"off", "echo off", "echo está desactivado.", "echo está desactivado", "echo is off.", "echo is off"})

GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040

_dlls = None


def _api():
	"""Funciones de Windows con sus tipos (se cargan la primera vez)."""
	global _dlls
	if _dlls is not None:
		return _dlls
	u = ctypes.WinDLL("user32", use_last_error=True)
	k = ctypes.WinDLL("kernel32", use_last_error=True)
	s = ctypes.WinDLL("shell32", use_last_error=True)
	u.OpenClipboard.argtypes = [wintypes.HWND]
	u.OpenClipboard.restype = wintypes.BOOL
	u.CloseClipboard.argtypes = []
	u.CloseClipboard.restype = wintypes.BOOL
	u.EmptyClipboard.argtypes = []
	u.EmptyClipboard.restype = wintypes.BOOL
	u.GetClipboardData.argtypes = [wintypes.UINT]
	u.GetClipboardData.restype = wintypes.HANDLE
	u.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
	u.SetClipboardData.restype = wintypes.HANDLE
	u.EnumClipboardFormats.argtypes = [wintypes.UINT]
	u.EnumClipboardFormats.restype = wintypes.UINT
	u.GetClipboardFormatNameW.argtypes = [wintypes.UINT, wintypes.LPWSTR, ctypes.c_int]
	u.GetClipboardFormatNameW.restype = ctypes.c_int
	u.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
	u.IsClipboardFormatAvailable.restype = wintypes.BOOL
	u.GetClipboardSequenceNumber.argtypes = []
	u.GetClipboardSequenceNumber.restype = wintypes.DWORD
	k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
	k.GlobalAlloc.restype = wintypes.HGLOBAL
	k.GlobalLock.argtypes = [wintypes.HGLOBAL]
	k.GlobalLock.restype = wintypes.LPVOID
	k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
	k.GlobalUnlock.restype = wintypes.BOOL
	k.GlobalSize.argtypes = [wintypes.HGLOBAL]
	k.GlobalSize.restype = ctypes.c_size_t
	k.GlobalFree.argtypes = [wintypes.HGLOBAL]
	k.GlobalFree.restype = wintypes.HGLOBAL
	s.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
	s.DragQueryFileW.restype = wintypes.UINT
	_dlls = (u, k, s)
	return _dlls


# ====================================================================== datos
@dataclass
class Elemento:
	"""Lo que había en el portapapeles: texto para mostrar y todos sus formatos."""

	texto: str
	formatos: dict[int, bytes] = field(default_factory=dict)
	archivos: list[str] = field(default_factory=list)
	instante: float = field(default_factory=time.time)

	@property
	def tieneFormatos(self) -> bool:
		return bool(self.formatos)


def textoParaMostrar(texto: str | None, archivos: list[str], formatos: dict[int, bytes] | None = None) -> str:
	"""Texto con que se muestra un elemento: los nombres de los archivos, el texto o el tipo de contenido."""
	if archivos:
		nombres = [os.path.basename(a.rstrip("\\/")) or a for a in archivos]
		if len(nombres) == 1:
			return nombres[0]
		return f"({len(nombres)}) Archivos: " + ", ".join(nombres)
	if texto:
		return texto
	formatos = formatos or {}
	if CF_DIB in formatos or CF_DIBV5 in formatos:
		return "(Imagen)"
	return "(Contenido con formato)"


def esTextoDeLimpieza(texto: str) -> bool:
	return texto.strip().lower() in TEXTOS_DE_LIMPIEZA


def archivosDeDropfiles(datos: bytes) -> list[str]:
	"""Rutas de una estructura DROPFILES (formato CF_HDROP) guardada como bytes."""
	if len(datos) < 20:
		return []
	offset = int.from_bytes(datos[0:4], "little")
	ancho = int.from_bytes(datos[16:20], "little")
	if offset <= 0 or offset >= len(datos):
		return []
	cuerpo = datos[offset:]
	if ancho:
		texto = cuerpo.decode("utf-16-le", errors="replace")
	else:
		texto = cuerpo.decode("mbcs", errors="replace")
	return [p for p in texto.split("\0") if p]


def textoUnicode(datos: bytes) -> str:
	return datos.decode("utf-16-le", errors="replace").split("\0", 1)[0]


# ====================================================================== Windows
def secuencia() -> int:
	"""Número de secuencia del portapapeles (cambia con cada escritura)."""
	try:
		return int(_api()[0].GetClipboardSequenceNumber())
	except Exception:
		return 0


def _abrir(intentos: int = 10, espera: float = 0.01) -> bool:
	u = _api()[0]
	for _i in range(intentos):
		if u.OpenClipboard(None):
			return True
		time.sleep(espera)
	return False


def _nombreFormato(fmt: int) -> str:
	u = _api()[0]
	buf = ctypes.create_unicode_buffer(256)
	n = u.GetClipboardFormatNameW(fmt, buf, 256)
	return buf.value if n > 0 else ""


def _leerGlobal(handle) -> bytes | None:
	_u, k, _s = _api()
	tam = k.GlobalSize(handle)
	if not tam or tam > MAX_FORMATO:
		return None
	p = k.GlobalLock(handle)
	if not p:
		return None
	try:
		return ctypes.string_at(p, tam)
	finally:
		k.GlobalUnlock(handle)


def _archivosDeHandle(handle) -> list[str]:
	s = _api()[2]
	cuenta = s.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
	rutas = []
	for i in range(cuenta):
		largo = s.DragQueryFileW(handle, i, None, 0)
		buf = ctypes.create_unicode_buffer(largo + 1)
		s.DragQueryFileW(handle, i, buf, largo + 1)
		rutas.append(buf.value)
	return rutas


def leerTodo() -> Elemento | None:
	"""Lee todos los formatos del portapapeles (``None`` si está vacío o no se puede abrir).

	Puede tardar si la aplicación que copió genera los formatos al pedirlos:
	llamar fuera del hilo del núcleo.
	"""
	u = _api()[0]
	if not _abrir():
		return None
	formatos: dict[int, bytes] = {}
	archivos: list[str] = []
	texto = None
	total = 0
	try:
		fmt = u.EnumClipboardFormats(0)
		while fmt:
			if fmt not in FORMATOS_NO_GLOBALES and not (0x200 <= fmt <= 0x3FF) and (fmt < 0xC000 or _nombreFormato(fmt) not in FORMATOS_PRIVADOS):
				handle = u.GetClipboardData(fmt)
				if handle:
					datos = _leerGlobal(handle)
					if datos:
						if fmt == CF_HDROP:
							archivos = _archivosDeHandle(handle)
						if fmt == CF_UNICODETEXT:
							texto = textoUnicode(datos)
						if total + len(datos) <= MAX_ELEMENTO or fmt in (CF_UNICODETEXT, CF_HDROP):
							formatos[fmt] = datos
							total += len(datos)
			fmt = u.EnumClipboardFormats(fmt)
	except Exception:
		pass
	finally:
		u.CloseClipboard()
	if texto is None and not formatos:
		return None
	return Elemento(textoParaMostrar(texto, archivos, formatos), formatos, archivos)


def escribirTodo(elemento: Elemento) -> bool:
	"""Pone en el portapapeles todos los formatos de ``elemento`` (o su texto si no tiene)."""
	if not elemento.formatos:
		return escribirTexto(elemento.texto)
	u, k, _s = _api()
	if not _abrir():
		return False
	try:
		u.EmptyClipboard()
		puesto = False
		for fmt, datos in elemento.formatos.items():
			h = k.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(datos))
			if not h:
				continue
			p = k.GlobalLock(h)
			if not p:
				k.GlobalFree(h)
				continue
			ctypes.memmove(p, datos, len(datos))
			k.GlobalUnlock(h)
			if u.SetClipboardData(fmt, h):
				puesto = True
			else:
				k.GlobalFree(h)
		return puesto
	finally:
		u.CloseClipboard()


def escribirTexto(texto: str) -> bool:
	u, k, _s = _api()
	datos = (texto + "\0").encode("utf-16-le")
	if not _abrir():
		return False
	try:
		u.EmptyClipboard()
		h = k.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(datos))
		if not h:
			return False
		p = k.GlobalLock(h)
		if not p:
			k.GlobalFree(h)
			return False
		ctypes.memmove(p, datos, len(datos))
		k.GlobalUnlock(h)
		if not u.SetClipboardData(CF_UNICODETEXT, h):
			k.GlobalFree(h)
			return False
		return True
	finally:
		u.CloseClipboard()


def leerTextoOArchivos() -> str | None:
	"""Texto del portapapeles o, si hay archivos copiados, sus nombres (``None`` si no hay ninguno)."""
	u = _api()[0]
	hayTexto = u.IsClipboardFormatAvailable(CF_UNICODETEXT)
	hayArchivos = u.IsClipboardFormatAvailable(CF_HDROP)
	if not hayTexto and not hayArchivos:
		return None
	if not _abrir(10, 0.005):
		return None
	try:
		if hayArchivos:
			h = u.GetClipboardData(CF_HDROP)
			if h:
				rutas = _archivosDeHandle(h)
				if rutas:
					return textoParaMostrar(None, rutas)
		if hayTexto:
			h = u.GetClipboardData(CF_UNICODETEXT)
			if h:
				datos = _leerGlobal(h)
				if datos:
					return textoUnicode(datos)
	finally:
		u.CloseClipboard()
	return None


def hayTexto() -> bool:
	try:
		return bool(_api()[0].IsClipboardFormatAvailable(CF_UNICODETEXT))
	except Exception:
		return False
