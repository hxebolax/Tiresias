"""Línea braille SuperBraille (versión 3.2 y compatibles).

Adaptado a Tiresias del controlador ``brailleDisplayDrivers/superBrl.py``
de NVDA (NonVisual Desktop Access), Copyright (C) 2017-2023 NV Access
Limited, Coscell Kao y Babbage B.V., distribuido bajo la Licencia Pública
General de GNU versión 2. Tiresias se distribuye bajo la GPL versión 2 o
posterior.

Conexión: puente USB-serie CP210x de Silicon Labs (``VID_10C4&PID_EA60``),
el mismo chip genérico que usan las Seika y otros aparatos: la detección
automática solo lo prueba si el usuario lo permite (y después de que lo haya
probado el controlador de Seika). Puerto a 9600 baudios, 8 bits, sin paridad
y un bit de parada.

Protocolo:

- identificación: se envía ``FF FF 0A``; la línea contesta ``00 05``, el
  número de celdas, un byte más y 8 bytes con la versión;
- celdas: ``FF FF 04 00 99 00 50 00`` seguido de ``00 <celda>`` por cada
  celda;
- al cerrar hay que esperar medio segundo antes de soltar el puerto: si no,
  la línea puede quedar en un estado en el que no se deja iniciar.

La línea no envía sus teclas por el puerto: sus dos teclas de
desplazamiento escriben el «menos» y el «más» del teclado numérico. Como en
NVDA, mientras la SuperBraille es la línea elegida, ``kb:numpadMinus`` y
``kb:numpadPlus`` desplazan la línea braille hacia atrás y hacia delante
(órdenes propias del controlador, que se pueden cambiar en Gestos de
entrada).
"""

from __future__ import annotations

import time
from typing import Any

from ...baseobject import script
from ...i18n import _
from ...log import getLogger
from .base import DeviceMatch, DisplayNotFound, HardwareDriver

log = getLogger("braille.superBrl")

BAUD_RATE = 9600
USB_ID = "VID_10C4&PID_EA60"
#: Petición de identificación (y del número de celdas).
DESCRIBE_TAG = b"\xff\xff\x0a"
#: Cabecera de la escritura de celdas.
DISPLAY_TAG = b"\xff\xff\x04\x00\x99\x00\x50\x00"
#: Inicio de la respuesta de identificación.
REPLY_PREFIX = b"\x00\x05"
#: Longitud completa de la respuesta (prefijo, celdas, un byte y 8 de versión).
REPLY_LENGTH = 12
#: Segundos de espera de la respuesta (como el ``TIMEOUT`` de NVDA).
TIMEOUT = 0.5
#: Pausa antes de cerrar el puerto.
CLOSE_DELAY = 0.5
MAX_BUFFER = 256


def _printable(data: bytes) -> str:
	return "".join(chr(b) for b in data if 32 <= b < 127).strip()


class SuperBrailleDriver(HardwareDriver):
	name = "superBrl"
	description = _("SuperBraille")
	usbSerialIds = frozenset({USB_ID})
	genericUsbIds = frozenset({USB_ID})
	tryClaimedPorts = True
	baudRate = BAUD_RATE
	gestureMap: dict[str, str] = {}
	keyDescriptions: dict[str, str] = {}

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		self._buffer = bytearray()
		self.version = ""
		super().__init__(*args, **kwargs)

	# ------------------------------------------------------------ conexión
	def _connect(self, match: DeviceMatch) -> None:
		self._resetState()
		self.numCells = 0
		self._io = self._open(match, baudrate=BAUD_RATE, parity="N", stopBits=1)
		self._write(DESCRIBE_TAG)
		self._waitFor(self._replyComplete, TIMEOUT)
		with self._cond:
			self._identify(final=True)
		if self.numCells <= 0:
			raise DisplayNotFound("La SuperBraille no ha respondido")

	def _initConnection(self, match: DeviceMatch) -> None:
		self._write(DESCRIBE_TAG)

	def _resetState(self) -> None:
		self._buffer.clear()

	def _replyComplete(self) -> bool:
		pos = self._buffer.find(REPLY_PREFIX)
		return pos >= 0 and len(self._buffer) - pos >= REPLY_LENGTH

	def _identify(self, final: bool = False) -> None:
		buf = self._buffer
		pos = buf.find(REPLY_PREFIX)
		if pos < 0 or len(buf) - pos < 3:
			return
		if len(buf) - pos < REPLY_LENGTH and not final:
			return
		cells = buf[pos + 2]
		if not cells:
			return
		self.version = _printable(bytes(buf[pos + 4 : pos + REPLY_LENGTH]))
		del buf[: pos + REPLY_LENGTH]
		self.model = f"SuperBraille{cells}"
		self.deviceName = "SuperBraille"
		log.info("SuperBraille encontrada, versión %s, %d celdas", self.version or "-", cells)
		self.numCells = cells

	def _sayGoodbye(self) -> None:
		# Sin esta pausa, la línea puede quedar sin poder iniciarse de nuevo.
		time.sleep(CLOSE_DELAY)

	# ------------------------------------------------------------ entrada
	def _handleData(self, data: bytes) -> None:
		# La línea solo envía la respuesta de identificación.
		buf = self._buffer
		buf.extend(data)
		if self.numCells <= 0 and self._replyComplete():
			self._identify()
		if len(buf) > MAX_BUFFER:
			del buf[:-MAX_BUFFER]

	# ------------------------------------------------------------ salida
	def _writeCells(self, cells: list[int]) -> None:
		self._write(DISPLAY_TAG + b"".join(b"\x00" + bytes((c & 0xFF,)) for c in cells))

	# ------------------------------------------------------------ teclas
	@script(
		description=_("Desplaza la línea braille hacia atrás (tecla de desplazamiento de la SuperBraille)"),
		category=_("Braille"),
		gesture="kb:numpadMinus",
	)
	def script_scrollBack(self, gesture) -> None:
		from ...global_commands import commands

		commands.script_braille_scrollBack(gesture)

	@script(
		description=_("Desplaza la línea braille hacia delante (tecla de desplazamiento de la SuperBraille)"),
		category=_("Braille"),
		gesture="kb:numpadPlus",
	)
	def script_scrollForward(self, gesture) -> None:
		from ...global_commands import commands

		commands.script_braille_scrollForward(gesture)


BrailleDisplayDriver = SuperBrailleDriver
