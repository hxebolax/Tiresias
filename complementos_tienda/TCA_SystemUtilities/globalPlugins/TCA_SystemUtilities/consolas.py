"""Lanzador de consolas: CMD, PowerShell, Windows Terminal y Git Bash.

Cada consola se puede abrir en una carpeta, normal o como administrador.
Módulo original de Héctor J. Benítez Corredera para TCA SystemUtilities.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from . import ejecutor

#: Tipo → (etiqueta normal, etiqueta como administrador), en el orden del original.
ETIQUETAS = {
	"cmd": ("Abrir CMD aquí", "Abrir CMD como Administrador"),
	"powershell": ("Abrir PowerShell aquí", "Abrir PowerShell como Administrador"),
	"wt": ("Abrir Windows Terminal aquí", "Abrir Windows Terminal como Administrador"),
	"git-bash": ("Abrir git-bash aquí", "Abrir git-bash como Administrador"),
}


@dataclass(frozen=True)
class Opcion:
	etiqueta: str
	tipo: str
	admin: bool
	ejecutable: str


def rutaWindowsTerminal() -> str:
	ruta = shutil.which("wt.exe") or ""
	if not ruta:
		candidata = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "wt.exe")
		if os.path.exists(candidata):
			ruta = candidata
	return ruta


def rutaGitBash() -> str:
	"""``git-bash.exe`` de Git para Windows (junto a la carpeta de ``git.exe`` o en las habituales)."""
	candidatas = []
	git = shutil.which("git.exe") or shutil.which("git")
	if git:
		# ...\Git\cmd\git.exe o ...\Git\bin\git.exe → ...\Git
		candidatas.append(os.path.dirname(os.path.dirname(git)))
	for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", ""), os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
		if base:
			candidatas.append(os.path.join(base, "Git"))
	for c in candidatas:
		exe = os.path.join(c, "git-bash.exe")
		if c and os.path.isfile(exe):
			return exe
	return ""


def detectar() -> dict[str, str]:
	"""Consolas disponibles: tipo → ejecutable (CMD siempre está)."""
	res = {"cmd": ejecutor.CMD}
	ps = ejecutor.powershell()
	if os.path.isfile(ps) or shutil.which("powershell.exe"):
		res["powershell"] = ps
	wt = rutaWindowsTerminal()
	if wt:
		res["wt"] = wt
	gb = rutaGitBash()
	if gb:
		res["git-bash"] = gb
	return res


def opciones(disponibles: dict[str, str] | None = None) -> list[Opcion]:
	disponibles = detectar() if disponibles is None else disponibles
	salida = []
	for tipo, (normal, admin) in ETIQUETAS.items():
		exe = disponibles.get(tipo)
		if not exe:
			continue
		salida.append(Opcion(normal, tipo, False, exe))
		salida.append(Opcion(admin, tipo, True, exe))
	return salida


def parametros(tipo: str, carpeta: str) -> str:
	"""Parámetros de la consola para que empiece en ``carpeta`` (también como administrador)."""
	if tipo == "cmd":
		return f'/k pushd "{carpeta}"'
	if tipo == "powershell":
		return "-NoExit -Command \"Set-Location -LiteralPath '{}'\"".format(carpeta.replace("'", "''"))
	if tipo == "wt":
		return f'-d "{carpeta}"'
	if tipo == "git-bash":
		return f'--cd="{carpeta}"'
	raise ValueError(f"Tipo de terminal no soportado: {tipo}")


def abrir(opcion: Opcion, carpeta: str) -> bool:
	"""Abre la consola (llamar desde un hilo propio: el permiso de administrador puede tardar).

	Devuelve ``False`` si no se pudo abrir. Puede lanzar :class:`ejecutor.Cancelado`.
	"""
	params = parametros(opcion.tipo, carpeta)
	if opcion.admin:
		ejecutor.elevado(opcion.ejecutable, params, esperar=False, mostrar=ejecutor.SW_SHOWNORMAL, carpeta=carpeta)
		return True
	return ejecutor.abrir(opcion.ejecutable, params, carpeta)
