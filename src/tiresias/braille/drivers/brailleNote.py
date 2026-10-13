"""Anotadores HumanWare BrailleNote en modo terminal (Apex, BT, mPower, PK...).

Se conectan por un puerto serie: el COM virtual de USB (Apex), un cable
serie o Bluetooth (perfil de puerto serie). 38400 baudios, sin paridad.

Protocolo:

- El ordenador pide la descripción con ``ESC ?``; la línea contesta
  ``86 <estado> <celdas>``.
- Las celdas se envían con ``ESC B`` seguido de un byte por celda; el byte
  ``ESC`` (0x1B) dentro de las celdas se duplica.
- La línea envía un byte de etiqueta seguido de su argumento:

  - ``80 <puntos>``: puntos (bit 0 = punto 1 ... bit 7 = punto 8);
  - ``81 <puntos>``: puntos con la barra espaciadora;
  - ``82 <puntos>``: con la tecla de retroceso (equivale a espacio+punto 7);
  - ``83 <puntos>``: con la tecla Intro (equivale a espacio+punto 8);
  - ``84 <bits>``: teclas de pulgar (1 anterior, 2 atrás, 4 avanzar, 8 siguiente);
  - ``85 <celda>``: botón de enrutamiento (desde 0);
  - ``8B <n>``: rueda de desplazamiento del Apex BT (0 giro a la izquierda,
    1 giro a la derecha, 2 arriba, 3 abajo, 4 izquierda, 5 derecha, 6 centro);
  - ``8D <modificadores> 8C <tecla>``: teclado QWERTY de la BrailleNote QT
    (modificadores: 1 función, 2 mayúsculas, 4 control, 8 lectura; la tecla
    es un código de tecla virtual de Windows). ``8C <tecla>`` suelto es una
    tecla sin modificadores.

Cada evento llega cuando se completa la combinación (no hay pulsar/soltar).

Nombres de teclas (gestos ``br(brailleNote):...``): ``d1``...``d8``,
``space``, ``tprevious``, ``tback``, ``tadvance``, ``tnext`` (teclas de
pulgar), ``routing``, ``wCounterclockwise``, ``wClockwise``, ``wUp``,
``wDown``, ``wLeft``, ``wRight``, ``wCenter`` (rueda) y, en la QT,
``function``, ``shift``, ``control``, ``read`` más la tecla (``a``...
``z``, ``0``...``9``, ``enter``, ``tab``, ``upArrow``...).
"""

from __future__ import annotations

from ...i18n import _
from ...log import getLogger
from .base import BrailleGesture, DeviceMatch, DisplayNotFound, HardwareDriver
from .ports import DeviceInfo

log = getLogger("braille.brailleNote")

BAUD_RATE = 38400
ESC = 0x1B
DESCRIBE = bytes((ESC, ord("?")))
DISPLAY = bytes((ESC, ord("B")))

TAG_DOTS = 0x80
TAG_DOTS_SPACE = 0x81
TAG_DOTS_BACKSPACE = 0x82
TAG_DOTS_ENTER = 0x83
TAG_THUMBS = 0x84
TAG_ROUTING = 0x85
TAG_STATUS = 0x86
TAG_WHEEL = 0x8B
TAG_QT_KEY = 0x8C
TAG_QT_MODIFIERS = 0x8D

#: Longitud total de cada mensaje (etiqueta incluida).
MESSAGE_LENGTHS = {
	TAG_DOTS: 2,
	TAG_DOTS_SPACE: 2,
	TAG_DOTS_BACKSPACE: 2,
	TAG_DOTS_ENTER: 2,
	TAG_THUMBS: 2,
	TAG_ROUTING: 2,
	TAG_STATUS: 3,
	TAG_WHEEL: 2,
	TAG_QT_KEY: 2,
	TAG_QT_MODIFIERS: 4,
}

DOT7 = 0x40
DOT8 = 0x80

THUMB_KEYS = ((0x01, "tprevious"), (0x02, "tback"), (0x04, "tadvance"), (0x08, "tnext"))
WHEEL_KEYS = ("wCounterclockwise", "wClockwise", "wUp", "wDown", "wLeft", "wRight", "wCenter")
QT_MODIFIERS = ((0x01, "function"), (0x02, "shift"), (0x04, "control"), (0x08, "read"))
#: Modificadores de la QT que se pueden emular tal cual en el teclado del PC.
QT_PC_MODIFIERS = frozenset({"shift", "control"})

#: Código de tecla virtual de la QT -> nombre de la tecla en el gesto.
QT_KEYS = {
	8: "backspace",
	9: "tab",
	13: "enter",
	27: "escape",
	32: "space",
	33: "pageUp",
	34: "pageDown",
	35: "end",
	36: "home",
	37: "leftArrow",
	38: "upArrow",
	39: "rightArrow",
	40: "downArrow",
	45: "insert",
	46: "delete",
	186: "semicolon",
	187: "equals",
	188: "comma",
	189: "dash",
	190: "period",
	191: "slash",
	192: "grave",
	219: "leftBracket",
	220: "backslash",
	221: "rightBracket",
	222: "apostrophe",
}
for _vk in range(0x30, 0x3A):
	QT_KEYS[_vk] = chr(_vk)
for _vk in range(0x41, 0x5B):
	QT_KEYS[_vk] = chr(_vk).lower()
#: Teclas de signos (OEM): dependen de la distribución del teclado.
QT_OEM_KEYS = frozenset(range(186, 223))

#: Rango de direcciones Bluetooth de los BrailleNote Apex.
APEX_BLUETOOTH_RANGES = ((0x0025EC000000, 0x0025EC01869F),)
APEX_USB_ID = "VID_1C71&PID_C004"

DESCRIBE_ATTEMPTS = 3
DESCRIBE_TIMEOUT = 0.5


class BrailleNoteDriver(HardwareDriver):
	name = "brailleNote"
	description = _("HumanWare BrailleNote (Apex, BT, mPower, PK, QT)")
	usbSerialIds = frozenset({APEX_USB_ID})
	bluetoothPrefixes = ("BrailleNote", "Braillenote")
	baudRate = BAUD_RATE
	keyOrder = [
		"read",
		"function",
		"control",
		"shift",
		"tprevious",
		"tback",
		"tadvance",
		"tnext",
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
	spaceKeys = frozenset({"space"})
	gestureMap = {
		# Teclas de pulgar.
		"tback": "braille_scrollBack",
		"tadvance": "braille_scrollForward",
		"tprevious": "braille_previousLine",
		"tnext": "braille_nextLine",
		"tprevious+tnext": "braille_toggleTether",
		"tback+tadvance": "braille_toFocus",
		# Enrutamiento.
		"routing": "braille_routeTo",
		# Rueda de desplazamiento (Apex BT).
		"wUp": "kb:upArrow",
		"wDown": "kb:downArrow",
		"wLeft": "kb:leftArrow",
		"wRight": "kb:rightArrow",
		"wCenter": "kb:enter",
		"wClockwise": "kb:tab",
		"wCounterclockwise": "kb:shift+tab",
		# Espacio + puntos (igual que en las demás líneas).
		"space+d1": "kb:upArrow",
		"space+d4": "kb:downArrow",
		"space+d3": "kb:leftArrow",
		"space+d6": "kb:rightArrow",
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
		"space+d1+d3+d4+d5": "showGui",
		"space+d1+d2+d3+d4+d5+d6": "sayAll",
		"space+d1+d2+d5": "toggleInputHelp",
		"space+d7": "kb:backspace",
		"space+d8": "kb:enter",
		# Teclado QWERTY de la BrailleNote QT (el resto de teclas se emulan tal cual).
		"function+upArrow": "kb:pageUp",
		"function+downArrow": "kb:pageDown",
		"function+leftArrow": "kb:home",
		"function+rightArrow": "kb:end",
		"read+t": "kb:control+home",
		"read+b": "kb:control+end",
		"read+n": "showGui",
		"read+w": "kb:windows",
		"read+m": "kb:alt",
		"read+h": "toggleInputHelp",
		"read+a": "sayAll",
	}
	keyDescriptions = {
		"d1": _("teclas de puntos 1 a 6 (d1...d6); retroceso es el punto 7 (d7) e Intro el punto 8 (d8)"),
		"space": _("barra espaciadora"),
		"tprevious": _("tecla de pulgar Anterior (la de más a la izquierda)"),
		"tback": _("tecla de pulgar Atrás"),
		"tadvance": _("tecla de pulgar Avanzar"),
		"tnext": _("tecla de pulgar Siguiente (la de más a la derecha)"),
		"routing": _("botones de enrutamiento sobre cada celda"),
		"wUp": _("rueda de desplazamiento del Apex BT: arriba, abajo, izquierda, derecha, centro y giro (wUp, wDown, wLeft, wRight, wCenter, wClockwise, wCounterclockwise)"),
		"read": _("teclas de la BrailleNote QT: Lectura (read), Función (function), Mayúsculas (shift) y Control (control)"),
	}

	def __init__(self, *args, **kwargs) -> None:
		self._buffer = bytearray()
		self._status = 0
		#: Tecla del PC que corresponde al último acorde de la QT (para emularla).
		self._qtEmulation: str | None = None
		super().__init__(*args, **kwargs)

	# ------------------------------------------------------------ detección
	@classmethod
	def _bluetoothNameMatches(cls, name: str) -> bool:
		low = (name or "").lower()
		# La BrailleNote Touch usa el protocolo Brailliant (controlador brailliantB).
		return low.startswith("braillenote") and "touch" not in low

	@staticmethod
	def _isApexAddress(address: int) -> bool:
		return any(first <= address <= last for first, last in APEX_BLUETOOTH_RANGES)

	@classmethod
	def matchDevice(cls, dev: DeviceInfo, allowGeneric: bool = True) -> DeviceMatch | None:
		if dev.kind != "serial":
			return None
		if dev.bluetooth:
			if cls._isApexAddress(dev.bluetoothAddress) or cls._bluetoothNameMatches(dev.bluetoothName):
				return DeviceMatch("serial", dev.bluetoothName, dev.path, True, dev)
			return None
		if dev.usbId in cls.usbSerialIds:
			return DeviceMatch("serial", dev.usbId, dev.path, False, dev)
		return None

	# ------------------------------------------------------------ conexión
	def _connect(self, match: DeviceMatch) -> None:
		self._resetState()
		self.numCells = 0
		self._io = self._open(match, baudrate=BAUD_RATE, parity="N")
		for _attempt in range(DESCRIBE_ATTEMPTS):
			self._write(DESCRIBE)
			if self._waitFor(lambda: self.numCells > 0, DESCRIBE_TIMEOUT):
				break
		if self.numCells <= 0:
			raise DisplayNotFound("No es una BrailleNote o no responde")
		apex = match.id == APEX_USB_ID or (match.device is not None and self._isApexAddress(match.device.bluetoothAddress))
		if apex:
			self.model = "Apex"
			self.deviceName = _("BrailleNote Apex de {cells} celdas").format(cells=self.numCells)
		else:
			self.model = "BrailleNote"
			self.deviceName = _("BrailleNote de {cells} celdas").format(cells=self.numCells)

	def _resetState(self) -> None:
		self._buffer.clear()

	# ------------------------------------------------------------ entrada
	def _handleData(self, data: bytes) -> None:
		buf = self._buffer
		buf.extend(data)
		while buf:
			tag = buf[0]
			length = MESSAGE_LENGTHS.get(tag)
			if length is None:
				log.debug("BrailleNote: byte desconocido %02X", tag)
				del buf[0]
				continue
			if len(buf) < length:
				return
			message = bytes(buf[:length])
			del buf[:length]
			self._handleMessage(message)

	def _handleMessage(self, msg: bytes) -> None:
		tag = msg[0]
		if tag == TAG_STATUS:
			self._status = msg[1]
			if msg[2] > 0:
				self.numCells = msg[2]
		elif tag in (TAG_DOTS, TAG_DOTS_SPACE, TAG_DOTS_BACKSPACE, TAG_DOTS_ENTER):
			dots = msg[1]
			if tag == TAG_DOTS_BACKSPACE:
				dots |= DOT7
			elif tag == TAG_DOTS_ENTER:
				dots |= DOT8
			chord = {f"d{i + 1}" for i in range(8) if dots & (1 << i)}
			if tag != TAG_DOTS:
				chord.add("space")
			if chord:
				self._fireChord(chord)
		elif tag == TAG_THUMBS:
			chord = {name for bit, name in THUMB_KEYS if msg[1] & bit}
			if chord:
				self._fireChord(chord)
		elif tag == TAG_ROUTING:
			self._fireChord({("routing", msg[1])})
		elif tag == TAG_WHEEL:
			if msg[1] < len(WHEEL_KEYS):
				self._fireChord({WHEEL_KEYS[msg[1]]})
			else:
				log.debug("BrailleNote: movimiento de rueda desconocido %d", msg[1])
		elif tag == TAG_QT_KEY:
			self._qtKey(0, msg[1])
		elif tag == TAG_QT_MODIFIERS:
			if msg[2] != TAG_QT_KEY:
				log.debug("BrailleNote: tecla QT con formato inesperado %r", msg)
			self._qtKey(msg[1], msg[3])

	def _qtKey(self, modifiers: int, vk: int) -> None:
		"""Una tecla del teclado QWERTY de la BrailleNote QT."""
		mods = {name for bit, name in QT_MODIFIERS if modifiers & bit}
		key = QT_KEYS.get(vk, f"vk{vk:02x}")
		chord = mods | {key}
		self._qtEmulation = self._pcKeyFor(mods, vk)
		try:
			self._fireChord(chord)
		finally:
			self._qtEmulation = None

	@staticmethod
	def _pcKeyFor(mods: set[str], vk: int) -> str | None:
		"""Tecla del PC equivalente (``kb:...``) o ``None`` si no la hay."""
		if mods - QT_PC_MODIFIERS or vk not in QT_KEYS:
			return None
		if vk in QT_OEM_KEYS:
			# Se usa el carácter que produce la tecla en la distribución actual.
			try:
				from ...input import keys

				name = keys.vkName(vk, False)
			except Exception:
				return None
			if not name or name.startswith("vk"):
				return None
		else:
			name = QT_KEYS[vk]
		order = [m for m in ("control", "shift") if m in mods]
		return "kb:" + "+".join(order + [name])

	def _makeGesture(self, chord) -> BrailleGesture | None:
		gesture = super()._makeGesture(chord)
		if gesture is not None and gesture.emulatedKey is None and self._qtEmulation:
			# Las teclas de la QT sin gesto propio se envían como el teclado del PC.
			gesture.emulatedKey = self._qtEmulation
		return gesture

	# ------------------------------------------------------------ salida
	def _writeCells(self, cells: list[int]) -> None:
		out = bytearray(DISPLAY)
		for cell in cells:
			cell &= 0xFF
			out.append(cell)
			if cell == ESC:
				out.append(ESC)
		self._write(bytes(out))


BrailleDisplayDriver = BrailleNoteDriver
