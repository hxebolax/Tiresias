"""Línea braille hedo ProfiLine USB (80 celdas y 4 de estado), de hedo
Reha-Technik GmbH.

Adaptado a Tiresias del controlador ``brailleDisplayDrivers/hedoProfiLine.py``
de NVDA (NonVisual Desktop Access), Copyright (C) 2011 Sebastian Kruber
<sebastian.kruber@hedo.de> (con partes del controlador Baum de James Teh),
distribuido bajo la Licencia Pública General de GNU versión 2. Tiresias se
distribuye bajo la GPL versión 2 o posterior.

Conexión: chip USB-serie FTDI con identificador propio de hedo
(``VID_0403&PID_DE59``; NVDA también prueba el de la MobilLine,
``PID_DE58``). Puerto a 19200 baudios, 8 bits, paridad impar y un bit de
parada. NVDA busca el puerto por el identificador; Tiresias, además, la
detecta automáticamente (el identificador es exclusivo de hedo).

Protocolo:

- saludo: se envía dos veces una línea en blanco (``01`` + 160 ceros, como
  NVDA) y la línea contesta con ``7E`` (confirmación);
- celdas: ``01`` + 4 celdas de estado (en blanco) + 80 celdas; la línea
  confirma cada envío con ``7E``;
- enrutamiento: ``20``...``6F`` al pulsar (celdas 0 a 79); al soltar llega
  el mismo valor + ``80``, que se ignora;
- teclas: un byte al pulsar y el mismo + ``80`` al soltar (``K1`` 04,
  ``K2``/``B1`` 03, ``K3`` 08, ``B2`` 07, ``B3`` 0B, ``B4`` 0F, ``B5`` 13,
  ``B6`` 17, ``B7`` 1B, ``B8`` 1F). La combinación se produce al soltar la
  primera tecla.

Nombres de teclas (gestos ``br(hedoProfiLine):...``): ``K1``, ``K2``,
``K3``, ``B2``...``B8`` y ``routing``.
"""

from __future__ import annotations

from typing import Any

from ...i18n import _
from ...log import getLogger
from .base import DeviceMatch, DisplayNotFound, HardwareDriver

log = getLogger("braille.hedoProfiLine")

BAUD_RATE = 19200
ACK = 0x7E
INIT = b"\x01"
CR_BEGIN = 0x20
CR_END = 0x6F
RELEASE_OFFSET = 0x80
CELL_COUNT = 80
STATUS_CELL_COUNT = 4
#: Segundos que se espera la confirmación del saludo.
ACK_TIMEOUT = 0.5

KEYMAP = {
	0x04: "K1",
	0x03: "K2",  # K2 o B1
	0x08: "K3",
	0x07: "B2",
	0x0B: "B3",
	0x0F: "B4",
	0x13: "B5",
	0x17: "B6",
	0x1B: "B7",
	0x1F: "B8",
}

USB_PROFILINE = "VID_0403&PID_DE59"
USB_MOBILLINE = "VID_0403&PID_DE58"


def blankGreeting() -> bytes:
	"""Línea en blanco del saludo (NVDA envía 160 celdas)."""
	return INIT + bytes(CELL_COUNT + CELL_COUNT)


class HedoProfiLineDriver(HardwareDriver):
	name = "hedoProfiLine"
	description = _("hedo ProfiLine USB")
	usbSerialIds = frozenset({USB_PROFILINE, USB_MOBILLINE})
	baudRate = BAUD_RATE
	keyOrder = ["K1", "K2", "K3", "B2", "B3", "B4", "B5", "B6", "B7", "B8"]
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
		"K1": _("tecla K1"),
		"K2": _("tecla K2 (o B1)"),
		"K3": _("tecla K3"),
		**{f"B{i}": _("tecla B{n}").format(n=i) for i in range(2, 9)},
		"routing": _("botón de enrutamiento sobre una celda"),
	}

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		self._acked = False
		super().__init__(*args, **kwargs)

	# ------------------------------------------------------------ conexión
	def _connect(self, match: DeviceMatch) -> None:
		self._resetState()
		self.numCells = 0
		self._io = self._open(match, baudrate=BAUD_RATE, parity="O", stopBits=1)
		self._greet()
		self._waitFor(lambda: self._acked, ACK_TIMEOUT)
		if not self._acked:
			raise DisplayNotFound("La hedo ProfiLine no ha confirmado el saludo")
		self._setConnected()

	def _initConnection(self, match: DeviceMatch) -> None:
		self._greet()
		self._setConnected()

	def _greet(self) -> None:
		blank = blankGreeting()
		self._write(blank)
		self._write(blank)

	def _setConnected(self) -> None:
		self.model = "ProfiLine"
		self.deviceName = "hedo ProfiLine USB"
		self.numCells = CELL_COUNT

	def _resetState(self) -> None:
		self._acked = False

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
		elif CR_BEGIN + RELEASE_OFFSET <= byte <= CR_END + RELEASE_OFFSET:
			return
		elif byte in KEYMAP:
			self._keyPressed(KEYMAP[byte])
		elif byte > RELEASE_OFFSET and byte - RELEASE_OFFSET in KEYMAP:
			self._keyReleased(KEYMAP[byte - RELEASE_OFFSET])
		else:
			log.debug("hedo ProfiLine: byte desconocido %#x", byte)

	# ------------------------------------------------------------ salida
	def _writeCells(self, cells: list[int]) -> None:
		cells = (list(cells) + [0] * CELL_COUNT)[:CELL_COUNT]
		self._write(INIT + bytes(STATUS_CELL_COUNT) + bytes(c & 0xFF for c in cells))


BrailleDisplayDriver = HedoProfiLineDriver
