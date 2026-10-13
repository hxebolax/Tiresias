"""Pruebas del grupo «web-ARIA y objetos» (peticiones parciales F23–F26).

- F23 (foros 1.17, #7910): caracteres restantes en los campos de edición.
- F24 (foros 1.18, #7412): imágenes sin texto alternativo y su nombre de archivo.
- F25 (foros 1.19): nombre de los objetos en su idioma.
- F26 (foros 1.20): describedby en grupos, ``<q>``, guiones blandos, abbr y
  aria-braille*.

El árbol UIA se simula con los elementos falsos de ``test_browse``; las
llamadas a IAccessible2 se sustituyen por objetos falsos.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_webaria_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]

from test_browse import FakeEl, group, text  # noqa: E402
from tiresias import presentation, speech  # noqa: E402
from tiresias.a11y import ia2_bridge  # noqa: E402
from tiresias.a11y import uia_client as uc  # noqa: E402
from tiresias.browse import html_details  # noqa: E402
from tiresias.browse.buffer import Node, VirtualBuffer  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.objects import text_limits  # noqa: E402
from tiresias.objects.roles import Role  # noqa: E402
from tiresias.speech.commands import LangChangeCommand  # noqa: E402


def build(root: FakeEl) -> VirtualBuffer:
	buf = VirtualBuffer(root)
	buf.build()
	return buf


class _ConfMixin(unittest.TestCase):
	SECTIONS = ("browseMode", "documentFormatting", "presentation", "objects", "speech")

	def setUp(self) -> None:
		self._saved = {s: dict(conf[s]) for s in self.SECTIONS}
		conf["browseMode"]["useScreenLayout"] = False
		conf["browseMode"]["maxLineLength"] = 200

	def tearDown(self) -> None:
		for s, values in self._saved.items():
			for k, v in values.items():
				conf[s][k] = v


# ====================================================================== F23
class RemainingCharactersTests(_ConfMixin):
	def test_remaining_text(self) -> None:
		self.assertEqual(text_limits.remainingText(3, 10), "3 caracteres escritos de 10, quedan 7")
		self.assertEqual(text_limits.remainingText(9, 10), "9 caracteres escritos de 10, queda 1")
		self.assertEqual(text_limits.remainingText(10, 10), "10 caracteres escritos de 10, límite alcanzado")
		self.assertEqual(text_limits.remainingText(1, None), "1 carácter escrito, sin límite de longitud")

	def test_warning_threshold_mode(self) -> None:
		w = text_limits.warningFor
		self.assertIsNone(w(20, None, "threshold", 10))
		# Al cruzar el umbral se avisa una vez.
		self.assertEqual(w(10, 11, "threshold", 10), "quedan 10 caracteres")
		self.assertIsNone(w(9, 10, "threshold", 10))
		self.assertEqual(w(1, None, "threshold", 10), "queda 1 carácter")
		# Al llegar al límite, siempre.
		self.assertEqual(w(0, 1, "threshold", 10), "límite de caracteres alcanzado")
		self.assertEqual(w(0, 0, "threshold", 10), "límite de caracteres alcanzado")
		self.assertIsNone(w(0, 0, "off", 10))

	def test_warning_countdown_mode(self) -> None:
		w = text_limits.warningFor
		self.assertEqual(w(5, 6, "countdown", 10), "quedan 5")
		self.assertEqual(w(1, 2, "countdown", 10), "queda 1")
		self.assertIsNone(w(5, 5, "countdown", 10))
		self.assertIsNone(w(11, 12, "countdown", 10))

	def test_text_length_ignores_object_char_and_final_newline(self) -> None:
		class Info:
			def __init__(self, t):
				self.text = t

		class Field:
			value = ""

			def __init__(self, t):
				self._t = t

			def _getCaretInfo(self):
				return None

			def makeTextInfo(self, pos):
				return Info(self._t)

		self.assertEqual(text_limits.textLength(Field("\ufffc")), 0)
		self.assertEqual(text_limits.textLength(Field("hola\r\n")), 4)

		class NoCaret:
			value = "abc"

		self.assertEqual(text_limits.textLength(NoCaret()), 3)

	def test_report_without_field(self) -> None:
		with mock.patch.object(speech, "speakMessage") as sm:
			text_limits.reportRemaining(None)
		sm.assert_called_once_with("No hay ningún campo de edición con el foco")

	def test_report_field(self) -> None:
		class Field:
			role = Role.EDITABLETEXT
			states: set = set()
			value = "hola"
			maxLength = 5

		with mock.patch.object(speech, "speakMessage") as sm:
			text_limits.reportRemaining(Field())
		sm.assert_called_once_with("4 caracteres escritos de 5, queda 1")

	def test_check_uses_options(self) -> None:
		class Field:
			role = Role.EDITABLETEXT
			states: set = set()
			value = "abcdefgh"
			maxLength = 10
			runtimeId = (1, 2, 3)

		conf["objects"]["maxLengthWarning"] = "threshold"
		conf["objects"]["maxLengthWarningThreshold"] = 2
		text_limits.forget(Field())
		with mock.patch.object(speech, "speakMessage") as sm:
			text_limits._check(Field())
		sm.assert_called_once_with("quedan 2 caracteres")
		conf["objects"]["maxLengthWarning"] = "off"
		with mock.patch.object(speech, "speakMessage") as sm:
			text_limits._check(Field())
		sm.assert_not_called()

	def test_command_registered(self) -> None:
		from tiresias.global_commands_extra import ExtraCommands

		func = ExtraCommands.script_reportRemainingCharacters
		self.assertIn("kb:tiresias+control+l", [g.lower() for g in func.gestures])


# ====================================================================== F24
class GraphicFileNameTests(_ConfMixin):
	def test_file_name_from_url(self) -> None:
		f = ia2_bridge.fileNameFromURL
		self.assertEqual(f("https://example.com/img/foto_de_la_playa.png?x=1#a"), "foto de la playa")
		self.assertEqual(f("file:///C:/Users/x/mi%20gato.JPEG"), "mi gato")
		self.assertEqual(f("data:image/png;base64,AAAA"), "")
		self.assertEqual(f("blob:https://x/123"), "")
		self.assertEqual(f(""), "")
		self.assertEqual(f("https://example.com/"), "")

	def test_buffer_text_with_file_name(self) -> None:
		conf["browseMode"]["reportUnlabeledGraphics"] = True
		conf["browseMode"]["reportGraphicFileNames"] = True
		doc = FakeEl(uc.CT_DOCUMENT, "doc", [group(text("Antes"), FakeEl(uc.CT_IMAGE, ""))])
		with mock.patch.object(html_details, "graphicFileName", return_value="foto de la playa"):
			buf = build(doc)
		self.assertIn("gráfico sin descripción foto de la playa", buf.text)
		conf["browseMode"]["reportGraphicFileNames"] = False
		with mock.patch.object(html_details, "graphicFileName", return_value="foto de la playa"):
			buf = build(doc)
		self.assertIn("gráfico sin descripción", buf.text)
		self.assertNotIn("playa", buf.text)
		conf["browseMode"]["reportUnlabeledGraphics"] = False
		buf = build(doc)
		self.assertNotIn("gráfico", buf.text)

	def test_linked_graphic_gets_file_name(self) -> None:
		conf["browseMode"]["reportUnlabeledGraphics"] = False
		conf["browseMode"]["reportGraphicFileNames"] = True
		doc = FakeEl(uc.CT_DOCUMENT, "doc", [FakeEl(uc.CT_HYPERLINK, "", [FakeEl(uc.CT_IMAGE, "")])])
		with mock.patch.object(html_details, "graphicFileName", return_value="logo"):
			buf = build(doc)
		self.assertIn("gráfico logo", buf.text)

	def test_object_speech_unlabeled(self) -> None:
		conf["browseMode"]["reportUnlabeledGraphics"] = True
		conf["browseMode"]["reportGraphicFileNames"] = True

		class Img:
			name = "Para obtener las descripciones de las imágenes, abre el menú contextual."
			UIALocalizedControlType = "Gráfico sin descripción"
			graphicFileName = "foto"

		name, unlabeled = presentation._graphicName(Img(), Img.name)
		self.assertEqual((name, unlabeled), ("foto", True))

		class Labeled:
			name = "Un perro"
			UIALocalizedControlType = "gráfico"

		self.assertEqual(presentation._graphicName(Labeled(), "Un perro"), ("Un perro", False))

	def test_path_resolver_checks_counts(self) -> None:
		class Acc:
			def __init__(self, n):
				self.accChildCount = n

		res = ia2_bridge.PathResolver()
		res._docs[1] = Acc(3)
		with mock.patch.object(ia2_bridge, "childAt", side_effect=lambda a, i: Acc(2)):
			self.assertIsNotNone(res.resolve(1, [0, 1], [3, 2]))
			# Si el número de hijos no coincide en un nivel, no se arriesga.
			res._cache.clear()
			self.assertIsNone(res.resolve(1, [0, 1], [3, 5]))

	def test_raw_path(self) -> None:
		leaf = FakeEl(uc.CT_IMAGE, "")
		mid = group(text("a"), leaf)
		root = FakeEl(uc.CT_DOCUMENT, "doc", [text("x"), mid])
		res = ia2_bridge.PathResolver()
		with mock.patch.object(uc, "makeCacheRequest", return_value=None), mock.patch.object(uc, "trueCondition", None, create=True):
			path = res.rawPath(root, leaf.rid)
		self.assertEqual(path, ([1, 1], [2, 2]))


# ====================================================================== F25
class ObjectLanguageTests(_ConfMixin):
	def test_with_name_language(self) -> None:
		seq = presentation.withNameLanguage("Bonjour botón", "Bonjour", "fr")
		self.assertIsInstance(seq[0], LangChangeCommand)
		self.assertEqual(seq[0].lang, "fr")
		self.assertEqual(seq[1], "Bonjour")
		self.assertEqual(seq[3], "botón")
		self.assertEqual(presentation.withNameLanguage("Hola botón", "Hola", None), ["Hola botón"])
		self.assertEqual(presentation.withNameLanguage("x", "no está", "fr"), ["x"])

	def test_object_language_options(self) -> None:
		class Obj:
			language = "fr_FR"

		conf["speech"]["autoLanguageSwitching"] = True
		conf["presentation"]["reportObjectLanguage"] = True
		with mock.patch.object(presentation, "normalizeLanguage", side_effect=lambda l: l[:2]):
			self.assertEqual(presentation.objectLanguage(Obj()), "fr")
			conf["presentation"]["reportObjectLanguage"] = False
			self.assertIsNone(presentation.objectLanguage(Obj()))
			conf["presentation"]["reportObjectLanguage"] = True
			conf["speech"]["autoLanguageSwitching"] = False
			self.assertIsNone(presentation.objectLanguage(Obj()))

	def test_lcid(self) -> None:
		self.assertIsNone(ia2_bridge.languageFromLcid(0))
		self.assertIsNone(ia2_bridge.languageFromLcid(127))
		self.assertIsNone(ia2_bridge.languageFromLcid(None))
		self.assertTrue((ia2_bridge.languageFromLcid(3082) or "").startswith("es"))

	def test_get_locale_errors(self) -> None:
		self.assertIsNone(ia2_bridge.getLocale(None))

		class Broken:
			def _IAccessible2__com__get_locale(self, p):
				raise OSError("no")

		self.assertIsNone(ia2_bridge.getLocale(Broken()))

	def test_speak_object_uses_language(self) -> None:
		conf["speech"]["autoLanguageSwitching"] = True
		conf["presentation"]["reportObjectLanguage"] = True

		class Btn:
			name = "Hello"
			role = Role.BUTTON
			states: set = set()
			value = ""
			description = ""
			roleText = None
			keyboardShortcut = ""
			positionInfo: dict = {}
			language = "en_US"

		with mock.patch.object(presentation, "normalizeLanguage", return_value="en"), mock.patch.object(speech, "speak") as sp, mock.patch("tiresias.braille.handler"):
			presentation.speakObject(Btn(), presentation.Reason.QUERY)
		seq = sp.call_args[0][0]
		langs = [c.lang for c in seq if isinstance(c, LangChangeCommand)]
		self.assertEqual(langs[:2], ["en", None])
		self.assertIn("Hello", seq)


# ====================================================================== F26
def _node(role: Role, name: str = "", parent: Node | None = None, **kw) -> Node:
	n = Node()
	n.role = role
	n.name = name
	n.parent = parent
	for k, v in kw.items():
		setattr(n, k, v)
	if parent is not None:
		parent.children.append(n)
	return n


class QuoteTests(_ConfMixin):
	def test_quote_kinds(self) -> None:
		p = _node(Role.PARAGRAPH)
		_node(Role.STATICTEXT, "Dijo", p)
		o = _node(Role.STATICTEXT, "“", p)
		_node(Role.STATICTEXT, "hola", p)
		o2 = _node(Role.STATICTEXT, "‘", p)
		c2 = _node(Role.STATICTEXT, "’", p)
		c = _node(Role.STATICTEXT, "”", p)
		self.assertEqual(html_details.quoteKind(o), "open")
		self.assertEqual(html_details.quoteKind(o2), "open")
		self.assertEqual(html_details.quoteKind(c2), "close")
		self.assertEqual(html_details.quoteKind(c), "close")
		conf["documentFormatting"]["reportQuotes"] = True
		self.assertEqual(html_details.quoteSpeech(o, "“"), "cita")
		self.assertEqual(html_details.quoteSpeech(c, "”"), "fin de cita")
		conf["documentFormatting"]["reportQuotes"] = False
		self.assertEqual(html_details.quoteSpeech(o, "“"), "“")

	def test_german_and_spanish_quotes(self) -> None:
		p = _node(Role.PARAGRAPH)
		a = _node(Role.STATICTEXT, "„", p)
		_node(Role.STATICTEXT, "Hallo", p)
		b = _node(Role.STATICTEXT, "“", p)
		self.assertEqual((html_details.quoteKind(a), html_details.quoteKind(b)), ("open", "close"))
		p2 = _node(Role.PARAGRAPH)
		a2 = _node(Role.STATICTEXT, "«", p2)
		b2 = _node(Role.STATICTEXT, "»", p2)
		self.assertEqual((html_details.quoteKind(a2), html_details.quoteKind(b2)), ("open", "close"))
		# Un texto normal no es una comilla.
		self.assertIsNone(html_details.quoteKind(_node(Role.STATICTEXT, "hola", p2)))


class DescriptionTests(_ConfMixin):
	def test_group_description_in_buffer(self) -> None:
		conf["presentation"]["reportGroupDescriptions"] = True
		doc = FakeEl(uc.CT_DOCUMENT, "doc", [group(text("Calle"), name="Envío", P_FULLDESCRIPTION="Dirección completa")])
		buf = build(doc)
		g = next(n for n in buf.nodes if n.name == "Envío")
		self.assertEqual(html_details.containerDescription(buf, g), "Dirección completa")
		# Si la descripción está dentro del grupo, ya se va a leer: no se repite.
		doc2 = FakeEl(uc.CT_DOCUMENT, "doc", [group(text("Dirección completa"), text("Calle"), name="Envío", P_FULLDESCRIPTION="Dirección completa")])
		buf2 = build(doc2)
		g2 = next(n for n in buf2.nodes if n.name == "Envío")
		self.assertEqual(html_details.containerDescription(buf2, g2), "")
		conf["presentation"]["reportGroupDescriptions"] = False
		self.assertEqual(html_details.containerDescription(buf, g), "")

	def test_focus_entered_description(self) -> None:
		conf["presentation"]["reportGroupDescriptions"] = True

		class Grp:
			name = "Envío"
			role = Role.GROUPING
			states: set = set()
			description = "Rellena la dirección"
			roleText = None

		parts = presentation.getObjectSpeech(Grp(), presentation.Reason.FOCUSENTERED)
		self.assertEqual(parts[-1], "Rellena la dirección")
		conf["presentation"]["reportGroupDescriptions"] = False
		self.assertNotIn("Rellena la dirección", presentation.getObjectSpeech(Grp(), presentation.Reason.FOCUSENTERED))


class SoftHyphenTests(_ConfMixin):
	def test_buffer_removes_soft_hyphens(self) -> None:
		doc = FakeEl(uc.CT_DOCUMENT, "doc", [group(text("super\xadcali\xadfragi"))])
		buf = build(doc)
		self.assertIn("supercalifragi", buf.text)
		self.assertNotIn("\xad", buf.text)

	def test_speech_removes_soft_hyphens(self) -> None:
		self.assertNotIn("\xad", speech.processText("pro\xadnun\xadcia\xadción"))
		self.assertIn("pronunciación", speech.processText("pro\xadnun\xadcia\xadción"))

	def test_braille_hides_soft_hyphens(self) -> None:
		from tiresias.braille import tables

		t = tables.getTable("es-comp8")
		with_ = tables.translate(t, "ab\xadcd", cursor=2)
		plain = tables.translate(t, "abcd")
		self.assertEqual(with_.cells, plain.cells)
		# El cursor sobre el guion blando cae en la celda siguiente.
		self.assertEqual(with_.cursorPos, 2)


class AbbrTests(_ConfMixin):
	def test_header_abbreviation(self) -> None:
		conf["documentFormatting"]["useHeaderAbbreviations"] = True
		h = _node(Role.TABLECOLUMNHEADER, "Población total")
		h.aria["abbr"] = "Pob."

		class Doc:
			buffer = None

		self.assertEqual(html_details.headerAbbreviation(Doc(), h), "Pob.")
		conf["documentFormatting"]["useHeaderAbbreviations"] = False
		self.assertEqual(html_details.headerAbbreviation(Doc(), h), "")
		cell = _node(Role.TABLECELL, "1000")
		conf["documentFormatting"]["useHeaderAbbreviations"] = True
		self.assertEqual(html_details.headerAbbreviation(Doc(), cell), "")


class BrailleLabelTests(_ConfMixin):
	def test_browse_line(self) -> None:
		doc = FakeEl(uc.CT_DOCUMENT, "doc", [FakeEl(uc.CT_BUTTON, "Aceptar", P_ARIAPROPERTIES="braillelabel=ok;brailleroledescription=btn")])
		buf = build(doc)

		class Doc:
			buffer = buf
			caret = 0

		node = next(n for n in buf.nodes if n.role == Role.BUTTON)
		s, e = buf.lineBounds(node.end - 1)
		Doc.caret = node.start
		text, cursor = html_details.brailleLabelLine(Doc, s, e)
		self.assertIn("ok btn", text)
		self.assertNotIn("Aceptar", text)
		self.assertIsNone(html_details.brailleLabelLine(type("D", (), {"buffer": build(FakeEl(uc.CT_DOCUMENT, "d", [text_("hola")])), "caret": 0}), 0, 4))

	def test_object_properties(self) -> None:
		from tiresias.braille import presenter

		class Btn:
			name = "Aceptar"
			role = Role.BUTTON
			states: set = set()
			value = ""
			description = ""
			roleText = None
			keyboardShortcut = ""
			positionInfo: dict = {}
			brailleLabel = "ok"
			brailleRoleText = "btn"

		props = dict(presenter.objectProperties(Btn()))
		self.assertEqual(props.get("name"), "ok")
		self.assertEqual(props.get("role"), "btn")


def text_(t: str) -> FakeEl:
	return text(t)


if __name__ == "__main__":
	unittest.main()
