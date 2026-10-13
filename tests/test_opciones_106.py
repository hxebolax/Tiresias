"""Revisión del cuadro de Opciones (1.0.6): organización, opciones repetidas y efecto.

- Estructura: ninguna opción está en dos categorías, todas existen en los
  valores por defecto y se leen en el código, las teclas rápidas no se repiten
  en ninguna categoría y el orden de la lista es el de NVDA (``PANEL_ORDER``),
  con las categorías de los complementos detrás de «Aplicaciones».
- Categorías unidas: «Mezclador de audio» (en «Audio»), «Líneas braille» (en
  «Braille»), «UI Automation» y «Objetos y aplicaciones» (en «Avanzado» y
  «Presentación de objetos»); sus identificadores siguen abriendo la nueva.
- «Valores de fábrica de esta categoría» pone cada control con su valor de fábrica.
- Opciones repetidas quitadas: Word y Excel siguen «Formato de documento»,
  «pulsable» es una sola opción y ``speech.reportNumbersAsDigits`` ya no existe
  (migración de la configuración a la versión 3).
- «Reproducir un sonido al registrarse un error» suena con cualquier error del
  registro, no solo con los de las órdenes.
- Cambios que no se aplicaban al guardar: el visor braille, la caché de API de
  las ventanas al cambiar las consolas o Java.
- El manual tiene una fila (y su ancla F1) para cada opción, en el orden del cuadro.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_opciones_106``
"""

from __future__ import annotations

import importlib
import os
import re
import shutil
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_opciones106_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()

from tiresias.config import conf  # noqa: E402

SRC = os.path.join(ROOT, "src", "tiresias")
MANUAL = os.path.join(ROOT, "manual", "manual_usuario.html")

#: Claves de ayuda F1 de controles propios que no son una opción de la configuración.
PSEUDO_KEYS = {("coexist", "rememberedReader")}


def _registerEverything() -> None:
	"""Valores por defecto y categorías, como al arrancar Tiresias."""
	from tiresias.gui import ai_dialogs
	from tiresias.gui import settings as S

	for mod, fn in (
		("tiresias.a11y", None),
		("tiresias.clipboard", None),
		("tiresias.ocr", None),
		("tiresias.vision", None),
		("tiresias.magnifier", None),
		("tiresias.mouse_keys", None),
		("tiresias.appmodules", None),
		("tiresias.ai.assistant", None),
		("tiresias.mathpres", None),
		("tiresias.touch.handler", None),
		("tiresias.remote", "registerDefaults"),
		("tiresias.remote.rdp", "registerDefaults"),
		("tiresias.productivity", "registerDefaults"),
		("tiresias.controller", "registerDefaults"),
		("tiresias.coexist", "registerDefaults"),
		("tiresias.gui.speech_settings", "registerPanels"),
		("tiresias.gui.audio_dialogs", "register"),
		("tiresias.gui.touch_panel", "register"),
		("tiresias.gui.apps_panel", "register"),
		("tiresias.gui.productivity_dialogs", "registerSettingsPanels"),
		("tiresias.gui.remote_dialogs", "registerSettingsPanel"),
		("tiresias.gui.rdp_panel", "register"),
		("tiresias.mathpres.settings_panel", "registerPanel"),
	):
		m = importlib.import_module(mod)
		if fn:
			getattr(m, fn)()
	S.registerPanel("ai", ai_dialogs.AiPanel.title, ai_dialogs.AiPanel)


def _accel(label: str) -> str | None:
	i = 0
	while i < len(label):
		if label[i] == "&":
			if label[i + 1 : i + 2] == "&":
				i += 2
				continue
			return label[i + 1 : i + 2].lower() or None
		i += 1
	return None


class _Dialog:
	"""Cuadro de Opciones real (sin mostrarlo) con todas las categorías creadas."""

	dlg = None
	panels: dict = {}

	@classmethod
	def open(cls) -> None:
		import wx

		from tiresias.gui import settings as S

		cls.app = wx.App.Get() or wx.App(False)
		_registerEverything()
		cls.dlg = S.SettingsDialog(None)
		cls.panels = {}
		for pid in S.getPanelIds():
			cls.dlg.selectCategory(pid)
			cls.panels[pid] = cls.dlg.getPanel(pid)

	@classmethod
	def close(cls) -> None:
		if cls.dlg is not None:
			for panel in cls.dlg._panels.values():
				try:
					panel.onDiscard()
				except Exception:
					pass
			cls.dlg.Destroy()
			cls.dlg = None

	@classmethod
	def options(cls, withHelp: bool = True) -> dict[tuple[str, str], list[str]]:
		"""{(sección, clave): [categorías]} de todas las opciones del cuadro."""
		out: dict[tuple[str, str], list[str]] = {}
		for pid, panel in cls.panels.items():
			keys = list(getattr(panel, "_bound", {}) or {})
			if withHelp:
				keys += [k for k in (getattr(panel, "_helpKeys", {}) or {}).values() if k not in keys]
			for key in dict.fromkeys(keys):
				out.setdefault(key, []).append(pid)
		return out


# ====================================================================== estructura
class StructureTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		_Dialog.open()

	@classmethod
	def tearDownClass(cls) -> None:
		_Dialog.close()

	def test_every_panel_builds(self) -> None:
		for pid, panel in _Dialog.panels.items():
			self.assertIsNotNone(panel, pid)

	def test_no_option_in_two_categories(self) -> None:
		repeated = {k: v for k, v in _Dialog.options().items() if len(v) > 1}
		self.assertEqual(repeated, {})

	def test_every_option_has_a_default(self) -> None:
		missing = []
		for sec, key in _Dialog.options():
			if (sec, key) in PSEUDO_KEYS:
				continue
			d = conf.defaults.get(sec)
			if not isinstance(d, dict) or key not in d:
				missing.append(f"{sec}.{key}")
		self.assertEqual(missing, [])

	def test_every_option_is_read_in_the_code(self) -> None:
		files: dict[str, list[str]] = {}
		for dp, _dn, fn in os.walk(SRC):
			if "__pycache__" in dp:
				continue
			for f in fn:
				if f.endswith(".py"):
					p = os.path.join(dp, f)
					with open(p, encoding="utf-8") as fh:
						files[p] = fh.read().splitlines()
		addons = os.path.join(ROOT, "data", "addons")
		for dp, _dn, fn in os.walk(addons):
			for f in fn:
				if f.endswith(".py") and "__pycache__" not in dp:
					p = os.path.join(dp, f)
					with open(p, encoding="utf-8") as fh:
						files[p] = fh.read().splitlines()
		skip = ("schema.py", "defaults.py", "validation.py", "nvda_import.py", "context_help.py")
		decl = re.compile(r"\b(Bool|Int|Choice|Text|ListText|Slider|Field|B|I|F\.\w+|S\.\w+|settings\.\w+)\(\s*[\"']")
		from tiresias.speech import voice_schemes

		# Si la clave existe en varias secciones, el archivo que la lee tiene que nombrar la sección.
		sections: dict[str, int] = {}
		for values in conf.defaults.values():
			if isinstance(values, dict):
				for k in values:
					sections[k] = sections.get(k, 0) + 1
		unread = []
		for sec, key in _Dialog.options(withHelp=False):
			m = re.fullmatch(r"context(\w+?)(Rate|Pitch|Volume|Voice|SymbolLevel)", key)
			if sec == "speech" and m:
				# Claves dinámicas: voice_schemes.contextKey(contexto, propiedad).
				self.assertIn(key, [voice_schemes.contextKey(c, m.group(2)) for c in voice_schemes.CONTEXTS])
				continue
			pat = re.compile(r"[\"']" + re.escape(key) + r"[\"']")
			found = False
			for p, lines in files.items():
				if os.path.basename(p) in skip:
					continue
				text = "\n".join(lines)
				if sections.get(key, 0) > 1 and f'"{sec}"' not in text and f"'{sec}'" not in text:
					continue
				for line in lines:
					s = line.strip()
					if s.startswith("#") or not pat.search(s) or decl.search(s) or "registerDefaults" in s:
						continue
					if re.match(r"^[\"']" + re.escape(key) + r"[\"']\s*:", s):
						continue
					found = True
					break
				if found:
					break
			if not found:
				unread.append(f"{sec}.{key}")
		self.assertEqual(unread, [])

	def test_accelerators_are_unique_in_each_category(self) -> None:
		import wx

		dlg = _Dialog.dlg

		def labels(win, skip=()) -> list[tuple[str, str]]:
			out = []

			def walk(w) -> None:
				if w in skip or (isinstance(w, wx.TopLevelWindow) and w is not win):
					return
				if isinstance(w, (wx.StaticText, wx.Button, wx.CheckBox, wx.RadioButton, wx.StaticBox)):
					a = _accel(w.GetLabel())
					if a:
						out.append((a, w.GetLabel()))
				for c in w.GetChildren():
					walk(c)

			walk(win)
			return out

		top = labels(dlg, skip=(dlg.container,))
		for pid, panel in _Dialog.panels.items():
			with self.subTest(category=pid):
				seen: dict[str, str] = {}
				dups = []
				for a, lab in top + labels(panel):
					if a in seen:
						dups.append((a, seen[a], lab))
					seen[a] = lab
				self.assertEqual(dups, [])

	def test_order_is_nvda_like(self) -> None:
		from tiresias.gui import settings as S

		ids = S.getPanelIds()
		self.assertEqual(ids, [i for i in S.PANEL_ORDER if i in ids])
		self.assertEqual(ids[:6], ["general", "speech", "speechReading", "speechLanguage", "voiceContexts", "braille"])
		self.assertEqual(ids[-1], "advanced")
		for before, after in (("braille", "audio"), ("audio", "vision"), ("vision", "keyboard"), ("keyboard", "mouse"), ("mouse", "reviewCursor"), ("reviewCursor", "presentation"), ("presentation", "browseMode"), ("browseMode", "documentFormatting"), ("documentFormatting", "documentNavigation"), ("documentNavigation", "ocr"), ("ocr", "updates")):
			self.assertLess(ids.index(before), ids.index(after), (before, after))
		for gone in ("mixer", "uia", "objects", "brailleDisplays"):
			self.assertNotIn(gone, ids)

	def test_addon_categories_go_after_apps(self) -> None:
		from tiresias.gui import settings as S

		class AddonPanel(S.ConfigPanel):
			section = "general"
			fields: list = []

		S.registerPanel("prueba106", "Prueba", AddonPanel)
		try:
			ids = S.getPanelIds()
			self.assertEqual(ids.index("prueba106"), ids.index("apps") + 1)
			self.assertEqual(ids[-1], "advanced")
		finally:
			S.unregisterPanel("prueba106")

	def test_old_category_ids_open_the_new_ones(self) -> None:
		dlg = _Dialog.dlg
		for old, new in (("mixer", "audio"), ("brailleDisplays", "braille"), ("uia", "advanced"), ("objects", "advanced")):
			dlg.selectCategory(old)
			self.assertEqual(dlg._current, new, old)

	def test_quick_settings_follow_the_dialog_order(self) -> None:
		from tiresias.gui import settings as S
		from tiresias.gui import system_dialogs

		seen: list[str] = []
		for e in system_dialogs.collectSettings():
			if not seen or seen[-1] != e.panelId:
				seen.append(e.panelId)
		self.assertEqual(seen, [i for i in S.getPanelIds() if i in seen])

	def test_moved_options(self) -> None:
		"""Cada opción en la categoría que un usuario esperaría (como en NVDA)."""
		where = {k: v[0] for k, v in _Dialog.options().items()}
		expected = {
			("keyboard", "speakWholeEditedWord"): "keyboard",
			("speech", "contextTypingRate"): "keyboard",
			("keyboard", "allowSkimReadingInSayAll"): "speechReading",
			("speech", "excludedSpeechModes"): "speech",
			("speech", "beepSpeechModePitch"): "speech",
			("speech", "reportUnknownSymbols"): "speech",
			("speech", "cancelExpiredFocusSpeech"): "speech",
			("speech", "spellAccessKeys"): "presentation",
			("speechViewer", "showAtStartup"): "speech",
			("brailleViewer", "showAtStartup"): "brailleAdvanced",
			("braille", "numCellsForViewer"): "brailleAdvanced",
			("braille", "pcKeyboardDots"): "braille",
			("brailleDisplays", "brlapiServer"): "braille",
			("audio", "mixerVolumeStep"): "audio",
			("audio", "soundVolume"): "sounds",
			("audio", "playSounds"): "sounds",
			("uia", "notificationsFromBackground"): "presentation",
			("uia", "eventRegistration"): "advanced",
			("objects", "reportDialogText"): "presentation",
			("objects", "useIA2"): "advanced",
			("terminal", "speakPasswords"): "advanced",
			("java", "enabled"): "advanced",
			("sleepMode", "enabled"): "apps",
			("documentNavigation", "paragraphStyle"): "documentNavigation",
		}
		self.assertEqual({k: where.get(k) for k in expected}, expected)

	def test_removed_duplicates(self) -> None:
		keys = _Dialog.options()
		for gone in (
			("officeWord", "reportListItems"),
			("officeWord", "reportCommentsAndRevisions"),
			("officeWord", "reportPageChanges"),
			("officeWord", "reportTableHeaders"),
			("officeExcel", "reportHeaders"),
			("presentation", "reportClickable"),
			("braille", "display"),
		):
			if gone == ("braille", "display"):
				# Ya no es una lista: el botón «Seleccionar línea braille...» (como en NVDA).
				self.assertNotIn(gone, {k for p in _Dialog.panels.values() for k in getattr(p, "_bound", {})})
				continue
			self.assertNotIn(gone, keys)
			self.assertNotIn(gone[1], conf.defaults.get(gone[0], {}))
		self.assertNotIn("reportNumbersAsDigits", conf.defaults["speech"])


# ====================================================================== valores de fábrica
class ResetToFactoryTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		_Dialog.open()

	@classmethod
	def tearDownClass(cls) -> None:
		_Dialog.close()

	@staticmethod
	def _other(b):
		"""Pone en el control un valor distinto del de fábrica (si se puede)."""
		from tiresias.gui import settings as S

		f = b.field
		ctrl = b.ctrl
		default = S.ConfigPanel.factoryValue(b.section, f.key, f.default)
		if f.kind == "bool":
			ctrl.SetValue(not default)
		elif f.kind in ("int", "slider"):
			ctrl.SetValue(f.minVal if default != f.minVal else f.maxVal)
		elif f.kind == "choice" and len(b.values) > 1:
			others = [i for i, v in enumerate(b.values) if v != default]
			ctrl.SetSelection(others[0])
		elif f.kind in ("text", "list"):
			ctrl.SetValue("zzz")
		elif f.kind == "checklist" and b.values:
			for i in range(len(b.values)):
				ctrl.Check(i, b.values[i] not in (default or []))

	def test_every_category_goes_back_to_factory_values(self) -> None:
		from tiresias.gui import settings as S

		dlg = _Dialog.dlg
		for pid, panel in _Dialog.panels.items():
			if not isinstance(panel, S.ConfigPanel):
				continue
			with self.subTest(category=pid):
				for b in panel._bound.values():
					if not b.field.readOnly and b.ctrl.IsEnabled():
						self._other(b)
				dlg.selectCategory(pid)
				self.assertTrue(dlg.resetCategory())
				for (sec, key), b in panel._bound.items():
					if b.field.readOnly or not b.ctrl.IsEnabled():
						continue
					default = S.ConfigPanel.factoryValue(sec, key, b.field.default)
					if b.field.kind == "choice" and default not in b.values:
						continue
					value = panel._readControl(b)
					if b.field.kind == "list":
						default = list(default or [])
					self.assertEqual(value, default, f"{sec}.{key}")

	def test_custom_controls_go_back_to_factory_values(self) -> None:
		from tiresias.gui import settings as S

		dlg = _Dialog.dlg
		speech = _Dialog.panels["speech"]
		for check in speech._modeChecks.values():
			check.SetValue(True)
		dlg.selectCategory("speech")
		dlg.resetCategory()
		self.assertEqual(speech._excluded(), [])
		audio = _Dialog.panels["audio"]
		for i in range(audio.splitModesList.GetCount()):
			audio.splitModesList.Check(i, False)
		dlg.selectCategory("audio")
		dlg.resetCategory()
		wanted = S.ConfigPanel.factoryValue("audio", "includedSoundSplitModes")
		self.assertEqual([m for i, m in enumerate(audio._splitModes) if audio.splitModesList.IsChecked(i)], [m for m in audio._splitModes if m in wanted])
		verbosity = _Dialog.panels["verbosity"]
		verbosity._order.reverse()
		dlg.selectCategory("verbosity")
		dlg.resetCategory()
		from tiresias.speech import verbosity as V

		self.assertEqual(verbosity._order, list(V.DEFAULT_ORDER))
		braille = _Dialog.panels["brailleAdvanced"]
		braille._propKeys.reverse()
		braille._roleAbbreviations = {"BUTTON": "x"}
		dlg.selectCategory("brailleAdvanced")
		dlg.resetCategory()
		self.assertEqual(braille._roleAbbreviations, {})
		from tiresias.braille import presenter

		self.assertEqual(sorted(braille._propKeys), sorted(presenter.PROPERTY_KEYS))

	def test_reset_button_does_not_save(self) -> None:
		dlg = _Dialog.dlg
		dlg.selectCategory("mouse")
		panel = _Dialog.panels["mouse"]
		old = conf["mouse"]["reportDelay"]
		try:
			conf["mouse"]["reportDelay"] = 300
			panel.setControlValue("reportDelay", 300)
			panel._bound[("mouse", "reportDelay")].original = 300
			with mock.patch("tiresias.gui.settings.speakMessageOnCore"):
				dlg._onResetCategory(None)
			self.assertEqual(conf["mouse"]["reportDelay"], 300)
			self.assertEqual(panel.getValue("reportDelay"), 0)
			with mock.patch.object(type(panel), "afterSave"):
				panel.onSave()
			self.assertEqual(conf["mouse"]["reportDelay"], 0)
		finally:
			conf["mouse"]["reportDelay"] = old
			panel.setControlValue("reportDelay", old)
			panel._bound[("mouse", "reportDelay")].original = old


# ====================================================================== opciones arregladas
class FixedOptionsTests(unittest.TestCase):
	def test_error_sound_for_any_logged_error(self) -> None:
		from tiresias import log as logModule

		handler = logModule._ErrorSoundHandler()
		record = logModule.logging.LogRecord("tiresias.prueba", logModule.logging.ERROR, __file__, 1, "fallo", None, None)
		old = conf["advanced"]["playErrorSound"]
		try:
			with mock.patch("tiresias.queue_handler.queueFunction") as q:
				conf["advanced"]["playErrorSound"] = True
				handler.emit(record)
				handler.emit(record)  # menos de un segundo después: no se repite
				self.assertEqual([c.args[0] for c in q.call_args_list], [logModule._playErrorSound])
				q.reset_mock()
				handler._last = time.monotonic() - 5
				conf["advanced"]["playErrorSound"] = False
				handler.emit(record)
				q.assert_not_called()
		finally:
			conf["advanced"]["playErrorSound"] = old
		self.assertEqual(handler.level, logModule.logging.ERROR)

	def test_word_uses_document_formatting(self) -> None:
		from tiresias.appmodules import _word, winword

		info = {"comments": 1, "revisions": 2, "footnotes": 1}
		self.assertEqual(_word.lineSuffix(info, True, False), ["con comentario", "con nota al pie"])
		self.assertEqual(_word.lineSuffix(info, False, True), ["con 2 revisiones"])
		self.assertEqual(_word.lineSuffix(info, True), ["con comentario", "con 2 revisiones", "con nota al pie"])
		df = conf["documentFormatting"]
		keys = ("reportLists", "reportComments", "reportRevisions", "reportPage", "reportTableHeaders")
		saved = {k: df[k] for k in keys}
		try:
			for k in keys:
				df[k] = False
			self.assertFalse(winword.WordDocument._wantsLineExtras(types.SimpleNamespace()))
			df["reportPage"] = True
			self.assertTrue(winword.WordDocument._wantsLineExtras(types.SimpleNamespace()))
		finally:
			for k, v in saved.items():
				df[k] = v
		with open(os.path.join(SRC, "appmodules", "winword.py"), encoding="utf-8") as f:
			text = f.read()
		for gone in ("reportListItems", "reportCommentsAndRevisions", "reportPageChanges"):
			self.assertNotIn(gone, text)

	def test_excel_headers_follow_document_formatting(self) -> None:
		from tiresias.appmodules import excel

		cell = types.SimpleNamespace(headerTexts=lambda: ("Fila", "Columna"), value="30", name="B2")
		old = conf["documentFormatting"]["reportTableHeaders"]
		try:
			conf["documentFormatting"]["reportTableHeaders"] = True
			self.assertEqual(excel.ExcelCell._speechParts(cell, withDetails=False)[:2], ["Fila", "Columna"])
			conf["documentFormatting"]["reportTableHeaders"] = False
			self.assertNotIn("Fila", excel.ExcelCell._speechParts(cell, withDetails=False))
		finally:
			conf["documentFormatting"]["reportTableHeaders"] = old

	def test_clickable_is_one_option(self) -> None:
		from tiresias import presentation
		from tiresias.objects.roles import Role

		class Clickable:
			name = "Texto"
			role = Role.STATICTEXT
			states: set = set()
			description = ""
			roleText = None

			def _prop(self, prop, default=None):
				return True

		old = conf["documentFormatting"]["reportClickable"]
		try:
			conf["documentFormatting"]["reportClickable"] = True
			self.assertIn("pulsable", " ".join(presentation.getObjectSpeech(Clickable(), presentation.Reason.FOCUS)))
			conf["documentFormatting"]["reportClickable"] = False
			self.assertNotIn("pulsable", " ".join(presentation.getObjectSpeech(Clickable(), presentation.Reason.FOCUS)))
		finally:
			conf["documentFormatting"]["reportClickable"] = old

	def test_migration_to_v3(self) -> None:
		from tiresias.config import migrations, schema

		self.assertEqual(schema.SCHEMA_VERSION, 3)
		data = {
			"schemaVersion": 2,
			"officeWord": {"reportListItems": False, "reportPageChanges": True, "reportFormattingShortcuts": False},
			"officeExcel": {"reportHeaders": False},
			"presentation": {"reportClickable": False},
			"speech": {"reportNumbersAsDigits": True},
		}
		self.assertEqual(migrations.migrate(data), [2])
		self.assertEqual(data["officeWord"], {"reportFormattingShortcuts": False})
		self.assertNotIn("officeExcel", data)
		self.assertNotIn("presentation", data)
		self.assertIs(data["documentFormatting"]["reportClickable"], False)
		self.assertEqual(data["speech"], {"numberReading": "digits"})
		# Si ya había un modo de lectura de números, se respeta.
		data = {"schemaVersion": 2, "speech": {"reportNumbersAsDigits": True, "numberReading": "pairs"}}
		migrations.migrate(data)
		self.assertEqual(data["speech"], {"numberReading": "pairs"})

	def test_number_mode_ignores_old_option(self) -> None:
		from tiresias.speech import numbers

		self.assertEqual(numbers.effectiveNumberMode({"numberReading": "full", "reportNumbersAsDigits": True}), "full")
		self.assertEqual(numbers.effectiveNumberMode({"numberReading": "nada"}), "full")

	def test_api_cache_is_forgotten_when_consoles_or_java_change(self) -> None:
		from tiresias.a11y import api_choice, system
		from tiresias.gui import settings as S

		for key in (("uia", "preferUIAForConsoles"), ("java", "enabled"), ("objects", "uiaClasses")):
			with self.subTest(key=key), mock.patch.object(S.queue_handler, "queueFunction") as q:
				S.AdvancedPanel.afterSave(types.SimpleNamespace(), {key: (True, False)})
				self.assertIn(api_choice.invalidate, [c.args[0] for c in q.call_args_list])
		with mock.patch.object(S.queue_handler, "queueFunction") as q:
			S.AdvancedPanel.afterSave(types.SimpleNamespace(), {("system", "registerAsAT"): (False, True)})
			self.assertEqual([c.args[0] for c in q.call_args_list], [system.applyConfig])

	def test_braille_viewer_cells_apply_on_save(self) -> None:
		from tiresias import braille
		from tiresias.gui import braille_panels

		with mock.patch.object(braille_panels.queue_handler, "queueFunction") as q:
			braille_panels.BraillePresentationPanel.afterSave(types.SimpleNamespace(), {("braille", "numCellsForViewer"): (40, 20)})
		self.assertEqual([c.args[0] for c in q.call_args_list], [braille.handler.reloadViewer, braille.handler.applyConfig])

	def test_braille_connection_changes_apply_on_save(self) -> None:
		from tiresias.gui import braille_display_dialog as bdd
		from tiresias.gui import settings as S

		# bdd.queue_handler y S.queue_handler son el mismo módulo.
		with mock.patch.object(S.queue_handler, "queueFunction") as q:
			S.BraillePanel.afterSave(types.SimpleNamespace(), {("brailleDisplays", "detectBluetooth"): (True, False), ("brailleDisplays", "brlapiServer"): ("a", "b")})
		self.assertEqual([c.args[0] for c in q.call_args_list], [bdd._rescan, bdd._reconnectBrltty])

	def test_buffer_size_applies_without_restarting(self) -> None:
		"""«Tamaño del búfer de audio» reabre la salida en el siguiente bloque de audio."""
		from tiresias.audio import wave_player

		class Backend(wave_player._Backend):
			mode = "wasapi"
			opened = 0

			def open(self, deviceName: str) -> None:
				type(self).opened += 1
				self.deviceName = deviceName

			def write(self, data: bytes) -> int:
				return 0

			def played(self) -> int:
				return 0

			def reset(self) -> None:
				pass

			def pause(self, switch: bool) -> None:
				pass

			def close(self) -> None:
				pass

			def stillValid(self) -> bool:
				return True

		saved = (conf["audio"]["outputMode"], conf["audio"]["bufferSize"])
		player = wave_player.WavePlayer(22050, 1, name="prueba-opciones106", keepAwake=False)
		try:
			conf["audio"]["outputMode"] = "wasapi"
			conf["audio"]["bufferSize"] = "normal"
			with mock.patch.object(wave_player, "_WasapiBackend", Backend), mock.patch.object(wave_player, "_WaveOutBackend", Backend):
				b1 = player._openBackend()
				self.assertIs(player._openBackend(), b1)
				conf["audio"]["bufferSize"] = "high"
				b2 = player._openBackend()
				self.assertIsNot(b2, b1)
				self.assertIs(player._openBackend(), b2)
			self.assertEqual(Backend.opened, 2)
		finally:
			player.terminate()
			conf["audio"]["outputMode"], conf["audio"]["bufferSize"] = saved

	def test_excluded_speech_modes_are_saved_from_speech_panel(self) -> None:
		import wx

		from tiresias.gui import settings as S

		app = wx.App.Get() or wx.App(False)  # noqa: F841
		frame = wx.Frame(None)
		old = list(conf["speech"]["excludedSpeechModes"])
		try:
			panel = S.SpeechPanel(frame)
			panel._modeChecks["beeps"].SetValue(True)
			with mock.patch.object(S.queue_handler, "queueFunction"):
				self.assertTrue(panel.isValid())
				panel.onSave()
			self.assertEqual(list(conf["speech"]["excludedSpeechModes"]), sorted(set(old) | {"beeps"}))
			for check in panel._modeChecks.values():
				check.SetValue(True)
			with mock.patch.object(S, "showError"):
				self.assertFalse(panel.isValid())
		finally:
			conf["speech"]["excludedSpeechModes"] = old
			frame.Destroy()


# ====================================================================== manual y F1
class ManualTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		if not os.path.isfile(MANUAL):
			raise unittest.SkipTest("sin manual")
		with open(MANUAL, encoding="utf-8") as f:
			cls.text = f.read()
		_Dialog.open()

	@classmethod
	def tearDownClass(cls) -> None:
		_Dialog.close()

	def test_every_option_has_its_row(self) -> None:
		missing = [f"opt-{s}-{k}" for (s, k) in _Dialog.options() if f'id="opt-{s}-{k}"' not in self.text]
		self.assertEqual(missing, [])

	def test_chapter_follows_the_dialog_order(self) -> None:
		from tiresias.gui import settings as S

		start = self.text.index('<h2 id="opciones">')
		end = self.text.index("</section>", start)
		chapter = self.text[start:end]
		cats = re.findall(r'<h3 id="op-[^"]+">[^<]*<span id="cat-([^"]+)"></span>', chapter)
		self.assertEqual(cats, S.getPanelIds())
		for gone in ("op-mezclador", "op-uia", "op-objetos", "op-lineas-braille", "cat-mixer", "cat-uia", "cat-objects", "cat-brailleDisplays"):
			self.assertIn(f'id="{gone}"', chapter)

	def test_rows_are_in_the_dialog_order(self) -> None:
		"""Dentro de cada categoría, las filas van en el orden del cuadro."""
		start = self.text.index('<h2 id="opciones">')
		end = self.text.index("</section>", start)
		chapter = self.text[start:end]
		pos = {m.group(1): m.start() for m in re.finditer(r'\bid="(opt-[^"]+)"', chapter)}
		for pid, panel in _Dialog.panels.items():
			keys = list(dict.fromkeys(list(getattr(panel, "_bound", {})) + list((getattr(panel, "_helpKeys", {}) or {}).values())))
			order = [pos[f"opt-{s}-{k}"] for s, k in keys if f"opt-{s}-{k}" in pos]
			with self.subTest(category=pid):
				# Las opciones de varios grupos pueden compartir fila: basta con que no retrocedan de grupo.
				cat = chapter.index(f'<span id="cat-{pid}"></span>')
				nxt = [m.start() for m in re.finditer(r"<h3 ", chapter) if m.start() > cat]
				limit = nxt[0] if nxt else len(chapter)
				self.assertTrue(all(cat < p < limit for p in order), pid)


if __name__ == "__main__":
	unittest.main()
