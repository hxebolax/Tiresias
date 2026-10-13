"""Órdenes y comportamientos ampliados del modo exploración.

Se mezcla con :class:`~tiresias.browse.document.BrowseModeDocument`:

- frases (Alt+flechas, cedidas a los cuadros combinados), selección por
  párrafo y por página, modo de selección nativa;
- Tab desde el cursor virtual, saltos a anclas, clic del ratón que mueve el
  cursor (#4896), activación con clic de respaldo;
- detalles, flujo (aria-flowto, #4049) y aria-controls (#8983) navegables,
  con pila de posiciones para volver;
- búsqueda con historial, mayúsculas, palabra completa, expresiones
  regulares y oferta de volver al principio (#4637, #16426, #18422);
- regiones vivas cortés/asertiva (#17662, #14990), cambios de aria-sort
  (#10890), diálogos que no se leen dos veces (#8971), salida de regiones al
  mover el foco (#10420);
- dirección de la página, inspector de atributos, distribución en pantalla,
  niveles de navegación (navegación inteligente), lectura rápida, vistazo y
  web flexible.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import comtypes

from .. import api, queue_handler, speech, textinfo
from ..a11y import uia_client as uc
from ..audio import tones
from ..baseobject import ScriptableObject, script
from ..config import conf
from ..i18n import _
from ..log import getLogger
from ..objects.roles import HEADING_ROLES, Role, State, roleLabel
from . import aria as ariaSem
from . import html_details
from .buffer import ATOMIC_ROLES, Node

log = getLogger("browseExtras")

CAT = _("Modo exploración")

#: Historial de búsqueda (compartido por todos los documentos).
_findHistory: list[str] = []
_findOptions = {"caseSensitive": False, "wholeWord": False, "regex": False}
FIND_HISTORY_SIZE = 20
#: Último modo anunciado (para anunciarlo al entrar en otro documento).
_lastModeReported: bool | None = None
#: Niveles de navegación con flechas (navegación inteligente).
NAV_LEVELS = ("line", "object", "control")
NAV_LEVEL_LABELS = {"line": _("navegación por líneas"), "object": _("navegación por elementos"), "control": _("navegación por controles")}

#: Roles con contenido emergente que se abre con Alt+flecha abajo.
_POPUP_ROLES = {Role.COMBOBOX, Role.DROPDOWNBUTTON, Role.SPLITBUTTON, Role.MENUBUTTON}
#: Roles dentro de los que el foco pasa a modo foco automáticamente.
APPLICATION_ROLES = {Role.APPLICATION}


def _repeat() -> int:
	from ..input import core as inputCore

	try:
		return inputCore.getLastScriptRepeatCount()
	except Exception:
		return 0


def _historyFile() -> str:
	from .. import paths

	return os.path.join(paths.cacheDir(), "busquedas.json")


def _loadFindHistory() -> None:
	if _findHistory:
		return
	try:
		with open(_historyFile(), encoding="utf-8") as f:
			data = json.load(f)
		if isinstance(data, list):
			_findHistory.extend(str(x) for x in data[:FIND_HISTORY_SIZE])
	except (OSError, ValueError):
		pass


def addFindHistory(text: str) -> None:
	if not text:
		return
	if text in _findHistory:
		_findHistory.remove(text)
	_findHistory.insert(0, text)
	del _findHistory[FIND_HISTORY_SIZE:]
	try:
		os.makedirs(os.path.dirname(_historyFile()), exist_ok=True)
		with open(_historyFile(), "w", encoding="utf-8") as f:
			json.dump(_findHistory, f, ensure_ascii=False)
	except OSError:
		log.debug("No se pudo guardar el historial de búsqueda", exc_info=True)


#: Sin versión anterior de una región viva, más texto que esto se recorta a lo último.
LIVE_REGION_FIRST_LIMIT = 400


def liveRegionLines(element: Any) -> list[str]:
	"""Líneas de texto de una región viva (construye su subárbol; fuera del núcleo)."""
	from .buffer import VirtualBuffer

	if element is None:
		return []
	try:
		sub = VirtualBuffer(element)
		sub.build()
	except (comtypes.COMError, AttributeError, ValueError):
		return []
	return [ln.strip() for ln in sub.plainText(0, len(sub.text)).split("\n") if ln.strip()]


class _LiveRegionWorker:
	"""Hilo único que construye las regiones vivas en orden (rev. 10.11, A2)."""

	def __init__(self) -> None:
		import queue
		import threading

		self.jobs: Any = queue.Queue()
		self.thread = threading.Thread(target=self._run, name="browseLiveRegions", daemon=True)
		self.thread.start()

	def submit(self, job: tuple) -> None:
		self.jobs.put(job)

	def _run(self) -> None:
		try:
			comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
		except OSError:
			pass
		while True:
			job = self.jobs.get()
			doc, element, rid, old, live, atomic, fallback, inBuffer = job
			try:
				lines = liveRegionLines(element)
			except Exception:
				log.debug("No se pudo leer la región viva", exc_info=True)
				lines = []
			queue_handler.queueFunction(doc._onLiveRegionText, element, rid, lines, old, live, atomic, fallback, inBuffer)


_liveWorkerInstance: _LiveRegionWorker | None = None


def _liveWorker() -> _LiveRegionWorker:
	global _liveWorkerInstance
	if _liveWorkerInstance is None:
		_liveWorkerInstance = _LiveRegionWorker()
	return _liveWorkerInstance


def findPattern(text: str, caseSensitive: bool, wholeWord: bool, regex: bool) -> re.Pattern | None:
	"""Expresión para buscar ``text`` con las opciones dadas (``None`` si no es válida)."""
	pattern = text if regex else re.escape(text)
	if wholeWord:
		pattern = rf"(?<!\w)(?:{pattern})(?!\w)"
	try:
		return re.compile(pattern, 0 if caseSensitive else re.IGNORECASE)
	except re.error:
		return None


class BrowseExtrasMixin(ScriptableObject):
	"""Ampliaciones de :class:`BrowseModeDocument`."""

	def _extrasInit(self) -> None:
		self.navLevel = "line"
		self._positionStack: list[int] = []
		self._lastDialogAnnounced: tuple[tuple, float] = ((), 0.0)
		self._lastLiveText: tuple[str, float] = ("", 0.0)

	# ================================================================ voz ampliada
	def extraPrefix(self, node: Node) -> list[str]:
		"""Información ARIA que se dice al entrar en un elemento."""
		out: list[str] = []
		df = conf["documentFormatting"]
		if node.role == Role.LINK and self.buffer is not None and df["reportLinks"] and df["reportLinkType"]:
			# «en esta página» lo añade el prefijo del enlace; aquí, los externos.
			if ariaSem.linkType(node.url, self.documentUrl()) == ariaSem.LINK_EXTERNAL:
				out.append(_("externo"))
		if node.semantic:
			out.append(node.semantic)
		if node.role == Role.LIST and self._isDefinitionList(node):
			terms = sum(1 for c in node.children if c.lct in ariaSem.TERM_LCT or c.ariaRole == "term")
			out.append(_("lista de definiciones con {n} términos").format(n=terms))
		if node.role in (Role.TABLECOLUMNHEADER, Role.TABLEROWHEADER, Role.HEADERITEM):
			sort = ariaSem.sortLabel(node.aria.get("sort") or node.itemStatus)
			if sort:
				out.append(sort)
		cur = ariaSem.currentLabel(node.aria.get("current"))
		if cur and node.role not in ATOMIC_ROLES:
			out.append(cur)
		if df.get("reportDetails", True):
			if node.relations.get("details"):
				out.append(_("tiene detalles"))
			if node.relations.get("flowTo"):
				out.append(_("con continuación"))
		# aria-describedby de grupos y regiones (#12718, foros 1.20).
		desc = html_details.containerDescription(self.buffer, node)
		if desc:
			out.append(desc)
		return out

	def extraSuffix(self, node: Node) -> list[str]:
		"""Información ARIA que se dice tras un control."""
		out: list[str] = []
		if node.role in ATOMIC_ROLES:
			popup = ariaSem.haspopupLabel(node.aria.get("haspopup"))
			if popup and node.role != Role.COMBOBOX:
				out.append(popup)
			cur = ariaSem.currentLabel(node.aria.get("current"))
			if cur:
				out.append(cur)
		orient = ariaSem.orientationLabel(node.role, node.orientation)
		if orient:
			out.append(orient)
		if node.role == Role.GRAPHIC and node.description and node.description != node.name:
			# Descripción larga (aria-describedby) de las imágenes.
			out.append(node.description)
		return out

	def wantsPrefix(self, node: Node) -> bool:
		"""¿El nodo tiene información ARIA que se dice al entrar?"""
		return bool(
			node.semantic
			or (node.role == Role.LINK and node.url)
			or (node.role == Role.LIST and self._isDefinitionList(node))
			or node.relations.get("details")
			or node.relations.get("flowTo")
			or ariaSem.currentLabel(node.aria.get("current"))
			or (node.role in (Role.TABLECOLUMNHEADER, Role.TABLEROWHEADER, Role.HEADERITEM) and ariaSem.sortLabel(node.aria.get("sort") or node.itemStatus))
			or (node.description and node.role in html_details.DESCRIBED_CONTAINER_ROLES and html_details.containerDescription(self.buffer, node))
		)

	@staticmethod
	def _isDefinitionList(node: Node) -> bool:
		return node.role == Role.LIST and any(c.ariaRole in ("definition", "term") or c.lct in ariaSem.DEFINITION_LCT | ariaSem.TERM_LCT for c in node.children)

	def documentUrl(self) -> str:
		cached = self.__dict__.get("_docUrl")
		if cached is not None:
			return cached
		try:
			url = str(self.rootObject._prop(uc.P_VALUEVALUE, "") or "")
		except Exception:
			url = ""
		self.__dict__["_docUrl"] = url
		return url

	# ================================================================ modo foco
	def escapeBelongsToApplication(self) -> bool:
		"""¿Escape debe llegar a la aplicación (menú abierto, lista desplegada...)?"""
		focus = api.getFocusObject()
		if focus is None:
			return False
		try:
			role = focus.role
			states = focus.states
		except Exception:
			return False
		if role in (Role.MENUITEM, Role.CHECKMENUITEM, Role.RADIOMENUITEM, Role.POPUPMENU, Role.MENUBAR):
			return True
		if State.EXPANDED in states and role in (Role.COMBOBOX, Role.BUTTON, Role.MENUBUTTON, Role.DROPDOWNBUTTON, Role.SPLITBUTTON, Role.EDITABLETEXT):
			return True
		try:
			parent = focus.parent
			if role in (Role.LISTITEM, Role.TREEVIEWITEM) and parent is not None and parent.role in (Role.LIST, Role.TREEVIEW):
				gp = parent.parent
				if gp is not None and gp.role == Role.COMBOBOX:
					return True
		except Exception:
			pass
		return False

	def onPassThroughChanged(self, state: bool) -> None:
		"""Documentos de texto (Word): el cursor del sistema sigue al virtual al pasar a modo foco."""
		if state and self.bufferKind in ("text", "lazyText") and self.isReady:
			self.caretToApplication()

	def caretToApplication(self) -> bool:
		from . import style

		r = style.rangeAt(self, self.caret) if self.buffer is not None and self.buffer.text else None
		if r is None:
			return False
		try:
			r.MoveEndpointByRange(uc.EP_END, r, uc.EP_START)
			r.Select()
			return True
		except comtypes.COMError:
			return False

	def caretFromApplication(self) -> bool:
		"""El cursor virtual va donde está el cursor del sistema (documentos de texto)."""
		buf = self.buffer
		offsetOf = getattr(buf, "offsetOfRange", None)
		if offsetOf is None:
			return False
		from . import style

		pat = style.textPattern(self)
		if pat is None:
			return False
		try:
			sel = pat.GetSelection()
			if not sel or sel.Length == 0:
				return False
			off = offsetOf(sel.GetElement(0))
		except comtypes.COMError:
			return False
		if off is None:
			return False
		self.caret = max(0, min(off, len(buf.text) - 1))
		self.selectionAnchor = None
		return True

	# ================================================================ frases
	def _caretNode(self) -> Node | None:
		return self.buffer.nodeAt(self.caret) if self.buffer else None

	def _popupControlAtCaret(self) -> Node | None:
		node = self._caretNode()
		while node is not None:
			if node.role in _POPUP_ROLES or (node.isFocusable and (State.COLLAPSED in node.states or State.EXPANDED in node.states) and node.aria.get("haspopup") not in (None, "", "false")):
				return node
			if node.role not in (Role.STATICTEXT, Role.GRAPHIC):
				break
			node = node.parent
		return None

	def _altArrow(self, gesture, direction: int) -> None:
		target = self._popupControlAtCaret()
		if target is not None and target.element is not None:
			# Alt+flechas abren y cierran los cuadros combinados: se ceden.
			try:
				target.element.SetFocus()
			except comtypes.COMError:
				pass
			queue_handler.callLater(60, gesture.send)
			queue_handler.callLater(400, self._reportToggled, target)
			return
		self._moveByUnit(textinfo.UNIT_SENTENCE, direction)

	@script(gesture="kb:alt+downArrow", description=_("Frase siguiente (en un cuadro combinado, lo abre)"), category=CAT, resumeSayAll=True)
	def script_nextSentence(self, gesture) -> None:
		self._altArrow(gesture, 1)

	@script(gesture="kb:alt+upArrow", description=_("Frase anterior (en un cuadro combinado, lo cierra)"), category=CAT, resumeSayAll=True)
	def script_previousSentence(self, gesture) -> None:
		self._altArrow(gesture, -1)

	# ================================================================ selección
	@script(gesture="kb:shift+control+downArrow", description=_("Selecciona hasta el final del párrafo"), category=CAT)
	def script_selectNextParagraph(self, gesture) -> None:
		self._select(textinfo.UNIT_PARAGRAPH, 1)

	@script(gesture="kb:shift+control+upArrow", description=_("Selecciona hasta el principio del párrafo"), category=CAT)
	def script_selectPrevParagraph(self, gesture) -> None:
		self._select(textinfo.UNIT_PARAGRAPH, -1)

	@script(gesture="kb:shift+pageDown", description=_("Selecciona una página hacia abajo"), category=CAT)
	def script_selectNextPage(self, gesture) -> None:
		self._select(textinfo.UNIT_LINE, conf["browseMode"]["linesPerPage"])

	@script(gesture="kb:shift+pageUp", description=_("Selecciona una página hacia arriba"), category=CAT)
	def script_selectPrevPage(self, gesture) -> None:
		self._select(textinfo.UNIT_LINE, -conf["browseMode"]["linesPerPage"])

	def syncNativeSelection(self) -> bool:
		"""Refleja la selección del modo exploración en el documento (selección nativa)."""
		if not conf["browseMode"]["nativeSelectionMode"] or self.buffer is None:
			return False
		from . import style

		s, e = self.selection
		try:
			if s == e:
				return False
			r = style.rangeAt(self, s)
			# Las líneas de contenedores (#3997) no existen en la página.
			last = style.rangeAt(self, max(s, self.buffer.contentOffset(e - 1, -1)))
			if r is None or last is None:
				return False
			r.MoveEndpointByRange(uc.EP_END, last, uc.EP_END)
			r.Select()
			return True
		except (comtypes.COMError, ValueError, AttributeError):
			log.debug("No se pudo aplicar la selección nativa", exc_info=True)
			return False

	@script(gesture="kb:tiresias+shift+f10", description=_("Activa o desactiva el modo de selección nativa (la selección se aplica al documento)"), category=CAT)
	def script_toggleNativeSelectionMode(self, gesture) -> None:
		value = not conf["browseMode"]["nativeSelectionMode"]
		conf["browseMode"]["nativeSelectionMode"] = value
		speech.speakMessage(_("modo de selección nativa activado") if value else _("modo de selección nativa desactivado"))
		if value:
			self.syncNativeSelection()

	# ================================================================ Tab desde el cursor
	def _tabFromCaret(self, gesture, direction: int) -> None:
		buf = self.buffer
		if buf is None:
			gesture.send()
			return
		focus = api.getFocusObject()
		rid = getattr(focus, "runtimeId", None)
		focusNode = buf.byRid.get(rid) if rid else None
		caret = self.caret
		if focusNode is not None and focusNode.start <= caret < max(focusNode.end, focusNode.start + 1):
			gesture.send()
			return
		if focusNode is None and focus is not None and focus != self.rootObject and not self.contains(focus):
			gesture.send()
			return

		def pred(n: Node) -> bool:
			return n.isFocusable and State.UNAVAILABLE not in n.states and n.role not in (Role.DOCUMENT, Role.FRAME) and n is not focusNode

		node = buf.nodeAt(caret)
		ref = node.start if (node is not None and direction < 0) else caret
		if direction > 0 and node is not None and node.isFocusable and node is not focusNode and node.start <= caret:
			target = node
		else:
			target = next(buf.iterNodes(pred, ref if direction < 0 else caret, direction), None)
		if target is None or target.element is None:
			gesture.send()
			return
		try:
			target.element.SetFocus()
		except comtypes.COMError:
			gesture.send()

	@script(gesture="kb:tab", description=_("Va al siguiente elemento enfocable desde el cursor virtual"), category=CAT)
	def script_tab(self, gesture) -> None:
		self._tabFromCaret(gesture, 1)

	@script(gesture="kb:shift+tab", description=_("Va al elemento enfocable anterior desde el cursor virtual"), category=CAT)
	def script_shiftTab(self, gesture) -> None:
		self._tabFromCaret(gesture, -1)

	# ================================================================ activación
	def scrollNodeIntoView(self, node: Node | None) -> None:
		"""Desplaza la página hasta el elemento (antes de pulsarlo con el ratón)."""
		if node is None or node.element is None:
			return
		try:
			pat = node.element.GetCurrentPattern(uc.PAT_SCROLLITEM)
			if pat:
				pat.QueryInterface(uc.UIA.IUIAutomationScrollItemPattern).ScrollIntoView()
		except (comtypes.COMError, ValueError, AttributeError):
			pass

	def clickNode(self, node: Node) -> bool:
		"""Clic del ratón en el centro del elemento (respaldo al activar).

		Rev. 10.11 (M3): con la posición actual del elemento (la guardada al
		construir el búfer queda desfasada al desplazar la página).
		"""
		from .buffer import liveNodeRect

		self.scrollNodeIntoView(node)
		rect = liveNodeRect(node)
		if not rect:
			return False
		x, y, w, h = rect
		if w <= 0 or h <= 0:
			return False
		from .. import mouse

		mouse.click(x + w // 2, y + h // 2)
		return True

	def afterActivate(self, node: Node) -> None:
		"""Tras activar un enlace a un ancla de esta página, el cursor va al destino."""
		if node.role != Role.LINK or not conf["browseMode"]["followAnchors"]:
			return
		if ariaSem.linkType(node.url, self.documentUrl()) != ariaSem.LINK_SAME_PAGE:
			return
		frag = ariaSem.fragmentOf(node.url)
		if frag:
			queue_handler.callLater(250, self.moveToAnchor, frag)

	def moveToAnchor(self, frag: str) -> bool:
		buf = self.buffer
		if buf is None:
			return False
		from urllib.parse import unquote

		frag = unquote(frag)
		target = next((n for n in buf.nodes if n.automationId == frag), None)
		if target is None:
			return False
		if target.end <= target.start:
			nxt = next((n for n in buf.nodes if n.start >= target.start and n.end > n.start), None)
			if nxt is None:
				return False
			target = nxt
		self.pushPosition()
		self._moveCaret(target.start, node=target)
		return True

	# ================================================================ relaciones y pila de posiciones
	def pushPosition(self) -> None:
		self._positionStack.append(self.caret)
		del self._positionStack[:-30]

	@script(gesture="kb:tiresias+alt+backspace", description=_("Vuelve a la posición anterior a un salto (ancla, detalles, flujo...)"), category=CAT)
	def script_popPosition(self, gesture) -> None:
		if not self._positionStack or self.buffer is None:
			speech.speakMessage(_("no hay posiciones anteriores"))
			return
		pos = self._positionStack.pop()
		self._moveCaret(min(pos, max(0, len(self.buffer.text) - 1)))

	def _relationTarget(self, kind: str | None = None) -> tuple[str, Node] | None:
		buf = self.buffer
		node = self._caretNode()
		kinds = (kind,) if kind else ("details", "flowTo", "controls", "describedBy")
		while node is not None:
			for k in kinds:
				for i, rid in enumerate(node.relations.get(k, ())):
					target = buf.byRid.get(rid)
					if target is None:
						els = node.relationElements.get(k) or []
						target = self._nodeInsideElement(els[i]) if i < len(els) else None
					if target is not None and target.end > target.start:
						return k, target
			node = node.parent
		return None

	def _nodeInsideElement(self, element) -> Node | None:
		"""Primer nodo del búfer dentro de un elemento que no está en el búfer.

		Los ``<p>`` sin semántica no están en la vista de control de UIA, pero
		su texto sí está en el búfer.
		"""
		buf = self.buffer
		walker = uc.rawWalker
		queue = [element]
		guard = 0
		try:
			while queue and guard < 200:
				guard += 1
				el = queue.pop(0)
				node = buf.byRid.get(uc.runtimeIdOf(el))
				if node is not None:
					return node
				child = walker.GetFirstChildElement(el)
				kids = []
				while child and len(kids) < 50:
					kids.append(child)
					child = walker.GetNextSiblingElement(child)
				queue[0:0] = kids
		except (comtypes.COMError, ValueError):
			return None
		return None

	@script(gesture="kb:tiresias+shift+j", description=_("Salta al elemento relacionado: detalles, continuación del flujo o elemento controlado"), category=CAT)
	def script_jumpToRelated(self, gesture) -> None:
		found = self._relationTarget()
		if found is None:
			speech.speakMessage(_("sin elementos relacionados"))
			return
		kind, target = found
		labels = {"details": _("detalles"), "flowTo": _("continuación"), "controls": _("elemento controlado"), "describedBy": _("descripción")}
		self.pushPosition()
		speech.cancelSpeech()
		speech.speakMessage(labels[kind])
		self.caret = target.start
		self.selectionAnchor = None
		self.speakNode(target)
		self._afterCaretMove(target)

	@script(description=_("Muestra la descripción larga del elemento en el cursor"), category=CAT)
	def script_showLongDescription(self, gesture) -> None:
		node = self._caretNode()
		texts: list[str] = []
		while node is not None and not texts:
			for rid in node.relations.get("describedBy", ()):
				t = self.buffer.byRid.get(rid)
				if t is not None:
					texts.append(" ".join(self.buffer.text[t.start : t.end].split()))
			if not texts and node.description and node.description != node.name:
				texts.append(node.description)
			node = node.parent
		if not texts:
			speech.speakMessage(_("sin descripción larga"))
			return
		from .. import gui

		gui.showBrowseableMessage("\n\n".join(texts), _("Descripción larga"))

	# ================================================================ información de la página
	@script(gesture="kb:tiresias+shift+u", description=_("Anuncia la dirección de la página (dos veces: la copia)"), category=CAT, speakOnDemand=True)
	def script_reportUrl(self, gesture) -> None:
		url = self.documentUrl() or self._documentKey()
		if not url:
			speech.speakMessage(_("sin dirección"))
			return
		if _repeat() >= 1:
			api.copyToClip(url, notify=True)
		else:
			speech.speakText(url)

	def inspectorText(self, node: Node) -> str:
		lines = []
		chain = [node] + list(node.ancestors())
		for depth, n in enumerate(chain[:6]):
			title = _("Elemento") if depth == 0 else _("Antecesor {n}").format(n=depth)
			lines.append(f"== {title} ==")
			lines.append(_("Rol: {role} ({name})").format(role=roleLabel(n.role), name=n.role.name))
			for label, value in (
				(_("Nombre"), n.name),
				(_("Rol ARIA"), n.ariaRole),
				(_("Tipo localizado"), n.lct),
				(_("Valor"), n.value),
				(_("Dirección"), n.url),
				(_("Descripción"), n.description),
				(_("Punto de referencia"), n.landmark),
				(_("Identificador"), n.automationId),
				(_("Clase"), n.className),
				(_("Idioma"), n.culture or ""),
				(_("Estado del elemento"), n.itemStatus),
			):
				if value:
					lines.append(f"{label}: {value}")
			if n.states:
				lines.append(_("Estados: {s}").format(s=", ".join(sorted(s.name for s in n.states))))
			if n.aria:
				lines.append(_("Propiedades ARIA: {p}").format(p="; ".join(f"{k}={v}" for k, v in sorted(n.aria.items()))))
			if n.level:
				lines.append(_("Nivel: {n}").format(n=n.level))
			if n.rowCol:
				lines.append(_("Celda: fila {r}, columna {c} (abarca {rs}×{cs})").format(r=n.rowCol[0], c=n.rowCol[1], rs=n.rowSpan, cs=n.colSpan))
			if n.tableSize:
				lines.append(_("Tabla: {r} filas, {c} columnas").format(r=n.tableSize[0], c=n.tableSize[1]))
			if n.orientation:
				lines.append(_("Orientación: {o}").format(o=_("vertical") if n.orientation == 2 else _("horizontal")))
			if n.live:
				lines.append(_("Región viva: {l}").format(l=_("asertiva") if n.live == 2 else _("cortés")))
			for k, rids in n.relations.items():
				lines.append(f"{k}: {len(rids)}")
			if n.location:
				lines.append(_("Posición: x={0} y={1} ancho={2} alto={3}").format(*n.location))
			lines.append(_("Texto en el búfer: {s}-{e}").format(s=n.start, e=n.end))
			lines.append("")
		return "\n".join(lines)

	@script(gesture="kb:tiresias+shift+f1", description=_("Muestra todos los atributos del elemento en el cursor (inspector)"), category=CAT)
	def script_inspectElement(self, gesture) -> None:
		node = self._caretNode()
		if node is None:
			speech.speakMessage(_("sin elemento"))
			return
		from .. import gui

		gui.showBrowseableMessage(self.inspectorText(node), _("Atributos del elemento"))

	@script(gesture="kb:tiresias+v", description=_("Activa o desactiva la distribución en pantalla (varios elementos en la misma línea)"), category=CAT)
	def script_toggleScreenLayout(self, gesture) -> None:
		value = not conf["browseMode"]["useScreenLayout"]
		conf["browseMode"]["useScreenLayout"] = value
		speech.speakMessage(_("distribución en pantalla activada") if value else _("distribución en pantalla desactivada"))
		self.requestRebuild()

	def pageSummary(self) -> str:
		buf = self.buffer
		if buf is None:
			return ""
		nodes = [n for n in buf.nodes if n.end > n.start]
		headings = sum(1 for n in nodes if n.role in HEADING_ROLES)
		links = sum(1 for n in nodes if n.role == Role.LINK)
		landmarks = sum(1 for n in buf.nodes if n.role == Role.LANDMARK)
		forms = sum(1 for n in buf.nodes if n.role == Role.LANDMARK and n.landmark == _("formulario"))
		fields = sum(1 for n in nodes if n.role in (Role.EDITABLETEXT, Role.PASSWORDEDIT, Role.COMBOBOX, Role.CHECKBOX, Role.RADIOBUTTON))
		parts = [
			_("{n} encabezados").format(n=headings),
			_("{n} enlaces").format(n=links),
			_("{n} regiones").format(n=landmarks),
		]
		if forms:
			parts.append(_("{n} formularios").format(n=forms))
		if fields:
			parts.append(_("{n} campos de formulario").format(n=fields))
		return ", ".join(parts)

	@script(description=_("Resume la página: número de encabezados, enlaces, regiones y formularios"), category=CAT, speakOnDemand=True)
	def script_reportPageSummary(self, gesture) -> None:
		speech.speakMessage(self.pageSummary() or _("documento vacío"))

	# ================================================================ búsqueda
	def find(self, text: str, direction: int = 1, caseSensitive: bool | None = None, wholeWord: bool | None = None, regex: bool | None = None, fromStart: bool = False, ask: bool = True) -> bool:
		buf = self.buffer
		if not buf or not text:
			return False
		opts = dict(_findOptions)
		for k, v in (("caseSensitive", caseSensitive), ("wholeWord", wholeWord), ("regex", regex)):
			if v is not None:
				opts[k] = v
		_findOptions.update(opts)
		self._lastFind = text
		addFindHistory(text)
		rx = findPattern(text, opts["caseSensitive"], opts["wholeWord"], opts["regex"])
		if rx is None:
			speech.speakMessage(_("expresión regular no válida"))
			return False
		hay = buf.text
		match = None
		if direction > 0:
			start = 0 if fromStart else self.caret + 1
			match = rx.search(hay, min(start, len(hay)))
		else:
			end = len(hay) if fromStart else max(0, self.caret)
			for m in rx.finditer(hay, 0, end):
				match = m
		if match is None or match.end() == match.start():
			if ask and not fromStart:
				self._offerWrap(text, direction)
			else:
				speech.speakMessage(_("no se encontró «{text}»").format(text=text))
			return False
		self.pushPosition()
		self._moveCaret(match.start())
		# Lo encontrado queda seleccionado.
		self.selectionAnchor = match.start()
		self.caret = match.end()
		self.syncNativeSelection()
		self.caret = match.start()
		self.selectionAnchor = match.end()
		return True

	def _offerWrap(self, text: str, direction: int) -> None:
		"""No hay más coincidencias: ofrece seguir desde el principio o el final (#4637)."""
		import wx

		from .. import gui

		question = (_("No se encontró «{text}» hasta el final del documento. ¿Buscar desde el principio?") if direction > 0 else _("No se encontró «{text}» hasta el principio del documento. ¿Buscar desde el final?")).format(text=text)

		def ask() -> None:
			res = gui.messageBox(question, _("Buscar"), wx.YES_NO | wx.ICON_QUESTION)
			if res == wx.YES:
				queue_handler.queueFunction(self.find, text, direction, fromStart=True, ask=False)

		tones.playSound("boundary")
		gui.runOnGui(ask)

	def lastFindText(self) -> str:
		_loadFindHistory()
		return self._lastFind or (_findHistory[0] if _findHistory else "")

	@script(gesture="kb:tiresias+control+f", description=_("Buscar texto en el documento"), category=CAT)
	def script_find(self, gesture) -> None:
		from ..gui import browse_dialogs

		_loadFindHistory()
		browse_dialogs.showFindDialog(self, self.lastFindText(), list(_findHistory), dict(_findOptions))

	@script(gesture="kb:tiresias+f3", description=_("Busca la siguiente aparición"), category=CAT)
	def script_findNext(self, gesture) -> None:
		text = self.lastFindText()
		if not text:
			self.script_find(gesture)
			return
		self.find(text, 1)

	@script(gesture="kb:tiresias+shift+f3", description=_("Busca la aparición anterior"), category=CAT)
	def script_findPrevious(self, gesture) -> None:
		text = self.lastFindText()
		if not text:
			self.script_find(gesture)
			return
		self.find(text, -1)

	# ================================================================ eventos
	def _nodeOf(self, obj: Any) -> Node | None:
		rid = getattr(obj, "runtimeId", None)
		return self.buffer.byRid.get(rid) if (self.buffer and rid) else None

	def liveRegionText(self, obj: Any) -> str:
		"""Texto actual de una región viva (con todos sus descendientes, #14990)."""
		lines = liveRegionLines(getattr(obj, "element", None))
		text = " ".join(" ".join(lines).split())
		return text or (obj.name or "") or (getattr(obj, "value", "") or "")

	def event_liveRegionChange(self, obj: Any, nextHandler) -> None:
		"""Región viva: se dice lo nuevo, no la región entera.

		Rev. 10.11 (A2): Chromium avisa en la raíz de la región; en un chat
		(role=log) se releía todo el historial con cada mensaje, y la región se
		construía en el hilo del núcleo. Ahora se construye en segundo plano y se
		compara con la versión anterior (la del búfer la primera vez): solo se
		dicen las líneas nuevas, salvo con aria-atomic="true".
		"""
		if not conf["presentation"]["reportDynamicContentChanges"] or not conf["browseMode"]["reportLiveRegions"]:
			return
		node = self._nodeOf(obj)
		live = node.live if node is not None else 0
		if not live:
			try:
				live = int(obj._prop(uc.P_LIVESETTING, 0) or 0)
			except Exception:
				live = 0
		atomic = False
		if node is not None:
			atomic = node.aria.get("atomic") == "true"
		else:
			try:
				from ..objects.uia import parseAriaProperties

				atomic = parseAriaProperties(str(obj._prop(uc.P_ARIAPROPERTIES, "") or "")).get("atomic") == "true"
			except Exception:
				atomic = False
		rid = tuple(getattr(obj, "runtimeId", ()) or ()) or (node.rid if node is not None else ())
		snapshots = self.__dict__.setdefault("_liveSnapshots", {})
		old = snapshots.get(rid)
		if old is None and node is not None and self.buffer is not None and node.end > node.start:
			# Primera vez: lo que ya estaba en el búfer no es nuevo.
			old = [ln.strip() for ln in self.buffer.plainText(node.start, node.end).split("\n") if ln.strip()]
		fallback = ""
		try:
			fallback = obj.name or getattr(obj, "value", "") or ""
		except Exception:
			fallback = ""
		job = (self, getattr(obj, "element", None), rid, old, live, atomic, fallback, node is not None)
		_liveWorker().submit(job)

	def _onLiveRegionText(self, element: Any, rid: tuple, lines: list[str], old: list[str] | None, live: int, atomic: bool, fallback: str, inBuffer: bool) -> None:
		"""En el núcleo: dice lo nuevo de la región viva (o toda si es atómica)."""
		if self.__dict__.get("_terminated"):
			return
		snapshots = self.__dict__.setdefault("_liveSnapshots", {})
		snapshots.pop(rid, None)
		snapshots[rid] = lines
		while len(snapshots) > 50:
			snapshots.pop(next(iter(snapshots)))
		if atomic or old is None:
			parts = lines
			if not atomic and len(" ".join(parts)) > LIVE_REGION_FIRST_LIMIT:
				# Sin versión anterior y con mucho texto (un registro largo): lo último.
				parts = parts[-3:]
		else:
			from ..objects.terminal import computeNewText

			parts = computeNewText(old, lines, "lines")
		text = " ".join(" ".join(parts).split())
		if not text and not lines:
			text = " ".join(fallback.split())
		if not text:
			return
		last, when = self._lastLiveText
		if text == last and time.monotonic() - when < 1.0:
			return
		self._lastLiveText = (text, time.monotonic())
		if live == ariaSem.LIVE_ASSERTIVE and conf["browseMode"]["assertiveLiveRegionsInterrupt"]:
			speech.cancelSpeech()
			speech.speakText(text, priority=speech.Priority.NOW)
		else:
			speech.speakText(text)
		if inBuffer and element is not None:
			self.onStructureChanged(element)

	def event_itemStatusChange(self, obj: Any, nextHandler) -> None:
		"""Cambio de aria-sort en un encabezado de columna (#10890)."""
		node = self._nodeOf(obj)
		try:
			status = str(obj._prop(uc.P_ITEMSTATUS, "") or "")
		except Exception:
			status = ""
		if node is not None and node.role in (Role.TABLECOLUMNHEADER, Role.TABLEROWHEADER, Role.HEADERITEM):
			old = node.itemStatus
			node.itemStatus = status
			node.aria.pop("sort", None)
			label = ariaSem.sortLabel(status)
			if status != old and label:
				speech.speakMessage(f"{obj.name or ''} {label}".strip())
			return
		nextHandler()

	def event_focusEntered(self, obj: Any, nextHandler) -> None:
		"""Un diálogo no se anuncia dos veces seguidas (#8971)."""
		if getattr(obj, "role", None) == Role.DIALOG:
			rid = tuple(getattr(obj, "runtimeId", ()) or ())
			last, when = self._lastDialogAnnounced
			if rid and rid == last and time.monotonic() - when < 3.0:
				return
			self._lastDialogAnnounced = (rid, time.monotonic())
		nextHandler()

	def landmarkExitSpeech(self, oldOffset: int, newOffset: int) -> list[str]:
		"""«fuera de navegación» al salir de una región con el foco (#10420)."""
		if not conf["browseMode"]["reportLandmarksOnFocusChange"] or self.buffer is None:
			return []
		from .buffer import CONTAINER_EXIT_LABELS

		old = [c for c in self.buffer.containersAt(oldOffset) if c.role in (Role.LANDMARK, Role.REGION)]
		new = self.buffer.containersAt(newOffset)
		out = []
		for c in reversed(old):
			if c not in new:
				out.append(CONTAINER_EXIT_LABELS[c.role].format(landmark=c.landmark or _("región")))
		return out

	def insideApplication(self, node: Node | None) -> bool:
		"""¿El elemento está dentro de role=application (se usa modo foco)?"""
		while node is not None:
			if node.role in APPLICATION_ROLES:
				return True
			node = node.parent
		return False

	def reportModeOnEnter(self) -> None:
		"""Anuncia el modo al entrar en un documento si es distinto del anterior."""
		global _lastModeReported
		mode = bool(self.passThrough)
		if _lastModeReported is not None and _lastModeReported != mode and conf["browseMode"]["announceModeOnDocumentChange"]:
			if conf["browseMode"]["passThroughAudioIndication"]:
				tones.playSound("focusMode" if mode else "browseMode")
			else:
				speech.speakMessage(_("modo foco") if mode else _("modo exploración"))
		_lastModeReported = mode

	@staticmethod
	def noteModeReported(mode: bool) -> None:
		global _lastModeReported
		_lastModeReported = bool(mode)

	# ================================================================ ratón
	def nodeAtPoint(self, x: int, y: int) -> Node | None:
		buf = self.buffer
		if buf is None:
			return None
		# Rev. 10.11 (M3): primero el elemento que está ahora en ese punto (las
		# posiciones del búfer son las de cuando se construyó; la página se desplaza).
		node = self._nodeFromScreenPoint(x, y)
		if node is not None:
			return node
		best = None
		bestArea = None
		for n in buf.nodes:
			loc = n.location
			if not loc or n.end <= n.start:
				continue
			lx, ly, w, h = loc
			if lx <= x < lx + w and ly <= y < ly + h:
				area = w * h
				if bestArea is None or area <= bestArea:
					best, bestArea = n, area
		return best

	def _nodeFromScreenPoint(self, x: int, y: int) -> Node | None:
		buf = self.buffer
		client = getattr(uc, "client", None)
		if buf is None or client is None:
			return None
		try:
			import ctypes.wintypes

			el = client.ElementFromPoint(ctypes.wintypes.POINT(int(x), int(y)))
		except (comtypes.COMError, ValueError, TypeError, OSError):
			return None
		walker = uc.rawWalker
		for _i in range(30):
			if not el:
				return None
			node = buf.byRid.get(uc.runtimeIdOf(el))
			if node is not None:
				# Un nodo con texto propio (no un contenedor vacío).
				return node if node.end > node.start else None
			if walker is None:
				return None
			try:
				el = walker.GetParentElement(el)
			except comtypes.COMError:
				return None
		return None

	def onMouseClick(self, x: int, y: int) -> None:
		"""Clic del ratón dentro del documento: el cursor virtual va allí (#4896)."""
		if not conf["browseMode"]["clickMovesCaret"] or self.passThrough:
			return
		node = self.nodeAtPoint(x, y)
		if node is None:
			return
		self.caret = node.start
		self.selectionAnchor = None
		api.setReviewPosition(self.makeTextInfo(textinfo.POSITION_CARET), isCaret=True)
		self._updateBraille(*self.buffer.lineBounds(node.start))

	# ================================================================ navegación inteligente
	@script(gesture="kb:tiresias+alt+n", description=_("Cambia el nivel de las flechas: líneas, elementos o controles (navegación inteligente)"), category=CAT)
	def script_cycleNavLevel(self, gesture) -> None:
		i = NAV_LEVELS.index(self.navLevel) if self.navLevel in NAV_LEVELS else 0
		self.navLevel = NAV_LEVELS[(i + 1) % len(NAV_LEVELS)]
		speech.speakMessage(NAV_LEVEL_LABELS[self.navLevel])

	def _levelPredicate(self):
		if self.navLevel == "control":
			return lambda n: n.role in ATOMIC_ROLES or n.role == Role.LINK or n.isFocusable and n.role not in (Role.DOCUMENT, Role.FRAME)
		buf = self.buffer

		def isItem(n: Node) -> bool:
			# Un elemento: bloque con texto propio, control, enlace o celda.
			if n.role in ATOMIC_ROLES or n.role == Role.LINK or n.rowCol:
				return True
			return n.children == [] and n.role == Role.STATICTEXT and buf.blockOf(n) is not None and buf.blockOf(n).start == n.start or n.role in HEADING_ROLES

		return isItem

	def moveByLevel(self, direction: int) -> bool:
		buf = self.buffer
		if buf is None:
			return False
		pred = self._levelPredicate()
		cur = buf.nodeAt(self.caret)
		start = cur.start if cur is not None else self.caret
		for n in buf.iterNodes(pred, start if direction < 0 else self.caret, direction):
			if cur is not None and (n is cur or n in cur.ancestors() or cur in n.ancestors()) and direction > 0 and n.start <= self.caret:
				continue
			if not buf.text[n.start : n.end].strip():
				continue
			self._moveCaret(n.start, node=n)
			return True
		tones.playSound("boundary")
		return False

	# ================================================================ lectura rápida
	@script(gesture="kb:tiresias+control+shift+s", description=_("Lectura rápida: resume el documento con una regla (primera frase de cada párrafo, texto buscado...)"), category=CAT)
	def script_skimReading(self, gesture) -> None:
		from ..gui import browse_dialogs

		browse_dialogs.showSkimDialog(self)

	def skimResults(self, rule: str, text: str = "") -> list[tuple[str, int]]:
		"""Resultados de la lectura rápida: (texto, desplazamiento)."""
		from . import style

		buf = self.buffer
		if buf is None:
			return []
		out: list[tuple[str, int]] = []
		rx = None
		if rule in ("contains", "regex") and text:
			rx = findPattern(text, False, False, rule == "regex")
			if rx is None:
				return []
		for block in style.textBlocks(buf):
			if block.role in (Role.LINK, Role.BUTTON) or block.role in ATOMIC_ROLES:
				continue
			# Sin las líneas de entrada de contenedores (#3997).
			s, e = buf.paragraphBounds(buf.contentOffset(block.start, 1))
			para = " ".join(buf.text[s:e].split())
			if not para:
				continue
			if out and out[-1][1] == s:
				continue
			if rule == "headings":
				if block.role in HEADING_ROLES:
					out.append((para, s))
				continue
			if rule in ("contains", "regex"):
				if rx is not None and rx.search(para):
					out.append((para, s))
				continue
			if block.role in HEADING_ROLES:
				out.append((para, s))
				continue
			first, _e = textinfo.findSentenceBoundaries(para, 0)
			sentence = para[first:_e].strip()
			if rule == "firstSentence" and len(para) >= 40:
				out.append((sentence, s))
		return out

	# ================================================================ vistazo (Smart Glance)
	def prominentBlocks(self) -> list[Node]:
		from . import style

		return [b for b in style.textBlocks(self.buffer) if style.isProminent(self, b)]

	# ================================================================ web flexible
	@script(gesture="kb:tiresias+control+shift+h", description=_("Web flexible: oculta en este sitio el bloque del cursor"), category=CAT)
	def script_flexHideElement(self, gesture) -> None:
		from . import flexweb

		node = self._caretNode()
		block = self.buffer.blockOf(node) if node is not None else None
		rule = flexweb.ruleForNode(block) if block is not None else None
		if rule is None:
			speech.speakMessage(_("no se puede identificar este elemento"))
			return
		if flexweb.hiddenFraction(rule, self.buffer) > flexweb.MAX_HIDDEN_FRACTION:
			# Rev. 10.11 (M9): la regla ocultaría casi toda la página (una clase genérica).
			speech.speakMessage(_("no se oculta: se ocultaría casi toda la página ({what})").format(what=flexweb.describeRule(rule)))
			return
		flexweb.addHidden(self._documentKey(), rule)
		speech.speakMessage(_("elemento oculto en este sitio: {what}").format(what=flexweb.describeRule(rule)))
		self.requestRebuild()

	@script(gesture="kb:tiresias+control+shift+i", description=_("Web flexible: la lectura de este sitio empezará en el bloque del cursor (dos veces: lo olvida)"), category=CAT)
	def script_flexSetStart(self, gesture) -> None:
		from . import flexweb

		if _repeat() >= 1:
			flexweb.setStart(self._documentKey(), None)
			speech.speakMessage(_("inicio de lectura olvidado"))
			return
		node = self._caretNode()
		block = self.buffer.blockOf(node) if node is not None else None
		rule = flexweb.ruleForNode(block) if block is not None else None
		if rule is None:
			speech.speakMessage(_("no se puede identificar este elemento"))
			return
		flexweb.setStart(self._documentKey(), rule)
		speech.speakMessage(_("la lectura de este sitio empezará aquí"))

	@script(gesture="kb:tiresias+control+shift+o", description=_("Web flexible: alterna el orden de lectura visual por columnas en este sitio (PDF, varias columnas)"), category=CAT)
	def script_flexToggleVisualOrder(self, gesture) -> None:
		from . import flexweb

		value = not flexweb.rulesFor(self._documentKey()).visualOrder
		flexweb.setVisualOrder(self._documentKey(), value)
		speech.speakMessage(_("orden de lectura visual por columnas") if value else _("orden de lectura del documento"))
		self.requestRebuild()

	# ---------------------------------------------------------------- orden de lectura a mano (foros 3.10)
	def _caretBlock(self) -> Node | None:
		node = self._caretNode()
		return self.buffer.textUnitOf(node) if node is not None and self.buffer is not None else None

	@script(gesture="kb:tiresias+control+shift+m", description=_("Orden de lectura: marca el bloque o párrafo del cursor para moverlo"), category=CAT)
	def script_flexMarkBlock(self, gesture) -> None:
		from .reading_order import blockText

		block = self._caretBlock()
		if block is None or not block.rid:
			speech.speakMessage(_("no se puede identificar este elemento"))
			return
		self.__dict__["_markedBlock"] = (block.rid, self._documentKey())
		speech.speakMessage(_("bloque marcado para mover: {text}").format(text=blockText(self.buffer, block)))

	def _moveMarked(self, after: bool) -> None:
		from . import flexweb, reading_order

		marked = self.__dict__.get("_markedBlock")
		if not marked or marked[1] != self._documentKey():
			speech.speakMessage(_("primero marca el bloque que quieres mover"))
			return
		moving = self.buffer.byRid.get(marked[0])
		target = self._caretBlock()
		if moving is None:
			self.__dict__.pop("_markedBlock", None)
			speech.speakMessage(_("el bloque marcado ya no está en el documento"))
			return
		if target is None or target is moving:
			speech.speakMessage(_("coloca el cursor en otro bloque"))
			return
		op = reading_order.planMove(self.buffer, moving, target, after)
		if op is None:
			speech.speakMessage(_("no se puede mover el bloque ahí"))
			return
		flexweb.addReadingOrderOp(self._documentKey(), op)
		self.__dict__.pop("_markedBlock", None)
		where = reading_order.blockText(self.buffer, target)
		speech.speakMessage((_("bloque movido después de: {text}") if after else _("bloque movido antes de: {text}")).format(text=where))
		self.requestRebuild()

	@script(gesture="kb:tiresias+control+shift+a", description=_("Orden de lectura: coloca el bloque marcado antes del bloque del cursor"), category=CAT)
	def script_flexMoveBlockBefore(self, gesture) -> None:
		self._moveMarked(after=False)

	@script(gesture="kb:tiresias+control+shift+d", description=_("Orden de lectura: coloca el bloque marcado después del bloque del cursor"), category=CAT)
	def script_flexMoveBlockAfter(self, gesture) -> None:
		self._moveMarked(after=True)

	@script(gesture="kb:tiresias+control+shift+z", description=_("Orden de lectura: deshace el último cambio del orden (dos veces: vuelve al orden original)"), category=CAT)
	def script_flexUndoReadingOrder(self, gesture) -> None:
		from . import flexweb

		everything = _repeat() >= 1
		left = flexweb.undoReadingOrder(self._documentKey(), everything=everything)
		if left < 0:
			speech.speakMessage(_("orden de lectura original") if everything else _("no hay cambios en el orden de lectura"))
			return
		if everything or left == 0:
			speech.speakMessage(_("orden de lectura original"))
		else:
			speech.speakMessage(_("deshecho el último cambio del orden de lectura; quedan {n}").format(n=left))
		self.requestRebuild()

	@script(description=_("Orden de lectura: el orden propio vale para este documento o para todo el sitio"), category=CAT)
	def script_flexReadingOrderScope(self, gesture) -> None:
		from . import flexweb

		scope = flexweb.toggleReadingOrderScope(self._documentKey())
		if scope is None:
			speech.speakMessage(_("no hay cambios en el orden de lectura"))
			return
		speech.speakMessage(_("el orden de lectura propio vale para todo el sitio") if scope == "site" else _("el orden de lectura propio vale solo para este documento"))
		self.requestRebuild()

	@script(gesture="kb:tiresias+control+shift+w", description=_("Web flexible: gestiona los elementos ocultos y el inicio de lectura de cada sitio"), category=CAT)
	def script_flexManage(self, gesture) -> None:
		from ..gui import browse_dialogs

		browse_dialogs.showFlexWebDialog(self)

	def flexStartNode(self) -> Node | None:
		from . import flexweb

		try:
			return flexweb.rulesFor(self._documentKey()).findStart(self.buffer.nodes)
		except Exception:
			return None
