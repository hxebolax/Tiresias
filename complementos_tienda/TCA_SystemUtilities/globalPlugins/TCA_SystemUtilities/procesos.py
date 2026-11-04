"""Procesos: tareas que no responden, cerrar todas las aplicaciones y terminar por nombre.

Nunca se termina Tiresias (ni sus procesos auxiliares ni los que lo
iniciaron), los lectores de pantalla ni los componentes de Windows (los
programas de la carpeta de Windows). Lo que no se puede terminar sin permisos
se reintenta con ``taskkill`` como administrador.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass, field

from . import ejecutor

#: Procesos que no se cierran nunca (sin extensión, en minúsculas): lectores de
#: pantalla y Tiresias aunque se ejecute desde otra carpeta.
PROTEGIDOS = {
	"tiresias",
	"nvda",
	"nvda_slave",
	"nvda_nouiaccess",
	"nvda_uiaccess",
	"nvda_dmp",
	"jfw",
	"fsreader",
	"fssupport",
	"jhookldr",
	"narrator",
}


@dataclass
class Resultado:
	terminados: list[str] = field(default_factory=list)
	fallidos: list[str] = field(default_factory=list)
	#: El usuario no dio el permiso de administrador para los que faltaban.
	cancelado: bool = False


def _psutil():
	import psutil

	return psutil


def _nombreBase(nombre: str) -> str:
	return os.path.splitext(nombre or "")[0].lower()


def procesosDeTiresias() -> set[int]:
	"""El proceso de Tiresias, sus descendientes y sus antecesores."""
	psutil = _psutil()
	pids = {os.getpid()}
	try:
		yo = psutil.Process(os.getpid())
		for hijo in yo.children(recursive=True):
			pids.add(hijo.pid)
		for padre in yo.parents():
			pids.add(padre.pid)
	except Exception:
		pass
	return pids


def esDeWindows(exe: str) -> bool:
	"""El ejecutable está en la carpeta de Windows (componente del sistema)."""
	if not exe:
		return True
	raiz = os.path.normcase(os.path.abspath(ejecutor.windows())) + os.sep
	return os.path.normcase(os.path.abspath(exe)).startswith(raiz)


def esProtegido(pid: int, nombre: str, protegidos: set[int]) -> bool:
	return pid in protegidos or pid in (0, 4) or _nombreBase(nombre) in PROTEGIDOS


# ====================================================================== terminar
def _terminar(pids: dict[int, str], timeout: float = 3.0) -> Resultado:
	"""Termina los procesos ``pid → nombre``; los denegados se reintentan como administrador."""
	psutil = _psutil()
	res = Resultado()
	denegados: dict[int, str] = {}
	for pid, nombre in pids.items():
		try:
			p = psutil.Process(pid)
			p.kill()
			try:
				p.wait(timeout)
			except psutil.TimeoutExpired:
				pass
			res.terminados.append(nombre)
		except psutil.NoSuchProcess:
			res.terminados.append(nombre)
		except psutil.AccessDenied:
			denegados[pid] = nombre
		except Exception:
			res.fallidos.append(nombre)
	if denegados:
		args = " ".join(f"/pid {pid}" for pid in denegados)
		try:
			ejecutor.elevado(ejecutor.TASKKILL, "/f " + args, esperar=True)
		except ejecutor.Cancelado:
			res.cancelado = True
		except OSError:
			pass
		for pid, nombre in denegados.items():
			if psutil.pid_exists(pid):
				res.fallidos.append(nombre)
			else:
				res.terminados.append(nombre)
	return res


def aplicacionesDelUsuario() -> dict[int, str]:
	"""Procesos del usuario que no son de Windows ni están protegidos (``pid → nombre``)."""
	psutil = _psutil()
	protegidos = procesosDeTiresias()
	try:
		usuario = psutil.Process(os.getpid()).username()
	except Exception:
		usuario = None
	salida: dict[int, str] = {}
	for p in psutil.process_iter(["pid", "name", "username", "exe"]):
		try:
			info = p.info
			if usuario is None or info.get("username") != usuario:
				continue
			nombre = info.get("name") or ""
			if esProtegido(info["pid"], nombre, protegidos) or esDeWindows(info.get("exe") or ""):
				continue
			salida[info["pid"]] = nombre
		except Exception:
			continue
	return salida


def cerrarTodas() -> Resultado:
	"""Cierra a la fuerza todas las aplicaciones del usuario (menos las protegidas)."""
	return _terminar(aplicacionesDelUsuario())


def coincidentes(nombre: str) -> dict[int, str]:
	"""Procesos cuyo nombre empieza por ``nombre`` (como ``taskkill /im nombre*``)."""
	psutil = _psutil()
	buscado = nombre.strip().lower()
	if not buscado:
		return {}
	protegidos = procesosDeTiresias()
	salida: dict[int, str] = {}
	for p in psutil.process_iter(["pid", "name"]):
		try:
			n = p.info.get("name") or ""
			if n.lower().startswith(buscado) and p.info["pid"] not in protegidos and p.info["pid"] not in (0, 4):
				salida[p.info["pid"]] = n
		except Exception:
			continue
	return salida


def terminarPorNombre(nombre: str) -> Resultado:
	return _terminar(coincidentes(nombre))


# ====================================================================== tareas que no responden
def ventanasColgadas() -> dict[int, str]:
	"""Procesos con alguna ventana visible que no responde (``pid → nombre``)."""
	user32 = ctypes.WinDLL("user32")
	user32.IsHungAppWindow.argtypes = [wintypes.HWND]
	user32.IsHungAppWindow.restype = wintypes.BOOL
	user32.IsWindowVisible.argtypes = [wintypes.HWND]
	user32.IsWindowVisible.restype = wintypes.BOOL
	user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
	user32.GetWindowThreadProcessId.restype = wintypes.DWORD
	pids: set[int] = set()
	WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

	def visitar(hwnd, _lparam):
		try:
			if user32.IsWindowVisible(hwnd) and user32.IsHungAppWindow(hwnd):
				pid = wintypes.DWORD()
				user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
				if pid.value:
					pids.add(int(pid.value))
		except Exception:
			pass
		return True

	user32.EnumWindows(WNDENUMPROC(visitar), 0)
	protegidos = procesosDeTiresias()
	salida: dict[int, str] = {}
	psutil = _psutil()
	for pid in pids:
		if pid in protegidos:
			continue
		try:
			salida[pid] = psutil.Process(pid).name()
		except Exception:
			salida[pid] = str(pid)
	return salida


def cerrarNoResponden() -> Resultado:
	return _terminar(ventanasColgadas())
