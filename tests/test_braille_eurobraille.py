"""Pruebas del controlador Eurobraille (Esys, Esytime, Iris, b.book, b.note) con datos simulados."""

from __future__ import annotations

import re
import unittest
from unittest import mock

import braille_sim  # noqa: F401
from braille_sim import connectSimulated, gestureIds

from tiresias.braille.drivers import eurobraille
from tiresias.braille.drivers.eurobraille import EurobrailleDriver, buildPacket
from tiresias.braille.drivers.ports import DeviceInfo

STX, ETX, ACK = 0x02, 0x03, 0x06


def pkt(ptype: bytes, sub: bytes, data: bytes = b"") -> bytes:
	"""Paquete tal como lo envía la línea (sin número de trama)."""
	body = ptype + sub + data
	return bytes([STX]) + (len(body) + 2).to_bytes(2, "big") + body + bytes([ETX])


def identity(typeCode: int, cells: int, protocol: bytes = b"2.0") -> list[bytes]:
	return [
		pkt(b"S", b"T", bytes([typeCode])),
		pkt(b"S", b"G", bytes([cells])),
		pkt(b"S", b"P", protocol + b"  \x00"),
		pkt(b"S", b"M", (128).to_bytes(2, "big")),
		pkt(b"S", b"I"),
	]


def serialResponder(typeCode: int, cells: int):
	def respond(data: bytes):
		if data == pkt(b"S", b"I"):
			return identity(typeCode, cells)
		return None

	return respond


HID_SIZE = 33  # tamaño de los informes de salida simulados (id + 32 bytes)


def hidReports(stream: bytes, size: int = HID_SIZE) -> list[bytes]:
	"""Reparte bytes en informes HID de entrada (id 0, relleno 0x55)."""
	block = size - 1
	out = []
	for i in range(0, len(stream), block):
		chunk = stream[i : i + block]
		out.append(b"\x00" + chunk + b"\x55" * (block - len(chunk)))
	return out


class HidResponder:
	"""Línea HID simulada: reconstruye los paquetes de los informes y contesta."""

	def __init__(self, typeCode: int, cells: int, protocol: bytes = b"3.0", ackDisplay: bool = False) -> None:
		self.typeCode = typeCode
		self.cells = cells
		self.protocol = protocol
		self.ackDisplay = ackDisplay
		self.stream = bytearray()
		self.packets: list[bytes] = []
		self.hidMode = True

	def __call__(self, report: bytes):
		self.stream += report[1:]
		replies = []
		while True:
			start = self.stream.find(bytes([STX]))
			if start < 0:
				self.stream.clear()
				break
			del self.stream[:start]
			if len(self.stream) < 3:
				break
			length = int.from_bytes(self.stream[1:3], "big")
			end = self.stream.find(bytes([ETX]), 1 + length)
			if end < 0:
				break
			packet = bytes(self.stream[: end + 1])
			del self.stream[: end + 1]
			self.packets.append(packet)
			body = packet[3 : 1 + length]
			frame = packet[1 + length] if end > 1 + length else None
			if body == b"SI":
				for p in identity(self.typeCode, self.cells, self.protocol):
					replies += hidReports(p)
			elif body[:2] == b"KU" and self.hidMode:
				replies += hidReports(pkt(b"K", b"U", body[2:3]))
			elif body[:2] == b"BS" and self.ackDisplay and frame is not None:
				replies += hidReports(bytes([ACK, frame]))
		return replies or None


def keyPkt(group: bytes, value: int, size: int) -> bytes:
	return pkt(b"K", group, value.to_bytes(size, "big"))


def brailleKeys(*dots: int, space: bool = False, backSpace: bool = False) -> bytes:
	value = 0
	for d in dots:
		value |= 1 << (d - 1)
	if backSpace:
		value |= 0x100
	if space:
		value |= 0x200
	return keyPkt(b"B", value, 2)


def commandKeys(*bits: int) -> bytes:
	value = 0
	for b in bits:
		value |= 1 << b
	return keyPkt(b"C", value, 4)


class ConnectionTests(unittest.TestCase):
	def test_esys_bluetooth_serial(self) -> None:
		drv, t = connectSimulated(EurobrailleDriver, serialResponder(0x08, 40), matchType="serial", port="COM5", bluetooth=True, name="Esys 40 BT")
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(drv.model, "Esys")
		self.assertEqual(drv.deviceName, "Esys 40")
		self.assertEqual(drv.protocolVersion, 2.0)
		self.assertFalse(drv._ackMode)
		self.assertEqual(drv.systemInfo["G"], bytes([40]))
		# Petición de identificación y desactivación de la visualización.
		self.assertEqual(t.writes[0], b"\x02\x00\x04SI\x03")
		self.assertEqual(t.writes[1], b"\x02\x00\x05VD0\x03")
		match, baud, kwargs = t.opened[0]
		self.assertEqual(baud, 9600)
		self.assertEqual(kwargs.get("parity"), "E")
		self.assertEqual(kwargs.get("stopBits"), 1)

	def test_bnote_sends_connection_name(self) -> None:
		drv, t = connectSimulated(EurobrailleDriver, serialResponder(0x13, 40), matchType="serial", port="COM9", usbId="VID_28AC&PID_0013")
		self.assertEqual(drv.model, "bnote")
		self.assertEqual(drv.deviceName, "b.note 2")
		self.assertEqual(t.writes[-1], pkt(b"S", b"n", b"Tiresias/09"))
		drv.closeDelay = 0
		drv.terminate()
		self.assertIn(pkt(b"S", b"n"), t.writes)
		self.assertTrue(t.closed)

	def test_esytime_and_iris_models(self) -> None:
		drv, _t = connectSimulated(EurobrailleDriver, serialResponder(0x10, 32))
		self.assertEqual((drv.model, drv.deviceName, drv.numCells), ("Esytime", "Esytime Evo 32", 32))
		drv, _t = connectSimulated(EurobrailleDriver, serialResponder(0x02, 40))
		self.assertEqual((drv.model, drv.deviceName), ("Iris", "Iris 40"))

	def test_no_answer(self) -> None:
		with mock.patch.object(EurobrailleDriver, "_waitFor", return_value=False):
			with self.assertRaises(eurobraille.DisplayNotFound):
				connectSimulated(EurobrailleDriver, None)

	def test_hid_connect_ack_mode(self) -> None:
		resp = HidResponder(0x0C, 80)
		drv, t = connectSimulated(EurobrailleDriver, resp, matchType="hid", port="\\\\?\\hid#x", usbId="VID_C251&PID_1123", outputSize=HID_SIZE)
		self.assertEqual((drv.numCells, drv.deviceName, drv.model), (80, "Esys 80", "Esys"))
		self.assertTrue(drv._ackMode)
		self.assertEqual(t.opened[0][2].get("exclusive"), False)
		# Primer informe: id 0 + petición de identificación + relleno 0x55.
		self.assertEqual(t.writes[0], b"\x00\x02\x00\x04SI\x03" + b"\x55" * 26)
		self.assertTrue(all(len(w) == HID_SIZE for w in t.writes))


class OutputTests(unittest.TestCase):
	def test_serial_display(self) -> None:
		drv, t = connectSimulated(EurobrailleDriver, serialResponder(0x07, 12))
		drv.display([0x01, 0xFF, 0x80] + [0] * 9)
		self.assertEqual(t.writes[-1], b"\x02\x00\x10BS\x01\xff\x80" + bytes(9) + b"\x03")
		# Celdas de menos: se rellenan hasta 12.
		drv.display([0x3F])
		self.assertEqual(t.writes[-1], b"\x02\x00\x10BS\x3f" + bytes(11) + b"\x03")

	def test_hid_display_split_with_frame(self) -> None:
		resp = HidResponder(0x08, 40, ackDisplay=True)
		drv, t = connectSimulated(EurobrailleDriver, resp, matchType="hid", outputSize=HID_SIZE)
		before = len(t.writes)
		cells = list(range(1, 41))
		drv.display(cells)
		reports = t.writes[before:]
		self.assertEqual(len(reports), 2)
		stream = reports[0][1:] + reports[1][1:]
		frame = stream[45]
		self.assertTrue(0x20 <= frame <= 0x7F)
		# Longitud = 44 (no cuenta el número de trama), luego trama y ETX, y relleno 0x55.
		self.assertEqual(stream[:46], b"\x02\x00\x2cBS" + bytes(cells) + bytes([frame]))
		self.assertEqual(stream[46], ETX)
		self.assertEqual(stream[47:], b"\x55" * (64 - 47))
		self.assertEqual(resp.packets[-1][3:5], b"BS")

	def test_ack_flow_control(self) -> None:
		resp = HidResponder(0x08, 40, ackDisplay=False)
		drv, t = connectSimulated(EurobrailleDriver, resp, matchType="hid", outputSize=HID_SIZE)
		with mock.patch.object(eurobraille.queue_handler, "callLater", return_value=7) as later:
			drv.display([1] * 40)
			sent = len(t.writes)
			first = resp.packets[-1]
			frame1 = first[-2]
			drv.display([2] * 40)
			drv.display([3] * 40)
			# Sin confirmación todavía: no se envía nada más; se programa el envío diferido.
			self.assertEqual(len(t.writes), sent)
			later.assert_called_once()
		with mock.patch.object(eurobraille.queue_handler, "cancelCallLater"):
			for r in hidReports(bytes([ACK, frame1])):
				t.feed(r)
		self.assertGreater(len(t.writes), sent)
		last = resp.packets[-1]
		self.assertEqual(last[5:45], bytes([3] * 40))
		self.assertEqual(last[-2], frame1 + 1)
		# Sin ACK: el envío diferido manda la última imagen pendiente.
		with mock.patch.object(eurobraille.queue_handler, "callLater", return_value=8):
			drv.display([4] * 40)
		self.assertEqual(resp.packets[-1][5:45], bytes([3] * 40))
		drv._flushPending()
		self.assertEqual(resp.packets[-1][5:45], bytes([4] * 40))

	def test_redraw_after_internal_menu(self) -> None:
		drv, t = connectSimulated(EurobrailleDriver, serialResponder(0x07, 12))
		drv.display([5] * 12)
		frame = t.writes[-1]
		t.feed(pkt(b"R", b"I"))
		t.feed(pkt(b"R", b"P"))
		self.assertEqual(t.writes[-1], frame)
		self.assertEqual(t.writes.count(frame), 2)


class InputTests(unittest.TestCase):
	def setUp(self) -> None:
		self.drv, self.t = connectSimulated(EurobrailleDriver, serialResponder(0x08, 40))

	def test_braille_keys(self) -> None:
		self.t.feed(brailleKeys(1, 2))
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.dots, 0b11)
		self.assertFalse(g.space)
		self.assertEqual(gestureIds(self.drv), ["br(eurobraille):dot1+dot2"])
		self.t.feed(brailleKeys(1, space=True))
		self.assertTrue(self.drv.lastGestures[-1].space)
		self.assertEqual(gestureIds(self.drv), ["br(eurobraille):dot1+space"])
		self.t.feed(brailleKeys(1, 2, backSpace=True))
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.dots, 0)
		self.assertEqual(gestureIds(self.drv), ["br(eurobraille):backspace+dot1+dot2"])
		self.t.feed(brailleKeys(7, 8))
		self.assertEqual(self.drv.lastGestures[-1].dots, 0xC0)

	def test_routing(self) -> None:
		self.t.feed(pkt(b"K", b"I", bytes([1, 5])))
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.routingIndex, 4)
		self.assertEqual(gestureIds(self.drv), ["br(eurobraille):routing"])
		self.t.feed(pkt(b"K", b"I", bytes([2, 5])))  # repetición: se ignora
		self.assertEqual(gestureIds(self.drv), [])
		self.t.feed(pkt(b"K", b"I", bytes([3, 40])))
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.routingIndex, 39)
		self.assertEqual(gestureIds(self.drv), ["br(eurobraille):doublerouting"])
		self.assertEqual(g.identifiers[0], "br(eurobraille.esys):doublerouting")

	def test_esys_command_keys(self) -> None:
		self.t.feed(commandKeys(1))  # switch1Left
		self.assertEqual(gestureIds(self.drv), [])
		self.t.feed(commandKeys())
		self.assertEqual(gestureIds(self.drv), ["br(eurobraille):switch1left"])
		# Joystick derecho izquierda + arriba.
		self.t.feed(commandKeys(27))
		self.t.feed(commandKeys(27, 24))
		self.t.feed(commandKeys(24))
		self.t.feed(commandKeys())
		self.assertEqual(gestureIds(self.drv), ["br(eurobraille):joystick2left+joystick2up"])
		self.t.feed(commandKeys(20))
		self.t.feed(commandKeys())
		self.assertEqual(gestureIds(self.drv), ["br(eurobraille):joystick1center"])
		# Mismo estado repetido: sin gesto.
		self.t.feed(commandKeys(10))
		self.t.feed(commandKeys(10))
		self.t.feed(commandKeys())
		self.assertEqual(gestureIds(self.drv), ["br(eurobraille):switch6right"])

	def test_command_held_with_braille_and_routing(self) -> None:
		self.t.feed(commandKeys(3))  # switch2Left pulsado
		self.t.feed(brailleKeys(1))
		self.assertEqual(gestureIds(self.drv), ["br(eurobraille):dot1+switch2left"])
		self.assertEqual(self.drv.lastGestures, [])
		self.t.feed(commandKeys())  # al soltar no hay otro gesto
		self.assertEqual(gestureIds(self.drv), [])
		self.t.feed(commandKeys(0))
		self.t.feed(pkt(b"K", b"I", bytes([1, 3])))
		self.t.feed(commandKeys())
		self.assertEqual(gestureIds(self.drv), ["br(eurobraille):routing+switch1right"])

	def test_byte_by_byte_and_noise(self) -> None:
		stream = b"\x55\x03" + brailleKeys(4, 5, space=True) + b"\x00" + pkt(b"K", b"I", bytes([1, 1])) + pkt(b"V", b"D", b"x")
		for b in stream:
			self.t.feed(bytes([b]))
		self.assertEqual(gestureIds(self.drv), ["br(eurobraille):dot4+dot5+space", "br(eurobraille):routing"])
		self.assertEqual(self.drv.lastGestures, [])

	def test_corrupt_packet_resync(self) -> None:
		bad = b"\x02\x00\x06KB\x00\x01\x55"  # sin ETX donde toca
		self.t.feed(bad + brailleKeys(2))
		self.assertEqual(gestureIds(self.drv), ["br(eurobraille):dot2"])


class PcKeyboardTests(unittest.TestCase):
	"""Teclado de PC (``K Z``: reservado, modificadores, tecla especial, carácter)."""

	def setUp(self) -> None:
		self.drv, self.t = connectSimulated(EurobrailleDriver, serialResponder(0x15, 40))
		patcher = mock.patch.object(self.drv, "_typeText")
		self.typed = patcher.start()
		self.addCleanup(patcher.stop)

	def pc(self, mods: int, special: int, char: int) -> None:
		self.t.feed(pkt(b"K", b"Z", bytes([0, mods, special, char])))

	def test_printable_characters_are_typed(self) -> None:
		self.pc(0, 0, ord("a"))
		self.pc(0x01, 0, ord("A"))  # Mayúsculas ya aplicadas
		self.pc(0x10, 0, 0x80)  # AltGr + E = «€» (Windows-1252)
		self.pc(0, 0, 0xF1)  # «ñ»
		self.assertEqual([c.args[0] for c in self.typed.call_args_list], ["a", "A", "€", "ñ"])
		self.assertEqual(gestureIds(self.drv), [])

	def test_special_keys_emulated(self) -> None:
		self.pc(0, 0x70, 0)
		self.pc(0, 0x26, 0)
		self.pc(0x02, 0x24, 0)
		self.pc(0x01, 0x09, 0)
		self.pc(0, 0, 0x0D)  # Intro como carácter de control
		gestures = list(self.drv.lastGestures)
		self.assertEqual(
			gestureIds(self.drv),
			["br(eurobraille):pc_f1", "br(eurobraille):pc_uparrow", "br(eurobraille):pc_control+pc_home", "br(eurobraille):pc_shift+pc_tab", "br(eurobraille):pc_enter"],
		)
		self.assertEqual([g.emulatedKey for g in gestures], ["kb:f1", "kb:upArrow", "kb:control+home", "kb:shift+tab", "kb:enter"])
		self.assertEqual(gestures[0].identifiers[0], "br(eurobraille.bbook):pc_f1")
		self.typed.assert_not_called()

	def test_shortcuts(self) -> None:
		self.pc(0x02, 0, ord("c"))
		self.pc(0x04 | 0x01, 0, ord("F"))
		self.pc(0x08, 0, ord("e"))
		self.pc(0x02, 0, ord(" "))
		self.pc(0x02, 0, ord("+"))
		gestures = list(self.drv.lastGestures)
		self.assertEqual(
			gestureIds(self.drv),
			[
				"br(eurobraille):pc_c+pc_control",
				"br(eurobraille):pc_alt+pc_f+pc_shift",
				"br(eurobraille):pc_e+pc_windows",
				"br(eurobraille):pc_control+pc_space",
				"br(eurobraille):pc_control+pc_plus",
			],
		)
		self.assertEqual([g.emulatedKey for g in gestures], ["kb:control+c", "kb:shift+alt+f", "kb:windows+e", "kb:control+space", None])
		self.typed.assert_not_called()

	def test_altgr_with_special_and_windows_key(self) -> None:
		self.pc(0x10, 0x2E, 0)
		self.pc(0, 0x5B, 0)
		self.pc(0x08, 0x5B, 0)
		self.assertEqual([g.emulatedKey for g in self.drv.lastGestures], ["kb:control+alt+delete", "kb:windows", "kb:windows"])

	def test_unknown_and_short_packets_ignored(self) -> None:
		self.pc(0, 0xEE, 0)
		self.t.feed(pkt(b"K", b"Z", b"\x41"))
		self.assertEqual(gestureIds(self.drv), [])
		self.typed.assert_not_called()

	def test_three_byte_packet(self) -> None:
		self.t.feed(pkt(b"K", b"Z", bytes([0x02, 0, ord("v")])))
		self.assertEqual(self.drv.lastGestures[-1].emulatedKey, "kb:control+v")


class FamilyInputTests(unittest.TestCase):
	def test_iris_one_shot_and_ping(self) -> None:
		drv, t = connectSimulated(EurobrailleDriver, serialResponder(0x01, 20))
		t.feed(commandKeys(0))  # l1, enviada una sola vez
		self.assertEqual(gestureIds(drv), ["br(eurobraille):l1"])
		self.assertEqual(drv.lastGestures, [])
		t.feed(commandKeys(8))
		self.assertEqual(gestureIds(drv), ["br(eurobraille):uparrow"])
		self.assertEqual(drv.lastGestures, [])
		t.feed(commandKeys(0, 7))
		self.assertEqual(gestureIds(drv), ["br(eurobraille):l1+l8"])
		t.feed(pkt(b"T", b"L", b"ab"))
		self.assertEqual(t.writes[-1], pkt(b"T", b"L", b"ab"))

	def test_esytime_keys(self) -> None:
		drv, t = connectSimulated(EurobrailleDriver, serialResponder(0x0E, 32))
		t.feed(commandKeys(7))
		t.feed(commandKeys())
		self.assertEqual(gestureIds(drv), ["br(eurobraille):l8"])
		self.assertEqual(drv.lastGestures, [])
		t.feed(commandKeys(16))
		t.feed(commandKeys())
		g = drv.lastGestures[-1]
		self.assertEqual(g.identifiers[0], "br(eurobraille.esytime):joystick1up")

	def test_hid_input_reports(self) -> None:
		resp = HidResponder(0x08, 40)
		drv, t = connectSimulated(EurobrailleDriver, resp, matchType="hid", outputSize=HID_SIZE)
		drv.lastGestures.clear()
		# Paquete partido entre dos informes de 9 bytes, con relleno al final.
		stream = brailleKeys(1, 3, space=True) + pkt(b"K", b"I", bytes([1, 2]))
		for r in hidReports(stream, size=9):
			t.feed(r)
		self.assertEqual(gestureIds(drv), ["br(eurobraille):dot1+dot3+space", "br(eurobraille):routing"])


class HidKeyboardTests(unittest.TestCase):
	def test_toggle_over_hid(self) -> None:
		resp = HidResponder(0x08, 40)
		drv, t = connectSimulated(EurobrailleDriver, resp, matchType="hid", outputSize=HID_SIZE)
		with mock.patch.object(drv, "_message") as msg, mock.patch.object(eurobraille.queue_handler, "callLater"):
			t.feed(hidReports(commandKeys(1, 17))[0])  # switch1Left + joystick1Down
			t.feed(hidReports(commandKeys())[0])
			gesture = drv.lastGestures[-1]
			self.assertEqual(gestureIds(drv), ["br(eurobraille):joystick1down+switch1left"])
			# El gesto lo atiende la orden propia del controlador.
			func = drv.getScript(gesture)
			self.assertIsNotNone(func)
			self.assertEqual(func.__name__, "script_toggleHidKeyboardInput")
			func(gesture)
			self.assertTrue(any(p[3:5] == b"KU" and p[5:6] == b"1" for p in resp.packets))
			self.assertTrue(drv.hidKeyboardInput)
			msg.assert_called_once()
			self.assertIn("activada", msg.call_args[0][0])
			msg.reset_mock()
			drv.toggleHidKeyboardInput()
			self.assertFalse(drv.hidKeyboardInput)
			self.assertIn("desactivada", msg.call_args[0][0])
			# La línea no cambia de modo: no disponible.
			resp.hidMode = False
			msg.reset_mock()
			drv.toggleHidKeyboardInput()
			drv._hidToggleTimeout(True)
			self.assertIn("no está disponible", msg.call_args[0][0])

	def test_toggle_over_serial_unavailable(self) -> None:
		drv, t = connectSimulated(EurobrailleDriver, serialResponder(0x0E, 32))
		count = len(t.writes)
		with mock.patch.object(drv, "_message") as msg:
			t.feed(commandKeys(0, 17))  # l1 + joystick1Down
			t.feed(commandKeys())
			gesture = drv.lastGestures[-1]
			self.assertEqual(gestureIds(drv), ["br(eurobraille):joystick1down+l1"])
			drv.getScript(gesture)(gesture)
		self.assertEqual(len(t.writes), count)
		self.assertIn("no está disponible", msg.call_args[0][0])


class DetectionTests(unittest.TestCase):
	def test_matches(self) -> None:
		devs = [
			DeviceInfo("hid", "\\\\?\\hid#esys", usbId="VID_C251&PID_1123"),
			DeviceInfo("hid", "\\\\?\\hid#otro", usbId="VID_1234&PID_0001"),
			DeviceInfo("serial", "COM3", usbId="VID_28AC&PID_0021"),
			DeviceInfo("serial", "COM4", usbId="VID_0403&PID_6001"),
			DeviceInfo("serial", "COM7", bluetooth=True, bluetoothName="Esys 40 0123"),
			DeviceInfo("serial", "COM8", bluetooth=True, bluetoothName="Focus 40"),
		]
		matches = EurobrailleDriver.getMatches(devs)
		self.assertEqual([(m.type, m.port, m.bluetooth) for m in matches], [("hid", "\\\\?\\hid#esys", False), ("serial", "COM3", False), ("serial", "COM7", True)])
		self.assertEqual(len(EurobrailleDriver.getMatches(devs, allowGeneric=False)), 3)
		self.assertEqual(len(EurobrailleDriver.getMatches(devs, bluetooth=False)), 2)
		self.assertEqual(len(EurobrailleDriver.getMatches(devs, usb=False)), 1)

	def test_ids_uppercase(self) -> None:
		for i in EurobrailleDriver.usbHidIds | EurobrailleDriver.usbSerialIds:
			self.assertRegex(i, r"^VID_[0-9A-F]{4}&PID_[0-9A-F]{4}$")


class GestureMapTests(unittest.TestCase):
	def test_values_and_keys(self) -> None:
		known = {"routing", "doubleRouting", "space", "backSpace"} | set(EurobrailleDriver.dotKeys)
		for table in eurobraille.COMMAND_KEYS.values():
			known |= set(table.values())
		for keys, target in EurobrailleDriver.gestureMap.items():
			self.assertTrue(target.startswith("kb:") or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", target), target)
			parts = keys.split("+")
			for k in parts:
				self.assertIn(k, known, keys)
			# Nada de órdenes con solo puntos (sirven para escribir).
			self.assertFalse(all(p in EurobrailleDriver.dotKeys for p in parts), keys)
		# Las combinaciones de la orden propia (modo teclado HID) no están en el mapa global.
		mapped = {"+".join(sorted(k.lower().split("+"))) for k in EurobrailleDriver.gestureMap}
		for gid in eurobraille.HID_KEYBOARD_TOGGLE_GESTURES:
			keys = gid.split(":", 1)[1]
			self.assertNotIn("+".join(sorted(keys.lower().split("+"))), mapped)
			for k in keys.split("+"):
				self.assertIn(k, known)
		self.assertTrue(set(EurobrailleDriver.keyOrder) >= known - {"routing"})

	def test_build_packet(self) -> None:
		self.assertEqual(buildPacket(b"B", b"S", b"\x01"), b"\x02\x00\x05BS\x01\x03")
		self.assertEqual(buildPacket(b"S", b"I", frame=0x21), b"\x02\x00\x04SI\x21\x03")


if __name__ == "__main__":
	unittest.main()
