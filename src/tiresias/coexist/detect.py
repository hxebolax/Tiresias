"""Detección de otros lectores de pantalla en ejecución.

Cada lector se reconoce por una combinación de señales, de la más rápida a
la más segura (ver ``docs/arquitectura.md``, «Convivencia con otros lectores
de pantalla»):

- **Proceso**: nombre del ejecutable en la instantánea de procesos
  (``CreateToolhelp32Snapshot``, unos milisegundos). Solo cuentan los
  procesos de la misma sesión y del mismo usuario: así se descartan las
  copias que Windows lanza como SYSTEM en el escritorio seguro (UAC, inicio
  de sesión), que Tiresias no puede leer de todos modos.
- **Ventana propia**: NVDA crea una ventana oculta de clase
  ``wxWindowClassNR`` y título ``NVDA``; JAWS, la de clase ``JFWUI2``. La
  ventana solo cuenta si es de un proceso del propio lector (la ventana de
  compatibilidad de Tiresias, ``tiresiasNvdaWindow.exe``, imita la de NVDA).
  Sirve también cuando no se puede abrir el proceso (por ejemplo, si el
  lector se ejecuta como administrador) y para saber si ya está listo.
- **Registro** (Narrador): ``HKCU\\Software\\Microsoft\\Narrator\\NoRoam``,
  valor ``RunningState`` = 1 mientras Narrador está en marcha. No basta solo
  (queda a 1 si Narrador se cierra de golpe): se exige además el proceso.

No se usa ``SPI_GETSCREENREADER``: lo activan muchas aplicaciones y el
propio Tiresias. Tampoco cuentan ``nvda_slave.exe``,
``nvdaHelperRemoteLoader.exe`` ni ``nvda_eoaProxy.exe`` (procesos auxiliares
de NVDA que no leen la pantalla).

Las funciones son Win32 puro y se pueden llamar desde cualquier hilo.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, NamedTuple

# ------------------------------------------------------------------ lectores conocidos
NVDA = "nvda"
JAWS = "jaws"
NARRATOR = "narrator"
ZOOMTEXT = "zoomtext"
DOLPHIN = "dolphin"
SYSTEM_ACCESS = "systemAccess"


@dataclass(frozen=True)
class ReaderSpec:
	"""Cómo se reconoce un lector de pantalla."""

	id: str
	name: str
	#: Nombres de ejecutable en minúsculas.
	processes: frozenset
	windowClass: str = ""
	windowTitle: str | None = None
	#: Se cede ante él si el usuario no ha cambiado la lista.
	defaultEnabled: bool = True


READERS: tuple[ReaderSpec, ...] = (
	# NVDA instalado (nvda.exe con uiAccess), portable o copia temporal del
	# instalador: todos son nvda.exe; los otros dos nombres son las variantes
	# que trae la copia instalada.
	ReaderSpec(NVDA, "NVDA", frozenset({"nvda.exe", "nvda_uiaccess.exe", "nvda_nouiaccess.exe"}), "wxWindowClassNR", "NVDA"),
	ReaderSpec(JAWS, "JAWS", frozenset({"jfw.exe"}), "JFWUI2"),
	ReaderSpec(NARRATOR, "Narrador", frozenset({"narrator.exe"})),
	# Solo si se usa su voz: con la lupa sola no hace falta ceder.
	ReaderSpec(ZOOMTEXT, "ZoomText", frozenset({"zt.exe", "zoomtext.exe"}), defaultEnabled=False),
	ReaderSpec(DOLPHIN, "Dolphin SuperNova / ScreenReader", frozenset({"snova.exe", "hal.exe"})),
	ReaderSpec(SYSTEM_ACCESS, "System Access", frozenset({"sa.exe", "satogo.exe"}), defaultEnabled=False),
)

SPECS = {s.id: s for s in READERS}
#: Orden de preferencia para elegir «el» lector activo cuando hay varios.
ORDER = [s.id for s in READERS]

#: Procesos auxiliares de NVDA que no son un lector activo.
NVDA_HELPERS = frozenset({"nvda_slave.exe", "nvdahelperremoteloader.exe", "nvda_eoaproxy.exe"})


@dataclass(frozen=True)
class ReaderInfo:
	"""Un lector de pantalla encontrado en ejecución."""

	id: str
	name: str
	pid: int
	#: Para NVDA: «instalado», «portable» o «copia temporal».
	detail: str = ""
	#: Ya ha terminado de arrancar (su ventana existe o el registro lo dice).
	ready: bool = False
	path: str = ""

	@property
	def label(self) -> str:
		return f"{self.name} ({self.detail})" if self.detail else self.name


class ProcessEntry(NamedTuple):
	pid: int
	name: str  # en minúsculas
	parentPid: int


# ------------------------------------------------------------------ Win32
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_u32 = ctypes.WinDLL("user32", use_last_error=True)
_adv = ctypes.WinDLL("advapi32", use_last_error=True)

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TokenUser = 1
INVALID_HANDLE_VALUE = wt.HANDLE(-1).value


class PROCESSENTRY32W(ctypes.Structure):
	_fields_ = [
		("dwSize", wt.DWORD),
		("cntUsage", wt.DWORD),
		("th32ProcessID", wt.DWORD),
		("th32DefaultHeapID", ctypes.c_size_t),
		("th32ModuleID", wt.DWORD),
		("cntThreads", wt.DWORD),
		("th32ParentProcessID", wt.DWORD),
		("pcPriClassBase", ctypes.c_long),
		("dwFlags", wt.DWORD),
		("szExeFile", wt.WCHAR * 260),
	]


_k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
_k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
_k32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_k32.Process32FirstW.restype = wt.BOOL
_k32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_k32.Process32NextW.restype = wt.BOOL
_k32.CloseHandle.argtypes = [wt.HANDLE]
_k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_k32.OpenProcess.restype = wt.HANDLE
_k32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
_k32.QueryFullProcessImageNameW.restype = wt.BOOL
_k32.ProcessIdToSessionId.argtypes = [wt.DWORD, ctypes.POINTER(wt.DWORD)]
_k32.ProcessIdToSessionId.restype = wt.BOOL
_k32.GetCurrentProcess.restype = wt.HANDLE
_adv.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
_adv.OpenProcessToken.restype = wt.BOOL
_adv.GetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)]
_adv.GetTokenInformation.restype = wt.BOOL
_adv.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_adv.EqualSid.restype = wt.BOOL
_u32.FindWindowExW.argtypes = [wt.HWND, wt.HWND, wt.LPCWSTR, wt.LPCWSTR]
_u32.FindWindowExW.restype = wt.HWND
_u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
_u32.GetWindowThreadProcessId.restype = wt.DWORD
_u32.OpenInputDesktop.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_u32.OpenInputDesktop.restype = wt.HANDLE
_u32.CloseDesktop.argtypes = [wt.HANDLE]
_u32.GetUserObjectInformationW.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)]
_u32.GetUserObjectInformationW.restype = wt.BOOL


def listProcesses() -> list[ProcessEntry]:
	"""Todos los procesos del sistema (instantánea de Toolhelp)."""
	snap = _k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
	if not snap or snap == INVALID_HANDLE_VALUE:
		return []
	out: list[ProcessEntry] = []
	try:
		entry = PROCESSENTRY32W()
		entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
		ok = _k32.Process32FirstW(snap, ctypes.byref(entry))
		while ok:
			out.append(ProcessEntry(entry.th32ProcessID, entry.szExeFile.lower(), entry.th32ParentProcessID))
			ok = _k32.Process32NextW(snap, ctypes.byref(entry))
	finally:
		_k32.CloseHandle(snap)
	return out


def sessionOf(pid: int) -> int | None:
	sid = wt.DWORD(0)
	if _k32.ProcessIdToSessionId(pid, ctypes.byref(sid)):
		return sid.value
	return None


_ownSession = sessionOf(os.getpid())


def _tokenUser(hProcess) -> bytes | None:
	"""SID del dueño del proceso (bytes) o ``None`` si no se puede leer."""
	token = wt.HANDLE()
	if not _adv.OpenProcessToken(hProcess, TOKEN_QUERY, ctypes.byref(token)):
		return None
	try:
		size = wt.DWORD(0)
		_adv.GetTokenInformation(token, TokenUser, None, 0, ctypes.byref(size))
		if not size.value:
			return None
		buf = ctypes.create_string_buffer(size.value)
		if not _adv.GetTokenInformation(token, TokenUser, buf, size, ctypes.byref(size)):
			return None
		# TOKEN_USER: SID_AND_ATTRIBUTES {PSID Sid; DWORD Attributes}.
		psid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
		length = ctypes.windll.advapi32.GetLengthSid(ctypes.c_void_p(psid))
		return ctypes.string_at(psid, length)
	finally:
		_k32.CloseHandle(token)


_ownSid: bytes | None = _tokenUser(_k32.GetCurrentProcess())


def isOwnUser(pid: int) -> bool | None:
	"""``True`` si el proceso es del mismo usuario; ``None`` si no se puede saber."""
	h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
	if not h:
		return None
	try:
		sid = _tokenUser(h)
	finally:
		_k32.CloseHandle(h)
	if sid is None or _ownSid is None:
		return None
	return sid == _ownSid


def processImagePath(pid: int) -> str:
	h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
	if not h:
		return ""
	try:
		buf = ctypes.create_unicode_buffer(1024)
		n = wt.DWORD(1024)
		if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
			return buf.value
		return ""
	finally:
		_k32.CloseHandle(h)


def windowsOf(windowClass: str, title: str | None = None) -> list[tuple[int, int]]:
	"""Ventanas de nivel superior de esa clase en el escritorio del hilo: ``[(hwnd, pid)]``."""
	out: list[tuple[int, int]] = []
	after = None
	for _i in range(64):
		hwnd = _u32.FindWindowExW(None, after, windowClass, title)
		if not hwnd:
			break
		pid = wt.DWORD(0)
		_u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
		out.append((int(hwnd), pid.value))
		after = hwnd
	return out


_ownDesktop: str | None = None


def ownDesktopName() -> str:
	"""Escritorio de este proceso en minúsculas (``default``; ``winlogon`` en la copia del escritorio seguro)."""
	global _ownDesktop
	if _ownDesktop is None:
		try:
			from ..secure_env import threadDesktopName

			_ownDesktop = (threadDesktopName() or "default").lower()
		except Exception:
			_ownDesktop = "default"
	return _ownDesktop


def isSecureDesktopActive() -> bool:
	"""``True`` si el escritorio de entrada no es el nuestro (UAC, Ctrl+Alt+Supr...).

	En la copia que Windows inicia en el escritorio seguro, «el nuestro» es
	``Winlogon``: allí la vigilancia sigue funcionando (NVDA puede iniciarse
	en ese mismo escritorio) y se para al volver al del usuario.
	"""
	h = _u32.OpenInputDesktop(0, False, 0)
	if not h:
		return True
	try:
		buf = ctypes.create_unicode_buffer(64)
		needed = wt.DWORD(0)
		if _u32.GetUserObjectInformationW(h, 2, buf, ctypes.sizeof(buf), ctypes.byref(needed)):  # UOI_NAME
			return buf.value.lower() not in (ownDesktopName(), "")
		return False
	finally:
		_u32.CloseDesktop(h)


# ------------------------------------------------------------------ NVDA instalado o portable
_installDirsCache: tuple[float, list[str]] = (0.0, [])


def nvdaInstallDirs() -> list[str]:
	"""Carpetas de NVDA instalado según el registro (caché de 60 s)."""
	global _installDirsCache
	now = time.monotonic()
	if _installDirsCache[1] and now - _installDirsCache[0] < 60:
		return _installDirsCache[1]
	import winreg

	dirs: list[str] = []
	keys = (
		(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\NVDA", 0),
		(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\NVDA", winreg.KEY_WOW64_32KEY),
		(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\NVDA", winreg.KEY_WOW64_32KEY),
	)
	for root, path, flag in keys:
		try:
			with winreg.OpenKey(root, path, 0, winreg.KEY_READ | flag) as k:
				for value in ("InstallDir", "UninstallDirectory", ""):
					try:
						d = winreg.QueryValueEx(k, value)[0]
					except OSError:
						continue
					if isinstance(d, str) and d:
						d = os.path.normcase(os.path.normpath(d))
						if d not in dirs:
							dirs.append(d)
		except OSError:
			continue
	_installDirsCache = (now, dirs)
	return dirs


def classifyNvda(path: str, installDirs: Iterable[str] | None = None) -> str:
	"""«instalado», «portable» o «copia temporal» (el lanzador del instalador)."""
	from ..i18n import _

	if not path:
		return ""
	folder = os.path.normcase(os.path.normpath(os.path.dirname(path)))
	dirs = list(installDirs) if installDirs is not None else nvdaInstallDirs()
	if folder in dirs:
		return _("instalado")
	temp = os.path.normcase(os.path.normpath(os.environ.get("TEMP", "") or os.environ.get("TMP", "")))
	if temp and folder.startswith(temp + os.sep):
		return _("copia temporal")
	return _("portable")


# ------------------------------------------------------------------ Narrador
def narratorRunningState() -> bool | None:
	"""``RunningState`` del registro de Narrador (``None`` si no existe)."""
	import winreg

	try:
		with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Narrator\NoRoam") as k:
			return bool(winreg.QueryValueEx(k, "RunningState")[0])
	except OSError:
		return None


# ------------------------------------------------------------------ detección
def _ignoredPidsFromEnv() -> set[int]:
	"""``TIRESIAS_COEXIST_IGNORE_PIDS``: procesos que no cuentan como lector.

	Solo para pruebas (por ejemplo, probar con un NVDA falso sin cerrar el
	NVDA real del equipo). Lista de PID separados por comas.
	"""
	out: set[int] = set()
	for part in os.environ.get("TIRESIAS_COEXIST_IGNORE_PIDS", "").split(","):
		part = part.strip()
		if part.isdigit():
			out.add(int(part))
	return out


@dataclass
class Detector:
	"""Busca lectores de pantalla en ejecución.

	Las funciones de sistema se pueden sustituir (pruebas unitarias).
	"""

	processes: Callable[[], list[ProcessEntry]] = listProcesses
	windows: Callable[[str, str | None], list[tuple[int, int]]] = windowsOf
	session: Callable[[int], int | None] = sessionOf
	ownUser: Callable[[int], bool | None] = isOwnUser
	imagePath: Callable[[int], str] = processImagePath
	narratorState: Callable[[], bool | None] = narratorRunningState
	ownSession: int | None = _ownSession
	#: Procesos que nunca son un lector (el propio Tiresias y sus auxiliares).
	excludePids: set = field(default_factory=lambda: {os.getpid()} | _ignoredPidsFromEnv())
	#: Solo pruebas: si no está vacía, solo cuentan los lectores cuyo ejecutable está en esa carpeta.
	onlyDir: str = field(default_factory=lambda: os.environ.get("TIRESIAS_COEXIST_ONLY_DIR", ""))

	def _inOnlyDir(self, pid: int) -> bool:
		folder = os.path.normcase(os.path.normpath(self.onlyDir))
		path = os.path.normcase(os.path.normpath(self.imagePath(pid) or ""))
		return path.startswith(folder + os.sep)

	def _candidates(self, spec: ReaderSpec, procs: list[ProcessEntry]) -> list[ProcessEntry]:
		out = []
		for p in procs:
			if p.name not in spec.processes or p.pid in self.excludePids:
				continue
			if self.ownSession is not None and self.session(p.pid) not in (self.ownSession, None):
				continue
			out.append(p)
		return out

	def detectOne(self, spec: ReaderSpec, procs: list[ProcessEntry]) -> ReaderInfo | None:
		if self.onlyDir:
			# Pruebas con lectores falsos: el lector real del equipo (y los de otras pruebas) no cuentan.
			procs = [p for p in procs if p.name not in spec.processes or self._inOnlyDir(p.pid)]
		names = {p.pid: p.name for p in procs}
		# Ventanas propias del lector (solo si son de uno de sus procesos).
		winPids: set[int] = set()
		if spec.windowClass:
			for _hwnd, pid in self.windows(spec.windowClass, spec.windowTitle):
				if pid in self.excludePids:
					continue
				if names.get(pid) in spec.processes:
					winPids.add(pid)
		chosen: int | None = None
		for p in self._candidates(spec, procs):
			own = self.ownUser(p.pid)
			if own is False:
				# Otro usuario (p. ej. SYSTEM en el escritorio seguro).
				continue
			if own is None and p.pid not in winPids:
				# No se puede abrir el proceso: solo cuenta si tiene su ventana aquí.
				continue
			if chosen is None or p.pid in winPids:
				chosen = p.pid
		if chosen is None and winPids:
			chosen = min(winPids)
		if chosen is None:
			return None
		# Ruta exacta del ejecutable: para recordar el lector y volver a iniciarlo (relaunch.py).
		path = self.imagePath(chosen)
		detail = ""
		if spec.id == NVDA:
			detail = classifyNvda(path)
		if spec.id == NARRATOR:
			ready = self.narratorState() is True
		elif spec.windowClass:
			ready = chosen in winPids
		else:
			ready = True
		return ReaderInfo(spec.id, spec.name, chosen, detail, ready, path)

	def detect(self, enabled: Iterable[str] | None = None) -> list[ReaderInfo]:
		"""Lectores en ejecución (en el orden de :data:`ORDER`)."""
		wanted = set(ORDER if enabled is None else enabled)
		procs = self.processes()
		out = []
		for spec in READERS:
			if spec.id not in wanted:
				continue
			info = self.detectOne(spec, procs)
			if info is not None:
				out.append(info)
		return out


_defaultDetector: Detector | None = None


def defaultDetector() -> Detector:
	global _defaultDetector
	if _defaultDetector is None:
		_defaultDetector = Detector()
	return _defaultDetector


def detectReaders(enabled: Iterable[str] | None = None) -> list[ReaderInfo]:
	return defaultDetector().detect(enabled)


def isNvdaRunning(excludePids: Iterable[int] | None = None) -> bool:
	"""¿Hay un NVDA de verdad en ejecución en esta sesión? (rápido, cualquier hilo)."""
	det = defaultDetector()
	if excludePids:
		det = Detector(excludePids=set(det.excludePids) | set(excludePids))
	return det.detectOne(SPECS[NVDA], det.processes()) is not None
