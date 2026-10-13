"""Integración de las matemáticas en el modo exploración.

- :func:`prefetch`: antes de recorrer el documento, localiza las fórmulas
  (elementos con rol ARIA «math» que no están dentro de otra fórmula) y
  obtiene su MathML de una sola vez (búsqueda IA2 con varios objetivos).
- :func:`mathText`: texto hablado de una fórmula para el búfer.
- :func:`mathMlAtCaret`: MathML de la fórmula del cursor de exploración.
- :func:`brailleLine`: línea del búfer con las fórmulas en braille CMU.
"""

from __future__ import annotations

import unicodedata
from typing import Any

import comtypes

from ..config import conf
from ..log import getLogger

log = getLogger("mathpres.browse")

_MAX_FORMULAS = 600


def _uc():
	from ..a11y import uia_client as uc

	return uc


def _cached(el, prop: int, default: Any = None) -> Any:
	uc = _uc()
	try:
		v = el.GetCachedPropertyValueEx(prop, True)
	except (comtypes.COMError, ValueError):
		return default
	if v is None or uc.isNotSupported(v):
		return default
	return v


def _isMath(el) -> bool:
	return (_cached(el, _uc().P_ARIAROLE, "") or "").lower() == "math"


def _children(el) -> list:
	try:
		arr = el.GetCachedChildren()
	except (comtypes.COMError, ValueError):
		return []
	if not arr:
		return []
	return [arr.GetElement(i) for i in range(arr.Length)]


def _findTopMath(el, out: list, depth: int = 0) -> None:
	if depth > 200 or len(out) >= _MAX_FORMULAS:
		return
	if _isMath(el):
		out.append(el)
		return
	for c in _children(el):
		_findTopMath(c, out, depth + 1)


def _rid(el) -> tuple:
	rid = _cached(el, _uc().P_RUNTIMEID, None)
	return tuple(rid) if rid else ()


def prefetch(buffer, cachedRoot) -> None:
	"""Obtiene el MathML de todas las fórmulas del documento."""
	from . import providers

	buffer._mathMl = {}
	buffer._mathByNode = {}
	_findLabelOnlyMath(buffer)
	maths: list = []
	_findTopMath(cachedRoot, maths)
	if not maths:
		return
	hwnd = providers.windowForElement(buffer.rootElement)
	targets = []
	for el in maths:
		rid = _rid(el)
		key = (hwnd, rid) if rid else None
		cached = providers.cacheGet(key)
		if cached:
			buffer._mathMl[rid] = cached
			continue
		name = (_cached(el, _uc().P_NAME, "") or "").strip()
		fromName = providers.mathMlFromText(name)
		if fromName:
			buffer._mathMl[rid] = fromName
			providers.cachePut(key, fromName)
			continue
		rect = _cached(el, _uc().P_BOUNDINGRECT, None)
		rect = tuple(float(v) for v in rect[:4]) if rect and len(rect) >= 4 else None
		targets.append((rid, rect))
	if targets and hwnd:
		timeout = min(6.0, 1.0 + 0.05 * len(targets))
		from .. import queue_handler

		if queue_handler.isCoreThread():
			# Actualización parcial o región viva (en el núcleo): búsqueda breve. Las
			# fórmulas que no se encuentren se leen con su texto y su MathML se pide
			# al explorarlas (Intro).
			timeout = min(timeout, 0.3)
		found = providers.prefetchForDocument(hwnd, targets, timeout=timeout)
		for rid, mathMl in found.items():
			buffer._mathMl[rid] = mathMl
			providers.cachePut((hwnd, rid) if rid else None, mathMl)


def _fallbackText(el, depth: int = 0) -> str:
	"""Texto de las hojas de una fórmula sin MathML disponible."""
	if depth > 60:
		return ""
	kids = _children(el)
	if not kids:
		return unicodedata.normalize("NFKC", (_cached(el, _uc().P_NAME, "") or "").strip())
	return " ".join(t for t in (_fallbackText(c, depth + 1) for c in kids) if t)


def mathText(buffer, node, el) -> str:
	"""Texto (hablado) de la fórmula ``node`` para el búfer."""
	from . import getSpeechText

	mm = getattr(buffer, "_mathMl", {}).get(node.rid)
	if mm is None and node.rid:
		from . import providers

		key = (providers.windowForElement(buffer.rootElement), node.rid)
		mm = providers.cacheGet(key)
	if mm:
		if not hasattr(buffer, "_mathByNode"):
			buffer._mathByNode = {}
		buffer._mathByNode[id(node)] = mm
		try:
			return getSpeechText(mm)
		except Exception:
			log.debug("Error leyendo la fórmula", exc_info=True)
	if node.name:
		from . import providers

		mm = providers.mathMlFromText(node.name)
		if mm:
			if not hasattr(buffer, "_mathByNode"):
				buffer._mathByNode = {}
			buffer._mathByNode[id(node)] = mm
			try:
				return getSpeechText(mm)
			except Exception:
				log.debug("Error leyendo la fórmula", exc_info=True)
		return node.name
	# Sin MathML: texto de las hojas (la estructura no está disponible).
	return _fallbackText(el) if el is not None else ""


def isLatexAlt(text: str) -> bool:
	"""¿El texto alternativo es una fórmula en LaTeX?"""
	from . import providers

	return providers.mathMlFromText(text) is not None


# ---------------------------------------------------------------- fórmulas fuera de la vista de control
def _findLabelOnlyMath(buffer) -> None:
	"""Chromium no publica en la vista de control los elementos ``role="math"``
	sin hijos (solo con etiqueta o texto alternativo). Se buscan en la vista
	completa y se recuerda delante de qué hermano van."""
	from . import providers

	uc = _uc()
	buffer._extraMath = {}
	try:
		cr = uc.makeCacheRequest([uc.P_NAME, uc.P_ARIAROLE, uc.P_RUNTIMEID, uc.P_BOUNDINGRECT])
		cr.TreeFilter = uc.client.RawViewCondition
		cond = uc.createAndCondition(uc.createPropertyCondition(uc.P_ARIAROLE, "math"), uc.client.CreatePropertyCondition(uc.P_ISCONTROLELEMENT, False))
		arr = buffer.rootElement.FindAllBuildCache(uc.TreeScope_Descendants, cond, cr)
	except (comtypes.COMError, AttributeError):
		return
	walker = uc.rawWalker
	for i in range(min(arr.Length if arr else 0, _MAX_FORMULAS)):
		el = arr.GetElement(i)
		name = (_cached(el, uc.P_NAME, "") or "").strip()
		if not name:
			continue
		try:
			parent = walker.GetParentElement(el)
			if not parent or providers.isMathElement(parent):
				continue
			anchor = _anchorFor(el, walker)
		except comtypes.COMError:
			continue
		if anchor is not None:
			mode, rid = anchor
			buffer._extraMath.setdefault(rid, []).append((mode, el, name))


def _anchorFor(el, walker, depth: int = 0) -> tuple[str, tuple] | None:
	"""Elemento de la vista de control junto al que va ``el``: («after», rid del
	anterior) o («before», rid del siguiente); si no hay, se sube un nivel."""
	uc = _uc()
	if depth > 6 or not el:
		return None
	prev = walker.GetPreviousSiblingElement(el)
	while prev and not prev.CurrentIsControlElement:
		prev = walker.GetPreviousSiblingElement(prev)
	if prev:
		return "after", uc.runtimeIdOf(prev)
	nxt = walker.GetNextSiblingElement(el)
	while nxt and not nxt.CurrentIsControlElement:
		nxt = walker.GetNextSiblingElement(nxt)
	if nxt:
		return "before", uc.runtimeIdOf(nxt)
	parent = walker.GetParentElement(el)
	if parent and parent.CurrentIsControlElement:
		# Único hijo de un elemento visible: se escribe tras su contenido.
		return "after", uc.runtimeIdOf(parent)
	return _anchorFor(parent, walker, depth + 1)


def emitExtras(buffer, parent, kid, mode: str) -> None:
	"""Escribe en el búfer las fórmulas que van antes o después de ``kid``."""
	from ..browse.buffer import Node
	from ..objects.roles import Role

	uc = _uc()
	rid = _rid(kid)
	items = buffer._extraMath.get(rid) if rid else None
	if not items:
		return
	pending = [x for x in items if x[0] == mode]
	for item in pending:
		items.remove(item)
		_mode, el, name = item
		n = Node()
		n.element = el
		n.parent = parent
		n.role = Role.MATH
		n.ariaRole = "math"
		n.name = name
		rid = _cached(el, uc.P_RUNTIMEID, None)
		n.rid = tuple(rid) if rid else ()
		rect = _cached(el, uc.P_BOUNDINGRECT, None)
		if rect and len(rect) >= 4:
			n.location = tuple(int(v) for v in rect[:4])
		buffer.nodes.append(n)
		if n.rid:
			buffer.byRid[n.rid] = n
		buffer._emit(mathText(buffer, n, None) or name, n)
		n.start = buffer.chunks[-1][0] if buffer.chunks and buffer.chunks[-1][2] is n else buffer._pos
		n.end = buffer._pos
		parent.children.append(n)


def mathNodeAt(buffer, offset: int):
	from ..objects.roles import Role

	node = buffer.nodeAt(offset)
	while node is not None and node.role != Role.MATH:
		node = node.parent
	return node


def mathMlForNode(buffer, node) -> str | None:
	mm = getattr(buffer, "_mathByNode", {}).get(id(node))
	if mm:
		return mm
	if node.element is None:
		return None
	from . import providers

	try:
		mm = providers.mathMlForUIAElement(node.element)
	except Exception:
		log.debug("Sin MathML para el nodo", exc_info=True)
		mm = None
	if not mm and node.name:
		mm = providers.mathMlFromText(node.name)
	if mm:
		if not hasattr(buffer, "_mathByNode"):
			buffer._mathByNode = {}
		buffer._mathByNode[id(node)] = mm
	return mm


def mathMlAtCaret(doc) -> str | None:
	buf = doc.buffer
	if buf is None:
		return None
	node = mathNodeAt(buf, doc.caret)
	if node is None:
		return None
	return mathMlForNode(buf, node)


def brailleLine(doc, start: int, end: int, withMap: bool = False) -> tuple | None:
	"""Texto de la línea con las fórmulas en braille CMU (o ``None`` si no hay).

	Con ``withMap`` devuelve también, por cada carácter del texto, su posición
	en el búfer (para los pulsadores de enrutamiento).
	"""
	if not conf["math"]["brailleMath"]:
		return None
	buf = doc.buffer
	from ..objects.roles import Role

	# Una fórmula partida en varias líneas del búfer se muestra una sola vez:
	# la línea braille abarca todas las líneas que ocupa.
	changedBounds = True
	while changedBounds:
		changedBounds = False
		for _cs, _ce, node in buf.chunksInRange(start, end):
			if node.role != Role.MATH:
				continue
			ns = buf.lineBounds(node.start)[0]
			ne = buf.lineBounds(max(node.start, node.end - 1))[1]
			if ns < start or ne > end:
				start, end = min(start, ns), max(end, ne)
				changedBounds = True
	pieces: list[str] = []
	offsets: list[int] = []
	pos = start
	newCursor = None
	changed = False
	done: set[int] = set()
	for _cs, _ce, node in buf.chunksInRange(start, end):
		if node.role != Role.MATH or id(node) in done:
			continue
		mm = getattr(buf, "_mathByNode", {}).get(id(node))
		if not mm:
			continue
		done.add(id(node))
		try:
			from . import getBrailleForMathMl

			braille = getBrailleForMathMl(mm)
		except Exception:
			continue
		s = max(start, node.start)
		e = min(end, node.end)
		before = buf.text[pos:s]
		pieces.append(before)
		offsets.extend(range(pos, s))
		outPos = sum(len(p) for p in pieces)
		if newCursor is None and doc.caret < e and doc.caret >= pos:
			newCursor = outPos if doc.caret >= s else outPos - (s - doc.caret)
		pieces.append(braille)
		# Las celdas de la fórmula apuntan a su inicio (activarlo la explora).
		offsets.extend([s] * len(braille))
		pos = e
		changed = True
	if not changed:
		return None
	pieces.append(buf.text[pos:end])
	offsets.extend(range(pos, end))
	text = "".join(pieces)
	if newCursor is None:
		# El cursor está tras la última fórmula.
		tail = end - doc.caret
		newCursor = max(0, len(text) - tail)
	newCursor = max(0, min(newCursor, len(text)))
	if withMap:
		return text, newCursor, offsets
	return text, newCursor
