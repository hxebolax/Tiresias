"""Revisión 1.0.12: Tiresias instalada en las pantallas seguras de Windows.

Inicio de sesión, Control de cuentas de usuario y Control+Alt+Supr, como NVDA
instalado (``tiresias.secure_screens``): registro en HKLM, opción en
Generales, aviso a ATBroker, copia del escritorio seguro (modo seguro, mutex
propio, sin guardián ni API de control, cierre al volver al escritorio del
usuario) y convivencia.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev1012_pantallas_seguras -v``

No escriben en el registro de Windows, no pulsan teclas, no piden permiso de
administrador ni inician Tiresias: todo lo que toca el sistema se simula.
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
import unittest
import winreg
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_pantallas_seguras_")
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]

from tiresias import secure_env, secure_screens  # noqa: E402
from tiresias.config import conf, policy as policyModule  # noqa: E402

INSTALLED_EXE = r"C:\Program Files\Tiresias\Tiresias.exe"
PORTABLE_EXE = r"C:\Users\prueba\AppData\Local\Programs\Tiresias\Tiresias.exe"
HKLM = winreg.HKEY_LOCAL_MACHINE
HKCU = winreg.HKEY_CURRENT_USER


class FakeRegistry:
	"""Registro en memoria con la interfaz de ``secure_screens.WinRegistry``."""

	def __init__(self) -> None:
		self.keys: dict = {}
		self.writes: list = []

	def _k(self, root, key):
		return (root, key.lower())

	def getValue(self, root, key, name):
		v = self.keys.get(self._k(root, key), {}).get(name)
		return None if v is None else v[1]

	def keyExists(self, root, key) -> bool:
		return self._k(root, key) in self.keys

	def setValues(self, root, key, values) -> None:
		self.writes.append((root, key, dict(values)))
		self.keys.setdefault(self._k(root, key), {}).update(values)

	def deleteKey(self, root, key) -> None:
		self.writes.append((root, key, None))
		self.keys.pop(self._k(root, key), None)


@contextlib.contextmanager
def confValue(section: str, key: str, value):
	"""Cambia una opción mientras dura el bloque (``mock.patch.dict`` no vale con ``conf``)."""
	old = conf[section][key]
	conf[section][key] = value
	try:
		yield
	finally:
		conf[section][key] = old


class SecureMode:
	def __enter__(self):
		self._old = policyModule.policy.secureMode
		policyModule.policy.secureMode = True
		return self

	def __exit__(self, *exc):
		policyModule.policy.secureMode = self._old


class _Base(unittest.TestCase):
	"""Registro falso, sesión del usuario (no escritorio seguro) y sin avisos previos."""

	def setUp(self) -> None:
		self.reg = FakeRegistry()
		patches = [
			mock.patch.object(secure_screens, "registry", self.reg),
			mock.patch.object(secure_screens, "_secureScreen", False),
			mock.patch.object(secure_screens, "_running", None),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def installed(self, exe: str = INSTALLED_EXE):
		"""Copia compilada e instalada en ``exe``."""
		from tiresias.a11y import system

		stack = [
			mock.patch.object(paths, "FROZEN", True),
			mock.patch.object(paths, "isInstalledCopy", return_value=True),
			mock.patch.object(system, "_launchInfo", return_value=(exe, "")),
		]
		for p in stack:
			p.start()
			self.addCleanup(p.stop)


# ====================================================================== registro de Windows
class RegistryTests(_Base):
	def test_activar_registra_en_hklm_y_en_el_inicio_de_sesion(self) -> None:
		self.installed()
		self.reg.setValues(HKLM, secure_screens.ACCESSIBILITY_KEY, {"Configuration": (winreg.REG_SZ, "narrator")})
		secure_screens.applyMachine(True)
		vals = self.reg.keys[(HKLM, secure_screens.AT_KEY.lower())]
		self.assertEqual(vals["StartExe"][1], INSTALLED_EXE)
		self.assertEqual(vals["ATExe"][1], "Tiresias.exe")
		self.assertIn("--secure", vals["StartParams"][1])
		self.assertIn("--ease-of-access", vals["StartParams"][1])
		self.assertEqual(vals["TerminateOnDesktopSwitch"], (winreg.REG_DWORD, 0))
		self.assertEqual(vals["SimpleProfile"][1], "screenreader")
		self.assertEqual(secure_screens.readConfiguration(), ["narrator", "tiresias"])
		self.assertTrue(secure_screens.isEnabled())
		# Activar otra vez no duplica el nombre.
		secure_screens.applyMachine(True)
		self.assertEqual(secure_screens.readConfiguration(), ["narrator", "tiresias"])

	def test_desactivar_deja_a_los_demas(self) -> None:
		self.installed()
		self.reg.setValues(HKLM, secure_screens.ACCESSIBILITY_KEY, {"Configuration": (winreg.REG_SZ, "nvda_nvda_v1,tiresias")})
		secure_screens.applyMachine(True)
		secure_screens.applyMachine(False)
		self.assertEqual(secure_screens.readConfiguration(), ["nvda_nvda_v1"])
		self.assertFalse(self.reg.keyExists(HKLM, secure_screens.AT_KEY))
		self.assertFalse(secure_screens.isEnabled())

	def test_no_borra_el_registro_de_otra_copia(self) -> None:
		self.installed(r"C:\Program Files\Otra\Tiresias.exe")
		secure_screens.applyMachine(True)
		self.installed()
		secure_screens.applyMachine(False)
		self.assertTrue(self.reg.keyExists(HKLM, secure_screens.AT_KEY))
		self.assertFalse(secure_screens.unregisterIfFrom(INSTALLED_EXE))

	def test_desinstalar_quita_el_de_esta_copia(self) -> None:
		self.installed()
		secure_screens.applyMachine(True)
		self.assertTrue(secure_screens.unregisterIfFrom(INSTALLED_EXE))
		self.assertFalse(secure_screens.isStartOnLogonScreen())
		self.assertFalse(self.reg.keyExists(HKLM, secure_screens.AT_KEY))

	def test_configuracion_vacia_o_con_espacios(self) -> None:
		self.assertEqual(secure_screens.readConfiguration(), [])
		self.reg.setValues(HKLM, secure_screens.ACCESSIBILITY_KEY, {"Configuration": (winreg.REG_SZ, "")})
		self.assertEqual(secure_screens.readConfiguration(), [])
		self.reg.setValues(HKLM, secure_screens.ACCESSIBILITY_KEY, {"Configuration": (winreg.REG_SZ, "osk, Tiresias")})
		self.assertTrue(secure_screens.isStartOnLogonScreen())

	def test_solo_registrado_sin_inicio_de_sesion_no_cuenta(self) -> None:
		self.installed()
		from tiresias.a11y import system

		self.reg.setValues(HKLM, secure_screens.AT_KEY, system._atValues(machine=True))
		self.assertTrue(secure_screens.isRegisteredForThisCopy())
		self.assertFalse(secure_screens.isEnabled())


# ====================================================================== disponibilidad
class AvailabilityTests(_Base):
	def test_codigo_fuente_o_portable(self) -> None:
		ok, reason = secure_screens.availability()
		self.assertFalse(ok)
		self.assertIn("Solo en la copia instalada", reason)
		with mock.patch.object(paths, "FROZEN", True), mock.patch.object(paths, "isInstalledCopy", return_value=False):
			self.assertFalse(secure_screens.isAvailable())

	def test_instalada_solo_para_el_usuario(self) -> None:
		self.installed(PORTABLE_EXE)
		ok, reason = secure_screens.availability()
		self.assertFalse(ok)
		self.assertIn("Archivos de programa", reason)

	def test_instalada_en_archivos_de_programa(self) -> None:
		self.installed()
		self.assertEqual(secure_screens.availability(), (True, ""))

	def test_modo_seguro_y_escritorio_seguro(self) -> None:
		self.installed()
		with SecureMode():
			self.assertFalse(secure_screens.isAvailable())
		with mock.patch.object(secure_screens, "_secureScreen", True):
			ok, reason = secure_screens.availability()
			self.assertFalse(ok)
			self.assertIn("modo seguro", reason)


# ====================================================================== activar y desactivar
class SetEnabledTests(_Base):
	def setUp(self) -> None:
		super().setUp()
		self.installed()
		from tiresias import installer

		self.installer = installer

	def test_sin_permisos_pide_una_copia_elevada(self) -> None:
		inst = self.installer
		with (
			mock.patch.object(secure_env, "isElevated", return_value=False),
			mock.patch.object(inst, "_launch", return_value=(INSTALLED_EXE, [])),
			mock.patch.object(inst, "shellExecuteElevated", return_value=0) as elev,
			mock.patch.object(secure_screens, "isEnabled", return_value=True),
			mock.patch.object(secure_screens, "syncRunning") as sync,
		):
			secure_screens.setEnabled(True, r"C:\Usuario\config")
		exe, params = elev.call_args[0]
		self.assertEqual(exe, INSTALLED_EXE)
		self.assertEqual(params, inst.quoteArgs(["--secure-screens", "1", "--copy-config-to-system", r"C:\Usuario\config"]))
		self.assertTrue(elev.call_args.kwargs.get("wait"))
		sync.assert_called_once()

	def test_errores_de_la_copia_elevada(self) -> None:
		inst = self.installer
		base = [
			mock.patch.object(secure_env, "isElevated", return_value=False),
			mock.patch.object(inst, "_launch", return_value=(INSTALLED_EXE, [])),
		]
		for p in base:
			p.start()
			self.addCleanup(p.stop)
		with mock.patch.object(inst, "shellExecuteElevated", return_value=3):
			with self.assertRaises(OSError) as cm:
				secure_screens.setEnabled(True, "x")
			self.assertIn("configuración", str(cm.exception))
		with mock.patch.object(inst, "shellExecuteElevated", return_value=1):
			self.assertRaises(OSError, secure_screens.setEnabled, True, "x")
		# Terminó bien pero el registro no ha cambiado (p. ej. otra copia).
		with mock.patch.object(inst, "shellExecuteElevated", return_value=0), mock.patch.object(secure_screens, "isEnabled", return_value=False):
			self.assertRaises(OSError, secure_screens.setEnabled, True, "x")
		# Permiso denegado en el Control de cuentas de usuario.
		with mock.patch.object(inst, "shellExecuteElevated", side_effect=OSError(1223, "cancelado")):
			self.assertRaises(OSError, secure_screens.setEnabled, True, "x")

	def test_como_administrador_lo_hace_directamente(self) -> None:
		inst = self.installer
		with (
			mock.patch.object(secure_env, "isElevated", return_value=True),
			mock.patch.object(inst, "copyConfigToSystem") as copy,
			mock.patch.object(inst, "shellExecuteElevated") as elev,
			mock.patch.object(secure_screens, "syncRunning"),
			mock.patch.object(secure_screens, "_sendWinU"),
		):
			secure_screens.setEnabled(True, r"C:\Usuario\config")
			self.assertTrue(secure_screens.isEnabled())
			copy.assert_called_once_with(r"C:\Usuario\config")
			secure_screens.setEnabled(False)
			self.assertFalse(secure_screens.isEnabled())
		elev.assert_not_called()
		self.assertEqual(copy.call_count, 1)

	def test_al_desactivar_avisa_antes_de_quitar_el_registro(self) -> None:
		order = []
		with (
			mock.patch.object(secure_env, "isElevated", return_value=True),
			mock.patch.object(secure_screens, "setRunning", side_effect=lambda r: order.append(("aviso", r))),
			mock.patch.object(secure_screens, "applyMachine", side_effect=lambda e: order.append(("registro", e))),
			mock.patch.object(secure_screens, "isEnabled", return_value=False),
		):
			secure_screens.setEnabled(False)
		self.assertEqual(order, [("aviso", False), ("registro", False)])

	def test_no_disponible(self) -> None:
		with mock.patch.object(secure_screens, "availability", return_value=(False, "solo en la copia instalada")):
			with self.assertRaises(OSError) as cm:
				secure_screens.setEnabled(True)
		self.assertIn("solo en la copia instalada", str(cm.exception))

	def test_orden_elevada(self) -> None:
		inst = self.installer
		with mock.patch.object(secure_screens, "availability", return_value=(False, "no")):
			self.assertEqual(secure_screens.runCommand(True), 2)
		with mock.patch.object(secure_env, "isElevated", return_value=False):
			self.assertEqual(secure_screens.runCommand(True), 5)
		with mock.patch.object(secure_env, "isElevated", return_value=True), mock.patch.object(inst, "copyConfigToSystem") as copy:
			self.assertEqual(secure_screens.runCommand(True, "C:\\cfg"), 0)
			copy.assert_called_once_with("C:\\cfg")
			self.assertTrue(secure_screens.isEnabled())
			# Al desactivar no se copia nada.
			self.assertEqual(secure_screens.runCommand(False, "C:\\cfg"), 0)
			self.assertEqual(copy.call_count, 1)
		with mock.patch.object(secure_env, "isElevated", return_value=True), mock.patch.object(inst, "copyConfigToSystem", side_effect=OSError("x")):
			self.assertEqual(secure_screens.runCommand(True, "C:\\cfg"), 3)
		with mock.patch.object(secure_env, "isElevated", return_value=True), mock.patch.object(secure_screens, "applyMachine", side_effect=PermissionError()):
			self.assertEqual(secure_screens.runCommand(True), 1)


# ====================================================================== aviso a ATBroker
class NotifyTests(_Base):
	def test_aviso_solo_al_cambiar(self) -> None:
		self.installed()
		secure_screens.applyMachine(True)
		with mock.patch.object(secure_screens, "_sendWinU") as winU, mock.patch.object(secure_screens, "_inStandby", return_value=False):
			secure_screens.setRunning(True)
			secure_screens.setRunning(True)
			secure_screens.syncRunning()
			self.assertEqual(winU.call_count, 1)
			self.assertEqual(self.reg.getValue(HKCU, secure_screens.TEMP_KEY, "tiresias"), secure_screens.SIGNAL_STARTED)
			secure_screens.setRunning(False)
			secure_screens.setRunning(False)
			self.assertEqual(winU.call_count, 2)
			self.assertEqual(self.reg.getValue(HKCU, secure_screens.TEMP_KEY, "tiresias"), secure_screens.SIGNAL_STOPPED)

	def test_sin_registro_no_se_pulsa_windows_u(self) -> None:
		"""Sin el registro de esta copia, Windows+U abriría la Configuración."""
		self.installed()
		with mock.patch.object(secure_screens, "_sendWinU") as winU:
			self.assertFalse(secure_screens.notify(secure_screens.SIGNAL_STARTED))
			secure_screens.setRunning(True)
			secure_screens.setRunning(False)
		winU.assert_not_called()
		self.assertEqual(self.reg.writes, [])

	def test_cuando_no_se_avisa(self) -> None:
		self.installed()
		secure_screens.applyMachine(True)
		with mock.patch.object(secure_screens, "_inStandby", return_value=True):
			self.assertFalse(secure_screens.shouldAnnounceRunning())
		with mock.patch.object(secure_screens, "_inStandby", return_value=False):
			self.assertTrue(secure_screens.shouldAnnounceRunning())
			with mock.patch.object(secure_screens, "_secureScreen", True):
				self.assertFalse(secure_screens.shouldAnnounceRunning())
			with mock.patch.object(paths, "FROZEN", False):
				self.assertFalse(secure_screens.shouldAnnounceRunning())

	def test_windows_u_suelta_las_modificadoras(self) -> None:
		from tiresias import winapi

		with (
			mock.patch.object(winapi, "isKeyDown", side_effect=lambda vk: vk == 0x11),
			mock.patch.object(winapi, "makeKeyInput", side_effect=lambda vk, up=False, extended=False: (vk, up)),
			mock.patch.object(winapi, "sendInputs") as send,
		):
			secure_screens._sendWinU()
		self.assertEqual(send.call_args[0][0], [(0x11, True), (0x5B, False), (0x55, False), (0x55, True), (0x5B, True), (0x11, False)])


# ====================================================================== copia del escritorio seguro
class DesktopWatcherTests(unittest.TestCase):
	def test_sale_al_volver_al_escritorio_del_usuario(self) -> None:
		seq = iter(["Winlogon", "Default", None, "Default", "Winlogon", "Default", "Default", "Default"])
		left = []
		w = secure_screens.DesktopWatcher("Winlogon", lambda: left.append(1), inputDesktop=lambda: next(seq), confirm=2)
		results = [w.check() for _i in range(8)]
		self.assertEqual(results, [False, False, False, False, False, False, True, False])
		self.assertEqual(left, [1])

	def test_otros_escritorios_no_cuentan(self) -> None:
		left = []
		w = secure_screens.DesktopWatcher("Winlogon", lambda: left.append(1), inputDesktop=lambda: "Screen-saver", confirm=1)
		self.assertFalse(any(w.check() for _i in range(5)))
		self.assertEqual(left, [])

	def test_en_el_escritorio_del_usuario_no_vigila(self) -> None:
		w = secure_screens.DesktopWatcher("Default", mock.Mock(), inputDesktop=lambda: "Default", confirm=1)
		self.assertFalse(w.active)
		self.assertFalse(w.check())
		with mock.patch.object(secure_screens.threading, "Thread") as th:
			self.assertIsNone(secure_screens.startDesktopWatcher("Default"))
		th.assert_not_called()

	def test_arranque_y_parada_de_la_vigilancia(self) -> None:
		with mock.patch.object(secure_screens.threading, "Thread") as th:
			try:
				w = secure_screens.startDesktopWatcher("Winlogon")
				self.assertIsNotNone(w)
				self.assertIs(secure_screens.startDesktopWatcher("Winlogon"), w)
				th.return_value.start.assert_called_once()
			finally:
				secure_screens.stopDesktopWatcher()
		self.assertIsNone(secure_screens._watcher)

	def test_salida_ordenada_con_plazo(self) -> None:
		from tiresias import core, queue_handler

		with (
			mock.patch.object(core, "requestQuit") as quit_,
			mock.patch.object(queue_handler, "queueFunction") as queue,
			mock.patch.object(secure_screens.threading, "Thread") as th,
		):
			secure_screens.leaveSecureDesktop()
		quit_.assert_called_once()
		queue.assert_called_once()
		th.return_value.start.assert_called_once()


class CoreTests(unittest.TestCase):
	def setUp(self) -> None:
		from tiresias import core

		self.core = core
		self._saved = (core.args, core._instanceDesktop, paths._configDirOverride, conf.readOnly)

	def tearDown(self) -> None:
		core = self.core
		core.args, core._instanceDesktop, paths._configDirOverride, conf.readOnly = self._saved

	def test_argumentos(self) -> None:
		ns = self.core.parseArgs(["--secure", "--ease-of-access"])
		self.assertTrue(ns.ease_of_access and ns.secure)
		self.assertIsNone(ns.secure_screens)
		self.assertEqual(self.core.parseArgs(["--secure-screens", "1"]).secure_screens, "1")
		self.assertFalse(self.core.parseArgs([]).ease_of_access)

	def test_mutex_por_escritorio(self) -> None:
		core = self.core
		core._instanceDesktop = ""
		self.assertEqual(core.instanceMutexName(), core.MUTEX_NAME)
		core._instanceDesktop = "Winlogon"
		self.assertEqual(core.instanceMutexName(), core.MUTEX_NAME + "_Winlogon")

	def test_escritorio_seguro_fuerza_el_modo_seguro(self) -> None:
		core = self.core
		with (
			mock.patch.object(secure_env, "mustForceSecureMode", return_value=True),
			mock.patch.object(secure_env, "threadDesktopName", return_value="Winlogon"),
			mock.patch.object(core, "_runStandaloneCommand", return_value=0),
		):
			self.assertEqual(core.main(["--secure", "--ease-of-access"]), 0)
		self.assertTrue(core.args.secure_desktop and core.args.secure and core.args.minimal)
		self.assertEqual(core.instanceMutexName(), core.MUTEX_NAME + "_Winlogon")
		self.assertEqual(paths.configDir(), os.path.abspath(paths.SYSTEM_CONFIG_DIR))
		self.assertTrue(conf.readOnly)

	def test_iniciada_por_windows_con_otra_copia_en_el_escritorio_del_usuario(self) -> None:
		core = self.core
		with (
			mock.patch.object(secure_env, "mustForceSecureMode", return_value=False),
			mock.patch.object(core, "_runStandaloneCommand", return_value=None),
			mock.patch.object(paths, "ensureDataDirs"),
			mock.patch.object(core, "isRunning", return_value=True),
			mock.patch.object(core, "_closeRunningInstance") as close,
		):
			self.assertEqual(core.main(["--secure", "--ease-of-access"]), 0)
		close.assert_not_called()
		self.assertEqual(core.instanceMutexName(), core.MUTEX_NAME)

	def test_en_el_escritorio_seguro_sustituye_a_la_anterior(self) -> None:
		core = self.core
		with (
			mock.patch.object(secure_env, "mustForceSecureMode", return_value=True),
			mock.patch.object(secure_env, "threadDesktopName", return_value="Winlogon"),
			mock.patch.object(core, "_runStandaloneCommand", return_value=None),
			mock.patch.object(paths, "ensureDataDirs"),
			mock.patch.object(core, "isRunning", return_value=True),
			mock.patch.object(core, "_closeRunningInstance", return_value=False) as close,
		):
			self.assertEqual(core.main(["--secure", "--ease-of-access"]), 1)
		close.assert_called_once_with(replacing=True)

	def test_sin_api_de_control_ni_clave_run_en_el_escritorio_seguro(self) -> None:
		core = self.core
		from tiresias import controller

		core.args = SimpleNamespace(secure_desktop=True, secure=True)
		with mock.patch.object(controller, "initialize") as init:
			core._initController()
		init.assert_not_called()
		with mock.patch("tiresias.gui.settings.setStartOnLogon") as setRun, confValue("general", "startOnLogon", True):
			core._refreshStartOnLogon()
		setRun.assert_not_called()


class GuardianAndCoexistTests(unittest.TestCase):
	def test_sin_guardian_en_el_escritorio_seguro(self) -> None:
		from tiresias.coexist import guardian

		env = {k: v for k, v in os.environ.items() if k not in ("TIRESIAS_NO_GUARDIAN", "TIRESIAS_GUARDIAN_TEST", "TIRESIAS_COEXIST_IGNORE_PIDS", "TIRESIAS_COEXIST_ONLY_DIR")}
		with mock.patch.dict(os.environ, env, clear=True):
			self.assertTrue(guardian.shouldStart(SimpleNamespace(exit_after=0)))
			self.assertFalse(guardian.shouldStart(SimpleNamespace(exit_after=0, secure_desktop=True)))
			with mock.patch.dict(os.environ, {"TIRESIAS_GUARDIAN_TEST": "1"}):
				self.assertFalse(guardian.shouldStart(SimpleNamespace(exit_after=0, secure_desktop=True)))

	def test_volver_al_lector_bloqueado_en_modo_seguro(self) -> None:
		from tiresias import coexist, speech

		self.assertTrue(policyModule.isAllowed("launchReaders"))
		with SecureMode():
			self.assertFalse(policyModule.isAllowed("launchReaders"))
			with mock.patch.object(coexist, "rememberedReader", return_value={"id": "nvda", "name": "NVDA"}):
				self.assertFalse(coexist.canSwitchToRememberedReader())
				with mock.patch.object(speech, "speakMessage") as speak:
					self.assertFalse(coexist.switchToRememberedReader())
				speak.assert_called_once_with(policyModule.blockedMessage())

	def test_vigilancia_en_su_propio_escritorio(self) -> None:
		from tiresias.coexist import detect

		def fake(name):
			def info(h, kind, buf, size, needed):
				buf.value = name
				return 1

			return SimpleNamespace(OpenInputDesktop=lambda *a: 1, GetUserObjectInformationW=info, CloseDesktop=lambda h: 1)

		with mock.patch.object(detect, "_ownDesktop", "default"):
			with mock.patch.object(detect, "_u32", fake("Winlogon")):
				self.assertTrue(detect.isSecureDesktopActive())
			with mock.patch.object(detect, "_u32", fake("Default")):
				self.assertFalse(detect.isSecureDesktopActive())
		with mock.patch.object(detect, "_ownDesktop", "winlogon"):
			with mock.patch.object(detect, "_u32", fake("Winlogon")):
				self.assertFalse(detect.isSecureDesktopActive())
			with mock.patch.object(detect, "_u32", fake("Default")):
				self.assertTrue(detect.isSecureDesktopActive())
		with mock.patch.object(detect, "_u32", SimpleNamespace(OpenInputDesktop=lambda *a: 0)):
			self.assertTrue(detect.isSecureDesktopActive())

	def test_otro_lector_como_system_cuenta_en_el_escritorio_seguro(self) -> None:
		"""Como SYSTEM, el NVDA del usuario es «otro usuario» y el NVDA de ese escritorio, el mismo."""
		from tiresias.coexist import detect

		procs = [detect.ProcessEntry(100, "nvda.exe", 4), detect.ProcessEntry(200, "nvda.exe", 4)]
		det = detect.Detector(
			processes=lambda: procs,
			windows=lambda cls, title: [(1, 200)],
			session=lambda pid: 1,
			ownUser=lambda pid: pid == 200,
			imagePath=lambda pid: r"C:\Program Files\NVDA\nvda.exe",
			narratorState=lambda: None,
			ownSession=1,
			excludePids=set(),
			onlyDir="",
		)
		info = det.detectOne(detect.SPECS[detect.NVDA], procs)
		self.assertEqual(info.pid, 200)


class SystemTests(unittest.TestCase):
	def test_parametros_de_hklm(self) -> None:
		from tiresias.a11y import system

		params = system._atValues(machine=True)["StartParams"][1]
		self.assertIn("--secure", params)
		self.assertIn(secure_screens.EASE_OF_ACCESS_ARG, params)
		self.assertNotIn("--ease-of-access", system._atValues()["StartParams"][1])

	def test_modo_seguro_no_toca_el_registro(self) -> None:
		from tiresias.a11y import system

		with SecureMode(), mock.patch.object(system, "_writeAT") as write, mock.patch.object(system, "_deleteAT") as delete:
			system.applyATRegistration()
		write.assert_not_called()
		delete.assert_not_called()

	def test_desregistrar_respeta_las_pantallas_seguras(self) -> None:
		from tiresias.a11y import system

		with confValue("system", "registerAsAT", False), mock.patch.object(system, "isRegisteredAsAT", return_value=True):
			with mock.patch.object(system, "_deleteAT") as delete, mock.patch.object(system, "secureScreensEnabled", return_value=True):
				system.applyATRegistration()
			delete.assert_called_once_with(winreg.HKEY_CURRENT_USER)
			with mock.patch.object(system, "_deleteAT") as delete, mock.patch.object(system, "secureScreensEnabled", return_value=False):
				system.applyATRegistration()
			self.assertEqual(delete.call_count, 2)

	def test_indicador_y_avisos(self) -> None:
		from tiresias.a11y import system

		with mock.patch.object(system, "_onSecureScreen", return_value=True), mock.patch.object(secure_screens, "syncRunning") as sync, mock.patch.object(system, "setScreenReaderFlag") as setFlag:
			system.applyScreenReaderFlag()
		setFlag.assert_not_called()
		sync.assert_called_once()
		with mock.patch.object(secure_screens, "setRunning") as running:
			system.releaseScreenReaderFlag()
		running.assert_called_once_with(False)
		from tiresias.a11y import jab

		with mock.patch.object(secure_screens, "setRunning") as running, mock.patch.object(jab, "terminate"), mock.patch.object(system, "_restoreScreenReaderFlag"):
			system.terminate()
		running.assert_called_once_with(False)


class StartupAndInstallerTests(unittest.TestCase):
	def test_orden_de_la_copia_elevada(self) -> None:
		from tiresias import core, installer, startup

		ns = core.parseArgs(["--secure-screens", "1", "--copy-config-to-system", r"C:\cfg"])
		self.assertEqual(startup.commandLogPath(ns), os.path.join(paths.logsDir(), startup.COMMAND_LOG))
		with mock.patch.object(secure_screens, "runCommand", return_value=0) as run, mock.patch.object(installer, "copyConfigToSystem") as copy:
			self.assertEqual(startup._runCommand(ns), 0)
		run.assert_called_once_with(True, r"C:\cfg")
		copy.assert_not_called()
		with mock.patch.object(secure_screens, "runCommand", return_value=0) as run:
			startup._runCommand(core.parseArgs(["--secure-screens", "0"]))
		run.assert_called_once_with(False, None)

	def test_vigilancia_al_preparar_la_configuracion(self) -> None:
		from tiresias import startup
		from tiresias.config.policy import Policy

		saved = startup.configWasMissing
		cls = type(startup.conf)
		try:
			for desk, expected in ((True, 1), (False, 0)):
				ns = SimpleNamespace(secure=True, secure_desktop=desk, data=None, safe_mode=False)
				with (
					mock.patch.object(startup.Policy, "load", return_value=Policy()),
					mock.patch.object(startup.conf, "setPolicy"),
					mock.patch.object(startup.conf, "load"),
					mock.patch.object(cls, "configFile", new_callable=mock.PropertyMock, return_value=__file__),
					mock.patch.object(secure_env, "installSecureModeGuards"),
					mock.patch.object(paths, "isInstalledCopy", return_value=False),
					mock.patch.object(secure_screens, "startDesktopWatcher") as watch,
				):
					startup.prepareConfiguration(ns)
				self.assertEqual(watch.call_count, expected)
				self.assertTrue(ns.safe_mode)
		finally:
			startup.configWasMissing = saved

	def test_desinstalar_quita_las_pantallas_seguras(self) -> None:
		from tiresias import installer
		from tiresias.remote import rdp_registration

		tmp = tempfile.mkdtemp(prefix="tiresias_desinstalar_")
		with open(os.path.join(tmp, paths.INSTALLED_MARKER), "w", encoding="utf-8") as f:
			f.write("{}")
		for allUsers, calls in ((True, 1), (False, 0)):
			targets = installer.SystemTargets(allUsers=allUsers, writeRegistry=True, startMenuDir=os.path.join(tmp, "menu"), desktopDir=os.path.join(tmp, "escritorio"))
			with (
				mock.patch.object(installer, "_regReadAll", return_value={}),
				mock.patch.object(installer, "_regDeleteKey"),
				mock.patch.object(installer, "removeRunAtLogonIfFrom"),
				mock.patch.object(rdp_registration, "unregisterIfFrom"),
				mock.patch.object(installer, "_removeFolder", return_value=True),
				mock.patch.object(secure_screens, "unregisterIfFrom") as unreg,
			):
				installer.uninstall(tmp, targets)
			self.assertEqual(unreg.call_count, calls)
			if calls:
				unreg.assert_called_once_with(os.path.join(os.path.abspath(tmp), installer.EXE_NAME))


# ====================================================================== Opciones, Generales
class SettingsTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		import wx

		cls.wx = wx
		cls.app = wx.App.Get() or wx.App(False)
		from tiresias import coexist

		coexist.registerDefaults()

	def setUp(self) -> None:
		from tiresias.gui import settings as S

		self.S = S
		self.frame = self.wx.Frame(None)
		self.addCleanup(self.frame.Destroy)
		self.reg = FakeRegistry()
		for p in (
			mock.patch.object(secure_screens, "registry", self.reg),
			mock.patch.object(secure_screens, "_secureScreen", False),
			mock.patch.object(S, "isStartOnLogonEnabled", return_value=False),
			mock.patch.object(S, "setStartOnLogon"),
		):
			p.start()
			self.addCleanup(p.stop)

	def panel(self):
		return self.S.GeneralPanel(self.frame)

	def test_esquema(self) -> None:
		from tiresias.config import schema

		self.assertIs(schema.DEFAULTS["general"]["startOnLogonScreen"], False)
		from tiresias.config import BASE_ONLY_SECTIONS

		self.assertIn("general", BASE_ONLY_SECTIONS)

	def test_portable_desactivada_con_explicacion(self) -> None:
		panel = self.panel()
		cb = panel._secureScreensCheck
		self.assertFalse(cb.IsEnabled())
		self.assertIn("(solo en la copia instalada)", cb.GetLabel())
		self.assertIn("Solo en la copia instalada", panel._secureScreensInfo.GetLabel())
		self.assertEqual(panel.fieldForControl(cb), ("general", "startOnLogonScreen"))
		with mock.patch.object(self.S, "applySecureScreens") as apply, mock.patch.object(self.S.ConfigPanel, "onSave"):
			cb.SetValue(True)
			panel.onSave()
		apply.assert_not_called()

	def test_modo_seguro(self) -> None:
		with SecureMode():
			panel = self.panel()
		self.assertFalse(panel._secureScreensCheck.IsEnabled())
		self.assertIn("(no disponible en modo seguro)", panel._secureScreensCheck.GetLabel())

	def test_instalada_activa_al_aceptar(self) -> None:
		with mock.patch.object(secure_screens, "availability", return_value=(True, "")), mock.patch.object(secure_screens, "isEnabled", return_value=False):
			panel = self.panel()
		cb = panel._secureScreensCheck
		self.assertTrue(cb.IsEnabled())
		self.assertFalse(cb.GetValue())
		calls = []
		with (
			mock.patch.object(self.S, "applySecureScreens", side_effect=lambda enable, done: calls.append(enable) or done(enable)),
			mock.patch.object(self.S.wx, "CallAfter", side_effect=lambda f, *a, **k: f(*a, **k)),
			mock.patch.object(self.S.ConfigPanel, "onSave"),
		):
			panel.onSave()
			self.assertEqual(calls, [])
			cb.SetValue(True)
			panel.onSave()
			# Aplicar otra vez sin cambios no repite la operación.
			panel.onSave()
		self.assertEqual(calls, [True])
		self.assertTrue(panel._secureScreensOriginal)

	def test_bloqueada_por_la_politica(self) -> None:
		with mock.patch.object(secure_screens, "availability", return_value=(True, "")), mock.patch.object(conf, "isLocked", side_effect=lambda s, k: (s, k) == ("general", "startOnLogonScreen")):
			panel = self.panel()
			self.assertFalse(panel._secureScreensCheck.IsEnabled())
			with mock.patch.object(self.S, "applySecureScreens") as apply, mock.patch.object(self.S.ConfigPanel, "onSave"):
				panel.onSave()
		apply.assert_not_called()

	def test_aplicar_guarda_copia_y_refleja_el_estado(self) -> None:
		S = self.S

		def sync(func, *a, callback=None, name=""):
			try:
				result, error = func(*a), None
			except Exception as e:  # noqa: BLE001
				result, error = None, e
			callback(result, error)

		states = []
		with (
			confValue("general", "startOnLogonScreen", False),
			mock.patch.object(conf, "readOnly", False),
			mock.patch.object(S, "runInThread", side_effect=sync),
			mock.patch.object(conf, "save") as save,
			mock.patch.object(S, "speakMessageOnCore") as speak,
			mock.patch.object(secure_screens, "setEnabled") as setEnabled,
		):
			S.applySecureScreens(True, states.append)
			save.assert_called_once()
			setEnabled.assert_called_once_with(True, paths.configDir())
			speak.assert_called_once()
			self.assertTrue(conf["general"]["startOnLogonScreen"])
			with mock.patch.object(S, "showError") as err, mock.patch.object(secure_screens, "isEnabled", return_value=True):
				setEnabled.side_effect = OSError("cancelado")
				S.applySecureScreens(False, states.append)
			err.assert_called_once()
			# Falló al desactivar: sigue activada.
			self.assertTrue(conf["general"]["startOnLogonScreen"])
		self.assertEqual(states, [True, True])


if __name__ == "__main__":
	unittest.main()
