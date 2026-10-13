"""Consultas al modelo de objetos de Microsoft PowerPoint.

Las funciones ``om_*`` reciben una ventana de PowerPoint con modelo de
objetos (``mdiClass``, ``paneClassDC`` o ``screenClass``) y se ejecutan en el
hilo de Office. Devuelven datos de Python sencillos.
"""

from __future__ import annotations

import re
import threading

from .. import winapi
from ..i18n import _
from . import _office

OM_WINDOW_CLASSES = ("mdiClass", "paneClassDC", "screenClass")

#: Tipos de forma (MsoShapeType) con nombre propio.
SHAPE_TYPES = {
	1: _("autoforma"),
	3: _("gráfico"),
	6: _("grupo"),
	7: _("objeto incrustado"),
	9: _("línea"),
	12: _("objeto OLE"),
	13: _("imagen"),
	14: _("marcador de posición"),
	15: _("WordArt"),
	16: _("vídeo"),
	17: _("cuadro de texto"),
	19: _("tabla"),
	21: _("tinta"),
	24: _("SmartArt"),
	28: _("modelo 3D"),
}


def _window(hwnd: int):
	return _office.nativeOMFromWindow(hwnd)


def _text(tr) -> str:
	try:
		t = tr.Text or ""
	except Exception:
		return ""
	return " ".join(t.replace("\r", " ").replace("\x0b", " ").split())


def _shapeText(shape) -> str:
	try:
		if shape.HasTextFrame and shape.TextFrame.HasText:
			return _text(shape.TextFrame.TextRange)
	except Exception:
		pass
	return ""


def _tableData(shape) -> list[list[str]]:
	rows: list[list[str]] = []
	tbl = shape.Table
	for r in range(1, int(tbl.Rows.Count) + 1):
		row = []
		for c in range(1, int(tbl.Columns.Count) + 1):
			try:
				row.append(_text(tbl.Cell(r, c).Shape.TextFrame.TextRange))
			except Exception:
				row.append("")
		rows.append(row)
	return rows


def _notes(slide) -> str:
	try:
		ph = slide.NotesPage.Shapes.Placeholders
		for i in range(1, int(ph.Count) + 1):
			p = ph.Item(i)
			if int(p.PlaceholderFormat.Type) == 2:  # ppPlaceholderBody
				return _text(p.TextFrame.TextRange)
	except Exception:
		pass
	return ""


def _slideDict(slide, withShapes: bool = True) -> dict:
	d: dict = {"index": int(slide.SlideIndex), "id": int(slide.SlideID), "title": "", "hidden": False, "notes": _notes(slide), "texts": [], "shapes": []}
	try:
		d["hidden"] = bool(slide.SlideShowTransition.Hidden)
	except Exception:
		pass
	try:
		if slide.Shapes.HasTitle:
			d["title"] = _text(slide.Shapes.Title.TextFrame.TextRange)
	except Exception:
		pass
	if withShapes:
		shapes = slide.Shapes
		for i in range(1, int(shapes.Count) + 1):
			sh = shapes.Item(i)
			info = {"name": sh.Name, "type": int(sh.Type), "text": _shapeText(sh), "left": float(sh.Left), "top": float(sh.Top), "width": float(sh.Width), "height": float(sh.Height), "alt": ""}
			try:
				info["alt"] = sh.AlternativeText or ""
			except Exception:
				pass
			try:
				info["id"] = int(sh.Id)
			except Exception:
				pass
			if info["text"] and _mathSuspect(sh, info["text"]):
				# Puede tener ecuaciones (foros 3.6): se confirman con el archivo.
				info["math"] = True
				d["mathSuspect"] = True
			try:
				if sh.HasTable:
					info["table"] = _tableData(sh)
			except Exception:
				pass
			d["shapes"].append(info)
			if info["text"] and info["text"] != d["title"]:
				d["texts"].append(info["text"])
	return d


def _presentation(hwnd: int):
	w = _window(hwnd)
	try:
		return w.Presentation
	except Exception:
		return w.Application.ActivePresentation


def _currentSlide(hwnd: int):
	w = _window(hwnd)
	try:
		# Ventana de presentación (diapositivas a pantalla completa).
		return w.View.Slide
	except Exception:
		pass
	app = w.Application
	try:
		return app.ActiveWindow.View.Slide
	except Exception:
		sel = app.ActiveWindow.Selection
		return sel.SlideRange.Item(1)


# ================================================================ diapositivas
def om_slideById(hwnd: int, slideId: int) -> dict:
	pres = _presentation(hwnd)
	slide = pres.Slides.FindBySlideID(slideId)
	d = _slideDict(slide, withShapes=False)
	d["count"] = int(pres.Slides.Count)
	return d


def om_currentSlide(hwnd: int) -> dict:
	slide = _currentSlide(hwnd)
	d = _slideDict(slide)
	try:
		d["count"] = int(slide.Parent.Slides.Count)
	except Exception:
		d["count"] = 0
	return d


def om_slideShowSlide(hwnd: int) -> dict:
	"""Diapositiva visible en la presentación a pantalla completa."""
	w = _window(hwnd)
	try:
		view = w.View
		state = int(view.State)  # 3 = pantalla negra, 4 = blanca, 5 = terminada
	except Exception:
		# No es la ventana de la presentación (o no da su estado).
		view = w.Application.SlideShowWindows.Item(1).View
		try:
			state = int(view.State)
		except Exception:
			state = 0
	if state == 5:
		# Pantalla final («Fin de la presentación»): no hay diapositiva visible y
		# ``View.Slide`` falla, así que se devuelve solo el estado.
		return {"state": state}
	slide = view.Slide
	d = _slideDict(slide)
	try:
		d["count"] = int(slide.Parent.Slides.Count)
	except Exception:
		d["count"] = 0
	d["state"] = state
	return d


def slideText(d: dict, full: bool = True, reportNotes: bool = True, reportHidden: bool = True, equations: dict | None = None, speakMath: bool = True) -> str:
	"""Texto de la diapositiva.

	``equations`` (``{id de forma: segmentos}``, de :func:`om_slideEquations`)
	sustituye el texto de las formas con ecuaciones por «ecuación» y su
	lectura con el motor de matemáticas (``speakMath``). Sin él, las formas
	que parecen tener ecuaciones dicen solo «ecuación» (foros 3.6).
	"""
	parts = [_("Diapositiva {n} de {total}").format(n=d.get("index"), total=d.get("count")) if d.get("count") else _("Diapositiva {n}").format(n=d.get("index"))]
	if reportHidden and d.get("hidden"):
		parts.append(_("oculta"))
	if d.get("title"):
		parts.append(d["title"])
	shapes = d.get("shapes") or []
	hasMath = any(sh.get("math") for sh in shapes) or bool(equations)
	if full:
		if hasMath:
			for sh in shapes:
				text = sh.get("text") or ""
				if not text or text == d.get("title"):
					continue
				segs = (equations or {}).get(sh.get("id"))
				if segs:
					parts.append(equationText(segs, speakMath))
				elif sh.get("math") and equations is None:
					parts.append(_("ecuación"))
				else:
					parts.append(text)
		else:
			parts.extend(d.get("texts") or [])
		for sh in shapes:
			if sh.get("table"):
				parts.append(tableSummary(sh["table"]))
			elif not sh.get("text") and sh.get("alt"):
				parts.append(sh["alt"])
	elif hasMath:
		n = sum(sum(1 for k, _v in segs if k == "math") for segs in (equations or {}).values())
		parts.append(_("con ecuaciones") if not n else (_("1 ecuación") if n == 1 else _("{n} ecuaciones").format(n=n)))
	if reportNotes and d.get("notes"):
		parts.append(_("tiene notas"))
	return ", ".join(p for p in parts if p)


def tableSummary(rows: list[list[str]]) -> str:
	if not rows:
		return _("tabla vacía")
	return _("tabla de {r} filas y {c} columnas").format(r=len(rows), c=len(rows[0]))


def tableText(rows: list[list[str]]) -> str:
	"""La tabla como texto navegable (NVDA #5350)."""
	lines = []
	header = rows[0] if rows else []
	for ri, row in enumerate(rows, 1):
		cells = []
		for ci, cell in enumerate(row):
			label = header[ci] if ri > 1 and ci < len(header) and header[ci] else ""
			cells.append(f"{label}: {cell}" if label else cell)
		lines.append(_("Fila {n}: {cells}").format(n=ri, cells="; ".join(cells)))
	return "\n".join(lines)


def slideIdFromAutomationId(aid: str) -> int | None:
	"""``Slide256Image`` → 256."""
	m = re.match(r"Slide(\d+)", aid or "")
	return int(m.group(1)) if m else None


# ================================================================ selección y formas
def om_selectionShape(hwnd: int) -> dict | None:
	"""Forma seleccionada: nombre, tipo, posición y tamaño, y tabla si la tiene."""
	app = _window(hwnd).Application
	sel = app.ActiveWindow.Selection
	try:
		rng = sel.ShapeRange
		if int(rng.Count) < 1:
			return None
		sh = rng.Item(1)
	except Exception:
		return None
	info = {"name": sh.Name, "type": int(sh.Type), "left": float(sh.Left), "top": float(sh.Top), "width": float(sh.Width), "height": float(sh.Height), "text": _shapeText(sh)}
	try:
		if sh.HasTable:
			info["table"] = _tableData(sh)
			tbl = sh.Table
			for r in range(1, int(tbl.Rows.Count) + 1):
				for c in range(1, int(tbl.Columns.Count) + 1):
					if tbl.Cell(r, c).Selected:
						info["cell"] = (r, c)
						raise StopIteration
	except StopIteration:
		pass
	except Exception:
		pass
	try:
		pageW = float(sh.Parent.Parent.PageSetup.SlideWidth)
		pageH = float(sh.Parent.Parent.PageSetup.SlideHeight)
		info["slideWidth"], info["slideHeight"] = pageW, pageH
	except Exception:
		pass
	return info


def shapeLocationText(s: dict) -> str:
	kind = SHAPE_TYPES.get(s.get("type", 0), _("forma"))
	parts = [f"{s.get('name', '')}, {kind}"]
	parts.append(_("a {x} del borde izquierdo y {y} del borde superior").format(x=_office.formatCm(s["left"]), y=_office.formatCm(s["top"])))
	parts.append(_("{w} de ancho por {h} de alto").format(w=_office.formatCm(s["width"]), h=_office.formatCm(s["height"])))
	if s.get("slideWidth"):
		right = s["slideWidth"] - (s["left"] + s["width"])
		bottom = s["slideHeight"] - (s["top"] + s["height"])
		if right < 0 or bottom < 0 or s["left"] < 0 or s["top"] < 0:
			parts.append(_("sale de la diapositiva"))
	return ", ".join(parts)


def om_selectShape(hwnd: int, slideIndex: int, shapeName: str) -> str:
	w = _window(hwnd)
	app = w.Application
	app.ActiveWindow.View.GotoSlide(slideIndex)
	shape = app.ActivePresentation.Slides.Item(slideIndex).Shapes.Item(shapeName)
	shape.Select()
	return shape.Name


def om_gotoSlide(hwnd: int, slideIndex: int) -> dict:
	w = _window(hwnd)
	w.Application.ActiveWindow.View.GotoSlide(slideIndex)
	return om_currentSlide(hwnd)


def om_elements(hwnd: int) -> dict[str, list[tuple[str, tuple]]]:
	pres = _presentation(hwnd)
	out: dict[str, list] = {"slides": [], "shapes": [], "tables": [], "notes": []}
	slides = pres.Slides
	count = int(slides.Count)
	current = None
	try:
		current = int(_currentSlide(hwnd).SlideIndex)
	except Exception:
		pass
	for i in range(1, count + 1):
		d = _slideDict(slides.Item(i))
		d["count"] = count
		out["slides"].append((slideText(d, full=False), ("slide", i, "")))
		if d.get("notes"):
			out["notes"].append((_("Diapositiva {n}: {text}").format(n=i, text=d["notes"]), ("slide", i, "")))
		for sh in d["shapes"]:
			label = f"{sh['name']}, {SHAPE_TYPES.get(sh['type'], _('forma'))}"
			if sh.get("text"):
				label += f": {sh['text'][:120]}"
			if i == current:
				out["shapes"].append((label, ("shape", i, sh["name"])))
			if sh.get("table"):
				out["tables"].append((_("Diapositiva {n}: {name}, {summary}").format(n=i, name=sh["name"], summary=tableSummary(sh["table"])), ("table", i, sh["name"], sh["table"])))
	return out


ELEMENT_KINDS = [
	("slides", _("Diapositivas")),
	("shapes", _("Formas de la diapositiva actual")),
	("tables", _("Tablas")),
	("notes", _("Notas del orador")),
]


# ================================================================ ecuaciones (foros 3.6)
# El modelo de objetos de PowerPoint no da el OMML de las ecuaciones (solo un
# texto lineal aproximado). Se leen del propio archivo .pptx: si la
# presentación está guardada, del archivo; si no, de una copia temporal
# (``SaveCopyAs``). El OMML se convierte a MathML con ``mathpres.omml``.
_P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_A14_NS = "http://schemas.microsoft.com/office/drawing/2010/main"
_M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_SHAPE_TAGS = {f"{{{_P_NS}}}{t}" for t in ("sp", "graphicFrame", "cxnSp", "pic")}
_MATH_TAGS = (f"{{{_M_NS}}}oMathPara", f"{{{_M_NS}}}oMath")
#: Extensiones que son paquetes Open XML de PowerPoint.
PPTX_EXTENSIONS = (".pptx", ".pptm", ".ppsx", ".ppsm", ".potx", ".potm")
#: Fuentes que usa Office para las ecuaciones.
_MATH_FONTS = ("cambria math", "math")


def _mathSuspect(shape, text: str) -> bool:
	"""``True`` si la forma parece contener una ecuación (barato, sin el archivo)."""
	if any(0x1D400 <= ord(ch) <= 0x1D7FF for ch in text):
		# Letras matemáticas (𝑥, 𝑦...) que PowerPoint usa en las ecuaciones.
		return True
	try:
		tr = shape.TextFrame.TextRange
		font = tr.Font.Name
		if font and any(m in str(font).lower() for m in _MATH_FONTS):
			return True
		if font:
			return False
		# Fuentes mezcladas: se miran los fragmentos (como mucho 60).
		runs = tr.Runs()
		for i in range(1, min(int(runs.Count), 60) + 1):
			name = tr.Runs(i, 1).Font.Name
			if name and any(m in str(name).lower() for m in _MATH_FONTS):
				return True
	except Exception:
		pass
	return False


def _iterNoFallback(el):
	"""Descendientes de ``el`` sin entrar en ``mc:Fallback`` (imagen de reserva)."""
	for child in el:
		if child.tag == f"{{{_MC_NS}}}Fallback":
			continue
		yield child
		yield from _iterNoFallback(child)


def _shapeCNvPr(shape):
	for child in shape:
		if child.tag.startswith(f"{{{_P_NS}}}nv"):
			c = child.find(f"{{{_P_NS}}}cNvPr")
			if c is not None:
				return c
	return None


def _paragraphSegments(p, out: list) -> None:
	from ..mathpres import omml

	for child in p:
		tag = child.tag
		if tag in (f"{{{_A_NS}}}r", f"{{{_A_NS}}}fld"):
			t = child.find(f"{{{_A_NS}}}t")
			if t is not None and t.text:
				out.append(("text", t.text))
		elif tag == f"{{{_A_NS}}}br":
			out.append(("text", " "))
		elif tag == f"{{{_MC_NS}}}AlternateContent":
			choice = child.find(f"{{{_MC_NS}}}Choice")
			if choice is not None:
				_paragraphSegments(choice, out)
		elif tag == f"{{{_A14_NS}}}m":
			for m in child:
				if m.tag in _MATH_TAGS:
					try:
						out.append(("math", omml.ommlElementToMathML(m)))
					except Exception:
						out.append(("math", ""))


def _mergeSegments(segs: list) -> list[tuple[str, str]]:
	out: list[tuple[str, str]] = []
	for kind, value in segs:
		if kind == "text" and out and out[-1][0] == "text":
			out[-1] = ("text", out[-1][1] + value)
		else:
			out.append((kind, value))
	cleaned = []
	for kind, value in out:
		if kind == "text":
			value = " ".join(value.split())
			if not value:
				continue
		cleaned.append((kind, value))
	return cleaned


def slideXmlEquations(xml: bytes | str) -> list[dict]:
	"""Formas con ecuaciones de una diapositiva: ``[{"id", "name", "segments"}]``.

	``segments`` es el texto de la forma en orden, con ``("text", texto)`` y
	``("math", mathml)``.
	"""
	import xml.etree.ElementTree as ET

	root = ET.fromstring(xml)
	out: list[dict] = []

	def visit(el) -> None:
		for child in el:
			if child.tag == f"{{{_MC_NS}}}Fallback":
				continue
			if child.tag in _SHAPE_TAGS:
				handleShape(child)
			else:
				visit(child)

	def handleShape(shape) -> None:
		if not any(e.tag in _MATH_TAGS for e in _iterNoFallback(shape)):
			return
		c = _shapeCNvPr(shape)
		segs: list = []
		first = True
		for e in _iterNoFallback(shape):
			if e.tag == f"{{{_A_NS}}}p":
				if not first:
					segs.append(("text", " "))
				first = False
				_paragraphSegments(e, segs)
		entry = {"id": int(c.get("id", "0")) if c is not None and c.get("id", "").isdigit() else 0, "name": c.get("name", "") if c is not None else "", "segments": _mergeSegments(segs)}
		out.append(entry)

	visit(root)
	return out


def pptxEquations(path: str) -> dict[int, list[dict]]:
	"""Ecuaciones de un archivo .pptx: ``{SlideID: [formas con ecuaciones]}``."""
	import posixpath
	import xml.etree.ElementTree as ET
	import zipfile

	out: dict[int, list[dict]] = {}
	with zipfile.ZipFile(path) as z:
		names = set(z.namelist())
		pres = ET.fromstring(z.read("ppt/presentation.xml"))
		rels = ET.fromstring(z.read("ppt/_rels/presentation.xml.rels"))
		targets = {r.get("Id"): r.get("Target", "") for r in rels}
		lst = pres.find(f"{{{_P_NS}}}sldIdLst")
		for s in list(lst) if lst is not None else []:
			try:
				sid = int(s.get("id", "0"))
			except ValueError:
				continue
			target = targets.get(s.get(f"{{{_R_NS}}}id"), "")
			if not target:
				continue
			part = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("ppt", target))
			if part not in names:
				continue
			data = z.read(part)
			if b"oMath" not in data:
				continue
			shapes = slideXmlEquations(data)
			if shapes:
				out[sid] = shapes
	return out


_eqLock = threading.Lock()
#: Caché: ruta → (firma del archivo, datos) para presentaciones guardadas, y
#: (ruta, SlideID, firma de las formas) → formas para las que no lo están.
_eqCache: dict = {}


def presentationEquations(pres, slideId: int, signature: tuple = ()) -> list[dict]:
	"""Formas con ecuaciones de la diapositiva ``slideId`` (en el hilo de Office)."""
	import os
	import shutil
	import tempfile

	path = str(getattr(pres, "FullName", "") or "")
	saved = False
	try:
		saved = bool(pres.Saved)
	except Exception:
		pass
	if saved and path.lower().endswith(PPTX_EXTENSIONS) and os.path.isfile(path):
		key = (os.path.getmtime(path), os.path.getsize(path))
		with _eqLock:
			hit = _eqCache.get(path)
		if hit is None or hit[0] != key:
			hit = (key, pptxEquations(path))
			with _eqLock:
				_eqCache[path] = hit
		return list(hit[1].get(slideId, []))
	ckey = (path, slideId, signature)
	with _eqLock:
		if ckey in _eqCache:
			return list(_eqCache[ckey])
		# Rev. 10.11: una copia sirve para todas las diapositivas mientras no
		# cambien (antes se guardaba una copia de la presentación entera por cada
		# diapositiva con ecuaciones, en plena presentación). Cada diapositiva
		# recuerda la firma con la que se leyó; si cambia, se hace otra copia.
		whole = _eqCache.get(("copia", path))
		if whole is not None:
			data, sigs = whole
			if sigs.get(slideId, signature) == signature:
				sigs[slideId] = signature
				return list(data.get(slideId, []))
	from .. import paths

	os.makedirs(paths.tempDir(), exist_ok=True)
	tmpdir = tempfile.mkdtemp(prefix="ppt-", dir=paths.tempDir())
	try:
		copy = os.path.join(tmpdir, "copia.pptx")
		pres.SaveCopyAs(copy, 24)  # ppSaveAsOpenXMLPresentation
		data = pptxEquations(copy)
	finally:
		shutil.rmtree(tmpdir, ignore_errors=True)
	shapes = data.get(slideId, [])
	with _eqLock:
		if len(_eqCache) > 200:
			_eqCache.clear()
		_eqCache[ckey] = shapes
		_eqCache[("copia", path)] = (data, {slideId: signature})
	return list(shapes)


def shapesSignature(d: dict) -> tuple:
	"""Firma de las formas con posibles ecuaciones (para la caché de copias)."""
	return tuple((sh.get("id"), sh.get("text", "")) for sh in d.get("shapes") or [] if sh.get("math"))


def om_slideEquations(hwnd: int, slideId: int, signature: tuple = ()) -> dict:
	"""``{id de forma: segmentos}`` de la diapositiva (para :func:`slideText`)."""
	pres = _presentation(hwnd)
	return {sh["id"]: sh["segments"] for sh in presentationEquations(pres, slideId, signature)}


def om_mathTargets(hwnd: int) -> dict:
	"""Ecuaciones de la forma seleccionada o, si no hay, de la diapositiva actual.

	Devuelve ``{"slide": índice, "items": [(etiqueta, mathml)]}``.
	"""
	w = _window(hwnd)
	# ``View.Slide`` funciona también en la vista normal: solo la ventana de la
	# presentación a pantalla completa (``screenClass``) no tiene selección.
	slide = _currentSlide(hwnd)
	selectedId = None
	if winapi.getClassName(hwnd) != "screenClass":
		try:
			rng = w.Application.ActiveWindow.Selection.ShapeRange
			if int(rng.Count) >= 1:
				selectedId = int(rng.Item(1).Id)
		except Exception:
			selectedId = None
	d = _slideDict(slide)
	pres = slide.Parent
	shapes = presentationEquations(pres, int(slide.SlideID), shapesSignature(d)) if d.get("mathSuspect") else []
	if selectedId is not None and any(sh["id"] == selectedId for sh in shapes):
		shapes = [sh for sh in shapes if sh["id"] == selectedId]
	items: list[tuple[str, str]] = []
	for sh in shapes:
		maths = [v for k, v in sh["segments"] if k == "math" and v]
		for i, m in enumerate(maths, 1):
			label = sh["name"] if len(maths) == 1 else _("{shape}, ecuación {n}").format(shape=sh["name"], n=i)
			items.append((label, m))
	return {"slide": d.get("index"), "items": items}


def equationText(segments: list, speakMath: bool = True) -> str:
	"""Texto de una forma con ecuaciones: «ecuación» y su lectura matemática."""
	parts: list[str] = []
	for kind, value in segments:
		if kind == "text":
			parts.append(value)
			continue
		spoken = ""
		if speakMath and value:
			try:
				from .. import mathpres

				spoken = mathpres.getSpeechText(value)
			except Exception:
				spoken = ""
		parts.append(_("ecuación: {math}").format(math=spoken) if spoken else _("ecuación"))
	return ", ".join(p.strip() for p in parts if p.strip())
