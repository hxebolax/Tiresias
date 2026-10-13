"""Pruebas básicas de la lógica de Tiresias que no necesita pantalla ni voz.

Ejecutar con: ``.venv\\Scripts\\python.exe -m unittest discover tests``
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="tiresias_test_")
shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
paths.setDataDir(_TMP)
paths.ensureDataDirs()

from tiresias.baseobject import ScriptableObject, normalizeGestureId, script  # noqa: E402
from tiresias.braille import tables  # noqa: E402
from tiresias.config import ConfigManager  # noqa: E402
from tiresias.speech.symbols import LEVEL_ALL, LEVEL_NONE, LEVEL_SOME, SymbolProcessor  # noqa: E402
from tiresias.textinfo import UNIT_LINE, UNIT_WORD, StaticTextInfo  # noqa: E402


class ConfigTests(unittest.TestCase):
	def setUp(self) -> None:
		self.conf = ConfigManager()

	def test_defaults(self) -> None:
		self.assertEqual(self.conf["speech"]["symbolLevel"], 100)

	def test_profile_overrides_base(self) -> None:
		self.conf["speech"]["symbolLevel"] = 200
		self.conf.createProfile("Prueba")
		self.conf.setManualProfile("Prueba")
		self.conf["speech"]["symbolLevel"] = 300
		self.assertEqual(self.conf["speech"]["symbolLevel"], 300)
		self.conf.setManualProfile(None)
		self.assertEqual(self.conf["speech"]["symbolLevel"], 200)
		self.conf.deleteProfile("Prueba")

	def test_triggers(self) -> None:
		self.conf.createProfile("Bloc")
		self.conf.profiles["Bloc"].data = {"speech": {"symbolLevel": 0}}
		self.conf.setTrigger("app:notepad", "Bloc")
		self.conf.enterTrigger("app:notepad")
		self.assertEqual(self.conf["speech"]["symbolLevel"], 0)
		self.conf.exitTrigger("app:notepad")
		self.assertEqual(self.conf["speech"]["symbolLevel"], 100)
		self.conf.deleteProfile("Bloc")

	def test_register_defaults(self) -> None:
		self.conf.registerDefaults("miComplemento", {"activo": True})
		self.assertTrue(self.conf["miComplemento"]["activo"])


class GestureTests(unittest.TestCase):
	def test_normalize(self) -> None:
		self.assertEqual(normalizeGestureId("kb:NVDA+Shift+A"), "kb:tiresias+shift+a")
		self.assertEqual(normalizeGestureId("kb:shift+control+upArrow"), "kb:control+shift+uparrow")
		self.assertEqual(normalizeGestureId("kb(laptop):Tiresias+L"), "kb(laptop):tiresias+l")

	def test_class_gestures(self) -> None:
		class Obj(ScriptableObject):
			@script(gesture="kb:tiresias+t")
			def script_titulo(self, gesture):
				pass

		self.assertEqual(dict(Obj.iterClassGestures())["kb:tiresias+t"], "titulo")


class SymbolTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		cls.proc = SymbolProcessor()
		cls.proc.load()

	def test_levels(self) -> None:
		self.assertIn("coma", self.proc.process("a, b", LEVEL_ALL))
		self.assertNotIn("coma", self.proc.process("a, b", LEVEL_SOME))

	def test_numbers_untouched(self) -> None:
		self.assertIn("1.500,25", self.proc.process("Son 1.500,25 euros", LEVEL_ALL))

	def test_repeated(self) -> None:
		self.assertIn("10 guion", self.proc.process("----------", LEVEL_NONE))

	def test_character_names(self) -> None:
		self.assertEqual(self.proc.characterName(" "), "espacio")
		self.assertEqual(self.proc.characterName("ñ"), "eñe")


class TextInfoTests(unittest.TestCase):
	def test_lines_and_words(self) -> None:
		info = StaticTextInfo(None, (0, 0), "hola mundo\nsegunda línea\n")
		info.expand(UNIT_LINE)
		self.assertEqual(info.text, "hola mundo\n")
		info.collapse()
		self.assertEqual(info.move(UNIT_LINE, 1), 1)
		info.expand(UNIT_LINE)
		self.assertEqual(info.text, "segunda línea\n")
		w = StaticTextInfo(None, (0, 0), "hola mundo")
		w.expand(UNIT_WORD)
		self.assertEqual(w.text, "hola ")


class BrailleTests(unittest.TestCase):
	def test_comp8_capital(self) -> None:
		t = tables.getTable("es-comp8").translate("Aa")
		self.assertEqual(t.cells, [0x41, 0x01])

	def test_g1_number(self) -> None:
		t = tables.getTable("es-g1").translate("12")
		self.assertEqual(t.cells[0], tables.NUMBER_SIGN)
		self.assertEqual(len(t.cells), 3)


class AddonTests(unittest.TestCase):
	def test_package_roundtrip(self) -> None:
		from tiresias import addons

		src = os.path.join(ROOT, "data", "addons", "whatsapp")
		out = os.path.join(_TMP, "wa.tiresias-addon")
		addons.createPackage(src, out)
		addon = addons.installFromFile(out)
		self.assertEqual(addon.id, "whatsapp")
		self.assertTrue(os.path.isfile(os.path.join(paths.addonsDir(), "whatsapp", "manifest.json")))


if __name__ == "__main__":
	unittest.main()
