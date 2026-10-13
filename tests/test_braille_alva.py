"""Pruebas del controlador de las líneas Optelec ALVA (serie 6 / BC6)."""

from __future__ import annotations

import datetime
import unittest
from unittest import mock

import braille_sim  # noqa: F401
from braille_sim import connectSimulated, gestureIds

from tiresias.baseobject import normalizeGestureId
from tiresias.braille.drivers import base, hwio
from tiresias.braille.drivers.alva import AlvaDriver
from tiresias.braille.drivers.ports import DeviceInfo

ESC = b"\x1b"
NOW = datetime.datetime(2026, 10, 6, 12, 30, 15)


def _rtc(dt: datetime.datetime) -> bytes:
	return bytes([dt.year & 0xFF, dt.year >> 8, dt.month, dt.day, dt.hour, dt.minute, dt.second])


def _sync(self, func):
	"""Sustituye a ``_inBackground``: ejecuta la tarea en el acto."""
	func()


class _Features:
	"""Informes de características simulados de una línea HID."""

	def __init__(self, cells=40, keySettings=0x00, rtc=None, malformedFirst=False, rawWritable=True):
		self.cells = cells
		self.keySettings = keySettings
		self.rtc = rtc if rtc is not None else _rtc(NOW)
		self.malformed = malformedFirst
		self.rawWritable = rawWritable
		self.requests: list[int] = []

	def get(self, reportId):
		self.requests.append(reportId)
		if reportId == 0x05:
			if self.malformed:
				self.malformed = False
				return bytes([0x05, 0, 7, 0, 0, 0, 0, 0])
			return bytes([0x05, 0, 1, 0, 0, 0, self.cells, 0])
		if reportId == 0x06:
			return bytes([0x06, self.keySettings])
		if reportId == 0x0A:
			return bytes([0x0A]) + self.rtc
		raise hwio.IoError(0, "informe desconocido")

	def responder(self, data):
		if data.startswith(b"FEATURE\x06") and self.rawWritable:
			self.keySettings = data[8]
		return None


def _patchFeatures(features):
	return mock.patch.object(hwio.MemoryTransport, "getFeature", lambda transport, reportId: features.get(reportId), create=True)


def _connectHid(features: _Features, usbId="VID_0798&PID_0640", now=NOW):
	with (
		_patchFeatures(features),
		mock.patch.object(AlvaDriver, "_inBackground", _sync),
		mock.patch.object(AlvaDriver, "_now", lambda self: now),
	):
		drv, t = connectSimulated(AlvaDriver, responder=features.responder, matchType="hid", port=r"\\?\hid#alva", usbId=usbId)
	return drv, t


class _Line:
	"""Línea por Bluetooth (puerto serie) simulada."""

	def __init__(self, deviceId=0x40, cells=40, raw=0, rtc=None, rawWritable=True):
		self.deviceId = deviceId
		self.cells = cells
		self.raw = raw
		self.rtc = rtc if rtc is not None else _rtc(NOW)
		self.rawWritable = rawWritable

	def __call__(self, data):
		if data == ESC + b"??":
			return ESC + b"?" + bytes([self.deviceId])
		if data == ESC + b"E?":
			return ESC + b"E" + bytes([self.cells])
		if data == ESC + b"H?":
			return ESC + b"H" + self.rtc
		if data == ESC + b"r?":
			return ESC + b"r" + bytes([self.raw])
		if data[:2] == ESC + b"r" and len(data) == 3:
			if self.rawWritable:
				self.raw = data[2]
			return None
		return None


def _connectSerial(line: _Line, now=NOW, bluetoothName="ALVA BC640 1234"):
	with mock.patch.object(AlvaDriver, "_now", lambda self: now), mock.patch.object(AlvaDriver, "_inBackground", _sync):
		return connectSimulated(AlvaDriver, responder=line, matchType="serial", port="COM7", bluetooth=True, name=bluetoothName)


def _runQueued(q):
	"""Ejecuta (con la voz simulada) lo último que se ha encolado al núcleo y devuelve el mensaje."""
	if not q.called:
		return None
	func, *args = q.call_args[0]
	with mock.patch("tiresias.braille.drivers.alva._speak") as speak:
		func(*args)
	return speak.call_args[0][0] if speak.called else None


def _hidKey(t, group, number):
	"""Pulsa y suelta una tecla (informe 0x04)."""
	t.feed(bytes([0x04, number, group]))
	t.feed(bytes([0x04, number, group | 0x80]))


def _serialKey(group, number, release=False):
	return ESC + b"K" + bytes([group | (0x80 if release else 0), number])


#: Ajustes del controlador simulados (sustituyen a la configuración).
STORE: dict = {}
KEY = "hidKeyboardInput"


class _Base(unittest.TestCase):
	"""Por defecto la línea simula un teclado HID (no se le cambia el modo)."""

	def setUp(self) -> None:
		STORE.clear()
		STORE[KEY] = True
		patches = (
			mock.patch.object(AlvaDriver, "getSetting", classmethod(lambda cls, key: STORE.get(key, False))),
			mock.patch.object(AlvaDriver, "setSetting", classmethod(lambda cls, key, value: STORE.__setitem__(key, value))),
		)
		for p in patches:
			p.start()
			self.addCleanup(p.stop)


# ===================================================================== HID
class HidConnectionTests(_Base):
	def test_bc640(self) -> None:
		f = _Features(cells=40)
		drv, t = _connectHid(f)
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(drv.model, "BC640")
		self.assertEqual(drv.deviceName, "ALVA BC640")
		self.assertTrue(drv._isHid)
		self.assertEqual(t.openArgs, {"exclusive": False})
		# Ajustes de pantalla, de teclas y reloj; el reloj está en hora: no se toca.
		self.assertEqual(f.requests, [0x05, 0x06, 0x0A])
		self.assertEqual(t.features, [])
		self.assertFalse(drv._rawInput)

	def test_bc680_malformed_first_report(self) -> None:
		f = _Features(cells=80, malformedFirst=True)
		drv, t = _connectHid(f, usbId="VID_0798&PID_0680")
		self.assertEqual(drv.numCells, 80)
		self.assertEqual(drv.model, "BC680")
		self.assertEqual(f.requests[:2], [0x05, 0x05])

	def test_protocol_converter_and_unknown(self) -> None:
		drv, t = _connectHid(_Features(cells=40), usbId="VID_0798&PID_0699")
		self.assertEqual(drv.model, "ProtocolConverter")
		self.assertEqual(drv.deviceName, "Convertidor de protocolo Optelec")
		drv, t = _connectHid(_Features(cells=12), usbId="VID_0798&PID_0612")
		self.assertEqual((drv.model, drv.numCells), ("ALVA12", 12))
		self.assertTrue(drv.model.isalnum())

	def test_no_cells_fails(self) -> None:
		with self.assertRaises(base.DisplayNotFound):
			_connectHid(_Features(cells=0))

	def test_feature_error_fails(self) -> None:
		def broken(transport, reportId):
			raise hwio.IoError(31, "error")

		with mock.patch.object(hwio.MemoryTransport, "getFeature", broken, create=True), self.assertRaises(base.DisplayNotFound):
			connectSimulated(AlvaDriver, matchType="hid", usbId="VID_0798&PID_0640")

	def test_time_sync(self) -> None:
		old = NOW - datetime.timedelta(minutes=3)
		f = _Features(rtc=_rtc(old))
		drv, t = _connectHid(f)
		self.assertEqual(t.features, [bytes([0x0A]) + _rtc(NOW)])

	def test_time_small_drift_and_invalid(self) -> None:
		f = _Features(rtc=_rtc(NOW - datetime.timedelta(seconds=3)))
		drv, t = _connectHid(f)
		self.assertEqual(t.features, [])
		# Año fuera de rango: la línea no tiene reloj.
		drv, t = _connectHid(_Features(rtc=bytes(7)))
		self.assertEqual(t.features, [])
		# Fecha imposible (mes 13).
		drv, t = _connectHid(_Features(rtc=bytes([0xEA, 0x07, 13, 1, 0, 0, 0])))
		self.assertEqual(t.features, [])

	def test_raw_input_read(self) -> None:
		STORE[KEY] = False
		drv, t = _connectHid(_Features(keySettings=0x30))
		self.assertTrue(drv._rawInput)


class HidOutputTests(_Base):
	def test_40_cells(self) -> None:
		drv, t = _connectHid(_Features(cells=40))
		drv.display([0x01, 0xFF, 0x1B])
		self.assertEqual(t.writes[-1], bytes([0x02, 0, 40, 0x01, 0xFF, 0x1B]) + bytes(37))

	def test_80_cells_two_reports(self) -> None:
		drv, t = _connectHid(_Features(cells=80), usbId="VID_0798&PID_0680")
		cells = list(range(80))
		drv.display(cells)
		self.assertEqual(t.writes[-2], bytes([0x02, 0, 40]) + bytes(range(40)))
		self.assertEqual(t.writes[-1], bytes([0x02, 40, 40]) + bytes(range(40, 80)))

	def test_odd_cell_count(self) -> None:
		drv, t = _connectHid(_Features(cells=12), usbId="VID_0798&PID_0612")
		drv.display([0x3F] * 12)
		self.assertEqual(t.writes[-1], bytes([0x02, 0, 12]) + bytes([0x3F] * 12))


class HidInputTests(_Base):
	def setUp(self) -> None:
		super().setUp()
		self.drv, self.t = _connectHid(_Features(cells=40))

	def test_thumb_keys(self) -> None:
		for n in range(5):
			_hidKey(self.t, 0x71, n)
		self.assertEqual(gestureIds(self.drv), [f"br(alva):t{i}" for i in range(1, 6)])

	def test_model_identifier(self) -> None:
		_hidKey(self.t, 0x71, 2)
		self.assertEqual(self.drv.lastGestures[-1].identifiers, ["br(alva.bc640):t3", "br(alva):t3"])

	def test_combination(self) -> None:
		t = self.t
		t.feed(bytes([0x04, 0, 0x71]))  # t1
		t.feed(bytes([0x04, 2, 0x71]))  # t3
		t.feed(bytes([0x04, 0, 0xF1]))
		t.feed(bytes([0x04, 2, 0xF1]))
		self.assertEqual(gestureIds(self.drv), ["br(alva):t1+t3"])

	def test_right_hand_keys_bc680(self) -> None:
		drv, t = _connectHid(_Features(cells=80), usbId="VID_0798&PID_0680")
		_hidKey(t, 0x71, 9)  # t5 derecha
		_hidKey(t, 0x73, 9 + 3)  # spEnter derecha
		self.assertEqual(gestureIds(drv), ["br(alva):t5", "br(alva):spenter"])
		# Las dos t1 (izquierda y derecha) se siguen por separado.
		t.feed(bytes([0x04, 0, 0x71]))
		t.feed(bytes([0x04, 5, 0x71]))
		t.feed(bytes([0x04, 5, 0xF1]))
		t.feed(bytes([0x04, 0, 0xF1]))
		g = drv.lastGestures[-1]
		self.assertEqual(g.keys, ["t1"])
		self.assertEqual(len(drv.lastGestures), 1)

	def test_smartpad_and_etouch(self) -> None:
		for n in range(9):
			_hidKey(self.t, 0x73, n)
		for n in range(4):
			_hidKey(self.t, 0x72, n)
		self.assertEqual(
			gestureIds(self.drv),
			[
				"br(alva):sp1",
				"br(alva):sp2",
				"br(alva):spleft",
				"br(alva):spenter",
				"br(alva):spup",
				"br(alva):spdown",
				"br(alva):spright",
				"br(alva):sp3",
				"br(alva):sp4",
				"br(alva):etouch1",
				"br(alva):etouch2",
				"br(alva):etouch3",
				"br(alva):etouch4",
			],
		)

	def test_routing_rows(self) -> None:
		_hidKey(self.t, 0x74, 5)
		g = self.drv.lastGestures[-1]
		self.assertEqual((g.keys, g.routingIndex), (["routing"], 5))
		_hidKey(self.t, 0x74, 0x80 | 39)
		g = self.drv.lastGestures[-1]
		self.assertEqual((g.keys, g.routingIndex), (["routing2"], 39))
		self.assertEqual(gestureIds(self.drv), ["br(alva):routing", "br(alva):routing2"])

	def test_multi_routing(self) -> None:
		t = self.t
		t.feed(bytes([0x04, 10, 0x74]))
		t.feed(bytes([0x04, 3, 0x74]))
		t.feed(bytes([0x04, 10, 0xF4]))
		t.feed(bytes([0x04, 3, 0xF4]))
		g = self.drv.lastGestures[-1]
		self.assertEqual((g.keys, g.routingIndexes), (["multiRouting"], [3, 10]))

	def test_thumb_plus_smartpad(self) -> None:
		t = self.t
		t.feed(bytes([0x04, 2, 0x71]))  # t3
		t.feed(bytes([0x04, 4, 0x73]))  # spUp
		t.feed(bytes([0x04, 4, 0xF3]))
		t.feed(bytes([0x04, 2, 0xF1]))
		self.assertEqual(gestureIds(self.drv), ["br(alva):spup+t3"])

	def _typeDots(self, t, numbers):
		for n in numbers:
			t.feed(bytes([0x04, n, 0x78]))
		for n in numbers:
			t.feed(bytes([0x04, n, 0xF8]))

	def test_braille_keyboard_raw(self) -> None:
		STORE[KEY] = False
		drv, t = _connectHid(_Features(keySettings=0x30))
		self._typeDots(t, [1, 2, 11])  # puntos 1 y 2 y espacio
		g = drv.lastGestures[-1]
		self.assertEqual(g.identifiers[-1], "br(alva):dot1+dot2+space")
		self.assertEqual((g.dots, g.space), (0b11, True))
		self._typeDots(t, [7, 8])
		self.assertEqual(drv.lastGestures[-1].dots, 0b11000000)
		# Teclas de órdenes del teclado: no son escritura braille.
		self._typeDots(t, [9])
		self._typeDots(t, [13])
		self.assertEqual([g.identifiers[-1] for g in drv.lastGestures[-2:]], ["br(alva):control", "br(alva):enter"])
		self.assertEqual(drv.lastGestures[-1].dots, 0)

	def test_braille_keyboard_hid_simulation(self) -> None:
		# Con la simulación de teclado HID la línea escribe por sí misma.
		self._typeDots(self.t, [1, 2])
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.identifiers[-1], "br(alva):dot1+dot2")
		self.assertEqual((g.dots, g.space), (0, False))

	def test_unknown_keys_ignored(self) -> None:
		_hidKey(self.t, 0x71, 12)
		_hidKey(self.t, 0x79, 1)
		self.t.feed(bytes([0x03, 1, 2]))  # otro informe
		self.assertEqual(gestureIds(self.drv), [])

	def test_settings_changed_split_point(self) -> None:
		f = _Features(cells=40)
		drv, t = _connectHid(f)
		f.cells = 30
		f.keySettings = 0x30
		with mock.patch.object(AlvaDriver, "_inBackground", _sync), _patchFeatures(f):
			t.feed(bytes([0x04, 0x01, 0x01]))
		self.assertEqual(drv.numCells, 30)
		self.assertTrue(drv._rawInput)
		self.assertEqual(gestureIds(drv), [])
		drv.display([1])
		self.assertEqual(t.writes[-1], bytes([0x02, 0, 30, 1]) + bytes(29))

	def test_refresh_after_cell_change_when_active(self) -> None:
		drv = self.drv
		drv._activated = True
		with mock.patch("tiresias.queue_handler.queueFunction") as q:
			drv._setNumCells(20)
		q.assert_called_once_with(drv._refreshDisplay)
		with mock.patch("tiresias.queue_handler.queueFunction") as q:
			drv._setNumCells(20)
		q.assert_not_called()


class HidKeyboardToggleTests(_Base):
	def _toggle(self, drv, f):
		with (
			mock.patch.object(AlvaDriver, "_inBackground", _sync),
			_patchFeatures(f),
			mock.patch("tiresias.queue_handler.queueFunction") as q,
		):
			drv.script_toggleHidKeyboardInput(None)
		return _runQueued(q)

	def test_toggle_hid(self) -> None:
		f = _Features(keySettings=0x01)
		drv, t = _connectHid(f)
		msg = self._toggle(drv, f)
		self.assertEqual(t.features[-1], bytes([0x06, 0x31]))
		self.assertTrue(drv._rawInput)
		self.assertTrue(msg.startswith("Simulación de teclado HID desactivada"), msg)
		self.assertIs(STORE[KEY], False)
		msg = self._toggle(drv, f)
		self.assertEqual(t.features[-1], bytes([0x06, 0x01]))
		self.assertFalse(drv._rawInput)
		self.assertTrue(msg.startswith("Simulación de teclado HID activada"), msg)
		self.assertIs(STORE[KEY], True)

	def test_toggle_not_supported(self) -> None:
		f = _Features(rawWritable=False)
		drv, t = _connectHid(f)
		msg = self._toggle(drv, f)
		self.assertFalse(drv._rawInput)
		self.assertIs(STORE[KEY], True)
		self.assertIn("no permite", msg)

	def test_saved_setting_applied_on_connect(self) -> None:
		# Ajuste guardado: simulación desactivada; la línea la tiene activada.
		STORE[KEY] = False
		f = _Features(keySettings=0x01)
		drv, t = _connectHid(f)
		self.assertEqual(t.features[-1], bytes([0x06, 0x31]))
		self.assertTrue(drv._rawInput)

	def test_saved_setting_already_matches(self) -> None:
		STORE[KEY] = False
		drv, t = _connectHid(_Features(keySettings=0x30))
		self.assertEqual(t.features, [])

	def test_apply_settings_from_options(self) -> None:
		f = _Features(keySettings=0x00)
		drv, t = _connectHid(f)
		STORE[KEY] = False
		with mock.patch.object(AlvaDriver, "_inBackground", _sync), _patchFeatures(f):
			drv.applySettings()
		self.assertEqual(t.features[-1], bytes([0x06, 0x30]))
		self.assertTrue(drv._rawInput)
		# Sin cambios: no se toca la línea.
		t.features.clear()
		with mock.patch.object(AlvaDriver, "_inBackground", _sync), _patchFeatures(f):
			drv.applySettings()
		self.assertEqual(t.features, [])

	def test_apply_settings_not_supported(self) -> None:
		f = _Features(keySettings=0x00, rawWritable=False)
		drv, t = _connectHid(f)
		STORE[KEY] = False
		with (
			mock.patch.object(AlvaDriver, "_inBackground", _sync),
			_patchFeatures(f),
			mock.patch("tiresias.queue_handler.queueFunction") as q,
		):
			drv.applySettings()
		self.assertFalse(drv._rawInput)
		self.assertIn("no permite", q.call_args[0][1])

	def test_apply_settings_disconnected(self) -> None:
		f = _Features()
		drv, t = _connectHid(f)
		drv.numCells = 0
		STORE[KEY] = False
		with mock.patch.object(AlvaDriver, "_inBackground") as bg:
			drv.applySettings()
		bg.assert_not_called()

	def test_setting_declared(self) -> None:
		(setting,) = AlvaDriver.driverSettings
		self.assertEqual((setting.key, setting.kind, setting.default), ("hidKeyboardInput", "bool", False))
		self.assertTrue(setting.label)

	def test_preference_reapplied_on_reconnect(self) -> None:
		f = _Features(keySettings=0x00)
		drv, t = _connectHid(f)
		STORE[KEY] = False
		with (
			mock.patch.object(AlvaDriver, "_inBackground", _sync),
			mock.patch.object(AlvaDriver, "_now", lambda self: NOW),
			mock.patch.object(AlvaDriver, "_open", lambda self, match, baudrate=None, **kw: t),
			_patchFeatures(f),
		):
			drv._resetState()
			drv._connect(base.DeviceMatch("hid", "VID_0798&PID_0640", r"\\?\hid#alva"))
		self.assertEqual(t.features[-1], bytes([0x06, 0x30]))
		self.assertTrue(drv._rawInput)

	def test_script_gesture(self) -> None:
		drv, t = _connectHid(_Features())
		_hidKey(t, 0x71, 0)
		t.feed(bytes([0x04, 0, 0x71]))
		t.feed(bytes([0x04, 3, 0x73]))
		t.feed(bytes([0x04, 3, 0xF3]))
		t.feed(bytes([0x04, 0, 0xF1]))
		g = drv.lastGestures[-1]
		self.assertEqual(g.identifiers[-1], "br(alva):spenter+t1")
		with mock.patch("tiresias.input.gestures.userMap.lookup", return_value=None):
			func = drv.getScript(g)
		self.assertIsNotNone(func)
		self.assertEqual(func.__name__, "script_toggleHidKeyboardInput")
		self.assertTrue(func.__doc__)


# ===================================================================== serie
class SerialTests(_Base):
	def test_connect(self) -> None:
		line = _Line(deviceId=0x80, cells=80)
		drv, t = _connectSerial(line)
		self.assertEqual(drv.numCells, 80)
		self.assertEqual(drv.model, "BC680")
		self.assertEqual(drv.deviceName, "ALVA BC680")
		self.assertFalse(drv._isHid)
		self.assertEqual(t.baudrate, 9600)
		self.assertEqual(t.writes[:5], [ESC + b"??", ESC + b"E?", ESC + b"H?", ESC + b"r\x00", ESC + b"r?"])

	def test_no_answer(self) -> None:
		with mock.patch.object(AlvaDriver, "_waitFor", lambda self, p, timeout: p()), self.assertRaises(base.DisplayNotFound):
			connectSimulated(AlvaDriver, responder=lambda d: None, matchType="serial", port="COM7", bluetooth=True)

	def test_no_cell_count(self) -> None:
		with mock.patch.object(AlvaDriver, "_waitFor", lambda self, p, timeout: p()), self.assertRaises(base.DisplayNotFound):
			connectSimulated(AlvaDriver, responder=_Line(cells=0), matchType="serial", port="COM7", bluetooth=True)

	def test_output(self) -> None:
		drv, t = _connectSerial(_Line(cells=40))
		drv.display([0x01, 0x1B, 0xFF])
		self.assertEqual(t.writes[-1], ESC + b"B" + bytes([0, 40, 0x01, 0x1B, 0xFF]) + bytes(37))

	def test_keys_and_split_stream(self) -> None:
		drv, t = _connectSerial(_Line())
		stream = (
			b"\x00garbage"
			+ _serialKey(0x71, 0)
			+ _serialKey(0x71, 2)
			+ _serialKey(0x71, 0, True)
			+ _serialKey(0x71, 2, True)
			+ _serialKey(0x74, 27)  # índice 27 = 0x1B (como ESC)
			+ _serialKey(0x74, 27, True)
			+ ESC
			+ b"V12345"  # versión: se ignora
			+ ESC
			+ b"Z"  # orden desconocida: se salta
			+ _serialKey(0x74, 0x80 | 2)
			+ _serialKey(0x74, 0x80 | 2, True)
		)
		for i in range(len(stream)):
			t.feed(stream[i : i + 1])
		gs = drv.lastGestures
		self.assertEqual([g.identifiers[-1] for g in gs], ["br(alva):t1+t3", "br(alva):routing", "br(alva):routing2"])
		self.assertEqual((gs[1].routingIndex, gs[2].routingIndex), (27, 2))
		self.assertEqual(bytes(drv._buffer), b"")

	def test_braille_input_raw(self) -> None:
		STORE[KEY] = False
		drv, t = _connectSerial(_Line(raw=1))
		self.assertTrue(drv._rawInput)
		t.feed(_serialKey(0x78, 11) + _serialKey(0x78, 4) + _serialKey(0x78, 4, True) + _serialKey(0x78, 11, True))
		g = drv.lastGestures[-1]
		self.assertEqual(g.identifiers[-1], "br(alva):dot4+space")
		self.assertEqual((g.dots, g.space), (0b1000, True))

	def test_time_sync(self) -> None:
		drv, t = _connectSerial(_Line(rtc=_rtc(NOW + datetime.timedelta(hours=1))))
		self.assertIn(ESC + b"H" + _rtc(NOW), t.writes)

	def test_time_in_sync(self) -> None:
		drv, t = _connectSerial(_Line())
		self.assertEqual([w for w in t.writes if w[:2] == ESC + b"H"], [ESC + b"H?"])

	def test_settings_changed(self) -> None:
		line = _Line(cells=40)
		drv, t = _connectSerial(line)
		line.cells = 32
		t.feed(_serialKey(0x01, 0x01))
		self.assertEqual(t.writes[-2:], [ESC + b"E?", ESC + b"r?"])
		self.assertEqual(drv.numCells, 32)
		self.assertEqual(gestureIds(drv), [])

	def test_toggle_serial(self) -> None:
		line = _Line(raw=0)
		drv, t = _connectSerial(line)
		with mock.patch.object(AlvaDriver, "_inBackground", _sync), mock.patch("tiresias.queue_handler.queueFunction") as q:
			drv.script_toggleHidKeyboardInput(None)
		self.assertIn(ESC + b"r\x01", t.writes)
		self.assertTrue(drv._rawInput)
		self.assertIn("desactivada", _runQueued(q))
		self.assertIs(STORE[KEY], False)

	def test_toggle_serial_not_supported(self) -> None:
		line = _Line(raw=0, rawWritable=False)
		drv, t = _connectSerial(line)
		with (
			mock.patch.object(AlvaDriver, "_inBackground", _sync),
			mock.patch.object(AlvaDriver, "_waitFor", lambda self, p, timeout: p()),
			mock.patch("tiresias.queue_handler.queueFunction") as q,
		):
			drv.script_toggleHidKeyboardInput(None)
		self.assertFalse(drv._rawInput)
		self.assertIn("no permite", q.call_args[0][1])

	def test_wanted_mode_sent_on_connect(self) -> None:
		line = _Line(raw=0)
		drv, t = _connectSerial(line)
		STORE[KEY] = False
		t.writes.clear()
		with mock.patch.object(AlvaDriver, "_now", lambda self: NOW), mock.patch.object(AlvaDriver, "_open", lambda self, match, baudrate=None, **kw: t):
			drv._resetState()
			drv._connect(base.DeviceMatch("serial", "ALVA BC640", "COM7", True))
		self.assertIn(ESC + b"r\x01", t.writes)
		self.assertTrue(drv._rawInput)


# ===================================================================== detección y mapa
class DetectionTests(_Base):
	def test_matches(self) -> None:
		devs = [
			DeviceInfo("hid", r"\\?\hid#640", usbId="VID_0798&PID_0640"),
			DeviceInfo("hid", r"\\?\hid#680", usbId="VID_0798&PID_0680"),
			DeviceInfo("hid", r"\\?\hid#699", usbId="VID_0798&PID_0699"),
			DeviceInfo("hid", r"\\?\hid#otro", usbId="VID_0798&PID_0001"),
			DeviceInfo("serial", "COM7", bluetooth=True, bluetoothName="ALVA BC640 0123"),
			DeviceInfo("serial", "COM8", bluetooth=True, bluetoothName="Brailliant"),
			DeviceInfo("serial", "COM9", usbId="VID_0403&PID_6001"),
			DeviceInfo("hid", r"\\?\hid#bt", bluetooth=True, bluetoothName="ALVA BC680 9"),
		]
		for allowGeneric in (False, True):
			ports = [m.port for m in AlvaDriver.getMatches(devs, allowGeneric=allowGeneric)]
			self.assertEqual(ports, [r"\\?\hid#640", r"\\?\hid#680", r"\\?\hid#699", "COM7", r"\\?\hid#bt"])
		self.assertEqual([m.port for m in AlvaDriver.getMatches(devs, bluetooth=False)], [r"\\?\hid#640", r"\\?\hid#680", r"\\?\hid#699"])
		self.assertEqual([m.port for m in AlvaDriver.getMatches(devs, usb=False)], ["COM7", r"\\?\hid#bt"])
		bt = AlvaDriver.matchDevice(devs[4])
		self.assertEqual((bt.type, bt.bluetooth, bt.id), ("serial", True, "ALVA BC640 0123"))


class GestureMapTests(_Base):
	def _allKeys(self) -> set[str]:
		from tiresias.braille.drivers import alva

		keys = set(alva.THUMB_KEYS) | set(alva.SMARTPAD_KEYS) | set(alva.ETOUCH_KEYS) | set(alva.KEYBOARD_KEYS.values())
		return keys | {"routing", "multiRouting", "routing2", "multiRouting2"}

	def test_values(self) -> None:
		from tiresias.global_commands import commands

		for keys, target in AlvaDriver.gestureMap.items():
			self.assertIsInstance(target, str)
			if target.startswith("kb:"):
				self.assertGreater(len(target), 3, keys)
				continue
			self.assertTrue(target.isidentifier(), target)
			# Las órdenes braille nuevas puede añadirlas otro módulo; el resto deben existir.
			if not target.startswith("braille_"):
				self.assertTrue(hasattr(commands, "script_" + target), target)

	def test_keys_exist(self) -> None:
		known = self._allKeys()
		for keys in AlvaDriver.gestureMap:
			for k in keys.split("+"):
				self.assertIn(k, known, keys)
		self.assertEqual(set(AlvaDriver.keyOrder), known - {"routing", "multiRouting", "routing2", "multiRouting2"})
		self.assertTrue(known <= set(AlvaDriver.keyDescriptions))

	def test_no_dot_only_commands(self) -> None:
		dots = set(AlvaDriver.dotKeys)
		for keys in AlvaDriver.gestureMap:
			parts = set(keys.split("+"))
			self.assertFalse(parts <= dots, keys)

	def test_script_gesture_not_in_map(self) -> None:
		ids = {normalizeGestureId(f"br(alva):{k}") for k in AlvaDriver.gestureMap}
		self.assertNotIn("br(alva):spenter+t1", ids)
		self.assertIn("br(alva):spenter+t1", dict(AlvaDriver.iterClassGestures()))

	def test_registered(self) -> None:
		from tiresias.braille.drivers import alva

		self.assertIs(alva.BrailleDisplayDriver, AlvaDriver)
		self.assertEqual(AlvaDriver.name, "alva")


if __name__ == "__main__":
	unittest.main()
