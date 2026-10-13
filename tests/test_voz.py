"""Pruebas del núcleo de voz y lectura (sin sintetizador real ni pantalla).

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_voz_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]
else:
	_TMP = paths._dataDirForTests  # type: ignore[attr-defined]
	if not os.path.isdir(os.path.join(_TMP, "symbols")):
		shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))

from tiresias.config import conf  # noqa: E402
from tiresias.speech import api as speech  # noqa: E402
from tiresias.speech import dictionaries, langdetect, languages, numbers, sayall, symbols, verbosity, voice_schemes  # noqa: E402
from tiresias.speech.commands import (  # noqa: E402
	BeepCommand,
	CallbackCommand,
	IndexCommand,
	LangChangeCommand,
	PitchCommand,
	RateCommand,
)


class FakeSynth:
	"""Sintetizador falso: guarda lo que recibe y deja avanzar los índices a mano."""

	name = "fake"
	language = "es_ES"
	availableLanguages = ("es_ES", "en_US", "ru_RU")

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

	def texts(self, i: int = -1) -> str:
		return " ".join(x for x in self.sent[i] if isinstance(x, str))

	def indexes(self, i: int = -1) -> list[int]:
		return [x.index for x in self.sent[i] if isinstance(x, IndexCommand)]


class _SynthTestCase(unittest.TestCase):
	def setUp(self) -> None:
		from tiresias import synth

		self.synth = FakeSynth()
		self._oldSynth = synth._current
		synth._current = self.synth  # type: ignore[assignment]
		languages._supportedCache = None
		speech._manager = None
		self.mgr = speech.getManager()
		conf["speech"]["speechMode"] = "talk"

	def tearDown(self) -> None:
		from tiresias import synth

		self.mgr.cancel()
		synth._current = self._oldSynth
		languages._supportedCache = None

	def reach(self, index: int) -> None:
		self.mgr._indexReached(index)


class PriorityTests(_SynthTestCase):
	def test_normal_queues_one_after_another(self) -> None:
		speech.speak(["uno"])
		speech.speak(["dos"])
		speech.speak(["tres"])
		# Como mucho dos enunciados en el sintetizador a la vez.
		self.assertEqual(len(self.synth.sent), 2)
		self.reach(self.synth.indexes(0)[-1])
		self.assertEqual(len(self.synth.sent), 3)
		self.assertIn("tres", self.synth.texts(2))

	def test_next_goes_before_normal(self) -> None:
		speech.speak(["uno"])
		speech.speak(["dos"])
		speech.speak(["tres"])
		speech.speak(["urgente"], priority=speech.Priority.NEXT)
		self.reach(self.synth.indexes(0)[-1])
		self.reach(self.synth.indexes(1)[-1])
		self.assertIn("urgente", self.synth.texts(-1))

	def test_now_interrupts_and_resumes(self) -> None:
		long = ["Primera frase larga del texto. " * 8, "Segunda parte que debe reanudarse."]
		speech.speak(long)
		first = self.synth.sent[0]
		cancelled = self.synth.cancelled
		speech.speak(["aviso"], priority=speech.Priority.NOW)
		self.assertGreater(self.synth.cancelled, cancelled)
		self.assertIn("aviso", self.synth.texts(-1))
		# Al terminar el aviso se reanuda lo interrumpido.
		self.reach(self.synth.indexes(-1)[-1])
		self.assertIn("Segunda parte", self.synth.texts(-1))
		self.assertIsNot(first, self.synth.sent[-1])

	def test_expired_focus_speech_is_dropped(self) -> None:
		valid = {"ok": True}
		speech.speak(["actual"])
		speech.speak(["foco viejo"], isValid=lambda: valid["ok"])
		speech.speak(["después"])
		valid["ok"] = False
		self.mgr.removeExpired()
		allText = " ".join(self.synth.texts(i) for i in range(len(self.synth.sent)))
		self.reach(self.synth.indexes(0)[-1])
		later = " ".join(self.synth.texts(i) for i in range(len(self.synth.sent)))
		self.assertIn("después", later)
		self.assertNotIn("foco viejo", later.replace(allText, "") if "foco viejo" not in allText else later.split("foco viejo")[-1])

	def test_callbacks_run_in_order(self) -> None:
		calls: list[int] = []
		speech.speak([CallbackCommand(lambda: calls.append(1)), "texto", CallbackCommand(lambda: calls.append(2))])
		for idx in self.synth.indexes(0):
			self.reach(idx)
		self.assertEqual(calls, [1, 2])

	def test_history_origin(self) -> None:
		speech.clearHistory()
		with speech.speechOrigin(speech.ORIGIN_TYPING):
			speech.speak(["hola"])
		speech.speak(["noti"], origin=speech.ORIGIN_NOTIFICATION)
		hist = speech.getHistory()
		self.assertEqual(hist[-2].origin, speech.ORIGIN_TYPING)
		self.assertEqual(hist[-1].origin, speech.ORIGIN_NOTIFICATION)
		path = os.path.join(_TMP, "hist.txt")
		self.assertEqual(speech.exportHistory(path), len(hist))
		with open(path, encoding="utf-8") as f:
			self.assertIn("Notificaciones", f.read())

	def test_excluded_modes(self) -> None:
		conf["speech"]["excludedSpeechModes"] = ["onDemand", "beeps"]
		try:
			self.assertEqual(speech.nextSpeechMode(speech.SpeechMode.talk), speech.SpeechMode.off)
			self.assertEqual(speech.nextSpeechMode(speech.SpeechMode.off), speech.SpeechMode.talk)
		finally:
			conf["speech"]["excludedSpeechModes"] = []

	def test_filter_speech_sequence(self) -> None:
		def f(value):
			return [s.upper() if isinstance(s, str) else s for s in value]

		speech.filter_speechSequence.register(f)
		try:
			speech.speak(["hola"])
		finally:
			speech.filter_speechSequence.unregister(f)
		self.assertIn("HOLA", self.synth.texts(0))


class LanguageTests(_SynthTestCase):
	def test_script_detection_switches(self) -> None:
		conf["speech"]["languageDetection"] = "script"
		speech.speak(["Hola, en ruso se dice Привет мир a todos"])
		langs = [x.lang for x in self.synth.sent[0] if isinstance(x, LangChangeCommand)]
		self.assertIn("ru", langs)
		self.assertIsNone(langs[-1])

	def test_ngram_detection(self) -> None:
		self.assertEqual(langdetect.detectLatin("Please click the button below to continue with the installation.", "es")[0], "en")
		self.assertEqual(langdetect.detectLatin("Haga clic en el botón de abajo para continuar con la instalación.", "es")[0], "es")
		self.assertIsNone(langdetect.detectLatin("OK", "es")[0])

	def test_not_supported_language_reported(self) -> None:
		conf["speech"]["reportNotSupportedLanguage"] = "speech"
		speech.speak([LangChangeCommand("ja"), "こんにちは", LangChangeCommand(None)])
		self.assertIn("idioma no admitido", self.synth.texts(0))
		conf["speech"]["reportNotSupportedLanguage"] = "beep"
		speech._manager = None
		self.mgr = speech.getManager()
		speech.speak([LangChangeCommand("ja"), "こんにちは"])
		self.assertTrue(any(isinstance(x, IndexCommand) for x in self.synth.sent[-1]))
		conf["speech"]["reportNotSupportedLanguage"] = "speech"

	def test_report_language(self) -> None:
		conf["speech"]["reportLanguage"] = True
		try:
			speech.speak([LangChangeCommand("en_US"), "hello", LangChangeCommand(None)])
			self.assertIn("inglés", self.synth.texts(0))
		finally:
			conf["speech"]["reportLanguage"] = False

	def test_dialect_parent_language(self) -> None:
		conf["speech"]["autoDialectSwitching"] = True
		try:
			self.assertIsNone(languages.resolveSwitch("es", "es_ES"))
			self.assertEqual(languages.resolveSwitch("es_MX", "es_ES"), "es_MX")
		finally:
			conf["speech"]["autoDialectSwitching"] = False
		self.assertEqual(languages.resolveSwitch("en_GB", "es_ES"), "en")

	def test_messages_in_interface_language(self) -> None:
		self.synth.language = "en_US"
		speech.speakMessage("mensaje")
		self.assertTrue(any(isinstance(x, LangChangeCommand) and x.lang == "es" for x in self.synth.sent[0]))


class SymbolTablesTests(unittest.TestCase):
	def test_english_table(self) -> None:
		p = symbols.getProcessor("en_US")
		self.assertIsNotNone(p)
		self.assertIn("comma", p.process("a, b", symbols.LEVEL_ALL))
		self.assertEqual(p.characterName(" "), "space")

	def test_symbols_follow_language(self) -> None:
		out = speech.processText("a, b", symbols.LEVEL_ALL, language="en")
		self.assertIn("comma", out)
		out = speech.processText("a, b", symbols.LEVEL_ALL, language="es")
		self.assertIn("coma", out)

	def test_unknown_symbol_names(self) -> None:
		p = symbols.getProcessor("es")
		self.assertIn("place of interest sign", p.process("hola ⌘", symbols.LEVEL_SOME, unknownSymbols=True).lower())

	def test_character_description_family(self) -> None:
		self.assertEqual(symbols.characterDescription("a", "es_MX"), "Antonio")
		self.assertEqual(symbols.characterDescription("a", "ca"), "Antonio")
		self.assertEqual(symbols.characterDescription("a", "en_GB"), "Alfa")

	def test_user_phonetic_alphabet(self) -> None:
		symbols.saveUserDescriptions("es", dict(symbols.getCharacterDescriptions("es"), a="Ana"))
		try:
			self.assertEqual(symbols.characterDescription("a", "es"), "Ana")
		finally:
			symbols.saveUserDescriptions("es", dict(symbols.BUILTIN_CHARACTER_DESCRIPTIONS["es"]))


class NumbersTests(unittest.TestCase):
	def test_modes(self) -> None:
		self.assertEqual(numbers.applyNumberMode("123456", "digits"), "1 2 3 4 5 6")
		self.assertEqual(numbers.applyNumberMode("123456", "pairs"), "12 34 56")
		self.assertEqual(numbers.applyNumberMode("1234567", "triples"), "123 456 7")
		self.assertEqual(numbers.applyNumberMode("12", "full"), "12")

	def test_alphanumeric_and_entities(self) -> None:
		self.assertEqual(numbers.splitAlphanumeric("abc123def"), "abc 123 def")
		self.assertEqual(numbers.decodeEntities("a &amp; b &#233; &#x20AC; &nada;"), "a & b é € &nada;")


class DictionaryTests(unittest.TestCase):
	def test_new_types(self) -> None:
		D = dictionaries
		text = "can canción escanear Duncan"
		self.assertEqual(D.Entry("can", "X", type=D.TYPE_WORD).apply(text), "X canción escanear Duncan")
		self.assertEqual(D.Entry("can", "X", type=D.TYPE_START).apply(text), "X Xción escanear Duncan")
		self.assertEqual(D.Entry("can", "X", type=D.TYPE_END).apply(text), "X canción escanear DunX")
		self.assertEqual(D.Entry("can", "X", type=D.TYPE_PART).apply(text), "can Xción esXear DunX")

	def test_disabled_entry(self) -> None:
		e = dictionaries.Entry("hola", "adiós", enabled=False)
		self.assertEqual(e.apply("hola"), "hola")

	def test_roundtrip(self) -> None:
		path = os.path.join(_TMP, "dict.json")
		dictionaries.writeEntries(path, [dictionaries.Entry("a", "b", type=dictionaries.TYPE_PART, enabled=False)])
		read = dictionaries.readEntries(path)
		self.assertEqual(read[0].type, dictionaries.TYPE_PART)
		self.assertFalse(read[0].enabled)

	def test_voice_dict_reloads_on_voice_change(self) -> None:
		from tiresias import synth

		old = synth._current
		fake = FakeSynth()
		synth._current = fake  # type: ignore[assignment]
		try:
			path = dictionaries.voiceDictFile("fake", "v1")
			dictionaries.writeEntries(path, [dictionaries.Entry("perro", "can")])
			dictionaries._voiceKey = None
			self.assertEqual(dictionaries.processText("perro"), "can")
		finally:
			synth._current = old
			dictionaries.voiceDict.clear()
			dictionaries._voiceKey = None


class VerbosityTests(unittest.TestCase):
	def test_compose_order_and_template(self) -> None:
		from tiresias.objects.roles import Role

		props = {"name": "Aceptar", "role": "botón", "value": "", "states": "", "description": "", "shortcut": "", "position": "", "level": ""}
		conf["presentation"]["propertyOrder"] = ["role", "name"]
		try:
			self.assertEqual(verbosity.compose(props, Role.BUTTON), ["botón", "Aceptar"])
			conf["presentation"]["roleTemplates"] = {"button": "{name} b"}
			self.assertEqual(verbosity.compose(props, Role.BUTTON), ["Aceptar b"])
		finally:
			conf["presentation"]["roleTemplates"] = {}
			conf["presentation"]["propertyOrder"] = list(verbosity.DEFAULT_ORDER)

	def test_template_validation(self) -> None:
		self.assertIsNone(verbosity.validateTemplate("{name} {role}"))
		self.assertIsNotNone(verbosity.validateTemplate("{nombre}"))

	def test_shortcut_letters(self) -> None:
		self.assertEqual(verbosity.formatShortcut("Alt+F"), "Alt+ efe")

	def test_expert_short_role(self) -> None:
		from tiresias.objects.roles import Role

		self.assertEqual(verbosity.shortRoleText(Role.HEADING2, 2), "encabezado 2")
		self.assertEqual(verbosity.shortRoleText(Role.COMBOBOX, None), "combo")


class SayAllTests(unittest.TestCase):
	def test_merge_without_pauses(self) -> None:
		calls: list[int] = []
		lines = [(lambda: calls.append(1), ["Esta frase sigue"]), (lambda: calls.append(2), ["en la línea siguiente."]), (lambda: calls.append(3), ["Otra."])]
		seq = sayall.mergeWithoutPauses(lines)
		texts = [x for x in seq if isinstance(x, str)]
		self.assertEqual(texts[0], "Esta frase sigue en la línea siguiente.")
		# La llamada de la segunda línea va tras el final de la frase, no en medio.
		self.assertIsInstance(seq[0], CallbackCommand)
		self.assertIsInstance(seq[2], CallbackCommand)

	def test_capitals(self) -> None:
		conf["speech"]["beepForCapitals"] = True
		try:
			seq = speech.capitalizedTextSequence("hola Mundo y NASA", "allCaps")
			self.assertTrue(any(isinstance(x, BeepCommand) for x in seq))
			self.assertIn("NASA", seq)
			self.assertEqual(speech.capitalizedTextSequence("sin nada", "initial"), ["sin nada"])
		finally:
			conf["speech"]["beepForCapitals"] = False


class SayAllReaderTests(_SynthTestCase):
	def test_reads_whole_text_without_pauses(self) -> None:
		from tiresias.textinfo import StaticTextInfo

		conf["speech"]["sayAllUnit"] = "line"
		conf["speech"]["sayAllWithoutPauses"] = True
		info = StaticTextInfo(None, (0, 0), "Una frase que sigue\nen otra línea.\nFin del texto.\n")
		sayall.readText(sayall.CURSOR_REVIEW, info)
		self.assertTrue(sayall.isRunning())
		# Se responde a todos los índices hasta que no quede nada.
		for _round in range(20):
			pending = [i for seq in self.synth.sent for i in [x.index for x in seq if isinstance(x, IndexCommand)]]
			for idx in pending:
				self.reach(idx)
			if not sayall.isRunning():
				break
		allText = " ".join(self.synth.texts(i) for i in range(len(self.synth.sent)))
		self.assertIn("Una frase que sigue en otra línea.", allText)
		self.assertIn("Fin del texto.", allText)
		self.assertFalse(sayall.isRunning())

	def test_sentence_unit(self) -> None:
		from tiresias.textinfo import StaticTextInfo

		conf["speech"]["sayAllUnit"] = "sentence"
		try:
			info = StaticTextInfo(None, (0, 0), "Primera frase. Segunda frase. Tercera.")
			sayall.readText(sayall.CURSOR_REVIEW, info)
			self.assertIn("Primera frase.", self.synth.texts(0))
			self.assertNotIn("Segunda", self.synth.texts(0))
		finally:
			conf["speech"]["sayAllUnit"] = "line"
			sayall.stop()


class VoiceSchemeTests(unittest.TestCase):
	def test_context_typing_rate(self) -> None:
		key = voice_schemes.contextKey("typing", "Rate")
		conf["speech"][key] = 40
		try:
			seq = voice_schemes.wrapContext("typing", ["a"])
			self.assertIsInstance(seq[0], RateCommand)
			self.assertEqual(seq[0].offset, 40)
			self.assertEqual(voice_schemes.wrapContext("caret", ["a"]), ["a"])
		finally:
			conf["speech"][key] = 0

	def test_scheme_decorate(self) -> None:
		conf["speech"]["voiceScheme"] = "expressive"
		try:
			before, after, label = voice_schemes.decorate("link", "x", "enlace")
			self.assertEqual(label, "")
			self.assertTrue(any(isinstance(c, PitchCommand) for c in before))
		finally:
			conf["speech"]["voiceScheme"] = ""
		self.assertEqual(voice_schemes.decorate("link", "x", "enlace"), ([], [], "enlace"))


class TypingEchoTests(unittest.TestCase):
	def test_word_before_caret(self) -> None:
		from tiresias import typing_echo

		self.assertEqual(typing_echo.wordBeforeCaret("hola casa "), "casa")
		self.assertEqual(typing_echo.wordBeforeCaret("I don't"), "don't")
		self.assertEqual(typing_echo.wordBeforeCaret("fin."), "fin")


if __name__ == "__main__":
	unittest.main()
