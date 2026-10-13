"""Pruebas de regresión de la revisión del paquete de voz (versión 1.0.6).

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_revision_voz -v``
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_revision_voz_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]
else:
	_TMP = paths._dataDirForTests  # type: ignore[attr-defined]
	if not os.path.isdir(os.path.join(_TMP, "symbols")):
		shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))

from tiresias import queue_handler  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.speech import api as speech  # noqa: E402
from tiresias.speech import languages, plugin, sayall, symbols  # noqa: E402
from tiresias.speech.commands import IndexCommand  # noqa: E402
from tiresias.speech.symbols import LEVEL_NONE, SymbolProcessor  # noqa: E402
from tiresias.textinfo import UNIT_LINE, StaticTextInfo  # noqa: E402

LINES = "uno\ndos\ntres\ncuatro\ncinco\nseis\nsiete\nocho\n"


class _Conf:
	"""Cambia opciones durante una prueba y las restablece al salir."""

	def __init__(self, section: str, **values) -> None:
		self.section = section
		self.values = values
		self.old: dict = {}

	def __enter__(self):
		for k, v in self.values.items():
			self.old[k] = conf[self.section][k]
			conf[self.section][k] = v
		return self

	def __exit__(self, *exc):
		for k, v in self.old.items():
			conf[self.section][k] = v


class FakeSynth:
	name = "fakeRevision"
	language = "es_ES"
	availableLanguages = ("es_ES",)

	def __init__(self) -> None:
		self.sent: list[list] = []
		self.cancelled = 0

	def speak(self, seq: list) -> None:
		self.sent.append(list(seq))

	def cancel(self) -> None:
		self.cancelled += 1

	def pause(self, switch: bool) -> None:
		pass

	def getSetting(self, sid):
		return "v1" if sid == "voice" else 50

	def isSupported(self, sid) -> bool:
		return True

	@property
	def availableVoices(self):
		return {}

	def allText(self, start: int = 0) -> str:
		return " ".join(x for seq in self.sent[start:] for x in seq if isinstance(x, str))


class _SynthCase(unittest.TestCase):
	def setUp(self) -> None:
		from tiresias import synth

		self.synth = FakeSynth()
		self._old = synth._current
		synth._current = self.synth  # type: ignore[assignment]
		languages._supportedCache = None
		speech._manager = None
		self.mgr = speech.getManager()
		self._conf = _Conf("speech", speechMode="talk", sayAllUnit="line", sayAllWithoutPauses=False, sayAllRateOffset=0)
		self._conf.__enter__()

	def tearDown(self) -> None:
		from tiresias import synth

		sayall.stop()
		self.mgr.cancel()
		self._conf.__exit__()
		synth._current = self._old
		speech._manager = None
		languages._supportedCache = None

	def finishAll(self) -> None:
		done: set[int] = set()
		for _round in range(40):
			pending = [x.index for seq in self.synth.sent for x in seq if isinstance(x, IndexCommand) and x.index not in done]
			if not pending:
				break
			for idx in pending:
				done.add(idx)
				self.mgr._indexReached(idx)
			if not sayall.isRunning():
				break


# ---------------------------------------------------------------------- símbolos
class RepeatedSymbolsThresholdTests(unittest.TestCase):
	"""La opción «Número mínimo de repeticiones» admite 2 y 3 (antes solo 4 o más)."""

	@classmethod
	def setUpClass(cls) -> None:
		cls.proc = SymbolProcessor()
		cls.proc.load()

	def test_threshold_two(self) -> None:
		self.assertIn("2 guion", self.proc.process("a--b", LEVEL_NONE, repeatThreshold=2))

	def test_threshold_three(self) -> None:
		self.assertIn("3 guion", self.proc.process("a---b", LEVEL_NONE, repeatThreshold=3))

	def test_multichar_symbol_kept(self) -> None:
		# «...» tiene nombre propio: no se convierte en «3 punto» con el mínimo en 3.
		out = self.proc.process("fin...", 300, repeatThreshold=3)
		self.assertIn("puntos suspensivos", out)
		self.assertNotIn("3 punto", out)

	def test_default_threshold_unchanged(self) -> None:
		self.assertNotIn("3 guion", self.proc.process("a---b", LEVEL_NONE, repeatThreshold=4))
		self.assertIn("4 guion", self.proc.process("a----b", LEVEL_NONE, repeatThreshold=4))


class MissingSymbolTableCacheTests(unittest.TestCase):
	"""Un idioma sin tabla no vuelve a leer la carpeta de símbolos en cada frase."""

	def test_missing_language_is_cached(self) -> None:
		symbols.reloadAll()
		with mock.patch.object(symbols, "availableLanguages", wraps=symbols.availableLanguages) as avail:
			self.assertIsNone(symbols.getProcessor("xx_YY"))
			self.assertIsNone(symbols.getProcessor("xx"))
			self.assertIsNone(symbols.getProcessor("xx"))
			self.assertEqual(avail.call_count, 1)
		# reloadAll olvida la caché (por si se añade una tabla).
		symbols.reloadAll()
		self.assertNotIn("xx", symbols._missing)


# ---------------------------------------------------------------------- idiomas
class SupportedLanguagesTests(unittest.TestCase):
	def test_failing_property_does_not_break_speech(self) -> None:
		from tiresias import synth

		class BadSynth(FakeSynth):
			@property
			def availableLanguages(self):  # type: ignore[override]
				raise RuntimeError("COM")

		old = synth._current
		synth._current = BadSynth()  # type: ignore[assignment]
		languages._supportedCache = None
		try:
			self.assertIsNone(languages.supportedLanguages())
			self.assertTrue(languages.isSupported("en"))
		finally:
			synth._current = old
			languages._supportedCache = None


# ---------------------------------------------------------------------- lectura continua
class SayAllCancelRaceTests(_SynthCase):
	"""La parada encolada al cancelar la voz no debe detener una lectura nueva."""

	def test_restart_before_queued_stop_keeps_new_reading(self) -> None:
		deferred: list = []

		def fakeQueue(func, *args, **kwargs):
			deferred.append((func, args, kwargs))

		sayall.readText(sayall.CURSOR_REVIEW, StaticTextInfo(None, (0, 0), LINES))
		self.assertTrue(sayall.isRunning())
		with mock.patch.object(queue_handler, "queueFunction", fakeQueue):
			# Una tecla cancela la voz (la parada se encola) y su orden vuelve a
			# empezar la lectura (Tiresias+flecha abajo otra vez, o reanudar tras hojear).
			speech.cancelSpeech()
			sayall.readText(sayall.CURSOR_REVIEW, StaticTextInfo(None, (0, 0), LINES))
		self.assertTrue(deferred)
		for func, args, kwargs in deferred:
			func(*args, **kwargs)
		self.assertTrue(sayall.isRunning())

	def test_queued_stop_still_stops_old_reading(self) -> None:
		sayall.readText(sayall.CURSOR_REVIEW, StaticTextInfo(None, (0, 0), LINES))
		speech.cancelSpeech()
		self.assertFalse(sayall.isRunning())
		self.assertIsNone(sayall._reader)


class SayAllSpeechModeTests(_SynthCase):
	def test_on_demand_reads_to_the_end(self) -> None:
		with _Conf("speech", speechMode="onDemand"):
			with speech.allowOnDemand():
				sayall.readText(sayall.CURSOR_REVIEW, StaticTextInfo(None, (0, 0), LINES))
			# Los trozos siguientes se encolan fuera de la orden.
			self.finishAll()
			self.assertIn("ocho", self.synth.allText())
			self.assertFalse(sayall.isRunning())

	def test_on_demand_without_command_does_not_get_stuck(self) -> None:
		with _Conf("speech", speechMode="onDemand"):
			sayall.readText(sayall.CURSOR_REVIEW, StaticTextInfo(None, (0, 0), LINES))
			self.assertEqual(self.synth.sent, [])
			self.assertFalse(sayall.isRunning())

	def test_speech_off_does_not_get_stuck(self) -> None:
		with _Conf("speech", speechMode="off"):
			sayall.readText(sayall.CURSOR_REVIEW, StaticTextInfo(None, (0, 0), LINES))
			self.assertFalse(sayall.isRunning())

	def test_other_speech_stays_silent_on_demand(self) -> None:
		with _Conf("speech", speechMode="onDemand"):
			with speech.allowOnDemand():
				sayall.readText(sayall.CURSOR_REVIEW, StaticTextInfo(None, (0, 0), LINES))
			before = len(self.synth.sent)
			speech.speak(["notificación"])
			self.assertEqual(len(self.synth.sent), before)

	def test_table_scripts_speak_on_demand(self) -> None:
		self.assertTrue(getattr(plugin.SpeechGlobalPlugin.script_sayAllInTableColumn, "speakOnDemand", False))
		self.assertTrue(getattr(plugin.SpeechGlobalPlugin.script_sayAllInTableRow, "speakOnDemand", False))


class PauseAndStandbyTests(_SynthCase):
	def test_speaking_while_paused_cancels_pause(self) -> None:
		speech.speak(["uno"])
		speech.pauseSpeech(True)
		cancelled = self.synth.cancelled
		speech.speak(["dos"])
		self.assertFalse(speech.isPaused())
		self.assertGreater(self.synth.cancelled, cancelled)
		self.assertIn("dos", self.synth.allText(-1))

	def test_message_not_shown_in_braille_in_standby(self) -> None:
		with mock.patch.object(speech, "_brailleMessage") as braille:
			speech.setSuspended(True)
			try:
				speech.speakMessage("hola")
			finally:
				speech.setSuspended(False)
			braille.assert_not_called()
			speech.speakMessage("hola")
			braille.assert_called_once_with("hola")


class SayAllSkipTests(_SynthCase):
	def test_skip_before_any_unit_reached_starts_from_beginning(self) -> None:
		sayall.readText(sayall.CURSOR_REVIEW, StaticTextInfo(None, (0, 0), LINES))
		start = len(self.synth.sent)
		# Aún no se ha alcanzado ninguna unidad: se salta desde la primera
		# línea, no desde la que lleva adelantada el lector.
		self.assertTrue(sayall.skip(UNIT_LINE, 1))
		first = " ".join(x for x in self.synth.sent[start] if isinstance(x, str))
		self.assertIn("dos", first)


if __name__ == "__main__":
	unittest.main()
