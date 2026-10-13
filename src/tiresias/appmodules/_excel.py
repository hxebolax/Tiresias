"""Consultas al modelo de objetos de Microsoft Excel.

Las funciones ``om_*`` reciben la ventana de la hoja (clase ``EXCEL7``), se
ejecutan en el hilo de Office con tiempo máximo y devuelven datos de Python.
Las demás son de presentación y se pueden probar sin Excel.
"""

from __future__ import annotations

import time
from typing import Any

from ..i18n import _
from . import _office

#: Límite de celdas que se recorren (lectura continua, fórmulas...).
MAX_CELLS = 5000
#: Valores de error de Excel (CVErr) que comtypes devuelve como enteros.
_CVERR = {-2146826281: "#¡DIV/0!", -2146826246: "#N/A", -2146826259: "#¿NOMBRE?", -2146826288: "#¡NULO!", -2146826252: "#¡NUM!", -2146826265: "#¡REF!", -2146826273: "#¡VALOR!"}


def _window(hwnd: int):
	return _office.nativeOMFromWindow(hwnd)


def _app(hwnd: int):
	return _window(hwnd).Application


def _str(v: Any) -> str:
	if v is None:
		return ""
	if isinstance(v, float) and v.is_integer():
		return str(int(v))
	return str(v)


# ================================================================ hoja y celda
def om_sheetInfo(hwnd: int) -> dict:
	"""Libro, hoja, protección y títulos de fila y columna de la hoja activa."""
	w = _window(hwnd)
	sheet = w.ActiveSheet
	book = sheet.Parent
	out: dict = {"book": book.FullName, "bookName": book.Name, "sheet": sheet.Name, "protected": False, "named": {}}
	try:
		out["protected"] = bool(sheet.ProtectContents)
	except Exception:
		pass
	# Rangos con nombre «ColumnTitle»/«RowTitle» (convención de otros lectores).
	try:
		names = book.Names
		for i in range(1, min(int(names.Count), 500) + 1):
			n = names.Item(i)
			base = n.Name.split("!")[-1].lower()
			if base.startswith("columntitle") or base.startswith("rowtitle") or base.startswith("titulocolumna") or base.startswith("titulofila"):
				try:
					rng = n.RefersToRange
					if rng.Worksheet.Name != sheet.Name:
						continue
					if base.startswith(("columntitle", "titulocolumna")):
						out["named"]["colHeaderRow"] = int(rng.Row)
					else:
						out["named"]["rowHeaderCol"] = int(rng.Column)
				except Exception:
					continue
	except Exception:
		pass
	return out


def om_cellDetails(hwnd: int) -> dict:
	"""Fórmula, comentario, nota, celdas combinadas y validación de la celda activa."""
	w = _window(hwnd)
	cell = w.Application.ActiveCell
	out: dict = {"address": cell.Address(False, False)}
	try:
		if cell.HasFormula:
			out["formula"] = cell.FormulaLocal
	except Exception:
		pass
	try:
		if cell.MergeCells:
			out["merged"] = cell.MergeArea.Address(False, False)
	except Exception:
		pass
	try:
		note = cell.Comment
		if note is not None:
			out["note"] = (note.Text() or "").strip()
	except Exception:
		pass
	try:
		ct = cell.CommentThreaded
		if ct is not None:
			out["comment"] = _threaded(ct)
	except Exception:
		pass
	try:
		v = cell.Validation
		msg = v.InputMessage
		if msg:
			title = v.InputTitle or ""
			out["validation"] = f"{title}: {msg}" if title else msg
	except Exception:
		pass
	try:
		if cell.WrapText is True:
			out["wrapped"] = True
	except Exception:
		pass
	try:
		if cell.EntireRow.Hidden or cell.EntireColumn.Hidden:
			out["hidden"] = True
	except Exception:
		pass
	try:
		if cell.Hyperlinks.Count:
			out["link"] = cell.Hyperlinks.Item(1).Address or ""
	except Exception:
		pass
	# Colores de la letra y del relleno (opción «Colores», con valores RGB o
	# hexadecimales según colorFormat, #8674). xlAutomatic = -4105, xlNone = -4142.
	try:
		from ..config import conf

		if conf["documentFormatting"]["reportColor"]:
			if int(cell.Font.ColorIndex) != -4105:
				out["fontColor"] = int(cell.Font.Color)
			if int(cell.Interior.ColorIndex) != -4142:
				out["fillColor"] = int(cell.Interior.Color)
	except Exception:
		pass
	return out


def _threaded(ct) -> dict:
	d: dict = {"author": "", "text": "", "resolved": False, "replies": []}
	try:
		d["author"] = ct.Author.Name
	except Exception:
		pass
	try:
		d["text"] = ct.Text() or ""
	except Exception:
		pass
	try:
		d["resolved"] = bool(ct.Resolved)
	except Exception:
		pass
	try:
		replies = ct.Replies
		for i in range(1, int(replies.Count) + 1):
			r = replies.Item(i)
			d["replies"].append({"author": r.Author.Name, "text": r.Text() or ""})
	except Exception:
		pass
	return d


def detailsText(d: dict, full: bool = False) -> list[str]:
	"""Avisos breves (al moverse) o completos (al pedirlos) de una celda."""
	out: list[str] = []
	if d.get("merged"):
		out.append(_("combinada {range}").format(range=d["merged"]))
	if d.get("formula"):
		out.append(_("fórmula {f}").format(f=d["formula"]) if full else _("tiene fórmula"))
	if d.get("comment"):
		out.append(threadedText(d["comment"]) if full else _("tiene comentario"))
	if d.get("note"):
		out.append(_("nota: {text}").format(text=d["note"]) if full else _("tiene nota"))
	if d.get("validation"):
		out.append(d["validation"])
	if d.get("wrapped"):
		out.append(_("texto ajustado"))
	if d.get("hidden"):
		out.append(_("oculta"))
	if d.get("link"):
		out.append(_("enlace a {url}").format(url=d["link"]) if full else _("enlace"))
	if "fontColor" in d or "fillColor" in d:
		from . import _office

		if "fontColor" in d:
			name = _office.colorName(d["fontColor"])
			if name:
				out.append(_("color {name}").format(name=name))
		if "fillColor" in d:
			name = _office.colorName(d["fillColor"])
			if name:
				out.append(_("relleno {name}").format(name=name))
	return out


def threadedText(c: dict) -> str:
	head = _("Comentario de {author}").format(author=c["author"]) if c.get("author") else _("Comentario")
	if c.get("resolved"):
		head += ", " + _("resuelto")
	parts = [f"{head}: {c.get('text', '')}"]
	for r in c.get("replies") or []:
		parts.append(_("Respuesta de {author}: {text}").format(author=r.get("author") or _("alguien"), text=r.get("text", "")))
	return ". ".join(parts)


def om_comment(hwnd: int) -> dict:
	d = om_cellDetails(hwnd)
	return {k: d[k] for k in ("address", "comment", "note") if k in d}


def om_formula(hwnd: int) -> dict:
	cell = _app(hwnd).ActiveCell
	out = {"address": cell.Address(False, False), "formula": "", "value": ""}
	try:
		if cell.HasFormula:
			out["formula"] = cell.FormulaLocal
	except Exception:
		pass
	try:
		out["value"] = cell.Text
	except Exception:
		pass
	return out


# ================================================================ selección
def om_selection(hwnd: int, delay: float = 0.0) -> dict:
	if delay:
		time.sleep(delay)
	sel = _app(hwnd).Selection
	out: dict = {"address": "", "count": 0, "rows": 0, "cols": 0}
	try:
		out["address"] = sel.Address(False, False)
		out["rows"] = int(sel.Rows.Count)
		out["cols"] = int(sel.Columns.Count)
		out["count"] = int(sel.CountLarge)
	except Exception:
		pass
	return out


def selectionText(d: dict) -> str:
	if not d.get("address"):
		return _("sin selección")
	addr = d["address"].replace(":", _(" a "))
	if d.get("count", 0) <= 1:
		return _("{addr} seleccionada").format(addr=addr)
	if d["rows"] >= 1048576:
		return _("columnas {addr} seleccionadas").format(addr=addr)
	if d["cols"] >= 16384:
		return _("filas {addr} seleccionadas").format(addr=addr)
	return _("{addr} seleccionado, {n} celdas").format(addr=addr, n=d["count"])


# ================================================================ lectura continua
def om_cellsFromActive(hwnd: int) -> list[tuple[str, str]]:
	"""Celdas no vacías desde la celda activa hasta el final de la hoja (#6624)."""
	app = _app(hwnd)
	sheet = app.ActiveSheet
	cell = app.ActiveCell
	used = sheet.UsedRange
	lastRow = int(used.Row) + int(used.Rows.Count) - 1
	lastCol = int(used.Column) + int(used.Columns.Count) - 1
	firstCol = int(used.Column)
	row, col = int(cell.Row), int(cell.Column)
	if row > lastRow:
		return []
	out: list[tuple[str, str]] = []
	# ``Value2`` da los números sin formato: las fechas como número de serie
	# (45292), los decimales con punto y los importes sin moneda. Se pide el
	# texto que muestra Excel a cada celda que no es texto, con un tiempo máximo
	# para no agotar el de la llamada en hojas enormes.
	deadline = time.monotonic() + SHOWN_TEXT_BUDGET
	# Rev. 10.11: se lee por bloques de filas hasta tener MAX_CELLS celdas. Antes
	# se pedía de una vez todo el rango usado (con columnas formateadas enteras,
	# un millón de filas): Excel se congelaba y la memoria se disparaba.
	readLimit = time.monotonic() + READ_BUDGET
	start = row
	while start <= lastRow and time.monotonic() < readLimit:
		end = min(lastRow, start + READ_BLOCK_ROWS - 1)
		values = sheet.Range(sheet.Cells(start, firstCol), sheet.Cells(end, lastCol)).Value2
		if not isinstance(values, tuple):
			values = ((values,),)
		for ri, rowVals in enumerate(values):
			r = start + ri
			for ci, v in enumerate(rowVals):
				c = firstCol + ci
				if r == row and c < col:
					continue
				if v is None or v == "":
					continue
				if isinstance(v, str):
					text = v
				elif time.monotonic() < deadline:
					text = _shownText(sheet, r, c, v)
				else:
					text = _cellText(v)
				out.append((_office.cellAddress(r, c), text))
				if len(out) >= MAX_CELLS:
					return out
		start = end + 1
	return out


#: Filas que se piden a Excel de una vez en la lectura continua.
READ_BLOCK_ROWS = 200
#: Segundos como mucho leyendo bloques (hojas casi vacías con rango usado enorme).
READ_BUDGET = 4.0


#: Segundos como mucho para pedir el texto mostrado de las celdas en la lectura continua.
SHOWN_TEXT_BUDGET = 3.0


def _shownText(sheet, r: int, c: int, v: Any) -> str:
	"""Texto que muestra Excel en la celda (con su formato); si no cabe («###»), el valor."""
	try:
		text = sheet.Cells(r, c).Text
	except Exception:
		text = ""
	if not text or set(str(text)) == {"#"}:
		return _cellText(v)
	return str(text)


def om_select(hwnd: int, address: str, sheet: str | None = None) -> str:
	app = _app(hwnd)
	if sheet:
		ws = app.ActiveWorkbook.Worksheets(sheet)
		ws.Activate()
	else:
		ws = app.ActiveSheet
	rng = ws.Range(address)
	rng.Select()
	try:
		return f"{rng.Address(False, False)} {rng.Cells(1, 1).Text}".strip()
	except Exception:
		return address


# ================================================================ lista de elementos
def om_elements(hwnd: int) -> dict[str, list[tuple[str, tuple[str, str]]]]:
	"""{tipo: [(texto, (hoja, dirección))]}."""
	app = _app(hwnd)
	book = app.ActiveWorkbook
	active = app.ActiveSheet
	out: dict[str, list] = {"sheets": [], "comments": [], "notes": [], "formulas": [], "charts": [], "names": []}
	sheets = book.Worksheets
	for i in range(1, int(sheets.Count) + 1):
		ws = sheets.Item(i)
		label = ws.Name
		try:
			if int(ws.Visible) != -1:
				label += " " + _("(oculta)")
		except Exception:
			pass
		try:
			if ws.ProtectContents:
				label += " " + _("(protegida)")
		except Exception:
			pass
		out["sheets"].append((label, (ws.Name, "A1")))
	ws = active
	try:
		notes = ws.Comments
		for i in range(1, min(int(notes.Count), 1000) + 1):
			n = notes.Item(i)
			addr = n.Parent.Address(False, False)
			out["notes"].append((f"{addr}: {(n.Text() or '').strip()}", (ws.Name, addr)))
	except Exception:
		pass
	try:
		cts = ws.CommentsThreaded
		for i in range(1, min(int(cts.Count), 1000) + 1):
			c = cts.Item(i)
			addr = c.Parent.Address(False, False)
			out["comments"].append((f"{addr}: {threadedText(_threaded(c))}", (ws.Name, addr)))
	except Exception:
		pass
	try:
		formulas = ws.UsedRange.SpecialCells(-4123)  # xlCellTypeFormulas
		count = 0
		for area in _iter(formulas.Areas):
			for cell in _iter(area.Cells):
				addr = cell.Address(False, False)
				out["formulas"].append((f"{addr}: {cell.FormulaLocal} = {cell.Text}", (ws.Name, addr)))
				count += 1
				if count >= 1000:
					break
			if count >= 1000:
				break
	except Exception:
		pass
	try:
		charts = ws.ChartObjects()
		for i in range(1, int(charts.Count) + 1):
			ch = charts.Item(i)
			title = ""
			try:
				if ch.Chart.HasTitle:
					title = ch.Chart.ChartTitle.Text
			except Exception:
				pass
			addr = ch.TopLeftCell.Address(False, False)
			out["charts"].append((f"{ch.Name}: {title} ({addr})".replace(":  (", " ("), (ws.Name, addr)))
	except Exception:
		pass
	try:
		names = book.Names
		for i in range(1, min(int(names.Count), 500) + 1):
			n = names.Item(i)
			try:
				rng = n.RefersToRange
				out["names"].append((f"{n.Name}: {rng.Address(False, False)}", (rng.Worksheet.Name, rng.Address(False, False))))
			except Exception:
				continue
	except Exception:
		pass
	return out


def _iter(coll):
	for i in range(1, int(coll.Count) + 1):
		yield coll.Item(i)


ELEMENT_KINDS = [
	("sheets", _("Hojas")),
	("comments", _("Comentarios")),
	("notes", _("Notas")),
	("formulas", _("Fórmulas")),
	("charts", _("Gráficos")),
	("names", _("Rangos con nombre")),
]


# ================================================================ celdas vigiladas
def om_watchedValues(hwnd: int, cells: list[tuple[str, str, str]]) -> dict[tuple[str, str, str], str]:
	"""Valores (texto mostrado) de celdas vigiladas ``(libro, hoja, dirección)``."""
	app = _app(hwnd)
	out = {}
	for book, sheet, addr in cells:
		try:
			wb = app.Workbooks(book)
			out[(book, sheet, addr)] = wb.Worksheets(sheet).Range(addr).Text
		except Exception:
			out[(book, sheet, addr)] = None
	return out


def om_activeCellRef(hwnd: int) -> tuple[str, str, str, str]:
	"""(nombre del libro, hoja, dirección, ruta completa del libro) de la celda activa."""
	app = _app(hwnd)
	cell = app.ActiveCell
	book = cell.Worksheet.Parent
	return (book.Name, cell.Worksheet.Name, cell.Address(False, False), book.FullName)


# ================================================================ fila o columna entera (NVDA #901, foros 3.4)
#: Límite de celdas que se leen de una fila o columna.
MAX_LINE_CELLS = 1000


def _cellText(v: Any) -> str:
	"""Texto de un valor de ``Value2`` (errores de Excel incluidos)."""
	if isinstance(v, int) and v < -2146820000 and v in _CVERR:
		return _CVERR[v]
	return _str(v)


def om_lineCells(hwnd: int, kind: str, fromStart: bool, skipBlank: bool, headerRow: int | None, headerCol: int | None) -> dict:
	"""Celdas de la fila (``kind="row"``) o la columna (``"col"``) de la celda activa.

	Devuelve ``{"kind", "row", "col", "items": [(dirección, título, texto)]}``.
	El texto es el que muestra Excel; el título, el de la fila o columna de
	títulos fijada (si la hay y no es la propia línea).
	"""
	app = _app(hwnd)
	sheet = app.ActiveSheet
	cell = app.ActiveCell
	row, col = int(cell.Row), int(cell.Column)
	used = sheet.UsedRange
	firstRow, firstCol = int(used.Row), int(used.Column)
	lastRow = firstRow + int(used.Rows.Count) - 1
	lastCol = firstCol + int(used.Columns.Count) - 1
	out: dict = {"kind": kind, "row": row, "col": col, "items": []}
	if kind == "row":
		start = min(firstCol, col) if fromStart else col
		end = max(lastCol, col)
		end = min(end, start + MAX_LINE_CELLS - 1)
		rng = sheet.Range(sheet.Cells(row, start), sheet.Cells(row, end))
	else:
		start = min(firstRow, row) if fromStart else row
		end = max(lastRow, row)
		end = min(end, start + MAX_LINE_CELLS - 1)
		rng = sheet.Range(sheet.Cells(start, col), sheet.Cells(end, col))
	values = rng.Value2
	if not isinstance(values, tuple):
		values = ((values,),)
	flat = [r[0] for r in values] if kind == "col" else list(values[0])
	for i, v in enumerate(flat):
		r, c = (row, start + i) if kind == "row" else (start + i, col)
		empty = v is None or v == ""
		if empty and skipBlank:
			continue
		text = ""
		if not empty:
			try:
				text = sheet.Cells(r, c).Text
			except Exception:
				text = _cellText(v)
			if not text or set(text) == {"#"}:
				# Columna demasiado estrecha («####»): se usa el valor.
				text = _cellText(v)
		title = ""
		try:
			if kind == "row" and headerRow and headerRow != row:
				title = sheet.Cells(headerRow, c).Text or ""
			elif kind == "col" and headerCol and headerCol != col:
				title = sheet.Cells(r, headerCol).Text or ""
		except Exception:
			title = ""
		out["items"].append((_office.cellAddress(r, c), title, text))
	return out


def lineLabel(d: dict) -> str:
	if d.get("kind") == "row":
		return _("fila {n}").format(n=d.get("row"))
	return _("columna {col}").format(col=_office.columnLetters(int(d.get("col") or 1)))


def lineTitle(d: dict) -> str:
	"""«Fila 3» o «Columna B» (título de la ventana)."""
	label = lineLabel(d)
	return label[:1].upper() + label[1:]


def lineSpeech(d: dict, withTitles: bool, withCoordinates: bool) -> list[str]:
	"""Una cadena por celda: «título, valor» o «valor, dirección»."""
	items = d.get("items") or []
	if not items:
		return [_("{line} vacía").format(line=lineLabel(d))]
	out: list[str] = []
	for addr, title, text in items:
		value = text if text else _("en blanco")
		if withTitles and title:
			out.append(f"{title}, {value}")
		elif withCoordinates:
			out.append(f"{value}, {addr}")
		else:
			out.append(value)
	return out


def lineViewerText(d: dict) -> str:
	"""La fila o columna como texto para la ventana navegable (una celda por línea)."""
	lines = [lineTitle(d)]
	for addr, title, text in d.get("items") or []:
		value = (text or _("en blanco")).replace("\n", " / ")
		lines.append(f"{addr}  {title}: {value}" if title else f"{addr}  {value}")
	return "\n".join(lines)


# ================================================================ visor de la celda (foros 3.4)
def om_cellFull(hwnd: int) -> dict:
	"""Contenido completo de la celda activa para el visor de celdas multilínea."""
	app = _app(hwnd)
	cell = app.ActiveCell
	out: dict = {"address": cell.Address(False, False), "sheet": "", "content": "", "shown": "", "formula": ""}
	try:
		out["sheet"] = cell.Worksheet.Name
	except Exception:
		pass
	try:
		out["shown"] = cell.Text or ""
	except Exception:
		pass
	hasFormula = False
	try:
		hasFormula = bool(cell.HasFormula)
	except Exception:
		pass
	if hasFormula:
		try:
			out["formula"] = cell.FormulaLocal or ""
		except Exception:
			pass
		try:
			out["content"] = _cellText(cell.Value2)
		except Exception:
			pass
	else:
		try:
			# Lo que escribió el usuario, con sus saltos de línea y en formato local.
			out["content"] = cell.FormulaLocal or ""
		except Exception:
			try:
				out["content"] = _cellText(cell.Value2)
			except Exception:
				pass
	try:
		d = om_cellDetails(hwnd)
		for k in ("note", "comment", "validation", "link", "merged"):
			if d.get(k):
				out[k] = d[k]
	except Exception:
		pass
	return out


def cellViewerText(d: dict, rowTitle: str = "", colTitle: str = "") -> str:
	"""Texto del visor de celdas: dirección, títulos, contenido completo y fórmula."""
	head = _("Celda {cell}").format(cell=d.get("address", ""))
	if d.get("sheet"):
		head += " " + _("de la hoja {sheet}").format(sheet=d["sheet"])
	lines = [head]
	if colTitle:
		lines.append(_("Título de columna: {text}").format(text=colTitle))
	if rowTitle:
		lines.append(_("Título de fila: {text}").format(text=rowTitle))
	lines.append("")
	content = (d.get("content") or "").replace("\r\n", "\n").replace("\r", "\n")
	lines.append(_("Contenido:"))
	lines.append(content if content else _("(en blanco)"))
	shown = d.get("shown") or ""
	if shown and shown != content and set(shown) != {"#"}:
		lines.append("")
		lines.append(_("Valor mostrado: {text}").format(text=shown))
	if d.get("formula"):
		lines.append("")
		lines.append(_("Fórmula: {f}").format(f=d["formula"]))
	if d.get("merged"):
		lines.append(_("Celda combinada: {range}").format(range=d["merged"]))
	if d.get("note"):
		lines.append("")
		lines.append(_("Nota: {text}").format(text=d["note"]))
	if d.get("comment"):
		lines.append("")
		lines.append(threadedText(d["comment"]))
	if d.get("validation"):
		lines.append("")
		lines.append(_("Mensaje de validación: {text}").format(text=d["validation"]))
	if d.get("link"):
		lines.append(_("Enlace: {url}").format(url=d["link"]))
	return "\n".join(lines)
