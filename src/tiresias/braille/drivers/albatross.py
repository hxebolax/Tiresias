"""Líneas braille Tivomatic Caiku Albatross 46 y 80.

Adaptado a Tiresias del controlador ``brailleDisplayDrivers/albatross`` de
NVDA (NonVisual Desktop Access), Copyright (C) 2023-2025 NV Access Limited,
Burman's Computer and Education Ltd. y Leonard de Ruijter, distribuido bajo
la Licencia Pública General de GNU versión 2. Tiresias se distribuye bajo la
GPL versión 2 o posterior.

Conexión: la línea lleva un chip USB-serie FTDI (``VID_0403&PID_6001``) que
comparten muchos otros aparatos. Se reconoce por la descripción que da el
bus USB, «Albatross Braille Display»; con esa descripción participa en la
detección automática (también después de que otros controladores hayan
probado el mismo puerto). Elegida a mano, se prueban todos los puertos FTDI.
Velocidad: 19200 baudios (la de fábrica) y, si no responde, 9600; 8 bits,
sin paridad, un bit de parada.

Protocolo:

- mientras no hay conexión, la línea envía sin parar paquetes de
  inicialización ``FF <ajustes>``; el ordenador contesta ``FE FD`` y la
  línea deja de enviarlos. También los envía al salir de su menú interno o
  si pasa unos 2 segundos sin recibir nada (por eso se envía ``FB FC`` si
  no se ha escrito nada en 1,5 segundos). Al reconectar así se vuelve a
  enviar todo el contenido.
- byte de ajustes (bits empezando por el más significativo): bit 0, 46 (0)
  u 80 (1) celdas; bits 1 y 3, distribución de las teclas (normal, lados
  intercambiados o todas como las de un lado); bit 2 y bits 4-7, celdas de
  estado (no se usan). Solo se aceptan ajustes hasta ``FE``: con ``FF`` hay
  que reducir las celdas de estado en el menú de la línea (máximo 14).
- celdas: ``FB`` + pares (posición desde 1, celda con los bits invertidos)
  de las celdas que han cambiado + ``FC``.
- teclas: un byte por tecla. Las teclas de control (F1, F2, F7, F8, F9,
  F10, F15, F16, inicio, fin, cursor, cursor «e» y atributos) empiezan una
  combinación de hasta 4 teclas que termina repitiendo la primera
  (``f1 f1`` es F1 sola; ``f1 f2 f3 f1`` es F1+F2+F3). Los botones de
  enrutamiento van de 2 a 41 y de 111 a 150 (fila inferior) y de 43 a 82 y
  de 152 a 191 (fila superior).

Nombres de teclas (gestos ``br(albatross):...``): ``f1``...``f16``,
``home1``/``home2``, ``end1``/``end2``, ``eCursor1``/``eCursor2``,
``cursor1``/``cursor2``, ``up1``...``up3``, ``down1``...``down3``, ``left``,
``right``, ``lWheelUp``/``Down``/``Left``/``Right``, ``rWheel...``,
``attribute1``...``attribute4``, ``routing``/``multiRouting`` (fila
inferior) y ``routing2``/``multiRouting2`` (fila superior; NVDA la llama
``secondRouting``).
"""

from __future__ import annotations

import threading
import time
from typing import Any

from ... import queue_handler
from ...i18n import _
from ...log import getLogger
from .base import DeviceMatch, DisplayNotFound, HardwareDriver
from .ports import DeviceInfo

log = getLogger("braille.albatross")

#: Velocidades que se prueban (la de fábrica primero).
BAUD_RATES = (19200, 9600)
USB_ID = "VID_0403&PID_6001"
BUS_DEVICE_DESC = "Albatross Braille Display"

INIT_START = 0xFF
MAX_SETTINGS = 0xFE
ESTABLISHED = b"\xfe\xfd"
START_BYTE = 0xFB
END_BYTE = 0xFC
BOTH_BYTES = b"\xfb\xfc"
#: Segundos sin escribir tras los que se envía ``FB FC`` para mantener la conexión.
KC_INTERVAL = 1.5
#: Segundos de espera de los paquetes de inicialización en cada velocidad.
INIT_TIMEOUT = 2.5
#: Paquetes iguales seguidos que se exigen al conectar (evita confundirlos
#: con datos leídos a otra velocidad).
INIT_PACKETS_REQUIRED = 2
#: Vaciados del búfer del puerto antes de conectar (como NVDA).
RESET_COUNT = 10
RESET_SLEEP = 0.05
MAX_COMBINATION_KEYS = 4
MAX_STATUS_CELLS_ALLOWED = 14
MAX_IDENTIFY_BUFFER = 512

#: Código -> nombre de las teclas.
KEYS = {
	1: "attribute1",
	42: "attribute2",
	83: "f1",
	84: "f2",
	85: "f3",
	86: "f4",
	87: "f5",
	88: "f6",
	89: "f7",
	90: "f8",
	91: "home1",
	92: "end1",
	93: "eCursor1",
	94: "cursor1",
	95: "up1",
	96: "down1",
	97: "left",
	98: "up2",
	103: "lWheelRight",
	104: "lWheelLeft",
	105: "lWheelUp",
	106: "lWheelDown",
	151: "attribute3",
	192: "attribute4",
	193: "f9",
	194: "f10",
	195: "f11",
	196: "f12",
	197: "f13",
	198: "f14",
	199: "f15",
	200: "f16",
	201: "home2",
	202: "end2",
	203: "eCursor2",
	204: "cursor2",
	205: "up3",
	206: "down2",
	207: "right",
	208: "down3",
	213: "rWheelRight",
	214: "rWheelLeft",
	215: "rWheelUp",
	216: "rWheelDown",
}
_CODES = {name: code for code, name in KEYS.items()}

#: Teclas que pueden empezar una combinación.
CONTROL_KEY_CODES = frozenset(
	_CODES[n]
	for n in (
		"attribute1",
		"attribute2",
		"f1",
		"f2",
		"f7",
		"f8",
		"home1",
		"end1",
		"eCursor1",
		"cursor1",
		"attribute3",
		"attribute4",
		"f9",
		"f10",
		"f15",
		"f16",
		"home2",
		"end2",
		"eCursor2",
		"cursor2",
	)
)

#: Tecla del lado izquierdo -> la equivalente del lado derecho.
LEFT_RIGHT_KEY_CODES = {
	_CODES[left]: _CODES[right]
	for left, right in (
		("attribute1", "attribute3"),
		("attribute2", "attribute4"),
		("f1", "f9"),
		("f2", "f10"),
		("f3", "f11"),
		("f4", "f12"),
		("f5", "f13"),
		("f6", "f14"),
		("f7", "f15"),
		("f8", "f16"),
		("home1", "home2"),
		("end1", "end2"),
		("eCursor1", "eCursor2"),
		("cursor1", "cursor2"),
		("up1", "up3"),
		("down1", "down2"),
		("lWheelRight", "rWheelRight"),
		("lWheelLeft", "rWheelLeft"),
		("lWheelUp", "rWheelUp"),
		("lWheelDown", "rWheelDown"),
	)
}
_RIGHT_LEFT_KEY_CODES = {right: left for left, right in LEFT_RIGHT_KEY_CODES.items()}

#: Máscara de la distribución de teclas en ``ajustes >> 4``.
KEY_LAYOUT_MASK = 5
LAYOUT_NORMAL = 0
LAYOUT_BOTH_AS_RIGHT = 1
LAYOUT_SWITCHED = 4
LAYOUT_BOTH_AS_LEFT = 5

#: (grupo, primer código, último código, desplazamiento del índice).
ROUTING_KEY_RANGES = (
	("routing", 2, 41, 2),
	("routing2", 43, 82, 43),
	("routing", 111, 150, 71),
	("routing2", 152, 191, 112),
)


def routingKey(code: int) -> tuple[str, int] | None:
	"""``("routing"|"routing2", índice)`` si el código es de enrutamiento."""
	for group, start, end, offset in ROUTING_KEY_RANGES:
		if start <= code <= end:
			return group, code - offset
	return None


def reverseBits(cell: int) -> int:
	"""La Albatross espera los puntos en orden inverso (punto 1 en el bit 7)."""
	return int(f"{cell & 0xFF:08b}"[::-1], 2)


def changeKeyValues(codes: list[int], layout: int) -> list[int]:
	"""Aplica la distribución de teclas elegida en el menú de la línea."""
	out = []
	for code in codes:
		if layout == LAYOUT_SWITCHED:
			code = LEFT_RIGHT_KEY_CODES.get(code, _RIGHT_LEFT_KEY_CODES.get(code, code))
		elif layout == LAYOUT_BOTH_AS_RIGHT:
			code = LEFT_RIGHT_KEY_CODES.get(code, code)
		elif layout == LAYOUT_BOTH_AS_LEFT:
			code = _RIGHT_LEFT_KEY_CODES.get(code, code)
		out.append(code)
	return out


class AlbatrossDriver(HardwareDriver):
	name = "albatross"
	description = _("Caiku Albatross 46/80")
	usbSerialIds = frozenset({USB_ID})
	genericUsbIds = frozenset({USB_ID})
	tryClaimedPorts = True
	baudRate = BAUD_RATES[0]
	keyOrder = (
		["attribute1", "attribute2", "attribute3", "attribute4"]
		+ [f"f{i}" for i in range(1, 17)]
		+ ["home1", "end1", "eCursor1", "cursor1", "home2", "end2", "eCursor2", "cursor2"]
		+ ["up1", "up2", "up3", "down1", "down2", "down3", "left", "right"]
		+ [f"{w}Wheel{d}" for w in ("l", "r") for d in ("Up", "Down", "Left", "Right")]
	)
	gestureMap = {
		"home1": "review_top",
		"home2": "review_top",
		"end1": "review_bottom",
		"end2": "review_bottom",
		"eCursor1": "navigatorObject_toFocus",
		"eCursor2": "navigatorObject_toFocus",
		"cursor1": "braille_toFocus",
		"cursor2": "braille_toFocus",
		"home1+home2": "moveMouseToNavigatorObject",
		"end1+end2": "moveNavigatorObjectToMouse",
		"eCursor1+eCursor2": "navigatorObject_moveFocus",
		"cursor1+cursor2": "braille_toggleTether",
		"up1": "braille_previousLine",
		"up2": "braille_previousLine",
		"up3": "braille_previousLine",
		"down1": "braille_nextLine",
		"down2": "braille_nextLine",
		"down3": "braille_nextLine",
		"left": "braille_scrollBack",
		"lWheelLeft": "braille_scrollBack",
		"rWheelLeft": "braille_scrollBack",
		"right": "braille_scrollForward",
		"lWheelRight": "braille_scrollForward",
		"rWheelRight": "braille_scrollForward",
		"routing": "braille_routeTo",
		"home1+multiRouting": "braille_selectRange",
		"home2+multiRouting": "braille_selectRange",
		"routing2": "braille_reportFormatting",
		"attribute1+attribute3": "braille_cycleFocusContextPresentation",
		"attribute2+attribute4": "speechMode",
		"f1": "reviewMode_previous",
		"f2": "reviewMode_next",
		"f3": "navigatorObject_parent",
		"f4": "navigatorObject_firstChild",
		"f5": "navigatorObject_previous",
		"f6": "navigatorObject_next",
		"f7": "navigatorObject_current",
		"f8": "navigatorObject_currentDimensions",
		"f1+home1": "activateBrailleSettingsDialog",
		"f9+home2": "activateBrailleSettingsDialog",
		"f1+end1": "reviewCursorToStatusLine",
		"f9+end2": "reviewCursorToStatusLine",
		"f1+eCursor1": "braille_cycleCursorShape",
		"f9+eCursor2": "braille_cycleCursorShape",
		"f1+cursor1": "braille_toggleShowCursor",
		"f9+cursor2": "braille_toggleShowCursor",
		"f1+f2": "braille_cycleShowMessages",
		"f9+f10": "braille_cycleShowMessages",
		"f1+f5": "braille_toggleShowSelection",
		"f9+f14": "braille_toggleShowSelection",
		"f1+f3": "braille_cycleReviewRoutingMovesSystemCaret",
		"f9+f11": "braille_cycleReviewRoutingMovesSystemCaret",
		"f7+f8": "review_activate",
		"f9": "dateTime",
		"f10": "sayBatteryStatus",
		"f11": "title",
		"f12": "reportStatusLine",
		"f13": "reportCurrentLine",
		"f14": "sayAll",
		"f15": "review_currentCharacter",
		"f16": "review_currentLine",
		"f15+f16": "review_currentWord",
		"lWheelUp": "review_previousLine",
		"rWheelUp": "review_previousLine",
		"lWheelDown": "review_nextLine",
		"rWheelDown": "review_nextLine",
		"attribute1": "kb:windows+d",
		"attribute2": "kb:windows+e",
		"attribute3": "kb:windows+b",
		"attribute4": "kb:windows+i",
	}
	keyDescriptions = {
		**{f"f{i}": _("tecla de función F{n}").format(n=i) for i in range(1, 17)},
		"home1": _("tecla Inicio izquierda (home1)"),
		"home2": _("tecla Inicio derecha (home2)"),
		"end1": _("tecla Fin izquierda (end1)"),
		"end2": _("tecla Fin derecha (end2)"),
		"eCursor1": _("tecla de cursor «e» izquierda (eCursor1)"),
		"eCursor2": _("tecla de cursor «e» derecha (eCursor2)"),
		"cursor1": _("tecla de cursor izquierda (cursor1)"),
		"cursor2": _("tecla de cursor derecha (cursor2)"),
		"up1": _("tecla arriba izquierda (up1)"),
		"up2": _("tecla arriba central (up2, modelo de 80)"),
		"up3": _("tecla arriba derecha (up3)"),
		"down1": _("tecla abajo izquierda (down1)"),
		"down2": _("tecla abajo derecha (down2)"),
		"down3": _("tecla abajo central (down3, modelo de 80)"),
		"left": _("tecla de desplazamiento izquierda"),
		"right": _("tecla de desplazamiento derecha"),
		"lWheelUp": _("rueda izquierda hacia arriba"),
		"lWheelDown": _("rueda izquierda hacia abajo"),
		"lWheelLeft": _("rueda izquierda hacia la izquierda"),
		"lWheelRight": _("rueda izquierda hacia la derecha"),
		"rWheelUp": _("rueda derecha hacia arriba"),
		"rWheelDown": _("rueda derecha hacia abajo"),
		"rWheelLeft": _("rueda derecha hacia la izquierda"),
		"rWheelRight": _("rueda derecha hacia la derecha"),
		"attribute1": _("tecla de atributo 1 (izquierda)"),
		"attribute2": _("tecla de atributo 2 (izquierda)"),
		"attribute3": _("tecla de atributo 3 (derecha)"),
		"attribute4": _("tecla de atributo 4 (derecha)"),
		"routing": _("botón de enrutamiento de la fila inferior"),
		"multiRouting": _("varios botones de enrutamiento de la fila inferior (con una tecla de control)"),
		"routing2": _("botón de enrutamiento de la fila superior"),
		"multiRouting2": _("varios botones de la fila superior (con una tecla de control)"),
	}

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		self._buffer = bytearray()
		self._keyLayout = LAYOUT_NORMAL
		self._settings: int | None = None
		self._statusCellsProblem = False
		self._statusCellsWarned = False
		#: Byte de inicialización recibido, falta el de ajustes.
		self._waitingSettings = False
		#: Combinación de teclas de control a medio recibir.
		self._ctrlPacket: list[int] = []
		#: Celdas mostradas (solo se envían las que cambian) y las últimas pedidas.
		self._oldCells: list[int] = []
		self._lastCells: list[int] = []
		self._displayLock = threading.Lock()
		self._writeTime = 0.0
		self._kcStop = threading.Event()
		self._kcThread: threading.Thread | None = None
		super().__init__(*args, **kwargs)

	# ------------------------------------------------------------ puertos
	@classmethod
	def _albatrossSerials(cls, devices: list[DeviceInfo]) -> set[str] | None:
		"""Números de serie de las Albatross USB presentes (``None`` si no hay ninguna)."""
		boards = [d for d in devices if d.kind == "usb" and d.usbId == USB_ID and (d.extra.get("busReportedDeviceDescription") or "").strip() == BUS_DEVICE_DESC]
		if not boards:
			return None
		serials = set()
		for d in boards:
			last = (d.extra.get("instanceId") or "").rsplit("\\", 1)[-1].upper()
			# Sin número de serie, Windows inventa un identificador con «&».
			if last and "&" not in last:
				serials.add(last)
		return serials

	@classmethod
	def getMatches(cls, devices: list[DeviceInfo], usb: bool = True, bluetooth: bool = True, allowGeneric: bool = True) -> list[DeviceMatch]:
		"""Solo los puertos FTDI de una Albatross (por la descripción del bus USB)."""
		if not usb:
			return []
		serials = cls._albatrossSerials(devices)
		if serials is None:
			return []
		out = []
		for dev in devices:
			if dev.kind != "serial" or dev.bluetooth or dev.usbId != USB_ID:
				continue
			instance = (dev.extra.get("instanceId") or "").upper()
			if serials and instance and not any(f"+{s}" in instance for s in serials):
				continue
			out.append(DeviceMatch("serial", dev.usbId, dev.path, False, dev))
		return out

	@classmethod
	def candidateMatches(cls, port: str) -> list[DeviceMatch]:
		from . import ports

		port = port or "auto"
		if port.upper().startswith("COM"):
			return super().candidateMatches(port)
		if port not in ("auto", "usb"):
			return []
		devices = ports.listAll()
		matches = cls.getMatches(devices)
		if matches:
			return matches
		# Elegida a mano: también los puertos FTDI sin la descripción del bus.
		return [DeviceMatch("serial", d.usbId, d.path, False, d) for d in devices if d.kind == "serial" and not d.bluetooth and d.usbId == USB_ID]

	# ------------------------------------------------------------ conexión
	def _connect(self, match: DeviceMatch) -> None:
		problemBaud = 0
		for baud in BAUD_RATES:
			self._closeIo()
			with self._cond:
				self._resetState()
				self._statusCellsProblem = False
			self.numCells = 0
			self._io = self._open(match, baudrate=baud, parity="N", stopBits=1)
			self._resetBuffers()
			self._waitFor(lambda: self._settings is not None or self._statusCellsProblem, INIT_TIMEOUT)
			if self._statusCellsProblem:
				# Puede ser ruido de leer a otra velocidad: se prueba la siguiente.
				problemBaud = baud
				continue
			if self._settings is None:
				continue
			with self._cond:
				settings = self._settings
				self._buffer.clear()
				self._waitingSettings = False
			self._write(ESTABLISHED)
			self._writeTime = time.monotonic()
			self._applySettings(settings)
			log.debug("Albatross a %d baudios, ajustes %02x", baud, settings)
			self._startKeepAlive()
			return
		if problemBaud:
			if problemBaud == BAUD_RATES[-1]:
				# Que la línea deje de enviar paquetes de inicialización.
				self._write(ESTABLISHED)
			self._warnStatusCells()
			raise DisplayNotFound("La Albatross tiene demasiadas celdas de estado")
		raise DisplayNotFound("La Albatross no ha enviado paquetes de inicialización")

	def _initConnection(self, match: DeviceMatch) -> None:
		# Conexiones ya abiertas (pruebas): se espera el paquete de inicialización.
		pass

	def _resetBuffers(self) -> None:
		"""Vacía varias veces el búfer del puerto (puede haber restos de otras pruebas)."""
		purge = getattr(self._io, "purge", None)
		if purge is None:
			return
		for _i in range(RESET_COUNT):
			try:
				purge()
			except Exception:
				log.debug("No se pudo vaciar el búfer del puerto", exc_info=True)
				break
			time.sleep(RESET_SLEEP)
		with self._cond:
			# Lo que llegara antes del vaciado (restos de otras pruebas) no cuenta.
			self._buffer.clear()
			self._settings = None
			self._statusCellsProblem = False

	def _resetState(self) -> None:
		self._buffer.clear()
		self._settings = None
		self._waitingSettings = False
		self._ctrlPacket = []
		self._kcStop.set()

	def _applySettings(self, settings: int) -> None:
		cells = 80 if settings >> 7 else 46
		self._keyLayout = (settings >> 4) & KEY_LAYOUT_MASK
		with self._displayLock:
			if len(self._oldCells) != cells:
				self._oldCells = [0] * cells
		self.model = f"Albatross{cells}"
		self.deviceName = f"Caiku Albatross {cells}"
		self.numCells = cells

	def _warnStatusCells(self) -> None:
		if self._statusCellsWarned:
			return
		self._statusCellsWarned = True
		msg = _(
			"Para usar la Albatross con Tiresias, reduce en el menú interno de la línea el número de celdas de estado a {maxCells} como máximo y reinicia la línea si hace falta."
		).format(maxCells=MAX_STATUS_CELLS_ALLOWED)
		log.warning(msg)
		from .base import _announce

		queue_handler.queueFunction(_announce, msg)

	# ------------------------------------------------------------ mantener la conexión
	def _startKeepAlive(self) -> None:
		self._kcStop = threading.Event()
		self._kcThread = threading.Thread(target=self._keepAliveLoop, args=(self._kcStop,), name="braille-albatross-kc", daemon=True)
		self._kcThread.start()

	def _keepAliveLoop(self, stop: threading.Event) -> None:
		while not stop.is_set() and not self._terminated:
			wait = KC_INTERVAL - (time.monotonic() - self._writeTime)
			if wait > 0:
				if stop.wait(wait):
					return
				continue
			if self._io is None:
				return
			self._keepAliveTick()

	def _keepAliveTick(self) -> None:
		"""Envía ``FB FC`` si no se ha escrito nada en :data:`KC_INTERVAL` segundos."""
		if self._io is None or self.numCells <= 0:
			return
		if time.monotonic() - self._writeTime >= KC_INTERVAL:
			self._send(BOTH_BYTES)

	def _stopKeepAlive(self) -> None:
		self._kcStop.set()
		thread = self._kcThread
		self._kcThread = None
		if thread is not None and thread.is_alive() and thread is not threading.current_thread():
			thread.join(1.0)

	def _send(self, data: bytes) -> None:
		self._writeTime = time.monotonic()
		try:
			self._write(data)
		except Exception:
			log.debug("Error escribiendo en la Albatross", exc_info=True)

	# ------------------------------------------------------------ entrada
	def _handleData(self, data: bytes) -> None:
		if self.numCells <= 0:
			self._identify(data)
			return
		settings = None
		for byte in data:
			if self._waitingSettings:
				self._waitingSettings = False
				if byte <= MAX_SETTINGS:
					settings = byte
				else:
					self._statusCellsProblem = True
				continue
			if byte == INIT_START:
				self._waitingSettings = True
				self._ctrlPacket = []
				continue
			self._handleKeyByte(byte)
		if self._statusCellsProblem:
			self._statusCellsProblem = False
			self._send(ESTABLISHED)
			self._warnStatusCells()
		elif settings is not None:
			# La línea ha vuelto a pedir la conexión (menú interno, apagado o
			# demasiado tiempo sin datos): se confirma y se envía todo de nuevo.
			self._send(ESTABLISHED)
			self._applySettings(settings)
			self._redraw()

	def _identify(self, data: bytes) -> None:
		"""Mientras se conecta: busca paquetes de inicialización iguales seguidos."""
		buf = self._buffer
		buf.extend(data)
		needed = 2 * INIT_PACKETS_REQUIRED
		for i in range(len(buf) - needed + 1):
			if buf[i] != INIT_START:
				continue
			settings = buf[i + 1]
			if settings == INIT_START:
				# ``FF FF``: el byte de ajustes valdría FF (demasiadas celdas de estado).
				if bytes(buf[i : i + needed]) == bytes([INIT_START]) * needed:
					self._statusCellsProblem = True
					return
				continue
			if all(buf[i + 2 * k] == INIT_START and buf[i + 2 * k + 1] == settings for k in range(INIT_PACKETS_REQUIRED)):
				self._settings = settings
				return
		if len(buf) > MAX_IDENTIFY_BUFFER:
			del buf[:-needed]

	def _handleKeyByte(self, byte: int) -> None:
		packet = self._ctrlPacket
		if packet:
			packet.append(byte)
			if byte == packet[0]:
				self._ctrlPacket = []
				self._fireKeys(packet)
			elif len(packet) > MAX_COMBINATION_KEYS:
				log.debug("Albatross: combinación no válida %r", packet)
				self._ctrlPacket = []
			return
		if byte in CONTROL_KEY_CODES:
			self._ctrlPacket = [byte]
			return
		self._fireKeys([byte])

	def _fireKeys(self, codes: list[int]) -> None:
		if self._keyLayout != LAYOUT_NORMAL:
			codes = changeKeyValues(codes, self._keyLayout)
		chord: set = set()
		for code in set(codes):
			routing = routingKey(code)
			if routing is not None:
				if routing[1] < self.numCells:
					chord.add(routing)
			elif code in KEYS:
				chord.add(KEYS[code])
			else:
				log.debug("Albatross: tecla desconocida %d", code)
		if chord:
			self._fireChord(chord)

	# ------------------------------------------------------------ salida
	def _writeCells(self, cells: list[int]) -> None:
		with self._displayLock:
			self._lastCells = list(cells)
			packet = self._diffPacket(cells)
		if packet:
			self._send(packet)

	def _diffPacket(self, cells: list[int]) -> bytes:
		"""``FB`` + (posición, celda) de las celdas que han cambiado + ``FC``."""
		if len(self._oldCells) < len(cells):
			self._oldCells += [0] * (len(cells) - len(self._oldCells))
		out = bytearray((START_BYTE,))
		for i, cell in enumerate(cells):
			if cell != self._oldCells[i]:
				self._oldCells[i] = cell
				out += bytes((i + 1, reverseBits(cell)))
		if len(out) == 1:
			return b""
		out.append(END_BYTE)
		return bytes(out)

	def _redraw(self) -> None:
		"""Tras reconectar: la línea está en blanco, se envía todo lo que había."""
		with self._displayLock:
			self._oldCells = [0] * self.numCells
			cells = (self._lastCells + [0] * self.numCells)[: self.numCells]
			packet = self._diffPacket(cells)
		if packet:
			self._send(packet)

	def _onIoError(self, code: int) -> None:
		self._stopKeepAlive()
		super()._onIoError(code)

	def terminate(self) -> None:
		self._stopKeepAlive()
		super().terminate()


BrailleDisplayDriver = AlbatrossDriver
