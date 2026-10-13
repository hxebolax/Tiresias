"""Líneas braille EcoBraille de la ONCE (Eco 20, Eco 40 y Eco 80).

Adaptado a Tiresias del controlador ``brailleDisplayDrivers/ecoBraille.py``
de NVDA (NonVisual Desktop Access), Copyright (C) 2014-2015 ONCE-CIDAT
<cidat.id@once.es>, distribuido bajo la Licencia Pública General de GNU
versión 2. Tiresias se distribuye bajo la GPL versión 2 o posterior.

Conexión: puerto serie (o adaptador USB-serie) a 19200 baudios, 8 bits, sin
paridad y un bit de parada. La línea no tiene un identificador USB propio,
así que no participa en la detección automática: se elige su puerto COM a
mano. Con el puerto «Automático» se prueban todos los puertos serie que no
son Bluetooth y solo se acepta el que envíe el mensaje de identificación.

Protocolo (tramas de 9 bytes de la línea al ordenador)::

	10 02 TT AA BB CC DD 10 03

- ``TT = F1``: identificación; ``AA`` es el modelo (``80``, ``40`` o ``20``
  celdas). Si al abrir el puerto no llega (la línea ya estaba iniciada, por
  ejemplo al reiniciar el lector), NVDA supone una Eco 80; Tiresias hace lo
  mismo cuando el puerto se ha elegido a mano.
- ``TT = 88``: tecla pulsada. ``AA BB CC DD`` forman un valor de 32 bits:
  ``AA`` entre ``80`` y ``CF`` es el botón de enrutamiento ``AA - 80``;
  ``D0``, ``D1``, ``D5`` y ``D6`` son las teclas de las celdas de estado (no
  se usan); el resto son bits de teclas (F1-F9, F0, A, S y las teclas de
  desplazamiento T1-T5). Cada trama trae la combinación completa.

Del ordenador a la línea: tras abrir se envía la respuesta del protocolo
``61 10 02 F1 57 57 57 10 03`` y una línea en blanco; las celdas van como
``10 02 BC`` + 5 bytes de las celdas de estado (en blanco) + las celdas con
los puntos reordenados (tabla ``output_dots_map`` de NVDA) + ``10 03``. Al
cerrar se repite la respuesta del protocolo.

Nombres de teclas (gestos ``br(ecoBraille):...``): ``F1``...``F9``, ``F0``,
``A``, ``S``, ``T1`` (arriba), ``T2`` (izquierda), ``T3`` (centro), ``T4``
(derecha), ``T5`` (abajo) y ``routing``. Los bits desconocidos se llaman
``keyN``. La EcoBraille no tiene teclado braille.
"""

from __future__ import annotations

from typing import Any

from ...i18n import _
from ...log import getLogger
from .base import DeviceMatch, DisplayNotFound, HardwareDriver

log = getLogger("braille.ecoBraille")

BAUD_RATE = 19200
#: Segundos que se espera el mensaje de identificación al abrir el puerto.
INIT_TIMEOUT = 2.7

STX = b"\x10\x02"
ETX = b"\x10\x03"
PACKET_LENGTH = 9
TYPE_IDENTIFY = 0xF1
TYPE_KEYS = 0x88
#: Modelo -> celdas en el mensaje de identificación.
MODELS = {0x80: 80, 0x40: 40, 0x20: 20}
#: Celdas que se suponen si la línea no se identifica (como NVDA).
DEFAULT_CELLS = 80
#: Respuesta del protocolo (al conectar y al cerrar).
PROTOCOL_ANSWER = b"\x61\x10\x02\xf1\x57\x57\x57\x10\x03"
#: Línea en blanco que se envía al conectar.
BLANK_LINE = b"\x10\x02\xbc\x00\x00\x00\x00\x00\x10\x03"
CELLS_HEADER = b"\x10\x02\xbc"
#: Celdas de estado (siempre en blanco).
STATUS_CELLS = 5

ROUTING_START = 0x80
ROUTING_END = 0xD0  # Primer valor que ya no es de enrutamiento.
#: Valores de ``AA`` de las teclas de las celdas de estado (se ignoran).
STATUS_KEYS = frozenset({0xD0, 0xD1, 0xD5, 0xD6})

#: Bit del valor de 32 bits -> nombre de la tecla.
KEY_BITS = {
	0x01: "F1",
	0x02: "F2",
	0x04: "F3",
	0x08: "F4",
	0x10: "F5",
	0x20: "F6",
	0x40: "F7",
	0x80: "F8",
	0x0100: "F9",
	0x0200: "A",
	0x0400: "F0",
	0x4000: "S",
	0x10000: "T5",
	0x20000: "T4",
	0x40000: "T3",
	0x80000: "T2",
	0x100000: "T1",
}

#: Punto de NVDA/Tiresias (bit 0 = punto 1) -> bit de la EcoBraille.
_DOT_BITS = (0x10, 0x20, 0x40, 0x01, 0x02, 0x04, 0x80, 0x08)


def ecoCell(cell: int) -> int:
	"""Convierte una celda al orden de puntos de la EcoBraille."""
	out = 0
	for bit, value in enumerate(_DOT_BITS):
		if cell & (1 << bit):
			out |= value
	return out


#: Tabla completa (equivale a ``output_dots_map`` de NVDA).
OUTPUT_DOTS_MAP = bytes(ecoCell(c) for c in range(256))


def cellsPacket(cells: list[int]) -> bytes:
	"""Trama de las celdas (``eco_out`` de NVDA)."""
	return CELLS_HEADER + bytes(STATUS_CELLS) + bytes(OUTPUT_DOTS_MAP[c & 0xFF] for c in cells) + ETX


def keyNames(value: int) -> set[str]:
	"""Teclas de un valor de 32 bits que no es de enrutamiento ni de estado."""
	names = set()
	for bit in range(32):
		mask = 1 << bit
		if value & mask:
			names.add(KEY_BITS.get(mask, f"key{bit}"))
	return names


class EcoBrailleDriver(HardwareDriver):
	name = "ecoBraille"
	description = _("EcoBraille (ONCE)")
	#: Solo puerto serie elegido a mano: la línea no tiene identificador propio.
	supportsAutoDetection = False
	baudRate = BAUD_RATE
	keyOrder = ["T1", "T2", "T3", "T4", "T5", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F0", "A", "S"]
	gestureMap = {
		"routing": "braille_routeTo",
		"T1": "braille_previousLine",
		"T5": "braille_nextLine",
		"T2": "braille_scrollBack",
		"T4": "braille_scrollForward",
		"T3": "review_activate",
		"F1": "reviewMode_next",
		"F2": "navigatorObject_parent",
		"F3": "reviewMode_previous",
		"F4": "navigatorObject_previous",
		"F5": "navigatorObject_current",
		"F6": "navigatorObject_next",
		"F7": "navigatorObject_toFocus",
		"F8": "navigatorObject_firstChild",
		"F9": "navigatorObject_moveFocus",
		"F0": "navigatorObject_currentDimensions",
		"A": "braille_toggleTether",
	}
	keyDescriptions = {
		**{f"F{i}": _("tecla de función F{n}").format(n=i) for i in range(1, 10)},
		"F0": _("tecla de función F0 (la décima)"),
		"A": _("tecla A"),
		"S": _("tecla S"),
		"T1": _("tecla de desplazamiento T1 (arriba)"),
		"T2": _("tecla de desplazamiento T2 (izquierda)"),
		"T3": _("tecla de desplazamiento T3 (centro)"),
		"T4": _("tecla de desplazamiento T4 (derecha)"),
		"T5": _("tecla de desplazamiento T5 (abajo)"),
		"routing": _("botón de enrutamiento sobre una celda"),
	}

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		self._buffer = bytearray()
		#: Celdas que dijo la línea en su identificación (0 si aún no).
		self._identified = 0
		super().__init__(*args, **kwargs)

	# ------------------------------------------------------------ puertos
	@classmethod
	def getPortChoices(cls) -> list[tuple[str, str]]:
		from . import ports

		choices = [("auto", _("Automático (puertos serie que respondan)"))]
		for dev in ports.listComPorts():
			if dev.bluetooth:
				continue
			label = dev.friendlyName or dev.path
			if dev.path not in label:
				label = f"{dev.path}: {label}"
			choices.append((dev.path, label))
		return choices

	@classmethod
	def candidateMatches(cls, port: str) -> list[DeviceMatch]:
		from . import ports

		port = port or "auto"
		if port.upper().startswith("COM"):
			return super().candidateMatches(port)
		if port in ("auto", "usb"):
			return [DeviceMatch("serial", dev.usbId, dev.path, False, dev) for dev in ports.listComPorts() if not dev.bluetooth]
		return []

	def _manualPort(self) -> bool:
		"""El puerto se eligió a mano (se acepta sin identificación, como NVDA)."""
		return (self._port or "").upper().startswith("COM")

	# ------------------------------------------------------------ conexión
	def _connect(self, match: DeviceMatch) -> None:
		self._resetState()
		self.numCells = 0
		self._io = self._open(match, baudrate=BAUD_RATE, parity="N", stopBits=1)
		self._waitFor(lambda: self._identified > 0, INIT_TIMEOUT)
		cells = self._identified
		if not cells:
			if not self._manualPort():
				raise DisplayNotFound("La EcoBraille no se ha identificado")
			log.debug("EcoBraille sin identificación en %s: se suponen %d celdas", match.port, DEFAULT_CELLS)
			cells = DEFAULT_CELLS
		self._greet()
		self._setCells(cells)

	def _initConnection(self, match: DeviceMatch) -> None:
		# Conexiones ya abiertas (pruebas): saludo y celdas por defecto.
		self._greet()
		if self.numCells <= 0:
			self._setCells(self._identified or DEFAULT_CELLS)

	def _greet(self) -> None:
		self._write(PROTOCOL_ANSWER)
		self._write(BLANK_LINE)

	def _setCells(self, cells: int) -> None:
		self.model = f"Eco{cells}"
		self.deviceName = f"EcoBraille {cells}"
		self.numCells = cells

	def _resetState(self) -> None:
		self._buffer.clear()
		self._identified = 0

	def _sayGoodbye(self) -> None:
		self._write(PROTOCOL_ANSWER)

	# ------------------------------------------------------------ entrada
	def _handleData(self, data: bytes) -> None:
		buf = self._buffer
		buf.extend(data)
		while len(buf) >= 2:
			start = buf.find(STX)
			if start < 0:
				# Se conserva el último byte por si es el comienzo de una trama.
				del buf[:-1]
				return
			if start:
				del buf[:start]
			if len(buf) < PACKET_LENGTH:
				return
			if buf[7:9] != ETX:
				# Trama rota: se busca la siguiente.
				del buf[:1]
				continue
			packet = bytes(buf[:PACKET_LENGTH])
			del buf[:PACKET_LENGTH]
			self._handlePacket(packet)

	def _handlePacket(self, packet: bytes) -> None:
		kind = packet[2]
		if kind == TYPE_IDENTIFY:
			cells = MODELS.get(packet[3], DEFAULT_CELLS)
			self._identified = cells
			log.debug("EcoBraille identificada: %d celdas", cells)
			return
		if kind != TYPE_KEYS or self.numCells <= 0:
			return
		value = int.from_bytes(packet[3:7], "big")
		if not value:
			return
		high = packet[3]
		if high in STATUS_KEYS:
			return
		if ROUTING_START <= high < ROUTING_END:
			index = high - ROUTING_START
			if index < self.numCells:
				self._fireChord({("routing", index)})
			return
		if high >= ROUTING_END:
			log.debug("EcoBraille: tecla desconocida %08x", value)
			return
		keys = keyNames(value)
		if keys:
			# Cada trama trae la combinación completa.
			self._fireChord(keys)

	# ------------------------------------------------------------ salida
	def _writeCells(self, cells: list[int]) -> None:
		self._write(cellsPacket(cells))


BrailleDisplayDriver = EcoBrailleDriver
