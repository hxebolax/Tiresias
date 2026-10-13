"""Pruebas de los módulos de aplicación y de las herramientas de sistema.

Usan objetos simulados: no necesitan Office, Teams ni ninguna aplicación.
Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import datetime
import importlib
import os
import shutil
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_apps_test_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()

from tiresias.appmodules import handler  # noqa: E402
from tiresias.config import conf  # noqa: E402


class FakeObj:
	"""Objeto accesible mínimo para las pruebas."""

	def __init__(self, name="", role=None, children=None, value="", description="", **kw):
		from tiresias.objects.roles import Role

		self.name = name
		self.role = role if role is not None else Role.LISTITEM
		self._children = children or []
		self.value = value
		self.description = description
		self.next = None
		self.previous = None
		for k, v in kw.items():
			setattr(self, k, v)
		for a, b in zip(self._children, self._children[1:]):
			a.next, b.previous = b, a

	@property
	def children(self):
		return list(self._children)

	@property
	def childCount(self):
		return len(self._children)

	@property
	def lastChild(self):
		return self._children[-1] if self._children else None


# ====================================================================== gestor
class HandlerTests(unittest.TestCase):
	def test_aliases(self):
		self.assertEqual(handler.moduleNameForProcess("notepad++"), "notepadplusplus")
		self.assertEqual(handler.moduleNameForProcess("CalculatorApp"), "calculator")
		self.assertEqual(handler.moduleNameForProcess("code - insiders"), "code")
		self.assertEqual(handler.moduleNameForProcess("searchapp"), "searchhost")
		self.assertEqual(handler.moduleNameForProcess("startmenuexperiencehost"), "searchhost")
		self.assertEqual(handler.moduleNameForProcess("ms-teams"), "teams")
		self.assertEqual(handler.moduleNameForProcess("whatsapp.root"), "whatsapp_root")

	def test_alias_targets_exist(self):
		for exe, mod in handler.EXECUTABLE_ALIASES.items():
			with self.subTest(exe=exe):
				m = importlib.import_module(f"tiresias.appmodules.{mod}")
				self.assertTrue(hasattr(m, "AppModule"))

	def test_support_modules_are_not_apps(self):
		self.assertIsNone(handler._findModule("_office"))
		self.assertIsNone(handler._findModule("handler"))

	def test_register_alias(self):
		handler.registerExecutableAlias("MiEditor", "notepadplusplus")
		self.assertEqual(handler.moduleNameForProcess("mieditor"), "notepadplusplus")
		del handler.EXECUTABLE_ALIASES["mieditor"]

	def test_host_names(self):
		self.assertEqual(handler.packageNameFromAumid("Microsoft.Kindle_8wekyb3d8bbwe!App"), "microsoft.kindle")
		self.assertEqual(handler._javaAppName(["javaw.exe", "-Xmx1g", "-jar", "C:/apps/MiPrograma.jar"]), "miprograma")
		self.assertEqual(handler._javaAppName(["java", "-cp", "lib/*", "org.ejemplo.Principal"]), "principal")
		self.assertEqual(handler.getAppNameFromHost(0, "notepad"), "notepad")

	def test_sleep_mode_persistent(self):
		from tiresias.appmodules import AppModule

		app = AppModule.__new__(AppModule)
		app.appName = "pruebadormir"
		app.sleepMode = False
		handler.setSleepMode(app, True, persist=True)
		self.assertTrue(app.sleepMode)
		self.assertIn("pruebadormir", conf["appModules"]["sleepApps"])
		handler.setSleepMode(app, False, persist=True)
		self.assertNotIn("pruebadormir", conf["appModules"]["sleepApps"])


class PropertyOverrideTests(unittest.TestCase):
	def test_override_name(self):
		from tiresias.objects.base import AccObject

		class O(AccObject):
			def _get_name(self):
				return "original"

		o = O()
		self.assertEqual(o.name, "original")
		o.name = "corregido"
		self.assertEqual(o.name, "corregido")

	def test_read_only_elsewhere(self):
		from tiresias.baseobject import AutoPropertyObject

		class P(AutoPropertyObject):
			def _get_x(self):
				return 1

		with self.assertRaises(AttributeError):
			P().x = 2


class EventFilterTests(unittest.TestCase):
	def test_app_filter(self):
		from tiresias import events

		class App:
			def shouldProcessEvent(self, eventName, obj, **kw):
				return eventName != "nameChange"

		obj = FakeObj("x")
		obj.appModule = App()
		self.assertFalse(events._appAcceptsEvent("nameChange", obj, {}))
		self.assertTrue(events._appAcceptsEvent("gainFocus", obj, {}))


# ====================================================================== Office
class OfficeWorkerTests(unittest.TestCase):
	def test_timeout_and_recovery(self):
		from tiresias.appmodules import _office

		with self.assertRaises(_office.OfficeBusy):
			_office.call(time.sleep, 0.5, timeout=0.05)
		self.assertEqual(_office.call(lambda a, b: a + b, 2, 3), 5)
		self.assertEqual(_office.safeCall(lambda: 1 / 0, default="x"), "x")

	def test_helpers(self):
		from tiresias.appmodules import _office

		self.assertEqual(_office.columnLetters(1), "A")
		self.assertEqual(_office.columnLetters(28), "AB")
		self.assertEqual(_office.cellAddress(3, 27), "AA3")
		self.assertEqual(_office.formatCm(72), "2,5 cm")


class WordTests(unittest.TestCase):
	def setUp(self):
		from tiresias.appmodules import _word

		self.w = _word

	def test_clean(self):
		self.assertEqual(self.w.clean("c11\r\x07"), "c11")
		self.assertEqual(self.w.clean("uno\rdos\x0btres"), "uno dos tres")

	def test_comment_with_replies(self):
		c = {"author": "Ana", "date": "01/01/2026 10:00", "text": "Revisar.", "done": True, "replies": [{"author": "Luis", "text": "Hecho."}], "scope": "frase"}
		text = self.w.commentText(c, withScope=True)
		self.assertIn("Comentario de Ana", text)
		self.assertIn("resuelto", text)
		self.assertIn("Respuesta de Luis: Hecho", text)
		self.assertIn("sobre el texto: frase", text)

	def test_list_prefix_and_suffix(self):
		self.assertEqual(self.w.listPrefix({"listType": 0}), "")
		self.assertIn("viñeta", self.w.listPrefix({"listType": 2, "listString": "\uf0b7", "listLevel": 1}))
		self.assertIn("nivel 2", self.w.listPrefix({"listType": 3, "listString": "1.", "listLevel": 2}))
		self.assertEqual(self.w.lineSuffix({"comments": 2, "revisions": 1}, True), ["con 2 comentarios", "con revisión"])
		self.assertEqual(self.w.lineSuffix({"comments": 2}, False), [])

	def test_format_diff(self):
		old = {"bold": 0, "alignment": 0, "leftIndent": 0.0, "style": "Normal"}
		new = {"bold": -1, "alignment": 1, "leftIndent": 36.0, "style": "Normal"}
		parts = self.w.formatDiff(old, new)
		self.assertIn("negrita activado", parts)
		self.assertIn("centrado", parts)
		self.assertTrue(any(p.startswith("sangría 1,3 cm") for p in parts))
		self.assertEqual(self.w.formatDiff(new, new), [])

	def test_formatting_text_and_position(self):
		parts = self.w.formattingText({"style": "Título 1", "fontName": "Aptos", "fontSize": 12.0, "bold": -1, "alignment": 3, "firstLineIndent": -18.0})
		self.assertIn("negrita", parts)
		self.assertIn("justificado", parts)
		self.assertTrue(any("sangría francesa" in p for p in parts))
		self.assertEqual(self.w.positionText({"page": 2, "pages": 5, "line": 3, "column": 7, "sections": 1}), "página 2 de 5, línea 3, columna 7")

	def test_cell_text(self):
		d = {"row": 2, "col": 3, "text": "", "rowHeader": "Ana", "colHeader": "Edad"}
		self.assertEqual(self.w.cellText(d, True), "Ana, Edad, en blanco, fila 2, columna 3")
		self.assertEqual(self.w.cellText(d, False, coords=False), "en blanco")

	def test_date(self):
		self.assertEqual(self.w.formatDate(datetime.datetime(2026, 10, 6, 16, 29)), "06/10/2026 16:29")


class ExcelTests(unittest.TestCase):
	def test_selection_text(self):
		from tiresias.appmodules import _excel

		self.assertEqual(_excel.selectionText({"address": "A1:C3", "count": 9, "rows": 3, "cols": 3}), "A1 a C3 seleccionado, 9 celdas")
		self.assertEqual(_excel.selectionText({"address": "B2", "count": 1, "rows": 1, "cols": 1}), "B2 seleccionada")
		self.assertIn("columnas", _excel.selectionText({"address": "A:B", "count": 2097152, "rows": 1048576, "cols": 2}))

	def test_details(self):
		from tiresias.appmodules import _excel

		d = {"formula": "=A1*2", "merged": "E1:F1", "note": "ojo", "comment": {"author": "Ana", "text": "¿seguro?", "resolved": False, "replies": [{"author": "Luis", "text": "sí"}]}}
		brief = _excel.detailsText(d)
		self.assertEqual(brief[:2], ["combinada E1:F1", "tiene fórmula"])
		full = " ".join(_excel.detailsText(d, full=True))
		self.assertIn("fórmula =A1*2", full)
		self.assertIn("Respuesta de Luis: sí", full)

	def test_watched_cells_saved_per_book(self):
		from unittest import mock

		from tiresias.appmodules import _watched, excel

		_watched.reset()
		app = excel.AppModule.__new__(excel.AppModule)
		app.watched = {}
		app._watchTimer = None
		app._watchHwnd = 0
		app._bookPaths = {}
		app._loadedBooks = set()
		book = os.path.join(paths.configDir(), "cuentas.xlsx")
		with mock.patch.object(excel.speech, "speakMessage"), mock.patch.object(excel.AppModule, "_scheduleWatch"):
			app.toggleWatch(1, ("cuentas.xlsx", "Resumen", "B12", book))
			app.toggleWatch(1, ("Libro1", "Hoja1", "A1", "Libro1"))
		_watched.reset()
		self.assertEqual(_watched.cells(book), [("Resumen", "B12")])
		self.assertEqual(_watched.cells("Libro1"), [])
		# Al volver a abrir el libro se recuperan.
		other = excel.AppModule.__new__(excel.AppModule)
		other.watched = {}
		other._watchTimer = None
		other._bookPaths = {}
		other._loadedBooks = set()
		with mock.patch.object(excel.AppModule, "_scheduleWatch"):
			other.loadWatched(5, "cuentas.xlsx", book)
		self.assertIn(("cuentas.xlsx", "Resumen", "B12"), other.watched)
		self.assertEqual(other._watchHwnd, 5)
		with mock.patch.object(excel.speech, "speakMessage"), mock.patch.object(excel.AppModule, "_scheduleWatch"):
			other.toggleWatch(5, ("cuentas.xlsx", "Resumen", "B12"))
		_watched.reset()
		self.assertEqual(_watched.cells(book), [])


class _FakeAxis:
	def __init__(self, title="", lo=None, hi=None):
		self.HasTitle = bool(title)
		self.AxisTitle = type("T", (), {"Text": title})()
		self.MinimumScale = lo
		self.MaximumScale = hi


class _FakeSeries:
	def __init__(self, name, values, cats):
		self.Name, self.Values, self.XValues = name, values, cats


class _FakeColl:
	def __init__(self, items):
		self._items = items
		self.Count = len(items)

	def Item(self, i):
		return self._items[i - 1]


class _FakeChart:
	HasTitle = True
	ChartType = 51
	HasLegend = True

	def __init__(self):
		self.ChartTitle = type("T", (), {"Text": "Ventas"})()
		self._series = _FakeColl([_FakeSeries("2025", (10.0, 30.0, 20.0), ("ene", "feb", "mar")), _FakeSeries("2026", (15.0, None, 40.0), ("ene", "feb", "mar"))])

	def Axes(self, kind):
		return _FakeAxis("Mes") if kind == 1 else _FakeAxis("Euros", 0.0, 50.0)

	def SeriesCollection(self):
		return self._series


class ChartTests(unittest.TestCase):
	def setUp(self):
		from tiresias.appmodules import _chart

		self.c = _chart
		self.data = _chart.readChart(_FakeChart())

	def test_read(self):
		d = self.data
		self.assertEqual(d["title"], "Ventas")
		self.assertEqual(d["typeName"], "de columnas")
		self.assertEqual(d["axes"]["value"], {"title": "Euros", "min": 0.0, "max": 50.0})
		self.assertEqual(d["legend"], ["2025", "2026"])
		self.assertEqual(d["series"][1]["values"], [15.0, None, 40.0])

	def test_texts(self):
		summary = self.c.summaryText(self.data)
		self.assertIn("Gráfico de columnas", summary)
		self.assertIn("eje de categorías: Mes", summary)
		self.assertIn("de 0 a 50", summary)
		self.assertIn("leyenda: 2025, 2026", summary)
		self.assertIn("feb: 30", self.c.fullText(self.data))

	def test_navigation(self):
		nav = self.c.ChartNavigator(self.data)
		self.assertEqual(nav.pointText(), "ene: 10, punto 1 de 3")
		self.assertFalse(nav.movePoint(-1))
		self.assertTrue(nav.movePoint(1))
		self.assertEqual(nav.pointText(), "feb: 30, punto 2 de 3")
		self.assertTrue(nav.moveSeries(1))
		self.assertTrue(nav.seriesText().startswith("Serie 2026, 2 de 2"))
		self.assertEqual(nav.pointText(), "feb: sin valor, punto 2 de 3")
		self.assertIsNone(nav.currentTone())
		self.assertFalse(nav.moveSeries(1))
		self.assertTrue(nav.moveToEdge(True))
		self.assertEqual(nav.point, 2)
		tones = nav.seriesTones()
		self.assertEqual(len(tones), 3)
		self.assertIsNone(tones[1])
		self.assertLess(tones[0], tones[2])

	def test_tone_scale(self):
		self.assertAlmostEqual(self.c.toneFor(0, 0, 50), self.c.TONE_LOW)
		self.assertAlmostEqual(self.c.toneFor(50, 0, 50), self.c.TONE_HIGH)
		self.assertLess(self.c.toneFor(10, 0, 50), self.c.toneFor(20, 0, 50))
		self.assertIsNone(self.c.toneFor(None, 0, 1))

	def test_pie_legend_uses_categories(self):
		chart = _FakeChart()
		chart.ChartType = 5
		self.assertEqual(self.c.readChart(chart)["legend"], ["ene", "feb", "mar"])

	def test_mixin_binds_and_releases_keys(self):
		from unittest import mock

		from tiresias.appmodules import AppModule

		class App(self.c.ChartNavigationMixin, AppModule):
			pass

		app = App.__new__(App)
		app._instanceGestures = {}
		app.chartNavigator = None
		with mock.patch("tiresias.speech.api.speak"):
			app.startChartNavigation(self.data)
			self.assertEqual(app._scriptNameForGesture("kb:rightarrow"), "chart_nextPoint")
			self.assertEqual(app._scriptNameForGesture("kb:escape"), "chart_exit")
			app.stopChartNavigation(silent=True)
		self.assertIsNone(app._scriptNameForGesture("kb:rightarrow"))
		self.assertIsNone(app.chartNavigator)


class PowerPointTests(unittest.TestCase):
	def test_slide_text(self):
		from tiresias.appmodules import _ppt

		d = {"index": 2, "count": 5, "title": "Resultados", "hidden": True, "notes": "x", "texts": ["Punto uno"], "shapes": [{"table": [["a", "b"], ["1", "2"]], "text": ""}]}
		text = _ppt.slideText(d)
		self.assertTrue(text.startswith("Diapositiva 2 de 5, oculta, Resultados, Punto uno"))
		self.assertIn("tabla de 2 filas y 2 columnas", text)
		self.assertTrue(text.endswith("tiene notas"))
		self.assertNotIn("oculta", _ppt.slideText(d, reportHidden=False))

	def test_table_and_ids(self):
		from tiresias.appmodules import _ppt

		self.assertEqual(_ppt.tableText([["Nombre", "Edad"], ["Ana", "30"]]), "Fila 1: Nombre; Edad\nFila 2: Nombre: Ana; Edad: 30")
		self.assertEqual(_ppt.slideIdFromAutomationId("Slide257Image"), 257)
		self.assertIsNone(_ppt.slideIdFromAutomationId("SlidePane"))
		text = _ppt.shapeLocationText({"name": "Título", "type": 14, "left": 72, "top": 36, "width": 144, "height": 72, "slideWidth": 720, "slideHeight": 540})
		self.assertIn("a 2,5 cm del borde izquierdo", text)


class OutlookTests(unittest.TestCase):
	def test_fields(self):
		from tiresias.appmodules import outlook

		received = {"class": outlook.olMail, "sent": True, "fields": {"from": "Ana", "subject": "Hola", "attachments": ""}}
		self.assertEqual(outlook.fieldFor(received, 1), ("De", "Ana"))
		self.assertEqual(outlook.fieldFor(received, 5), ("Asunto", "Hola"))
		draft = dict(received, sent=False)
		draft["fields"] = {"to": "luis@x", "subject": "Borrador"}
		self.assertEqual(outlook.fieldFor(draft, 1), ("Para", "luis@x"))
		self.assertIsNone(outlook.fieldFor(draft, 6))
		appt = {"class": outlook.olAppointment, "fields": {"subject": "Reunión", "location": "Sala 2"}}
		self.assertEqual(outlook.fieldFor(appt, 2), ("Ubicación", "Sala 2"))

	def test_details_text(self):
		from tiresias.appmodules import outlook

		d = {"calendar": False, "items": [{"class": outlook.olMail, "subject": "Factura", "from": "Banco", "unread": True, "attachments": 1, "importance": 2, "size": 4096}]}
		text = outlook.detailsText(d)
		self.assertIn("no leído", text)
		self.assertIn("1 adjunto", text)
		self.assertIn("importancia alta", text)
		self.assertEqual(outlook.detailsText({"items": []}), "No hay nada seleccionado")


# ====================================================================== chats
class ChatTests(unittest.TestCase):
	def test_classify(self):
		from tiresias.appmodules import _chat

		self.assertEqual(_chat.classify("Ana levantó la mano"), "hands")
		self.assertEqual(_chat.classify("Luis se unió a la reunión"), "joinLeave")
		self.assertEqual(_chat.classify("Recording started"), "recording")
		self.assertEqual(_chat.classify("Ana está compartiendo pantalla"), "sharing")
		self.assertEqual(_chat.classify("Nuevo mensaje de Ana"), "chat")
		self.assertEqual(_chat.classify("Algo raro"), "other")

	def test_dedupe(self):
		from tiresias.appmodules import _chat

		f = _chat.AlertFilter(2.0)
		self.assertFalse(f.isDuplicate("Tarjeta: aprobar gastos", now=0))
		self.assertTrue(f.isDuplicate("Tarjeta:  aprobar gastos", now=0.5))
		self.assertTrue(f.isDuplicate("aprobar gastos", now=0.6))
		self.assertFalse(f.isDuplicate("Tarjeta: aprobar gastos", now=5))

	def test_action(self):
		from tiresias.appmodules import _chat

		settings = {"alertMode": "all", "alertHands": False, "alertChat": True, "alertOther": True}
		self.assertEqual(_chat.AlertFilter.action("hands", settings), "ignore")
		self.assertEqual(_chat.AlertFilter.action("chat", settings), "speak")
		self.assertEqual(_chat.AlertFilter.action("chat", dict(settings, alertMode="beep")), "beep")
		self.assertEqual(_chat.AlertFilter.action("chat", dict(settings, alertMode="off")), "ignore")

	def test_rate_limit(self):
		from tiresias.appmodules import _chat

		r = _chat.RateLimiter(3)
		self.assertEqual([r.allow("x", now=0.1 * i) for i in range(5)], [True, True, True, False, False])
		self.assertTrue(r.allow("x", now=2.0))

	def test_message_list_and_last(self):
		from tiresias.appmodules import _chat

		app = _chat.ChatAppModule.__new__(_chat.ChatAppModule)
		app.messageListHints = _chat.MESSAGE_LIST_HINTS
		msgs = FakeObj("Mensajes de chat", children=[FakeObj("uno"), FakeObj("dos"), FakeObj("", children=[FakeObj("tres"), FakeObj("bis")])])
		other = FakeObj("Personas", children=[FakeObj(str(i)) for i in range(20)])
		self.assertIs(app.chooseMessageList([other, msgs]), msgs)
		app.findMessageList = lambda: msgs
		import collections

		app.history = collections.deque()
		self.assertEqual(app.lastMessages(3), ["tres bis", "dos", "uno"])

	def test_all_chat_modules_have_alt_numbers(self):
		for mod in ("teams", "zoom", "discord", "telegram", "slack"):
			m = importlib.import_module(f"tiresias.appmodules.{mod}")
			gestures = dict(m.AppModule.iterClassGestures())
			for k in "1234567890":
				self.assertIn(f"kb:alt+{k}", gestures, mod)


# ====================================================================== otras aplicaciones
class OtherAppsTests(unittest.TestCase):
	def _bare(self, modName):
		m = importlib.import_module(f"tiresias.appmodules.{modName}")
		return m.AppModule.__new__(m.AppModule)

	def test_media_titles(self):
		from tiresias.appmodules import _media

		self.assertEqual(_media.parseElapsedTotal("MP3 | 320 kbps | 1:23 / 3:45"), (83, 225))
		self.assertEqual(_media.formatSeconds(3723), "1:02:03")
		self.assertIsNone(self._bare("spotify").trackFromTitle("Spotify Premium"))
		self.assertEqual(self._bare("spotify").trackFromTitle("Artista - Canción"), "Artista - Canción")
		self.assertEqual(self._bare("winamp").trackFromTitle("12. Artista - Canción - Winamp"), "Artista - Canción")
		self.assertIsNone(self._bare("winamp").trackFromTitle("12. Artista - Canción - Winamp [Detenido]"))
		self.assertEqual(self._bare("foobar2000").trackFromTitle("Artista - Canción [foobar2000]"), "Artista - Canción")
		player = self._bare("spotify")
		player._lastTrack = None
		self.assertIsNone(player.checkTrack("A - B"))
		self.assertEqual(player.checkTrack("C - D"), "C - D")
		self.assertIsNone(player.checkTrack("C - D"))

	def test_putty_lines(self):
		from tiresias.appmodules import putty

		self.assertEqual(putty.lastLines("a\r\nb\r\n\r\nc\r\n", 2), ["c", "b"])
		self.assertEqual(putty.newLines("$ ls\r\nuno\r\n$ ", "$ ls\r\nuno\r\n$ pwd\r\n/home\r\n$ "), ["$ pwd", "/home", "$"])

	def test_explorer_clean(self):
		from tiresias.appmodules import explorer

		self.assertEqual(explorer.cleanText("Reloj 16:22\n\u200e06/\u200e10/\u200e2026"), "Reloj 16:22 06/10/2026")
		item = FakeObj("doc", children=[FakeObj("Nombre", value="doc", UIAAutomationId="System.ItemNameDisplay", UIAClassName="UIProperty"), FakeObj("Tamaño", value="1 KB", UIAAutomationId="System.Size", UIAClassName="UIProperty")])
		self.assertEqual(explorer.detailColumns(item), [("Tamaño", "1 KB")])

	def test_calculator_echo(self):
		app = self._bare("calculator")
		app._lastSpoken = ("", 0.0)
		app._lastTyped = ("7", 100.0)
		self.assertFalse(app.shouldSpeakDisplay("La pantalla muestra 7", now=100.2))
		self.assertTrue(app.shouldSpeakDisplay("La pantalla muestra 7", now=101.0))
		app._lastTyped = ("+", 100.0)
		self.assertTrue(app.shouldSpeakDisplay("La pantalla muestra 7", now=100.1))

	def test_scintilla_offsets(self):
		from tiresias.appmodules import _scintilla

		raw = "año\r\nbé".encode("utf-8")
		doc = _scintilla.ScintillaDocument(raw, 65001)
		self.assertEqual(doc.text, "año\r\nbé")
		self.assertEqual(doc.charOffset(4), 3)
		self.assertEqual(doc.byteOffset(3), 4)
		ascii_ = _scintilla.ScintillaDocument(b"abc", 0)
		self.assertEqual(ascii_.byteOffset(2), 2)

	def test_headers_store(self):
		from tiresias.appmodules import _headers

		_headers.reset()
		key = _headers.makeKey("C:/libro.xlsx", "Hoja1")
		_headers.set(key, "colHeaderRow", 2)
		_headers.reset()
		self.assertEqual(_headers.get(key), {"colHeaderRow": 2})
		_headers.set(key, "colHeaderRow", None)
		self.assertEqual(_headers.get(key), {})

	def test_vscode_workbench(self):
		from tiresias.appmodules import code
		from tiresias.objects.roles import Role

		window = FakeObj("VS Code", role=Role.WINDOW)
		wb = FakeObj("archivo.py - VS Code", role=Role.DOCUMENT, parent=window)
		inner = FakeObj("Vista previa", role=Role.DOCUMENT, parent=FakeObj("", role=Role.PANE, parent=wb))
		self.assertTrue(code.isWorkbenchDocument(wb))
		self.assertFalse(code.isWorkbenchDocument(inner))
		self.assertFalse(code.Workbench.shouldCreateTreeInterceptor)


# ====================================================================== herramientas de sistema
class SystemToolsTests(unittest.TestCase):
	def test_end_process_guard(self):
		from tiresias import system_tools

		ok, why = system_tools.canEndProcess(system_tools.ProcessInfo(4, "System"))
		self.assertFalse(ok)
		ok, _why = system_tools.canEndProcess(system_tools.ProcessInfo(os.getpid(), "python"))
		self.assertFalse(ok)
		ok, _why = system_tools.canEndProcess(system_tools.ProcessInfo(123456, "bloc"))
		self.assertTrue(ok)

	def test_windows_list(self):
		from tiresias import system_tools

		wins = system_tools.listWindows()
		self.assertIsInstance(wins, list)
		for w in wins:
			self.assertTrue(w.title)
			self.assertNotEqual(w.pid, os.getpid())

	def test_tray_icon_label(self):
		from tiresias import system_tools

		icon = system_tools.TrayIcon("OneDrive\r\nSincronizado", True, "onedrive")
		self.assertEqual(icon.label, "OneDrive Sincronizado (oculto)")


# ====================================================================== gestos
class GestureConflictTests(unittest.TestCase):
	def test_new_global_gestures_unique(self):
		from tiresias.global_commands import GlobalCommands

		gestures = dict(GlobalCommands.iterClassGestures())
		for g in ("kb:tiresias+f11", "kb:tiresias+shift+f11", "kb:tiresias+control+f11"):
			self.assertIn(g, gestures)
		self.assertEqual(gestures["kb:tiresias+shift+f11"], "processList")
		self.assertEqual(gestures["kb:tiresias+control+f11"], "trayIconList")

	def test_app_gestures_do_not_hide_important_globals(self):
		"""Los módulos no deben tapar órdenes globales de uso general."""
		from tiresias.global_commands import GlobalCommands

		globals_ = dict(GlobalCommands.iterClassGestures())
		allowed = {
			"kb:tiresias+f",  # formato (Word lo amplía)
			"kb(desktop):tiresias+numpaddelete",  # posición del cursor (Word, PowerPoint)
			"kb(laptop):tiresias+delete",
			"kb(desktop):tiresias+downarrow",  # leer todo (Excel lo hace por celdas)
			"kb(laptop):tiresias+a",
		}
		mods = ("winword", "excel", "powerpnt", "outlook", "teams", "zoom", "explorer", "putty", "thunderbird", "code", "devenv", "calculator", "notepad", "notepadplusplus")
		for name in mods:
			m = importlib.import_module(f"tiresias.appmodules.{name}")
			classes = [m.AppModule] + [getattr(m, c) for c in ("WordDocument", "ExcelCell", "SlideShowWindow") if hasattr(m, c)]
			for cls in classes:
				for g, _s in cls.iterClassGestures():
					if g in globals_ and g not in allowed:
						self.fail(f"{name}.{cls.__name__} tapa la orden global {globals_[g]} con {g}")


if __name__ == "__main__":
	unittest.main()
