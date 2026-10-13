"""Búfer virtual: representación lineal (texto plano) de un documento web.

Se construye recorriendo el árbol UIA del documento con una única petición
de caché (``BuildUpdatedCache`` con ámbito de subárbol), lo que es rápido
incluso en páginas grandes. Cada elemento se convierte en un :class:`Node`
con su rango ``[start, end)`` dentro del texto del búfer.
"""

from __future__ import annotations

import bisect
from typing import Any, Callable, Iterator

import comtypes

from ..a11y import uia_client as uc
from ..config import conf
from ..i18n import _
from ..log import getLogger
from ..objects.roles import HEADING_ROLES, Role, State
from ..objects.uia import _ARIA_ROLES, _CONTROLTYPE_ROLES, _LANDMARK_ARIA, _LANDMARK_TYPES, isMsaaProxyProvider, looksLikeTextLeaf, parseAriaProperties
from . import aria as ariaSem

log = getLogger("vbuf")

#: Puntuación que cierra una frase o un inciso: se queda pegada al enlace que
#: la precede aunque el texto siguiente vaya en otra línea (#11073).
_CLOSING_PUNCTUATION = ",.;:)]}!?»…\"'”’"

#: Roles cuyo contenido se trata como un único bloque atómico (no se recorren hijos).
ATOMIC_ROLES = {
	Role.BUTTON,
	Role.TOGGLEBUTTON,
	Role.CHECKBOX,
	Role.RADIOBUTTON,
	Role.EDITABLETEXT,
	Role.PASSWORDEDIT,
	Role.COMBOBOX,
	Role.SLIDER,
	Role.SPINBUTTON,
	Role.PROGRESSBAR,
	Role.SCROLLBAR,
	Role.SPLITBUTTON,
	Role.MENUITEM,
	Role.SWITCH,
	Role.GRAPHIC,
	Role.SEPARATOR,
	Role.TAB,
}

#: Roles que fluyen en línea con el texto.
INLINE_ROLES = {
	Role.STATICTEXT,
	Role.LINK,
	Role.GRAPHIC,
	Role.BUTTON,
	Role.TOGGLEBUTTON,
	Role.CHECKBOX,
	Role.RADIOBUTTON,
	Role.EDITABLETEXT,
	Role.PASSWORDEDIT,
	Role.COMBOBOX,
	Role.SLIDER,
	Role.SPINBUTTON,
	Role.SPLITBUTTON,
	Role.SWITCH,
	Role.MARKED_CONTENT,
	# Encabezados de fila y columna: en la misma línea que las demás celdas.
	Role.TABLECOLUMNHEADER,
	Role.TABLEROWHEADER,
	Role.TABLECELL,
	Role.DATAITEM,
	Role.TAB,
	Role.MENUITEM,
	Role.MATH,
}

#: Roles de formulario (tecla F).
FORM_FIELD_ROLES = {
	Role.EDITABLETEXT,
	Role.PASSWORDEDIT,
	Role.COMBOBOX,
	Role.CHECKBOX,
	Role.RADIOBUTTON,
	Role.SLIDER,
	Role.SPINBUTTON,
	Role.BUTTON,
	Role.TOGGLEBUTTON,
	Role.SPLITBUTTON,
	Role.SWITCH,
	Role.LIST,
	Role.TREEVIEW,
	Role.MENUBUTTON,
	Role.DROPDOWNBUTTON,
}

#: Roles con texto propio que se anuncia con prefijo de rol al entrar.
PREFIX_FIELD_ROLES = {
	Role.LINK,
	Role.HEADING,
	Role.HEADING1,
	Role.HEADING2,
	Role.HEADING3,
	Role.HEADING4,
	Role.HEADING5,
	Role.HEADING6,
	Role.LIST,
	Role.TABLE,
	Role.DATAGRID,
	Role.LANDMARK,
	Role.BLOCKQUOTE,
	Role.ARTICLE,
	Role.FIGURE,
	Role.DIALOG,
	Role.GRAPHIC,
	Role.REGION,
	Role.TREEVIEW,
	Role.MATH,
}

#: Contenedores cuya salida se anuncia («fuera de lista»).
CONTAINER_ROLES = {
	Role.LIST,
	Role.TABLE,
	Role.DATAGRID,
	Role.LANDMARK,
	Role.BLOCKQUOTE,
	Role.ARTICLE,
	Role.FIGURE,
	Role.DIALOG,
	Role.REGION,
	Role.TREEVIEW,
	Role.FRAME,
}

CONTAINER_EXIT_LABELS = {
	Role.LIST: _("fuera de lista"),
	Role.TABLE: _("fuera de tabla"),
	Role.DATAGRID: _("fuera de cuadrícula"),
	Role.LANDMARK: _("fuera de {landmark}"),
	Role.BLOCKQUOTE: _("fuera de cita"),
	Role.ARTICLE: _("fuera de artículo"),
	Role.FIGURE: _("fuera de figura"),
	Role.DIALOG: _("fuera de diálogo"),
	Role.REGION: _("fuera de región"),
	Role.TREEVIEW: _("fuera de árbol"),
	Role.FRAME: _("fuera de marco"),
	Role.GROUPING: _("fuera de agrupación"),
}


def isLayoutTable(node: "Node") -> bool:
	return node.role in (Role.TABLE, Role.DATAGRID) and node.layoutTable and not conf["browseMode"]["includeLayoutTables"]


def isContainer(node: "Node") -> bool:
	"""Contenedores cuya entrada y salida se anuncian."""
	if isLayoutTable(node):
		return False
	if node.role == Role.GROUPING:
		return bool(node.name) and conf["documentFormatting"]["reportGroupings"]
	return node.role in CONTAINER_ROLES


class Node:
	__slots__ = (
		"element",
		"role",
		"name",
		"value",
		"states",
		"level",
		"landmark",
		"rid",
		"start",
		"end",
		"parent",
		"children",
		"isFocusable",
		"rowCol",
		"tableSize",
		"description",
		"childCount",
		"index",
		"ariaRole",
		"location",
		"automationId",
		"className",
		"culture",
		"fmt",
		"clickable",
		"layoutTable",
		"aria",
		"lct",
		"url",
		"orientation",
		"live",
		"rowSpan",
		"colSpan",
		"itemStatus",
		"relations",
		"relationElements",
		"semantic",
		"unlabeled",
		"spaceAround",
	)

	def __init__(self) -> None:
		self.element = None
		self.role = Role.UNKNOWN
		self.name = ""
		self.value = ""
		self.states: set[State] = set()
		self.level = 0
		self.landmark = ""
		self.rid: tuple = ()
		self.start = 0
		self.end = 0
		self.parent: Node | None = None
		self.children: list[Node] = []
		self.isFocusable = False
		self.rowCol: tuple[int, int] | None = None
		self.tableSize: tuple[int, int] | None = None
		self.description = ""
		self.childCount = 0
		self.index = 0
		self.ariaRole = ""
		self.location: tuple[int, int, int, int] | None = None
		self.automationId = ""
		self.className = ""
		#: Idioma del elemento (``es_ES``) si lo indica la página.
		self.culture: str | None = None
		#: Marca semántica en línea: emphasis, strong, mark, insertion, deletion, comment.
		self.fmt = ""
		#: Elemento genérico que responde a clics (``pulsable``).
		self.clickable = False
		#: Tabla usada solo para maquetar.
		self.layoutTable = False
		#: Propiedades ARIA (``aria-current``, ``aria-haspopup``, ``aria-sort``...).
		self.aria: dict[str, str] = {}
		#: Tipo de control localizado (en minúsculas).
		self.lct = ""
		#: Destino de los enlaces.
		self.url = ""
		#: Orientación UIA: 0 sin indicar, 1 horizontal, 2 vertical.
		self.orientation = 0
		#: Región viva: 0 desactivada, 1 cortés, 2 asertiva.
		self.live = 0
		#: Celdas combinadas.
		self.rowSpan = 1
		self.colSpan = 1
		#: ItemStatus (los navegadores ponen aquí ``aria-sort``).
		self.itemStatus = ""
		#: Relaciones con otros elementos (RuntimeId de los destinos):
		#: ``details``, ``flowTo``, ``controls``, ``describedBy``.
		self.relations: dict[str, list[tuple]] = {}
		#: Elementos UIA de esas relaciones (por si el destino no está en el búfer).
		self.relationElements: dict[str, list] = {}
		#: Rol semántico expuesto solo como tipo localizado (DPUB, término...).
		self.semantic = ""
		#: Imagen sin texto alternativo.
		self.unlabeled = False
		#: El nombre original empezaba o terminaba con espacio (antes de quitarlo).
		self.spaceAround = (False, False)

	def ancestors(self) -> Iterator["Node"]:
		n = self.parent
		while n is not None:
			yield n
			n = n.parent

	def isHeading(self) -> bool:
		return self.role in HEADING_ROLES

	def headingLevel(self) -> int:
		if self.role in HEADING_ROLES and self.role != Role.HEADING:
			return int(self.role) - int(Role.HEADING1) + 1
		return self.level or 0

	def __repr__(self) -> str:
		return f"<Node {self.role.name} {self.name[:30]!r} [{self.start},{self.end})>"


def _cached(el, propId: int, default: Any = None) -> Any:
	try:
		val = el.GetCachedPropertyValueEx(propId, True)
	except (comtypes.COMError, ValueError):
		return default
	if val is None or uc.isNotSupported(val):
		return default
	return val


def _cachedRelation(el, propId: int) -> list[tuple]:
	"""(RuntimeId, elemento) de una propiedad de tipo matriz (cacheada).

	Se lee con el accesor tipado cacheado (``CachedControllerFor``...), nunca
	como VARIANT: comtypes libera mal las matrices de IUnknown (montón dañado).
	"""
	out = []
	for e in uc.elementArray(el, propId, cached=True)[:50]:
		rid = uc.runtimeIdOf(e)
		if rid:
			out.append((rid, e))
	return out


class VirtualBuffer:
	def __init__(self, rootElement) -> None:
		self.rootElement = rootElement
		self.text = ""
		self.nodes: list[Node] = []
		self.chunks: list[tuple[int, int, Node]] = []
		self._chunkStarts: list[int] = []
		self.root: Node | None = None
		self.byRid: dict[tuple, Node] = {}
		self.tables: dict[int, dict[tuple[int, int], Node]] = {}
		self._parts: list[str] = []
		self._pos = 0
		self._atLineStart = True
		self._lastRect: tuple[int, int, int, int] | None = None
		self._screenLayout = True
		#: Reglas de la web flexible (elementos ocultos por el usuario) o ``None``.
		self.hiddenRules = None
		#: Orden de lectura visual (por columnas) en lugar del orden del documento.
		self.visualOrder = False
		#: Orden de lectura propio, a mano o con IA (``reading_order.ReadingOrder``, foros 3.10).
		self.readingOrder = None
		#: Etiquetas y textos alternativos generados con IA (``ai.labelstore.Lookup``, foros 3.10 y 6.3).
		self.aiLabels = None
		#: Etiquetas personalizadas del usuario: función ``nodo -> etiqueta`` (``labels.bufferLookup``) o ``None``.
		self.customLabels = None
		#: Posiciones de los saltos de línea añadidos al cortar líneas largas.
		self.softBreaks: set[int] = set()
		#: Padre del nodo raíz (al reconstruir solo un subárbol).
		self.rootParent: Node | None = None
		#: Etiquetas de las líneas de entrada y salida de cada contenedor (#3997):
		#: función ``nodo -> (entrada, salida)``; ``None`` si la opción está desactivada.
		self.containerLabels: Callable[[Node], tuple[str, str]] | None = None
		#: Líneas añadidas por esa opción, ordenadas: (inicio, fin, contenedor, "start" o "end").
		#: No pertenecen a ningún trozo de texto del documento (no se copian).
		self.boundaryLines: list[tuple[int, int, Node, str]] = []
		self._boundaryStarts: list[int] = []
		#: Salto de línea pendiente tras un enlace o control sin disposición en pantalla (#11073).
		self._pendingBreak = False
		self._breakAfterLinks = True
		#: Opciones con las que se construyó (para reconstruir si cambian).
		self.layoutSignature: tuple = ()
		#: Versión del texto: sube con cada empalme (actualización parcial).
		self.version = 0
		#: Empalmes hechos: (versión nueva, inicio, fin anterior, diferencia).
		#: Permite trasladar desplazamientos antiguos (lectura continua, M1).
		self.edits: list[tuple[int, int, int, int]] = []
		#: Rectángulo propio del último trozo de texto emitido (palabras partidas, A9).
		self._lastOwnRect: tuple[int, int, int, int] | None = None
		self._lastSpaceAfter = False

	# ------------------------------------------------------------ construcción
	def build(self) -> None:
		try:
			cached = self.rootElement.BuildUpdatedCache(uc.treeCacheRequest)
		except comtypes.COMError:
			log.debug("No se pudo construir la caché del documento", exc_info=True)
			raise
		self._parts = []
		self._pos = 0
		self._atLineStart = True
		self._lastRect = None
		self._lastOwnRect = None
		self._lastSpaceAfter = False
		self._screenLayout = conf["browseMode"]["useScreenLayout"]
		self._breakAfterLinks = conf["browseMode"]["breakAfterLinks"]
		self._pendingBreak = False
		self.nodes = []
		self.chunks = []
		self.byRid = {}
		self.tables = {}
		try:
			from ..mathpres import browse_support

			browse_support.prefetch(self, cached)
		except Exception:
			log.debug("No se pudieron preparar las fórmulas", exc_info=True)
		self.softBreaks = set()
		self.root = self._walk(cached, self.rootParent, 0)
		self._newLine()
		self.text = "".join(self._parts)
		self._insertContainerLines()
		self._wrapLongLines()
		self._chunkStarts = [c[0] for c in self.chunks]
		self.nodes.sort(key=lambda n: (n.start, -n.end))
		for i, n in enumerate(self.nodes):
			n.index = i
		self._refineClickable()

	def _refineClickable(self) -> None:
		"""Solo es «pulsable» un elemento pequeño sin controles propios dentro.

		Las páginas modernas registran clics en contenedores enteros; anunciarlos
		todos sería ruido.
		"""
		for i, n in enumerate(self.nodes):
			if not n.clickable:
				continue
			if n.end - n.start > 150 or n.end <= n.start:
				n.clickable = False
				n.states.discard(State.CLICKABLE)
				continue
			j = i + 1
			while j < len(self.nodes) and self.nodes[j].start < n.end:
				d = self.nodes[j]
				if d.isFocusable or d.role in ATOMIC_ROLES or d.role == Role.LINK or d.clickable:
					n.clickable = False
					n.states.discard(State.CLICKABLE)
					break
				j += 1

	def _append(self, text: str) -> None:
		if not text:
			return
		self._parts.append(text)
		self._pos += len(text)
		self._atLineStart = text.endswith("\n")

	def _newLine(self) -> None:
		self._lastRect = None
		self._lastOwnRect = None
		self._pendingBreak = False
		if not self._atLineStart:
			self._append("\n")

	def _emit(self, text: str, node: Node) -> None:
		# Los guiones blandos (U+00AD) no se leen ni se muestran (#9343, foros 1.20).
		text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xad", "")
		if not text:
			return
		if self._pendingBreak:
			# #11073: lo que sigue a un enlace va en otra línea, salvo la
			# puntuación que lo cierra («enlace,» «enlace.»), que se queda con él.
			self._pendingBreak = False
			stripped = text.lstrip(" ")
			n = 0
			while n < len(stripped) and stripped[n] in _CLOSING_PUNCTUATION:
				n += 1
			if n and n < len(stripped) and not stripped[n].isspace():
				# «.com», «)a»: no es puntuación de cierre sino parte de una palabra.
				n = 0
			if n:
				start = self._pos
				self._append(stripped[:n])
				self.chunks.append((start, self._pos, node))
				text = stripped[n:].lstrip(" ")
				if not text:
					return
			self._newLine()
		rect = node.location
		anc = node.parent
		while rect is None and anc is not None:
			rect = anc.location
			anc = anc.parent
		if self._screenLayout and rect is not None and self._lastRect is not None and not self._atLineStart:
			# Distribución de pantalla: si el elemento empieza en una fila
			# inferior a la del anterior, va en una línea nueva.
			top = rect[1]
			ltop, lh = self._lastRect[1], self._lastRect[3]
			if top >= ltop + lh - 2:
				self._append("\n")
		if rect is not None:
			self._lastRect = rect
		if not self._atLineStart and self._parts:
			last = self._parts[-1][-1:]
			if last not in (" ", "\n", "\t") and not text[:1].isspace() and text[:1] not in ",.;:)]!?»" and not self._continuesWord(node):
				self._append(" ")
		start = self._pos
		self._append(text)
		self.chunks.append((start, self._pos, node))
		own = node.location if node.role == Role.STATICTEXT else None
		self._lastOwnRect = own if own and own[2] > 0 and own[3] > 0 else None
		self._lastSpaceAfter = bool(node.spaceAround[1])

	def _continuesWord(self, node: Node) -> bool:
		"""¿El texto sigue pegado al anterior en pantalla («<mark>Mad</mark>rid»)?

		Los nombres llegan sin los espacios de los extremos, así que entre dos
		trozos de texto se pone un espacio, salvo que estén en la misma fila y el
		segundo empiece justo donde acaba el primero (rev. 10.11, A9).
		"""
		prev = self._lastOwnRect
		if prev is None or node.role != Role.STATICTEXT or self._lastSpaceAfter or node.spaceAround[0]:
			return False
		own = node.location
		if not own or own[2] <= 0 or own[3] <= 0:
			return False
		px, py, pw, ph = prev
		x, y, w, h = own
		if abs(y - py) > 2 or abs((y + h) - (py + ph)) > 4:
			return False
		gap = x - (px + pw)
		return -1 <= gap <= 1

	def _isGeckoMsaaProxy(self) -> bool:
		"""El documento es de Gecko sin UIA propio (lo da el puente MSAA→UIA del sistema)."""
		val = self.__dict__.get("_geckoMsaaProxy")
		if val is None:
			try:
				el = self.rootElement
				val = str(el.CurrentFrameworkId or "") == "Gecko" and isMsaaProxyProvider(el.GetCurrentPropertyValue(uc.P_PROVIDERDESCRIPTION))
			except (comtypes.COMError, AttributeError, ValueError):
				val = False
			self._geckoMsaaProxy = val
		return val

	def _makeNode(self, el, parent: Node | None) -> Node | None:
		aria = parseAriaProperties(_cached(el, uc.P_ARIAPROPERTIES, "") or "")
		if aria.get("hidden") == "true":
			return None
		n = Node()
		n.element = el
		n.parent = parent
		ct = _cached(el, uc.P_CONTROLTYPE, 0) or 0
		role = _CONTROLTYPE_ROLES.get(ct, Role.UNKNOWN)
		ariaRole = (_cached(el, uc.P_ARIAROLE, "") or "").lower()
		n.ariaRole = ariaRole
		rawName = _cached(el, uc.P_NAME, "") or ""
		if not isinstance(rawName, str):
			rawName = str(rawName)
		n.name = rawName.strip()
		if n.name:
			n.spaceAround = (rawName[:1].isspace(), rawName[-1:].isspace())
		n.automationId = _cached(el, uc.P_AUTOMATIONID, "") or ""
		n.className = _cached(el, uc.P_CLASSNAME, "") or ""
		n.aria = aria
		n.lct = str(_cached(el, uc.P_LOCALIZEDCONTROLTYPE, "") or "").strip().lower()
		if self.hiddenRules is not None and self.hiddenRules.matches(n, ct):
			# Elemento ocultado por el usuario (web flexible).
			return None
		if ct == uc.CT_EDIT and _cached(el, uc.P_ISPASSWORD, False):
			role = Role.PASSWORDEDIT
		elif ct == uc.CT_EDIT and self._isGeckoMsaaProxy() and looksLikeTextLeaf(lambda p, d=None: _cached(el, p, d)):
			# Trozo de texto de Gecko a través del puente MSAA (cuerpo de los correos
			# de Thunderbird 102): es texto normal, no un campo «edición».
			role = Role.STATICTEXT
		heading =_cached(el, uc.P_HEADINGLEVEL, 0) or 0
		if heading and heading > uc.HEADINGLEVEL_NONE:
			lvl = heading - uc.HEADINGLEVEL_NONE
			role = Role(Role.HEADING1 + lvl - 1) if 1 <= lvl <= 6 else Role.HEADING
			n.level = lvl
		elif ariaRole == "heading":
			role = Role.HEADING
			try:
				n.level = int(aria.get("level", "0"))
			except ValueError:
				n.level = 0
			if 1 <= n.level <= 6:
				role = Role(Role.HEADING1 + n.level - 1)
		elif ariaRole in _ARIA_ROLES and role not in (Role.EDITABLETEXT, Role.BUTTON, Role.LINK, Role.CHECKBOX, Role.LIST, Role.LISTITEM):
			role = _ARIA_ROLES[ariaRole]
		lm = _cached(el, uc.P_LANDMARKTYPE, 0) or 0
		if lm:
			n.landmark = _LANDMARK_TYPES.get(lm) or (_cached(el, uc.P_LOCALIZEDLANDMARKTYPE, "") or "")
			role = Role.LANDMARK
		elif ariaRole in _LANDMARK_ARIA and role in (Role.GROUPING, Role.PANE, Role.CUSTOM, Role.UNKNOWN, Role.SECTION):
			if ariaRole != "region" or n.name:
				n.landmark = _cached(el, uc.P_LOCALIZEDLANDMARKTYPE, "") or _LANDMARK_ARIA[ariaRole]
				role = Role.LANDMARK
		if role == Role.BUTTON and _cached(el, uc.P_ISTOGGLEPATTERNAVAILABLE, False):
			role = Role.TOGGLEBUTTON
		if ct == uc.CT_DOCUMENT and parent is not None:
			# Documento dentro del documento: un marco (iframe).
			role = Role.FRAME
		if ariaRole in ("emphasis", "strong", "mark", "insertion", "deletion", "comment"):
			n.fmt = ariaRole
		elif ariaRole == "ins":
			n.fmt = "insertion"
		elif ariaRole == "del":
			n.fmt = "deletion"
		culture = _cached(el, uc.P_CULTURE, 0) or 0
		if culture:
			from ..i18n import lcidToLanguage

			n.culture = lcidToLanguage(int(culture))
		if _cached(el, uc.P_ISINVOKEPATTERNAVAILABLE, False) and role in (Role.GROUPING, Role.STATICTEXT, Role.SECTION, Role.UNKNOWN, Role.PARAGRAPH, Role.CUSTOM, Role.PANE, Role.GRAPHIC, Role.LISTITEM, Role.TABLECELL):
			n.clickable = True
		if _cached(el, uc.P_ISDIALOG, False):
			role = Role.DIALOG
		if role == Role.DATAITEM and ariaRole == "row":
			role = Role.TABLEROW
		if role == Role.DATAITEM and ariaRole in ("gridcell", "cell"):
			role = Role.TABLECELL
		# Roles que el navegador solo expone con el tipo localizado.
		if role in (Role.GROUPING, Role.SECTION, Role.CUSTOM, Role.UNKNOWN) and n.lct in ariaSem.FIGURE_LCT:
			role = Role.FIGURE
		if not n.fmt:
			if n.lct in ariaSem.MARK_LCT:
				n.fmt = "mark"
			elif n.lct in ariaSem.COMMENT_LCT:
				n.fmt = "comment"
			elif n.lct in ariaSem.INSERTION_LCT:
				n.fmt = "insertion"
			elif n.lct in ariaSem.DELETION_LCT:
				n.fmt = "deletion"
			elif n.lct in ariaSem.SUGGESTION_LCT or ariaRole == "suggestion":
				n.fmt = "suggestion"
		n.semantic = ariaSem.semanticLabel(role, n.lct)
		if role == Role.GRAPHIC and (ariaSem.isUnlabeledGraphicLct(n.lct) or not n.name):
			# Edge pone como nombre una invitación a describir la imagen.
			n.unlabeled = True
			n.name = ""
		n.role = role
		states: set[State] = set()
		if not _cached(el, uc.P_ISENABLED, True):
			states.add(State.UNAVAILABLE)
		if _cached(el, uc.P_ISKEYBOARDFOCUSABLE, False):
			states.add(State.FOCUSABLE)
			n.isFocusable = True
		if _cached(el, uc.P_ISTOGGLEPATTERNAVAILABLE, False):
			t = _cached(el, uc.P_TOGGLESTATE, 0)
			if role == Role.TOGGLEBUTTON:
				if t == 1:
					states.add(State.PRESSED)
			elif role == Role.SWITCH:
				if t == 1:
					states.add(State.ON)
			else:
				states.add(State.CHECKABLE)
				if t == 1:
					states.add(State.CHECKED)
				elif t == 2:
					states.add(State.HALFCHECKED)
		ec = _cached(el, uc.P_EXPANDCOLLAPSESTATE, None)
		if ec in (1, 2):
			states.add(State.EXPANDED)
		elif ec == 0:
			states.add(State.COLLAPSED)
		if _cached(el, uc.P_SELECTIONITEMISSELECTED, False):
			states.add(State.SELECTED)
		if _cached(el, uc.P_ISREQUIREDFORFORM, False):
			states.add(State.REQUIRED)
		legacy = int(_cached(el, uc.P_LEGACYSTATE, 0) or 0)
		if legacy & 0x800000:
			states.add(State.VISITED)
		if aria.get("haspopup") not in (None, "", "false"):
			states.add(State.HASPOPUP)
		if aria.get("invalid") not in (None, "", "false"):
			states.add(State.INVALID_ENTRY)
		if aria.get("readonly") == "true":
			states.add(State.READONLY)
		if n.clickable:
			states.add(State.CLICKABLE)
		n.states = states
		if role in (Role.EDITABLETEXT, Role.PASSWORDEDIT, Role.COMBOBOX):
			if _cached(el, uc.P_ISVALUEPATTERNAVAILABLE, False):
				v = _cached(el, uc.P_VALUEVALUE, "") or ""
				n.value = "" if role == Role.PASSWORDEDIT else str(v)
		elif role in (Role.SLIDER, Role.PROGRESSBAR, Role.SPINBUTTON):
			rv = _cached(el, uc.P_RANGEVALUEVALUE, None)
			if rv is not None:
				try:
					f = float(rv)
					n.value = str(int(f)) if f.is_integer() else f"{f:g}"
				except (TypeError, ValueError):
					n.value = str(rv)
		row = _cached(el, uc.P_GRIDITEMROW, None)
		col = _cached(el, uc.P_GRIDITEMCOLUMN, None)
		if row is not None and col is not None and role in (Role.TABLECELL, Role.DATAITEM, Role.TABLECOLUMNHEADER, Role.TABLEROWHEADER, Role.HEADERITEM):
			n.rowCol = (int(row) + 1, int(col) + 1)
		rc = _cached(el, uc.P_GRIDROWCOUNT, None)
		cc = _cached(el, uc.P_GRIDCOLUMNCOUNT, None)
		if rc is not None and cc is not None and role in (Role.TABLE, Role.DATAGRID):
			n.tableSize = (int(rc), int(cc))
		n.description = _cached(el, uc.P_FULLDESCRIPTION, "") or ""
		if role == Role.LINK:
			n.url = str(_cached(el, uc.P_VALUEVALUE, "") or "")
		elif role in (Role.SLIDER, Role.PROGRESSBAR, Role.SPINBUTTON, Role.SCROLLBAR):
			mn = _cached(el, uc.P_RANGEVALUEMINIMUM, None)
			mx = _cached(el, uc.P_RANGEVALUEMAXIMUM, None)
			if mn is not None and mx is not None:
				n.aria.setdefault("valuemin", str(mn))
				n.aria.setdefault("valuemax", str(mx))
		n.orientation = int(_cached(el, uc.P_ORIENTATION, 0) or 0)
		n.live = int(_cached(el, uc.P_LIVESETTING, 0) or 0) or ariaSem.liveFromAria(aria)
		n.itemStatus = str(_cached(el, uc.P_ITEMSTATUS, "") or "")
		if n.rowCol:
			n.rowSpan = max(1, int(_cached(el, uc.P_GRIDITEMROWSPAN, 1) or 1))
			n.colSpan = max(1, int(_cached(el, uc.P_GRIDITEMCOLUMNSPAN, 1) or 1))
		for key, prop in (("details", uc.P_ANNOTATIONOBJECTS), ("flowTo", uc.P_FLOWSTO), ("controls", uc.P_CONTROLLERFOR), ("describedBy", uc.P_DESCRIBEDBY)):
			pairs = _cachedRelation(el, prop)
			if pairs:
				n.relations[key] = [rid for rid, _e in pairs]
				n.relationElements[key] = [e for _r, e in pairs]
		rid = _cached(el, uc.P_RUNTIMEID, None)
		n.rid = tuple(rid) if rid else ()
		rect = _cached(el, uc.P_BOUNDINGRECT, None)
		if rect and len(rect) >= 4:
			n.location = tuple(int(v) for v in rect[:4])  # type: ignore[assignment]
		if self.customLabels is not None:
			# Etiqueta personalizada del usuario: sustituye al nombre en el texto
			# del documento y en la lista de elementos (como en la voz y el braille).
			try:
				label = self.customLabels(n)
			except Exception:
				label = None
			if label:
				n.name = label
				n.unlabeled = False
		if self.aiLabels is not None and not n.name:
			# Texto generado con IA para un elemento sin nombre (foros 3.10 y 6.3).
			label = self.aiLabels.get(n)
			if label:
				n.name = label
				n.unlabeled = False
		return n

	def _walk(self, el, parent: Node | None, depth: int) -> Node | None:
		if depth > 200:
			return None
		node = self._makeNode(el, parent)
		if node is None:
			return None
		# Posición del nodo en la lista (para las celdas de las tablas, sin
		# buscarlo con ``list.index``, que en páginas con muchas tablas es cuadrático).
		nodeIndex = len(self.nodes)
		self.nodes.append(node)
		if node.rid:
			self.byRid[node.rid] = node
		role = node.role
		isInline = role in INLINE_ROLES
		if not self._screenLayout and role in ATOMIC_ROLES | {Role.LINK}:
			isInline = False
		if not isInline:
			self._newLine()
		node.start = self._pos
		try:
			children = el.GetCachedChildren()
			childCount = children.Length if children else 0
		except (comtypes.COMError, ValueError):
			children = None
			childCount = 0
		node.childCount = childCount
		if role == Role.GRAPHIC and node.name and "\\" in node.name:
			from ..mathpres import browse_support

			if browse_support.isLatexAlt(node.name):
				# Imagen con la fórmula en LaTeX como texto alternativo (Wikipedia).
				role = node.role = Role.MATH
		if role == Role.MATH:
			# Fórmula: se lee con el motor de matemáticas (no se recorren sus hijos).
			from ..mathpres import browse_support

			self._emit(browse_support.mathText(self, node, el) or " ", node)
			if self.chunks and self.chunks[-1][2] is node:
				# La fórmula empieza donde empieza su texto (no en el separador).
				node.start = self.chunks[-1][0]
		elif role in ATOMIC_ROLES:
			self._emit(self._atomicText(node), node)
		elif role == Role.TABLEROW:
			# Las filas de tabla ocupan una línea; sus celdas van en línea.
			for i in range(childCount):
				child = self._walk(children.GetElement(i), node, depth + 1)
				if child is not None:
					node.children.append(child)
		else:
			before = self._pos
			kids = [children.GetElement(i) for i in range(childCount)]
			custom = self.readingOrder.reorder(el, kids, parent is None) if self.readingOrder is not None and len(kids) > 1 else None
			if custom is not None:
				# Orden de lectura fijado a mano o con IA (foros 3.10).
				kids = custom
			elif self.visualOrder and len(kids) > 1 and role not in INLINE_ROLES and role not in (Role.PARAGRAPH, Role.LINK, Role.TABLE, Role.DATAGRID, Role.LIST) and role not in HEADING_ROLES:
				kids = visualOrder(kids)
			# Fórmulas que UIA no publica en la vista de control (role="math" con solo etiqueta).
			extras = getattr(self, "_extraMath", None)
			for kid in kids:
				if extras:
					from ..mathpres import browse_support

					browse_support.emitExtras(self, node, kid, "before")
				child = self._walk(kid, node, depth + 1)
				if child is not None:
					node.children.append(child)
				if extras:
					browse_support.emitExtras(self, node, kid, "after")
			if self._pos == before:
				# Sin hijos con texto: se usa el nombre (p. ej. texto estático).
				text = node.name
				if role == Role.LINK and not text:
					text = _("enlace")
				if text and role not in (Role.LIST, Role.TABLE, Role.DATAGRID, Role.LANDMARK, Role.DOCUMENT):
					self._emit(text, node)
				elif role in (Role.TABLECELL, Role.DATAITEM) and node.rowCol:
					# Celda vacía: se reserva un espacio para poder navegar a ella.
					self._emit(" ", node)
		node.end = self._pos
		if role in (Role.TABLE, Role.DATAGRID):
			cells: dict[tuple[int, int], Node] = {}
			for n in self.nodes[nodeIndex + 1 :]:
				if n.rowCol and n.start >= node.start:
					tableOf = next((a for a in n.ancestors() if a.role in (Role.TABLE, Role.DATAGRID)), None)
					if tableOf is node:
						# Una celda combinada ocupa todas sus coordenadas.
						r0, c0 = n.rowCol
						for dr in range(min(n.rowSpan, 200)):
							for dc in range(min(n.colSpan, 200)):
								cells.setdefault((r0 + dr, c0 + dc), n)
			if cells:
				self.tables[id(node)] = cells
				if not node.tableSize:
					rows = max(r for r, _c in cells)
					cols = max(c for _r, c in cells)
					node.tableSize = (rows, cols)
			hasHeaders = any(c.role in (Role.TABLECOLUMNHEADER, Role.TABLEROWHEADER, Role.HEADERITEM) for c in cells.values())
			rows, cols = node.tableSize or (0, 0)
			if node.ariaRole in ("presentation", "none") or (not hasHeaders and (rows <= 1 or cols <= 1)):
				node.layoutTable = True
		if not isInline and not self._screenLayout and role in ATOMIC_ROLES | {Role.LINK}:
			# Sin disposición en pantalla: el enlace o el control empieza línea y
			# lo que le sigue empieza otra (#11073), o sigue en la del enlace si
			# el usuario lo prefiere («breakAfterLinks» desactivada).
			self._pendingBreak = role != Role.LINK or self._breakAfterLinks
		elif not isInline:
			self._newLine()
		elif role in (Role.TABLECELL, Role.DATAITEM, Role.TABLECOLUMNHEADER, Role.TABLEROWHEADER):
			self._append(" ")
		return node

	def _atomicText(self, node: Node) -> str:
		role = node.role
		if role == Role.SEPARATOR:
			# Los saltos de página de las publicaciones digitales tienen nombre («página 12»).
			return node.name or _("separador")
		if role == Role.GRAPHIC:
			if not node.name:
				# Imágenes sin texto alternativo: «gráfico» en enlaces y controles; las
				# demás solo si el usuario lo pide; con su nombre de archivo (#7412).
				from . import html_details

				return html_details.graphicText(self, node)
			return node.name
		parts = [node.name] if node.name else []
		if node.value and node.value != node.name:
			parts.append(node.value)
		text = " ".join(parts)
		if not text:
			text = " "
		return text

	def _wrapLongLines(self) -> None:
		"""Corta las líneas largas en espacios, sin partir controles ni enlaces."""
		maxLen = conf["browseMode"]["maxLineLength"]
		if maxLen <= 0:
			return
		chars = list(self.text)
		protected = bytearray(len(chars))
		for s, e, node in self.chunks:
			if node.role in ATOMIC_ROLES or node.role == Role.LINK or any(a.role == Role.LINK for a in node.ancestors()):
				if e - s < maxLen:
					for i in range(s, min(e, len(chars))):
						protected[i] = 1
		lineStart = 0
		lastSpace = -1
		for i, ch in enumerate(chars):
			if ch == "\n":
				lineStart = i + 1
				lastSpace = -1
				continue
			if ch == " " and not protected[i]:
				lastSpace = i
			if i - lineStart >= maxLen and lastSpace > lineStart:
				chars[lastSpace] = "\n"
				self.softBreaks.add(lastSpace)
				lineStart = lastSpace + 1
				lastSpace = -1
		self.text = "".join(chars)

	def _insertContainerLines(self) -> None:
		"""Pone en líneas propias la entrada y la salida de los contenedores (#3997).

		Se hace después del recorrido porque la etiqueta de entrada depende de
		los hijos («lista con 3 elementos»). Las líneas quedan dentro del
		rango del contenedor (la de entrada en su principio y la de salida en
		su final) y no pertenecen a ningún trozo de texto, así que no tienen
		elemento propio: el texto del documento y su correspondencia con los
		nodos se desplazan sin cambiar.
		"""
		self.boundaryLines = []
		self._boundaryStarts = []
		labeler = self.containerLabels
		text = self.text
		if labeler is None or not text:
			return
		#: (posición, orden, profundidad, etiqueta, contenedor, tipo)
		ins: list[tuple[int, int, int, str, Node, str]] = []
		for n in self.nodes:
			if n.end <= n.start or not isContainer(n):
				continue
			try:
				entry, exitLabel = labeler(n)
			except Exception:
				log.debug("Sin etiquetas para %r", n, exc_info=True)
				continue
			depth = sum(1 for _a in n.ancestors())
			entry = " ".join((entry or "").split())
			exitLabel = " ".join((exitLabel or "").split())
			if entry and (n.start == 0 or text[n.start - 1] == "\n"):
				ins.append((n.start, 1, depth, entry, n, "start"))
			if exitLabel:
				q = self.segmentEnd(n)
				if text[q - 1 : q] == "\n":
					ins.append((q, 0, -depth, exitLabel, n, "end"))
		if not ins:
			return
		# En una misma posición: primero las salidas (de dentro afuera) y luego
		# las entradas (de fuera adentro).
		ins.sort(key=lambda t: (t[0], t[1], t[2]))
		positions = [t[0] for t in ins]
		prefix = [0]
		for t in ins:
			prefix.append(prefix[-1] + len(t[3]) + 1)

		def group(x: int) -> range:
			return range(bisect.bisect_left(positions, x), bisect.bisect_right(positions, x))

		def shiftStart(n: Node, x: int) -> int:
			idx = group(x)
			extra = 0
			if len(idx):
				anc = {id(a) for a in n.ancestors()}
				for i in idx:
					_p, _o, _d, label, c, kind = ins[i]
					if kind == "end" and id(c) not in anc or kind == "start" and id(c) in anc:
						extra += len(label) + 1
			return x + prefix[idx.start] + extra

		def before(x: int) -> int:
			return x + prefix[bisect.bisect_left(positions, x)]

		for n in self.nodes:
			s, e = n.start, n.end
			n.start = shiftStart(n, s)
			n.end = max(n.start, before(e))
		# Los trozos van detrás de todo lo insertado en su principio.
		self.chunks = [(cs + prefix[bisect.bisect_right(positions, cs)], before(ce), node) for cs, ce, node in self.chunks]
		parts: list[str] = []
		last = 0
		for k, (pos, _o, _d, label, c, kind) in enumerate(ins):
			parts.append(text[last:pos])
			parts.append(label + "\n")
			last = pos
			ls = pos + prefix[k]
			le = ls + len(label) + 1
			self.boundaryLines.append((ls, le, c, kind))
			if kind == "start":
				c.start = ls
			else:
				# La línea de salida es lo último del contenedor y de los que lo contienen.
				a: Node | None = c
				while a is not None and a is not self.rootParent:
					if a.end < le:
						a.end = le
					a = a.parent
		parts.append(text[last:])
		self.text = "".join(parts)
		self._boundaryStarts = [b[0] for b in self.boundaryLines]

	def chunkAt(self, offset: int) -> tuple[int, int, Node] | None:
		i = bisect.bisect_right(self._chunkStarts, offset) - 1
		if i >= 0:
			s, e, n = self.chunks[i]
			if s <= offset < e:
				return self.chunks[i]
		return None

	def nodeAt(self, offset: int) -> Node | None:
		c = self.chunkAt(offset)
		if c:
			return c[2]
		# Busca el nodo más profundo que contenga el desplazamiento.
		best = None
		for n in self.nodes:
			if n.start <= offset < n.end:
				best = n
			elif n.start > offset:
				break
		return best

	def chunksInRange(self, start: int, end: int) -> list[tuple[int, int, Node]]:
		i = max(0, bisect.bisect_right(self._chunkStarts, start) - 1)
		out = []
		while i < len(self.chunks):
			s, e, n = self.chunks[i]
			if s >= end:
				break
			if e > start:
				out.append(self.chunks[i])
			i += 1
		return out

	def containersAt(self, offset: int) -> list[Node]:
		node = self.nodeAt(offset)
		if node is None:
			return []
		out = [a for a in node.ancestors() if isContainer(a)]
		if isContainer(node):
			out.insert(0, node)
		return list(reversed(out))

	def iterNodes(self, predicate: Callable[[Node], bool], offset: int, direction: int) -> Iterator[Node]:
		"""Nodos que cumplen ``predicate`` después (1) o antes (-1) de ``offset``."""
		if direction > 0:
			for n in self.nodes:
				if n.start > offset and n.end > n.start and predicate(n):
					yield n
		else:
			for n in reversed(self.nodes):
				if n.start < offset and n.end > n.start and predicate(n):
					yield n

	def lineBounds(self, offset: int) -> tuple[int, int]:
		text = self.text
		start = text.rfind("\n", 0, offset) + 1
		end = text.find("\n", offset)
		return start, (len(text) if end == -1 else end + 1)

	# ------------------------------------------------------------ líneas de contenedores (#3997)
	def boundaryAt(self, offset: int) -> tuple[int, int, Node, str] | None:
		"""Línea de entrada o salida de contenedor que contiene ``offset``."""
		i = bisect.bisect_right(self._boundaryStarts, offset) - 1
		if i >= 0:
			b = self.boundaryLines[i]
			if b[0] <= offset < b[1]:
				return b
		return None

	def boundaryContainersIn(self, start: int, end: int) -> set[int]:
		"""``id`` de los contenedores con alguna línea propia en ``[start, end)``."""
		out: set[int] = set()
		i = max(0, bisect.bisect_right(self._boundaryStarts, start) - 1)
		while i < len(self.boundaryLines):
			s, e, c, _k = self.boundaryLines[i]
			if s >= end:
				break
			if e > start:
				out.add(id(c))
			i += 1
		return out

	def plainText(self, start: int, end: int) -> str:
		"""Texto del documento entre dos posiciones sin las líneas de contenedores.

		Es lo que se copia al portapapeles: «lista con 3 elementos» o «fuera de
		lista» no forman parte de la página.
		"""
		if not self.boundaryLines:
			return self.text[start:end]
		parts: list[str] = []
		pos = start
		for s, e, _c, _k in self.boundaryLines:
			if e <= pos:
				continue
			if s >= end:
				break
			parts.append(self.text[pos:s])
			pos = max(pos, e)
		if pos < end:
			parts.append(self.text[pos:end])
		return "".join(parts)

	def contentOffset(self, offset: int, direction: int) -> int:
		"""La posición de texto del documento más cercana (fuera de las líneas de contenedores)."""
		guard = 0
		b = self.boundaryAt(offset)
		while b is not None and guard < 200:
			offset = b[1] if direction > 0 else b[0] - 1
			if offset < 0 or offset >= len(self.text):
				return max(0, min(offset, len(self.text) - 1))
			b = self.boundaryAt(offset)
			guard += 1
		return offset

	# ------------------------------------------------------------ párrafos
	def isInlineNode(self, node: Node) -> bool:
		if node.role not in INLINE_ROLES:
			return False
		return self._screenLayout or node.role not in ATOMIC_ROLES | {Role.LINK}

	def blockOf(self, node: Node | None) -> Node | None:
		"""Bloque (elemento que no fluye en línea) que contiene ``node``."""
		while node is not None and node.role in INLINE_ROLES:
			node = node.parent
		return node

	def textUnitOf(self, node: Node | None) -> Node | None:
		"""Unidad de texto (párrafo) de un nodo.

		Es su bloque, salvo que el bloque sea un contenedor grande (región,
		documento, lista...): los navegadores no publican en la vista de
		control los ``<p>`` sin semántica, así que su texto cuelga directamente
		del contenedor y cada trozo en línea es su propio párrafo.
		"""
		block = self.blockOf(node)
		if block is not None and block is not self.root and block.role not in _NON_PARAGRAPH_BLOCKS:
			return block
		n = node
		while n is not None and n.parent is not None and n.parent is not block:
			n = n.parent
		return n

	def _chunkBefore(self, offset: int):
		i = bisect.bisect_left(self._chunkStarts, offset) - 1
		return self.chunks[i] if 0 <= i < len(self.chunks) else None

	def _chunkAfter(self, offset: int):
		i = bisect.bisect_right(self._chunkStarts, offset)
		return self.chunks[i] if 0 <= i < len(self.chunks) else None

	def isSoftLineBreak(self, nl: int) -> bool:
		"""¿El salto de línea en ``nl`` está dentro de un mismo párrafo?

		Lo es si lo añadió el corte de líneas largas o si separa dos trozos de
		texto del mismo bloque (la distribución en pantalla parte un párrafo
		con enlaces en varias filas).
		"""
		if nl in self.softBreaks:
			return True
		if self.boundaryLines and (self.boundaryAt(nl) is not None or self.boundaryAt(nl + 1) is not None):
			# Las líneas de entrada y salida de contenedores son párrafos propios (#3997).
			return False
		a = self._chunkBefore(nl)
		b = self._chunkAfter(nl)
		if a is None or b is None:
			return False
		ba = self.blockOf(a[2])
		bb = self.blockOf(b[2])
		if ba is None or ba is not bb or ba is self.root:
			return False
		return ba.role not in _NON_PARAGRAPH_BLOCKS

	def paragraphBounds(self, offset: int) -> tuple[int, int]:
		"""Párrafo real: líneas unidas por saltos suaves (no la línea del búfer)."""
		text = self.text
		if not text:
			return 0, 0
		offset = max(0, min(offset, len(text) - 1))
		start, end = self.lineBounds(offset)
		guard = 0
		while start > 0 and guard < 5000 and self.isSoftLineBreak(start - 1):
			start = self.lineBounds(start - 1)[0]
			guard += 1
		while end < len(text) and guard < 10000 and text[end - 1 : end] == "\n" and self.isSoftLineBreak(end - 1):
			end = self.lineBounds(end)[1]
			guard += 1
		return start, end

	# ------------------------------------------------------------ actualización parcial
	def segmentEnd(self, node: Node) -> int:
		"""Fin del texto de un bloque, incluido el salto de línea que lo cierra."""
		e = node.end
		if e > node.start and self.text[e - 1 : e] != "\n" and self.text[e : e + 1] == "\n":
			e += 1
		return e

	def subtreeOf(self, node: Node) -> list[Node]:
		out = []
		stack = [node]
		while stack:
			n = stack.pop()
			out.append(n)
			stack.extend(n.children)
		return out

	def spliceSubtree(self, old: Node, sub: "VirtualBuffer") -> int:
		"""Sustituye el bloque ``old`` por el búfer ``sub`` (su nueva versión).

		Devuelve la diferencia de longitud. Solo se usa con bloques: empiezan
		en principio de línea y su texto termina con un salto de línea.
		"""
		s = old.start
		e = self.segmentEnd(old)
		newText = sub.text
		delta = len(newText) - (e - s)
		oldIds = {id(n) for n in self.subtreeOf(old)}
		self.text = self.text[:s] + newText + self.text[e:]
		ancestorIds = {id(a) for a in old.ancestors()}
		keep = []
		for n in self.nodes:
			if id(n) in oldIds:
				continue
			if id(n) in ancestorIds:
				n.end += delta
			elif n.start >= e:
				n.start += delta
				n.end += delta
			keep.append(n)
		for n in sub.nodes:
			n.start += s
			n.end += s
		newRoot = sub.root
		parent = old.parent
		if newRoot is not None:
			newRoot.parent = parent
		if parent is not None:
			try:
				i = parent.children.index(old)
				if newRoot is None:
					del parent.children[i]
				else:
					parent.children[i] = newRoot
			except ValueError:
				pass
		elif newRoot is not None:
			self.root = newRoot
		self.nodes = keep + sub.nodes
		self.nodes.sort(key=lambda n: (n.start, -n.end))
		for i, n in enumerate(self.nodes):
			n.index = i
		chunks = []
		for cs, ce, n in self.chunks:
			if id(n) in oldIds:
				continue
			if cs >= e:
				chunks.append((cs + delta, ce + delta, n))
			else:
				chunks.append((cs, ce, n))
		chunks.extend((cs + s, ce + s, n) for cs, ce, n in sub.chunks)
		chunks.sort(key=lambda c: c[0])
		self.chunks = chunks
		self._chunkStarts = [c[0] for c in chunks]
		self.softBreaks = {p + delta if p >= e else p for p in self.softBreaks if not (s <= p < e)} | {p + s for p in sub.softBreaks}
		# Líneas de contenedores (#3997): las del bloque se sustituyen por las nuevas.
		lines = [(bs + delta, be + delta, c, k) if bs >= e else (bs, be, c, k) for bs, be, c, k in self.boundaryLines if not (s <= bs < e)]
		lines.extend((bs + s, be + s, c, k) for bs, be, c, k in sub.boundaryLines)
		lines.sort(key=lambda b: b[0])
		self.boundaryLines = lines
		self._boundaryStarts = [b[0] for b in lines]
		self.tables = {k: v for k, v in self.tables.items() if not any(id(c) in oldIds for c in v.values())}
		self.tables.update(sub.tables)
		self.byRid = {n.rid: n for n in self.nodes if n.rid}
		# Fórmulas del bloque nuevo: su MathML queda en el búfer (braille CMU,
		# Intro para explorarlas) y no hay que volver a pedirlo al navegador.
		byNode = self.__dict__.get("_mathByNode")
		if byNode:
			for key in oldIds & byNode.keys():
				del byNode[key]
		for attr in ("_mathByNode", "_mathMl"):
			new = sub.__dict__.get(attr)
			if new:
				self.__dict__.setdefault(attr, {}).update(new)
		# Bloques de texto y estilos guardados (vistazo, mismo estilo...): los
		# nodos del bloque viejo ya no existen.
		for attr in ("_textBlocks", "_blockStyles", "_bodySize", "_tableIndex", "_uiaHeaderCache"):
			self.__dict__.pop(attr, None)
		self.version += 1
		self.edits.append((self.version, s, e, delta))
		del self.edits[:-200]
		return delta

	def translateOffset(self, offset: int, fromVersion: int) -> int:
		"""Desplazamiento de la versión ``fromVersion`` trasladado a la actual.

		Lo de detrás de un bloque rehecho se mueve con él; lo que estaba dentro
		pasa al principio del bloque nuevo (rev. 10.11, M1).
		"""
		if fromVersion >= self.version:
			return offset
		for ver, s, e, delta in self.edits:
			if ver <= fromVersion:
				continue
			if offset >= e:
				offset += delta
			elif offset >= s:
				offset = s
		return max(0, min(offset, len(self.text)))


#: Bloques que no son párrafos aunque contengan texto directamente.
_NON_PARAGRAPH_BLOCKS = {Role.DOCUMENT, Role.LANDMARK, Role.REGION, Role.ARTICLE, Role.SECTION, Role.FORM, Role.LIST, Role.TABLE, Role.DATAGRID, Role.TABLEROW, Role.TREEVIEW, Role.FRAME, Role.DIALOG, Role.TOOLBAR, Role.MENUBAR, Role.POPUPMENU}


def _rectOf(el) -> tuple[int, int, int, int] | None:
	r = _cached(el, uc.P_BOUNDINGRECT, None)
	if r and len(r) >= 4 and r[2] > 0 and r[3] > 0:
		return int(r[0]), int(r[1]), int(r[2]), int(r[3])
	return None


def liveNodeRect(node: Node | None) -> tuple[int, int, int, int] | None:
	"""Rectángulo actual en pantalla de un nodo.

	``node.location`` se fija al construir el búfer y se queda desfasado al
	desplazar la página: se pide al elemento su posición actual y, si no la da
	(elemento ya sin vida, nodos del OCR sin elemento), se usa la guardada.
	"""
	if node is None:
		return None
	el = getattr(node, "element", None)
	if el is not None:
		try:
			r = el.GetCurrentPropertyValueEx(uc.P_BOUNDINGRECT, True)
			if r and not uc.isNotSupported(r) and len(r) >= 4 and r[2] > 0 and r[3] > 0:
				return int(r[0]), int(r[1]), int(r[2]), int(r[3])
		except Exception:
			pass
	return node.location or None


def visualOrder(elements: list) -> list:
	"""Ordena elementos hermanos por columnas visuales (orden de lectura de PDF).

	Los elementos muy anchos (títulos que ocupan toda la página) separan
	franjas; dentro de cada franja se agrupan en columnas por solape
	horizontal y se leen columna a columna, de arriba abajo. Los elementos sin
	posición conservan su lugar tras el elemento que los precedía.
	"""
	items = [(i, el, _rectOf(el)) for i, el in enumerate(elements)]
	placed = [it for it in items if it[2] is not None]
	if len(placed) < 2:
		return list(elements)
	left = min(r[0] for _i, _e, r in placed)
	right = max(r[0] + r[2] for _i, _e, r in placed)
	width = max(1, right - left)
	ordered: list = []

	def flush(band: list) -> None:
		cols: list[list] = []
		for it in sorted(band, key=lambda t: t[2][0]):
			x, _y, w, _h = it[2]
			for c in cols:
				if x < c[1] - 4 and x + w > c[0] + 4:
					c[0] = min(c[0], x)
					c[1] = max(c[1], x + w)
					c[2].append(it)
					break
			else:
				cols.append([x, x + w, [it]])
		cols.sort(key=lambda c: c[0])
		for c in cols:
			ordered.extend(sorted(c[2], key=lambda t: (t[2][1] // 4, t[2][0])))

	band: list = []
	for it in sorted(placed, key=lambda t: (t[2][1], t[2][0])):
		if it[2][2] > width * 0.6:
			flush(band)
			band = []
			ordered.append(it)
		else:
			band.append(it)
	flush(band)
	result = [it[1] for it in ordered]
	positions = {it[0]: k for k, it in enumerate(ordered)}
	for i, el, r in items:
		if r is not None:
			continue
		prev = max((j for j in positions if j < i), default=None)
		k = positions[prev] + 1 if prev is not None else 0
		result.insert(min(k, len(result)), el)
		for j in positions:
			if positions[j] >= k:
				positions[j] += 1
		positions[i] = k
	return result
