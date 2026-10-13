"""Pruebas del controlador HumanWare BrailleNote (modo terminal) con datos simulados."""

from __future__ import annotations

import re
import unittest
from unittest import mock

import braille_sim  # noqa: F401
from braille_sim import connectSimulated, gestureIds

from tiresias.braille.drivers import brailleNote as mod
from tiresias.braille.drivers.base import DisplayNotFound
from tiresias.braille.drivers.brailleNote import BrailleNoteDriver
from tiresias.braille.drivers.ports import DeviceInfo

DESCRIBE = b"\x1b?"


def responder(cells=32, split=False):
	def respond(data):
		if data == DESCRIBE:
			reply = bytes((0x86, 0x00, cells))
			return [bytes((b,)) for b in reply] if split else reply
		return None

	return respond


class ConnectionTests(unittest.TestCase):
	def test_describe_apex_usb(self) -> None:
		drv, t = connectSimulated(BrailleNoteDriver, responder(32), usbId="VID_1C71&PID_C004")
		self.assertEqual(t.writes[0], DESCRIBE)
		self.assertEqual(drv.numCells, 32)
		self.assertEqual(drv.model, "Apex")
		self.assertEqual(drv.deviceName, "BrailleNote Apex de 32 celdas")
		_match, baud, kwargs = t.opened[0]
		self.assertEqual(baud, 38400)
		self.assertEqual(kwargs.get("parity"), "N")

	def test_describe_split_bluetooth(self) -> None:
		drv, _t = connectSimulated(BrailleNoteDriver, responder(18, split=True), bluetooth=True, name="BrailleNote mPower")
		self.assertEqual(drv.numCells, 18)
		self.assertEqual(drv.model, "BrailleNote")
		self.assertEqual(drv.deviceName, "BrailleNote de 18 celdas")

	def test_no_answer(self) -> None:
		with mock.patch.object(mod, "DESCRIBE_TIMEOUT", 0.01):
			with self.assertRaises(DisplayNotFound):
				connectSimulated(BrailleNoteDriver, lambda data: None)

	def test_not_a_braillenote(self) -> None:
		with mock.patch.object(mod, "DESCRIBE_TIMEOUT", 0.01):
			with self.assertRaises(DisplayNotFound):
				connectSimulated(BrailleNoteDriver, lambda data: b"\x00\x13\x55")


class ProtocolTests(unittest.TestCase):
	def setUp(self) -> None:
		self.drv, self.t = connectSimulated(BrailleNoteDriver, responder(32), usbId="VID_1C71&PID_C004")

	def test_display_escapes_esc(self) -> None:
		cells = [0x1B, 0x01, 0xFF, 0x1B] + [0] * 28
		self.drv.display(cells)
		self.assertEqual(self.t.writes[-1], b"\x1bB\x1b\x1b\x01\xff\x1b\x1b" + bytes(28))

	def test_display_pads(self) -> None:
		self.drv.display([0x3F])
		self.assertEqual(self.t.writes[-1], b"\x1bB\x3f" + bytes(31))

	def test_dots(self) -> None:
		self.t.feed(b"\x80\x0b")
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.dots, 0x0B)
		self.assertFalse(g.space)
		self.assertEqual(gestureIds(self.drv), ["br(braillenote):d1+d2+d4"])

	def test_dots_with_space(self) -> None:
		self.t.feed(b"\x81\x01")
		g = self.drv.lastGestures[-1]
		self.assertEqual((g.dots, g.space), (1, True))
		self.assertEqual(gestureIds(self.drv), ["br(braillenote):d1+space"])
		self.t.feed(b"\x81\x00")
		self.assertEqual(gestureIds(self.drv), ["br(braillenote):space"])

	def test_backspace_and_enter(self) -> None:
		self.t.feed(b"\x82\x00\x83\x00\x83\x80")
		self.assertEqual(gestureIds(self.drv), ["br(braillenote):d7+space", "br(braillenote):d8+space", "br(braillenote):d8+space"])

	def test_thumb_keys(self) -> None:
		self.t.feed(b"\x84\x02")
		self.t.feed(b"\x84\x09")
		self.assertEqual(gestureIds(self.drv), ["br(braillenote):tback", "br(braillenote):tnext+tprevious"])

	def test_routing(self) -> None:
		self.t.feed(b"\x85\x07")
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.routingIndex, 7)
		self.assertEqual(gestureIds(self.drv), ["br(braillenote):routing"])

	def test_wheel(self) -> None:
		self.t.feed(b"\x8b\x00\x8b\x02\x8b\x06\x8b\x09")
		self.assertEqual(gestureIds(self.drv), ["br(braillenote):wcounterclockwise", "br(braillenote):wup", "br(braillenote):wcenter"])

	def test_byte_by_byte_with_garbage(self) -> None:
		stream = b"\x00\x41" + b"\x84\x04" + b"\x85\x1f" + b"\x8d\x08\x8c\x54" + b"\x81\x24"
		for b in stream:
			self.t.feed(bytes((b,)))
		self.assertEqual(
			gestureIds(self.drv, clear=False),
			["br(braillenote):tadvance", "br(braillenote):routing", "br(braillenote):read+t", "br(braillenote):d3+d6+space"],
		)
		self.assertEqual(self.drv.lastGestures[1].routingIndex, 31)

	def test_status_updates_cells(self) -> None:
		self.t.feed(b"\x86\x00\x12")
		self.assertEqual(self.drv.numCells, 18)

	def test_qt_keys(self) -> None:
		# Lectura + T: gesto propio, sin tecla emulada.
		self.t.feed(b"\x8d\x08\x8c\x54")
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.identifiers[-1], "br(braillenote):read+t")
		self.assertIsNone(g.emulatedKey)
		# Mayúsculas + A: se emula en el PC.
		self.t.feed(b"\x8d\x02\x8c\x41")
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.identifiers[-1], "br(braillenote):a+shift")
		self.assertEqual(g.emulatedKey, "kb:shift+a")
		# Letra sin modificadores.
		self.t.feed(b"\x8d\x00\x8c\x42")
		self.assertEqual(self.drv.lastGestures[-1].emulatedKey, "kb:b")
		# Control + flecha arriba.
		self.t.feed(b"\x8d\x04\x8c\x26")
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.identifiers[-1], "br(braillenote):control+uparrow")
		self.assertEqual(g.emulatedKey, "kb:control+upArrow")
		# Función + flecha: solo por el mapa de gestos.
		self.t.feed(b"\x8d\x01\x8c\x26")
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.identifiers[-1], "br(braillenote):function+uparrow")
		self.assertIsNone(g.emulatedKey)
		# Tecla suelta con la etiqueta 8C.
		self.t.feed(b"\x8c\x0d")
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.identifiers[-1], "br(braillenote):enter")
		self.assertEqual(g.emulatedKey, "kb:enter")
		# QT: la barra espaciadora se emula como tecla, no como escritura braille.
		self.t.feed(b"\x8c\x20")
		self.assertEqual(self.drv.lastGestures[-1].emulatedKey, "kb:space")
		# Los puntos no llevan tecla emulada.
		self.t.feed(b"\x81\x01")
		self.assertIsNone(self.drv.lastGestures[-1].emulatedKey)

	def test_model_identifier(self) -> None:
		self.t.feed(b"\x84\x01")
		self.assertEqual(self.drv.lastGestures[-1].identifiers, ["br(braillenote.apex):tprevious", "br(braillenote):tprevious"])


class DetectionTests(unittest.TestCase):
	def test_usb_serial(self) -> None:
		devs = [
			DeviceInfo("serial", "COM3", usbId="VID_1C71&PID_C004"),
			DeviceInfo("serial", "COM4", usbId="VID_1C71&PID_C005"),
			DeviceInfo("hid", "h1", usbId="VID_1C71&PID_C004"),
		]
		self.assertEqual([(m.type, m.port, m.bluetooth) for m in BrailleNoteDriver.getMatches(devs)], [("serial", "COM3", False)])

	def test_bluetooth(self) -> None:
		devs = [
			DeviceInfo("serial", "COM8", bluetooth=True, bluetoothName="Braillenote BT 32"),
			DeviceInfo("serial", "COM9", bluetooth=True, bluetoothName="BrailleNote Apex", bluetoothAddress=0x0011223344),
			DeviceInfo("serial", "COM10", bluetooth=True, bluetoothName="Apex", bluetoothAddress=0x0025EC000100),
			DeviceInfo("serial", "COM11", bluetooth=True, bluetoothName="BrailleNote Touch 32"),
			DeviceInfo("serial", "COM12", bluetooth=True, bluetoothName="Otro", bluetoothAddress=0x0025EC020000),
		]
		self.assertEqual([m.port for m in BrailleNoteDriver.getMatches(devs)], ["COM8", "COM9", "COM10"])
		self.assertEqual(BrailleNoteDriver.getMatches(devs, bluetooth=False), [])

	def test_apex_bluetooth_model(self) -> None:
		dev = DeviceInfo("serial", "COM10", bluetooth=True, bluetoothName="Apex", bluetoothAddress=0x0025EC000100)
		match = BrailleNoteDriver.matchDevice(dev)
		from tiresias.braille.drivers import hwio

		transport = hwio.MemoryTransport(kind="serial", responder=responder(18))

		def fakeOpen(self, m, baudrate=None, **kwargs):
			transport.onReceive = self._onReceive
			return transport

		with mock.patch.object(BrailleNoteDriver, "_open", fakeOpen):
			drv = BrailleNoteDriver(match=match, configName="brailleNote")
		self.assertEqual(drv.model, "Apex")
		self.assertEqual(drv.numCells, 18)

	def test_no_generic_ids(self) -> None:
		self.assertEqual(BrailleNoteDriver.genericUsbIds, frozenset())


class GestureMapTests(unittest.TestCase):
	def test_map_values_and_keys(self) -> None:
		known = {f"d{i}" for i in range(1, 9)} | {"space", "routing"}
		known |= {name for _bit, name in mod.THUMB_KEYS}
		known |= set(mod.WHEEL_KEYS)
		known |= {name for _bit, name in mod.QT_MODIFIERS}
		known |= set(mod.QT_KEYS.values())
		ident = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
		for keys, target in BrailleNoteDriver.gestureMap.items():
			self.assertTrue(target.startswith("kb:") or ident.match(target), target)
			parts = keys.split("+")
			for k in parts:
				self.assertIn(k, known, keys)
			self.assertFalse(all(p in BrailleNoteDriver.dotKeys for p in parts), keys)
		for k in BrailleNoteDriver.keyDescriptions:
			self.assertIn(k, known)
		for k in BrailleNoteDriver.keyOrder:
			self.assertIn(k, known)

	def test_effective_map(self) -> None:
		m = BrailleNoteDriver.effectiveGestureMap()
		self.assertEqual(m["br(braillenote):tback"], "braille_scrollBack")
		self.assertEqual(m["br(braillenote):d1+d3+space"], "kb:shift+tab")
		self.assertEqual(m["br(braillenote):read+t"], "kb:control+home")


if __name__ == "__main__":
	unittest.main()
