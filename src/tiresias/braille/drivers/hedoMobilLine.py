"""Línea braille hedo MobilLine USB (40 celdas y 2 de estado), de hedo
Reha-Technik GmbH.

Adaptado a Tiresias del controlador ``brailleDisplayDrivers/hedoMobilLine.py``
de NVDA (NonVisual Desktop Access), Copyright (C) 2011 Sebastian Kruber
<sebastian.kruber@hedo.de> (con partes del controlador Baum de James Teh),
distribuido bajo la Licencia Pública General de GNU versión 2. Tiresias se
distribuye bajo la GPL versión 2 o posterior.

Conexión: chip USB-serie FTDI con identificador propio de hedo
(``VID_0403&PID_DE58``). Puerto a 9600 baudios, 8 bits, paridad impar y un
bit de parada. NVDA busca el puerto por el identificador; Tiresias, además,
la detecta automáticamente (el identificador es exclusivo de hedo).

Protocolo:

- saludo: se envía dos veces una línea en blanco (``01`` + 42 ceros) y la
  línea contesta con ``30`` (confirmación);
- celdas: ``01`` + 2 celdas de estado (en blanco) + 40 celdas;
- enrutamiento: ``40``...``67`` (celdas 0 a 39);
- teclas: en cada pulsación o liberación llegan tres bytes, uno por grupo;
  los 4 bits altos dicen el grupo (``0x`` B1-B3, ``1x`` B4-B6, ``2x``
  K1-K3) y los 3 bajos, las teclas pulsadas del grupo. La combinación se
  produce al soltar la primera tecla.

Nombres de teclas (gestos ``br(hedoMobilLine):...``): ``K1``...``K3``,
``B1``...``B6`` y ``routing``.
"""

from __future__ import annotations

from typing import Any

from ...i18n import _
from ...log import getLogger
from .base import DeviceMatch, DisplayNotFound, HardwareDriver

log = getLogger("braille.hedoMobilLine")

BAUD_RATE = 9600
USB_ID = "VID_0403&PID_DE58"
ACK = 0x30
INIT = b"\x01"
CR_BEGIN = 0x40
CR_END = 0x67
CELL_COUNT = 40
STATUS_CELL_COUNT = 2
#: Segundos que se espera la confirmación del saludo.
ACK_TIMEOUT = 0.5

#: Grupo (4 bits altos) -> nombres de las teclas de los bits 0, 1 y 2.
KEY_GROUPS = {
	0x00: ("B1", "B2", "B3"),
	0x10: ("B4", "B5", "B6"),
	0x20: ("K1", "K2", "K3"),
}


def blankGreeting() -> bytes:
	return INIT + bytes(CELL_COUNT + STATUS_CELL_COUNT)


class HedoMobilLineDriver(HardwareDriver):
	name = "hedoMobilLine"
	description = _("hedo MobilLine USB")
	usbSerialIds = frozenset({USB_ID})
	baudRate = BAUD_RATE
	keyOrder = ["K1", "K2", "K3", "B1", "B2", "B3", "B4", "B5", "B6"]
	gestureMap = {
		"K1": "braille_scrollBack",
		"K2": "braille_toggleTether",
		"K3": "braille_scrollForward",
		"B2": "braille_previousLine",
		"B5": "braille_nextLine",
		"B6": "sayAll",
		"routing": "braille_routeTo",
	}
	keyDescriptions = {
		**{f"K{i}": _("tecla K{n}").format(n=i) for i in range(1, 4)},
		**{f"B{i}": _("tecla B{n}").format(n=i) for i in range(1, 7)},
		"routing": _("botón de enrutamiento sobre una celda"),
	}

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		self._acked = False
		#: Teclas pulsadas de cada grupo.
		self._groups: dict[int, set[str]] = {}
		super().__init__(*args, **kwargs)

	# ------------------------------------------------------------ conexión
	def _connect(self, match: DeviceMatch) -> None:
		self._resetState()
		self.numCells = 0
		self._io = self._open(match, baudrate=BAUD_RATE, parity="O", stopBits=1)
		self._greet()
		self._waitFor(lambda: self._acked, ACK_TIMEOUT)
		if not self._acked:
			raise DisplayNotFound("La hedo MobilLine no ha confirmado el saludo")
		self._setConnected()

	def _initConnection(self, match: DeviceMatch) -> None:
		self._greet()
		self._setConnected()

	def _greet(self) -> None:
		blank = blankGreeting()
		self._write(blank)
		self._write(blank)

	def _setConnected(self) -> None:
		self.model = "MobilLine"
		self.deviceName = "hedo MobilLine USB"
		self.numCells = CELL_COUNT

	def _resetState(self) -> None:
		self._acked = False
		self._groups = {}

	# ------------------------------------------------------------ entrada
	def _handleData(self, data: bytes) -> None:
		for byte in data:
			if byte == ACK:
				self._acked = True
				continue
			if self.numCells <= 0:
				continue
			self._handleByte(byte)

	def _handleByte(self, byte: int) -> None:
		if CR_BEGIN <= byte <= CR_END:
			self._fireChord({("routing", byte - CR_BEGIN)})
			return
		names = KEY_GROUPS.get(byte & 0xF0)
		if names is None:
			log.debug("hedo MobilLine: byte desconocido %#x", byte)
			return
		self._groups[byte & 0xF0] = {name for bit, name in enumerate(names) if byte & (1 << bit)}
		down: set[str] = set()
		for keys in self._groups.values():
			down |= keys
		self._keysChanged(down)

	# ------------------------------------------------------------ salida
	def _writeCells(self, cells: list[int]) -> None:
		cells = (list(cells) + [0] * CELL_COUNT)[:CELL_COUNT]
		self._write(INIT + bytes(STATUS_CELL_COUNT) + bytes(c & 0xFF for c in cells))


BrailleDisplayDriver = HedoMobilLineDriver
