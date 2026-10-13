"""Revisión 1.0.11 de la voz, la síntesis y el audio (sin sonido por los altavoces).

Todo se prueba con reproductores, sintetizadores y sesiones de audio falsos:
no se abre ningún dispositivo de salida ni se cambia el volumen o el balance
de ninguna aplicación real.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev1011_voz``
"""

from __future__ import annotations

import collections
import ctypes
import importlib
import json
import os
import queue
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_rev1011_voz_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]
else:
	_TMP = paths._dataDirForTests  # type: ignore[attr-defined]
	if not os.path.isdir(os.path.join(_TMP, "symbols")):
		shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))

from tiresias import queue_handler  # noqa: E402
from tiresias import synth as synthHandler  # noqa: E402
from tiresias.audio import core_audio, ducking, sound_split, timestretch, tones, wave_player  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.speech import api as speech  # noqa: E402
from tiresias.speech import symbols  # noqa: E402
from tiresias.speech.commands import CallbackCommand, IndexCommand, LangChangeCommand, RateCommand  # noqa: E402
from tiresias.synth import base  # noqa: E402

SYNTH_DIR = os.path.join(ROOT, "data", "addons", "eloquence", "synthDrivers")
ELOQ_PKG = "tiresias_test_eloquence"
#: Eloquence es propietario: no está en el repositorio público (se distribuye
#: aparte en la tienda). Sin él, sus pruebas se saltan.
HAS_ELOQUENCE = os.path.isfile(os.path.join(SYNTH_DIR, "ibmtts.py"))
NO_ELOQUENCE = "Falta el complemento Eloquence (data/addons/eloquence): no se incluye en el repositorio"


def _waitFor(cond, timeout: float = 5.0) -> bool:
	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		if cond():
			return True
		time.sleep(0.005)
	return bool(cond())


# ====================================================================== falsos
class ManualPlayer:
	"""Reproductor falso que solo «suena» cuando la prueba lo pide."""

	def __init__(self, *a, **k) -> None:
		self.volume = 1.0
		self.muted = False
		self.items: collections.deque = collections.deque()
		self.lock = threading.Lock()
		self.played: list[bytes] = []
		self.stops = 0
		self.pending = 0.0
		self.paused = False

	def feed(self, data, onDone=None) -> None:
		with self.lock:
			self.items.append((data, onDone))

	def stop(self) -> None:
		with self.lock:
			self.items.clear()
			self.stops += 1

	def pause(self, switch) -> None:
		self.paused = switch

	def isPlaying(self) -> bool:
		return bool(self.items)

	def isPaused(self) -> bool:
		return self.paused

	def queuedSeconds(self) -> float:
		return self.pending

	def terminate(self) -> None:
		self.stop()

	def playAll(self) -> None:
		"""Hace sonar todo lo encolado, en orden, con sus retrollamadas."""
		while True:
			with self.lock:
				if not self.items:
					return
				data, cb = self.items.popleft()
			if data:
				self.played.append(data)
			if cb is not None:
				cb()


class FakeAudioSynth(base.AudioSynthDriver):
	name = "fakeAudio1011"
	description = "falso"
	supportedSettings = ()
	sampleRate = 1000

	@classmethod
	def check(cls) -> bool:
		return True

	def __init__(self) -> None:
		self.segments: list[list] = []
		self.delay = 0.0
		super().__init__()

	def _synthesizeSegment(self, items, emit, isCancelled) -> None:
		self.segments.append(list(items))
		if self.delay:
			time.sleep(self.delay)
		text = "".join(i for i in items if isinstance(i, str))
		emit(text.encode("utf-8", "replace") or b"x")


class RecordingSynth(base.SynthDriver):
	"""Sintetizador sin audio que avisa de sus índices al momento (o nunca)."""

	name = "recording1011"
	description = "grabador"
	supportedSettings = ()
	answer = True
	log: list[str] = []

	@classmethod
	def check(cls) -> bool:
		return True

	def speak(self, sequence) -> None:
		RecordingSynth.log.append(" ".join(i for i in sequence if isinstance(i, str)))
		if self.answer:
			for item in sequence:
				if isinstance(item, IndexCommand):
					self._notifyIndex(item.index)
			self._notifyDone()

	def cancel(self) -> None:
		pass


class _SpeechTestCase(unittest.TestCase):
	"""Núcleo «directo» (queueFunction ejecuta en el acto) y sintetizador propio."""

	def setUp(self) -> None:
		self._oldCore = queue_handler._coreThreadId
		queue_handler._coreThreadId = None
		self._oldSynth = synthHandler._current
		self._oldTrim = conf["speech"]["trimLeadingSilence"]
		conf["speech"]["trimLeadingSilence"] = False
		self._patched: list = []
		self.patch(base, "WavePlayer", ManualPlayer)
		speech.getManager().cancel()

	def patch(self, obj, name, value) -> None:
		self._patched.append((obj, name, getattr(obj, name)))
		setattr(obj, name, value)

	def tearDown(self) -> None:
		cur = synthHandler._current
		speech.getManager().cancel()
		if cur is not None and cur is not self._oldSynth:
			try:
				cur.terminate()
			except Exception:
				pass
		synthHandler._current = self._oldSynth
		for obj, name, value in reversed(self._patched):
			setattr(obj, name, value)
		conf["speech"]["trimLeadingSilence"] = self._oldTrim
		queue_handler._coreThreadId = self._oldCore
		speech.getManager().cancel()

	def idle(self, s: base.AudioSynthDriver) -> bool:
		return _waitFor(lambda: s._queue.empty() and not s._busySince)


# ====================================================================== 1: mudo tras cambiar de sintetizador
class CambioDeSintetizadorTests(_SpeechTestCase):
	def test_lo_enviado_al_sintetizador_caido_se_reenvia_al_nuevo(self) -> None:
		class Hung(RecordingSynth):
			name = "hung1011"
			answer = False

		class Good(RecordingSynth):
			name = "good1011"

		RecordingSynth.log = []
		synthHandler._externalModules["good1011"] = types.SimpleNamespace(SynthDriver=Good)
		oldPriority = list(conf["speech"]["synthPriority"])
		try:
			conf["speech"]["synthPriority"] = ["good1011"]
			synthHandler._current = Hung()
			mgr = speech.getManager()
			mgr.speak(["primera cosa"])
			mgr.speak(["segunda cosa"])
			self.assertEqual(len(mgr._sent), 2)
			# Como en el núcleo: lo encolado se ejecuta después de la tarea actual.
			queue_handler._coreThreadId = -1
			try:
				self.assertEqual(synthHandler.fallbackFrom("hung1011", "no responde"), "good1011")
				while queue_handler.pendingCount():
					queue_handler.pump()
			finally:
				queue_handler._coreThreadId = None
			spoken = RecordingSynth.log[2:]
			# Primero el aviso (prioridad «ahora») y después lo que quedó a medias.
			self.assertIn("ha fallado", spoken[0])
			self.assertTrue(any("primera cosa" in t for t in spoken[1:]))
			self.assertTrue(any("segunda cosa" in t for t in spoken[1:]))
			self.assertEqual(mgr.pendingCount(), 0)
			mgr.speak(["algo nuevo"])
			self.assertIn("algo nuevo", RecordingSynth.log[-1])
		finally:
			conf["speech"]["synthPriority"] = oldPriority
			synthHandler._externalModules.pop("good1011", None)

	def test_avisos_de_un_sintetizador_que_ya_no_es_el_actual(self) -> None:
		cur = RecordingSynth()
		synthHandler._current = cur
		mgr = speech.getManager()
		called = []
		cur.answer = False
		mgr.speak(["hola", CallbackCommand(lambda: called.append(1))])
		idx = [i for i in mgr._owners]
		old = RecordingSynth()
		for i in idx:
			base.synthIndexReached.notify(synth=old, index=i)
		self.assertEqual(called, [])
		for i in idx:
			base.synthIndexReached.notify(synth=cur, index=i)
		self.assertEqual(called, [1])


# ====================================================================== 2: el aviso de fin no adelanta enunciados
class AvisoDeFinTests(_SpeechTestCase):
	def test_el_fin_de_A_no_da_por_dicho_B(self) -> None:
		s = FakeAudioSynth()
		synthHandler._current = s
		mgr = speech.getManager()
		events: list[str] = []
		mgr.speak(["AAAA", CallbackCommand(lambda: events.append("fin A"))])
		self.assertTrue(self.idle(s))
		# A está sintetizado (y su aviso de fin, encolado) pero aún no ha sonado.
		mgr.speak([CallbackCommand(lambda: events.append("inicio B")), "BBBB", CallbackCommand(lambda: events.append("fin B"))])
		self.assertTrue(self.idle(s))
		player = s._player
		# Suena solo A (hasta su aviso de fin incluido).
		with player.lock:
			queued = list(player.items)
		cut = next(i for i, (d, _cb) in enumerate(queued) if d and d.startswith(b"BBBB"))
		with player.lock:
			firstPart = [player.items.popleft() for _ in range(cut)]
		for data, cb in firstPart:
			if cb is not None:
				cb()
		self.assertIn("fin A", events)
		self.assertNotIn("fin B", events, "el aviso de fin de A dio por dicho B antes de sonar")
		self.assertTrue(s._speaking, "la voz debe seguir «hablando» (Mayúsculas para pausar)")
		player.playAll()
		self.assertEqual(events, ["fin A", "inicio B", "fin B"])
		self.assertFalse(s._speaking)

	def test_aviso_de_fin_sigue_llegando_al_final(self) -> None:
		s = FakeAudioSynth()
		done = []
		h = lambda synth=None: done.append(synth)  # noqa: E731
		base.synthDoneSpeaking.register(h)
		try:
			s.speak(["uno"])
			self.assertTrue(self.idle(s))
			s._player.playAll()
			self.assertEqual(done, [s])
		finally:
			base.synthDoneSpeaking.unregister(h)
			s.terminate()


# ====================================================================== 3: velocidad relativa en OneCore
class OneCoreRateTests(unittest.TestCase):
	def test_porcentaje_con_signo(self) -> None:
		from tiresias.synth import onecore

		d = onecore.SynthDriver.__new__(onecore.SynthDriver)
		d._settings = {"voice": "", "pitch": 50, "rate": 50}
		d._voices = {}
		self.assertIn('rate="-20%"', d._buildSsml([RateCommand(offset=-20), "hola"]))
		self.assertIn('rate="+10%"', d._buildSsml([RateCommand(offset=10), "hola"]))
		self.assertIn('rate="-90%"', d._buildSsml([RateCommand(offset=-100), "hola"]))
		self.assertNotIn('rate="80%"', d._buildSsml([RateCommand(offset=-20), "hola"]))


# ====================================================================== 4: caracteres que no se pueden sintetizar
class TextoSaneadoTests(_SpeechTestCase):
	def test_sanitize(self) -> None:
		self.assertEqual(base.sanitizeText("a\ud83db\x00c￾d\ttab\nfin"), "a b c d\ttab\nfin")
		self.assertEqual(base.sanitizeText("emoji 😀 bien"), "emoji 😀 bien")

	def test_el_gestor_no_envia_surrogates(self) -> None:
		cur = RecordingSynth()
		RecordingSynth.log = []
		synthHandler._current = cur
		speech.getManager().speak(["hola \ud83d mundo\x00"])
		self.assertEqual(RecordingSynth.log[-1].strip(), "hola   mundo")

	def test_un_texto_imposible_no_cambia_de_sintetizador(self) -> None:
		s = FakeAudioSynth()
		failed = []
		h = lambda synth=None, error=None: failed.append(error)  # noqa: E731
		base.synthFailed.register(h)

		def bad(items, emit, isCancelled):
			"".join(i for i in items if isinstance(i, str)).encode("ascii")

		s._synthesizeSegment = bad
		try:
			for _ in range(3):
				s.speak(["añadir"])
				self.assertTrue(self.idle(s))
			self.assertEqual(failed, [])
		finally:
			base.synthFailed.unregister(h)
			s.terminate()

	def test_la_base_sanea_antes_del_controlador(self) -> None:
		s = FakeAudioSynth()
		s._processSequence(s._generation, ["x\ud800y"])
		self.assertEqual(s.segments[-1], ["x y"])
		s.terminate()

	def test_exportar_historial_con_surrogate(self) -> None:
		path = os.path.join(_TMP, "historial1011.txt")
		n = speech.exportHistory(path, [speech.HistoryEntry(time.time(), "roto \ud83d", "focus")])
		self.assertEqual(n, 1)
		self.assertTrue(os.path.getsize(path) > 0)


# ====================================================================== 5 y 10: vigilante y contrapresión
class VigilanteYContrapresionTests(_SpeechTestCase):
	def test_texto_largo_no_parece_colgado(self) -> None:
		s = FakeAudioSynth()
		s.delay = 0.04
		text = ("Una frase de un texto muy largo copiado al portapapeles. " * 6 + "\n") * 12
		s.speak([text])
		stalled = False
		start = time.monotonic()
		while time.monotonic() - start < 10 and not s._queue.empty() or s._busySince:
			stalled = stalled or s.isStalled(0.15)
			time.sleep(0.01)
			if time.monotonic() - start > 10:
				break
		self.assertGreater(len(s.segments), 5)
		self.assertFalse(stalled, "el vigilante confundía un texto largo con un cuelgue")
		s.terminate()

	def test_sintetizador_colgado_si_se_detecta(self) -> None:
		s = FakeAudioSynth()
		gate = threading.Event()
		s._synthesizeSegment = lambda items, emit, c: gate.wait(5)
		s.speak(["hola"])
		self.assertTrue(_waitFor(lambda: s.isStalled(0.2), 3))
		gate.set()
		s.terminate()

	def test_espera_al_reproductor_y_se_cancela(self) -> None:
		s = FakeAudioSynth()
		s._player.pending = base.MAX_BUFFERED_SECONDS + 5
		text = ("Frase larga de prueba para trocear en varios segmentos. " * 3 + "\n") * 4
		s.speak([text])
		time.sleep(0.3)
		self.assertEqual(s.segments, [], "con el reproductor lleno no debe seguir sintetizando")
		s._player.pending = 0
		self.assertTrue(_waitFor(lambda: len(s.segments) > 1))
		# Con el reproductor lleno otra vez, callar libera la espera.
		s._player.pending = base.MAX_BUFFERED_SECONDS + 5
		s.speak([text])
		time.sleep(0.2)
		s.cancel()
		self.assertTrue(self.idle(s))
		s.terminate()

	def test_wave_player_cuenta_lo_pendiente(self) -> None:
		p = wave_player.WavePlayer.__new__(wave_player.WavePlayer)
		p._lock = threading.RLock()
		p._items = collections.deque()
		p._pendingBytes = 0
		p._bytesPerSec = 1000 * 2
		p._generation = 0
		p._resetRequested = False
		p._paused = False
		p._pauseRequested = None
		p._event = wave_player.kernel32.CreateEventW(None, False, False, None)
		try:
			p.feed(b"\x00" * 4000)
			p.feed(None, lambda: None)
			self.assertAlmostEqual(p.queuedSeconds(), 2.0)
			p.stop()
			self.assertEqual(p.queuedSeconds(), 0)
		finally:
			wave_player.kernel32.CloseHandle(p._event)


# ====================================================================== 6: fragmento viejo tras callar
class FragmentoViejoTests(_SpeechTestCase):
	def test_trozo_de_una_generacion_anterior_no_llega(self) -> None:
		s = FakeAudioSynth()
		gen = s._generation
		s.cancel()
		self.assertFalse(s._feed(b"viejo", None, gen))
		self.assertEqual(list(s._player.items), [])
		self.assertTrue(s._feed(b"nuevo", None, s._generation))
		s.terminate()

	def test_cancel_espera_al_envio_en_curso(self) -> None:
		s = FakeAudioSynth()
		gen = s._generation
		s._feedLock.acquire()
		t = threading.Thread(target=s.cancel)
		t.start()
		time.sleep(0.05)
		self.assertEqual(s._generation, gen, "cancel no debe cambiar la generación a mitad de un envío")
		s._feedLock.release()
		t.join(2)
		self.assertEqual(s._generation, gen + 1)
		s.terminate()


# ====================================================================== 7 y 11: SAPI 5
class Sapi5Tests(unittest.TestCase):
	def test_dialecto_sin_voz_no_cambia_de_voz(self) -> None:
		from tiresias.synth import sapi5

		installed = [0x0C0A, 0x080A, 0x0409]
		self.assertIsNone(sapi5._lcidForLang("es_419", installed, "es_MX"))
		self.assertEqual(sapi5._lcidForLang("es_ES", installed, "es_MX"), 0x0C0A)
		self.assertEqual(sapi5._lcidForLang("en", installed, "es_MX"), 0x0409)
		self.assertIsNone(sapi5._lcidForLang("ru", installed, "es_MX"))

	def test_idioma_de_voces_fuera_de_la_tabla(self) -> None:
		from tiresias.synth import sapi5

		self.assertEqual(sapi5._langFromAttribute("419"), "ru_RU")
		self.assertEqual(sapi5._langFromAttribute("80A;C0A"), "es_MX")
		self.assertIsNone(sapi5._langFromAttribute(""))

	def test_callar_purga_sapi(self) -> None:
		from tiresias.synth import sapi5

		class Voice:
			def __init__(self) -> None:
				self.calls = []
				self.AudioOutputStream = None

			def Speak(self, text, flags):  # noqa: N802
				self.calls.append((text, flags))

			def WaitUntilDone(self, ms):  # noqa: N802
				return any(f & sapi5._PURGE_BEFORE_SPEAK for _t, f in self.calls)

		d = sapi5.SynthDriver.__new__(sapi5.SynthDriver)
		d._settings = {"voice": "", "rate": 50, "pitch": 50}
		d._voice = Voice()
		d._voiceDirty = False
		d._fmt = None
		self.patchStream(sapi5)
		out = []
		cancelled = [False]

		def isCancelled():
			if len(d._voice.calls) == 1:
				cancelled[0] = True
			return cancelled[0]

		d._synthesizeSegment(["hola"], out.append, isCancelled)
		self.assertTrue(d._voice.calls[0][1] & sapi5.SVSFlagsAsync)
		self.assertTrue(d._voice.calls[-1][1] & sapi5._PURGE_BEFORE_SPEAK)
		self.assertEqual(out, [])

	def patchStream(self, sapi5) -> None:
		import comtypes.client

		class Stream:
			Format = None

			def GetData(self):  # noqa: N802
				return b""

		old = comtypes.client.CreateObject
		comtypes.client.CreateObject = lambda *a, **k: Stream()
		self.addCleanup(setattr, comtypes.client, "CreateObject", old)


# ====================================================================== 9: números en Piper
class PiperNumerosTests(unittest.TestCase):
	def test_no_se_parte_por_los_separadores_de_cifras(self) -> None:
		from tiresias.synth import piper_phonemizer as pp

		parts = [p for p in pp._splitPunct.split("Cuesta 1.500 euros, o 3,14 a las 12:30.") if p]
		self.assertIn("Cuesta 1.500 euros", parts)
		self.assertTrue(any("3,14 a las 12:30" in p for p in parts))
		self.assertTrue(pp._splitPunct.fullmatch(","))
		self.assertTrue(pp._splitPunct.fullmatch("."))


# ====================================================================== 12 y 16: reproductor
class WavePlayerRobustoTests(unittest.TestCase):
	def test_ganancias_con_canales_raros(self) -> None:
		data = b"\x01\x00" * 7  # 7 muestras: tramas incompletas
		self.assertEqual(len(wave_player._applyGains(data, 2, 1.0)) % 4, 0)
		self.assertEqual(len(wave_player._applyGains(data, 3, 1.0)) % 4, 0)

	def test_el_hilo_sobrevive_a_un_error_que_no_es_de_salida(self) -> None:
		p = wave_player.WavePlayer(8000, 1, name="prueba1011", keepAwake=False)
		try:
			# Sin abrir ningún dispositivo: la escritura falla antes de la salida.
			p._writeItem = lambda item, gen: (_ for _ in ()).throw(ValueError("formato"))
			got = threading.Event()
			p.feed(b"\x00\x00" * 10, lambda: None)
			p.feed(None, got.set)
			self.assertTrue(got.wait(3))
			self.assertTrue(p._thread.is_alive())
		finally:
			p.terminate()

	def test_cambio_de_dispositivo_aunque_haya_indices_pendientes(self) -> None:
		class Fake(wave_player._Backend):
			mode = "wasapi"
			opened = 0

			def __init__(self, rate, event) -> None:
				super().__init__(rate, event)
				self.valid = True

			def open(self, deviceName) -> None:
				Fake.opened += 1
				self.deviceName = deviceName

			def close(self) -> None:
				pass

			def played(self) -> int:
				return 0

			def stillValid(self) -> bool:
				return self.valid

		p = wave_player.WavePlayer.__new__(wave_player.WavePlayer)
		p._lock = threading.RLock()
		p._backend = None
		p._backendFor = ""
		p._marks = []
		p._realEnd = 0
		p._paused = False
		p.samplesPerSec = 8000
		p._event = None
		old = (wave_player._WasapiBackend, wave_player._WaveOutBackend)
		wave_player._WasapiBackend = wave_player._WaveOutBackend = Fake
		oldMode = wave_player._outputMode
		wave_player._outputMode = lambda: "wasapi"
		try:
			first = p._openBackend()
			fired = []
			p._marks.append((10, lambda: fired.append(1)))
			first.valid = False  # cambió el predeterminado de Windows
			second = p._openBackend()
			self.assertIsNot(first, second)
			self.assertEqual(fired, [1])
		finally:
			wave_player._WasapiBackend, wave_player._WaveOutBackend = old
			wave_player._outputMode = oldMode


# ====================================================================== 13: eSpeak no se libera con el hilo ocupado
class EspeakTerminateTests(unittest.TestCase):
	def test_no_libera_la_biblioteca_con_el_hilo_dentro(self) -> None:
		from tiresias.synth import espeak

		class Dll:
			terminated = 0

			def espeak_Terminate(self):  # noqa: N802
				Dll.terminated += 1

		gate = threading.Event()
		d = espeak.SynthDriver.__new__(espeak.SynthDriver)
		d._generation = 0
		d._queue = queue.Queue()
		d._player = ManualPlayer()
		d._speaking = False
		d._workerStarted = True
		d._worker = threading.Thread(target=gate.wait, args=(5,), daemon=True)
		d._worker.start()
		d._busySince = time.monotonic() - 100
		d._cancelFlag = False
		d._dll = Dll()
		try:
			d.terminate()
			self.assertEqual(Dll.terminated, 0)
		finally:
			gate.set()


# ====================================================================== símbolos: marcas del plano 15
class SimbolosMarcasTests(unittest.TestCase):
	def test_uso_privado_del_plano_15(self) -> None:
		p = symbols.getProcessor("es") or symbols.processor
		out = p.process("a \U000F0000 b 😀", 100)
		self.assertNotIn("\U000F0000", out)
		self.assertEqual(out.count("cara"), 1 if "cara" in out else 0)


# ====================================================================== audio auxiliar
class TonosTests(unittest.TestCase):
	def test_retraso_acotado(self) -> None:
		class P:
			def __init__(self) -> None:
				self.pending = 5.0
				self.stops = 0
				self.volume = 1.0
				self.fed = 0

			def queuedSeconds(self):
				return self.pending

			def stop(self):
				self.stops += 1
				self.pending = 0

			def feed(self, data, cb=None):
				self.fed += 1

		p = P()
		old = tones._getPlayer
		tones._getPlayer = lambda: p
		oldVol = tones._soundVolume
		tones._soundVolume = lambda: 1.0
		try:
			tones.beep(440, 20)
			self.assertEqual((p.stops, p.fed), (1, 1))
			tones.beep(440, 20)
			self.assertEqual((p.stops, p.fed), (1, 2))
			tones.beep(float("nan"), 20)
			tones.beep(440, float("inf"))
			self.assertEqual(p.fed, 2)
		finally:
			tones._getPlayer = old
			tones._soundVolume = oldVol

	def test_notas_largas_fuera_de_la_cache(self) -> None:
		tones._genNoteCached.cache_clear()
		tones._genNote(440.0, 2000, 50, 50)
		self.assertEqual(tones._genNoteCached.cache_info().currsize, 0)
		tones._genNote(440.0, 50, 50, 50)
		self.assertEqual(tones._genNoteCached.cache_info().currsize, 1)
		self.assertEqual(tones._silence(-5), b"")

	def test_wav_de_tres_canales_rechazado(self) -> None:
		path = os.path.join(_TMP, "tres1011.wav")
		with wave.open(path, "wb") as w:
			w.setnchannels(3)
			w.setsampwidth(2)
			w.setframerate(8000)
			w.writeframes(b"\x00\x00" * 9)
		with self.assertRaises(ValueError):
			tones._loadWav(path, os.path.getmtime(path))

	def test_timestretch_factores_extremos(self) -> None:
		pcm = b"\x10\x00" * 4000
		for f in (0, -1, float("nan"), float("inf"), 1e6):
			self.assertEqual(timestretch.stretch(pcm, 8000, f), pcm)


class CadenasCoreAudioTests(unittest.TestCase):
	def test_take_string_libera(self) -> None:
		ole32 = ctypes.WinDLL("ole32")
		ole32.CoTaskMemAlloc.restype = ctypes.c_void_p
		ole32.CoTaskMemAlloc.argtypes = [ctypes.c_size_t]
		text = "Altavoces (prueba)"
		size = (len(text) + 1) * 2
		ptr = ole32.CoTaskMemAlloc(size)
		ctypes.memmove(ptr, ctypes.create_unicode_buffer(text), size)
		self.assertEqual(core_audio.takeString(ptr), text)
		self.assertEqual(core_audio.takeString(None), "")


# ---------------------------------------------------------------- sesiones de audio falsas
class _Store:
	"""Volúmenes que «recuerda Windows» por aplicación (identificador estable)."""

	def __init__(self) -> None:
		self.volume: dict[str, float] = {}
		self.channels: dict[str, list[float]] = {}


class FakeSession:
	def __init__(self, store: _Store, app: str, pid: int, channels: int = 2, state: int = 1) -> None:
		self.store = store
		self.pid = pid
		self.sessionIdentifier = "{dev}|\\Device\\" + app + "%b{0}"
		self.identifier = self.sessionIdentifier + "|1%b" + str(pid)
		self.deviceId = "dev"
		self._state = state
		store.volume.setdefault(self.sessionIdentifier, 1.0)
		store.channels.setdefault(self.sessionIdentifier, [1.0] * channels)
		outer = self

		class SV:
			def GetMasterVolume(self):  # noqa: N802
				return store.volume[outer.sessionIdentifier]

			def SetMasterVolume(self, v, ctx):  # noqa: N802
				store.volume[outer.sessionIdentifier] = float(v)

		class CV:
			def GetChannelCount(self):  # noqa: N802
				return len(store.channels[outer.sessionIdentifier])

			def GetChannelVolume(self, ch):  # noqa: N802
				return store.channels[outer.sessionIdentifier][ch]

			def SetChannelVolume(self, ch, v, ctx):  # noqa: N802
				store.channels[outer.sessionIdentifier][ch] = float(v)

		self._sv, self._cv = SV(), CV()

	def simpleVolume(self):
		return self._sv

	def channelVolume(self):
		return self._cv

	def state(self) -> int:
		return self._state

	def isSystemSounds(self) -> bool:
		return False


class _SessionsTestCase(unittest.TestCase):
	def setUp(self) -> None:
		self.store = _Store()
		self.sessions: list[FakeSession] = []
		self.names: dict[int, str] = {}
		self._patched = []
		self.patch(core_audio, "getSessions", lambda allDevices=False: list(self.sessions))
		self.patch(core_audio, "runInSessionThread", lambda func, *args: func(*args))
		self.patch(core_audio, "waitSessionThread", lambda timeout=3.0: True)
		self.patch(ducking, "_processName", lambda pid: self.names.get(pid, "app.exe"))
		self.patch(queue_handler, "callLater", lambda *a, **k: None)
		self.patch(queue_handler, "cancelCallLater", lambda *a, **k: None)
		self.standby = False
		self.patch(synthHandler, "isStandby", lambda: self.standby)
		self._mode = conf["audio"]["duckingMode"]
		self._level = conf["audio"]["duckingLevel"]
		conf["audio"]["duckingMode"] = "always"
		conf["audio"]["duckingLevel"] = 25
		ducking._saved.clear()
		ducking._duckedInstances.clear()
		ducking._pendingRestore.clear()
		ducking._ducked = False
		ducking._duckJobQueued = False
		ducking._removeStateFile()

	def patch(self, obj, name, value) -> None:
		self._patched.append((obj, name, getattr(obj, name)))
		setattr(obj, name, value)

	def tearDown(self) -> None:
		ducking._ducked = False
		ducking._rescanTimer = None
		ducking._unduckTimer = None
		ducking._saved.clear()
		ducking._duckedInstances.clear()
		ducking._pendingRestore.clear()
		ducking._removeStateFile()
		for obj, name, value in reversed(self._patched):
			setattr(obj, name, value)
		conf["audio"]["duckingMode"] = self._mode
		conf["audio"]["duckingLevel"] = self._level

	def open(self, app: str, pid: int, **kw) -> FakeSession:
		s = FakeSession(self.store, app, pid, **kw)
		self.sessions.append(s)
		return s


class AtenuacionTests(_SessionsTestCase):
	def test_no_se_acumula_al_cerrar_y_abrir_la_aplicacion(self) -> None:
		for cycle in range(4):
			s = self.open("musica.exe", 1000 + cycle)
			ducking.duck()
			self.assertAlmostEqual(self.store.volume[s.sessionIdentifier], 0.25, places=3)
			self.sessions.remove(s)  # se cierra atenuada
			ducking.unduck()
		s = self.open("musica.exe", 2000)
		ducking.duck()
		ducking.unduck()
		self.assertAlmostEqual(self.store.volume[s.sessionIdentifier], 1.0, places=3)

	def test_restauracion_tras_cierre_inesperado(self) -> None:
		s = self.open("musica.exe", 10)
		ducking.duck()
		self.assertTrue(os.path.exists(ducking._stateFile()))
		# Tiresias muere: se pierde la memoria, queda el archivo y la app se reinicia.
		ducking._saved.clear()
		ducking._duckedInstances.clear()
		ducking._ducked = False
		self.sessions.remove(s)
		s2 = self.open("musica.exe", 11)
		ducking._restoreFromCrashJob()
		self.assertAlmostEqual(self.store.volume[s2.sessionIdentifier], 1.0, places=3)

	def test_aplicacion_cerrada_al_arrancar_se_restaura_al_volver(self) -> None:
		key = "{dev}|\\Device\\musica.exe%b{0}"
		self.store.volume[key] = 0.25
		with open(ducking._stateFile(), "w", encoding="utf-8") as f:
			json.dump({key + "|1%b55": 1.0}, f)  # archivo antiguo (por instancia)
		ducking._restoreFromCrashJob()
		self.assertIn(key, ducking._pendingRestore)
		conf["audio"]["duckingMode"] = "off"
		self.open("musica.exe", 77)
		ducking.duck()
		ducking.unduck()
		self.assertAlmostEqual(self.store.volume[key], 1.0, places=3)

	def test_lectores_de_pantalla_e_inactivas_no_se_atenuan(self) -> None:
		nvda = self.open("nvda.exe", 50)
		self.names[50] = "nvda.exe"
		quiet = self.open("silencio.exe", 51, state=0)
		ducking.duck()
		self.assertEqual(self.store.volume[nvda.sessionIdentifier], 1.0)
		self.assertEqual(self.store.volume[quiet.sessionIdentifier], 1.0)
		ducking.unduck()

	def test_en_espera_no_se_atenua(self) -> None:
		s = self.open("musica.exe", 60)
		self.standby = True
		ducking.duck()
		self.assertFalse(ducking.isDucked())
		self.assertEqual(self.store.volume[s.sessionIdentifier], 1.0)

	def test_se_respeta_el_volumen_que_cambia_el_usuario(self) -> None:
		s = self.open("musica.exe", 70)
		ducking.duck()
		self.store.volume[s.sessionIdentifier] = 0.6  # el usuario lo cambia
		ducking.unduck()
		self.assertAlmostEqual(self.store.volume[s.sessionIdentifier], 0.6, places=3)

	def test_escritura_atomica(self) -> None:
		self.open("musica.exe", 80)
		ducking.duck()
		self.assertFalse(os.path.exists(ducking._stateFile() + ".tmp"))
		with open(ducking._stateFile(), encoding="utf-8") as f:
			self.assertEqual(list(json.load(f).values()), [1.0])
		ducking.unduck()
		self.assertFalse(os.path.exists(ducking._stateFile()))


class DivisionSonidoTests(_SessionsTestCase):
	def setUp(self) -> None:
		super().setUp()
		self._split = (conf["audio"]["soundSplitMode"], conf["audio"]["soundSplitApplyToOtherApps"])
		conf["audio"]["soundSplitApplyToOtherApps"] = True
		sound_split._touched.clear()
		sound_split._applyQueued = False
		try:
			os.remove(sound_split._stateFile())
		except OSError:
			pass

	def tearDown(self) -> None:
		conf["audio"]["soundSplitMode"], conf["audio"]["soundSplitApplyToOtherApps"] = self._split
		sound_split._touched.clear()
		sound_split._timer = None
		sound_split._appliedApps = False
		wave_player.OutputSettings.channelGains = (1.0, 1.0)
		try:
			os.remove(sound_split._stateFile())
		except OSError:
			pass
		super().tearDown()

	def test_mono_y_51_no_se_tocan_y_se_restaura_el_estereo(self) -> None:
		stereo = self.open("musica.exe", 1)
		mono = self.open("mono.exe", 2, channels=1)
		surround = self.open("peli.exe", 3, channels=6)
		sound_split.apply("leftRight")
		self.assertEqual(self.store.channels[stereo.sessionIdentifier], [0.0, 1.0])
		self.assertEqual(self.store.channels[mono.sessionIdentifier], [1.0])
		self.assertEqual(self.store.channels[surround.sessionIdentifier], [1.0] * 6)
		self.assertTrue(os.path.exists(sound_split._stateFile()))
		sound_split.apply("off")
		self.assertEqual(self.store.channels[stereo.sessionIdentifier], [1.0, 1.0])
		self.assertFalse(os.path.exists(sound_split._stateFile()))

	def test_aplicacion_cerrada_dividida_se_centra_al_volver(self) -> None:
		s = self.open("musica.exe", 1)
		sound_split.apply("leftRight")
		self.sessions.remove(s)
		sound_split._touched.clear()  # nueva ejecución de Tiresias: solo queda el archivo
		sound_split.apply("off")
		s2 = self.open("musica.exe", 9)
		sound_split.apply("off")
		self.assertEqual(self.store.channels[s2.sessionIdentifier], [1.0, 1.0])

	def test_ni_otros_lectores_ni_en_espera(self) -> None:
		nvda = self.open("nvda.exe", 5)
		self.names[5] = "nvda.exe"
		app = self.open("musica.exe", 6)
		sound_split.apply("leftRight")
		self.assertEqual(self.store.channels[nvda.sessionIdentifier], [1.0, 1.0])
		self.assertEqual(self.store.channels[app.sessionIdentifier], [0.0, 1.0])
		self.standby = True
		sound_split.apply("leftRight")
		self.assertEqual(self.store.channels[app.sessionIdentifier], [1.0, 1.0])


# ====================================================================== Eloquence
def _eloquence():
	if ELOQ_PKG not in sys.modules:
		pkg = types.ModuleType(ELOQ_PKG)
		pkg.__path__ = [SYNTH_DIR]
		sys.modules[ELOQ_PKG] = pkg
	return importlib.import_module(f"{ELOQ_PKG}.ibmtts")


@unittest.skipUnless(HAS_ELOQUENCE, NO_ELOQUENCE)
class EloquenceTextoTests(unittest.TestCase):
	def setUp(self) -> None:
		self.mod = _eloquence()

	def driver(self, voice: str):
		d = self.mod.SynthDriver.__new__(self.mod.SynthDriver)
		d._settings = {"voice": voice, "pauseMode": "0", "rate": 40, "pitch": 65}
		d._voices = {}
		return d

	def test_nul_y_surrogates_no_rompen(self) -> None:
		self.assertEqual(self.mod.toCp1252("a\x00b\ud83dc"), b"a b c")

	def test_correcciones_anticuelgue_por_idioma_vigente(self) -> None:
		en = str(self.mod.LANGUAGES["enu"][0])
		es = str(self.mod.LANGUAGES["esp"][0])
		self.assertIn(b"seizur", self.driver(en)._processText("caesure"))
		self.assertIn(b"dane `0 ben", self.driver(str(self.mod.LANGUAGES["deu"][0]))._processText("dane-ben"))
		# Voz española con un tramo en inglés: también se corrige.
		d = self.driver(es)
		d._voices = {es: types.SimpleNamespace(language="es_ES")}
		data = d._buildInput(["hola", LangChangeCommand("en"), "caesure"])
		self.assertIn(b"seizur", data)

	def test_japones_no_son_interrogaciones(self) -> None:
		jp = str(self.mod.LANGUAGES["jpn"][0])
		data = self.driver(jp)._processText("こんにちは")
		self.assertNotIn(b"?", data)
		self.assertEqual(data.decode("cp932"), "こんにちは")

	def test_trozos_de_texto_y_pausas(self) -> None:
		parts = self.mod._splitBytes(b"ab " * 30000, self.mod.MAX_ADD_TEXT)
		self.assertTrue(all(len(p) <= self.mod.MAX_ADD_TEXT for p in parts))
		self.assertEqual(b"".join(parts), b"ab " * 30000)
		d = self.driver("131072")
		normal = d._breakAnnotation(100)
		d._settings["rateBoost"] = True
		self.assertNotEqual(normal, d._breakAnnotation(100))

	def test_plazos_por_debajo_del_vigilante(self) -> None:
		self.assertLess(self.mod.SEGMENT_TIMEOUT, synthHandler.STALL_TIMEOUT)
		self.assertLess(self.mod.INACTIVITY_TIMEOUT, self.mod.SEGMENT_TIMEOUT)

	def test_version_subida(self) -> None:
		with open(os.path.join(ROOT, "data", "addons", "eloquence", "manifest.json"), encoding="utf-8") as f:
			self.assertEqual(json.load(f)["version"], "1.0.3")


if __name__ == "__main__":
	unittest.main()
