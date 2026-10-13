"""Revisión 1.0.6 del núcleo y la entrada: pruebas de regresión.

- Registro: el archivo se escribe en un hilo propio (el núcleo llegó a quedarse
  6 s parado en ``tell()`` del archivo de registro) y los niveles «OFF» y
  «CRITICAL» tienen efecto.
- Modo dormir: ni el modo exploración ni los complementos hablan; el primer
  plano se actualiza; el teclado y el ratón no anuncian nada.
- Gestos: una asignación general (de instancia o del usuario) vence a la de la
  distribución de la clase (mapa compatible con JAWS: Tiresias+Re Pág).
- AltGr solo con el Control falso del sistema.
- Posición de revisión al cambiar el foco sin objeto navegador propio.
- Fondo blanco, portapapeles y órdenes globales con objetos simulados.

No se envían teclas ni clics reales ni se toca el portapapeles del usuario.
Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_revision_nucleo -v``
"""

from __future__ import annotations

import copy
import logging
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_revnucleo_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]

from tiresias import a11y  # noqa: E402,F401  (registra las opciones)
from tiresias import api, events, textinfo  # noqa: E402
from tiresias.baseobject import ScriptableObject, script  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.objects.roles import Role  # noqa: E402


# ====================================================================== objetos simulados
class FakeApp:
	def __init__(self, sleeping: bool = False) -> None:
		self.sleepMode = sleeping
		self.processID = -1
		self.appName = "prueba"
		self.productName = "Prueba"
		self.productVersion = "1.0"
		self.calls: list[str] = []

	def event_gainFocus(self, obj, nextHandler) -> None:
		self.calls.append("gainFocus")
		nextHandler()


class FakeObj:
	"""Objeto accesible mínimo con texto (``StaticTextInfo``)."""

	def __init__(self, name: str = "Objeto", role: Role = Role.EDITABLETEXT, app: FakeApp | None = None, parent=None, text: str = "Hola mundo\nsegunda línea\n") -> None:
		self.name = name
		self.role = role
		self.appModule = app
		self.parent = parent
		self.value = ""
		self.description = ""
		self.states: set = set()
		self.location = (10, 20, 100, 30)
		self.children: list = []
		self.treeInterceptor = None
		self.keyboardShortcut = ""
		self.hasText = True
		self.isEditable = True
		self.roleText = ""
		self.positionInfo: dict = {}
		self.devInfo = ["nombre: " + name]
		self.actionName = "pulsar"
		self._text = text
		self.calls: list[str] = []
		self.next = self.previous = self.firstChild = None
		self.simpleNext = self.simplePrevious = self.simpleFirstChild = None
		self.simpleParent = parent

	@property
	def ancestors(self) -> list:
		out = []
		p = self.parent
		while p is not None:
			out.insert(0, p)
			p = p.parent
		return out

	def makeTextInfo(self, position):
		return textinfo.StaticTextInfo(self, position, self._text)

	def event_gainFocus(self) -> None:
		self.calls.append("gainFocus")

	def event_becomeNavigatorObject(self, isFocus: bool = False) -> None:
		pass

	def event_foreground(self) -> None:
		self.calls.append("foreground")

	def event_loseFocus(self) -> None:
		pass

	def setFocus(self) -> None:
		self.calls.append("setFocus")

	def doAction(self) -> bool:
		self.calls.append("doAction")
		return True

	def _prop(self, *a, **k):
		return ""


class FakeTI:
	passThrough = True

	def __init__(self) -> None:
		self.calls: list[str] = []

	def event_gainFocus(self, obj, nextHandler) -> None:
		self.calls.append("gainFocus")
		nextHandler()


class FakePlugin:
	def __init__(self) -> None:
		self.calls: list[str] = []

	def event_gainFocus(self, obj, nextHandler) -> None:
		self.calls.append("gainFocus")
		nextHandler()


class _Events(unittest.TestCase):
	def setUp(self) -> None:
		from tiresias.a11y import system
		from tiresias.input import core as inputCore
		from tiresias.plugins import handler as pluginHandler

		self.plugin = FakePlugin()
		self.ti = FakeTI()
		patches = [
			mock.patch.object(system, "isSecureObject", return_value=False),
			mock.patch("tiresias.appmodules.handler.handleForegroundApp"),
			mock.patch("tiresias.tree_interceptor.update", return_value=self.ti),
			mock.patch.object(inputCore, "manager", mock.Mock()),
			mock.patch.object(pluginHandler, "runningPlugins", [self.plugin]),
			mock.patch("tiresias.speech.cancelSpeech"),
			mock.patch("tiresias.presentation.speakObject"),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)
		api.setFocusObject(None, [])
		api.setForegroundObject(None)
		events._lastFocusAncestors = []
		events._lastFocusTime = 0.0
		self.addCleanup(api.setFocusObject, None, [])
		self.addCleanup(api.setForegroundObject, None)

	def test_modo_dormir_no_ejecuta_la_cadena(self) -> None:
		desktop = FakeObj("Escritorio", Role.DESKTOPPANE)
		awakeWin = FakeObj("Despierta", Role.WINDOW, FakeApp(), desktop)
		awake = FakeObj("campo", Role.EDITABLETEXT, awakeWin.appModule, awakeWin)
		app = FakeApp(sleeping=True)
		win = FakeObj("Dormida", Role.WINDOW, app, desktop)
		obj = FakeObj("campo dormido", Role.EDITABLETEXT, app, win)
		events.executeEvent("gainFocus", awake)
		self.assertIs(api.getForegroundObject(), awakeWin)
		self.plugin.calls.clear()
		self.ti.calls.clear()
		events.executeEvent("gainFocus", obj)
		self.assertIs(api.getFocusObject(), obj)
		# Ni el complemento global, ni el modo exploración, ni el objeto hablan.
		self.assertEqual(self.plugin.calls, [])
		self.assertEqual(self.ti.calls, [])
		self.assertEqual(obj.calls, [])
		self.assertEqual(app.calls, [])
		# El primer plano sí se actualiza: al volver a la ventana despierta se anuncia.
		self.assertIs(api.getForegroundObject(), win)
		awakeWin.calls.clear()
		events.executeEvent("gainFocus", awake)
		self.assertIs(api.getForegroundObject(), awakeWin)
		self.assertIn("foreground", awakeWin.calls)
		self.assertEqual(self.plugin.calls, ["gainFocus"])


# ====================================================================== api
class ReviewPositionTests(unittest.TestCase):
	def tearDown(self) -> None:
		api.setFocusObject(None, [])
		api.setNavigatorObject(None)

	def test_revision_sigue_al_foco_sin_navegador_propio(self) -> None:
		with mock.patch("tiresias.a11y.system.isSecureObject", return_value=False):
			api.setNavigatorObject(None)
		a = FakeObj("a", text="primero")
		b = FakeObj("b", text="segundo")
		api.setFocusObject(a, [])
		self.assertIs(api.getReviewPosition().obj, a)
		api.setFocusObject(b, [])
		self.assertIs(api.getReviewPosition().obj, b)


# ====================================================================== gestos
class GesturePriorityTests(unittest.TestCase):
	def _gesture(self, layout: str, keys: str):
		g = mock.Mock()
		g.identifiers = [f"kb({layout}):{keys}", f"kb:{keys}"]
		return g

	def test_instancia_general_vence_a_la_clase_por_distribucion(self) -> None:
		class Obj(ScriptableObject):
			@script(gesture="kb(desktop):tiresias+pageup")
			def script_clase(self, gesture) -> None:
				pass

			def script_instancia(self, gesture) -> None:
				pass

		o = Obj()
		self.assertEqual(o.getScript(self._gesture("desktop", "tiresias+pageup")).__name__, "script_clase")
		o.bindGesture("kb:tiresias+pageUp", "instancia")
		self.assertEqual(o.getScript(self._gesture("desktop", "tiresias+pageup")).__name__, "script_instancia")
		o.removeGestureBinding("kb:tiresias+pageUp")
		self.assertIsNone(o.getScript(self._gesture("desktop", "tiresias+pageup")))

	def test_usuario_general_vence_a_la_clase_por_distribucion(self) -> None:
		from tiresias.input import gestures

		class Obj2(ScriptableObject):
			@script(gesture="kb(laptop):tiresias+x")
			def script_clase(self, gesture) -> None:
				pass

			def script_usuario(self, gesture) -> None:
				pass

		old = copy.deepcopy(gestures.userMap._map)
		try:
			gestures.userMap.bind(gestures.UserGestureMap.classKey(Obj2), "kb:tiresias+x", "usuario")
			self.assertEqual(Obj2().getScript(self._gesture("laptop", "tiresias+x")).__name__, "script_usuario")
		finally:
			gestures.userMap._map = old

	def test_mapa_jaws_tiresias_re_pag_dice_el_titulo(self) -> None:
		from tiresias import gesture_layouts
		from tiresias.global_commands import commands
		from tiresias.input import core as inputCore
		from tiresias.input.gestures import KeyboardGesture

		old = conf["keyboard"]["gestureLayout"]
		with mock.patch.object(inputCore.manager, "updateChain"):
			try:
				conf["keyboard"]["gestureLayout"] = "jaws"
				gesture_layouts.apply()
				g = KeyboardGesture(0x21, 0, True, frozenset({"tiresias"}), "pageup", "desktop")
				self.assertEqual(commands.getScript(g).__name__, "script_title")
				g = KeyboardGesture(0x22, 0, True, frozenset({"tiresias"}), "pagedown", "laptop")
				self.assertEqual(commands.getScript(g).__name__, "script_reportStatusLine")
			finally:
				conf["keyboard"]["gestureLayout"] = old
				gesture_layouts.apply()
		g = KeyboardGesture(0x21, 0, True, frozenset({"tiresias"}), "pageup", "desktop")
		self.assertEqual(commands.getScript(g).__name__, "script_review_previousPage")


# ====================================================================== entrada
class InputTests(unittest.TestCase):
	def _manager(self):
		from tiresias.input import core as inputCore

		m = inputCore.InputManager()
		m.chain = []
		return m

	def test_altgr_solo_con_el_control_falso(self) -> None:
		from tiresias import winapi

		m = self._manager()
		# Alt derecha sin el Control falso (distribución sin AltGr): Alt normal.
		m._onKey(0xA5, 0x38, winapi.LLKHF_EXTENDED, False, False)
		self.assertFalse(m._altGr)
		m._onKey(0xA5, 0x38, winapi.LLKHF_EXTENDED, True, False)
		# Con AltGr el sistema manda antes un Control izquierdo falso.
		m._onKey(0xA2, 0x21D, 0, False, False)
		m._onKey(0xA5, 0x38, winapi.LLKHF_EXTENDED, False, False)
		self.assertTrue(m._altGr)
		self.assertNotIn("control", m._mods)
		m._onKey(0xA2, 0x21D, 0, True, False)
		m._onKey(0xA5, 0x38, winapi.LLKHF_EXTENDED, True, False)
		self.assertFalse(m._altGr)
		m.resetState()

	def test_modo_dormir_no_anuncia_teclas(self) -> None:
		from tiresias.input import core as inputCore

		m = self._manager()

		class Nothing:
			def getScript(self, gesture):
				return None

		queued: list = []
		old = conf["keyboard"]["speakCommandKeys"]
		conf["keyboard"]["speakCommandKeys"] = True
		try:
			with mock.patch.object(inputCore.queue_handler, "queueFunction", side_effect=lambda f, *a, **k: queued.append(f)):
				m.chain = [inputCore._SleepModeFilter(Nothing())]
				self.assertFalse(m._onKeyDown(0x74, 0x3F, False))  # F5: pasa a la aplicación
				self.assertNotIn(inputCore._speakText, queued)
				self.assertNotIn(inputCore._cancelSpeech, queued)
				m.chain = [Nothing()]
				self.assertFalse(m._onKeyDown(0x74, 0x3F, False))
				self.assertIn(inputCore._speakText, queued)
		finally:
			conf["keyboard"]["speakCommandKeys"] = old


# ====================================================================== ratón
class MouseSleepTests(unittest.TestCase):
	def test_no_lee_bajo_el_raton_en_modo_dormir(self) -> None:
		from tiresias import mouse

		obj = FakeObj("dormido", app=FakeApp(sleeping=True))
		with mock.patch("tiresias.objects.uia.getObjectFromPoint", return_value=obj), mock.patch("tiresias.speech.speakText") as speak, mock.patch("tiresias.speech.cancelSpeech"):
			mouse._reportAt(1, 1)
			speak.assert_not_called()
			obj.appModule.sleepMode = False
			mouse._lastText = ""
			mouse._reportAt(1, 1)
			speak.assert_called()
		api.setMouseObject(None)


# ====================================================================== registro
class LogTests(unittest.TestCase):
	def test_archivo_en_hilo_propio_y_niveles(self) -> None:
		from tiresias import log as logModule

		logger = logModule.log
		oldHandlers, oldLevel = list(logger.handlers), logger.level
		oldHooks = (sys.excepthook, threading.excepthook)
		folder = tempfile.mkdtemp(prefix="tiresias_log_")
		try:
			with mock.patch.object(paths, "logsDir", return_value=folder):
				logModule.initialize("INFO")
			self.assertFalse(any(isinstance(h, logging.FileHandler) for h in logger.handlers), "el archivo no se escribe en el hilo que registra")
			self.assertTrue(any(isinstance(h, logging.handlers.QueueHandler) for h in logger.handlers))
			logModule.getLogger("prueba").info("mensaje de prueba %d", 42)
			logModule.flush()
			logModule._stopListener()
			with open(os.path.join(folder, "tiresias.log"), encoding="utf-8") as f:
				self.assertIn("mensaje de prueba 42", f.read())
			logModule.setLevel("OFF")
			self.assertGreater(logger.level, logging.CRITICAL)
			logModule.setLevel("CRITICAL")
			self.assertEqual(logger.level, logging.CRITICAL)
		finally:
			logModule._stopListener()
			logger.handlers[:] = oldHandlers
			logger.setLevel(oldLevel)
			sys.excepthook, threading.excepthook = oldHooks
			shutil.rmtree(folder, ignore_errors=True)


# ====================================================================== formato y portapapeles
class FormattingClipboardTests(unittest.TestCase):
	def test_fondo_blanco_solo_al_volver_a_el(self) -> None:
		from tiresias import formatting

		white, yellow = 0xFFFFFF, 0x00FFFF
		self.assertEqual(formatting.describe({"backgroundColor": white}, {}), [])
		self.assertEqual(formatting.describe({"backgroundColor": white}, None), [])
		self.assertTrue(formatting.describe({"backgroundColor": yellow}, {}))
		self.assertEqual(formatting.describe({"backgroundColor": white}, {"backgroundColor": yellow}), ["fondo blanco"])

	def test_portapapeles_ignora_la_escritura_propia_aunque_avance_dos(self) -> None:
		from tiresias import clipboard, winapi

		seq = [100]
		with mock.patch.object(winapi.user32, "GetClipboardSequenceNumber", side_effect=lambda: seq[0]), mock.patch.object(winapi, "getClipboardText", return_value="texto"), mock.patch("tiresias.speech.speakMessage") as say:
			clipboard._lastSeq = 100
			clipboard._ignoreSeq.clear()
			clipboard.ignoreNextChange()
			seq[0] = 102  # vaciar y escribir
			clipboard._check()
			say.assert_not_called()
			self.assertFalse(clipboard._ignoreSeq)
			# Un fallo al escribir no deja la marca tapando el siguiente cambio.
			clipboard.ignoreNextChange()
			clipboard.cancelIgnore()
			seq[0] = 103
			old = conf["clipboard"]["announceCopy"]
			conf["clipboard"]["announceCopy"] = True
			try:
				with mock.patch.object(winapi, "getClipboardText", return_value="otro texto"):
					clipboard._check()
			finally:
				conf["clipboard"]["announceCopy"] = old
			say.assert_called()


# ====================================================================== órdenes globales
_MY_MODULES = ("tiresias.global_commands", "tiresias.global_commands_extra")


class GlobalScriptsSmokeTests(unittest.TestCase):
	"""Cada orden global de este área se ejecuta sin errores, sin foco y con un foco simulado."""

	def setUp(self) -> None:
		from tiresias import core, mouse, winapi
		from tiresias.input import core as inputCore

		self._base = copy.deepcopy(conf.base)
		self._triggers = conf.triggersEnabled
		self.fakeGui = mock.MagicMock(name="gui")
		heavy = {name: mock.MagicMock(name=name) for name in ("tiresias.gui", "tiresias.magnifier", "tiresias.vision", "tiresias.ocr", "tiresias.system_tools", "tiresias.audio.sound_split", "tiresias.audio.ducking", "tiresias.braille", "tiresias.synth.ring")}
		heavy["tiresias.gui"] = self.fakeGui
		import tiresias
		import tiresias.audio
		import tiresias.synth

		patches = [mock.patch.dict(sys.modules, heavy)]
		for full, mod in heavy.items():
			parentName, _sep, attr = full.rpartition(".")
			parent = {"tiresias": tiresias, "tiresias.audio": tiresias.audio, "tiresias.synth": tiresias.synth}[parentName]
			patches.append(mock.patch.object(parent, attr, mod, create=True))
		patches += [
			mock.patch.object(mouse, "click"),
			mock.patch.object(mouse, "moveTo"),
			mock.patch.object(mouse, "toggleLock", return_value=True),
			mock.patch.object(mouse, "scroll"),
			mock.patch.object(winapi, "sendInputs"),
			mock.patch.object(winapi, "mouseEvent"),
			mock.patch.object(winapi, "setClipboardText", return_value=True),
			mock.patch.object(winapi, "getClipboardText", return_value="texto del portapapeles"),
			mock.patch.object(core, "restart"),
			mock.patch.object(core, "reloadPlugins"),
			mock.patch.object(core, "applyConfiguration"),
			mock.patch.object(conf, "save"),
			mock.patch.object(conf, "revertToSaved"),
			mock.patch.object(conf, "resetToFactoryDefaults"),
			mock.patch.object(inputCore.manager, "updateChain"),
			mock.patch("tiresias.speech.speak"),
			mock.patch("tiresias.speech.speakMessage"),
			mock.patch("tiresias.speech.speakText"),
			mock.patch("tiresias.speech.speakSpelling"),
			mock.patch("tiresias.speech.cancelSpeech"),
			mock.patch("tiresias.speech.sayall.readText"),
			mock.patch("tiresias.speech.sayall.readObjects"),
			mock.patch("tiresias.audio.tones.playSound"),
			mock.patch("tiresias.audio.tones.beep"),
			mock.patch("tiresias.objects.uia.getObjectFromPoint", return_value=None),
			mock.patch("tiresias.a11y.system.isSecureObject", return_value=False),
			mock.patch("os.startfile", create=True),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)
		# Sin restos de otras pruebas (foco, navegador, revisión).
		api.setFocusObject(None, [])
		api.setNavigatorObject(None)
		api.setForegroundObject(None)
		api.setMouseObject(None)

	def tearDown(self) -> None:
		conf.base = self._base
		conf.triggersEnabled = self._triggers
		api.setFocusObject(None, [])
		api.setForegroundObject(None)
		api.setNavigatorObject(None)

	def _scripts(self):
		from tiresias.global_commands import GlobalCommands, commands

		for name in sorted(dir(GlobalCommands)):
			func = getattr(GlobalCommands, name, None)
			if name.startswith("script_") and getattr(func, "__module__", "") in _MY_MODULES:
				# Órdenes que cierran Tiresias: se prueban aparte.
				if name in ("script_quit",):
					continue
				yield name, getattr(commands, name)

	def _runAll(self) -> list[str]:
		from tiresias.input import core as inputCore

		errors = []
		self.assertGreater(len(list(self._scripts())), 150)
		for count in (0, 1, 2, 3):
			with mock.patch.object(inputCore, "getLastScriptRepeatCount", return_value=count):
				for name, func in self._scripts():
					try:
						func(None)
					except Exception as e:  # noqa: BLE001
						errors.append(f"{name} (x{count + 1}): {type(e).__name__}: {e}")
		return errors

	def test_sin_foco(self) -> None:
		self.assertEqual(self._runAll(), [])

	def test_con_foco_simulado(self) -> None:
		desktop = FakeObj("Escritorio", Role.DESKTOPPANE)
		win = FakeObj("Ventana de prueba", Role.WINDOW, FakeApp(), desktop)
		obj = FakeObj("Campo", Role.EDITABLETEXT, win.appModule, win)
		win.children = [obj]
		win.firstChild = win.simpleFirstChild = obj
		api.setFocusObject(obj, [desktop, win])
		api.setForegroundObject(win)
		self.assertEqual(self._runAll(), [])

	def test_seleccionar_linea_braille_abre_su_dialogo(self) -> None:
		from tiresias.global_commands import GlobalCommands

		func = GlobalCommands.script_activateBrailleDisplayDialog
		self.assertEqual(func.__module__, "tiresias.global_commands")
		self.assertNotIn("script_activateBrailleDisplayDialog", vars(__import__("tiresias.global_commands_extra", fromlist=["ExtraCommands"]).ExtraCommands))


class PolicyTests(unittest.TestCase):
	"""Las teclas respetan la política y el modo seguro igual que el menú."""

	def test_ordenes_bloqueadas_por_la_politica(self) -> None:
		from tiresias.config import policy as policyModule
		from tiresias.global_commands import commands
		from tiresias.input import core as inputCore

		pol = policyModule.Policy({"allowPythonConsole": False, "allowFactoryReset": False, "allowSaveConfiguration": False, "allowOpenDataFolder": False})
		fakeGui = mock.MagicMock()
		import tiresias

		with mock.patch.object(policyModule, "policy", pol), mock.patch.dict(sys.modules, {"tiresias.gui": fakeGui}), mock.patch.object(tiresias, "gui", fakeGui, create=True), mock.patch("tiresias.speech.speakMessage") as say, mock.patch.object(conf, "save") as save, mock.patch.object(conf, "resetToFactoryDefaults") as reset, mock.patch("tiresias.core.applyConfiguration"), mock.patch("os.startfile", create=True) as start:
			commands.script_activatePythonConsole(None)
			fakeGui.showPythonConsole.assert_not_called()
			commands.script_saveConfiguration(None)
			save.assert_not_called()
			with mock.patch.object(inputCore, "getLastScriptRepeatCount", return_value=2):
				commands.script_revertConfiguration(None)
			reset.assert_not_called()
			commands.script_openUserConfigurationDirectory(None)
			fakeGui.runOnGui.assert_not_called()
			start.assert_not_called()
			self.assertTrue(all("administrador" in c.args[0] for c in say.call_args_list))
		with mock.patch.object(policyModule, "policy", policyModule.Policy({})), mock.patch.dict(sys.modules, {"tiresias.gui": fakeGui}), mock.patch.object(tiresias, "gui", fakeGui, create=True):
			commands.script_activatePythonConsole(None)
			fakeGui.showPythonConsole.assert_called_once()

	def test_recargar_sin_complementos_no_los_carga(self) -> None:
		from tiresias import core

		old = core.args
		try:
			core.args = core.parseArgs(["--safe-mode"])
			with mock.patch("tiresias.addons.loadAll") as load, mock.patch("tiresias.plugins.handler.terminate"), mock.patch("tiresias.plugins.handler.initialize"), mock.patch("tiresias.appmodules.handler.reloadAll"), mock.patch("tiresias.input.core.manager.updateChain"):
				core.reloadPlugins()
				load.assert_not_called()
				core.args = core.parseArgs([])
				core.reloadPlugins()
				load.assert_called_once()
		finally:
			core.args = old


if __name__ == "__main__":
	unittest.main()
