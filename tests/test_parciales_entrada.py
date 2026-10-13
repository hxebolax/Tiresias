"""Pruebas del grupo «entrada, ratón y diálogos» (peticiones parciales).

- G17 (#11678): las tres teclas Tiresias activadas por defecto; dos
  pulsaciones de Bloq Mayús siguen cambiando el bloqueo de mayúsculas.
- G30 (#2559): tonos de coordenadas del objeto navegador y de la revisión.
- G36 (#11898): espera opcional antes de leer lo que hay bajo el ratón.
- G35 (#258): cuadro de mensaje propio con el texto en un campo recorrible.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(ROOT, "src") not in sys.path:
	sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="tiresias_test_entrada_")
if not os.path.isdir(os.path.join(_TMP, "symbols")):
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
paths.setDataDir(_TMP)
paths.ensureDataDirs()

import wx  # noqa: E402

from tiresias import mouse, queue_handler, winapi  # noqa: E402
from tiresias.config import conf, schema, validation  # noqa: E402
from tiresias.gui import message_dialog as md  # noqa: E402
from tiresias.input import core as inputCore  # noqa: E402


class _ConfValue:
	"""Cambia un valor de configuración durante la prueba y lo restaura."""

	def __init__(self, section: str, key: str, value) -> None:
		self.section, self.key, self.value = section, key, value

	def __enter__(self):
		self.old = conf[self.section][self.key]
		conf[self.section][self.key] = self.value
		return self

	def __exit__(self, *exc) -> None:
		conf[self.section][self.key] = self.old


# ====================================================================== G17
class TiresiasKeysTests(unittest.TestCase):
	def test_all_keys_enabled_by_default(self) -> None:
		kb = schema.DEFAULTS["keyboard"]
		self.assertTrue(kb["useInsertAsModifier"])
		self.assertTrue(kb["useNumpadInsertAsModifier"])
		self.assertTrue(kb["useCapsLockAsModifier"])

	def test_caps_lock_is_tiresias_key(self) -> None:
		m = inputCore.InputManager()
		with _ConfValue("keyboard", "useCapsLockAsModifier", True):
			self.assertTrue(m._isTiresiasKey(winapi.VK_CAPITAL, False))
			self.assertTrue(m._isTiresiasKey(winapi.VK_INSERT, True))
			self.assertTrue(m._isTiresiasKey(winapi.VK_INSERT, False))
		with _ConfValue("keyboard", "useCapsLockAsModifier", False):
			self.assertFalse(m._isTiresiasKey(winapi.VK_CAPITAL, False))

	def _press(self, m, vk=winapi.VK_CAPITAL, used=False) -> None:
		self.assertTrue(m._onTiresiasKey(vk, False, False))
		if used:
			m._tiresiasUsed = True
		self.assertTrue(m._onTiresiasKey(vk, False, True))

	def test_double_press_toggles_caps_lock(self) -> None:
		m = inputCore.InputManager()
		queued = []
		with mock.patch.object(winapi, "sendInputs") as send, mock.patch.object(queue_handler, "queueFunction", side_effect=lambda f, *a, **k: queued.append(a)), _ConfValue("keyboard", "announceToggleKeys", True):
			self._press(m)
			send.assert_not_called()
			self._press(m)
			self.assertEqual(send.call_count, 1)
			inputs = send.call_args[0][0]
			self.assertEqual(len(inputs), 2)
			self.assertEqual(inputs[0].ki.wVk, winapi.VK_CAPITAL)
			self.assertEqual(inputs[0].ki.dwExtraInfo, winapi.TIRESIAS_INJECTION_MARK)
		self.assertTrue(m._capsToggled)
		self.assertIn(("bloqueo de mayúsculas activado",), queued)

	def test_caps_used_as_modifier_does_not_toggle(self) -> None:
		m = inputCore.InputManager()
		with mock.patch.object(winapi, "sendInputs") as send, mock.patch.object(queue_handler, "queueFunction"):
			self._press(m, used=True)
			self._press(m)
			send.assert_not_called()
		self.assertFalse(m._capsToggled)

	def test_welcome_dialog_mentions_caps_lock(self) -> None:
		with open(os.path.join(ROOT, "src", "tiresias", "gui", "config_dialogs.py"), encoding="utf-8") as f:
			src = f.read()
		# La bienvenida dice que de fábrica sirven las tres teclas (y deja elegirlas).
		self.assertIn("de fábrica sirven las tres: Insertar, Insertar del teclado numérico y Bloqueo de mayúsculas", src)
		# El mismo texto que en Opciones, categoría Teclado (revisión de Opciones 1.0.6).
		self.assertIn('("useCapsLockAsModifier", _("&Bloqueo de mayúsculas"))', src)


# ====================================================================== G30
class _Obj:
	def __init__(self, location) -> None:
		self.location = location


class _Info:
	def __init__(self, rects=(), point=None, obj=None) -> None:
		self._rects = list(rects)
		self.pointAtStart = point
		self.obj = obj

	@property
	def boundingRects(self):
		return self._rects

	def copy(self):
		return self

	def expand(self, unit) -> None:
		pass


class AudioCoordinatesTests(unittest.TestCase):
	def test_coordinate_tone(self) -> None:
		screen = (0, 0, 1000, 500)
		self.assertEqual(mouse.coordinateTone(0, 0, screen, 220, 880), (880, 0))
		self.assertEqual(mouse.coordinateTone(1000, 500, screen, 220, 880), (220, 100))
		pitch, right = mouse.coordinateTone(500, 250, screen, 220, 880)
		self.assertAlmostEqual(pitch, 550)
		self.assertEqual(right, 50)
		# Fuera de la pantalla: se ajusta al borde.
		self.assertEqual(mouse.coordinateTone(-50, 900, screen, 220, 880), (220, 0))
		# Escritorio virtual con un monitor a la izquierda (x negativas).
		self.assertEqual(mouse.coordinateTone(-1000, 0, (-1000, 0, 2000, 500), 220, 880), (880, 0))

	def test_navigator_tone_only_when_enabled(self) -> None:
		with mock.patch.object(mouse, "_audioCoordinates") as tone:
			with _ConfValue("reviewCursor", "audioCoordinatesOnNavigatorMove", False):
				mouse.navigatorAudioCoordinates(_Obj((100, 200, 50, 20)))
				tone.assert_not_called()
			with _ConfValue("reviewCursor", "audioCoordinatesOnNavigatorMove", True):
				mouse.navigatorAudioCoordinates(_Obj((100, 200, 50, 20)))
				tone.assert_called_once_with(125, 210)
				tone.reset_mock()
				mouse.navigatorAudioCoordinates(_Obj(None))
				mouse.navigatorAudioCoordinates(_Obj((0, 0, 0, 0)))
				mouse.navigatorAudioCoordinates(None)
				tone.assert_not_called()

	def test_review_tone(self) -> None:
		with mock.patch.object(mouse, "_audioCoordinates") as tone:
			with _ConfValue("reviewCursor", "audioCoordinatesOnReviewMove", False):
				mouse.reviewAudioCoordinates(_Info([(10, 10, 10, 10)]))
				tone.assert_not_called()
			with _ConfValue("reviewCursor", "audioCoordinatesOnReviewMove", True):
				mouse.reviewAudioCoordinates(_Info([(10, 10, 10, 10)]))
				tone.assert_called_once_with(15, 15)
				tone.reset_mock()
				from tiresias import textinfo

				mouse.reviewAudioCoordinates(_Info(point=textinfo.Point(40, 60)))
				tone.assert_called_once_with(40, 60)
				tone.reset_mock()
				# Sin posición del texto: la del objeto.
				mouse.reviewAudioCoordinates(_Info(obj=_Obj((0, 0, 100, 100))))
				tone.assert_called_once_with(50, 50)

	def test_toggle_commands(self) -> None:
		from tiresias import global_commands_extra, speech

		cls = global_commands_extra.ExtraCommands
		obj = cls.__new__(cls)
		with mock.patch.object(speech, "speakMessage"):
			for script, key in (("script_toggleNavigatorAudioCoordinates", "audioCoordinatesOnNavigatorMove"), ("script_toggleReviewAudioCoordinates", "audioCoordinatesOnReviewMove")):
				before = conf["reviewCursor"][key]
				getattr(cls, script)(obj, None)
				self.assertEqual(conf["reviewCursor"][key], not before)
				getattr(cls, script)(obj, None)
				self.assertEqual(conf["reviewCursor"][key], before)
			before = conf["mouse"]["reportDelay"]
			try:
				conf["mouse"]["reportDelay"] = 0
				cls.script_cycleMouseReportDelay(obj, None)
				self.assertEqual(conf["mouse"]["reportDelay"], 250)
			finally:
				conf["mouse"]["reportDelay"] = before


# ====================================================================== G36
class MouseDelayTests(unittest.TestCase):
	def setUp(self) -> None:
		mouse._lastPos = (-1, -1)
		mouse._delayTimer = None
		from tiresias.magnifier import magnifier

		self._patches = [
			mock.patch.object(magnifier, "onMouse"),
			mock.patch.object(mouse, "_reportAt"),
			mock.patch.object(queue_handler, "callLater", side_effect=self._callLater),
			mock.patch.object(queue_handler, "cancelCallLater"),
		]
		self.timers = []
		for p in self._patches:
			p.start()
		self.addCleanup(lambda: [p.stop() for p in self._patches])
		self.addCleanup(setattr, mouse, "_delayTimer", None)

	def _callLater(self, ms, func, *a, **k):
		self.timers.append((ms, func))
		return len(self.timers)

	def test_schema_and_range(self) -> None:
		self.assertEqual(conf.defaults["mouse"]["reportDelay"], 0)
		self.assertEqual(validation.RANGES[("mouse", "reportDelay")], (0, 5000))

	def test_no_delay_reports_immediately(self) -> None:
		with _ConfValue("mouse", "reportDelay", 0), _ConfValue("mouse", "enableMouseTracking", True):
			mouse.handleMouseMove(10, 20)
		mouse._reportAt.assert_called_once_with(10, 20)
		self.assertEqual(self.timers, [])

	def test_delay_waits_until_pointer_stops(self) -> None:
		with _ConfValue("mouse", "reportDelay", 400), _ConfValue("mouse", "enableMouseTracking", True):
			mouse.handleMouseMove(10, 20)
			mouse.handleMouseMove(30, 40)
			mouse._reportAt.assert_not_called()
			# Un solo temporizador aunque el puntero se mueva varias veces.
			self.assertEqual(len(self.timers), 1)
			self.assertEqual(self.timers[0][0], 400)
			# El puntero se acaba de mover: se vuelve a esperar.
			mouse._lastMoveTime = time.monotonic() - 0.1
			self.timers[0][1]()
			mouse._reportAt.assert_not_called()
			self.assertEqual(len(self.timers), 2)
			self.assertTrue(250 <= self.timers[1][0] <= 300)
			# Ya lleva el tiempo quieto: se lee la última posición.
			mouse._lastMoveTime = time.monotonic() - 1
			self.timers[1][1]()
			mouse._reportAt.assert_called_once_with(30, 40)

	def test_remaining_delay(self) -> None:
		self.assertEqual(mouse._remainingDelay(10.0, 9.9, 500), 400)
		self.assertEqual(mouse._remainingDelay(10.0, 9.0, 500), 0)


# ====================================================================== G35
class MessageDialogLogicTests(unittest.TestCase):
	def test_buttons(self) -> None:
		self.assertEqual(md.buttonIds(wx.OK), [wx.ID_OK])
		self.assertEqual(md.buttonIds(wx.OK | wx.CANCEL), [wx.ID_OK, wx.ID_CANCEL])
		self.assertEqual(md.buttonIds(wx.YES_NO), [wx.ID_YES, wx.ID_NO])
		self.assertEqual(md.buttonIds(wx.YES_NO | wx.CANCEL), [wx.ID_YES, wx.ID_NO, wx.ID_CANCEL])
		self.assertEqual(md.buttonIds(0), [wx.ID_OK])
		self.assertEqual(md.buttonIds(wx.OK | wx.HELP), [wx.ID_OK, wx.ID_HELP])

	def test_default_and_escape(self) -> None:
		self.assertEqual(md.defaultId(wx.YES_NO), wx.ID_YES)
		self.assertEqual(md.defaultId(wx.YES_NO | wx.NO_DEFAULT), wx.ID_NO)
		self.assertEqual(md.defaultId(wx.OK | wx.CANCEL | wx.CANCEL_DEFAULT), wx.ID_CANCEL)
		self.assertEqual(md.defaultId(wx.OK), wx.ID_OK)
		self.assertEqual(md.escapeId(wx.YES_NO), wx.ID_NO)
		self.assertEqual(md.escapeId(wx.YES_NO | wx.CANCEL), wx.ID_CANCEL)
		self.assertEqual(md.escapeId(wx.OK), wx.ID_OK)

	def test_icons_and_results(self) -> None:
		self.assertEqual(md.iconKind(wx.OK | wx.ICON_ERROR), "error")
		self.assertEqual(md.iconKind(wx.OK | wx.ICON_WARNING), "warning")
		self.assertEqual(md.iconKind(wx.YES_NO), "question")
		self.assertEqual(md.iconKind(wx.OK), "information")
		self.assertEqual(md.iconKind(wx.OK | wx.ICON_NONE), "")
		self.assertEqual(md.resultFromId(wx.ID_YES), wx.YES)
		self.assertEqual(md.resultFromId(wx.ID_NO), wx.NO)
		self.assertEqual(md.resultFromId(wx.ID_OK), wx.OK)
		self.assertEqual(md.resultFromId(wx.ID_CANCEL), wx.CANCEL)

	def test_mnemonic(self) -> None:
		self.assertEqual(md.mnemonic("&Sí"), "s")
		self.assertEqual(md.mnemonic("A&yuda"), "y")
		self.assertEqual(md.mnemonic("Aceptar"), "")
		self.assertEqual(md.mnemonic("Tom && Jerry"), "")

	def test_no_native_message_boxes_left(self) -> None:
		"""Ningún aviso de Tiresias usa el cuadro nativo de Windows (#258)."""
		base = os.path.join(ROOT, "src", "tiresias")
		pattern = re.compile(r"wx\.(MessageBox|MessageDialog|RichMessageDialog|GenericMessageDialog)\(")
		found = []
		for dirpath, _dirs, files in os.walk(base):
			if "locale" in dirpath:
				continue
			for name in files:
				if not name.endswith(".py") or name == "message_dialog.py":
					continue
				path = os.path.join(dirpath, name)
				with open(path, encoding="utf-8") as f:
					for n, line in enumerate(f, 1):
						if pattern.search(line):
							found.append(f"{os.path.relpath(path, base)}:{n}")
		self.assertEqual(found, [])


class MessageDialogWidgetTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		cls.app = wx.App.Get() or wx.App(False)

	def _make(self, style, text="Primera línea.\nSegunda línea con más palabras.", **kw):
		dlg = md.MessageDialog(None, text, "Prueba", style)
		self.addCleanup(dlg.Destroy)
		for k, v in kw.items():
			getattr(dlg, k)(*v)
		dlg.build()
		return dlg

	def test_read_only_text_and_buttons(self) -> None:
		dlg = self._make(wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
		self.assertTrue(dlg.text.IsMultiLine())
		self.assertFalse(dlg.text.IsEditable())
		self.assertIn("Segunda línea con más palabras.", dlg.text.GetValue())
		self.assertEqual(set(dlg.buttons), {wx.ID_YES, wx.ID_NO})
		self.assertEqual(dlg._defaultId, wx.ID_NO)
		self.assertEqual(dlg._escapeId, wx.ID_NO)
		self.assertEqual(dlg.GetEscapeId(), wx.ID_NO)
		labels = [c.GetLabel() for c in dlg.GetChildren() if isinstance(c, wx.StaticText)]
		self.assertTrue(any("Intro responde «No»" in lbl for lbl in labels))

	def test_custom_labels_and_checkbox(self) -> None:
		dlg = self._make(wx.YES_NO | wx.ICON_WARNING, SetYesNoLabels=("&Deshacer", "&Aceptar"), ShowCheckBox=("No volver a preguntar",))
		self.assertEqual(dlg.buttons[wx.ID_YES].GetLabel(), "&Deshacer")
		self.assertEqual(dlg._buttonForKey("d"), wx.ID_YES)
		self.assertEqual(dlg._buttonForKey("a"), wx.ID_NO)
		self.assertIsNotNone(dlg.checkBox)
		self.assertFalse(dlg.IsCheckBoxChecked())
		dlg.checkBox.SetValue(True)
		self.assertTrue(dlg.IsCheckBoxChecked())

	def test_ok_only_has_no_hint(self) -> None:
		dlg = self._make(wx.OK | wx.ICON_INFORMATION, text="Hecho.")
		self.assertEqual(list(dlg.buttons), [wx.ID_OK])
		labels = [c.GetLabel() for c in dlg.GetChildren() if isinstance(c, wx.StaticText)]
		self.assertFalse(any("Intro responde" in lbl for lbl in labels))
		# Sin modal: el botón deja el código de retorno.
		dlg._finish(wx.ID_OK)
		self.assertEqual(dlg.GetReturnCode(), wx.ID_OK)


if __name__ == "__main__":
	unittest.main()
