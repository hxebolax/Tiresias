"""Líneas braille de Freedom Scientific: Focus (14, 40, 80, Blue, 5.ª
generación, y la primera generación de 44, 70 y 84 celdas) y PAC Mate.

Conexiones:

- USB con el controlador de Freedom Scientific (extremos bulk);
- puerto serie (cable serie, adaptadores USB-serie o puerto COM elegido a
  mano) y Bluetooth (puerto serie Bluetooth), a 57600 baudios sin paridad.

Protocolo (el mismo en todas las conexiones): cada paquete empieza con una
cabecera de cuatro bytes (tipo y tres argumentos). Los paquetes con el bit
alto del tipo activado llevan además una carga útil (su longitud es el
primer argumento) y una suma de control final que hace que la suma de todos
los bytes del paquete sea 0 (módulo 256). La línea confirma cada escritura
de celdas con un ACK (o un NAK si algo ha ido mal); mientras no llega la
confirmación, las celdas nuevas se guardan y se envían al llegar.

Nombres de teclas (gestos ``br(freedomScientific):...``):

- teclado braille: ``dot1``...``dot8`` y ``brailleSpaceBar``;
- ``leftAdvanceBar``/``rightAdvanceBar`` (botones de avance),
  ``leftRockerBarUp``/``Down`` y ``rightRockerBarUp``/``Down`` (balancines),
  ``leftBumperBarUp``/``Down`` y ``rightBumperBarUp``/``Down`` (barras de
  desplazamiento de la primera generación), ``leftShiftKey``/``rightShiftKey``
  (selectores), ``leftGDFButton``/``rightGDFButton``,
  ``leftWizWheelPress``/``rightWizWheelPress`` (pulsar las ruedas);
- ruedas (gestos sin soltar): ``leftWizWheelUp``/``Down`` y
  ``rightWizWheelUp``/``Down``;
- enrutamiento: ``routing``/``multiRouting`` y, en las líneas con una
  segunda fila de botones, ``routing2``/``multiRouting2``.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any

from ...i18n import _
from ...log import getLogger
from . import hwio
from .base import DeviceMatch, DisplayNotFound, HardwareDriver

log = getLogger("braille.freedomScientific")

# ------------------------------------------------------------------ tipos de paquete
#: Petición de identificación (fabricante, modelo y firmware).
PKT_QUERY = 0x00
#: Confirmación de la línea.
PKT_ACK = 0x01
#: Rechazo de la línea (el primer argumento es el código de error).
PKT_NAK = 0x02
#: Estado de las teclas (24 bits en los tres argumentos).
PKT_KEY = 0x03
#: Botón de enrutamiento pulsado o soltado.
PKT_BUTTON = 0x04
#: Giro de una rueda.
PKT_WHEEL = 0x05
#: Configuración (activar las teclas extendidas).
PKT_CONFIG = 0x0F
#: Respuesta a la identificación.
PKT_INFO = 0x80
#: Escritura de celdas.
PKT_WRITE = 0x81
#: Estado de las teclas extendidas (balancines).
PKT_EXT_KEY = 0x82

#: Parámetro de ``PKT_CONFIG``: enviar las teclas extendidas.
CFG_EXTENDED_KEYS = 0x02

#: Tipos de paquete que puede enviar la línea.
_INCOMING_TYPES = frozenset({PKT_ACK, PKT_NAK, PKT_KEY, PKT_BUTTON, PKT_WHEEL, PKT_INFO, PKT_EXT_KEY})

#: Campos de la respuesta de identificación: (inicio, fin).
INFO_MANUFACTURER = (0, 24)
INFO_MODEL = (24, 40)
INFO_FIRMWARE = (40, 48)

BAUD_RATE = 57600
#: Extremos USB bulk del controlador de Freedom Scientific y tamaño de lectura.
USB_EP_IN = 1
USB_EP_OUT = 0
USB_READ_SIZE = 56

#: Segundos que se espera la confirmación de una escritura antes de enviar
#: igualmente las celdas pendientes.
ACK_TIMEOUT = 0.5

#: Modelos conocidos (nombre en minúsculas) -> celdas.
KNOWN_MODELS = {
	"focus 14": 14,
	"focus 40": 40,
	"focus 44": 44,
	"focus 70": 70,
	"focus 80": 80,
	"focus 84": 84,
	"pm display 20": 20,
	"pm display 40": 40,
}

#: Las Focus de primera generación (44, 70 y 84 celdas, con celdas de estado)
#: ordenan los puntos de cada celda de otra manera.
FIRST_GENERATION_CELLS = frozenset({44, 70, 84})

#: Bit de cada punto (1 a 8) en las celdas de la primera generación.
_FIRST_GENERATION_DOT_BITS = (0x01, 0x02, 0x04, 0x10, 0x20, 0x40, 0x08, 0x80)


def _buildDotTable(dotBits: tuple[int, ...]) -> bytes:
	"""Tabla de 256 entradas: celda estándar (bit n = punto n+1) -> byte de la línea."""
	table = bytearray(256)
	for cell in range(256):
		out = 0
		for dot, bit in enumerate(dotBits):
			if cell & (1 << dot):
				out |= bit
		table[cell] = out
	return bytes(table)


FIRST_GENERATION_TABLE = _buildDotTable(_FIRST_GENERATION_DOT_BITS)

#: Bits del paquete de teclas (argumento 1 = bits 0-7, 2 = 8-15, 3 = 16-23).
KEY_BITS = {
	0: "dot1",
	1: "dot2",
	2: "dot3",
	3: "dot4",
	4: "dot5",
	5: "dot6",
	6: "dot7",
	7: "dot8",
	8: "leftWizWheelPress",
	9: "rightWizWheelPress",
	10: "leftShiftKey",
	11: "rightShiftKey",
	12: "leftAdvanceBar",
	13: "rightAdvanceBar",
	15: "brailleSpaceBar",
	16: "leftGDFButton",
	17: "rightGDFButton",
	20: "leftBumperBarUp",
	21: "leftBumperBarDown",
	22: "rightBumperBarUp",
	23: "rightBumperBarDown",
}

#: Bits de las teclas extendidas (los cuatro bits altos del primer byte).
EXT_KEY_BITS = {
	0: "leftRockerBarUp",
	1: "leftRockerBarDown",
	2: "rightRockerBarUp",
	3: "rightRockerBarDown",
}

#: Código de rueda del paquete de giro -> nombre del gesto.
WHEEL_NAMES = {
	0: "leftWizWheelUp",
	1: "leftWizWheelDown",
	2: "rightWizWheelDown",
	3: "rightWizWheelUp",
}

_MAIN_KEY_NAMES = frozenset(KEY_BITS.values())
_EXT_KEY_NAMES = frozenset(EXT_KEY_BITS.values())


def keyNameForBit(bit: int) -> str:
	"""Nombre de la tecla de un bit del paquete de teclas (genérico si no se conoce)."""
	return KEY_BITS.get(bit, f"key{bit}")


def cellsForModel(model: str) -> int:
	"""Celdas de un modelo a partir del nombre que da la línea (0 si no se sabe)."""
	norm = " ".join(model.lower().split())
	if norm in KNOWN_MODELS:
		return KNOWN_MODELS[norm]
	# Variantes con sufijos («Focus 40 Blue», «Focus 14 BT»...): el número del nombre.
	if norm.startswith(("focus", "pm display", "pac mate", "pacmate")):
		m = re.search(r"(\d+)", norm)
		if m and 12 <= int(m.group(1)) <= 88:
			return int(m.group(1))
	return 0


def checksum(data: bytes) -> int:
	"""Byte que hace que la suma de ``data`` más él sea 0 (módulo 256)."""
	return (-sum(data)) & 0xFF


def buildPacket(ptype: int, arg1: int = 0, arg2: int = 0, arg3: int = 0, data: bytes = b"") -> bytes:
	"""Paquete para la línea: cabecera y, si hay datos, datos y suma de control."""
	packet = bytes((ptype & 0xFF, arg1 & 0xFF, arg2 & 0xFF, arg3 & 0xFF)) + bytes(data)
	if data:
		packet += bytes((checksum(packet),))
	return packet


def _field(payload: bytes, span: tuple[int, int]) -> str:
	return payload[span[0] : span[1]].replace(b"\x00", b"").decode("latin-1", "replace").strip()


class FreedomScientificDriver(HardwareDriver):
	name = "freedomScientific"
	description = _("Freedom Scientific Focus y PAC Mate")
	usbBulkIds = frozenset(
		{
			"VID_0F4E&PID_0100",  # Focus de primera generación
			"VID_0F4E&PID_0111",  # PAC Mate
			"VID_0F4E&PID_0112",  # Focus de segunda generación
			"VID_0F4E&PID_0114",  # Focus Blue y posteriores
		}
	)
	bluetoothPrefixes = ("F14", "Focus 14 BT", "Focus 40 BT", "Focus 80 BT")
	baudRate = BAUD_RATE
	keyOrder = [
		"leftShiftKey",
		"rightShiftKey",
		"leftGDFButton",
		"rightGDFButton",
		"leftWizWheelPress",
		"rightWizWheelPress",
		"leftAdvanceBar",
		"rightAdvanceBar",
		"leftRockerBarUp",
		"leftRockerBarDown",
		"rightRockerBarUp",
		"rightRockerBarDown",
		"leftBumperBarUp",
		"leftBumperBarDown",
		"rightBumperBarUp",
		"rightBumperBarDown",
		"dot1",
		"dot2",
		"dot3",
		"dot4",
		"dot5",
		"dot6",
		"dot7",
		"dot8",
		"brailleSpaceBar",
	]
	dotKeys = {f"dot{i}": i for i in range(1, 9)}
	spaceKeys = frozenset({"brailleSpaceBar"})
	gestureMap = {
		# Enrutamiento.
		"routing": "braille_routeTo",
		"multiRouting": "braille_selectRange",
		"routing2": "braille_reportFormatting",
		"leftShiftKey+routing": "braille_reportFormatting",
		# Desplazamiento de la línea.
		"leftAdvanceBar": "braille_scrollBack",
		"rightAdvanceBar": "braille_scrollForward",
		"leftBumperBarUp": "braille_scrollBack",
		"rightBumperBarUp": "braille_scrollBack",
		"leftBumperBarDown": "braille_scrollForward",
		"rightBumperBarDown": "braille_scrollForward",
		"leftRockerBarUp": "braille_previousLine",
		"rightRockerBarUp": "braille_previousLine",
		"leftRockerBarDown": "braille_nextLine",
		"rightRockerBarDown": "braille_nextLine",
		# Ruedas: la izquierda cambia de línea y la derecha desplaza.
		"leftWizWheelUp": "braille_previousLine",
		"leftWizWheelDown": "braille_nextLine",
		"rightWizWheelUp": "braille_scrollBack",
		"rightWizWheelDown": "braille_scrollForward",
		"leftWizWheelPress": "braille_toFocus",
		"rightWizWheelPress": "reportCurrentLine",
		# Selectores y botones GDF.
		"leftShiftKey": "kb:shift+tab",
		"rightShiftKey": "kb:tab",
		"leftShiftKey+leftAdvanceBar": "review_top",
		"rightShiftKey+rightAdvanceBar": "review_bottom",
		"leftGDFButton": "braille_toFocus",
		"rightGDFButton": "reportCurrentFocus",
		"leftGDFButton+rightGDFButton": "braille_toggleTether",
		# Espacio y puntos.
		"brailleSpaceBar+dot1": "kb:upArrow",
		"brailleSpaceBar+dot4": "kb:downArrow",
		"brailleSpaceBar+dot3": "kb:leftArrow",
		"brailleSpaceBar+dot6": "kb:rightArrow",
		"brailleSpaceBar+dot2": "kb:control+leftArrow",
		"brailleSpaceBar+dot5": "kb:control+rightArrow",
		"brailleSpaceBar+dot1+dot2": "kb:home",
		"brailleSpaceBar+dot4+dot5": "kb:end",
		"brailleSpaceBar+dot1+dot2+dot3": "kb:control+home",
		"brailleSpaceBar+dot4+dot5+dot6": "kb:control+end",
		"brailleSpaceBar+dot1+dot3": "kb:shift+tab",
		"brailleSpaceBar+dot4+dot6": "kb:tab",
		"brailleSpaceBar+dot1+dot5": "kb:escape",
		"brailleSpaceBar+dot1+dot3+dot4": "kb:alt",
		"brailleSpaceBar+dot3+dot4": "kb:windows",
		"brailleSpaceBar+dot1+dot4+dot5": "kb:windows+d",
		"brailleSpaceBar+dot2+dot3+dot4+dot5": "kb:alt+tab",
		"brailleSpaceBar+dot1+dot4": "reportCurrentLine",
		"brailleSpaceBar+dot1+dot3+dot4+dot5": "showGui",
		"brailleSpaceBar+dot1+dot2+dot3+dot4+dot5+dot6": "sayAll",
		"brailleSpaceBar+dot7": "kb:backspace",
		"brailleSpaceBar+dot8": "kb:enter",
	}
	keyDescriptions = {
		"dot1": _("punto 1 del teclado braille"),
		"dot2": _("punto 2 del teclado braille"),
		"dot3": _("punto 3 del teclado braille"),
		"dot4": _("punto 4 del teclado braille"),
		"dot5": _("punto 5 del teclado braille"),
		"dot6": _("punto 6 del teclado braille"),
		"dot7": _("punto 7 del teclado braille"),
		"dot8": _("punto 8 del teclado braille"),
		"brailleSpaceBar": _("barra espaciadora del teclado braille"),
		"leftAdvanceBar": _("botón de avance izquierdo"),
		"rightAdvanceBar": _("botón de avance derecho"),
		"leftRockerBarUp": _("balancín izquierdo hacia arriba"),
		"leftRockerBarDown": _("balancín izquierdo hacia abajo"),
		"rightRockerBarUp": _("balancín derecho hacia arriba"),
		"rightRockerBarDown": _("balancín derecho hacia abajo"),
		"leftBumperBarUp": _("barra de desplazamiento izquierda hacia arriba (primera generación)"),
		"leftBumperBarDown": _("barra de desplazamiento izquierda hacia abajo (primera generación)"),
		"rightBumperBarUp": _("barra de desplazamiento derecha hacia arriba (primera generación)"),
		"rightBumperBarDown": _("barra de desplazamiento derecha hacia abajo (primera generación)"),
		"leftShiftKey": _("selector izquierdo"),
		"rightShiftKey": _("selector derecho"),
		"leftGDFButton": _("botón GDF izquierdo"),
		"rightGDFButton": _("botón GDF derecho"),
		"leftWizWheelPress": _("pulsar la rueda izquierda"),
		"rightWizWheelPress": _("pulsar la rueda derecha"),
		"leftWizWheelUp": _("girar la rueda izquierda hacia arriba"),
		"leftWizWheelDown": _("girar la rueda izquierda hacia abajo"),
		"rightWizWheelUp": _("girar la rueda derecha hacia arriba"),
		"rightWizWheelDown": _("girar la rueda derecha hacia abajo"),
		"routing": _("botón de enrutamiento"),
		"multiRouting": _("dos botones de enrutamiento a la vez"),
		"routing2": _("botón de la segunda fila de enrutamiento"),
		"multiRouting2": _("dos botones de la segunda fila de enrutamiento a la vez"),
	}

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		self._buffer = bytearray()
		self._down: set = set()
		self._awaitingAck = False
		self._ackDeadline = 0.0
		self._pendingPacket: bytes | None = None
		self._ackTimer: threading.Timer | None = None
		self._dotTable: bytes | None = None
		self.manufacturer = ""
		self.modelName = ""
		self.firmware = ""
		super().__init__(*args, **kwargs)

	# ------------------------------------------------------------ conexión
	def _connect(self, match: DeviceMatch) -> None:
		self._resetState()
		self.numCells = 0
		if match.type == "bulk":
			self._io = self._open(match, epIn=USB_EP_IN, epOut=USB_EP_OUT, readSize=USB_READ_SIZE)
		else:
			self._io = self._open(match, baudrate=BAUD_RATE, parity="N")
		# Se pregunta dos veces por si la primera petición se pierde
		# (p. ej. al despertar una conexión Bluetooth).
		for _attempt in range(2):
			self._sendPacket(PKT_QUERY)
			if self._waitFor(lambda: self.numCells > 0, 1.0):
				break
		if self.numCells <= 0:
			raise DisplayNotFound("La línea Freedom Scientific no ha respondido")
		self._configureDisplay()

	def _initConnection(self, match: DeviceMatch) -> None:
		# Conexiones ya abiertas (pruebas): solo se pide la identificación.
		self._sendPacket(PKT_QUERY)

	def _configureDisplay(self) -> None:
		"""Activa las teclas extendidas (balancines) en las Focus con firmware 3 o posterior."""
		if self.modelName.lower().startswith("focus") and self.firmware[:1].isdigit() and int(self.firmware[:1]) >= 3:
			self._sendPacket(PKT_CONFIG, CFG_EXTENDED_KEYS)

	def _sendPacket(self, ptype: int, arg1: int = 0, arg2: int = 0, arg3: int = 0, data: bytes = b"") -> None:
		self._write(buildPacket(ptype, arg1, arg2, arg3, data))

	def _resetState(self) -> None:
		self._buffer.clear()
		self._down = set()
		self._awaitingAck = False
		self._pendingPacket = None
		self._cancelAckTimer()

	# ------------------------------------------------------------ entrada
	def _handleData(self, data: bytes) -> None:
		buf = self._buffer
		buf.extend(data)
		while len(buf) >= 4:
			ptype = buf[0]
			if ptype not in _INCOMING_TYPES:
				# Byte suelto o basura: se descarta para volver a sincronizar.
				del buf[0]
				continue
			if ptype & 0x80:
				length = 4 + buf[1] + 1
				if len(buf) < length:
					return
				packet = bytes(buf[:length])
				if sum(packet) & 0xFF:
					log.debug("Suma de control incorrecta en el paquete %r", packet)
					del buf[0]
					continue
				del buf[:length]
				self._handlePacket(ptype, packet[1], packet[2], packet[3], packet[4:-1])
			else:
				packet = bytes(buf[:4])
				del buf[:4]
				self._handlePacket(ptype, packet[1], packet[2], packet[3], b"")

	def _handlePacket(self, ptype: int, arg1: int, arg2: int, arg3: int, payload: bytes) -> None:
		if ptype == PKT_ACK:
			self._handleAck()
		elif ptype == PKT_NAK:
			log.debug("La línea ha rechazado un paquete (código %d)", arg1)
			self._handleAck()
		elif ptype == PKT_INFO:
			self._handleInfo(payload)
		elif ptype == PKT_KEY:
			bits = arg1 | (arg2 << 8) | (arg3 << 16)
			keys = {keyNameForBit(b) for b in range(24) if bits & (1 << b)}
			self._updateKeys(keys, lambda k: isinstance(k, str) and (k in _MAIN_KEY_NAMES or k.startswith("key")))
		elif ptype == PKT_EXT_KEY:
			bits = (payload[0] >> 4) if payload else 0
			keys = {name for b, name in EXT_KEY_BITS.items() if bits & (1 << b)}
			self._updateKeys(keys, lambda k: k in _EXT_KEY_NAMES)
		elif ptype == PKT_BUTTON:
			key = ("routing2" if arg3 else "routing", arg1)
			down = set(self._down)
			if arg2 & 0x01:
				down.add(key)
			else:
				down.discard(key)
			self._setDown(down)
		elif ptype == PKT_WHEEL:
			count = arg1 & 0x07
			name = WHEEL_NAMES.get((arg1 >> 3) & 0x07)
			if name is None:
				log.debug("Rueda desconocida en %#x", arg1)
				return
			for _i in range(count):
				self._fireChord({name})

	def _updateKeys(self, keys: set, belongs) -> None:
		"""Sustituye el estado de un grupo de teclas y conserva el de los demás."""
		down = {k for k in self._down if not belongs(k)} | keys
		self._setDown(down)

	def _setDown(self, down: set) -> None:
		self._down = down
		self._keysChanged(down)

	def _handleInfo(self, payload: bytes) -> None:
		self.manufacturer = _field(payload, INFO_MANUFACTURER)
		self.modelName = _field(payload, INFO_MODEL)
		self.firmware = _field(payload, INFO_FIRMWARE)
		cells = cellsForModel(self.modelName)
		if cells <= 0:
			log.debug("Modelo Freedom Scientific desconocido: %r", self.modelName)
			return
		self._dotTable = FIRST_GENERATION_TABLE if cells in FIRST_GENERATION_CELLS else None
		self.model = "".join(ch for ch in self.modelName if ch.isalnum())
		if self.modelName.lower().startswith("pm display"):
			name = _("PAC Mate de {cells} celdas").format(cells=cells)
		else:
			name = self.modelName
			if self._dotTable is not None:
				name = _("{model} (primera generación)").format(model=name)
		if self.manufacturer and self.manufacturer.lower() not in name.lower():
			name = f"{self.manufacturer} {name}"
		self.deviceName = name
		log.debug("Freedom Scientific: fabricante %r, modelo %r, firmware %r", self.manufacturer, self.modelName, self.firmware)
		self.numCells = cells

	# ------------------------------------------------------------ salida
	def _writeCells(self, cells: list[int]) -> None:
		data = bytes(c & 0xFF for c in cells)
		if self._dotTable is not None:
			data = data.translate(self._dotTable)
		packet = buildPacket(PKT_WRITE, self.numCells, 0, 0, data)
		with self._cond:
			if self._awaitingAck and time.monotonic() < self._ackDeadline:
				# La línea aún no ha confirmado la escritura anterior.
				self._pendingPacket = packet
				self._startAckTimer()
				return
			self._sendCells(packet)

	def _sendCells(self, packet: bytes) -> None:
		self._pendingPacket = None
		self._awaitingAck = True
		self._ackDeadline = time.monotonic() + ACK_TIMEOUT
		self._write(packet)

	def _handleAck(self) -> None:
		with self._cond:
			self._awaitingAck = False
			packet = self._pendingPacket
			if packet is not None:
				self._cancelAckTimer()
				try:
					self._sendCells(packet)
				except hwio.IoError as e:
					log.debug("Error escribiendo en la línea braille: %s", e)

	def _startAckTimer(self) -> None:
		if self._ackTimer is not None:
			return
		delay = max(0.0, self._ackDeadline - time.monotonic())
		timer = threading.Timer(delay, self._onAckTimeout)
		timer.daemon = True
		self._ackTimer = timer
		timer.start()

	def _cancelAckTimer(self) -> None:
		timer = self._ackTimer
		self._ackTimer = None
		if timer is not None:
			timer.cancel()

	def _onAckTimeout(self) -> None:
		"""La confirmación no ha llegado a tiempo: se envían las celdas pendientes."""
		with self._cond:
			self._ackTimer = None
			if self._terminated or self._io is None or self._pendingPacket is None:
				return
			log.debug("La línea no ha confirmado la escritura; se envían las celdas pendientes")
			try:
				self._sendCells(self._pendingPacket)
			except hwio.IoError as e:
				log.debug("Error escribiendo en la línea braille: %s", e)

	def _sayGoodbye(self) -> None:
		# Al cerrar no se espera la confirmación: se envía lo que quede pendiente.
		with self._cond:
			self._cancelAckTimer()
			if self._pendingPacket is not None:
				self._sendCells(self._pendingPacket)

	def terminate(self) -> None:
		try:
			super().terminate()
		finally:
			self._cancelAckTimer()


BrailleDisplayDriver = FreedomScientificDriver
