"""Pruebas del controlador BRLTTY (protocolo BrlAPI propio) con un servidor simulado."""

from __future__ import annotations

import socket
import struct
import threading
import time
import unittest
from unittest import mock

import braille_sim  # noqa: F401
from braille_sim import connectSimulated, gestureIds

from tiresias.braille.drivers import base
from tiresias.braille.drivers import brltty as bt
from tiresias.braille.drivers.brltty import BrlttyDriver
from tiresias.braille.drivers.ports import DeviceInfo


def pkt(ptype: str, data: bytes = b"") -> bytes:
	return struct.pack(">II", len(data), ord(ptype)) + data


def keyPkt(code: int) -> bytes:
	return pkt("k", struct.pack(">Q", code))


def cmd(block: int, arg: int = 0, flags: int = 0) -> bytes:
	return keyPkt((flags << 32) | 0x20000000 | (block << 16) | arg)


def sym(code: int, flags: int = 0) -> bytes:
	return keyPkt((flags << 32) | code)


def errorPkt(code: int, ptype: str) -> bytes:
	return pkt("e", struct.pack(">II", code, ord(ptype)))


VERSION = pkt("v", b"\x00\x00\x00\x08")
ENTER_TTY = pkt("t", b"\x00\x00\x00\x00\x00")


class FakeBrltty:
	"""Servidor BrlAPI simulado: contesta a cada paquete del cliente."""

	def __init__(self, auth=("N",), key=b"", columns=40, rows=1, driver=b"FreedomScientific", model=b"Focus 40", version=8, modelError=False):
		self.auth = auth
		self.key = key
		self.columns = columns
		self.rows = rows
		self.driver = driver
		self.model = model
		self.version = version
		self.modelError = modelError
		self.packets: list[tuple[str, bytes]] = []

	def __call__(self, data: bytes):
		size, ptype = struct.unpack(">II", data[:8])
		payload = data[8 : 8 + size]
		assert len(payload) == size, "paquete incompleto"
		t = chr(ptype)
		self.packets.append((t, payload))
		if t == "v":
			methods = b"".join(struct.pack(">I", ord(a)) for a in self.auth)
			return [pkt("v", struct.pack(">I", self.version)), pkt("a", methods)]
		if t == "a":
			method = struct.unpack(">I", payload[:4])[0]
			if method == ord("K") and payload[4:] == self.key:
				return pkt("A")
			return errorPkt(0x11, "a")
		if t == "n":
			return pkt("n", self.driver + b"\x00")
		if t == "s":
			return pkt("s", struct.pack(">II", self.columns, self.rows))
		if t == "d":
			return errorPkt(0x04, "d") if self.modelError else pkt("d", self.model + b"\x00")
		if t in "twL":
			return pkt("A")
		return errorPkt(0x04, t)


def connect(server=None, **kw):
	server = server or FakeBrltty(**kw)
	drv, t = connectSimulated(BrlttyDriver, server, matchType="socket", port="127.0.0.1:4101", name="brltty")
	return drv, t, server


def expectedWrite(cells: list[int]) -> bytes:
	"""Paquete 'w' escrito a mano: región, texto UTF-8, máscaras, cursor y juego de caracteres."""
	n = len(cells)
	text = "".join(chr(0x2800 + c) for c in cells).encode("utf-8")
	payload = struct.pack(">I", 0x7E) + struct.pack(">II", 1, n) + struct.pack(">I", len(text)) + text
	payload += bytes(n) + bytes(cells) + b"\x00\x00\x00\x00" + b"\x05UTF-8"
	return pkt("w", payload)


#: Escritura de los puntos [1, 2, 3] en una línea de 40 celdas capturada de
#: libbrlapi 0.8.7 (``writeDots``); la biblioteca envía el tamaño de región en
#: negativo (-40 = 0xffffffd8), Tiresias lo envía en positivo.
LIBBRLAPI_WRITE = bytes.fromhex(
	"0000007e00000001ffffffd800000078e2a081e2a082e2a083"
	+ "e2a080" * 37
	+ "00" * 40
	+ "010203"
	+ "00" * 37
	+ "0000000005"
	+ "5554462d38"
)


class ConnectionTests(unittest.TestCase):
	def test_handshake(self) -> None:
		drv, t, srv = connect()
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(drv.model, "FreedomScientific")
		self.assertEqual(drv.driverName, "FreedomScientific")
		self.assertEqual(drv.modelId, "Focus 40")
		self.assertEqual(drv.deviceName, "BRLTTY: FreedomScientific Focus 40")
		self.assertEqual(t.writes, [VERSION, pkt("n"), pkt("s"), pkt("d"), ENTER_TTY])
		match = t.opened[0][0]
		self.assertEqual((match.type, match.port), ("socket", "127.0.0.1:4101"))

	def test_key_authentication(self) -> None:
		with mock.patch.object(bt, "readAuthKey", return_value=b"secreto\n"):
			drv, t, srv = connect(auth=("K",), key=b"secreto\n")
		self.assertEqual(t.writes[1], pkt("a", b"\x00\x00\x00K" + b"secreto\n"))
		self.assertEqual(drv.numCells, 40)

	def test_none_listed_after_key(self) -> None:
		# Si el servidor acepta «sin autenticación» no se envía ninguna clave.
		drv, t, srv = connect(auth=("K", "N"))
		self.assertNotIn("a", [p[0] for p in srv.packets])
		self.assertEqual(drv.numCells, 40)

	def test_bad_key_fails(self) -> None:
		with mock.patch.object(bt, "readAuthKey", return_value=b"otra"):
			with self.assertRaises(base.DisplayNotFound):
				connect(auth=("K",), key=b"secreto")

	def test_no_key_file_fails(self) -> None:
		with mock.patch.object(bt, "readAuthKey", return_value=None):
			with self.assertRaises(base.DisplayNotFound):
				connect(auth=("K",), key=b"secreto")

	def test_credentials_method(self) -> None:
		class Server(FakeBrltty):
			def __call__(self, data):
				if data[4:8] == b"\x00\x00\x00a" and data[8:12] == b"\x00\x00\x00C":
					self.packets.append(("a", data[8:]))
					return pkt("A")
				return super().__call__(data)

		drv, t, srv = connect(Server(auth=("C",)))
		self.assertEqual(t.writes[1], pkt("a", b"\x00\x00\x00C"))
		self.assertEqual(drv.numCells, 40)

	def test_version_mismatch(self) -> None:
		with self.assertRaises(base.DisplayNotFound):
			connect(version=7)

	def test_no_display(self) -> None:
		with self.assertRaises(base.DisplayNotFound):
			connect(columns=0)

	def test_no_answer(self) -> None:
		with mock.patch.object(bt, "REPLY_TIMEOUT", 0.05):
			with self.assertRaises(base.DisplayNotFound):
				connectSimulated(BrlttyDriver, lambda d: None, matchType="socket", port="127.0.0.1:4101")

	def test_model_unknown_to_old_server(self) -> None:
		drv, t, srv = connect(modelError=True, driver=b"HandyTech")
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(drv.modelId, "")
		self.assertEqual(drv.deviceName, "BRLTTY: HandyTech")

	def test_two_rows(self) -> None:
		drv, t, srv = connect(columns=20, rows=2)
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(drv.numRows, 2)

	def test_replies_split_byte_by_byte(self) -> None:
		inner = FakeBrltty()

		def responder(data):
			reply = inner(data)
			chunks = b"".join(reply if isinstance(reply, list) else [reply])
			return [bytes((b,)) for b in chunks]

		drv, t, srv = connect(responder)
		self.assertEqual(drv.numCells, 40)


class OutputTests(unittest.TestCase):
	def test_write_cells(self) -> None:
		drv, t, srv = connect(columns=12)
		drv.display([0x01, 0xFF, 0x80])
		self.assertEqual(t.writes[-1], expectedWrite([0x01, 0xFF, 0x80] + [0] * 9))

	def test_matches_libbrlapi(self) -> None:
		drv, t, srv = connect()
		drv.display([1, 2, 3])
		ours = t.writes[-1][8:]
		self.assertEqual(t.writes[-1][:8], struct.pack(">II", len(LIBBRLAPI_WRITE), ord("w")))
		self.assertEqual(ours[:8], LIBBRLAPI_WRITE[:8])
		self.assertEqual(struct.unpack(">I", ours[8:12])[0], 40)
		self.assertEqual(ours[12:], LIBBRLAPI_WRITE[12:])

	def test_write_acks_ignored(self) -> None:
		drv, t, srv = connect()
		for _i in range(3):
			drv.display([7])
		self.assertEqual(drv._replies, [])
		self.assertEqual(drv.numCells, 40)

	def test_terminate_leaves_tty_mode(self) -> None:
		drv, t, srv = connect(columns=4)
		drv.terminate()
		self.assertEqual(t.writes[-2:], [expectedWrite([0, 0, 0, 0]), pkt("L")])
		self.assertTrue(t.closed)

	def test_disconnect(self) -> None:
		drv, t, srv = connect()
		with mock.patch.object(bt.queue_handler, "queueFunction"):
			t.fail(0)
		self.assertFalse(drv.connected)


class InputTests(unittest.TestCase):
	def setUp(self) -> None:
		self.drv, self.t, _srv = connect()

	def ids(self):
		return gestureIds(self.drv)

	def test_simple_commands(self) -> None:
		for code in (0x01, 0x02, 0x17, 0x18, 0x09, 0x0A, 0x1D, 0x33, 0x34, 0x51, 0x3F):
			self.t.feed(cmd(0, code))
		self.assertEqual(
			self.ids(),
			[
				"br(brltty):lnup",
				"br(brltty):lndn",
				"br(brltty):fwinlt",
				"br(brltty):fwinrt",
				"br(brltty):top",
				"br(brltty):bot",
				"br(brltty):home",
				"br(brltty):learn",
				"br(brltty):prefmenu",
				"br(brltty):time",
				"br(brltty):say_line",
			],
		)

	def test_model_identifier(self) -> None:
		self.t.feed(cmd(0, 0x17))
		self.assertEqual(self.drv.lastGestures[-1].identifiers[0], "br(brltty.freedomscientific):fwinlt")

	def test_toggle_flags_ignored(self) -> None:
		self.t.feed(cmd(0, 0x28, flags=0x0100))  # CSRTRK con TOGGLE_ON
		self.assertEqual(self.ids(), ["br(brltty):csrtrk"])

	def test_noop_ignored(self) -> None:
		self.t.feed(cmd(0, 0))
		self.t.feed(cmd(0x24, 0x1E))  # PASSXT: código de teclado en bruto
		self.assertEqual(self.ids(), [])

	def test_unknown_command(self) -> None:
		self.t.feed(cmd(0, 0xF0))
		self.t.feed(cmd(0x40, 3))
		self.assertEqual(self.ids(), ["br(brltty):cmd240", "br(brltty):blk64"])

	def test_route(self) -> None:
		self.t.feed(cmd(0x01, 5))
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.routingIndex, 5)
		self.assertEqual(self.ids(), ["br(brltty):route"])

	def test_cell_block_commands(self) -> None:
		self.t.feed(cmd(0x09, 12))  # DESCCHAR
		self.t.feed(cmd(0x0B, 2))  # SETMARK: no es una celda
		g1, g2 = self.drv.lastGestures
		self.assertEqual(g1.routingIndex, 12)
		self.assertIsNone(g2.routingIndex)
		self.assertEqual(g2.argument, 2)
		self.assertEqual(self.ids(), ["br(brltty):descchar", "br(brltty):setmark"])

	def test_passdots(self) -> None:
		self.t.feed(cmd(0x22, 0x03))
		g = self.drv.lastGestures[-1]
		self.assertEqual((g.dots, g.space), (0x03, False))
		self.t.feed(cmd(0x22, 0x100 | 0x01))
		g = self.drv.lastGestures[-1]
		self.assertEqual((g.dots, g.space), (0x01, True))
		self.t.feed(cmd(0x22, 0))
		g = self.drv.lastGestures[-1]
		self.assertEqual((g.dots, g.space), (0, True))
		self.t.feed(cmd(0x22, 0xC0))
		self.assertEqual(self.drv.lastGestures[-1].dots, 0xC0)
		self.assertEqual(
			self.ids(),
			["br(brltty):dot1+dot2", "br(brltty):dot1+space", "br(brltty):space", "br(brltty):dot7+dot8"],
		)

	def test_passdots_with_control(self) -> None:
		self.t.feed(cmd(0x22, 0x01, flags=0x0400))
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.dots, 0)
		self.assertEqual(self.ids(), ["br(brltty):dot1+key_control"])

	def test_passkey_emulation(self) -> None:
		self.t.feed(sym(0xFF51))
		self.t.feed(sym(0xFF09, flags=0x0100))
		self.t.feed(sym(0xFFBE + 4))
		self.t.feed(sym(0xFF0D))
		gs = list(self.drv.lastGestures)
		self.assertEqual([g.emulatedKey for g in gs], ["kb:leftArrow", "kb:shift+tab", "kb:f5", "kb:enter"])
		self.assertEqual(
			self.ids(),
			["br(brltty):key_leftarrow", "br(brltty):key_shift+key_tab", "br(brltty):key_f5", "br(brltty):key_enter"],
		)

	def test_characters_typed(self) -> None:
		self.t.feed(sym(0x61))
		self.t.feed(sym(0xE9))  # é (latin-1)
		self.t.feed(sym(0x01000000 | 0x20AC))  # € (Unicode)
		self.t.feed(sym(0x62, flags=0x0200))  # UPPER
		self.assertEqual(self.drv.typedText, ["a", "é", "€", "B"])
		self.assertEqual(self.ids(), [])

	def test_character_with_control(self) -> None:
		self.t.feed(sym(0x63, flags=0x0400))
		g = self.drv.lastGestures[-1]
		self.assertEqual(g.emulatedKey, "kb:control+c")
		self.assertEqual(self.ids(), ["br(brltty):key_c+key_control"])
		self.assertEqual(self.drv.typedText, [])

	def test_mapped_kb_gesture_gets_emulation(self) -> None:
		self.drv._emulated = {k: v for k, v in BrlttyDriver.effectiveGestureMap().items() if v.startswith("kb:")}
		self.t.feed(cmd(0x22, 0x100 | 0x08))  # espacio + punto 4
		self.assertEqual(self.drv.lastGestures[-1].emulatedKey, "kb:downArrow")

	def test_stream_byte_by_byte(self) -> None:
		stream = cmd(0, 0x01) + pkt("A") + cmd(0x01, 7) + pkt("E", struct.pack(">II", 6, ord("w"))) + cmd(0x22, 0x101)
		for b in stream:
			self.t.feed(bytes((b,)))
		self.assertEqual(self.drv.lastGestures[1].routingIndex, 7)
		self.assertEqual(self.ids(), ["br(brltty):lnup", "br(brltty):route", "br(brltty):dot1+space"])

	def test_packets_together(self) -> None:
		self.t.feed(cmd(0, 0x17) + cmd(0, 0x18) + pkt("A"))
		self.assertEqual(self.ids(), ["br(brltty):fwinlt", "br(brltty):fwinrt"])

	def test_corrupt_stream_discarded(self) -> None:
		self.t.feed(b"\xff\xff\xff\xff\x00\x00\x00k")
		self.t.feed(cmd(0, 0x02))
		self.assertEqual(self.ids(), ["br(brltty):lndn"])

	def test_split_key_code(self) -> None:
		self.assertEqual(bt.splitKeyCode(0x20010005), (0x20000000, 1, 5, 0))
		self.assertEqual(bt.splitKeyCode((0x400 << 32) | 0xFF51), (0, 0, 0xFF51, 0x400))


class ServerAddressTests(unittest.TestCase):
	def test_parse(self) -> None:
		self.assertEqual(bt.parseServer("127.0.0.1:4101"), ("tcp", "127.0.0.1", 4101))
		self.assertEqual(bt.parseServer("equipo"), ("tcp", "equipo", 4101))
		self.assertEqual(bt.parseServer("equipo:1"), ("tcp", "equipo", 4102))
		self.assertEqual(bt.parseServer("[::1]:5000"), ("tcp", "::1", 5000))
		self.assertEqual(bt.parseServer(":0"), ("pipe", "\\\\.\\pipe\\BrlAPI0", 0))
		self.assertEqual(bt.parseServer(":3"), ("pipe", "\\\\.\\pipe\\BrlAPI3", 0))
		self.assertEqual(bt.parseServer("\\\\.\\pipe\\BrlAPI1"), ("pipe", "\\\\.\\pipe\\BrlAPI1", 0))
		self.assertEqual(bt.parseServer(""), ("tcp", "127.0.0.1", 4101))
		with self.assertRaises(ValueError):
			bt.parseServer("equipo:abc")
		self.assertEqual(bt.formatAddress("::1", 4101), "[::1]:4101")


class DetectionTests(unittest.TestCase):
	def matches(self, pipes=(), running=False, portOpen=False, server="127.0.0.1:4101"):
		with (
			mock.patch.object(bt, "_listPipes", return_value=list(pipes)),
			mock.patch.object(bt, "_brlttyRunning", return_value=running),
			mock.patch.object(bt, "_portOpen", return_value=portOpen) as probe,
			mock.patch.object(bt, "configuredServer", return_value=server),
		):
			found = BrlttyDriver.getMatches([DeviceInfo("usb", "x", usbId="VID_0F4E&PID_0114")])
			self.probed = probe.called
		return [(m.type, m.id, m.port) for m in found]

	def test_nothing_running(self) -> None:
		self.assertEqual(self.matches(), [])

	def test_pipe(self) -> None:
		self.assertEqual(self.matches(pipes=["\\\\.\\pipe\\BrlAPI0"]), [("socket", "brltty", "\\\\.\\pipe\\BrlAPI0")])

	def test_local_process_running(self) -> None:
		self.assertEqual(self.matches(running=True), [("socket", "brltty", "127.0.0.1:4101")])
		self.assertFalse(self.probed)

	def test_without_psutil_probes_port(self) -> None:
		self.assertEqual(self.matches(running=None, portOpen=True), [("socket", "brltty", "127.0.0.1:4101")])
		self.assertTrue(self.probed)
		self.assertEqual(self.matches(running=None, portOpen=False), [])

	def test_remote_server(self) -> None:
		self.assertEqual(self.matches(server="192.168.1.20:4101", portOpen=True), [("socket", "brltty", "192.168.1.20:4101")])
		self.assertEqual(self.matches(server="192.168.1.20:4101", portOpen=False), [])

	def test_candidates_without_check(self) -> None:
		with (
			mock.patch.object(bt, "_listPipes", return_value=[]),
			mock.patch.object(bt, "_brlttyRunning", return_value=False),
			mock.patch.object(bt, "configuredServer", return_value="127.0.0.1:4101"),
		):
			found = BrlttyDriver.candidateMatches("auto")
		self.assertEqual([(m.type, m.port) for m in found], [("socket", "127.0.0.1:4101")])

	def test_port_choices(self) -> None:
		self.assertEqual([c[0] for c in BrlttyDriver.getPortChoices()], ["auto"])
		self.assertFalse(BrlttyDriver.supportsSerialPorts)
		self.assertFalse(BrlttyDriver.usbHidIds or BrlttyDriver.usbSerialIds or BrlttyDriver.usbBulkIds)

	def test_port_open_real(self) -> None:
		srv = socket.socket()
		srv.bind(("127.0.0.1", 0))
		srv.listen(1)
		port = srv.getsockname()[1]
		try:
			self.assertTrue(bt._portOpen("127.0.0.1", port))
		finally:
			srv.close()

	def test_key_file(self) -> None:
		import os
		import tempfile

		with tempfile.TemporaryDirectory() as d:
			path = os.path.join(d, "brlapi.key")
			with open(path, "wb") as f:
				f.write(b"clave")
			with mock.patch.dict(os.environ, {"BRLAPI_AUTH": "keyfile:" + path}), mock.patch.object(bt, "_brlttyExecutables", return_value=[]):
				self.assertEqual(bt.readAuthKey(), b"clave")


class _TcpServer:
	"""Servidor BrlAPI de verdad (TCP en 127.0.0.1) para probar SocketTransport."""

	def __init__(self) -> None:
		self.sock = socket.socket()
		self.sock.bind(("127.0.0.1", 0))
		self.sock.listen(1)
		self.port = self.sock.getsockname()[1]
		self.conn = None
		self.received = bytearray()
		self.fake = FakeBrltty(columns=20)
		self.accepted = threading.Event()
		threading.Thread(target=self._run, daemon=True).start()

	def _run(self) -> None:
		conn, _a = self.sock.accept()
		self.conn = conn
		self.accepted.set()
		# Como BRLTTY: la versión se envía nada más aceptar.
		conn.sendall(VERSION)
		buf = b""
		try:
			while True:
				data = conn.recv(4096)
				if not data:
					return
				self.received += data
				buf += data
				while len(buf) >= 8:
					size = struct.unpack(">I", buf[:4])[0]
					if len(buf) < 8 + size:
						break
					packet, buf = buf[: 8 + size], buf[8 + size :]
					reply = self.fake(packet)
					if packet[4:8] == b"\x00\x00\x00v":
						reply = reply[1:]  # la versión ya se ha enviado
					for chunk in reply if isinstance(reply, list) else [reply]:
						conn.sendall(chunk)
		except OSError:
			return

	def close(self) -> None:
		try:
			if self.conn is not None:
				self.conn.close()
		finally:
			self.sock.close()


class SocketTransportTests(unittest.TestCase):
	def test_real_tcp_connection(self) -> None:
		server = _TcpServer()
		try:
			match = base.DeviceMatch("socket", "brltty", f"127.0.0.1:{server.port}")
			drv = BrlttyDriver(match=match, configName="brltty")
			drv.lastGestures = []
			self.assertEqual(drv.numCells, 20)
			self.assertIsInstance(drv._io, bt.SocketTransport)
			drv.display([0x3F])
			server.conn.sendall(cmd(0, 0x18))
			deadline = time.monotonic() + 2
			while time.monotonic() < deadline and not drv.lastGestures:
				time.sleep(0.01)
			self.assertEqual(gestureIds(drv), ["br(brltty):fwinrt"])
			deadline = time.monotonic() + 2
			while time.monotonic() < deadline and expectedWrite([0x3F] + [0] * 19) not in bytes(server.received):
				time.sleep(0.01)
			self.assertIn(expectedWrite([0x3F] + [0] * 19), bytes(server.received))
			# El servidor cierra: se avisa de la desconexión.
			with mock.patch.object(bt.queue_handler, "queueFunction") as queued:
				server.conn.close()
				deadline = time.monotonic() + 2
				while time.monotonic() < deadline and not queued.called:
					time.sleep(0.01)
				self.assertFalse(drv.connected)
				self.assertTrue(queued.called)
			drv.terminate()
		finally:
			server.close()

	def test_transport_on_error_once(self) -> None:
		srv = socket.socket()
		srv.bind(("127.0.0.1", 0))
		srv.listen(1)
		received: list[bytes] = []
		errors: list[int] = []
		t = bt.SocketTransport("127.0.0.1", srv.getsockname()[1], received.append, errors.append)
		conn, _a = srv.accept()
		try:
			conn.sendall(b"hola")
			t.write(b"adios")
			self.assertEqual(conn.recv(10), b"adios")
			deadline = time.monotonic() + 2
			while time.monotonic() < deadline and not received:
				time.sleep(0.01)
			# El servidor cierra (Windows puede enviar RST en vez de FIN: ambos avisan).
			conn.close()
			deadline = time.monotonic() + 2
			while time.monotonic() < deadline and not errors:
				time.sleep(0.01)
			self.assertEqual(b"".join(received), b"hola")
			self.assertEqual(len(errors), 1)
			t.close()
			with self.assertRaises(bt.hwio.IoError):
				t.write(b"x")
		finally:
			t.close()
			srv.close()

	def test_connection_refused(self) -> None:
		srv = socket.socket()
		srv.bind(("127.0.0.1", 0))
		port = srv.getsockname()[1]
		srv.close()
		with mock.patch.object(bt, "CONNECT_TIMEOUT", 0.5):
			with self.assertRaises(base.DisplayNotFound):
				BrlttyDriver(match=base.DeviceMatch("socket", "brltty", f"127.0.0.1:{port}"), configName="brltty")


class GestureMapTests(unittest.TestCase):
	def test_map_values_and_keys(self) -> None:
		known = set(bt.COMMANDS.values()) | set(bt.BLOCK_COMMANDS.values()) | set(BrlttyDriver.keyOrder)
		for keys, target in BrlttyDriver.gestureMap.items():
			self.assertTrue(target.startswith("kb:") or target.isidentifier(), target)
			parts = keys.split("+")
			for k in parts:
				self.assertIn(k, known, keys)
			self.assertFalse(all(p.startswith("dot") for p in parts), keys)

	def test_mapped_commands_described(self) -> None:
		for keys in BrlttyDriver.gestureMap:
			for k in keys.split("+"):
				self.assertIn(k, BrlttyDriver.keyDescriptions, k)

	def test_basic_commands_mapped(self) -> None:
		m = BrlttyDriver.gestureMap
		self.assertEqual(m["fwinlt"], "braille_scrollBack")
		self.assertEqual(m["fwinrt"], "braille_scrollForward")
		self.assertEqual(m["lnup"], "braille_previousLine")
		self.assertEqual(m["lndn"], "braille_nextLine")
		self.assertEqual(m["route"], "braille_routeTo")


if __name__ == "__main__":
	unittest.main()
