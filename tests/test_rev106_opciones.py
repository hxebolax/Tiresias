"""Pruebas de regresión de la revisión de los paneles de Opciones (1.0.6).

Cada clase cubre un hallazgo (el número es el de la revisión):

- 1: copiar la entrada «permitir» de Escritorio remoto se hace en el núcleo.
- 2: activar Java Access Bridge no bloquea la interfaz (hilo propio).
- 3: la configuración del sistema se copia y se quita en un hilo propio, y
  ``removeSystemConfig`` avisa si falla.
- 4: las voces por contexto se leen en el núcleo.
- 5: los idiomas del OCR se obtienen en un hilo propio.
- 6: el cambio de perfil de RDP se aplica en el núcleo.
- 7: «Solo lectura» guarda el perfil antes de protegerlo.
- 8: cambiar el nombre del perfil que se edita actualiza el perfil manual.
- 9: los cambios de nombre y borrados de esquemas de voz se aplican al Aceptar.
- 10: la lista de un ajuste del sintetizador usa las opciones actuales.
- 11: la tabla de símbolos se compila antes de sustituirse.
- 12: las combinaciones reservadas y comunes están normalizadas.
- 15: se valida la sustitución de las expresiones regulares.
- 16: el rango del doble toque coincide con el de la validación.
- 17: nombres de tema de sonidos no válidos en Windows.
- 18: «Iniciar al iniciar sesión» lee el registro y revierte si falla.
- 19: «Teclas actuales» del menú se refresca.
- 20: el diccionario de voz no se recarga dos veces.
- 21: un fallo al guardar un panel no cierra Opciones.
- 22: los controles propios respetan las opciones bloqueadas.
- 23: Aceptar sin cambios no recarga el sintetizador.
- 24: un valor desconocido de un ajuste del controlador braille se conserva.
- 25: el modo dormir por configuración no se puede marcar sin perfil.
- 26: el diccionario de otro perfil se registra como único.
- 27: instalar complementos y exportar temas, en hilos propios.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev106_opciones``
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_rev106_test_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()

import wx  # noqa: E402

from tiresias.config import conf  # noqa: E402

_app = wx.App.Get() or wx.App(False)


def _flush(cond=None, timeout: float = 5.0) -> None:
	"""Procesa los wx.CallAfter pendientes (hasta que se cumpla ``cond``)."""
	end = time.monotonic() + timeout
	while True:
		_app.ProcessPendingEvents()
		# Yield también destruye las ventanas pendientes (Destroy es diferido).
		wx.Yield()
		if cond is None or cond():
			return
		if time.monotonic() > end:
			return
		time.sleep(0.01)


class _FakeTextEntry:
	"""Sustituye a wx.TextEntryDialog: devuelve un texto fijo."""

	value = ""

	def __init__(self, *args, **kwargs) -> None:
		pass

	def ShowModal(self) -> int:
		return wx.ID_OK

	def GetValue(self) -> str:
		return type(self).value

	def Destroy(self) -> None:
		pass


class _Base(unittest.TestCase):
	def setUp(self) -> None:
		self.frame = wx.Frame(None)

	def tearDown(self) -> None:
		self.frame.Destroy()
		_flush()


# ====================================================================== 1
class RdpCopyTests(unittest.TestCase):
	def test_copy_is_queued_on_core(self) -> None:
		from tiresias import api
		from tiresias.gui import rdp_panel

		with mock.patch.object(rdp_panel.queue_handler, "queueFunction") as q:
			rdp_panel.RdpPanel._onCopyAllowEntry(types.SimpleNamespace(_allowEntry="entrada"), None)
		q.assert_called_once_with(api.copyToClip, "entrada", True)


# ====================================================================== 2
class JabThreadTests(_Base):
	def test_enable_bridge_runs_in_own_thread(self) -> None:
		from tiresias.a11y import jab
		from tiresias.gui import settings as S

		# El estado de Java Access Bridge está en «Avanzado», grupo «Aplicaciones Java».
		with mock.patch.object(jab, "findDll", return_value="C:/java/WindowsAccessBridge-64.dll"), mock.patch.object(jab, "isBridgeEnabled", return_value=False):
			panel = S.AdvancedPanel(self.frame)
		threads: list[int] = []

		def enable() -> bool:
			threads.append(threading.get_ident())
			return True

		with mock.patch.object(S, "askYesNo", return_value=True), mock.patch.object(jab, "enableBridge", side_effect=enable):
			panel._onEnableJab(None)
			_flush(lambda: "Reinicie" in panel._jabStatus.GetLabel())
		self.assertEqual(len(threads), 1)
		self.assertNotEqual(threads[0], threading.get_ident())
		self.assertIn("Reinicie", panel._jabStatus.GetLabel())
		self.assertFalse(panel._jabButton.IsEnabled())


# ====================================================================== 3
class SystemConfigTests(_Base):
	def test_remove_system_config_reports_failures(self) -> None:
		from tiresias import installer

		tmp = tempfile.mkdtemp(prefix="tiresias_syscfg_")
		target = os.path.join(tmp, "systemConfig")
		os.makedirs(target)
		try:
			with mock.patch.object(paths, "SYSTEM_CONFIG_DIR", target):
				# Elevado: un código de salida distinto de 0 es un error.
				with mock.patch.object(installer, "isWritable", return_value=False), mock.patch.object(installer, "shellExecuteElevated", return_value=5):
					with self.assertRaises(OSError):
						installer.removeSystemConfig()
				# Sin elevar: rmtree ignora los errores, así que se comprueba la carpeta.
				with mock.patch.object(installer, "isWritable", return_value=True), mock.patch.object(installer.shutil, "rmtree"):
					with self.assertRaises(OSError):
						installer.removeSystemConfig()
				with mock.patch.object(installer, "isWritable", return_value=True):
					installer.removeSystemConfig()
				self.assertFalse(os.path.isdir(target))
		finally:
			shutil.rmtree(tmp, ignore_errors=True)

	def test_remove_runs_in_thread_and_shows_error(self) -> None:
		from tiresias import installer
		from tiresias.gui import settings as S

		panel = S.GeneralPanel(self.frame)
		threads: list[int] = []

		def remove() -> None:
			threads.append(threading.get_ident())
			raise OSError("denegado")

		with mock.patch.object(S, "askYesNo", return_value=True), mock.patch.object(S, "showError") as err, mock.patch.object(installer, "removeSystemConfig", side_effect=remove):
			panel._onRemoveSystem(None)
			_flush(lambda: err.called)
		self.assertEqual(len(threads), 1)
		self.assertNotEqual(threads[0], threading.get_ident())
		self.assertTrue(err.called)
		self.assertIn("denegado", err.call_args[0][0])
		self.assertFalse(panel._systemBusy)

	def test_copy_runs_in_thread(self) -> None:
		from tiresias import installer
		from tiresias.gui import settings as S

		panel = S.GeneralPanel(self.frame)
		threads: list[int] = []
		with (
			mock.patch.object(S, "askYesNo", return_value=True),
			mock.patch.object(conf, "save"),
			mock.patch.object(S.message_dialog, "messageBox") as box,
			mock.patch.object(installer, "requestCopyConfigToSystem", side_effect=lambda: threads.append(threading.get_ident())),
		):
			panel._onCopyToSystem(None)
			_flush(lambda: box.called)
		self.assertEqual(len(threads), 1)
		self.assertNotEqual(threads[0], threading.get_ident())
		self.assertTrue(box.called)


# ====================================================================== 4
class VoiceChoicesTests(_Base):
	def test_voices_are_read_on_core(self) -> None:
		from tiresias.gui import settings as S, speech_settings
		from tiresias.speech import voice_schemes as vs

		calls = []
		with mock.patch.object(S, "runOnCore", side_effect=lambda func, *a, callback=None: calls.append((func, callback))):
			with mock.patch.object(vs, "contextVoiceChoices", side_effect=AssertionError("en la interfaz")) as voices:
				panel = speech_settings.VoiceContextsPanel(self.frame)
		voices.assert_not_called()
		funcs = [f for f, _cb in calls]
		self.assertIn(voices, funcs)
		callback = calls[funcs.index(voices)][1]
		key = vs.contextKey(vs.CONTEXTS[0], "Voice")
		callback([("", "La misma voz"), ("v1", "Voz uno"), ("v2", "Voz dos")])
		ctrl = panel.getControl(key)
		self.assertIn("Voz dos", ctrl.GetStrings())
		self.assertEqual(panel.getValue(key), conf["speech"][key])


# ====================================================================== 5
class OcrChoicesTests(_Base):
	def test_languages_in_own_thread(self) -> None:
		from tiresias.gui import settings as S

		threads: list[int] = []

		def collect() -> dict:
			threads.append(threading.get_ident())
			return {"language": [("", "Automático"), ("es-ES", "es-ES")], "tesseractLanguage": [("spa", "spa"), ("fra", "fra")]}

		with (
			mock.patch.object(S, "_collectOcrChoices", side_effect=collect),
			mock.patch.object(S, "_tesseractLanguageChoices", side_effect=AssertionError("en la interfaz")),
			mock.patch.object(S, "_ocrLanguageChoices", side_effect=AssertionError("en la interfaz")),
			mock.patch.dict(S._ocrChoicesCache, clear=True),
		):
			panel = S.OcrPanel(self.frame)
			_flush(lambda: "fra" in panel.getControl("tesseractLanguage").GetStrings())
		self.assertEqual(len(threads), 1)
		self.assertNotEqual(threads[0], threading.get_ident())
		self.assertIn("fra", panel.getControl("tesseractLanguage").GetStrings())
		self.assertIn("es-ES", panel.getControl("language").GetStrings())


# ====================================================================== 6
class RdpProfileSwitchTests(unittest.TestCase):
	def test_profile_switch_queues_apply(self) -> None:
		from tiresias.remote import rdp

		with mock.patch.object(rdp.queue_handler, "queueFunction") as q, mock.patch.object(rdp, "applyConfig") as apply:
			rdp._onProfileSwitch()
		q.assert_called_once_with(apply)
		apply.assert_not_called()


# ====================================================================== 7, 8 y 26
class ProfilesDialogTests(_Base):
	def setUp(self) -> None:
		super().setUp()
		from tiresias.gui import config_dialogs

		self.cd = config_dialogs
		for name in ("Rev106A", "Rev106B", "Rev106C"):
			if name in conf.profiles:
				conf.deleteProfile(name)
		conf.createProfile("Rev106A")
		self.dlg = config_dialogs.ProfilesDialog(None, "prueba")

	def tearDown(self) -> None:
		if self.cd.isAlive(self.dlg):
			self.dlg.Destroy()
		conf.setManualProfile(None)
		for name in ("Rev106A", "Rev106B", "Rev106C"):
			if name in conf.profiles:
				conf.setProfileReadOnly(name, False)
				conf.deleteProfile(name)
		super().tearDown()

	def test_read_only_saves_first(self) -> None:
		conf.profiles["Rev106A"].dirty = True
		self.dlg.refresh("Rev106A")
		seen = []
		with mock.patch.object(conf, "save", side_effect=lambda: seen.append(conf.isProfileReadOnly("Rev106A"))):
			self.dlg._onToggleReadOnly(None)
			_flush(lambda: conf.isProfileReadOnly("Rev106A"))
		self.assertEqual(seen, [False])
		self.assertTrue(conf.isProfileReadOnly("Rev106A"))

	def test_rename_updates_previous_manual(self) -> None:
		self.dlg._prevManual = "Rev106A"
		self.dlg.refresh("Rev106A")
		_FakeTextEntry.value = "Rev106B"
		with mock.patch.object(self.cd.wx, "TextEntryDialog", _FakeTextEntry):
			self.dlg._onRename(None)
		self.assertIn("Rev106B", conf.profiles)
		self.assertEqual(self.dlg._prevManual, "Rev106B")

	def test_profile_dict_is_registered(self) -> None:
		conf.createProfile("Rev106C")
		self.dlg.refresh("Rev106A")
		self.dlg._onProfileDict(None)
		opened = self.cd._dialogs.get("dict-profile")
		try:
			self.assertIsNotNone(opened)
			self.assertEqual(opened.profileName, "Rev106A")
			# Abrir el de otro perfil con uno abierto: se avisa y no se abre otro.
			self.dlg.refresh("Rev106C")
			with mock.patch.object(self.cd, "showError") as err:
				self.dlg._onProfileDict(None)
			self.assertTrue(err.called)
			self.assertIs(self.cd._dialogs.get("dict-profile"), opened)
			self.assertEqual(conf.manualProfile, "Rev106A")
		finally:
			if self.cd.isAlive(opened):
				opened.closeDialog()
			_flush()
		self.assertNotEqual(conf.manualProfile, "Rev106A")


# ====================================================================== 9
class VoiceSchemesTests(unittest.TestCase):
	def setUp(self) -> None:
		from tiresias.gui import speech_dialogs
		from tiresias.speech import voice_schemes as vs

		self.sd = speech_dialogs
		self.vs = vs
		vs.saveUserSchemes({"Mio": {}, "Otro": {}})
		conf["speech"]["voiceScheme"] = "Mio"

	def tearDown(self) -> None:
		self.vs.saveUserSchemes({})
		conf["speech"]["voiceScheme"] = ""

	def _dialog(self):
		dlg = self.sd.VoiceSchemesDialog(None)
		dlg.schemeList.SetSelection(dlg._names().index("Mio"))
		return dlg

	def test_rename_applies_on_ok_only(self) -> None:
		_FakeTextEntry.value = "Nuevo"
		dlg = self._dialog()
		with mock.patch.object(self.sd.wx, "TextEntryDialog", _FakeTextEntry):
			dlg._onRename(None)
		self.assertEqual(conf["speech"]["voiceScheme"], "Mio")
		dlg.onCancel()
		self.assertEqual(conf["speech"]["voiceScheme"], "Mio")
		dlg = self._dialog()
		called = []
		dlg.onSaved.append(lambda: called.append(True))
		with mock.patch.object(self.sd.wx, "TextEntryDialog", _FakeTextEntry):
			dlg._onRename(None)
		dlg._onOk(None)
		self.assertEqual(conf["speech"]["voiceScheme"], "Nuevo")
		self.assertEqual(called, [True])

	def test_delete_applies_on_ok_only(self) -> None:
		dlg = self._dialog()
		with mock.patch.object(self.sd, "askYesNo", return_value=True):
			dlg._onDelete(None)
		self.assertEqual(conf["speech"]["voiceScheme"], "Mio")
		dlg._onOk(None)
		self.assertEqual(conf["speech"]["voiceScheme"], "")

	def test_panel_scheme_list_refreshes(self) -> None:
		from tiresias.gui import speech_settings

		frame = wx.Frame(None)
		try:
			panel = speech_settings.VoiceContextsPanel(frame)
			self.vs.saveUserSchemes({"Mio": {}, "Otro": {}, "Tercero": {}})
			conf["speech"]["voiceScheme"] = "Renombrado"
			self.vs.saveUserSchemes({"Renombrado": {}, "Otro": {}, "Tercero": {}})
			panel._refreshSchemes()
			strings = panel.getControl("voiceScheme").GetStrings()
			self.assertIn("Tercero", strings)
			self.assertNotIn("Mio", strings)
			self.assertEqual(panel.getValue("voiceScheme"), "Renombrado")
		finally:
			frame.Destroy()


# ====================================================================== 10
class SynthChoiceTests(unittest.TestCase):
	def test_uses_current_choices(self) -> None:
		from tiresias.gui import settings as S

		old = {"id": "variant", "choices": [("a", "A"), ("b", "B")]}
		new = {"id": "variant", "choices": [("x", "X"), ("y", "Y")]}
		fake = types.SimpleNamespace(_synthControls={"variant": (new, None)}, _onSynthValue=mock.Mock())
		evt = mock.Mock()
		evt.GetSelection.return_value = 1
		S.SpeechPanel._onSynthChoice(fake, old, evt)
		fake._onSynthValue.assert_called_once_with(new, "y")


# ====================================================================== 11
class SymbolsSwapTests(unittest.TestCase):
	def test_replace_compiles_before_swap(self) -> None:
		from tiresias.speech import symbols

		proc = symbols.SymbolProcessor("es")
		proc.ensureLoaded()
		table = {k: v for k, v in proc.symbols.items() if k != "#"}
		table["§"] = symbols.Symbol("§", "parágrafo", 0)
		proc.replaceSymbols(table)
		self.assertNotIn("#", proc.symbols)
		self.assertIn("parágrafo", proc.process("a § b", 300))

	def test_stale_regex_does_not_raise(self) -> None:
		from tiresias.speech import symbols

		proc = symbols.SymbolProcessor("es")
		proc.ensureLoaded()
		# Expresión vieja con una tabla a la que le falta un símbolo.
		proc.symbols = {k: v for k, v in proc.symbols.items() if k != "#"}
		proc.process("uno # dos", 300)

	def test_dialog_ok_applies_on_core(self) -> None:
		from tiresias.gui import config_dialogs

		dlg = config_dialogs.SymbolsDialog(None)
		calls = []
		with mock.patch.object(config_dialogs, "runOnCore", side_effect=lambda func, *a, callback=None: calls.append((func, callback))):
			dlg._onOk(None)
		self.assertEqual(len(calls), 1)
		func, callback = calls[0]
		with mock.patch.object(dlg._symbolsModule.SymbolProcessor, "saveUser"), mock.patch.object(dlg._symbolsModule.SymbolProcessor, "replaceSymbols") as swap:
			self.assertIsNone(func())
		self.assertTrue(swap.called)
		callback(None)
		_flush()
		self.assertFalse(config_dialogs.isAlive(dlg) and dlg.IsShown())


# ====================================================================== 12
class GestureNormalizationTests(unittest.TestCase):
	def test_reserved_and_common_are_normalized(self) -> None:
		from tiresias.baseobject import normalizeGestureId
		from tiresias.gui import gesture_tools as gt

		for keys in list(gt.RESERVED) + list(gt.COMMON):
			self.assertEqual(normalizeGestureId("kb:" + keys), "kb:" + keys)
		self.assertTrue(gt.checkGesture([], {}, normalizeGestureId("kb:alt+shift+tab"))["reserved"])
		self.assertTrue(gt.checkGesture([], {}, normalizeGestureId("kb:windows+control+enter"))["reserved"])
		self.assertTrue(gt.checkGesture([], {}, normalizeGestureId("kb:control+shift+tab"))["common"])


# ====================================================================== 15
class DictEntryReplacementTests(_Base):
	def _check(self, pattern: str, replacement: str) -> bool:
		from tiresias.gui import config_dialogs

		dlg = config_dialogs.DictEntryDialog(self.frame, "prueba")
		try:
			dlg.patternCtrl.SetValue(pattern)
			dlg.replacementCtrl.SetValue(replacement)
			dlg.typeCtrl.SetSelection([t for t, _l in config_dialogs._DICT_TYPES].index("regex"))
			evt = mock.Mock()
			with mock.patch.object(config_dialogs, "showError") as err:
				dlg._onOk(evt)
			return evt.Skip.called and not err.called
		finally:
			dlg.Destroy()

	def test_replacement_is_validated(self) -> None:
		self.assertFalse(self._check("a", "\\1"))
		self.assertFalse(self._check("(a)", "\\g<nombre>"))
		self.assertTrue(self._check("(a)", "\\1\\1"))
		self.assertTrue(self._check("a", "b"))


# ====================================================================== 16
class TouchRangeTests(unittest.TestCase):
	def test_multitap_range_matches_validation(self) -> None:
		from tiresias.config import validation
		from tiresias.gui import touch_panel

		field = next(f for f in touch_panel.TouchPanel.fields if f.key == "multiTapTimeout")
		self.assertEqual((field.minVal, field.maxVal), tuple(int(v) for v in validation.RANGES[("touch", "multiTapTimeout")]))


# ====================================================================== 17
class ThemeNameTests(unittest.TestCase):
	def test_names(self) -> None:
		from tiresias.gui.audio_dialogs import isValidThemeName

		for bad in ("", "default", ".", "..", " . ", "tema.", "tema ", "a/b", "a:b", "CON", "nul.txt", "co\tsa"):
			with self.subTest(name=bad):
				self.assertFalse(isValidThemeName(bad))
		for good in ("personalizado", "mi tema", "v1.2", "Tema-2"):
			with self.subTest(name=good):
				self.assertTrue(isValidThemeName(good))


# ====================================================================== 18 y 25
class GeneralPanelTests(_Base):
	def setUp(self) -> None:
		super().setUp()
		conf.setManualProfile(None)
		conf.editProfile = None

	def test_start_on_logon_reads_registry(self) -> None:
		from tiresias.gui import settings as S

		conf["general"]["startOnLogon"] = False
		with mock.patch.object(S, "isStartOnLogonEnabled", return_value=True):
			panel = S.GeneralPanel(self.frame)
		self.assertTrue(panel.getValue("startOnLogon"))

	def test_start_on_logon_reverts_on_error(self) -> None:
		from tiresias.gui import settings as S

		conf["general"]["startOnLogon"] = False
		with mock.patch.object(S, "isStartOnLogonEnabled", return_value=False):
			panel = S.GeneralPanel(self.frame)
		panel.setControlValue("startOnLogon", True)
		with mock.patch.object(S, "setStartOnLogon", side_effect=OSError("acceso denegado")), mock.patch.object(S, "showError") as err:
			panel.onSave()
		self.assertTrue(err.called)
		self.assertFalse(conf["general"]["startOnLogon"])
		self.assertFalse(panel.getValue("startOnLogon"))

	def test_sleep_mode_disabled_without_profile(self) -> None:
		from tiresias.gui import settings as S

		from tiresias.gui import apps_panel

		# El modo dormir por perfil está en «Aplicaciones», junto al permanente.
		conf["sleepMode"]["enabled"] = False
		panel = apps_panel.AppsPanel(self.frame)
		self.assertFalse(panel.getControl("enabled", "sleepMode").IsEnabled())
		general = S.GeneralPanel.getFields(S.GeneralPanel.__new__(S.GeneralPanel))
		self.assertNotIn(("sleepMode", "enabled"), [(f.section or "general", f.key) for f in general])


# ====================================================================== 19
class MenuKeysRefreshTests(_Base):
	def test_label_refreshes_after_dialog(self) -> None:
		from tiresias.gui import gesture_tools, settings as S

		panel = S.KeyboardPanel(self.frame)
		fakeDialog = wx.Dialog(self.frame)
		with (
			mock.patch.object(gesture_tools, "showMenuKeyDialog"),
			mock.patch.object(gesture_tools, "_menuKeyDialog", fakeDialog),
			mock.patch.object(gesture_tools, "describeMenuKeys", return_value="Tiresias+Z"),
		):
			panel._onMenuKey(None)
			fakeDialog.Destroy()
			_flush(lambda: "Tiresias+Z" in panel.menuKeysText.GetLabel())
		self.assertIn("Tiresias+Z", panel.menuKeysText.GetLabel())


# ====================================================================== 20
class VoiceDictReloadTests(unittest.TestCase):
	def test_single_reload(self) -> None:
		from tiresias import core, synth
		from tiresias.gui import config_dialogs, settings as S

		with mock.patch.object(synth, "changeSetting") as change, mock.patch.object(core, "_loadVoiceDict") as reload:
			S._changeSynthSetting("voice", "v1")
		change.assert_called_once_with("voice", "v1")
		reload.assert_not_called()
		self.assertFalse(hasattr(config_dialogs.SpeechDictDialog, "_copy"))


# ====================================================================== 21
class SaveAllTests(unittest.TestCase):
	def test_failed_panel_keeps_dialog_open(self) -> None:
		from tiresias.gui import settings as S

		dlg = S.SettingsDialog(None)
		try:
			pid = next(iter(dlg._panels))
			panel = dlg._panels[pid]
			with mock.patch.object(panel, "onSave", side_effect=RuntimeError("fallo")), mock.patch.object(S, "showError") as err:
				self.assertFalse(dlg._saveAll())
			self.assertTrue(err.called)
			self.assertTrue(dlg._saveAll())
		finally:
			dlg.Destroy()


# ====================================================================== 22
class LockedControlsTests(_Base):
	def _locked(self, *paths):
		original = conf.isLocked

		def isLocked(section, key=None):
			return (section, key) in paths or original(section, key)

		return mock.patch.object(conf, "isLocked", side_effect=isLocked)

	def test_speech_modes_locked(self) -> None:
		from tiresias.gui import settings as S

		before = list(conf["speech"]["excludedSpeechModes"])
		with self._locked(("speech", "excludedSpeechModes")):
			panel = S.SpeechPanel(self.frame)
			self.assertTrue(all(not c.IsEnabled() for c in panel._modeChecks.values()))
			self.assertTrue(panel.isValid())
			panel.onSave()
		self.assertEqual(list(conf["speech"]["excludedSpeechModes"]), before)

	def test_verbosity_order_locked(self) -> None:
		from tiresias.gui import speech_settings

		with self._locked(("presentation", "propertyOrder")):
			panel = speech_settings.VerbosityPanel(self.frame)
		self.assertFalse(panel.orderList.IsEnabled())

	def test_audio_split_modes_locked(self) -> None:
		from tiresias.gui import settings as S

		with self._locked(("audio", "includedSoundSplitModes")):
			panel = S.AudioPanel(self.frame)
		self.assertFalse(panel.splitModesList.IsEnabled())

	def test_braille_properties_locked(self) -> None:
		from tiresias.gui import braille_panels

		with self._locked(("braille", "propertyOrder"), ("braille", "roleAbbreviations")):
			panel = braille_panels.BraillePresentationPanel(self.frame)
		self.assertFalse(panel._propList.IsEnabled())
		self.assertTrue(panel._rolesLocked)


# ====================================================================== 23
class SynthSelectionTests(unittest.TestCase):
	def test_ok_without_changes_does_not_reload(self) -> None:
		from tiresias.gui import settings as S

		conf["speech"]["synth"] = "auto"
		with mock.patch.object(S.SynthSelectionDialog, "_collect", staticmethod(lambda: ([], None))):
			dlg = S.SynthSelectionDialog(None)
		with mock.patch.object(S.queue_handler, "queueFunction") as q:
			dlg._onOk(None)
		self.assertFalse(any(c.args and c.args[0] is S._applySynthSelection for c in q.call_args_list))


# ====================================================================== 24
class DriverSettingUnknownValueTests(_Base):
	def test_unknown_value_is_kept(self) -> None:
		from tiresias.braille import drivers
		from tiresias.braille.drivers import base
		from tiresias.gui import braille_display_dialog as bdd

		setting = base.DriverSetting("modo", "Modo:", "choice", default="a", choices=(("a", "A"), ("b", "B")))
		fakeCls = types.SimpleNamespace(driverSettings=(setting,), getSetting=lambda key: "desconocido")
		from tiresias.gui import settings as S

		# Los ajustes de cada línea están en la categoría «Braille».
		with mock.patch.object(drivers, "hardwareDriverChoices", return_value=[("falso", "Falso")]), mock.patch.object(bdd, "_driverClass", return_value=fakeCls):
			panel = S.BraillePanel(self.frame)
		with mock.patch.object(base, "getDriverSetting", return_value="desconocido"), mock.patch.object(base, "setDriverSetting") as setter, mock.patch.object(panel, "isValid", return_value=True):
			panel.onSave()
		setter.assert_not_called()


# ====================================================================== 27
class BackgroundWorkTests(_Base):
	def test_sound_theme_export_in_thread(self) -> None:
		from tiresias.gui import audio_dialogs

		panel = audio_dialogs.SoundsPanel(self.frame)
		_FakeTextEntry.value = "rev106"
		with mock.patch.object(audio_dialogs.wx, "TextEntryDialog", _FakeTextEntry), mock.patch.object(audio_dialogs.S, "runInThread") as run, mock.patch.object(audio_dialogs.S, "runOnCore") as core:
			panel._onExport(None)
		self.assertTrue(run.called)
		core.assert_not_called()

	def test_addon_install_in_thread(self) -> None:
		from tiresias.gui import config_dialogs

		dlg = config_dialogs.AddonsDialog(None)
		try:
			fileDialog = mock.MagicMock()
			fileDialog.return_value.ShowModal.return_value = wx.ID_OK
			fileDialog.return_value.GetPath.return_value = "C:/complemento.tiresias-addon"
			with (
				mock.patch.object(config_dialogs.wx, "FileDialog", fileDialog),
				mock.patch.object(dlg._addonsModule, "inspectPackage", return_value=({"id": "x"}, None)),
				mock.patch.object(config_dialogs, "runInThread") as run,
			):
				dlg._onInstall(None)
			self.assertTrue(run.called)
			self.assertIs(run.call_args[0][0], dlg._addonsModule.installFromFile)
		finally:
			dlg.Destroy()


if __name__ == "__main__":
	unittest.main()
