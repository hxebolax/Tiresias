"""Líneas braille de HIMS: Braille Sense, Braille EDGE, QBraille XL, Braille
eMotion, Smart Beetle y Sync Braille.

Conexiones:

- **USB bulk** con el controlador USB de HIMS (``himsusb.sys``) o, donde
  Windows 11 no deja instalarlo, con el paquete WinUSB de HIMS (NVDA #20555,
  ver :mod:`.winusb`): Braille Sense (2, U2, Polaris, 6, mini...), Smart
  Beetle, Braille EDGE 40 y QBraille XL.
- **USB serie**: Sync Braille (chip FTDI) y Braille eMotion / EDGE 2S (chip WCH).
- **USB HID**: Braille eMotion / EDGE 3S (protocolo HID propio de HIMS).
- **Bluetooth** (puerto serie): Braille Sense, BrailleSense 6, Braille EDGE,
  QBraille XL y Smart Beetle.

Protocolo serie/bulk
--------------------
Tramas del ordenador a la línea::

	T T 01 F0 <lon1 LE16> <datos1> F1 F2 <lon2 LE16> <datos2> F3 00 00 00 00 <suma> FD FD

``T`` es el tipo (``FC`` = celdas, ``FB`` = petición del número de celdas) y
``suma`` es la suma de todos los bytes de la trama (con la suma a cero)
truncada a 8 bits.

Tramas de la línea al ordenador (10 bytes)::

	FA <modo> 01 <valor> <teclas LE32> <suma> FB

``modo`` 0 = tecla de enrutamiento ``valor``; 1 = teclas (máscara de 32
bits, la línea envía la combinación completa); 2 = la línea tiene ``valor``
celdas. ``suma`` es la suma de los otros nueve bytes.

Identificación: el ordenador pregunta ``1C <id> 1F`` por cada identificador
posible (``SX``, ``QX``, ``BE``, ``LX``, ``BS``) y la línea contesta con la
misma trama si es el suyo.

Los códigos de las teclas de cada modelo coinciden con los de los
controladores de NVDA y BRLTTY. Donde no coinciden (Braille eMotion por
serie) o no hay datos (QBraille XL), se explica junto a la tabla.

Protocolo HID (Braille eMotion / EDGE 3S)
-----------------------------------------
El número de celdas está en el byte 9 del informe de característica 1. Las
celdas se envían como informe de salida ``<celdas> <puntos...>``. Los
informes de entrada son de 12 bytes con el estado de las teclas (bytes 2-6:
enrutamiento, una tecla por bit); un informe a cero significa que se han
soltado todas.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ...i18n import _
from ...log import getLogger
from . import hwio, winusb
from .base import DeviceMatch, DisplayNotFound, HardwareDriver
from .ports import DeviceInfo

log = getLogger("braille.hims")

BAUD_RATE = 115200

# Tipos de trama del ordenador a la línea.
PKT_CELLS = 0xFC
PKT_CELL_COUNT = 0xFB
# Tramas de la línea al ordenador.
IN_START = 0xFA
IN_END = 0xFB
IN_LENGTH = 10
IN_CHECKSUM = 8
MODE_ROUTING = 0x00
MODE_KEYS = 0x01
MODE_CELL_COUNT = 0x02
# Identificación.
ID_START = 0x1C
ID_END = 0x1F

# Protocolo HID.
HID_CAPS_REPORT = 0x01
HID_CAPS_CELLS_INDEX = 9
HID_REPORT_SIZE = 12
HID_ROUTING_SHIFT = 16
HID_ROUTING_KEYS = 40

USB_SENSE = "VID_045E&PID_930A"
USB_EDGE = "VID_045E&PID_930B"
#: Braille eMotion (NVDA lo llama Braille EDGE 3S) por HID.
USB_EMOTION_HID = "VID_045E&PID_940A"
#: Braille eMotion (NVDA: Braille EDGE 2S) por serie (chip WCH CH343).
USB_EMOTION_SERIAL = "VID_1A86&PID_55D3"
USB_SYNC = "VID_0403&PID_6001"


# ======================================================================= teclas
def _keys(*groups: dict[int, str]) -> dict[int, str]:
	out: dict[int, str] = {}
	for g in groups:
		out.update(g)
	return out


#: Teclado braille y espacio (bits 0-8).
_BRAILLE = {**{1 << i: f"dot{i + 1}" for i in range(8)}, 0x0100: "space"}

#: F1-F4 (bits 9-12).
_F14 = {0x0200: "f1", 0x0400: "f2", 0x0800: "f3", 0x1000: "f4"}

#: Las dos teclas de desplazamiento («atrás» y «adelante») de los Braille
#: Sense de una tecla a cada lado (bits 13 y 14).
_PAN = {0x2000: "leftSideScroll", 0x4000: "rightSideScroll"}

#: Base común de la serie Braille Sense.
_COMMON = _keys(_BRAILLE, _F14, _PAN)

#: Braille Sense con cuatro teclas de desplazamiento (byte 2).
_SENSE_SCROLL = {
	0x010000: "leftSideScrollUp",
	0x020000: "leftSideScrollDown",
	0x040000: "rightSideScrollUp",
	0x080000: "rightSideScrollDown",
}

#: Braille EDGE: las teclas de desplazamiento van en otro orden.
_EDGE_SCROLL = {
	0x010000: "leftSideScrollUp",
	0x020000: "rightSideScrollUp",
	0x040000: "rightSideScrollDown",
	0x080000: "leftSideScrollDown",
}

#: Braille EDGE 40: F5-F8 (byte 2) y las dos crucetas (byte 3).
_EDGE_EXTRA = {
	0x100000: "f5",
	0x200000: "f6",
	0x400000: "f7",
	0x800000: "f8",
	0x01000000: "leftSideUpArrow",
	0x02000000: "leftSideDownArrow",
	0x04000000: "leftSideLeftArrow",
	0x08000000: "leftSideRightArrow",
	0x10000000: "rightSideUpArrow",
	0x20000000: "rightSideDownArrow",
	0x40000000: "rightSideLeftArrow",
	0x80000000: "rightSideRightArrow",
}

#: Smart Beetle: F2 y F4 tienen los códigos intercambiados y solo tiene dos
#: teclas de desplazamiento, que a veces llegan con los códigos del byte 2.
_BEETLE = {
	0x0400: "f4",
	0x1000: "f2",
	0x040000: "leftSideScroll",
	0x080000: "rightSideScroll",
}

#: Sync Braille: solo cuatro teclas de desplazamiento, en el byte 1.
_SYNC = {
	0x1000: "leftSideScrollUp",
	0x2000: "rightSideScrollUp",
	0x4000: "rightSideScrollDown",
	0x8000: "leftSideScrollDown",
}

#: Braille eMotion por serie: según BRLTTY (tabla «emotion»), F3 y F4 ocupan
#: los bits de F1 y F2, Control y Alt los de F3 y F4, y F1 y F2 los de F7 y
#: F8; las teclas de desplazamiento siguen el orden del EDGE. NVDA (modelo
#: «Edge 2S») lee los bits 9-12 como F1-F4 y no conoce Control ni Alt. Aquí
#: se sigue a BRLTTY porque es coherente con el mismo aparato por HID, que sí
#: tiene Control y Alt.
_EMOTION_SERIAL = {
	0x0200: "f3",
	0x0400: "f4",
	0x0800: "control",
	0x1000: "alt",
	0x400000: "f1",
	0x800000: "f2",
}

#: Braille eMotion por HID: bits del informe de 12 bytes (el byte 0 es el
#: identificador de informe y los bytes 2-6, el enrutamiento).
_EMOTION_HID = {
	**{1 << (8 + i): f"dot{i + 1}" for i in range(8)},
	0x01 << 64: "f1",
	0x02 << 64: "leftCursor",
	0x04 << 64: "f2",
	# El informe no distingue el lado de las teclas de desplazamiento.
	0x08 << 64: "rightSideScrollUp",
	0x10 << 64: "f3",
	0x20 << 64: "rightCursor",
	0x40 << 64: "f4",
	0x80 << 64: "rightSideScrollDown",
	0x01 << 72: "control",
	0x02 << 72: "alt",
	0x04 << 72: "home",
	0x01 << 88: "space",
}


@dataclass(frozen=True)
class HimsModel:
	"""Un modelo de línea HIMS."""

	#: Identificador del modelo en los gestos (``br(hims.<model>):...``).
	model: str
	#: Nombre legible.
	label: str
	#: Identificador de dos bytes del protocolo (vacío si no se pregunta).
	deviceId: bytes
	#: Celdas (0 = las que diga la línea).
	cells: int
	#: Máscara de bits -> nombre de tecla.
	keys: dict[int, str] = field(hash=False, compare=False)
	usbIds: frozenset[str] = frozenset()
	bluetoothPrefixes: tuple[str, ...] = ()


SENSE_QX = HimsModel("BrailleSenseQWERTY", "Braille Sense QWERTY", b"SX", 32, _keys(_COMMON, _SENSE_SCROLL), frozenset({USB_SENSE}), ("BrailleSense",))
SENSE_Q = HimsModel("BrailleSenseQWERTY", "Braille Sense QWERTY", b"QX", 32, _keys(_COMMON, _SENSE_SCROLL), frozenset({USB_SENSE}), ("BrailleSense",))
EDGE = HimsModel("BrailleEdge", "Braille EDGE", b"BE", 40, _keys(_COMMON, _EDGE_SCROLL, _EDGE_EXTRA), frozenset({USB_EDGE}), ("BrailleEDGE",))
#: QBraille XL: BRLTTY lo atiende con el mismo canal USB (045E:930B), la misma
#: identificación («BE») y la misma tabla de teclas que el Braille EDGE, así
#: que por USB no se distingue de él. Solo se reconoce por el nombre Bluetooth
#: (se supone que empieza por «QBraille»; no está comprobado).
QBRAILLE = HimsModel("QBrailleXL", "QBraille XL", b"BE", 40, _keys(_COMMON, _EDGE_SCROLL, _EDGE_EXTRA), frozenset(), ("QBraille",))
EMOTION_SERIAL = HimsModel("BrailleEmotion", "Braille eMotion", b"", 40, _keys(_BRAILLE, _EDGE_SCROLL, _EMOTION_SERIAL), frozenset({USB_EMOTION_SERIAL}))
SMART_BEETLE = HimsModel("SmartBeetle", "Smart Beetle", b"LX", 14, _keys(_COMMON, _BEETLE), frozenset({USB_SENSE}), ("SmartBeetle",))
SENSE = HimsModel("BrailleSense", "Braille Sense", b"LX", 0, _keys(_COMMON, _SENSE_SCROLL), frozenset({USB_SENSE}), ("BrailleSense",))
#: BrailleSense 6: contesta «LX» como los Braille Sense de cuatro teclas de
#: desplazamiento, pero sus teclas de desplazamiento van en el orden del EDGE
#: y no tiene las de un solo lado (tabla «bs6» de BRLTTY). Por Bluetooth se
#: reconoce por el nombre («BrailleSense6», sin distinguir mayúsculas); por
#: USB, porque usa el mismo número de extremo para entrar y salir (solo se ve
#: con WinUSB, ver :meth:`HimsDriver._connect`).
SENSE_6 = HimsModel("BrailleSense6", "BrailleSense 6", b"LX", 0, _keys(_BRAILLE, _F14, _EDGE_SCROLL), frozenset(), ("BrailleSense6",))
SENSE_CLASSIC = HimsModel("BrailleSenseClassic", "Braille Sense Classic", b"BS", 0, _keys(_COMMON, _SENSE_SCROLL), frozenset({USB_SENSE}), ("BrailleSense",))
SYNC = HimsModel("SyncBraille", "Sync Braille", b"", 0, dict(_SYNC), frozenset({USB_SYNC}))
#: Solo por HID.
EMOTION_HID = HimsModel("BrailleEmotion", "Braille eMotion", b"", 40, dict(_EMOTION_HID), frozenset({USB_EMOTION_HID}))

#: Modelos del protocolo serie/bulk, en el orden en que se pregunta su
#: identificador (algunas líneas pueden hacerse pasar por otras).
SERIAL_MODELS: tuple[HimsModel, ...] = (SENSE_QX, SENSE_Q, EDGE, QBRAILLE, EMOTION_SERIAL, SMART_BEETLE, SENSE, SENSE_6, SENSE_CLASSIC, SYNC)


def pickModel(models: list[HimsModel] | tuple[HimsModel, ...], numCells: int) -> HimsModel | None:
	"""Elige entre varios modelos posibles según el número de celdas.

	Un modelo con un número de celdas fijo gana si es el único que coincide;
	si no, el modelo genérico de la serie (sin celdas fijas) y, por último,
	el primero que coincida.
	"""
	if not models:
		return None
	exact = [m for m in models if m.cells and m.cells == numCells]
	if len(exact) == 1:
		return exact[0]
	generic = [m for m in models if not m.cells]
	if generic:
		return generic[0]
	return exact[0] if exact else models[0]


def checksum(data: bytes | bytearray) -> int:
	return sum(data) & 0xFF


def buildPacket(packetType: int, data1: bytes, data2: bytes = b"") -> bytes:
	"""Trama del ordenador a la línea (protocolo serie/bulk)."""
	body = bytearray((packetType, packetType, 0x01, 0xF0))
	body += len(data1).to_bytes(2, "little") + bytes(data1) + b"\xf1"
	body += b"\xf2" + len(data2).to_bytes(2, "little") + bytes(data2) + b"\xf3"
	body += bytes(4)
	body.append(0)  # Hueco de la suma.
	body += b"\xfd\xfd"
	body[-3] = checksum(body)
	return bytes(body)


def buildInputPacket(mode: int, value: int = 0, keys: int = 0) -> bytes:
	"""Trama de la línea al ordenador (la usan las pruebas y la documentación)."""
	packet = bytearray((IN_START, mode, 0x01, value & 0xFF)) + keys.to_bytes(4, "little") + bytearray((0, IN_END))
	packet[IN_CHECKSUM] = checksum(packet[:IN_CHECKSUM] + packet[IN_CHECKSUM + 1 :])
	return bytes(packet)


# ================================================================= controlador
class HimsDriver(HardwareDriver):
	name = "hims"
	description = _("HIMS Braille Sense, Braille EDGE, QBraille XL, Braille eMotion, Smart Beetle y Sync Braille")
	usbBulkIds = frozenset({USB_SENSE, USB_EDGE})
	usbHidIds = frozenset({USB_EMOTION_HID})
	usbSerialIds = frozenset({USB_SYNC, USB_EMOTION_SERIAL})
	# Chips USB-serie genéricos (FTDI y WCH) que usan también otros aparatos.
	genericUsbIds = frozenset({USB_SYNC, USB_EMOTION_SERIAL})
	bluetoothPrefixes = ("BrailleSense", "BrailleEDGE", "SmartBeetle", "QBraille")
	baudRate = BAUD_RATE
	#: Segundos de espera de cada respuesta (bulk tarda más: la línea puede
	#: aparecer en el sistema antes de estar lista, p. ej. al pasar de
	#: Bluetooth a USB en el Braille EDGE).
	replyTimeout = 0.3
	replyTimeoutBulk = 2.0
	replyTimeoutBluetooth = 1.0
	#: Pausa antes de cerrar: sin ella la línea puede quedar en mal estado.
	closeDelay = 0.2

	keyOrder = (
		["space"]
		+ [f"dot{i}" for i in range(1, 9)]
		+ [f"f{i}" for i in range(1, 9)]
		+ ["control", "alt", "home"]
		+ ["leftSideScroll", "rightSideScroll", "leftSideScrollUp", "leftSideScrollDown", "rightSideScrollUp", "rightSideScrollDown"]
		+ [f"{side}Side{d}Arrow" for side in ("left", "right") for d in ("Up", "Down", "Left", "Right")]
		+ ["leftCursor", "rightCursor"]
	)
	dotKeys = {f"dot{i}": i for i in range(1, 9)}
	spaceKeys = frozenset({"space"})

	gestureMap = {
		# Enrutamiento.
		"routing": "braille_routeTo",
		"multiRouting": "braille_selectRange",
		# Desplazamiento: las de arriba retroceden y las de abajo avanzan.
		"leftSideScrollUp": "braille_scrollBack",
		"rightSideScrollUp": "braille_scrollBack",
		"leftSideScrollDown": "braille_scrollForward",
		"rightSideScrollDown": "braille_scrollForward",
		"leftSideScroll": "braille_scrollBack",
		"rightSideScroll": "braille_scrollForward",
		"leftSideScrollUp+rightSideScrollUp": "braille_previousLine",
		"leftSideScrollDown+rightSideScrollDown": "braille_nextLine",
		"space+leftSideScrollUp": "braille_previousLine",
		"space+rightSideScrollUp": "braille_previousLine",
		"space+leftSideScrollDown": "braille_nextLine",
		"space+rightSideScrollDown": "braille_nextLine",
		"space+leftSideScroll": "braille_previousLine",
		"space+rightSideScroll": "braille_nextLine",
		"leftSideScrollUp+leftSideScrollDown": "braille_toFocus",
		"rightSideScrollUp+rightSideScrollDown": "braille_toFocus",
		"leftSideScroll+rightSideScroll": "braille_toFocus",
		# Crucetas del Braille EDGE: la izquierda mueve el cursor y la
		# derecha, el cursor de revisión.
		"leftSideUpArrow": "kb:upArrow",
		"leftSideDownArrow": "kb:downArrow",
		"leftSideLeftArrow": "kb:leftArrow",
		"leftSideRightArrow": "kb:rightArrow",
		"rightSideUpArrow": "review_previousLine",
		"rightSideDownArrow": "review_nextLine",
		"rightSideLeftArrow": "review_previousCharacter",
		"rightSideRightArrow": "review_nextCharacter",
		# Teclas de función (como las teclas de programa, menú, tabulador y
		# escape del Braille Sense).
		"f1": "kb:windows",
		"f2": "kb:alt",
		"f3": "kb:tab",
		"f4": "kb:escape",
		"f2+f3": "kb:alt+tab",
		"f1+f2+f3": "kb:shift+alt+tab",
		"f5": "kb:home",
		"f6": "kb:end",
		"f7": "kb:windows",
		"f8": "kb:applications",
		# Teclas del Braille EDGE 3S.
		"control": "kb:control",
		"alt": "kb:alt",
		"home": "kb:home",
		"leftCursor": "kb:leftArrow",
		"rightCursor": "kb:rightArrow",
		# Espacio + puntos (comunes a las líneas de Tiresias).
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
		# Espacio + puntos al estilo de los anotadores HIMS.
		"space+dot4+dot5": "kb:tab",
		"space+dot1+dot2": "kb:shift+tab",
		"space+dot2": "kb:control+leftArrow",
		"space+dot5": "kb:control+rightArrow",
		"space+dot2+dot3": "kb:control+upArrow",
		"space+dot5+dot6": "kb:control+downArrow",
		"space+dot1+dot2+dot3": "kb:control+home",
		"space+dot4+dot5+dot6": "kb:control+end",
		"space+dot1+dot2+dot6": "kb:pageUp",
		"space+dot3+dot4+dot5": "kb:pageDown",
		"space+dot1+dot2+dot6+dot8": "kb:control+pageUp",
		"space+dot3+dot4+dot5+dot8": "kb:control+pageDown",
		"space+dot1+dot3+dot5": "kb:delete",
		"space+dot1+dot3+dot5+dot6": "kb:alt+f4",
		"space+dot1+dot2+dot3+dot4": "kb:applications",
		"space+dot1+dot3+dot6": "kb:capsLock",
	}

	modelGestureMaps = {
		# Braille EDGE: F1 escape, F2 tabulador, F3 control y F4 alt.
		"BrailleEdge": {
			"f1": "kb:escape",
			"f2": "kb:tab",
			"f3": "kb:control",
			"f4": "kb:alt",
		},
		# Smart Beetle: F1 control, F2 Windows, F3 alt y F4 inicio.
		"SmartBeetle": {
			"f1": "kb:control",
			"f2": "kb:windows",
			"f3": "kb:alt",
			"f4": "kb:home",
		},
	}
	# El QBraille XL usa el protocolo y las teclas del Braille EDGE (por USB
	# ni siquiera se distingue de él): mismas asignaciones en los dos casos.
	modelGestureMaps["QBrailleXL"] = dict(modelGestureMaps["BrailleEdge"])

	keyDescriptions = {
		**{f"dot{i}": _("punto {n} del teclado braille").format(n=i) for i in range(1, 9)},
		"space": _("barra espaciadora"),
		**{f"f{i}": _("tecla de función F{n}").format(n=i) for i in range(1, 9)},
		"leftSideScroll": _("tecla de desplazamiento izquierda (modelos con una tecla a cada lado)"),
		"rightSideScroll": _("tecla de desplazamiento derecha (modelos con una tecla a cada lado)"),
		"leftSideScrollUp": _("tecla de desplazamiento izquierda superior"),
		"leftSideScrollDown": _("tecla de desplazamiento izquierda inferior"),
		"rightSideScrollUp": _("tecla de desplazamiento derecha superior"),
		"rightSideScrollDown": _("tecla de desplazamiento derecha inferior"),
		"leftSideUpArrow": _("flecha arriba de la cruceta izquierda (Braille EDGE)"),
		"leftSideDownArrow": _("flecha abajo de la cruceta izquierda (Braille EDGE)"),
		"leftSideLeftArrow": _("flecha izquierda de la cruceta izquierda (Braille EDGE)"),
		"leftSideRightArrow": _("flecha derecha de la cruceta izquierda (Braille EDGE)"),
		"rightSideUpArrow": _("flecha arriba de la cruceta derecha (Braille EDGE)"),
		"rightSideDownArrow": _("flecha abajo de la cruceta derecha (Braille EDGE)"),
		"rightSideLeftArrow": _("flecha izquierda de la cruceta derecha (Braille EDGE)"),
		"rightSideRightArrow": _("flecha derecha de la cruceta derecha (Braille EDGE)"),
		"control": _("tecla Control (Braille eMotion)"),
		"alt": _("tecla Alt (Braille eMotion)"),
		"home": _("tecla Inicio (Braille eMotion por USB HID)"),
		"leftCursor": _("tecla de cursor izquierda (Braille eMotion por USB HID)"),
		"rightCursor": _("tecla de cursor derecha (Braille eMotion por USB HID)"),
		"routing": _("botón de enrutamiento sobre una celda"),
		"multiRouting": _("varios botones de enrutamiento a la vez (solo por HID)"),
	}

	def __init__(self, *args, **kwargs) -> None:
		self._buffer = bytearray()
		self._hid = False
		self._modelInfo: HimsModel | None = None
		self._idReply: bytes | None = None
		#: La conexión USB usa el mismo extremo para entrar y salir (BrailleSense 6).
		self._sense6Hint = False
		super().__init__(*args, **kwargs)

	# ------------------------------------------------------------ detección
	@classmethod
	def matchDevice(cls, dev: DeviceInfo, allowGeneric: bool = True) -> DeviceMatch | None:
		# Por Bluetooth HID estas líneas usan el estándar HID Braille (lo
		# atiende hidBraille); el protocolo HID propio solo es del eMotion por USB.
		if dev.kind == "hid" and dev.bluetooth:
			return None
		if dev.kind == "winusb":
			# Interfaz del paquete WinUSB de HIMS (NVDA #20555).
			if not dev.usbId or dev.usbId in cls.usbBulkIds:
				return DeviceMatch("winusb", dev.usbId, dev.path, False, dev)
			return None
		return super().matchDevice(dev, allowGeneric=allowGeneric)

	@classmethod
	def getMatches(cls, devices: list[DeviceInfo], usb: bool = True, bluetooth: bool = True, allowGeneric: bool = True) -> list[DeviceMatch]:
		devices = list(devices)
		# NVDA #20555: en Windows 11 la línea puede estar con WinUSB en vez de
		# himsusb.sys. Se buscan sus interfaces WinUSB si hay una línea HIMS
		# USB conectada (y van delante: con WinUSB, la apertura bulk falla).
		if usb and not any(d.kind == "winusb" for d in devices) and any(d.kind == "usb" and d.usbId in cls.usbBulkIds for d in devices):
			devices = winusb.listDevices() + devices
		return super().getMatches(devices, usb=usb, bluetooth=bluetooth, allowGeneric=allowGeneric)

	@classmethod
	def _bluetoothNameMatches(cls, name: str) -> bool:
		low = (name or "").lower()
		return bool(low) and any(low.startswith(p.lower()) for p in cls.bluetoothPrefixes)

	@staticmethod
	def candidateModels(match: DeviceMatch) -> list[HimsModel]:
		"""Modelos posibles según el identificador USB o el nombre Bluetooth."""
		if match.type == "hid":
			return [EMOTION_HID]
		if match.bluetooth:
			# Gana el prefijo más largo: «BrailleSense6» frente a «BrailleSense».
			name = (match.id or "").lower()
			best = 0
			found: list[HimsModel] = []
			for m in SERIAL_MODELS:
				length = max((len(p) for p in m.bluetoothPrefixes if name.startswith(p.lower())), default=0)
				if not length or length < best:
					continue
				if length > best:
					best = length
					found = []
				found.append(m)
		else:
			# Un puerto COM elegido a mano no trae el identificador en ``id``.
			usbId = match.id or (match.device.usbId if match.device is not None else "")
			found = [m for m in SERIAL_MODELS if usbId and usbId in m.usbIds]
		return found or list(SERIAL_MODELS)

	# ------------------------------------------------------------ conexión
	def _open(self, match: DeviceMatch, baudrate: int | None = None, **kwargs) -> hwio.Transport:
		if match.type == "winusb":
			# NVDA #20555: WinUSB en lugar de himsusb.sys.
			return winusb.WinUsbDevice(match.port, self._onReceive, self._onIoError, readSize=kwargs.get("readSize", 64), info=match.info)
		return super()._open(match, baudrate, **kwargs)

	def _replyTimeout(self, match: DeviceMatch) -> float:
		if match.type in ("bulk", "winusb"):
			return self.replyTimeoutBulk
		if match.bluetooth:
			return self.replyTimeoutBluetooth
		return self.replyTimeout

	def _connect(self, match: DeviceMatch) -> None:
		self._resetState()
		self.numCells = 0
		self._sense6Hint = False
		self._hid = match.type == "hid"
		if self._hid:
			self._connectHid(match)
			return
		if match.type in ("bulk", "winusb"):
			self._io = self._open(match, epIn=0, epOut=1, readSize=64)
			# BRLTTY distingue el BrailleSense 6 por USB porque entra y sale
			# por el extremo 1 (los demás salen por el 2). Solo WinUSB dice
			# qué extremos son; con himsusb.sys se ve como Braille Sense.
			pipeIn = getattr(self._io, "pipeIn", None)
			pipeOut = getattr(self._io, "pipeOut", None)
			if isinstance(pipeIn, int) and isinstance(pipeOut, int):
				self._sense6Hint = (pipeIn & 0x0F) == (pipeOut & 0x0F)
		else:
			self._io = self._open(match, baudrate=BAUD_RATE, parity="N")
		timeout = self._replyTimeout(match)
		for _attempt in range(3):
			self._write(buildPacket(PKT_CELL_COUNT, bytes(32)))
			if self._waitFor(lambda: self.numCells > 0, timeout):
				break
		if self.numCells <= 0:
			raise DisplayNotFound("La línea HIMS no indica sus celdas")
		# Ya se sabe que la línea está lista: la identificación no necesita la
		# espera larga de bulk.
		model = self._identify(match, self.replyTimeoutBluetooth if match.bluetooth else self.replyTimeout)
		if model is SENSE and self._sense6Hint:
			model = SENSE_6
		self._setModel(model)

	def _identify(self, match: DeviceMatch, timeout: float) -> HimsModel:
		"""Averigua el modelo: directamente si solo hay uno posible o preguntando."""
		candidates = self.candidateModels(match)
		if len(candidates) == 1:
			return candidates[0]
		asked: list[bytes] = []
		for model in candidates:
			if not model.deviceId or model.deviceId in asked:
				continue
			asked.append(model.deviceId)
			self._idReply = None
			self._write(bytes((ID_START,)) + model.deviceId + bytes((ID_END,)))
			if self._waitFor(lambda: self._idReply is not None, timeout):
				reply = self._idReply
				found = pickModel([m for m in SERIAL_MODELS if m.deviceId == reply], self.numCells)
				if found is not None:
					return found
				log.debug("Identificador HIMS desconocido: %r", reply)
		# La línea ha contestado al número de celdas pero no a la identificación.
		model = pickModel(candidates, self.numCells) or SENSE
		log.debug("La línea HIMS no se identifica; se supone %s", model.label)
		return model

	def _connectHid(self, match: DeviceMatch) -> None:
		self._io = self._open(match, exclusive=False)
		cells = 0
		for _attempt in range(3):
			try:
				caps = self._io.getFeature(HID_CAPS_REPORT)  # type: ignore[union-attr]
			except (hwio.IoError, OSError, AttributeError) as e:
				log.debug("No se pudo leer el número de celdas por HID: %s", e)
				continue
			if len(caps) > HID_CAPS_CELLS_INDEX and caps[HID_CAPS_CELLS_INDEX]:
				cells = caps[HID_CAPS_CELLS_INDEX]
				break
		self._setModel(EMOTION_HID, cells or EMOTION_HID.cells)

	def _setModel(self, model: HimsModel, cells: int = 0) -> None:
		self._modelInfo = model
		if cells:
			self.numCells = cells
		elif not self.numCells:
			self.numCells = model.cells
		self.model = model.model
		self.deviceName = f"HIMS {model.label}"

	def _resetState(self) -> None:
		self._buffer.clear()
		self._idReply = None

	# ------------------------------------------------------------ entrada
	def _handleData(self, data: bytes) -> None:
		if self._hid:
			self._handleHidReport(data)
			return
		buf = self._buffer
		buf += data
		while buf:
			head = buf[0]
			if head == IN_START:
				if len(buf) >= 3 and buf[2] != 0x01:
					del buf[0]
					continue
				if len(buf) < IN_LENGTH:
					return
				packet = bytes(buf[:IN_LENGTH])
				if packet[9] != IN_END or checksum(packet[:IN_CHECKSUM] + packet[IN_CHECKSUM + 1 :]) != packet[IN_CHECKSUM]:
					log.debug("Trama HIMS no válida: %s", packet.hex(" "))
					del buf[0]
					continue
				del buf[:IN_LENGTH]
				self._handlePacket(packet)
			elif head == ID_START:
				if len(buf) < 4:
					return
				if buf[3] != ID_END:
					del buf[0]
					continue
				self._idReply = bytes(buf[1:3])
				del buf[:4]
			else:
				# Relleno (p. ej. ceros de las lecturas bulk) o basura.
				del buf[0]

	def _handlePacket(self, packet: bytes) -> None:
		mode = packet[1]
		if mode == MODE_ROUTING:
			if self.numCells and packet[3] >= self.numCells:
				return
			self._fireChord({("routing", packet[3])})
		elif mode == MODE_KEYS:
			mask = int.from_bytes(packet[4:8], "little")
			names = self._decodeKeys(mask)
			if names:
				self._fireChord(names)
		elif mode == MODE_CELL_COUNT:
			if packet[3]:
				self.numCells = packet[3]
		else:
			log.debug("Modo de trama HIMS desconocido: %d", mode)

	def _decodeKeys(self, mask: int) -> set[str]:
		"""Nombres de las teclas de una máscara (vacío si hay bits desconocidos)."""
		model = self._modelInfo
		if model is None or not mask:
			return set()
		names: set[str] = set()
		rest = mask
		for bit, name in model.keys.items():
			if mask & bit:
				names.add(name)
				rest &= ~bit
		if rest:
			# Una combinación incompleta podría ejecutar algo distinto de lo pulsado.
			log.debug("Teclas HIMS desconocidas: 0x%x", rest)
			return set()
		return names

	def _handleHidReport(self, data: bytes) -> None:
		report = bytes(data[:HID_REPORT_SIZE])
		# El byte 0 es el identificador de informe.
		value = int.from_bytes(report, "little") & ~0xFF
		routingMask = ((1 << HID_ROUTING_KEYS) - 1) << HID_ROUTING_SHIFT
		routing = (value & routingMask) >> HID_ROUTING_SHIFT
		down: set = {("routing", i) for i in range(HID_ROUTING_KEYS) if routing & (1 << i)}
		rest = value & ~routingMask
		if rest:
			names = self._decodeKeys(rest)
			if not names:
				return
			down |= names
		self._keysChanged(down)

	# ------------------------------------------------------------ salida
	def _writeCells(self, cells: list[int]) -> None:
		data = bytes(c & 0xFF for c in cells)
		if self._hid:
			io = self._io
			if io is None:
				return
			io.setOutputReport(bytes((self.numCells,)) + data)  # type: ignore[attr-defined]
			return
		self._write(buildPacket(PKT_CELLS, data))

	def _sayGoodbye(self) -> None:
		if not isinstance(self._io, hwio.MemoryTransport):
			time.sleep(self.closeDelay)


BrailleDisplayDriver = HimsDriver
