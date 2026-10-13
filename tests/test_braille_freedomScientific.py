"""Pruebas del controlador de las líneas Freedom Scientific (Focus y PAC Mate)
con una línea simulada."""

from __future__ import annotations

import time
import unittest
from unittest import mock

import braille_sim  # noqa: F401
from braille_sim import connectSimulated, gestureIds

from tiresias.braille.drivers import base
from tiresias.braille.drivers import freedomScientific as fs
from tiresias.braille.drivers.freedomScientific import FreedomScientificDriver
from tiresias.braille.drivers.ports import DeviceInfo

QUERY = b"\x00\x00\x00\x00"
ACK = b"\x01\x00\x00\x00"
CONFIG_EXT = b"\x0f\x02\x00\x00"


def infoPacket(model: str, firmware: str = "3.4", manufacturer: str = "Freedom Scientific") -> bytes:
	payload = manufacturer.encode().ljust(24, b"\x00") + model.encode().ljust(16, b"\x00") + firmware.encode().ljust(8, b"\x00")
	head = bytes((0x80, len(payload), 0, 0)) + payload
	return head + bytes(((-sum(head)) & 0xFF,))


def keyPacket(bits: int) -> bytes:
	return bytes((0x03, bits & 0xFF, (bits >> 8) & 0xFF, (bits >> 16) & 0xFF))


def extKeyPacket(bits: int) -> bytes:
	head = bytes((0x82, 1, 0, 0, (bits << 4) & 0xF0))
	return head + bytes(((-sum(head)) & 0xFF,))


def buttonPacket(index: int, press: bool, top: bool = False) -> bytes:
	return bytes((0x04, index, 1 if press else 0, 1 if top else 0))


def wheelPacket(wheel: int, count: int) -> bytes:
	return bytes((0x05, (wheel << 3) | count, 0, 0))


def bit(name: str) -> int:
	return next(1 << b for b, n in fs.KEY_BITS.items() if n == name)


class _Display:
	"""Línea simulada: contesta a la identificación y confirma las escrituras."""

	def __init__(self, model="Focus 40", firmware="3.4", ack=True):
		self.model = model
		self.firmware = firmware
		self.ack = ack

	def __call__(self, data: bytes):
		if data == QUERY:
			return infoPacket(self.model, self.firmware)
		if data[:1] in (b"\x81", b"\x0f") and self.ack:
			return ACK
		return None


def connect(model="Focus 40", firmware="3.4", ack=True, matchType="serial", **kw):
	return connectSimulated(FreedomScientificDriver, _Display(model, firmware, ack), matchType=matchType, **kw)


def writePacket(n: int, data: bytes) -> bytes:
	head = bytes((0x81, n, 0, 0)) + data
	return head + bytes(((-sum(head)) & 0xFF,))


class ConnectionTests(unittest.TestCase):
	def test_focus40_serial(self) -> None:
		drv, t = connect()
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(drv.model, "Focus40")
		self.assertEqual(drv.deviceName, "Freedom Scientific Focus 40")
		self.assertEqual(drv.firmware, "3.4")
		self.assertEqual(t.writes[0], QUERY)
		# Firmware 3 o posterior: se activan las teclas extendidas.
		self.assertEqual(t.writes[1], CONFIG_EXT)
		match, baud, kwargs = t.opened[0]
		self.assertEqual(baud, 57600)
		self.assertEqual(kwargs.get("parity"), "N")

	def test_old_firmware_no_extended_keys(self) -> None:
		drv, t = connect(firmware="2.1")
		self.assertEqual(t.writes, [QUERY])

	def test_usb_bulk_endpoints(self) -> None:
		drv, t = connect(model="Focus 14", matchType="bulk", port=r"\\?\usb#vid_0f4e&pid_0114", usbId="VID_0F4E&PID_0114")
		self.assertEqual(drv.numCells, 14)
		self.assertEqual(t.opened[0][2], {"epIn": 1, "epOut": 0, "readSize": 56})

	def test_models_and_cells(self) -> None:
		self.assertEqual(fs.cellsForModel("Focus 80"), 80)
		self.assertEqual(fs.cellsForModel("Focus 84"), 84)
		self.assertEqual(fs.cellsForModel("pm display 20"), 20)
		self.assertEqual(fs.cellsForModel("Focus 40 Blue"), 40)
		self.assertEqual(fs.cellsForModel("Otra cosa 40"), 0)

	def test_pac_mate(self) -> None:
		drv, t = connect(model="pm display 40", firmware="1.0")
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(drv.model, "pmdisplay40")
		self.assertIn("PAC Mate", drv.deviceName)
		self.assertEqual(t.writes, [QUERY])

	def test_first_generation(self) -> None:
		drv, t = connect(model="Focus 44", firmware="1.2")
		self.assertEqual(drv.numCells, 44)
		self.assertIn("primera generación", drv.deviceName)

	def test_unknown_model_raises(self) -> None:
		with mock.patch.object(FreedomScientificDriver, "_waitFor", lambda self, p, t: p()):
			with self.assertRaises(base.DisplayNotFound):
				connect(model="Desconocido")

	def test_no_answer_raises(self) -> None:
		with mock.patch.object(FreedomScientificDriver, "_waitFor", lambda self, p, t: p()):
			with self.assertRaises(base.DisplayNotFound):
				connectSimulated(FreedomScientificDriver, lambda d: None)

	def test_info_split_in_chunks(self) -> None:
		def responder(data):
			if data == QUERY:
				return [bytes((b,)) for b in infoPacket("Focus 80")]
			return None

		drv, t = connectSimulated(FreedomScientificDriver, responder)
		self.assertEqual(drv.numCells, 80)

	def test_bad_checksum_ignored(self) -> None:
		def responder(data):
			if data == QUERY:
				bad = bytearray(infoPacket("Focus 80"))
				bad[-1] ^= 0xFF
				return [bytes(bad), infoPacket("Focus 14")]
			return None

		drv, t = connectSimulated(FreedomScientificDriver, responder)
		self.assertEqual(drv.numCells, 14)


class OutputTests(unittest.TestCase):
	def test_write_cells(self) -> None:
		drv, t = connect(model="Focus 14")
		drv.display([0x01, 0xFF, 0x80])
		data = bytes([0x01, 0xFF, 0x80]) + bytes(11)
		self.assertEqual(t.writes[-1], writePacket(14, data))
		self.assertEqual(sum(t.writes[-1]) & 0xFF, 0)
		# La línea ha confirmado (ACK): la siguiente escritura sale enseguida.
		drv.display([0x3F])
		self.assertEqual(t.writes[-1], writePacket(14, bytes([0x3F]) + bytes(13)))

	def test_first_generation_translation(self) -> None:
		drv, t = connect(model="Focus 44", firmware="1.2")
		# Punto 4 -> 0x10, punto 7 -> 0x08, puntos 1-8 -> 0xFF, punto 6 -> 0x40.
		drv.display([0x08, 0x40, 0xFF, 0x20])
		self.assertEqual(t.writes[-1], writePacket(44, bytes([0x10, 0x08, 0xFF, 0x40]) + bytes(40)))
		self.assertEqual(fs.FIRST_GENERATION_TABLE[0x10], 0x20)

	def test_waits_for_ack(self) -> None:
		drv, t = connect(model="Focus 14", ack=False)
		drv.display([1])
		count = len(t.writes)
		drv.display([2])
		drv.display([3])
		self.assertEqual(len(t.writes), count)  # Pendiente hasta el ACK.
		t.feed(ACK)
		self.assertEqual(len(t.writes), count + 1)
		self.assertEqual(t.writes[-1], writePacket(14, bytes([3]) + bytes(13)))
		t.feed(ACK)
		self.assertEqual(len(t.writes), count + 1)  # Nada más pendiente.
		drv.terminate()

	def test_nak_counts_as_ack(self) -> None:
		drv, t = connect(model="Focus 14", ack=False)
		drv.display([1])
		drv.display([2])
		t.feed(b"\x02\x05\x00\x00")
		self.assertEqual(t.writes[-1], writePacket(14, bytes([2]) + bytes(13)))
		drv.terminate()

	def test_ack_timeout_sends_pending(self) -> None:
		drv, t = connect(model="Focus 14", ack=False)
		with mock.patch.object(fs, "ACK_TIMEOUT", 0.05):
			drv.display([1])
			drv.display([7])
			deadline = time.monotonic() + 2.0
			while time.monotonic() < deadline and t.writes[-1] != writePacket(14, bytes([7]) + bytes(13)):
				time.sleep(0.01)
		self.assertEqual(t.writes[-1], writePacket(14, bytes([7]) + bytes(13)))
		drv.terminate()

	def test_terminate_flushes_blank(self) -> None:
		drv, t = connect(model="Focus 14", ack=False)
		drv.display([1])
		drv.terminate()
		self.assertEqual(t.writes[-1], writePacket(14, bytes(14)))


class InputTests(unittest.TestCase):
	def setUp(self) -> None:
		self.drv, self.t = connect()

	def test_advance_bar(self) -> None:
		self.t.feed(keyPacket(bit("leftAdvanceBar")))
		self.t.feed(keyPacket(0))
		self.assertEqual(gestureIds(self.drv), ["br(freedomscientific):leftadvancebar"])

	def test_dots_and_space(self) -> None:
		self.t.feed(keyPacket(bit("dot1") | bit("dot2")))
		self.t.feed(keyPacket(bit("dot1") | bit("dot2") | bit("brailleSpaceBar")))
		self.t.feed(keyPacket(bit("dot1")))
		self.t.feed(keyPacket(0))
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.dots, 0b11)
		self.assertTrue(g.space)
		self.assertEqual(gestureIds(self.drv), ["br(freedomscientific):braillespacebar+dot1+dot2"])

	def test_typing_dots_only(self) -> None:
		self.t.feed(keyPacket(bit("dot1") | bit("dot4") | bit("dot8")))
		self.t.feed(keyPacket(0))
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.dots, 0b10001001)
		self.assertFalse(g.space)

	def test_third_byte_keys(self) -> None:
		self.t.feed(keyPacket(bit("leftGDFButton") | bit("rightGDFButton")))
		self.t.feed(keyPacket(0))
		self.t.feed(keyPacket(bit("rightBumperBarDown")))
		self.t.feed(keyPacket(0))
		self.assertEqual(
			gestureIds(self.drv),
			["br(freedomscientific):leftgdfbutton+rightgdfbutton", "br(freedomscientific):rightbumperbardown"],
		)

	def test_unknown_bit_has_name(self) -> None:
		self.t.feed(keyPacket(1 << 14))
		self.t.feed(keyPacket(0))
		self.assertEqual(gestureIds(self.drv), ["br(freedomscientific):key14"])

	def test_rocker_bars(self) -> None:
		self.t.feed(extKeyPacket(0b0100))
		self.t.feed(extKeyPacket(0))
		self.assertEqual(gestureIds(self.drv), ["br(freedomscientific):rightrockerbarup"])

	def test_rocker_with_selector(self) -> None:
		self.t.feed(keyPacket(bit("leftShiftKey")))
		self.t.feed(extKeyPacket(0b0010))
		self.t.feed(extKeyPacket(0))
		self.t.feed(keyPacket(0))
		self.assertEqual(gestureIds(self.drv), ["br(freedomscientific):leftrockerbardown+leftshiftkey"])

	def test_routing(self) -> None:
		self.t.feed(buttonPacket(5, True))
		self.t.feed(buttonPacket(5, False))
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.routingIndex, 5)
		self.assertEqual(gestureIds(self.drv), ["br(freedomscientific):routing"])

	def test_multi_routing_and_second_row(self) -> None:
		self.t.feed(buttonPacket(2, True))
		self.t.feed(buttonPacket(9, True))
		self.t.feed(buttonPacket(9, False))
		self.t.feed(buttonPacket(2, False))
		self.assertEqual(self.drv.lastGestures[-1].routingIndexes, [2, 9])
		self.assertEqual(gestureIds(self.drv), ["br(freedomscientific):multirouting"])
		self.t.feed(buttonPacket(0, True, top=True))
		self.t.feed(buttonPacket(0, False, top=True))
		self.assertEqual(self.drv.lastGestures[-1].routingIndex, 0)
		self.assertEqual(gestureIds(self.drv), ["br(freedomscientific):routing2"])

	def test_selector_plus_routing(self) -> None:
		self.t.feed(keyPacket(bit("leftShiftKey")))
		self.t.feed(buttonPacket(3, True))
		self.t.feed(buttonPacket(3, False))
		self.t.feed(keyPacket(0))
		self.assertEqual(self.drv.lastGestures[-1].routingIndex, 3)
		self.assertEqual(gestureIds(self.drv), ["br(freedomscientific):leftshiftkey+routing"])

	def test_wheels(self) -> None:
		self.t.feed(wheelPacket(0, 2))
		self.t.feed(wheelPacket(1, 1))
		self.t.feed(wheelPacket(2, 1))
		self.t.feed(wheelPacket(3, 1))
		self.t.feed(wheelPacket(6, 1))  # Rueda desconocida: se ignora.
		self.assertEqual(
			gestureIds(self.drv),
			[
				"br(freedomscientific):leftwizwheelup",
				"br(freedomscientific):leftwizwheelup",
				"br(freedomscientific):leftwizwheeldown",
				"br(freedomscientific):rightwizwheeldown",
				"br(freedomscientific):rightwizwheelup",
			],
		)

	def test_model_identifier(self) -> None:
		self.t.feed(keyPacket(bit("rightAdvanceBar")))
		self.t.feed(keyPacket(0))
		self.assertEqual(self.drv.lastGestures[-1].identifiers[0], "br(freedomscientific.focus40):rightadvancebar")

	def test_stream_byte_by_byte(self) -> None:
		stream = (
			keyPacket(bit("dot4") | bit("brailleSpaceBar"))
			+ b"\xee"  # basura
			+ keyPacket(0)
			+ buttonPacket(7, True)
			+ buttonPacket(7, False)
			+ extKeyPacket(0b0001)
			+ extKeyPacket(0)
			+ wheelPacket(3, 1)
		)
		for b in stream:
			self.t.feed(bytes((b,)))
		self.assertEqual(
			gestureIds(self.drv),
			[
				"br(freedomscientific):braillespacebar+dot4",
				"br(freedomscientific):routing",
				"br(freedomscientific):leftrockerbarup",
				"br(freedomscientific):rightwizwheelup",
			],
		)

	def test_packets_together(self) -> None:
		self.t.feed(keyPacket(bit("leftAdvanceBar")) + keyPacket(0) + ACK + keyPacket(bit("rightAdvanceBar")) + keyPacket(0))
		self.assertEqual(
			gestureIds(self.drv),
			["br(freedomscientific):leftadvancebar", "br(freedomscientific):rightadvancebar"],
		)


class DetectionTests(unittest.TestCase):
	def test_matches(self) -> None:
		devs = [
			DeviceInfo("usb", r"\\?\usb#vid_0f4e&pid_0114#1", usbId="VID_0F4E&PID_0114"),
			DeviceInfo("usb", r"\\?\usb#vid_0f4e&pid_0111#1", usbId="VID_0F4E&PID_0111"),
			DeviceInfo("usb", r"\\?\usb#vid_1234&pid_0001#1", usbId="VID_1234&PID_0001"),
			DeviceInfo("serial", "COM7", bluetooth=True, bluetoothName="Focus 40 BT 1234"),
			DeviceInfo("serial", "COM8", bluetooth=True, bluetoothName="F14 Blue"),
			DeviceInfo("serial", "COM9", bluetooth=True, bluetoothName="Otra línea"),
			DeviceInfo("serial", "COM3", usbId="VID_0403&PID_6001"),
		]
		matches = FreedomScientificDriver.getMatches(devs, allowGeneric=False)
		self.assertEqual([(m.type, m.port) for m in matches], [
			("bulk", r"\\?\usb#vid_0f4e&pid_0114#1"),
			("bulk", r"\\?\usb#vid_0f4e&pid_0111#1"),
			("serial", "COM7"),
			("serial", "COM8"),
		])
		self.assertTrue(matches[2].bluetooth)
		self.assertEqual(len(FreedomScientificDriver.getMatches(devs, allowGeneric=True)), 4)
		self.assertEqual(len(FreedomScientificDriver.getMatches(devs, bluetooth=False)), 2)
		self.assertEqual(len(FreedomScientificDriver.getMatches(devs, usb=False)), 2)


class GestureMapTests(unittest.TestCase):
	def test_map_values_and_keys(self) -> None:
		known = set(FreedomScientificDriver.keyOrder) | set(FreedomScientificDriver.keyDescriptions)
		for keys, target in FreedomScientificDriver.gestureMap.items():
			self.assertTrue(target.startswith("kb:") or target.isidentifier(), target)
			for k in keys.split("+"):
				self.assertIn(k, known, keys)
			parts = keys.split("+")
			# Ninguna orden en combinaciones solo de puntos.
			self.assertFalse(all(p.startswith("dot") for p in parts), keys)

	def test_key_names_described(self) -> None:
		names = set(fs.KEY_BITS.values()) | set(fs.EXT_KEY_BITS.values()) | set(fs.WHEEL_NAMES.values())
		for name in names:
			self.assertIn(name, FreedomScientificDriver.keyDescriptions)


if __name__ == "__main__":
	unittest.main()
