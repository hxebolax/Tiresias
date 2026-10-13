"""Pruebas de regresión de la revisión 1.0.6 (braille, voz, audio, visión, remoto...).

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import os
import queue
import shutil
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="tiresias_test_rev106p4_")
if not os.path.isdir(os.path.join(_TMP, "symbols")):
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
paths.setDataDir(_TMP)
paths.ensureDataDirs()


class _FakePlayer:
	def __init__(self) -> None:
		self.fed: list = []

	def feed(self, data, onDone=None) -> None:
		self.fed.append(data)
		if onDone is not None:
			onDone()

	def stop(self) -> None:
		pass

	def terminate(self) -> None:
		pass

	def pause(self, switch) -> None:
		pass


def _makeSynth(segment):
	"""Sintetizador de audio de prueba con hilo de trabajo real y sin tarjeta de sonido."""
	from tiresias.synth.base import AudioSynthDriver

	class Fake(AudioSynthDriver):
		name = "falsoRev"

		def __init__(self) -> None:  # sin WavePlayer real
			self._settings = {}
			self._generation = 0
			self._queue = queue.Queue()
			self._player = _FakePlayer()
			self._speaking = False
			self._worker = threading.Thread(target=self._run, name="Synth-falsoRev", daemon=True)
			self._workerStarted = False
			self._errorCount = 0
			self._busySince = 0.0
			self._failed = False
			self.sampleRate = 8000
			self.done = 0

		def _synthesizeSegment(self, items, emit, isCancelled) -> None:
			segment(self, items, emit, isCancelled)

		def _notifyDone(self) -> None:
			self.done += 1

		def _notifyIndex(self, index) -> None:
			pass

	return Fake()


class SynthWorkerQueueTests(unittest.TestCase):
	def test_cancel_keeps_worker_jobs(self) -> None:
		"""cancel() descarta la voz pendiente pero no los trabajos de runInWorker."""
		synth = _makeSynth(lambda s, items, emit, c: None)
		ran = threading.Event()
		synth._queue.put((0, ["voz pendiente"]))
		synth._queue.put(ran.set)
		synth._queue.put((0, ["otra"]))
		synth.cancel()
		items = list(synth._queue.queue)
		self.assertEqual(items, [ran.set])
		synth._ensureWorker()
		self.assertTrue(ran.wait(5))
		synth.terminate()

	def test_speech_pending_ignores_jobs(self) -> None:
		synth = _makeSynth(lambda s, items, emit, c: None)
		synth._queue.put(lambda: None)
		self.assertFalse(synth._speechPending())
		synth._queue.put((0, ["hola"]))
		self.assertTrue(synth._speechPending())

	def test_done_notified_with_export_job_queued(self) -> None:
		"""Con un trabajo de exportación en cola, el fin de la voz se sigue avisando (lectura continua)."""
		gate = threading.Event()

		def segment(s, items, emit, c):
			emit(b"\x00\x00")

		synth = _makeSynth(segment)
		synth._queue.put((0, ["hola"]))
		synth._queue.put(gate.wait)  # trabajo largo detrás de la voz
		synth._ensureWorker()
		deadline = time.monotonic() + 5
		while synth.done == 0 and time.monotonic() < deadline:
			time.sleep(0.01)
		self.assertEqual(synth.done, 1)
		gate.set()
		synth.terminate()


class AudioExportInterleaveTests(unittest.TestCase):
	def test_export_survives_cancel_and_interleaves(self) -> None:
		"""Una cancelación de voz durante la exportación repite el trozo cortado y no pierde trabajos."""
		from tiresias import audio_export
		from tiresias.synth.base import splitLongText

		calls: list[str] = []
		state = {"cut": False}

		def segment(s, items, emit, isCancelled):
			text = items[0]
			calls.append(text)
			emit(b"\x01\x00" * 10)
			if not state["cut"]:
				# Una tecla cancela la voz en mitad del primer trozo y llega voz nueva.
				state["cut"] = True
				s.cancel()
				s.speak(["voz del lector"])
				return
			emit(b"\x01\x00" * (len(text) - 10))

		synth = _makeSynth(segment)
		text = "Frase de prueba número uno. " * 60
		pieces = [p for p in splitLongText(text, 400) if p.strip()]
		self.assertGreater(len(pieces), 2)
		pcm, rate, ch = audio_export.renderPcm(text, synth, timeout=10)
		self.assertEqual((rate, ch), (8000, 1))
		# El primer trozo se generó dos veces y el audio no sale cortado.
		self.assertEqual(len(pcm), sum(2 * max(len(p), 10) for p in pieces))
		# La voz del lector se intercaló entre los trozos de la exportación.
		self.assertIn("voz del lector", calls)
		self.assertLess(calls.index("voz del lector"), len(calls) - 1)
		synth.terminate()

	def test_export_fails_fast_when_synth_closes(self) -> None:
		from tiresias import audio_export

		def segment(s, items, emit, c):
			emit(b"\x00\x00")

		synth = _makeSynth(segment)
		synth._ensureWorker()
		synth._queue.put(None)  # el hilo termina (cambio de voz)
		synth._worker.join(5)
		t = time.monotonic()
		with self.assertRaises(audio_export.ExportError):
			audio_export.renderPcm("Hola. " * 10, synth, timeout=30)
		self.assertLess(time.monotonic() - t, 5)


class BraillePresenterTests(unittest.TestCase):
	def test_single_handleCustom_clamps_cursor(self) -> None:
		"""handleCustom solo se define una vez y limita el cursor al texto."""
		import inspect

		from tiresias.braille import presenter

		src = inspect.getsource(presenter.BraillePresenter)
		self.assertEqual(src.count("def handleCustom("), 1)
		got = {}
		class P(presenter.BraillePresenter):
			enabled = True
			speechMode = False

		p = P.__new__(P)
		p._regionKind = "custom"
		p._regionObj = None
		p._setRegion = lambda text, cursor, selection=None, keepWindow=False: got.update(cursor=cursor, keep=keepWindow)
		p.handleCustom("abc", 10, None)
		self.assertEqual(got["cursor"], 3)
		self.assertTrue(got["keep"])
		p.handleCustom("abc", None, object())
		self.assertIsNone(got["cursor"])
		self.assertFalse(got["keep"])

	def test_bidi_marks_written_as_escapes(self) -> None:
		path = os.path.join(ROOT, "src", "tiresias", "braille", "presenter.py")
		with open(path, encoding="utf-8") as f:
			src = f.read()
		for ch in "\u200e\u200f\u202a\u202b\u202c\u202d\u202e":
			self.assertNotIn(ch, src)
		from tiresias.braille import presenter

		self.assertEqual("a\u200eb\u202ec".translate(presenter._BIDI_MARKS), "abc")


class MsvcRuntimeTests(unittest.TestCase):
	def test_modern_msvcp_loaded_first(self) -> None:
		"""La msvcp140.dll del proceso es la moderna (winrt trae una antigua que cuelga onnxruntime)."""
		import tiresias  # noqa: F401  (hace la precarga)
		from tiresias import msvc_runtime

		path = msvc_runtime.loadedPath()
		self.assertTrue(path)
		self.assertNotIn("winrt", path.lower())
		self.assertTrue(msvc_runtime.isModernEnough())


if __name__ == "__main__":
	unittest.main()
