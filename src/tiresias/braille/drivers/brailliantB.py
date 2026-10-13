"""Líneas braille de HumanWare con protocolo propio (familia Brailliant).

Modelos: Brailliant BI 14, BI 32, BI 40 y B 80, Brailliant BI 40X y BI 20X,
BrailleNote Touch (y Touch Plus), BrailleOne 20, NLS eReader 20 de
HumanWare, APH Chameleon 20 y APH Mantis Q40.

Hay dos variantes del protocolo:

- **HID** (USB y Bluetooth). Las celdas se piden con el informe de
  características 1 (el byte 24 es el número de celdas; si no lo indica, se
  deduce del tamaño del informe de salida). Las teclas llegan en el informe
  de entrada 4 con los códigos de las teclas pulsadas en ese momento
  (terminados en 0). Las celdas se envían con el informe de salida 5
  (``05 01 00 <celdas> <puntos...>``) mediante ``HidD_SetOutputReport``.
  El informe 7 avisa de que la línea se apaga.
- **Serie** (puerto COM virtual de USB y Bluetooth, 115200 baudios, paridad
  par). Cada mensaje es ``ESC <id> <longitud> <datos>``: 00 = petición de
  identificación, 01 = respuesta (datos[0] = 0 si se permite la
  comunicación, datos[2] = celdas), 02 = celdas, 05/06 = tecla pulsada o
  soltada (un byte con su código).

Los Brailliant BI 40X/20X, Chameleon y Mantis tienen además una interfaz HID
Braille estándar: este controlador usa la interfaz propia de HumanWare
(página de uso 0x93) y deja la estándar al controlador «hidBraille».

Nombres de teclas (gestos ``br(brailliantB):...``): ``dot1``...``dot8``,
``space``, ``c1``...``c6`` (teclas de órdenes), ``up``, ``left``,
``right``, ``down`` (teclas de pulgar), ``stickUp``, ``stickDown``,
``stickLeft``, ``stickRight``, ``stickAction`` (joystick del BI 14),
``power``, ``routing``/``multiRouting`` y las de calibración de la
BrailleNote Touch (``calibrationOk``...).
"""

from __future__ import annotations

import time

from ...i18n import _
from ...log import getLogger
from .base import DeviceMatch, DisplayNotFound, HardwareDriver
from .ports import DeviceInfo

log = getLogger("braille.brailliantB")

# ------------------------------------------------------------------ serie
SERIAL_BAUD = 115200
SERIAL_PARITY = "E"
ESC = 0x1B
CMD_IDENTIFY = 0x00
CMD_IDENTITY = 0x01
CMD_CELLS = 0x02
CMD_KEY_DOWN = 0x05
CMD_KEY_UP = 0x06

# ------------------------------------------------------------------ HID
REPORT_CAPABILITIES = 0x01
REPORT_KEYS = 0x04
REPORT_CELLS = 0x05
REPORT_POWER_OFF = 0x07
#: Página de uso de la interfaz HID propia de HumanWare.
HUMANWARE_USAGE_PAGE = 0x93
#: Posición del número de celdas en el informe de características.
CAPS_CELLS_OFFSET = 24
#: Bytes del informe de celdas que no son celdas (id, módulo, desplazamiento, cantidad).
CELLS_REPORT_OVERHEAD = 4
STANDARD_BRAILLE_USAGE_PAGE = 0x41
GENERIC_DESKTOP_USAGE_PAGE = 0x01

#: Código de tecla -> nombre.
KEY_CODES = {
	1: "power",
	2: "dot1",
	3: "dot2",
	4: "dot3",
	5: "dot4",
	6: "dot5",
	7: "dot6",
	8: "dot7",
	9: "dot8",
	10: "space",
	11: "c1",
	12: "c2",
	13: "c3",
	14: "c4",
	15: "c5",
	16: "c6",
	17: "up",
	18: "left",
	19: "right",
	20: "down",
	21: "stickUp",
	22: "stickDown",
	23: "stickLeft",
	24: "stickRight",
	25: "stickAction",
	30: "calibrationOk",
	31: "calibrationFail",
	32: "calibrationEmpty",
	34: "calibrationReset",
}
#: Los códigos desde aquí son las teclas de enrutamiento (celda 0, 1...).
ROUTING_BASE = 80

# ------------------------------------------------------------------ identificadores
#: Modelos HID con interfaz propia (página 0x93) y otra HID Braille estándar.
DUAL_INTERFACE_HID_IDS = frozenset({
	"VID_1C71&PID_C111",  # APH Mantis Q40
	"VID_1C71&PID_C101",  # APH Chameleon 20
	"VID_1C71&PID_C131",  # Brailliant BI 40X
	"VID_1C71&PID_C141",  # Brailliant BI 20X
})
PROPRIETARY_HID_IDS = frozenset({
	"VID_1C71&PID_C006",  # Brailliant BI 32, 40 y 80
	"VID_1C71&PID_C022",  # Brailliant BI 14
	"VID_1C71&PID_C00A",  # BrailleNote Touch
	"VID_1C71&PID_C00E",  # BrailleNote Touch (segunda versión)
	"VID_1C71&PID_C121",  # BrailleOne 20
	"VID_1C71&PID_CE01",  # NLS eReader 20
})
SERIAL_IDS = frozenset({
	"VID_1C71&PID_C005",  # Brailliant BI 32, 40 y 80
	"VID_1C71&PID_C021",  # Brailliant BI 14
})

#: Identificador USB -> (modelo, nombre). Modelo vacío: se deduce de las celdas.
USB_MODELS = {
	"VID_1C71&PID_C111": ("MantisQ40", "APH Mantis Q40"),
	"VID_1C71&PID_C101": ("Chameleon20", "APH Chameleon 20"),
	"VID_1C71&PID_C131": ("BrailliantBI40X", "Brailliant BI 40X"),
	"VID_1C71&PID_C141": ("BrailliantBI20X", "Brailliant BI 20X"),
	"VID_1C71&PID_C121": ("BrailleOne20", "HumanWare BrailleOne 20"),
	"VID_1C71&PID_CE01": ("NLSeReader20", "NLS eReader 20"),
	"VID_1C71&PID_C022": ("BrailliantBI14", "Brailliant BI 14"),
	"VID_1C71&PID_C021": ("BrailliantBI14", "Brailliant BI 14"),
	"VID_1C71&PID_C00A": ("BrailleNoteTouch", "BrailleNote Touch"),
	"VID_1C71&PID_C00E": ("BrailleNoteTouch", "BrailleNote Touch"),
	"VID_1C71&PID_C006": ("", ""),
	"VID_1C71&PID_C005": ("", ""),
}

#: Productos HID por Bluetooth que solo valen en la interfaz propia (0x93).
DUAL_INTERFACE_PRODUCTS = {
	"APH Chameleon 20": ("Chameleon20", "APH Chameleon 20"),
	"APH Mantis Q40": ("MantisQ40", "APH Mantis Q40"),
	"Brailliant BI 40X": ("BrailliantBI40X", "Brailliant BI 40X"),
	"Brailliant BI 20X": ("BrailliantBI20X", "Brailliant BI 20X"),
}
#: Productos HID por Bluetooth con el protocolo propio en cualquier interfaz.
PROPRIETARY_PRODUCTS = {
	"Brailliant HID": ("", ""),
	"Humanware BrailleOne": ("BrailleOne20", "HumanWare BrailleOne 20"),
	"NLS eReader": ("NLSeReader20", "NLS eReader 20"),
	"NLS eReader Humanware": ("NLSeReader20", "NLS eReader 20"),
}

#: Modelos de la serie Brailliant BI/B según las celdas (cuando el
#: identificador no distingue el tamaño).
MODELS_BY_CELLS = {
	14: ("BrailliantBI14", "Brailliant BI 14"),
	32: ("BrailliantBI32", "Brailliant BI 32"),
	40: ("BrailliantBI40", "Brailliant BI 40"),
	80: ("BrailliantB80", "Brailliant B 80"),
}

#: Intentos de identificación (la línea a veces no contesta recién abierta).
INIT_ATTEMPTS = 3
INIT_TIMEOUT = 0.6
INIT_RETRY_DELAY = 0.3


def _isHumanware(manufacturer: str) -> bool:
	return (manufacturer or "").strip().lower().startswith("humanware")


class BrailliantBDriver(HardwareDriver):
	name = "brailliantB"
	description = _("HumanWare Brailliant BI/B, BrailleNote Touch, BrailleOne, Chameleon y Mantis")
	usbHidIds = DUAL_INTERFACE_HID_IDS | PROPRIETARY_HID_IDS
	usbSerialIds = SERIAL_IDS
	bluetoothPrefixes = ("Brailliant B", "Brailliant 80", "BrailleNote Touch")
	baudRate = SERIAL_BAUD
	keyOrder = [
		"power",
		"c1",
		"c2",
		"c3",
		"c4",
		"c5",
		"c6",
		"up",
		"left",
		"right",
		"down",
		"stickUp",
		"stickDown",
		"stickLeft",
		"stickRight",
		"stickAction",
		"space",
		"dot1",
		"dot2",
		"dot3",
		"dot4",
		"dot5",
		"dot6",
		"dot7",
		"dot8",
	]
	dotKeys = {f"dot{i}": i for i in range(1, 9)}
	spaceKeys = frozenset({"space"})
	gestureMap = {
		# Teclas de pulgar y de órdenes: desplazamiento por la línea.
		"left": "braille_scrollBack",
		"right": "braille_scrollForward",
		"up": "braille_previousLine",
		"down": "braille_nextLine",
		"up+down": "braille_toggleTether",
		"left+right": "braille_toFocus",
		"c1": "braille_previousLine",
		"c2": "braille_scrollBack",
		"c3": "braille_nextLine",
		"c4": "braille_toFocus",
		"c5": "braille_scrollForward",
		"c6": "braille_toggleTether",
		"c1+c3+c4+c5": "showGui",
		"c1+c2+c3+c4+c5+c6": "sayAll",
		# Enrutamiento.
		"routing": "braille_routeTo",
		"multiRouting": "braille_selectRange",
		"c1+routing": "braille_reportFormatting",
		# Joystick del Brailliant BI 14.
		"stickUp": "kb:upArrow",
		"stickDown": "kb:downArrow",
		"stickLeft": "kb:leftArrow",
		"stickRight": "kb:rightArrow",
		"stickAction": "kb:enter",
		# Espacio + puntos (igual que en las demás líneas).
		"space+dot1": "kb:upArrow",
		"space+dot4": "kb:downArrow",
		"space+dot3": "kb:leftArrow",
		"space+dot6": "kb:rightArrow",
		"space+dot1+dot2": "kb:home",
		"space+dot4+dot5": "kb:end",
		"space+dot1+dot2+dot3": "kb:control+home",
		"space+dot4+dot5+dot6": "kb:control+end",
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
	}
	keyDescriptions = {
		"dot1": _("teclas de puntos 1 a 8 del teclado braille (dot1...dot8)"),
		"space": _("barra espaciadora"),
		"c1": _("teclas de órdenes C1 a C6, encima de las celdas (Brailliant BI 32, 40 y 80)"),
		"up": _("teclas de pulgar: arriba, izquierda, derecha y abajo (up, left, right, down)"),
		"stickUp": _("joystick del Brailliant BI 14: arriba, abajo, izquierda, derecha y pulsación central (stickUp...stickAction)"),
		"power": _("botón de encendido (Brailliant BI 32, 40 y 80)"),
		"routing": _("botones de enrutamiento sobre cada celda"),
	}

	def __init__(self, *args, **kwargs) -> None:
		self._hid = False
		self._buffer = bytearray()
		self._denied = False
		self._identity = b""
		super().__init__(*args, **kwargs)

	# ------------------------------------------------------------ detección
	@classmethod
	def _bluetoothNameMatches(cls, name: str) -> bool:
		if not name:
			return False
		return name.startswith("Brailliant B") or name == "Brailliant 80" or "BrailleNote Touch" in name

	@classmethod
	def matchDevice(cls, dev: DeviceInfo, allowGeneric: bool = True) -> DeviceMatch | None:
		if dev.kind == "hid":
			if not cls._hidInterfaceMatches(dev):
				return None
			return DeviceMatch("hid", dev.usbId or dev.product, dev.path, dev.bluetooth, dev)
		if dev.kind == "serial":
			if dev.bluetooth:
				if cls._bluetoothNameMatches(dev.bluetoothName):
					return DeviceMatch("serial", dev.bluetoothName, dev.path, True, dev)
				return None
			if dev.usbId in SERIAL_IDS:
				return DeviceMatch("serial", dev.usbId, dev.path, False, dev)
		return None

	@classmethod
	def _hidInterfaceMatches(cls, dev: DeviceInfo) -> bool:
		"""¿Es esta interfaz HID la del protocolo propio de HumanWare?"""
		page = dev.usagePage
		if dev.usbId in DUAL_INTERFACE_HID_IDS:
			# La interfaz HID Braille estándar (0x41) es del controlador hidBraille.
			return page in (0, HUMANWARE_USAGE_PAGE)
		if dev.usbId in PROPRIETARY_HID_IDS:
			# Las colecciones de teclado o ratón del sistema no son la línea.
			return page != GENERIC_DESKTOP_USAGE_PAGE
		if dev.bluetooth and _isHumanware(dev.manufacturer):
			product = (dev.product or dev.bluetoothName or "").strip()
			if product in DUAL_INTERFACE_PRODUCTS:
				return page in (0, HUMANWARE_USAGE_PAGE)
			if product in PROPRIETARY_PRODUCTS:
				return page != GENERIC_DESKTOP_USAGE_PAGE
		return False

	# ------------------------------------------------------------ conexión
	def _connect(self, match: DeviceMatch) -> None:
		self._resetState()
		self._denied = False
		self.numCells = 0
		self._hid = match.type == "hid"
		if self._hid:
			self._connectHid(match)
		else:
			self._connectSerial(match)
		self._setModel(match)

	def _connectHid(self, match: DeviceMatch) -> None:
		io = self._open(match, exclusive=False)
		self._io = io
		page = getattr(io, "usagePage", None)
		if page == STANDARD_BRAILLE_USAGE_PAGE and self._isDualInterface(match, io):
			raise DisplayNotFound("Interfaz HID Braille estándar: la usa el controlador hidBraille")
		outputSize = int(getattr(io, "outputSize", 0) or 0)
		maxCells = outputSize - CELLS_REPORT_OVERHEAD if outputSize > CELLS_REPORT_OVERHEAD else 0
		reported = 0
		getFeature = getattr(io, "getFeature", None)
		if getFeature is not None:
			for attempt in range(INIT_ATTEMPTS):
				if attempt:
					time.sleep(INIT_RETRY_DELAY)
				try:
					caps = bytes(getFeature(REPORT_CAPABILITIES))
				except OSError as e:
					log.debug("Brailliant HID: no responde a la petición de capacidades: %s", e)
					continue
				if len(caps) > CAPS_CELLS_OFFSET:
					reported = caps[CAPS_CELLS_OFFSET]
				break
		numCells = reported or maxCells
		if maxCells and numCells > maxCells:
			# El informe de salida no admite más celdas de las que caben.
			numCells = maxCells
		if numCells <= 0:
			raise DisplayNotFound("La línea HID no indica sus celdas")
		self.numCells = numCells

	@staticmethod
	def _isDualInterface(match: DeviceMatch, io) -> bool:
		if match.id in DUAL_INTERFACE_HID_IDS:
			return True
		product = (getattr(io, "product", "") or (match.device.product if match.device else "") or "").strip()
		return product in DUAL_INTERFACE_PRODUCTS

	def _connectSerial(self, match: DeviceMatch) -> None:
		self._io = self._open(match, baudrate=SERIAL_BAUD, parity=SERIAL_PARITY)
		for attempt in range(INIT_ATTEMPTS):
			if attempt:
				time.sleep(INIT_RETRY_DELAY)
			self._sendMessage(CMD_IDENTIFY)
			if self._waitFor(lambda: self.numCells > 0 or self._denied, INIT_TIMEOUT):
				break
		if self._denied:
			raise DisplayNotFound("La línea no permite la comunicación")
		if self.numCells <= 0:
			raise DisplayNotFound("La línea no responde a la identificación")

	def _setModel(self, match: DeviceMatch) -> None:
		model, name = "", ""
		if match.id in USB_MODELS:
			model, name = USB_MODELS[match.id]
		else:
			product = ""
			if match.device is not None:
				product = (match.device.product or "").strip()
			product = product or (getattr(self._io, "product", "") or "").strip()
			btName = match.id or (match.device.bluetoothName if match.device else "")
			if product in DUAL_INTERFACE_PRODUCTS:
				model, name = DUAL_INTERFACE_PRODUCTS[product]
			elif product in PROPRIETARY_PRODUCTS:
				model, name = PROPRIETARY_PRODUCTS[product]
			elif btName and "BrailleNote Touch" in btName:
				model, name = "BrailleNoteTouch", "BrailleNote Touch"
		if not model:
			model, name = MODELS_BY_CELLS.get(self.numCells, ("Brailliant", _("Brailliant de {cells} celdas").format(cells=self.numCells)))
		self.model = model
		self.deviceName = name

	def _resetState(self) -> None:
		self._buffer.clear()

	# ------------------------------------------------------------ serie
	def _sendMessage(self, command: int, payload: bytes = b"") -> None:
		self._write(bytes((ESC, command, len(payload))) + bytes(payload))

	def _handleData(self, data: bytes) -> None:
		if self._hid:
			self._handleReport(bytes(data))
			return
		buf = self._buffer
		buf.extend(data)
		while buf:
			if buf[0] != ESC:
				# Basura antes de la cabecera: se descarta hasta el siguiente ESC.
				pos = buf.find(ESC)
				log.debug("Brailliant: se descartan %d bytes sin cabecera", len(buf) if pos < 0 else pos)
				if pos < 0:
					buf.clear()
					return
				del buf[:pos]
			if len(buf) < 3:
				return
			length = buf[2]
			if len(buf) < 3 + length:
				return
			command = buf[1]
			payload = bytes(buf[3 : 3 + length])
			del buf[: 3 + length]
			self._handleMessage(command, payload)

	def _handleMessage(self, command: int, payload: bytes) -> None:
		if command == CMD_IDENTITY:
			self._identity = payload
			if not payload or payload[0] != 0:
				log.debug("Brailliant: la línea no permite la comunicación (%r)", payload)
				self._denied = True
				return
			if len(payload) >= 3 and payload[2] > 0:
				self.numCells = payload[2]
		elif command == CMD_KEY_DOWN and payload:
			self._keyPressed(self._keyFor(payload[0]))
		elif command == CMD_KEY_UP and payload:
			self._keyReleased(self._keyFor(payload[0]))
		else:
			log.debug("Brailliant: mensaje desconocido %02X %r", command, payload)

	@staticmethod
	def _keyFor(code: int):
		if code >= ROUTING_BASE:
			return ("routing", code - ROUTING_BASE)
		return KEY_CODES.get(code, f"key{code}")

	# ------------------------------------------------------------ HID
	def _handleReport(self, report: bytes) -> None:
		if not report:
			return
		reportId = report[0]
		if reportId == REPORT_KEYS:
			codes = report[1:].split(b"\x00", 1)[0]
			self._keysChanged({self._keyFor(c) for c in codes})
		elif reportId == REPORT_POWER_OFF:
			log.debug("Brailliant: la línea se está apagando")
		else:
			log.debug("Brailliant: informe HID desconocido %r", report[:8])

	# ------------------------------------------------------------ salida
	def _writeCells(self, cells: list[int]) -> None:
		data = bytes(c & 0xFF for c in cells)
		if self._hid:
			report = bytes((REPORT_CELLS, 1, 0, len(data))) + data
			io = self._io
			if io is None:
				return
			# Estas líneas no reciben bien WriteFile: hay que usar SetOutputReport.
			setReport = getattr(io, "setOutputReport", None)
			if setReport is not None:
				setReport(report)
			else:
				io.write(report)
		else:
			self._sendMessage(CMD_CELLS, data)


BrailleDisplayDriver = BrailliantBDriver
