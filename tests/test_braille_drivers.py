"""Pruebas de la infraestructura de líneas braille: gestos, detección,
conexión simulada, desconexión y el controlador HID Braille estándar."""

from __future__ import annotations

import types
import unittest
from unittest import mock

import braille_sim  # noqa: F401  (prepara rutas y datos)
from braille_sim import connectSimulated, gestureIds

from tiresias.braille.drivers import base, detect, hwio
from tiresias.braille.drivers.base import HardwareDriver, KeyTracker, buildGesture
from tiresias.braille.drivers.hidBraille import USAGE_PAGE_BRAILLE, HidBrailleDriver, HidLayout
from tiresias.braille.drivers.ports import DeviceInfo, normalizeUsbId, parseBluetoothAddress


class KeyTrackerTests(unittest.TestCase):
	def test_chord_on_first_release(self) -> None:
		t = KeyTracker()
		self.assertIsNone(t.press("a"))
		self.assertIsNone(t.press("b"))
		self.assertEqual(t.release("a"), {"a", "b"})
		self.assertIsNone(t.release("b"))

	def test_new_press_after_partial_release(self) -> None:
		t = KeyTracker()
		t.press("a")
		t.press("b")
		t.release("b")
		self.assertIsNone(t.press("c"))
		self.assertEqual(t.release("c"), {"a", "c"})

	def test_update_set(self) -> None:
		t = KeyTracker()
		self.assertIsNone(t.update({"x", "y"}))
		self.assertEqual(t.update(set()), {"x", "y"})


class GestureTests(unittest.TestCase):
	def test_dots_and_space(self) -> None:
		g = buildGesture("drv", {"space", "dot1", "dot2"}, ["space", "dot1", "dot2"], {"dot1": 1, "dot2": 2}, {"space"})
		self.assertEqual(g.identifiers[-1], "br(drv):dot1+dot2+space")
		self.assertEqual(g.dots, 0b11)
		self.assertTrue(g.space)

	def test_not_braille_input_with_command_key(self) -> None:
		g = buildGesture("drv", {"dot1", "panLeft"}, [], {"dot1": 1}, {"space"})
		self.assertEqual(g.dots, 0)
		self.assertFalse(g.space)

	def test_routing_single_and_multi(self) -> None:
		g = buildGesture("drv", {("routing", 5)})
		self.assertEqual(g.keys, ["routing"])
		self.assertEqual(g.routingIndex, 5)
		g = buildGesture("drv", {("routing", 7), ("routing", 2)})
		self.assertEqual(g.keys, ["multiRouting"])
		self.assertEqual(g.routingIndexes, [2, 7])
		g = buildGesture("drv", {("routing2", 3), "d1"})
		self.assertEqual(g.identifiers[-1], "br(drv):d1+routing2")
		self.assertEqual(g.routingIndex, 3)

	def test_model_identifier(self) -> None:
		g = buildGesture("drv", {"k1"}, model="Focus40")
		self.assertEqual(g.identifiers, ["br(drv.focus40):k1", "br(drv):k1"])


class PortsTests(unittest.TestCase):
	def test_usb_id(self) -> None:
		self.assertEqual(normalizeUsbId(r"USB\VID_0904&PID_6101&REV_0100"), "VID_0904&PID_6101")
		self.assertEqual(normalizeUsbId(r"\\?\hid#vid_1c71&pid_c006#7&1"), "VID_1C71&PID_C006")
		self.assertEqual(normalizeUsbId("nada"), "")

	def test_bluetooth_address(self) -> None:
		self.assertEqual(parseBluetoothAddress("{00001101-0000}#0012F3A1B2C3_C00000000"), 0x0012F3A1B2C3)
		self.assertEqual(parseBluetoothAddress(r"BTHENUM\{X}\8&2A&0&001122334455_C00000000"), 0x001122334455)
		self.assertEqual(parseBluetoothAddress(""), 0)


class _FakeDriver(HardwareDriver):
	"""Protocolo de juguete: «C<n>» = celdas; «K<bits>» = teclas k0..k7."""

	name = "fake"
	description = "Fake"
	usbSerialIds = frozenset({"VID_1111&PID_2222", "VID_0403&PID_6001"})
	usbHidIds = frozenset({"VID_1111&PID_3333"})
	genericUsbIds = frozenset({"VID_0403&PID_6001"})
	bluetoothPrefixes = ("Fake BT",)
	gestureMap = {"k0": "braille_scrollBack", "k1": "kb:tab", "k2": "noExiste"}

	def _initConnection(self, match) -> None:
		self._write(b"?")

	def _handleData(self, data: bytes) -> None:
		if data[:1] == b"C":
			self.numCells = data[1]
		elif data[:1] == b"K":
			self._keysChanged({f"k{i}" for i in range(8) if data[1] & (1 << i)})

	def _writeCells(self, cells) -> None:
		self._write(b"D" + bytes(cells))


class FakeDriverTests(unittest.TestCase):
	def _connect(self):
		return connectSimulated(_FakeDriver, responder=lambda d: b"C\x14" if d == b"?" else None, usbId="VID_1111&PID_2222")

	def test_connect_and_display(self) -> None:
		drv, t = self._connect()
		self.assertEqual(drv.numCells, 20)
		drv.display([1, 2, 3])
		self.assertEqual(t.writes[-1], b"D" + bytes([1, 2, 3]) + bytes(17))

	def test_no_answer_raises(self) -> None:
		with self.assertRaises(base.DisplayNotFound):
			with mock.patch.object(_FakeDriver, "_waitFor", lambda self, p, t: p()):
				connectSimulated(_FakeDriver, responder=lambda d: None)

	def test_keys(self) -> None:
		drv, t = self._connect()
		t.feed(b"K\x01")
		t.feed(b"K\x03")
		t.feed(b"K\x02")
		t.feed(b"K\x00")
		self.assertEqual(gestureIds(drv), ["br(fake):k0+k1"])

	def test_disconnect(self) -> None:
		drv, t = self._connect()
		with mock.patch("tiresias.queue_handler.queueFunction") as q:
			t.fail()
		self.assertEqual(drv.numCells, 0)
		self.assertTrue(t.closed)
		self.assertTrue(q.called)
		drv.display([1, 2])  # No falla sin conexión.

	def test_detection_matches(self) -> None:
		devs = [
			DeviceInfo("serial", "COM5", usbId="VID_1111&PID_2222"),
			DeviceInfo("hid", r"\\?\hid#1", usbId="VID_1111&PID_3333"),
			DeviceInfo("serial", "COM7", bluetooth=True, bluetoothName="Fake BT 40"),
			DeviceInfo("serial", "COM8", bluetooth=True, bluetoothName="Otro"),
			DeviceInfo("serial", "COM9", usbId="VID_0403&PID_6001"),
		]
		ports = [m.port for m in _FakeDriver.getMatches(devs, allowGeneric=False)]
		self.assertEqual(ports, ["COM5", r"\\?\hid#1", "COM7"])
		self.assertIn("COM9", [m.port for m in _FakeDriver.getMatches(devs, allowGeneric=True)])
		self.assertEqual([m.port for m in _FakeDriver.getMatches(devs, bluetooth=False, allowGeneric=False)], ["COM5", r"\\?\hid#1"])

	def test_find_candidates_order_and_claim(self) -> None:
		class Other(_FakeDriver):
			name = "other"
			usbSerialIds = frozenset({"VID_1111&PID_2222"})
			bluetoothPrefixes = ("Otro",)

		devs = [
			DeviceInfo("serial", "COM8", bluetooth=True, bluetoothName="Otro"),
			DeviceInfo("serial", "COM5", usbId="VID_1111&PID_2222"),
		]
		cands = detect.findCandidates(devs, ["fake", "other"], classes={"fake": _FakeDriver, "other": Other})
		self.assertEqual([(n, m.port) for n, m in cands], [("fake", "COM5"), ("other", "COM8")])
		cands = detect.findCandidates(devs, ["fake", "other"], bluetooth=False, classes={"fake": _FakeDriver, "other": Other})
		self.assertEqual([(n, m.port) for n, m in cands], [("fake", "COM5")])

	def test_gesture_binding(self) -> None:
		from tiresias.global_commands import commands

		drv, t = self._connect()
		drv._bindGestures()
		inst = commands.__dict__.get("_instanceGestures") or {}
		self.assertEqual(inst.get("br(fake):k0"), "braille_scrollBack")
		self.assertNotIn("br(fake):k2", inst)
		self.assertEqual(drv._emulated.get("br(fake):k1"), "kb:tab")
		t.feed(b"K\x02")
		t.feed(b"K\x00")
		self.assertEqual(drv.lastGestures[-1].emulatedKey, "kb:tab")
		drv._unbindGestures()
		self.assertNotIn("br(fake):k0", commands.__dict__.get("_instanceGestures") or {})

	def test_emulated_key_decider(self) -> None:
		from tiresias.input import core as inputCore

		g = base.BrailleGesture("fake", ["k1"])
		g.emulatedKey = "kb:tab"
		with mock.patch.object(inputCore.manager, "findScript", return_value=None), mock.patch("tiresias.input.gestures.sendKey") as send:
			inputCore.manager.inputHelp = False
			self.assertFalse(base._decideBrailleGesture(gesture=g))
		send.assert_called_once_with("tab")
		g.emulatedKey = None
		with mock.patch.object(inputCore.manager, "findScript", return_value=None):
			self.assertTrue(base._decideBrailleGesture(gesture=g))


class DriverSettingsTests(unittest.TestCase):
	def test_settings_roundtrip(self) -> None:
		class WithSettings(_FakeDriver):
			name = "fakesettings"
			driverSettings = (base.DriverSetting("firmeza", "Firmeza", "choice", 1, choices=((0, "baja"), (1, "media"))), base.DriverSetting("modo", "Modo", "bool", False))

		self.assertEqual(WithSettings.getSetting("firmeza"), 1)
		self.assertFalse(WithSettings.getSetting("modo"))
		WithSettings.setSetting("modo", True)
		WithSettings.setSetting("firmeza", 0)
		self.assertTrue(WithSettings.getSetting("modo"))
		self.assertEqual(WithSettings.getSetting("firmeza"), 0)
		self.assertIsNone(base.getDriverSetting("otro", "x"))


class DriverScriptTests(unittest.TestCase):
	def test_driver_own_script(self) -> None:
		from tiresias import braille
		from tiresias.baseobject import script
		from tiresias.input import core as inputCore

		calls = []

		class WithScript(_FakeDriver):
			name = "fakescript"

			@script(description="Prueba", gestures=("br(fakescript):k3",))
			def script_hacerAlgo(self, gesture) -> None:
				calls.append(gesture)

		drv, t = connectSimulated(WithScript, responder=lambda d: b"C\x14" if d == b"?" else None)
		g = base.BrailleGesture("fakescript", ["k3"])
		old = braille.handler.display
		braille.handler.display = drv
		try:
			# El controlador activo está en la cadena de órdenes del gestor de entrada.
			func = inputCore._brailleDisplayScripts.getScript(g)
		finally:
			braille.handler.display = old
		self.assertIsNotNone(func)
		func(g)
		self.assertEqual(len(calls), 1)


# ------------------------------------------------------------- HID Braille
def _ns(**kw):
	return types.SimpleNamespace(**kw)


def _button(usage, dataIndex, link=0, linkUsage=0, page=USAGE_PAGE_BRAILLE, rng=None):
	if rng:
		r = _ns(UsageMin=rng[0], UsageMax=rng[1], DataIndexMin=rng[2], DataIndexMax=rng[3])
		return _ns(UsagePage=page, IsRange=1, Range=r, NotRange=None, LinkCollection=link, LinkUsage=linkUsage, LinkUsagePage=USAGE_PAGE_BRAILLE)
	return _ns(UsagePage=page, IsRange=0, NotRange=_ns(Usage=usage, DataIndex=dataIndex), Range=None, LinkCollection=link, LinkUsage=linkUsage, LinkUsagePage=USAGE_PAGE_BRAILLE)


def _value(usage, count, reportId=0, link=1, dataIndex=0):
	return _ns(UsagePage=USAGE_PAGE_BRAILLE, IsRange=0, NotRange=_ns(Usage=usage, DataIndex=dataIndex), ReportCount=count, ReportID=reportId, LinkCollection=link)


class _FakeHid(hwio.MemoryTransport):
	def __init__(self, layoutReports):
		super().__init__(kind="hid")
		self.reports = layoutReports

	def getData(self, report):
		return self.reports[report]

	def makeOutputReport(self, reportId, values):
		out = bytes([reportId])
		for _page, link, usage, data in values:
			out += bytes([link, usage]) + data
		return out


class HidBrailleTests(unittest.TestCase):
	def _layout(self):
		buttons = [
			_button(0x201, 0, rng=(0x201, 0x208, 0, 7)),  # puntos 1-8: índices 0-7
			_button(0x20A, 8),  # espacio izquierdo
			_button(0x21A, 9),
			_button(0x21B, 10),
			# Enrutamiento: 40 teclas con el mismo uso, en la colección «router set 1».
			_button(0x100, 0, link=3, linkUsage=0xFA, rng=(0x100, 0x100, 20, 59)),
			_button(0x100, 0, link=4, linkUsage=0xFB, rng=(0x100, 0x100, 60, 99)),
		]
		outputs = [_value(0x03, 40, reportId=2, link=1)]
		inputs = [_value(0x05, 1, dataIndex=100)]
		return HidLayout(buttons, outputs, inputs)

	def test_layout(self) -> None:
		lay = self._layout()
		self.assertEqual(lay.totalCells, 40)
		self.assertEqual(lay.keys[3], "dot4")
		self.assertEqual(lay.keys[8], "space")
		self.assertEqual(lay.keys[20], ("routing", 0))
		self.assertEqual(lay.keys[59], ("routing", 39))
		self.assertEqual(lay.keys[61], ("routing2", 1))
		self.assertEqual(lay.numCellsIndex, 100)

	def test_six_dot_cells(self) -> None:
		lay = HidLayout([], [_value(0x04, 20)], [])
		self.assertEqual(lay.totalCells, 20)

	def test_multi_row(self) -> None:
		lay = HidLayout([], [_value(0x03, 20, link=1), _value(0x03, 20, link=2)], [])
		self.assertEqual((lay.numRows, lay.totalCells), (2, 40))

	def _driver(self):
		reports = {
			b"dots": [(0, 1), (1, 1), (8, 1)],
			b"none": [],
			b"route": [(25, 1)],
			b"route2": [(25, 1), (30, 1)],
			b"pan": [(9, 1)],
			b"cells": [(100, 38)],
		}
		t = _FakeHid(reports)
		drv = HidBrailleDriver(transport=t)
		drv._setLayout(self._layout(), "Linea Prueba")
		drv.lastGestures = []
		return drv, t

	def test_keys(self) -> None:
		drv, t = self._driver()
		t.feed(b"dots")
		t.feed(b"none")
		g = drv.lastGestures[-1]
		self.assertEqual(g.identifiers[-1], "br(hidbraille):dot1+dot2+space")
		self.assertEqual((g.dots, g.space), (3, True))
		t.feed(b"route")
		t.feed(b"none")
		self.assertEqual(drv.lastGestures[-1].routingIndex, 5)
		t.feed(b"route2")
		t.feed(b"none")
		g = drv.lastGestures[-1]
		self.assertEqual((g.keys, g.routingIndexes), (["multiRouting"], [5, 10]))
		self.assertEqual(g.identifiers[0], "br(hidbraille.lineaprueba):multirouting")

	def test_number_of_cells(self) -> None:
		drv, t = self._driver()
		t.feed(b"cells")
		self.assertEqual(drv.numCells, 38)

	def test_output(self) -> None:
		drv, t = self._driver()
		drv.display([0x01, 0xFF])
		self.assertEqual(t.writes[-1], bytes([2, 1, 3, 1, 0xFF]) + bytes(38))

	def test_matches_usage_page(self) -> None:
		devs = [
			DeviceInfo("hid", "a", usbId="VID_1&PID_2", usagePage=0x41, usage=1),
			DeviceInfo("hid", "b", usbId="VID_1&PID_3", usagePage=0x01),
			DeviceInfo("hid", "c", usagePage=0x41, usage=1, bluetooth=True, product="BT"),
		]
		self.assertEqual([m.port for m in HidBrailleDriver.getMatches(devs)], ["a", "c"])
		self.assertEqual([m.port for m in HidBrailleDriver.getMatches(devs, usb=False)], ["c"])

	def test_compat_module(self) -> None:
		from tiresias.braille import hid_braille

		self.assertIs(hid_braille.BrailleDisplayDriver, HidBrailleDriver)


class RegistryTests(unittest.TestCase):
	def test_display_list_has_auto_and_hid(self) -> None:
		from tiresias import braille

		names = [n for n, _d in braille.getDisplayList()]
		self.assertEqual(names[:3], ["noBraille", "viewer", "auto"])
		self.assertIn("hidBraille", names)

	def test_auto_driver_class(self) -> None:
		from tiresias import braille

		cls = braille.getDriverClass("auto")
		self.assertEqual(cls.name, "auto")


if __name__ == "__main__":
	unittest.main()
