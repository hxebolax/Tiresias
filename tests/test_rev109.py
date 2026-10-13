"""Pruebas de regresión de la versión 1.0.9: API para los complementos de la tienda.

- ``gui.registerToolsMenuItem``: entradas y submenús de complementos en el menú
  Herramientas.
- ``paths.addonDataDir``: carpeta de datos de cada complemento.
- F1 en la categoría de un complemento abre la ayuda del complemento.
- La tienda avisa de los complementos propietarios.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev109 -v``
"""

from __future__ import annotations

import inspect
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_rev109_")
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]

import wx  # noqa: E402

from tiresias import addons  # noqa: E402
from tiresias import gui  # noqa: E402
from tiresias.gui import context_help, settings, system_dialogs  # noqa: E402

_app = wx.App.Get() or wx.App(False)


class TestMenuHerramientas(unittest.TestCase):
	def tearDown(self) -> None:
		gui.unregisterToolsMenuItem("prueba")
		gui.unregisterToolsMenuItem("prueba2")

	def _labels(self, menu: wx.Menu) -> list[str]:
		return [item.GetItemLabel().replace("&", "") for item in menu.GetMenuItems()]

	def _tools(self, frame) -> wx.Menu:
		# Se guarda el menú principal: si no, wx destruye el submenú.
		self._menu = menu = gui._buildMainMenu(frame)
		for item in menu.GetMenuItems():
			if item.GetItemLabel().replace("&", "") == "Herramientas":
				return item.GetSubMenu()
		self.fail("No hay menú Herramientas")

	def test_entrada_y_submenu(self) -> None:
		frame = gui.MainFrame("prueba")
		try:
			called = []
			gui.registerToolsMenuItem("prueba", "Mi &radio...", lambda: called.append(1))
			gui.registerToolsMenuItem("prueba2", "&Utilidades", lambda: [("Uno", lambda: None), None, ("Más", [("Dos", lambda: None)])], submenu=True)
			tools = self._tools(frame)
			labels = self._labels(tools)
			self.assertIn("Mi radio...", labels)
			self.assertIn("Utilidades", labels)
			self.assertLess(labels.index("Mi radio..."), labels.index("Utilidades"))
			self.assertLess(labels.index("Utilidades"), labels.index("Visor de registro..."))
			sub = next(i.GetSubMenu() for i in tools.GetMenuItems() if i.GetItemLabel().replace("&", "") == "Utilidades")
			self.assertEqual([lbl for lbl in self._labels(sub) if lbl], ["Uno", "Más"])
			# La acción queda registrada en el marco.
			item = next(i for i in tools.GetMenuItems() if i.GetItemLabel().replace("&", "") == "Mi radio...")
			frame._menuActions[item.GetId()]()
			self.assertEqual(called, [1])
			gui.unregisterToolsMenuItem("prueba")
			self.assertNotIn("Mi radio...", self._labels(self._tools(frame)))
		finally:
			frame.Destroy()

	def test_un_submenu_que_falla_no_rompe_el_menu(self) -> None:
		frame = gui.MainFrame("prueba")
		try:

			def roto():
				raise RuntimeError("fallo")

			gui.registerToolsMenuItem("prueba", "Roto", roto, submenu=True)
			self.assertIn("Visor de registro...", self._labels(self._tools(frame)))
		finally:
			frame.Destroy()


class TestDatosDeComplementos(unittest.TestCase):
	def test_carpeta(self) -> None:
		p = paths.addonDataDir("miComplemento")
		self.assertTrue(os.path.isdir(p))
		self.assertEqual(p, os.path.join(paths.DATA_DIR, "addonsData", "miComplemento"))

	def test_no_se_publica(self) -> None:
		sys.path.insert(0, os.path.join(ROOT, "tools"))
		import publicar

		self.assertIn("addonsData", publicar.PRIVATE_DATA)


class TestAyudaDeComplementos(unittest.TestCase):
	def setUp(self) -> None:
		self.tmp = tempfile.mkdtemp(prefix="tiresias_ayuda_")
		doc = os.path.join(self.tmp, "doc", "es")
		os.makedirs(doc)
		self.readme = os.path.join(doc, "readme.html")
		with open(self.readme, "w", encoding="utf-8") as f:
			f.write("<html></html>")
		self.addon = addons.Addon(self.tmp, {"id": "miAyuda", "version": "1.0.0"})

	def tearDown(self) -> None:
		settings._panels.pop("miAyuda", None)
		shutil.rmtree(self.tmp, ignore_errors=True)

	def test_readme_del_complemento(self) -> None:
		cls = type("Panel", (settings.SettingsPanel,), {"__module__": "tiresias_addons.miAyuda.globalPlugins.x"})
		settings.registerPanel("miAyuda", "Mi ayuda", cls)
		with mock.patch.object(addons, "getAddons", return_value=[self.addon]):
			self.assertEqual(os.path.normpath(context_help.addonHelpFor("miAyuda")), self.readme)
			with mock.patch.object(os, "startfile", create=True) as start:
				self.assertEqual(context_help.openHelp("miAyuda"), "")
				self.assertEqual(os.path.normpath(start.call_args[0][0]), self.readme)

	def test_helpPath(self) -> None:
		cls = type("Panel", (settings.SettingsPanel,), {"helpPath": self.readme})
		settings.registerPanel("miAyuda", "Mi ayuda", cls)
		self.assertEqual(context_help.addonHelpFor("miAyuda"), self.readme)

	def test_categorias_del_nucleo(self) -> None:
		self.assertIsNone(context_help.addonHelpFor("speech"))
		self.assertIsNone(context_help.addonHelpFor(None))


class TestTiendaPropietarios(unittest.TestCase):
	def test_aviso_y_confirmacion(self) -> None:
		src = inspect.getsource(system_dialogs.AddonStoreDialog)
		self.assertIn('e.extra.get("proprietary")', src)
		self.assertIn("necesitas una licencia válida", src)

	def test_catalogo_conserva_la_marca(self) -> None:
		from tiresias import addon_store

		entries = addon_store.parseCatalog({"format": "tiresias-catalogo", "addons": [{"id": "voz", "version": "1.0.0", "proprietary": True}]})
		self.assertTrue(entries[0].extra.get("proprietary"))


class TestComplementosDeLaTienda(unittest.TestCase):
	def test_manifiestos(self) -> None:
		base = os.path.join(ROOT, "complementos_tienda")
		ids = []
		for entry in sorted(os.listdir(base)):
			folder = os.path.join(base, entry)
			if not os.path.isdir(folder):
				continue
			m = addons._readManifest(folder)
			self.assertIsNotNone(m, entry)
			self.assertEqual(m["id"], entry)
			for k in ("name", "version", "author", "description"):
				self.assertTrue(m.get(k), f"{entry}: falta {k}")
			ids.append(entry)
			if not m.get("proprietary"):
				self.assertTrue(os.path.isfile(os.path.join(folder, "doc", "es", "readme.html")), entry)
		# La voz Álvaro (propietaria de Microsoft) no está en el repositorio público.
		hasVoice = os.path.isdir(os.path.join(base, "NeuralVoices-voz-Alvaro"))
		self.assertGreaterEqual(len(ids), 8 if hasVoice else 7)


if __name__ == "__main__":
	unittest.main()
