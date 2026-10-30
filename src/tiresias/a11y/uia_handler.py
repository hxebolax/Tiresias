"""Recepción de eventos de UI Automation.

Los eventos llegan en hilos internos de UIA; aquí solo se encolan en el hilo
del núcleo, donde se crean los objetos y se despachan con
:func:`tiresias.events.executeEvent`.
"""

from __future__ import annotations

import os
import threading
from ctypes import c_int as ctypes_c_int
import time
from typing import Any

import comtypes
from comtypes import COMObject

from .. import api, queue_handler
from ..config import conf
from ..log import getLogger
from . import uia_client as uc

log = getLogger("uiaHandler")
UIA = uc.UIA

_handler = None
_focusSeq = 0
_focusLock = threading.Lock()
_ownPid = os.getpid()
_localTextElement = None
#: id(oyente) -> (oyente, elemento raíz, manejador propio del documento).
_structureListeners: dict[int, tuple[Any, Any, Any]] = {}
#: RuntimeId del foco actual (para filtrar eventos en el hilo de UIA).
_focusRid: tuple = ()


def _onFocusChange(obj=None) -> None:
	global _focusRid, _focusAncestorRids
	try:
		_focusRid = tuple(obj.runtimeId) if obj is not None and hasattr(obj, "runtimeId") else ()
	except Exception:
		_focusRid = ()
	rids = set()
	try:
		for anc in api.getFocusAncestors()[-6:]:
			rid = getattr(anc, "runtimeId", None)
			if rid:
				rids.add(tuple(rid))
	except Exception:
		pass
	_focusAncestorRids = frozenset(rids)
	global _focusPid
	try:
		_focusPid = int(obj.processID) if obj is not None else 0
	except Exception:
		_focusPid = 0
	global _focusIsCombo, _focusComboCollapsed
	try:
		from ..objects.roles import Role, State

		_focusIsCombo = obj is not None and hasattr(obj, "element") and obj.role == Role.COMBOBOX
		_focusComboCollapsed = _focusIsCombo and State.COLLAPSED in obj.states
	except Exception:
		_focusIsCombo = _focusComboCollapsed = False


_focusPid = 0
#: El foco es un cuadro combinado UIA cerrado. Sus listas (y las de otros
#: controles del diálogo) mandan varias selecciones por cada flecha que no se
#: anuncian (el valor nuevo llega con su cambio de valor): se descartan ya en el
#: hilo de UIA para que el valor se lea sin esperar a procesarlas.
_focusIsCombo = False
_focusComboCollapsed = False


def _cachedInt(sender, propId: int) -> int:
	try:
		return int(sender.GetCachedPropertyValue(propId) or 0)
	except Exception:
		return 0


def _isOwnProcess(sender) -> bool:
	"""El evento viene de una ventana de Tiresias (se leen con MSAA, como NVDA).

	Solo se mira el ProcessId cacheado: preguntar a UIA por elementos del propio
	proceso bloquea el hilo de la interfaz y repite eventos.
	"""
	return _cachedInt(sender, uc.P_PROCESSID) == _ownPid


def _ownFocusFallback() -> None:
	from . import winevents

	winevents.scheduleFocusCheck(150)


def _isFromSlowProcess(sender) -> bool:
	"""``True`` si el evento viene de un proceso marcado como lento (sin llamadas entre procesos)."""
	pid = _cachedInt(sender, uc.P_PROCESSID)
	until = _slowPids.get(pid)
	if until is None:
		return False
	if time.monotonic() > until:
		_slowPids.pop(pid, None)
		return False
	try:
		rid = tuple(sender.GetCachedPropertyValue(uc.P_RUNTIMEID) or ())
	except Exception:
		rid = ()
	return rid != _focusRid


def _isHeaderInFocusProcess(sender) -> bool:
	if not _focusPid or _cachedInt(sender, uc.P_PROCESSID) != _focusPid:
		return False
	if _cachedInt(sender, uc.P_CONTROLTYPE) == uc.CT_HEADERITEM:
		return True
	try:
		role = (sender.GetCachedPropertyValue(uc.P_ARIAROLE) or "").lower()
	except Exception:
		role = ""
	return role in ("columnheader", "rowheader")


def markSlowProcess(pid: int, seconds: float = 10.0) -> None:
	"""Durante ``seconds`` se ignoran los eventos secundarios de ``pid`` (#20654)."""
	if pid:
		if pid not in _slowPids:
			log.info("Proveedor UIA lento en el proceso %d: se filtran sus eventos secundarios", pid)
		_slowPids[pid] = time.monotonic() + seconds


api.post_focusChange.register(_onFocusChange)

#: Propiedades vigiladas globalmente -> nombre de evento.
PROPERTY_EVENTS = {
	uc.P_NAME: "nameChange",
	uc.P_VALUEVALUE: "valueChange",
	uc.P_RANGEVALUEVALUE: "valueChange",
	uc.P_TOGGLESTATE: "stateChange",
	uc.P_EXPANDCOLLAPSESTATE: "stateChange",
	uc.P_SELECTIONITEMISSELECTED: "stateChange",
	uc.P_ISENABLED: "stateChange",
	uc.P_HELPTEXT: "descriptionChange",
	uc.P_FULLDESCRIPTION: "descriptionChange",
	uc.P_ITEMSTATUS: "itemStatusChange",
	uc.P_CONTROLLERFOR: "controllerForChange",
	uc.P_ARIAPROPERTIES: "ariaPropertiesChange",
}

#: Eventos UIA de selección, diseño y arrastrar y soltar (se registran si existen).
EXTRA_AUTOMATION_EVENTS = {
	uc.E_ELEMENTADDEDTOSELECTION: "selectionAdd",
	uc.E_ELEMENTREMOVEDFROMSELECTION: "selectionRemove",
	uc.E_SELECTIONINVALIDATED: "selectionWithin",
	uc.E_LAYOUTINVALIDATED: "layoutInvalidated",
	uc.E_DRAGSTART: "dragStart",
	uc.E_DRAGCANCEL: "dragCancel",
	uc.E_DRAGCOMPLETE: "dragComplete",
	uc.E_DROPTARGETDRAGENTER: "dropTargetEnter",
	uc.E_DROPTARGETDRAGLEAVE: "dropTargetLeave",
	uc.E_DROPTARGETDROPPED: "dropped",
}

#: Eventos que solo interesan si vienen de la aplicación en primer plano.
_FOREGROUND_ONLY_EVENTS = {
	"selectionAdd",
	"selectionRemove",
	"selectionWithin",
	"layoutInvalidated",
	"dragStart",
	"dragCancel",
	"dragComplete",
	"dropTargetEnter",
	"dropTargetLeave",
	"dropped",
	"selection",
	"menuStart",
	"menuEnd",
	"windowOpened",
}

#: Procesos con proveedores lentos: pid -> instante hasta el que se filtran (#20654).
_slowPids: dict[int, float] = {}
#: Eventos que se descartan de los procesos lentos (salvo los del foco).
_DROPPABLE_WHEN_SLOW = {"nameChange", "valueChange", "descriptionChange", "itemStatusChange", "liveRegionChange", "textChange", "layoutInvalidated", "selectionWithin", "ariaPropertiesChange"}
#: RuntimeIds de los antecesores del foco (para aria-sort fuera del foco).
_focusAncestorRids: frozenset = frozenset()

AUTOMATION_EVENTS = {
	uc.E_MENUOPENED: "menuStart",
	uc.E_MENUCLOSED: "menuEnd",
	uc.E_TOOLTIPOPENED: "tooltipOpen",
	uc.E_WINDOWOPENED: "windowOpened",
	uc.E_LIVEREGIONCHANGED: "liveRegionChange",
	uc.E_SYSTEMALERT: "alert",
	uc.E_ASYNCCONTENTLOADED: "documentLoadComplete",
	uc.E_ELEMENTSELECTED: "selection",
}

LOCAL_EVENTS = {
	uc.E_TEXTSELECTIONCHANGED: "caret",
	uc.E_TEXTCHANGED: "textChange",
	uc.E_TEXTEDITTEXTCHANGED: "textChange",
}


class _EventHandler(COMObject):
	_com_interfaces_ = [
		UIA.IUIAutomationEventHandler,
		UIA.IUIAutomationFocusChangedEventHandler,
		UIA.IUIAutomationPropertyChangedEventHandler,
		UIA.IUIAutomationNotificationEventHandler,
		UIA.IUIAutomationStructureChangedEventHandler,
	] + ([UIA.IUIAutomationActiveTextPositionChangedEventHandler] if hasattr(UIA, "IUIAutomationActiveTextPositionChangedEventHandler") else [])

	def IUIAutomationEventHandler_HandleAutomationEvent(self, sender, eventID):
		name = AUTOMATION_EVENTS.get(eventID) or LOCAL_EVENTS.get(eventID) or EXTRA_AUTOMATION_EVENTS.get(eventID)
		if not name:
			return
		if _isOwnProcess(sender):
			return
		if name == "selection" and _focusComboCollapsed:
			return
		if _slowPids and name in _DROPPABLE_WHEN_SLOW and _isFromSlowProcess(sender):
			return
		_queueEvent(sender, name)

	def IUIAutomationActiveTextPositionChangedEventHandler_HandleActiveTextPositionChangedEvent(self, sender, textRange):
		if _isOwnProcess(sender):
			return
		try:
			rid = tuple(sender.GetCachedPropertyValue(uc.P_RUNTIMEID) or ())
		except Exception:
			rid = ()
		if rid == _focusRid or rid in _focusAncestorRids:
			_queueEvent(sender, "activeTextPositionChange")

	def IUIAutomationFocusChangedEventHandler_HandleFocusChangedEvent(self, sender):
		global _focusSeq
		if _isOwnProcess(sender):
			# Diálogos de Tiresias: los lee MSAA (WinEvent de foco). Por si ese
			# evento no llega, se comprueba el foco real un poco después.
			queue_handler.queueFunction(_ownFocusFallback)
			return
		with _focusLock:
			_focusSeq += 1
			seq = _focusSeq
		queue_handler.queueFunction(_onFocus, sender, seq)

	def IUIAutomationPropertyChangedEventHandler_HandlePropertyChangedEvent(self, sender, propertyId, newValue):
		# ``newValue`` es una copia superficial del VARIANT de UIA: comtypes le
		# haría VariantClear al destruirla y UIA lo libera otra vez al volver.
		# Con un BSTR o una matriz de elementos (ControllerFor) eso es una doble
		# liberación que corrompe el montón (0xc0000374). Se vacía antes de nada:
		# su valor no se usa (las propiedades se leen del elemento), salvo el
		# entero del estado expandido/contraído, que se copia antes.
		global _focusComboCollapsed
		try:
			if propertyId == uc.P_EXPANDCOLLAPSESTATE and _focusIsCombo and newValue.vt in (2, 3):
				if tuple(sender.GetCachedPropertyValue(uc.P_RUNTIMEID) or ()) == _focusRid:
					_focusComboCollapsed = newValue.value == 0
		except Exception:
			pass
		try:
			newValue.vt = 0  # VT_EMPTY
		except Exception:
			pass
		name = PROPERTY_EVENTS.get(propertyId)
		if not name:
			return
		if _isOwnProcess(sender):
			return
		if _slowPids and name in _DROPPABLE_WHEN_SLOW and _isFromSlowProcess(sender):
			return
		if name == "ariaPropertiesChange":
			# Solo interesa el orden (aria-sort) del foco o de sus antecesores
			# cercanos, p. ej. el encabezado de columna de un botón (#10890).
			try:
				rid = tuple(sender.GetCachedPropertyValue(uc.P_RUNTIMEID) or ())
			except Exception:
				rid = ()
			if rid == _focusRid or rid in _focusAncestorRids or _isHeaderInFocusProcess(sender):
				_queueEvent(sender, name)
			return
		if name == "nameChange":
			# Elementos con LiveSetting (regiones vivas implícitas): su nombre se lee
			# aunque no tengan el foco.
			try:
				live = sender.GetCachedPropertyValue(uc.P_LIVESETTING)
			except Exception:
				live = 0
			if live in (1, 2) and isImplicitLiveRegion(sender):
				queue_handler.queueFunction(_dispatch, sender, "liveRegionChange")
				return
		if name in ("nameChange", "descriptionChange", "valueChange", "itemStatusChange", "controllerForChange") and not (_globalEvents and name in ("nameChange", "descriptionChange")):
			# Filtro rápido (sin llamadas entre procesos): solo interesa el foco,
			# las barras de progreso y los controles con valor.
			try:
				rid = tuple(sender.GetCachedPropertyValue(uc.P_RUNTIMEID) or ())
			except Exception:
				rid = ()
			if rid != _focusRid:
				try:
					ct = sender.GetCachedPropertyValue(uc.P_CONTROLTYPE)
				except Exception:
					ct = 0
				if name == "itemStatusChange":
					# aria-sort de los encabezados de tabla aunque no tengan el foco (#10890).
					if ct not in (uc.CT_HEADERITEM, uc.CT_DATAITEM):
						return
				elif name != "valueChange":
					return
				elif ct not in (uc.CT_PROGRESSBAR, uc.CT_COMBOBOX, uc.CT_EDIT, uc.CT_SLIDER, uc.CT_SPINNER):
					return
				elif ct == uc.CT_PROGRESSBAR and not _acceptBackgroundProgress(sender):
					# Barra de otra aplicación: se descarta antes de crear el objeto.
					return
		_queueEvent(sender, name)

	def IUIAutomationNotificationEventHandler_HandleNotificationEvent(self, sender, notificationKind, notificationProcessing, displayString, activityId):
		if _isOwnProcess(sender):
			return
		queue_handler.queueFunction(_onNotification, sender, notificationKind, notificationProcessing, displayString or "", activityId or "")

	def IUIAutomationStructureChangedEventHandler_HandleStructureChangedEvent(self, sender, changeType, runtimeId):
		# Los cambios de estructura de los documentos llegan por el manejador propio
		# de cada documento (_StructureHandler): con uno compartido no se sabía de
		# qué documento venía el evento y se repartía a todos (rev. 10.11, C1).
		return


class _StructureHandler(COMObject):
	"""Manejador de StructureChanged de UN documento (sabe a qué oyente avisar)."""

	_com_interfaces_ = [UIA.IUIAutomationStructureChangedEventHandler]

	def __init__(self, key: int) -> None:
		super().__init__()
		self.key = key

	def IUIAutomationStructureChangedEventHandler_HandleStructureChangedEvent(self, sender, changeType, runtimeId):
		queue_handler.queueFunction(_onStructure, self.key, sender)


#: Clases cuyo LiveSetting no indica una región viva. La interfaz de Office
#: (NetUI: cinta y barra de estado de Word, Excel, Outlook...) publica
#: «asertivo» en todos sus elementos: al escribir en Word, el botón «Contar
#: palabras» de la barra de estado cambia de nombre y se leía cada vez
#: («Contar palabras 12 palabras»). NVDA no lee estos cambios de nombre; los
#: avisos reales de Office (evento LiveRegionChanged) siguen leyéndose.
_NOT_LIVE_CLASS_PREFIXES = ("NetUI",)


def isImplicitLiveRegion(element) -> bool:
	"""``True`` si un cambio de nombre de ``element`` (con LiveSetting) es una región viva.

	Solo usa propiedades en caché: se llama en el hilo de eventos de UIA.
	"""
	try:
		cls = str(element.GetCachedPropertyValue(uc.P_CLASSNAME) or "")
	except Exception:
		cls = ""
	return not cls.startswith(_NOT_LIVE_CLASS_PREFIXES)


def _makeObject(element):
	from ..objects.uia import UIAObject

	started = time.monotonic()
	try:
		return UIAObject.fromElement(element)
	except Exception:
		log.debug("No se pudo crear el objeto del evento", exc_info=True)
		return None
	finally:
		# Solo cuenta lo que tarda el proveedor en dar el objeto (antes se medía
		# todo el evento, voz y braille incluidos, y una región viva larga
		# marcaba como lento a Chrome: sus avisos se perdían 10 s).
		_checkSlowProvider(element, (time.monotonic() - started) * 1000)


def _checkSlowProvider(element, elapsedMs: float) -> None:
	try:
		threshold = conf["objects"]["slowProviderThresholdMs"]
	except KeyError:
		threshold = 800
	if elapsedMs > threshold:
		# El proveedor tarda demasiado: sus eventos secundarios se filtran un rato.
		markSlowProcess(_cachedInt(element, uc.P_PROCESSID))


# ------------------------------------------------------------------ agrupación
#: Eventos que se agrupan por elemento mientras esperan en la cola del núcleo:
#: si llega otro igual del mismo elemento, se sustituye el pendiente por el más
#: reciente (el objeto se crea con su caché, la de después del cambio) y no se
#: encola otra vez. Las regiones vivas, alertas, menús y avisos no se agrupan.
_COALESCED_EVENTS = frozenset(
	{
		"nameChange",
		"valueChange",
		"stateChange",
		"descriptionChange",
		"itemStatusChange",
		"controllerForChange",
		"ariaPropertiesChange",
		"layoutInvalidated",
		"selection",
		"selectionAdd",
		"selectionRemove",
		"selectionWithin",
		"documentLoadComplete",
		"textChange",
		"caret",
		"activeTextPositionChange",
	}
)
#: (evento, RuntimeId) -> (elemento más reciente, instante en que se encoló).
_pendingEvents: dict[tuple, tuple[Any, float]] = {}
_pendingLock = threading.Lock()
#: Segundos tras los que un pendiente ya no bloquea (por si la cola se vació sin procesarlo).
_PENDING_EXPIRY = 1.0


def _queueEvent(sender, name: str) -> None:
	"""Encola un evento en el núcleo agrupando los repetidos (hilo de UIA)."""
	if name in _COALESCED_EVENTS:
		try:
			rid = tuple(sender.GetCachedPropertyValue(uc.P_RUNTIMEID) or ())
		except Exception:
			rid = ()
		if rid:
			key = (name, rid)
			now = time.monotonic()
			with _pendingLock:
				old = _pendingEvents.get(key)
				if len(_pendingEvents) > 5000:
					_pendingEvents.clear()
				_pendingEvents[key] = (sender, now if old is None or now - old[1] >= _PENDING_EXPIRY else old[1])
			if old is not None and now - old[1] < _PENDING_EXPIRY:
				return
			queue_handler.queueFunction(_dispatchPending, key)
			return
	queue_handler.queueFunction(_dispatch, sender, name)


def _dispatchPending(key: tuple) -> None:
	with _pendingLock:
		entry = _pendingEvents.pop(key, None)
	if entry is not None:
		_dispatch(entry[0], key[0])


def _acceptBackgroundProgress(sender) -> bool:
	"""Barra de progreso que no es el foco: ¿se procesa? (hilo de UIA, sin llamadas entre procesos)."""
	try:
		if conf["presentation"]["reportBackgroundProgressBars"]:
			return True
	except KeyError:
		return True
	from .. import winapi

	try:
		fg = winapi.getForegroundWindow()
		return not fg or _cachedInt(sender, uc.P_PROCESSID) == winapi.getWindowProcessId(fg)
	except Exception:
		return True


_lastEventKey: tuple | None = None
_lastEventTime = 0.0


def _dispatch(element, eventName: str) -> None:
	if _suspended:
		# Eventos que ya estaban en cola al pasar a espera.
		return
	_dispatchEvent(element, eventName)


#: Último orden (aria-sort) conocido de cada encabezado: runtimeId -> valor.
_sortStates: dict[tuple, str] = {}

#: Eventos cuya repetición dentro de la ventana de agrupación se procesa al final
#: de la ventana en vez de perderse (salida de terminales y textos que cambian).
_TRAILING_EVENTS = frozenset({"textChange"})
#: (RuntimeId, evento) con un procesamiento diferido ya programado.
_trailingPending: set = set()


def _scheduleTrailing(key: tuple, element, eventName: str, delayS: float) -> None:
	if key in _trailingPending:
		return
	_trailingPending.add(key)

	def run() -> None:
		_trailingPending.discard(key)
		_dispatch(element, eventName)

	queue_handler.callLater(max(1, int(delayS * 1000) + 1), run)


def _refresh(obj) -> None:
	"""Olvida lo leído del objeto en este ciclo (ver ``AccObject.refreshProperties``)."""
	refresh = getattr(obj, "refreshProperties", None)
	if refresh is not None:
		try:
			refresh()
		except Exception:
			log.debug("No se pudieron refrescar las propiedades", exc_info=True)


def _dispatchEvent(element, eventName: str) -> None:
	global _lastEventKey, _lastEventTime
	from ..events import executeEvent

	try:
		rid = uc.runtimeIdOf(element)
	except Exception:
		rid = ()
	if eventName == "ariaPropertiesChange":
		obj = _makeObject(element)
		if obj is None:
			return
		sort = obj.UIAAriaProperties.get("sort", "")
		old = _sortStates.get(rid)
		_sortStates[rid] = sort
		if len(_sortStates) > 200:
			_sortStates.clear()
		if (old is not None and old != sort) or (old is None and sort not in ("", "none")):
			executeEvent("sortChange", obj)
		return
	if eventName in _FOREGROUND_ONLY_EVENTS:
		obj = _makeObject(element)
		if obj is None:
			return
		if eventName in ("menuStart", "menuEnd") and _isMSAAWindow(obj):
			# Menú de una ventana que se lee con MSAA (los menús Win32 #32768):
			# ya avisa su WinEvent; con los dos, el menú se anunciaba dos veces.
			return
		fg = api.getForegroundObject()
		try:
			if fg is not None and obj.processID != fg.processID:
				# Los menús emergentes (p. ej. el de Tiresias) se abren sobre una
				# ventana que no llega a ser el primer plano anunciado: cuenta la
				# ventana activa real.
				from .. import winapi

				if eventName not in ("menuStart", "menuEnd") or obj.processID != winapi.getWindowProcessId(winapi.getForegroundWindow()):
					return
		except Exception:
			return
		executeEvent(eventName, obj)
		return
	# Evita repetir el mismo evento sobre el mismo elemento en ráfagas.
	key = (rid, eventName)
	now = time.monotonic()
	windowS = conf["advanced"]["eventCoalesceMs"] / 1000.0
	if key == _lastEventKey and now - _lastEventTime < windowS:
		if eventName in _TRAILING_EVENTS:
			# El último de una ráfaga de cambios de texto no se pierde: se procesa
			# al acabar la ventana (lee el estado de ese momento).
			_scheduleTrailing(key, element, eventName, windowS - (now - _lastEventTime))
		return
	_lastEventKey, _lastEventTime = key, now
	obj = _makeObject(element)
	if obj is None:
		return
	if eventName in ("nameChange", "valueChange", "stateChange", "descriptionChange", "caret", "textChange", "controllerForChange"):
		focus = api.getFocusObject()
		# Solo interesan cambios del foco, de sus antecesores cercanos o barras de progreso.
		from ..objects.roles import Role

		isFocus = focus is not None and obj == focus
		if not isFocus and _globalEvents and eventName in ("nameChange", "descriptionChange"):
			# Registro global: los módulos de aplicación y complementos reciben el
			# cambio de cualquier objeto (los objetos solo lo leen si tienen el foco).
			executeEvent(eventName, obj)
			return
		if not isFocus and eventName != "valueChange" and eventName not in ("caret", "textChange"):
			if eventName == "stateChange" and obj.role in (Role.CHECKBOX, Role.RADIOBUTTON, Role.TOGGLEBUTTON, Role.SWITCH, Role.TREEVIEWITEM, Role.LISTITEM):
				fg = api.getForegroundObject()
				if fg is None or obj.processID != fg.processID:
					return
			else:
				return
		if eventName == "valueChange" and not isFocus and obj.role != Role.PROGRESSBAR:
			if focus is None or obj.processID != focus.processID:
				return
			if obj.role not in (Role.COMBOBOX, Role.SLIDER, Role.SPINBUTTON, Role.EDITABLETEXT):
				return
			# Valor de un elemento que no es el foco (p. ej. el campo de un combo).
			if focus.role == Role.COMBOBOX and obj in [focus.firstChild]:
				obj = focus
				_refresh(obj)
			else:
				return
		if isFocus:
			obj = focus
			# Lo leído del foco en este ciclo es de antes del cambio.
			_refresh(obj)
	if eventName == "tooltipOpen":
		fg = api.getForegroundObject()
		if fg is not None and obj.processID != fg.processID:
			return
	if eventName in ("liveRegionChange",):
		fg = api.getForegroundObject()
		if fg is not None and obj.processID != fg.processID:
			return
	executeEvent(eventName, obj)


def _isMSAAWindow(obj) -> bool:
	"""``True`` si la ventana de ``obj`` se lee con MSAA (ver :mod:`api_choice`)."""
	from . import api_choice

	try:
		hwnd = obj.windowHandle
	except Exception:
		return False
	return bool(hwnd) and api_choice.chooseAPI(hwnd) == api_choice.API_MSAA


def isInForegroundWindow(obj) -> bool:
	"""``True`` si ``obj`` está en la ventana activa (o en su proceso).

	Se acepta el mismo proceso que la ventana activa (menús emergentes y
	ventanas propias) y el contenido incrustado de otro proceso cuya ventana
	raíz es la activa (WebView2). Si no se puede saber, se acepta.
	"""
	from .. import winapi

	try:
		fg = winapi.getForegroundWindow()
		if not fg:
			return True
		fgPid = winapi.getWindowProcessId(fg)
		if int(obj.processID) == fgPid:
			return True
		hwnd = obj.windowHandle
		if not hwnd:
			return True
		root = winapi.getAncestor(hwnd, winapi.GA_ROOT)
		if root == fg or winapi.getWindowProcessId(root) == fgPid:
			return True
		# Rev. 1.0.14: en WinUI 3 el contenido WebView2 (WhatsApp, Teams, el
		# Outlook nuevo) vive en una ventana de nivel superior de
		# msedgewebview2.exe que la aplicación compone dentro de la suya: su
		# raíz Win32 no es la ventana activa, pero quien lo muestra sí. Sin
		# esto, todos los focos de la página se descartaban como «internos de
		# una ventana en segundo plano».
		from ..appmodules import handler as appHandler

		return appHandler.hostProcessId(obj, root) == fgPid
	except Exception:
		return True


def _onFocus(element, seq: int) -> None:
	from ..events import executeEvent

	if _suspended:
		return
	if seq != _focusSeq:
		# Llegó otro evento de foco más reciente: este ya no vale.
		return
	obj = _makeObject(element)
	if obj is None:
		return
	try:
		# El valor actual, no el de la caché del evento (que siempre dice «sí»):
		# el foco puede haberse movido desde entonces.
		if not bool(element.CurrentHasKeyboardFocus):
			# Algunos marcos mandan foco a elementos que ya no lo tienen.
			current = uc.getFocusedElement(uc.baseCacheRequest)
			if current is not None and not uc.compareElements(current, element):
				obj = _makeObject(current)
				if obj is None:
					return
	except Exception:
		pass
	if not getattr(obj, "shouldAllowFocusEvent", True):
		return
	if not isInForegroundWindow(obj):
		# Foco interno de una ventana en segundo plano (Chromium lo anuncia al
		# activarse la accesibilidad): no es el foco del sistema. Se comprueba
		# el foco real por si acaso.
		from . import winevents

		log.debug("Foco UIA de una ventana en segundo plano descartado: %r", obj)
		winevents.scheduleFocusCheck(150)
		return
	from . import api_choice

	# Con un menú Win32 abierto cuenta la ventana del propio elemento (el menú),
	# no la del control que lo abrió: los menús #32768 los lee MSAA y su foco
	# UIA aquí sería un anuncio repetido.
	choice, hwnd = api_choice.chooseAPIForFocus(obj)
	if choice != api_choice.API_UIA:
		# La ventana con el foco se lee con MSAA o Java: lo resuelve su API
		# (WinEvent o Java Access Bridge); por si no avisa, se comprueba luego.
		from . import winevents

		log.debug("Foco UIA en una ventana que se lee con %s (%x): se deja a su API", choice, hwnd)
		winevents.scheduleFocusCheck(100)
		return
	old = api.getFocusObject()
	if old is not None and obj == old:
		return
	executeEvent("gainFocus", obj)
	_registerLocalHandlers(obj)


#: Registro de eventos «global» (opción uia.eventRegistration); se lee en el hilo de UIA.
_globalEvents = False
#: Última notificación anunciada: (activityId, instante).
_lastNotification: tuple[str, float] = ("", 0.0)
#: NotificationProcessing_ImportantMostRecent y NotificationProcessing_MostRecent.
_MOST_RECENT_PROCESSING = (1, 3)


def applyConfig() -> None:
	"""Relee las opciones de UIA que se consultan en los hilos de eventos."""
	global _globalEvents
	try:
		_globalEvents = conf["uia"]["eventRegistration"] == "global"
	except KeyError:
		_globalEvents = False


def _sayAllRunning() -> bool:
	try:
		from ..speech import sayall

		return bool(sayall.isRunning())
	except Exception:
		return False


def _onNotification(element, kind: int, processing: int, displayString: str, activityId: str) -> None:
	global _lastNotification
	from ..events import executeEvent

	if _suspended:
		return
	if not conf["presentation"]["reportNotifications"]:
		return
	obj = _makeObject(element)
	if obj is not None and not conf["uia"]["notificationsFromBackground"]:
		# Solo las notificaciones de la aplicación en primer plano.
		fg = api.getForegroundObject()
		try:
			if fg is not None and obj.processID != fg.processID:
				return
		except Exception:
			pass
	now = time.monotonic()
	if conf["uia"]["honorNotificationProcessing"] and processing in _MOST_RECENT_PROCESSING and activityId:
		# La aplicación pide que solo cuente la más reciente: se corta la anterior.
		lastId, lastTime = _lastNotification
		if lastId == activityId and now - lastTime < 5 and not _sayAllRunning():
			# Durante la lectura continua no se corta: cancelar la voz la detendría.
			from .. import speech

			speech.cancelSpeech()
	_lastNotification = (activityId, now)
	from .. import speech

	# Lo que se diga se marca como notificación en el historial de voz.
	with speech.speechOrigin(speech.ORIGIN_NOTIFICATION):
		if obj is None:
			# Sin elemento: se habla igualmente.
			if displayString:
				speech.speakText(displayString)
			return
		executeEvent("notification", obj, displayString=displayString, activityId=activityId, notificationKind=kind, notificationProcessing=processing)


def _onStructure(key: int, element: Any = None) -> None:
	entry = _structureListeners.get(key)
	if entry is None:
		return
	listener = entry[0]
	try:
		# ``element``: el elemento que cambió (permite actualizar solo esa parte).
		listener.onStructureChanged(element)
	except Exception:
		log.exception("Error en cambio de estructura")


# ------------------------------------------------------------------ registro
def initialize() -> None:
	global _handler
	from ..config import post_configProfileSwitch, post_configReset, post_configSave

	applyConfig()
	for action in (post_configProfileSwitch, post_configReset, post_configSave):
		action.register(applyConfig)
	_handler = _EventHandler()
	# En el hilo de registro: con una aplicación colgada, registrar en la raíz
	# puede tardar (contacta con los proveedores) y el núcleo no debe esperar.
	_registrar.submit(_registerGlobalHandlers, _handler)


#: Hilo MTA donde se registran y quitan los manejadores de eventos UIA (en orden).
from .mta_worker import MTAWorker  # noqa: E402

_registrar = MTAWorker("UIA-registro")


def _registerGlobalHandlers(handler=None) -> None:
	"""Eventos de todo el escritorio (foco, automatización, propiedades, notificaciones)."""
	handler = handler if handler is not None else _handler
	if _suspended or handler is not _handler:
		# Se pasó a espera (o se cambió de manejador) antes de llegar aquí.
		return
	client = uc.client
	root = client.GetRootElement()
	client.AddFocusChangedEventHandler(uc.baseCacheRequest, handler)
	for eventId in list(AUTOMATION_EVENTS) + list(EXTRA_AUTOMATION_EVENTS):
		try:
			client.AddAutomationEventHandler(eventId, root, uc.TreeScope_Subtree, uc.baseCacheRequest, handler)
		except comtypes.COMError:
			log.debug("No se pudo registrar el evento %d", eventId, exc_info=True)
	if hasattr(client, "AddActiveTextPositionChangedEventHandler") and hasattr(UIA, "IUIAutomationActiveTextPositionChangedEventHandler"):
		try:
			client.AddActiveTextPositionChangedEventHandler(root, uc.TreeScope_Subtree, uc.baseCacheRequest, handler)
		except (comtypes.COMError, TypeError, ValueError):
			log.debug("Sin eventos de posición de texto activa", exc_info=True)
	props = list(PROPERTY_EVENTS)
	arr = (ctypes_c_int * len(props))(*props)
	try:
		client.AddPropertyChangedEventHandlerNativeArray(root, uc.TreeScope_Subtree, uc.baseCacheRequest, handler, arr, len(props))
	except comtypes.COMError:
		log.exception("No se pudo registrar el cambio de propiedades")
	if hasattr(client, "AddNotificationEventHandler"):
		try:
			client.AddNotificationEventHandler(root, uc.TreeScope_Subtree, uc.baseCacheRequest, handler)
		except comtypes.COMError:
			log.debug("Sin eventos de notificación", exc_info=True)
	log.info("Eventos UIA registrados")


def _registerLocalHandlers(obj) -> None:
	"""Eventos de texto (cursor, cambios) solo para el elemento con foco.

	Solo si ``obj`` es de verdad el foco: si el foco se rechazó (rebote a un
	contenedor vacío, filtro del módulo de aplicación), el campo que sigue con
	el foco conserva sus eventos. El registro se hace en el hilo de registro
	(:data:`_registrar`), sin que el núcleo espere a la aplicación.
	"""
	if _suspended or obj is None:
		return
	focus = api.getFocusObject()
	try:
		if focus is not obj and focus != obj:
			return
	except Exception:
		return
	el = None
	try:
		if obj.hasText:
			# Objetos MSAA o Java: sus eventos de texto llegan por WinEvent o JAB.
			el = getattr(obj, "element", None)
	except Exception:
		el = None
	_registrar.submit(_updateLocalHandlers, el, _handler)


def _updateLocalHandlers(el, handler) -> None:
	"""(Hilo de registro) Pasa los eventos de texto locales a ``el`` (o los quita)."""
	global _localTextElement
	client = uc.client
	old = _localTextElement
	if old is not None and el is not None and uc.compareElements(old, el):
		# El mismo elemento: no hace falta quitar y volver a poner.
		return
	if old is not None:
		for eventId in LOCAL_EVENTS:
			try:
				client.RemoveAutomationEventHandler(eventId, old, handler)
			except comtypes.COMError:
				pass
		_localTextElement = None
	if el is None or _suspended or handler is not _handler:
		return
	for eventId in LOCAL_EVENTS:
		try:
			client.AddAutomationEventHandler(eventId, el, uc.TreeScope_Element, uc.baseCacheRequest, handler)
		except comtypes.COMError:
			pass
	_localTextElement = el


def registerStructureChanged(listener, element) -> bool:
	if _suspended:
		return False
	key = id(listener)
	# Un manejador por documento: el evento sabe de qué documento viene (C1).
	handler = _StructureHandler(key)
	try:
		uc.client.AddStructureChangedEventHandler(element, uc.TreeScope_Subtree, uc.baseCacheRequest, handler)
	except comtypes.COMError:
		log.debug("No se pudo vigilar la estructura", exc_info=True)
		return False
	_structureListeners[key] = (listener, element, handler)
	return True


def unregisterStructureChanged(listener) -> None:
	entry = _structureListeners.pop(id(listener), None)
	if entry is None:
		return
	try:
		uc.client.RemoveStructureChangedEventHandler(entry[1], entry[2])
	except comtypes.COMError:
		pass


#: Eventos quitados mientras Tiresias está en espera (otro lector tiene preferencia).
_suspended = False


def suspend() -> None:
	"""Quita todos los manejadores de eventos UIA (Tiresias en espera; hilo del núcleo).

	Así Tiresias no recibe ni procesa eventos de otras aplicaciones mientras
	otro lector de pantalla tiene preferencia.
	"""
	global _suspended
	if _suspended or _handler is None:
		return
	_suspended = True
	# En el hilo de registro, detrás de lo que estuviera pendiente: así ningún
	# registro atrasado queda puesto durante la espera.
	_registrar.submit(_removeAllHandlers)
	log.info("Eventos UIA suspendidos")


def _removeAllHandlers() -> None:
	"""(Hilo de registro) Quita todos los manejadores de eventos UIA."""
	global _localTextElement
	try:
		uc.client.RemoveAllEventHandlers()
	except Exception:
		log.debug("No se pudieron quitar los eventos UIA", exc_info=True)
	_localTextElement = None


def resume() -> None:
	"""Vuelve a registrar los eventos UIA quitados con :func:`suspend`."""
	global _suspended, _handler
	if not _suspended or _handler is None:
		return
	# Lo que quedara del paso a espera (quitar los manejadores) termina antes
	# de volver a registrar nada.
	if not _registrar.wait(3.0):
		log.warning("El registro de eventos UIA sigue ocupado al reanudar")
	_suspended = False
	# Al quitarlo, UI Automation suelta el manejador y comtypes lo da por
	# liberado (ya no admite sus interfaces): hace falta uno nuevo.
	_handler = _EventHandler()
	_registrar.submit(_registerGlobalHandlers, _handler)
	for key, entry in list(_structureListeners.items()):
		listener, element = entry[0], entry[1]
		# Manejador nuevo por documento: UI Automation soltó los anteriores (C1).
		handler = _StructureHandler(key)
		_structureListeners[key] = (listener, element, handler)
		try:
			uc.client.AddStructureChangedEventHandler(element, uc.TreeScope_Subtree, uc.baseCacheRequest, handler)
		except comtypes.COMError:
			log.debug("No se pudo volver a vigilar la estructura", exc_info=True)


def isSuspended() -> bool:
	return _suspended


def terminate() -> None:
	if _registrar.isRunning:
		_registrar.submit(_removeAllHandlers)
		# Si una aplicación colgada lo retiene, no se espera más (el proceso termina).
		_registrar.stop(3.0)
		return
	try:
		uc.client.RemoveAllEventHandlers()
	except Exception:
		pass

