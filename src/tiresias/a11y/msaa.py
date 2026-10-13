"""Cliente MSAA (IAccessible) e IAccessible2.

Envoltorio propio sobre ``oleacc.dll`` con comtypes:

- funciones de obtención de objetos (desde ventana, evento o punto);
- enumeración de hijos (``AccessibleChildren``);
- constantes de roles, estados, eventos WinEvent e identificadores de objeto;
- declaración a mano de las interfaces IAccessible2 que usa Tiresias
  (IAccessible2, IAccessibleText, IAccessibleAction, IAccessibleValue e
  IAccessibleTableCell), siguiendo el orden de la tabla virtual de la
  especificación IAccessible2 1.3.

Todo se usa desde el hilo del núcleo (MTA): COM serializa las llamadas entre
procesos. Las ventanas del propio Tiresias son la excepción: sus objetos se
crean y se leen en el hilo de la interfaz (:mod:`own_windows`).
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import POINTER, byref, c_long, c_void_p, wintypes

import comtypes
import comtypes.client
from comtypes import BSTR, COMMETHOD, GUID, HRESULT, IUnknown
from comtypes.automation import VARIANT

from ..log import getLogger
from . import own_windows

log = getLogger("msaa")

Accessibility = comtypes.client.GetModule("oleacc.dll")
IAccessible = Accessibility.IAccessible

oleacc = ctypes.oledll.oleacc
_oleaccW = ctypes.windll.oleacc
user32 = ctypes.windll.user32

# ------------------------------------------------------------------ constantes
CHILDID_SELF = 0
OBJID_WINDOW = 0
OBJID_SYSMENU = -1
OBJID_TITLEBAR = -2
OBJID_MENU = -3
OBJID_CLIENT = -4
OBJID_VSCROLL = -5
OBJID_HSCROLL = -6
OBJID_CARET = -8
OBJID_CURSOR = -9
OBJID_ALERT = -10
OBJID_NATIVEOM = -16

NAVDIR_UP = 1
NAVDIR_DOWN = 2
NAVDIR_LEFT = 3
NAVDIR_RIGHT = 4
NAVDIR_NEXT = 5
NAVDIR_PREVIOUS = 6
NAVDIR_FIRSTCHILD = 7
NAVDIR_LASTCHILD = 8

SELFLAG_TAKEFOCUS = 1
SELFLAG_TAKESELECTION = 2

# Roles MSAA (ROLE_SYSTEM_*).
ROLE_TITLEBAR = 1
ROLE_MENUBAR = 2
ROLE_SCROLLBAR = 3
ROLE_GRIP = 4
ROLE_SOUND = 5
ROLE_CURSOR = 6
ROLE_CARET = 7
ROLE_ALERT = 8
ROLE_WINDOW = 9
ROLE_CLIENT = 10
ROLE_MENUPOPUP = 11
ROLE_MENUITEM = 12
ROLE_TOOLTIP = 13
ROLE_APPLICATION = 14
ROLE_DOCUMENT = 15
ROLE_PANE = 16
ROLE_CHART = 17
ROLE_DIALOG = 18
ROLE_BORDER = 19
ROLE_GROUPING = 20
ROLE_SEPARATOR = 21
ROLE_TOOLBAR = 22
ROLE_STATUSBAR = 23
ROLE_TABLE = 24
ROLE_COLUMNHEADER = 25
ROLE_ROWHEADER = 26
ROLE_COLUMN = 27
ROLE_ROW = 28
ROLE_CELL = 29
ROLE_LINK = 30
ROLE_HELPBALLOON = 31
ROLE_CHARACTER = 32
ROLE_LIST = 33
ROLE_LISTITEM = 34
ROLE_OUTLINE = 35
ROLE_OUTLINEITEM = 36
ROLE_PAGETAB = 37
ROLE_PROPERTYPAGE = 38
ROLE_INDICATOR = 39
ROLE_GRAPHIC = 40
ROLE_STATICTEXT = 41
ROLE_TEXT = 42
ROLE_PUSHBUTTON = 43
ROLE_CHECKBUTTON = 44
ROLE_RADIOBUTTON = 45
ROLE_COMBOBOX = 46
ROLE_DROPLIST = 47
ROLE_PROGRESSBAR = 48
ROLE_DIAL = 49
ROLE_HOTKEYFIELD = 50
ROLE_SLIDER = 51
ROLE_SPINBUTTON = 52
ROLE_DIAGRAM = 53
ROLE_ANIMATION = 54
ROLE_EQUATION = 55
ROLE_BUTTONDROPDOWN = 56
ROLE_BUTTONMENU = 57
ROLE_BUTTONDROPDOWNGRID = 58
ROLE_WHITESPACE = 59
ROLE_PAGETABLIST = 60
ROLE_CLOCK = 61
ROLE_SPLITBUTTON = 62
ROLE_IPADDRESS = 63
ROLE_OUTLINEBUTTON = 64

# Estados MSAA (STATE_SYSTEM_*).
STATE_UNAVAILABLE = 0x1
STATE_SELECTED = 0x2
STATE_FOCUSED = 0x4
STATE_PRESSED = 0x8
STATE_CHECKED = 0x10
STATE_MIXED = 0x20
STATE_READONLY = 0x40
STATE_HOTTRACKED = 0x80
STATE_DEFAULT = 0x100
STATE_EXPANDED = 0x200
STATE_COLLAPSED = 0x400
STATE_BUSY = 0x800
STATE_FLOATING = 0x1000
STATE_MARQUEED = 0x2000
STATE_ANIMATED = 0x4000
STATE_INVISIBLE = 0x8000
STATE_OFFSCREEN = 0x10000
STATE_SIZEABLE = 0x20000
STATE_MOVEABLE = 0x40000
STATE_SELFVOICING = 0x80000
STATE_FOCUSABLE = 0x100000
STATE_SELECTABLE = 0x200000
STATE_LINKED = 0x400000
STATE_TRAVERSED = 0x800000
STATE_MULTISELECTABLE = 0x1000000
STATE_EXTSELECTABLE = 0x2000000
STATE_ALERT_LOW = 0x4000000
STATE_ALERT_MEDIUM = 0x8000000
STATE_ALERT_HIGH = 0x10000000
STATE_PROTECTED = 0x20000000
STATE_HASPOPUP = 0x40000000

# Eventos WinEvent.
EVENT_SYSTEM_SOUND = 0x0001
EVENT_SYSTEM_ALERT = 0x0002
EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_SYSTEM_MENUSTART = 0x0004
EVENT_SYSTEM_MENUEND = 0x0005
EVENT_SYSTEM_MENUPOPUPSTART = 0x0006
EVENT_SYSTEM_MENUPOPUPEND = 0x0007
EVENT_SYSTEM_CAPTURESTART = 0x0008
EVENT_SYSTEM_DIALOGSTART = 0x0010
EVENT_SYSTEM_DIALOGEND = 0x0011
EVENT_SYSTEM_SCROLLINGSTART = 0x0012
EVENT_SYSTEM_SCROLLINGEND = 0x0013
EVENT_SYSTEM_SWITCHSTART = 0x0014
EVENT_SYSTEM_SWITCHEND = 0x0015
EVENT_SYSTEM_MINIMIZESTART = 0x0016
EVENT_SYSTEM_MINIMIZEEND = 0x0017
EVENT_SYSTEM_DESKTOPSWITCH = 0x0020
EVENT_CONSOLE_CARET = 0x4001
EVENT_CONSOLE_UPDATE_REGION = 0x4002
EVENT_CONSOLE_UPDATE_SIMPLE = 0x4003
EVENT_CONSOLE_UPDATE_SCROLL = 0x4004
EVENT_CONSOLE_LAYOUT = 0x4005
EVENT_CONSOLE_START_APPLICATION = 0x4006
EVENT_CONSOLE_END_APPLICATION = 0x4007
EVENT_OBJECT_CREATE = 0x8000
EVENT_OBJECT_DESTROY = 0x8001
EVENT_OBJECT_SHOW = 0x8002
EVENT_OBJECT_HIDE = 0x8003
EVENT_OBJECT_REORDER = 0x8004
EVENT_OBJECT_FOCUS = 0x8005
EVENT_OBJECT_SELECTION = 0x8006
EVENT_OBJECT_SELECTIONADD = 0x8007
EVENT_OBJECT_SELECTIONREMOVE = 0x8008
EVENT_OBJECT_SELECTIONWITHIN = 0x8009
EVENT_OBJECT_STATECHANGE = 0x800A
EVENT_OBJECT_LOCATIONCHANGE = 0x800B
EVENT_OBJECT_NAMECHANGE = 0x800C
EVENT_OBJECT_DESCRIPTIONCHANGE = 0x800D
EVENT_OBJECT_VALUECHANGE = 0x800E
EVENT_OBJECT_PARENTCHANGE = 0x800F
EVENT_OBJECT_HELPCHANGE = 0x8010
EVENT_OBJECT_DEFACTIONCHANGE = 0x8011
EVENT_OBJECT_ACCELERATORCHANGE = 0x8012
EVENT_OBJECT_INVOKED = 0x8013
EVENT_OBJECT_TEXTSELECTIONCHANGED = 0x8014
EVENT_OBJECT_CONTENTSCROLLED = 0x8015
EVENT_SYSTEM_ARRANGMENTPREVIEW = 0x8016
EVENT_OBJECT_CLOAKED = 0x8017
EVENT_OBJECT_UNCLOAKED = 0x8018
EVENT_OBJECT_LIVEREGIONCHANGED = 0x8019

# Eventos IAccessible2 (enumeración IA2EventID, empieza en 0x101).
IA2_EVENT_ACTION_CHANGED = 0x101
IA2_EVENT_ACTIVE_DESCENDANT_CHANGED = 0x102
IA2_EVENT_DOCUMENT_ATTRIBUTE_CHANGED = 0x103
IA2_EVENT_DOCUMENT_CONTENT_CHANGED = 0x104
IA2_EVENT_DOCUMENT_LOAD_COMPLETE = 0x105
IA2_EVENT_DOCUMENT_LOAD_STOPPED = 0x106
IA2_EVENT_DOCUMENT_RELOAD = 0x107
IA2_EVENT_HYPERLINK_END_INDEX_CHANGED = 0x108
IA2_EVENT_HYPERLINK_NUMBER_OF_ANCHORS_CHANGED = 0x109
IA2_EVENT_HYPERLINK_SELECTED_LINK_CHANGED = 0x10A
IA2_EVENT_HYPERTEXT_LINK_ACTIVATED = 0x10B
IA2_EVENT_HYPERTEXT_LINK_SELECTED = 0x10C
IA2_EVENT_HYPERLINK_START_INDEX_CHANGED = 0x10D
IA2_EVENT_HYPERTEXT_CHANGED = 0x10E
IA2_EVENT_HYPERTEXT_NLINKS_CHANGED = 0x10F
IA2_EVENT_OBJECT_ATTRIBUTE_CHANGED = 0x110
IA2_EVENT_PAGE_CHANGED = 0x111
IA2_EVENT_SECTION_CHANGED = 0x112
IA2_EVENT_TABLE_CAPTION_CHANGED = 0x113
IA2_EVENT_TABLE_COLUMN_DESCRIPTION_CHANGED = 0x114
IA2_EVENT_TABLE_COLUMN_HEADER_CHANGED = 0x115
IA2_EVENT_TABLE_MODEL_CHANGED = 0x116
IA2_EVENT_TABLE_ROW_DESCRIPTION_CHANGED = 0x117
IA2_EVENT_TABLE_ROW_HEADER_CHANGED = 0x118
IA2_EVENT_TABLE_SUMMARY_CHANGED = 0x119
IA2_EVENT_TEXT_ATTRIBUTE_CHANGED = 0x11A
IA2_EVENT_TEXT_CARET_MOVED = 0x11B
IA2_EVENT_TEXT_CHANGED = 0x11C
IA2_EVENT_TEXT_COLUMN_CHANGED = 0x11D
IA2_EVENT_TEXT_INSERTED = 0x11E
IA2_EVENT_TEXT_REMOVED = 0x11F
IA2_EVENT_TEXT_UPDATED = 0x120
IA2_EVENT_TEXT_SELECTION_CHANGED = 0x121
IA2_EVENT_VISIBLE_DATA_CHANGED = 0x122
IA2_EVENT_ROLE_CHANGED = 0x123

# Roles IAccessible2.
IA2_ROLE_UNKNOWN = 0
IA2_ROLE_CANVAS = 0x401
IA2_ROLE_CAPTION = 0x402
IA2_ROLE_CHECK_MENU_ITEM = 0x403
IA2_ROLE_COLOR_CHOOSER = 0x404
IA2_ROLE_DATE_EDITOR = 0x405
IA2_ROLE_DESKTOP_ICON = 0x406
IA2_ROLE_DESKTOP_PANE = 0x407
IA2_ROLE_DIRECTORY_PANE = 0x408
IA2_ROLE_EDITBAR = 0x409
IA2_ROLE_EMBEDDED_OBJECT = 0x40A
IA2_ROLE_ENDNOTE = 0x40B
IA2_ROLE_FILE_CHOOSER = 0x40C
IA2_ROLE_FONT_CHOOSER = 0x40D
IA2_ROLE_FOOTER = 0x40E
IA2_ROLE_FOOTNOTE = 0x40F
IA2_ROLE_FORM = 0x410
IA2_ROLE_FRAME = 0x411
IA2_ROLE_GLASS_PANE = 0x412
IA2_ROLE_HEADER = 0x413
IA2_ROLE_HEADING = 0x414
IA2_ROLE_ICON = 0x415
IA2_ROLE_IMAGE_MAP = 0x416
IA2_ROLE_INPUT_METHOD_WINDOW = 0x417
IA2_ROLE_INTERNAL_FRAME = 0x418
IA2_ROLE_LABEL = 0x419
IA2_ROLE_LAYERED_PANE = 0x41A
IA2_ROLE_NOTE = 0x41B
IA2_ROLE_OPTION_PANE = 0x41C
IA2_ROLE_PAGE = 0x41D
IA2_ROLE_PARAGRAPH = 0x41E
IA2_ROLE_RADIO_MENU_ITEM = 0x41F
IA2_ROLE_REDUNDANT_OBJECT = 0x420
IA2_ROLE_ROOT_PANE = 0x421
IA2_ROLE_RULER = 0x422
IA2_ROLE_SCROLL_PANE = 0x423
IA2_ROLE_SECTION = 0x424
IA2_ROLE_SHAPE = 0x425
IA2_ROLE_SPLIT_PANE = 0x426
IA2_ROLE_TEAR_OFF_MENU = 0x427
IA2_ROLE_TERMINAL = 0x428
IA2_ROLE_TEXT_FRAME = 0x429
IA2_ROLE_TOGGLE_BUTTON = 0x42A
IA2_ROLE_VIEW_PORT = 0x42B
IA2_ROLE_COMPLEMENTARY_CONTENT = 0x42C
IA2_ROLE_LANDMARK = 0x42D
IA2_ROLE_LEVEL_BAR = 0x42E
IA2_ROLE_CONTENT_DELETION = 0x42F
IA2_ROLE_CONTENT_INSERTION = 0x430
IA2_ROLE_BLOCK_QUOTE = 0x431
IA2_ROLE_MARK = 0x432
IA2_ROLE_SUGGESTION = 0x433
IA2_ROLE_COMMENT = 0x434

# Estados IAccessible2 (bits).
IA2_STATE_ACTIVE = 0x1
IA2_STATE_ARMED = 0x2
IA2_STATE_DEFUNCT = 0x4
IA2_STATE_EDITABLE = 0x8
IA2_STATE_HORIZONTAL = 0x10
IA2_STATE_ICONIFIED = 0x20
IA2_STATE_INVALID_ENTRY = 0x40
IA2_STATE_MANAGES_DESCENDANTS = 0x80
IA2_STATE_MODAL = 0x100
IA2_STATE_MULTI_LINE = 0x200
IA2_STATE_OPAQUE = 0x400
IA2_STATE_REQUIRED = 0x800
IA2_STATE_SELECTABLE_TEXT = 0x1000
IA2_STATE_SINGLE_LINE = 0x2000
IA2_STATE_STALE = 0x4000
IA2_STATE_SUPPORTS_AUTOCOMPLETION = 0x8000
IA2_STATE_TRANSIENT = 0x10000
IA2_STATE_VERTICAL = 0x20000
IA2_STATE_CHECKABLE = 0x40000
IA2_STATE_PINNED = 0x80000

IA2_TEXT_BOUNDARY_CHAR = 0
IA2_TEXT_BOUNDARY_WORD = 1
IA2_TEXT_BOUNDARY_SENTENCE = 2
IA2_TEXT_BOUNDARY_PARAGRAPH = 3
IA2_TEXT_BOUNDARY_LINE = 4
IA2_TEXT_BOUNDARY_ALL = 5
IA2_TEXT_OFFSET_LENGTH = -1
IA2_TEXT_OFFSET_CARET = -2
IA2_COORDTYPE_SCREEN_RELATIVE = 0
IA2_SCROLL_TYPE_ANYWHERE = 6

#: Carácter que representa un objeto incrustado en el texto IAccessible2.
EMBEDDED_OBJECT_CHAR = "￼"


# ------------------------------------------------------------------ interfaces IA2
class IA2TextSegment(ctypes.Structure):
	_fields_ = [("text", BSTR), ("start", c_long), ("end", c_long)]


class IAccessible2(IAccessible):
	_iid_ = GUID("{E89F726E-C4F4-4C19-BB19-B647D7FA8478}")
	_idlflags_ = []
	_methods_ = [
		COMMETHOD(["propget"], HRESULT, "nRelations", (["out", "retval"], POINTER(c_long), "nRelations")),
		# relation, relations: no se usan; solo ocupan su lugar en la tabla virtual.
		COMMETHOD(["propget"], HRESULT, "relation", (["in"], c_long, "relationIndex"), (["in"], c_void_p, "relation")),
		COMMETHOD(["propget"], HRESULT, "relations", (["in"], c_long, "maxRelations"), (["in"], c_void_p, "relations"), (["in"], c_void_p, "nRelations")),
		COMMETHOD([], HRESULT, "role", (["out", "retval"], POINTER(c_long), "role")),
		COMMETHOD([], HRESULT, "scrollTo", (["in"], c_long, "scrollType")),
		COMMETHOD([], HRESULT, "scrollToPoint", (["in"], c_long, "coordinateType"), (["in"], c_long, "x"), (["in"], c_long, "y")),
		COMMETHOD(
			["propget"],
			HRESULT,
			"groupPosition",
			(["out"], POINTER(c_long), "groupLevel"),
			(["out"], POINTER(c_long), "similarItemsInGroup"),
			(["out", "retval"], POINTER(c_long), "positionInGroup"),
		),
		COMMETHOD(["propget"], HRESULT, "states", (["out", "retval"], POINTER(c_long), "states")),
		COMMETHOD(["propget"], HRESULT, "extendedRole", (["out", "retval"], POINTER(BSTR), "extendedRole")),
		COMMETHOD(["propget"], HRESULT, "localizedExtendedRole", (["out", "retval"], POINTER(BSTR), "localizedExtendedRole")),
		COMMETHOD(["propget"], HRESULT, "nExtendedStates", (["out", "retval"], POINTER(c_long), "nExtendedStates")),
		COMMETHOD(["propget"], HRESULT, "extendedStates", (["in"], c_long, "maxExtendedStates"), (["in"], c_void_p, "extendedStates"), (["in"], c_void_p, "nExtendedStates")),
		COMMETHOD(["propget"], HRESULT, "localizedExtendedStates", (["in"], c_long, "maxExtendedStates"), (["in"], c_void_p, "extendedStates"), (["in"], c_void_p, "nExtendedStates")),
		COMMETHOD(["propget"], HRESULT, "uniqueID", (["out", "retval"], POINTER(c_long), "uniqueID")),
		COMMETHOD(["propget"], HRESULT, "windowHandle", (["out", "retval"], POINTER(wintypes.HWND), "windowHandle")),
		COMMETHOD(["propget"], HRESULT, "indexInParent", (["out", "retval"], POINTER(c_long), "indexInParent")),
		COMMETHOD(["propget"], HRESULT, "locale", (["in"], c_void_p, "locale")),
		COMMETHOD(["propget"], HRESULT, "attributes", (["out", "retval"], POINTER(BSTR), "attributes")),
	]


class IAccessibleText(IUnknown):
	_iid_ = GUID("{24FD2FFB-3AAD-4A08-8335-A3AD89C0FB4B}")
	_idlflags_ = []
	_methods_ = [
		COMMETHOD([], HRESULT, "addSelection", (["in"], c_long, "startOffset"), (["in"], c_long, "endOffset")),
		COMMETHOD(
			["propget"],
			HRESULT,
			"attributes",
			(["in"], c_long, "offset"),
			(["out"], POINTER(c_long), "startOffset"),
			(["out"], POINTER(c_long), "endOffset"),
			(["out", "retval"], POINTER(BSTR), "textAttributes"),
		),
		COMMETHOD(["propget"], HRESULT, "caretOffset", (["out", "retval"], POINTER(c_long), "offset")),
		COMMETHOD(
			[],
			HRESULT,
			"characterExtents",
			(["in"], c_long, "offset"),
			(["in"], c_long, "coordType"),
			(["out"], POINTER(c_long), "x"),
			(["out"], POINTER(c_long), "y"),
			(["out"], POINTER(c_long), "width"),
			(["out", "retval"], POINTER(c_long), "height"),
		),
		COMMETHOD(["propget"], HRESULT, "nSelections", (["out", "retval"], POINTER(c_long), "nSelections")),
		COMMETHOD(
			[],
			HRESULT,
			"offsetAtPoint",
			(["in"], c_long, "x"),
			(["in"], c_long, "y"),
			(["in"], c_long, "coordType"),
			(["out", "retval"], POINTER(c_long), "offset"),
		),
		COMMETHOD(
			["propget"],
			HRESULT,
			"selection",
			(["in"], c_long, "selectionIndex"),
			(["out"], POINTER(c_long), "startOffset"),
			(["out", "retval"], POINTER(c_long), "endOffset"),
		),
		COMMETHOD(["propget"], HRESULT, "text", (["in"], c_long, "startOffset"), (["in"], c_long, "endOffset"), (["out", "retval"], POINTER(BSTR), "text")),
		COMMETHOD(
			[],
			HRESULT,
			"textBeforeOffset",
			(["in"], c_long, "offset"),
			(["in"], c_long, "boundaryType"),
			(["out"], POINTER(c_long), "startOffset"),
			(["out"], POINTER(c_long), "endOffset"),
			(["out", "retval"], POINTER(BSTR), "text"),
		),
		COMMETHOD(
			[],
			HRESULT,
			"textAfterOffset",
			(["in"], c_long, "offset"),
			(["in"], c_long, "boundaryType"),
			(["out"], POINTER(c_long), "startOffset"),
			(["out"], POINTER(c_long), "endOffset"),
			(["out", "retval"], POINTER(BSTR), "text"),
		),
		COMMETHOD(
			[],
			HRESULT,
			"textAtOffset",
			(["in"], c_long, "offset"),
			(["in"], c_long, "boundaryType"),
			(["out"], POINTER(c_long), "startOffset"),
			(["out"], POINTER(c_long), "endOffset"),
			(["out", "retval"], POINTER(BSTR), "text"),
		),
		COMMETHOD([], HRESULT, "removeSelection", (["in"], c_long, "selectionIndex")),
		COMMETHOD([], HRESULT, "setCaretOffset", (["in"], c_long, "offset")),
		COMMETHOD([], HRESULT, "setSelection", (["in"], c_long, "selectionIndex"), (["in"], c_long, "startOffset"), (["in"], c_long, "endOffset")),
		COMMETHOD(["propget"], HRESULT, "nCharacters", (["out", "retval"], POINTER(c_long), "nCharacters")),
		COMMETHOD([], HRESULT, "scrollSubstringTo", (["in"], c_long, "startIndex"), (["in"], c_long, "endIndex"), (["in"], c_long, "scrollType")),
		COMMETHOD(
			[],
			HRESULT,
			"scrollSubstringToPoint",
			(["in"], c_long, "startIndex"),
			(["in"], c_long, "endIndex"),
			(["in"], c_long, "coordinateType"),
			(["in"], c_long, "x"),
			(["in"], c_long, "y"),
		),
		COMMETHOD(["propget"], HRESULT, "newText", (["out", "retval"], POINTER(IA2TextSegment), "newText")),
		COMMETHOD(["propget"], HRESULT, "oldText", (["out", "retval"], POINTER(IA2TextSegment), "oldText")),
	]


class IAccessibleAction(IUnknown):
	_iid_ = GUID("{B70D9F59-3B5A-4DBA-AB9E-22012F607DF5}")
	_idlflags_ = []
	_methods_ = [
		COMMETHOD([], HRESULT, "nActions", (["out", "retval"], POINTER(c_long), "nActions")),
		COMMETHOD([], HRESULT, "doAction", (["in"], c_long, "actionIndex")),
		COMMETHOD(["propget"], HRESULT, "description", (["in"], c_long, "actionIndex"), (["out", "retval"], POINTER(BSTR), "description")),
		COMMETHOD(["propget"], HRESULT, "keyBinding", (["in"], c_long, "actionIndex"), (["in"], c_long, "nMaxBindings"), (["in"], c_void_p, "keyBinding"), (["in"], c_void_p, "nBinding")),
		COMMETHOD(["propget"], HRESULT, "name", (["in"], c_long, "actionIndex"), (["out", "retval"], POINTER(BSTR), "name")),
		COMMETHOD(["propget"], HRESULT, "localizedName", (["in"], c_long, "actionIndex"), (["out", "retval"], POINTER(BSTR), "localizedName")),
	]


class IAccessibleValue(IUnknown):
	_iid_ = GUID("{35855B5B-C566-4FD0-A7B1-E65465600394}")
	_idlflags_ = []
	_methods_ = [
		COMMETHOD(["propget"], HRESULT, "currentValue", (["out", "retval"], POINTER(VARIANT), "currentValue")),
		COMMETHOD([], HRESULT, "setCurrentValue", (["in"], VARIANT, "value")),
		COMMETHOD(["propget"], HRESULT, "maximumValue", (["out", "retval"], POINTER(VARIANT), "maximumValue")),
		COMMETHOD(["propget"], HRESULT, "minimumValue", (["out", "retval"], POINTER(VARIANT), "minimumValue")),
	]


class IAccessibleTableCell(IUnknown):
	_iid_ = GUID("{594116B1-C99F-4847-AD06-0A7A86ECE645}")
	_idlflags_ = []
	_methods_ = [
		COMMETHOD(["propget"], HRESULT, "columnExtent", (["out", "retval"], POINTER(c_long), "nColumnsSpanned")),
		COMMETHOD(["propget"], HRESULT, "columnHeaderCells", (["in"], c_void_p, "cellAccessibles"), (["in"], c_void_p, "nColumnHeaderCells")),
		COMMETHOD(["propget"], HRESULT, "columnIndex", (["out", "retval"], POINTER(c_long), "columnIndex")),
		COMMETHOD(["propget"], HRESULT, "rowExtent", (["out", "retval"], POINTER(c_long), "nRowsSpanned")),
		COMMETHOD(["propget"], HRESULT, "rowHeaderCells", (["in"], c_void_p, "cellAccessibles"), (["in"], c_void_p, "nRowHeaderCells")),
		COMMETHOD(["propget"], HRESULT, "rowIndex", (["out", "retval"], POINTER(c_long), "rowIndex")),
	]


# ------------------------------------------------------------------ prototipos oleacc
oleacc.AccessibleObjectFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD, POINTER(GUID), POINTER(POINTER(IAccessible))]
oleacc.AccessibleObjectFromEvent.argtypes = [wintypes.HWND, wintypes.DWORD, wintypes.DWORD, POINTER(POINTER(IAccessible)), POINTER(VARIANT)]
oleacc.AccessibleObjectFromPoint.argtypes = [wintypes.POINT, POINTER(POINTER(IAccessible)), POINTER(VARIANT)]
oleacc.AccessibleChildren.argtypes = [POINTER(IAccessible), c_long, c_long, POINTER(VARIANT), POINTER(c_long)]
oleacc.WindowFromAccessibleObject.argtypes = [POINTER(IAccessible), POINTER(wintypes.HWND)]
_oleaccW.GetRoleTextW.argtypes = [wintypes.DWORD, wintypes.LPWSTR, wintypes.UINT]
_oleaccW.GetRoleTextW.restype = wintypes.UINT
user32.IsHungAppWindow.argtypes = [wintypes.HWND]
user32.IsHungAppWindow.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.GetDesktopWindow.restype = wintypes.HWND
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND


def _dword(value: int) -> int:
	return value & 0xFFFFFFFF


# ------------------------------------------------------------------ ventanas de otros procesos
# ``AccessibleObjectFromWindow`` y ``AccessibleObjectFromEvent`` envían
# ``WM_GETOBJECT`` a la ventana con un ``SendMessage`` sin tiempo máximo: si el
# hilo de esa ventana está ocupado y no atiende mensajes (una aplicación que
# crea muchas ventanas al arrancar, por ejemplo), el núcleo se queda esperando
# lo que tarde. ``IsHungAppWindow`` no basta: Windows solo marca una aplicación
# como colgada cuando lleva 5 s sin atender mensajes, y la comprobación se hace
# antes de la llamada. En una ejecución de prueba el núcleo se quedó así 10 s
# con el foco de una lista (``SysListView32``) de otro proceso.
#
# Por eso, con las ventanas de OTROS procesos, ``WM_GETOBJECT`` se envía aquí
# con ``SendMessageTimeout`` y un tiempo máximo, y la respuesta se convierte
# con ``ObjectFromLresult`` (o con el objeto estándar del sistema si la ventana
# no tiene servidor propio), que es lo mismo que hace oleacc por dentro. El
# hilo que no responde a tiempo se recuerda unos segundos y sus ventanas se
# omiten al instante, salvo que una sonda muy corta muestre que ya responde
# (igual que se hace con los proveedores UIA lentos).

#: Tiempo máximo (ms) que se espera a que otra aplicación atienda ``WM_GETOBJECT``.
GETOBJECT_TIMEOUT_MS = 1500
#: Segundos que se recuerda un hilo que no respondió a tiempo.
SLOW_WINDOW_SECONDS = 10.0
#: Tiempo máximo (ms) de la sonda que comprueba si un hilo lento ya responde.
PROBE_TIMEOUT_MS = 50

WM_NULL = 0x0000
WM_GETOBJECT = 0x003D
SMTO_ABORTIFHUNG = 0x0002

_user32p = ctypes.WinDLL("user32", use_last_error=True)
_user32p.SendMessageTimeoutW.argtypes = [
	wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM, wintypes.UINT, wintypes.UINT, POINTER(ctypes.c_size_t),
]
_user32p.SendMessageTimeoutW.restype = wintypes.LPARAM
_user32p.GetWindowThreadProcessId.argtypes = [wintypes.HWND, POINTER(wintypes.DWORD)]
_user32p.GetWindowThreadProcessId.restype = wintypes.DWORD
_oleaccP = ctypes.OleDLL("oleacc")
_oleaccP.ObjectFromLresult.argtypes = [wintypes.LPARAM, POINTER(GUID), wintypes.WPARAM, c_void_p]
_oleaccP.CreateStdAccessibleObject.argtypes = [wintypes.HWND, c_long, POINTER(GUID), c_void_p]

_OWN_PID = os.getpid()
#: Hilos (de otros procesos) que no atendieron a tiempo: id del hilo -> instante límite.
_slowThreads: dict[int, float] = {}


def _windowThreadProcess(hwnd: int) -> tuple[int, int]:
	pid = wintypes.DWORD()
	try:
		tid = _user32p.GetWindowThreadProcessId(hwnd, byref(pid))
	except Exception:
		return 0, 0
	return int(tid or 0), int(pid.value or 0)


def _isForeignWindow(hwnd: int) -> bool:
	"""``True`` si ``hwnd`` es de otro proceso (las propias van por :mod:`own_windows`)."""
	_tid, pid = _windowThreadProcess(hwnd)
	return bool(pid) and pid != _OWN_PID


def _sendMessageTimeout(hwnd: int, msg: int, wParam: int, lParam: int, timeoutMs: int) -> int | None:
	"""``SendMessageTimeout``: el resultado del mensaje, o ``None`` si no respondió a tiempo."""
	result = ctypes.c_size_t()
	try:
		ok = _user32p.SendMessageTimeoutW(hwnd, msg, wParam, lParam, SMTO_ABORTIFHUNG, timeoutMs, byref(result))
	except Exception:
		return None
	if not ok:
		return None
	return int(result.value)


def markSlowWindow(hwnd: int, seconds: float = SLOW_WINDOW_SECONDS) -> None:
	"""Recuerda que el hilo de ``hwnd`` no respondió: sus ventanas se omiten unos segundos."""
	tid, pid = _windowThreadProcess(hwnd)
	if not tid:
		return
	if tid not in _slowThreads:
		log.info("La ventana %x (proceso %d) no responde a MSAA: se omite durante %d s", hwnd, pid, int(seconds))
	_slowThreads[tid] = time.monotonic() + seconds


def isSlowWindow(hwnd: int) -> bool:
	"""``True`` si el hilo de ``hwnd`` no respondió hace poco y sigue sin responder."""
	if not _slowThreads:
		return False
	tid, _pid = _windowThreadProcess(hwnd)
	until = _slowThreads.get(tid)
	if until is None:
		return False
	if time.monotonic() >= until or _sendMessageTimeout(hwnd, WM_NULL, 0, 0, PROBE_TIMEOUT_MS) is not None:
		# Caducó, o ya atiende mensajes: se vuelve a leer con normalidad.
		_slowThreads.pop(tid, None)
		return False
	return True


def _foreignObjectFromWindow(hwnd: int, objectId: int, interface=None):
	"""``AccessibleObjectFromWindow`` con tiempo máximo (ventanas de otros procesos)."""
	interface = interface or IAccessible
	res = _sendMessageTimeout(hwnd, WM_GETOBJECT, 0, _dword(objectId), GETOBJECT_TIMEOUT_MS)
	if res is None:
		if user32.IsWindow(hwnd):
			markSlowWindow(hwnd)
		return None
	p = POINTER(interface)()
	try:
		if res:
			_oleaccP.ObjectFromLresult(res, byref(interface._iid_), 0, byref(p))
		else:
			_oleaccP.CreateStdAccessibleObject(hwnd, objectId, byref(interface._iid_), byref(p))
	except (OSError, comtypes.COMError):
		return None
	return p if p else None


def _isUsableWindow(hwnd: int) -> bool:
	try:
		return bool(hwnd) and bool(user32.IsWindow(hwnd)) and not user32.IsHungAppWindow(hwnd) and not isSlowWindow(hwnd)
	except Exception:
		return False


def accessibleObjectFromWindow(hwnd: int, objectId: int = OBJID_CLIENT):
	"""``IAccessible`` de una ventana (``None`` si falla o la ventana no responde).

	Para las ventanas del propio Tiresias se crea en el hilo de la interfaz y
	se devuelve un :class:`own_windows.OwnAccessible` (ver ese módulo).
	"""
	if not _isUsableWindow(hwnd):
		return None
	if own_windows.mustDelegate(hwnd):
		return own_windows.fromHwnd(hwnd, _accessibleObjectFromWindow, objectId)
	return _accessibleObjectFromWindow(hwnd, objectId)


def _accessibleObjectFromWindow(hwnd: int, objectId: int):
	if _isForeignWindow(hwnd):
		return _foreignObjectFromWindow(hwnd, objectId)
	p = POINTER(IAccessible)()
	try:
		oleacc.AccessibleObjectFromWindow(hwnd, _dword(objectId), byref(IAccessible._iid_), byref(p))
	except (OSError, comtypes.COMError):
		return None
	return p if p else None


def accessibleObjectFromEvent(hwnd: int, objectId: int, childId: int):
	"""Devuelve ``(IAccessible, childId)`` del objeto que generó un WinEvent."""
	if not _isUsableWindow(hwnd):
		return None
	if own_windows.mustDelegate(hwnd):
		return own_windows.fromHwnd(hwnd, _accessibleObjectFromEvent, objectId, childId)
	return _accessibleObjectFromEvent(hwnd, objectId, childId)


def _accessibleObjectFromEvent(hwnd: int, objectId: int, childId: int):
	if _isForeignWindow(hwnd):
		return _foreignObjectFromEvent(hwnd, objectId, childId)
	p = POINTER(IAccessible)()
	var = VARIANT()
	try:
		oleacc.AccessibleObjectFromEvent(hwnd, _dword(objectId), _dword(childId), byref(p), byref(var))
	except (OSError, comtypes.COMError):
		return None
	if not p:
		return None
	child = var.value
	return p, int(child) if isinstance(child, int) else CHILDID_SELF


def _foreignObjectFromEvent(hwnd: int, objectId: int, childId: int):
	"""``AccessibleObjectFromEvent`` con tiempo máximo (ventanas de otros procesos).

	Como oleacc: el objeto de la ventana y, si el evento es de un hijo, ese
	hijo si es un objeto completo; si no, el contenedor con su ``childId``.
	"""
	pacc = _foreignObjectFromWindow(hwnd, objectId)
	if pacc is None:
		return None
	if childId == CHILDID_SELF:
		return pacc, CHILDID_SELF
	try:
		child = normalizeIAccessible(pacc.accChild(childId))
	except (comtypes.COMError, OSError, ValueError, TypeError):
		child = None
	if child is not None:
		return child, CHILDID_SELF
	return pacc, childId


def accessibleObjectFromPoint(x: int, y: int):
	"""``(IAccessible, childId)`` del punto (en el hilo de la interfaz si es una ventana propia)."""
	try:
		hwnd = user32.WindowFromPoint(wintypes.POINT(x, y)) or 0
	except Exception:
		hwnd = 0
	if hwnd and own_windows.mustDelegate(hwnd):
		return own_windows.fromHwnd(hwnd, lambda _h: _accessibleObjectFromPoint(x, y))
	if hwnd and _isForeignWindow(hwnd):
		# Sin servidor que espere: si la ventana no atiende mensajes, no se pregunta.
		if isSlowWindow(hwnd):
			return None
		if _sendMessageTimeout(hwnd, WM_NULL, 0, 0, GETOBJECT_TIMEOUT_MS) is None:
			markSlowWindow(hwnd)
			return None
	return _accessibleObjectFromPoint(x, y)


def _accessibleObjectFromPoint(x: int, y: int):
	p = POINTER(IAccessible)()
	var = VARIANT()
	try:
		oleacc.AccessibleObjectFromPoint(wintypes.POINT(x, y), byref(p), byref(var))
	except (OSError, comtypes.COMError):
		return None
	if not p:
		return None
	child = var.value
	return p, int(child) if isinstance(child, int) else CHILDID_SELF


def windowFromAccessibleObject(pacc) -> int:
	if isinstance(pacc, own_windows.OwnAccessible):
		try:
			return own_windows.runWith(pacc, windowFromAccessibleObject)
		except OSError:
			return 0
	hwnd = wintypes.HWND()
	try:
		oleacc.WindowFromAccessibleObject(pacc, byref(hwnd))
	except (OSError, comtypes.COMError, ctypes.ArgumentError):
		return 0
	return hwnd.value or 0


def normalizeIAccessible(value):
	"""Convierte un ``IDispatch``/``IUnknown`` en ``IAccessible`` (o ``None``)."""
	if value is None:
		return None
	try:
		if not bool(value):
			return None
	except (ValueError, comtypes.COMError):
		return None
	if isinstance(value, POINTER(IAccessible)):
		return value
	if isinstance(value, own_windows.OwnAccessible) and value.isIAccessible:
		return value
	try:
		return value.QueryInterface(IAccessible)
	except (comtypes.COMError, AttributeError, ValueError, OSError):
		return None


def accessibleChildren(pacc, start: int, count: int) -> list:
	"""Hijos de ``pacc``: lista de ``(IAccessible, childId)``."""
	if count <= 0:
		return []
	if isinstance(pacc, own_windows.OwnAccessible):
		try:
			return own_windows.runWith(pacc, accessibleChildren, start, count)
		except OSError:
			return []
	count = min(count, 10000)
	arr = (VARIANT * count)()
	obtained = c_long()
	try:
		oleacc.AccessibleChildren(pacc, start, count, arr, byref(obtained))
	except (OSError, comtypes.COMError, ctypes.ArgumentError):
		return []
	out = []
	for i in range(obtained.value):
		val = arr[i].value
		if isinstance(val, int):
			out.append((pacc, val))
			continue
		acc = normalizeIAccessible(val)
		if acc is not None:
			out.append((acc, CHILDID_SELF))
	return out


def getRoleText(role: int) -> str:
	buf = ctypes.create_unicode_buffer(128)
	try:
		_oleaccW.GetRoleTextW(role, buf, 128)
	except Exception:
		return ""
	return buf.value


def queryIAccessible2(pacc):
	"""``IAccessible2`` del objeto (por QueryService o QueryInterface) o ``None``."""
	if pacc is None:
		return None
	if isinstance(pacc, own_windows.OwnAccessible):
		# Las ventanas de Tiresias (wx y controles de Windows) no implementan IA2.
		return None
	try:
		sp = pacc.QueryInterface(comtypes.IServiceProvider)
		ia2 = sp.QueryService(IAccessible._iid_, IAccessible2)
		if ia2:
			return ia2
	except (comtypes.COMError, AttributeError, ValueError, OSError):
		pass
	try:
		return pacc.QueryInterface(IAccessible2)
	except (comtypes.COMError, AttributeError, ValueError):
		return None


def queryInterface(ptr, iface):
	if ptr is None:
		return None
	try:
		return ptr.QueryInterface(iface)
	except (comtypes.COMError, AttributeError, ValueError, OSError):
		return None


def parseIA2Attributes(text: str | None) -> dict[str, str]:
	"""Analiza ``clave:valor;clave2:valor2`` (con escapes ``\\``)."""
	out: dict[str, str] = {}
	if not text:
		return out
	key: list[str] = []
	val: list[str] = []
	cur = key
	escape = False
	for ch in text:
		if escape:
			cur.append(ch)
			escape = False
		elif ch == "\\":
			escape = True
		elif ch == ":" and cur is key:
			cur = val
		elif ch == ";":
			if key:
				out["".join(key).strip()] = "".join(val)
			key, val = [], []
			cur = key
		else:
			cur.append(ch)
	if key:
		out["".join(key).strip()] = "".join(val)
	return out


def isDesktopWindow(hwnd: int) -> bool:
	try:
		return hwnd == (user32.GetDesktopWindow() or 0)
	except Exception:
		return False
