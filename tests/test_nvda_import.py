"""Pruebas del importador de la configuración de NVDA (``tiresias.nvda_import``).

Se crean varias configuraciones de NVDA de ejemplo (instalada, portable, con
perfiles, con gestos, con diccionarios y con símbolos) en carpetas temporales
y se comprueban la lectura, las equivalencias, la aplicación y el deshacer.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import nvda_import as ni, paths  # noqa: E402
from tiresias.config import ConfigManager, conf  # noqa: E402

# ---------------------------------------------------------------------- ejemplos
NVDA_INI_INSTALLED = """schemaVersion = 25
[general]
	language = es
	showWelcomeDialogAtStartup = False
	loggingLevel = DEBUGWARNING
[speech]
	synth = ibmeci
	autoLanguageSwitching = False
	autoDialectSwitching = True
	delayedCharacterDescriptions = True
	symbolLevel = 200
	speechDictionaries = voice, default
	excludedSpeechModes = 1, 3
	[[ibmeci]]
		voice = 131072
		variant = 2
		pitch = 65
		inflection = 35
		volume = 95
		rgh = 3
		bth = 4
		hsz = 52
		rate = 55
		rateBoost = True
		ABRDICT = True
		sampleRate = 0
		pauseMode = 1
		speechStyle = 7
		capPitchChange = 20
		sayCapForCapitals = True
	[[espeak]]
		voice = roa/es
		variant = max
		rate = 30
	[[RHVoice]]
		voice = Mateo
[audio]
	audioDuckingMode = 1
	soundSplitState = 3
	includedSoundSplitModes = 0, 2, 4
	audioAwakeTime = 60
[braille]
	display = freedomScientific
	translationTable = es-g1.ctb
	inputTable = Es-Es-G0.utb
	showMessages = 2
	autoScrollRate = 9.93
	textWrap = MARK_WORD_CUTS
	cursorShapeReview = 64
	[[freedomScientific]]
		port = usb
	[[auto]]
		excludedDisplays = lineaInventada, hidBrailleStandard
[keyboard]
	keyboardLayout = laptop
	NVDAModifierKeys = 5
	speakTypedCharacters = 0
	speakTypedWords = 1
	multiPressTimeout = 600
[presentation]
	reportTooltips = True
	[[progressBarUpdates]]
		progressBarOutputMode = both
		beepPercentageInterval = 5
[virtualBuffers]
	useScreenLayout = False
	maxLineLength = 120
[documentFormatting]
	reportSpellingErrors2 = 5
	reportTableHeaders = 2
	reportLineIndentation = 3
	fontAttributeReporting = 1
	reportBookmarks = False
[vision]
	[[NVDAHighlighter]]
		enabled = True
		highlightNavigator = False
[screenCurtain]
	enabled = False
	warnOnLoad = False
[UIA]
	eventRegistration = auto
	winConsoleImplementation = legacy
[terminals]
	diffAlgo = difflib
[magnifier]
	zoom = 300
	filter = inverted
	fullscreenMode = relative
[speechViewer]
	autoPositionWindow = False
	x = 10
	y = 20
	width = 300
	height = 200
	displays = "(1920, 1080)",
[miComplemento]
	clave = 1
	token = secreto
"""

PROFILE_INI = """[speech]
	[[ibmeci]]
		rate = 80
[keyboard]
	speakTypedCharacters = 2
"""

TRIGGERS_INI = """[triggersToProfiles]
	app:notepad = Bloc de notas
	sayAll = Lectura
	app:inexistente = Nadie
"""

READING_PROFILE_INI = """[braille]
	tetherTo = review
"""

GESTURES_INI = """[globalCommands.GlobalCommands]
	say_battery_status = kb:nvda+control+shift+b
	showGui = kb:nvda+n
	toggleInputHelp = kb:alt+tab
	dateTime = kb:NVDA+m
	None = kb:nvda+x
	inventada = kb:nvda+shift+j
[browseMode.BrowseModeTreeInterceptor]
	nextHeading = kb:shift+control+alt+h
[globalPlugins.miPlugin.GlobalPlugin]
	abrir = kb:nvda+control+o, kb:nvda+control+i
"""

DEFAULT_DIC = """# un comentario
NVDA	ene ve de a	0	2
\\bdr\\.	doctor	1	1
hola	adiós	0	0
x*z	equis zeta	0	6
([	mal	0	1
"""

VOICE_DIC = """Tiresias	Tiresias el adivino	1	2
"""

SYMBOLS_DIC = """complexSymbols:
# identificador	expresión
miComplejo	\\d+x
symbols:
€	euro	some	never
→	flecha	all	always	# flecha a la derecha
.	-	most	-
miComplejo	equis	all
sentence ending	fin	all
"""


def _read(path: str) -> str:
	with open(path, encoding="utf-8") as f:
		return f.read()


def _json(path: str) -> dict:
	return json.loads(_read(path))


def _write(path: str, text: str) -> None:
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "w", encoding="utf-8") as f:
		f.write(text)


def makeInstalled(base: str) -> str:
	folder = os.path.join(base, "nvda")
	_write(os.path.join(folder, "nvda.ini"), NVDA_INI_INSTALLED)
	return folder


def makeFull(base: str) -> str:
	"""Instalada con perfiles, gestos, diccionarios y símbolos."""
	folder = makeInstalled(base)
	_write(os.path.join(folder, "profiles", "Bloc de notas.ini"), PROFILE_INI)
	_write(os.path.join(folder, "profiles", "Lectura.ini"), READING_PROFILE_INI)
	_write(os.path.join(folder, "profileTriggers.ini"), TRIGGERS_INI)
	_write(os.path.join(folder, "gestures.ini"), GESTURES_INI)
	_write(os.path.join(folder, "speechDicts", "default.dic"), DEFAULT_DIC)
	_write(os.path.join(folder, "speechDicts", "temp.dic"), "a\tb\t0\t0\n")
	_write(os.path.join(folder, "speechDicts", "voiceDicts.v1", "ibmeci", "ibmeci-Castilian Spanish.dic"), VOICE_DIC)
	_write(os.path.join(folder, "speechDicts", "voiceDicts.v1", "RHVoice", "RHVoice-Mateo.dic"), VOICE_DIC)
	_write(os.path.join(folder, "symbols-es_ES.dic"), SYMBOLS_DIC)
	_write(os.path.join(folder, "symbols-xx.dic"), "symbols:\n€\teuro\n")
	return folder


def makePortable(base: str) -> str:
	"""NVDA portable: la configuración está en «userConfig» junto a nvda.exe."""
	folder = os.path.join(base, "NVDA portable")
	_write(os.path.join(folder, "nvda.exe"), "")
	_write(os.path.join(folder, "userConfig", "nvda.ini"), "[speech]\n\tsynth = espeak\n\t[[espeak]]\n\t\trate = 70\n")
	return folder


# ---------------------------------------------------------------------- base de las pruebas
class _Base(unittest.TestCase):
	def setUp(self) -> None:
		self._oldData = paths.DATA_DIR
		self._oldConfig = paths._configDirOverride
		self.tmp = tempfile.mkdtemp(prefix="tiresias_nvda_")
		self.data = os.path.join(self.tmp, "data")
		paths.setDataDir(self.data)
		paths.setConfigDir(None)
		paths.ensureDataDirs()
		# Tablas de símbolos de fábrica (para heredar los campos «-»).
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

	def plan(self, folder: str, useDefaults: bool = True) -> ni.Plan:
		return ni.buildPlan(folder, useNvdaDefaults=useDefaults, configManager=self.cm)

	@staticmethod
	def values(plan: ni.Plan) -> dict:
		return {c.path: c.value for c in plan.changes}

	@staticmethod
	def notices(plan: ni.Plan) -> str:
		return "\n".join(n.text for n in plan.notices)


# ====================================================================== lector de configobj
class IniParserTests(unittest.TestCase):
	def test_sections_values_and_lists(self) -> None:
		data = ni.parseIni(
			'top = 1\n[a]\n\tx = "hola, mundo"\n\ty = uno, dos\n\tz = solo,\n\tw = valor # comentario\n'
			"\t[[b]]\n\t\tk = '{\"1\":2}'\n\t\t[[[c]]]\n\t\t\tq = 3\n\t[[d]]\n\t\tm = 4\n[e]\n\tt = \"\"\"uno\ndos\"\"\"\n"
		)
		self.assertEqual(data["top"], "1")
		self.assertEqual(data["a"]["x"], "hola, mundo")
		self.assertEqual(data["a"]["y"], ["uno", "dos"])
		self.assertEqual(data["a"]["z"], ["solo"])
		self.assertEqual(data["a"]["w"], "valor")
		self.assertEqual(data["a"]["b"]["k"], '{"1":2}')
		self.assertEqual(data["a"]["b"]["c"]["q"], "3")
		self.assertEqual(data["a"]["d"]["m"], "4")
		self.assertEqual(data["e"]["t"], "uno\ndos")

	def test_real_style_values(self) -> None:
		data = ni.parseIni('[speech]\n\t[[oneCore]]\n\t\tvoice = HKEY_LOCAL_MACHINE\\SOFTWARE\\X\\Tokens\\Pablo\n[v]\n\tdisplays = "(1920, 1080)",\n')
		self.assertEqual(data["speech"]["oneCore"]["voice"], "HKEY_LOCAL_MACHINE\\SOFTWARE\\X\\Tokens\\Pablo")
		self.assertEqual(data["v"]["displays"], ["(1920, 1080)"])

	def test_real_user_ini_if_present(self) -> None:
		"""La configuración real de NVDA del equipo se lee sin errores (solo lectura)."""
		folder = ni.findNvdaConfig()
		if not folder:
			self.skipTest("NVDA no está instalado en este equipo")
		data = ni.readIni(os.path.join(folder, "nvda.ini"))
		self.assertIn("speech", data)


# ====================================================================== localizar la configuración
class LocateTests(_Base):
	def test_installed_and_portable(self) -> None:
		installed = makeInstalled(self.tmp)
		self.assertEqual(ni.resolveFolder(installed), installed)
		self.assertEqual(ni.resolveFolder(os.path.join(installed, "nvda.ini")), installed)
		portable = makePortable(self.tmp)
		self.assertEqual(ni.resolveFolder(portable), os.path.join(portable, "userConfig"))
		self.assertEqual(ni.resolveFolder(os.path.join(portable, "nvda.exe")), os.path.join(portable, "userConfig"))
		self.assertIsNone(ni.resolveFolder(os.path.join(self.tmp, "no existe")))

	def test_default_folder_uses_appdata(self) -> None:
		old = os.environ.get("APPDATA")
		os.environ["APPDATA"] = self.tmp
		try:
			makeInstalled(self.tmp)
			self.assertEqual(ni.findNvdaConfig(), os.path.join(self.tmp, "nvda"))
		finally:
			if old is None:
				del os.environ["APPDATA"]
			else:
				os.environ["APPDATA"] = old

	def test_portable_plan(self) -> None:
		folder = ni.resolveFolder(makePortable(self.tmp))
		plan = self.plan(folder)
		self.assertTrue(plan.isPortable)
		v = self.values(plan)
		self.assertEqual(v[("speech", "synth")], "espeak")
		self.assertEqual(v[("speech", "synths", "espeak", "rate")], 70)


# ====================================================================== equivalencias
class MappingTests(_Base):
	def setUp(self) -> None:
		super().setUp()
		self.folder = makeInstalled(self.tmp)
		self.p = self.plan(self.folder)
		self.v = self.values(self.p)
		self.n = self.notices(self.p)

	def test_eloquence(self) -> None:
		v = self.v
		self.assertEqual(v[("speech", "synth")], "ibmtts")
		eci = {k[3]: val for k, val in v.items() if k[:3] == ("speech", "synths", "ibmtts")}
		self.assertEqual(
			eci,
			{
				"voice": "131072",
				"variant": "2",
				"pitch": 65,
				"inflection": 35,
				"volume": 95,
				"roughness": 3,
				"breathiness": 4,
				"headSize": 52,
				"rate": 55,
				"rateBoost": True,
				"abbreviationDictionary": True,
				"sampleRate": "0",
				"pauseMode": "1",
			},
		)
		self.assertIn("speechStyle", self.n)
		# Mayúsculas del sintetizador activo.
		self.assertEqual(v[("speech", "capitalPitchChange")], 20)
		self.assertIs(v[("speech", "sayCapitalForCapitals")], True)
		self.assertIs(v[("speech", "beepForCapitals")], False)

	def test_eci_voice_formats(self) -> None:
		self.assertEqual(ni.eciVoice("131072"), "131072")
		self.assertEqual(ni.eciVoice("131073:2"), "131073")
		self.assertEqual(ni.eciVoice("esp"), str(0x20000))
		self.assertEqual(ni.eciVoice("es_ES"), str(0x20000))
		self.assertEqual(ni.eciVoice("es_MX"), str(0x20001))
		self.assertEqual(ni.eciVoiceFromDisplayName("Castilian Spanish"), str(0x20000))
		self.assertEqual(ni.eciVoiceFromDisplayName("Latin American Spanish"), str(0x20001))
		self.assertEqual(ni.eciVoiceFromDisplayName("American English"), str(0x10000))
		self.assertIsNone(ni.eciVoice("klingon"))

	def test_synth_names(self) -> None:
		for nvda, tir in (("ibmeci", "ibmtts"), ("ibmtts", "ibmtts"), ("eloquence", "ibmtts"), ("espeak", "espeak"), ("oneCore", "onecore"), ("sapi5", "sapi5"), ("sapi5_32", "sapi5_32"), ("sapi4_32", "sapi4"), ("sapi4", "sapi4"), ("auto", "auto")):
			self.assertEqual(ni.tiresiasSynthName(nvda), tir, nvda)
		self.assertIsNone(ni.tiresiasSynthName("RHVoice"))

	def test_other_synths(self) -> None:
		self.assertEqual(self.v[("speech", "synths", "espeak", "voice")], "es")
		self.assertEqual(self.v[("speech", "synths", "espeak", "variant")], "max")
		self.assertIn("RHVoice", self.n)

	def test_speech(self) -> None:
		v = self.v
		self.assertIs(v[("speech", "autoLanguageSwitching")], False)
		self.assertIs(v[("speech", "autoDialectSwitching")], True)
		self.assertIs(v[("speech", "delayedCharacterDescriptions")], True)
		self.assertEqual(v[("speech", "symbolLevel")], 200)
		self.assertEqual(v[("speech", "excludedSpeechModes")], ["beeps", "onDemand"])

	def test_keyboard(self) -> None:
		v = self.v
		self.assertEqual(v[("keyboard", "layout")], "laptop")
		# 5 = Bloq Mayús (1) + Insert extendida (4), sin Insert del teclado numérico.
		self.assertIs(v[("keyboard", "useCapsLockAsModifier")], True)
		self.assertIs(v[("keyboard", "useNumpadInsertAsModifier")], False)
		self.assertIs(v[("keyboard", "useInsertAsModifier")], True)
		self.assertEqual(v[("keyboard", "speakTypedCharacters")], "off")
		self.assertEqual(v[("keyboard", "speakTypedWords")], "editOnly")
		self.assertEqual(v[("keyboard", "multiPressTimeout")], 600)

	def test_braille(self) -> None:
		v = self.v
		self.assertEqual(v[("braille", "display")], "freedomScientific")
		self.assertEqual(v[("braille", "translationTable")], "es-g1.ctb")
		self.assertEqual(v[("braille", "inputTable")], "Es-Es-G0.utb")
		self.assertEqual(v[("braille", "showMessages")], "always")
		self.assertEqual(v[("braille", "autoScrollRate")], 10)
		self.assertEqual(v[("braille", "textWrap")], "markWordCuts")
		self.assertEqual(v[("braille", "cursorShapeReview")], 64)
		self.assertEqual(v[("brailleDisplays", "ports", "freedomScientific")], "usb")
		self.assertEqual(v[("brailleDisplays", "excludedFromAuto")], ["hidBraille"])
		# Bit 4 de los errores ortográficos: también en braille.
		self.assertIs(v[("braille", "showSpellingErrors")], True)

	def test_braille_tables_and_drivers(self) -> None:
		self.assertEqual(ni.tiresiasBrailleTable("auto"), "auto")
		self.assertEqual(ni.tiresiasBrailleTable("ES-G1.CTB"), "es-g1.ctb")
		self.assertIsNone(ni.tiresiasBrailleTable("noexiste.ctb"))
		self.assertEqual(ni.tiresiasBrailleDriver("hidBrailleStandard"), "hidBraille")
		self.assertEqual(ni.tiresiasBrailleDriver("virtualBraille"), "viewer")
		self.assertEqual(ni.tiresiasBrailleDriver("baum"), "baum")
		self.assertIsNone(ni.tiresiasBrailleDriver("lineaInventada"))

	def test_other_options(self) -> None:
		v = self.v
		self.assertEqual(v[("general", "language")], "es")
		self.assertEqual(v[("general", "logLevel")], "DEBUG")
		self.assertEqual(v[("audio", "duckingMode")], "speaking")
		self.assertEqual(v[("audio", "soundSplitMode")], "leftBoth")
		self.assertEqual(v[("audio", "includedSoundSplitModes")], ["off", "leftRight", "rightLeft"])
		self.assertEqual(v[("audio", "keepAudioAwakeSeconds")], 60)
		self.assertIs(v[("presentation", "reportTooltips")], True)
		self.assertEqual(v[("presentation", "progressBarOutputMode")], "both")
		self.assertEqual(v[("presentation", "progressBarBeepInterval")], 5)
		self.assertIs(v[("browseMode", "useScreenLayout")], False)
		self.assertEqual(v[("browseMode", "maxLineLength")], 120)
		self.assertIs(v[("documentFormatting", "reportSpellingErrors")], True)
		self.assertIs(v[("documentFormatting", "reportTableHeaders")], True)
		self.assertEqual(v[("documentFormatting", "reportLineIndentation")], "both")
		self.assertIs(v[("documentFormatting", "reportFontAttributes")], True)
		self.assertIs(v[("vision", "highlightFocus")], True)
		self.assertIs(v[("vision", "highlightNavigator")], False)
		self.assertIs(v[("vision", "screenCurtain")], False)
		self.assertIs(v[("vision", "curtainWarnOnEnable")], False)
		self.assertEqual(v[("uia", "eventRegistration")], "selective")
		self.assertIs(v[("uia", "preferUIAForConsoles")], False)
		self.assertEqual(v[("terminal", "diffAlgorithm")], "lines")
		self.assertEqual(v[("magnifier", "level")], 3.0)
		self.assertEqual(v[("magnifier", "filter")], "invert")
		self.assertEqual(v[("magnifier", "trackingMode")], "relative")
		self.assertEqual(v[("speechViewer", "position")], [10, 20, 300, 200])

	def test_notices(self) -> None:
		n = self.n
		self.assertIn("miComplemento", n)
		# Los valores de los complementos no se copian al informe (pueden ser secretos).
		self.assertNotIn("secreto", n)
		self.assertIn("reportBookmarks", n)
		self.assertIn("filas o solo de columnas", n)

	def test_nvda_defaults_flag(self) -> None:
		# Sin escribir en nvda.ini, NVDA no anuncia las descripciones emergentes.
		self.assertNotIn(("presentation", "reportHelpBalloons"), [c.path for c in self.p.changes if c.changes])
		with_defaults = self.values(self.p)
		# 10000 Hz en NVDA; se limita al rango del panel de Voz de Tiresias (50-5000).
		self.assertEqual(with_defaults[("speech", "beepSpeechModePitch")], 5000)
		plan = self.plan(self.folder, useDefaults=False)
		self.assertNotIn(("speech", "beepSpeechModePitch"), self.values(plan))
		self.assertTrue(all(not c.fromDefault for c in plan.changes))

	def test_unchanged_values_are_detected(self) -> None:
		same = [c for c in self.p.changes if not c.changes]
		self.assertTrue(same)
		self.assertTrue(any(c.path == ("speech", "trustVoiceLanguage") for c in same))

	def test_descriptions(self) -> None:
		lines = ni.previewLines(self.p, set(ni.CATEGORIES))
		text = "\n".join(lines)
		self.assertIn("Eloquence (IBMTTS) › Velocidad: 55", text)
		self.assertIn("[valor por defecto de NVDA]", text)


# ====================================================================== perfiles, gestos, diccionarios y símbolos
class FullTests(_Base):
	def setUp(self) -> None:
		super().setUp()
		self.folder = makeFull(self.tmp)
		self.p = self.plan(self.folder)
		self.n = self.notices(self.p)

	def test_profiles(self) -> None:
		profiles = {p.name: p for p in self.p.profiles}
		self.assertEqual(set(profiles), {"Bloc de notas", "Lectura"})
		notepad = profiles["Bloc de notas"]
		self.assertEqual(notepad.triggers, ["app:notepad"])
		values = {c.path: c.value for c in notepad.changes}
		self.assertEqual(values, {("speech", "synths", "ibmtts", "rate"): 80, ("keyboard", "speakTypedCharacters"): "always"})
		self.assertEqual(profiles["Lectura"].triggers, ["sayAll"])
		self.assertIn("Nadie", self.n)

	def test_gestures(self) -> None:
		got = {(g.gesture, g.script) for g in self.p.gestures}
		self.assertIn(("kb:tiresias+control+shift+b", "sayBatteryStatus"), got)
		self.assertIn(("kb:control+shift+alt+h", "quickNavNextHeading"), got)
		browse = [g for g in self.p.gestures if g.script == "quickNavNextHeading"]
		self.assertEqual(browse[0].classKey, "tiresias.browse.document.BrowseModeDocument")
		scripts = {g.script for g in self.p.gestures}
		# El menú nunca se importa con la tecla de NVDA, ni se pisa el de Tiresias.
		self.assertNotIn("showGui", scripts)
		self.assertNotIn(("kb:tiresias+m", "dateTime"), got)
		self.assertIn("menú de NVDA", self.n)
		self.assertIn("es la tecla del menú de Tiresias", self.n)
		# Teclas reservadas por Windows.
		self.assertNotIn("toggleInputHelp", scripts)
		self.assertIn("tecla reservada", self.n)
		self.assertIn("inventada", self.n)
		self.assertIn("miPlugin", self.n)
		self.assertIn("NVDA quita", self.n)

	def test_gesture_translation(self) -> None:
		self.assertEqual(ni.translateGesture("kb:NVDA+Shift+upArrow")[0], "kb:tiresias+shift+uparrow")
		self.assertEqual(ni.translateGesture("kb(laptop):nvda+control+a")[0], "kb(laptop):tiresias+control+a")
		self.assertEqual(ni.tiresiasScriptName("previousLandmark"), "quickNavPrevLandmark")
		self.assertEqual(ni.tiresiasScriptName("nextNotLinkBlock"), "quickNavNotLinkBlock")
		self.assertEqual(ni.tiresiasScriptName("nextTextParagraph"), "quickNavNextParagraph")
		self.assertIsNone(ni.translateGesture("br(lineaInventada):routing")[0])
		self.assertIsNone(ni.translateGesture("kb:nvda+teclainventada")[0])

	def test_dictionaries(self) -> None:
		dicts = {d.kind + ":" + d.target: d for d in self.p.dicts}
		default = dicts["default:default.json"]
		types = {(e["pattern"], e["type"]) for e in default.entries}
		self.assertIn(("NVDA", "word"), types)
		self.assertIn(("\\bdr\\.", "regex"), types)
		self.assertIn(("hola", "anywhere"), types)
		self.assertTrue(any(t == "regex" and p.startswith("(?s:x") for p, t in types))
		self.assertEqual(len(default.entries), 4)
		nvda = next(e for e in default.entries if e["pattern"] == "NVDA")
		self.assertEqual(nvda["comment"], "un comentario")
		self.assertIn("expresión regular no válida", self.n)
		voice = [d for d in self.p.dicts if d.kind == "voice"]
		self.assertEqual(len(voice), 1)
		self.assertEqual(voice[0].target, os.path.join("voices", "ibmtts-131072.json"))
		self.assertIn("temporal", self.n)
		self.assertIn("RHVoice", self.n)

	def test_symbols(self) -> None:
		self.assertEqual(len(self.p.symbols), 1)
		s = self.p.symbols[0]
		self.assertEqual(s.target, "symbols_user.json")
		bySym = {x["symbol"]: x for x in s.symbols}
		self.assertEqual(bySym["€"], {"symbol": "€", "name": "euro", "level": 100, "preserve": "never"})
		self.assertEqual(bySym["→"]["preserve"], "always")
		# «-»: el nombre de fábrica de Tiresias y el nivel nuevo.
		self.assertEqual(bySym["."]["level"], 200)
		self.assertEqual(bySym["."]["name"], "punto")
		self.assertNotIn("miComplejo", bySym)
		self.assertNotIn("sentence ending", bySym)
		self.assertIn("xx", self.n)

	def test_summary(self) -> None:
		text = "\n".join(self.p.summary)
		self.assertIn("Perfiles: 2", text)
		self.assertIn("NVDA instalado", text)


# ====================================================================== aplicar y deshacer
class ApplyUndoTests(_Base):
	def setUp(self) -> None:
		super().setUp()
		self.folder = makeFull(self.tmp)
		# Configuración previa de Tiresias que se tiene que poder recuperar.
		self.cm.base = {"speech": {"symbolLevel": 300}, "keyboard": {"layout": "desktop"}}
		self.cm.save()
		self.before = _read(self.cm.configFile)

	def test_apply_and_undo(self) -> None:
		plan = self.plan(self.folder)
		result = ni.applyPlan(plan, None, None, self.cm)
		self.assertTrue(os.path.isdir(result.backup))
		with open(self.cm.configFile, encoding="utf-8") as f:
			saved = json.load(f)
		self.assertEqual(saved["speech"]["synth"], "ibmtts")
		self.assertEqual(saved["speech"]["synths"]["ibmtts"]["rate"], 55)
		self.assertEqual(saved["speech"]["symbolLevel"], 200)
		self.assertEqual(saved["keyboard"]["layout"], "laptop")
		# Perfiles y disparadores.
		self.assertTrue(os.path.isfile(os.path.join(paths.profilesDir(), "Bloc de notas.json")))
		with open(self.cm.triggersFile, encoding="utf-8") as f:
			triggers = json.load(f)
		self.assertEqual(triggers["app:notepad"], "Bloc de notas")
		self.assertEqual(triggers["sayAll"], "Lectura")
		# Gestos.
		with open(os.path.join(paths.configDir(), "gestures.json"), encoding="utf-8") as f:
			gestures = json.load(f)
		self.assertEqual(gestures["tiresias.global_commands.GlobalCommands"]["kb:tiresias+control+shift+b"], "sayBatteryStatus")
		# Diccionarios y símbolos.
		self.assertTrue(os.path.isfile(os.path.join(paths.speechDictsDir(), "default.json")))
		self.assertTrue(os.path.isfile(os.path.join(paths.speechDictsDir(), "voices", "ibmtts-131072.json")))
		with open(os.path.join(paths.configDir(), "symbols_user.json"), encoding="utf-8") as f:
			self.assertTrue(any(s["symbol"] == "€" for s in json.load(f)["symbols"]))
		# Informe y copia exportada.
		self.assertTrue(os.path.isfile(result.report))
		report = _read(result.report)
		self.assertIn("LO QUE NO SE HA IMPORTADO Y POR QUÉ", report)
		export = _json(result.export)
		self.assertEqual(export["configuracion"]["speech"]["synth"], "ibmtts")
		# Deshacer.
		self.assertTrue(ni.canUndo())
		ni.undoLastImport(self.cm)
		self.assertEqual(_read(self.cm.configFile), self.before)
		self.assertFalse(os.path.isfile(os.path.join(paths.profilesDir(), "Bloc de notas.json")))
		self.assertFalse(os.path.isfile(os.path.join(paths.configDir(), "gestures.json")))
		self.assertFalse(os.path.isfile(os.path.join(paths.speechDictsDir(), "default.json")))
		self.assertFalse(os.path.isfile(os.path.join(paths.configDir(), "symbols_user.json")))
		self.assertFalse(ni.canUndo())
		with self.assertRaises(ni.ImportError_):
			ni.undoLastImport(self.cm)

	def test_apply_selected_categories_into_new_profile(self) -> None:
		plan = self.plan(self.folder)
		result = ni.applyPlan(plan, {ni.CAT_SPEECH, ni.CAT_KEYBOARD}, "Como NVDA", self.cm)
		self.assertEqual(result.gestures, 0)
		self.assertEqual(result.profiles, 0)
		with open(os.path.join(paths.profilesDir(), "Como NVDA.json"), encoding="utf-8") as f:
			prof = json.load(f)
		self.assertEqual(prof["speech"]["synth"], "ibmtts")
		self.assertEqual(prof["keyboard"]["layout"], "laptop")
		self.assertNotIn("braille", prof)
		# La configuración normal no cambia.
		self.assertEqual(_json(self.cm.configFile)["speech"]["symbolLevel"], 300)
		self.assertNotIn("keyboard", _json(self.cm.configFile))
		self.assertFalse(os.path.isfile(os.path.join(paths.configDir(), "gestures.json")))
		with self.assertRaises(ni.ImportError_):
			ni.applyPlan(plan, {ni.CAT_SPEECH}, "Como NVDA", self.cm)
		ni.undoLastImport(self.cm)
		self.assertFalse(os.path.isfile(os.path.join(paths.profilesDir(), "Como NVDA.json")))

	def test_dictionary_merge(self) -> None:
		target = os.path.join(paths.speechDictsDir(), "default.json")
		os.makedirs(os.path.dirname(target), exist_ok=True)
		with open(target, "w", encoding="utf-8") as f:
			json.dump({"entries": [{"pattern": "hola", "replacement": "adiós", "caseSensitive": False, "type": "anywhere"}, {"pattern": "propia", "replacement": "mía"}]}, f)
		plan = self.plan(self.folder)
		ni.applyPlan(plan, {ni.CAT_DICTS}, None, self.cm)
		entries = _json(target)["entries"]
		patterns = [e["pattern"] for e in entries]
		self.assertEqual(patterns.count("hola"), 1)
		self.assertIn("propia", patterns)
		self.assertIn("NVDA", patterns)

	def test_read_only_refuses(self) -> None:
		plan = self.plan(self.folder)
		self.cm.readOnly = True
		with self.assertRaises(ni.ImportError_):
			ni.applyPlan(plan, None, None, self.cm)

	def test_command_line(self) -> None:
		from tiresias import core

		# La línea de órdenes usa la configuración global: se guarda y se restaura.
		saved = (copy.deepcopy(conf.base), dict(conf.profiles), dict(conf.triggers), conf.policy, core.args)
		self.addCleanup(self._restoreConf, saved)
		out = io.StringIO()
		with contextlib.redirect_stdout(out):
			code = core.main(["--data", self.data, "--import-nvda-config", self.folder])
		self.assertEqual(code, 0, out.getvalue())
		self.assertIn("Informe:", out.getvalue())
		with open(os.path.join(paths.configDir(), "config.json"), encoding="utf-8") as f:
			self.assertEqual(json.load(f)["speech"]["synth"], "ibmtts")
		with contextlib.redirect_stdout(out):
			self.assertEqual(core.main(["--data", self.data, "--undo-nvda-import"]), 0)
		with open(os.path.join(paths.configDir(), "config.json"), encoding="utf-8") as f:
			self.assertNotIn("synth", json.load(f).get("speech", {}))
		with contextlib.redirect_stdout(out):
			self.assertEqual(core.main(["--data", self.data, "--import-nvda-config", os.path.join(self.tmp, "nada")]), 1)

	@staticmethod
	def _restoreConf(saved: tuple) -> None:
		from tiresias import core

		base, profiles, triggers, policy, args = saved
		conf.base, conf.profiles, conf.triggers = base, profiles, triggers
		conf.setPolicy(policy)
		core.args = args


if __name__ == "__main__":
	unittest.main()
