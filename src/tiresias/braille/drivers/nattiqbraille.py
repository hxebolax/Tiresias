"""Línea braille Nattiq nBraille (Nattiq Technologies).

Adaptado a Tiresias del controlador ``brailleDisplayDrivers/nattiqbraille.py``
de NVDA (NonVisual Desktop Access), Copyright (C) 2020-2023 NV Access
Limited y Mohammed Noman (Nattiq Technologies), distribuido bajo la Licencia
Pública General de GNU versión 2. Tiresias se distribuye bajo la GPL
versión 2 o posterior.

Conexión: puerto serie USB de un microcontrolador Atmel con el identificador
de Arduino Leonardo (``VID_2341&PID_8036``). Como ese identificador lo
comparten muchos aparatos caseros, la detección automática solo lo prueba si
el usuario permite los adaptadores USB-serie genéricos; elegida a mano, se
prueba siempre. Velocidad 10 000 000 baudios (la de NVDA; en un puerto USB
virtual da igual), sin paridad.

Protocolo (texto ASCII):

- saludo: ``reset`` y después ``0``; la línea contesta ``0`` seguido de dos
  cifras con el número de celdas (``040``);
- celdas: los valores de las celdas en decimal separados por guiones
  (``0-12-255-...``);
- teclas: ``1`` + dos cifras = botón de enrutamiento (desde 0); ``2``
  arriba, ``3`` abajo, ``4`` derecha y ``5`` izquierda. Cada tecla llega
  sola (no hay combinaciones);
- al cerrar se envía ``reset``.

Nombres de teclas (gestos ``br(nattiqbraille):...``, los de NVDA):
``tback`` (tecla arriba), ``tadvance`` (abajo), ``tnext`` (derecha),
``tprevious`` (izquierda) y ``routing``.
"""

from __future__ import annotations

from typing import Any

from ...i18n import _
from ...log import getLogger
from .base import DeviceMatch, DisplayNotFound, HardwareDriver

log = getLogger("braille.nattiqbraille")

BAUD_RATE = 10_000_000
USB_ID = "VID_2341&PID_8036"
INIT_TAG = b"0"
RESET_TAG = b"reset"
#: Segundos de espera tras ``reset`` y tras ``0`` (``timeout * 10`` en NVDA).
RESET_TIMEOUT = 2.0
INIT_TIMEOUT = 2.0

INIT_RESP = ord("0")
ROUTE_RESP = ord("1")
#: Respuesta -> nombre de la tecla.
KEY_RESPONSES = {
	ord("2"): "tback",
	ord("3"): "tadvance",
	ord("4"): "tnext",
	ord("5"): "tprevious",
}


def cellsText(cells: list[int]) -> bytes:
	return "-".join(str(c & 0xFF) for c in cells).encode("ascii")


class NattiqBrailleDriver(HardwareDriver):
	name = "nattiqbraille"
	description = _("Nattiq nBraille")
	usbSerialIds = frozenset({USB_ID})
	genericUsbIds = frozenset({USB_ID})
	baudRate = BAUD_RATE
	keyOrder = ["tback", "tadvance", "tprevious", "tnext"]
	gestureMap = {
		"tback": "braille_scrollBack",
		"routing": "braille_routeTo",
		"tadvance": "braille_scrollForward",
		"tprevious": "braille_previousLine",
		"tnext": "braille_nextLine",
	}
	keyDescriptions = {
		"tback": _("tecla arriba (tback)"),
		"tadvance": _("tecla abajo (tadvance)"),
		"tnext": _("tecla derecha (tnext)"),
		"tprevious": _("tecla izquierda (tprevious)"),
		"routing": _("botón de enrutamiento sobre una celda"),
	}

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		self._buffer = bytearray()
		self._received = False
		self._cellsReported = 0
		super().__init__(*args, **kwargs)

	# ------------------------------------------------------------ conexión
	def _connect(self, match: DeviceMatch) -> None:
		self._resetState()
		self.numCells = 0
		self._io = self._open(match, baudrate=BAUD_RATE, parity="N", stopBits=1)
		self._write(RESET_TAG)
		self._waitFor(lambda: self._received, RESET_TIMEOUT)
		self._write(INIT_TAG)
		self._waitFor(lambda: self._cellsReported > 0, INIT_TIMEOUT)
		if self._cellsReported <= 0:
			raise DisplayNotFound("La Nattiq nBraille no ha respondido")
		self._setCells(self._cellsReported)

	def _initConnection(self, match: DeviceMatch) -> None:
		self._write(RESET_TAG)
		self._write(INIT_TAG)
		if self._cellsReported:
			self._setCells(self._cellsReported)

	def _setCells(self, cells: int) -> None:
		self.model = f"nBraille{cells}"
		self.deviceName = "Nattiq nBraille"
		self.numCells = cells

	def _resetState(self) -> None:
		self._buffer.clear()
		self._received = False
		self._cellsReported = 0

	def _sayGoodbye(self) -> None:
		self._write(RESET_TAG)

	# ------------------------------------------------------------ entrada
	def _handleData(self, data: bytes) -> None:
		self._received = True
		buf = self._buffer
		buf.extend(data)
		while buf:
			code = buf[0]
			if code in (INIT_RESP, ROUTE_RESP):
				if len(buf) < 3:
					return
				digits = bytes(buf[1:3])
				del buf[:3]
				if not digits.isdigit():
					log.debug("Nattiq nBraille: respuesta no válida %r", digits)
					continue
				value = int(digits)
				if code == INIT_RESP:
					if value > 0:
						self._cellsReported = value
						if self.numCells > 0:
							self._setCells(value)
				elif self.numCells > 0 and value < self.numCells:
					self._fireChord({("routing", value)})
				continue
			del buf[:1]
			name = KEY_RESPONSES.get(code)
			if name is not None and self.numCells > 0:
				self._fireChord({name})

	# ------------------------------------------------------------ salida
	def _writeCells(self, cells: list[int]) -> None:
		self._write(cellsText(cells))


BrailleDisplayDriver = NattiqBrailleDriver
