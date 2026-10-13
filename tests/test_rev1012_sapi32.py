"""Revisión 1.0.12: voces SAPI 5 de 32 bits y SAPI 4 con el auxiliar de 32 bits.

Sin sonido por los altavoces: el reproductor de los controladores se cambia
por uno que guarda el audio en memoria. Las pruebas «reales» usan el auxiliar
compilado (``data/synthDrivers/sapi32/tiresiasSapi32.exe``) y las voces SAPI 5
de 32 bits instaladas en el equipo; si faltan, se omiten. No se cambia la
configuración de voz del usuario ni el registro.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev1012_sapi32``
"""

from __future__ import annotations

import io
import os
import shutil
import struct
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_rev1012_sapi32_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]

from tiresias import synth as synthHandler  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.speech.commands import (  # noqa: E402
	BreakCommand,
	CharacterModeCommand,
	IndexCommand,
	LangChangeCommand,
	PitchCommand,
	RateCommand,
	VolumeCommand,
)
from tiresias.synth import _sapi32host as host32  # noqa: E402
from tiresias.synth import base, sapi4, sapi5_32  # noqa: E402

try:
	import numpy
except ImportError:  # pragma: no cover
	numpy = None


class MemoryPlayer:
	"""Reproductor falso: guarda el audio y llama a las retrollamadas al momento."""

	def __init__(self, *args, **kwargs) -> None:
		self.lock = threading.Lock()
		self.data: list[bytes] = []
		self.volume = 1.0
		self.stops = 0

	def feed(self, data, onDone=None) -> None:
		with self.lock:
			if data:
				self.data.append(bytes(data))
		if onDone is not None:
			onDone()

	def audio(self) -> bytes:
		with self.lock:
			return b"".join(self.data)

	def clear(self) -> None:
		with self.lock:
			self.data.clear()

	def queuedSeconds(self) -> float:
		return 0.0

	def isPaused(self) -> bool:
		return False

	def stop(self) -> None:
		self.stops += 1

	def pause(self, switch: bool) -> None:
		pass

	def terminate(self) -> None:
		pass


def _frame(kind: str, payload: bytes = b"") -> bytes:
	return struct.pack("<IB", len(payload) + 1, ord(kind)) + payload


class FakeProc:
	"""Proceso falso con respuestas grabadas para probar el protocolo."""

	def __init__(self, responses: bytes) -> None:
		self.stdin = io.BytesIO()
		self.stdout = io.BytesIO(responses)
		self.pid = 4242
		self.killed = False

	def poll(self):
		return 0 if self.killed else None

	def wait(self, timeout=None):
		return 0

	def kill(self) -> None:
		self.killed = True


def _synthListOf(*names: str) -> list[str]:
	"""``getSynthList`` limitado a unos controladores (sin cargar SAPI 5 de 64 bits en este hilo)."""
	old = synthHandler.getDriverNames
	synthHandler.getDriverNames = lambda: list(names)
	try:
		return [n for n, _d in synthHandler.getSynthList()]
	finally:
		synthHandler.getDriverNames = old


def _waitIdle(s: base.AudioSynthDriver, timeout: float = 20.0) -> bool:
	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		if s._queue.empty() and not s._busySince:
			time.sleep(0.05)
			if s._queue.empty() and not s._busySince:
				return True
		time.sleep(0.02)
	return False


def _peak(pcm: bytes) -> int:
	import array

	a = array.array("h")
	a.frombytes(pcm[: len(pcm) - len(pcm) % 2])
	return max((abs(v) for v in a), default=0)


def _f0(pcm: bytes, sr: int = 22050) -> float:
	"""Tono fundamental (mediana) por autocorrelación de los tramos sonoros."""
	x = numpy.frombuffer(pcm[: len(pcm) - len(pcm) % 2], dtype=numpy.int16).astype(float)
	found = []
	lo, hi = sr // 400, sr // 60
	for i in range(0, len(x) - 1024, 512):
		fr = x[i : i + 1024]
		if numpy.abs(fr).mean() < 800:
			continue
		fr = fr - fr.mean()
		ac = numpy.correlate(fr, fr, "full")[1023:]
		k = lo + int(numpy.argmax(ac[lo:hi]))
		if ac[k] > 0.3 * ac[0]:
			found.append(sr / k)
	return float(numpy.median(found)) if found else 0.0


# ====================================================================== sin auxiliar
class TestRegistroYOrden(unittest.TestCase):
	def test_orden_automatico_no_cambia(self) -> None:
		names = list(synthHandler.BUILTIN_DRIVERS)
		self.assertIn("sapi5_32", names)
		self.assertIn("sapi4", names)
		# Los anteriores conservan su orden y los nuevos van detrás (antes del silencio).
		self.assertEqual([n for n in names if n not in ("sapi5_32", "sapi4")], ["espeak", "onecore", "sapi5", "piper", "silence"])
		self.assertGreater(names.index("sapi5_32"), names.index("piper"))
		self.assertGreater(names.index("sapi4"), names.index("piper"))
		self.assertEqual(names[-1], "silence")
		self.assertEqual(list(conf["speech"]["synthPriority"])[:4], ["ibmtts", "espeak", "onecore", "sapi5"])
		order = synthHandler._fallbackOrder("nada")
		self.assertLess(order.index("piper"), order.index("sapi5_32"))

	def test_clases_y_descripciones(self) -> None:
		self.assertEqual(synthHandler._getDriverClass("sapi5_32").name, "sapi5_32")
		self.assertEqual(synthHandler._getDriverClass("sapi4").name, "sapi4")
		self.assertEqual(sapi5_32.SynthDriver.description, "Microsoft Speech API versión 5 (32 bits)")
		self.assertEqual(sapi4.SynthDriver.description, "Microsoft Speech API versión 4")

	def test_sin_ejecutable_no_disponibles(self) -> None:
		old = host32.hostPath
		missing = os.path.join(tempfile.gettempdir(), "no_existe_tiresiasSapi32.exe")
		try:
			host32.hostPath = lambda: missing
			sapi5_32.hostPath = host32.hostPath
			sapi4.hostPath = host32.hostPath
			self.assertFalse(sapi5_32.SynthDriver.check())
			self.assertFalse(sapi4.SynthDriver.check())
		finally:
			host32.hostPath = old
			sapi5_32.hostPath = old
			sapi4.hostPath = old

	def test_sapi4_restos_de_motores_desinstalados(self) -> None:
		saved = (host32._clsidRegistered32, host32._keyExists32, host32._subkeys32)
		try:
			host32._keyExists32 = lambda root, path: True
			host32._subkeys32 = lambda root, path: ["{1B6BF820-9299-101B-8A19-265D428C60FF}"]
			host32._clsidRegistered32 = lambda clsid: clsid == host32.CLSID_TTS_ENUMERATOR
			self.assertIs(host32.sapi4Registry(), False)
			host32._clsidRegistered32 = lambda clsid: True
			self.assertIs(host32.sapi4Registry(), True)
			host32._keyExists32 = lambda root, path: False
			self.assertIsNone(host32.sapi4Registry())
			host32._clsidRegistered32 = lambda clsid: False
			self.assertIs(host32.sapi4Registry(), False)
		finally:
			host32._clsidRegistered32, host32._keyExists32, host32._subkeys32 = saved


class TestTextoSapi4(unittest.TestCase):
	def _driver(self, ranges: dict) -> sapi4.SynthDriver:
		d = sapi4.SynthDriver.__new__(sapi4.SynthDriver)
		d._settings = {"rate": 50, "pitch": 50, "volume": 100}
		d._ranges = ranges
		return d

	def test_margenes(self) -> None:
		self.assertEqual(sapi4.parseRanges("rate=10,300,150;pitch=50,200,100;volume=0,65535;"), {"rate": (10, 300, 150), "pitch": (50, 200, 100), "volume": (0, 65535)})
		self.assertEqual(sapi4.parseRanges("rate=5,5,5;basura;pitch=x,y"), {})
		self.assertEqual(sapi4.percentToParam(0, 10, 310), 10)
		self.assertEqual(sapi4.percentToParam(50, 10, 310), 160)
		self.assertEqual(sapi4.percentToParam(150, 10, 310), 310)

	def test_etiquetas(self) -> None:
		d = self._driver({"rate": (0, 200, 100), "pitch": (0, 100, 50), "volume": (0, 65535)})
		text, rate, pitch = d._buildRequest(["a\\b", CharacterModeCommand(True), "x", BreakCommand(300), RateCommand(offset=20), "c", PitchCommand(offset=-10), VolumeCommand(multiplier=0.5), "d"])
		self.assertEqual((rate, pitch), (100, 50))
		self.assertTrue(text.startswith("a\\\\b\\RmS=1\\x\\Pau=300\\\\Spd=140\\c\\Pit=40\\"), text)
		self.assertIn("\\Vol=32768\\d", text)
		# Al final se vuelve a la prosodia normal y se sale del deletreo.
		self.assertTrue(text.endswith("\\Spd=100\\\\Pit=50\\\\Vol=65535\\\\RmS=0\\"), text)

	def test_sin_margenes_sin_etiquetas(self) -> None:
		d = self._driver({})
		text, rate, pitch = d._buildRequest(["hola", RateCommand(offset=20), "adiós", LangChangeCommand("en")])
		self.assertEqual(text, "holaadiós")
		self.assertIsNone(rate)
		self.assertIsNone(pitch)


class TestXmlSapi5_32(unittest.TestCase):
	def _driver(self, rate: int) -> sapi5_32.SynthDriver:
		d = sapi5_32.SynthDriver.__new__(sapi5_32.SynthDriver)
		d._settings = {"rate": rate, "pitch": 50, "volume": 100, "voice": "v"}
		d._voices = {}
		return d

	def test_velocidad_base_fuera_del_xml(self) -> None:
		d = self._driver(80)
		xml, rate, pitch = d._buildRequest(["hola", RateCommand(offset=10), "rápido"])
		self.assertEqual(rate, 6)
		self.assertIsNone(pitch)
		# Sin velocidad base en el XML; el cambio interior es relativo a la base (+10 % = +2).
		self.assertTrue(xml.startswith('<pitch absmiddle="0">hola<rate absspeed="2">'), xml)
		self.assertIn("rápido", xml)
		self.assertEqual(d._settings["rate"], 80)

	def test_escapado_xml(self) -> None:
		xml, _r, _p = self._driver(50)._buildRequest(["a < b & c"])
		self.assertIn("a &lt; b &amp; c", xml)


class TestProtocolo(unittest.TestCase):
	def _host(self, responses: bytes) -> tuple[host32.HostProcess, list]:
		procs: list = []

		def launcher(cmd, **kwargs):
			procs.append((cmd, kwargs))
			p = FakeProc(responses)
			procs.append(p)
			return p

		exe = sys.executable  # cualquier archivo que exista
		h = host32.HostProcess("sapi5", exe=exe, launcher=launcher)
		return h, procs

	def test_conversacion(self) -> None:
		hello = _frame("h", b"mode=sapi5;protocol=1;rate=22050;bits=16;channels=1")
		voices = _frame("l", b"id1\tVoz uno\tC0A\t\nid2\tVoz dos\t409\t\n")
		audio = _frame("a", struct.pack("<I", 7) + b"viejo") + _frame("a", struct.pack("<I", 1) + b"\x01\x02") + _frame("a", struct.pack("<I", 1) + b"\x03\x04") + _frame("d", struct.pack("<IiB", 1, 0, 0))
		h, procs = self._host(hello + voices + audio)
		h.start()
		cmd, kwargs = procs[0]
		self.assertEqual(cmd[1:3], ["sapi5", "--parent"])
		self.assertEqual(kwargs["creationflags"], host32.CREATE_NO_WINDOW)
		self.assertEqual(h.info["rate"], "22050")
		self.assertEqual(h.listVoices(), [("id1", "Voz uno", "C0A", ""), ("id2", "Voz dos", "409", "")])
		got: list[bytes] = []
		self.assertTrue(h.speak(1, "<x/>", got.append, lambda: False, rate=-3))
		# Solo el audio del enunciado pedido (el «viejo» es de uno cancelado).
		self.assertEqual(got, [b"\x01\x02", b"\x03\x04"])
		sent = procs[1].stdin.getvalue()
		# H, L y S: la última petición lleva el número, las banderas y la velocidad (-3).
		sIndex = sent.rfind(struct.pack("<IB", 1 + 16 + len(b"<x/>"), ord("S")))
		self.assertGreaterEqual(sIndex, 0)
		seq, flags, rate, pitch = struct.unpack_from("<IIIi", sent, sIndex + 5)
		self.assertEqual((seq, flags, rate, pitch), (1, host32.FLAG_RATE, (-3) & 0xFFFFFFFF, 0))
		# Fin de la salida: el auxiliar ha muerto.
		with self.assertRaises(host32.HostError):
			h.speak(2, "x", got.append, lambda: False)

	def test_error_del_motor(self) -> None:
		hello = _frame("h", b"mode=sapi5;protocol=1")
		done = _frame("d", struct.pack("<IiB", 1, -2147467259, 0))
		h, _procs = self._host(hello + done)
		h.start()
		with self.assertRaises(host32.HostError):
			h.speak(1, "x", lambda d: None, lambda: False)

	def test_version_incompatible(self) -> None:
		h, procs = self._host(_frame("h", b"mode=sapi4;protocol=1"))
		with self.assertRaises(host32.HostError):
			h.start()
		self.assertTrue(procs[1].killed)


# ====================================================================== con el auxiliar y voces reales
def _realAvailable() -> bool:
	try:
		return os.path.isfile(host32.hostPath()) and host32.sapi5Registry32()
	except Exception:
		return False


def _pick(voices, *suffixes) -> str | None:
	for suf in suffixes:
		for key in voices:
			if key.upper().endswith(suf.upper()):
				return key
	return None


@unittest.skipUnless(_realAvailable(), "Falta el auxiliar de 32 bits o no hay voces SAPI 5 de 32 bits")
class TestSapi5_32Real(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		cls._oldPlayer = base.WavePlayer
		base.WavePlayer = MemoryPlayer
		cls._oldTrim = conf["speech"]["trimLeadingSilence"]
		conf["speech"]["trimLeadingSilence"] = False
		cls.synth = sapi5_32.SynthDriver()
		cls.eloq = _pick(cls.synth.availableVoices, "ETIEloq_ESP")
		cls.helena = _pick(cls.synth.availableVoices, "TTS_MS_ES-ES_HELENA_11.0")

	@classmethod
	def tearDownClass(cls) -> None:
		try:
			cls.synth.terminate()
		finally:
			base.WavePlayer = cls._oldPlayer
			conf["speech"]["trimLeadingSilence"] = cls._oldTrim

	def setUp(self) -> None:
		s = self.synth
		s.cancel()
		_waitIdle(s)
		s.setSetting("rate", 50)
		s.setSetting("pitch", 50)
		s.setSetting("rateBoost", False)
		s._player.clear()

	def say(self, seq, voice: str | None = None) -> bytes:
		s = self.synth
		if voice:
			s.setSetting("voice", voice)
		s._player.clear()
		s.speak(list(seq))
		self.assertTrue(_waitIdle(s), "el sintetizador no terminó")
		return s._player.audio()

	def test_enumera_voces_de_32_bits(self) -> None:
		voices = self.synth.availableVoices
		self.assertTrue(self.eloq or self.helena, list(voices))
		for key in filter(None, (self.eloq, self.helena)):
			self.assertEqual(voices[key].language, "es_ES")
		self.assertTrue(sapi5_32.SynthDriver.check())
		names = _synthListOf("sapi5_32", "sapi4")
		self.assertIn("sapi5_32", names)

	def test_sintetiza_a_memoria(self) -> None:
		for voice in filter(None, (self.eloq, self.helena)):
			pcm = self.say(["Hola, esta es la voz de treinta y dos bits."], voice)
			self.assertGreater(len(pcm), 22050, voice)  # más de medio segundo
			self.assertGreater(_peak(pcm), 2000, voice)

	def test_indices_y_fin(self) -> None:
		reached: list[int] = []
		done: list[bool] = []

		def onIndex(synth=None, index=None):
			if synth is self.synth:
				reached.append(index)

		def onDone(synth=None):
			if synth is self.synth:
				done.append(True)

		base.synthIndexReached.register(onIndex)
		base.synthDoneSpeaking.register(onDone)
		try:
			pcm = self.say(["Uno.", IndexCommand(11), "Dos.", IndexCommand(12)], self.helena or self.eloq)
		finally:
			base.synthIndexReached.unregister(onIndex)
			base.synthDoneSpeaking.unregister(onDone)
		self.assertGreater(len(pcm), 0)
		self.assertEqual(reached, [11, 12])
		self.assertTrue(done)

	def test_cancelacion_corta(self) -> None:
		s = self.synth
		voice = self.helena or self.eloq
		s.setSetting("voice", voice)
		s.setSetting("rate", 20)
		texto = " ".join(f"Esta es la frase número {i} de un texto muy largo que no debe terminar de sonar." for i in range(30))
		s._player.clear()
		s.speak([texto])
		deadline = time.monotonic() + 10
		while not s._player.data and time.monotonic() < deadline:
			time.sleep(0.005)
		self.assertTrue(s._player.data, "no llegó audio")
		t0 = time.monotonic()
		s.cancel()
		before = len(s._player.audio())
		self.assertTrue(_waitIdle(s, 5))
		elapsed = time.monotonic() - t0
		time.sleep(0.3)
		after = len(s._player.audio())
		self.assertLess(elapsed, 1.5)
		self.assertEqual(after, before, "siguió llegando audio tras callar")
		# Mucho menos que el texto entero (30 frases a velocidad lenta: más de un minuto).
		self.assertLess(after, 22050 * 2 * 30)
		# Y sigue hablando después.
		s.setSetting("rate", 50)
		self.assertGreater(len(self.say(["Sigo aquí."])), 0)

	def test_velocidad_cambia_el_audio(self) -> None:
		text = ["Esta es una frase de prueba para medir la velocidad de la voz."]
		for voice in filter(None, (self.eloq, self.helena)):
			self.synth.setSetting("rate", 20)
			slow = len(self.say(text, voice))
			self.synth.setSetting("rate", 80)
			fast = len(self.say(text, voice))
			self.assertGreater(slow, fast * 1.5, f"{voice}: {slow} / {fast}")

	def test_tono_cambia_el_audio(self) -> None:
		text = ["Esta es una frase de prueba para medir el tono de la voz."]
		for voice in filter(None, (self.eloq, self.helena)):
			self.synth.setSetting("pitch", 10)
			low = self.say(text, voice)
			self.synth.setSetting("pitch", 90)
			high = self.say(text, voice)
			self.assertNotEqual(low, high, voice)
		if self.helena and numpy is not None:
			self.synth.setSetting("pitch", 10)
			low = _f0(self.say(text, self.helena))
			self.synth.setSetting("pitch", 90)
			high = _f0(self.say(text, self.helena))
			self.assertGreater(high, low * 1.2, f"tono {low:.0f} Hz -> {high:.0f} Hz")

	def test_aumento_de_velocidad(self) -> None:
		voice = self.helena or self.eloq
		self.synth.setSetting("rate", 80)
		normal = len(self.say(["Una frase corta para el aumento de velocidad."], voice))
		self.synth.setSetting("rateBoost", True)
		boosted = len(self.say(["Una frase corta para el aumento de velocidad."], voice))
		self.assertLess(boosted, normal * 0.8)

	def test_cambio_de_idioma(self) -> None:
		voice = self.helena or self.eloq
		self.synth.setSetting("voice", voice)
		xml, _r, _p = self.synth._buildRequest([LangChangeCommand("en_US"), "Hello world"])
		self.assertIn('<lang langid="409">', xml)
		self.assertGreater(len(self.say([LangChangeCommand("en_US"), "Hello world"], voice)), 0)

	def test_auxiliar_muerto_se_recupera(self) -> None:
		s = self.synth
		voice = self.helena or self.eloq
		self.assertGreater(len(self.say(["Antes."], voice)), 0)
		old = s._host
		oldPid = old.pid
		old._proc.kill()
		old._proc.wait(5)
		pcm = self.say(["Después de matar el auxiliar."], voice)
		self.assertGreater(len(pcm), 0)
		self.assertIsNotNone(s._host)
		self.assertNotEqual(s._host.pid, oldPid)
		self.assertEqual(s._errorCount, 0)
		self.assertFalse(s._failed)

	def test_auxiliar_irrecuperable_informa_del_fallo(self) -> None:
		s = sapi5_32.SynthDriver()
		failures: list = []

		def onFailed(synth=None, error=None):
			if synth is s:
				failures.append(error)

		oldFallback = conf["speech"]["synthFallback"]
		conf["speech"]["synthFallback"] = False  # sin cambiar de sintetizador de verdad
		base.synthFailed.register(onFailed)
		oldPath = host32.hostPath
		try:
			self.assertGreater(len(s._host.listVoices()), 0)
			host32.hostPath = lambda: os.path.join(tempfile.gettempdir(), "no_existe_tiresiasSapi32.exe")
			s._host._proc.kill()
			s._host._proc.wait(5)
			for _i in range(base.MAX_CONSECUTIVE_ERRORS):
				s.speak(["Esto no puede sonar."])
				self.assertTrue(_waitIdle(s))
			self.assertTrue(failures, "no se informó del fallo")
			self.assertIsInstance(failures[0], host32.HostError)
		finally:
			host32.hostPath = oldPath
			base.synthFailed.unregister(onFailed)
			conf["speech"]["synthFallback"] = oldFallback
			s.terminate()

	def test_espera_libera_y_recupera(self) -> None:
		s = self.synth
		proc = s._host._proc
		s.releaseResources()
		self.assertIsNone(s._host)
		self.assertIsNotNone(proc.wait(5))
		s.restoreResources()
		self.assertTrue(s._host.isAlive())
		self.assertGreater(len(self.say(["De vuelta."])), 0)

	def test_terminar_cierra_el_auxiliar(self) -> None:
		s = sapi5_32.SynthDriver()
		proc = s._host._proc
		s.terminate()
		self.assertIsNotNone(proc.wait(5))

	def test_auxiliar_termina_si_tiresias_cierra_la_tuberia(self) -> None:
		h = host32.HostProcess("sapi5")
		h.start()
		h._proc.stdin.close()
		self.assertIsNotNone(h._proc.wait(5))
		h.kill()


@unittest.skipUnless(os.path.isfile(host32.hostPath()), "Falta el auxiliar de 32 bits")
class TestSapi4Real(unittest.TestCase):
	def test_check_sin_fallar(self) -> None:
		host32._probeCache.clear()
		result = sapi4.SynthDriver.check()
		self.assertIsInstance(result, bool)
		if host32.sapi4Registry() is False:
			self.assertFalse(result)

	def test_auxiliar_sapi4_enumera_sin_fallar(self) -> None:
		h = host32.HostProcess("sapi4")
		try:
			h.start()
			self.assertEqual(h.info.get("mode"), "sapi4")
			voices = h.listVoices()
			self.assertIsInstance(voices, list)
			if not voices:
				# Sin motores: hablar falla limpiamente y el auxiliar sigue vivo.
				with self.assertRaises(host32.HostError):
					h.speak(1, "hola", lambda d: None, lambda: False)
				self.assertTrue(h.isAlive())
				self.assertEqual(h.listVoices(), [])
		finally:
			h.stop()

	def test_sin_motores_no_se_puede_cargar(self) -> None:
		if host32.probeVoices("sapi4"):
			self.skipTest("Este equipo tiene motores SAPI 4")
		with self.assertRaises(RuntimeError):
			sapi4.SynthDriver()
		self.assertNotIn("sapi4", _synthListOf("sapi5_32", "sapi4"))


# ====================================================================== SAPI 5 de 64 bits: velocidad en la voz
class TestVelocidadSapi5_64(unittest.TestCase):
	"""La velocidad base va en la voz (ISpVoice::SetRate): Eloquence SAPI 5 no atiende <rate> en el XML."""

	def _driver(self, rate: int):
		from tiresias.synth import sapi5

		d = sapi5.SynthDriver.__new__(sapi5.SynthDriver)
		d._settings = {"rate": rate, "pitch": 50, "voice": "", "rateBoost": False}
		return d

	def test_xml_sin_velocidad_base(self) -> None:
		xml = self._driver(80)._buildXml(["hola", RateCommand(offset=10), "rápido"])
		self.assertTrue(xml.startswith('<pitch absmiddle="0">hola<rate absspeed="2">'), xml)
		self.assertNotIn('absspeed="6"', xml)
		xml = self._driver(30)._buildXml(["hola"])
		self.assertNotIn("<rate", xml)

	def test_velocidad_en_la_voz(self) -> None:
		import comtypes.client

		from tiresias.synth import sapi5

		class Voice:
			Rate = None
			AudioOutputStream = None

			def __init__(self) -> None:
				self.spoken = []

			def Speak(self, text, flags):  # noqa: N802
				self.spoken.append((text, self.Rate))

			def WaitUntilDone(self, ms):  # noqa: N802
				return True

		class Stream:
			Format = None

			def GetData(self):  # noqa: N802
				return b""

		old = comtypes.client.CreateObject
		comtypes.client.CreateObject = lambda *a, **k: Stream()
		self.addCleanup(setattr, comtypes.client, "CreateObject", old)
		for rate, expected in ((20, -6), (50, 0), (80, 6), (100, 10), (0, -10)):
			d = self._driver(rate)
			d._voice = Voice()
			d._voiceDirty = False
			d._fmt = None
			d._synthesizeSegment(["hola"], lambda data: None, lambda: False)
			self.assertEqual(d._voice.spoken[0][1], expected, rate)
			self.assertEqual(sapi5.sapiRate(rate), expected)


# ====================================================================== importar de NVDA
VOICE32 = r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\Voices\Tokens\ETIEloq_ESP"
NVDA_INI_SAPI32 = (
	"[speech]\n"
	"\tsynth = sapi5_32\n"
	"\t[[sapi5_32]]\n"
	"\t\tvoice = " + VOICE32 + "\n"
	"\t\trate = 70\n"
	"\t\tpitch = 40\n"
	"\t\tvolume = 90\n"
	"\t\trateBoost = True\n"
	"\t[[sapi4]]\n"
	"\t\tvoice = {11111111-2222-3333-4444-555555555555}\n"
	"\t\trate = 10\n"
	"\t[[sapi4_32]]\n"
	"\t\tvoice = {abcdef01-2345-6789-abcd-ef0123456789}\n"
	"\t\trate = 30\n"
	"\t\tpitch = 60\n"
	"\t\tvolume = 80\n"
)


class TestImportarNvda(unittest.TestCase):
	def setUp(self) -> None:
		from tests import test_nvda_import as tni

		self.tni = tni
		self.base = tni._Base("run")
		self.base.setUp()
		self.addCleanup(self.base.tearDown)

	def _plan(self, ini: str):
		folder = os.path.join(self.base.tmp, "nvda")
		self.tni._write(os.path.join(folder, "nvda.ini"), ini)
		return self.base.plan(folder)

	def test_sapi5_32_y_sapi4(self) -> None:
		from tiresias import nvda_import as ni

		plan = self._plan(NVDA_INI_SAPI32)
		v = self.base.values(plan)
		notes = self.base.notices(plan)
		self.assertEqual(v[("speech", "synth")], "sapi5_32")
		s32 = {k[3]: val for k, val in v.items() if k[:3] == ("speech", "synths", "sapi5_32")}
		self.assertEqual(s32, {"voice": VOICE32, "rate": 70, "pitch": 40, "volume": 90, "rateBoost": True})
		# Nada va a parar a sapi5 (64 bits).
		self.assertFalse([k for k in v if k[:3] == ("speech", "synths", "sapi5")])
		# SAPI 4: los de «sapi4_32» (NVDA 2026.1), con el GUID en mayúsculas.
		s4 = {k[3]: val for k, val in v.items() if k[:3] == ("speech", "synths", "sapi4")}
		self.assertEqual(s4, {"voice": "{ABCDEF01-2345-6789-ABCD-EF0123456789}", "rate": 30, "pitch": 60, "volume": 80})
		self.assertIn("«sapi4»", notes)
		self.assertEqual(ni.synthDisplayName("sapi5_32"), "Microsoft SAPI 5 (32 bits)")
		self.assertEqual(ni.synthDisplayName("sapi4"), "Microsoft SAPI 4")

	def test_sapi4_activo_manda(self) -> None:
		plan = self._plan(NVDA_INI_SAPI32.replace("synth = sapi5_32", "synth = sapi4"))
		v = self.base.values(plan)
		self.assertEqual(v[("speech", "synth")], "sapi4")
		self.assertEqual(v[("speech", "synths", "sapi4", "voice")], "{11111111-2222-3333-4444-555555555555}")
		self.assertEqual(v[("speech", "synths", "sapi4", "rate")], 10)


if __name__ == "__main__":
	unittest.main()
