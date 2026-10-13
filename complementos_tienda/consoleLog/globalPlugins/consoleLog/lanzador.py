"""Lanzador de consolas: detecta las terminales instaladas y las abre en una carpeta.

La carpeta es la del elemento seleccionado en el Explorador de archivos (o la
carpeta abierta) o, desde el escritorio, la del icono enfocado o el propio
escritorio. Se puede abrir cada terminal normal o como administrador.

La detección lanza procesos (``powershell``, ``pwsh``, ``wsl``) y recorre las
carpetas de Visual Studio: se hace una sola vez y en segundo plano.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass

from tiresias.log import getLogger

log = getLogger("consoleLog")

CREATE_NO_WINDOW = 0x08000000


@dataclass
class InfoConsola:
	nombre: str
	identificador: str
	disponible: bool
	ruta: str = ""
	descripcion: str = ""


@dataclass
class OpcionConsola:
	"""Una entrada de la lista del lanzador."""

	nombre: str
	tipo: str
	como_admin: bool = False
	script_vs: str | None = None
	disponible: bool = True

	@property
	def clave(self) -> str:
		return "{}|{}".format(self.tipo, 1 if self.como_admin else 0)


#: Etiquetas de las opciones: tipo -> (normal, administrador).
ETIQUETAS = {
	"cmd": ("Abrir CMD aquí", "Abrir CMD como administrador"),
	"powershell": ("Abrir PowerShell aquí", "Abrir PowerShell como administrador"),
	"pwsh": ("Abrir PowerShell 7 (Core) aquí", "Abrir PowerShell 7 (Core) como administrador"),
	"wt": ("Abrir Windows Terminal aquí", "Abrir Windows Terminal como administrador"),
	"git-bash": ("Abrir Git Bash aquí", "Abrir Git Bash como administrador"),
	"wsl": ("Abrir WSL (Linux) aquí", "Abrir WSL (Linux) como administrador"),
	"msys2": ("Abrir MSYS2 / MinGW aquí", "Abrir MSYS2 / MinGW como administrador"),
	"vs-32": ("Abrir Visual Studio Developer (32 bits)", "Abrir Visual Studio Developer (32 bits) como administrador"),
	"vs-64": ("Abrir Visual Studio Developer (64 bits)", "Abrir Visual Studio Developer (64 bits) como administrador"),
}
ORDEN = ("cmd", "powershell", "wt", "git-bash", "vs-32", "vs-64", "pwsh", "wsl", "msys2")


def _ejecutarSilencioso(args: list[str], timeout: float) -> tuple[int, bytes]:
	p = subprocess.Popen(args, creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	try:
		salida, _err = p.communicate(timeout=timeout)
	except subprocess.TimeoutExpired:
		p.kill()
		salida, _err = p.communicate()
		return -1, salida or b""
	return p.returncode, salida or b""


class GestorLanzador:
	def __init__(self) -> None:
		self._consolas: dict[str, InfoConsola] = {}
		self._detectadas = threading.Event()
		self._detectando = False
		self._cerrojo = threading.Lock()

	# --------------------------------------------------------------- detección
	@property
	def detectadas(self) -> bool:
		return self._detectadas.is_set()

	def detectar_en_segundo_plano(self, alTerminar=None) -> None:
		"""Detecta las consolas (una vez) y llama a ``alTerminar()`` desde el hilo."""
		with self._cerrojo:
			if self._detectadas.is_set():
				if alTerminar:
					alTerminar()
				return
			esperando = self._detectando
			self._detectando = True

		def trabajo() -> None:
			if esperando:
				self._detectadas.wait(60)
			else:
				try:
					self._detectar_consolas()
				except Exception:
					log.exception("consoleLog: error detectando las consolas")
				finally:
					self._detectadas.set()
			if alTerminar:
				alTerminar()

		threading.Thread(target=trabajo, name="consoleLogLanzador", daemon=True).start()

	def _detectar_consolas(self) -> None:
		consolas: dict[str, InfoConsola] = {}
		consolas["cmd"] = InfoConsola("CMD (Símbolo del sistema)", "cmd", True, "cmd.exe", "Consola de comandos clásica de Windows")
		consolas["powershell"] = self._detectar_powershell()
		consolas["wt"] = self._detectar_windows_terminal()
		consolas["git-bash"] = self._detectar_git_bash()
		vs32, vs64 = self._detectar_visual_studio()
		consolas["vs-32"] = vs32
		consolas["vs-64"] = vs64
		consolas["pwsh"] = self._detectar_powershell_core()
		consolas["wsl"] = self._detectar_wsl()
		consolas["msys2"] = self._detectar_msys2()
		self._consolas = consolas
		log.debug("consoleLog: consolas detectadas: %s", [k for k, v in consolas.items() if v.disponible])

	@staticmethod
	def _detectar_powershell() -> InfoConsola:
		disponible = bool(shutil.which("powershell.exe"))
		if disponible:
			try:
				codigo, _s = _ejecutarSilencioso(["powershell.exe", "-NoProfile", "-Command", "echo $null"], 5)
				disponible = codigo == 0
			except Exception:
				disponible = False
		return InfoConsola("PowerShell", "powershell", disponible, "powershell.exe", "Windows PowerShell para automatización y scripts")

	@staticmethod
	def _detectar_powershell_core() -> InfoConsola:
		ruta = shutil.which("pwsh.exe") or ""
		disponible = False
		if ruta:
			try:
				codigo, _s = _ejecutarSilencioso([ruta, "-NoProfile", "-Command", "echo $null"], 5)
				disponible = codigo == 0
			except Exception:
				disponible = False
		return InfoConsola("PowerShell 7 (Core)", "pwsh", disponible, ruta or "pwsh.exe", "Versión moderna y multiplataforma de PowerShell")

	@staticmethod
	def _detectar_wsl() -> InfoConsola:
		ruta = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "wsl.exe")
		disponible = False
		if os.path.isfile(ruta):
			try:
				codigo, _s = _ejecutarSilencioso([ruta, "--status"], 5)
				disponible = codigo == 0
			except Exception:
				disponible = False
		return InfoConsola("WSL (Linux)", "wsl", disponible, ruta, "Subsistema de Windows para Linux")

	@staticmethod
	def _detectar_windows_terminal() -> InfoConsola:
		ruta = shutil.which("wt.exe") or ""
		if not ruta:
			candidata = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "wt.exe")
			if os.path.exists(candidata):
				ruta = candidata
		return InfoConsola("Windows Terminal", "wt", bool(ruta), "wt.exe" if ruta else "", "Terminal moderna de Windows con pestañas y temas")

	@staticmethod
	def _detectar_git_bash() -> InfoConsola:
		carpeta = ""
		git = shutil.which("git.exe") or shutil.which("git")
		candidatas = []
		if git:
			# ...\Git\cmd\git.exe o ...\Git\bin\git.exe → ...\Git
			candidatas.append(os.path.dirname(os.path.dirname(git)))
		for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
			candidatas.append(os.path.join(base, "Git"))
		for c in candidatas:
			if c and os.path.isfile(os.path.join(c, "git-bash.exe")):
				carpeta = c
				break
		return InfoConsola("Git Bash", "git-bash", bool(carpeta), carpeta, "Terminal Bash de Git para Windows")

	@staticmethod
	def _detectar_msys2() -> InfoConsola:
		for c in (r"C:\msys64", r"C:\msys32", os.path.join(os.environ.get("LOCALAPPDATA", ""), "msys64")):
			if os.path.isfile(os.path.join(c, "msys2_shell.cmd")):
				return InfoConsola("MSYS2 / MinGW", "msys2", True, c, "Entorno MSYS2 con MinGW")
		return InfoConsola("MSYS2 / MinGW", "msys2", False, "", "Entorno MSYS2 con MinGW")

	@staticmethod
	def _detectar_visual_studio() -> tuple[InfoConsola, InfoConsola]:
		raices = [
			os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Microsoft Visual Studio"),
			os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Microsoft Visual Studio"),
		]
		vs32 = vs64 = ""
		for raiz in raices:
			if not os.path.isdir(raiz):
				continue
			for carpeta, _dirs, archivos in os.walk(raiz):
				if not vs32 and "vcvars32.bat" in archivos:
					vs32 = os.path.join(carpeta, "vcvars32.bat")
				if not vs64 and "vcvars64.bat" in archivos:
					vs64 = os.path.join(carpeta, "vcvars64.bat")
				if vs32 and vs64:
					break
			if vs32 and vs64:
				break
		return (
			InfoConsola("Visual Studio Developer (32 bits)", "vs-32", bool(vs32), vs32, "Consola de desarrollador de Visual Studio (32 bits)"),
			InfoConsola("Visual Studio Developer (64 bits)", "vs-64", bool(vs64), vs64, "Consola de desarrollador de Visual Studio (64 bits)"),
		)

	def obtener_consolas_disponibles(self) -> list[InfoConsola]:
		return [c for c in self._consolas.values() if c.disponible]

	def obtener_todas_consolas(self) -> list[InfoConsola]:
		return list(self._consolas.values())

	def opciones(self, incluirNoDisponibles: bool = False) -> list[OpcionConsola]:
		"""Entradas de la lista del lanzador (normal y administrador de cada consola)."""
		salida: list[OpcionConsola] = []
		for tipo in ORDEN:
			info = self._consolas.get(tipo)
			if info is None or (not info.disponible and not incluirNoDisponibles):
				continue
			normal, admin = ETIQUETAS[tipo]
			sufijo = "" if info.disponible else " (no instalada)"
			script = info.ruta if tipo in ("vs-32", "vs-64") else None
			salida.append(OpcionConsola(normal + sufijo, tipo, False, script, info.disponible))
			salida.append(OpcionConsola(admin + sufijo, tipo, True, script, info.disponible))
		return salida

	# --------------------------------------------------------------- carpeta
	@staticmethod
	def carpeta_escritorio() -> str:
		try:
			from ctypes import wintypes

			buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
			CSIDL_DESKTOPDIRECTORY = 0x10
			if ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_DESKTOPDIRECTORY, None, 0, buf) == 0 and buf.value:
				return buf.value
		except Exception:
			pass
		return os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")

	def obtener_directorio(self, esExplorador: bool, hwnd: int, nombreFoco: str) -> str | None:
		"""Carpeta de trabajo (llamar en el hilo de la interfaz: usa COM del Shell)."""
		try:
			if not esExplorador:
				return self._directorio_escritorio(nombreFoco)
			ruta = self._ruta_seleccion(hwnd)
			if ruta is None:
				ruta = self._directorio_escritorio(nombreFoco)
			return self.encontrar_directorio_valido(ruta)
		except Exception:
			log.exception("consoleLog: error al obtener la carpeta del Explorador")
			return None

	def _ruta_seleccion(self, hwnd: int) -> str | None:
		try:
			from comtypes.client import CreateObject

			shell = CreateObject("Shell.Application", dynamic=True)
			ventanas = shell.Windows()
			for i in range(int(ventanas.Count)):
				try:
					v = ventanas.Item(i)
					if v is None or int(v.HWND) != int(hwnd):
						continue
					doc = v.Document
					item = doc.FocusedItem
					if item is not None and str(item.Path):
						return str(item.Path)
					return str(doc.Folder.Self.Path)
				except Exception:
					continue
			return None
		except Exception:
			log.debug("consoleLog: Shell.Application no disponible; se usa PowerShell", exc_info=True)
			return self._ruta_via_powershell(hwnd)

	@staticmethod
	def _ruta_via_powershell(hwnd: int) -> str | None:
		orden = (
			"$OutputEncoding=[console]::OutputEncoding=New-Object System.Text.UTF8Encoding;"
			"(New-Object -ComObject 'Shell.Application').Windows() | "
			"ForEach-Object { \"$($_.HWND):$($_.Document.FocusedItem.Path)\" }"
		)
		try:
			codigo, salida = _ejecutarSilencioso(["powershell.exe", "-NoProfile", "-Command", orden], 5)
			if codigo != 0:
				return None
			for linea in salida.decode("utf-8", "replace").splitlines():
				if ":" not in linea:
					continue
				h, ruta = linea.split(":", 1)
				if h.strip() == str(hwnd):
					return ruta.strip() or None
		except Exception:
			log.debug("consoleLog: error obteniendo la carpeta con PowerShell", exc_info=True)
		return None

	def _directorio_escritorio(self, nombreFoco: str) -> str:
		escritorio = self.carpeta_escritorio()
		if nombreFoco:
			candidato = os.path.join(escritorio, nombreFoco)
			if os.path.exists(candidato):
				return self.encontrar_directorio_valido(candidato) or escritorio
		return escritorio

	@staticmethod
	def encontrar_directorio_valido(ruta: str | None) -> str | None:
		"""La carpeta existente más cercana (sube por la jerarquía si es un archivo)."""
		if not isinstance(ruta, str) or not ruta:
			return None
		if os.path.isdir(ruta):
			return ruta
		actual = ruta
		while True:
			padre = os.path.dirname(actual)
			if not padre or padre == actual:
				return None
			if os.path.isdir(padre):
				return padre
			actual = padre

	# --------------------------------------------------------------- apertura
	def construir_comando(self, tipo: str, directorio: str, ruta_script: str | None = None) -> tuple[str, str]:
		"""(ejecutable, parámetros) para ``ShellExecuteW``."""
		if tipo == "cmd":
			return ("cmd.exe", '/k pushd "{}"'.format(directorio))
		if tipo == "powershell":
			return ("powershell.exe", "-NoExit -Command \"Set-Location -LiteralPath '{}'\"".format(directorio.replace("'", "''")))
		if tipo == "pwsh":
			info = self._consolas.get("pwsh")
			exe = info.ruta if info and info.ruta else "pwsh.exe"
			return (exe, "-NoExit -Command \"Set-Location -LiteralPath '{}'\"".format(directorio.replace("'", "''")))
		if tipo == "wt":
			return ("wt.exe", '-d "{}"'.format(directorio))
		if tipo == "git-bash":
			info = self._consolas.get("git-bash")
			carpeta = info.ruta if info else ""
			return (os.path.join(carpeta, "git-bash.exe"), '--cd="{}"'.format(directorio))
		if tipo in ("vs-32", "vs-64"):
			info = self._consolas.get(tipo)
			script = ruta_script or (info.ruta if info else "")
			return ("cmd.exe", '/k pushd "{}" && call "{}" && pushd "{}"'.format(os.path.dirname(script), script, directorio))
		if tipo == "wsl":
			info = self._consolas.get("wsl")
			return (info.ruta if info and info.ruta else "wsl.exe", '--cd "{}"'.format(directorio))
		if tipo == "msys2":
			info = self._consolas.get("msys2")
			carpeta = info.ruta if info else r"C:\msys64"
			return ("cmd.exe", '/c ""{}" -mingw64 -here"'.format(os.path.join(carpeta, "msys2_shell.cmd")))
		raise ValueError("Tipo de consola no soportado: {}".format(tipo))

	def abrir_consola(self, tipo: str, directorio: str, como_admin: bool = False, ruta_script: str | None = None, alError=None) -> bool:
		"""Abre la consola en un hilo (``ShellExecuteW``; «runas» para administrador)."""
		ejecutable, parametros = self.construir_comando(tipo, directorio, ruta_script)

		def abrir() -> None:
			operacion = "runas" if como_admin else "open"
			try:
				r = ctypes.windll.shell32.ShellExecuteW(None, operacion, ejecutable, parametros, directorio, 1)
			except Exception as e:  # noqa: BLE001
				r = 0
				log.exception("consoleLog: error abriendo la consola")
				if alError:
					alError(str(e))
				return
			if int(r) <= 32 and alError:
				# 5 = acceso denegado; 1223 (cancelado) llega también como 5 desde runas.
				alError("Windows no pudo abrir la consola (código {}).".format(int(r)))

		threading.Thread(target=abrir, name="consoleLogAbrir", daemon=True).start()
		return True
