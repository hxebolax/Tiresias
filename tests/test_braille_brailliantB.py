"""Pruebas del controlador HumanWare Brailliant (protocolos serie y HID) con datos simulados."""

from __future__ import annotations

import re
import unittest
from unittest import mock

import braille_sim  # noqa: F401
from braille_sim import connectSimulated, gestureIds

from tiresias.braille.drivers import brailliantB as mod
from tiresias.braille.drivers import detect, hwio
from tiresias.braille.drivers.base import DisplayNotFound
from tiresias.braille.drivers.brailliantB import BrailliantBDriver
from tiresias.braille.drivers.hidBraille import HidBrailleDriver
from tiresias.braille.drivers.ports import DeviceInfo

IDENTIFY = b"\x1b\x00\x00"


def serialResponder(cells=40, allowed=True, split=False):
	"""Línea serie simulada: contesta a la petición de identificación."""

	def respond(data):
		if data == IDENTIFY:
			reply = bytes((0x1B, 0x01, 0x03, 0 if allowed else 1, 0x01, cells))
			return [bytes((b,)) for b in reply] if split else reply
		return None

	return respond


def capsReport(cells):
	report = bytearray(32)
	report[0] = mod.REPORT_CAPABILITIES
	report[mod.CAPS_CELLS_OFFSET] = cells
	return bytes(report)


def keyDown(code):
	return bytes((0x1B, 0x05, 0x01, code))


def keyUp(code):
	return bytes((0x1B, 0x06, 0x01, code))


def connectHid(usbId="VID_1C71&PID_C006", cells=40, outputSize=44, feature=True, usagePage=None):
	patches = []
	if feature:
		patches.append(mock.patch.object(hwio.MemoryTransport, "getFeature", lambda self, rid: capsReport(cells) if rid == 1 else b"", create=True))
	if usagePage is not None:
		patches.append(mock.patch.object(hwio.MemoryTransport, "usagePage", usagePage, create=True))
	for p in patches:
		p.start()
	try:
		return connectSimulated(BrailliantBDriver, matchType="hid", port="\\\\?\\hid#vid_1c71", usbId=usbId, outputSize=outputSize)
	finally:
		for p in patches:
			p.stop()


class SerialConnectionTests(unittest.TestCase):
	def test_identify_usb(self) -> None:
		drv, t = connectSimulated(BrailliantBDriver, serialResponder(40), usbId="VID_1C71&PID_C005")
		self.assertEqual(t.writes[0], IDENTIFY)
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(drv.model, "BrailliantBI40")
		self.assertEqual(drv.deviceName, "Brailliant BI 40")
		match, baud, kwargs = t.opened[0]
		self.assertEqual(baud, 115200)
		self.assertEqual(kwargs.get("parity"), "E")

	def test_identify_split_reply(self) -> None:
		drv, _t = connectSimulated(BrailliantBDriver, serialResponder(80, split=True), usbId="VID_1C71&PID_C005")
		self.assertEqual(drv.numCells, 80)
		self.assertEqual(drv.model, "BrailliantB80")

	def test_bi14_by_usb_id(self) -> None:
		drv, _t = connectSimulated(BrailliantBDriver, serialResponder(14), usbId="VID_1C71&PID_C021")
		self.assertEqual(drv.model, "BrailliantBI14")

	def test_bluetooth_brailleNote_touch(self) -> None:
		drv, _t = connectSimulated(BrailliantBDriver, serialResponder(32), bluetooth=True, name="BrailleNote Touch 32")
		self.assertEqual(drv.numCells, 32)
		self.assertEqual(drv.model, "BrailleNoteTouch")
		self.assertIn("Bluetooth", drv.displayName)

	def test_communication_not_allowed(self) -> None:
		with self.assertRaises(DisplayNotFound):
			connectSimulated(BrailliantBDriver, serialResponder(40, allowed=False), usbId="VID_1C71&PID_C005")

	def test_no_answer(self) -> None:
		with mock.patch.object(mod, "INIT_TIMEOUT", 0.01), mock.patch.object(mod, "INIT_RETRY_DELAY", 0):
			with self.assertRaises(DisplayNotFound):
				connectSimulated(BrailliantBDriver, lambda data: None, usbId="VID_1C71&PID_C005")


class SerialProtocolTests(unittest.TestCase):
	def setUp(self) -> None:
		self.drv, self.t = connectSimulated(BrailliantBDriver, serialResponder(40), usbId="VID_1C71&PID_C005")

	def test_display(self) -> None:
		cells = [0x01, 0x1B, 0xFF] + [0] * 37
		self.drv.display(cells)
		self.assertEqual(self.t.writes[-1], b"\x1b\x02\x28" + bytes(cells))

	def test_display_pads(self) -> None:
		self.drv.display([0x07])
		self.assertEqual(self.t.writes[-1], b"\x1b\x02\x28\x07" + bytes(39))

	def test_dots_and_space(self) -> None:
		self.t.feed(keyDown(10) + keyDown(2) + keyDown(4) + keyUp(2) + keyUp(4) + keyUp(10))
		self.assertEqual(gestureIds(self.drv, clear=False), ["br(brailliantb):dot1+dot3+space"])
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.dots, 0b101)
		self.assertTrue(g.space)

	def test_byte_by_byte(self) -> None:
		stream = b"\x00\x42" + keyDown(17) + keyDown(20) + keyUp(17) + keyUp(20)
		for b in stream:
			self.t.feed(bytes((b,)))
		self.assertEqual(gestureIds(self.drv), ["br(brailliantb):down+up"])

	def test_routing(self) -> None:
		self.t.feed(keyDown(80 + 5) + keyUp(80 + 5))
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.routingIndex, 5)
		self.assertEqual(gestureIds(self.drv), ["br(brailliantb):routing"])
		self.t.feed(keyDown(80 + 2) + keyDown(80 + 9) + keyUp(80 + 2) + keyUp(80 + 9))
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.routingIndexes, [2, 9])
		self.assertEqual(gestureIds(self.drv), ["br(brailliantb):multirouting"])

	def test_command_keys(self) -> None:
		self.t.feed(keyDown(11) + keyDown(80) + keyUp(80) + keyUp(11))
		self.assertEqual(gestureIds(self.drv), ["br(brailliantb):c1+routing"])
		self.t.feed(keyDown(25) + keyUp(25))
		self.assertEqual(gestureIds(self.drv), ["br(brailliantb):stickaction"])
		self.assertEqual(self.drv.lastGestures, [])

	def test_model_identifier(self) -> None:
		self.t.feed(keyDown(18) + keyUp(18))
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.identifiers, ["br(brailliantb.brailliantbi40):left", "br(brailliantb):left"])


class HidTests(unittest.TestCase):
	def test_connect_with_feature(self) -> None:
		drv, t = connectHid(cells=32, outputSize=36)
		self.assertEqual(drv.numCells, 32)
		self.assertEqual(drv.model, "BrailliantBI32")
		self.assertEqual(t.opened[0][2].get("exclusive"), False)

	def test_connect_without_feature_uses_report_size(self) -> None:
		drv, _t = connectHid(usbId="VID_1C71&PID_C131", outputSize=44, feature=False)
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(drv.model, "BrailliantBI40X")
		self.assertEqual(drv.deviceName, "Brailliant BI 40X")

	def test_feature_zero_falls_back(self) -> None:
		drv, _t = connectHid(usbId="VID_1C71&PID_C101", cells=0, outputSize=24)
		self.assertEqual(drv.numCells, 20)
		self.assertEqual(drv.model, "Chameleon20")

	def test_reported_cells_clamped_to_report(self) -> None:
		drv, _t = connectHid(usbId="VID_1C71&PID_C111", cells=80, outputSize=44)
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(drv.model, "MantisQ40")

	def test_standard_interface_rejected_for_dual_models(self) -> None:
		with self.assertRaises(DisplayNotFound):
			connectHid(usbId="VID_1C71&PID_C141", usagePage=0x41)

	def test_display(self) -> None:
		drv, t = connectHid(cells=40, outputSize=44)
		cells = list(range(40))
		drv.display(cells)
		self.assertEqual(t.writes[-1], b"\x05\x01\x00\x28" + bytes(cells))

	def test_display_padded_to_report(self) -> None:
		drv, t = connectHid(usbId="VID_1C71&PID_C022", cells=14, outputSize=24)
		self.assertEqual(drv.model, "BrailliantBI14")
		drv.display([0xFF] * 14)
		self.assertEqual(t.writes[-1], b"\x05\x01\x00\x0e" + b"\xff" * 14 + bytes(6))

	def test_keys(self) -> None:
		drv, t = connectHid()
		t.feed(b"\x04\x0b" + bytes(10))
		t.feed(b"\x04\x0b\x53" + bytes(9))
		t.feed(b"\x04" + bytes(11))
		g = drv.lastGestures[-1]
		self.assertEqual(g.routingIndex, 3)
		self.assertEqual(gestureIds(drv), ["br(brailliantb):c1+routing"])
		t.feed(b"\x04\x0a\x02\x07")
		t.feed(b"\x04\x0a")
		t.feed(b"\x04")
		g = drv.lastGestures[-1]
		self.assertEqual(g.dots, 0b100001)
		self.assertTrue(g.space)
		self.assertEqual(gestureIds(drv), ["br(brailliantb):dot1+dot6+space"])

	def test_power_off_and_unknown_reports(self) -> None:
		drv, t = connectHid()
		t.feed(b"\x07\x00")
		t.feed(b"\x09\x01\x02")
		t.feed(b"")
		self.assertEqual(gestureIds(drv), [])


class DetectionTests(unittest.TestCase):
	def test_usb_hid_and_serial(self) -> None:
		devs = [
			DeviceInfo("hid", "h1", usbId="VID_1C71&PID_C006", usagePage=0xFF00),
			DeviceInfo("hid", "h2", usbId="VID_1C71&PID_C006", usagePage=0x01, usage=0x06),
			DeviceInfo("serial", "COM4", usbId="VID_1C71&PID_C005"),
			DeviceInfo("serial", "COM5", usbId="VID_0403&PID_6001"),
			DeviceInfo("hid", "h3", usbId="VID_1C71&PID_C004"),
		]
		matches = BrailliantBDriver.getMatches(devs)
		self.assertEqual([(m.type, m.port) for m in matches], [("hid", "h1"), ("serial", "COM4")])

	def test_dual_interface_models(self) -> None:
		devs = [
			DeviceInfo("hid", "own", usbId="VID_1C71&PID_C131", usagePage=0x93),
			DeviceInfo("hid", "std", usbId="VID_1C71&PID_C131", usagePage=0x41, usage=0x01),
		]
		self.assertEqual([m.port for m in BrailliantBDriver.getMatches(devs)], ["own"])
		classes = {"brailliantB": BrailliantBDriver, "hidBraille": HidBrailleDriver}
		found = detect.findCandidates(devs, ["brailliantB", "hidBraille"], classes=classes)
		self.assertEqual([(n, m.port) for n, m in found], [("brailliantB", "own"), ("hidBraille", "std")])

	def test_bluetooth_serial_names(self) -> None:
		names = {
			"Brailliant BI 40": True,
			"Brailliant 80": True,
			"BrailleNote Touch 32": True,
			"HumanWare BrailleNote Touch": True,
			"HWG Brailliant": False,
			"Braillenote Apex": False,
		}
		for name, ok in names.items():
			dev = DeviceInfo("serial", "COM7", bluetooth=True, bluetoothName=name)
			self.assertEqual(bool(BrailliantBDriver.getMatches([dev])), ok, name)
		dev = DeviceInfo("serial", "COM7", bluetooth=True, bluetoothName="Brailliant BI 32")
		self.assertEqual(BrailliantBDriver.getMatches([dev], bluetooth=False), [])

	def test_bluetooth_hid(self) -> None:
		devs = [
			DeviceInfo("hid", "b1", bluetooth=True, bluetoothName="APH Mantis Q40", product="APH Mantis Q40", manufacturer="Humanware", usagePage=0x93),
			DeviceInfo("hid", "b2", bluetooth=True, bluetoothName="APH Mantis Q40", product="APH Mantis Q40", manufacturer="Humanware", usagePage=0x41),
			DeviceInfo("hid", "b3", bluetooth=True, bluetoothName="Brailliant HID", product="Brailliant HID", manufacturer="HumanWare", usagePage=0xFF00),
			DeviceInfo("hid", "b4", bluetooth=True, bluetoothName="NLS eReader", product="NLS eReader", manufacturer="Humanware"),
			DeviceInfo("hid", "b5", bluetooth=True, bluetoothName="Brailliant HID", product="Brailliant HID", manufacturer="Otro"),
		]
		matches = BrailliantBDriver.getMatches(devs)
		self.assertEqual([m.port for m in matches], ["b1", "b3", "b4"])
		self.assertTrue(all(m.bluetooth for m in matches))

	def test_bluetooth_hid_model_from_product(self) -> None:
		dev = DeviceInfo("hid", "b1", bluetooth=True, bluetoothName="APH Chameleon 20", product="APH Chameleon 20", manufacturer="Humanware", usagePage=0x93)
		match = BrailliantBDriver.matchDevice(dev)
		with mock.patch.object(hwio.MemoryTransport, "getFeature", lambda self, rid: capsReport(20), create=True):
			transport = hwio.MemoryTransport(kind="hid", outputSize=24)

			def fakeOpen(self, m, baudrate=None, **kwargs):
				transport.onReceive = self._onReceive
				return transport

			with mock.patch.object(BrailliantBDriver, "_open", fakeOpen):
				drv = BrailliantBDriver(match=match, configName="brailliantB")
		self.assertEqual(drv.numCells, 20)
		self.assertEqual(drv.model, "Chameleon20")

	def test_generic_ids_not_claimed(self) -> None:
		self.assertEqual(BrailliantBDriver.genericUsbIds, frozenset())
		self.assertTrue(BrailliantBDriver.usbHidIds.isdisjoint(BrailliantBDriver.usbSerialIds))


class GestureMapTests(unittest.TestCase):
	def test_map_values_and_keys(self) -> None:
		known = set(mod.KEY_CODES.values()) | {"routing", "multiRouting"}
		ident = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
		for keys, target in BrailliantBDriver.gestureMap.items():
			self.assertTrue(target.startswith("kb:") or ident.match(target), target)
			for k in keys.split("+"):
				self.assertIn(k, known, keys)
			parts = keys.split("+")
			# Ninguna orden en combinaciones solo de puntos.
			self.assertFalse(all(p.startswith("dot") for p in parts), keys)
		for k in BrailliantBDriver.keyDescriptions:
			self.assertIn(k, known)
		for k in BrailliantBDriver.keyOrder:
			self.assertIn(k, known)

	def test_effective_map(self) -> None:
		m = BrailliantBDriver.effectiveGestureMap()
		self.assertEqual(m["br(brailliantb):left"], "braille_scrollBack")
		self.assertEqual(m["br(brailliantb):dot1+dot3+space"], "kb:shift+tab")


if __name__ == "__main__":
	unittest.main()
