"""Pruebas del complemento «Voces neuronales de Microsoft» (NeuralVoices) y de la voz Álvaro.

Carga de verdad el Speech SDK de Microsoft con la voz Álvaro (copiada como
complemento instalado en una carpeta de datos temporal) y sintetiza A MEMORIA:
nada se reproduce por los altavoces (el reproductor se sustituye por uno falso).

Ejecutar con:
``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_complemento_neuralvoices -v``
"""

from __future__ import annotations

import array
import importlib
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

STORE = os.path.join(ROOT, "complementos_tienda")
ADDON_DIR = os.path.join(STORE, "NeuralVoices")
VOICE_DIR = os.path.join(STORE, "NeuralVoices-voz-Alvaro")
SYNTH_DIR = os.path.join(ADDON_DIR, "synthDrivers", "neuralvoices")
CORE_DLL = os.path.join(ADDON_DIR, "sdk", "Microsoft.CognitiveServices.Speech.core.dll")
#: La voz Álvaro es un modelo propietario de Microsoft: no está en el repositorio
#: público (se distribuye aparte en la tienda). Sin ella, sus pruebas se saltan.
HAS_VOICE = os.path.isfile(os.path.join(VOICE_DIR, "SynthModel.license"))
NO_VOICE = "Falta la voz Álvaro (complementos_tienda/NeuralVoices-voz-Alvaro): no se incluye en el repositorio"
HAS_SDK = os.path.isfile(CORE_DLL) and HAS_VOICE

if not getattr(paths, "_dataDirForTests", None):
	# Restos de ejecuciones anteriores (las bibliotecas que no se pudieron borrar al salir).
	import glob

	for _old in glob.glob(os.path.join(tempfile.gettempdir(), "tiresias_neuralvoices_*")):
		shutil.rmtree(_old, ignore_errors=True)
	_TMP = tempfile.mkdtemp(prefix="tiresias_neuralvoices_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]
	# Al salir se borra la copia (las bibliotecas del SDK, aún cargadas, pueden quedarse).
	import atexit

	atexit.register(shutil.rmtree, _TMP, True)
else:
	_TMP = paths._dataDirForTests  # type: ignore[attr-defined]

# Los dos complementos, instalados en la carpeta de datos temporal.
_ADDONS = os.path.join(_TMP, "addons")
os.makedirs(_ADDONS, exist_ok=True)
for _src, _name in ((ADDON_DIR, "NeuralVoices"), (VOICE_DIR, "NeuralVoices-voz-Alvaro")):
	_dst = os.path.join(_ADDONS, _name)
	if os.path.isdir(_src) and not os.path.isdir(_dst):
		shutil.copytree(_src, _dst, ignore=shutil.ignore_patterns("__pycache__"))

from tiresias import addons  # noqa: E402
from tiresias import synth as synthHandler  # noqa: E402
from tiresias.speech.commands import (  # noqa: E402
	BreakCommand,
	CharacterModeCommand,
	IndexCommand,
	LangChangeCommand,
	PhonemeCommand,
	PitchCommand,
	RateCommand,
)

addons.loadAll()
PKG = addons.getAddon("NeuralVoices").packageName
nv = importlib.import_module(f"{PKG}.synthDrivers.neuralvoices")
langdet = importlib.import_module(f"{PKG}.synthDrivers.neuralvoices.languageDetection")
scripts = importlib.import_module(f"{PKG}.synthDrivers.neuralvoices.scripts")

ALVARO = "Microsoft Server Speech Text to Speech Voice (es-ES, AlvaroNeural)"


class FakePlayer:
	"""Reproductor falso: guarda el audio y ejecuta las retrollamadas en orden (sin sonido)."""

	def __init__(self) -> None:
		self.items: list = []
		self.volume = 1.0
		self.muted = False
		self.lock = threading.Lock()

	def feed(self, data, onDone=None) -> None:
		with self.lock:
			if data:
				self.items.append(("audio", len(data), data))
			if onDone is not None:
				self.items.append(("cb", onDone, None))

	def run(self) -> None:
		for kind, value, _d in list(self.items):
			if kind == "cb":
				value()

	def audioBytes(self) -> int:
		return sum(v for k, v, _d in self.items if k == "audio")

	def stop(self) -> None:
		with self.lock:
			self.items.clear()

	def pause(self, switch) -> None:
		pass

	def isPlaying(self) -> bool:
		return False

	def terminate(self) -> None:
		pass


def _peak(pcm: bytes) -> int:
	a = array.array("h")
	a.frombytes(pcm[: len(pcm) - len(pcm) % 2])
	return max((abs(x) for x in a), default=0)


# ---------------------------------------------------------------------- sin SDK
class ManifiestosTests(unittest.TestCase):
	def _manifest(self, folder: str) -> dict:
		with open(os.path.join(folder, "manifest.json"), encoding="utf-8-sig") as f:
			return json.load(f)

	def test_manifiesto_controlador(self) -> None:
		m = self._manifest(ADDON_DIR)
		self.assertEqual(m["id"], "NeuralVoices")
		self.assertEqual(m["name"], "Voces neuronales de Microsoft")
		self.assertEqual(m["version"], "1.0.0")
		self.assertIn("Kvark", m["author"])
		for key in ("description", "minApiVersion", "lastTestedApiVersion", "url", "changelog"):
			self.assertTrue(m.get(key), key)
		self.assertTrue(os.path.isfile(os.path.join(ADDON_DIR, "doc", "es", "readme.html")))
		self.assertTrue(os.path.isfile(os.path.join(ADDON_DIR, "sdk", "LICENCIA_SPEECH_SDK.txt")))
		# Envoltorio propio: ni cffi ni el módulo original.
		for root, _dirs, files in os.walk(ADDON_DIR):
			self.assertNotIn("speechapi_cffi.py", files)
			for fn in files:
				self.assertFalse(fn.endswith(".pyd"), fn)
				if fn.endswith(".py"):
					with open(os.path.join(root, fn), encoding="utf-8") as f:
						self.assertNotIn("import cffi", f.read())

	@unittest.skipUnless(HAS_VOICE, NO_VOICE)
	def test_manifiesto_voz(self) -> None:
		m = self._manifest(VOICE_DIR)
		self.assertEqual(m["id"], "NeuralVoices-voz-Alvaro")
		self.assertEqual(m["name"], "Voz neuronal Álvaro (español de España)")
		self.assertIs(m["proprietary"], True)
		self.assertIn("Voces neuronales de Microsoft", m["description"])
		self.assertIn("propiedad de Microsoft", m["description"])
		self.assertTrue(os.path.isfile(os.path.join(VOICE_DIR, "data", "es-ES-AlvaroNeural", "Tokens.xml")))
		# Sin código.
		for _root, _dirs, files in os.walk(VOICE_DIR):
			for fn in files:
				self.assertFalse(fn.endswith((".py", ".pyc", ".dll")), fn)

	@unittest.skipUnless(HAS_VOICE, NO_VOICE)
	def test_licencia_sin_modificar(self) -> None:
		# La licencia original, si la voz está instalada en NVDA (carpeta de complementos de NVDA).
		original = os.path.join(os.environ.get("APPDATA", ""), "nvda", "addons", "NeuralVoices-voice-Alvaro-Natural-Spanish-Spain", "SynthModel.license")
		with open(os.path.join(VOICE_DIR, "SynthModel.license"), "rb") as f:
			data = f.read()
		self.assertTrue(data.startswith(b"This model and the software may not be used"))
		if os.path.isfile(original):
			with open(original, "rb") as f:
				self.assertEqual(f.read(), data)

	def test_complementos_cargados(self) -> None:
		ids = {a.id for a in addons.getAddons()}
		self.assertIn("NeuralVoices", ids)
		if HAS_VOICE:
			self.assertIn("NeuralVoices-voz-Alvaro", ids)
		self.assertIn("neuralvoices", synthHandler.getDriverNames())


class EscriturasTests(unittest.TestCase):
	def test_escritura_de_caracteres(self) -> None:
		self.assertEqual(scripts.scriptOf(ord("a")), "Latin")
		self.assertEqual(scripts.scriptOf(ord("ñ")), "Latin")
		self.assertEqual(scripts.scriptOf(ord("я")), "Cyrillic")
		self.assertEqual(scripts.scriptOf(ord("中")), "Han")
		self.assertEqual(scripts.scriptOf(ord("あ")), "Hiragana")
		self.assertEqual(scripts.scriptOf(ord("א")), "Hebrew")
		self.assertEqual(scripts.scriptOf(ord("1")), "Common")
		self.assertEqual(scripts.scriptOf(ord(" ")), "Common")
		self.assertIsNone(scripts.scriptOf(0x10FFFF))

	def _detect(self, seq, default="es", ignoreNumbers=False, latin="es"):
		langs = dict(langdet.DEFAULT_SCRIPT_LANGUAGES, Latin=latin)
		out = []
		for item in langdet.addDetectedLanguageCommands(seq, default, langs, ignoreNumbers):
			out.append(("lang", item.lang) if isinstance(item, LangChangeCommand) else item)
		return out

	def test_deteccion_por_escritura(self) -> None:
		out = self._detect(["Hola привет мир 中文"])
		self.assertEqual(out, [("lang", "es"), "Hola ", ("lang", "ru"), "привет мир ", ("lang", "zh"), "中文"])

	def test_numeros(self) -> None:
		# Los números van en el idioma de la voz salvo que se ignoren.
		self.assertEqual(self._detect(["привет 25"]), [("lang", "ru"), "привет ", ("lang", "es"), "25"])
		self.assertEqual(self._detect(["привет 25"], ignoreNumbers=True), [("lang", "ru"), "привет 25"])

	def test_respeta_cambios_de_idioma_y_ordenes(self) -> None:
		idx = IndexCommand(3)
		out = self._detect([LangChangeCommand("en"), "hello", idx, LangChangeCommand(None), "25"], latin="en")
		# Tras LangChangeCommand(None) se vuelve al idioma de la voz (los números, en ese idioma).
		self.assertEqual(out, [("lang", "en"), "hello", idx, ("lang", "es"), "25"])


# ---------------------------------------------------------------------- con el Speech SDK real
@unittest.skipUnless(HAS_SDK, "Faltan las bibliotecas del Speech SDK o la voz Álvaro")
class SintetizadorTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		cls.driver = nv.SynthDriver()
		# Nada se reproduce: el reproductor real se cambia por uno falso.
		cls.driver._player.terminate()
		cls.driver._player = FakePlayer()

	@classmethod
	def tearDownClass(cls) -> None:
		synthHandler._current = None
		cls.driver.terminate()

	def setUp(self) -> None:
		d = self.driver
		d._player = FakePlayer()
		d._voiceSettings.clear()
		d._languageVoices.clear()
		d.setSetting("voice", ALVARO)
		d.setSetting("useUnicodeLanguageDetection", False)

	def test_check_y_lista(self) -> None:
		self.assertTrue(nv.SynthDriver.check())
		self.assertIn("neuralvoices", [n for n, _d in synthHandler.getSynthList()])
		packages = nv.getVoicePackages()
		self.assertEqual(len(packages), 1)
		self.assertTrue(packages[0][0].endswith("SynthModel.license"))
		# Carga como lo hace Tiresias (con los ajustes guardados); no se habla.
		from tiresias.config import conf

		conf["speech"]["synths"]["neuralvoices"] = {"voice": ALVARO, "rate": 60, "voices": {ALVARO: {"rate": 61, "pitch": 50, "volume": 50}}}
		other = synthHandler._instantiate("neuralvoices")
		try:
			self.assertEqual(other.getSetting("rate"), 61)
			self.assertEqual(other._player.volume, 1.0)
		finally:
			other.terminate()
			conf["speech"]["synths"]["neuralvoices"] = {}

	def test_voces(self) -> None:
		voices = self.driver.availableVoices
		self.assertIn(ALVARO, voices)
		v = voices[ALVARO]
		self.assertEqual(v.language, "es_ES")
		self.assertTrue(v.displayName.startswith("Alvaro ("), v.displayName)
		self.assertEqual(self.driver.getSetting("voice"), ALVARO)
		self.assertEqual(self.driver.language, "es_ES")
		ids = [s.id for s in self.driver.supportedSettings]
		self.assertEqual(ids[:6], ["voice", "rate", "pitch", "volume", "useUnicodeLanguageDetection", "ignoreNumbersInLanguageDetection"])
		# Un solo idioma latino instalado: no hay ajuste de idioma latino (como el original).
		self.assertNotIn("latinLanguage", ids)

	def test_sintesis_a_memoria(self) -> None:
		pcm = self.driver.synthesizeToMemory(["Hola, esto es una prueba de las voces neuronales de Microsoft en Tiresias."])
		self.assertGreater(len(pcm), 24000 * 2)  # más de un segundo a 24 kHz
		self.assertEqual(len(pcm) % 2, 0)
		self.assertGreater(_peak(pcm), 1000)
		self.assertEqual(self.driver._player.items, [])  # nada al reproductor

	def test_velocidad_tono_volumen_por_voz(self) -> None:
		d = self.driver
		text = ["Uno, dos, tres, cuatro, cinco, seis, siete."]
		d.setSetting("rate", 50)
		normal = len(d.synthesizeToMemory(text))
		d.setSetting("rate", 90)
		fast = len(d.synthesizeToMemory(text))
		self.assertLess(fast, normal * 0.8)
		d.setSetting("rate", 50)
		d.setSetting("volume", 10)
		quiet = _peak(d.synthesizeToMemory(text))
		d.setSetting("volume", 50)
		loud = _peak(d.synthesizeToMemory(text))
		self.assertLess(quiet, loud)
		d.setSetting("pitch", 70)
		self.assertEqual(d.getSetting("pitch"), 70)
		self.assertEqual(d.voiceSettings(ALVARO).pitch, 70)
		saved = d.saveableSettings()
		self.assertEqual(saved["voices"][ALVARO], {"rate": 50, "pitch": 70, "volume": 50})
		# Al cargar mandan los valores de la voz.
		d._voiceSettings.clear()
		d.loadSettings({"voice": ALVARO, "rate": 20, "voices": {ALVARO: {"rate": 33, "pitch": 44, "volume": 55}}})
		self.assertEqual((d.getSetting("rate"), d.getSetting("pitch"), d.getSetting("volume")), (33, 44, 55))
		# Sin «voices» (p. ej. configuración importada) se usan los generales.
		d._voiceSettings.clear()
		d.loadSettings({"voice": ALVARO, "rate": 20, "pitch": 30, "volume": 40})
		self.assertEqual((d.getSetting("rate"), d.getSetting("pitch"), d.getSetting("volume")), (20, 30, 40))

	def test_ssml(self) -> None:
		d = self.driver
		ssml, indexes, hasText = d.buildSsml(
			d.currentVoice,
			["a < b & c\x01", IndexCommand(5), BreakCommand(300), CharacterModeCommand(True), "xy", CharacterModeCommand(False), PitchCommand(offset=20), PhonemeCommand("ˈxola", "hola"), RateCommand(multiplier=0.5)],
		)
		self.assertTrue(hasText)
		self.assertEqual(indexes, [5])
		self.assertIn("a &lt; b &amp; c ", ssml)
		self.assertIn('<mark name="5"/>', ssml)
		self.assertIn('<break time="300ms"/>', ssml)
		self.assertIn('<say-as interpret-as="characters">xy</say-as>', ssml)
		self.assertIn('<prosody rate="+50%" pitch="+0%" volume="+0%">', ssml)
		self.assertIn('pitch="+40%"', ssml)
		self.assertIn('<phoneme alphabet="ipa" ph="ˈxola">hola</phoneme>', ssml)
		self.assertIn('rate="-25%"', ssml)
		self.assertTrue(ssml.startswith('<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="es-ES">'))
		# El motor acepta este SSML (sin error de SSML).
		pcm = d.synthesizeToMemory(["a < b & c\x01", BreakCommand(300), CharacterModeCommand(True), "xy", CharacterModeCommand(False), PhonemeCommand("ˈxola", "hola")])
		self.assertGreater(len(pcm), 10000)

	def test_indices_y_pausas_con_reproductor_falso(self) -> None:
		d = self.driver
		reached: list[int] = []
		d._notifyIndex = reached.append  # type: ignore[method-assign]
		try:
			gen = d._generation
			seq = ["Primera frase del texto.", IndexCommand(1), "Segunda frase,", BreakCommand(400), "algo más larga.", IndexCommand(2), "Fin.", IndexCommand(3)]
			d._processSequence(gen, seq)
			player = d._player
			kinds = [k for k, _v, _d in player.items]
			self.assertEqual(kinds.count("cb"), 3)
			# Los índices están entre trozos de audio, en orden.
			first = kinds.index("cb")
			self.assertGreater(first, 0)
			self.assertIn("audio", kinds[first:])
			self.assertEqual(kinds[-1], "cb")
			player.run()
			self.assertEqual(reached, [1, 2, 3])
			self.assertGreater(player.audioBytes(), 48000)
			# Con la pausa el audio es más largo.
			d._player = FakePlayer()
			d._processSequence(gen, ["Segunda frase,", BreakCommand(1500), "algo más larga."])
			withBreak = d._player.audioBytes()
			d._player = FakePlayer()
			d._processSequence(gen, ["Segunda frase,", "algo más larga."])
			self.assertGreater(withBreak, d._player.audioBytes() + 48000)
			# Índices sin texto: se cumplen igualmente.
			reached.clear()
			d._player = FakePlayer()
			d._processSequence(gen, [IndexCommand(9)])
			d._player.run()
			self.assertEqual(reached, [9])
		finally:
			del d._notifyIndex

	def test_cancelar(self) -> None:
		d = self.driver
		gen = d._generation
		long_text = " ".join(["Esta es una frase bastante larga para que la síntesis dure un rato."] * 40)
		t = threading.Thread(target=d._processSequence, args=(gen, [long_text, IndexCommand(1)]))
		t.start()
		import time

		time.sleep(0.05)
		d._generation += 1
		d._cancelSynthesis()
		t.join(10)
		self.assertFalse(t.is_alive())
		# Tras cancelar sigue funcionando.
		self.assertGreater(len(d.synthesizeToMemory(["Otra vez."])), 4000)

	def test_cambio_de_idioma_y_voz_por_idioma(self) -> None:
		d = self.driver
		self.assertIs(d.getVoiceForLanguage("es"), d.currentVoice)
		self.assertIs(d.getVoiceForLanguage("es_MX"), d.currentVoice)
		self.assertIs(d.getVoiceForLanguage("es-ES"), d.currentVoice)
		self.assertIsNone(d.getVoiceForLanguage("en"))
		self.assertEqual(d.languagesForMapping(), ["es-ES", "es"])
		# Idioma sin voz: no se cambia nada y la secuencia queda en un solo tramo.
		runs = d.splitByVoice(["hola", LangChangeCommand("en"), "hello", LangChangeCommand(None), "adiós"])
		self.assertEqual(len(runs), 1)
		self.assertEqual(runs[0][1], ["hola", "hello", "adiós"])
		d.setLanguageVoices({"es": ALVARO, "xx": "no existe"})
		self.assertEqual(d.getLanguageVoices(), {"es": ALVARO})
		self.assertEqual(d.saveableSettings()["languages"], {"es": {"voice": ALVARO}})
		d.setLanguageVoices({"es": None})
		self.assertEqual(d.getLanguageVoices(), {})
		# Con la detección por escritura activada, el texto cirílico sin voz rusa sigue con Álvaro.
		d.setSetting("useUnicodeLanguageDetection", True)
		self.assertGreater(len(d.synthesizeToMemory(["Hola привет"])), 10000)

	def test_complemento_global(self) -> None:
		from tiresias import gui
		from tiresias.gui import settings as S

		plugin = importlib.import_module(f"{PKG}.globalPlugins.neuralvoices_opciones")
		synthHandler._current = None
		snap = plugin.snapshot()
		self.assertFalse(snap["active"])
		self.assertIn("Voces neuronales de Microsoft", plugin.notActiveMessage("eSpeak NG"))
		synthHandler._current = self.driver
		try:
			snap = plugin.snapshot()
			self.assertTrue(snap["active"])
			self.assertIn(ALVARO, [vid for vid, _l in snap["voices"]])
			self.assertEqual([c for c, _l in snap["langs"]], ["es-ES", "es"])
			self.assertTrue(plugin.applyMapping({"es-ES": ALVARO}))
			self.assertEqual(self.driver.getLanguageVoices(), {"es-ES": ALVARO})
			from tiresias.config import conf

			self.assertEqual(conf["speech"]["synths"]["neuralvoices"]["languages"]["es-ES"]["voice"], ALVARO)
			gp = plugin.GlobalPlugin()
			try:
				self.assertIn(plugin.MENU_ID, gui._addonToolsEntries)
				self.assertIn(plugin.PANEL_ID, S._panels)
				fn = plugin.GlobalPlugin.script_vozPorIdioma
				self.assertTrue(fn.__doc__)
				self.assertEqual(fn.category, "Voces neuronales de Microsoft")
				self.assertEqual(fn.gestures, [])
			finally:
				gp.terminate()
			self.assertNotIn(plugin.MENU_ID, gui._addonToolsEntries)
			self.assertNotIn(plugin.PANEL_ID, S._panels)
		finally:
			synthHandler._current = None
			self.driver.setLanguageVoices({"es-ES": None})

	def test_dialogo_y_panel(self) -> None:
		"""Crea el diálogo y la categoría de Opciones sin mostrarlos."""
		import wx

		plugin = importlib.import_module(f"{PKG}.globalPlugins.neuralvoices_opciones")
		app = wx.App.Get() or wx.App(False)
		synthHandler._current = self.driver
		try:
			snap = plugin.snapshot()
		finally:
			synthHandler._current = None
		frame = wx.Frame(None)
		try:
			dlg = plugin._dialogClass()(frame, snap)
			ed = dlg.editor
			self.assertEqual(ed.langChoice.GetCount(), 2)
			self.assertEqual(ed.voiceChoice.GetString(0), plugin.AUTOMATIC)
			self.assertEqual(ed.voiceChoice.GetSelection(), 0)
			# Se elige Álvaro para «es» (segunda fila de idiomas).
			ed.langChoice.SetSelection(1)
			ed._showVoiceForLang()
			ed.voiceChoice.SetSelection(1)
			evt = wx.CommandEvent(wx.wxEVT_CHOICE)
			ed._onVoiceChoice(evt)
			self.assertEqual(ed.changes(), {"es": ALVARO})
			ed.resetAll()
			self.assertEqual(ed.changes(), {})
			dlg.Destroy()
			panelCls = plugin._panelClass()
			panel = panelCls(frame)
			panel._onSnapshot({"active": False, "description": "eSpeak NG"})
			self.assertIsNone(panel.editor)
			panel2 = panelCls(frame)
			panel2._onSnapshot(snap)
			self.assertIsNotNone(panel2.editor)
			panel2.editor.mapping["es-ES"] = ALVARO
			applied = []
			old = plugin.queueApply
			plugin.queueApply = applied.append
			try:
				panel2.onSave()
			finally:
				plugin.queueApply = old
			self.assertEqual(applied, [{"es-ES": ALVARO}])
		finally:
			frame.Destroy()
			del app


if __name__ == "__main__":
	unittest.main()
