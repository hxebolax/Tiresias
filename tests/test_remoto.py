"""Pruebas del acceso remoto.

Levantan el servidor de retransmisión propio en 127.0.0.1 (puerto libre) y
conectan clientes en el mismo proceso. No se conecta a ningún servidor de
Internet ni se inyectan teclas reales: el «equipo local» de las sesiones es
un registrador.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import ssl
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if "tiresias_test" not in os.path.basename(paths.DATA_DIR or ""):
	# Nunca se toca la carpeta de datos real (otras pruebas pueden haber puesto ya una temporal).
	_TMPDATA = tempfile.mkdtemp(prefix="tiresias_test_remoto_")
	paths.setDataDir(_TMPDATA)
	paths.ensureDataDirs()

from tiresias.remote import protocol, serializer  # noqa: E402
from tiresias.remote.certs import CertificateManager  # noqa: E402
from tiresias.remote.protocol import ConnectionInfo, ConnectionMode, MessageType  # noqa: E402
from tiresias.remote.server import RelayServer  # noqa: E402
from tiresias.remote.session import FollowerSession, LeaderSession, LocalMachine  # noqa: E402
from tiresias.remote.store import KIND_HOST, Preset, RemoteStore  # noqa: E402
from tiresias.remote.transport import RelayTransport, fingerprintOf, formatFingerprint  # noqa: E402
from tiresias.speech import commands as cmds  # noqa: E402

TIMEOUT = 10.0


def waitFor(cond, timeout: float = TIMEOUT) -> bool:
	end = time.monotonic() + timeout
	while time.monotonic() < end:
		if cond():
			return True
		time.sleep(0.01)
	return cond()


class Recorder(LocalMachine):
	"""Equipo local de prueba: apunta todo lo que le pide la sesión."""

	def __init__(self) -> None:
		self.calls: list[tuple] = []
		self.lock = threading.Lock()

	def _rec(self, *item) -> None:
		with self.lock:
			self.calls.append(item)

	def of(self, name: str) -> list[tuple]:
		with self.lock:
			return [c for c in self.calls if c[0] == name]

	def speak(self, sequence, priority=0):
		self._rec("speak", sequence, priority)

	def cancelSpeech(self):
		self._rec("cancel")

	def pauseSpeech(self, switch):
		self._rec("pause", switch)

	def beep(self, hz, length, left=50, right=50):
		self._rec("beep", hz, length, left, right)

	def playWave(self, fileName="", name=""):
		self._rec("wave", fileName, name)

	def display(self, cells):
		self._rec("display", cells)

	def sendKey(self, vk, extended, pressed, scan=None):
		self._rec("key", vk, extended, pressed, scan)

	def brailleInput(self, **kwargs):
		self._rec("brailleInput", kwargs)

	def sendSAS(self):
		self._rec("sas")

	def setBrailleDisplaySize(self, size):
		self._rec("displaySize", size)

	def setClipboardText(self, text):
		self._rec("clipboard", text)

	def onClientJoined(self, session, client):
		self._rec("joined", client.get("connection_type"))

	def onClientLeft(self, session, client):
		self._rec("left", client.get("connection_type"))

	def onMotd(self, session, motd, forceDisplay):
		self._rec("motd", motd)

	def onServerError(self, session, error):
		self._rec("error", error)


# ====================================================================== protocolo
class ProtocolTests(unittest.TestCase):
	def test_addresses(self) -> None:
		self.assertEqual(protocol.addressToHostPort("nvdaremote.com"), ("nvdaremote.com", 6837))
		self.assertEqual(protocol.addressToHostPort("ejemplo.org:1234"), ("ejemplo.org", 1234))
		self.assertEqual(protocol.addressToHostPort("[::1]:7000"), ("::1", 7000))
		self.assertEqual(protocol.hostPortToAddress(("nvdaremote.com", 6837)), "nvdaremote.com")
		self.assertEqual(protocol.hostPortToAddress(("::1", 7000)), "[::1]:7000")
		with self.assertRaises(ValueError):
			protocol.addressToHostPort("")

	def test_url_roundtrip(self) -> None:
		info = ConnectionInfo(hostname="nvdaremote.com", mode=ConnectionMode.LEADER, key="12345")
		self.assertEqual(info.getURL(), "nvdaremote://nvdaremote.com?key=12345&mode=master")
		self.assertEqual(info.getURLToConnect(), "nvdaremote://nvdaremote.com?key=12345&mode=slave")
		parsed = ConnectionInfo.fromURL("nvdaremote://192.168.1.5:7000?key=abc&mode=slave")
		self.assertEqual((parsed.hostname, parsed.port, parsed.key, parsed.mode), ("192.168.1.5", 7000, "abc", ConnectionMode.FOLLOWER))
		with self.assertRaises(protocol.URLParsingError):
			ConnectionInfo.fromURL("nvdaremote://host?mode=master")
		with self.assertRaises(protocol.URLParsingError):
			ConnectionInfo.fromURL("http://host?key=1&mode=master")

	def test_generate_key(self) -> None:
		keys = {protocol.generateKey() for _i in range(50)}
		self.assertEqual(len(keys), 50)
		for k in keys:
			self.assertEqual(len(k), 10)
			self.assertTrue(k.isdigit())

	def test_wire_values_match_nvda(self) -> None:
		# Valores del protocolo de NVDA (source/_remoteClient/protocol.py).
		expected = {
			"PROTOCOL_VERSION": "protocol_version",
			"JOIN": "join",
			"CHANNEL_JOINED": "channel_joined",
			"CLIENT_JOINED": "client_joined",
			"CLIENT_LEFT": "client_left",
			"GENERATE_KEY": "generate_key",
			"KEY": "key",
			"SPEAK": "speak",
			"CANCEL": "cancel",
			"PAUSE_SPEECH": "pause_speech",
			"TONE": "tone",
			"WAVE": "wave",
			"SEND_SAS": "send_SAS",
			"DISPLAY": "display",
			"BRAILLE_INPUT": "braille_input",
			"SET_BRAILLE_INFO": "set_braille_info",
			"SET_DISPLAY_SIZE": "set_display_size",
			"SET_CLIPBOARD_TEXT": "set_clipboard_text",
			"MOTD": "motd",
			"VERSION_MISMATCH": "version_mismatch",
			"PING": "ping",
			"ERROR": "error",
			"NVDA_NOT_CONNECTED": "nvda_not_connected",
		}
		for name, value in expected.items():
			self.assertEqual(MessageType[name].value, value)
		self.assertEqual(protocol.PROTOCOL_VERSION, 2)
		self.assertEqual(protocol.SERVER_PORT, 6837)
		self.assertEqual(ConnectionMode.LEADER.value, "master")
		self.assertEqual(ConnectionMode.FOLLOWER.value, "slave")


# ====================================================================== serialización
class _NvdaLikeEncoder(json.JSONEncoder):
	"""Reproduce cómo codifica NVDA las órdenes de voz: ``[clase, __dict__]``."""

	def default(self, o):
		return [o.__class__.__name__, o.__dict__]


class _NvdaPitch:
	pass


class SerializerTests(unittest.TestCase):
	def test_speech_roundtrip(self) -> None:
		seq = [
			"Hola",
			cmds.CharacterModeCommand(True),
			"a",
			cmds.CharacterModeCommand(False),
			cmds.LangChangeCommand("en"),
			cmds.BreakCommand(150),
			cmds.PitchCommand(offset=30),
			"mundo",
			cmds.PitchCommand(0),
			cmds.EndUtteranceCommand(),
			cmds.IndexCommand(5),
			cmds.CallbackCommand(lambda: None),
			cmds.BeepCommand(440, 20),
		]
		data = serializer.serialize(MessageType.SPEAK, sequence=seq, priority=0)
		self.assertTrue(data.endswith(b"\n"))
		self.assertEqual(data.count(b"\n"), 1)
		raw = json.loads(data)
		self.assertEqual(raw["type"], "speak")
		self.assertIn(["PitchCommand", {"_offset": 30, "_multiplier": 1.0, "isDefault": False}], raw["sequence"])
		self.assertIn(["CharacterModeCommand", {"state": True, "isDefault": False}], raw["sequence"])
		self.assertIn(["LangChangeCommand", {"lang": "en", "isDefault": False}], raw["sequence"])
		# Índices, llamadas y pitidos no viajan dentro de la voz.
		names = [i[0] for i in raw["sequence"] if isinstance(i, list)]
		self.assertNotIn("IndexCommand", names)
		self.assertNotIn("CallbackCommand", names)
		self.assertNotIn("BeepCommand", names)
		back = serializer.deserialize(data)["sequence"]
		self.assertEqual(back[0], "Hola")
		self.assertIsInstance(back[1], cmds.CharacterModeCommand)
		self.assertTrue(back[1].state)
		pitch = [i for i in back if isinstance(i, cmds.PitchCommand)]
		self.assertEqual(pitch[0].offset, 30)
		self.assertIsInstance(back[-1], cmds.EndUtteranceCommand)

	def test_decode_nvda_format(self) -> None:
		# Un objeto con los atributos internos de NVDA, codificado como NVDA.
		p = _NvdaPitch()
		p.__class__.__name__  # noqa: B018
		pitch = type("PitchCommand", (), {})()
		pitch._offset = 20
		pitch._multiplier = 1
		pitch.isDefault = False
		char = type("CharacterModeCommand", (), {})()
		char.state = True
		char.isDefault = False
		end = type("EndUtteranceCommand", (), {})()
		unknown = type("ConfigProfileTriggerCommand", (), {})()
		unknown.trigger = "x"
		line = json.dumps({"sequence": ["Botón", pitch, char, "b", end, unknown], "priority": 1, "type": "speak"}, cls=_NvdaLikeEncoder).encode("utf-8")
		msg = serializer.deserialize(line)
		seq = msg["sequence"]
		self.assertEqual(seq[0], "Botón")
		self.assertIsInstance(seq[1], cmds.PitchCommand)
		self.assertEqual((seq[1].offset, seq[1].multiplier), (20, 1.0))
		self.assertIsInstance(seq[2], cmds.CharacterModeCommand)
		self.assertIsInstance(seq[4], cmds.EndUtteranceCommand)
		self.assertEqual(len(seq), 5)  # la orden desconocida se descarta
		self.assertEqual(msg["priority"], 1)

	def test_unicode_and_newlines(self) -> None:
		text = "línea 1\nlínea 2 ñ € \U0001f600"
		data = serializer.serialize(MessageType.SET_CLIPBOARD_TEXT, text=text)
		self.assertEqual(data.count(b"\n"), 1)
		self.assertEqual(serializer.deserialize(data.rstrip(b"\n"))["text"], text)

	def test_invalid(self) -> None:
		with self.assertRaises(ValueError):
			serializer.deserialize(b"[1, 2]")
		with self.assertRaises(ValueError):
			serializer.deserialize(b"{no json")


# ====================================================================== almacén
class StoreTests(unittest.TestCase):
	def test_presets_and_trust(self) -> None:
		folder = tempfile.mkdtemp(prefix="tiresias_store_")
		try:
			path = os.path.join(folder, "remote", "remoto.json")
			st = RemoteStore(path)
			st.savePreset(Preset(name="Casa", mode="slave", kind=KIND_HOST, port=7000, key="111"))
			st.savePreset(Preset(name="Trabajo", mode="master", host="nvdaremote.com", key="222"))
			st.autoconnect = "Casa"
			st.trust("192.168.1.5:7000", "ABCDEF")
			st.addRecent("nvdaremote.com")
			st2 = RemoteStore(path)
			self.assertEqual([p.name for p in st2.getPresets()], ["Casa", "Trabajo"])
			casa = st2.getPreset("casa")
			self.assertEqual((casa.kind, casa.port, casa.key, casa.mode), (KIND_HOST, 7000, "111", "slave"))
			self.assertEqual(st2.autoconnect, "Casa")
			self.assertTrue(st2.isTrusted("192.168.1.5:7000", "abcdef"))
			self.assertFalse(st2.isTrusted("192.168.1.5:7000", "000000"))
			self.assertEqual(st2.recentHosts(), ["nvdaremote.com"])
			self.assertTrue(st2.deletePreset("Casa"))
			self.assertEqual(st2.autoconnect, "")
			self.assertTrue(st2.shouldShowMotd("srv", "h1"))
			self.assertFalse(st2.shouldShowMotd("srv", "h1"))
		finally:
			shutil.rmtree(folder, ignore_errors=True)


# ====================================================================== red
class _NetBase(unittest.TestCase):
	server: RelayServer
	certDir: str

	@classmethod
	def setUpClass(cls) -> None:
		cls.certDir = tempfile.mkdtemp(prefix="tiresias_certs_")
		cls.certs = CertificateManager(cls.certDir)
		cls.server = RelayServer(0, None, cls.certs, bindHosts=("127.0.0.1",))
		cls.server.start()
		cls.port = cls.server.port

	@classmethod
	def tearDownClass(cls) -> None:
		cls.server.close()
		shutil.rmtree(cls.certDir, ignore_errors=True)

	def setUp(self) -> None:
		self._transports: list[RelayTransport] = []

	def tearDown(self) -> None:
		for t in self._transports:
			t.close()
		for t in self._transports:
			t.join(5)

	def makeTransport(self, channel, mode, port=None, **kw) -> RelayTransport:
		kw.setdefault("insecure", True)
		kw.setdefault("trustedFingerprint", self.server.fingerprint)
		t = RelayTransport(
			"127.0.0.1",
			port or self.port,
			channel=channel,
			connectionType=mode.value if mode else None,
			timeout=5,
			reconnectDelay=0.2,
			**kw,
		)
		self._transports.append(t)
		return t

	def pair(self, channel: str):
		lt = self.makeTransport(channel, ConnectionMode.LEADER)
		ft = self.makeTransport(channel, ConnectionMode.FOLLOWER)
		lm, fm = Recorder(), Recorder()
		leader = LeaderSession(lt, lm)
		follower = FollowerSession(ft, fm)
		ft.start()
		self.assertTrue(waitFor(lambda: follower.channelJoined))
		lt.start()
		self.assertTrue(waitFor(lambda: leader.hasFollowers and follower.hasLeaders))
		return leader, follower, lm, fm


class CertificateTests(_NetBase):
	def test_certificate_files_and_fingerprint(self) -> None:
		fp = self.server.fingerprint
		self.assertRegex(fp, r"^[0-9a-f]{64}$")
		for name in ("servidor.pem", "servidor.key", "servidor.huella"):
			self.assertTrue(os.path.isfile(os.path.join(self.certDir, name)))
		# Se reutiliza el certificado guardado.
		self.assertEqual(CertificateManager(self.certDir).ensureValid(), fp)
		self.assertEqual(formatFingerprint("ab12")[:5], "AB:12")

	def test_untrusted_certificate_is_rejected_with_fingerprint(self) -> None:
		t = self.makeTransport("canal-cert", ConnectionMode.FOLLOWER, insecure=False, trustedFingerprint=None)
		failed = []
		t.onCertificateFailed = lambda fp: failed.append(fp)
		t.start()
		self.assertTrue(waitFor(lambda: failed))
		self.assertEqual(failed[0], self.server.fingerprint)
		self.assertFalse(t.connected)
		self.assertFalse(waitFor(lambda: t.successfulConnects > 0, 0.5))

	def test_trusted_fingerprint_from_store_connects(self) -> None:
		seen = []

		def isTrusted(address, fp):
			seen.append(address)
			return fp == self.server.fingerprint

		t = self.makeTransport("canal-cert2", ConnectionMode.FOLLOWER, insecure=False, trustedFingerprint=None, isTrusted=isTrusted)
		t.start()
		self.assertTrue(waitFor(lambda: t.connected))
		self.assertEqual(seen[0], f"127.0.0.1:{self.port}")
		ver = t._conn.sock.version()
		self.assertIn(ver, ("TLSv1.2", "TLSv1.3"))
		der = t._conn.sock.getpeercert(True)
		self.assertEqual(fingerprintOf(der), self.server.fingerprint)

	def test_wrong_pinned_fingerprint_is_rejected(self) -> None:
		t = self.makeTransport("canal-cert3", ConnectionMode.LEADER, trustedFingerprint="00" * 32)
		failed = []
		t.onCertificateFailed = lambda fp: failed.append(fp)
		t.start()
		self.assertTrue(waitFor(lambda: failed))
		self.assertEqual(failed[0], self.server.fingerprint)
		self.assertFalse(t.connected)


class SessionTests(_NetBase):
	def test_join_and_protocol_version(self) -> None:
		leader, follower, lm, fm = self.pair("canal-union")
		self.assertEqual(lm.of("joined")[0][1], "slave")
		self.assertEqual(fm.of("joined")[0][1], "master")
		with self.server._lock:
			versions = {c.connectionType: c.protocolVersion for c in self.server._clients.values() if c.channel == "canal-union"}
		self.assertEqual(versions, {"master": 2, "slave": 2})
		self.assertEqual(self.server.clientCount >= 2, True)

	def test_speech_tones_and_cancel_follower_to_leader(self) -> None:
		leader, follower, lm, fm = self.pair("canal-voz")
		self.assertTrue(follower.sendSpeech(["Inicio", cmds.PitchCommand(offset=25), "Botón Aceptar"], 0))
		self.assertTrue(waitFor(lambda: lm.of("speak")))
		seq = lm.of("speak")[0][1]
		self.assertEqual(seq[0], "Inicio")
		self.assertIsInstance(seq[1], cmds.PitchCommand)
		self.assertEqual(seq[2], "Botón Aceptar")
		follower.sendCancel()
		follower.sendTone(880, 40, 30, 70)
		follower.sendWave("C:\\NVDA\\waves\\browseMode.wav", "browseMode")
		follower.sendPause(True)
		self.assertTrue(waitFor(lambda: lm.of("cancel") and lm.of("beep") and lm.of("wave") and lm.of("pause")))
		self.assertEqual(lm.of("beep")[0][1:], (880.0, 40, 30, 70))
		self.assertEqual(lm.of("wave")[0][1:], ("C:\\NVDA\\waves\\browseMode.wav", "browseMode"))
		self.assertEqual(lm.of("pause")[0][1], True)
		# El que controla no recibe su propia voz de vuelta.
		self.assertFalse(fm.of("speak"))

	def test_keys_leader_to_follower(self) -> None:
		leader, follower, lm, fm = self.pair("canal-teclas")
		leader.sendKey(0x41, False, True, 0x1E)
		leader.sendKey(0x41, False, False, 0x1E)
		leader.sendKey(0x2D, True, True)
		self.assertTrue(waitFor(lambda: len(fm.of("key")) == 3))
		self.assertEqual(fm.of("key"), [("key", 0x41, False, True, 0x1E), ("key", 0x41, False, False, 0x1E), ("key", 0x2D, True, True, None)])
		leader.sendSAS()
		self.assertTrue(waitFor(lambda: fm.of("sas")))

	def test_clipboard_both_ways(self) -> None:
		leader, follower, lm, fm = self.pair("canal-portapapeles")
		leader.pushClipboard("texto del que controla\ncon dos líneas")
		follower.pushClipboard("respuesta ñ")
		self.assertTrue(waitFor(lambda: fm.of("clipboard") and lm.of("clipboard")))
		self.assertEqual(fm.of("clipboard")[0][1], "texto del que controla\ncon dos líneas")
		self.assertEqual(lm.of("clipboard")[0][1], "respuesta ñ")

	def test_braille_negotiation_and_display(self) -> None:
		lt = self.makeTransport("canal-braille", ConnectionMode.LEADER)
		ft = self.makeTransport("canal-braille", ConnectionMode.FOLLOWER)
		lm, fm = Recorder(), Recorder()
		leader = LeaderSession(lt, lm)
		leader.setBrailleInfo("hidBraille", 40)
		follower = FollowerSession(ft, fm)
		ft.start()
		self.assertTrue(waitFor(lambda: follower.channelJoined))
		# Sin línea braille en quien controla no se envían celdas.
		self.assertFalse(follower.sendDisplay([1, 2, 3]))
		lt.start()
		self.assertTrue(waitFor(lambda: follower.hasBrailleLeaders))
		self.assertEqual(follower.remoteDisplaySize, 40)
		self.assertIn(("displaySize", 40), fm.of("displaySize"))
		cells = [0x01, 0x03, 0xFF, 0]
		self.assertTrue(follower.sendDisplay(cells))
		self.assertTrue(waitFor(lambda: lm.of("display")))
		self.assertEqual(lm.of("display")[0][1], cells)
		leader.sendBrailleInput(source="hidBraille", id="routing", routingIndex=3, cellIndexes=[3], dots=0, space=False, scriptPath=["globalCommands", "GlobalCommands", "braille_routeTo"])
		self.assertTrue(waitFor(lambda: fm.of("brailleInput")))
		data = fm.of("brailleInput")[0][1]
		self.assertEqual(data["scriptPath"][2], "braille_routeTo")
		self.assertEqual(data["routingIndex"], 3)
		# Al irse quien controla, el tamaño vuelve a 0.
		lt.close()
		self.assertTrue(waitFor(lambda: fm.of("left")))
		self.assertTrue(waitFor(lambda: follower.remoteDisplaySize == 0))
		self.assertEqual(fm.of("displaySize")[-1], ("displaySize", 0))

	def test_channels_are_isolated(self) -> None:
		leader, follower, lm, fm = self.pair("canal-A")
		other = Recorder()
		ot = self.makeTransport("canal-B", ConnectionMode.LEADER)
		otherSession = LeaderSession(ot, other)
		ot.start()
		self.assertTrue(waitFor(lambda: otherSession.channelJoined))
		otherSession.sendKey(0x42, False, True)
		follower.sendSpeech(["solo para A"])
		self.assertTrue(waitFor(lambda: lm.of("speak")))
		time.sleep(0.2)
		self.assertFalse(fm.of("key"))
		self.assertFalse(other.of("speak"))

	def test_generate_key(self) -> None:
		t = self.makeTransport(None, None)
		got = []
		t.onMessage = lambda obj: got.append(obj)
		t.start()
		self.assertTrue(waitFor(lambda: got))
		self.assertEqual(got[0]["type"], "generate_key")
		self.assertTrue(got[0]["key"].isdigit())

	def test_reconnect_after_server_drops_client(self) -> None:
		leader, follower, lm, fm = self.pair("canal-reconexion")
		with self.server._lock:
			fClient = [c for c in self.server._clients.values() if c.channel == "canal-reconexion" and c.connectionType == "slave"][0]
		fClient.close()
		self.assertTrue(waitFor(lambda: follower.transport.successfulConnects >= 2 and follower.transport.connected))
		self.assertTrue(waitFor(lambda: follower.hasLeaders))


class PasswordServerTests(unittest.TestCase):
	"""Servidor local de conexión directa (una sola clave)."""

	def test_wrong_and_right_key(self) -> None:
		certDir = tempfile.mkdtemp(prefix="tiresias_certs_")
		server = RelayServer(0, "clave-correcta", CertificateManager(certDir), bindHosts=("127.0.0.1",))
		server.start()
		transports = []
		try:
			bad = RelayTransport("127.0.0.1", server.port, channel="otra", connectionType="slave", insecure=True, trustedFingerprint=server.fingerprint, reconnectDelay=0.2)
			transports.append(bad)
			rec = Recorder()
			badSession = FollowerSession(bad, rec)
			bad.start()
			self.assertTrue(waitFor(lambda: rec.of("error")))
			self.assertEqual(rec.of("error")[0][1], "incorrect_password")
			self.assertFalse(bad.reconnect)
			self.assertTrue(waitFor(lambda: not bad.running))
			self.assertFalse(badSession.channelJoined)
			good = RelayTransport("127.0.0.1", server.port, channel="clave-correcta", connectionType="slave", insecure=True, trustedFingerprint=server.fingerprint)
			transports.append(good)
			goodSession = FollowerSession(good, Recorder())
			good.start()
			self.assertTrue(waitFor(lambda: goodSession.channelJoined))
		finally:
			for t in transports:
				t.close()
			server.close()
			shutil.rmtree(certDir, ignore_errors=True)


class NvdaWireCompatibilityTests(_NetBase):
	"""Un cliente «a mano» que habla exactamente como NVDA."""

	def rawClient(self, channel: str, mode: str):
		ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
		ctx.check_hostname = False
		ctx.verify_mode = ssl.CERT_NONE
		sock = ctx.wrap_socket(socket.create_connection(("127.0.0.1", self.port), timeout=5), server_hostname="127.0.0.1")
		sock.sendall(b'{"version": 2, "type": "protocol_version"}\n')
		sock.sendall(json.dumps({"channel": channel, "connection_type": mode, "type": "join"}).encode() + b"\n")
		return sock

	@staticmethod
	def readMessages(sock, until, timeout=TIMEOUT):
		buf = b""
		msgs = []
		end = time.monotonic() + timeout
		while time.monotonic() < end:
			sock.settimeout(max(0.05, end - time.monotonic()))
			try:
				chunk = sock.recv(65536)
			except (socket.timeout, TimeoutError):
				break
			if not chunk:
				break
			buf += chunk
			while b"\n" in buf:
				line, buf = buf.split(b"\n", 1)
				msgs.append(json.loads(line))
			if until(msgs):
				break
		return msgs

	def test_nvda_follower_receives_tiresias_keys(self) -> None:
		raw = self.rawClient("canal-nvda", "slave")
		try:
			joined = self.readMessages(raw, lambda m: any(x["type"] == "channel_joined" for x in m))
			self.assertEqual(joined[0]["type"], "channel_joined")
			lt = self.makeTransport("canal-nvda", ConnectionMode.LEADER)
			leader = LeaderSession(lt, Recorder())
			leader.setBrailleInfo("noBraille", 0)
			lt.start()
			self.assertTrue(waitFor(lambda: leader.hasFollowers))
			leader.sendKey(0x2D, True, True, 0x52)
			msgs = self.readMessages(raw, lambda m: any(x["type"] == "key" for x in m))
			types = [m["type"] for m in msgs]
			self.assertIn("client_joined", types)
			self.assertIn("set_braille_info", types)
			key = [m for m in msgs if m["type"] == "key"][0]
			origin = key.pop("origin")
			self.assertIsInstance(origin, int)
			self.assertEqual(key, {"vk_code": 0x2D, "extended": True, "pressed": True, "scan_code": 0x52, "type": "key"})
			info = [m for m in msgs if m["type"] == "set_braille_info"][0]
			self.assertEqual((info["name"], info["numCells"]), ("noBraille", 0))
		finally:
			raw.close()

	def test_nvda_follower_speech_reaches_tiresias_leader(self) -> None:
		lt = self.makeTransport("canal-nvda-voz", ConnectionMode.LEADER)
		lm = Recorder()
		leader = LeaderSession(lt, lm)
		lt.start()
		self.assertTrue(waitFor(lambda: leader.channelJoined))
		raw = self.rawClient("canal-nvda-voz", "slave")
		try:
			self.assertTrue(waitFor(lambda: leader.hasFollowers))
			# Exactamente como lo serializa NVDA (orden de claves y separadores por defecto).
			raw.sendall(
				b'{"sequence": ["Escritorio", ["PitchCommand", {"_offset": 30, "_multiplier": 1, "isDefault": false}], "lista"], "priority": 0, "type": "speak"}\n'
				b'{"type": "cancel"}\n'
				b'{"hz": 440, "length": 50, "left": 50, "right": 50, "isSpeechBeepCommand": false, "type": "tone"}\n'
				b'{"fileName": "C:\\\\Program Files\\\\NVDA\\\\waves\\\\focusMode.wav", "asynchronous": true, "isSpeechWaveFileCommand": false, "type": "wave"}\n'
				b'{"cells": [1, 2, 3], "type": "display"}\n'
				b'{"type": "ping"}\n'
				b'{"text": "copiado en NVDA", "type": "set_clipboard_text"}\n'
			)
			self.assertTrue(waitFor(lambda: lm.of("clipboard")))
			seq = lm.of("speak")[0][1]
			self.assertEqual(seq[0], "Escritorio")
			self.assertEqual(seq[1].offset, 30)
			self.assertTrue(lm.of("cancel"))
			self.assertEqual(lm.of("beep")[0][1:3], (440.0, 50))
			self.assertTrue(lm.of("wave")[0][1].endswith("focusMode.wav"))
			self.assertEqual(lm.of("display")[0][1], [1, 2, 3])
			self.assertEqual(lm.of("clipboard")[0][1], "copiado en NVDA")
		finally:
			raw.close()


# ====================================================================== teclado del que controla
class _FakeTransport:
	connected = True
	reconnect = True
	addressKey = "test"

	def __init__(self) -> None:
		self.sent: list[tuple] = []
		self.onMessage = None

	def send(self, type, **payload):
		self.sent.append((type.value if hasattr(type, "value") else type, payload))
		return True

	def close(self):
		pass

	def stopReconnecting(self):
		self.reconnect = False


class _FakeManager:
	def __init__(self) -> None:
		self._modVks = set()
		self._tiresiasDown = False
		self._tiresiasVk = None
		self.inputHelp = False


class KeyboardForwardingTests(unittest.TestCase):
	"""Estado de las teclas al alternar entre el equipo local y el remoto."""

	def setUp(self) -> None:
		from tiresias.remote.client import RemoteClient

		folder = tempfile.mkdtemp(prefix="tiresias_kb_")
		self.addCleanup(shutil.rmtree, folder, True)
		self.client = RemoteClient(RemoteStore(os.path.join(folder, "r.json")), CertificateManager(folder))
		self.transport = _FakeTransport()
		self.session = LeaderSession(self.transport, Recorder())
		self.session.clients[1] = {"id": 1, "connection_type": "slave"}
		self.client.session = self.session
		self.toggles = 0

		def fakeToggle(gesture=None):
			self.toggles += 1

		self.client.toggleRemoteKeyControl = fakeToggle
		# Alternar = Tiresias (Insert) + Alt + Tab.
		self.client._isToggleGesture = lambda vk, scan, ext: vk == 0x09 and (0x2D, True) in self.client._remoteDown and (0xA4, False) in self.client._remoteDown

	def keys(self):
		return [(p["vk_code"], p["pressed"]) for t, p in self.transport.sent if t == "key"]

	def test_full_cycle(self) -> None:
		c = self.client
		mgr = _FakeManager()
		# El usuario pulsa Insert+Alt+Tab en local: se pasa al remoto con esas teclas pendientes.
		mgr._modVks = {0xA4}
		mgr._tiresiasDown = True
		mgr._tiresiasVk = (0x2D, True)
		with c._keyLock:
			c._beginRemote(mgr, 0x09)
		self.assertTrue(c.sendingKeys)
		# Las liberaciones de esas teclas se procesan en local (True).
		self.assertTrue(c._onRawKey(0x09, 0x0F, False, False, False))
		self.assertTrue(c._onRawKey(0xA4, 0x38, False, False, False))
		self.assertTrue(c._onRawKey(0x2D, 0x52, True, False, False))
		self.assertFalse(self.keys())
		# Teclas normales: se envían y se capturan.
		self.assertFalse(c._onRawKey(0x41, 0x1E, False, True, False))
		self.assertFalse(c._onRawKey(0x41, 0x1E, False, False, False))
		# Las teclas inyectadas por otros programas no se envían.
		self.assertTrue(c._onRawKey(0x42, 0x30, False, True, True))
		self.assertEqual(self.keys(), [(0x41, True), (0x41, False)])
		# Insert+Alt+Tab en remoto: vuelve al local soltando Insert y Alt en el remoto.
		self.assertFalse(c._onRawKey(0x2D, 0x52, True, True, False))
		self.assertFalse(c._onRawKey(0xA4, 0x38, False, True, False))
		self.assertFalse(c._onRawKey(0x09, 0x0F, False, True, False))
		self.assertFalse(c.sendingKeys)
		self.assertEqual(self.toggles, 1)
		sent = self.keys()[2:]
		self.assertEqual(sent[:2], [(0x2D, True), (0xA4, True)])
		# Antes de soltar Alt se envía VK_NONE para que no se abra el menú remoto.
		self.assertIn((0xFF, True), sent)
		self.assertIn((0xFF, False), sent)
		self.assertIn((0x2D, False), sent)
		self.assertIn((0xA4, False), sent)
		self.assertNotIn((0x09, True), sent)
		# Las liberaciones físicas se descartan en local (y la repetición también).
		self.assertFalse(c._onRawKey(0xA4, 0x38, False, True, False))
		self.assertFalse(c._onRawKey(0x09, 0x0F, False, False, False))
		self.assertFalse(c._onRawKey(0xA4, 0x38, False, False, False))
		self.assertFalse(c._onRawKey(0x2D, 0x52, True, False, False))
		# Y después todo vuelve a la normalidad en el equipo local.
		self.assertTrue(c._onRawKey(0x41, 0x1E, False, True, False))
		self.assertTrue(c._onRawKey(0x41, 0x1E, False, False, False))
		self.assertEqual(len(self.keys()), len(sent) + 2)

	def test_disconnect_while_sending_releases_remote_keys(self) -> None:
		c = self.client
		with c._keyLock:
			c._beginRemote(_FakeManager(), None)
		c._onRawKey(0xA0, 0x2A, False, True, False)  # Mayúsculas izquierda pulsada en remoto
		with c._keyLock:
			c._endRemote(None)
		self.assertEqual(self.keys(), [(0xA0, True), (0xA0, False)])
		self.assertFalse(c._onRawKey(0xA0, 0x2A, False, False, False))
		self.assertTrue(c._onRawKey(0xA0, 0x2A, False, True, False))


class SessionLockTests(KeyboardForwardingTests):
	"""El bloqueo de la sesión de Windows devuelve el teclado al equipo local."""

	def setUp(self) -> None:
		super().setUp()
		self.locks = 0
		self.resumed = 0

		def fakeLock():
			self.locks += 1

		def fakeResume():
			self.resumed += 1

		# Nunca se bloquea el equipo de verdad en las pruebas.
		self.client._lockLocalWorkstation = fakeLock
		self.client._afterSwitchToRemote = fakeResume

	def test_full_cycle(self) -> None:  # (heredada: no se repite aquí)
		pass

	def test_disconnect_while_sending_releases_remote_keys(self) -> None:
		pass

	def test_lock_and_unlock(self) -> None:
		c = self.client
		with c._keyLock:
			c._beginRemote(_FakeManager(), None)
		c._onRawKey(0xA2, 0x1D, False, True, False)  # Control pulsado en el remoto
		c.onSessionLockChanged(True)
		self.assertFalse(c.sendingKeys)
		self.assertIn((0xA2, False), self.keys())
		c.onSessionLockChanged(False)
		self.assertTrue(c.sendingKeys)
		self.assertEqual(self.resumed, 1)
		# Desbloquear sin haber estado controlando no cambia nada.
		with c._keyLock:
			c._endRemote(None)
		c.onSessionLockChanged(False)
		self.assertFalse(c.sendingKeys)

	def test_windows_l_returns_to_local(self) -> None:
		c = self.client
		with c._keyLock:
			c._beginRemote(_FakeManager(), None)
		self.assertFalse(c._onRawKey(0x5B, 0x5B, True, True, False))  # Windows en el remoto
		self.assertFalse(c._onRawKey(0x4C, 0x26, False, True, False))  # L
		self.assertFalse(c.sendingKeys)
		self.assertEqual(self.locks, 1)
		sent = self.keys()
		self.assertNotIn((0x4C, True), sent)
		self.assertEqual(sent[-1], (0x5B, False))
		self.assertIn((0xFF, True), sent)
		# Las liberaciones físicas no llegan al equipo local.
		self.assertFalse(c._onRawKey(0x4C, 0x26, False, False, False))
		self.assertFalse(c._onRawKey(0x5B, 0x5B, True, False, False))
		self.assertTrue(c._wasSendingBeforeLock)

	def test_monitor_window_receives_notifications(self) -> None:
		from tiresias.remote import session_lock

		got = []
		mon = session_lock.SessionLockMonitor(lambda locked: got.append(locked))
		mon.start()
		try:
			self.assertTrue(mon.hwnd)
			self.assertTrue(mon.registered)
			# Se simulan los mensajes que envía Windows (sin bloquear nada).
			session_lock._user32.PostMessageW(mon.hwnd, session_lock.WM_WTSSESSION_CHANGE, session_lock.WTS_SESSION_LOCK, 0)
			session_lock._user32.PostMessageW(mon.hwnd, session_lock.WM_WTSSESSION_CHANGE, session_lock.WTS_SESSION_UNLOCK, 0)
			self.assertTrue(waitFor(lambda: got == [True, False]))
		finally:
			mon.stop()
		self.assertIsNone(mon.hwnd)
		self.assertFalse(mon.registered)


class DpapiStoreTests(unittest.TestCase):
	def test_roundtrip(self) -> None:
		from tiresias.remote import dpapi

		enc = dpapi.protect("clave secreta ñ 123")
		self.assertTrue(enc.startswith("dpapi:"))
		self.assertNotIn("secreta", enc)
		self.assertEqual(dpapi.unprotect(enc), "clave secreta ñ 123")
		with self.assertRaises(OSError):
			dpapi.unprotect("dpapi:" + "QUJDRA==")

	def test_plaintext_keys_are_migrated(self) -> None:
		folder = tempfile.mkdtemp(prefix="tiresias_dpapi_")
		self.addCleanup(shutil.rmtree, folder, True)
		path = os.path.join(folder, "remoto.json")
		old = {"presets": [{"name": "Viejo", "mode": "master", "kind": "relay", "host": "h", "port": 6837, "key": "clave-en-claro"}, {"name": "Ajeno", "mode": "slave", "kind": "relay", "host": "h", "port": 6837, "key": "dpapi:QUJDRA=="}]}
		with open(path, "w", encoding="utf-8") as f:
			json.dump(old, f)
		st = RemoteStore(path)
		self.assertEqual(st.getPreset("Viejo").key, "clave-en-claro")
		self.assertEqual(st.getPreset("Ajeno").key, "")
		with open(path, encoding="utf-8") as f:
			text = f.read()
		self.assertNotIn("clave-en-claro", text)
		saved = {p["name"]: p["key"] for p in json.loads(text)["presets"]}
		self.assertTrue(saved["Viejo"].startswith("dpapi:"))
		# La clave que no se puede descifrar (otro usuario o equipo) se conserva.
		self.assertEqual(saved["Ajeno"], "dpapi:QUJDRA==")
		st.savePreset(Preset(name="Nuevo", key="otra-clave"))
		self.assertEqual(RemoteStore(path).getPreset("Nuevo").key, "otra-clave")
		self.assertEqual(RemoteStore(path).getPreset("Viejo").key, "clave-en-claro")


class ClientHostModeTests(unittest.TestCase):
	"""El cliente de Tiresias aloja el servidor y se conecta como controlado."""

	def test_host_and_forward_speech(self) -> None:
		from tiresias.config import conf
		from tiresias.remote import client as clientModule
		from tiresias.remote import registerDefaults

		registerDefaults()
		conf["remote"]["playSounds"] = False
		conf["audio"]["playSounds"] = False
		origServer = clientModule.RelayServer
		clientModule.RelayServer = lambda port, key, certs: origServer(port, key, certs, bindHosts=("127.0.0.1",))
		self.addCleanup(setattr, clientModule, "RelayServer", origServer)
		folder = tempfile.mkdtemp(prefix="tiresias_host_")
		self.addCleanup(shutil.rmtree, folder, True)
		c = clientModule.RemoteClient(RemoteStore(os.path.join(folder, "r.json")), CertificateManager(folder))
		self.addCleanup(c.disconnect, True)
		info = ConnectionInfo(hostname="localhost", mode=ConnectionMode.FOLLOWER, key="clave-host", port=0)
		self.assertTrue(c.connect(info, hostPort=0))
		self.assertTrue(waitFor(lambda: c.isConnected))
		self.assertTrue(c.isFollower)
		port = c.hostPort
		self.assertTrue(port)
		self.assertIn(f":{port}?key=clave-host&mode=master", c.info.getURLToConnect())
		lt = RelayTransport("127.0.0.1", port, channel="clave-host", connectionType="master", insecure=True, trustedFingerprint=c.server.fingerprint)
		self.addCleanup(lt.close)
		lm = Recorder()
		leader = LeaderSession(lt, lm)
		lt.start()
		self.assertTrue(waitFor(lambda: c.session.hasLeaders and leader.hasFollowers))
		# Lo que «dice» el equipo controlado llega al que controla.
		c._onPreSpeech(["texto del equipo controlado"])
		c._onBeep(500, 30)
		self.assertTrue(waitFor(lambda: lm.of("speak") and lm.of("beep")))
		self.assertIn("texto del equipo controlado", lm.of("speak")[-1][1])
		self.assertIn("controlado por otro equipo", c.statusText())
		server = c.server
		c.disconnect(silent=True)
		self.assertIsNone(c.session)
		self.assertTrue(waitFor(lambda: not server.running))
		self.assertTrue(waitFor(lambda: not lt.connected))


if __name__ == "__main__":
	unittest.main()
