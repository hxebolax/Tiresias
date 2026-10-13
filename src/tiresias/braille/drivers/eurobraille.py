"""Líneas braille Eurobraille: Esys, Esytime, Iris, b.book y b.note.

Protocolo de Eurobraille (resumen de lo que usa este controlador):

- Cada paquete es ``STX`` (0x02), una longitud de 2 bytes en orden big
  endian, el tipo (una letra ASCII), el subtipo, los datos y ``ETX`` (0x03).
  La longitud cuenta los dos bytes de la propia longitud, el tipo, el subtipo
  y los datos (no cuenta ``STX`` ni ``ETX``).
- Por USB HID el flujo de bytes va dentro de informes HID: el byte 0 es el
  identificador de informe (0) y el resto, un trozo del flujo. Los paquetes
  que no caben en un informe se reparten en varios; el último se rellena con
  0x55.
- Por USB serie (b.book, b.note) y Bluetooth (Esys) el flujo va tal cual a
  9600 baudios, 8 bits, paridad par y 1 bit de parada.
- Con la versión 3 o posterior del protocolo por HID, cada paquete que se
  envía lleva un número de trama (0x20-0x7F) justo antes de ``ETX`` (la
  longitud no lo cuenta) y la línea confirma con ``ACK`` (0x06) + número. El
  controlador no envía otra imagen de la línea hasta recibir la confirmación
  de la anterior (o pasado un tiempo prudencial).

Paquetes principales:

- ``S I``: petición de identificación. La línea contesta con varios paquetes
  ``S``: ``T`` (tipo de aparato), ``G`` (número de celdas), ``P`` (versión
  del protocolo), ``M`` (longitud máxima de trama)... y termina con ``S I``.
- ``B S`` + celdas: escribe la línea (bit 0 = punto 1 ... bit 7 = punto 8).
- ``K B``: teclado braille (bits 0-7 puntos, bit 8 retroceso, bit 9 espacio).
- ``K I``: teclas interactivas (enrutamiento): tipo de pulsación (1 simple,
  2 repetición, 3 doble) y celda (desde 1).
- ``K C``: teclas de órdenes (máscara de bits; en Esys, Esytime, b.book y
  b.note se envía el estado completo en cada cambio; en Iris, una vez por
  combinación).
- ``K U``: modo teclado HID activado (``1``) o no (``0``).
- ``T L``: «ping» de las Iris cada dos segundos; hay que devolverlo igual.
- ``R P`` / ``R I``: la línea vuelve al modo controlador / pasa a su menú.

Nombres de teclas (gestos ``br(eurobraille):...``): ``dot1``...``dot8``,
``space``, ``backSpace``, ``routing`` y ``doubleRouting`` (doble pulsación
de una tecla interactiva), ``switch1Left``...``switch6Right`` (conmutadores
de las Esys y b.note), ``l1``...``l8`` (Esytime, b.book e Iris),
``upArrow``/``downArrow``/``leftArrow``/``rightArrow`` (Iris) y
``joystick1Up``...``joystick2Center`` (joysticks izquierdo y derecho).
El teclado de PC de b.book, b.note e Iris KB escribe los caracteres y
produce gestos ``pc_<modificador>+pc_<tecla>`` (p. ej. ``pc_control+pc_c``,
``pc_f5``) que emulan esa tecla salvo que se les asigne otra orden.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any, Iterable

from ... import queue_handler
from ...baseobject import script
from ...i18n import _
from ...log import getLogger
from .base import BrailleGesture, DeviceMatch, DisplayNotFound, HardwareDriver, buildGesture

log = getLogger("braille.eurobraille")

STX = 0x02
ETX = 0x03
ACK = 0x06

# Tipos de paquete.
PKT_SYSTEM = b"S"
PKT_MODE = b"R"
PKT_KEY = b"K"
PKT_DISPLAY = b"B"
PKT_TEST = b"T"
PKT_VISUALISATION = b"V"
PKT_ENCRYPTION = b"Z"

# Subtipos de los paquetes de sistema.
SYS_IDENTITY = b"I"
SYS_CELLS = b"G"
SYS_TYPE = b"T"
SYS_PROTOCOL = b"P"
SYS_FRAME_LENGTH = b"M"
SYS_CONNECTION_NAME = b"n"

# Subtipos de los paquetes de teclas.
KEY_BRAILLE = b"B"
KEY_INTERACTIVE = b"I"
KEY_COMMAND = b"C"
KEY_PC_KEYBOARD = b"Z"
KEY_HID_MODE = b"U"

# Tipos de pulsación de las teclas interactivas.
CLICK_SINGLE = 1
CLICK_REPEAT = 2
CLICK_DOUBLE = 3

#: Longitud máxima razonable de un paquete (para descartar basura).
MAX_PACKET_LENGTH = 1024

# Familias de aparatos.
FAMILY_IRIS = "Iris"
FAMILY_ESYS = "Esys"
FAMILY_ESYTIME = "Esytime"
FAMILY_BNOTE = "bnote"
FAMILY_BBOOK = "bbook"

#: Código de tipo (paquete ``S T``) -> (nombre legible, familia).
DEVICE_TYPES: dict[int, tuple[str, str]] = {
	0x01: ("Iris 20", FAMILY_IRIS),
	0x02: ("Iris 40", FAMILY_IRIS),
	0x03: ("Iris S-20", FAMILY_IRIS),
	0x04: ("Iris S-32", FAMILY_IRIS),
	0x05: ("Iris KB-20", FAMILY_IRIS),
	0x06: ("Iris KB-40", FAMILY_IRIS),
	0x07: ("Esys 12", FAMILY_ESYS),
	0x08: ("Esys 40", FAMILY_ESYS),
	0x09: ("Esys Light 40", FAMILY_ESYS),
	0x0A: ("Esys 24", FAMILY_ESYS),
	0x0B: ("Esys 64", FAMILY_ESYS),
	0x0C: ("Esys 80", FAMILY_ESYS),
	0x0D: ("Esys", FAMILY_ESYS),
	0x0E: ("Esytime 32", FAMILY_ESYTIME),
	0x0F: ("Esytime 32 Standard", FAMILY_ESYTIME),
	0x10: ("Esytime Evo 32", FAMILY_ESYTIME),
	0x11: ("Esytime Evo 32 Standard", FAMILY_ESYTIME),
	0x12: ("b.note", FAMILY_BNOTE),
	0x13: ("b.note 2", FAMILY_BNOTE),
	0x14: ("b.book", FAMILY_BBOOK),
	0x15: ("b.book 2", FAMILY_BBOOK),
}


def _bitNames(*groups: dict[int, str]) -> dict[int, str]:
	out: dict[int, str] = {}
	for g in groups:
		out.update(g)
	return out


#: Joysticks izquierdo (1) y derecho (2): bits 16-20 y 24-28.
_JOYSTICKS: dict[int, str] = {}
for _n, _base in ((1, 16), (2, 24)):
	for _off, _dir in enumerate(("Up", "Down", "Right", "Left", "Center")):
		_JOYSTICKS[_base + _off] = f"joystick{_n}{_dir}"
#: Conmutadores de las Esys y b.note: cada uno ocupa dos bits (derecha, izquierda).
_SWITCHES: dict[int, str] = {}
for _n in range(6):
	_SWITCHES[2 * _n] = f"switch{_n + 1}Right"
	_SWITCHES[2 * _n + 1] = f"switch{_n + 1}Left"
#: Teclas de función L1-L8 (Esytime, b.book, Iris).
_LKEYS = {i: f"l{i + 1}" for i in range(8)}
#: Flechas de las Iris.
_IRIS_ARROWS = {8: "upArrow", 9: "downArrow", 10: "rightArrow", 11: "leftArrow"}

#: Familia -> nº de bit de las teclas de órdenes -> nombre.
COMMAND_KEYS: dict[str, dict[int, str]] = {
	FAMILY_ESYS: _bitNames(_SWITCHES, _JOYSTICKS),
	FAMILY_BNOTE: _bitNames(_SWITCHES, _JOYSTICKS),
	FAMILY_ESYTIME: _bitNames(_LKEYS, _JOYSTICKS),
	FAMILY_BBOOK: _bitNames(_LKEYS, _JOYSTICKS),
	FAMILY_IRIS: _bitNames(_LKEYS, _IRIS_ARROWS),
}

#: Bits del teclado braille (además de los puntos, bits 0-7).
_BRAILLE_EXTRA = {8: "backSpace", 9: "space"}

#: Teclado de PC de b.book, b.note e Iris KB (paquete ``K Z``).
#:
#: NO VERIFICADO CON HARDWARE: es la interpretación más probable del formato.
#: Los datos traen (al final) tres bytes: modificadores, código de tecla
#: especial y carácter. Si el código especial es 0, la tecla es el carácter
#: (ya con Mayúsculas o AltGr aplicados, en Windows-1252); si no, el código
#: especial indica la tecla y se interpreta como código de tecla virtual de
#: Windows (F1 = 0x70, flechas 0x25-0x28...). Los bits de los modificadores
#: también son una suposición; están en esta tabla para corregirlos fácilmente.
PC_MODIFIERS = ((0x01, "shift"), (0x02, "control"), (0x04, "alt"), (0x08, "windows"), (0x10, "altGr"))
#: Código de tecla especial -> nombre de tecla de Tiresias (para ``kb:``).
PC_SPECIAL_KEYS: dict[int, str] = {
	0x08: "backspace",
	0x09: "tab",
	0x0D: "enter",
	0x13: "pause",
	0x14: "capsLock",
	0x1B: "escape",
	0x20: "space",
	0x21: "pageUp",
	0x22: "pageDown",
	0x23: "end",
	0x24: "home",
	0x25: "leftArrow",
	0x26: "upArrow",
	0x27: "rightArrow",
	0x28: "downArrow",
	0x2C: "printScreen",
	0x2D: "insert",
	0x2E: "delete",
	0x5B: "windows",
	0x5C: "windows",
	0x5D: "applications",
	0x90: "numLock",
	0x91: "scrollLock",
}
for _i in range(12):
	PC_SPECIAL_KEYS[0x70 + _i] = f"f{_i + 1}"
#: Modificadores que convierten un carácter en atajo (en vez de escribirlo).
_PC_SHORTCUT_MODIFIERS = frozenset({"control", "alt", "windows"})

#: Gestos por defecto de la orden del controlador que activa o desactiva el modo teclado HID.
HID_KEYBOARD_TOGGLE_GESTURES = (
	"br(eurobraille):switch1Left+joystick1Down",
	"br(eurobraille):l1+joystick1Down",
)


def _bits(value: int) -> Iterable[int]:
	bit = 0
	while value:
		if value & 1:
			yield bit
		value >>= 1
		bit += 1


def buildPacket(ptype: bytes, subtype: bytes, data: bytes = b"", frame: int | None = None) -> bytes:
	"""Paquete completo (con ``STX``/``ETX`` y, si se indica, número de trama)."""
	body = bytes(ptype) + bytes(subtype) + bytes(data)
	out = bytearray([STX])
	out += (len(body) + 2).to_bytes(2, "big")
	out += body
	if frame is not None:
		out.append(frame & 0xFF)
	out.append(ETX)
	return bytes(out)


class EurobrailleDriver(HardwareDriver):
	name = "eurobraille"
	description = _("Eurobraille Esys, Esytime, Iris, b.book, b.note")
	usbHidIds = frozenset(
		{
			# Esys (con y sin tarjeta SD, versiones de firmware anteriores y posteriores a la 3.0).
			"VID_C251&PID_1122",
			"VID_C251&PID_1123",
			"VID_C251&PID_1124",
			"VID_C251&PID_1125",
			"VID_C251&PID_1126",
			"VID_C251&PID_1127",
			"VID_C251&PID_1128",
			"VID_C251&PID_1129",
			"VID_C251&PID_112A",
			"VID_C251&PID_112B",
			"VID_C251&PID_112C",
			"VID_C251&PID_112D",
			"VID_C251&PID_112E",
			"VID_C251&PID_112F",
			# Esytime y reservados.
			"VID_C251&PID_1130",
			"VID_C251&PID_1131",
			"VID_C251&PID_1132",
		}
	)
	usbSerialIds = frozenset(
		{
			"VID_28AC&PID_0012",  # b.note
			"VID_28AC&PID_0013",  # b.note 2
			"VID_28AC&PID_0020",  # b.book (interno)
			"VID_28AC&PID_0021",  # b.book (externo)
		}
	)
	bluetoothPrefixes = ("Esys",)
	baudRate = 9600
	#: Segundos que se espera la confirmación (ACK) de una imagen antes de enviar la siguiente.
	ackTimeout = 0.5
	#: Pausa antes de cerrar el puerto (si se cierra de golpe, la línea puede quedar sin responder).
	closeDelay = 0.2

	keyOrder = (
		[f"switch{n}{side}" for n in range(1, 7) for side in ("Left", "Right")]
		+ [f"l{i}" for i in range(1, 9)]
		+ ["upArrow", "downArrow", "leftArrow", "rightArrow"]
		+ [f"joystick{n}{d}" for n in (1, 2) for d in ("Up", "Down", "Left", "Right", "Center")]
		+ ["backSpace", "space"]
		+ [f"dot{i}" for i in range(1, 9)]
		+ ["doubleRouting"]
	)
	dotKeys = {f"dot{i}": i for i in range(1, 9)}
	spaceKeys = frozenset({"space"})
	gestureMap = {
		# Teclas interactivas (enrutamiento).
		"routing": "braille_routeTo",
		"doubleRouting": "braille_reportFormatting",
		# Conmutadores de Esys y b.note.
		"switch1Left": "braille_scrollBack",
		"switch1Right": "braille_scrollForward",
		"switch2Left": "braille_previousLine",
		"switch2Right": "braille_nextLine",
		"switch3Left": "kb:shift+tab",
		"switch3Right": "kb:tab",
		"switch4Left": "kb:pageUp",
		"switch4Right": "kb:pageDown",
		"switch5Left": "braille_scrollBack",
		"switch5Right": "braille_scrollForward",
		"switch6Left": "braille_previousLine",
		"switch6Right": "braille_nextLine",
		"switch1Left+switch1Right": "braille_toFocus",
		"switch2Left+switch2Right": "braille_toFocus",
		"switch5Left+switch5Right": "braille_toFocus",
		"switch6Left+switch6Right": "braille_toFocus",
		# Teclas L1-L8 de Esytime, b.book e Iris.
		"l1": "braille_scrollBack",
		"l8": "braille_scrollForward",
		"l2": "braille_previousLine",
		"l7": "braille_nextLine",
		"l3": "kb:shift+tab",
		"l6": "kb:tab",
		"l4": "kb:escape",
		"l5": "kb:enter",
		"l1+l8": "braille_toFocus",
		"l2+l7": "braille_toggleTether",
		# Flechas de las Iris.
		"upArrow": "kb:upArrow",
		"downArrow": "kb:downArrow",
		"leftArrow": "kb:leftArrow",
		"rightArrow": "kb:rightArrow",
		# Joystick izquierdo: cursor de revisión.
		"joystick1Up": "review_previousLine",
		"joystick1Down": "review_nextLine",
		"joystick1Left": "review_previousCharacter",
		"joystick1Right": "review_nextCharacter",
		"joystick1Center": "review_currentCharacter",
		"joystick1Left+joystick1Up": "review_top",
		"joystick1Down+joystick1Right": "review_bottom",
		# Joystick derecho: flechas del sistema.
		"joystick2Up": "kb:upArrow",
		"joystick2Down": "kb:downArrow",
		"joystick2Left": "kb:leftArrow",
		"joystick2Right": "kb:rightArrow",
		"joystick2Center": "kb:enter",
		"joystick2Left+joystick2Up": "kb:control+home",
		"joystick2Down+joystick2Right": "kb:control+end",
		# Teclado braille.
		"backSpace": "kb:backspace",
		"backSpace+space": "kb:enter",
		"space+dot1": "kb:upArrow",
		"space+dot4": "kb:downArrow",
		"space+dot3": "kb:leftArrow",
		"space+dot6": "kb:rightArrow",
		"space+dot1+dot3": "kb:shift+tab",
		"space+dot4+dot6": "kb:tab",
		"space+dot1+dot5": "kb:escape",
		"space+dot1+dot3+dot4": "kb:alt",
		"space+dot3+dot4": "kb:windows",
		"space+dot1+dot4+dot5": "kb:windows+d",
		"space+dot2+dot3+dot4+dot5": "kb:alt+tab",
		"space+dot1+dot3+dot4+dot5": "showGui",
		"space+dot1+dot2+dot3+dot4+dot5+dot6": "sayAll",
		"space+dot7": "kb:backspace",
		"space+dot8": "kb:enter",
		"space+dot1+dot2+dot3": "kb:home",
		"space+dot4+dot5+dot6": "kb:end",
		"space+dot3+dot6": "kb:delete",
		"space+dot1+dot2+dot3+dot4": "kb:applications",
		# Retroceso + letra: teclas de función (a = F1 ... l = F12).
		"backSpace+dot1": "kb:f1",
		"backSpace+dot1+dot2": "kb:f2",
		"backSpace+dot1+dot4": "kb:f3",
		"backSpace+dot1+dot4+dot5": "kb:f4",
		"backSpace+dot1+dot5": "kb:f5",
		"backSpace+dot1+dot2+dot4": "kb:f6",
		"backSpace+dot1+dot2+dot4+dot5": "kb:f7",
		"backSpace+dot1+dot2+dot5": "kb:f8",
		"backSpace+dot2+dot4": "kb:f9",
		"backSpace+dot2+dot4+dot5": "kb:f10",
		"backSpace+dot1+dot3": "kb:f11",
		"backSpace+dot1+dot2+dot3": "kb:f12",
	}
	keyDescriptions = {
		"dot1": _("puntos 1 a 8 del teclado braille (dot1 ... dot8)"),
		"space": _("barra espaciadora del teclado braille"),
		"backSpace": _("tecla de retroceso de las Esys y Esytime, junto al teclado braille"),
		"routing": _("tecla interactiva (encima de cada celda), pulsación simple"),
		"doubleRouting": _("tecla interactiva, doble pulsación"),
		"switch1Left": _("conmutadores de las Esys y b.note, empujados a la izquierda (switch1Left ... switch6Left)"),
		"switch1Right": _("conmutadores de las Esys y b.note, empujados a la derecha (switch1Right ... switch6Right)"),
		"l1": _("teclas de función L1 a L8 de las Esytime, b.book e Iris"),
		"upArrow": _("flechas arriba, abajo, izquierda y derecha de las Iris"),
		"joystick1Up": _("joystick izquierdo: arriba, abajo, izquierda, derecha y pulsación en el centro (joystick1...)"),
		"joystick2Up": _("joystick derecho: arriba, abajo, izquierda, derecha y pulsación en el centro (joystick2...)"),
	}

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		self._isHid = False
		self._buf = bytearray()
		self._sendLock = threading.RLock()
		self._resetProtocol()
		super().__init__(*args, **kwargs)

	def _resetProtocol(self) -> None:
		"""Estado del protocolo de una conexión (se olvida al reconectar)."""
		self._buf = bytearray()
		self.deviceType: int | None = None
		self.family = ""
		self._commandKeys = COMMAND_KEYS[FAMILY_ESYS]
		self._identityEnd = False
		#: Información de sistema recibida: subtipo (letra) -> datos.
		self.systemInfo: dict[str, bytes] = {}
		self.protocolVersion: float | None = None
		self.frameLength = 0
		self._ackMode = False
		self._frame = 0x20
		self._displayFrame: int | None = None
		self._displaySentAt = 0.0
		self._pendingCells: bytes | None = None
		self._flushTimer: int | None = None
		self._lastCells: bytes | None = None
		self._suppressCommandRelease = False
		self.hidKeyboardInput = False
		self._hidToggleWanted: bool | None = None

	# ------------------------------------------------------------ conexión
	def _connect(self, match: DeviceMatch) -> None:
		self._resetProtocol()
		self.numCells = 0
		self._isHid = match.type == "hid"
		if self._isHid:
			# Eurobraille pide no bloquear el acceso de otras aplicaciones al dispositivo.
			self._io = self._open(match, exclusive=False)
		else:
			self._io = self._open(match, baudrate=self.baudRate, parity="E", stopBits=1)
		identified = False
		for _attempt in range(3):
			self._initConnection(match)
			if self._waitFor(self._isIdentified, 1.5):
				identified = True
				break
		if not identified:
			raise DisplayNotFound("La línea Eurobraille no se ha identificado")
		if not self._identityEnd:
			# Esperar un poco al resto de la identificación (versión del protocolo).
			self._waitFor(lambda: self._identityEnd, 0.5)
		log.info("Eurobraille %s, %d celdas, protocolo %s, datos %r", self.deviceName, self.numCells, self.protocolVersion, self.systemInfo)
		if self.family in (FAMILY_BNOTE, FAMILY_BBOOK):
			# Los anotadores muestran qué lector de pantalla está conectado y en qué puerto.
			m = re.search(r"(\d+)$", match.port or "")
			number = int(m.group(1)) if m else 0
			self._sendPacket(PKT_SYSTEM, SYS_CONNECTION_NAME, f"Tiresias/{number:02d}".encode("ascii"))

	def _initConnection(self, match: DeviceMatch) -> None:
		self._isHid = match.type == "hid"
		# Petición de identificación y desactivación de los paquetes de visualización (no se usan).
		self._sendPacket(PKT_SYSTEM, SYS_IDENTITY)
		self._sendPacket(PKT_VISUALISATION, b"D", b"0")

	def _isIdentified(self) -> bool:
		return self.numCells > 0 and self.deviceType is not None

	def _resetState(self) -> None:
		self._cancelFlushTimer()
		self._resetProtocol()

	def _sayGoodbye(self) -> None:
		# La línea en blanco puede haber quedado pendiente de confirmación.
		if self._pendingCells is not None:
			self._sendCells(self._pendingCells)
		if self.family in (FAMILY_BNOTE, FAMILY_BBOOK):
			self._sendPacket(PKT_SYSTEM, SYS_CONNECTION_NAME, b"")
		self._cancelFlushTimer()
		if self.closeDelay > 0:
			time.sleep(self.closeDelay)

	# ------------------------------------------------------------ envío
	def _nextFrame(self) -> int:
		frame = self._frame
		self._frame = frame + 1 if frame < 0x7F else 0x20
		return frame

	def _sendPacket(self, ptype: bytes, subtype: bytes, data: bytes = b"") -> int | None:
		"""Envía un paquete; devuelve su número de trama (modo con confirmación) o ``None``."""
		with self._sendLock:
			frame = self._nextFrame() if self._ackMode else None
			packet = buildPacket(ptype, subtype, data, frame)
			if self._isHid:
				self._writeHid(packet)
			else:
				self._write(packet)
			return frame

	def _writeHid(self, packet: bytes) -> None:
		"""Reparte un paquete en informes HID (id 0 + trozo, rellenado con 0x55)."""
		size = int(getattr(self._io, "outputSize", 0) or 0)
		block = size - 1 if size > 1 else len(packet)
		for offset in range(0, len(packet), block):
			chunk = packet[offset : offset + block]
			self._write(b"\x00" + chunk + b"\x55" * (block - len(chunk)))

	def _writeCells(self, cells: list[int]) -> None:
		data = bytes(c & 0xFF for c in cells)
		with self._sendLock:
			self._lastCells = data
			if self._ackMode and self._displayFrame is not None and time.monotonic() - self._displaySentAt < self.ackTimeout:
				# La imagen anterior aún no está confirmada: se enviará al llegar el ACK.
				self._pendingCells = data
				if self._flushTimer is None:
					self._flushTimer = queue_handler.callLater(int(self.ackTimeout * 1000), self._flushPending)
				return
			self._sendCells(data)

	def _sendCells(self, data: bytes) -> None:
		with self._sendLock:
			self._pendingCells = None
			frame = self._sendPacket(PKT_DISPLAY, b"S", data)
			self._displayFrame = frame
			self._displaySentAt = time.monotonic()

	def _flushPending(self) -> None:
		"""Sin confirmación a tiempo: se envía la última imagen pendiente."""
		with self._sendLock:
			self._flushTimer = None
			data = self._pendingCells
			if data is None or self._io is None:
				return
			self._sendCells(data)

	def _cancelFlushTimer(self) -> None:
		timer = self._flushTimer
		self._flushTimer = None
		if timer is not None:
			queue_handler.cancelCallLater(timer)

	def _handleAck(self, frame: int) -> None:
		with self._sendLock:
			if frame != self._displayFrame:
				return
			self._displayFrame = None
			data = self._pendingCells
			if data is not None:
				self._cancelFlushTimer()
				self._sendCells(data)

	# ------------------------------------------------------------ recepción
	def _handleData(self, data: bytes) -> None:
		if not data:
			return
		if self._isHid:
			# Byte 0: identificador de informe. Si no hay un paquete a medias, empieza uno nuevo.
			payload = data[1:]
			if not (self._buf and self._buf[0] == STX):
				self._buf.clear()
			self._buf += payload
		else:
			self._buf += data
		self._parse()
		if self._isHid and self._buf and self._buf[0] != STX:
			# Relleno del final del informe.
			self._buf.clear()

	def _parse(self) -> None:
		buf = self._buf
		while buf:
			first = buf[0]
			if first == ACK:
				if len(buf) < 2:
					return
				frame = buf[1]
				del buf[:2]
				self._handleAck(frame)
				continue
			if first != STX:
				# ETX sueltos, relleno o ruido.
				del buf[0]
				continue
			if len(buf) < 3:
				return
			length = int.from_bytes(buf[1:3], "big")
			if length < 3 or length > MAX_PACKET_LENGTH:
				del buf[0]
				continue
			end = 1 + length  # posición esperada de ETX
			if len(buf) <= end:
				return
			if buf[end] == ETX:
				body = bytes(buf[3:end])
				del buf[: end + 1]
			elif len(buf) <= end + 1:
				return
			elif buf[end + 1] == ETX:
				# Paquete con número de trama.
				body = bytes(buf[3:end])
				del buf[: end + 2]
			else:
				del buf[0]
				continue
			try:
				self._handlePacket(body)
			except Exception:
				log.debug("Paquete Eurobraille no válido: %r", body, exc_info=True)

	def _handlePacket(self, body: bytes) -> None:
		ptype, subtype, data = body[0:1], body[1:2], body[2:]
		if ptype == PKT_SYSTEM:
			self._handleSystem(subtype, data)
		elif ptype == PKT_KEY:
			self._handleKeys(subtype, data)
		elif ptype == PKT_MODE:
			if subtype == b"P":
				# La línea vuelve del menú interno: hay que redibujarla.
				log.debug("Eurobraille: modo controlador")
				if self._lastCells is not None and self._io is not None:
					self._sendCells(self._lastCells)
			elif subtype == b"I":
				log.debug("Eurobraille: modo interno")
		elif ptype == PKT_TEST and subtype == b"L":
			# «Ping» de las Iris: se contesta desde el hilo del núcleo, así la línea
			# sabe si el lector se ha quedado bloqueado.
			queue_handler.queueFunction(self._answerPing, data)
		else:
			log.debug("Paquete Eurobraille ignorado: %r", body)

	def _answerPing(self, data: bytes) -> None:
		if self._io is not None:
			self._sendPacket(PKT_TEST, b"L", data)

	def _handleSystem(self, subtype: bytes, data: bytes) -> None:
		if subtype == SYS_IDENTITY:
			self._identityEnd = True
			return
		value = data.rstrip(b"\x00 ")
		try:
			self.systemInfo[subtype.decode("ascii")] = value
		except UnicodeDecodeError:
			pass
		if subtype == SYS_TYPE and data:
			self._setDeviceType(data[0])
		elif subtype == SYS_CELLS and data:
			self.numCells = data[0]
		elif subtype == SYS_FRAME_LENGTH and data:
			self.frameLength = int.from_bytes(data, "big")
		elif subtype == SYS_PROTOCOL:
			m = re.match(rb"\s*(\d+(?:\.\d+)?)", value)
			if m:
				self.protocolVersion = float(m.group(1))
				# Las tramas numeradas con confirmación solo se usan por HID.
				self._ackMode = self._isHid and self.protocolVersion >= 3.0

	def _setDeviceType(self, code: int) -> None:
		self.deviceType = code
		name, family = DEVICE_TYPES.get(code, (f"Eurobraille {code:#04x}", ""))
		self.family = family
		self.deviceName = name
		self.model = family or "".join(ch for ch in name if ch.isalnum())
		self._commandKeys = COMMAND_KEYS.get(family, COMMAND_KEYS[FAMILY_ESYS])
		if not family:
			log.debug("Tipo de línea Eurobraille desconocido: %#x", code)

	# ------------------------------------------------------------ teclas
	def _handleKeys(self, group: bytes, data: bytes) -> None:
		value = int.from_bytes(data, "big") if data else 0
		if group == KEY_BRAILLE:
			keys = set()
			for bit in _bits(value):
				if bit < 8:
					keys.add(f"dot{bit + 1}")
				else:
					keys.add(_BRAILLE_EXTRA.get(bit, f"brailleKey{bit}"))
			if keys:
				self._fireWithCommandKeys(keys)
		elif group == KEY_INTERACTIVE:
			if len(data) < 2:
				return
			kind, cell = data[0], data[1] - 1
			if kind == CLICK_REPEAT or cell < 0:
				return
			key = ("doubleRouting", cell) if kind == CLICK_DOUBLE else ("routing", cell)
			self._fireWithCommandKeys({key})
		elif group == KEY_COMMAND:
			keys = {self._commandKeys.get(bit, f"key{bit}") for bit in _bits(value)}
			if self.family == FAMILY_IRIS:
				# Las Iris envían cada combinación una sola vez.
				if keys:
					self._fireChord(keys)
				return
			self._commandKeysChanged(keys)
		elif group == KEY_HID_MODE:
			self._hidModeReported(data[:1] == b"1")
		elif group == KEY_PC_KEYBOARD:
			self._handlePcKey(data)

	# ------------------------------------------------------------ teclado de PC
	def _handlePcKey(self, data: bytes) -> None:
		"""Tecla del teclado de PC (b.book, b.note, Iris KB): se escribe o se emula.

		- Carácter sin Control, Alt ni Windows: se escribe tal cual.
		- Teclas especiales y atajos: gesto ``br(eurobraille):pc_<mod>+pc_<tecla>``
		  que emula la tecla (``kb:...``) si el usuario no le asigna otra orden.
		"""
		if len(data) < 3:
			log.debug("Paquete de teclado de PC demasiado corto: %r", data)
			return
		mods, special, char = data[-3], data[-2], data[-1]
		modNames = [name for bit, name in PC_MODIFIERS if mods & bit]
		if not special and (char < 0x20 or char == 0x7F):
			# Caracteres de control: Intro, Tab, Retroceso, Escape, Suprimir.
			special = 0x2E if char == 0x7F else char
		if special:
			key = PC_SPECIAL_KEYS.get(special)
			if key is None:
				log.debug("Tecla especial del teclado de PC desconocida: %#x", special)
				return
			self._firePcKey(modNames, key, key)
			return
		if not char:
			return
		try:
			ch = bytes([char]).decode("cp1252")
		except UnicodeDecodeError:
			ch = chr(char)
		if not (set(modNames) & _PC_SHORTCUT_MODIFIERS):
			# Mayúsculas y AltGr ya están aplicados en el carácter.
			queue_handler.queueFunction(self._typeText, ch)
			return
		if ch == " ":
			self._firePcKey(modNames, "space", "space")
		elif ch == "+":
			# «+» no se puede nombrar en un gesto de teclado: solo se ofrece para asignarlo.
			self._firePcKey(modNames, "plus", None)
		else:
			name = ch.lower() if ch.isalnum() else f"char{ord(ch)}"
			self._firePcKey(modNames, name, ch.lower())

	def _firePcKey(self, modNames: list[str], key: str, kbKey: str | None) -> None:
		gesture = BrailleGesture(self.name, [f"pc_{m}" for m in modNames] + [f"pc_{key}"], model=self.model)
		if kbKey:
			kbMods: list[str] = []
			for m in modNames:
				for part in ("control", "alt") if m == "altGr" else (m,):
					if part not in kbMods:
						kbMods.append(part)
			if kbKey == "windows" and "windows" in kbMods:
				kbMods.remove("windows")
			gesture.emulatedKey = "kb:" + "+".join(kbMods + [kbKey])
		for gid in gesture.identifiers:
			if gid in self._emulated:
				gesture.emulatedKey = self._emulated[gid]
				break
		self._dispatch(gesture)

	def _typeText(self, text: str) -> None:
		"""Hilo del núcleo: escribe el texto en la aplicación con el foco."""
		from ... import winapi

		try:
			winapi.typeText(text)
		except Exception:
			log.debug("No se pudo escribir %r", text, exc_info=True)

	def _commandKeysChanged(self, keys: set[str]) -> None:
		"""Estado completo de las teclas de órdenes (Esys, Esytime, b.book, b.note)."""
		if keys - self._keys.down:
			self._suppressCommandRelease = False
		chord = self._keys.update(keys)
		if chord and not self._suppressCommandRelease:
			self._fireChord(chord)

	def _fireWithCommandKeys(self, keys: set) -> None:
		"""Combinación enviada de una vez, junto con las teclas de órdenes que estén pulsadas."""
		held = set(self._keys.down)
		if held:
			# Al soltar después esas teclas de órdenes no hay que producir otro gesto.
			self._suppressCommandRelease = True
		self._fireChord(keys | held)

	def _makeGesture(self, chord: Iterable) -> BrailleGesture | None:
		chord = set(chord)
		double = {k for k in chord if isinstance(k, tuple) and k[0] == "doubleRouting"}
		if not double:
			return super()._makeGesture(chord)
		# Doble pulsación de una tecla interactiva: gesto «doubleRouting» con la celda.
		plain = (chord - double) | {("routing", k[1]) for k in double}
		g = buildGesture(self.name, plain, self.keyOrder, self.dotKeys, self.spaceKeys, self.model)
		if g is None:
			return None
		keys = ["doubleRouting" if k == "routing" else k for k in g.keys if k != "multiRouting"]
		if "multiRouting" in g.keys:
			keys.append("doubleRouting")
		gesture = BrailleGesture(self.name, keys, model=self.model, routingIndexes=g.routingIndexes)
		for gid in gesture.identifiers:
			if gid in self._emulated:
				gesture.emulatedKey = self._emulated[gid]
				break
		return gesture

	# ------------------------------------------------------------ modo teclado HID
	@script(
		description=_("Activa o desactiva la simulación de teclado HID de la línea Eurobraille (solo por USB: la línea escribe como un teclado USB)"),
		category=_("Braille"),
		gestures=HID_KEYBOARD_TOGGLE_GESTURES,
	)
	def script_toggleHidKeyboardInput(self, gesture) -> None:
		self.toggleHidKeyboardInput()

	def toggleHidKeyboardInput(self) -> None:
		"""Activa o desactiva el modo teclado HID (la línea escribe como un teclado USB)."""
		if not self._isHid or self._io is None:
			self._message(_("La simulación de teclado HID no está disponible con esta conexión"))
			return
		want = not self.hidKeyboardInput
		self._hidToggleWanted = want
		self._sendPacket(PKT_KEY, KEY_HID_MODE, b"1" if want else b"0")
		if self._hidToggleWanted is not None:
			queue_handler.callLater(1000, self._hidToggleTimeout, want)

	def _hidModeReported(self, state: bool) -> None:
		self.hidKeyboardInput = state
		wanted = self._hidToggleWanted
		if wanted is None:
			return
		self._hidToggleWanted = None
		if state != wanted:
			self._message(_("La simulación de teclado HID no está disponible"))
		elif state:
			self._message(_("Simulación de teclado HID activada"))
		else:
			self._message(_("Simulación de teclado HID desactivada"))

	def _hidToggleTimeout(self, wanted: bool) -> None:
		if self._hidToggleWanted is wanted:
			self._hidToggleWanted = None
			self._message(_("La simulación de teclado HID no está disponible"))

	def _message(self, text: str) -> None:
		queue_handler.queueFunction(_speak, text)


def _speak(text: str) -> None:
	from ... import speech

	try:
		speech.speakMessage(text)
	except Exception:
		log.debug("No se pudo anunciar: %s", text, exc_info=True)


BrailleDisplayDriver = EurobrailleDriver
