"""Revisión 10.11: modo exploración, texto y edición (auditoría y correcciones).

El árbol UIA se simula con los elementos falsos de ``test_browse``; no hace
falta ningún navegador ni se instalan ganchos.
"""

from __future__ import annotations

import os
import sys
import time
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_browse import FakeEl, group, text  # noqa: E402
from tiresias import textinfo, tree_interceptor  # noqa: E402
from tiresias.a11y import uia_client as uc  # noqa: E402
from tiresias.browse import extras, flexweb, loader, quicknav, reading_order, style, tables  # noqa: E402
from tiresias.browse.buffer import VirtualBuffer  # noqa: E402
from tiresias.browse.document import BrowseModeDocument, BufferTextInfo, lineAnchor, resolveAnchor  # noqa: E402
from tiresias.browse.textbuffer import TextPatternBuffer, normalizeText  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.objects.roles import Role, State  # noqa: E402


def link(t: str, **props) -> FakeEl:
	return FakeEl(uc.CT_HYPERLINK, t, [text(t)], P_ISKEYBOARDFOCUSABLE=True, **props)


def makeDoc(root: FakeEl) -> BrowseModeDocument:
	doc = BrowseModeDocument.__new__(BrowseModeDocument)
	d = doc.__dict__
	d.update(buffer=None, caret=0, selectionAnchor=None, _textPatternCache=False, _passThrough=False, _built=True, navLevel="line", _positionStack=[], _docKey="prueba", _docUrl="", _focusModeLocked=False, _disableAutoPassThrough=False, bufferKind="tree", _dirty=False, _rebuildTimer=None, _loadAnnounced=True)
	d["rootObject"] = mock.Mock(element=root, processID=0, appModule=None, windowClassName="")
	doc._loaderInit()
	doc._extrasInit()
	doc.backgroundLoading = False
	buf = VirtualBuffer(root)
	buf.build()
	d["buffer"] = buf
	return doc


class Base(unittest.TestCase):
	def setUp(self) -> None:
		self._saved = {k: dict(conf[k]) for k in ("browseMode", "documentFormatting")}
		conf["browseMode"]["useScreenLayout"] = True
		conf["browseMode"]["maxLineLength"] = 200
		conf["browseMode"]["containerLinesApart"] = False
		conf["browseMode"]["quickNavWrap"] = True
		self.messages: list[str] = []
		self.spoken: list[str] = []
		self.sounds: list[str] = []
		for p in (
			mock.patch("tiresias.speech.speakMessage", side_effect=lambda m, *a, **k: self.messages.append(m)),
			mock.patch("tiresias.speech.speakText", side_effect=lambda m, *a, **k: self.spoken.append(m)),
			mock.patch("tiresias.speech.speak", side_effect=lambda seq, *a, **k: self.spoken.append(seq)),
			mock.patch("tiresias.speech.cancelSpeech"),
			mock.patch("tiresias.audio.tones.playSound", side_effect=self.sounds.append),
			mock.patch("tiresias.api.setReviewPosition"),
		):
			p.start()
			self.addCleanup(p.stop)

	def tearDown(self) -> None:
		for sec, values in self._saved.items():
			for k, v in values.items():
				conf[sec][k] = v


class SyncThread:
	"""Sustituto de ``threading.Thread`` que ejecuta en el acto."""

	def __init__(self, target=None, args=(), kwargs=None, **_kw) -> None:
		self.target, self.args, self.kwargs = target, args, kwargs or {}

	def start(self) -> None:
		self.target(*self.args, **self.kwargs)


# ====================================================================== C1
class StructureEventsTests(Base):
	def test_each_document_has_its_own_handler(self) -> None:
		from tiresias.a11y import uia_handler

		calls = []
		listenerA = mock.Mock(onStructureChanged=lambda el: calls.append(("A", el)))
		listenerB = mock.Mock(onStructureChanged=lambda el: calls.append(("B", el)))
		saved = dict(uia_handler._structureListeners)
		self.addCleanup(lambda: (uia_handler._structureListeners.clear(), uia_handler._structureListeners.update(saved)))
		with mock.patch.object(uia_handler, "_suspended", False), mock.patch.object(uia_handler.uc, "client", mock.Mock()):
			self.assertTrue(uia_handler.registerStructureChanged(listenerA, "raizA"))
			self.assertTrue(uia_handler.registerStructureChanged(listenerB, "raizB"))
		handlerA = uia_handler._structureListeners[id(listenerA)][2]
		with mock.patch.object(uia_handler.queue_handler, "queueFunction", side_effect=lambda f, *a: f(*a)):
			handlerA.IUIAutomationStructureChangedEventHandler_HandleStructureChangedEvent("cambio", 0, None)
			# El manejador global ya no reparte nada.
			uia_handler._EventHandler.IUIAutomationStructureChangedEventHandler_HandleStructureChangedEvent(None, "otro", 0, None)
		self.assertEqual(calls, [("A", "cambio")])

	def test_change_from_another_document_is_ignored(self) -> None:
		inner = group(text("a"))
		root = FakeEl(uc.CT_DOCUMENT, "d", [inner])
		doc = makeDoc(root)
		foreign = FakeEl(uc.CT_TEXT, "de otra pestaña")
		walker = mock.Mock(GetParentElement=lambda el: None)
		with mock.patch.object(uc, "rawWalker", walker):
			self.assertIs(doc._nodeForElement(foreign), loader.OUTSIDE)
			self.assertEqual(doc._blocksToUpdate([foreign]), [])
			# Uno propio sigue funcionando junto al ajeno.
			self.assertEqual([b.rid for b in doc._blocksToUpdate([foreign, inner.children[0]])], [inner.rid])


# ====================================================================== C2
class Utf16Tests(unittest.TestCase):
	def test_converter(self) -> None:
		conv = textinfo.Utf16Converter("a😀bc")
		self.assertEqual(conv.utf16Length, 5)
		self.assertEqual([conv.utf16ToStr(i) for i in range(6)], [0, 1, 1, 2, 3, 4])
		self.assertEqual([conv.strToUtf16(i) for i in range(5)], [0, 1, 3, 4, 5])
		self.assertTrue(textinfo.Utf16Converter("sin emojis ñ").isTrivial)

	def test_edit_window_caret_after_emoji(self) -> None:
		from tiresias.objects import iaccessible

		obj = types.SimpleNamespace(windowHandle=1, windowClassName="Edit")
		w = iaccessible.win32ctl
		with mock.patch.object(w, "getWindowText", return_value="a😀bc"), mock.patch.object(w, "editGetSelection", return_value=(4, 4)), mock.patch.object(w, "isRichEditClass", return_value=False), mock.patch.object(w, "getWindowStyle", return_value=0):
			info = iaccessible.EditWindowTextInfo(obj, textinfo.POSITION_CARET)
			info.expand(textinfo.UNIT_CHARACTER)
			self.assertEqual(info.text, "c")
		with mock.patch.object(w, "getWindowText", return_value="a😀bc"), mock.patch.object(w, "isRichEditClass", return_value=False), mock.patch.object(w, "editSetSelection") as setSel:
			iaccessible.EditWindowTextInfo(obj, (3, 3)).updateCaret()
		setSel.assert_called_once_with(1, 4, 4)

	def test_ia2_offsets_are_converted(self) -> None:
		from tiresias.objects import iaccessible

		iface = types.SimpleNamespace(nCharacters=6, caretOffset=4, nSelections=0, text=lambda s, e: "a😀b c"[:5], textAtOffset=lambda off, b: (3, 6, ""))
		obj = types.SimpleNamespace()
		with mock.patch.object(iaccessible, "_ia2TextIfaceOf", return_value=iface):
			info = iaccessible.IA2TextInfo(obj, textinfo.POSITION_CARET)
			self.assertEqual(info.offsets, (3, 3))
			info.expand(textinfo.UNIT_WORD)
			self.assertEqual(info.offsets, (2, 5))


# ====================================================================== A1 y A10
class FocusTests(Base):
	def _doc(self):
		self.button = FakeEl(uc.CT_BUTTON, "Aceptar", P_ISKEYBOARDFOCUSABLE=True)
		root = FakeEl(uc.CT_DOCUMENT, "d", [group(text("Página de detrás")), group(self.button)])
		return makeDoc(root)

	def test_caret_goes_to_focus_after_update(self) -> None:
		doc = self._doc()
		focus = types.SimpleNamespace(runtimeId=self.button.rid, role=Role.BUTTON, states=set(), isFocusable=True)
		doc._pendingFocus = (self.button.rid, time.monotonic())
		with mock.patch("tiresias.api.getFocusObject", return_value=focus):
			doc._applyPendingFocus()
		self.assertEqual(doc.caret, doc.buffer.byRid[self.button.rid].start)
		self.assertNotIn("_pendingFocus", doc.__dict__)

	def test_focus_not_in_buffer_switches_to_focus_mode(self) -> None:
		doc = self._doc()
		focus = types.SimpleNamespace(runtimeId=(42, 99999), role=Role.BUTTON, states=set(), isFocusable=True)
		doc._pendingFocus = ((42, 99999), time.monotonic())
		with mock.patch("tiresias.api.getFocusObject", return_value=focus), mock.patch.object(BrowseModeDocument, "_set_passThrough", lambda self, v: setattr(self, "_passThrough", v)):
			doc._applyPendingFocus()
		self.assertTrue(doc._passThrough)

	def test_should_pass_through_like_nvda(self) -> None:
		doc = self._doc()

		def obj(role, *states, focusable=True):
			return types.SimpleNamespace(role=role, states=set(states), isFocusable=focusable, parent=None)

		for role in (Role.RADIOBUTTON, Role.TAB, Role.MENUITEM, Role.EDITABLETEXT, Role.COMBOBOX):
			self.assertTrue(doc.shouldPassThrough(obj(role)), role)
		self.assertTrue(doc.shouldPassThrough(obj(Role.GROUPING, State.EDITABLE)))
		self.assertFalse(doc.shouldPassThrough(obj(Role.LINK)))
		self.assertFalse(doc.shouldPassThrough(obj(Role.HEADING1)))
		self.assertFalse(doc.shouldPassThrough(obj(Role.LISTITEM, focusable=False)))
		self.assertFalse(doc.shouldPassThrough(obj(Role.DOCUMENT)))

	def test_leaving_field_to_plain_content_returns_to_browse_mode(self) -> None:
		doc = self._doc()
		doc._passThrough = True
		with mock.patch.object(BrowseModeDocument, "_set_passThrough", lambda self, v: setattr(self, "_passThrough", v)):
			doc._autoPassThroughForFocus(types.SimpleNamespace(role=Role.SECTION, states=set(), isFocusable=True, parent=None), None)
			self.assertFalse(doc._passThrough)
			doc._passThrough = True
			# En una celda o un menú se sigue en modo foco.
			doc._autoPassThroughForFocus(types.SimpleNamespace(role=Role.TABLECELL, states={State.READONLY}, isFocusable=False, parent=None), None)
			self.assertTrue(doc._passThrough)


# ====================================================================== A2
class LiveRegionTests(Base):
	def test_only_new_lines_are_spoken(self) -> None:
		log = FakeEl(uc.CT_GROUP, "", [group(text("Ana: hola")), group(text("Luis: qué tal"))], P_LIVESETTING=1)
		doc = makeDoc(FakeEl(uc.CT_DOCUMENT, "d", [log]))
		node = doc.buffer.byRid[log.rid]
		old = [ln for ln in doc.buffer.plainText(node.start, node.end).split("\n") if ln.strip()]
		doc._onLiveRegionText(log, log.rid, ["Ana: hola", "Luis: qué tal", "Ana: muy bien"], old, 1, False, "", False)
		self.assertEqual(self.spoken, ["Ana: muy bien"])
		# La siguiente se compara con la versión que se acaba de leer.
		doc._onLiveRegionText(log, log.rid, ["Ana: hola", "Luis: qué tal", "Ana: muy bien", "Luis: genial"], doc._liveSnapshots[log.rid], 1, False, "", False)
		self.assertEqual(self.spoken[-1], "Luis: genial")

	def test_atomic_region_is_read_whole(self) -> None:
		doc = makeDoc(FakeEl(uc.CT_DOCUMENT, "d", [group(text("x"))]))
		doc._onLiveRegionText(None, (1,), ["3 resultados", "página 1"], ["2 resultados", "página 1"], 1, True, "", False)
		self.assertEqual(self.spoken, ["3 resultados página 1"])

	def test_event_builds_off_the_core_thread(self) -> None:
		log = FakeEl(uc.CT_GROUP, "", [group(text("uno"))], P_LIVESETTING=1)
		doc = makeDoc(FakeEl(uc.CT_DOCUMENT, "d", [log]))
		obj = mock.Mock(element=log, runtimeId=log.rid)
		obj.name = ""
		worker = mock.Mock()
		with mock.patch.object(extras, "_liveWorker", return_value=worker):
			doc.event_liveRegionChange(obj, lambda: None)
		job = worker.submit.call_args.args[0]
		self.assertIs(job[0], doc)
		self.assertEqual(job[3], ["uno"])  # lo que ya estaba en el búfer


# ====================================================================== A3 y M6
class TextBufferTests(Base):
	def test_toggle_to_browse_mode_refreshes_word_buffer(self) -> None:
		doc = makeDoc(FakeEl(uc.CT_DOCUMENT, "d", [group(text("x"))]))
		doc.bufferKind = "lazyText"
		doc._passThrough = True
		with mock.patch.object(BrowseModeDocument, "requestRebuild") as req, mock.patch.object(BrowseModeDocument, "caretFromApplication"), mock.patch.object(BrowseModeDocument, "_set_passThrough", lambda self, v: setattr(self, "_passThrough", v)):
			doc.script_toggleFocusMode(mock.Mock())
		req.assert_called_once()
		self.assertFalse(doc._passThrough)

	def test_unchanged_text_reuses_previous_buffer(self) -> None:
		prev = TextPatternBuffer(None)
		prev._raw = "Hola\r"
		prev.text = "Hola\n"
		prev.nodes = ["nodo"]
		new = TextPatternBuffer(None)
		self.assertTrue(new._reuse(prev, "Hola\r"))
		self.assertEqual(new.text, "Hola\n")
		self.assertFalse(TextPatternBuffer(None)._reuse(prev, "Adiós\r"))


# ====================================================================== A4
class CaretWatchTests(unittest.TestCase):
	def test_lazy_story(self) -> None:
		calls = []

		class Info(textinfo.OffsetsTextInfo):
			caretMayExceedText = False

			def _getStoryText(self):
				calls.append(1)
				return "texto"

			def _getCaretOffset(self):
				return 2

		Info(None, textinfo.POSITION_CARET)
		Info(None, textinfo.POSITION_FIRST)
		self.assertEqual(calls, [])

	def test_poll_skips_text_while_caret_signature_is_unchanged(self) -> None:
		from tiresias.objects import behaviors

		obj = mock.Mock()
		obj.TextInfo = types.SimpleNamespace(caretSignature=lambda o: (5, 10))
		saved = behaviors._watch
		self.addCleanup(setattr, behaviors, "_watch", saved)
		behaviors._watch = {"obj": obj, "old": None, "deadline": time.monotonic() + 5, "done": mock.Mock(), "selection": False, "timer": None, "focusSeq": behaviors._focusChange[0], "sig": (5, 10)}
		with mock.patch.object(behaviors.queue_handler, "callLater", return_value=7):
			behaviors._pollWatch()
		obj._getCaretInfo.assert_not_called()
		self.assertEqual(behaviors._watch["timer"], 7)


# ====================================================================== A5
class WordMovementTests(unittest.TestCase):
	def test_backward_word_does_not_stop_on_spaces(self) -> None:
		t = "hola  mundo, adiós\nsegunda línea fin\n"
		info = textinfo.StaticTextInfo(None, (len(t) - 2, len(t) - 2), t)
		stops = []
		while info.move(textinfo.UNIT_WORD, -1):
			stops.append(t[info.offsets[0] :].split()[0] if t[info.offsets[0]].strip() else repr(t[info.offsets[0]]))
		self.assertEqual(stops, ["fin", "línea", "segunda", "adiós", ",", "mundo,", "hola"])

	def test_word_boundaries_from_line_start_match_full_scan(self) -> None:
		t = "uno dos\n  tres, cuatro\n\ncinco"
		for off in range(len(t)):
			full = textinfo._wordRe.finditer(t)
			expect = None
			for m in full:
				if m.start() <= off < m.end():
					expect = m
					break
			s, _e = textinfo.findWordBoundaries(t, off)
			self.assertEqual(s, expect.start(), off)


# ====================================================================== A6 y A8
class LoaderTests(Base):
	def test_loading_indicator_only_on_first_load(self) -> None:
		doc = makeDoc(FakeEl(uc.CT_DOCUMENT, "d", [group(text("x"))]))
		doc.backgroundLoading = True
		with mock.patch.object(loader.threading, "Thread", mock.Mock()), mock.patch.object(BrowseModeDocument, "_scheduleLoadingIndicator") as ind:
			doc.requestRebuild()
		ind.assert_not_called()
		doc._building = False
		doc._built = False
		with mock.patch.object(loader.threading, "Thread", mock.Mock()), mock.patch.object(BrowseModeDocument, "_scheduleLoadingIndicator") as ind:
			doc.requestRebuild(initial=True)
		ind.assert_called_once()

	def test_announcement_does_not_wait_for_another_rebuild(self) -> None:
		doc = makeDoc(FakeEl(uc.CT_DOCUMENT, "d", [group(text("x"))]))
		doc._buildGeneration = 2
		doc._building = True
		doc._buildAgain = True
		with mock.patch.object(BrowseModeDocument, "_installBuffer"), mock.patch.object(BrowseModeDocument, "_notifyNewNodes"), mock.patch.object(BrowseModeDocument, "_onReady") as ready, mock.patch.object(BrowseModeDocument, "requestRebuild") as req:
			doc._onBuildDone(2, doc.buffer, None, False)
		ready.assert_called_once()
		req.assert_called_once()

	def test_first_load_timeout_is_retried(self) -> None:
		import comtypes

		doc = makeDoc(FakeEl(uc.CT_DOCUMENT, "d", []))
		doc.buffer = None
		doc._buildGeneration = 1
		doc._building = True
		with mock.patch.object(BrowseModeDocument, "makeBuffer", return_value=VirtualBuffer(None)), mock.patch.object(loader.queue_handler, "callLater") as later:
			doc._onBuildDone(1, None, comtypes.COMError(-2146233083, "tiempo agotado", None), True)
		later.assert_called_once()
		self.assertIs(later.call_args.args[1].__func__, BrowseModeDocument._retryLoad)

	def test_frequent_full_rebuilds_are_throttled(self) -> None:
		doc = makeDoc(FakeEl(uc.CT_DOCUMENT, "d", [group(text("x"))]))
		doc._lastAutoRebuild = time.monotonic()
		with mock.patch.object(BrowseModeDocument, "requestRebuild") as req, mock.patch.object(loader.queue_handler, "callLater", return_value=3):
			doc._requestAutoRebuild()
		req.assert_not_called()
		self.assertTrue(doc._fullRebuildPending)


# ====================================================================== A7
class AliveTests(Base):
	def test_alive_check_is_cached(self) -> None:
		el = mock.Mock(CurrentProcessId=5, CurrentControlType=uc.CT_DOCUMENT)
		doc = makeDoc(FakeEl(uc.CT_DOCUMENT, "d", []))
		doc.rootObject = mock.Mock(element=el, windowHandle=0, processID=5)
		self.assertTrue(doc.isAlive)
		el.CurrentControlType = 0
		self.assertTrue(doc.isAlive)  # dentro del intervalo no se vuelve a preguntar
		doc._aliveChecked = (time.monotonic() - 60, True)
		self.assertFalse(doc.isAlive)

	def test_other_process_is_not_contained(self) -> None:
		ti = tree_interceptor.TreeInterceptor(types.SimpleNamespace(processID=10))
		obj = mock.Mock(processID=11)
		self.assertFalse(ti.contains(obj))
		obj.iterAncestors.assert_not_called()


# ====================================================================== A9
class SplitWordTests(Base):
	def test_touching_text_leaves_are_joined(self) -> None:
		root = FakeEl(uc.CT_DOCUMENT, "d", [group(text("Mad", P_BOUNDINGRECT=(10, 10, 30, 16)), text("rid es", P_BOUNDINGRECT=(40, 10, 50, 16)))])
		buf = VirtualBuffer(root)
		buf.build()
		self.assertIn("Madrid es", buf.text)

	def test_separate_words_keep_their_space(self) -> None:
		root = FakeEl(uc.CT_DOCUMENT, "d", [group(text("Hola", P_BOUNDINGRECT=(10, 10, 30, 16)), text("mundo", P_BOUNDINGRECT=(45, 10, 40, 16)), text(" sin", P_BOUNDINGRECT=(85, 10, 20, 16)))])
		buf = VirtualBuffer(root)
		buf.build()
		self.assertIn("Hola mundo sin", buf.text)


# ====================================================================== M1
class BufferTextInfoTests(Base):
	def test_offsets_follow_a_splice(self) -> None:
		inner = group(text("corto"))
		root = FakeEl(uc.CT_DOCUMENT, "d", [inner, group(text("Final del documento"))])
		doc = makeDoc(root)
		buf = doc.buffer
		pos = buf.text.find("Final")
		info = BufferTextInfo(doc, (pos, pos))
		inner.children = [text("un texto bastante más largo que antes")]
		doc._updateBlock(buf.byRid[inner.rid])
		info.expand(textinfo.UNIT_LINE)
		self.assertEqual(info.text.strip(), "Final del documento")

	def test_offsets_follow_a_full_rebuild(self) -> None:
		target = group(text("Final del documento"))
		root = FakeEl(uc.CT_DOCUMENT, "d", [group(text("corto")), target])
		doc = makeDoc(root)
		info = BufferTextInfo(doc, (doc.buffer.text.find("Final"), doc.buffer.text.find("Final")))
		root.children.insert(0, group(text("Algo nuevo al principio")))
		new = VirtualBuffer(root)
		new.build()
		doc.buffer = new
		info.expand(textinfo.UNIT_LINE)
		self.assertEqual(info.text.strip(), "Final del documento")


# ====================================================================== M2, B5 y B7
class PartialUpdateTests(Base):
	def test_partial_update_runs_in_background_and_splices(self) -> None:
		inner = group(text("viejo"))
		root = FakeEl(uc.CT_DOCUMENT, "d", [group(text("a")), inner])
		doc = makeDoc(root)
		doc.backgroundLoading = True
		inner.children = [text("nuevo")]
		doc._pendingElements = [inner.children[0]]
		doc.__dict__["_docUrl"] = "http://viejo"
		calls = []
		with mock.patch.object(loader.threading, "Thread", SyncThread), mock.patch.object(loader.queue_handler, "queueFunction", side_effect=lambda f, *a: calls.append(f.__name__) or f(*a)), mock.patch.object(uc, "rawWalker", None):
			doc.applyPendingUpdates()
		self.assertIn("_onPartialDone", calls)
		self.assertIn("nuevo", doc.buffer.text)
		self.assertNotIn("_docUrl", doc.__dict__)
		self.assertFalse(doc._building)

	def test_selection_inside_rebuilt_block_is_dropped(self) -> None:
		inner = group(text("viejo texto"))
		root = FakeEl(uc.CT_DOCUMENT, "d", [group(text("a")), inner])
		doc = makeDoc(root)
		block = doc.buffer.byRid[inner.rid]
		doc.selectionAnchor = block.start + 2
		doc._updateBlock(block)
		self.assertIsNone(doc.selectionAnchor)


# ====================================================================== M3
class ActivationTests(Base):
	def test_plain_text_is_not_clicked(self) -> None:
		doc = makeDoc(FakeEl(uc.CT_DOCUMENT, "d", [group(text("Solo texto"))]))
		with mock.patch("tiresias.mouse.click") as click, mock.patch.object(BrowseModeDocument, "objectForNode") as objFor:
			doc.activateAt(doc.buffer.text.find("texto"))
		click.assert_not_called()
		objFor.assert_not_called()
		self.assertEqual(self.messages, ["No se puede activar"])

	def test_click_fallback_uses_current_position(self) -> None:
		el = FakeEl(uc.CT_BUTTON, "B", P_BOUNDINGRECT=(0, 0, 10, 10))
		doc = makeDoc(FakeEl(uc.CT_DOCUMENT, "d", [el]))
		node = doc.buffer.byRid[el.rid]
		with mock.patch("tiresias.browse.buffer.liveNodeRect", return_value=(100, 200, 20, 10)), mock.patch("tiresias.mouse.click") as click:
			self.assertTrue(doc.clickNode(node))
		click.assert_called_once_with(110, 205)


# ====================================================================== M4
class TableTests(Base):
	def test_table_key_is_computed_once(self) -> None:
		def cell(t, r, c):
			return FakeEl(uc.CT_DATAITEM, "", [text(t)], P_GRIDITEMROW=r, P_GRIDITEMCOLUMN=c, P_ARIAROLE="cell")

		rows = [FakeEl(uc.CT_DATAITEM, "", [cell(f"c{r}{c}", r, c) for c in range(2)], P_ARIAROLE="row") for r in range(3)]
		tbl = FakeEl(uc.CT_TABLE, "", rows)
		doc = makeDoc(FakeEl(uc.CT_DOCUMENT, "d", [tbl]))
		table = doc.buffer.byRid[tbl.rid]
		self.assertEqual(doc._tableKey(table), ("prueba", 0))
		cache = doc.buffer.__dict__["_tableIndex"]
		doc._tableKey(table)
		self.assertIs(doc.buffer.__dict__["_tableIndex"], cache)

	def test_header_lookups_stop_after_budget(self) -> None:
		doc = makeDoc(FakeEl(uc.CT_DOCUMENT, "d", [group(text("x"))]))
		cellNode = doc.buffer.nodes[-1]
		cellNode.element = mock.Mock()
		doc._headerBudget = time.monotonic() - 1
		self.assertEqual(doc._uiaHeaders(cellNode), ("", ""))
		cellNode.element.GetCurrentPattern.assert_not_called()


# ====================================================================== M5
class RangeMappingTests(unittest.TestCase):
	def test_align_index(self) -> None:
		self.assertEqual(style.alignIndex("palabra", "  pala\xadbra", 5), 8)
		self.assertEqual(style.alignIndex("a\nb", "a\r\nb", 2), 3)
		self.assertIsNone(style.alignIndex("Cerrar", "X", 3))

	def test_move_to_text_index_corrects_provider_units(self) -> None:
		# Proveedor que cuenta un emoji como dos «caracteres».
		text_ = "😀abc"
		units = [0, 0, 1, 2, 3, 4]  # unidad del proveedor -> índice de Python

		class R:
			def __init__(self, s=0, e=0):
				self.s, self.e = s, e

			def Clone(self):
				return R(self.s, self.e)

			def Move(self, unit, n):
				self.s = max(0, min(5, self.s + n))
				self.e = self.s
				return n

			def MoveEndpointByRange(self, ep, other, oep):
				self.e = other.s

			def GetText(self, n):
				return text_[units[self.s] : units[self.e]]

		base, r = R(0, 5), R(0, 0)
		style.moveToTextIndex(base, r, 2)
		self.assertEqual(units[r.s], 2)


# ====================================================================== M7
class LoadingKeysTests(Base):
	def test_keys_pass_through_while_loading(self) -> None:
		doc = makeDoc(FakeEl(uc.CT_DOCUMENT, "d", []))
		doc._built = False
		g = mock.Mock(modifierNames=[])
		with mock.patch("tiresias.tree_interceptor.TreeInterceptor.getScript", create=True, return_value=BrowseModeDocument.script_tab):
			pass
		with mock.patch("tiresias.baseobject.ScriptableObject.getScript", return_value=doc.script_tab):
			self.assertIsNone(doc.getScript(g))
		with mock.patch("tiresias.baseobject.ScriptableObject.getScript", return_value=doc.script_quickNavNextHeading):
			self.assertEqual(doc.getScript(g), doc.script_documentLoading)


# ====================================================================== M8
class WrapTests(Base):
	def test_wrap_stops_at_first_match(self) -> None:
		root = FakeEl(uc.CT_DOCUMENT, "d", [group(link("uno")), group(text("x")), group(link("dos"))])
		doc = makeDoc(root)
		doc.caret = doc.buffer.text.find("dos")
		evaluated = []

		def pred(n):
			evaluated.append(n)
			return n.role == Role.LINK

		with mock.patch.object(quicknav, "dynamicPredicate", return_value=pred), mock.patch.object(BrowseModeDocument, "_moveCaret", lambda self, off, *a, **k: setattr(self, "caret", off)):
			doc.quickNav("link", 1)
		self.assertTrue(doc.buffer.text[doc.caret :].strip().startswith("uno"))
		self.assertLess(len(evaluated), len(doc.buffer.nodes) * 2)

	def test_style_predicate_has_a_budget(self) -> None:
		pred = quicknav._budgeted(lambda n: False, budget=0.0)
		pred(1)
		time.sleep(0.01)
		calls = []
		pred2 = quicknav._budgeted(lambda n: calls.append(n) or False, budget=0.0)
		pred2(1)
		time.sleep(0.01)
		pred2(2)
		self.assertEqual(calls, [1])


# ====================================================================== M9
class FlexWebTests(Base):
	def test_rule_hiding_most_of_the_page_is_detected(self) -> None:
		root = FakeEl(uc.CT_DOCUMENT, "d", [group(text("todo el contenido de la página " * 5), P_CLASSNAME="container"), group(text("pie"))])
		buf = VirtualBuffer(root)
		buf.build()
		self.assertGreater(flexweb.hiddenFraction({"ct": 0, "id": "", "name": "", "cls": "container"}, buf), 0.5)
		self.assertLess(flexweb.hiddenFraction({"ct": 0, "id": "", "name": "", "cls": "nada"}, buf), 0.01)


# ====================================================================== M10
class ReadingOrderTests(unittest.TestCase):
	def test_text_key_only_for_matching_control_types(self) -> None:
		order = reading_order.ReadingOrder([{"container": f"{uc.CT_LIST}:Menú", "order": ["a", "b"]}])
		with mock.patch.object(reading_order, "elementText", side_effect=AssertionError("no debe recorrer")):
			self.assertIsNone(order._containerKey(FakeEl(uc.CT_GROUP, "", [])))
		self.assertEqual(order._containerKey(FakeEl(uc.CT_GROUP, "", [], P_AUTOMATIONID="x")), f"{uc.CT_GROUP}#x")


# ====================================================================== B1 y B2
class TextPatternBufferTests(unittest.TestCase):
	def test_overlapping_chunks_are_clipped(self) -> None:
		from tiresias.browse.buffer import Node

		b = TextPatternBuffer(None)
		b.text = "primer parrafo con enlace\nsegundo parrafo sigue\n"

		def N(role, s, e):
			n = Node()
			n.role, n.start, n.end = role, s, e
			return n

		b._assemble([N(Role.DOCUMENT, 0, len(b.text)), N(Role.PARAGRAPH, 0, 26), N(Role.PARAGRAPH, 26, len(b.text)), N(Role.LINK, 19, 33)])
		pos = 0
		for s, e, _n in b.chunks:
			self.assertGreaterEqual(s, pos)
			pos = e
		self.assertEqual("".join(b.text[s:e] for s, e, _n in b.chunks), b.text)

	def test_crlf_does_not_add_blank_lines(self) -> None:
		self.assertEqual(normalizeText("uno\r\ndos\r\n"), "uno \ndos \n")
		self.assertEqual(len(normalizeText("a\r\nb")), 4)


# ====================================================================== B4
class AnchorTests(Base):
	def test_bookmark_follows_its_line(self) -> None:
		root = FakeEl(uc.CT_DOCUMENT, "d", [group(text("Primera")), group(text("Línea marcada aquí"))])
		buf = VirtualBuffer(root)
		buf.build()
		start, txt = lineAnchor(buf, buf.text.find("marcada"))
		root.children.insert(0, group(text("Contenido nuevo arriba")))
		new = VirtualBuffer(root)
		new.build()
		self.assertEqual(resolveAnchor(new, start, txt), new.text.find("Línea marcada"))


# ====================================================================== B8
class BackspaceTests(unittest.TestCase):
	def test_read_only_field_does_not_announce(self) -> None:
		from tiresias.objects import behaviors

		obj = mock.Mock()
		obj.states = {State.READONLY}
		obj.role = Role.EDITABLETEXT
		obj._isTerminalLike = lambda: False
		g = mock.Mock()
		with mock.patch("tiresias.speech.speakCharacter") as sc:
			behaviors.EditableText.script_caret_backspaceCharacter(obj, g)
		g.send.assert_called_once()
		sc.assert_not_called()
		obj._getCaretInfo.assert_not_called()


# ====================================================================== módulos de aplicación
WA_BASE = os.path.join(ROOT, "data", "addons", "whatsapp")


def _waModules():
	import importlib

	for name, path in (("rev1011_wa", WA_BASE), ("rev1011_wa.appModules", os.path.join(WA_BASE, "appModules")), ("rev1011_wa.globalPlugins", os.path.join(WA_BASE, "globalPlugins"))):
		if name not in sys.modules:
			mod = types.ModuleType(name)
			mod.__path__ = [path]  # type: ignore[attr-defined]
			sys.modules[name] = mod
	return importlib.import_module("rev1011_wa.appModules.whatsapp_root"), importlib.import_module("rev1011_wa.appModules.wa_strings")


class _WaNode:
	def __init__(self, name="", ct=uc.CT_TEXT, cls="", children=()):
		self.name, self.ct, self.cls = name, ct, cls
		self.children = list(children)
		self.parent = None
		for c in self.children:
			c.parent = self

	@property
	def isMessage(self):
		return "focusable-list-item" in self.cls

	def walk(self):
		yield self
		for c in self.children:
			yield from c.walk()

	def texts(self):
		return [n.name for n in self.walk() if n.ct == uc.CT_TEXT and n.name]


class WhatsAppTests(unittest.TestCase):
	def setUp(self) -> None:
		self.root, self.S = _waModules()
		self._saved = dict(conf["whatsapp"])
		conf["whatsapp"]["filterPhoneNumbersInMessages"] = True
		conf["whatsapp"]["filterMaybePrefix"] = True
		conf["whatsapp"]["filterHints"] = True

	def tearDown(self) -> None:
		for k, v in self._saved.items():
			conf["whatsapp"][k] = v

	def test_message_content_keeps_numbers(self) -> None:
		msg = _WaNode(cls="focusable-list-item", children=[_WaNode("Mi número es 612 345 678, llámame"), _WaNode("10:45")])
		self.assertIn("612 345 678", self.root.messageText(msg))
		msg = _WaNode(cls="focusable-list-item", children=[_WaNode("Quizás mañana vaya")])
		self.assertEqual(self.root.messageText(msg), "Quizás mañana vaya")

	def test_unsaved_sender_is_filtered(self) -> None:
		msg = _WaNode(cls="focusable-list-item", children=[_WaNode("‪+34 612 345 678‬"), _WaNode("Hola")])
		self.assertEqual(self.root.messageText(msg), "Hola")
		# Para copiar: todo.
		self.assertIn("612", self.root.messageText(msg, forCopy=True))

	def test_maybe_prefix_is_a_whole_word(self) -> None:
		self.assertEqual(self.root.cleanText("Maybelline es una marca"), "Maybelline es una marca")
		self.assertEqual(self.root.cleanText("Quizás Ana"), "Ana")

	def test_recording_ignores_message_times_and_other_delete_buttons(self) -> None:
		app = self.root.AppModule.__new__(self.root.AppModule)
		messages = _WaNode(children=[_WaNode(cls="focusable-list-item", children=[_WaNode("hola"), _WaNode("10:45"), _WaNode("Eliminar mensaje", ct=uc.CT_BUTTON)])])
		main = _WaNode(children=[messages, _WaNode("Eliminar mensaje", ct=uc.CT_BUTTON)])
		self.assertFalse(app._isRecording(main))
		footer = _WaNode(children=[_WaNode("Eliminar", ct=uc.CT_BUTTON), _WaNode("0:07")])
		main.children.append(footer)
		self.assertTrue(app._isRecording(main))

	def test_version_was_raised(self) -> None:
		import json

		with open(os.path.join(WA_BASE, "manifest.json"), encoding="utf-8") as f:
			self.assertEqual(json.load(f)["version"], "1.0.4")


class OfficeTests(Base):
	def test_excel_say_all_reads_in_blocks(self) -> None:
		from tiresias.appmodules import _excel

		requested = []

		class Cell:
			def __init__(self, r, c):
				self.Row, self.Column = r, c

		class Rng:
			def __init__(self, a, b):
				requested.append((a.Row, b.Row))
				self.Value2 = tuple(tuple(f"v{r}" if r % 100 == 1 else None for _c in range(a.Column, b.Column + 1)) for r in range(a.Row, b.Row + 1))

		sheet = types.SimpleNamespace(UsedRange=types.SimpleNamespace(Row=1, Column=1, Rows=types.SimpleNamespace(Count=1048576), Columns=types.SimpleNamespace(Count=2)), Cells=Cell, Range=Rng)
		app = types.SimpleNamespace(ActiveSheet=sheet, ActiveCell=Cell(1, 1))
		with mock.patch.object(_excel, "_app", return_value=app), mock.patch.object(_excel, "READ_BUDGET", 0.2):
			cells = _excel.om_cellsFromActive(1)
		self.assertTrue(cells)
		self.assertTrue(all(b - a < _excel.READ_BLOCK_ROWS for a, b in requested))

	def test_cancelled_office_call_does_not_run_late(self) -> None:
		import queue as _queue
		import threading

		from tiresias.appmodules import _office

		w = _office._Worker()
		q = _queue.Queue()
		ran = []
		done = threading.Event()
		q.put((lambda: ran.append(1), (), {"cancelled": True}, done))
		q.put(None)
		w._run(q)
		self.assertEqual(ran, [])
		self.assertTrue(done.is_set())

	def test_powerpoint_copy_is_reused_between_slides(self) -> None:
		from tiresias.appmodules import _ppt

		pres = mock.Mock(FullName="https://onedrive/x.pptx", Saved=False)
		saved = dict(_ppt._eqCache)
		self.addCleanup(lambda: (_ppt._eqCache.clear(), _ppt._eqCache.update(saved)))
		_ppt._eqCache.clear()
		with mock.patch.object(_ppt, "pptxEquations", return_value={1: [{"id": 1}], 2: [{"id": 2}]}):
			_ppt.presentationEquations(pres, 1, ("a",))
			self.assertEqual(_ppt.presentationEquations(pres, 2, ("b",)), [{"id": 2}])
		self.assertEqual(pres.SaveCopyAs.call_count, 1)
		with mock.patch.object(_ppt, "pptxEquations", return_value={1: []}):
			_ppt.presentationEquations(pres, 1, ("cambiada",))
		self.assertEqual(pres.SaveCopyAs.call_count, 2)

	def test_libreoffice_spanish_shortcut_only_on_change(self) -> None:
		from tiresias.appmodules import soffice

		app = soffice.AppModule.__new__(soffice.AppModule)
		g = mock.Mock(identifiers=["kb:control+s"])
		btn = mock.Mock(states={State.PRESSED})
		with mock.patch.object(soffice.api, "getFocusObject", return_value=mock.Mock(role=Role.DOCUMENT)), mock.patch.object(soffice.api, "getForegroundObject"), mock.patch.object(soffice, "findToggle", return_value=btn), mock.patch.object(soffice.queue_handler, "callLater", side_effect=lambda ms, f: f()):
			app.script_formatShortcut(g)
		g.send.assert_called_once()
		self.assertEqual(self.messages, [])


class OtherAppTests(Base):
	def test_zoom_ignores_plain_label_changes(self) -> None:
		from tiresias.appmodules import zoom

		app = zoom.AppModule.__new__(zoom.AppModule)
		app.handleIncoming = mock.Mock()
		label = types.SimpleNamespace(role=Role.STATICTEXT, name="Hablando: Ana", parent=types.SimpleNamespace(role=Role.PANE))
		nh = mock.Mock()
		app.event_nameChange(label, nh)
		nh.assert_called_once()
		app.handleIncoming.assert_not_called()
		alert = types.SimpleNamespace(role=Role.STATICTEXT, name="Ana se unió", parent=types.SimpleNamespace(role=Role.ALERT))
		app.event_nameChange(alert, mock.Mock())
		app.handleIncoming.assert_called_once()

	def test_new_outlook_and_search_start_in_focus_mode(self) -> None:
		from tiresias.appmodules import handler, olk, searchhost

		self.assertTrue(olk.AppModule.disableBrowseModeByDefault)
		self.assertTrue(searchhost.AppModule.disableBrowseModeByDefault)
		self.assertEqual(handler.EXECUTABLE_ALIASES["betterbird"], "thunderbird")

	def test_disable_browse_mode_pauses_auto_switching(self) -> None:
		class TI(tree_interceptor.TreeInterceptor):
			def __init__(self, root):
				super().__init__(root)
				self._disableAutoPassThrough = False

		cand = types.SimpleNamespace(treeInterceptorClass=TI, shouldCreateTreeInterceptor=True, appModule=types.SimpleNamespace(disableBrowseModeByDefault=True))
		saved = list(tree_interceptor.runningTable)
		self.addCleanup(lambda: (tree_interceptor.runningTable.clear(), tree_interceptor.runningTable.extend(saved)))
		with mock.patch.object(tree_interceptor, "getTreeInterceptor", return_value=None):
			ti = tree_interceptor.update(cand, [])
		self.assertTrue(ti.passThrough)
		self.assertTrue(ti._disableAutoPassThrough)


if __name__ == "__main__":
	unittest.main()
