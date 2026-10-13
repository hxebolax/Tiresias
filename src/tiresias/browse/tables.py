"""Navegación por tablas del modo exploración.

Celdas combinadas (una celda ocupa todas sus coordenadas en
``VirtualBuffer.tables``), primera y última fila o columna, lectura de la
fila o la columna completas, encabezados reales (``TableItemPattern``:
``HeaderItems`` de UIA) y encabezados fijados por el usuario.
"""

from __future__ import annotations

import time

import comtypes

from .. import speech
from ..a11y import uia_client as uc
from ..audio import tones
from ..baseobject import ScriptableObject, script
from ..config import conf
from ..i18n import _
from ..objects.roles import Role
from .buffer import Node, isLayoutTable

CAT = _("Modo exploración")

HEADER_ROLES = {Role.TABLECOLUMNHEADER, Role.TABLEROWHEADER, Role.HEADERITEM}
#: Segundos de consultas de encabezados a la aplicación al leer una fila o columna.
READ_LINE_HEADER_BUDGET = 1.5

#: Encabezados fijados a mano: {(documento, nº de tabla): {"colRow", "colFrom", "rowCol", "rowFrom"}}.
_manualHeaders: dict[tuple[str, int], dict[str, int]] = {}


def _repeat() -> int:
	from ..input import core as inputCore

	try:
		return inputCore.getLastScriptRepeatCount()
	except Exception:
		return 0


class TableNavigationMixin(ScriptableObject):
	"""Órdenes de tabla de :class:`BrowseModeDocument` (se mezcla con él)."""

	# ------------------------------------------------------------ consultas
	def _currentCell(self) -> tuple[Node, Node] | None:
		buf = self.buffer
		if not buf:
			return None
		offset = self.caret
		b = buf.boundaryAt(offset)
		if b is not None and b[2].role in (Role.TABLE, Role.DATAGRID):
			# En la línea de entrada o salida de la tabla (#3997): su primera o última celda.
			if b[3] == "start":
				offset = buf.contentOffset(offset, 1)
			else:
				prev = buf._chunkBefore(b[0])
				offset = prev[0] if prev else offset
		cell = buf.nodeAt(offset)
		while cell is not None and not cell.rowCol:
			cell = cell.parent
		if cell is None:
			return None
		table = next((a for a in cell.ancestors() if a.role in (Role.TABLE, Role.DATAGRID)), None)
		if table is None or isLayoutTable(table):
			return None
		return table, cell

	def _tableCells(self, table: Node) -> dict[tuple[int, int], Node]:
		return self.buffer.tables.get(id(table), {}) if self.buffer else {}

	def _tableKey(self, table: Node) -> tuple[str, int]:
		# Rev. 10.11 (M4): el número de cada tabla se calcula una vez por búfer
		# (se recorría todo el documento por cada celda al leer una columna).
		buf = self.buffer
		index = buf.__dict__.get("_tableIndex")
		if index is None or index[0] is not buf.nodes:
			tables = [n for n in buf.nodes if n.role in (Role.TABLE, Role.DATAGRID)]
			index = (buf.nodes, {id(t): i for i, t in enumerate(tables)})
			buf.__dict__["_tableIndex"] = index
		return self._documentKey(), index[1].get(id(table), -1)

	def _cellText(self, cell: Node | None) -> str:
		if cell is None or not self.buffer:
			return ""
		return " ".join(self.buffer.text[cell.start : cell.end].split())

	def _headerText(self, cell: Node | None) -> str:
		"""Texto de un encabezado al anunciarlo con otra celda: su abreviatura
		(``abbr``, #3566) si la tiene y la opción está activa; si no, su texto."""
		from . import html_details

		return html_details.headerAbbreviation(self, cell) or self._cellText(cell)

	def _logicalCoords(self, cell: Node) -> tuple[int, int]:
		"""Coordenadas lógicas: dentro de una celda combinada se recuerda la columna o fila de entrada."""
		last = self.__dict__.get("_tableCoords")
		r0, c0 = cell.rowCol
		if last and r0 <= last[0] < r0 + cell.rowSpan and c0 <= last[1] < c0 + cell.colSpan:
			return last
		return r0, c0

	def _uiaHeaders(self, cell: Node) -> tuple[str, str]:
		"""Encabezados que da el navegador (``TableItemPattern``)."""
		rowH = colH = ""
		el = cell.element
		if el is None:
			return rowH, colH
		# Rev. 10.11 (M4): una consulta por celda y búfer; se guarda.
		cache = self.buffer.__dict__.setdefault("_uiaHeaderCache", {}) if self.buffer is not None else {}
		cached = cache.get(id(cell))
		if cached is not None:
			return cached
		budget = self.__dict__.get("_headerBudget")
		if budget is not None and time.monotonic() > budget:
			# Lectura de una fila o columna larga: sin más consultas a la aplicación.
			return rowH, colH
		try:
			pat = el.GetCurrentPattern(uc.PAT_TABLEITEM)
			if not pat:
				return rowH, colH
			pat = pat.QueryInterface(uc.UIA.IUIAutomationTableItemPattern)

			def names(arr) -> str:
				out = []
				for i in range(arr.Length if arr else 0):
					e = arr.GetElement(i)
					node = self.buffer.byRid.get(uc.runtimeIdOf(e)) if self.buffer else None
					text = self._headerText(node) if node is not None and node is not cell else ""
					if not text and node is not cell:
						text = (e.CurrentName or "").strip()
					if text:
						out.append(text)
				return " ".join(out)

			colH = names(pat.GetCurrentColumnHeaderItems())
			rowH = names(pat.GetCurrentRowHeaderItems())
		except (comtypes.COMError, AttributeError, ValueError):
			pass
		cache[id(cell)] = (rowH, colH)
		return rowH, colH

	def headerTexts(self, table: Node, cell: Node, row: int | None = None, col: int | None = None) -> tuple[str, str]:
		"""(encabezado de fila, encabezado de columna) de una celda."""
		cells = self._tableCells(table)
		r0, c0 = cell.rowCol
		row = r0 if row is None else row
		col = c0 if col is None else col
		rowH = colH = ""
		manual = _manualHeaders.get(self._tableKey(table))
		if manual:
			if "colRow" in manual and row > manual["colRow"] and col >= manual["colFrom"]:
				colH = self._headerText(cells.get((manual["colRow"], col)))
			if "rowCol" in manual and col > manual["rowCol"] and row >= manual["rowFrom"]:
				rowH = self._headerText(cells.get((row, manual["rowCol"])))
		if not (rowH and colH) and cell.role not in HEADER_ROLES:
			uRow, uCol = self._uiaHeaders(cell)
			rowH = rowH or uRow
			colH = colH or uCol
		if not colH and row != 1:
			h = cells.get((1, col))
			if h is not None and h.role in (Role.TABLECOLUMNHEADER, Role.HEADERITEM) and h is not cell:
				colH = self._headerText(h)
		if not rowH and col != 1:
			h = cells.get((row, 1))
			if h is not None and h.role == Role.TABLEROWHEADER and h is not cell:
				rowH = self._headerText(h)
		return rowH, colH

	def cellSpeech(self, table: Node, cell: Node, row: int, col: int, rowChanged: bool, colChanged: bool) -> str:
		df = conf["documentFormatting"]
		parts: list[str] = []
		if df["reportTableHeaders"]:
			rowH, colH = self.headerTexts(table, cell, row, col)
			if rowChanged and rowH:
				parts.append(rowH)
			if colChanged and colH:
				parts.append(colH)
		if df["reportTableCellCoords"]:
			if rowChanged:
				parts.append(_("fila {n}").format(n=row))
			if colChanged:
				parts.append(_("columna {n}").format(n=col))
		if cell.colSpan > 1:
			parts.append(_("abarca {n} columnas").format(n=cell.colSpan))
		if cell.rowSpan > 1:
			parts.append(_("abarca {n} filas").format(n=cell.rowSpan))
		from .aria import sortLabel

		sort = sortLabel(cell.aria.get("sort") or cell.itemStatus)
		if sort and cell.role in HEADER_ROLES:
			parts.append(sort)
		parts.append(self._cellText(cell) or _("en blanco"))
		return " ".join(p for p in parts if p)

	def _goToCell(self, table: Node, cell: Node, row: int, col: int, rowChanged: bool, colChanged: bool) -> None:
		self.caret = cell.start
		self.selectionAnchor = None
		self.__dict__["_tableCoords"] = (row, col)
		speech.cancelSpeech()
		speech.speak([self.cellSpeech(table, cell, row, col, rowChanged, colChanged)])
		self._updateBraille(*self.buffer.lineBounds(cell.start))
		self._afterCaretMove(cell)

	# ------------------------------------------------------------ movimiento
	def _tableMove(self, dRow: int, dCol: int) -> None:
		cur = self._currentCell()
		if cur is None:
			speech.speakMessage(_("no está en una tabla"))
			return
		table, cell = cur
		cells = self._tableCells(table)
		row, col = self._logicalCoords(cell)
		r, c = row, col
		target = None
		for _i in range(500):
			r += dRow
			c += dCol
			cand = cells.get((r, c))
			if cand is None:
				break
			if cand is not cell:
				target = cand
				break
		if target is None:
			speech.speakMessage(_("borde de la tabla"))
			tones.playSound("boundary")
			return
		self._goToCell(table, target, r, c, bool(dRow), bool(dCol))

	def _tableJump(self, axis: str, last: bool) -> None:
		"""Primera o última fila (``axis="row"``) o columna (``"col"``)."""
		cur = self._currentCell()
		if cur is None:
			speech.speakMessage(_("no está en una tabla"))
			return
		table, cell = cur
		cells = self._tableCells(table)
		row, col = self._logicalCoords(cell)
		if axis == "row":
			rows = sorted({r for (r, c) in cells if c == col}, reverse=last)
			target = next(((r, cells[(r, col)]) for r in rows), None)
			if target is None or target[1] is cell:
				tones.playSound("boundary")
				speech.speakMessage(_("borde de la tabla"))
				return
			self._goToCell(table, target[1], target[0], col, True, False)
		else:
			cols = sorted({c for (r, c) in cells if r == row}, reverse=last)
			target = next(((c, cells[(row, c)]) for c in cols), None)
			if target is None or target[1] is cell:
				tones.playSound("boundary")
				speech.speakMessage(_("borde de la tabla"))
				return
			self._goToCell(table, target[1], row, target[0], False, True)

	def _readLine(self, axis: str) -> None:
		"""Lee la fila o la columna entera sin mover el cursor."""
		cur = self._currentCell()
		if cur is None:
			speech.speakMessage(_("no está en una tabla"))
			return
		table, cell = cur
		cells = self._tableCells(table)
		row, col = self._logicalCoords(cell)
		if axis == "row":
			keys = sorted((k for k in cells if k[0] == row), key=lambda k: k[1])
		else:
			keys = sorted((k for k in cells if k[1] == col), key=lambda k: k[0])
		seen: set[int] = set()
		parts: list[str] = []
		headers = conf["documentFormatting"]["reportTableHeaders"]
		# Rev. 10.11 (M4): tiempo máximo de consultas a la aplicación por lectura.
		self.__dict__["_headerBudget"] = time.monotonic() + READ_LINE_HEADER_BUDGET
		try:
			for k in keys:
				c = cells[k]
				if id(c) in seen:
					continue
				seen.add(id(c))
				text = self._cellText(c) or _("en blanco")
				if headers and c.role not in HEADER_ROLES:
					rowH, colH = self.headerTexts(table, c, k[0], k[1])
					h = colH if axis == "row" else rowH
					if h:
						text = f"{h}: {text}"
				parts.append(text)
		finally:
			self.__dict__.pop("_headerBudget", None)
		speech.cancelSpeech()
		speech.speak(["; ".join(parts)])

	@script(gesture="kb:control+alt+downArrow", description=_("Celda de abajo"), category=CAT)
	def script_tableNextRow(self, gesture) -> None:
		self._tableMove(1, 0)

	@script(gesture="kb:control+alt+upArrow", description=_("Celda de arriba"), category=CAT)
	def script_tablePrevRow(self, gesture) -> None:
		self._tableMove(-1, 0)

	@script(gesture="kb:control+alt+rightArrow", description=_("Celda siguiente"), category=CAT)
	def script_tableNextCol(self, gesture) -> None:
		self._tableMove(0, 1)

	@script(gesture="kb:control+alt+leftArrow", description=_("Celda anterior"), category=CAT)
	def script_tablePrevCol(self, gesture) -> None:
		self._tableMove(0, -1)

	@script(gesture="kb:control+alt+pageUp", description=_("Va a la primera fila de la tabla"), category=CAT)
	def script_tableFirstRow(self, gesture) -> None:
		self._tableJump("row", False)

	@script(gesture="kb:control+alt+pageDown", description=_("Va a la última fila de la tabla"), category=CAT)
	def script_tableLastRow(self, gesture) -> None:
		self._tableJump("row", True)

	@script(gesture="kb:control+alt+home", description=_("Va a la primera columna de la tabla"), category=CAT)
	def script_tableFirstCol(self, gesture) -> None:
		self._tableJump("col", False)

	@script(gesture="kb:control+alt+end", description=_("Va a la última columna de la tabla"), category=CAT)
	def script_tableLastCol(self, gesture) -> None:
		self._tableJump("col", True)

	@script(gesture="kb:tiresias+control+alt+leftArrow", description=_("Lee la fila actual de la tabla sin mover el cursor"), category=CAT, speakOnDemand=True)
	def script_tableSpeakRow(self, gesture) -> None:
		self._readLine("row")

	@script(gesture="kb:tiresias+control+alt+upArrow", description=_("Lee la columna actual de la tabla sin mover el cursor"), category=CAT, speakOnDemand=True)
	def script_tableSpeakColumn(self, gesture) -> None:
		self._readLine("col")

	# ------------------------------------------------------------ encabezados fijados
	def _setHeaders(self, kind: str) -> None:
		cur = self._currentCell()
		if cur is None:
			speech.speakMessage(_("no está en una tabla"))
			return
		table, cell = cur
		key = self._tableKey(table)
		row, col = self._logicalCoords(cell)
		data = _manualHeaders.setdefault(key, {})
		if kind == "col":
			if _repeat() >= 1 or (data.get("colRow") == row and data.get("colFrom") == col):
				data.pop("colRow", None)
				data.pop("colFrom", None)
				speech.speakMessage(_("encabezados de columna olvidados"))
			else:
				data["colRow"], data["colFrom"] = row, col
				speech.speakMessage(_("la fila {n} es ahora la de encabezados de columna").format(n=row))
		else:
			if _repeat() >= 1 or (data.get("rowCol") == col and data.get("rowFrom") == row):
				data.pop("rowCol", None)
				data.pop("rowFrom", None)
				speech.speakMessage(_("encabezados de fila olvidados"))
			else:
				data["rowCol"], data["rowFrom"] = col, row
				speech.speakMessage(_("la columna {n} es ahora la de encabezados de fila").format(n=col))
		if not data:
			_manualHeaders.pop(key, None)

	@script(gesture="kb:tiresias+control+alt+c", description=_("Usa la fila actual como encabezados de columna de la tabla (dos veces: los olvida)"), category=CAT)
	def script_tableSetColumnHeader(self, gesture) -> None:
		self._setHeaders("col")

	@script(gesture="kb:tiresias+control+alt+r", description=_("Usa la columna actual como encabezados de fila de la tabla (dos veces: los olvida)"), category=CAT)
	def script_tableSetRowHeader(self, gesture) -> None:
		self._setHeaders("row")

	@script(description=_("Incluye o excluye las tablas de diseño en el modo exploración"), category=CAT)
	def script_toggleIncludeLayoutTables(self, gesture) -> None:
		value = not conf["browseMode"]["includeLayoutTables"]
		conf["browseMode"]["includeLayoutTables"] = value
		speech.speakMessage(_("incluir tablas de diseño activado") if value else _("incluir tablas de diseño desactivado"))
		self.requestRebuild()

	# ------------------------------------------------------------ al leer por líneas
	def cellEntrySpeech(self, node: Node, chunkStart: int, state: dict) -> list[str]:
		"""«fila N columna M» al entrar en una celda mientras se lee por líneas."""
		if not conf["documentFormatting"]["reportTableCellCoords"]:
			return []
		cell = node
		while cell is not None and not cell.rowCol:
			cell = cell.parent
		if cell is None or cell.start != chunkStart or id(cell) in state.setdefault("cells", set()):
			return []
		table = next((a for a in cell.ancestors() if a.role in (Role.TABLE, Role.DATAGRID)), None)
		if table is None or isLayoutTable(table):
			return []
		state["cells"].add(id(cell))
		row, col = cell.rowCol
		out = []
		if state.get("row") != (id(table), row):
			state["row"] = (id(table), row)
			out.append(_("fila {n}").format(n=row))
		out.append(_("columna {n}").format(n=col))
		return out
