"""Dot Pad (Dot Incorporated): línea braille y pantalla de gráficos táctiles.

Adaptado a Tiresias del controlador ``brailleDisplayDrivers/dotPad`` de NVDA
(NonVisual Desktop Access), Copyright (C) 2024-2026 NV Access Limited, Dot
Incorporated y Bram Duvigneau, distribuido bajo la Licencia Pública General
de GNU versión 2 o posterior (con las condiciones de la licencia de NVDA).
Incluye el dibujo de celdas braille en la zona gráfica del módulo
``tactile`` de NVDA (Copyright (C) 2024 NV Access Limited, GPL v2).
Tiresias se distribuye bajo la GPL versión 2 o posterior.

Conexión: puerto serie USB del chip FTDI doble del DotPad320A
(``VID_0403&PID_6010``), a 115200 baudios, sin paridad. Es un chip genérico
(lo usan otros aparatos), así que la detección automática solo lo prueba si
el usuario permite los adaptadores USB-serie genéricos.

Protocolo: paquetes ``AA 55 <longitud BE16> <destino> <orden BE16> <secuencia>
<datos> <suma>``, donde la suma es el XOR de los bytes del cuerpo empezando
por ``A5``. Al conectar se piden el nombre del aparato (``0100``) y la
información de la placa (``0110``: funciones, celdas de la línea de texto y
de la zona gráfica). Cada línea se envía con ``0200`` (destino = número de
fila, datos ``00`` + celdas) y la línea contesta ``0201`` con ``00``
(aceptada), ``01`` (rechazada) o ``03`` (suma errónea); solo se reenvían las
filas que cambian. Las teclas llegan como avisos ``03x2`` (``0332`` teclas de
función, ``0312`` teclado Perkins y desplazamiento) con un bit por tecla.

Qué se ha portado y qué no:

- se usa **una sola fila de texto** (Tiresias maneja líneas de una fila):
  en el modo «línea de texto» es la primera fila de texto del aparato; en
  el modo «zona gráfica» (para los Dot Pad sin línea de texto, o si se elige
  en Opciones) las celdas se dibujan en la primera fila de la zona gráfica,
  con un punto de separación entre celdas, como hace NVDA. NVDA, en cambio,
  reparte varias filas de texto por toda la zona gráfica;
- no se muestran gráficos táctiles (imágenes, diagramas): NVDA tampoco lo
  hace todavía desde este controlador;
- teclas: las de función (``f1``...) y las del teclado Perkins (puntos,
  espacio, mayúsculas y control a cada lado, desplazamiento y cruceta),
  como NVDA; los avisos de los grupos de enrutamiento y de desplazamiento
  (``0322`` y ``0302``) no se interpretan, como en NVDA, porque su formato
  no está documentado;
- las líneas se envían desde un hilo propio, para no bloquear Tiresias
  mientras se espera la confirmación de cada fila.

Nombres de teclas (gestos ``br(dotPad):...``): ``f1``...``fN``, ``dot1``...
``dot8``, ``space``, ``shiftLeft``, ``controlLeft``, ``shiftRight``,
``controlRight``, ``panLeft``, ``panRight``, ``navCenter``, ``navUp``,
``navRight``, ``navDown`` y ``navLeft``.
"""

from __future__ import annotations

import ctypes
import functools
import operator
import struct
import threading
from dataclasses import dataclass
from typing import Any

from ... import queue_handler
from ...i18n import _
from ...log import getLogger
from .base import DeviceMatch, DisplayNotFound, DriverSetting, HardwareDriver

log = getLogger("braille.dotPad")

BAUD_RATE = 115200
USB_ID = "VID_0403&PID_6010"

SYNC1 = 0xAA
SYNC2 = 0x55
CHECKSUM_BASE = 0xA5
#: Tamaño total plausible de un paquete (cabecera de 4 bytes incluida).
MIN_PACKET_SIZE = 4 + 5
MAX_PACKET_SIZE = 512
SEQ_TEXT = 0x80

# Órdenes.
REQ_FIRMWARE_VERSION = 0x0000
RSP_FIRMWARE_VERSION = 0x0001
REQ_DEVICE_NAME = 0x0100
RSP_DEVICE_NAME = 0x0101
REQ_BOARD_INFORMATION = 0x0110
RSP_BOARD_INFORMATION = 0x0111
REQ_DISPLAY_LINE = 0x0200
RSP_DISPLAY_LINE = 0x0201
NTF_DISPLAY_LINE = 0x0202
NTF_KEYS_SCROLL = 0x0302
NTF_KEYS_PERKINS = 0x0312
NTF_KEYS_ROUTING = 0x0322
NTF_KEYS_FUNCTION = 0x0332
NTF_ERROR = 0x9902

# Respuestas a ``REQ_DISPLAY_LINE``.
DISPLAY_ACK = 0
DISPLAY_NACK = 1
DISPLAY_WAIT = 2
DISPLAY_CHECKSUM = 3

# Funciones de la placa.
HAS_GRAPHIC_DISPLAY = 0x80
HAS_TEXT_DISPLAY = 0x40
HAS_PERKINS_KEYS = 0x20
HAS_ROUTING_KEYS = 0x10
HAS_NAVIGATION_KEYS = 0x08
HAS_PANNING_KEYS = 0x04
HAS_FUNCTION_KEYS = 0x02

# Grupos de teclas (segundo byte de la orden de aviso).
GROUP_SCROLL = 0x02
GROUP_PERKINS = 0x12
GROUP_ROUTING = 0x22
GROUP_FUNCTION = 0x32
KEY_GROUPS = (GROUP_SCROLL, GROUP_PERKINS, GROUP_ROUTING, GROUP_FUNCTION)

#: Número de tecla del grupo Perkins -> nombre (``DP_PerkinsKey`` de NVDA).
PERKINS_KEYS = {
	0: "dot7",
	1: "dot3",
	2: "dot2",
	3: "dot1",
	4: "dot4",
	5: "dot5",
	6: "dot6",
	7: "dot8",
	8: "space",
	9: "shiftLeft",
	10: "controlLeft",
	11: "shiftRight",
	12: "controlRight",
	13: "panLeft",
	14: "panRight",
	16: "navCenter",
	17: "navUp",
	18: "navRight",
	19: "navDown",
	20: "navLeft",
}

#: Segundos de espera de cada respuesta (20 x 50 ms en NVDA).
RESPONSE_TIMEOUT = 1.0
#: Espera de la confirmación de cada fila al cerrar.
CLOSE_RESPONSE_TIMEOUT = 0.3

# Zona gráfica: cada celda del Dot Pad tiene 2 x 4 puntos; las celdas braille
# se dibujan con un punto de separación horizontal (``hCellPadding``).
CELL_WIDTH = 2
CELL_HEIGHT = 4
H_CELL_PADDING = 1
#: Punto braille (bit 0 = punto 1) -> (x, y) dentro de la celda.
BRAILLE_DOT_COORDS = ((0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (0, 3), (1, 3))

DEST_TEXT = "text"
DEST_GRAPHIC = "graphic"


class DisplayDescriptor(ctypes.Structure):
	_fields_ = [
		("rowCount", ctypes.c_ubyte),
		("columnCount", ctypes.c_ubyte),
		("dividedLine", ctypes.c_ubyte),
		("refreshTime", ctypes.c_ubyte),
	]


class BoardInformation(ctypes.Structure):
	_fields_ = [
		("features", ctypes.c_ubyte),
		("dotsPerCell", ctypes.c_ubyte),
		("distanceBetweenPins", ctypes.c_ubyte),
		("functionKeyCount", ctypes.c_ubyte),
		("text", DisplayDescriptor),
		("graphic", DisplayDescriptor),
	]


@dataclass
class CommandResponse:
	cmd: int
	data: bytes
	dest: int
	seqNum: int


def checksum(body: bytes | bytearray) -> int:
	return functools.reduce(operator.xor, body, CHECKSUM_BASE)


def buildPacket(cmd: int, data: bytes = b"", dest: int = 0, seqNum: int = 0) -> bytes:
	"""Paquete del ordenador al Dot Pad (o al revés: el formato es el mismo)."""
	body = bytearray([dest & 0xFF, *struct.pack(">H", cmd), seqNum & 0xFF, *data])
	body.append(checksum(body))
	return bytes([SYNC1, SYNC2, *struct.pack(">H", len(body)), *body])


class GraphicBuffer:
	"""Celdas de la zona gráfica (``DpTactileGraphicsBuffer`` de NVDA)."""

	def __init__(self, hCellCount: int, vCellCount: int) -> None:
		self.hCellCount = hCellCount
		self.vCellCount = vCellCount
		self.cells = bytearray(hCellCount * vCellCount)
		self.width = hCellCount * CELL_WIDTH
		self.height = vCellCount * CELL_HEIGHT

	def setDot(self, x: int, y: int) -> None:
		if not (0 <= x < self.width and 0 <= y < self.height):
			return
		cellIndex = (y // CELL_HEIGHT) * self.hCellCount + x // CELL_WIDTH
		bit = (y % CELL_HEIGHT) + (x % CELL_WIDTH) * CELL_HEIGHT
		self.cells[cellIndex] |= 1 << bit

	def drawBrailleCells(self, x: int, y: int, cells: list[int]) -> None:
		for cell in cells:
			for dot in range(8):
				if cell & (1 << dot):
					dx, dy = BRAILLE_DOT_COORDS[dot]
					self.setDot(x + dx, y + dy)
			x += CELL_WIDTH + H_CELL_PADDING

	def row(self, index: int) -> bytes:
		start = index * self.hCellCount
		return bytes(self.cells[start : start + self.hCellCount])


def graphicCellCount(columnCount: int) -> int:
	"""Celdas braille que caben en una fila de la zona gráfica."""
	return (columnCount * CELL_WIDTH) // (CELL_WIDTH + H_CELL_PADDING)


class DotPadDriver(HardwareDriver):
	name = "dotPad"
	description = _("Dot Pad (línea braille y gráficos táctiles)")
	usbSerialIds = frozenset({USB_ID})
	genericUsbIds = frozenset({USB_ID})
	baudRate = BAUD_RATE
	#: Las filas se envían desde un hilo propio (las pruebas lo desactivan).
	asyncDisplay = True
	keyOrder = (
		["space"]
		+ [f"dot{i}" for i in range(1, 9)]
		+ ["shiftLeft", "controlLeft", "shiftRight", "controlRight", "panLeft", "panRight"]
		+ ["navCenter", "navUp", "navRight", "navDown", "navLeft"]
		+ [f"f{i}" for i in range(1, 33)]
	)
	dotKeys = {f"dot{i}": i for i in range(1, 9)}
	spaceKeys = frozenset({"space"})
	gestureMap = {
		# Las de NVDA.
		"panLeft": "braille_scrollBack",
		"panRight": "braille_scrollForward",
		# Cruceta (añadidas en Tiresias).
		"navUp": "braille_previousLine",
		"navDown": "braille_nextLine",
		"navLeft": "braille_scrollBack",
		"navRight": "braille_scrollForward",
		"navCenter": "braille_toFocus",
		# Combinaciones comunes del teclado braille.
		"space+dot1": "kb:upArrow",
		"space+dot4": "kb:downArrow",
		"space+dot3": "kb:leftArrow",
		"space+dot6": "kb:rightArrow",
		"space+dot1+dot3": "kb:shift+tab",
		"space+dot4+dot6": "kb:tab",
		"space+dot1+dot3+dot4": "kb:alt",
		"space+dot1+dot5": "kb:escape",
		"space+dot3+dot4": "kb:windows",
		"space+dot1+dot4+dot5": "kb:windows+d",
		"space+dot2+dot3+dot4+dot5": "kb:alt+tab",
		"space+dot1+dot3+dot4+dot5": "showGui",
		"space+dot1+dot2+dot3+dot4+dot5+dot6": "sayAll",
		"space+dot7": "kb:backspace",
		"space+dot8": "kb:enter",
	}
	keyDescriptions = {
		**{f"dot{i}": _("punto {n} del teclado braille").format(n=i) for i in range(1, 9)},
		"space": _("barra espaciadora"),
		"shiftLeft": _("tecla Mayúsculas izquierda"),
		"controlLeft": _("tecla Control izquierda"),
		"shiftRight": _("tecla Mayúsculas derecha"),
		"controlRight": _("tecla Control derecha"),
		"panLeft": _("tecla de desplazamiento izquierda"),
		"panRight": _("tecla de desplazamiento derecha"),
		"navCenter": _("pulsación central de la cruceta"),
		"navUp": _("cruceta hacia arriba"),
		"navDown": _("cruceta hacia abajo"),
		"navLeft": _("cruceta hacia la izquierda"),
		"navRight": _("cruceta hacia la derecha"),
		"f1": _("tecla de función F1 (y siguientes: f2, f3...)"),
	}
	driverSettings = (
		DriverSetting(
			"brailleDestination",
			_("Destino del braille en el Dot Pad:"),
			"choice",
			DEST_TEXT,
			choices=((DEST_TEXT, _("Línea de texto (si la tiene)")), (DEST_GRAPHIC, _("Zona gráfica"))),
		),
	)

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		self._buffer = bytearray()
		self._responses: dict[int, CommandResponse] = {}
		self._board: BoardInformation | None = None
		self._destination = DEST_TEXT
		self._lineCache: dict[int, bytes] = {}
		self._groups: dict[int, set[str]] = {}
		self._pendingCells: list[int] | None = None
		self._writerLock = threading.Lock()
		self._writerEvent = threading.Event()
		self._writerStop = threading.Event()
		self._writer: threading.Thread | None = None
		super().__init__(*args, **kwargs)

	# ------------------------------------------------------------ paquetes
	def _sendCommand(self, cmd: int, data: bytes = b"", dest: int = 0, seqNum: int = 0, rspCmd: int | None = None, timeout: float = RESPONSE_TIMEOUT) -> bytes | None:
		"""Envía una orden y, si se indica ``rspCmd``, espera su respuesta (``None`` si no llega)."""
		if rspCmd is not None:
			with self._cond:
				self._responses.pop(dest, None)
		self._write(buildPacket(cmd, data, dest, seqNum))
		if rspCmd is None:
			return b""

		def arrived() -> bool:
			r = self._responses.get(dest)
			return r is not None and r.cmd == rspCmd

		if not self._waitFor(arrived, timeout):
			return None
		with self._cond:
			response = self._responses.pop(dest)
		return response.data

	def _handleData(self, data: bytes) -> None:
		buf = self._buffer
		buf.extend(data)
		while len(buf) >= 4:
			if buf[0] != SYNC1 or buf[1] != SYNC2:
				del buf[:1]
				continue
			length = struct.unpack(">H", bytes(buf[2:4]))[0]
			total = 4 + length
			if not MIN_PACKET_SIZE <= total <= MAX_PACKET_SIZE:
				# Cabecera falsa (ruido o desincronización): se busca otra.
				del buf[:1]
				continue
			if len(buf) < total:
				return
			body = bytes(buf[4:total])
			del buf[:total]
			try:
				self._processPacket(body)
			except (ValueError, struct.error):
				log.debug("Dot Pad: paquete no válido %r", body, exc_info=True)

	def _processPacket(self, body: bytes) -> None:
		if checksum(body[:-1]) != body[-1]:
			log.debug("Dot Pad: suma de comprobación errónea en %r", body)
			return
		dest = body[0]
		cmd = struct.unpack(">H", body[1:3])[0]
		seqNum = body[3]
		data = body[4:-1]
		kind = cmd & 0x0F
		if kind == 0x01:
			self._responses[dest] = CommandResponse(cmd, data, dest, seqNum)
		elif cmd in (NTF_KEYS_FUNCTION, NTF_KEYS_PERKINS, NTF_KEYS_SCROLL, NTF_KEYS_ROUTING):
			if self.numCells > 0:
				self._handleKeys(cmd & 0xFF, data)
		elif cmd == NTF_ERROR:
			log.debug("Dot Pad: error %r", data)

	# ------------------------------------------------------------ conexión
	def _connect(self, match: DeviceMatch) -> None:
		self._stopWriter()
		with self._cond:
			self._resetState()
		self.numCells = 0
		self._io = self._open(match, baudrate=BAUD_RATE, parity="N", stopBits=1)
		name = self._sendCommand(REQ_DEVICE_NAME, rspCmd=RSP_DEVICE_NAME)
		if name is None:
			raise DisplayNotFound("El Dot Pad no ha dicho su nombre")
		info = self._sendCommand(REQ_BOARD_INFORMATION, rspCmd=RSP_BOARD_INFORMATION)
		if info is None or len(info) < ctypes.sizeof(BoardInformation):
			raise DisplayNotFound("El Dot Pad no ha enviado la información de la placa")
		board = BoardInformation.from_buffer_copy(info[: ctypes.sizeof(BoardInformation)])
		if not board.features & (HAS_TEXT_DISPLAY | HAS_GRAPHIC_DISPLAY):
			raise DisplayNotFound("El Dot Pad no tiene línea de texto ni zona gráfica")
		self._board = board
		self.model = name.decode("ascii", "replace").strip("\x00 ").strip() or "DotPad"
		self.deviceName = self.model
		self._chooseDestination()
		if self.asyncDisplay:
			self._startWriter()

	def _initConnection(self, match: DeviceMatch) -> None:
		pass

	def _resetState(self) -> None:
		self._buffer.clear()
		self._responses = {}
		self._lineCache = {}
		self._groups = {}
		self._pendingCells = None

	def _available(self) -> list[str]:
		board = self._board
		if board is None:
			return []
		out = []
		if board.features & HAS_TEXT_DISPLAY and board.text.rowCount and board.text.columnCount:
			out.append(DEST_TEXT)
		if board.features & HAS_GRAPHIC_DISPLAY and board.graphic.rowCount and board.graphic.columnCount:
			out.append(DEST_GRAPHIC)
		return out

	def _chooseDestination(self) -> None:
		available = self._available()
		if not available:
			raise DisplayNotFound("El Dot Pad no tiene dónde mostrar braille")
		wanted = self.getSetting("brailleDestination")
		self._destination = wanted if wanted in available else available[0]
		board = self._board
		if self._destination == DEST_TEXT:
			cells = board.text.columnCount
		else:
			cells = graphicCellCount(board.graphic.columnCount)
		self.numCells = cells

	def applySettings(self) -> None:
		"""Hilo del núcleo: se ha cambiado el destino en Opciones."""
		if self._io is None or self._board is None or self.numCells <= 0:
			return
		wanted = self.getSetting("brailleDestination")
		if wanted == self._destination or wanted not in self._available():
			return
		writer = self._writer
		if writer is not None and writer.is_alive() and not self._writerStop.is_set():
			# El cambio lo hace el hilo que envía las filas (no se mezclan los envíos).
			self._switchPending = True
			self._writerEvent.set()
			return
		self._switchDestination()

	#: Hay un cambio de destino pendiente para el hilo de envío.
	_switchPending = False

	def _switchDestination(self) -> None:
		"""Borra el destino anterior, cambia al nuevo y vuelve a mostrar el foco."""
		self._switchPending = False
		self._sendLines([0] * self.numCells)
		try:
			self._chooseDestination()
		except DisplayNotFound:
			return
		from .base import _showInitial

		queue_handler.queueFunction(_showInitial)

	# ------------------------------------------------------------ salida
	def _lines(self, cells: list[int]) -> list[tuple[int, bytes, int]]:
		"""(destino, datos, secuencia) de cada fila que hay que enviar."""
		board = self._board
		if board is None:
			return []
		if self._destination == DEST_TEXT:
			out = [(0, b"\x00" + bytes(c & 0xFF for c in cells[: board.text.columnCount]), SEQ_TEXT)]
			# El resto de filas de texto (si las hay) queda en blanco.
			for row in range(1, board.text.rowCount):
				out.append((row, b"\x00" + bytes(board.text.columnCount), SEQ_TEXT))
			return out
		graphic = GraphicBuffer(board.graphic.columnCount, board.graphic.rowCount)
		graphic.drawBrailleCells(0, 0, cells[: graphicCellCount(board.graphic.columnCount)])
		first = board.text.rowCount if board.features & HAS_TEXT_DISPLAY else 0
		return [(first + y, b"\x00" + graphic.row(y), 0) for y in range(graphic.vCellCount)]

	def _sendLines(self, cells: list[int], timeout: float = RESPONSE_TIMEOUT) -> None:
		for dest, data, seqNum in self._lines(cells):
			if self._io is None:
				return
			if self._lineCache.get(dest) == data:
				continue
			code = self._sendCommand(REQ_DISPLAY_LINE, data, dest, seqNum, rspCmd=RSP_DISPLAY_LINE, timeout=timeout)
			if code is None:
				# Sin respuesta: no se espera a las demás filas (se reintenta en la próxima actualización).
				log.debug("Dot Pad: sin respuesta al mostrar la fila %d", dest)
				return
			result = code[0] if code else DISPLAY_NACK
			if result == DISPLAY_ACK:
				self._lineCache[dest] = data
			elif result == DISPLAY_CHECKSUM:
				log.debug("Dot Pad: suma errónea al mostrar la fila %d", dest)
			else:
				log.debug("Dot Pad: fila %d no aceptada (%d)", dest, result)

	def _writeCells(self, cells: list[int]) -> None:
		writer = self._writer
		if writer is not None and writer.is_alive() and not self._writerStop.is_set():
			with self._writerLock:
				self._pendingCells = list(cells)
			self._writerEvent.set()
			return
		self._sendLines(list(cells), CLOSE_RESPONSE_TIMEOUT if self._terminated else RESPONSE_TIMEOUT)

	def _startWriter(self) -> None:
		self._writerStop = threading.Event()
		self._writerEvent = threading.Event()
		self._writer = threading.Thread(target=self._writerLoop, args=(self._writerStop, self._writerEvent), name="braille-dotpad", daemon=True)
		self._writer.start()

	def _writerLoop(self, stop: threading.Event, event: threading.Event) -> None:
		while not stop.is_set():
			event.wait(1.0)
			event.clear()
			if stop.is_set() or self._terminated:
				return
			if self._switchPending and self._io is not None:
				try:
					self._switchDestination()
				except Exception:
					log.debug("Error cambiando el destino del Dot Pad", exc_info=True)
			with self._writerLock:
				cells = self._pendingCells
				self._pendingCells = None
			if cells is None or self._io is None:
				continue
			try:
				self._sendLines(cells)
			except Exception:
				log.debug("Error mostrando en el Dot Pad", exc_info=True)

	def _stopWriter(self) -> None:
		self._writerStop.set()
		self._writerEvent.set()
		writer = self._writer
		self._writer = None
		if writer is not None and writer.is_alive() and writer is not threading.current_thread():
			writer.join(2.0)

	def _onIoError(self, code: int) -> None:
		self._writerStop.set()
		self._writerEvent.set()
		super()._onIoError(code)

	def terminate(self) -> None:
		self._stopWriter()
		super().terminate()

	# ------------------------------------------------------------ teclas
	def _handleKeys(self, group: int, data: bytes) -> None:
		"""Teclas pulsadas de un grupo (bit 7 del primer byte = tecla 0)."""
		if group not in KEY_GROUPS:
			log.debug("Dot Pad: grupo de teclas desconocido %#x", group)
			return
		names: set[str] = set()
		for byteIndex, byte in enumerate(data):
			for bitPos in range(8):
				if byte & (1 << (7 - bitPos)):
					number = byteIndex * 8 + bitPos
					name = self._keyName(group, number)
					if name:
						names.add(name)
		self._groups[group] = names
		down: set[str] = set()
		for keys in self._groups.values():
			down |= keys
		self._keysChanged(down)

	@staticmethod
	def _keyName(group: int, number: int) -> str | None:
		if group == GROUP_FUNCTION:
			return f"f{number + 1}"
		if group == GROUP_PERKINS:
			name = PERKINS_KEYS.get(number)
			if name is None:
				log.debug("Dot Pad: tecla Perkins desconocida %d", number)
			return name
		# Enrutamiento y desplazamiento: sin formato conocido (tampoco en NVDA).
		log.debug("Dot Pad: tecla %d del grupo %#x sin interpretar", number, group)
		return None


BrailleDisplayDriver = DotPadDriver
