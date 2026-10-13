"""Líneas braille Seika de Nippon Telesoft: Seika versión 3, 4 y 5
(40 celdas) y Seika80 (80 celdas), incluidas las Seika 3 más antiguas.

Las Seika V6, V6Pro y MiniSeika usan otro protocolo: son del controlador
``seikaNotetaker``.

Conexiones:

- USB: la línea lleva un puente USB-serie CP210x de Silicon Labs
  (``VID_10C4&PID_EA60``) y aparece como puerto COM con el controlador del
  fabricante. Es un chip genérico que usan otros aparatos, así que la
  detección automática solo lo prueba si el usuario lo permite;
- Bluetooth: puerto serie Bluetooth; las líneas se anuncian como
  «TS5 nnnn» (cuatro cifras) (petición de NVDA #14242).

En los dos casos el puerto va a 9600 baudios, 8 bits, paridad impar y un
bit de parada.

Protocolo:

- identificación: se envía ``FF FF 1C``; la línea contesta con 13 bytes de
  texto que empiezan por ``seika80`` (80 celdas) o ``seika3`` (40 celdas;
  también la dan las versiones 4 y 5). Las Seika 3 antiguas no contestan a
  eso: se les pregunta con ``FF FF 0A`` y contestan con 12 bytes que
  empiezan por ``00 05 28 08`` seguidos de ``v5.0`` o ``seika``;
- celdas: una cabecera de 8 bytes seguida de las celdas. En las líneas de
  40 celdas cada celda va precedida de un byte 0; en la de 80 van seguidas;
- teclas: paquetes de 2 bytes cuyo primer byte tiene activado alguno de los
  bits 0x20/0x40; cada paquete trae la combinación completa;
- enrutamiento: si el primer byte no tiene esos bits, es un bloque de
  ``2 + celdas / 4`` bytes con un bit por botón de enrutamiento a partir del
  octavo byte.

Nombres de teclas (gestos ``br(seika):...``): ``left`` y ``right`` (teclas
de desplazamiento), ``b1``...``b6`` (botones de función), ``routing`` y
``multiRouting``. Los bits desconocidos se llaman ``keyN``.
"""

from __future__ import annotations

import re
import time
from typing import Any

from ...i18n import _
from ...log import getLogger
from .base import DeviceMatch, DisplayNotFound, HardwareDriver

log = getLogger("braille.seika")

BAUD_RATE = 9600
#: Todas las órdenes que se envían a la línea empiezan así.
PREFIX = b"\xff\xff"
#: Petición de la versión (Seika 3, 4, 5 y Seika80).
REQUEST_VERSION = PREFIX + b"\x1c"
#: Petición de la versión de las Seika 3 antiguas.
REQUEST_LEGACY = PREFIX + b"\x0a"
#: Longitud de las respuestas de identificación.
VERSION_REPLY_LEN = 13
LEGACY_REPLY_LEN = 12
#: Inicio de la respuesta de las Seika 3 antiguas y textos que pueden seguirle.
LEGACY_PREFIX = b"\x00\x05\x28\x08"
LEGACY_MARKERS = (b"v5.0", b"seika")

#: Cabeceras de la escritura de celdas.
HEADER_40 = (PREFIX + b"seika").ljust(8, b"\x00")
HEADER_80 = (PREFIX + b"s80").ljust(8, b"\x00")
HEADER_LEGACY = PREFIX + b"\x04\x00\x63\x00\x50\x00"

#: Bits que distinguen un paquete de teclas de un bloque de enrutamiento.
KEY_PACKET_MARK = 0x60
#: Bits de las teclas en cada byte del paquete (los altos son marcas).
KEY_MASK = 0x1F
#: Primer byte con los bits de enrutamiento dentro del bloque.
ROUTING_OFFSET = 7

#: (byte, bit) del paquete de teclas -> nombre de la tecla.
KEY_BITS = {
	(0, 0x01): "left",
	(0, 0x04): "right",
	(1, 0x02): "b1",
	(1, 0x08): "b2",
	(1, 0x10): "b3",
	(0, 0x10): "b4",
	(0, 0x08): "b5",
	(0, 0x02): "b6",
}

#: Segundos que se espera cada respuesta de identificación.
IDENTIFY_TIMEOUT = 0.6
IDENTIFY_TIMEOUT_BLUETOOTH = 1.5
#: Segundos durante los que se descartan los restos de la respuesta de identificación.
SKIP_WINDOW = 0.5
#: Tamaño máximo del búfer mientras se espera la identificación.
MAX_IDENTIFY_BUFFER = 256

_VERSION_RE = re.compile(rb"seika(\d+)")


def keyNames(packet: bytes) -> set[str]:
	"""Teclas pulsadas en un paquete de teclas de 2 bytes."""
	keys = set()
	for index in range(2):
		value = packet[index] & KEY_MASK
		for bit in range(5):
			mask = 1 << bit
			if value & mask:
				keys.add(KEY_BITS.get((index, mask), f"key{index * 8 + bit}"))
	return keys


def routingIndexes(block: bytes, numCells: int) -> list[int]:
	"""Botones de enrutamiento pulsados en un bloque (índices desde 0)."""
	out = []
	data = block[ROUTING_OFFSET : ROUTING_OFFSET + numCells // 8]
	for byteIndex, value in enumerate(data):
		for bit in range(8):
			if value & (1 << bit):
				out.append(byteIndex * 8 + bit)
	return [i for i in out if i < numCells]


def routingBlockLength(numCells: int) -> int:
	return 2 + numCells // 4


def _printable(data: bytes) -> str:
	return "".join(chr(b) for b in data if 32 <= b < 127).strip()


class SeikaDriver(HardwareDriver):
	name = "seika"
	description = _("Seika 3, 4, 5 y Seika80")
	usbSerialIds = frozenset({"VID_10C4&PID_EA60"})  # Puente USB-serie CP210x
	genericUsbIds = frozenset({"VID_10C4&PID_EA60"})
	# #14242: puertos serie Bluetooth de las Seika 3/5/80 («TS5 nnnn»).
	bluetoothPrefixes = ("TS5 ",)
	baudRate = BAUD_RATE
	keyOrder = ["left", "right", "b1", "b2", "b3", "b4", "b5", "b6"]
	gestureMap = {
		"routing": "braille_routeTo",
		"multiRouting": "braille_selectRange",
		# Desplazamiento.
		"left": "braille_scrollBack",
		"right": "braille_scrollForward",
		"b3": "braille_previousLine",
		"b4": "braille_nextLine",
		"left+right": "showGui",
		# Botones de función.
		"b1": "kb:shift+tab",
		"b2": "kb:tab",
		"b5": "braille_toFocus",
		"b6": "sayAll",
		"b1+b2": "kb:alt+tab",
		"b3+b4": "braille_toggleTether",
		"b5+b6": "reportCurrentLine",
		"right+b1": "kb:escape",
		"right+b2": "kb:enter",
		"left+b3": "review_top",
		"left+b4": "review_bottom",
		"left+b5": "reportCurrentFocus",
		"right+b5": "title",
		"right+b6": "reportStatusLine",
	}
	keyDescriptions = {
		"left": _("tecla de desplazamiento izquierda"),
		"right": _("tecla de desplazamiento derecha"),
		"b1": _("botón de función 1"),
		"b2": _("botón de función 2"),
		"b3": _("botón de función 3"),
		"b4": _("botón de función 4"),
		"b5": _("botón de función 5"),
		"b6": _("botón de función 6"),
		"routing": _("botón de enrutamiento"),
		"multiRouting": _("dos botones de enrutamiento a la vez"),
	}

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		self._buffer = bytearray()
		#: ``"40"``, ``"80"`` o ``"legacy"`` (cabecera y formato de las celdas).
		self.protocol = ""
		self.firmware = ""
		self._skip = 0
		self._skipUntil = 0.0
		super().__init__(*args, **kwargs)

	@classmethod
	def _bluetoothNameMatches(cls, name: str) -> bool:
		return bool(name) and re.match(r"TS5 \d{4}", name) is not None

	# ------------------------------------------------------------ conexión
	def _connect(self, match: DeviceMatch) -> None:
		self._resetState()
		self.numCells = 0
		self._io = self._open(match, baudrate=BAUD_RATE, parity="O", stopBits=1)
		timeout = IDENTIFY_TIMEOUT_BLUETOOTH if match.bluetooth else IDENTIFY_TIMEOUT
		for request in (REQUEST_VERSION, REQUEST_LEGACY):
			with self._cond:
				self._buffer.clear()
			self._write(request)
			self._waitFor(lambda: self.numCells > 0 or self._identityComplete(), timeout)
			with self._cond:
				if self.numCells <= 0:
					# Lo que haya llegado, aunque la respuesta esté incompleta.
					self._identify(final=True)
			if self.numCells > 0:
				break
		if self.numCells <= 0:
			raise DisplayNotFound("La línea Seika no ha respondido")

	def _initConnection(self, match: DeviceMatch) -> None:
		# Conexiones ya abiertas (pruebas): solo se pide la versión.
		self._write(REQUEST_VERSION)

	def _resetState(self) -> None:
		self._buffer.clear()
		self._skip = 0

	# ------------------------------------------------------------ identificación
	def _identityComplete(self) -> bool:
		buf = self._buffer
		pos = buf.find(b"seika")
		if pos >= 0 and len(buf) - pos >= VERSION_REPLY_LEN:
			return True
		pos = buf.find(LEGACY_PREFIX)
		return pos >= 0 and len(buf) - pos >= LEGACY_REPLY_LEN

	def _identify(self, final: bool = False) -> None:
		"""Interpreta la respuesta de identificación que haya en el búfer."""
		buf = self._buffer
		pos = buf.find(LEGACY_PREFIX)
		if pos >= 0:
			rest = bytes(buf[pos + len(LEGACY_PREFIX) : pos + LEGACY_REPLY_LEN])
			if any(rest.startswith(m) for m in LEGACY_MARKERS):
				self._consumeIdentity(pos, LEGACY_REPLY_LEN)
				self.firmware = _printable(rest)
				self._setModel("legacy", 40)
				return
		pos = buf.find(b"seika")
		if pos < 0:
			return
		reply = bytes(buf[pos : pos + VERSION_REPLY_LEN])
		m = _VERSION_RE.match(reply)
		if m is None or (len(reply) < VERSION_REPLY_LEN and not final):
			return
		version = m.group(1)
		if version.startswith(b"80"):
			protocol, cells = "80", 80
		elif version[:1] in (b"3", b"4", b"5", b"6"):
			protocol, cells = "40", 40
		else:
			log.debug("Versión de Seika desconocida: %r", reply)
			return
		self._consumeIdentity(pos, VERSION_REPLY_LEN)
		self.firmware = _printable(reply)
		self._setModel(protocol, cells)

	def _consumeIdentity(self, pos: int, length: int) -> None:
		available = len(self._buffer) - pos
		taken = min(length, available)
		del self._buffer[: pos + taken]
		# Si la respuesta llega a trozos, el resto se descarta al llegar.
		self._skip = length - taken
		self._skipUntil = time.monotonic() + SKIP_WINDOW

	def _setModel(self, protocol: str, cells: int) -> None:
		self.protocol = protocol
		self.model = f"Seika{cells}"
		if protocol == "80":
			self.deviceName = "Seika80"
		elif protocol == "legacy":
			self.deviceName = _("Seika 3 (modelo antiguo)")
		else:
			self.deviceName = _("Seika de 40 celdas")
		log.debug("Seika: respuesta %r, %d celdas", self.firmware, cells)
		self.numCells = cells

	# ------------------------------------------------------------ entrada
	def _handleData(self, data: bytes) -> None:
		buf = self._buffer
		buf.extend(data)
		if self.numCells <= 0:
			if self._identityComplete():
				self._identify()
			if self.numCells <= 0:
				if len(buf) > MAX_IDENTIFY_BUFFER:
					del buf[:-MAX_IDENTIFY_BUFFER]
				return
		if self._skip:
			if time.monotonic() < self._skipUntil:
				count = min(self._skip, len(buf))
				del buf[:count]
				self._skip -= count
			else:
				self._skip = 0
		while buf:
			if buf[0] & KEY_PACKET_MARK:
				if len(buf) < 2:
					return
				packet = bytes(buf[:2])
				del buf[:2]
				keys = keyNames(packet)
				if keys:
					# Cada paquete trae la combinación completa.
					self._fireChord(keys)
			else:
				length = routingBlockLength(self.numCells)
				if len(buf) < length:
					return
				block = bytes(buf[:length])
				del buf[:length]
				indexes = routingIndexes(block, self.numCells)
				if indexes:
					self._fireChord({("routing", i) for i in indexes})

	# ------------------------------------------------------------ salida
	def _writeCells(self, cells: list[int]) -> None:
		data = bytes(c & 0xFF for c in cells)
		if self.protocol == "80":
			packet = HEADER_80 + data
		else:
			header = HEADER_LEGACY if self.protocol == "legacy" else HEADER_40
			packet = header + b"".join(b"\x00" + bytes((c,)) for c in data)
		self._write(packet)


BrailleDisplayDriver = SeikaDriver
