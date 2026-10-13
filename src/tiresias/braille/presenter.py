"""Presentación braille: qué se muestra en la línea y cómo se desplaza.

:class:`BraillePresenter` es la parte del gestor braille
(``braille.handler``) que decide el contenido de la línea; la gestión de los
controladores (cargar, cambiar, visor espejo, acceso remoto) está en
``braille/__init__.py``.

Modelo: un **búfer principal** de texto (``self.text``) con su traducción a
celdas, el cursor, la selección y las marcas (formato, errores ortográficos,
elemento seleccionado). La línea muestra una **ventana** de ese búfer que se
calcula según el ajuste de texto. Opcionalmente la línea se divide en dos
regiones: la principal a la izquierda y una vista secundaria a la derecha.
"""

from __future__ import annotations

import time
from typing import Any

from .. import api, queue_handler
from ..config import conf
from ..i18n import _
from ..log import getLogger
from ..objects.roles import ROLE_BRAILLE, Role, State, roleLabel
from . import tables

log = getLogger("braille")

#: Teclas físicas pulsadas en la sesión (las cuenta :func:`countKey`). Un mensaje
#: braille deja paso al contenido nuevo si se pulsa una tecla después de mostrarlo.
keyCounter = 0


def countKey(vk: int = 0, scanCode: int = 0, extended: bool = False, pressed: bool = True, injected: bool = False, **kwargs: Any) -> bool:
	"""``decide_handleRawKey`` (hilo de ganchos): solo cuenta; nunca captura la tecla."""
	global keyCounter
	if pressed and not injected:
		keyCounter += 1
	return True

# ---------------------------------------------------------------------- opciones
#: Orden por defecto de las propiedades de un objeto en braille (#7232).
PROPERTY_KEYS = ("name", "role", "value", "states", "level", "position", "itemCount", "table", "placeholder", "description", "shortcut")

DEFAULTS = {
	# «followCursors» (sigue al foco y la revisión) o «speechOutput» (muestra lo que se dice).
	"mode": "followCursors",
	"inputTable": "auto",
	# Celdas por segundo del desplazamiento automático.
	"autoScrollRate": 10,
	# Enrutar en la revisión mueve también el cursor del sistema: never, always, onlyWhenAutoTethered.
	"reviewRoutingMovesSystemCaret": "never",
	"paragraphStartMarker": "",
	# Ajuste del texto (#17010): none, markWordCuts, wordBoundaries, syllableBoundaries.
	"textWrap": "wordBoundaries",
	"unicodeNormalization": False,
	"speakOnRouting": False,
	"speakOnNavigatingByUnit": False,
	"reportLiveRegions": True,
	# Formato del texto: off, liblouis (signos de énfasis de la tabla), dots78 (subrayado).
	"fontFormattingDisplay": "liblouis",
	"showSpellingErrors": True,
	# Emojis descritos con su nombre (#9213).
	"showEmojiNames": True,
	# Caracteres que la tabla no define: hex, allDots, questionMark, omit.
	"undefinedCharacters": "hex",
	# Vista de la región derecha al dividir la línea: off, speech, review, title, clock.
	"splitView": "off",
	"followSayAll": True,
	"markSelectedItem": True,
	"propertyOrder": list(PROPERTY_KEYS),
	"hiddenProperties": ["description", "shortcut"],
	# Abreviaturas de rol del usuario (#4105): nombre del rol -> abreviatura ("" = no mostrar).
	"roleAbbreviations": {},
	# Teclado braille con las teclas del PC: «8» (A S D F J K L Ñ) o «6» (S D F J K L).
	"pcKeyboardDots": 8,
}
conf.registerDefaults("braille", DEFAULTS)
conf.registerDefaults(
	"brailleViewer",
	{
		"showAtStartup": False,
		# Enrutar al dejar el puntero sobre una celda del visor (milisegundos de espera).
		"routeOnHover": False,
		"hoverDwellTime": 1000,
		# Posición de la ventana del visor (-1 = centrada arriba).
		"x": -1,
		"y": -1,
	},
)

TEXT_WRAP_MODES = ("none", "markWordCuts", "wordBoundaries", "syllableBoundaries")
SPLIT_VIEWS = ("off", "speech", "review", "title", "clock")

#: Marca de palabra cortada (puntos 7 y 8).
CONTINUATION_CELL = 0xC0
#: Separador de la línea dividida: dos barras verticales (puntos 1237 y 4568).
SPLIT_SEPARATOR = [0x47, 0xB8]
UNDERLINE = 0xC0

#: Abreviaturas de estados en braille.
#: Marcas invisibles de dirección del texto (fechas de las celdas del Explorador).
_BIDI_MARKS = dict.fromkeys(map(ord, "\u200e\u200f\u202a\u202b\u202c\u202d\u202e"), None)

STATE_BRAILLE: dict[State, str] = {
	State.CHECKED: "(x)",
	State.HALFCHECKED: "(-)",
	State.PRESSED: "=]",
	State.HALF_PRESSED: "=-]",
	State.SELECTED: "sel",
	State.EXPANDED: "-",
	State.COLLAPSED: "+",
	State.UNAVAILABLE: "nd",
	State.READONLY: "sl",
	State.REQUIRED: "obl",
	State.INVALID_ENTRY: "inv",
	State.BUSY: "ocp",
	State.VISITED: "vis",
	State.HASPOPUP: "submnu",
	State.MULTILINE: "mln",
	State.SORTED_ASCENDING: "asc",
	State.SORTED_DESCENDING: "desc",
	State.HASCOMMENT: "cmnt",
	State.HASFORMULA: "frml",
	State.HASNOTE: "nota",
	State.ON: "act",
	State.MODAL: "modal",
}

#: Roles que no se muestran si no tienen abreviatura.
_SILENT_ROLES = {Role.STATICTEXT, Role.PANE, Role.WINDOW, Role.SECTION, Role.UNKNOWN}
#: Roles con número de elementos.
_CONTAINER_ROLES = {Role.LIST, Role.TREEVIEW, Role.MENU, Role.POPUPMENU, Role.TABCONTROL}


def propertyLabels() -> dict[str, str]:
	"""Nombres en español de las propiedades (para las opciones)."""
	return {
		"name": _("Nombre"),
		"role": _("Tipo (rol)"),
		"value": _("Valor"),
		"states": _("Estados"),
		"level": _("Nivel"),
		"position": _("Posición (x de y)"),
		"itemCount": _("Número de elementos de las listas"),
		"table": _("Coordenadas de la celda de tabla"),
		"placeholder": _("Texto de ejemplo de los campos vacíos"),
		"description": _("Descripción"),
		"shortcut": _("Tecla de acceso"),
	}


def roleAbbreviation(role: Role) -> str:
	"""Abreviatura del rol: la del usuario, la incorporada o el nombre completo."""
	user = conf["braille"]["roleAbbreviations"] or {}
	key = role.name if isinstance(role, Role) else str(role)
	if key in user:
		return str(user[key] or "")
	abbr = ROLE_BRAILLE.get(role)
	if abbr is not None:
		return abbr
	if role in _SILENT_ROLES:
		return ""
	return roleLabel(role)


def defaultRoleAbbreviation(role: Role) -> str:
	abbr = ROLE_BRAILLE.get(role)
	if abbr is not None:
		return abbr
	return "" if role in _SILENT_ROLES else roleLabel(role)


def _orderedKeys() -> list[str]:
	order = [k for k in (conf["braille"]["propertyOrder"] or []) if k in PROPERTY_KEYS]
	return order + [k for k in PROPERTY_KEYS if k not in order]


def objectProperties(obj: Any, isFocus: bool = False) -> list[tuple[str, str]]:
	"""Propiedades del objeto ``[(clave, texto)]`` en el orden configurado."""
	b = conf["braille"]
	hidden = set(b["hiddenProperties"] or [])
	try:
		name = obj.name or ""
		role = obj.role
		states = obj.states
	except Exception:
		return []
	try:
		asCell = bool(getattr(obj, "presentAsCell", False))
	except Exception:
		asCell = False
	if asCell:
		# Celda de una fila con otro rol (columnas del Explorador): como una
		# celda, sin «solo lectura» (igual que en la voz).
		role = Role.TABLECELL
	parts: dict[str, str] = {}
	# aria-braillelabel sustituye al nombre en braille (#11829, foros 1.20).
	try:
		brailleName = getattr(obj, "brailleLabel", "") or ""
	except Exception:
		brailleName = ""
	# La etiqueta personalizada del usuario manda sobre todo lo demás (como en la voz).
	try:
		from .. import labels

		userLabel = labels.getLabel(obj) or ""
	except Exception:
		userLabel = ""
	parts["name"] = userLabel or brailleName or name
	if "value" not in hidden:
		try:
			value = obj.value or ""
		except Exception:
			value = ""
		if asCell and value:
			value = " ".join(value.translate(_BIDI_MARKS).split())
		if value and value != name:
			parts["value"] = value
	if "role" not in hidden:
		abbr = roleAbbreviation(role)
		try:
			custom = obj.roleText
		except Exception:
			custom = None
		if custom and custom != roleLabel(role):
			abbr = custom
		if role == Role.HEADING and abbr:
			try:
				level = obj.level
			except Exception:
				level = None
			if level:
				abbr = f"{abbr}{level}"
		try:
			# aria-brailleroledescription sustituye al rol en braille (#11829).
			brailleRole = getattr(obj, "brailleRoleText", "") or ""
		except Exception:
			brailleRole = ""
		parts["role"] = brailleRole or abbr
	if "states" not in hidden:
		st: list[str] = []
		for s in sorted(states, key=int):
			if s == State.SELECTED and (isFocus or role in (Role.TAB, Role.MENUITEM)):
				continue
			if s == State.READONLY and role not in (Role.EDITABLETEXT, Role.DOCUMENT, Role.COMBOBOX, Role.PASSWORDEDIT):
				continue
			if s == State.MULTILINE and role != Role.EDITABLETEXT:
				continue
			label = STATE_BRAILLE.get(s)
			if label:
				st.append(label)
		if role == Role.CHECKBOX and not ({State.CHECKED, State.HALFCHECKED} & states):
			st.insert(0, "( )")
		parts["states"] = " ".join(st)
	try:
		info = obj.positionInfo or {}
	except Exception:
		info = {}
	if "position" not in hidden and "indexInGroup" in info:
		parts["position"] = f"{info['indexInGroup']}/{info['similarItemsInGroup']}"
	if "level" not in hidden and role in (Role.TREEVIEWITEM, Role.LISTITEM) and info.get("level"):
		parts["level"] = _("nv{level}").format(level=info["level"])
	if "itemCount" not in hidden and role in _CONTAINER_ROLES:
		try:
			child = obj.firstChild
			count = (child.positionInfo or {}).get("similarItemsInGroup") if child is not None else None
		except Exception:
			count = None
		if count:
			parts["itemCount"] = _("{n} elem").format(n=count)
	if "table" not in hidden:
		coords = getattr(obj, "tableCellCoords", None)
		try:
			if coords:
				parts["table"] = _("f{row}c{col}").format(row=coords[0], col=coords[1])
		except Exception:
			pass
	if "placeholder" not in hidden and role in (Role.EDITABLETEXT, Role.COMBOBOX) and not parts.get("value"):
		try:
			ph = obj.placeholder
		except Exception:
			ph = ""
		if ph:
			parts["placeholder"] = ph
	if "description" not in hidden:
		try:
			desc = obj.description or ""
		except Exception:
			desc = ""
		if desc and desc != name:
			parts["description"] = desc
	if "shortcut" not in hidden:
		try:
			sc = obj.keyboardShortcut or ""
		except Exception:
			sc = ""
		if sc:
			parts["shortcut"] = sc
	return [(k, parts[k]) for k in _orderedKeys() if parts.get(k) and k not in hidden]


def objectText(obj: Any, isFocus: bool = False, excludeValue: bool = False) -> str:
	return " ".join(t for k, t in objectProperties(obj, isFocus) if not (excludeValue and k == "value"))


# ---------------------------------------------------------------------- presentador
class _Snapshot:
	"""Estado del búfer principal (para restaurarlo tras un mensaje)."""

	__slots__ = ("values",)

	FIELDS = (
		"text",
		"cursorPos",
		"_selection",
		"_marks",
		"_typeform",
		"_regionKind",
		"_regionObj",
		"_regionInfo",
		"_lineStart",
		"_lineLen",
		"_source",
		"windowStart",
		"_objectSpans",
		"_browseOffsets",
	)

	def __init__(self, presenter: "BraillePresenter") -> None:
		self.values = {f: getattr(presenter, f) for f in self.FIELDS}


class BraillePresenter:
	"""Contenido de la línea braille (se mezcla en ``BrailleHandler``)."""

	_browseOffsets: list[int] | None = None

	def _initPresenter(self) -> None:
		self.text = ""
		self.cursorPos: int | None = None
		self.windowStart = 0
		self._translation: tables.Translation | None = None
		self._selection: tuple[int, int] | None = None
		#: Rangos (inicio, fin) del texto subrayados con los puntos 7 y 8.
		self._marks: list[tuple[int, int]] = []
		self._typeform: list[int] | None = None
		self._regionKind = "object"
		self._regionObj: Any = None
		self._regionInfo: Any = None
		#: Posición del texto de la línea dentro del búfer (tras el contexto).
		self._lineStart = 0
		self._lineLen = 0
		self._source = "focus"
		#: Objetos del contexto: (inicio, fin, objeto) para el enrutamiento.
		self._objectSpans: list[tuple[int, int, Any]] = []
		#: Modo exploración: posición en el búfer de cada carácter de una línea
		#: sustituida (aria-braillelabel, matemáticas); ``None`` si es el texto tal cual.
		self._browseOffsets: list[int] | None = None
		self._messageTimer: int | None = None
		self._messageActive = False
		self._saved: _Snapshot | None = None
		self._blinkTimer: int | None = None
		self._cursorVisible = True
		self._lastContext: list = []
		self._focusContext: tuple[Any, str] | None = None
		self._autoScrollTimer: int | None = None
		self._autoScroll = False
		self._updateTimer: int | None = None
		self._splitTimer: int | None = None
		self._inputCells: list[int] = []
		self._lastWindow: tuple[int, int, bool] = (0, 0, False)
		self._speechTime = 0.0

	# ================================================================ utilidades
	@property
	def speechMode(self) -> bool:
		return conf["braille"]["mode"] == "speechOutput"

	def _tether(self) -> str:
		return conf["braille"]["tetherTo"]

	def _outputTable(self) -> tables.Table:
		return tables.getTable(conf["braille"]["translationTable"])

	def _mainWidth(self) -> int:
		n = self.numCells
		if n <= 0:
			return 0
		if conf["braille"]["splitView"] != "off" and not self._messageActive and n >= 20:
			return (n - len(SPLIT_SEPARATOR)) // 2
		return n

	def _translate(self, text: str, cursor: int | None) -> tables.Translation:
		b = conf["braille"]
		table = self._outputTable()
		typeform = self._typeform if (b["fontFormattingDisplay"] == "liblouis" and isinstance(table, tables.LouisTable)) else None
		expand = bool(b["expandAtCursor"]) and cursor is not None and self._regionKind in ("text", "browse")
		return tables.translate(
			table,
			text,
			cursor,
			expandAtCursor=expand,
			typeform=typeform,
			normalize=bool(b["unicodeNormalization"]),
			emoji=bool(b["showEmojiNames"]),
			undefined=b["undefinedCharacters"],
		)

	def retranslate(self) -> None:
		"""Vuelve a traducir el búfer (tras cambiar la tabla u opciones)."""
		if self._translation is None:
			return
		self._translation = self._translate(self.text, self.cursorPos)
		self.windowStart = min(self.windowStart, max(0, len(self._translation.cells) - 1))
		self._ensureCursorVisible()
		self._refresh()

	# ================================================================ región
	def _setRegion(
		self,
		text: str,
		cursor: int | None,
		selection: tuple[int, int] | None = None,
		marks: list[tuple[int, int]] | None = None,
		typeform: list[int] | None = None,
		windowAt: int | None = None,
		keepWindow: bool = False,
	) -> None:
		self._dropMessageIfKeysPressed()
		if self._messageActive:
			# El mensaje se queda; al quitarlo se mostrará este contenido.
			self._applyRegion(text, cursor, selection, marks, typeform)
			self._positionWindow(windowAt, keepWindow)
			self._saved = _Snapshot(self)
			self._restoreMessage()
			return
		self._applyRegion(text, cursor, selection, marks, typeform)
		self._positionWindow(windowAt, keepWindow)
		self._cursorVisible = True
		self._refresh()

	def _applyRegion(self, text, cursor, selection, marks, typeform) -> None:
		self.text = text
		self.cursorPos = cursor
		self._selection = selection
		self._marks = list(marks or [])
		self._typeform = typeform
		self._translation = self._translate(text, cursor)

	def _positionWindow(self, windowAt: int | None, keepWindow: bool) -> None:
		tr = self._translation
		if tr is None:
			return
		if keepWindow and self._cursorInWindow():
			return
		if windowAt is not None:
			self.windowStart = max(0, min(tr.cellForRaw(windowAt), max(0, len(tr.cells) - 1)))
			if self._cursorInWindow() or self.cursorPos is None:
				return
		self.windowStart = 0
		self._ensureCursorVisible()

	def _cursorCell(self) -> int | None:
		tr = self._translation
		if tr is None or self.cursorPos is None:
			return None
		if tr.cursorPos is not None:
			return tr.cursorPos
		return tr.cellForRaw(self.cursorPos)

	def _cursorInWindow(self) -> bool:
		cell = self._cursorCell()
		if cell is None:
			return True
		end, _mark = self._windowEnd(self.windowStart)
		total = len(self._translation.cells)
		if cell >= total and end >= total:
			return self.windowStart <= cell and cell - self.windowStart < self._mainWidth()
		return self.windowStart <= cell < end

	def _ensureCursorVisible(self) -> None:
		cell = self._cursorCell()
		if cell is None or self._mainWidth() <= 0:
			return
		if not self._cursorInWindow():
			self.windowStart = self._windowForCell(cell)

	# ================================================================ ventanas y ajuste
	def _isSpaceCell(self, ci: int) -> bool:
		tr = self._translation
		if tr is None or ci < 0 or ci >= len(tr.cells):
			return True
		raw = tr.brailleToRaw[ci] if ci < len(tr.brailleToRaw) else len(self.text)
		return raw >= len(self.text) or self.text[raw].isspace()

	def _windowEnd(self, start: int) -> tuple[int, bool]:
		"""Fin (exclusivo) de la ventana que empieza en ``start`` y si lleva
		marca de palabra cortada."""
		tr = self._translation
		n = self._mainWidth()
		if tr is None or n <= 0:
			return start, False
		total = len(tr.cells)
		if start + n >= total:
			return total, False
		mode = conf["braille"]["textWrap"]
		limit = start + n
		if mode == "none" or n < 4:
			return limit, False
		midCut = not self._isSpaceCell(limit - 1) and not self._isSpaceCell(limit)
		if not midCut:
			return limit, False
		if mode == "markWordCuts":
			return limit - 1, True
		b = limit
		while b > start and not self._isSpaceCell(b - 1):
			b -= 1
		if mode == "syllableBoundaries":
			cut = self._syllableCut(b if b > start else start, limit - 1)
			if cut is not None:
				return cut, True
		if b > start:
			return b, False
		# Palabra más larga que la línea: se corta y se marca.
		return limit - 1, True

	def _syllableCut(self, wordStartCell: int, maxCell: int) -> int | None:
		tr = self._translation
		if tr is None or wordStartCell >= len(tr.brailleToRaw):
			return None
		rawStart = tr.brailleToRaw[wordStartCell]
		rawEnd = rawStart
		while rawEnd < len(self.text) and not self.text[rawEnd].isspace():
			rawEnd += 1
		word = self.text[rawStart:rawEnd]
		points = tables.hyphenationPoints(self._outputTable(), word)
		for p in reversed(points):
			cell = tr.cellForRaw(rawStart + p)
			if wordStartCell < cell <= maxCell:
				return cell
		return None

	def _windowForCell(self, cell: int) -> int:
		tr = self._translation
		if tr is None:
			return 0
		total = len(tr.cells)
		start = 0
		for _i in range(100000):
			end, _mark = self._windowEnd(start)
			if cell < end or end >= total or end <= start:
				if cell >= total and end >= total and cell - start >= self._mainWidth() and end > start:
					return end
				return start
			start = end
		return start

	def _previousWindowStart(self, current: int) -> int:
		n = self._mainWidth()
		start = max(0, current - n)
		if conf["braille"]["textWrap"] in ("wordBoundaries", "syllableBoundaries") and start > 0:
			s = start
			while s < current and not self._isSpaceCell(s - 1):
				s += 1
			if s < current:
				start = s
		return start

	# ================================================================ dibujo
	def _cellLabels(self, start: int, end: int) -> list[str]:
		tr = self._translation
		labels: list[str] = []
		if tr is None:
			return labels
		b2r = tr.brailleToRaw
		for ci in range(start, end):
			raw = b2r[ci] if ci < len(b2r) else len(self.text)
			if ci > start and ci - 1 < len(b2r) and b2r[ci - 1] == raw:
				labels.append("")
				continue
			nxt = ci + 1
			while nxt < len(b2r) and b2r[nxt] == raw:
				nxt += 1
			rawNext = b2r[nxt] if nxt < len(b2r) else len(self.text)
			if rawNext <= raw:
				rawNext = raw + 1
			labels.append(self.text[raw:rawNext].replace("\n", " ").replace("\t", " "))
		return labels

	def _cursorShape(self) -> int:
		shape = conf["braille"]["cursorShapeReview"] if self._source == "review" else conf["braille"]["cursorShapeFocus"]
		try:
			return int(shape) & 0xFF
		except (TypeError, ValueError):
			return 0xC0

	def _refresh(self) -> None:
		n = self.numCells
		if n <= 0:
			return
		if self._remoteCells is not None and not self._messageActive:
			# Acceso remoto: la línea muestra lo que envía el equipo controlado.
			self._writeCells(self._remoteCells, "")
			return
		tr = self._translation
		if tr is None:
			return
		b = conf["braille"]
		mainW = self._mainWidth()
		ws = max(0, min(self.windowStart, len(tr.cells)))
		we, mark = self._windowEnd(ws)
		self._lastWindow = (ws, we, mark)
		cells = list(tr.cells[ws:we])
		labels = self._cellLabels(ws, we)
		b2r = tr.brailleToRaw
		if not self._messageActive:
			sel = self._selection if b["showSelection"] else None
			for i, ci in enumerate(range(ws, we)):
				raw = b2r[ci] if ci < len(b2r) else -1
				if sel and sel[0] <= raw < sel[1]:
					cells[i] |= UNDERLINE
				for m0, m1 in self._marks:
					if m0 <= raw < m1:
						cells[i] |= UNDERLINE
						break
		cells += [0] * (mainW - len(cells))
		labels += [""] * (mainW - len(labels))
		if mark and we - ws < mainW:
			cells[we - ws] = CONTINUATION_CELL
		cursorCell = self._cursorCell()
		if cursorCell is not None and not self._messageActive:
			rel = cursorCell - ws
			if self._inputCells and 0 <= rel < mainW:
				# Celdas escritas con el teclado braille que aún no se han traducido.
				for k, c in enumerate(self._inputCells):
					if rel + k < mainW:
						cells[rel + k] = c
				rel = min(mainW - 1, rel + len(self._inputCells))
			if b["showCursor"] and self._cursorVisible and 0 <= rel < mainW:
				cells[rel] |= self._cursorShape()
		cells = cells[:mainW]
		labels = labels[:mainW]
		if mainW < n:
			secondary = self._secondaryCells(n - mainW - len(SPLIT_SEPARATOR))
			cells += SPLIT_SEPARATOR + secondary
			labels += ["|", "|"] + [""] * len(secondary)
		self._writeCells(cells, "".join(labels), labels)
		from . import post_displayUpdate

		post_displayUpdate.notify(cells=cells, text=self.text)

	# ================================================================ línea dividida
	def _secondaryText(self) -> str:
		view = conf["braille"]["splitView"]
		try:
			if view == "speech":
				from .. import speech

				return speech.getLastSpokenText()
			if view == "review":
				from .. import textinfo

				pos = api.getReviewPosition()
				if pos is None:
					nav = api.getNavigatorObject()
					return objectText(nav) if nav is not None else ""
				line = pos.copy()
				line.expand(textinfo.UNIT_LINE)
				return line.text.rstrip("\r\n")
			if view == "title":
				fg = api.getForegroundObject()
				return fg.name if fg is not None else ""
			if view == "clock":
				return time.strftime("%H:%M %d/%m/%Y")
		except Exception:
			log.debug("Error obteniendo la vista secundaria", exc_info=True)
		return ""

	def _secondaryCells(self, width: int) -> list[int]:
		if width <= 0:
			return []
		text = self._secondaryText()
		try:
			cells = tables.translate(self._outputTable(), text, emoji=bool(conf["braille"]["showEmojiNames"])).cells if text else []
		except Exception:
			cells = []
		return (cells + [0] * width)[:width]

	def updateSplit(self) -> None:
		"""Programa el refresco periódico de la vista secundaria (reloj, título)."""
		if self._splitTimer is not None:
			queue_handler.cancelCallLater(self._splitTimer)
			self._splitTimer = None
		if conf["braille"]["splitView"] in ("clock", "title") and self.enabled:
			self._splitTimer = queue_handler.callLater(15000, self._splitTick)

	def _splitTick(self) -> None:
		self._splitTimer = None
		self._refresh()
		self.updateSplit()

	def onSpeech(self, text: str) -> None:
		"""Se ha pedido hablar ``text`` (modo «mostrar voz» y vista de voz)."""
		if not self.enabled or not text.strip():
			return
		if self.speechMode:
			self._regionKind = "speech"
			self._regionObj = None
			self._regionInfo = None
			self._source = "focus"
			self._objectSpans = []
			self._lineStart = 0
			self._lineLen = len(text)
			if self._messageActive:
				self._cancelMessageTimer()
				self._messageActive = False
				self._saved = None
			self._setRegion(text, None)
		elif conf["braille"]["splitView"] == "speech" and not self._messageActive:
			self._refresh()

	# ================================================================ parpadeo
	def _updateBlink(self) -> None:
		"""Programa el parpadeo del cursor según las opciones."""
		if self._blinkTimer is not None:
			queue_handler.cancelCallLater(self._blinkTimer)
			self._blinkTimer = None
		self._cursorVisible = True
		b = conf["braille"]
		if self.enabled and b["showCursor"] and b["cursorBlink"]:
			self._blinkTimer = queue_handler.callLater(max(100, int(b["cursorBlinkRate"])), self._blink)

	def _blink(self) -> None:
		self._blinkTimer = None
		if not self.enabled:
			return
		b = conf["braille"]
		if not (b["showCursor"] and b["cursorBlink"]):
			self._cursorVisible = True
			self._refresh()
			return
		if self.cursorPos is not None and not self._messageActive:
			self._cursorVisible = not self._cursorVisible
			self._refresh()
		self._blinkTimer = queue_handler.callLater(max(100, int(b["cursorBlinkRate"])), self._blink)

	def _rawIndex(self, cellIndex: int) -> int:
		if self._translation is None or not self._translation.brailleToRaw:
			return 0
		cellIndex = max(0, min(cellIndex, len(self._translation.brailleToRaw) - 1))
		return self._translation.brailleToRaw[cellIndex]

	# ================================================================ objetos
	@staticmethod
	def objectText(obj: Any) -> str:
		return objectText(obj)

	def _contextAncestors(self) -> list:
		try:
			return [a for a in api.getFocusAncestors()[1:] if a.name and a.presentationType == "content" and a.role != Role.WINDOW]
		except Exception:
			return []

	def _computeContext(self, obj: Any) -> list[tuple[str, Any]]:
		"""Antecesores del foco según «Presentación del contexto del foco»."""
		mode = conf["braille"]["focusContextPresentation"]
		ancestors = self._contextAncestors()
		if mode == "changedContext":
			old = self._lastContext
			shown = [a for a in ancestors if a not in old]
		else:
			shown = ancestors
		self._lastContext = ancestors
		out = []
		for a in shown:
			t = objectText(a)
			if t:
				out.append((t, a))
		return out

	def _focusPrefix(self, obj: Any, fresh: bool, includeValue: bool) -> tuple[str, list[tuple[int, int, Any]], list[tuple[int, int]]]:
		"""Contexto + propiedades del objeto con foco: (texto, tramos, marcas)."""
		if fresh or self._focusContext is None or self._focusContext[0] != obj:
			self._focusContext = (obj, self._computeContext(obj))
		context = self._focusContext[1]
		text = ""
		spans: list[tuple[int, int, Any]] = []
		marks: list[tuple[int, int]] = []
		for t, a in context:
			start = len(text)
			text += t + " "
			spans.append((start, start + len(t), a))
		props = objectProperties(obj, isFocus=True)
		if not includeValue:
			props = [(k, t) for k, t in props if k != "value"]
		start = len(text)
		for k, t in props:
			if k == "name" and self._shouldMarkSelected(obj):
				marks.append((len(text), len(text) + len(t)))
			text += t + " "
		spans.append((start, len(text), obj))
		return text.rstrip(" "), spans, marks

	@staticmethod
	def _shouldMarkSelected(obj: Any) -> bool:
		if not conf["braille"]["markSelectedItem"]:
			return False
		try:
			return State.SELECTED in obj.states and obj.role in (Role.LISTITEM, Role.TREEVIEWITEM, Role.MENUITEM, Role.TAB, Role.DATAITEM, Role.RADIOBUTTON)
		except Exception:
			return False

	def handleObject(self, obj: Any, reason: Any = None, keepWindow: bool = False) -> None:
		if not self.enabled or self.speechMode:
			return
		reasonName = getattr(reason, "value", reason) or "focus"
		try:
			isFocus = obj == api.getFocusObject()
		except Exception:
			isFocus = False
		tether = self._tether()
		if isFocus or reasonName != "query":
			# Foco y primer plano: siguen al foco (salvo «seguir a la revisión»).
			if tether == "review" and reasonName != "query":
				return
			source = "focus"
		else:
			# Consulta de otro objeto (navegación de objetos): es la revisión.
			if tether == "focus":
				return
			source = "review"
		fresh = reasonName in ("focus", "foreground")
		if fresh and isFocus:
			try:
				from . import input as brailleInput

				brailleInput.handler.onFocusChange()
			except Exception:
				log.debug("Error reiniciando la entrada braille", exc_info=True)
		self._regionObj = obj
		self._source = source
		try:
			if isFocus and obj.hasText:
				from .. import textinfo

				info = obj.makeTextInfo(textinfo.POSITION_CARET)
				self._showText(info, "focus", fresh=fresh, keepWindow=keepWindow)
				return
		except Exception:
			log.debug("Sin texto en el foco", exc_info=True)
		self._regionKind = "object"
		self._regionInfo = None
		if isFocus:
			text, spans, marks = self._focusPrefix(obj, fresh, includeValue=True)
		else:
			props = objectProperties(obj)
			text = " ".join(t for _k, t in props)
			spans = [(0, len(text), obj)]
			marks = []
			if props and props[0][0] == "name" and self._shouldMarkSelected(obj):
				marks.append((0, len(props[0][1])))
		self._objectSpans = spans
		objStart = spans[-1][0] if spans else 0
		self._lineStart = objStart
		self._lineLen = len(text) - objStart
		self._applyRegionAndWindow(text, objStart, marks, keepWindow)

	def _applyRegionAndWindow(self, text: str, objStart: int, marks: list, keepWindow: bool) -> None:
		mode = conf["braille"]["focusContextPresentation"]
		self._dropMessageIfKeysPressed()
		if self._messageActive:
			self._setRegion(text, None, marks=marks, windowAt=objStart if mode == "scroll" else None)
			return
		self._applyRegion(text, None, None, marks, None)
		tr = self._translation
		n = self._mainWidth()
		if keepWindow and self.windowStart < len(tr.cells):
			pass
		elif mode == "scroll":
			self.windowStart = tr.cellForRaw(objStart) if objStart < len(text) else 0
		elif n and len(tr.cells) > n:
			# Se llena la línea con el contexto que quepa a la izquierda del objeto.
			objCell = tr.cellForRaw(objStart) if objStart < len(text) else 0
			self.windowStart = max(0, min(objCell, len(tr.cells) - n))
		else:
			self.windowStart = 0
		self._cursorVisible = True
		self._refresh()

	def handleUpdate(self, obj: Any) -> None:
		if not self.enabled or self.speechMode or obj != self._regionObj:
			return
		if self._regionKind == "object":
			self.handleObject(obj, "change", keepWindow=True)
		elif self._regionKind == "text":
			self.scheduleFocusUpdate()

	# ================================================================ texto
	def handleCaretMove(self, info: Any, prefix: str = "", source: str = "focus") -> None:
		if source == "focus":
			# La entrada braille empieza palabra nueva si el cursor se ha movido
			# por otra causa que su propia escritura (también sin línea: teclado del PC).
			try:
				from . import input as brailleInput

				brailleInput.handler.onCaretMove()
			except Exception:
				log.debug("Error avisando a la entrada braille", exc_info=True)
		if not self.enabled or self.speechMode:
			return
		if source == "focus":
			if self._tether() == "review":
				return
			if not self._followingSayAll():
				return
		self._showText(info, source, fresh=False, keepWindow=True)

	def _followingSayAll(self) -> bool:
		if conf["braille"]["followSayAll"]:
			return True
		try:
			from ..speech import sayall

			return not sayall.isRunning()
		except Exception:
			return True

	def _showText(self, info: Any, source: str, fresh: bool = False, keepWindow: bool = False) -> None:
		from .. import textinfo

		b = conf["braille"]
		unit = textinfo.UNIT_PARAGRAPH if b["readByParagraph"] else textinfo.UNIT_LINE
		try:
			line = info.copy()
			line.expand(unit)
			text = line.text.rstrip("\r\n")
			start = line.copy()
			start.collapse()
			caret = info.copy()
			caret.collapse()
			pre = start.copy()
			pre.setEndPoint(caret, "endToStart")
			cursor = min(len(pre.text), len(text))
		except Exception:
			log.debug("No se pudo leer la línea para braille", exc_info=True)
			return
		obj = getattr(info, "obj", None)
		sameLine = False
		if keepWindow and self._regionKind == "text" and self._regionInfo is not None and self._source == source:
			try:
				sameLine = self._regionInfo.obj is obj and self._regionInfo.compareEndPoints(start, "startToStart") == 0
			except Exception:
				sameLine = False
		prefix = ""
		spans: list[tuple[int, int, Any]] = []
		marks: list[tuple[int, int]] = []
		if source == "focus" and obj is not None:
			try:
				isFocus = obj == api.getFocusObject()
			except Exception:
				isFocus = False
			if isFocus:
				prefix, spans, marks = self._focusPrefix(obj, fresh, includeValue=False)
		marker = b["paragraphStartMarker"] if b["readByParagraph"] else ""
		offset = len(prefix) + (1 if prefix else 0) + len(marker)
		full = (prefix + " " if prefix else "") + marker + text
		selection = None
		if source == "focus" and b["showSelection"]:
			selection = self._selectionRange(info, start, len(text))
			if selection is not None:
				selection = (selection[0] + offset, selection[1] + offset)
		lineMarks, typeform = self._formatMarks(line, text)
		marks += [(a + offset, e + offset) for a, e in lineMarks]
		if typeform is not None:
			typeform = [0] * offset + typeform
		self._regionKind = "text"
		self._regionObj = obj
		self._regionInfo = start
		self._source = source
		self._objectSpans = spans
		self._lineStart = offset
		self._lineLen = len(text)
		self._setRegion(full, offset + cursor, selection, marks, typeform, keepWindow=sameLine)

	def _selectionRange(self, info: Any, lineStart: Any, lineLen: int) -> tuple[int, int] | None:
		from .. import textinfo

		try:
			sel = info.obj.makeTextInfo(textinfo.POSITION_SELECTION)
			if sel.isCollapsed:
				return None
			# Inicio de la selección relativo a la línea (puede empezar antes).
			s0 = sel.copy()
			s0.collapse()
			if s0.compareEndPoints(lineStart, "startToStart") <= 0:
				a = 0
			else:
				r = lineStart.copy()
				r.setEndPoint(s0, "endToStart")
				a = len(r.text)
			s1 = sel.copy()
			s1.collapse(end=True)
			if s1.compareEndPoints(lineStart, "startToStart") <= 0:
				return None
			r = lineStart.copy()
			r.setEndPoint(s1, "endToStart")
			e = min(lineLen, len(r.text))
			if e <= a:
				return None
			return (a, e)
		except Exception:
			return None

	def _formatMarks(self, line: Any, text: str) -> tuple[list[tuple[int, int]], list[int] | None]:
		"""Errores ortográficos y formato de la línea: (marcas, typeform)."""
		b = conf["braille"]
		fmtMode = b["fontFormattingDisplay"]
		wantSpelling = bool(b["showSpellingErrors"])
		if not (wantSpelling or fmtMode != "off") or not text or len(text) > 600:
			return [], None
		getter = getattr(line, "getFormatInfo", None)
		if getter is None or type(line).getFormatInfo is _BaseGetFormat():
			return [], None
		from .. import textinfo

		keys = {"spellingError", "fontWeight", "italic", "underline"}
		marks: list[tuple[int, int]] = []
		typeform = [0] * len(text) if fmtMode == "liblouis" else None
		anyFormat = False
		try:
			pos = 0
			run = line.copy()
			run.collapse()
			for _i in range(80):
				nxt = run.copy()
				if not nxt.move(textinfo.UNIT_FORMAT, 1, endPoint="end"):
					break
				if nxt.compareEndPoints(line, "endToEnd") > 0:
					nxt.setEndPoint(line, "endToEnd")
				runText = nxt.text
				if not runText:
					break
				try:
					fmt = nxt.getFormatInfo(keys)
				except TypeError:
					fmt = nxt.getFormatInfo()
				end = min(len(text), pos + len(runText))
				bold = (fmt.get("fontWeight") or 0) >= 600
				italic = bool(fmt.get("italic"))
				underline = bool(fmt.get("underline"))
				if wantSpelling and fmt.get("spellingError"):
					marks.append((pos, end))
				if fmtMode == "dots78" and (bold or italic or underline):
					marks.append((pos, end))
				if typeform is not None and (bold or italic or underline):
					from . import liblouis

					val = (liblouis.BOLD if bold else 0) | (liblouis.ITALIC if italic else 0) | (liblouis.UNDERLINE if underline else 0)
					for i in range(pos, end):
						typeform[i] = val
					anyFormat = True
				pos = end
				if pos >= len(text) or nxt.compareEndPoints(line, "endToEnd") >= 0:
					break
				run = nxt.copy()
				run.collapse(end=True)
		except Exception:
			log.debug("No se pudo leer el formato para braille", exc_info=True)
		return marks, (typeform if anyFormat else None)

	def handleReviewMove(self, info: Any = None, isCaret: bool = False) -> None:
		"""Movimiento del cursor de revisión (si el braille lo sigue)."""
		if not self.enabled or info is None or self.speechMode:
			return
		tether = self._tether()
		if tether == "focus" or (tether == "auto" and isCaret):
			return
		self._showText(info, "review", keepWindow=True)

	def handleNavigatorObject(self, obj: Any = None, **kwargs: Any) -> None:
		"""Cambio del objeto navegador: con «seguir a la revisión» se muestra."""
		if not self.enabled or obj is None or self.speechMode or self._tether() != "review":
			return
		try:
			if obj == api.getFocusObject():
				self._regionObj = obj
				self._source = "review"
				self._regionKind = "object"
				props = objectProperties(obj)
				text = " ".join(t for _k, t in props)
				self._objectSpans = [(0, len(text), obj)]
				self._lineStart = 0
				self._lineLen = len(text)
				self._applyRegionAndWindow(text, 0, [], False)
				return
		except Exception:
			pass
		self.handleObject(obj, "query")

	def handleBrowseLine(self, text: str, cursor: int, offsets: list[int] | None = None) -> None:
		"""Línea del modo exploración.

		``offsets`` da, si la línea está sustituida (aria-braillelabel,
		matemáticas), la posición en el búfer de cada carácter de ``text``.
		"""
		if not self.enabled or self.speechMode or self._tether() == "review":
			return
		if not self._followingSayAll():
			return
		text = text.rstrip("\n")
		sameLine = self._regionKind == "browse" and text == self.text[self._lineStart :]
		self._browseOffsets = list(offsets[: len(text)]) if offsets else None
		self._regionKind = "browse"
		self._regionObj = None
		self._regionInfo = None
		self._source = "focus"
		self._objectSpans = []
		self._lineStart = 0
		self._lineLen = len(text)
		self._setRegion(text, max(0, min(cursor, len(text))), keepWindow=sameLine)

	def handleCustom(self, text: str, cursor: int | None = None, owner: Any = None, selection: tuple[int, int] | None = None) -> None:
		"""Región propia de un componente (p. ej. la exploración de matemáticas).

		``text`` puede llevar caracteres braille Unicode, que pasan tal cual.
		Los pulsadores de enrutamiento llaman a ``owner.routeTo(índice)`` con
		el índice del carácter de ``text``.
		"""
		if not self.enabled or self.speechMode:
			return
		same = self._regionKind == "custom" and self._regionObj is owner
		self._regionKind = "custom"
		self._regionObj = owner
		self._regionInfo = None
		self._source = "focus"
		self._objectSpans = []
		self._lineStart = 0
		self._lineLen = len(text)
		if cursor is not None:
			cursor = max(0, min(cursor, len(text)))
		self._setRegion(text, cursor, selection, keepWindow=same)

	def handleSayAllLine(self, info: Any, isCaret: bool) -> None:
		"""Lectura continua: la línea que se empieza a leer."""
		if not self.enabled or self.speechMode or not conf["braille"]["followSayAll"]:
			return
		self._showText(info, "focus" if isCaret else "review")

	def handleLiveRegion(self, obj: Any) -> None:
		if not conf["braille"]["reportLiveRegions"]:
			return
		try:
			text = obj.name or obj.value
		except Exception:
			text = ""
		if text:
			self.message(text)

	# ================================================================ actualización al escribir
	def scheduleFocusUpdate(self, delay: int = 40) -> None:
		"""Refresca la región del foco en breve (agrupa ráfagas de eventos)."""
		if not self.enabled or self.speechMode or self._updateTimer is not None:
			return
		self._updateTimer = queue_handler.callLater(delay, self._doFocusUpdate)

	def _doFocusUpdate(self) -> None:
		self._updateTimer = None
		if not self.enabled or self.speechMode:
			return
		focus = api.getFocusObject()
		if focus is None:
			return
		ti = getattr(focus, "treeInterceptor", None)
		if ti is not None and not getattr(ti, "passThrough", True):
			return
		if self._regionKind in ("browse", "custom"):
			return
		try:
			if focus.hasText:
				from .. import textinfo

				if self._tether() == "review" or not self._followingSayAll():
					return
				info = focus.makeTextInfo(textinfo.POSITION_CARET)
				self._showText(info, "focus", keepWindow=True)
				return
		except Exception:
			log.debug("Error actualizando el texto en braille", exc_info=True)
		if self._regionObj == focus and self._regionKind == "object":
			self.handleObject(focus, "change", keepWindow=True)

	def onEvent(self, eventName: str = "", obj: Any = None, **kwargs: Any) -> None:
		"""Eventos procesados (``events.post_event``)."""
		if eventName in ("caret", "typedCharacter"):
			# Cursor movido o tecla escrita con el teclado normal: la entrada
			# braille empieza palabra nueva (salvo si lo ha causado ella misma).
			try:
				from . import input as brailleInput

				brailleInput.handler.onCaretMove()
			except Exception:
				log.debug("Error avisando a la entrada braille", exc_info=True)
		if not self.enabled:
			return
		if eventName == "liveRegionChange":
			self.handleLiveRegion(obj)
			return
		if eventName not in ("caret", "textChange", "valueChange", "typedCharacter", "nameChange", "stateChange", "descriptionChange"):
			return
		try:
			if obj != api.getFocusObject():
				return
		except Exception:
			return
		self.scheduleFocusUpdate(60 if eventName == "typedCharacter" else 30)

	# ================================================================ mensajes
	def message(self, text: str) -> None:
		if not self.enabled or not text or conf["braille"]["showMessages"] == "disabled":
			return
		if self.speechMode:
			# En el modo «mostrar voz» el mensaje ya llega como voz.
			return
		if not self._messageActive:
			self._saved = _Snapshot(self)
		self._messageActive = False
		self._regionKind = "message"
		self._regionObj = None
		self._regionInfo = None
		self._objectSpans = []
		self._lineStart = 0
		self._lineLen = len(text)
		self._applyRegion(text, None, None, None, None)
		self.windowStart = 0
		self._messageActive = True
		self._messageKeyCount = keyCounter
		self._messageState = (_Snapshot(self), self._translation)
		self._refresh()
		self._restartMessageTimer()

	def _restartMessageTimer(self) -> None:
		self._cancelMessageTimer()
		if conf["braille"]["showMessages"] == "timeout":
			self._messageTimer = queue_handler.callLater(int(float(conf["braille"]["messageTimeout"]) * 1000), self._dismissMessage)

	def _cancelMessageTimer(self) -> None:
		if self._messageTimer is not None:
			queue_handler.cancelCallLater(self._messageTimer)
			self._messageTimer = None

	def _restoreMessage(self) -> None:
		"""Tras guardar el contenido de fondo, vuelve a dejar el mensaje en el búfer."""
		msg = self._messageState
		if msg is None:
			return
		snap, translation = msg
		for k, v in snap.values.items():
			setattr(self, k, v)
		self._translation = translation

	_messageState: tuple[_Snapshot, Any] | None = None
	#: Valor de :data:`keyCounter` al mostrar el mensaje.
	_messageKeyCount = 0

	def _dropMessageIfKeysPressed(self) -> bool:
		"""Como NVDA: si se ha pulsado una tecla desde que apareció el mensaje, el
		contenido nuevo (foco, cursor, cambios) lo sustituye en vez de esperar a
		que caduque. ``True`` si se ha quitado."""
		if not self._messageActive or keyCounter <= self._messageKeyCount:
			return False
		self._cancelMessageTimer()
		self._messageActive = False
		self._messageState = None
		self._saved = None
		return True

	def _dismissMessage(self) -> None:
		self._cancelMessageTimer()
		if not self._messageActive:
			return
		self._messageActive = False
		self._messageState = None
		saved = self._saved
		self._saved = None
		if saved is not None:
			for k, v in saved.values.items():
				setattr(self, k, v)
			self._translation = self._translate(self.text, self.cursorPos)
		self._cursorVisible = True
		self._refresh()

	@property
	def messageActive(self) -> bool:
		return self._messageActive

	# ================================================================ desplazamiento
	def _interruptSpeech(self) -> None:
		if conf["braille"]["interruptSpeechWhileScrolling"]:
			from .. import speech

			speech.cancelSpeech()

	def scrollForward(self, auto: bool = False) -> bool:
		"""Avanza la ventana. Devuelve ``False`` si no se ha podido avanzar."""
		n = self._mainWidth()
		tr = self._translation
		if n <= 0 or tr is None:
			return False
		if not auto:
			self._interruptSpeech()
		end, _mark = self._windowEnd(self.windowStart)
		if end < len(tr.cells):
			self.windowStart = end
			self._refresh()
			if self._messageActive:
				self._messageState = (_Snapshot(self), self._translation)
				self._restartMessageTimer()
			return True
		if self._messageActive:
			# Al pasar del final de un mensaje, se quita (#15697).
			self._dismissMessage()
			return True
		return self._moveLine(1, auto=auto)

	def scrollBack(self) -> bool:
		n = self._mainWidth()
		if n <= 0 or self._translation is None:
			return False
		self._interruptSpeech()
		if self.windowStart > 0:
			self.windowStart = self._previousWindowStart(self.windowStart)
			self._refresh()
			if self._messageActive:
				self._messageState = (_Snapshot(self), self._translation)
				self._restartMessageTimer()
			return True
		if self._messageActive:
			return False
		return self._moveLine(-1)

	def _moveLine(self, direction: int, auto: bool = False, toStart: bool = False) -> bool:
		if self._regionKind == "browse":
			return self._moveBrowseLine(direction, auto, toStart)
		if self._regionKind != "text" or self._regionInfo is None:
			return False
		from .. import textinfo

		unit = textinfo.UNIT_PARAGRAPH if conf["braille"]["readByParagraph"] else textinfo.UNIT_LINE
		info = self._regionInfo.copy()
		if not info.move(unit, direction):
			return False
		if direction < 0 and not toStart:
			# Al retroceder, el cursor va al último carácter de la línea anterior
			# (como NVDA): así el evento de cursor posterior deja la ventana al final.
			try:
				last = info.copy()
				last.expand(unit)
				last.collapse(end=True)
				if last.move(textinfo.UNIT_CHARACTER, -1) and last.compareEndPoints(info, "startToStart") >= 0:
					info = last
			except Exception:
				log.debug("No se pudo ir al final de la línea anterior", exc_info=True)
		source = self._source
		if source == "focus":
			try:
				info.updateCaret()
			except Exception:
				log.debug("No se pudo mover el cursor del sistema", exc_info=True)
		else:
			api.setReviewPosition(info)
		self._showText(info, source)
		if direction < 0 and not toStart and self._translation is not None:
			# Al retroceder se muestra el final de la línea anterior.
			total = len(self._translation.cells)
			self.windowStart = self._windowForCell(max(0, total - 1))
			self._refresh()
		if conf["braille"]["speakOnNavigatingByUnit"] and not auto:
			from .. import presentation

			presentation.speakTextInfo(info, unit, reason=presentation.Reason.REVIEW if source == "review" else presentation.Reason.CARET)
		return True

	def _moveBrowseLine(self, direction: int, auto: bool, toStart: bool) -> bool:
		"""Desplazamiento entre líneas del modo exploración (mueve su cursor virtual)."""
		from .. import textinfo

		doc = api.getCaretObject()
		buf = getattr(doc, "buffer", None)
		if not buf or not buf.text:
			return False
		start, end = buf.lineBounds(doc.caret)
		if direction > 0:
			if end >= len(buf.text):
				return False
			target = end
		else:
			if start <= 0:
				return False
			target = buf.lineBounds(start - 1)[0]
		speak = bool(conf["braille"]["speakOnNavigatingByUnit"]) and not auto
		try:
			if speak:
				doc._moveCaret(target, speakUnit=textinfo.UNIT_LINE)
			else:
				# Sin voz (y sin cortar la que esté sonando): se mueve el cursor
				# virtual y se refresca la línea braille.
				doc.caret = target
				doc.selectionAnchor = None
				doc._afterCaretMove(buf.nodeAt(target))
				doc._updateBraille(*buf.lineBounds(target))
		except Exception:
			log.debug("No se pudo mover el cursor virtual", exc_info=True)
			return False
		if direction < 0 and not toStart and self._regionKind == "browse" and self._translation is not None:
			# Al retroceder se muestra el final de la línea anterior.
			total = len(self._translation.cells)
			self.windowStart = self._windowForCell(max(0, total - 1))
			self._refresh()
		return True

	def nextLine(self) -> bool:
		"""Línea siguiente de la región (fuera del texto: la revisión)."""
		return self._moveLine(1, toStart=True)

	def previousLine(self) -> bool:
		return self._moveLine(-1, toStart=True)

	# ---------------------------------------------------------- automático
	@property
	def autoScrollActive(self) -> bool:
		return self._autoScroll

	def setAutoScroll(self, on: bool) -> None:
		self._autoScroll = bool(on) and self.enabled
		self._scheduleAutoScroll()

	def _scheduleAutoScroll(self) -> None:
		if self._autoScrollTimer is not None:
			queue_handler.cancelCallLater(self._autoScrollTimer)
			self._autoScrollTimer = None
		if not self._autoScroll:
			return
		rate = max(1, min(20, int(conf["braille"]["autoScrollRate"] or 10)))
		cells = max(1, self._mainWidth())
		self._autoScrollTimer = queue_handler.callLater(int(cells * 1000 / rate), self._autoScrollTick)

	def _autoScrollTick(self) -> None:
		self._autoScrollTimer = None
		if not self._autoScroll:
			return
		if not self.scrollForward(auto=True):
			self._autoScroll = False
			from .. import speech

			speech.speakMessage(_("fin del desplazamiento automático"))
			return
		self._scheduleAutoScroll()

	# ================================================================ enrutamiento
	def cellToRaw(self, cellIndex: int) -> int | None:
		"""Carácter del búfer bajo la celda ``cellIndex`` de la línea (o ``None``)."""
		tr = self._translation
		if tr is None or cellIndex < 0 or cellIndex >= self._mainWidth():
			return None
		ws, we, _mark = self._lastWindow
		ci = self.windowStart + cellIndex
		if ci >= max(we, ws) or ci >= len(tr.cells):
			if ci >= len(tr.cells) and self._regionKind in ("text", "browse"):
				return len(self.text)
			return None
		return tr.brailleToRaw[ci]

	def _textInfoAtRaw(self, raw: int) -> Any:
		from .. import textinfo

		if self._regionInfo is None:
			return None
		offset = max(0, min(raw - self._lineStart, self._lineLen))
		info = self._regionInfo.copy()
		info.collapse()
		if offset:
			info.move(textinfo.UNIT_CHARACTER, offset)
		return info

	def routeTo(self, cellIndex: int) -> None:
		if self._messageActive:
			self._dismissMessage()
			return
		if self.speechMode:
			return
		raw = self.cellToRaw(cellIndex)
		if raw is None:
			return
		b = conf["braille"]
		from .. import presentation, textinfo

		if self._regionKind == "text" and self._regionInfo is not None:
			if raw < self._lineStart:
				self._activateSpanAt(raw)
				return
			info = self._textInfoAtRaw(raw)
			if info is None:
				return
			try:
				if self._source == "review":
					api.setReviewPosition(info)
					mode = b["reviewRoutingMovesSystemCaret"]
					if mode == "always" or (mode == "onlyWhenAutoTethered" and self._tether() == "auto"):
						info.updateCaret()
				else:
					info.updateCaret()
			except Exception:
				log.debug("No se pudo mover el cursor", exc_info=True)
			if b["speakOnRouting"]:
				presentation.speakTextInfo(info, textinfo.UNIT_CHARACTER, reason=presentation.Reason.REVIEW if self._source == "review" else presentation.Reason.CARET)
			self._showText(info, self._source, keepWindow=True)
		elif self._regionKind == "custom" and hasattr(self._regionObj, "routeTo"):
			try:
				self._regionObj.routeTo(raw)
			except Exception:
				log.debug("Error en el pulsador de la región propia", exc_info=True)
		elif self._regionKind == "browse":
			caret = api.getCaretObject()
			if caret is not None and getattr(caret, "buffer", None):
				offsets = self._browseOffsets
				if offsets:
					target = offsets[max(0, min(raw, len(offsets) - 1))]
				else:
					s, _e = caret.buffer.lineBounds(caret.caret)
					target = s + min(raw, max(0, self._lineLen - 1))
				if target == caret.caret:
					caret.activateAt(target)
				else:
					try:
						caret._moveCaret(target, speakUnit=textinfo.UNIT_CHARACTER if b["speakOnRouting"] else None)
						caret._updateBraille(*caret.buffer.lineBounds(target))
					except Exception:
						log.debug("No se pudo mover el cursor virtual", exc_info=True)
		elif self._regionKind == "object":
			self._activateSpanAt(raw)

	def _activateSpanAt(self, raw: int) -> None:
		target = None
		for start, end, obj in self._objectSpans:
			if start <= raw <= end:
				target = obj
		if target is None and self._regionObj is not None and self._regionKind == "object":
			target = self._regionObj
		if target is None:
			return
		try:
			target.doAction()
		except Exception:
			log.debug("No se pudo activar el objeto", exc_info=True)

	def textInfoForCell(self, cellIndex: int) -> Any:
		raw = self.cellToRaw(cellIndex)
		if raw is None or self._regionKind != "text" or raw < self._lineStart:
			return None
		return self._textInfoAtRaw(raw)

	def selectRange(self, startCell: int, endCell: int) -> str | None:
		"""Selecciona el texto entre dos celdas. Devuelve un error o ``None``."""
		if self._regionKind != "text" or self._source != "focus":
			return _("No se puede seleccionar desde la línea braille aquí")
		return self._selectBetween(self.textInfoForCell(min(startCell, endCell)), self.textInfoForCell(max(startCell, endCell)))

	def selectionAnchorAt(self, cellIndex: int) -> Any:
		"""Posición en el texto bajo la celda (para seleccionar en dos pulsaciones).

		Es una posición del texto, no de la ventana: sigue valiendo aunque la
		línea se desplace o cambie entre las dos pulsaciones."""
		if self._regionKind != "text" or self._source != "focus":
			return None
		return self.textInfoForCell(cellIndex)

	def selectFromAnchor(self, anchor: Any, cellIndex: int) -> str | None:
		"""Selecciona desde ``anchor`` (de :meth:`selectionAnchorAt`) hasta la celda."""
		if self._regionKind != "text" or self._source != "focus":
			return _("No se puede seleccionar desde la línea braille aquí")
		other = self.textInfoForCell(cellIndex)
		if anchor is None or other is None or getattr(anchor, "obj", None) is not getattr(other, "obj", None):
			return _("No se puede seleccionar desde la línea braille aquí")
		try:
			if anchor.compareEndPoints(other, "startToStart") > 0:
				anchor, other = other, anchor
		except Exception:
			return _("No se puede seleccionar desde la línea braille aquí")
		return self._selectBetween(anchor.copy(), other.copy())

	def _selectBetween(self, a: Any, e: Any) -> str | None:
		if a is None or e is None:
			return _("No se puede seleccionar desde la línea braille aquí")
		from .. import textinfo

		try:
			e.move(textinfo.UNIT_CHARACTER, 1, endPoint="end")
			a.setEndPoint(e, "endToEnd")
			a.updateSelection()
		except Exception:
			return _("Este control no permite seleccionar")
		self.scheduleFocusUpdate(80)
		return None

	def formattingAtCell(self, cellIndex: int) -> str:
		"""Descripción del formato del carácter bajo la celda."""
		info = self.textInfoForCell(cellIndex)
		if info is None:
			return ""
		try:
			from .. import formatting

			parts = formatting.fullDescription(info)
			return ", ".join(p for p in parts if p)
		except Exception:
			log.debug("No se pudo leer el formato", exc_info=True)
			return ""

	# ================================================================ seguimiento
	def cycleTether(self) -> str:
		order = [("auto", _("braille sigue automáticamente")), ("focus", _("braille sigue al foco")), ("review", _("braille sigue a la revisión"))]
		cur = conf["braille"]["tetherTo"]
		keys = [k for k, _l in order]
		nxt = order[(keys.index(cur) + 1) % len(order) if cur in keys else 0]
		conf["braille"]["tetherTo"] = nxt[0]
		if nxt[0] == "review":
			pos = api.getReviewPosition()
			if pos is not None:
				self.handleReviewMove(pos)
			else:
				self.handleNavigatorObject(api.getNavigatorObject())
		else:
			self.toFocus()
		return nxt[1]

	def toFocus(self) -> None:
		"""Muestra el foco en la línea (sin cambiar el seguimiento a la revisión)."""
		if self.speechMode:
			return
		focus = api.getFocusObject()
		if focus is None:
			return
		if self._messageActive:
			self._cancelMessageTimer()
			self._messageActive = False
			self._saved = None
		ti = getattr(focus, "treeInterceptor", None)
		if ti is not None and not getattr(ti, "passThrough", True) and getattr(ti, "buffer", None):
			try:
				ti._updateBraille(*ti.buffer.lineBounds(ti.caret))
				return
			except Exception:
				pass
		saved = conf["braille"]["tetherTo"]
		if saved == "review":
			# Se muestra el foco una vez, sin cambiar la opción.
			conf["braille"]["tetherTo"] = "focus"
			try:
				self.handleObject(focus, "query")
			finally:
				conf["braille"]["tetherTo"] = saved
		else:
			self.handleObject(focus, "query")

	def reloadViewer(self) -> None:
		"""Vuelve a abrir el visor que hace de línea (tras cambiar sus celdas)."""
		if getattr(self.display, "name", "") == "viewer":
			self.setDisplay("viewer", persist=False)

	def setInputCells(self, cells: list[int]) -> None:
		"""Celdas pendientes del teclado braille (se muestran en el cursor)."""
		self._inputCells = list(cells)
		self._refresh()

	def applyConfig(self) -> None:
		"""Tras cambiar opciones: vuelve a traducir y redibuja."""
		self._focusContext = None
		if self.speechMode and self._regionKind != "speech":
			from .. import speech

			last = speech.getLastSpokenText()
			if last:
				self.onSpeech(last)
		elif not self.speechMode and self._regionKind == "speech":
			self.toFocus()
		self.retranslate()
		self._updateBlink()
		self.updateSplit()
		self._scheduleAutoScroll()


class _BaseGetFormatHolder:
	value = None


def _BaseGetFormat():
	"""``TextInfo.getFormatInfo`` de la clase base (no da información)."""
	if _BaseGetFormatHolder.value is None:
		from .. import textinfo

		_BaseGetFormatHolder.value = textinfo.TextInfo.getFormatInfo
	return _BaseGetFormatHolder.value
