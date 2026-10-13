"""Regresiones de la revisión 1.0.6: acceso remoto, Escritorio remoto y productividad.

Una prueba (o un grupo) por cada fallo de la auditoría de ``remote/`` y
``productivity/``. No se conecta a ningún servidor (las sesiones usan
transportes falsos), no se inyectan teclas ni se toca el registro real.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import gc
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if "tiresias_test" not in os.path.basename(paths.DATA_DIR or ""):
	# Nunca se toca la carpeta de datos real.
	_TMPDATA = tempfile.mkdtemp(prefix="tiresias_test_rev106_remoto_")
	paths.setDataDir(_TMPDATA)
	paths.ensureDataDirs()

from tiresias import queue_handler  # noqa: E402
from tiresias.remote import rdp  # noqa: E402
from tiresias.remote.certs import CertificateManager  # noqa: E402
from tiresias.remote.protocol import ConnectionInfo, ConnectionMode  # noqa: E402
from tiresias.remote.session import FollowerSession, LeaderSession, LocalMachine  # noqa: E402
from tiresias.remote.store import KIND_HOST, Preset, RemoteStore  # noqa: E402

TIMEOUT = 10.0


def waitFor(cond, timeout: float = TIMEOUT) -> bool:
	end = time.monotonic() + timeout
	while time.monotonic() < end:
		if cond():
			return True
		time.sleep(0.01)
	return cond()


class _FakeTransport:
	connected = True
	reconnect = True
	addressKey = "prueba"

	def __init__(self) -> None:
		self.sent: list[tuple[str, dict]] = []
		self.onMessage = None

	def send(self, type, **payload):
		self.sent.append((type.value if hasattr(type, "value") else type, payload))
		return True

	def close(self):
		pass

	def stopReconnecting(self):
		self.reconnect = False

	def types(self) -> list[str]:
		return [t for t, _p in self.sent]


def _client(folder: str):
	from tiresias.remote.client import RemoteClient

	return RemoteClient(RemoteStore(os.path.join(folder, "r.json")), CertificateManager(folder))


# ====================================================================== 1. aviso de sesión
class SessionLockWndProcTests(unittest.TestCase):
	"""La clase de ventana usa un único procedimiento del módulo que nunca se libera."""

	def test_second_monitor_after_first_is_freed(self) -> None:
		from tiresias.remote import session_lock

		self.assertIsInstance(session_lock._WNDPROC, session_lock.WNDPROC)
		for round_ in range(2):
			got: list[bool] = []
			mon = session_lock.SessionLockMonitor(got.append)
			# El monitor ya no tiene un procedimiento propio que pueda liberarse.
			self.assertFalse(hasattr(mon, "_proc"))
			mon.start()
			try:
				self.assertTrue(mon.hwnd, f"vuelta {round_}")
				self.assertIs(session_lock._monitors.get(mon.hwnd), mon)
				session_lock._user32.PostMessageW(mon.hwnd, session_lock.WM_WTSSESSION_CHANGE, session_lock.WTS_SESSION_LOCK, 0)
				self.assertTrue(waitFor(lambda got=got: got == [True]))
			finally:
				hwnd = mon.hwnd
				mon.stop()
			self.assertIsNone(mon.hwnd)
			self.assertNotIn(hwnd, session_lock._monitors)
			# El primer monitor desaparece del todo antes de crear el segundo.
			del mon
			gc.collect()


# ====================================================================== 2. set_braille_info sin bucle
class BrailleInfoLoopTests(unittest.TestCase):
	def test_leader_does_not_answer_other_leader(self) -> None:
		t = _FakeTransport()
		leader = LeaderSession(t, LocalMachine())
		t.sent.clear()
		# Otro equipo que controla anuncia su línea (como hace NVDA al recibir la nuestra).
		for _i in range(5):
			leader._onMessage({"type": "set_braille_info", "name": "baum", "numCells": 40, "origin": 7})
		self.assertNotIn("set_braille_info", t.types())

	def test_leader_announces_when_client_joins(self) -> None:
		t = _FakeTransport()
		leader = LeaderSession(t, LocalMachine())
		leader.setBrailleInfo("baum", 40)
		leader._onMessage({"type": "client_joined", "client": {"id": 3, "connection_type": "slave"}})
		self.assertEqual(t.types().count("set_braille_info"), 1)

	def test_two_leaders_exchange_finitely(self) -> None:
		"""Dos equipos que controlan unidos por un canal: los mensajes se acaban."""
		ta, tb = _FakeTransport(), _FakeTransport()
		a = LeaderSession(ta, LocalMachine())
		b = LeaderSession(tb, LocalMachine())
		a._onMessage({"type": "client_joined", "client": {"id": "b", "connection_type": "master"}})
		b._onMessage({"type": "client_joined", "client": {"id": "a", "connection_type": "master"}})
		for _round in range(20):
			pending = [(b, m) for m in ta.sent] + [(a, m) for m in tb.sent]
			ta.sent.clear()
			tb.sent.clear()
			if not pending:
				break
			for target, (typ, payload) in pending:
				target._onMessage(dict(payload, type=typ, origin="x"))
		self.assertEqual(ta.sent + tb.sent, [])


# ====================================================================== 3. aviso de incoherencias por línea
class _Info:
	def __init__(self, bookmark=1) -> None:
		self.bookmark = bookmark


class _Gesture:
	def __init__(self) -> None:
		self.sent = 0

	def send(self) -> None:
		self.sent += 1


class CaretMovedTests(unittest.TestCase):
	def setUp(self) -> None:
		from tiresias.objects import behaviors

		self.behaviors = behaviors
		self.order: list[str] = []
		self.handler = lambda obj=None, info=None, unit="": self.order.append(f"movido:{unit}")
		behaviors.post_caretMoved.register(self.handler)
		self.addCleanup(behaviors.post_caretMoved.unregister, self.handler)

	def test_helper_notifies_after_speaking_new_line(self) -> None:
		from tiresias import presentation, review, speech
		from tiresias.objects.behaviors import EditableText

		order = self.order
		captured = {}

		class Fake:
			def _getCaretInfo(self):
				return _Info(2)

			def _startWatch(self, old, done, selection=False):
				captured["done"] = done

		gesture = _Gesture()
		with mock.patch.object(presentation, "speakTextInfo", side_effect=lambda *a, **k: order.append("línea")), mock.patch.object(
			review, "handleCaretMove", lambda *a, **k: None
		), mock.patch.object(speech, "cancelSpeech", side_effect=lambda: order.append("cancelar")):
			EditableText._caretMovementScriptHelper(Fake(), gesture, "line")
			self.assertEqual(gesture.sent, 1)
			# Antes de que termine la vigilancia del cursor no se avisa de nada.
			self.assertEqual(order, [])
			captured["done"](_Info(3), True)
		self.assertEqual(order, ["cancelar", "línea", "movido:line"])

	def test_word_line_move_notifies_after_reading(self) -> None:
		from tiresias import presentation, review, speech
		from tiresias.appmodules import _office, winword

		order = self.order

		class Fake:
			def _app(self):
				return None

			def _hwnd(self):
				return 0

		def fakeCallAsync(func, *args, callback=None, onError=None, timeout=None, **kw):
			onError(RuntimeError("sin Word"))

		with mock.patch.object(_office, "callAsync", fakeCallAsync), mock.patch.object(
			presentation, "speakTextInfo", side_effect=lambda *a, **k: order.append("línea")
		), mock.patch.object(review, "handleCaretMove", lambda *a, **k: None), mock.patch.object(speech, "cancelSpeech", lambda: None):
			winword.WordDocument._afterLineMove(Fake(), _Info())
		self.assertEqual(order, ["línea", "movido:line"])

	def test_productivity_reports_after_caret_moved(self) -> None:
		from tiresias import productivity, speech
		from tiresias.config import conf
		from tiresias.productivity import plugin, text_analyzer
		from tiresias.speech import api as speechApi
		from tiresias.speech.commands import WaveFileCommand

		productivity.registerDefaults()
		c = conf["textAnalyzer"]
		old = (c["lineSound"], c["lineSpeak"])
		self.addCleanup(lambda: (c.__setitem__("lineSound", old[0]), c.__setitem__("lineSpeak", old[1])))
		c["lineSound"] = True
		c["lineSpeak"] = True
		# Las órdenes de los campos de edición ya no se analizan al ejecutarse
		# (el cursor aún no se ha movido): solo las del modo exploración.
		self.assertNotIn("script_caret_moveByLine", plugin.LINE_SCRIPTS)
		self.assertIn("script_nextLine", plugin.LINE_SCRIPTS)
		issue = text_analyzer.analyze("hola  mundo", plugin.analyzerChecks())
		self.assertTrue(issue)
		obj = object()
		calls: list = []
		spoken: list = []
		with mock.patch.object(plugin, "_lineIssuesAtCaret", side_effect=lambda o=None: calls.append(o) or (issue, "hola  mundo")), mock.patch.object(
			speech, "speak", side_effect=lambda seq, *a, **k: spoken.append(list(seq))
		), mock.patch.object(speechApi, "getSpeechMode", return_value=speechApi.SpeechMode.talk):
			plugin._onScriptExecuted(script=type("S", (), {"__name__": "script_caret_moveByLine"})())
			self.assertEqual(calls, [])
			plugin._onCaretMoved(obj=obj, info=_Info(), unit="character")
			self.assertEqual(calls, [])
			plugin._onCaretMoved(obj=obj, info=_Info(), unit="line")
		self.assertEqual(calls, [obj])
		self.assertEqual(len(spoken), 1)
		# Sonido y descripción en la cola, detrás de la línea (sin cancelar la voz).
		self.assertIsInstance(spoken[0][0], WaveFileCommand)
		self.assertEqual(spoken[0][0].name, "textIssue")
		self.assertEqual(spoken[0][1], text_analyzer.describe(issue))

	def test_plugin_registers_caret_moved(self) -> None:
		from tiresias.productivity import plugin

		p = plugin.ProductivityGlobalPlugin()
		try:
			self.assertIn(plugin._onCaretMoved, list(self.behaviors.post_caretMoved.handlers()))
		finally:
			p.terminate()
		self.assertNotIn(plugin._onCaretMoved, list(self.behaviors.post_caretMoved.handlers()))


# ====================================================================== 4. teclas de productividad y PuTTY
class GestureConflictTests(unittest.TestCase):
	NEW = ("kb:tiresias+control+shift+alt+n", "kb:tiresias+control+shift+alt+v")
	OLD = ("kb:tiresias+shift+alt+n", "kb:tiresias+shift+alt+v")

	@staticmethod
	def _norm(g: str) -> str:
		order = ["tiresias", "control", "shift", "alt", "windows"]
		pre, _s, keys = g.lower().partition(":")
		parts = keys.split("+")
		mods = sorted(parts[:-1], key=lambda x: order.index(x) if x in order else 9)
		return pre + ":" + "+".join(mods + parts[-1:])

	def _classGestures(self, cls) -> dict[str, str]:
		return {self._norm(g): s for g, s in cls.iterClassGestures()}

	def test_productivity_keys_do_not_cover_putty(self) -> None:
		from tiresias.appmodules import putty
		from tiresias.gui import config_dialogs, gesture_tools
		from tiresias.productivity.plugin import ProductivityGlobalPlugin

		prod = self._classGestures(ProductivityGlobalPlugin)
		self.assertEqual(prod.get(self.NEW[0]), "showNotificationHistory")
		self.assertEqual(prod.get(self.NEW[1]), "toggleRegionWatch")
		for g in self.OLD:
			self.assertNotIn(g, prod)
		puttyG = self._classGestures(putty.AppModule)
		self.assertEqual(puttyG.get(self.OLD[1]), "viewTerminal")
		self.assertEqual(puttyG.get(self.OLD[0]), "readNew")
		# Con la herramienta de conflictos de Gestos de entrada.
		from tiresias.browse.document import BrowseModeDocument
		from tiresias.global_commands import GlobalCommands
		from tiresias.objects.behaviors import EditableText

		scripts = []
		for cls in (GlobalCommands, BrowseModeDocument, EditableText, ProductivityGlobalPlugin, putty.AppModule):
			scripts.extend(config_dialogs._scriptsForClass(cls, "x"))
		for gid in self.NEW:
			own = next(i for i in scripts if i.cls is ProductivityGlobalPlugin and gid in [self._norm(g) for g in i.classGestures if i.classGestures[g] == i.name])
			report = gesture_tools.checkGesture(scripts, {}, next(g for g in own.classGestures if self._norm(g) == gid), exclude=own)
			self.assertEqual(report["conflicts"], [], gid)
			self.assertIsNone(report["reserved"])

	def test_new_keys_unused_elsewhere_in_code(self) -> None:
		pat = re.compile(r'"(kb(?:\([a-z]+\))?:[A-Za-z0-9+.,;/\'\[\]-]+)"')
		found: dict[str, set[str]] = {}
		for base in ("src/tiresias", "data/addons"):
			for dp, _dn, fn in os.walk(os.path.join(ROOT, base)):
				for f in fn:
					if not f.endswith(".py"):
						continue
					path = os.path.join(dp, f)
					with open(path, encoding="utf-8", errors="replace") as fh:
						text = fh.read()
					for m in pat.finditer(text):
						found.setdefault(self._norm(m.group(1)), set()).add(os.path.relpath(path, ROOT).replace("\\", "/"))
		for gid in self.NEW:
			self.assertEqual(found.get(gid), {"src/tiresias/productivity/plugin.py"}, gid)
		for gid in self.OLD:
			self.assertEqual(found.get(gid), {"src/tiresias/appmodules/putty.py"}, gid)

	def test_manual_mentions_new_keys(self) -> None:
		with open(os.path.join(ROOT, "manual", "manual_usuario.html"), encoding="utf-8") as f:
			html = f.read()
		self.assertIn("<kbd>Tiresias+Control+Mayúsculas+Alt+N</kbd> abre el historial", html)
		self.assertIn('Vigilar zona con OCR</th><td><kbd>Tiresias+Control+Mayúsculas+Alt+V</kbd>', html)
		self.assertIn('Historial de notificaciones</th><td><kbd>Tiresias+Control+Mayúsculas+Alt+N</kbd>', html)


# ====================================================================== 5 y 6. objetos que no son UIA
class _MsaaAcc:
	def __init__(self, alive: bool = True) -> None:
		self.alive = alive

	def accRole(self, child):
		if not self.alive:
			raise OSError("objeto destruido")
		return 10


class _MsaaObj:
	def __init__(self, hwnd: int, alive: bool = True) -> None:
		self.windowHandle = hwnd
		self.IAccessibleObject = _MsaaAcc(alive)
		self.IAccessibleChildID = 0
		self.name = "objeto"


class NonUiaObjectTests(unittest.TestCase):
	def setUp(self) -> None:
		from tiresias import winapi

		self.desktop = int(winapi.user32.GetDesktopWindow())

	def test_watch_isAlive_msaa(self) -> None:
		from tiresias.productivity.watch import isAlive

		self.assertTrue(isAlive(_MsaaObj(self.desktop)))
		# La ventana ya no existe.
		self.assertFalse(isAlive(_MsaaObj(0x7FFFFFF0)))
		# La ventana sigue, pero el objeto IAccessible ya no responde.
		self.assertFalse(isAlive(_MsaaObj(self.desktop, alive=False)))

	def test_watch_removes_dead_msaa_object(self) -> None:
		from tiresias import productivity
		from tiresias.productivity import watch

		productivity.registerDefaults()
		mgr = watch.WatchManager()
		obj = _MsaaObj(self.desktop)
		with mock.patch.object(queue_handler, "callLater", return_value=None):
			w = mgr.add(watch.KIND_OBJECT, obj, "app", "objeto", None, "objeto")
		self.addCleanup(mgr.clear)
		announced: list[str] = []
		mgr._announce = lambda w, message, force=False: announced.append(message)
		obj.IAccessibleObject.alive = False
		for _i in range(3):
			mgr._pollObject(w)
		self.assertNotIn(w, mgr.watches)
		self.assertEqual(len(announced), 1)

	def test_window_find_with_msaa_foreground(self) -> None:
		from tiresias.a11y import uia_client
		from tiresias.productivity import window_find

		sentinel = object()
		fg = _MsaaObj(self.desktop)
		with mock.patch.object(uia_client, "elementFromHandle", side_effect=lambda h: sentinel if h == self.desktop else None) as m:
			self.assertIs(window_find.rootElementOf(fg), sentinel)
			m.assert_called_with(self.desktop)
		uiaLike = type("U", (), {"element": "elemento"})()
		self.assertEqual(window_find.rootElementOf(uiaLike), "elemento")
		self.assertIsNone(window_find.rootElementOf(None))
		# La ventana MSAA pasada a la búsqueda se considera viva.
		self.assertTrue(window_find._isAlive(fg))

	def test_window_find_uses_msaa_window(self) -> None:
		from tiresias import api, productivity, speech
		from tiresias.productivity import window_find

		productivity.registerDefaults()
		roots: list = []
		fg = _MsaaObj(self.desktop)
		with mock.patch.object(window_find, "rootElementOf", side_effect=lambda o: roots.append(o) or "raiz"), mock.patch.object(
			window_find, "collect", return_value=[]
		), mock.patch.object(api, "getNavigatorObject", return_value=None), mock.patch.object(speech, "speakMessage") as say:
			window_find.WindowFinder().find("hola", 1, fg)
		self.assertEqual(roots, [fg])
		self.assertIn("No se encontró", say.call_args[0][0])


# ====================================================================== 7. vigilancia de zonas
class RegionWatchPrimingTests(unittest.TestCase):
	def test_first_ocr_is_not_announced(self) -> None:
		from tiresias import productivity
		from tiresias.config import conf
		from tiresias.productivity import watch

		productivity.registerDefaults()
		old = conf["watch"]["onlyNewText"]
		self.addCleanup(conf["watch"].__setitem__, "onlyNewText", old)
		conf["watch"]["onlyNewText"] = True
		mgr = watch.WatchManager()
		with mock.patch.object(queue_handler, "callLater", return_value=None):
			w = mgr.add(watch.KIND_REGION, None, "juego", "marcador", (0, 0, 10, 10))
			o = mgr.add(watch.KIND_OBJECT, None, "app", "objeto", None, "inicial")
		self.addCleanup(mgr.clear)
		announced: list[str] = []
		mgr._announce = lambda w, message, force=False: announced.append(message)
		self.assertFalse(w.primed)
		mgr._compare(w, "Vida 100\nPuntos 20")
		self.assertEqual(announced, [])
		self.assertTrue(w.primed)
		mgr._compare(w, "Vida 100\nPuntos 30")
		self.assertEqual(announced, ["Puntos 30"])
		# Un objeto ya se leyó al crear la vigilancia: el primer cambio se anuncia.
		self.assertTrue(o.primed)
		mgr._compare(o, "inicial cambiado")
		self.assertEqual(announced[-1], "cambiado")


# ====================================================================== 8. prioridad de la voz
class SpeechPriorityTests(unittest.TestCase):
	def _follower(self) -> tuple[FollowerSession, _FakeTransport]:
		t = _FakeTransport()
		s = FollowerSession(t, LocalMachine())
		s.clients[1] = {"id": 1, "connection_type": ConnectionMode.LEADER.value}
		return s, t

	def test_remote_client_sends_real_priority(self) -> None:
		from tiresias.speech import api as speechApi

		folder = tempfile.mkdtemp(prefix="tiresias_prio_")
		self.addCleanup(shutil.rmtree, folder, True)
		c = _client(folder)
		s, t = self._follower()
		c.session = s
		c._onSpeechQueued(speechSequence=["urgente"], priority=speechApi.Priority.NOW)
		c._onSpeechQueued(speechSequence=["normal"], priority=speechApi.Priority.NORMAL)
		speaks = [p for typ, p in t.sent if typ == "speak"]
		self.assertEqual([(p["sequence"], p["priority"]) for p in speaks], [(["urgente"], 2), (["normal"], 0)])

	def test_hooks_use_pre_speechQueued(self) -> None:
		from tiresias.speech import api as speechApi

		folder = tempfile.mkdtemp(prefix="tiresias_prio_")
		self.addCleanup(shutil.rmtree, folder, True)
		c = _client(folder)
		s, t = self._follower()
		c._registerHooks(s)
		try:
			self.assertIn(c._onSpeechQueued, list(speechApi.pre_speechQueued.handlers()))
			self.assertNotIn(c._onPreSpeech, list(speechApi.pre_speech.handlers()))
		finally:
			c._unregisterHooks()
		self.assertNotIn(c._onSpeechQueued, list(speechApi.pre_speechQueued.handlers()))

	def test_rdp_server_sends_real_priority(self) -> None:
		server = rdp.RdpServerSide(openChannel=lambda: None, isRemote=lambda: False, tiresiasHooks=False)
		s, t = self._follower()
		server.session = s
		server._onSpeechQueued(speechSequence=["ya"], priority=1)
		self.assertEqual([p["priority"] for typ, p in t.sent if typ == "speak"], [1])


# ====================================================================== 9. braille remoto por dueño
class BrailleOwnerTests(unittest.TestCase):
	def test_sizes_and_cells_are_combined_by_owner(self) -> None:
		from tiresias import api
		from tiresias.braille import BrailleHandler

		h = BrailleHandler()
		with mock.patch.object(api, "getFocusObject", return_value=None):
			h.setRemoteNumCells(40, owner="remote")
			h.setRemoteNumCells(20, owner="rdp")
			self.assertEqual(h.remoteNumCells, 20)
			# Termina el Escritorio remoto: queda la línea del acceso remoto.
			h.setRemoteNumCells(0, owner="rdp")
			self.assertEqual(h.remoteNumCells, 40)
			h.setRemoteNumCells(0, owner="remote")
			self.assertEqual(h.remoteNumCells, 0)
		a, b = object(), object()
		h.showRemoteCells([1, 2], owner=a)
		h.showRemoteCells([3], owner=b)
		self.assertEqual(h._remoteCells, [3])
		# Uno deja de mostrar: no se borra lo del otro.
		h.showRemoteCells(None, owner=b)
		self.assertEqual(h._remoteCells, [1, 2])
		h.showRemoteCells(None, owner=a)
		self.assertIsNone(h._remoteCells)

	def test_rdp_and_remote_use_distinct_owners(self) -> None:
		from tiresias import braille

		calls: list = []
		server = rdp.RdpServerSide(openChannel=lambda: None, isRemote=lambda: False, tiresiasHooks=True)
		with mock.patch.object(braille.handler, "setRemoteNumCells", side_effect=lambda n, owner=None: calls.append((n, owner))):
			server._onBrailleSize(32)
			server._detach()
			folder = tempfile.mkdtemp(prefix="tiresias_br_")
			self.addCleanup(shutil.rmtree, folder, True)
			_client(folder).machine.setBrailleDisplaySize(40)
		self.assertEqual(calls, [(32, rdp.BRAILLE_OWNER), (0, rdp.BRAILLE_OWNER), (40, "remote")])
		self.assertNotEqual(rdp.BRAILLE_OWNER, "remote")


# ====================================================================== 10. cambio entre ventanas RDP
class _Recorder(LocalMachine):
	log: list = []

	def __init__(self, owner=None) -> None:
		self.calls: list = []

	def setReceivingBraille(self, state: bool) -> None:
		self.calls.append(("receiving", state))
		_Recorder.log.append((id(self), state))


class _DummyStream:
	def close(self) -> None:
		pass


class RdpForegroundOrderTests(unittest.TestCase):
	def test_deactivates_before_activating(self) -> None:
		procs = {100: ("mstsc.exe", 4), 200: ("mstsc.exe", 4)}
		client = rdp.RdpClientSide(pipeName="\\\\.\\pipe\\TiresiasRdpNoUsada", dispatch=lambda f, *a: f(*a), tiresiasHooks=False, machineFactory=_Recorder, processInfo=lambda pid: procs.get(pid, ("", 0)))
		# El enlace que se activa va primero en la lista: antes se activaba y
		# después el otro se desactivaba, volviendo a lo local.
		b = rdp._Link(client, _DummyStream(), 200)
		a = rdp._Link(client, _DummyStream(), 100)
		client.links.extend([b, a])
		client._setForegroundPid(100)
		_Recorder.log.clear()
		client._setForegroundPid(200)
		self.assertEqual(_Recorder.log, [(id(a.machine), False), (id(b.machine), True)])
		self.assertTrue(b.active)
		self.assertFalse(a.active)


# ====================================================================== 11. preajuste sin clave
class AutoconnectKeyTests(unittest.TestCase):
	def test_undecryptable_key_does_not_connect(self) -> None:
		import json

		from tiresias.remote import client as clientModule

		folder = tempfile.mkdtemp(prefix="tiresias_auto_")
		self.addCleanup(shutil.rmtree, folder, True)
		path = os.path.join(folder, "r.json")
		with open(path, "w", encoding="utf-8") as f:
			json.dump({"presets": [{"name": "Oficina", "mode": "master", "kind": "relay", "host": "127.0.0.1", "port": 6837, "key": "dpapi:QUJDRA=="}], "autoconnect": "Oficina"}, f)
		store = RemoteStore(path)
		self.assertTrue(store.keyUnavailable("Oficina"))
		c = clientModule.RemoteClient(store, CertificateManager(folder))
		said: list[str] = []
		with mock.patch.object(clientModule, "_say", side_effect=lambda t, interrupt=False: said.append(t)), mock.patch.object(c, "connect") as connect:
			c.performAutoconnect()
		connect.assert_not_called()
		self.assertIsNone(c.session)
		self.assertTrue(any("Oficina" in t and "no tiene clave" in t for t in said), said)

	def test_empty_key_preset_does_not_connect(self) -> None:
		from tiresias.remote import client as clientModule

		folder = tempfile.mkdtemp(prefix="tiresias_auto_")
		self.addCleanup(shutil.rmtree, folder, True)
		c = _client(folder)
		said: list[str] = []
		with mock.patch.object(clientModule, "_say", side_effect=lambda t, interrupt=False: said.append(t)), mock.patch.object(c, "connect") as connect:
			self.assertFalse(c.connectPreset(Preset(name="Casa", mode="slave", kind=KIND_HOST, port=6837, key="")))
			connect.assert_not_called()
			c.connectPreset(Preset(name="Casa", mode="slave", kind=KIND_HOST, port=6837, key="clave"))
			connect.assert_called_once()
		self.assertIn("Casa", said[0])


# ====================================================================== 12. ruta de los sonidos de NVDA
class NvdaWavePathTests(unittest.TestCase):
	def test_prefers_folder_with_nvda(self) -> None:
		from tiresias.remote import cues, local_machine

		name = next(iter(cues.TIRESIAS_TO_NVDA))
		folder = tempfile.mkdtemp(prefix="tiresias_nvdawaves_")
		self.addCleanup(shutil.rmtree, folder, True)
		pf, x86 = os.path.join(folder, "pf"), os.path.join(folder, "x86")
		os.makedirs(os.path.join(x86, "NVDA", "waves"))
		os.makedirs(pf)
		local_machine._nvdaWavesDir.cache_clear()
		self.addCleanup(local_machine._nvdaWavesDir.cache_clear)
		with mock.patch.dict(os.environ, {"ProgramFiles": pf, "ProgramFiles(x86)": x86}):
			path = local_machine.nvdaWavePath(name)
			self.assertTrue(path.startswith(os.path.join(x86, "NVDA", "waves")), path)
			local_machine._nvdaWavesDir.cache_clear()
			shutil.rmtree(os.path.join(x86, "NVDA"))
			path = local_machine.nvdaWavePath(name)
			self.assertTrue(path.startswith(os.path.join(pf, "NVDA", "waves")), path)
		self.assertEqual(local_machine.nvdaWavePath("sonidoQueNoExiste"), "")

	def test_manual_documents_limitation(self) -> None:
		with open(os.path.join(ROOT, "manual", "manual_usuario.html"), encoding="utf-8") as f:
			html = f.read()
		section = html[html.index('id="remoto-problemas"') : html.index('id="rdp"')]
		self.assertIn("Archivos de programa (x86)", section)


# ====================================================================== 13 y 17. arranque del servidor local
class _FakeServer:
	def __init__(self, port=0, key="", certs=None) -> None:
		self.port = 6999
		self.fingerprint = "ab"
		self.closed = threading.Event()

	def start(self) -> None:
		pass

	def close(self) -> None:
		self.closed.set()


class ServerStartTests(unittest.TestCase):
	def setUp(self) -> None:
		folder = tempfile.mkdtemp(prefix="tiresias_srv_")
		self.addCleanup(shutil.rmtree, folder, True)
		self.c = _client(folder)
		self.started: list = []
		self.c._startSession = lambda info, public, server: self.started.append((info, public, server))

	def test_ip_lookup_runs_in_server_thread(self) -> None:
		from tiresias.remote import client as clientModule

		threads: list = []
		queued: list = []
		info = ConnectionInfo(hostname="localhost", mode=ConnectionMode.FOLLOWER, key="k", port=0)

		def fakeIps():
			threads.append(threading.current_thread())
			return ["192.168.1.20"]

		with mock.patch.object(clientModule, "RelayServer", _FakeServer), mock.patch.object(clientModule, "localIPv4Addresses", side_effect=fakeIps), mock.patch.object(
			queue_handler, "queueFunction", side_effect=lambda f, *a: queued.append((f, a))
		):
			self.c._starting = True
			self.c._startAttempt = 1
			th = threading.Thread(target=self.c._startServerThread, args=(info, 0, 1))
			th.start()
			th.join(TIMEOUT)
			self.assertEqual(threads, [th])
			# En el hilo del núcleo ya no se resuelven nombres.
			func, args = queued[0]
			func(*args)
		self.assertEqual(threads, [th])
		self.assertEqual(self.started[0][1].hostname, "192.168.1.20")

	def test_stale_start_is_discarded(self) -> None:
		info1 = ConnectionInfo(hostname="localhost", mode=ConnectionMode.FOLLOWER, key="vieja", port=0)
		info2 = ConnectionInfo(hostname="localhost", mode=ConnectionMode.LEADER, key="nueva", port=0)
		with mock.patch.object(threading.Thread, "start"):
			self.c.connect(info1, hostPort=0)
			first = self.c._startAttempt
			self.c.disconnect(silent=True)
			self.assertFalse(self.c._starting)
			self.c.connect(info2, hostPort=0)
			second = self.c._startAttempt
		self.assertNotEqual(first, second)
		old = _FakeServer()
		# El arranque cancelado termina después de empezar el nuevo: se descarta.
		self.c._serverStarted(info1, old, first, ["10.0.0.1"])
		self.assertTrue(old.closed.wait(TIMEOUT))
		self.assertEqual(self.started, [])
		self.assertTrue(self.c._starting)
		# Y un fallo del arranque viejo tampoco cambia nada.
		self.c._serverFailed(0, "error", first)
		self.assertTrue(self.c._starting)
		new = _FakeServer()
		self.c._serverStarted(info2, new, second, ["10.0.0.2"])
		self.assertEqual(len(self.started), 1)
		self.assertIs(self.started[0][2], new)
		self.assertEqual(self.started[0][1].key, "nueva")
		self.assertFalse(self.c._starting)


# ====================================================================== 14. Citrix sin complemento de Escritorio remoto
class CitrixPanelTests(unittest.TestCase):
	def test_missing_is_announced(self) -> None:
		from tiresias.gui import rdp_panel

		with mock.patch.object(rdp_panel.message_dialog, "messageBox") as box:
			rdp_panel._announceCitrix("missing")
		box.assert_called_once()
		self.assertIn("falta el complemento de Escritorio remoto", box.call_args[0][0])


# ====================================================================== 15. carrera al desmarcar Citrix
class CitrixRaceTests(unittest.TestCase):
	def test_watcher_checks_stop_and_option(self) -> None:
		calls: list = []
		with mock.patch.object(rdp, "syncCitrix", side_effect=lambda e: calls.append(e) or "pending"):
			watcher = rdp._CitrixWatcher(interval=0.01, onRegistered=lambda: None, isWanted=lambda: False)
			watcher.start()
			self.assertTrue(waitFor(lambda: not watcher.running))
			self.assertEqual(calls, [])
			wanted = [True]
			watcher = rdp._CitrixWatcher(interval=0.01, onRegistered=lambda: None, isWanted=lambda: wanted[0])
			watcher.start()
			self.assertTrue(waitFor(lambda: len(calls) >= 1))
			wanted[0] = False
			self.assertTrue(waitFor(lambda: not watcher.running))
			n = len(calls)
			time.sleep(0.05)
			self.assertEqual(len(calls), n)

	def test_apply_stops_watcher_before_unregistering(self) -> None:
		events: list = []

		class FakeWatcher:
			running = True

			def stop(self):
				events.append("parar")

		def fakeSync(enabled):
			events.append(("sync", enabled, rdp._citrixLock.locked()))
			return "unregistered"

		reg = mock.MagicMock()
		reg.isRegistered.return_value = True
		old = rdp._citrixWatcher
		rdp._citrixWatcher = FakeWatcher()
		try:
			with mock.patch.object(rdp, "syncCitrix", side_effect=fakeSync), mock.patch("tiresias.remote.rdp_registration.RdpRegistration", return_value=reg):
				rdp._applyCitrix(False)
		finally:
			rdp._citrixWatcher = old
		self.assertEqual(events, ["parar", ("sync", False, True)])

	def test_watcher_waits_for_lock(self) -> None:
		calls: list = []
		with mock.patch.object(rdp, "syncCitrix", side_effect=lambda e: calls.append(e) or "pending"):
			watcher = rdp._CitrixWatcher(interval=0.01, onRegistered=lambda: None, isWanted=lambda: True)
			with rdp._citrixLock:
				watcher.start()
				time.sleep(0.05)
				# Mientras el núcleo cambia el registro, el vigilante espera; se para.
				watcher.stop()
				self.assertEqual(calls, [])
			self.assertTrue(waitFor(lambda: not watcher.running))
		self.assertEqual(calls, [])


# ====================================================================== 16. silencio de pitidos y sonidos
class RdpMuteTonesTests(unittest.TestCase):
	def test_mute_silences_tones_but_still_forwards(self) -> None:
		from tiresias.audio import tones

		server = rdp.RdpServerSide(openChannel=lambda: None, isRemote=lambda: False, tiresiasHooks=True)
		self.addCleanup(tones.setMuted, rdp.TONES_OWNER, False)
		server._setMuted(True)
		self.assertTrue(tones.isMuted())
		self.assertEqual(tones._soundVolume(), 0.0)
		beeps: list = []
		handler = lambda **kw: beeps.append(kw)  # noqa: E731
		tones.pre_beep.register(handler)
		try:
			with mock.patch.object(tones, "_getPlayer", side_effect=AssertionError("no debe sonar")):
				tones.beep(440, 10)
				tones.playSound("wrap")
		finally:
			tones.pre_beep.unregister(handler)
		self.assertEqual(len(beeps), 1)
		server._setMuted(False)
		self.assertFalse(tones.isMuted())

	def test_manual_promises_tones(self) -> None:
		with open(os.path.join(ROOT, "manual", "manual_usuario.html"), encoding="utf-8") as f:
			html = f.read()
		section = html[html.index('id="rdp-opciones"') : html.index('id="rdp-uso"')]
		self.assertIn("ni sus pitidos, ni sus sonidos", section)


if __name__ == "__main__":
	unittest.main()
