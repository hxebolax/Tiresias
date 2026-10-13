"""El lector de pantalla recordado y su relanzamiento (Tiresias y el guardián).

Para que el usuario nunca se quede sin lector de pantalla, Tiresias recuerda
el lector profesional que había activo (NVDA, JAWS, Narrador...) y, si
Tiresias se cierra o falla, el proceso guardián (:mod:`.guardian`) lo vuelve
a iniciar. Este módulo reúne lo que comparten los dos procesos y no depende
de wx ni del núcleo:

- **Lector recordado** (``data\\config\\lectorRecordado.json``): el lector,
  la ruta exacta de su ejecutable y una copia de las opciones que necesita
  el guardián. Se escribe en cuanto cambia, así que sobrevive a un cierre
  brusco.
- **Cómo se inicia** cada lector (:func:`launchCandidates`, :func:`launchReader`).
- **Marcador de salida** (``data\\temp\\salida_<pid>.txt``): por qué terminó
  Tiresias (salida del usuario, reinicio, actualización...). Si no hay
  marcador, fue un cierre por error.
- **Latido** en memoria compartida (``Local\\Tiresias_Latido_<pid>``): el
  vigilante de Tiresias anota cada segundo cuándo respondió el núcleo por
  última vez; el guardián lo usa para detectar que Tiresias no responde.
- **Máquina de decisiones** (:func:`decideExit`, :func:`decideHang`): lógica
  pura, probada en ``tests/test_relanzar_lector.py``.
- Objetos con nombre para coordinar procesos: el mutex del guardián
  (``Local\\Tiresias_Guardian_<pid>``) y el evento que crea una copia nueva
  de Tiresias al sustituir a otra (``Local\\Tiresias_Sustituida_<pid>``).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import datetime
import json
import os
import subprocess
import threading
import time
from typing import Iterable

from .. import paths
from . import detect

#: Nombre del archivo del lector recordado (en ``data\config``).
MEMORY_FILE = "lectorRecordado.json"
#: Prefijo de los marcadores de salida (en ``data\temp``).
MARKER_PREFIX = "salida_"
#: Mismo nombre que ``core.MUTEX_NAME`` (aquí sin importar el núcleo).
INSTANCE_MUTEX = "Tiresias_LectorDePantalla_Instancia"
#: Título de la ventana principal oculta (``core.MAIN_WINDOW_TITLE``).
MAIN_WINDOW_TITLE = "Tiresias - ventana principal oculta"
#: Auxiliar de compatibilidad con NVDA (ventana «NVDA» y punto de conexión).
NVDA_HELPER = "tiresiasnvdawindow.exe"

# Motivos de salida (marcador).
EXIT_USER = "user"  # Salir (menú, Tiresias+Q, --quit, desinstalar)
EXIT_ERROR = "error"  # sin marcador: excepción, cierre nativo, proceso terminado
EXIT_RESTART = "restart"  # Reiniciar (también el reinicio de emergencia del vigilante)
EXIT_UPDATE = "update"  # actualización de la copia portable (--apply-update)
EXIT_REPLACED = "replaced"  # otra copia de Tiresias sustituye a esta
EXIT_SWITCH = "switch"  # «Volver a <lector>»: Tiresias ya inició el lector
EXIT_KINDS = (EXIT_USER, EXIT_ERROR, EXIT_RESTART, EXIT_UPDATE, EXIT_REPLACED, EXIT_SWITCH)

# Decisiones del guardián.
ACTION_NONE = "none"
ACTION_LAUNCH = "launch"
ACTION_WAIT = "waitSuccessor"

#: Opciones que el guardián lee del archivo (copia de ``conf["coexist"]``).
DEFAULT_OPTIONS = {
	"relaunchOnExit": True,
	"relaunchOnHang": True,
	"hangTimeout": 20,
}
HANG_TIMEOUT_RANGE = (5, 600)


# ====================================================================== decisiones (lógica pura)
def decideExit(kind: str, *, enabled: bool, hasReader: bool, readerRunning: bool) -> str:
	"""Qué hace el guardián cuando termina Tiresias.

	- Sin lector recordado: nada.
	- «Volver a <lector>»: nada (Tiresias ya lo inició).
	- Actualización: nada (la copia que actualiza se encarga, :func:`guardian.afterUpdateLaunch`).
	- Reinicio o sustitución: esperar a la copia nueva (si no llega, se trata como un fallo).
	- Salida del usuario o fallo: iniciar el lector si la opción está activa y
	  no hay ya un lector de pantalla en ejecución.
	"""
	if not hasReader:
		return ACTION_NONE
	if kind in (EXIT_SWITCH, EXIT_UPDATE):
		return ACTION_NONE
	if kind in (EXIT_RESTART, EXIT_REPLACED):
		return ACTION_WAIT
	if not enabled or readerRunning:
		return ACTION_NONE
	return ACTION_LAUNCH


def decideAfterWait(successorRunning: bool, *, enabled: bool, hasReader: bool, readerRunning: bool) -> str:
	"""Tras esperar a la copia nueva de un reinicio: si no ha llegado, es un fallo."""
	if successorRunning:
		return ACTION_NONE
	return decideExit(EXIT_ERROR, enabled=enabled, hasReader=hasReader, readerRunning=readerRunning)


def decideHang(staleSeconds: float, *, timeout: float, enabled: bool, hasReader: bool, readerRunning: bool, alreadyLaunched: bool) -> str:
	"""Con Tiresias en marcha: ¿se inicia el lector porque el núcleo no responde?

	Solo una vez por bloqueo (``alreadyLaunched``: el guardián vuelve a armarse
	cuando el núcleo responde de nuevo).
	"""
	if not enabled or not hasReader or alreadyLaunched:
		return ACTION_NONE
	if staleSeconds < max(1.0, float(timeout)):
		return ACTION_NONE
	if readerRunning:
		return ACTION_NONE
	return ACTION_LAUNCH


# ====================================================================== lector recordado
def memoryPath(dataDir: str | None = None) -> str:
	return os.path.join(dataDir or paths.DATA_DIR, "config", MEMORY_FILE)


def loadMemory(path: str | None = None) -> dict:
	"""``{"reader": {...} | None, "options": {...}}`` (valores por defecto si falta o está dañado)."""
	path = path or memoryPath()
	data: dict = {}
	try:
		with open(path, encoding="utf-8") as f:
			raw = json.load(f)
		if isinstance(raw, dict):
			data = raw
	except (OSError, ValueError):
		data = {}
	reader = data.get("reader")
	if not (isinstance(reader, dict) and reader.get("id") and isinstance(reader.get("path", ""), str)):
		reader = None
	options = dict(DEFAULT_OPTIONS)
	raw = data.get("options")
	if isinstance(raw, dict):
		for key, default in DEFAULT_OPTIONS.items():
			value = raw.get(key, default)
			if isinstance(default, bool):
				options[key] = bool(value)
			else:
				try:
					options[key] = max(HANG_TIMEOUT_RANGE[0], min(HANG_TIMEOUT_RANGE[1], int(value)))
				except (TypeError, ValueError):
					pass
		readers = raw.get("readers")
		if isinstance(readers, list):
			options["readers"] = [str(r) for r in readers]
	options.setdefault("readers", [s.id for s in detect.READERS if s.defaultEnabled])
	return {"reader": reader, "options": options}


def saveMemory(data: dict, path: str | None = None) -> None:
	"""Escribe el archivo de forma atómica (copia temporal y ``os.replace``)."""
	path = path or memoryPath()
	os.makedirs(os.path.dirname(path), exist_ok=True)
	tmp = f"{path}.{os.getpid()}.tmp"
	with open(tmp, "w", encoding="utf-8") as f:
		json.dump({"version": 1, "reader": data.get("reader"), "options": data.get("options", dict(DEFAULT_OPTIONS))}, f, ensure_ascii=False, indent="\t")
	os.replace(tmp, path)


def readerRecord(info: detect.ReaderInfo, previous: dict | None = None) -> dict:
	"""Lo que se guarda de un lector detectado.

	Si es el mismo lector en la misma ruta, se conservan los datos que no da
	la detección (los argumentos de inicio). Si la detección no sabe la ruta
	(proceso de otro usuario o protegido), se conserva la anterior.
	"""
	path = info.path or ""
	if info.id == detect.NARRATOR and not path:
		path = narratorPath()
	if previous and previous.get("id") == info.id:
		if not path:
			path = previous.get("path", "")
	record = {
		"id": info.id,
		"name": info.name,
		"path": path,
		"detail": info.detail,
		"args": [],
	}
	if previous and previous.get("id") == info.id and _samePath(previous.get("path", ""), path):
		args = previous.get("args")
		if isinstance(args, list):
			record["args"] = [str(a) for a in args]
	return record


def _samePath(a: str, b: str) -> bool:
	return bool(a) and bool(b) and os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def sameRecord(a: dict | None, b: dict | None) -> bool:
	if not a or not b:
		return a == b
	keys = ("id", "name", "path", "detail", "args")
	return all(a.get(k) == b.get(k) for k in keys)


def rememberReader(info: detect.ReaderInfo, path: str | None = None) -> bool:
	"""Recuerda ``info`` como lector profesional. ``True`` si ha cambiado algo."""
	data = loadMemory(path)
	# Sin ruta también se recuerda: NVDA instalado y Narrador tienen alternativa (launchCandidates).
	record = readerRecord(info, data["reader"])
	if sameRecord(record, data["reader"]):
		return False
	record["updated"] = datetime.datetime.now().isoformat(timespec="seconds")
	data["reader"] = record
	saveMemory(data, path)
	return True


def forgetReader(path: str | None = None) -> bool:
	data = loadMemory(path)
	if data["reader"] is None:
		return False
	data["reader"] = None
	saveMemory(data, path)
	return True


def saveOptions(options: dict, path: str | None = None) -> bool:
	"""Actualiza la copia de las opciones para el guardián. ``True`` si ha cambiado."""
	data = loadMemory(path)
	new = dict(data["options"])
	for key in list(DEFAULT_OPTIONS) + ["readers"]:
		if key in options:
			new[key] = options[key]
	if new == data["options"] and os.path.isfile(path or memoryPath()):
		return False
	data["options"] = new
	saveMemory(data, path)
	return True


def readerLabel(reader: dict | None) -> str:
	if not reader:
		return ""
	name = reader.get("name") or reader.get("id", "")
	detail = reader.get("detail") or ""
	return f"{name} ({detail})" if detail else name


# ====================================================================== cómo se inicia cada lector
def narratorPath() -> str:
	return os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32", "Narrator.exe")


def launchCandidates(reader: dict | None, installDirs: Iterable[str] | None = None, exists=os.path.isfile) -> list[str]:
	"""Ejecutables para iniciar el lector, en orden de preferencia (solo los que existen).

	Primero, la ruta exacta recordada (instalado o portable). Si era
	``nvda_uiAccess.exe`` o ``nvda_noUIAccess.exe`` (las variantes de la copia
	instalada de NVDA), el ``nvda.exe`` de la misma carpeta. Narrador es
	siempre ``Narrator.exe`` de System32.

	Solo si la ruta recordada **ya no existe** (por ejemplo, la copia temporal
	del instalador de NVDA) se recurre a otra: el NVDA instalado según el
	registro o el Narrador de System32. En las pruebas con lectores falsos
	(``TIRESIAS_RELAUNCH_NO_FALLBACK=1``, ``TIRESIAS_COEXIST_IGNORE_PIDS`` o
	``TIRESIAS_COEXIST_ONLY_DIR``) nunca: sería el NVDA real del equipo.
	"""
	if not reader:
		return []
	rid = reader.get("id", "")
	path = reader.get("path") or ""
	own: list[str] = []
	fallback: list[str] = []
	if path:
		if rid == detect.NVDA and os.path.basename(path).lower() in ("nvda_uiaccess.exe", "nvda_nouiaccess.exe"):
			own.append(os.path.join(os.path.dirname(path), "nvda.exe"))
		own.append(path)
	if rid == detect.NVDA:
		dirs = list(installDirs) if installDirs is not None else _safeInstallDirs()
		fallback = [os.path.join(d, "nvda.exe") for d in dirs]
	elif rid == detect.NARRATOR:
		fallback = [narratorPath()]
	result = _existing(own, exists)
	if result or _testEnvironment():
		return result
	return _existing(fallback, exists)


def _testEnvironment() -> bool:
	"""Pruebas con lectores falsos: nunca se recurre a otra ruta (sería el lector real del equipo)."""
	env = os.environ
	return env.get("TIRESIAS_RELAUNCH_NO_FALLBACK") == "1" or bool(env.get("TIRESIAS_COEXIST_IGNORE_PIDS") or env.get("TIRESIAS_COEXIST_ONLY_DIR"))


def _existing(candidates: list[str], exists) -> list[str]:
	seen: set[str] = set()
	result = []
	for p in candidates:
		key = os.path.normcase(os.path.normpath(p))
		if key in seen:
			continue
		seen.add(key)
		if exists(p):
			result.append(p)
	return result


def _safeInstallDirs() -> list[str]:
	try:
		return detect.nvdaInstallDirs()
	except Exception:
		return []


class _SHELLEXECUTEINFOW(ctypes.Structure):
	_fields_ = [
		("cbSize", wt.DWORD),
		("fMask", wt.ULONG),
		("hwnd", wt.HWND),
		("lpVerb", wt.LPCWSTR),
		("lpFile", wt.LPCWSTR),
		("lpParameters", wt.LPCWSTR),
		("lpDirectory", wt.LPCWSTR),
		("nShow", ctypes.c_int),
		("hInstApp", wt.HINSTANCE),
		("lpIDList", ctypes.c_void_p),
		("lpClass", wt.LPCWSTR),
		("hkeyClass", wt.HKEY),
		("dwHotKey", wt.DWORD),
		("hIconOrMonitor", wt.HANDLE),
		("hProcess", wt.HANDLE),
	]


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_u32 = ctypes.WinDLL("user32", use_last_error=True)
_shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_SHELLEXECUTEINFOW)]
_shell32.ShellExecuteExW.restype = wt.BOOL
_k32.GetProcessId.argtypes = [wt.HANDLE]
_k32.GetProcessId.restype = wt.DWORD
_k32.CloseHandle.argtypes = [wt.HANDLE]
_k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_k32.OpenProcess.restype = wt.HANDLE
_k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
_k32.WaitForSingleObject.restype = wt.DWORD
_k32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
_k32.TerminateProcess.restype = wt.BOOL
_k32.OpenMutexW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
_k32.OpenMutexW.restype = wt.HANDLE
_k32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
_k32.CreateMutexW.restype = wt.HANDLE
_k32.OpenEventW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
_k32.OpenEventW.restype = wt.HANDLE
_k32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
_k32.CreateEventW.restype = wt.HANDLE
_k32.CreateFileMappingW.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.DWORD, wt.LPCWSTR]
_k32.CreateFileMappingW.restype = wt.HANDLE
_k32.OpenFileMappingW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
_k32.OpenFileMappingW.restype = wt.HANDLE
_k32.MapViewOfFile.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_size_t]
_k32.MapViewOfFile.restype = ctypes.c_void_p
_k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
_k32.QueryUnbiasedInterruptTime.argtypes = [ctypes.POINTER(ctypes.c_ulonglong)]
_k32.QueryUnbiasedInterruptTime.restype = wt.BOOL
_u32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
_u32.FindWindowW.restype = wt.HWND
_u32.GetSystemMetrics.argtypes = [ctypes.c_int]
_u32.GetSystemMetrics.restype = ctypes.c_int

SEE_MASK_NOCLOSEPROCESS = 0x00000040
SEE_MASK_NOASYNC = 0x00000100
SEE_MASK_FLAG_NO_UI = 0x00000400
SW_SHOWNORMAL = 1
SYNCHRONIZE = 0x00100000
PROCESS_TERMINATE = 0x0001
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102
ERROR_ACCESS_DENIED = 5
SM_SHUTTINGDOWN = 0x2000


def launchExecutable(path: str, args: Iterable[str] = ()) -> int:
	"""Inicia ``path`` con ``ShellExecuteEx`` (respeta uiAccess y la elevación). Devuelve el PID o 0."""
	params = subprocess.list2cmdline([str(a) for a in args]) if args else None
	info = _SHELLEXECUTEINFOW()
	info.cbSize = ctypes.sizeof(_SHELLEXECUTEINFOW)
	info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC | SEE_MASK_FLAG_NO_UI
	info.lpVerb = "open"
	info.lpFile = path
	info.lpParameters = params
	info.lpDirectory = os.path.dirname(path) or None
	info.nShow = SW_SHOWNORMAL
	if not _shell32.ShellExecuteExW(ctypes.byref(info)):
		raise OSError(ctypes.get_last_error(), f"No se pudo iniciar {path}")
	pid = 0
	if info.hProcess:
		pid = int(_k32.GetProcessId(info.hProcess))
		_k32.CloseHandle(info.hProcess)
	return pid


def launchReader(reader: dict | None, logger=None) -> int:
	"""Inicia el lector recordado (el primer ejecutable que funcione). Devuelve el PID o 0."""
	remembered = (reader or {}).get("path") or ""
	for exe in launchCandidates(reader):
		# Los argumentos recordados solo valen para su propio ejecutable.
		args = ((reader or {}).get("args") or ()) if _samePath(exe, remembered) else ()
		try:
			pid = launchExecutable(exe, args)
		except OSError as e:
			if logger is not None:
				logger(f"No se pudo iniciar {exe}: {e}")
			continue
		if logger is not None:
			logger(f"Lector de pantalla iniciado: {readerLabel(reader)} ({exe}, PID {pid})")
		return pid or -1
	if logger is not None:
		logger(f"No se encuentra el ejecutable de {readerLabel(reader) or 'ningún lector'}")
	return 0


def anyReaderRunning(ids: Iterable[str], detector: detect.Detector | None = None) -> list[detect.ReaderInfo]:
	"""Lectores de la lista en ejecución (respeta ``TIRESIAS_COEXIST_IGNORE_PIDS``)."""
	det = detector or detect.Detector()
	return det.detect(set(ids))


def readerIds(memory: dict) -> set[str]:
	ids = set(memory["options"].get("readers") or [])
	if memory["reader"]:
		ids.add(memory["reader"]["id"])
	return ids


def isShuttingDown() -> bool:
	"""Windows está cerrando la sesión o apagándose: no se inicia nada."""
	try:
		return bool(_u32.GetSystemMetrics(SM_SHUTTINGDOWN))
	except Exception:
		return False


# ====================================================================== marcadores de salida
def markerPath(pid: int, dataDir: str | None = None) -> str:
	return os.path.join(dataDir or paths.DATA_DIR, "temp", f"{MARKER_PREFIX}{int(pid)}.txt")


def writeMarker(kind: str, pid: int | None = None, dataDir: str | None = None) -> None:
	path = markerPath(pid or os.getpid(), dataDir)
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "w", encoding="utf-8") as f:
		f.write(kind)


def readMarker(pid: int, dataDir: str | None = None, remove: bool = False) -> str | None:
	path = markerPath(pid, dataDir)
	try:
		with open(path, encoding="utf-8") as f:
			kind = f.read().strip()
	except OSError:
		return None
	if remove:
		try:
			os.remove(path)
		except OSError:
			pass
	return kind if kind in EXIT_KINDS else EXIT_ERROR


# ====================================================================== latido (memoria compartida)
def unbiasedNow() -> float:
	"""Segundos desde el arranque sin contar la suspensión del equipo."""
	value = ctypes.c_ulonglong(0)
	if _k32.QueryUnbiasedInterruptTime(ctypes.byref(value)):
		return value.value / 10_000_000
	return time.monotonic()


class _HeartbeatData(ctypes.Structure):
	_fields_ = [
		("magic", ctypes.c_uint32),
		("version", ctypes.c_uint32),
		# Último instante (unidades de 100 ns, sin suspensión) en que el núcleo respondía.
		("lastHealthy", ctypes.c_uint64),
		# 1 cuando el vigilante ya ha escrito el primer latido.
		("armed", ctypes.c_uint32),
		("reserved", ctypes.c_uint32),
	]


HEARTBEAT_MAGIC = 0x53524954  # "TIRS"
PAGE_READWRITE = 0x04
FILE_MAP_READ = 0x0004
FILE_MAP_WRITE = 0x0002
INVALID_HANDLE_VALUE = wt.HANDLE(-1).value


def heartbeatName(pid: int) -> str:
	return f"Local\\Tiresias_Latido_{int(pid)}"


class Heartbeat:
	"""Lado de Tiresias: crea la memoria compartida y anota los latidos."""

	def __init__(self, pid: int | None = None) -> None:
		self.pid = pid or os.getpid()
		# beat() (vigilante) y close() (hilo principal al salir) pueden coincidir:
		# escribir en la vista ya liberada tumbaría el proceso.
		self._lock = threading.Lock()
		self._handle = _k32.CreateFileMappingW(INVALID_HANDLE_VALUE, None, PAGE_READWRITE, 0, ctypes.sizeof(_HeartbeatData), heartbeatName(self.pid))
		if not self._handle:
			raise OSError(ctypes.get_last_error(), "CreateFileMapping")
		self._view = _k32.MapViewOfFile(self._handle, FILE_MAP_READ | FILE_MAP_WRITE, 0, 0, ctypes.sizeof(_HeartbeatData))
		if not self._view:
			_k32.CloseHandle(self._handle)
			raise OSError(ctypes.get_last_error(), "MapViewOfFile")
		self._data = _HeartbeatData.from_address(self._view)
		self._data.version = 1
		self._data.lastHealthy = int(unbiasedNow() * 10_000_000)
		self._data.magic = HEARTBEAT_MAGIC

	def beat(self) -> None:
		"""El núcleo responde: se anota el instante y se arma la detección."""
		with self._lock:
			if self._view and self._data is not None:
				self._data.lastHealthy = int(unbiasedNow() * 10_000_000)
				self._data.armed = 1

	def close(self) -> None:
		with self._lock:
			if self._view:
				self._data = None
				_k32.UnmapViewOfFile(self._view)
				self._view = None
			if self._handle:
				_k32.CloseHandle(self._handle)
				self._handle = None


class HeartbeatReader:
	"""Lado del guardián: lee los latidos de un proceso de Tiresias."""

	def __init__(self, pid: int) -> None:
		self.pid = pid
		self._handle = None
		self._view = None

	def _open(self) -> bool:
		if self._view:
			return True
		h = _k32.OpenFileMappingW(FILE_MAP_READ, False, heartbeatName(self.pid))
		if not h:
			return False
		view = _k32.MapViewOfFile(h, FILE_MAP_READ, 0, 0, ctypes.sizeof(_HeartbeatData))
		if not view:
			_k32.CloseHandle(h)
			return False
		self._handle, self._view = h, view
		return True

	def read(self) -> tuple[bool, float] | None:
		"""``(armado, segundos desde el último latido)`` o ``None`` si no hay latido."""
		if not self._open():
			return None
		data = _HeartbeatData.from_address(self._view)
		if data.magic != HEARTBEAT_MAGIC:
			return None
		return bool(data.armed), max(0.0, unbiasedNow() - data.lastHealthy / 10_000_000)

	def close(self) -> None:
		if self._view:
			_k32.UnmapViewOfFile(self._view)
			self._view = None
		if self._handle:
			_k32.CloseHandle(self._handle)
			self._handle = None


# ====================================================================== objetos con nombre
def guardianMutexName(pid: int) -> str:
	return f"Local\\Tiresias_Guardian_{int(pid)}"


def replacedEventName(pid: int) -> str:
	return f"Local\\Tiresias_Sustituida_{int(pid)}"


def _namedObjectExists(opener, name: str) -> bool:
	h = opener(SYNCHRONIZE, False, name)
	if h:
		_k32.CloseHandle(h)
		return True
	# Existe pero es de un proceso elevado (Reiniciar como administrador).
	return ctypes.get_last_error() == ERROR_ACCESS_DENIED


def isGuardianRunning(pid: int) -> bool:
	return _namedObjectExists(_k32.OpenMutexW, guardianMutexName(pid))


def waitGuardianGone(pid: int, timeout: float = 5.0) -> bool:
	"""Espera a que termine el guardián de ``pid`` (antes de tocar los archivos del programa)."""
	deadline = time.monotonic() + timeout
	while isGuardianRunning(pid):
		if time.monotonic() >= deadline:
			return False
		time.sleep(0.05)
	return True


def createGuardianMutex(pid: int):
	return _k32.CreateMutexW(None, False, guardianMutexName(pid))


def markReplacing(pid: int):
	"""La copia nueva avisa de que sustituye a ``pid`` (el evento vive mientras ella viva)."""
	return _k32.CreateEventW(None, True, True, replacedEventName(pid))


def wasReplaced(pid: int) -> bool:
	return _namedObjectExists(_k32.OpenEventW, replacedEventName(pid))


def instanceRunning() -> bool:
	"""¿Hay alguna copia de Tiresias en ejecución en esta sesión?"""
	if _u32.FindWindowW(None, MAIN_WINDOW_TITLE):
		return True
	return _namedObjectExists(_k32.OpenMutexW, INSTANCE_MUTEX)


def closeHandle(h) -> None:
	if h:
		_k32.CloseHandle(h)


# ====================================================================== procesos
def openProcess(pid: int, terminate: bool = False):
	access = SYNCHRONIZE | (PROCESS_TERMINATE if terminate else 0)
	return _k32.OpenProcess(access, False, int(pid)) or None


def waitHandle(handle, timeout: float) -> bool:
	"""``True`` si el proceso ha terminado."""
	return _k32.WaitForSingleObject(handle, max(0, int(timeout * 1000))) == WAIT_OBJECT_0


def helperProcesses(parentPid: int) -> list[int]:
	"""Auxiliares ``tiresiasNvdaWindow.exe`` que inició ese proceso de Tiresias."""
	return [p.pid for p in detect.listProcesses() if p.name == NVDA_HELPER and p.parentPid == parentPid]


def endHelpers(parentPid: int, timeout: float = 3.0, logger=None) -> None:
	"""Se asegura de que el auxiliar de compatibilidad con NVDA ha terminado.

	El auxiliar termina solo al morir Tiresias (vigila su proceso), pero NVDA
	necesita libre su punto de conexión: si sigue vivo pasado ``timeout``, se
	termina (es nuestro).
	"""
	deadline = time.monotonic() + timeout
	while True:
		pids = helperProcesses(parentPid)
		if not pids:
			return
		if time.monotonic() >= deadline:
			break
		time.sleep(0.1)
	for pid in pids:
		h = openProcess(pid, terminate=True)
		if not h:
			continue
		try:
			_k32.TerminateProcess(h, 1)
			if logger is not None:
				logger(f"Auxiliar de compatibilidad con NVDA terminado (PID {pid})")
		finally:
			_k32.CloseHandle(h)
