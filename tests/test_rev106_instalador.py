"""Pruebas de regresión de la revisión 1.0.6 del instalador, la copia portable y la reparación COM.

Nada toca el sistema de verdad: las carpetas son temporales, las claves del
registro son de prueba (``HKCU\\Software\\TiresiasPruebasRev106``) mediante
``SystemTargets``, y la elevación, los procesos y los mensajes se simulan.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev106_instalador``
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import VERSION, installer, paths  # noqa: E402

#: Carpeta de pruebas de esta revisión (si existe; si no, la temporal del sistema).
_SCRATCH = os.path.join(tempfile.gettempdir(), "claude", "E--Antigravity-LectorPantalla", "170a2ad4-6c9b-49cd-ac1d-e58800f4b582", "scratchpad", "rev106_p3")
TEST_KEY = r"Software\TiresiasPruebasRev106"


def _write(path: str, text: str = "x") -> str:
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "w", encoding="utf-8") as f:
		f.write(text)
	return path


def _read(path: str) -> str:
	with open(path, encoding="utf-8") as f:
		return f.read()


def _args(**kw) -> SimpleNamespace:
	base = dict(install_dir=None, launch=False, no_desktop_shortcut=False, no_start_menu=False, start_on_logon=False, all_users=None, no_elevate=False)
	base.update(kw)
	return SimpleNamespace(**base)


class Base(unittest.TestCase):
	def setUp(self) -> None:
		if os.path.isdir(os.path.dirname(_SCRATCH)):
			os.makedirs(_SCRATCH, exist_ok=True)
		self.tmp = tempfile.mkdtemp(prefix="rev106_inst_", dir=_SCRATCH if os.path.isdir(_SCRATCH) else None)

	def tearDown(self) -> None:
		shutil.rmtree(self.tmp, ignore_errors=True)

	def program(self, name: str = "programa", files: dict | None = None) -> str:
		app = os.path.join(self.tmp, name)
		default = {
			"Tiresias.exe": "nuevo",
			"python314.dll": "nuevo",
			"lib/tiresias/core.pyc": "x",
			"Manual de usuario.html": "manual",
			"data/symbols/es.json": "símbolos nuevos",
			"data/sounds/inicio.wav": "sonido nuevo",
			"data/brailleTables/tabla.json": "tabla nueva",
			"data/speechDicts/default.json": "diccionario de fábrica",
			"data/config/config.json": '{"desarrollador": 1}',
		}
		default.update(files or {})
		for rel, text in default.items():
			_write(os.path.join(app, *rel.split("/")), text)
		return app

	def noRegistry(self, **kw) -> installer.SystemTargets:
		return installer.SystemTargets(allUsers=False, writeRegistry=False, startMenuDir=os.path.join(self.tmp, "menu"), desktopDir=os.path.join(self.tmp, "escritorio"), **kw)


# ====================================================================== 1, C, 6: instalar
class InstallFolderTests(Base):
	def test_rechaza_carpeta_ajena_no_vacia(self) -> None:
		app = self.program()
		target = os.path.join(self.tmp, "ajena")
		_write(os.path.join(target, "lib", "mio.txt"), "del usuario")
		_write(os.path.join(target, "docs", "carta.txt"), "del usuario")
		with self.assertRaises(ValueError):
			installer.install(installer.InstallOptions(targetDir=target, allUsers=False, sourceDir=app, desktopShortcut=False, startMenu=False, targets=self.noRegistry()))
		# No se ha borrado nada.
		self.assertEqual(_read(os.path.join(target, "lib", "mio.txt")), "del usuario")
		self.assertEqual(_read(os.path.join(target, "docs", "carta.txt")), "del usuario")

	def test_acepta_carpeta_vacia_y_copia_de_tiresias(self) -> None:
		app = self.program()
		empty = os.path.join(self.tmp, "vacia")
		os.makedirs(empty)
		opts = dict(allUsers=False, sourceDir=app, desktopShortcut=False, startMenu=False, targets=self.noRegistry())
		installer.install(installer.InstallOptions(targetDir=empty, **opts))
		self.assertTrue(os.path.isfile(os.path.join(empty, "Tiresias.exe")))
		portable = os.path.join(self.tmp, "portable")
		_write(os.path.join(portable, "Tiresias.exe"), "viejo")
		installer.install(installer.InstallOptions(targetDir=portable, **opts))
		self.assertEqual(_read(os.path.join(portable, "Tiresias.exe")), "nuevo")

	def test_borra_archivos_sueltos_de_la_version_anterior(self) -> None:
		app = self.program()
		target = os.path.join(self.tmp, "instalado")
		_write(os.path.join(target, "Tiresias.exe"), "viejo")
		_write(os.path.join(target, "python313.dll"), "viejo")
		_write(os.path.join(target, "python3.dll"), "viejo")
		_write(os.path.join(target, "policy.json"), "{}")
		self.assertEqual(sorted(installer.staleRootFiles(app, target)), ["python3.dll", "python313.dll"])
		installer.install(installer.InstallOptions(targetDir=target, allUsers=False, sourceDir=app, desktopShortcut=False, startMenu=False, targets=self.noRegistry()))
		self.assertFalse(os.path.exists(os.path.join(target, "python313.dll")))
		self.assertFalse(os.path.exists(os.path.join(target, "python3.dll")))
		self.assertTrue(os.path.isfile(os.path.join(target, "python314.dll")))
		# Lo que no es del programa (la política del administrador) se conserva.
		self.assertTrue(os.path.isfile(os.path.join(target, "policy.json")))

	def test_vacia_data_solo_en_copias_instaladas(self) -> None:
		app = self.program()
		opts = dict(allUsers=False, sourceDir=app, desktopShortcut=False, startMenu=False, targets=self.noRegistry())
		instalada = os.path.join(self.tmp, "instalada")
		_write(os.path.join(instalada, "Tiresias.exe"), "viejo")
		_write(os.path.join(instalada, paths.INSTALLED_MARKER), "{}")
		_write(os.path.join(instalada, "data", "symbols", "viejo.json"), "resto")
		installer.install(installer.InstallOptions(targetDir=instalada, **opts))
		self.assertFalse(os.path.exists(os.path.join(instalada, "data", "symbols", "viejo.json")))
		self.assertTrue(os.path.isfile(os.path.join(instalada, "data", "symbols", "es.json")))
		portable = os.path.join(self.tmp, "portable")
		_write(os.path.join(portable, "Tiresias.exe"), "viejo")
		_write(os.path.join(portable, "data", "config", "config.json"), '{"mio": 1}')
		installer.install(installer.InstallOptions(targetDir=portable, **opts))
		self.assertEqual(_read(os.path.join(portable, "data", "config", "config.json")), '{"mio": 1}')


# ====================================================================== 2: datos del usuario
class SeedUserDataTests(Base):
	def test_version_nueva_sobrescribe_sin_pisar_lo_del_usuario(self) -> None:
		app = self.program()
		user = os.path.join(self.tmp, "appdata")
		installer.seedUserData(os.path.join(app, "data"), user)
		self.assertEqual(_read(os.path.join(user, "symbols", "es.json")), "símbolos nuevos")
		with open(os.path.join(user, installer.SEED_MARKER), encoding="utf-8") as f:
			self.assertEqual(json.load(f)["version"], VERSION)
		# Datos del usuario: diccionario, símbolos propios (en config) y un tema de sonidos.
		_write(os.path.join(user, "speechDicts", "default.json"), "mi diccionario")
		_write(os.path.join(user, "config", "symbols_user.json"), "mis símbolos")
		_write(os.path.join(user, "sounds", "mitema", "inicio.wav"), "mi sonido")
		# Misma versión: lo que ya existe no se toca.
		_write(os.path.join(user, "symbols", "es.json"), "cambiado")
		installer.seedUserData(os.path.join(app, "data"), user)
		self.assertEqual(_read(os.path.join(user, "symbols", "es.json")), "cambiado")
		# Versión anterior (o sin marca, como las copias de antes): se actualiza.
		_write(os.path.join(user, installer.SEED_MARKER), json.dumps({"version": "1.0.5"}))
		_write(os.path.join(user, "sounds", "inicio.wav"), "sonido viejo")
		_write(os.path.join(user, "brailleTables", "tabla.json"), "tabla vieja")
		installer.seedUserData(os.path.join(app, "data"), user)
		self.assertEqual(_read(os.path.join(user, "symbols", "es.json")), "símbolos nuevos")
		self.assertEqual(_read(os.path.join(user, "sounds", "inicio.wav")), "sonido nuevo")
		self.assertEqual(_read(os.path.join(user, "brailleTables", "tabla.json")), "tabla nueva")
		self.assertEqual(_read(os.path.join(user, "speechDicts", "default.json")), "mi diccionario")
		self.assertEqual(_read(os.path.join(user, "config", "symbols_user.json")), "mis símbolos")
		self.assertEqual(_read(os.path.join(user, "sounds", "mitema", "inicio.wav")), "mi sonido")
		os.remove(os.path.join(user, installer.SEED_MARKER))
		_write(os.path.join(user, "symbols", "es.json"), "de una versión sin marca")
		installer.seedUserData(os.path.join(app, "data"), user)
		self.assertEqual(_read(os.path.join(user, "symbols", "es.json")), "símbolos nuevos")

	def test_simbolos_del_usuario_estan_en_config(self) -> None:
		from tiresias.speech import symbols

		self.assertNotIn("symbols/user.json", installer.USER_DATA_INCLUDE)
		self.assertIn("config", installer.USER_DATA_INCLUDE)
		self.assertIn("symbols_user", inspect.getsource(symbols))
		src = os.path.join(self.tmp, "datos")
		_write(os.path.join(src, "config", "symbols_user.json"), "mis símbolos")
		dest = os.path.join(self.tmp, "destino")
		installer.copyUserData(src, dest, includeAddons=False)
		self.assertEqual(_read(os.path.join(dest, "config", "symbols_user.json")), "mis símbolos")


# ====================================================================== 3, 4, 5, A: instalación silenciosa
class SilentInstallTests(Base):
	def test_argumentos_nuevos(self) -> None:
		from tiresias import core

		ns = core.parseArgs(["--install-silent", "--all-users", "1", "--no-elevate"])
		self.assertEqual(ns.all_users, "1")
		self.assertTrue(ns.no_elevate)
		self.assertIsNone(core.parseArgs([]).all_users)

	def test_todos_los_usuarios_en_carpeta_propia(self) -> None:
		folder = os.path.join(self.tmp, "Programas", "Tiresias")
		opts, _logon = installer.silentInstallPlan(_args(install_dir=folder, all_users="1"))
		self.assertTrue(opts.allUsers)
		opts, _logon = installer.silentInstallPlan(_args(install_dir=folder, all_users="0"))
		self.assertFalse(opts.allUsers)
		# Sin --all-users se deduce como antes: fuera de Archivos de programa, solo el usuario.
		opts, _logon = installer.silentInstallPlan(_args(install_dir=folder))
		self.assertFalse(opts.allUsers)
		args = installer.elevatedInstallArgs(installer.silentInstallPlan(_args(install_dir=folder, all_users="1"))[0])
		self.assertEqual(args[args.index("--all-users") + 1], "1")
		self.assertIn("--no-elevate", args)

	def test_carpeta_relativa_y_variables(self) -> None:
		opts, _logon = installer.silentInstallPlan(_args(install_dir="relativa"))
		self.assertTrue(os.path.isabs(opts.targetDir))
		self.assertEqual(opts.targetDir, os.path.abspath("relativa"))
		with mock.patch.dict(os.environ, {"TIRESIAS_PRUEBA_DIR": self.tmp}):
			opts, _logon = installer.silentInstallPlan(_args(install_dir=r"%TIRESIAS_PRUEBA_DIR%\Tiresias"))
		self.assertEqual(opts.targetDir, os.path.join(self.tmp, "Tiresias"))

	def test_hijo_elevado_no_inicia_nada_y_el_padre_si(self) -> None:
		folder = os.path.join(self.tmp, "Tiresias")
		args = _args(install_dir=folder, all_users="1", launch=True, start_on_logon=True)
		with mock.patch.object(installer, "isElevated", return_value=False), mock.patch.object(installer, "shellExecuteElevated", return_value=0) as elev, mock.patch.object(
			installer, "setRunAtLogon"
		) as run, mock.patch.object(installer.subprocess, "Popen") as popen:
			code = installer.runSilentInstall(args)
		self.assertEqual(code, 0)
		params = elev.call_args.args[1]
		self.assertNotIn("--launch", params)
		self.assertNotIn("--start-on-logon", params)
		self.assertIn("--no-elevate", params)
		self.assertIn("--all-users 1", params)
		exe = os.path.join(folder, "Tiresias.exe")
		run.assert_called_once_with(exe, True)
		self.assertEqual(popen.call_args.args[0], [exe])

	def test_fallo_del_hijo_no_inicia_nada(self) -> None:
		args = _args(install_dir=os.path.join(self.tmp, "T"), all_users="1", launch=True, start_on_logon=True)
		with mock.patch.object(installer, "isElevated", return_value=False), mock.patch.object(installer, "shellExecuteElevated", return_value=1), mock.patch.object(
			installer, "setRunAtLogon"
		) as run, mock.patch.object(installer.subprocess, "Popen") as popen:
			self.assertEqual(installer.runSilentInstall(args), 1)
		run.assert_not_called()
		popen.assert_not_called()

	def test_sin_elevar_no_vuelve_a_pedir_permiso(self) -> None:
		args = _args(install_dir=os.path.join(self.tmp, "T"), all_users="1", no_elevate=True)
		with mock.patch.object(installer, "isElevated", return_value=False), mock.patch.object(installer, "shellExecuteElevated") as elev:
			self.assertEqual(installer.runSilentInstall(args), 5)
		elev.assert_not_called()

	def test_desinstalar_sin_elevar_no_hace_bucle(self) -> None:
		with mock.patch.object(installer.paths, "isInstalledCopy", return_value=True), mock.patch.object(installer, "isElevated", return_value=False), mock.patch.object(
			installer, "shellExecuteElevated", return_value=0
		) as elev, mock.patch.object(installer, "_message"), mock.patch("builtins.open", mock.mock_open(read_data='{"allUsers": true}')):
			self.assertEqual(installer.runUninstall(interactive=False, noElevate=True), 5)
			elev.assert_not_called()
			installer.runUninstall(interactive=False)
		self.assertIn("--no-elevate", elev.call_args.args[1])

	def test_launch_desde_codigo_sin_consola(self) -> None:
		with mock.patch.object(installer.paths, "FROZEN", False):
			exe, args = installer._launch()
		if os.path.isfile(os.path.join(os.path.dirname(sys.executable), "pythonw.exe")):
			self.assertEqual(os.path.basename(exe).lower(), "pythonw.exe")
		self.assertTrue(args[0].endswith("tiresias.pyw"))


# ====================================================================== 6, B/E: actualizar una copia portable
class PortableUpdateTests(Base):
	def setUp(self) -> None:
		super().setUp()
		self.new = self.program("nueva", {"LEEME.txt": "nuevo"})
		self.old = os.path.join(self.tmp, "Tiresias")
		for rel, text in {
			"Tiresias.exe": "viejo",
			"python313.dll": "viejo",
			"LEEME.txt": "viejo",
			"lib/viejo.pyc": "x",
			"data/config/config.json": '{"mio": 1}',
		}.items():
			_write(os.path.join(self.old, *rel.split("/")), text)

	def test_quita_python313(self) -> None:
		installer.applyPortableUpdate(self.new, self.old)
		self.assertFalse(os.path.exists(os.path.join(self.old, "python313.dll")))
		self.assertEqual(_read(os.path.join(self.old, "python314.dll")), "nuevo")
		self.assertEqual(_read(os.path.join(self.old, "data", "config", "config.json")), '{"mio": 1}')

	def test_si_falla_restaura_python313_y_quita_lo_nuevo(self) -> None:
		real = installer.copyTree
		calls = [0]

		def failing(src, dst, *a, **kw):
			calls[0] += 1
			if calls[0] == 4:
				raise OSError("disco lleno")
			return real(src, dst, *a, **kw)

		with mock.patch.object(installer, "copyTree", side_effect=failing), self.assertRaises(OSError):
			installer.applyPortableUpdate(self.new, self.old)
		self.assertEqual(_read(os.path.join(self.old, "python313.dll")), "viejo")
		self.assertEqual(_read(os.path.join(self.old, "Tiresias.exe")), "viejo")
		self.assertFalse(os.path.exists(os.path.join(self.old, "python314.dll")))
		self.assertFalse(os.path.exists(os.path.join(self.old, installer.UPDATE_BACKUP_DIR)))

	def test_restauracion_parcial_sigue_y_conserva_la_copia(self) -> None:
		backup = os.path.join(self.old, installer.UPDATE_BACKUP_DIR)
		realReplace = os.replace

		def replace(src, dst):
			if os.path.normcase(src) == os.path.normcase(os.path.join(backup, "LEEME.txt")):
				raise PermissionError("en uso")
			return realReplace(src, dst)

		staging = os.path.join(self.old, installer.UPDATE_STAGING_DIR)
		placedFirst = [False]

		def replaceOrFail(src, dst):
			# Desde la 1.0.11 la copia lenta va a una carpeta de preparación y no
			# toca nada: el fallo que obliga a restaurar ocurre al sustituir.
			if os.path.normcase(src).startswith(os.path.normcase(staging)):
				if placedFirst[0]:
					raise OSError("disco lleno")
				placedFirst[0] = True
			return replace(src, dst)

		with mock.patch.object(installer.os, "replace", side_effect=replaceOrFail), self.assertRaises(OSError) as ctx:
			installer.applyPortableUpdate(self.new, self.old)
		self.assertIn("disco lleno", str(ctx.exception))
		# Lo demás se ha restaurado y la copia de seguridad se conserva con lo que falta.
		self.assertEqual(_read(os.path.join(self.old, "Tiresias.exe")), "viejo")
		self.assertEqual(_read(os.path.join(self.old, "python313.dll")), "viejo")
		self.assertTrue(os.path.isfile(os.path.join(self.old, "lib", "viejo.pyc")))
		self.assertEqual(_read(os.path.join(backup, "LEEME.txt")), "viejo")


# ====================================================================== 7: registro de las órdenes
class CommandLogTests(Base):
	def setUp(self) -> None:
		super().setUp()
		self._oldData = paths.DATA_DIR
		paths.setDataDir(os.path.join(self.tmp, "data"))

	def tearDown(self) -> None:
		paths.setDataDir(self._oldData)
		super().tearDown()

	def test_errores_de_las_ordenes_quedan_en_ordenes_log(self) -> None:
		from tiresias import comrepair, core, startup
		from tiresias.log import getLogger
		from tiresias.log import log as rootLog

		level, handlers = rootLog.level, list(rootLog.handlers)
		ns = core.parseArgs(["--repair-com", "--data", paths.DATA_DIR])

		def fails(noElevate: bool = False) -> int:
			getLogger("comRepair").error("No se pudo registrar prueba.dll")
			return 1

		with mock.patch.object(comrepair, "runFromCommandLine", side_effect=fails):
			self.assertEqual(startup.runStandaloneCommand(ns), 1)
		path = os.path.join(paths.logsDir(), startup.COMMAND_LOG)
		text = _read(path)
		self.assertIn("No se pudo registrar prueba.dll", text)
		self.assertIn("código 1", text)
		# El registrador queda como estaba.
		self.assertEqual(rootLog.level, level)
		self.assertEqual(rootLog.handlers, handlers)
		self.assertEqual(logging.getLogger("tiresias").handlers, handlers)

	def test_rutas_del_registro(self) -> None:
		from tiresias import core, startup

		self.assertIsNone(startup.commandLogPath(core.parseArgs(["--no-input"])))
		target = os.path.join(self.tmp, "portable")
		self.assertEqual(startup.commandLogPath(core.parseArgs(["--apply-update", target])), os.path.join(target, "data", "logs", startup.COMMAND_LOG))
		self.assertTrue(startup.commandLogPath(core.parseArgs(["--install-silent"])).startswith(paths.userDataDir()))
		self.assertFalse(startup.commandLogPath(core.parseArgs(["--uninstall"])).startswith(paths.userDataDir() + os.sep))


# ====================================================================== 8: reparación COM
class ComRepairTests(unittest.TestCase):
	def test_sin_administrador_eleva_y_avisa(self) -> None:
		from tiresias import comrepair

		with mock.patch.object(installer, "isElevated", return_value=False), mock.patch.object(comrepair, "runElevated", return_value=0) as elev, mock.patch.object(
			comrepair, "_showResult"
		) as show:
			self.assertEqual(comrepair.runFromCommandLine(), 0)
		elev.assert_called_once()
		show.assert_called_once_with(0)

	def test_permiso_denegado(self) -> None:
		from tiresias import comrepair

		with mock.patch.object(installer, "isElevated", return_value=False), mock.patch.object(comrepair, "runElevated", side_effect=OSError(1223, "cancelado")), mock.patch.object(
			comrepair, "_showResult"
		) as show:
			self.assertEqual(comrepair.runFromCommandLine(), 5)
		show.assert_called_once_with(5)
		self.assertTrue(comrepair.resultMessage(5)[1])
		self.assertFalse(comrepair.resultMessage(0)[1])

	def test_no_elevate_no_hace_bucle(self) -> None:
		from tiresias import comrepair

		with mock.patch.object(installer, "isElevated", return_value=False), mock.patch.object(comrepair, "runElevated") as elev, mock.patch.object(comrepair, "_showResult") as show:
			self.assertEqual(comrepair.runFromCommandLine(noElevate=True), 5)
		elev.assert_not_called()
		show.assert_not_called()
		with mock.patch.object(installer, "shellExecuteElevated", return_value=0) as sh:
			comrepair.runElevated()
		self.assertIn("--no-elevate", sh.call_args.args[1])


# ====================================================================== 9: valores del diálogo
class DialogDefaultsTests(unittest.TestCase):
	def test_copiar_configuracion(self) -> None:
		d = installer.installDialogDefaults({}, hasOwnConfig=True, fromInstallerTemp=False)
		self.assertTrue(d["copyConfig"])
		self.assertTrue(d["desktop"] and d["startMenu"])
		self.assertFalse(d["logon"])
		# Al actualizar una copia instalada no se pisa su configuración.
		info = {"DisplayVersion": "1.0.5", "InstallLocation": r"C:\Programas\Tiresias", "AllUsers": 0, "DesktopShortcut": "", "StartMenuFolder": r"C:\menu\Tiresias"}
		d = installer.installDialogDefaults(info, hasOwnConfig=True, fromInstallerTemp=False, runCommand=r'"C:\Programas\Tiresias\Tiresias.exe"')
		self.assertFalse(d["copyConfig"])
		self.assertFalse(d["allUsers"])
		self.assertFalse(d["desktop"])
		self.assertTrue(d["startMenu"])
		self.assertTrue(d["logon"])
		# Desde la copia temporal del instalador, tampoco.
		self.assertFalse(installer.installDialogDefaults({}, hasOwnConfig=True, fromInstallerTemp=True)["copyConfig"])

	def test_copia_temporal_del_instalador(self) -> None:
		temp = os.path.join(tempfile.gettempdir(), "TiresiasInstalador", "Tiresias")
		self.assertTrue(installer.isInstallerTempCopy(temp))
		self.assertFalse(installer.isInstallerTempCopy(r"C:\Program Files\Tiresias"))


# ====================================================================== 10, G: diálogo
class DialogTests(unittest.TestCase):
	def test_no_se_cierra_mientras_instala(self) -> None:
		from tiresias.gui import installer_dialogs as dlg

		fake = SimpleNamespace(_busy=True, Hide=mock.Mock(), Destroy=mock.Mock())
		with mock.patch.object(dlg, "speakMessage") as speak:
			dlg.InstallDialog._close(fake)
		fake.Destroy.assert_not_called()
		speak.assert_called_once()
		evt = mock.Mock()
		evt.CanVeto.return_value = True
		fake._close = mock.Mock()
		with mock.patch.object(dlg, "speakMessage"):
			dlg.InstallDialog._onCloseEvent(fake, evt)
		evt.Veto.assert_called_once()
		fake._close.assert_not_called()
		fake._busy = False
		dlg.InstallDialog._close(fake)
		fake.Destroy.assert_called_once()

	def test_politica_impide_instalar(self) -> None:
		from tiresias.config import policy as policyModule
		from tiresias.gui import installer_dialogs as dlg

		with mock.patch.object(policyModule, "policy", policyModule.Policy({"allowInstall": False})), mock.patch.object(dlg, "showError") as err, mock.patch.object(
			dlg, "parentWindow", return_value=None
		), mock.patch.object(dlg, "InstallDialog") as cls:
			dlg.showInstallDialog()
		err.assert_called_once()
		cls.assert_not_called()
		secure = policyModule.Policy({})
		secure.secureMode = True
		with mock.patch.object(policyModule, "policy", secure), mock.patch.object(dlg, "showError") as err, mock.patch.object(dlg, "parentWindow", return_value=None), mock.patch.object(
			dlg, "InstallDialog"
		) as cls:
			dlg.showInstallDialog()
		cls.assert_not_called()


# ====================================================================== 11: accesos directos e inicio automático
class ReinstallShortcutTests(Base):
	def setUp(self) -> None:
		super().setUp()
		self.keys = [TEST_KEY + r"\Uninstall\Tiresias", TEST_KEY + r"\Run", TEST_KEY + r"\Uninstall", TEST_KEY]

	def tearDown(self) -> None:
		import winreg

		for k in self.keys:
			try:
				winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, k, winreg.KEY_WOW64_64KEY, 0)
			except OSError:
				pass
		super().tearDown()

	def test_desmarcar_quita_los_antiguos(self) -> None:
		app = self.program()
		target = os.path.join(self.tmp, "Tiresias")
		menu = os.path.join(self.tmp, "menu", "Tiresias")
		desk = os.path.join(self.tmp, "escritorio")
		os.makedirs(desk)
		targets = installer.SystemTargets(allUsers=False, uninstallKey=self.keys[0], runKey=self.keys[1], startMenuDir=menu, desktopDir=desk)
		exe = installer.install(installer.InstallOptions(targetDir=target, allUsers=False, sourceDir=app, startOnLogon=True, targets=targets))
		self.assertTrue(os.path.isfile(os.path.join(menu, "Tiresias.lnk")))
		self.assertTrue(os.path.isfile(os.path.join(desk, "Tiresias.lnk")))
		self.assertIn(exe, installer.runAtLogonCommand(self.keys[1]))
		# Otro acceso directo «Tiresias» que no es de esta copia (una portable) se respeta.
		other = os.path.join(self.tmp, "otro")
		os.makedirs(other)
		installer.makeShortcut(os.path.join(other, "Tiresias.lnk"), os.path.join(self.tmp, "portable", "Tiresias.exe"))
		# Sin tocar el inicio automático (None), se conserva.
		installer.install(installer.InstallOptions(targetDir=target, allUsers=False, sourceDir=app, startOnLogon=None, targets=targets))
		self.assertIn(exe, installer.runAtLogonCommand(self.keys[1]))
		installer.install(installer.InstallOptions(targetDir=target, allUsers=False, sourceDir=app, desktopShortcut=False, startMenu=False, startOnLogon=False, targets=targets))
		self.assertFalse(os.path.exists(os.path.join(desk, "Tiresias.lnk")))
		self.assertFalse(os.path.exists(menu))
		self.assertEqual(installer.runAtLogonCommand(self.keys[1]), "")
		self.assertTrue(os.path.isfile(os.path.join(other, "Tiresias.lnk")))
		self.assertFalse(installer._removeShortcutInto(os.path.join(other, "Tiresias.lnk"), target))
		info = installer.installedInfo(targets)
		self.assertEqual(info["StartMenuFolder"], "")
		self.assertEqual(info["DesktopShortcut"], "")

	def test_inicio_automatico_de_otra_copia_no_se_quita(self) -> None:
		installer.setRunAtLogon(os.path.join(self.tmp, "portable", "Tiresias.exe"), True, self.keys[1])
		self.assertFalse(installer.removeRunAtLogonIfFrom(os.path.join(self.tmp, "Tiresias", "Tiresias.exe"), self.keys[1]))
		self.assertIn("portable", installer.runAtLogonCommand(self.keys[1]))


# ====================================================================== 12: copia portable
class PortableCopyTests(Base):
	def test_no_encima_de_una_copia_instalada(self) -> None:
		app = self.program()
		dest = os.path.join(self.tmp, "instalada")
		_write(os.path.join(dest, "Tiresias.exe"), "instalado")
		_write(os.path.join(dest, paths.INSTALLED_MARKER), "{}")
		with self.assertRaises(ValueError):
			installer.createPortableCopy(dest, appDir=app, dataDir=os.path.join(self.tmp, "datos"), programDataDir=os.path.join(app, "data"), frozen=True)
		self.assertEqual(_read(os.path.join(dest, "Tiresias.exe")), "instalado")
		self.assertTrue(os.path.isfile(os.path.join(dest, paths.INSTALLED_MARKER)))


# ====================================================================== 13: desinstalar
class UninstallCloseTests(unittest.TestCase):
	def test_solo_se_cierra_la_copia_de_la_carpeta(self) -> None:
		folder = r"C:\Program Files\Tiresias"
		self.assertTrue(installer.shouldCloseRunning(1234, r"C:\Program Files\Tiresias\Tiresias.exe", folder))
		self.assertFalse(installer.shouldCloseRunning(1234, r"D:\Portable\Tiresias\Tiresias.exe", folder))
		self.assertFalse(installer.shouldCloseRunning(1234, r"C:\Program Files\Tiresias2\Tiresias.exe", folder))
		self.assertFalse(installer.shouldCloseRunning(1234, r"E:\proyecto\.venv\Scripts\pythonw.exe", folder))
		self.assertFalse(installer.shouldCloseRunning(1234, "", folder))
		self.assertFalse(installer.shouldCloseRunning(0, r"C:\Program Files\Tiresias\Tiresias.exe", folder))
		self.assertFalse(installer.shouldCloseRunning(os.getpid(), r"C:\Program Files\Tiresias\Tiresias.exe", folder))

	def test_cierre_simulado(self) -> None:
		from tiresias import core

		folder = r"C:\Program Files\Tiresias"
		with mock.patch.object(installer, "_runningInstance", return_value=(4321, r"D:\Portable\Tiresias.exe")), mock.patch.object(core, "_closeRunningInstance") as close:
			self.assertFalse(installer.closeRunningInstanceIn(folder))
		close.assert_not_called()
		with mock.patch.object(installer, "_runningInstance", return_value=(4321, folder + r"\Tiresias.exe")), mock.patch.object(core, "_closeRunningInstance", return_value=True) as close:
			self.assertTrue(installer.closeRunningInstanceIn(folder))
		close.assert_called_once_with()


# ====================================================================== 15: power
class PowerTests(unittest.TestCase):
	def test_terminate_se_llama_al_cerrar(self) -> None:
		from tiresias import core

		self.assertIn("power.terminate", inspect.getsource(core._terminateCore))


if __name__ == "__main__":
	unittest.main()
