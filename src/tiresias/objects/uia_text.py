"""TextInfo basado en el patrón Text de UI Automation."""

from __future__ import annotations

import ctypes
from typing import Any

import comtypes

from .. import textinfo
from ..a11y import uia_client as uc
from ..log import getLogger

log = getLogger("uiaText")
UIA = uc.UIA

_UNITS = {
	textinfo.UNIT_CHARACTER: uc.TU_CHARACTER,
	textinfo.UNIT_FORMAT: uc.TU_FORMAT,
	textinfo.UNIT_WORD: uc.TU_WORD,
	textinfo.UNIT_LINE: uc.TU_LINE,
	textinfo.UNIT_PARAGRAPH: uc.TU_PARAGRAPH,
	textinfo.UNIT_SENTENCE: uc.TU_PARAGRAPH,
	textinfo.UNIT_PAGE: uc.TU_PAGE,
	textinfo.UNIT_STORY: uc.TU_DOCUMENT,
}

_EP = {"start": uc.EP_START, "end": uc.EP_END}


def _attr(name: str, default: int) -> int:
	return getattr(UIA, name, default)


ATTR_FONTNAME = _attr("UIA_FontNameAttributeId", 40005)
ATTR_FONTSIZE = _attr("UIA_FontSizeAttributeId", 40006)
ATTR_FONTWEIGHT = _attr("UIA_FontWeightAttributeId", 40007)
ATTR_FOREGROUNDCOLOR = _attr("UIA_ForegroundColorAttributeId", 40008)
ATTR_BACKGROUNDCOLOR = _attr("UIA_BackgroundColorAttributeId", 40003)
ATTR_ISITALIC = _attr("UIA_IsItalicAttributeId", 40014)
ATTR_UNDERLINESTYLE = _attr("UIA_UnderlineStyleAttributeId", 40026)
ATTR_STRIKETHROUGH = _attr("UIA_StrikethroughStyleAttributeId", 40024)
ATTR_ISSUPERSCRIPT = _attr("UIA_IsSuperscriptAttributeId", 40017)
ATTR_ISSUBSCRIPT = _attr("UIA_IsSubscriptAttributeId", 40016)
ATTR_STYLENAME = _attr("UIA_StyleNameAttributeId", 40032)
ATTR_ALIGNMENT = _attr("UIA_HorizontalTextAlignmentAttributeId", 40013)
ATTR_ANNOTATIONTYPES = _attr("UIA_AnnotationTypesAttributeId", 40031)
ATTR_CULTURE = _attr("UIA_CultureAttributeId", 40004)
ATTR_INDENT_FIRST = _attr("UIA_IndentationFirstLineAttributeId", 40010)
ATTR_INDENT_LEADING = _attr("UIA_IndentationLeadingAttributeId", 40011)
ATTR_STYLEID = _attr("UIA_StyleIdAttributeId", 40034)
ATTR_LINESPACING = _attr("UIA_LineSpacingAttributeId", 40040)
ANNOTATION_SPELLING = 60001
ANNOTATION_GRAMMAR = 60002
ANNOTATION_COMMENT = 60003
ANNOTATION_HIGHLIGHTED = 60008
ANNOTATION_INSERTION = 60011
ANNOTATION_DELETION = 60012
ANNOTATION_FORMATCHANGE = 60014

#: Atributos que se pueden pedir a getFormatInfo (clave -> identificador UIA).
FORMAT_ATTRIBUTES = {
	"fontName": ATTR_FONTNAME,
	"fontSize": ATTR_FONTSIZE,
	"fontWeight": ATTR_FONTWEIGHT,
	"italic": ATTR_ISITALIC,
	"underline": ATTR_UNDERLINESTYLE,
	"strikethrough": ATTR_STRIKETHROUGH,
	"superscript": ATTR_ISSUPERSCRIPT,
	"subscript": ATTR_ISSUBSCRIPT,
	"style": ATTR_STYLENAME,
	"color": ATTR_FOREGROUNDCOLOR,
	"backgroundColor": ATTR_BACKGROUNDCOLOR,
	"alignment": ATTR_ALIGNMENT,
	"language": ATTR_CULTURE,
	"indentFirstLine": ATTR_INDENT_FIRST,
	"indentLeading": ATTR_INDENT_LEADING,
	"lineSpacing": ATTR_LINESPACING,
}


class UIABookmark(textinfo.Bookmark):
	def __eq__(self, other: object) -> bool:
		if not isinstance(other, UIABookmark):
			return False
		try:
			return bool(self.data.Compare(other.data))
		except Exception:
			return False

	def __hash__(self) -> int:
		return 0


class UIATextInfo(textinfo.TextInfo):
	def __init__(self, obj: Any, position: Any, _range=None) -> None:
		super().__init__(obj, position)
		if _range is not None:
			self._range = _range
			return
		pattern = obj.textPattern
		if pattern is None:
			raise RuntimeError("El objeto no tiene patrón Text")
		self._pattern = pattern
		if position == textinfo.POSITION_FIRST:
			r = pattern.DocumentRange
			r.MoveEndpointByRange(uc.EP_END, r, uc.EP_START)
		elif position == textinfo.POSITION_LAST:
			r = pattern.DocumentRange
			r.MoveEndpointByRange(uc.EP_START, r, uc.EP_END)
			r.MoveEndpointByUnit(uc.EP_START, uc.TU_CHARACTER, -1)
			r.MoveEndpointByRange(uc.EP_END, r, uc.EP_START)
		elif position == textinfo.POSITION_ALL:
			r = pattern.DocumentRange
		elif position == textinfo.POSITION_CARET:
			r = self._caretRange(pattern)
		elif position == textinfo.POSITION_SELECTION:
			r = self._selectionRange(pattern)
		elif isinstance(position, textinfo.Point):
			r = pattern.RangeFromPoint(ctypes.wintypes.POINT(position.x, position.y))
		elif isinstance(position, UIABookmark):
			r = position.data.Clone()
		elif isinstance(position, UIATextInfo):
			r = position._range.Clone()
		else:
			r = position  # Se asume un IUIAutomationTextRange.
		self._range = r

	@staticmethod
	def _selectionRange(pattern):
		try:
			arr = pattern.GetSelection()
			if arr and arr.Length > 0:
				return arr.GetElement(0)
		except comtypes.COMError:
			pass
		r = pattern.DocumentRange
		r.MoveEndpointByRange(uc.EP_END, r, uc.EP_START)
		return r

	@classmethod
	def _caretRange(cls, pattern):
		if isinstance(pattern, UIA.IUIAutomationTextPattern2):
			try:
				isActive = ctypes.c_int()
				r = pattern.GetCaretRange(ctypes.byref(isActive))
				if r:
					return r
			except (comtypes.COMError, TypeError):
				try:
					res = pattern.GetCaretRange()
					r = res[1] if isinstance(res, tuple) else res
					if r:
						return r
				except Exception:
					pass
		r = cls._selectionRange(pattern)
		r = r.Clone()
		r.MoveEndpointByRange(uc.EP_END, r, uc.EP_START)
		return r

	# ------------------------------------------------------------------
	def copy(self) -> "UIATextInfo":
		c = UIATextInfo(self.obj, None, _range=self._range.Clone())
		c._pattern = getattr(self, "_pattern", None)
		return c

	@property
	def text(self) -> str:
		try:
			return self._range.GetText(-1) or ""
		except comtypes.COMError:
			return ""

	def expand(self, unit: str) -> None:
		if unit == textinfo.UNIT_SENTENCE:
			# UIA no tiene unidad «frase»: se calcula dentro del párrafo.
			try:
				found = self._sentenceAt(self._range)
			except comtypes.COMError:
				found = None
			if found is not None:
				self._range = found[0]
				return
		u = _UNITS.get(unit, uc.TU_CHARACTER)
		if unit in (textinfo.UNIT_CHARACTER, textinfo.UNIT_WORD) and self._isCollapsedAtEnd():
			# Tras el último carácter no hay nada: algunos proveedores (los campos
			# Win32) expandirían hacia atrás y devolverían el último carácter.
			return
		try:
			self._range.ExpandToEnclosingUnit(u)
		except comtypes.COMError:
			pass

	def _isCollapsedAtEnd(self) -> bool:
		"""``True`` si el rango está contraído al final del texto."""
		try:
			r = self._range
			if r.CompareEndpoints(uc.EP_START, r, uc.EP_END) != 0:
				return False
			pat = getattr(self, "_pattern", None) or self.obj.textPattern
			if pat is None:
				return False
			return r.CompareEndpoints(uc.EP_START, pat.DocumentRange, uc.EP_END) >= 0
		except (comtypes.COMError, AttributeError):
			return False

	# ------------------------------------------------------- frases emuladas
	@staticmethod
	def _collapsed(r, end: bool = False):
		c = r.Clone()
		if end:
			c.MoveEndpointByRange(uc.EP_START, c, uc.EP_END)
		else:
			c.MoveEndpointByRange(uc.EP_END, c, uc.EP_START)
		return c

	def _sentenceAt(self, r):
		"""(rango de la frase, rango del párrafo, inicio, fin, desplazamiento)."""
		para = self._collapsed(r)
		para.ExpandToEnclosingUnit(uc.TU_PARAGRAPH)
		text = para.GetText(-1) or ""
		if not text:
			return None
		pre = self._collapsed(para)
		pre.MoveEndpointByRange(uc.EP_END, r, uc.EP_START)
		off = len(pre.GetText(-1) or "")
		off = min(off, len(text) - 1)
		s, e = textinfo.findSentenceBoundaries(text, off)
		# Rev. 10.11 (M5): los extremos se colocan comprobando el texto (la unidad
		# «carácter» de UIA no siempre coincide con la de Python: emojis).
		sent = self._collapsedAt(para, s)
		if e > s:
			sent.MoveEndpointByRange(uc.EP_END, self._collapsedAt(para, e), uc.EP_START)
		return sent, para, s, e, off, len(text)

	@classmethod
	def _collapsedAt(cls, para, index: int):
		"""Rango contraído a ``index`` caracteres (de Python) del principio de ``para``."""
		r = cls._collapsed(para)
		if index <= 0:
			return r
		r.Move(uc.TU_CHARACTER, index)
		for _i in range(4):
			probe = cls._collapsed(para)
			probe.MoveEndpointByRange(uc.EP_END, r, uc.EP_START)
			diff = index - len(probe.GetText(-1) or "")
			if diff == 0 or not r.Move(uc.TU_CHARACTER, diff):
				break
		return r

	def _moveSentence(self, r, direction: int):
		"""Mueve el rango contraído ``r`` una frase; devuelve el nuevo o ``None``."""
		found = self._sentenceAt(r)
		if found is None:
			return None
		sent, para, s, e, off, length = found
		pat = getattr(self, "_pattern", None)
		doc = pat.DocumentRange if pat is not None else None
		if direction > 0:
			rest = (para.GetText(-1) or "")[e:]
			if e < length and rest.strip():
				return self._collapsed(sent, end=True)
			nxt = self._collapsed(para, end=True)
			if doc is not None and nxt.CompareEndpoints(uc.EP_START, doc, uc.EP_END) >= 0:
				return None
			if nxt.CompareEndpoints(uc.EP_START, r, uc.EP_START) <= 0:
				return None
			return nxt
		if off > 0:
			# Inicio de la frase que contiene el carácter anterior.
			text = para.GetText(-1) or ""
			s2, _e2 = textinfo.findSentenceBoundaries(text, off - 1)
			return self._collapsedAt(para, s2)
		prev = self._collapsed(para)
		if prev.MoveEndpointByUnit(uc.EP_START, uc.TU_CHARACTER, -1) == 0:
			return None
		prev = self._collapsed(prev)
		found = self._sentenceAt(prev)
		if found is None:
			return prev
		# Se salta el final vacío del párrafo anterior.
		sent2, _p, s2, _e2, _o2, _l2 = found
		return self._collapsed(sent2)

	def _moveBySentence(self, direction: int, endPoint: str | None) -> int:
		if endPoint == "end":
			cur = self._collapsed(self._range, end=True)
		else:
			cur = self._collapsed(self._range)
		moved = 0
		step = 1 if direction > 0 else -1
		while moved != direction:
			nxt = self._moveSentence(cur, step)
			if nxt is None:
				break
			cur = nxt
			moved += step
		if not moved:
			return 0
		if endPoint == "start":
			self._range.MoveEndpointByRange(uc.EP_START, cur, uc.EP_START)
			if self._range.CompareEndpoints(uc.EP_END, cur, uc.EP_START) < 0:
				self._range.MoveEndpointByRange(uc.EP_END, cur, uc.EP_START)
		elif endPoint == "end":
			self._range.MoveEndpointByRange(uc.EP_END, cur, uc.EP_START)
			if self._range.CompareEndpoints(uc.EP_START, cur, uc.EP_START) > 0:
				self._range.MoveEndpointByRange(uc.EP_START, cur, uc.EP_START)
		else:
			self._range = cur
		return moved

	def collapse(self, end: bool = False) -> None:
		if end:
			self._range.MoveEndpointByRange(uc.EP_START, self._range, uc.EP_END)
		else:
			self._range.MoveEndpointByRange(uc.EP_END, self._range, uc.EP_START)

	def move(self, unit: str, direction: int, endPoint: str | None = None) -> int:
		if unit == textinfo.UNIT_SENTENCE:
			try:
				return self._moveBySentence(direction, endPoint)
			except comtypes.COMError:
				return 0
		u = _UNITS.get(unit, uc.TU_CHARACTER)
		try:
			if endPoint:
				return int(self._range.MoveEndpointByUnit(_EP[endPoint], u, direction))
			self.collapse()
			moved = int(self._range.Move(u, direction))
			self.collapse()
			return moved
		except comtypes.COMError:
			return 0

	def compareEndPoints(self, other: textinfo.TextInfo, which: str) -> int:
		assert isinstance(other, UIATextInfo)
		src = uc.EP_START if which.startswith("start") else uc.EP_END
		dst = uc.EP_START if which.endswith("Start") else uc.EP_END
		try:
			res = self._range.CompareEndpoints(src, other._range, dst)
		except comtypes.COMError:
			return 0
		return (res > 0) - (res < 0)

	def setEndPoint(self, other: textinfo.TextInfo, which: str) -> None:
		assert isinstance(other, UIATextInfo)
		src = uc.EP_START if which.startswith("start") else uc.EP_END
		dst = uc.EP_START if which.endswith("Start") else uc.EP_END
		self._range.MoveEndpointByRange(src, other._range, dst)

	@property
	def isCollapsed(self) -> bool:
		try:
			return self._range.CompareEndpoints(uc.EP_START, self._range, uc.EP_END) == 0
		except comtypes.COMError:
			return True

	@property
	def bookmark(self) -> textinfo.Bookmark:
		return UIABookmark(UIATextInfo, self._range.Clone())

	def updateCaret(self) -> None:
		r = self._range.Clone()
		r.MoveEndpointByRange(uc.EP_END, r, uc.EP_START)
		try:
			r.Select()
		except comtypes.COMError:
			log.debug("No se pudo mover el cursor", exc_info=True)

	def updateSelection(self) -> None:
		try:
			self._range.Select()
		except comtypes.COMError:
			log.debug("No se pudo seleccionar", exc_info=True)

	@property
	def boundingRects(self) -> list[tuple[int, int, int, int]]:
		try:
			vals = self._range.GetBoundingRectangles()
		except comtypes.COMError:
			return []
		vals = list(vals or ())
		return [tuple(int(v) for v in vals[i : i + 4]) for i in range(0, len(vals) - 3, 4)]  # type: ignore[misc]

	@property
	def pointAtStart(self) -> textinfo.Point | None:
		c = self.copy()
		c.collapse()
		c.move(textinfo.UNIT_CHARACTER, 1, endPoint="end")
		rects = c.boundingRects
		if rects:
			x, y, w, h = rects[0]
			return textinfo.Point(x + max(1, w // 2), y + max(1, h // 2))
		return None

	def getEnclosingObject(self):
		from .uia import UIAObject

		try:
			el = self._range.GetEnclosingElementBuildCache(uc.baseCacheRequest)
		except (comtypes.COMError, AttributeError):
			try:
				el = self._range.GetEnclosingElement()
			except comtypes.COMError:
				return None
		return UIAObject.fromElement(el) if el else None

	def _attrValue(self, attrId: int) -> Any:
		try:
			val = self._range.GetAttributeValue(attrId)
		except comtypes.COMError:
			return None
		if uc.isNotSupported(val):
			return None
		try:
			if uc.MIXED_ATTRIBUTE is not None and val == uc.MIXED_ATTRIBUTE:
				return None
		except Exception:
			pass
		return val

	def getFormatInfo(self, keys: set[str] | None = None) -> dict:
		"""Formato al inicio del rango. ``keys`` limita los atributos pedidos.

		Además de los atributos de ``FORMAT_ATTRIBUTES`` admite las claves de
		anotaciones: ``spellingError``, ``grammarError``, ``comment``,
		``insertion``, ``deletion`` y ``highlighted``.
		"""
		r = self.copy()
		r.collapse()
		r.move(textinfo.UNIT_CHARACTER, 1, endPoint="end")
		info: dict = {}
		for key, attr in FORMAT_ATTRIBUTES.items():
			if keys is not None and key not in keys:
				continue
			val = r._attrValue(attr)
			if val is not None:
				info[key] = val
		annotationKeys = {"spellingError", "grammarError", "comment", "insertion", "deletion", "highlighted"}
		if keys is None or keys & annotationKeys:
			ann = r._attrValue(ATTR_ANNOTATIONTYPES)
			types: set = set()
			if ann:
				try:
					types = set(ann)
				except TypeError:
					types = {ann}
			info["spellingError"] = ANNOTATION_SPELLING in types
			info["grammarError"] = ANNOTATION_GRAMMAR in types
			info["comment"] = ANNOTATION_COMMENT in types
			info["insertion"] = ANNOTATION_INSERTION in types
			info["deletion"] = ANNOTATION_DELETION in types
			info["highlighted"] = ANNOTATION_HIGHLIGHTED in types
		return info

	def getLanguage(self) -> str | None:
		"""Idioma del texto (``es_ES``...) si el documento lo indica."""
		from ..i18n import lcidToLanguage

		val = self._attrValue(ATTR_CULTURE)
		if isinstance(val, int) and val:
			return lcidToLanguage(val)
		return None

	@property
	def pageNumber(self) -> int | None:
		"""Número de página (si el documento admite la unidad «página»).

		Los controles sin paginación (campos de edición, RichEdit...) sustituyen
		la página por el documento entero: entonces no hay número de página.
		"""
		try:
			r = self._range.Clone()
			r.MoveEndpointByRange(uc.EP_END, r, uc.EP_START)
			r.ExpandToEnclosingUnit(uc.TU_PAGE)
			doc = r.Clone()
			doc.ExpandToEnclosingUnit(uc.TU_DOCUMENT)
			if r.CompareEndpoints(uc.EP_START, doc, uc.EP_START) == 0 and r.CompareEndpoints(uc.EP_END, doc, uc.EP_END) == 0:
				return None
			# Con el rango ya ajustado a su página, cada paso atrás es una página entera.
			moved = r.Move(uc.TU_PAGE, -10000)
			return abs(int(moved)) + 1
		except comtypes.COMError:
			return None

	@property
	def lineNumber(self) -> int | None:
		try:
			r = self._range.Clone()
			r.MoveEndpointByRange(uc.EP_END, r, uc.EP_START)
			r.ExpandToEnclosingUnit(uc.TU_LINE)
			moved = r.Move(uc.TU_LINE, -100000)
			return abs(int(moved)) + 1
		except comtypes.COMError:
			return None

	def hasSpellingError(self) -> bool:
		ann = self._attrValue(ATTR_ANNOTATIONTYPES)
		if not ann:
			return False
		try:
			return ANNOTATION_SPELLING in set(ann)
		except TypeError:
			return ann == ANNOTATION_SPELLING

	def activate(self) -> None:
		obj = self.getEnclosingObject()
		if obj:
			obj.doAction()

	def scrollIntoView(self) -> None:
		try:
			self._range.ScrollIntoView(True)
		except comtypes.COMError:
			pass
