"""Objetos accesibles basados en MSAA (IAccessible) e IAccessible2.

:class:`IAccessibleObject` representa un objeto MSAA identificado por un
puntero ``IAccessible`` y un identificador de hijo (``childId``; 0 es el propio
objeto). Si la aplicación implementa IAccessible2 (LibreOffice, Qt, Firefox,
Thunderbird…) se usan además sus roles, estados, atributos, posición en el
grupo y su interfaz de texto (:class:`IA2TextInfo`).

Para los campos de edición Win32 (``Edit``, ``RichEdit`` y derivados) el texto,
el cursor y las líneas se leen con mensajes de ventana
(:class:`EditWindowTextInfo`).

La navegación es mixta: al subir desde un objeto MSAA hasta una ventana que se
lee con UI Automation se devuelve el objeto UIA de esa ventana, y al revés
(ver ``UIAObject._wrap``).
"""

from __future__ import annotations

from typing import Any

import comtypes

from .. import baseobject, textinfo
from ..a11y import msaa, win32ctl
from ..i18n import _
from ..log import getLogger
from .base import AccObject, looksLikeTypeName
from .roles import Role, State

log = getLogger("iaccessible")

_MSAA_ROLES = {
	msaa.ROLE_TITLEBAR: Role.TITLEBAR,
	msaa.ROLE_MENUBAR: Role.MENUBAR,
	msaa.ROLE_SCROLLBAR: Role.SCROLLBAR,
	msaa.ROLE_GRIP: Role.GRIP,
	msaa.ROLE_SOUND: Role.SOUND,
	msaa.ROLE_CURSOR: Role.CURSOR,
	msaa.ROLE_CARET: Role.CARET,
	msaa.ROLE_ALERT: Role.ALERT,
	msaa.ROLE_WINDOW: Role.WINDOW,
	msaa.ROLE_CLIENT: Role.PANE,
	msaa.ROLE_MENUPOPUP: Role.POPUPMENU,
	msaa.ROLE_MENUITEM: Role.MENUITEM,
	msaa.ROLE_TOOLTIP: Role.TOOLTIP,
	msaa.ROLE_APPLICATION: Role.APPLICATION,
	msaa.ROLE_DOCUMENT: Role.DOCUMENT,
	msaa.ROLE_PANE: Role.PANE,
	msaa.ROLE_CHART: Role.CHART,
	msaa.ROLE_DIALOG: Role.DIALOG,
	msaa.ROLE_BORDER: Role.BORDER,
	msaa.ROLE_GROUPING: Role.GROUPING,
	msaa.ROLE_SEPARATOR: Role.SEPARATOR,
	msaa.ROLE_TOOLBAR: Role.TOOLBAR,
	msaa.ROLE_STATUSBAR: Role.STATUSBAR,
	msaa.ROLE_TABLE: Role.TABLE,
	msaa.ROLE_COLUMNHEADER: Role.TABLECOLUMNHEADER,
	msaa.ROLE_ROWHEADER: Role.TABLEROWHEADER,
	msaa.ROLE_COLUMN: Role.TABLECOLUMN,
	msaa.ROLE_ROW: Role.TABLEROW,
	msaa.ROLE_CELL: Role.TABLECELL,
	msaa.ROLE_LINK: Role.LINK,
	msaa.ROLE_HELPBALLOON: Role.HELPBALLOON,
	msaa.ROLE_CHARACTER: Role.CHARACTER,
	msaa.ROLE_LIST: Role.LIST,
	msaa.ROLE_LISTITEM: Role.LISTITEM,
	msaa.ROLE_OUTLINE: Role.TREEVIEW,
	msaa.ROLE_OUTLINEITEM: Role.TREEVIEWITEM,
	msaa.ROLE_PAGETAB: Role.TAB,
	msaa.ROLE_PROPERTYPAGE: Role.PROPERTYPAGE,
	msaa.ROLE_INDICATOR: Role.INDICATOR,
	msaa.ROLE_GRAPHIC: Role.GRAPHIC,
	msaa.ROLE_STATICTEXT: Role.STATICTEXT,
	msaa.ROLE_TEXT: Role.EDITABLETEXT,
	msaa.ROLE_PUSHBUTTON: Role.BUTTON,
	msaa.ROLE_CHECKBUTTON: Role.CHECKBOX,
	msaa.ROLE_RADIOBUTTON: Role.RADIOBUTTON,
	msaa.ROLE_COMBOBOX: Role.COMBOBOX,
	msaa.ROLE_DROPLIST: Role.DROPLIST,
	msaa.ROLE_PROGRESSBAR: Role.PROGRESSBAR,
	msaa.ROLE_DIAL: Role.DIAL,
	msaa.ROLE_HOTKEYFIELD: Role.HOTKEYFIELD,
	msaa.ROLE_SLIDER: Role.SLIDER,
	msaa.ROLE_SPINBUTTON: Role.SPINBUTTON,
	msaa.ROLE_DIAGRAM: Role.DIAGRAM,
	msaa.ROLE_ANIMATION: Role.ANIMATION,
	msaa.ROLE_EQUATION: Role.EQUATION,
	msaa.ROLE_BUTTONDROPDOWN: Role.DROPDOWNBUTTON,
	msaa.ROLE_BUTTONMENU: Role.MENUBUTTON,
	msaa.ROLE_BUTTONDROPDOWNGRID: Role.DROPDOWNBUTTONGRID,
	msaa.ROLE_WHITESPACE: Role.WHITESPACE,
	msaa.ROLE_PAGETABLIST: Role.TABCONTROL,
	msaa.ROLE_CLOCK: Role.CLOCK,
	msaa.ROLE_SPLITBUTTON: Role.SPLITBUTTON,
	msaa.ROLE_IPADDRESS: Role.IPADDRESS,
	msaa.ROLE_OUTLINEBUTTON: Role.TREEVIEWBUTTON,
}

_IA2_ROLES = {
	msaa.IA2_ROLE_CANVAS: Role.CANVAS,
	msaa.IA2_ROLE_CAPTION: Role.CAPTION,
	msaa.IA2_ROLE_CHECK_MENU_ITEM: Role.CHECKMENUITEM,
	msaa.IA2_ROLE_COLOR_CHOOSER: Role.COLORCHOOSER,
	msaa.IA2_ROLE_DATE_EDITOR: Role.DATEEDITOR,
	msaa.IA2_ROLE_DESKTOP_ICON: Role.DESKTOPICON,
	msaa.IA2_ROLE_DESKTOP_PANE: Role.DESKTOPPANE,
	msaa.IA2_ROLE_DIRECTORY_PANE: Role.DIRECTORYPANE,
	msaa.IA2_ROLE_EDITBAR: Role.EDITBAR,
	msaa.IA2_ROLE_EMBEDDED_OBJECT: Role.EMBEDDEDOBJECT,
	msaa.IA2_ROLE_ENDNOTE: Role.ENDNOTE,
	msaa.IA2_ROLE_FILE_CHOOSER: Role.FILECHOOSER,
	msaa.IA2_ROLE_FONT_CHOOSER: Role.FONTCHOOSER,
	msaa.IA2_ROLE_FOOTER: Role.FOOTER,
	msaa.IA2_ROLE_FOOTNOTE: Role.FOOTNOTE,
	msaa.IA2_ROLE_FORM: Role.FORM,
	msaa.IA2_ROLE_FRAME: Role.FRAME,
	msaa.IA2_ROLE_GLASS_PANE: Role.GLASSPANE,
	msaa.IA2_ROLE_HEADER: Role.HEADER,
	msaa.IA2_ROLE_HEADING: Role.HEADING,
	msaa.IA2_ROLE_ICON: Role.ICON,
	msaa.IA2_ROLE_IMAGE_MAP: Role.IMAGEMAP,
	msaa.IA2_ROLE_INPUT_METHOD_WINDOW: Role.INPUTWINDOW,
	msaa.IA2_ROLE_INTERNAL_FRAME: Role.INTERNALFRAME,
	msaa.IA2_ROLE_LABEL: Role.LABEL,
	msaa.IA2_ROLE_LAYERED_PANE: Role.LAYEREDPANE,
	msaa.IA2_ROLE_NOTE: Role.NOTE,
	msaa.IA2_ROLE_OPTION_PANE: Role.OPTIONPANE,
	msaa.IA2_ROLE_PAGE: Role.PAGE,
	msaa.IA2_ROLE_PARAGRAPH: Role.PARAGRAPH,
	msaa.IA2_ROLE_RADIO_MENU_ITEM: Role.RADIOMENUITEM,
	msaa.IA2_ROLE_REDUNDANT_OBJECT: Role.REDUNDANTOBJECT,
	msaa.IA2_ROLE_ROOT_PANE: Role.ROOTPANE,
	msaa.IA2_ROLE_RULER: Role.RULER,
	msaa.IA2_ROLE_SCROLL_PANE: Role.SCROLLPANE,
	msaa.IA2_ROLE_SECTION: Role.SECTION,
	msaa.IA2_ROLE_SHAPE: Role.SHAPE,
	msaa.IA2_ROLE_SPLIT_PANE: Role.SPLITPANE,
	msaa.IA2_ROLE_TEAR_OFF_MENU: Role.TEAROFFMENU,
	msaa.IA2_ROLE_TERMINAL: Role.TERMINAL,
	msaa.IA2_ROLE_TEXT_FRAME: Role.TEXTFRAME,
	msaa.IA2_ROLE_TOGGLE_BUTTON: Role.TOGGLEBUTTON,
	msaa.IA2_ROLE_VIEW_PORT: Role.VIEWPORT,
	msaa.IA2_ROLE_COMPLEMENTARY_CONTENT: Role.LANDMARK,
	msaa.IA2_ROLE_LANDMARK: Role.LANDMARK,
	msaa.IA2_ROLE_LEVEL_BAR: Role.PROGRESSBAR,
	msaa.IA2_ROLE_CONTENT_DELETION: Role.DELETED_CONTENT,
	msaa.IA2_ROLE_CONTENT_INSERTION: Role.INSERTED_CONTENT,
	msaa.IA2_ROLE_BLOCK_QUOTE: Role.BLOCKQUOTE,
	msaa.IA2_ROLE_MARK: Role.MARKED_CONTENT,
	msaa.IA2_ROLE_SUGGESTION: Role.SUGGESTION,
	msaa.IA2_ROLE_COMMENT: Role.COMMENT,
}

_MSAA_STATES = {
	msaa.STATE_UNAVAILABLE: State.UNAVAILABLE,
	msaa.STATE_SELECTED: State.SELECTED,
	msaa.STATE_FOCUSED: State.FOCUSED,
	msaa.STATE_PRESSED: State.PRESSED,
	msaa.STATE_CHECKED: State.CHECKED,
	msaa.STATE_MIXED: State.HALFCHECKED,
	msaa.STATE_READONLY: State.READONLY,
	msaa.STATE_EXPANDED: State.EXPANDED,
	msaa.STATE_COLLAPSED: State.COLLAPSED,
	msaa.STATE_BUSY: State.BUSY,
	msaa.STATE_INVISIBLE: State.INVISIBLE,
	msaa.STATE_OFFSCREEN: State.OFFSCREEN,
	msaa.STATE_FOCUSABLE: State.FOCUSABLE,
	msaa.STATE_SELECTABLE: State.SELECTABLE,
	msaa.STATE_LINKED: State.LINKED,
	msaa.STATE_TRAVERSED: State.VISITED,
	msaa.STATE_MULTISELECTABLE: State.MULTISELECTABLE,
	msaa.STATE_PROTECTED: State.PROTECTED,
	msaa.STATE_HASPOPUP: State.HASPOPUP,
}

_IA2_STATES = {
	msaa.IA2_STATE_DEFUNCT: State.DEFUNCT,
	msaa.IA2_STATE_EDITABLE: State.EDITABLE,
	msaa.IA2_STATE_ICONIFIED: State.ICONIFIED,
	msaa.IA2_STATE_INVALID_ENTRY: State.INVALID_ENTRY,
	msaa.IA2_STATE_MODAL: State.MODAL,
	msaa.IA2_STATE_MULTI_LINE: State.MULTILINE,
	msaa.IA2_STATE_REQUIRED: State.REQUIRED,
	msaa.IA2_STATE_SUPPORTS_AUTOCOMPLETION: State.AUTOCOMPLETE,
	msaa.IA2_STATE_CHECKABLE: State.CHECKABLE,
	msaa.IA2_STATE_PINNED: State.PINNED,
}

#: Roles ARIA (atributo IA2 ``xml-roles``) que precisan el rol.
_XML_ROLES = {
	"switch": Role.SWITCH,
	"article": Role.ARTICLE,
	"figure": Role.FIGURE,
	"region": Role.REGION,
	"banner": Role.LANDMARK,
	"navigation": Role.LANDMARK,
	"main": Role.LANDMARK,
	"contentinfo": Role.LANDMARK,
	"complementary": Role.LANDMARK,
	"search": Role.LANDMARK,
	"form": Role.LANDMARK,
}

_LANDMARK_NAMES = {
	"banner": _("cabecera"),
	"navigation": _("navegación"),
	"main": _("principal"),
	"contentinfo": _("información de contenido"),
	"complementary": _("complementario"),
	"search": _("búsqueda"),
	"form": _("formulario"),
	"region": _("región"),
}


def _safe(func, default=None):
	try:
		val = func()
	except (comtypes.COMError, OSError, ValueError, AttributeError, TypeError):
		return default
	return default if val is None else val


class IAccessibleObject(AccObject):
	"""Objeto accesible respaldado por ``IAccessible`` (MSAA) y, si existe, IAccessible2."""

	def __init__(self, pacc, childId: int = 0, windowHandle: int = 0, objectId: int | None = None) -> None:
		super().__init__()
		self.IAccessibleObject = pacc
		self.IAccessibleChildID = int(childId or 0)
		self._windowHandle = int(windowHandle or 0)
		#: Identificador de objeto MSAA si se creó desde una ventana o un evento.
		self.objectId = objectId
		self._ia2Cache: Any = False

	# ----------------------------------------------------- creación
	@classmethod
	def fromIAccessible(cls, pacc, childId: int = 0, windowHandle: int = 0, objectId: int | None = None) -> "IAccessibleObject | None":
		if pacc is None:
			return None
		try:
			obj = cls(pacc, childId, windowHandle, objectId)
			obj._applyOverlays()
		except (comtypes.COMError, OSError):
			# OSError: ventana propia con la interfaz ocupada (own_windows.GuiBusyError).
			return None
		except Exception:
			log.exception("No se pudo crear el objeto MSAA")
			return None
		from ..a11y import system

		if system.isSecureObject(obj):
			return None
		return obj

	@classmethod
	def fromWindow(cls, hwnd: int, objectId: int = msaa.OBJID_CLIENT) -> "IAccessibleObject | None":
		pacc = msaa.accessibleObjectFromWindow(hwnd, objectId)
		if pacc is None:
			return None
		return cls.fromIAccessible(pacc, 0, hwnd, objectId)

	@classmethod
	def fromEvent(cls, hwnd: int, objectId: int, childId: int) -> "IAccessibleObject | None":
		res = msaa.accessibleObjectFromEvent(hwnd, objectId, childId)
		if res is None:
			return None
		pacc, child = res
		# ``objectId`` solo identifica al objeto si el evento es del propio objeto
		# (``childId`` del evento = 0). Si el evento es de un hijo que resulta ser
		# un objeto completo (los elementos con submenú de un menú), ese hijo no
		# es «el objeto cliente de la ventana»: con ``objectId`` todos los
		# elementos con submenú parecían el mismo y no se anunciaban (#menú).
		obj = cls.fromIAccessible(pacc, child, hwnd, objectId if childId == 0 and child == 0 else None)
		return obj

	@classmethod
	def fromFocusedWindow(cls, hwnd: int) -> "IAccessibleObject | None":
		"""Objeto con el foco dentro de ``hwnd`` (baja por ``accFocus``)."""
		obj = cls.fromWindow(hwnd)
		guard = 0
		while obj is not None and guard < 20:
			guard += 1
			inner = obj._focusedDescendant()
			if inner is None or inner == obj:
				break
			obj = inner
		return obj

	def _focusedDescendant(self) -> "IAccessibleObject | None":
		if self.IAccessibleChildID:
			return None
		val = _safe(lambda: self.IAccessibleObject.accFocus)
		if val is None:
			return None
		if isinstance(val, int):
			if val == 0:
				return None
			return IAccessibleObject.fromIAccessible(self.IAccessibleObject, val, self.windowHandle)
		pacc = msaa.normalizeIAccessible(val)
		if pacc is None:
			return None
		return IAccessibleObject.fromIAccessible(pacc, 0, msaa.windowFromAccessibleObject(pacc))

	def _wrapAccessible(self, pacc, childId: int = 0) -> "AccObject | None":
		"""Crea el objeto adecuado para ``pacc`` (MSAA o el de la API de su ventana)."""
		if pacc is None:
			return None
		hwnd = msaa.windowFromAccessibleObject(pacc) if childId == 0 else self.windowHandle
		if hwnd and msaa.isDesktopWindow(hwnd):
			from .. import api

			return api.getDesktopObject()
		if childId == 0 and hwnd and hwnd != self.windowHandle:
			from ..a11y import api_choice

			choice = api_choice.chooseAPI(hwnd)
			if choice != api_choice.API_MSAA:
				return _objectForWindow(hwnd, choice)
			if _safe(lambda: pacc.accRole(0), 0) == msaa.ROLE_WINDOW:
				# Los hijos de un cliente son los objetos «ventana» de las
				# subventanas: como al subir (_get_parent), se usa su cliente,
				# que es el control de verdad (botón, campo, texto...).
				client = msaa.accessibleObjectFromWindow(hwnd, msaa.OBJID_CLIENT)
				if client is not None:
					return IAccessibleObject.fromIAccessible(client, 0, hwnd, msaa.OBJID_CLIENT)
		return IAccessibleObject.fromIAccessible(pacc, childId, hwnd)

	# ----------------------------------------------------- IA2
	@property
	def IA2(self):
		if self._ia2Cache is False:
			self._ia2Cache = None if self.IAccessibleChildID else msaa.queryIAccessible2(self.IAccessibleObject)
		return self._ia2Cache

	def _get_IA2Attributes(self) -> dict[str, str]:
		ia2 = self.IA2
		if ia2 is None:
			return {}
		return msaa.parseIA2Attributes(_safe(lambda: ia2.attributes, ""))

	def _get_IA2States(self) -> int:
		ia2 = self.IA2
		return int(_safe(lambda: ia2.states, 0)) if ia2 is not None else 0

	def _get_IAccessibleRole(self) -> Any:
		ia2 = self.IA2
		if ia2 is not None:
			r = _safe(lambda: ia2.role(), None)
			if r:
				return int(r)
		return _safe(lambda: self.IAccessibleObject.accRole(self.IAccessibleChildID), 0)

	def _get_IAccessibleStates(self) -> int:
		val = _safe(lambda: self.IAccessibleObject.accState(self.IAccessibleChildID), 0)
		try:
			return int(val)
		except (TypeError, ValueError):
			return 0

	# ----------------------------------------------------- identidad
	def _identity(self):
		pacc = self.IAccessibleObject
		if isinstance(pacc, msaa.own_windows.OwnAccessible):
			return pacc.addr
		try:
			unk = self.IAccessibleObject.QueryInterface(comtypes.IUnknown)
			return ctypes_addr(unk)
		except (comtypes.COMError, ValueError, AttributeError):
			return None

	def isSameAs(self, other: AccObject) -> bool:
		if not isinstance(other, IAccessibleObject):
			return False
		if self.IAccessibleChildID != other.IAccessibleChildID:
			return False
		if self.IA2 is not None and other.IA2 is not None:
			idA = self.IA2UniqueID
			idB = other.IA2UniqueID
			if idA is not None and idB is not None:
				return idA == idB and self.windowHandle == other.windowHandle
		ia, ib = self._identity(), other._identity()
		if ia is not None and ib is not None:
			if ia == ib:
				return True
		if self.windowHandle != other.windowHandle:
			return False
		if self.objectId is not None and self.objectId == other.objectId and self.IAccessibleChildID == 0:
			return True
		try:
			return self.IAccessibleRole == other.IAccessibleRole and self.name == other.name and self.location == other.location
		except Exception:
			return False

	def __hash__(self) -> int:
		# Con IAccessible2 casi todos los objetos comparten ventana y childId 0:
		# sin el uniqueID, los diccionarios (estados recordados...) degeneraban en
		# búsquedas lineales con llamadas entre procesos en cada comparación.
		uid = self.IA2UniqueID if self.IA2 is not None else None
		return hash((self.windowHandle, self.IAccessibleChildID, uid))

	@property
	def IA2UniqueID(self) -> int | None:
		"""``IAccessible2::uniqueID`` (se pide una sola vez por objeto)."""
		cached = self.__dict__.get("_uniqueIdCache", False)
		if cached is not False:
			return cached
		ia2 = self.IA2
		uid = _safe(lambda: ia2.uniqueID) if ia2 is not None else None
		try:
			uid = int(uid) if uid is not None else None
		except (TypeError, ValueError):
			uid = None
		self.__dict__["_uniqueIdCache"] = uid
		return uid

	# ----------------------------------------------------- propiedades
	def _get_name(self) -> str:
		name = _safe(lambda: self.IAccessibleObject.accName(self.IAccessibleChildID), "")
		if not isinstance(name, str):
			return ""
		if "\t" in name and self._isMenuItem():
			# Menús Win32: «Copiar\tCtrl+C». El atajo va aparte (keyboardShortcut).
			name = name.split("\t", 1)[0]
		return name.strip()

	def _isMenuItem(self) -> bool:
		return _safe(lambda: self.IAccessibleObject.accRole(self.IAccessibleChildID), 0) == msaa.ROLE_MENUITEM

	def _menuAccelerator(self) -> str:
		"""Atajo de un elemento de menú Win32 (el texto tras el tabulador del nombre)."""
		name = _safe(lambda: self.IAccessibleObject.accName(self.IAccessibleChildID), "")
		if not isinstance(name, str) or "\t" not in name or not self._isMenuItem():
			return ""
		return name.split("\t", 1)[1].strip()

	def _get_role(self) -> Role:
		raw = self.IAccessibleRole
		role = Role.UNKNOWN
		if isinstance(raw, int):
			role = _IA2_ROLES.get(raw) or _MSAA_ROLES.get(raw, Role.UNKNOWN)
		elif isinstance(raw, str):
			low = raw.lower()
			if "edit" in low or "text" in low:
				role = Role.EDITABLETEXT
			elif "button" in low:
				role = Role.BUTTON
		attrs = self.IA2Attributes
		xmlRole = (attrs.get("xml-roles") or "").split(" ")[0]
		if xmlRole in _XML_ROLES and role in (Role.SECTION, Role.GROUPING, Role.PANE, Role.UNKNOWN, Role.LANDMARK, Role.TOGGLEBUTTON, Role.CHECKBOX):
			if xmlRole != "region" or self.name:
				role = _XML_ROLES[xmlRole]
		if role == Role.HEADING:
			try:
				level = int(attrs.get("level", "0"))
			except ValueError:
				level = 0
			if 1 <= level <= 6:
				return Role(Role.HEADING1 + level - 1)
		if role == Role.EDITABLETEXT and self.IA2 is not None and not self.IA2States & msaa.IA2_STATE_EDITABLE:
			# En IAccessible2, ROLE_SYSTEM_TEXT sin el estado editable es texto normal.
			return Role.STATICTEXT
		if role == Role.EDITABLETEXT and self.IAccessibleStates & msaa.STATE_PROTECTED:
			return Role.PASSWORDEDIT
		if role == Role.PANE and self.windowClassName == "ConsoleWindowClass":
			return Role.TERMINAL
		if role == Role.MENUITEM and self.IAccessibleChildID and isinstance(self.IAccessibleObject, msaa.own_windows.OwnAccessible):
			return _ownMenuItemRole(self.windowHandle, self.IAccessibleChildID) or role
		return role

	def _get_roleText(self) -> str | None:
		if self.role == Role.LANDMARK:
			return self.landmark
		raw = self.IAccessibleRole
		if isinstance(raw, str) and raw:
			return raw
		ia2 = self.IA2
		if ia2 is not None and self.role in (Role.UNKNOWN, Role.CUSTOM):
			loc = _safe(lambda: ia2.localizedExtendedRole, "")
			if loc:
				return loc
		return None

	def _get_landmark(self) -> str | None:
		xmlRole = (self.IA2Attributes.get("xml-roles") or "").split(" ")[0]
		if xmlRole in _LANDMARK_NAMES:
			return _LANDMARK_NAMES[xmlRole]
		return None

	def _get_states(self) -> set[State]:
		states: set[State] = set()
		bits = self.IAccessibleStates
		for flag, st in _MSAA_STATES.items():
			if bits & flag:
				states.add(st)
		ia2bits = self.IA2States
		for flag, st in _IA2_STATES.items():
			if ia2bits & flag:
				states.add(st)
		role = self.role
		if role not in (Role.LIST, Role.TREEVIEW, Role.TABLE, Role.DATAGRID, Role.TABCONTROL):
			# Los proxies MSAA marcan también los elementos: solo cuenta en el contenedor.
			states.discard(State.MULTISELECTABLE)
		if role in (Role.EDITABLETEXT, Role.PASSWORDEDIT, Role.TERMINAL):
			if State.READONLY not in states:
				states.add(State.EDITABLE)
			if self.windowClassName and win32ctl.isEditClass(self.windowClassName) and not self.IAccessibleChildID:
				if win32ctl.getWindowStyle(self.windowHandle) & win32ctl.ES_MULTILINE:
					states.add(State.MULTILINE)
		if role in (Role.CHECKBOX, Role.RADIOBUTTON, Role.CHECKMENUITEM, Role.RADIOMENUITEM):
			states.add(State.CHECKABLE)
		if State.PRESSED in states and _isMomentaryPress(self, role):
			# Los botones Win32 marcan «pulsado» solo mientras se mantiene la tecla
			# Espacio o el ratón: con MSAA, al marcar una casilla se oía «pulsado»
			# y luego «marcado no pulsado» o «no pulsado no marcado» (las ventanas
			# propias se leen con MSAA desde la 1.0.2). NVDA tampoco lo dice.
			states.discard(State.PRESSED)
		if role == Role.TOGGLEBUTTON and bits & msaa.STATE_CHECKED:
			states.discard(State.CHECKED)
			states.add(State.PRESSED)
		attrs = self.IA2Attributes
		sort = attrs.get("sort")
		if sort == "ascending":
			states.add(State.SORTED_ASCENDING)
		elif sort == "descending":
			states.add(State.SORTED_DESCENDING)
		elif sort == "other":
			states.add(State.SORTED)
		if attrs.get("haspopup") not in (None, "", "false"):
			states.add(State.HASPOPUP)
		# aria-current se dice con su propio texto (ariaCurrent), no como «seleccionado».
		return states

	def _get_ariaCurrent(self) -> str:
		value = (self.IA2Attributes.get("current") or "").strip().lower()
		return "" if value == "false" else value

	def _get_value(self) -> str:
		role = self.role
		if role in (Role.LINK, Role.STATICTEXT, Role.TABLECELL, Role.PASSWORDEDIT, Role.DOCUMENT) or role in _HEADINGS:
			return ""
		val = _safe(lambda: self.IAccessibleObject.accValue(self.IAccessibleChildID), "")
		if not isinstance(val, str):
			val = str(val) if val is not None else ""
		if val == self.name:
			return ""
		return val

	def _get_description(self) -> str:
		desc = _safe(lambda: self.IAccessibleObject.accDescription(self.IAccessibleChildID), "")
		if not isinstance(desc, str) or desc == self.name:
			return ""
		if looksLikeTypeName(desc):
			# Nombre de tipo .NET (WinForms), no un texto para el usuario.
			return ""
		return desc

	def _get_helpText(self) -> str:
		val = _safe(lambda: self.IAccessibleObject.accHelp(self.IAccessibleChildID), "")
		return val if isinstance(val, str) else ""

	def _get_keyboardShortcut(self) -> str:
		val = _safe(lambda: self.IAccessibleObject.accKeyboardShortcut(self.IAccessibleChildID), "")
		val = val if isinstance(val, str) else ""
		accel = self._menuAccelerator()
		if accel and accel.lower() != val.lower():
			# Letra de acceso y atajo, como en UIA: «c Ctrl+C».
			return f"{val} {accel}".strip()
		return val

	def _get_placeholder(self) -> str:
		return self.IA2Attributes.get("placeholder", "")

	def _get_maxLength(self) -> int | None:
		val = self.IA2Attributes.get("maxlength")
		if val and val.isdigit():
			return int(val)
		if not self.IAccessibleChildID and win32ctl.isEditClass(self.windowClassName):
			limit = win32ctl.editLimitText(self.windowHandle)
			if limit and limit < 0x7FFFFFFE and limit not in (30000, 32767, 0xFFFFFFFF):
				return int(limit)
		return None

	def _get_language(self) -> str | None:
		"""Idioma del objeto (``IAccessible2::locale``; Firefox, Thunderbird…; foros 1.19)."""
		from ..a11y import ia2_bridge

		return ia2_bridge.getLocale(self.IA2)

	def _get_graphicFileName(self) -> str:
		"""Nombre del archivo de una imagen (atributo IA2 ``src``, #7412)."""
		from ..a11y import ia2_bridge

		return ia2_bridge.fileNameFromURL(self.IA2Attributes.get("src", ""))

	def _get_brailleLabel(self) -> str:
		"""``aria-braillelabel`` (#11829)."""
		return self.IA2Attributes.get("braillelabel", "")

	def _get_brailleRoleText(self) -> str:
		"""``aria-brailleroledescription`` (#11829)."""
		return self.IA2Attributes.get("brailleroledescription", "")

	def _get_location(self) -> tuple[int, int, int, int] | None:
		loc = _safe(lambda: self.IAccessibleObject.accLocation(self.IAccessibleChildID))
		if not loc or len(loc) < 4:
			return None
		x, y, w, h = (int(v) for v in loc[:4])
		if w <= 0 and h <= 0:
			return None
		return (x, y, w, h)

	def _get_level(self) -> int | None:
		lvl = self.IA2Attributes.get("level")
		if lvl and lvl.isdigit():
			return int(lvl)
		ia2 = self.IA2
		if ia2 is not None:
			pos = _safe(lambda: ia2.groupPosition)
			if pos and pos[0]:
				return int(pos[0])
		return None

	def _get_positionInfo(self) -> dict[str, int]:
		info: dict[str, int] = {}
		ia2 = self.IA2
		if ia2 is not None:
			pos = _safe(lambda: ia2.groupPosition)
			if pos:
				level, similar, index = (int(v or 0) for v in pos)
				if index > 0 and similar > 0:
					info["indexInGroup"] = index
					info["similarItemsInGroup"] = similar
				if level > 0:
					info["level"] = level
		attrs = self.IA2Attributes
		if "indexInGroup" not in info and attrs.get("posinset", "").isdigit() and attrs.get("setsize", "").isdigit():
			info["indexInGroup"] = int(attrs["posinset"])
			info["similarItemsInGroup"] = int(attrs["setsize"])
		if "indexInGroup" not in info and ia2 is None:
			info.update(self._siblingPosition())
		return info

	def _siblingPosition(self) -> dict[str, int]:
		"""Posición entre los hermanos sin IA2 («2 de 9»): menús, pestañas y listas simples."""
		role = self.role
		cid = self.IAccessibleChildID
		if role in (Role.LISTITEM, Role.TAB) and cid:
			# Proxies de Windows (ListBox, pestañas): el identificador es la posición.
			total = int(_safe(lambda: self.IAccessibleObject.accChildCount, 0) or 0)
			return {"indexInGroup": cid, "similarItemsInGroup": total} if 0 < cid <= total else {}
		if role not in (Role.MENUITEM, Role.CHECKMENUITEM, Role.RADIOMENUITEM):
			return {}
		if cid:
			container = self.IAccessibleObject
		else:
			container = msaa.normalizeIAccessible(_safe(lambda: self.IAccessibleObject.accParent))
		if container is None:
			return {}
		count = int(_safe(lambda: container.accChildCount, 0) or 0)
		if count <= 0 or count > 200:
			return {}
		myName = self.name
		index = 0
		total = 0
		for pacc, child in msaa.accessibleChildren(container, 0, count):
			r = _safe(lambda p=pacc, c=child: p.accRole(c), 0)
			st = _safe(lambda p=pacc, c=child: p.accState(c), 0)
			if r == msaa.ROLE_SEPARATOR or (isinstance(st, int) and st & msaa.STATE_INVISIBLE):
				continue
			total += 1
			if index:
				continue
			if cid:
				if child == cid and ctypes_addr(pacc) == ctypes_addr(container):
					index = total
			elif not child:
				# Elemento con submenú: cada consulta da un objeto nuevo, así que se compara el nombre.
				name = _safe(lambda p=pacc: p.accName(0), "")
				if isinstance(name, str) and name.split("\t", 1)[0].strip() == myName and r in (msaa.ROLE_MENUITEM, self.IAccessibleRole):
					index = total
		return {"indexInGroup": index, "similarItemsInGroup": total} if index else {}

	def _get_windowHandle(self) -> int:
		if self._windowHandle:
			return self._windowHandle
		hwnd = 0
		ia2 = self.IA2
		if ia2 is not None:
			hwnd = int(_safe(lambda: ia2.windowHandle, 0) or 0)
		if not hwnd:
			hwnd = msaa.windowFromAccessibleObject(self.IAccessibleObject)
		self._windowHandle = hwnd
		return hwnd

	def _get_tableCellCoords(self) -> tuple[int, int] | None:
		cell = msaa.queryInterface(self.IA2, msaa.IAccessibleTableCell) if self.IA2 is not None else None
		if cell is None:
			return None
		row = _safe(lambda: cell.rowIndex)
		col = _safe(lambda: cell.columnIndex)
		if row is None or col is None:
			return None
		return int(row) + 1, int(col) + 1

	# ----------------------------------------------------- navegación
	def _get_parent(self) -> AccObject | None:
		from ..a11y import system

		if self.IAccessibleChildID:
			return system.filterSecure(IAccessibleObject.fromIAccessible(self.IAccessibleObject, 0, self.windowHandle))
		pacc = msaa.normalizeIAccessible(_safe(lambda: self.IAccessibleObject.accParent))
		guard = 0
		while pacc is not None and guard < 5:
			guard += 1
			hwnd = msaa.windowFromAccessibleObject(pacc)
			# El objeto «ventana» de la propia ventana no aporta nada: se salta.
			role = _safe(lambda p=pacc: p.accRole(0), 0)
			if role == msaa.ROLE_WINDOW and hwnd == self.windowHandle and self.IAccessibleRole != msaa.ROLE_WINDOW:
				nxt = msaa.normalizeIAccessible(_safe(lambda p=pacc: p.accParent))
				if nxt is None:
					break
				pacc = nxt
				continue
			return system.filterSecure(self._wrapAccessible(pacc))
		if self.windowHandle:
			from .. import winapi

			parentHwnd = winapi.getAncestor(self.windowHandle, winapi.GA_PARENT)
			if parentHwnd:
				if msaa.isDesktopWindow(parentHwnd):
					from .. import api

					return api.getDesktopObject()
				from ..a11y import api_choice

				return system.filterSecure(_objectForWindow(parentHwnd, api_choice.chooseAPI(parentHwnd)))
		return None

	def _get_children(self) -> list[AccObject]:
		from ..a11y import system

		if self.IAccessibleChildID:
			return []
		count = _safe(lambda: self.IAccessibleObject.accChildCount, 0) or 0
		out: list[AccObject] = []
		for pacc, child in msaa.accessibleChildren(self.IAccessibleObject, 0, int(count)):
			obj = self._wrapAccessible(pacc, child)
			obj = system.filterSecure(obj)
			if obj is not None:
				out.append(obj)
		return out

	def _get_childCount(self) -> int:
		if self.IAccessibleChildID:
			return 0
		return int(_safe(lambda: self.IAccessibleObject.accChildCount, 0) or 0)

	def _get_firstChild(self) -> AccObject | None:
		children = self.children
		return children[0] if children else None

	def _get_lastChild(self) -> AccObject | None:
		children = self.children
		return children[-1] if children else None

	def _sibling(self, direction: int) -> AccObject | None:
		parent = self.parent
		if parent is None:
			return None
		siblings = parent.children
		for i, s in enumerate(siblings):
			if s == self:
				j = i + direction
				return siblings[j] if 0 <= j < len(siblings) else None
		return None

	def _get_next(self) -> AccObject | None:
		return self._sibling(1)

	def _get_previous(self) -> AccObject | None:
		return self._sibling(-1)

	# ----------------------------------------------------- acciones
	def setFocus(self) -> None:
		try:
			self.IAccessibleObject.accSelect(msaa.SELFLAG_TAKEFOCUS, self.IAccessibleChildID)
		except (comtypes.COMError, OSError):
			log.debug("accSelect falló", exc_info=True)

	def _get_actionName(self) -> str:
		action = _safe(lambda: self.IAccessibleObject.accDefaultAction(self.IAccessibleChildID), "")
		return action if isinstance(action, str) and action else _("hacer clic")

	def doAction(self, index: int = 0) -> bool:
		ia2 = self.IA2
		if ia2 is not None:
			act = msaa.queryInterface(ia2, msaa.IAccessibleAction)
			if act is not None and (_safe(lambda: act.nActions(), 0) or 0) > index:
				try:
					act.doAction(index)
					return True
				except comtypes.COMError:
					pass
		try:
			self.IAccessibleObject.accDoDefaultAction(self.IAccessibleChildID)
			return True
		except (comtypes.COMError, OSError):
			pass
		loc = self.location
		if not loc:
			return False
		from .. import mouse

		x, y, w, h = loc
		mouse.click(x + w // 2, y + h // 2)
		return True

	def scrollIntoView(self) -> None:
		ia2 = self.IA2
		if ia2 is not None:
			try:
				ia2.scrollTo(msaa.IA2_SCROLL_TYPE_ANYWHERE)
			except comtypes.COMError:
				pass

	def selectedChildren(self) -> list[AccObject]:
		"""Hijos seleccionados (``accSelection``)."""
		val = _safe(lambda: self.IAccessibleObject.accSelection)
		out: list[AccObject] = []
		if val is None:
			return out
		if isinstance(val, int):
			o = IAccessibleObject.fromIAccessible(self.IAccessibleObject, val, self.windowHandle)
			return [o] if o else []
		pacc = msaa.normalizeIAccessible(val)
		if pacc is not None:
			o = IAccessibleObject.fromIAccessible(pacc, 0)
			return [o] if o else []
		# IEnumVARIANT: se recorren los hijos marcados como seleccionados.
		for child in self.children:
			try:
				if State.SELECTED in child.states:
					out.append(child)
			except Exception:
				continue
		return out

	# ----------------------------------------------------- texto
	def _get_TextInfo(self):
		if self.IAccessibleChildID:
			return None
		ia2 = self.IA2
		if ia2 is not None and msaa.queryInterface(ia2, msaa.IAccessibleText) is not None:
			return IA2TextInfo
		if win32ctl.isEditClass(self.windowClassName) and self.role in (Role.EDITABLETEXT, Role.PASSWORDEDIT, Role.DOCUMENT):
			return EditWindowTextInfo
		if self.windowClassName == "ConsoleWindowClass":
			from .terminal import ConsoleTextInfo

			return ConsoleTextInfo
		return None

	# ----------------------------------------------------- superposiciones
	def findOverlayClasses(self, clsList: list[type]) -> None:
		from . import behaviors

		role = self.role
		cls = self.windowClassName
		ti = self.TextInfo
		if cls == "ConsoleWindowClass" and role == Role.TERMINAL:
			from .terminal import Terminal

			clsList.append(Terminal)
		elif ti is not None and role in (Role.EDITABLETEXT, Role.PASSWORDEDIT, Role.DOCUMENT, Role.TERMINAL, Role.PARAGRAPH, Role.COMBOBOX):
			if State.EDITABLE in self.states or role in (Role.EDITABLETEXT, Role.PASSWORDEDIT):
				clsList.append(behaviors.EditableTextWithCaret)
			else:
				clsList.append(behaviors.ReadOnlyDocument)
		elif role in (Role.EDITABLETEXT, Role.PASSWORDEDIT):
			clsList.append(behaviors.EditableTextNoCaret)
		if role == Role.PROGRESSBAR:
			clsList.append(behaviors.ProgressBar)
		if role == Role.DIALOG:
			clsList.append(behaviors.Dialog)
		if role == Role.LISTITEM and cls == "SysListView32" and self.IAccessibleChildID:
			from .listview import ListViewItem

			clsList.append(ListViewItem)
			# Control+Espacio y la selección de otros elementos (selectionAdd/Remove).
			clsList.append(behaviors.SelectableItem)
		elif role in (Role.LISTITEM, Role.TABLEROW, Role.TREEVIEWITEM, Role.DATAITEM):
			if role == Role.TREEVIEWITEM and cls == "SysTreeView32" and self.IAccessibleChildID:
				clsList.append(SysTreeViewItem)
			clsList.append(behaviors.SelectableItem)
		if role in (Role.LIST, Role.TREEVIEW, Role.TABLE, Role.DATAGRID):
			clsList.append(behaviors.ListContainer)

	# ----------------------------------------------------- depuración
	def _get_devInfo(self) -> list[str]:
		info = super()._get_devInfo()
		info.append(f"IAccessible childID: {self.IAccessibleChildID}")
		info.append(f"IAccessible role: {self.IAccessibleRole!r}")
		info.append(f"IAccessible states: 0x{self.IAccessibleStates:x}")
		info.append(f"IAccessible2: {'sí' if self.IA2 is not None else 'no'}")
		if self.IA2 is not None:
			info.append(f"IA2 states: 0x{self.IA2States:x}")
			info.append(f"IA2 attributes: {self.IA2Attributes!r}")
		return info


class SysTreeViewItem(AccObject):
	"""Elemento de un árbol Win32 (``SysTreeView32``) leído con MSAA.

	El proxy MSAA del sistema pone como valor el nivel del elemento empezando
	en 0 («Rama A 0 contraído») y no da la posición. Aquí el valor no se lee y
	la posición y el nivel salen del propio control: «Rama A contraído 1 de 3
	nivel 1», igual que con UIA. Es lo que se oye en los árboles de las
	ventanas de Tiresias (gestos de entrada, lista de elementos), que se leen
	con MSAA.
	"""

	def _get_value(self) -> str:
		return ""

	def _get_positionInfo(self) -> dict[str, int]:
		info = win32ctl.treeViewItemPosition(self.windowHandle, self.IAccessibleChildID)
		return info or super()._get_positionInfo()

	def _get_level(self) -> int | None:
		return self.positionInfo.get("level") or super()._get_level()


def _isMomentaryPress(obj: IAccessibleObject, role: Role) -> bool:
	"""``True`` si el estado «pulsado» de MSAA solo indica que el botón está hundido.

	En las casillas y los botones de opción nunca significa nada más. En los
	botones de la clase Win32 ``Button`` (los de los diálogos, también los de
	wxPython) es el instante en que se mantiene pulsado: el «activado» de un
	botón de alternar llega como STATE_CHECKED. En cambio, los botones de una
	barra de herramientas o de IAccessible2 (``aria-pressed``) usan «pulsado»
	para decir que están activados, y ahí se conserva.
	"""
	if role in (Role.CHECKBOX, Role.RADIOBUTTON, Role.CHECKMENUITEM, Role.RADIOMENUITEM):
		return True
	if role in (Role.BUTTON, Role.TOGGLEBUTTON) and not obj.IAccessibleChildID:
		try:
			return (obj.windowClassName or "").lower() == "button"
		except Exception:
			return False
	return False


def _ownMenuItemRole(hwnd: int, childId: int) -> Role | None:
	"""Rol de un elemento de un menú de Tiresias: de verificación o de opción.

	Windows solo sabe que un elemento es «de verificación» mientras está
	marcado; la interfaz recuerda cuáles lo son (``gui.checkableMenuIds``).
	"""

	def query() -> Role | None:
		import ctypes

		from .. import gui, winapi

		hmenu = winapi.user32.SendMessageW(hwnd, 0x01E1, 0, 0)  # MN_GETHMENU
		if not hmenu:
			return None
		info = _MENUITEMINFOW(cbSize=ctypes.sizeof(_MENUITEMINFOW), fMask=0x100 | 0x2)  # MIIM_FTYPE | MIIM_ID
		if not ctypes.windll.user32.GetMenuItemInfoW(ctypes.c_void_p(hmenu), childId - 1, True, ctypes.byref(info)):
			return None
		if info.fType & 0x200:  # MFT_RADIOCHECK
			return Role.RADIOMENUITEM
		if (info.wID & 0xFFFF) in gui.checkableMenuIds:
			return Role.CHECKMENUITEM
		return None

	try:
		return msaa.own_windows.call(query)
	except Exception:
		return None


def _menuItemInfoType():
	import ctypes
	from ctypes import wintypes

	class MENUITEMINFOW(ctypes.Structure):
		_fields_ = [
			("cbSize", wintypes.UINT),
			("fMask", wintypes.UINT),
			("fType", wintypes.UINT),
			("fState", wintypes.UINT),
			("wID", wintypes.UINT),
			("hSubMenu", wintypes.HANDLE),
			("hbmpChecked", wintypes.HANDLE),
			("hbmpUnchecked", wintypes.HANDLE),
			("dwItemData", ctypes.c_size_t),
			("dwTypeData", wintypes.LPWSTR),
			("cch", wintypes.UINT),
			("hbmpItem", wintypes.HANDLE),
		]

	return MENUITEMINFOW


_MENUITEMINFOW = _menuItemInfoType()

_HEADINGS = {Role.HEADING, Role.HEADING1, Role.HEADING2, Role.HEADING3, Role.HEADING4, Role.HEADING5, Role.HEADING6}


def ctypes_addr(ptr) -> int:
	import ctypes

	if isinstance(ptr, msaa.own_windows.OwnAccessible):
		return ptr.addr
	return ctypes.cast(ptr, ctypes.c_void_p).value or 0


def _objectForWindow(hwnd: int, choice: str) -> AccObject | None:
	"""Objeto de la ventana ``hwnd`` con la API indicada."""
	from ..a11y import api_choice

	if choice == api_choice.API_MSAA:
		return IAccessibleObject.fromWindow(hwnd)
	if choice == api_choice.API_JAVA:
		try:
			from .jab import JABObject

			obj = JABObject.fromWindow(hwnd)
			if obj is not None:
				return obj
		except Exception:
			log.debug("No se pudo crear el objeto Java", exc_info=True)
	from .uia import getObjectFromHandle

	return getObjectFromHandle(hwnd)


# ====================================================================== texto
def _ia2TextIfaceOf(obj):
	cached = obj.__dict__.get("_ia2TextIface")
	if cached is not None and cached[0] == baseobject._cacheGeneration:
		return cached[1]
	iface = msaa.queryInterface(obj.IA2, msaa.IAccessibleText)
	obj.__dict__["_ia2TextIface"] = (baseobject._cacheGeneration, iface)
	return iface


class IA2TextInfo(textinfo.Utf16OffsetsTextInfo):
	"""Texto de un objeto con ``IAccessibleText`` (IAccessible2).

	Rev. 10.11 (C2): IAccessibleText cuenta en unidades UTF-16; los
	desplazamientos se convierten (un emoji ocupa dos).
	"""

	def _textIface(self):
		return _ia2TextIfaceOf(self.obj)

	@staticmethod
	def caretSignature(obj) -> tuple | None:
		"""Cursor y longitud sin copiar el texto (para vigilar el cursor, A4)."""
		t = _ia2TextIfaceOf(obj)
		if t is None:
			return None
		return (_safe(lambda: t.caretOffset, None), _safe(lambda: t.nCharacters, None), _safe(lambda: t.nSelections, None))

	def _getStoryText(self) -> str:
		t = self._textIface()
		if t is None:
			return ""
		n = _safe(lambda: t.nCharacters, 0) or 0
		if n <= 0:
			return ""
		text = _safe(lambda: t.text(0, n), "") or ""
		# Los objetos incrustados ocupan un carácter: se sustituye por un espacio.
		return text.replace(msaa.EMBEDDED_OBJECT_CHAR, " ")

	def _getCaretOffset(self) -> int:
		t = self._textIface()
		off = _safe(lambda: t.caretOffset, 0) if t is not None else 0
		return self._toStr(max(0, int(off or 0)))

	def _setCaretOffset(self, offset: int) -> None:
		t = self._textIface()
		if t is not None:
			try:
				t.setCaretOffset(self._toUtf16(offset))
			except comtypes.COMError:
				log.debug("setCaretOffset falló", exc_info=True)

	def _getSelectionOffsets(self) -> tuple[int, int]:
		t = self._textIface()
		if t is not None and (_safe(lambda: t.nSelections, 0) or 0) > 0:
			sel = _safe(lambda: t.selection(0))
			if sel:
				start, end = self._toStr(int(sel[0])), self._toStr(int(sel[1]))
				return min(start, end), max(start, end)
		o = self._getCaretOffset()
		return o, o

	def _setSelectionOffsets(self, start: int, end: int) -> None:
		t = self._textIface()
		if t is None:
			return
		start, end = self._toUtf16(start), self._toUtf16(end)
		try:
			if (_safe(lambda: t.nSelections, 0) or 0) > 0:
				t.setSelection(0, start, end)
			else:
				t.addSelection(start, end)
		except comtypes.COMError:
			log.debug("setSelection falló", exc_info=True)

	def _getOffsetFromPoint(self, x: int, y: int) -> int:
		t = self._textIface()
		off = _safe(lambda: t.offsetAtPoint(x, y, msaa.IA2_COORDTYPE_SCREEN_RELATIVE), 0) if t is not None else 0
		return self._toStr(max(0, int(off or 0)))

	def _unitBoundaries(self, unit: str, offset: int) -> tuple[int, int]:
		boundary = {
			textinfo.UNIT_LINE: msaa.IA2_TEXT_BOUNDARY_LINE,
			textinfo.UNIT_WORD: msaa.IA2_TEXT_BOUNDARY_WORD,
			textinfo.UNIT_SENTENCE: msaa.IA2_TEXT_BOUNDARY_SENTENCE,
		}.get(unit)
		t = self._textIface() if boundary is not None else None
		if t is not None:
			wide = self._toUtf16(offset)
			res = _safe(lambda: t.textAtOffset(wide, boundary))
			if res and len(res) >= 2:
				start, end = self._toStr(int(res[0])), self._toStr(int(res[1]))
				if 0 <= start <= offset < end or (start == end == offset):
					return start, end
		return super()._unitBoundaries(unit, offset)

	@property
	def boundingRects(self) -> list[tuple[int, int, int, int]]:
		t = self._textIface()
		if t is None:
			return []
		wide = self._toUtf16(self._start)
		res = _safe(lambda: t.characterExtents(wide, msaa.IA2_COORDTYPE_SCREEN_RELATIVE))
		if not res:
			return []
		return [tuple(int(v) for v in res[:4])]  # type: ignore[list-item]

	def scrollIntoView(self) -> None:
		t = self._textIface()
		if t is not None:
			try:
				t.scrollSubstringTo(self._toUtf16(self._start), self._toUtf16(max(self._start, self._end)), msaa.IA2_SCROLL_TYPE_ANYWHERE)
			except comtypes.COMError:
				pass


class EditWindowTextInfo(textinfo.Utf16OffsetsTextInfo):
	"""Texto de un campo ``Edit``/``RichEdit`` leído con mensajes de ventana.

	El objeto solo necesita ``windowHandle`` y ``windowClassName``, así que lo
	usan tanto los objetos MSAA como los UIA sin patrón Text. Las posiciones de
	los mensajes están en unidades UTF-16 y se convierten (rev. 10.11, C2).
	"""

	@staticmethod
	def caretSignature(obj) -> tuple | None:
		"""Selección y longitud sin copiar el texto (para vigilar el cursor, A4)."""
		hwnd = getattr(obj, "windowHandle", 0)
		if not hwnd:
			return None
		return (win32ctl.editGetSelection(hwnd), win32ctl.sendMessage(hwnd, win32ctl.WM_GETTEXTLENGTH))

	def _isRich(self) -> bool:
		return win32ctl.isRichEditClass(self.obj.windowClassName)

	def _getStoryText(self) -> str:
		text = win32ctl.getWindowText(self.obj.windowHandle) or ""
		if self._isRich():
			# RichEdit cuenta el fin de párrafo como un solo carácter.
			text = text.replace("\r\n", "\n")
		return text

	def _getSelectionOffsets(self) -> tuple[int, int]:
		sel = win32ctl.editGetSelection(self.obj.windowHandle)
		if not sel:
			return 0, 0
		start, end = self._toStr(sel[0]), self._toStr(sel[1])
		n = len(self._story())
		return max(0, min(start, n)), max(0, min(end, n))

	def _getCaretOffset(self) -> int:
		return self._getSelectionOffsets()[1]

	def _setCaretOffset(self, offset: int) -> None:
		wide = self._toUtf16(offset)
		win32ctl.editSetSelection(self.obj.windowHandle, wide, wide)

	def _setSelectionOffsets(self, start: int, end: int) -> None:
		win32ctl.editSetSelection(self.obj.windowHandle, self._toUtf16(start), self._toUtf16(end))

	def _unitBoundaries(self, unit: str, offset: int) -> tuple[int, int]:
		if unit == textinfo.UNIT_LINE and win32ctl.getWindowStyle(self.obj.windowHandle) & win32ctl.ES_MULTILINE:
			hwnd = self.obj.windowHandle
			line = win32ctl.editLineFromChar(hwnd, self._toUtf16(offset))
			if line is not None:
				start = win32ctl.editLineIndex(hwnd, line)
				nextStart = win32ctl.editLineIndex(hwnd, line + 1)
				n = len(self._story())
				if start is not None and start >= 0:
					start = self._toStr(start)
					nextStart = self._toStr(nextStart) if nextStart is not None and nextStart >= 0 else None
					end = nextStart if nextStart is not None and nextStart > start else n
					if start <= offset < end or offset == n:
						return start, min(end, n)
		return super()._unitBoundaries(unit, offset)

	@property
	def lineNumber(self) -> int | None:
		line = win32ctl.editLineFromChar(self.obj.windowHandle, self._toUtf16(self._start))
		return line + 1 if line is not None else super().lineNumber
