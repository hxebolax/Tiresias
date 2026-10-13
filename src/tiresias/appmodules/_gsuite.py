"""Google Docs y Hojas de cálculo de Google en el navegador (foros 3.5).

Google Workspace funciona dentro de Chrome, Edge o Firefox, así que no tiene
módulo de aplicación propio: este complemento global incorporado lo detecta
por la dirección del documento (o por el título de la ventana) y por la
estructura ARIA.

**Hojas de cálculo.** La cuadrícula se dibuja en un lienzo: la página no
publica las demás celdas, solo el cuadro de nombre (``t-name-box``, la
dirección de la celda actual) y la barra de fórmulas (su contenido), y anuncia
la celda por una región viva. Tiresias:

- superpone :class:`SheetsCellEditor` al editor de celdas
  (``waffle-rich-text-editor``) en modo foco;
- tras cada tecla de movimiento lee la dirección y el contenido, los recuerda
  y, si la fila o la columna cambian, dice el título de fila o de columna;
- permite fijar la fila de títulos de columna y la columna de títulos de fila
  con las mismas teclas que en Excel; se guardan por hoja (documento y
  ``gid``) en ``data/config/googleSheetsHeaders.json`` junto con los títulos
  aprendidos, así que basta pasar una vez por la fila de títulos.

Si la página publica una cuadrícula ARIA de verdad (celdas con
``GridItemPattern``), los títulos se leen directamente de ella.

**Documentos.** Al entrar en un documento de Docs, Hojas o Presentaciones se
recuerda (una vez por documento y sesión) cómo activar la compatibilidad con
lectores de pantalla y con braille de Google.
"""

from __future__ import annotations

import json
import os
import re
import threading
from typing import Any

from .. import paths, queue_handler, speech
from ..baseobject import script
from ..config import conf
from ..i18n import _
from ..log import getLogger
from ..objects.base import AccObject
from ..plugins import GlobalPlugin as _BasePlugin

log = getLogger("gsuite")

CAT = _("Google Docs y Hojas de cálculo")

conf.registerDefaults(
	"googleApps",
	{
		# Decir los títulos de fila y columna fijados al moverse por las celdas.
		"reportHeaders": True,
		# Recordar cómo activar la compatibilidad con lectores de pantalla.
		"announceTips": True,
	},
)

#: Identificadores de la página de Hojas de cálculo de Google.
EDITOR_ID = "waffle-rich-text-editor"
NAME_BOX_ID = "t-name-box"
#: Celdas recordadas por hoja (las más recientes).
MAX_CACHED_CELLS = 5000


# ================================================================ detección (pura)
def googleAppFromUrl(url: str) -> str | None:
	"""``sheets``, ``docs`` o ``slides`` para una dirección de Google Workspace."""
	m = re.match(r"https?://docs\.google\.com/(spreadsheets|document|presentation)/", url or "", re.I)
	if not m:
		return None
	return {"spreadsheets": "sheets", "document": "docs", "presentation": "slides"}[m.group(1).lower()]


_TITLE_SUFFIXES = {
	"sheets": ("hojas de cálculo de google", "google sheets"),
	"docs": ("documentos de google", "google docs"),
	"slides": ("presentaciones de google", "google slides"),
}


def googleAppFromTitle(title: str) -> str | None:
	"""Lo mismo por el título de la ventana («Libro - Hojas de cálculo de Google - Google Chrome»)."""
	low = (title or "").lower()
	for app, suffixes in _TITLE_SUFFIXES.items():
		if any(f" - {s}" in low for s in suffixes):
			return app
	return None


def documentIdFromUrl(url: str) -> str:
	m = re.search(r"/d/([A-Za-z0-9_-]+)", url or "")
	return m.group(1) if m else ""


def sheetKey(url: str, title: str = "") -> str:
	"""Clave de la hoja: documento y ``gid`` (pestaña), o el título si no hay dirección."""
	docId = documentIdFromUrl(url)
	if not docId:
		return f"titulo:{title}" if title else ""
	m = re.search(r"[#&?]gid=(\d+)", url or "")
	return f"{docId}:{m.group(1) if m else '0'}"


def parseCellRef(text: str) -> tuple[int, int] | None:
	"""``B3`` → (3, 2). Acepta ``$B$3``, ``Hoja1!B3`` y rangos (``A1:C3``, la primera)."""
	ref = (text or "").strip()
	if "!" in ref:
		ref = ref.rsplit("!", 1)[1]
	ref = ref.split(":", 1)[0].replace("$", "").strip("'")
	m = re.fullmatch(r"([A-Za-z]{1,3})(\d{1,7})", ref)
	if not m:
		return None
	col = 0
	for ch in m.group(1).upper():
		col = col * 26 + (ord(ch) - 64)
	return int(m.group(2)), col


def columnLetters(col: int) -> str:
	out = ""
	while col > 0:
		col, rem = divmod(col - 1, 26)
		out = chr(65 + rem) + out
	return out


# ================================================================ títulos guardados
_lock = threading.Lock()
_data: dict | None = None


def _file() -> str:
	return os.path.join(paths.configDir(), "googleSheetsHeaders.json")


def _load() -> dict:
	global _data
	if _data is None:
		try:
			with open(_file(), encoding="utf-8") as f:
				raw = json.load(f)
			_data = {str(k): v for k, v in raw.items() if isinstance(v, dict)}
		except FileNotFoundError:
			_data = {}
		except Exception:
			log.exception("No se pudieron leer los títulos de Hojas de cálculo de Google")
			_data = {}
	return _data


def _save() -> None:
	try:
		os.makedirs(os.path.dirname(_file()), exist_ok=True)
		tmp = _file() + ".tmp"
		with open(tmp, "w", encoding="utf-8") as f:
			json.dump(_data or {}, f, ensure_ascii=False, indent=1)
		os.replace(tmp, _file())
	except Exception:
		log.exception("No se pudieron guardar los títulos de Hojas de cálculo de Google")


def getEntry(key: str) -> dict:
	with _lock:
		e = _load().get(key) or {}
		return {"colHeaderRow": e.get("colHeaderRow"), "rowHeaderCol": e.get("rowHeaderCol"), "colTitles": dict(e.get("colTitles") or {}), "rowTitles": dict(e.get("rowTitles") or {})}


def putEntry(key: str, entry: dict) -> None:
	with _lock:
		data = _load()
		clean = {k: v for k, v in entry.items() if v not in (None, {}, "")}
		if clean.get("colHeaderRow") is None:
			clean.pop("colTitles", None)
		if clean.get("rowHeaderCol") is None:
			clean.pop("rowTitles", None)
		if clean:
			data[key] = clean
		else:
			data.pop(key, None)
		_save()


def reset() -> None:
	"""Olvida la caché (para pruebas)."""
	global _data
	with _lock:
		_data = None


# ================================================================ lógica de la hoja (pura)
class SheetState:
	"""Títulos fijados y celdas vistas de una hoja."""

	def __init__(self, key: str) -> None:
		self.key = key
		self.entry = getEntry(key) if key else {"colHeaderRow": None, "rowHeaderCol": None, "colTitles": {}, "rowTitles": {}}
		self.cells: dict[tuple[int, int], str] = {}
		self.last: tuple[int, int] | None = None

	def learn(self, row: int, col: int, value: str) -> bool:
		"""Recuerda el contenido de una celda. ``True`` si cambió un título guardado."""
		value = (value or "").strip()
		self.cells.pop((row, col), None)
		self.cells[(row, col)] = value
		if len(self.cells) > MAX_CACHED_CELLS:
			self.cells.pop(next(iter(self.cells)))
		changed = False
		e = self.entry
		if e.get("colHeaderRow") == row and e["colTitles"].get(str(col)) != value:
			if value:
				e["colTitles"][str(col)] = value
			else:
				e["colTitles"].pop(str(col), None)
			changed = True
		if e.get("rowHeaderCol") == col and e["rowTitles"].get(str(row)) != value:
			if value:
				e["rowTitles"][str(row)] = value
			else:
				e["rowTitles"].pop(str(row), None)
			changed = True
		return changed

	def setHeader(self, kind: str, row: int, col: int) -> bool:
		"""Fija (o quita, si ya era esa) la fila o columna de títulos. ``True`` si queda fijada."""
		e = self.entry
		if kind == "colHeaderRow":
			if e.get("colHeaderRow") == row:
				e["colHeaderRow"] = None
				e["colTitles"] = {}
				return False
			e["colHeaderRow"] = row
			e["colTitles"] = {str(c): v for (r, c), v in self.cells.items() if r == row and v}
			return True
		if e.get("rowHeaderCol") == col:
			e["rowHeaderCol"] = None
			e["rowTitles"] = {}
			return False
		e["rowHeaderCol"] = col
		e["rowTitles"] = {str(r): v for (r, c), v in self.cells.items() if c == col and v}
		return True

	def titles(self, row: int, col: int) -> tuple[str, str]:
		"""(título de fila, título de columna) de una celda ("" si no se conoce)."""
		e = self.entry
		rowT = colT = ""
		hr, hc = e.get("colHeaderRow"), e.get("rowHeaderCol")
		if hr and row > hr:
			colT = e["colTitles"].get(str(col)) or self.cells.get((hr, col), "")
		if hc and col > hc:
			rowT = e["rowTitles"].get(str(row)) or self.cells.get((row, hc), "")
		return rowT, colT

	def moveAnnouncement(self, row: int, col: int) -> list[str]:
		"""Títulos que se dicen al llegar a una celda: los de la dimensión que cambió."""
		last = self.last
		self.last = (row, col)
		rowT, colT = self.titles(row, col)
		out: list[str] = []
		if rowT and (last is None or last[0] != row):
			out.append(rowT)
		if colT and (last is None or last[1] != col):
			out.append(colT)
		return out


_states: dict[str, SheetState] = {}


def stateFor(key: str) -> SheetState:
	st = _states.get(key)
	if st is None:
		st = _states[key] = SheetState(key)
	return st


# ================================================================ acceso a la página (UIA)
def _uc():
	from ..a11y import uia_client as uc

	return uc


def _documentRoot(element):
	"""Elemento documento (``RootWebArea``) que contiene ``element``."""
	uc = _uc()
	el = element
	for _i in range(60):
		if el is None:
			return None
		try:
			if el.CurrentControlType == 50030:  # documento
				return el
			el = uc.controlWalker.GetParentElement(el)
		except Exception:
			return None
	return None


class _Page:
	"""Elementos de la página de la hoja (se buscan una vez y se reutilizan)."""

	def __init__(self) -> None:
		self.rootId: tuple | None = None
		self.root = None
		self.nameBox = None
		self.formula = None

	def bind(self, element) -> bool:
		uc = _uc()
		root = _documentRoot(element)
		if root is None:
			return False
		rid = uc.runtimeIdOf(root)
		if rid == self.rootId and self.nameBox is not None:
			return True
		self.rootId, self.root, self.nameBox, self.formula = rid, root, None, None
		try:
			self.nameBox = root.FindFirst(uc.TreeScope_Descendants, uc.createPropertyCondition(uc.P_AUTOMATIONID, NAME_BOX_ID))
			# La barra de fórmulas es un cuadro de edición de clase «cell-input...»
			# (el contenedor con su id no siempre está en la vista de controles).
			edits = root.FindAll(uc.TreeScope_Descendants, uc.createPropertyCondition(uc.P_CONTROLTYPE, 50004))
			for i in range(edits.Length if edits else 0):
				el = edits.GetElement(i)
				if str(el.CurrentClassName or "").startswith("cell-input") and el.CurrentAutomationId != EDITOR_ID:
					self.formula = el
					break
		except Exception:
			log.debug("No se encontraron los controles de la hoja", exc_info=True)
		return self.nameBox is not None

	def _value(self, el) -> str:
		if el is None:
			return ""
		try:
			return str(el.GetCurrentPropertyValue(_uc().P_VALUEVALUE) or "")
		except Exception:
			# Rev. 10.11: el elemento caducó (la hoja rehízo sus controles): se
			# olvida para que bind() lo vuelva a buscar; antes los títulos dejaban
			# de funcionar hasta cambiar de documento.
			if el is self.nameBox:
				self.nameBox = None
			if el is self.formula:
				self.formula = None
			return ""

	def url(self) -> str:
		return self._value(self.root)

	def title(self) -> str:
		try:
			return str(self.root.CurrentName or "") if self.root is not None else ""
		except Exception:
			return ""

	def address(self) -> str:
		return self._value(self.nameBox).strip()

	def content(self) -> str:
		return self._value(self.formula).rstrip("\n")


_page = _Page()


# ================================================================ editor de celdas
#: Teclas de movimiento: (modificadores y tecla) → orden de texto que se conserva.
NAV_KEYS = {
	"uparrow": "caret_moveByLine",
	"downarrow": "caret_moveByLine",
	"leftarrow": "caret_moveByCharacter",
	"rightarrow": "caret_moveByCharacter",
	"control+uparrow": "caret_moveByParagraph",
	"control+downarrow": "caret_moveByParagraph",
	"control+leftarrow": "caret_moveByWord",
	"control+rightarrow": "caret_moveByWord",
	"home": "caret_moveByLineBoundary",
	"end": "caret_moveByLineBoundary",
	"pageup": "caret_moveByLineBoundary",
	"pagedown": "caret_moveByLineBoundary",
	"control+home": "caret_moveToDocumentBoundary",
	"control+end": "caret_moveToDocumentBoundary",
	"tab": None,
	"shift+tab": None,
	"enter": None,
	"shift+enter": None,
}


def isSheetsEditor(obj) -> bool:
	try:
		return getattr(obj, "UIAAutomationId", "") == EDITOR_ID
	except Exception:
		return False


class SheetsCellEditor(AccObject):
	"""Editor de celdas de Hojas de cálculo de Google (modo foco)."""

	scriptCategory = CAT

	def _bind(self) -> SheetState | None:
		el = getattr(self, "element", None)
		if el is None or not _page.bind(el):
			return None
		return stateFor(sheetKey(_page.url(), _page.title()))

	def _current(self) -> tuple[SheetState, int, int] | None:
		st = self._bind()
		if st is None:
			return None
		rc = parseCellRef(_page.address())
		if rc is None:
			return None
		if st.learn(rc[0], rc[1], _page.content()):
			putEntry(st.key, st.entry)
		return st, rc[0], rc[1]

	def _afterMove(self, before: str, tries: int = 0) -> None:
		"""Espera a que cambie el cuadro de nombre y dice los títulos nuevos."""
		addr = _page.address()
		if addr == before and tries < 8:
			queue_handler.callLater(50, self._afterMove, before, tries + 1)
			return
		cur = self._current()
		if cur is None or addr == before:
			return
		st, row, col = cur
		titles = st.moveAnnouncement(row, col)
		if titles and conf["googleApps"]["reportHeaders"]:
			speech.speakMessage(", ".join(titles))

	def script_sheetsNavigate(self, gesture) -> None:
		st = self._bind()
		before = _page.address() if st is not None else ""
		key = "+".join(list(gesture.modifierNames) + [gesture.mainKeyName.lower()]) if hasattr(gesture, "modifierNames") else gesture.mainKeyName.lower()
		base = NAV_KEYS.get(key.lower())
		func = getattr(super(), f"script_{base}", None) if base else None
		if func is not None:
			func(gesture)
		else:
			gesture.send()
		if st is not None:
			queue_handler.callLater(60, self._afterMove, before)

	script_sheetsNavigate.__doc__ = _("En Hojas de cálculo de Google: se mueve por las celdas y dice los títulos fijados")
	script_sheetsNavigate.category = CAT  # type: ignore[attr-defined]

	def event_gainFocus(self) -> None:
		super().event_gainFocus()  # type: ignore[misc]
		cur = self._current()
		if cur is not None:
			cur[0].last = (cur[1], cur[2])

	def _setHeader(self, kind: str) -> None:
		cur = self._current()
		if cur is None:
			speech.speakMessage(_("No se encuentra la celda actual de la hoja"))
			return
		st, row, col = cur
		fixed = st.setHeader(kind, row, col)
		putEntry(st.key, st.entry)
		if kind == "colHeaderRow":
			msg = _("La fila {n} contiene los títulos de columna").format(n=row) if fixed else _("Títulos de columna borrados")
		else:
			msg = _("La columna {col} contiene los títulos de fila").format(col=columnLetters(col)) if fixed else _("Títulos de fila borrados")
		speech.speakMessage(msg)

	@script(description=_("Hojas de cálculo de Google: usa la fila actual como títulos de columna (otra vez: los borra)"), category=CAT, gesture="kb:tiresias+control+alt+c")
	def script_setColumnHeaders(self, gesture) -> None:
		self._setHeader("colHeaderRow")

	@script(description=_("Hojas de cálculo de Google: usa la columna actual como títulos de fila (otra vez: los borra)"), category=CAT, gesture="kb:tiresias+control+alt+r")
	def script_setRowHeaders(self, gesture) -> None:
		self._setHeader("rowHeaderCol")

	def _readHeader(self, which: int) -> None:
		cur = self._current()
		if cur is None:
			speech.speakMessage(_("No se encuentra la celda actual de la hoja"))
			return
		st, row, col = cur
		text = st.titles(row, col)[which]
		if text:
			speech.speakText(text)
			return
		e = st.entry
		fixedRow, fixedCol = e.get("colHeaderRow"), e.get("rowHeaderCol")
		if which == 1:
			if not fixedRow:
				speech.speakMessage(_("Sin título de columna. Fíjalo con Tiresias+Control+Alt+C"))
			else:
				speech.speakMessage(_("Título de columna desconocido: pasa una vez por la fila {n}").format(n=fixedRow))
		elif not fixedCol:
			speech.speakMessage(_("Sin título de fila. Fíjalo con Tiresias+Control+Alt+R"))
		else:
			speech.speakMessage(_("Título de fila desconocido: pasa una vez por la columna {col}").format(col=columnLetters(fixedCol)))

	@script(description=_("Hojas de cálculo de Google: lee el título de la columna de la celda actual"), category=CAT, gesture="kb:tiresias+control+shift+c", speakOnDemand=True)
	def script_readColumnHeader(self, gesture) -> None:
		self._readHeader(1)

	@script(description=_("Hojas de cálculo de Google: lee el título de la fila de la celda actual"), category=CAT, gesture="kb:tiresias+control+shift+f", speakOnDemand=True)
	def script_readRowHeader(self, gesture) -> None:
		self._readHeader(0)


for _k in NAV_KEYS:
	from ..baseobject import normalizeGestureId as _norm

	SheetsCellEditor._classGestures[_norm("kb:" + _k)] = "sheetsNavigate"  # type: ignore[attr-defined]


# ================================================================ cuadrículas ARIA
class AriaGridCell(AccObject):
	"""Celda de una cuadrícula ARIA de Google (modo foco): títulos fijados por el usuario."""

	scriptCategory = CAT

	def _key(self) -> str:
		from ..domain_profiles import documentUrl

		url = documentUrl(self)
		return "aria:" + sheetKey(url, "")

	def _coords(self) -> tuple[int, int] | None:
		c = getattr(self, "tableCellCoords", None)
		return (int(c[0]), int(c[1])) if c else None

	def _gridValue(self, row: int, col: int) -> str:
		uc = _uc()
		grid = self.parent
		try:
			pat = grid._pattern(uc.PAT_GRID, uc.UIA.IUIAutomationGridPattern)
			el = pat.GetItem(row - 1, col - 1) if pat else None
			if el is None:
				return ""
			name = el.CurrentName or ""
			return str(name)
		except Exception:
			return ""

	def headerTexts(self) -> tuple[str, str]:
		rc = self._coords()
		e = getEntry(self._key())
		rowT = colT = ""
		if rc:
			if e.get("colHeaderRow") and rc[0] > e["colHeaderRow"]:
				colT = self._gridValue(e["colHeaderRow"], rc[1])
			if e.get("rowHeaderCol") and rc[1] > e["rowHeaderCol"]:
				rowT = self._gridValue(rc[0], e["rowHeaderCol"])
		return rowT, colT

	def reportFocus(self) -> None:
		if conf["googleApps"]["reportHeaders"]:
			titles = [t for t in self.headerTexts() if t]
			if titles:
				speech.speakMessage(", ".join(titles))
		super().reportFocus()

	def _set(self, kind: str) -> None:
		rc = self._coords()
		if rc is None:
			return
		key = self._key()
		e = getEntry(key)
		value = rc[0] if kind == "colHeaderRow" else rc[1]
		e[kind] = None if e.get(kind) == value else value
		putEntry(key, e)
		if kind == "colHeaderRow":
			speech.speakMessage(_("La fila {n} contiene los títulos de columna").format(n=value) if e[kind] else _("Títulos de columna borrados"))
		else:
			speech.speakMessage(_("La columna {n} contiene los títulos de fila").format(n=value) if e[kind] else _("Títulos de fila borrados"))

	@script(description=_("Cuadrícula de Google: usa la fila actual como títulos de columna (otra vez: los borra)"), category=CAT, gesture="kb:tiresias+control+alt+c")
	def script_setColumnHeaders(self, gesture) -> None:
		self._set("colHeaderRow")

	@script(description=_("Cuadrícula de Google: usa la columna actual como títulos de fila (otra vez: los borra)"), category=CAT, gesture="kb:tiresias+control+alt+r")
	def script_setRowHeaders(self, gesture) -> None:
		self._set("rowHeaderCol")

	@script(description=_("Cuadrícula de Google: lee el título de la columna"), category=CAT, gesture="kb:tiresias+control+shift+c", speakOnDemand=True)
	def script_readColumnHeader(self, gesture) -> None:
		t = self.headerTexts()[1]
		speech.speakText(t) if t else speech.speakMessage(_("Sin título de columna. Fíjalo con Tiresias+Control+Alt+C"))

	@script(description=_("Cuadrícula de Google: lee el título de la fila"), category=CAT, gesture="kb:tiresias+control+shift+f", speakOnDemand=True)
	def script_readRowHeader(self, gesture) -> None:
		t = self.headerTexts()[0]
		speech.speakText(t) if t else speech.speakMessage(_("Sin título de fila. Fíjalo con Tiresias+Control+Alt+R"))


def isGoogleGridCell(obj) -> bool:
	"""Celda de cuadrícula ARIA (``gridcell``) dentro de un documento de Google."""
	try:
		if not getattr(obj, "tableCellCoords", None):
			return False
		if str(getattr(obj, "UIAFrameworkId", "") or "") not in ("Chrome", "Gecko", "MicrosoftEdge"):
			return False
		from ..a11y import uia_client as uc

		aria = obj._prop(uc.P_ARIAROLE, "") if hasattr(obj, "_prop") else ""
		if str(aria).lower() != "gridcell":
			return False
		from .. import winapi

		title = winapi.getWindowText(winapi.getAncestor(obj.windowHandle, winapi.GA_ROOT))
		return googleAppFromTitle(title) is not None
	except Exception:
		return False


# ================================================================ complemento global
TIPS = {
	"docs": _("Documento de Google. Si no se lee bien, activa la compatibilidad con lectores de pantalla con Control+Alt+Z y la de braille con Control+Alt+H (menú Herramientas, Accesibilidad)."),
	"sheets": _("Hoja de cálculo de Google. Activa la compatibilidad con lectores de pantalla con Control+Alt+Z. Tiresias+Control+Alt+C y Tiresias+Control+Alt+R fijan la fila y la columna de títulos."),
	"slides": _("Presentación de Google. Si no se lee bien, activa la compatibilidad con lectores de pantalla con Control+Alt+Z y la de braille con Control+Alt+H."),
}


class GlobalPlugin(_BasePlugin):
	"""Detección de Google Docs y Hojas de cálculo en los navegadores."""

	def __init__(self) -> None:
		super().__init__()
		#: Documentos de los que ya se dio el aviso en esta sesión.
		self._tipped: set[str] = set()

	def chooseObjectClass(self, obj, clsList: list[type]) -> None:
		if isSheetsEditor(obj):
			clsList.insert(0, SheetsCellEditor)
		elif isGoogleGridCell(obj):
			clsList.insert(0, AriaGridCell)

	def event_gainFocus(self, obj: Any, nextHandler, **kwargs) -> None:
		nextHandler()
		if not conf["googleApps"]["announceTips"]:
			return
		try:
			from ..domain_profiles import documentUrl

			url = documentUrl(obj)
		except Exception:
			url = ""
		app = googleAppFromUrl(url)
		if app is None:
			return
		doc = documentIdFromUrl(url) or url
		if doc in self._tipped:
			return
		self._tipped.add(doc)
		speech.speakMessage(TIPS[app])
