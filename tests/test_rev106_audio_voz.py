"""Pruebas de regresión de la revisión 1.0.6: audio, sintetizadores, exportación y Eloquence.

Ninguna prueba reproduce sonido: los reproductores usan salidas simuladas y
Eloquence (si está instalado) sintetiza a memoria, sin pasar por la tarjeta.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import array
import ctypes
import importlib
import inspect
import math
import os
import queue
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
from collections import OrderedDict
from ctypes import wintypes
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
	sys.path.insert(0, SRC)

from tiresias import paths  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="tiresias_test_rev106_audio_")
if not os.path.isdir(os.path.join(_TMP, "symbols")):
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
paths.setDataDir(_TMP)
paths.ensureDataDirs()

from tiresias.config import conf  # noqa: E402

import tiresias.audio  # noqa: E402,F401  (valores por defecto de audio)
from tiresias import queue_handler, speech  # noqa: E402
from tiresias.audio import core_audio, ducking, mixer, sound_split, tones, wave_player  # noqa: E402
from tiresias.speech.commands import BreakCommand, LangChangeCommand, PitchCommand, VolumeCommand  # noqa: E402
from tiresias.synth import base as synthBase  # noqa: E402

SYNTH_DIR = os.path.join(ROOT, "data", "addons", "eloquence", "synthDrivers")
HOST_DLL = os.path.join(SYNTH_DIR, "eci", "ibmtts_host32.dll")
ECI_DLL = os.path.join(SYNTH_DIR, "eci", "ECI.DLL")
RUNDLL32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "SysWOW64", "rundll32.exe")
#: Eloquence es propietario: no está en el repositorio público (se distribuye
#: aparte en la tienda). Sin él, sus pruebas se saltan.
HAS_ELOQUENCE = os.path.isfile(os.path.join(SYNTH_DIR, "ibmtts.py"))
NO_ELOQUENCE = "Falta el complemento Eloquence (data/addons/eloquence): no se incluye en el repositorio"
REAL_BRIDGE = HAS_ELOQUENCE and os.path.isfile(HOST_DLL) and os.path.isfile(ECI_DLL) and os.path.isfile(RUNDLL32)
PKG = "tiresias_test_rev106_eloquence"


def _eloquence():
	if PKG not in sys.modules:
		pkg = types.ModuleType(PKG)
		pkg.__path__ = [SYNTH_DIR]
		sys.modules[PKG] = pkg
	return importlib.import_module(f"{PKG}.ibmtts")


ibm = _eloquence() if HAS_ELOQUENCE else None
bridge = ibm.bridge if ibm is not None else None


class _ConfPatch:
	"""Cambia valores de ``conf["audio"]`` y los restaura al terminar."""

	def setConf(self, **values) -> None:
		if not hasattr(self, "_confSaved"):
			self._confSaved = {}
		for k, v in values.items():
			self._confSaved.setdefault(k, conf["audio"][k])
			conf["audio"][k] = v

	def restoreConf(self) -> None:
		for k, v in getattr(self, "_confSaved", {}).items():
			conf["audio"][k] = v
		self._confSaved = {}


# ====================================================================== sintetizador de audio de prueba
class _FakePlayer:
	def __init__(self) -> None:
		self.fed: list = []
		self.volume = 1.0
		self.muted = False
		self.playing = False
		self.terminated = False

	def feed(self, data, onDone=None) -> None:
		self.fed.append(data)
		if onDone is not None:
			onDone()

	def stop(self) -> None:
		pass

	def terminate(self) -> None:
		self.terminated = True

	def pause(self, switch) -> None:
		pass

	def isPlaying(self) -> bool:
		return self.playing


def _makeSynth(segment):
	class Fake(synthBase.AudioSynthDriver):
		name = "falsoAudioVoz"

		def __init__(self) -> None:  # sin WavePlayer real
			self._settings = {}
			self._generation = 0
			self._queue = queue.Queue()
			self._player = _FakePlayer()
			self._speaking = False
			self._worker = threading.Thread(target=self._run, name="Synth-falsoAudioVoz", daemon=True)
			self._workerStarted = False
			self._errorCount = 0
			self._busySince = 0.0
			self._failed = False
			self.sampleRate = 8000
			self.done = 0
			self.segments: list[list] = []

		def _synthesizeSegment(self, items, emit, isCancelled) -> None:
			self.segments.append(list(items))
			segment(self, items, emit, isCancelled)

		def _notifyDone(self) -> None:
			self.done += 1

		def _notifyIndex(self, index) -> None:
			pass

	return Fake()


def _waitFor(cond, timeout: float = 5.0) -> bool:
	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		if cond():
			return True
		time.sleep(0.01)
	return cond()


# ====================================================================== 1 y 11: exportación (ya resueltos)
class ExportYaResueltoTests(unittest.TestCase):
	def test_1_cancel_conserva_los_trabajos_de_exportacion(self) -> None:
		s = _makeSynth(lambda *a: None)
		job = threading.Event()
		s._queue.put((0, ["voz"]))
		s._queue.put(job.set)
		s.cancel()
		self.assertEqual(list(s._queue.queue), [job.set])
		s._ensureWorker()
		self.assertTrue(job.wait(5))
		s.terminate()

	def test_11_aviso_de_fin_con_una_exportacion_en_cola(self) -> None:
		gate = threading.Event()
		s = _makeSynth(lambda self, items, emit, c: emit(b"\x00\x00"))
		s._queue.put((0, ["hola"]))
		s._queue.put(gate.wait)
		s._ensureWorker()
		self.assertTrue(_waitFor(lambda: s.done == 1))
		gate.set()
		s.terminate()


# ====================================================================== 14: pausas en textos largos
class TrozosLargosTests(unittest.TestCase):
	def test_14_la_pausa_no_se_repite_y_el_estado_si(self) -> None:
		s = _makeSynth(lambda *a: None)
		text = ("Esta es una frase de prueba bastante larga para que se divida. " * 12).strip()
		pitch = PitchCommand(offset=10)
		s._processSequence(0, [BreakCommand(300), pitch, text])
		self.assertGreater(len(s.segments), 1)
		breaks = [i for seg in s.segments for i in seg if isinstance(i, BreakCommand)]
		self.assertEqual(len(breaks), 1)
		for seg in s.segments:
			self.assertIn(pitch, seg)

	def test_14_sin_variable_muerta(self) -> None:
		self.assertNotIn("persistent", inspect.getsource(synthBase.AudioSynthDriver._processSequence))


# ====================================================================== 2 y 3: reproductor
class _Backend(wave_player._Backend):
	opened: list = []

	def __init__(self, rate: int, event: int) -> None:
		super().__init__(rate, event)
		self.closed = False

	def open(self, deviceName: str) -> None:
		type(self).opened.append(self.mode)
		self.deviceName = deviceName

	def write(self, data: bytes) -> int:
		return 0

	def played(self) -> int:
		return 0

	def reset(self) -> None:
		pass

	def pause(self, switch: bool) -> None:
		pass

	def close(self) -> None:
		self.closed = True


class _BrokenWasapi(_Backend):
	mode = "wasapi"

	def open(self, deviceName: str) -> None:
		type(self).opened.append("wasapi-fallo")
		raise OSError("sin WASAPI")


class _WaveOut(_Backend):
	mode = "waveOut"


class _Wasapi(_Backend):
	mode = "wasapi"


class WavePlayerTests(_ConfPatch, unittest.TestCase):
	def setUp(self) -> None:
		_Backend.opened = []
		self.player = wave_player.WavePlayer(22050, 1, name="prueba-rev106", keepAwake=False)
		self._device = wave_player.OutputSettings.deviceName

	def tearDown(self) -> None:
		self.player.terminate()
		wave_player.OutputSettings.deviceName = self._device
		self.restoreConf()

	def test_2_la_salida_de_reserva_no_se_reabre_en_cada_bloque(self) -> None:
		self.setConf(outputMode="wasapi")
		with mock.patch.object(wave_player, "_WasapiBackend", _BrokenWasapi), mock.patch.object(wave_player, "_WaveOutBackend", _WaveOut):
			b1 = self.player._openBackend()
			b2 = self.player._openBackend()
			b3 = self.player._openBackend()
			self.assertIs(b1, b2)
			self.assertIs(b2, b3)
			self.assertEqual(b1.mode, "waveOut")
			self.assertEqual(_Backend.opened, ["wasapi-fallo", "waveOut"])
			# Si cambia la configuración, sí se reabre (y se vuelve a probar el modo pedido).
			self.setConf(outputMode="waveOut")
			b4 = self.player._openBackend()
			self.assertIsNot(b4, b1)
			self.assertTrue(b1.closed)
		with mock.patch.object(wave_player, "_WasapiBackend", _Wasapi), mock.patch.object(wave_player, "_WaveOutBackend", _WaveOut):
			# Tras el cierre por inactividad se reintenta el modo preferido.
			self.setConf(outputMode="wasapi")
			self.player._closeBackend()
			self.assertEqual(self.player._openBackend().mode, "wasapi")

	def test_3_cambio_de_dispositivo_ejecuta_las_marcas(self) -> None:
		self.setConf(outputMode="wasapi")
		called: list[str] = []
		with mock.patch.object(wave_player, "_WasapiBackend", _Wasapi), mock.patch.object(wave_player, "_WaveOutBackend", _WaveOut):
			self.player._openBackend()
			with self.player._lock:
				self.player._marks.append((10_000, lambda: called.append("índice")))
			wave_player.OutputSettings.deviceName = "Auriculares Bluetooth"
			self.player._openBackend()
		self.assertEqual(called, ["índice"])
		self.assertEqual(self.player._marks, [])

	def test_3_error_de_audio_ejecuta_las_marcas(self) -> None:
		called: list[str] = []
		self.player._backend = _Wasapi(22050, self.player._event)
		with self.player._lock:
			self.player._marks.append((10_000, lambda: called.append("índice")))
		self.player._closeBackend(fireMarks=True)
		self.assertEqual(called, ["índice"])

	def test_3_stop_descarta_las_marcas(self) -> None:
		called: list[str] = []
		self.player._backend = _Wasapi(22050, self.player._event)
		self.player.pause(True)
		with self.player._lock:
			self.player._marks.append((10_000, lambda: called.append("índice")))
		self.player.stop()
		self.assertTrue(_waitFor(lambda: not self.player._marks))
		time.sleep(0.05)
		self.assertEqual(called, [])

	def test_codigo_muerto_quitado(self) -> None:
		self.assertFalse(hasattr(wave_player.WavePlayer, "sync"))
		self.assertNotIn("asynchronous", inspect.signature(tones.playWaveFile).parameters)
		from tiresias.synth import espeak, sapi5

		self.assertFalse(hasattr(espeak, "espeakENDPAUSE"))
		self.assertFalse(hasattr(sapi5, "SVSFPurgeBeforeSpeak"))


# ====================================================================== sesiones simuladas
class _Vol:
	def __init__(self, level: float = 1.0, mute: bool = False) -> None:
		self.level = level
		self.mute = mute

	def GetMasterVolume(self):
		return self.level

	def SetMasterVolume(self, v, ctx):
		self.level = v

	def GetMute(self):
		return self.mute

	def SetMute(self, m, ctx):
		self.mute = bool(m)


class _Channels:
	def __init__(self) -> None:
		self.levels = [1.0, 1.0]
		self.sets = 0

	def GetChannelCount(self):
		return 2

	def GetChannelVolume(self, ch):
		return self.levels[ch]

	def SetChannelVolume(self, ch, level, ctx):
		self.levels[ch] = level
		self.sets += 1


class _Session:
	def __init__(self, pid: int, ident: str, level: float = 1.0) -> None:
		self.pid = pid
		self.identifier = ident
		self.vol = _Vol(level)
		self.channels = _Channels()

	def simpleVolume(self):
		return self.vol

	def channelVolume(self):
		return self.channels

	def displayName(self) -> str:
		return ""

	def state(self) -> int:
		return 1


class _SessionsCase(_ConfPatch, unittest.TestCase):
	def setUp(self) -> None:
		self.sessions = [_Session(1111, "app"), _Session(core_audio.OWN_PID, "own")]
		self.threads: set[str] = set()

		def getSessions(allDevices=False):
			self.threads.add(threading.current_thread().name)
			return list(self.sessions)

		self.patches = [
			mock.patch.object(core_audio, "getSessions", side_effect=getSessions),
			mock.patch.object(queue_handler, "callLater", return_value=1),
			mock.patch.object(queue_handler, "cancelCallLater"),
			mock.patch.object(ducking, "_processName", return_value="app.exe"),
		]
		for p in self.patches:
			p.start()
		self.setConf(duckingLevel=50, duckingMode="speaking")

	def tearDown(self) -> None:
		ducking.unduck()
		core_audio.waitSessionThread()
		sound_split._appliedApps = False
		for p in self.patches:
			p.stop()
		self.restoreConf()


# ====================================================================== 4, 12, 13 y 17: atenuación
class DuckingTests(_SessionsCase):
	def test_17_las_sesiones_se_recorren_fuera_del_nucleo(self) -> None:
		ducking.duck()
		self.assertTrue(core_audio.waitSessionThread())
		self.assertAlmostEqual(self.sessions[0].vol.level, 0.5)
		self.assertEqual(self.threads, {"SesionesAudio"})
		ducking.unduck()
		core_audio.waitSessionThread()
		self.assertAlmostEqual(self.sessions[0].vol.level, 1.0)

	def test_4_callar_la_voz_quita_la_atenuacion(self) -> None:
		with mock.patch.object(speech.pre_speechCanceled, "_handlers", []):
			with mock.patch.object(ducking, "restoreFromCrash"), mock.patch.object(ducking, "apply"):
				ducking.initialize()
			self.assertIn(ducking._onSpeechCanceled, speech.pre_speechCanceled.handlers())
			ducking.terminate()
		ducking.duck()
		core_audio.waitSessionThread()
		scheduled: list = []
		queue_handler.callLater.side_effect = lambda ms, func, *a: scheduled.append(func) or 7
		with mock.patch.object(queue_handler, "queueFunction", side_effect=lambda f, *a, **k: f(*a, **k)), mock.patch.object(ducking, "_isSpeaking", return_value=False):
			ducking._onSpeechCanceled()
			self.assertTrue(scheduled)
			scheduled[-1]()
		core_audio.waitSessionThread()
		self.assertFalse(ducking.isDucked())
		self.assertAlmostEqual(self.sessions[0].vol.level, 1.0)

	def test_4_no_se_quita_si_ya_habla_otra_vez(self) -> None:
		ducking.duck()
		scheduled: list = []
		queue_handler.callLater.side_effect = lambda ms, func, *a: scheduled.append(func) or 7
		ducking._scheduleUnduck(400)
		with mock.patch.object(ducking, "_isSpeaking", return_value=True):
			scheduled[-1]()
		self.assertTrue(ducking.isDucked())

	def test_12_sonidos_desactivados_no_atenuan(self) -> None:
		self.setConf(duckForSounds=True, playSounds=False)
		with mock.patch.object(queue_handler, "queueFunction") as qf:
			ducking._onSound(name="error")
			qf.assert_not_called()
			self.setConf(playSounds=True, soundVolumeFollowsVoice=False, soundVolume=0)
			ducking._onSound(name="error")
			qf.assert_not_called()
			self.setConf(soundVolume=50)
			ducking._onSound(name="error")
			qf.assert_called_once()

	def test_13_volumen_de_atenuacion_se_aplica_al_guardar(self) -> None:
		self.setConf(duckingMode="always")
		ducking.apply()
		core_audio.waitSessionThread()
		self.assertAlmostEqual(self.sessions[0].vol.level, 0.5)
		self.setConf(duckingLevel=20)
		ducking.apply()
		core_audio.waitSessionThread()
		self.assertAlmostEqual(self.sessions[0].vol.level, 0.2)
		self.setConf(duckingMode="off")
		ducking.apply()
		core_audio.waitSessionThread()
		self.assertAlmostEqual(self.sessions[0].vol.level, 1.0)

	def test_13_guardar_las_opciones_vuelve_a_aplicar(self) -> None:
		from tiresias.gui import settings as guiSettings

		for key in ("duckingLevel", "soundSplitApplyToOtherApps"):
			with mock.patch.object(guiSettings.queue_handler, "queueFunction") as qf:
				guiSettings.AudioPanel.afterSave(None, {("audio", key): (1, 2)})
				qf.assert_called_once_with(guiSettings._applyAudioModes)


# ====================================================================== 8: mezclador y atenuación
class MixerDuckingTests(_SessionsCase):
	def test_8_cambiar_volumen_durante_la_atenuacion(self) -> None:
		self.setConf(mixerVolumeStep=10)
		ducking.duck()
		core_audio.waitSessionThread()
		app = mixer.App("app.exe", "App")
		app.sessions = [self.sessions[0]]
		app.pids = {1111}
		self.assertEqual(app.volume(), 100)  # el volumen real, no el atenuado
		self.assertEqual(mixer.changeAppVolume(app, -1), 90)
		self.assertAlmostEqual(self.sessions[0].vol.level, 0.45)
		ducking.unduck()
		core_audio.waitSessionThread()
		self.assertAlmostEqual(self.sessions[0].vol.level, 0.9)


# ====================================================================== 18 y 13: división del sonido
class SoundSplitTests(_SessionsCase):
	def test_18_desactivada_no_toca_el_balance_ajeno(self) -> None:
		self.setConf(soundSplitApplyToOtherApps=True)
		self.sessions[0].channels.levels = [0.3, 1.0]  # balance que puso el usuario
		sound_split._appliedApps = False
		sound_split.apply("off")
		core_audio.waitSessionThread()
		self.assertEqual(self.sessions[0].channels.levels, [0.3, 1.0])
		sound_split.apply("leftRight")
		core_audio.waitSessionThread()
		self.assertEqual(self.sessions[0].channels.levels, [0.0, 1.0])
		self.assertEqual(self.threads, {"SesionesAudio"})
		sound_split.apply("off")
		core_audio.waitSessionThread()
		self.assertEqual(self.sessions[0].channels.levels, [1.0, 1.0])
		self.sessions[0].channels.levels = [0.3, 1.0]
		sound_split.apply("off")
		core_audio.waitSessionThread()
		self.assertEqual(self.sessions[0].channels.levels, [0.3, 1.0])

	def test_13_aplicar_a_las_demas_aplicaciones_al_guardar(self) -> None:
		self.setConf(soundSplitApplyToOtherApps=False, soundSplitMode="leftRight")
		sound_split.apply()
		core_audio.waitSessionThread()
		self.assertEqual(self.sessions[0].channels.levels, [1.0, 1.0])
		self.setConf(soundSplitApplyToOtherApps=True)
		sound_split.apply()
		core_audio.waitSessionThread()
		self.assertEqual(self.sessions[0].channels.levels, [0.0, 1.0])
		self.setConf(soundSplitApplyToOtherApps=False)
		sound_split.apply()
		core_audio.waitSessionThread()
		self.assertEqual(self.sessions[0].channels.levels, [1.0, 1.0])
		self.setConf(soundSplitMode="off")
		sound_split.apply()


# ====================================================================== 9: sesión propia al abrir el primer flujo
class SesionPropiaTests(_SessionsCase):
	def test_9_quitar_el_silencio_al_abrir_el_primer_flujo(self) -> None:
		self.setConf(unmuteOnStartup=True)
		own = self.sessions[1]
		own.vol.mute = True
		own.vol.level = 0.0
		self.sessions = [self.sessions[0]]  # al arrancar aún no existe
		with mock.patch.object(wave_player, "_streamOpened", False), mock.patch.object(wave_player, "_streamOpenedHandlers", []):
			from tiresias.audio import manager

			with mock.patch.object(core_audio, "endpointVolume", side_effect=OSError("sin dispositivo")):
				manager.initializeEarly()
			self.assertTrue(own.vol.mute)
			self.sessions.append(own)  # Windows la crea al abrir el flujo
			wave_player._notifyStreamOpened()
			core_audio.waitSessionThread()
			self.assertFalse(own.vol.mute)
			self.assertAlmostEqual(own.vol.level, 1.0)
			# Solo la primera vez.
			own.vol.mute = True
			wave_player._notifyStreamOpened()
			core_audio.waitSessionThread()
			self.assertTrue(own.vol.mute)


# ====================================================================== Eloquence sin puente real
class _FakeClient:
	def __init__(self, fail: set | None = None, onFail=None) -> None:
		self.calls: list[tuple] = []
		self.fail = fail or set()
		self.onFail = onFail
		self.pipeName = "falsa"
		self.connected = True
		#: Si no es None, el «motor» termina en cuanto se le pide sintetizar.
		self.driver = None

	def call(self, funcId, *args, timeout=None):
		self.calls.append((funcId, args, threading.current_thread().name))
		if funcId in self.fail:
			if self.onFail:
				self.onFail()
			raise bridge.BridgeError("puente caído")
		if funcId == bridge.ECI_SYNTHESIZE and self.driver is not None:
			self.driver._done.set()
		return 1

	def close(self) -> None:
		pass

	def ids(self) -> list[int]:
		return [c[0] for c in self.calls]


class _FakeHost:
	pipeName = "falsa"
	pid = 1

	def isRunning(self) -> bool:
		return True

	def stop(self) -> None:
		pass


def _fakeEloquence(client=None):
	"""Controlador de Eloquence sin puente ni reproductor reales."""
	d = ibm.SynthDriver.__new__(ibm.SynthDriver)
	synthBase.SynthDriver.__init__(d)
	d._voices = OrderedDict(
		(str(code), synthBase.VoiceInfo(str(code), label, lang))
		for code, label, lang in (ibm.LANGUAGES["esp"], ibm.LANGUAGES["enu"])
	)
	d._settings["voice"] = str(ibm.LANGUAGES["esp"][0])
	d._settings["variant"] = "1"
	d._requested = {"voice": d._settings["voice"], "variant": "1", "sampleRate": "1"}
	d._dirty = set()
	d._dirtyLock = threading.Lock()
	d._variantDefaults = {"2": {"pitch": 81, "inflection": 32, "headSize": 50, "roughness": 0, "breathiness": 40}}
	d._dormant = False
	d._client = client or _FakeClient()
	d._host = _FakeHost()
	d._handle = 1
	d._done = threading.Event()
	d._emit = None
	d._cancelled = False
	d._stopRequested = False
	d._engineLock = threading.RLock()
	d._player = _FakePlayer()
	d.sampleRate = 11025
	d._failed = False
	d._generation = 0
	d.cancel = mock.Mock()
	if client is None:
		d._client.driver = d
	return d


@unittest.skipUnless(HAS_ELOQUENCE, NO_ELOQUENCE)
class EloquenceTests(unittest.TestCase):
	def test_5_mismo_valor_no_hace_nada_ni_corta_la_voz(self) -> None:
		d = _fakeEloquence()
		d.loadSettings({"voice": d._settings["voice"], "variant": "1", "sampleRate": "1", "pitch": 65})
		d.cancel.assert_not_called()
		self.assertEqual(d._dirty, {"pitch"})
		self.assertEqual(d._client.calls, [])

	def test_5_cambios_en_el_hilo_de_sintesis_sin_cancel(self) -> None:
		d = _fakeEloquence()
		en = str(ibm.LANGUAGES["enu"][0])
		d.setSetting("voice", en)
		d.setSetting("sampleRate", "0")
		d.setSetting("variant", "2")
		d.cancel.assert_not_called()
		self.assertEqual(d._client.calls, [])  # nada desde el núcleo
		self.assertEqual(d._settings["pitch"], 81)  # la variante se adopta al momento
		with mock.patch("tiresias.audio.wave_player.WavePlayer", return_value=_FakePlayer()):
			d._synthesizeSegment(["hola"], lambda b: None, lambda: False)
		ids = d._client.ids()
		self.assertIn(bridge.ECI_SET_PARAM, ids)
		self.assertIn(bridge.ECI_COPY_VOICE, ids)
		self.assertLess(ids.index(bridge.ECI_COPY_VOICE), ids.index(bridge.ECI_ADD_TEXT))
		langCalls = [c for c in d._client.calls if c[0] == bridge.ECI_SET_PARAM and c[1][1] == ibm.P_LANGUAGE]
		self.assertEqual(langCalls[0][1][2], int(en))
		self.assertEqual(d.sampleRate, 8000)
		self.assertFalse(d._dirty)

	def test_6_cancelar_desde_el_nucleo_no_llama_al_puente(self) -> None:
		d = _fakeEloquence()
		d._client.driver = None  # el motor no termina: hay que cancelarlo
		cancelled = [False]
		worker = threading.Thread(target=d._synthesizeSegment, args=(["hola"], lambda b: None, lambda: cancelled[0]), name="SintesisPrueba")
		worker.start()
		self.assertTrue(_waitFor(lambda: bridge.ECI_SYNTHESIZE in d._client.ids()))
		before = len(d._client.calls)
		cancelled[0] = True
		d._cancelSynthesis()  # en el «núcleo» (este hilo)
		self.assertEqual(len(d._client.calls), before)
		worker.join(5)
		stops = [c for c in d._client.calls if c[0] == bridge.ECI_STOP]
		self.assertEqual(len(stops), 1)
		self.assertEqual(stops[0][2], "SintesisPrueba")

	def test_7_prefijo_con_idioma_y_volumen(self) -> None:
		d = _fakeEloquence()
		data = d._buildInput(["hola"])
		self.assertTrue(data.startswith(b"`l2.0 `vv100 "), data)
		d._settings["voice"] = str(ibm.LANGUAGES["enu"][0])
		self.assertTrue(d._buildInput(["hello"]).startswith(b"`l1.0 `vv100 "))

	def test_10_emojis_no_cortan_el_final(self) -> None:
		self.assertTrue(ibm.toCp1252("hola 😀 adiós 👍🏽 fin").endswith(b"fin"))
		self.assertEqual(ibm.toCp1252("ó"), b"\xf3")

	def test_15_voz_inexistente_no_se_guarda(self) -> None:
		d = _fakeEloquence()
		esp = d._settings["voice"]
		d.setSetting("voice", "999999")
		self.assertEqual(d._settings["voice"], esp)
		self.assertEqual(d.saveableSettings()["voice"], esp)
		d.setSetting("variant", "42")
		self.assertEqual(d._settings["variant"], "1")

	def test_16_fallo_al_entrar_en_espera_no_cambia_de_sintetizador(self) -> None:
		d = _fakeEloquence()

		def dormir():
			d._dormant = True

		d._client = _FakeClient(fail={bridge.ECI_ADD_TEXT}, onFail=dormir)
		with mock.patch.object(d, "_reportFailure") as report:
			d._synthesizeSegment(["hola"], lambda b: None, lambda: False)  # no lanza
			report.assert_not_called()
		# La voz se cancela justo cuando falla la llamada.
		flag = [False]
		d2 = _fakeEloquence(_FakeClient(fail={bridge.ECI_ADD_TEXT}, onFail=lambda: flag.__setitem__(0, True)))
		with mock.patch.object(d2, "_reportFailure") as report:
			d2._synthesizeSegment(["hola"], lambda b: None, lambda: flag[0])
			report.assert_not_called()
		# Un fallo de verdad sí se avisa.
		d3 = _fakeEloquence(_FakeClient(fail={bridge.ECI_ADD_TEXT}))
		with mock.patch.object(d3, "_reportFailure") as report, mock.patch.object(d3, "_reconnect", return_value=False):
			with self.assertRaises(bridge.BridgeError):
				d3._synthesizeSegment(["hola"], lambda b: None, lambda: False)
			report.assert_called_once()


# ====================================================================== 6: tubería con tiempo de espera
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
kernel32.CreateNamedPipeW.restype = wintypes.HANDLE
kernel32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


@unittest.skipUnless(HAS_ELOQUENCE, NO_ELOQUENCE)
class PipeTimeoutTests(unittest.TestCase):
	def test_6_un_puente_colgado_no_bloquea_para_siempre(self) -> None:
		name = f"\\\\.\\pipe\\tiresias_prueba_colgado_{os.getpid()}"
		h = kernel32.CreateNamedPipeW(name, 3, 4 | 2, 1, 65536, 65536, 0, None)  # dúplex, mensajes
		self.assertNotEqual(h, wintypes.HANDLE(-1).value)
		accepted = threading.Thread(target=kernel32.ConnectNamedPipe, args=(h, None), daemon=True)
		accepted.start()
		client = bridge.PipeClient()
		try:
			client.connect(name)
			t0 = time.monotonic()
			with self.assertRaises(bridge.BridgeError):
				client.call(bridge.ECI_VERSION, timeout=0.3)  # el «puente» nunca responde
			self.assertLess(time.monotonic() - t0, 3.0)
			self.assertFalse(client.connected)
			with self.assertRaises(bridge.BridgeError):
				client.call(bridge.ECI_VERSION, timeout=0.3)
		finally:
			client.close()
			kernel32.CloseHandle(h)

	def test_6_cerrojo_con_tiempo_de_espera(self) -> None:
		client = bridge.PipeClient()
		client._handle = 1  # no se llega a usar
		client._lock.acquire()
		try:
			t0 = time.monotonic()
			with self.assertRaises(bridge.BridgeError):
				client.call(bridge.ECI_VERSION, timeout=0.2)
			self.assertLess(time.monotonic() - t0, 2.0)
		finally:
			client._lock.release()
			client._handle = None


# ====================================================================== Eloquence real (síntesis a memoria)
def _rms(data: bytes) -> float:
	a = array.array("h")
	a.frombytes(data[: len(data) - len(data) % 2])
	return math.sqrt(sum(x * x for x in a) / max(1, len(a)))


@unittest.skipUnless(REAL_BRIDGE, "Falta el puente de 32 bits, ECI.DLL o rundll32 de 32 bits")
class EloquenceRealTests(unittest.TestCase):
	TEXT = "hola, esto es una prueba de voz"

	@classmethod
	def setUpClass(cls) -> None:
		cls.d = ibm.SynthDriver()

	@classmethod
	def tearDownClass(cls) -> None:
		cls.d.terminate()

	def _speak(self, items) -> bytes:
		out: list[bytes] = []
		self.d._synthesizeSegment(items, out.append, lambda: False)
		return b"".join(out)

	def test_7_tras_cambiar_idioma_y_volumen_el_siguiente_es_normal(self) -> None:
		base = self._speak([self.TEXT])
		english = self._speak([LangChangeCommand("en"), self.TEXT])
		self.assertNotEqual(len(base), len(english))
		self._speak([LangChangeCommand("en"), "hello", VolumeCommand(-60), "quiet"])
		after = self._speak([self.TEXT])
		self.assertEqual(len(after), len(base))  # en español, no en inglés
		self.assertGreater(_rms(after), _rms(base) * 0.8)  # a volumen completo

	def test_5_variantes_leidas_y_frecuencia_en_el_hilo(self) -> None:
		self.assertEqual(set(self.d._variantDefaults), set(ibm.VARIANTS))
		self.assertNotEqual(self.d._variantDefaults["1"]["pitch"], self.d._variantDefaults["2"]["pitch"])
		self.d.setSetting("sampleRate", "0")
		self.assertEqual(self.d.sampleRate, 11025)  # aún no: se aplica antes del siguiente trozo
		short = self._speak([self.TEXT])
		self.assertEqual(self.d.sampleRate, 8000)
		self.d.setSetting("sampleRate", "1")
		normal = self._speak([self.TEXT])
		self.assertEqual(self.d.sampleRate, 11025)
		self.assertLess(len(short), len(normal))


if __name__ == "__main__":
	unittest.main()
