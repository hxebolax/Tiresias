"""Pruebas de la API de control (compatibilidad con nvdaControllerClient).

- Interpretación del SSML de ``speakSsml``.
- Conversión a secuencia de voz.
- Servidor RPC nativo + biblioteca cliente propia en el mismo proceso: se
  comprueba que las llamadas llegan a los manejadores, que las marcas SSML
  vuelven al cliente y los códigos de error. Si ya hay un Tiresias en
  ejecución en este escritorio (punto de conexión ocupado), esa parte se
  omite para no hablar por él.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import sys
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias.controller import ssml  # noqa: E402
from tiresias.controller import server as srv  # noqa: E402


class SsmlTests(unittest.TestCase):
	def test_texto_plano(self):
		self.assertEqual(ssml.parse("Hola mundo"), ["Hola mundo"])
		self.assertEqual(ssml.parse(""), [])

	def test_marcas_y_pausas(self):
		items = ssml.parse('<speak>Uno <mark name="a"/> dos<break time="500ms"/>tres<break strength="strong"/>cuatro<mark name="fin"/></speak>')
		self.assertEqual(items, ["Uno", ("mark", "a"), "dos", ("break", 500), "tres", ("break", 700), "cuatro", ("mark", "fin")])

	def test_prosodia_e_idioma(self):
		items = ssml.parse('<speak><prosody pitch="150%" rate="fast">rápido</prosody> normal <voice xml:lang="en-US">hello</voice></speak>')
		self.assertIn(("pitch", 1.5), items)
		self.assertIn(("rate", 1.5), items)
		self.assertIn(("lang", "en-US"), items)
		self.assertIn("hello", items)
		# Tras el bloque se vuelve al valor anterior.
		i = items.index("rápido")
		self.assertIn(("pitch", 1.0), items[i:])
		self.assertEqual(ssml.parseMultiplier("+20%", {}), 1.2)
		self.assertEqual(ssml.parseMultiplier("-50%", {}), 0.5)
		self.assertEqual(ssml.parseTime("1.5s"), 1500)
		self.assertEqual(ssml.parseTime("99s"), ssml.MAX_BREAK_MS)

	def test_deletreo_sustitucion_y_fonema(self):
		items = ssml.parse('<speak><say-as interpret-as="characters">abc</say-as> <sub alias="Organización">ONU</sub> <phoneme alphabet="ipa" ph="təˈmeɪtoʊ">tomato</phoneme></speak>')
		self.assertIn(("spell", "abc"), items)
		self.assertIn("Organización", items)
		self.assertIn(("phoneme", "təˈmeɪtoʊ", "tomato"), items)
		self.assertEqual(ssml.plainText(items), "abc Organización tomato")

	def test_ssml_invalido(self):
		self.assertEqual(ssml.parse("<speak>sin cerrar <b>"), ["sin cerrar"])
		self.assertEqual(ssml.parse("texto &amp; <mark name='m'/> más"), ["texto &", ("mark", "m"), "más"])

	def test_secuencia_de_voz(self):
		from tiresias import controller
		from tiresias.speech.commands import BreakCommand, CallbackCommand, LangChangeCommand, PitchCommand

		reached = []
		seq = controller.buildSequence(["Hola", ("break", 200), ("mark", "m1"), ("pitch", 1.5), ("lang", "en")], reached.append)
		self.assertEqual(seq[0], "Hola")
		self.assertIsInstance(seq[1], BreakCommand)
		self.assertIsInstance(seq[2], CallbackCommand)
		seq[2].callback()
		self.assertEqual(reached, ["m1"])
		self.assertIsInstance(seq[3], PitchCommand)
		self.assertEqual(seq[3].multiplier, 1.5)
		self.assertIsInstance(seq[4], LangChangeCommand)


class _Recorder(srv.Handlers):
	def __init__(self) -> None:
		self.calls: list = []
		self.server: srv.ControllerServer | None = None
		self.enabled = True

	def testIfRunning(self, pid):
		return 0 if self.enabled else srv.ERROR_SERVICE_NOT_ACTIVE

	def speakText(self, pid, text):
		self.calls.append(("speakText", pid, text))
		return 0 if self.enabled else srv.ERROR_SERVICE_NOT_ACTIVE

	def cancelSpeech(self, pid):
		self.calls.append(("cancel", pid))
		return 0

	def brailleMessage(self, pid, text):
		self.calls.append(("braille", text))
		return 0

	def speakSsml(self, pid, text, level, priority, asynchronous):
		self.calls.append(("ssml", text, level, priority, asynchronous))
		if not asynchronous:
			for name in ("a", "b"):
				self.server.markReached(name)
		return 0

	def isSpeaking(self, pid):
		return 0, True

	def speakTextEx(self, pid, text, flags):
		self.calls.append(("ex", text, flags))
		return 0

	def pauseSpeech(self, pid, pause):
		self.calls.append(("pause", pause))
		return 0 if self.enabled else srv.ERROR_SERVICE_NOT_ACTIVE


CLIENT = os.path.join(ROOT, "data", "controller", "x64", "tiresiasControllerClient.dll")


@unittest.skipUnless(os.path.isfile(srv.serverDllPath()) and os.path.isfile(CLIENT), "Faltan las bibliotecas nativas (python controller/build.py)")
class RpcTests(unittest.TestCase):
	recorder: _Recorder
	server: srv.ControllerServer

	@classmethod
	def setUpClass(cls):
		cls.recorder = _Recorder()
		cls.server = srv.ControllerServer(cls.recorder)
		cls.recorder.server = cls.server
		if cls.server.start() != 0:
			raise unittest.SkipTest("No se pudo registrar el servidor RPC")
		if cls.server.listen(srv.TIRESIAS_PREFIX) != 0:
			cls.server.stop()
			raise unittest.SkipTest("Ya hay un Tiresias en ejecución en este escritorio")
		cls.client = ctypes.WinDLL(CLIENT)

	@classmethod
	def tearDownClass(cls):
		cls.server.stop()

	def setUp(self):
		self.recorder.calls.clear()
		self.recorder.enabled = True

	def test_llamadas_basicas(self):
		c = self.client
		self.assertEqual(c.tiresiasController_testIfRunning(), 0)
		self.assertEqual(c.nvdaController_speakText("hola"), 0)
		self.assertEqual(c.tiresiasController_brailleMessage("braille"), 0)
		self.assertEqual(c.nvdaController_cancelSpeech(), 0)
		self.assertEqual(c.tiresiasController_speakTextEx("abc", 3), 0)
		self.assertEqual(c.tiresiasController_pauseSpeech(1), 0)
		pid = wt.ULONG()
		self.assertEqual(c.nvdaController_getProcessId(ctypes.byref(pid)), 0)
		self.assertEqual(pid.value, os.getpid())
		ver = wt.ULONG()
		self.assertEqual(c.tiresiasController_getApiVersion(ctypes.byref(ver)), 0)
		self.assertEqual(ver.value, 0x00010000)
		speaking = ctypes.c_ubyte()
		self.assertEqual(c.nvdaController_isSpeaking(ctypes.byref(speaking)), 0)
		self.assertEqual(speaking.value, 1)
		calls = self.recorder.calls
		self.assertIn(("speakText", os.getpid(), "hola"), calls)
		self.assertIn(("braille", "braille"), calls)
		self.assertIn(("ex", "abc", 3), calls)
		self.assertIn(("pause", True), calls)

	def test_ssml_sincrono_con_marcas(self):
		marks: list[str] = []
		CB = ctypes.WINFUNCTYPE(ctypes.c_ulong, wt.LPCWSTR)
		cb = CB(lambda m: (marks.append(m), 0)[1])
		self.client.nvdaController_setOnSsmlMarkReachedCallback(cb)
		try:
			res = self.client.nvdaController_speakSsml("<speak>uno <mark name='a'/> dos</speak>", -1, 2, 0)
		finally:
			self.client.nvdaController_setOnSsmlMarkReachedCallback(None)
		self.assertEqual(res, 0)
		self.assertEqual(marks, ["a", "b"])
		self.assertIn(("ssml", "<speak>uno <mark name='a'/> dos</speak>", -1, 2, False), self.recorder.calls)

	def test_desactivada(self):
		# Solo con funciones propias de Tiresias: las comunes probarían después
		# el punto de conexión de NVDA (y NVDA podría estar en ejecución).
		self.recorder.enabled = False
		self.assertEqual(self.client.tiresiasController_pauseSpeech(0), srv.ERROR_SERVICE_NOT_ACTIVE)

	def test_hilos(self):
		errors = []

		def worker(n: int) -> None:
			for i in range(20):
				if self.client.nvdaController_speakText(f"{n}-{i}") != 0:
					errors.append((n, i))

		threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
		for t in threads:
			t.start()
		for t in threads:
			t.join(10)
		self.assertEqual(errors, [])
		self.assertEqual(len([c for c in self.recorder.calls if c[0] == "speakText"]), 80)


if __name__ == "__main__":
	unittest.main()
