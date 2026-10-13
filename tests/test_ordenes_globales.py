"""Pruebas de las órdenes globales añadidas y de los errores urgentes corregidos.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
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

_TMP = tempfile.mkdtemp(prefix="tiresias_test_ordenes_")
if not os.path.isdir(os.path.join(_TMP, "symbols")):
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
paths.setDataDir(_TMP)
paths.ensureDataDirs()

from tiresias import formatting, global_commands_extra  # noqa: E402
from tiresias.baseobject import normalizeGestureId  # noqa: E402
from tiresias.config import conf, schema, validation  # noqa: E402
from tiresias.objects.roles import Role  # noqa: E402


class _FakeSpeech:
	"""Sustituye a ``speech.speakMessage`` para capturar los mensajes."""

	def __init__(self) -> None:
		self.messages: list[str] = []

	def __enter__(self):
		from tiresias import speech

		self._speech = speech
		self._old = speech.speakMessage
		speech.speakMessage = lambda text, *a, **k: self.messages.append(text)
		return self

	def __exit__(self, *exc) -> None:
		self._speech.speakMessage = self._old


class SchemaTests(unittest.TestCase):
	def test_new_document_formatting_options(self) -> None:
		df = schema.DEFAULTS["documentFormatting"]
		for key in ("reportLineSpacing", "ignoreBlankLinesForRLI", "reportCellBorders", "reportLinkType", "reportFigures"):
			self.assertIn(key, df)
		self.assertIn(("documentFormatting", "reportCellBorders"), validation.CHOICES)

	def test_clipboard_and_sleep_options(self) -> None:
		cb = schema.DEFAULTS["clipboard"]
		for key in ("confirmCopyCommands", "announceCutCopyPaste", "announcePastedText"):
			self.assertIn(key, cb)
		self.assertIn("enabled", schema.DEFAULTS["sleepMode"])

	def test_speech_output_device_removed(self) -> None:
		self.assertNotIn("outputDevice", schema.DEFAULTS["speech"])


class GlobalCommandsTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		from tiresias import global_commands

		cls.cls = global_commands.GlobalCommands
		cls.commands = global_commands.commands

	def test_all_document_toggles_installed(self) -> None:
		names = [n for n, _k, _w in global_commands_extra.DOC_TOGGLES] + [n for n, _k, _w, _v in global_commands_extra.DOC_CYCLES]
		# 39: incluye «cycleColorFormat» (#8674) y, desde la revisión del manual
		# (D-004), citas en línea, detalles, abreviaturas de encabezados y
		# detectar el formato después del cursor.
		self.assertEqual(len(names), 39)
		for name in names:
			func = getattr(self.cls, "script_" + name, None)
			self.assertIsNotNone(func, name)
			self.assertTrue(func.__doc__)

	def test_document_toggle_changes_config(self) -> None:
		before = conf["documentFormatting"]["reportFigures"]
		with _FakeSpeech() as fake:
			self.commands.script_toggleReportFigures(None)
		self.assertEqual(conf["documentFormatting"]["reportFigures"], not before)
		self.assertTrue(fake.messages)
		with _FakeSpeech():
			self.commands.script_toggleReportFigures(None)
		self.assertEqual(conf["documentFormatting"]["reportFigures"], before)

	def test_document_cycle(self) -> None:
		with _FakeSpeech():
			start = conf["documentFormatting"]["reportCellBorders"]
			seen = set()
			for _i in range(3):
				self.commands.script_toggleReportCellBorders(None)
				seen.add(conf["documentFormatting"]["reportCellBorders"])
		self.assertEqual(seen, {"off", "styles", "colorsAndStyles"})
		self.assertEqual(conf["documentFormatting"]["reportCellBorders"], start)

	def test_language_switching_cycle(self) -> None:
		sp = conf["speech"]
		states = set()
		with _FakeSpeech():
			for _i in range(3):
				self.commands.script_cycleSpeechAutomaticLanguageSwitching(None)
				states.add((sp["autoLanguageSwitching"], sp["autoDialectSwitching"]))
		self.assertEqual(states, {(False, False), (True, False), (True, True)})

	def test_new_commands_exist(self) -> None:
		for name in (
			"review_currentSymbol",
			"review_startOfSelection",
			"review_endOfSelection",
			"review_moveToStartMarkedForCopy",
			"reviewCursorToStatusLine",
			"toggleSimpleReviewMode",
			"reportReviewCursorLocation",
			"reportCurrentNavigatorObjectLocation",
			"reportCaretLocation",
			"reportFocusObjectLocation",
			"reportDetailsSummary",
			"mouseScrollUp",
			"mouseScrollDown",
			"mouseScrollLeft",
			"mouseScrollRight",
			"toggleMouseAudioCoordinates",
			"toggleMouseTextResolution",
			"activateVisionSettingsDialog",
			"activateMagnifierSettingsDialog",
			"activateWindowsOCRSettings",
			"activateAdvancedSettings",
			"activateReviewCursorDialog",
			"activateBrailleDisplayDialog",
			"activateDefaultDictionaryDialog",
			"activateVoiceDictionaryDialog",
			"activateTemporaryDictionaryDialog",
			"activateSpeechSymbolsDialog",
			"activateInputGesturesDialog",
			"activateAddonsManager",
			"toggleSpeechViewer",
			"toggleBrailleViewer",
			"restart",
			"openUserConfigurationDirectory",
			"log_markStartThenCopy",
			"reportActiveConfigurationProfile",
			"toggleConfigProfileTriggers",
			"toggleKeyboardLayout",
			"reportScreenCurtainState",
			"cycleSpeechAutomaticLanguageSwitching",
			"toggleDelayedCharacterDescriptions",
			"speech_cycleUnicodeNormalization",
			"toggleReportCLDR",
			"firstValueSynthRing",
			"lastValueSynthRing",
			"reportCaretLanguage",
			"sayFromLineStartToCaret",
			"sayFromCaretToLineEnd",
			"reportOrShowFormattingAtReview",
			"reportFormattingAtCaret",
			"showFormattingAtCaret",
		):
			self.assertTrue(callable(getattr(self.cls, "script_" + name, None)), name)

	def test_new_gestures_do_not_steal_existing_ones(self) -> None:
		gestures = dict(self.cls.iterClassGestures())
		expected = {
			"kb:tiresias+d": "reportDetailsSummary",
			"kb:tiresias+shift+f": "reportOrShowFormattingAtReview",
			"kb:tiresias+alt+home": "review_startOfSelection",
			"kb:tiresias+alt+end": "review_endOfSelection",
			"kb:tiresias+shift+f9": "review_moveToStartMarkedForCopy",
			"kb:tiresias+control+w": "activateMagnifierSettingsDialog",
			"kb:tiresias+shift+q": "restart",
			"kb:tiresias+control+shift+f1": "log_markStartThenCopy",
			"kb:tiresias+shift+alt+home": "sayFromLineStartToCaret",
			"kb:tiresias+shift+alt+end": "sayFromCaretToLineEnd",
		}
		for gid, name in expected.items():
			self.assertEqual(gestures.get(normalizeGestureId(gid)), name, gid)
		# Las órdenes de siempre conservan sus teclas.
		self.assertEqual(gestures.get(normalizeGestureId("kb:tiresias+f")), "reportFormatting")
		self.assertEqual(gestures.get(normalizeGestureId("kb:tiresias+t")), "title")

	def test_profile_triggers_toggle(self) -> None:
		with _FakeSpeech():
			self.commands.script_toggleConfigProfileTriggers(None)
			self.assertFalse(conf.triggersEnabled)
			self.commands.script_toggleConfigProfileTriggers(None)
		self.assertTrue(conf.triggersEnabled)

	def test_keyboard_layout_toggle(self) -> None:
		from tiresias.input import core as inputCore

		old = inputCore.manager.updateChain
		inputCore.manager.updateChain = lambda: None
		try:
			before = conf["keyboard"]["layout"]
			with _FakeSpeech():
				self.commands.script_toggleKeyboardLayout(None)
				self.assertNotEqual(conf["keyboard"]["layout"], before)
				self.commands.script_toggleKeyboardLayout(None)
			self.assertEqual(conf["keyboard"]["layout"], before)
		finally:
			inputCore.manager.updateChain = old


class FormattingTests(unittest.TestCase):
	def test_line_spacing_text(self) -> None:
		self.assertEqual(formatting.lineSpacingText("LineSpacingRule: Single; LineSpacing: 1.0pt;"), "sencillo")
		self.assertEqual(formatting.lineSpacingText("LineSpacingRule: Double; LineSpacing: 2.0pt;"), "doble")
		self.assertIn("12", formatting.lineSpacingText("LineSpacingRule: Exactly; LineSpacing: 12pt;"))
		self.assertEqual(formatting.lineSpacingText(None), "")

	def test_describe_line_spacing_change(self) -> None:
		out = formatting.describe({"lineSpacing": "LineSpacingRule: Double; LineSpacing: 2pt;"}, {"lineSpacing": "LineSpacingRule: Single; LineSpacing: 1pt;"})
		self.assertIn("interlineado doble", out)

	def test_same_page_url(self) -> None:
		self.assertTrue(formatting.isSamePageUrl("#seccion", "https://ejemplo.es/a"))
		self.assertTrue(formatting.isSamePageUrl("https://ejemplo.es/a#b", "https://ejemplo.es/a"))
		self.assertFalse(formatting.isSamePageUrl("https://ejemplo.es/otra#b", "https://ejemplo.es/a"))
		self.assertFalse(formatting.isSamePageUrl("https://ejemplo.es/a", "https://ejemplo.es/a"))
		conf["documentFormatting"]["reportLinkType"] = True
		self.assertEqual(formatting.linkTypeText("#x", "https://e.es/"), "en esta página")
		conf["documentFormatting"]["reportLinkType"] = False
		self.assertEqual(formatting.linkTypeText("#x", "https://e.es/"), "")
		conf["documentFormatting"]["reportLinkType"] = True

	def test_cell_borders(self) -> None:
		text = formatting.describeCellBorders([1.0, 3.0, 0, 0], [0, 0xFF, 0, 0])
		self.assertIn("arriba fino", text)
		self.assertIn("abajo grueso rojo", text)
		self.assertNotIn("izquierda", text)
		self.assertEqual(formatting.describeCellBorders([0, 0, 0, 0], []), "")

	def test_line_indentation_and_blank_lines(self) -> None:
		df = conf["documentFormatting"]
		old = (df["reportLineIndentation"], df["ignoreBlankLinesForRLI"])
		try:
			df["reportLineIndentation"] = "speech"
			df["ignoreBlankLinesForRLI"] = False
			formatting.reset()
			self.assertEqual(formatting.lineIndentationSpeech("\tuno"), ["1 tabulador"])
			self.assertEqual(formatting.lineIndentationSpeech("\tdos"), [])
			self.assertEqual(formatting.lineIndentationSpeech(""), ["sin sangría"])
			self.assertEqual(formatting.lineIndentationSpeech("\ttres"), ["1 tabulador"])
			df["ignoreBlankLinesForRLI"] = True
			self.assertEqual(formatting.lineIndentationSpeech(""), [])
			self.assertEqual(formatting.lineIndentationSpeech("\tcuatro"), [])
		finally:
			df["reportLineIndentation"], df["ignoreBlankLinesForRLI"] = old
			formatting.reset()

	def test_containers_follow_toggles(self) -> None:
		df = conf["documentFormatting"]
		self.assertTrue(formatting.shouldReportContainer(Role.DIALOG))
		df["reportFigures"] = False
		self.assertFalse(formatting.shouldReportContainer(Role.FIGURE))
		df["reportFigures"] = True
		self.assertTrue(formatting.shouldReportContainer(Role.FIGURE))

	def test_wanted_keys_include_line_spacing(self) -> None:
		conf["documentFormatting"]["reportLineSpacing"] = True
		try:
			self.assertIn("lineSpacing", formatting._wantedKeys())
		finally:
			conf["documentFormatting"]["reportLineSpacing"] = False


class ClipboardTests(unittest.TestCase):
	def test_classify_key(self) -> None:
		from tiresias import clipboard

		self.assertEqual(clipboard.classifyKey(0x43, frozenset({"control"})), "copy")
		self.assertEqual(clipboard.classifyKey(0x58, frozenset({"control"})), "cut")
		self.assertEqual(clipboard.classifyKey(0x56, frozenset({"control"})), "paste")
		self.assertEqual(clipboard.classifyKey(0x2E, frozenset({"shift"})), "cut")
		self.assertIsNone(clipboard.classifyKey(0x43, frozenset({"control", "shift"})))
		self.assertIsNone(clipboard.classifyKey(0x43, frozenset()))

	def test_change_message(self) -> None:
		from tiresias import clipboard

		self.assertTrue(clipboard.changeMessage("cut", "hola").startswith("Cortado"))
		self.assertTrue(clipboard.changeMessage(None, "hola").startswith("Copiado"))

	def test_confirm_copy_option(self) -> None:
		from tiresias import api, winapi

		oldSet = winapi.setClipboardText
		winapi.setClipboardText = lambda text: True
		try:
			conf["clipboard"]["confirmCopyCommands"] = False
			with _FakeSpeech() as fake:
				api.copyToClip("x", notify=True)
			self.assertEqual(fake.messages, [])
			conf["clipboard"]["confirmCopyCommands"] = True
			with _FakeSpeech() as fake:
				api.copyToClip("x", notify=True)
			self.assertEqual(fake.messages, ["Copiado al portapapeles"])
		finally:
			winapi.setClipboardText = oldSet


class PaletteTests(unittest.TestCase):
	def test_fuzzy_score(self) -> None:
		from tiresias.gui.helpers import fuzzyScore, normalizeForSearch

		hay = normalizeForSearch("Abre las opciones de la lupa — Configuración")
		self.assertGreater(fuzzyScore(hay, "lupa"), 0)
		self.assertGreater(fuzzyScore(hay, "opcines lupa"), 0)  # errata
		self.assertGreater(fuzzyScore(hay, "Configuracion"), 0)  # sin tilde
		self.assertEqual(fuzzyScore(hay, "cortina"), 0)

	def test_filter_entries_ranking_and_keys(self) -> None:
		from tiresias.gui.command_palette import PaletteEntry, filterEntries

		a = PaletteEntry("Visión", "Abre las opciones de la lupa", ["Tiresias+Control+W"], "activateMagnifierSettingsDialog", None, gestureIds=["kb:tiresias+control+w"])
		b = PaletteEntry("Visión", "Activa o desactiva la lupa", [], "toggleMagnifier", None)
		c = PaletteEntry("Voz", "Repite lo último que se dijo", [], "repeat", None)
		res = filterEntries([c, a, b], "lupa")
		self.assertEqual(len(res), 2)
		self.assertTrue(any(e is a for e in res) and any(e is b for e in res))
		self.assertFalse(any(e is c for e in res))
		self.assertEqual(filterEntries([a, b, c], "", ["kb(desktop):tiresias+control+w", "kb:tiresias+control+w"]), [a])


class LogMarkTests(unittest.TestCase):
	def test_mark_survives_buffer_rotation(self) -> None:
		from tiresias import log as logModule

		handler = logModule._MemoryHandler()
		import logging

		rec = logging.LogRecord("x", logging.INFO, "", 0, "antes", None, None)
		handler.emit(rec)
		logModule.markStart()
		self.assertTrue(logModule.hasMark())
		for i in range(3):
			handler.emit(logging.LogRecord("x", logging.INFO, "", 0, f"después {i}", None, None))
		text = logModule.getTextSinceMark()
		self.assertIn("después 0", text)
		self.assertNotIn("antes", text)
		logModule.clearMark()
		self.assertFalse(logModule.hasMark())


class CoreArgsTests(unittest.TestCase):
	def test_replace_and_check_running(self) -> None:
		from tiresias import core

		ns = core.parseArgs([])
		self.assertTrue(ns.replace)
		self.assertFalse(ns.check_running)
		self.assertFalse(core.parseArgs(["--no-replace"]).replace)
		self.assertTrue(core.parseArgs(["--replace"]).replace)
		self.assertTrue(core.parseArgs(["-k"]).check_running)

	def test_restart_clears_safe_mode(self) -> None:
		from tiresias import core

		old = (core.args, core.requestQuit, core._restartRequested)
		try:
			core.args = core.parseArgs(["--safe-mode"])
			core.requestQuit = lambda: None
			core.restart()
			self.assertFalse(core.args.safe_mode)
			core.restart(True)
			self.assertTrue(core.args.safe_mode)
		finally:
			core.args, core.requestQuit, core._restartRequested = old


class SleepModeProfileTests(unittest.TestCase):
	def test_profile_sleeps_foreground_app_and_respects_manual_wake(self) -> None:
		from tiresias.appmodules import handler as appHandler
		from tiresias.input import core as inputCore

		class FakeApp:
			processID = -1
			sleepMode = False

		app = FakeApp()
		oldFg, oldUpdate = appHandler.getForegroundApp, inputCore.manager.updateChain
		appHandler.getForegroundApp = lambda: app
		inputCore.manager.updateChain = lambda: None
		try:
			with _FakeSpeech():
				conf["sleepMode"]["enabled"] = True
				global_commands_extra.applyProfileSleepMode()
				self.assertTrue(app.sleepMode)
				app.sleepMode = False  # el usuario lo despierta
				global_commands_extra.applyProfileSleepMode()
				self.assertFalse(app.sleepMode)
				conf["sleepMode"]["enabled"] = False
				global_commands_extra.applyProfileSleepMode()
				self.assertFalse(app.sleepMode)
				conf["sleepMode"]["enabled"] = True
				global_commands_extra.applyProfileSleepMode()
				self.assertTrue(app.sleepMode)
				conf["sleepMode"]["enabled"] = False
				global_commands_extra.applyProfileSleepMode()
				self.assertFalse(app.sleepMode)
		finally:
			appHandler.getForegroundApp, inputCore.manager.updateChain = oldFg, oldUpdate
			conf["sleepMode"]["enabled"] = False


if __name__ == "__main__":
	unittest.main()
