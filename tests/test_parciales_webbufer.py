"""Pruebas del grupo «web-búfer» del modo exploración.

- #3997 (G20): entrada y salida de contenedores en líneas propias del búfer.
- #11073 (G39): el texto que sigue a un enlace sin disposición en pantalla.
- #15732 (G38): coma y Mayúsculas+coma sin salir del contenedor.

El árbol UIA se simula con los elementos falsos de ``test_browse``.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_browse import FakeEl, group, text  # noqa: E402
from tiresias.a11y import uia_client as uc  # noqa: E402
from tiresias.browse.buffer import VirtualBuffer  # noqa: E402
from tiresias.browse.document import BrowseModeDocument  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.objects.roles import Role  # noqa: E402


def item(t: str, *extra) -> FakeEl:
	return FakeEl(uc.CT_LISTITEM, "", [text(t), *extra])


def lst(*items) -> FakeEl:
	return FakeEl(uc.CT_LIST, "", list(items))


def link(t: str) -> FakeEl:
	return FakeEl(uc.CT_HYPERLINK, t, [text(t)])


def makeDoc() -> BrowseModeDocument:
	doc = BrowseModeDocument.__new__(BrowseModeDocument)
	doc.__dict__["buffer"] = None
	doc.__dict__["caret"] = 0
	doc.__dict__["selectionAnchor"] = None
	doc.__dict__["_textPatternCache"] = False
	return doc


def build(root: FakeEl, doc: BrowseModeDocument | None = None) -> VirtualBuffer:
	buf = VirtualBuffer(root)
	if doc is not None:
		buf.containerLabels = doc.containerLineLabels if conf["browseMode"]["containerLinesApart"] else None
	buf.build()
	if doc is not None:
		doc.__dict__["buffer"] = buf
	return buf


class Base(unittest.TestCase):
	def setUp(self) -> None:
		self._saved = dict(conf["browseMode"])
		self._savedDf = dict(conf["documentFormatting"])
		conf["browseMode"]["useScreenLayout"] = False
		conf["browseMode"]["maxLineLength"] = 100
		conf["browseMode"]["containerLinesApart"] = False
		conf["browseMode"]["breakAfterLinks"] = True
		conf["documentFormatting"]["reportLists"] = True

	def tearDown(self) -> None:
		for k, v in self._saved.items():
			conf["browseMode"][k] = v
		for k, v in self._savedDf.items():
			conf["documentFormatting"][k] = v


class ContainerLinesTests(Base):
	"""#3997: «lista con N elementos» y «fuera de lista» en líneas aparte."""

	def _simple(self):
		self.lstEl = lst(item("uno"), item("dos"))
		return FakeEl(uc.CT_DOCUMENT, "d", [group(text("antes")), self.lstEl, group(text("después"))])

	def test_option_off_keeps_classic_buffer(self) -> None:
		doc = makeDoc()
		buf = build(self._simple(), doc)
		self.assertEqual(buf.text, "antes\nuno\ndos\ndespués\n")
		self.assertEqual(buf.boundaryLines, [])

	def test_lines_inserted_and_offsets_consistent(self) -> None:
		conf["browseMode"]["containerLinesApart"] = True
		doc = makeDoc()
		buf = build(self._simple(), doc)
		self.assertEqual(buf.text, "antes\nlista con 2 elementos\nuno\ndos\nfuera de lista\ndespués\n")
		# Cada trozo sigue apuntando a su texto.
		for s, e, node in buf.chunks:
			self.assertEqual(buf.text[s:e], node.name, node)
		listNode = buf.byRid[self.lstEl.rid]
		self.assertEqual(buf.text[listNode.start : listNode.end], "lista con 2 elementos\nuno\ndos\nfuera de lista\n")
		self.assertEqual([b[3] for b in buf.boundaryLines], ["start", "end"])
		self.assertIs(buf.nodeAt(buf.text.find("uno")).role, Role.STATICTEXT)
		self.assertEqual(buf.containersAt(buf.text.find("fuera"))[-1], listNode)
		# No se copian ni separan párrafos de forma rara.
		self.assertEqual(buf.plainText(0, len(buf.text)), "antes\nuno\ndos\ndespués\n")
		self.assertFalse(buf.isSoftLineBreak(buf.text.find("\nuno")))
		self.assertEqual(buf.contentOffset(buf.text.find("lista"), 1), buf.text.find("uno"))

	def test_nested_containers_order(self) -> None:
		conf["browseMode"]["containerLinesApart"] = True
		inner = lst(item("sub"))
		outer = lst(item("a"), item("b", inner))
		buf = build(FakeEl(uc.CT_DOCUMENT, "d", [outer, group(text("fin"))]), makeDoc())
		self.assertEqual(buf.text, "lista con 2 elementos\na\nb\nlista con 1 elemento\nsub\nfuera de lista\nfuera de lista\nfin\n")
		o, i = buf.byRid[outer.rid], buf.byRid[inner.rid]
		self.assertTrue(o.start <= i.start and i.end <= o.end)
		self.assertEqual(buf.text[i.start : i.end], "lista con 1 elemento\nsub\nfuera de lista\n")
		self.assertTrue(buf.text[o.start : o.end].endswith("fuera de lista\nfuera de lista\n"))

	def test_splice_equals_full_build(self) -> None:
		conf["browseMode"]["containerLinesApart"] = True
		doc = makeDoc()
		target = lst(item("x"))
		root = FakeEl(uc.CT_DOCUMENT, "d", [group(text("uno")), target, lst(item("tres"))])
		buf = build(root, doc)
		target.children = [item("x"), item("y")]
		sub = VirtualBuffer(target)
		sub.containerLabels = doc.containerLineLabels
		block = buf.byRid[target.rid]
		sub.rootParent = block.parent
		sub.build()
		buf.spliceSubtree(block, sub)
		full = build(root, makeDoc())
		self.assertEqual(buf.text, full.text)
		self.assertEqual([(n.role, n.start, n.end) for n in buf.nodes], [(n.role, n.start, n.end) for n in full.nodes])
		self.assertEqual([(s, e, k) for s, e, _c, k in buf.boundaryLines], [(s, e, k) for s, e, _c, k in full.boundaryLines])

	def test_transitions_not_repeated_on_lines(self) -> None:
		conf["browseMode"]["containerLinesApart"] = True
		doc = makeDoc()
		buf = build(self._simple(), doc)
		t = buf.text

		def move(a: str, b: str) -> list:
			old, new = t.find(a), t.find(b)
			s, e = buf.lineBounds(new)
			return doc._containerTransitions(old, new, s, e)

		self.assertEqual(move("antes", "lista"), [])
		self.assertEqual(move("lista", "uno"), [])
		self.assertEqual(move("dos", "fuera"), [])
		self.assertEqual(move("fuera", "después"), [])
		self.assertEqual(move("después", "fuera"), [])
		self.assertEqual(move("lista", "antes"), [])
		# Un salto que no pasa por las líneas sí avisa.
		self.assertEqual(move("antes", "dos"), ["lista con 2 elementos"])
		self.assertEqual(move("uno", "después"), ["fuera de lista"])

	def test_line_speech(self) -> None:
		conf["browseMode"]["containerLinesApart"] = True
		doc = makeDoc()
		buf = build(self._simple(), doc)
		s, e = buf.lineBounds(buf.text.find("lista"))
		self.assertEqual(" ".join(x for x in doc.getRangeSpeech(s, e) if isinstance(x, str)).strip(), "lista con 2 elementos")
		s, e = buf.lineBounds(buf.text.find("uno"))
		spoken = " ".join(x for x in doc.getRangeSpeech(s, e) if isinstance(x, str))
		self.assertNotIn("lista", spoken)
		self.assertIn("uno", spoken)

	def test_copy_skips_container_lines(self) -> None:
		conf["browseMode"]["containerLinesApart"] = True
		doc = makeDoc()
		buf = build(self._simple(), doc)
		doc.selectionAnchor = 0
		doc.caret = len(buf.text)
		doc.syncNativeSelection = lambda: False
		gesture = mock.Mock()
		with mock.patch("tiresias.browse.document.api.copyToClip") as clip:
			doc.script_copySelection(gesture)
		clip.assert_called_once()
		self.assertEqual(clip.call_args[0][0], "antes\nuno\ndos\ndespués\n")

	def test_layout_signature_follows_options(self) -> None:
		a = BrowseModeDocument.layoutSignature()
		conf["browseMode"]["containerLinesApart"] = True
		b = BrowseModeDocument.layoutSignature()
		self.assertNotEqual(a, b)
		conf["documentFormatting"]["reportLists"] = False
		self.assertNotEqual(b, BrowseModeDocument.layoutSignature())
		conf["browseMode"]["containerLinesApart"] = False
		conf["browseMode"]["breakAfterLinks"] = False
		self.assertNotEqual(a, BrowseModeDocument.layoutSignature())

	def test_reported_formatting_off_means_no_line(self) -> None:
		conf["browseMode"]["containerLinesApart"] = True
		conf["documentFormatting"]["reportLists"] = False
		buf = build(self._simple(), makeDoc())
		self.assertEqual(buf.text, "antes\nuno\ndos\ndespués\n")


class TextAfterLinkTests(Base):
	"""#11073: sin disposición en pantalla, el enlace va solo en su línea."""

	def _para(self, after: str) -> FakeEl:
		return FakeEl(uc.CT_DOCUMENT, "d", [group(text("Ver"), link("aquí"), text(after))])

	def test_text_after_link_on_its_own_line(self) -> None:
		buf = build(self._para("lo que sigue"))
		self.assertEqual([ln.strip() for ln in buf.text.splitlines()], ["Ver", "aquí", "lo que sigue"])
		# Sigue siendo un único párrafo.
		s, e = buf.paragraphBounds(0)
		self.assertEqual(e, len(buf.text))

	def test_closing_punctuation_stays_with_link(self) -> None:
		buf = build(self._para(", y luego más."))
		self.assertEqual([ln.strip() for ln in buf.text.splitlines()], ["Ver", "aquí,", "y luego más."])
		for s, e, node in buf.chunks:
			self.assertTrue(buf.text[s:e].strip())
		buf = build(self._para("."))
		self.assertEqual([ln.strip() for ln in buf.text.splitlines()], ["Ver", "aquí."])
		# «.com» no es puntuación de cierre.
		buf = build(self._para(".com es un dominio"))
		self.assertEqual([ln.strip() for ln in buf.text.splitlines()], ["Ver", "aquí", ".com es un dominio"])

	def test_option_off_keeps_text_with_link(self) -> None:
		conf["browseMode"]["breakAfterLinks"] = False
		buf = build(self._para("lo que sigue"))
		self.assertEqual([ln.strip() for ln in buf.text.splitlines()], ["Ver", "aquí lo que sigue"])
		# Los controles siguen en su propia línea.
		btn = FakeEl(uc.CT_BUTTON, "Enviar")
		buf = build(FakeEl(uc.CT_DOCUMENT, "d", [group(btn, text("detrás"))]))
		self.assertEqual([ln.strip() for ln in buf.text.splitlines()], ["Enviar", "detrás"])

	def test_screen_layout_unchanged(self) -> None:
		conf["browseMode"]["useScreenLayout"] = True
		buf = build(self._para("lo que sigue"))
		self.assertEqual(buf.text, "Ver aquí lo que sigue\n")


class ContainerNavigationTests(Base):
	"""#15732: coma y Mayúsculas+coma no salen del contenedor."""

	def setUp(self) -> None:
		super().setUp()
		self.doc = makeDoc()
		self.moves: list[int] = []
		self.messages: list[str] = []

		def moveCaret(offset, speakUnit=None, node=None):
			self.moves.append(offset)
			self.doc.caret = offset

		self.doc._moveCaret = moveCaret
		p1 = mock.patch("tiresias.browse.document.speech.speakMessage", side_effect=self.messages.append)
		p2 = mock.patch("tiresias.browse.document.speech.cancelSpeech")
		p3 = mock.patch("tiresias.browse.document.tones.playSound")
		for p in (p1, p2, p3):
			p.start()
			self.addCleanup(p.stop)

	def _build(self):
		self.inner = lst(item("sub1"), item("sub2"))
		self.outer = lst(item("a"), item("b", self.inner), item("c"))
		return build(FakeEl(uc.CT_DOCUMENT, "d", [group(text("antes")), self.outer, group(text("después"))]), self.doc)

	def test_end_then_report(self) -> None:
		buf = self._build()
		self.doc.caret = buf.text.find("a\n")
		self.doc.nextContainerBoundary(True)
		self.assertEqual(buf.text[self.doc.caret :].split("\n")[0], "c")
		self.doc.nextContainerBoundary(True)
		self.assertEqual(self.messages, ["final de lista"])
		self.assertEqual(len(self.moves), 1)

	def test_start_then_report(self) -> None:
		buf = self._build()
		self.doc.caret = buf.text.find("c\n")
		self.doc.nextContainerBoundary(False)
		self.assertEqual(self.doc.caret, buf.byRid[self.outer.rid].start)
		self.doc.nextContainerBoundary(False)
		self.assertEqual(self.messages, ["principio de lista"])

	def test_nested_stays_inside_inner(self) -> None:
		buf = self._build()
		self.doc.caret = buf.text.find("sub1")
		self.doc.nextContainerBoundary(True)
		self.assertEqual(self.doc.caret, buf.text.find("sub2"))
		self.doc.nextContainerBoundary(False)
		self.assertEqual(self.doc.caret, buf.byRid[self.inner.rid].start)

	def test_exit_command_leaves_container(self) -> None:
		buf = self._build()
		self.doc.caret = buf.text.find("a\n")
		self.doc.exitContainer()
		self.assertEqual(self.doc.caret, buf.text.find("después"))

	def test_end_is_exit_line_with_container_lines(self) -> None:
		conf["browseMode"]["containerLinesApart"] = True
		buf = self._build()
		self.doc.caret = buf.text.find("a\n")
		self.doc.nextContainerBoundary(True)
		outer = buf.byRid[self.outer.rid]
		self.assertEqual(buf.boundaryAt(self.doc.caret)[2], outer)
		self.assertEqual(buf.boundaryAt(self.doc.caret)[3], "end")
		self.doc.exitContainer()
		self.assertEqual(self.doc.caret, buf.text.find("después"))

	def test_outside_container(self) -> None:
		buf = self._build()
		self.doc.caret = buf.text.find("antes")
		self.doc.nextContainerBoundary(True)
		self.assertEqual(self.messages, ["no se está dentro de un contenedor"])

	def test_scripts_and_gestures(self) -> None:
		gestures = dict(BrowseModeDocument.iterClassGestures())
		self.assertEqual(gestures.get("kb:,"), "quickNavContainerEnd")
		self.assertEqual(gestures.get("kb:shift+,"), "quickNavContainerStart")
		self.assertTrue(hasattr(BrowseModeDocument, "script_quickNavContainerExit"))
		self.assertNotIn("quickNavContainerExit", gestures.values())


if __name__ == "__main__":
	unittest.main()
