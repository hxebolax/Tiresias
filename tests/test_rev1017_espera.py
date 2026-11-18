"""Pruebas de la 1.0.17: Tiresias en espera deja paso de verdad al otro lector.

- Con la cortina de Tiresias puesta, NVDA no podía activar la suya
  («Failed to enable Screen Curtain», error 87 de la API de ampliación): en
  espera, Tiresias suelta la cortina y la lupa sin cambiar sus opciones y
  las recupera al volver a activarse.
- El aviso «Tiresias está en espera» se pedía a NVDA cuando aún estaba
  arrancando (sin foco): NVDA dejaba un error en su registro y Tiresias se
  quedaba en un tono. Ahora espera a la ventana principal de NVDA y reintenta.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev1017_espera -v``
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import coexist, magnifier, vision  # noqa: E402
from tiresias.coexist import announce  # noqa: E402
from tiresias.config import conf  # noqa: E402


class CortinaTests(unittest.TestCase):
	def setUp(self) -> None:
		self.h = vision.VisionHandler()
		self.applied: list[bool] = []

		def apply(enable: bool) -> bool:
			self.applied.append(enable)
			self.h._curtainAcquired = enable
			self.h.curtainActive = enable
			return True

		for p in (mock.patch.object(self.h, "_applyCurtain", side_effect=apply), mock.patch("tiresias.magnifier.runOnGuiAndWait", side_effect=lambda f, timeout=3.0: f())):
			p.start()
			self.addCleanup(p.stop)
		self.old = conf["vision"]["screenCurtain"]
		self.addCleanup(lambda: conf["vision"].__setitem__("screenCurtain", self.old))

	def test_en_espera_suelta_la_cortina_sin_cambiar_la_opcion(self) -> None:
		conf["vision"]["screenCurtain"] = True
		self.h.curtainActive = self.h._curtainAcquired = True
		self.h.suspendForOtherReader()
		self.assertEqual(self.applied, [False])
		self.assertFalse(self.h.curtainActive)
		self.assertTrue(conf["vision"]["screenCurtain"])
		with mock.patch.object(self.h, "setScreenCurtain") as setCurtain:
			self.h.resumeAfterOtherReader()
		setCurtain.assert_called_once_with(True, announce=False, startup=True)

	def test_sin_cortina_no_hace_nada(self) -> None:
		self.h.suspendForOtherReader()
		with mock.patch.object(self.h, "setScreenCurtain") as setCurtain:
			self.h.resumeAfterOtherReader()
		self.assertEqual(self.applied, [])
		setCurtain.assert_not_called()

	def test_si_entretanto_se_desactivo_no_vuelve(self) -> None:
		self.h.curtainActive = self.h._curtainAcquired = True
		self.h.suspendForOtherReader()
		conf["vision"]["screenCurtain"] = False
		with mock.patch.object(self.h, "setScreenCurtain") as setCurtain:
			self.h.resumeAfterOtherReader()
		setCurtain.assert_not_called()

	def test_arrancar_en_espera_no_pone_la_cortina(self) -> None:
		conf["vision"]["screenCurtain"] = True
		with mock.patch.object(vision, "_otherReaderHasPriority", return_value=True), mock.patch.object(self.h, "setScreenCurtain") as setCurtain, mock.patch(
			"tiresias.api.post_focusChange"
		), mock.patch("tiresias.api.post_reviewMove"), mock.patch("tiresias.api.post_navigatorObjectChange"), mock.patch("tiresias.events.post_event", create=True), mock.patch.object(
			self.h, "anyHighlight", return_value=False
		):
			try:
				self.h.initialize()
			except Exception:
				pass
		setCurtain.assert_not_called()
		self.assertTrue(self.h._curtainSuspended)


class LupaTests(unittest.TestCase):
	def test_suelta_y_recupera(self) -> None:
		m = magnifier.Magnifier()
		m.active = True
		with mock.patch.object(m, "setActive") as setActive:
			m.suspendForOtherReader()
			m.resumeAfterOtherReader()
		self.assertEqual(setActive.call_args_list, [mock.call(False, announce=False), mock.call(True, announce=False)])

	def test_apagada_no_se_enciende(self) -> None:
		m = magnifier.Magnifier()
		with mock.patch.object(m, "setActive") as setActive:
			m.suspendForOtherReader()
			m.resumeAfterOtherReader()
		setActive.assert_not_called()


class PasosTests(unittest.TestCase):
	def test_paso_de_reanudacion(self) -> None:
		names = [s[0] for s in coexist._resumeSteps()]
		self.assertIn("cortina y lupa", names)

	def test_ceder_suelta_la_cortina(self) -> None:
		steps: list[str] = []
		with mock.patch.object(coexist, "_step", side_effect=lambda name, func, *a: steps.append(name)):
			coexist._suspendAll()
		self.assertIn("cortina y lupa", steps)

	def test_visionStandby(self) -> None:
		with mock.patch.object(vision.handler, "suspendForOtherReader") as vs, mock.patch.object(magnifier.magnifier, "suspendForOtherReader") as ms:
			coexist._visionStandby(True)
		vs.assert_called_once()
		ms.assert_called_once()


class FakeClient:
	def __init__(self, results: list[int]) -> None:
		self.results = list(results)
		self.spoken = 0
		self.braille = 0

	def testIfRunning(self) -> int:
		return 0

	def getProcessId(self):
		return 0, 1234

	def speakText(self, text: str) -> int:
		self.spoken += 1
		return self.results.pop(0) if self.results else 0

	def brailleMessage(self, text: str) -> int:
		self.braille += 1
		return 0


class AvisoNvdaTests(unittest.TestCase):
	def test_espera_la_ventana_principal(self) -> None:
		pids = iter([0, 0, 1234])
		slept: list[float] = []
		ok = announce.waitNvdaReady(SimpleNamespace(pid=1234), time.monotonic() + 5, lambda: True, sleep=slept.append, findPid=lambda: next(pids))
		self.assertTrue(ok)
		self.assertEqual(slept, [0.5, 0.5, announce.NVDA_WINDOW_SETTLE])

	def test_ventana_de_otro_nvda(self) -> None:
		ok = announce.waitNvdaReady(SimpleNamespace(pid=1234), time.monotonic() + 0.01, lambda: True, sleep=lambda s: time.sleep(0.005), findPid=lambda: 999)
		self.assertFalse(ok)

	def _speak(self, client: FakeClient) -> bool:
		with mock.patch("tiresias.controller.server.nvdaClient", return_value=client), mock.patch.object(announce, "waitNvdaReady", return_value=True), mock.patch.object(
			announce.time, "sleep"
		), mock.patch.object(announce.os, "getpid", return_value=1):
			return announce.speakThroughNvda("hola", SimpleNamespace(pid=1234), 5.0, lambda: True)

	def test_reintenta_mientras_nvda_arranca(self) -> None:
		client = FakeClient([-1, -1, 0])
		self.assertTrue(self._speak(client))
		self.assertEqual(client.spoken, 3)
		self.assertEqual(client.braille, 1)

	def test_se_rinde_tras_los_reintentos(self) -> None:
		client = FakeClient([-1] * 10)
		self.assertFalse(self._speak(client))
		self.assertEqual(client.spoken, announce.NVDA_SPEAK_RETRIES)


if __name__ == "__main__":
	unittest.main()
