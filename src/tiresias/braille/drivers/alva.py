"""Líneas braille Optelec ALVA de la serie 6 (protocolo BC6).

Modelos: ALVA BC640 y BC680, ALVA 640 Comfort, Easylink 12 Touch y el
convertidor de protocolo de Optelec (para usar líneas antiguas, como la
Braille Voyager o la Satellite, con el protocolo BC6).

Conexiones:

- **USB HID** (y HID por Bluetooth): las celdas y el estado se leen con
  informes de características (``0x05`` ajustes de pantalla, ``0x06``
  ajustes de teclas, ``0x0A`` reloj), las teclas llegan en el informe de
  entrada ``0x04`` y las celdas se escriben con el informe de salida
  ``0x02`` (como mucho 40 celdas por informe).
- **Bluetooth (puerto serie)**: mensajes ``ESC <orden> <valor>`` de longitud
  fija según la orden.

Nombres de las teclas (gestos ``br(alva):...``): ``t1``...``t5`` (teclas de
pulgar), ``etouch1``...``etouch4``, ``sp1``...``sp4``, ``spUp``,
``spDown``, ``spLeft``, ``spRight`` y ``spEnter`` (Smartpad), ``routing``
y ``multiRouting`` (fila de enrutamiento), ``routing2`` y
``multiRouting2`` (segunda fila), y el teclado braille de la 640 Comfort y
la Easylink: ``dot1``...``dot8``, ``space``, ``control``, ``windows``,
``alt`` y ``enter``. La BC680 y el convertidor tienen dos juegos de teclas
de pulgar y de Smartpad (izquierdo y derecho): los dos usan los mismos
nombres.

El teclado braille de la línea solo escribe a través de Tiresias si la
«simulación de teclado HID» de la línea está desactivada (si está activada,
la línea traduce y escribe por sí misma como un teclado). La orden
:meth:`AlvaDriver.script_toggleHidKeyboardInput` (``t1+spEnter``) la
cambia y la guarda en el ajuste del controlador ``hidKeyboardInput``
(también en Opciones, categoría «Braille»), que se aplica a la línea cada vez
que se conecta.

La línea puede reservar parte de sus celdas para sus funciones internas
(«punto de división» o *split point*): cuando cambia un ajuste interno la
línea lo avisa y Tiresias vuelve a leer el número de celdas.
"""

from __future__ import annotations

import datetime
import re
import threading
from typing import Callable, Iterable

from ... import queue_handler
from ...baseobject import script
from ...i18n import _
from ...log import getLogger
from .base import BrailleGesture, DeviceMatch, DisplayNotFound, DriverSetting, HardwareDriver, buildGesture

log = getLogger("braille.alva")

ESC = 0x1B

# ------------------------------------------------------------------ HID
#: Informe de salida con las celdas: id, desplazamiento, número de celdas, celdas.
HID_OUTPUT_REPORT = 0x02
#: Celdas como máximo en cada informe de salida.
HID_OUTPUT_MAX_CELLS = 40
#: Informe de entrada de teclas: id, número de tecla, grupo.
HID_KEY_REPORT = 0x04
#: Informe de características con los ajustes de pantalla.
HID_DISPLAY_SETTINGS = 0x05
#: Posición del lado de las celdas de estado (un valor > 1 indica un informe defectuoso).
HID_STATUS_SIDE_POS = 2
#: Posición del número de celdas.
HID_CELL_COUNT_POS = 6
#: Informe de características con los ajustes de teclas (byte 1, bits).
HID_KEY_SETTINGS = 0x06
#: Bits de «teclado en bruto» (simulación de teclado HID desactivada).
RAW_INPUT_MASK = 0x30
#: Informe de características del reloj (año en dos bytes, mes, día, hora, minuto, segundo).
HID_RTC_REPORT = 0x0A
RTC_LENGTH = 7
#: Diferencia (segundos) a partir de la cual se pone en hora el reloj de la línea.
RTC_MAX_DRIFT = 5

# ------------------------------------------------------------------ serie
#: Longitud del valor de cada orden del protocolo serie (Bluetooth).
SERIAL_LENGTHS = {
	ord("T"): 2,  # celdas de estado
	ord("S"): 1,  # punto de división
	ord("D"): 1,  # presión de los puntos
	ord("O"): 1,  # tabla braille de salida
	ord("I"): 1,  # tabla braille de entrada
	ord("F"): 4,  # respuesta de las teclas
	ord("P"): 1,  # repetición de teclas
	ord("2"): 3,  # emulación de la segunda fila de enrutamiento
	ord("L"): 3,  # idioma
	ord("R"): 1,  # Bluetooth activado
	ord("V"): 5,  # versiones de hardware y firmware
	ord("G"): 9,  # batería
	ord("H"): RTC_LENGTH,  # fecha y hora
	ord("?"): 1,  # identificador del aparato
	ord("E"): 1,  # número de celdas
	ord("N"): 12,  # números de serie
	ord("X"): 1,  # estado de la conexión Bluetooth
	ord("k"): 1,  # interfaz de teclado HID estándar
	ord("r"): 1,  # mensajes de teclado en bruto
	ord("h"): 8,  # mensajes HID por serie
	ord("K"): 2,  # tecla: grupo y número
}

# ------------------------------------------------------------------ teclas
RELEASE_MASK = 0x80
SECOND_ROW_MASK = 0x80
SPECIAL_GROUP = 0x01
SETTINGS_CHANGED = 0x01
THUMB_GROUP = 0x71
ETOUCH_GROUP = 0x72
SMARTPAD_GROUP = 0x73
ROUTING_GROUP = 0x74
KEYBOARD_GROUP = 0x78

THUMB_KEYS = ("t1", "t2", "t3", "t4", "t5")
SMARTPAD_KEYS = ("sp1", "sp2", "spLeft", "spEnter", "spUp", "spDown", "spRight", "sp3", "sp4")
ETOUCH_KEYS = ("etouch1", "etouch2", "etouch3", "etouch4")
#: Teclado braille (640 Comfort, Easylink): número -> nombre (empieza en 1).
KEYBOARD_KEYS = {
	1: "dot1",
	2: "dot2",
	3: "dot3",
	4: "dot4",
	5: "dot5",
	6: "dot6",
	7: "dot7",
	8: "dot8",
	9: "control",
	10: "windows",
	11: "space",
	12: "alt",
	13: "enter",
}
#: Sufijo interno de las teclas del juego derecho (BC680): se quita al crear el gesto.
RIGHT_SUFFIX = "@r"

#: Identificador del aparato -> (modelo, nombre).
MODELS = {
	0x40: ("BC640", "ALVA BC640"),
	0x80: ("BC680", "ALVA BC680"),
	0x99: ("ProtocolConverter", ""),
}

_PID_RE = re.compile(r"PID_([0-9A-F]{4})", re.I)

#: Ajuste guardado: ``True`` = la línea simula un teclado HID (escribe por sí misma).
HID_KEYBOARD_SETTING = "hidKeyboardInput"


def _notSupportedMessage() -> str:
	return _("Esta línea no permite cambiar la simulación de teclado HID")


def _speak(text: str) -> None:
	"""Hilo del núcleo: habla (y muestra en braille) un mensaje."""
	from ... import speech

	try:
		speech.speakMessage(text)
	except Exception:
		log.debug("No se pudo anunciar: %s", text, exc_info=True)


class AlvaDriver(HardwareDriver):
	name = "alva"
	description = _("Optelec ALVA BC640/BC680, ALVA 640 Comfort, Easylink 12 Touch y convertidor de protocolo")
	usbHidIds = frozenset(
		{
			"VID_0798&PID_0640",  # BC640 (y 640 Comfort)
			"VID_0798&PID_0680",  # BC680
			"VID_0798&PID_0699",  # convertidor de protocolo USB
		}
	)
	bluetoothPrefixes = ("ALVA ",)
	baudRate = 9600
	driverSettings = (
		DriverSetting(HID_KEYBOARD_SETTING, _("Simulación de teclado HID de la ALVA activa (la línea escribe como un teclado USB)"), "bool", False),
	)
	keyOrder = [
		"t1",
		"t2",
		"t3",
		"t4",
		"t5",
		"etouch1",
		"etouch2",
		"etouch3",
		"etouch4",
		"sp1",
		"sp2",
		"sp3",
		"sp4",
		"spUp",
		"spDown",
		"spLeft",
		"spRight",
		"spEnter",
		"control",
		"windows",
		"alt",
		"enter",
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
		# Teclas de pulgar: desplazamiento y líneas.
		"t1": "braille_scrollBack",
		"t2": "braille_previousLine",
		"t3": "braille_toFocus",
		"t4": "braille_nextLine",
		"t5": "braille_scrollForward",
		"t1+t2": "review_top",
		"t4+t5": "review_bottom",
		"t1+t3": "braille_toggleTether",
		"t1+t4": "braille_cycleCursorShape",
		"t2+t5": "braille_toggleShowCursor",
		"t2+t3": "reportCurrentLine",
		"t3+t4": "reportCurrentFocus",
		# eTouch.
		"etouch1": "braille_scrollBack",
		"etouch2": "title",
		"etouch3": "braille_scrollForward",
		"etouch4": "reportStatusLine",
		# Enrutamiento.
		"routing": "braille_routeTo",
		"multiRouting": "braille_selectRange",
		"routing2": "braille_reportFormatting",
		# Smartpad.
		"sp1": "kb:shift+tab",
		"sp2": "kb:alt",
		"sp3": "kb:escape",
		"sp4": "kb:tab",
		"spUp": "kb:upArrow",
		"spDown": "kb:downArrow",
		"spLeft": "kb:leftArrow",
		"spRight": "kb:rightArrow",
		"spEnter": "kb:enter",
		"sp1+sp2": "kb:windows",
		"sp1+sp3": "showGui",
		"sp1+sp4": "kb:windows+d",
		"sp2+sp3": "dateTime",
		"sp2+sp4": "kb:alt+tab",
		"sp3+sp4": "kb:windows+b",
		"t3+spUp": "kb:control+home",
		"t3+spDown": "kb:control+end",
		"t3+spLeft": "kb:home",
		"t3+spRight": "kb:end",
		"t2+spUp": "kb:pageUp",
		"t2+spDown": "kb:pageDown",
		# Teclado braille (640 Comfort, Easylink).
		"control": "kb:control",
		"windows": "kb:windows",
		"alt": "kb:alt",
		"enter": "kb:enter",
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
	keyDescriptions = {
		"t1": _("primera tecla de pulgar (la de la izquierda)"),
		"t2": _("segunda tecla de pulgar"),
		"t3": _("tecla de pulgar central"),
		"t4": _("cuarta tecla de pulgar"),
		"t5": _("quinta tecla de pulgar (la de la derecha)"),
		"etouch1": _("tecla eTouch 1 (izquierda, arriba)"),
		"etouch2": _("tecla eTouch 2 (izquierda, abajo)"),
		"etouch3": _("tecla eTouch 3 (derecha, arriba)"),
		"etouch4": _("tecla eTouch 4 (derecha, abajo)"),
		"sp1": _("tecla Smartpad F1"),
		"sp2": _("tecla Smartpad F2"),
		"sp3": _("tecla Smartpad F3"),
		"sp4": _("tecla Smartpad F4"),
		"spUp": _("flecha arriba del Smartpad"),
		"spDown": _("flecha abajo del Smartpad"),
		"spLeft": _("flecha izquierda del Smartpad"),
		"spRight": _("flecha derecha del Smartpad"),
		"spEnter": _("tecla Intro del Smartpad (centro de las flechas)"),
		"routing": _("botón de enrutamiento sobre una celda"),
		"multiRouting": _("dos botones de enrutamiento a la vez"),
		"routing2": _("botón de la segunda fila de enrutamiento"),
		"multiRouting2": _("dos botones de la segunda fila de enrutamiento a la vez"),
		"dot1": _("punto 1 del teclado braille"),
		"dot2": _("punto 2 del teclado braille"),
		"dot3": _("punto 3 del teclado braille"),
		"dot4": _("punto 4 del teclado braille"),
		"dot5": _("punto 5 del teclado braille"),
		"dot6": _("punto 6 del teclado braille"),
		"dot7": _("punto 7 del teclado braille"),
		"dot8": _("punto 8 del teclado braille"),
		"space": _("barra espaciadora del teclado braille"),
		"control": _("tecla Control del teclado braille"),
		"windows": _("tecla Windows del teclado braille"),
		"alt": _("tecla Alt del teclado braille"),
		"enter": _("tecla Intro del teclado braille"),
	}

	def __init__(self, *args, **kwargs) -> None:
		self._isHid = False
		self._buffer = bytearray()
		#: Identificador del aparato (0x40, 0x80, 0x99...).
		self._deviceId: int | None = None
		#: La línea envía las teclas del teclado braille en bruto (simulación HID desactivada).
		self._rawInput = False
		#: Respuesta recibida a la consulta «r ?» (protocolo serie).
		self._rawAnswered = False
		super().__init__(*args, **kwargs)

	def _wantedRawInput(self) -> bool:
		"""Modo del teclado guardado en la configuración (``True``: teclas en bruto)."""
		return not bool(self.getSetting(HID_KEYBOARD_SETTING))

	# ============================================================ conexión
	def _connect(self, match: DeviceMatch) -> None:
		self._deviceId = None
		self._buffer.clear()
		self._rawInput = False
		self.numCells = 0
		self._isHid = match.type == "hid"
		if self._isHid:
			self._connectHid(match)
		else:
			self._connectSerial(match)
		self._setModel()

	def _connectHid(self, match: DeviceMatch) -> None:
		self._io = self._open(match, exclusive=False)
		self._deviceId = self._hidDeviceId(match)
		try:
			self._readHidSettings()
		except OSError as e:
			raise DisplayNotFound(f"La línea no da sus ajustes: {e}") from e
		if self.numCells <= 0:
			raise DisplayNotFound("La línea no indica sus celdas")
		# El reloj y la preferencia de teclado no retrasan la conexión.
		self._inBackground(self._afterHidConnect)

	def _hidDeviceId(self, match: DeviceMatch) -> int | None:
		"""El identificador del modelo es el byte bajo del PID USB."""
		candidates = [match.id, match.device.usbId if match.device else ""]
		for text in candidates:
			m = _PID_RE.search(text or "")
			if m:
				return int(m.group(1), 16) & 0xFF
		pid = getattr(self._io, "productId", 0)
		return pid & 0xFF if pid else None

	def _connectSerial(self, match: DeviceMatch) -> None:
		self._io = self._open(match, baudrate=self.baudRate)
		self._sendCommand(b"?", b"?")
		if not self._waitFor(lambda: self._deviceId is not None, 1.5):
			raise DisplayNotFound("La línea no da su identificador")
		self._sendCommand(b"E", b"?")
		if not self._waitFor(lambda: self.numCells > 0, 1.5):
			raise DisplayNotFound("La línea no indica sus celdas")
		# Las respuestas llegan después y se atienden en el hilo de lectura.
		self._sendCommand(b"H", b"?")
		# Se aplica el modo del teclado guardado y se pregunta el que queda.
		self._sendCommand(b"r", bytes([int(self._wantedRawInput())]))
		self._sendCommand(b"r", b"?")

	def _setModel(self) -> None:
		devId = self._deviceId
		if devId in MODELS:
			self.model, name = MODELS[devId]
			self.deviceName = name or _("Convertidor de protocolo Optelec")
		else:
			self.model = f"ALVA{devId:02X}" if devId is not None else ""
			self.deviceName = "Optelec ALVA"

	def _resetState(self) -> None:
		self._buffer.clear()
		self._deviceId = None
		self._rawInput = False
		self._rawAnswered = False

	# ------------------------------------------------------- tareas en segundo plano
	def _inBackground(self, func: Callable[[], None]) -> None:
		"""Ejecuta ``func`` en un hilo propio (consultas HID, esperas)."""
		threading.Thread(target=self._runSafely, args=(func,), name="braille-alva", daemon=True).start()

	@staticmethod
	def _runSafely(func: Callable[[], None]) -> None:
		try:
			func()
		except Exception:
			log.debug("Error en una tarea de la línea ALVA", exc_info=True)

	def _afterHidConnect(self) -> None:
		try:
			self._checkTime(self._getFeature(HID_RTC_REPORT)[1 : 1 + RTC_LENGTH])
		except OSError:
			log.debug("No se pudo leer el reloj de la línea ALVA", exc_info=True)
		wanted = self._wantedRawInput()
		if wanted != self._rawInput:
			self._setRawInput(wanted)

	# ============================================================ HID
	def _getFeature(self, reportId: int) -> bytes:
		io = self._io
		if io is None:
			raise OSError("Sin conexión")
		return bytes(io.getFeature(reportId))  # type: ignore[attr-defined]

	def _setFeature(self, report: bytes) -> None:
		io = self._io
		if io is None:
			raise OSError("Sin conexión")
		io.setFeature(report)  # type: ignore[attr-defined]

	def _readHidSettings(self) -> None:
		"""Lee el número de celdas y el modo del teclado (informes de características)."""
		settings = self._getFeature(HID_DISPLAY_SETTINGS)
		if len(settings) > HID_STATUS_SIDE_POS and settings[HID_STATUS_SIDE_POS] > 1:
			# La BC680 a veces responde mal a la primera petición: se repite.
			settings = self._getFeature(HID_DISPLAY_SETTINGS)
		if len(settings) <= HID_CELL_COUNT_POS:
			raise OSError("Informe de ajustes demasiado corto")
		self._setNumCells(settings[HID_CELL_COUNT_POS])
		try:
			keySettings = self._getFeature(HID_KEY_SETTINGS)
			self._rawInput = len(keySettings) > 1 and bool(keySettings[1] & RAW_INPUT_MASK)
		except OSError:
			log.debug("La línea no da los ajustes de teclas", exc_info=True)

	# ============================================================ serie
	def _sendCommand(self, cmd: bytes, value: bytes = b"") -> None:
		self._write(bytes([ESC]) + cmd + value)

	def _handleSerial(self, data: bytes) -> None:
		buf = self._buffer
		buf.extend(data)
		while buf:
			start = buf.find(ESC)
			if start < 0:
				buf.clear()
				return
			if start:
				del buf[:start]
			if len(buf) < 2:
				return
			length = SERIAL_LENGTHS.get(buf[1])
			if length is None:
				# Orden desconocida: se descarta el ESC y se busca el siguiente.
				del buf[:1]
				continue
			if len(buf) < 2 + length:
				return
			cmd = buf[1]
			value = bytes(buf[2 : 2 + length])
			del buf[: 2 + length]
			self._handleSerialCommand(cmd, value)

	def _handleSerialCommand(self, cmd: int, value: bytes) -> None:
		if cmd == ord("K"):
			self._handleKey(value[0], value[1])
		elif cmd == ord("E"):
			self._setNumCells(value[0])
		elif cmd == ord("?"):
			self._deviceId = value[0]
		elif cmd == ord("r"):
			self._rawInput = bool(value[0])
			self._rawAnswered = True
		elif cmd == ord("H"):
			self._checkTime(value)

	# ============================================================ entrada
	def _handleData(self, data: bytes) -> None:
		if not self._isHid:
			self._handleSerial(data)
			return
		if len(data) >= 3 and data[0] == HID_KEY_REPORT:
			self._handleKey(data[2], data[1])

	def _handleKey(self, group: int, number: int) -> None:
		if group & ~RELEASE_MASK == SPECIAL_GROUP:
			if group == SPECIAL_GROUP and number == SETTINGS_CHANGED:
				self._onSettingsChanged()
			return
		release = bool(group & RELEASE_MASK)
		group &= ~RELEASE_MASK
		key = self._keyFor(group, number)
		if key is None:
			log.debug("Tecla ALVA desconocida: grupo %#x, número %d", group, number)
			return
		if release:
			self._keyReleased(key)
		else:
			self._keyPressed(key)

	@staticmethod
	def _keyFor(group: int, number: int):
		if group == ROUTING_GROUP:
			row = "routing2" if number & SECOND_ROW_MASK else "routing"
			return (row, number & ~SECOND_ROW_MASK)
		if group in (THUMB_GROUP, SMARTPAD_GROUP):
			names = THUMB_KEYS if group == THUMB_GROUP else SMARTPAD_KEYS
			if number < len(names):
				return names[number]
			if number < 2 * len(names):
				# Juego derecho de la BC680: mismo nombre, pero se sigue aparte.
				return names[number - len(names)] + RIGHT_SUFFIX
			return None
		if group == ETOUCH_GROUP:
			return ETOUCH_KEYS[number] if number < len(ETOUCH_KEYS) else None
		if group == KEYBOARD_GROUP:
			return KEYBOARD_KEYS.get(number)
		return None

	def _makeGesture(self, chord: Iterable) -> BrailleGesture | None:
		keys = {k.split("@", 1)[0] if isinstance(k, str) else k for k in chord}
		# Con la simulación de teclado HID activada la línea escribe por sí
		# misma: los puntos no se escriben otra vez a través de Tiresias.
		raw = self._rawInput
		gesture = buildGesture(
			self.name,
			keys,
			self.keyOrder,
			self.dotKeys if raw else {},
			self.spaceKeys if raw else (),
			self.model,
		)
		if gesture is not None:
			for gid in gesture.identifiers:
				if gid in self._emulated:
					gesture.emulatedKey = self._emulated[gid]
					break
		return gesture

	def _onSettingsChanged(self) -> None:
		"""La línea ha cambiado un ajuste interno (p. ej. el punto de división)."""
		if self._isHid:
			self._inBackground(self._readHidSettings)
		else:
			self._sendCommand(b"E", b"?")
			self._sendCommand(b"r", b"?")

	def _setNumCells(self, count: int) -> None:
		if count <= 0:
			return
		old = self.numCells
		self.numCells = count
		if old and old != count and self._activated:
			queue_handler.queueFunction(self._refreshDisplay)

	def _refreshDisplay(self) -> None:
		"""Hilo del núcleo: vuelve a dibujar tras cambiar el número de celdas."""
		from .. import handler

		if handler.display is not self:
			return
		try:
			handler.retranslate()
		except Exception:
			log.debug("No se pudo redibujar la línea", exc_info=True)

	# ============================================================ reloj
	def _now(self) -> datetime.datetime:
		return datetime.datetime.now()

	def _checkTime(self, value: bytes) -> None:
		"""Pone en hora la línea si su reloj se ha desviado."""
		if len(value) < RTC_LENGTH:
			return
		year = value[0] | (value[1] << 8)
		if not 1900 <= year <= 3000:
			log.debug("La línea ALVA no informa de la hora")
			return
		try:
			displayTime = datetime.datetime(year, value[2], value[3], value[4], value[5], value[6])
		except ValueError:
			log.debug("Fecha no válida en la línea ALVA: %r", value)
			return
		now = self._now()
		if abs((displayTime - now).total_seconds()) < RTC_MAX_DRIFT:
			return
		log.debug("Se pone en hora la línea ALVA (tenía %s)", displayTime.isoformat())
		data = bytes([now.year & 0xFF, now.year >> 8, now.month, now.day, now.hour, now.minute, now.second])
		if self._isHid:
			self._setFeature(bytes([HID_RTC_REPORT]) + data)
		else:
			self._sendCommand(b"H", data)

	# ============================================================ simulación de teclado HID
	def _setRawInput(self, raw: bool) -> bool:
		"""Pide a la línea el modo del teclado braille y devuelve el que queda."""
		if self._isHid:
			current = self._getFeature(HID_KEY_SETTINGS)[1]
			new = (current | RAW_INPUT_MASK) if raw else (current & ~RAW_INPUT_MASK & 0xFF)
			self._setFeature(bytes([HID_KEY_SETTINGS, new]))
			self._rawInput = bool(self._getFeature(HID_KEY_SETTINGS)[1] & RAW_INPUT_MASK)
			return self._rawInput
		self._rawAnswered = False
		self._sendCommand(b"r", bytes([int(raw)]))
		self._sendCommand(b"r", b"?")
		self._waitFor(lambda: self._rawAnswered and self._rawInput == raw, 1.0)
		return self._rawInput

	def _toggleHidKeyboardInput(self) -> None:
		if not self.connected:
			return
		wantRaw = not self._rawInput
		try:
			result = self._setRawInput(wantRaw)
		except OSError:
			log.debug("No se pudo cambiar el modo del teclado de la línea", exc_info=True)
			result = not wantRaw
		if result == wantRaw:
			if wantRaw:
				text = _("Simulación de teclado HID desactivada: el teclado braille escribe a través de Tiresias")
			else:
				text = _("Simulación de teclado HID activada: la línea escribe por sí misma")
			queue_handler.queueFunction(self._afterToggle, text, not wantRaw)
		else:
			queue_handler.queueFunction(self._afterToggle, _notSupportedMessage(), None)

	def _afterToggle(self, text: str, hidKeyboard: bool | None) -> None:
		"""Hilo del núcleo: guarda el nuevo modo (si ha cambiado) y lo anuncia."""
		if hidKeyboard is not None:
			self.setSetting(HID_KEYBOARD_SETTING, hidKeyboard)
		_speak(text)

	def applySettings(self) -> None:
		"""Hilo del núcleo: se ha cambiado el ajuste en Opciones; se aplica a la línea."""
		if not self.connected:
			return
		wanted = self._wantedRawInput()
		if wanted != self._rawInput:
			self._inBackground(lambda: self._applyRawInput(wanted))

	def _applyRawInput(self, wanted: bool) -> None:
		try:
			result = self._setRawInput(wanted)
		except OSError:
			log.debug("No se pudo cambiar el modo del teclado de la línea", exc_info=True)
			result = not wanted
		if result != wanted:
			queue_handler.queueFunction(_speak, _notSupportedMessage())

	@script(
		description=_("Activa o desactiva la simulación de teclado HID de la línea ALVA (si está desactivada, el teclado braille escribe con las tablas de Tiresias)"),
		category=_("Braille"),
		gesture="br(alva):t1+spEnter",
	)
	def script_toggleHidKeyboardInput(self, gesture) -> None:
		# Las consultas a la línea pueden tardar: fuera del hilo del núcleo.
		self._inBackground(self._toggleHidKeyboardInput)

	# ============================================================ salida
	def _writeCells(self, cells: list[int]) -> None:
		data = bytes(c & 0xFF for c in cells)
		if self._isHid:
			for offset in range(0, len(data), HID_OUTPUT_MAX_CELLS):
				chunk = data[offset : offset + HID_OUTPUT_MAX_CELLS]
				self._write(bytes([HID_OUTPUT_REPORT, offset, len(chunk)]) + chunk)
		else:
			self._sendCommand(b"B", bytes([0, len(data)]) + data)


BrailleDisplayDriver = AlvaDriver
