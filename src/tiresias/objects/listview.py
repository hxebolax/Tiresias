"""Filas con columnas: listas ``SysListView32`` en vista de detalles y filas de
tablas UIA en modo foco.

:class:`RowWithColumns` añade a cualquier fila:

- lectura de todas las columnas con su encabezado al recibir el foco
  (como descripción del elemento);
- ``Control+Tiresias+1`` … ``Control+Tiresias+9`` y ``Control+Tiresias+0``:
  leer la columna 1 a 10 (dos pulsaciones: deletrearla);
- ``Control+Alt+flecha derecha/izquierda``: pasar a la columna siguiente o
  anterior, y ``Control+Alt+Inicio/Fin``: primera o última columna.

:class:`ListViewItem` obtiene las columnas de una lista Win32 con mensajes
``LVM_*`` (funciona igual con objetos MSAA y UIA) y :class:`UIATableRow` de
las celdas hijas de una fila UIA.
"""

from __future__ import annotations

from .. import speech
from ..a11y import win32ctl
from ..baseobject import script
from ..config import conf
from ..i18n import _
from ..log import getLogger
from .base import AccObject
from .roles import Role

log = getLogger("listview")

CAT_LIST = _("Listas y tablas")

#: Última columna leída con Control+Alt+flechas: (clave de la fila, índice).
_columnCursor: tuple[object, int] = (None, 0)


def _repeatCount() -> int:
	try:
		from ..global_commands import repeatCount

		return repeatCount()
	except Exception:
		return 0


class RowWithColumns(AccObject):
	"""Fila con columnas (lista de detalles o fila de tabla)."""

	#: Leer todas las columnas como descripción de la fila al recibir el foco.
	describeColumns = True

	def columnData(self) -> list[tuple[str, str]]:
		"""Lista de ``(encabezado, texto)`` en el orden visual."""
		return []

	def _formatColumn(self, header: str, text: str) -> str:
		text = text or _("en blanco")
		if header and conf["documentFormatting"]["reportTableHeaders"]:
			return f"{header}: {text}"
		return text

	def _get_description(self) -> str:
		if not self.describeColumns:
			return super()._get_description()
		cols = self.columnData()
		if len(cols) <= 1:
			return super()._get_description()
		name = self.name
		parts = []
		for i, (header, text) in enumerate(cols):
			if i == 0 and text == name:
				continue
			if not text:
				continue
			parts.append(self._formatColumn(header, text))
		return ", ".join(parts)

	def _speakColumn(self, index: int) -> None:
		global _columnCursor
		cols = self.columnData()
		if not cols:
			speech.speakMessage(_("Sin columnas"))
			return
		if not 0 <= index < len(cols):
			speech.speakMessage(_("No hay columna {n}").format(n=index + 1))
			return
		_columnCursor = (self._rowKey(), index)
		header, text = cols[index]
		if _repeatCount() == 1:
			speech.speakSpelling(text or "")
			return
		speech.speakMessage(self._formatColumn(header, text))

	def _rowKey(self) -> object:
		try:
			return (self.windowHandle, self.name)
		except Exception:
			return None

	@script(
		description=_("Lee la columna 1 a 10 de la fila de la lista (dos veces: la deletrea)"),
		category=CAT_LIST,
		gestures=tuple(f"kb:tiresias+control+{d}" for d in "1234567890"),
		speakOnDemand=True,
	)
	def script_readColumn(self, gesture) -> None:
		key = getattr(gesture, "mainKeyName", "") or ""
		digit = key[-1:] if key else ""
		if not digit.isdigit():
			return
		index = 9 if digit == "0" else int(digit) - 1
		self._speakColumn(index)

	def _moveColumn(self, delta: int | None = None, absolute: int | None = None) -> None:
		key, index = _columnCursor
		cols = self.columnData()
		if not cols:
			speech.speakMessage(_("Sin columnas"))
			return
		if key != self._rowKey():
			# Fila nueva: se empieza por la primera (o la última hacia atrás).
			index = -1 if (delta or 0) > 0 else len(cols)
		if absolute is not None:
			new = absolute if absolute >= 0 else len(cols) - 1
		else:
			new = index + (delta or 0)
		if not 0 <= new < len(cols):
			from ..audio import tones

			tones.playSound("boundary")
			return
		self._speakColumn(new)

	@script(description=_("Lee la columna siguiente de la fila"), category=CAT_LIST, gesture="kb:control+alt+rightArrow")
	def script_nextColumn(self, gesture) -> None:
		self._moveColumn(1)

	@script(description=_("Lee la columna anterior de la fila"), category=CAT_LIST, gesture="kb:control+alt+leftArrow")
	def script_previousColumn(self, gesture) -> None:
		self._moveColumn(-1)

	@script(description=_("Lee la primera columna de la fila"), category=CAT_LIST, gesture="kb:control+alt+home")
	def script_firstColumn(self, gesture) -> None:
		self._moveColumn(absolute=0)

	@script(description=_("Lee la última columna de la fila"), category=CAT_LIST, gesture="kb:control+alt+end")
	def script_lastColumn(self, gesture) -> None:
		self._moveColumn(absolute=-1)


class ListViewItem(RowWithColumns):
	"""Elemento de una lista Win32 ``SysListView32``."""

	def _listHwnd(self) -> int:
		return self.windowHandle

	def _get_listViewIndex(self) -> int:
		childId = getattr(self, "IAccessibleChildID", 0)
		if childId:
			return int(childId) - 1
		hwnd = self._listHwnd()
		row = getattr(self, "tableCellCoords", None)
		if row:
			return row[0] - 1
		try:
			if self.hasFocus:
				return win32ctl.listViewFocusedItem(hwnd)
		except Exception:
			pass
		name = self.name
		count = min(win32ctl.listViewItemCount(hwnd), 2000)
		for i in range(count):
			texts = win32ctl.listViewItemTexts(hwnd, i, 1)
			if texts and texts[0] == name:
				return i
		return -1

	def columnData(self) -> list[tuple[str, str]]:
		hwnd = self._listHwnd()
		if not hwnd or not win32ctl.listViewIsDetails(hwnd):
			return []
		index = self.listViewIndex
		if index < 0:
			return []
		count = win32ctl.listViewColumnCount(hwnd)
		if count <= 0:
			return []
		headers = win32ctl.listViewHeaders(hwnd)
		texts = win32ctl.listViewItemTexts(hwnd, index, count)
		order = win32ctl.listViewColumnOrder(hwnd, count)
		out = []
		for logical in order:
			header = headers[logical] if logical < len(headers) else ""
			text = texts[logical] if logical < len(texts) else ""
			out.append((header, text))
		return out

	def _get_positionInfo(self) -> dict[str, int]:
		# Primero la propia lista (LVM_GETITEMCOUNT): el recuento de hijos MSAA
		# incluye también el encabezado de columnas y daba «1 de 5» con 4 filas.
		index = self.listViewIndex
		count = win32ctl.listViewItemCount(self._listHwnd())
		if 0 <= index < count:
			return {"indexInGroup": index + 1, "similarItemsInGroup": count}
		return dict(super()._get_positionInfo())


class UIATableRow(RowWithColumns):
	"""Fila de una tabla o cuadrícula UIA cuyas celdas son sus hijos.

	Las columnas solo se leen con las órdenes (el foco anuncia la fila como la
	presenta la aplicación)."""

	describeColumns = False

	def columnData(self) -> list[tuple[str, str]]:
		out: list[tuple[str, str]] = []
		try:
			children = self.children
		except Exception:
			return out
		for child in children[:60]:
			try:
				role = child.role
			except Exception:
				continue
			if role in (Role.TABLECELL, Role.DATAITEM, Role.STATICTEXT, Role.EDITABLETEXT, Role.TABLEROWHEADER, Role.HEADERITEM, Role.CHECKBOX, Role.LINK):
				header = ""
				try:
					rowH, colH = child.tableHeaders
					header = colH
				except Exception:
					header = ""
				text = child.name or child.value or ""
				out.append((header, text))
		return out
