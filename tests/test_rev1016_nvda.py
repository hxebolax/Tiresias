"""Pruebas de la revisión 1.0.16: mejoras traídas de NVDA (octubre y noviembre de 2026).

1. Acceso remoto: límites de tamaño de los mensajes (NVDA #21097): 64 KiB
   antes de unirse al canal y 10 MiB después en el servidor local; búfer sin
   coste cuadrático.
2. Alt+Tab clásico de Windows 10: el conmutador (``#32771``,
   ``TaskSwitcherWnd``) no se descarta por «colgado» (NVDA #21054).
3. Notificaciones UIA importantes (``ariaNotify`` de prioridad alta) con
   prioridad de voz NEXT (NVDA #21026).
4. OneCore: carácter de sustitución al empezar el modo carácter (NVDA #20959).
5. Copia portable: «D:» sin barra tiene su propio mensaje de error (NVDA #21045).
6. Instalar: cerrar las demás copias en ejecución desde la carpeta de
   instalación, preguntando antes (NVDA #20998, #21033).

Nada toca el sistema de verdad: los procesos, psutil, las ventanas y los
diálogos se simulan siempre (nunca se buscan ni se terminan procesos reales).

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev1016_nvda -v``
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_rev1016_nvda_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]

from tiresias import installer, speech, startup  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.remote import connection, server  # noqa: E402
from tiresias.speech.api import Priority  # noqa: E402


class _ConfValue:
	def __init__(self, section: str, key: str, value) -> None:
		self.section, self.key, self.value = section, key, value

	def __enter__(self):
		self.old = conf[self.section][self.key]
		conf[self.section][self.key] = self.value
		return self

	def __exit__(self, *exc) -> None:
		conf[self.section][self.key] = self.old


# ====================================================================== 1: acceso remoto
class _ConnMixin:
	def makeConn(self, **kw) -> connection.LineConnection:
		lines: list[bytes] = []
		conn = connection.LineConnection(None, lines.append, name="prueba", **kw)  # type: ignore[arg-type]
		self.addCleanup(conn._wakeR.close)
		self.addCleanup(conn._wakeW.close)
		conn.lines = lines  # type: ignore[attr-defined]
		return conn


class LineConnectionLimitTests(_ConnMixin, unittest.TestCase):
	def test_lineas_partidas_entre_trozos(self) -> None:
		conn = self.makeConn()
		self.assertTrue(conn._feed(b'{"a":'))
		self.assertTrue(conn._feed(b'1}\n{"b"'))
		self.assertTrue(conn._feed(b':2}\n\n  \n{"c":3}\n'))
		self.assertEqual(conn.lines, [b'{"a":1}', b'{"b":2}', b'{"c":3}'])
		self.assertEqual(bytes(conn._buffer), b"")
		self.assertIsInstance(conn._buffer, bytearray)

	def test_limite_por_defecto_del_cliente(self) -> None:
		conn = self.makeConn()
		self.assertEqual(conn.lineLimit(), connection.MAX_LINE)

	def test_linea_completa_demasiado_larga_cierra(self) -> None:
		conn = self.makeConn(maxLine=10)
		self.assertTrue(conn._feed(b"0123456789\n"))
		self.assertFalse(conn._feed(b"0123456789A\n"))
		self.assertEqual(conn.lines, [b"0123456789"])

	def test_linea_larga_en_un_solo_trozo_con_otras(self) -> None:
		# Antes solo se miraba lo pendiente: una línea enorme completa pasaba.
		conn = self.makeConn(maxLine=10)
		self.assertFalse(conn._feed(b"corta\n" + b"x" * 50 + b"\nresto"))
		self.assertEqual(conn.lines, [b"corta"])

	def test_resto_pendiente_demasiado_largo_cierra(self) -> None:
		conn = self.makeConn(maxLine=10)
		self.assertTrue(conn._feed(b"12345"))
		self.assertTrue(conn._feed(b"67890"))
		self.assertFalse(conn._feed(b"1"))

	def test_limite_como_funcion(self) -> None:
		limit = [5]
		conn = self.makeConn(maxLine=lambda: limit[0])
		self.assertFalse(conn._feed(b"123456\n"))
		conn = self.makeConn(maxLine=lambda: limit[0])
		limit[0] = 100
		self.assertTrue(conn._feed(b"123456\n"))
		self.assertEqual(conn.lines, [b"123456"])

	def test_funcion_que_falla_usa_el_limite_por_defecto(self) -> None:
		conn = self.makeConn(maxLine=lambda: 1 / 0)
		with mock.patch.object(connection.log, "exception"):
			self.assertEqual(conn.lineLimit(), connection.MAX_LINE)

	def test_no_entrega_mas_lineas_tras_pedir_cerrar(self) -> None:
		got: list[bytes] = []
		conn = connection.LineConnection(None, lambda line: (got.append(line), conn.close()), name="prueba")  # type: ignore[arg-type]
		self.addCleanup(conn._wakeR.close)
		self.addCleanup(conn._wakeW.close)
		self.assertTrue(conn._feed(b"uno\ndos\ntres\n"))
		self.assertEqual(got, [b"uno"])

	def test_sin_coste_cuadratico(self) -> None:
		# 4 MiB en trozos de 256 bytes sin salto de línea: buscar «\n» en todo el
		# búfer en cada trozo (como antes) recorrería decenas de gigas.
		conn = self.makeConn()
		chunk = b"a" * 256
		start = time.perf_counter()
		for _i in range(16384):
			self.assertTrue(conn._feed(chunk))
		self.assertTrue(conn._feed(b"\n"))
		self.assertLess(time.perf_counter() - start, 3.0)
		self.assertEqual(len(conn.lines), 1)
		self.assertEqual(len(conn.lines[0]), 256 * 16384)


class RelayClientLimitTests(unittest.TestCase):
	def makeClient(self) -> server._Client:
		srv = mock.Mock()
		client = server._Client(srv, None, ("127.0.0.1", 1))  # type: ignore[arg-type]
		self.addCleanup(client.conn._wakeR.close)
		self.addCleanup(client.conn._wakeW.close)
		return client

	def test_limites_segun_autenticacion(self) -> None:
		self.assertEqual(server.MAX_UNAUTHENTICATED_LINE, 64 * 1024)
		self.assertEqual(server.MAX_AUTHENTICATED_LINE, 10 * 1024 * 1024)
		client = self.makeClient()
		self.assertEqual(client.conn.lineLimit(), server.MAX_UNAUTHENTICATED_LINE)
		client.authenticated = True
		self.assertEqual(client.conn.lineLimit(), server.MAX_AUTHENTICATED_LINE)

	def test_sin_autenticar_rechaza_mensaje_grande(self) -> None:
		client = self.makeClient()
		big = b'{"type":"join","channel":"' + b"x" * (70 * 1024) + b'"}\n'
		self.assertFalse(client.conn._feed(big))
		client.server._join.assert_not_called()
		# Y tampoco puede acumular más de 64 KiB sin terminar la línea.
		client = self.makeClient()
		self.assertFalse(client.conn._feed(b"x" * (65 * 1024)))

	def test_autenticado_admite_mensajes_grandes(self) -> None:
		client = self.makeClient()
		client.authenticated = True
		msg = b'{"type":"set_clipboard_text","text":"' + b"x" * (1024 * 1024) + b'"}\n'
		self.assertTrue(client.conn._feed(msg))
		client.server._forward.assert_called_once()
		self.assertFalse(client.conn._feed(b"x" * (server.MAX_AUTHENTICATED_LINE + 1)))

	def test_el_limite_cambia_al_unirse_en_el_mismo_trozo(self) -> None:
		client = self.makeClient()

		def join(c, obj) -> None:
			c.authenticated = True

		client.server._join.side_effect = join
		big = b'{"type":"x","t":"' + b"y" * (100 * 1024) + b'"}\n'
		self.assertTrue(client.conn._feed(b'{"type":"join","channel":"c"}\n' + big))
		client.server._forward.assert_called_once()


# ====================================================================== 2: Alt+Tab clásico
class ClassicAltTabTests(unittest.TestCase):
	def setUp(self) -> None:
		from tiresias.a11y import msaa

		self.msaa = msaa
		self.user32 = mock.Mock()
		self.user32.IsWindow.return_value = True
		self.user32.IsHungAppWindow.return_value = True
		p = mock.patch.object(msaa, "user32", self.user32)
		p.start()
		self.addCleanup(p.stop)

	def withClass(self, name: str):
		return mock.patch.object(self.msaa, "_windowClassName", return_value=name)

	def test_conmutador_colgado_se_lee(self) -> None:
		for cls in ("#32771", "TaskSwitcherWnd"):
			with self.withClass(cls), mock.patch.object(self.msaa, "isSlowWindow", return_value=True):
				self.assertTrue(self.msaa._isUsableWindow(0x1234), cls)

	def test_otras_ventanas_colgadas_se_descartan(self) -> None:
		with self.withClass("Notepad"):
			self.assertFalse(self.msaa._isUsableWindow(0x1234))
		self.user32.IsHungAppWindow.return_value = False
		with self.withClass("Notepad"), mock.patch.object(self.msaa, "isSlowWindow", return_value=True):
			self.assertFalse(self.msaa._isUsableWindow(0x1234))
		with self.withClass("Notepad"), mock.patch.object(self.msaa, "isSlowWindow", return_value=False):
			self.assertTrue(self.msaa._isUsableWindow(0x1234))

	def test_ventana_que_no_existe(self) -> None:
		self.user32.IsWindow.return_value = False
		with self.withClass("#32771"):
			self.assertFalse(self.msaa._isUsableWindow(0x1234))
		self.assertFalse(self.msaa._isUsableWindow(0))

	def test_smto_normal_con_el_mismo_tiempo(self) -> None:
		fake = mock.Mock()
		fake.SendMessageTimeoutW.return_value = 1
		with mock.patch.object(self.msaa, "_user32p", fake):
			with self.withClass("#32771"):
				self.assertEqual(self.msaa._sendMessageTimeout(0x1234, self.msaa.WM_GETOBJECT, 0, 0, 1500), 0)
			args = fake.SendMessageTimeoutW.call_args[0]
			self.assertEqual(args[4], self.msaa.SMTO_NORMAL)
			self.assertEqual(args[5], 1500)
			with self.withClass("Notepad"):
				self.msaa._sendMessageTimeout(0x1234, self.msaa.WM_GETOBJECT, 0, 0, 1500)
			args = fake.SendMessageTimeoutW.call_args[0]
			self.assertEqual(args[4], self.msaa.SMTO_ABORTIFHUNG)
			self.assertEqual(args[5], 1500)

	def test_conmutador_nunca_es_lento(self) -> None:
		with mock.patch.dict(self.msaa._slowThreads, {77: time.monotonic() + 60}), mock.patch.object(self.msaa, "_windowThreadProcess", return_value=(77, 9)):
			with self.withClass("TaskSwitcherWnd"):
				self.assertFalse(self.msaa.isSlowWindow(0x1234))
			with self.withClass("Notepad"), mock.patch.object(self.msaa, "_sendMessageTimeout", return_value=None):
				self.assertTrue(self.msaa.isSlowWindow(0x1234))

	def test_explorer_reconoce_el_alt_tab_clasico(self) -> None:
		from tiresias.appmodules import explorer

		self.assertIn("#32771", explorer.TASK_SWITCHER_CLASSES)
		self.assertIn("TaskSwitcherWnd", explorer.TASK_SWITCHER_CLASSES)


# ====================================================================== 3: notificaciones importantes
class ImportantNotificationTests(unittest.TestCase):
	def test_prioridad_segun_el_procesamiento(self) -> None:
		from tiresias.objects.base import notificationPriority

		self.assertEqual(notificationPriority(0), Priority.NEXT)  # ImportantAll
		self.assertEqual(notificationPriority(2), Priority.NEXT)  # ImportantCurrentThenMostRecent
		for p in (1, 3, 4, None):
			self.assertEqual(notificationPriority(p), Priority.NORMAL, p)

	def test_evento_del_objeto(self) -> None:
		from tiresias.audio import tones
		from tiresias.objects.base import AccObject

		with _ConfValue("presentation", "reportNotifications", True), mock.patch.object(tones, "playSound"), mock.patch.object(speech, "speakText") as speak:
			AccObject.event_notification(mock.Mock(), displayString="Alta", activityId="", notificationKind=0, notificationProcessing=0)
			speak.assert_called_once_with("Alta", priority=Priority.NEXT)
			speak.reset_mock()
			AccObject.event_notification(mock.Mock(), displayString="Normal", notificationProcessing=4)
			speak.assert_called_once_with("Normal", priority=Priority.NORMAL)
			speak.reset_mock()
			AccObject.event_notification(mock.Mock(), displayString="Sin dato")
			speak.assert_called_once_with("Sin dato", priority=Priority.NORMAL)

	def test_manejador_uia_sin_objeto(self) -> None:
		from tiresias.a11y import uia_handler

		with _ConfValue("presentation", "reportNotifications", True), mock.patch.object(uia_handler, "_suspended", False), mock.patch.object(uia_handler, "_makeObject", return_value=None), mock.patch.object(speech, "speakText") as speak:
			uia_handler._onNotification(None, 0, 2, "Importante", "")
			speak.assert_called_once_with("Importante", priority=Priority.NEXT)
			speak.reset_mock()
			uia_handler._onNotification(None, 0, 4, "Normal", "")
			speak.assert_called_once_with("Normal", priority=Priority.NORMAL)

	def test_manejador_uia_pasa_el_procesamiento_al_objeto(self) -> None:
		from tiresias import events
		from tiresias.a11y import uia_handler

		obj = mock.Mock()
		with _ConfValue("presentation", "reportNotifications", True), _ConfValue("uia", "notificationsFromBackground", True), mock.patch.object(uia_handler, "_suspended", False), mock.patch.object(uia_handler, "_makeObject", return_value=obj), mock.patch.object(events, "executeEvent") as execute:
			uia_handler._onNotification(object(), 0, 0, "Alta", "id")
		execute.assert_called_once()
		self.assertEqual(execute.call_args.kwargs["notificationProcessing"], 0)
		self.assertEqual(execute.call_args.kwargs["displayString"], "Alta")


# ====================================================================== 4: OneCore en modo carácter
class OneCoreCharacterModeTests(unittest.TestCase):
	def driver(self):
		from tiresias.synth import onecore

		d = onecore.SynthDriver.__new__(onecore.SynthDriver)
		d._settings = {"voice": "", "pitch": 50, "rate": 50}
		d._voices = {}
		return d

	def test_sustitucion_tras_abrir_say_as(self) -> None:
		from tiresias.speech.commands import CharacterModeCommand

		ssml = self.driver()._buildSsml([CharacterModeCommand(True), "a", CharacterModeCommand(False), " fin"])
		self.assertIn('<say-as interpret-as="characters">\ufffda</say-as> fin', ssml)
		self.assertEqual(ssml.count("\ufffd"), 1)

	def test_sin_cierre_explicito(self) -> None:
		from tiresias.speech.commands import CharacterModeCommand

		ssml = self.driver()._buildSsml(["x", CharacterModeCommand(True), "b"])
		self.assertTrue(ssml.endswith('x<say-as interpret-as="characters">\ufffdb</say-as></speak>'), ssml)

	def test_el_texto_sigue_escapando_controles(self) -> None:
		ssml = self.driver()._buildSsml(["a\x1ab<c"])
		self.assertIn("a b&lt;c", ssml)
		self.assertNotIn("\ufffd", ssml)


# ====================================================================== 5: carpeta de la copia portable
class PortableDirTests(unittest.TestCase):
	def test_unidad_sin_barra(self) -> None:
		for text in ("D:", "D:carpeta", "  d:  "):
			with self.assertRaises(installer.PortablePathError) as cm:
				installer.validatePortableDir(text)
			msg = str(cm.exception)
			self.assertIn("La letra de unidad debe ir seguida de una barra", msg)
			drive = text.strip()[:2]
			self.assertIn(f"usa {drive}\\ para la raíz o {drive}\\carpeta", msg)

	def test_ruta_relativa(self) -> None:
		for text in ("carpeta", r"..\otra", "\\sin_unidad"):
			with self.assertRaises(installer.PortablePathError) as cm:
				installer.validatePortableDir(text)
			msg = str(cm.exception)
			self.assertIn("C:\\", msg)
			self.assertNotIn("La letra de unidad debe", msg)

	def test_vacia(self) -> None:
		for text in ("", "   ", None):
			with self.assertRaises(installer.PortablePathError):
				installer.validatePortableDir(text)  # type: ignore[arg-type]

	def test_rutas_validas(self) -> None:
		self.assertEqual(installer.validatePortableDir("D:\\"), "D:\\")
		self.assertEqual(installer.validatePortableDir(r"D:\Tiresias\..\Portable"), r"D:\Portable")
		self.assertEqual(installer.validatePortableDir(r"\\servidor\recurso\Tiresias"), r"\\servidor\recurso\Tiresias")
		with mock.patch.dict(os.environ, {"TIRESIAS_PRUEBA_PORTABLE": r"E:\Datos"}):
			self.assertEqual(installer.validatePortableDir(r"%TIRESIAS_PRUEBA_PORTABLE%\Tiresias"), r"E:\Datos\Tiresias")

	def test_es_un_valueerror(self) -> None:
		self.assertTrue(issubclass(installer.PortablePathError, ValueError))

	def test_linea_de_ordenes(self) -> None:
		args = SimpleNamespace(portable_path="D:", portable_no_config=False, portable_no_addons=False)
		with mock.patch.object(installer, "createPortableCopy") as create, mock.patch.object(startup, "_logToConsole") as console:
			self.assertEqual(startup._createPortableFromCommandLine(args), 2)
		create.assert_not_called()
		self.assertIn("La letra de unidad debe ir seguida de una barra", console.call_args[0][0])
		args.portable_path = r"D:\Tiresias\.\Portable"
		with mock.patch.object(installer, "createPortableCopy") as create, mock.patch.object(startup, "_logToConsole"):
			self.assertEqual(startup._createPortableFromCommandLine(args), 0)
		self.assertEqual(create.call_args[0][0], r"D:\Tiresias\Portable")

	def test_dialogo(self) -> None:
		from tiresias.gui import system_dialogs

		fake = mock.Mock()
		fake.path.GetValue.return_value = "D:"
		with mock.patch.object(system_dialogs, "showError") as error, mock.patch.object(system_dialogs, "_runInThread") as run, mock.patch.object(installer, "createPortableCopy") as create:
			system_dialogs.CreatePortableDialog._onCreate(fake, None)
		self.assertIn("La letra de unidad debe ir seguida de una barra", error.call_args[0][0])
		run.assert_not_called()
		create.assert_not_called()
		fake.okButton.Enable.assert_not_called()
		# Con una ruta válida se crea con la ruta ya expandida y absoluta.
		fake.path.GetValue.return_value = r"D:\Portable\."
		with mock.patch.object(system_dialogs, "showError") as error, mock.patch.object(system_dialogs, "speakMessage"), mock.patch.object(system_dialogs, "_runInThread") as run, mock.patch.object(installer, "createPortableCopy") as create:
			system_dialogs.CreatePortableDialog._onCreate(fake, None)
			error.assert_not_called()
			run.call_args[0][0]()
		self.assertEqual(create.call_args[0][0], r"D:\Portable")


# ====================================================================== 6: copias en ejecución al instalar
class FakeProc:
	def __init__(self, pid: int, exe: str, ppid: int = 1, running: bool = True) -> None:
		self.pid = pid
		self.info = {"exe": exe, "ppid": ppid}
		self.running = running
		self.kill = mock.Mock(side_effect=self._kill)

	def _kill(self) -> None:
		self.running = False

	def is_running(self) -> bool:
		return self.running


class _NoRealProcesses(unittest.TestCase):
	"""psutil siempre simulado: ninguna prueba ve ni termina procesos reales."""

	def setUp(self) -> None:
		import psutil

		self.psutil = psutil
		self.procs: list[FakeProc] = []
		for name, kw in (("process_iter", {"side_effect": lambda *a, **k: iter(self.procs)}), ("wait_procs", {"side_effect": lambda procs, timeout=None: ([p for p in procs if not p.running], [p for p in procs if p.running])})):
			p = mock.patch.object(psutil, name, **kw)
			setattr(self, name, p.start())
			self.addCleanup(p.stop)
		self.folder = os.path.join(tempfile.gettempdir(), "TiresiasPruebaNoExiste", "Tiresias")


class RunningCopiesTests(_NoRealProcesses):
	def test_busca_solo_dentro_de_la_carpeta(self) -> None:
		own = os.getpid()
		inside = FakeProc(100, os.path.join(self.folder, "Tiresias.exe"))
		helper = FakeProc(101, os.path.join(self.folder, "lib", "ayudante.exe"))
		self.procs = [
			inside,
			helper,
			FakeProc(own, os.path.join(self.folder, "Tiresias.exe")),  # el propio proceso
			FakeProc(102, os.path.join(self.folder, "Tiresias.exe"), ppid=own),  # su guardián
			FakeProc(103, os.path.join(self.folder + "2", "Tiresias.exe")),  # carpeta parecida
			FakeProc(104, r"C:\Windows\explorer.exe"),
			FakeProc(105, ""),  # sin acceso a la ruta
		]
		self.assertEqual(installer.findRunningCopies(self.folder), [inside, helper])
		self.process_iter.assert_called_once_with(["exe", "ppid"])

	def test_espera_a_que_terminen_solas(self) -> None:
		quick = FakeProc(100, os.path.join(self.folder, "Tiresias.exe"))
		self.procs = [quick]
		calls = [0]

		def isRunning() -> bool:
			calls[0] += 1
			return calls[0] < 3

		quick.is_running = isRunning  # type: ignore[method-assign]
		with mock.patch.object(installer.time, "sleep") as sleep:
			self.assertEqual(installer.waitForRunningCopies(self.folder, timeout=60), [])
		self.assertEqual(sleep.call_count, 2)

	def test_devuelve_las_que_siguen_tras_el_plazo(self) -> None:
		stays = FakeProc(100, os.path.join(self.folder, "Tiresias.exe"))
		self.procs = [stays, FakeProc(101, os.path.join(self.folder, "x.exe"), running=False)]
		with mock.patch.object(installer.time, "sleep"):
			self.assertEqual(installer.waitForRunningCopies(self.folder, timeout=0.05, poll=0.01), [stays])
		self.assertEqual(installer.RUNNING_WAIT_BEFORE_ASK, 3.0)

	def test_termina_hijos_antes_que_padres(self) -> None:
		order: list[int] = []
		parent = FakeProc(100, os.path.join(self.folder, "Tiresias.exe"))
		guardian = FakeProc(200, os.path.join(self.folder, "Tiresias.exe"), ppid=100)
		other = FakeProc(300, os.path.join(self.folder, "Tiresias.exe"))
		for p in (parent, guardian, other):
			p.kill.side_effect = lambda p=p: (order.append(p.pid), p._kill())
		self.assertEqual(installer.terminateProcesses([parent, guardian, other]), [])
		self.assertEqual(order[0], 200)
		self.assertEqual(sorted(order), [100, 200, 300])
		self.wait_procs.assert_called_once()

	def test_fallos_al_terminar_no_paran_los_demas(self) -> None:
		bad = FakeProc(100, os.path.join(self.folder, "Tiresias.exe"))
		bad.kill.side_effect = self.psutil.AccessDenied(100)
		gone = FakeProc(101, os.path.join(self.folder, "Tiresias.exe"))
		gone.kill.side_effect = self.psutil.NoSuchProcess(101)
		stuck = FakeProc(102, os.path.join(self.folder, "Tiresias.exe"))
		stuck.kill.side_effect = None  # no termina
		good = FakeProc(103, os.path.join(self.folder, "Tiresias.exe"))
		with mock.patch.object(installer.log, "warning"):
			alive = installer.terminateProcesses([bad, gone, stuck, good])
		good.kill.assert_called_once()
		self.assertEqual(alive, [stuck])
		self.assertEqual(installer.terminateProcesses([]), [])

	def test_cerrar_copias(self) -> None:
		a = FakeProc(100, os.path.join(self.folder, "Tiresias.exe"))
		self.procs = [a]
		with mock.patch.object(installer.time, "sleep"):
			self.assertEqual(installer.closeRunningCopies(self.folder, timeout=0), [])
		a.kill.assert_called_once()


class InstallClosesRunningTests(_NoRealProcesses):
	def setUp(self) -> None:
		super().setUp()
		self.tmp = tempfile.mkdtemp(prefix="rev1016_nvda_inst_")
		self.addCleanup(shutil.rmtree, self.tmp, True)
		self.app = os.path.join(self.tmp, "programa")
		for rel in ("Tiresias.exe", "lib/x.pyc", "data/symbols/es.json"):
			path = os.path.join(self.app, *rel.split("/"))
			os.makedirs(os.path.dirname(path), exist_ok=True)
			with open(path, "w", encoding="utf-8") as f:
				f.write("x")
		self.target = os.path.join(self.tmp, "instalada")
		self.targets = installer.SystemTargets(allUsers=False, writeRegistry=False, startMenuDir=os.path.join(self.tmp, "menu"), desktopDir=os.path.join(self.tmp, "escritorio"))

	def install(self, **kw) -> None:
		installer.install(installer.InstallOptions(targetDir=self.target, allUsers=False, sourceDir=self.app, desktopShortcut=False, startMenu=False, startOnLogon=None, targets=self.targets, **kw))

	def test_solo_al_actualizar_y_con_permiso(self) -> None:
		with mock.patch.object(installer, "closeRunningCopies", return_value=[]) as close:
			self.install(closeRunning=True)  # instalación nueva: no hay nada que cerrar
			close.assert_not_called()
			self.install()  # actualización sin permiso del usuario
			close.assert_not_called()
			self.install(closeRunning=True)
			close.assert_called_once_with(self.target)
		self.process_iter.assert_not_called()

	def test_fallo_al_cerrar_no_impide_instalar(self) -> None:
		self.install()
		with mock.patch.object(installer, "closeRunningCopies", side_effect=RuntimeError("x")), mock.patch.object(installer.log, "exception"):
			self.install(closeRunning=True)
		self.assertTrue(os.path.isfile(os.path.join(self.target, paths.INSTALLED_MARKER)))

	def test_cierra_antes_de_copiar(self) -> None:
		self.install()
		seen = []
		self.procs = [FakeProc(4242, os.path.join(self.target, "Tiresias.exe"))]
		real = installer.copyTree

		def copyTree(*a, **k):
			seen.append(self.procs[0].running)
			return real(*a, **k)

		with mock.patch.object(installer, "copyTree", side_effect=copyTree):
			self.install(closeRunning=True)
		self.procs[0].kill.assert_called_once()
		self.assertTrue(seen)
		self.assertFalse(any(seen))

	def test_linea_de_ordenes(self) -> None:
		from tiresias import core

		base = dict(install_dir=self.target, launch=False, no_desktop_shortcut=False, no_start_menu=False, start_on_logon=False, all_users="1", no_elevate=False)
		opts, _logon = installer.silentInstallPlan(SimpleNamespace(**base))
		self.assertFalse(opts.closeRunning)
		self.assertNotIn("--close-running", installer.elevatedInstallArgs(opts))
		opts, _logon = installer.silentInstallPlan(SimpleNamespace(close_running=True, **base))
		self.assertTrue(opts.closeRunning)
		self.assertIn("--close-running", installer.elevatedInstallArgs(opts))
		self.assertTrue(core.parseArgs(["--install-silent", "--close-running"]).close_running)
		self.assertFalse(core.parseArgs(["--install-silent"]).close_running)


class InstallDialogRunningTests(_NoRealProcesses):
	def setUp(self) -> None:
		super().setUp()
		from tiresias.gui import installer_dialogs, system_dialogs

		self.dialogs = installer_dialogs
		self.tmp = tempfile.mkdtemp(prefix="rev1016_nvda_dlg_")
		self.addCleanup(shutil.rmtree, self.tmp, True)
		self.target = os.path.join(self.tmp, "Tiresias")
		os.makedirs(self.target)
		self.fake = mock.Mock()
		self.fake.installer = installer
		self.fake.folder.GetValue.return_value = self.target
		for target, name, kw in (
			(paths, "FROZEN", {"new": True}),
			(installer_dialogs, "isAlive", {"return_value": True}),
			(installer_dialogs, "speakMessage", {}),
			(system_dialogs, "_runInThread", {"side_effect": self._sync}),
		):
			p = mock.patch.object(target, name, **kw)
			p.start()
			self.addCleanup(p.stop)

	@staticmethod
	def _sync(func, done) -> None:
		try:
			result, error = func(), None
		except Exception as e:
			result, error = None, e
		done(result, error)

	def run_dialog(self, running: list, answer: bool):
		with mock.patch.object(installer, "waitForRunningCopies", return_value=running) as wait, mock.patch.object(self.dialogs, "confirmCloseRunningCopies", return_value=answer) as confirm, mock.patch.object(self.dialogs, "showError") as error:
			self.dialogs.InstallDialog._onInstall(self.fake, None)
		return wait, confirm, error

	def markInstalled(self) -> None:
		with open(os.path.join(self.target, paths.INSTALLED_MARKER), "w", encoding="utf-8") as f:
			f.write("{}")
		with open(os.path.join(self.target, installer.EXE_NAME), "w", encoding="utf-8") as f:
			f.write("x")

	def test_instalacion_nueva_no_busca(self) -> None:
		wait, confirm, error = self.run_dialog([], True)
		wait.assert_not_called()
		confirm.assert_not_called()
		self.fake._install.assert_called_once_with(self.target, closeRunning=False)

	def test_actualizacion_sin_copias_no_pregunta(self) -> None:
		self.markInstalled()
		wait, confirm, error = self.run_dialog([], True)
		wait.assert_called_once_with(self.target)
		confirm.assert_not_called()
		self.fake._install.assert_called_once_with(self.target, closeRunning=False, announce=False)

	def test_actualizacion_con_copias_y_permiso(self) -> None:
		self.markInstalled()
		running = [FakeProc(1, os.path.join(self.target, "Tiresias.exe")), FakeProc(2, os.path.join(self.target, "Tiresias.exe"))]
		wait, confirm, error = self.run_dialog(running, True)
		self.assertEqual(confirm.call_args[0][0], 2)
		self.fake._install.assert_called_once_with(self.target, closeRunning=True, announce=True)
		error.assert_not_called()
		for p in running:
			p.kill.assert_not_called()  # las termina la instalación, no la pregunta

	def test_actualizacion_con_copias_sin_permiso(self) -> None:
		self.markInstalled()
		wait, confirm, error = self.run_dialog([FakeProc(1, os.path.join(self.target, "Tiresias.exe"))], False)
		self.fake._install.assert_not_called()
		error.assert_called_once()
		self.assertIn("otras copias en ejecución", error.call_args[0][0])
		self.fake._setBusy.assert_called_with(False)

	def test_fallo_al_buscar_instala_sin_cerrar(self) -> None:
		self.markInstalled()
		with mock.patch.object(installer, "waitForRunningCopies", side_effect=OSError("x")), mock.patch.object(self.dialogs, "confirmCloseRunningCopies") as confirm, mock.patch.object(self.dialogs.log, "warning"):
			self.dialogs.InstallDialog._onInstall(self.fake, None)
		confirm.assert_not_called()
		self.fake._install.assert_called_once_with(self.target, closeRunning=False, announce=False)

	def test_install_pasa_la_opcion_a_la_copia_elevada(self) -> None:
		self.fake.allUsers.GetValue.return_value = True
		self.fake.logon.GetValue.return_value = False
		self.fake.copyConfig.GetValue.return_value = False
		self.fake.launch.GetValue.return_value = False
		with mock.patch.object(installer, "isElevated", return_value=False), mock.patch.object(installer, "_launch", return_value=("exe", [])), mock.patch.object(installer, "shellExecuteElevated", return_value=0) as elevated, mock.patch.object(installer, "removeRunAtLogonIfFrom"), mock.patch.object(self.dialogs.message_dialog, "messageBox"):
			self.dialogs.InstallDialog._install(self.fake, self.target, closeRunning=True)
		self.assertIn("--close-running", elevated.call_args[0][1])

	def test_pregunta_con_no_por_defecto(self) -> None:
		from tiresias.gui import settings

		with mock.patch.object(settings, "askYesNo", return_value=True) as ask:
			self.assertTrue(self.dialogs.confirmCloseRunningCopies(2))
		message = ask.call_args[0][0]
		self.assertIn("pantallas seguras", message)
		self.assertIn("no se volverán a abrir solas", message)


if __name__ == "__main__":
	unittest.main()
