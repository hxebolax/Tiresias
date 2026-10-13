"""Estilo visual del texto del modo exploración.

Se pide al documento con el patrón Text de UIA (``RangeFromChild``) y se
guarda por bloque. Lo usan:

- ``BufferTextInfo.getFormatInfo`` (formato en el cursor, revisión, énfasis);
- la navegación «mismo estilo» / «distinto estilo»;
- el «vistazo» (Smart Glance): saltar a lo que destaca visualmente por
  tamaño, negrita o color aunque la página no lo marque como encabezado.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import comtypes

from ..a11y import uia_client as uc
from ..log import getLogger
from ..objects.roles import HEADING_ROLES, Role

log = getLogger("browseStyle")

STYLE_KEYS = {"fontName", "fontSize", "fontWeight", "italic", "color"}


def textPattern(doc: Any):
	"""Patrón Text del documento (``None`` si no tiene)."""
	cached = doc.__dict__.get("_textPatternCache")
	if cached is not None:
		return cached or None
	pat = None
	try:
		raw = doc.rootObject.element.GetCurrentPattern(uc.PAT_TEXT)
		if raw:
			pat = raw.QueryInterface(uc.UIA.IUIAutomationTextPattern)
	except (comtypes.COMError, AttributeError, ValueError):
		pat = None
	doc.__dict__["_textPatternCache"] = pat or False
	return pat


def rangeAt(doc: Any, offset: int):
	"""Rango UIA de un carácter del búfer (``None`` si no se puede)."""
	buf = doc.buffer
	if buf is None:
		return None
	custom = getattr(buf, "uiaRangeAt", None)
	if custom is not None:
		return custom(offset)
	pat = textPattern(doc)
	if pat is None:
		return None
	chunk = buf.chunkAt(offset)
	if chunk is None:
		chunk = buf._chunkAfter(offset)
		if chunk is None:
			return None
		offset = chunk[0]
	cs, ce, node = chunk
	if node.element is None:
		return None
	try:
		whole = pat.RangeFromChild(node.element)
		if whole is None:
			return None
		delta = offset - cs
		index = delta
		if delta > 0:
			# Rev. 10.11 (M5): el texto del búfer no es idéntico al del elemento (sin
			# guiones blandos, sin espacios en los extremos, \r\n como \n): se
			# alinea con el texto real antes de contar.
			try:
				full = whole.GetText(-1) or ""
			except comtypes.COMError:
				full = ""
			aligned = alignIndex(buf.text[cs:ce], full, delta) if full else None
			if aligned is not None:
				index = aligned
		r = whole.Clone()
		r.MoveEndpointByRange(uc.EP_END, r, uc.EP_START)
		if index > 0:
			moveToTextIndex(whole, r, index)
		r.MoveEndpointByUnit(uc.EP_END, uc.TU_CHARACTER, 1)
		return r
	except (comtypes.COMError, ValueError, AttributeError):
		return None


def alignIndex(chunkText: str, full: str, delta: int) -> int | None:
	"""Posición en ``full`` (texto real del elemento) del carácter ``delta`` del trozo del búfer.

	El búfer quita los guiones blandos y los espacios de los extremos y cambia
	``\\r\\n`` y ``\\r`` por ``\\n``. ``None`` si los textos no se corresponden
	(el trozo sale de una etiqueta, no del texto).
	"""
	i = j = 0
	n = len(full)
	if chunkText[:1] and not chunkText[:1].isspace():
		while j < n and full[j].isspace():
			j += 1
	while i < delta:
		if j >= n or i >= len(chunkText):
			return None
		fc = full[j]
		if fc == "\xad":
			j += 1
			continue
		if fc == "\r":
			j += 1
			if j < n and full[j] == "\n":
				continue
			i += 1
			continue
		ch = chunkText[i]
		if fc != ch and not (fc.isspace() and ch.isspace()):
			return None
		i += 1
		j += 1
	return j


def moveToTextIndex(base, r, index: int) -> None:
	"""Lleva el rango contraído ``r`` (al principio de ``base``) a ``index`` caracteres de Python.

	Rev. 10.11 (M5): la unidad «carácter» de UIA no es la de Python en todos
	los proveedores (emojis, grafemas): se mueve, se comprueba con el texto
	que queda detrás y se corrige.
	"""
	r.Move(uc.TU_CHARACTER, index)
	for _i in range(4):
		probe = base.Clone()
		probe.MoveEndpointByRange(uc.EP_END, r, uc.EP_START)
		got = len(probe.GetText(-1) or "")
		diff = index - got
		if diff == 0:
			return
		if not r.Move(uc.TU_CHARACTER, diff):
			return


def formatAt(doc: Any, offset: int, keys: set[str] | None = None) -> dict:
	"""Formato del texto en ``offset`` (atributos UIA + semántica del nodo)."""
	from ..objects.uia_text import UIATextInfo

	info: dict = {}
	r = rangeAt(doc, offset)
	if r is not None:
		try:
			info.update(UIATextInfo(None, None, _range=r).getFormatInfo(keys))
		except Exception:
			log.debug("Sin formato UIA", exc_info=True)
	buf = doc.buffer
	node = buf.nodeAt(offset) if buf is not None else None
	# Semántica de la página: completa lo que no da (o no tiene) el patrón Text.
	chain = [node] + list(node.ancestors()) if node is not None else []
	fmts = {n.fmt for n in chain if n is not None and n.fmt}
	if "mark" in fmts:
		info["highlighted"] = True
	if "insertion" in fmts:
		info["insertion"] = True
	if "deletion" in fmts:
		info["deletion"] = True
	if "comment" in fmts or any(n.relations.get("details") for n in chain if n is not None):
		info["comment"] = True
	if "strong" in fmts and not info.get("fontWeight"):
		info["fontWeight"] = 700
	if "emphasis" in fmts and "italic" not in info:
		info["italic"] = True
	for n in chain:
		inv = (n.aria.get("invalid") or "").lower()
		if inv == "spelling":
			info["spellingError"] = True
		elif inv == "grammar":
			info["grammarError"] = True
	if keys is not None:
		info = {k: v for k, v in info.items() if k in keys}
	return info


# ------------------------------------------------------------------ bloques de texto
def textBlocks(buf: Any) -> list:
	"""Bloques con texto propio, en orden del documento."""
	cache = buf.__dict__.get("_textBlocks") if hasattr(buf, "__dict__") else None
	if cache is not None and cache[0] == len(buf.text):
		return cache[1]
	seen: set[int] = set()
	out = []
	pos = 0
	text = buf.text
	# Párrafo a párrafo; cada uno se representa con su unidad de texto.
	for _i in range(100000):
		if pos >= len(text):
			break
		s, e = buf.paragraphBounds(pos)
		e = max(e, pos + 1)
		chunk = next((c for c in buf.chunksInRange(s, e) if text[c[0] : c[1]].strip()), None)
		if chunk is not None:
			unit = buf.textUnitOf(chunk[2])
			if unit is not None and id(unit) not in seen and unit is not buf.root:
				seen.add(id(unit))
				out.append(unit)
		pos = e
	buf.__dict__["_textBlocks"] = (len(buf.text), out)
	return out


def blockStyle(doc: Any, block: Any) -> tuple | None:
	"""(fuente, tamaño, peso, cursiva, color) del principio del bloque."""
	buf = doc.buffer
	styles = buf.__dict__.setdefault("_blockStyles", {})
	key = id(block)
	if key in styles:
		return styles[key]
	start = block.start
	# Primer carácter visible del bloque.
	text = buf.text
	while start < block.end and text[start : start + 1].isspace():
		start += 1
	fmt = formatAt(doc, start, STYLE_KEYS)
	style = None
	if fmt:
		style = (fmt.get("fontName"), fmt.get("fontSize"), fmt.get("fontWeight"), bool(fmt.get("italic")), fmt.get("color"))
	styles[key] = style
	return style


def bodySize(doc: Any) -> float:
	"""Tamaño de letra más habitual (ponderado por longitud de texto)."""
	buf = doc.buffer
	cached = buf.__dict__.get("_bodySize")
	if cached:
		return cached
	sizes: Counter = Counter()
	for block in textBlocks(buf)[:400]:
		st = blockStyle(doc, block)
		if st and st[1]:
			sizes[float(st[1])] += block.end - block.start
	size = sizes.most_common(1)[0][0] if sizes else 0.0
	buf.__dict__["_bodySize"] = size
	return size


def isProminent(doc: Any, block: Any) -> bool:
	"""¿El bloque destaca visualmente (más grande o en negrita y breve)?"""
	if block.role in HEADING_ROLES or block.role in (Role.LINK, Role.BUTTON) or block.rowCol:
		return False
	if any(a.role in (Role.TABLE, Role.DATAGRID, Role.LINK, Role.BUTTON) or a.role in HEADING_ROLES for a in block.ancestors()):
		return False
	st = blockStyle(doc, block)
	if not st:
		return False
	body = bodySize(doc)
	size = float(st[1] or 0)
	weight = int(st[2] or 400)
	length = len(doc.buffer.text[block.start : block.end].strip())
	if body and size >= body * 1.2 and length < 300:
		return True
	return weight >= 600 and length < 120 and (not body or size >= body)


def isVerticallyAligned(ref: Any, block: Any) -> bool:
	if ref is None or block is ref or not ref.location or not block.location:
		return False
	return abs(ref.location[0] - block.location[0]) <= 3
