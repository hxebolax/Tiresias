"""Cursor de revisión: permite leer el texto sin mover el cursor del sistema.

Modos:

- ``object``: texto del objeto navegador.
- ``document``: documento en modo exploración (si lo hay).
- ``screen``: «revisión plana» de la ventana en primer plano: todos los
  objetos visibles ordenados por su posición en pantalla.
"""

from __future__ import annotations

from typing import Any

from . import api, labels, textinfo
from .config import conf
from .i18n import _
from .log import getLogger
from .objects.roles import Role, State

log = getLogger("review")

MODES = ("object", "document", "screen")
MODE_LABELS = {"object": _("revisión de objeto"), "document": _("revisión de documento"), "screen": _("revisión de pantalla")}
_currentMode = "object"


def getCurrentMode() -> str:
	return _currentMode


def getPositionForCurrentMode(obj: Any):
	if _currentMode == "document":
		ti = getattr(obj, "treeInterceptor", None)
		if ti is not None:
			try:
				return ti.makeTextInfo(textinfo.POSITION_CARET)
			except Exception:
				pass
	if _currentMode == "screen":
		return ScreenReviewTextInfo.forForeground(textinfo.POSITION_FIRST)
	try:
		if obj == api.getFocusObject() and obj.hasText:
			return obj.makeTextInfo(textinfo.POSITION_CARET)
	except Exception:
		pass
	try:
		return obj.makeTextInfo(textinfo.POSITION_FIRST)
	except Exception:
		from .textinfo import StaticTextInfo

		return StaticTextInfo(obj, textinfo.POSITION_FIRST, obj.basicText)


def setMode(mode: str) -> bool:
	global _currentMode
	obj = api.getNavigatorObject()
	if mode == "document":
		ti = getattr(obj, "treeInterceptor", None) if obj else None
		if ti is None:
			focus = api.getFocusObject()
			ti = getattr(focus, "treeInterceptor", None) if focus else None
		if ti is None:
			return False
	_currentMode = mode
	if obj is not None:
		pos = getPositionForCurrentMode(obj)
		if pos is not None:
			api.setReviewPosition(pos)
	return True


def nextMode(direction: int) -> str | None:
	"""Pasa al modo de revisión siguiente (1) o anterior (-1) disponible."""
	i = MODES.index(_currentMode) + direction
	while 0 <= i < len(MODES):
		if setMode(MODES[i]):
			return MODES[i]
		i += direction
	return None


def handleCaretMove(obj: Any, info: textinfo.TextInfo) -> None:
	"""El cursor del sistema se movió: la revisión lo sigue si procede."""
	if not conf["reviewCursor"]["followCaret"]:
		return
	nav = api.getNavigatorObject()
	if nav is not None and nav != obj and _currentMode == "object":
		focus = api.getFocusObject()
		if nav != focus:
			return
	if _currentMode == "screen":
		return
	api.setReviewPosition(info, isCaret=True)


# ------------------------------------------------------------------ pantalla
class ScreenReviewTextInfo(textinfo.OffsetsTextInfo):
	"""Texto de todos los objetos visibles del primer plano, por líneas."""

	_cacheText: str | None = None
	_cacheChunks: list = []

	@classmethod
	def forForeground(cls, position):
		fg = api.getForegroundObject()
		return cls(fg, position)

	def __init__(self, obj: Any, position: Any) -> None:
		self._chunks: list[tuple[int, int, Any]] = []
		self._built = None
		super().__init__(obj, position)

	def _build(self) -> str:
		if self._built is not None:
			return self._built
		items: list[tuple[int, int, int, str, Any]] = []

		def walk(o: Any, depth: int) -> None:
			if depth > 25 or len(items) > 3000:
				return
			try:
				children = o.children
			except Exception:
				return
			for c in children:
				try:
					st = c.states
					if State.INVISIBLE in st or State.OFFSCREEN in st:
						continue
					loc = c.location
					role = c.role
				except Exception:
					continue
				text = ""
				if role in (Role.STATICTEXT, Role.LINK, Role.BUTTON, Role.CHECKBOX, Role.RADIOBUTTON, Role.MENUITEM, Role.TAB, Role.LISTITEM, Role.TREEVIEWITEM, Role.EDITABLETEXT, Role.COMBOBOX, Role.HEADING, Role.GRAPHIC, Role.TABLECELL, Role.DATAITEM) or c.name and not c.children:
					text = " ".join(p for p in (labels.displayName(c, c.name), c.value) if p)
				if text and loc:
					items.append((loc[1], loc[0], loc[3], text, c))
				if role not in (Role.BUTTON, Role.LINK, Role.LISTITEM, Role.MENUITEM, Role.EDITABLETEXT, Role.COMBOBOX):
					walk(c, depth + 1)

		if self.obj is not None:
			walk(self.obj, 0)
		items.sort(key=lambda t: (t[0], t[1]))
		lines: list[list[tuple[int, str, Any]]] = []
		lastY = None
		lastH = 0
		for y, x, h, text, o in items:
			if lastY is None or y >= lastY + max(4, lastH * 0.6):
				lines.append([])
				lastY, lastH = y, h
			lines[-1].append((x, text, o))
		out = []
		pos = 0
		for line in lines:
			line.sort(key=lambda t: t[0])
			parts = []
			for _x, text, o in line:
				start = pos + sum(len(p) + 2 for p in parts)
				parts.append(text)
				self._chunks.append((start, start + len(text), o))
			s = "  ".join(parts) + "\n"
			out.append(s)
			pos += len(s)
		self._built = "".join(out)
		return self._built

	def _getStoryText(self) -> str:
		return self._build()

	def objectAtOffset(self, offset: int) -> Any:
		for s, e, o in self._chunks:
			if s <= offset < e:
				return o
		return None

	def activate(self) -> None:
		o = self.objectAtOffset(self._start)
		if o is not None:
			o.doAction()

	def getEnclosingObject(self) -> Any:
		return self.objectAtOffset(self._start)
