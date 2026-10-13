"""Pruebas del controlador de líneas braille Handy Tech (datos simulados)."""

from __future__ import annotations

import datetime
import re
import unittest
from unittest import mock

import braille_sim  # noqa: F401
from braille_sim import connectSimulated, gestureIds

from tiresias.braille.drivers import base
from tiresias.braille.drivers.handyTech import MODELS, HandyTechDriver
from tiresias.braille.drivers.ports import DeviceInfo

ACTIVE_BRAILLE = 0x54
BASIC_BRAILLE_40 = 0x84
MODULAR_40 = 0x89
EASY_BRAILLE = 0x44
BRAILLE_WAVE = 0x05
ACTIVATOR = 0xA4


def ext(modelId: int, payload: bytes) -> bytes:
	"""Paquete extendido de la línea."""
	return bytes([0x79, modelId, len(payload)]) + bytes(payload) + b"\x16"


def serialResponder(modelId: int | None, ack: bool = True, properties: int | None = None, okWithLength: int | None = None):
	"""Contesta como una línea serie: identificación, propiedades y confirmaciones."""

	def respond(data: bytes):
		if data == b"\xff":
			if modelId is None:
				return None
			if okWithLength is not None:
				return bytes([0xFD, modelId, okWithLength])
			return bytes([0xFE, modelId])
		if data[:1] == b"\x79" and len(data) >= 4:
			if data[3] == 0xC1 and properties is not None:
				return ext(modelId, bytes([0xC1, 0x00, 0x01, properties]))
			if data[3] == 0x01 and ack:
				return ext(modelId, b"\x07\x7e")
		if data[:1] == b"\x01" and ack:
			return b"\x7e"
		return None

	return respond


def hidReport(payload: bytes, size: int = 32) -> bytes:
	report = bytes([0x01, len(payload)]) + bytes(payload)
	return report + bytes(max(0, size - len(report)))


def unwrapHid(report: bytes) -> bytes:
	assert report[0] == 0x02, report
	return report[2 : 2 + report[1]]


def hidResponder(inner, chunk: int = 0):
	"""Adapta un ``serialResponder`` a informes HID (``chunk`` > 0: adaptador HID-serie)."""
	partial = bytearray()

	def respond(data: bytes):
		if data[0] == 0xFB:
			return None
		partial.extend(unwrapHid(data))
		# Las tramas largas llegan en varios informes: se espera al terminador o a un paquete corto.
		packet = bytes(partial)
		if packet[:1] == b"\x79" and (len(packet) < 3 or len(packet) < packet[2] + 4):
			return None
		partial.clear()
		reply = inner(packet)
		if not reply:
			return None
		if chunk:
			return [hidReport(reply[i : i + chunk]) for i in range(0, len(reply), chunk)]
		return hidReport(reply)

	return respond


#: Ajustes del controlador durante las pruebas (no se toca la configuración real).
STORE: dict = {}
_patches: list = []


def _fakeGet(driverName, key, default=None):
	return STORE.get(key, default)


def _fakeSet(driverName, key, value):
	STORE[key] = value


def setUpModule() -> None:
	for target, fake in (
		("tiresias.braille.drivers.base.getDriverSetting", _fakeGet),
		("tiresias.braille.drivers.base.setDriverSetting", _fakeSet),
		("tiresias.braille.drivers.handyTech.getDriverSetting", _fakeGet),
	):
		p = mock.patch(target, fake)
		p.start()
		_patches.append(p)


def tearDownModule() -> None:
	for p in _patches:
		p.stop()
	_patches.clear()


class _Isolated(unittest.TestCase):
	def setUp(self) -> None:
		STORE.clear()


def connect(modelId: int = ACTIVE_BRAILLE, **kwargs):
	responder = kwargs.pop("responder", None) or serialResponder(modelId, properties=kwargs.pop("properties", None))
	return connectSimulated(HandyTechDriver, responder=responder, **kwargs)


def press(transport, *codes: int) -> None:
	for c in codes:
		transport.feed(bytes([c]))


def extKey(modelId: int, code: int) -> bytes:
	return ext(modelId, bytes([0x04, code]))


def runToggle(test: unittest.TestCase, drv):
	"""Comprueba que el último gesto es la orden de escritura braille y la ejecuta."""
	gesture = drv.lastGestures[-1]
	drv.lastGestures.clear()
	func = drv.getScript(gesture)
	test.assertIsNotNone(func, gesture)
	test.assertEqual(func.__name__, "script_toggleBrailleInput")
	with mock.patch("tiresias.queue_handler.queueFunction") as q:
		func(gesture)
	return q


class ConnectionTests(_Isolated):
	def test_serial_extended_model(self) -> None:
		drv, t = connect(ACTIVE_BRAILLE, properties=40)
		self.assertEqual(t.opened[0][1], 19200)
		self.assertEqual(t.opened[0][2], {"parity": "O"})
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(drv.model, "ActiveBraille")
		self.assertEqual(drv.deviceName, "Handy Tech Active Braille")
		self.assertEqual(t.writes[0], b"\xff")
		self.assertEqual(t.writes[1], bytes([0x79, ACTIVE_BRAILLE, 0x01, 0xC1, 0x16]))
		# Petición de la hora (modelos con reloj).
		self.assertEqual(t.writes[2], bytes([0x79, ACTIVE_BRAILLE, 0x01, 0x45, 0x16]))

	def test_old_protocol_model_skips_properties(self) -> None:
		drv, t = connect(MODULAR_40)
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(drv.model, "Modular")
		self.assertEqual(drv.deviceName, "Handy Tech Modular 40")
		self.assertEqual(t.writes, [b"\xff"])

	def test_ok_with_length(self) -> None:
		drv, _t = connect(BASIC_BRAILLE_40, responder=serialResponder(BASIC_BRAILLE_40, okWithLength=32, properties=32))
		self.assertEqual(drv.numCells, 32)
		self.assertEqual(drv.deviceName, "Handy Tech Basic Braille 40")

	def test_properties_change_cells_and_active_split(self) -> None:
		drv, t = connect(ACTIVATOR, properties=32)
		self.assertEqual(drv.numCells, 32)
		self.assertIn(bytes([0x79, ACTIVATOR, 0x01, 0xAE, 0x16]), t.writes)

	def test_unknown_model_uses_properties(self) -> None:
		drv, _t = connect(0x99, properties=24)
		self.assertEqual(drv.numCells, 24)
		self.assertEqual(drv.model, "HandyTech99")

	def test_unknown_model_without_cells_fails(self) -> None:
		with mock.patch.object(HandyTechDriver, "_waitFor", lambda self, p, t: p()):
			with self.assertRaises(base.DisplayNotFound):
				connect(0x99)

	def test_no_answer(self) -> None:
		with mock.patch.object(HandyTechDriver, "_waitFor", lambda self, p, t: p()):
			with self.assertRaises(base.DisplayNotFound):
				connect(responder=serialResponder(None))

	def test_model_change_reconnects(self) -> None:
		drv, t = connect(BASIC_BRAILLE_40, properties=40)
		with mock.patch("tiresias.queue_handler.queueFunction") as q:
			t.feed(bytes([0xFE, ACTIVE_BRAILLE]))
		self.assertTrue(q.called)
		self.assertEqual(drv.numCells, 0)
		self.assertTrue(t.closed)


class OutputTests(_Isolated):
	def test_extended_cells(self) -> None:
		drv, t = connect(BASIC_BRAILLE_40, properties=40)
		drv.display([0x01, 0xFF, 0x80])
		cells = bytes([0x01, 0xFF, 0x80]) + bytes(37)
		self.assertEqual(t.writes[-1], bytes([0x79, BASIC_BRAILLE_40, 41, 0x01]) + cells + b"\x16")

	def test_old_protocol_with_status_cells(self) -> None:
		drv, t = connect(MODULAR_40)
		drv.display([0x3F] * 40)
		self.assertEqual(t.writes[-1], b"\x01" + bytes(4) + bytes([0x3F] * 40))

	def test_old_protocol_without_status_cells(self) -> None:
		drv, t = connect(EASY_BRAILLE)
		drv.display([1, 2])
		self.assertEqual(t.writes[-1], b"\x01" + bytes([1, 2]) + bytes(38))

	def test_waits_for_ack(self) -> None:
		drv, t = connect(BASIC_BRAILLE_40, responder=serialResponder(BASIC_BRAILLE_40, ack=False, properties=40))
		drv.display([1])
		first = len(t.writes)
		drv.display([2])
		drv.display([3])
		# Sin confirmación no se envía nada más; solo se guarda la última.
		self.assertEqual(len(t.writes), first)
		t.feed(ext(BASIC_BRAILLE_40, b"\x07\x7e"))
		self.assertEqual(len(t.writes), first + 1)
		self.assertEqual(t.writes[-1][4], 3)
		drv._cancelAckTimer()

	def test_old_ack_byte(self) -> None:
		drv, t = connect(MODULAR_40, responder=serialResponder(MODULAR_40, ack=False))
		drv.display([1])
		drv.display([2])
		n = len(t.writes)
		t.feed(b"\x7e")
		self.assertEqual(len(t.writes), n + 1)
		self.assertEqual(t.writes[-1], b"\x01" + bytes(4) + b"\x02" + bytes(39))
		drv._cancelAckTimer()

	def test_ack_timeout_sends_pending(self) -> None:
		drv, t = connect(BASIC_BRAILLE_40, responder=serialResponder(BASIC_BRAILLE_40, ack=False, properties=40))
		drv.display([1])
		drv.display([2])
		n = len(t.writes)
		drv._onAckTimeout()
		self.assertEqual(len(t.writes), n + 1)
		self.assertEqual(t.writes[-1][4], 2)


class InputTests(_Isolated):
	def test_extended_keys(self) -> None:
		drv, t = connect(ACTIVE_BRAILLE, properties=40)
		t.feed(extKey(ACTIVE_BRAILLE, 0x0F))  # B4
		t.feed(extKey(ACTIVE_BRAILLE, 0x8F))
		t.feed(extKey(ACTIVE_BRAILLE, 0x10))  # espacio izquierdo
		t.feed(extKey(ACTIVE_BRAILLE, 0x03))  # B1
		t.feed(extKey(ACTIVE_BRAILLE, 0x90))
		t.feed(extKey(ACTIVE_BRAILLE, 0x83))
		t.feed(extKey(ACTIVE_BRAILLE, 0x76))  # palanca arriba
		t.feed(extKey(ACTIVE_BRAILLE, 0xF6))
		t.feed(extKey(ACTIVE_BRAILLE, 0x0C))  # triple acción izquierda arriba
		t.feed(extKey(ACTIVE_BRAILLE, 0x14))  # y abajo (centro)
		t.feed(extKey(ACTIVE_BRAILLE, 0x8C))
		t.feed(extKey(ACTIVE_BRAILLE, 0x94))
		self.assertEqual(
			gestureIds(drv),
			[
				"br(handytech):b4",
				"br(handytech):b1+leftspace",
				"br(handytech):joystickup",
				"br(handytech):lefttakbottom+lefttaktop",
			],
		)
		self.assertEqual(drv.lastGestures, [])

	def test_model_identifier(self) -> None:
		drv, t = connect(ACTIVE_BRAILLE, properties=40)
		t.feed(extKey(ACTIVE_BRAILLE, 0x13) + extKey(ACTIVE_BRAILLE, 0x93))
		g = drv.lastGestures[0]
		self.assertEqual(g.identifiers, ["br(handytech.activebraille):b5", "br(handytech):b5"])
		self.assertEqual(g.dots, 0)

	def test_routing(self) -> None:
		drv, t = connect(BASIC_BRAILLE_40, properties=40)
		t.feed(extKey(BASIC_BRAILLE_40, 0x25) + extKey(BASIC_BRAILLE_40, 0xA5))
		self.assertEqual(drv.lastGestures[0].routingIndex, 5)
		self.assertEqual(gestureIds(drv), ["br(handytech):routing"])
		# Última celda y varias a la vez.
		t.feed(extKey(BASIC_BRAILLE_40, 0x20 + 39) + extKey(BASIC_BRAILLE_40, 0x22))
		t.feed(extKey(BASIC_BRAILLE_40, 0x80 | (0x20 + 39)) + extKey(BASIC_BRAILLE_40, 0xA2))
		self.assertEqual(drv.lastGestures[0].routingIndexes, [2, 39])
		self.assertEqual(gestureIds(drv), ["br(handytech):multirouting"])
		# Con una barra espaciadora.
		t.feed(extKey(BASIC_BRAILLE_40, 0x18) + extKey(BASIC_BRAILLE_40, 0x21) + extKey(BASIC_BRAILLE_40, 0xA1) + extKey(BASIC_BRAILLE_40, 0x98))
		self.assertEqual(gestureIds(drv), ["br(handytech):rightspace+routing"])

	def test_serial_stream_byte_by_byte(self) -> None:
		drv, t = connect(BASIC_BRAILLE_40, properties=40)
		press(t, *(extKey(BASIC_BRAILLE_40, 0x0F) + extKey(BASIC_BRAILLE_40, 0x13) + extKey(BASIC_BRAILLE_40, 0x8F) + extKey(BASIC_BRAILLE_40, 0x93)))
		self.assertEqual(gestureIds(drv), ["br(handytech):b4+b5"])

	def test_resync_after_garbage(self) -> None:
		drv, t = connect(BASIC_BRAILLE_40, properties=40)
		t.feed(b"\x00\x33\x79\x84\x02\x04\x0f\x00" + extKey(BASIC_BRAILLE_40, 0x0F) + extKey(BASIC_BRAILLE_40, 0x8F))
		self.assertEqual(gestureIds(drv), ["br(handytech):b4"])

	def test_old_protocol_keys(self) -> None:
		drv, t = connect(MODULAR_40)
		press(t, 0x70, 0xF0)  # primera tecla de estado
		press(t, 0x20 + 10, 0xA0 + 10)  # enrutamiento celda 11
		press(t, 0x0C, 0x8C)  # triple acción izquierda arriba
		press(t, 0x15, 0x95)  # teclado numérico: 1
		self.assertEqual(
			gestureIds(drv),
			["br(handytech):statusrouting1", "br(handytech):routing", "br(handytech):lefttaktop", "br(handytech):n1"],
		)

	def test_old_protocol_ack_and_keys_mixed(self) -> None:
		drv, t = connect(MODULAR_40)
		t.feed(b"\x7e\x0f\x7e\x8f")
		self.assertEqual(gestureIds(drv), ["br(handytech):b4"])

	def test_braille_input_mode(self) -> None:
		drv, t = connect(BASIC_BRAILLE_40, properties=40)
		k = lambda c: extKey(BASIC_BRAILLE_40, c)  # noqa: E731
		# Espacio izquierdo + B1 + B3 + B4: la orden propia del controlador activa la escritura.
		t.feed(k(0x10) + k(0x03) + k(0x0B) + k(0x0F) + k(0x90) + k(0x83) + k(0x8B) + k(0x8F))
		self.assertEqual(gestureIds(drv, clear=False), ["br(handytech):b1+b3+b4+leftspace"])
		q = runToggle(self, drv)
		self.assertTrue(drv.brailleInput)
		self.assertTrue(q.called)
		# B4 + B3 (puntos 1 y 2: «b») y espacio + B4 (espacio + punto 1).
		t.feed(k(0x0F) + k(0x0B) + k(0x8F) + k(0x8B))
		t.feed(k(0x18) + k(0x0F) + k(0x98) + k(0x8F))
		t.feed(k(0x18) + k(0x98))
		gestures = list(drv.lastGestures)
		self.assertEqual(gestureIds(drv), ["br(handytech):dot1+dot2", "br(handytech):dot1+space", "br(handytech):space"])
		self.assertEqual((gestures[0].dots, gestures[0].space), (0b11, False))
		self.assertEqual((gestures[1].dots, gestures[1].space), (0b1, True))
		self.assertTrue(gestures[2].space)
		# B1 y B8 son los puntos 7 y 8.
		t.feed(k(0x03) + k(0x1F) + k(0x83) + k(0x9F))
		self.assertEqual(drv.lastGestures[0].dots, 0b11000000)
		gestureIds(drv)
		# Espacio + puntos 1-2-7 lo desactiva.
		t.feed(k(0x18) + k(0x03) + k(0x0B) + k(0x0F) + k(0x98) + k(0x83) + k(0x8B) + k(0x8F))
		self.assertEqual(gestureIds(drv, clear=False), ["br(handytech):dot1+dot2+dot7+space"])
		runToggle(self, drv)
		self.assertFalse(drv.brailleInput)
		t.feed(k(0x0F) + k(0x8F))
		self.assertEqual(gestureIds(drv), ["br(handytech):b4"])

	def test_easy_braille_left_right(self) -> None:
		drv, t = connect(EASY_BRAILLE)
		press(t, 0x04, 0x84)
		g = drv.lastGestures[0]
		self.assertEqual(g.identifiers, ["br(handytech.easybraille):left", "br(handytech):left"])
		gestureIds(drv)
		press(t, 0x08, 0x03, 0x0B, 0x0F, 0x88, 0x83, 0x8B, 0x8F)
		runToggle(self, drv)
		self.assertTrue(drv.brailleInput)
		press(t, 0x04, 0x13, 0x84, 0x93)  # izquierda + B5 = espacio + punto 4
		self.assertEqual(gestureIds(drv), ["br(handytech):dot4+space"])

	def test_braille_wave_keys(self) -> None:
		drv, t = connect(BRAILLE_WAVE)
		press(t, 0x0C, 0x8C, 0x14, 0x94, 0x10, 0x0F, 0x90, 0x8F)
		self.assertEqual(gestureIds(drv), ["br(handytech):escape", "br(handytech):return", "br(handytech):b4+space"])

	def test_activator_escape_return(self) -> None:
		drv, t = connect(ACTIVATOR, properties=40)
		t.feed(extKey(ACTIVATOR, 0x7A) + extKey(ACTIVATOR, 0xFA) + extKey(ACTIVATOR, 0x78) + extKey(ACTIVATOR, 0xF8))
		self.assertEqual(gestureIds(drv), ["br(handytech):escape", "br(handytech):joystickaction"])


class HidTests(_Isolated):
	def test_native_hid(self) -> None:
		drv, t = connectSimulated(
			HandyTechDriver,
			responder=hidResponder(serialResponder(ACTIVE_BRAILLE, properties=40)),
			matchType="hid",
			usbId="VID_1FE4&PID_0054",
			outputSize=32,
		)
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(t.opened[0][2], {})
		self.assertEqual(t.writes[0], bytes([0x02, 0x01, 0xFF, 0x00]) + bytes(28))
		self.assertEqual(unwrapHid(t.writes[1]), bytes([0x79, ACTIVE_BRAILLE, 0x01, 0xC1, 0x16]))
		before = len(t.writes)
		drv.display(list(range(1, 41)))
		packet = bytes([0x79, ACTIVE_BRAILLE, 41, 0x01]) + bytes(range(1, 41)) + b"\x16"
		# 45 bytes en bloques de 29 (32 - 3): dos informes terminados en 0x00.
		self.assertEqual(len(t.writes), before + 2)
		self.assertEqual(t.writes[before], bytes([0x02, 29]) + packet[:29] + b"\x00")
		self.assertEqual(t.writes[before + 1], (bytes([0x02, 16]) + packet[29:] + b"\x00").ljust(32, b"\x00"))
		t.feed(hidReport(extKey(ACTIVE_BRAILLE, 0x77)))
		t.feed(hidReport(extKey(ACTIVE_BRAILLE, 0xF7)))
		self.assertEqual(gestureIds(drv), ["br(handytech):joystickdown"])
		# Informes de otro tipo se ignoran.
		t.feed(bytes([0xFC, 0x02, 0x01, 0x00]))
		self.assertEqual(gestureIds(drv), [])

	def test_hid_serial_converter(self) -> None:
		drv, t = connectSimulated(
			HandyTechDriver,
			responder=hidResponder(serialResponder(0x74, properties=40), chunk=1),
			matchType="hid",
			usbId="VID_1FE4&PID_0003",
			outputSize=32,
		)
		self.assertEqual(t.writes[0], bytes([0xFB, 0x01]) + bytes(30))
		self.assertEqual(unwrapHid(t.writes[1]), b"\xff")
		self.assertEqual(drv.deviceName, "Handy Tech Braille Star 40")
		self.assertEqual(drv.numCells, 40)
		# El flujo serie llega de uno en uno o de dos en dos bytes.
		stream = extKey(0x74, 0x0C) + extKey(0x74, 0x8C)
		for i in range(0, len(stream), 2):
			t.feed(hidReport(stream[i : i + 2]))
		self.assertEqual(gestureIds(drv), ["br(handytech):lefttaktop"])

	def test_bluetooth_hid_is_native(self) -> None:
		drv, t = connectSimulated(
			HandyTechDriver,
			responder=hidResponder(serialResponder(0x61, properties=16)),
			matchType="hid",
			bluetooth=True,
			name="Actilino AL123",
			outputSize=32,
		)
		self.assertEqual(drv.numCells, 16)
		self.assertEqual(drv.model, "Actilino")
		self.assertEqual(t.writes[0][:4], bytes([0x02, 0x01, 0xFF, 0x00]))


class ClockAndAtcTests(_Isolated):
	def test_clock_sync(self) -> None:
		drv, t = connect(ACTIVE_BRAILLE, properties=40)
		now = datetime.datetime(2026, 10, 6, 12, 30, 15)
		with mock.patch.object(drv, "_now", return_value=now):
			n = len(t.writes)
			# Hora correcta: no se cambia.
			t.feed(ext(ACTIVE_BRAILLE, bytes([0x45, 0x07, 0xEA, 10, 6, 12, 30, 17])))
			self.assertEqual(len(t.writes), n)
			# Diez minutos de diferencia: se pone en hora (año con el byte bajo primero).
			t.feed(ext(ACTIVE_BRAILLE, bytes([0x45, 0x07, 0xEA, 10, 6, 12, 40, 15])))
		self.assertEqual(t.writes[-1], ext(ACTIVE_BRAILLE, bytes([0x44, 0xEA, 0x07, 10, 6, 12, 30, 15])))

	def test_atc(self) -> None:
		drv, t = connect(ACTIVE_BRAILLE, properties=40)
		self.assertTrue(drv.setAtc(True))
		self.assertEqual(t.writes[-1], ext(ACTIVE_BRAILLE, b"\x50\x01"))
		t.feed(ext(ACTIVE_BRAILLE, b"\x55\x07"))
		self.assertEqual(drv.readingPosition, 7)
		t.feed(ext(ACTIVE_BRAILLE, b"\x55\xff"))
		self.assertIsNone(drv.readingPosition)
		drv2, _t2 = connect(BASIC_BRAILLE_40, properties=40)
		self.assertFalse(drv2.setAtc(True))


class DetectionTests(_Isolated):
	def test_matches(self) -> None:
		devs = [
			DeviceInfo("hid", r"\\?\hid#ab", usbId="VID_1FE4&PID_0054"),
			DeviceInfo("hid", r"\\?\hid#adapter", usbId="VID_1FE4&PID_0003"),
			DeviceInfo("hid", r"\\?\hid#otro", usbId="VID_1234&PID_0001"),
			DeviceInfo("serial", "COM3", usbId="VID_0403&PID_6001"),
			DeviceInfo("serial", "COM4", usbId="VID_0921&PID_1200"),
			DeviceInfo("serial", "COM5", bluetooth=True, bluetoothName="Braille Star 40 BS1234"),
			DeviceInfo("serial", "COM6", bluetooth=True, bluetoothName="Otra línea"),
			DeviceInfo("hid", r"\\?\hid#bt", bluetooth=True, bluetoothName="Active Braille AB4/12345"),
		]
		ms = HandyTechDriver.getMatches(devs, allowGeneric=False)
		self.assertEqual([(m.type, m.port, m.bluetooth) for m in ms], [
			("hid", r"\\?\hid#ab", False),
			("hid", r"\\?\hid#adapter", False),
			("serial", "COM5", True),
			("hid", r"\\?\hid#bt", True),
		])
		ms = HandyTechDriver.getMatches(devs, allowGeneric=True, bluetooth=False)
		self.assertEqual([m.port for m in ms], [r"\\?\hid#ab", r"\\?\hid#adapter", "COM3", "COM4"])

	def test_all_bluetooth_prefixes(self) -> None:
		for name in ("Actilino AL1", "Basic Braille Plus BP1", "Easy Braille EBR1", "myBraille 40", "Activator 1", "Braille Wave BW1", "Braillino BL1", "Active Star AS1", "Basic Braille BB1"):
			dev = DeviceInfo("serial", "COM9", bluetooth=True, bluetoothName=name)
			self.assertIsNotNone(HandyTechDriver.matchDevice(dev), name)


class GestureMapTests(_Isolated):
	def _knownKeys(self) -> set[str]:
		keys = {"routing", "multiRouting", "space"} | set(HandyTechDriver.dotKeys)
		for info in MODELS.values():
			keys |= set(info.keys.values())
		return keys

	def test_values_and_keys(self) -> None:
		known = self._knownKeys()
		ident = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
		maps = [HandyTechDriver.gestureMap] + list(HandyTechDriver.modelGestureMaps.values())
		for gmap in maps:
			for keys, target in gmap.items():
				self.assertTrue(target.startswith("kb:") or ident.match(target), target)
				for k in keys.split("+"):
					self.assertIn(k, known, keys)
		for model in HandyTechDriver.modelGestureMaps:
			self.assertIn(model, {i.series for i in MODELS.values()})

	def test_driver_script_gestures(self) -> None:
		known = {k.lower() for k in self._knownKeys()}
		gestures = [g for g, s in HandyTechDriver.iterClassGestures() if s == "toggleBrailleInput"]
		self.assertEqual(len(gestures), 6)
		for gid in gestures:
			self.assertTrue(gid.startswith("br(handytech):"), gid)
			for k in gid.split(":", 1)[1].split("+"):
				self.assertIn(k, known, gid)

	def test_no_dot_only_commands(self) -> None:
		dots = set(HandyTechDriver.dotKeys)
		for keys in HandyTechDriver.gestureMap:
			self.assertFalse(set(keys.split("+")) <= dots, keys)

	def test_same_chord_in_both_modes(self) -> None:
		gm = HandyTechDriver.gestureMap
		self.assertEqual(gm["space+dot1"], gm["leftSpace+b4"])
		self.assertEqual(gm["space+dot4+dot6"], gm["rightSpace+b5+b7"])
		self.assertEqual(HandyTechDriver.modelGestureMaps["EasyBraille"]["left+b4"], "kb:upArrow")

	def test_model_table(self) -> None:
		self.assertEqual(MODELS[0x8B].cells, 160)
		self.assertEqual(MODELS[0x88].statusCells, 4)
		self.assertTrue(MODELS[0x05].oldProtocol)
		self.assertFalse(MODELS[0x74].oldProtocol)


class SettingsTests(_Isolated):
	def test_settings_applied_on_connect(self) -> None:
		STORE.update({"dotFirmness": 2, "atc": True, "brailleInput": True})
		drv, t = connect(ACTIVE_BRAILLE, properties=40)
		self.assertIn(ext(ACTIVE_BRAILLE, b"\x60\x02"), t.writes)
		self.assertIn(ext(ACTIVE_BRAILLE, b"\x50\x01"), t.writes)
		self.assertNotIn(ext(ACTIVE_BRAILLE, b"\x61"), t.writes)
		self.assertTrue(drv.brailleInput)
		self.assertTrue(drv.atcEnabled)

	def test_firmness_read_from_display_when_unset(self) -> None:
		drv, t = connect(ACTIVE_BRAILLE, properties=40)
		self.assertIn(ext(ACTIVE_BRAILLE, b"\x61"), t.writes)
		# ATC desactivado por defecto: no se envía nada al conectar.
		self.assertFalse(any(w[3:4] == b"\x50" for w in t.writes))
		t.feed(ext(ACTIVE_BRAILLE, b"\x61\x00"))
		self.assertEqual(STORE["dotFirmness"], 0)
		self.assertEqual(drv.getSetting("dotFirmness"), 0)

	def test_apply_settings(self) -> None:
		STORE.update({"dotFirmness": 1, "atc": True})
		drv, t = connect(ACTIVE_BRAILLE, properties=40)
		STORE.update({"dotFirmness": 0, "atc": False, "brailleInput": True})
		n = len(t.writes)
		drv.applySettings()
		self.assertEqual(t.writes[n:], [ext(ACTIVE_BRAILLE, b"\x60\x00"), ext(ACTIVE_BRAILLE, b"\x50\x00")])
		self.assertFalse(drv.atcEnabled)
		self.assertTrue(drv.brailleInput)

	def test_apply_settings_unsupported_model(self) -> None:
		drv, t = connect(BASIC_BRAILLE_40, properties=40)
		STORE.update({"dotFirmness": 2, "atc": True})
		n = len(t.writes)
		drv.applySettings()
		self.assertEqual(t.writes[n:], [])
		self.assertFalse(drv.atcEnabled)

	def test_braille_input_persists(self) -> None:
		drv, t = connect(BASIC_BRAILLE_40, properties=40)
		k = lambda c: extKey(BASIC_BRAILLE_40, c)  # noqa: E731
		t.feed(k(0x10) + k(0x03) + k(0x0B) + k(0x0F) + k(0x90) + k(0x83) + k(0x8B) + k(0x8F))
		runToggle(self, drv)
		self.assertIs(STORE["brailleInput"], True)
		# Nueva sesión: se restaura el modo.
		drv2, t2 = connect(BASIC_BRAILLE_40, properties=40)
		self.assertTrue(drv2.brailleInput)
		t2.feed(extKey(BASIC_BRAILLE_40, 0x0F) + extKey(BASIC_BRAILLE_40, 0x8F))
		self.assertEqual(gestureIds(drv2), ["br(handytech):dot1"])


class AtcScrollTests(_Isolated):
	def _connect(self):
		STORE["atc"] = True
		drv, t = connect(ACTIVE_BRAILLE, properties=40)
		drv.display([0x01, 0x03, 0x07])
		return drv, t

	def test_scrolls_at_last_cell_with_content(self) -> None:
		drv, t = self._connect()
		drv._shownSince -= 1  # pasado el tiempo de asentamiento
		with mock.patch("tiresias.queue_handler.queueFunction") as q:
			t.feed(ext(ACTIVE_BRAILLE, b"\x55\x01"))
			self.assertFalse(q.called)
			self.assertEqual(drv.readingPosition, 1)
			t.feed(ext(ACTIVE_BRAILLE, b"\x55\x02"))
			q.assert_called_once_with(drv._atcScrollForward)
			# Una sola vez por contenido mostrado.
			t.feed(ext(ACTIVE_BRAILLE, b"\x55\x03"))
			self.assertEqual(q.call_count, 1)
		fakeHandler = mock.Mock()
		with mock.patch("tiresias.braille.handler", fakeHandler):
			drv._atcScrollForward()
		fakeHandler.scrollForward.assert_called_once_with(auto=True)
		# Contenido nuevo: vuelve a poder avanzar.
		drv.display([0x01, 0x01])
		drv._shownSince -= 1
		with mock.patch("tiresias.queue_handler.queueFunction") as q:
			t.feed(ext(ACTIVE_BRAILLE, b"\x55\x01"))
		self.assertTrue(q.called)

	def test_ignores_reading_right_after_refresh(self) -> None:
		drv, t = self._connect()
		with mock.patch("tiresias.queue_handler.queueFunction") as q:
			t.feed(ext(ACTIVE_BRAILLE, b"\x55\x02"))
		self.assertFalse(q.called)

	def test_no_scroll_when_atc_disabled(self) -> None:
		drv, t = connect(ACTIVE_BRAILLE, properties=40)
		drv.display([0x01])
		drv._shownSince -= 1
		with mock.patch("tiresias.queue_handler.queueFunction") as q:
			t.feed(ext(ACTIVE_BRAILLE, b"\x55\x00"))
		self.assertFalse(q.called)
		self.assertEqual(drv.readingPosition, 0)


class WideRoutingTests(_Isolated):
	def test_routing_beyond_96_cells(self) -> None:
		drv, t = connect(0x8B, properties=160)
		self.assertEqual(drv.numCells, 160)
		code = 0x20 + 120
		t.feed(ext(0x8B, bytes([0x04, code >> 8, code & 0xFF])))
		t.feed(ext(0x8B, bytes([0x04, 0x80 | code >> 8, code & 0xFF])))
		self.assertEqual(drv.lastGestures[0].routingIndex, 120)
		self.assertEqual(gestureIds(drv), ["br(handytech):routing"])
		# Última celda, y una tecla normal en 16 bits (B4).
		code = 0x20 + 159
		t.feed(ext(0x8B, bytes([0x04, 0x00, code])) + ext(0x8B, bytes([0x04, 0x80, code])))
		t.feed(ext(0x8B, b"\x04\x00\x0f") + ext(0x8B, b"\x04\x80\x0f"))
		self.assertEqual(drv.lastGestures[0].routingIndex, 159)
		self.assertEqual(gestureIds(drv), ["br(handytech):routing", "br(handytech):b4"])
		# Los códigos de un byte siguen funcionando.
		t.feed(extKey(0x8B, 0x25) + extKey(0x8B, 0xA5))
		self.assertEqual(drv.lastGestures[0].routingIndex, 5)

	def test_short_displays_keep_one_byte_codes(self) -> None:
		drv, t = connect(BASIC_BRAILLE_40, properties=40)
		# Un byte de más en una línea de 40 celdas no cambia la interpretación.
		t.feed(ext(BASIC_BRAILLE_40, b"\x04\x0f\x00") + ext(BASIC_BRAILLE_40, b"\x04\x8f\x00"))
		self.assertEqual(gestureIds(drv), ["br(handytech):b4"])


if __name__ == "__main__":
	unittest.main()
