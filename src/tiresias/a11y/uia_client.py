"""Cliente de UI Automation (UIA).

Se inicializa en el hilo del núcleo (apartamento MTA). Expone el objeto
cliente, los andadores del árbol y solicitudes de caché reutilizables.
"""

from __future__ import annotations

import ctypes

import comtypes
import comtypes.client

from ..log import getLogger

log = getLogger("uia")

UIA = comtypes.client.GetModule("UIAutomationCore.dll")

client = None  # IUIAutomation (la versión más alta disponible)
rawWalker = None
controlWalker = None
baseCacheRequest = None
treeCacheRequest = None
trueCondition = None
_version = 1

# ------------------------------------------------------------------ constantes
TreeScope_Element = 1
TreeScope_Children = 2
TreeScope_Descendants = 4
TreeScope_Subtree = 7
TreeScope_Parent = 8
TreeScope_Ancestors = 16

P_RUNTIMEID = 30000
P_BOUNDINGRECT = 30001
P_PROCESSID = 30002
P_CONTROLTYPE = 30003
P_LOCALIZEDCONTROLTYPE = 30004
P_NAME = 30005
P_ACCELERATORKEY = 30006
P_ACCESSKEY = 30007
P_HASKEYBOARDFOCUS = 30008
P_ISKEYBOARDFOCUSABLE = 30009
P_ISENABLED = 30010
P_AUTOMATIONID = 30011
P_CLASSNAME = 30012
P_HELPTEXT = 30013
P_CULTURE = 30015
P_ISCONTROLELEMENT = 30016
P_ISCONTENTELEMENT = 30017
P_LABELEDBY = 30018
P_ISPASSWORD = 30019
P_NATIVEWINDOWHANDLE = 30020
P_ITEMTYPE = 30021
P_ISOFFSCREEN = 30022
P_ORIENTATION = 30023
P_FRAMEWORKID = 30024
P_ISREQUIREDFORFORM = 30025
P_ITEMSTATUS = 30026
P_ISVALUEPATTERNAVAILABLE = 30043
P_ISTEXTPATTERNAVAILABLE = 30040
P_ISINVOKEPATTERNAVAILABLE = 30031
P_ISTOGGLEPATTERNAVAILABLE = 30041
P_ISSELECTIONITEMPATTERNAVAILABLE = 30036
P_ISEXPANDCOLLAPSEPATTERNAVAILABLE = 30028
P_ISRANGEVALUEPATTERNAVAILABLE = 30033
P_ISGRIDITEMPATTERNAVAILABLE = 30029
P_ISTABLEITEMPATTERNAVAILABLE = 30039
P_ISLEGACYIACCESSIBLEPATTERNAVAILABLE = 30090
P_VALUEVALUE = 30045
P_VALUEISREADONLY = 30046
P_RANGEVALUEVALUE = 30047
P_RANGEVALUEISREADONLY = 30048
P_RANGEVALUEMINIMUM = 30049
P_RANGEVALUEMAXIMUM = 30050
P_RANGEVALUELARGECHANGE = 30051
P_RANGEVALUESMALLCHANGE = 30052
P_SELECTIONCANSELECTMULTIPLE = 30060
P_GRIDROWCOUNT = 30062
P_GRIDCOLUMNCOUNT = 30063
P_GRIDITEMROW = 30064
P_GRIDITEMCOLUMN = 30065
P_GRIDITEMROWSPAN = 30066
P_GRIDITEMCOLUMNSPAN = 30067
P_EXPANDCOLLAPSESTATE = 30070
P_WINDOWISMODAL = 30077
P_SELECTIONITEMISSELECTED = 30079
P_TOGGLESTATE = 30086
P_LEGACYROLE = 30095
P_LEGACYSTATE = 30096
P_LEGACYDEFAULTACTION = 30100
P_LEGACYVALUE = 30093
P_LEGACYDESCRIPTION = 30094
P_ARIAROLE = 30101
P_ARIAPROPERTIES = 30102
P_ISDATAVALIDFORFORM = 30103
P_CONTROLLERFOR = 30104
P_DESCRIBEDBY = 30105
P_FLOWSTO = 30106
P_PROVIDERDESCRIPTION = 30107
P_LIVESETTING = 30135
P_POSITIONINSET = 30152
P_SIZEOFSET = 30153
P_LEVEL = 30154
P_ANNOTATIONTYPES = 30155
P_LANDMARKTYPE = 30157
P_LOCALIZEDLANDMARKTYPE = 30158
P_FULLDESCRIPTION = 30159
P_HEADINGLEVEL = 30173
P_ISDIALOG = 30174

PAT_INVOKE = 10000
PAT_SELECTION = 10001
PAT_VALUE = 10002
PAT_RANGEVALUE = 10003
PAT_SCROLL = 10004
PAT_EXPANDCOLLAPSE = 10005
PAT_GRID = 10006
PAT_GRIDITEM = 10007
PAT_WINDOW = 10009
PAT_SELECTIONITEM = 10010
PAT_TABLE = 10012
PAT_TABLEITEM = 10013
PAT_TEXT = 10014
PAT_TOGGLE = 10015
PAT_SCROLLITEM = 10017
PAT_LEGACYIACCESSIBLE = 10018
PAT_TEXT2 = 10024
PAT_TEXTEDIT = 10032

#: UIA_IsReadOnlyAttributeId (atributo de texto de un rango).
A_ISREADONLY = 40015

E_TOOLTIPOPENED = 20000
E_STRUCTURECHANGED = 20002
E_MENUOPENED = 20003
E_PROPERTYCHANGED = 20004
E_FOCUSCHANGED = 20005
E_ASYNCCONTENTLOADED = 20006
E_MENUCLOSED = 20007
E_LAYOUTINVALIDATED = 20008
E_INVOKED = 20009
E_ELEMENTADDEDTOSELECTION = 20010
E_ELEMENTREMOVEDFROMSELECTION = 20011
E_ELEMENTSELECTED = 20012
E_SELECTIONINVALIDATED = 20013
E_TEXTSELECTIONCHANGED = 20014
E_TEXTCHANGED = 20015
E_WINDOWOPENED = 20016
E_WINDOWCLOSED = 20017
E_MENUMODESTART = 20018
E_MENUMODEEND = 20019
E_SYSTEMALERT = 20023
E_LIVEREGIONCHANGED = 20024
E_DRAGSTART = 20026
E_DRAGCANCEL = 20027
E_DRAGCOMPLETE = 20028
E_DROPTARGETDRAGENTER = 20029
E_DROPTARGETDRAGLEAVE = 20030
E_DROPTARGETDROPPED = 20031
E_TEXTEDITTEXTCHANGED = 20032
E_NOTIFICATION = 20035
E_ACTIVETEXTPOSITIONCHANGED = 20036

CT_BUTTON = 50000
CT_CALENDAR = 50001
CT_CHECKBOX = 50002
CT_COMBOBOX = 50003
CT_EDIT = 50004
CT_HYPERLINK = 50005
CT_IMAGE = 50006
CT_LISTITEM = 50007
CT_LIST = 50008
CT_MENU = 50009
CT_MENUBAR = 50010
CT_MENUITEM = 50011
CT_PROGRESSBAR = 50012
CT_RADIOBUTTON = 50013
CT_SCROLLBAR = 50014
CT_SLIDER = 50015
CT_SPINNER = 50016
CT_STATUSBAR = 50017
CT_TAB = 50018
CT_TABITEM = 50019
CT_TEXT = 50020
CT_TOOLBAR = 50021
CT_TOOLTIP = 50022
CT_TREE = 50023
CT_TREEITEM = 50024
CT_CUSTOM = 50025
CT_GROUP = 50026
CT_THUMB = 50027
CT_DATAGRID = 50028
CT_DATAITEM = 50029
CT_DOCUMENT = 50030
CT_SPLITBUTTON = 50031
CT_WINDOW = 50032
CT_PANE = 50033
CT_HEADER = 50034
CT_HEADERITEM = 50035
CT_TABLE = 50036
CT_TITLEBAR = 50037
CT_SEPARATOR = 50038
CT_SEMANTICZOOM = 50039
CT_APPBAR = 50040

TU_CHARACTER = 0
TU_FORMAT = 1
TU_WORD = 2
TU_LINE = 3
TU_PARAGRAPH = 4
TU_PAGE = 5
TU_DOCUMENT = 6

EP_START = 0
EP_END = 1

LANDMARK_CUSTOM = 80000
LANDMARK_FORM = 80001
LANDMARK_MAIN = 80002
LANDMARK_NAVIGATION = 80003
LANDMARK_SEARCH = 80004
HEADINGLEVEL_NONE = 80050
HEADINGLEVEL1 = 80051

#: Propiedades que se piden de una vez al crear objetos a partir de eventos.
BASE_PROPERTIES = (
	P_RUNTIMEID,
	P_NAME,
	P_CONTROLTYPE,
	P_LOCALIZEDCONTROLTYPE,
	P_AUTOMATIONID,
	P_CLASSNAME,
	P_PROCESSID,
	P_NATIVEWINDOWHANDLE,
	P_FRAMEWORKID,
	P_HASKEYBOARDFOCUS,
	P_ISKEYBOARDFOCUSABLE,
	P_ISENABLED,
	P_ISPASSWORD,
	P_ISOFFSCREEN,
	P_ARIAROLE,
	P_ARIAPROPERTIES,
	P_ISTEXTPATTERNAVAILABLE,
	P_ISVALUEPATTERNAVAILABLE,
	P_ISTOGGLEPATTERNAVAILABLE,
	P_ISSELECTIONITEMPATTERNAVAILABLE,
	P_ISEXPANDCOLLAPSEPATTERNAVAILABLE,
	P_ISRANGEVALUEPATTERNAVAILABLE,
	P_ISINVOKEPATTERNAVAILABLE,
	P_ISLEGACYIACCESSIBLEPATTERNAVAILABLE,
	P_HEADINGLEVEL,
	P_LANDMARKTYPE,
	P_LOCALIZEDLANDMARKTYPE,
	P_ISDIALOG,
	P_POSITIONINSET,
	P_SIZEOFSET,
	P_LEVEL,
	P_BOUNDINGRECT,
	P_LIVESETTING,
)

#: Propiedades para construir el modo exploración (árbol completo).
TREE_PROPERTIES = (
	P_RUNTIMEID,
	P_NAME,
	P_CONTROLTYPE,
	P_LOCALIZEDCONTROLTYPE,
	P_AUTOMATIONID,
	P_CLASSNAME,
	P_ISKEYBOARDFOCUSABLE,
	P_HASKEYBOARDFOCUS,
	P_ISENABLED,
	P_ISPASSWORD,
	P_ISOFFSCREEN,
	P_ARIAROLE,
	P_ARIAPROPERTIES,
	P_HEADINGLEVEL,
	P_LANDMARKTYPE,
	P_LOCALIZEDLANDMARKTYPE,
	P_BOUNDINGRECT,
	P_VALUEVALUE,
	P_ISVALUEPATTERNAVAILABLE,
	P_TOGGLESTATE,
	P_ISTOGGLEPATTERNAVAILABLE,
	P_EXPANDCOLLAPSESTATE,
	P_SELECTIONITEMISSELECTED,
	P_ISREQUIREDFORFORM,
	P_LEGACYSTATE,
	P_GRIDITEMROW,
	P_GRIDITEMCOLUMN,
	P_GRIDROWCOUNT,
	P_GRIDCOLUMNCOUNT,
	P_SIZEOFSET,
	P_POSITIONINSET,
	P_LEVEL,
	P_FULLDESCRIPTION,
	P_HELPTEXT,
	P_ISDIALOG,
	P_RANGEVALUEVALUE,
	P_CULTURE,
	P_ISINVOKEPATTERNAVAILABLE,
	# Modo exploración: orientación, celdas combinadas, regiones vivas,
	# aria-sort, relaciones (flowto, controls, details, describedby) y rangos.
	P_ORIENTATION,
	P_GRIDITEMROWSPAN,
	P_GRIDITEMCOLUMNSPAN,
	P_LIVESETTING,
	P_ITEMSTATUS,
	P_FLOWSTO,
	P_CONTROLLERFOR,
	P_DESCRIBEDBY,
	30156,  # UIA_AnnotationObjectsPropertyId (aria-details)
	P_RANGEVALUEMINIMUM,
	P_RANGEVALUEMAXIMUM,
	P_ISTEXTPATTERNAVAILABLE,
)

#: UIA_AnnotationObjectsPropertyId: elementos de anotación (aria-details).
P_ANNOTATIONOBJECTS = 30156
#: UIA_FlowsFromPropertyId (IUIAutomationElement2).
P_FLOWSFROM = 30148

#: Propiedades cuyo valor es una matriz de elementos -> (interfaz mínima,
#: accesor actual, accesor cacheado). NUNCA se leen como VARIANT
#: (``Get*PropertyValue*``): comtypes libera mal las matrices de IUnknown y
#: acaba corrompiendo el montón (0xc0000374). Se usan sus accesores tipados,
#: que devuelven un ``IUIAutomationElementArray``.
_ELEMENT_ARRAY_ACCESSORS = {
	P_CONTROLLERFOR: ("IUIAutomationElement", "CurrentControllerFor", "CachedControllerFor"),
	P_DESCRIBEDBY: ("IUIAutomationElement", "CurrentDescribedBy", "CachedDescribedBy"),
	P_FLOWSTO: ("IUIAutomationElement", "CurrentFlowsTo", "CachedFlowsTo"),
	P_FLOWSFROM: ("IUIAutomationElement2", "CurrentFlowsFrom", "CachedFlowsFrom"),
	P_ANNOTATIONOBJECTS: ("IUIAutomationElement4", "CurrentAnnotationObjects", "CachedAnnotationObjects"),
}
ELEMENT_ARRAY_PROPERTIES = frozenset(_ELEMENT_ARRAY_ACCESSORS)
#: Propiedades cuyo valor es UN elemento (también con accesor tipado).
ELEMENT_PROPERTIES = frozenset({P_LABELEDBY})


def elementArray(element, propId: int, cached: bool = False) -> list:
	"""Elementos de una propiedad de tipo matriz (ControllerFor, DescribedBy,
	FlowsTo, FlowsFrom, AnnotationObjects) leídos con su accesor tipado.

	``cached``: lee la copia de la caché (la propiedad debe estar en la
	petición de caché con la que se obtuvo el elemento).
	"""
	spec = _ELEMENT_ARRAY_ACCESSORS.get(propId)
	if spec is None or element is None:
		return []
	ifaceName, current, cachedName = spec
	try:
		el = element if ifaceName == "IUIAutomationElement" else element.QueryInterface(getattr(UIA, ifaceName))
		arr = getattr(el, cachedName if cached else current)
		if not arr:
			return []
		return [arr.GetElement(i) for i in range(arr.Length)]
	except (comtypes.COMError, AttributeError, ValueError, TypeError):
		return []


def labeledBy(element, cached: bool = False):
	"""Elemento que hace de etiqueta (LabeledBy) con el accesor tipado, o ``None``."""
	if element is None:
		return None
	try:
		el = element.CachedLabeledBy if cached else element.CurrentLabeledBy
		return el if el else None
	except (comtypes.COMError, AttributeError, ValueError):
		return None

NOT_SUPPORTED = None  # Se rellena al iniciar con ReservedNotSupportedValue.
MIXED_ATTRIBUTE = None


def initialize(connectionTimeoutMs: int = 2000) -> None:
	"""Crea el cliente UIA. Debe llamarse en el hilo del núcleo (MTA)."""
	global client, rawWalker, controlWalker, baseCacheRequest, treeCacheRequest, trueCondition, _version
	global NOT_SUPPORTED, MIXED_ATTRIBUTE
	obj = comtypes.client.CreateObject(UIA.CUIAutomation8, interface=UIA.IUIAutomation)
	best = obj
	for v, iface in ((6, "IUIAutomation6"), (5, "IUIAutomation5"), (4, "IUIAutomation4"), (3, "IUIAutomation3"), (2, "IUIAutomation2")):
		cls = getattr(UIA, iface, None)
		if cls is None:
			continue
		try:
			best = obj.QueryInterface(cls)
			_version = v
			break
		except comtypes.COMError:
			continue
	client = best
	try:
		client.AutoSetFocus = False
		client.ConnectionTimeout = connectionTimeoutMs
		# Rev. 10.11 (A8): 3 s no bastaban para la petición de caché del árbol de
		# una página enorme (modo exploración: «documento vacío»). NVDA deja el
		# valor del sistema (20 s); 10 s es un término medio con las aplicaciones
		# colgadas (el núcleo tiene su vigilante).
		client.TransactionTimeout = max(connectionTimeoutMs, 10000)
	except Exception:
		log.debug("No se pudieron ajustar los tiempos de espera de UIA", exc_info=True)
	if _version >= 6:
		try:
			client.CoalesceEvents = 1  # CoalesceEventsOptions_Enabled
			client.ConnectionRecoveryBehavior = 1
		except Exception:
			pass
	rawWalker = client.RawViewWalker
	controlWalker = client.ControlViewWalker
	trueCondition = client.CreateTrueCondition()
	baseCacheRequest = makeCacheRequest(BASE_PROPERTIES)
	treeCacheRequest = makeCacheRequest(TREE_PROPERTIES, scope=TreeScope_Subtree)
	NOT_SUPPORTED = client.ReservedNotSupportedValue
	MIXED_ATTRIBUTE = client.ReservedMixedAttributeValue
	log.info("UI Automation iniciado (IUIAutomation%s)", _version if _version > 1 else "")


def makeCacheRequest(properties, patterns=(), scope: int = TreeScope_Element, condition=None):
	cr = client.CreateCacheRequest()
	for p in properties:
		try:
			cr.AddProperty(p)
		except comtypes.COMError:
			pass
	for pat in patterns:
		try:
			cr.AddPattern(pat)
		except comtypes.COMError:
			pass
	cr.TreeScope = scope
	if condition is not None:
		cr.TreeFilter = condition
	return cr


def isNotSupported(value) -> bool:
	if value is None:
		return True
	try:
		return value is NOT_SUPPORTED or (NOT_SUPPORTED is not None and value == NOT_SUPPORTED)
	except Exception:
		return False


def runtimeIdOf(element) -> tuple:
	try:
		rid = element.GetRuntimeId()
		return tuple(rid) if rid else ()
	except Exception:
		return ()


def compareElements(a, b) -> bool:
	try:
		return bool(client.CompareElements(a, b))
	except Exception:
		return False


def getFocusedElement(cacheRequest=None):
	try:
		if cacheRequest is not None:
			el = client.GetFocusedElementBuildCache(cacheRequest)
		else:
			el = client.GetFocusedElement()
	except comtypes.COMError:
		# Rev. 1.0.14: el proveedor de la ventana (WinUI 3 con WebView2) a veces
		# no responde a tiempo. Se busca el foco desde la ventana con el foco del
		# teclado antes de darse por vencido.
		el = _focusedDescendantOfFocusWindow(0, cacheRequest)
		if el is not None:
			log.debug("GetFocusedElement falló: se usa el descendiente con foco de la ventana del teclado")
		return el
	return refineFocusedElement(el, cacheRequest)


def _keyboardFocusWindow() -> int:
	"""Ventana con el foco del teclado del hilo en primer plano (0 si no se sabe)."""
	from .. import winapi

	info = winapi.getGUIThreadInfo(0)
	return int(info.hwndFocus or 0) if info is not None else 0


def focusedDescendantOfWindow(hwnd: int, cacheRequest=None):
	"""Descendiente con ``HasKeyboardFocus`` de la ventana ``hwnd`` (o ``None``)."""
	return _focusedDescendantOfFocusWindow(hwnd, cacheRequest) if hwnd else None


def _focusedDescendantOfFocusWindow(focusHwnd: int, cacheRequest=None):
	"""Descendiente con ``HasKeyboardFocus`` de la ventana con el foco del teclado."""
	try:
		focusHwnd = focusHwnd or _keyboardFocusWindow()
		if not focusHwnd:
			return None
		request = cacheRequest if cacheRequest is not None else baseCacheRequest
		root = client.ElementFromHandleBuildCache(focusHwnd, request)
		if not root:
			return None
		cond = createPropertyCondition(P_HASKEYBOARDFOCUS, True)
		found = root.FindFirstBuildCache(TreeScope_Descendants, cond, request)
		return found if found else None
	except (comtypes.COMError, ValueError, TypeError, AttributeError):
		return None


_user32 = ctypes.windll.user32
_user32.IsChild.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_user32.IsChild.restype = ctypes.c_int


def refineFocusedElement(el, cacheRequest=None):
	"""Baja hasta el elemento con el foco cuando UIA se queda en una ventana por encima.

	En las aplicaciones WinUI 3 con WebView2 (WhatsApp, Teams, el Outlook nuevo...)
	el foco del teclado está en la ventana ``Chrome_WidgetWin_0`` del contenido,
	pero esa ventana solo tiene el proxy MSAA del sistema, que no sabe qué
	elemento tiene el foco: ``GetFocusedElement`` devuelve el panel
	``Microsoft.UI.Content.DesktopChildSiteBridge`` que la contiene, sin nombre
	y sin el estado «con foco». Tiresias se quedaba con ese panel: no leía el
	control web, ni el eco, ni el cursor (rev. 1.0.14).

	Si el elemento devuelto no es la ventana con el foco del teclado, esta
	ventana está dentro de la suya y el elemento no tiene el foco, se busca el
	descendiente con ``HasKeyboardFocus`` desde la ventana del foco. En
	Chromium es inmediato (el foco está marcado en el árbol); si no hay ninguno,
	se devuelve el elemento original.
	"""
	if el is None:
		return None
	try:
		focusHwnd = _keyboardFocusWindow()
		if not focusHwnd:
			return el
		if cacheRequest is not None:
			elHwnd = int(el.GetCachedPropertyValue(P_NATIVEWINDOWHANDLE) or 0)
		else:
			elHwnd = int(el.CurrentNativeWindowHandle or 0)
		if not elHwnd or elHwnd == focusHwnd or not _user32.IsChild(elHwnd, focusHwnd):
			return el
		if bool(el.CurrentHasKeyboardFocus):
			return el
		found = _focusedDescendantOfFocusWindow(focusHwnd, cacheRequest)
		if found is not None:
			log.debug("Foco UIA en una ventana por encima del foco del teclado: se usa el descendiente con foco")
			return found
	except (comtypes.COMError, ValueError, TypeError, AttributeError):
		pass
	return el


def elementFromHandle(hwnd: int):
	try:
		return client.ElementFromHandleBuildCache(hwnd, baseCacheRequest)
	except comtypes.COMError:
		return None


def elementFromPoint(x: int, y: int):
	from ctypes.wintypes import POINT

	try:
		return client.ElementFromPointBuildCache(POINT(x, y), baseCacheRequest)
	except comtypes.COMError:
		return None


def getRootElement():
	return client.GetRootElement()


def createPropertyCondition(propertyId: int, value):
	return client.CreatePropertyCondition(propertyId, value)


def createOrCondition(conditions: list):
	if len(conditions) == 1:
		return conditions[0]
	arr = (comtypes.POINTER(UIA.IUIAutomationCondition) * len(conditions))(*conditions)
	return client.CreateOrConditionFromNativeArray(arr, len(conditions))


def createAndCondition(a, b):
	return client.CreateAndCondition(a, b)
