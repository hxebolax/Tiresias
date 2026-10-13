"""Pruebas de regresión de la revisión 1.0.6 (convivencia, guardián y API de control).

- La activación tras la espera anuncia enseguida y deja lo lento (ganchos,
  eventos UIA, braille, indicador de lector de pantalla, auxiliar de NVDA)
  para después, un paso por ciclo del núcleo; si Tiresias vuelve a ceder
  entretanto, los pasos pendientes no se ejecutan.
- La vigilancia filtra con la lista de lectores vigente (carrera con
  ``applyConfiguration``) y ``_onStableReaders`` usa el conjunto actual.
- La máquina de estados recuerda el lector actual mientras está activa junto
  a otro lector.
- El latido del guardián no escribe en una vista ya cerrada.
- El estado de la API de control no promete reintentos con la API desactivada.
- Los anuncios por el otro lector se abandonan al cerrar Tiresias.

Todo con objetos simulados: no se lanza ningún lector ni se toca el sistema.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_revision_convivencia -v``
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import coexist  # noqa: E402
from tiresias.coexist import detect, relaunch, state  # noqa: E402
from tiresias.coexist.detect import ReaderInfo  # noqa: E402


def _r(rid: str, ready: bool = True, pid: int = 100) -> ReaderInfo:
	return ReaderInfo(rid, detect.SPECS[rid].name, pid, ready=ready)


class _FakeQueue:
	"""Sustituye a ``queue_handler``: guarda lo encolado y lo programado."""

	def __init__(self, log: list) -> None:
		self.log = log
		self.timers: list = []

	def callLater(self, delay, func, *args, **kwargs):
		self.log.append(("callLater", getattr(func, "__name__", repr(func))))
		self.timers.append((func, args, kwargs))
		return len(self.timers)

	def queueFunction(self, func, *args, **kwargs):
		self.log.append(("queue", getattr(func, "__name__", repr(func))))

	def runOneTimer(self) -> bool:
		if not self.timers:
			return False
		func, args, kwargs = self.timers.pop(0)
		func(*args, **kwargs)
		return True


class _FakeSpeech:
	def __init__(self, log: list) -> None:
		self.log = log

	def speakMessage(self, text):
		self.log.append(("speak", text))

	def whenDoneSpeaking(self, callback):
		self.log.append(("whenDoneSpeaking",))


class ActivationTests(unittest.TestCase):
	"""goActive: anuncio primero, lo lento después y en ciclos distintos del núcleo."""

	def setUp(self):
		self.log: list = []
		self.queue = _FakeQueue(self.log)
		fakeSpeech = _FakeSpeech(self.log)
		steps = [(name, (lambda n=name: self.log.append(("step", n))), ()) for name in ("entrada", "táctil", "eventos UIA", "braille", "indicador", "controlador", "cadena")]
		self.machine = state.Coexistence(coexist._Actions())
		self.machine.state = state.STANDBY
		self.machine.reader = _r("nvda")
		self.patches = [
			mock.patch.object(coexist, "queue_handler", self.queue),
			mock.patch.object(coexist, "_resumeSpeech", lambda: self.log.append(("resumeSpeech",))),
			mock.patch.object(coexist, "_resumeSteps", lambda: list(steps)),
			mock.patch.object(coexist, "_updateGui", lambda: None),
			mock.patch.object(coexist, "_suspendAll", lambda: self.log.append(("suspendAll",))),
			mock.patch.object(coexist, "_runPendingOnActive", lambda: self.log.append(("pending",))),
			mock.patch.object(coexist, "_machine", self.machine),
			mock.patch("tiresias.speech", fakeSpeech, create=True),
		]
		for p in self.patches:
			p.start()

	def tearDown(self):
		for p in reversed(self.patches):
			p.stop()

	def test_anuncio_antes_de_lo_lento(self):
		self.machine.onReaders([])
		kinds = [e[0] for e in self.log]
		# Voz, anuncio y nada lento todavía: solo queda programado el primer paso.
		self.assertEqual(kinds[:2], ["resumeSpeech", "speak"])
		self.assertNotIn("step", kinds)
		self.assertEqual(self.log[-1], ("callLater", "_runResumeSteps"))
		# Cada paso se ejecuta en su propio ciclo (callLater, no queueFunction).
		while self.queue.runOneTimer():
			pass
		steps = [e[1] for e in self.log if e[0] == "step"]
		self.assertEqual(steps, ["entrada", "táctil", "eventos UIA", "braille", "indicador", "controlador", "cadena"])
		# Un paso por temporizador: tras cada paso se programa el siguiente.
		order = [e for e in self.log if e[0] in ("step", "callLater")]
		for i, e in enumerate(order):
			if e[0] == "step":
				self.assertEqual(order[i + 1][0], "callLater")
		# Al final, el foco (tras la voz) y las tareas aplazadas.
		self.assertEqual(self.log[-2:], [("whenDoneSpeaking",), ("pending",)])

	def test_ceder_a_mitad_abandona_los_pasos(self):
		self.machine.onReaders([])
		self.queue.runOneTimer()  # entrada
		self.queue.runOneTimer()  # táctil
		# Vuelve NVDA: Tiresias cede antes de terminar la activación.
		self.machine.onReaders([_r("nvda")])
		self.assertTrue(self.machine.isStandby)
		while self.queue.runOneTimer():
			pass
		steps = [e[1] for e in self.log if e[0] == "step"]
		self.assertEqual(steps, ["entrada", "táctil"])
		self.assertNotIn(("pending",), self.log)

	def test_pasos_reales_en_orden(self):
		# La lista real empieza por la entrada y termina con la cadena de órdenes.
		self.patches[2].stop()
		try:
			names = [s[0] for s in coexist._resumeSteps()]
		finally:
			self.patches[2].start()
		self.assertEqual(names[0], "entrada")
		self.assertEqual(names[-1], "cadena de órdenes")
		self.assertIn("indicador de lector de pantalla", names)
		self.assertIn("eventos UIA", names)
		self.assertNotIn("voz", names)


class PollRaceTests(unittest.TestCase):
	"""La vigilancia usa la lista de lectores vigente, no la del principio del sondeo."""

	def setUp(self):
		self.queued: list = []
		self.patches = [
			mock.patch.object(coexist, "_debouncer", state.Debouncer()),
			mock.patch.object(coexist, "_enabled", frozenset({"nvda", "jaws"})),
			mock.patch.object(coexist, "_nvdaSeen", True),
			mock.patch.object(coexist.detect, "isSecureDesktopActive", lambda: False),
			mock.patch.object(coexist.queue_handler, "queueFunction", lambda f, *a, **k: self.queued.append((f, a))),
		]
		for p in self.patches:
			p.start()

	def tearDown(self):
		for p in reversed(self.patches):
			p.stop()

	def test_lector_quitado_durante_el_sondeo(self):
		class _Det:
			def detect(self, enabled):
				# Mientras se detecta, el usuario quita JAWS de la lista.
				coexist._enabled = frozenset({"nvda"})
				return [_r("nvda"), _r("jaws", pid=200)]

		coexist._poll(_Det())
		self.assertEqual(set(coexist._debouncer.stable), {"nvda"})
		# Se encola sin el conjunto del sondeo: _onStableReaders lee el actual.
		self.assertEqual(self.queued, [(coexist._onStableReaders, ())])

	def test_on_stable_readers_usa_el_conjunto_actual(self):
		seen = []
		machine = mock.Mock()
		machine.onReaders.side_effect = lambda readers: seen.append([r.id for r in readers])
		coexist._debouncer.reset([_r("nvda")])
		with mock.patch.object(coexist, "_machine", machine), mock.patch.object(coexist, "_rememberReaders", lambda r: None), mock.patch.object(coexist, "_updateGui", lambda: None):
			# Argumento antiguo (de un sondeo anterior a applyConfiguration): se ignora.
			coexist._onStableReaders([_r("jaws", pid=200)])
		self.assertEqual(seen, [["nvda"]])


class _NoActions:
	def __init__(self) -> None:
		self.calls: list = []

	def goStandby(self, reader, initial):
		self.calls.append(("standby", reader.id))

	def goActive(self, reason, reader):
		self.calls.append(("active", reason, reader.id if reader else None))


class MachineReaderTests(unittest.TestCase):
	def test_forzado_sigue_al_lector_en_ejecucion(self):
		m = state.Coexistence(_NoActions())
		m.start([_r("nvda")], True, forced=True)
		self.assertEqual(m.reader.id, "nvda")
		# NVDA se cierra pero queda JAWS: «Ceder el paso a...» debe decir JAWS.
		m.onReaders([_r("jaws", pid=200)])
		self.assertFalse(m.isStandby)
		self.assertEqual(m.reader.id, "jaws")
		self.assertTrue(m.yieldNow())
		self.assertEqual(m.actions.calls[-1], ("standby", "jaws"))

	def test_opcion_desactivada_sigue_al_lector(self):
		m = state.Coexistence(_NoActions())
		m.start([], False)
		m.onReaders([_r("jaws", pid=200)])
		self.assertFalse(m.isStandby)
		self.assertEqual(m.reader.id, "jaws")
		m.onReaders([])
		self.assertIsNone(m.reader)


class HeartbeatTests(unittest.TestCase):
	def test_latido_tras_cerrar_no_falla(self):
		# PID ficticio: solo crea una memoria compartida propia de la prueba.
		hb = relaunch.Heartbeat(pid=3_999_999_001)
		reader = relaunch.HeartbeatReader(3_999_999_001)
		try:
			hb.beat()
			armed, stale = reader.read()
			self.assertTrue(armed)
			self.assertLess(stale, 5)
		finally:
			reader.close()
		hb.close()
		# El vigilante puede latir justo después del cierre: no debe tocar la vista liberada.
		hb.beat()
		hb.close()


class ControllerStatusTests(unittest.TestCase):
	def test_api_desactivada_no_promete_reintentos(self):
		from tiresias import controller

		conf = dict(controller.DEFAULTS, enabled=False)
		with (
			mock.patch.object(controller, "_conf", lambda: conf),
			mock.patch.object(controller, "_initialized", True),
			mock.patch.object(controller, "_server", object()),
			mock.patch.object(controller, "_inStandby", lambda: False),
			mock.patch.object(controller, "_nvdaRunning", lambda: False),
			mock.patch.object(controller, "isServingNvda", lambda: False),
			mock.patch.object(controller, "getClients", lambda: []),
		):
			text = controller.statusText()
			self.assertIn("desactivada", text)
			self.assertNotIn("Compatibilidad con NVDA", text)
			conf["enabled"] = True
			text = controller.statusText()
			self.assertIn("Compatibilidad con NVDA: no disponible por ahora", text)


class AnnounceAfterTerminateTests(unittest.TestCase):
	def test_anuncio_se_abandona_al_cerrar(self):
		captured = []
		machine = state.Coexistence(_NoActions())
		machine.state = state.STANDBY
		machine.reader = _r("nvda")
		with (
			mock.patch.object(coexist, "_machine", machine),
			mock.patch.object(coexist._announcer, "announce", lambda reader, text, valid: captured.append(valid)),
			mock.patch.object(coexist, "_initialized", True),
		):
			coexist._announceStandby(machine.reader)
			valid = captured[0]
			self.assertTrue(valid())
			coexist._initialized = False
			self.assertFalse(valid())


if __name__ == "__main__":
	unittest.main()
