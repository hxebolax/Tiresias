"""Búfer del modo exploración para documentos UIA con patrón Text.

Word (también el panel de lectura de Outlook), documentos XAML de solo
lectura y otros documentos UIA no exponen su contenido como árbol de
elementos, sino como texto. El búfer se construye así:

- el texto es ``DocumentRange.GetText`` (con las marcas de Word
  normalizadas sin cambiar la longitud, para que los desplazamientos del
  búfer coincidan con los caracteres del documento);
- cada párrafo es un nodo; su estilo (``StyleId``) da los encabezados de
  nivel 1 a 9, las citas y las listas;
- los elementos hijos del documento (enlaces, tablas con sus celdas,
  imágenes, listas) se colocan en su rango de texto.
"""

from __future__ import annotations

import bisect
from typing import Any

import comtypes

from ..a11y import uia_client as uc
from ..i18n import _
from ..log import getLogger
from ..objects.roles import Role
from ..objects.uia import _CONTROLTYPE_ROLES
from .buffer import Node, VirtualBuffer, _cached

log = getLogger("textBuffer")

#: Límite de párrafos que se recorren uno a uno (el resto va en un bloque).
MAX_PARAGRAPHS = 20000
#: Límite de elementos hijos (enlaces, tablas...) que se colocan.
MAX_CHILDREN = 600

STYLE_HEADING1 = 70001
STYLE_HEADING9 = 70009
STYLE_TITLE = 70010
STYLE_SUBTITLE = 70011
STYLE_QUOTE = 70014
STYLE_BULLETED = 70015
STYLE_NUMBERED = 70016
ATTR_STYLEID = 40034

CELL_MARK = "\x07"
#: Espacios y marcas de Word (un párrafo solo con ellas está vacío).
_MARKS = " \t\r\n\x07\x0b\x0c"


def normalizeText(text: str) -> str:
	"""Marcas de Word a texto legible sin cambiar la longitud.

	``\\r\\n`` (documentos WPF y XAML) pasa a « \\n»: antes quedaba «\\n\\n» y
	cada párrafo iba seguido de una línea en blanco (rev. 10.11, B2).
	"""
	return text.replace("\r\n", " \n").replace("\r", "\n").replace("\x0b", "\n").replace("\x0c", "\n").replace(CELL_MARK, " ")


class TextPatternBuffer(VirtualBuffer):
	"""Búfer construido con el patrón Text de UIA."""

	def __init__(self, rootElement) -> None:
		super().__init__(rootElement)
		self._pattern = None
		#: Inicio (desplazamiento) y rango UIA de cada párrafo.
		self._paraStarts: list[int] = []
		self._paraRanges: list[Any] = []
		#: Estilo (StyleId) de cada párrafo, leído al recorrerlos.
		self._paraStyles: list[int] = []
		#: Búfer anterior del mismo documento: si el texto no ha cambiado se
		#: reutiliza en lugar de recorrer de nuevo los párrafos (rev. 10.11, A3).
		self.reuseFrom: "TextPatternBuffer | None" = None
		self._raw: str | None = None

	_REUSED_ATTRS = ("text", "nodes", "chunks", "_chunkStarts", "root", "byRid", "tables", "softBreaks", "_paraStarts", "_paraRanges", "_paraStyles", "boundaryLines", "_boundaryStarts")

	def _reuse(self, prev: "TextPatternBuffer", raw: str) -> bool:
		if prev is None or getattr(prev, "_raw", None) != raw or not prev.nodes:
			return False
		for attr in self._REUSED_ATTRS:
			setattr(self, attr, getattr(prev, attr))
		self._raw = raw
		return True

	def build(self) -> None:
		pat = self.rootElement.GetCurrentPattern(uc.PAT_TEXT)
		if not pat:
			raise comtypes.COMError(-2147467259, "Sin patrón Text", None)
		pat = pat.QueryInterface(uc.UIA.IUIAutomationTextPattern)
		self._pattern = pat
		docRange = pat.DocumentRange
		raw = docRange.GetText(-1) or ""
		prev = self.reuseFrom
		self.reuseFrom = None
		if self._reuse(prev, raw):
			return
		self._raw = raw
		self.nodes = []
		self.chunks = []
		self.byRid = {}
		self.tables = {}
		self.softBreaks = set()
		self._paraStarts = []
		self._paraRanges = []
		self._paraStyles = []
		root = Node()
		root.element = self.rootElement
		root.role = Role.DOCUMENT
		root.start, root.end = 0, len(raw)
		self.root = root
		paras = self._walkParagraphs(docRange, raw)
		chars = list(normalizeText(raw))
		# Las marcas de fin de fila de tabla separan líneas.
		for start, _end, ptext in paras:
			if ptext == CELL_MARK and start < len(chars):
				chars[start] = "\n"
		if not raw.endswith(("\r", "\n")):
			chars.append("\n")
			root.end += 1
		self.text = "".join(chars)
		nodes: list[Node] = [root]
		listNode: Node | None = None
		for i, (start, end, _ptext) in enumerate(paras):
			n = Node()
			n.start, n.end = start, end
			style = self._paraStyles[i] if i < len(self._paraStyles) else self._styleOf(start)
			if STYLE_HEADING1 <= style <= STYLE_HEADING9:
				lvl = style - STYLE_HEADING1 + 1
				n.level = lvl
				n.role = Role(Role.HEADING1 + lvl - 1) if lvl <= 6 else Role.HEADING
			elif style == STYLE_QUOTE:
				n.role = Role.BLOCKQUOTE
			elif style in (STYLE_BULLETED, STYLE_NUMBERED):
				n.role = Role.LISTITEM
			elif style in (STYLE_TITLE, STYLE_SUBTITLE):
				n.role = Role.PARAGRAPH
				n.semantic = _("título") if style == STYLE_TITLE else _("subtítulo")
			else:
				n.role = Role.PARAGRAPH
			if n.role == Role.LISTITEM:
				if listNode is None or listNode.end != start:
					listNode = Node()
					listNode.role = Role.LIST
					listNode.start = start
					nodes.append(listNode)
				listNode.end = end
			else:
				listNode = None
			nodes.append(n)
		nodes.extend(self._childNodes(docRange))
		self._assemble(nodes)
		self._wrapLongLines()
		self._chunkStarts = [c[0] for c in self.chunks]
		for i, n in enumerate(self.nodes):
			n.index = i

	# ------------------------------------------------------------ párrafos
	def _walkParagraphs(self, docRange, raw: str) -> list[tuple[int, int, str]]:
		out: list[tuple[int, int, str]] = []
		cur = docRange.Clone()
		cur.MoveEndpointByRange(uc.EP_END, cur, uc.EP_START)
		offset = 0
		total = len(raw)
		for _i in range(MAX_PARAGRAPHS):
			para = cur.Clone()
			para.ExpandToEnclosingUnit(uc.TU_PARAGRAPH)
			ptext = para.GetText(-1) or ""
			if not ptext:
				break
			# Se recoloca si el texto no coincide (campos ocultos, etc.).
			if raw[offset : offset + len(ptext)] != ptext:
				found = raw.find(ptext, offset, offset + len(ptext) + 2000)
				if found >= 0:
					offset = found
			start = offset
			end = min(total, start + len(ptext))
			out.append((start, end, ptext))
			self._paraStarts.append(start)
			self._paraRanges.append(para)
			# Rev. 10.11 (M6): el estilo se lee aquí (sin buscar luego el párrafo)
			# y no en los párrafos vacíos (solo marcas), que no pueden ser encabezados.
			self._paraStyles.append(self._rangeStyle(para) if ptext.strip(_MARKS) else 0)
			offset = end
			if offset >= total or cur.Move(uc.TU_PARAGRAPH, 1) == 0:
				break
		if offset < total:
			out.append((offset, total, raw[offset:]))
			self._paraStarts.append(offset)
			rest = docRange.Clone()
			if self._paraRanges:
				rest.MoveEndpointByRange(uc.EP_START, self._paraRanges[-1], uc.EP_END)
			self._paraRanges.append(rest)
			self._paraStyles.append(0)
		return out

	@staticmethod
	def _rangeStyle(r) -> int:
		try:
			val = r.GetAttributeValue(ATTR_STYLEID)
		except comtypes.COMError:
			return 0
		return val if isinstance(val, int) and not isinstance(val, bool) else 0

	def _styleOf(self, start: int) -> int:
		i = bisect.bisect_right(self._paraStarts, start) - 1
		if i < 0:
			return 0
		return self._rangeStyle(self._paraRanges[i])

	def offsetOfRange(self, r) -> int | None:
		"""Desplazamiento en el búfer del inicio de un rango UIA."""
		lo, hi = 0, len(self._paraRanges) - 1
		idx = -1
		try:
			while lo <= hi:
				mid = (lo + hi) // 2
				if self._paraRanges[mid].CompareEndpoints(uc.EP_START, r, uc.EP_START) <= 0:
					idx = mid
					lo = mid + 1
				else:
					hi = mid - 1
			if idx < 0:
				return 0
			pre = self._paraRanges[idx].Clone()
			pre.MoveEndpointByRange(uc.EP_END, r, uc.EP_START)
			return self._paraStarts[idx] + len(pre.GetText(-1) or "")
		except comtypes.COMError:
			return None

	def uiaRangeAt(self, offset: int):
		"""Rango UIA (un carácter) en ``offset``."""
		i = bisect.bisect_right(self._paraStarts, offset) - 1
		if i < 0 or not self._paraRanges:
			return None
		try:
			r = self._paraRanges[i].Clone()
			r.MoveEndpointByRange(uc.EP_END, r, uc.EP_START)
			delta = offset - self._paraStarts[i]
			if delta > 0:
				# Rev. 10.11 (M5): con comprobación (emojis: Word cuenta distinto).
				from .style import moveToTextIndex

				moveToTextIndex(self._paraRanges[i], r, delta)
			r.MoveEndpointByUnit(uc.EP_END, uc.TU_CHARACTER, 1)
			return r
		except (comtypes.COMError, AttributeError):
			return None

	# ------------------------------------------------------------ elementos hijos
	def _childNodes(self, docRange) -> list[Node]:
		out: list[Node] = []
		try:
			children = docRange.GetChildren()
		except comtypes.COMError:
			return out
		for i in range(min(children.Length if children else 0, MAX_CHILDREN)):
			try:
				el = children.GetElement(i).BuildUpdatedCache(uc.treeCacheRequest)
			except comtypes.COMError:
				continue
			node = self._elementNode(el)
			if node is None:
				continue
			out.append(node)
			if node.role in (Role.TABLE, Role.DATAGRID):
				out.extend(self._tableCells(el, node))
		return out

	def _rangeOffsets(self, el) -> tuple[int, int] | None:
		try:
			r = self._pattern.RangeFromChild(el)
		except comtypes.COMError:
			return None
		if r is None:
			return None
		start = self.offsetOfRange(r)
		if start is None:
			return None
		try:
			length = len(r.GetText(-1) or "")
		except comtypes.COMError:
			length = 0
		return start, start + length

	def _elementNode(self, el) -> Node | None:
		ct = _cached(el, uc.P_CONTROLTYPE, 0) or 0
		role = _CONTROLTYPE_ROLES.get(ct, Role.UNKNOWN)
		if role not in (Role.LINK, Role.TABLE, Role.DATAGRID, Role.GRAPHIC, Role.EDITABLETEXT, Role.BUTTON, Role.CHECKBOX, Role.COMBOBOX):
			return None
		offs = self._rangeOffsets(el)
		if offs is None:
			return None
		n = Node()
		n.element = el
		n.role = role
		n.name = (_cached(el, uc.P_NAME, "") or "").strip()
		n.start, n.end = offs
		rid = _cached(el, uc.P_RUNTIMEID, None)
		n.rid = tuple(rid) if rid else ()
		if n.rid:
			self.byRid[n.rid] = n
		if _cached(el, uc.P_ISKEYBOARDFOCUSABLE, False):
			n.isFocusable = True
		if role == Role.LINK:
			n.url = str(_cached(el, uc.P_VALUEVALUE, "") or "")
		rect = _cached(el, uc.P_BOUNDINGRECT, None)
		if rect and len(rect) >= 4:
			n.location = tuple(int(v) for v in rect[:4])  # type: ignore[assignment]
		if role in (Role.TABLE, Role.DATAGRID):
			rc = _cached(el, uc.P_GRIDROWCOUNT, None)
			cc = _cached(el, uc.P_GRIDCOLUMNCOUNT, None)
			if rc is not None and cc is not None:
				n.tableSize = (int(rc), int(cc))
		if n.end <= n.start and role != Role.GRAPHIC:
			return None
		return n

	def _tableCells(self, el, table: Node) -> list[Node]:
		cells: list[Node] = []
		stack = [el]
		guard = 0
		while stack and guard < 5000:
			guard += 1
			cur = stack.pop()
			try:
				kids = cur.GetCachedChildren()
			except (comtypes.COMError, ValueError):
				kids = None
			for i in range((kids.Length if kids else 0) - 1, -1, -1):
				stack.append(kids.GetElement(i))
			if cur is el:
				continue
			row = _cached(cur, uc.P_GRIDITEMROW, None)
			col = _cached(cur, uc.P_GRIDITEMCOLUMN, None)
			if row is None or col is None:
				continue
			offs = self._rangeOffsets(cur)
			if offs is None:
				continue
			c = Node()
			c.element = cur
			c.role = Role.TABLECELL
			c.rowCol = (int(row) + 1, int(col) + 1)
			c.rowSpan = max(1, int(_cached(cur, uc.P_GRIDITEMROWSPAN, 1) or 1))
			c.colSpan = max(1, int(_cached(cur, uc.P_GRIDITEMCOLUMNSPAN, 1) or 1))
			c.start, c.end = offs
			rid = _cached(cur, uc.P_RUNTIMEID, None)
			c.rid = tuple(rid) if rid else ()
			if c.rid:
				self.byRid[c.rid] = c
			cells.append(c)
		grid: dict[tuple[int, int], Node] = {}
		for c in cells:
			for dr in range(c.rowSpan):
				for dc in range(c.colSpan):
					grid.setdefault((c.rowCol[0] + dr, c.rowCol[1] + dc), c)
		if grid:
			self.tables[id(table)] = grid
			if not table.tableSize:
				table.tableSize = (max(r for r, _c in grid), max(c for _r, c in grid))
		return cells

	# ------------------------------------------------------------ árbol y trozos
	def _assemble(self, nodes: list[Node]) -> None:
		"""Anida los nodos por contención de rangos y crea los trozos de texto."""
		root = nodes[0]
		rest = sorted(nodes[1:], key=lambda n: (n.start, -n.end, _ROLE_ORDER.get(n.role, 5)))
		stack = [root]
		for n in rest:
			while len(stack) > 1 and not (stack[-1].start <= n.start and n.end <= stack[-1].end):
				stack.pop()
			parent = stack[-1]
			n.parent = parent
			parent.children.append(n)
			stack.append(n)
		self.nodes = [root] + rest
		chunks: list[tuple[int, int, Node]] = []

		def emit(node: Node) -> None:
			pos = node.start
			for child in node.children:
				if child.start > pos:
					chunks.append((pos, child.start, node))
				emit(child)
				pos = max(pos, child.end)
			if pos < node.end and node is not root:
				chunks.append((pos, node.end, node))

		emit(root)
		# Rev. 10.11 (B1): un elemento que cruza el límite de un párrafo (un
		# enlace de dos párrafos) solapaba sus trozos con los del párrafo y el
		# texto se leía dos veces: cada trozo empieza donde acaba el anterior.
		chunks.sort(key=lambda c: c[0])
		clean: list[tuple[int, int, Node]] = []
		pos = 0
		for s, e, n in chunks:
			s = max(s, pos)
			if e > s:
				clean.append((s, e, n))
				pos = e
		self.chunks = clean


#: A igual rango, los contenedores van antes que su contenido.
_ROLE_ORDER = {Role.TABLE: 0, Role.DATAGRID: 0, Role.LIST: 1, Role.TABLECELL: 2, Role.LISTITEM: 3}
