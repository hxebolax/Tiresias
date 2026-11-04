"""Rutas y atributos de archivos del Explorador de Windows.

- :class:`Contexto`: la ventana en primer plano cuando se pidió la acción (se
  captura antes de abrir un menú, que pasa a primer plano).
- :func:`rutas`: el elemento con el foco y la carpeta abierta en esa ventana
  del Explorador, con el objeto COM ``Shell.Application`` (como el original)
  o, si falla, con PowerShell. En el escritorio, el icono con el foco o la
  carpeta del escritorio.
- Listado ordenado de una carpeta (carpetas primero, como ``dir /og /on /b``)
  y ocultar o mostrar elementos.
"""

from __future__ import annotations

import ctypes
import os
import stat
from ctypes import wintypes
from dataclasses import dataclass

from . import ejecutor

FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
SHCNE_ATTRIBUTES = 0x00000800
SHCNE_UPDATEDIR = 0x00001000
SHCNE_UPDATEITEM = 0x00002000
SHCNF_PATHW = 0x0005
#: Clases de la ventana del escritorio.
CLASES_ESCRITORIO = ("Progman", "WorkerW")

MSG_ACTIVE_EXPLORADOR = "Active una ventana del explorador antes de ejecutar esta acción"


@dataclass
class Contexto:
	"""La ventana activa cuando se pidió la acción."""

	hwnd: int = 0
	esExplorador: bool = False
	clase: str = ""
	titulo: str = ""
	nombreFoco: str = ""

	@property
	def esEscritorio(self) -> bool:
		return self.esExplorador and self.clase in CLASES_ESCRITORIO


def capturarContexto(leerFoco: bool = True) -> Contexto:
	"""Contexto de la ventana en primer plano.

	``leerFoco``: lee también el nombre del objeto con el foco (solo en el hilo
	del núcleo; desde el menú de Tiresias no se lee).
	"""
	from tiresias import winapi

	ctx = Contexto()
	try:
		ctx.hwnd = int(winapi.getForegroundWindow() or 0)
		ctx.esExplorador = winapi.getProcessName(winapi.getWindowProcessId(ctx.hwnd)) == "explorer"
		ctx.clase = winapi.getClassName(ctx.hwnd) or ""
		ctx.titulo = winapi.getWindowText(ctx.hwnd) or ""
	except Exception:
		pass
	if leerFoco and ctx.esExplorador:
		try:
			from tiresias import api

			foco = api.getFocusObject()
			ctx.nombreFoco = str(foco.name or "") if foco is not None else ""
		except Exception:
			ctx.nombreFoco = ""
	return ctx


# ====================================================================== rutas
def carpetaEscritorio() -> str:
	try:
		buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
		CSIDL_DESKTOPDIRECTORY = 0x10
		if ctypes.WinDLL("shell32").SHGetFolderPathW(None, CSIDL_DESKTOPDIRECTORY, None, 0, buf) == 0 and buf.value:
			return buf.value
	except Exception:
		pass
	return os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")


def _existe(ruta) -> str | None:
	if not ruta:
		return None
	ruta = str(ruta)
	return ruta if os.path.exists(ruta) else None


def _elegirVentana(candidatas: list, titulo: str):
	"""Con pestañas (Windows 11) varias ventanas COM comparten el HWND: se elige
	la pestaña cuyo nombre coincide con el título de la ventana."""
	if len(candidatas) <= 1 or not titulo:
		return candidatas[0] if candidatas else None
	for v in candidatas:
		try:
			nombre = str(v.LocationName or "")
		except Exception:
			continue
		if nombre and (titulo == nombre or titulo.startswith(nombre + " ")):
			return v
	return candidatas[0]


def _rutasCom(ctx: Contexto) -> tuple[str | None, str | None] | None:
	"""(foco, carpeta) con ``Shell.Application``; ``None`` si la ventana no está o falla COM."""
	try:
		from comtypes.client import CreateObject

		shell = CreateObject("Shell.Application", dynamic=True)
		ventanas = shell.Windows()
		candidatas = []
		for i in range(int(ventanas.Count)):
			try:
				v = ventanas.Item(i)
				if v is not None and int(v.HWND) == int(ctx.hwnd):
					candidatas.append(v)
			except Exception:
				continue
		v = _elegirVentana(candidatas, ctx.titulo)
		if v is None:
			return None
		doc = v.Document
		foco = None
		try:
			item = doc.FocusedItem
			if item is not None:
				foco = _existe(item.Path)
		except Exception:
			foco = None
		try:
			carpeta = _existe(doc.Folder.Self.Path)
		except Exception:
			carpeta = None
		return foco, carpeta
	except Exception:
		return _rutasPowerShell(ctx)


_PS_RUTAS = (
	"[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
	"(New-Object -ComObject 'Shell.Application').Windows() | "
	'ForEach-Object { "$($_.HWND)|$($_.Document.FocusedItem.Path)|$($_.Document.Folder.Self.Path)" }'
)


def analizarSalidaPowerShell(salida: str, hwnd: int) -> tuple[str | None, str | None] | None:
	"""Busca la ventana ``hwnd`` en la salida de :data:`_PS_RUTAS`."""
	for linea in (salida or "").splitlines():
		partes = linea.strip().split("|")
		if len(partes) != 3:
			continue
		if partes[0].strip() == str(hwnd):
			return _existe(partes[1].strip()), _existe(partes[2].strip())
	return None


def _rutasPowerShell(ctx: Contexto) -> tuple[str | None, str | None] | None:
	codigo, salida = ejecutor.oculto(ejecutor.psArgumentos(_PS_RUTAS), 15)
	if codigo != 0:
		return None
	return analizarSalidaPowerShell(salida, ctx.hwnd)


def rutasEscritorio(nombreFoco: str) -> tuple[str | None, str | None]:
	escritorio = carpetaEscritorio()
	foco = _existe(os.path.join(escritorio, nombreFoco)) if nombreFoco else None
	return foco, _existe(escritorio)


def rutas(ctx: Contexto) -> tuple[str | None, str | None]:
	"""(ruta del elemento con el foco, carpeta abierta) de la ventana del Explorador.

	Usa COM: llamar en el hilo de la interfaz.
	"""
	if not ctx.esExplorador:
		return None, None
	if ctx.esEscritorio:
		return rutasEscritorio(ctx.nombreFoco)
	res = _rutasCom(ctx)
	if res is None:
		return None, None
	return res


def carpetaDe(ruta: str | None) -> str | None:
	"""La carpeta: la propia ruta si es una carpeta, o la que contiene el archivo."""
	if not ruta:
		return None
	if os.path.isdir(ruta):
		return ruta
	padre = os.path.dirname(ruta)
	return padre if padre and os.path.isdir(padre) else None


# ====================================================================== listado
def _atributos(entrada: os.DirEntry) -> int:
	try:
		return int(getattr(entrada.stat(follow_symlinks=False), "st_file_attributes", 0))
	except OSError:
		return 0


def listarCarpeta(carpeta: str) -> list[str]:
	"""Nombres de los elementos visibles: carpetas primero y luego archivos, por nombre.

	Como ``dir /og /on /b``: sin los elementos ocultos ni los de sistema.
	"""
	carpetas: list[str] = []
	archivos: list[str] = []
	with os.scandir(carpeta) as it:
		for e in it:
			if _atributos(e) & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM):
				continue
			try:
				esCarpeta = e.is_dir()
			except OSError:
				esCarpeta = False
			(carpetas if esCarpeta else archivos).append(e.name)
	clave = str.casefold
	return sorted(carpetas, key=clave) + sorted(archivos, key=clave)


# ====================================================================== atributos
def atributos(ruta: str) -> int:
	return int(getattr(os.stat(ruta, follow_symlinks=False), "st_file_attributes", 0))


def estaOculto(ruta: str) -> bool:
	return bool(atributos(ruta) & FILE_ATTRIBUTE_HIDDEN)


def _ponerAtributos(ruta: str, valor: int) -> None:
	k32 = ctypes.WinDLL("kernel32", use_last_error=True)
	k32.SetFileAttributesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
	k32.SetFileAttributesW.restype = wintypes.BOOL
	if not k32.SetFileAttributesW(ruta, valor):
		raise ctypes.WinError(ctypes.get_last_error())


def _attribElevado(ruta: str, ocultar: bool) -> None:
	"""``attrib`` como administrador (elementos protegidos)."""
	orden = 'attrib {} "{}"'.format("+h" if ocultar else "-h", ruta)
	codigo = ejecutor.elevado(ejecutor.CMD, ejecutor.cmdParametros(orden), esperar=True)
	if codigo != 0 or estaOculto(ruta) != ocultar:
		raise OSError(f"attrib terminó con el código {codigo}")


def cambiarOculto(ruta: str, ocultar: bool) -> None:
	"""Pone o quita el atributo oculto (como administrador si hace falta).

	Puede lanzar :class:`ejecutor.Cancelado` u ``OSError``.
	"""
	actual = atributos(ruta)
	nuevo = (actual | FILE_ATTRIBUTE_HIDDEN) if ocultar else (actual & ~FILE_ATTRIBUTE_HIDDEN)
	# SetFileAttributes no acepta FILE_ATTRIBUTE_NORMAL junto a otros: se quitan
	# los bits que no se pueden poner (directorio, comprimido, etc.).
	nuevo &= 0x0000FFFF & ~(stat.FILE_ATTRIBUTE_DIRECTORY | stat.FILE_ATTRIBUTE_COMPRESSED | stat.FILE_ATTRIBUTE_ENCRYPTED | stat.FILE_ATTRIBUTE_REPARSE_POINT | stat.FILE_ATTRIBUTE_SPARSE_FILE)
	try:
		_ponerAtributos(ruta, nuevo or stat.FILE_ATTRIBUTE_NORMAL)
	except PermissionError:
		_attribElevado(ruta, ocultar)
	avisarCambio(ruta)


def ocultosEn(carpeta: str) -> list[str]:
	"""Elementos ocultos (no de sistema) que hay directamente en ``carpeta``."""
	salida = []
	with os.scandir(carpeta) as it:
		for e in it:
			a = _atributos(e)
			if a & FILE_ATTRIBUTE_HIDDEN and not a & FILE_ATTRIBUTE_SYSTEM:
				salida.append(e.path)
	return sorted(salida, key=str.casefold)


def avisarCambio(ruta: str) -> None:
	"""Avisa al Explorador para que actualice la vista (en lugar de pulsar F5)."""
	try:
		shell32 = ctypes.WinDLL("shell32")
		shell32.SHChangeNotify.argtypes = [wintypes.LONG, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p]
		shell32.SHChangeNotify.restype = None
		buf = ctypes.create_unicode_buffer(ruta)
		shell32.SHChangeNotify(SHCNE_ATTRIBUTES, SHCNF_PATHW, ctypes.cast(buf, ctypes.c_void_p), None)
		shell32.SHChangeNotify(SHCNE_UPDATEITEM, SHCNF_PATHW, ctypes.cast(buf, ctypes.c_void_p), None)
		padre = os.path.dirname(ruta)
		if padre:
			pbuf = ctypes.create_unicode_buffer(padre)
			shell32.SHChangeNotify(SHCNE_UPDATEDIR, SHCNF_PATHW, ctypes.cast(pbuf, ctypes.c_void_p), None)
	except Exception:
		pass
