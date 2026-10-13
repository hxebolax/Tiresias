"""Pruebas del controlador de líneas braille con protocolo Baum (sin hardware)."""

from __future__ import annotations

import re
import unittest
from unittest import mock

import braille_sim  # noqa: F401
from braille_sim import connectSimulated, gestureIds

from tiresias.braille.drivers import baum, hwio
from tiresias.braille.drivers.baum import ALL_KEYS, BaumDriver
from tiresias.braille.drivers.base import DisplayNotFound
from tiresias.braille.drivers.ports import DeviceInfo

ESC = b"\x1b"


def frame(command: int, arg: bytes = b"") -> bytes:
	"""Trama serie tal como la enviaría la línea."""
	return ESC + bytes((command,)) + arg.replace(ESC, ESC * 2)


def deviceId(text: str, size: int = 16) -> bytes:
	return text.encode("latin-1").ljust(size, b"\0")


def serialResponder(ident: bytes, cells: int, serial: bytes = b"SN000001"):
	"""Línea serie que se identifica al activar el protocolo."""

	def respond(data: bytes):
		if data == frame(0x15, b"\x01"):
			return [frame(0x84, ident), frame(0x8A, serial), frame(0x01, bytes((cells,)))]
		return None

	return respond


def hidResponder(ident: bytes, cells: int, rejectProtocolOn: bool = False, padding: int = 0):
	"""Línea HID: los informes no llevan ESC; responde a la petición de información."""

	def respond(data: bytes):
		if data[:1] == b"\x15" and rejectProtocolOn:
			raise hwio.IoError(31, "informe no admitido")
		if data[:2] == b"\x02\x00":
			return [b"\x84" + ident + bytes(padding), b"\x01" + bytes((cells,)) + bytes(padding)]
		return None

	return respond


def connectSerial(ident: str = "VarioUltra 40", cells: int = 40, **kwargs):
	return connectSimulated(BaumDriver, responder=serialResponder(deviceId(ident), cells), **kwargs)


class FastWaits(unittest.TestCase):
	"""Acorta las esperas de la conexión para las pruebas que no reciben respuesta."""

	def setUp(self) -> None:
		patcher = mock.patch.multiple(baum, WAIT_IDENTIFY=0.05, WAIT_RETRY=0.05)
		patcher.start()
		self.addCleanup(patcher.stop)


class ConnectionTests(FastWaits):
	def test_serial_handshake(self) -> None:
		driver, transport = connectSerial("VarioUltra 40", 40, usbId="VID_0904&PID_2007")
		self.assertEqual(driver.numCells, 40)
		self.assertEqual(driver.model, "VarioUltra40")
		self.assertEqual(driver.deviceName, "VarioUltra 40")
		self.assertEqual(driver.serialNumber, "SN000001")
		# Desactivar y activar dos veces el protocolo.
		self.assertEqual(transport.writes[:3], [b"\x1b\x15\x00", b"\x1b\x15\x01", b"\x1b\x15\x01"])
		self.assertEqual(transport.baudrate, 19200)
		self.assertEqual(transport.openArgs.get("parity"), "N")

	def test_refreshabraille_id_byte_by_byte(self) -> None:
		ident = b"Refreshabraille 18"
		stream = b"\x07" + frame(0x84, ident) + frame(0x01, b"\x12")

		def respond(data: bytes):
			if data == frame(0x15, b"\x01"):
				return [bytes((b,)) for b in stream]
			return None

		driver, _t = connectSimulated(BaumDriver, responder=respond, usbId="VID_0904&PID_3000")
		self.assertEqual(driver.numCells, 18)
		self.assertEqual(driver.deviceName, "Refreshabraille 18")
		self.assertEqual(driver.model, "Refreshabraille18")

	def test_serial_unknown_command_and_garbage_resync(self) -> None:
		# Basura, un comando desconocido (0x60) con un ESC duplicado en sus datos, y la identificación.
		stream = b"\xff\x00" + ESC + b"\x60\x01" + ESC * 2 + b"\x02" + frame(0x84, deviceId("SuperVario 40")) + frame(0x01, b"\x28")

		def respond(data: bytes):
			if data == frame(0x15, b"\x01"):
				return [stream[:3], stream[3:9], stream[9:]]
			return None

		driver, _t = connectSimulated(BaumDriver, responder=respond, usbId="VID_0403&PID_FE72")
		self.assertEqual(driver.numCells, 40)
		self.assertEqual(driver.model, "SuperVario40")

	def test_serial_request_info_retry(self) -> None:
		def respond(data: bytes):
			if data == frame(0x02, b"\x00"):
				return [frame(0x84, deviceId("EcoVario 24")), frame(0x01, b"\x18")]
			return None

		driver, transport = connectSimulated(BaumDriver, responder=respond, usbId="VID_0904&PID_2001")
		self.assertEqual(driver.numCells, 24)
		self.assertEqual(driver.model, "EcoVario24")
		self.assertIn(b"\x1b\x02\x00", transport.writes)

	def test_hid_handshake(self) -> None:
		driver, transport = connectSimulated(BaumDriver, responder=hidResponder(deviceId("Orbit Reader 20"), 20, padding=4), matchType="hid", port="hidpath", usbId="VID_0483&PID_A1D3")
		self.assertEqual(driver.numCells, 20)
		self.assertEqual(driver.model, "OrbitReader20")
		self.assertEqual(driver.deviceName, "Orbit Reader 20")
		self.assertEqual(transport.writes[:2], [b"\x15\x01", b"\x02\x00"])

	def test_hid_protocol_on_rejected(self) -> None:
		# La Pronto! y la VarioUltra rechazan el informe de activar el protocolo.
		driver, transport = connectSimulated(BaumDriver, responder=hidResponder(deviceId("Pronto! V4 40"), 40, rejectProtocolOn=True), matchType="hid", port="hidpath", usbId="VID_0904&PID_4008")
		self.assertEqual(driver.numCells, 40)
		self.assertEqual(driver.model, "ProntoV440")
		self.assertEqual(driver.deviceName, "Pronto! V4 40")

	def test_hid_refreshabraille(self) -> None:
		driver, _t = connectSimulated(BaumDriver, responder=hidResponder(b"Refreshabraille 18", 18), matchType="hid", port="hidpath", usbId="VID_0904&PID_3001")
		self.assertEqual(driver.model, "Refreshabraille18")

	def test_cells_without_id(self) -> None:
		def respond(data: bytes):
			return frame(0x01, b"\x20") if data == frame(0x15, b"\x01") else None

		driver, _t = connectSimulated(BaumDriver, responder=respond, usbId="VID_0904&PID_2008")
		self.assertEqual(driver.numCells, 32)
		self.assertEqual(driver.model, "")
		self.assertEqual(driver.deviceName, "Baum")

	def test_no_answer(self) -> None:
		with self.assertRaises(DisplayNotFound):
			connectSimulated(BaumDriver, responder=lambda d: None, usbId="VID_0904&PID_2002")

	def test_known_baum_does_not_try_zoomax(self) -> None:
		written = []

		def respond(data: bytes):
			written.append(data)

		with self.assertRaises(DisplayNotFound):
			connectSimulated(BaumDriver, responder=respond, usbId="VID_0904&PID_2002")
		self.assertNotIn(frame(0x15, b"\x03"), written)

	def test_zoomax_bluetooth(self) -> None:
		def respond(data: bytes):
			if data == frame(0x08):
				return frame(0x01, b"\x14")
			return None

		driver, transport = connectSimulated(BaumDriver, responder=respond, bluetooth=True, name="NLS eReader Zoomax")
		self.assertEqual(transport.writes[:2], [b"\x1b\x15\x03", b"\x1b\x08"])
		self.assertEqual(driver.numCells, 20)
		self.assertEqual(driver.model, "NLSeReaderZoomax")
		self.assertEqual(driver.deviceName, "NLS eReader Zoomax")
		# b11 es la tercera barra espaciadora.
		transport.feed(frame(0x33, b"\x04\x01"))
		transport.feed(frame(0x33, b"\x00\x00"))
		g = driver.lastGestures[-1]
		self.assertEqual(g.identifiers, ["br(baum.nlsereaderzoomax):b1+b11", "br(baum):b1+b11"])
		self.assertTrue(g.space)
		self.assertEqual(g.dots, 1)
		self.assertIn("b11+b1", BaumDriver.modelGestureMaps["NLSeReaderZoomax"])
		driver.terminate()
		self.assertNotIn(b"\x1b\x15\x00", transport.writes[2:])

	def test_manual_port_falls_back_to_zoomax(self) -> None:
		def respond(data: bytes):
			return frame(0x01, b"\x14") if data == frame(0x08) else None

		driver, transport = connectSimulated(BaumDriver, responder=respond, port="COM4")
		self.assertEqual(transport.writes[0], b"\x1b\x15\x00")
		self.assertIn(b"\x1b\x15\x03", transport.writes)
		self.assertEqual(driver.model, "NLSeReaderZoomax")

	def test_goodbye(self) -> None:
		driver, transport = connectSerial("Vario 40", 40, usbId="VID_0403&PID_FE70")
		driver.terminate()
		self.assertEqual(transport.writes[-2], b"\x1b\x01" + bytes(40))
		self.assertEqual(transport.writes[-1], b"\x1b\x15\x00")


class OutputTests(FastWaits):
	def test_serial_cells_escaped(self) -> None:
		driver, transport = connectSerial("VarioUltra 20", 20, usbId="VID_0904&PID_2009")
		driver.display([0x01, 0x1B, 0xFF, 0x1B])
		self.assertEqual(transport.writes[-1], b"\x1b\x01" + b"\x01\x1b\x1b\xff\x1b\x1b" + bytes(16))

	def test_hid_cells(self) -> None:
		driver, transport = connectSimulated(BaumDriver, responder=hidResponder(deviceId("VarioUltra 20"), 20), matchType="hid", port="hidpath", usbId="VID_0904&PID_6101")
		driver.display([0x1B] * 3)
		self.assertEqual(transport.writes[-1], b"\x01" + b"\x1b" * 3 + bytes(17))


class InputTests(FastWaits):
	def setUp(self) -> None:
		super().setUp()
		self.driver, self.transport = connectSerial("VarioUltra 40", 40, usbId="VID_0904&PID_2007")

	def feed(self, *frames: bytes) -> None:
		for f in frames:
			self.transport.feed(f)

	def test_display_key(self) -> None:
		self.feed(frame(0x24, b"\x02"), frame(0x24, b"\x00"))
		self.assertEqual(gestureIds(self.driver), ["br(baum):d2"])

	def test_display_key_combination(self) -> None:
		self.feed(frame(0x24, b"\x02"), frame(0x24, b"\x12"), frame(0x24, b"\x10"), frame(0x24, b"\x00"))
		self.assertEqual(gestureIds(self.driver), ["br(baum):d2+d5"])

	def test_model_identifier(self) -> None:
		self.feed(frame(0x24, b"\x01"), frame(0x24, b"\x00"))
		self.assertEqual(self.driver.lastGestures[-1].identifiers, ["br(baum.varioultra40):d1", "br(baum):d1"])

	def test_braille_input_with_space(self) -> None:
		# b9 (bit 0 del primer byte) + puntos 1 y 3 (segundo byte).
		self.feed(frame(0x33, b"\x01\x05"), frame(0x33, b"\x00\x00"))
		g = self.driver.lastGestures[-1]
		self.assertEqual(gestureIds(self.driver), ["br(baum):b1+b3+b9"])
		self.assertEqual(g.dots, 0b101)
		self.assertTrue(g.space)

	def test_braille_dots_only(self) -> None:
		self.feed(frame(0x33, b"\x00\x81"), frame(0x33, b"\x00\x00"))
		g = self.driver.lastGestures[-1]
		self.assertEqual(g.identifiers[-1], "br(baum):b1+b8")
		self.assertEqual(g.dots, 0x81)
		self.assertFalse(g.space)

	def test_command_keys_are_not_braille_input(self) -> None:
		self.feed(frame(0x33, b"\x10\x01"), frame(0x33, b"\x00\x00"))
		g = self.driver.lastGestures[-1]
		self.assertEqual(g.identifiers[-1], "br(baum):b1+c1")
		self.assertEqual(g.dots, 0)
		self.assertFalse(g.space)

	def test_escaped_key_data(self) -> None:
		# Primer byte 0x1B = b9, b10, (bit 3) y c1: va duplicado en la trama.
		self.transport.feed(b"\x1b\x33\x1b\x1b\x00")
		self.transport.feed(frame(0x33, b"\x00\x00"))
		self.assertEqual(gestureIds(self.driver), ["br(baum):b10+b9+c1"])

	def test_c_keys(self) -> None:
		for bit, name in ((0x10, "c1"), (0x20, "c2"), (0x40, "c3"), (0x80, "c4"), (0x02, "b10"), (0x04, "b11")):
			self.feed(frame(0x33, bytes((bit, 0))), frame(0x33, b"\x00\x00"))
			self.assertEqual(gestureIds(self.driver), [f"br(baum):{name}"])

	def test_joystick(self) -> None:
		for bit, name in ((1, "up"), (2, "left"), (4, "down"), (8, "right"), (16, "select")):
			self.feed(frame(0x34, bytes((bit,))), frame(0x34, b"\x00"))
			self.assertEqual(gestureIds(self.driver), [f"br(baum):{name}"])

	def test_routing_bitmask(self) -> None:
		# Tecla 18 (índice 17): byte 2, bit 1.
		self.feed(frame(0x22, b"\x00\x00\x02\x00\x00"), frame(0x22, bytes(5)))
		g = self.driver.lastGestures[-1]
		self.assertEqual(gestureIds(self.driver), ["br(baum):routing"])
		self.assertEqual(g.routingIndex, 17)

	def test_multi_routing_bitmask(self) -> None:
		self.feed(frame(0x22, b"\x01\x00\x00\x00\x80"), frame(0x22, bytes(5)))
		g = self.driver.lastGestures[-1]
		self.assertEqual(g.identifiers[-1], "br(baum):multirouting")
		self.assertEqual(g.routingIndexes, [0, 39])

	def test_single_routing_key(self) -> None:
		self.feed(frame(0x27, b"\x05"), frame(0x27, b"\x00"))
		g = self.driver.lastGestures[-1]
		self.assertEqual(gestureIds(self.driver), ["br(baum):routing"])
		self.assertEqual(g.routingIndex, 4)
		self.feed(frame(0x27, b"\x03"), frame(0x27, b"\x07"), frame(0x27, b"\x00"))
		self.assertEqual(self.driver.lastGestures[-1].routingIndexes, [2, 6])

	def test_display_key_with_routing(self) -> None:
		self.feed(frame(0x24, b"\x02"), frame(0x22, b"\x04\x00\x00\x00\x00"), frame(0x22, bytes(5)), frame(0x24, b"\x00"))
		g = self.driver.lastGestures[-1]
		self.assertEqual(gestureIds(self.driver), ["br(baum):d2+routing"])
		self.assertEqual(g.routingIndex, 2)

	def test_byte_by_byte_stream(self) -> None:
		stream = frame(0x33, b"\x02\x09") + frame(0x33, b"\x00\x00") + frame(0x34, b"\x08") + frame(0x34, b"\x00")
		for b in stream:
			self.transport.feed(bytes((b,)))
		self.assertEqual(gestureIds(self.driver), ["br(baum):b1+b10+b4", "br(baum):right"])

	def test_cut_frame_resync(self) -> None:
		# Trama de teclas braille cortada tras un byte; la siguiente se entiende.
		self.transport.feed(b"\x1b\x33\x01" + frame(0x34, b"\x01") + frame(0x34, b"\x00"))
		self.assertEqual(gestureIds(self.driver), ["br(baum):up"])

	def test_cell_count_change(self) -> None:
		self.feed(frame(0x01, b"\x50"))
		self.assertEqual(self.driver.numCells, 80)


class WideDisplayTests(FastWaits):
	def test_routing_10_bytes(self) -> None:
		driver, transport = connectSerial("SuperVario 80", 80, usbId="VID_0403&PID_FE75")
		mask = bytearray(10)
		mask[8] = 0x40  # índice 70
		transport.feed(frame(0x22, bytes(mask)))
		transport.feed(frame(0x22, bytes(10)))
		g = driver.lastGestures[-1]
		self.assertEqual(gestureIds(driver), ["br(baum):routing"])
		self.assertEqual(g.routingIndex, 70)

	def test_hid_routing_and_keys(self) -> None:
		driver, transport = connectSimulated(BaumDriver, responder=hidResponder(deviceId("VarioUltra 40"), 40), matchType="hid", port="hidpath", usbId="VID_0904&PID_6102")
		transport.feed(b"\x22\x00\x01\x00\x00\x00" + bytes(10))
		transport.feed(b"\x22" + bytes(15))
		transport.feed(b"\x33\x01\x02" + bytes(4))
		transport.feed(b"\x33\x00\x00" + bytes(4))
		self.assertEqual(gestureIds(driver), ["br(baum):routing", "br(baum):b2+b9"])


class OldModelTests(FastWaits):
	"""Teclas y sensores de los modelos antiguos (Inka, DM80P, Vario)."""

	def setUp(self) -> None:
		super().setUp()
		self.driver, self.transport = connectSerial("Vario 40", 40, usbId="VID_0403&PID_FE70")

	def press(self, command: int, down: bytes, up: bytes) -> list[str]:
		self.transport.feed(frame(command, down))
		self.transport.feed(frame(command, up))
		return gestureIds(self.driver)

	def test_horizontal_sensors_mask(self) -> None:
		self.assertEqual(self.press(0x20, b"\x00\x08\x00\x00\x00", bytes(5)), ["br(baum):routing2"])
		self.transport.feed(frame(0x20, b"\x00\x08\x00\x00\x00"))
		self.transport.feed(frame(0x20, bytes(5)))
		self.assertEqual(self.driver.lastGestures[-1].routingIndex, 11)

	def test_horizontal_sensor_single(self) -> None:
		self.transport.feed(frame(0x25, b"\x03"))
		self.transport.feed(frame(0x25, b"\x00"))
		g = self.driver.lastGestures[-1]
		self.assertEqual(gestureIds(self.driver), ["br(baum):routing2"])
		self.assertEqual(g.routingIndex, 2)

	def test_routing_and_sensor_rows_together(self) -> None:
		self.transport.feed(frame(0x22, b"\x01\x00\x00\x00\x00"))
		self.transport.feed(frame(0x25, b"\x02"))
		self.transport.feed(frame(0x22, bytes(5)))
		self.assertEqual(gestureIds(self.driver), ["br(baum):routing+routing2"])

	def test_vertical_sensors(self) -> None:
		self.assertEqual(self.press(0x21, b"\x04\x00\x00\x00", bytes(4)), ["br(baum):verticalsensor3"])
		# Un sensor suelto: el bit 0x40 (lado) no cambia el nombre.
		self.assertEqual(self.press(0x26, b"\x41", b"\x00"), ["br(baum):verticalsensor1"])

	def test_front_back_command_keys(self) -> None:
		self.assertEqual(self.press(0x28, b"\x02", b"\x00"), ["br(baum):front2"])
		self.assertEqual(self.press(0x29, b"\x20", b"\x00"), ["br(baum):back6"])
		self.assertEqual(self.press(0x2C, b"\x00\x02", b"\x00\x00"), ["br(baum):front10"])
		self.assertEqual(self.press(0x2D, b"\x01\x00", b"\x00\x00"), ["br(baum):back1"])
		self.assertEqual(self.press(0x2B, b"\x01", b"\x00"), ["br(baum):command1"])

	def test_ignored_frames_keep_sync(self) -> None:
		stream = frame(0x40, b"\x05") + frame(0x23, b"\x01") + frame(0x11, b"\x01\x1b") + frame(0x8C, b"Baum Vario 40\0") + frame(0x24, b"\x01") + frame(0x24, b"\x00")
		for b in stream:
			self.transport.feed(bytes((b,)))
		self.assertEqual(gestureIds(self.driver), ["br(baum):d1"])


def moduleFrame(command: int, body: bytes) -> bytes:
	"""Trama de módulo de la VarioPro: longitud + cuerpo."""
	return frame(command, bytes((len(body),)) + body)


DISPLAY80 = b"\x80\x41\x01\x00"  # módulo 0x4180, serie 1
STATUS = b"\x20\x42\x02\x00"  # módulo 0x4220, serie 2


def registers(module: bytes, values: bytes, start: int = 0) -> bytes:
	return module + bytes((0x00, start, len(values))) + values


class VarioProTests(FastWaits):
	def setUp(self) -> None:
		super().setUp()

		def respond(data: bytes):
			if data == frame(0x15, b"\x01"):
				return [frame(0x84, deviceId("VarioPro 80")), moduleFrame(0x50, DISPLAY80 + b"\x01"), moduleFrame(0x50, STATUS + b"\x01")]
			return None

		self.driver, self.transport = connectSimulated(BaumDriver, responder=respond, usbId="VID_0403&PID_FE76")

	def test_registration(self) -> None:
		self.assertEqual(self.driver.numCells, 80)
		self.assertEqual(self.driver.model, "VarioPro80")
		self.assertIn(b"\x1b\x50\x05" + DISPLAY80 + b"\x01", self.transport.writes)
		self.assertIn(b"\x1b\x50\x05" + STATUS + b"\x01", self.transport.writes)

	def test_cells_through_display_module(self) -> None:
		self.driver.display([0x1B, 0x01])
		cells = b"\x1b\x01" + bytes(78)
		body = DISPLAY80 + b"\x00\x00" + bytes((80,)) + cells
		self.assertEqual(self.transport.writes[-1], b"\x1b\x51" + bytes((len(body),)) + body.replace(ESC, ESC * 2))

	def test_display_keys(self) -> None:
		self.transport.feed(moduleFrame(0x51, registers(DISPLAY80, b"\x04\x00\x00\x00\x00\x00\x02")))
		self.transport.feed(moduleFrame(0x51, registers(DISPLAY80, b"\x04\x00\x00\x00\x00\x00\x00")))
		g = self.driver.lastGestures[-1]
		self.assertEqual(g.identifiers, ["br(baum.variopro80):d2", "br(baum):d2"])

	def test_wheels(self) -> None:
		# Rueda 2: -2 pasos (hacia arriba); rueda 4: +1 (hacia abajo).
		self.transport.feed(moduleFrame(0x51, registers(DISPLAY80, b"\x01\x00\xfe\x00\x01")))
		self.assertEqual(gestureIds(self.driver), ["br(baum):wheel2up", "br(baum):wheel2up", "br(baum):wheel4down"])
		# Sin el indicador de ruedas no se repiten los pasos.
		self.transport.feed(moduleFrame(0x51, registers(DISPLAY80, b"\x04\x00\xfe\x00\x01\x00\x00")))
		self.assertEqual(gestureIds(self.driver), [])

	def test_wheel_press(self) -> None:
		self.transport.feed(moduleFrame(0x51, registers(DISPLAY80, b"\x02\x00\x00\x00\x00\x01")))
		self.transport.feed(moduleFrame(0x51, registers(DISPLAY80, b"\x02\x00\x00\x00\x00\x00")))
		self.assertEqual(gestureIds(self.driver), ["br(baum):wheel1press"])

	def test_sensors_with_escaped_length(self) -> None:
		# 20 registros: la longitud del cuerpo es 27 (0x1B) y va duplicada.
		values = bytearray(20)
		values[0] = 0x08
		values[7 + 1] = 0x10  # índice 12
		data = moduleFrame(0x51, registers(DISPLAY80, bytes(values)))
		self.assertEqual(data[:4], b"\x1b\x51\x1b\x1b")
		for b in data:
			self.transport.feed(bytes((b,)))
		values[7 + 1] = 0
		self.transport.feed(moduleFrame(0x51, registers(DISPLAY80, bytes(values))))
		g = self.driver.lastGestures[-1]
		self.assertEqual(gestureIds(self.driver), ["br(baum):routing"])
		self.assertEqual(g.routingIndex, 12)

	def test_sensors_from_offset(self) -> None:
		# Solo los registros de sensores, sin los indicadores.
		self.transport.feed(moduleFrame(0x51, registers(DISPLAY80, b"\x01\x00", start=7)))
		self.transport.feed(moduleFrame(0x51, registers(DISPLAY80, b"\x00\x00", start=7)))
		self.assertEqual(self.driver.lastGestures[-1].routingIndex, 0)

	def test_status_keys(self) -> None:
		self.transport.feed(moduleFrame(0x51, registers(STATUS, b"\x02\x04")))
		self.transport.feed(moduleFrame(0x51, registers(STATUS, b"\x02\x00")))
		self.assertEqual(gestureIds(self.driver), ["br(baum):statuskey3"])

	def test_display_key_with_status_key(self) -> None:
		self.transport.feed(moduleFrame(0x51, registers(STATUS, b"\x02\x01")))
		self.transport.feed(moduleFrame(0x51, registers(DISPLAY80, b"\x04\x00\x00\x00\x00\x00\x01")))
		self.transport.feed(moduleFrame(0x51, registers(STATUS, b"\x02\x00")))
		self.assertEqual(gestureIds(self.driver), ["br(baum):d1+statuskey1"])

	def test_module_removal(self) -> None:
		self.transport.feed(moduleFrame(0x50, DISPLAY80 + b"\x02"))
		self.driver.display([1])
		self.assertEqual(self.transport.writes[-1], b"\x1b\x01\x01" + bytes(79))

	def test_hid_module_report(self) -> None:
		driver, transport = connectSimulated(BaumDriver, responder=hidResponder(deviceId("VarioPro 64"), 64), matchType="hid", port="hidpath")
		body = registers(b"\x40\x41\x05\x00", b"\x04\x00\x00\x00\x00\x00\x20")
		transport.feed(b"\x51" + bytes((len(body),)) + body + bytes(8))
		transport.feed(b"\x51" + bytes((len(body),)) + body[:-1] + b"\x00" + bytes(8))
		self.assertEqual(gestureIds(driver), ["br(baum):d6"])


class DetectionTests(unittest.TestCase):
	def test_matches(self) -> None:
		devs = [
			DeviceInfo("hid", r"\\?\hid#vu", usbId="VID_0904&PID_6101"),
			DeviceInfo("hid", r"\\?\hid#orbit", usbId="VID_0483&PID_A366"),
			DeviceInfo("hid", r"\\?\hid#otro", usbId="VID_1234&PID_5678"),
			DeviceInfo("serial", "COM3", usbId="VID_0403&PID_FE72"),
			DeviceInfo("serial", "COM4", usbId="VID_0904&PID_2002"),
			DeviceInfo("serial", "COM5", usbId="VID_1A86&PID_7523"),
			DeviceInfo("serial", "COM6", usbId="VID_0403&PID_6001"),
			DeviceInfo("serial", "COM7", bluetooth=True, bluetoothName="Pronto! 18 V4"),
			DeviceInfo("serial", "COM8", bluetooth=True, bluetoothName="Orbit Reader 20 1234"),
			DeviceInfo("serial", "COM9", bluetooth=True, bluetoothName="NLS eReader Zoomax"),
			DeviceInfo("serial", "COM10", bluetooth=True, bluetoothName="Focus 40 BT"),
			DeviceInfo("serial", "COM11", bluetooth=True, bluetoothName="Baum SuperVario 40"),
		]
		ports = [m.port for m in BaumDriver.getMatches(devs, allowGeneric=False)]
		self.assertEqual(ports, [r"\\?\hid#vu", r"\\?\hid#orbit", "COM3", "COM4", "COM7", "COM8", "COM9", "COM11"])
		withGeneric = [m.port for m in BaumDriver.getMatches(devs, allowGeneric=True)]
		self.assertIn("COM5", withGeneric)
		self.assertNotIn("COM6", withGeneric)
		usbOnly = BaumDriver.getMatches(devs, bluetooth=False, allowGeneric=False)
		self.assertEqual([m.type for m in usbOnly], ["hid", "hid", "serial", "serial"])
		bt = BaumDriver.getMatches(devs, usb=False)
		self.assertTrue(all(m.bluetooth for m in bt))
		self.assertEqual(bt[0].id, "Pronto! 18 V4")

	def test_bluetooth_hid(self) -> None:
		dev = DeviceInfo("hid", r"\\?\hid#bt", bluetooth=True, bluetoothName="VarioUltra 40")
		m = BaumDriver.matchDevice(dev)
		self.assertIsNotNone(m)
		self.assertEqual((m.type, m.bluetooth), ("hid", True))


class GestureMapTests(unittest.TestCase):
	def test_values(self) -> None:
		ident = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
		maps = [BaumDriver.gestureMap, *BaumDriver.modelGestureMaps.values()]
		for gmap in maps:
			for keys, target in gmap.items():
				self.assertTrue(target.startswith("kb:") or ident.match(target), (keys, target))

	def test_keys_exist(self) -> None:
		known = set(ALL_KEYS) | {"routing", "multiRouting", "routing2", "multiRouting2"}
		maps = [BaumDriver.gestureMap, *BaumDriver.modelGestureMaps.values()]
		for gmap in maps:
			for keys in gmap:
				for key in keys.split("+"):
					self.assertIn(key, known, keys)
		self.assertEqual(set(BaumDriver.keyOrder), set(ALL_KEYS))
		for key in known:
			self.assertIn(key, BaumDriver.keyDescriptions)

	def test_no_dot_only_commands(self) -> None:
		dots = set(BaumDriver.dotKeys)
		for keys in BaumDriver.gestureMap:
			self.assertFalse(set(keys.split("+")) <= dots, keys)

	def test_both_space_bars(self) -> None:
		self.assertEqual(BaumDriver.gestureMap["b9+b1+b5"], "kb:escape")
		self.assertEqual(BaumDriver.gestureMap["b10+b1+b5"], "kb:escape")
		self.assertEqual(BaumDriver.gestureMap["b9+b8"], "kb:enter")


if __name__ == "__main__":
	unittest.main()
