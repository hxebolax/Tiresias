"""Pruebas de la voz y el braille por Escritorio remoto (NVDA #3564).

No se abre ninguna sesión de Escritorio remoto ni se toca la configuración
del sistema:

- El registro del complemento se prueba bajo ``HKCU\\Software\\TiresiasPruebas``.
- La biblioteca ``tiresiasRdpClient.dll`` se carga con ``rdpTestHost.exe``,
  que hace de cliente de Escritorio remoto con objetos COM falsos.
- El lado remoto usa una tubería con las mismas cabeceras que el canal virtual.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import ctypes
import json
import os
import queue
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
import winreg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if "tiresias_test" not in os.path.basename(paths.DATA_DIR or ""):
	_TMPDATA = tempfile.mkdtemp(prefix="tiresias_test_rdp_")
	paths.setDataDir(_TMPDATA)
	paths.ensureDataDirs()

from tiresias.remote import rdp, rdp_io, serializer  # noqa: E402
from tiresias.remote.rdp_registration import (  # noqa: E402
	ADDIN_NAME,
	CITRIX_PLUGIN,
	CLSID,
	HORIZON_VALUES,
	CitrixRegistration,
	RdpRegistration,
	dllPath,
	unregisterIfFrom,
)
from tiresias.remote.session import LocalMachine  # noqa: E402

TIMEOUT = 10.0
TEST_ROOT = "Software\\TiresiasPruebas"
DLL64 = dllPath("x64", ROOT)
DLL86 = dllPath("x86", ROOT)
HOST64 = os.path.join(ROOT, "rdp", "test", "x64", "rdpTestHost.exe")
HOST86 = os.path.join(ROOT, "rdp", "test", "x86", "rdpTestHost.exe")


def waitFor(cond, timeout: float = TIMEOUT) -> bool:
	end = time.monotonic() + timeout
	while time.monotonic() < end:
		if cond():
			return True
		time.sleep(0.01)
	return cond()


def _keyExists(path: str) -> bool:
	try:
		winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY).Close()
		return True
	except OSError:
		return False


class Recorder(LocalMachine):
	"""Efectos locales de prueba: apunta lo que pide la sesión."""

	def __init__(self, owner=None) -> None:
		self.owner = owner
		self.calls: list[tuple] = []

	def speak(self, sequence: list, priority: int = 0) -> None:
		self.calls.append(("speak", list(sequence), priority))

	def cancelSpeech(self) -> None:
		self.calls.append(("cancel",))

	def display(self, cells: list[int]) -> None:
		self.calls.append(("display", list(cells)))

	def setBrailleDisplaySize(self, size: int) -> None:
		self.calls.append(("size", size))
		if self.owner is not None:
			self.owner._onBrailleSize(size)

	def onClientJoined(self, session, client: dict) -> None:
		self.calls.append(("joined", client.get("connection_type")))
		if self.owner is not None:
			self.owner._onPeerJoined(session, client)

	def onClientLeft(self, session, client: dict) -> None:
		self.calls.append(("left", client.get("connection_type")))
		if self.owner is not None:
			self.owner._onPeerLeft(session, client)

	def setReceivingBraille(self, state: bool) -> None:
		self.calls.append(("receiving", state))

	def of(self, kind: str) -> list[tuple]:
		return [c for c in self.calls if c[0] == kind]


def _direct(func, *args) -> None:
	func(*args)


# ====================================================================== registro
class RegistrationTests(unittest.TestCase):
	def setUp(self) -> None:
		self.sub = f"{TEST_ROOT}\\Rdp{uuid.uuid4().hex[:8]}"
		self.root = f"{self.sub}\\Software"
		self.realAddin = _keyExists(RdpRegistration().addinKey)

	def tearDown(self) -> None:
		RdpRegistration._deleteTree(self.sub)
		try:
			winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, TEST_ROOT, winreg.KEY_WOW64_64KEY, 0)
		except OSError:
			pass  # quedan otras pruebas o no existe
		self.assertFalse(_keyExists(self.sub), "La clave de pruebas no se ha borrado")
		# El registro real no se toca.
		self.assertEqual(_keyExists(RdpRegistration().addinKey), self.realAddin)

	def test_registerAndUnregister(self) -> None:
		if not (os.path.isfile(DLL64) and os.path.isfile(DLL86)):
			self.skipTest("Falta compilar rdp/build.py")
		reg = RdpRegistration(self.root)
		self.assertFalse(reg.isRegistered())
		done = reg.register({"x64": DLL64, "x86": DLL86})
		self.assertEqual(done, ["x64", "x86"])
		self.assertTrue(reg.isRegistered())
		self.assertEqual(reg.registeredPaths(), {"x64": os.path.abspath(DLL64), "x86": os.path.abspath(DLL86)})
		# Valores exactos que lee mstsc.exe.
		with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{self.root}\\Microsoft\\Terminal Server Client\\Default\\AddIns\\{ADDIN_NAME}") as k:
			self.assertEqual(winreg.QueryValueEx(k, "Name")[0], CLSID)
		with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{self.root}\\Classes\\CLSID\\{CLSID}\\InprocServer32") as k:
			self.assertEqual(winreg.QueryValueEx(k, "ThreadingModel")[0], "Free")
		self.assertTrue(_keyExists(f"{self.root}\\Classes\\WOW6432Node\\CLSID\\{CLSID}\\InprocServer32"))
		self.assertTrue(reg.pointsTo(ROOT))
		self.assertFalse(reg.pointsTo(tempfile.gettempdir()))
		self.assertTrue(reg.unregister())
		self.assertFalse(reg.isRegistered())
		self.assertFalse(_keyExists(f"{self.root}\\Classes\\CLSID\\{CLSID}"))
		self.assertFalse(_keyExists(f"{self.root}\\Classes\\WOW6432Node\\CLSID\\{CLSID}"))
		self.assertFalse(_keyExists(reg.addinKey))
		self.assertFalse(reg.unregister())

	def test_missingDll(self) -> None:
		reg = RdpRegistration(self.root)
		with self.assertRaises(FileNotFoundError):
			reg.register({"x64": os.path.join(tempfile.gettempdir(), "no_existe.dll")})
		self.assertFalse(_keyExists(reg.addinKey))

	def test_uninstallOnlyOwnCopy(self) -> None:
		if not os.path.isfile(DLL64):
			self.skipTest("Falta compilar rdp/build.py")
		reg = RdpRegistration(self.root)
		reg.register({"x64": DLL64})
		self.assertFalse(unregisterIfFrom(tempfile.gettempdir(), self.root))
		self.assertTrue(reg.isRegistered())
		self.assertTrue(unregisterIfFrom(ROOT, self.root))
		self.assertFalse(reg.isRegistered())

	def test_syncRegistrationRespectsOption(self) -> None:
		if not os.path.isfile(DLL64):
			self.skipTest("Falta compilar rdp/build.py")
		old = os.environ.get("TIRESIAS_RDP_REGROOT")
		os.environ["TIRESIAS_RDP_REGROOT"] = self.root
		try:
			reg = RdpRegistration()
			self.assertEqual(reg.root, self.root)
			# Desactivada al arrancar: no se registra nada.
			self.assertEqual(rdp.syncRegistration(False, startup=True), "")
			self.assertFalse(reg.isRegistered())
			self.assertEqual(rdp.syncRegistration(True), "registered")
			self.assertTrue(reg.isRegistered())
			self.assertEqual(rdp.syncRegistration(True), "")  # ya estaba
			self.assertEqual(rdp.syncRegistration(False), "unregistered")
			self.assertFalse(reg.isRegistered())
		finally:
			if old is None:
				os.environ.pop("TIRESIAS_RDP_REGROOT", None)
			else:
				os.environ["TIRESIAS_RDP_REGROOT"] = old


# ====================================================================== Citrix Workspace y Horizon (registro)
class _RootEnv:
	"""``TIRESIAS_RDP_REGROOT`` apuntando a la raíz de pruebas mientras dura el bloque."""

	def __init__(self, root: str) -> None:
		self.root = root

	def __enter__(self):
		self.old = os.environ.get("TIRESIAS_RDP_REGROOT")
		os.environ["TIRESIAS_RDP_REGROOT"] = self.root
		return self

	def __exit__(self, *exc) -> None:
		if self.old is None:
			os.environ.pop("TIRESIAS_RDP_REGROOT", None)
		else:
			os.environ["TIRESIAS_RDP_REGROOT"] = self.old


class CitrixRegistrationTests(unittest.TestCase):
	"""Configuración de usuario de Citrix Workspace simulada bajo la raíz de pruebas."""

	def setUp(self) -> None:
		self.sub = f"{TEST_ROOT}\\Ctx{uuid.uuid4().hex[:8]}"
		self.root = f"{self.sub}\\Software"
		self.realCitrix = _keyExists("Software\\Citrix\\ICA Client\\Engine\\Configuration\\Advanced\\Modules\\DVCPlugin_" + CITRIX_PLUGIN)

	def tearDown(self) -> None:
		RdpRegistration._deleteTree(self.sub)
		try:
			winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, TEST_ROOT, winreg.KEY_WOW64_64KEY, 0)
		except OSError:
			pass
		self.assertFalse(_keyExists(self.sub))
		# La configuración real de Citrix no se toca.
		self.assertEqual(_keyExists("Software\\Citrix\\ICA Client\\Engine\\Configuration\\Advanced\\Modules\\DVCPlugin_" + CITRIX_PLUGIN), self.realCitrix)

	def _firstSession(self, plugins: str = "VDTUIProxy,MsTeams") -> CitrixRegistration:
		"""Lo que hace Citrix al abrir la primera sesión: copia su configuración al usuario."""
		ctx = CitrixRegistration(self.root, installed=lambda: True)
		with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, ctx.adapterKey, 0, winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as k:
			winreg.SetValueEx(k, "DvcPlugins", 0, winreg.REG_SZ, plugins)
		return ctx

	def _plugins(self, ctx: CitrixRegistration) -> str:
		with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ctx.adapterKey, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
			return winreg.QueryValueEx(k, "DvcPlugins")[0]

	def test_states(self) -> None:
		self.assertEqual(CitrixRegistration(self.root, installed=lambda: False).state(), CitrixRegistration.NOT_INSTALLED)
		pending = CitrixRegistration(self.root, installed=lambda: True)
		self.assertEqual(pending.state(), CitrixRegistration.NO_SESSION)
		# Sin la configuración de usuario no se escribe nada.
		self.assertFalse(pending.register())
		self.assertFalse(_keyExists(pending.pluginKey))
		ctx = self._firstSession()
		self.assertEqual(ctx.state(), CitrixRegistration.READY)

	def test_registerKeepsOtherPlugins(self) -> None:
		ctx = self._firstSession()
		self.assertTrue(ctx.register())
		self.assertEqual(ctx.state(), CitrixRegistration.REGISTERED)
		self.assertEqual(self._plugins(ctx), f"VDTUIProxy,MsTeams,{CITRIX_PLUGIN}")
		with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ctx.pluginKey) as k:
			self.assertEqual(winreg.QueryValueEx(k, "PluginClassId")[0], CLSID)
			self.assertEqual(winreg.QueryValueEx(k, "DvcNames")[0], CITRIX_PLUGIN)
		self.assertTrue(ctx.pluginKey.endswith("\\Modules\\DVCPlugin_TiresiasRdp"))
		# Registrar otra vez no duplica el nombre.
		self.assertTrue(ctx.register())
		self.assertEqual(self._plugins(ctx), f"VDTUIProxy,MsTeams,{CITRIX_PLUGIN}")
		self.assertTrue(ctx.unregister())
		self.assertEqual(self._plugins(ctx), "VDTUIProxy,MsTeams")
		self.assertFalse(_keyExists(ctx.pluginKey))
		self.assertFalse(ctx.unregister())

	def test_emptyPluginList(self) -> None:
		ctx = self._firstSession("")
		self.assertTrue(ctx.register())
		self.assertEqual(self._plugins(ctx), CITRIX_PLUGIN)
		ctx.unregister()
		self.assertEqual(self._plugins(ctx), "")

	def test_horizonValues(self) -> None:
		if not os.path.isfile(DLL64):
			self.skipTest("Falta compilar rdp/build.py")
		reg = RdpRegistration(self.root)
		reg.register({"x64": DLL64})
		self.assertTrue(reg.horizonEnabled())
		with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg.addinKey) as k:
			for name in HORIZON_VALUES:
				self.assertEqual(winreg.QueryValueEx(k, name), (1, winreg.REG_DWORD))
		# Un registro anterior sin esos valores se completa al sincronizar.
		with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg.addinKey, 0, winreg.KEY_SET_VALUE) as k:
			winreg.DeleteValue(k, "Horizon Enabled")
		self.assertFalse(reg.horizonEnabled())
		with _RootEnv(self.root):
			self.assertEqual(rdp.syncRegistration(True), "registered")
			self.assertTrue(reg.horizonEnabled())

	def test_syncCitrixNeedsComRegistration(self) -> None:
		if not os.path.isfile(DLL64):
			self.skipTest("Falta compilar rdp/build.py")
		ctx = self._firstSession()
		with _RootEnv(self.root):
			# Sin el objeto COM registrado, Citrix no podría crearlo.
			self.assertEqual(rdp.syncCitrix(True), "missing")
			self.assertFalse(ctx.isRegistered())
			self.assertEqual(rdp.syncRegistration(True), "registered")
			self.assertEqual(rdp.syncCitrix(True), "registered")
			self.assertTrue(ctx.isRegistered())
			self.assertEqual(rdp.syncCitrix(True), "")
			self.assertEqual(rdp.syncCitrix(False), "unregistered")
			self.assertFalse(ctx.isRegistered())
			self.assertEqual(rdp.syncCitrix(False), "")
			# La desinstalación quita también la entrada de Citrix.
			self.assertEqual(rdp.syncCitrix(True), "registered")
		self.assertTrue(unregisterIfFrom(ROOT, self.root))
		self.assertFalse(ctx.isRegistered())
		self.assertEqual(self._plugins(ctx), "VDTUIProxy,MsTeams")

	def test_watcherRegistersAfterFirstSession(self) -> None:
		if not os.path.isfile(DLL64):
			self.skipTest("Falta compilar rdp/build.py")
		with _RootEnv(self.root):
			self.assertEqual(rdp.syncRegistration(True), "registered")
			self.assertIn(rdp.syncCitrix(True), ("pending", "notInstalled"))
			done = threading.Event()
			watcher = rdp._CitrixWatcher(interval=0.05, onRegistered=done.set, isWanted=lambda: True)
			watcher.start()
			try:
				time.sleep(0.2)
				self.assertFalse(done.is_set())
				# El usuario abre su primera sesión de Citrix.
				ctx = self._firstSession()
				self.assertTrue(done.wait(TIMEOUT))
				self.assertTrue(ctx.isRegistered())
			finally:
				watcher.stop()
			self.assertTrue(waitFor(lambda: not watcher.running))

	def test_allowListEntry(self) -> None:
		exe = os.path.join("C:\\", "Program Files", "Tiresias", "Tiresias.exe")
		self.assertEqual(rdp.citrixAllowListEntry(exe), f"{exe},TiresiasRdp,TiresiasRdp")


class PanelTests(unittest.TestCase):
	"""Panel «Escritorio remoto» de Opciones: la opción de Citrix depende de la recepción."""

	def test_citrixOptionFollowsReceive(self) -> None:
		import wx

		from tiresias.config import conf
		from tiresias.gui import rdp_panel

		app = wx.App.Get() or wx.App(False)
		self.assertIsNotNone(app)
		rdp.registerDefaults()
		old = (conf["rdp"]["receiveFromRemote"], conf["rdp"]["citrixClient"])
		conf["rdp"]["receiveFromRemote"] = False
		frame = wx.Frame(None)
		try:
			panel = rdp_panel.RdpPanel(frame)
			receive = panel.getControl("receiveFromRemote")
			citrix = panel.getControl("citrixClient")
			self.assertIsNotNone(citrix)
			self.assertFalse(citrix.IsEnabled())
			receive.SetValue(True)
			panel._onReceiveToggled()
			self.assertTrue(citrix.IsEnabled())
			texts = [c.GetValue() for c in panel.GetChildren() if isinstance(c, wx.TextCtrl)]
			self.assertIn(rdp.citrixAllowListEntry(), texts)
			self.assertTrue(any(isinstance(c, wx.Button) and "Citrix" in c.GetLabel() for c in panel.GetChildren()))
		finally:
			frame.Destroy()
			conf["rdp"]["receiveFromRemote"], conf["rdp"]["citrixClient"] = old


# ====================================================================== tipo de sesión remota (servidor)
class _NoMetrics:
	@staticmethod
	def GetSystemMetrics(index: int) -> int:
		return 0


class SessionKindTests(unittest.TestCase):
	def _kind(self, protocol, horizon: bool = False) -> tuple[str, bool]:
		from unittest import mock

		with mock.patch.object(rdp_io, "clientProtocol", return_value=protocol), mock.patch.object(rdp_io, "isHorizonSession", return_value=horizon), mock.patch.object(rdp_io, "user32", _NoMetrics):
			return rdp_io.remoteKind(), rdp_io.isRemoteSession()

	def test_kinds(self) -> None:
		self.assertEqual(self._kind(rdp_io.PROTOCOL_ICA), ("citrix", True))
		self.assertEqual(self._kind(rdp_io.PROTOCOL_RDP), ("rdp", True))
		self.assertEqual(self._kind(rdp_io.PROTOCOL_RDP, horizon=True), ("horizon", True))
		self.assertEqual(self._kind(rdp_io.PROTOCOL_CONSOLE, horizon=True), ("horizon", True))
		self.assertEqual(self._kind(rdp_io.PROTOCOL_CONSOLE), ("", False))
		self.assertEqual(self._kind(None), ("", False))

	def test_realSessionQuery(self) -> None:
		# En el equipo de pruebas: consola o Escritorio remoto, nunca un error.
		self.assertIn(rdp_io.clientProtocol(), (0, 1, 2, None))
		self.assertIn(rdp_io.remoteKind(), ("", "rdp", "citrix", "horizon"))

	def test_channelApiChoice(self) -> None:
		from unittest import mock

		class FakeBridge:
			VDP_VirtualChannelOpenEx = VDP_VirtualChannelQuery = VDP_VirtualChannelClose = VDP_FreeMemory = staticmethod(lambda *a: 0)

		with mock.patch.object(rdp_io, "isHorizonSession", return_value=True), mock.patch.object(rdp_io, "_horizonBridge", return_value=FakeBridge()):
			self.assertEqual(rdp_io.channelApi().name, "VDP")
		with mock.patch.object(rdp_io, "isHorizonSession", return_value=False):
			self.assertEqual(rdp_io.channelApi().name, "WTS")

	def test_openDynamicChannelWithBridgeApi(self) -> None:
		"""Las funciones de canal (WTS o VDP) devuelven un identificador de archivo que se duplica."""
		name = f"\\\\.\\pipe\\TiresiasRdpCanal.{uuid.uuid4().hex}"
		accepted: queue.Queue = queue.Queue()
		listener = rdp_io.PipeListener(name, lambda stream, pid: accepted.put(stream), messageMode=True)
		listener.start()
		calls: list[str] = []
		try:
			self.assertTrue(listener.listening.wait(TIMEOUT))
			raw = rdp_io.connectPipe(name)
			peer = accepted.get(timeout=TIMEOUT)
			box = ctypes.c_void_p(raw.handle)

			def openEx(session, channel, flags):
				calls.append(f"open {channel.decode()} {flags}")
				return 0x1234

			def query(h, cls, pBuf, pSize):
				calls.append(f"query {h:#x} {cls}")
				pBuf._obj.value = ctypes.addressof(box)
				pSize._obj.value = ctypes.sizeof(box)
				return True

			api = rdp_io.ChannelApi(openEx, query, lambda h: calls.append(f"close {h:#x}") or True, lambda p: calls.append("free"), name="VDP")
			stream = rdp_io.openDynamicChannel(api=api)
			raw.close()  # el identificador original lo cierra la API; queda el duplicado
			self.assertEqual(calls, ["open TiresiasRdp 1", "query 0x1234 1", "free", "close 0x1234"])
			payload = b'{"type":"cancel"}\n'
			peer.write(struct.pack("<II", len(payload), 3) + payload)
			self.assertEqual(stream.read(), payload)
			stream.close()
			peer.close()
			# Si el cliente no tiene el complemento, el error lleva el nombre de la API.
			failing = rdp_io.ChannelApi(lambda *a: 0, query, lambda h: True, lambda p: None, name="VDP")
			with self.assertRaises(OSError) as cm:
				rdp_io.openDynamicChannel(api=failing)
			self.assertIn("VDPVirtualChannelOpenEx", str(cm.exception))
		finally:
			listener.stop()


# ====================================================================== programa cliente (braille en primer plano)
class _DummyStream:
	def close(self) -> None:
		pass


class ClientProgramTests(unittest.TestCase):
	PROCS = {
		100: ("vmware-remotemks.exe", 50),
		50: ("horizon-client.exe", 4),
		200: ("mstsc.exe", 60),
		60: ("explorer.exe", 4),
		300: ("wfica32.exe", 60),
	}

	def _client(self) -> rdp.RdpClientSide:
		return rdp.RdpClientSide(pipeName="\\\\.\\pipe\\TiresiasRdpNoUsada", dispatch=_direct, tiresiasHooks=False, machineFactory=Recorder, processInfo=lambda pid: self.PROCS.get(pid, ("", 0)))

	def test_foregroundFollowsClientWindow(self) -> None:
		client = self._client()
		links = {pid: rdp._Link(client, _DummyStream(), pid) for pid in (100, 200, 300)}
		client.links.extend(links.values())
		self.assertEqual(links[100].windowPids, {100, 50})
		# El padre de mstsc.exe es el Explorador: no cuenta como ventana de la conexión.
		self.assertEqual(links[200].windowPids, {200})
		self.assertEqual(links[300].exe, "wfica32.exe")
		client._setForegroundPid(50)
		self.assertEqual([p for p, link in links.items() if link.active], [100])
		client._setForegroundPid(60)
		self.assertFalse(any(link.active for link in links.values()))
		client._setForegroundPid(300)
		self.assertEqual([p for p, link in links.items() if link.active], [300])
		self.assertIn(("receiving", True), links[300].machine.calls)
		self.assertEqual(rdp.CLIENT_PROGRAMS[links[300].exe], "Citrix Workspace")

	def test_realProcessInfo(self) -> None:
		exe, parent = rdp_io.processInfo(os.getpid())
		self.assertTrue(exe.lower().startswith("python"))
		self.assertEqual(parent, os.getppid())
		self.assertEqual(rdp_io.processInfo(0xFFFFFFF0), ("", 0))


# ====================================================================== tubería y transporte
class PipeTransportTests(unittest.TestCase):
	def test_linesBothWays(self) -> None:
		name = f"\\\\.\\pipe\\TiresiasRdpPrueba.{uuid.uuid4().hex}"
		accepted: queue.Queue = queue.Queue()
		listener = rdp_io.PipeListener(name, lambda stream, pid: accepted.put((stream, pid)))
		listener.start()
		try:
			self.assertTrue(listener.listening.wait(TIMEOUT))
			client = rdp_io.connectPipe(name)
			serverStream, pid = accepted.get(timeout=TIMEOUT)
			self.assertEqual(pid, os.getpid())
			received: list[dict] = []
			lost = threading.Event()
			t = rdp.StreamTransport(serverStream)
			t.onMessage = received.append
			t.onDisconnected = lost.set
			t.start()
			# Dos mensajes en una escritura y otro partido en dos.
			client.write(serializer.serialize("speak", sequence=["uno"], priority=0) + serializer.serialize("cancel"))
			part = serializer.serialize("speak", sequence=["dos"], priority=1)
			client.write(part[:5])
			client.write(part[5:])
			self.assertTrue(waitFor(lambda: len(received) == 3))
			self.assertEqual(received[0]["sequence"], ["uno"])
			self.assertEqual(received[1]["type"], "cancel")
			self.assertEqual(received[2]["sequence"], ["dos"])
			self.assertTrue(t.send("set_braille_info", name="noBraille", numCells=40))
			data = client.read()
			self.assertEqual(json.loads(data.decode("utf-8").strip())["numCells"], 40)
			client.close()
			self.assertTrue(lost.wait(TIMEOUT))
			self.assertFalse(t.connected)
			self.assertFalse(t.send("cancel"))
			t.join()
		finally:
			listener.stop()
		self.assertFalse(listener.running)

	def test_pduHeaderIsRemoved(self) -> None:
		name = f"\\\\.\\pipe\\TiresiasRdpPrueba.{uuid.uuid4().hex}"
		accepted: queue.Queue = queue.Queue()
		listener = rdp_io.PipeListener(name, lambda stream, pid: accepted.put(stream), messageMode=True)
		listener.start()
		try:
			self.assertTrue(listener.listening.wait(TIMEOUT))
			channel = rdp_io.openPipeAsChannel(name)
			fake = accepted.get(timeout=TIMEOUT)
			payload = b'{"type":"cancel"}\n'
			fake.write(struct.pack("<II", len(payload), 3) + payload)
			self.assertEqual(channel.read(), payload)
			channel.close()
			fake.close()
		finally:
			listener.stop()

	def test_closeWakesBlockedRead(self) -> None:
		name = f"\\\\.\\pipe\\TiresiasRdpPrueba.{uuid.uuid4().hex}"
		accepted: queue.Queue = queue.Queue()
		listener = rdp_io.PipeListener(name, lambda stream, pid: accepted.put(stream))
		listener.start()
		try:
			self.assertTrue(listener.listening.wait(TIMEOUT))
			client = rdp_io.connectPipe(name)
			server = accepted.get(timeout=TIMEOUT)
			result: list[bytes] = []
			t = threading.Thread(target=lambda: result.append(server.read()))
			t.start()
			time.sleep(0.2)
			server.close()
			t.join(TIMEOUT)
			self.assertFalse(t.is_alive())
			self.assertEqual(result, [b""])
			client.close()
		finally:
			listener.stop()


# ====================================================================== lado remoto (servidor)
class ServerSideTests(unittest.TestCase):
	def setUp(self) -> None:
		self.name = f"\\\\.\\pipe\\TiresiasRdpCanal.{uuid.uuid4().hex}"
		self.accepted: queue.Queue = queue.Queue()
		self.listener = rdp_io.PipeListener(self.name, lambda stream, pid: self.accepted.put(stream), messageMode=True)
		self.listener.start()
		self.assertTrue(self.listener.listening.wait(TIMEOUT))
		self.server = rdp.RdpServerSide(openChannel=lambda: rdp_io.openPipeAsChannel(self.name), isRemote=lambda: True, dispatch=_direct, tiresiasHooks=False)
		self.recorder = Recorder(self.server)
		self.server.machine = self.recorder
		self.server.start()
		# El extremo «cliente» del canal simulado.
		self.peer = self.accepted.get(timeout=TIMEOUT)
		self.lines: queue.Queue = queue.Queue()
		self._reader = threading.Thread(target=self._readPeer, daemon=True)
		self._reader.start()
		self.assertTrue(waitFor(lambda: self.server.session is not None))

	def tearDown(self) -> None:
		self.server.stop()
		self.peer.close()
		self.listener.stop()

	def _readPeer(self) -> None:
		buf = b""
		while True:
			data = self.peer.read()
			if not data:
				return
			buf += data
			*lines, buf = buf.split(b"\n")
			for line in lines:
				if line.strip():
					self.lines.put(json.loads(line))

	def _sendToServer(self, type: str, **payload) -> None:
		data = serializer.serialize(type, **payload)
		# Como el canal real: cabecera CHANNEL_PDU_HEADER y trozos de 1600 bytes.
		for i in range(0, len(data), 1600):
			chunk = data[i : i + 1600]
			flags = (1 if i == 0 else 0) | (2 if i + 1600 >= len(data) else 0)
			self.peer.write(struct.pack("<II", len(data), flags) + chunk)

	def test_speechOnlyWhileClientListens(self) -> None:
		self.server._onPreSpeech(["antes"])
		self.assertFalse(self.server.listening)
		self._sendToServer("client_joined", client={"id": "rdp", "connection_type": "master"})
		self.assertTrue(waitFor(lambda: self.server.listening))
		self.assertTrue(self.server._muted, "Por defecto se silencia la voz local mientras el cliente escucha")
		self._sendToServer("set_braille_info", name="baum", numCells=40)
		self.assertTrue(waitFor(lambda: ("size", 40) in self.recorder.calls))
		self.server._onPreSpeech(["Hola desde la sesión remota"])
		self.server._onSpeechCanceled()
		self.server._onDisplayUpdate([1, 2, 3])
		self.server._onBeep(440, 50)
		msg = self.lines.get(timeout=TIMEOUT)
		self.assertEqual(msg["type"], "speak")
		self.assertEqual(msg["sequence"], ["Hola desde la sesión remota"])
		self.assertEqual(self.lines.get(timeout=TIMEOUT)["type"], "cancel")
		self.assertEqual(self.lines.get(timeout=TIMEOUT)["cells"], [1, 2, 3])
		self.assertEqual(self.lines.get(timeout=TIMEOUT)["type"], "tone")
		# Mensaje largo (varios trozos con cabecera).
		long = "x" * 5000
		self._sendToServer("speak", sequence=[long], priority=0)
		# La biblioteca avisa de que el Tiresias del cliente se ha ido.
		self._sendToServer("client_left", client={"id": "rdp", "connection_type": "master"})
		self.assertTrue(waitFor(lambda: not self.server.listening))
		self.assertFalse(self.server._muted)
		self.assertIn(("size", 0), self.recorder.calls)
		self.server._onPreSpeech(["después"])
		time.sleep(0.2)
		self.assertTrue(self.lines.empty())

	def test_keysAndClipboardAreIgnored(self) -> None:
		machine = rdp.RdpMachine(self.server)
		# Nada de esto debe tener efecto (ni excepciones).
		machine.sendKey(0x41, False, True)
		machine.setClipboardText("x")
		machine.sendSAS()

	def test_channelLossDetaches(self) -> None:
		self._sendToServer("client_joined", client={"id": "rdp", "connection_type": "master"})
		self.assertTrue(waitFor(lambda: self.server.listening))
		self.peer.close()
		self.assertTrue(waitFor(lambda: self.server.session is None))
		self.assertFalse(self.server._muted)


# ====================================================================== biblioteca de mstsc
class _Host:
	"""``rdpTestHost.exe``: cliente de Escritorio remoto simulado."""

	def __init__(self, exe: str, dll: str) -> None:
		self.proc = subprocess.Popen([exe, dll], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		self.out: queue.Queue = queue.Queue()
		self.lines: list[str] = []
		threading.Thread(target=self._read, daemon=True).start()

	def _read(self) -> None:
		for raw in self.proc.stdout:
			line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
			self.lines.append(line)
			self.out.put(line)

	def cmd(self, text: str) -> None:
		self.proc.stdin.write(text.encode("utf-8") + b"\n")
		self.proc.stdin.flush()

	def expect(self, prefix: str, timeout: float = TIMEOUT) -> str:
		end = time.monotonic() + timeout
		while time.monotonic() < end:
			try:
				line = self.out.get(timeout=max(0.01, end - time.monotonic()))
			except queue.Empty:
				break
			if line.startswith(prefix):
				return line
		raise AssertionError(f"No llegó {prefix!r}; salida: {self.lines}")

	def writes(self) -> list[dict]:
		out = []
		for line in self.lines:
			if line.startswith("WRITE ") and line[6:].strip():
				out.append(json.loads(line[6:]))
		return out

	def finish(self) -> None:
		if self.proc.stdin.closed:
			return
		try:
			self.cmd("quit")
		except (OSError, ValueError):
			pass
		try:
			self.proc.wait(TIMEOUT)
		finally:
			if self.proc.poll() is None:
				self.proc.kill()
			for f in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
				try:
					f.close()
				except OSError:
					pass


class ClientDllTests(unittest.TestCase):
	def _run(self, exe: str, dll: str) -> None:
		if not (os.path.isfile(exe) and os.path.isfile(dll)):
			self.skipTest("Falta compilar rdp/build.py")
		recorders: list[Recorder] = []

		def factory(owner):
			r = Recorder()
			recorders.append(r)
			return r

		client = rdp.RdpClientSide(dispatch=_direct, tiresiasHooks=False, machineFactory=factory)
		client.start()
		if not waitFor(lambda: client._listener.listening.is_set(), 3):
			client.stop()
			self.skipTest(f"La tubería {client.pipeName} está ocupada (¿otro Tiresias recibe la voz de Escritorio remoto?)")
		host = _Host(exe, dll)
		try:
			host.expect("LOADED")
			self.assertEqual(host.expect("LISTEN"), "LISTEN TiresiasRdp")
			host.cmd("open")
			host.expect("ACCEPT 1")
			# El Tiresias local se anuncia y envía el tamaño de su línea.
			self.assertTrue(waitFor(lambda: len(client.links) == 1))
			self.assertTrue(waitFor(lambda: any(w.get("type") == "set_braille_info" for w in host.writes())))
			kinds = [w["type"] for w in host.writes()]
			self.assertEqual(kinds[:2], ["client_joined", "set_braille_info"])
			self.assertEqual(host.writes()[0]["client"]["connection_type"], "master")
			# Lo que «dice» el equipo remoto llega a Tiresias.
			host.cmd("send " + serializer.serialize("speak", sequence=["Hola desde el equipo remoto"], priority=0).decode("utf-8").strip())
			host.cmd("send " + serializer.serialize("cancel").decode("utf-8").strip())
			host.cmd("send " + serializer.serialize("display", cells=[7, 8]).decode("utf-8").strip())
			rec = recorders[0]
			self.assertTrue(waitFor(lambda: rec.of("display")))
			self.assertEqual(rec.of("speak")[0][1], ["Hola desde el equipo remoto"])
			self.assertEqual(len(rec.of("cancel")), 1)
			self.assertEqual(rec.of("display")[0][1], [7, 8])
			# Tiresias se cierra: la biblioteca avisa al equipo remoto.
			client.stop()
			self.assertTrue(waitFor(lambda: any(w.get("type") == "client_left" for w in host.writes())))
			# Vuelve a arrancar: la biblioteca se reconecta sola.
			client.start()
			self.assertTrue(waitFor(lambda: len(client.links) == 1))
			self.assertTrue(waitFor(lambda: [w["type"] for w in host.writes()].count("client_joined") == 2))
			host.cmd("close")
			host.expect("CLOSED")
			self.assertTrue(waitFor(lambda: not client.links))
			host.finish()
			self.assertIn("UNLOAD S_OK", host.lines)
			self.assertIn("REFS channel=1 listener=1", host.lines)
		finally:
			host.finish()
			client.stop()

	def test_x64(self) -> None:
		self._run(HOST64, DLL64)

	def test_x86(self) -> None:
		self._run(HOST86, DLL86)

	def test_withoutTiresiasDataIsDropped(self) -> None:
		if not (os.path.isfile(HOST64) and os.path.isfile(DLL64)):
			self.skipTest("Falta compilar rdp/build.py")
		host = _Host(HOST64, DLL64)
		try:
			host.expect("LOADED")
			host.cmd("open")
			host.expect("ACCEPT 1")
			host.cmd("send " + serializer.serialize("speak", sequence=["nadie escucha"]).decode("utf-8").strip())
			host.expect("SENT")
			host.cmd("close")
			host.expect("CLOSED")
			host.finish()
			self.assertIn("UNLOAD S_OK", host.lines)
		finally:
			host.finish()


if __name__ == "__main__":
	unittest.main()
