"""Objetos accesibles de aplicaciones Java (Java Access Bridge).

:class:`JABObject` envuelve un ``AccessibleContext`` (identificador de máquina
virtual + referencia al objeto Java). La información básica se lee de una
sola vez con ``getAccessibleContextInfo`` y se guarda durante el ciclo del
núcleo. Los campos de texto usan :class:`JABTextInfo` (texto completo,
cursor, selección y límites de línea del propio Java; las palabras se calculan
en Tiresias porque Java las delimita mal, #16374).
"""

from __future__ import annotations

import ctypes

from .. import baseobject, textinfo
from ..a11y import jab
from ..i18n import _
from ..log import getLogger
from .base import AccObject
from .roles import Role, State

log = getLogger("jabObjects")

_ROLES = {
	"alert": Role.ALERT,
	"canvas": Role.CANVAS,
	"check box": Role.CHECKBOX,
	"color chooser": Role.COLORCHOOSER,
	"column header": Role.TABLECOLUMNHEADER,
	"combo box": Role.COMBOBOX,
	"date editor": Role.DATEEDITOR,
	"desktop icon": Role.DESKTOPICON,
	"desktop pane": Role.DESKTOPPANE,
	"dialog": Role.DIALOG,
	"directory pane": Role.DIRECTORYPANE,
	"edit bar": Role.EDITBAR,
	"file chooser": Role.FILECHOOSER,
	"filler": Role.FILLER,
	"font chooser": Role.FONTCHOOSER,
	"footer": Role.FOOTER,
	"frame": Role.FRAME,
	"glass pane": Role.GLASSPANE,
	"group box": Role.GROUPING,
	"header": Role.HEADER,
	"hyperlink": Role.LINK,
	"icon": Role.ICON,
	"internal frame": Role.INTERNALFRAME,
	"label": Role.LABEL,
	"layered pane": Role.LAYEREDPANE,
	"list": Role.LIST,
	"list item": Role.LISTITEM,
	"menu": Role.POPUPMENU,
	"menu bar": Role.MENUBAR,
	"menu item": Role.MENUITEM,
	"option pane": Role.OPTIONPANE,
	"page tab": Role.TAB,
	"page tab list": Role.TABCONTROL,
	"panel": Role.PANEL,
	"paragraph": Role.PARAGRAPH,
	"password text": Role.PASSWORDEDIT,
	"popup menu": Role.POPUPMENU,
	"progress bar": Role.PROGRESSBAR,
	"push button": Role.BUTTON,
	"radio button": Role.RADIOBUTTON,
	"root pane": Role.ROOTPANE,
	"row header": Role.TABLEROWHEADER,
	"ruler": Role.RULER,
	"scroll bar": Role.SCROLLBAR,
	"scroll pane": Role.SCROLLPANE,
	"separator": Role.SEPARATOR,
	"slider": Role.SLIDER,
	"spin box": Role.SPINBUTTON,
	"split pane": Role.SPLITPANE,
	"status bar": Role.STATUSBAR,
	"statusbar": Role.STATUSBAR,
	"table": Role.TABLE,
	"text": Role.EDITABLETEXT,
	"toggle button": Role.TOGGLEBUTTON,
	"tool bar": Role.TOOLBAR,
	"tool tip": Role.TOOLTIP,
	"tree": Role.TREEVIEW,
	"viewport": Role.VIEWPORT,
	"window": Role.WINDOW,
	"unknown": Role.UNKNOWN,
}

_STATES = {
	"focusable": State.FOCUSABLE,
	"focused": State.FOCUSED,
	"selected": State.SELECTED,
	"selectable": State.SELECTABLE,
	"checked": State.CHECKED,
	"pressed": State.PRESSED,
	"expanded": State.EXPANDED,
	"collapsed": State.COLLAPSED,
	"busy": State.BUSY,
	"modal": State.MODAL,
	"multi line": State.MULTILINE,
	"editable": State.EDITABLE,
	"iconified": State.ICONIFIED,
	"indeterminate": State.HALFCHECKED,
	"multiselectable": State.MULTISELECTABLE,
}


def parseStates(text: str) -> set[State]:
	"""Convierte la lista de estados en inglés de Java en estados de Tiresias."""
	parts = {p.strip().lower() for p in (text or "").split(",") if p.strip()}
	states = {st for key, st in _STATES.items() if key in parts}
	if "enabled" not in parts and parts:
		states.add(State.UNAVAILABLE)
	if "showing" not in parts and "visible" not in parts and parts:
		states.add(State.INVISIBLE)
	if "expandable" in parts and State.EXPANDED not in states:
		states.add(State.COLLAPSED)
	return states


def mapRole(roleEn: str) -> Role:
	return _ROLES.get((roleEn or "").strip().lower(), Role.UNKNOWN)


class JABObject(AccObject):
	"""Objeto de una aplicación Java (Java Access Bridge)."""

	def __init__(self, vmID: int, context: int, windowHandle: int = 0) -> None:
		super().__init__()
		self.vmID = int(vmID)
		self.context = int(context)
		self._windowHandle = int(windowHandle or 0)
		self._infoCache: tuple[int, jab.AccessibleContextInfo | None] | None = None

	def __del__(self) -> None:
		try:
			if jab.bridge is not None and self.context:
				# El recolector puede ejecutarse en cualquier hilo: se suelta en el núcleo.
				jab.releaseObject(self.vmID, self.context)
		except Exception:
			pass

	# ----------------------------------------------------- creación
	@classmethod
	def fromContext(cls, vmID: int, context: int, windowHandle: int = 0) -> "JABObject | None":
		if jab.bridge is None or not context:
			return None
		try:
			obj = cls(vmID, context, windowHandle)
			if obj.info is None:
				return None
			obj._applyOverlays()
		except Exception:
			log.debug("No se pudo crear el objeto Java", exc_info=True)
			return None
		from ..a11y import system

		return system.filterSecure(obj)

	@classmethod
	def fromWindow(cls, hwnd: int) -> "JABObject | None":
		if jab.bridge is None:
			return None
		vm = jab.vmID_t()
		ac = jab.JOBJECT64()
		if not jab.bridge.getAccessibleContextFromHWND(hwnd, ctypes.byref(vm), ctypes.byref(ac)):
			return None
		return cls.fromContext(vm.value, ac.value, hwnd)

	@classmethod
	def fromFocusedWindow(cls, hwnd: int) -> "JABObject | None":
		if jab.bridge is None:
			return None
		vm = jab.vmID_t()
		ac = jab.JOBJECT64()
		if not jab.bridge.getAccessibleContextWithFocus(hwnd, ctypes.byref(vm), ctypes.byref(ac)):
			return cls.fromWindow(hwnd)
		return cls.fromContext(vm.value, ac.value)

	# ----------------------------------------------------- información
	@property
	def info(self) -> "jab.AccessibleContextInfo | None":
		cached = self._infoCache
		if cached is not None and cached[0] == baseobject._cacheGeneration:
			return cached[1]
		info = jab.AccessibleContextInfo()
		try:
			ok = bool(jab.bridge.getAccessibleContextInfo(self.vmID, self.context, ctypes.byref(info)))
		except (OSError, AttributeError):
			ok = False
		result = info if ok else None
		self._infoCache = (baseobject._cacheGeneration, result)
		return result

	def isSameAs(self, other: AccObject) -> bool:
		if not isinstance(other, JABObject) or other.vmID != self.vmID:
			return False
		try:
			return bool(jab.bridge.isSameObject(self.vmID, self.context, other.context))
		except (OSError, AttributeError):
			return False

	def __hash__(self) -> int:
		return hash((self.vmID, self.windowHandle))

	def _get_name(self) -> str:
		info = self.info
		name = info.name if info else ""
		if not name and jab.bridge is not None:
			buf = ctypes.create_unicode_buffer(jab.MAX_STRING_SIZE)
			try:
				if jab.bridge.getVirtualAccessibleName(self.vmID, self.context, buf, jab.MAX_STRING_SIZE):
					name = buf.value
			except OSError:
				pass
		return (name or "").strip()

	def _get_JABRole(self) -> str:
		info = self.info
		return info.role_en_US if info else ""

	def _get_JABStates(self) -> str:
		info = self.info
		return info.states_en_US if info else ""

	def _get_role(self) -> Role:
		role = mapRole(self.JABRole)
		if role == Role.EDITABLETEXT and "editable" not in self.JABStates.lower() and self.info and not self.info.accessibleText:
			return Role.STATICTEXT
		return role

	def _get_roleText(self) -> str | None:
		if self.role == Role.UNKNOWN:
			info = self.info
			return info.role if info and info.role else None
		return None

	def _get_states(self) -> set[State]:
		states = parseStates(self.JABStates)
		if self.role in (Role.CHECKBOX, Role.RADIOBUTTON, Role.TOGGLEBUTTON):
			states.add(State.CHECKABLE)
			if self.role == Role.TOGGLEBUTTON and State.CHECKED in states:
				states.discard(State.CHECKED)
				states.add(State.PRESSED)
		return states

	def _get_value(self) -> str:
		info = self.info
		if info is None or not (info.accessibleInterfaces & jab.INTERFACE_VALUE):
			return ""
		buf = ctypes.create_unicode_buffer(jab.SHORT_STRING_SIZE)
		try:
			if jab.bridge.getCurrentAccessibleValueFromContext(self.vmID, self.context, buf, jab.SHORT_STRING_SIZE):
				return buf.value
		except OSError:
			pass
		return ""

	def _get_description(self) -> str:
		info = self.info
		desc = info.description if info else ""
		return "" if desc == self.name else desc

	def _get_location(self) -> tuple[int, int, int, int] | None:
		info = self.info
		if info is None or (info.width <= 0 and info.height <= 0):
			return None
		return (info.x, info.y, info.width, info.height)

	def _get_positionInfo(self) -> dict[str, int]:
		info = self.info
		if info is None or self.role not in (Role.LISTITEM, Role.TAB, Role.MENUITEM, Role.RADIOBUTTON, Role.TREEVIEWITEM):
			return {}
		parent = self.parent
		count = parent.info.childrenCount if isinstance(parent, JABObject) and parent.info else 0
		if count > 0 and info.indexInParent >= 0:
			return {"indexInGroup": info.indexInParent + 1, "similarItemsInGroup": count}
		return {}

	def _get_windowHandle(self) -> int:
		if self._windowHandle:
			return self._windowHandle
		hwnd = 0
		try:
			top = jab.bridge.getTopLevelObject(self.vmID, self.context)
			if top:
				hwnd = jab.bridge.getHWNDFromAccessibleContext(self.vmID, top) or 0
				jab.bridge.releaseJavaObject(self.vmID, top)
		except (OSError, AttributeError):
			hwnd = 0
		self._windowHandle = int(hwnd)
		return self._windowHandle

	# ----------------------------------------------------- navegación
	def _get_parent(self) -> AccObject | None:
		from .. import api
		from ..a11y import system

		try:
			ctx = jab.bridge.getAccessibleParentFromContext(self.vmID, self.context)
		except (OSError, AttributeError):
			ctx = 0
		if ctx:
			return system.filterSecure(JABObject.fromContext(self.vmID, ctx, self._windowHandle))
		return api.getDesktopObject()

	def _get_children(self) -> list[AccObject]:
		info = self.info
		if info is None:
			return []
		out: list[AccObject] = []
		for i in range(min(info.childrenCount, 1000)):
			try:
				ctx = jab.bridge.getAccessibleChildFromContext(self.vmID, self.context, i)
			except (OSError, AttributeError):
				break
			obj = JABObject.fromContext(self.vmID, ctx, self._windowHandle) if ctx else None
			if obj is not None:
				out.append(obj)
		return out

	def _get_childCount(self) -> int:
		info = self.info
		return info.childrenCount if info else 0

	def _childOf(self, context: int, index: int) -> AccObject | None:
		"""Hijo ``index`` de ``context`` (como ``_get_children``: el puente puede
		haberse descargado o fallar con la aplicación Java cerrándose)."""
		try:
			ctx = jab.bridge.getAccessibleChildFromContext(self.vmID, context, index)
		except (OSError, AttributeError):
			return None
		return JABObject.fromContext(self.vmID, ctx, self._windowHandle) if ctx else None

	def _get_firstChild(self) -> AccObject | None:
		info = self.info
		if info is None or info.childrenCount <= 0:
			return None
		return self._childOf(self.context, 0)

	def _get_lastChild(self) -> AccObject | None:
		info = self.info
		if info is None or info.childrenCount <= 0:
			return None
		return self._childOf(self.context, info.childrenCount - 1)

	def _sibling(self, direction: int) -> AccObject | None:
		info = self.info
		parent = self.parent
		if info is None or not isinstance(parent, JABObject) or parent.info is None:
			return None
		index = info.indexInParent + direction
		if not 0 <= index < parent.info.childrenCount:
			return None
		return self._childOf(parent.context, index)

	def _get_next(self) -> AccObject | None:
		return self._sibling(1)

	def _get_previous(self) -> AccObject | None:
		return self._sibling(-1)

	# ----------------------------------------------------- acciones
	def setFocus(self) -> None:
		try:
			jab.bridge.requestFocus(self.vmID, self.context)
		except (OSError, AttributeError):
			pass

	def _actions(self) -> list[str]:
		acts = jab.AccessibleActions()
		try:
			if not jab.bridge.getAccessibleActions(self.vmID, self.context, ctypes.byref(acts)):
				return []
		except (OSError, AttributeError):
			return []
		return [acts.actionInfo[i].name for i in range(min(acts.actionsCount, jab.MAX_ACTION_INFO))]

	def _get_actionName(self) -> str:
		acts = self._actions()
		return acts[0] if acts else _("hacer clic")

	def doAction(self, index: int = 0) -> bool:
		acts = self._actions()
		if 0 <= index < len(acts):
			todo = jab.AccessibleActionsToDo()
			todo.actionsCount = 1
			todo.actions[0].name = acts[index]
			failure = jab.jint()
			try:
				if jab.bridge.doAccessibleActions(self.vmID, self.context, ctypes.byref(todo), ctypes.byref(failure)):
					return True
			except OSError:
				pass
		loc = self.location
		if not loc:
			return False
		from .. import mouse

		x, y, w, h = loc
		mouse.click(x + w // 2, y + h // 2)
		return True

	# ----------------------------------------------------- texto
	def _get_TextInfo(self):
		info = self.info
		if info is not None and info.accessibleText and self.role in (Role.EDITABLETEXT, Role.PASSWORDEDIT, Role.PARAGRAPH, Role.STATICTEXT, Role.DOCUMENT):
			return JABTextInfo
		return None

	def findOverlayClasses(self, clsList: list[type]) -> None:
		from . import behaviors

		role = self.role
		if self.TextInfo is not None and role in (Role.EDITABLETEXT, Role.PASSWORDEDIT):
			clsList.append(behaviors.EditableTextWithCaret)
		elif role in (Role.EDITABLETEXT, Role.PASSWORDEDIT):
			clsList.append(behaviors.EditableTextNoCaret)
		if role == Role.PROGRESSBAR:
			clsList.append(behaviors.ProgressBar)
		if role == Role.DIALOG:
			clsList.append(behaviors.Dialog)
		if role in (Role.LISTITEM, Role.TREEVIEWITEM):
			clsList.append(behaviors.SelectableItem)
		if role in (Role.LIST, Role.TREEVIEW, Role.TABLE):
			clsList.append(behaviors.ListContainer)

	def _get_devInfo(self) -> list[str]:
		info = super()._get_devInfo()
		info.append(f"Java vmID: {self.vmID}")
		info.append(f"Java role: {self.JABRole!r}")
		info.append(f"Java states: {self.JABStates!r}")
		return info


class JABTextInfo(textinfo.Utf16OffsetsTextInfo):
	"""Texto de un componente Java con ``AccessibleText``.

	Java cuenta en unidades UTF-16: los desplazamientos se convierten (rev. 10.11, C2).
	"""

	def _textInfo(self) -> "jab.AccessibleTextInfo | None":
		info = jab.AccessibleTextInfo()
		try:
			if jab.bridge.getAccessibleTextInfo(self.obj.vmID, self.obj.context, ctypes.byref(info), 0, 0):
				return info
		except (OSError, AttributeError):
			pass
		return None

	def _getStoryText(self) -> str:
		info = self._textInfo()
		if info is None or info.charCount <= 0:
			return ""
		out: list[str] = []
		start = 0
		chunk = 8000
		total = min(info.charCount, 2_000_000)
		while start < total:
			end = min(total, start + chunk) - 1
			buf = ctypes.create_unicode_buffer(end - start + 2)
			try:
				if not jab.bridge.getAccessibleTextRange(self.obj.vmID, self.obj.context, start, end, buf, end - start + 2):
					break
			except OSError:
				break
			out.append(buf.value)
			start = end + 1
		return "".join(out)

	def _getCaretOffset(self) -> int:
		info = self._textInfo()
		return self._toStr(max(0, info.caretIndex)) if info else 0

	def _setCaretOffset(self, offset: int) -> None:
		try:
			jab.bridge.setCaretPosition(self.obj.vmID, self.obj.context, self._toUtf16(offset))
		except (OSError, AttributeError):
			pass

	def _getSelectionOffsets(self) -> tuple[int, int]:
		sel = jab.AccessibleTextSelectionInfo()
		try:
			if jab.bridge.getAccessibleTextSelectionInfo(self.obj.vmID, self.obj.context, ctypes.byref(sel)):
				start, end = sel.selectionStartIndex, sel.selectionEndIndex
				if 0 <= start < end:
					return self._toStr(start), self._toStr(end)
		except (OSError, AttributeError):
			pass
		o = self._getCaretOffset()
		return o, o

	def _setSelectionOffsets(self, start: int, end: int) -> None:
		try:
			jab.bridge.selectTextRange(self.obj.vmID, self.obj.context, self._toUtf16(start), self._toUtf16(end))
		except (OSError, AttributeError):
			pass

	def _unitBoundaries(self, unit: str, offset: int) -> tuple[int, int]:
		if unit == textinfo.UNIT_LINE:
			start = jab.jint()
			end = jab.jint()
			try:
				if jab.bridge.getAccessibleTextLineBounds(self.obj.vmID, self.obj.context, self._toUtf16(offset), ctypes.byref(start), ctypes.byref(end)):
					s, e = self._toStr(start.value), self._toStr(end.value + 1)
					n = len(self._story())
					if 0 <= s <= offset < e <= n + 1:
						return s, min(e, n)
			except (OSError, AttributeError):
				pass
		return super()._unitBoundaries(unit, offset)

	@property
	def boundingRects(self) -> list[tuple[int, int, int, int]]:
		rect = jab.AccessibleTextRectInfo()
		try:
			if jab.bridge.getAccessibleTextRect(self.obj.vmID, self.obj.context, ctypes.byref(rect), self._toUtf16(self._start)):
				return [(rect.x, rect.y, rect.width, rect.height)]
		except (OSError, AttributeError):
			pass
		return []
