"""Lectura de la consola clásica de Windows con la API de consola.

Alternativa a UI Automation para ``conhost`` (ventanas ``ConsoleWindowClass``):
Tiresias se conecta momentáneamente a la consola del proceso con
``AttachConsole`` y lee el búfer de pantalla: las líneas **visibles** (así no
se leen líneas ocultas con paginadores como ``less`` o ``more``, #13157), la
posición del cursor y el tamaño de la ventana.

Un proceso que ya tiene consola no puede conectarse a otra. Si Tiresias tiene
consola propia (ejecutable de depuración o ``python.exe`` desde una terminal),
la lectura la hace un **proceso auxiliar** sin consola (el propio Tiresias con
``--console-helper``) que responde por tuberías; las peticiones tienen un
tiempo de espera para no bloquear nunca el núcleo.
"""

from __future__ import annotations

import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
from ctypes import wintypes
from dataclasses import dataclass, field

from .log import getLogger

log = getLogger("consoleReader")

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class COORD(ctypes.Structure):
	_fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]


class SMALL_RECT(ctypes.Structure):
	_fields_ = [("Left", wintypes.SHORT), ("Top", wintypes.SHORT), ("Right", wintypes.SHORT), ("Bottom", wintypes.SHORT)]


class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
	_fields_ = [
		("dwSize", COORD),
		("dwCursorPosition", COORD),
		("wAttributes", wintypes.WORD),
		("srWindow", SMALL_RECT),
		("dwMaximumWindowSize", COORD),
	]


kernel32.AttachConsole.argtypes = [wintypes.DWORD]
kernel32.FreeConsole.restype = wintypes.BOOL
kernel32.GetConsoleWindow.restype = wintypes.HWND
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.GetConsoleScreenBufferInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(CONSOLE_SCREEN_BUFFER_INFO)]
kernel32.ReadConsoleOutputCharacterW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, COORD, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 1
FILE_SHARE_WRITE = 2
OPEN_EXISTING = 3
INVALID_HANDLE = wintypes.HANDLE(-1).value
DETACHED_PROCESS = 0x00000008
HELPER_TIMEOUT = 1.0
ERROR_ACCESS_DENIED = 5
#: Se usa el proceso auxiliar (este proceso no puede conectarse a otras consolas).
_useHelper = False

_lock = threading.Lock()

CTRL_C_EVENT = 0
CTRL_BREAK_EVENT = 1
_HandlerRoutine = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
kernel32.SetConsoleCtrlHandler.argtypes = [_HandlerRoutine, wintypes.BOOL]
kernel32.SetConsoleCtrlHandler.restype = wintypes.BOOL


@_HandlerRoutine
def _ctrlHandler(event: int) -> bool:
	"""Mientras se lee una consola ajena, su Control+C y Control+Pausa no son para Tiresias.

	Sin esto, si el usuario pulsa Control+C en la consola justo durante la
	lectura, Python lanzaría ``KeyboardInterrupt`` en el hilo principal, y
	Control+Pausa cerraría Tiresias (manejador por defecto: ``ExitProcess``).
	"""
	return event in (CTRL_C_EVENT, CTRL_BREAK_EVENT)


_ctrlHandlerInstalled = False


def _installCtrlHandler() -> None:
	"""Se instala tras el primer ``AttachConsole`` correcto (el proceso no tiene consola propia)."""
	global _ctrlHandlerInstalled
	if not _ctrlHandlerInstalled:
		_ctrlHandlerInstalled = bool(kernel32.SetConsoleCtrlHandler(_ctrlHandler, True))


@dataclass
class ConsoleScreen:
	"""Contenido visible de una consola."""

	lines: list[str] = field(default_factory=list)
	#: Cursor relativo a la ventana visible (columna, fila); fila -1 si está fuera.
	cursor: tuple[int, int] = (0, 0)
	width: int = 0

	def toDict(self) -> dict:
		return {"lines": self.lines, "cursor": list(self.cursor), "width": self.width}

	@classmethod
	def fromDict(cls, data: dict) -> "ConsoleScreen":
		cur = data.get("cursor") or [0, 0]
		return cls(list(data.get("lines") or []), (int(cur[0]), int(cur[1])), int(data.get("width") or 0))


def hasOwnConsole() -> bool:
	return bool(kernel32.GetConsoleWindow())


def isAvailable() -> bool:
	"""Siempre disponible: con consola propia se usa el proceso auxiliar."""
	return True


def _readAttached(pid: int) -> ConsoleScreen | None:
	"""Lee la consola de ``pid`` desde este proceso (que no debe tener consola)."""
	global _useHelper
	with _lock:
		if not kernel32.AttachConsole(pid):
			if ctypes.get_last_error() == ERROR_ACCESS_DENIED:
				# Este proceso ya tiene una consola (aunque no tenga ventana,
				# p. ej. una pseudoconsola): se usará el proceso auxiliar.
				_useHelper = True
			return None
		try:
			_installCtrlHandler()
			h = kernel32.CreateFileW("CONOUT$", GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
			if not h or h == INVALID_HANDLE:
				return None
			try:
				info = CONSOLE_SCREEN_BUFFER_INFO()
				if not kernel32.GetConsoleScreenBufferInfo(h, ctypes.byref(info)):
					return None
				win = info.srWindow
				width = win.Right - win.Left + 1
				if width <= 0:
					return None
				lines: list[str] = []
				buf = ctypes.create_unicode_buffer(width + 1)
				read = wintypes.DWORD()
				for row in range(win.Top, win.Bottom + 1):
					if kernel32.ReadConsoleOutputCharacterW(h, buf, width, COORD(win.Left, row), ctypes.byref(read)):
						lines.append(buf.value[: read.value].rstrip())
					else:
						lines.append("")
				cx = info.dwCursorPosition.X - win.Left
				cy = info.dwCursorPosition.Y - win.Top
				if not 0 <= cy < len(lines):
					cy = -1
				return ConsoleScreen(lines, (max(0, cx), cy), width)
			finally:
				kernel32.CloseHandle(h)
		finally:
			kernel32.FreeConsole()


# ------------------------------------------------------------------ proceso auxiliar
class _Helper:
	def __init__(self) -> None:
		self.proc: subprocess.Popen | None = None
		self.responses: "queue.Queue[str]" = queue.Queue()
		self.lock = threading.Lock()

	def _command(self) -> list[str]:
		from . import paths

		if paths.FROZEN:
			exe = os.path.join(os.path.dirname(sys.executable), "Tiresias.exe")
			return [exe if os.path.isfile(exe) else sys.executable, "--console-helper"]
		exe = sys.executable
		pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
		script = os.path.join(paths.SOURCE_DIR, "tiresias.pyw")
		return [pyw if os.path.isfile(pyw) else exe, script, "--console-helper"]

	def _start(self) -> bool:
		if self.proc is not None and self.proc.poll() is None:
			return True
		try:
			self.proc = subprocess.Popen(
				self._command(),
				stdin=subprocess.PIPE,
				stdout=subprocess.PIPE,
				stderr=subprocess.DEVNULL,
				creationflags=DETACHED_PROCESS,
				text=True,
				encoding="utf-8",
				bufsize=1,
			)
		except OSError:
			log.debug("No se pudo iniciar el lector de consola auxiliar", exc_info=True)
			self.proc = None
			return False
		self.responses = queue.Queue()
		threading.Thread(target=self._reader, args=(self.proc, self.responses), name="LectorConsolaAux", daemon=True).start()
		return True

	@staticmethod
	def _reader(proc: subprocess.Popen, responses: "queue.Queue[str]") -> None:
		try:
			for line in proc.stdout:  # type: ignore[union-attr]
				responses.put(line)
		except (OSError, ValueError):
			pass

	def read(self, pid: int) -> ConsoleScreen | None:
		with self.lock:
			fresh = self.proc is None or self.proc.poll() is not None
			if not self._start():
				return None
			try:
				while not self.responses.empty():
					self.responses.get_nowait()
				self.proc.stdin.write(json.dumps({"pid": pid}) + "\n")  # type: ignore[union-attr]
				self.proc.stdin.flush()  # type: ignore[union-attr]
				# El primer arranque del auxiliar puede tardar más (carga de Python).
				line = self.responses.get(timeout=HELPER_TIMEOUT * (4 if fresh else 1))
			except (OSError, ValueError, queue.Empty):
				log.debug("El lector de consola auxiliar no respondió", exc_info=True)
				self.stop()
				return None
		try:
			data = json.loads(line)
		except ValueError:
			return None
		return ConsoleScreen.fromDict(data) if data else None

	def stop(self) -> None:
		proc, self.proc = self.proc, None
		if proc is not None:
			try:
				proc.kill()
			except OSError:
				pass


_helper = _Helper()


def readScreen(pid: int) -> ConsoleScreen | None:
	"""Contenido visible de la consola del proceso ``pid`` (``None`` si falla)."""
	if not pid:
		return None
	if _useHelper or hasOwnConsole():
		return _helper.read(pid)
	screen = _readAttached(pid)
	if screen is None and _useHelper:
		return _helper.read(pid)
	return screen


def readVisibleLines(pid: int) -> list[str] | None:
	"""Líneas visibles de la consola del proceso ``pid`` (``None`` si falla)."""
	screen = readScreen(pid)
	return screen.lines if screen is not None else None


def terminate() -> None:
	_helper.stop()


def helperMain() -> int:
	"""Bucle del proceso auxiliar: lee peticiones JSON y responde por línea."""
	if sys.stdin is None or sys.stdout is None:
		# Ejecutables sin consola (base «gui»): se abren las tuberías heredadas.
		import msvcrt

		kernel32.GetStdHandle.restype = wintypes.HANDLE
		sys.stdin = open(msvcrt.open_osfhandle(kernel32.GetStdHandle(-10), os.O_RDONLY), encoding="utf-8")
		sys.stdout = open(msvcrt.open_osfhandle(kernel32.GetStdHandle(-11), 0), "w", encoding="utf-8")
	for line in sys.stdin:
		try:
			req = json.loads(line)
			screen = _readAttached(int(req.get("pid") or 0))
			out = screen.toDict() if screen is not None else None
		except Exception:
			out = None
		try:
			sys.stdout.write(json.dumps(out) + "\n")
			sys.stdout.flush()
		except (OSError, ValueError):
			return 0
	return 0
