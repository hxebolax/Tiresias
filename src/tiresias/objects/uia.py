"""Objetos accesibles basados en UI Automation."""

from __future__ import annotations

from typing import Any

import comtypes

from .. import baseobject, winapi
from ..a11y import ia2_bridge
from ..a11y import uia_client as uc
from ..i18n import _
from ..log import getLogger
from .base import AccObject, looksLikeTypeName
from .roles import Role, State

log = getLogger("uiaObjects")
UIA = uc.UIA

_CONTROLTYPE_ROLES = {
	uc.CT_BUTTON: Role.BUTTON,
	uc.CT_CALENDAR: Role.CALENDAR,
	uc.CT_CHECKBOX: Role.CHECKBOX,
	uc.CT_COMBOBOX: Role.COMBOBOX,
	uc.CT_EDIT: Role.EDITABLETEXT,
	uc.CT_HYPERLINK: Role.LINK,
	uc.CT_IMAGE: Role.GRAPHIC,
	uc.CT_LISTITEM: Role.LISTITEM,
	uc.CT_LIST: Role.LIST,
	uc.CT_MENU: Role.POPUPMENU,
	uc.CT_MENUBAR: Role.MENUBAR,
	uc.CT_MENUITEM: Role.MENUITEM,
	uc.CT_PROGRESSBAR: Role.PROGRESSBAR,
	uc.CT_RADIOBUTTON: Role.RADIOBUTTON,
	uc.CT_SCROLLBAR: Role.SCROLLBAR,
	uc.CT_SLIDER: Role.SLIDER,
	uc.CT_SPINNER: Role.SPINBUTTON,
	uc.CT_STATUSBAR: Role.STATUSBAR,
	uc.CT_TAB: Role.TABCONTROL,
	uc.CT_TABITEM: Role.TAB,
	uc.CT_TEXT: Role.STATICTEXT,
	uc.CT_TOOLBAR: Role.TOOLBAR,
	uc.CT_TOOLTIP: Role.TOOLTIP,
	uc.CT_TREE: Role.TREEVIEW,
	uc.CT_TREEITEM: Role.TREEVIEWITEM,
	uc.CT_CUSTOM: Role.CUSTOM,
	uc.CT_GROUP: Role.GROUPING,
	uc.CT_THUMB: Role.THUMB,
	uc.CT_DATAGRID: Role.DATAGRID,
	uc.CT_DATAITEM: Role.DATAITEM,
	uc.CT_DOCUMENT: Role.DOCUMENT,
	uc.CT_SPLITBUTTON: Role.SPLITBUTTON,
	uc.CT_WINDOW: Role.WINDOW,
	uc.CT_PANE: Role.PANE,
	uc.CT_HEADER: Role.HEADER,
	uc.CT_HEADERITEM: Role.HEADERITEM,
	uc.CT_TABLE: Role.TABLE,
	uc.CT_TITLEBAR: Role.TITLEBAR,
	uc.CT_SEPARATOR: Role.SEPARATOR,
	uc.CT_SEMANTICZOOM: Role.SEMANTICZOOM,
	uc.CT_APPBAR: Role.APPBAR,
}

_ARIA_ROLES = {
	"heading": Role.HEADING,
	"paragraph": Role.PARAGRAPH,
	"blockquote": Role.BLOCKQUOTE,
	"row": Role.TABLEROW,
	"gridcell": Role.TABLECELL,
	"cell": Role.TABLECELL,
	"columnheader": Role.TABLECOLUMNHEADER,
	"rowheader": Role.TABLEROWHEADER,
	"switch": Role.SWITCH,
	"dialog": Role.DIALOG,
	"alertdialog": Role.DIALOG,
	"alert": Role.ALERT,
	"article": Role.ARTICLE,
	"figure": Role.FIGURE,
	"note": Role.NOTE,
	"math": Role.MATH,
	"tabpanel": Role.PROPERTYPAGE,
	"menuitemcheckbox": Role.CHECKMENUITEM,
	"menuitemradio": Role.RADIOMENUITEM,
	"mark": Role.MARKED_CONTENT,
	"comment": Role.COMMENT,
	"suggestion": Role.SUGGESTION,
	"definition": Role.DEFINITION,
	"term": Role.STATICTEXT,
	"application": Role.APPLICATION,
	"log": Role.SECTION,
	"status": Role.STATUSBAR,
	"timer": Role.CLOCK,
	"img": Role.GRAPHIC,
	"image": Role.GRAPHIC,
	"separator": Role.SEPARATOR,
	"toolbar": Role.TOOLBAR,
	"feed": Role.LIST,
}

_LANDMARK_ARIA = {
	"banner": _("cabecera"),
	"navigation": _("navegación"),
	"main": _("principal"),
	"contentinfo": _("información de contenido"),
	"complementary": _("complementario"),
	"search": _("búsqueda"),
	"form": _("formulario"),
	"region": _("región"),
}

_LANDMARK_TYPES = {
	uc.LANDMARK_FORM: _("formulario"),
	uc.LANDMARK_MAIN: _("principal"),
	uc.LANDMARK_NAVIGATION: _("navegación"),
	uc.LANDMARK_SEARCH: _("búsqueda"),
}

# Estados MSAA (LegacyIAccessible) útiles.
STATE_SYSTEM_UNAVAILABLE = 0x1
STATE_SYSTEM_SELECTED = 0x2
STATE_SYSTEM_FOCUSED = 0x4
STATE_SYSTEM_PRESSED = 0x8
STATE_SYSTEM_CHECKED = 0x10
STATE_SYSTEM_MIXED = 0x20
STATE_SYSTEM_READONLY = 0x40
STATE_SYSTEM_BUSY = 0x800
STATE_SYSTEM_INVISIBLE = 0x8000
STATE_SYSTEM_TRAVERSED = 0x800000
STATE_SYSTEM_MULTISELECTABLE = 0x1000000
STATE_SYSTEM_PROTECTED = 0x20000000
STATE_SYSTEM_HASPOPUP = 0x40000000

#: Roles en los que «selección múltiple» (estado MSAA heredado) tiene sentido.
_MULTISELECT_CONTAINERS = frozenset({Role.LIST, Role.TREEVIEW, Role.TABLE, Role.DATAGRID, Role.TABCONTROL})


def parseAriaProperties(props: str) -> dict[str, str]:
	out: dict[str, str] = {}
	if not props:
		return out
	for part in props.split(";"):
		if "=" in part:
			k, v = part.split("=", 1)
			out[k.strip()] = v.strip()
	return out


def _clean(value: Any) -> Any:
	if uc.isNotSupported(value):
		return None
	return value


#: Estado MSAA «enfocable» (LegacyIAccessible).
STATE_SYSTEM_FOCUSABLE = 0x100000


def isMsaaProxyProvider(description: Any) -> bool:
	"""El proveedor UIA es el puente MSAA→UIA del sistema (``ProviderDescription``)."""
	return "MSAA Proxy" in str(description or "")


def looksLikeTextLeaf(get: Any) -> bool:
	"""Trozo de texto de Gecko que el puente MSAA→UIA presenta como campo de edición.

	Gecko sin proveedor UIA propio (Thunderbird 102 y anteriores) da a cada
	trozo de texto el rol MSAA ``ROLE_SYSTEM_TEXT`` sin «solo lectura», y el
	puente lo convierte en un ``Edit`` con valor modificable: el cuerpo de un
	correo se leía «Hola. edición». NVDA lo lee con IAccessible2 (sin
	``IA2_STATE_EDITABLE`` es texto normal). Un campo de verdad se puede
	enfocar o está desactivado, y tiene valor. ``get(propiedad, defecto)`` lee
	las propiedades del elemento; el marco y el proveedor los comprueba quien llama.
	"""
	if get(uc.P_CONTROLTYPE, 0) != uc.CT_EDIT or get(uc.P_ISPASSWORD, False):
		return False
	if get(uc.P_ISKEYBOARDFOCUSABLE, False) or not get(uc.P_ISENABLED, True):
		return False
	try:
		legacy = int(get(uc.P_LEGACYSTATE, 0) or 0)
	except (TypeError, ValueError):
		legacy = 0
	if legacy & (STATE_SYSTEM_FOCUSABLE | STATE_SYSTEM_UNAVAILABLE):
		return False
	return not str(get(uc.P_VALUEVALUE, "") or "")


class UIAObject(AccObject):
	"""Objeto accesible respaldado por un ``IUIAutomationElement``."""

	def __init__(self, element, windowHandle: int | None = None) -> None:
		super().__init__()
		self.element = element
		self._creationGen = baseobject._cacheGeneration
		self._windowHandle = windowHandle
		self._runtimeId: tuple | None = None
		self._patternCache: dict[int, Any] = {}

	# ----------------------------------------------------- creación
	@classmethod
	def fromElement(cls, element, windowHandle: int | None = None) -> "UIAObject | None":
		try:
			if element is None or not bool(element):
				return None
		except (ValueError, comtypes.COMError):
			return None
		try:
			obj = cls(element, windowHandle)
			obj._applyOverlays()
			return obj
		except comtypes.COMError:
			return None
		except Exception:
			log.exception("No se pudo crear el objeto UIA")
			return None

	def _wrap(self, element) -> "AccObject | None":
		"""Objeto para un elemento al navegar (respeta la API de cada ventana)."""
		if element is None:
			return None
		try:
			# Un puntero nulo de COM se evalúa como falso.
			if not bool(element):
				return None
		except Exception:
			return None
		from ..a11y import api_choice, system

		try:
			hwnd = int(element.GetCachedPropertyValue(uc.P_NATIVEWINDOWHANDLE) or 0)
		except (comtypes.COMError, ValueError, TypeError):
			hwnd = 0
		if hwnd and hwnd != self._windowHandle:
			# Navegación mixta: las ventanas que se leen con MSAA o Java se
			# convierten en el objeto de su API.
			choice = api_choice.chooseAPI(hwnd)
			if choice != api_choice.API_UIA:
				from .iaccessible import _objectForWindow

				obj = _objectForWindow(hwnd, choice)
				if obj is not None:
					return system.filterSecure(obj)
		return system.filterSecure(UIAObject.fromElement(element))

	# ----------------------------------------------------- utilidades
	def _prop(self, propId: int, default: Any = None) -> Any:
		el = self.element
		if propId in uc.ELEMENT_ARRAY_PROPERTIES:
			# Matrices de elementos: nunca como VARIANT (ver uia_client.elementArray).
			return uc.elementArray(el, propId) or default
		if propId in uc.ELEMENT_PROPERTIES:
			return uc.labeledBy(el) or default
		if self._creationGen == baseobject._cacheGeneration:
			try:
				val = el.GetCachedPropertyValueEx(propId, True)
				if val is not None and not uc.isNotSupported(val):
					return val
			except (comtypes.COMError, ValueError):
				pass
		try:
			val = el.GetCurrentPropertyValueEx(propId, True)
		except comtypes.COMError:
			return default
		except Exception:
			return default
		if val is None or uc.isNotSupported(val):
			return default
		return val

	#: Relaciones -> propiedad UIA con matriz de elementos.
	_RELATIONS = {
		"controllerFor": uc.P_CONTROLLERFOR,
		"describedBy": uc.P_DESCRIBEDBY,
		"flowsTo": uc.P_FLOWSTO,
		"flowsFrom": uc.P_FLOWSFROM,
		"details": uc.P_ANNOTATIONOBJECTS,
	}

	def relationElements(self, relation: str) -> list:
		"""Elementos UIA de una relación (``controllerFor``, ``describedBy``,
		``flowsTo``, ``flowsFrom``, ``details``) con los accesores tipados."""
		propId = self._RELATIONS.get(relation)
		if propId is None:
			return []
		return uc.elementArray(self.element, propId)

	def _pattern(self, patternId: int, iface) -> Any:
		cached = self._patternCache.get(patternId)
		if cached is not None and cached[0] == baseobject._cacheGeneration:
			return cached[1]
		try:
			punk = self.element.GetCurrentPattern(patternId)
			pat = punk.QueryInterface(iface) if punk else None
		except (comtypes.COMError, ValueError, AttributeError):
			pat = None
		self._patternCache[patternId] = (baseobject._cacheGeneration, pat)
		return pat

	@property
	def runtimeId(self) -> tuple:
		if self._runtimeId is None:
			self._runtimeId = uc.runtimeIdOf(self.element)
		return self._runtimeId

	def isSameAs(self, other: AccObject) -> bool:
		if not isinstance(other, UIAObject):
			return False
		a, b = self.runtimeId, other.runtimeId
		if a and b:
			return a == b
		return uc.compareElements(self.element, other.element)

	def __hash__(self) -> int:
		rid = self.runtimeId
		return hash(rid) if rid else id(self)

	def refreshProperties(self) -> None:
		super().refreshProperties()
		# Sin esto, en el ciclo en que se creó se seguirían leyendo los valores
		# de la caché del evento (los de antes del cambio).
		self._creationGen = -1
		self._patternCache.clear()

	#: El elemento ya no existe: UIA_E_ELEMENTNOTAVAILABLE, RPC_E_DISCONNECTED,
	#: RPC_S_SERVER_UNAVAILABLE (el proceso terminó).
	_DEAD_HRESULTS = frozenset({0x80040201, 0x80010108, 0x800706BA})

	def isDefunct(self) -> bool:
		"""``True`` si el elemento ya no existe (una pregunta barata al proveedor)."""
		try:
			self.element.CurrentProcessId
		except comtypes.COMError as e:
			return ((e.hresult or 0) & 0xFFFFFFFF) in self._DEAD_HRESULTS
		except ValueError:
			return True
		except Exception:
			return False
		return False

	# ----------------------------------------------------- propiedades
	def _get_UIAControlType(self) -> int:
		return self._prop(uc.P_CONTROLTYPE, 0) or 0

	def _get_UIAAutomationId(self) -> str:
		return self._prop(uc.P_AUTOMATIONID, "") or ""

	def _get_UIAClassName(self) -> str:
		return self._prop(uc.P_CLASSNAME, "") or ""

	def _get_UIAFrameworkId(self) -> str:
		return self._prop(uc.P_FRAMEWORKID, "") or ""

	def _get_UIAAriaRole(self) -> str:
		return (self._prop(uc.P_ARIAROLE, "") or "").lower()

	def _get_UIAAriaProperties(self) -> dict[str, str]:
		return parseAriaProperties(self._prop(uc.P_ARIAPROPERTIES, "") or "")

	def _get_UIALocalizedControlType(self) -> str:
		return self._prop(uc.P_LOCALIZEDCONTROLTYPE, "") or ""

	def _get_UIALegacyState(self) -> int:
		return int(self._prop(uc.P_LEGACYSTATE, 0) or 0)

	def _get_name(self) -> str:
		name = self._prop(uc.P_NAME, "") or ""
		if not name and self.UIAControlType in (uc.CT_EDIT, uc.CT_COMBOBOX, uc.CT_LIST, uc.CT_SLIDER):
			try:
				el = uc.labeledBy(self.element)
				if el is not None:
					name = el.CurrentName or ""
			except Exception:
				pass
		return name.strip() if isinstance(name, str) else ""

	def _get_role(self) -> Role:
		ct = self.UIAControlType
		role = _CONTROLTYPE_ROLES.get(ct, Role.UNKNOWN)
		aria = self.UIAAriaRole
		if ct == uc.CT_EDIT and self._prop(uc.P_ISPASSWORD, False):
			return Role.PASSWORDEDIT
		heading = self._prop(uc.P_HEADINGLEVEL, 0) or 0
		if heading and heading > uc.HEADINGLEVEL_NONE:
			level = heading - uc.HEADINGLEVEL_NONE
			return Role(Role.HEADING1 + level - 1) if 1 <= level <= 6 else Role.HEADING
		if aria:
			if aria == "heading":
				return Role.HEADING
			mapped = _ARIA_ROLES.get(aria)
			if mapped is not None and role not in (Role.EDITABLETEXT, Role.BUTTON, Role.LINK, Role.CHECKBOX):
				return mapped
			if aria in _LANDMARK_ARIA and role in (Role.GROUPING, Role.PANE, Role.CUSTOM, Role.UNKNOWN):
				if aria != "region" or self._prop(uc.P_NAME, ""):
					return Role.LANDMARK
		if role == Role.BUTTON and self._prop(uc.P_ISTOGGLEPATTERNAVAILABLE, False):
			return Role.TOGGLEBUTTON
		if role == Role.WINDOW and (self._prop(uc.P_ISDIALOG, False) or self.UIAClassName == "#32770"):
			return Role.DIALOG
		if role == Role.PANE and self._prop(uc.P_ISDIALOG, False):
			return Role.DIALOG
		if role in (Role.GROUPING, Role.CUSTOM, Role.PANE) and self._prop(uc.P_LANDMARKTYPE, 0):
			return Role.LANDMARK
		if role == Role.DATAITEM and aria == "row":
			return Role.TABLEROW
		if role == Role.CUSTOM and not aria and (self._prop(uc.P_ISGRIDITEMPATTERNAVAILABLE, False) or self._prop(uc.P_ISTABLEITEMPATTERNAVAILABLE, False)):
			# Celda de DataGrid de WPF (DataGridCell, tipo «personalizado» con
			# GridItem/TableItem): es una celda, no «personalizado pulsable».
			return Role.TABLECELL
		if role == Role.DOCUMENT and self._isPlainEditableDocument():
			# RichEdit y documentos editables que no son web ni Word: «edición
			# multilínea», como NVDA (el modo exploración no les afecta).
			return Role.EDITABLETEXT
		if role == Role.EDITABLETEXT and self.UIAFrameworkId == "Gecko" and looksLikeTextLeaf(self._prop) and isMsaaProxyProvider(self._prop(uc.P_PROVIDERDESCRIPTION, "")):
			# Texto del cuerpo de un correo de Thunderbird (Gecko con el puente MSAA):
			# es texto normal, no «edición».
			return Role.STATICTEXT
		return role

	#: Marcos web: sus documentos (también los editables) siguen siendo documentos.
	_WEB_FRAMEWORKS = ("Chrome", "Gecko", "MicrosoftEdge", "InternetExplorer")

	def _isMultiline(self) -> bool:
		"""Campo de edición de varias líneas (documento editable o Edit con ES_MULTILINE)."""
		if self.UIAControlType == uc.CT_DOCUMENT:
			return True
		hwnd = self._prop(uc.P_NATIVEWINDOWHANDLE, 0) or 0
		if not hwnd:
			return False
		from ..a11y import win32ctl

		try:
			return win32ctl.isEditClass(self.windowClassName) and bool(win32ctl.getWindowStyle(hwnd) & win32ctl.ES_MULTILINE)
		except Exception:
			return False

	def _isEditableWordDocument(self) -> bool:
		"""Documento de Word (clase ``_WwG``) en el que se puede escribir.

		El UIA de Word no publica el patrón de valor, así que el documento
		parecería de solo lectura. Lo que sí distingue es el atributo de texto
		``IsReadOnly`` del rango del documento: verdadero en la vista de lectura,
		la vista protegida y los mensajes del panel de lectura de Outlook; falso
		al escribir (también en un archivo abierto «solo lectura», donde se puede
		escribir aunque no guardar encima). Valor mixto (formularios protegidos
		con campos rellenables): editable.
		"""
		if self.UIAClassName != "_WwG" or not self._prop(uc.P_ISTEXTPATTERNAVAILABLE, False):
			return False
		cached = self.__dict__.get("_wordEditable")
		if cached is not None:
			return cached
		editable = True
		try:
			pat = self.textPattern
			if pat:
				value = pat.DocumentRange.GetAttributeValue(uc.A_ISREADONLY)
				editable = not (isinstance(value, bool) and value)
		except (comtypes.COMError, AttributeError, ValueError):
			log.debug("No se pudo saber si el documento de Word es editable", exc_info=True)
		self.__dict__["_wordEditable"] = editable
		return editable

	def _isPlainEditableDocument(self) -> bool:
		"""Documento UIA editable que no es web ni de Word (RichEdit, cuadros de texto ricos...)."""
		if not self._prop(uc.P_ISVALUEPATTERNAVAILABLE, False) or self._prop(uc.P_VALUEISREADONLY, False):
			return False
		if self.UIAFrameworkId in self._WEB_FRAMEWORKS:
			return False
		if "_WwG" in (self.UIAClassName, self.windowClassName):
			return False
		return True

	def _get_roleText(self) -> str | None:
		role = self.role
		if role == Role.LANDMARK:
			return self.landmark
		if role in (Role.CUSTOM, Role.UNKNOWN):
			lct = self.UIALocalizedControlType
			return lct or None
		return None

	def _get_landmark(self) -> str | None:
		lmType = self._prop(uc.P_LANDMARKTYPE, 0) or 0
		if lmType in _LANDMARK_TYPES:
			return _LANDMARK_TYPES[lmType]
		loc = self._prop(uc.P_LOCALIZEDLANDMARKTYPE, "")
		if loc:
			return loc
		aria = self.UIAAriaRole
		if aria in _LANDMARK_ARIA:
			return _LANDMARK_ARIA[aria]
		return None

	def _get_level(self) -> int | None:
		lvl = self._prop(uc.P_LEVEL, 0)
		return int(lvl) if lvl else None

	def _get_states(self) -> set[State]:
		states: set[State] = set()
		if not self._prop(uc.P_ISENABLED, True):
			states.add(State.UNAVAILABLE)
		if self._prop(uc.P_ISKEYBOARDFOCUSABLE, False):
			states.add(State.FOCUSABLE)
		if self._prop(uc.P_HASKEYBOARDFOCUS, False):
			states.add(State.FOCUSED)
		if self._prop(uc.P_ISOFFSCREEN, False):
			states.add(State.OFFSCREEN)
		if self._prop(uc.P_ISPASSWORD, False):
			states.add(State.PROTECTED)
		if self._prop(uc.P_ISREQUIREDFORFORM, False):
			states.add(State.REQUIRED)
		valid = self._prop(uc.P_ISDATAVALIDFORFORM, True)
		if valid is False:
			states.add(State.INVALID_ENTRY)
		role = self.role
		if self._prop(uc.P_ISSELECTIONITEMPATTERNAVAILABLE, False):
			states.add(State.SELECTABLE)
			if self._prop(uc.P_SELECTIONITEMISSELECTED, False):
				states.add(State.SELECTED)
			if role == Role.RADIOBUTTON:
				# Un botón de opción «seleccionado» está marcado (como con MSAA y en
				# NVDA): sin esto, «Opción dos botón de opción» no decía «marcado».
				states.add(State.CHECKABLE)
				if State.SELECTED in states:
					states.add(State.CHECKED)
		if self._prop(uc.P_ISTOGGLEPATTERNAVAILABLE, False):
			toggle = self._prop(uc.P_TOGGLESTATE, None)
			if role in (Role.TOGGLEBUTTON, Role.BUTTON):
				if toggle == 1:
					states.add(State.PRESSED)
				elif toggle == 2:
					states.add(State.HALF_PRESSED)
			elif role == Role.SWITCH:
				if toggle == 1:
					states.add(State.ON)
			else:
				states.add(State.CHECKABLE)
				if toggle == 1:
					states.add(State.CHECKED)
				elif toggle == 2:
					states.add(State.HALFCHECKED)
		if self._prop(uc.P_ISEXPANDCOLLAPSEPATTERNAVAILABLE, False):
			ec = self._prop(uc.P_EXPANDCOLLAPSESTATE, 3)
			if ec in (1, 2):
				states.add(State.EXPANDED)
			elif ec == 0:
				states.add(State.COLLAPSED)
		if role in (Role.EDITABLETEXT, Role.PASSWORDEDIT, Role.DOCUMENT, Role.COMBOBOX):
			if self._prop(uc.P_ISVALUEPATTERNAVAILABLE, False):
				if self._prop(uc.P_VALUEISREADONLY, False):
					states.add(State.READONLY)
				else:
					states.add(State.EDITABLE)
			elif role in (Role.EDITABLETEXT, Role.PASSWORDEDIT):
				states.add(State.EDITABLE)
			if role == Role.DOCUMENT and State.EDITABLE not in states:
				states.add(State.EDITABLE if self._isEditableWordDocument() else State.READONLY)
			if role == Role.EDITABLETEXT and self._isMultiline():
				states.add(State.MULTILINE)
		aria = self.UIAAriaProperties
		if aria:
			if aria.get("multiline") == "true":
				states.add(State.MULTILINE)
			if aria.get("haspopup") not in (None, "", "false"):
				states.add(State.HASPOPUP)
			if aria.get("busy") == "true":
				states.add(State.BUSY)
			# aria-current no es «seleccionado»: se dice con su propio texto
			# («página actual»...; ver ariaCurrent y presentation.ariaCurrentText).
			if aria.get("pressed") == "true":
				states.add(State.PRESSED)
			sort = aria.get("sort")
			if sort == "ascending":
				states.add(State.SORTED_ASCENDING)
			elif sort == "descending":
				states.add(State.SORTED_DESCENDING)
			elif sort == "other":
				states.add(State.SORTED)
		if self._prop(uc.P_ISLEGACYIACCESSIBLEPATTERNAVAILABLE, False):
			legacy = self.UIALegacyState
			if legacy & STATE_SYSTEM_TRAVERSED:
				states.add(State.VISITED)
			if legacy & STATE_SYSTEM_HASPOPUP and role in (Role.MENUITEM, Role.BUTTON, Role.SPLITBUTTON):
				states.add(State.HASPOPUP)
			if legacy & STATE_SYSTEM_BUSY:
				states.add(State.BUSY)
			if legacy & STATE_SYSTEM_MULTISELECTABLE and role in _MULTISELECT_CONTAINERS:
				# Los elementos del Explorador (y de otros puentes MSAA) también llevan
				# la marca: solo cuenta en la lista, no en cada archivo («alfa
				# selección múltiple 1 de 5»).
				states.add(State.MULTISELECTABLE)
			if legacy & STATE_SYSTEM_INVISIBLE and not self.location:
				states.add(State.INVISIBLE)
		if self._prop(uc.P_WINDOWISMODAL, False):
			states.add(State.MODAL)
		return states

	def _get_value(self) -> str:
		role = self.role
		if role in (Role.LINK, Role.HEADING, Role.TABLECELL, Role.STATICTEXT) or role in (
			Role.HEADING1,
			Role.HEADING2,
			Role.HEADING3,
			Role.HEADING4,
			Role.HEADING5,
			Role.HEADING6,
		):
			return ""
		if self._prop(uc.P_ISRANGEVALUEPATTERNAVAILABLE, False) and not self._prop(uc.P_ISVALUEPATTERNAVAILABLE, False):
			val = self._prop(uc.P_RANGEVALUEVALUE, None)
			if val is None:
				return ""
			if role == Role.PROGRESSBAR:
				lo = self._prop(uc.P_RANGEVALUEMINIMUM, 0) or 0
				hi = self._prop(uc.P_RANGEVALUEMAXIMUM, 100) or 100
				try:
					pct = (float(val) - float(lo)) / (float(hi) - float(lo)) * 100 if hi != lo else 0
				except (TypeError, ValueError):
					return str(val)
				return f"{round(pct)}%"
			try:
				f = float(val)
				return str(int(f)) if f.is_integer() else f"{f:g}"
			except (TypeError, ValueError):
				return str(val)
		if self._prop(uc.P_ISVALUEPATTERNAVAILABLE, False):
			val = self._prop(uc.P_VALUEVALUE, "") or ""
			if role == Role.PASSWORDEDIT:
				return ""
			if role == Role.DOCUMENT:
				return ""
			if val == self.name:
				return ""
			return str(val)
		if role == Role.COMBOBOX:
			sel = self._selectedItemNames()
			return ", ".join(sel)
		return ""

	def _selectedItemNames(self, limit: int | None = None) -> list[str]:
		"""Nombres de los elementos seleccionados (solo los ``limit`` primeros)."""
		pat = self._pattern(uc.PAT_SELECTION, UIA.IUIAutomationSelectionPattern)
		if not pat:
			return []
		try:
			arr = pat.GetCurrentSelection()
			n = arr.Length if limit is None else min(arr.Length, limit)
			return [arr.GetElement(i).CurrentName for i in range(n)]
		except comtypes.COMError:
			return []

	def _selectedItemCount(self) -> int | None:
		"""Número de elementos seleccionados (``None`` sin patrón Selection)."""
		pat = self._pattern(uc.PAT_SELECTION, UIA.IUIAutomationSelectionPattern)
		if not pat:
			return None
		try:
			return int(pat.GetCurrentSelection().Length)
		except comtypes.COMError:
			return None

	def _get_description(self) -> str:
		desc = self._prop(uc.P_FULLDESCRIPTION, "") or ""
		if not desc:
			desc = self._prop(uc.P_HELPTEXT, "") or ""
		if desc and desc == self.name:
			return ""
		if desc and looksLikeTypeName(desc, self.UIAClassName):
			# Celdas de DataGridView: «DataGridViewTextBoxCell(DataGridViewCell)».
			return ""
		return desc

	def _get_helpText(self) -> str:
		return self._prop(uc.P_HELPTEXT, "") or ""

	def _get_placeholder(self) -> str:
		return self.UIAAriaProperties.get("placeholder", "")

	def _get_maxLength(self) -> int | None:
		val = self.UIAAriaProperties.get("maxlength", "")
		if val.isdigit():
			return int(val)
		hwnd = int(self._prop(uc.P_NATIVEWINDOWHANDLE, 0) or 0)
		if hwnd and self.role in (Role.EDITABLETEXT, Role.PASSWORDEDIT):
			from ..a11y import win32ctl

			if win32ctl.isEditClass(win32ctl.getClassName(hwnd)):
				limit = win32ctl.editLimitText(hwnd)
				# Los límites por defecto de Windows no son una longitud máxima real.
				if limit and limit < 30000:
					return int(limit)
		if self.UIAFrameworkId in ia2_bridge.WEB_FRAMEWORKS and self.role in (Role.EDITABLETEXT, Role.PASSWORDEDIT, Role.COMBOBOX):
			# Chrome y Edge no ponen maxlength en AriaProperties: está en IA2 (foros 1.17).
			val = self.IA2WebAttributes.get("maxlength", "")
			if val.isdigit() and int(val) > 0:
				return int(val)
		return None

	# ----------------------------------------------------- datos de IA2 (web)
	def _get_IA2WebAttributes(self) -> dict[str, str]:
		"""Atributos IA2 del mismo objeto en las páginas web (lo que UIA no publica)."""
		if self.UIAFrameworkId not in ia2_bridge.WEB_FRAMEWORKS:
			return {}
		return ia2_bridge.attributesForElement(self.element)

	def _get_language(self) -> str | None:
		"""Idioma del objeto: UIA Culture (Chrome y Edge lo heredan del antecesor con
		``lang``) o, en Firefox, ``IAccessible2::locale`` (foros 1.19)."""
		lang = ia2_bridge.languageFromLcid(self._prop(uc.P_CULTURE, 0))
		if lang:
			return lang
		if self.UIAFrameworkId == "Gecko":
			return ia2_bridge.localeForElement(self.element)
		return None

	def _get_graphicFileName(self) -> str:
		"""Nombre del archivo de una imagen web (atributo IA2 ``src``, #7412)."""
		return ia2_bridge.fileNameFromURL(self.IA2WebAttributes.get("src", ""))

	def _get_brailleLabel(self) -> str:
		"""``aria-braillelabel`` (#11829)."""
		return self.UIAAriaProperties.get("braillelabel", "")

	def _get_brailleRoleText(self) -> str:
		"""``aria-brailleroledescription`` (#11829)."""
		return self.UIAAriaProperties.get("brailleroledescription", "")

	def _get_itemStatus(self) -> str:
		return self._prop(uc.P_ITEMSTATUS, "") or ""

	def _get_ariaCurrent(self) -> str:
		value = (self.UIAAriaProperties.get("current") or "").strip().lower()
		return "" if value == "false" else value

	def _get_keyboardShortcut(self) -> str:
		parts = []
		ak = self._prop(uc.P_ACCESSKEY, "") or ""
		acc = self._prop(uc.P_ACCELERATORKEY, "") or ""
		if ak:
			parts.append(ak)
		if acc and acc != ak:
			parts.append(acc)
		return " ".join(parts)

	def _get_location(self) -> tuple[int, int, int, int] | None:
		rect = self._prop(uc.P_BOUNDINGRECT, None)
		if not rect or len(rect) < 4:
			return None
		x, y, w, h = (int(v) for v in rect[:4])
		if w <= 0 and h <= 0:
			return None
		return (x, y, w, h)

	def _get_positionInfo(self) -> dict[str, int]:
		info: dict[str, int] = {}
		pos = self._prop(uc.P_POSITIONINSET, 0) or 0
		size = self._prop(uc.P_SIZEOFSET, 0) or 0
		level = self._prop(uc.P_LEVEL, 0) or 0
		if pos > 0 and size > 0:
			info["indexInGroup"] = int(pos)
			info["similarItemsInGroup"] = int(size)
		if level > 0:
			info["level"] = int(level)
		return info

	def _get_processID(self) -> int:
		return int(self._prop(uc.P_PROCESSID, 0) or 0)

	def _get_windowHandle(self) -> int:
		if self._windowHandle:
			return self._windowHandle
		hwnd = int(self._prop(uc.P_NATIVEWINDOWHANDLE, 0) or 0)
		if not hwnd:
			# Busca el antecesor más cercano con ventana propia.
			try:
				walker = uc.rawWalker
				el = walker.GetParentElement(self.element)
				guard = 0
				while el and guard < 60:
					h = el.CurrentNativeWindowHandle
					if h:
						hwnd = int(h)
						break
					el = walker.GetParentElement(el)
					guard += 1
			except (comtypes.COMError, ValueError):
				pass
		self._windowHandle = hwnd
		return hwnd

	def _get_isFocusable(self) -> bool:
		return bool(self._prop(uc.P_ISKEYBOARDFOCUSABLE, False))

	def _get_hasFocus(self) -> bool:
		return bool(self._prop(uc.P_HASKEYBOARDFOCUS, False))

	# ----------------------------------------------------- navegación
	def _walk(self, method: str) -> "UIAObject | None":
		walker = uc.controlWalker
		try:
			el = getattr(walker, method + "BuildCache")(self.element, uc.baseCacheRequest)
		except (comtypes.COMError, ValueError):
			return None
		if not el:
			return None
		return self._wrap(el)

	def _get_parent(self) -> "UIAObject | None":
		parent = self._walk("GetParentElement")
		if parent is not None:
			try:
				root = uc.getRootElement()
				if uc.compareElements(parent.element, root):
					# El escritorio es la raíz de la navegación.
					return DesktopObject(parent.element)
			except Exception:
				pass
		return parent

	def _get_next(self) -> "UIAObject | None":
		return self._walk("GetNextSiblingElement")

	def _get_previous(self) -> "UIAObject | None":
		return self._walk("GetPreviousSiblingElement")

	def _get_firstChild(self) -> "UIAObject | None":
		return self._walk("GetFirstChildElement")

	def _get_lastChild(self) -> "UIAObject | None":
		return self._walk("GetLastChildElement")

	def _get_children(self) -> list["UIAObject"]:
		try:
			cr = uc.makeCacheRequest(uc.BASE_PROPERTIES, scope=uc.TreeScope_Children)
			cr.TreeFilter = uc.client.ControlViewCondition
			parent = self.element.BuildUpdatedCache(cr)
			arr = parent.GetCachedChildren()
		except (comtypes.COMError, ValueError):
			return super()._get_children()
		if not arr:
			return []
		out = []
		for i in range(arr.Length):
			o = self._wrap(arr.GetElement(i))
			if o is not None:
				out.append(o)
		return out

	# ----------------------------------------------------- acciones
	def setFocus(self) -> None:
		try:
			self.element.SetFocus()
		except comtypes.COMError:
			log.debug("SetFocus falló", exc_info=True)

	def _get_actionName(self) -> str:
		if self._prop(uc.P_ISINVOKEPATTERNAVAILABLE, False):
			return _("pulsar")
		if self._prop(uc.P_ISTOGGLEPATTERNAVAILABLE, False):
			return _("alternar")
		if self._prop(uc.P_ISEXPANDCOLLAPSEPATTERNAVAILABLE, False):
			return _("expandir o contraer")
		if self._prop(uc.P_ISSELECTIONITEMPATTERNAVAILABLE, False):
			return _("seleccionar")
		return _("hacer clic")

	def doAction(self, index: int = 0) -> bool:
		try:
			if self._prop(uc.P_ISINVOKEPATTERNAVAILABLE, False):
				pat = self._pattern(uc.PAT_INVOKE, UIA.IUIAutomationInvokePattern)
				if pat:
					pat.Invoke()
					return True
			if self._prop(uc.P_ISTOGGLEPATTERNAVAILABLE, False):
				pat = self._pattern(uc.PAT_TOGGLE, UIA.IUIAutomationTogglePattern)
				if pat:
					pat.Toggle()
					return True
			if self._prop(uc.P_ISEXPANDCOLLAPSEPATTERNAVAILABLE, False):
				pat = self._pattern(uc.PAT_EXPANDCOLLAPSE, UIA.IUIAutomationExpandCollapsePattern)
				if pat:
					if pat.CurrentExpandCollapseState == 0:
						pat.Expand()
					else:
						pat.Collapse()
					return True
			if self._prop(uc.P_ISSELECTIONITEMPATTERNAVAILABLE, False):
				pat = self._pattern(uc.PAT_SELECTIONITEM, UIA.IUIAutomationSelectionItemPattern)
				if pat:
					pat.Select()
					return True
			if self._prop(uc.P_ISLEGACYIACCESSIBLEPATTERNAVAILABLE, False):
				pat = self._pattern(uc.PAT_LEGACYIACCESSIBLE, UIA.IUIAutomationLegacyIAccessiblePattern)
				if pat and pat.CurrentDefaultAction:
					pat.DoDefaultAction()
					return True
		except comtypes.COMError:
			log.debug("Acción UIA falló", exc_info=True)
		return self.clickCenter()

	def clickCenter(self, button: str = "left") -> bool:
		loc = self.location
		if not loc:
			return False
		from .. import mouse

		x, y, w, h = loc
		mouse.click(x + w // 2, y + h // 2, button=button)
		return True

	def scrollIntoView(self) -> None:
		pat = self._pattern(uc.PAT_SCROLLITEM, UIA.IUIAutomationScrollItemPattern)
		if pat:
			try:
				pat.ScrollIntoView()
			except comtypes.COMError:
				pass

	def expandCollapse(self, expand: bool) -> bool:
		pat = self._pattern(uc.PAT_EXPANDCOLLAPSE, UIA.IUIAutomationExpandCollapsePattern)
		if not pat:
			return False
		try:
			pat.Expand() if expand else pat.Collapse()
			return True
		except comtypes.COMError:
			return False

	def setValue(self, value: str) -> bool:
		pat = self._pattern(uc.PAT_VALUE, UIA.IUIAutomationValuePattern)
		if not pat:
			return False
		try:
			pat.SetValue(value)
			return True
		except comtypes.COMError:
			return False

	# ----------------------------------------------------- texto
	def _get_TextInfo(self):
		if self._prop(uc.P_ISTEXTPATTERNAVAILABLE, False):
			from .uia_text import UIATextInfo

			return UIATextInfo
		if self.role in (Role.EDITABLETEXT, Role.PASSWORDEDIT, Role.DOCUMENT) and self.isEditWindow:
			# Campo Win32 que el proveedor UIA no reconoce (Delphi, VB, Forms…):
			# el texto y el cursor se leen con mensajes de ventana.
			from .iaccessible import EditWindowTextInfo

			return EditWindowTextInfo
		return None

	def _get_isEditWindow(self) -> bool:
		"""El elemento es la propia ventana de un campo de edición Win32."""
		from ..a11y import win32ctl

		hwnd = int(self._prop(uc.P_NATIVEWINDOWHANDLE, 0) or 0)
		return bool(hwnd) and win32ctl.isEditClass(win32ctl.getClassName(hwnd))

	def _get_textPattern(self):
		pat = self._pattern(uc.PAT_TEXT2, UIA.IUIAutomationTextPattern2)
		if pat:
			return pat
		return self._pattern(uc.PAT_TEXT, UIA.IUIAutomationTextPattern)

	_cache_textPattern = False

	def _get_treeInterceptorClass(self):
		from .. import browse

		if browse.shouldUseBrowseMode(self):
			from ..browse.document import BrowseModeDocument

			return BrowseModeDocument
		return None

	# ----------------------------------------------------- tablas
	def _get_tableCellCoords(self) -> tuple[int, int] | None:
		if not self._prop(uc.P_ISGRIDITEMPATTERNAVAILABLE, False):
			return None
		row = self._prop(uc.P_GRIDITEMROW, None)
		col = self._prop(uc.P_GRIDITEMCOLUMN, None)
		if row is None or col is None:
			return None
		return int(row) + 1, int(col) + 1

	def _get_tableHeaders(self) -> tuple[str, str]:
		pat = self._pattern(uc.PAT_TABLEITEM, UIA.IUIAutomationTableItemPattern)
		rowH = colH = ""
		from ..config import conf

		# abbr de los encabezados (#3566): solo Firefox lo publica (atributo IA2).
		useAbbr = self.UIAFrameworkId == "Gecko" and conf["documentFormatting"]["useHeaderAbbreviations"]

		def headerName(el) -> str:
			if useAbbr:
				abbr = ia2_bridge.attributesForElement(el).get("abbr", "").strip()
				if abbr:
					return abbr
			return el.CurrentName

		if pat:
			try:
				arr = pat.GetCurrentColumnHeaderItems()
				if arr and arr.Length:
					colH = " ".join(headerName(arr.GetElement(i)) for i in range(arr.Length))
				arr = pat.GetCurrentRowHeaderItems()
				if arr and arr.Length:
					rowH = " ".join(headerName(arr.GetElement(i)) for i in range(arr.Length))
			except comtypes.COMError:
				pass
		return rowH, colH

	def _get_tableDimensions(self) -> tuple[int, int] | None:
		rows = self._prop(uc.P_GRIDROWCOUNT, None)
		cols = self._prop(uc.P_GRIDCOLUMNCOUNT, None)
		if rows is None or cols is None:
			return None
		return int(rows), int(cols)

	# ----------------------------------------------------- superposiciones
	def findOverlayClasses(self, clsList: list[type]) -> None:
		from . import behaviors

		from .terminal import Terminal

		role = self.role
		cls = self.UIAClassName
		ct = self.UIAControlType
		if (cls in ("ConsoleWindowClass", "TermControl", "TermControl2", "WPFTermControl") and ct != uc.CT_WINDOW) or self.UIAAutomationId == "Text Area" and cls == "":
			clsList.append(Terminal)
		elif (self._prop(uc.P_ISTEXTPATTERNAVAILABLE, False) or self.isEditWindow) and role in (
			Role.EDITABLETEXT,
			Role.PASSWORDEDIT,
			Role.DOCUMENT,
			Role.COMBOBOX,
		):
			if role == Role.DOCUMENT and State.EDITABLE not in self.states:
				clsList.append(behaviors.ReadOnlyDocument)
			else:
				clsList.append(behaviors.EditableTextWithCaret)
		elif role in (Role.EDITABLETEXT, Role.PASSWORDEDIT):
			clsList.append(behaviors.EditableTextNoCaret)
		if role == Role.PROGRESSBAR:
			clsList.append(behaviors.ProgressBar)
		if ct == uc.CT_WINDOW and "ToastView" in self.UIAAutomationId:
			# Notificación emergente de Windows 10/11.
			clsList.append(behaviors.Toast)
		elif cls == "ToastContentHost" and ct == uc.CT_TOOLTIP:
			clsList.append(behaviors.Toast)
		elif role == Role.DIALOG:
			if self.UIAFrameworkId in ("Chrome", "Gecko", "MicrosoftEdge") and not self._prop(uc.P_NATIVEWINDOWHANDLE, 0):
				clsList.append(behaviors.WebDialog)
			else:
				clsList.append(behaviors.Dialog)
		if role in (Role.LISTITEM, Role.DATAITEM, Role.TABLEROW) and self.windowClassName == "SysListView32":
			from .listview import ListViewItem

			clsList.append(ListViewItem)
		elif role in (Role.DATAITEM, Role.TABLEROW) and self._prop(uc.P_ISGRIDITEMPATTERNAVAILABLE, False) is False and self.UIAAriaRole in ("row", ""):
			from .listview import UIATableRow

			clsList.append(UIATableRow)
		if role in (Role.LISTITEM, Role.TREEVIEWITEM, Role.DATAITEM, Role.TABLEROW):
			clsList.append(behaviors.SelectableItem)
		if role in (Role.LIST, Role.TREEVIEW, Role.DATAGRID, Role.TABLE):
			clsList.append(behaviors.ListContainer)

	# ----------------------------------------------------- depuración
	def _get_devInfo(self) -> list[str]:
		info = super()._get_devInfo()
		for label, prop in (
			("UIA ControlType", uc.P_CONTROLTYPE),
			("UIA LocalizedControlType", uc.P_LOCALIZEDCONTROLTYPE),
			("UIA AutomationId", uc.P_AUTOMATIONID),
			("UIA ClassName", uc.P_CLASSNAME),
			("UIA FrameworkId", uc.P_FRAMEWORKID),
			("UIA AriaRole", uc.P_ARIAROLE),
			("UIA AriaProperties", uc.P_ARIAPROPERTIES),
			("UIA ProviderDescription", uc.P_PROVIDERDESCRIPTION),
		):
			try:
				info.append(f"{label}: {self._prop(prop)!r}")
			except Exception as e:
				info.append(f"{label}: {e}")
		info.append(f"UIA RuntimeId: {self.runtimeId!r}")
		return info


class DesktopObject(UIAObject):
	"""El escritorio (raíz del árbol)."""

	def _get_name(self) -> str:
		return _("Escritorio")

	def _get_role(self) -> Role:
		return Role.DESKTOPPANE

	def _get_parent(self) -> None:
		return None

	def _get_next(self) -> None:
		return None

	def _get_previous(self) -> None:
		return None

	def findOverlayClasses(self, clsList: list[type]) -> None:
		pass


def getDesktopObject() -> DesktopObject:
	return DesktopObject(uc.getRootElement())


def getFocusObject() -> AccObject | None:
	"""Objeto con el foco, con la API que corresponda a su ventana."""
	from ..a11y import api_choice

	choice, hwnd = api_choice.chooseAPIForFocus()
	if choice == api_choice.API_MSAA:
		from .iaccessible import IAccessibleObject

		obj = IAccessibleObject.fromFocusedWindow(hwnd)
		if obj is not None:
			return obj
		if _isOwnWindow(hwnd):
			# Ventana de Tiresias con la interfaz ocupada: nada de UIA dentro del
			# propio proceso (se vuelve a mirar el foco cuando la interfaz responda).
			return None
	elif choice == api_choice.API_JAVA:
		from .jab import JABObject

		obj = JABObject.fromFocusedWindow(hwnd)
		if obj is not None:
			return obj
	el = uc.getFocusedElement(uc.baseCacheRequest)
	obj = UIAObject.fromElement(el) if el else None
	if obj is not None and hwnd and isStaleFocus(obj, hwnd):
		# Rev. 1.0.14: UIA sigue dando el foco de la ventana anterior (al volver
		# a WhatsApp u otra aplicación WinUI 3 con WebView2 que no avisa del
		# foco al activarse): se busca el elemento con foco dentro de la
		# ventana que de verdad tiene el foco del teclado.
		fresh = uc.focusedDescendantOfWindow(hwnd, uc.baseCacheRequest)
		fallback = UIAObject.fromElement(fresh) if fresh else None
		if fallback is not None:
			log.debug("Foco UIA caducado (%r): se usa el elemento con foco de la ventana %x", obj, hwnd)
			obj = fallback
	return obj


def isStaleFocus(obj: "UIAObject", focusHwnd: int) -> bool:
	"""``True`` si ``obj`` no pertenece a la ventana con el foco del teclado.

	Cuenta el proceso: el del objeto, o el que lo muestra si es contenido
	incrustado de otro proceso (WebView2, CEF: ``appmodules.handler.hostProcessId``),
	tiene que ser el de la ventana del foco.
	"""
	from ..appmodules import handler as appHandler

	try:
		focusPid = winapi.getWindowProcessId(focusHwnd)
		if not focusPid:
			return False
		objPid = int(obj.processID or 0)
		if not objPid or objPid == focusPid:
			return False
		hwnd = obj.windowHandle
		if not hwnd:
			return False
		root = winapi.getAncestor(hwnd, winapi.GA_ROOT) or hwnd
		return appHandler.hostProcessId(obj, root) != focusPid
	except Exception:
		return False


def _isOwnWindow(hwnd: int) -> bool:
	from ..a11y import own_windows

	return own_windows.mustDelegate(hwnd)


def getObjectFromHandle(hwnd: int) -> UIAObject | None:
	if _isOwnWindow(hwnd):
		# Las ventanas de Tiresias se leen con MSAA en el hilo de la interfaz.
		from .iaccessible import IAccessibleObject

		return IAccessibleObject.fromWindow(hwnd)
	el = uc.elementFromHandle(hwnd)
	return UIAObject.fromElement(el, hwnd) if el else None


def getObjectFromPoint(x: int, y: int) -> AccObject | None:
	"""Objeto en un punto de la pantalla (nunca uno protegido por el bloqueo)."""
	from ..a11y import api_choice, system

	hwnd = winapi.user32.WindowFromPoint(winapi.POINT(x, y)) or 0
	if hwnd and api_choice.chooseAPI(hwnd) == api_choice.API_MSAA:
		from ..a11y import msaa
		from .iaccessible import IAccessibleObject

		res = msaa.accessibleObjectFromPoint(x, y)
		if res is not None:
			obj = IAccessibleObject.fromIAccessible(res[0], res[1])
			if obj is not None:
				return obj
		if _isOwnWindow(hwnd):
			return None
	el = uc.elementFromPoint(x, y)
	return system.filterSecure(UIAObject.fromElement(el)) if el else None


def getForegroundObject() -> UIAObject | None:
	hwnd = winapi.getForegroundWindow()
	if not hwnd:
		return None
	return getObjectFromHandle(hwnd)
