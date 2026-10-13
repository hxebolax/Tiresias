"""Pruebas del grupo «voz y formato» (G7, G8, F28, F30, F31).

- G7 (#8674): colores con valores RGB o hexadecimales.
- G8 (#13967): retardo por defecto de la descripción fonética.
- F28 (foros 2.1): leer todo por párrafos y velocidad propia de la lectura continua.
- F30 (foros 2.3): voces por contexto con otra voz, otra puntuación, menús y diálogos.
- F31 (foros 2.4): esquemas con colores, tipos de control y estados, también
  fuera del modo exploración.

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
	_TMP = tempfile.mkdtemp(prefix="tiresias_parciales_voz_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]
else:
	_TMP = paths._dataDirForTests  # type: ignore[attr-defined]
	if not os.path.isdir(os.path.join(_TMP, "symbols")):
		shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))

from tiresias import formatting  # noqa: E402
from tiresias.config import conf, validation  # noqa: E402
from tiresias.objects.roles import Role, State  # noqa: E402
from tiresias.speech import api as speech  # noqa: E402
from tiresias.speech import languages, sayall, voice_schemes  # noqa: E402
from tiresias.speech.commands import (  # noqa: E402
	IndexCommand,
	PitchCommand,
	RateCommand,
	SymbolLevelCommand,
	VoiceCommand,
	WaveFileCommand,
)
from tiresias.textinfo import StaticTextInfo  # noqa: E402


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


class VoiceSynth:
	"""Sintetizador falso con varias voces y ajustes."""

	name = "fakeVoices"
	language = "es_ES"
	availableLanguages = ("es_ES",)

	def __init__(self) -> None:
		self.sent: list[list] = []
		self.cancelled = 0
		self.settings = {"voice": "normal", "rate": 50, "pitch": 50, "volume": 100}
		self.voiceLog: list[str] = []

	@property
	def availableVoices(self):
		return {"normal": "Normal", "grave": "Grave", "aguda": "Aguda"}

	def speak(self, seq: list) -> None:
		self.sent.append(list(seq))

	def cancel(self) -> None:
		self.cancelled += 1

	def pause(self, switch: bool) -> None:
		pass

	def isSupported(self, sid: str) -> bool:
		return sid in ("voice", "rate", "pitch", "volume")

	def getSetting(self, sid: str):
		return self.settings.get(sid)

	def setSetting(self, sid: str, value) -> None:
		self.settings[sid] = value
		if sid == "voice":
			self.voiceLog.append(value)
			# Como algunos sintetizadores, el cambio de voz reinicia la velocidad.
			self.settings["rate"] = 50

	def saveableSettings(self) -> dict:
		return dict(self.settings)

	def texts(self, i: int = -1) -> str:
		return " ".join(x for x in self.sent[i] if isinstance(x, str))

	def indexes(self, i: int = -1) -> list[int]:
		return [x.index for x in self.sent[i] if isinstance(x, IndexCommand)]


class _SynthCase(unittest.TestCase):
	def setUp(self) -> None:
		from tiresias import synth

		self.synth = VoiceSynth()
		self._old = synth._current
		synth._current = self.synth  # type: ignore[assignment]
		languages._supportedCache = None
		speech._manager = None
		self.mgr = speech.getManager()
		conf["speech"]["speechMode"] = "talk"

	def tearDown(self) -> None:
		from tiresias import synth

		sayall.stop()
		self.mgr.cancel()
		synth._current = self._old
		speech._manager = None
		languages._supportedCache = None

	def finishAll(self) -> None:
		for _round in range(30):
			pending = [i for seq in self.synth.sent for i in [x.index for x in seq if isinstance(x, IndexCommand)]]
			for idx in pending:
				self.mgr._indexReached(idx)
			if not sayall.isRunning():
				break


# ====================================================================== G7
class ColorFormatTests(unittest.TestCase):
	NAVY = 0x800000  # COLORREF 0x00BBGGRR: azul 128

	def test_default_is_name_only(self) -> None:
		self.assertEqual(conf.defaults["documentFormatting"]["colorFormat"], "name")
		with _Conf("documentFormatting", colorFormat="name"):
			self.assertEqual(formatting.colorName(self.NAVY), "azul marino")

	def test_rgb_and_hex(self) -> None:
		with _Conf("documentFormatting", colorFormat="nameAndRgb"):
			self.assertEqual(formatting.colorName(0x794E1F), "verde azulado, rojo 31, verde 78, azul 121")
		with _Conf("documentFormatting", colorFormat="nameAndHex"):
			self.assertEqual(formatting.colorName(0x794E1F), "verde azulado, hexadecimal 1F4E79")
		self.assertEqual(formatting.colorName(0x0000FF, "nameAndHex"), "rojo, hexadecimal FF0000")
		self.assertEqual(formatting.colorName(-1), "")
		self.assertEqual(formatting.colorName("x"), "")

	def test_office_and_describe(self) -> None:
		from tiresias.appmodules import _office

		with _Conf("documentFormatting", colorFormat="nameAndRgb"):
			self.assertIn("rojo 255, verde 0, azul 0", _office.colorName(0x0000FF))
			out = formatting.describe({"color": 0x0000FF, "backgroundColor": 0xFFFFFF}, None)
			self.assertIn("color rojo, rojo 255, verde 0, azul 0", out)
			# Fondo blanco por defecto: no se anuncia al principio.
			self.assertFalse(any(p.startswith("fondo") for p in out))

	def test_word_and_excel_texts(self) -> None:
		from tiresias.appmodules import _excel, _word

		with _Conf("documentFormatting", colorFormat="nameAndHex"):
			text = _word.formattingText({"color": 0x0000FF, "backgroundColor": 0x00FFFF})
			self.assertIn("color rojo, hexadecimal FF0000", text)
			self.assertIn("fondo amarillo, hexadecimal FFFF00", text)
			cell = _excel.detailsText({"fontColor": 0x0000FF, "fillColor": 0x00FF00}, full=True)
			self.assertIn("color rojo, hexadecimal FF0000", cell)
			self.assertIn("relleno verde lima, hexadecimal 00FF00", cell)

	def test_cell_borders_with_values(self) -> None:
		with _Conf("documentFormatting", colorFormat="nameAndRgb"):
			text = formatting.describeCellBorders([1.0, 3.0, 0, 0], [0, 0xFF, 0, 0])
		self.assertIn("; ", text)
		self.assertIn("abajo grueso rojo, rojo 255", text)

	def test_validation_and_command(self) -> None:
		from tiresias import global_commands_extra

		self.assertEqual(validation.CHOICES[("documentFormatting", "colorFormat")], ("name", "nameAndRgb", "nameAndHex"))
		names = [n for n, _k, _w, _v in global_commands_extra.DOC_CYCLES]
		self.assertIn("cycleColorFormat", names)


# ====================================================================== G8
class DelayedDescriptionTests(unittest.TestCase):
	def test_default_reduced(self) -> None:
		from tiresias.config import schema as sch

		with open(sch.__file__, encoding="utf-8") as f:
			src = f.read()
		self.assertIn('"delayedCharacterDescriptionsDelay": 500', src)
		self.assertEqual(validation.RANGES[("speech", "delayedCharacterDescriptionsDelay")], (100, 10000))

	def test_saved_value_is_kept(self) -> None:
		data = {"speech": {"delayedCharacterDescriptionsDelay": 1000}}
		validation.validate(data, {"speech": {"delayedCharacterDescriptionsDelay": 500}})
		self.assertEqual(data["speech"]["delayedCharacterDescriptionsDelay"], 1000)


# ====================================================================== F28
class SayAllParagraphAndRateTests(_SynthCase):
	def test_paragraph_unit(self) -> None:
		with _Conf("speech", sayAllUnit="paragraph", sayAllWithoutPauses=True, sayAllRateOffset=0):
			info = StaticTextInfo(None, (0, 0), "Primer párrafo. Sigue igual.\nSegundo párrafo.\n")
			sayall.readText(sayall.CURSOR_REVIEW, info)
			self.assertIn("Primer párrafo. Sigue igual.", self.synth.texts(0))
			self.assertNotIn("Segundo", self.synth.texts(0))
			self.finishAll()

	def test_with_rate_shifts_scheme_rates(self) -> None:
		seq = sayall.withRate(["a", RateCommand(offset=-10), "b", RateCommand(0)], 20)
		rates = [c.offset for c in seq if isinstance(c, RateCommand)]
		self.assertEqual(rates, [20, 10, 20])
		self.assertEqual(sayall.withRate(["a"], 0), ["a"])

	def test_own_rate_does_not_touch_voice_rate(self) -> None:
		with _Conf("speech", sayAllUnit="line", sayAllRateMode="sayAll", sayAllRateOffset=0, sayAllRateStep=5):
			info = StaticTextInfo(None, (0, 0), "uno\ndos\ntres\ncuatro\ncinco\nseis\n")
			sayall.readText(sayall.CURSOR_REVIEW, info)
			self.assertEqual(sayall.changeRate(1), 5)
			self.assertEqual(conf["speech"]["sayAllRateOffset"], 5)
			# La velocidad de la voz no cambia; la lectura lleva su propio cambio.
			self.assertEqual(self.synth.settings["rate"], 50)
			last = self.synth.sent[-1]
			self.assertTrue(any(isinstance(c, RateCommand) and c.offset == 5 for c in last))
			# Lo que no es lectura continua suena con la velocidad normal.
			sayall.stop()
			self.mgr.cancel()
			speech.speak(["mensaje"])
			self.assertFalse(any(isinstance(c, RateCommand) and c.offset for c in self.synth.sent[-1]))

	def test_temporary_rate_resets(self) -> None:
		with _Conf("speech", sayAllUnit="line", sayAllRateMode="temporary", sayAllRateOffset=0, sayAllRateStep=10):
			info = StaticTextInfo(None, (0, 0), "uno\ndos\ntres\ncuatro\ncinco\nseis\n")
			sayall.readText(sayall.CURSOR_REVIEW, info)
			sayall.changeRate(1)
			self.assertEqual(sayall.rateOffset(), 10)
			self.assertEqual(conf["speech"]["sayAllRateOffset"], 0)
			# Al saltar se conserva; una lectura nueva vuelve a la normal.
			sayall.skip("line", 1)
			self.assertEqual(sayall.rateOffset(), 10)
			sayall.readText(sayall.CURSOR_REVIEW, StaticTextInfo(None, (0, 0), "otra\n"))
			self.assertEqual(sayall.rateOffset(), 0)

	def test_global_mode_changes_voice(self) -> None:
		with _Conf("speech", sayAllRateMode="global", sayAllRateOffset=0, sayAllRateStep=5):
			old = conf["speech"]["synths"].dict() if hasattr(conf["speech"]["synths"], "dict") else {}
			try:
				self.assertIsNone(sayall.changeRate(-1))
				self.assertEqual(self.synth.settings["rate"], 45)
			finally:
				conf["speech"]["synths"] = old

	def test_unit_choices(self) -> None:
		from tiresias.speech import plugin

		self.assertIn(("speech", "sayAllRateMode"), validation.CHOICES)
		self.assertEqual([k for k, _l in plugin.SAYALL_UNIT_LABELS], ["line", "sentence", "paragraph"])


# ====================================================================== F30
class VoiceContextTests(_SynthCase):
	def test_wrap_context_voice_and_punctuation(self) -> None:
		with _Conf("speech", voiceContexts=True, contextMessageVoice="grave", contextMessageSymbolLevel=300, contextMessagePitch=10):
			seq = voice_schemes.wrapContext("message", ["hola"])
			self.assertIsInstance(seq[0], VoiceCommand)
			self.assertEqual(seq[0].voice, "grave")
			self.assertTrue(any(isinstance(c, SymbolLevelCommand) and c.level == 300 for c in seq))
			self.assertTrue(any(isinstance(c, PitchCommand) for c in seq))
		with _Conf("speech", voiceContexts=False, contextMessageVoice="grave"):
			self.assertEqual(voice_schemes.wrapContext("message", ["hola"]), ["hola"])

	def test_symbol_level_marker(self) -> None:
		out = speech._processSequence([SymbolLevelCommand(300), "a, b"], None)
		self.assertIn("coma", " ".join(x for x in out if isinstance(x, str)))
		out = speech._processSequence([SymbolLevelCommand(0), "a, b"], None)
		self.assertNotIn("coma", " ".join(x for x in out if isinstance(x, str)))
		# Un nivel explícito de la llamada manda sobre el del contexto.
		out = speech._processSequence([SymbolLevelCommand(300), "a, b"], 0)
		self.assertNotIn("coma", " ".join(x for x in out if isinstance(x, str)))

	def test_manager_switches_voice_between_utterances(self) -> None:
		self.synth.settings["rate"] = 70
		speech.speak(["normal uno"])
		speech.speak([VoiceCommand("grave"), "contexto"])
		# El segundo no sale hasta que acabe el primero (cambia la voz).
		self.assertEqual(len(self.synth.sent), 1)
		self.assertEqual(self.synth.voiceLog, [])
		self.mgr._indexReached(self.synth.indexes(0)[-1])
		self.assertEqual(len(self.synth.sent), 2)
		self.assertEqual(self.synth.settings["voice"], "grave")
		# La velocidad se conserva aunque el sintetizador la reinicie.
		self.assertEqual(self.synth.settings["rate"], 70)
		# Mientras suena, se guarda la voz normal.
		saved = speech.savedSynthSettings(self.synth, self.synth.saveableSettings())
		self.assertEqual(saved["voice"], "normal")
		self.mgr._indexReached(self.synth.indexes(1)[-1])
		self.assertEqual(self.synth.settings["voice"], "normal")
		self.assertEqual(self.synth.voiceLog, ["grave", "normal"])

	def test_unknown_or_same_voice_is_ignored(self) -> None:
		speech.speak([VoiceCommand("no existe"), "a"])
		speech.speak([VoiceCommand("normal"), "b"])
		self.assertEqual(self.synth.voiceLog, [])

	def test_ring_change_becomes_normal(self) -> None:
		speech.speak([VoiceCommand("grave"), "a"])
		self.assertEqual(self.synth.settings["voice"], "grave")
		# El usuario elige otra voz con el anillo mientras suena el contexto.
		self.synth.settings["voice"] = "aguda"
		self.mgr.cancel()
		self.assertEqual(self.synth.settings["voice"], "aguda")

	def test_menu_and_dialog_context(self) -> None:
		from tiresias import api

		class Obj:
			def __init__(self, role):
				self.role = role

		item = Obj(Role.MENUITEM)
		edit = Obj(Role.EDITABLETEXT)
		with _Conf("speech", voiceContexts=True, contextMenuPitch=20, contextDialogRate=10):
			self.assertEqual(voice_schemes.objectVoiceContext(item), "menu")
			old = (api._focusObject, api._focusAncestors)
			try:
				api._focusObject = edit
				api._focusAncestors = [Obj(Role.DIALOG)]
				self.assertEqual(voice_schemes.objectVoiceContext(edit), "dialog")
				api._focusAncestors = [Obj(Role.PANE)]
				self.assertIsNone(voice_schemes.objectVoiceContext(edit))
			finally:
				api._focusObject, api._focusAncestors = old
		with _Conf("speech", voiceContexts=False):
			self.assertIsNone(voice_schemes.objectVoiceContext(item))

	def test_ui_choices(self) -> None:
		choices = voice_schemes.contextVoiceChoices()
		self.assertEqual(choices[0][0], "")
		self.assertIn("grave", [k for k, _l in choices])
		self.assertEqual(voice_schemes.contextSymbolLevelChoices()[0][0], -1)
		self.assertIn("menu", voice_schemes.CONTEXTS)
		self.assertIn("dialog", voice_schemes.CONTEXTS)


# ====================================================================== F31
class _FmtInfo(StaticTextInfo):
	"""Texto con formato por posiciones: {posición: formato}."""

	def __init__(self, text: str, fmts: dict, start: int = 0, end: int | None = None) -> None:
		super().__init__(None, (start, len(text) if end is None else end), text)
		self._fmts = fmts

	def getFormatInfo(self, keys=None) -> dict:
		return dict(self._fmts.get(self._start, {}))


class VoiceSchemeTests(unittest.TestCase):
	def test_color_family(self) -> None:
		self.assertEqual(voice_schemes.colorFamily(0x0000FF), "color_red")
		self.assertEqual(voice_schemes.colorFamily(0xFF0000), "color_blue")
		self.assertEqual(voice_schemes.colorFamily(0x00FF00), "color_green")
		self.assertEqual(voice_schemes.colorFamily(0x808080), "color_gray")
		self.assertEqual(voice_schemes.colorFamily(0x13458B), "color_brown")
		self.assertIsNone(voice_schemes.colorFamily(0))
		self.assertIsNone(voice_schemes.colorFamily(0xFFFFFF))

	def test_object_style_replaces_role_and_states(self) -> None:
		with _Conf("speech", voiceScheme="sounds", voiceSchemeEverywhere=True):
			style = voice_schemes.ObjectStyle(Role.CHECKBOX, {State.CHECKED})
			self.assertTrue(style.replacedRole)
			self.assertIn(State.CHECKED, style.replacedStates)
			self.assertEqual(style.sounds, ["role_checkBox", "state_checked"])
			off = voice_schemes.ObjectStyle(Role.CHECKBOX, set())
			self.assertIn(State.CHECKED, off.replacedNegative)
			dis = voice_schemes.ObjectStyle(Role.BUTTON, {State.UNAVAILABLE})
			self.assertIn("state_unavailable", dis.attributes)

	def test_presentation_outside_browse_mode(self) -> None:
		from tiresias import presentation

		class Btn:
			name = "Aceptar"
			role = Role.BUTTON
			states = {State.UNAVAILABLE, State.FOCUSABLE}
			roleText = None
			value = ""
			description = ""
			keyboardShortcut = ""
			positionInfo: dict = {}

		with _Conf("speech", voiceScheme="sounds", voiceSchemeEverywhere=True):
			with voice_schemes.objectContext(Btn(), presentation.Reason.FOCUS) as style:
				text = " ".join(presentation.getObjectSpeech(Btn(), presentation.Reason.FOCUS))
			self.assertIn("Aceptar", text)
			self.assertNotIn("botón", text)
			self.assertNotIn("no disponible", text)
			seq = style.wrap([text])
			self.assertTrue(any(isinstance(c, WaveFileCommand) and c.name == "role_button" for c in seq))
		with _Conf("speech", voiceScheme="sounds", voiceSchemeEverywhere=False):
			with voice_schemes.objectContext(Btn(), presentation.Reason.FOCUS) as style:
				text = " ".join(presentation.getObjectSpeech(Btn(), presentation.Reason.FOCUS))
			self.assertIn("botón", text)
			self.assertFalse(style)

	def test_editable_text_attributes(self) -> None:
		text = "Texto en rojo"
		red = {"color": 0x0000FF}
		info = _FmtInfo(text, {0: red, len(text) - 1: red})
		with _Conf("speech", voiceScheme="proofreading", voiceSchemeEverywhere=True):
			seq = voice_schemes.decorateTextInfo(info, [text])
			self.assertTrue(any(isinstance(c, PitchCommand) and c.offset == 20 for c in seq))
			# Si solo el principio es rojo, no se tiñe la línea entera.
			partial = _FmtInfo(text, {0: red})
			self.assertEqual(voice_schemes.decorateTextInfo(partial, [text]), [text])
		with _Conf("speech", voiceScheme="", voiceSchemeEverywhere=True):
			self.assertEqual(voice_schemes.decorateTextInfo(info, [text]), [text])

	def test_browse_suffix_and_decoration(self) -> None:
		class Node:
			def __init__(self, role, states=(), parent=None):
				self.role = role
				self.states = set(states)
				self.parent = parent
				self.fmt = ""
				self.clickable = False

		box = Node(Role.CHECKBOX, {State.CHECKED})
		with _Conf("speech", voiceScheme="sounds"):
			self.assertEqual(voice_schemes.filterSuffix(box, "casilla de verificación marcado"), "")
			state: dict = {}
			before, _after = voice_schemes.textDecoration(object(), box, 0, state)
			self.assertEqual([c.name for c in before if isinstance(c, WaveFileCommand)], ["role_checkBox", "state_checked"])
			# Una sola vez por control.
			self.assertEqual(voice_schemes.controlSounds(box, state), [])
		with _Conf("speech", voiceScheme="expressive"):
			self.assertEqual(voice_schemes.filterSuffix(box, "casilla de verificación marcado"), "casilla de verificación marcado")

	def test_states_context_only_changed(self) -> None:
		class Box:
			role = Role.CHECKBOX
			states = {State.CHECKED, State.FOCUSABLE}

		with _Conf("speech", voiceScheme="sounds", voiceSchemeEverywhere=True):
			with voice_schemes.statesContext(Box(), {State.CHECKED}, set()) as style:
				self.assertTrue(voice_schemes.stateReplaced(State.CHECKED))
				self.assertFalse(voice_schemes.roleReplaced(Role.CHECKBOX))
			self.assertEqual(style.sounds, ["state_checked"])

	def test_all_attributes_have_labels(self) -> None:
		for a in voice_schemes.ATTRIBUTES:
			self.assertIn(a, voice_schemes.ATTRIBUTE_LABELS)
		for name, scheme in voice_schemes.BUILTIN_SCHEMES.items():
			self.assertIn(name, voice_schemes.BUILTIN_LABELS)
			for a in scheme:
				self.assertIn(a, voice_schemes.ATTRIBUTES, (name, a))


if __name__ == "__main__":
	unittest.main()
