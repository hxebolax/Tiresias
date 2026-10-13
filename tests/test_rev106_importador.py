"""Pruebas de regresión de la revisión del importador de NVDA (1.0.6).

Cada clase cubre uno de los hallazgos de la revisión de ``tiresias.nvda_import``
y del diálogo ``tiresias.gui.nvda_import_dialog``. Todo se hace en carpetas
temporales sintéticas: nunca se lee ni se escribe la configuración real de NVDA.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev106_importador``
"""

from __future__ import annotations

import contextlib
import copy
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import nvda_import as ni, paths  # noqa: E402
from tiresias.config import ConfigManager, conf  # noqa: E402


def _write(path: str, text: str) -> None:
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "w", encoding="utf-8") as f:
		f.write(text)


def _read(path: str) -> str:
	with open(path, encoding="utf-8") as f:
		return f.read()


class _Base(unittest.TestCase):
	"""Carpeta de datos de Tiresias temporal y una configuración propia."""

	def setUp(self) -> None:
		self._oldData = paths.DATA_DIR
		self._oldConfig = paths._configDirOverride
		self.tmp = tempfile.mkdtemp(prefix="tiresias_rev106_")
		self.data = os.path.join(self.tmp, "data")
		paths.setDataDir(self.data)
		paths.setConfigDir(None)
		paths.ensureDataDirs()
		shutil.copytree(os.path.join(ROOT, "data", "symbols"), paths.symbolsDir(), dirs_exist_ok=True)
		ni._ensureDefaults()
		self.cm = ConfigManager()
		self.cm.defaults = copy.deepcopy(conf.defaults)
		self.cm.load()

	def tearDown(self) -> None:
		from tiresias.input import gestures

		gestures.userMap.reset()
		paths.setDataDir(self._oldData)
		paths.setConfigDir(self._oldConfig)
		shutil.rmtree(self.tmp, ignore_errors=True)

	def nvda(self, ini: str, files: dict[str, str] | None = None) -> str:
		"""Carpeta de NVDA sintética con ``nvda.ini`` y otros archivos."""
		folder = os.path.join(self.tmp, "nvda")
		_write(os.path.join(folder, "nvda.ini"), ini)
		for rel, text in (files or {}).items():
			_write(os.path.join(folder, rel), text)
		return folder

	def plan(self, folder: str, useDefaults: bool = True) -> ni.Plan:
		return ni.buildPlan(folder, useNvdaDefaults=useDefaults, configManager=self.cm)

	@staticmethod
	def values(plan: ni.Plan) -> dict:
		return {c.path: c.value for c in plan.changes}

	@staticmethod
	def notices(plan: ni.Plan) -> str:
		return "\n".join(n.text for n in plan.notices)


# ====================================================================== 1 y 2: comodines de los diccionarios
class WildcardDictTests(_Base):
	def test_anchor_removed_in_any_python(self) -> None:
		rx = ni._wildcardToRegex("x*z")
		self.assertFalse(rx.endswith("\\z") or rx.endswith("\\Z"), rx)
		# Sin ancla, la entrada actúa en medio del texto, como en NVDA.
		self.assertEqual(re.sub(rx, "Q", "axyzb"), "aQb")

	def test_parsed_entry_and_literal_replacement(self) -> None:
		path = os.path.join(self.tmp, "d.dic")
		_write(path, "x*z\ta\\1b\\n\t0\t6\n")
		entries, problems = ni.parseSpeechDict(path)
		self.assertEqual(problems, [])
		self.assertEqual(entries[0]["type"], "regex")
		self.assertFalse(entries[0]["pattern"].endswith(("\\z", "\\Z")))
		from tiresias.speech import dictionaries

		e = dictionaries.entryFromDict(entries[0])
		# El reemplazo es literal: las barras invertidas se dicen tal cual.
		self.assertEqual(e.apply("1 xyz 2"), "1 a\\1b\\n 2")

	def test_other_types_keep_replacement(self) -> None:
		path = os.path.join(self.tmp, "d.dic")
		_write(path, "(\\d)x\t\\1 por\t0\t1\n")
		entries, _p = ni.parseSpeechDict(path)
		self.assertEqual(entries[0]["replacement"], "\\1 por")


# ====================================================================== 3: estilo de voz matemático
class MathStyleTests(_Base):
	def test_style_of_configured_language(self) -> None:
		folder = self.nvda("[math]\n\t[[speech]]\n\t\tlanguage = es\n\t\t[[[es]]]\n\t\t\tspeechStyle = MathSpeak\n\t\t[[[en]]]\n\t\t\tspeechStyle = ClearSpeak\n")
		v = self.values(self.plan(folder))
		self.assertEqual(v[("math", "style")], "estructural")

	def test_default_language_is_english(self) -> None:
		folder = self.nvda("[math]\n\t[[speech]]\n\t\t[[[en]]]\n\t\t\tspeechStyle = MathSpeak\n")
		self.assertEqual(self.values(self.plan(folder))[("math", "style")], "estructural")
		folder = self.nvda("[math]\n\t[[speech]]\n\t\tlanguage = Auto\n\t\t[[[en]]]\n\t\t\tspeechStyle = SimpleSpeak\n")
		self.assertEqual(self.values(self.plan(folder))[("math", "style")], "natural")

	def test_unknown_style_is_noted(self) -> None:
		folder = self.nvda("[math]\n\t[[speech]]\n\t\tlanguage = en\n\t\t[[[en]]]\n\t\t\tspeechStyle = Nemeth\n")
		p = self.plan(folder)
		self.assertNotIn(("math", "style"), self.values(p))
		self.assertIn("Nemeth", self.notices(p))

	def test_profile_uses_base_language(self) -> None:
		folder = self.nvda(
			"[math]\n\t[[speech]]\n\t\tlanguage = es\n",
			{"profiles/Mates.ini": "[math]\n\t[[speech]]\n\t\t[[[es]]]\n\t\t\tspeechStyle = MathSpeak\n"},
		)
		prof = next(p for p in self.plan(folder).profiles if p.name == "Mates")
		self.assertEqual({c.path: c.value for c in prof.changes}[("math", "style")], "estructural")


# ====================================================================== 4: atributos de fuente en voz y braille
class FontAttributeTests(_Base):
	def check(self, mode: str, extra: str = "") -> dict:
		folder = self.nvda(f"[documentFormatting]\n\tfontAttributeReporting = {mode}\n{extra}")
		return self.values(self.plan(folder, useDefaults=False))

	def test_modes(self) -> None:
		# La opción existe en Tiresias y admite «off».
		self.assertIn("fontFormattingDisplay", self.cm.defaults["braille"])
		v = self.check("0")
		self.assertIs(v[("documentFormatting", "reportFontAttributes")], False)
		self.assertEqual(v[("braille", "fontFormattingDisplay")], "off")
		v = self.check("1")
		self.assertIs(v[("documentFormatting", "reportFontAttributes")], True)
		self.assertEqual(v[("braille", "fontFormattingDisplay")], "off")
		v = self.check("2")
		self.assertIs(v[("documentFormatting", "reportFontAttributes")], False)
		self.assertEqual(v[("braille", "fontFormattingDisplay")], "liblouis")
		v = self.check("3")
		self.assertIs(v[("documentFormatting", "reportFontAttributes")], True)
		self.assertEqual(v[("braille", "fontFormattingDisplay")], "liblouis")

	def test_other_row_wins(self) -> None:
		v = self.check("1", "[braille]\n\tfontFormattingDisplay = LIBLOUIS\n")
		self.assertEqual(v[("braille", "fontFormattingDisplay")], "liblouis")

	def test_nvda_default_turns_braille_off(self) -> None:
		folder = self.nvda("[speech]\n\tsynth = espeak\n")
		v = self.values(self.plan(folder))
		self.assertIs(v[("documentFormatting", "reportFontAttributes")], False)
		self.assertEqual(v[("braille", "fontFormattingDisplay")], "off")


# ====================================================================== 5: símbolos con nombre vacío
class SymbolFieldTests(_Base):
	def test_empty_name_is_silence_and_dash_inherits(self) -> None:
		self.assertEqual(ni._symbolField(["x", ""], 1), "")
		self.assertIsNone(ni._symbolField(["x", "-"], 1))
		self.assertIsNone(ni._symbolField(["x"], 1))
		path = os.path.join(self.tmp, "symbols-es.dic")
		_write(path, "symbols:\n€\t\tsome\n.\t-\tmost\n¶\tcalderón\tchar\n")
		symbols, problems, _c = ni.parseSymbolsFile(path)
		self.assertEqual(problems, [])
		bySym = {s["symbol"]: s for s in symbols}
		self.assertEqual(bySym["€"]["name"], "")
		self.assertIsNone(bySym["."]["name"])

	def test_plan_keeps_empty_name(self) -> None:
		folder = self.nvda("[speech]\n", {"symbols-es.dic": "symbols:\n€\t\tsome\tnever\n¶\tcalderón\tchar\n"})
		p = self.plan(folder)
		bySym = {s["symbol"]: s for s in p.symbols[0].symbols}
		self.assertEqual(bySym["€"]["name"], "")
		self.assertEqual(bySym["€"]["level"], 100)
		self.assertEqual(bySym["¶"]["level"], 1000)


# ====================================================================== 6: órdenes con el mismo nombre
class ScriptNameTests(_Base):
	def test_same_name_first(self) -> None:
		exists = {"nextSynthSetting", "previousSynthSetting"}.__contains__
		self.assertEqual(ni.tiresiasScriptName("nextSynthSetting", exists), "nextSynthSetting")
		self.assertEqual(ni.tiresiasScriptName("previousSynthSetting", exists), "previousSynthSetting")
		self.assertEqual(ni.tiresiasScriptName("nextHeading", exists), "quickNavNextHeading")
		self.assertEqual(ni.tiresiasScriptName("nextSynthSetting"), "quickNavNextSynthSetting")

	def test_plan_binds_existing_script(self) -> None:
		folder = self.nvda("[speech]\n", {"gestures.ini": "[globalCommands.GlobalCommands]\n\tnextSynthSetting = kb:nvda+control+shift+rightArrow\n"})
		p = self.plan(folder)
		scripts = {g.script for g in p.gestures}
		self.assertIn("nextSynthSetting", scripts)
		self.assertNotIn("quickNavNextSynthSetting", self.notices(p))


# ====================================================================== 7, 11 y 15: recarga en el núcleo
class _FakeSynth:
	name = "ibmtts"

	def __init__(self) -> None:
		self.loaded: list[dict] = []

	def loadSettings(self, settings: dict) -> None:
		self.loaded.append(dict(settings))


class ReloadTests(_Base):
	def setUp(self) -> None:
		super().setUp()
		self.cm.base = {"speech": {"synth": "ibmtts", "synths": {"ibmtts": {"rate": 55}, "espeak": {"rate": 30}}}}
		self.cm.createProfile("Como NVDA")
		self.cm.save()
		self.saved = copy.deepcopy(self.cm.base["speech"]["synths"])

	def run_reload(self, announce=None, then=None, activate=None, speak=None) -> _FakeSynth:
		from tiresias import core, speech, synth
		from tiresias.input import gestures
		from tiresias.speech import dictionaries, symbols

		fake = _FakeSynth()

		def applyConfiguration() -> None:
			# El sintetizador anterior y el mismo controlador recargado guardan lo que tenían en memoria.
			self.cm["speech"]["synths"]["espeak"] = {"rate": 99}
			self.cm["speech"]["synths"]["ibmtts"] = {"rate": 10}

		with contextlib.ExitStack() as st:
			st.enter_context(mock.patch("tiresias.config.conf", self.cm))
			st.enter_context(mock.patch.object(core, "applyConfiguration", applyConfiguration))
			st.enter_context(mock.patch.object(synth, "getSynth", lambda: fake))
			st.enter_context(mock.patch.object(gestures.userMap, "load", lambda: None))
			st.enter_context(mock.patch.object(dictionaries, "loadDefault", lambda: None))
			st.enter_context(mock.patch.object(symbols, "reloadAll", lambda: None))
			st.enter_context(mock.patch.object(speech, "speakMessage", speak or (lambda text: None)))
			ni._reloadOnCore(announce, then, activate)
		return fake

	def test_imported_synth_settings_survive(self) -> None:
		fake = self.run_reload()
		self.assertEqual(self.cm.base["speech"]["synths"], self.saved)
		self.assertEqual(fake.loaded[-1]["rate"], 55)

	def test_missing_synths_section_is_removed_again(self) -> None:
		self.cm.base = {"speech": {"synth": "ibmtts"}}
		self.cm.save()
		self.run_reload()
		self.assertNotIn("synths", self.cm.base.get("speech", {}))

	def test_new_profile_is_activated(self) -> None:
		self.run_reload(activate="Como NVDA")
		self.assertEqual(self.cm.manualProfile, "Como NVDA")

	def test_then_always_called(self) -> None:
		calls: list[int] = []

		def boom(text: str) -> None:
			raise RuntimeError("sin voz")

		self.run_reload(announce="hola", then=lambda: calls.append(1), speak=boom)
		self.assertEqual(calls, [1])


class FirstRunTests(unittest.TestCase):
	def run_first(self, answer: int | None, buildPlan=None) -> list[int]:
		import wx

		from tiresias.gui import nvda_import_dialog as dlgModule

		calls: list[int] = []

		class FakeDialog:
			def __init__(self, *args, **kwargs) -> None:
				if answer is None:
					raise RuntimeError("sin ventana")

			def ShowModal(self) -> int:
				return answer

			def Destroy(self) -> None:
				pass

		with contextlib.ExitStack() as st:
			st.enter_context(mock.patch.object(dlgModule.message_dialog, "MessageDialog", FakeDialog))
			st.enter_context(mock.patch.object(dlgModule, "parentWindow", lambda: None))
			st.enter_context(mock.patch.object(dlgModule, "showError", lambda *a, **k: None))
			st.enter_context(mock.patch.object(wx, "BusyCursor", contextlib.nullcontext))
			st.enter_context(mock.patch.object(dlgModule.nvda_import, "canUndo", lambda: False))
			if buildPlan is not None:
				st.enter_context(mock.patch.object(dlgModule.nvda_import, "buildPlan", buildPlan))
			dlgModule.askOnFirstRun("carpeta", then=lambda: calls.append(1))
		return calls

	def test_finish_on_no(self) -> None:
		import wx

		self.assertEqual(self.run_first(wx.ID_NO), [1])

	def test_finish_on_unexpected_error(self) -> None:
		import wx

		def boom(folder):
			raise RuntimeError("inesperado")

		self.assertEqual(self.run_first(wx.ID_YES, boom), [1])

	def test_finish_if_dialog_fails(self) -> None:
		self.assertEqual(self.run_first(None), [1])


# ====================================================================== 8: manifiesto antes de tocar nada
class PartialImportUndoTests(_Base):
	def test_failed_import_can_be_undone(self) -> None:
		folder = self.nvda(
			"[speech]\n\tsymbolLevel = 200\n",
			{
				"profiles/Bloc de notas.ini": "[keyboard]\n\tspeakTypedCharacters = 2\n",
				"symbols-es.dic": "symbols:\n€\teuro\tsome\tnever\n",
			},
		)
		self.cm.base = {"speech": {"symbolLevel": 300}}
		self.cm.save()
		before = _read(self.cm.configFile)
		plan = self.plan(folder)
		with mock.patch.object(ni, "_mergeSymbols", side_effect=RuntimeError("fallo a medias")):
			with self.assertRaises(RuntimeError):
				ni.applyPlan(plan, None, None, self.cm)
		self.assertTrue(os.path.isfile(os.path.join(paths.profilesDir(), "Bloc de notas.json")))
		folderBackup = ni.lastBackup()
		self.assertIsNotNone(folderBackup)
		manifest = ni._readManifest(folderBackup)
		self.assertFalse(manifest["completa"])
		self.assertIn("config/config.json", manifest["escritos"])
		ni.undoLastImport(self.cm)
		self.assertEqual(_read(self.cm.configFile), before)
		self.assertFalse(os.path.isfile(os.path.join(paths.profilesDir(), "Bloc de notas.json")))


# ====================================================================== 9 y 23: perfiles existentes
class ExistingProfileTests(_Base):
	def folder(self) -> str:
		return self.nvda(
			"[speech]\n",
			{
				"profiles/Bloc de notas.ini": "[keyboard]\n\tspeakTypedCharacters = 2\n",
				"profiles/Lectura.ini": "[braille]\n\ttetherTo = review\n",
				"profileTriggers.ini": "[triggersToProfiles]\n\tapp:notepad = Bloc de notas\n\tsayAll = Lectura\n",
			},
		)

	def test_read_only_profile_untouched(self) -> None:
		self.cm.createProfile("Bloc de notas")
		self.cm.setProfileReadOnly("Bloc de notas", True)
		fileBefore = _read(self.cm.profiles["Bloc de notas"].fileName)
		p = self.plan(self.folder())
		self.assertIn("solo lectura", self.notices(p))
		result = ni.applyPlan(p, {ni.CAT_PROFILES}, None, self.cm)
		self.assertEqual(self.cm.profiles["Bloc de notas"].data, {})
		self.assertEqual(_read(self.cm.profiles["Bloc de notas"].fileName), fileBefore)
		self.assertNotIn("app:notepad", self.cm.triggers)
		self.assertTrue(any("solo lectura" in s for s in result.skipped))
		self.assertEqual(result.profiles, 1)

	def test_case_insensitive_profile_is_the_same(self) -> None:
		self.cm.createProfile("lectura")
		p = self.plan(self.folder())
		names = {x.name for x in p.profiles}
		self.assertIn("lectura", names)
		self.assertNotIn("Lectura", names)
		ni.applyPlan(p, {ni.CAT_PROFILES}, None, self.cm)
		self.assertNotIn("Lectura", self.cm.profiles)
		self.assertEqual(self.cm.triggers["sayAll"], "lectura")
		self.assertEqual(self.cm.profiles["lectura"].data["braille"]["tetherTo"], "review")
		files = [f for f in os.listdir(paths.profilesDir()) if f.lower() == "lectura.json"]
		self.assertEqual(files, ["lectura.json"])

	def test_target_profile_case_insensitive(self) -> None:
		self.cm.createProfile("Como NVDA")
		p = self.plan(self.folder())
		with self.assertRaises(ni.ImportError_):
			ni.applyPlan(p, {ni.CAT_SPEECH}, "como nvda", self.cm)
		self.assertEqual(ni.findProfileName(self.cm, "COMO nvda"), "Como NVDA")
		self.assertIsNone(ni.findProfileName(self.cm, "Otro"))


# ====================================================================== 10: valores por defecto de NVDA
class NvdaDefaultsTests(_Base):
	def test_defaults_that_differ_from_tiresias(self) -> None:
		v = self.values(self.plan(self.nvda("[speech]\n\tsynth = espeak\n")))
		self.assertIs(v[("speech", "unicodeNormalization")], True)
		self.assertEqual(v[("speech", "sayAllUnit")], "sentence")
		self.assertIs(v[("presentation", "reportMultiSelect")], False)
		self.assertIs(v[("browseMode", "nativeSelectionMode")], False)
		self.assertEqual(v[("magnifier", "trackingMode")], "center")

	def test_default_flag_written(self) -> None:
		folder = self.nvda(
			"[speech]\n\tunicodeNormalization = DEFAULT\n\tsayAllReadingUnit = PARAGRAPH\n[virtualBuffers]\n\tnativeSelectionMode = DEFAULT\n",
			{"profiles/P.ini": "[speech]\n\tsayAllReadingUnit = DEFAULT\n"},
		)
		v = self.values(self.plan(folder))
		self.assertIs(v[("speech", "unicodeNormalization")], True)
		self.assertIs(v[("browseMode", "nativeSelectionMode")], False)
		self.assertEqual(v[("speech", "sayAllUnit")], "paragraph")
		# Sin los valores por defecto, «DEFAULT» en la configuración normal no se importa...
		plain = self.plan(folder, useDefaults=False)
		self.assertNotIn(("speech", "unicodeNormalization"), self.values(plain))
		# ...pero en un perfil sí: tapa el valor de la configuración normal.
		prof = next(p for p in plain.profiles if p.name == "P")
		self.assertEqual({c.path: c.value for c in prof.changes}[("speech", "sayAllUnit")], "sentence")


# ====================================================================== 13: voces de eSpeak
class EspeakVoiceTests(_Base):
	def test_lowercase_identifier(self) -> None:
		self.assertEqual(ni._espeakVoice("roa/pt-BR"), "pt-br")
		self.assertEqual(ni._espeakVoice("gmw/en-US"), "en-us")
		folder = self.nvda("[speech]\n\tsynth = espeak\n\t[[espeak]]\n\t\tvoice = roa/pt-BR\n")
		self.assertEqual(self.values(self.plan(folder))[("speech", "synths", "espeak", "voice")], "pt-br")


# ====================================================================== 16: archivos de Tiresias estropeados
class BrokenFilesTests(_Base):
	def test_invalid_dictionary_and_symbols_not_overwritten(self) -> None:
		folder = self.nvda(
			"[speech]\n",
			{"speechDicts/default.dic": "hola\tadiós\t0\t0\n", "symbols-es.dic": "symbols:\n€\teuro\tsome\tnever\n"},
		)
		dictFile = os.path.join(paths.speechDictsDir(), "default.json")
		symFile = os.path.join(paths.configDir(), "symbols_user.json")
		_write(dictFile, "{mal")
		_write(symFile, "[1, 2]")
		result = ni.applyPlan(self.plan(folder), {ni.CAT_DICTS, ni.CAT_SYMBOLS}, None, self.cm)
		self.assertEqual(_read(dictFile), "{mal")
		self.assertEqual(_read(symFile), "[1, 2]")
		self.assertEqual(result.dictEntries, 0)
		self.assertEqual(result.symbols, 0)
		self.assertEqual(len(result.skipped), 2)
		self.assertIn("no se ha tocado", _read(result.report))


# ====================================================================== 17: tono del modo pitidos
class BeepPitchTests(_Base):
	def test_clamped_to_panel_range(self) -> None:
		for written, expected in (("10000", 5000), ("8000", 5000), ("300", 300), ("20", 50)):
			folder = self.nvda(f"[speech]\n\tbeepSpeechModePitch = {written}\n")
			self.assertEqual(self.values(self.plan(folder, useDefaults=False))[("speech", "beepSpeechModePitch")], expected, written)


# ====================================================================== 20: copias de seguridad
class BackupLimitTests(_Base):
	def test_only_last_five_kept(self) -> None:
		folders = [ni.makeBackup("origen") for _i in range(7)]
		kept = sorted(os.listdir(ni.backupRoot()))
		self.assertEqual(len(kept), ni.MAX_BACKUPS)
		for f in folders[-ni.MAX_BACKUPS :]:
			self.assertTrue(os.path.isdir(f), f)
		for f in folders[: -ni.MAX_BACKUPS]:
			self.assertFalse(os.path.isdir(f), f)

	def test_order_with_same_second(self) -> None:
		with mock.patch.object(ni.os, "listdir", lambda root: ["20261007-120000", "20261007-120000-10", "20261007-120000-2", "20261006-235959"]):
			with mock.patch.object(ni.os.path, "isdir", lambda p: True):
				self.assertEqual(ni._backupNames(), ["20261007-120000-10", "20261007-120000-2", "20261007-120000", "20261006-235959"])


# ====================================================================== 22: gestos braille con modelo
class BrailleGestureTests(unittest.TestCase):
	def test_model_removed(self) -> None:
		withModel, reason = ni.translateGesture("br(freedomScientific.focus40):routing")
		self.assertIsNone(reason)
		self.assertEqual(withModel, ni.translateGesture("br(freedomScientific):routing")[0])
		self.assertTrue(withModel.lower().startswith("br(freedomscientific):"), withModel)


# ====================================================================== 12: código muerto (nivel «char»)
class SymbolLevelTests(_Base):
	def test_char_level_new_symbol(self) -> None:
		folder = self.nvda("[speech]\n", {"symbols-es.dic": "symbols:\nŧ\tte barrada\tchar\n"})
		sym = self.plan(folder).symbols[0].symbols[0]
		self.assertEqual((sym["symbol"], sym["level"], sym["preserve"]), ("ŧ", 1000, "never"))


if __name__ == "__main__":
	unittest.main()
