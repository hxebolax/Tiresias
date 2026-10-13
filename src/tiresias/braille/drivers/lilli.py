"""Línea braille MDV Lilli (40 celdas, USB).

Adaptado a Tiresias del controlador ``brailleDisplayDrivers/lilli.py`` de
NVDA (NonVisual Desktop Access), Copyright (C) 2008-2017 NV Access Limited,
Gianluca Casalino, Alberto Benassati y Babbage B.V., distribuido bajo la
Licencia Pública General de GNU versión 2. Tiresias se distribuye bajo la
GPL versión 2 o posterior.

La comunicación pasa por ``lilli.dll``, una biblioteca del fabricante (MDV)
que Tiresias no incluye. Se busca, por este orden:

1. en ``data\\brailleDisplayDrivers\\lilli.dll`` de la carpeta de Tiresias;
2. en la carpeta ``brailleDisplayDrivers`` de NVDA, si está instalado (NVDA
   la trae de serie).

Solo se usa si es de la misma arquitectura que Tiresias (64 bits). Si no
está, el controlador se declara no disponible (no aparece en la lista de
líneas) sin fallar. La DLL no se carga hasta que se elige la línea.

Funciones de la DLL: ``Init408USB()`` (abre la línea; distinto de cero si
la encuentra), ``ReadBuf()`` (siguiente tecla pulsada o 0; se consulta cada
50 ms), ``WriteBuf(celdas)`` y ``Close408USB()``.

Teclas: códigos 1-64 (``F1``...``F10``, ``LF``, ``UP``, ``RG``, ``DN`` y sus
variantes con el prefijo ``S``, ``L`` y ``SL``, más ``SFDN`` y ``SFUP``) y
enrutamiento ``0x101``...``0x128``. Cada pulsación llega sola (no hay
combinaciones). Gestos ``br(lilli):...``; el enrutamiento es ``routing``
(NVDA lo llama ``route``).
"""

from __future__ import annotations

import ctypes
import os
import struct
import threading
import winreg
from typing import Any, Callable

from ... import paths
from ...i18n import _
from ...log import getLogger
from . import hwio
from .base import DeviceMatch, DisplayNotFound, HardwareDriver

log = getLogger("braille.lilli")

NUM_CELLS = 40
#: Segundos entre consultas de teclas.
KEY_CHECK_INTERVAL = 0.05
DLL_NAME = "lilli.dll"
ROUTING_FIRST = 0x101
ROUTING_LAST = 0x128

LILLI_KEYS = [
	"",
	"F1",
	"F2",
	"F3",
	"F4",
	"F5",
	"F6",
	"F7",
	"F8",
	"F9",
	"F10",
	"LF",
	"UP",
	"RG",
	"DN",
	"",
	"",
	"SF1",
	"SF2",
	"SF3",
	"SF4",
	"SF5",
	"SF6",
	"SF7",
	"SF8",
	"SF9",
	"SF10",
	"SLF",
	"SUP",
	"SRG",
	"SDN",
	"",
	"",
	"LF1",
	"LF2",
	"LF3",
	"LF4",
	"LF5",
	"LF6",
	"LF7",
	"LF8",
	"LF9",
	"LF10",
	"LLF",
	"LUP",
	"LRG",
	"LDN",
	"",
	"",
	"SLF1",
	"SLF2",
	"SLF3",
	"SLF4",
	"SLF5",
	"SLF6",
	"SLF7",
	"SLF8",
	"SLF9",
	"SLF10",
	"SLLF",
	"SLUP",
	"SLRG",
	"SLDN",
	"SFDN",
	"SFUP",
]


def convertLilliCell(cell: int) -> int:
	"""Orden de los puntos de la Lilli (``convertLilliCells`` de NVDA)."""
	return (
		(1 << 6 if cell & 1 << 4 else 0)
		| (1 << 5 if cell & 1 << 5 else 0)
		| (1 << 0 if cell & 1 << 6 else 0)
		| (1 << 3 if cell & 1 << 0 else 0)
		| (1 << 2 if cell & 1 << 1 else 0)
		| (1 << 1 if cell & 1 << 2 else 0)
		| (1 << 7 if cell & 1 << 3 else 0)
		| (1 << 4 if cell & 1 << 7 else 0)
	)


LILLI_CELLS_MAP = bytes(convertLilliCell(c) for c in range(256))


# ============================================================ la DLL
def _nvdaDirs() -> list[str]:
	dirs = []
	for root, sub in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\NVDA"), (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\NVDA")):
		try:
			with winreg.OpenKey(root, sub) as key:
				value = winreg.QueryValueEx(key, "")[0]
				if isinstance(value, str) and value:
					dirs.append(value)
		except OSError:
			pass
	for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
		base = os.environ.get(env)
		if base:
			dirs.append(os.path.join(base, "NVDA"))
	return dirs


def _candidatePaths() -> list[str]:
	out = [paths.programData("brailleDisplayDrivers", DLL_NAME)]
	out += [os.path.join(d, "brailleDisplayDrivers", DLL_NAME) for d in _nvdaDirs()]
	seen: set[str] = set()
	unique = []
	for p in out:
		key = os.path.normcase(os.path.abspath(p))
		if key not in seen:
			seen.add(key)
			unique.append(p)
	return unique


#: Código de máquina PE del proceso actual.
_PROCESS_MACHINE = 0x8664 if struct.calcsize("P") == 8 else 0x014C


def dllMachine(path: str) -> int:
	"""Arquitectura de una DLL (campo «Machine» de la cabecera PE; 0 si no se sabe)."""
	try:
		with open(path, "rb") as f:
			head = f.read(4096)
		if head[:2] != b"MZ":
			return 0
		offset = struct.unpack_from("<I", head, 0x3C)[0]
		if head[offset : offset + 4] != b"PE\x00\x00":
			return 0
		return struct.unpack_from("<H", head, offset + 4)[0]
	except (OSError, struct.error):
		return 0


def findDll() -> str | None:
	"""Ruta de una ``lilli.dll`` que se pueda cargar en este proceso, o ``None``."""
	for path in _candidatePaths():
		if os.path.isfile(path) and dllMachine(path) == _PROCESS_MACHINE:
			return path
	return None


_dll: Any = None
_dllLock = threading.Lock()


def loadDll() -> Any:
	"""Carga la DLL (una sola vez). Devuelve ``None`` si no está o no se puede cargar."""
	global _dll
	with _dllLock:
		if _dll is not None:
			return _dll
		path = findDll()
		if path is None:
			return None
		try:
			dll = ctypes.WinDLL(path)
			dll.Init408USB.restype = ctypes.c_int
			dll.Close408USB.restype = ctypes.c_int
			dll.ReadBuf.restype = ctypes.c_int
			dll.WriteBuf.argtypes = [ctypes.c_char_p]
		except (OSError, AttributeError):
			log.warning("No se pudo cargar %s", path, exc_info=True)
			return None
		log.info("Biblioteca de la MDV Lilli cargada: %s", path)
		_dll = dll
		return dll


class LilliTransport(hwio.Transport):
	"""Conexión con la Lilli a través de su DLL.

	Un hilo consulta las teclas cada :data:`KEY_CHECK_INTERVAL` segundos y
	las entrega a ``onReceive`` como dos bytes (little-endian) por tecla.
	"""

	kind = "dll"
	port = "lilli"

	def __init__(self, dll: Any, onReceive: Callable[[bytes], None], onError: Callable[[int], None] | None = None) -> None:
		self.info = {}
		self._dll = dll
		self._onReceive = onReceive
		self._onError = onError
		self._lock = threading.Lock()
		self._stop = threading.Event()
		self._closed = False
		self._thread = threading.Thread(target=self._poll, name="braille-lilli", daemon=True)
		self._thread.start()

	def _poll(self) -> None:
		while not self._stop.wait(KEY_CHECK_INTERVAL):
			while not self._closed:
				try:
					with self._lock:
						key = int(self._dll.ReadBuf())
				except Exception:
					log.debug("Error leyendo las teclas de la Lilli", exc_info=True)
					key = 0
				if not key:
					break
				try:
					self._onReceive((key & 0xFFFF).to_bytes(2, "little"))
				except Exception:
					log.exception("Error procesando una tecla de la Lilli")

	def write(self, data: bytes) -> None:
		if self._closed:
			raise hwio.IoError(0, "Conexión cerrada")
		with self._lock:
			self._dll.WriteBuf(bytes(data))

	def close(self) -> None:
		if self._closed:
			return
		self._closed = True
		self._stop.set()
		if self._thread.is_alive() and self._thread is not threading.current_thread():
			self._thread.join(1.0)
		with self._lock:
			try:
				self._dll.Close408USB()
			except Exception:
				log.debug("Error cerrando la Lilli", exc_info=True)


class LilliDriver(HardwareDriver):
	name = "lilli"
	description = _("MDV Lilli")
	supportsSerialPorts = False
	supportsAutoDetection = False
	keyOrder = [k for k in LILLI_KEYS if k]
	gestureMap = {
		"routing": "braille_routeTo",
		"LF": "braille_scrollBack",
		"UP": "braille_previousLine",
		"DN": "braille_nextLine",
		"RG": "braille_scrollForward",
		"SLF": "kb:shift+tab",
		"SRG": "kb:tab",
		"SDN": "kb:alt+tab",
		"SUP": "kb:alt+shift+tab",
	}
	keyDescriptions = {
		**{f"F{i}": _("tecla de función F{n}").format(n=i) for i in range(1, 11)},
		"LF": _("tecla izquierda (LF)"),
		"RG": _("tecla derecha (RG)"),
		"UP": _("tecla arriba (UP)"),
		"DN": _("tecla abajo (DN)"),
		"SLF": _("tecla izquierda con el modificador S (SLF)"),
		"SRG": _("tecla derecha con el modificador S (SRG)"),
		"SUP": _("tecla arriba con el modificador S (SUP)"),
		"SDN": _("tecla abajo con el modificador S (SDN)"),
		"routing": _("botón de enrutamiento sobre una celda"),
	}

	@classmethod
	def check(cls) -> bool:
		return findDll() is not None

	@classmethod
	def getPortChoices(cls) -> list[tuple[str, str]]:
		return [("auto", _("Automático")), ("usb", _("USB"))]

	@classmethod
	def candidateMatches(cls, port: str) -> list[DeviceMatch]:
		if (port or "auto") not in ("auto", "usb") or findDll() is None:
			return []
		return [DeviceMatch("dll", "", "lilli")]

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		self._buffer = bytearray()
		super().__init__(*args, **kwargs)

	def _open(self, match: DeviceMatch, baudrate: int | None = None, **kwargs: Any) -> hwio.Transport:
		if match.type != "dll":
			return super()._open(match, baudrate, **kwargs)
		dll = loadDll()
		if dll is None:
			raise DisplayNotFound("No está la biblioteca lilli.dll")
		if not dll.Init408USB():
			raise DisplayNotFound("No se encuentra la MDV Lilli")
		return LilliTransport(dll, self._onReceive, self._onIoError)

	def _connect(self, match: DeviceMatch) -> None:
		self._buffer.clear()
		self._io = self._open(match)
		self._initConnection(match)

	def _initConnection(self, match: DeviceMatch) -> None:
		self.model = "Lilli"
		self.deviceName = "MDV Lilli"
		self.numCells = NUM_CELLS

	def _resetState(self) -> None:
		self._buffer.clear()

	# ------------------------------------------------------------ entrada
	def _handleData(self, data: bytes) -> None:
		buf = self._buffer
		buf.extend(data)
		while len(buf) >= 2:
			key = int.from_bytes(buf[:2], "little")
			del buf[:2]
			self._handleKey(key)

	def _handleKey(self, key: int) -> None:
		if ROUTING_FIRST <= key <= ROUTING_LAST:
			self._fireChord({("routing", key - ROUTING_FIRST)})
		elif 0 < key < len(LILLI_KEYS) and LILLI_KEYS[key]:
			self._fireChord({LILLI_KEYS[key]})
		else:
			log.debug("Lilli: tecla desconocida %#x", key)

	# ------------------------------------------------------------ salida
	def _writeCells(self, cells: list[int]) -> None:
		self._write(bytes(LILLI_CELLS_MAP[c & 0xFF] for c in cells))


BrailleDisplayDriver = LilliDriver
