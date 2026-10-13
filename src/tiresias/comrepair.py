"""Herramienta de reparación de los registros COM de accesibilidad.

Algunos programas mal desinstalados (o «limpiadores» del registro) rompen el
registro de las bibliotecas COM que usan la accesibilidad de Windows y UI
Automation. Los síntomas: Tiresias no lee los navegadores, los menús o los
cuadros de diálogo, o lee «desconocido» en todas partes.

La herramienta vuelve a registrar esas bibliotecas del sistema con
``regsvr32`` (en ``System32`` y, en Windows de 64 bits, en ``SysWOW64``).
Necesita permiso de administrador: la interfaz la ejecuta como
``Tiresias.exe --repair-com`` elevado.
"""

from __future__ import annotations

import os
import subprocess

from .log import getLogger

log = getLogger("comRepair")

#: Bibliotecas que se vuelven a registrar (las que no existan se omiten).
DLLS = (
	"oleacc.dll",
	"oleaut32.dll",
	"actxprxy.dll",
	"UIAutomationCore.dll",
	"msctf.dll",
)
#: Bibliotecas fuera de las carpetas del sistema (relativas a Archivos de programa).
EXTRA = (os.path.join("Internet Explorer", "ieproxy.dll"),)


def systemDirs() -> list[str]:
	root = os.environ.get("SystemRoot", r"C:\Windows")
	dirs = [os.path.join(root, "System32")]
	wow = os.path.join(root, "SysWOW64")
	if os.path.isdir(wow):
		dirs.append(wow)
	return dirs


def candidates() -> list[tuple[str, str]]:
	"""Pares (regsvr32 que corresponde, biblioteca) que existen en este equipo."""
	out = []
	for d in systemDirs():
		regsvr = os.path.join(d, "regsvr32.exe")
		for dll in DLLS:
			path = os.path.join(d, dll)
			if os.path.isfile(path):
				out.append((regsvr, path))
	for base, sysdir in ((os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles"), systemDirs()[0]), (os.environ.get("ProgramFiles(x86)"), systemDirs()[-1])):
		if not base:
			continue
		for rel in EXTRA:
			path = os.path.join(base, rel)
			if os.path.isfile(path):
				out.append((os.path.join(sysdir, "regsvr32.exe"), path))
	return out


def repair() -> tuple[int, list[str]]:
	"""Registra las bibliotecas. Devuelve (correctas, fallidas)."""
	ok = 0
	failed: list[str] = []
	CREATE_NO_WINDOW = 0x08000000
	for regsvr, dll in candidates():
		try:
			r = subprocess.run([regsvr, "/s", dll], timeout=60, creationflags=CREATE_NO_WINDOW)
			if r.returncode == 0:
				ok += 1
			else:
				failed.append(dll)
		except (OSError, subprocess.TimeoutExpired):
			failed.append(dll)
	log.info("Reparación COM: %d bibliotecas registradas, %d fallidas", ok, len(failed))
	for dll in failed:
		log.warning("No se pudo registrar %s", dll)
	return ok, failed


def runFromCommandLine(noElevate: bool = False) -> int:
	"""``--repair-com``: código 0 si todo fue bien, 1 si algo falló, 5 sin permisos.

	Sin permisos de administrador pide el permiso y repite la orden en una copia
	elevada (con ``--no-elevate``, para no pedirlo en bucle si el control de
	cuentas está desactivado) y explica el resultado con un mensaje. Con
	``--no-elevate`` (la copia elevada, o la interfaz, que da su propio
	mensaje) no muestra nada y devuelve el código.
	"""
	from . import installer

	if installer.isElevated():
		_ok, failed = repair()
		return 1 if failed else 0
	log.error("La reparación COM necesita permisos de administrador")
	if noElevate:
		return 5
	try:
		code = runElevated()
	except OSError:
		log.error("No se obtuvo el permiso de administrador")
		code = 5
	_showResult(code)
	return code


def resultMessage(code: int) -> tuple[str, bool]:
	"""Texto para el usuario del resultado de la reparación y si es un error."""
	from .i18n import _

	if code == 0:
		return _("La reparación ha terminado. Reinicie Windows para que todos los programas usen los registros reparados."), False
	if code == 5:
		return _("La reparación de los registros COM necesita permiso de administrador y no se ha concedido."), True
	return _("Algunas bibliotecas no se pudieron registrar (código {code}). Los detalles están en el archivo logs\\ordenes.log de la carpeta de datos de Tiresias.").format(code=code), True


def _showResult(code: int) -> None:
	import ctypes

	from . import APP_NAME

	text, error = resultMessage(code)
	try:
		MB_ICONERROR, MB_ICONINFORMATION, MB_SETFOREGROUND = 0x10, 0x40, 0x10000
		ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, (MB_ICONERROR if error else MB_ICONINFORMATION) | MB_SETFOREGROUND)
	except Exception:
		log.exception("No se pudo mostrar el resultado de la reparación")


def runElevated() -> int:
	"""Ejecuta la reparación como administrador y espera al resultado (hilo propio)."""
	from . import installer

	exe, args = installer._launch()
	return installer.shellExecuteElevated(exe, installer.quoteArgs(args + ["--repair-com", "--no-elevate"]), wait=True)
