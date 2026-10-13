"""Seika Notetaker de Nippon Telesoft: MiniSeika (16 y 24 celdas), Seika V6
y V6Pro (40 celdas).

Conexiones:

- USB HID: la línea lleva un puente HID-serie CP2110 de Silicon Labs
  (``VID_10C4&PID_EA80``) y no necesita controladores. Al abrirlo se
  configura su puerto serie interno (9600 baudios, 8 bits, sin paridad) con
  el informe de características 0x50 y se activa con el 0x41. Los datos van
  dentro de informes cuyo número (1 a 63) es la cantidad de bytes útiles que
  llevan detrás;
- Bluetooth: puerto serie Bluetooth a 9600 baudios sin paridad. La línea se
  anuncia como «TSM nnnn» (cuatro cifras).

Protocolo (el mismo flujo en las dos conexiones): cada paquete empieza por
``FF FF``, sigue el código de la orden, la longitud de los datos y los
datos.

- ``FF FF A1``: petición de identificación. Respuesta ``FF FF A2 n``: número
  de botones, de celdas y de botones de enrutamiento y una descripción en
  ASCII;
- ``FF FF A3 n celdas``: escritura de celdas;
- ``FF FF A4 n bits``: botones de enrutamiento pulsados (un bit por botón);
- ``FF FF A6 03 puntos teclas teclas``: teclado braille (un bit por punto) y
  demás teclas (16 bits);
- ``FF FF A8 n``: teclas (3 bytes, como en A6) y enrutamiento a la vez.

Cada paquete de teclas trae la combinación completa.

Nombres de teclas (gestos ``br(seikaNotetaker):...``): ``d1``...``d8``
(teclado braille), ``space`` y ``backspace`` (teclas de los pulgares; las
dos escriben un espacio con los puntos), ``lb`` y ``rb`` (botones de
desplazamiento izquierdo y derecho), ``ljUp``, ``ljDown``, ``ljLeft``,
``ljRight`` y ``ljCenter`` (joystick izquierdo), ``rjUp``... ``rjCenter``
(joystick derecho), ``routing`` y ``multiRouting``.
"""

from __future__ import annotations

import re
from typing import Any

from ...i18n import _
from ...log import getLogger
from .base import DeviceMatch, DisplayNotFound, HardwareDriver
from .ports import DeviceInfo

log = getLogger("braille.seikaNotetaker")

BAUD_RATE = 9600
USB_ID = "VID_10C4&PID_EA80"

PREFIX = b"\xff\xff"
CMD_REQUEST_INFO = 0xA1
CMD_INFO = 0xA2
CMD_WRITE = 0xA3
CMD_ROUTING = 0xA4
CMD_KEYS = 0xA6
CMD_KEYS_ROUTING = 0xA8

#: Informe de características del CP2110 con la configuración del puerto
#: serie: velocidad (4 bytes), paridad (0 = ninguna), control de flujo
#: (0 = ninguno), bits de datos (3 = ocho) y bits de parada (0 = uno).
HID_UART_CONFIG = bytes((0x50,)) + BAUD_RATE.to_bytes(4, "big") + bytes((0x00, 0x00, 0x03, 0x00))
#: Informe de características del CP2110 que activa el puerto serie.
HID_UART_ENABLE = bytes((0x41, 0x01))
#: Bytes útiles como máximo en cada informe de datos del CP2110.
HID_MAX_DATA = 63

#: Bit de la palabra de teclas -> nombre.
KEY_BITS = {
	0: "backspace",
	1: "space",
	2: "lb",
	3: "rb",
	4: "ljCenter",
	5: "ljLeft",
	6: "ljRight",
	7: "ljUp",
	8: "ljDown",
	9: "rjCenter",
	10: "rjLeft",
	11: "rjRight",
	12: "rjUp",
	13: "rjDown",
}

#: Modelos por número de celdas: (modelo para los gestos, nombre legible).
MODELS = {
	16: ("MiniSeika16", "MiniSeika 16"),
	24: ("MiniSeika24", "MiniSeika 24"),
	40: ("SeikaV6", "Seika V6"),
}

#: Segundos que se espera la identificación en cada intento.
IDENTIFY_TIMEOUT = 1.0
IDENTIFY_TIMEOUT_BLUETOOTH = 2.0
IDENTIFY_ATTEMPTS = 2

_BT_NAME = re.compile(r"TSM \d{4}")


def buildPacket(command: int, data: bytes = b"") -> bytes:
	"""Paquete del flujo serie: ``FF FF orden longitud datos``."""
	return PREFIX + bytes((command, len(data) & 0xFF)) + bytes(data)


def hidReports(stream: bytes) -> list[bytes]:
	"""Informes de datos del CP2110 que llevan ``stream`` (63 bytes como máximo cada uno)."""
	out = []
	for start in range(0, len(stream), HID_MAX_DATA):
		chunk = stream[start : start + HID_MAX_DATA]
		out.append(bytes((len(chunk),)) + chunk)
	return out


def hidPayload(report: bytes) -> bytes:
	"""Bytes del flujo serie que trae un informe de entrada del CP2110."""
	if not report:
		return b""
	count = report[0]
	if not 1 <= count <= HID_MAX_DATA:
		return b""
	return bytes(report[1 : 1 + count])


def keyNames(dots: int, keys: int) -> set[str]:
	"""Nombres de las teclas pulsadas (puntos y demás teclas)."""
	names = {f"d{i + 1}" for i in range(8) if dots & (1 << i)}
	for bit in range(16):
		if keys & (1 << bit):
			names.add(KEY_BITS.get(bit, f"key{bit}"))
	return names


def routingIndexes(data: bytes) -> list[int]:
	"""Índices (desde 0) de los botones de enrutamiento con su bit activado."""
	return [i * 8 + bit for i, value in enumerate(data) for bit in range(8) if value & (1 << bit)]


class SeikaNotetakerDriver(HardwareDriver):
	name = "seikaNotetaker"
	description = _("Seika Notetaker (MiniSeika, Seika V6 y V6Pro)")
	usbHidIds = frozenset({USB_ID})
	bluetoothPrefixes = ("TSM ",)
	baudRate = BAUD_RATE
	keyOrder = [
		"lb",
		"rb",
		"ljUp",
		"ljDown",
		"ljLeft",
		"ljRight",
		"ljCenter",
		"rjUp",
		"rjDown",
		"rjLeft",
		"rjRight",
		"rjCenter",
		"backspace",
		"space",
		"d1",
		"d2",
		"d3",
		"d4",
		"d5",
		"d6",
		"d7",
		"d8",
	]
	dotKeys = {f"d{i}": i for i in range(1, 9)}
	spaceKeys = frozenset({"space", "backspace"})
	gestureMap = {
		# Enrutamiento.
		"routing": "braille_routeTo",
		"multiRouting": "braille_selectRange",
		"ljCenter+routing": "braille_reportFormatting",
		# Botones de desplazamiento.
		"lb": "braille_scrollBack",
		"rb": "braille_scrollForward",
		"lb+rb": "showGui",
		"space+lb": "review_top",
		"space+rb": "review_bottom",
		# Joystick izquierdo: líneas y tabulador.
		"ljUp": "braille_previousLine",
		"ljDown": "braille_nextLine",
		"ljLeft": "kb:shift+tab",
		"ljRight": "kb:tab",
		"ljCenter": "braille_toFocus",
		"space+ljCenter": "braille_toggleTether",
		"space+ljUp": "kb:home",
		"space+ljDown": "kb:end",
		"space+ljLeft": "kb:pageUp",
		"space+ljRight": "kb:pageDown",
		"backspace+ljUp": "kb:control+home",
		"backspace+ljDown": "kb:control+end",
		"backspace+ljCenter": "reportCurrentFocus",
		# Joystick derecho: flechas.
		"rjUp": "kb:upArrow",
		"rjDown": "kb:downArrow",
		"rjLeft": "kb:leftArrow",
		"rjRight": "kb:rightArrow",
		"rjCenter": "kb:enter",
		"space+rjUp": "kb:shift+upArrow",
		"space+rjDown": "kb:shift+downArrow",
		"space+rjLeft": "kb:shift+leftArrow",
		"space+rjRight": "kb:shift+rightArrow",
		"space+rjCenter": "kb:escape",
		"backspace+rjUp": "kb:control+upArrow",
		"backspace+rjDown": "kb:control+downArrow",
		"backspace+rjLeft": "kb:control+leftArrow",
		"backspace+rjRight": "kb:control+rightArrow",
		"backspace+rjCenter": "kb:windows",
		# Teclas de los pulgares.
		"backspace": "kb:backspace",
		"backspace+space": "sayAll",
		# Espacio y puntos.
		"space+d1": "kb:upArrow",
		"space+d4": "kb:downArrow",
		"space+d3": "kb:leftArrow",
		"space+d6": "kb:rightArrow",
		"space+d2": "kb:control+leftArrow",
		"space+d5": "kb:control+rightArrow",
		"space+d1+d2": "kb:home",
		"space+d4+d5": "kb:end",
		"space+d1+d2+d3": "kb:control+home",
		"space+d4+d5+d6": "kb:control+end",
		"space+d1+d3": "kb:shift+tab",
		"space+d4+d6": "kb:tab",
		"space+d1+d5": "kb:escape",
		"space+d1+d3+d4": "kb:alt",
		"space+d3+d4": "kb:windows",
		"space+d1+d4+d5": "kb:windows+d",
		"space+d2+d3+d4+d5": "kb:alt+tab",
		"space+d1+d4": "reportCurrentLine",
		"space+d1+d3+d4+d5": "showGui",
		"space+d1+d2+d3+d4+d5+d6": "sayAll",
		"space+d7": "kb:backspace",
		"space+d8": "kb:enter",
	}
	keyDescriptions = {
		"d1": _("punto 1 del teclado braille"),
		"d2": _("punto 2 del teclado braille"),
		"d3": _("punto 3 del teclado braille"),
		"d4": _("punto 4 del teclado braille"),
		"d5": _("punto 5 del teclado braille"),
		"d6": _("punto 6 del teclado braille"),
		"d7": _("punto 7 del teclado braille"),
		"d8": _("punto 8 del teclado braille"),
		"space": _("tecla de espacio (pulgar derecho)"),
		"backspace": _("tecla de retroceso (pulgar izquierdo); con puntos también escribe un espacio"),
		"lb": _("botón de desplazamiento izquierdo"),
		"rb": _("botón de desplazamiento derecho"),
		"ljUp": _("joystick izquierdo hacia arriba"),
		"ljDown": _("joystick izquierdo hacia abajo"),
		"ljLeft": _("joystick izquierdo a la izquierda"),
		"ljRight": _("joystick izquierdo a la derecha"),
		"ljCenter": _("pulsar el joystick izquierdo"),
		"rjUp": _("joystick derecho hacia arriba"),
		"rjDown": _("joystick derecho hacia abajo"),
		"rjLeft": _("joystick derecho a la izquierda"),
		"rjRight": _("joystick derecho a la derecha"),
		"rjCenter": _("pulsar el joystick derecho"),
		"routing": _("botón de enrutamiento"),
		"multiRouting": _("dos botones de enrutamiento a la vez"),
	}

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		self._buffer = bytearray()
		self._hid = False
		self.numButtons = 0
		self.numRoutingKeys = 0
		self.deviceDescription = ""
		super().__init__(*args, **kwargs)

	# ------------------------------------------------------------ detección
	@classmethod
	def _bluetoothNameMatches(cls, name: str) -> bool:
		return bool(name) and _BT_NAME.match(name) is not None

	@classmethod
	def matchDevice(cls, dev: DeviceInfo, allowGeneric: bool = True) -> DeviceMatch | None:
		# Por Bluetooth la línea solo ofrece el puerto serie.
		if dev.kind == "hid" and dev.bluetooth:
			return None
		return super().matchDevice(dev, allowGeneric=allowGeneric)

	# ------------------------------------------------------------ conexión
	def _connect(self, match: DeviceMatch) -> None:
		self._resetState()
		self.numCells = 0
		self._hid = match.type == "hid"
		if self._hid:
			self._io = self._open(match, exclusive=True)
			self._configureHid()
		else:
			self._io = self._open(match, baudrate=BAUD_RATE, parity="N", stopBits=1)
		timeout = IDENTIFY_TIMEOUT_BLUETOOTH if match.bluetooth else IDENTIFY_TIMEOUT
		for _attempt in range(IDENTIFY_ATTEMPTS):
			self._sendStream(buildPacket(CMD_REQUEST_INFO))
			if self._waitFor(lambda: self.numCells > 0, timeout):
				break
		if self.numCells <= 0:
			raise DisplayNotFound("La Seika Notetaker no ha respondido")

	def _initConnection(self, match: DeviceMatch) -> None:
		# Conexiones ya abiertas (pruebas).
		self._hid = match.type == "hid"
		if self._hid:
			self._configureHid()
		self._sendStream(buildPacket(CMD_REQUEST_INFO))

	def _configureHid(self) -> None:
		"""Configura y activa el puerto serie interno del puente CP2110."""
		self._io.setFeature(HID_UART_CONFIG)
		self._io.setFeature(HID_UART_ENABLE)

	def _resetState(self) -> None:
		self._buffer.clear()

	def _sendStream(self, data: bytes) -> None:
		if self._hid:
			for report in hidReports(data):
				self._write(report)
		else:
			self._write(data)

	# ------------------------------------------------------------ entrada
	def _handleData(self, data: bytes) -> None:
		if self._hid:
			data = hidPayload(data)
			if not data:
				return
		buf = self._buffer
		buf.extend(data)
		while True:
			start = buf.find(PREFIX)
			if start < 0:
				# Se conserva un FF final por si es el inicio de un paquete.
				keep = 1 if buf[-1:] == b"\xff" else 0
				del buf[: len(buf) - keep]
				return
			if start:
				log.debug("Bytes sueltos descartados: %r", bytes(buf[:start]))
				del buf[:start]
			if len(buf) < 4:
				return
			command = buf[2]
			if command == 0xFF:
				del buf[0]
				continue
			length = buf[3]
			if len(buf) < 4 + length:
				return
			args = bytes(buf[4 : 4 + length])
			del buf[: 4 + length]
			self._handlePacket(command, args)

	def _handlePacket(self, command: int, args: bytes) -> None:
		if command == CMD_INFO:
			self._handleInfo(args)
		elif command == CMD_KEYS:
			self._handleKeys(args[:3], b"")
		elif command == CMD_ROUTING:
			self._handleKeys(b"", args)
		elif command == CMD_KEYS_ROUTING:
			self._handleKeys(args[:3], args[3:])
		else:
			log.debug("Orden desconocida de la Seika Notetaker: %#x %r", command, args)

	def _handleInfo(self, args: bytes) -> None:
		if len(args) < 3 or not args[1]:
			log.debug("Identificación incompleta de la Seika Notetaker: %r", args)
			return
		self.numButtons = args[0]
		cells = args[1]
		self.numRoutingKeys = args[2]
		self.deviceDescription = "".join(chr(b) for b in args[3:] if 32 <= b < 127).strip()
		model, name = MODELS.get(cells, (f"Seika{cells}", _("Seika Notetaker de {cells} celdas").format(cells=cells)))
		self.model = model
		self.deviceName = f"{name} ({self.deviceDescription})" if self.deviceDescription else name
		log.debug("Seika Notetaker: %d celdas, %d botones, %d de enrutamiento, %r", cells, self.numButtons, self.numRoutingKeys, self.deviceDescription)
		self.numCells = cells

	def _handleKeys(self, keyBytes: bytes, routing: bytes) -> None:
		chord: set = set()
		if len(keyBytes) >= 3:
			chord |= keyNames(keyBytes[0], keyBytes[1] | (keyBytes[2] << 8))
		limit = self.numCells or len(routing) * 8
		chord |= {("routing", i) for i in routingIndexes(routing) if i < limit}
		if chord:
			# Cada paquete trae la combinación completa.
			self._fireChord(chord)

	# ------------------------------------------------------------ salida
	def _writeCells(self, cells: list[int]) -> None:
		data = bytes((self.numCells & 0xFF,)) + bytes(c & 0xFF for c in cells)
		self._sendStream(PREFIX + bytes((CMD_WRITE,)) + data)


BrailleDisplayDriver = SeikaNotetakerDriver
