"""Todo lo que Tiresias necesita o genera está dentro de ``data``.

Comprueba las rutas de los binarios (API de control, Escritorio remoto,
eSpeak NG), los documentos, los temporales, la copia limpia de
``tools/build_data.py`` y que el instalador lleve esas carpetas.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from tiresias import paths  # noqa: E402


def _write(path: str, text: str = "x") -> None:
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "w", encoding="utf-8") as f:
		f.write(text)


class ProgramPathsTests(unittest.TestCase):
	def test_binaries_inside_program_data(self) -> None:
		base = os.path.normcase(paths.PROGRAM_DATA_DIR) + os.sep
		for path in (paths.controllerBinDir(), paths.rdpBinDir(), paths.espeakDir()):
			self.assertTrue(os.path.normcase(path).startswith(base), path)
		self.assertEqual(paths.controllerBinDir(), os.path.join(paths.PROGRAM_DATA_DIR, "controller"))
		self.assertEqual(paths.rdpBinDir(), os.path.join(paths.PROGRAM_DATA_DIR, "rdp"))
		self.assertEqual(paths.espeakDir(), os.path.join(paths.PROGRAM_DATA_DIR, "synthDrivers", "espeak"))

	def test_source_tree_has_binaries_in_data(self) -> None:
		# Desde el código fuente los binarios ya compilados están en data.
		self.assertFalse(os.path.isdir(os.path.join(ROOT, "controller", "x64")))
		self.assertFalse(os.path.isdir(os.path.join(ROOT, "rdp", "x64")))
		self.assertTrue(os.path.isfile(os.path.join(ROOT, "data", "controller", "x64", "tiresiasControllerServer.dll")))
		self.assertTrue(os.path.isfile(os.path.join(ROOT, "data", "rdp", "x64", "tiresiasRdpClient.dll")))

	def test_louis_and_locale_in_data(self) -> None:
		from tiresias import i18n  # noqa: F401
		from tiresias.braille import liblouis

		self.assertEqual(paths.louisDir(), os.path.join(paths.PROGRAM_DATA_DIR, "louis"))
		self.assertEqual(paths.localeDir(), os.path.join(paths.PROGRAM_DATA_DIR, "locale"))
		self.assertEqual(liblouis.DLL_PATH, os.path.join(paths.louisDir(), "liblouis.dll"))
		self.assertEqual(liblouis.TABLES_DIR, os.path.join(paths.louisDir(), "tables"))
		self.assertTrue(os.path.isfile(liblouis.DLL_PATH))
		self.assertTrue(os.path.isfile(os.path.join(paths.localeDir(), "en", "LC_MESSAGES", "tiresias.mo")))
		self.assertTrue(os.path.isfile(os.path.join(paths.localeDir(), "tiresias.pot")))

	def test_package_has_only_code(self) -> None:
		# Dentro de src/tiresias solo hay código Python: los datos están en data.
		base = os.path.join(ROOT, "src", "tiresias")
		others = []
		for dirpath, dirs, files in os.walk(base):
			dirs[:] = [d for d in dirs if d != "__pycache__"]
			others += [os.path.relpath(os.path.join(dirpath, f), base) for f in files if not f.endswith((".py", ".pyc"))]
		self.assertEqual(others, [])

	def test_i18n_tool_uses_data_locale(self) -> None:
		import i18n as tool

		self.assertEqual(tool.LOCALE, os.path.join(ROOT, "data", "locale"))
		self.assertEqual(os.path.dirname(tool.POT), tool.LOCALE)

	def test_controller_server_path(self) -> None:
		from tiresias.controller import server

		self.assertEqual(server.controllerDir(), paths.controllerBinDir())
		self.assertEqual(server.serverDllPath(), os.path.join(paths.controllerBinDir(), "x64", "tiresiasControllerServer.dll"))

	def test_rdp_dll_path(self) -> None:
		from tiresias.remote.rdp_registration import dllPath

		self.assertEqual(dllPath("x64"), os.path.join(paths.rdpBinDir(), "x64", "tiresiasRdpClient.dll"))
		self.assertEqual(dllPath("x86", r"C:\Prog\Tiresias"), os.path.join(r"C:\Prog\Tiresias", "data", "rdp", "x86", "tiresiasRdpClient.dll"))

	def test_espeak_prefers_data(self) -> None:
		from tiresias.synth import espeak

		dirs = espeak._candidateDirs()
		self.assertEqual(dirs[0], paths.espeakDir())
		# Desde el código se admite también el paquete espeakng_loader, después.
		self.assertTrue(any("espeakng_loader" in d for d in dirs[1:]))

	def test_espeak_data_copy_wins(self) -> None:
		from tiresias.synth import espeak

		tmp = tempfile.mkdtemp()
		try:
			_write(os.path.join(tmp, "synthDrivers", "espeak", "espeak-ng.dll"))
			os.makedirs(os.path.join(tmp, "synthDrivers", "espeak", "espeak-ng-data"))
			with mock.patch.object(paths, "PROGRAM_DATA_DIR", tmp):
				self.assertEqual(espeak.findLibrary(), (os.path.join(tmp, "synthDrivers", "espeak", "espeak-ng.dll"), os.path.join(tmp, "synthDrivers", "espeak")))
		finally:
			shutil.rmtree(tmp, ignore_errors=True)

	def test_doc_path_prefers_data_docs(self) -> None:
		tmp = tempfile.mkdtemp()
		try:
			with mock.patch.object(paths, "PROGRAM_DATA_DIR", tmp):
				# Sin data/docs: docs de la raíz.
				self.assertEqual(paths.docPath("novedades.html"), os.path.join(paths.APP_DIR, "docs", "novedades.html"))
				_write(os.path.join(tmp, "docs", "novedades.html"))
				self.assertEqual(paths.docPath("novedades.html"), os.path.join(tmp, "docs", "novedades.html"))
		finally:
			shutil.rmtree(tmp, ignore_errors=True)


class TempDirTests(unittest.TestCase):
	def setUp(self) -> None:
		self.tmp = tempfile.mkdtemp()
		self._old = paths.DATA_DIR
		paths.setDataDir(self.tmp)

	def tearDown(self) -> None:
		paths.DATA_DIR = self._old
		shutil.rmtree(self.tmp, ignore_errors=True)

	def test_temp_and_comtypes_inside_data(self) -> None:
		self.assertEqual(paths.tempDir(), os.path.join(self.tmp, "temp"))
		self.assertEqual(paths.comtypesCacheDir(), os.path.join(self.tmp, "cache", "comtypes"))
		paths.ensureDataDirs()
		self.assertTrue(os.path.isdir(paths.tempDir()))

	def test_clean_temp_keeps_recent(self) -> None:
		old = os.path.join(paths.tempDir(), "viejo.png")
		oldDir = os.path.join(paths.tempDir(), "adjuntos", "adjunto-1")
		new = os.path.join(paths.tempDir(), "nuevo.png")
		_write(old)
		_write(os.path.join(oldDir, "a.txt"))
		_write(new)
		past = time.time() - 3 * 86400
		for p in (old, os.path.join(paths.tempDir(), "adjuntos")):
			os.utime(p, (past, past))
		paths.cleanTempDir()
		self.assertFalse(os.path.exists(old))
		self.assertFalse(os.path.exists(os.path.join(paths.tempDir(), "adjuntos")))
		self.assertTrue(os.path.exists(new))

	def test_outlook_attachments_in_data_temp(self) -> None:
		from tiresias.appmodules import outlook

		root = outlook._tempRoot()
		self.assertEqual(root, os.path.join(self.tmp, "temp", "adjuntos"))
		self.assertTrue(os.path.isdir(root))


class CleanDataTests(unittest.TestCase):
	def setUp(self) -> None:
		self.tmp = tempfile.mkdtemp()

	def tearDown(self) -> None:
		shutil.rmtree(self.tmp, ignore_errors=True)

	def test_build_clean_data(self) -> None:
		import build_data

		include = ["controller", "rdp", "synthDrivers", "louis", "docs", "images", "symbols"]
		with mock.patch.object(build_data, "INCLUDE", include):
			build_data.buildCleanData(self.tmp)
		data = os.path.join(self.tmp, "data")
		for rel in (
			"controller/x64/tiresiasControllerServer.dll",
			"controller/x64/tiresiasNvdaWindow.exe",
			"controller/x86/tiresiasControllerClient.dll",
			"controller/include/tiresiasControllerClient.h",
			"controller/examples/ejemplo.py",
			"rdp/x64/tiresiasRdpClient.dll",
			"rdp/x86/tiresiasRdpClient.dll",
			"synthDrivers/espeak/espeak-ng.dll",
			"docs/api_control.md",
			"docs/novedades.html",
			"docs/catalogo_complementos.json",
			"images/tiresias.ico",
			"louis/liblouis.dll",
			"louis/tables/es.tbl",
			"louis/COPYING.LESSER.txt",
			"locale/en/LC_MESSAGES/tiresias.mo",
		):
			self.assertTrue(os.path.isfile(os.path.join(data, *rel.split("/"))), rel)
		# Los .po y el .pot son para traductores: no se distribuyen.
		self.assertFalse(os.path.exists(os.path.join(data, "locale", "tiresias.pot")))
		self.assertFalse(os.path.exists(os.path.join(data, "locale", "en", "LC_MESSAGES", "tiresias.po")))
		self.assertTrue(os.path.isdir(os.path.join(data, "synthDrivers", "espeak", "espeak-ng-data")))
		# El programa de pruebas de Escritorio remoto no se distribuye.
		for root, _dirs, files in os.walk(os.path.join(data, "rdp")):
			self.assertNotIn("rdpTestHost.exe", files)
		# Datos del usuario: carpetas vacías.
		for rel in ("config", "logs", "cache", "temp", "labels", "voices"):
			folder = os.path.join(data, rel)
			self.assertTrue(os.path.isdir(folder), rel)
			self.assertEqual([f for f in os.listdir(folder) if f != "profiles"], [], rel)

	def test_whitelist_excludes_user_data(self) -> None:
		import build_data

		for rel in ("config", "logs", "cache", "temp", "labels", "voices"):
			self.assertNotIn(rel, build_data.INCLUDE)


class InstallerDataTests(unittest.TestCase):
	def setUp(self) -> None:
		self.tmp = tempfile.mkdtemp()

	def tearDown(self) -> None:
		shutil.rmtree(self.tmp, ignore_errors=True)

	def test_install_copies_program_data_and_removes_legacy(self) -> None:
		from tiresias import installer

		app = os.path.join(self.tmp, "programa")
		for rel in (
			"Tiresias.exe",
			"lib/tiresias/core.pyc",
			"data/controller/x64/tiresiasControllerServer.dll",
			"data/rdp/x64/tiresiasRdpClient.dll",
			"data/synthDrivers/espeak/espeak-ng.dll",
			"data/docs/novedades.html",
			"data/images/tiresias.ico",
			"data/louis/liblouis.dll",
			"data/locale/en/LC_MESSAGES/tiresias.mo",
			"data/config/config.json",
		):
			_write(os.path.join(app, *rel.split("/")))
		target = os.path.join(self.tmp, "instalado")
		# Restos de una versión anterior (antes de 1.0.2) con las carpetas fuera de data.
		for rel in ("Tiresias.exe", "controller/x64/viejo.dll", "rdp/x64/tiresiasRdpClient.dll", "synthDrivers/espeak/espeak-ng.dll", "docs/novedades.html", "share/licenses/x.txt", "tiresias.ico"):
			_write(os.path.join(target, *rel.split("/")))
		opts = installer.InstallOptions(
			targetDir=target,
			allUsers=False,
			desktopShortcut=False,
			startMenu=False,
			sourceDir=app,
			targets=installer.SystemTargets(writeRegistry=False),
		)
		installer.install(opts)
		for rel in (
			"data/controller/x64/tiresiasControllerServer.dll",
			"data/rdp/x64/tiresiasRdpClient.dll",
			"data/synthDrivers/espeak/espeak-ng.dll",
			"data/docs/novedades.html",
			"data/images/tiresias.ico",
			"data/louis/liblouis.dll",
			"data/locale/en/LC_MESSAGES/tiresias.mo",
		):
			self.assertTrue(os.path.isfile(os.path.join(target, *rel.split("/"))), rel)
		for rel in ("controller", "rdp", "synthDrivers", "docs", "share", "tiresias.ico"):
			self.assertFalse(os.path.exists(os.path.join(target, rel)), rel)
		# La configuración del desarrollador nunca se instala.
		self.assertFalse(os.path.exists(os.path.join(target, "data", "config", "config.json")))


if __name__ == "__main__":
	unittest.main()
