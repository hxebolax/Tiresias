"""Pruebas del controlador de las líneas Seika 3, 4, 5 y Seika80 con una
línea simulada."""

from __future__ import annotations

import unittest
from unittest import mock

import braille_sim  # noqa: F401
from braille_sim import connectSimulated, gestureIds

from tiresias.braille.drivers import base
from tiresias.braille.drivers import seika
from tiresias.braille.drivers.ports import DeviceInfo
from tiresias.braille.drivers.seika import SeikaDriver

REQ_VERSION = b"\xff\xff\x1c"
REQ_LEGACY = b"\xff\xff\x0a"
REPLY_40 = b"seika3 v1.23 "
REPLY_80 = b"seika80 v2.0 "
REPLY_LEGACY = b"\x00\x05\x28\x08seika\x00\x00\x00"


class _Display:
	"""Línea simulada que contesta a una de las dos peticiones de versión."""

	def __init__(self, reply: bytes = REPLY_40, legacy: bool = False, chunks: bool = False):
		self.reply = reply
		self.legacy = legacy
		self.chunks = chunks

	def __call__(self, data: bytes):
		if (data == REQ_VERSION and not self.legacy) or (data == REQ_LEGACY and self.legacy):
			if self.chunks:
				return [bytes((b,)) for b in self.reply]
			return self.reply
		return None


def connect(reply: bytes = REPLY_40, legacy: bool = False, **kw):
	return connectSimulated(SeikaDriver, _Display(reply, legacy), **kw)


def keyPacket(byte0: int, byte1: int = 0) -> bytes:
	return bytes((0x60 | byte0, 0x60 | byte1))


def routingBlock(indexes, cells: int = 40) -> bytes:
	block = bytearray(2 + cells // 4)
	for i in indexes:
		block[7 + i // 8] |= 1 << (i % 8)
	return bytes(block)


class ConnectionTests(unittest.TestCase):
	def test_seika40(self) -> None:
		drv, t = connect()
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(drv.model, "Seika40")
		self.assertEqual(drv.deviceName, "Seika de 40 celdas")
		self.assertEqual(drv.protocol, "40")
		self.assertEqual(drv.firmware, "seika3 v1.23")
		self.assertEqual(t.writes, [REQ_VERSION])
		match, baud, kwargs = t.opened[0]
		self.assertEqual(baud, 9600)
		self.assertEqual(kwargs.get("parity"), "O")
		self.assertEqual(kwargs.get("stopBits"), 1)

	def test_seika80(self) -> None:
		drv, t = connect(REPLY_80)
		self.assertEqual(drv.numCells, 80)
		self.assertEqual(drv.model, "Seika80")
		self.assertEqual(drv.deviceName, "Seika80")
		self.assertEqual(drv.protocol, "80")

	def test_versions_4_and_5(self) -> None:
		drv, t = connect(b"seika5 v3.00 ")
		self.assertEqual(drv.numCells, 40)

	def test_legacy_seika3(self) -> None:
		with mock.patch.object(seika, "IDENTIFY_TIMEOUT", 0.05):
			drv, t = connect(REPLY_LEGACY, legacy=True)
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(drv.protocol, "legacy")
		self.assertIn("antiguo", drv.deviceName)
		self.assertEqual(t.writes, [REQ_VERSION, REQ_LEGACY])

	def test_legacy_v5_marker(self) -> None:
		with mock.patch.object(seika, "IDENTIFY_TIMEOUT", 0.05):
			drv, t = connect(b"\x00\x05\x28\x08v5.0\x01\x01\x01\x01", legacy=True)
		self.assertEqual(drv.protocol, "legacy")

	def test_reply_in_chunks(self) -> None:
		drv, t = connectSimulated(SeikaDriver, _Display(REPLY_80, chunks=True))
		self.assertEqual(drv.numCells, 80)
		# Tras la identificación, las teclas se leen bien.
		t.feed(keyPacket(0x01))
		self.assertEqual(gestureIds(drv), ["br(seika):left"])

	def test_short_reply_and_rest_skipped(self) -> None:
		# La respuesta llega incompleta: se acepta al terminar la espera y el
		# resto, si llega luego, no se toma por teclas.
		def responder(data):
			if data == REQ_VERSION:
				return REPLY_40[:8]
			return None

		with mock.patch.object(seika, "IDENTIFY_TIMEOUT", 0.05):
			drv, t = connectSimulated(SeikaDriver, responder)
		self.assertEqual(drv.numCells, 40)
		t.feed(REPLY_40[8:] + keyPacket(0x04))
		self.assertEqual(gestureIds(drv), ["br(seika):right"])

	def test_garbage_before_reply(self) -> None:
		drv, t = connect(b"\x13\x00" + REPLY_40)
		self.assertEqual(drv.numCells, 40)

	def test_no_answer_raises(self) -> None:
		with mock.patch.object(seika, "IDENTIFY_TIMEOUT", 0.05):
			with self.assertRaises(base.DisplayNotFound):
				connectSimulated(SeikaDriver, lambda d: None)

	def test_unknown_version_raises(self) -> None:
		with mock.patch.object(seika, "IDENTIFY_TIMEOUT", 0.05):
			with self.assertRaises(base.DisplayNotFound):
				connect(b"seika9 v1.00 ")

	def test_bluetooth_port(self) -> None:
		drv, t = connect(bluetooth=True, name="TS5 1234")
		self.assertEqual(drv.numCells, 40)
		self.assertIn("Bluetooth", drv.displayName)


class OutputTests(unittest.TestCase):
	def test_write_40(self) -> None:
		drv, t = connect()
		drv.display([0x01, 0xFF, 0x80])
		expected = b"\xff\xffseika\x00" + b"\x00\x01\x00\xff\x00\x80" + b"\x00\x00" * 37
		self.assertEqual(t.writes[-1], expected)
		self.assertEqual(len(t.writes[-1]), 88)

	def test_write_80(self) -> None:
		drv, t = connect(REPLY_80)
		drv.display([0x3F] * 81)
		self.assertEqual(t.writes[-1], b"\xff\xffs80\x00\x00\x00" + b"\x3f" * 80)

	def test_write_legacy(self) -> None:
		with mock.patch.object(seika, "IDENTIFY_TIMEOUT", 0.05):
			drv, t = connect(REPLY_LEGACY, legacy=True)
		drv.display([0x07])
		self.assertEqual(t.writes[-1], b"\xff\xff\x04\x00\x63\x00\x50\x00" + b"\x00\x07" + b"\x00\x00" * 39)

	def test_terminate_blanks(self) -> None:
		drv, t = connect(REPLY_80)
		drv.display([1, 2, 3])
		drv.terminate()
		self.assertEqual(t.writes[-1], b"\xff\xffs80\x00\x00\x00" + bytes(80))
		self.assertTrue(t.closed)


class InputTests(unittest.TestCase):
	def setUp(self) -> None:
		self.drv, self.t = connect()

	def test_scroll_keys(self) -> None:
		self.t.feed(keyPacket(0x01))
		self.t.feed(keyPacket(0x04))
		self.assertEqual(gestureIds(self.drv), ["br(seika):left", "br(seika):right"])

	def test_function_keys(self) -> None:
		for byte0, byte1, name in (
			(0, 0x02, "b1"),
			(0, 0x08, "b2"),
			(0, 0x10, "b3"),
			(0x10, 0, "b4"),
			(0x08, 0, "b5"),
			(0x02, 0, "b6"),
		):
			self.t.feed(keyPacket(byte0, byte1))
			self.assertEqual(gestureIds(self.drv), [f"br(seika):{name}"])

	def test_combination(self) -> None:
		self.t.feed(keyPacket(0, 0x02 | 0x08))
		self.t.feed(keyPacket(0x01 | 0x04))
		self.assertEqual(gestureIds(self.drv), ["br(seika):b1+b2", "br(seika):left+right"])

	def test_release_packet_ignored(self) -> None:
		self.t.feed(keyPacket(0x08))
		self.t.feed(keyPacket(0))
		self.assertEqual(gestureIds(self.drv), ["br(seika):b5"])

	def test_unknown_bit(self) -> None:
		self.t.feed(keyPacket(0, 0x01))
		self.assertEqual(gestureIds(self.drv), ["br(seika):key8"])

	def test_model_identifier(self) -> None:
		self.t.feed(keyPacket(0x04))
		self.assertEqual(self.drv.lastGestures[-1].identifiers[0], "br(seika.seika40):right")

	def test_routing(self) -> None:
		self.t.feed(routingBlock([0]))
		self.t.feed(routingBlock([39]))
		gestures = list(self.drv.lastGestures)
		self.assertEqual([g.routingIndex for g in gestures], [0, 39])
		self.assertEqual(gestureIds(self.drv), ["br(seika):routing", "br(seika):routing"])

	def test_multi_routing(self) -> None:
		self.t.feed(routingBlock([3, 17]))
		self.assertEqual(self.drv.lastGestures[-1].routingIndexes, [3, 17])
		self.assertEqual(gestureIds(self.drv), ["br(seika):multirouting"])

	def test_empty_routing_block_ignored(self) -> None:
		self.t.feed(routingBlock([]))
		self.assertEqual(gestureIds(self.drv), [])

	def test_stream_byte_by_byte(self) -> None:
		stream = keyPacket(0x10) + routingBlock([12]) + keyPacket(0, 0x10) + keyPacket(0)
		for b in stream:
			self.t.feed(bytes((b,)))
		self.assertEqual(gestureIds(self.drv), ["br(seika):b4", "br(seika):routing", "br(seika):b3"])

	def test_routing_80(self) -> None:
		drv, t = connect(REPLY_80)
		block = routingBlock([79, 40], cells=80)
		self.assertEqual(len(block), 22)
		t.feed(block[:5])
		t.feed(block[5:])
		self.assertEqual(drv.lastGestures[-1].routingIndexes, [40, 79])
		self.assertEqual(gestureIds(drv), ["br(seika):multirouting"])


class DetectionTests(unittest.TestCase):
	def test_matches(self) -> None:
		devs = [
			DeviceInfo("serial", "COM3", usbId="VID_10C4&PID_EA60"),
			DeviceInfo("serial", "COM4", usbId="VID_0403&PID_6001"),
			DeviceInfo("serial", "COM7", bluetooth=True, bluetoothName="TS5 0042"),
			DeviceInfo("serial", "COM8", bluetooth=True, bluetoothName="TSM 0042"),
			DeviceInfo("serial", "COM9", bluetooth=True, bluetoothName="TS5 abc"),
			DeviceInfo("hid", r"\\?\hid#vid_10c4&pid_ea80", usbId="VID_10C4&PID_EA80"),
		]
		matches = SeikaDriver.getMatches(devs, allowGeneric=False)
		self.assertEqual([(m.type, m.port, m.bluetooth) for m in matches], [("serial", "COM7", True)])
		matches = SeikaDriver.getMatches(devs, allowGeneric=True)
		self.assertEqual([(m.type, m.port, m.bluetooth) for m in matches], [("serial", "COM3", False), ("serial", "COM7", True)])
		self.assertEqual(len(SeikaDriver.getMatches(devs, bluetooth=False)), 1)
		self.assertEqual(len(SeikaDriver.getMatches(devs, usb=False)), 1)


class GestureMapTests(unittest.TestCase):
	def test_map_values_and_keys(self) -> None:
		known = set(SeikaDriver.keyOrder) | set(SeikaDriver.keyDescriptions)
		for keys, target in SeikaDriver.gestureMap.items():
			self.assertTrue(target.startswith("kb:") or target.isidentifier(), target)
			for k in keys.split("+"):
				self.assertIn(k, known, keys)

	def test_key_names_described(self) -> None:
		for name in seika.KEY_BITS.values():
			self.assertIn(name, SeikaDriver.keyDescriptions)


if __name__ == "__main__":
	unittest.main()
