"""Líneas braille Papenmeier BRAILLEX.

Un solo controlador para los dos protocolos de la marca:

**Protocolo nuevo** (EL 40s, EL 66s, EL 70s, EL 80s, EL 2D-80s, EL 20c,
EL 40c, EL 60c, EL 80c, Trio, Live, Live+ y Live 20). Por USB las líneas
llevan un chip FTDI que Windows presenta como puerto COM virtual (57600
baudios; el Trio contesta a 115200) y el Trio y la Live también se conectan
por Bluetooth (puerto serie, 57600 baudios). Todas las tramas empiezan por
STX (0x02) y terminan en ETX (0x03):

- identificación: el controlador envía ``STX 'B' 0x50 0x50 ETX`` y la línea
  contesta con una trama de 10 bytes cuyos bytes 4 y 5 son los dos nibbles
  (``0x30 | n``) del código de modelo;
- celdas: ``STX 'C' lonAlta lonBaja datos ETX``. La longitud va en dos
  nibbles (``0x50 | n``) y cuenta «posiciones» de la línea: las celdas del
  módulo vertical de las 2D, dos posiciones por cada módulo de teclas del
  extremo izquierdo y del derecho (EL) y las celdas de texto. Cada posición
  son dos bytes ``0x30 | nibble`` (primero el nibble alto) con los puntos en
  orden inverso (punto 1 en el bit 7);
- teclas: ``STX 'K' lonAlta lonBaja datos ETX`` con el estado completo de
  todas las teclas en nibbles (``0x30 | n``), y en el Trio y la Live
  ``STX 'L' ...`` con cada combinación del teclado braille (puntos 1-8 y las
  tres teclas de los pulgares).

**Protocolo antiguo** (BRAILLEX por puerto serie: Compact, 2D Lite,
2D Screen, IB 80, EL 2D-40, EL 2D-66, EL 80, EL 2D-80, EL 40 P, Elba). A
19200 baudios (o a 38400 los que tienen barra de acceso fácil). Tramas:

- identificación: ``STX 'S' 0 0 0 0 ETX`` (una escritura vacía); la línea
  contesta ``STX 'I' modelo ... ETX`` (10 bytes);
- escritura: ``STX 'S' dirAlta dirBaja lonAlta lonBaja datos ETX``, donde la
  longitud es la de toda la trama. Las celdas de texto están en la dirección
  igual al número de celdas de estado y en 0x200 + dirección se indica que
  los datos son puntos y no caracteres;
- teclas: ``STX 'K' códigoAlto códigoBajo x x pulsada x modificadores x ETX``
  con un evento por tecla.

Al conectar se prueban los dos protocolos (y sus velocidades) y se queda el
que conteste a la identificación.

Nombres de teclas (gestos ``br(papenmeier):...``): ``left``, ``left2``,
``right``, ``right2``, ``up``, ``up2``, ``dn``, ``dn2`` (barra de acceso
fácil o barras frontales), ``l1``, ``l2``, ``r1``, ``r2`` (teclas de los
extremos), ``reportf`` (tecla frontal de algunos modelos antiguos),
``routing``/``multiRouting`` (fila inferior de enrutamiento),
``routing2``/``multiRouting2`` (fila superior), ``statusN`` y
``upperStatusN`` (teclas de las celdas de estado o del módulo vertical),
``dot1``...``dot8``, ``lt``, ``space`` y ``rt`` (teclado braille del Trio y
la Live).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...i18n import _
from ...log import getLogger
from .base import DeviceMatch, DisplayNotFound, HardwareDriver

log = getLogger("braille.papenmeier")

STX = 0x02
ETX = 0x03

# ------------------------------------------------------------ protocolo nuevo
NEW_IDENTIFY = 0x42  # 'B'
NEW_CELLS = 0x43  # 'C'
NEW_KEYS = 0x4B  # 'K'
NEW_KEYBOARD = 0x4C  # 'L'
#: Tramas sin longitud (identificación y demás respuestas): tamaño fijo.
NEW_FIXED_FRAME = 10
NEW_IDENTIFY_REQUEST = bytes((STX, NEW_IDENTIFY, 0x50, 0x50, ETX))

# ------------------------------------------------------------ protocolo antiguo
OLD_WRITE = 0x53  # 'S'
OLD_IDENTITY = 0x49  # 'I'
OLD_KEY = 0x4B  # 'K'
OLD_FRAME = 10
OLD_IDENTIFY_REQUEST = bytes((STX, OLD_WRITE, 0, 0, 0, 0, ETX))
#: Dirección del modo de escritura de cada celda (1 = puntos).
OLD_WRITE_MODE_BASE = 0x200
#: Código de la primera tecla de enrutamiento; cada tecla avanza 3.
OLD_KEY_BASE = 0x300

#: Byte con los bits en orden inverso (el protocolo nuevo pone el punto 1 en el bit 7).
_REVERSED = bytes(int(f"{i:08b}"[::-1], 2) for i in range(256))


@dataclass(frozen=True)
class NewModel:
	"""Modelo del protocolo nuevo."""

	model: str
	name: str
	cells: int
	#: ``"el"``: barra de acceso fácil, teclas l1/l2/r1/r2 en módulos laterales
	#: y dos filas de enrutamiento. ``"trio"``: Trio y Live, con teclado braille.
	family: str
	#: Celdas del módulo vertical (EL 2D-80s).
	vertical: int = 0


NEW_MODELS: dict[int, NewModel] = {
	0x55: NewModel("EL40s", "BRAILLEX EL 40s", 40, "el"),
	0x57: NewModel("EL66s", "BRAILLEX EL 66s", 66, "el"),
	0x58: NewModel("EL80s", "BRAILLEX EL 80s", 80, "el"),
	0x5A: NewModel("EL70s", "BRAILLEX EL 70s", 70, "el"),
	0x5B: NewModel("EL2D80s", "BRAILLEX EL 2D-80s", 80, "el", vertical=20),
	0x5E: NewModel("EL20c", "BRAILLEX EL 20c", 20, "el"),
	0x5F: NewModel("EL40c", "BRAILLEX EL 40c", 40, "el"),
	0x60: NewModel("EL60c", "BRAILLEX EL 60c", 60, "el"),
	0x61: NewModel("EL80c", "BRAILLEX EL 80c", 80, "el"),
	0x59: NewModel("Trio", "BRAILLEX Trio", 40, "trio"),
	0x62: NewModel("Live", "BRAILLEX Live", 40, "trio"),
	0x63: NewModel("LivePlus", "BRAILLEX Live+", 40, "trio"),
	0x64: NewModel("Live20", "BRAILLEX Live 20", 20, "trio"),
}

#: Teclas de la familia EL por número de tecla del protocolo nuevo.
EL_BAR_KEYS = {20: "up2", 21: "up", 22: "dn", 23: "dn2", 24: "right", 25: "left", 26: "right2", 27: "left2"}
#: Primera tecla tras las barras (módulo vertical, si lo hay, o l1).
EL_FIRST_MODULE_KEY = 28
#: Teclas fijas del Trio y la Live.
TRIO_FIXED_KEYS = {16: "left2", 17: "right2", 18: "left", 19: "right", 20: "dn2", 21: "dn", 22: "up", 23: "up2", 30: "l2", 31: "l1"}
#: Primera tecla de enrutamiento (dos por celda: inferior y superior).
ROUTING_FIRST_KEY = 32
#: Teclas de los pulgares del teclado braille (bits del segundo nibble de la trama 'L').
THUMB_KEYS = ((0x01, "rt"), (0x02, "space"), (0x04, "lt"))


@dataclass(frozen=True)
class OldModel:
	"""Modelo del protocolo antiguo."""

	model: str
	name: str
	cells: int
	#: Celdas de estado a la izquierda de las de texto.
	statusCells: int
	#: Teclas frontales por posición (modelos sin barra de acceso fácil).
	frontKeys: tuple[str, ...]


OLD_FRONT_KEYS_9 = ("l1", "l2", "left", "up", "r2", "dn", "right", "r1", "reportf")
OLD_FRONT_KEYS_13 = ("l1", "l2", "r2", "reportf", "up", "left", "r1", "right", "dn", "left2", "up2", "dn2", "right2")

OLD_MODELS: dict[int, OldModel] = {
	1: OldModel("Compact486", "BRAILLEX Compact 486", 40, 0, OLD_FRONT_KEYS_9),
	2: OldModel("Braillex2DLite", "BRAILLEX 2D Lite", 40, 0, OLD_FRONT_KEYS_9),
	3: OldModel("Braillex2DScreen", "BRAILLEX 2D Screen", 80, 22, OLD_FRONT_KEYS_13),
	6: OldModel("IB80", "BRAILLEX IB 80", 80, 0, OLD_FRONT_KEYS_13),
	64: OldModel("EL2D40", "BRAILLEX EL 2D-40", 40, 13, OLD_FRONT_KEYS_9),
	65: OldModel("EL2D66", "BRAILLEX EL 2D-66", 66, 13, OLD_FRONT_KEYS_9),
	66: OldModel("EL80", "BRAILLEX EL 80", 80, 2, OLD_FRONT_KEYS_9),
	67: OldModel("EL2D80", "BRAILLEX EL 2D-80", 80, 20, OLD_FRONT_KEYS_13),
	68: OldModel("EL40P", "BRAILLEX EL 40 P", 40, 0, OLD_FRONT_KEYS_9),
	69: OldModel("Elba32", "BRAILLEX Elba 32", 32, 0, OLD_FRONT_KEYS_9),
	70: OldModel("Elba20", "BRAILLEX Elba 20", 20, 0, OLD_FRONT_KEYS_9),
}

#: Teclas de la barra de acceso fácil en el protocolo antiguo (índice de tecla negativo).
OLD_EAB_KEYS = {-255: "left", -254: "left2", -253: "up", -252: "up2", -251: "right", -250: "right2", -249: "dn", -248: "dn2"}
#: Bits del byte de modificadores (líneas con barra de acceso fácil).
OLD_EAB_MODIFIERS = ((0x04, "l1"), (0x08, "l2"), (0x10, "r1"), (0x20, "r2"))

#: Teclas con nombre fijo (para comprobar el mapa de gestos).
NAMED_KEYS = frozenset(
	{"left", "left2", "right", "right2", "up", "up2", "dn", "dn2", "l1", "l2", "r1", "r2", "reportf", "lt", "space", "rt"}
	| {f"dot{i}" for i in range(1, 9)}
	| {"routing", "multiRouting", "routing2", "multiRouting2"}
)


class PapenmeierDriver(HardwareDriver):
	name = "papenmeier"
	description = _("Papenmeier BRAILLEX (EL, Trio, Live y modelos serie antiguos)")
	# Chip FTDI con el identificador propio de Papenmeier y el genérico (algunas
	# líneas y los adaptadores USB-serie de los modelos antiguos).
	usbSerialIds = frozenset({"VID_0403&PID_F208", "VID_0403&PID_6001"})
	genericUsbIds = frozenset({"VID_0403&PID_6001"})
	bluetoothPrefixes = ("BRAILLEX Trio", "BRAILLEX Live")
	baudRate = 57600
	#: Segundos de espera de la identificación en cada intento.
	identifyTimeout = 0.5
	keyOrder = [
		"l1", "l2", "r1", "r2", "reportf",
		"left", "left2", "right", "right2", "up", "up2", "dn", "dn2",
		"lt", "space", "rt",
		"dot1", "dot2", "dot3", "dot4", "dot5", "dot6", "dot7", "dot8",
	]  # fmt: skip
	dotKeys = {f"dot{i}": i for i in range(1, 9)}
	spaceKeys = frozenset({"space"})
	gestureMap = {
		# Barra de acceso fácil / barras frontales.
		"left": "braille_scrollBack",
		"right": "braille_scrollForward",
		"up": "braille_previousLine",
		"dn": "braille_nextLine",
		"left2": "navigatorObject_previous",
		"right2": "navigatorObject_next",
		"up2": "navigatorObject_parent",
		"dn2": "navigatorObject_firstChild",
		# Teclas de los extremos.
		"l1": "braille_toFocus",
		"l2": "review_activate",
		"r1": "reportCurrentFocus",
		"r2": "braille_toggleTether",
		"l1+l2": "showGui",
		"r1+r2": "sayAll",
		"l1+up": "title",
		"l1+dn": "reportStatusLine",
		"l2+up": "review_top",
		"l2+dn": "review_bottom",
		"l2+left": "review_startOfLine",
		"l2+right": "review_endOfLine",
		"r1+up": "kb:upArrow",
		"r1+dn": "kb:downArrow",
		"r1+left": "kb:leftArrow",
		"r1+right": "kb:rightArrow",
		"r2+left": "kb:shift+tab",
		"r2+right": "kb:tab",
		"r2+up": "kb:escape",
		"r2+dn": "kb:enter",
		"reportf": "reportFormatting",
		# Enrutamiento.
		"routing": "braille_routeTo",
		"multiRouting": "braille_selectRange",
		"routing2": "braille_reportFormatting",
		# Teclado braille del Trio y la Live.
		"lt": "braille_scrollBack",
		"rt": "braille_scrollForward",
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
		"space+dot7+dot8": "kb:delete",
		# Pulgar derecho + letra a-l: teclas de función F1-F12.
		"rt+dot1": "kb:f1",
		"rt+dot1+dot2": "kb:f2",
		"rt+dot1+dot4": "kb:f3",
		"rt+dot1+dot4+dot5": "kb:f4",
		"rt+dot1+dot5": "kb:f5",
		"rt+dot1+dot2+dot4": "kb:f6",
		"rt+dot1+dot2+dot4+dot5": "kb:f7",
		"rt+dot1+dot2+dot5": "kb:f8",
		"rt+dot2+dot4": "kb:f9",
		"rt+dot2+dot4+dot5": "kb:f10",
		"rt+dot1+dot3": "kb:f11",
		"rt+dot1+dot2+dot3": "kb:f12",
		# Pulgar izquierdo + letra: atajos con Control.
		"lt+dot1": "kb:control+a",
		"lt+dot1+dot4": "kb:control+c",
		"lt+dot1+dot2+dot4": "kb:control+f",
		"lt+dot2+dot3+dot4": "kb:control+s",
		"lt+dot1+dot2+dot3+dot6": "kb:control+v",
		"lt+dot1+dot3+dot4+dot6": "kb:control+x",
		"lt+dot1+dot3+dot4+dot5+dot6": "kb:control+y",
		"lt+dot1+dot3+dot5+dot6": "kb:control+z",
	}
	keyDescriptions = {
		"left": _("Barra de acceso fácil (o barra frontal) hacia la izquierda"),
		"left2": _("Barra de acceso fácil hacia la izquierda, segunda posición"),
		"right": _("Barra de acceso fácil (o barra frontal) hacia la derecha"),
		"right2": _("Barra de acceso fácil hacia la derecha, segunda posición"),
		"up": _("Barra de acceso fácil (o barra frontal) hacia arriba"),
		"up2": _("Barra de acceso fácil hacia arriba, segunda posición"),
		"dn": _("Barra de acceso fácil (o barra frontal) hacia abajo"),
		"dn2": _("Barra de acceso fácil hacia abajo, segunda posición"),
		"l1": _("Primera tecla del extremo izquierdo"),
		"l2": _("Segunda tecla del extremo izquierdo"),
		"r1": _("Primera tecla del extremo derecho"),
		"r2": _("Segunda tecla del extremo derecho"),
		"reportf": _("Tecla frontal de formato (algunos modelos serie antiguos)"),
		"routing": _("Botón de enrutamiento de la fila inferior, sobre cada celda"),
		"routing2": _("Botón de enrutamiento de la fila superior, sobre cada celda"),
		"statusN": _("Botón de la celda de estado o del módulo vertical número N (statusN, fila inferior; upperStatusN, fila superior)"),
		"lt": _("Tecla del pulgar izquierdo (Trio y Live)"),
		"space": _("Barra espaciadora (Trio y Live)"),
		"rt": _("Tecla del pulgar derecho (Trio y Live)"),
		"dot1": _("Puntos 1 a 8 del teclado braille (Trio y Live)"),
	}

	@classmethod
	def _bluetoothNameMatches(cls, name: str) -> bool:
		# Las líneas se anuncian como «braillex trio 1234» o «BRAILLEX Live...».
		low = (name or "").strip().lower()
		return bool(low) and any(low.startswith(p.lower()) for p in cls.bluetoothPrefixes)

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		#: ``"new"`` u ``"old"``: protocolo con el que se interpretan los datos.
		self._protocol = ""
		self._buffer = bytearray()
		#: Código de modelo recibido en la identificación.
		self._identity: int | None = None
		self._newModel: NewModel | None = None
		self._oldModel: OldModel | None = None
		#: Protocolo antiguo: la línea tiene barra de acceso fácil (38400 baudios).
		self._eab = False
		#: Protocolo antiguo: teclas pulsadas según los eventos recibidos.
		self._oldDown: set = set()
		super().__init__(*args, **kwargs)

	# ------------------------------------------------------------ conexión
	def _attempts(self, match: DeviceMatch) -> list[tuple[str, int]]:
		"""Protocolos y velocidades que se prueban, en orden."""
		new = [("new", 57600), ("new", 115200)]
		old = [("old", 19200), ("old", 38400)]
		if match.bluetooth:
			# Por Bluetooth solo hay Trio y Live (protocolo nuevo).
			return new
		if match.id.upper().startswith("VID_"):
			return new + old
		# Puerto COM elegido a mano: lo más probable es un modelo serie antiguo.
		return old + new

	def _connect(self, match: DeviceMatch) -> None:
		for protocol, baud in self._attempts(match):
			if self._terminated:
				break
			self._closeIo()
			with self._cond:
				self._protocol = protocol
				self._identity = None
				self._buffer.clear()
				self._oldDown.clear()
			self._io = self._open(match, baudrate=baud)
			try:
				ok = self._identifyNew(baud) if protocol == "new" else self._identifyOld(baud)
			except Exception as e:
				log.debug("Papenmeier: error identificando (%s, %d): %s", protocol, baud, e)
				ok = False
			if ok:
				return
		self._closeIo()
		raise DisplayNotFound("La línea Papenmeier no ha respondido")

	def _identifyNew(self, baud: int) -> bool:
		self._write(NEW_IDENTIFY_REQUEST)
		if baud == 115200:
			# Tras el cambio de velocidad el Trio puede perder la primera petición.
			self._write(NEW_IDENTIFY_REQUEST)
		if not self._waitFor(lambda: self._identity is not None, self.identifyTimeout):
			return False
		model = NEW_MODELS.get(self._identity or 0)
		if model is None:
			log.info("Papenmeier: modelo desconocido 0x%02X (protocolo nuevo)", self._identity or 0)
			return False
		self._newModel = model
		self._oldModel = None
		self.model = model.model
		self.deviceName = model.name
		self.numCells = model.cells
		return True

	def _identifyOld(self, baud: int) -> bool:
		self._write(OLD_IDENTIFY_REQUEST)
		if not self._waitFor(lambda: self._identity is not None, self.identifyTimeout):
			return False
		model = OLD_MODELS.get(self._identity or 0)
		if model is None:
			log.info("Papenmeier: modelo desconocido %d (protocolo antiguo)", self._identity or 0)
			return False
		self._oldModel = model
		self._newModel = None
		self._eab = baud == 38400
		self.model = model.model
		self.deviceName = model.name
		# Las celdas de texto reciben puntos, no caracteres que traducir.
		self._write(self._oldFrame(OLD_WRITE_MODE_BASE + model.statusCells, bytes([1]) * model.cells))
		self.numCells = model.cells
		return True

	def _resetState(self) -> None:
		self._buffer.clear()
		self._oldDown.clear()

	# ------------------------------------------------------------ entrada
	def _handleData(self, data: bytes) -> None:
		self._buffer.extend(data)
		if self._protocol == "new":
			self._parseNew()
		elif self._protocol == "old":
			self._parseOld()
		else:
			self._buffer.clear()

	def _syncToStx(self) -> bool:
		"""Descarta lo anterior al siguiente STX. Devuelve False si no queda ninguno."""
		buf = self._buffer
		pos = buf.find(STX)
		if pos < 0:
			buf.clear()
			return False
		del buf[:pos]
		return True

	def _parseNew(self) -> None:
		buf = self._buffer
		while buf:
			if buf[0] != STX and not self._syncToStx():
				return
			if len(buf) < 2:
				return
			if buf[1] in (NEW_KEYS, NEW_KEYBOARD):
				if len(buf) < 4:
					return
				hi, lo = buf[2], buf[3]
				if (hi & 0xF0) != 0x50 or (lo & 0xF0) != 0x50:
					del buf[0]
					continue
				size = 4 + 2 * (((hi & 0x0F) << 4) | (lo & 0x0F)) + 1
			else:
				size = NEW_FIXED_FRAME
			if len(buf) < size:
				return
			if buf[size - 1] != ETX:
				# Trama rota: se busca el siguiente comienzo.
				del buf[0]
				continue
			frame = bytes(buf[:size])
			del buf[:size]
			self._handleNewFrame(frame)

	def _handleNewFrame(self, frame: bytes) -> None:
		cmd = frame[1]
		data = frame[4:-1]
		if cmd == NEW_KEYS:
			if self.numCells > 0 and self._newModel is not None:
				self._keysChanged(self._decodeNewKeys(data))
			return
		if cmd == NEW_KEYBOARD:
			if self.numCells > 0:
				self._handleBrailleKeyboard(data)
			return
		# Respuesta a la identificación (solo mientras se conecta).
		if self.numCells <= 0 and all(0x30 <= b <= 0x3F for b in frame[4:6]):
			self._identity = ((frame[4] & 0x0F) << 4) | (frame[5] & 0x0F)

	def _decodeNewKeys(self, data: bytes) -> set:
		"""Teclas pulsadas de una trama 'K' del protocolo nuevo."""
		model = self._newModel
		assert model is not None
		numbers: list[int] = []
		if model.family == "el":
			# Pares de bytes: el segundo lleva las teclas n..n+3 y el primero n+4..n+7.
			for pair in range(len(data) // 2):
				base = 4 + 8 * pair
				high = data[2 * pair] & 0x0F
				low = data[2 * pair + 1] & 0x0F
				for bit in range(4):
					if low & (1 << bit):
						numbers.append(base + bit)
					if high & (1 << bit):
						numbers.append(base + 4 + bit)
		else:
			# Un byte por cada cuatro teclas, la primera en el bit 3.
			for i, value in enumerate(data):
				for bit in range(4):
					if value & (1 << bit):
						numbers.append(4 * i + 3 - bit)
		keys = set()
		for number in numbers:
			key = self._newKeyName(number)
			if key is not None:
				keys.add(key)
		return keys

	def _newKeyName(self, number: int) -> Any:
		model = self._newModel
		assert model is not None
		cells = self.numCells
		if model.family == "el":
			if number in EL_BAR_KEYS:
				return EL_BAR_KEYS[number]
			vertical = 2 * model.vertical
			if EL_FIRST_MODULE_KEY <= number < EL_FIRST_MODULE_KEY + vertical:
				cell, upper = divmod(number - EL_FIRST_MODULE_KEY, 2)
				return f"{'upperStatus' if upper else 'status'}{cell + 1}"
			number -= vertical
			if number == EL_FIRST_MODULE_KEY:
				return "l1"
			if number == EL_FIRST_MODULE_KEY + 1:
				return "l2"
			rightModule = ROUTING_FIRST_KEY + 2 * cells
			if number == rightModule:
				return "r1"
			if number == rightModule + 1:
				return "r2"
		else:
			if number in TRIO_FIXED_KEYS:
				return TRIO_FIXED_KEYS[number]
			rightModule = ROUTING_FIRST_KEY + 2 * cells
			if number == rightModule + 6:
				return "r2"
			if number == rightModule + 7:
				return "r1"
		if ROUTING_FIRST_KEY <= number < ROUTING_FIRST_KEY + 2 * cells:
			cell, upper = divmod(number - ROUTING_FIRST_KEY, 2)
			return ("routing2" if upper else "routing", cell)
		return None

	def _handleBrailleKeyboard(self, data: bytes) -> None:
		"""Trama 'L': una combinación completa del teclado braille."""
		if len(data) < 4:
			return
		if (data[0] & 0x0F) >> 3:
			# Tecla de un teclado de PC conectado a la línea (código de exploración).
			# Tiresias no inyecta códigos de exploración: se ignora.
			log.debug("Papenmeier: tecla de PC no admitida %r", data)
			return
		thumbs = data[1] & 0x07
		dots = ((data[2] & 0x0F) << 4) | (data[3] & 0x0F)
		chord = {name for bit, name in THUMB_KEYS if thumbs & bit}
		chord.update(f"dot{i + 1}" for i in range(8) if dots & (1 << i))
		if chord:
			self._fireChord(chord)

	def _parseOld(self) -> None:
		buf = self._buffer
		while buf:
			if buf[0] != STX and not self._syncToStx():
				return
			if len(buf) < OLD_FRAME:
				return
			if buf[OLD_FRAME - 1] != ETX:
				del buf[0]
				continue
			frame = bytes(buf[:OLD_FRAME])
			del buf[:OLD_FRAME]
			self._handleOldFrame(frame)

	def _handleOldFrame(self, frame: bytes) -> None:
		cmd = frame[1]
		if cmd == OLD_IDENTITY:
			if self.numCells <= 0:
				self._identity = frame[2]
			return
		if cmd != OLD_KEY or self.numCells <= 0 or self._oldModel is None:
			return
		index = (((frame[2] << 8) | frame[3]) - OLD_KEY_BASE) // 3
		key = self._oldKeyName(index)
		if key is not None:
			if frame[6]:
				self._oldDown.add(key)
			else:
				self._oldDown.discard(key)
		down = set(self._oldDown)
		if self._eab:
			down.update(name for bit, name in OLD_EAB_MODIFIERS if frame[8] & bit)
		self._keysChanged(down)

	def _oldKeyName(self, index: int) -> Any:
		model = self._oldModel
		assert model is not None
		if index >= 0:
			upper = index > 255
			pos = index - 256 if upper else index
			cell = pos - model.statusCells
			if cell < 0:
				return f"{'upperStatus' if upper else 'status'}{pos + 1}"
			if cell >= self.numCells:
				return None
			return ("routing2" if upper else "routing", cell)
		if self._eab:
			return OLD_EAB_KEYS.get(index)
		slot = index + 255
		if 0 <= slot < len(model.frontKeys):
			return model.frontKeys[slot]
		return None

	# ------------------------------------------------------------ salida
	@staticmethod
	def _oldFrame(address: int, data: bytes) -> bytes:
		"""Trama de escritura del protocolo antiguo."""
		return bytes((STX, OLD_WRITE)) + address.to_bytes(2, "big") + (len(data) + 7).to_bytes(2, "big") + data + bytes((ETX,))

	def _writeCells(self, cells: list[int]) -> None:
		if self._protocol == "old" and self._oldModel is not None:
			self._write(self._oldFrame(self._oldModel.statusCells, bytes(c & 0xFF for c in cells)))
			return
		model = self._newModel
		if model is None:
			return
		sideModule = 1 if model.family == "el" else 0
		units = model.vertical + 2 * sideModule + len(cells) + 2 * sideModule
		out = bytearray((STX, NEW_CELLS, 0x50 | ((units >> 4) & 0x0F), 0x50 | (units & 0x0F)))
		# Celdas del módulo vertical y módulo izquierdo: en blanco.
		out += b"\x30" * (2 * model.vertical + 4 * sideModule)
		for cell in cells:
			value = _REVERSED[cell & 0xFF]
			out.append(0x30 | (value >> 4))
			out.append(0x30 | (value & 0x0F))
		out += b"\x30" * (4 * sideModule)
		out.append(ETX)
		self._write(bytes(out))


BrailleDisplayDriver = PapenmeierDriver
