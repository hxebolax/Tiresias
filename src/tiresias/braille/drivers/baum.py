"""Líneas braille con el protocolo Baum.

Lo usan las líneas de Baum (VarioPro, Pronto!, SuperVario y SuperVario2,
Conny, PocketVario, VarioConnect/BrailleConnect, EcoVario, VarioUltra,
Vario 340 y Vario 4), la HumanWare Brailliant2 (que habla Baum), la APH
Refreshabraille, las Orbit Reader 20 y 40 y la NLS eReader de Zoomax (una
variante con otra forma de activar el protocolo).

Formato de los mensajes
-----------------------
- **USB HID**: cada informe es ``comando`` + ``argumentos`` (el id de
  informe es el propio comando); no hay escapes.
- **Serie** (USB serie y Bluetooth, 19200 baudios, 8N1): cada trama es
  ``ESC`` (0x1B) + ``comando`` + ``argumentos``; un 0x1B dentro de los
  argumentos se envía duplicado. El flujo llega en trozos arbitrarios, así
  que se acumula en un búfer y se extraen las tramas completas; un ``ESC``
  suelto en mitad de una trama indica que la anterior se ha cortado y se
  vuelve a sincronizar.

Comandos que se usan:

- ``0x01`` hacia la línea: celdas; desde la línea: número de celdas (1 byte).
- ``0x02`` petición de información (la línea responde con id, número de
  serie y celdas).
- ``0x15`` activar (1) o desactivar (0) el protocolo. La NLS eReader Zoomax
  se activa con el parámetro 3 y se le pide que repita su estado con ``0x08``.
- ``0x16`` canal de comunicación y ``0x17`` aviso de apagado (1 byte).
- ``0x22`` teclas de enrutamiento: máscara de bits de 5 bytes (hasta 40
  celdas) o de 10 (más de 40).
- ``0x24`` teclas de pantalla d1-d6 (1 byte).
- ``0x27`` una tecla de enrutamiento (número desde 1; 0 = suelta).
- ``0x33`` teclado braille (2 bytes, el primero es el menos significativo):
  b9, b10, b11, -, c1-c4 y luego b1-b8.
- ``0x34`` joystick (1 byte): arriba, izquierda, abajo, derecha, pulsar.
- ``0x84`` identificación del aparato (16 bytes; 18 en la Refreshabraille,
  cuyos 16 primeros son ``"Refreshabraille "``).
- ``0x8A`` número de serie (8 bytes).

Modelos antiguos (Inka, DM80P, Vario de primera generación). Estas tramas
no están en la referencia de NVDA; su formato sigue el controlador Baum de
BRLTTY tal como se recuerda, y la interpretación es la más probable:

- ``0x20`` sensores horizontales: máscara de bits como ``0x22`` (segunda fila
  de enrutamiento, ``routing2``); ``0x25`` un sensor horizontal (desde 1).
- ``0x21`` sensores verticales: máscara de 4 bytes (``verticalSensorN``);
  ``0x26`` un sensor vertical (número en los 6 bits bajos).
- ``0x28``/``0x29`` 6 teclas delanteras/traseras (1 byte); ``0x2C``/``0x2D``
  10 teclas delanteras/traseras (2 bytes); ``0x2B`` teclas de órdenes (1 byte).
- ``0x05`` versión, ``0x23`` interruptores, ``0x40`` código de error (1 byte),
  ``0x11`` modo (2 bytes), ``0x8C`` nombre Bluetooth (14 bytes): se leen para
  no perder la sincronía, pero no producen gestos.

Módulos de la VarioPro (``0x50`` registro, ``0x51`` registros de datos,
``0x52`` registros de servicio). Interpretación probable, sin verificar con
hardware: tras el comando va un byte con la longitud del resto; luego el
identificador del módulo (2 bytes, el menos significativo primero) y su
número de serie (2 bytes).

- ``0x50``: ``id, serie, suceso`` (1 alta, 2 baja, 3 reconexión). Se
  confirma con ``0x50 05 id serie 01``.
- ``0x51``: ``id, serie, orden, inicio, cantidad, registros``. El primer
  registro son indicadores de cambio (bit 0 ruedas, 1 botones, 2 teclas,
  3 sensores). Módulo de pantalla (byte alto del id 0x41): 4 ruedas (bytes
  con signo: pasos), botones (pulsar cada rueda), teclas d1-d6 y sensores de
  enrutamiento. Módulo de estado (0x42): botones ``statusKey1``...``4``.
  Con un módulo de pantalla registrado, las celdas se escriben con
  ``0x51 len id serie 00 00 n celdas``.

Nombres de las teclas (gestos ``br(baum):...``): ``d1``...``d6`` (teclas de
pantalla), ``b1``...``b8`` (puntos), ``b9`` y ``b10`` (barras espaciadoras),
``b11``, ``c1``...``c4`` (teclas de órdenes), ``up``, ``down``, ``left``,
``right`` y ``select`` (joystick), ``routing`` y ``multiRouting``,
``routing2`` y ``multiRouting2`` (sensores horizontales), ``front1``...
``front10``, ``back1``...``back10``, ``command1``...``command8``,
``verticalSensor1``...``verticalSensor32``, ``wheel1Up``/``Down``/``Press``
... ``wheel4...`` y ``statusKey1``...``statusKey4``.
"""

from __future__ import annotations

from typing import Any

from ...i18n import _
from ...log import getLogger
from . import hwio
from .base import DeviceMatch, DisplayNotFound, HardwareDriver

log = getLogger("braille.baum")

ESC = 0x1B

CMD_DISPLAY_DATA = 0x01
CMD_CELL_COUNT = 0x01
CMD_REQUEST_INFO = 0x02
CMD_REPEAT_ALL = 0x08
CMD_PROTOCOL_ONOFF = 0x15
CMD_COMMUNICATION_CHANNEL = 0x16
CMD_POWERDOWN = 0x17
CMD_ROUTING_KEYS = 0x22
CMD_DISPLAY_KEYS = 0x24
CMD_ROUTING_KEY = 0x27
CMD_BRAILLE_KEYS = 0x33
CMD_JOYSTICK_KEYS = 0x34
CMD_DEVICE_ID = 0x84
CMD_SERIAL_NUMBER = 0x8A
# Modelos antiguos (interpretación según BRLTTY, sin verificar).
CMD_VERSION = 0x05
CMD_MODE_SETTING = 0x11
CMD_HORIZONTAL_SENSORS = 0x20
CMD_VERTICAL_SENSORS = 0x21
CMD_SWITCHES = 0x23
CMD_HORIZONTAL_SENSOR = 0x25
CMD_VERTICAL_SENSOR = 0x26
CMD_FRONT_KEYS6 = 0x28
CMD_BACK_KEYS6 = 0x29
CMD_COMMAND_KEYS = 0x2B
CMD_FRONT_KEYS10 = 0x2C
CMD_BACK_KEYS10 = 0x2D
CMD_ERROR_CODE = 0x40
CMD_BLUETOOTH_NAME = 0x8C
# Módulos de la VarioPro (tramas con su propia longitud).
CMD_MODULE_REGISTRATION = 0x50
CMD_DATA_REGISTERS = 0x51
CMD_SERVICE_REGISTERS = 0x52
MODULE_COMMANDS = frozenset({CMD_MODULE_REGISTRATION, CMD_DATA_REGISTERS, CMD_SERVICE_REGISTERS})

#: Parámetro de ``0x15`` con el que se activa la NLS eReader Zoomax.
ZOOMAX_PROTOCOL = 0x03

#: Longitud de los argumentos de las respuestas de longitud fija.
RESPONSE_LENGTHS = {
	CMD_CELL_COUNT: 1,
	CMD_COMMUNICATION_CHANNEL: 1,
	CMD_POWERDOWN: 1,
	CMD_DISPLAY_KEYS: 1,
	CMD_ROUTING_KEY: 1,
	CMD_BRAILLE_KEYS: 2,
	CMD_JOYSTICK_KEYS: 1,
	CMD_DEVICE_ID: 16,
	CMD_SERIAL_NUMBER: 8,
	CMD_VERSION: 1,
	CMD_MODE_SETTING: 2,
	CMD_VERTICAL_SENSORS: 4,
	CMD_SWITCHES: 1,
	CMD_HORIZONTAL_SENSOR: 1,
	CMD_VERTICAL_SENSOR: 1,
	CMD_FRONT_KEYS6: 1,
	CMD_BACK_KEYS6: 1,
	CMD_COMMAND_KEYS: 1,
	CMD_FRONT_KEYS10: 2,
	CMD_BACK_KEYS10: 2,
	CMD_ERROR_CODE: 1,
	CMD_BLUETOOTH_NAME: 14,
}

#: Registro de módulos: sucesos y orden de confirmación (interpretación probable).
MODULE_EVENT_REMOVAL = 2
MODULE_ACKNOWLEDGE = 0x01
#: Orden de escritura de los registros de datos.
DATA_REGISTERS_WRITE = 0x00
#: Tipo de módulo (byte alto del identificador).
MODULE_TYPE_DISPLAY = 0x41
MODULE_TYPE_STATUS = 0x42
#: Indicadores de cambio del primer registro de datos.
DRF_WHEELS = 0x01
DRF_BUTTONS = 0x02
DRF_KEYS = 0x04
DRF_SENSORS = 0x08
#: Pasos de rueda que se atienden como mucho en un informe.
MAX_WHEEL_STEPS = 10

#: La Refreshabraille manda 18 bytes de identificación en vez de 16.
REFRESHABRAILLE_ID = b"Refreshabraille "
REFRESHABRAILLE_ID_LENGTH = 18

#: Bit -> nombre de tecla de cada grupo (``None``: bit sin tecla).
DISPLAY_KEY_BITS = ("d1", "d2", "d3", "d4", "d5", "d6")
BRAILLE_KEY_BITS = (
	# Primer byte.
	"b9", "b10", "b11", None, "c1", "c2", "c3", "c4",
	# Segundo byte.
	"b1", "b2", "b3", "b4", "b5", "b6", "b7", "b8",
)
JOYSTICK_KEY_BITS = ("up", "left", "down", "right", "select")
FRONT_KEY_BITS = tuple(f"front{i}" for i in range(1, 11))
BACK_KEY_BITS = tuple(f"back{i}" for i in range(1, 11))
COMMAND_KEY_BITS = tuple(f"command{i}" for i in range(1, 9))
VERTICAL_SENSOR_BITS = tuple(f"verticalSensor{i}" for i in range(1, 33))
WHEEL_COUNT = 4
WHEEL_PRESS_BITS = tuple(f"wheel{i}Press" for i in range(1, WHEEL_COUNT + 1))
WHEEL_STEP_KEYS = tuple(f"wheel{i}{d}" for i in range(1, WHEEL_COUNT + 1) for d in ("Up", "Down"))
STATUS_KEY_BITS = tuple(f"statusKey{i}" for i in range(1, 5))
KEY_BITS = {
	CMD_DISPLAY_KEYS: DISPLAY_KEY_BITS,
	CMD_BRAILLE_KEYS: BRAILLE_KEY_BITS,
	CMD_JOYSTICK_KEYS: JOYSTICK_KEY_BITS,
	CMD_FRONT_KEYS6: FRONT_KEY_BITS[:6],
	CMD_FRONT_KEYS10: FRONT_KEY_BITS,
	CMD_BACK_KEYS6: BACK_KEY_BITS[:6],
	CMD_BACK_KEYS10: BACK_KEY_BITS,
	CMD_COMMAND_KEYS: COMMAND_KEY_BITS,
	CMD_VERTICAL_SENSORS: VERTICAL_SENSOR_BITS,
}

#: Todas las teclas con nombre que puede producir este controlador.
ALL_KEYS = frozenset(
	[k for bits in KEY_BITS.values() for k in bits if k] + list(WHEEL_PRESS_BITS) + list(WHEEL_STEP_KEYS) + list(STATUS_KEY_BITS)
)

#: Modelo y nombre con que se presenta la NLS eReader Zoomax.
ZOOMAX_MODEL = "NLSeReaderZoomax"
ZOOMAX_NAME = "NLS eReader Zoomax"
ZOOMAX_BT_PREFIX = "NLS eReader Z"
#: Chip USB-serie CH340 que usa la NLS eReader Zoomax (genérico).
ZOOMAX_USB_ID = "VID_1A86&PID_7523"

#: Tiempos de espera de las respuestas durante la conexión (segundos).
WAIT_IDENTIFY = 1.0
WAIT_RETRY = 0.6


def _bitsToKeys(value: int, names: tuple) -> set[str]:
	return {name for bit, name in enumerate(names) if name and value & (1 << bit)}


def _escape(data: bytes) -> bytes:
	"""Duplica los ESC de los argumentos (formato serie)."""
	return data.replace(bytes((ESC,)), bytes((ESC, ESC)))


def _spaceChords(space: str) -> dict[str, str]:
	"""Combinaciones de barra espaciadora + puntos para una barra concreta."""
	chords = {
		"b1": "kb:upArrow",
		"b4": "kb:downArrow",
		"b3": "kb:leftArrow",
		"b6": "kb:rightArrow",
		"b1+b3": "kb:shift+tab",
		"b4+b6": "kb:tab",
		"b1+b5": "kb:escape",
		"b1+b3+b4": "kb:alt",
		"b3+b4": "kb:windows",
		"b1+b4+b5": "kb:windows+d",
		"b2+b3+b4+b5": "kb:alt+tab",
		"b1+b3+b4+b5": "showGui",
		"b1+b2+b3+b4+b5+b6": "sayAll",
		"b7": "kb:backspace",
		"b8": "kb:enter",
	}
	return {f"{space}+{dots}": target for dots, target in chords.items()}


def _buildGestureMap() -> dict[str, str]:
	gestures = {
		# Teclas de pantalla: las centrales desplazan, las de los extremos cambian de línea.
		"d2": "braille_scrollBack",
		"d5": "braille_scrollForward",
		"d1": "braille_previousLine",
		"d3": "braille_nextLine",
		"d4": "braille_previousLine",
		"d6": "braille_nextLine",
		"d2+d5": "braille_toFocus",
		"d1+d3": "braille_toggleTether",
		# Teclas de órdenes c1-c4, de izquierda a derecha.
		"c1": "braille_scrollBack",
		"c2": "braille_previousLine",
		"c3": "braille_nextLine",
		"c4": "braille_scrollForward",
		# Enrutamiento.
		"routing": "braille_routeTo",
		"multiRouting": "braille_selectRange",
		"d2+routing": "braille_reportFormatting",
		# Joystick.
		"up": "kb:upArrow",
		"down": "kb:downArrow",
		"left": "kb:leftArrow",
		"right": "kb:rightArrow",
		"select": "kb:enter",
		# Sensores horizontales de los modelos antiguos (segunda fila de enrutamiento).
		"routing2": "braille_reportFormatting",
		# Módulos de la VarioPro: ruedas de los módulos de pantalla.
		"wheel1Up": "braille_previousLine",
		"wheel1Down": "braille_nextLine",
		"wheel2Up": "braille_scrollBack",
		"wheel2Down": "braille_scrollForward",
		"wheel3Up": "kb:upArrow",
		"wheel3Down": "kb:downArrow",
		"wheel4Up": "kb:leftArrow",
		"wheel4Down": "kb:rightArrow",
		"wheel1Press": "braille_toFocus",
		"wheel2Press": "braille_toggleTether",
		"wheel3Press": "kb:enter",
		"wheel4Press": "kb:enter",
		# Teclas del módulo de estado: informan de dónde se está.
		"statusKey1": "reportCurrentFocus",
		"statusKey2": "reportCurrentLine",
		"statusKey3": "title",
		"statusKey4": "reportStatusLine",
	}
	# Teclas delanteras y traseras de los modelos antiguos: las seis primeras
	# hacen lo mismo que d1-d6.
	for row in ("front", "back"):
		for i in range(1, 7):
			gestures[f"{row}{i}"] = gestures[f"d{i}"]
	gestures.update(_spaceChords("b9"))
	gestures.update(_spaceChords("b10"))
	return gestures


class BaumDriver(HardwareDriver):
	name = "baum"
	description = _("Baum (VarioUltra, Pronto!, SuperVario, VarioConnect, EcoVario...), HumanWare Brailliant2, APH Refreshabraille, Orbit Reader y NLS eReader Zoomax")
	baudRate = 19200
	usbHidIds = frozenset(
		{
			"VID_0904&PID_3001",  # Refreshabraille 18
			"VID_0904&PID_4004",  # Pronto! 18 V3
			"VID_0904&PID_4005",  # Pronto! 40 V3
			"VID_0904&PID_4007",  # Pronto! 18 V4
			"VID_0904&PID_4008",  # Pronto! 40 V4
			"VID_0904&PID_6001",  # SuperVario2 40
			"VID_0904&PID_6002",  # SuperVario2 24
			"VID_0904&PID_6003",  # SuperVario2 32
			"VID_0904&PID_6004",  # SuperVario2 64
			"VID_0904&PID_6005",  # SuperVario2 80
			"VID_0904&PID_6006",  # Brailliant2 40
			"VID_0904&PID_6007",  # Brailliant2 24
			"VID_0904&PID_6008",  # Brailliant2 32
			"VID_0904&PID_6009",  # Brailliant2 64
			"VID_0904&PID_600A",  # Brailliant2 80
			"VID_0904&PID_6101",  # VarioUltra 20
			"VID_0904&PID_6102",  # VarioUltra 40
			"VID_0904&PID_6103",  # VarioUltra 32
			"VID_0904&PID_6201",  # Vario 340
			"VID_0904&PID_6301",  # Vario 4
			"VID_0483&PID_A1D3",  # Orbit Reader 20
			"VID_0483&PID_A366",  # Orbit Reader 40
		}
	)
	usbSerialIds = frozenset(
		{
			"VID_0403&PID_FE70",  # Vario 40
			"VID_0403&PID_FE71",  # PocketVario
			"VID_0403&PID_FE72",  # SuperVario/Brailliant 40
			"VID_0403&PID_FE73",  # SuperVario/Brailliant 32
			"VID_0403&PID_FE74",  # SuperVario/Brailliant 64
			"VID_0403&PID_FE75",  # SuperVario/Brailliant 80
			"VID_0403&PID_FE76",  # VarioPro 80
			"VID_0403&PID_FE77",  # VarioPro 64
			"VID_0904&PID_2000",  # VarioPro 40
			"VID_0904&PID_2001",  # EcoVario 24
			"VID_0904&PID_2002",  # EcoVario 40
			"VID_0904&PID_2007",  # VarioConnect/BrailleConnect 40
			"VID_0904&PID_2008",  # VarioConnect/BrailleConnect 32
			"VID_0904&PID_2009",  # VarioConnect/BrailleConnect 24
			"VID_0904&PID_2010",  # VarioConnect/BrailleConnect 64
			"VID_0904&PID_2011",  # VarioConnect/BrailleConnect 80
			"VID_0904&PID_2014",  # EcoVario 32
			"VID_0904&PID_2015",  # EcoVario 64
			"VID_0904&PID_2016",  # EcoVario 80
			"VID_0904&PID_3000",  # Refreshabraille 18
			ZOOMAX_USB_ID,  # NLS eReader Zoomax (chip CH340)
		}
	)
	genericUsbIds = frozenset({ZOOMAX_USB_ID})
	bluetoothPrefixes = (
		"Baum ",  # Baum SuperVario, PocketVario, SVario, Conny...
		"HWG Brailliant",
		"Refreshabraille",
		"VarioConnect",
		"BrailleConnect",
		"Pronto!",
		"VarioUltra",
		"Orbit Reader 20",
		"Orbit Reader 40",
		"Vario 4",
		ZOOMAX_BT_PREFIX,
	)
	keyOrder = [
		"d1", "d2", "d3", "d4", "d5", "d6",
		"c1", "c2", "c3", "c4",
		"b9", "b10", "b11",
		"b1", "b2", "b3", "b4", "b5", "b6", "b7", "b8",
		"up", "down", "left", "right", "select",
		*FRONT_KEY_BITS, *BACK_KEY_BITS, *COMMAND_KEY_BITS,
		*WHEEL_STEP_KEYS, *WHEEL_PRESS_BITS, *STATUS_KEY_BITS,
		*VERTICAL_SENSOR_BITS,
	]
	dotKeys = {f"b{i}": i for i in range(1, 9)}
	spaceKeys = frozenset({"b9", "b10"})
	gestureMap = _buildGestureMap()
	#: En la NLS eReader Zoomax la tercera tecla (b11) también es barra espaciadora.
	modelGestureMaps = {ZOOMAX_MODEL: _spaceChords("b11")}
	keyDescriptions = {
		"d1": _("tecla de pantalla 1 (izquierda, arriba)"),
		"d2": _("tecla de pantalla 2 (izquierda, centro)"),
		"d3": _("tecla de pantalla 3 (izquierda, abajo)"),
		"d4": _("tecla de pantalla 4 (derecha, arriba)"),
		"d5": _("tecla de pantalla 5 (derecha, centro)"),
		"d6": _("tecla de pantalla 6 (derecha, abajo)"),
		**{f"b{i}": _("punto {n} del teclado braille").format(n=i) for i in range(1, 9)},
		"b9": _("barra espaciadora izquierda"),
		"b10": _("barra espaciadora derecha"),
		"b11": _("tecla b11 del teclado braille (en la NLS eReader Zoomax, la tercera barra espaciadora)"),
		"c1": _("tecla de órdenes c1"),
		"c2": _("tecla de órdenes c2"),
		"c3": _("tecla de órdenes c3"),
		"c4": _("tecla de órdenes c4"),
		"up": _("joystick hacia arriba"),
		"down": _("joystick hacia abajo"),
		"left": _("joystick hacia la izquierda"),
		"right": _("joystick hacia la derecha"),
		"select": _("pulsar el joystick"),
		"routing": _("tecla de enrutamiento sobre una celda"),
		"multiRouting": _("dos teclas de enrutamiento a la vez"),
		"routing2": _("sensor horizontal sobre una celda (modelos antiguos)"),
		"multiRouting2": _("dos sensores horizontales a la vez (modelos antiguos)"),
		**{f"front{i}": _("tecla delantera {n} (modelos antiguos)").format(n=i) for i in range(1, 11)},
		**{f"back{i}": _("tecla trasera {n} (modelos antiguos)").format(n=i) for i in range(1, 11)},
		**{f"command{i}": _("tecla de órdenes {n} (modelos antiguos)").format(n=i) for i in range(1, 9)},
		**{f"verticalSensor{i}": _("sensor vertical {n} (modelos antiguos)").format(n=i) for i in range(1, 33)},
		**{f"wheel{i}Up": _("rueda {n} del módulo de pantalla hacia arriba (VarioPro)").format(n=i) for i in range(1, WHEEL_COUNT + 1)},
		**{f"wheel{i}Down": _("rueda {n} del módulo de pantalla hacia abajo (VarioPro)").format(n=i) for i in range(1, WHEEL_COUNT + 1)},
		**{f"wheel{i}Press": _("pulsar la rueda {n} del módulo de pantalla (VarioPro)").format(n=i) for i in range(1, WHEEL_COUNT + 1)},
		**{f"statusKey{i}": _("tecla {n} del módulo de estado (VarioPro)").format(n=i) for i in range(1, 5)},
	}

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		self._isHid = False
		self._zoomax = False
		self._buffer = bytearray()
		#: Teclas pulsadas por grupo (comando que las informa, o módulo y registro).
		self._groups: dict[Any, frozenset] = {}
		#: Módulos registrados de la VarioPro: (id, serie) -> tipo.
		self._modules: dict[tuple[int, int], int] = {}
		#: Módulo de pantalla al que se escriben las celdas (id, serie, celdas).
		self._displayModule: tuple[int, int, int] | None = None
		self._deviceId = ""
		self.serialNumber = ""
		super().__init__(*args, **kwargs)

	# ------------------------------------------------------------ conexión
	@staticmethod
	def _isZoomaxMatch(match: DeviceMatch) -> bool:
		return match.id == ZOOMAX_USB_ID or match.id.startswith(ZOOMAX_BT_PREFIX)

	def _isKnownBaumMatch(self, match: DeviceMatch) -> bool:
		"""El dispositivo es sin duda Baum (no hace falta probar la variante Zoomax)."""
		if match.id in self.usbSerialIds or match.id in self.usbHidIds:
			return match.id != ZOOMAX_USB_ID
		return bool(match.id) and self._bluetoothNameMatches(match.id) and not match.id.startswith(ZOOMAX_BT_PREFIX)

	def _connect(self, match: DeviceMatch) -> None:
		if match.type not in ("hid", "serial"):
			raise DisplayNotFound(f"Tipo de conexión no admitido: {match.type}")
		self._isHid = match.type == "hid"
		self._resetState()
		self._deviceId = ""
		self.serialNumber = ""
		self.numCells = 0
		if self._isHid:
			self._io = self._open(match)
			self._connectHid()
		else:
			self._io = self._open(match, baudrate=self.baudRate, parity="N", stopBits=1)
			self._connectSerial(match)
		if self.numCells <= 0:
			raise DisplayNotFound("La línea Baum no ha respondido")
		self._applyIdentity()

	def _identified(self) -> bool:
		return self.numCells > 0 and bool(self._deviceId)

	def _connectHid(self) -> None:
		try:
			# Imprescindible en la Orbit Reader; la Pronto! y la VarioUltra no lo
			# admiten por HID y rechazan el informe.
			self._sendCommand(CMD_PROTOCOL_ONOFF, b"\x01")
		except hwio.IoError as e:
			log.debug("La línea no admite activar el protocolo por HID: %s", e)
		# Activar el protocolo no siempre devuelve la información: se pide aparte.
		self._sendCommand(CMD_REQUEST_INFO, b"\x00")
		if not self._waitFor(self._identified, WAIT_IDENTIFY) and self.numCells <= 0:
			self._sendCommand(CMD_REQUEST_INFO, b"\x00")
			self._waitFor(self._identified, WAIT_RETRY)

	def _connectSerial(self, match: DeviceMatch) -> None:
		if self._isZoomaxMatch(match):
			self._activateZoomax()
			return
		# Si el protocolo ya estaba activo, activarlo otra vez no responde nada:
		# primero se desactiva. Se activa dos veces por si la línea pierde la primera.
		self._sendCommand(CMD_PROTOCOL_ONOFF, b"\x00")
		self._sendCommand(CMD_PROTOCOL_ONOFF, b"\x01")
		self._sendCommand(CMD_PROTOCOL_ONOFF, b"\x01")
		if self._waitFor(self._identified, WAIT_IDENTIFY) or self.numCells > 0:
			return
		self._sendCommand(CMD_REQUEST_INFO, b"\x00")
		if self._waitFor(self._identified, WAIT_RETRY) or self.numCells > 0:
			return
		if not self._isKnownBaumMatch(match):
			# Puerto elegido a mano o desconocido: puede ser una NLS eReader Zoomax.
			self._activateZoomax()

	def _activateZoomax(self) -> None:
		self._zoomax = True
		self._sendCommand(CMD_PROTOCOL_ONOFF, bytes((ZOOMAX_PROTOCOL,)))
		self._sendCommand(CMD_REPEAT_ALL)
		self._waitFor(lambda: self.numCells > 0, WAIT_IDENTIFY)
		if self.numCells <= 0:
			self._zoomax = False

	def _applyIdentity(self) -> None:
		"""Fija el modelo y el nombre a partir de la identificación recibida."""
		if self._zoomax:
			self.model = ZOOMAX_MODEL
			self.deviceName = self._deviceId or ZOOMAX_NAME
			# La tercera tecla del teclado también es barra espaciadora.
			self.spaceKeys = frozenset({"b9", "b10", "b11"})
			return
		self.spaceKeys = type(self).spaceKeys
		self.deviceName = self._deviceId or "Baum"
		self.model = "".join(ch for ch in self._deviceId if ch.isalnum())

	def _resetState(self) -> None:
		self._buffer.clear()
		self._groups.clear()
		self._modules.clear()
		self._displayModule = None

	def _sayGoodbye(self) -> None:
		if self._zoomax:
			return
		try:
			self._sendCommand(CMD_PROTOCOL_ONOFF, b"\x00")
		except hwio.IoError:
			# Algunas líneas no admiten este comando por HID.
			pass

	# ------------------------------------------------------------ envío
	def _sendCommand(self, command: int, arg: bytes = b"") -> None:
		if self._isHid:
			self._write(bytes((command,)) + arg)
		else:
			self._write(bytes((ESC, command)) + _escape(arg))

	def _writeCells(self, cells: list[int]) -> None:
		data = bytes(c & 0xFF for c in cells)
		module = self._displayModule
		if module is None:
			self._sendCommand(CMD_DISPLAY_DATA, data)
			return
		# VarioPro: las celdas son los registros de datos del módulo de pantalla
		# (formato probable, sin verificar con hardware).
		ident, serial, _cells = module
		body = ident.to_bytes(2, "little") + serial.to_bytes(2, "little") + bytes((DATA_REGISTERS_WRITE, 0, len(data))) + data
		self._sendCommand(CMD_DATA_REGISTERS, bytes((len(body),)) + body)

	def _sendModuleAcknowledge(self, ident: int, serial: int) -> None:
		body = ident.to_bytes(2, "little") + serial.to_bytes(2, "little") + bytes((MODULE_ACKNOWLEDGE,))
		try:
			self._sendCommand(CMD_MODULE_REGISTRATION, bytes((len(body),)) + body)
		except hwio.IoError as e:
			log.debug("No se pudo confirmar el módulo %04X: %s", ident, e)

	# ------------------------------------------------------------ recepción
	def _argLength(self, command: int) -> int | None:
		"""Longitud de los argumentos de una respuesta (``None`` si no se conoce).

		Las tramas de módulos (0x50-0x52) llevan su longitud en el primer byte:
		aquí se devuelve 1 y quien lee completa el resto.
		"""
		if command in (CMD_ROUTING_KEYS, CMD_HORIZONTAL_SENSORS):
			return 10 if self.numCells > 40 else 5
		if command in MODULE_COMMANDS:
			return 1
		return RESPONSE_LENGTHS.get(command)

	def _handleData(self, data: bytes) -> None:
		if self._isHid:
			self._handleHidReport(data)
			return
		self._buffer += data
		while True:
			frame = self._nextFrame()
			if frame is None:
				break
			self._handleResponse(*frame)

	def _handleHidReport(self, report: bytes) -> None:
		if not report:
			return
		command = report[0]
		length = self._argLength(command)
		if length is None:
			log.debug("Informe Baum desconocido: %s", report.hex(" "))
			return
		if command in MODULE_COMMANDS and len(report) > 1:
			length = 1 + report[1]
		arg = bytes(report[1 : 1 + length])
		if command == CMD_DEVICE_ID and arg == REFRESHABRAILLE_ID:
			arg = bytes(report[1 : 1 + REFRESHABRAILLE_ID_LENGTH])
		if len(arg) < length:
			log.debug("Informe Baum incompleto: %s", report.hex(" "))
			return
		self._handleResponse(command, arg)

	def _nextFrame(self) -> tuple[int, bytes] | None:
		"""Extrae del búfer la siguiente trama serie completa (o ``None``)."""
		buf = self._buffer
		while True:
			start = buf.find(ESC)
			if start < 0:
				if buf:
					log.debug("Bytes sin ESC descartados: %s", bytes(buf).hex(" "))
				buf.clear()
				return None
			if start:
				log.debug("Bytes antes de ESC descartados: %s", bytes(buf[:start]).hex(" "))
				del buf[:start]
			if len(buf) < 2:
				return None
			command = buf[1]
			if command == ESC:
				# ESC duplicado fuera de una trama (argumentos de una trama
				# desconocida o perdida): se descarta.
				del buf[:2]
				continue
			length = self._argLength(command)
			if length is None:
				# Trama desconocida: no se sabe su longitud. Se descarta la cabecera y
				# se ignora lo que siga hasta el próximo ESC que empiece una trama.
				log.debug("Comando Baum desconocido: %02X", command)
				del buf[:2]
				continue
			arg = bytearray()
			i = 2
			resync = False
			while len(arg) < length:
				if i >= len(buf):
					return None
				byte = buf[i]
				if byte == ESC:
					if i + 1 >= len(buf):
						return None
					if buf[i + 1] != ESC:
						# ESC suelto: empieza otra trama y esta se ha cortado.
						resync = True
						break
					i += 2
				else:
					i += 1
				arg.append(byte)
				if command == CMD_DEVICE_ID and len(arg) == length and bytes(arg) == REFRESHABRAILLE_ID:
					length = REFRESHABRAILLE_ID_LENGTH
				elif command in MODULE_COMMANDS and len(arg) == 1:
					# Tramas de módulos: el primer byte es la longitud del resto.
					length = 1 + byte
			if resync:
				log.debug("Trama Baum %02X cortada: %s", command, bytes(arg).hex(" "))
				del buf[:i]
				continue
			del buf[:i]
			return command, bytes(arg)

	def _handleResponse(self, command: int, arg: bytes) -> None:
		if command == CMD_CELL_COUNT:
			if arg[0] > 0:
				self.numCells = arg[0]
			return
		if command == CMD_DEVICE_ID:
			# Los identificadores cortos se rellenan con nulos o espacios.
			self._deviceId = arg.rstrip(b"\0 ").decode("latin-1")
			return
		if command == CMD_SERIAL_NUMBER:
			self.serialNumber = arg.rstrip(b"\0 ").decode("latin-1")
			return
		if command == CMD_POWERDOWN:
			log.debug("La línea Baum avisa de que se apaga")
			return
		if command in (CMD_COMMUNICATION_CHANNEL, CMD_VERSION, CMD_MODE_SETTING, CMD_SWITCHES, CMD_BLUETOOTH_NAME):
			return
		if command == CMD_ERROR_CODE:
			log.debug("La línea Baum informa del error %02X", arg[0])
			return
		if command == CMD_MODULE_REGISTRATION:
			self._handleModuleRegistration(arg[1:])
			return
		if command == CMD_DATA_REGISTERS:
			self._handleDataRegisters(arg[1:])
			return
		if command == CMD_SERVICE_REGISTERS:
			log.debug("Registros de servicio de un módulo Baum: %s", arg.hex(" "))
			return
		value = int.from_bytes(arg, "little")
		if command in KEY_BITS:
			keys: set = _bitsToKeys(value, KEY_BITS[command])
		elif command in (CMD_ROUTING_KEYS, CMD_HORIZONTAL_SENSORS):
			group = "routing" if command == CMD_ROUTING_KEYS else "routing2"
			keys = self._routingMask(group, arg)
		elif command in (CMD_ROUTING_KEY, CMD_HORIZONTAL_SENSOR):
			# Una sola tecla, numerada desde 1; las sucesivas se acumulan hasta
			# que llega un 0 (todas sueltas).
			group = "routing" if command == CMD_ROUTING_KEY else "routing2"
			keys = self._accumulate(command, (group, value - 1) if value > 0 else None)
		elif command == CMD_VERTICAL_SENSOR:
			# Número del sensor en los 6 bits bajos; el bit 0x40 parece indicar
			# el lado (izquierdo o derecho) y no se distingue.
			number = value & 0x3F
			if number > len(VERTICAL_SENSOR_BITS):
				return
			keys = self._accumulate(command, f"verticalSensor{number}" if number else None)
		else:
			return
		self._updateGroups({command: keys})

	def _routingMask(self, group: str, mask: bytes) -> set:
		value = int.from_bytes(mask, "little")
		limit = self.numCells or len(mask) * 8
		return {(group, i) for i in range(min(limit, len(mask) * 8)) if value & (1 << i)}

	def _accumulate(self, groupKey: Any, key: Any) -> set:
		"""Teclas informadas de una en una: se suman hasta que llega «ninguna»."""
		if key is None:
			return set()
		return set(self._groups.get(groupKey, frozenset())) | {key}

	def _updateGroups(self, changes: dict) -> None:
		"""Cambia las teclas de varios grupos y avisa una sola vez."""
		for groupKey, keys in changes.items():
			if keys:
				self._groups[groupKey] = frozenset(keys)
			else:
				self._groups.pop(groupKey, None)
		down: set = set()
		for group in self._groups.values():
			down |= group
		self._keysChanged(down)

	# ------------------------------------------------------------ módulos de la VarioPro
	@staticmethod
	def _moduleHeader(data: bytes) -> tuple[int, int] | None:
		if len(data) < 4:
			return None
		return int.from_bytes(data[0:2], "little"), int.from_bytes(data[2:4], "little")

	@staticmethod
	def _displayModuleCells(ident: int) -> int:
		# Suposición: el byte bajo 0x40 identifica el módulo de 64 celdas; el
		# resto, el de 80.
		return 64 if ident & 0xFF == 0x40 else 80

	def _handleModuleRegistration(self, data: bytes) -> None:
		header = self._moduleHeader(data)
		if header is None:
			return
		ident, serial = header
		event = data[4] if len(data) > 4 else 1
		moduleType = ident >> 8
		if event == MODULE_EVENT_REMOVAL:
			log.debug("Módulo Baum %04X/%04X retirado", ident, serial)
			self._modules.pop((ident, serial), None)
			if self._displayModule and self._displayModule[:2] == (ident, serial):
				self._displayModule = None
			self._updateGroups({key: set() for key in list(self._groups) if isinstance(key, tuple) and key[1:3] == (ident, serial)})
		else:
			log.debug("Módulo Baum %04X/%04X registrado (tipo %02X)", ident, serial, moduleType)
			self._modules[(ident, serial)] = moduleType
			if moduleType == MODULE_TYPE_DISPLAY:
				cells = self._displayModuleCells(ident)
				self._displayModule = (ident, serial, cells)
				if self.numCells <= 0:
					self.numCells = cells
		self._sendModuleAcknowledge(ident, serial)

	def _handleDataRegisters(self, data: bytes) -> None:
		header = self._moduleHeader(data)
		if header is None or len(data) < 7:
			return
		ident, serial = header
		start, count = data[5], data[6]
		values = data[7 : 7 + count]
		registers = {start + i: v for i, v in enumerate(values)}
		moduleType = self._modules.get((ident, serial), ident >> 8)
		# El primer registro indica qué ha cambiado; si no viene, se atiende todo.
		flags = registers.get(0, DRF_WHEELS | DRF_BUTTONS | DRF_KEYS | DRF_SENSORS)
		prefix = ("module", ident, serial)
		changes: dict = {}
		if moduleType == MODULE_TYPE_DISPLAY:
			if flags & DRF_WHEELS:
				for wheel in range(WHEEL_COUNT):
					raw = registers.get(1 + wheel, 0)
					steps = raw - 256 if raw > 127 else raw
					# Suposición: los pasos positivos son hacia abajo (hacia delante).
					name = f"wheel{wheel + 1}{'Down' if steps > 0 else 'Up'}"
					for _step in range(min(abs(steps), MAX_WHEEL_STEPS)):
						self._fireChord({name})
			if flags & DRF_BUTTONS and 5 in registers:
				changes[prefix + ("buttons",)] = _bitsToKeys(registers[5], WHEEL_PRESS_BITS)
			if flags & DRF_KEYS and 6 in registers:
				changes[prefix + ("keys",)] = _bitsToKeys(registers[6], DISPLAY_KEY_BITS)
			sensors = bytes(registers[i] for i in sorted(registers) if i >= 7)
			if flags & DRF_SENSORS and sensors:
				changes[prefix + ("sensors",)] = self._routingMask("routing", sensors)
		elif moduleType == MODULE_TYPE_STATUS:
			if flags & DRF_BUTTONS and 1 in registers:
				changes[prefix + ("buttons",)] = _bitsToKeys(registers[1], STATUS_KEY_BITS)
		else:
			log.debug("Datos de un módulo Baum no admitido (%04X): %s", ident, data.hex(" "))
			return
		if changes:
			self._updateGroups(changes)


BrailleDisplayDriver = BaumDriver
