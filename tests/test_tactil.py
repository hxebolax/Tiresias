"""Pruebas del soporte táctil: reconocedor de gestos, identificadores, panel
táctil (informes HID simulados) y ventana de captura.

No se inyectan toques ni teclas en el sistema. La ventana de captura se crea
oculta o transparente a la entrada y se destruye enseguida.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import ctypes
import os
import shutil
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="tiresias_test_tactil_")
shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
paths.setDataDir(_TMP)
paths.ensureDataDirs()

from tiresias.baseobject import ScriptableObject, normalizeGestureId, script  # noqa: E402
from tiresias.touch import recognizer as R  # noqa: E402
from tiresias.touch import touchpad as TP  # noqa: E402
from tiresias.touch.gestures import TouchGesture, actionLabel, identifiersFor, labelForIdentifier  # noqa: E402


class Feeder:
	"""Alimenta el reconocedor con secuencias sintéticas y recoge los gestos."""

	def __init__(self, **settings) -> None:
		self.rec = R.GestureRecognizer(R.RecognizerSettings(**settings))
		self.events: list[R.TouchEvent] = []
		self.t = 100.0

	def at(self, t: float) -> "Feeder":
		self.t = t
		self.events += self.rec.poll(t)
		return self

	def down(self, cid, x, y, dt=0.0):
		self.t += dt
		self.events += self.rec.down(cid, x, y, self.t)
		return self

	def move(self, cid, x, y, dt=0.0):
		self.t += dt
		self.events += self.rec.move(cid, x, y, self.t)
		return self

	def up(self, cid, x, y, dt=0.0):
		self.t += dt
		self.events += self.rec.up(cid, x, y, self.t)
		return self

	def drag(self, cid, x0, y0, x1, y1, duration, steps=5):
		for i in range(1, steps + 1):
			self.move(cid, x0 + (x1 - x0) * i // steps, y0 + (y1 - y0) * i // steps, duration / steps)
		return self

	def settle(self):
		"""Deja pasar el tiempo suficiente para resolver todo lo pendiente."""
		return self.at(self.t + 5)

	def names(self):
		return [e.name for e in self.events]


class RecognizerTests(unittest.TestCase):
	def test_tap_waits_for_multitap_timeout(self) -> None:
		f = Feeder()
		f.down(1, 100, 100).up(1, 101, 100, 0.08)
		self.assertEqual(f.events, [], "el toque espera por si llega un segundo toque")
		self.assertIsNotNone(f.rec.nextDeadline())
		f.at(f.t + 0.31)
		self.assertEqual(f.names(), ["tap"])
		ev = f.events[0]
		self.assertEqual((ev.x, ev.y, ev.fingers), (100, 100, 1))
		self.assertIsNone(f.rec.nextDeadline())

	def test_double_and_triple_tap(self) -> None:
		f = Feeder()
		f.down(1, 50, 50).up(1, 50, 50, 0.05).down(2, 52, 51, 0.1).up(2, 52, 51, 0.05).settle()
		self.assertEqual(f.names(), ["doubleTap"])
		f = Feeder()
		for i in range(3):
			f.down(i, 50, 50, 0.1).up(i, 50, 50, 0.05)
		self.assertEqual(f.names(), ["tripleTap"], "el triple toque se emite sin esperar")

	def test_taps_too_far_apart_are_separate(self) -> None:
		f = Feeder()
		f.down(1, 50, 50).up(1, 50, 50, 0.05).down(2, 50, 50, 0.6).up(2, 50, 50, 0.05).settle()
		self.assertEqual(f.names(), ["tap", "tap"])

	def test_multi_finger_taps(self) -> None:
		f = Feeder()
		f.down(1, 100, 100).down(2, 200, 100, 0.02).up(1, 100, 100, 0.06).up(2, 200, 100, 0.01).settle()
		self.assertEqual(f.names(), ["2finger_tap"])
		self.assertEqual((f.events[0].x, f.events[0].y), (150, 100))
		f = Feeder()
		f.down(1, 100, 100).down(2, 150, 100, 0.01).down(3, 200, 100, 0.01).up(1, 100, 100, 0.05).up(2, 150, 100).up(3, 200, 100).settle()
		self.assertEqual(f.names(), ["3finger_tap"])
		f = Feeder()
		for _round in range(2):
			for cid in range(4):
				f.down(cid, 100 + cid * 40, 300, 0.01)
			for cid in range(4):
				f.up(cid, 100 + cid * 40, 300, 0.01)
			f.at(f.t + 0.1)
		f.settle()
		self.assertEqual(f.names(), ["4finger_doubleTap"])

	def test_flicks_in_four_directions(self) -> None:
		cases = {
			"flickRight": (300, 0),
			"flickLeft": (-300, 0),
			"flickDown": (0, 300),
			"flickUp": (0, -300),
		}
		for expected, (dx, dy) in cases.items():
			with self.subTest(expected):
				f = Feeder()
				f.down(1, 500, 500).drag(1, 500, 500, 500 + dx, 500 + dy, 0.12).up(1, 500 + dx, 500 + dy, 0.01).settle()
				self.assertEqual(f.names(), [expected])

	def test_two_finger_flick_down(self) -> None:
		f = Feeder()
		f.down(1, 400, 200).down(2, 480, 200, 0.02)
		f.drag(1, 400, 200, 400, 500, 0.1).drag(2, 480, 200, 480, 500, 0.02)
		f.up(1, 400, 500, 0.01).up(2, 480, 500, 0.01).settle()
		self.assertEqual(f.names(), ["2finger_flickDown"])

	def test_short_movement_is_not_a_flick(self) -> None:
		f = Feeder()
		f.down(1, 500, 500).drag(1, 500, 500, 530, 500, 0.1).up(1, 530, 500, 0.01).settle()
		self.assertEqual(f.names(), [], "30 píxeles no llegan a deslizamiento ni son un toque")

	def test_hover_exploration(self) -> None:
		f = Feeder()
		f.down(1, 10, 10).at(f.t + 0.3)
		self.assertEqual(f.names(), ["hoverDown"])
		f.move(1, 40, 10, 0.05).move(1, 90, 20, 0.05).up(1, 90, 20, 0.05).settle()
		self.assertEqual(f.names(), ["hoverDown", "hover", "hover", "hoverUp"])
		self.assertEqual((f.events[-1].x, f.events[-1].y), (90, 20))
		self.assertTrue(all(e.isHover for e in f.events))

	def test_slow_drag_becomes_hover(self) -> None:
		f = Feeder()
		f.down(1, 0, 0).drag(1, 0, 0, 400, 0, 0.8, steps=8).up(1, 400, 0, 0.01).settle()
		names = f.names()
		self.assertEqual(names[0], "hoverDown")
		self.assertEqual(names[-1], "hoverUp")
		self.assertNotIn("flickRight", names)

	def test_split_tap_while_exploring(self) -> None:
		f = Feeder()
		f.down(1, 300, 300).at(f.t + 0.3).move(1, 320, 300, 0.05)
		f.down(2, 600, 600, 0.1).up(2, 600, 600, 0.05)
		f.up(1, 320, 300, 0.2).settle()
		self.assertEqual(f.names(), ["hoverDown", "hover", "splitTap", "hoverUp"])
		split = f.events[2]
		self.assertEqual((split.x, split.y), (320, 300), "el toque dividido actúa donde está el dedo que explora")

	def test_tap_and_hold_variants(self) -> None:
		f = Feeder()
		f.down(1, 50, 50).up(1, 50, 50, 0.05).down(2, 51, 50, 0.1).at(f.t + 0.3)
		self.assertEqual(f.names(), ["tapAndHold"])
		f.move(2, 200, 200, 0.1).up(2, 200, 200, 0.1).settle()
		self.assertEqual(f.names(), ["tapAndHold"], "tras mantener no se explora")
		f = Feeder()
		f.down(1, 50, 50).up(1, 50, 50, 0.05).down(2, 50, 50, 0.1).up(2, 50, 50, 0.05).down(3, 50, 50, 0.1).at(f.t + 0.3)
		f.up(3, 50, 50, 0.1).settle()
		self.assertEqual(f.names(), ["doubleTapAndHold"])

	def test_multi_finger_hold(self) -> None:
		f = Feeder()
		f.down(1, 100, 100).down(2, 200, 100, 0.01).at(f.t + 0.4)
		self.assertEqual(f.names(), ["2finger_hold"])
		f.up(1, 100, 100, 0.5).up(2, 200, 100).settle()
		self.assertEqual(f.names(), ["2finger_hold"])

	def test_pinch(self) -> None:
		f = Feeder()
		f.down(1, 400, 400).down(2, 600, 400, 0.01)
		f.move(1, 300, 400, 0.05).move(2, 700, 400).move(1, 250, 400, 0.05).move(2, 750, 400)
		f.up(1, 250, 400, 0.02).up(2, 750, 400).settle()
		self.assertEqual(f.names(), ["2finger_pinchOut"])
		f = Feeder()
		f.down(1, 200, 400).down(2, 800, 400, 0.01)
		f.move(1, 400, 400, 0.08).move(2, 600, 400)
		f.up(1, 400, 400, 0.02).up(2, 600, 400).settle()
		self.assertEqual(f.names(), ["2finger_pinchIn"])

	def test_tap_then_flick_flushes_tap_first(self) -> None:
		f = Feeder()
		f.down(1, 50, 50).up(1, 50, 50, 0.05)
		f.down(2, 100, 100, 0.1).drag(2, 100, 100, 400, 100, 0.1).up(2, 400, 100, 0.01).settle()
		self.assertEqual(f.names(), ["tap", "flickRight"])

	def test_mixed_fingers_are_ignored(self) -> None:
		f = Feeder()
		f.down(1, 100, 100).down(2, 400, 400, 0.01)
		f.drag(2, 400, 400, 700, 400, 0.1)
		f.up(1, 100, 100, 0.01).up(2, 700, 400).settle()
		self.assertEqual(f.names(), [])

	def test_cancel_forgets_everything(self) -> None:
		f = Feeder()
		f.down(1, 10, 10).at(f.t + 0.3)
		self.assertEqual(f.names(), ["hoverDown"])
		f.rec.cancel(f.t)
		self.assertFalse(f.rec.isTouching)
		f.up(1, 10, 10, 0.1).settle()
		self.assertEqual(f.names(), ["hoverDown"])

	def test_names(self) -> None:
		self.assertEqual(R.makeName("tap", 1), "tap")
		self.assertEqual(R.makeName("flickDown", 2), "2finger_flickDown")
		self.assertEqual(R.splitName("3finger_tap"), (3, "tap"))
		self.assertEqual(R.splitName("doubletap"), (1, "doubletap"))


_DIRS = {"Right": (1, 0), "Left": (-1, 0), "Down": (0, 1), "Up": (0, -1)}


class SequenceAndEdgeTests(unittest.TestCase):
	def _continuous(self, first: str, second: str, x=500, y=500, **settings) -> Feeder:
		"""Dos tramos de 200 px sin levantar el dedo, en 0,3 s."""
		f = Feeder(**settings)
		(ax, ay), (bx, by) = _DIRS[first], _DIRS[second]
		mx, my = x + ax * 200, y + ay * 200
		ex, ey = mx + bx * 200, my + by * 200
		f.down(1, x, y).drag(1, x, y, mx, my, 0.12).drag(1, mx, my, ex, ey, 0.12).up(1, ex, ey, 0.01).settle()
		return f

	def test_all_twelve_continuous_sequences(self) -> None:
		self.assertEqual(len(R.SEQUENCE_ACTIONS), 12)
		self.assertEqual(len(R.OPPOSITE_SEQUENCES), 4)
		self.assertEqual(len(R.L_SEQUENCES), 8)
		for first in _DIRS:
			for second in _DIRS:
				if first == second:
					continue
				with self.subTest(f"{first}->{second}"):
					f = self._continuous(first, second)
					self.assertEqual(f.names(), [f"flick{first}Then{second}"])

	def test_straight_and_diagonal_flicks_are_not_sequences(self) -> None:
		f = Feeder()
		f.down(1, 100, 100).drag(1, 100, 100, 500, 110, 0.15, steps=8).up(1, 500, 110, 0.01).settle()
		self.assertEqual(f.names(), ["flickRight"])
		f = Feeder()
		f.down(1, 100, 100).drag(1, 100, 100, 300, 302, 0.15, steps=8).up(1, 300, 302, 0.01).settle()
		self.assertEqual(f.names(), ["flickDown"], "una diagonal no es una secuencia en L")

	def test_fast_flick_does_not_start_exploring(self) -> None:
		f = Feeder()
		f.down(1, 0, 0).drag(1, 0, 0, 200, 0, 0.2).drag(1, 200, 0, 200, 200, 0.2).up(1, 200, 200, 0.01).settle()
		self.assertEqual(f.names(), ["flickRightThenDown"], "0,4 s deslizando rápido no es exploración")

	def test_two_finger_sequence(self) -> None:
		f = Feeder()
		f.down(1, 400, 400).down(2, 480, 400, 0.01)
		for cid, x in ((1, 400), (2, 480)):
			f.drag(cid, x, 400, x, 600, 0.05).drag(cid, x, 600, x, 400, 0.05)
		f.up(1, 400, 400, 0.01).up(2, 480, 400).settle()
		self.assertEqual(f.names(), ["2finger_flickDownThenUp"])

	def test_lifted_sequence_only_when_filter_asks(self) -> None:
		def flick(f, dx, dy, pause):
			f.down(1, 500, 500, pause).drag(1, 500, 500, 500 + dx, 500 + dy, 0.1).up(1, 500 + dx, 500 + dy, 0.01)

		f = Feeder()
		flick(f, 300, 0, 0)
		flick(f, -300, 0, 0.1)
		f.settle()
		self.assertEqual(f.names(), ["flickRight", "flickLeft"], "sin filtro no se espera")
		asked = []
		f = Feeder()
		f.rec.sequenceFilter = lambda action, n: asked.append((action, n)) or action == "flickRight"
		flick(f, 300, 0, 0)
		self.assertEqual(f.events, [], "espera un segundo deslizamiento")
		flick(f, 0, 300, 0.1)
		f.settle()
		self.assertEqual(f.names(), ["flickRightThenDown"])
		self.assertEqual(asked, [("flickRight", 1)])
		f = Feeder()
		f.rec.sequenceFilter = lambda action, n: True
		flick(f, 300, 0, 0)
		f.settle()
		self.assertEqual(f.names(), ["flickRight"], "sin segundo deslizamiento se emite al vencer el plazo")
		f = Feeder()
		f.rec.sequenceFilter = lambda action, n: True
		flick(f, 300, 0, 0)
		flick(f, -300, 0, 0.6)
		f.settle()
		self.assertEqual(f.names(), ["flickRight", "flickLeft"], "demasiado separados")
		f = Feeder()
		f.rec.sequenceFilter = lambda action, n: True
		flick(f, 300, 0, 0)
		f.down(2, 50, 50, 0.1).up(2, 50, 50, 0.05).settle()
		self.assertEqual(f.names(), ["flickRight", "tap"])

	def test_edges(self) -> None:
		settings = {"edgeMargin": 20, "bounds": (0, 0, 1000, 800)}
		cases = [((5, 400), "Right", "left"), ((995, 400), "Left", "right"), ((500, 3), "Down", "top"), ((500, 797), "Up", "bottom")]
		for (x, y), direction, edge in cases:
			with self.subTest(edge):
				f = Feeder(**settings)
				dx, dy = _DIRS[direction]
				f.down(1, x, y).drag(1, x, y, x + dx * 250, y + dy * 250, 0.1).up(1, x + dx * 250, y + dy * 250, 0.01).settle()
				ev = f.events[0]
				self.assertEqual((ev.action, ev.edge), (f"flick{direction}", edge))
				self.assertEqual(ev.edgeName, f"{edge}Edge_flick{direction}")
		f = Feeder(**settings)
		f.down(1, 100, 400).drag(1, 100, 400, 400, 400, 0.1).up(1, 400, 400, 0.01).settle()
		self.assertIsNone(f.events[0].edge, "lejos del borde")
		f = Feeder(edgeMargin=0, bounds=(0, 0, 1000, 800))
		f.down(1, 5, 400).drag(1, 5, 400, 300, 400, 0.1).up(1, 300, 400, 0.01).settle()
		self.assertIsNone(f.events[0].edge, "gestos de borde desactivados")
		f = Feeder(**settings)
		f.down(1, 5, 400).up(1, 5, 400, 0.05).settle()
		self.assertEqual((f.names(), f.events[0].edge), (["tap"], None), "un toque en el borde no es gesto de borde")
		f = self._continuous("Right", "Up", x=5, y=400, **settings)
		self.assertEqual(f.events[0].edgeName, "leftEdge_flickRightThenUp")

	def test_edge_identifiers_fall_back(self) -> None:
		ev = R.TouchEvent("flickRight", 1, 0, 0, 0.0, "left")
		g = TouchGesture(ev, "object")
		self.assertEqual(
			g.identifiers,
			["ts(object):leftedge_flickright", "ts:leftedge_flickright", "ts(object):flickright", "ts:flickright"],
		)
		self.assertEqual(g.displayName, "deslizar a la derecha desde el borde izquierdo")
		self.assertEqual(labelForIdentifier("ts:flickupthenleft"), "pantalla táctil: deslizar hacia arriba y luego a la izquierda")
		self.assertEqual(R.splitEdge("bottomedge_flickup"), ("bottom", "flickup"))
		self.assertEqual(R.splitEdge("2finger_tap"), (None, "2finger_tap"))


class TouchGestureTests(unittest.TestCase):
	def test_identifiers(self) -> None:
		ev = R.TouchEvent("flickDown", 2, 10, 20, 0.0)
		g = TouchGesture(ev, "object")
		self.assertEqual(g.identifiers, ["ts(object):2finger_flickdown", "ts:2finger_flickdown"])
		self.assertEqual((g.x, g.y), (10, 20))
		self.assertEqual(g.displayName, "deslizar hacia abajo con 2 dedos")
		tp = TouchGesture(R.TouchEvent("tap", 3, 0, 0, 0.0), "text", source="tp")
		self.assertEqual(tp.identifiers, ["tp(text):3finger_tap", "tp:3finger_tap", "ts(text):3finger_tap", "ts:3finger_tap"])
		for gid in g.identifiers + tp.identifiers:
			self.assertEqual(normalizeGestureId(gid), gid, "los identificadores ya vienen normalizados")
		self.assertEqual(identifiersFor("doubleTap", "browse"), ["ts(browse):doubletap", "ts:doubletap"])

	def test_spanish_labels(self) -> None:
		self.assertEqual(labelForIdentifier("ts:doubletap"), "pantalla táctil: doble toque")
		self.assertEqual(labelForIdentifier("ts(object):2finger_flickright"), "pantalla táctil: deslizar a la derecha con 2 dedos (modo objeto)")
		self.assertEqual(labelForIdentifier("tp(text):3finger_tap"), "panel táctil: toque con 3 dedos (modo texto)")
		self.assertEqual(actionLabel("tapandhold"), "toque y mantener")
		self.assertEqual(actionLabel("hoverup"), "levantar el dedo al explorar")
		for action in R.ALL_ACTIONS:
			label = actionLabel(action.lower())
			self.assertNotEqual(label, action.lower(), f"falta el nombre en español de {action}")

	def test_keys_label_delegates_to_touch(self) -> None:
		from tiresias.input import keys

		self.assertEqual(keys.labelForGesture("ts(browse):flickup"), "pantalla táctil: deslizar hacia arriba (modo exploración)")
		self.assertFalse(keys.labelForGesture("kb:tiresias+control+alt+t").startswith("pantalla"))
		self.assertEqual(keys.labelForGesture("tp:2finger_tap"), "panel táctil: toque con 2 dedos")


class TouchCommandsTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		from tiresias import global_commands

		cls.gc = global_commands

	def test_scripts_installed_with_defaults(self) -> None:
		G = self.gc.GlobalCommands
		for name in ("touch_toggleSupport", "touch_changeMode", "touch_newExplore", "touch_explore", "touch_hoverUp", "touch_rightClick", "touch_browseNext"):
			self.assertTrue(hasattr(G, "script_" + name), name)
		gestures = dict(G.iterClassGestures())
		self.assertEqual(gestures["kb:tiresias+control+alt+t"], "touch_toggleSupport")
		self.assertEqual(gestures["ts:doubletap"], "review_activate")
		self.assertEqual(gestures["ts:2finger_tap"], "touch_stopSpeech")
		self.assertEqual(gestures["ts:2finger_flickdown"], "review_sayAll")
		self.assertEqual(gestures["ts:4finger_doubletap"], "toggleInputHelp")
		self.assertEqual(gestures["ts:3finger_tap"], "touch_changeMode")
		self.assertEqual(gestures["ts(object):flickright"], "navigatorObject_nextInFlow")
		self.assertEqual(gestures["ts(text):flickright"], "review_nextCharacter")
		self.assertEqual(gestures["ts(browse):flickright"], "touch_browseNext")
		for gid, name in gestures.items():
			if gid.startswith("ts"):
				self.assertTrue(hasattr(G, "script_" + name), f"{gid} apunta a una orden inexistente {name}")

	def test_toggle_key_has_no_conflict(self) -> None:
		G = self.gc.GlobalCommands
		owners = [s for g, s in G.iterClassGestures() if g == "kb:tiresias+control+alt+t"]
		self.assertEqual(owners, ["touch_toggleSupport"])
		from tiresias.gui import gesture_tools

		self.assertIsNone(gesture_tools.RESERVED.get("tiresias+control+alt+t"))

	def test_mode_specific_resolution(self) -> None:
		cmds = self.gc.commands
		flick = R.TouchEvent("flickRight", 1, 0, 0, 0.0)
		self.assertEqual(cmds.getScript(TouchGesture(flick, "object")).__name__, "script_navigatorObject_nextInFlow")
		self.assertEqual(cmds.getScript(TouchGesture(flick, "text")).__name__, "script_review_nextCharacter")
		self.assertEqual(cmds.getScript(TouchGesture(flick, "browse")).__name__, "script_touch_browseNext")
		dt = R.TouchEvent("doubleTap", 1, 0, 0, 0.0)
		self.assertEqual(cmds.getScript(TouchGesture(dt, "text")).__name__, "script_review_activate")
		self.assertEqual(cmds.getScript(TouchGesture(dt, "object", source="tp")).__name__, "script_review_activate")
		self.assertTrue(getattr(cmds.script_touch_explore, "noSpeechInterrupt", False))

	def test_sequence_and_edge_defaults(self) -> None:
		G = self.gc.GlobalCommands
		gestures = dict(G.iterClassGestures())
		for action in R.SEQUENCE_ACTIONS:
			gid = "ts:" + action.lower()
			self.assertIn(gid, gestures, f"{action} sin orden por defecto")
			self.assertTrue(hasattr(G, "script_" + gestures[gid]))
		for edge in ("left", "right", "top", "bottom"):
			self.assertTrue(any(g.startswith(f"ts:{edge}edge_") for g in gestures), edge)
		cmds = self.gc.commands
		seq = R.TouchEvent("flickDownThenLeft", 1, 0, 0, 0.0)
		self.assertEqual(cmds.getScript(TouchGesture(seq, "text")).__name__, "script_touch_escape")
		edge = R.TouchEvent("flickDown", 1, 0, 0, 0.0, "top")
		self.assertEqual(cmds.getScript(TouchGesture(edge, "object")).__name__, "script_title")
		unboundEdge = R.TouchEvent("flickRight", 1, 0, 0, 0.0, "top")
		self.assertEqual(cmds.getScript(TouchGesture(unboundEdge, "object")).__name__, "script_navigatorObject_nextInFlow", "sin orden de borde se usa la normal")

	def test_handler_sequence_filter(self) -> None:
		from tiresias.config import conf
		from tiresias.touch.handler import TouchHandler

		h = TouchHandler()
		old = conf["touch"]["liftedSequentialFlicks"]
		try:
			conf["touch"]["liftedSequentialFlicks"] = False
			self.assertFalse(h.sequenceFilter("flickRight", 1))
			conf["touch"]["liftedSequentialFlicks"] = True
			self.assertTrue(h.sequenceFilter("flickRight", 1))
			self.assertFalse(h.sequenceFilter("flickRight", 3), "no hay secuencias de 3 dedos asignadas")
		finally:
			conf["touch"]["liftedSequentialFlicks"] = old
		old = conf["touch"]["edgeGestures"]
		try:
			conf["touch"]["edgeGestures"] = False
			self.assertEqual(h.recognizerSettings().edgeMargin, 0)
			conf["touch"]["edgeGestures"] = True
			s = h.recognizerSettings()
			self.assertGreater(s.edgeMargin, 0)
			self.assertIsNotNone(s.bounds)
			self.assertEqual(h.recognizerSettings(edges=False).edgeMargin, 0, "el panel táctil no tiene bordes")
		finally:
			conf["touch"]["edgeGestures"] = old

	def test_gesture_dialog_conflicts(self) -> None:
		from tiresias.gui import gesture_tools as gt

		self.assertTrue(gt.overlap("ts:tap", "ts(object):tap"))
		self.assertFalse(gt.overlap("ts(object):tap", "ts(text):tap"))
		self.assertFalse(gt.overlap("ts:tap", "kb:tap"))
		self.assertTrue(gt.overlap("kb:tiresias+a", "kb(laptop):tiresias+a"))
		self.assertFalse(gt.overlap("kb(desktop):tiresias+a", "kb(laptop):tiresias+a"))


class InputManagerTouchTests(unittest.TestCase):
	def setUp(self) -> None:
		from tiresias.input import core as inputCore

		self.manager = inputCore.InputManager()
		calls = self.calls = []

		class Target(ScriptableObject):
			@script(description="prueba", gestures=("ts(object):flickRight", "ts:hover"))
			def script_test(self, gesture) -> None:
				calls.append(gesture.name)

		Target.script_test.noSpeechInterrupt = True
		self.manager.chain = [Target()]

	def test_executes_and_captures(self) -> None:
		m = self.manager
		m.executeTouchGesture(TouchGesture(R.TouchEvent("flickRight", 1, 0, 0, 0.0), "object"))
		m.executeTouchGesture(TouchGesture(R.TouchEvent("flickRight", 1, 0, 0, 0.0), "text"))
		self.assertEqual(self.calls, ["flickRight"], "en modo texto no hay orden para ese gesto")
		captured = []
		m.captureFunc = lambda g: captured.append(g.identifiers[0]) or True
		m.executeTouchGesture(TouchGesture(R.TouchEvent("hover", 1, 0, 0, 0.0), "object"))
		m.executeTouchGesture(TouchGesture(R.TouchEvent("doubleTap", 2, 0, 0, 0.0), "object"))
		self.assertEqual(captured, ["ts(object):2finger_doubletap"], "la exploración no se captura")
		self.assertEqual(self.calls, ["flickRight", "hover"])


class FakeReport:
	"""Informe HID simulado: valores y botones por colección."""

	def __init__(self, values: dict, buttons: dict) -> None:
		self.values = values
		self.buttons = buttons

	def value(self, page, usage, link):
		return self.values.get((page, usage, link))

	def pressed(self, page, link):
		return self.buttons.get((page, link), set())


def _finger(link, cid, x, y, tip=True, confident=True):
	values = {(TP.PAGE_GENERIC, TP.USAGE_X, link): x, (TP.PAGE_GENERIC, TP.USAGE_Y, link): y, (TP.PAGE_DIGITIZER, TP.USAGE_CONTACT_ID, link): cid}
	pressed = set()
	if tip:
		pressed.add(TP.USAGE_TIP_SWITCH)
	if confident:
		pressed.add(TP.USAGE_CONFIDENCE)
	return values, {(TP.PAGE_DIGITIZER, link): pressed}


def _report(count, *fingers):
	values: dict = {}
	buttons: dict = {}
	if count is not None:
		values[(TP.PAGE_DIGITIZER, TP.USAGE_CONTACT_COUNT, 0)] = count
	for v, b in fingers:
		values.update(v)
		buttons.update(b)
	return FakeReport(values, buttons)


class TouchpadTests(unittest.TestCase):
	def _caps(self):
		vcaps = []
		for link in (1, 2):
			for usage, maxv in ((TP.USAGE_X, 1000), (TP.USAGE_Y, 500)):
				c = TP.HIDP_VALUE_CAPS()
				c.UsagePage = TP.PAGE_GENERIC
				c.LinkCollection = link
				c.LogicalMin = 0
				c.LogicalMax = maxv
				c.NotRange.Usage = usage
				vcaps.append(c)
			c = TP.HIDP_VALUE_CAPS()
			c.UsagePage = TP.PAGE_DIGITIZER
			c.LinkCollection = link
			c.NotRange.Usage = TP.USAGE_CONTACT_ID
			vcaps.append(c)
		c = TP.HIDP_VALUE_CAPS()
		c.UsagePage = TP.PAGE_DIGITIZER
		c.LinkCollection = 0
		c.NotRange.Usage = TP.USAGE_CONTACT_COUNT
		vcaps.append(c)
		bcaps = []
		for link in (1, 2):
			b = TP.HIDP_BUTTON_CAPS()
			b.UsagePage = TP.PAGE_DIGITIZER
			b.LinkCollection = link
			b.IsRange = 1
			b.Range.UsageMin = TP.USAGE_TIP_SWITCH
			b.Range.UsageMax = TP.USAGE_CONFIDENCE
			bcaps.append(b)
		return vcaps, bcaps

	def test_struct_sizes(self) -> None:
		self.assertEqual(ctypes.sizeof(TP.HIDP_VALUE_CAPS), 72)
		self.assertEqual(ctypes.sizeof(TP.HIDP_BUTTON_CAPS), 72)
		self.assertEqual(ctypes.sizeof(TP.HIDP_CAPS), 64)

	def test_layout_from_caps(self) -> None:
		layout = TP.layoutFromCaps(*self._caps())
		self.assertEqual([f.link for f in layout.fingers], [1, 2])
		self.assertEqual(layout.contactCountLink, 0)
		f = layout.fingers[0]
		self.assertEqual((f.xMin, f.xMax, f.yMin, f.yMax), (0, 1000, 0, 500))
		self.assertTrue(f.hasContactId and f.hasConfidence)

	def test_frames_single_and_hybrid(self) -> None:
		layout = TP.layoutFromCaps(*self._caps())
		asm = TP.FrameAssembler(layout)
		frame = asm.feed(_report(2, _finger(1, 7, 100, 50), _finger(2, 9, 300, 60)))
		self.assertEqual([(c.cid, c.x, c.y, c.tip) for c in frame], [(7, 100, 50, True), (9, 300, 60, True)])
		# Modo híbrido: 3 contactos repartidos en dos informes (solo caben 2 por informe).
		layout3 = TP.TouchpadLayout(layout.fingers, 0)
		asm = TP.FrameAssembler(layout3)
		self.assertIsNone(asm.feed(_report(3, _finger(1, 1, 10, 10), _finger(2, 2, 20, 20))))
		frame = asm.feed(_report(0, _finger(1, 3, 30, 30), _finger(2, 99, 0, 0)))
		self.assertEqual([c.cid for c in frame], [1, 2, 3])
		# Recuento 0 sin fotograma pendiente: no queda ningún dedo.
		self.assertEqual(asm.feed(_report(0)), [])

	def test_palm_contact_is_not_a_touch(self) -> None:
		layout = TP.layoutFromCaps(*self._caps())
		frame = TP.FrameAssembler(layout).feed(_report(1, _finger(1, 4, 10, 10, confident=False)))
		self.assertEqual([(c.cid, c.tip) for c in frame], [(4, False)])

	def test_tracker_and_recognizer_end_to_end(self) -> None:
		layout = TP.layoutFromCaps(*self._caps())
		screen = (0, 0, 1001, 501)
		slot = layout.fingers[0]
		tracker = TP.ContactTracker(lambda s, x, y: TP.scaleToScreen(s, x, y, screen))
		asm = TP.FrameAssembler(layout)
		rec = R.GestureRecognizer()
		events = []
		t = 10.0

		def feed(report):
			nonlocal t
			t += 0.03
			frame = asm.feed(report)
			for kind, cid, x, y in tracker.update(frame, slot):
				events.extend(getattr(rec, kind)(cid, x, y, t))

		feed(_report(2, _finger(1, 1, 100, 100), _finger(2, 2, 400, 100)))
		feed(_report(2, _finger(1, 1, 101, 100), _finger(2, 2, 400, 101)))
		feed(_report(2, _finger(1, 1, 101, 100, tip=False), _finger(2, 2, 400, 101, tip=False)))
		events += rec.poll(t + 1)
		self.assertEqual([e.name for e in events], ["2finger_tap"])
		self.assertEqual(TP.scaleToScreen(slot, 1000, 500, (-100, 0, 1920, 1080)), (1819, 1079))

	def test_tracker_lost_contacts(self) -> None:
		tracker = TP.ContactTracker()
		self.assertEqual(tracker.update([TP.Contact(1, 5, 5, True)]), [("down", 1, 5, 5)])
		self.assertEqual(tracker.update([TP.Contact(1, 6, 5, True)]), [("move", 1, 6, 5)])
		self.assertEqual(tracker.update([]), [("up", 1, 6, 5)])

	def test_parse_raw_input_buffer(self) -> None:
		reports = [bytes([0x05, 1, 2, 3]), bytes([0x05, 4, 5, 6])]
		header = struct.pack("IIQQ", TP.RIM_TYPEHID, 0, 0x1234, 0)
		buf = header + struct.pack("II", 4, 2) + b"".join(reports)
		hDevice, parsed = TP.parseRawInputBuffer(buf)
		self.assertEqual(hDevice, 0x1234)
		self.assertEqual(parsed, reports)
		self.assertIsNone(TP.parseRawInputBuffer(struct.pack("IIQQ", 0, 0, 1, 0) + b"\0" * 8), "no es HID")
		self.assertIsNone(TP.parseRawInputBuffer(header + struct.pack("II", 4, 5) + b"\0" * 4), "informe truncado")


class WindowTests(unittest.TestCase):
	"""Crea las ventanas un instante y las destruye. No captura ningún toque:
	la superposición se crea oculta o transparente a la entrada."""

	def test_hardware_detection(self) -> None:
		from tiresias.touch import win32

		present, maxTouches = win32.touchHardware()
		self.assertIsInstance(present, bool)
		self.assertGreaterEqual(maxTouches, 0)
		self.assertIsInstance(win32.hasUiAccess(), bool)

	def test_overlay_create_and_destroy(self) -> None:
		from tiresias.touch import win32 as W
		from tiresias.touch.overlay import TouchInputWindow

		for show in (False, True):
			with self.subTest(show=show):
				win = TouchInputWindow(lambda events: None, show=show, passthrough=True)
				win.start()
				try:
					hwnd = win.hwnd
					self.assertTrue(W.user32.IsWindow(hwnd))
					ex = win.exStyle()
					for flag in (W.WS_EX_TOPMOST, W.WS_EX_LAYERED, W.WS_EX_TOOLWINDOW, W.WS_EX_NOACTIVATE, W.WS_EX_TRANSPARENT):
						self.assertTrue(ex & flag, hex(flag))
					self.assertEqual(bool(W.user32.IsWindowVisible(hwnd)), show)
					self.assertFalse(win.isCapturing, "en la prueba nunca tapa la pantalla")
					win.allowMouseThrough()  # desde otro hilo: no debe bloquearse
					self.assertTrue(win.exStyle() & W.WS_EX_TRANSPARENT)
				finally:
					win.stop()
				self.assertFalse(W.user32.IsWindow(hwnd))
				self.assertFalse(win.isRunning)

	def test_touchpad_window_create_and_destroy(self) -> None:
		from tiresias.touch import win32 as W
		from tiresias.touch.touchpad import TouchpadInput

		tp = TouchpadInput(lambda events: None)
		tp.start()
		hwnd = tp.hwnd
		try:
			self.assertTrue(W.user32.IsWindow(hwnd))
		finally:
			tp.stop()
		self.assertFalse(W.user32.IsWindow(hwnd))


class HandlerTests(unittest.TestCase):
	def test_no_input_never_starts_capture(self) -> None:
		from tiresias.config import conf
		from tiresias.touch.handler import TouchHandler

		h = TouchHandler()
		old = conf["touch"]["enabled"]
		try:
			conf["touch"]["enabled"] = True
			h.initialize(inputAllowed=False)
			self.assertFalse(h.wantsTouch())
			self.assertIsNone(h.window)
			self.assertIsNone(h.touchpad)
			msg = h.setEnabled(True)
			self.assertIsNone(h.window)
			self.assertIsInstance(msg, str)
		finally:
			h.terminate()
			conf["touch"]["enabled"] = old

	def test_modes_cycle_without_browse_document(self) -> None:
		from tiresias.touch.handler import TouchHandler

		h = TouchHandler()
		self.assertEqual(h.availableModes(), ["object", "text"])
		self.assertEqual(h.cycleMode(), "modo texto")
		self.assertEqual(h.cycleMode(), "modo objeto")
		h.mode = "browse"
		self.assertEqual(h.effectiveMode(), "object", "sin documento en modo exploración se usa el modo objeto")

	def test_recognizer_settings_from_config(self) -> None:
		from tiresias.touch.handler import TouchHandler

		s = TouchHandler().recognizerSettings()
		self.assertAlmostEqual(s.multiTapTimeout, 0.3)
		self.assertGreaterEqual(s.minFlickDistance, 50)


if __name__ == "__main__":
	unittest.main()
