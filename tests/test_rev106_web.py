"""Revisión 1.0.6: modo exploración web y matemáticas en el modo exploración.

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
from tiresias.browse import flexweb, html_details, loader  # noqa: E402
from tiresias.browse.buffer import VirtualBuffer  # noqa: E402
from tiresias.browse.document import BrowseModeDocument  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.objects.roles import Role  # noqa: E402


def link(t: str) -> FakeEl:
	return FakeEl(uc.CT_HYPERLINK, t, [text(t)])


def item(t: str) -> FakeEl:
	return FakeEl(uc.CT_LISTITEM, "", [text(t)])


def cell(t: str, r: int, c: int) -> FakeEl:
	return FakeEl(uc.CT_DATAITEM, "", [text(t)], P_GRIDITEMROW=r, P_GRIDITEMCOLUMN=c, P_ARIAROLE="cell")


def row(*cells) -> FakeEl:
	return FakeEl(uc.CT_DATAITEM, "", list(cells), P_ARIAROLE="row")


def table(prefix: str) -> FakeEl:
	return FakeEl(uc.CT_TABLE, "", [row(*[cell(f"{prefix}{r}{c}", r, c) for c in range(2)]) for r in range(2)])


def makeDoc(root: FakeEl) -> BrowseModeDocument:
	doc = BrowseModeDocument.__new__(BrowseModeDocument)
	d = doc.__dict__
	d.update(buffer=None, caret=0, selectionAnchor=None, _textPatternCache=False, _passThrough=False, _built=True, navLevel="line", _positionStack=[], _docKey="prueba", _docUrl="")
	d["rootObject"] = mock.Mock(element=root, processID=0)
	buf = VirtualBuffer(root)
	buf.build()
	d["buffer"] = buf
	return doc


class Base(unittest.TestCase):
	def setUp(self) -> None:
		self._saved = dict(conf["browseMode"])
		conf["browseMode"]["useScreenLayout"] = True
		conf["browseMode"]["maxLineLength"] = 200
		conf["browseMode"]["containerLinesApart"] = False
		conf["browseMode"]["quickNavWrap"] = True
		self.messages: list[str] = []
		self.sounds: list[str] = []
		for p in (
			mock.patch("tiresias.speech.speakMessage", side_effect=lambda m, *a, **k: self.messages.append(m)),
			mock.patch("tiresias.speech.cancelSpeech"),
			mock.patch("tiresias.audio.tones.playSound", side_effect=self.sounds.append),
		):
			p.start()
			self.addCleanup(p.stop)

	def tearDown(self) -> None:
		for k, v in self._saved.items():
			conf["browseMode"][k] = v


class QuickNavTests(Base):
	def _doc(self):
		root = FakeEl(uc.CT_DOCUMENT, "d", [group(text("Antes")), group(text("Menú:"), link("uno"), link("dos"), link("tres")), group(text("Después"))])
		doc = makeDoc(root)
		self.moves: list[int] = []

		def moveCaret(offset, speakUnit=None, node=None):
			self.moves.append(offset)
			doc.caret = offset

		doc.__dict__["_moveCaret"] = moveCaret
		return doc

	def _at(self, doc) -> str:
		return doc.buffer.text[doc.caret :].strip().split()[0]

	def test_previous_link_on_same_line(self) -> None:
		# Varios enlaces en la misma línea (distribución en pantalla): Mayúsculas+K
		# iba al último enlace del documento (dando la vuelta) en lugar del anterior.
		doc = self._doc()
		buf = doc.buffer
		self.assertEqual(buf.lineBounds(buf.text.find("uno"))[0], buf.lineBounds(buf.text.find("tres"))[0])
		doc.caret = buf.byRid[[n for n in buf.nodes if n.role == Role.LINK][2].rid].start
		doc.quickNav("link", -1)
		self.assertEqual(self._at(doc), "dos")
		doc.quickNav("link", -1)
		self.assertEqual(self._at(doc), "uno")
		self.assertNotIn("wrap", self.sounds)

	def test_previous_from_inside_link_skips_it(self) -> None:
		doc = self._doc()
		doc.caret = doc.buffer.text.find("os")  # dentro de «dos»
		doc.quickNav("link", -1)
		self.assertEqual(self._at(doc), "uno")

	def test_next_link_on_same_line(self) -> None:
		doc = self._doc()
		doc.caret = doc.buffer.text.find("uno") - 1
		doc.quickNav("link", 1)
		self.assertEqual(self._at(doc), "dos")


class SingleLetterNavTests(Base):
	def test_option_is_read_live(self) -> None:
		# La opción se copiaba al crear el documento: cambiarla en Opciones, con
		# un perfil por sitio o desde otra pestaña no afectaba a los ya abiertos.
		from tiresias.baseobject import ScriptableObject

		doc = makeDoc(FakeEl(uc.CT_DOCUMENT, "d", [group(text("a"))]))
		gesture = mock.Mock(modifierNames=[])
		with mock.patch.object(ScriptableObject, "getScript", lambda self, g: self.script_quickNavNextHeading):
			conf["browseMode"]["singleLetterNavigation"] = True
			self.assertIsNotNone(doc.getScript(gesture))
			conf["browseMode"]["singleLetterNavigation"] = False
			self.assertIsNone(doc.getScript(gesture))
			# Con un modificador distinto de Mayúsculas sigue funcionando.
			self.assertIsNotNone(doc.getScript(mock.Mock(modifierNames=["control"])))
		doc.script_toggleSingleLetterNav(gesture)
		self.assertTrue(conf["browseMode"]["singleLetterNavigation"])
		self.assertEqual(self.messages[-1], "navegación con una sola letra activada")


class LinkPrefixTests(Base):
	def test_same_page_link_uses_buffer_url(self) -> None:
		# El tipo de enlace se calcula con el destino guardado en el búfer, sin
		# pedirlo de nuevo a la página por cada enlace que se lee.
		saved = dict(conf["documentFormatting"])
		self.addCleanup(lambda: conf["documentFormatting"].update(saved))
		conf["documentFormatting"]["reportLinks"] = True
		conf["documentFormatting"]["reportLinkType"] = True
		anchor = FakeEl(uc.CT_HYPERLINK, "Ir", [text("Ir")], P_VALUEVALUE="https://ej.com/p#sec")
		other = FakeEl(uc.CT_HYPERLINK, "Otro", [text("Otro")], P_VALUEVALUE="https://ej.com/q")
		doc = makeDoc(FakeEl(uc.CT_DOCUMENT, "d", [group(anchor), group(other)]))
		doc.__dict__["_docUrl"] = "https://ej.com/p"
		buf = doc.buffer
		self.assertIn("en esta página", doc.fieldPrefix(buf.byRid[anchor.rid]))
		self.assertNotIn("en esta página", doc.fieldPrefix(buf.byRid[other.rid]))


class ElementsListTests(Base):
	def test_form_fields_exclude_plain_lists(self) -> None:
		# Un <ul> normal no es un campo de formulario (la tecla F ya lo excluía).
		root = FakeEl(
			uc.CT_DOCUMENT,
			"d",
			[
				FakeEl(uc.CT_LIST, "", [item("a"), item("b")]),
				FakeEl(uc.CT_LIST, "Opciones", [item("x")], P_ISKEYBOARDFOCUSABLE=True),
				FakeEl(uc.CT_EDIT, "Nombre"),
				FakeEl(uc.CT_BUTTON, "Enviar"),
			],
		)
		doc = makeDoc(root)
		labels = [label for label, _o, _l in doc.getElements("formField")]
		self.assertFalse(any(label.startswith("a b") for label in labels), labels)
		self.assertTrue(any("Nombre" in label for label in labels))
		self.assertTrue(any(label.startswith("x") for label in labels))
		self.assertEqual([label for label, _o, _l in doc.getElements("button")], ["Enviar botón"])


class TableBuildTests(Base):
	def test_each_table_maps_its_own_cells(self) -> None:
		root = FakeEl(uc.CT_DOCUMENT, "d", [group(text("x")), table("A"), group(text("y")), table("B")])
		buf = VirtualBuffer(root)
		buf.build()
		tables = [n for n in buf.nodes if n.role == Role.TABLE]
		self.assertEqual(len(tables), 2)
		for t, prefix in zip(tables, ("A", "B"), strict=True):
			cells = buf.tables[id(t)]
			self.assertEqual(sorted(cells), [(1, 1), (1, 2), (2, 1), (2, 2)])
			self.assertEqual(buf.text[cells[(2, 2)].start : cells[(2, 2)].end].strip(), f"{prefix}11")
			self.assertEqual(t.tableSize, (2, 2))


class SpliceTests(Base):
	def test_splice_keeps_math_and_drops_stale_caches(self) -> None:
		inner = group(text("viejo"))
		root = FakeEl(uc.CT_DOCUMENT, "d", [group(text("a")), inner])
		buf = VirtualBuffer(root)
		buf.build()
		block = buf.byRid[inner.rid]
		old = block.children[0]
		buf._mathByNode = {id(old): "<math>viejo</math>"}
		buf.__dict__["_textBlocks"] = (len(buf.text), [block])
		buf.__dict__["_blockStyles"] = {id(block): ("x",)}
		sub = VirtualBuffer(inner)
		sub.rootParent = block.parent
		sub.build()
		newNode = sub.root.children[0]
		sub._mathByNode = {id(newNode): "<math>nuevo</math>"}
		buf.spliceSubtree(block, sub)
		self.assertEqual(buf._mathByNode.get(id(newNode)), "<math>nuevo</math>")
		self.assertNotIn(id(old), buf._mathByNode)
		self.assertNotIn("_textBlocks", buf.__dict__)
		self.assertNotIn("_blockStyles", buf.__dict__)


class LoaderTests(Base):
	def test_large_block_rebuilds_in_background(self) -> None:
		inner = group(*[text(f"t{i}") for i in range(10)])
		root = FakeEl(uc.CT_DOCUMENT, "d", [group(text("a")), inner])
		doc = makeDoc(root)
		el = inner.children[3]
		with mock.patch.object(loader, "MAX_PARTIAL_NODES", 1000):
			blocks = doc._blocksToUpdate([el])
		self.assertEqual([b.rid for b in blocks], [inner.rid])
		with mock.patch.object(loader, "MAX_PARTIAL_NODES", 5):
			self.assertIsNone(doc._blocksToUpdate([el]))

	def test_refresh_is_asynchronous_and_announced_when_done(self) -> None:
		root = FakeEl(uc.CT_DOCUMENT, "d", [group(text("a"))])
		doc = makeDoc(root)
		doc._loaderInit()
		with mock.patch.object(BrowseModeDocument, "requestRebuild") as req, mock.patch.object(BrowseModeDocument, "_rebuild") as sync:
			doc.script_refreshBuffer(mock.Mock())
		req.assert_called_once()
		sync.assert_not_called()
		self.assertEqual(self.messages, [])
		doc._buildGeneration = 3
		doc._building = True
		with mock.patch.object(BrowseModeDocument, "_installBuffer"), mock.patch.object(BrowseModeDocument, "_notifyNewNodes"), mock.patch.object(BrowseModeDocument, "_onReady"):
			doc._onBuildDone(3, doc.buffer, None, False)
		self.assertEqual(self.messages, ["documento actualizado"])
		# Solo una vez.
		with mock.patch.object(BrowseModeDocument, "_installBuffer"), mock.patch.object(BrowseModeDocument, "_notifyNewNodes"), mock.patch.object(BrowseModeDocument, "_onReady"):
			doc._onBuildDone(3, doc.buffer, None, False)
		self.assertEqual(self.messages, ["documento actualizado"])


class CoreThreadBudgetTests(Base):
	def test_math_prefetch_is_short_on_core_thread(self) -> None:
		from tiresias.mathpres import browse_support, providers

		formula = FakeEl(uc.CT_TEXT, "", [text("x")], P_ARIAROLE="math", P_BOUNDINGRECT=(1, 2, 3, 4))
		root = FakeEl(uc.CT_DOCUMENT, "d", [formula])
		buf = VirtualBuffer(root)
		calls: list[float] = []

		def prefetch(hwnd, targets, timeout=4.0):
			calls.append(timeout)
			return {}

		with mock.patch.object(providers, "windowForElement", return_value=1234), mock.patch.object(providers, "prefetchForDocument", side_effect=prefetch), mock.patch.object(browse_support, "_findLabelOnlyMath"):
			with mock.patch("tiresias.queue_handler.isCoreThread", return_value=False):
				browse_support.prefetch(buf, root)
			with mock.patch("tiresias.queue_handler.isCoreThread", return_value=True):
				browse_support.prefetch(buf, root)
		self.assertEqual(len(calls), 2)
		self.assertGreaterEqual(calls[0], 1.0)
		self.assertLessEqual(calls[1], 0.3)

	def test_graphic_budget_expires_on_core_thread(self) -> None:
		# El tiempo gastado al construir el búfer caducaba solo dentro de
		# ``rawPath``, que no se llegaba a llamar: las consultas posteriores
		# (abreviaturas de encabezados) no se hacían nunca.
		from tiresias.a11y import ia2_bridge

		buf = VirtualBuffer(None)
		buf._frameworkId = "Gecko"
		res = ia2_bridge.PathResolver(lifetime=5.0)
		res.spent = 10.0
		res._created -= 60
		buf._ia2Resolver = res
		node = mock.Mock(element=object(), rid=(1, 2))
		with mock.patch("tiresias.queue_handler.isCoreThread", return_value=True), mock.patch.object(ia2_bridge, "attributesForElement", return_value={"abbr": "Pob."}) as attrs, mock.patch.object(ia2_bridge.PathResolver, "rawPath", return_value=([0], [1])):
			self.assertEqual(html_details.nodeIA2Attributes(buf, node), {"abbr": "Pob."})
		attrs.assert_called_once()
		self.assertEqual(html_details.CORE_GRAPHIC_BUDGET, 0.3)


class FlexWebTests(Base):
	def test_never_hides_the_whole_document(self) -> None:
		root = FakeEl(uc.CT_DOCUMENT, "Página", [group(text("sin nombre"))])
		buf = VirtualBuffer(root)
		buf.build()
		block = buf.root.children[0]
		self.assertIsNone(flexweb.ruleForNode(block))
		named = FakeEl(uc.CT_DOCUMENT, "Página", [group(text("anuncio"), P_AUTOMATIONID="pub")])
		buf = VirtualBuffer(named)
		buf.build()
		rule = flexweb.ruleForNode(buf.root.children[0].children[0])
		self.assertEqual(rule["id"], "pub")


if __name__ == "__main__":
	unittest.main()
