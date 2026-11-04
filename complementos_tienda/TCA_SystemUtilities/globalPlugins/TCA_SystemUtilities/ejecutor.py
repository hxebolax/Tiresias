"""Ejecución de programas de Windows para TCA SystemUtilities.

- :func:`abrir`: ``ShellExecute`` normal (abre programas, carpetas, paneles
  de control y direcciones ``ms-settings:``).
- :func:`elevado`: ``ShellExecuteEx`` con el verbo «runas» (pide permiso con
  el Control de cuentas de usuario), visible u oculto, esperando o no a que
  termine. Si el usuario no da el permiso lanza :class:`Cancelado`.
- :func:`oculto`: ejecuta un programa sin ventana y devuelve su código de
  salida y lo que ha escrito.

Las tres son variables del módulo: las pruebas las sustituyen y no se ejecuta
nada real. No usa wx.
"""

from __future__ import annotations

import base64
import ctypes
import os
import subprocess
import threading
from collections.abc import Callable
from ctypes import wintypes

SW_HIDE = 0
SW_SHOWNORMAL = 1
CREATE_NO_WINDOW = 0x08000000
ERROR_CANCELLED = 1223
SEE_MASK_NOCLOSEPROCESS = 0x40
SEE_MASK_NOASYNC = 0x100
INFINITE = 0xFFFFFFFF


class Cancelado(Exception):
	"""El usuario no concedió el permiso de administrador."""


def windows(*partes: str) -> str:
	"""Ruta dentro de la carpeta de Windows."""
	return os.path.join(os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows", *partes)


def system32(*partes: str) -> str:
	"""Ruta dentro de System32 (Tiresias es de 64 bits: no hay redirección WOW64)."""
	return windows("System32", *partes)


CMD = system32("cmd.exe")
POWERSHELL = system32("WindowsPowerShell", "v1.0", "powershell.exe")
SHUTDOWN = system32("shutdown.exe")
TASKKILL = system32("taskkill.exe")


def powershell() -> str:
	return POWERSHELL if os.path.isfile(POWERSHELL) else "powershell.exe"


# ====================================================================== parámetros
def cmdParametros(orden: str, pausa: bool = False, mantener: bool = False) -> str:
	"""Parámetros de ``cmd.exe`` para ejecutar ``orden``.

	La orden va entre comillas exteriores (``/c "..."``): cmd las quita y deja
	intactas las comillas interiores de las rutas. ``pausa`` añade «pause» para
	que se pueda leer el resultado antes de que se cierre la ventana.
	"""
	if pausa:
		orden += " & pause"
	return '{} "{}"'.format("/k" if mantener else "/c", orden)


def psCodificado(script: str) -> str:
	"""El script de PowerShell en Base64 (UTF-16LE), para ``-EncodedCommand``."""
	return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def psArgumentos(script: str) -> list[str]:
	"""Argumentos para ejecutar ``script`` con Windows PowerShell sin ventana."""
	return [powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", psCodificado(script)]


def psParametros(script: str) -> str:
	"""Los mismos argumentos como cadena (para :func:`elevado`)."""
	return "-NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand " + psCodificado(script)


def decodificar(datos: bytes | None) -> str:
	"""Texto de la salida de un programa de consola.

	Unos escriben UTF-8 y otros (systeminfo, MpCmdRun...) la página de códigos
	OEM de la consola cuando la salida no es una consola.
	"""
	if not datos:
		return ""
	if datos.startswith(b"\xff\xfe"):
		return datos[2:].decode("utf-16-le", "replace")
	if datos.startswith(b"\xef\xbb\xbf"):
		datos = datos[3:]
	for codificacion in ("utf-8", "oem", "mbcs"):
		try:
			return datos.decode(codificacion)
		except (UnicodeDecodeError, LookupError):
			continue
	return datos.decode("latin-1", "replace")


# ====================================================================== Win32
class SHELLEXECUTEINFOW(ctypes.Structure):
	_fields_ = [
		("cbSize", wintypes.DWORD),
		("fMask", ctypes.c_ulong),
		("hwnd", wintypes.HWND),
		("lpVerb", wintypes.LPCWSTR),
		("lpFile", wintypes.LPCWSTR),
		("lpParameters", wintypes.LPCWSTR),
		("lpDirectory", wintypes.LPCWSTR),
		("nShow", ctypes.c_int),
		("hInstApp", wintypes.HINSTANCE),
		("lpIDList", ctypes.c_void_p),
		("lpClass", wintypes.LPCWSTR),
		("hkeyClass", wintypes.HKEY),
		("dwHotKey", wintypes.DWORD),
		("hIcon", wintypes.HANDLE),
		("hProcess", wintypes.HANDLE),
	]


_dlls: dict[str, ctypes.WinDLL] = {}


def _dll(nombre: str) -> ctypes.WinDLL:
	"""Instancias propias: no se cambian los argtypes compartidos de ctypes.windll."""
	dll = _dlls.get(nombre)
	if dll is not None:
		return dll
	dll = ctypes.WinDLL(nombre, use_last_error=True)
	if nombre == "shell32":
		dll.ShellExecuteW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int]
		dll.ShellExecuteW.restype = ctypes.c_void_p
		dll.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
		dll.ShellExecuteExW.restype = wintypes.BOOL
	elif nombre == "kernel32":
		dll.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
		dll.WaitForSingleObject.restype = wintypes.DWORD
		dll.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
		dll.GetExitCodeProcess.restype = wintypes.BOOL
		dll.CloseHandle.argtypes = [wintypes.HANDLE]
		dll.CloseHandle.restype = wintypes.BOOL
	_dlls[nombre] = dll
	return dll


class _Com:
	"""COM en el hilo actual mientras dura el bloque (ShellExecute lo necesita)."""

	def __enter__(self) -> _Com:
		self.hr = _dll("ole32").CoInitializeEx(None, 0x2 | 0x4)
		return self

	def __exit__(self, *exc) -> None:
		if self.hr in (0, 1):
			_dll("ole32").CoUninitialize()


def _abrir(archivo: str, parametros: str | None = None, carpeta: str | None = None, verbo: str = "open", mostrar: int = SW_SHOWNORMAL) -> bool:
	with _Com():
		res = _dll("shell32").ShellExecuteW(None, verbo, archivo, parametros, carpeta, mostrar)
	return int(res or 0) > 32


def _elevado(archivo: str, parametros: str = "", esperar: bool = False, mostrar: int = SW_HIDE, carpeta: str | None = None) -> int:
	info = SHELLEXECUTEINFOW()
	info.cbSize = ctypes.sizeof(info)
	info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
	info.lpVerb = "runas"
	info.lpFile = archivo
	info.lpParameters = parametros or None
	info.lpDirectory = carpeta
	info.nShow = mostrar
	with _Com():
		ok = _dll("shell32").ShellExecuteExW(ctypes.byref(info))
		error = ctypes.get_last_error()
	if not ok:
		if error == ERROR_CANCELLED:
			raise Cancelado()
		raise OSError(error, f"No se pudo ejecutar {os.path.basename(archivo)} como administrador")
	kernel32 = _dll("kernel32")
	if not info.hProcess:
		return 0
	try:
		if not esperar:
			return 0
		kernel32.WaitForSingleObject(info.hProcess, INFINITE)
		codigo = wintypes.DWORD()
		kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(codigo))
		return int(codigo.value)
	finally:
		kernel32.CloseHandle(info.hProcess)


def _oculto(args: list[str], timeout: float = 120) -> tuple[int, str]:
	si = subprocess.STARTUPINFO()
	si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
	try:
		proc = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, startupinfo=si, creationflags=CREATE_NO_WINDOW, timeout=timeout)
	except subprocess.TimeoutExpired as e:
		return -1, decodificar(e.stdout)
	except OSError as e:
		return -1, str(e)
	salida = proc.stdout or b""
	if not salida.strip():
		salida = proc.stderr or b""
	return proc.returncode, decodificar(salida)


#: Se pueden sustituir en las pruebas.
abrir: Callable[..., bool] = _abrir
elevado: Callable[..., int] = _elevado
oculto: Callable[..., tuple[int, str]] = _oculto


def enHilo(func: Callable, *args) -> threading.Thread:
	"""Ejecuta ``func`` en un hilo propio (las pruebas lo sustituyen por una llamada directa)."""
	t = threading.Thread(target=func, args=args, name="TCASystemUtilities", daemon=True)
	t.start()
	return t
