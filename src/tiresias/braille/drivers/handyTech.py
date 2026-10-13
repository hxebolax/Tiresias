"""Líneas braille Handy Tech (Help Tech).

Modelos: Modular (20, 40, 80), Modular Evolution (64, 88), Modular Connect 88,
Braille Wave, Easy Braille, Braillino, Braille Star (40, 80), Basic Braille
(16 a 160 celdas), Basic Braille Plus (32, 40), Active Braille, Active Star 40,
Connect Braille, Actilino, Activator, Activator Pro (64, 80) y myBraille (24,
40, 64, 80).

Conexiones:

- **Serie** (USB-serie y Bluetooth): 19200 baudios, 8 bits, paridad impar.
- **HID nativo** (modelos modernos por USB o Bluetooth): cada informe de
  entrada lleva ``0x01 longitud datos...``; los de salida ``0x02 longitud
  datos... 0x00`` (los paquetes largos se trocean en varios informes).
- **Adaptador HID-serie** (cable USB de Handy Tech para líneas serie y las
  Easy Braille / Braille Star 40 con el adaptador integrado): los mismos
  informes, pero llevan trozos del flujo serie que hay que reensamblar. Al
  abrir se le envía la orden «vaciar búferes» (informe ``0xFB 0x01``).

Protocolo (flujo de bytes):

- Identificación: el ordenador envía ``0xFF`` (reinicio) y la línea contesta
  ``0xFE <modelo>`` (o ``0xFD <modelo> <celdas>``).
- Protocolo antiguo (Modular, Braille Wave, Easy Braille, Braillino): celdas
  con ``0x01 <celdas>``; cada tecla es un byte (bit 7 = soltar).
- Protocolo extendido (el resto): paquetes ``0x79 <modelo> <longitud> <tipo>
  <datos...> 0x16`` (la longitud cuenta el tipo y los datos; no hay suma de
  control, el terminador ``0x16`` sirve para resincronizar). Celdas: tipo
  ``0x01``; teclas: tipo ``0x04`` con el código de la tecla.
- La línea confirma cada envío de celdas con ``0x7E`` (o un paquete extendido
  de confirmación); el controlador no envía celdas nuevas hasta recibirla (o
  hasta que pasa un tiempo prudencial) y guarda solo la última pendiente.

Ajustes (Opciones, categoría «Braille»; se aplican al conectar y al guardar):

- **Firmeza de los puntos** (suave, media, firme; paquetes ``0x60``/``0x61``)
  en Active Braille, Active Star, Actilino, Activator y myBraille. Si no hay
  ajuste guardado, se respeta y se guarda la firmeza que tenga la línea.
- **ATC** (lectura táctil activa, paquete ``0x50``) en Modular Evolution,
  Active Braille, Active Star, Actilino, Activator y myBraille: la línea
  informa de la celda que se está leyendo (paquete ``0x55``) y, cuando se lee
  la última celda con contenido de la ventana, Tiresias avanza la línea solo
  (una vez por contenido mostrado; se ignoran las lecturas de los 0,25 s
  siguientes a escribir las celdas, que pueden ser falsas).
- **Modo de escritura braille**: se guarda al cambiarlo con su orden y se
  restaura al conectar.

Enrutamiento en líneas de más de 96 celdas (Basic Braille 160): con un byte
por tecla solo caben los códigos 0x20 a 0x7F; para el resto se acepta el
paquete extendido de tecla con el código en 16 bits (byte alto primero, bit 15
= soltar). Ese formato no está verificado con una línea real.

Teclas (gestos ``br(handyTech):...``): ``b1``...``b8`` (teclado braille, de
izquierda a derecha), ``leftSpace``, ``rightSpace``, ``left``/``right`` (Easy
Braille, Braille Wave), ``leftTakTop``, ``leftTakBottom``, ``rightTakTop``,
``rightTakBottom`` (teclas de triple acción), ``joystickUp``/``Down``/
``Left``/``Right``/``Action``, ``escape``, ``return``, ``statusRouting1``...
``statusRouting4`` (Modular), teclado numérico de las Modular y Braille Star
80 (``n0``...``n9``, ``b9``...``b14``) y ``routing``/``multiRouting``.

Modo de escritura braille: al pulsar espacio+B1+B3+B4 (espacio+puntos 1-2-7)
las teclas B pasan a ser puntos (``dot1``...``dot8``) y las barras
espaciadoras ``space``, para escribir en braille; la misma combinación lo
desactiva (orden propia del controlador ``toggleBrailleInput``, que se puede
reasignar en «Gestos de entrada»).
"""

from __future__ import annotations

import datetime
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable

from ... import queue_handler
from ...baseobject import script
from ...i18n import _
from ...log import getLogger
from . import hwio
from .base import DeviceMatch, DisplayNotFound, DriverSetting, HardwareDriver, getDriverSetting

log = getLogger("braille.handyTech")

BAUD_RATE = 19200

# ------------------------------------------------------------------ paquetes
PKT_BRAILLE = 0x01
PKT_EXTENDED = 0x79
PKT_NAK = 0x7D
PKT_ACK = 0x7E
PKT_OK_WITH_LENGTH = 0xFD
PKT_OK = 0xFE
PKT_RESET = 0xFF
EXT_TERMINATOR = 0x16
#: Longitud máxima de los paquetes extendidos que envía la línea (los mayores
#: se consideran basura y se resincroniza en vez de esperar más bytes).
MAX_EXT_LENGTH = 64

EXT_BRAILLE = 0x01
EXT_KEY = 0x04
EXT_CONFIRMATION = 0x07
EXT_SET_RTC = 0x44
EXT_GET_RTC = 0x45
EXT_SET_ATC_MODE = 0x50
EXT_ATC_INFO = 0x52
EXT_READING_POSITION = 0x55
EXT_SET_FIRMNESS = 0x60
EXT_GET_FIRMNESS = 0x61
EXT_PROTOCOL_PROPERTIES = 0xC1
EXT_NO_RECONNECT = 0xAE

#: Bit de «tecla soltada» en los códigos de tecla.
KEY_RELEASE = 0x80
#: Bit de «tecla soltada» en los códigos de tecla de 16 bits.
KEY_RELEASE_WIDE = 0x8000
#: Primer código de las teclas de enrutamiento.
KEY_ROUTING = 0x20
#: Celdas que caben en los códigos de tecla de un byte (0x20 a 0x7F).
MAX_BYTE_ROUTING = KEY_RELEASE - KEY_ROUTING

# ----------------------------------------------------------------------- HID
HID_REPORT_OUT_DATA = 0x01  # informe de entrada: datos de la línea
HID_REPORT_IN_DATA = 0x02  # informe de salida: datos para la línea
HID_REPORT_COMMAND = 0xFB  # orden para el adaptador HID-serie
HID_CMD_FLUSH = 0x01  # vaciar los búferes (abre el canal serie)
#: Tamaño de informe de salida si el dispositivo no lo indica.
HID_DEFAULT_REPORT_SIZE = 64

#: Adaptadores HID-serie (el cable USB y dos líneas con el adaptador integrado).
HID_CONVERTER_IDS = frozenset(
	{
		"VID_1FE4&PID_0003",  # cable adaptador USB-HID
		"VID_1FE4&PID_0074",  # Braille Star 40
		"VID_1FE4&PID_0044",  # Easy Braille
	}
)

#: Modelos con procesador HID propio.
HID_NATIVE_IDS = frozenset(
	{
		"VID_1FE4&PID_0054",  # Active Braille
		"VID_1FE4&PID_0055",  # Connect Braille
		"VID_1FE4&PID_0061",  # Actilino
		"VID_1FE4&PID_0064",  # Active Star 40
		"VID_1FE4&PID_0081",  # Basic Braille 16
		"VID_1FE4&PID_0082",  # Basic Braille 20
		"VID_1FE4&PID_0083",  # Basic Braille 32
		"VID_1FE4&PID_0084",  # Basic Braille 40
		"VID_1FE4&PID_008A",  # Basic Braille 48
		"VID_1FE4&PID_0086",  # Basic Braille 64
		"VID_1FE4&PID_0087",  # Basic Braille 80
		"VID_1FE4&PID_008B",  # Basic Braille 160
		"VID_1FE4&PID_008C",  # Basic Braille 84
		"VID_1FE4&PID_0093",  # Basic Braille Plus 32
		"VID_1FE4&PID_0094",  # Basic Braille Plus 40
		"VID_1FE4&PID_00A4",  # Activator
		"VID_1FE4&PID_00A6",  # Activator Pro 64
		"VID_1FE4&PID_00A8",  # Activator Pro 80
		"VID_1FE4&PID_00B2",  # myBraille 24
		"VID_1FE4&PID_00B4",  # myBraille 40
		"VID_1FE4&PID_00B6",  # myBraille 64
		"VID_1FE4&PID_00B8",  # myBraille 80
	}
)

#: Chips USB-serie de los cables de Handy Tech (genéricos: los usan otros aparatos).
SERIAL_IDS = frozenset(
	{
		"VID_0403&PID_6001",  # FTDI
		"VID_0921&PID_1200",  # GoHubs
	}
)

# ---------------------------------------------------------------------- teclas
KEY_B1, KEY_B2, KEY_B3, KEY_B4 = 0x03, 0x07, 0x0B, 0x0F
KEY_B5, KEY_B6, KEY_B7, KEY_B8 = 0x13, 0x17, 0x1B, 0x1F
KEY_LEFT_SPACE = 0x10
KEY_RIGHT_SPACE = 0x18

#: Teclas B -> punto braille (B1 y B8 son los puntos 7 y 8; B4 y B5, los centrales, 1 y 4).
B_KEY_DOTS = {KEY_B4: 1, KEY_B3: 2, KEY_B2: 3, KEY_B5: 4, KEY_B6: 5, KEY_B7: 6, KEY_B1: 7, KEY_B8: 8}

#: Teclas que tienen todas las líneas (o casi): teclado braille, espacios y el
#: teclado numérico de las Modular / Braille Star 80 (los modelos sin él
#: simplemente no envían esos códigos).
BASE_KEYS = {
	KEY_B1: "b1",
	KEY_B2: "b2",
	KEY_B3: "b3",
	KEY_B4: "b4",
	KEY_B5: "b5",
	KEY_B6: "b6",
	KEY_B7: "b7",
	KEY_B8: "b8",
	KEY_LEFT_SPACE: "leftSpace",
	KEY_RIGHT_SPACE: "rightSpace",
	# Teclado numérico: 4 filas (b9 7 8 9 / b10 4 5 6 / b11 1 2 3 / b12 b13 0 b14).
	0x12: "b9",
	0x16: "n7",
	0x1A: "n8",
	0x1E: "n9",
	0x02: "b10",
	0x06: "n4",
	0x0A: "n5",
	0x0E: "n6",
	0x11: "b11",
	0x15: "n1",
	0x19: "n2",
	0x1D: "n3",
	0x01: "b12",
	0x09: "b13",
	0x05: "n0",
	0x0D: "b14",
}
#: Teclas de triple acción, a ambos lados de las celdas (el centro = arriba+abajo).
TAK_KEYS = {0x0C: "leftTakTop", 0x14: "leftTakBottom", 0x04: "rightTakTop", 0x08: "rightTakBottom"}
#: Teclas izquierda/derecha de Easy Braille y Braille Wave.
LEFT_RIGHT_KEYS = {0x04: "left", 0x08: "right"}
#: Braille Wave: Escape, Intro y una sola barra espaciadora.
WAVE_KEYS = {0x0C: "escape", 0x14: "return", KEY_LEFT_SPACE: "space"}
JOYSTICK_KEYS = {0x74: "joystickLeft", 0x75: "joystickRight", 0x76: "joystickUp", 0x77: "joystickDown", 0x78: "joystickAction"}
STATUS_KEYS = {0x70: "statusRouting1", 0x71: "statusRouting2", 0x72: "statusRouting3", 0x73: "statusRouting4"}
ESCAPE_RETURN_KEYS = {0x7A: "escape", 0x7B: "return"}


@dataclass(frozen=True)
class ModelInfo:
	"""Características de un modelo de Handy Tech."""

	#: Nombre del aparato (p. ej. «Basic Braille 40»).
	name: str
	#: Serie, sin espacios: aparece en los gestos ``br(handyTech.<serie>):...``.
	series: str
	cells: int
	keys: dict[int, str]
	#: Protocolo antiguo (celdas con ``0x01`` y teclas de un byte).
	oldProtocol: bool = False
	#: Celdas de estado a la izquierda (se envían en blanco).
	statusCells: int = 0
	#: Lectura táctil activa (ATC): informa de la celda que se está leyendo.
	atc: bool = False
	#: Reloj interno que se puede sincronizar con el del ordenador.
	clock: bool = False
	#: Firmeza de los puntos regulable (los mismos modelos que tienen reloj).
	firmness: bool = False
	#: ActiveSplit: hay que pedirle que no se reconecte al cambiar de longitud.
	activeSplit: bool = False
	#: Códigos que hacen de barra espaciadora en el modo de escritura.
	spaceCodes: frozenset[int] = field(default=frozenset({KEY_LEFT_SPACE, KEY_RIGHT_SPACE}))


def _keys(*extra: dict[int, str]) -> dict[int, str]:
	out = dict(BASE_KEYS)
	for part in extra:
		out.update(part)
	return out


def _buildModels() -> dict[int, ModelInfo]:
	m: dict[int, ModelInfo] = {}

	def add(modelId: int, name: str, series: str, cells: int, keys: dict[int, str], **kw) -> None:
		if kw.get("clock"):
			kw.setdefault("firmness", True)
		m[modelId] = ModelInfo(name, series, cells, keys, **kw)

	tak = _keys(TAK_KEYS)
	add(0x05, "Braille Wave", "BrailleWave", 40, _keys(LEFT_RIGHT_KEYS, WAVE_KEYS), oldProtocol=True)
	add(0x44, "Easy Braille", "EasyBraille", 40, _keys(LEFT_RIGHT_KEYS), oldProtocol=True, spaceCodes=frozenset({0x04, 0x08}))
	add(0x72, "Braillino", "Braillino", 20, tak, oldProtocol=True)
	for modelId, cells in ((0x80, 20), (0x89, 40), (0x88, 80)):
		add(modelId, f"Modular {cells}", "Modular", cells, _keys(TAK_KEYS, STATUS_KEYS), oldProtocol=True, statusCells=4)
	add(0x36, "Modular Evolution 64", "ModularEvolution", 64, tak, atc=True)
	add(0x38, "Modular Evolution 88", "ModularEvolution", 88, tak, atc=True)
	add(0x3A, "Modular Connect 88", "ModularConnect", 88, tak)
	add(0x74, "Braille Star 40", "BrailleStar", 40, tak)
	add(0x78, "Braille Star 80", "BrailleStar", 80, tak)
	add(0x54, "Active Braille", "ActiveBraille", 40, _keys(TAK_KEYS, JOYSTICK_KEYS), atc=True, clock=True)
	add(0x55, "Connect Braille", "ConnectBraille", 40, tak)
	add(0x61, "Actilino", "Actilino", 16, _keys(TAK_KEYS, JOYSTICK_KEYS), atc=True, clock=True)
	add(0x64, "Active Star 40", "ActiveStar", 40, tak, atc=True, clock=True)
	for modelId, cells in ((0x81, 16), (0x82, 20), (0x83, 32), (0x84, 40), (0x8A, 48), (0x86, 64), (0x87, 80), (0x8B, 160), (0x8C, 84)):
		add(modelId, f"Basic Braille {cells}", "BasicBraille", cells, _keys())
	for modelId, cells in ((0x93, 32), (0x94, 40)):
		add(modelId, f"Basic Braille Plus {cells}", "BasicBraillePlus", cells, tak)
	split = {"atc": True, "clock": True, "activeSplit": True}
	add(0xA4, "Activator", "Activator", 40, _keys(TAK_KEYS, JOYSTICK_KEYS, ESCAPE_RETURN_KEYS), **split)
	for modelId, cells in ((0xA6, 64), (0xA8, 80)):
		add(modelId, f"Activator Pro {cells}", "ActivatorPro", cells, _keys(TAK_KEYS, ESCAPE_RETURN_KEYS), **split)
	for modelId, cells in ((0xB2, 24), (0xB4, 40), (0xB6, 64), (0xB8, 80)):
		add(modelId, f"myBraille {cells}", "myBraille", cells, _keys(TAK_KEYS, JOYSTICK_KEYS, ESCAPE_RETURN_KEYS), **split)
	return m


#: Identificador de modelo (lo que contesta la línea al reinicio) -> características.
MODELS: dict[int, ModelInfo] = _buildModels()

# ---------------------------------------------------------------- mapa de gestos
#: Punto braille -> tecla B (para escribir las combinaciones con las teclas B).
_B_FOR_DOT = {dot: BASE_KEYS[code] for code, dot in B_KEY_DOTS.items()}

#: Espacio + puntos (modo de escritura braille), igual que en el resto de líneas.
_SPACE_DOT_COMMANDS = {
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
}


def _commandModeVariants(spaceNames: Iterable[str]) -> dict[str, str]:
	"""Las mismas combinaciones físicas fuera del modo de escritura.

	Fuera del modo de escritura las teclas se llaman ``b1``...``b8`` y las
	barras ``leftSpace``/``rightSpace``; así la misma combinación hace lo mismo
	en los dos modos.
	"""
	out: dict[str, str] = {}
	for keys, target in _SPACE_DOT_COMMANDS.items():
		dots = [int(k[3:]) for k in keys.split("+")[1:]]
		for space in spaceNames:
			out["+".join([space] + [_B_FOR_DOT[d] for d in dots])] = target
	return out


GESTURE_MAP: dict[str, str] = {
	# Enrutamiento.
	"routing": "braille_routeTo",
	"multiRouting": "braille_selectRange",
	"leftSpace+routing": "braille_reportFormatting",
	"rightSpace+routing": "braille_reportFormatting",
	"space+routing": "braille_reportFormatting",
	# Desplazamiento.
	"leftSpace": "braille_scrollBack",
	"rightSpace": "braille_scrollForward",
	"left": "braille_scrollBack",
	"right": "braille_scrollForward",
	"leftTakTop": "braille_scrollBack",
	"leftTakBottom": "braille_scrollForward",
	"rightTakTop": "braille_previousLine",
	"rightTakBottom": "braille_nextLine",
	"leftTakTop+leftTakBottom": "kb:shift+tab",
	"rightTakTop+rightTakBottom": "kb:tab",
	"leftTakTop+leftTakBottom+rightTakTop+rightTakBottom": "kb:enter",
	# Teclas B (fuera del modo de escritura).
	"b1": "kb:escape",
	"b2": "braille_toggleTether",
	"b3": "braille_scrollBack",
	"b4": "braille_previousLine",
	"b5": "braille_nextLine",
	"b6": "braille_scrollForward",
	"b7": "braille_toFocus",
	"b8": "kb:enter",
	"b4+b5": "reportCurrentFocus",
	"b3+b6": "braille_reportFormatting",
	# Palanca de mando.
	"joystickUp": "kb:upArrow",
	"joystickDown": "kb:downArrow",
	"joystickLeft": "kb:leftArrow",
	"joystickRight": "kb:rightArrow",
	"joystickAction": "kb:enter",
	# Escape e Intro (Braille Wave, Activator, myBraille).
	"escape": "kb:escape",
	"return": "kb:enter",
	# Teclas de las celdas de estado (Modular).
	"statusRouting1": "braille_toggleTether",
	"statusRouting2": "braille_toFocus",
	"statusRouting3": "title",
	"statusRouting4": "reportStatusLine",
	# Teclado numérico (Modular, Braille Star 80).
	**{f"n{i}": f"kb:{i}" for i in range(10)},
	"b9": "kb:pageUp",
	"b10": "kb:pageDown",
	"b11": "kb:tab",
	"b12": "kb:escape",
	"b13": "kb:backspace",
	"b14": "kb:enter",
	# Espacio + puntos (modo de escritura) y lo mismo con las teclas B.
	**_SPACE_DOT_COMMANDS,
	**_commandModeVariants(("leftSpace", "rightSpace")),
}

#: Easy Braille no tiene barras espaciadoras: hacen de espacio sus teclas
#: izquierda y derecha; Braille Wave tiene una sola barra (``space``).
MODEL_GESTURE_MAPS: dict[str, dict[str, str]] = {
	"EasyBraille": _commandModeVariants(("left", "right")),
	"BrailleWave": _commandModeVariants(("space",)),
}

#: Combinación (en puntos) que activa o desactiva el modo de escritura: espacio + B1+B3+B4.
#: Fuera del modo llega con el nombre de la barra (``leftSpace``, ``rightSpace``,
#: ``space`` en Braille Wave, ``left``/``right`` en Easy Braille); dentro, como
#: espacio + puntos 1-2-7.
INPUT_TOGGLE_GESTURES = tuple(
	f"br(handyTech):{space}+b1+b3+b4" for space in ("leftSpace", "rightSpace", "space", "left", "right")
) + ("br(handyTech):space+dot1+dot2+dot7",)


class HandyTechDriver(HardwareDriver):
	name = "handyTech"
	description = _(
		"Handy Tech: Active Braille, Active Star, Actilino, Activator, Basic Braille (Plus), Braille Star, "
		"Braillino, Braille Wave, Connect Braille, Easy Braille, Modular (Evolution, Connect), myBraille"
	)
	usbHidIds = HID_NATIVE_IDS | HID_CONVERTER_IDS
	usbSerialIds = SERIAL_IDS
	genericUsbIds = SERIAL_IDS
	bluetoothPrefixes = (
		"Actilino AL",
		"Active Braille AB",
		"Active Star AS",
		"Basic Braille BB",
		"Basic Braille Plus BP",
		"Braille Star 40 BS",
		"Braillino BL",
		"Braille Wave BW",
		"Easy Braille EBR",
		"Activator",
		"myBraille",
	)
	baudRate = BAUD_RATE
	keyOrder = (
		["leftSpace", "space", "rightSpace", "left", "right"]
		+ [f"b{i}" for i in range(1, 9)]
		+ [f"dot{i}" for i in range(1, 9)]
		+ ["leftTakTop", "leftTakBottom", "rightTakTop", "rightTakBottom"]
		+ ["joystickUp", "joystickDown", "joystickLeft", "joystickRight", "joystickAction", "escape", "return"]
		+ [f"statusRouting{i}" for i in range(1, 5)]
		+ [f"b{i}" for i in range(9, 15)]
		+ [f"n{i}" for i in range(10)]
	)
	dotKeys = {f"dot{i}": i for i in range(1, 9)}
	spaceKeys = frozenset({"space"})
	gestureMap = GESTURE_MAP
	modelGestureMaps = MODEL_GESTURE_MAPS
	keyDescriptions = {
		"b1": _("B1: primera tecla del teclado braille empezando por la izquierda (punto 7)"),
		"b2": _("B2: segunda tecla del teclado braille (punto 3)"),
		"b3": _("B3: tercera tecla del teclado braille (punto 2)"),
		"b4": _("B4: cuarta tecla, la central izquierda (punto 1)"),
		"b5": _("B5: quinta tecla, la central derecha (punto 4)"),
		"b6": _("B6: sexta tecla del teclado braille (punto 5)"),
		"b7": _("B7: séptima tecla del teclado braille (punto 6)"),
		"b8": _("B8: última tecla del teclado braille (punto 8)"),
		"leftSpace": _("barra espaciadora izquierda"),
		"rightSpace": _("barra espaciadora derecha"),
		"space": _("barra espaciadora (en el modo de escritura braille, cualquiera de ellas)"),
		"left": _("tecla izquierda (Easy Braille, Braille Wave)"),
		"right": _("tecla derecha (Easy Braille, Braille Wave)"),
		"leftTakTop": _("tecla de triple acción izquierda, parte de arriba"),
		"leftTakBottom": _("tecla de triple acción izquierda, parte de abajo"),
		"rightTakTop": _("tecla de triple acción derecha, parte de arriba"),
		"rightTakBottom": _("tecla de triple acción derecha, parte de abajo"),
		"joystickUp": _("palanca de mando hacia arriba"),
		"joystickDown": _("palanca de mando hacia abajo"),
		"joystickLeft": _("palanca de mando hacia la izquierda"),
		"joystickRight": _("palanca de mando hacia la derecha"),
		"joystickAction": _("pulsar la palanca de mando"),
		"escape": _("tecla Escape (Braille Wave, Activator, myBraille)"),
		"return": _("tecla Intro (Braille Wave, Activator, myBraille)"),
		"statusRouting1": _("tecla de la primera celda de estado (Modular)"),
		"statusRouting2": _("tecla de la segunda celda de estado (Modular)"),
		"statusRouting3": _("tecla de la tercera celda de estado (Modular)"),
		"statusRouting4": _("tecla de la cuarta celda de estado (Modular)"),
		"b9": _("teclado numérico: tecla de función de la primera fila"),
		"b10": _("teclado numérico: tecla de función de la segunda fila"),
		"b11": _("teclado numérico: tecla de función de la tercera fila"),
		"b12": _("teclado numérico: tecla de función de la última fila, a la izquierda"),
		"b13": _("teclado numérico: tecla a la izquierda del 0"),
		"b14": _("teclado numérico: tecla a la derecha del 0"),
		**{f"n{i}": _("teclado numérico: {digit}").format(digit=i) for i in range(10)},
		**{f"dot{i}": _("punto {dot} (modo de escritura braille)").format(dot=i) for i in range(1, 9)},
		"routing": _("tecla de enrutamiento sobre una celda"),
		"multiRouting": _("dos teclas de enrutamiento a la vez"),
	}

	driverSettings = (
		DriverSetting(
			"dotFirmness",
			_("Firmeza de los puntos de la Handy Tech:"),
			"choice",
			1,
			choices=((0, _("Suave")), (1, _("Media")), (2, _("Firme"))),
		),
		DriverSetting("atc", _("Activar ATC (seguimiento de la lectura) en las Handy Tech que lo admiten"), "bool", False),
		DriverSetting("brailleInput", _("Modo de escritura braille de las Handy Tech activo"), "bool", False),
	)

	#: Segundos que se espera la confirmación de unas celdas antes de enviar las siguientes.
	ackTimeout = 0.3
	#: Tras escribir celdas, el ATC puede dar lecturas falsas durante este tiempo (segundos).
	atcSettleTime = 0.25
	#: Diferencia (segundos) a partir de la que se pone en hora el reloj de la línea.
	clockTolerance = 5

	def __init__(self, *args, **kwargs) -> None:
		self._buffer = bytearray()
		self._modelId: int | None = None
		self._info: ModelInfo | None = None
		self._hid = False
		self._hidConverter = False
		self._propertiesSeen = False
		self._downNames: dict[int, object] = {}
		self._awaitingAck = False
		self._ackSince = 0.0
		self._pendingCells: tuple[bytes, list[int]] | None = None
		self._ackTimer: threading.Timer | None = None
		#: Celdas mostradas (sin las de estado) y cuándo se enviaron (para el ATC).
		self._shownCells: list[int] = []
		self._shownSince = 0.0
		self._atcScrolled = False
		#: Modo de escritura braille (las teclas B son puntos).
		self.brailleInput = False
		#: ATC activado y última celda leída (``None`` si no se sabe).
		self.atcEnabled = False
		self.readingPosition: int | None = None
		super().__init__(*args, **kwargs)

	# ------------------------------------------------------------ conexión
	def _initConnection(self, match: DeviceMatch) -> None:
		"""Decide el tipo de conexión y pide la identificación (reinicio)."""
		self._hid = match.type == "hid"
		self._hidConverter = self._hid and match.id.upper() in HID_CONVERTER_IDS
		if self._hidConverter:
			# Abre el canal serie del adaptador.
			self._write(bytes([HID_REPORT_COMMAND, HID_CMD_FLUSH]))
		self._sendPacket(bytes([PKT_RESET]))

	def _connect(self, match: DeviceMatch) -> None:
		self._resetState()
		if match.type == "serial":
			self._io = self._open(match, baudrate=BAUD_RATE, parity="O")
		elif match.type == "hid":
			self._io = self._open(match)
		else:
			raise DisplayNotFound(f"Tipo de conexión no admitido: {match.type}")
		self._initConnection(match)
		if not self._waitFor(lambda: self._modelId is not None, 2.0):
			raise DisplayNotFound("La línea Handy Tech no ha respondido al reinicio")
		if self._info is None or not self._info.oldProtocol:
			# Protocolo extendido: la línea indica sus celdas reales (ActiveSplit,
			# modelos desconocidos).
			self._propertiesSeen = False
			self._sendExtended(EXT_PROTOCOL_PROPERTIES)
			self._waitFor(lambda: self._propertiesSeen, 0.5 if self._info else 1.5)
		if self.numCells <= 0:
			raise DisplayNotFound(f"Modelo Handy Tech desconocido: {self._modelId:#04x}")
		self._postInit()

	def _postInit(self) -> None:
		info = self._info
		if info is None:
			return
		if info.activeSplit:
			# Que no se desconecte al cambiar el número de celdas.
			self._sendExtended(EXT_NO_RECONNECT)
		if info.clock:
			self._sendExtended(EXT_GET_RTC)
		self.brailleInput = bool(self.getSetting("brailleInput"))
		self._applyDeviceSettings(initial=True)

	def _applyDeviceSettings(self, initial: bool = False) -> None:
		"""Envía a la línea la firmeza de los puntos y el ATC configurados."""
		info = self._info
		if info is None:
			return
		if info.firmness:
			stored = getDriverSetting(self.name, "dotFirmness", None)
			if stored is None and initial:
				# Sin ajuste guardado se respeta el de la línea: se pregunta y se guarda.
				self._sendExtended(EXT_GET_FIRMNESS)
			else:
				self._sendExtended(EXT_SET_FIRMNESS, bytes([self._firmnessValue()]))
		if info.atc:
			wanted = bool(self.getSetting("atc"))
			if wanted or not initial:
				self.setAtc(wanted)

	def _firmnessValue(self) -> int:
		try:
			value = int(self.getSetting("dotFirmness"))
		except (TypeError, ValueError):
			return 1
		return value if 0 <= value <= 2 else 1

	def applySettings(self) -> None:
		"""Hilo del núcleo: se han cambiado los ajustes en Opciones."""
		with self._cond:
			self.brailleInput = bool(self.getSetting("brailleInput"))
			if self._io is None or self._info is None or self.numCells <= 0:
				return
			try:
				self._applyDeviceSettings()
			except hwio.IoError as e:
				log.debug("No se pudieron aplicar los ajustes a la línea Handy Tech: %s", e)

	def _resetState(self) -> None:
		self._buffer.clear()
		self._modelId = None
		self._info = None
		self._downNames.clear()
		self._awaitingAck = False
		self._pendingCells = None
		self._cancelAckTimer()
		self.readingPosition = None
		self.atcEnabled = False
		self._shownCells = []
		self._atcScrolled = False

	def _sayGoodbye(self) -> None:
		self._cancelAckTimer()
		# Algunas líneas (Easy Braille) quedan en mal estado si se cierra al
		# instante de escribir.
		time.sleep(0.1)

	# ------------------------------------------------------------ envío
	def _sendPacket(self, packet: bytes) -> None:
		if not self._hid:
			self._write(packet)
			return
		size = getattr(self._io, "outputSize", 0) or HID_DEFAULT_REPORT_SIZE
		block = max(1, size - 3)
		for pos in range(0, len(packet), block):
			chunk = packet[pos : pos + block]
			self._write(bytes([HID_REPORT_IN_DATA, len(chunk)]) + chunk + b"\x00")

	def _sendExtended(self, packetType: int, data: bytes = b"") -> None:
		if self._modelId is None:
			return
		self._sendPacket(bytes([PKT_EXTENDED, self._modelId, len(data) + 1, packetType]) + bytes(data) + bytes([EXT_TERMINATOR]))

	def _cellsPacket(self, cells: list[int]) -> bytes:
		info = self._info
		status = info.statusCells if info else 0
		data = bytes(status) + bytes(c & 0xFF for c in cells)
		if info is not None and info.oldProtocol:
			return bytes([PKT_BRAILLE]) + data
		return bytes([PKT_EXTENDED, self._modelId or 0, len(data) + 1, EXT_BRAILLE]) + data + bytes([EXT_TERMINATOR])

	def _writeCells(self, cells: list[int]) -> None:
		packet = self._cellsPacket(cells)
		with self._cond:
			if self._awaitingAck and not self._terminated and time.monotonic() - self._ackSince < self.ackTimeout:
				# La línea aún no ha confirmado las anteriores: solo cuenta la última.
				self._pendingCells = (packet, list(cells))
				self._scheduleAckTimer()
				return
			self._sendCellsNow(packet, cells)

	def _sendCellsNow(self, packet: bytes, cells: list[int]) -> None:
		self._pendingCells = None
		self._awaitingAck = True
		self._ackSince = time.monotonic()
		if cells != self._shownCells:
			self._shownCells = list(cells)
			self._atcScrolled = False
		self._shownSince = self._ackSince
		self._sendPacket(packet)

	def _flushPending(self) -> None:
		pending = self._pendingCells
		if pending is None or self._io is None:
			self._pendingCells = None
			return
		try:
			self._sendCellsNow(*pending)
		except hwio.IoError as e:
			log.debug("Error escribiendo en la línea braille: %s", e)

	def _scheduleAckTimer(self) -> None:
		if self._ackTimer is not None:
			return
		timer = threading.Timer(self.ackTimeout, self._onAckTimeout)
		timer.daemon = True
		self._ackTimer = timer
		timer.start()

	def _cancelAckTimer(self) -> None:
		timer = self._ackTimer
		self._ackTimer = None
		if timer is not None:
			timer.cancel()

	def _onAckTimeout(self) -> None:
		with self._cond:
			self._ackTimer = None
			if self._pendingCells is not None and not self._terminated:
				log.debug("La línea Handy Tech no ha confirmado las celdas; se envían las siguientes")
				self._flushPending()

	def _handleAck(self) -> None:
		self._awaitingAck = False
		self._cancelAckTimer()
		if self._pendingCells is not None:
			self._flushPending()

	# ------------------------------------------------------------ recepción
	def _handleData(self, data: bytes) -> None:
		if self._hid:
			# Informe HID: 0x01, longitud y los bytes del flujo.
			if len(data) < 2 or data[0] != HID_REPORT_OUT_DATA:
				return
			length = data[1]
			if not length:
				return
			self._buffer += data[2 : 2 + length]
		else:
			self._buffer += data
		self._processBuffer()

	def _processBuffer(self) -> None:
		buf = self._buffer
		while buf:
			first = buf[0]
			if first == PKT_OK:
				if len(buf) < 2:
					return
				self._identified(buf[1], None)
				del buf[:2]
			elif first == PKT_OK_WITH_LENGTH:
				if len(buf) < 3:
					return
				self._identified(buf[1], buf[2])
				del buf[:3]
			elif first == PKT_EXTENDED:
				if len(buf) < 3:
					return
				end = buf[2] + 4
				if 0 < buf[2] <= MAX_EXT_LENGTH and len(buf) < end:
					return
				if not 0 < buf[2] <= MAX_EXT_LENGTH or buf[end - 1] != EXT_TERMINATOR:
					# Trama corrupta: se descarta el primer byte para resincronizar.
					log.debug("Paquete extendido de Handy Tech no válido: %s", bytes(buf[:end]).hex())
					del buf[:1]
					continue
				modelId = buf[1]
				payload = bytes(buf[3 : end - 1])
				del buf[:end]
				self._handleExtended(modelId, payload)
			elif first == PKT_ACK:
				del buf[:1]
				self._handleAck()
			elif first == PKT_NAK:
				del buf[:1]
				log.debug("La línea Handy Tech ha rechazado un paquete (NAK)")
				self._handleAck()
			else:
				del buf[:1]
				if self._info is not None and self._info.oldProtocol and (first & 0x7F) < PKT_EXTENDED:
					self._handleKey(first)

	def _identified(self, modelId: int, cells: int | None) -> None:
		"""Respuesta al reinicio: ``0xFE <modelo>`` o ``0xFD <modelo> <celdas>``."""
		if self._modelId is not None and self.numCells > 0:
			if modelId != self._modelId:
				# Otra línea en el mismo puerto: se reconecta para identificarla.
				log.info("La línea Handy Tech ha cambiado de modelo (%#04x -> %#04x)", self._modelId, modelId)
				self._onIoError(0)
			return
		info = MODELS.get(modelId)
		self._modelId = modelId
		self._info = info
		if info is not None:
			self.model = info.series
			self.deviceName = f"Handy Tech {info.name}"
			self.numCells = cells or info.cells
		else:
			log.info("Modelo Handy Tech desconocido: %#04x", modelId)
			self.model = f"HandyTech{modelId:02X}"
			self.deviceName = _("Handy Tech (modelo {id})").format(id=f"{modelId:#04x}")
			if cells:
				self.numCells = cells

	def _handleExtended(self, modelId: int, payload: bytes) -> None:
		if self._modelId is not None and modelId != self._modelId:
			log.debug("Paquete de otro modelo (%#04x) ignorado", modelId)
			return
		kind = payload[0]
		if kind == EXT_KEY and len(payload) >= 3 and self.numCells > MAX_BYTE_ROUTING:
			# Líneas de más de 96 celdas: código de tecla de 16 bits (ver _handleKey).
			self._handleKey(payload[1] << 8 | payload[2], wide=True)
		elif kind == EXT_KEY and len(payload) >= 2:
			self._handleKey(payload[1])
		elif kind == EXT_CONFIRMATION:
			if payload[1:2] == bytes([PKT_NAK]):
				log.debug("La línea Handy Tech ha rechazado un paquete (NAK)")
			self._handleAck()
		elif kind == EXT_PROTOCOL_PROPERTIES:
			if len(payload) >= 4 and payload[3] > 0:
				self.numCells = payload[3]
			self._propertiesSeen = True
		elif kind == EXT_GET_RTC:
			self._handleClock(payload[1:])
		elif kind == EXT_READING_POSITION:
			if len(payload) >= 2:
				self._handleReadingPosition(payload[1])
		elif kind == EXT_GET_FIRMNESS:
			if len(payload) >= 2 and 0 <= payload[1] <= 2:
				# Firmeza actual de la línea: se guarda para que Opciones la muestre.
				self.setSetting("dotFirmness", payload[1])
		elif kind == EXT_ATC_INFO:
			pass
		else:
			log.debug("Paquete extendido de Handy Tech sin tratar: %s", payload.hex())

	# ------------------------------------------------------------ reloj y ATC
	def _now(self) -> datetime.datetime:
		return datetime.datetime.now()

	def _handleClock(self, data: bytes) -> None:
		"""Hora de la línea: si se ha desviado, se pone la del ordenador."""
		if len(data) < 7:
			return
		try:
			shown = datetime.datetime(data[0] << 8 | data[1], data[2], data[3], data[4], data[5], data[6])
		except ValueError:
			shown = None
		now = self._now()
		if shown is not None and abs((shown - now).total_seconds()) < self.clockTolerance:
			return
		# Al poner la hora, el año va con el byte bajo primero.
		self._sendExtended(EXT_SET_RTC, bytes([now.year & 0xFF, now.year >> 8, now.month, now.day, now.hour, now.minute, now.second]))

	def _handleReadingPosition(self, pos: int) -> None:
		"""Celda que se está leyendo (ATC).

		Si se lee la última celda con contenido de la ventana mostrada, la
		línea avanza sola (en el hilo del núcleo, sin interrumpir la voz), una
		vez por cada contenido mostrado. Justo después de escribir celdas el ATC
		puede dar lecturas falsas, así que durante ``atcSettleTime`` se ignoran.
		"""
		if pos >= self.numCells:
			self.readingPosition = None
			return
		self.readingPosition = pos
		if not self.atcEnabled or self._atcScrolled:
			return
		if time.monotonic() - self._shownSince < self.atcSettleTime:
			return
		last = max((i for i, c in enumerate(self._shownCells) if c), default=-1)
		if last >= 0 and pos >= last:
			self._atcScrolled = True
			queue_handler.queueFunction(self._atcScrollForward)

	def _atcScrollForward(self) -> None:
		"""Hilo del núcleo: avance automático al terminar de leer la ventana."""
		from .. import handler

		if self.connected and not self._terminated:
			handler.scrollForward(auto=True)

	def setAtc(self, enabled: bool) -> bool:
		"""Activa o desactiva la lectura táctil activa (ATC). Devuelve si el modelo la admite."""
		if self._info is None or not self._info.atc:
			return False
		self._sendExtended(EXT_SET_ATC_MODE, bytes([1 if enabled else 0]))
		self.atcEnabled = enabled
		if not enabled:
			self.readingPosition = None
		return True

	# ------------------------------------------------------------ teclas
	def _keyName(self, code: int):
		info = self._info
		if KEY_ROUTING <= code < KEY_ROUTING + self.numCells:
			return ("routing", code - KEY_ROUTING)
		spaceCodes = info.spaceCodes if info else frozenset({KEY_LEFT_SPACE, KEY_RIGHT_SPACE})
		if self.brailleInput:
			if code in B_KEY_DOTS:
				return f"dot{B_KEY_DOTS[code]}"
			if code in spaceCodes:
				return "space"
		keys = info.keys if info else _keys(TAK_KEYS)
		return keys.get(code)

	def _handleKey(self, raw: int, wide: bool = False) -> None:
		"""Pulsación o liberación de una tecla.

		Normalmente el código ocupa un byte (bit 7 = soltar), lo que limita el
		enrutamiento a 96 celdas (0x20 a 0x7F). En las líneas de más celdas
		(Basic Braille 160) se acepta un paquete de tecla con el código en 16
		bits, byte alto primero (bit 15 = soltar), con la misma numeración:
		enrutamiento = 0x20 + celda.
		"""
		release = raw & (KEY_RELEASE_WIDE if wide else KEY_RELEASE)
		code = raw & ((KEY_RELEASE_WIDE - 1) if wide else (KEY_RELEASE - 1))
		if not code:
			return
		if release:
			name = self._downNames.pop(code, None)
			if name is None:
				name = self._keyName(code)
			if name is not None:
				self._keyReleased(name)
			return
		name = self._keyName(code)
		if name is None:
			log.debug("Tecla de Handy Tech desconocida: %#04x", code)
			return
		self._downNames[code] = name
		self._keyPressed(name)

	@script(
		description=_("Activa o desactiva la escritura braille con el teclado de la línea Handy Tech (las teclas B pasan a ser puntos y las barras, espacio)"),
		category=_("Braille"),
		gestures=INPUT_TOGGLE_GESTURES,
	)
	def script_toggleBrailleInput(self, gesture) -> None:
		self.brailleInput = not self.brailleInput
		self.setSetting("brailleInput", self.brailleInput)
		queue_handler.queueFunction(self._reportInputMode, self.brailleInput)

	@staticmethod
	def _reportInputMode(enabled: bool) -> None:
		from ... import speech

		speech.speakMessage(_("Escritura braille activada") if enabled else _("Escritura braille desactivada"))


BrailleDisplayDriver = HandyTechDriver
