"""Consultas al modelo de objetos de Microsoft Word.

Todas las funciones ``om_*`` reciben el identificador de la ventana del
documento (clase ``_WwG``) y se ejecutan en el hilo de Office (con
:func:`tiresias.appmodules._office.callAsync`). Devuelven datos de Python
sencillos (cadenas, números, listas y diccionarios), nunca objetos COM, para
que el resto del módulo no dependa de Office ni pueda bloquearse.

Las funciones sin prefijo ``om_`` son de presentación (texto para el
usuario) y se pueden probar sin Word.
"""

from __future__ import annotations

import datetime
from typing import Any

from ..i18n import _
from . import _office

# Constantes de Word (WdInformation y otras).
wdActiveEndAdjustedPageNumber = 1
wdActiveEndSectionNumber = 2
wdActiveEndPageNumber = 3
wdNumberOfPagesInDocument = 4
wdFirstCharacterColumnNumber = 9
wdFirstCharacterLineNumber = 10
wdWithInTable = 12
wdStartOfRangeRowNumber = 13
wdMaximumNumberOfRows = 15
wdStartOfRangeColumnNumber = 16
wdMaximumNumberOfColumns = 18

#: Límites para no recorrer documentos enormes.
MAX_ITEMS = 2000

REVISION_TYPES = {
	1: _("inserción"),
	2: _("eliminación"),
	3: _("cambio de formato"),
	4: _("cambio de numeración"),
	5: _("cambio de campo"),
	6: _("revisión reconciliada"),
	7: _("conflicto"),
	8: _("cambio de estilo"),
	9: _("reemplazo"),
	10: _("cambio de formato de párrafo"),
	11: _("cambio de formato de tabla"),
	12: _("cambio de formato de sección"),
	13: _("cambio de definición de estilo"),
	14: _("movido desde"),
	15: _("movido a"),
	16: _("celda insertada"),
	17: _("celda eliminada"),
	18: _("celdas combinadas"),
}

ALIGNMENTS = {
	0: _("alineado a la izquierda"),
	1: _("centrado"),
	2: _("alineado a la derecha"),
	3: _("justificado"),
	4: _("distribuido"),
	5: _("justificado"),
	7: _("justificado"),
	8: _("justificado"),
	# wdAlignParagraphThaiJustify: una justificación, no la alineación a la izquierda.
	9: _("justificado"),
}

LINE_SPACING = {
	0: _("interlineado sencillo"),
	1: _("interlineado de 1,5 líneas"),
	2: _("interlineado doble"),
}


# ================================================================ acceso
def _window(hwnd: int):
	return _office.nativeOMFromWindow(hwnd)


def _doc(hwnd: int):
	return _window(hwnd).Document


def _sel(hwnd: int):
	return _window(hwnd).Application.Selection


def _text(rng) -> str:
	try:
		t = rng.Text or ""
	except Exception:
		return ""
	return clean(t)


def clean(text: str) -> str:
	"""Quita los caracteres de control de Word (fin de celda, de párrafo...)."""
	if not text:
		return ""
	for ch in ("\x07", "\x0e", "\x02", "\x05", "\x01", "\x13", "\x14", "\x15"):
		text = text.replace(ch, "")
	for ch in ("\r", "\n", "\x0b", "\x0c", "\t"):
		text = text.replace(ch, " ")
	return " ".join(text.split())


def formatDate(value: Any) -> str:
	if isinstance(value, datetime.datetime):
		return value.strftime("%d/%m/%Y %H:%M")
	if isinstance(value, datetime.date):
		return value.strftime("%d/%m/%Y")
	return str(value) if value else ""


# ================================================================ posición
def om_position(hwnd: int) -> dict:
	sel = _sel(hwnd)
	info = sel.Information
	out = {
		"page": int(info(wdActiveEndAdjustedPageNumber)),
		"pages": int(info(wdNumberOfPagesInDocument)),
		"line": int(info(wdFirstCharacterLineNumber)),
		"column": int(info(wdFirstCharacterColumnNumber)),
		"section": int(info(wdActiveEndSectionNumber)),
		"sections": 0,
	}
	try:
		out["sections"] = int(sel.Document.Sections.Count)
	except Exception:
		pass
	return out


def positionText(p: dict) -> str:
	parts = [_("página {page} de {pages}").format(page=p["page"], pages=p["pages"])]
	if p.get("sections", 0) > 1:
		parts.append(_("sección {n}").format(n=p["section"]))
	parts.append(_("línea {n}").format(n=p["line"]))
	parts.append(_("columna {n}").format(n=p["column"]))
	return ", ".join(parts)


# ================================================================ datos de la línea
def om_lineInfo(hwnd: int) -> dict:
	"""Página, tabla, lista, comentarios y revisiones de la línea del cursor."""
	sel = _sel(hwnd)
	info = sel.Information
	out: dict = {"page": int(info(wdActiveEndAdjustedPageNumber)), "inTable": bool(info(wdWithInTable))}
	if out["inTable"]:
		try:
			out["row"] = int(info(wdStartOfRangeRowNumber))
			out["col"] = int(info(wdStartOfRangeColumnNumber))
			tbl = sel.Tables(1)
			out["rows"] = int(tbl.Rows.Count)
			out["cols"] = int(tbl.Columns.Count)
			out["tableStart"] = int(tbl.Range.Start)
		except Exception:
			out["inTable"] = False
	_listData(sel.Paragraphs(1), out)
	try:
		line = sel.Bookmarks("\\Line").Range
		comments = line.Comments
		out["comments"] = sum(1 for i in range(1, min(int(comments.Count), 50) + 1) if not _isReply(comments.Item(i)))
		out["revisions"] = int(line.Revisions.Count)
		out["footnotes"] = int(line.Footnotes.Count)
	except Exception:
		out["comments"] = out["revisions"] = out["footnotes"] = 0
	return out


def listPrefix(info: dict) -> str:
	"""Texto previo a la línea de un elemento de lista (NVDA #7742)."""
	if not info.get("listType"):
		return ""
	marker = info.get("listString") or ""
	level = info.get("listLevel") or 1
	# Las viñetas suelen ser símbolos de fuentes privadas: se dice «viñeta».
	if marker and (len(marker) == 1 and not marker.isalnum()):
		marker = _("viñeta")
	text = _("elemento de lista {marker}").format(marker=marker).strip()
	if level > 1:
		text += " " + _("nivel {n}").format(n=level)
	return text


def lineSuffix(info: dict, reportComments: bool, reportRevisions: bool | None = None) -> list[str]:
	"""Avisos de la línea: comentarios y notas al pie (``reportComments``) y
	revisiones (``reportRevisions``; si no se indica, lo mismo que ``reportComments``)."""
	if reportRevisions is None:
		reportRevisions = reportComments
	out: list[str] = []
	if reportComments and info.get("comments"):
		out.append(_("con comentario") if info["comments"] == 1 else _("con {n} comentarios").format(n=info["comments"]))
	if reportRevisions and info.get("revisions"):
		out.append(_("con revisión") if info["revisions"] == 1 else _("con {n} revisiones").format(n=info["revisions"]))
	if reportComments and info.get("footnotes"):
		out.append(_("con nota al pie"))
	return out


# ================================================================ listas (NVDA #7742, foros 3.3)
#: Párrafos que se recorren como mucho al buscar el siguiente elemento de lista.
MAX_LIST_SCAN = 5000


def _listData(para, out: dict) -> None:
	"""Añade a ``out`` la lista del párrafo: tipo, marca, nivel, inicio y elementos.

	``listStart`` (inicio de la lista completa) identifica la lista para saber
	cuándo se entra en otra o se sale de ella.
	"""
	try:
		lf = para.Range.ListFormat
		out["listType"] = int(lf.ListType)
		out["listString"] = lf.ListString or ""
		out["listLevel"] = int(lf.ListLevelNumber)
	except Exception:
		out["listType"] = 0
		return
	if not out["listType"]:
		return
	try:
		lst = lf.List
		out["listStart"] = int(lst.Range.Start)
		out["listCount"] = int(lst.ListParagraphs.Count)
	except Exception:
		pass


def om_listInfo(hwnd: int) -> dict:
	"""Datos de lista del párrafo del cursor (para moverse por párrafos)."""
	out: dict = {}
	_listData(_sel(hwnd).Paragraphs(1), out)
	return out


def listTransition(lastListStart: int | None, info: dict) -> tuple[list[str], int | None]:
	"""Avisos al moverse: entrada en una lista, salida y prefijo del elemento.

	Devuelve ``(avisos, nuevo inicio de lista)``; el inicio se guarda para la
	siguiente llamada (``None`` fuera de las listas).
	"""
	parts: list[str] = []
	start = info.get("listStart") if info.get("listType") else None
	if info.get("listType") and start is None:
		# Word no dio el inicio: se trata como la misma lista para no repetir avisos.
		start = lastListStart if lastListStart is not None else -1
	if start != lastListStart:
		if start is not None:
			count = info.get("listCount")
			if count:
				parts.append(_("lista con {n} elementos").format(n=count) if count != 1 else _("lista con 1 elemento"))
			else:
				parts.append(_("lista"))
		elif lastListStart is not None:
			parts.append(_("fuera de lista"))
	prefix = listPrefix(info)
	if prefix:
		parts.append(prefix)
	return parts, start


def _paraListStart(para) -> int | None:
	try:
		lf = para.Range.ListFormat
		if not int(lf.ListType):
			return None
		return int(lf.List.Range.Start)
	except Exception:
		return None


def om_listItemMove(hwnd: int, where: str) -> dict:
	"""Lleva el cursor a otro elemento de lista: ``next``, ``previous``, ``first`` o ``last``.

	Dentro de una lista se recorre solo esa lista; fuera de ella, ``next`` y
	``previous`` buscan el elemento más cercano de cualquier lista. Devuelve
	``{"moved": bool, "reason": "notInList"|"end"|"start"|"none", ...datos}``.
	"""
	w = _window(hwnd)
	sel = w.Application.Selection
	doc = sel.Document
	para = sel.Paragraphs(1)
	current = _paraListStart(para)
	target = None
	if where in ("first", "last"):
		if current is None:
			return {"moved": False, "reason": "notInList"}
		paras = para.Range.ListFormat.List.Range.Paragraphs
		p = paras.First if where == "first" else paras.Last
		step = "Next" if where == "first" else "Previous"
		for _i in range(MAX_LIST_SCAN):
			if p is None:
				break
			if _paraListStart(p) == current:
				target = p
				break
			p = getattr(p, step)()
	else:
		step = "Next" if where == "next" else "Previous"
		p = para
		for _i in range(MAX_LIST_SCAN):
			try:
				p = getattr(p, step)()
			except Exception:
				p = None
			if p is None:
				break
			start = _paraListStart(p)
			if current is not None:
				if start == current:
					target = p
					break
				if start is None:
					# Un párrafo normal dentro de la lista se salta; fuera de su rango, se acaba.
					try:
						lr = para.Range.ListFormat.List.Range
						if int(p.Range.Start) >= int(lr.End) or int(p.Range.End) <= int(lr.Start):
							break
					except Exception:
						break
				elif start != current:
					break
			elif start is not None:
				target = p
				break
	if target is None:
		if current is None and where in ("next", "previous"):
			return {"moved": False, "reason": "none"}
		return {"moved": False, "reason": "end" if where in ("next", "last") else "start"}
	rng = target.Range
	pos = int(rng.Start)
	doc.Range(pos, pos).Select()
	try:
		w.ScrollIntoView(doc.Range(pos, pos), True)
	except Exception:
		pass
	out: dict = {"moved": True, "text": _text(rng)[:1000]}
	_listData(target, out)
	try:
		listStart = out.get("listStart")
		if listStart is not None:
			# Un rango vacío devolvería el párrafo del cursor: el primero es el 1.
			out["index"] = 1 if pos <= listStart else int(doc.Range(listStart, pos - 1).ListParagraphs.Count) + 1
	except Exception:
		pass
	return out


def listItemText(d: dict) -> str:
	"""Lo que se dice al llegar a un elemento de lista con la navegación propia."""
	parts = [listPrefix(d)]
	if d.get("index") and d.get("listCount"):
		parts.append(_("{i} de {n}").format(i=d["index"], n=d["listCount"]))
	parts.append(d.get("text") or _("en blanco"))
	return ", ".join(p for p in parts if p)


# ================================================================ comentarios
def _commentDict(c) -> dict:
	d: dict = {"author": "", "date": "", "text": "", "done": False, "replies": [], "scope": "", "start": 0}
	try:
		d["author"] = c.Author or ""
	except Exception:
		pass
	try:
		d["date"] = formatDate(c.Date)
	except Exception:
		pass
	try:
		d["text"] = _text(c.Range)
	except Exception:
		pass
	try:
		d["done"] = bool(c.Done)
	except Exception:
		pass
	try:
		scope = c.Scope
		d["scope"] = _text(scope)
		d["start"] = int(scope.Start)
		d["end"] = int(scope.End)
	except Exception:
		pass
	try:
		replies = c.Replies
		for i in range(1, int(replies.Count) + 1):
			r = replies.Item(i)
			d["replies"].append({"author": r.Author or "", "date": formatDate(r.Date), "text": _text(r.Range)})
	except Exception:
		pass
	return d


def _isReply(c) -> bool:
	try:
		return c.Ancestor is not None
	except Exception:
		return False


def om_comments(hwnd: int) -> list[dict]:
	"""Comentarios principales del documento (las respuestas van dentro)."""
	doc = _doc(hwnd)
	out = []
	comments = doc.Comments
	for i in range(1, min(int(comments.Count), MAX_ITEMS) + 1):
		c = comments.Item(i)
		if _isReply(c):
			continue
		out.append(_commentDict(c))
	out.sort(key=lambda d: d.get("start", 0))
	return out


def om_commentsAtCaret(hwnd: int) -> list[dict]:
	"""Comentarios cuyo ámbito contiene el cursor (o, si no hay, los del párrafo)."""
	sel = _sel(hwnd)
	start, end = int(sel.Start), int(sel.End)
	para = sel.Paragraphs(1).Range
	pStart, pEnd = int(para.Start), int(para.End)
	doc = sel.Document
	exact, inPara = [], []
	comments = doc.Comments
	for i in range(1, min(int(comments.Count), MAX_ITEMS) + 1):
		c = comments.Item(i)
		if _isReply(c):
			continue
		try:
			scope = c.Scope
			s, e = int(scope.Start), int(scope.End)
		except Exception:
			continue
		if s <= start <= max(e, s + 1) or (start <= s and e <= end and end > start):
			exact.append(_commentDict(c))
		elif s < pEnd and e > pStart:
			inPara.append(_commentDict(c))
	return exact or inPara


def commentText(d: dict, withScope: bool = False) -> str:
	parts = []
	head = _("Comentario de {author}").format(author=d["author"]) if d.get("author") else _("Comentario")
	if d.get("date"):
		head += " " + _("del {date}").format(date=d["date"])
	if d.get("done"):
		head += ", " + _("resuelto")
	parts.append(head + ": " + (d.get("text") or "").rstrip("."))
	if withScope and d.get("scope"):
		parts.append(_("sobre el texto: {text}").format(text=d["scope"].rstrip(".")))
	replies = d.get("replies") or []
	if replies:
		parts.append(_("{n} respuestas").format(n=len(replies)) if len(replies) != 1 else _("1 respuesta"))
		for r in replies:
			who = r.get("author") or _("alguien")
			parts.append(_("Respuesta de {author}: {text}").format(author=who, text=r.get("text", "").rstrip(".")))
	return ". ".join(parts)


# ================================================================ revisiones
def _revisionDict(r) -> dict:
	d: dict = {"type": 0, "author": "", "text": "", "date": "", "start": 0}
	try:
		d["type"] = int(r.Type)
	except Exception:
		pass
	try:
		d["author"] = r.Author or ""
	except Exception:
		pass
	try:
		d["date"] = formatDate(r.Date)
	except Exception:
		pass
	try:
		rng = r.Range
		d["text"] = _text(rng)
		d["start"] = int(rng.Start)
		d["end"] = int(rng.End)
	except Exception:
		pass
	return d


def om_revisions(hwnd: int) -> list[dict]:
	doc = _doc(hwnd)
	revs = doc.Revisions
	out = [_revisionDict(revs.Item(i)) for i in range(1, min(int(revs.Count), MAX_ITEMS) + 1)]
	out.sort(key=lambda d: d.get("start", 0))
	return out


def revisionText(d: dict) -> str:
	kind = REVISION_TYPES.get(d.get("type", 0), _("revisión"))
	text = d.get("text") or ""
	if len(text) > 300:
		text = text[:300] + "…"
	out = f"{kind}: {text}" if text else kind
	if d.get("author"):
		out += " " + _("de {author}").format(author=d["author"])
	return out


# ================================================================ notas
def om_notesAtCaret(hwnd: int) -> list[dict]:
	"""Notas al pie y al final del párrafo del cursor."""
	sel = _sel(hwnd)
	start = int(sel.Start)
	para = sel.Paragraphs(1).Range
	out = []
	for kind, coll in ((_("Nota al pie"), para.Footnotes), (_("Nota al final"), para.Endnotes)):
		for i in range(1, int(coll.Count) + 1):
			n = coll.Item(i)
			ref = n.Reference
			out.append({"kind": kind, "index": int(n.Index), "text": _text(n.Range), "start": int(ref.Start), "distance": abs(int(ref.Start) - start)})
	out.sort(key=lambda d: d["distance"])
	return out


def noteText(d: dict) -> str:
	return f"{d['kind']} {d['index']}: {d['text']}"


# ================================================================ moverse
def om_moveTo(hwnd: int, start: int, end: int | None = None) -> str:
	"""Coloca el cursor en ``start`` (o selecciona hasta ``end``) y devuelve la línea."""
	w = _window(hwnd)
	doc = w.Document
	rng = doc.Range(start, start if end is None else end)
	rng.Select()
	try:
		w.ScrollIntoView(rng, True)
	except Exception:
		pass
	sel = w.Application.Selection
	try:
		return _text(sel.Bookmarks("\\Line").Range)
	except Exception:
		return ""


def om_findNext(hwnd: int, kind: str, direction: int) -> dict | None:
	"""Siguiente o anterior comentario (``comment``) o revisión (``revision``) desde el cursor."""
	sel = _sel(hwnd)
	pos = int(sel.Start)
	# Solo se pide el inicio de cada uno; los datos completos (autor, texto,
	# respuestas...), del elegido: en documentos con muchos comentarios o
	# revisiones, leerlos todos agotaba el tiempo de la llamada.
	items = _itemStarts(sel.Document, kind)
	if direction > 0:
		cands = [t for t in items if t[0] > pos]
		found = cands[0] if cands else None
	else:
		cands = [t for t in items if t[0] < pos]
		found = cands[-1] if cands else None
	if found is None:
		return None
	target = _commentDict(found[1]) if kind == "comment" else _revisionDict(found[1])
	target["start"] = found[0]
	target["line"] = om_moveTo(hwnd, found[0])
	return target


def _itemStarts(doc, kind: str) -> list[tuple[int, Any]]:
	"""``(inicio, objeto)`` de los comentarios principales o de las revisiones, por orden."""
	out: list[tuple[int, Any]] = []
	if kind == "comment":
		coll = doc.Comments
		for i in range(1, min(int(coll.Count), MAX_ITEMS) + 1):
			c = coll.Item(i)
			if _isReply(c):
				continue
			try:
				start = int(c.Scope.Start)
			except Exception:
				start = 0
			out.append((start, c))
	else:
		coll = doc.Revisions
		for i in range(1, min(int(coll.Count), MAX_ITEMS) + 1):
			r = coll.Item(i)
			try:
				start = int(r.Range.Start)
			except Exception:
				start = 0
			out.append((start, r))
	out.sort(key=lambda t: t[0])
	return out


# ================================================================ tablas
def om_tableMove(hwnd: int, dRow: int, dCol: int, headers: dict | None) -> dict:
	"""Mueve el cursor a otra celda de la tabla y devuelve sus datos."""
	sel = _sel(hwnd)
	info = sel.Information
	if not info(wdWithInTable):
		return {"inTable": False}
	tbl = sel.Tables(1)
	row = int(info(wdStartOfRangeRowNumber))
	col = int(info(wdStartOfRangeColumnNumber))
	newRow, newCol = row + dRow, col + dCol
	try:
		cell = tbl.Cell(newRow, newCol)
	except Exception:
		return {"inTable": True, "edge": True, "row": row, "col": col}
	cell.Select()
	sel = _sel(hwnd)
	try:
		sel.Collapse(1)  # wdCollapseStart
	except Exception:
		pass
	return om_cellInfo(hwnd, headers)


def om_cellInfo(hwnd: int, headers: dict | None) -> dict:
	sel = _sel(hwnd)
	info = sel.Information
	if not info(wdWithInTable):
		return {"inTable": False}
	tbl = sel.Tables(1)
	row = int(info(wdStartOfRangeRowNumber))
	col = int(info(wdStartOfRangeColumnNumber))
	out = {"inTable": True, "row": row, "col": col, "text": "", "rowHeader": "", "colHeader": "", "tableStart": int(tbl.Range.Start)}
	try:
		out["text"] = _text(tbl.Cell(row, col).Range)
	except Exception:
		pass
	headerRow = (headers or {}).get("colHeaderRow")
	headerCol = (headers or {}).get("rowHeaderCol")
	if headerRow is None:
		try:
			if tbl.Rows(1).HeadingFormat:
				headerRow = 1
		except Exception:
			pass
	if headerRow and row > headerRow:
		try:
			out["colHeader"] = _text(tbl.Cell(headerRow, col).Range)
		except Exception:
			pass
	if headerCol and col > headerCol:
		try:
			out["rowHeader"] = _text(tbl.Cell(row, headerCol).Range)
		except Exception:
			pass
	return out


def om_tableKey(hwnd: int) -> tuple[str, int] | None:
	"""Clave estable de la tabla del cursor: (documento, número de tabla)."""
	sel = _sel(hwnd)
	if not sel.Information(wdWithInTable):
		return None
	doc = sel.Document
	start = int(sel.Tables(1).Range.Start)
	tables = doc.Tables
	for i in range(1, int(tables.Count) + 1):
		if int(tables.Item(i).Range.Start) == start:
			return (doc.FullName, i)
	return (doc.FullName, 0)


def cellText(d: dict, reportHeaders: bool, coords: bool = True) -> str:
	parts = []
	if reportHeaders:
		if d.get("rowHeader"):
			parts.append(d["rowHeader"])
		if d.get("colHeader"):
			parts.append(d["colHeader"])
	parts.append(d.get("text") or _("en blanco"))
	if coords:
		parts.append(_("fila {r}, columna {c}").format(r=d.get("row"), c=d.get("col")))
	return ", ".join(parts)


# ================================================================ formato
def om_formatting(hwnd: int) -> dict:
	sel = _sel(hwnd)
	font = sel.Font
	para = sel.Paragraphs(1)
	out: dict = {}
	for key, getter in (
		("style", lambda: para.Style.NameLocal),
		("fontName", lambda: font.Name),
		("fontSize", lambda: float(font.Size)),
		("bold", lambda: int(font.Bold)),
		("italic", lambda: int(font.Italic)),
		("underline", lambda: int(font.Underline)),
		("strike", lambda: int(font.StrikeThrough)),
		("smallCaps", lambda: int(font.SmallCaps)),
		("allCaps", lambda: int(font.AllCaps)),
		("superscript", lambda: int(font.Superscript)),
		("subscript", lambda: int(font.Subscript)),
		("color", lambda: int(font.Color)),
		("highlight", lambda: int(sel.Range.HighlightColorIndex)),
		# Sombreado del texto (color de fondo), para el informe de colores (#8674).
		("backgroundColor", lambda: int(sel.Range.Shading.BackgroundPatternColor)),
		("alignment", lambda: int(para.Alignment)),
		("leftIndent", lambda: float(para.LeftIndent)),
		("rightIndent", lambda: float(para.RightIndent)),
		("firstLineIndent", lambda: float(para.FirstLineIndent)),
		("lineSpacingRule", lambda: int(para.LineSpacingRule)),
		("spaceBefore", lambda: float(para.SpaceBefore)),
		("spaceAfter", lambda: float(para.SpaceAfter)),
		("outlineLevel", lambda: int(para.OutlineLevel)),
		("language", lambda: str(sel.Range.LanguageID)),
	):
		try:
			out[key] = getter()
		except Exception:
			pass
	try:
		out.update({k: v for k, v in om_position(hwnd).items() if k in ("page", "pages", "line", "column")})
	except Exception:
		pass
	return out


_ON = 1


def _flag(v: Any) -> bool | None:
	# Word devuelve -1 (verdadero), 0 o 9999999 (mixto).
	if v in (None, 9999999):
		return None
	return bool(v)


def formattingText(f: dict) -> list[str]:
	out: list[str] = []
	if f.get("style"):
		out.append(_("estilo {name}").format(name=f["style"]))
	if f.get("fontName"):
		out.append(f["fontName"])
	if f.get("fontSize"):
		size = f["fontSize"]
		out.append(_("{n} puntos").format(n=int(size) if float(size).is_integer() else str(size).replace(".", ",")))
	for key, label in (("bold", _("negrita")), ("italic", _("cursiva")), ("underline", _("subrayado")), ("strike", _("tachado")), ("smallCaps", _("versalitas")), ("allCaps", _("todo mayúsculas")), ("superscript", _("superíndice")), ("subscript", _("subíndice"))):
		if _flag(f.get(key)):
			out.append(label)
	if "color" in f and f["color"] not in (-16777216, 9999999):
		name = _office.colorName(f["color"])
		if name:
			out.append(_("color {name}").format(name=name))
	if "backgroundColor" in f and f["backgroundColor"] not in (-16777216, 9999999):
		name = _office.colorName(f["backgroundColor"])
		if name:
			out.append(_("fondo {name}").format(name=name))
	if f.get("highlight"):
		out.append(_("resaltado"))
	if "alignment" in f:
		out.append(ALIGNMENTS.get(f["alignment"], ""))
	if f.get("leftIndent"):
		out.append(_("sangría izquierda {v}").format(v=_office.formatCm(f["leftIndent"])))
	if f.get("rightIndent"):
		out.append(_("sangría derecha {v}").format(v=_office.formatCm(f["rightIndent"])))
	fl = f.get("firstLineIndent") or 0
	if fl > 0:
		out.append(_("sangría de primera línea {v}").format(v=_office.formatCm(fl)))
	elif fl < 0:
		out.append(_("sangría francesa {v}").format(v=_office.formatCm(-fl)))
	if f.get("lineSpacingRule") in LINE_SPACING:
		out.append(LINE_SPACING[f["lineSpacingRule"]])
	if f.get("outlineLevel") and f["outlineLevel"] < 10:
		out.append(_("nivel de esquema {n}").format(n=f["outlineLevel"]))
	if f.get("page"):
		out.append(_("página {page}").format(page=f["page"]))
	return [p for p in out if p]


# ================================================================ lista de elementos
def om_elements(hwnd: int) -> dict[str, list[tuple[str, int, int]]]:
	"""Elementos del documento para la lista: {tipo: [(texto, inicio, fin)]}."""
	doc = _doc(hwnd)
	out: dict[str, list[tuple[str, int, int]]] = {}
	heads = []
	paras = doc.Paragraphs
	count = min(int(paras.Count), 20000)
	p = paras.First if count else None
	n = 0
	while p is not None and n < count and len(heads) < MAX_ITEMS:
		n += 1
		try:
			lvl = int(p.OutlineLevel)
			if lvl < 10:
				rng = p.Range
				text = _text(rng)
				if text:
					heads.append((_("nivel {n}: {text}").format(n=lvl, text=text), int(rng.Start), int(rng.Start)))
		except Exception:
			pass
		try:
			p = p.Next()
		except Exception:
			break
	out["headings"] = heads
	out["comments"] = [(commentText(c, withScope=False), c.get("start", 0), c.get("start", 0)) for c in om_comments(hwnd)]
	out["revisions"] = [(revisionText(r), r.get("start", 0), r.get("start", 0)) for r in om_revisions(hwnd)]
	notes = []
	for kind, coll in ((_("Nota al pie"), doc.Footnotes), (_("Nota al final"), doc.Endnotes)):
		for i in range(1, min(int(coll.Count), MAX_ITEMS) + 1):
			nt = coll.Item(i)
			ref = nt.Reference
			notes.append((f"{kind} {int(nt.Index)}: {_text(nt.Range)}", int(ref.Start), int(ref.Start)))
	notes.sort(key=lambda t: t[1])
	out["notes"] = notes
	tables = []
	tbls = doc.Tables
	for i in range(1, min(int(tbls.Count), MAX_ITEMS) + 1):
		t = tbls.Item(i)
		try:
			first = _text(t.Cell(1, 1).Range)
		except Exception:
			first = ""
		label = _("Tabla {n}: {rows} filas, {cols} columnas").format(n=i, rows=int(t.Rows.Count), cols=int(t.Columns.Count))
		if first:
			label += ", " + first
		start = int(t.Range.Start)
		tables.append((label, start, start))
	out["tables"] = tables
	links = []
	hl = doc.Hyperlinks
	for i in range(1, min(int(hl.Count), MAX_ITEMS) + 1):
		h = hl.Item(i)
		try:
			label = h.TextToDisplay or h.Address or ""
			rng = h.Range
			links.append((label, int(rng.Start), int(rng.Start)))
		except Exception:
			continue
	out["links"] = links
	for key, coll in (("spelling", doc.SpellingErrors), ("grammar", doc.GrammaticalErrors)):
		items = []
		try:
			total = min(int(coll.Count), 500)
			for i in range(1, total + 1):
				rng = coll.Item(i)
				items.append((_text(rng), int(rng.Start), int(rng.End)))
		except Exception:
			pass
		out[key] = items
	marks = []
	bms = doc.Bookmarks
	for i in range(1, min(int(bms.Count), MAX_ITEMS) + 1):
		b = bms.Item(i)
		try:
			marks.append((b.Name, int(b.Range.Start), int(b.Range.Start)))
		except Exception:
			continue
	out["bookmarks"] = marks
	return out


ELEMENT_KINDS = [
	("headings", _("Encabezados")),
	("comments", _("Comentarios")),
	("revisions", _("Revisiones")),
	("notes", _("Notas al pie y al final")),
	("spelling", _("Errores ortográficos")),
	("grammar", _("Errores gramaticales")),
	("tables", _("Tablas")),
	("links", _("Enlaces")),
	("bookmarks", _("Marcadores")),
]


# ================================================================ atajos de formato
def om_formatSnapshot(hwnd: int, delay: float = 0.0) -> dict:
	"""Estado de formato que cambian los atajos de teclado (para compararlo)."""
	import time

	if delay:
		time.sleep(delay)
	sel = _sel(hwnd)
	font = sel.Font
	para = sel.Paragraphs(1)
	snap: dict = {}
	for key, getter in (
		("bold", lambda: int(font.Bold)),
		("italic", lambda: int(font.Italic)),
		("underline", lambda: int(font.Underline)),
		("strike", lambda: int(font.StrikeThrough)),
		("superscript", lambda: int(font.Superscript)),
		("subscript", lambda: int(font.Subscript)),
		("fontSize", lambda: float(font.Size)),
		("alignment", lambda: int(para.Alignment)),
		("leftIndent", lambda: round(float(para.LeftIndent), 1)),
		("firstLineIndent", lambda: round(float(para.FirstLineIndent), 1)),
		("lineSpacingRule", lambda: int(para.LineSpacingRule)),
		("style", lambda: para.Style.NameLocal),
	):
		try:
			snap[key] = getter()
		except Exception:
			pass
	return snap


_TOGGLES = (
	("bold", _("negrita")),
	("italic", _("cursiva")),
	("underline", _("subrayado")),
	("strike", _("tachado")),
	("superscript", _("superíndice")),
	("subscript", _("subíndice")),
)


def formatDiff(old: dict, new: dict) -> list[str]:
	"""Qué cambió entre dos instantáneas de :func:`om_formatSnapshot`."""
	out: list[str] = []
	for key, label in _TOGGLES:
		if key in old and key in new and old[key] != new[key]:
			flag = _flag(new[key])
			if flag is None:
				continue
			out.append(_("{fmt} activado").format(fmt=label) if flag else _("{fmt} desactivado").format(fmt=label))
	if old.get("fontSize") != new.get("fontSize") and new.get("fontSize") and new["fontSize"] < 9999:
		size = new["fontSize"]
		out.append(_("{n} puntos").format(n=int(size) if float(size).is_integer() else str(size).replace(".", ",")))
	if "style" in new and old.get("style") != new.get("style"):
		out.append(_("estilo {name}").format(name=new["style"]))
	elif "alignment" in new and old.get("alignment") != new.get("alignment"):
		out.append(ALIGNMENTS.get(new["alignment"], ""))
	if old.get("leftIndent") != new.get("leftIndent") and "leftIndent" in new:
		out.append(_("sangría {v}").format(v=_office.formatCm(new["leftIndent"])) if new["leftIndent"] else _("sin sangría"))
	if old.get("firstLineIndent") != new.get("firstLineIndent") and "firstLineIndent" in new:
		fl = new["firstLineIndent"]
		if fl < 0:
			out.append(_("sangría francesa {v}").format(v=_office.formatCm(-fl)))
		elif fl > 0:
			out.append(_("sangría de primera línea {v}").format(v=_office.formatCm(fl)))
		else:
			out.append(_("sin sangría de primera línea"))
	if old.get("lineSpacingRule") != new.get("lineSpacingRule") and new.get("lineSpacingRule") in LINE_SPACING:
		out.append(LINE_SPACING[new["lineSpacingRule"]])
	return [p for p in out if p]
