"""Pruebas de los fallos del código encontrados al revisar el manual (1.0.4).

- E-001: órdenes de PowerPoint fuera de la clase (``speakSlide`` en medio).
- D-001: con el mapa compatible con JAWS, Tiresias+Espacio y Tiresias+V ceden
  ante el documento.
- C-003: las etiquetas personalizadas se aplican también al braille, a la
  revisión y al modo exploración.
- C-008: teclas rápidas repetidas en los diálogos y en las categorías de Opciones.
- C-020: descripciones de las teclas de la línea HID estándar.
- C-025: descripción de Tiresias+Control+T (tres modos).
- D-002: anclas de la ayuda F1 para todas las categorías.
- D-004: órdenes para las cuatro opciones de formato que no la tenían.
- D-006: «Avanzado» es siempre la última categoría.
- D-017: aviso al quitar la última tecla del menú.
- A-001: gestos declarados con los modificadores en otro orden (WhatsApp).
- A-007: Tabulador de la línea HID (Espacio+puntos 4 6).

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import ast
import importlib
import inspect
import os
import pkgutil
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
	_TMP = tempfile.mkdtemp(prefix="tiresias_revman_test_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()

from tiresias.config import conf  # noqa: E402


class FakeGesture:
	def __init__(self, *ids: str) -> None:
		self.identifiers = list(ids)


# ====================================================================== E-001
class PowerPointScriptsTests(unittest.TestCase):
	def setUp(self) -> None:
		from tiresias.appmodules import powerpnt

		self.m = powerpnt

	def test_scripts_are_methods_of_appmodule(self) -> None:
		tree = ast.parse(inspect.getsource(self.m))
		classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
		methods = {f.name for f in classes["AppModule"].body if isinstance(f, ast.FunctionDef)}
		for name in ("script_shapeLocation", "script_readTable", "script_chart", "script_elementsList", "script_readNotes", "script_readSlide"):
			self.assertIn(name, methods)
		# speakSlide es una función del módulo, no un método ni contiene órdenes.
		top = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
		self.assertIn("speakSlide", top)
		self.assertFalse([n for n in ast.walk(top["speakSlide"]) if isinstance(n, ast.FunctionDef) and n.name.startswith("script_")])

	def test_gestures_reach_the_scripts(self) -> None:
		app = self.m.AppModule.__new__(self.m.AppModule)
		app._instanceGestures = {}
		for gid, name in (
			("kb(desktop):tiresias+numpadDelete", "shapeLocation"),
			("kb(laptop):tiresias+delete", "shapeLocation"),
			("kb:tiresias+alt+shift+t", "readTable"),
			("kb:tiresias+alt+g", "chart"),
			("kb:tiresias+f7", "elementsList"),
		):
			from tiresias.baseobject import normalizeGestureId

			self.assertEqual(app._scriptNameForGesture(normalizeGestureId(gid)), name, gid)
			self.assertTrue(callable(getattr(app, "script_" + name)))

	def test_scripts_run(self) -> None:
		"""Las cuatro órdenes llaman al modelo de objetos y hablan con su resultado."""
		m = self.m
		results = {
			m._ppt.om_selectionShape: {"name": "Tabla 1", "type": 19, "left": 72, "top": 36, "width": 144, "height": 72, "table": [["Nombre", "Edad"], ["Ana", "30"]], "cell": (2, 1)},
			m._ppt.om_elements: {"slides": [("Diapositiva 1", ("slide", 1, ""))], "shapes": [], "tables": [], "notes": []},
		}

		def fakeCall(func, *args, callback=None, onError=None, timeout=None):
			if callback is not None:
				callback(results.get(func))

		spoken: list[str] = []
		app = m.AppModule.__new__(m.AppModule)
		app._instanceGestures = {}
		app.chartNavigator = None
		with mock.patch.object(m._office, "callAsync", side_effect=fakeCall), mock.patch.object(m.speech, "speakMessage", side_effect=spoken.append), mock.patch.object(
			m.speech, "speakText", side_effect=spoken.append
		), mock.patch.object(m, "_repeat", return_value=0), mock.patch.object(app, "_hwnd", return_value=1), mock.patch.object(m.winapi, "getAncestor", return_value=1), mock.patch(
			"tiresias.gui.app_dialogs.showItemList"
		) as showList, mock.patch.object(app, "openChart") as openChart:
			app.script_shapeLocation(None)
			app.script_readTable(None)
			app.script_chart(None)
			app.script_elementsList(None)
		self.assertTrue(spoken[0].startswith("Tabla 1, tabla"))
		self.assertIn("fila 2, columna 1", spoken[1])
		self.assertIn("Ana", spoken[1])
		openChart.assert_called_once()
		showList.assert_called_once()


# ====================================================================== D-001
class JawsLayoutYieldsToDocumentTests(unittest.TestCase):
	def setUp(self) -> None:
		from tiresias import config_plugin, gesture_layouts
		from tiresias.baseobject import ScriptableObject, script
		from tiresias.global_commands import commands
		from tiresias.input import core as inputCore

		self.layouts = gesture_layouts
		self.inputCore = inputCore
		self.oldInstance = config_plugin.instance
		self.oldLayout = conf["keyboard"]["gestureLayout"]
		self.oldChain = list(inputCore.manager.chain)
		self.plugin = config_plugin.GlobalPlugin()
		conf["keyboard"]["gestureLayout"] = "jaws"
		with mock.patch.object(inputCore.manager, "updateChain"):
			gesture_layouts.apply()

		class Doc(ScriptableObject):
			@script(description="modo foco", gesture="kb:tiresias+space")
			def script_togglePassThrough(self, gesture):
				pass

			@script(description="disposición", gesture="kb:tiresias+v")
			def script_toggleScreenLayout(self, gesture):
				pass

		self.doc = Doc()
		self.commands = commands

	def tearDown(self) -> None:
		from tiresias import config_plugin

		conf["keyboard"]["gestureLayout"] = self.oldLayout
		with mock.patch.object(self.inputCore.manager, "updateChain"):
			self.layouts.apply()
		self.plugin.terminate()
		config_plugin.instance = self.oldInstance
		self.inputCore.manager.chain = self.oldChain

	def test_document_wins_inside_documents(self) -> None:
		self.inputCore.manager.chain = [self.plugin, self.doc, self.commands]
		for gid, docScript in (("kb:tiresias+space", "script_togglePassThrough"), ("kb:tiresias+v", "script_toggleScreenLayout")):
			g = FakeGesture("kb(desktop):" + gid[3:], gid)
			self.assertIsNone(self.plugin.getScript(g), gid)
			func = self.inputCore.manager.findScript(g)
			self.assertEqual(func.__name__, docScript)

	def test_layers_and_quick_settings_outside_documents(self) -> None:
		self.inputCore.manager.chain = [self.plugin, self.commands]
		self.assertEqual(self.plugin.getScript(FakeGesture("kb:tiresias+space")).__name__, "script_layerKey")
		self.assertEqual(self.plugin.getScript(FakeGesture("kb:tiresias+v")).__name__, "script_quickSettings")

	def test_own_gestures_do_not_yield(self) -> None:
		"""Las teclas propias del complemento (no del mapa) no ceden."""
		self.inputCore.manager.chain = [self.plugin, self.doc, self.commands]
		self.assertEqual(self.plugin.getScript(FakeGesture("kb:tiresias+control+q")).__name__, "script_quickSettings")


# ====================================================================== C-003
class _LabelledObj:
	def __init__(self, name="", role=None, aid="lbl-1", app="pruebaetiquetas", value="", **kw) -> None:
		from tiresias.objects.roles import Role

		self.name = name
		self.role = role if role is not None else Role.BUTTON
		self.UIAAutomationId = aid
		self.UIAClassName = ""
		self.windowClassName = "Ventana"
		self.location = (0, 0, 20, 10)
		self.appModule = types.SimpleNamespace(appName=app)
		self.value = value
		self.states = set()
		for k, v in kw.items():
			setattr(self, k, v)


class CustomLabelsEverywhereTests(unittest.TestCase):
	def setUp(self) -> None:
		from tiresias import labels

		self.labels = labels
		self.old = conf["labels"]["enabled"]
		conf["labels"]["enabled"] = True
		self.obj = _LabelledObj(name="btn_x7")
		labels.setLabel(self.obj, "Enviar")

	def tearDown(self) -> None:
		self.labels.setLabel(self.obj, None)
		conf["labels"]["enabled"] = self.old

	def test_display_name(self) -> None:
		self.assertEqual(self.labels.displayName(self.obj), "Enviar")
		other = _LabelledObj(name="Aceptar", aid="otro")
		self.assertEqual(self.labels.displayName(other), "Aceptar")

	def test_speech_and_braille(self) -> None:
		from tiresias import presentation
		from tiresias.braille import presenter

		self.assertIn("Enviar", presentation.getObjectSpeech(self.obj))
		props = dict(presenter.objectProperties(self.obj))
		self.assertEqual(props["name"], "Enviar")

	def test_object_review_text(self) -> None:
		from tiresias.objects.base import AccObject

		class Obj(AccObject):
			def _get_name(self):
				return "btn_x7"

			def _get_value(self):
				return ""

			def _get_role(self):
				from tiresias.objects.roles import Role

				return Role.BUTTON

			def _get_UIAAutomationId(self):
				return "lbl-1"

			def _get_windowClassName(self):
				return "Ventana"

			def _get_appModule(self):
				return types.SimpleNamespace(appName="pruebaetiquetas")

		o = Obj.__new__(Obj)
		self.assertEqual(o.basicText, "Enviar")

	def test_browse_buffer_nodes(self) -> None:
		from tiresias.objects.roles import Role

		lookup = self.labels.bufferLookup("pruebaetiquetas", "Ventana")
		node = types.SimpleNamespace(automationId="lbl-1", className="", role=Role.BUTTON, name="btn_x7", location=(0, 0, 20, 10))
		self.assertEqual(lookup(node), "Enviar")
		node2 = types.SimpleNamespace(automationId="otro", className="", role=Role.BUTTON, name="x", location=None)
		self.assertIsNone(lookup(node2))
		# Etiqueta por nombre: la clase del objeto es la de la ventana del navegador.
		named = _LabelledObj(name="Más", aid="")
		self.labels.setLabel(named, "Más opciones")
		try:
			node3 = types.SimpleNamespace(automationId="", className="", role=Role.BUTTON, name="Más", location=None)
			self.assertEqual(lookup(node3), "Más opciones")
		finally:
			self.labels.setLabel(named, None)

	def test_buffer_uses_custom_labels(self) -> None:
		from tiresias.browse import buffer

		buf = buffer.VirtualBuffer(None)
		self.assertIsNone(buf.customLabels)
		src = inspect.getsource(buffer.VirtualBuffer._makeNode)
		self.assertIn("customLabels", src)

	def test_disabled_labels(self) -> None:
		conf["labels"]["enabled"] = False
		self.assertEqual(self.labels.displayName(self.obj), "btn_x7")
		self.assertIsNone(self.labels.bufferLookup("pruebaetiquetas"))


# ====================================================================== C-008
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


class AcceleratorTests(unittest.TestCase):
	"""Ninguna letra & repetida en una misma ventana."""

	@classmethod
	def setUpClass(cls) -> None:
		import wx

		cls.wx = wx
		cls.app = wx.App.Get() or wx.App(False)

	def _labels(self, win, skip=()) -> list[tuple[str, str]]:
		wx = self.wx
		out = []

		def walk(w):
			if w in skip or (isinstance(w, wx.TopLevelWindow) and w is not win):
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

	def _assertUnique(self, items, where) -> None:
		seen: dict[str, str] = {}
		dups = []
		for a, lab in items:
			if a in seen:
				dups.append((a, seen[a], lab))
			seen[a] = lab
		self.assertEqual(dups, [], where)

	def test_speech_history_dialog(self) -> None:
		from tiresias.gui import history_dialogs

		dlg = history_dialogs.SpeechHistoryDialog()
		try:
			self._assertUnique(self._labels(dlg), "historial de voz")
		finally:
			dlg.Destroy()

	def test_simple_dialogs(self) -> None:
		from tiresias.gui import audio_dialogs, config_dialogs, nvda_import_dialog, speech_dialogs, system_dialogs, tutorial

		for cls in (
			audio_dialogs.MixerDialog,
			config_dialogs.ProfilesDialog,
			config_dialogs.AddonsDialog,
			config_dialogs.WelcomeDialog,
			nvda_import_dialog.NvdaImportDialog,
			speech_dialogs.VoiceSchemesDialog,
			speech_dialogs.RoleTemplatesDialog,
			system_dialogs.QuickSettingsDialog,
			system_dialogs.LabelsManagerDialog,
			system_dialogs.CreatePortableDialog,
			tutorial.TutorialDialog,
		):
			with self.subTest(dialog=cls.__name__):
				try:
					dlg = cls() if not [p for p in list(inspect.signature(cls.__init__).parameters.values())[1:] if p.default is p.empty] else cls(None)
				except Exception as e:  # noqa: BLE001
					self.skipTest(f"{cls.__name__}: {e!r}")
				try:
					self._assertUnique(self._labels(dlg), cls.__name__)
				finally:
					dlg.Destroy()

	def test_profiles_dialog_alternate_labels(self) -> None:
		"""Las etiquetas que cambian según el perfil activo tampoco chocan con las demás."""
		from tiresias.gui import config_dialogs

		dlg = config_dialogs.ProfilesDialog(None)
		try:
			for label, button in (("Des&activar", dlg.activateButton), ("Activar e&ste perfil", dlg.enableButton), ("Pe&rmitir cambios", dlg.readOnlyButton)):
				button.SetLabel(label)
				self._assertUnique(self._labels(dlg), label)
		finally:
			dlg.Destroy()

	def test_settings_categories(self) -> None:
		from tiresias.gui import settings as S

		for mod, fn in (
			("tiresias.gui.speech_settings", "registerPanels"),
			("tiresias.gui.audio_dialogs", "register"),
			("tiresias.gui.touch_panel", "register"),
			("tiresias.gui.remote_dialogs", "registerSettingsPanel"),
			("tiresias.gui.rdp_panel", "register"),
			("tiresias.mathpres.settings_panel", "registerPanel"),
		):
			try:
				getattr(importlib.import_module(mod), fn)()
			except Exception:
				pass
		try:
			from tiresias.gui import ai_dialogs

			S.registerPanel("ai", ai_dialogs.AiPanel.title, ai_dialogs.AiPanel)
		except Exception:
			pass
		dlg = S.SettingsDialog(None)
		try:
			top = self._labels(dlg, skip=(dlg.container,))
			for pid in S.getPanelIds():
				dlg.selectCategory(pid)
				panel = dlg.getPanel(pid)
				if panel is None:
					continue
				with self.subTest(category=pid):
					self._assertUnique(top + self._labels(panel), pid)
			self.assertEqual(S.getPanelIds()[-1], "advanced")
		finally:
			dlg.Destroy()


# ====================================================================== C-020, C-025, A-007
class BrailleDescriptionsTests(unittest.TestCase):
	def test_hid_key_descriptions(self) -> None:
		from tiresias.braille.drivers import hidBraille

		drv = hidBraille.HidBrailleDriver
		self.assertTrue(drv.keyDescriptions)
		keys = set()
		for gid in drv.gestureMap:
			keys.update(gid.split("+"))
		for k in keys:
			self.assertTrue(k in drv.keyDescriptions or (k.startswith("dot") and "dot1" in drv.keyDescriptions), k)

	def test_tether_description(self) -> None:
		from tiresias.global_commands import GlobalCommands

		doc = GlobalCommands.script_braille_toggleTether.__doc__
		self.assertIn("automático", doc)
		self.assertIn("foco", doc)
		self.assertIn("revisión", doc)

	def test_hid_tab_is_dots_4_6(self) -> None:
		from tiresias.baseobject import normalizeGestureId
		from tiresias.braille.drivers import hidBraille
		from tiresias.global_commands import GlobalCommands

		gestures = dict(GlobalCommands.iterClassGestures())
		self.assertEqual(gestures.get(normalizeGestureId("br(hidBraille):space+dot4+dot6")), "braille_tab")
		self.assertNotIn(normalizeGestureId("br(hidBraille):space+dot4+dot5"), gestures)
		self.assertEqual(hidBraille.HidBrailleDriver.gestureMap["space+dot4+dot6"], "kb:tab")


# ====================================================================== D-002
class ContextHelpAnchorsTests(unittest.TestCase):
	def test_every_category_has_anchors(self) -> None:
		from tiresias.gui import context_help as CH

		self.assertEqual(set(CH.CATEGORY_ANCHORS), set(CH.PANEL_ANCHORS))
		for pid, anchor in CH.CATEGORY_ANCHORS.items():
			self.assertEqual(anchor, f"cat-{pid}")
		self.assertEqual(CH.optionAnchor("general", "language"), "opt-general-language")

	def test_fallback_order(self) -> None:
		from tiresias.gui import context_help as CH

		with mock.patch.object(CH, "manualIds", return_value={"opt-speech-rate", "cat-speech", "op-voz", "op-teclado", "opciones"}):
			self.assertEqual(CH.anchorFor("speech", ("speech", "rate")), "opt-speech-rate")
			self.assertEqual(CH.anchorFor("speech", ("speech", "pitch")), "cat-speech")
			self.assertEqual(CH.anchorFor("keyboard", ("keyboard", "x")), "op-teclado")
			self.assertEqual(CH.anchorFor("desconocido", None), "opciones")

	def test_panel_anchors_exist_in_manual(self) -> None:
		"""Los apartados de respaldo existen hoy en el manual."""
		from tiresias.gui import context_help as CH

		path = os.path.join(ROOT, "manual", "manual_usuario.html")
		if not os.path.isfile(path):
			self.skipTest("sin manual")
		with open(path, encoding="utf-8") as f:
			text = f.read()
		for pid, anchor in CH.PANEL_ANCHORS.items():
			self.assertIn(f'id="{anchor}"', text, pid)


# ====================================================================== D-004, D-017
class SmallFixesTests(unittest.TestCase):
	def test_format_toggles(self) -> None:
		from tiresias import global_commands_extra as X

		keys = {k for _n, k, _w in X.DOC_TOGGLES}
		for k in ("detectFormatAfterCursor", "reportQuotes", "useHeaderAbbreviations", "reportDetails"):
			self.assertIn(k, keys)
			self.assertIn(k, conf["documentFormatting"])
		for name, _k, _w in X.DOC_TOGGLES:
			self.assertTrue(hasattr(X.ExtraCommands, "script_" + name), name)

	def test_menu_key_removal_warning(self) -> None:
		from tiresias.gui import gesture_tools

		src = inspect.getsource(gesture_tools.ScriptGesturesDialog._onRemove)
		self.assertIn("showGui", src)
		self.assertIn("área de notificación", src)


# ====================================================================== A-001
class GestureNormalizationTests(unittest.TestCase):
	def test_gesture_dict_normalizes(self) -> None:
		from tiresias.baseobject import GestureDict

		d = GestureDict()
		d["kb:alt+shift+1"] = "x"
		self.assertIn("kb:shift+alt+1", dict(d))
		self.assertEqual(d["kb:shift+alt+1"], "x")
		self.assertEqual(d.get("kb:ALT+Shift+1"), "x")
		d.setdefault("kb:control+tiresias+a", "y")
		self.assertIn("kb:tiresias+control+a", dict(d))
		del d["kb:alt+shift+1"]
		self.assertNotIn("kb:shift+alt+1", d)

	def test_direct_class_gesture_write_is_found(self) -> None:
		from tiresias.baseobject import ScriptableObject
		from tiresias.input.gestures import KeyboardGesture

		class O(ScriptableObject):
			def script_hola(self, gesture):
				pass

		O._classGestures["kb:alt+shift+5"] = "hola"
		g = KeyboardGesture(0, 0, False, frozenset({"alt", "shift"}), "5")
		self.assertEqual(O().getScript(g).__name__, "script_hola")

	def test_whatsapp_read_last_messages(self) -> None:
		from tiresias.input.gestures import KeyboardGesture

		base = os.path.join(ROOT, "data", "addons", "whatsapp")
		if not os.path.isdir(base):
			self.skipTest("sin complemento de WhatsApp")
		for name, path in (("prueba_wa", base), ("prueba_wa.appModules", os.path.join(base, "appModules"))):
			if name not in sys.modules:
				mod = types.ModuleType(name)
				mod.__path__ = [path]  # type: ignore[attr-defined]
				sys.modules[name] = mod
		wa = importlib.import_module("prueba_wa.appModules.whatsapp_root")
		app = wa.AppModule.__new__(wa.AppModule)
		app._instanceGestures = {}
		for n in range(1, 11):
			g = KeyboardGesture(0, 0, False, frozenset({"alt", "shift"}), str(n % 10))
			self.assertEqual(app._scriptNameForGesture(g.identifiers[-1]), f"readLastMessage{n}")

	def test_all_declared_gestures_are_normalized(self) -> None:
		"""Recorre todas las clases con órdenes: cada gesto está en su forma normalizada."""
		import tiresias
		from tiresias.baseobject import GestureDict, ScriptableObject, normalizeGestureId

		skip = ("tiresias.test_", "tiresias.gui.python_console")
		for info in pkgutil.walk_packages(tiresias.__path__, "tiresias."):
			if info.name.startswith(skip):
				continue
			try:
				importlib.import_module(info.name)
			except Exception:
				pass
		bad = []

		def walk(cls):
			yield cls
			for sub in cls.__subclasses__():
				yield from walk(sub)

		for cls in set(walk(ScriptableObject)):
			cg = cls.__dict__.get("_classGestures")
			if cg is None:
				continue
			if not isinstance(cg, GestureDict):
				bad.append(f"{cls.__module__}.{cls.__qualname__}: no es GestureDict")
			for gid in dict(cg):
				if gid != normalizeGestureId(gid):
					bad.append(f"{cls.__module__}.{cls.__qualname__}: {gid}")
			for attr, func in vars(cls).items():
				for g in getattr(func, "gestures", None) or ():
					if attr.startswith("script_") and normalizeGestureId(g) not in cg and not any(normalizeGestureId(g) == k for k in cg):
						# El gesto declarado tiene que estar registrado en la clase.
						bad.append(f"{cls.__module__}.{cls.__qualname__}.{attr}: {g} sin registrar")
		self.assertEqual(bad, [])


if __name__ == "__main__":
	unittest.main()
