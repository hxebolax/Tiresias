"""Pruebas de sintetizadores y audio: reproductor, recorte de silencio,
velocidad (WSOLA), división del sonido, atenuación, mezclador, sonidos de
controles, OneCore, SAPI 5, Piper y cambio automático de sintetizador.

No necesitan tarjeta de sonido: el reproductor se prueba con una salida
simulada y Core Audio con objetos falsos. Las pruebas de Piper que necesitan
eSpeak NG u onnxruntime se saltan si no están instalados.
"""

from __future__ import annotations

import array
import hashlib
import io
import json
import math
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import wave
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402
from tiresias.config import conf  # noqa: E402

import tiresias.audio  # noqa: E402,F401  (valores por defecto de audio)
from tiresias.audio import core_audio, ducking, earcons, mixer, sound_split, timestretch, tones, wave_player  # noqa: E402
from tiresias.objects.roles import Role, State  # noqa: E402
from tiresias.speech.commands import (  # noqa: E402
	BreakCommand,
	LangChangeCommand,
	PhonemeCommand,
	PitchCommand,
	VolumeCommand,
)
from tiresias.synth import base as synthBase  # noqa: E402
from tiresias.synth import piper, piper_voices  # noqa: E402


class _TempData:
	"""Carpeta de datos temporal mientras dura una prueba."""

	def setUp(self) -> None:  # noqa: D401
		self._oldData = paths.DATA_DIR
		self.tmp = tempfile.mkdtemp(prefix="tiresias_audio_")
		paths.setDataDir(self.tmp)
		paths.ensureDataDirs()

	def tearDown(self) -> None:
		paths.setDataDir(self._oldData)
		shutil.rmtree(self.tmp, ignore_errors=True)


def _tone(rate: int = 22050, ms: int = 200, hz: float = 220.0, amp: int = 8000) -> bytes:
	n = int(rate * ms / 1000)
	return array.array("h", [int(amp * math.sin(2 * math.pi * hz * i / rate)) for i in range(n)]).tobytes()


# ====================================================================== reproductor
class _FakeBackend(wave_player._Backend):
	"""Salida simulada: todo lo escrito «suena» al instante."""

	mode = "wasapi"

	def __init__(self, rate: int, event: int) -> None:
		super().__init__(rate, event)
		self.data = bytearray()
		self.resets = 0

	def open(self, deviceName: str) -> None:
		self.deviceName = deviceName

	def write(self, data: bytes) -> int:
		self.data += data
		frames = len(data) // 4
		self.written += frames
		return frames

	def played(self) -> int:
		return self.written

	def reset(self) -> None:
		self.resets += 1
		self.written = 0

	def pause(self, switch: bool) -> None:
		pass

	def close(self) -> None:
		pass


def _sync(p, timeout: float) -> None:
	"""Espera a que el reproductor termine lo encolado."""
	done = threading.Event()
	p.feed(None, done.set)
	done.wait(timeout)


class WavePlayerTests(unittest.TestCase):
	def _player(self, **kw) -> tuple[wave_player.WavePlayer, list]:
		backends: list[_FakeBackend] = []
		p = wave_player.WavePlayer(22050, 1, name="prueba", **kw)

		def openBackend():
			if p._backend is None:
				p._backend = _FakeBackend(22050, p._event)
				backends.append(p._backend)
			return p._backend

		p._openBackend = openBackend  # type: ignore[method-assign]
		return p, backends

	def test_callbacks_in_order(self) -> None:
		p, backends = self._player(keepAwake=False)
		try:
			order: list[str] = []
			p.feed(_tone(ms=50), lambda: order.append("a"))
			p.feed(None, lambda: order.append("b"))
			p.feed(_tone(ms=50), lambda: order.append("c"))
			_sync(p, 5)
			self.assertEqual(order, ["a", "b", "c"])
			# Mono a estéreo: dos tonos de 50 ms a 22 050 Hz = 2 × 1102 tramas de 4 bytes.
			self.assertEqual(len(backends[0].data), 2 * int(22050 * 0.05) * 4)
		finally:
			p.terminate()

	def test_stop_discards_pending(self) -> None:
		p, backends = self._player(keepAwake=False)
		try:
			p.pause(True)
			called: list[int] = []
			p.feed(_tone(ms=100), lambda: called.append(1))
			time.sleep(0.1)
			p.stop()
			p.pause(False)
			_sync(p, 5)
			self.assertEqual(called, [])
			self.assertFalse(p.isPlaying())
		finally:
			p.terminate()

	def test_apply_gains(self) -> None:
		data = array.array("h", [1000, -1000]).tobytes()
		out = array.array("h")
		out.frombytes(wave_player._applyGains(data, 1, 0.5, (1.0, 0.0)))
		self.assertEqual(list(out), [500, 0, -500, 0])

	def test_noise_chunk_level(self) -> None:
		p, _b = self._player(keepAwake=True)
		try:
			with mock.patch.object(wave_player, "_whiteNoiseVolume", return_value=100):
				chunk = p._noiseChunk(1000)
			samples = array.array("h")
			samples.frombytes(chunk)
			self.assertEqual(len(samples), 2000)
			self.assertLessEqual(max(abs(s) for s in samples), int(32767 * 0.05))
			self.assertGreater(max(abs(s) for s in samples), 0)
		finally:
			p.terminate()

	def test_buffer_sizes_and_modes(self) -> None:
		self.assertEqual(set(wave_player.BUFFER_SIZES), {"low", "normal", "high"})
		self.assertIn(conf["audio"]["outputMode"], wave_player.OUTPUT_MODES)


# ====================================================================== silencio y velocidad
class SilenceTests(unittest.TestCase):
	def test_trim_leading(self) -> None:
		data = bytes(2000) + _tone(ms=20)
		out, found = synthBase.trimLeadingSilence(data, 22050)
		self.assertTrue(found)
		self.assertLess(len(out), len(data))
		margin = int(22050 * synthBase.SILENCE_MARGIN_MS / 1000) * 2
		self.assertLessEqual(len(data) - len(out), 2000)
		self.assertGreaterEqual(len(out), len(_tone(ms=20)) + 0)
		self.assertLessEqual(len(out), len(_tone(ms=20)) + margin + 2)

	def test_trim_all_silent(self) -> None:
		out, found = synthBase.trimLeadingSilence(bytes(1000), 22050)
		self.assertFalse(found)
		self.assertEqual(out, b"")

	def test_trim_trailing(self) -> None:
		data = _tone(ms=20) + bytes(22050)
		out = synthBase.trimTrailingSilence(data, 22050, keepMs=10)
		self.assertLess(len(out), len(_tone(ms=20)) + int(22050 * 0.012) * 2)


class TimeStretchTests(unittest.TestCase):
	@unittest.skipUnless(timestretch.available(), "numpy no está instalado")
	def test_speed_keeps_pitch(self) -> None:
		import numpy as np

		rate = 22050
		data = _tone(rate, 2000, 200.0)
		out = timestretch.stretch(data, rate, 2.0)
		self.assertAlmostEqual(len(out) / len(data), 0.5, delta=0.02)
		a = np.frombuffer(out, np.int16).astype(float)[2000:12000]
		crossings = ((a[:-1] < 0) & (a[1:] >= 0)).sum()
		self.assertAlmostEqual(crossings / (len(a) / rate), 200.0, delta=10.0)

	def test_factor_one_is_identity(self) -> None:
		data = _tone()
		self.assertEqual(timestretch.stretch(data, 22050, 1.0), data)


# ====================================================================== división del sonido
class SoundSplitTests(unittest.TestCase):
	def test_next_mode_included(self) -> None:
		self.assertEqual(sound_split.nextMode("off", ["off", "leftRight", "rightLeft"]), "leftRight")
		self.assertEqual(sound_split.nextMode("rightLeft", ["off", "leftRight", "rightLeft"]), "off")

	def test_next_mode_not_included(self) -> None:
		# El modo actual no está en la lista: se pasa al siguiente incluido.
		self.assertEqual(sound_split.nextMode("leftBoth", ["off", "bothRight"]), "bothRight")

	def test_included_modes_default(self) -> None:
		self.assertEqual(sound_split.includedModes(), list(sound_split.ORDER))


# ====================================================================== Core Audio falso
class _FakeSimpleVolume:
	def __init__(self) -> None:
		self.level = 1.0
		self.mute = False

	def GetMasterVolume(self):
		return self.level

	def SetMasterVolume(self, v, ctx):
		self.level = v

	def GetMute(self):
		return self.mute

	def SetMute(self, m, ctx):
		self.mute = bool(m)


class _FakeSession:
	def __init__(self, pid: int, ident: str) -> None:
		self.pid = pid
		self.identifier = ident
		self.vol = _FakeSimpleVolume()

	def simpleVolume(self):
		return self.vol

	def displayName(self) -> str:
		return ""

	def state(self) -> int:
		return 1


class DuckingTests(_TempData, unittest.TestCase):
	def setUp(self) -> None:
		super().setUp()
		self.sessions = [_FakeSession(1111, "a"), _FakeSession(core_audio.OWN_PID, "own"), _FakeSession(0, "sys")]
		self.patch = mock.patch.object(core_audio, "getSessions", side_effect=lambda allDevices=False: list(self.sessions))
		self.patch.start()
		self.later = mock.patch.object(ducking.queue_handler, "callLater", return_value=1)
		self.later.start()
		self.names = mock.patch.object(ducking, "_processName", side_effect=lambda pid: "sndvol.exe" if pid == 2222 else "app.exe")
		self.names.start()
		self._level = conf["audio"]["duckingLevel"]
		conf["audio"]["duckingLevel"] = 50

	def tearDown(self) -> None:
		ducking.unduck()
		core_audio.waitSessionThread()
		conf["audio"]["duckingLevel"] = self._level
		self.names.stop()
		self.later.stop()
		self.patch.stop()
		super().tearDown()

	def test_duck_and_new_sessions(self) -> None:
		ducking.duck()
		core_audio.waitSessionThread()
		self.assertAlmostEqual(self.sessions[0].vol.level, 0.5)
		self.assertEqual(self.sessions[1].vol.level, 1.0)  # Tiresias
		self.assertEqual(self.sessions[2].vol.level, 1.0)  # sonidos del sistema
		# Una aplicación empieza a sonar durante la atenuación.
		late = _FakeSession(3333, "late")
		mixerVol = _FakeSession(2222, "sndvol")
		self.sessions += [late, mixerVol]
		ducking._rescanTimer = None
		ducking._rescan()
		core_audio.waitSessionThread()
		self.assertAlmostEqual(late.vol.level, 0.5)
		self.assertEqual(mixerVol.vol.level, 1.0)  # #5752
		ducking.unduck()
		core_audio.waitSessionThread()
		self.assertEqual(self.sessions[0].vol.level, 1.0)
		self.assertEqual(late.vol.level, 1.0)


# ====================================================================== mezclador
class _FakeEndpoint:
	def __init__(self, level: float, muted: bool) -> None:
		self.level = level
		self.muted = muted

	def GetMasterVolumeLevelScalar(self):
		return self.level

	def SetMasterVolumeLevelScalar(self, v, ctx):
		self.level = v

	def GetMute(self):
		return self.muted

	def SetMute(self, m, ctx):
		self.muted = bool(m)


class MixerTests(unittest.TestCase):
	def setUp(self) -> None:
		self.render = _FakeEndpoint(0.0, True)
		self.capture = _FakeEndpoint(0.8, False)
		self.p1 = mock.patch.object(core_audio, "endpointVolume", side_effect=lambda devId=None, flow=0: self.capture if flow == core_audio.eCapture else self.render)
		self.p2 = mock.patch.object(core_audio, "getSessions", return_value=[])
		self.p3 = mock.patch.object(core_audio, "getDefaultDeviceId", return_value="mic")
		for p in (self.p1, self.p2, self.p3):
			p.start()
		self._saved = {k: conf["audio"][k] for k in ("unmuteOnStartup", "startupVolumeLevel", "confirmSystemMute", "mixerVolumeStep", "outputDevice")}

	def tearDown(self) -> None:
		for k, v in self._saved.items():
			conf["audio"][k] = v
		for p in (self.p1, self.p2, self.p3):
			p.stop()

	def test_ensure_audible(self) -> None:
		conf["audio"]["unmuteOnStartup"] = True
		conf["audio"]["startupVolumeLevel"] = 40
		msg = mixer.ensureAudible()
		self.assertFalse(self.render.muted)
		self.assertAlmostEqual(self.render.level, 0.4)
		self.assertTrue(msg)

	def test_ensure_audible_disabled(self) -> None:
		conf["audio"]["unmuteOnStartup"] = False
		self.assertIsNone(mixer.ensureAudible())
		self.assertTrue(self.render.muted)

	def test_ensure_audible_keeps_low_volume(self) -> None:
		conf["audio"]["unmuteOnStartup"] = True
		self.render.level, self.render.muted = 0.1, False
		self.assertIsNone(mixer.ensureAudible())
		self.assertAlmostEqual(self.render.level, 0.1)

	def test_master_volume_step(self) -> None:
		conf["audio"]["mixerVolumeStep"] = 5
		self.render.level, self.render.muted = 0.5, False
		self.assertEqual(mixer.changeMasterVolume(1), 55)
		self.assertEqual(mixer.changeMasterVolume(-1), 50)
		self.assertEqual(mixer.setMasterVolume(150), 100)

	def test_mic_toggle(self) -> None:
		self.assertTrue(mixer.toggleMicMute())
		self.assertTrue(self.capture.muted)
		self.assertFalse(mixer.toggleMicMute())

	def test_mute_key_confirmation(self) -> None:
		conf["audio"]["confirmSystemMute"] = True
		self.render.level, self.render.muted = 0.5, False
		mixer._muteArmedUntil = 0.0
		first = mixer.handleMuteKey()
		self.assertFalse(self.render.muted)
		self.assertIn("otra vez", first)
		mixer.handleMuteKey()
		self.assertTrue(self.render.muted)
		# Si ya está silenciado, una pulsación devuelve el sonido.
		mixer.handleMuteKey()
		self.assertFalse(self.render.muted)

	def test_cycle_tiresias_output(self) -> None:
		devs = [core_audio.Device("1", "Altavoces (dispositivo con un nombre muy largo de más de 31 letras)", 0, True), core_audio.Device("2", "Auriculares", 0)]
		with mock.patch.object(mixer, "outputDevices", return_value=devs):
			conf["audio"]["outputDevice"] = ""
			mixer.cycleTiresiasOutput(1)
			self.assertEqual(conf["audio"]["outputDevice"], devs[0].name)
			self.assertEqual(wave_player.OutputSettings.deviceName, devs[0].name)
			mixer.cycleTiresiasOutput(1)
			mixer.cycleTiresiasOutput(1)
			self.assertEqual(conf["audio"]["outputDevice"], "")

	def test_find_device_accepts_truncated_names(self) -> None:
		devs = [core_audio.Device("1", "Altavoces (Realtek High Definition Audio)", 0)]
		with mock.patch.object(core_audio, "getDevices", return_value=devs):
			self.assertIs(core_audio.findDevice("Altavoces (Realtek High Definit"), devs[0])
			self.assertIsNone(core_audio.findDevice("Otro"))


# ====================================================================== sonidos de controles
class _Obj:
	def __init__(self, role, states=(), location=None, roleText=None, name="Aceptar") -> None:
		self.role = role
		self.states = set(states)
		self.location = location
		self.roleText = roleText
		self.name = name
		self.value = ""
		self.description = ""
		self.keyboardShortcut = ""
		self.placeholder = ""
		self.positionInfo = {}
		self.hasText = False


class EarconTests(unittest.TestCase):
	def setUp(self) -> None:
		self._saved = dict(conf["earcons"].dict()) if hasattr(conf["earcons"], "dict") else {k: conf["earcons"][k] for k in ("mode", "roles", "states", "positional")}
		self.played: list[tuple[str, object]] = []
		self.p = mock.patch.object(tones, "playSound", side_effect=lambda name, pan=None: self.played.append((name, pan)))
		self.p.start()

	def tearDown(self) -> None:
		self.p.stop()
		for k, v in self._saved.items():
			conf["earcons"][k] = v

	def test_all_sounds_registered(self) -> None:
		names = set(tones.availableSounds())
		for name in list(earcons.ROLE_SOUNDS.values()) + list(earcons.STATE_SOUNDS.values()) + ["boundaryStart", "boundaryEnd", "micMuted", "micUnmuted"]:
			self.assertIn(name, names)

	def test_sounds_for_checkbox(self) -> None:
		names, ctx = earcons.soundsForObject(_Obj(Role.CHECKBOX), Role.CHECKBOX, set(), "focus")
		self.assertEqual(names, ["role_checkBox", "state_notChecked"])
		self.assertIn(State.CHECKED, ctx.negative)
		names, _ctx = earcons.soundsForObject(_Obj(Role.CHECKBOX), Role.CHECKBOX, {State.CHECKED}, "focus")
		self.assertEqual(names, ["role_checkBox", "state_checked"])

	def test_heading_levels(self) -> None:
		obj = _Obj(Role.HEADING)
		obj.level = 3
		self.assertEqual(earcons.roleSound(obj, Role.HEADING), "role_heading3")
		self.assertEqual(earcons.roleSound(obj, Role.HEADING2), "role_heading2")

	def test_custom_role_text_has_no_sound(self) -> None:
		names, ctx = earcons.soundsForObject(_Obj(Role.BUTTON, roleText="botón especial"), Role.BUTTON, set(), "focus")
		self.assertNotIn("role_button", names)

	def test_instead_of_speech_suppresses_role_and_state(self) -> None:
		from tiresias import presentation

		conf["earcons"]["mode"] = "insteadOfSpeech"
		conf["earcons"]["positional"] = False
		obj = _Obj(Role.CHECKBOX, {State.CHECKED})
		with earcons.objectContext(obj, presentation.Reason.FOCUS):
			self.assertTrue(earcons.roleHandled(Role.CHECKBOX))
			self.assertTrue(earcons.stateHandled(State.CHECKED))
			text = " ".join(presentation.getObjectSpeech(obj, presentation.Reason.FOCUS))
		self.assertEqual(text, "Aceptar")
		self.assertEqual([n for n, _p in self.played], ["role_checkBox", "state_checked"])
		# Fuera del contexto no se omite nada.
		self.assertFalse(earcons.roleHandled(Role.CHECKBOX))

	def test_with_speech_keeps_text(self) -> None:
		from tiresias import presentation

		conf["earcons"]["mode"] = "withSpeech"
		obj = _Obj(Role.CHECKBOX, {State.CHECKED})
		with earcons.objectContext(obj, presentation.Reason.FOCUS):
			self.assertFalse(earcons.roleHandled(Role.CHECKBOX))
		self.assertTrue(self.played)

	def test_off_plays_nothing(self) -> None:
		from tiresias import presentation

		conf["earcons"]["mode"] = "off"
		with earcons.objectContext(_Obj(Role.BUTTON), presentation.Reason.FOCUS):
			pass
		self.assertEqual(self.played, [])

	def test_positional_pan(self) -> None:
		from tiresias import presentation

		conf["earcons"]["mode"] = "withSpeech"
		conf["earcons"]["positional"] = True
		obj = _Obj(Role.BUTTON, location=(0, 0, 10, 10))
		with mock.patch.object(earcons, "monitorRect", return_value=(0, 0, 1000, 800)):
			with earcons.objectContext(obj, presentation.Reason.FOCUS):
				pass
		self.assertTrue(self.played)
		self.assertLess(self.played[0][1], -0.9)

	def test_pan_for_rect(self) -> None:
		self.assertAlmostEqual(earcons.panForRect((450, 0, 100, 10), (0, 0, 1000, 800)), 0.0)
		self.assertIsNone(earcons.panForRect(None))

	def test_states_context_change(self) -> None:
		conf["earcons"]["mode"] = "insteadOfSpeech"
		obj = _Obj(Role.CHECKBOX)
		with earcons.statesContext(obj, set(), {State.CHECKED}):
			self.assertTrue(earcons.stateHandled(State.CHECKED, negative=True))
		self.assertEqual(self.played[0][0], "state_notChecked")

	def test_cycle_mode(self) -> None:
		conf["earcons"]["mode"] = "off"
		earcons.cycleMode()
		self.assertEqual(conf["earcons"]["mode"], "withSpeech")


class ToneTests(_TempData, unittest.TestCase):
	def test_pan_gains(self) -> None:
		left, right = tones.panGains(-1.0)
		self.assertGreater(left, 1.0)
		self.assertAlmostEqual(right, 0.0, places=6)
		self.assertEqual(tones.panGains(None), (1.0, 1.0))
		l0, r0 = tones.panGains(0.0)
		self.assertAlmostEqual(l0, r0)

	def test_export_theme(self) -> None:
		folder = os.path.join(paths.soundsDir(), "personalizado")
		count = tones.exportTheme(folder, ["role_button", "boundaryEnd"])
		self.assertEqual(count, 2)
		with wave.open(os.path.join(folder, "role_button.wav")) as w:
			self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (2, 2, tones.SAMPLE_RATE))
			self.assertGreater(w.getnframes(), 0)
		self.assertIn("personalizado", tones.availableThemes())
		# No sobrescribe sin permiso.
		self.assertEqual(tones.exportTheme(folder, ["role_button"]), 0)

	def test_timbres(self) -> None:
		for t in tones.TIMBRES:
			self.assertTrue(tones._genNote(440.0, 20, 50, 50, t))


# ====================================================================== sintetizadores
class OneCoreTests(unittest.TestCase):
	def _driver(self):
		from tiresias.synth import onecore

		d = onecore.SynthDriver.__new__(onecore.SynthDriver)
		d._voices = {}
		d._settings = {"voice": "", "rate": 50, "pitch": 50, "rateBoost": False}
		return onecore, d

	def test_ssml_commands(self) -> None:
		onecore, d = self._driver()
		ssml = d._buildSsml(["Hola", VolumeCommand(-50), "bajo", PhonemeCommand("ˈola", "hola"), PitchCommand(10), "alto", BreakCommand(100)])
		self.assertIn('<prosody volume="50">', ssml)
		self.assertIn('<phoneme alphabet="ipa" ph="ˈola">hola</phoneme>', ssml)
		self.assertIn('<prosody pitch="+20%">', ssml)
		self.assertIn('<break time="100ms"/>', ssml)
		self.assertEqual(ssml.count("<prosody"), ssml.count("</prosody>"))

	def test_punctuation_pause(self) -> None:
		onecore, _d = self._driver()
		self.assertEqual(onecore.punctuationPauseMs("Hola."), onecore.SENTENCE_PAUSE_MS)
		self.assertEqual(onecore.punctuationPauseMs("Hola,"), onecore.CLAUSE_PAUSE_MS)
		self.assertEqual(onecore.punctuationPauseMs("Hola"), 0)
		self.assertLess(onecore.punctuationPauseMs("Hola.", 2.0), onecore.SENTENCE_PAUSE_MS)


class Sapi5Tests(unittest.TestCase):
	def test_xml_commands(self) -> None:
		from tiresias.synth import sapi5

		d = sapi5.SynthDriver.__new__(sapi5.SynthDriver)
		d._settings = {"rate": 50, "pitch": 50}
		xml = d._buildXml(["Hola", VolumeCommand(-20), "x", LangChangeCommand("en_US"), "hello", PhonemeCommand("ˈola", "hola")])
		self.assertIn('<volume level="80">', xml)
		self.assertIn('<lang langid="409">', xml)
		self.assertIn("hola", xml)
		self.assertNotIn("ˈola", xml)

	def test_boost_factor(self) -> None:
		from tiresias.synth import sapi5

		self.assertEqual(sapi5.boostFactor(0), 1.0)
		self.assertEqual(sapi5.boostFactor(100), 3.0)
		self.assertIn("rateBoost", [s.id for s in sapi5.SynthDriver.supportedSettings])


class PiperTests(_TempData, unittest.TestCase):
	def test_speed_and_pitch(self) -> None:
		self.assertAlmostEqual(piper.speedForRate(50), 1.0)
		self.assertAlmostEqual(piper.speedForRate(0), 0.5)
		self.assertAlmostEqual(piper.speedForRate(100), 2.5)
		self.assertAlmostEqual(piper.speedForRate(100, boost=True), 5.0)
		self.assertAlmostEqual(piper.pitchFactor(50), 1.0)
		self.assertGreater(piper.pitchFactor(100), 1.3)

	def test_phoneme_ids(self) -> None:
		from tiresias.synth.piper_phonemizer import phonemesToIds

		idMap = {"_": [0], "^": [1], "$": [2], "a": [5], "b": [6]}
		self.assertEqual(phonemesToIds("ab", idMap), [1, 0, 5, 0, 6, 0, 2])
		# Los caracteres desconocidos se ignoran.
		self.assertEqual(phonemesToIds("aZ", idMap), [1, 0, 5, 0, 2])

	def test_catalog_sorting(self) -> None:
		data = {
			"en_US-amy-low": {"name": "amy", "language": {"code": "en_US", "family": "en"}, "quality": "low", "files": {}},
			"es_MX-ald-medium": {"name": "ald", "language": {"code": "es_MX", "family": "es"}, "quality": "medium", "files": {}},
			"es_ES-davefx-medium": {"name": "davefx", "language": {"code": "es_ES", "family": "es"}, "quality": "medium", "files": {"a.onnx": {"size_bytes": 10}, "a.onnx.json": {"size_bytes": 5}}},
		}
		voices = piper_voices.parseCatalog(data)
		self.assertEqual([v.key for v in voices], ["es_ES-davefx-medium", "es_MX-ald-medium", "en_US-amy-low"])
		self.assertEqual(voices[0].size, 15)
		self.assertIn("España", voices[0].displayName)

	def _fakeVoice(self, key: str = "es_ES-prueba-low") -> str:
		folder = os.path.join(paths.voicesDir(), key)
		os.makedirs(folder, exist_ok=True)
		with open(os.path.join(folder, key + ".onnx"), "wb") as f:
			f.write(b"x")
		with open(os.path.join(folder, key + ".onnx.json"), "w", encoding="utf-8") as f:
			json.dump({"audio": {"sample_rate": 16000, "quality": "low"}, "language": {"code": "es_ES"}, "espeak": {"voice": "es"}}, f)
		return folder

	def test_installed_and_delete(self) -> None:
		self._fakeVoice()
		voices = piper_voices.installedVoices()
		self.assertEqual([v.key for v in voices], ["es_ES-prueba-low"])
		self.assertEqual(voices[0].sampleRate, 16000)
		self.assertTrue(piper_voices.deleteVoice("es_ES-prueba-low"))
		self.assertEqual(piper_voices.installedVoices(), [])

	def _entry(self, payload: bytes, md5: str) -> piper_voices.VoiceEntry:
		return piper_voices.VoiceEntry(
			key="es_ES-red-low",
			name="red",
			language="es_ES",
			family="es",
			languageName="Español",
			quality="low",
			files={
				"es/es_ES/red/low/es_ES-red-low.onnx": {"size_bytes": len(payload), "md5_digest": md5},
				"es/es_ES/red/low/es_ES-red-low.onnx.json": {"size_bytes": 2, "md5_digest": hashlib.md5(b"{}").hexdigest()},
			},
		)

	def _fakeOpen(self, payload: bytes):
		def opener(url):
			body = b"{}" if url.endswith(".json") else payload
			return _Resp(body)

		return opener

	def test_download_verifies_md5(self) -> None:
		payload = b"modelo" * 1000
		entry = self._entry(payload, hashlib.md5(payload).hexdigest())
		progress: list[tuple[int, int]] = []
		with mock.patch.object(piper_voices, "_open", side_effect=self._fakeOpen(payload)):
			folder = piper_voices.downloadVoice(entry, lambda d, t: progress.append((d, t)))
		self.assertTrue(os.path.isfile(os.path.join(folder, "es_ES-red-low.onnx")))
		self.assertEqual(progress[-1][0], len(payload) + 2)
		bad = self._entry(payload, "0" * 32)
		with mock.patch.object(piper_voices, "_open", side_effect=self._fakeOpen(payload)):
			shutil.rmtree(folder)
			with self.assertRaises(IOError):
				piper_voices.downloadVoice(bad)
		self.assertFalse(os.path.exists(os.path.join(paths.voicesDir(), "es_ES-red-low")))

	def test_download_cancel(self) -> None:
		payload = b"x" * 10
		entry = self._entry(payload, hashlib.md5(payload).hexdigest())
		cancel = threading.Event()
		cancel.set()
		with mock.patch.object(piper_voices, "_open", side_effect=self._fakeOpen(payload)):
			with self.assertRaises(piper_voices.DownloadCancelled):
				piper_voices.downloadVoice(entry, cancel=cancel)
		self.assertEqual(os.listdir(paths.voicesDir()), [])

	def test_phonemizer_spanish(self) -> None:
		from tiresias.synth.espeak import findLibrary

		if findLibrary() is None:
			self.skipTest("eSpeak NG no está disponible")
		from tiresias.synth.piper_phonemizer import Phonemizer

		p = Phonemizer()
		out = p.phonemize("Hola, ¿qué tal? Adiós.", "es")
		self.assertEqual(len(out), 2)
		self.assertIn(",", out[0])
		self.assertTrue(out[0].rstrip().endswith("?"))
		self.assertNotIn("¿", out[0])

	def test_check_without_voices(self) -> None:
		self.assertFalse(piper.SynthDriver.check())


class _Resp:
	def __init__(self, body: bytes) -> None:
		self._buf = io.BytesIO(body)

	def read(self, n: int = -1) -> bytes:
		return self._buf.read(n)

	def __enter__(self):
		return self

	def __exit__(self, *a) -> None:
		pass


# ====================================================================== fallos del sintetizador
class _FailingSynth(synthBase.AudioSynthDriver):
	name = "fallo"
	supportedSettings = ()

	@classmethod
	def check(cls) -> bool:
		return True

	def _synthesizeSegment(self, items, emit, isCancelled) -> None:
		raise RuntimeError("roto")


class _GoodSynth(synthBase.SynthDriver):
	name = "bueno"
	description = "Bueno"

	@classmethod
	def check(cls) -> bool:
		return True

	def speak(self, sequence) -> None:
		pass

	def cancel(self) -> None:
		pass


class FailoverTests(unittest.TestCase):
	def test_failed_notification(self) -> None:
		got: list = []
		handler = lambda synth=None, error=None: got.append((synth, error))  # noqa: E731
		synthBase.synthFailed.register(handler)
		s = _FailingSynth()
		quiet = mock.patch.object(synthBase.log, "exception")
		quiet.start()
		try:
			s.speak(["uno"])
			s.speak(["dos"])
			deadline = time.time() + 5
			while not got and time.time() < deadline:
				time.sleep(0.02)
			self.assertEqual(len(got), 1)
			self.assertIs(got[0][0], s)
		finally:
			quiet.stop()
			synthBase.synthFailed.unregister(handler)
			s.terminate()

	def test_fallback_switches_synth(self) -> None:
		import types

		from tiresias import synth

		modA = types.ModuleType("fallo")
		modA.SynthDriver = _FailingSynth
		modB = types.ModuleType("bueno")
		modB.SynthDriver = _GoodSynth
		synth.registerDriverModule("fallo", modA)
		synth.registerDriverModule("bueno", modB)
		oldPriority = list(conf["speech"]["synthPriority"])
		conf["speech"]["synthPriority"] = ["bueno"]
		try:
			self.assertTrue(synth.setSynth("fallo"))
			self.assertEqual(synth.getSynth().name, "fallo")
			self.assertEqual(synth.fallbackFrom("fallo"), "bueno")
			self.assertEqual(synth.getSynth().name, "bueno")
			# Si el que falla ya no es el actual, no se hace nada.
			self.assertIsNone(synth.fallbackFrom("fallo"))
		finally:
			conf["speech"]["synthPriority"] = oldPriority
			synth.terminate()
			synth.unregisterDriverModule("fallo")
			synth.unregisterDriverModule("bueno")

	def test_stall_detection(self) -> None:
		s = _FailingSynth()
		try:
			self.assertFalse(s.isStalled(1))
			s._busySince = time.monotonic() - 30
			self.assertTrue(s.isStalled(20))
		finally:
			s._busySince = 0.0
			s.terminate()


# ====================================================================== msvcp140
class MsvcRuntimeTests(unittest.TestCase):
	def test_modern_runtime_loaded(self) -> None:
		from tiresias import msvc_runtime

		path = msvc_runtime.loadedPath()
		self.assertIsNotNone(path)
		ver = msvc_runtime.fileVersion(path)
		self.assertIsNotNone(ver)
		# winrt trae una 14.29: la cargada primero debe ser la moderna.
		self.assertNotIn("winrt", path.lower())
		self.assertEqual(msvc_runtime.isModernEnough(), ver[:2] >= msvc_runtime.MIN_VERSION)


# ====================================================================== órdenes
class CommandTests(unittest.TestCase):
	def test_commands_installed(self) -> None:
		from tiresias import global_commands
		from tiresias.baseobject import normalizeGestureId

		cls = global_commands.GlobalCommands
		for name in ("script_audio_showMixer", "script_audio_toggleMicMute", "script_earcons_cycleMode", "script_piper_showVoiceManager"):
			self.assertTrue(hasattr(cls, name), name)
		gestures = cls.__dict__.get("_classGestures") or {}
		self.assertEqual(gestures.get(normalizeGestureId("kb:tiresias+alt+a")), "audio_showMixer")
		self.assertEqual(gestures.get(normalizeGestureId("kb:tiresias+alt+shift+m")), "audio_toggleMicMute")


if __name__ == "__main__":
	unittest.main()
