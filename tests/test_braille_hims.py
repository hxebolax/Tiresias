"""Pruebas del controlador de las líneas braille HIMS (sin hardware)."""

import braille_sim  # noqa: F401
from braille_sim import connectSimulated, gestureIds

import ctypes
import threading
import unittest
from unittest import mock

from tiresias.braille.drivers import hwio, winusb
from tiresias.braille.drivers.base import DisplayNotFound
from tiresias.braille.drivers.hims import (
	EDGE,
	SENSE,
	SERIAL_MODELS,
	SMART_BEETLE,
	HimsDriver,
	buildInputPacket,
	buildPacket,
	pickModel,
)
from tiresias.braille.drivers.ports import DeviceInfo


_patches = [mock.patch.object(HimsDriver, "replyTimeout", 0.05), mock.patch.object(HimsDriver, "replyTimeoutBulk", 0.05)]


def setUpModule() -> None:
	# Esperas cortas: la línea simulada contesta al instante o nunca.
	for p in _patches:
		p.start()


def tearDownModule() -> None:
	for p in _patches:
		p.stop()


def cellCountRequest() -> bytes:
	return buildPacket(0xFB, bytes(32))


class FakeHims:
	"""Línea HIMS simulada: contesta al número de celdas y a su identificador."""

	def __init__(self, cells: int, deviceId: bytes = b"", answerId: bool = True, chunked: bool = False) -> None:
		self.cells = cells
		self.deviceId = deviceId
		self.answerId = answerId
		self.chunked = chunked
		self.idRequests: list[bytes] = []

	def __call__(self, data: bytes):
		if data == cellCountRequest():
			reply = buildInputPacket(0x02, self.cells)
			return [reply[i : i + 1] for i in range(len(reply))] if self.chunked else reply
		if len(data) == 4 and data[0] == 0x1C and data[3] == 0x1F:
			self.idRequests.append(data[1:3])
			if self.answerId and data[1:3] == self.deviceId:
				return data
		return None


def keysPacket(mask: int) -> bytes:
	return buildInputPacket(0x01, 0, mask)


class PacketTests(unittest.TestCase):
	def test_cell_count_request_frame(self) -> None:
		frame = cellCountRequest()
		expected = bytearray(b"\xfb\xfb\x01\xf0\x20\x00" + bytes(32) + b"\xf1\xf2\x00\x00\xf3\x00\x00\x00\x00\x00\xfd\xfd")
		expected[-3] = sum(expected) & 0xFF
		self.assertEqual(frame, bytes(expected))
		self.assertEqual(len(frame), 2 + 1 + 1 + 2 + 32 + 1 + 1 + 2 + 0 + 1 + 4 + 1 + 2)

	def test_input_packet_checksum(self) -> None:
		packet = buildInputPacket(0x01, 0, 0x00000301)
		self.assertEqual(packet[:8], b"\xfa\x01\x01\x00\x01\x03\x00\x00")
		self.assertEqual(packet[8], (0xFA + 0x01 + 0x01 + 0x01 + 0x03 + 0xFB) & 0xFF)
		self.assertEqual(packet[9], 0xFB)

	def test_pick_model(self) -> None:
		lx = [m for m in SERIAL_MODELS if m.deviceId == b"LX"]
		self.assertIs(pickModel(lx, 14), SMART_BEETLE)
		self.assertIs(pickModel(lx, 32), SENSE)
		be = [m for m in SERIAL_MODELS if m.deviceId == b"BE"]
		self.assertIs(pickModel(be, 40), EDGE)


class ConnectionTests(unittest.TestCase):
	def test_edge_bulk_without_identification(self) -> None:
		fake = FakeHims(40, b"BE")
		drv, t = connectSimulated(HimsDriver, fake, matchType="bulk", port=r"\\?\usb#hims", usbId="VID_045E&PID_930B")
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(drv.model, "BrailleEdge")
		self.assertEqual(drv.deviceName, "HIMS Braille EDGE")
		self.assertEqual(t.writes[0], cellCountRequest())
		# Solo hay un modelo posible: no se pregunta el identificador.
		self.assertEqual(fake.idRequests, [])
		self.assertEqual(t.opened[0][2], {"epIn": 0, "epOut": 1, "readSize": 64})

	def test_sense_bulk_identification(self) -> None:
		fake = FakeHims(32, b"LX")
		drv, t = connectSimulated(HimsDriver, fake, matchType="bulk", port=r"\\?\usb#hims", usbId="VID_045E&PID_930A")
		# Se pregunta por orden hasta que la línea contesta.
		self.assertEqual(fake.idRequests, [b"SX", b"QX", b"LX"])
		self.assertEqual(t.writes[-1], b"\x1cLX\x1f")
		self.assertEqual(drv.model, "BrailleSense")
		self.assertEqual(drv.numCells, 32)

	def test_smart_beetle_by_cells(self) -> None:
		fake = FakeHims(14, b"LX")
		drv, t = connectSimulated(HimsDriver, fake, matchType="bulk", usbId="VID_045E&PID_930A")
		self.assertEqual(drv.model, "SmartBeetle")
		self.assertEqual(drv.deviceName, "HIMS Smart Beetle")

	def test_sense_qwerty_and_classic(self) -> None:
		drv, _t = connectSimulated(HimsDriver, FakeHims(32, b"QX"), matchType="bulk", usbId="VID_045E&PID_930A")
		self.assertEqual(drv.model, "BrailleSenseQWERTY")
		drv, _t = connectSimulated(HimsDriver, FakeHims(18, b"BS"), matchType="bulk", usbId="VID_045E&PID_930A")
		self.assertEqual(drv.model, "BrailleSenseClassic")
		self.assertEqual(drv.numCells, 18)

	def test_bluetooth_serial(self) -> None:
		fake = FakeHims(40, b"BE", chunked=True)
		drv, t = connectSimulated(HimsDriver, fake, matchType="serial", port="COM7", bluetooth=True, name="BrailleEDGE40 1234")
		self.assertEqual(t.opened[0][1], 115200)
		self.assertEqual(t.opened[0][2], {"parity": "N"})
		# Solo el EDGE se anuncia como «BrailleEDGE»: no hace falta preguntar.
		self.assertEqual(fake.idRequests, [])
		self.assertEqual(drv.model, "BrailleEdge")
		self.assertEqual(drv.numCells, 40)

	def test_bluetooth_name_case_insensitive(self) -> None:
		drv, _t = connectSimulated(HimsDriver, FakeHims(40, b"BE"), matchType="serial", bluetooth=True, name="brailleedge 40")
		self.assertEqual(drv.model, "BrailleEdge")

	def test_manual_port_asks_all(self) -> None:
		fake = FakeHims(40, b"BE")
		drv, _t = connectSimulated(HimsDriver, fake, matchType="serial", port="COM12")
		# Puerto elegido a mano sin datos: se pregunta en orden y se deduplica.
		self.assertEqual(fake.idRequests, [b"SX", b"QX", b"BE"])
		self.assertEqual(drv.model, "BrailleEdge")

	def test_sense6_bluetooth(self) -> None:
		fake = FakeHims(32, b"LX")
		drv, _t = connectSimulated(HimsDriver, fake, matchType="serial", bluetooth=True, name="BrailleSense6 0123")
		self.assertEqual(fake.idRequests, [])
		self.assertEqual(drv.model, "BrailleSense6")
		self.assertEqual(drv.deviceName, "HIMS BrailleSense 6")

	def test_qbraille_bluetooth(self) -> None:
		drv, _t = connectSimulated(HimsDriver, FakeHims(40, b"BE"), matchType="serial", bluetooth=True, name="QBraille XL 01")
		self.assertEqual(drv.model, "QBrailleXL")
		self.assertEqual(drv.deviceName, "HIMS QBraille XL")
		m = HimsDriver.effectiveGestureMap("QBrailleXL")
		self.assertEqual(m["br(hims.qbraillexl):f1"], "kb:escape")

	def test_winusb_open_and_sense6_by_endpoints(self) -> None:
		for pipeOut, model in ((0x01, "BrailleSense6"), (0x02, "BrailleSense")):
			with mock.patch.object(hwio.MemoryTransport, "pipeIn", 0x81, create=True), mock.patch.object(hwio.MemoryTransport, "pipeOut", pipeOut, create=True):
				drv, t = connectSimulated(HimsDriver, FakeHims(32, b"LX"), matchType="winusb", port=r"\\?\usb#vid_045e&pid_930a#{78a1c341}", usbId="VID_045E&PID_930A")
			self.assertEqual(drv.model, model)
			self.assertEqual(t.opened[0][2], {"epIn": 0, "epOut": 1, "readSize": 64})

	def test_open_dispatches_winusb(self) -> None:
		from tiresias.braille.drivers import winusb
		from tiresias.braille.drivers.base import DeviceMatch

		drv, _t = connectSimulated(HimsDriver, FakeHims(40, b"BE"), matchType="bulk", usbId="VID_045E&PID_930B")
		match = DeviceMatch("winusb", "VID_045E&PID_930B", r"\\?\usb#edge#{78a1c341}")
		with mock.patch.object(winusb, "WinUsbDevice") as dev:
			result = HimsDriver._open(drv, match, epIn=0, epOut=1, readSize=64)
		self.assertIs(result, dev.return_value)
		self.assertEqual(dev.call_args.args[0], r"\\?\usb#edge#{78a1c341}")
		self.assertEqual(dev.call_args.kwargs["readSize"], 64)

	def test_smart_beetle_bluetooth_direct(self) -> None:
		fake = FakeHims(14, b"LX")
		drv, _t = connectSimulated(HimsDriver, fake, matchType="serial", bluetooth=True, name="SmartBeetle(b) 0001")
		self.assertEqual(fake.idRequests, [])
		self.assertEqual(drv.model, "SmartBeetle")

	def test_sync_braille_and_edge_2s_serial(self) -> None:
		drv, _t = connectSimulated(HimsDriver, FakeHims(40), matchType="serial", usbId="VID_0403&PID_6001")
		self.assertEqual(drv.model, "SyncBraille")
		self.assertEqual(drv.numCells, 40)
		fake = FakeHims(40)
		drv, _t = connectSimulated(HimsDriver, fake, matchType="serial", usbId="VID_1A86&PID_55D3")
		self.assertEqual(fake.idRequests, [])
		self.assertEqual(drv.model, "BrailleEmotion")
		self.assertEqual(drv.deviceName, "HIMS Braille eMotion")

	def test_no_identification_reply_uses_series_model(self) -> None:
		with mock.patch.object(HimsDriver, "replyTimeout", 0.01), mock.patch.object(HimsDriver, "replyTimeoutBluetooth", 0.01):
			drv, _t = connectSimulated(HimsDriver, FakeHims(32, b"LX", answerId=False), matchType="serial", bluetooth=True, name="BrailleSense U2")
		self.assertEqual(drv.model, "BrailleSense")
		self.assertEqual(drv.numCells, 32)

	def test_no_answer_raises(self) -> None:
		with mock.patch.object(HimsDriver, "replyTimeout", 0.01):
			with self.assertRaises(DisplayNotFound):
				connectSimulated(HimsDriver, lambda d: None, matchType="serial", usbId="VID_0403&PID_6001")

	def test_bad_checksum_ignored(self) -> None:
		def responder(data):
			if data == cellCountRequest():
				bad = bytearray(buildInputPacket(0x02, 40))
				bad[8] ^= 0xFF
				return bytes(bad)
			return None

		with mock.patch.object(HimsDriver, "replyTimeout", 0.01):
			with self.assertRaises(DisplayNotFound):
				connectSimulated(HimsDriver, responder, matchType="serial", usbId="VID_0403&PID_6001")


class OutputTests(unittest.TestCase):
	def test_display_frame(self) -> None:
		drv, t = connectSimulated(HimsDriver, FakeHims(14, b"LX"), matchType="serial", bluetooth=True, name="SmartBeetle")
		drv.display([0x01, 0xFF, 0x3C])
		cells = bytes([0x01, 0xFF, 0x3C]) + bytes(11)
		expected = bytearray(b"\xfc\xfc\x01\xf0\x0e\x00" + cells + b"\xf1\xf2\x00\x00\xf3\x00\x00\x00\x00\x00\xfd\xfd")
		expected[-3] = sum(expected) & 0xFF
		self.assertEqual(t.writes[-1], bytes(expected))
		self.assertEqual(t.writes[-1][-3], (sum(expected[:-3]) + 0xFD * 2) & 0xFF)

	def test_terminate_clears_display(self) -> None:
		drv, t = connectSimulated(HimsDriver, FakeHims(40, b"BE"), matchType="bulk", usbId="VID_045E&PID_930B")
		drv.terminate()
		self.assertEqual(t.writes[-1], buildPacket(0xFC, bytes(40)))
		self.assertTrue(t.closed)


class InputTests(unittest.TestCase):
	def _edge(self):
		return connectSimulated(HimsDriver, FakeHims(40, b"BE"), matchType="bulk", usbId="VID_045E&PID_930B")

	def test_routing(self) -> None:
		drv, t = self._edge()
		t.feed(buildInputPacket(0x00, 5))
		ids = gestureIds(drv, clear=False)
		self.assertEqual(ids, ["br(hims):routing"])
		self.assertEqual(drv.lastGestures[0].routingIndex, 5)
		self.assertEqual(drv.lastGestures[0].identifiers[0], "br(hims.brailleedge):routing")

	def test_routing_out_of_range_ignored(self) -> None:
		drv, t = self._edge()
		t.feed(buildInputPacket(0x00, 40))
		self.assertEqual(gestureIds(drv), [])

	def test_braille_input(self) -> None:
		drv, t = self._edge()
		t.feed(keysPacket(0x01 | 0x04 | 0x08 | 0x0100))
		g = drv.lastGestures[-1]
		self.assertEqual(g.identifiers[-1], "br(hims):dot1+dot3+dot4+space")
		self.assertEqual(g.dots, 0b1101)
		self.assertTrue(g.space)
		t.feed(keysPacket(0x80))
		self.assertEqual(drv.lastGestures[-1].dots, 0x80)
		self.assertFalse(drv.lastGestures[-1].space)

	def test_edge_keys(self) -> None:
		drv, t = self._edge()
		t.feed(keysPacket(0x010000 | 0x020000))  # Desplazamiento superior izquierda + derecha.
		t.feed(keysPacket(0x100000))  # F5
		t.feed(keysPacket(0x01000000))  # Cruceta izquierda arriba.
		t.feed(keysPacket(0x80000000))  # Cruceta derecha derecha.
		t.feed(keysPacket(0x080000))  # Desplazamiento inferior izquierda.
		self.assertEqual(
			gestureIds(drv),
			[
				"br(hims):leftsidescrollup+rightsidescrollup",
				"br(hims):f5",
				"br(hims):leftsideuparrow",
				"br(hims):rightsiderightarrow",
				"br(hims):leftsidescrolldown",
			],
		)

	def test_function_key_not_braille_input(self) -> None:
		drv, t = self._edge()
		t.feed(keysPacket(0x01 | 0x0200))
		g = drv.lastGestures[-1]
		self.assertEqual(g.identifiers[-1], "br(hims):dot1+f1")
		self.assertEqual(g.dots, 0)

	def test_zero_and_unknown_keys_ignored(self) -> None:
		drv, t = connectSimulated(HimsDriver, FakeHims(40), matchType="serial", usbId="VID_0403&PID_6001")
		t.feed(keysPacket(0))
		t.feed(keysPacket(0x01))  # La Sync Braille no tiene teclado braille.
		t.feed(keysPacket(0x1000 | 0x2000))
		self.assertEqual(gestureIds(drv), ["br(hims):leftsidescrollup+rightsidescrollup"])

	def test_sense_scroll_keys(self) -> None:
		drv, t = connectSimulated(HimsDriver, FakeHims(32, b"LX"), matchType="bulk", usbId="VID_045E&PID_930A")
		t.feed(keysPacket(0x020000))
		t.feed(keysPacket(0x040000))
		t.feed(keysPacket(0x2000))
		self.assertEqual(gestureIds(drv), ["br(hims):leftsidescrolldown", "br(hims):rightsidescrollup", "br(hims):leftsidescroll"])

	def test_sense6_scroll_order(self) -> None:
		drv, t = connectSimulated(HimsDriver, FakeHims(32, b"LX"), matchType="serial", bluetooth=True, name="BrailleSense6")
		for mask in (0x010000, 0x020000, 0x040000, 0x080000, 0x0200 | 0x0100):
			t.feed(keysPacket(mask))
		t.feed(keysPacket(0x2000))  # Sin teclas de un solo lado: se descarta.
		self.assertEqual(
			gestureIds(drv),
			["br(hims):leftsidescrollup", "br(hims):rightsidescrollup", "br(hims):rightsidescrolldown", "br(hims):leftsidescrolldown", "br(hims):f1+space"],
		)

	def test_emotion_serial_keys(self) -> None:
		drv, t = connectSimulated(HimsDriver, FakeHims(40), matchType="serial", usbId="VID_1A86&PID_55D3")
		for mask in (0x400000, 0x800000, 0x0200, 0x0400, 0x0800 | 0x01, 0x1000, 0x080000):
			t.feed(keysPacket(mask))
		self.assertEqual(
			gestureIds(drv),
			["br(hims):f1", "br(hims):f2", "br(hims):f3", "br(hims):f4", "br(hims):control+dot1", "br(hims):alt", "br(hims):leftsidescrolldown"],
		)

	def test_smart_beetle_swapped_keys(self) -> None:
		drv, t = connectSimulated(HimsDriver, FakeHims(14, b"LX"), matchType="bulk", usbId="VID_045E&PID_930A")
		t.feed(keysPacket(0x0400))
		t.feed(keysPacket(0x1000))
		t.feed(keysPacket(0x040000))
		t.feed(keysPacket(0x080000 | 0x0200))
		self.assertEqual(gestureIds(drv), ["br(hims):f4", "br(hims):f2", "br(hims):leftsidescroll", "br(hims):f1+rightsidescroll"])

	def test_byte_by_byte_and_garbage(self) -> None:
		drv, t = self._edge()
		stream = b"\x00\x00\x13" + keysPacket(0x0100 | 0x08) + b"\xfa\x05" + buildInputPacket(0x00, 2)
		for b in stream:
			t.feed(bytes([b]))
		self.assertEqual(gestureIds(drv), ["br(hims):dot4+space", "br(hims):routing"])

	def test_bulk_chunk_with_padding(self) -> None:
		drv, t = self._edge()
		t.feed((keysPacket(0x0800) + bytes(64))[:64])
		self.assertEqual(gestureIds(drv), ["br(hims):f3"])

	def test_cell_count_update(self) -> None:
		drv, t = self._edge()
		t.feed(buildInputPacket(0x02, 32))
		self.assertEqual(drv.numCells, 32)


class HidTests(unittest.TestCase):
	def _connect(self, caps=None):
		caps = caps if caps is not None else bytes([1, 0, 0, 0, 0, 0, 0, 0, 0, 40])
		with mock.patch.object(hwio.MemoryTransport, "getFeature", lambda self, rid: caps if rid == 1 else b"", create=True):
			return connectSimulated(HimsDriver, None, matchType="hid", port=r"\\?\hid#hims", usbId="VID_045E&PID_940A")

	@staticmethod
	def report(value: int) -> bytes:
		return value.to_bytes(12, "little")

	def test_connect_and_output(self) -> None:
		drv, t = self._connect()
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(drv.model, "BrailleEmotion")
		self.assertEqual(drv.deviceName, "HIMS Braille eMotion")
		self.assertEqual(t.opened[0][2], {"exclusive": False})
		drv.display([0x07, 0x38])
		self.assertEqual(t.writes[-1], bytes([40, 0x07, 0x38]) + bytes(38))

	def test_feature_failure_uses_default_cells(self) -> None:
		drv, _t = self._connect(caps=b"")
		self.assertEqual(drv.numCells, 40)

	def test_keys_on_release(self) -> None:
		drv, t = self._connect()
		t.feed(self.report(0x01 << 88))  # Espacio.
		t.feed(self.report((0x01 << 88) | (0x01 << 8)))  # Espacio + punto 1.
		t.feed(self.report(0))
		g = drv.lastGestures[-1]
		self.assertEqual(gestureIds(drv), ["br(hims):dot1+space"])
		self.assertEqual(g.dots, 1)
		self.assertTrue(g.space)

	def test_function_and_special_keys(self) -> None:
		drv, t = self._connect()
		for value in (0x01 << 64, 0x40 << 64, 0x08 << 64, 0x80 << 64, 0x01 << 72, 0x02 << 72, 0x04 << 72, 0x02 << 64, 0x20 << 64):
			t.feed(self.report(value))
			t.feed(self.report(0))
		self.assertEqual(
			gestureIds(drv),
			[
				"br(hims):f1",
				"br(hims):f4",
				"br(hims):rightsidescrollup",
				"br(hims):rightsidescrolldown",
				"br(hims):control",
				"br(hims):alt",
				"br(hims):home",
				"br(hims):leftcursor",
				"br(hims):rightcursor",
			],
		)

	def test_routing_single_and_multi(self) -> None:
		drv, t = self._connect()
		t.feed(self.report(1 << (16 + 3)))
		t.feed(self.report(0))
		self.assertEqual(drv.lastGestures[-1].routingIndexes, [3])
		t.feed(self.report((1 << (16 + 0)) | (1 << (16 + 39))))
		t.feed(self.report(0))
		self.assertEqual(drv.lastGestures[-1].routingIndexes, [0, 39])
		self.assertEqual(gestureIds(drv), ["br(hims):routing", "br(hims):multirouting"])

	def test_report_id_byte_ignored(self) -> None:
		drv, t = self._connect()
		t.feed(bytes([0x05]) + self.report(0x01 << 64)[1:])
		t.feed(bytes([0x05]) + bytes(11))
		self.assertEqual(gestureIds(drv), ["br(hims):f1"])


class DetectionTests(unittest.TestCase):
	def test_matches(self) -> None:
		devs = [
			DeviceInfo("usb", r"\\?\usb#sense", usbId="VID_045E&PID_930A"),
			DeviceInfo("usb", r"\\?\usb#edge", usbId="VID_045E&PID_930B"),
			DeviceInfo("hid", r"\\?\hid#edge3s", usbId="VID_045E&PID_940A"),
			DeviceInfo("serial", "COM3", usbId="VID_0403&PID_6001"),
			DeviceInfo("serial", "COM4", usbId="VID_1A86&PID_55D3"),
			DeviceInfo("serial", "COM5", bluetooth=True, bluetoothName="BrailleSense U2 QWERTY"),
			DeviceInfo("serial", "COM6", bluetooth=True, bluetoothName="BrailleEDGE40"),
			DeviceInfo("serial", "COM8", bluetooth=True, bluetoothName="SmartBeetle(b)"),
			DeviceInfo("serial", "COM9", bluetooth=True, bluetoothName="Focus 40 BT"),
			DeviceInfo("hid", r"\\?\hid#bt", bluetooth=True, bluetoothName="BrailleSense 6"),
			DeviceInfo("serial", "COM10", usbId="VID_1234&PID_5678"),
		]
		with mock.patch.object(winusb, "listDevices", return_value=[]) as listed:
			strict = HimsDriver.getMatches(devs, allowGeneric=False)
		self.assertTrue(listed.called)
		self.assertEqual(
			[(m.type, m.port, m.bluetooth) for m in strict],
			[
				("bulk", r"\\?\usb#sense", False),
				("bulk", r"\\?\usb#edge", False),
				("hid", r"\\?\hid#edge3s", False),
				("serial", "COM5", True),
				("serial", "COM6", True),
				("serial", "COM8", True),
			],
		)
		loose = [m.port for m in HimsDriver.getMatches(devs, allowGeneric=True)]
		self.assertIn("COM3", loose)
		self.assertIn("COM4", loose)
		self.assertEqual([m.port for m in HimsDriver.getMatches(devs, usb=False)], ["COM5", "COM6", "COM8"])

	def test_bluetooth_new_prefixes(self) -> None:
		devs = [
			DeviceInfo("serial", "COM5", bluetooth=True, bluetoothName="BrailleSense6 1234"),
			DeviceInfo("serial", "COM6", bluetooth=True, bluetoothName="QBraille XL"),
			DeviceInfo("serial", "COM7", bluetooth=True, bluetoothName="brailleedge40"),
		]
		self.assertEqual([m.port for m in HimsDriver.getMatches(devs)], ["COM5", "COM6", "COM7"])

	def test_winusb_enumerated_first(self) -> None:
		devs = [DeviceInfo("usb", r"\\?\usb#vid_045e&pid_930a#1", usbId="VID_045E&PID_930A")]
		found = [DeviceInfo("winusb", r"\\?\usb#vid_045e&pid_930a#1#{78a1c341}", usbId="VID_045E&PID_930A")]
		with mock.patch.object(winusb, "listDevices", return_value=found):
			matches = HimsDriver.getMatches(devs)
		self.assertEqual([(m.type, m.port) for m in matches], [("winusb", found[0].path), ("bulk", devs[0].path)])
		# Sin línea HIMS USB no se enumera WinUSB.
		with mock.patch.object(winusb, "listDevices") as listed:
			self.assertEqual(HimsDriver.getMatches([DeviceInfo("usb", "x", usbId="VID_1111&PID_2222")]), [])
		self.assertFalse(listed.called)
		# Interfaz WinUSB de otro producto: no es de HIMS.
		self.assertIsNone(HimsDriver.matchDevice(DeviceInfo("winusb", "y", usbId="VID_1111&PID_2222")))


class FakeWinUsbLib:
	"""Imita ``winusb.dll``: extremos configurables y lecturas preparadas."""

	def __init__(self, pipes, reads=()) -> None:
		self.pipes = pipes
		self.reads = list(reads)
		self.written: list[tuple[int, bytes]] = []
		self.aborted: list[int] = []
		self.freed = False

	def WinUsb_Initialize(self, fileHandle, ref) -> bool:
		ref._obj.value = 0x1234
		return True

	def WinUsb_QueryInterfaceSettings(self, usb, alt, ref) -> bool:
		ref._obj.bNumEndpoints = len(self.pipes)
		return True

	def WinUsb_QueryPipe(self, usb, alt, index, ref) -> bool:
		ref._obj.PipeType, ref._obj.PipeId = self.pipes[index]
		return True

	def WinUsb_ReadPipe(self, usb, pipe, buf, size, countRef, ovRef) -> bool:
		if self.reads:
			item = self.reads.pop(0)
			if isinstance(item, int):
				ctypes.set_last_error(item)
				return False
			ctypes.memmove(buf, item, len(item))
			countRef._obj.value = len(item)
			return True
		# Lectura pendiente que no termina hasta cerrar.
		ctypes.set_last_error(hwio.ERROR_IO_PENDING)
		return False

	def WinUsb_WritePipe(self, usb, pipe, buf, size, countRef, ovRef) -> bool:
		self.written.append((pipe, ctypes.string_at(buf, size)))
		countRef._obj.value = size
		return True

	def WinUsb_AbortPipe(self, usb, pipe) -> bool:
		self.aborted.append(pipe)
		return True

	def WinUsb_GetOverlappedResult(self, usb, ov, ref, wait) -> bool:
		return True

	def WinUsb_Free(self, usb) -> bool:
		self.freed = True
		return True


class WinUsbDeviceTests(unittest.TestCase):
	def _open(self, lib, onReceive=None, onError=None):
		# Un evento hace de «archivo» para que CloseHandle reciba un identificador válido.
		handle = hwio.kernel32.CreateEventW(None, True, False, None)
		with mock.patch.object(hwio, "_openFile", return_value=handle):
			return winusb.WinUsbDevice(r"\\?\usb#hims", onReceive or (lambda d: None), onError, readSize=64, lib=lib)

	def test_pipes_write_read_close(self) -> None:
		got: list[bytes] = []
		received = threading.Event()

		def onReceive(data):
			got.append(data)
			received.set()

		packet = buildInputPacket(0x02, 32)
		lib = FakeWinUsbLib([(3, 0x83), (2, 0x81), (2, 0x02)], reads=[packet])
		dev = self._open(lib, onReceive)
		try:
			self.assertEqual((dev.pipeIn, dev.pipeOut), (0x81, 0x02))
			self.assertEqual(dev.kind, "winusb")
			self.assertTrue(received.wait(2))
			self.assertEqual(got, [packet])
			dev.write(b"\x01\x02")
			self.assertEqual(lib.written, [(0x02, b"\x01\x02")])
		finally:
			dev.close()
		self.assertTrue(lib.freed)
		self.assertIn(0x81, lib.aborted)
		with self.assertRaises(hwio.IoError):
			dev.write(b"x")

	def test_missing_pipes(self) -> None:
		lib = FakeWinUsbLib([(2, 0x81)])
		with self.assertRaises(hwio.IoError):
			self._open(lib)
		self.assertTrue(lib.freed)

	def test_read_error_reported_once(self) -> None:
		errors: list[int] = []
		reported = threading.Event()

		def onError(code):
			errors.append(code)
			reported.set()

		lib = FakeWinUsbLib([(2, 0x81), (2, 0x01)], reads=[31])
		dev = self._open(lib, onError=onError)
		try:
			self.assertTrue(reported.wait(2))
			self.assertEqual(errors, [31])
		finally:
			dev.close()


class GestureMapTests(unittest.TestCase):
	def test_map_values_and_keys(self) -> None:
		from tiresias.input import keys as kbKeys

		known = {"routing", "multiRouting"}
		for model in SERIAL_MODELS:
			known |= set(model.keys.values())
		from tiresias.braille.drivers.hims import EMOTION_HID

		known |= set(EMOTION_HID.keys.values())
		maps = [HimsDriver.gestureMap] + list(HimsDriver.modelGestureMaps.values())
		for gmap in maps:
			for combo, target in gmap.items():
				for key in combo.split("+"):
					self.assertIn(key, known, combo)
				self.assertIsInstance(target, str)
				if target.startswith("kb:"):
					parts = target[3:].split("+")
					main = [p for p in parts if p.lower() not in ("control", "shift", "alt", "windows")]
					for name in main:
						self.assertIsNotNone(kbKeys.vkFromName(name), target)
				else:
					self.assertRegex(target, r"^[A-Za-z_]+$")
				# Nada de órdenes con solo puntos: sirven para escribir.
				self.assertFalse(all(k.startswith("dot") for k in combo.split("+")), combo)
		for model in HimsDriver.modelGestureMaps:
			self.assertIn(model, {m.model for m in SERIAL_MODELS})

	def test_commands_exist(self) -> None:
		from tiresias.global_commands import GlobalCommands

		optional = {"braille_toFocus", "braille_selectRange"}
		for target in set(HimsDriver.gestureMap.values()):
			if target.startswith("kb:") or target in optional:
				continue
			self.assertTrue(hasattr(GlobalCommands, "script_" + target), target)

	def test_effective_model_map(self) -> None:
		m = HimsDriver.effectiveGestureMap("SmartBeetle")
		self.assertEqual(m["br(hims.smartbeetle):f2"], "kb:windows")
		self.assertEqual(m["br(hims):f2"], "kb:alt")


if __name__ == "__main__":
	unittest.main()
