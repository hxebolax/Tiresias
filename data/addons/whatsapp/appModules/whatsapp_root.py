"""Módulo de aplicación para WhatsApp de la Microsoft Store (WhatsApp.Root.exe).

La interfaz de WhatsApp es una página web (WhatsApp Web) dentro de WebView2,
expuesta por UI Automation. Este módulo:

- desactiva el modo exploración (WhatsApp se usa como aplicación);
- limpia lo que se lee (pistas repetitivas, números de teléfono, «Quizás»,
  roles de tabla);
- añade atajos para moverse entre la lista de chats, los mensajes y el cuadro
  de edición, leer los últimos mensajes sin mover el foco, manejar notas de
  voz y llamadas, copiar mensajes y leer automáticamente los mensajes nuevos.

Los elementos se localizan por criterios estables (identificadores HTML
``side``, ``main`` y ``pane-side``, roles ARIA y la clase
``focusable-list-item``) y, como último recurso, por textos en
``wa_strings.py``.
"""

from __future__ import annotations

import re
from typing import Iterator

import comtypes

from tiresias import api, queue_handler, speech
from tiresias.a11y import uia_client as uc
from tiresias.appmodules import AppModule as BaseAppModule
from tiresias.audio import tones
from tiresias.baseobject import normalizeGestureId, script
from tiresias.config import conf
from tiresias.i18n import _
from tiresias.input import core as inputCore
from tiresias.log import getLogger
from tiresias.objects.base import AccObject
from tiresias.objects.roles import Role, State
from tiresias.objects.uia import UIAObject

from . import wa_options
from . import wa_strings as S

log = getLogger("whatsapp")

CAT = "WhatsApp"

# Opciones (sección «whatsapp»): ver wa_options.py.
wa_options.registerDefaults()

_CR = None


def _cacheRequest():
	"""Petición de caché del subárbol con las propiedades que usa el módulo."""
	global _CR
	if _CR is None:
		_CR = uc.makeCacheRequest(
			(
				uc.P_RUNTIMEID,
				uc.P_NAME,
				uc.P_CONTROLTYPE,
				uc.P_CLASSNAME,
				uc.P_AUTOMATIONID,
				uc.P_ARIAROLE,
				uc.P_ARIAPROPERTIES,
				uc.P_ISKEYBOARDFOCUSABLE,
				uc.P_HASKEYBOARDFOCUS,
				uc.P_ISOFFSCREEN,
				uc.P_RANGEVALUEVALUE,
				uc.P_RANGEVALUEMAXIMUM,
				uc.P_SELECTIONITEMISSELECTED,
				uc.P_VALUEVALUE,
				uc.P_BOUNDINGRECT,
			),
			scope=uc.TreeScope_Subtree,
		)
		# Vista completa: Chromium marca los contenedores genéricos (side, main...)
		# como elementos «no de control» y no aparecerían en la vista de control.
		_CR.TreeFilter = uc.client.RawViewCondition
	return _CR


_FIND_CR = None


def _findCacheRequest():
	global _FIND_CR
	if _FIND_CR is None:
		_FIND_CR = uc.makeCacheRequest(uc.BASE_PROPERTIES)
		_FIND_CR.TreeFilter = uc.client.RawViewCondition
	return _FIND_CR


class Node:
	"""Elemento de una instantánea del árbol (propiedades cacheadas)."""

	__slots__ = ("el", "name", "ct", "cls", "aid", "aria", "focusable", "depth", "parent", "children", "rangeValue", "rangeMax", "selected", "hasFocus", "value")

	def __init__(self, el, parent: "Node | None", depth: int) -> None:
		self.el = el
		self.parent = parent
		self.depth = depth
		self.children: list[Node] = []

		def g(pid, default=None):
			try:
				v = el.GetCachedPropertyValueEx(pid, True)
			except (comtypes.COMError, ValueError):
				return default
			return default if v is None or uc.isNotSupported(v) else v

		self.name = (g(uc.P_NAME, "") or "").strip()
		self.ct = g(uc.P_CONTROLTYPE, 0) or 0
		self.cls = g(uc.P_CLASSNAME, "") or ""
		self.aid = g(uc.P_AUTOMATIONID, "") or ""
		self.aria = (g(uc.P_ARIAROLE, "") or "").lower()
		self.focusable = bool(g(uc.P_ISKEYBOARDFOCUSABLE, False))
		self.hasFocus = bool(g(uc.P_HASKEYBOARDFOCUS, False))
		self.rangeValue = g(uc.P_RANGEVALUEVALUE, None)
		self.rangeMax = g(uc.P_RANGEVALUEMAXIMUM, None)
		self.selected = bool(g(uc.P_SELECTIONITEMISSELECTED, False))
		self.value = g(uc.P_VALUEVALUE, "") or ""

	def walk(self) -> Iterator["Node"]:
		yield self
		for c in self.children:
			yield from c.walk()

	def texts(self) -> list[str]:
		out = []
		for n in self.walk():
			if n.ct == uc.CT_TEXT and n.name:
				out.append(n.name)
		return out

	@property
	def isMessage(self) -> bool:
		return "focusable-list-item" in self.cls

	def obj(self) -> UIAObject | None:
		return UIAObject.fromElement(self.el)


def snapshot(element, maxNodes: int = 6000) -> Node | None:
	"""Recorre el subárbol de ``element`` con una sola petición de caché."""
	if element is None:
		return None
	try:
		cached = element.BuildUpdatedCache(_cacheRequest())
	except (comtypes.COMError, ValueError):
		return None
	count = 0

	def build(el, parent, depth) -> Node:
		nonlocal count
		count += 1
		node = Node(el, parent, depth)
		if count < maxNodes and depth < 120:
			try:
				kids = el.GetCachedChildren()
				n = kids.Length if kids else 0
			except (comtypes.COMError, ValueError):
				n = 0
			for i in range(n):
				node.children.append(build(kids.GetElement(i), node, depth + 1))
		return node

	return build(cached, None, 0)


def _stripMarks(text: str) -> str:
	return text.replace("\u202a", "").replace("\u202c", "").replace("\u200e", "").replace("\u200f", "")


def cleanText(text: str, isMessage: bool = False, filterNumbers: bool = True) -> str:
	"""Texto sin marcas de dirección, pistas ni ruido.

	``filterNumbers=False`` (rev. 10.11, A4): no se quitan «Quizás» ni los
	teléfonos; es lo que usa el texto de los mensajes, donde borraban el
	número o el código que te envían («Quizás mañana...»). Del mensaje solo
	se filtra su remitente (:func:`messageText`).
	"""
	wa = conf["whatsapp"]
	# Primero las marcas de dirección: delante de «Quizás» impedían quitar el prefijo.
	text = _stripMarks(text)
	if wa["filterHints"]:
		text = S.HINT_RE.sub(" ", text)
	text = S.NOISE_RE.sub(" ", text)
	if filterNumbers:
		if wa["filterMaybePrefix"]:
			text = S.MAYBE_RE.sub("", text)
		phones = wa["filterPhoneNumbersInMessages"] if isMessage else wa["filterPhoneNumbersInChats"]
		if phones:
			text = S.PHONE_RE.sub(" ", text)
	return re.sub(r"\s{2,}", " ", text).strip(" ,")


def _isSenderNoise(part: str) -> bool:
	"""El texto es el remitente sin guardar: «Quizás +34 600...» o solo un teléfono."""
	wa = conf["whatsapp"]
	t = _stripMarks(part)
	if wa["filterMaybePrefix"]:
		t = S.MAYBE_RE.sub("", t)
	return bool(wa["filterPhoneNumbersInMessages"]) and bool(S.ONLY_PHONE_RE.match(t))


def messageText(node: Node, forCopy: bool = False) -> str:
	"""Texto de un mensaje.

	``forCopy``: para copiarlo o verlo entero: sin las pistas, pero sin quitar
	el remitente ni nada del contenido (rev. 10.11, A4).
	"""
	parts: list[str] = []
	for t in node.texts():
		if t not in parts[-3:]:
			parts.append(t)
	if not forCopy and len(parts) > 1 and _isSenderNoise(parts[0]):
		# El primer texto es el remitente (contacto sin guardar): solo él se filtra.
		parts = parts[1:]
	text = " ".join(parts)
	if len(node.name) > len(text):
		text = node.name
	return cleanText(text, isMessage=True, filterNumbers=False)


#: Palabras del estado de entrega que solo llevan los mensajes enviados (sin tildes).
_DELIVERY_WORDS = ("leido", "entregado", "enviado", "pendiente", "delivered", " sent", " read")


def _nodesOutsideMessages(root: Node):
	"""Nodos del árbol que no están dentro de un mensaje (pie del chat, cabecera...)."""
	stack = [root]
	while stack:
		n = stack.pop()
		if n.isMessage:
			continue
		yield n
		stack.extend(reversed(n.children))


def messageDirection(node: Node) -> str | None:
	"""``"out"`` (enviado), ``"in"`` (recibido) o ``None`` si no se sabe.

	WhatsApp Web marca cada burbuja con la clase HTML ``message-out`` o
	``message-in``, que Chromium publica como ``ClassName`` de UIA.
	"""
	for n in node.walk():
		classes = n.cls.split()
		if "message-out" in classes:
			return "out"
		if "message-in" in classes:
			return "in"
	return None


def isOutgoingMessage(node: Node, text: str) -> bool:
	"""Si el mensaje lo ha enviado el usuario (no se lee en voz alta al llegar).

	Primero por la clase de la burbuja: así un mensaje recibido que diga
	«ya lo he enviado» o «lo tengo pendiente» se lee. Solo si no hay clase se
	buscan las palabras del estado de entrega en el texto.
	"""
	direction = messageDirection(node)
	if direction is not None:
		return direction == "out"
	norm = S.normalize(text)
	return any(word in norm for word in _DELIVERY_WORDS)


# ====================================================================== objetos
class WACleanName(AccObject):
	"""Limpia los nombres de los elementos de WhatsApp antes de leerlos."""

	def _get_name(self) -> str:
		name = super()._get_name()
		return cleanText(name, isMessage=False) if name else name


class WAChatItem(WACleanName):
	"""Celda de la lista de chats: sin «fila», «celda» ni «1 de 20»."""

	def _get_role(self) -> Role:
		return Role.SECTION if conf["whatsapp"]["silenceTableRoles"] else super()._get_role()

	def _get_positionInfo(self) -> dict:
		return {} if conf["whatsapp"]["silenceTableRoles"] else super()._get_positionInfo()

	def _get_states(self) -> set[State]:
		return {s for s in super()._get_states() if s not in (State.SELECTED, State.SELECTABLE)}


class WAMessage(AccObject):
	"""Mensaje de la conversación (elemento ``focusable-list-item``)."""

	def _get_name(self) -> str:
		node = snapshot(self.element, maxNodes=400)
		if node is None:
			return super()._get_name()
		return messageText(node)

	def _get_role(self) -> Role:
		return Role.SECTION

	def _get_positionInfo(self) -> dict:
		return {}

	def _get_description(self) -> str:
		return ""


# ====================================================================== módulo
class AppModule(BaseAppModule):
	disableBrowseModeByDefault = True
	scriptCategory = CAT

	def __init__(self, processID: int, appName: str | None = None) -> None:
		super().__init__(processID, appName)
		self._lastMessageSignature: str | None = None
		self._lastMessageCount = 0
		self._lastChatTitle = ""
		self._lastSubtitle = ""
		self._pollTimer: int | None = None
		self._messagesContainer = None
		self._mainEl = None
		self._headerEl = None
		self._lastFocusedMessage = None
		self._recording = False
		self._readCount = 0
		self._lastReadIndex = -1
		self._startPolling()

	def terminate(self) -> None:
		if self._pollTimer is not None:
			queue_handler.cancelCallLater(self._pollTimer)
			self._pollTimer = None

	# ------------------------------------------------------------ clases
	def chooseObjectClass(self, obj, clsList: list[type]) -> None:
		if not isinstance(obj, UIAObject):
			return
		try:
			cls = obj.UIAClassName
			aria = obj.UIAAriaRole
			ct = obj.UIAControlType
		except Exception:
			return
		if "focusable-list-item" in cls:
			clsList.insert(0, WAMessage)
		elif ct == uc.CT_DATAITEM and aria in ("gridcell", "row"):
			clsList.insert(0, WAChatItem)
		elif ct in (uc.CT_BUTTON, uc.CT_DATAITEM, uc.CT_GROUP, uc.CT_LISTITEM, uc.CT_TEXT, uc.CT_HYPERLINK):
			clsList.insert(0, WACleanName)

	def event_gainFocus(self, obj, nextHandler) -> None:
		if isinstance(obj, WAMessage):
			self._lastFocusedMessage = obj.element
		nextHandler()

	def event_appModule_gainFocus(self) -> None:
		self._startPolling()

	# ------------------------------------------------------------ localizar
	def _document(self):
		focus = api.getFocusObject()
		if focus is not None and (not isinstance(focus, UIAObject) or focus.appModule is not self):
			focus = None
		candidates = []
		if focus is not None:
			candidates = [focus] + list(reversed(api.getFocusAncestors()))
		for c in candidates:
			try:
				if getattr(c, "UIAAutomationId", "") == "RootWebArea":
					return c.element
			except Exception:
				continue
		fg = api.getForegroundObject()
		if fg is None or fg.processID != self.processID:
			return None
		try:
			cond = uc.createPropertyCondition(uc.P_AUTOMATIONID, "RootWebArea")
			el = fg.element.FindFirstBuildCache(uc.TreeScope_Descendants, cond, _findCacheRequest())
			return el if el else None
		except comtypes.COMError:
			return None

	def _findById(self, automationId: str):
		doc = self._document()
		if doc is None:
			return None
		try:
			cond = uc.createPropertyCondition(uc.P_AUTOMATIONID, automationId)
			el = doc.FindFirstBuildCache(uc.TreeScope_Descendants, cond, _findCacheRequest())
			return el if el else None
		except comtypes.COMError:
			return None

	def _mainSnapshot(self) -> Node | None:
		return snapshot(self._findById("main"))

	def _messages(self, main: Node | None = None) -> list[Node]:
		main = main or self._mainSnapshot()
		if main is None:
			return []
		msgs = [n for n in main.walk() if n.isMessage]
		if not msgs:
			# Alternativa: filas (role=row) con un elemento enfocable dentro.
			for n in main.walk():
				if n.aria == "row":
					focusable = next((d for d in n.walk() if d.focusable), None)
					if focusable is not None:
						msgs.append(focusable)
		return msgs

	def _composeBox(self, main: Node | None = None) -> Node | None:
		main = main or self._mainSnapshot()
		if main is None:
			return None
		edits = [n for n in main.walk() if n.ct == uc.CT_EDIT]
		for e in edits:
			if S.contains(e.name, S.COMPOSE_BOX):
				return e
		return edits[-1] if edits else None

	def _chatHeader(self, main: Node | None = None) -> Node | None:
		main = main or self._mainSnapshot()
		if main is None:
			return None
		for n in main.walk():
			if n.aria == "banner" or n.ct == uc.CT_HEADER:
				return n
		return None

	def _chatList(self) -> Node | None:
		side = snapshot(self._findById("pane-side")) or snapshot(self._findById("side"))
		if side is None:
			return None
		for n in side.walk():
			if n.ct == uc.CT_DATAGRID or n.aria == "grid" or S.matches(n.name, S.CHAT_LIST):
				return n
		return None

	@staticmethod
	def _focus(node: Node | None) -> bool:
		if node is None:
			return False
		try:
			node.el.SetFocus()
			return True
		except comtypes.COMError:
			return False

	def _chatTitleAndStatus(self) -> tuple[str, str]:
		header = self._chatHeader()
		if header is None:
			return "", ""
		texts = [t for t in header.texts() if t.strip()]
		if not texts:
			btn = next((n for n in header.walk() if n.ct == uc.CT_BUTTON and n.name), None)
			return (cleanText(btn.name) if btn else ""), ""
		title = cleanText(texts[0])
		status = cleanText(" ".join(texts[1:3])) if len(texts) > 1 else ""
		return title, status

	# ------------------------------------------------------------ órdenes
	def _speak(self, text: str) -> None:
		speech.cancelSpeech()
		speech.speakText(text)

	@script(description=_("Va a la lista de chats (al chat seleccionado)"), gesture="kb:alt+1", category=CAT)
	def script_goToChatList(self, gesture) -> None:
		grid = self._chatList()
		if grid is None:
			self._speak(_("No se encontró la lista de chats"))
			return
		cells = [n for n in grid.walk() if n.focusable and n.ct == uc.CT_DATAITEM]
		if not cells:
			cells = [n for n in grid.walk() if n.focusable]
		target = next((c for c in cells if c.selected), None) or (cells[0] if cells else None)
		if not self._focus(target):
			self._speak(_("No se pudo ir a la lista de chats"))

	@script(description=_("Va al último mensaje del chat abierto"), gesture="kb:alt+2", category=CAT)
	def script_goToLastMessage(self, gesture) -> None:
		msgs = self._messages()
		if not msgs:
			self._speak(_("No hay mensajes visibles. Abre un chat primero."))
			return
		self._focus(msgs[-1])

	@script(description=_("Va al primer mensaje no leído"), gesture="kb:alt+3", category=CAT)
	def script_goToFirstUnread(self, gesture) -> None:
		main = self._mainSnapshot()
		if main is None:
			self._speak(_("No hay un chat abierto"))
			return
		nodes = list(main.walk())
		for i, n in enumerate(nodes):
			if n.name and S.UNREAD_DIVIDER.search(n.name):
				nxt = next((m for m in nodes[i + 1 :] if m.isMessage), None)
				if nxt is not None:
					self._speak(n.name)
					self._focus(nxt)
					return
		self._speak(_("No hay mensajes no leídos en este chat"))

	@script(description=_("Alterna entre el cuadro de edición y el último mensaje enfocado"), gesture="kb:alt+d", category=CAT)
	def script_toggleComposeAndMessages(self, gesture) -> None:
		focus = api.getFocusObject()
		inEdit = focus is not None and focus.role in (Role.EDITABLETEXT,)
		if inEdit:
			if self._lastFocusedMessage is not None:
				try:
					self._lastFocusedMessage.SetFocus()
					return
				except comtypes.COMError:
					pass
			self.script_goToLastMessage(gesture)
			return
		box = self._composeBox()
		if not self._focus(box):
			self._speak(_("No se encontró el cuadro de edición"))

	@script(description=_("Lee el título del chat y su estado (dos veces: activa o desactiva el aviso de «escribiendo»)"), gesture="kb:alt+t", category=CAT)
	def script_chatTitle(self, gesture) -> None:
		if inputCore.getLastScriptRepeatCount() == 1:
			v = not conf["whatsapp"]["announceTyping"]
			conf["whatsapp"]["announceTyping"] = v
			self._speak(_("Aviso de escribiendo activado") if v else _("Aviso de escribiendo desactivado"))
			return
		title, status = self._chatTitleAndStatus()
		if not title:
			self._speak(_("No hay un chat abierto"))
			return
		self._speak(f"{title}. {status}" if status else title)

	def _readNthLast(self, n: int) -> None:
		msgs = self._messages()
		if len(msgs) < n:
			self._speak(_("No hay {n} mensajes visibles").format(n=n))
			return
		node = msgs[-n]
		if inputCore.getLastScriptRepeatCount() >= 1 and self._lastReadIndex == n:
			self._focus(node)
			return
		self._lastReadIndex = n
		self._speak(messageText(node) or _("Mensaje sin texto"))

	def _changeChat(self, direction: int) -> None:
		grid = self._chatList()
		if grid is None:
			self._speak(_("No se encontró la lista de chats"))
			return
		cells = [n for n in grid.walk() if n.focusable and n.ct == uc.CT_DATAITEM] or [n for n in grid.walk() if n.focusable]
		if not cells:
			return
		idx = next((i for i, c in enumerate(cells) if c.selected), None)
		if idx is None:
			idx = -1 if direction > 0 else len(cells)
		target = idx + direction
		if not (0 <= target < len(cells)):
			tones.playSound("boundary")
			return
		cell = cells[target]
		if self._focus(cell):
			from tiresias.input.gestures import sendKey

			sendKey("enter")
			queue_handler.callLater(400, self._announceChat)

	def _announceChat(self) -> None:
		title, status = self._chatTitleAndStatus()
		if title:
			speech.speakText(f"{title}. {status}" if status else title)

	@script(description=_("Abre el chat anterior de la lista"), gesture="kb:alt+upArrow", category=CAT)
	def script_previousChat(self, gesture) -> None:
		self._changeChat(-1)

	@script(description=_("Abre el chat siguiente de la lista"), gesture="kb:alt+downArrow", category=CAT)
	def script_nextChat(self, gesture) -> None:
		self._changeChat(1)

	# --------------------------------------------------- mensaje con foco
	def _focusedMessage(self) -> Node | None:
		focus = api.getFocusObject()
		if not isinstance(focus, WAMessage):
			return None
		return snapshot(focus.element, maxNodes=500)

	@script(description=_("En un mensaje de voz o vídeo: reproduce o pausa"), gesture="kb:enter", category=CAT)
	def script_playPause(self, gesture) -> None:
		msg = self._focusedMessage()
		if msg is None:
			gesture.send()
			return
		nodes = list(msg.walk())
		sliderIdx = next((i for i, n in enumerate(nodes) if n.ct == uc.CT_SLIDER), None)
		button = None
		if sliderIdx is not None:
			button = next((n for n in reversed(nodes[:sliderIdx]) if n.ct == uc.CT_BUTTON), None)
		if button is None:
			button = next((n for n in nodes if n.ct == uc.CT_BUTTON and (S.matches(n.name, S.PLAY) or S.matches(n.name, S.PAUSE))), None)
		if button is None:
			gesture.send()
			return
		before = button.name
		obj = button.obj()
		if obj is not None and obj.doAction():
			queue_handler.callLater(300, self._reportPlayState, before)

	def _reportPlayState(self, before: str) -> None:
		speech.speakMessage(_("Pausado") if S.matches(before, S.PAUSE) else _("Reproduciendo"))

	@script(description=_("Posición y duración de la nota de voz del mensaje"), gesture="kb:alt+shift+t", category=CAT)
	def script_voicePosition(self, gesture) -> None:
		msg = self._focusedMessage()
		nodes = list(msg.walk()) if msg else []
		slider = next((n for n in nodes if n.ct == uc.CT_SLIDER), None)
		if slider is None:
			main = self._mainSnapshot()
			slider = next((n for n in reversed(list(main.walk())) if n.ct == uc.CT_SLIDER), None) if main else None
		if slider is None or slider.rangeValue is None:
			self._speak(_("No hay una nota de voz"))
			return

		def fmt(seconds: float) -> str:
			s = int(seconds)
			return f"{s // 60}:{s % 60:02d}"

		pos = float(slider.rangeValue)
		total = float(slider.rangeMax or 0)
		self._speak(_("{pos} de {total}").format(pos=fmt(pos), total=fmt(total)) if total else fmt(pos))

	@script(description=_("Copia el texto limpio del mensaje con foco"), gesture="kb:control+c", category=CAT)
	def script_copyMessage(self, gesture) -> None:
		msg = self._focusedMessage()
		if msg is None:
			gesture.send()
			return
		# Rev. 10.11 (A4): se copia el mensaje entero (sin las pistas), también
		# los teléfonos y los códigos que contenga.
		text = messageText(msg, forCopy=True)
		if text:
			api.copyToClip(text, notify=True)

	@script(description=_("Muestra el mensaje completo en una ventana (expande «Leer más»)"), gesture="kb:alt+c", category=CAT)
	def script_fullMessage(self, gesture) -> None:
		msg = self._focusedMessage()
		if msg is None:
			self._speak(_("Sitúate en un mensaje"))
			return
		more = next((n for n in msg.walk() if n.ct in (uc.CT_BUTTON, uc.CT_HYPERLINK) and S.matches(n.name, S.READ_MORE)), None)
		if more is not None:
			obj = more.obj()
			if obj is not None:
				obj.doAction()
			queue_handler.callLater(250, self._showFullMessage)
		else:
			self._showFullMessage()

	def _showFullMessage(self) -> None:
		from tiresias import gui

		msg = self._focusedMessage()
		if msg is None:
			return
		gui.showBrowseableMessage(messageText(msg, forCopy=True), _("Mensaje de WhatsApp"))

	@script(description=_("Abre el menú contextual del mensaje"), gesture="kb:shift+enter", category=CAT)
	def script_messageMenu(self, gesture) -> None:
		msg = self._focusedMessage()
		if msg is None:
			gesture.send()
			return
		buttons = [n for n in msg.walk() if n.ct == uc.CT_BUTTON]
		target = next((b for b in buttons if S.contains(b.name, S.MENU)), None) or (buttons[-1] if buttons else None)
		obj = target.obj() if target else None
		if obj is None or not obj.doAction():
			gesture.send()

	@script(description=_("Reacciona al mensaje con foco"), gesture="kb:control+shift+enter", category=CAT)
	def script_react(self, gesture) -> None:
		msg = self._focusedMessage()
		if msg is None:
			gesture.send()
			return
		target = next((b for b in msg.walk() if b.ct == uc.CT_BUTTON and S.contains(b.name, S.REACT)), None)
		obj = target.obj() if target else None
		if obj is None or not obj.doAction():
			self._speak(_("No se encontró el botón de reaccionar"))

	# --------------------------------------------------- notas de voz
	def _isRecording(self, main: Node | None = None) -> bool:
		"""Hay una nota de voz grabándose si aparecen sus controles (descartar,
		pausar o el contador de tiempo) en el pie del chat."""
		main = main or self._mainSnapshot()
		if main is None:
			return False
		hasDelete = False
		hasPauseOrTimer = False
		# Rev. 10.11 (M5): solo fuera de los mensajes (la hora de cada mensaje
		# parecía el contador de la grabación) y con el nombre exacto del botón
		# («Eliminar mensaje» no es «Eliminar»).
		for n in _nodesOutsideMessages(main):
			if n.ct == uc.CT_BUTTON and S.matches(n.name, S.DELETE_RECORDING, exact=True):
				hasDelete = True
			elif n.ct == uc.CT_BUTTON and S.matches(n.name, S.PAUSE, exact=True):
				hasPauseOrTimer = True
			elif n.ct == uc.CT_TEXT and re.fullmatch(r"\d{1,2}:\d{2}", n.name or ""):
				hasPauseOrTimer = True
		return hasDelete and hasPauseOrTimer

	@script(description=_("Empieza a grabar una nota de voz; si ya se graba, la envía"), gesture="kb:alt+m", category=CAT)
	def script_recordVoice(self, gesture) -> None:
		from tiresias.input.gestures import sendKey

		if self._isRecording():
			sendKey("control+enter")
			speech.speakMessage(_("Nota de voz enviada"))
			return
		sendKey("control+alt+shift+r")
		tones.playSound("recording")
		speech.speakMessage(_("Grabando nota de voz. Alt+M para enviar, Alt+Mayúsculas+M para descartar"))

	@script(description=_("Descarta la nota de voz que se está grabando"), gesture="kb:alt+shift+m", category=CAT)
	def script_discardVoice(self, gesture) -> None:
		main = self._mainSnapshot()
		btn = None
		if main is not None and self._isRecording(main):
			btn = next((n for n in _nodesOutsideMessages(main) if n.ct == uc.CT_BUTTON and S.matches(n.name, S.DELETE_RECORDING, exact=True)), None)
		obj = btn.obj() if btn else None
		if obj is not None and obj.doAction():
			speech.speakMessage(_("Grabación descartada"))
		else:
			self._speak(_("No hay ninguna grabación en curso"))

	# --------------------------------------------------- llamadas
	def _invokeHeaderButton(self, names: list[str], notFound: str) -> None:
		header = self._chatHeader()
		btn = next((n for n in header.walk() if n.ct == uc.CT_BUTTON and S.matches(n.name, names)), None) if header else None
		obj = btn.obj() if btn else None
		if obj is None or not obj.doAction():
			self._speak(notFound)

	@script(description=_("Llamada de voz al chat abierto"), gesture="kb:alt+shift+c", category=CAT)
	def script_voiceCall(self, gesture) -> None:
		self._invokeHeaderButton(S.VOICE_CALL, _("No se encontró el botón de llamada"))

	@script(description=_("Videollamada al chat abierto"), gesture="kb:alt+shift+v", category=CAT)
	def script_videoCall(self, gesture) -> None:
		self._invokeHeaderButton(S.VIDEO_CALL, _("No se encontró el botón de videollamada"))

	def _callWindowButton(self, names: list[str]):
		"""Busca un botón en las ventanas de llamada de WhatsApp (WinUI)."""
		from tiresias import winapi

		found = []

		def enum(hwnd, lParam):
			if winapi.getWindowProcessId(hwnd) == self.processID and winapi.user32.IsWindowVisible(hwnd):
				found.append(hwnd)
			return True

		winapi.user32.EnumWindows(winapi.WNDENUMPROC(enum), 0)
		cond = uc.createPropertyCondition(uc.P_CONTROLTYPE, uc.CT_BUTTON)
		for hwnd in found:
			try:
				root = uc.client.ElementFromHandle(hwnd)
				arr = root.FindAllBuildCache(uc.TreeScope_Descendants, cond, uc.baseCacheRequest)
			except comtypes.COMError:
				continue
			for i in range(arr.Length if arr else 0):
				el = arr.GetElement(i)
				try:
					# Rev. 10.11 (M5): nombre exacto («Aceptar» de cualquier diálogo no
					# es la llamada).
					if S.matches(el.CachedName or "", names, exact=True):
						return UIAObject.fromElement(el)
				except comtypes.COMError:
					continue
		return None

	@script(description=_("Acepta una llamada entrante"), gesture="kb:control+alt+a", category=CAT)
	def script_acceptCall(self, gesture) -> None:
		obj = self._callWindowButton(S.ACCEPT_CALL)
		if obj is None or not obj.doAction():
			gesture.send()
		else:
			speech.speakMessage(_("Llamada aceptada"))

	@script(description=_("Rechaza la llamada entrante o cuelga"), gesture="kb:control+alt+d", category=CAT)
	def script_declineCall(self, gesture) -> None:
		obj = self._callWindowButton(S.DECLINE_CALL)
		if obj is None or not obj.doAction():
			gesture.send()
		else:
			speech.speakMessage(_("Llamada rechazada"))

	# --------------------------------------------------- utilidades
	@script(description=_("Cierra el visor de multimedia, el reproductor o el aviso que tapa la ventana"), gesture="kb:alt+0", category=CAT)
	def script_closeOverlay(self, gesture) -> None:
		doc = self._document()
		snap = snapshot(doc, maxNodes=4000) if doc is not None else None
		btn = None
		if snap is not None:
			for n in snap.walk():
				if n.ct == uc.CT_BUTTON and S.matches(n.name, S.CLOSE, exact=True):
					btn = n
		obj = btn.obj() if btn else None
		if obj is not None and obj.doAction():
			speech.speakMessage(_("Cerrado"))
		else:
			self._speak(_("No hay nada que cerrar"))

	@script(description=_("Activa o desactiva la lectura automática de mensajes nuevos"), gesture="kb:alt+shift+l", category=CAT)
	def script_toggleAutoRead(self, gesture) -> None:
		v = not conf["whatsapp"]["autoReadNewMessages"]
		conf["whatsapp"]["autoReadNewMessages"] = v
		self._speak(_("Lectura automática de mensajes nuevos activada") if v else _("Lectura automática desactivada"))

	@script(description=_("Activa o desactiva el filtro de números de teléfono"), gesture="kb:control+shift+e", category=CAT)
	def script_togglePhoneFilter(self, gesture) -> None:
		focus = api.getFocusObject()
		key = "filterPhoneNumbersInMessages" if isinstance(focus, WAMessage) else "filterPhoneNumbersInChats"
		v = not conf["whatsapp"][key]
		conf["whatsapp"][key] = v
		if key.endswith("Messages"):
			self._speak(_("Números de teléfono ocultos en mensajes") if v else _("Números de teléfono visibles en mensajes"))
		else:
			self._speak(_("Números de teléfono ocultos en la lista de chats") if v else _("Números de teléfono visibles en la lista de chats"))

	@script(description=_("Activa o desactiva la lectura de las pistas de uso de WhatsApp"), gesture="kb:alt+shift+h", category=CAT)
	def script_toggleHints(self, gesture) -> None:
		v = not conf["whatsapp"]["filterHints"]
		conf["whatsapp"]["filterHints"] = v
		self._speak(_("Pistas ocultas") if v else _("Pistas visibles"))

	@script(description=_("Ayuda de los atajos del complemento de WhatsApp"), gesture="kb:alt+h", category=CAT)
	def script_help(self, gesture) -> None:
		from tiresias import gui
		from tiresias.input.keys import labelForGesture

		lines = [_("Atajos del complemento WhatsApp accesible:"), ""]
		for gid, name in sorted(type(self).iterClassGestures(), key=lambda g: g[1]):
			func = getattr(self, "script_" + name, None)
			if func and func.__doc__:
				lines.append(f"{labelForGesture(gid)}: {func.__doc__}")
		lines += [
			"",
			_("Atajos propios de WhatsApp (siguen funcionando):"),
			_("Control+Alt+N: nuevo chat. Control+Mayúsculas+N: nuevo grupo."),
			_("Control+Alt+barra: buscar. Control+Mayúsculas+F: buscar en el chat."),
			_("Control+Mayúsculas+U: marcar como no leído. Control+Mayúsculas+M: silenciar. Control+Mayúsculas+A: archivar."),
			_("Control+Alt+Mayúsculas+P: fijar chat. Alt+I: información del chat. Alt+S: ajustes de WhatsApp."),
			_("Alt+R: responder. Control+Alt+D: reenviar (fuera de llamadas). Alt+8: destacar. Alt+A: adjuntar."),
			_("Mayúsculas+punto y Mayúsculas+coma: velocidad de la nota de voz. Alt+P: pausar la grabación."),
			_("Control+flecha arriba: editar el último mensaje. Escape: cerrar el chat."),
			_("Control+1 a Control+9: abrir el chat número N."),
		]
		gui.showBrowseableMessage("\n".join(lines), _("Ayuda de WhatsApp accesible"))

	@script(description=_("Ajustes del complemento de WhatsApp"), gesture="kb:alt+shift+s", category=CAT)
	def script_settings(self, gesture) -> None:
		from tiresias import gui

		gui.runOnGui(_showSettingsDialog)

	# --------------------------------------------------- vigilancia
	def _startPolling(self) -> None:
		if self._pollTimer is None:
			self._pollTimer = queue_handler.callLater(1500, self._poll)

	def _poll(self) -> None:
		self._pollTimer = None
		if not self.isAlive:
			return
		try:
			self._checkChat()
		except Exception:
			log.debug("Error vigilando WhatsApp", exc_info=True)
		self._pollTimer = queue_handler.callLater(1200, self._poll)

	def _isForeground(self) -> bool:
		fg = api.getForegroundObject()
		return fg is not None and fg.processID == self.processID

	def _elementAlive(self, el, automationId: str | None = None) -> bool:
		if el is None:
			return False
		try:
			if automationId is not None:
				return el.CurrentAutomationId == automationId
			return bool(el.CurrentProcessId)
		except (comtypes.COMError, ValueError):
			return False

	def _cachedMain(self):
		if not self._elementAlive(self._mainEl, "main"):
			self._mainEl = self._findById("main")
			self._messagesContainer = None
			self._headerEl = None
		return self._mainEl

	def _locateContainers(self) -> bool:
		"""Localiza (una vez por chat) el contenedor de mensajes y la cabecera."""
		main = snapshot(self._cachedMain())
		if main is None:
			return False
		msgs = self._messages(main)
		self._messagesContainer = None
		if msgs:
			# El contenedor es el antecesor común de los mensajes (el padre de su fila).
			last = msgs[-1]
			row = last
			found = False
			while row.parent is not None:
				if row.parent.aria in ("grid", "list", "application", "log") or len([c for c in row.parent.children if any(d.isMessage for d in c.walk())]) > 1:
					found = True
					break
				row = row.parent
			if found:
				self._messagesContainer = row.parent.el
			else:
				# Rev. 10.11 (M4): un solo mensaje (chat nuevo): su padre directo.
				self._messagesContainer = last.parent.el if last.parent is not None else None
		header = self._chatHeader(main)
		self._headerEl = header.el if header is not None else None
		return True

	def _lastRowSnapshot(self) -> Node | None:
		container = self._messagesContainer
		if container is None:
			return None
		try:
			last = uc.rawWalker.GetLastChildElement(container)
		except (comtypes.COMError, ValueError):
			self._messagesContainer = None
			return None
		guard = 0
		while last is not None and guard < 6:
			snap = snapshot(last, maxNodes=400)
			if snap is not None:
				msg = next((n for n in snap.walk() if n.isMessage), None)
				if msg is not None:
					return msg
			try:
				last = uc.rawWalker.GetPreviousSiblingElement(last)
			except (comtypes.COMError, ValueError):
				return None
			guard += 1
		return None

	def _headerTexts(self) -> tuple[str, str]:
		if self._headerEl is None:
			return "", ""
		snap = snapshot(self._headerEl, maxNodes=200)
		if snap is None:
			self._headerEl = None
			return "", ""
		texts = [t for t in snap.texts() if t.strip()]
		if not texts:
			return "", ""
		return cleanText(texts[0]), (cleanText(" ".join(texts[1:3])) if len(texts) > 1 else "")

	def _checkChat(self) -> None:
		wa = conf["whatsapp"]
		if not self._isForeground() and not wa["autoReadInBackground"]:
			return
		if self.sleepMode or not (wa["autoReadNewMessages"] or wa["announceTyping"]):
			return
		if self._cachedMain() is None:
			self._lastMessageSignature = None
			return
		if self._messagesContainer is None or self._headerEl is None:
			# Rev. 10.11 (M4): si no se encuentran (chat vacío, otra versión de
			# WhatsApp), no se recorre la ventana entera cada segundo: se espera
			# cada vez más (hasta 30 s) antes de volver a intentarlo.
			import time

			now = time.monotonic()
			retryAt = self.__dict__.get("_locateRetryAt", 0.0)
			if now < retryAt:
				return
			ok = self._locateContainers()
			if not ok or self._messagesContainer is None or self._headerEl is None:
				backoff = min(30.0, max(2.4, self.__dict__.get("_locateBackoff", 1.2) * 2))
				self._locateBackoff = backoff
				self._locateRetryAt = now + backoff
				if not ok:
					return
			else:
				self._locateBackoff = 1.2
				self._locateRetryAt = 0.0
		title, status = self._headerTexts()
		if title != self._lastChatTitle:
			# Cambio de chat: se vuelve a localizar todo y no se lee nada.
			self._lastChatTitle = title
			self._lastSubtitle = status
			self._lastMessageSignature = None
			self._locateContainers()
		elif wa["announceTyping"] and status != self._lastSubtitle:
			self._lastSubtitle = status
			if status and S.contains(status, S.TYPING):
				speech.speakText(f"{title} {status}")
		last = self._lastRowSnapshot()
		if last is None:
			return
		text = messageText(last)
		try:
			rid = tuple(last.el.GetRuntimeId() or ())
		except (comtypes.COMError, ValueError):
			rid = ()
		signature = f"{rid}|{text}"
		if self._lastMessageSignature is None:
			self._lastMessageSignature = signature
			return
		if signature == self._lastMessageSignature:
			return
		previous = self._lastMessageSignature
		self._lastMessageSignature = signature
		if previous.split("|", 1)[-1] == text or not text:
			return
		if not wa["autoReadNewMessages"] or isOutgoingMessage(last, text):
			return
		focus = api.getFocusObject()
		if focus is not None and isinstance(focus, WAMessage):
			# El usuario está recorriendo mensajes: solo un aviso sonoro.
			tones.playSound("newMessage")
			return
		if wa["newMessageSound"]:
			tones.playSound("newMessage")
		speech.speakText(text)


def _addReadLastScripts() -> None:
	"""Alt+Mayúsculas+1 a 9 y 0: lee el mensaje N contando desde el final (0 = el décimo).

	Es el equivalente de Alt+1 a Alt+0 de los demás chats (Teams, Discord...),
	que aquí no se usa porque Alt+1 a Alt+3 ya mueven el foco.
	"""
	for n in range(1, 11):
		key = str(n % 10)

		def scriptFunc(self, gesture, _n=n):
			self._readNthLast(_n)

		scriptFunc.__name__ = f"script_readLastMessage{n}"
		desc = _("Lee el último mensaje (dos veces: lo enfoca)") if n == 1 else _("Lee el mensaje {n} contando desde el final (dos veces: lo enfoca)").format(n=n)
		decorated = script(description=desc, gesture=f"kb:alt+shift+{key}", category=CAT)(scriptFunc)
		setattr(AppModule, scriptFunc.__name__, decorated)
		# Normalizado (kb:shift+alt+N): así se genera el gesto al pulsar las teclas.
		AppModule._classGestures[normalizeGestureId(f"kb:alt+shift+{key}")] = f"readLastMessage{n}"  # type: ignore[attr-defined]


_addReadLastScripts()


# ====================================================================== ajustes
_SETTINGS = wa_options.SETTINGS


def _showSettingsDialog() -> None:
	import wx

	from tiresias import winapi

	dlg = wx.Dialog(None, title=_("Ajustes de WhatsApp accesible"))
	sizer = wx.BoxSizer(wx.VERTICAL)
	boxes = {}
	for key, label in _SETTINGS:
		cb = wx.CheckBox(dlg, label=label)
		cb.SetValue(bool(conf["whatsapp"][key]))
		sizer.Add(cb, 0, wx.ALL, 5)
		boxes[key] = cb
	btns = dlg.CreateButtonSizer(wx.OK | wx.CANCEL)
	sizer.Add(btns, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
	dlg.SetSizerAndFit(sizer)

	def onClose(evt):
		if evt.GetId() == wx.ID_OK:
			for key, cb in boxes.items():
				conf["whatsapp"][key] = cb.GetValue()
		dlg.Destroy()

	dlg.Bind(wx.EVT_BUTTON, onClose, id=wx.ID_OK)
	dlg.Bind(wx.EVT_BUTTON, onClose, id=wx.ID_CANCEL)
	dlg.Show()
	dlg.Raise()
	winapi.setForegroundWindow(dlg.GetHandle())
	if boxes:
		next(iter(boxes.values())).SetFocus()
