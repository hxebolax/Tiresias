"""Revisión de las opciones de configuración (octubre de 2026).

- Al salir de un perfil que eligió otro sintetizador, vuelve la elección
  automática si la configuración normal está en «auto» (core.applyConfiguration).
- Opciones globales (``config.isBaseOnly``): se leen y se guardan siempre en la
  configuración normal, aunque haya un perfil activo o en edición.
- Opciones de diccionario entero (``config.ATOMIC_KEYS``): vale el de la capa más
  alta; ``speech.synths`` sigue combinándose ajuste a ajuste.
- La migración de ``braille.wordWrap`` está en config/migrations.py y arregla
  también los perfiles.
- Los valores de la política de las secciones de los módulos se validan al registrarse.
- ``CHOICES`` y ``RANGES`` coinciden con las listas y los cuadros numéricos del
  cuadro de Opciones; los elementos de las listas también se validan.
- El nivel del registro y la API de control se vuelven a aplicar al restablecer.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -p test_rev1011_opciones.py``
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_rev1011_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()

from tiresias import config as configModule  # noqa: E402
from tiresias.config import ConfigManager, migrations, validation  # noqa: E402
from tiresias.config.policy import Policy  # noqa: E402


def _setPolicy(test: unittest.TestCase, cm: ConfigManager, pol: Policy) -> None:
	"""``setPolicy`` cambia también la política global: se restaura al terminar."""
	from tiresias.config import policy as policyModule

	test.addCleanup(setattr, policyModule, "policy", policyModule.policy)
	cm.setPolicy(pol)


def _manager() -> ConfigManager:
	"""Configuración en memoria (no escribe en el disco)."""
	cm = ConfigManager()
	cm.readOnly = True
	cm.registerDefaults("braille", {"roleAbbreviations": {}})
	cm.registerDefaults("presentation", {"roleTemplates": {}})
	return cm


# ====================================================================== opciones globales
class BaseOnlyTests(unittest.TestCase):
	def setUp(self) -> None:
		self.cm = _manager()
		self.cm.createProfile("Trabajo")
		self.cm.setManualProfile("Trabajo")

	def test_classification(self) -> None:
		isBaseOnly = configModule.isBaseOnly
		for path in (("general", "language"), ("general", "saveConfigurationOnExit"), ("general", "lastRunVersion"), ("update", "autoCheck"), ("addons", "catalogUrl"), ("coexist", "readers"), ("controller", "enabled"), ("speechViewer", "position"), ("brailleViewer", "x")):
			self.assertTrue(isBaseOnly(path), path)
		for path in (("general", "preventDisplayTurningOff"), ("speech", "rate"), ("speech", "synth"), ("braille", "display"), ("general",)):
			self.assertFalse(isBaseOnly(path), path)

	def test_write_goes_to_base_with_a_profile(self) -> None:
		self.cm["general"]["language"] = "en"
		self.assertEqual(self.cm.base["general"]["language"], "en")
		self.assertNotIn("general", self.cm.profiles["Trabajo"].data)
		self.assertTrue(self.cm.baseDirty)
		# Sigue igual al desactivar el perfil (el caso del reinicio tras cambiar el idioma).
		self.cm.setManualProfile(None)
		self.assertEqual(self.cm["general"]["language"], "en")

	def test_write_goes_to_base_while_editing_a_profile(self) -> None:
		self.cm.setManualProfile(None)
		self.cm.editProfile = "Trabajo"
		self.cm["general"]["saveConfigurationOnExit"] = False
		self.cm["update"]["autoCheck"] = False
		self.assertIs(self.cm.base["general"]["saveConfigurationOnExit"], False)
		self.assertIs(self.cm.base["update"]["autoCheck"], False)
		self.assertEqual(self.cm.profiles["Trabajo"].data, {})

	def test_old_profile_values_are_ignored_and_removed(self) -> None:
		data = self.cm.profiles["Trabajo"].data
		data["general"] = {"language": "en", "preventDisplayTurningOff": False}
		data["speechViewer"] = {"position": [1, 2, 3, 4]}
		self.assertEqual(self.cm["general"]["language"], "auto")
		self.assertEqual(self.cm["speechViewer"]["position"], [])
		# El que sí puede ir en un perfil se respeta.
		self.assertIs(self.cm["general"]["preventDisplayTurningOff"], False)
		self.assertEqual(self.cm["general"].dict()["language"], "auto")
		self.assertIs(self.cm["general"].dict()["preventDisplayTurningOff"], False)
		self.cm["general"]["language"] = "es"
		self.assertNotIn("language", data["general"])
		self.assertTrue(self.cm.profiles["Trabajo"].dirty)

	def test_profile_allowed_key_still_goes_to_profile(self) -> None:
		self.cm["general"]["preventDisplayTurningOff"] = False
		self.assertIs(self.cm.profiles["Trabajo"].data["general"]["preventDisplayTurningOff"], False)
		self.cm.setManualProfile(None)
		self.assertIs(self.cm["general"]["preventDisplayTurningOff"], True)

	def test_triggered_profile_does_not_get_last_run_version(self) -> None:
		"""Al arrancar puede haber un perfil de aplicación activo (startup._checkNews)."""
		self.cm.setManualProfile(None)
		self.cm.createProfile("Explorador")
		self.cm.setTrigger("app:explorer", "Explorador")
		self.cm.enterTrigger("app:explorer")
		self.assertEqual(self.cm.activeProfileName, "Explorador")
		self.cm["general"]["lastRunVersion"] = "9.9"
		self.assertEqual(self.cm.base["general"]["lastRunVersion"], "9.9")
		self.assertEqual(self.cm.profiles["Explorador"].data, {})
		self.cm.exitTrigger("app:explorer")
		self.assertEqual(self.cm["general"]["lastRunVersion"], "9.9")

	def test_delete_base_only(self) -> None:
		self.cm.base["general"] = {"language": "en"}
		del self.cm["general"]["language"]
		self.assertNotIn("language", self.cm.base["general"])

	def test_profile_values_still_override(self) -> None:
		self.cm["speech"]["symbolLevel"] = 300
		self.assertEqual(self.cm.profiles["Trabajo"].data["speech"]["symbolLevel"], 300)
		self.cm.setManualProfile(None)
		self.assertEqual(self.cm["speech"]["symbolLevel"], 100)

	def test_policy_still_wins(self) -> None:
		_setPolicy(self, self.cm, Policy({"lockedSettings": {"general.language": "es"}}))
		self.cm["general"]["language"] = "en"
		self.assertEqual(self.cm["general"]["language"], "es")
		self.assertNotIn("general", self.cm.base)


# ====================================================================== diccionarios
class AtomicDictTests(unittest.TestCase):
	def setUp(self) -> None:
		self.cm = _manager()
		self.cm.base["braille"] = {"roleAbbreviations": {"button": "btn", "link": "lnk"}}
		self.cm.base["presentation"] = {"roleTemplates": {"button": "{name} {role}"}}
		self.cm.createProfile("P")
		self.cm.setManualProfile("P")

	def test_profile_replaces_the_whole_dict(self) -> None:
		self.cm["braille"]["roleAbbreviations"] = {"button": "bt"}
		self.assertEqual(self.cm["braille"]["roleAbbreviations"].dict(), {"button": "bt"})
		self.assertNotIn("link", self.cm["braille"]["roleAbbreviations"])
		with self.assertRaises(KeyError):
			self.cm["braille"]["roleAbbreviations"]["link"]
		self.cm.setManualProfile(None)
		self.assertEqual(self.cm["braille"]["roleAbbreviations"].dict(), {"button": "btn", "link": "lnk"})

	def test_factory_values_in_a_profile_clear_the_base_entries(self) -> None:
		self.cm["presentation"]["roleTemplates"] = {}
		self.assertEqual(self.cm["presentation"]["roleTemplates"].dict(), {})
		self.assertEqual(len(self.cm["presentation"]["roleTemplates"]), 0)
		self.assertEqual(self.cm.base["presentation"]["roleTemplates"], {"button": "{name} {role}"})

	def test_changing_one_entry_copies_the_current_dict(self) -> None:
		self.cm["braille"]["roleAbbreviations"]["button"] = "bt"
		self.assertEqual(self.cm.profiles["P"].data["braille"]["roleAbbreviations"], {"button": "bt", "link": "lnk"})
		del self.cm["braille"]["roleAbbreviations"]["link"]
		self.assertEqual(self.cm["braille"]["roleAbbreviations"].dict(), {"button": "bt"})
		self.assertEqual(self.cm.base["braille"]["roleAbbreviations"], {"button": "btn", "link": "lnk"})

	def test_without_profile_value_the_base_is_used(self) -> None:
		self.assertEqual(self.cm["braille"]["roleAbbreviations"]["link"], "lnk")
		self.assertEqual(self.cm["braille"].dict()["roleAbbreviations"], {"button": "btn", "link": "lnk"})

	def test_policy_dict_wins(self) -> None:
		_setPolicy(self, self.cm, Policy({"lockedSettings": {"braille.roleAbbreviations": {"heading": "h"}}}))
		self.assertEqual(self.cm["braille"]["roleAbbreviations"].dict(), {"heading": "h"})

	def test_synths_are_merged_setting_by_setting(self) -> None:
		"""Un perfil guarda solo los ajustes de voz que cambia; el resto viene de la configuración normal."""
		self.cm.base["speech"] = {"synths": {"espeak": {"rate": 30, "voice": "es"}, "ibmtts": {"rate": 50}}}
		self.cm["speech"]["synths"]["espeak"]["rate"] = 70
		self.assertEqual(self.cm.profiles["P"].data["speech"], {"synths": {"espeak": {"rate": 70}}})
		self.assertEqual(self.cm["speech"]["synths"]["espeak"].dict(), {"rate": 70, "voice": "es"})
		self.assertEqual(self.cm["speech"]["synths"]["ibmtts"]["rate"], 50)
		self.assertEqual(self.cm["speech"]["synths"].dict(), {"espeak": {"rate": 70, "voice": "es"}, "ibmtts": {"rate": 50}})

	def test_ports_are_merged(self) -> None:
		self.cm.base["brailleDisplays"] = {"ports": {"hims": "COM3"}}
		self.cm["brailleDisplays"]["ports"]["freedomScientific"] = "usb"
		self.assertEqual(self.cm["brailleDisplays"]["ports"].dict(), {"hims": "COM3", "freedomScientific": "usb"})


# ====================================================================== sintetizador
class _FakeSynth:
	def __init__(self, name: str) -> None:
		self.name = name
		self.loaded: list = []

	def loadSettings(self, values: dict) -> None:
		self.loaded.append(values)


class SynthOnProfileSwitchTests(unittest.TestCase):
	def setUp(self) -> None:
		from tiresias import braille, controller, core, startup, synth
		from tiresias.audio import ducking, sound_split

		self.core = core
		self.cm = _manager()
		self.current = _FakeSynth("ibmtts")
		self.calls: list[str] = []

		def setSynth(name: str, isFallback: bool = False) -> bool:
			self.calls.append(name)
			if name == "auto":
				name = "ibmtts"
			self.current = _FakeSynth(name)
			return True

		display = types.SimpleNamespace(name="noBraille", configName="noBraille")
		handler = types.SimpleNamespace(display=display, setDisplay=mock.Mock(), applyConfig=mock.Mock())
		patches = [
			mock.patch.object(core, "conf", self.cm),
			mock.patch.object(synth, "getSynth", lambda: self.current),
			mock.patch.object(synth, "setSynth", setSynth),
			mock.patch.object(synth, "getSynthList", lambda: [("ibmtts", "Eloquence"), ("espeak", "eSpeak NG"), ("sapi5", "SAPI 5")]),
			mock.patch.object(synth, "getDriverNames", lambda: ["ibmtts", "espeak", "sapi5", "silence"]),
			mock.patch.object(braille, "handler", handler),
			mock.patch.object(sound_split, "apply"),
			mock.patch.object(ducking, "apply"),
			mock.patch.object(core, "_applyVisionConfiguration"),
			mock.patch.object(startup, "applyConfiguration"),
			mock.patch.object(controller, "applyConfiguration"),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)
		if hasattr(core.applyConfiguration, "lastWantedSynth"):
			del core.applyConfiguration.lastWantedSynth
		self.cm.createProfile("Navegador")
		self.cm.profiles["Navegador"].data = {"speech": {"synth": "espeak"}}

	def test_back_to_auto_after_leaving_profile(self) -> None:
		self.core.applyConfiguration()
		self.assertEqual(self.calls, [])
		self.cm.setManualProfile("Navegador")
		self.core.applyConfiguration(True)
		self.assertEqual(self.calls, ["espeak"])
		self.cm.setManualProfile(None)
		self.core.applyConfiguration(True)
		self.assertEqual(self.calls, ["espeak", "auto"])
		self.assertEqual(self.current.name, "ibmtts")

	def test_auto_does_not_reload_the_same_synth(self) -> None:
		self.core.applyConfiguration()
		self.core.applyConfiguration(True)
		self.assertEqual(self.calls, [])
		self.assertTrue(self.current.loaded is not None)

	def test_explicit_base_synth_is_kept(self) -> None:
		self.cm.base["speech"] = {"synth": "sapi5"}
		self.current = _FakeSynth("sapi5")
		self.core.applyConfiguration()
		self.cm.setManualProfile("Navegador")
		self.core.applyConfiguration(True)
		self.cm.setManualProfile(None)
		self.core.applyConfiguration(True)
		self.assertEqual(self.calls, ["espeak", "sapi5"])

	def test_auto_already_on_best_available(self) -> None:
		"""Si el elegido por el perfil es el mejor disponible, no se recarga."""
		self.cm.profiles["Navegador"].data = {"speech": {"synth": "ibmtts"}}
		self.core.applyConfiguration()
		self.cm.setManualProfile("Navegador")
		self.core.applyConfiguration(True)
		self.cm.setManualProfile(None)
		self.core.applyConfiguration(True)
		self.assertEqual(self.calls, [])

	def test_controller_and_log_level_are_reapplied_on_reset(self) -> None:
		from tiresias import controller, log as logModule

		self.cm.base["general"] = {"logLevel": "WARNING"}
		with mock.patch.object(logModule, "setLevel") as setLevel, mock.patch.object(self.core, "args", None):
			self.core.applyConfiguration()
			setLevel.assert_called_once_with("WARNING")
			self.assertTrue(controller.applyConfiguration.called)
			controller.applyConfiguration.reset_mock()
			self.core.applyConfiguration(True)
			# Al cambiar de perfil no: son opciones globales.
			self.assertFalse(controller.applyConfiguration.called)

	def test_command_line_log_level_wins(self) -> None:
		from tiresias import log as logModule

		self.cm.base["general"] = {"logLevel": "WARNING"}
		args = types.SimpleNamespace(log_level="DEBUG", debug=False)
		with mock.patch.object(logModule, "setLevel") as setLevel, mock.patch.object(self.core, "args", args):
			self.core.applyConfiguration()
		setLevel.assert_not_called()


# ====================================================================== migración
class WordWrapMigrationTests(unittest.TestCase):
	def test_fixup_in_any_file(self) -> None:
		data = {"schemaVersion": 3, "braille": {"wordWrap": False}}
		self.assertEqual(migrations.migrate(data), [])
		self.assertEqual(data, {"braille": {"textWrap": "none"}})
		data = {"schemaVersion": 3, "braille": {"wordWrap": False, "textWrap": "markWordCuts"}}
		migrations.migrate(data)
		self.assertEqual(data, {"braille": {"textWrap": "markWordCuts"}})
		data = {"schemaVersion": 3, "braille": {"wordWrap": True}}
		migrations.migrate(data)
		self.assertEqual(data, {})
		# Junto con las migraciones de versión (archivos antiguos).
		data = {"braille": {"wordWrap": False, "showCursor": False}}
		self.assertEqual(migrations.migrate(data), [1, 2])
		self.assertEqual(data["braille"], {"showCursor": False, "textWrap": "none"})

	def test_newer_files_are_left_alone(self) -> None:
		data = {"schemaVersion": 99, "braille": {"wordWrap": False}}
		migrations.migrate(data)
		self.assertEqual(data, {"braille": {"wordWrap": False}})

	def test_profiles_are_migrated_on_load(self) -> None:
		old = (paths.DATA_DIR, paths._configDirOverride)
		tmp = tempfile.mkdtemp(prefix="tiresias_rev1011_cfg_")
		self.addCleanup(shutil.rmtree, tmp, True)
		paths.setDataDir(tmp)
		paths.setConfigDir(None)
		self.addCleanup(lambda: (paths.setDataDir(old[0]), paths.setConfigDir(old[1])))
		paths.ensureDataDirs()
		os.makedirs(paths.profilesDir(), exist_ok=True)
		with open(os.path.join(paths.profilesDir(), "Lectura.json"), "w", encoding="utf-8") as f:
			json.dump({"schemaVersion": 3, "braille": {"wordWrap": False}}, f)
		cm = ConfigManager()
		cm.load()
		self.assertEqual(cm.profiles["Lectura"].data, {"braille": {"textWrap": "none"}})

	def test_braille_no_longer_migrates_at_runtime(self) -> None:
		import tiresias.braille as braille

		self.assertFalse(hasattr(braille, "_migrateConfig"))
		self.assertNotIn("wordWrap", inspect.getsource(braille.initialize))


# ====================================================================== política
class PolicyValidationTests(unittest.TestCase):
	def test_module_sections_are_validated_when_registered(self) -> None:
		cm = _manager()
		_setPolicy(self, cm, Policy({"lockedSettings": {"miModulo.valor": "nada", "miModulo.otro": "7", "miModulo.lista": [1, "a"]}}))
		cm.registerDefaults("miModulo", {"valor": 5, "otro": 1, "lista": ["x"]})
		self.assertEqual(cm["miModulo"]["valor"], 5)
		self.assertEqual(cm["miModulo"]["otro"], 7)
		self.assertEqual(cm["miModulo"]["lista"], ["a"])
		# Sigue bloqueada (con su valor por defecto), aunque el valor no fuera válido.
		self.assertTrue(cm.isLocked("miModulo", "valor"))
		cm["miModulo"]["valor"] = 3
		self.assertEqual(cm["miModulo"]["valor"], 5)


# ====================================================================== validación
def _registerEverything() -> None:
	for mod, fn in (
		("tiresias.speech.defaults", "register"),
		("tiresias.synth", None),
		("tiresias.audio", None),
		("tiresias.braille.presenter", None),
		("tiresias.a11y", None),
		("tiresias.clipboard", None),
		("tiresias.ocr", None),
		("tiresias.vision", None),
		("tiresias.magnifier", None),
		("tiresias.mouse_keys", None),
		("tiresias.appmodules", None),
		("tiresias.appmodules._gsuite", None),
		("tiresias.ai.assistant", None),
		("tiresias.mathpres", None),
		("tiresias.remote", "registerDefaults"),
		("tiresias.remote.rdp", "registerDefaults"),
		("tiresias.productivity", "registerDefaults"),
		("tiresias.controller", "registerDefaults"),
		("tiresias.coexist", "registerDefaults"),
	):
		m = importlib.import_module(mod)
		if fn:
			getattr(m, fn)()
	from tiresias.config import conf
	from tiresias.touch import handler as touchHandler

	conf.registerDefaults("touch", touchHandler.DEFAULTS)


def _panelFields() -> list:
	"""[(panel, sección, Field)] de todas las categorías del cuadro de Opciones (sin crear ventanas)."""
	from tiresias.gui import settings as S

	captured: list = []
	modules = [S]

	def capture(pid, title, cls) -> None:
		captured.append(cls)

	with mock.patch.object(S, "registerPanel", capture):
		for mod, fn in (
			("tiresias.gui.speech_settings", "registerPanels"),
			("tiresias.gui.audio_dialogs", None),
			("tiresias.gui.touch_panel", None),
			("tiresias.gui.apps_panel", None),
			("tiresias.gui.braille_panels", None),
			("tiresias.gui.config_panels", None),
			("tiresias.gui.rdp_panel", None),
			("tiresias.gui.ai_dialogs", None),
			("tiresias.gui.productivity_dialogs", "registerSettingsPanels"),
			("tiresias.gui.remote_dialogs", "registerSettingsPanel"),
			("tiresias.mathpres.settings_panel", "registerPanel"),
		):
			m = importlib.import_module(mod)
			modules.append(m)
			if fn:
				getattr(m, fn)()
	classes = list(captured)
	for m in modules:
		classes += [obj for obj in vars(m).values() if inspect.isclass(obj) and issubclass(obj, S.ConfigPanel) and obj is not S.ConfigPanel]

	class _Fake:
		def __init__(self, cls) -> None:
			object.__setattr__(self, "_cls", cls)

		def __getattr__(self, name):
			attr = inspect.getattr_static(self._cls, name)
			if isinstance(attr, staticmethod):
				return attr.__func__
			if isinstance(attr, classmethod):
				return attr.__func__.__get__(self._cls)
			if inspect.isfunction(attr):
				return attr.__get__(self)
			return getattr(self._cls, name)

	out = []
	seen = set()
	for cls in classes:
		if cls in seen or not issubclass(cls, S.ConfigPanel):
			continue
		seen.add(cls)
		for f in cls.getFields(_Fake(cls)):
			out.append((cls.__name__, f.section or cls.section, f))
	return out


class ValidationCoherenceTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		_registerEverything()
		cls.fields = _panelFields()
		from tiresias.config import conf

		cls.defaults = conf.defaults

	def test_fields_found(self) -> None:
		self.assertGreater(len(self.fields), 400)

	def test_numeric_fields_have_the_same_range(self) -> None:
		for panel, sec, f in self.fields:
			if f.kind in ("int", "slider"):
				with self.subTest(option=f"{sec}.{f.key}", panel=panel):
					self.assertEqual(validation.RANGES.get((sec, f.key)), (f.minVal, f.maxVal))

	def test_choice_fields_match_choices(self) -> None:
		for panel, sec, f in self.fields:
			if f.kind != "choice" or (sec, f.key) not in validation.CHOICES:
				continue
			values = [v for v, _l in (f.choices() if callable(f.choices) else f.choices)]
			with self.subTest(option=f"{sec}.{f.key}", panel=panel):
				self.assertEqual(sorted(values, key=str), sorted(validation.CHOICES[(sec, f.key)], key=str))

	def test_fixed_text_choices_are_validated(self) -> None:
		"""Toda lista desplegable de textos fijos (no de cosas del equipo) está en CHOICES."""
		dynamic = {
			("general", "language"),
			("audio", "outputDevice"),
			("audio", "soundTheme"),
			("braille", "translationTable"),
			("braille", "inputTable"),
			("ocr", "language"),
			("ocr", "tesseractLanguage"),
			("ai", "anthropicModel"),
			("ai", "translateTo"),
			("speech", "voiceScheme"),
		}
		for panel, sec, f in self.fields:
			if f.kind != "choice" or (sec, f.key) in dynamic or f.key.startswith("context"):
				continue
			values = [v for v, _l in (f.choices() if callable(f.choices) else f.choices)]
			if values and all(isinstance(v, str) for v in values):
				with self.subTest(option=f"{sec}.{f.key}", panel=panel):
					self.assertIn((sec, f.key), validation.CHOICES)

	def test_validation_entries_exist_and_defaults_are_valid(self) -> None:
		for key in list(validation.RANGES) + list(validation.CHOICES) + list(validation.LIST_CHOICES) + list(validation.LIST_TYPES):
			with self.subTest(option=key):
				self.assertIn(key[1], self.defaults.get(key[0], {}))
		for sec, values in self.defaults.items():
			for key, value in values.items():
				with self.subTest(option=f"{sec}.{key}"):
					self.assertTrue(validation.isValidValue(sec, key, value, self.defaults))

	def test_nvda_import_values_are_valid(self) -> None:
		from tiresias import nvda_import

		for row in nvda_import.ROWS:
			target, conv, nvdaDefault = row[3], row[4], row[5]
			sec, key = target.split(".", 1)
			cells = [c.cell_contents for c in (getattr(conv, "__closure__", None) or [])]
			samples = [v for m in cells if isinstance(m, dict) for v in m.values() if not isinstance(v, Exception)]
			if nvdaDefault is not None:
				samples.append(conv(nvdaDefault))
			for value in samples:
				with self.subTest(option=target, value=value):
					self.assertTrue(validation.isValidValue(sec, key, value, self.defaults))

	def test_list_items(self) -> None:
		data = {
			"speech": {"excludedSpeechModes": ["beeps", "inventado", 3], "synthPriority": ["espeak", 5]},
			"speechViewer": {"position": ["10", 20, 30.0, "x", True]},
			"presentation": {"propertyOrder": "role, name, nada"},
			"audio": {"includedSoundSplitModes": ["off", "leftRight", "arriba"]},
		}
		issues = validation.validate(data, self.defaults)
		self.assertEqual(data["speech"]["excludedSpeechModes"], ["beeps"])
		self.assertEqual(data["speech"]["synthPriority"], ["espeak"])
		self.assertEqual(data["speechViewer"]["position"], [10, 20, 30])
		self.assertEqual(data["presentation"]["propertyOrder"], ["role", "name"])
		self.assertEqual(data["audio"]["includedSoundSplitModes"], ["off", "leftRight"])
		self.assertEqual(len(issues), 5)

	def test_new_choices_and_ranges(self) -> None:
		data = {
			"braille": {"textWrap": "nada", "cursorShapeFocus": 999},
			"magnifier": {"view": "lupa", "dockSize": 5},
			"speech": {"contextMenuPitch": 500, "contextDialogSymbolLevel": -5},
			"ai": {"timeout": 0},
		}
		validation.validate(data, self.defaults)
		self.assertNotIn("textWrap", data["braille"])
		self.assertEqual(data["braille"]["cursorShapeFocus"], 255)
		self.assertNotIn("view", data["magnifier"])
		self.assertEqual(data["magnifier"]["dockSize"], 10)
		self.assertEqual(data["speech"], {"contextMenuPitch": 80, "contextDialogSymbolLevel": -1})
		self.assertEqual(data["ai"]["timeout"], 10)


# ====================================================================== manual
class ManualTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		path = os.path.join(ROOT, "manual", "manual_usuario.html")
		if not os.path.isfile(path):
			raise unittest.SkipTest("sin manual")
		with open(path, encoding="utf-8") as f:
			cls.text = f.read()

	def test_profiles_chapter_lists_global_options(self) -> None:
		start = self.text.index('<h2 id="perfiles">')
		end = self.text.index('<h2 id="opciones">')
		chapter = self.text[start:end]
		self.assertIn('id="perfiles-globales"', chapter)
		for words in ("idioma de la interfaz", "Guardar la configuración al salir", "Actualizaciones", "Impedir que la pantalla se apague"):
			self.assertIn(words, chapter)


if __name__ == "__main__":
	unittest.main()
