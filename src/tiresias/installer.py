"""Instalación, desinstalación y copias portables de Tiresias.

El instalador es el propio Tiresias compilado (un instalador en Python
congelado): el archivo ``Tiresias-<versión>-instalador.exe`` que genera
``tools/build_installer.py`` descomprime el programa en una carpeta temporal
y ejecuta ``Tiresias.exe --install``, que arranca el lector (para que la
instalación sea accesible desde el primer momento) y muestra el diálogo de
instalación.

Una copia instalada:

- vive en ``Archivos de programa\\Tiresias`` (para todos los usuarios, con
  permiso de administrador) o en ``%LOCALAPPDATA%\\Programs\\Tiresias``
  (solo para el usuario actual);
- tiene la marca ``instalado.json`` junto al ejecutable;
- guarda los datos de cada usuario en ``%APPDATA%\\Tiresias`` (la carpeta
  del programa no se puede escribir);
- tiene accesos directos en el menú Inicio (Tiresias, manual, desinstalar) y,
  si se quiere, en el escritorio con ``Control+Alt+T``;
- se registra en «Aplicaciones instaladas» de Windows para desinstalarla.

La desinstalación quita los accesos directos, las claves del registro y la
carpeta del programa (los datos del usuario solo si se pide).

Todas las funciones aceptan rutas y claves de registro alternativas para
poder probarlas sin tocar el sistema.
"""

from __future__ import annotations

import ctypes
import datetime
import fnmatch
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field

from . import APP_NAME, COPYRIGHT, VERSION, paths
from .log import getLogger

log = getLogger("installer")

UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Tiresias"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
EXE_NAME = "Tiresias.exe"
PUBLISHER = "Proyecto Tiresias"

#: Partes de ``data`` que acompañan al programa (también los binarios: API de
#: control, Escritorio remoto, eSpeak NG, documentos e icono).
PROGRAM_DATA_INCLUDE = ["symbols", "sounds", "brailleTables", "addons", "speechDicts/default.json", "controller", "rdp", "synthDrivers", "louis", "locale", "docs", "images"]
#: Partes de ``data`` del programa que se sustituyen enteras al instalar encima.
PROGRAM_DATA_REPLACE = ["controller", "rdp", "synthDrivers", "louis", "locale", "docs", "images"]
#: Carpetas de versiones anteriores a 1.0.2 (fuera de ``data``) que se borran al actualizar.
LEGACY_PROGRAM_DIRS = ["controller", "rdp", "synthDrivers", "docs", "share"]
#: Partes de los datos del usuario que se copian con «copiar la configuración»
#: (los símbolos del usuario están en ``config\symbols_user*.json``).
USER_DATA_INCLUDE = ["config", "labels", "speechDicts"]
#: Archivos sueltos de la raíz del programa que cambian de nombre entre versiones
#: (p. ej. ``python313.dll`` al pasar a Python 3.14): al instalar o actualizar se
#: borran los que la versión nueva ya no trae.
STALE_ROOT_PATTERNS = ["python3*.dll", "Tiresias*.exe", "msvcp140*.dll", "vcruntime140*.dll", "concrt140.dll", "vcamp140.dll", "vccorlib140.dll", "vcomp140.dll"]
#: Marca, en la carpeta de datos del usuario de una copia instalada, con la
#: versión del programa cuyos símbolos, sonidos y tablas se copiaron.
SEED_MARKER = "datos_programa.json"
EXCLUDE = ["__pycache__", "*.pyc", "*.pyo", "*.tmp", "*.part", "*.old.tmp", "pending.json", "_install.tmp", "*.log", "Thumbs.db", "desktop.ini"]
#: En la carpeta del programa solo se omiten temporales (los .pyc son el programa).
PROGRAM_COPY_EXCLUDE = ["*.tmp", "*.part", "*.log", "Thumbs.db", "desktop.ini"]
#: Lo que no se copia del programa (datos del usuario y la marca de instalación).
PROGRAM_EXCLUDE_TOP = {"data", paths.INSTALLED_MARKER, "systemConfig"}


# ====================================================================== utilidades
def _excluded(name: str, patterns: list[str] | None = None) -> bool:
	return any(fnmatch.fnmatch(name, pat) for pat in (EXCLUDE if patterns is None else patterns))


def copyTree(src: str, dst: str, overwrite: bool = True, exclude: list[str] | None = None) -> int:
	"""Copia ``src`` (archivo o carpeta) en ``dst`` sin los temporales. Devuelve el número de archivos."""
	count = 0
	if os.path.isfile(src):
		if overwrite or not os.path.exists(dst):
			os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
			shutil.copy2(src, dst)
			return 1
		return 0
	for root, dirs, files in os.walk(src):
		dirs[:] = [d for d in dirs if not _excluded(d, exclude)]
		rel = os.path.relpath(root, src)
		target = os.path.join(dst, rel) if rel != "." else dst
		os.makedirs(target, exist_ok=True)
		for fn in files:
			if _excluded(fn, exclude):
				continue
			out = os.path.join(target, fn)
			if not overwrite and os.path.exists(out):
				continue
			shutil.copy2(os.path.join(root, fn), out)
			count += 1
	return count


FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def isLink(path: str) -> bool:
	"""``True`` si ``path`` es un enlace simbólico, una unión o cualquier punto de reanálisis."""
	try:
		st = os.lstat(path)
	except OSError:
		return True
	if getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
		return True
	return os.path.islink(path) or bool(getattr(os.path, "isjunction", lambda p: False)(path))


def copyTreeNoLinks(src: str, dst: str) -> int:
	"""Como :func:`copyTree` pero sin seguir ni copiar enlaces ni uniones."""
	count = 0
	for root, dirs, files in os.walk(src, followlinks=False):
		dirs[:] = [d for d in dirs if not isLink(os.path.join(root, d))]
		rel = os.path.relpath(root, src)
		target = os.path.join(dst, rel) if rel != "." else dst
		os.makedirs(target, exist_ok=True)
		for fn in files:
			path = os.path.join(root, fn)
			if isLink(path):
				log.warning("No se copia %s: es un enlace", path)
				continue
			shutil.copy2(path, os.path.join(target, fn), follow_symlinks=False)
			count += 1
	return count


def folderSize(path: str) -> int:
	total = 0
	for root, _dirs, files in os.walk(path):
		for fn in files:
			try:
				total += os.path.getsize(os.path.join(root, fn))
			except OSError:
				pass
	return total


def isElevated() -> bool:
	try:
		return bool(ctypes.windll.shell32.IsUserAnAdmin())
	except Exception:
		return False


def programFilesDir() -> str:
	return os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles") or r"C:\Program Files"


def defaultInstallDir(allUsers: bool = True) -> str:
	if allUsers:
		return os.path.join(programFilesDir(), APP_NAME)
	base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
	return os.path.join(base, "Programs", APP_NAME)


def isWritable(folder: str) -> bool:
	try:
		os.makedirs(folder, exist_ok=True)
		fd, tmp = tempfile.mkstemp(dir=folder)
		os.close(fd)
		os.remove(tmp)
		return True
	except OSError:
		return False


def shellExecuteElevated(exe: str, params: str, wait: bool = False) -> int:
	"""Ejecuta ``exe`` como administrador (pide permiso con UAC). Devuelve el código de salida o 0."""
	from ctypes import wintypes

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

	SEE_MASK_NOCLOSEPROCESS = 0x40
	info = SHELLEXECUTEINFOW()
	info.cbSize = ctypes.sizeof(info)
	info.fMask = SEE_MASK_NOCLOSEPROCESS
	info.lpVerb = "runas"
	info.lpFile = exe
	info.lpParameters = params
	info.nShow = 1
	if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
		raise OSError(ctypes.GetLastError(), "No se obtuvo el permiso de administrador")
	if not wait or not info.hProcess:
		if info.hProcess:
			ctypes.windll.kernel32.CloseHandle(info.hProcess)
		return 0
	ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
	code = wintypes.DWORD()
	ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
	ctypes.windll.kernel32.CloseHandle(info.hProcess)
	return int(code.value)


def quoteArgs(args: list[str]) -> str:
	return subprocess.list2cmdline(args)


def isInside(path: str, folder: str) -> bool:
	"""``True`` si ``path`` es ``folder`` o está dentro de ella."""
	p = os.path.normcase(os.path.abspath(path))
	f = os.path.normcase(os.path.abspath(folder)).rstrip("\\/")
	return p == f or p.startswith(f + os.sep)


def staleRootFiles(source: str, target: str) -> list[str]:
	"""Archivos sueltos de la raíz de ``target`` que la versión de ``source`` ya no trae."""
	try:
		new = {os.path.normcase(e) for e in os.listdir(source)}
		entries = sorted(os.listdir(target))
	except OSError:
		return []
	out = []
	for e in entries:
		if os.path.normcase(e) in new or not os.path.isfile(os.path.join(target, e)):
			continue
		if any(fnmatch.fnmatch(e, pat) for pat in STALE_ROOT_PATTERNS):
			out.append(e)
	return out


#: Carpeta (dentro de %TEMP%) donde descomprime el programa el instalador (tools/build_installer.py).
INSTALLER_TEMP_FOLDER = "TiresiasInstalador"


def isInstallerTempCopy(appDir: str | None = None) -> bool:
	"""``True`` si ``appDir`` es la copia temporal que descomprime el instalador."""
	appDir = appDir or paths.APP_DIR
	temps = {os.environ.get("TEMP") or "", os.environ.get("TMP") or "", tempfile.gettempdir()}
	return any(t and isInside(appDir, os.path.join(t, INSTALLER_TEMP_FOLDER)) for t in temps)


def installDialogDefaults(info: dict, hasOwnConfig: bool, fromInstallerTemp: bool, runCommand: str = "") -> dict:
	"""Valores iniciales de las casillas del diálogo de instalación.

	Si ya hay una copia instalada (``info``, de :func:`installedInfo`), se
	respetan sus accesos directos e inicio automático, y la configuración de
	esta copia no se copia por defecto: pisaría la del usuario. Tampoco si esta
	es la copia temporal del instalador (su configuración es la de fábrica).
	"""
	existing = bool(info.get("DisplayVersion"))
	exe = os.path.join(info.get("InstallLocation") or "", EXE_NAME) if existing and info.get("InstallLocation") else ""
	return {
		"allUsers": bool(info.get("AllUsers", 1)),
		"desktop": bool(info["DesktopShortcut"]) if existing and "DesktopShortcut" in info else True,
		"startMenu": bool(info["StartMenuFolder"]) if existing and "StartMenuFolder" in info else True,
		"logon": bool(exe and runCommand and os.path.normcase(exe) in os.path.normcase(runCommand)),
		"copyConfig": bool(hasOwnConfig) and not existing and not fromInstallerTemp,
	}


def isTiresiasFolder(folder: str) -> bool:
	"""``True`` si ``folder`` tiene una copia de Tiresias (instalada o portable)."""
	return os.path.isfile(os.path.join(folder, paths.INSTALLED_MARKER)) or os.path.isfile(os.path.join(folder, EXE_NAME))


# ====================================================================== registro y accesos directos
@dataclass
class SystemTargets:
	"""Dónde escribe el instalador (se cambia en las pruebas)."""

	allUsers: bool = True
	uninstallKey: str = UNINSTALL_KEY
	runKey: str = RUN_KEY
	startMenuDir: str | None = None
	desktopDir: str | None = None
	writeRegistry: bool = True
	#: Raíz (bajo HKCU) del registro del complemento de Escritorio remoto.
	rdpRegRoot: str | None = None

	@property
	def hive(self):
		import winreg

		return winreg.HKEY_LOCAL_MACHINE if self.allUsers else winreg.HKEY_CURRENT_USER

	def specialFolder(self, name: str) -> str:
		import comtypes.client

		shell = comtypes.client.CreateObject("WScript.Shell", dynamic=True)
		return str(shell.SpecialFolders(name))

	def programsDir(self) -> str:
		if self.startMenuDir:
			return self.startMenuDir
		return os.path.join(self.specialFolder("AllUsersPrograms" if self.allUsers else "Programs"), APP_NAME)

	def desktop(self) -> str:
		if self.desktopDir:
			return self.desktopDir
		return self.specialFolder("AllUsersDesktop" if self.allUsers else "Desktop")


def makeShortcut(path: str, target: str, arguments: str = "", workDir: str = "", description: str = "", hotkey: str = "", icon: str = "") -> None:
	import comtypes.client

	os.makedirs(os.path.dirname(path), exist_ok=True)
	shell = comtypes.client.CreateObject("WScript.Shell", dynamic=True)
	sc = shell.CreateShortcut(path)
	sc.TargetPath = target
	sc.Arguments = arguments
	sc.WorkingDirectory = workDir or os.path.dirname(target)
	if description:
		sc.Description = description
	if hotkey:
		sc.Hotkey = hotkey
	if icon:
		sc.IconLocation = icon
	sc.Save()


def _regWrite(hive, keyPath: str, values: dict) -> None:
	import winreg

	with winreg.CreateKeyEx(hive, keyPath, 0, winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as key:
		for name, value in values.items():
			if isinstance(value, int):
				winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
			else:
				winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))


def _regDeleteKey(hive, keyPath: str) -> None:
	import winreg

	try:
		winreg.DeleteKeyEx(hive, keyPath, winreg.KEY_WOW64_64KEY, 0)
	except FileNotFoundError:
		pass


def _regReadAll(hive, keyPath: str) -> dict:
	import winreg

	out = {}
	try:
		with winreg.OpenKey(hive, keyPath, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
			i = 0
			while True:
				try:
					name, value, _t = winreg.EnumValue(key, i)
				except OSError:
					break
				out[name] = value
				i += 1
	except FileNotFoundError:
		pass
	return out


def setRunAtLogon(exe: str, enable: bool, runKey: str = RUN_KEY) -> None:
	"""Inicio automático al iniciar sesión (usuario actual)."""
	import winreg

	with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, runKey, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
		if enable:
			winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe}"')
		else:
			try:
				winreg.DeleteValue(key, APP_NAME)
			except FileNotFoundError:
				pass


def installedInfo(targets: SystemTargets | None = None) -> dict:
	"""Datos de la copia instalada registrada (vacío si no hay)."""
	if targets is None:
		import winreg

		for allUsers in (True, False):
			info = _regReadAll(winreg.HKEY_LOCAL_MACHINE if allUsers else winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
			if info:
				return info
		return {}
	return _regReadAll(targets.hive, targets.uninstallKey)


# ====================================================================== instalar
@dataclass
class InstallOptions:
	targetDir: str = ""
	allUsers: bool = True
	desktopShortcut: bool = True
	startMenu: bool = True
	#: ``True``: iniciar al iniciar sesión; ``False``: quitar el inicio automático
	#: de esta copia si lo tenía; ``None``: no tocarlo (lo hace otro proceso).
	startOnLogon: bool | None = False
	copyConfig: bool = False
	launchAfter: bool = True
	sourceDir: str = ""
	userDataDir: str | None = None
	targets: SystemTargets = field(default_factory=SystemTargets)


def programFiles(sourceDir: str) -> list[str]:
	"""Entradas de la carpeta del programa que se instalan."""
	return [e for e in sorted(os.listdir(sourceDir)) if e not in PROGRAM_EXCLUDE_TOP and not _excluded(e, PROGRAM_COPY_EXCLUDE)]


def install(opts: InstallOptions) -> str:
	"""Instala Tiresias. Devuelve la ruta del ejecutable instalado."""
	source = os.path.abspath(opts.sourceDir or paths.APP_DIR)
	target = os.path.abspath(opts.targetDir or defaultInstallDir(opts.allUsers))
	if not os.path.isfile(os.path.join(source, EXE_NAME)):
		raise ValueError(f"No se encuentra {EXE_NAME} en {source}: solo se puede instalar la versión compilada")
	if os.path.normcase(source) == os.path.normcase(target):
		raise ValueError("La carpeta de origen y la de instalación son la misma")
	if isInside(source, target) or isInside(target, source):
		raise ValueError("La carpeta de instalación no puede contener la del programa ni estar dentro de ella")
	# Nunca se instala encima de una carpeta con otras cosas: al instalar se
	# borran sus subcarpetas lib, docs, share...
	if os.path.isdir(target) and os.listdir(target) and not isTiresiasFolder(target):
		raise ValueError(f"La carpeta {target} no está vacía y no es una copia de {APP_NAME}")
	wasInstalled = os.path.isfile(os.path.join(target, paths.INSTALLED_MARKER))
	t = opts.targets
	previous = _regReadAll(t.hive, t.uninstallKey) if t.writeRegistry else {}
	log.info("Instalando %s %s en %s", APP_NAME, VERSION, target)
	os.makedirs(target, exist_ok=True)
	# Se borran las bibliotecas de una versión anterior para no mezclar archivos,
	# y las carpetas que antes iban fuera de data (ahora están en data).
	for sub in ["lib", *LEGACY_PROGRAM_DIRS, *(os.path.join("data", d) for d in PROGRAM_DATA_REPLACE)]:
		shutil.rmtree(os.path.join(target, sub), ignore_errors=True)
	if wasInstalled and not isInside(paths.DATA_DIR, os.path.join(target, "data")):
		# En una copia instalada, data solo tiene lo que acompaña al programa (los
		# datos del usuario están en %APPDATA%): se vacía para no dejar restos.
		# Nunca en una copia portable, donde data es la del usuario.
		shutil.rmtree(os.path.join(target, "data"), ignore_errors=True)
	for name in ["tiresias.ico", *staleRootFiles(source, target)]:
		try:
			os.remove(os.path.join(target, name))
		except OSError:
			pass
	for entry in programFiles(source):
		copyTree(os.path.join(source, entry), os.path.join(target, entry), exclude=PROGRAM_COPY_EXCLUDE)
	# Datos que acompañan al programa (símbolos, complementos incluidos...).
	srcData = os.path.join(source, "data")
	for part in PROGRAM_DATA_INCLUDE:
		p = os.path.join(srcData, *part.split("/"))
		if os.path.exists(p):
			copyTree(p, os.path.join(target, "data", *part.split("/")))
	exe = os.path.join(target, EXE_NAME)
	with open(os.path.join(target, paths.INSTALLED_MARKER), "w", encoding="utf-8") as f:
		json.dump({"version": VERSION, "date": datetime.date.today().isoformat(), "allUsers": opts.allUsers}, f, ensure_ascii=False, indent="\t")
	if opts.copyConfig:
		dest = opts.userDataDir or paths.userDataDir()
		if os.path.normcase(os.path.abspath(dest)) != os.path.normcase(os.path.abspath(paths.DATA_DIR)):
			copyUserData(paths.DATA_DIR, dest, includeAddons=True)
	# Al reinstalar sin accesos directos se quitan los de la instalación anterior
	# (solo los que apuntan a esta carpeta).
	try:
		if not opts.startMenu:
			for folder in {previous.get("StartMenuFolder") or "", t.programsDir()}:
				_removeStartMenu(folder, target)
		if not opts.desktopShortcut:
			for lnk in {previous.get("DesktopShortcut") or "", os.path.join(t.desktop(), f"{APP_NAME}.lnk")}:
				_removeShortcutInto(lnk, target)
	except Exception:
		log.exception("No se pudieron quitar los accesos directos anteriores")
	if opts.startMenu:
		folder = t.programsDir()
		makeShortcut(os.path.join(folder, f"{APP_NAME}.lnk"), exe, description=f"{APP_NAME}: lector de pantalla", icon=f"{exe},0")
		manual = os.path.join(target, "Manual de usuario.html")
		if os.path.isfile(manual):
			makeShortcut(os.path.join(folder, "Manual de usuario.lnk"), manual, description="Manual de usuario de Tiresias")
		makeShortcut(os.path.join(folder, f"Desinstalar {APP_NAME}.lnk"), exe, arguments="--uninstall", description=f"Desinstalar {APP_NAME}", icon=f"{exe},0")
	if opts.desktopShortcut:
		makeShortcut(os.path.join(t.desktop(), f"{APP_NAME}.lnk"), exe, description=f"{APP_NAME}: lector de pantalla", hotkey="CTRL+ALT+T", icon=f"{exe},0")
	if t.writeRegistry:
		_regWrite(
			t.hive,
			t.uninstallKey,
			{
				"DisplayName": APP_NAME,
				"DisplayVersion": VERSION,
				"Publisher": PUBLISHER,
				"InstallLocation": target,
				"DisplayIcon": f"{exe},0",
				"UninstallString": f'"{exe}" --uninstall',
				"QuietUninstallString": f'"{exe}" --uninstall-silent',
				"Comments": COPYRIGHT,
				"NoModify": 1,
				"NoRepair": 1,
				"EstimatedSize": folderSize(target) // 1024,
				"AllUsers": 1 if opts.allUsers else 0,
				"StartMenuFolder": t.programsDir() if opts.startMenu else "",
				"DesktopShortcut": os.path.join(t.desktop(), f"{APP_NAME}.lnk") if opts.desktopShortcut else "",
			},
		)
		if opts.startOnLogon:
			setRunAtLogon(exe, True, t.runKey)
		elif opts.startOnLogon is not None:
			removeRunAtLogonIfFrom(exe, t.runKey)
	log.info("Instalación terminada")
	return exe


def _shortcutTarget(lnk: str) -> str:
	"""Destino de un acceso directo (vacío si no se puede leer)."""
	try:
		import comtypes.client

		shell = comtypes.client.CreateObject("WScript.Shell", dynamic=True)
		return str(shell.CreateShortcut(lnk).TargetPath or "")
	except Exception:
		log.debug("No se pudo leer el acceso directo %s", lnk, exc_info=True)
		return ""


def _removeShortcutInto(lnk: str, folder: str) -> bool:
	"""Borra el acceso directo ``lnk`` solo si apunta a algo dentro de ``folder``."""
	if not lnk or not os.path.isfile(lnk):
		return False
	dest = _shortcutTarget(lnk)
	if not dest or not isInside(dest, folder):
		return False
	try:
		os.remove(lnk)
		return True
	except OSError:
		return False


def _removeStartMenu(menuFolder: str, target: str) -> None:
	"""Quita los accesos directos de esta copia del menú Inicio (y la carpeta si queda vacía)."""
	if not menuFolder or not os.path.isdir(menuFolder):
		return
	for name in (f"{APP_NAME}.lnk", "Manual de usuario.lnk", f"Desinstalar {APP_NAME}.lnk"):
		_removeShortcutInto(os.path.join(menuFolder, name), target)
	try:
		os.rmdir(menuFolder)
	except OSError:
		pass


def runAtLogonCommand(runKey: str = RUN_KEY) -> str:
	"""Orden del inicio automático de Tiresias (usuario actual), vacía si no hay."""
	import winreg

	return str(_regReadAll(winreg.HKEY_CURRENT_USER, runKey).get(APP_NAME, "") or "")


def removeRunAtLogonIfFrom(exe: str, runKey: str = RUN_KEY) -> bool:
	"""Quita el inicio automático solo si inicia ``exe`` (no el de otra copia)."""
	run = runAtLogonCommand(runKey)
	if run and os.path.normcase(exe) in os.path.normcase(run):
		setRunAtLogon(exe, False, runKey)
		return True
	return False


def copyUserData(srcDataDir: str, destDataDir: str, includeAddons: bool = True) -> int:
	"""Copia la configuración, etiquetas, diccionarios (y complementos) del usuario."""
	count = 0
	parts = list(USER_DATA_INCLUDE) + (["addons"] if includeAddons else [])
	for part in parts:
		p = os.path.join(srcDataDir, *part.split("/"))
		if os.path.exists(p):
			count += copyTree(p, os.path.join(destDataDir, *part.split("/")))
	return count


def seedUserData(programDataDir: str | None = None, userDir: str | None = None) -> None:
	"""Prepara los datos del usuario de una copia instalada.

	Copia los símbolos, sonidos y tablas braille del programa: los que falten y,
	si el programa ha cambiado de versión desde la última vez (marca
	:data:`SEED_MARKER`), también los que ya existan, para que una versión nueva
	traiga sus símbolos, sonidos y tablas. Los cambios del usuario no se pierden:
	sus símbolos están en ``config\\symbols_user*.json``, sus temas de sonidos en
	subcarpetas propias y su diccionario ``speechDicts\\default.json`` nunca se
	sobrescribe. Actualiza también los complementos incluidos con el programa si
	su versión es más reciente que la del usuario.
	"""
	src = programDataDir or paths.PROGRAM_DATA_DIR
	dst = userDir or paths.DATA_DIR
	if not os.path.isdir(src):
		return
	marker = os.path.join(dst, SEED_MARKER)
	try:
		with open(marker, encoding="utf-8") as f:
			seeded = str(json.load(f).get("version", ""))
	except (OSError, ValueError, AttributeError):
		seeded = ""
	newVersion = seeded != VERSION
	for part in ("symbols", "sounds", "brailleTables"):
		p = os.path.join(src, part)
		if os.path.exists(p):
			copyTree(p, os.path.join(dst, part), overwrite=newVersion)
	p = os.path.join(src, "speechDicts", "default.json")
	if os.path.exists(p):
		copyTree(p, os.path.join(dst, "speechDicts", "default.json"), overwrite=False)
	updateBundledAddons(os.path.join(src, "addons"), os.path.join(dst, "addons"))
	if newVersion:
		try:
			os.makedirs(dst, exist_ok=True)
			with open(marker, "w", encoding="utf-8") as f:
				json.dump({"version": VERSION}, f)
		except OSError:
			log.warning("No se pudo guardar %s", marker, exc_info=True)


def updateBundledAddons(srcAddons: str, dstAddons: str) -> None:
	"""Instala o actualiza los complementos incluidos con el programa si son más recientes."""
	if not os.path.isdir(srcAddons):
		return
	from . import addons

	dst = os.path.dirname(dstAddons)
	for entry in os.listdir(srcAddons):
		folder = os.path.join(srcAddons, entry)
		manifest = addons._readManifest(folder) if os.path.isdir(folder) else None
		if manifest is None:
			continue
		target = os.path.join(dst, "addons", entry)
		current = addons._readManifest(target) if os.path.isdir(target) else None
		marker = os.path.join(dst, "addons", f".{entry}.eliminado")
		if current is None and os.path.exists(marker):
			# El usuario eliminó este complemento: no se vuelve a instalar.
			continue
		if current is None or addons.compareVersions(manifest.get("version"), current.get("version")) > 0:
			shutil.rmtree(target, ignore_errors=True)
			copyTree(folder, target)
			log.info("Complemento incluido instalado o actualizado: %s", entry)


# ====================================================================== desinstalar
def uninstall(targetDir: str | None = None, targets: SystemTargets | None = None, removeUserData: bool = False, userDataDir: str | None = None) -> bool:
	"""Desinstala. Devuelve ``True`` si la carpeta se ha borrado ya (``False`` si se borrará al salir)."""
	if targets is None:
		marker = os.path.join(targetDir or paths.APP_DIR, paths.INSTALLED_MARKER)
		allUsers = True
		try:
			with open(marker, encoding="utf-8") as f:
				allUsers = bool(json.load(f).get("allUsers", True))
		except (OSError, ValueError):
			pass
		targets = SystemTargets(allUsers=allUsers)
	info = _regReadAll(targets.hive, targets.uninstallKey) if targets.writeRegistry else {}
	target = os.path.abspath(targetDir or info.get("InstallLocation") or paths.APP_DIR)
	if not os.path.isfile(os.path.join(target, paths.INSTALLED_MARKER)):
		raise ValueError(f"{target} no es una copia instalada de {APP_NAME}")
	exe = os.path.join(target, EXE_NAME)
	log.info("Desinstalando %s de %s", APP_NAME, target)
	# Accesos directos.
	startMenu = info.get("StartMenuFolder") or ""
	if targets.startMenuDir:
		startMenu = targets.startMenuDir
	if startMenu and os.path.isdir(startMenu):
		shutil.rmtree(startMenu, ignore_errors=True)
	desktopLnk = info.get("DesktopShortcut") or ""
	if targets.desktopDir:
		desktopLnk = os.path.join(targets.desktopDir, f"{APP_NAME}.lnk")
	if desktopLnk and os.path.isfile(desktopLnk):
		try:
			os.remove(desktopLnk)
		except OSError:
			pass
	if targets.writeRegistry:
		_regDeleteKey(targets.hive, targets.uninstallKey)
		# Inicio automático, solo si apunta a esta copia.
		removeRunAtLogonIfFrom(exe, targets.runKey)
		# Complemento de Escritorio remoto (HKCU), solo si es el de esta copia.
		from .remote.rdp_registration import unregisterIfFrom

		unregisterIfFrom(target, targets.rdpRegRoot)
		if targets.allUsers:
			# Inicio de sesión y pantallas seguras (HKLM), solo si es el de esta copia.
			from . import secure_screens

			secure_screens.unregisterIfFrom(exe)
	if removeUserData:
		shutil.rmtree(userDataDir or paths.userDataDir(), ignore_errors=True)
	return _removeFolder(target)


def _removeFolder(target: str) -> bool:
	running = os.path.normcase(os.path.abspath(sys.executable)).startswith(os.path.normcase(target) + os.sep)
	if not running:
		shutil.rmtree(target, ignore_errors=True)
		return not os.path.exists(target)
	# El ejecutable en uso no se puede borrar: se encarga un proceso aparte
	# que espera a que Tiresias termine. La orden va en la línea de órdenes, sin
	# archivo .cmd en la carpeta temporal (otro proceso del usuario podría
	# cambiarlo antes de que lo ejecute una desinstalación con permisos de administrador).
	cmdLine = uninstallCommandLine(target)
	if cmdLine is None:
		log.warning("No se borra después la carpeta %s (caracteres no admitidos)", target)
		return False
	CREATE_NO_WINDOW = 0x08000000
	DETACHED_PROCESS = 0x00000008
	subprocess.Popen(cmdLine, creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS, close_fds=True, cwd=_system32())
	return False


def _system32() -> str:
	return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")


def uninstallCommandLine(target: str) -> str | None:
	"""Línea de órdenes que borra ``target`` cuando Tiresias termina (``None`` si no es segura).

	``cmd.exe`` con ruta absoluta, sin archivo intermedio. ``%`` y ``"`` no se
	pueden proteger en la línea de órdenes de cmd: con ellos no se programa.
	"""
	if not target or '"' in target or "%" in target or any(ord(c) < 32 for c in target):
		return None
	cmd = os.path.join(_system32(), "cmd.exe")
	ping = os.path.join(_system32(), "PING.EXE")
	loop = f'for /l %i in (1,1,30) do (rmdir /s /q "{target}" 2>nul & if not exist "{target}" exit /b 0 & "{ping}" -n 2 127.0.0.1 >nul)'
	return f'"{cmd}" /d /s /c "{loop}"'


# ====================================================================== copia portable
#: Código fuente de una copia portable hecha desde el código (los binarios de
#: controller y rdp van en data, con :data:`PROGRAM_DATA_INCLUDE`).
SOURCE_TREE_ITEMS = ["src", "manual", "docs", "tools", "resources", "controller", "rdp", "Tiresias.bat", "requirements.txt", "README.md", "LEEME.txt", "LICENSE.txt", "setup_cxfreeze.py"]


def createPortableCopy(dest: str, copyConfig: bool = True, copyAddons: bool = True, appDir: str | None = None, dataDir: str | None = None, programDataDir: str | None = None, frozen: bool | None = None) -> str:
	"""Crea una copia portable en ``dest`` (#16341, #2467). Devuelve la carpeta."""
	appDir = os.path.abspath(appDir or paths.APP_DIR)
	dataDir = os.path.abspath(dataDir or paths.DATA_DIR)
	programDataDir = os.path.abspath(programDataDir or paths.PROGRAM_DATA_DIR)
	frozen = paths.FROZEN if frozen is None else frozen
	dest = os.path.abspath(dest)
	if os.path.normcase(dest + os.sep).startswith(os.path.normcase(appDir + os.sep)) or os.path.normcase(dest) == os.path.normcase(appDir):
		raise ValueError("La copia portable no puede estar dentro de la carpeta del programa")
	if os.path.isfile(os.path.join(dest, paths.INSTALLED_MARKER)):
		# Encima de una copia instalada quedaría una mezcla de las dos que no es ni una ni otra.
		raise ValueError("La carpeta de destino tiene una copia instalada de Tiresias: elija otra carpeta")
	if os.path.isdir(dest) and os.listdir(dest):
		if not os.path.isfile(os.path.join(dest, EXE_NAME)) and not os.path.isfile(os.path.join(dest, "src", "tiresias.pyw")):
			raise ValueError("La carpeta de destino no está vacía")
	os.makedirs(dest, exist_ok=True)
	if frozen:
		for entry in programFiles(appDir):
			copyTree(os.path.join(appDir, entry), os.path.join(dest, entry), exclude=PROGRAM_COPY_EXCLUDE)
	else:
		for entry in SOURCE_TREE_ITEMS:
			p = os.path.join(appDir, entry)
			if os.path.exists(p):
				copyTree(p, os.path.join(dest, entry))
	for part in PROGRAM_DATA_INCLUDE:
		p = os.path.join(programDataDir, *part.split("/"))
		if os.path.exists(p):
			copyTree(p, os.path.join(dest, "data", *part.split("/")))
	for sub in ("config/profiles", "logs", "cache", "labels", "speechDicts/voices", "addons"):
		os.makedirs(os.path.join(dest, "data", *sub.split("/")), exist_ok=True)
	if copyConfig:
		for part in USER_DATA_INCLUDE:
			p = os.path.join(dataDir, *part.split("/"))
			if os.path.exists(p):
				copyTree(p, os.path.join(dest, "data", *part.split("/")))
	if copyAddons:
		p = os.path.join(dataDir, "addons")
		if os.path.isdir(p):
			copyTree(p, os.path.join(dest, "data", "addons"))
	# Una copia portable nunca lleva la marca de instalación.
	try:
		os.remove(os.path.join(dest, paths.INSTALLED_MARKER))
	except OSError:
		pass
	log.info("Copia portable creada en %s", dest)
	return dest


# ====================================================================== actualizar una copia portable
#: Partes de ``data`` de una copia portable que se actualizan sin pisar los
#: cambios del usuario (los archivos que ya existan no se sobrescriben).
PORTABLE_DATA_KEEP = ["speechDicts/default.json"]
#: Partes de ``data`` de una copia portable que se actualizan sobrescribiendo
#: (salvo :data:`PORTABLE_USER_FILES`). Los cambios de símbolos del usuario
#: están en ``config\symbols_user*.json``, que no se toca.
PORTABLE_DATA_OVERWRITE = ["symbols", "sounds", "brailleTables"]
PORTABLE_USER_FILES: set[str] = set()
UPDATE_BACKUP_DIR = "_actualizacion_anterior"
#: Carpeta donde se prepara la versión nueva antes de sustituir la copia portable.
UPDATE_STAGING_DIR = "_actualizacion_nueva"


def waitForProcess(pid: int, timeout: float = 120.0) -> bool:
	"""Espera a que termine el proceso ``pid``. ``True`` si ya no está en ejecución."""
	if not pid:
		return True
	SYNCHRONIZE = 0x00100000
	k32 = ctypes.windll.kernel32
	k32.OpenProcess.restype = ctypes.c_void_p
	h = k32.OpenProcess(SYNCHRONIZE, False, int(pid))
	if not h:
		return True
	try:
		return k32.WaitForSingleObject(ctypes.c_void_p(h), int(timeout * 1000)) == 0
	finally:
		k32.CloseHandle(ctypes.c_void_p(h))


def applyPortableUpdate(source: str, target: str) -> int:
	"""Sustituye el programa de la copia portable ``target`` por el de ``source``.

	Conserva la configuración, los registros, las etiquetas, los diccionarios y
	los complementos del usuario; los complementos incluidos se actualizan si
	la versión nueva es más reciente. Devuelve el número de archivos copiados.

	Para que una interrupción (apagón, antivirus, proceso terminado) nunca deje
	la copia sin programa, se trabaja en dos fases:

	1. Se copia la versión nueva a ``_actualizacion_nueva`` dentro de la copia
	   (lo lento). La copia que funciona no se toca.
	2. Se sustituye con renombrados en el mismo disco (instantáneos): lo antiguo
	   va a ``_actualizacion_anterior`` y lo nuevo a su sitio. ``Tiresias.exe``
	   se mueve en último lugar y se coloca en primero. Si algo falla, se
	   restaura lo anterior.
	"""
	source, target = os.path.abspath(source), os.path.abspath(target)
	if not os.path.isfile(os.path.join(source, EXE_NAME)):
		raise ValueError(f"No se encuentra {EXE_NAME} en {source}")
	if not os.path.isfile(os.path.join(target, EXE_NAME)):
		raise ValueError(f"{target} no es una copia de {APP_NAME}")
	if os.path.isfile(os.path.join(target, paths.INSTALLED_MARKER)):
		raise ValueError("Las copias instaladas se actualizan con el instalador")
	if os.path.normcase(source) == os.path.normcase(target):
		raise ValueError("La carpeta de origen y la de destino son la misma")
	backup = os.path.join(target, UPDATE_BACKUP_DIR)
	staging = os.path.join(target, UPDATE_STAGING_DIR)
	if os.path.lexists(backup):
		# Restos de una restauración incompleta anterior: pueden ser la única copia
		# buena de algún archivo, así que se apartan en lugar de borrarse.
		kept = f"{backup}_{time.strftime('%Y%m%d-%H%M%S')}"
		try:
			os.replace(backup, kept)
			log.warning("Se conserva una copia de seguridad anterior en %s", kept)
		except OSError:
			shutil.rmtree(backup, ignore_errors=True)
	shutil.rmtree(staging, ignore_errors=True)
	entries = programFiles(source)
	srcData, dstData = os.path.join(source, "data"), os.path.join(target, "data")
	count = 0
	# Fase 1: preparar la versión nueva sin tocar la que funciona.
	try:
		os.makedirs(staging)
		for entry in entries:
			count += copyTree(os.path.join(source, entry), os.path.join(staging, entry), exclude=PROGRAM_COPY_EXCLUDE)
		for d in PROGRAM_DATA_REPLACE:
			p = os.path.join(srcData, d)
			if os.path.exists(p):
				count += copyTree(p, os.path.join(staging, "data", d))
	except Exception:
		log.exception("Error al preparar la actualización de la copia portable: no se ha tocado nada")
		shutil.rmtree(staging, ignore_errors=True)
		raise
	newItems = list(entries) + [os.path.join("data", d) for d in PROGRAM_DATA_REPLACE if os.path.exists(os.path.join(staging, "data", d))]
	# También los archivos sueltos que la versión nueva ya no trae (python313.dll...).
	toMove = sorted({e for e in entries + ["lib", *LEGACY_PROGRAM_DIRS, *staleRootFiles(source, target)] if e not in (UPDATE_BACKUP_DIR, UPDATE_STAGING_DIR)})
	toMove += [os.path.join("data", d) for d in PROGRAM_DATA_REPLACE]
	exeLast = lambda rel: os.path.normcase(rel) == os.path.normcase(EXE_NAME)  # noqa: E731
	toMove.sort(key=exeLast)
	newItems.sort(key=lambda rel: not exeLast(rel))
	moved: list[str] = []
	placed: list[str] = []
	# Fase 2: sustituir con renombrados.
	try:
		os.makedirs(backup)
		for rel in toMove:
			p = os.path.join(target, rel)
			if os.path.lexists(p):
				os.makedirs(os.path.dirname(os.path.join(backup, rel)), exist_ok=True)
				os.replace(p, os.path.join(backup, rel))
				moved.append(rel)
		for rel in newItems:
			dst = os.path.join(target, rel)
			os.makedirs(os.path.dirname(dst), exist_ok=True)
			os.replace(os.path.join(staging, rel), dst)
			placed.append(rel)
		for part in PORTABLE_DATA_OVERWRITE:
			p = os.path.join(srcData, *part.split("/"))
			if not os.path.isdir(p):
				continue
			for root, dirs, files in os.walk(p):
				dirs[:] = [d for d in dirs if not _excluded(d)]
				for fn in files:
					rel = os.path.relpath(os.path.join(root, fn), srcData)
					if _excluded(fn) or os.path.normcase(rel) in PORTABLE_USER_FILES:
						continue
					count += copyTree(os.path.join(root, fn), os.path.join(dstData, rel))
		for part in PORTABLE_DATA_KEEP:
			p = os.path.join(srcData, *part.split("/"))
			if os.path.exists(p):
				count += copyTree(p, os.path.join(dstData, *part.split("/")), overwrite=False)
		updateBundledAddons(os.path.join(srcData, "addons"), os.path.join(dstData, "addons"))
	except Exception:
		log.exception("Error al actualizar la copia portable: se restaura la versión anterior")
		failed: list[str] = []
		# Lo nuevo ya colocado se quita (también lo que no sustituía a nada, p. ej. python314.dll).
		for rel in reversed(placed):
			try:
				dst = os.path.join(target, rel)
				if os.path.isdir(dst) and not os.path.islink(dst):
					shutil.rmtree(dst)
				elif os.path.lexists(dst):
					os.remove(dst)
			except Exception:
				log.exception("No se pudo quitar %s", rel)
				failed.append(rel)
		# Entrada a entrada: si una falla, se intenta con las demás. El ejecutable, primero.
		for rel in sorted(moved, key=lambda r: not exeLast(r)):
			try:
				dst = os.path.join(target, rel)
				if os.path.isdir(dst) and not os.path.islink(dst):
					shutil.rmtree(dst)
				elif os.path.lexists(dst):
					os.remove(dst)
				os.replace(os.path.join(backup, rel), dst)
			except Exception:
				log.exception("No se pudo restaurar %s", rel)
				failed.append(rel)
		shutil.rmtree(staging, ignore_errors=True)
		if not failed:
			shutil.rmtree(backup, ignore_errors=True)
		else:
			# La copia de seguridad se conserva para poder recuperar lo que falte a mano.
			log.error("Restauración incompleta (%s): la versión anterior sigue en %s", ", ".join(failed), backup)
		raise
	shutil.rmtree(staging, ignore_errors=True)
	shutil.rmtree(backup, ignore_errors=True)
	log.info("Copia portable %s actualizada a %s (%d archivos)", target, VERSION, count)
	return count


def runApplyUpdate(args) -> int:
	"""``--apply-update CARPETA [--wait-pid PID]``: la ejecuta el Tiresias nuevo descomprimido.

	Espera a que se cierre la copia antigua, la actualiza y la vuelve a abrir
	(también si la actualización falla, para que el usuario no se quede sin
	lector). El resultado queda en ``data/actualizacion_resultado.json`` de la
	copia actualizada y Tiresias lo comunica al arrancar.
	"""
	target = os.path.abspath(args.apply_update)
	result: dict = {"version": VERSION, "ok": False, "error": ""}
	code = 1
	if not waitForProcess(getattr(args, "wait_pid", 0) or 0):
		result["error"] = "la copia anterior de Tiresias no se ha cerrado"
	else:
		try:
			# Su guardián (la misma Tiresias.exe) termina enseguida al ver el marcador de actualización.
			from .coexist import relaunch

			relaunch.waitGuardianGone(getattr(args, "wait_pid", 0) or 0, 10.0)
		except Exception:
			pass
		try:
			applyPortableUpdate(paths.APP_DIR, target)
			result["ok"] = True
			code = 0
		except Exception as e:
			result["error"] = str(e) or e.__class__.__name__
	try:
		os.makedirs(os.path.join(target, "data"), exist_ok=True)
		with open(os.path.join(target, "data", "actualizacion_resultado.json"), "w", encoding="utf-8") as f:
			json.dump(result, f, ensure_ascii=False)
	except OSError:
		pass
	exe = os.path.join(target, EXE_NAME)
	if os.path.isfile(exe) and not getattr(args, "no_launch_after_update", False):
		subprocess.Popen([exe], cwd=target, close_fds=True)
		try:
			# Si la copia actualizada no llega a arrancar, el lector de pantalla recordado.
			from .coexist import guardian

			guardian.afterUpdateLaunch(target)
		except Exception:
			log.exception("Error en la red de seguridad del lector recordado")
	return code


# ====================================================================== configuración del sistema
def copyConfigToSystem(srcConfigDir: str, systemDir: str | None = None) -> str:
	"""Copia una configuración a la del sistema (la usa el modo seguro).

	Se ejecuta con permisos de administrador sobre una carpeta que el usuario
	puede escribir: no se siguen enlaces simbólicos ni uniones (``junction``),
	que llevarían a copiar a Archivos de programa archivos ajenos.
	"""
	systemDir = systemDir or paths.SYSTEM_CONFIG_DIR
	src = os.path.abspath(srcConfigDir)
	if not os.path.isdir(src) or isLink(src):
		raise OSError(f"No existe {src}")
	shutil.rmtree(systemDir, ignore_errors=True)
	copyTreeNoLinks(src, systemDir)
	# Las copias de seguridad y los archivos dañados no hacen falta.
	for root, _dirs, files in os.walk(systemDir):
		for fn in files:
			if fn.endswith((".bak", ".corrupto")):
				os.remove(os.path.join(root, fn))
	return systemDir


def requestCopyConfigToSystem() -> None:
	"""Copia la configuración actual a la del sistema (pide permiso de administrador si hace falta)."""
	src = paths.configDir()
	if isWritable(paths.APP_DIR):
		copyConfigToSystem(src)
		return
	exe, args = _launch()
	code = shellExecuteElevated(exe, quoteArgs(args + ["--copy-config-to-system", src]), wait=True)
	if code != 0:
		raise OSError(f"La copia terminó con el código {code}")


def removeSystemConfig() -> None:
	"""Quita la configuración del sistema (#814)."""
	if not os.path.isdir(paths.SYSTEM_CONFIG_DIR):
		return
	if isWritable(paths.APP_DIR):
		shutil.rmtree(paths.SYSTEM_CONFIG_DIR, ignore_errors=True)
	else:
		cmd = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe")
		code = shellExecuteElevated(cmd, quoteArgs(["/c", "rmdir", "/s", "/q", paths.SYSTEM_CONFIG_DIR]), wait=True)
		if code != 0:
			raise OSError(f"rmdir terminó con el código {code}")
	# rmtree ignora los errores: se comprueba que la carpeta ya no exista.
	if os.path.isdir(paths.SYSTEM_CONFIG_DIR):
		raise OSError(f"No se pudo borrar {paths.SYSTEM_CONFIG_DIR}")


def _launch() -> tuple[str, list[str]]:
	if paths.FROZEN:
		return sys.executable, []
	# pythonw.exe: sin ventana de consola (los errores van a logs\ordenes.log).
	pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
	return (pyw if os.path.isfile(pyw) else sys.executable), [os.path.join(paths.SOURCE_DIR, "tiresias.pyw")]


# ====================================================================== línea de órdenes
def resolveInstallDir(folder: str) -> str:
	"""Carpeta de instalación absoluta (con las variables de entorno expandidas)."""
	return os.path.abspath(os.path.expandvars(folder.strip()))


def silentInstallPlan(args) -> tuple[InstallOptions, bool]:
	"""Opciones de ``--install-silent`` y si se quiere iniciar al iniciar sesión."""
	installDir = resolveInstallDir(args.install_dir) if args.install_dir else ""
	flag = getattr(args, "all_users", None)
	if flag is not None:
		allUsers = str(flag) == "1"
	else:
		allUsers = not installDir or isInside(installDir, programFilesDir())
	logon = bool(getattr(args, "start_on_logon", False))
	opts = InstallOptions(
		targetDir=installDir or defaultInstallDir(allUsers),
		allUsers=allUsers,
		launchAfter=bool(args.launch),
		desktopShortcut=not getattr(args, "no_desktop_shortcut", False),
		startMenu=not getattr(args, "no_start_menu", False),
		# Sin --start-on-logon no se toca el inicio automático que hubiera.
		startOnLogon=True if logon else None,
	)
	return opts, logon


def elevatedInstallArgs(opts: InstallOptions) -> list[str]:
	"""Argumentos de la copia elevada que instala para todos los usuarios.

	Lleva ``--no-elevate`` (si el control de cuentas está desactivado no se
	vuelve a pedir permiso en bucle) y nunca ``--launch`` ni
	``--start-on-logon``: eso es del usuario y lo hace el proceso sin elevar.
	"""
	args = ["--install-silent", "--install-dir", opts.targetDir, "--all-users", "1" if opts.allUsers else "0", "--no-elevate"]
	args += [] if opts.desktopShortcut else ["--no-desktop-shortcut"]
	args += [] if opts.startMenu else ["--no-start-menu"]
	return args


def runSilentInstall(args) -> int:
	"""``--install-silent [--install-dir X] [--all-users 0|1] [--launch] [--start-on-logon]``."""
	opts, logon = silentInstallPlan(args)
	if opts.allUsers and not isElevated():
		if getattr(args, "no_elevate", False):
			log.error("La instalación para todos los usuarios necesita permisos de administrador")
			return 5
		exe, base = _launch()
		try:
			code = shellExecuteElevated(exe, quoteArgs(base + elevatedInstallArgs(opts)), wait=True)
		except OSError:
			log.error("No se obtuvo el permiso de administrador para instalar")
			return 5
		if code != 0:
			log.error("La instalación como administrador terminó con el código %d", code)
			return code
		# Con la cuenta del usuario, no con la del administrador.
		installed = os.path.join(opts.targetDir, EXE_NAME)
		if logon:
			try:
				setRunAtLogon(installed, True)
			except OSError:
				log.exception("No se pudo activar el inicio automático")
		if opts.launchAfter:
			_startInstalled(installed)
		return 0
	try:
		exe = install(opts)
	except Exception:
		log.exception("Error en la instalación")
		return 1
	if opts.launchAfter:
		_startInstalled(exe)
	return 0


def _startInstalled(exe: str) -> None:
	try:
		subprocess.Popen([exe], cwd=os.path.dirname(exe), close_fds=True)
	except OSError:
		log.exception("No se pudo iniciar %s", exe)


def _runningInstance() -> tuple[int, str]:
	"""PID y ejecutable de la copia de Tiresias en ejecución (``0, ""`` si no hay)."""
	from . import core, winapi

	hwnd = core._findRunningInstance()
	if not hwnd and core._instanceMutexExists():
		hwnd = core._waitForInstanceWindow(5.0)
	if not hwnd:
		return 0, ""
	pid = winapi.getWindowProcessId(hwnd)
	return pid, (winapi.getProcessImagePath(pid) if pid else "")


def shouldCloseRunning(pid: int, exePath: str, folder: str) -> bool:
	"""¿Hay que cerrar la copia en ejecución para desinstalar ``folder``?

	Solo si su ejecutable está dentro de esa carpeta: una copia portable (o la
	del código) que esté funcionando es el lector del usuario y no se toca.
	"""
	if not pid or pid == os.getpid() or not exePath:
		return False
	return isInside(exePath, folder)


def closeRunningInstanceIn(folder: str) -> bool:
	"""Cierra la copia en ejecución si es la de ``folder``. ``True`` si la ha cerrado."""
	pid, exePath = _runningInstance()
	if not shouldCloseRunning(pid, exePath, folder):
		if pid and pid != os.getpid():
			log.info("No se cierra la copia en ejecución (%s): no es la que se desinstala", exePath or "desconocida")
		return False
	from . import core

	return core._closeRunningInstance()


def runUninstall(interactive: bool = True, noElevate: bool = False) -> int:
	"""``--uninstall`` (con confirmación) o ``--uninstall-silent``."""
	if not paths.isInstalledCopy():
		_message("Esta copia de Tiresias no está instalada: basta con borrar su carpeta.", error=True, show=interactive)
		return 2
	marker = os.path.join(paths.APP_DIR, paths.INSTALLED_MARKER)
	try:
		with open(marker, encoding="utf-8") as f:
			allUsers = bool(json.load(f).get("allUsers", True))
	except (OSError, ValueError):
		allUsers = True
	if allUsers and not isElevated():
		if noElevate:
			_message("Para desinstalar Tiresias hace falta permiso de administrador.", error=True, show=interactive)
			return 5
		# --no-elevate: si el control de cuentas está desactivado, no se pide en bucle.
		args = ["--uninstall" if interactive else "--uninstall-silent", "--no-elevate"]
		try:
			return shellExecuteElevated(sys.executable, quoteArgs(args), wait=False)
		except OSError:
			return 5
	removeData = False
	if interactive:
		MB_YESNO, MB_ICONQUESTION, IDYES = 0x4, 0x20, 6
		r = ctypes.windll.user32.MessageBoxW(None, f"¿Desinstalar {APP_NAME} de este equipo?", f"Desinstalar {APP_NAME}", MB_YESNO | MB_ICONQUESTION)
		if r != IDYES:
			return 1
		r = ctypes.windll.user32.MessageBoxW(
			None,
			"¿Borrar también su configuración, perfiles, etiquetas y complementos?\n\nSi contesta No, se conservan por si vuelve a instalarlo.",
			f"Desinstalar {APP_NAME}",
			MB_YESNO | MB_ICONQUESTION | 0x100,
		)
		removeData = r == IDYES
	# Se cierra la copia en ejecución antes de borrar sus archivos, pero solo si
	# es la que se desinstala (una portable en marcha es el lector del usuario).
	try:
		closeRunningInstanceIn(paths.APP_DIR)
	except Exception:
		log.exception("No se pudo comprobar la copia en ejecución")
	try:
		uninstall(paths.APP_DIR, SystemTargets(allUsers=allUsers), removeUserData=removeData)
	except Exception as e:
		log.exception("Error en la desinstalación")
		_message(f"No se pudo desinstalar {APP_NAME}: {e}", error=True, show=interactive)
		return 1
	_message(f"{APP_NAME} se ha desinstalado.", show=interactive)
	return 0


def _message(text: str, error: bool = False, show: bool = True) -> None:
	log.info(text)
	if show:
		ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x10 if error else 0x40)
