"""Pruebas del núcleo braille sin hardware: liblouis, tablas, presentación,
ajuste y desplazamiento, modos, mensajes, enrutamiento y entrada braille."""

from __future__ import annotations

import unittest
from unittest import mock

import braille_sim  # noqa: F401  (prepara rutas y datos)

from tiresias import api, braille, textinfo
from tiresias.braille import commands as brailleCommands
from tiresias.braille import input as brailleInput
from tiresias.braille import liblouis, presenter, tables
from tiresias.config import conf
from tiresias.objects.roles import Role, State
from tiresias.textinfo import StaticTextInfo

D = tables.dots


def U(cells) -> str:
	return tables.cellsToUnicode(cells)


# ====================================================================== simulaciones
class FakeDisplay(braille.BrailleDisplayDriver):
	name = "fake"
	description = "Línea simulada"

	def __init__(self, numCells: int = 20) -> None:
		super().__init__()
		self.numCells = numCells
		self.shown: list[int] = []

	@classmethod
	def check(cls) -> bool:
		return True

	def display(self, cells: list[int]) -> None:
		self.shown = list(cells)


class FakeTextInfo(StaticTextInfo):
	def updateCaret(self) -> None:
		self.obj.caret = self._start

	def updateSelection(self) -> None:
		self.obj.selection = (self._start, self._end)


class FakeObj:
	presentationType = "content"
	roleText = None
	level = None
	description = ""
	keyboardShortcut = ""
	placeholder = ""
	firstChild = None
	treeInterceptor = None
	positionInfo: dict = {}

	def __init__(self, name="", role=Role.BUTTON, value="", text=None, states=None) -> None:
		self.name = name
		self.role = role
		self.value = value
		self.states = set(states or ())
		self._text = text
		self.caret = 0
		self.selection = None
		self.actions = 0

	@property
	def hasText(self) -> bool:
		return self._text is not None

	def makeTextInfo(self, position):
		if position == textinfo.POSITION_CARET:
			ti = FakeTextInfo(self, (self.caret, self.caret), self._text)
		elif position == textinfo.POSITION_SELECTION:
			s = self.selection or (self.caret, self.caret)
			ti = FakeTextInfo(self, s, self._text)
		else:
			ti = FakeTextInfo(self, position, self._text)
		return ti

	def doAction(self) -> None:
		self.actions += 1


class _BrailleCase(unittest.TestCase):
	"""Prepara una línea simulada de 20 celdas y restaura la configuración."""

	cells = 20
	KEYS = (
		"translationTable",
		"inputTable",
		"textWrap",
		"tetherTo",
		"mode",
		"splitView",
		"showCursor",
		"cursorBlink",
		"showMessages",
		"expandAtCursor",
		"focusContextPresentation",
		"hiddenProperties",
		"propertyOrder",
		"roleAbbreviations",
		"showEmojiNames",
		"undefinedCharacters",
		"unicodeNormalization",
		"readByParagraph",
		"paragraphStartMarker",
		"fontFormattingDisplay",
		"showSpellingErrors",
	)

	def setUp(self) -> None:
		self._saved = {}
		for k in self.KEYS:
			v = conf["braille"][k]
			self._saved[k] = dict(v) if hasattr(v, "keys") else (list(v) if isinstance(v, list) else v)
		self.h = braille.handler
		self._oldDisplay = self.h.display
		self.display = FakeDisplay(self.cells)
		self.h.display = self.display
		self.h._initPresenter()
		conf["braille"]["cursorBlink"] = False
		conf["braille"]["translationTable"] = "es-comp8"
		conf["braille"]["textWrap"] = "wordBoundaries"
		conf["braille"]["tetherTo"] = "auto"
		conf["braille"]["mode"] = "followCursors"
		conf["braille"]["splitView"] = "off"
		conf["braille"]["showMessages"] = "timeout"
		conf["braille"]["expandAtCursor"] = False
		self._oldFocus = api.getFocusObject()

	def tearDown(self) -> None:
		for k, v in self._saved.items():
			conf["braille"][k] = v
		self.h.terminate()
		self.h.display = self._oldDisplay
		self.h._initPresenter()
		api.setFocusObject(self._oldFocus, [])


# ====================================================================== liblouis
class LiblouisTests(unittest.TestCase):
	def test_loaded(self) -> None:
		self.assertTrue(liblouis.isAvailable(), liblouis.loadError())
		self.assertTrue(liblouis.version().startswith("3."))

	def test_spanish_computer(self) -> None:
		cells, b2r, r2b, _cur = liblouis.translate(["Es-Es-G0.utb"], "Ab")
		self.assertEqual(cells, [D("17"), D("12")])
		self.assertEqual(b2r, [0, 1])
		self.assertEqual(r2b, [0, 1])

	def test_spanish_literary_signs(self) -> None:
		cells = liblouis.translate(["es.tbl"], "Hola 12")[0]
		self.assertEqual(cells[0], D("46"))
		self.assertIn(D("3456"), cells)

	def test_english_contracted(self) -> None:
		cells = liblouis.translate(["en-ueb-g2.ctb"], "the")[0]
		self.assertEqual(cells, [D("2346")])

	def test_expand_at_cursor(self) -> None:
		normal = liblouis.translate(["en-ueb-g2.ctb"], "the knowledge")[0]
		expanded, _b, _r, cur = liblouis.translate(["en-ueb-g2.ctb"], "the knowledge", cursorPos=5, mode=liblouis.COMPBRL_AT_CURSOR)
		self.assertGreater(len(expanded), len(normal))
		self.assertIsNotNone(cur)

	def test_back_translate(self) -> None:
		for table, text in (("es.tbl", "Hola 123"), ("Es-Es-G0.utb", "Hola @ 5"), ("en-ueb-g1.ctb", "Hello")):
			cells = liblouis.translate([table], text)[0]
			self.assertEqual(liblouis.backTranslate([table], cells), text, table)

	def test_hyphenation(self) -> None:
		self.assertEqual(liblouis.hyphenate(["es-chardefs.cti", "hyph_es_ES.dic"], "murciélago"), [3, 6, 8])


# ====================================================================== tablas
class TableCatalogTests(unittest.TestCase):
	def test_spanish_names_from_metadata(self) -> None:
		names = dict(tables.listTables())
		self.assertEqual(names["Es-Es-G0.utb"], "Español, braille informático")
		self.assertEqual(names["es-g2.ctb"], "Español, braille contraído (grado 2)")
		self.assertTrue(names["de-g2.ctb"].startswith("Alemán"))
		self.assertGreater(len(names), 200)

	def test_input_list_excludes_forward_only(self) -> None:
		inputs = dict(tables.listTables(forInput=True))
		self.assertNotIn("es-g2.ctb", inputs)
		self.assertIn("es.tbl", inputs)

	def test_auto(self) -> None:
		self.assertEqual(tables.autoTableName(), "Es-Es-G0.utb")
		self.assertEqual(tables.getTable("auto").name, "Es-Es-G0.utb")
		self.assertTrue(tables.listTables(includeAuto=True)[0][1].startswith("Automática"))

	def test_unknown_falls_back_to_own(self) -> None:
		self.assertEqual(tables.getTable("no-existe.ctb").name, "es-comp8")

	def test_broken_louis_table_uses_own(self) -> None:
		t = tables.LouisTable("roto.ctb", "Rota", {"language": "es", "type": "literary", "contraction": "no", "dots": "6"})
		tr = tables.translate(t, "Hola")
		self.assertTrue(getattr(t, "_broken", False))
		self.assertEqual(tr.cells, tables.getTable("es-g1").translate("Hola").cells)


class TranslateOptionsTests(unittest.TestCase):
	def setUp(self) -> None:
		self.t = tables.getTable("Es-Es-G0.utb")

	def test_emoji_names(self) -> None:
		tr = tables.translate(self.t, "a😀b", emoji=True)
		plain = tables.translate(self.t, "a😀b", emoji=False)
		self.assertGreater(len(tr.cells), len(plain.cells))
		# Todas las celdas del nombre apuntan al emoji.
		self.assertEqual(set(tr.brailleToRaw[1:-1]), {1})
		self.assertEqual(tr.rawToBraille[2], len(tr.cells) - 1)

	def test_undefined_modes(self) -> None:
		self.assertEqual(tables.translate(self.t, "a☃", undefined="allDots").cells[-1], 0xFF)
		self.assertEqual(tables.translate(self.t, "a☃", undefined="omit").cells, [D("1")])
		self.assertEqual(tables.translate(self.t, "a☃", undefined="questionMark").cells[-1:], self.t.translate("?").cells)

	def test_unicode_normalization(self) -> None:
		decomposed = "é"
		tr = tables.translate(self.t, decomposed, normalize=True)
		self.assertEqual(tr.cells, tables.translate(self.t, "é").cells)
		self.assertEqual(tr.rawToBraille, [0, 0])

	def test_cursor_position(self) -> None:
		tr = tables.translate(tables.getTable("es.tbl"), "Ab 12", cursor=3)
		# «A» lleva signo de mayúscula; «1» lleva signo de número.
		self.assertEqual(tr.cursorPos, tr.rawToBraille[3])
		self.assertEqual(tr.cells[tr.cursorPos], D("3456"))


class OwnTablesTests(unittest.TestCase):
	def test_comp8_dot7_not_always_capital(self) -> None:
		t = tables.getTable("es-comp8")
		self.assertEqual(t.backTranslate([D("47"), D("17"), D("2357"), D("267"), D("1")]), "@A¡¿a")

	def test_g1_numbers_and_capitals(self) -> None:
		t = tables.getTable("es-g1")
		for text in ("Hola 123", "ÉL dijo 4,5", "año"):
			self.assertEqual(t.backTranslate(t.translate(text).cells), text)


# ====================================================================== presentación
class PropertiesTests(_BrailleCase):
	def test_order_hidden_and_abbreviations(self) -> None:
		obj = FakeObj("Aceptar", Role.CHECKBOX, states={State.CHECKED})
		obj.positionInfo = {"indexInGroup": 2, "similarItemsInGroup": 5}
		self.assertEqual(presenter.objectText(obj), "Aceptar chk (x) 2/5")
		conf["braille"]["propertyOrder"] = ["role", "states", "name", "position"]
		self.assertEqual(presenter.objectText(obj), "chk (x) Aceptar 2/5")
		conf["braille"]["hiddenProperties"] = ["position", "description", "shortcut"]
		conf["braille"]["roleAbbreviations"] = {"CHECKBOX": "casilla"}
		self.assertEqual(presenter.objectText(obj), "casilla (x) Aceptar")
		conf["braille"]["roleAbbreviations"] = {"CHECKBOX": ""}
		self.assertEqual(presenter.objectText(obj), "(x) Aceptar")

	def test_unchecked_and_heading_level(self) -> None:
		self.assertEqual(presenter.objectText(FakeObj("Recordar", Role.CHECKBOX)), "Recordar chk ( )")
		h = FakeObj("Título", Role.HEADING)
		h.level = 2
		self.assertEqual(presenter.objectText(h), "Título h2")


class PresenterTests(_BrailleCase):
	def _cellsFor(self, text: str) -> list[int]:
		return tables.getTable("es-comp8").translate(text).cells

	def test_object_region(self) -> None:
		obj = FakeObj("Aceptar", Role.BUTTON)
		api.setFocusObject(obj, [])
		self.h.handleObject(obj, "focus")
		self.assertEqual(self.display.shown[:11], self._cellsFor("Aceptar btn"))
		self.h.routeTo(2)
		self.assertEqual(obj.actions, 1)

	def test_edit_field_context_and_cursor(self) -> None:
		obj = FakeObj("Buscar", Role.EDITABLETEXT, text="hola mundo")
		obj.caret = 5
		api.setFocusObject(obj, [])
		self.h.handleObject(obj, "focus")
		self.assertTrue(self.h.text.startswith("Buscar edt "))
		cur = self.h._cursorCell() - self.h.windowStart
		self.assertEqual(self.display.shown[cur] & 0xC0, 0xC0)
		self.assertEqual(self.display.shown[cur] & 0x3F, D("134"))  # «m»
		# Enrutar mueve el cursor del sistema dentro del texto.
		self.h.windowStart = 0
		self.h._refresh()
		self.h.routeTo(self.h._lineStart + 2)
		self.assertEqual(obj.caret, 2)

	def test_update_while_typing(self) -> None:
		obj = FakeObj("", Role.EDITABLETEXT, text="ab")
		obj.caret = 2
		api.setFocusObject(obj, [])
		self.h.handleObject(obj, "focus")
		obj._text = "abc"
		obj.caret = 3
		with mock.patch("tiresias.queue_handler.callLater", side_effect=lambda ms, f, *a: f(*a) or 1):
			self.h.onEvent(eventName="caret", obj=obj)
		self.assertIn("abc", self.h.text)
		self.assertEqual(self.h.cursorPos, self.h._lineStart + 3)

	def test_selection_dots_7_8(self) -> None:
		obj = FakeObj("", Role.EDITABLETEXT, text="hola mundo")
		obj.caret = 4
		obj.selection = (0, 4)
		api.setFocusObject(obj, [])
		self.h.handleObject(obj, "focus")
		start = self.h._lineStart - self.h.windowStart
		self.assertTrue(all(self.display.shown[start + i] & 0xC0 == 0xC0 for i in range(4)))
		self.assertEqual(self.display.shown[start + 5] & 0xC0, 0)

	def test_message_and_restore(self) -> None:
		obj = FakeObj("Aceptar", Role.BUTTON)
		api.setFocusObject(obj, [])
		self.h.handleObject(obj, "focus")
		before = list(self.display.shown)
		self.h.message("hola")
		self.assertEqual(self.display.shown[:4], self._cellsFor("hola"))
		# Un cambio de foco durante el mensaje no lo borra.
		other = FakeObj("Cancelar", Role.BUTTON)
		api.setFocusObject(other, [])
		self.h.handleObject(other, "focus")
		self.assertEqual(self.display.shown[:4], self._cellsFor("hola"))
		self.h._dismissMessage()
		self.assertEqual(self.display.shown[:12], self._cellsFor("Cancelar btn"))
		self.assertNotEqual(before, self.display.shown)

	def test_speak_message_reaches_braille(self) -> None:
		from tiresias import queue_handler, speech

		with mock.patch.object(queue_handler, "isCoreThread", return_value=True), mock.patch.object(self.h, "message") as msg:
			speech.speakMessage("prueba")
		msg.assert_called_with("prueba")

	def test_speech_mode(self) -> None:
		conf["braille"]["mode"] = "speechOutput"
		self.h.onSpeech("dicho")
		self.assertEqual(self.display.shown[:5], self._cellsFor("dicho"))
		self.h.handleObject(FakeObj("Otro", Role.BUTTON), "focus")
		self.assertEqual(self.h.text, "dicho")

	def test_tether(self) -> None:
		obj = FakeObj("", Role.EDITABLETEXT, text="línea de foco")
		api.setFocusObject(obj, [])
		review = StaticTextInfo(None, (0, 0), "revisión")
		conf["braille"]["tetherTo"] = "focus"
		self.h.handleReviewMove(review)
		self.assertNotEqual(self.h._source, "review")
		conf["braille"]["tetherTo"] = "review"
		self.h.handleReviewMove(review)
		self.assertEqual(self.h._source, "review")
		self.assertEqual(self.h.text, "revisión")
		# El cursor del sistema no se muestra mientras se sigue a la revisión.
		self.h.handleCaretMove(obj.makeTextInfo(textinfo.POSITION_CARET))
		self.assertEqual(self.h.text, "revisión")

	def test_review_speech_does_not_break_tether(self) -> None:
		from tiresias import presentation

		info = StaticTextInfo(None, (0, 0), "abc")
		with mock.patch.object(self.h, "handleCaretMove") as hcm, mock.patch("tiresias.speech.speak"):
			presentation.speakTextInfo(info, textinfo.UNIT_CHARACTER, reason=presentation.Reason.REVIEW)
			hcm.assert_not_called()
			presentation.speakTextInfo(info, textinfo.UNIT_CHARACTER, reason=presentation.Reason.CARET)
			hcm.assert_called_once()

	def test_split_view(self) -> None:
		conf["braille"]["splitView"] = "clock"
		self.h.message("x")
		self.h._dismissMessage()
		obj = FakeObj("Aceptar", Role.BUTTON)
		api.setFocusObject(obj, [])
		self.h.handleObject(obj, "focus")
		main = self.h._mainWidth()
		self.assertEqual(main, 9)
		self.assertEqual(self.display.shown[main : main + 2], presenter.SPLIT_SEPARATOR)
		self.assertNotEqual(self.display.shown[main + 2 :], [0] * (self.cells - main - 2))


class WrapAndScrollTests(_BrailleCase):
	cells = 10
	TEXT = "uno dos tres cuatrocientos cinco seis"

	def _show(self) -> None:
		self.h._regionKind = "object"
		self.h._setRegion(self.TEXT, None)

	def _windows(self) -> list[str]:
		out = []
		self.h.windowStart = 0
		for _i in range(20):
			ws = self.h.windowStart
			we, mark = self.h._windowEnd(ws)
			out.append(self.TEXT[self.h._rawIndex(ws) : self.h._rawIndex(we - 1) + 1] + ("~" if mark else ""))
			if we >= len(self.h._translation.cells):
				break
			self.h.windowStart = we
		return out

	def test_word_boundaries(self) -> None:
		self._show()
		self.assertEqual(self._windows(), ["uno dos ", "tres ", "cuatrocie~", "ntos cinco", " seis"])

	def test_none(self) -> None:
		conf["braille"]["textWrap"] = "none"
		self._show()
		self.assertEqual(self._windows()[0], "uno dos tr")

	def test_mark_word_cuts(self) -> None:
		conf["braille"]["textWrap"] = "markWordCuts"
		self._show()
		w = self._windows()
		self.assertEqual(w[0], "uno dos t~")
		self.h.windowStart = 0
		self.h._refresh()
		self.assertEqual(self.display.shown[9], presenter.CONTINUATION_CELL)

	def test_syllables(self) -> None:
		conf["braille"]["translationTable"] = "Es-Es-G0.utb"
		conf["braille"]["textWrap"] = "syllableBoundaries"
		self._show()
		w = self._windows()
		# La palabra que no cabe se parte por una sílaba y se marca.
		self.assertEqual(w[:3], ["uno dos ", "tres cua~", "trocientos"])

	def test_scroll_forward_and_back_cover_everything(self) -> None:
		self._show()
		starts = [0]
		while self.h.scrollForward():
			if self.h.windowStart == starts[-1]:
				break
			starts.append(self.h.windowStart)
		self.assertEqual(len(starts), 5)
		back = [self.h.windowStart]
		while self.h.windowStart > 0 and self.h.scrollBack():
			back.append(self.h.windowStart)
		self.assertEqual(back[-1], 0)

	def test_scroll_moves_to_next_line(self) -> None:
		obj = FakeObj("", Role.EDITABLETEXT, text="corto\nsegunda línea")
		api.setFocusObject(obj, [])
		self.h.handleObject(obj, "focus")
		self.assertEqual(self.h.text, "edt corto")
		self.h.scrollForward()
		self.assertEqual(self.h.text, "edt segunda línea")
		self.assertEqual(obj.caret, 6)

	def test_auto_scroll(self) -> None:
		self._show()
		with mock.patch("tiresias.queue_handler.callLater", return_value=7):
			self.h.setAutoScroll(True)
			self.assertTrue(self.h.autoScrollActive)
			self.h._autoScrollTick()
		self.assertGreater(self.h.windowStart, 0)
		self.h.setAutoScroll(False)


# ====================================================================== entrada braille
class InputTests(_BrailleCase):
	def setUp(self) -> None:
		super().setUp()
		self.typed: list[str] = []
		self.keys: list[str] = []
		self.inp = brailleInput.handler
		self.inp.cells = []
		self.inp.typed = ""
		self.inp.modifiers = set()
		p1 = mock.patch("tiresias.winapi.typeText", side_effect=self.typed.append)
		p2 = mock.patch.object(brailleInput.BrailleInputHandler, "_backspace", side_effect=lambda n: self.typed.append("<" * n))
		p3 = mock.patch("tiresias.input.gestures.KeyboardGesture.send", autospec=True, side_effect=lambda g: self.keys.append(g.normalizedKeys))
		p4 = mock.patch("tiresias.speech.speakMessage")
		for p in (p1, p2, p3, p4):
			p.start()
			self.addCleanup(p.stop)

	def test_literary_capital_and_number(self) -> None:
		conf["braille"]["inputTable"] = "es.tbl"
		for c in (D("46"), D("1"), D("3456"), D("1"), D("12")):
			self.inp.input(c)
		self.assertEqual("".join(self.typed), "A12")

	def test_own_g1_numbers(self) -> None:
		conf["braille"]["inputTable"] = "es-g1"
		for c in (D("3456"), D("1"), D("12")):
			self.inp.input(c)
		self.inp.space()
		self.assertEqual("".join(self.typed), "12 ")

	def test_computer_dot7(self) -> None:
		conf["braille"]["inputTable"] = "es-comp8"
		self.inp.input(D("47"))
		self.inp.space()
		self.inp.input(D("17"))
		self.assertEqual("".join(self.typed), "@ A")

	def test_contracted(self) -> None:
		conf["braille"]["inputTable"] = "en-ueb-g2.ctb"
		self.inp.input(D("2346"))
		self.assertEqual(self.typed, [])
		self.assertEqual(self.h._inputCells, [D("2346")])
		self.inp.space()
		self.assertEqual("".join(self.typed), "the ")
		self.assertEqual(self.h._inputCells, [])

	def test_erase_last_cell(self) -> None:
		conf["braille"]["inputTable"] = "es.tbl"
		self.inp.input(D("1"))
		self.inp.input(D("12"))
		self.inp.eraseLastCell()
		self.assertEqual("".join(self.typed), "ab<")
		self.inp.cells = []
		self.inp.eraseLastCell()
		self.assertEqual(self.keys, ["backspace"])

	def test_space_plus_dots_without_command_does_not_type(self) -> None:
		g = brailleInput.BrailleKeyboardGesture(D("13"), True)
		self.inp.handleGesture(g)
		self.assertEqual(self.typed, [])

	def test_modifier_toggle(self) -> None:
		conf["braille"]["inputTable"] = "es-comp8"
		self.inp.toggleModifier("control")
		self.inp.input(D("14"))
		self.assertEqual(self.keys, ["control+c"])
		self.assertEqual(self.inp.modifiers, set())

	def test_keyboard_identifiers_and_commands(self) -> None:
		from tiresias.global_commands import commands as gc

		g = brailleInput.BrailleKeyboardGesture(D("7"), False)
		self.assertEqual(gc.getScript(g).__name__, "script_braille_eraseLastCell")
		g = brailleInput.BrailleKeyboardGesture(D("12"), False)
		self.assertIn("bk:dots", g.identifiers)
		self.assertEqual(gc.getScript(g).__name__, "script_braille_dots")
		g = brailleInput.BrailleKeyboardGesture(D("148"), True)
		self.assertEqual(gc.getScript(g).__name__, "script_braille_toggleControl")

		class DriverGesture:
			identifiers = ["br(x):dot1+dot2"]
			dots = D("12")
			space = False

		dg = DriverGesture()
		brailleInput.addKeyboardIdentifiers(dg)
		self.assertEqual(dg.identifiers, ["br(x):dot1+dot2", "bk:dot1+dot2", "bk:dots"])

	def test_pc_keyboard(self) -> None:
		kb = brailleInput.PcBrailleKeyboard()
		kb.enabled = True
		conf["braille"]["pcKeyboardDots"] = 8
		with mock.patch("tiresias.queue_handler.queueFunction") as q:
			self.assertFalse(kb.onRawKey(scanCode=0x21, pressed=True))  # F = punto 1
			self.assertFalse(kb.onRawKey(scanCode=0x24, pressed=True))  # J = punto 4
			self.assertFalse(kb.onRawKey(scanCode=0x21, pressed=False))
			q.assert_not_called()
			self.assertFalse(kb.onRawKey(scanCode=0x24, pressed=False))
			q.assert_called_once()
			self.assertEqual(q.call_args[0][1:], (D("14"), False))
			# Otras teclas no se capturan.
			self.assertTrue(kb.onRawKey(scanCode=0x10, pressed=True))


class CommandInstallTests(unittest.TestCase):
	def test_installed(self) -> None:
		from tiresias.global_commands import GlobalCommands

		for func, _desc, _keys in brailleCommands._SCRIPTS:
			self.assertTrue(hasattr(GlobalCommands, func.__name__))
		self.assertEqual(GlobalCommands._classGestures.get("bk:dot8"), "braille_enter")
		self.assertEqual(GlobalCommands._classGestures.get("kb:tiresias+alt+t"), "braille_toggleMode")


if __name__ == "__main__":
	unittest.main()
