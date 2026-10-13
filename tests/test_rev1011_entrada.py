"""Pruebas de la revisión de la entrada y las órdenes (1.0.11).

- C1: ganchos de bajo nivel en su hilo; detección y reinstalación del gancho perdido.
- A1: modificadores olvidados al cambiar de escritorio y validados con GetAsyncKeyState.
- A2: las teclas no se adelantan a las órdenes que reenvían su tecla (Retroceso, Word, Outlook).
- M1: la ayuda de entrada y la captura de gestos no dejan pasar modificadores ni la doble pulsación.
- M2: los bloqueos se leen de Windows; Bloq Num pasa en la ayuda de entrada.
- M3: cadena desfasada tras cambiar de ventana.
- M4: órdenes del objeto con el foco en Gestos de entrada.
- M5: caracteres Unicode inyectados (VK_PACKET).
- M6: teclas especiales de Windows (StickyKeys).
- M7: deslizar con dos dedos en el panel táctil no hereda las órdenes de la pantalla.
- B1-B11: pasar la siguiente tecla, pulsaciones repetidas, teclas muertas, AltGr,
  Mayúsculas sola, capas, teclas capturadas, modo dormir, mapa JAWS, superposición táctil.

No instala ganchos reales: todo se prueba con funciones y objetos simulados.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev1011_entrada``
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_rev1011_test_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()

from tiresias import queue_handler, winapi  # noqa: E402
from tiresias.baseobject import ScriptableObject, script  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.input import core as inputCore  # noqa: E402
from tiresias.input import hooks  # noqa: E402

VK_A = 0x41
VK_B = 0x42
VK_BACK = 0x08
VK_F5 = 0x74
VK_LSHIFT = 0xA0
VK_LCONTROL = 0xA2
VK_LALT = 0xA4
VK_LWIN = 0x5B


class _ConfValue:
	def __init__(self, section: str, key: str, value) -> None:
		self.section, self.key, self.value = section, key, value

	def __enter__(self):
		self.old = conf[self.section][self.key]
		conf[self.section][self.key] = self.value
		return self

	def __exit__(self, *exc) -> None:
		conf[self.section][self.key] = self.old


class _Queue:
	"""Sustituye la cola del núcleo: guarda las funciones y las ejecuta a mano."""

	def __init__(self) -> None:
		self.items: list = []

	def __call__(self, func, *args, **kwargs) -> None:
		self.items.append((func, args, kwargs))

	def names(self) -> list[str]:
		return [getattr(f, "__name__", repr(f)) for f, _a, _k in self.items]

	def run(self) -> None:
		while self.items:
			func, args, kwargs = self.items.pop(0)
			func(*args, **kwargs)


class _Scripts(ScriptableObject):
	"""Objeto de la cadena con órdenes de prueba."""

	def __init__(self, log: list) -> None:
		super().__init__()
		self.log = log

	@script(gesture="kb:backspace")
	def script_back(self, gesture) -> None:
		# Sin descripción, como las del cursor: reenvía su tecla (intercepta).
		self.log.append("back")
		gesture.send()

	@script(description="Orden con descripción", gesture="kb:f5")
	def script_describe(self, gesture) -> None:
		self.log.append("describe")

	@script(description="Orden de Tiresias", gesture="kb:tiresias+t")
	def script_title(self, gesture) -> None:
		self.log.append("title")


class _ManagerCase(unittest.TestCase):
	def setUp(self) -> None:
		self.m = inputCore.InputManager()
		self.log: list = []
		self.scripts = _Scripts(self.log)
		self.m.chain = [self.scripts]
		self.q = _Queue()
		patches = [
			mock.patch.object(inputCore.queue_handler, "queueFunction", self.q),
			mock.patch.object(inputCore.winapi, "sendInputs"),
			mock.patch.object(inputCore.InputManager, "_stickyFlags", return_value=0),
			mock.patch.object(inputCore.InputManager, "_readToggleState", return_value=None),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)
		self.down: set[int] = set()
		p = mock.patch.object(inputCore.winapi, "isKeyDown", side_effect=lambda vk: vk in self.down)
		p.start()
		self.addCleanup(p.stop)

	def key(self, vk: int, up: bool = False, extended: bool = False, scan: int = 0) -> bool:
		flags = winapi.LLKHF_EXTENDED if extended else 0
		return self.m._onKey(vk, scan, flags, up, False)

	def press(self, vk: int, **kw) -> bool:
		swallowed = self.key(vk, **kw)
		self.key(vk, up=True, **kw)
		return swallowed

	def mod(self, vk: int, up: bool = False) -> bool:
		if up:
			self.down.discard(vk)
		else:
			self.down.add(vk)
		return self.key(vk, up=up)


# ====================================================================== C1
class HookLossTests(unittest.TestCase):
	def test_hook_seems_lost(self) -> None:
		# El gancho vio la última entrada: no hay pérdida.
		self.assertFalse(hooks.hookSeemsLost(1000, 1000, 5000))
		self.assertFalse(hooks.hookSeemsLost(1000, 1200, 5000))
		# Entrada reciente que el gancho no vio (pero aún muy reciente para juzgar).
		self.assertFalse(hooks.hookSeemsLost(5000, 1000, 5100))
		# Entrada que el gancho no vio hace tiempo: perdido.
		self.assertTrue(hooks.hookSeemsLost(5000, 1000, 6000))
		# Diferencia pequeña: no basta.
		self.assertFalse(hooks.hookSeemsLost(2000, 1000, 6000))
		self.assertFalse(hooks.hookSeemsLost(None, 0, 6000))
		# Vuelta a cero de GetTickCount (49,7 días).
		self.assertTrue(hooks.hookSeemsLost(3000, 0xFFFFF000, 4000))
		self.assertFalse(hooks.hookSeemsLost(0xFFFFF000, 100, 0xFFFFF900))

	def _hooks(self, unhookResults: list[bool]):
		ll = hooks.LowLevelHooks()
		ll._threadId = 1
		ll._kbHook, ll._mouseHook = 11, 12
		results = list(unhookResults)
		ll._unhook = mock.Mock(side_effect=lambda h: results.pop(0))
		ll._setHook = mock.Mock(side_effect=[21, 22])
		return ll

	def test_reinstall_after_real_loss_announces(self) -> None:
		ll = self._hooks([False, True])  # el de teclado ya no existía
		with mock.patch.object(hooks, "_announce") as announce:
			ll._reinstall()
		self.assertEqual((ll._kbHook, ll._mouseHook), (21, 22))
		self.assertEqual(ll.recoveredCount, 1)
		announce.assert_called_once()
		self.assertIn("recuperado", announce.call_args[0][0])

	def test_false_alarm_is_silent_with_backoff(self) -> None:
		ll = self._hooks([True, True])
		with mock.patch.object(hooks, "_announce") as announce:
			ll._reinstall()
		announce.assert_not_called()
		self.assertEqual(ll.silentReinstalls, 1)
		self.assertGreater(ll._backoffUntil, time.monotonic())

	def test_check_requires_two_suspicions_and_normal_desktop(self) -> None:
		ll = hooks.LowLevelHooks()
		ll._threadId = 1
		ll._kbHook = ll._mouseHook = 5
		ll.lastHookTick = 1000
		with (
			mock.patch.object(hooks, "lastInputTick", return_value=5000),
			mock.patch.object(hooks, "tickCount", return_value=7000),
			mock.patch.object(hooks, "isNormalInputDesktop", return_value=True),
			mock.patch.object(ll, "requestReinstall", return_value=True) as req,
		):
			self.assertFalse(ll.checkOnce())
			self.assertTrue(ll.checkOnce())
			req.assert_called_once()
		with (
			mock.patch.object(hooks, "lastInputTick", return_value=5000),
			mock.patch.object(hooks, "tickCount", return_value=7000),
			mock.patch.object(hooks, "isNormalInputDesktop", return_value=False),
			mock.patch.object(ll, "requestReinstall") as req,
		):
			ll.checkOnce()
			ll.checkOnce()
			req.assert_not_called()

	def test_failed_install_is_retried_and_announced_once(self) -> None:
		ll = hooks.LowLevelHooks()
		ll._threadId = 1
		ll._setHook = mock.Mock(return_value=None)
		with mock.patch.object(hooks, "_announce") as announce:
			self.assertFalse(ll._install())
			self.assertFalse(ll._install())
		announce.assert_called_once()
		with mock.patch.object(ll, "requestReinstall", return_value=True) as req:
			self.assertTrue(ll.checkOnce())
			req.assert_called_once()

	def test_callbacks_live_in_low_level_hooks(self) -> None:
		ht = hooks.HookThread()
		cb = lambda *a: False  # noqa: E731
		ht.keyCallback = cb
		self.assertIs(ht.lowLevel.keyCallback, cb)
		self.assertIsNot(ht.lowLevel, hooks.hookThread.lowLevel)
		self.assertEqual(hooks.LowLevelHooks.threadName, "GanchoTeclado")


# ====================================================================== A1
class StaleModifierTests(_ManagerCase):
	def test_desktop_switch_forgets_modifiers(self) -> None:
		self.mod(VK_LCONTROL)
		self.mod(VK_LALT)
		self.assertEqual(self.m._mods, {"control", "alt"})
		# Control+Alt+Supr: las liberaciones se pierden en el escritorio seguro.
		self.m.onDesktopSwitch()
		self.m._resetPending = True  # (onDesktopSwitch ya lo pone)
		self.down.clear()
		self.key(VK_F5)
		self.assertEqual(self.m._mods, set())
		self.assertFalse(self.m._tiresiasDown)

	def test_get_async_key_state_discards_stale_modifiers(self) -> None:
		self.mod(VK_LWIN)
		self.down.discard(VK_LWIN)  # Windows+L: la tecla Windows ya no está pulsada
		self.press(VK_F5)
		self.assertNotIn("windows", self.m._mods)
		self.q.run()
		self.assertEqual(self.log, ["describe"])

	def test_held_modifier_is_kept(self) -> None:
		self.mod(VK_LCONTROL)
		self.m._validateModifiers()
		self.assertEqual(self.m._mods, {"control"})

	def test_desktop_switch_calls_input_manager(self) -> None:
		from tiresias.a11y import system, winevents

		with (
			mock.patch.object(inputCore.manager, "onDesktopSwitch") as switch,
			mock.patch.object(system, "isSecureDesktopActive", return_value=True),
			mock.patch("tiresias.speech.speakMessage"),
		):
			winevents._onDesktopSwitch()
		switch.assert_called_once()


# ====================================================================== A2
class KeyOrderTests(_ManagerCase):
	def test_unbound_key_waits_for_intercepting_script(self) -> None:
		sent: list[str] = []
		with mock.patch.object(inputCore.KeyboardGesture, "send", lambda g: sent.append(g.mainKeyName)):
			self.assertTrue(self.key(VK_BACK))  # Retroceso: orden que reenvía la tecla
			self.key(VK_BACK, up=True)
			# La «a» no pasa ya: se encola detrás del Retroceso.
			self.assertTrue(self.key(VK_A))
			self.assertTrue(self.key(VK_A, up=True))
			self.q.run()
		self.assertEqual(sent, ["backspace", "a"])
		self.assertEqual(self.m._interceptPending, 0)
		# Sin órdenes pendientes, las teclas vuelven a pasar directamente.
		self.assertFalse(self.key(VK_B))

	def test_described_script_does_not_hold(self) -> None:
		self.assertTrue(self.key(VK_F5))
		self.assertEqual(self.m._interceptPending, 0)
		self.assertFalse(self.key(VK_A))

	def test_is_intercepting_script(self) -> None:
		self.assertTrue(inputCore.isInterceptingScript(self.scripts.script_back))
		self.assertFalse(inputCore.isInterceptingScript(self.scripts.script_describe))

		def f(g):
			"""Con descripción."""

		f.interceptsGesture = True
		self.assertTrue(inputCore.isInterceptingScript(f))

	def test_deferred_send_keeps_order(self) -> None:
		sent: list[str] = []
		with mock.patch.object(inputCore.KeyboardGesture, "send", lambda g: sent.append(g.mainKeyName)):
			release = self.m.deferInterceptedSend()
			self.assertTrue(self.key(VK_A))
			self.assertTrue(self.key(VK_B))
			self.q.run()
			self.assertEqual(sent, [])  # esperan a la orden diferida
			sent.append("alt+1")  # la orden manda su tecla...
			release()  # ...y libera las demás, en orden
			release()  # una segunda llamada no hace nada
		self.assertEqual(sent, ["alt+1", "a", "b"])
		self.assertEqual(self.m._deferCount, 0)

	def test_word_and_outlook_scripts_intercept(self) -> None:
		from tiresias.appmodules import outlook, winword

		self.assertTrue(inputCore.isInterceptingScript(winword.WordDocument.script_formatShortcut))
		for n in range(1, 7):
			self.assertTrue(inputCore.isInterceptingScript(getattr(outlook.AppModule, f"script_field{n}")))

	def test_word_format_baseline(self) -> None:
		from tiresias.appmodules import winword

		winword._formatBaselines.clear()
		now = time.monotonic()
		winword._storeFormatBaseline(7, now - 1, {"bold": 0})
		self.assertEqual(winword._formatBaseline(7, now), {"bold": 0})
		# Pedida después de enviar el atajo: no sirve como «antes».
		self.assertIsNone(winword._formatBaseline(7, now - 2))
		# Demasiado antigua.
		self.assertIsNone(winword._formatBaseline(7, now + winword.FORMAT_BASELINE_MAX_AGE + 5))
		# Una instantánea más antigua no sustituye a otra más reciente.
		winword._storeFormatBaseline(7, now - 5, {"bold": 1})
		self.assertEqual(winword._formatBaseline(7, now), {"bold": 0})
		winword._formatBaselines.clear()

	def test_word_sends_key_first(self) -> None:
		from tiresias.appmodules import _office, winword

		order: list[str] = []
		gesture = mock.Mock()
		gesture.send = lambda: order.append("send")
		doc = mock.Mock(spec=["_hwnd"])
		doc._hwnd = lambda: 5
		with _ConfValue("officeWord", "reportFormattingShortcuts", True), mock.patch.object(_office, "callAsync", side_effect=lambda *a, **k: order.append("read")):
			winword.WordDocument.script_formatShortcut(doc, gesture)
		self.assertEqual(order, ["send", "read"])


# ====================================================================== M1
class InputHelpTests(_ManagerCase):
	def test_modifiers_are_swallowed_in_input_help(self) -> None:
		self.m.inputHelp = True
		self.assertTrue(self.mod(VK_LWIN))
		self.assertTrue(self.mod(VK_LWIN, up=True))  # Windows sola no abre Inicio
		self.assertTrue(self.mod(VK_LALT))
		self.assertTrue(self.key(0x73))  # Alt+F4: no se ejecuta
		self.assertTrue(self.key(0x73, up=True))
		self.assertTrue(self.mod(VK_LALT, up=True))
		self.assertIn("_speakText", self.q.names())
		self.assertEqual(self.log, [])

	def test_modifier_swallowed_while_capturing_gesture(self) -> None:
		captured: list = []
		self.m.captureFunc = captured.append
		self.assertTrue(self.mod(VK_LCONTROL))
		self.m.captureFunc = None  # la captura termina con el Control pulsado
		self.assertTrue(self.mod(VK_LCONTROL, up=True))  # su liberación tampoco llega
		self.assertEqual(self.m._swallowedMods, set())

	def test_no_native_double_press_in_input_help(self) -> None:
		self.m.inputHelp = True
		with _ConfValue("keyboard", "useCapsLockAsModifier", True):
			for _i in range(2):
				self.key(winapi.VK_CAPITAL)
				self.key(winapi.VK_CAPITAL, up=True)
		inputCore.winapi.sendInputs.assert_not_called()


# ====================================================================== M2
class ToggleKeyTests(_ManagerCase):
	def test_swallowed_toggle_does_not_change_state(self) -> None:
		self.m.inputHelp = True
		with _ConfValue("keyboard", "useCapsLockAsModifier", False):
			self.assertTrue(self.key(winapi.VK_CAPITAL))
		self.assertFalse(self.m._capsToggled)

	def test_numlock_passes_in_input_help(self) -> None:
		self.m.inputHelp = True
		self.assertFalse(self.key(winapi.VK_NUMLOCK))
		self.assertTrue(self.m._numToggled)

	def test_real_state_wins(self) -> None:
		with _ConfValue("keyboard", "useCapsLockAsModifier", False), _ConfValue("keyboard", "announceToggleKeys", True):
			self.assertFalse(self.key(winapi.VK_CAPITAL))
			self.assertTrue(self.m._capsToggled)  # previsión inmediata
			with mock.patch.object(inputCore.InputManager, "_readToggleState", return_value=False):
				self.q.run()  # se lee el estado real: estaba desincronizado
		self.assertFalse(self.m._capsToggled)

	def test_frozen_core_still_tracks_toggle(self) -> None:
		with mock.patch.object(inputCore.InputManager, "_coreFrozen", return_value=True):
			self.assertFalse(self.key(winapi.VK_NUMLOCK))
		self.assertTrue(self.m._numToggled)


# ====================================================================== M3
class StaleChainTests(_ManagerCase):
	def test_other_foreground_uses_global_chain(self) -> None:
		globalOnly = _Scripts(self.log)
		self.m._globalChain = [globalOnly]
		self.m._chainFg = 100
		self.assertIs(self.m._chainFor(100), self.m.chain)
		self.assertEqual(self.m._chainFor(200), [globalOnly])
		self.assertIs(self.m._chainFor(0), self.m.chain)
		self.m._chainFg = 0
		self.assertIs(self.m._chainFor(200), self.m.chain)


# ====================================================================== M4
class GestureDialogTests(unittest.TestCase):
	def test_focus_classes_are_listed(self) -> None:
		from tiresias import api
		from tiresias.gui import config_dialogs

		class Base(ScriptableObject):
			@script(description="Base", gesture="kb:f9")
			def script_base(self, gesture) -> None:
				pass

		class Focused(Base):
			@script(description="Propia del objeto", gesture="kb:f8")
			def script_own(self, gesture) -> None:
				pass

		obj = Focused()
		with mock.patch.object(api, "getFocusObject", return_value=obj), mock.patch.object(api, "getFocusAncestors", return_value=[]):
			classes = [c for c, _cat in config_dialogs._focusScriptClasses([])]
			self.assertEqual(classes, [Focused, Base])
			# Una clase ya incluida (o sus bases) no se repite.
			self.assertEqual([c for c, _cat in config_dialogs._focusScriptClasses([Focused])], [])
		infos = config_dialogs._scriptsForClass(Focused, "x", ownOnly=True)
		self.assertEqual([i.name for i in infos], ["own"])


# ====================================================================== M5
class PacketTests(_ManagerCase):
	def test_packet_is_text_not_a_command(self) -> None:
		self.assertFalse(self.key(inputCore.VK_PACKET, scan=ord("h")))
		typed = [a for f, a, _k in self.q.items if f is inputCore._typedCharacter]
		self.assertEqual(typed, [("h",)])
		self.assertNotIn("_speakText", self.q.names())

	def test_surrogate_pair(self) -> None:
		self.key(inputCore.VK_PACKET, scan=0xD83D)
		self.key(inputCore.VK_PACKET, scan=0xDE00)
		typed = [a[0] for f, a, _k in self.q.items if f is inputCore._typedCharacter]
		self.assertEqual(typed, ["\U0001f600"])


# ====================================================================== M6
class StickyKeysTests(_ManagerCase):
	def test_latched_modifier_applies_to_next_key(self) -> None:
		seen: list = []
		with mock.patch.object(inputCore.InputManager, "_stickyFlags", return_value=inputCore.SKF_STICKYKEYSON | inputCore.SKF_TRISTATE):
			self.mod(VK_LCONTROL)
			self.mod(VK_LCONTROL, up=True)  # sola: queda enganchada
			self.assertEqual(self.m._latched, {"control"})
			with mock.patch.object(self.m, "findScript", side_effect=lambda g, fg=None: seen.append(g.normalizedKeys)):
				self.key(VK_A)
			self.assertEqual(seen, ["control+a"])
			self.assertEqual(self.m._latched, set())
			# Dos veces: bloqueada hasta pulsarla otra vez.
			self.mod(VK_LCONTROL)
			self.mod(VK_LCONTROL, up=True)
			self.mod(VK_LCONTROL)
			self.mod(VK_LCONTROL, up=True)
			self.assertEqual(self.m._locked, {"control"})

	def test_tiresias_key_latches(self) -> None:
		with mock.patch.object(inputCore.InputManager, "_stickyFlags", return_value=inputCore.SKF_STICKYKEYSON), _ConfValue("keyboard", "useCapsLockAsModifier", True):
			self.press(winapi.VK_CAPITAL)
			self.assertEqual(self.m._latched, {"tiresias"})
			self.assertTrue(self.key(0x54))  # T: Tiresias+T
			self.q.run()
		self.assertEqual(self.log, ["title"])
		inputCore.winapi.sendInputs.assert_not_called()


# ====================================================================== M7
class TouchpadTests(unittest.TestCase):
	def test_two_finger_flicks_do_not_inherit_screen(self) -> None:
		from tiresias.touch.gestures import identifiersFor

		ids = identifiersFor("2finger_flickDown", "object", "tp")
		self.assertEqual(ids, ["tp(object):2finger_flickdown", "tp:2finger_flickdown"])
		self.assertTrue([i for i in identifiersFor("3finger_flickUp", "object", "tp") if i.startswith("ts")])
		self.assertTrue([i for i in identifiersFor("2finger_tap", "object", "tp") if i.startswith("ts")])
		self.assertTrue([i for i in identifiersFor("2finger_flickDown", "object", "ts") if i.startswith("ts")])


# ====================================================================== B
class SmallFixesTests(_ManagerCase):
	def test_pass_next_key_passes_tiresias_combination(self) -> None:
		self.m.passNextKey = True
		with _ConfValue("keyboard", "useCapsLockAsModifier", True):
			self.assertFalse(self.key(winapi.VK_INSERT, extended=True))  # Insertar llega a la aplicación
			self.assertFalse(self.key(0x54))  # T con Insertar pulsada: también
			self.assertFalse(self.key(0x54))  # repetición automática: sigue pasando
			self.assertFalse(self.key(0x54, up=True))
			self.assertFalse(self.key(winapi.VK_INSERT, up=True, extended=True))
		self.assertFalse(self.m._tiresiasDown)
		self.assertEqual(self.m._passing, set())
		self.q.run()
		self.assertEqual(self.log, [])
		self.assertTrue(self.press(VK_F5))  # vuelve lo normal

	def test_autorepeat_is_not_a_double_press(self) -> None:
		self.key(VK_F5)
		self.key(VK_F5)  # repetición (sin soltar)
		self.q.run()
		self.assertEqual(self.m.getLastScriptRepeatCount(), 0)
		self.key(VK_F5, up=True)
		self.key(VK_F5)
		self.q.run()
		self.assertEqual(self.m.getLastScriptRepeatCount(), 1)

	def test_unbound_key_breaks_double_press(self) -> None:
		self.press(VK_F5)
		self.press(VK_A)
		self.press(VK_F5)
		self.q.run()
		self.assertEqual(self.m.getLastScriptRepeatCount(), 0)

	def test_compose_dead_key(self) -> None:
		c = inputCore.composeDeadKey
		self.assertEqual(c("´", "a"), "á")
		self.assertEqual(c("´", "A"), "Á")
		self.assertEqual(c("¨", "u"), "ü")
		self.assertEqual(c("´", "n"), "´n")  # sin forma acentuada: los dos
		self.assertEqual(c("´", "1"), "´1")
		self.assertEqual(c("´", " "), "´")
		self.assertEqual(c(None, "a"), "a")

	def test_dead_key_kept_when_key_is_swallowed(self) -> None:
		self.m._deadKey = "´"
		self.press(VK_F5)  # orden: la tecla no llega a la aplicación
		self.assertEqual(self.m._deadKey, "´")

	def test_shift_alone_not_after_tiresias_key(self) -> None:
		with _ConfValue("keyboard", "useCapsLockAsModifier", True):
			self.mod(VK_LSHIFT)
			self.press(winapi.VK_CAPITAL)
			self.mod(VK_LSHIFT, up=True)
		self.assertNotIn("_pauseSpeechToggle", self.q.names())

	def test_shift_alone_not_after_mouse_click(self) -> None:
		self.mod(VK_LSHIFT)
		self.m._onMouse(0x0201, 0, 0, False)
		self.mod(VK_LSHIFT, up=True)
		self.assertNotIn("_pauseSpeechToggle", self.q.names())

	def test_passed_key_release_is_not_swallowed(self) -> None:
		with _ConfValue("keyboard", "useCapsLockAsModifier", True):
			self.key(winapi.VK_CAPITAL)
			self.assertTrue(self.key(0x54))  # Tiresias+T: capturada
			self.key(winapi.VK_CAPITAL, up=True)
			self.m.chain = []
			self.assertFalse(self.key(0x54))  # repetición sin Tiresias: pasa
			self.assertFalse(self.key(0x54, up=True))  # su liberación también

	def test_sleep_mode_passes_unbound_tiresias_combination(self) -> None:
		self.m.chain = [inputCore._SleepModeFilter(self.scripts)]
		with _ConfValue("keyboard", "useCapsLockAsModifier", True):
			self.key(winapi.VK_CAPITAL)
			self.assertFalse(self.key(0x55))  # Tiresias+U sin orden permitida
			self.key(0x55, up=True)
			self.key(winapi.VK_CAPITAL, up=True)

	def test_altgr_captured_as_control_alt(self) -> None:
		captured: list = []
		self.m.captureFunc = captured.append
		self.key(0xA2, scan=0x21D)
		self.down.add(0xA5)
		self.key(0xA5, extended=True)
		self.m.captureFunc = captured.append
		self.key(0x32)
		self.q.run()
		self.assertEqual([g.normalizedKeys for g in captured], ["control+alt+2"])


class LayerRaceTests(unittest.TestCase):
	def test_stale_capture_forwards_to_current_layer(self) -> None:
		from tiresias import config_plugin

		plugin = config_plugin.GlobalPlugin.__new__(config_plugin.GlobalPlugin)
		plugin._layer = None
		plugin._layerName = ""
		plugin._layerGen = 0
		plugin._captureRef = None
		mgr = inputCore.InputManager()
		keysSeen: list = []
		with (
			mock.patch.object(inputCore, "manager", mgr),
			mock.patch.object(queue_handler, "callLater"),
			mock.patch("tiresias.audio.tones.beep"),
			mock.patch.object(config_plugin.GlobalPlugin, "_onLayerKey", lambda self, g: keysSeen.append((g, self._layer))),
		):
			plugin._startLayer(None, "capas")
			first = mgr.captureFunc
			sub = {"x": ("equis", "global:dateTime")}
			first("v")  # la primera tecla abre una subcapa...
			plugin._startLayer(sub, "sub")
			second = mgr.captureFunc
			self.assertIsNot(first, second)
			first("1")  # ...y la segunda, encolada con la captura antigua, va a la subcapa
			self.assertIsNone(mgr.captureFunc)
		self.assertEqual([k for k, _l in keysSeen], ["v", "1"])
		self.assertIs(keysSeen[1][1], sub)


class JawsLayoutTests(unittest.TestCase):
	def test_no_command_loses_its_only_key(self) -> None:
		from tiresias import gesture_layouts
		from tiresias.global_commands import GlobalCommands, commands
		from tiresias.input.gestures import KeyboardGesture

		def effective(layout: str) -> set[str]:
			found = set()
			for gid, _name in GlobalCommands.iterClassGestures():
				pass
			ids = {g for g, _n in GlobalCommands.iterClassGestures() if g.startswith("kb")}
			ids |= {g for g in (commands.__dict__.get("_instanceGestures") or {}) if g.startswith("kb")}
			for gid in ids:
				prefix, keysPart = gid.split(":", 1)
				if prefix.startswith("kb(") and prefix != f"kb({layout})":
					continue
				g = KeyboardGesture(0, 0, False, frozenset(), "x", layout)
				g.identifiers = [f"kb({layout}):{keysPart}", f"kb:{keysPart}"]
				func = commands.getScript(g)
				if func is not None:
					found.add(func.__name__[7:])
			return found

		old = conf["keyboard"]["gestureLayout"]
		try:
			conf["keyboard"]["gestureLayout"] = "tiresias"
			gesture_layouts.apply()
			own = {layout: effective(layout) for layout in ("desktop", "laptop")}
			conf["keyboard"]["gestureLayout"] = "jaws"
			gesture_layouts.apply()
			jaws = {layout: effective(layout) for layout in ("desktop", "laptop")}
		finally:
			conf["keyboard"]["gestureLayout"] = old
			gesture_layouts.apply()
		for layout in ("desktop", "laptop"):
			self.assertEqual(own[layout] - jaws[layout], set(), layout)
		self.assertNotIn("kb:tiresias+control+x", gesture_layouts.LAYOUTS["jaws"])


class OverlayFrozenTests(unittest.TestCase):
	def test_core_frozen(self) -> None:
		from tiresias.touch import overlay

		with mock.patch.object(queue_handler, "busy", True), mock.patch.object(queue_handler, "lastPumpTime", time.monotonic() - 10):
			self.assertTrue(overlay.coreFrozen())
		with mock.patch.object(queue_handler, "busy", False):
			self.assertFalse(overlay.coreFrozen())

	def test_overlay_lets_touches_through_when_frozen(self) -> None:
		from tiresias.touch import overlay

		win = overlay.TouchInputWindow(lambda events: None, show=False)
		win.hwnd = 0
		with mock.patch.object(overlay, "coreFrozen", return_value=True), mock.patch.object(overlay.W, "cursorPos", return_value=(0, 0)), mock.patch.object(overlay.W, "mouseButtonsDown", return_value=False), mock.patch.object(overlay.W, "virtualScreen", return_value=win._screen):
			win._maintain(0)
			self.assertTrue(win.isPassthrough)
			win._lastMouseActivity = 0.0
			win._maintain(0)  # sigue sin capturar mientras el núcleo esté bloqueado
			self.assertTrue(win.isPassthrough)


if __name__ == "__main__":
	unittest.main()
