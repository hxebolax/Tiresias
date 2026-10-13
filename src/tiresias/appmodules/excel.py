"""Microsoft Excel.

La celda con el foco llega por UI Automation (rápido y válido también en
hojas protegidas, NVDA #18537). El modelo de objetos se usa en segundo plano
y con tiempo máximo para lo demás, de modo que Excel no se congela por culpa
de Tiresias (NVDA #15281):

- títulos de fila y columna fijados por el usuario o con rangos con nombre
  «ColumnTitle»/«RowTitle» (también en hojas protegidas);
- fórmula, comentarios con respuestas, notas, celdas combinadas, validación,
  texto ajustado, celdas ocultas y enlaces;
- anuncio de la selección (Mayúsculas+flechas, Control+A...);
- lectura continua de la hoja desde la celda actual (NVDA #6624);
- lista de elementos: hojas, comentarios, notas, fórmulas, gráficos y rangos
  con nombre;
- celdas vigiladas que avisan cuando cambian;
- lectura de la fila o la columna entera con sus títulos (NVDA #901) y visor
  de celdas multilínea con la fórmula (foros 3.4);
- resumen del gráfico seleccionado.
"""

from __future__ import annotations

from .. import queue_handler, speech, winapi
from ..baseobject import script
from ..config import conf
from ..i18n import _
from ..log import getLogger
from ..objects.base import AccObject
from ..speech.commands import CallbackCommand
from . import AppModule as BaseAppModule
from . import _chart, _excel, _headers, _office, _watched

log = getLogger("excel")

CAT = _("Microsoft Excel")

SELECTION_GESTURES = (
	"kb:shift+upArrow",
	"kb:shift+downArrow",
	"kb:shift+leftArrow",
	"kb:shift+rightArrow",
	"kb:shift+home",
	"kb:shift+end",
	"kb:shift+pageUp",
	"kb:shift+pageDown",
	"kb:control+shift+upArrow",
	"kb:control+shift+downArrow",
	"kb:control+shift+leftArrow",
	"kb:control+shift+rightArrow",
	"kb:control+shift+home",
	"kb:control+shift+end",
	"kb:control+shift+space",
	"kb:shift+space",
	"kb:control+space",
	"kb:control+a",
	"kb:control+e",
)


def _repeat() -> int:
	from ..input import core as inputCore

	return inputCore.getLastScriptRepeatCount()


def _fail(error: BaseException) -> None:
	speech.speakMessage(_office.busyMessage(error))


def isSavedBook(path: str) -> bool:
	"""``True`` si el libro tiene archivo (``Libro1`` sin guardar no lo tiene)."""
	import os

	return bool(path) and (os.path.isabs(path) or "://" in path)


def isExcelCell(obj) -> bool:
	try:
		return getattr(obj, "UIAClassName", "") == "XLSpreadsheetCell"
	except Exception:
		return False


class ExcelCell(AccObject):
	"""Celda de Excel con el foco."""

	scriptCategory = CAT

	def _hwnd(self) -> int:
		return _office.windowForObject(self, "EXCEL7")

	# ------------------------------------------------------------ datos por UIA
	def _gridRowCol(self) -> tuple[int, int] | None:
		"""Fila y columna de Excel (1 = fila 1, 1 = columna A)."""
		coords = getattr(self, "tableCellCoords", None)
		if not coords:
			return None
		# La rejilla UIA incluye la fila y la columna de encabezados.
		return coords[0] - 1, coords[1] - 1

	def _sheetKey(self) -> str | None:
		"""Hoja (identificador de automatización del panel de la hoja) para la caché."""
		try:
			grid = self.parent
			sheetPane = grid.parent if grid is not None else None
			aid = getattr(sheetPane, "UIAAutomationId", "") if sheetPane is not None else ""
			return f"{self._hwnd()}|{aid}" if aid else None
		except Exception:
			return None

	def _gridCellValue(self, row: int, col: int) -> str:
		"""Valor de otra celda leído por UIA (sirve en hojas protegidas)."""
		from ..a11y import uia_client as uc
		from ..objects.uia import UIAObject

		grid = self.parent
		if grid is None:
			return ""
		try:
			pat = grid._pattern(uc.PAT_GRID, uc.UIA.IUIAutomationGridPattern)
			if not pat:
				return ""
			el = pat.GetItem(row, col)
			o = UIAObject.fromElement(el)
			return (o.value or "") if o is not None else ""
		except Exception:
			return ""

	def headerTexts(self) -> tuple[str, str]:
		"""(título de fila, título de columna) según la configuración de la hoja."""
		app = self.appModule
		info = app.sheetInfo(self._sheetKey()) if app is not None else None
		rc = self._gridRowCol()
		if not info or not rc:
			return "", ""
		row, col = rc
		headers = info.get("headers") or {}
		rowH = colH = ""
		hr = headers.get("colHeaderRow")
		hc = headers.get("rowHeaderCol")
		if hr and row > hr:
			colH = self._gridCellValue(hr, col)
		if hc and col > hc:
			rowH = self._gridCellValue(row, hc)
		return rowH, colH

	# ------------------------------------------------------------ presentación
	def _speechParts(self, withDetails: bool = True) -> list[str]:
		c = conf["officeExcel"]
		parts: list[str] = []
		# Los títulos de fila y columna siguen «Formato de documento», como en NVDA.
		if conf["documentFormatting"]["reportTableHeaders"]:
			rowH, colH = self.headerTexts()
			if rowH:
				parts.append(rowH)
			if colH:
				parts.append(colH)
		value = self.value
		parts.append(value if value else _("en blanco"))
		if c["reportCoordinates"]:
			parts.append(self.name)
		if withDetails and c["reportCellDetails"]:
			status = getattr(self, "_prop", None)
			try:
				from ..a11y import uia_client as uc

				item = self._prop(uc.P_ITEMSTATUS, "") if status else ""
			except Exception:
				item = ""
			if item:
				parts.append(item)
		return parts

	def reportFocus(self) -> None:
		app = self.appModule
		if app is not None:
			app.ensureSheetInfo(self)
		speech.speakText(", ".join(self._speechParts()))
		if conf["officeExcel"]["reportCellDetails"]:
			# Combinada, validación... por el modelo de objetos (sin esperar).
			name = self.name

			def done(d: dict) -> None:
				from .. import api

				focus = api.getFocusObject()
				if focus is None or getattr(focus, "name", None) != name:
					return
				extra = [p for p in _excel.detailsText(d) if p not in (_("tiene fórmula"), _("tiene nota"), _("tiene comentario"))]
				if extra:
					speech.speakMessage(", ".join(extra))

			_office.callAsync(_excel.om_cellDetails, self._hwnd(), callback=done, timeout=0.8)

	# ------------------------------------------------------------ órdenes
	@script(description=_("Lee el comentario o la nota de la celda, con las respuestas (dos veces: lo muestra)"), category=CAT, gesture="kb:tiresias+alt+c", speakOnDemand=True)
	def script_readComment(self, gesture) -> None:
		show = _repeat() == 1

		def done(d: dict) -> None:
			texts = []
			if d.get("comment"):
				texts.append(_excel.threadedText(d["comment"]))
			if d.get("note"):
				texts.append(_("Nota: {text}").format(text=d["note"]))
			if not texts:
				speech.speakMessage(_("La celda no tiene comentarios ni notas"))
			elif show:
				from .. import gui

				gui.showBrowseableMessage("\n\n".join(texts), _("Comentarios de {cell}").format(cell=d.get("address", "")))
			else:
				speech.speakText(" ".join(texts))

		_office.callAsync(_excel.om_comment, self._hwnd(), callback=done, onError=_fail)

	@script(description=_("Lee la fórmula de la celda (dos veces: la deletrea)"), category=CAT, gesture="kb:tiresias+alt+f", speakOnDemand=True)
	def script_readFormula(self, gesture) -> None:
		spell = _repeat() == 1

		def done(d: dict) -> None:
			if not d.get("formula"):
				speech.speakMessage(_("La celda no tiene fórmula"))
			elif spell:
				speech.speakSpelling(d["formula"])
			else:
				speech.speakText(_("{formula}, resultado {value}").format(formula=d["formula"], value=d.get("value") or _("en blanco")))

		_office.callAsync(_excel.om_formula, self._hwnd(), callback=done, onError=_fail)

	@script(description=_("Lee los detalles de la celda: fórmula, comentarios, combinación, validación, enlace"), category=CAT, gesture="kb:tiresias+alt+d", speakOnDemand=True)
	def script_cellDetails(self, gesture) -> None:
		def done(d: dict) -> None:
			parts = _excel.detailsText(d, full=True)
			speech.speakText(", ".join([d.get("address", "")] + parts) if parts else _("{cell}, sin detalles").format(cell=d.get("address", "")))

		_office.callAsync(_excel.om_cellDetails, self._hwnd(), callback=done, onError=_fail)

	def script_announceSelection(self, gesture) -> None:
		gesture.send()
		if not conf["officeExcel"]["reportSelection"]:
			return
		_office.callAsync(_excel.om_selection, self._hwnd(), 0.06, callback=lambda d: speech.speakMessage(_excel.selectionText(d)), timeout=1.0)

	script_announceSelection.__doc__ = _("Anuncia el rango seleccionado al ampliar la selección")
	script_announceSelection.category = CAT  # type: ignore[attr-defined]

	@script(description=_("Lee la hoja desde la celda actual hasta el final"), category=CAT, gestures=("kb(desktop):tiresias+downArrow", "kb(laptop):tiresias+a"), speakOnDemand=True)
	def script_sayAll(self, gesture) -> None:
		hwnd = self._hwnd()

		def done(cells: list) -> None:
			if not cells:
				speech.speakMessage(_("No hay más datos en la hoja"))
				return
			seq: list = []
			for addr, value in cells:
				seq.append(CallbackCommand(lambda a=addr: _office.callAsync(_excel.om_select, hwnd, a, timeout=1.0)))
				seq.append(f"{value}, {addr}" if conf["officeExcel"]["reportCoordinates"] else value)
			speech.cancelSpeech()
			speech.speak(seq)

		_office.callAsync(_excel.om_cellsFromActive, hwnd, callback=done, onError=_fail, timeout=6)

	# ------------------------------------------------------------ títulos
	def _setHeader(self, kind: str) -> None:
		app = self.appModule
		rc = self._gridRowCol()
		hwnd = self._hwnd()
		if rc is None or app is None:
			return

		def done(info: dict) -> None:
			key = _headers.makeKey(info["book"], info["sheet"])
			value = rc[0] if kind == "colHeaderRow" else rc[1]
			if _headers.get(key).get(kind) == value:
				_headers.set(key, kind, None)
				msg = _("Títulos de columna borrados") if kind == "colHeaderRow" else _("Títulos de fila borrados")
			else:
				_headers.set(key, kind, value)
				msg = _("La fila {n} contiene los títulos de columna").format(n=value) if kind == "colHeaderRow" else _("La columna {col} contiene los títulos de fila").format(col=_office.columnLetters(value))
			app.forgetSheetInfo()
			app.ensureSheetInfo(self)
			speech.speakMessage(msg)

		_office.callAsync(_excel.om_sheetInfo, hwnd, callback=done, onError=_fail)

	@script(description=_("Usa la fila actual como títulos de columna de la hoja (otra vez: los borra)"), category=CAT, gesture="kb:tiresias+control+alt+c")
	def script_setColumnHeaders(self, gesture) -> None:
		self._setHeader("colHeaderRow")

	@script(description=_("Usa la columna actual como títulos de fila de la hoja (otra vez: los borra)"), category=CAT, gesture="kb:tiresias+control+alt+r")
	def script_setRowHeaders(self, gesture) -> None:
		self._setHeader("rowHeaderCol")

	@script(description=_("Lee el título de la columna de la celda actual"), category=CAT, gesture="kb:tiresias+control+shift+c", speakOnDemand=True)
	def script_readColumnHeader(self, gesture) -> None:
		colH = self.headerTexts()[1]
		speech.speakText(colH) if colH else speech.speakMessage(_("Sin título de columna. Fíjalo con Tiresias+Control+Alt+C"))

	@script(description=_("Lee el título de la fila de la celda actual"), category=CAT, gesture="kb:tiresias+control+shift+f", speakOnDemand=True)
	def script_readRowHeader(self, gesture) -> None:
		rowH = self.headerTexts()[0]
		speech.speakText(rowH) if rowH else speech.speakMessage(_("Sin título de fila. Fíjalo con Tiresias+Control+Alt+R"))

	# ------------------------------------------------------------ fila o columna entera (#901, foros 3.4)
	def _readLine(self, kind: str) -> None:
		show = _repeat() == 1
		c = conf["officeExcel"]
		app = self.appModule
		info = app.sheetInfo(self._sheetKey()) if app is not None else None
		headers = (info or {}).get("headers") or {}

		def done(d: dict) -> None:
			if show:
				from .. import gui

				gui.showBrowseableMessage(_excel.lineViewerText(d), _excel.lineTitle(d))
				return
			speech.cancelSpeech()
			speech.speak(_excel.lineSpeech(d, bool(c["readLineHeaders"]), bool(c["reportCoordinates"])))

		_office.callAsync(
			_excel.om_lineCells,
			self._hwnd(),
			kind,
			c["readLineFrom"] == "start",
			bool(c["readLineSkipBlank"]),
			headers.get("colHeaderRow"),
			headers.get("rowHeaderCol"),
			callback=done,
			onError=_fail,
			timeout=6,
		)

	@script(description=_("Lee la fila de la celda actual con los títulos de columna (dos veces: la muestra en una ventana)"), category=CAT, gesture="kb:tiresias+control+alt+leftArrow", speakOnDemand=True)
	def script_readRow(self, gesture) -> None:
		self._readLine("row")

	@script(description=_("Lee la columna de la celda actual con los títulos de fila (dos veces: la muestra en una ventana)"), category=CAT, gesture="kb:tiresias+control+alt+upArrow", speakOnDemand=True)
	def script_readColumn(self, gesture) -> None:
		self._readLine("col")

	# ------------------------------------------------------------ visor de celdas (foros 3.4)
	@script(description=_("Muestra el contenido completo de la celda (varias líneas, fórmula, notas) en una ventana de solo lectura"), category=CAT, gesture="kb:tiresias+shift+v")
	def script_cellViewer(self, gesture) -> None:
		rowH, colH = self.headerTexts()

		def done(d: dict) -> None:
			from .. import gui

			gui.showBrowseableMessage(_excel.cellViewerText(d, rowH, colH), _("Celda {cell}").format(cell=d.get("address", "")))

		_office.callAsync(_excel.om_cellFull, self._hwnd(), callback=done, onError=_fail)

	# ------------------------------------------------------------ celdas vigiladas
	@script(description=_("Vigila la celda actual y avisa cuando cambie su valor (otra vez: deja de vigilarla)"), category=CAT, gesture="kb:tiresias+control+alt+w")
	def script_toggleWatchCell(self, gesture) -> None:
		app = self.appModule
		hwnd = self._hwnd()

		def done(ref: tuple) -> None:
			app.toggleWatch(hwnd, tuple(ref))

		_office.callAsync(_excel.om_activeCellRef, hwnd, callback=done, onError=_fail)

	# ------------------------------------------------------------ lista de elementos
	@script(description=_("Lista de elementos del libro: hojas, comentarios, notas, fórmulas, gráficos y rangos con nombre"), category=CAT, gesture="kb:tiresias+f7")
	def script_elementsList(self, gesture) -> None:
		hwnd = self._hwnd()
		root = winapi.getAncestor(hwnd, winapi.GA_ROOT)
		speech.speakMessage(_("Buscando elementos..."))

		def done(elements: dict) -> None:
			from ..gui import app_dialogs

			def provider(key: str):
				return lambda: list(elements.get(key, []))

			def go(payload) -> None:
				sheet, addr = payload

				def onCore() -> None:
					winapi.setForegroundWindow(root)
					_office.callAsync(_excel.om_select, hwnd, addr, sheet, callback=lambda t: speech.speakText(t), onError=_fail)

				queue_handler.callLater(200, onCore)

			categories = [(label, provider(key)) for key, label in _excel.ELEMENT_KINDS]
			app_dialogs.showItemList("excelElements", _("Lista de elementos de Excel"), categories, [app_dialogs.Action(_("&Ir"), go, default=True)])

		_office.callAsync(_excel.om_elements, hwnd, callback=done, onError=_fail, timeout=15)


for _g in SELECTION_GESTURES:
	from ..baseobject import normalizeGestureId as _norm

	ExcelCell._classGestures[_norm(_g)] = "announceSelection"  # type: ignore[attr-defined]


class AppModule(_chart.ChartNavigationMixin, BaseAppModule):
	def __init__(self, processID: int, appName: str | None = None) -> None:
		super().__init__(processID, appName)
		self._sheetInfo: dict[str, dict] = {}
		self._pendingSheet: set[str] = set()
		#: Celdas vigiladas: (libro, hoja, dirección) -> último valor.
		self.watched: dict[tuple[str, str, str], str | None] = {}
		self._watchHwnd = 0
		self._watchTimer: int | None = None
		#: Nombre del libro -> ruta completa (las celdas vigiladas se guardan por ruta).
		self._bookPaths: dict[str, str] = {}
		self._loadedBooks: set[str] = set()

	def terminate(self) -> None:
		if self._watchTimer is not None:
			queue_handler.cancelCallLater(self._watchTimer)
			self._watchTimer = None

	def chooseObjectClass(self, obj, clsList: list[type]) -> None:
		if isExcelCell(obj):
			clsList.insert(0, ExcelCell)

	# ------------------------------------------------------------ información de hojas
	def sheetInfo(self, key: str | None) -> dict | None:
		return self._sheetInfo.get(key) if key else None

	def forgetSheetInfo(self) -> None:
		self._sheetInfo.clear()

	def ensureSheetInfo(self, cell: ExcelCell) -> None:
		"""Pide (una vez por hoja) los títulos de la hoja al modelo de objetos."""
		key = cell._sheetKey()
		if not key or key in self._sheetInfo or key in self._pendingSheet:
			return
		self._pendingSheet.add(key)

		def done(info: dict) -> None:
			self._pendingSheet.discard(key)
			headers = dict(info.get("named") or {})
			headers.update(_headers.get(_headers.makeKey(info["book"], info["sheet"])))
			info["headers"] = headers
			self._sheetInfo[key] = info
			self.loadWatched(hwnd, info["bookName"], info["book"])

		def fail(e) -> None:
			self._pendingSheet.discard(key)

		hwnd = cell._hwnd()
		_office.callAsync(_excel.om_sheetInfo, hwnd, callback=done, onError=fail, timeout=2)

	# ------------------------------------------------------------ celdas vigiladas
	def loadWatched(self, hwnd: int, bookName: str, bookPath: str) -> None:
		"""Recupera las celdas vigiladas guardadas de un libro (una vez por libro)."""
		self._bookPaths[bookName] = bookPath
		if bookPath in self._loadedBooks:
			return
		self._loadedBooks.add(bookPath)
		saved = _watched.cells(bookPath)
		if not saved:
			return
		for sheet, addr in saved:
			self.watched.setdefault((bookName, sheet, addr), None)
		self._watchHwnd = hwnd
		self._scheduleWatch()

	def toggleWatch(self, hwnd: int, ref: tuple) -> None:
		bookName, sheet, addr = ref[0], ref[1], ref[2]
		if len(ref) > 3 and ref[3]:
			self._bookPaths[bookName] = ref[3]
		path = self._bookPaths.get(bookName, "")
		key = (bookName, sheet, addr)
		if key in self.watched:
			del self.watched[key]
			if path:
				_watched.remove(path, sheet, addr)
			speech.speakMessage(_("Ya no se vigila {cell}").format(cell=addr))
		else:
			self.watched[key] = None
			self._watchHwnd = hwnd
			if isSavedBook(path):
				# Solo se guardan los libros que ya tienen archivo (o están en la nube).
				_watched.add(path, sheet, addr)
			speech.speakMessage(_("Se vigila {cell} de la hoja {sheet}").format(cell=addr, sheet=sheet))
		self._scheduleWatch()

	def _scheduleWatch(self) -> None:
		if self._watchTimer is not None:
			queue_handler.cancelCallLater(self._watchTimer)
			self._watchTimer = None
		if self.watched:
			interval = max(250, int(conf["officeExcel"]["watchedCellsInterval"]))
			self._watchTimer = queue_handler.callLater(interval, self._pollWatched)

	def _pollWatched(self) -> None:
		self._watchTimer = None
		if not self.watched or not self.isAlive or not winapi.user32.IsWindow(self._watchHwnd):
			return

		def done(values: dict) -> None:
			for ref, val in values.items():
				if ref not in self.watched:
					continue
				old = self.watched[ref]
				self.watched[ref] = val
				if old is not None and val is not None and val != old:
					speech.speakMessage(_("{cell} cambió a {value}").format(cell=ref[2], value=val or _("en blanco")))
			self._scheduleWatch()

		_office.callAsync(_excel.om_watchedValues, self._watchHwnd, list(self.watched), callback=done, onError=lambda e: self._scheduleWatch(), timeout=1.5)

	@script(description=_("Lista de celdas vigiladas para ir a una o dejar de vigilarla"), category=CAT, gesture="kb:tiresias+alt+w")
	def script_watchedCellsList(self, gesture) -> None:
		from ..gui import app_dialogs

		if not self.watched:
			speech.speakMessage(_("No hay celdas vigiladas. Usa Tiresias+Control+Alt+W en una celda"))
			return
		hwnd = self._watchHwnd

		def provider():
			# Copia: el núcleo puede cambiar la lista mientras la lee la interfaz.
			return [(f"{s} {a}: {v if v is not None else '?'}", (b, s, a)) for (b, s, a), v in list(self.watched.items())]

		def go(ref) -> None:
			root = winapi.getAncestor(hwnd, winapi.GA_ROOT)

			def onCore() -> None:
				winapi.setForegroundWindow(root)
				_office.callAsync(_excel.om_select, hwnd, ref[2], ref[1], callback=lambda t: speech.speakText(t), onError=_fail)

			queue_handler.callLater(200, onCore)

		def remove(ref) -> None:
			queue_handler.queueFunction(self.toggleWatch, hwnd, ref)

		app_dialogs.showItemList("excelWatched", _("Celdas vigiladas"), [(_("Celdas"), provider)], [app_dialogs.Action(_("&Ir"), go, default=True), app_dialogs.Action(_("&Dejar de vigilar"), remove)])

	@script(description=_("Recorre el gráfico seleccionado con las flechas (dos veces: lo muestra entero)"), category=CAT, gesture="kb:tiresias+alt+g")
	def script_describeChart(self, gesture) -> None:
		from .. import api

		focus = api.getFocusObject()
		hwnd = _office.windowForObject(focus, "EXCEL7") if focus is not None else 0
		self.openChart(_chart.om_excelChart, hwnd)
