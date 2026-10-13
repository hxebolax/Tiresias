"""Base común de los controladores de líneas braille físicas.

:class:`HardwareDriver` se encarga de lo que todos comparten:

- abrir la conexión (serie, HID, bulk o socket) en el puerto configurado o
  en el que encuentre la detección automática;
- conectar en segundo plano sin bloquear el núcleo y reconectar si la línea
  se desconecta, avisando al usuario;
- convertir las teclas en gestos ``br(<controlador>):<teclas>`` (y
  ``br(<controlador>.<modelo>):<teclas>``) y asociar el mapa de gestos por
  defecto del controlador a las órdenes globales o a teclas emuladas.

Cada controlador implementa :meth:`HardwareDriver._connect` (abrir y
saludar a la línea), :meth:`HardwareDriver._handleData` (interpretar lo que
llega) y :meth:`HardwareDriver._writeCells` (enviar las celdas).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from ... import queue_handler
from ...config import conf
from ...i18n import _
from ...log import getLogger
from .. import BrailleDisplayDriver
from . import hwio
from .ports import DeviceInfo

log = getLogger("braille.drivers")


class DisplayNotFound(RuntimeError):
	"""No se ha encontrado o no responde la línea braille."""


# ====================================================================== puertos
@dataclass(frozen=True)
class DeviceMatch:
	"""Un dispositivo concreto con el que un controlador puede intentar conectar."""

	#: ``"hid"``, ``"serial"``, ``"bulk"`` o ``"socket"``.
	type: str
	#: Identificador USB (``VID_xxxx&PID_xxxx``) o nombre Bluetooth.
	id: str
	#: Ruta del dispositivo, puerto COM o dirección del servidor.
	port: str
	bluetooth: bool = False
	device: DeviceInfo | None = field(default=None, compare=False, hash=False)

	def describe(self) -> str:
		if self.type == "socket":
			return self.port
		where = self.port if self.type == "serial" else ""
		if self.bluetooth:
			name = self.id or (self.device.bluetoothName if self.device else "")
			text = _("Bluetooth") + (f" {name}" if name else "")
		else:
			text = _("USB")
		return f"{text} ({where})" if where else text

	@property
	def info(self) -> dict:
		data = self.device.asInfo() if self.device else {}
		data["bluetooth"] = self.bluetooth
		return data


@dataclass(frozen=True)
class DriverSetting:
	"""Ajuste propio de un controlador (aparece en Opciones, categoría «Braille»).

	``kind``: ``"bool"``, ``"int"`` (con ``minVal``/``maxVal``) o ``"choice"``
	(con ``choices``: pares valor, etiqueta). Se guarda en
	``conf["brailleDisplays"]["settings"][controlador][key]``.
	"""

	key: str
	label: str
	kind: str = "bool"
	default: Any = False
	minVal: int = 0
	maxVal: int = 100
	choices: tuple = ()


def getDriverSetting(driverName: str, key: str, default: Any = None) -> Any:
	try:
		section = conf["brailleDisplays"]["settings"].get(driverName)
		if section is not None and key in section:
			return section[key]
	except KeyError:
		pass
	return default


def setDriverSetting(driverName: str, key: str, value: Any) -> None:
	settings = conf["brailleDisplays"]["settings"]
	if driverName not in settings:
		settings[driverName] = {}
	conf["brailleDisplays"]["settings"][driverName][key] = value


def portLabel(port: str) -> str:
	"""Nombre legible de un valor de puerto de la configuración."""
	if port in ("", "auto"):
		return _("Automático")
	if port == "usb":
		return _("USB")
	if port == "bluetooth":
		return _("Bluetooth")
	return port


def getConfiguredPort(driverName: str) -> str:
	try:
		return conf["brailleDisplays"]["ports"].get(driverName, "auto") or "auto"
	except KeyError:
		return "auto"


def setConfiguredPort(driverName: str, port: str) -> None:
	conf["brailleDisplays"]["ports"][driverName] = port or "auto"


# ====================================================================== gestos
class BrailleGesture:
	"""Gesto de una línea braille, compatible con el gestor de entrada.

	``keys`` son los nombres de las teclas (sin las de enrutamiento, que se
	indican con ``routing``/``multiRouting`` y sus índices en
	``routingIndexes``). Si la combinación es solo de puntos y espacio,
	``dots`` (bits 0-7 = puntos 1-8) y ``space`` permiten escribir con el
	teclado braille de la línea.
	"""

	modifierNames: list[str] = []
	mainKeyName = ""
	char: str | None = None
	isModifier = False

	def __init__(
		self,
		driverName: str,
		keys: list[str],
		routingIndex: int | None = None,
		dots: int = 0,
		space: bool = False,
		model: str = "",
		routingIndexes: list[int] | None = None,
	) -> None:
		from ...baseobject import normalizeGestureId

		self.driverName = driverName
		self.keys = list(keys)
		self.routingIndexes = list(routingIndexes) if routingIndexes else ([routingIndex] if routingIndex is not None else [])
		self.routingIndex = self.routingIndexes[0] if self.routingIndexes else routingIndex
		self.dots = dots
		self.space = space
		self.model = model
		name = "+".join(self.keys)
		self.normalizedKeys = name
		ids = []
		if model:
			ids.append(normalizeGestureId(f"br({driverName}.{model}):{name}"))
		ids.append(normalizeGestureId(f"br({driverName}):{name}"))
		self.identifiers = ids
		label = name
		if self.routingIndexes:
			cells = ", ".join(str(i + 1) for i in self.routingIndexes)
			label = f"{name} ({_('celda')} {cells})"
		self.displayName = _("línea braille: {keys}").format(keys=label)
		#: Tecla emulada por defecto (``"kb:..."``) si ninguna orden atiende el gesto.
		self.emulatedKey: str | None = None

	def send(self) -> None:
		pass

	def __repr__(self) -> str:
		return f"<BrailleGesture {self.identifiers[-1]} {self.routingIndexes or ''}>"


class KeyTracker:
	"""Convierte pulsaciones y liberaciones en combinaciones.

	Las teclas se van acumulando mientras se pulsan; al soltar la primera se
	produce la combinación completa. Las liberaciones siguientes se ignoran
	hasta que se pulse otra tecla.
	"""

	def __init__(self) -> None:
		self.down: set = set()
		self._ignore = False

	def update(self, nowDown: Iterable) -> set | None:
		nowDown = set(nowDown)
		chord = None
		if nowDown - self.down:
			self._ignore = False
		if self.down - nowDown and not self._ignore:
			chord = set(self.down)
			self._ignore = True
		self.down = nowDown
		return chord

	def press(self, key) -> set | None:
		return self.update(self.down | {key})

	def release(self, key) -> set | None:
		return self.update(self.down - {key})

	def reset(self) -> None:
		self.down = set()
		self._ignore = False


#: Grupos de enrutamiento: clave interna -> (nombre con una celda, nombre con varias).
ROUTING_GROUPS = {"routing": ("routing", "multiRouting"), "routing2": ("routing2", "multiRouting2")}


def buildGesture(
	driverName: str,
	chord: Iterable,
	keyOrder: list[str] | None = None,
	dotKeys: dict[str, int] | None = None,
	spaceKeys: Iterable[str] = (),
	model: str = "",
) -> BrailleGesture | None:
	"""Crea el gesto de una combinación.

	Las teclas de enrutamiento son tuplas ``("routing", índice)`` (o
	``"routing2"`` para la segunda fila); el resto son nombres. Si todas las
	teclas son puntos o espacio, el gesto lleva ``dots``/``space`` para la
	escritura braille.
	"""
	names: list[str] = []
	routing: dict[str, list[int]] = {}
	for key in chord:
		if isinstance(key, tuple):
			routing.setdefault(key[0], []).append(int(key[1]))
		else:
			names.append(str(key))
	order = {k: i for i, k in enumerate(keyOrder or [])}
	names.sort(key=lambda n: (order.get(n, len(order)), n))
	dotKeys = dotKeys or {}
	spaceKeys = set(spaceKeys)
	dots = 0
	space = False
	if names and not routing and all(n in dotKeys or n in spaceKeys for n in names):
		for n in names:
			if n in dotKeys:
				dots |= 1 << (dotKeys[n] - 1)
			else:
				space = True
	indexes: list[int] = []
	for group in ("routing", "routing2"):
		if group in routing:
			cells = sorted(set(routing[group]))
			single, multi = ROUTING_GROUPS[group]
			names.append(single if len(cells) == 1 else multi)
			if not indexes:
				indexes = cells
	if not names:
		return None
	return BrailleGesture(driverName, names, dots=dots, space=space, model=model, routingIndexes=indexes)


def _executeGesture(gesture: BrailleGesture) -> None:
	"""Ejecuta un gesto de la línea (hilo del núcleo)."""
	from ...input import core as inputCore

	inputCore.manager.executeBrailleGesture(gesture)


_deciderRegistered = False


def _decideBrailleGesture(gesture: Any = None, **kwargs: Any) -> bool:
	"""Captura de gestos (diálogo «Gestos de entrada») y teclas emuladas por defecto."""
	from ...input import core as inputCore

	if gesture is None:
		return True
	mgr = inputCore.manager
	capture = getattr(mgr, "captureFunc", None)
	if capture is not None:
		# Cualquier gesto braille (también el teclado braille del PC) se
		# captura en «Gestos de entrada» en vez de escribir en el diálogo.
		try:
			capture(gesture)
		except Exception:
			log.exception("Error capturando el gesto braille")
		return False
	if not isinstance(gesture, BrailleGesture):
		return True
	key = gesture.emulatedKey
	# Las órdenes (globales, de la aplicación o propias del controlador, que
	# está en la cadena de órdenes) tienen prioridad sobre la tecla emulada.
	if not key or mgr.findScript(gesture) is not None:
		return True
	from ...input.keys import labelForGesture

	if mgr.inputHelp:
		from ... import speech

		speech.speakMessage(_("{gesture}: emula {key}").format(gesture=gesture.displayName, key=labelForGesture(key)))
		return False
	from ...input.gestures import sendKey
	from .. import input as brailleInput

	try:
		keyName = key.split(":", 1)[1]
		if brailleInput.handler.modifiers:
			# Modificadores activados desde la línea (Control, Alt...): se
			# combinan con la tecla emulada y se desactivan.
			brailleInput.handler.sendKey(keyName)
		else:
			sendKey(keyName)
	except Exception:
		log.exception("No se pudo emular %s", key)
	return False


def registerDecider() -> None:
	global _deciderRegistered
	if _deciderRegistered:
		return
	from ...input import core as inputCore

	inputCore.decide_executeBrailleGesture.register(_decideBrailleGesture)
	_deciderRegistered = True


# =================================================================== controlador
class HardwareDriver(BrailleDisplayDriver):
	"""Controlador de una línea braille física."""

	#: Es una línea física (la detección y el diálogo de selección lo usan).
	isHardware = True
	#: Identificadores USB por tipo de conexión.
	usbHidIds: frozenset[str] = frozenset()
	usbSerialIds: frozenset[str] = frozenset()
	usbBulkIds: frozenset[str] = frozenset()
	#: Identificadores de chips USB-serie genéricos que comparten otros aparatos:
	#: solo se detectan automáticamente si el usuario lo permite.
	genericUsbIds: frozenset[str] = frozenset()
	#: Prefijos del nombre Bluetooth (puertos serie y HID por Bluetooth).
	bluetoothPrefixes: tuple[str, ...] = ()
	#: Se puede elegir un puerto COM a mano.
	supportsSerialPorts = True
	#: Participa en la detección automática.
	supportsAutoDetection = True
	#: En la detección automática se prueba también en los dispositivos que ya
	#: ha reclamado otro controlador anterior (líneas que comparten el mismo
	#: chip USB-serie con otras, como la Caiku Albatross o la SuperBraille).
	tryClaimedPorts = False
	#: Mapa de gestos por defecto: ``"teclas"`` -> nombre de orden global o ``"kb:tecla"``.
	gestureMap: dict[str, str] = {}
	#: Mapas adicionales por modelo (tienen prioridad).
	modelGestureMaps: dict[str, dict[str, str]] = {}
	#: Orden de las teclas en los gestos (para nombres legibles).
	keyOrder: list[str] = []
	#: Teclas del teclado braille: nombre -> número de punto.
	dotKeys: dict[str, int] = {}
	spaceKeys: frozenset[str] = frozenset()
	#: Descripción de las teclas para el manual: nombre -> texto.
	keyDescriptions: dict[str, str] = {}
	#: Segundos entre intentos de conexión en segundo plano.
	retryInterval = 3.0
	retryIntervalBluetooth = 15.0

	#: Ajustes propios del controlador (ver :class:`DriverSetting`).
	driverSettings: tuple[DriverSetting, ...] = ()

	@classmethod
	def check(cls) -> bool:
		return True

	# -------------------------------------------------------- ajustes
	@classmethod
	def getSetting(cls, key: str) -> Any:
		default = next((s.default for s in cls.driverSettings if s.key == key), None)
		return getDriverSetting(cls.name, key, default)

	@classmethod
	def setSetting(cls, key: str, value: Any) -> None:
		setDriverSetting(cls.name, key, value)

	def applySettings(self) -> None:
		"""Hilo del núcleo: los ajustes del controlador han cambiado en Opciones."""

	# -------------------------------------------------------- puertos
	@classmethod
	def matchDevice(cls, dev: DeviceInfo, allowGeneric: bool = True) -> DeviceMatch | None:
		"""Comprueba si un dispositivo enumerado es de este controlador."""
		if dev.usbId in cls.genericUsbIds and not allowGeneric:
			return None
		if dev.kind == "hid":
			if dev.usbId and dev.usbId in cls.usbHidIds:
				return DeviceMatch("hid", dev.usbId, dev.path, dev.bluetooth, dev)
			if dev.bluetooth and cls._bluetoothNameMatches(dev.bluetoothName) and cls.usbHidIds:
				return DeviceMatch("hid", dev.bluetoothName, dev.path, True, dev)
			return None
		if dev.kind == "usb":
			if dev.usbId in cls.usbBulkIds:
				return DeviceMatch("bulk", dev.usbId, dev.path, False, dev)
			return None
		if dev.kind == "serial":
			if dev.bluetooth:
				if cls._bluetoothNameMatches(dev.bluetoothName):
					return DeviceMatch("serial", dev.bluetoothName, dev.path, True, dev)
				return None
			if dev.usbId and dev.usbId in cls.usbSerialIds:
				return DeviceMatch("serial", dev.usbId, dev.path, False, dev)
		return None

	@classmethod
	def _bluetoothNameMatches(cls, name: str) -> bool:
		return bool(name) and any(name.startswith(p) for p in cls.bluetoothPrefixes)

	@classmethod
	def getMatches(cls, devices: list[DeviceInfo], usb: bool = True, bluetooth: bool = True, allowGeneric: bool = True) -> list[DeviceMatch]:
		"""Dispositivos de la lista que puede usar este controlador (USB primero)."""
		usbMatches: list[DeviceMatch] = []
		btMatches: list[DeviceMatch] = []
		for dev in devices:
			m = cls.matchDevice(dev, allowGeneric=allowGeneric)
			if m is None:
				continue
			if m.bluetooth:
				if bluetooth:
					btMatches.append(m)
			elif usb:
				usbMatches.append(m)
		return usbMatches + btMatches

	@classmethod
	def getPortChoices(cls) -> list[tuple[str, str]]:
		"""Puertos que se ofrecen en el diálogo de selección."""
		choices = [("auto", _("Automático"))]
		if cls.usbHidIds or cls.usbSerialIds or cls.usbBulkIds:
			choices.append(("usb", _("USB")))
		if cls.bluetoothPrefixes:
			choices.append(("bluetooth", _("Bluetooth")))
		if cls.supportsSerialPorts:
			from . import ports

			for dev in ports.listComPorts():
				label = dev.friendlyName or dev.path
				if dev.bluetoothName:
					label = f"{dev.path}: Bluetooth {dev.bluetoothName}"
				elif dev.path not in label:
					label = f"{dev.path}: {label}"
				choices.append((dev.path, label))
		return choices

	@classmethod
	def candidateMatches(cls, port: str) -> list[DeviceMatch]:
		"""Dispositivos que hay que probar según el puerto elegido."""
		from . import ports

		port = port or "auto"
		if port.upper().startswith("COM"):
			info = next((d for d in ports.listComPorts() if d.path == port.upper()), None)
			return [DeviceMatch("serial", info.bluetoothName if info else "", port.upper(), bool(info and info.bluetooth), info)]
		devices = ports.listAll()
		return cls.getMatches(devices, usb=port in ("auto", "usb"), bluetooth=port in ("auto", "bluetooth"))

	def _candidateMatches(self) -> list[DeviceMatch]:
		return self.candidateMatches(self._port)

	# -------------------------------------------------------- ciclo de vida
	def __init__(self, port: str | None = None, match: DeviceMatch | None = None, configName: str | None = None, transport: hwio.Transport | None = None) -> None:
		"""Crea el controlador.

		- ``match``: conecta ya, en el hilo actual (lo usa la detección, que
		  trabaja en segundo plano). Lanza :class:`DisplayNotFound` si falla.
		- ``transport``: conexión ya abierta (pruebas con :class:`hwio.MemoryTransport`).
		- sin ninguno de los dos: conecta en segundo plano con el puerto
		  configurado y sigue intentándolo hasta que la línea aparezca.
		"""
		super().__init__()
		self.numCells = 0
		self.model = ""
		#: Nombre del aparato para los avisos (p. ej. «Focus 40 Blue»).
		self.deviceName = ""
		self._io: hwio.Transport | None = None
		self._match: DeviceMatch | None = None
		self._cond = threading.Condition(threading.RLock())
		self._keys = KeyTracker()
		self._terminated = False
		self._activated = False
		self._boundGestures: dict[str, str] = {}
		self._emulated: dict[str, str] = {}
		self._wakeEvent = threading.Event()
		self._connector: threading.Thread | None = None
		self.configName = configName or self.name
		self._port = port if port is not None else getConfiguredPort(self.name)
		if transport is not None:
			self._io = transport
			if isinstance(transport, hwio.MemoryTransport):
				transport.onReceive = self._onReceive
				transport.onError = self._onIoError
			self._match = DeviceMatch(transport.kind, "", transport.port, transport.isBluetooth)
			self._afterOpen(self._match)
			return
		if match is not None:
			if not self._tryMatch(match):
				raise DisplayNotFound(f"{self.name}: sin respuesta en {match.port}")
			return
		self._startConnector()
		queue_handler.callLater(8000, self._reportNotFound)

	def _reportNotFound(self) -> None:
		"""Avisa una vez si la línea elegida no aparece al poco de seleccionarla."""
		from .. import handler

		if self._terminated or self.connected or handler.display is not self:
			return
		_announce(_("No se encuentra la línea braille {name} ({port}). Se conectará en cuanto esté disponible.").format(name=self.shortName, port=portLabel(self._port)))

	@property
	def connected(self) -> bool:
		return self._io is not None and self.numCells > 0

	def _tryMatch(self, match: DeviceMatch) -> bool:
		"""Intenta conectar con un dispositivo concreto."""
		try:
			self._connect(match)
		except Exception as e:
			log.debug("%s: no conecta con %s: %s", self.name, match.port, e)
			self._closeIo()
			return False
		if self._io is None or self.numCells <= 0:
			self._closeIo()
			return False
		self._match = match
		log.info("Línea braille %s (%s) conectada por %s: %d celdas", self.deviceName or self.description, self.model or "-", match.describe(), self.numCells)
		return True

	def _afterOpen(self, match: DeviceMatch) -> None:
		"""Para conexiones de prueba: saluda a la línea sin esperar respuesta."""
		try:
			self._initConnection(match)
		except Exception:
			log.debug("Error inicializando la conexión de prueba", exc_info=True)

	def _initConnection(self, match: DeviceMatch) -> None:
		"""Saludo inicial tras abrir la conexión (opcional)."""

	def _connect(self, match: DeviceMatch) -> None:
		"""Abre la conexión y espera la identificación de la línea.

		Debe dejar ``self._io`` abierto y ``self.numCells`` > 0, o lanzar una
		excepción. Por defecto abre el puerto con :meth:`_open` y llama a
		:meth:`_initConnection` y espera a que la línea diga sus celdas.
		"""
		self._io = self._open(match)
		self._initConnection(match)
		self._waitFor(lambda: self.numCells > 0, 2.0)
		if self.numCells <= 0:
			raise DisplayNotFound("La línea no ha respondido")

	#: Velocidad por defecto de los puertos serie.
	baudRate = 9600

	def _open(self, match: DeviceMatch, baudrate: int | None = None, **kwargs: Any) -> hwio.Transport:
		"""Abre la conexión adecuada al tipo de dispositivo.

		Los controladores deben abrir siempre a través de este método (las
		pruebas lo sustituyen por una conexión en memoria). ``kwargs``: para
		serie, ``parity``, ``stopBits``, ``rtscts``...; para HID, ``exclusive``;
		para bulk, ``epIn``, ``epOut`` y ``readSize``.
		"""
		if match.type == "hid":
			return self._openHid(match, exclusive=kwargs.get("exclusive", False))
		if match.type == "serial":
			return self._openSerial(match, baudrate or self.baudRate, **kwargs)
		if match.type == "bulk":
			return self._openBulk(match, kwargs.get("epIn", 0), kwargs.get("epOut", 1), kwargs.get("readSize", 64))
		raise DisplayNotFound(f"Tipo de conexión no admitido: {match.type}")

	def _openHid(self, match: DeviceMatch, exclusive: bool = False) -> hwio.HidDevice:
		return hwio.HidDevice(match.port, self._onReceive, self._onIoError, exclusive=exclusive, info=match.info)

	def _openSerial(self, match: DeviceMatch, baudrate: int, **kwargs: Any) -> hwio.SerialPort:
		return hwio.SerialPort(match.port, baudrate, self._onReceive, self._onIoError, info=match.info, **kwargs)

	def _openBulk(self, match: DeviceMatch, epIn: int | str, epOut: int | str, readSize: int = 64) -> hwio.BulkDevice:
		return hwio.BulkDevice(match.port, epIn, epOut, self._onReceive, self._onIoError, readSize=readSize, info=match.info)

	def _waitFor(self, predicate: Callable[[], bool], timeout: float) -> bool:
		"""Espera (en el hilo que conecta) a que lleguen datos que cumplan ``predicate``."""
		with self._cond:
			return self._cond.wait_for(predicate, timeout)

	def _write(self, data: bytes) -> None:
		io = self._io
		if io is None:
			return
		io.write(data)

	def _closeIo(self) -> None:
		io = self._io
		self._io = None
		if io is not None:
			try:
				io.close()
			except Exception:
				log.debug("Error cerrando la conexión", exc_info=True)

	# -------------------------------------------------------- conexión en segundo plano
	def _startConnector(self) -> None:
		if self._connector is not None and self._connector.is_alive():
			self._wakeEvent.set()
			return
		self._wakeEvent.clear()
		self._connector = threading.Thread(target=self._connectLoop, name=f"braille-connect-{self.name}", daemon=True)
		self._connector.start()

	def _connectLoop(self) -> None:
		lastAttempt: dict[str, float] = {}
		while not self._terminated:
			try:
				candidates = self._candidateMatches()
			except Exception:
				log.debug("Error buscando dispositivos para %s", self.name, exc_info=True)
				candidates = []
			for match in candidates:
				if self._terminated:
					return
				wait = self.retryIntervalBluetooth if (match.bluetooth or match.type == "serial") else self.retryInterval
				key = f"{match.type}:{match.port}"
				if time.monotonic() - lastAttempt.get(key, -1e9) < wait:
					continue
				lastAttempt[key] = time.monotonic()
				with self._cond:
					if self._terminated:
						return
				if self._tryMatch(match):
					if self._terminated:
						self._closeIo()
						return
					queue_handler.queueFunction(self._activate)
					return
			self._wakeEvent.wait(1.0)
			self._wakeEvent.clear()

	def _activate(self) -> None:
		"""Hilo del núcleo: la línea está conectada y lista."""
		from .. import handler

		if self._terminated:
			return
		registerDecider()
		self._bindGestures()
		self._activated = True
		if handler.display is self:
			handler.setDisplay(self.name, persist=False, instance=self)
		_announce(_("Línea braille conectada: {name}, {cells} celdas").format(name=self.displayName, cells=self.numCells))
		_showInitial()

	@property
	def shortName(self) -> str:
		"""Nombre corto de la marca (la descripción hasta el primer paréntesis o coma)."""
		name = self.description
		for sep in (" (", ","):
			name = name.split(sep, 1)[0]
		return name.strip() or self.description

	@property
	def displayName(self) -> str:
		"""Nombre del aparato para avisos y diálogos."""
		name = self.deviceName or self.description
		if self._match is not None and self._match.bluetooth:
			name += " (" + _("Bluetooth") + ")"
		return name

	# -------------------------------------------------------- recepción
	def _onReceive(self, data: bytes) -> None:
		"""Hilo de lectura: datos de la línea."""
		with self._cond:
			try:
				self._handleData(data)
			finally:
				self._cond.notify_all()

	def _handleData(self, data: bytes) -> None:
		raise NotImplementedError

	def _onIoError(self, code: int) -> None:
		"""Hilo de lectura (o de escritura): la conexión se ha perdido."""
		with self._cond:
			if self._terminated or self._io is None:
				return
			log.info("Se ha perdido la conexión con la línea braille %s", self.displayName)
			io = self._io
			self._io = None
			self.numCells = 0
			self._keys.reset()
			self._resetState()
		# Se cierra fuera del cerrojo: el cierre espera al hilo de lectura.
		try:
			io.close()
		except Exception:
			log.debug("Error cerrando la conexión perdida", exc_info=True)
		queue_handler.queueFunction(self._afterDisconnect)

	def _resetState(self) -> None:
		"""Olvida el estado del protocolo (al desconectar)."""

	def _afterDisconnect(self) -> None:
		from .. import handler

		self._unbindGestures()
		self._activated = False
		if self._terminated:
			return
		_announce(_("Línea braille desconectada: {name}").format(name=self.displayName))
		if handler.display is not self:
			return
		if self.configName == "auto":
			# Se vuelve a la detección automática por si se conecta otra línea.
			handler.setDisplay("auto", persist=False)
			return
		self._startConnector()

	# -------------------------------------------------------- teclas
	def _keysChanged(self, nowDown: Iterable) -> None:
		chord = self._keys.update(nowDown)
		if chord:
			self._fireChord(chord)

	def _keyPressed(self, key) -> None:
		chord = self._keys.press(key)
		if chord:
			self._fireChord(chord)

	def _keyReleased(self, key) -> None:
		chord = self._keys.release(key)
		if chord:
			self._fireChord(chord)

	def _fireChord(self, chord: Iterable) -> None:
		gesture = self._makeGesture(chord)
		if gesture is not None:
			self._dispatch(gesture)

	def _makeGesture(self, chord: Iterable) -> BrailleGesture | None:
		gesture = buildGesture(self.name, chord, self.keyOrder, self.dotKeys, self.spaceKeys, self.model)
		if gesture is not None:
			for gid in gesture.identifiers:
				if gid in self._emulated:
					gesture.emulatedKey = self._emulated[gid]
					break
		return gesture

	#: Gestos generados (para las pruebas cuando no hay núcleo).
	lastGestures: list[BrailleGesture] | None = None

	def _dispatch(self, gesture: BrailleGesture) -> None:
		if self.lastGestures is not None:
			self.lastGestures.append(gesture)
			return
		queue_handler.queueFunction(_executeGesture, gesture)

	# -------------------------------------------------------- mapa de gestos
	@classmethod
	def effectiveGestureMap(cls, model: str = "") -> dict[str, str]:
		"""Mapa por defecto (identificador normalizado -> orden o ``kb:``)."""
		from ...baseobject import normalizeGestureId

		out: dict[str, str] = {}
		for keys, target in cls.gestureMap.items():
			out[normalizeGestureId(f"br({cls.name}):{keys}")] = target
		if model and model in cls.modelGestureMaps:
			for keys, target in cls.modelGestureMaps[model].items():
				out[normalizeGestureId(f"br({cls.name}.{model}):{keys}")] = target
		return out

	def _bindGestures(self) -> None:
		"""Asocia el mapa por defecto a las órdenes globales (hilo del núcleo)."""
		from ...global_commands import commands

		self._unbindGestures()
		for gid, target in self.effectiveGestureMap(self.model).items():
			if target.startswith("kb:"):
				self._emulated[gid] = target
				continue
			if not hasattr(commands, "script_" + target):
				log.debug("Orden %s inexistente para %s", target, gid)
				continue
			inst = commands.__dict__.setdefault("_instanceGestures", {})
			if gid in inst:
				continue
			commands.bindGesture(gid, target)
			self._boundGestures[gid] = target

	def _unbindGestures(self) -> None:
		if self._boundGestures:
			from ...global_commands import commands

			inst = commands.__dict__.get("_instanceGestures") or {}
			for gid, target in self._boundGestures.items():
				if inst.get(gid) == target:
					del inst[gid]
		self._boundGestures = {}
		self._emulated = {}

	# -------------------------------------------------------- salida
	def display(self, cells: list[int]) -> None:
		if self._io is None or self.numCells <= 0:
			return
		cells = (list(cells) + [0] * self.numCells)[: self.numCells]
		try:
			self._writeCells(cells)
		except hwio.IoError as e:
			log.debug("Error escribiendo en la línea braille: %s", e)

	def _writeCells(self, cells: list[int]) -> None:
		raise NotImplementedError

	def terminate(self) -> None:
		with self._cond:
			self._terminated = True
		self._wakeEvent.set()
		if self._activated:
			try:
				self._unbindGestures()
			except Exception:
				log.debug("Error quitando los gestos", exc_info=True)
		if self._io is not None:
			try:
				if self.numCells > 0:
					self._writeCells([0] * self.numCells)
				self._sayGoodbye()
			except Exception:
				pass
		self._closeIo()
		self.numCells = 0

	def _sayGoodbye(self) -> None:
		"""Mensaje de despedida al cerrar (opcional)."""


# ====================================================================== avisos
def _announce(text: str) -> None:
	"""Avisa por voz de conexiones y desconexiones (hilo del núcleo)."""
	try:
		if not conf["brailleDisplays"]["announceConnection"]:
			log.info(text)
			return
	except KeyError:
		pass
	from ... import speech

	try:
		speech.speakMessage(text)
	except Exception:
		log.debug("No se pudo anunciar: %s", text, exc_info=True)


def _showInitial() -> None:
	"""Muestra el foco en la línea recién conectada."""
	from ... import api
	from .. import handler

	try:
		focus = api.getFocusObject()
		if focus is not None:
			handler.handleObject(focus)
	except Exception:
		log.debug("No se pudo mostrar el foco en la línea", exc_info=True)
