"""Revisión 1.0.11 del núcleo: estabilidad del arranque, el cierre y el vigilante.

- Arranque: cada paso aislado y vigilado; los ganchos se instalan aunque falle
  algo; aviso de lo que falló; arranque sin complementos tras arranques
  fallidos; registro en otra carpeta si ``data`` no admite escritura.
- Vigilante: mide cada tarea (no el lote), vigila el arranque y el cierre,
  fuerza la salida si el cierre se bloquea y limita los reinicios de emergencia.
- Fin de sesión de Windows: no se veta y se guarda la configuración.
- Instancia única sin carrera, «Reiniciar como administrador» sin bloquear el
  núcleo, puntos de extensión con referencias débiles y baja al recargar,
  lectura de config.json bloqueada, registro (unraisablehook, comtypes,
  fallos.log acotado) y archivos de datos con raíz no válida.

No se arranca Tiresias, no se instalan ganchos y no suena nada (todo simulado).
Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev1011_nucleo -v``
"""

from __future__ import annotations

import gc
import json
import logging
import os
import shutil
import struct
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
	_TMP = tempfile.mkdtemp(prefix="tiresias_rev1011_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]

from tiresias import core, crash_log, extension_points, i18n, queue_handler, watchdog  # noqa: E402
from tiresias import log as logModule  # noqa: E402
from tiresias.config import ConfigManager  # noqa: E402


class _Stop(Exception):
	"""Sustituye a os._exit en las pruebas."""


def _drainQueue() -> None:
	while True:
		try:
			queue_handler._queue.get_nowait()
		except Exception:
			return


# ====================================================================== cola y vigilante
class TestColaVigilada(unittest.TestCase):
	def tearDown(self) -> None:
		_drainQueue()
		queue_handler.busy = False
		queue_handler.currentTask = None

	def test_cada_tarea_renueva_la_marca(self) -> None:
		vistos = []

		def tarea() -> None:
			vistos.append(queue_handler.lastPumpTime)
			time.sleep(0.05)

		for _i in range(3):
			queue_handler._queue.put((tarea, (), {}))
		queue_handler.pump()
		self.assertEqual(len(vistos), 3)
		# La tercera tarea no mide desde el principio del lote.
		self.assertGreaterEqual(vistos[2] - vistos[0], 0.09)
		self.assertFalse(queue_handler.busy)
		self.assertIsNone(queue_handler.currentTask)

	def test_lote_limitado_por_tiempo(self) -> None:
		hechas = []
		with mock.patch.object(queue_handler, "MAX_BATCH_SECONDS", 0.05):
			for i in range(10):
				queue_handler._queue.put((lambda i=i: (hechas.append(i), time.sleep(0.02)), (), {}))
			queue_handler.pump()
		self.assertLess(len(hechas), 10)
		self.assertGreater(queue_handler.pendingCount(), 0)

	def test_fase_vigilada(self) -> None:
		with queue_handler.watchedPhase("arranque: prueba"):
			self.assertTrue(queue_handler.busy)
			self.assertEqual(queue_handler.currentTask, "arranque: prueba")
			time.sleep(0.02)
			self.assertGreater(queue_handler.frozenFor(), 0.0)
		self.assertFalse(queue_handler.busy)
		self.assertEqual(queue_handler.frozenFor(), 0.0)

	def test_fase_vigilada_con_excepcion(self) -> None:
		with self.assertRaises(RuntimeError):
			with queue_handler.watchedPhase("cierre: x"):
				raise RuntimeError("fallo")
		self.assertFalse(queue_handler.busy)


class TestLimiteDeReinicios(unittest.TestCase):
	def setUp(self) -> None:
		self.tmp = tempfile.mkdtemp(prefix="tiresias_reinicios_")
		self.path = os.path.join(self.tmp, "reinicios.json")
		self.p = mock.patch.object(watchdog, "restartHistoryPath", return_value=self.path)
		self.p.start()
		watchdog._restartSuppressed = False
		watchdog._restarting = False
		watchdog._lastCancel = 0.0

	def tearDown(self) -> None:
		self.p.stop()
		watchdog._restartSuppressed = False
		watchdog._restarting = False
		shutil.rmtree(self.tmp, ignore_errors=True)

	def test_historial_y_ventana(self) -> None:
		ahora = 1_000_000.0
		self.assertTrue(watchdog.restartAllowed(ahora))
		watchdog._recordRestart(ahora - watchdog.RESTART_WINDOW - 5)  # antiguo: no cuenta
		watchdog._recordRestart(ahora - 30)
		self.assertTrue(watchdog.restartAllowed(ahora))
		watchdog._recordRestart(ahora - 10)
		self.assertEqual(len(watchdog.loadRestartHistory(ahora)), 2)
		self.assertFalse(watchdog.restartAllowed(ahora))

	def test_historial_danado(self) -> None:
		with open(self.path, "w", encoding="utf-8") as f:
			f.write("{no es json")
		self.assertEqual(watchdog.loadRestartHistory(), [])
		with open(self.path, "w", encoding="utf-8") as f:
			json.dump({"a": 1}, f)
		self.assertEqual(watchdog.loadRestartHistory(), [])

	def test_recover_reinicia_si_se_permite(self) -> None:
		with mock.patch.object(watchdog, "emergencyRestart") as er, mock.patch.object(watchdog, "_suppressRestarts") as sup, mock.patch.object(watchdog, "cancelPendingCall"):
			watchdog.recover(40)
			er.assert_called_once()
			sup.assert_not_called()

	def test_recover_no_reinicia_tras_el_limite(self) -> None:
		watchdog._recordRestart()
		watchdog._recordRestart()
		with mock.patch.object(watchdog, "emergencyRestart") as er, mock.patch.object(watchdog, "_suppressRestarts") as sup, mock.patch.object(watchdog, "cancelPendingCall"):
			watchdog.recover(40)
			er.assert_not_called()
			sup.assert_called_once()

	def test_recover_durante_el_cierre_no_reinicia(self) -> None:
		with mock.patch.object(watchdog, "emergencyRestart") as er, mock.patch.object(watchdog, "_suppressRestarts") as sup, mock.patch.object(watchdog, "cancelPendingCall") as cc:
			watchdog.recover(400, allowRestart=False)
			er.assert_not_called()
			sup.assert_not_called()
			cc.assert_called_once()

	def test_aviso_del_limite(self) -> None:
		voz = mock.Mock()
		from tiresias import gui, synth

		with mock.patch.object(watchdog.ctypes.windll.kernel32, "Beep") as beep, mock.patch.object(synth, "getSynth", return_value=voz), mock.patch.object(gui, "showTrayNotification") as tray:
			watchdog._suppressRestarts(45)
		self.assertTrue(watchdog._restartSuppressed)
		self.assertTrue(beep.called)
		voz.speak.assert_called_once()
		self.assertIn("no se reiniciará más", voz.speak.call_args[0][0][0])
		tray.assert_called_once()
		# Suprimido: aunque se permita por historial, no se reinicia hasta recuperarse.
		with mock.patch.object(watchdog, "emergencyRestart") as er, mock.patch.object(watchdog, "cancelPendingCall"):
			watchdog.recover(60)
			er.assert_not_called()
		watchdog.onRecovered()
		self.assertFalse(watchdog._restartSuppressed)

	def test_reinicio_de_emergencia_anota_y_termina_sin_logging_shutdown(self) -> None:
		from tiresias.coexist import guardian
		from tiresias.config import conf

		with mock.patch.object(watchdog.ctypes.windll.kernel32, "Beep"), mock.patch.object(conf, "save"), mock.patch.object(watchdog.subprocess, "Popen") as popen, mock.patch.object(guardian, "writeMarkerNow") as marker, mock.patch.object(logModule, "shutdown") as shut, mock.patch.object(logModule, "flush") as flush, mock.patch.object(crash_log, "uninstall"), mock.patch.object(watchdog.os, "_exit", side_effect=_Stop):
			with self.assertRaises(_Stop):
				watchdog.emergencyRestart(35)
		popen.assert_called_once()
		marker.assert_called_once_with("restart")
		shut.assert_not_called()
		flush.assert_called_once()
		self.assertEqual(len(watchdog.loadRestartHistory()), 1)


# ====================================================================== bucle del vigilante del núcleo
class TestVigilanteDelNucleo(unittest.TestCase):
	def setUp(self) -> None:
		self.oldThread = core._coreThread
		self.oldQuit = core._quitRequested

	def tearDown(self) -> None:
		core._coreThread = self.oldThread
		core._quitRequested = self.oldQuit
		queue_handler.busy = False
		queue_handler.currentTask = None

	def _fakeThread(self, aliveTimes: int):
		t = mock.Mock()
		t.is_alive.side_effect = [True] * aliveTimes + [False] * 5
		return t

	def test_cierre_bloqueado_fuerza_la_salida(self) -> None:
		core._coreThread = self._fakeThread(3)
		core._quitRequested = True
		queue_handler.busy = True
		queue_handler.currentTask = "cierre: braille"
		queue_handler.lastPumpTime = time.monotonic() - core.SHUTDOWN_STEP_TIMEOUT - 5
		with mock.patch.object(core.time, "sleep"), mock.patch.object(core, "_forceExit") as fe, mock.patch.object(watchdog, "recover") as rec:
			core._watchdog()
		fe.assert_called_once()
		self.assertIn("cierre: braille", fe.call_args[0][0])
		rec.assert_not_called()

	def test_bloqueo_normal_recupera_con_reinicio_permitido(self) -> None:
		from tiresias import synth

		core._coreThread = self._fakeThread(1)
		core._quitRequested = False
		queue_handler.busy = True
		queue_handler.currentTask = "tarea"
		queue_handler.lastPumpTime = time.monotonic() - 9
		with mock.patch.object(core.time, "sleep"), mock.patch.object(watchdog, "recover") as rec, mock.patch.object(crash_log, "dumpThreads") as dump, mock.patch.object(synth, "getSynth", return_value=None):
			core._watchdog()
		rec.assert_called_once()
		self.assertTrue(rec.call_args.kwargs["allowRestart"])
		dump.assert_called_once()


# ====================================================================== arranque
class TestPasosDelArranque(unittest.TestCase):
	def setUp(self) -> None:
		self.old = list(core._initFailures)
		core._initFailures.clear()

	def tearDown(self) -> None:
		core._initFailures[:] = self.old

	def test_paso_que_falla_no_lanza(self) -> None:
		def falla() -> None:
			raise OSError("Clase no registrada")

		self.assertIsNone(core._initStep("UI Automation", falla, critical=True))
		self.assertEqual(core._initFailures, ["UI Automation"])
		self.assertFalse(queue_handler.busy)
		self.assertIsNone(core._initStep("opcional", falla))
		self.assertEqual(core._initFailures, ["UI Automation"])
		self.assertEqual(core._initStep("bien", lambda x, y=0: x + y, 2, y=3), 5)

	def test_nucleo_instala_los_ganchos_aunque_falle_el_arranque(self) -> None:
		from tiresias import coexist, gui

		oldId = queue_handler._coreThreadId
		hechos = {}

		def run() -> None:
			try:
				core._coreMain()
			except Exception as e:  # pragma: no cover
				hechos["error"] = e

		with mock.patch.object(core, "_initializeCore", side_effect=RuntimeError("UIA")), mock.patch.object(core, "startInput") as si, mock.patch.object(core, "_reportStartupProblems") as rep, mock.patch.object(core, "_loop"), mock.patch.object(core, "_terminateCore"), mock.patch.object(gui, "exitMainLoop") as ex, mock.patch.object(core, "_startGuiExitTimer") as timer, mock.patch.object(coexist, "isStandby", return_value=False), mock.patch.object(watchdog, "registerCoreThread"), mock.patch("comtypes.CoInitializeEx"):
			t = threading.Thread(target=run)
			t.start()
			t.join(10)
		queue_handler._coreThreadId = oldId
		self.assertNotIn("error", hechos)
		si.assert_called_once()
		rep.assert_called_once()
		ex.assert_called_once()
		timer.assert_called_once()
		self.assertEqual(len(core._initFailures), 1)

	def test_cierre_que_falla_sigue_terminando_la_interfaz(self) -> None:
		from tiresias import coexist, gui

		oldId = queue_handler._coreThreadId

		def run() -> None:
			try:
				core._coreMain()
			except BaseException:
				pass

		with mock.patch.object(core, "_initializeCore"), mock.patch.object(core, "startInput"), mock.patch.object(core, "_reportStartupProblems"), mock.patch.object(core, "_loop"), mock.patch.object(core, "_terminateCore", side_effect=SystemExit), mock.patch.object(gui, "exitMainLoop") as ex, mock.patch.object(core, "_startGuiExitTimer"), mock.patch.object(coexist, "isStandby", return_value=False), mock.patch.object(watchdog, "registerCoreThread"), mock.patch("comtypes.CoInitializeEx"):
			t = threading.Thread(target=run)
			t.start()
			t.join(10)
		queue_handler._coreThreadId = oldId
		ex.assert_called_once()

	def test_aviso_de_problemas(self) -> None:
		from tiresias import speech
		from tiresias.audio import tones

		core._initFailures.append("UI Automation")
		with mock.patch.object(speech, "speakMessage") as sm, mock.patch.object(tones, "playSound") as ps, mock.patch.object(logModule, "fallbackLogsDir", "C:\\Temp\\Tiresias\\logs"), mock.patch.object(core, "_autoSafeMode", True):
			core._reportStartupProblems()
		textos = " ".join(c[0][0] for c in sm.call_args_list)
		self.assertIn("UI Automation", textos)
		self.assertIn("No se puede escribir", textos)
		self.assertIn("sin complementos", textos)
		ps.assert_called_once_with("error")

	def test_terminar_paso_aislado(self) -> None:
		core._terminateStep("x", mock.Mock(side_effect=SystemExit))
		self.assertFalse(queue_handler.busy)


class TestArranquesFallidos(unittest.TestCase):
	def setUp(self) -> None:
		self.tmp = tempfile.mkdtemp(prefix="tiresias_arranques_")
		self.p = mock.patch.object(core, "_startupPendingPath", return_value=os.path.join(self.tmp, "a.json"))
		self.p.start()
		self.oldAuto = core._autoSafeMode

	def tearDown(self) -> None:
		self.p.stop()
		core._autoSafeMode = self.oldAuto
		shutil.rmtree(self.tmp, ignore_errors=True)

	def test_dos_arranques_sin_terminar_activan_el_modo_sin_complementos(self) -> None:
		for _i in range(core.STARTUP_FAILURES_FOR_SAFE_MODE):
			ns = types.SimpleNamespace(safe_mode=False)
			self.assertFalse(core._beginStartupAttempt(ns))
			self.assertFalse(ns.safe_mode)
		ns = types.SimpleNamespace(safe_mode=False)
		self.assertTrue(core._beginStartupAttempt(ns))
		self.assertTrue(ns.safe_mode)
		self.assertTrue(core._autoSafeMode)
		# Termina bien: el siguiente arranque vuelve a cargar los complementos.
		core._startupCompleted()
		ns = types.SimpleNamespace(safe_mode=False)
		self.assertFalse(core._beginStartupAttempt(ns))
		self.assertFalse(ns.safe_mode)

	def test_modo_sin_complementos_pedido_no_cuenta_como_automatico(self) -> None:
		for _i in range(3):
			core._beginStartupAttempt(types.SimpleNamespace(safe_mode=False))
		ns = types.SimpleNamespace(safe_mode=True)
		self.assertFalse(core._beginStartupAttempt(ns))
		self.assertFalse(core._autoSafeMode)

	def test_cuenta_danada(self) -> None:
		with open(core._startupPendingPath(), "w", encoding="utf-8") as f:
			f.write("[1, 2")
		self.assertEqual(core._readStartupFailures(), 0)
		with open(core._startupPendingPath(), "w", encoding="utf-8") as f:
			json.dump({"pendientes": "muchos"}, f)
		self.assertEqual(core._readStartupFailures(), 0)


# ====================================================================== salida
class TestSalida(unittest.TestCase):
	def setUp(self) -> None:
		self.saved = (core._exitClaimed, core._quitRequested, core._restartRequested)
		core._exitClaimed = False
		core._exitDone.clear()

	def tearDown(self) -> None:
		core._exitClaimed, core._quitRequested, core._restartRequested = self.saved
		core._exitDone.clear()

	def test_salida_forzada(self) -> None:
		with mock.patch.object(core, "_saveConfigurationWithTimeout") as save, mock.patch.object(core, "_processExitSteps") as steps, mock.patch.object(crash_log, "dumpThreads"), mock.patch.object(watchdog, "flushAndExit", side_effect=_Stop) as fe:
			with self.assertRaises(_Stop):
				core._forceExit("prueba")
		save.assert_called_once()
		steps.assert_called_once()
		fe.assert_called_once_with(0)

	def test_salida_forzada_con_el_camino_normal_en_marcha(self) -> None:
		self.assertTrue(core._claimExit())
		core._exitDone.set()
		with mock.patch.object(core, "_saveConfigurationWithTimeout") as save, mock.patch.object(core, "_processExitSteps") as steps, mock.patch.object(crash_log, "dumpThreads"), mock.patch.object(watchdog, "flushAndExit", side_effect=_Stop):
			with self.assertRaises(_Stop):
				core._forceExit("prueba")
		save.assert_not_called()
		steps.assert_not_called()

	def test_pasos_finales_una_sola_vez(self) -> None:
		self.assertTrue(core._claimExit())
		self.assertFalse(core._claimExit())

	def test_pasos_finales_marcan_el_final(self) -> None:
		from tiresias.coexist import guardian

		core._restartRequested = False
		with mock.patch.object(guardian, "onProcessExit") as ope, mock.patch.object(core, "_mutex", None):
			core._processExitSteps()
		ope.assert_called_once()
		self.assertTrue(core._exitDone.is_set())

	def test_fin_de_sesion(self) -> None:
		from tiresias import synth
		from tiresias.coexist import guardian, relaunch

		evt = mock.Mock()
		core._onQueryEndSession(evt)
		evt.Veto.assert_not_called()
		evt.Skip.assert_not_called()
		voz = mock.Mock()
		with mock.patch.object(core, "_saveConfigurationWithTimeout") as save, mock.patch.object(guardian, "writeMarkerNow") as marker, mock.patch.object(queue_handler, "requestQuit") as rq, mock.patch.object(synth, "getSynth", return_value=voz), mock.patch.object(logModule, "flush"):
			core._onEndSession(evt)
		save.assert_called_once()
		marker.assert_called_once_with(relaunch.EXIT_USER)
		rq.assert_called_once()
		voz.cancel.assert_called_once()
		self.assertTrue(core._quitRequested)
		evt.Skip.assert_not_called()

	def test_guardar_con_plazo_no_espera_para_siempre(self) -> None:
		from tiresias.config import conf

		hecho = threading.Event()
		listo = threading.Event()

		def ocupa() -> None:
			with conf._lock:
				listo.set()
				hecho.wait(5)

		t = threading.Thread(target=ocupa)
		t.start()
		listo.wait(2)
		try:
			with mock.patch.object(conf, "save") as save:
				inicio = time.monotonic()
				core._saveConfigurationWithTimeout(0.2)
				self.assertLess(time.monotonic() - inicio, 2)
				save.assert_not_called()
		finally:
			hecho.set()
			t.join(5)


class TestInstanciaUnica(unittest.TestCase):
	def _run(self, creates, exists=True, window=0, replace=True, closeOk=True):
		with mock.patch.object(core, "_createInstanceMutex", side_effect=creates) as cm, mock.patch.object(core, "_instanceMutexExists", return_value=exists), mock.patch.object(core, "_waitForInstanceWindow", return_value=window), mock.patch.object(core, "_closeRunningInstance", return_value=closeOk) as close, mock.patch.object(core.time, "sleep"), mock.patch.object(core.winapi.kernel32, "CloseHandle"):
			result = core._acquireInstanceMutex(replace)
		return result, cm, close

	def test_sin_otra_copia(self) -> None:
		(h, code), _cm, close = self._run([(11, False)])
		self.assertEqual((h, code), (11, None))
		close.assert_not_called()

	def test_consulta_momentanea_del_guardian(self) -> None:
		(h, code), cm, _close = self._run([(11, True), (12, False)], exists=False)
		self.assertEqual((h, code), (12, None))
		self.assertEqual(cm.call_count, 2)

	def test_otra_copia_con_no_replace(self) -> None:
		(h, code), _cm, close = self._run([(11, True)], window=99, replace=False)
		self.assertEqual(code, 0)
		close.assert_not_called()

	def test_otra_copia_se_sustituye(self) -> None:
		(h, code), _cm, close = self._run([(11, True), (13, False)], window=99, replace=True)
		self.assertEqual((h, code), (13, None))
		close.assert_called_once_with(replacing=True)

	def test_otra_copia_que_no_se_cierra(self) -> None:
		(h, code), _cm, _close = self._run([(11, True)], window=99, replace=True, closeOk=False)
		self.assertEqual(code, 1)

	def test_otra_copia_sin_ventana_se_sigue(self) -> None:
		(h, code), _cm, close = self._run([(11, True), (14, True)], window=0)
		self.assertEqual((h, code), (14, None))
		close.assert_not_called()


class TestReiniciarComoAdministrador(unittest.TestCase):
	def test_no_bloquea_el_nucleo(self) -> None:
		from tiresias import speech

		suelta = threading.Event()
		llamado = threading.Event()
		visto = {}

		def runas(exe: str, params: str) -> int:
			visto["params"] = params
			visto["hilo"] = threading.current_thread().name
			llamado.set()
			suelta.wait(5)
			return 5  # ERROR_ACCESS_DENIED: el usuario dijo que no

		with mock.patch.object(core, "isElevated", return_value=False), mock.patch.object(core, "_shellExecuteRunas", side_effect=runas), mock.patch.object(queue_handler, "queueFunction") as qf, mock.patch.object(speech, "speakMessage"):
			inicio = time.monotonic()
			core.restartAsAdmin()
			self.assertLess(time.monotonic() - inicio, 1.0)
			self.assertTrue(llamado.wait(5))
			suelta.set()
			for _i in range(100):
				if qf.called:
					break
				time.sleep(0.02)
		self.assertIn("--data", visto["params"])
		self.assertNotEqual(visto["hilo"], threading.current_thread().name)
		qf.assert_called_once()


# ====================================================================== puntos de extensión
class _Dueno:
	def __init__(self) -> None:
		self.n = 0

	def manejador(self, valor=None) -> None:
		self.n += 1


class TestPuntosDeExtension(unittest.TestCase):
	def test_metodo_ligado_con_referencia_debil(self) -> None:
		a = extension_points.Action()
		d = _Dueno()
		a.register(d.manejador)
		a.notify(valor=1)
		self.assertEqual(d.n, 1)
		self.assertIn(d.manejador, a.handlers())
		del d
		gc.collect()
		self.assertEqual(a.handlers(), [])

	def test_funcion_y_lambda_con_referencia_normal(self) -> None:
		a = extension_points.Action()
		visto = []
		a.register(lambda valor=None: visto.append(valor))
		gc.collect()
		a.notify(valor=3, otro=4)
		self.assertEqual(visto, [3])

	def test_firma_calculada_una_vez(self) -> None:
		a = extension_points.Action()
		visto = []

		def h(x):
			visto.append(x)

		with mock.patch.object(extension_points.inspect, "signature", wraps=extension_points.inspect.signature) as sig:
			a.register(h)
			for i in range(5):
				a.notify(x=i, y=0)
		self.assertEqual(sig.call_count, 1)
		self.assertEqual(visto, [0, 1, 2, 3, 4])

	def test_filtro_y_decisor(self) -> None:
		f = extension_points.Filter()
		f.register(lambda value: value + 1)
		f.register(lambda value, extra=0: value * extra)
		self.assertEqual(f.apply(1, extra=3), 6)
		dec = extension_points.Decider()
		dec.register(lambda **kw: kw.get("ok", True))
		self.assertTrue(dec.decide(ok=True))
		self.assertFalse(dec.decide(ok=False))

	def test_registro_duplicado_y_baja(self) -> None:
		a = extension_points.Action()
		d = _Dueno()
		a.register(d.manejador)
		a.register(d.manejador)
		self.assertEqual(len(a.handlers()), 1)
		self.assertTrue(a.unregister(d.manejador))
		self.assertFalse(a.unregister(d.manejador))

	def test_baja_por_dueno_en_todos_los_puntos(self) -> None:
		a1, a2 = extension_points.Action(), extension_points.Filter()
		viejo, otro = _Dueno(), _Dueno()
		a1.register(viejo.manejador)
		a2.register(viejo.manejador)
		a1.register(otro.manejador)
		self.assertGreaterEqual(extension_points.unregisterOwnedBy([viejo]), 2)
		self.assertEqual(a1.handlers(), [otro.manejador])
		self.assertEqual(a2.handlers(), [])

	def test_recargar_complementos_da_de_baja_al_viejo(self) -> None:
		from tiresias import addons, api, events  # noqa: F401
		from tiresias.appmodules import handler as appHandler
		from tiresias.input import core as inputCore
		from tiresias.plugins import handler as pluginHandler

		a = extension_points.Action()
		viejo = _Dueno()
		a.register(viejo.manejador)
		with mock.patch.object(pluginHandler, "runningPlugins", [viejo]), mock.patch.object(pluginHandler, "terminate"), mock.patch.object(pluginHandler, "initialize"), mock.patch.object(appHandler, "reloadAll"), mock.patch.object(addons, "loadAll"), mock.patch.object(api, "getFocusObject", return_value=None), mock.patch.object(inputCore.manager, "updateChain"), mock.patch.object(core, "args", types.SimpleNamespace(safe_mode=True)):
			core.reloadPlugins()
		self.assertEqual(a.handlers(), [])


# ====================================================================== configuración
class TestConfigBloqueada(unittest.TestCase):
	def setUp(self) -> None:
		self.tmp = tempfile.mkdtemp(prefix="tiresias_conf_")
		self.path = os.path.join(self.tmp, "config.json")
		with open(self.path, "w", encoding="utf-8") as f:
			json.dump({"general": {"askToExit": False}}, f)
		self.cm = ConfigManager()

	def tearDown(self) -> None:
		shutil.rmtree(self.tmp, ignore_errors=True)

	def _parser(self, fallosRuta: int, bak: dict | None):
		cuenta = {"n": 0}
		real = ConfigManager._parseJson

		def parse(path: str) -> dict:
			if path.endswith(".bak"):
				if bak is None:
					raise FileNotFoundError(path)
				return bak
			cuenta["n"] += 1
			if cuenta["n"] <= fallosRuta:
				raise PermissionError(32, "El proceso no tiene acceso al archivo")
			return real(path)

		return parse

	def test_bloqueo_momentaneo_se_reintenta(self) -> None:
		with mock.patch.object(self.cm, "_parseJson", side_effect=self._parser(1, None)), mock.patch("tiresias.config.time.sleep"), mock.patch("tiresias.config.shutil.copy2") as copy2:
			data = self.cm._readJson(self.path)
		self.assertEqual(data, {"general": {"askToExit": False}})
		self.assertEqual(self.cm.unreadableFiles, [])
		self.assertEqual(self.cm.recoveredFiles, [])
		copy2.assert_not_called()

	def test_bloqueo_persistente_no_pisa_el_archivo(self) -> None:
		bak = {"general": {"askToExit": True}}
		with mock.patch.object(self.cm, "_parseJson", side_effect=self._parser(99, bak)), mock.patch("tiresias.config.time.sleep"), mock.patch("tiresias.config.shutil.copy2") as copy2:
			data = self.cm._readJson(self.path)
		self.assertEqual(data, bak)
		self.assertEqual(self.cm.unreadableFiles, ["config.json"])
		self.assertEqual(self.cm.recoveredFiles, [])
		copy2.assert_not_called()  # ni .corrupto ni .bak encima
		self.assertFalse(self.cm._mayWrite(self.path))
		self.assertTrue(self.cm._mayWrite(self.path + ".otro"))

	def test_json_danado_sigue_recuperandose(self) -> None:
		with open(self.path, "w", encoding="utf-8") as f:
			f.write("")
		with open(self.path + ".bak", "w", encoding="utf-8") as f:
			json.dump({"general": {}}, f)
		data = self.cm._readJson(self.path)
		self.assertEqual(data, {"general": {}})
		self.assertEqual(self.cm.recoveredFiles, ["config.json"])
		self.assertTrue(os.path.isfile(self.path + ".corrupto"))

	def test_guardar_no_sobrescribe_el_ilegible(self) -> None:
		self.cm._protectedPaths.add(os.path.normcase(os.path.abspath(self.cm.configFile)))
		escritos = []
		with mock.patch.object(self.cm, "_writeJson", side_effect=lambda p, d: escritos.append(p)):
			self.cm.save()
		self.assertNotIn(self.cm.configFile, escritos)
		self.assertIn(self.cm.triggersFile, escritos)

	def test_claves_con_cambios_concurrentes(self) -> None:
		self.cm.base = {"general": {f"k{i}": i for i in range(50)}}
		parar = threading.Event()

		def cambia() -> None:
			i = 0
			while not parar.is_set():
				self.cm.base["general"][f"n{i % 500}"] = i
				self.cm.base["general"].pop(f"n{(i + 250) % 500}", None)
				i += 1

		t = threading.Thread(target=cambia)
		t.start()
		try:
			for _i in range(300):
				self.cm._keys(("general",))
		finally:
			parar.set()
			t.join(5)


# ====================================================================== registro
class TestRegistro(unittest.TestCase):
	def tearDown(self) -> None:
		# Se deja el registro como lo usan las demás pruebas.
		logModule.initialize("INFO")

	def test_carpeta_de_datos_sin_escritura(self) -> None:
		tmp = tempfile.mkdtemp(prefix="tiresias_logs_")
		real = logModule._openLogFile

		def abre(folder, fmt):
			if folder == paths.logsDir():
				raise PermissionError(5, "Acceso denegado")
			return real(folder, fmt)

		try:
			with mock.patch.object(logModule, "_openLogFile", side_effect=abre), mock.patch.object(logModule, "fallbackLogsDirCandidate", return_value=tmp):
				logModule.initialize("INFO")
				self.assertEqual(logModule.fallbackLogsDir, tmp)
				self.assertEqual(logModule.logsDir(), tmp)
				logModule.log.info("hola")
				logModule.flush(2)
			logModule._stopListener()
			self.assertTrue(os.path.isfile(os.path.join(tmp, "tiresias.log")))
		finally:
			shutil.rmtree(tmp, ignore_errors=True)

	def test_sin_ninguna_carpeta_tampoco_falla(self) -> None:
		with mock.patch.object(logModule, "_openLogFile", side_effect=PermissionError(5, "x")):
			logModule.initialize("INFO")
		logModule.log.info("solo en memoria")
		self.assertIn("solo en memoria", logModule.getLogText())

	def test_excepciones_ignoradas_y_comtypes_al_registro(self) -> None:
		logModule.initialize("INFO")
		self.assertIs(sys.unraisablehook, logModule._unraisableHook)
		try:
			raise ValueError("fallo en retrollamada")
		except ValueError as e:
			u = types.SimpleNamespace(exc_type=ValueError, exc_value=e, exc_traceback=e.__traceback__, err_msg="Exception ignored on calling ctypes callback function", object="gancho")
		logModule._unraisableHook(u)
		logging.getLogger("comtypes._comobject").warning("Exception in IUIAutomationEventHandler implementation")
		texto = logModule.getLogText()
		self.assertIn("fallo en retrollamada", texto)
		self.assertIn("IUIAutomationEventHandler", texto)

	def test_categorias_de_depuracion_no_validas(self) -> None:
		logModule.applyDebugCategories([1, None, "voz"])
		self.assertEqual(logModule.log.getChild("speech").level, logging.DEBUG)
		logModule.applyDebugCategories("eventos")
		self.assertEqual(logModule.log.getChild("events").level, logging.DEBUG)
		logModule.applyDebugCategories(5)
		logModule.applyDebugCategories([])
		self.assertEqual(logModule.log.getChild("speech").level, logging.NOTSET)


class TestRegistroDeFallos(unittest.TestCase):
	def test_fallos_log_acotado(self) -> None:
		tmp = tempfile.mkdtemp(prefix="tiresias_fallos_")
		path = os.path.join(tmp, "fallos.log")
		try:
			with open(path, "w", encoding="utf-8") as f:
				f.write("x" * 2000)
			with mock.patch.object(crash_log, "MAX_SIZE", 1000):
				crash_log._rotate(path)
			self.assertFalse(os.path.isfile(path))
			self.assertTrue(os.path.isfile(path + ".1"))
			with open(path, "w", encoding="utf-8") as f:
				f.write("y" * 10)
			with mock.patch.object(crash_log, "MAX_SIZE", 1000):
				crash_log._rotate(path)
			self.assertTrue(os.path.isfile(path))
		finally:
			shutil.rmtree(tmp, ignore_errors=True)

	def test_instalar_y_restaurar(self) -> None:
		tmp = tempfile.mkdtemp(prefix="tiresias_fallos_")
		k32 = mock.Mock()
		k32.SetUnhandledExceptionFilter.return_value = 0x1234
		crt = mock.Mock()
		crt.signal.return_value = None
		saved = (crash_log._file, crash_log.installed, crash_log._kernel32)
		try:
			with mock.patch.object(crash_log, "_kernel32", k32), mock.patch.object(crash_log.ctypes, "CDLL", return_value=crt), mock.patch.object(crash_log.atexit, "register"), mock.patch.dict(os.environ, {"TIRESIAS_FAULTHANDLER": ""}):
				crash_log.installed = False
				crash_log.install(os.path.join(tmp, "fallos.log"))
				self.assertTrue(crash_log.installed)
				crash_log.uninstall()
				self.assertFalse(crash_log.installed)
				self.assertEqual(k32.SetUnhandledExceptionFilter.call_args_list[-1][0][0], 0x1234)
				self.assertEqual(crt.signal.call_args_list[-1][0], (crash_log.SIGABRT, None))
				crash_log.uninstall()  # idempotente
		finally:
			if crash_log._file is not None and crash_log._file is not saved[0]:
				crash_log._file.close()
			crash_log._file, crash_log.installed, crash_log._kernel32 = saved
			shutil.rmtree(tmp, ignore_errors=True)


# ====================================================================== archivos de datos
class TestArchivosDeDatos(unittest.TestCase):
	def test_catalogo_de_idioma_danado(self) -> None:
		oldT, oldL = i18n._translation, i18n.LANGUAGE
		try:
			with mock.patch.object(i18n, "resolveLanguage", return_value="en"), mock.patch.object(i18n.gettext, "translation", side_effect=struct.error("unpack requires a buffer")):
				i18n.initialize("en")
			self.assertEqual(i18n.LANGUAGE, "es")
		finally:
			i18n._translation, i18n.LANGUAGE = oldT, oldL

	def test_gestos_con_raiz_no_valida(self) -> None:
		from tiresias.input.gestures import UserGestureMap

		tmp = tempfile.mkdtemp(prefix="tiresias_gestos_")
		path = os.path.join(tmp, "gestures.json")
		try:
			for contenido in ("[1, 2]", '{"a": {"5": "x"}}', '"texto"'):
				with open(path, "w", encoding="utf-8") as f:
					f.write(contenido)
				m = UserGestureMap()
				with mock.patch.object(UserGestureMap, "fileName", new_callable=mock.PropertyMock, return_value=path):
					m.load()
				self.assertIsInstance(m._map, dict)
		finally:
			shutil.rmtree(tmp, ignore_errors=True)

	def test_simbolos_con_raiz_no_valida(self) -> None:
		from tiresias.speech.symbols import SymbolProcessor

		tmp = tempfile.mkdtemp(prefix="tiresias_simbolos_")
		try:
			for name, contenido in (("zz.json", "[]"), ("emoji_zz.json", "[1]")):
				with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
					f.write(contenido)
			p = SymbolProcessor("zz")
			with mock.patch.object(paths, "symbolsDir", return_value=tmp):
				p.load()
			self.assertEqual(p.defaults, {})
			self.assertEqual(p.emoji, {})
		finally:
			shutil.rmtree(tmp, ignore_errors=True)


# ====================================================================== interfaz
class TestVentanaPrincipal(unittest.TestCase):
	def test_cerrar_pide_salir_directamente(self) -> None:
		from tiresias import gui

		evt = mock.Mock()
		evt.CanVeto.return_value = True
		with mock.patch.object(core, "requestQuit") as rq, mock.patch.object(queue_handler, "queueFunction") as qf:
			gui.MainFrame.onClose(None, evt)
		evt.Veto.assert_called_once()
		rq.assert_called_once_with()
		qf.assert_not_called()

	def test_menu_que_falla_al_construirse_se_puede_volver_a_abrir(self) -> None:
		from tiresias import gui

		fake = types.SimpleNamespace(_inMenu=False, _menuActions={}, prePopup=mock.Mock(), postPopup=mock.Mock(), PopupMenu=mock.Mock())
		with mock.patch.object(gui, "_buildMainMenu", side_effect=RuntimeError("complemento")):
			with self.assertRaises(RuntimeError):
				gui.MainFrame.showMenu(fake)
		self.assertFalse(fake._inMenu)
		fake.postPopup.assert_not_called()


if __name__ == "__main__":
	unittest.main()
