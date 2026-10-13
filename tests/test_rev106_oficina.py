"""Revisión 1.0.6: módulos de Office (Word, Excel, PowerPoint, Outlook), gráficos,
Google, LibreOffice y Thunderbird.

Cada orden (``script_*``) se ejecuta con el modelo de objetos simulado y con
``_office.callAsync`` síncrono: no hace falta Office.
Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev106_oficina -v``
"""

from __future__ import annotations

import ast
import inspect
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_rev106_oficina_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()

from tiresias import queue_handler, speech, winapi  # noqa: E402
from tiresias.appmodules import _chart, _excel, _office, _ppt, _word, excel, outlook, powerpnt, winword  # noqa: E402
from tiresias.config import conf  # noqa: E402


# ====================================================================== utilidades
class Harness:
	"""Parches comunes: Office síncrono, voz grabada, ventanas y diálogos simulados."""

	def __init__(self, repeat: int = 0) -> None:
		self.said: list[str] = []
		self.shown: list[tuple[str, str]] = []
		self.lists: list[tuple] = []
		self.errors: list[BaseException] = []
		self.repeat = repeat
		self._patches: list = []

	def _sync(self, func, *args, callback=None, onError=None, timeout=2.0):
		try:
			result = func(*args)
		except BaseException as e:  # noqa: BLE001
			self.errors.append(e)
			if onError is not None:
				onError(e)
			return
		if callback is not None:
			callback(result)

	def _say(self, text, *a, **k):
		if isinstance(text, (list, tuple)):
			self.said.extend(str(t) for t in text if isinstance(t, str))
		else:
			self.said.append(str(text))

	def __enter__(self) -> "Harness":
		from tiresias import gui
		from tiresias.gui import app_dialogs
		from tiresias.input import core as inputCore

		ps = [
			mock.patch.object(_office, "callAsync", self._sync),
			mock.patch.object(speech, "speakMessage", self._say),
			mock.patch.object(speech, "speakText", self._say),
			mock.patch.object(speech, "speak", self._say),
			mock.patch.object(speech, "speakSpelling", self._say),
			mock.patch.object(speech, "cancelSpeech", lambda *a, **k: None),
			mock.patch.object(gui, "showBrowseableMessage", lambda text, title="", *a, **k: self.shown.append((title, text))),
			mock.patch.object(app_dialogs, "showItemList", lambda *a, **k: self.lists.append(a)),
			mock.patch.object(inputCore, "getLastScriptRepeatCount", lambda: self.repeat),
			mock.patch.object(queue_handler, "callLater", lambda ms, f, *a, **k: f(*a, **k)),
			mock.patch.object(winapi, "setForegroundWindow", lambda h: True),
			mock.patch.object(winapi, "getAncestor", lambda h, f=2: h),
		]
		for p in ps:
			p.start()
		self._patches = ps
		return self

	def __exit__(self, *exc) -> None:
		for p in reversed(self._patches):
			p.stop()

	def text(self) -> str:
		return " | ".join(self.said)


def _gesture(main: str = "downarrow", ids: tuple = ()) -> mock.Mock:
	g = mock.Mock()
	g.mainKeyName = main
	g.identifiers = list(ids)
	return g


def _scriptNames(cls) -> list[str]:
	return [k for k, v in cls.__dict__.items() if k.startswith("script_") and callable(v)]


# ====================================================================== estructura de las órdenes
class ScriptStructureTests(unittest.TestCase):
	FILES = ("winword", "_word", "excel", "_excel", "powerpnt", "_ppt", "outlook", "_office", "_chart", "_gsuite", "_headers", "soffice", "thunderbird")

	def test_no_scripts_inside_functions(self):
		"""Ninguna orden (ni decorador ``@script``) dentro de una función."""
		import importlib

		for name in self.FILES:
			m = importlib.import_module(f"tiresias.appmodules.{name}")
			tree = ast.parse(inspect.getsource(m))
			for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
				for inner in ast.walk(fn):
					if inner is fn or not isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
						continue
					self.assertFalse(inner.name.startswith("script_"), f"{name}: {inner.name} está dentro de {fn.name}")
					self.assertFalse(inner.decorator_list, f"{name}: {inner.name} decorada dentro de {fn.name}")

	def test_focus_scripts_not_hidden_by_app_module(self):
		"""El módulo de aplicación va antes que el foco: un gesto repetido en el foco no se ejecutaría.

		Antes, ``SlideShowWindow.script_readNotes`` (Tiresias+Alt+N) nunca se ejecutaba.
		"""
		pairs = [(powerpnt.AppModule, powerpnt.SlideShowWindow), (powerpnt.AppModule, powerpnt.SlideThumbnail), (excel.AppModule, excel.ExcelCell), (winword.AppModule, winword.WordDocument), (outlook.AppModule, winword.WordDocument)]
		for app, obj in pairs:
			appG = dict(app.iterClassGestures())
			for g, s in obj.iterClassGestures():
				self.assertNotIn(g, appG, f"{obj.__name__}.{s} tapada por {app.__name__}.{appG.get(g)}")

	def test_every_gesture_has_its_script(self):
		classes = [winword.WordDocument, winword.AppModule, excel.ExcelCell, excel.AppModule, powerpnt.AppModule, powerpnt.SlideShowWindow, outlook.AppModule]
		for cls in classes:
			for g, s in cls.iterClassGestures():
				self.assertTrue(callable(getattr(cls, "script_" + s, None)), f"{cls.__name__}: {g} → {s} no existe")


# ====================================================================== hilo de Office
class OfficeWorkerTests(unittest.TestCase):
	def test_stuck_thread_ends_when_office_answers(self):
		"""El hilo que se quedó esperando a Office no queda vivo para siempre."""
		w = _office._Worker()
		release = threading.Event()
		with self.assertRaises(_office.OfficeBusy):
			w.call(release.wait, (5,), 0.05)
		old = w._thread
		self.assertEqual(w.call(lambda: 5, (), 2.0), 5)
		self.assertIsNot(w._thread, old)
		release.set()
		old.join(2)
		self.assertFalse(old.is_alive())
		w.stop()

	def test_errors_reach_the_caller(self):
		w = _office._Worker()
		with self.assertRaises(ZeroDivisionError):
			w.call(lambda: 1 / 0, (), 2.0)
		self.assertEqual(_office.safeCall(lambda: 1 / 0, default="x"), "x")
		w.stop()

	def test_helpers(self):
		self.assertEqual(_office.columnLetters(28), "AB")
		self.assertEqual(_office.cellAddress(3, 2), "B3")
		self.assertEqual(_office.formatCm(72), "2,5 cm")
		self.assertEqual(_office.colorName(-1), "")


# ====================================================================== Word
def _wordApp():
	app = winword.AppModule.__new__(winword.AppModule)
	app._instanceGestures = {}
	app._lastPage = app._lastTable = app._lastList = None
	app.chartNavigator = None
	return app


class WordScriptTests(unittest.TestCase):
	def setUp(self):
		self.doc = winword.WordDocument.__new__(winword.WordDocument)
		self.app = _wordApp()
		self.ps = [mock.patch.object(winword.WordDocument, "_hwnd", return_value=11), mock.patch.object(winword.WordDocument, "_app", return_value=self.app)]
		for p in self.ps:
			p.start()

	def tearDown(self):
		for p in self.ps:
			p.stop()

	def test_position_and_formatting(self):
		with Harness() as h, mock.patch.object(_word, "om_position", return_value={"page": 2, "pages": 5, "line": 3, "column": 7, "section": 1, "sections": 1}):
			self.doc.script_caretPos_currentDimensions(_gesture())
		self.assertEqual(h.said, ["página 2 de 5, línea 3, columna 7"])
		f = {"style": "Normal", "bold": -1, "alignment": 1, "leftIndent": 36.0}
		with Harness() as h, mock.patch.object(_word, "om_formatting", return_value=f):
			self.doc.script_reportFormatting(_gesture())
		self.assertIn("negrita", h.text())
		self.assertIn("sangría izquierda 1,3 cm", h.text())
		with Harness(repeat=1) as h, mock.patch.object(_word, "om_formatting", return_value=f):
			self.doc.script_reportFormatting(_gesture())
		self.assertEqual(h.shown[0][0], "Formato")

	def test_comments_notes_and_moves(self):
		c = {"author": "Ana", "date": "", "text": "Revisar.", "done": True, "replies": [{"author": "Luis", "text": "Hecho"}], "scope": "texto", "start": 4}
		with Harness() as h, mock.patch.object(_word, "om_commentsAtCaret", return_value=[c]):
			self.doc.script_readComment(_gesture())
		self.assertIn("Comentario de Ana, resuelto: Revisar", h.text())
		self.assertIn("Respuesta de Luis: Hecho", h.text())
		with Harness() as h, mock.patch.object(_word, "om_commentsAtCaret", return_value=[]):
			self.doc.script_readComment(_gesture())
		self.assertEqual(h.said, ["No hay comentarios aquí"])
		with Harness() as h, mock.patch.object(_word, "om_notesAtCaret", return_value=[{"kind": "Nota al pie", "index": 2, "text": "Fuente"}]):
			self.doc.script_readNote(_gesture())
		self.assertEqual(h.said, ["Nota al pie 2: Fuente"])
		for name, kind, direction, empty in (
			("script_nextComment", "comment", 1, "No hay más comentarios"),
			("script_previousComment", "comment", -1, "No hay comentarios anteriores"),
			("script_nextRevision", "revision", 1, "No hay más revisiones"),
			("script_previousRevision", "revision", -1, "No hay revisiones anteriores"),
		):
			with Harness() as h, mock.patch.object(_word, "om_findNext", return_value=None) as om:
				getattr(self.doc, name)(_gesture())
			om.assert_called_once_with(11, kind, direction)
			self.assertEqual(h.said, [empty])
		with Harness() as h, mock.patch.object(_word, "om_findNext", return_value={"type": 1, "text": "hola", "author": "Ana", "line": "la línea"}):
			self.doc.script_nextRevision(_gesture())
		self.assertEqual(h.said, ["inserción: hola de Ana", "la línea"])

	def test_elements_list_and_go(self):
		elements = {"headings": [("nivel 1: Intro", 0, 0)], "spelling": [("errror", 10, 16)]}
		with Harness() as h, mock.patch.object(_word, "om_elements", return_value=elements), mock.patch.object(_word, "om_moveTo", return_value="línea") as move:
			self.doc.script_elementsList(_gesture())
			key, title, categories, actions = h.lists[0][:4]
			self.assertEqual(key, "wordElements")
			items = dict(categories)["Errores ortográficos"]()
			actions[0].callback(items[0][1])
		move.assert_called_once_with(11, 10, 16)
		self.assertIn("línea", h.said)

	def test_table_navigation_and_headers(self):
		cell = {"inTable": True, "row": 2, "col": 1, "text": "Ana", "rowHeader": "", "colHeader": "Nombre", "tableStart": 40}
		with Harness() as h, mock.patch.object(_word, "om_tableKey", return_value=("C:\\a.docx", 1)), mock.patch.object(_word, "om_tableMove", return_value=cell) as move:
			for name, d in (("script_nextRow", (1, 0)), ("script_previousRow", (-1, 0)), ("script_nextColumn", (0, 1)), ("script_previousColumn", (0, -1))):
				h.said.clear()
				getattr(self.doc, name)(_gesture())
				self.assertEqual(move.call_args[0][1:3], d)
				self.assertEqual(h.said, ["Nombre, Ana, fila 2, columna 1"])
		self.assertEqual(self.app._lastTable, 40)
		with Harness() as h, mock.patch.object(_word, "om_tableKey", return_value=None):
			self.doc.script_nextRow(_gesture())
			self.doc.script_setColumnHeaders(_gesture())
			self.doc.script_readColumnHeader(_gesture())
		self.assertEqual(h.said, ["No estás en una tabla"] * 3)
		from tiresias.appmodules import _headers

		_headers.reset()
		with mock.patch.object(_headers, "_save"):
			with Harness() as h, mock.patch.object(_word, "om_tableKey", return_value=("C:\\a.docx", 1)), mock.patch.object(_word, "om_cellInfo", return_value=cell):
				self.doc.script_setColumnHeaders(_gesture())
				self.doc.script_setRowHeaders(_gesture())
				self.doc.script_setColumnHeaders(_gesture())
				self.doc.script_readColumnHeader(_gesture())
				self.doc.script_readRowHeader(_gesture())
		self.assertEqual(h.said, ["La fila 2 contiene los títulos de columna", "La columna 1 contiene los títulos de fila", "Títulos de columna borrados", "Nombre", "Sin título de fila"])
		_headers.reset()

	def test_list_items(self):
		d = {"moved": True, "text": "dos", "listType": 2, "listString": "", "listLevel": 1, "listStart": 6, "listCount": 3, "index": 2}
		for name, where in (("script_nextListItem", "next"), ("script_previousListItem", "previous"), ("script_firstListItem", "first"), ("script_lastListItem", "last")):
			self.app._lastList = None
			with Harness() as h, mock.patch.object(_word, "om_listItemMove", return_value=d) as move:
				getattr(self.doc, name)(_gesture())
			move.assert_called_once_with(11, where)
			self.assertEqual(h.said, ["lista con 3 elementos, elemento de lista viñeta, 2 de 3, dos"])
		with Harness() as h, mock.patch.object(_word, "om_listItemMove", return_value={"moved": False, "reason": "notInList"}):
			self.doc.script_firstListItem(_gesture())
		self.assertEqual(h.said, ["No estás en una lista"])

	def test_format_shortcut(self):
		# Revisión 1.0.11: el formato de antes se lee al pulsar Control y la
		# tecla se envía primero (lo escrito después no se adelanta a la negrita).
		from tiresias import api

		snaps = iter([{"bold": 0}, {"bold": -1}])
		g = _gesture("n")
		winword._formatBaselines.clear()
		with Harness() as h, mock.patch.object(_word, "om_formatSnapshot", side_effect=lambda *a: next(snaps)), mock.patch.object(api, "getFocusObject", return_value=self.doc):
			winword._onModifierDown("control")
			self.doc.script_formatShortcut(g)
		g.send.assert_called_once()
		self.assertEqual(h.said, ["negrita activado"])
		winword._formatBaselines.clear()

	def test_format_shortcut_disabled(self):
		g = _gesture("n")
		with _confValue("officeWord", "reportFormattingShortcuts", False), Harness() as h, mock.patch.object(_word, "om_formatSnapshot", side_effect=AssertionError):
			self.doc.script_formatShortcut(g)
		g.send.assert_called_once()
		self.assertEqual(h.said, [])

	def test_line_move_remembers_selection(self):
		"""Tras moverse por líneas se recuerda la selección (como el ayudante base): si
		no, los eventos de cursor siguientes anunciaban «no seleccionado»."""
		from tiresias.objects import behaviors

		info = mock.Mock(bookmark="b")
		g = _gesture()
		with (
			mock.patch.object(winword.WordDocument, "_wantsLineExtras", return_value=True),
			mock.patch.object(winword.WordDocument, "_getCaretInfo", return_value=info, create=True),
			mock.patch.object(winword.WordDocument, "_startWatch", create=True) as watch,
			mock.patch.object(winword.WordDocument, "_afterLineMove") as after,
			mock.patch.object(behaviors, "_rememberCaret"),
			mock.patch.object(behaviors, "_rememberSelection") as remember,
		):
			self.doc.script_caret_moveByLine(g)
			g.send.assert_called_once()
			watch.call_args[0][1](info, True)
		remember.assert_called_once_with(self.doc)
		after.assert_called_once_with(info)

	def test_paragraph_move_remembers_selection(self):
		from tiresias import textinfo
		from tiresias.objects import behaviors

		info = mock.Mock(bookmark="b")
		for style in ("application", "multiLineBreak"):
			with (
				mock.patch.object(textinfo, "paragraphStyle", return_value=style),
				mock.patch.object(winword.WordDocument, "_getCaretInfo", return_value=info, create=True),
				mock.patch.object(winword.WordDocument, "_startWatch", create=True) as watch,
				mock.patch.object(winword.WordDocument, "_speakWithList") as spoke,
				mock.patch.object(winword.review, "handleCaretMove"),
				mock.patch.object(behaviors, "_rememberCaret"),
				mock.patch.object(behaviors, "_rememberSelection") as remember,
			):
				self.doc.script_caret_moveByParagraph(_gesture())
				if style == "application":
					watch.call_args[0][1](info, True)
			remember.assert_called_once_with(self.doc)
			spoke.assert_called_once_with(info, textinfo.UNIT_PARAGRAPH)

	def test_line_move_announcements(self):
		info = mock.Mock()
		li = {"page": 3, "inTable": True, "tableStart": 5, "rows": 2, "cols": 4, "listType": 0, "comments": 1, "revisions": 0, "footnotes": 0}
		self.app._lastPage = 2
		with Harness() as h, mock.patch.object(_word, "om_lineInfo", return_value=li), mock.patch.object(winword.review, "handleCaretMove"), mock.patch.object(winword.presentation, "speakTextInfo", lambda *a, **k: h.said.append("LÍNEA")):
			self.doc._afterLineMove(info)
		self.assertEqual(h.said, ["página 3, tabla de 2 filas y 4 columnas", "LÍNEA", "con comentario"])

	def test_alignment_names(self):
		self.assertEqual(_word.ALIGNMENTS[9], "justificado")
		self.assertNotIn("om_formatToggle", dir(_word))

	def test_chart_in_word_and_outlook(self):
		"""Tiresias+Alt+G en el cuerpo de un mensaje de Outlook (documento de Word)
		fallaba: el módulo de Outlook no tenía la navegación por gráficos."""
		data = {"title": "Ventas", "type": 51, "typeName": "de columnas", "axes": {}, "legend": [], "series": [{"name": "2024", "values": [1.0, 2.0], "categories": ["ene", "feb"]}]}
		self.assertTrue(issubclass(outlook.AppModule, _chart.ChartNavigationMixin))
		app = outlook.AppModule.__new__(outlook.AppModule)
		app._instanceGestures = {}
		for target in (self.app, app):
			with mock.patch.object(winword.WordDocument, "_app", return_value=target), Harness() as h, mock.patch.object(_chart, "om_wordChart", return_value=data):
				self.doc.script_chart(_gesture())
				self.assertIsNotNone(target.chartNavigator)
				target.stopChartNavigation(silent=True)
			self.assertIn("Ventas", h.text())

	def test_om_functions_with_fake_word(self):
		w = mock.MagicMock()
		values = {_word.wdActiveEndAdjustedPageNumber: 4, _word.wdNumberOfPagesInDocument: 9, _word.wdFirstCharacterLineNumber: 12, _word.wdFirstCharacterColumnNumber: 3, _word.wdActiveEndSectionNumber: 1, _word.wdWithInTable: False}
		w.Application.Selection.Information.side_effect = lambda k: values[k]
		w.Application.Selection.Document.Sections.Count = 1
		with mock.patch.object(_word, "_window", return_value=w):
			self.assertEqual(_word.om_position(1), {"page": 4, "pages": 9, "line": 12, "column": 3, "section": 1, "sections": 1})
			self.assertEqual(_word.om_tableMove(1, 1, 0, None), {"inTable": False})
			self.assertEqual(_word.om_cellInfo(1, None), {"inTable": False})
			self.assertIsNone(_word.om_tableKey(1))
			self.assertEqual(_word.om_lineInfo(1)["page"], 4)
			for fn in (_word.om_formatting, _word.om_elements, _word.om_comments, _word.om_revisions, _word.om_commentsAtCaret, _word.om_notesAtCaret, _word.om_listInfo, _word.om_formatSnapshot):
				fn(1)
			self.assertIsInstance(_word.om_moveTo(1, 5), str)


class _confValue:
	"""Cambia una opción mientras dura el bloque."""

	def __init__(self, section: str, key: str, value) -> None:
		self.section, self.key, self.value = section, key, value

	def __enter__(self):
		self.old = conf[self.section][self.key]
		conf[self.section][self.key] = self.value
		return self

	def __exit__(self, *exc) -> None:
		conf[self.section][self.key] = self.old


# ====================================================================== Excel
class _XlCell:
	def __init__(self, sheet, r, c):
		self.sheet, self.Row, self.Column = sheet, r, c

	@property
	def Text(self):
		return self.sheet.shown.get((self.Row, self.Column), "")


class _XlRange:
	def __init__(self, sheet, a, b):
		self.sheet, self.a, self.b = sheet, a, b

	@property
	def Value2(self):
		return tuple(tuple(self.sheet.data.get((r, c)) for c in range(self.a.Column, self.b.Column + 1)) for r in range(self.a.Row, self.b.Row + 1))


class _XlSheet:
	def __init__(self, data, shown):
		self.data, self.shown = data, shown

		class Used:
			Row = 1
			Column = 1

			class Rows:
				Count = 2

			class Columns:
				Count = 3

		self.UsedRange = Used()
		self.textCalls = 0

	def Cells(self, r, c):
		self.textCalls += 1
		return _XlCell(self, r, c)

	def Range(self, a, b):
		return _XlRange(self, a, b)


class ExcelSayAllTests(unittest.TestCase):
	def setUp(self):
		data = {(1, 1): "Fecha", (1, 2): "Importe", (1, 3): "Pagado", (2, 1): 45292.0, (2, 2): 1234.5, (2, 3): True}
		shown = {(1, 1): "Fecha", (2, 1): "01/01/2024", (2, 2): "1.234,50 €", (2, 3): "VERDADERO"}
		self.sheet = _XlSheet(data, shown)

		class App:
			ActiveSheet = self.sheet
			ActiveCell = _XlCell(self.sheet, 1, 1)

		self.p = mock.patch.object(_excel, "_app", lambda hwnd: App)
		self.p.start()

	def tearDown(self):
		self.p.stop()

	def test_numbers_and_dates_as_shown(self):
		"""La lectura continua leía las fechas como número de serie y los importes sin formato."""
		cells = _excel.om_cellsFromActive(1)
		self.assertEqual(cells, [("A1", "Fecha"), ("B1", "Importe"), ("C1", "Pagado"), ("A2", "01/01/2024"), ("B2", "1.234,50 €"), ("C2", "VERDADERO")])

	def test_time_budget_falls_back_to_values(self):
		with mock.patch.object(_excel, "SHOWN_TEXT_BUDGET", -1):
			cells = _excel.om_cellsFromActive(1)
		self.assertEqual(cells[3:5], [("A2", "45292"), ("B2", "1234.5")])

	def test_narrow_column_uses_value(self):
		self.sheet.shown[(2, 2)] = "####"
		self.assertEqual(_excel.om_cellsFromActive(1)[4], ("B2", "1234.5"))


def _excelApp():
	app = excel.AppModule.__new__(excel.AppModule)
	app._instanceGestures = {}
	app._sheetInfo, app._pendingSheet, app.watched = {}, set(), {}
	app._watchHwnd, app._watchTimer, app._bookPaths, app._loadedBooks = 0, None, {}, set()
	app.chartNavigator = None
	return app


class ExcelScriptTests(unittest.TestCase):
	def setUp(self):
		self.app = _excelApp()

		class Cell(excel.ExcelCell):
			appModule = self.app
			value = "30"
			name = "B2"
			tableCellCoords = (3, 3)

		self.cell = Cell.__new__(Cell)
		self.ps = [mock.patch.object(excel.ExcelCell, "_hwnd", return_value=21), mock.patch.object(excel.ExcelCell, "_sheetKey", return_value="21|hoja")]
		for p in self.ps:
			p.start()

	def tearDown(self):
		for p in self.ps:
			p.stop()

	def test_comment_formula_details(self):
		d = {"address": "B2", "comment": {"author": "Ana", "text": "ojo", "resolved": False, "replies": []}, "note": "nota"}
		with Harness() as h, mock.patch.object(_excel, "om_comment", return_value=d):
			self.cell.script_readComment(_gesture())
		self.assertEqual(h.said, ["Comentario de Ana: ojo Nota: nota"])
		with Harness() as h, mock.patch.object(_excel, "om_comment", return_value={"address": "B2"}):
			self.cell.script_readComment(_gesture())
		self.assertEqual(h.said, ["La celda no tiene comentarios ni notas"])
		with Harness() as h, mock.patch.object(_excel, "om_formula", return_value={"address": "B2", "formula": "=A1*2", "value": "30"}):
			self.cell.script_readFormula(_gesture())
		self.assertEqual(h.said, ["=A1*2, resultado 30"])
		with Harness(repeat=1) as h, mock.patch.object(_excel, "om_formula", return_value={"address": "B2", "formula": "=A1", "value": ""}):
			self.cell.script_readFormula(_gesture())
		self.assertEqual(h.said, ["=A1"])
		with Harness() as h, mock.patch.object(_excel, "om_cellDetails", return_value={"address": "B2", "merged": "B2:C2"}):
			self.cell.script_cellDetails(_gesture())
		self.assertEqual(h.said, ["B2, combinada B2:C2"])

	def test_selection_and_say_all(self):
		g = _gesture()
		with Harness() as h, mock.patch.object(_excel, "om_selection", return_value={"address": "A1:B2", "count": 4, "rows": 2, "cols": 2}):
			self.cell.script_announceSelection(g)
		g.send.assert_called_once()
		self.assertEqual(h.said, ["A1 a B2 seleccionado, 4 celdas"])
		self.assertEqual(dict(excel.ExcelCell.iterClassGestures())["kb:shift+downarrow"], "announceSelection")
		with Harness() as h, mock.patch.object(_excel, "om_cellsFromActive", return_value=[("B2", "30"), ("C2", "Sevilla")]):
			self.cell.script_sayAll(_gesture())
		self.assertEqual(h.said, ["30, B2", "Sevilla, C2"])
		with Harness() as h, mock.patch.object(_excel, "om_cellsFromActive", return_value=[]):
			self.cell.script_sayAll(_gesture())
		self.assertEqual(h.said, ["No hay más datos en la hoja"])

	def test_headers(self):
		from tiresias.appmodules import _headers

		_headers.reset()
		with mock.patch.object(_headers, "_save"), Harness() as h, mock.patch.object(_excel, "om_sheetInfo", return_value={"book": "C:\\l.xlsx", "bookName": "l.xlsx", "sheet": "Hoja1", "named": {}}), mock.patch.object(excel.AppModule, "loadWatched"):
			self.cell.script_setColumnHeaders(_gesture())
			self.cell.script_setRowHeaders(_gesture())
			self.assertEqual(self.app.sheetInfo("21|hoja")["headers"], {"colHeaderRow": 2, "rowHeaderCol": 2})
			with mock.patch.object(excel.ExcelCell, "headerTexts", return_value=("Ana", "Edad")):
				self.cell.script_readColumnHeader(_gesture())
				self.cell.script_readRowHeader(_gesture())
			with mock.patch.object(excel.ExcelCell, "headerTexts", return_value=("", "")):
				self.cell.script_readColumnHeader(_gesture())
		self.assertEqual(h.said[:4], ["La fila 2 contiene los títulos de columna", "La columna B contiene los títulos de fila", "Edad", "Ana"])
		self.assertIn("Sin título de columna", h.said[4])
		_headers.reset()

	def test_row_column_viewer_watch_and_elements(self):
		line = {"kind": "row", "row": 2, "col": 2, "items": [("A2", "Nombre", "Ana")]}
		with Harness() as h, mock.patch.object(_excel, "om_lineCells", return_value=line) as om:
			self.cell.script_readRow(_gesture())
			self.cell.script_readColumn(_gesture())
		self.assertEqual([c[0][1] for c in om.call_args_list], ["row", "col"])
		self.assertEqual(h.said[0], "Nombre, Ana")
		with Harness() as h, mock.patch.object(excel.ExcelCell, "headerTexts", return_value=("", "")), mock.patch.object(_excel, "om_cellFull", return_value={"address": "B2", "content": "uno\ndos"}):
			self.cell.script_cellViewer(_gesture())
		self.assertEqual(h.shown[0][0], "Celda B2")
		with Harness() as h, mock.patch.object(_excel, "om_activeCellRef", return_value=("l.xlsx", "Hoja1", "B2", "")), mock.patch.object(excel.AppModule, "_scheduleWatch"):
			self.cell.script_toggleWatchCell(_gesture())
			self.assertIn(("l.xlsx", "Hoja1", "B2"), self.app.watched)
			self.app.script_watchedCellsList(_gesture())
			self.assertEqual(h.lists[-1][0], "excelWatched")
			self.cell.script_toggleWatchCell(_gesture())
		self.assertEqual(h.said, ["Se vigila B2 de la hoja Hoja1", "Ya no se vigila B2"])
		with Harness() as h:
			self.app.script_watchedCellsList(_gesture())
		self.assertIn("No hay celdas vigiladas", h.said[0])
		with Harness() as h, mock.patch.object(_excel, "om_elements", return_value={"sheets": [("Hoja1", ("Hoja1", "A1"))]}), mock.patch.object(_excel, "om_select", return_value="A1 x") as sel:
			self.cell.script_elementsList(_gesture())
			categories, actions = h.lists[0][2], h.lists[0][3]
			actions[0].callback(dict(categories)["Hojas"]()[0][1])
		sel.assert_called_once_with(21, "A1", "Hoja1")

	def test_chart(self):
		with Harness() as h, mock.patch.object(_chart, "om_excelChart", return_value=None), mock.patch("tiresias.api.getFocusObject", return_value=self.cell):
			self.app.script_describeChart(_gesture())
		self.assertEqual(h.said, ["No hay ningún gráfico seleccionado"])

	def test_om_functions_with_fake_excel(self):
		w = mock.MagicMock()
		with mock.patch.object(_excel, "_window", return_value=w):
			for fn in (_excel.om_sheetInfo, _excel.om_cellDetails, _excel.om_comment, _excel.om_formula, _excel.om_selection, _excel.om_elements, _excel.om_activeCellRef, _excel.om_cellFull):
				fn(1)
			_excel.om_select(1, "A1", "Hoja1")
			self.assertEqual(list(_excel.om_watchedValues(1, [("l", "h", "A1")])), [("l", "h", "A1")])
			_excel.om_lineCells(1, "row", True, True, None, None)


# ====================================================================== PowerPoint
class _View:
	def __init__(self, state, slide=None):
		self.State = state
		self._slide = slide

	@property
	def Slide(self):
		if self._slide is None:
			raise OSError("No hay ninguna diapositiva visible")
		return self._slide


class PowerPointTests(unittest.TestCase):
	def setUp(self):
		self.app = powerpnt.AppModule.__new__(powerpnt.AppModule)
		self.app._instanceGestures = {}
		self.app._lastShowSlide = None
		self.app.chartNavigator = None
		self.ps = [mock.patch.object(powerpnt.AppModule, "_hwnd", return_value=31)]
		for p in self.ps:
			p.start()

	def tearDown(self):
		for p in self.ps:
			p.stop()

	def test_slideshow_end_state(self):
		"""Al terminar la presentación ``View.Slide`` falla: antes nunca se decía «Fin de la presentación»."""
		w = mock.Mock()
		w.View = _View(5)
		with mock.patch.object(_ppt, "_window", return_value=w):
			self.assertEqual(_ppt.om_slideShowSlide(1), {"state": 5})
		w.View = _View(1, mock.MagicMock())
		with mock.patch.object(_ppt, "_window", return_value=w):
			d = _ppt.om_slideShowSlide(1)
		self.assertEqual(d["state"], 1)
		self.assertIn("index", d)

		app = self.app

		class Show(powerpnt.SlideShowWindow):
			appModule = app

		show = Show.__new__(Show)
		with Harness() as h, mock.patch.object(powerpnt, "omWindow", return_value=31), mock.patch.object(_ppt, "_window", return_value=mock.Mock(View=_View(5))):
			show.script_changeSlide(_gesture("space"))
		self.assertEqual(h.said, ["Fin de la presentación"])

	def test_slideshow_notes_use_app_module_script(self):
		self.assertNotIn("script_readNotes", powerpnt.SlideShowWindow.__dict__)
		self.assertEqual(dict(powerpnt.AppModule.iterClassGestures())["kb:tiresias+alt+n"], "readNotes")
		with Harness() as h, mock.patch.object(_ppt, "om_currentSlide", return_value={"index": 3, "notes": "Saludar"}):
			self.app.script_readNotes(_gesture())
		self.assertEqual(h.said, ["Saludar"])
		with Harness(repeat=1) as h, mock.patch.object(_ppt, "om_currentSlide", return_value={"index": 3, "notes": "Saludar"}):
			self.app.script_readNotes(_gesture())
		self.assertEqual(h.shown, [("Notas de la diapositiva 3", "Saludar")])
		with Harness() as h, mock.patch.object(_ppt, "om_currentSlide", return_value={"index": 3, "notes": ""}):
			self.app.script_readNotes(_gesture())
		self.assertEqual(h.said, ["La diapositiva 3 no tiene notas"])

	def test_math_targets_honour_selection(self):
		"""En la vista normal se usa la forma seleccionada (antes se ignoraba siempre)."""
		w = mock.MagicMock()
		w.Application.ActiveWindow.Selection.ShapeRange.Count = 1
		w.Application.ActiveWindow.Selection.ShapeRange.Item.return_value.Id = 7
		shapes = [{"id": 4, "name": "A", "segments": [("math", "<math>a</math>")]}, {"id": 7, "name": "B", "segments": [("math", "<math>b</math>")]}]
		with (
			mock.patch.object(_ppt, "_window", return_value=w),
			mock.patch.object(_ppt, "_currentSlide", return_value=mock.MagicMock()),
			mock.patch.object(_ppt, "_slideDict", return_value={"index": 2, "mathSuspect": True, "shapes": []}),
			mock.patch.object(_ppt, "presentationEquations", return_value=shapes),
		):
			with mock.patch.object(_ppt.winapi, "getClassName", return_value="paneClassDC"):
				self.assertEqual(_ppt.om_mathTargets(1), {"slide": 2, "items": [("B", "<math>b</math>")]})
			with mock.patch.object(_ppt.winapi, "getClassName", return_value="screenClass"):
				self.assertEqual(len(_ppt.om_mathTargets(1)["items"]), 2)

	def test_scripts(self):
		slide = {"index": 1, "count": 2, "title": "Hola", "texts": [], "shapes": [], "notes": ""}
		with Harness() as h, mock.patch.object(_ppt, "om_currentSlide", return_value=slide):
			self.app.script_readSlide(_gesture())
		self.assertEqual(h.said, ["Diapositiva 1 de 2, Hola"])
		shape = {"name": "Título 1", "type": 14, "left": 72.0, "top": 72.0, "width": 144.0, "height": 72.0, "table": [["Nombre", "Edad"], ["Ana", "30"]], "cell": (2, 2)}
		with Harness() as h, mock.patch.object(_ppt, "om_selectionShape", return_value=shape):
			self.app.script_shapeLocation(_gesture())
			self.app.script_readTable(_gesture())
		self.assertTrue(h.said[0].startswith("Título 1, marcador de posición, a 2,5 cm"))
		self.assertEqual(h.said[1], "tabla de 2 filas y 2 columnas, fila 2, columna 2, Edad, 30")
		with Harness() as h, mock.patch.object(_ppt, "om_selectionShape", return_value=None):
			self.app.script_shapeLocation(_gesture())
			self.app.script_readTable(_gesture())
		self.assertEqual(h.said, ["No hay ninguna forma seleccionada", "No hay ninguna tabla seleccionada"])
		with Harness() as h, mock.patch.object(_chart, "om_pptChart", return_value=None):
			self.app.script_chart(_gesture())
		self.assertEqual(h.said, ["No hay ningún gráfico seleccionado"])
		elements = {"slides": [("Diapositiva 2", ("slide", 2, ""))], "tables": [("t", ("table", 1, "T", [["a"]]))]}
		with Harness() as h, mock.patch.object(_ppt, "om_elements", return_value=elements), mock.patch.object(_ppt, "om_gotoSlide", return_value=slide) as go:
			self.app.script_elementsList(_gesture())
			categories, actions = dict(h.lists[0][2]), h.lists[0][3]
			actions[0].callback(categories["Diapositivas"]()[0][1])
			actions[0].callback(categories["Tablas"]()[0][1])
		go.assert_called_once_with(31, 2)
		self.assertEqual(h.shown[0][0], "T")

	def test_om_functions_with_fake_powerpoint(self):
		w = mock.MagicMock()
		with mock.patch.object(_ppt, "_window", return_value=w):
			for fn in (_ppt.om_currentSlide, _ppt.om_selectionShape, _ppt.om_elements):
				fn(1)
			_ppt.om_slideById(1, 256)
			_ppt.om_gotoSlide(1, 1)
			_ppt.om_selectShape(1, 1, "Título")


# ====================================================================== Outlook
class OutlookTests(unittest.TestCase):
	def setUp(self):
		self.app = outlook.AppModule.__new__(outlook.AppModule)
		self.app._instanceGestures = {}

	def test_fields(self):
		data = {"class": outlook.olMail, "sent": True, "fields": {"from": "Ana", "date": "01/02/2024 10:00", "to": "Luis", "cc": "", "subject": "Hola", "attachments": "a.pdf (3 KB)"}}
		focus = mock.Mock(windowHandle=5)
		with Harness() as h, mock.patch.object(outlook, "om_inspectorFields", return_value=data), mock.patch.object(outlook.api, "getFocusObject", return_value=focus), mock.patch.object(outlook, "_rootClass", return_value=outlook.OUTLOOK_WINDOW_CLASS):
			for n in range(1, 7):
				getattr(self.app, f"script_field{n}")(_gesture(str(n)))
		self.assertEqual(h.said, ["De: Ana", "Fecha: 01/02/2024 10:00", "Para: Luis", "CC vacío", "Asunto: Hola", "Adjuntos: a.pdf (3 KB)"])
		g = _gesture("1")
		with Harness() as h, mock.patch.object(outlook, "om_inspectorFields", return_value=None), mock.patch.object(outlook.api, "getFocusObject", return_value=focus), mock.patch.object(outlook, "_rootClass", return_value=outlook.OUTLOOK_WINDOW_CLASS):
			self.app.script_field1(g)
		g.send.assert_called_once()
		self.assertEqual(h.said, [])

	def test_details_and_attachments(self):
		d = {"items": [{"class": outlook.olMail, "subject": "Hola", "from": "Ana", "unread": True}], "calendar": False}
		with Harness() as h, mock.patch.object(outlook, "om_selectionDetails", return_value=d):
			self.app.script_selectionDetails(_gesture())
		self.assertEqual(h.said, ["no leído, de Ana, Hola"])
		with Harness() as h, mock.patch.object(outlook, "om_attachments", return_value={"where": "", "items": []}):
			self.app.script_attachmentsList(_gesture())
		self.assertEqual(h.said, ["No hay ningún mensaje abierto ni seleccionado"])
		with Harness() as h, mock.patch.object(outlook, "om_attachments", return_value={"where": "explorer", "subject": "Hola", "entryId": "x", "items": [{"index": 1, "name": "a.pdf", "size": 2048, "type": 1}]}):
			self.app.script_attachmentsList(_gesture())
		self.assertEqual(h.lists[0][0], "outlookAttachments")
		self.assertEqual(h.lists[0][2][0][1](), [("a.pdf, 2 KB", {"index": 1, "name": "a.pdf", "size": 2048, "type": 1})])

	def test_om_functions_with_fake_outlook(self):
		app = mock.MagicMock()
		app.ActiveWindow.return_value.Class = outlook.olInspector
		app.ActiveWindow.return_value.CurrentItem.Class = outlook.olMail
		with mock.patch.object(outlook, "_outlook", return_value=app):
			self.assertEqual(outlook.om_inspectorFields()["class"], outlook.olMail)
			outlook.om_selectionDetails()
			self.assertEqual(outlook.om_attachments()["where"], "inspector")


# ====================================================================== gráficos, LibreOffice, Thunderbird y Google
class ChartAndOtherAppsTests(unittest.TestCase):
	def test_chart_navigation_scripts(self):
		data = {"title": "T", "type": 4, "typeName": "de líneas", "axes": {"value": {"title": "€"}}, "legend": ["A"], "series": [{"name": "A", "values": [1.0, 3.0], "categories": ["x", "y"]}, {"name": "B", "values": [2.0], "categories": ["x"]}]}
		app = _wordApp()
		from tiresias.audio import tones

		with Harness() as h, mock.patch.object(tones, "beep"), mock.patch.object(tones, "playSound"):
			app.startChartNavigation(data)
			names = sorted(set(_chart.NAV_GESTURES.values()) - {"chart_exit"}) + ["chart_exit"]
			for name in names:
				h.said.clear()
				app.chartNavigator.series = app.chartNavigator.point = 0
				getattr(app, "script_" + name)(_gesture())
				if name not in ("chart_playSeries", "chart_previousPoint", "chart_previousSeries", "chart_firstPoint"):
					self.assertTrue(h.said, name)
			self.assertIsNone(app.chartNavigator)

	def test_libreoffice_format_shortcut(self):
		from tiresias.appmodules import soffice
		from tiresias.objects.roles import Role, State

		app = soffice.AppModule.__new__(soffice.AppModule)
		g = _gesture("b", ("kb:control+b",))
		btn = mock.Mock(states={State.PRESSED})
		with Harness() as h, mock.patch.object(soffice.api, "getFocusObject", return_value=mock.Mock(role=Role.DOCUMENT)), mock.patch.object(soffice.api, "getForegroundObject"), mock.patch.object(soffice, "findToggle", return_value=btn):
			app.script_formatShortcut(g)
		g.send.assert_called_once()
		self.assertEqual(h.said, ["negrita activado"])

	def test_thunderbird_headers(self):
		from tiresias.appmodules import thunderbird

		app = thunderbird.AppModule.__new__(thunderbird.AppModule)
		fg = mock.Mock()
		fg.element.FindFirstBuildCache.side_effect = lambda scope, cond, req: mock.Mock(CachedName="De  Ana")
		with Harness() as h, mock.patch.object(thunderbird.api, "getForegroundObject", return_value=fg), mock.patch("tiresias.a11y.uia_client.createPropertyCondition"):
			app.script_readHeaders(_gesture())
		self.assertEqual(h.said, ["De Ana"])

	def test_google_sheets_without_page(self):
		from tiresias.appmodules import _gsuite

		ed = _gsuite.SheetsCellEditor.__new__(_gsuite.SheetsCellEditor)
		with Harness() as h, mock.patch.object(_gsuite.SheetsCellEditor, "_bind", return_value=None):
			ed.script_readColumnHeader(_gesture())
			ed.script_setRowHeaders(_gesture())
		self.assertEqual(h.said, ["No se encuentra la celda actual de la hoja"] * 2)


class WordFindNextTests(unittest.TestCase):
	def test_only_the_target_is_read_in_full(self):
		"""Ir al comentario siguiente leía autor, texto y respuestas de todos (lento en documentos grandes)."""
		reads: list[int] = []

		class Comment:
			def __init__(self, start, reply=False):
				self.Scope = mock.Mock(Start=start, End=start + 3, Text="abc")
				self.Ancestor = object() if reply else None
				self.Done = False
				self.Date = None
				self.Range = mock.Mock(Text=f"c{start}")
				self.Replies = mock.Mock(Count=0)
				self._start = start

			@property
			def Author(self):
				reads.append(self._start)
				return "Ana"

		comments = [Comment(50), Comment(10), Comment(30, reply=True), Comment(80)]
		coll = mock.Mock(Count=len(comments))
		coll.Item.side_effect = lambda i: comments[i - 1]
		sel = mock.Mock(Start=20)
		sel.Document.Comments = coll
		with mock.patch.object(_word, "_sel", return_value=sel), mock.patch.object(_word, "om_moveTo", return_value="línea") as move:
			d = _word.om_findNext(1, "comment", 1)
			self.assertEqual((d["start"], d["text"], d["line"]), (50, "c50", "línea"))
			move.assert_called_once_with(1, 50)
			self.assertEqual(reads, [50])
			reads.clear()
			self.assertEqual(_word.om_findNext(1, "comment", -1)["start"], 10)
			self.assertEqual(reads, [10])
			sel.Start = 90
			self.assertIsNone(_word.om_findNext(1, "comment", 1))
		revs = [mock.Mock(Type=1, Author="Luis", Date=None, Range=mock.Mock(Start=s, End=s + 1, Text="x")) for s in (40, 5)]
		rcoll = mock.Mock(Count=2)
		rcoll.Item.side_effect = lambda i: revs[i - 1]
		sel = mock.Mock(Start=6)
		sel.Document.Revisions = rcoll
		with mock.patch.object(_word, "_sel", return_value=sel), mock.patch.object(_word, "om_moveTo", return_value=""):
			self.assertEqual(_word.om_findNext(1, "revision", 1)["start"], 40)
			self.assertEqual(_word.om_findNext(1, "revision", -1)["author"], "Luis")


if __name__ == "__main__":
	unittest.main()
