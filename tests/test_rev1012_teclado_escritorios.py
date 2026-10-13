"""Pruebas de la revisión 1.0.12: idioma del teclado y escritorios virtuales.

- Cambio de idioma o distribución del teclado (:mod:`tiresias.input.input_language`):
  nombres (idioma, distribución, IME), una sola vez por cambio, sin repetir al
  cambiar de ventana, con el ratón o desde la barra de tareas, opción para
  desactivarlo, silencio en la lectura continua y arranque con los ganchos.
- Escritorios virtuales (:mod:`tiresias.virtual_desktops`): el evento de nombre
  del escritorio (#32769) se filtra en el hilo de los ganchos y se anuncia una
  vez tras 250 ms; sin título, el nombre sale del registro («Escritorio N»).

No instala ganchos ni cambia la distribución ni los escritorios del usuario:
todo se prueba con funciones y objetos simulados.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev1012_teclado_escritorios``
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
import uuid
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_rev1012_test_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()

from tiresias import virtual_desktops as VD  # noqa: E402
from tiresias.a11y import msaa, winevents  # noqa: E402
from tiresias.config import (
	conf,  # noqa: E402
	validation,  # noqa: E402
)
from tiresias.input import hooks  # noqa: E402
from tiresias.input import input_language as IL  # noqa: E402

ES = 0x040A0C0A  # Español (España), distribución Español
US = 0x04090409  # Inglés (Estados Unidos), distribución Estados Unidos
ES_US = 0x04090C0A  # Español (España) con la distribución de Estados Unidos
JA = 0x04110411  # Japonés (IME de Text Services Framework)


class _Conf:
	def __init__(self, section: str, key: str, value) -> None:
		self.section, self.key, self.value = section, key, value

	def __enter__(self):
		self.old = conf[self.section][self.key]
		conf[self.section][self.key] = self.value
		return self

	def __exit__(self, *exc) -> None:
		conf[self.section][self.key] = self.old


class _Clock:
	def __init__(self) -> None:
		self.t = 100.0

	def __call__(self) -> float:
		return self.t


# ====================================================================== nombres
class NameTests(unittest.TestCase):
	def test_klid_from_hkl(self) -> None:
		self.assertEqual(IL.klidFromHkl(ES), "0000040A")
		self.assertEqual(IL.klidFromHkl(US), "00000409")
		self.assertEqual(IL.klidFromHkl(0xE0010411), "E0010411")
		# Variante con «Layout Id» (Estados Unidos - Internacional).
		self.assertEqual(IL.klidFromHkl(0xF0010409, {1: "00020409"}), "00020409")
		self.assertEqual(IL.klidFromHkl(0xF0010409, {}), "00000409")
		self.assertEqual(IL.langIdOf(ES), 0x0C0A)

	def test_language_name(self) -> None:
		self.assertEqual(IL.composeLanguageName("Español", "España", "Español (España, internacional)"), "Español (España)")
		self.assertEqual(IL.composeLanguageName("Inglés", "Estados Unidos"), "Inglés (Estados Unidos)")
		# El idioma ya lleva paréntesis: el nombre completo de Windows.
		self.assertEqual(IL.composeLanguageName("Chino (simplificado)", "China", "Chino (simplificado, China continental)"), "Chino (simplificado, China continental)")
		self.assertEqual(IL.composeLanguageName("Esperanto", "", ""), "Esperanto")

	def test_strip_language_prefix_only_when_it_is_the_language(self) -> None:
		self.assertEqual(IL.stripLanguagePrefix("Chinese (Simplified) - US Keyboard", ("", "Chinese (Simplified)")), "US Keyboard")
		self.assertEqual(IL.stripLanguagePrefix("Estados Unidos - Internacional", ("Inglés (Estados Unidos)", "Inglés")), "Estados Unidos - Internacional")
		self.assertEqual(IL.stripLanguagePrefix("Español", ("Español (España)", "Español")), "Español")

	def test_format_announcement(self) -> None:
		self.assertEqual(IL.formatAnnouncement("Español (España)", "Español", True), "Español (España), Español")
		self.assertEqual(IL.formatAnnouncement("Inglés (Estados Unidos)", "EE. UU.", True), "Inglés (Estados Unidos), EE. UU.")
		# Mismo idioma: solo la distribución (como NVDA).
		self.assertEqual(IL.formatAnnouncement("Español (España)", "Estados Unidos", False), "Estados Unidos")
		# Sin distribución conocida: el idioma.
		self.assertEqual(IL.formatAnnouncement("Japonés (Japón)", "", False), "Japonés (Japón)")
		self.assertEqual(IL.formatAnnouncement("", "", True), "idioma desconocido")

	def test_profile_values(self) -> None:
		self.assertEqual(IL.parseProfileValue("0C0A:0000040A"), (0x0C0A, "0000040A", "", ""))
		tip = IL.parseProfileValue("0411:{03B5835F-F03C-411B-9CE2-AA23E1171E36}{A76C93D9-5523-4E90-AAFA-4DB112F9AC76}")
		self.assertEqual(tip[0], 0x0411)
		self.assertEqual(tip[2], "{03B5835F-F03C-411B-9CE2-AA23E1171E36}")
		self.assertIsNone(IL.parseProfileValue("CachedLanguageName"))

	def test_choose_input_method(self) -> None:
		ja = (0x411, "", "{C}", "{P}")
		es = (0x0C0A, "0000040A", "", "")
		self.assertEqual(IL.chooseInputMethod("0000040A", [es, ja], 0x0C0A), ("layout", "0000040A", ""))
		# Un solo IME para el idioma: su nombre.
		self.assertEqual(IL.chooseInputMethod("00000411", [es, ja], 0x411), ("tip", "{C}", "{P}"))
		# Varios IME: no se sabe cuál (solo el idioma).
		self.assertEqual(IL.chooseInputMethod("00000804", [(0x804, "", "{A}", "{1}"), (0x804, "", "{B}", "{2}")], 0x804), ("none", "", ""))
		# Distribución normal del idioma aunque tenga también un IME.
		self.assertEqual(IL.chooseInputMethod("00000409", [(0x804, "00000409", "", ""), (0x804, "", "{A}", "{1}")], 0x804), ("layout", "00000409", ""))

	def test_describe_uses_language_only_when_it_changes(self) -> None:
		with (
			mock.patch.object(IL, "languageNames", side_effect=lambda l: {0x0C0A: ("Español (España)", "Español"), 0x0409: ("Inglés (Estados Unidos)", "Inglés")}[l]),
			mock.patch.object(IL, "inputMethodName", side_effect=lambda h: {ES: "Español", US: "EE. UU.", ES_US: "EE. UU."}[h]),
		):
			self.assertEqual(IL.describe(US, ES), "Inglés (Estados Unidos), EE. UU.")
			self.assertEqual(IL.describe(ES, US), "Español (España), Español")
			self.assertEqual(IL.describe(ES_US, ES), "EE. UU.")

	def test_ime_name(self) -> None:
		entries = [(0x411, "", "{C}", "{P}")]
		with (
			mock.patch.object(IL, "userProfileEntries", return_value=entries),
			mock.patch.object(IL, "layoutIdMap", return_value={}),
			mock.patch.object(IL, "tipDisplayName", return_value="Microsoft IME") as tip,
		):
			self.assertEqual(IL.inputMethodName(JA), "Microsoft IME")
		tip.assert_called_once_with("{C}", "{P}", 0x411)

	@unittest.skipUnless(sys.platform == "win32", "solo Windows")
	def test_real_names_are_read_from_windows(self) -> None:
		"""Lectura real (sin cambiar nada): «Estados Unidos» existe en todos los Windows."""
		self.assertTrue(IL.layoutDisplayName("00000409"))
		full, short = IL.languageNames(0x0409)
		self.assertTrue(full and short)
		self.assertIn(short, full)


# ====================================================================== una vez por cambio
class TrackerTests(unittest.TestCase):
	def make(self, perThread: bool = False) -> tuple[IL.LayoutTracker, _Clock]:
		clock = _Clock()
		return IL.LayoutTracker(perThread=lambda: perThread, clock=clock), clock

	def test_first_sample_is_the_baseline(self) -> None:
		t, _c = self.make()
		self.assertIsNone(t.observe(1, ES))
		self.assertIsNone(t.observe(1, ES))
		self.assertEqual(t.current, ES)

	def test_change_in_the_focused_window_is_announced_once(self) -> None:
		t, _c = self.make()
		t.observe(1, ES)
		self.assertEqual(t.observe(1, US), ES)
		self.assertIsNone(t.observe(1, US))
		self.assertEqual(t.observe(1, ES), US)

	def test_global_layout_no_repeat_when_switching_windows(self) -> None:
		t, _c = self.make()
		t.observe(1, ES)
		t.observe(2, ES)  # otra ventana conocida
		t.observe(1, ES)
		self.assertEqual(t.observe(1, US), ES)
		# La otra ventana aún tiene la antigua un momento y luego toma la común.
		self.assertIsNone(t.observe(2, ES))
		self.assertIsNone(t.observe(2, US))
		self.assertIsNone(t.observe(1, US))

	def test_mouse_selector_on_the_taskbar(self) -> None:
		"""El selector de la barra de tareas: cambia su hilo y luego vuelve a la ventana."""
		t, _c = self.make()
		t.observe(1, ES)  # editor
		t.observe(7, ES)  # barra de tareas (clic en el indicador)
		self.assertEqual(t.observe(7, US), ES)
		self.assertIsNone(t.observe(1, US))
		# Si el selector se cierra antes de verlo: se anuncia al volver al editor.
		t2, _c = self.make()
		t2.observe(1, ES)
		t2.observe(7, ES)
		self.assertEqual(t2.observe(1, US), ES)

	def test_new_window_with_another_layout_is_silent(self) -> None:
		t, _c = self.make()
		t.observe(1, ES)
		self.assertIsNone(t.observe(9, US))

	def test_per_window_layouts(self) -> None:
		t, clock = self.make(perThread=True)
		t.observe(1, ES)
		t.observe(2, US)  # cada ventana con la suya: no se anuncia
		self.assertIsNone(t.observe(1, ES))
		self.assertIsNone(t.observe(2, US))
		# Cambio dentro de la ventana 2.
		self.assertEqual(t.observe(2, ES), US)
		# El selector cambia su hilo y después la ventana: una sola vez.
		clock.t += 10
		t.observe(7, ES)
		self.assertEqual(t.observe(7, US), ES)
		self.assertIsNone(t.observe(1, US))
		# Más tarde, el mismo cambio en otra ventana sí es otro cambio.
		clock.t += 10
		t.observe(2, ES)
		self.assertEqual(t.observe(2, US), ES)

	def test_threads_are_forgotten(self) -> None:
		t, _c = self.make()
		for i in range(IL.MAX_THREADS + 10):
			t.observe(i + 1, ES)
		self.assertLessEqual(len(t._byThread), IL.MAX_THREADS)


class WatcherTests(unittest.TestCase):
	def test_check_once_queues_one_announcement(self) -> None:
		samples = [(1, ES), (1, ES), (1, US), (1, US), None, (2, US)]
		calls = []
		w = IL.LayoutWatcher(sample=lambda: samples.pop(0), onChange=lambda h, p: calls.append((h, p)), tracker=IL.LayoutTracker(perThread=lambda: False))
		results = [w.checkOnce() for _i in range(6)]
		self.assertEqual(results, [False, False, True, False, False, False])
		self.assertEqual(calls, [(US, ES)])

	def test_sample_errors_are_ignored(self) -> None:
		w = IL.LayoutWatcher(sample=mock.Mock(side_effect=OSError), onChange=mock.Mock())
		self.assertFalse(w.checkOnce())

	def test_watcher_thread_starts_and_stops(self) -> None:
		w = IL.LayoutWatcher(sample=lambda: None, onChange=mock.Mock(), interval=0.01)
		w.start()
		try:
			self.assertTrue(w.isRunning)
			w.start()  # dos veces: el mismo hilo
		finally:
			w.stop()
		self.assertFalse(w.isRunning)

	def test_sample_uses_the_focus_thread(self) -> None:
		from tiresias import winapi

		info = mock.Mock(hwndFocus=0x200)
		with (
			mock.patch.object(winapi, "getForegroundWindow", return_value=0x100),
			mock.patch.object(winapi, "getWindowThreadId", side_effect=lambda h: {0x100: 10, 0x200: 20}[h]),
			mock.patch.object(winapi, "getGUIThreadInfo", return_value=info),
			mock.patch.object(IL, "_user32") as u32,
		):
			u32.GetKeyboardLayout.return_value = US
			self.assertEqual(IL.sampleForeground(), (20, US))
			u32.GetKeyboardLayout.assert_called_once_with(20)
		with mock.patch.object(winapi, "getForegroundWindow", return_value=0):
			self.assertIsNone(IL.sampleForeground())

	def test_hook_thread_starts_and_stops_the_watcher(self) -> None:
		ht = hooks.HookThread()
		with (
			mock.patch.object(IL, "start") as start,
			mock.patch.object(IL, "stop") as stop,
			mock.patch.object(hooks.threading, "Thread") as thread,
		):
			thread.return_value.is_alive.return_value = False
			ht._ready = mock.Mock()
			ht.start([])
			start.assert_called_once()
			ht.stop()
			stop.assert_called_once()


class AnnounceTests(unittest.TestCase):
	def test_announce_speaks_the_description(self) -> None:
		from tiresias import speech

		with (
			_Conf("keyboard", "announceInputLanguageChanges", True),
			mock.patch.object(IL, "_shouldStaySilent", return_value=False),
			mock.patch.object(IL, "describe", return_value="Inglés (Estados Unidos), EE. UU."),
			mock.patch.object(speech, "speakMessage") as speak,
		):
			IL.announce(US, ES)
		speak.assert_called_once_with("Inglés (Estados Unidos), EE. UU.")

	def test_option_turns_it_off(self) -> None:
		from tiresias import speech

		with (
			_Conf("keyboard", "announceInputLanguageChanges", False),
			mock.patch.object(IL, "describe", return_value="x") as desc,
			mock.patch.object(speech, "speakMessage") as speak,
		):
			IL.announce(US, ES)
		speak.assert_not_called()
		desc.assert_not_called()

	def test_silent_during_say_all(self) -> None:
		from tiresias import speech
		from tiresias.speech import sayall

		with (
			_Conf("keyboard", "announceInputLanguageChanges", True),
			mock.patch.object(sayall, "isRunning", return_value=True),
			mock.patch.object(speech, "speakMessage") as speak,
		):
			IL.announce(US, ES)
		speak.assert_not_called()

	def test_option_in_schema_validation_and_panel(self) -> None:
		self.assertIs(conf.defaults["keyboard"]["announceInputLanguageChanges"], True)
		data = {"keyboard": {"announceInputLanguageChanges": "no"}}
		validation.validate(data, conf.defaults)
		self.assertIs(data["keyboard"]["announceInputLanguageChanges"], False)
		data = {"keyboard": {"announceInputLanguageChanges": "quizá"}}
		validation.validate(data, conf.defaults)
		self.assertNotIn("announceInputLanguageChanges", data["keyboard"])
		from tiresias.gui import settings as S

		keys = [f.key for f in S.KeyboardPanel.getFields(S.KeyboardPanel.__new__(S.KeyboardPanel))]
		self.assertIn("announceInputLanguageChanges", keys)
		self.assertEqual(keys.index("announceInputLanguageChanges"), keys.index("announceToggleKeys") + 1)


# ====================================================================== escritorios virtuales
class _Timers:
	def __init__(self) -> None:
		self.pending: dict[int, tuple] = {}
		self.n = 0

	def callLater(self, ms, func, *args, **kwargs) -> int:
		self.n += 1
		self.pending[self.n] = (ms, func, args, kwargs)
		return self.n

	def cancel(self, tid) -> None:
		self.pending.pop(tid, None)

	def fire(self) -> None:
		items, self.pending = list(self.pending.values()), {}
		for _ms, func, args, kwargs in items:
			func(*args, **kwargs)


class VirtualDesktopTests(unittest.TestCase):
	def setUp(self) -> None:
		VD._pendingName = ""
		VD._timer = None
		VD._lastAnnounced = ("", 0.0)
		VD._lastTitleTime = 0.0
		self.timers = _Timers()
		from tiresias import queue_handler, speech

		self.patches = [
			mock.patch.object(queue_handler, "callLater", self.timers.callLater),
			mock.patch.object(queue_handler, "cancelCallLater", self.timers.cancel),
			mock.patch.object(speech, "speakMessage"),
		]
		for p in self.patches:
			p.start()
		self.speak = speech.speakMessage

	def tearDown(self) -> None:
		for p in reversed(self.patches):
			p.stop()

	def test_registry_names(self) -> None:
		a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
		blob = a.bytes_le + b.bytes_le + c.bytes_le
		ids = VD.parseGuids(blob)
		self.assertEqual(ids, [a, b, c])
		self.assertEqual(VD.desktopName(b, ids, {}), "Escritorio 2")
		self.assertEqual(VD.desktopName(b, ids, {b: "Trabajo"}), "Trabajo")
		self.assertEqual(VD.desktopName(None, ids, {}), "")
		self.assertEqual(VD.parseGuids(None), [])

	def test_several_events_one_announcement(self) -> None:
		VD.onNameChange("Escritorio 2")
		VD.onNameChange("Escritorio 2")
		self.assertEqual(len(self.timers.pending), 1)
		ms = next(iter(self.timers.pending.values()))[0]
		self.assertEqual(ms, VD.ANNOUNCE_DELAY_MS)
		self.timers.fire()
		self.speak.assert_called_once_with("Escritorio 2")

	def test_last_name_wins(self) -> None:
		# Control+Windows+Flecha derecha dos veces seguidas.
		VD.onNameChange("Escritorio 2")
		VD.onNameChange("Escritorio 3")
		self.timers.fire()
		self.speak.assert_called_once_with("Escritorio 3")

	def test_empty_title_after_a_name_is_ignored(self) -> None:
		VD.onNameChange("Trabajo")
		self.timers.fire()
		VD.onNameChange("")  # el título vuelve a quedar vacío
		self.assertEqual(self.timers.pending, {})
		self.speak.assert_called_once_with("Trabajo")

	def test_empty_title_uses_the_registry(self) -> None:
		with mock.patch.object(VD, "registryDesktopName", return_value="Escritorio 4"):
			VD.onNameChange("")
			self.timers.fire()
		self.speak.assert_called_once_with("Escritorio 4")

	def test_same_name_not_repeated_immediately(self) -> None:
		VD.onNameChange("Escritorio 2")
		self.timers.fire()
		VD.onNameChange("Escritorio 2")
		self.timers.fire()
		self.assertEqual(self.speak.call_count, 1)
		VD.onNameChange("Escritorio 1")
		self.timers.fire()
		self.assertEqual(self.speak.call_count, 2)

	def test_hook_thread_filters_the_desktop_window(self) -> None:
		from tiresias import queue_handler

		desk = VD.desktopWindow()
		with (
			mock.patch.object(queue_handler, "queueFunction") as q,
			mock.patch.object(VD, "_SUPPORTED", True),
			mock.patch.object(VD, "readDesktopTitle", return_value="Escritorio 3"),
		):
			winevents.onWinEvent(msaa.EVENT_OBJECT_NAMECHANGE, desk, msaa.OBJID_WINDOW, msaa.CHILDID_SELF, 0)
			q.assert_called_once_with(VD.onNameChange, "Escritorio 3")
			q.reset_mock()
			# Un hijo del escritorio: nada.
			winevents.onWinEvent(msaa.EVENT_OBJECT_NAMECHANGE, desk, msaa.OBJID_CLIENT, 5, 0)
			q.assert_not_called()

	def test_desktop_check_is_cheap_and_exact(self) -> None:
		with mock.patch.object(VD, "_SUPPORTED", True):
			self.assertTrue(VD.isDesktopNameChange(VD.desktopWindow()))
			self.assertFalse(VD.isDesktopNameChange(0))
			self.assertFalse(VD.isDesktopNameChange(VD.desktopWindow() + 4))
		with mock.patch.object(VD, "_SUPPORTED", False):
			self.assertFalse(VD.isDesktopNameChange(VD.desktopWindow()))


if __name__ == "__main__":
	unittest.main()
