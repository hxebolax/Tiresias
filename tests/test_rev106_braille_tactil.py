"""Revisión 1.0.6: braille (con los controladores de líneas) y soporte táctil.

Una prueba de regresión por cada fallo corregido en la auditoría. No se usa
hardware: las conexiones, los documentos y los gestos son simulados.
"""

from __future__ import annotations

import inspect
import threading
import time
import unittest
from unittest import mock

import braille_sim  # noqa: F401  (prepara rutas y datos)
import test_braille as tb

from tiresias import api, braille, textinfo
from tiresias.braille import commands as brailleCommands
from tiresias.braille import input as brailleInput
from tiresias.braille import presenter, tables
from tiresias.braille.drivers import base as driversBase
from tiresias.braille.drivers import detect, hwio, winusb
from tiresias.config import conf
from tiresias.input import core as inputCore
from tiresias.objects.roles import Role

D = tables.dots


# ====================================================================== 1. bloqueo mutuo
class WriteDeadlockTests(unittest.TestCase):
	"""Tras 3 escrituras fallidas, el aviso cierra la conexión sin colgarse."""

	def _runWrites(self, io) -> threading.Thread:
		def run() -> None:
			for _i in range(hwio.MAX_WRITE_FAILURES):
				try:
					io.write(b"\x01\x02")
				except hwio.IoError:
					pass

		t = threading.Thread(target=run, daemon=True)
		t.start()
		t.join(3)
		return t

	def test_overlapped_io_reports_outside_lock(self) -> None:
		io = hwio._OverlappedIo.__new__(hwio._OverlappedIo)
		io._readHandle = io._writeHandle = 1
		io._readSize = 1
		io._onReceive = lambda data: None
		io._stopEvent = io._writeEvent = 2
		io._writeLock = threading.Lock()
		io._closed = False
		io._errorReported = False
		io._writeFailures = 0
		io._thread = threading.Thread(target=lambda: None)
		io.port = "COM9"
		errors: list[int] = []

		def onError(code: int) -> None:
			errors.append(code)
			io.close()

		io._onError = onError
		k32 = mock.Mock()
		k32.WriteFile.return_value = 0
		with mock.patch.object(hwio, "kernel32", k32), mock.patch("ctypes.get_last_error", return_value=31):
			t = self._runWrites(io)
		self.assertFalse(t.is_alive(), "write() se ha quedado bloqueado")
		self.assertEqual(errors, [31])
		self.assertTrue(io._closed)
		k32.CloseHandle.assert_called()

	def test_winusb_reports_outside_lock(self) -> None:
		io = winusb.WinUsbDevice.__new__(winusb.WinUsbDevice)
		io.port = "usb"
		io._lib = mock.Mock()
		io._lib.WinUsb_WritePipe.return_value = 0
		io._closed = False
		io._errorReported = False
		io._writeFailures = 0
		io._writeLock = threading.Lock()
		io._usb = mock.Mock()
		io._file = 0
		io.pipeOut = 1
		io._stopEvent = io._writeEvent = 2
		io._thread = threading.Thread(target=lambda: None)
		errors: list[int] = []

		def onError(code: int) -> None:
			errors.append(code)
			io.close()

		io._onError = onError
		with mock.patch.object(hwio, "kernel32", mock.Mock()), mock.patch("ctypes.get_last_error", return_value=31):
			t = self._runWrites(io)
		self.assertFalse(t.is_alive(), "write() se ha quedado bloqueado")
		self.assertEqual(errors, [31])
		io._lib.WinUsb_Free.assert_called_once()


# ====================================================================== simulación del modo exploración
class FakeBuffer:
	def __init__(self, text: str) -> None:
		self.text = text

	def lineBounds(self, offset: int) -> tuple[int, int]:
		start = self.text.rfind("\n", 0, offset) + 1
		end = self.text.find("\n", offset)
		return start, (len(self.text) if end == -1 else end + 1)

	def nodeAt(self, offset: int):
		return None


class FakeBrowseDoc:
	def __init__(self, text: str, caret: int = 0) -> None:
		self.buffer = FakeBuffer(text)
		self.caret = caret
		self.selectionAnchor = None
		self.moves: list[tuple[int, object]] = []
		self.activated: list[int] = []

	def _afterCaretMove(self, node) -> None:
		pass

	def _updateBraille(self, start: int, end: int) -> None:
		braille.handler.handleBrowseLine(self.buffer.text[start:end], self.caret - start)

	def _moveCaret(self, offset: int, speakUnit=textinfo.UNIT_LINE, node=None) -> None:
		self.moves.append((offset, speakUnit))
		self.caret = offset
		self._updateBraille(*self.buffer.lineBounds(offset))

	def activateAt(self, offset: int) -> None:
		self.activated.append(offset)


class _Case(tb._BrailleCase):
	def setUp(self) -> None:
		super().setUp()
		p = mock.patch("tiresias.speech.speakMessage")
		self.spoken = p.start()
		self.addCleanup(p.stop)
		self._savedNav = conf["braille"]["speakOnNavigatingByUnit"]
		self.addCleanup(lambda: conf["braille"].__setitem__("speakOnNavigatingByUnit", self._savedNav))
		conf["braille"]["speakOnNavigatingByUnit"] = False


# ====================================================================== 2. desplazamiento en modo exploración
class BrowseScrollTests(_Case):
	cells = 10
	TEXT = "primera linea bastante larga\nsegunda\ntercera linea larga de verdad\n"

	def _doc(self, caret: int = 0) -> FakeBrowseDoc:
		doc = FakeBrowseDoc(self.TEXT, caret)
		p = mock.patch.object(api, "getCaretObject", return_value=doc)
		p.start()
		self.addCleanup(p.stop)
		doc._updateBraille(*doc.buffer.lineBounds(caret))
		return doc

	def test_scroll_forward_passes_to_next_line(self) -> None:
		doc = self._doc()
		while self.h.scrollForward():
			if doc.caret:
				break
		self.assertEqual(doc.caret, self.TEXT.index("segunda"))
		self.assertEqual(self.h.text, "segunda")
		self.assertEqual(doc.moves, [], "sin «leer al navegar» no se usa _moveCaret (no habla)")

	def test_scroll_back_shows_end_of_previous_line(self) -> None:
		third = self.TEXT.index("tercera")
		doc = self._doc(third)
		self.assertEqual(self.h.windowStart, 0)
		self.assertTrue(self.h.scrollBack())
		self.assertEqual(doc.caret, self.TEXT.index("segunda"))
		# Línea corta: cabe entera. Desde la segunda se vuelve a la primera, larga.
		self.assertTrue(self.h.scrollBack())
		self.assertEqual(doc.caret, 0)
		self.assertGreater(self.h.windowStart, 0, "al retroceder se muestra el final de la línea")
		self.assertEqual(self.h.text, "primera linea bastante larga")

	def test_speak_on_navigating_uses_line_speech(self) -> None:
		conf["braille"]["speakOnNavigatingByUnit"] = True
		doc = self._doc(self.TEXT.index("segunda"))
		self.assertTrue(self.h.scrollForward())
		self.assertEqual(doc.moves, [(self.TEXT.index("tercera"), textinfo.UNIT_LINE)])

	def test_auto_scroll_goes_line_by_line(self) -> None:
		doc = self._doc()
		with mock.patch("tiresias.queue_handler.callLater", return_value=7):
			self.h.setAutoScroll(True)
			for _i in range(30):
				if not self.h.autoScrollActive or doc.caret >= self.TEXT.index("tercera"):
					break
				self.h._autoScrollTick()
		self.assertEqual(doc.caret, self.TEXT.index("tercera"))
		self.assertEqual(doc.moves, [])
		self.h.setAutoScroll(False)

	def test_last_line_ends_auto_scroll(self) -> None:
		doc = self._doc(self.TEXT.index("tercera"))
		self.h.windowStart = len(self.h._translation.cells) - 1
		self.assertFalse(self.h._moveLine(1))
		self.assertEqual(doc.caret, self.TEXT.index("tercera"))


# ====================================================================== 3. retroceder en un campo de edición
class EditPreviousLineTests(_Case):
	cells = 10

	def test_previous_line_caret_at_end(self) -> None:
		text = "primera linea bastante larga\nsegunda"
		obj = tb.FakeObj("", Role.EDITABLETEXT, text=text)
		obj.caret = text.index("segunda")
		api.setFocusObject(obj, [])
		self.h.handleObject(obj, "focus")
		second = obj.caret
		for _i in range(5):
			self.assertTrue(self.h.scrollBack())
			if obj.caret != second:
				break
		# El cursor queda al final de la línea anterior (como NVDA)...
		self.assertEqual(obj.caret, text.index("\n"))
		self.assertGreater(self.h.windowStart, 0)
		# ...y el evento de cursor que llega después no devuelve la ventana al principio.
		self.h.handleCaretMove(obj.makeTextInfo(textinfo.POSITION_CARET))
		self.assertGreater(self.h.windowStart, 0)

	def test_previous_line_command_goes_to_start(self) -> None:
		text = "primera linea bastante larga\nsegunda"
		obj = tb.FakeObj("", Role.EDITABLETEXT, text=text)
		obj.caret = text.index("segunda")
		api.setFocusObject(obj, [])
		self.h.handleObject(obj, "focus")
		self.assertTrue(self.h.previousLine())
		self.assertEqual(obj.caret, 0)


# ====================================================================== 4. modificadores y teclas emuladas
class EmulatedKeyModifierTests(unittest.TestCase):
	def setUp(self) -> None:
		self.inp = brailleInput.handler
		self.inp.modifiers = set()
		self.addCleanup(lambda: setattr(self.inp, "modifiers", set()))
		self.mgr = inputCore.manager
		for name, value in (("captureFunc", None), ("inputHelp", False)):
			old = getattr(self.mgr, name)
			setattr(self.mgr, name, value)
			self.addCleanup(setattr, self.mgr, name, old)

	def _gesture(self) -> driversBase.BrailleGesture:
		g = driversBase.BrailleGesture("prueba", ["joystickUp"])
		g.emulatedKey = "kb:upArrow"
		return g

	def test_modifiers_are_applied_and_cleared(self) -> None:
		sent: list[str] = []
		self.inp.modifiers = {"control"}
		with (
			mock.patch.object(self.mgr, "findScript", return_value=None),
			mock.patch("tiresias.input.gestures.KeyboardGesture.send", autospec=True, side_effect=lambda g: sent.append(g.normalizedKeys.lower())),
			mock.patch("tiresias.input.gestures.sendKey") as plain,
		):
			self.assertFalse(driversBase._decideBrailleGesture(gesture=self._gesture()))
		plain.assert_not_called()
		self.assertEqual(len(sent), 1)
		self.assertIn("control", sent[0])
		self.assertIn("uparrow", sent[0])
		self.assertEqual(self.inp.modifiers, set())

	def test_without_modifiers_plain_key(self) -> None:
		with mock.patch.object(self.mgr, "findScript", return_value=None), mock.patch("tiresias.input.gestures.sendKey") as plain:
			self.assertFalse(driversBase._decideBrailleGesture(gesture=self._gesture()))
		plain.assert_called_once_with("upArrow")


# ====================================================================== 5. «Automático» no bloquea al parar
class DetectorStopTests(unittest.TestCase):
	def test_stop_does_not_wait(self) -> None:
		det = detect.Detector(lambda driver: None, driverNames=[])
		release = threading.Event()
		det._thread = threading.Thread(target=release.wait, daemon=True)
		det._thread.start()
		t0 = time.monotonic()
		det.stop()
		self.assertLess(time.monotonic() - t0, 0.5)
		self.assertTrue(det._stop.is_set())
		release.set()

	def test_late_driver_is_terminated_by_thread(self) -> None:
		found: list = []
		det = detect.Detector(found.append, driverNames=["x"])
		driver = mock.Mock()

		def make(**kwargs):
			# La parada llega mientras el hilo conecta.
			det.stop()
			return driver

		cls = mock.Mock(side_effect=make)
		match = mock.Mock(type="hid", port="p", bluetooth=False)
		with (
			mock.patch.object(detect.ports, "listAll", return_value=[]),
			mock.patch.object(detect, "findCandidates", return_value=[("x", match)]),
			mock.patch("tiresias.braille.drivers.getDriverClass", return_value=cls),
		):
			self.assertTrue(det._tryAll(["x"], False))
		driver.terminate.assert_called_once()
		self.assertEqual(found, [])


# ====================================================================== 6. enrutamiento en líneas sustituidas
class BrowseRoutingMapTests(_Case):
	cells = 40

	def test_route_uses_offsets(self) -> None:
		text = "Pulsa Aceptar ahora\n"
		doc = FakeBrowseDoc(text, 0)
		# «Aceptar» (6-13) se muestra como «ok btn»: 6 caracteres que apuntan al botón.
		shown = "Pulsa ok btn ahora"
		offsets = list(range(0, 6)) + [6 + min(i, 6) for i in range(6)] + list(range(13, 19))
		with mock.patch.object(api, "getCaretObject", return_value=doc):
			self.h.handleBrowseLine(shown, 0, offsets=offsets)
			self.h.routeTo(shown.index("ahora"))
		self.assertEqual(doc.caret, text.index("ahora"))

	def test_route_without_offsets(self) -> None:
		text = "uno dos\n"
		doc = FakeBrowseDoc(text, 0)
		with mock.patch.object(api, "getCaretObject", return_value=doc):
			self.h.handleBrowseLine("uno dos", 0)
			self.h.routeTo(4)
		self.assertEqual(doc.caret, 4)

	def _buffer(self, pieces):
		from tiresias.browse.buffer import Node, VirtualBuffer

		buf = VirtualBuffer(None)
		buf.text = "".join(t for t, _r in pieces) + "\n"
		pos = 0
		nodes = []
		for t, role in pieces:
			n = Node()
			n.role = role
			n.start, n.end = pos, pos + len(t)
			pos += len(t)
			nodes.append(n)
		buf.nodes = nodes
		buf.chunks = [(n.start, n.end, n) for n in nodes]
		buf._chunkStarts = [c[0] for c in buf.chunks]
		return buf, nodes

	def test_braille_label_line_map(self) -> None:
		from tiresias.browse import html_details

		buf, nodes = self._buffer([("Pulsa ", Role.STATICTEXT), ("Aceptar", Role.BUTTON), (" ahora", Role.STATICTEXT)])
		nodes[1].aria = {"braillelabel": "ok"}
		doc = type("Doc", (), {"buffer": buf, "caret": 0})()
		text, _cursor, offsets = html_details.brailleLabelLine(doc, 0, len(buf.text), withMap=True)
		self.assertEqual(len(offsets), len(text))
		i = text.index("ahora")
		self.assertEqual(offsets[i], buf.text.index("ahora"))
		self.assertEqual(offsets[text.index("ok")], nodes[1].start)
		# Sin ``withMap`` sigue devolviendo dos valores.
		self.assertEqual(len(html_details.brailleLabelLine(doc, 0, len(buf.text))), 2)

	def test_math_line_map(self) -> None:
		from tiresias.mathpres import browse_support

		buf, nodes = self._buffer([("Valor ", Role.STATICTEXT), ("x igual a 1", Role.MATH), (" fin", Role.STATICTEXT)])
		buf._mathByNode = {id(nodes[1]): "<math><mi>x</mi></math>"}
		doc = type("Doc", (), {"buffer": buf, "caret": 0})()
		saved = conf["math"]["brailleMath"]
		self.addCleanup(lambda: conf["math"].__setitem__("brailleMath", saved))
		conf["math"]["brailleMath"] = True
		with mock.patch("tiresias.mathpres.getBrailleForMathMl", return_value="⠭⠶⠼⠁"):
			text, _cursor, offsets = browse_support.brailleLine(doc, 0, len(buf.text), withMap=True)
		self.assertEqual(len(offsets), len(text))
		self.assertEqual(offsets[text.index("fin")], buf.text.index("fin"))
		self.assertEqual(offsets[text.index("⠶")], nodes[1].start)


# ====================================================================== 7 y 16. táctil
class TouchpadTests(unittest.TestCase):
	def setUp(self) -> None:
		from tiresias.touch import handler as touchHandler

		conf.registerDefaults("touch", touchHandler.DEFAULTS)
		self.mod = touchHandler

	def test_touchpad_tap_does_not_explore(self) -> None:
		from tiresias.touch.gestures import identifiersFor

		ids = identifiersFor("tap", "object", "tp")
		self.assertTrue(ids)
		self.assertFalse([i for i in ids if i.startswith("ts")], ids)
		self.assertTrue([i for i in identifiersFor("doubleTap", "object", "tp") if i.startswith("ts")])
		self.assertTrue([i for i in identifiersFor("tap", "object", "ts") if i.startswith("ts")])

	def test_touchpad_hover_is_dropped(self) -> None:
		from tiresias.touch import recognizer as R

		h = self.mod.TouchHandler()
		saved = conf["touch"]["touchpadSingleFinger"]
		self.addCleanup(lambda: conf["touch"].__setitem__("touchpadSingleFinger", saved))
		conf["touch"]["touchpadSingleFinger"] = True
		events = [R.TouchEvent(a, 1, 10, 10, 0.0) for a in (R.HOVER_DOWN, R.HOVER, R.HOVER_UP)]
		with mock.patch("tiresias.queue_handler.queueFunction") as q:
			h._onEvents(events, "tp")
			q.assert_not_called()
			h._onEvents([R.TouchEvent(R.DOUBLE_TAP, 1, 10, 10, 0.0)], "tp")
			q.assert_called_once()

	def test_profile_switch_reloads_thresholds(self) -> None:
		h = self.mod.TouchHandler()
		h.initialized = True
		h.window = mock.Mock()
		saved = conf["touch"]["multiTapTimeout"]
		self.addCleanup(lambda: conf["touch"].__setitem__("multiTapTimeout", saved))
		h.recognizerSettings()
		with mock.patch.object(h, "reload") as reload, mock.patch.object(h, "apply") as apply:
			h._afterProfileSwitch()
			reload.assert_not_called()
			apply.assert_called_once()
			conf["touch"]["multiTapTimeout"] = int(saved) + 100
			h._afterProfileSwitch()
			reload.assert_called_once()

	def test_profile_switch_is_queued(self) -> None:
		h = self.mod.TouchHandler()
		with mock.patch("tiresias.queue_handler.queueFunction") as q:
			h._onProfileSwitch()
		self.assertEqual(q.call_args[0][0], h._afterProfileSwitch)


# ====================================================================== 8, 9 y 15. entrada braille
class BrailleInputStateTests(_Case):
	def setUp(self) -> None:
		super().setUp()
		self.typed: list[str] = []
		self.inp = brailleInput.handler
		self.inp.cells = []
		self.inp.typed = ""
		self.inp.modifiers = set()
		self.addCleanup(self.inp.reset)
		self.addCleanup(lambda: setattr(self.inp, "modifiers", set()))
		p = mock.patch("tiresias.winapi.typeText", side_effect=self.typed.append)
		p.start()
		self.addCleanup(p.stop)
		conf["braille"]["inputTable"] = "es.tbl"

	def test_caret_move_by_other_cause_resets_word(self) -> None:
		self.inp.input(D("1"))
		self.assertTrue(self.inp.cells)
		obj = tb.FakeObj("", Role.EDITABLETEXT, text="a")
		api.setFocusObject(obj, [])
		# Justo después de escribir: el movimiento es de la propia escritura.
		self.h.onEvent(eventName="caret", obj=obj)
		self.assertTrue(self.inp.cells)
		with mock.patch("time.monotonic", return_value=time.monotonic() + 5):
			self.h.onEvent(eventName="caret", obj=obj)
		self.assertEqual(self.inp.cells, [])
		self.assertEqual(self.inp.typed, "")

	def test_typing_with_keyboard_resets_word(self) -> None:
		self.inp.input(D("1"))
		with mock.patch("time.monotonic", return_value=time.monotonic() + 5):
			self.h.onEvent(eventName="typedCharacter", obj=None)
		self.assertEqual(self.inp.cells, [])
		# Lo siguiente es una palabra nueva: no se corrige lo ya escrito.
		self.inp.input(D("12"))
		self.assertEqual("".join(self.typed), "ab")

	def test_focus_change_clears_modifiers(self) -> None:
		self.inp.toggleModifier("control")
		self.inp.onFocusChange()
		self.assertEqual(self.inp.modifiers, set())

	def test_pc_keyboard_is_captured(self) -> None:
		captured: list = []
		mgr = inputCore.manager
		old = mgr.captureFunc
		self.addCleanup(setattr, mgr, "captureFunc", old)
		mgr.captureFunc = captured.append
		with mock.patch.object(mgr, "executeBrailleGesture") as ex:
			brailleInput._executePcGesture(D("1"), False)
		ex.assert_not_called()
		self.assertEqual(len(captured), 1)
		self.assertIn("br(pckeyboard):dot1", [i.lower() for i in captured[0].identifiers])
		self.assertEqual(self.typed, [])
		# El decisor de los gestos de línea también captura cualquier gesto braille.
		g = brailleInput.BrailleKeyboardGesture(D("2"), False)
		self.assertFalse(driversBase._decideBrailleGesture(gesture=g))
		self.assertIs(captured[-1], g)


# ====================================================================== 10. rama inalcanzable
class RouteCustomTests(_Case):
	def test_single_custom_branch(self) -> None:
		src = inspect.getsource(presenter.BraillePresenter.routeTo)
		self.assertEqual(src.count('self._regionKind == "custom"'), 1)

	def test_custom_without_router(self) -> None:
		self.h.handleCustom("abc", 0, owner=object())
		self.h.routeTo(1)  # no falla


# ====================================================================== 11 y 12. vista dividida y visor espejo
class DisplayChangeTests(_Case):
	def test_split_view_refreshed_on_set_display(self) -> None:
		conf["braille"]["splitView"] = "clock"
		with mock.patch("tiresias.queue_handler.callLater", return_value=9) as later:
			self.h.setDisplay("fake", persist=False, instance=tb.FakeDisplay(20))
		self.assertEqual(self.h._splitTimer, 9)
		self.assertIn(15000, [c[0][0] for c in later.call_args_list])

	def test_split_view_refreshed_on_remote_cells(self) -> None:
		conf["braille"]["splitView"] = "title"
		self.h.display = braille.NoBrailleDriver()
		self.addCleanup(self.h.setRemoteNumCells, 0)
		with mock.patch("tiresias.queue_handler.callLater", return_value=11), mock.patch.object(self.h, "handleObject"):
			self.h.setRemoteNumCells(20)
		self.assertEqual(self.h._splitTimer, 11)

	def test_mirror_kept_while_line_connects(self) -> None:
		from tiresias.braille.drivers.auto import AutoDetectDriver
		from tiresias.braille.drivers.base import HardwareDriver
		from tiresias.gui import braille_viewer

		self.h._mirror = True
		self.addCleanup(setattr, self.h, "_mirror", False)
		pending = HardwareDriver.__new__(HardwareDriver)
		pending.numCells = 0
		with mock.patch.object(braille_viewer, "show") as show, mock.patch.object(braille_viewer, "close") as close:
			self.h.setDisplay("x", persist=False, instance=pending)
			self.assertTrue(self.h._mirror)
			close.assert_not_called()
			auto = AutoDetectDriver.__new__(AutoDetectDriver)
			auto.numCells = 0
			self.h.setDisplay("auto", persist=False, instance=auto)
			self.assertTrue(self.h._mirror)
			close.assert_not_called()
			# Al conectar (``_activate`` vuelve a instalarla), el visor toma sus celdas.
			pending.numCells = 40
			self.h.setDisplay("x", persist=False, instance=pending)
			show.assert_called_with(40)
			# «Sin braille» sí cierra el espejo.
			self.h.setDisplay("noBraille", persist=False, instance=braille.NoBrailleDriver())
			self.assertFalse(self.h._mirror)
			close.assert_called_once()


# ====================================================================== 13. seleccionar en dos pulsaciones
class SelectTwoPressesTests(_Case):
	cells = 10

	def test_anchor_survives_scrolling(self) -> None:
		text = "uno dos tres cuatro cinco seis siete"
		obj = tb.FakeObj("", Role.EDITABLETEXT, text=text)
		api.setFocusObject(obj, [])
		self.h.handleObject(obj, "focus")
		self.addCleanup(lambda: setattr(self.h, "_selectAnchor", None))
		self.h._selectAnchor = None
		first = self.h.cellToRaw(6) - self.h._lineStart
		g1 = type("G", (), {"routingIndexes": [6], "routingIndex": 6})()
		brailleCommands.script_braille_selectRange(None, g1)
		self.assertIsNotNone(self.h._selectAnchor)
		self.assertTrue(self.h.scrollForward())
		self.assertGreater(self.h.windowStart, 0)
		second = self.h.cellToRaw(2) - self.h._lineStart
		g2 = type("G", (), {"routingIndexes": [2], "routingIndex": 2})()
		with mock.patch("tiresias.queue_handler.callLater"):
			brailleCommands.script_braille_selectRange(None, g2)
		self.assertEqual(obj.selection, (first, second + 1))


# ====================================================================== 14. intercambiar tablas
class CycleTablesTests(_Case):
	def test_invalid_tables_are_not_swapped(self) -> None:
		conf["braille"]["translationTable"] = "salida.utb"
		conf["braille"]["inputTable"] = "entrada.utb"

		class T:
			def __init__(self, name: str, forInput: bool, forOutput: bool) -> None:
				self.name = self.displayName = name
				self.forInput = forInput
				self.forOutput = forOutput

		catalog = {"salida.utb": T("salida.utb", False, True), "entrada.utb": T("entrada.utb", True, False)}
		with mock.patch.object(tables, "getTable", side_effect=lambda name, forInput=False: catalog[name]):
			brailleCommands.script_braille_cycleOutputTable(None, None)
		self.assertEqual(conf["braille"]["translationTable"], "salida.utb")
		self.assertEqual(conf["braille"]["inputTable"], "entrada.utb")
		self.assertIn("No se pueden intercambiar", self.spoken.call_args[0][0])

	def test_valid_tables_are_swapped(self) -> None:
		conf["braille"]["translationTable"] = "es-comp8"
		conf["braille"]["inputTable"] = "es-g1"
		brailleCommands.script_braille_cycleOutputTable(None, None)
		self.assertEqual(conf["braille"]["translationTable"], "es-g1")
		self.assertEqual(conf["braille"]["inputTable"], "es-comp8")


# ====================================================================== manual: HID estándar sin teclas duplicadas
class HidJoystickTests(unittest.TestCase):
	def test_joystick_handled_by_global_commands(self) -> None:
		from tiresias.braille.drivers.hidBraille import HidBrailleDriver
		from tiresias.global_commands import commands as gc

		for key in ("joystickUp", "dpadDown", "joystickCenter"):
			self.assertNotIn(key, HidBrailleDriver.gestureMap)
			g = driversBase.BrailleGesture("hidBraille", [key])
			self.assertIsNotNone(gc.getScript(g), key)


if __name__ == "__main__":
	unittest.main()
