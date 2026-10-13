"""Modo exploración para documentos web (Chrome, Edge, Firefox, WebView2...).

El documento se convierte en un búfer de texto por el que se navega con un
cursor virtual (flechas, letras de navegación rápida, tablas...). Con
Tiresias+Espacio se pasa al modo foco, en el que las teclas van directamente
a la página.
"""

from __future__ import annotations

import time
from typing import Any, Callable

import comtypes

from .. import api, formatting, queue_handler, speech, textinfo
from ..a11y import uia_client as uc
from ..audio import tones
from ..baseobject import script
from ..config import conf
from ..i18n import _
from ..log import getLogger
from ..objects.roles import HEADING_ROLES, Role, State, roleLabel, stateLabel
from ..speech import verbosity
from ..textinfo import OffsetsTextInfo
from ..tree_interceptor import TreeInterceptor
from . import html_details
from .extras import BrowseExtrasMixin
from .loader import BufferLoaderMixin
from .tables import TableNavigationMixin
from .buffer import (
	isLayoutTable,
	ATOMIC_ROLES,
	CONTAINER_EXIT_LABELS,
	FORM_FIELD_ROLES,
	PREFIX_FIELD_ROLES,
	Node,
	VirtualBuffer,
)

log = getLogger("browseMode")

CAT = _("Modo exploración")

EDITABLE_ROLES = {Role.EDITABLETEXT, Role.PASSWORDEDIT, Role.COMBOBOX, Role.SLIDER, Role.SPINBUTTON, Role.LIST, Role.TREEVIEW}
ACTIVATABLE_ROLES = {
	Role.LINK,
	Role.BUTTON,
	Role.TOGGLEBUTTON,
	Role.CHECKBOX,
	Role.RADIOBUTTON,
	Role.TAB,
	Role.MENUITEM,
	Role.SWITCH,
	Role.SPLITBUTTON,
	Role.TREEVIEWITEM,
	Role.LISTITEM,
	Role.GRAPHIC,
}

#: Navegación rápida: tecla -> (nombre interno, descripción singular, plural, predicado)
_isHeading = lambda n: n.role in HEADING_ROLES  # noqa: E731


def _headingLevel(level: int) -> Callable[[Node], bool]:
	return lambda n: n.role in HEADING_ROLES and n.headingLevel() == level


QUICK_NAV: list[tuple[str, str, str, str, Callable[[Node], bool]]] = [
	("h", "heading", _("encabezado"), _("encabezados"), _isHeading),
	("1", "heading1", _("encabezado de nivel 1"), _("encabezados de nivel 1"), _headingLevel(1)),
	("2", "heading2", _("encabezado de nivel 2"), _("encabezados de nivel 2"), _headingLevel(2)),
	("3", "heading3", _("encabezado de nivel 3"), _("encabezados de nivel 3"), _headingLevel(3)),
	("4", "heading4", _("encabezado de nivel 4"), _("encabezados de nivel 4"), _headingLevel(4)),
	("5", "heading5", _("encabezado de nivel 5"), _("encabezados de nivel 5"), _headingLevel(5)),
	("6", "heading6", _("encabezado de nivel 6"), _("encabezados de nivel 6"), _headingLevel(6)),
	("k", "link", _("enlace"), _("enlaces"), lambda n: n.role == Role.LINK),
	("u", "unvisitedLink", _("enlace no visitado"), _("enlaces no visitados"), lambda n: n.role == Role.LINK and State.VISITED not in n.states),
	("v", "visitedLink", _("enlace visitado"), _("enlaces visitados"), lambda n: n.role == Role.LINK and State.VISITED in n.states),
	("l", "list", _("lista"), _("listas"), lambda n: n.role == Role.LIST),
	("i", "listItem", _("elemento de lista"), _("elementos de lista"), lambda n: n.role == Role.LISTITEM),
	("t", "table", _("tabla"), _("tablas"), lambda n: n.role in (Role.TABLE, Role.DATAGRID) and not isLayoutTable(n)),
	("f", "formField", _("campo de formulario"), _("campos de formulario"), lambda n: n.role in FORM_FIELD_ROLES and n.role != Role.LIST or (n.role == Role.LIST and n.isFocusable)),
	("e", "edit", _("campo de edición"), _("campos de edición"), lambda n: n.role in (Role.EDITABLETEXT, Role.PASSWORDEDIT) or n.role == Role.COMBOBOX and State.READONLY not in n.states),
	("b", "button", _("botón"), _("botones"), lambda n: n.role in (Role.BUTTON, Role.TOGGLEBUTTON, Role.SPLITBUTTON, Role.MENUBUTTON)),
	("x", "checkBox", _("casilla de verificación"), _("casillas de verificación"), lambda n: n.role in (Role.CHECKBOX, Role.SWITCH)),
	("c", "comboBox", _("cuadro combinado"), _("cuadros combinados"), lambda n: n.role == Role.COMBOBOX),
	("r", "radioButton", _("botón de opción"), _("botones de opción"), lambda n: n.role == Role.RADIOBUTTON),
	("g", "graphic", _("gráfico"), _("gráficos"), lambda n: n.role == Role.GRAPHIC),
	("d", "landmark", _("punto de referencia"), _("puntos de referencia"), lambda n: n.role == Role.LANDMARK),
	("q", "blockQuote", _("cita"), _("citas"), lambda n: n.role == Role.BLOCKQUOTE),
	("s", "separator", _("separador"), _("separadores"), lambda n: n.role == Role.SEPARATOR),
	("m", "frame", _("marco"), _("marcos"), lambda n: n.role in (Role.FRAME, Role.DOCUMENT) and n.parent is not None),
	("o", "embeddedObject", _("objeto incrustado"), _("objetos incrustados"), lambda n: n.role in (Role.EMBEDDEDOBJECT, Role.APPLICATION, Role.VIDEO, Role.AUDIO)),
	("p", "paragraph", _("párrafo"), _("párrafos"), lambda n: n.role == Role.PARAGRAPH or (n.ariaRole == "paragraph")),
	("a", "article", _("artículo"), _("artículos"), lambda n: n.role == Role.ARTICLE),
	("j", "dialog", _("diálogo"), _("diálogos"), lambda n: n.role == Role.DIALOG),
	("w", "tab", _("pestaña"), _("pestañas"), lambda n: n.role == Role.TAB),
	("y", "menuItem", _("elemento de menú"), _("elementos de menú"), lambda n: n.role in (Role.MENUITEM, Role.CHECKMENUITEM, Role.RADIOMENUITEM)),
	("z", "focusable", _("elemento enfocable"), _("elementos enfocables"), lambda n: n.isFocusable and n.role not in (Role.DOCUMENT,)),
	("0", "math", _("fórmula matemática"), _("fórmulas matemáticas"), lambda n: n.role == Role.MATH),
]
# Tipos añadidos: encabezados 7-9, anotación, error, vistazo, deslizador... (quicknav.py).
from . import quicknav  # noqa: E402

QUICK_NAV.extend(quicknav.EXTRA_QUICK_NAV)


#: Última posición del cursor en cada página (dirección o título -> (desplazamiento, texto de la línea)).
_savedPositions: dict[str, Any] = {}
#: Páginas recordadas como máximo (las más antiguas se olvidan).
MAX_SAVED_POSITIONS = 300


def _remapOffset(old: VirtualBuffer, new: VirtualBuffer, offset: int) -> int:
	"""Desplazamiento de ``old`` en ``new`` (por el elemento que lo contiene)."""
	if not new.text:
		return 0
	if not old.text:
		return max(0, min(offset, len(new.text)))
	node = old.nodeAt(max(0, min(offset, len(old.text) - 1)))
	n = node
	while n is not None and not (n.rid and n.rid in new.byRid):
		n = n.parent
	if n is None:
		return max(0, min(offset, len(new.text)))
	target = new.byRid[n.rid]
	pos = target.start + max(0, offset - n.start)
	return max(0, min(pos, max(target.start, target.end - 1), len(new.text)))


def lineAnchor(buf: VirtualBuffer | None, offset: int) -> tuple[int, str]:
	"""(principio de la línea, su texto) para recolocar una posición guardada."""
	if buf is None or not buf.text:
		return offset, ""
	s, e = buf.lineBounds(max(0, min(offset, len(buf.text) - 1)))
	return s, " ".join(buf.text[s:e].split())[:80]


def resolveAnchor(buf: VirtualBuffer | None, offset: int, text: str = "") -> int | None:
	"""Posición actual de una línea guardada: la aparición de su texto más cercana al desplazamiento.

	Rev. 10.11 (B4): los marcadores y la última posición de cada página
	guardaban solo el desplazamiento; si la página cambiaba apuntaban a otro sitio.
	"""
	if buf is None or not buf.text:
		return None
	if text:
		norm = text
		best = None
		pos = 0
		# Se buscan las líneas que empiezan igual (con el texto normalizado).
		key = norm[:40]
		while key:
			i = buf.text.find(key, pos)
			if i < 0:
				break
			s, e = buf.lineBounds(i)
			if " ".join(buf.text[s:e].split())[:80] == norm and (best is None or abs(s - offset) < abs(best - offset)):
				best = s
			pos = i + 1
			if pos - offset > 200000 and best is not None:
				break
		if best is not None:
			return best
	if offset < len(buf.text):
		return offset
	return None


class BufferTextInfo(OffsetsTextInfo):
	"""Rango del búfer que sigue a sus cambios.

	Rev. 10.11 (M1): el texto no se guarda en el rango (la lectura continua
	usaba una copia vieja con desplazamientos del búfer nuevo). Si el búfer se
	actualiza por partes, los desplazamientos se trasladan con su registro de
	empalmes; si se reconstruye entero, se recolocan por el elemento.
	"""

	def __init__(self, doc: "BrowseModeDocument", position: Any) -> None:
		self.doc = doc
		buf = doc.buffer
		self._buf = buf
		self._bufVersion = getattr(buf, "version", 0)
		super().__init__(doc, position)

	def _getStoryText(self) -> str:
		return self.doc.buffer.text if self.doc.buffer else ""

	def _story(self) -> str:
		self._syncBuffer()
		buf = self.doc.buffer
		return buf.text if buf is not None else ""

	def _syncBuffer(self) -> None:
		buf = self.doc.buffer
		old = self.__dict__.get("_buf")
		if buf is None:
			return
		if old is buf:
			ver = getattr(buf, "version", 0)
			if self._bufVersion != ver:
				self._start = buf.translateOffset(self._start, self._bufVersion)
				self._end = max(self._start, buf.translateOffset(self._end, self._bufVersion))
				self._bufVersion = ver
			return
		if old is not None and old.text and "_start" in self.__dict__:
			# Búfer nuevo (reconstrucción completa): se recoloca por el elemento.
			start, end = self._start, self._end
			self._start = _remapOffset(old, buf, start)
			self._end = self._start if end == start else max(self._start, _remapOffset(old, buf, end))
		self._buf = buf
		self._bufVersion = getattr(buf, "version", 0)

	@property
	def offsets(self) -> tuple[int, int]:
		self._syncBuffer()
		return self._start, self._end

	def compareEndPoints(self, other, which: str) -> int:
		self._syncBuffer()
		if isinstance(other, BufferTextInfo):
			other._syncBuffer()
		return super().compareEndPoints(other, which)

	def setEndPoint(self, other, which: str) -> None:
		self._syncBuffer()
		if isinstance(other, BufferTextInfo):
			other._syncBuffer()
		super().setEndPoint(other, which)

	def updateCaret(self) -> None:
		self._syncBuffer()
		super().updateCaret()

	def updateSelection(self) -> None:
		self._syncBuffer()
		super().updateSelection()

	def _getCaretOffset(self) -> int:
		return self.doc.caret

	def _setCaretOffset(self, offset: int) -> None:
		self.doc.caret = offset
		self.doc.selectionAnchor = None

	def _getSelectionOffsets(self) -> tuple[int, int]:
		return self.doc.selection

	def _setSelectionOffsets(self, start: int, end: int) -> None:
		self.doc.selectionAnchor = start
		self.doc.caret = end

	def getEnclosingObject(self) -> Any:
		node = self.doc.buffer.nodeAt(self._start) if self.doc.buffer else None
		return self.doc.objectForNode(node) if node else None

	def activate(self) -> None:
		self.doc.activateAt(self._start)

	@property
	def pointAtStart(self):
		from .buffer import liveNodeRect

		node = self.doc.buffer.nodeAt(self._start) if self.doc.buffer else None
		# Posición actual (la del búfer queda desfasada al desplazar la página).
		rect = liveNodeRect(node) if node else None
		if rect:
			x, y, w, h = rect
			return textinfo.Point(x + w // 2, y + h // 2)
		return None

	def speakLine(self) -> None:
		self.doc.speakLineAt(self._start)

	def _getParagraphOffsets(self, offset: int) -> tuple[int, int]:
		"""Párrafo real: une las líneas cortadas por el búfer (no es la línea)."""
		buf = self.doc.buffer
		if buf is None or textinfo.paragraphStyle() == "multiLineBreak":
			return super()._getParagraphOffsets(offset)
		return buf.paragraphBounds(offset)

	def getFormatInfo(self, keys: set[str] | None = None) -> dict:
		"""Formato del texto (atributos UIA del documento y semántica de la página)."""
		from . import style

		if self.doc.buffer is None or not self.doc.buffer.text:
			return {}
		return style.formatAt(self.doc, min(self._start, len(self.doc.buffer.text) - 1), keys)


class BrowseModeDocument(BrowseExtrasMixin, TableNavigationMixin, BufferLoaderMixin, TreeInterceptor):
	scriptCategory = CAT

	#: Scripts que siguen activos en modo foco.
	_passThroughScripts = {"toggleFocusMode", "exitFocusMode", "refreshBuffer", "reportUrl", "reportPageSummary", "inspectElement", "flexManage"}

	def __init__(self, rootObject: Any) -> None:
		super().__init__(rootObject)
		self.buffer: VirtualBuffer | None = None
		self.caret = 0
		self.selectionAnchor: int | None = None
		self._lastCaret = 0
		self._dirty = False
		self._rebuildTimer: int | None = None
		self._lastBuildTime = 0.0
		self._lastFind = ""
		self._loadAnnounced = False
		self._structureHandlerRegistered = False
		self._built = False
		#: Con «Activar el modo exploración al cargar las páginas» desactivado,
		#: el documento empieza en modo foco y el paso automático entre modos
		#: queda en pausa hasta que el usuario pase a modo exploración a mano.
		self._disableAutoPassThrough = not conf["browseMode"]["enableOnPageLoad"]
		if self._disableAutoPassThrough:
			self._passThrough = True
		self._loaderInit()
		self._extrasInit()
		#: Modo foco fijado a mano (Tiresias+Espacio): el foco no lo cambia.
		self._focusModeLocked = False
		from . import browseModeKind

		# Las subclases sin árbol UIA (resultado del OCR) fijan ``fixedBufferKind``.
		self.bufferKind = getattr(self, "fixedBufferKind", None) or browseModeKind(rootObject) or "tree"
		#: Word editable: se empieza en modo foco y el búfer se construye al pedirlo.
		self.lazyBuild = self.bufferKind == "lazyText"
		if self.lazyBuild:
			self._passThrough = True
			self._focusModeLocked = True
		else:
			# Documentos de texto: el cursor virtual empieza donde está el del sistema.
			self._syncCaretFromApp = self.bufferKind == "text"
			self.requestRebuild(initial=True)
		if self.bufferKind == "tree":
			from ..a11y import uia_handler

			self._structureHandlerRegistered = uia_handler.registerStructureChanged(self, self.rootObject.element)

	# --------------------------------------------------------- ciclo de vida
	#: Segundos entre dos comprobaciones de vida por UIA (llamadas entre procesos).
	ALIVE_CHECK_INTERVAL = 3.0

	@property
	def isAlive(self) -> bool:
		"""¿Sigue vivo el documento?

		Rev. 10.11 (A7): se consultaba por UIA (dos llamadas entre procesos) en
		cada evento y para cada documento abierto; con la aplicación colgada,
		cada evento de cualquier programa esperaba el tiempo límite de UIA.
		Ahora se mira la ventana (barato) y la comprobación por UIA se hace como
		mucho cada pocos segundos y nunca con la ventana colgada.
		"""
		if self.__dict__.get("_terminated"):
			return False
		from .. import winapi

		hwnd = 0
		try:
			hwnd = int(getattr(self.rootObject, "windowHandle", 0) or 0)
		except Exception:
			hwnd = 0
		try:
			if hwnd and not winapi.user32.IsWindow(hwnd):
				return False
		except Exception:
			pass
		now = time.monotonic()
		last = self.__dict__.get("_aliveChecked")
		if last is not None and now - last[0] < self.ALIVE_CHECK_INTERVAL:
			return last[1]
		if hwnd and last is not None:
			try:
				if winapi.user32.IsHungAppWindow(hwnd):
					return last[1]
			except Exception:
				pass
		try:
			el = self.rootObject.element
			alive = bool(el.CurrentProcessId) and el.CurrentControlType == uc.CT_DOCUMENT
		except (comtypes.COMError, AttributeError, ValueError):
			alive = False
		self.__dict__["_aliveChecked"] = (now, alive)
		return alive

	def terminate(self) -> None:
		from ..a11y import uia_handler

		if conf["browseMode"]["rememberPositionPerPage"] and self.buffer is not None:
			try:
				self._rememberPosition()
			except Exception:
				pass
		if self._structureHandlerRegistered:
			uia_handler.unregisterStructureChanged(self)
		self._terminated = True
		self._stopLoadingIndicator()
		self.buffer = None

	def contains(self, obj: Any, ancestors: list | None = None) -> bool:
		if obj is None:
			return False
		if obj == self.rootObject:
			return True
		rid = getattr(obj, "runtimeId", None)
		if self.buffer and rid and rid in self.buffer.byRid:
			return True
		return super().contains(obj, ancestors)

	def makeBuffer(self) -> VirtualBuffer:
		"""Búfer vacío del tipo adecuado (árbol de elementos o patrón Text)."""
		if self.bufferKind in ("text", "lazyText"):
			from .textbuffer import TextPatternBuffer

			buf: VirtualBuffer = TextPatternBuffer(self.rootObject.element)
			if isinstance(self.buffer, TextPatternBuffer):
				# Si el texto no cambió se reutiliza (A3: se comprueba al volver).
				buf.reuseFrom = self.buffer
		else:
			buf = VirtualBuffer(self.rootObject.element)
		self.configureBuffer(buf)
		return buf

	def configureBuffer(self, buf: VirtualBuffer) -> None:
		super().configureBuffer(buf)
		# Entrada y salida de contenedores en líneas propias (#3997).
		buf.containerLabels = self.containerLineLabels if conf["browseMode"]["containerLinesApart"] else None
		buf.layoutSignature = self.layoutSignature()

	@staticmethod
	def layoutSignature() -> tuple:
		"""Opciones que cambian el texto del búfer (si cambian, se reconstruye)."""
		bm = conf["browseMode"]
		sig: tuple = (bm["useScreenLayout"], bm["breakAfterLinks"], bm["containerLinesApart"], bm["includeLayoutTables"], bm["maxLineLength"])
		# Imágenes sin texto alternativo y su nombre de archivo (#7412).
		sig += (bm["reportUnlabeledGraphics"], bm["reportGraphicFileNames"])
		if bm["containerLinesApart"]:
			df = conf["documentFormatting"]
			keys = ("reportLists", "reportTables", "reportLandmarks", "reportBlockQuotes", "reportArticles", "reportFigures", "reportFrames", "reportGroupings")
			sig += tuple(df.get(k) for k in keys)
		return sig

	def containerLineLabels(self, node: Node) -> tuple[str, str]:
		"""Texto de las líneas de entrada y salida de un contenedor (#3997)."""
		entry = self.fullPrefix(node)
		label = CONTAINER_EXIT_LABELS.get(node.role, "")
		exitLabel = ""
		if label and formatting.shouldReportContainer(node.role, node.name):
			exitLabel = label.format(landmark=node.landmark or _("región"))
		return entry, exitLabel

	def _rebuild(self, initial: bool = False) -> None:
		"""Reconstrucción síncrona (en el hilo del núcleo)."""
		start = time.monotonic()
		buf = self.makeBuffer()
		try:
			buf.build()
		except comtypes.COMError:
			if initial or self.buffer is None:
				self.buffer = self.makeBuffer()
			return
		self._installBuffer(buf, initial, time.monotonic() - start)
		self._readyEvent.set()

	def _installBuffer(self, buf: VirtualBuffer, initial: bool, elapsed: float) -> None:
		"""Pone en uso un búfer recién construido conservando la posición."""
		oldRid = None
		delta = 0
		if self.buffer is not None and self.buffer.text:
			node = self.buffer.nodeAt(self.caret)
			if node is not None and node.rid:
				oldRid = node.rid
				delta = self.caret - node.start
		self.buffer = buf
		self._built = True
		self.__dict__.pop("_docKey", None)
		self.__dict__.pop("_docUrl", None)
		self._lastBuildTime = time.monotonic()
		if oldRid and oldRid in buf.byRid:
			n = buf.byRid[oldRid]
			self.caret = min(n.start + delta, max(n.start, n.end - 1))
		else:
			self.caret = min(self.caret, max(0, len(buf.text) - 1))
		self.selectionAnchor = None
		self._pendingElements = []
		if self.__dict__.get("_syncCaretFromApp"):
			# Documentos de texto: el cursor virtual va donde está el del sistema
			# (también al reconstruir tras editar, A3).
			self._syncCaretFromApp = False
			self.caretFromApplication()
		try:
			self._applyPendingFocus()
		except Exception:
			log.debug("No se pudo llevar el cursor al foco", exc_info=True)
		log.debug("Búfer construido en %.0f ms (%d nodos, %d caracteres)", elapsed * 1000, len(buf.nodes), len(buf.text))

	# --------------------------------------------------------- modo foco
	def _set_passThrough(self, state: bool) -> None:
		if state == self._passThrough:
			return
		self._passThrough = state
		self.noteModeReported(state)
		self.onPassThroughChanged(state)
		if conf["browseMode"]["passThroughAudioIndication"]:
			tones.playSound("focusMode" if state else "browseMode")
		else:
			speech.speakMessage(_("modo foco") if state else _("modo exploración"))
		from ..input import core as inputCore

		inputCore.manager.updateChain()

	def getScript(self, gesture):
		func = super().getScript(gesture)
		if func is None:
			return None
		if self.passThrough and func.__name__[7:] not in self._passThroughScripts:
			return None
		if not self.isReady and func.__name__[7:] not in self._passThroughScripts:
			# Documento cargándose. Rev. 10.11 (M7): la navegación con una letra
			# avisa «cargando»; el resto de teclas (Tab, flechas, Intro, Escape...)
			# llega a la aplicación en lugar de perderse.
			if func.__name__.startswith("script_quickNav"):
				return self.script_documentLoading
			return None
		# Se lee la opción cada vez: la cambian Opciones, los perfiles (por sitio web)
		# y Tiresias+Mayúsculas+Espacio desde cualquier otro documento abierto.
		if not conf["browseMode"]["singleLetterNavigation"] and func.__name__.startswith("script_quickNav") and not (set(gesture.modifierNames) - {"shift"}):
			return None
		return func

	# --------------------------------------------------------- texto
	def makeTextInfo(self, position: Any) -> BufferTextInfo:
		return BufferTextInfo(self, position)

	@property
	def selection(self) -> tuple[int, int]:
		if self.selectionAnchor is None:
			return self.caret, self.caret
		return min(self.selectionAnchor, self.caret), max(self.selectionAnchor, self.caret)

	def objectForNode(self, node: Node | None):
		if node is None or node.element is None:
			return None
		from ..objects.uia import UIAObject

		return UIAObject.fromElement(node.element)

	# --------------------------------------------------------- voz
	def fieldPrefix(self, node: Node) -> str:
		df = conf["documentFormatting"]
		role = node.role
		if role == Role.LINK and df["reportLinks"]:
			label = _("enlace")
			if State.VISITED in node.states:
				label += " " + _("visitado")
			# Tipo de enlace (opción de formato de documento): anclas de la misma página.
			# Con el destino guardado en el búfer: pedirlo a la página en cada enlace
			# que se lee eran dos llamadas entre procesos en el hilo del núcleo.
			linkType = formatting.linkTypeText(node.url, self.documentUrl())
			if linkType:
				label += " " + linkType
			return label
		if role in HEADING_ROLES and df["reportHeadings"]:
			lvl = node.headingLevel()
			return _("encabezado de nivel {level}").format(level=lvl) if lvl else _("encabezado")
		if role == Role.LIST and df["reportLists"]:
			count = sum(1 for c in node.children if c.role == Role.LISTITEM) or sum(1 for c in node.children if c.end > c.start)
			return _("lista con {n} elementos").format(n=count) if count != 1 else _("lista con 1 elemento")
		if role in (Role.TABLE, Role.DATAGRID) and df["reportTables"]:
			if node.tableSize:
				rows, cols = node.tableSize
				return _("tabla con {rows} filas y {cols} columnas").format(rows=rows, cols=cols)
			return _("tabla")
		if role == Role.LANDMARK and df["reportLandmarks"]:
			parts = [node.landmark or _("región"), _("punto de referencia")]
			if node.name and node.name.lower() != (node.landmark or "").lower():
				parts.insert(0, node.name)
			return " ".join(parts)
		if role == Role.REGION and df["reportLandmarks"] and node.name:
			return f"{node.name} {_('región')}"
		if role == Role.BLOCKQUOTE and df["reportBlockQuotes"]:
			return _("cita")
		if role == Role.ARTICLE and df["reportArticles"]:
			return _("artículo")
		if role == Role.FIGURE and df["reportFigures"]:
			return _("figura")
		if role == Role.DIALOG:
			return f"{node.name} {_('diálogo')}".strip()
		if role == Role.GRAPHIC and df["reportGraphics"]:
			return _("gráfico")
		if role == Role.TREEVIEW:
			return _("árbol")
		if role == Role.FRAME and df["reportFrames"]:
			return f"{node.name} {_('marco')}".strip()
		if role == Role.GROUPING and node.name and df["reportGroupings"]:
			return f"{node.name} {_('agrupación')}"
		if role == Role.MATH:
			from .. import mathpres  # noqa: F401  (registra la sección «math»)

			return _("matemáticas") if conf["math"]["announceMathRole"] else ""
		parts: list[str] = []
		fmtLabels = {
			"emphasis": (df["reportEmphasis"], _("énfasis")),
			"strong": (df["reportEmphasis"], _("énfasis fuerte")),
			"mark": (df["reportHighlight"], _("resaltado")),
			"insertion": (df["reportRevisions"], _("insertado")),
			"deletion": (df["reportRevisions"], _("eliminado")),
			"comment": (df["reportComments"], _("comentario")),
		}
		if node.fmt in fmtLabels and fmtLabels[node.fmt][0]:
			parts.append(fmtLabels[node.fmt][1])
		if node.clickable and df["reportClickable"]:
			parts.append(_("pulsable"))
		return " ".join(parts)

	def fullPrefix(self, node: Node) -> str:
		"""Prefijo del elemento más la información ARIA (tipo de enlace, detalles...)."""
		base = self.fieldPrefix(node)
		parts = [base] + [p for p in self.extraPrefix(node) if p and p.lower() not in base.lower()]
		return " ".join(p for p in parts if p)

	def controlSuffix(self, node: Node) -> str:
		role = node.role
		extra = self.extraSuffix(node)
		if role not in ATOMIC_ROLES or role in (Role.GRAPHIC, Role.SEPARATOR):
			return " ".join(extra)
		# Plantilla del tipo de control (Opciones, Voz): lo que no está en ella
		# tampoco se dice en el modo exploración (p. ej. «{name} {value}» quita «edición»).
		template = verbosity.templateFor(role)
		showStates = template is None or "{states}" in template
		parts = [roleLabel(role)] if template is None or "{role}" in template else []
		for st in (State.CHECKED, State.HALFCHECKED, State.PRESSED, State.ON, State.EXPANDED, State.COLLAPSED, State.SELECTED, State.UNAVAILABLE, State.REQUIRED, State.INVALID_ENTRY, State.HASPOPUP, State.READONLY):
			if st in node.states and showStates:
				if st == State.SELECTED and role not in (Role.TAB,):
					continue
				if st == State.READONLY and role not in (Role.EDITABLETEXT, Role.COMBOBOX, Role.PASSWORDEDIT):
					continue
				if st == State.HASPOPUP and role != Role.COMBOBOX and node.aria.get("haspopup") not in (None, "", "false"):
					# El tipo de emergente (menú, lista, diálogo...) va en la información ARIA.
					continue
				parts.append(stateLabel(st))
		if showStates and role in (Role.CHECKBOX,) and State.CHECKED not in node.states and State.HALFCHECKED not in node.states:
			parts.append(_("no marcado"))
		if showStates and role == Role.SWITCH and State.ON not in node.states:
			parts.append(_("desactivado"))
		if node.description and node.description != node.name and (template is None or "{description}" in template):
			parts.append(node.description)
		parts.extend(extra)
		return " ".join(p for p in parts if p)

	def _isPrefixField(self, node: Node) -> bool:
		if isLayoutTable(node):
			return False
		if node.role in PREFIX_FIELD_ROLES or node.fmt or node.clickable or self.wantsPrefix(node):
			return True
		return node.role in (Role.GROUPING, Role.FRAME) and bool(node.name)

	def _nodeLanguage(self, node: Node) -> str | None:
		"""Idioma efectivo de un nodo (el suyo o el de su antecesor más cercano)."""
		n: Node | None = node
		while n is not None:
			if n.culture:
				return n.culture
			n = n.parent
		return None

	def getRangeSpeech(self, start: int, end: int) -> list:
		"""Secuencia de voz (cadenas y cambios de idioma) del rango indicado."""
		from ..presentation import normalizeLanguage
		from ..speech import voice_schemes
		from ..speech.commands import LangChangeCommand, WaveFileCommand

		buf = self.buffer
		if buf is None:
			return []
		switchLang = conf["speech"]["autoLanguageSwitching"]
		scheme = voice_schemes.activeScheme()
		seq: list = []
		announced: set[int] = set()
		suffixed: set[int] = set()
		cellState: dict = {}
		schemeState: dict = {}
		currentLang: str | None = None
		pos = start
		for cs, ce, node in buf.chunksInRange(start, end):
			if cs > pos:
				gap = buf.text[pos:cs]
				if gap.strip():
					seq.append(gap)
			chain = [node] + list(node.ancestors())
			for anc in reversed(chain):
				# El elemento empieza en este trozo (los elementos en línea empiezan
				# en el espacio que los separa del texto anterior).
				if id(anc) not in announced and anc.start <= cs and not buf.text[anc.start : cs].strip() and self._isPrefixField(anc):
					announced.add(id(anc))
					prefix = self.fullPrefix(anc)
					attr = voice_schemes.nodeAttribute(anc) if scheme else None
					if attr:
						# Esquema de voz y sonido: el sonido puede sustituir a la etiqueta.
						before, _after, prefix = voice_schemes.decorate(attr, "", prefix)
						seq.extend(c for c in before if isinstance(c, WaveFileCommand))
					if prefix:
						seq.append(prefix)
			seq.extend(self.cellEntrySpeech(node, cs, cellState))
			if switchLang:
				lang = self._nodeLanguage(node)
				lang = normalizeLanguage(lang) if lang else None
				if lang != currentLang:
					seq.append(LangChangeCommand(lang))
					currentLang = lang
			text = buf.text[max(start, cs) : min(end, ce)]
			# Comillas de <q>: «cita» y «fin de cita» (#14654).
			text = html_details.quoteSpeech(node, text)
			if text.strip():
				if scheme:
					# Esquema: voz del atributo (sin repetir el sonido de la etiqueta),
					# del tipo de control, de sus estados y del color (foros 2.4).
					before, after = voice_schemes.textDecoration(self, node, cs, schemeState)
					seq.extend(before)
					seq.append(text)
					seq.extend(after)
				else:
					seq.append(text)
			if id(node) not in suffixed and ce <= end:
				suffixed.add(id(node))
				suffix = self.controlSuffix(node)
				if suffix and scheme:
					seq.extend(voice_schemes.controlSounds(node, schemeState))
					suffix = voice_schemes.filterSuffix(node, suffix)
				if suffix:
					seq.append(suffix)
			pos = min(end, ce)
		if currentLang is not None:
			seq.append(LangChangeCommand(None))
		if pos < end:
			rest = buf.text[pos:end]
			if rest.strip():
				seq.append(rest)
		return seq

	@staticmethod
	def compactSpeech(seq: list) -> list:
		"""Une las cadenas contiguas con espacios conservando las órdenes de voz."""
		out: list = []
		for item in seq:
			if isinstance(item, str):
				if out and isinstance(out[-1], str):
					out[-1] = f"{out[-1]} {item}"
				else:
					out.append(item)
			elif item is not None:
				out.append(item)
		return out

	def _containerTransitions(self, old: int, new: int, rangeStart: int, rangeEnd: int) -> list[str]:
		buf = self.buffer
		if buf is None:
			return []
		oldC = buf.containersAt(old)
		newC = buf.containersAt(new)
		if buf.boundaryLines:
			# Contenedores con líneas propias (#3997): su entrada y su salida se
			# leen en esas líneas; no se repiten al llegar a ellas ni al dejarlas.
			ob = buf.boundaryAt(old)
			skip = buf.boundaryContainersIn(rangeStart, rangeEnd)
			nb = buf.boundaryAt(new)
			for b in (ob, nb):
				if b is not None:
					skip.add(id(b[2]))
			oldC = [c for c in oldC if id(c) not in skip]
			newC = [c for c in newC if id(c) not in skip]
		out: list[str] = []
		for c in reversed(oldC):
			if c not in newC:
				label = CONTAINER_EXIT_LABELS.get(c.role, "")
				if label and formatting.shouldReportContainer(c.role, c.name):
					out.append(label.format(landmark=c.landmark or _("región")))
		for c in newC:
			if c not in oldC and not (rangeStart <= c.start < rangeEnd):
				prefix = self.fullPrefix(c)
				if prefix:
					out.append(prefix)
		return out

	def speakLineAt(self, offset: int, oldOffset: int | None = None) -> None:
		buf = self.buffer
		if buf is None:
			return
		start, end = buf.lineBounds(offset)
		seq: list[str] = []
		if oldOffset is not None:
			seq.extend(self._containerTransitions(oldOffset, offset, start, end))
		body = self.getRangeSpeech(start, end)
		if not body:
			body = [_("en blanco")]
		seq.extend(body)
		speech.speak(self.compactSpeech(seq))
		self._updateBraille(start, end)

	def speakNode(self, node: Node, oldOffset: int | None = None) -> None:
		seq: list[str] = []
		if oldOffset is not None:
			seq.extend(self._containerTransitions(oldOffset, node.start, node.start, node.end))
		end = node.end
		if node.role in (Role.LIST, Role.TABLE, Role.DATAGRID, Role.LANDMARK, Role.ARTICLE, Role.DIALOG, Role.REGION, Role.BLOCKQUOTE):
			# Contenedores grandes: prefijo + primera línea.
			_s, end = self.buffer.lineBounds(node.start)
		seq.extend(self.getRangeSpeech(node.start, max(node.start + 1, end)))
		if not seq:
			seq.append(self.fieldPrefix(node) or roleLabel(node.role))
		speech.speak(self.compactSpeech([s for s in seq if s]))
		self._updateBraille(*self.buffer.lineBounds(node.start))

	def _updateBraille(self, start: int, end: int) -> None:
		from .. import braille

		try:
			from ..mathpres import browse_support

			mathLine = browse_support.brailleLine(self, start, end, withMap=True)
		except Exception:
			mathLine = None
		try:
			# Las líneas sustituidas llevan la posición en el búfer de cada
			# carácter, para que el enrutamiento apunte al carácter correcto.
			if mathLine is not None:
				text, cursor, offsets = mathLine
				braille.handler.handleBrowseLine(text, cursor, offsets=offsets)
				return
			# aria-braillelabel y aria-brailleroledescription (#11829).
			labelLine = html_details.brailleLabelLine(self, start, end, withMap=True)
			if labelLine is not None:
				text, cursor, offsets = labelLine
				braille.handler.handleBrowseLine(text, cursor, offsets=offsets)
				return
			braille.handler.handleBrowseLine(self.buffer.text[start:end], self.caret - start)
		except Exception:
			log.debug("Braille no disponible", exc_info=True)

	# --------------------------------------------------------- movimiento
	def _moveCaret(self, newOffset: int, speakUnit: str | None = textinfo.UNIT_LINE, node: Node | None = None) -> None:
		buf = self.buffer
		if buf is None or not buf.text:
			speech.speakMessage(_("documento vacío"))
			return
		newOffset = max(0, min(newOffset, len(buf.text) - 1))
		old = self.caret
		self.caret = newOffset
		self.selectionAnchor = None
		speech.cancelSpeech()
		if node is not None:
			self.speakNode(node, old)
		elif speakUnit == textinfo.UNIT_LINE:
			self.speakLineAt(newOffset, old)
		elif speakUnit in (textinfo.UNIT_PARAGRAPH, textinfo.UNIT_SENTENCE):
			self.speakUnitAt(newOffset, speakUnit, old)
		elif speakUnit is not None:
			from .. import presentation

			presentation.speakTextInfo(self.makeTextInfo(textinfo.POSITION_CARET), speakUnit)
		self._afterCaretMove(node or buf.nodeAt(newOffset))

	def _afterCaretMove(self, node: Node | None) -> None:
		api.setReviewPosition(self.makeTextInfo(textinfo.POSITION_CARET), isCaret=True)
		if conf["browseMode"]["rememberPositionPerPage"]:
			self._rememberPosition()
		if node is None or node.element is None:
			return
		bm = conf["browseMode"]
		if bm["autoPassThroughOnCaretMove"] and not self.passThrough:
			target: Node | None = node
			while target is not None and target.role not in EDITABLE_ROLES:
				target = target.parent
			if target is not None and target.role not in (Role.LIST, Role.TREEVIEW) and target.isFocusable:
				try:
					target.element.SetFocus()
				except comtypes.COMError:
					pass
				self.passThrough = True
				return
		if bm["scrollIntoView"]:
			try:
				pat = node.element.GetCurrentPattern(uc.PAT_SCROLLITEM)
				if pat:
					pat.QueryInterface(uc.UIA.IUIAutomationScrollItemPattern).ScrollIntoView()
			except (comtypes.COMError, ValueError, AttributeError):
				pass
		if bm["autoFocusFocusableElements"] and node.isFocusable:
			try:
				node.element.SetFocus()
			except comtypes.COMError:
				pass

	def speakUnitAt(self, offset: int, unit: str, oldOffset: int | None = None) -> None:
		"""Lee el párrafo o la frase que empieza en ``offset`` con su información."""
		info = self.makeTextInfo((offset, offset))
		info.expand(unit)
		s, e = info.offsets
		seq: list = []
		if oldOffset is not None:
			seq.extend(self._containerTransitions(oldOffset, offset, s, e))
		body = self.getRangeSpeech(s, e)
		seq.extend(body or [_("en blanco")])
		speech.speak(self.compactSpeech(seq))
		self._updateBraille(*self.buffer.lineBounds(offset))

	def _moveByUnit(self, unit: str, direction: int) -> None:
		if unit == textinfo.UNIT_LINE and self.navLevel != "line":
			# Navegación inteligente: las flechas van de elemento en elemento.
			self.moveByLevel(direction)
			return
		info = self.makeTextInfo(textinfo.POSITION_CARET)
		moved = info.move(unit, direction)
		if moved and unit == textinfo.UNIT_LINE and conf["browseMode"]["skipBlankLines"]:
			# Se saltan las líneas en blanco (#4904).
			for _i in range(500):
				line = info.copy()
				line.expand(textinfo.UNIT_LINE)
				if line.text.strip():
					break
				if not info.move(unit, direction):
					break
		if not moved:
			# Principio o final del documento con sonidos distintos (#4285, #13612).
			tones.playSound("boundaryStart" if direction < 0 else "boundaryEnd")
			if unit == textinfo.UNIT_LINE:
				self.speakLineAt(self.caret)
			return
		self._moveCaret(info.offsets[0], unit)

	def _moveToBoundary(self, which: str) -> None:
		buf = self.buffer
		if not buf:
			return
		if which == "lineStart":
			s, _e = buf.lineBounds(self.caret)
			self._moveCaret(s, textinfo.UNIT_CHARACTER)
		elif which == "lineEnd":
			_s, e = buf.lineBounds(self.caret)
			self._moveCaret(max(_s, e - 2 if buf.text[e - 1 : e] == "\n" else e - 1), textinfo.UNIT_CHARACTER)
		elif which == "docStart":
			self._moveCaret(0)
		elif which == "docEnd":
			s, _e = buf.lineBounds(max(0, len(buf.text) - 1))
			self._moveCaret(s)

	@script(gesture="kb:downArrow", description=_("Línea siguiente"), resumeSayAll=True)
	def script_nextLine(self, gesture) -> None:
		self._moveByUnit(textinfo.UNIT_LINE, 1)

	@script(gesture="kb:upArrow", description=_("Línea anterior"), resumeSayAll=True)
	def script_previousLine(self, gesture) -> None:
		self._moveByUnit(textinfo.UNIT_LINE, -1)

	@script(gesture="kb:rightArrow")
	def script_nextCharacter(self, gesture) -> None:
		self._moveByUnit(textinfo.UNIT_CHARACTER, 1)

	@script(gesture="kb:leftArrow")
	def script_previousCharacter(self, gesture) -> None:
		self._moveByUnit(textinfo.UNIT_CHARACTER, -1)

	@script(gesture="kb:control+rightArrow")
	def script_nextWord(self, gesture) -> None:
		self._moveByUnit(textinfo.UNIT_WORD, 1)

	@script(gesture="kb:control+leftArrow")
	def script_previousWord(self, gesture) -> None:
		self._moveByUnit(textinfo.UNIT_WORD, -1)

	@script(gesture="kb:control+downArrow", resumeSayAll=True)
	def script_nextParagraph(self, gesture) -> None:
		self._moveByParagraph(1)

	@script(gesture="kb:control+upArrow", resumeSayAll=True)
	def script_previousParagraph(self, gesture) -> None:
		self._moveByParagraph(-1)

	def _moveByParagraph(self, direction: int) -> None:
		"""Párrafo real (según el estilo de párrafo de «Navegación por documentos»)."""
		if not self.buffer:
			return
		self._moveByUnit(textinfo.UNIT_PARAGRAPH, direction)

	@staticmethod
	def _blockOf(node: Node | None) -> Node | None:
		from .buffer import INLINE_ROLES

		while node is not None and node.role in INLINE_ROLES:
			node = node.parent
		return node

	@script(gesture="kb:home")
	def script_startOfLine(self, gesture) -> None:
		self._moveToBoundary("lineStart")

	@script(gesture="kb:end")
	def script_endOfLine(self, gesture) -> None:
		self._moveToBoundary("lineEnd")

	@script(gesture="kb:control+home")
	def script_startOfDocument(self, gesture) -> None:
		self._moveToBoundary("docStart")

	@script(gesture="kb:control+end")
	def script_endOfDocument(self, gesture) -> None:
		self._moveToBoundary("docEnd")

	@script(gesture="kb:pageDown")
	def script_pageDown(self, gesture) -> None:
		info = self.makeTextInfo(textinfo.POSITION_CARET)
		if not info.move(textinfo.UNIT_LINE, conf["browseMode"]["linesPerPage"]):
			tones.playSound("boundaryEnd")
		self._moveCaret(info.offsets[0])

	@script(gesture="kb:pageUp")
	def script_pageUp(self, gesture) -> None:
		info = self.makeTextInfo(textinfo.POSITION_CARET)
		if not info.move(textinfo.UNIT_LINE, -conf["browseMode"]["linesPerPage"]):
			tones.playSound("boundaryStart")
		self._moveCaret(info.offsets[0])

	# --------------------------------------------------------- selección
	def _select(self, unit: str, direction: int) -> None:
		buf = self.buffer
		if not buf:
			return
		if self.selectionAnchor is None:
			self.selectionAnchor = self.caret
		info = self.makeTextInfo((self.caret, self.caret))
		if unit == "lineEnd":
			_s, e = buf.lineBounds(self.caret)
			newPos = e
		elif unit == "lineStart":
			newPos = buf.lineBounds(self.caret)[0]
		elif unit == "docEnd":
			newPos = len(buf.text)
		elif unit == "docStart":
			newPos = 0
		else:
			info.move(unit, direction)
			newPos = info.offsets[0]
		oldSel = self.selection
		self.caret = newPos
		newSel = self.selection
		old = self.makeTextInfo(oldSel)
		new = self.makeTextInfo(newSel)
		from .. import presentation

		speech.cancelSpeech()
		presentation.speakSelectionChange(old, new)
		self.syncNativeSelection()

	@script(gesture="kb:shift+rightArrow")
	def script_selectNextChar(self, gesture) -> None:
		self._select(textinfo.UNIT_CHARACTER, 1)

	@script(gesture="kb:shift+leftArrow")
	def script_selectPrevChar(self, gesture) -> None:
		self._select(textinfo.UNIT_CHARACTER, -1)

	@script(gesture="kb:shift+control+rightArrow")
	def script_selectNextWord(self, gesture) -> None:
		self._select(textinfo.UNIT_WORD, 1)

	@script(gesture="kb:shift+control+leftArrow")
	def script_selectPrevWord(self, gesture) -> None:
		self._select(textinfo.UNIT_WORD, -1)

	@script(gesture="kb:shift+downArrow")
	def script_selectNextLine(self, gesture) -> None:
		self._select(textinfo.UNIT_LINE, 1)

	@script(gesture="kb:shift+upArrow")
	def script_selectPrevLine(self, gesture) -> None:
		self._select(textinfo.UNIT_LINE, -1)

	@script(gesture="kb:shift+end")
	def script_selectToLineEnd(self, gesture) -> None:
		self._select("lineEnd", 1)

	@script(gesture="kb:shift+home")
	def script_selectToLineStart(self, gesture) -> None:
		self._select("lineStart", -1)

	@script(gesture="kb:shift+control+end")
	def script_selectToDocEnd(self, gesture) -> None:
		self._select("docEnd", 1)

	@script(gesture="kb:shift+control+home")
	def script_selectToDocStart(self, gesture) -> None:
		self._select("docStart", -1)

	@script(gesture="kb:control+a", description=_("Selecciona todo el documento"))
	def script_selectAll(self, gesture) -> None:
		if not self.buffer:
			return
		self.selectionAnchor = 0
		self.caret = len(self.buffer.text)
		speech.speakMessage(_("todo seleccionado"))
		self.syncNativeSelection()

	@script(gesture="kb:control+c", description=_("Copia el texto seleccionado"))
	def script_copySelection(self, gesture) -> None:
		s, e = self.selection
		if s == e or not self.buffer:
			gesture.send()
			return
		if self.syncNativeSelection():
			# Selección nativa: copia la aplicación (con su formato).
			gesture.send()
			speech.speakMessage(_("copiado"))
			return
		# Sin las líneas de entrada y salida de contenedores (#3997).
		api.copyToClip(self.buffer.plainText(s, e), notify=True)

	# --------------------------------------------------------- activación
	def activateAt(self, offset: int) -> None:
		buf = self.buffer
		if not buf:
			return
		if buf.boundaryAt(offset) is not None:
			# Línea de entrada o salida de un contenedor (#3997): no es parte de la página.
			speech.speakMessage(_("No se puede activar"))
			return
		node = buf.nodeAt(offset)
		if node is not None and node.role == Role.MATH:
			# Fórmula: Intro o Espacio empiezan a explorarla.
			from ..mathpres import browse_support, interaction

			mathMl = browse_support.mathMlForNode(buf, node)
			if mathMl:
				interaction.start(mathMl, self)
				return
		target = node
		while target is not None and target.parent is not None and not (target.role in ACTIVATABLE_ROLES or target.role in EDITABLE_ROLES or target.isFocusable or target.clickable):
			target = target.parent
		if target is None or target.parent is None:
			# Rev. 10.11 (M3): texto sin nada que activar. Antes se hacía clic con
			# el ratón en su centro (aunque estuviera fuera de la pantalla).
			if node is not None:
				speech.speakMessage(_("No se puede activar"))
			return
		obj = self.objectForNode(target)
		if obj is None:
			return
		if target.role in EDITABLE_ROLES and target.role not in (Role.LIST, Role.TREEVIEW) or target.role in (Role.LIST, Role.TREEVIEW) and target.isFocusable:
			obj.setFocus()
			self.passThrough = True
			return
		if target.isFocusable and target.role not in (Role.LINK, Role.BUTTON, Role.TOGGLEBUTTON, Role.CHECKBOX, Role.RADIOBUTTON):
			obj.setFocus()
		# El objeto puede acabar pulsándose con el ratón: primero se hace visible.
		self.scrollNodeIntoView(target)
		if not obj.doAction():
			# Respaldo: clic del ratón en el elemento.
			if not self.clickNode(target):
				speech.speakMessage(_("No se puede activar"))
				return
		self.afterActivate(target)
		if target.role in (Role.CHECKBOX, Role.TOGGLEBUTTON, Role.SWITCH, Role.RADIOBUTTON):
			queue_handler.callLater(150, self._reportToggled, target)

	def _reportToggled(self, node: Node) -> None:
		obj = self.objectForNode(node)
		if obj is None:
			return
		from .. import presentation

		presentation.speakObjectProperties(obj, states=True, reason=presentation.Reason.QUERY)
		# Se rehace solo el bloque del control para reflejar su nuevo estado.
		self.onStructureChanged(node.element)

	@script(gestures=("kb:enter", "kb:numpadEnter", "kb:space"), description=_("Activa el elemento en el cursor"))
	def script_activate(self, gesture) -> None:
		self.activateAt(self.caret)

	@script(gesture="kb:shift+f10", description=_("Abre el menú contextual del elemento"))
	def script_contextMenu(self, gesture) -> None:
		from .buffer import liveNodeRect

		node = self.buffer.nodeAt(self.caret) if self.buffer else None
		rect = liveNodeRect(node)
		if rect:
			x, y, w, h = rect
			from .. import mouse

			mouse.click(x + w // 2, y + h // 2, button="right")
		else:
			gesture.send()

	@script(gesture="kb:applications")
	def script_applicationsKey(self, gesture) -> None:
		self.script_contextMenu(gesture)

	# --------------------------------------------------------- modo foco
	@script(gesture="kb:tiresias+space", description=_("Alterna entre modo exploración y modo foco"), category=CAT)
	def script_toggleFocusMode(self, gesture) -> None:
		if not self.passThrough:
			node = self.buffer.nodeAt(self.caret) if self.buffer else None
			if node is not None and node.isFocusable:
				try:
					node.element.SetFocus()
				except comtypes.COMError:
					pass
		if self.passThrough and self.bufferKind in ("text", "lazyText"):
			# Word: el búfer se construye (o se pone al día tras escribir, A3) al
			# pedir el modo exploración.
			self.refreshTextBuffer()
		self.passThrough = not self.passThrough
		# Modo foco puesto a mano: queda fijado hasta volver a modo exploración.
		self._focusModeLocked = self.passThrough
		if not self.passThrough:
			# El usuario eligió el modo exploración: vuelve el paso automático.
			self._disableAutoPassThrough = False

	def refreshTextBuffer(self, syncCaret: bool = True) -> None:
		"""Documentos de texto (Word, Outlook...): construye o pone al día el búfer.

		Rev. 10.11 (A3): el búfer de texto no se rehacía nunca; tras escribir en
		Word y volver al modo exploración se leía el texto antiguo. Si el texto
		del documento no ha cambiado, la reconstrucción reutiliza el búfer actual
		(es barata). El cursor virtual va donde está el del sistema.
		"""
		if syncCaret or not self.isReady:
			self._syncCaretFromApp = True
			if self.isReady and self.buffer is not None and self.buffer.text:
				# Mientras llega el búfer nuevo, el cursor ya está en su sitio.
				self.caretFromApplication()
				self._syncCaretFromApp = True
		self.requestRebuild(initial=not self.isReady)

	@script(gesture="kb:escape", description=_("Sale del modo foco"), category=CAT)
	def script_exitFocusMode(self, gesture) -> None:
		if self.passThrough and getattr(self, "_disableAutoPassThrough", False):
			# Documento abierto en modo foco por la opción enableOnPageLoad:
			# Escape pertenece a la página (cerrar menús, diálogos...).
			gesture.send()
			return
		if self.passThrough and self.escapeBelongsToApplication():
			# Menús abiertos, listas desplegadas, celdas en edición: Escape es suyo.
			gesture.send()
			return
		if self.passThrough:
			self._focusModeLocked = False
			if self.bufferKind in ("text", "lazyText"):
				self.refreshTextBuffer()
			self.passThrough = False
			focus = api.getFocusObject()
			rid = getattr(focus, "runtimeId", None)
			if self.buffer and rid in self.buffer.byRid:
				self.caret = self.buffer.byRid[rid].start
		else:
			gesture.send()

	@script(gesture="kb:tiresias+shift+space", description=_("Activa o desactiva la navegación con una sola letra"), category=CAT)
	def script_toggleSingleLetterNav(self, gesture) -> None:
		value = not conf["browseMode"]["singleLetterNavigation"]
		conf["browseMode"]["singleLetterNavigation"] = value
		speech.speakMessage(_("navegación con una sola letra activada") if value else _("navegación con una sola letra desactivada"))

	@script(gesture="kb:tiresias+f5", description=_("Actualiza el contenido del documento"), category=CAT)
	def script_refreshBuffer(self, gesture) -> None:
		if not self.backgroundLoading:
			self._rebuild()
			speech.speakMessage(_("documento actualizado"))
			return
		# En segundo plano, como la primera carga: en una página grande la
		# reconstrucción tarda y no debe bloquear el núcleo. Se avisa al terminar.
		self._announceRefresh = True
		self.requestRebuild()

	def script_documentLoading(self, gesture) -> None:
		speech.speakMessage(_("cargando el documento"))

	# --------------------------------------------------------- navegación rápida
	def quickNav(self, key: str, direction: int) -> None:
		entry = next((q for q in QUICK_NAV if q[1] == key), None)
		if entry is None or self.buffer is None:
			return
		_k, _id, singular, plural, pred = entry
		if _id == "paragraph":
			# Párrafos marcados y párrafos de texto (opciones de «Navegación por documentos»).
			from .doc_navigation import paragraphPredicate

			pred = paragraphPredicate(self.buffer, pred)
		from .quicknav import dynamicPredicate

		pred = dynamicPredicate(self, _id, pred)
		caret = self.caret
		lineStart = self.buffer.lineBounds(caret)[0]
		nodes = []
		for n in self.buffer.iterNodes(pred, caret, direction):
			if direction < 0 and lineStart <= n.start and caret < n.end:
				# El elemento en el que está el cursor (empieza en esta línea): se
				# busca el anterior. Los anteriores de la misma línea (varios
				# enlaces seguidos con la distribución en pantalla) sí cuentan.
				continue
			nodes.append(n)
			break
		if not nodes and conf["browseMode"]["quickNavWrap"]:
			# Rev. 10.11 (M8): solo hasta el primero (o el último) que cumple; antes
			# se evaluaba el predicado en todo el documento (con los tipos de
			# estilo, miles de llamadas a la aplicación).
			edge = -1 if direction > 0 else len(self.buffer.text) + 1
			first = next(self.buffer.iterNodes(pred, edge, direction), None)
			if first is not None:
				tones.playSound("wrap")
				nodes = [first]
		if not nodes:
			msg = _("no hay más {what}") if direction > 0 else _("no hay {what} anteriores")
			speech.speakMessage(msg.format(what=plural))
			return
		target = nodes[0]
		self._moveCaret(target.start, node=target)
		if key == "math":
			from ..mathpres import browse_support, interaction

			if conf["math"]["browseMode"] != "interactive":
				return
			mathMl = browse_support.mathMlForNode(self.buffer, target)
			if mathMl:
				interaction.start(mathMl, self)

	@staticmethod
	def containerName(c: Node) -> str:
		"""Nombre corto del contenedor para «final de lista», «principio de navegación»..."""
		if c.role == Role.LANDMARK:
			return c.landmark or _("región")
		return roleLabel(c.role)

	def containerLastLine(self, c: Node) -> int:
		"""Principio de la última línea con texto del contenedor (su línea de salida, si la tiene)."""
		buf = self.buffer
		text = buf.text
		pos = min(buf.segmentEnd(c), len(text)) - 1
		while pos > c.start and not text[pos].strip():
			pos -= 1
		return buf.lineBounds(max(c.start, pos))[0]

	def nextContainerBoundary(self, toEnd: bool) -> None:
		"""Final o principio del contenedor más interno, sin salir de él (#15732).

		La primera pulsación lleva a la última (o a la primera) línea del
		contenedor; si ya se está allí, se avisa («final de lista») en lugar
		de saltar fuera, así no se pierde lo que hay entre medias ni se acaba
		en otro contenedor. Para salir está «Salta tras el final del contenedor».
		"""
		buf = self.buffer
		if not buf:
			return
		containers = buf.containersAt(self.caret)
		if not containers:
			speech.speakMessage(_("no se está dentro de un contenedor"))
			return
		c = containers[-1]
		lineStart = buf.lineBounds(self.caret)[0]
		what = self.containerName(c)
		if toEnd:
			target = self.containerLastLine(c)
			if lineStart >= target:
				speech.cancelSpeech()
				speech.speakMessage(_("final de {what}").format(what=what))
				return
			self._moveCaret(target)
		else:
			if lineStart <= c.start:
				speech.cancelSpeech()
				speech.speakMessage(_("principio de {what}").format(what=what))
				return
			self._moveCaret(c.start, node=c)

	def exitContainer(self) -> None:
		"""Salta a lo primero que hay después del contenedor más interno (#15732)."""
		buf = self.buffer
		if not buf:
			return
		containers = buf.containersAt(self.caret)
		if not containers:
			speech.speakMessage(_("no se está dentro de un contenedor"))
			return
		pos = buf.segmentEnd(containers[-1])
		while pos < len(buf.text) and not buf.text[pos].strip():
			pos += 1
		if pos >= len(buf.text):
			tones.playSound("boundaryEnd")
			speech.speakMessage(_("final del documento"))
			return
		self._moveCaret(buf.lineBounds(pos)[0])

	@script(gesture="kb:,", description=_("Va al final del contenedor (lista, tabla...) sin salir de él"), category=CAT)
	def script_quickNavContainerEnd(self, gesture) -> None:
		self.nextContainerBoundary(True)

	@script(gesture="kb:shift+,", description=_("Va al principio del contenedor"), category=CAT)
	def script_quickNavContainerStart(self, gesture) -> None:
		self.nextContainerBoundary(False)

	# #15732: el salto clásico fuera del contenedor, sin tecla (Gestos de entrada).
	@script(description=_("Salta tras el final del contenedor (lo primero que hay después de él)"), category=CAT)
	def script_quickNavContainerExit(self, gesture) -> None:
		self.exitContainer()

	@script(gesture="kb:n", description=_("Salta al texto que sigue a un bloque de enlaces"), category=CAT)
	def script_quickNavNotLinkBlock(self, gesture) -> None:
		self._notLinkBlock(1)

	@script(gesture="kb:shift+n", description=_("Salta al texto anterior a un bloque de enlaces"), category=CAT)
	def script_quickNavNotLinkBlockPrev(self, gesture) -> None:
		self._notLinkBlock(-1)

	def _notLinkBlock(self, direction: int) -> None:
		buf = self.buffer
		if not buf:
			return
		start, end = buf.lineBounds(self.caret)
		pos = end if direction > 0 else start - 1
		while 0 <= pos < len(buf.text):
			ls, le = buf.lineBounds(pos)
			chunks = buf.chunksInRange(ls, le)
			textChunks = [c for c in chunks if buf.text[c[0] : c[1]].strip()]
			if textChunks and not any(c[2].role == Role.LINK or any(a.role == Role.LINK for a in c[2].ancestors()) for c in textChunks):
				if sum(len(buf.text[c[0]:c[1]].strip()) for c in textChunks) > 20:
					self._moveCaret(ls)
					return
			pos = le if direction > 0 else ls - 1
		speech.speakMessage(_("no hay más texto fuera de enlaces"))

	# Tablas: tables.TableNavigationMixin. Búsqueda: extras.BrowseExtrasMixin.

	# --------------------------------------------------------- marcadores
	def _documentKey(self) -> str:
		"""Clave del documento para los marcadores (su dirección web o su título)."""
		cached = self.__dict__.get("_docKey")
		if cached:
			return cached
		try:
			url = self.rootObject._prop(uc.P_VALUEVALUE, "") or ""
		except Exception:
			url = ""
		key = str(url or self.rootObject.name or "documento")
		self.__dict__["_docKey"] = key
		return key

	def _rememberPosition(self) -> None:
		"""Guarda la posición del cursor de esta página con el texto de su línea (B4)."""
		key = self._documentKey()
		_savedPositions.pop(key, None)
		_savedPositions[key] = lineAnchor(self.buffer, self.caret) + (self.caret,)
		while len(_savedPositions) > MAX_SAVED_POSITIONS:
			_savedPositions.pop(next(iter(_savedPositions)))

	def _savedPosition(self) -> int | None:
		saved = _savedPositions.get(self._documentKey())
		if saved is None:
			return None
		if isinstance(saved, int):
			return saved if self.buffer is not None and saved < len(self.buffer.text) else None
		lineStart, text, caret = saved
		pos = resolveAnchor(self.buffer, lineStart, text)
		if pos is None:
			return None
		if pos == lineStart:
			# La misma línea en el mismo sitio: se vuelve al carácter exacto.
			return min(caret, len(self.buffer.text) - 1)
		return pos

	@staticmethod
	def _bookmarksFile() -> str:
		import os

		from .. import paths

		return os.path.join(paths.cacheDir(), "marcadores.json")

	def _loadBookmarks(self) -> dict:
		import json

		try:
			with open(self._bookmarksFile(), encoding="utf-8") as f:
				return json.load(f)
		except (OSError, ValueError):
			return {}

	def _saveBookmarks(self, data: dict) -> None:
		import json
		import os

		os.makedirs(os.path.dirname(self._bookmarksFile()), exist_ok=True)
		with open(self._bookmarksFile(), "w", encoding="utf-8") as f:
			json.dump(data, f, ensure_ascii=False)

	@script(gesture="kb:tiresias+'", description=_("Pone o quita un marcador en la posición actual del documento"), category=CAT)
	def script_toggleBookmark(self, gesture) -> None:
		data = self._loadBookmarks()
		key = self._documentKey()
		raw = list(data.get(key, []))
		lineStart, text = lineAnchor(self.buffer, self.caret)
		# Cada marcador guarda el texto de su línea para encontrarlo aunque la
		# página cambie (B4); los antiguos (solo el desplazamiento) siguen valiendo.
		resolved = [(m, self._resolveBookmark(m)) for m in raw]
		hit = [m for m, pos in resolved if pos == lineStart]
		if hit:
			raw = [m for m in raw if m not in hit]
			speech.speakMessage(_("marcador quitado"))
		else:
			raw.append({"o": lineStart, "t": text})
			speech.speakMessage(_("marcador puesto"))
		data[key] = raw
		self._saveBookmarks(data)

	def _resolveBookmark(self, mark) -> int | None:
		if isinstance(mark, dict):
			try:
				return resolveAnchor(self.buffer, int(mark.get("o", 0)), str(mark.get("t", "")))
			except (TypeError, ValueError):
				return None
		try:
			off = int(mark)
		except (TypeError, ValueError):
			return None
		return off if self.buffer is not None and off < len(self.buffer.text) else None

	def _moveToBookmark(self, direction: int) -> None:
		raw = self._loadBookmarks().get(self._documentKey(), [])
		marks = sorted({p for p in (self._resolveBookmark(m) for m in raw) if p is not None}) if self.buffer else []
		if not marks or not self.buffer:
			speech.speakMessage(_("no hay marcadores en este documento"))
			return
		lineStart = self.buffer.lineBounds(self.caret)[0]
		cands = [m for m in marks if (m > lineStart if direction > 0 else m < lineStart) and m < len(self.buffer.text)]
		if not cands:
			tones.playSound("wrap")
			cands = [marks[0] if direction > 0 else marks[-1]]
		target = cands[0] if direction > 0 else cands[-1]
		self._moveCaret(min(target, len(self.buffer.text) - 1))

	@script(gesture="kb:'", description=_("Va al marcador siguiente"), category=CAT)
	def script_quickNavNextBookmark(self, gesture) -> None:
		self._moveToBookmark(1)

	@script(gesture="kb:shift+'", description=_("Va al marcador anterior"), category=CAT)
	def script_quickNavPrevBookmark(self, gesture) -> None:
		self._moveToBookmark(-1)

	# --------------------------------------------------------- lista de elementos
	def getElements(self, kind: str) -> list[tuple[str, int, int]]:
		"""(etiqueta, desplazamiento, nivel) de los elementos de un tipo."""
		buf = self.buffer
		if not buf:
			return []
		quick = {q[1]: q[4] for q in QUICK_NAV}
		preds = {
			"link": lambda n: n.role == Role.LINK,
			"heading": lambda n: n.role in HEADING_ROLES,
			# Los mismos que las teclas F y B (las listas que no son controles,
			# como un <ul> normal, no son campos de formulario).
			"formField": quick["formField"],
			"button": quick["button"],
			"landmark": lambda n: n.role == Role.LANDMARK,
			"table": lambda n: n.role in (Role.TABLE, Role.DATAGRID) and not isLayoutTable(n),
			"graphic": lambda n: n.role == Role.GRAPHIC and bool(n.name),
			"clickable": lambda n: n.clickable,
			"tab": lambda n: n.role == Role.TAB,
			"figure": lambda n: n.role == Role.FIGURE,
			"article": lambda n: n.role == Role.ARTICLE,
			"annotation": quicknav.isAnnotation,
			"error": quicknav.isError,
			"frame": lambda n: n.role == Role.FRAME,
		}
		if kind == "prominent":
			return [(" ".join(buf.text[b.start : b.end].split())[:150], b.start, 0) for b in self.prominentBlocks()]
		pred = preds.get(kind)
		if pred is None:
			return []
		out = []
		for n in buf.nodes:
			if not pred(n) or n.end <= n.start and n.role != Role.LANDMARK:
				continue
			text = " ".join(buf.plainText(n.start, n.end).split())
			if n.role == Role.LANDMARK:
				label = " ".join(p for p in (n.name, n.landmark) if p)
			elif n.role in FORM_FIELD_ROLES:
				label = f"{text} {roleLabel(n.role)}".strip()
			else:
				label = text or n.name
			if len(label) > 150:
				label = label[:150] + "…"
			if n.role == Role.LANDMARK:
				# Regiones anidadas: el nivel es su profundidad entre regiones.
				level = 1 + sum(1 for a in n.ancestors() if a.role == Role.LANDMARK)
			else:
				level = n.headingLevel() if n.role in HEADING_ROLES else 0
			out.append((label, n.start, level))
		return out

	@script(gesture="kb:tiresias+f7", description=_("Lista de elementos: enlaces, encabezados, campos..."), category=CAT)
	def script_elementsList(self, gesture) -> None:
		from ..gui import browse_dialogs

		data = {k: self.getElements(k) for k, _label in browse_dialogs.ELEMENT_KINDS if k not in browse_dialogs.LAZY_KINDS}
		browse_dialogs.showElementsList(self, data, self.caret)

	def moveToOffsetFromGui(self, offset: int, activate: bool = False) -> None:
		"""Llamado desde la lista de elementos (en el hilo del núcleo)."""
		node = self.buffer.nodeAt(offset) if self.buffer else None
		self.pushPosition()
		self.caret = offset
		if activate:
			self.activateAt(offset)
		else:
			if node is not None:
				self.speakNode(node)
			self._afterCaretMove(node)

	# --------------------------------------------------------- eventos
	def event_gainFocus(self, obj: Any, nextHandler) -> None:
		if self._dirty and self.isReady:
			# Cambios que llegaron con el foco fuera del documento.
			self.applyPendingUpdates()
		elif self.isReady and self.bufferKind == "tree" and self.buffer is not None and self.buffer.layoutSignature and self.buffer.layoutSignature != self.layoutSignature():
			# Se cambiaron en Opciones la disposición o las líneas de contenedores
			# (#3997, #11073): se rehace al volver al documento.
			self.requestRebuild()
		buf = self.buffer
		if obj == self.rootObject:
			self.reportModeOnEnter()
			if self.lazyBuild and self.passThrough:
				# Word editable en modo foco: lo atiende el propio documento.
				nextHandler()
				return
			if not self.isReady and not self.lazyBuild:
				# Se anuncia cuando termine la carga en segundo plano.
				self._announceWhenReady = True
				if not self._building:
					self.requestRebuild(initial=True)
				return
			if not self._loadAnnounced:
				self._loadAnnounced = True
				self._announceLoad()
				return
			if not self.passThrough and self.bufferKind in ("text", "lazyText") and not self._building:
				# Rev. 10.11 (A3): al volver a un documento de texto (el panel de
				# lectura de Outlook con otro mensaje...) se comprueba si cambió.
				self.refreshTextBuffer()
			if not self.passThrough:
				speech.speakText(obj.name)
				return
			nextHandler()
			return
		rid = getattr(obj, "runtimeId", None)
		node = buf.byRid.get(rid) if (buf and rid) else None
		self.__dict__.pop("_pendingFocus", None)
		if node is None and buf is not None and self.isReady and self.bufferKind == "tree":
			# Rev. 10.11 (A1): contenido nuevo (un diálogo, otra vista de la
			# aplicación de una página). Cuando el búfer lo tenga, el cursor
			# virtual irá al foco en lugar de quedarse en la página de detrás.
			if rid:
				self._pendingFocus = (tuple(rid), time.monotonic())
			self.onStructureChanged(None)
		if node is not None:
			exits = self.landmarkExitSpeech(self.caret, node.start)
			if exits:
				speech.speakMessage(" ".join(exits))
			self.caret = node.start
			self.selectionAnchor = None
		if conf["browseMode"]["autoPassThroughOnFocusChange"] and not self._disableAutoPassThrough and not self._focusModeLocked:
			self._autoPassThroughForFocus(obj, node)
		# Se llega desde otro documento en otro modo: se indica el modo.
		self.reportModeOnEnter()
		nextHandler()

	#: Roles que siempre pasan a modo foco al recibir el foco (como NVDA).
	ALWAYS_PASS_THROUGH_ROLES = frozenset(
		{
			Role.COMBOBOX,
			Role.EDITABLETEXT,
			Role.PASSWORDEDIT,
			Role.LIST,
			Role.LISTITEM,
			Role.SLIDER,
			Role.TABCONTROL,
			Role.MENUBAR,
			Role.POPUPMENU,
			Role.TREEVIEW,
			Role.TREEVIEWITEM,
			Role.SPINBUTTON,
			Role.TABLEROW,
			Role.TABLECELL,
			Role.TABLEROWHEADER,
			Role.TABLECOLUMNHEADER,
		}
	)
	#: Roles que pasan a modo foco al recibir el foco (teclas propias: flechas).
	PASS_THROUGH_ON_FOCUS_ROLES = frozenset({Role.LISTITEM, Role.RADIOBUTTON, Role.TAB, Role.MENUITEM, Role.RADIOMENUITEM, Role.CHECKMENUITEM})
	#: Con el foco en ellos no se sale del modo foco.
	KEEP_PASS_THROUGH_ROLES = frozenset({Role.MENUITEM, Role.RADIOMENUITEM, Role.CHECKMENUITEM, Role.TABLECELL, Role.DATAITEM})
	#: Solo lectura pero interactivos: no impiden el modo foco.
	_READONLY_INTERACTIVE = frozenset({Role.EDITABLETEXT, Role.COMBOBOX, Role.TABLEROW, Role.TABLECELL, Role.TABLEROWHEADER, Role.TABLECOLUMNHEADER, Role.DATAITEM})

	def shouldPassThrough(self, obj: Any, node: Node | None = None) -> bool:
		"""¿El foco en ``obj`` pide modo foco? (``browseMode.shouldPassThrough`` de NVDA).

		Rev. 10.11 (A10): faltaban los botones de opción, las pestañas, los
		elementos de menú, las barras de herramientas, las filas y celdas de las
		cuadrículas y los contenedores editables que no son documentos.
		"""
		if node is not None and self.insideApplication(node):
			return True
		try:
			role = obj.role
			states = obj.states
		except Exception:
			return False
		if State.EDITABLE in states and State.UNAVAILABLE not in states:
			return True
		if role == Role.DOCUMENT:
			return False
		try:
			focusable = bool(obj.isFocusable)
		except Exception:
			focusable = True
		if not focusable and State.FOCUSED not in states and role != Role.POPUPMENU:
			return False
		if State.READONLY in states:
			if role == Role.LISTITEM:
				parent = node.parent if node is not None else getattr(obj, "parent", None)
				if parent is not None and getattr(parent, "role", None) in (Role.LIST, Role.TREEVIEW) and (getattr(parent, "isFocusable", False) or State.FOCUSABLE in getattr(parent, "states", ())):
					return True
			if role not in self._READONLY_INTERACTIVE:
				return False
		if role in self.ALWAYS_PASS_THROUGH_ROLES or role in self.PASS_THROUGH_ON_FOCUS_ROLES:
			return True
		if role == Role.DATAITEM:
			# Celdas y filas de una cuadrícula interactiva (role=grid o treegrid).
			chain = list(node.ancestors()) if node is not None else []
			if not chain or any(a.role in (Role.DATAGRID, Role.TABLE) and a.isFocusable for a in chain) or any(a.role == Role.TREEVIEW for a in chain):
				return True
		# Elementos de una barra de herramientas: las flechas son suyas.
		if node is not None:
			return any(a.role == Role.TOOLBAR for a in node.ancestors())
		parent = getattr(obj, "parent", None)
		for _i in range(8):
			if parent is None or parent == self.rootObject:
				break
			if getattr(parent, "role", None) == Role.TOOLBAR:
				return True
			parent = getattr(parent, "parent", None)
		return False

	def _autoPassThroughForFocus(self, obj: Any, node: Node | None) -> None:
		wantPass = self.shouldPassThrough(obj, node)
		if wantPass:
			if not self.passThrough:
				self.passThrough = True
			return
		if self.passThrough and getattr(obj, "role", None) not in self.KEEP_PASS_THROUGH_ROLES:
			# Rev. 10.11 (A10): el foco salió de un campo hacia contenido normal
			# (un div enfocable, un encabezado...): se vuelve al modo exploración.
			self.passThrough = False

	def _applyPendingFocus(self) -> None:
		"""Tras actualizar el búfer, el cursor va al foco que llegó antes que su contenido (A1)."""
		pending = self.__dict__.get("_pendingFocus")
		buf = self.buffer
		if not pending or buf is None:
			return
		rid, when = pending
		if time.monotonic() - when > 15:
			self.__dict__.pop("_pendingFocus", None)
			return
		focus = api.getFocusObject()
		focusRid = getattr(focus, "runtimeId", None) if focus is not None else None
		if focusRid is None or tuple(focusRid) != rid:
			# El foco ya se fue a otro sitio.
			self.__dict__.pop("_pendingFocus", None)
			return
		node = buf.byRid.get(rid)
		if node is None:
			if not self._building and not self._pendingElements and not self._fullRebuildPending:
				# Ni con el búfer al día está: el foco está en algo que el modo
				# exploración no muestra; se pasa a modo foco (como NVDA).
				self.__dict__.pop("_pendingFocus", None)
				if conf["browseMode"]["autoPassThroughOnFocusChange"] and not self._disableAutoPassThrough and not self._focusModeLocked and not self.passThrough:
					self.passThrough = True
			return
		self.__dict__.pop("_pendingFocus", None)
		self.caret = node.start
		self.selectionAnchor = None
		if conf["browseMode"]["autoPassThroughOnFocusChange"] and not self._disableAutoPassThrough and not self._focusModeLocked:
			self._autoPassThroughForFocus(focus, node)
		try:
			api.setReviewPosition(self.makeTextInfo(textinfo.POSITION_CARET), isCaret=True)
		except Exception:
			pass

	def _announceLoad(self) -> None:
		name = self.rootObject.name
		if name:
			speech.speakText(name)
		if self.passThrough:
			return
		if conf["browseMode"]["reportPageSummary"]:
			summary = self.pageSummary()
			if summary:
				speech.speakMessage(summary)
		saved = self._savedPosition() if conf["browseMode"]["rememberPositionPerPage"] else None
		start = self.flexStartNode() if saved is None else None
		if start is not None:
			# Web flexible: la lectura empieza donde el usuario fijó.
			saved = start.start
			if conf["browseMode"]["autoSayAllOnPageLoad"] and conf["browseMode"]["enableOnPageLoad"]:
				from ..speech import sayall

				self.caret = saved
				sayall.readText(sayall.CURSOR_CARET)
				return
		if saved is not None and self.buffer is not None and saved < len(self.buffer.text):
			# Página ya visitada: se vuelve donde se dejó.
			self.caret = saved
			self.speakLineAt(self.caret)
		elif conf["browseMode"]["autoSayAllOnPageLoad"] and conf["browseMode"]["enableOnPageLoad"] and self.bufferKind == "tree":
			from ..speech import sayall

			self.caret = 0
			sayall.readText(sayall.CURSOR_CARET)
		else:
			self.speakLineAt(self.caret)

	def event_documentLoadComplete(self, obj: Any, nextHandler) -> None:
		if obj == self.rootObject and not self.lazyBuild:
			self.requestRebuild()
		nextHandler()


def _makeQuickNavScripts() -> None:
	for key, ident, singular, _plural, _pred in QUICK_NAV:
		capIdent = ident[0].upper() + ident[1:]

		def nextScript(self, gesture, _i=ident):
			self.quickNav(_i, 1)

		def prevScript(self, gesture, _i=ident):
			self.quickNav(_i, -1)

		nextName = f"script_quickNavNext{capIdent}"
		prevName = f"script_quickNavPrev{capIdent}"
		nextScript.__name__ = nextName
		prevScript.__name__ = prevName
		# Sin tecla: la orden existe pero se asigna en «Gestos de entrada».
		# «Siguiente tabla», «Encabezado anterior»: sin artículo, para que concuerde
		# con cualquier género («Va al agrupación» no lo hacía).
		nextScript = script(description=_("Siguiente {what}").format(what=singular), category=CAT, gesture=f"kb:{key}" if key else None)(nextScript)
		prevScript = script(description=(_("{what} anterior").format(what=singular))[:1].upper() + _("{what} anterior").format(what=singular)[1:], category=CAT, gesture=f"kb:shift+{key}" if key else None)(prevScript)
		setattr(BrowseModeDocument, nextName, nextScript)
		setattr(BrowseModeDocument, prevName, prevScript)
		if key:
			BrowseModeDocument._classGestures[f"kb:{key}"] = nextName[7:]  # type: ignore[attr-defined]
			BrowseModeDocument._classGestures[f"kb:shift+{key}"] = prevName[7:]  # type: ignore[attr-defined]


_makeQuickNavScripts()


def _onMouseClick(x: int, y: int) -> None:
	"""Un clic dentro de un documento en modo exploración mueve su cursor (#4896)."""
	focus = api.getFocusObject()
	ti = getattr(focus, "treeInterceptor", None) if focus is not None else None
	if isinstance(ti, BrowseModeDocument) and ti.isReady:
		try:
			ti.onMouseClick(x, y)
		except Exception:
			log.debug("Error moviendo el cursor con el ratón", exc_info=True)


def _registerMouse() -> None:
	from ..input import core as inputCore

	inputCore.post_mouseClick.register(_onMouseClick)


_registerMouse()


def _rebuildChangedLayouts() -> None:
	"""Rehace los documentos cuyo búfer se hizo con otras opciones de presentación.

	Cambiar en Opciones la disposición en pantalla, las líneas de contenedores
	(#3997) o el salto tras los enlaces (#11073) se nota al momento.
	"""
	from .. import tree_interceptor

	sig = BrowseModeDocument.layoutSignature()
	for ti in list(tree_interceptor.runningTable):
		if not isinstance(ti, BrowseModeDocument) or ti.bufferKind != "tree" or not ti.isReady:
			continue
		buf = ti.buffer
		if buf is not None and buf.layoutSignature and buf.layoutSignature != sig:
			ti.requestRebuild()


def _onConfigChanged(*args, **kwargs) -> None:
	queue_handler.queueFunction(_rebuildChangedLayouts)


def _registerConfigHandlers() -> None:
	from ..config import post_configProfileSwitch, post_configSave

	for action in (post_configSave, post_configProfileSwitch):
		action.register(_onConfigChanged)


_registerConfigHandlers()
