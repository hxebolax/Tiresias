"""Pruebas del controlador de la Seika Notetaker (MiniSeika, Seika V6 y
V6Pro) con una línea simulada por USB HID y por Bluetooth."""

from __future__ import annotations

import unittest
from unittest import mock

import braille_sim  # noqa: F401
from braille_sim import connectSimulated, gestureIds

from tiresias.braille.drivers import base
from tiresias.braille.drivers import seikaNotetaker as ntk
from tiresias.braille.drivers.ports import DeviceInfo
from tiresias.braille.drivers.seikaNotetaker import SeikaNotetakerDriver

REQUEST = b"\xff\xff\xa1\x00"
UART_CONFIG = b"\x50\x00\x00\x25\x80\x00\x00\x03\x00"
UART_ENABLE = b"\x41\x01"
DESCRIPTION = b"foobarloremips"


def infoPacket(cells: int, buttons: int = 0x16, routing: int | None = None, desc: bytes = DESCRIPTION) -> bytes:
	routing = cells if routing is None else routing
	args = bytes((buttons, cells, routing)) + desc
	return b"\xff\xff\xa2" + bytes((len(args),)) + args


def keysPacket(dots: int = 0, keys: int = 0) -> bytes:
	return b"\xff\xff\xa6\x03" + bytes((dots, keys & 0xFF, keys >> 8))


def routingPacket(indexes, cells: int = 40) -> bytes:
	data = bytearray((cells + 7) // 8)
	for i in indexes:
		data[i // 8] |= 1 << (i % 8)
	return b"\xff\xff\xa4" + bytes((len(data),)) + bytes(data)


def keysRoutingPacket(dots: int, keys: int, indexes, cells: int = 40) -> bytes:
	data = bytearray((cells + 7) // 8)
	for i in indexes:
		data[i // 8] |= 1 << (i % 8)
	args = bytes((dots, keys & 0xFF, keys >> 8)) + bytes(data)
	return b"\xff\xff\xa8" + bytes((len(args),)) + args


def toHid(stream: bytes) -> list[bytes]:
	"""Como el CP2110: un informe por byte (número de informe 1)."""
	return [bytes((1, b, 0)) for b in stream]


def key(name: str) -> int:
	return next(1 << b for b, n in ntk.KEY_BITS.items() if n == name)


class _Display:
	def __init__(self, cells: int = 40, hid: bool = False):
		self.cells = cells
		self.hid = hid

	def __call__(self, data: bytes):
		if data.startswith(b"FEATURE"):
			return None
		stream = ntk.hidPayload(data) if self.hid else data
		if stream == b"\xff\xff\xa1\x00":
			reply = infoPacket(self.cells)
			return toHid(reply) if self.hid else reply
		return None


def connectSerial(cells: int = 40, **kw):
	kw.setdefault("bluetooth", True)
	kw.setdefault("name", "TSM 1234")
	return connectSimulated(SeikaNotetakerDriver, _Display(cells), matchType="serial", **kw)


def connectHid(cells: int = 40, **kw):
	return connectSimulated(
		SeikaNotetakerDriver,
		_Display(cells, hid=True),
		matchType="hid",
		port=r"\\?\hid#vid_10c4&pid_ea80#1",
		usbId="VID_10C4&PID_EA80",
		**kw,
	)


class ConnectionTests(unittest.TestCase):
	def test_hid_v6(self) -> None:
		drv, t = connectHid()
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(drv.model, "SeikaV6")
		self.assertEqual(drv.deviceName, "Seika V6 (foobarloremips)")
		self.assertEqual(drv.numButtons, 22)
		self.assertEqual(drv.numRoutingKeys, 40)
		self.assertEqual(t.features, [UART_CONFIG, UART_ENABLE])
		self.assertEqual(t.writes[0], b"\x04" + REQUEST)
		self.assertEqual(t.opened[0][2], {"exclusive": True})

	def test_hid_report_padding(self) -> None:
		drv, t = connectHid(cells=16, outputSize=64)
		self.assertEqual(drv.numCells, 16)
		self.assertEqual(drv.model, "MiniSeika16")
		self.assertEqual(t.writes[0], b"\x04" + REQUEST + bytes(59))

	def test_bluetooth_serial(self) -> None:
		drv, t = connectSerial(cells=24)
		self.assertEqual(drv.numCells, 24)
		self.assertEqual(drv.model, "MiniSeika24")
		self.assertEqual(t.writes, [REQUEST])
		self.assertEqual(t.features, [])
		match, baud, kwargs = t.opened[0]
		self.assertEqual(baud, 9600)
		self.assertEqual(kwargs.get("parity"), "N")

	def test_info_byte_by_byte_with_garbage(self) -> None:
		def responder(data):
			if data == REQUEST:
				return [bytes((b,)) for b in b"\x00\xff\x13" + infoPacket(40)]
			return None

		drv, t = connectSimulated(SeikaNotetakerDriver, responder, bluetooth=True, name="TSM 0001")
		self.assertEqual(drv.numCells, 40)

	def test_unknown_cell_count(self) -> None:
		def responder(data):
			if data == REQUEST:
				return infoPacket(32, desc=b"")
			return None

		drv, t = connectSimulated(SeikaNotetakerDriver, responder)
		self.assertEqual(drv.numCells, 32)
		self.assertEqual(drv.model, "Seika32")
		self.assertIn("32", drv.deviceName)

	def test_retry_then_answer(self) -> None:
		calls = []

		def responder(data):
			if data == REQUEST:
				calls.append(data)
				if len(calls) == 2:
					return infoPacket(40)
			return None

		with mock.patch.object(ntk, "IDENTIFY_TIMEOUT", 0.05):
			drv, t = connectSimulated(SeikaNotetakerDriver, responder)
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(len(calls), 2)

	def test_no_answer_raises(self) -> None:
		with mock.patch.object(ntk, "IDENTIFY_TIMEOUT", 0.05):
			with self.assertRaises(base.DisplayNotFound):
				connectSimulated(SeikaNotetakerDriver, lambda d: None)


class HidFramingTests(unittest.TestCase):
	def test_payload(self) -> None:
		self.assertEqual(ntk.hidPayload(b"\x01\xa2\x03"), b"\xa2")
		self.assertEqual(ntk.hidPayload(b"\x03\xff\xff\xa6\x00"), b"\xff\xff\xa6")
		self.assertEqual(ntk.hidPayload(b"\x50\x00"), b"")
		self.assertEqual(ntk.hidPayload(b""), b"")

	def test_reports_split(self) -> None:
		reports = ntk.hidReports(bytes(range(100)))
		self.assertEqual([r[0] for r in reports], [63, 37])
		self.assertEqual(b"".join(r[1:] for r in reports), bytes(range(100)))


class OutputTests(unittest.TestCase):
	def test_write_hid(self) -> None:
		drv, t = connectHid()
		drv.display([0x01, 0xFF, 0x80])
		self.assertEqual(t.writes[-1], b"\x2c\xff\xff\xa3\x28" + bytes([0x01, 0xFF, 0x80]) + bytes(37))

	def test_write_hid_16(self) -> None:
		drv, t = connectHid(cells=16)
		drv.display([0x3F] * 16)
		self.assertEqual(t.writes[-1], b"\x14\xff\xff\xa3\x10" + b"\x3f" * 16)

	def test_write_serial(self) -> None:
		drv, t = connectSerial(cells=24)
		drv.display([0x07, 0x38])
		self.assertEqual(t.writes[-1], b"\xff\xff\xa3\x18" + bytes([0x07, 0x38]) + bytes(22))


class InputTests(unittest.TestCase):
	def setUp(self) -> None:
		self.drv, self.t = connectSerial()

	def feed(self, data: bytes) -> None:
		self.t.feed(data)

	def test_keys(self) -> None:
		self.feed(keysPacket(keys=key("lb")))
		self.feed(keysPacket(keys=key("rjDown")))
		self.feed(keysPacket(keys=key("lb") | key("rb")))
		self.assertEqual(
			gestureIds(self.drv),
			["br(seikanotetaker):lb", "br(seikanotetaker):rjdown", "br(seikanotetaker):lb+rb"],
		)

	def test_all_named_keys(self) -> None:
		for bitIndex, name in ntk.KEY_BITS.items():
			self.feed(keysPacket(keys=1 << bitIndex))
			self.assertEqual(gestureIds(self.drv), [f"br(seikanotetaker):{name.lower()}"])

	def test_unknown_key_bit(self) -> None:
		self.feed(keysPacket(keys=1 << 15))
		self.assertEqual(gestureIds(self.drv), ["br(seikanotetaker):key15"])

	def test_dots(self) -> None:
		self.feed(keysPacket(dots=0b10000001, keys=key("rjDown")))
		self.assertEqual(gestureIds(self.drv), ["br(seikanotetaker):d1+d8+rjdown"])
		self.feed(keysPacket(dots=0b00001001))
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.dots, 0b1001)
		self.assertFalse(g.space)
		self.assertEqual(gestureIds(self.drv), ["br(seikanotetaker):d1+d4"])

	def test_space_and_dots(self) -> None:
		self.feed(keysPacket(dots=0b001, keys=key("space")))
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.dots, 1)
		self.assertTrue(g.space)
		self.assertEqual(gestureIds(self.drv), ["br(seikanotetaker):d1+space"])
		# Retroceso con puntos también es espacio y puntos.
		self.feed(keysPacket(dots=0b100, keys=key("backspace")))
		g = self.drv.lastGestures[-1]
		self.assertEqual((g.dots, g.space), (0b100, True))
		self.feed(keysPacket(keys=key("space")))
		self.assertTrue(self.drv.lastGestures[-1].space)

	def test_release_packet_ignored(self) -> None:
		self.feed(keysPacket())
		self.assertEqual(gestureIds(self.drv), [])

	def test_routing(self) -> None:
		self.feed(routingPacket([0]))
		self.feed(routingPacket([39]))
		self.assertEqual([g.routingIndex for g in self.drv.lastGestures], [0, 39])
		self.assertEqual(gestureIds(self.drv), ["br(seikanotetaker):routing"] * 2)

	def test_multi_routing(self) -> None:
		self.feed(routingPacket([0, 7, 8, 15]))
		self.assertEqual(self.drv.lastGestures[-1].routingIndexes, [0, 7, 8, 15])
		self.assertEqual(gestureIds(self.drv), ["br(seikanotetaker):multirouting"])

	def test_keys_and_routing(self) -> None:
		self.feed(keysRoutingPacket(0, key("ljCenter"), [17]))
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.routingIndex, 17)
		self.assertEqual(gestureIds(self.drv), ["br(seikanotetaker):ljcenter+routing"])
		# Sin teclas: solo enrutamiento.
		self.feed(keysRoutingPacket(0, 0, [5]))
		self.assertEqual(gestureIds(self.drv), ["br(seikanotetaker):routing"])

	def test_nvda_sample_packet(self) -> None:
		# Teclas y enrutamiento de una MiniSeika 16 (LJ centro y arriba, celda 15).
		drv, t = connectSerial(cells=16)
		t.feed(bytes([0xFF, 0xFF, 0xA8, 0x05, 0x00, 0b10010000, 0x00, 0x00, 0x40]))
		self.assertEqual(drv.lastGestures[-1].routingIndex, 14)
		self.assertEqual(gestureIds(drv), ["br(seikanotetaker):ljcenter+ljup+routing"])

	def test_routing_beyond_cells_ignored(self) -> None:
		drv, t = connectSerial(cells=16)
		t.feed(routingPacket([16, 20], cells=24))
		self.assertEqual(gestureIds(drv), [])

	def test_model_identifier(self) -> None:
		self.feed(keysPacket(keys=key("rb")))
		self.assertEqual(self.drv.lastGestures[-1].identifiers[0], "br(seikanotetaker.seikav6):rb")

	def test_stream_byte_by_byte(self) -> None:
		stream = (
			keysPacket(keys=key("ljUp"))
			+ b"\x00\x13"  # basura
			+ routingPacket([3, 4])
			+ b"\xff"
			+ keysPacket(dots=0xFF, keys=key("space"))
			+ b"\xff\xff\x99\x01\x00"  # orden desconocida
			+ keysPacket(keys=key("rjCenter"))
		)
		for b in stream:
			self.feed(bytes((b,)))
		self.assertEqual(
			gestureIds(self.drv),
			[
				"br(seikanotetaker):ljup",
				"br(seikanotetaker):multirouting",
				"br(seikanotetaker):d1+d2+d3+d4+d5+d6+d7+d8+space",
				"br(seikanotetaker):rjcenter",
			],
		)

	def test_packet_with_ff_in_data(self) -> None:
		# Todos los puntos y teclas: los datos contienen FF FF.
		self.feed(keysPacket(dots=0xFF, keys=0x3FFF) + keysPacket(keys=key("lb")))
		ids = gestureIds(self.drv)
		self.assertEqual(len(ids), 2)
		self.assertEqual(ids[-1], "br(seikanotetaker):lb")


class HidInputTests(unittest.TestCase):
	def test_keys_over_hid(self) -> None:
		drv, t = connectHid()
		for report in toHid(keysPacket(keys=key("rjUp"))):
			t.feed(report)
		# Un informe con varios bytes útiles.
		packet = routingPacket([2])
		t.feed(bytes((len(packet),)) + packet + bytes(63 - len(packet)))
		self.assertEqual(gestureIds(drv), ["br(seikanotetaker):rjup", "br(seikanotetaker):routing"])


class DetectionTests(unittest.TestCase):
	def test_matches(self) -> None:
		devs = [
			DeviceInfo("hid", r"\\?\hid#vid_10c4&pid_ea80#1", usbId="VID_10C4&PID_EA80"),
			DeviceInfo("hid", r"\\?\hid#vid_1234&pid_0001#1", usbId="VID_1234&PID_0001"),
			DeviceInfo("hid", r"\\?\hid#{00001124}_bt#1", bluetooth=True, bluetoothName="TSM 1234"),
			DeviceInfo("serial", "COM3", usbId="VID_10C4&PID_EA60"),
			DeviceInfo("serial", "COM5", bluetooth=True, bluetoothName="TSM 3366"),
			DeviceInfo("serial", "COM6", bluetooth=True, bluetoothName="TSMX"),
			DeviceInfo("serial", "COM7", bluetooth=True, bluetoothName="TS5 0042"),
		]
		matches = SeikaNotetakerDriver.getMatches(devs, allowGeneric=False)
		self.assertEqual(
			[(m.type, m.port, m.bluetooth) for m in matches],
			[("hid", r"\\?\hid#vid_10c4&pid_ea80#1", False), ("serial", "COM5", True)],
		)
		self.assertEqual(len(SeikaNotetakerDriver.getMatches(devs, allowGeneric=True)), 2)
		self.assertEqual(len(SeikaNotetakerDriver.getMatches(devs, bluetooth=False)), 1)
		self.assertEqual(len(SeikaNotetakerDriver.getMatches(devs, usb=False)), 1)


class GestureMapTests(unittest.TestCase):
	def test_map_values_and_keys(self) -> None:
		known = set(SeikaNotetakerDriver.keyOrder) | set(SeikaNotetakerDriver.keyDescriptions)
		for keys, target in SeikaNotetakerDriver.gestureMap.items():
			self.assertTrue(target.startswith("kb:") or target.isidentifier(), target)
			parts = keys.split("+")
			for k in parts:
				self.assertIn(k, known, keys)
			# Ninguna orden en combinaciones solo de puntos.
			self.assertFalse(all(p in SeikaNotetakerDriver.dotKeys for p in parts), keys)

	def test_key_names_described(self) -> None:
		for name in ntk.KEY_BITS.values():
			self.assertIn(name, SeikaNotetakerDriver.keyDescriptions)


if __name__ == "__main__":
	unittest.main()
