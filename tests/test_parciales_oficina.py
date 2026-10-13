"""Pruebas de las peticiones de ofimática completadas (F5, F35, F36, F37, F38).

Usan dobles del modelo de objetos de Office y de la página de Google: no
necesitan Office ni un navegador.
Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_oficina_test_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()

from tiresias.config import conf  # noqa: E402


# ====================================================================== Excel (F5)
class _Cell:
	def __init__(self, sheet, r, c):
		self.sheet, self.Row, self.Column = sheet, r, c

	@property
	def Text(self):
		v = self.sheet.data.get((self.Row, self.Column))
		return "" if v is None else str(v)


class _Range:
	def __init__(self, sheet, a, b):
		self.sheet, self.a, self.b = sheet, a, b

	@property
	def Value2(self):
		rows = []
		for r in range(self.a.Row, self.b.Row + 1):
			rows.append(tuple(self.sheet.data.get((r, c)) for c in range(self.a.Column, self.b.Column + 1)))
		return tuple(rows)


class _Used:
	Row = 1
	Column = 1

	class Rows:
		Count = 3

	class Columns:
		Count = 4


class _Sheet:
	def __init__(self, data):
		self.data = data
		self.UsedRange = _Used()

	def Cells(self, r, c):
		return _Cell(self, r, c)

	def Range(self, a, b):
		return _Range(self, a, b)


class _XlApp:
	def __init__(self, data, active):
		self.ActiveSheet = _Sheet(data)
		self.ActiveCell = _Cell(self.ActiveSheet, *active)


class ExcelLineTests(unittest.TestCase):
	def setUp(self):
		from tiresias.appmodules import _excel

		self.x = _excel
		data = {(1, 1): "Nombre", (1, 2): "Edad", (1, 4): "Ciudad", (2, 1): "Ana", (2, 2): 30.0, (2, 4): "Sevilla", (3, 1): "Luis", (3, 2): 41.0}
		self.app = _XlApp(data, (2, 2))
		self.patch = mock.patch.object(_excel, "_app", lambda hwnd: self.app)
		self.patch.start()

	def tearDown(self):
		self.patch.stop()

	def test_row_from_start_with_titles(self):
		d = self.x.om_lineCells(1, "row", True, True, 1, 1)
		self.assertEqual(d["items"], [("A2", "Nombre", "Ana"), ("B2", "Edad", "30.0"), ("D2", "Ciudad", "Sevilla")])
		self.assertEqual(self.x.lineSpeech(d, True, True)[0], "Nombre, Ana")
		self.assertEqual(self.x.lineSpeech(d, False, True)[0], "Ana, A2")
		self.assertEqual(self.x.lineSpeech(d, False, False)[2], "Sevilla")

	def test_row_from_current_with_blanks(self):
		d = self.x.om_lineCells(1, "row", False, False, 1, 1)
		self.assertEqual([i[0] for i in d["items"]], ["B2", "C2", "D2"])
		self.assertIn("en blanco", self.x.lineSpeech(d, True, False)[1])

	def test_column_with_row_titles(self):
		d = self.x.om_lineCells(1, "col", True, True, 1, 1)
		self.assertEqual(d["items"][1], ("B2", "Ana", "30.0"))
		text = self.x.lineViewerText(d)
		self.assertTrue(text.startswith("Columna B"))
		self.assertIn("B3  Luis: 41.0", text)

	def test_empty_line(self):
		self.assertEqual(self.x.lineSpeech({"kind": "row", "row": 9, "items": []}, True, True), ["fila 9 vacía"])

	def test_cell_viewer_text(self):
		d = {"address": "A5", "sheet": "Hoja1", "content": "uno\ndos", "shown": "uno\ndos", "formula": "", "note": "ojo"}
		text = self.x.cellViewerText(d, "Ana", "Nombre")
		self.assertIn("Título de columna: Nombre", text)
		self.assertIn("uno\ndos", text)
		self.assertIn("Nota: ojo", text)
		d2 = {"address": "B4", "content": "71", "shown": "71,00 €", "formula": "=B2+B3"}
		text2 = self.x.cellViewerText(d2)
		self.assertIn("Fórmula: =B2+B3", text2)
		self.assertIn("Valor mostrado: 71,00 €", text2)

	def test_scripts_and_options(self):
		from tiresias.appmodules import excel

		gestures = dict(excel.ExcelCell.iterClassGestures())
		self.assertEqual(gestures["kb:tiresias+control+alt+leftarrow"], "readRow")
		self.assertEqual(gestures["kb:tiresias+control+alt+uparrow"], "readColumn")
		self.assertEqual(gestures["kb:tiresias+shift+v"], "cellViewer")
		self.assertEqual(conf["officeExcel"]["readLineFrom"], "start")
		self.assertTrue(conf["officeExcel"]["readLineSkipBlank"])
		self.assertTrue(conf["officeExcel"]["readLineHeaders"])


# ====================================================================== Word (F35)
class _LF:
	def __init__(self, kind=0, marker="", level=1, lst=None):
		self.ListType, self.ListString, self.ListLevelNumber, self.List = kind, marker, level, lst


class _WRange:
	def __init__(self, start, end, text="", lf=None, doc=None):
		self.Start, self.End, self.Text = start, end, text
		self.ListFormat = lf or _LF()
		self._doc = doc
		self.selected = False

	def Select(self):
		self._doc.selection = self.Start

	@property
	def ListParagraphs(self):
		doc = self._doc

		class C:
			Count = sum(1 for p in doc.paras if p.Range.ListFormat.ListType and p.Range.Start < self.End and p.Range.End > self.Start)

		return C()


class _Para:
	def __init__(self, doc, i, start, end, text, lf):
		self.doc, self.i = doc, i
		self.Range = _WRange(start, end, text, lf, doc)

	def Next(self):
		return self.doc.paras[self.i + 1] if self.i + 1 < len(self.doc.paras) else None

	def Previous(self):
		return self.doc.paras[self.i - 1] if self.i > 0 else None


class _List:
	def __init__(self, doc, items):
		self.doc, self.items = doc, items

	@property
	def Range(self):
		first, last = self.items[0], self.items[-1]
		r = _WRange(first.Range.Start, last.Range.End, doc=self.doc)

		class Ps:
			First = first
			Last = last

		r.Paragraphs = Ps()
		return r

	@property
	def ListParagraphs(self):
		class C:
			Count = len(self.items)

		return C()


class _Doc:
	"""Documento: «Intro», lista de tres viñetas, «Medio», lista numerada de dos."""

	def __init__(self):
		self.paras = []
		specs = [("Intro", None), ("uno", "a"), ("dos", "a"), ("tres", "a"), ("Medio", None), ("primero", "b"), ("segundo", "b")]
		pos = 0
		for i, (text, lst) in enumerate(specs):
			self.paras.append(_Para(self, i, pos, pos + len(text) + 1, text + "\r", None))
			pos += len(text) + 1
		la = _List(self, [p for p, s in zip(self.paras, specs) if s[1] == "a"])
		lb = _List(self, [p for p, s in zip(self.paras, specs) if s[1] == "b"])
		n = 0
		for p, (text, lst) in zip(self.paras, specs):
			if lst == "a":
				p.Range.ListFormat = _LF(2, "", 1, la)
			elif lst == "b":
				n += 1
				p.Range.ListFormat = _LF(3, f"{n}.", 1, lb)
		self.selection = 0

	def Range(self, a, b):
		return _WRange(a, b, doc=self)


class _Selection:
	def __init__(self, doc):
		self.doc = doc
		self.Document = doc

	def Paragraphs(self, i):
		return next(p for p in self.doc.paras if p.Range.Start <= self.doc.selection < p.Range.End)


class _Window:
	def __init__(self, doc):
		class App:
			pass

		self.Application = App()
		self.Application.Selection = _Selection(doc)

	def ScrollIntoView(self, rng, start):
		pass


class WordListTests(unittest.TestCase):
	def setUp(self):
		from tiresias.appmodules import _word

		self.w = _word
		self.doc = _Doc()
		self.patch = mock.patch.object(_word, "_window", lambda hwnd: _Window(self.doc))
		self.patch.start()

	def tearDown(self):
		self.patch.stop()

	def test_transition_enter_exit(self):
		parts, start = self.w.listTransition(None, {"listType": 2, "listString": "", "listLevel": 1, "listStart": 6, "listCount": 3})
		self.assertEqual(parts, ["lista con 3 elementos", "elemento de lista viñeta"])
		parts2, start2 = self.w.listTransition(start, {"listType": 2, "listString": "", "listLevel": 2, "listStart": 6, "listCount": 3})
		self.assertEqual(parts2, ["elemento de lista viñeta nivel 2"])
		parts3, start3 = self.w.listTransition(start2, {"listType": 0})
		self.assertEqual((parts3, start3), (["fuera de lista"], None))
		self.assertEqual(self.w.listTransition(None, {"listType": 0}), ([], None))

	def test_list_info(self):
		self.doc.selection = 7  # «dos»
		d = self.w.om_listInfo(1)
		self.assertEqual((d["listType"], d["listStart"], d["listCount"]), (2, 6, 3))

	def test_next_previous_first_last(self):
		self.doc.selection = 0  # «Intro»: fuera de lista, va a la primera lista
		d = self.w.om_listItemMove(1, "next")
		self.assertTrue(d["moved"])
		self.assertEqual((d["text"], d["index"], d["listCount"]), ("uno", 1, 3))
		d = self.w.om_listItemMove(1, "next")
		self.assertEqual((d["text"], d["index"]), ("dos", 2))
		self.assertEqual(self.w.listItemText(d), "elemento de lista viñeta, 2 de 3, dos")
		d = self.w.om_listItemMove(1, "last")
		self.assertEqual(d["text"], "tres")
		d = self.w.om_listItemMove(1, "next")
		self.assertEqual((d["moved"], d["reason"]), (False, "end"))
		d = self.w.om_listItemMove(1, "first")
		self.assertEqual(d["text"], "uno")
		d = self.w.om_listItemMove(1, "previous")
		self.assertEqual(d["reason"], "start")

	def test_outside_list(self):
		self.doc.selection = 20  # «Medio»
		self.assertEqual(self.w.om_listItemMove(1, "first")["reason"], "notInList")
		d = self.w.om_listItemMove(1, "next")
		self.assertEqual((d["text"], d["listString"]), ("primero", "1."))
		self.doc.selection = 20
		d = self.w.om_listItemMove(1, "previous")
		self.assertEqual(d["text"], "tres")

	def test_gestures(self):
		from tiresias.appmodules import winword

		g = dict(winword.WordDocument.iterClassGestures())
		self.assertEqual(g["kb:tiresias+control+shift+alt+downarrow"], "nextListItem")
		self.assertEqual(g["kb:tiresias+control+shift+alt+uparrow"], "previousListItem")
		self.assertEqual(g["kb:tiresias+control+alt+home"], "firstListItem")
		self.assertEqual(g["kb:tiresias+control+alt+end"], "lastListItem")
		self.assertTrue(callable(winword.WordDocument.script_caret_moveByParagraph))


# ====================================================================== PowerPoint (F37)
_PRES = (
	'<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
	'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
	'<p:sldIdLst><p:sldId id="256" r:id="rId2"/><p:sldId id="257" r:id="rId3"/></p:sldIdLst></p:presentation>'
)
_RELS = (
	'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
	'<Relationship Id="rId2" Type="slide" Target="slides/slide1.xml"/>'
	'<Relationship Id="rId3" Type="slide" Target="slides/slide2.xml"/></Relationships>'
)
_RUN = '<m:r><a:rPr lang="es-ES" i="1"/><m:t>{t}</m:t></m:r>'
_SLIDE1 = (
	'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
	'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
	'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
	'xmlns:a14="http://schemas.microsoft.com/office/drawing/2010/main" '
	'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><p:cSld><p:spTree>'
	'<mc:AlternateContent><mc:Choice Requires="a14"><p:sp><p:nvSpPr><p:cNvPr id="4" name="Ecuación"/></p:nvSpPr>'
	'<p:txBody><a:p><a:r><a:t>Resuelve</a:t></a:r><a14:m><m:oMathPara><m:oMath>'
	'<m:sSup><m:e>' + _RUN.format(t="x") + '</m:e><m:sup>' + _RUN.format(t="2") + '</m:sup></m:sSup>' + _RUN.format(t="=4") + '</m:oMath></m:oMathPara></a14:m></a:p>'
	'<a:p><a:r><a:t>en los reales</a:t></a:r></a:p></p:txBody></p:sp></mc:Choice>'
	'<mc:Fallback><p:sp><p:nvSpPr><p:cNvPr id="4" name="Ecuación"/></p:nvSpPr><p:txBody><a:p><a:r><a:t>imagen</a:t></a:r></a:p></p:txBody></p:sp></mc:Fallback>'
	'</mc:AlternateContent>'
	'<p:sp><p:nvSpPr><p:cNvPr id="5" name="Texto"/></p:nvSpPr><p:txBody><a:p><a:r><a:t>Hola</a:t></a:r></a:p></p:txBody></p:sp>'
	'</p:spTree></p:cSld></p:sld>'
)
_SLIDE2 = '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree/></p:cSld></p:sld>'


def _makePptx(path: str) -> None:
	with zipfile.ZipFile(path, "w") as z:
		z.writestr("ppt/presentation.xml", _PRES)
		z.writestr("ppt/_rels/presentation.xml.rels", _RELS)
		z.writestr("ppt/slides/slide1.xml", _SLIDE1)
		z.writestr("ppt/slides/slide2.xml", _SLIDE2)


class PowerPointEquationTests(unittest.TestCase):
	def setUp(self):
		from tiresias.appmodules import _ppt

		self.p = _ppt
		self.dir = tempfile.mkdtemp(prefix="tiresias_pptx_")
		self.path = os.path.join(self.dir, "mates.pptx")
		_makePptx(self.path)
		_ppt._eqCache.clear()

	def tearDown(self):
		shutil.rmtree(self.dir, ignore_errors=True)

	def test_parse_file(self):
		eq = self.p.pptxEquations(self.path)
		self.assertEqual(list(eq), [256])
		shape = eq[256][0]
		self.assertEqual((shape["id"], shape["name"]), (4, "Ecuación"))
		kinds = [k for k, _v in shape["segments"]]
		self.assertEqual(kinds, ["text", "math", "text"])
		self.assertIn("<msup>", shape["segments"][1][1])
		self.assertNotIn("imagen", str(shape["segments"]))

	def test_slide_text_with_equations(self):
		eq = {sh["id"]: sh["segments"] for sh in self.p.pptxEquations(self.path)[256]}
		d = {"index": 1, "count": 2, "title": "", "shapes": [{"id": 4, "name": "Ecuación", "text": " 𝑥 2 =4", "math": True}, {"id": 5, "name": "Texto", "text": "Hola"}], "texts": [" 𝑥 2 =4", "Hola"]}
		self.assertEqual(self.p.slideText(d, reportNotes=False), "Diapositiva 1 de 2, ecuación, Hola")
		text = self.p.slideText(d, reportNotes=False, equations=eq)
		self.assertIn("Resuelve, ecuación: x al cuadrado igual a 4, en los reales", text)
		self.assertIn("Hola", text)
		self.assertIn("ecuación, en los reales", self.p.slideText(d, equations=eq, speakMath=False))
		self.assertIn("1 ecuación", self.p.slideText(d, full=False, equations=eq))

	def test_saved_presentation_uses_file_and_cache(self):
		class Pres:
			FullName = self.path
			Saved = -1

			def SaveCopyAs(self, *a):  # no debe usarse
				raise AssertionError

		shapes = self.p.presentationEquations(Pres(), 256)
		self.assertEqual(shapes[0]["id"], 4)
		with mock.patch.object(self.p, "pptxEquations", side_effect=AssertionError):
			self.assertEqual(self.p.presentationEquations(Pres(), 256)[0]["id"], 4)
		self.assertEqual(self.p.presentationEquations(Pres(), 257), [])

	def test_unsaved_presentation_uses_copy(self):
		src = self.path

		class Pres:
			FullName = "Presentación1"
			Saved = 0
			copies = 0

			def SaveCopyAs(self, path, fmt):
				Pres.copies += 1
				shutil.copy(src, path)

		shapes = self.p.presentationEquations(Pres(), 256, ((4, "x"),))
		self.assertEqual(shapes[0]["name"], "Ecuación")
		self.p.presentationEquations(Pres(), 256, ((4, "x"),))
		self.assertEqual(Pres.copies, 1)
		self.p.presentationEquations(Pres(), 256, ((4, "y"),))
		self.assertEqual(Pres.copies, 2)

	def test_math_suspect(self):
		shape = mock.Mock()
		shape.TextFrame.TextRange.Font.Name = "Aptos"
		self.assertTrue(self.p._mathSuspect(shape, "𝑥+1"))
		self.assertFalse(self.p._mathSuspect(shape, "Hola"))
		shape.TextFrame.TextRange.Font.Name = "Cambria Math"
		self.assertTrue(self.p._mathSuspect(shape, "2+2=4"))

	def test_math_command_uses_app_hook(self):
		from tiresias.mathpres import plugin

		called = []

		class App:
			def interactWithMath(self, focus):
				called.append(focus)
				return True

		class Focus:
			appModule = App()

		focus = Focus()
		with mock.patch.object(plugin.api, "getFocusObject", return_value=focus), mock.patch.object(plugin, "findMathAtCursor", side_effect=AssertionError):
			plugin.MathGlobalPlugin.script_interactWithMath(plugin.MathGlobalPlugin.__new__(plugin.MathGlobalPlugin), None)
		self.assertEqual(called, [focus])
		self.assertTrue(conf["officePowerPoint"]["readEquations"])


# ====================================================================== Outlook (F38)
class _Att:
	def __init__(self, name, size, hidden=False, kind=1):
		self.FileName, self.Size, self.Type = name, size, kind
		self.DisplayName = name
		self.saved = None
		hid = hidden

		class PA:
			def GetProperty(self, prop):
				return hid

		self.PropertyAccessor = PA()

	def SaveAsFile(self, path):
		self.saved = path


class _Atts:
	def __init__(self, items):
		self.items = items
		self.Count = len(items)

	def Item(self, i):
		return self.items[i - 1]


class OutlookAttachmentTests(unittest.TestCase):
	def setUp(self):
		from tiresias.appmodules import outlook

		self.o = outlook
		self.atts = [_Att("informe.pdf", 250 * 1024), _Att("logo.png", 2000, hidden=True), _Att("datos.xlsx", 3 * 1024 * 1024)]
		mail = mock.Mock()
		mail.Subject = "Cuentas"
		mail.EntryID = "ABC"
		mail.Attachments = _Atts(self.atts)
		win = mock.Mock()
		win.Class = 35
		win.CurrentItem = mail
		app = mock.Mock()
		app.ActiveWindow.return_value = win
		app.Session.GetItemFromID.return_value = mail
		self.patch = mock.patch.object(outlook, "_outlook", return_value=app)
		self.patch.start()

	def tearDown(self):
		self.patch.stop()

	def test_list(self):
		d = self.o.om_attachments()
		self.assertEqual(d["subject"], "Cuentas")
		self.assertEqual(d["where"], "inspector")
		self.assertEqual([a["name"] for a in d["items"]], ["informe.pdf", "datos.xlsx"])
		self.assertEqual(self.o.attachmentLabel(d["items"][0]), "informe.pdf, 250 KB")
		self.assertEqual(self.o.attachmentLabel(d["items"][1]), "datos.xlsx, 3,0 MB")

	def test_save(self):
		path = os.path.join(tempfile.gettempdir(), "x.xlsx")
		self.assertEqual(self.o.om_saveAttachment("ABC", 3, "datos.xlsx", path), path)
		self.assertEqual(self.atts[2].saved, path)
		# Si el índice ya no corresponde, se busca por nombre.
		self.o.om_saveAttachment("ABC", 1, "datos.xlsx", path + "2")
		self.assertEqual(self.atts[2].saved, path + "2")
		with self.assertRaises(Exception):
			self.o.om_saveAttachment("ABC", 1, "no.txt", path)

	def test_helpers(self):
		self.assertTrue(self.o.isBlocked("virus.EXE"))
		self.assertFalse(self.o.isBlocked("carta.docx"))
		self.assertEqual(self.o.safeFileName('a:b/c?.txt'), "a_b_c_.txt")
		self.assertEqual(self.o.sizeText(500), "500 bytes")
		gestures = dict(self.o.AppModule.iterClassGestures())
		self.assertEqual(gestures["kb:tiresias+control+shift+a"], "attachmentsList")


# ====================================================================== Google (F36)
class GoogleTests(unittest.TestCase):
	def setUp(self):
		from tiresias.appmodules import _gsuite

		self.g = _gsuite
		_gsuite.reset()
		_gsuite._states.clear()
		try:
			os.remove(_gsuite._file())
		except FileNotFoundError:
			pass

	def test_detection(self):
		g = self.g
		self.assertEqual(g.googleAppFromUrl("https://docs.google.com/spreadsheets/d/abc/edit#gid=5"), "sheets")
		self.assertEqual(g.googleAppFromUrl("https://docs.google.com/document/d/x/edit"), "docs")
		self.assertIsNone(g.googleAppFromUrl("https://example.com/spreadsheets/d/x"))
		self.assertEqual(g.googleAppFromTitle("Notas - Hojas de cálculo de Google - Google Chrome"), "sheets")
		self.assertEqual(g.googleAppFromTitle("Informe - Google Docs - Personal: Microsoft Edge"), "docs")
		self.assertEqual(g.sheetKey("https://docs.google.com/spreadsheets/d/abc_1/edit#gid=5"), "abc_1:5")
		self.assertEqual(g.sheetKey("https://docs.google.com/spreadsheets/d/abc/edit"), "abc:0")
		self.assertEqual(g.parseCellRef("B3"), (3, 2))
		self.assertEqual(g.parseCellRef("Hoja 1!$AA$10:AB12"), (10, 27))
		self.assertIsNone(g.parseCellRef("Ventas"))

	def test_titles_learned_and_saved(self):
		g = self.g
		st = g.stateFor("doc:0")
		st.learn(1, 1, "Nombre")
		st.learn(1, 2, "Edad")
		self.assertTrue(st.setHeader("colHeaderRow", 1, 2))
		self.assertTrue(st.setHeader("rowHeaderCol", 2, 1))
		self.assertTrue(st.learn(1, 3, "Ciudad"))  # se aprende al pasar por la fila de títulos
		st.learn(2, 1, "Ana")
		self.assertEqual(st.titles(2, 2), ("Ana", "Edad"))
		self.assertEqual(st.titles(1, 1), ("", ""))
		g.putEntry(st.key, st.entry)
		g.reset()
		e = g.getEntry("doc:0")
		self.assertEqual((e["colHeaderRow"], e["rowHeaderCol"]), (1, 1))
		self.assertEqual(e["colTitles"], {"1": "Nombre", "2": "Edad", "3": "Ciudad"})
		fresh = g.SheetState("doc:0")
		self.assertEqual(fresh.titles(5, 3), ("", "Ciudad"))
		# Al moverse solo se dice el título de lo que cambia.
		fresh.learn(2, 1, "Ana")
		self.assertEqual(fresh.moveAnnouncement(2, 2), ["Ana", "Edad"])
		self.assertEqual(fresh.moveAnnouncement(2, 3), ["Ciudad"])
		self.assertEqual(fresh.moveAnnouncement(3, 3), [])
		# Otra vez la misma fila: se borran los títulos.
		self.assertFalse(fresh.setHeader("colHeaderRow", 1, 1))
		self.assertEqual(fresh.titles(5, 3), ("", ""))

	def test_overlay_and_gestures(self):
		g = self.g

		class Obj:
			UIAAutomationId = "waffle-rich-text-editor"

		classes: list = []
		g.GlobalPlugin().chooseObjectClass(Obj(), classes)
		self.assertEqual(classes, [g.SheetsCellEditor])
		gestures = dict(g.SheetsCellEditor.iterClassGestures())
		self.assertEqual(gestures["kb:downarrow"], "sheetsNavigate")
		self.assertEqual(gestures["kb:tab"], "sheetsNavigate")
		self.assertEqual(gestures["kb:tiresias+control+alt+c"], "setColumnHeaders")
		self.assertEqual(gestures["kb:tiresias+control+shift+f"], "readRowHeader")
		self.assertTrue(conf["googleApps"]["reportHeaders"])

	def test_tip_once_per_document(self):
		g = self.g
		plugin = g.GlobalPlugin()
		url = "https://docs.google.com/document/d/XYZ/edit"
		with mock.patch("tiresias.domain_profiles.documentUrl", return_value=url), mock.patch.object(g.speech, "speakMessage") as say:
			plugin.event_gainFocus(object(), lambda: None)
			plugin.event_gainFocus(object(), lambda: None)
		self.assertEqual(say.call_count, 1)
		self.assertIn("Control+Alt+Z", say.call_args[0][0])


if __name__ == "__main__":
	unittest.main()
