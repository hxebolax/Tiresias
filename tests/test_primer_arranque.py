"""Pruebas del arranque: pregunta de importar NVDA y diálogo de bienvenida.

- ``first_run.planSteps``: la máquina de decisiones (primera vez con y sin NVDA,
  arranques siguientes, modo seguro, ``--minimal``).
- ``first_run.StartupSequence`` con diálogos simulados: primero la pregunta y,
  solo cuando ha terminado (importación aplicada y resumen cerrado), la
  bienvenida; con Tiresias en espera todo se aplaza en el mismo orden.
- El paso guardado (``general.firstRunStep``) con la configuración real en una
  carpeta temporal: la pregunta no vuelve a salir, ni aunque se dijera que no.
- ``first_run.start`` de verdad (con ``APPDATA`` apuntando a un NVDA falso) y
  la convivencia (``coexist.runWhenActive``).
- El diálogo de bienvenida: valores iniciales, teclas Tiresias, validación,
  aceleradores sin repetir y fin del primer arranque al aceptar.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import copy
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import first_run as fr, paths, queue_handler  # noqa: E402
from tiresias.config import conf  # noqa: E402

FAKE_NVDA_INI = """schemaVersion = 11
[general]
	showWelcomeDialogAtStartup = False
[keyboard]
	keyboardLayout = laptop
	NVDAModifierKeys = 6
"""


# ====================================================================== decisión
class PlanStepsTests(unittest.TestCase):
	def test_first_run_with_nvda(self) -> None:
		self.assertEqual(fr.planSteps(fr.STEP_NVDA, "C:/nvda", True), [fr.ASK_IMPORT, fr.WELCOME])

	def test_first_run_welcome_even_if_unchecked(self) -> None:
		# La importación pone la casilla de NVDA (desmarcada): la bienvenida sale igual.
		self.assertEqual(fr.planSteps(fr.STEP_NVDA, "C:/nvda", False), [fr.ASK_IMPORT, fr.WELCOME])
		self.assertEqual(fr.planSteps(fr.STEP_WELCOME, None, False), [fr.WELCOME])

	def test_first_run_without_nvda(self) -> None:
		self.assertEqual(fr.planSteps(fr.STEP_NVDA, None, True), [fr.WELCOME])
		self.assertEqual(fr.planSteps(fr.STEP_NVDA, "", False), [fr.WELCOME])

	def test_next_runs_follow_checkbox(self) -> None:
		self.assertEqual(fr.planSteps(fr.STEP_DONE, "C:/nvda", True), [fr.WELCOME])
		self.assertEqual(fr.planSteps(fr.STEP_DONE, "C:/nvda", False), [])

	def test_read_only_never_imports(self) -> None:
		self.assertEqual(fr.planSteps(fr.STEP_NVDA, "C:/nvda", True, readOnly=True), [fr.WELCOME])

	def test_suppressed(self) -> None:
		for step in (fr.STEP_NVDA, fr.STEP_WELCOME, fr.STEP_DONE):
			self.assertEqual(fr.planSteps(step, "C:/nvda", True, suppressed=True), [])


# ====================================================================== secuencia con diálogos simulados
class _Fake:
	"""Diálogos y estado simulados; ``events`` guarda el orden de todo."""

	def __init__(self, step: str = fr.STEP_NVDA, standby: bool = False) -> None:
		self.events: list = []
		self.step = step
		self.standby = standby
		self.deferred: list = []
		self.pendingAsk = None
		self.openDialogs: set[str] = set()

	def ask(self, folder, onAnswer, then) -> None:
		self.assertNoOtherDialog("pregunta")
		self.events.append(("ask", folder))
		self.openDialogs.add("pregunta")
		self.pendingAsk = (onAnswer, then)

	def answer(self, yes: bool) -> None:
		onAnswer, then = self.pendingAsk
		self.pendingAsk = None
		self.openDialogs.discard("pregunta")
		onAnswer(yes)
		self.events.append(("answered", yes))
		if yes:
			# Importación aplicada en el núcleo y resumen (modal) cerrado.
			self.events.append(("imported",))
		then()

	def welcome(self, imported: bool) -> None:
		self.assertNoOtherDialog("bienvenida")
		self.events.append(("welcome", imported))
		self.openDialogs.add("bienvenida")

	def setStep(self, value: str, save: bool) -> None:
		if value == self.step:
			return
		self.step = value
		self.events.append(("step", value, save))

	def isStandby(self) -> bool:
		return self.standby

	def defer(self, func) -> None:
		self.events.append(("deferred",))
		self.deferred.append(func)

	def activate(self) -> None:
		self.standby = False
		pending, self.deferred = self.deferred, []
		for func in pending:
			func()

	def assertNoOtherDialog(self, name: str) -> None:
		if self.openDialogs:
			raise AssertionError(f"{name} con otro diálogo abierto: {self.openDialogs}")

	def sequence(self, steps, folder="C:/nvda", firstRun=True) -> fr.StartupSequence:
		return fr.StartupSequence(
			steps, folder, firstRun=firstRun, ask=self.ask, welcome=self.welcome, setStep=self.setStep, isStandby=self.isStandby, defer=self.defer
		)


class SequenceTests(unittest.TestCase):
	def test_yes_imports_then_welcome(self) -> None:
		f = _Fake()
		seq = f.sequence([fr.ASK_IMPORT, fr.WELCOME])
		seq.start()
		self.assertEqual(f.events, [("ask", "C:/nvda")])
		# Mientras la pregunta está abierta no sale nada más.
		self.assertNotIn("bienvenida", f.openDialogs)
		f.answer(True)
		self.assertEqual(
			f.events,
			[("ask", "C:/nvda"), ("step", fr.STEP_WELCOME, False), ("answered", True), ("imported",), ("welcome", True)],
		)
		self.assertTrue(seq.imported)
		self.assertEqual(seq.done, [fr.ASK_IMPORT, fr.WELCOME])

	def test_no_shows_welcome_and_remembers(self) -> None:
		f = _Fake()
		f.sequence([fr.ASK_IMPORT, fr.WELCOME]).start()
		f.answer(False)
		# Con «No» se guarda enseguida que ya se preguntó.
		self.assertEqual(f.events, [("ask", "C:/nvda"), ("step", fr.STEP_WELCOME, True), ("answered", False), ("welcome", False)])

	def test_without_nvda_only_welcome(self) -> None:
		f = _Fake()
		f.sequence([fr.WELCOME], folder=None).start()
		self.assertEqual(f.events, [("step", fr.STEP_WELCOME, True), ("welcome", False)])

	def test_standby_defers_everything_in_order(self) -> None:
		f = _Fake(standby=True)
		f.sequence([fr.ASK_IMPORT, fr.WELCOME]).start()
		self.assertEqual(f.events, [("deferred",)])
		self.assertFalse(f.openDialogs)
		f.activate()
		self.assertEqual(f.events[-1], ("ask", "C:/nvda"))
		f.answer(False)
		self.assertEqual(f.events[-1], ("welcome", False))

	def test_standby_between_steps(self) -> None:
		f = _Fake()
		f.sequence([fr.ASK_IMPORT, fr.WELCOME]).start()
		f.standby = True  # otro lector se abre mientras se responde
		f.answer(True)
		self.assertEqual(f.events[-1], ("deferred",))
		self.assertNotIn(("welcome", True), f.events)
		f.activate()
		self.assertEqual(f.events[-1], ("welcome", True))

	def test_standby_welcome_only(self) -> None:
		f = _Fake(step=fr.STEP_DONE, standby=True)
		f.sequence([fr.WELCOME], firstRun=False).start()
		self.assertEqual(f.events, [("deferred",)])
		f.activate()
		self.assertEqual(f.events, [("deferred",), ("welcome", False)])

	def test_next_run_does_not_touch_step(self) -> None:
		f = _Fake(step=fr.STEP_DONE)
		f.sequence([fr.WELCOME], firstRun=False).start()
		self.assertEqual(f.events, [("welcome", False)])

	def test_nothing_to_do(self) -> None:
		f = _Fake(step=fr.STEP_DONE)
		f.sequence([], firstRun=False).start()
		self.assertEqual(f.events, [])


# ====================================================================== configuración real
class _ConfBase(unittest.TestCase):
	def setUp(self) -> None:
		self._oldData = paths.DATA_DIR
		self._oldConfig = paths._configDirOverride
		self._saved = (copy.deepcopy(conf.base), dict(conf.profiles), dict(conf.triggers), conf.readOnly, conf.manualProfile)
		self.tmp = tempfile.mkdtemp(prefix="tiresias_primer_")
		self.data = os.path.join(self.tmp, "data")
		paths.setDataDir(self.data)
		paths.setConfigDir(None)
		paths.ensureDataDirs()
		conf.readOnly = False
		conf.manualProfile = None
		conf.load()

	def tearDown(self) -> None:
		base, profiles, triggers, readOnly, manual = self._saved
		conf.base, conf.profiles, conf.triggers, conf.readOnly, conf.manualProfile = base, profiles, triggers, readOnly, manual
		paths.setDataDir(self._oldData)
		paths.setConfigDir(self._oldConfig)
		shutil.rmtree(self.tmp, ignore_errors=True)

	def configJson(self) -> dict:
		import json

		with open(conf.configFile, encoding="utf-8") as f:
			return json.load(f)


class StoredStepTests(_ConfBase):
	def test_prepare_marks_first_run_only_without_config(self) -> None:
		from tiresias import startup

		startup.prepareConfiguration(None)
		self.assertTrue(startup.configWasMissing)
		self.assertEqual(fr.currentStep(), fr.STEP_NVDA)
		# Se guarda (al salir o al responder): el siguiente arranque ya no es el primero,
		# pero el paso pendiente se conserva.
		conf.save()
		startup.prepareConfiguration(None)
		self.assertFalse(startup.configWasMissing)
		self.assertEqual(fr.currentStep(), fr.STEP_NVDA)

	def test_existing_config_is_not_first_run(self) -> None:
		from tiresias import startup

		conf.save()
		startup.prepareConfiguration(None)
		self.assertFalse(startup.configWasMissing)
		self.assertEqual(fr.currentStep(), fr.STEP_DONE)

	def test_steps_saved_and_pruned(self) -> None:
		fr.markFirstRun()
		conf.save()
		self.assertEqual(self.configJson()["general"]["firstRunStep"], "nvda")
		fr.setStep(fr.STEP_WELCOME, save=False)
		conf.save()
		self.assertEqual(self.configJson()["general"]["firstRunStep"], "welcome")
		fr.welcomeAccepted()
		conf.save()
		# Terminado: igual que el valor por defecto, no se escribe.
		self.assertNotIn("firstRunStep", self.configJson().get("general", {}))
		self.assertEqual(fr.currentStep(), fr.STEP_DONE)

	def test_step_goes_to_base_not_profile(self) -> None:
		conf.createProfile("Prueba")
		conf.setManualProfile("Prueba")
		self.addCleanup(conf.setManualProfile, None)
		fr.setStep(fr.STEP_WELCOME, save=False)
		self.assertEqual(conf.base["general"]["firstRunStep"], "welcome")
		self.assertNotIn("general", conf.profiles["Prueba"].data)

	def test_read_only_never_writes(self) -> None:
		conf.readOnly = True
		fr.setStep(fr.STEP_NVDA, save=False)
		self.assertEqual(fr.currentStep(), fr.STEP_DONE)

	def test_invalid_value_means_done(self) -> None:
		conf.base.setdefault("general", {})["firstRunStep"] = "otra cosa"
		self.assertEqual(fr.currentStep(), fr.STEP_DONE)


class StartTests(_ConfBase):
	"""``first_run.start`` real, con NVDA falso en ``APPDATA`` y diálogos simulados."""

	def setUp(self) -> None:
		super().setUp()
		self.appdata = os.path.join(self.tmp, "appdata")
		os.makedirs(os.path.join(self.appdata, "nvda"))
		with open(os.path.join(self.appdata, "nvda", "nvda.ini"), "w", encoding="utf-8") as f:
			f.write(FAKE_NVDA_INI)
		self.events: list = []
		from tiresias import coexist, gui

		self.coexist = coexist
		patches = [
			mock.patch.dict(os.environ, {"APPDATA": self.appdata}),
			mock.patch.object(gui, "runOnGui", lambda func, *a, **k: func(*a, **k)),
			mock.patch.object(fr, "_askImport", self._ask),
			mock.patch.object(fr, "_showWelcome", lambda imported: self.events.append(("welcome", imported))),
			# El guardado se encola en el núcleo: aquí se hace en el acto.
			mock.patch.object(queue_handler, "queueFunction", lambda func, *a: func(*a)),
			mock.patch.object(coexist, "_machine", None),
			mock.patch.object(coexist, "_pendingOnActive", []),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)
		self.answerWith: bool | None = None

	def _ask(self, folder, onAnswer, then) -> None:
		self.events.append(("ask", os.path.normcase(folder)))
		onAnswer(bool(self.answerWith))
		then()

	def args(self, **kw):
		return types.SimpleNamespace(minimal=kw.get("minimal", False), install=kw.get("install", False))

	def test_first_run_with_nvda_no(self) -> None:
		fr.markFirstRun()
		self.answerWith = False
		fr.start(self.args())
		self.assertEqual(self.events, [("ask", os.path.normcase(os.path.join(self.appdata, "nvda"))), ("welcome", False)])
		self.assertEqual(fr.currentStep(), fr.STEP_WELCOME)
		# Se guardó: el siguiente arranque ya no pregunta.
		self.assertEqual(self.configJson()["general"]["firstRunStep"], "welcome")
		self.events.clear()
		fr.start(self.args())
		self.assertEqual(self.events, [("welcome", False)])

	def test_first_run_without_nvda(self) -> None:
		shutil.rmtree(os.path.join(self.appdata, "nvda"))
		fr.markFirstRun()
		fr.start(self.args())
		self.assertEqual(self.events, [("welcome", False)])
		self.assertEqual(fr.currentStep(), fr.STEP_WELCOME)

	def test_next_runs(self) -> None:
		conf["general"]["showWelcomeDialogAtStartup"] = True
		self.assertIsNotNone(fr.start(self.args()))
		self.assertEqual(self.events, [("welcome", False)])
		self.events.clear()
		conf["general"]["showWelcomeDialogAtStartup"] = False
		self.assertIsNone(fr.start(self.args()))
		self.assertEqual(self.events, [])

	def test_minimal_shows_nothing(self) -> None:
		fr.markFirstRun()
		self.assertIsNone(fr.start(self.args(minimal=True)))
		self.assertEqual(self.events, [])
		self.assertEqual(fr.currentStep(), fr.STEP_NVDA)

	def test_standby_waits_for_activation(self) -> None:
		fr.markFirstRun()
		self.answerWith = False
		self.coexist._machine = types.SimpleNamespace(isStandby=True)
		fr.start(self.args())
		self.assertEqual(self.events, [])
		self.assertEqual(len(self.coexist._pendingOnActive), 1)
		self.coexist._machine.isStandby = False
		self.coexist._runPendingOnActive()
		self.assertEqual([e[0] for e in self.events], ["ask", "welcome"])
		self.assertEqual(self.coexist._pendingOnActive, [])


# ====================================================================== diálogo de bienvenida
class WelcomeDialogTests(_ConfBase):
	@classmethod
	def setUpClass(cls) -> None:
		try:
			import wx
		except ImportError:
			raise unittest.SkipTest("Sin wxPython")
		cls.wx = wx
		cls.app = wx.App.Get() or wx.App(False)

	def setUp(self) -> None:
		super().setUp()
		from tiresias.gui import config_dialogs

		self.cd = config_dialogs
		p = mock.patch.object(config_dialogs, "_saveConfig", lambda: None)
		p.start()
		self.addCleanup(p.stop)

	def make(self, imported: bool = False):
		dlg = self.cd.WelcomeDialog(None, imported)
		self.addCleanup(lambda: dlg.Destroy() if self.cd.isAlive(dlg) else None)
		return dlg

	def test_initial_values_from_config(self) -> None:
		# Por ejemplo, lo importado de NVDA: portátil, sin Bloq Mayús, sin bienvenida.
		kb = conf["keyboard"]
		kb["layout"] = "laptop"
		kb["useCapsLockAsModifier"] = False
		kb["useNumpadInsertAsModifier"] = True
		conf["general"]["showWelcomeDialogAtStartup"] = False
		dlg = self.make(imported=True)
		self.assertEqual(dlg.layoutCtrl.GetSelection(), 1)
		self.assertFalse(dlg.modifierCtrls["useCapsLockAsModifier"].GetValue())
		self.assertTrue(dlg.modifierCtrls["useInsertAsModifier"].GetValue())
		self.assertTrue(dlg.modifierCtrls["useNumpadInsertAsModifier"].GetValue())
		self.assertFalse(dlg.showCtrl.GetValue())
		self.assertIn("NVDA", dlg.intro.GetValue())

	def test_defaults_and_text(self) -> None:
		dlg = self.make()
		for ctrl in dlg.modifierCtrls.values():
			self.assertTrue(ctrl.GetValue())
		self.assertTrue(dlg.showCtrl.GetValue())
		text = dlg.intro.GetValue()
		self.assertNotIn("importado", text)
		# «Bloqueo de mayúsculas», como en Opciones y en el manual (revisión de Opciones 1.0.6).
		for part in ("Tiresias+1", "Tiresias+Q", "Bloqueo de mayúsculas", "tutorial", "manual"):
			self.assertIn(part, text)
		# Las teclas reales del menú (de fábrica Tiresias+M y Tiresias+Aplicaciones), solo de teclado.
		self.assertIn("tiresias+m", text.lower())
		self.assertIn("tiresias+aplicaciones", text.lower())
		self.assertNotIn("táctil", text)

	def test_ok_applies_and_finishes_first_run(self) -> None:
		fr.setStep(fr.STEP_WELCOME, save=False)
		dlg = self.make()
		dlg.layoutCtrl.SetSelection(1)
		dlg.modifierCtrls["useCapsLockAsModifier"].SetValue(False)
		dlg.showCtrl.SetValue(False)
		with mock.patch.object(self.cd, "runOnCore") as onCore:
			self.assertTrue(dlg._onOk())
		onCore.assert_called_once()  # updateChain por el cambio de distribución
		kb = conf["keyboard"]
		self.assertEqual(kb["layout"], "laptop")
		self.assertFalse(kb["useCapsLockAsModifier"])
		self.assertTrue(kb["useInsertAsModifier"])
		self.assertFalse(conf["general"]["showWelcomeDialogAtStartup"])
		self.assertEqual(fr.currentStep(), fr.STEP_DONE)

	def test_at_least_one_tiresias_key(self) -> None:
		fr.setStep(fr.STEP_WELCOME, save=False)
		dlg = self.make()
		for ctrl in dlg.modifierCtrls.values():
			ctrl.SetValue(False)
		with mock.patch.object(self.cd, "showError") as err:
			self.assertFalse(dlg._onOk())
		err.assert_called_once()
		self.assertTrue(self.cd.isAlive(dlg))
		self.assertTrue(conf["keyboard"]["useCapsLockAsModifier"])
		self.assertEqual(fr.currentStep(), fr.STEP_WELCOME)

	def test_accelerators_unique(self) -> None:
		dlg = self.make()
		seen: dict[str, str] = {}

		def walk(win) -> None:
			for w in win.GetChildren():
				label = (w.GetLabel() if hasattr(w, "GetLabel") else "").replace("&&", "")
				if "&" in label and not isinstance(w, self.wx.TextCtrl):
					key = label[label.index("&") + 1].lower()
					self.assertNotIn(key, seen, f"{label} y {seen.get(key)}")
					seen[key] = label
				walk(w)

		walk(dlg)
		# Información, Distribución, Insertar, numérico, Bloq Mayús, sesión, Mostrar, Tutorial, manual.
		self.assertEqual(len(seen), 9, seen)


if __name__ == "__main__":
	unittest.main()
