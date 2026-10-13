"""Eventos WinEvent del sistema: MSAA, IAccessible2, consola y escritorio.

Los ganchos ``SetWinEventHook`` se instalan en el hilo de ganchos
(``input/hooks.py``) con la lista :data:`WIN_EVENTS`. La retrollamada
:func:`onWinEvent` se ejecuta en ese hilo y debe ser rapidísima: solo filtra
(sin llamadas entre procesos) y encola el trabajo en el hilo del núcleo.

Usos:

- Detectar cambios de ventana en primer plano y de foco que UIA no avisa.
- Todos los eventos de las ventanas que se leen con MSAA/IAccessible2 (ver
  :mod:`api_choice`): foco, nombre, valor, estado, descripción, aparición y
  desaparición, selección (y selección múltiple), cursor, menús, alertas,
  regiones vivas y eventos de texto de IAccessible2.
- Eventos de la consola clásica (``EVENT_CONSOLE_*``): texto nuevo y cursor.
- Cambio al escritorio seguro (UAC, inicio de sesión) y vuelta.
- Cambio de escritorio virtual: el escritorio (``#32769``) cambia de nombre
  (ver :mod:`tiresias.virtual_desktops`).
"""

from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes

from .. import api, queue_handler, virtual_desktops, winapi
from ..i18n import _
from ..log import getLogger
from . import api_choice, msaa

log = getLogger("winEvents")

_user32 = ctypes.windll.user32
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD

_pendingCheck: int | None = None
#: Proceso y ventana del foco actual (los lee el hilo de ganchos).
_focusPid = 0
_focusIsMSAA = False
_focusRootHwnd = 0
_ownPid = os.getpid()
#: Hay un evento de texto de consola encolado (para no inundar el núcleo).
_consolePending = False
#: Última ventana en primer plano que no es de Tiresias (para volver a ella
#: al cerrar un diálogo o menú propio).
_lastForeignForeground = 0


def lastForeignForeground() -> int:
	"""Última ventana activa de otra aplicación (0 si no se sabe)."""
	return _lastForeignForeground

#: Eventos de objeto MSAA -> nombre de evento de Tiresias.
MSAA_EVENTS = {
	msaa.EVENT_OBJECT_NAMECHANGE: "nameChange",
	msaa.EVENT_OBJECT_VALUECHANGE: "valueChange",
	msaa.EVENT_OBJECT_STATECHANGE: "stateChange",
	msaa.EVENT_OBJECT_DESCRIPTIONCHANGE: "descriptionChange",
	msaa.EVENT_OBJECT_SHOW: "show",
	msaa.EVENT_OBJECT_HIDE: "hide",
	msaa.EVENT_OBJECT_SELECTION: "selection",
	msaa.EVENT_OBJECT_SELECTIONADD: "selectionAdd",
	msaa.EVENT_OBJECT_SELECTIONREMOVE: "selectionRemove",
	msaa.EVENT_OBJECT_SELECTIONWITHIN: "selectionWithin",
	msaa.EVENT_OBJECT_LIVEREGIONCHANGED: "liveRegionChange",
	msaa.EVENT_OBJECT_TEXTSELECTIONCHANGED: "caret",
	msaa.EVENT_SYSTEM_ALERT: "alert",
	msaa.EVENT_SYSTEM_MENUSTART: "menuStart",
	msaa.EVENT_SYSTEM_MENUPOPUPSTART: "menuStart",
	msaa.IA2_EVENT_TEXT_CARET_MOVED: "caret",
	msaa.IA2_EVENT_TEXT_INSERTED: "textChange",
	msaa.IA2_EVENT_TEXT_REMOVED: "textChange",
	msaa.IA2_EVENT_TEXT_UPDATED: "textChange",
	msaa.IA2_EVENT_TEXT_CHANGED: "textChange",
	msaa.IA2_EVENT_DOCUMENT_LOAD_COMPLETE: "documentLoadComplete",
	msaa.IA2_EVENT_OBJECT_ATTRIBUTE_CHANGED: "IA2AttributeChange",
	msaa.IA2_EVENT_ACTIVE_DESCENDANT_CHANGED: "activeDescendantChange",
}

#: Eventos que solo interesan si el objeto es el foco.
_FOCUS_ONLY = {"nameChange", "descriptionChange", "caret", "textChange"}

#: Cambios que se agrupan: si el mismo evento del mismo objeto ya espera en la
#: cola del núcleo, no se encola otra vez (el valor se lee al procesarlo). Así,
#: con el núcleo ocupado, varias flechas seguidas en un cuadro combinado dan un
#: solo anuncio con el valor final, no uno repetido por cada evento atrasado.
_COALESCED = {"valueChange", "nameChange", "stateChange", "descriptionChange", "selection"}
#: Eventos que nunca se agrupan (cada uno trae un aviso distinto). El resto se
#: agrupa por objeto igual que :data:`_COALESCED` (el estado se lee al procesarlo).
_NOT_COALESCED = {"alert", "liveRegionChange", "menuStart", "menuEnd"}
#: clave -> instante en que se encoló (una clave de más de 1 s ya no bloquea,
#: por si la cola se vació sin procesarla).
_pendingChanges: dict = {}
#: Límite de avalanchas (como el limitador de NVDA): eventos pendientes en la
#: cola del núcleo por cada hilo de la aplicación que los genera. Con más, los
#: nuevos se descartan: los que esperan leerán el estado actual al procesarse.
MAX_PENDING_PER_THREAD = 30
_pendingPerThread: dict[int, int] = {}
_pendingLock = threading.Lock()
#: Número del último foco MSAA encolado (los anteriores aún en cola se descartan).
_msaaFocusSeq = 0
#: Clases cuyos eventos «show» se procesan aunque sean de un objeto hijo
#: (como NVDA: el resto inundaba el núcleo sin anunciar nada).
_SHOW_CLASSES = frozenset({"tooltips_class32", "Frame Notification Bar", "mscandui21.candidate", "mscandui40.candidate", "MSCandUIWindow_Candidate", "TTrayAlert"})
#: Segundos que una comprobación del foco puede aplazarse como máximo.
FOCUS_CHECK_MAX_WAIT = 0.5
_pendingCheckSince = 0.0
#: La próxima comprobación del foco anuncia el foco aunque no haya cambiado.
_forceFocusCheck = False

CONSOLE_EVENTS = {
	msaa.EVENT_CONSOLE_CARET: "caret",
	msaa.EVENT_CONSOLE_UPDATE_REGION: "textChange",
	msaa.EVENT_CONSOLE_UPDATE_SIMPLE: "textChange",
	msaa.EVENT_CONSOLE_UPDATE_SCROLL: "textChange",
	msaa.EVENT_CONSOLE_LAYOUT: "textChange",
}


def _pidOf(hwnd: int) -> int:
	pid = wintypes.DWORD()
	_user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
	return pid.value


def _isMenuWindow(hwnd: int) -> bool:
	"""``True`` si ``hwnd`` es un menú Win32 (#32768); sin llamadas entre procesos."""
	return api_choice.getClassName(hwnd) == api_choice.MENU_CLASS


def isForegroundRelated(hwnd: int) -> bool:
	"""``True`` si ``hwnd`` pertenece a la ventana activa (sin llamadas entre procesos).

	Como ``eventHandler.shouldAcceptEvent`` de NVDA: la propia ventana activa o
	una descendiente, el mismo dueño raíz (cintas de Office, ventanas
	emergentes), el mismo proceso, la ventana activa del hilo en primer plano,
	los menús Win32 y las ventanas de Tiresias. Si no se puede saber, se acepta.
	"""
	try:
		fg = int(_user32.GetForegroundWindow() or 0)
		if not fg or not hwnd:
			return True
		if hwnd == fg:
			return True
		root = winapi.getAncestor(hwnd, winapi.GA_ROOT) or hwnd
		if root == fg:
			return True
		pid = _pidOf(hwnd)
		if pid == _ownPid or pid == _pidOf(fg):
			return True
		if winapi.getAncestor(hwnd, winapi.GA_ROOTOWNER) == winapi.getAncestor(fg, winapi.GA_ROOTOWNER):
			return True
		if _isMenuWindow(hwnd) or _isMenuWindow(root):
			return True
		info = winapi.getGUIThreadInfo(winapi.getWindowThreadId(fg))
		if info is not None:
			for h in (info.hwndActive, info.hwndFocus):
				h = int(h or 0)
				if h and (h == hwnd or winapi.getAncestor(h, winapi.GA_ROOT) == root):
					return True
		return False
	except Exception:
		return True


def _sameFocusRoot(hwnd: int) -> bool:
	"""``hwnd`` está en la ventana raíz del foco MSAA actual."""
	if not _focusIsMSAA or not _focusRootHwnd:
		return False
	return hwnd == _focusRootHwnd or winapi.getAncestor(hwnd, winapi.GA_ROOT) == _focusRootHwnd


def _countPending(threadId: int) -> bool:
	"""Anota un evento pendiente del hilo ``threadId``; ``False`` si ya hay demasiados."""
	with _pendingLock:
		n = _pendingPerThread.get(threadId, 0)
		if n >= MAX_PENDING_PER_THREAD:
			return False
		if len(_pendingPerThread) > 2000:
			_pendingPerThread.clear()
		_pendingPerThread[threadId] = n + 1
		return True


def _releasePending(threadId: int) -> None:
	with _pendingLock:
		n = _pendingPerThread.get(threadId, 0) - 1
		if n > 0:
			_pendingPerThread[threadId] = n
		else:
			_pendingPerThread.pop(threadId, None)


def _onFocusChange(obj=None) -> None:
	"""Recuerda el proceso del foco para filtrar en el hilo de ganchos."""
	global _focusPid, _focusIsMSAA, _focusRootHwnd
	try:
		_focusPid = int(obj.processID) if obj is not None else 0
	except Exception:
		_focusPid = 0
	_focusIsMSAA = obj is not None and hasattr(obj, "IAccessibleObject")
	try:
		hwnd = obj.windowHandle if obj is not None else 0
		_focusRootHwnd = winapi.getAncestor(hwnd, winapi.GA_ROOT) if hwnd else 0
	except Exception:
		_focusRootHwnd = 0


api.post_focusChange.register(_onFocusChange)


def shouldRecoverEarly() -> bool:
	"""(Cualquier hilo, sin llamadas entre procesos) ¿El usuario ha dejado la ventana del foco?

	Para el vigilante (como ``_shouldRecoverAfterMinTimeout`` de NVDA): si el
	núcleo está bloqueado y la ventana activa ya no es la del foco de Tiresias
	(el usuario cambió de aplicación, o no hay ventana con foco), conviene
	cancelar la llamada bloqueada enseguida en vez de esperar el tiempo normal.
	"""
	try:
		fg = int(_user32.GetForegroundWindow() or 0)
		if not fg:
			return True
		info = winapi.getGUIThreadInfo(winapi.getWindowThreadId(fg))
		if info is None or not info.hwndFocus:
			# Hilo en primer plano colgado o sin foco.
			return True
		if not _focusRootHwnd:
			return False
		return winapi.getAncestor(int(info.hwndFocus), winapi.GA_ROOT) != _focusRootHwnd and fg != _focusRootHwnd
	except Exception:
		return False


# ------------------------------------------------------------------ hilo de ganchos
def onWinEvent(event: int, hwnd: int, idObject: int, idChild: int, threadId: int) -> None:
	"""Retrollamada en el hilo de ganchos: filtra y encola."""
	if event == msaa.EVENT_SYSTEM_FOREGROUND:
		global _lastForeignForeground
		if hwnd and _pidOf(hwnd) != _ownPid:
			_lastForeignForeground = hwnd
		queue_handler.queueFunction(_onForeground)
		return
	if event in (msaa.EVENT_SYSTEM_MENUPOPUPEND, msaa.EVENT_SYSTEM_MENUEND, msaa.EVENT_SYSTEM_SWITCHEND):
		queue_handler.queueFunction(scheduleFocusCheck, 120)
		if event == msaa.EVENT_SYSTEM_MENUEND and api_choice.cachedAPI(hwnd) == api_choice.API_MSAA:
			queue_handler.queueFunction(_onMSAAEvent, "menuEnd", hwnd, idObject, idChild)
		return
	if event == msaa.EVENT_SYSTEM_DESKTOPSWITCH:
		queue_handler.queueFunction(_onDesktopSwitch)
		return
	if event == msaa.EVENT_OBJECT_NAMECHANGE and virtual_desktops.isDesktopNameChange(hwnd):
		# Cambio de escritorio virtual: el escritorio (#32769) toma su nombre.
		if idObject in (msaa.OBJID_WINDOW, msaa.OBJID_CLIENT) and idChild == msaa.CHILDID_SELF:
			queue_handler.queueFunction(virtual_desktops.onNameChange, virtual_desktops.readDesktopTitle(hwnd))
		return
	if msaa.EVENT_CONSOLE_CARET <= event <= msaa.EVENT_CONSOLE_END_APPLICATION:
		name = CONSOLE_EVENTS.get(event)
		if name and hwnd and (hwnd == _focusRootHwnd or winapi.getAncestor(hwnd, winapi.GA_ROOT) == _focusRootHwnd):
			global _consolePending
			if name == "textChange":
				# La consola manda muchísimos eventos: basta uno pendiente a la vez.
				if _consolePending:
					return
				_consolePending = True
			queue_handler.queueFunction(_onConsoleEvent, name, hwnd)
		return
	if not hwnd:
		return
	choice = api_choice.cachedAPI(hwnd)
	if event == msaa.EVENT_OBJECT_FOCUS:
		if choice == api_choice.API_MSAA or choice is None:
			if not isForegroundRelated(hwnd):
				# Foco interno de una ventana en segundo plano: no es el foco del
				# sistema (foco «fantasma»).
				return
			global _msaaFocusSeq
			_msaaFocusSeq += 1
			queue_handler.queueFunction(_onFocusWinEvent, hwnd, idObject, idChild, _msaaFocusSeq)
		elif choice == api_choice.API_UIA and idObject == msaa.OBJID_CLIENT:
			queue_handler.queueFunction(scheduleFocusCheck, 150)
		return
	if event == msaa.EVENT_OBJECT_LOCATIONCHANGE:
		if idObject == msaa.OBJID_CARET and choice == api_choice.API_MSAA and _focusIsMSAA:
			queue_handler.queueFunction(_onMSAAEvent, "caret", hwnd, idObject, idChild)
		return
	name = MSAA_EVENTS.get(event)
	if name is None:
		return
	if choice is not None and choice != api_choice.API_MSAA:
		return
	pid = _pidOf(hwnd)
	if name == "menuStart" and pid != _ownPid:
		# Inicio de un menú: el foco del teclado sigue en el control que lo abrió,
		# así que cuenta el proceso del foco o el de la ventana activa (la ventana
		# del menú nunca es la activa). Los menús Win32 (#32768) se leen siempre
		# con MSAA, aunque el foco sea de una ventana UIA (ver api_choice).
		if pid != _focusPid and pid != _pidOf(_user32.GetForegroundWindow() or 0):
			return
		if choice is None and not (_focusIsMSAA and pid == _focusPid) and not _isMenuWindow(hwnd):
			return
	elif pid == _ownPid and pid != _focusPid:
		# Ventanas de Tiresias sin el foco: solo sus menús emergentes (el menú
		# de Tiresias se abre sobre otra aplicación).
		if name != "menuStart":
			return
	elif choice is None:
		# Ventana sin decidir: solo si es del proceso del foco MSAA (sub-ventanas).
		if not _focusIsMSAA or pid != _focusPid:
			return
	elif name != "alert" and name != "liveRegionChange" and pid != _focusPid:
		# Las aplicaciones en segundo plano solo pueden avisar con alertas.
		return
	if name == "hide":
		# Nadie los anuncia y llegan a miles (como NVDA, se descartan).
		return
	if name == "show" and idChild != msaa.CHILDID_SELF and api_choice.getClassName(hwnd) not in _SHOW_CLASSES:
		# Cada objeto nuevo de una aplicación IA2 manda el suyo: solo cuentan las
		# ventanas que aparecen (ayudas emergentes) y las clases conocidas.
		return
	if name in _FOCUS_ONLY and not _sameFocusRoot(hwnd):
		# Solo interesan si son del foco: se descartan antes de crear el objeto.
		return
	if name not in _NOT_COALESCED:
		key = (name, hwnd, idObject, idChild)
		now = time.monotonic()
		queued = _pendingChanges.get(key)
		if queued is not None and now - queued < 1.0:
			return
		if len(_pendingChanges) > 500:
			_pendingChanges.clear()
		_pendingChanges[key] = now
		if threadId and not _countPending(threadId):
			# Avalancha de este hilo: lo que ya espera basta.
			_pendingChanges.pop(key, None)
			return
		queue_handler.queueFunction(_onMSAAEvent, name, hwnd, idObject, idChild, threadId)
		return
	queue_handler.queueFunction(_onMSAAEvent, name, hwnd, idObject, idChild)


# ------------------------------------------------------------------ núcleo
def scheduleFocusCheck(delay: int, force: bool = False) -> None:
	"""Comprueba el foco real dentro de ``delay`` ms (agrupa peticiones).

	Las peticiones seguidas aplazan la comprobación, pero nunca más de
	:data:`FOCUS_CHECK_MAX_WAIT` desde la primera (eventos que se repiten sin
	parar ya no la aplazan para siempre). ``force``: se anuncia el foco aunque
	sea el mismo de antes (vuelta del escritorio seguro).
	"""
	global _pendingCheck, _pendingCheckSince, _forceFocusCheck
	if force:
		_forceFocusCheck = True
	now = time.monotonic()
	if _pendingCheck is not None:
		if now - _pendingCheckSince >= FOCUS_CHECK_MAX_WAIT:
			# Ya se aplazó bastante: se deja la que está programada.
			return
		queue_handler.cancelCallLater(_pendingCheck)
	else:
		_pendingCheckSince = now
	_pendingCheck = queue_handler.callLater(delay, _checkFocus)


# Compatibilidad con el nombre antiguo.
_scheduleFocusCheck = scheduleFocusCheck


def _checkFocus() -> None:
	"""Si la API no avisó del cambio de foco, se detecta aquí."""
	global _pendingCheck, _forceFocusCheck
	_pendingCheck = None
	force, _forceFocusCheck = _forceFocusCheck, False
	from ..events import executeEvent
	from ..objects.uia import getFocusObject

	focus = api.getFocusObject()
	if _menuStillOpen(focus):
		# Con un menú abierto, el foco «de Windows» sigue en el control que lo
		# abrió (el campo de un menú contextual): no se le devuelve el foco.
		return
	obj = getFocusObject()
	if obj is None:
		return
	if focus is not None and obj == focus and not force:
		return
	if not getattr(obj, "shouldAllowFocusEvent", True):
		return
	executeEvent("gainFocus", obj)
	from . import uia_handler

	uia_handler._registerLocalHandlers(obj)


#: GUITHREADINFO.flags: el hilo está en un menú (barra o emergente).
_GUI_INMENUMODE = 0x4
_GUI_POPUPMENUMODE = 0x10


def _menuStillOpen(focus) -> bool:
	"""``True`` si el foco es un elemento de un menú que sigue abierto."""
	from ..objects.roles import Role

	if focus is None:
		return False
	try:
		if focus.role not in (Role.MENUITEM, Role.CHECKMENUITEM, Role.RADIOMENUITEM, Role.POPUPMENU):
			return False
		hwnd = focus.windowHandle
		if not hwnd or not _user32.IsWindow(hwnd) or not _user32.IsWindowVisible(hwnd):
			return False
		info = winapi.getGUIThreadInfo(winapi.getWindowThreadId(hwnd))
	except Exception:
		return False
	return info is not None and bool(info.flags & (_GUI_INMENUMODE | _GUI_POPUPMENUMODE))


def _onForeground() -> None:
	from . import system

	system.invalidateLockCache()
	scheduleFocusCheck(80)


#: Antecesores que se miran como máximo buscando el estado «con foco».
_FOCUSED_SEARCH_DEPTH = 30


def _isWindowFocus(hwnd: int) -> bool:
	"""``hwnd`` es la ventana con el foco del teclado de su hilo."""
	try:
		info = winapi.getGUIThreadInfo(winapi.getWindowThreadId(hwnd))
		return info is not None and int(info.hwndFocus or 0) == hwnd
	except Exception:
		return False


def shouldAllowMSAAFocus(obj, hwnd: int, idObject: int, idChild: int) -> bool:
	"""El objeto (o uno de sus antecesores) tiene el estado «con foco».

	Como ``shouldAllowIAccessibleFocusEvent`` de NVDA: descarta los focos
	caducados (el elemento ya lo perdió cuando se procesa el evento) y los
	internos de controles que no tienen el foco. El foco de la propia ventana
	que Windows da como enfocada se acepta siempre.
	"""
	from ..objects.roles import State

	if idChild == msaa.CHILDID_SELF and idObject == msaa.OBJID_CLIENT and _isWindowFocus(hwnd):
		return True
	test = obj
	depth = 0
	while test is not None and depth < _FOCUSED_SEARCH_DEPTH:
		try:
			if State.FOCUSED in test.states:
				return True
			test = test.parent
		except Exception:
			return True
		depth += 1
	return False


def _onFocusWinEvent(hwnd: int, idObject: int, idChild: int, seq: int | None = None) -> None:
	"""Foco MSAA: si la ventana se lee con MSAA se anuncia el objeto."""
	if seq is not None and seq != _msaaFocusSeq:
		# Llegó otro foco MSAA más reciente: este ya no vale.
		return
	choice = api_choice.chooseAPI(hwnd)
	if choice != api_choice.API_MSAA:
		if choice == api_choice.API_UIA and idObject == msaa.OBJID_CLIENT:
			scheduleFocusCheck(150)
		return
	from ..events import executeEvent
	from ..objects.iaccessible import IAccessibleObject
	from ..objects.roles import Role, State

	obj = IAccessibleObject.fromEvent(hwnd, idObject, idChild)
	if obj is None:
		return
	try:
		# Algunos contenedores avisan del foco y el elemento activo está dentro.
		if obj.role in (Role.LIST, Role.TREEVIEW, Role.TABLE, Role.MENUBAR, Role.TABCONTROL) and State.FOCUSED in obj.states:
			inner = obj._focusedDescendant()
			if inner is not None:
				obj = inner
	except Exception:
		pass
	if not getattr(obj, "shouldAllowFocusEvent", True):
		return
	if not shouldAllowMSAAFocus(obj, hwnd, idObject, idChild):
		# Foco caducado o interno: por si acaso, se mira el foco real.
		log.debug("Foco MSAA sin estado «con foco» descartado: %x %d %d", hwnd, idObject, idChild)
		scheduleFocusCheck(150)
		return
	focus = api.getFocusObject()
	if focus is not None and obj == focus:
		return
	executeEvent("gainFocus", obj)
	from . import uia_handler

	uia_handler._registerLocalHandlers(obj)


#: Último valor del atributo «sort» de IA2 por objeto.
_ia2SortStates: dict[tuple, str] = {}


def _onMSAAEvent(name: str, hwnd: int, idObject: int, idChild: int, threadId: int = 0) -> None:
	_pendingChanges.pop((name, hwnd, idObject, idChild), None)
	if threadId:
		_releasePending(threadId)
	from ..events import executeEvent
	from ..objects.iaccessible import IAccessibleObject
	from ..objects.roles import Role

	focus = api.getFocusObject()
	if name == "caret" and idObject == msaa.OBJID_CARET:
		# El cursor del sistema se movió: el evento es del objeto con el foco.
		if isinstance(focus, IAccessibleObject) and focus.windowHandle == hwnd:
			executeEvent("caret", focus)
		return
	obj = IAccessibleObject.fromEvent(hwnd, idObject, idChild)
	if obj is None:
		return
	isFocus = focus is not None and obj == focus
	if name in _FOCUS_ONLY and not isFocus:
		if name == "caret" and isinstance(focus, IAccessibleObject) and focus.windowHandle == hwnd:
			# IA2: el cursor pasa a otro objeto de texto (otro párrafo).
			executeEvent("caret", obj)
		return
	if name == "valueChange" and not isFocus and obj.role != Role.PROGRESSBAR:
		return
	if name == "stateChange" and not isFocus and obj.role not in (Role.CHECKBOX, Role.RADIOBUTTON, Role.TOGGLEBUTTON, Role.TREEVIEWITEM, Role.LISTITEM):
		return
	if name == "activeDescendantChange":
		if not isFocus:
			return
		inner = obj._focusedDescendant()
		if inner is not None and inner != focus:
			executeEvent("gainFocus", inner)
		return
	if name == "IA2AttributeChange":
		key = (hwnd, idObject, idChild)
		sort = obj.IA2Attributes.get("sort", "")
		old = _ia2SortStates.get(key)
		_ia2SortStates[key] = sort
		if len(_ia2SortStates) > 200:
			_ia2SortStates.clear()
		if (old is not None and old != sort) or (old is None and sort not in ("", "none")):
			executeEvent("sortChange", obj)
		return
	if isFocus:
		obj = focus
		# Lo leído del foco en este ciclo es de antes del cambio.
		_refresh(obj)
	executeEvent(name, obj)


def _refresh(obj) -> None:
	refresh = getattr(obj, "refreshProperties", None)
	if refresh is not None:
		try:
			refresh()
		except Exception:
			log.debug("No se pudieron refrescar las propiedades", exc_info=True)


def _onConsoleEvent(name: str, hwnd: int) -> None:
	"""Eventos de la consola clásica: texto nuevo o movimiento del cursor."""
	global _consolePending
	from ..events import executeEvent
	from ..objects.roles import Role

	if name == "textChange":
		_consolePending = False

	focus = api.getFocusObject()
	if focus is None:
		return
	try:
		if focus.role != Role.TERMINAL:
			return
		fh = focus.windowHandle
		if fh != hwnd and winapi.getAncestor(fh, winapi.GA_ROOT) != winapi.getAncestor(hwnd, winapi.GA_ROOT):
			return
	except Exception:
		return
	executeEvent(name, focus)


def _onDesktopSwitch() -> None:
	from .. import speech
	from . import system

	global _onSecureDesktop
	system.invalidateLockCache()
	# Las teclas soltadas en otro escritorio no llegan al gancho: se olvidan.
	from ..input import core as inputCore

	inputCore.manager.onDesktopSwitch()
	if system.isSecureDesktopActive():
		_onSecureDesktop = True
		if system.secureScreensEnabled():
			# La copia instalada lee esa pantalla (Windows la inicia allí): basta
			# un aviso breve para no solaparse con ella.
			speech.cancelSpeech()
			speech.speakMessage(_("Escritorio seguro"))
		else:
			speech.speakMessage(
				_("Escritorio seguro (Control de cuentas de usuario o inicio de sesión). Tiresias no puede leerlo porque Windows solo lo permite a servicios del sistema.")
			)
		return
	# Vuelta al escritorio normal: se lee el foco de nuevo, aunque sea el mismo
	# control de antes (al cancelar el Control de cuentas no se oía nada).
	wasSecure, _onSecureDesktop = _onSecureDesktop, False
	scheduleFocusCheck(300, force=wasSecure)


#: Tiresias vio pasar al escritorio seguro y aún no ha vuelto.
_onSecureDesktop = False


WIN_EVENTS = [
	(msaa.EVENT_SYSTEM_ALERT, msaa.EVENT_SYSTEM_MENUPOPUPEND, onWinEvent),
	(msaa.EVENT_SYSTEM_SWITCHEND, msaa.EVENT_SYSTEM_SWITCHEND, onWinEvent),
	(msaa.EVENT_SYSTEM_DESKTOPSWITCH, msaa.EVENT_SYSTEM_DESKTOPSWITCH, onWinEvent),
	(msaa.EVENT_CONSOLE_CARET, msaa.EVENT_CONSOLE_LAYOUT, onWinEvent),
	(msaa.EVENT_OBJECT_SHOW, msaa.EVENT_OBJECT_LIVEREGIONCHANGED, onWinEvent),
	(msaa.IA2_EVENT_ACTIVE_DESCENDANT_CHANGED, msaa.IA2_EVENT_TEXT_SELECTION_CHANGED, onWinEvent),
	# Ventanas del propio Tiresias (se leen con MSAA, ver api_choice): solo lo
	# necesario para el foco, los valores, la selección y el cursor.
	(msaa.EVENT_SYSTEM_ALERT, msaa.EVENT_SYSTEM_MENUPOPUPEND, onWinEvent, True),
	(msaa.EVENT_OBJECT_FOCUS, msaa.EVENT_OBJECT_VALUECHANGE, onWinEvent, True),
	(msaa.EVENT_OBJECT_TEXTSELECTIONCHANGED, msaa.EVENT_OBJECT_TEXTSELECTIONCHANGED, onWinEvent, True),
]
