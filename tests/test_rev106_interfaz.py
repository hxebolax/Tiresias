"""Revisión 1.0.6 (Python 3.14): interfaz, configuración visible, instalación y distribución.

- Todos los paneles de Opciones y los diálogos se construyen sin mostrarse, sin
  letras rápidas repetidas, con anclas F1 que existen en el manual, guardan sin
  cambiar nada y sus campos coinciden con los valores por defecto y la validación.
- Validaciones nuevas: direcciones de actualizaciones, catálogo, IA local y BrlAPI.
- Lista de elementos de los módulos de aplicación: letras rápidas libres («&Explorar»).
- Tienda: filtros con complementos incompatibles instalados, «R&einstalar».
- Ajustes rápidos: listas de casillas y ``afterSave`` del panel.
- Diálogos que no se cerraban (marcadores de texto, posiciones del ratón), Intro
  sobre Cancelar/Cerrar, tutorial (ayuda de entrada y modo de voz).
- Complementos: zip slip con letra de unidad, ``isTooNew``, versiones previas,
  manifiesto con BOM, reinstalar un complemento marcado para eliminar,
  eliminaciones solo al arrancar, estado de complementos fuera de los perfiles.
- Actualizaciones y tienda: SHA-256 obligatorio en la red, ``file://`` de red,
  nombres de descarga, versiones de ``versions`` sin heredar el SHA-256, paquete
  que no corresponde a la entrada.
- ``Tiresias.bat`` (CRLF, códigos de salida), ``setup_cxfreeze.py`` (nada de 3.13,
  no compilar sobre una copia en uso), instalador sin datos privados y versión
  en README, LEEME y novedades.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev106_interfaz``
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_rev106_ui_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()

from tiresias.config import conf  # noqa: E402


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


def _registerEverything() -> None:
	"""Registra los valores por defecto y los paneles como al arrancar."""
	from tiresias.gui import settings as S

	for mod, fn in (
		("tiresias.a11y", None),
		("tiresias.clipboard", None),
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
		try:
			m = importlib.import_module(mod)
			if fn:
				getattr(m, fn)()
		except Exception:
			pass
	from tiresias.gui import ai_dialogs

	S.registerPanel("ai", ai_dialogs.AiPanel.title, ai_dialogs.AiPanel)


class _WxCase(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		import wx

		cls.wx = wx
		cls.app = wx.App.Get() or wx.App(False)
		_registerEverything()

	def labels(self, win, skip=()) -> list[tuple[str, str]]:
		wx = self.wx
		out = []

		def walk(w):
			if w in skip or (isinstance(w, wx.TopLevelWindow) and w is not win) or (w is not win and not w.IsShown()):
				return
			labs = []
			if isinstance(w, (wx.StaticText, wx.Button, wx.CheckBox, wx.RadioButton, wx.ToggleButton, wx.StaticBox)):
				labs.append(w.GetLabel())
			elif isinstance(w, wx.RadioBox):
				labs.append(w.GetLabel())
				labs.extend(w.GetString(i) for i in range(w.GetCount()))
			for lab in labs:
				a = _accel(lab)
				if a:
					out.append((a, lab))
			if isinstance(w, wx.RadioBox):
				return
			for c in w.GetChildren():
				walk(c)

		walk(win)
		return out

	def assertNoDuplicates(self, items, where) -> None:
		seen: dict[str, str] = {}
		dups = []
		for a, lab in items:
			if a in seen:
				dups.append((a, seen[a], lab))
			seen[a] = lab
		self.assertEqual(dups, [], where)


# ====================================================================== Opciones
class SettingsPanelsTests(_WxCase):
	def test_every_panel_builds_saves_and_has_help(self) -> None:
		from tiresias.gui import context_help as CH
		from tiresias.gui import settings as S

		ids = CH.manualIds()
		self.assertTrue(ids, "sin manual")
		dlg = S.SettingsDialog(None)
		try:
			top = self.labels(dlg, skip=(dlg.container,))
			for pid in S.getPanelIds():
				with self.subTest(panel=pid):
					dlg.selectCategory(pid)
					panel = dlg.getPanel(pid)
					self.assertIsNotNone(panel, pid)
					self.assertNoDuplicates(top + self.labels(panel), pid)
					# F1: la categoría y cada opción con ayuda tienen su ancla en el manual.
					self.assertIn(CH.categoryAnchor(pid), ids)
					for anchor, sec, key in CH.panelOptions(panel):
						self.assertIn(anchor, ids, f"{pid}: {sec}.{key}")
						self.assertEqual(CH.anchorFor(pid, (sec, key)), anchor)
					with mock.patch.object(S, "showError"):
						self.assertTrue(panel.isValid(), pid)
			# Guardar sin tocar nada no cambia ninguna opción ni lanza errores.
			for pid, panel in dlg._panels.items():
				if isinstance(panel, S.ConfigPanel):
					before = {k: panel._readControl(b) for k, b in panel._bound.items()}
					with mock.patch.object(type(panel), "afterSave") as after:
						panel.onSave()
					after.assert_not_called()
					self.assertEqual(before, {k: b.original for k, b in panel._bound.items()}, pid)
		finally:
			for panel in dlg._panels.values():
				try:
					panel.onDiscard()
				except Exception:
					pass
			dlg.Destroy()

	def test_fields_match_defaults_and_validation(self) -> None:
		from tiresias.config import validation
		from tiresias.gui import settings as S

		dlg = S.SettingsDialog(None)
		problems = []
		try:
			for pid in S.getPanelIds():
				dlg.selectCategory(pid)
				panel = dlg.getPanel(pid)
				if not isinstance(panel, S.ConfigPanel):
					continue
				for (sec, key), b in panel._bound.items():
					f = b.field
					d = conf.defaults.get(sec, {})
					if not isinstance(d, dict) or key not in d:
						problems.append(f"{pid}: {sec}.{key} sin valor por defecto")
						continue
					if not validation.isValidValue(sec, key, panel._readControl(b), conf.defaults):
						problems.append(f"{pid}: {sec}.{key} el control da un valor no válido")
					rng = validation.RANGES.get((sec, key))
					if f.kind in ("int", "slider") and rng and (f.minVal < rng[0] or f.maxVal > rng[1]):
						problems.append(f"{pid}: {sec}.{key} rango {f.minVal}-{f.maxVal} fuera de {rng}")
					ch = validation.CHOICES.get((sec, key))
					if f.kind == "choice" and ch and set(b.values) - set(ch):
						problems.append(f"{pid}: {sec}.{key} ofrece valores no válidos {set(b.values) - set(ch)}")
		finally:
			dlg.Destroy()
		self.assertEqual(problems, [])

	def _panel(self, pid: str):
		from tiresias.gui import settings as S

		dlg = S.SettingsDialog(None, pid)
		self.addCleanup(dlg.Destroy)
		return dlg.getPanel(pid)

	def test_url_validation(self) -> None:
		from tiresias.gui import settings as S

		panel = self._panel("updates")
		with mock.patch.object(S, "showError") as err:
			self.assertTrue(panel.isValid())
			for key, section in (("serverUrl", "update"), ("checkUrl", "update"), ("catalogUrl", "addons")):
				ctrl = panel.getControl(key, section)
				for bad in ("servidor.com/tiresias", "ftp://x/y", "https://"):
					ctrl.SetValue(bad)
					self.assertFalse(panel.isValid(), f"{key}={bad}")
				for good in ("", "https://ejemplo.org/tiresias", "file:///C:/web", "C:\\web\\Tiresias", "\\\\servidor\\web"):
					ctrl.SetValue(good)
					self.assertTrue(panel.isValid(), f"{key}={good}")
			self.assertTrue(err.called)

	def test_ai_local_url_validation(self) -> None:
		from tiresias.gui import settings as S

		panel = self._panel("ai")
		ctrl = panel.getControl("localUrl")
		with mock.patch.object(S, "showError"):
			ctrl.SetValue("localhost:11434/v1")
			self.assertFalse(panel.isValid())
			ctrl.SetValue("http://localhost:11434/v1")
			self.assertTrue(panel.isValid())

	def test_brlapi_server_validation(self) -> None:
		from tiresias.gui import settings as S

		# El servidor BrlAPI está en la categoría «Braille», grupo «Conexión de la línea».
		panel = self._panel("braille")
		ctrl = panel.getControl("brlapiServer", "brailleDisplays")
		with mock.patch.object(S, "showError"):
			ctrl.SetValue("equipo:abc")
			self.assertFalse(panel.isValid())
			for good in ("127.0.0.1:4101", ":0", "equipo", "[::1]:4101"):
				ctrl.SetValue(good)
				self.assertTrue(panel.isValid(), good)

	def test_existing_validations(self) -> None:
		from tiresias.gui import settings as S

		with mock.patch.object(S, "showError"):
			kb = self._panel("keyboard")
			for k in ("useInsertAsModifier", "useNumpadInsertAsModifier", "useCapsLockAsModifier"):
				kb.setControlValue(k, False)
			self.assertFalse(kb.isValid())
			mouse = self._panel("mouse")
			mouse.setControlValue("audioCoordinatesMinPitch", 5000)
			mouse.setControlValue("audioCoordinatesMaxPitch", 100)
			self.assertFalse(mouse.isValid())
			vision = self._panel("vision")
			vision.setControlValue("highlightColor", "rojo")
			self.assertFalse(vision.isValid())
			nav = self._panel("documentNavigation")
			nav.setControlValue("textParagraphRegex", "([")
			self.assertFalse(nav.isValid())

	def test_policy_fixed_urls_are_disabled(self) -> None:
		from tiresias.config import policy

		with mock.patch.object(policy.policy, "data", {"distributionUrl": "https://empresa/tiresias"}):
			panel = self._panel("updates")
			self.assertFalse(panel.getControl("serverUrl", "update").IsEnabled())
			self.assertTrue(panel.getControl("catalogUrl", "addons").IsEnabled())


class UrlProblemTests(unittest.TestCase):
	def test_urls(self) -> None:
		from tiresias.gui.helpers import urlProblem

		self.assertIsNone(urlProblem(""))
		self.assertIsNone(urlProblem("https://a.b/c"))
		self.assertIsNotNone(urlProblem("a.b/c"))
		self.assertIsNotNone(urlProblem("file:///C:/x"))
		self.assertIsNone(urlProblem("file:///C:/x", allowLocal=True))
		self.assertIsNone(urlProblem("C:\\x", allowLocal=True))
		self.assertIsNotNone(urlProblem("x\\y", allowLocal=True))


# ====================================================================== diálogos
class DialogsBuildTests(_WxCase):
	NO_ARGS = (
		("audio_dialogs", "MixerDialog"),
		("braille_display_dialog", "BrailleDisplayDialog"),
		("config_dialogs", "ProfilesDialog"),
		("config_dialogs", "AddonsDialog"),
		("config_dialogs", "InputGesturesDialog"),
		("config_dialogs", "SymbolsDialog"),
		("config_dialogs", "WelcomeDialog"),
		("config_dialogs", "AboutDialog"),
		("history_dialogs", "SpeechHistoryDialog"),
		("history_dialogs", "ClipboardHistoryDialog"),
		("installer_dialogs", "InstallDialog"),
		("log_viewer", "LogViewerDialog"),
		("nvda_import_dialog", "NvdaImportDialog"),
		("piper_dialog", "VoiceManagerDialog"),
		("productivity_dialogs", "NotificationHistoryDialog"),
		("productivity_dialogs", "WatchesDialog"),
		("remote_dialogs", "ConnectDialog"),
		("settings", "SynthSelectionDialog"),
		("speech_dialogs", "PhoneticAlphabetDialog"),
		("speech_dialogs", "VoiceSchemesDialog"),
		("speech_dialogs", "RoleTemplatesDialog"),
		("speech_viewer", "SpeechViewerFrame"),
		("system_dialogs", "QuickSettingsDialog"),
		("system_dialogs", "LabelsManagerDialog"),
		("system_dialogs", "AddonStoreDialog"),
		("system_dialogs", "CreatePortableDialog"),
		("tutorial", "TutorialDialog"),
	)

	def _check(self, name: str, factory) -> None:
		with self.subTest(dialog=name):
			try:
				win = factory()
			except Exception as e:  # noqa: BLE001
				self.fail(f"{name}: {e!r}")
			try:
				self.assertNoDuplicates(self.labels(win), name)
			finally:
				win.Destroy()

	def test_dialogs_without_arguments(self) -> None:
		for mod, cls in self.NO_ARGS:
			klass = getattr(importlib.import_module(f"tiresias.gui.{mod}"), cls)
			params = [p for p in list(inspect.signature(klass.__init__).parameters.values())[1:] if p.default is p.empty]
			self._check(cls, (lambda k=klass, n=len(params): k(*([None] * n))))

	def test_dialogs_with_arguments(self) -> None:
		from tiresias.gui import (
			ai_dialogs,
			app_dialogs,
			braille_panels,
			braille_viewer,
			browse_dialogs,
			command_palette,
			config_dialogs,
			dialogs,
			gesture_tools,
			message_dialog,
			mouse_positions,
			ocr_viewer,
			productivity_dialogs,
			python_console,
			remote_dialogs,
			system_dialogs,
		)
		from tiresias.global_commands import GlobalCommands
		from tiresias.productivity.notifications import Rule

		wx = self.wx
		frame = wx.Frame(None)
		self.addCleanup(frame.Destroy)

		def noop(*a, **k):
			pass

		cases = [
			("ChatDialog", lambda: ai_dialogs.ChatDialog(mock.MagicMock(title="t", history=[], messages=[]))),
			("OrderConfirmDialog", lambda: ai_dialogs.OrderConfirmDialog("t", "p", noop)),
			("AgentConfirmDialog", lambda: ai_dialogs.AgentConfirmDialog("d", noop)),
			("ItemListDialog", lambda: app_dialogs.ItemListDialog("t", [("Uno", lambda: [("a", 1)]), ("Dos", lambda: [])], [app_dialogs.Action("&Ir", noop, default=True)], refreshable=True)),
			("RoleAbbreviationsDialog", lambda: braille_panels.RoleAbbreviationsDialog(frame, {})),
			("BrailleViewerFrame", lambda: braille_viewer.BrailleViewerFrame(40)),
			("ElementsListDialog", lambda: browse_dialogs.ElementsListDialog(mock.MagicMock(), {"link": [("e", 0, 1)]}, 0)),
			("FindDialog", lambda: browse_dialogs.FindDialog(mock.MagicMock(), "x", ["x"], {})),
			("SkimDialog", lambda: browse_dialogs.SkimDialog(mock.MagicMock())),
			("FlexWebDialog", lambda: browse_dialogs.FlexWebDialog(mock.MagicMock(), "ejemplo.com")),
			("CommandPaletteDialog", lambda: command_palette.CommandPaletteDialog([])),
			("NewProfileDialog", lambda: config_dialogs.NewProfileDialog(frame, "notepad")),
			("TriggersDialog", lambda: config_dialogs.TriggersDialog(frame, "notepad")),
			("DictEntryDialog", lambda: config_dialogs.DictEntryDialog(frame, "t")),
			("SpeechDictDialog", lambda: config_dialogs.SpeechDictDialog(None, "default")),
			("AskTextDialog", lambda: dialogs.AskTextDialog("t", "&Texto:", "", noop)),
			("BrowseableMessageDialog", lambda: dialogs.BrowseableMessageDialog("texto", "t")),
			("ChooseDialog", lambda: dialogs.ChooseDialog(None, "t", "&Elige:", ["a"], noop)),
			("MessageDialog", lambda: message_dialog.MessageDialog(None, "m", "t", wx.YES_NO | wx.CANCEL)),
			("PositionsDialog", lambda: mouse_positions.PositionsDialog("notepad", ["a"])),
			("OcrViewerDialog", lambda: ocr_viewer.OcrViewerDialog(mock.MagicMock(title="t", lines=[], words=[]))),
			("TextBookmarksDialog", lambda: productivity_dialogs.TextBookmarksDialog(mock.MagicMock(), [(0, "uno")])),
			("RuleDialog", lambda: productivity_dialogs.RuleDialog(None, Rule(), True)),
			("PythonConsoleFrame", lambda: python_console.PythonConsoleFrame(None, None)),
			("CertificateDialog", lambda: remote_dialogs.CertificateDialog("h", "AA", noop)),
			("UpdateDialog", lambda: system_dialogs.UpdateDialog(mock.MagicMock(version="9.9.9", notes="n", notesUrl="", url="u", size=1, channel="estable"))),
			("ScriptGesturesDialog", lambda: gesture_tools.ScriptGesturesDialog(None, GlobalCommands, "showGui", "Menú", ["kb:tiresias+m"])),
		]
		for name, factory in cases:
			self._check(name, factory)

	def test_item_list_moves_clashing_accelerators(self) -> None:
		"""PowerPoint usa «&Explorar», que chocaba con «&Elementos:»."""
		from tiresias.gui import app_dialogs

		dlg = app_dialogs.ItemListDialog("t", [("Ecuaciones", lambda: [])], [app_dialogs.Action("&Explorar", lambda p: None, default=True), app_dialogs.Action("&Cerrar todo", lambda p: None)])
		try:
			self.assertNoDuplicates(self.labels(dlg), "ItemListDialog")
		finally:
			dlg.Destroy()

	def test_free_accelerator(self) -> None:
		from tiresias.gui.app_dialogs import freeAccelerator

		used = {"f", "e", "c"}
		self.assertEqual(freeAccelerator("&Explorar", used), "E&xplorar")
		self.assertEqual(freeAccelerator("&Ir", used), "&Ir")
		self.assertIn("x", used)
		self.assertEqual(freeAccelerator("Tom && Jerry", set()), "&Tom && Jerry")
		self.assertEqual(freeAccelerator("&ee", {"e"}), "ee")

	def test_closing_dialogs_destroys_them(self) -> None:
		from tiresias.gui import mouse_positions, productivity_dialogs
		from tiresias.gui.helpers import isAlive

		for dlg in (productivity_dialogs.TextBookmarksDialog(mock.MagicMock(), [(0, "uno")]), mouse_positions.PositionsDialog("notepad", ["a"])):
			with self.subTest(dialog=type(dlg).__name__):
				dlg.Close()
				self.wx.GetApp().ProcessPendingEvents()
				self.wx.Yield()
				self.assertFalse(isAlive(dlg) and dlg.IsShown())
				self.assertFalse(isAlive(dlg))

	def test_choose_dialog_enter_on_cancel_does_not_accept(self) -> None:
		from tiresias.gui import dialogs

		chosen = []
		dlg = dialogs.ChooseDialog(None, "t", "&Elige:", ["a", "b"], chosen.append)
		evt = mock.MagicMock()
		evt.GetKeyCode.return_value = self.wx.WXK_RETURN
		cancel = dlg.FindWindow(self.wx.ID_CANCEL)
		with mock.patch.object(self.wx.Window, "FindFocus", return_value=cancel):
			dlg._onCharHook(evt)
		self.assertEqual(chosen, [])
		evt.Skip.assert_called_once()
		with mock.patch.object(self.wx.Window, "FindFocus", return_value=dlg.list), mock.patch.object(self.wx, "CallLater", side_effect=lambda ms, f, *a: f(*a)) as later:
			dlg._onCharHook(evt)
		self.assertEqual(chosen, ["a"])
		# La acción espera a que el foco vuelva a la ventana anterior.
		self.assertEqual(later.call_args[0][0], 200)

	def test_ask_text_cancel_callback(self) -> None:
		from tiresias.gui import dialogs

		cancelled = []
		dlg = dialogs.AskTextDialog("t", "&Texto:", "", lambda v: None, lambda: cancelled.append(True))
		dlg.onCancel(None)
		self.assertEqual(cancelled, [True])

	def test_store_filters_and_reinstall_label(self) -> None:
		from tiresias.gui import system_dialogs

		dlg = system_dialogs.AddonStoreDialog.__new__(system_dialogs.AddonStoreDialog)
		with mock.patch.object(system_dialogs.AddonStoreDialog, "_load"):
			dlg.__init__()
		try:
			from tiresias import addon_store

			inst = addon_store.CatalogEntry(id="inst", name="Instalado", version="1.0", minApiVersion="9.0")
			free = addon_store.CatalogEntry(id="libre", name="Libre", version="1.0")
			installed = mock.MagicMock(version="1.0")
			p = mock.patch.object(addon_store.CatalogEntry, "installedAddon", lambda self: installed if self.id == "inst" else None)
			p.start()
			self.addCleanup(p.stop)
			self.assertEqual(inst.status(), "incompatible")
			dlg.entries = [inst, free]
			kinds = [k for k, _l in system_dialogs._STORE_FILTERS]
			dlg.filter.SetSelection(kinds.index("installed"))
			dlg._refresh()
			self.assertEqual([e.name for e in dlg.visible], ["Instalado"])
			dlg.filter.SetSelection(kinds.index("available"))
			dlg._refresh()
			self.assertEqual([e.name for e in dlg.visible], ["Libre"])
			dlg.installButton.SetLabel("R&einstalar")
			self.assertNoDuplicates(self.labels(dlg), "tienda")
		finally:
			dlg.Destroy()

	def test_quick_settings_checklist(self) -> None:
		from tiresias.gui import system_dialogs

		dlg = system_dialogs.QuickSettingsDialog()
		try:
			entries = [e for e in dlg.entries if e.field.kind == "checklist"]
			self.assertTrue(entries)
			e = entries[0]
			dlg.filter.SetValue(e.field.key)
			idx = dlg.visible.index(e)
			dlg.list.Select(idx)
			dlg._buildEditor()
			self.assertIsInstance(dlg.editor, self.wx.CheckListBox)
			self.assertEqual(dlg._readEditor(e), [v for v in dlg.editorValues if v in (e.value() or [])])
		finally:
			dlg.close()

	def test_quick_settings_runs_panel_after_save(self) -> None:
		from tiresias.gui import settings as S
		from tiresias.gui import system_dialogs

		entry = next(e for e in system_dialogs.collectSettings() if (e.section, e.field.key) == ("braille", "tetherTo"))
		cls = S._panels[entry.panelId][1]
		with mock.patch.object(cls, "afterSave") as after, mock.patch.object(system_dialogs, "applySettingChange") as legacy:
			system_dialogs.applyPanelChange(entry, "auto", "focus")
		after.assert_called_once()
		self.assertEqual(after.call_args[0][1], {("braille", "tetherTo"): ("auto", "focus")})
		legacy.assert_not_called()

	def test_tutorial_steps_wait_for_normal_state(self) -> None:
		from tiresias.gui import tutorial
		from tiresias.input import core as inputCore
		from tiresias.speech import api as speechApi

		with mock.patch.object(inputCore.manager, "inputHelp", True):
			self.assertFalse(tutorial.TutorialDialog._stepDone("toggleInputHelp"))
		with mock.patch.object(inputCore.manager, "inputHelp", False):
			self.assertTrue(tutorial.TutorialDialog._stepDone("toggleInputHelp"))
		with mock.patch.object(speechApi, "getSpeechMode", return_value=speechApi.SpeechMode.onDemand):
			self.assertFalse(tutorial.TutorialDialog._stepDone("speechMode"))
		with mock.patch.object(speechApi, "getSpeechMode", return_value=speechApi.SpeechMode.talk):
			self.assertTrue(tutorial.TutorialDialog._stepDone("speechMode"))
		self.assertTrue(tutorial.TutorialDialog._stepDone("reportCurrentLine"))

	def test_python_console_blocked_by_policy(self) -> None:
		from tiresias.config import policy
		from tiresias.gui import helpers, python_console

		with mock.patch.object(policy.policy, "data", {"allowPythonConsole": False}), mock.patch.object(helpers, "speakMessage") as speak, mock.patch.object(python_console, "runOnGui") as run:
			python_console.show()
		run.assert_not_called()
		speak.assert_called_once()


# ====================================================================== complementos
def _makePackage(path: str, manifest: dict | bytes, extra: dict[str, bytes] | None = None) -> str:
	with zipfile.ZipFile(path, "w") as z:
		z.writestr("manifest.json", manifest if isinstance(manifest, bytes) else json.dumps(manifest))
		for name, data in (extra or {}).items():
			z.writestr(name, data)
	return path


class AddonsTests(unittest.TestCase):
	def setUp(self) -> None:
		from tiresias import addons

		self.addons = addons
		self.tmp = tempfile.mkdtemp(prefix="rev106_addons_")
		self.addCleanup(shutil.rmtree, self.tmp, True)
		self.base = os.path.join(self.tmp, "addons")
		os.makedirs(self.base)
		p = mock.patch.object(paths, "addonsDir", return_value=self.base)
		p.start()
		self.addCleanup(p.stop)

	def test_zip_slip_with_drive_letter(self) -> None:
		outside = os.path.join(self.tmp, "fuera.txt")
		pkg = _makePackage(os.path.join(self.tmp, "a.tiresias-addon"), {"id": "malo", "version": "1"}, {outside.replace("\\", "/"): b"x"})
		with self.assertRaises(ValueError):
			self.addons.installFromFile(pkg)
		self.assertFalse(os.path.exists(outside))
		self.assertFalse(self.addons._isSafeMember("C:/x"))
		self.assertFalse(self.addons._isSafeMember("C:x"))
		self.assertFalse(self.addons._isSafeMember("a/../../x"))
		self.assertTrue(self.addons._isSafeMember("appModules/x.py"))

	def test_manifest_with_bom_and_reinstall_after_removal(self) -> None:
		addons = self.addons
		pkg = _makePackage(os.path.join(self.tmp, "ok.tiresias-addon"), b"\xef\xbb\xbf" + json.dumps({"id": "ok", "version": "1.0"}).encode())
		addon = addons.installFromFile(pkg)
		self.assertEqual(addon.id, "ok")
		self.assertIsNotNone(addons._readManifest(os.path.join(self.base, "ok")))
		addons.markForRemoval("ok")
		self.assertIn("ok", addons.pendingRemovals())
		addons.installFromFile(_makePackage(os.path.join(self.tmp, "ok2.tiresias-addon"), {"id": "ok", "version": "2.0"}))
		self.assertNotIn("ok", addons.pendingRemovals())
		addons._processPending()
		self.assertTrue(os.path.isdir(os.path.join(self.base, "ok")))
		self.assertFalse([n for n in os.listdir(self.base) if n.endswith(".tmp")])

	def test_pending_removals_only_once(self) -> None:
		addons = self.addons
		with mock.patch.object(addons, "_pendingProcessed", False), mock.patch.object(addons, "_processPending") as proc, mock.patch.object(addons, "discover", return_value=[]):
			for _i in range(2):
				try:
					addons.loadAll()
				except Exception:
					pass
		self.assertEqual(proc.call_count, 1)

	def test_versions(self) -> None:
		addons = self.addons
		self.assertFalse(addons.Addon(self.tmp, {"id": "x", "minApiVersion": "1.0.0"}).isTooNew)
		self.assertTrue(addons.Addon(self.tmp, {"id": "x", "minApiVersion": "1.1"}).isTooNew)
		self.assertEqual(addons.compareVersions("1.1.0", "1.1.0b1"), 1)
		self.assertEqual(addons.compareVersions("1.0.0.2", "1.0.0.1"), 1)
		self.assertEqual(addons.compareVersions("1.0", "1.0.0"), 0)

	def test_addon_state_is_not_stored_in_profiles(self) -> None:
		name = "rev106perfil"
		if name not in conf.profiles:
			conf.createProfile(name)
		self.addCleanup(lambda: conf.deleteProfile(name) if name in conf.profiles else None)
		conf.profiles[name].data.setdefault("addons", {})["disabled"] = ["viejo"]
		old = conf.manualProfile
		conf.manualProfile = name
		try:
			self.addons.setEnabled("whatsapp", False)
			self.assertIn("whatsapp", conf["addons"]["disabled"])
			self.assertIn("whatsapp", conf.base["addons"]["disabled"])
			self.assertNotIn("disabled", conf.profiles[name].data.get("addons", {}))
		finally:
			conf.manualProfile = old
			self.addons.setEnabled("whatsapp", True)


class UpdatesAndStoreTests(unittest.TestCase):
	def test_file_url_and_checksum(self) -> None:
		from tiresias import updates

		self.assertEqual(updates.fileUrlPath("file://servidor/compartida/a.json"), "\\\\servidor\\compartida\\a.json")
		self.assertEqual(updates.fileUrlPath("file:///C:/x/a.json"), "C:\\x\\a.json")
		with self.assertRaises(ValueError):
			updates.requireChecksum("https://x/a.exe", "", "a")
		updates.requireChecksum("https://x/a.exe", "abc", "a")
		updates.requireChecksum("C:\\x\\a.exe", "", "a")
		updates.requireChecksum("file:///C:/x/a.exe", "", "a")

	def test_download_name_is_sanitized(self) -> None:
		from tiresias import updates

		info = updates.UpdateInfo(version="9.9", url="https://x/descargas/a%2F..%2F..%2Fmalo.exe", sha256="00")
		with mock.patch.object(updates, "download", side_effect=lambda url, dest, *a, **k: dest) as dl, mock.patch.object(updates, "_cleanDownloadDir"):
			dest = updates.downloadUpdate(info)
		self.assertEqual(os.path.dirname(dest), updates.downloadDir())
		self.assertEqual(os.path.basename(dest), "malo.exe")
		dl.assert_called_once()
		with self.assertRaises(ValueError):
			updates.downloadUpdate(updates.UpdateInfo(version="9.9", url="https://x/a.exe"))

	def test_prepare_bad_portable_package(self) -> None:
		from tiresias import updates

		tmp = tempfile.mkdtemp(prefix="rev106_upd_")
		self.addCleanup(shutil.rmtree, tmp, True)
		bad = os.path.join(tmp, "a.zip")
		with open(bad, "wb") as f:
			f.write(b"no es un zip")
		with mock.patch.object(updates, "copyKind", return_value="portable"):
			with self.assertRaises(ValueError):
				updates.preparePackage(bad)
		self.assertIsNone(updates.preparePackage(os.path.join(tmp, "a.exe")))

	def test_catalog_versions_do_not_inherit_package_data(self) -> None:
		from tiresias import addon_store

		item = {"id": "x", "version": "2.0", "minApiVersion": "9.0", "url": "x-2.0.tiresias-addon", "sha256": "nuevo", "size": 10, "versions": [{"version": "2.0", "minApiVersion": "9.0"}, {"version": "1.0", "minApiVersion": "1.0", "url": "x-1.0.tiresias-addon"}]}
		best = addon_store._bestVersion(item)
		self.assertEqual(best["version"], "1.0")
		self.assertNotIn("sha256", best)
		self.assertEqual(best["url"], "x-1.0.tiresias-addon")

	def test_store_requires_checksum_and_matching_package(self) -> None:
		from tiresias import addon_store

		entry = addon_store.CatalogEntry(id="whatsapp", name="WhatsApp", version="1.0", url="https://x/w.tiresias-addon")
		with self.assertRaises(ValueError):
			addon_store.downloadPackage(entry)
		tmp = tempfile.mkdtemp(prefix="rev106_store_")
		self.addCleanup(shutil.rmtree, tmp, True)
		other = _makePackage(os.path.join(tmp, "o.tiresias-addon"), {"id": "otro", "version": "1.0"})
		entry.sha256 = "00"
		with mock.patch.object(addon_store, "downloadPackage", return_value=other), mock.patch("tiresias.addons.installFromFile") as inst:
			with self.assertRaises(ValueError):
				addon_store.installEntry(entry)
		inst.assert_not_called()


class ConfigGlobalTests(unittest.TestCase):
	def test_set_global_writes_base_and_clears_profiles(self) -> None:
		name = "rev106global"
		if name not in conf.profiles:
			conf.createProfile(name)
		self.addCleanup(lambda: conf.deleteProfile(name) if name in conf.profiles else None)
		conf.profiles[name].data["update"] = {"lastCheck": 5}
		old = conf.manualProfile
		conf.manualProfile = name
		try:
			conf.setGlobal("update", "lastCheck", 1234)
			self.assertEqual(conf["update"]["lastCheck"], 1234)
			self.assertEqual(conf.base["update"]["lastCheck"], 1234)
			self.assertNotIn("lastCheck", conf.profiles[name].data["update"])
		finally:
			conf.manualProfile = old


# ====================================================================== herramientas y documentos
class BatchFileTests(unittest.TestCase):
	BAT = os.path.join(ROOT, "Tiresias.bat")

	def _text(self) -> bytes:
		with open(self.BAT, "rb") as f:
			return f.read()

	def test_crlf_and_ascii(self) -> None:
		data = self._text()
		self.assertEqual(data.count(b"\n"), data.count(b"\r\n"), "finales de línea CRLF")
		self.assertNotIn(b"\r\r", data)
		self.assertTrue(all(b < 128 for b in data), "solo ASCII (cmd y chcp)")

	def test_every_option_has_its_label(self) -> None:
		text = self._text().decode("ascii")
		m = re.search(r"for %%o in \(([^)]*)\) do", text)
		self.assertIsNotNone(m)
		for opt in m.group(1).split() + ["publicar"]:
			self.assertRegex(text, rf"(?mi)^:{opt}\r?$", opt)
		for label in re.findall(r"call :(\w+)", text):
			self.assertRegex(text, rf"(?mi)^:{label}\r?$", label)
		self.assertIn("PYVER=3.14", text)
		self.assertNotIn(">=(3,12)", text)

	@unittest.skipUnless(sys.platform == "win32", "Windows")
	def test_exit_codes(self) -> None:
		"""Las opciones que fallan devuelven 1 (antes «exit /b» dentro de un bloque daba 0)."""
		for args in (["opcionrara"], ["importarnvda", "raro"]):
			with self.subTest(args=args):
				r = subprocess.run(["cmd", "/c", self.BAT, *args], stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
				self.assertEqual(r.returncode, 1, r.stdout.decode("cp850", "replace"))


class FreezeAndInstallerTests(unittest.TestCase):
	def test_no_python313_leftovers(self) -> None:
		for rel in ("setup_cxfreeze.py", "Tiresias.bat", "requirements.txt", os.path.join("tools", "build_installer.py"), os.path.join("tools", "build_data.py")):
			with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
				text = f.read()
			with self.subTest(file=rel):
				self.assertNotIn("python313", text.lower())
				self.assertNotIn("msilib", text)
				self.assertNotRegex(text, r"3\.13\b")

	def test_running_from_dist_detection(self) -> None:
		sys.path.insert(0, ROOT)
		try:
			import setup_cxfreeze
		finally:
			sys.path.remove(ROOT)
		import psutil

		here = os.path.dirname(psutil.Process().exe())
		pids = setup_cxfreeze.runningFromDist(here)
		self.assertIn(os.getpid(), pids)
		self.assertEqual(setup_cxfreeze.runningFromDist(tempfile.mkdtemp(prefix="rev106_dist_")), [])

	def test_installer_zip_excludes_private_data(self) -> None:
		sys.path.insert(0, os.path.join(ROOT, "tools"))
		try:
			import build_installer
		finally:
			sys.path.remove(os.path.join(ROOT, "tools"))
		prog = tempfile.mkdtemp(prefix="rev106_prog_")
		self.addCleanup(shutil.rmtree, prog, True)
		for rel in ("Tiresias.exe", "data/voices/es/es.onnx", "data/speechDicts/voices/x.json", "data/speechDicts/default.json", "data/addons/pending.json", "systemConfig/config.json", "data/config/config.json", "data/symbols/es.json", "instalado.json"):
			p = os.path.join(prog, *rel.split("/"))
			os.makedirs(os.path.dirname(p), exist_ok=True)
			with open(p, "w") as f:
				f.write("x")
		out = os.path.join(prog, "..", os.path.basename(prog) + ".zip")
		self.addCleanup(lambda: os.path.exists(out) and os.remove(out))
		build_installer.makeZip(out, prog)
		with zipfile.ZipFile(out) as z:
			names = {n.replace("\\", "/") for n in z.namelist()}
		self.assertEqual(names, {"Tiresias.exe", "data/speechDicts/default.json", "data/symbols/es.json"})


class DocsTests(unittest.TestCase):
	def test_version_everywhere(self) -> None:
		import tiresias

		v = tiresias.VERSION
		with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
			self.assertIn(f"Versión actual: **{v}**", f.read())
		with open(os.path.join(ROOT, "LEEME.txt"), encoding="utf-8") as f:
			self.assertTrue(f.readline().startswith(f"TIRESIAS {v} "))
		with open(os.path.join(ROOT, "docs", "novedades.html"), encoding="utf-8") as f:
			news = f.read()
		anchor = "v" + v.replace(".", "-")
		self.assertIn(f'id="{anchor}"', news)
		self.assertIn(f'href="#{anchor}"', news)

	def test_readme_lists_every_bat_option(self) -> None:
		with open(os.path.join(ROOT, "Tiresias.bat"), encoding="ascii") as f:
			bat = f.read()
		with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
			readme = f.read()
		opts = re.search(r"for %%o in \(([^)]*)\) do", bat).group(1).split() + ["publicar"]
		for opt in opts:
			self.assertIn(f"`{opt}", readme, opt)

	def test_architecture_sections_are_numbered_once(self) -> None:
		with open(os.path.join(ROOT, "docs", "arquitectura.md"), encoding="utf-8") as f:
			nums = [int(m) for m in re.findall(r"(?m)^## (\d+)\. ", f.read())]
		self.assertEqual(nums, list(range(1, len(nums) + 1)))


if __name__ == "__main__":
	unittest.main()
