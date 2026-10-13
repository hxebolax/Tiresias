"""Pruebas del modo exploración (búfer, unidades de texto, tablas, ARIA, búsqueda, web flexible).

El árbol UIA se simula con elementos falsos que devuelven propiedades
«cacheadas», así que no hace falta ningún navegador.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import textinfo  # noqa: E402
from tiresias.a11y import uia_client as uc  # noqa: E402
from tiresias.browse import aria, flexweb, quicknav  # noqa: E402
from tiresias.browse.buffer import VirtualBuffer, visualOrder  # noqa: E402
from tiresias.browse.extras import findPattern  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.objects.roles import Role  # noqa: E402

_ridCounter = [100]


class FakeArray:
	def __init__(self, items: list) -> None:
		self.items = items

	@property
	def Length(self) -> int:
		return len(self.items)

	def GetElement(self, i: int):
		return self.items[i]

	def QueryInterface(self, iface):
		return self


class FakeEl:
	"""Elemento UIA falso con propiedades «cacheadas» e hijos."""

	def __init__(self, ct: int, name: str = "", children: list | None = None, **props) -> None:
		_ridCounter[0] += 1
		self.rid = (42, _ridCounter[0])
		self.props = {uc.P_CONTROLTYPE: ct, uc.P_NAME: name, uc.P_RUNTIMEID: self.rid}
		for k, v in props.items():
			self.props[getattr(uc, k) if isinstance(k, str) and hasattr(uc, k) else k] = v
		self.children = children or []

	def GetCachedPropertyValueEx(self, propId: int, ignoreDefault: bool):
		# Las matrices de elementos no se leen nunca como VARIANT (montón dañado).
		assert propId not in uc.ELEMENT_ARRAY_PROPERTIES, "relación leída como VARIANT"
		return self.props.get(propId)

	#: Accesores tipados de las relaciones (CachedFlowsTo, CurrentControllerFor...).
	_TYPED = {
		"ControllerFor": uc.P_CONTROLLERFOR,
		"DescribedBy": uc.P_DESCRIBEDBY,
		"FlowsTo": uc.P_FLOWSTO,
		"FlowsFrom": uc.P_FLOWSFROM,
		"AnnotationObjects": uc.P_ANNOTATIONOBJECTS,
	}

	def __getattr__(self, name: str):
		if name != "props":
			for prefix in ("Cached", "Current"):
				if name.startswith(prefix) and name[len(prefix) :] in self._TYPED:
					return self.props.get(self._TYPED[name[len(prefix) :]])
		raise AttributeError(name)

	def QueryInterface(self, iface):
		return self

	def GetCachedPropertyValue(self, propId: int):
		return self.props.get(propId)

	def GetCachedChildren(self):
		return FakeArray(self.children)

	def BuildUpdatedCache(self, request):
		return self

	def GetRuntimeId(self):
		return list(self.rid)


def text(t: str, **props) -> FakeEl:
	return FakeEl(uc.CT_TEXT, t, **props)


def group(*children, name: str = "", **props) -> FakeEl:
	return FakeEl(uc.CT_GROUP, name, list(children), **props)


def build(root: FakeEl) -> VirtualBuffer:
	buf = VirtualBuffer(root)
	buf.build()
	return buf


class Base(unittest.TestCase):
	def setUp(self) -> None:
		self._saved = dict(conf["browseMode"])
		conf["browseMode"]["useScreenLayout"] = False
		conf["browseMode"]["maxLineLength"] = 40

	def tearDown(self) -> None:
		for k, v in self._saved.items():
			conf["browseMode"][k] = v


class BufferTests(Base):
	def test_headings_seven_to_nine(self) -> None:
		doc = FakeEl(uc.CT_DOCUMENT, "doc", [FakeEl(uc.CT_TEXT, "Ocho", [], P_ARIAROLE="heading", P_ARIAPROPERTIES="level=8")])
		buf = build(doc)
		node = next(n for n in buf.nodes if n.name == "Ocho")
		self.assertEqual(node.headingLevel(), 8)
		pred = next(q for q in quicknav.EXTRA_QUICK_NAV if q[1] == "heading8")[4]
		self.assertTrue(pred(node))

	def test_merged_cells_cover_their_coordinates(self) -> None:
		def cell(t, r, c, cs=1, ct=uc.CT_DATAITEM, aria="cell"):
			return FakeEl(ct, t, [text(t)], P_ARIAROLE=aria, P_GRIDITEMROW=r, P_GRIDITEMCOLUMN=c, P_GRIDITEMROWSPAN=1, P_GRIDITEMCOLUMNSPAN=cs)

		row1 = FakeEl(uc.CT_DATAITEM, "", [cell("A", 0, 0, ct=uc.CT_HEADERITEM, aria="columnheader"), cell("B", 0, 1, ct=uc.CT_HEADERITEM, aria="columnheader")], P_ARIAROLE="row")
		row2 = FakeEl(uc.CT_DATAITEM, "", [cell("ancha", 1, 0, cs=2)], P_ARIAROLE="row")
		table = FakeEl(uc.CT_TABLE, "t", [row1, row2], P_GRIDROWCOUNT=2, P_GRIDCOLUMNCOUNT=2)
		buf = build(FakeEl(uc.CT_DOCUMENT, "doc", [table]))
		cells = next(iter(buf.tables.values()))
		self.assertIs(cells[(2, 1)], cells[(2, 2)])
		self.assertEqual(cells[(2, 1)].colSpan, 2)
		# Los encabezados van en la misma línea que el resto de la fila.
		self.assertIn("A B", buf.text)

	def test_real_paragraph_joins_soft_breaks(self) -> None:
		long = "palabra " * 20
		buf = build(FakeEl(uc.CT_DOCUMENT, "doc", [group(text(long.strip())), group(text("Otro párrafo."))]))
		self.assertTrue(buf.softBreaks)
		s, e = buf.paragraphBounds(0)
		line = buf.lineBounds(0)
		self.assertGreater(e - s, line[1] - line[0])
		self.assertEqual(buf.text[s:e].replace("\n", " ").strip(), long.strip())

	def test_splice_equals_full_build(self) -> None:
		target = group(text("antes"))
		doc = FakeEl(uc.CT_DOCUMENT, "doc", [group(text("uno")), target, group(text("tres"))])
		buf = build(doc)
		target.children = [text("después del cambio"), text("y más")]
		sub = VirtualBuffer(target)
		block = buf.byRid[target.rid]
		sub.rootParent = block.parent
		sub.build()
		buf.spliceSubtree(block, sub)
		full = build(doc)
		self.assertEqual(buf.text, full.text)
		self.assertEqual([(n.role, n.start, n.end) for n in buf.nodes], [(n.role, n.start, n.end) for n in full.nodes])
		self.assertIn(target.rid, buf.byRid)

	def test_relations_and_aria_properties(self) -> None:
		dest = group(text("destino"))
		src = group(text("origen"), P_FLOWSTO=FakeArray([dest]))
		link = FakeEl(uc.CT_HYPERLINK, "menú", [text("menú")], P_ARIAPROPERTIES="haspopup=menu;current=page", P_VALUEVALUE="https://otro.com/x")
		buf = build(FakeEl(uc.CT_DOCUMENT, "doc", [src, dest, link]))
		node = buf.byRid[src.rid]
		self.assertEqual(node.relations["flowTo"], [dest.rid])
		lnk = buf.byRid[link.rid]
		self.assertEqual(lnk.url, "https://otro.com/x")
		self.assertEqual(aria.currentLabel(lnk.aria.get("current")), "página actual")

	def test_unlabeled_graphics_option(self) -> None:
		img = FakeEl(uc.CT_IMAGE, "Para obtener descripciones...", P_LOCALIZEDCONTROLTYPE="Gráfico sin descripción")
		conf["browseMode"]["reportUnlabeledGraphics"] = False
		self.assertNotIn("Para obtener", build(FakeEl(uc.CT_DOCUMENT, "d", [img])).text)
		self.assertNotIn("gráfico", build(FakeEl(uc.CT_DOCUMENT, "d", [img])).text)
		conf["browseMode"]["reportUnlabeledGraphics"] = True
		self.assertIn("gráfico sin descripción", build(FakeEl(uc.CT_DOCUMENT, "d", [img])).text)

	def test_dpub_and_figure_from_localized_type(self) -> None:
		fig = group(text("pie"), P_LOCALIZEDCONTROLTYPE="cifra")
		chap = group(text("cap"), P_LOCALIZEDCONTROLTYPE="capítulo")
		buf = build(FakeEl(uc.CT_DOCUMENT, "d", [fig, chap]))
		self.assertEqual(buf.byRid[fig.rid].role, Role.FIGURE)
		self.assertEqual(buf.byRid[chap.rid].semantic, "capítulo")

	def test_hidden_rules(self) -> None:
		ad = group(text("publicidad"), P_AUTOMATIONID="anuncio")
		buf = VirtualBuffer(FakeEl(uc.CT_DOCUMENT, "d", [ad, group(text("contenido"))]))
		buf.hiddenRules = flexweb.SiteRules("s", {"hidden": [{"id": "anuncio"}]})
		buf.build()
		self.assertNotIn("publicidad", buf.text)
		self.assertIn("contenido", buf.text)

	def test_visual_order_by_columns(self) -> None:
		def box(t, x, y, w=100):
			return group(text(t), P_BOUNDINGRECT=(x, y, w, 20))

		elems = [box("título", 0, 0, 500), box("izq1", 0, 50), box("der1", 300, 50), box("izq2", 0, 80), box("der2", 300, 80)]
		order = [e.children[0].props[uc.P_NAME] for e in visualOrder(elems)]
		self.assertEqual(order, ["título", "izq1", "izq2", "der1", "der2"])


class TextUnitTests(unittest.TestCase):
	def test_sentences_and_abbreviations(self) -> None:
		info = textinfo.StaticTextInfo(None, (0, 0), "Hola Sr. Pérez. ¿Qué tal? Bien.\nOtra.")
		info.expand(textinfo.UNIT_SENTENCE)
		self.assertEqual(info.text, "Hola Sr. Pérez. ")
		info.collapse()
		self.assertEqual(info.move(textinfo.UNIT_SENTENCE, 2), 2)
		info.expand(textinfo.UNIT_SENTENCE)
		self.assertEqual(info.text, "Bien.\n")

	def test_paragraph_styles(self) -> None:
		t = "uno\ndos\n\ntres\n"
		saved = conf["documentNavigation"]["paragraphStyle"]
		try:
			conf["documentNavigation"]["paragraphStyle"] = "multiLineBreak"
			info = textinfo.StaticTextInfo(None, (0, 0), t)
			info.expand(textinfo.UNIT_PARAGRAPH)
			self.assertEqual(info.text, "uno\ndos\n\n")
			conf["documentNavigation"]["paragraphStyle"] = "singleLineBreak"
			info = textinfo.StaticTextInfo(None, (0, 0), t)
			info.expand(textinfo.UNIT_PARAGRAPH)
			self.assertEqual(info.text, "uno\n")
		finally:
			conf["documentNavigation"]["paragraphStyle"] = saved

	def test_page_is_not_whole_document(self) -> None:
		t = "".join(f"línea {i}\n" for i in range(100))
		info = textinfo.StaticTextInfo(None, (0, 0), t)
		info.expand(textinfo.UNIT_PAGE)
		self.assertEqual(info.text.count("\n"), conf["browseMode"]["linesPerPage"])
		info = textinfo.StaticTextInfo(None, (0, 0), "a\fb\fc")
		info.expand(textinfo.UNIT_PAGE)
		self.assertEqual(info.text, "a\f")


class AriaTests(unittest.TestCase):
	def test_labels(self) -> None:
		self.assertEqual(aria.haspopupLabel("listbox"), "abre una lista")
		self.assertEqual(aria.haspopupLabel("false"), "")
		self.assertEqual(aria.currentLabel("step"), "paso actual")
		self.assertEqual(aria.sortLabel("descending"), "orden descendente")
		self.assertEqual(aria.orientationLabel(Role.SLIDER, 2), "vertical")
		self.assertEqual(aria.orientationLabel(Role.SLIDER, 1), "")
		self.assertEqual(aria.orientationLabel(Role.LIST, 1), "horizontal")

	def test_link_types(self) -> None:
		doc = "https://ejemplo.com/a/b.html"
		self.assertEqual(aria.linkType("https://ejemplo.com/a/b.html#sec", doc), aria.LINK_SAME_PAGE)
		self.assertEqual(aria.linkType("https://ejemplo.com/otra", doc), aria.LINK_SAME_SITE)
		self.assertEqual(aria.linkType("https://otro.org/", doc), aria.LINK_EXTERNAL)
		self.assertEqual(aria.linkTypeLabel("https://otro.org/", doc), "externo")


class FindTests(unittest.TestCase):
	def test_find_options(self) -> None:
		self.assertIsNotNone(findPattern("hola", False, False, False).search("HOLA"))
		self.assertIsNone(findPattern("hola", True, False, False).search("HOLA"))
		self.assertIsNone(findPattern("ola", False, True, False).search("hola"))
		self.assertIsNotNone(findPattern(r"B\d", False, False, True).search("Elemento B2"))
		self.assertIsNone(findPattern("(", False, False, True))


class FlexWebTests(unittest.TestCase):
	def test_rules_persist_per_site(self) -> None:
		tmp = tempfile.mkdtemp(prefix="tiresias_flex_")
		old = flexweb._file
		flexweb._file = lambda: os.path.join(tmp, "flexibleWeb.json")
		flexweb._resetForTests()
		try:
			flexweb.addHidden("https://www.ejemplo.com/pagina", {"id": "anuncio"})
			flexweb.setVisualOrder("https://www.ejemplo.com/otra", True)
			flexweb._resetForTests()
			rules = flexweb.rulesFor("https://www.ejemplo.com/x")
			self.assertEqual(rules.hidden, [{"id": "anuncio"}])
			self.assertTrue(rules.visualOrder)
			self.assertFalse(flexweb.rulesFor("https://otro.org/").hidden)
			flexweb.removeHidden("https://www.ejemplo.com/", 0)
			flexweb.setVisualOrder("https://www.ejemplo.com/", False)
			self.assertNotIn("www.ejemplo.com", flexweb.allSites())
		finally:
			flexweb._file = old
			flexweb._resetForTests()


class DocumentScriptsTests(unittest.TestCase):
	def test_quick_nav_types_have_scripts(self) -> None:
		from tiresias.browse.document import QUICK_NAV, BrowseModeDocument

		for _key, ident, *_rest in QUICK_NAV:
			cap = ident[0].upper() + ident[1:]
			self.assertTrue(hasattr(BrowseModeDocument, f"script_quickNavNext{cap}"), ident)
		gestures = dict(BrowseModeDocument.iterClassGestures())
		self.assertEqual(gestures.get("kb:7"), "quickNavNextHeading7")
		self.assertEqual(gestures.get("kb:alt+downarrow"), "nextSentence")
		self.assertEqual(gestures.get("kb:control+alt+pageup"), "tableFirstRow")
		self.assertNotIn("kb:", gestures)

	def test_buffer_format_info_from_page_semantics(self) -> None:
		from tiresias.browse import style
		from tiresias.browse.document import BrowseModeDocument

		mark = FakeEl(uc.CT_TEXT, "", [text("marcado")], P_LOCALIZEDCONTROLTYPE="destacado")
		bad = FakeEl(uc.CT_TEXT, "", [text("herror")], P_ARIAPROPERTIES="invalid=spelling")
		buf = build(FakeEl(uc.CT_DOCUMENT, "d", [group(mark), group(bad)]))
		doc = BrowseModeDocument.__new__(BrowseModeDocument)
		doc.__dict__["buffer"] = buf
		doc.__dict__["caret"] = 0
		doc.__dict__["_textPatternCache"] = False
		fmt = style.formatAt(doc, buf.text.find("marcado"))
		self.assertTrue(fmt.get("highlighted"))
		fmt = style.formatAt(doc, buf.text.find("herror"))
		self.assertTrue(fmt.get("spellingError"))


if __name__ == "__main__":
	unittest.main()
