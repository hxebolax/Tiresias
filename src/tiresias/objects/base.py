"""Objeto accesible abstracto.

:class:`AccObject` es la representación de un control o elemento de la
interfaz (botón, lista, documento...). Las implementaciones concretas
(``UIAObject``) obtienen la información de la API de accesibilidad.

Las propiedades se definen con métodos ``_get_x`` y se cachean durante un
ciclo del núcleo. Los complementos pueden crear clases «superpuestas»
(overlay) que se mezclan con la clase base mediante
``AppModule.chooseObjectClass`` para añadir órdenes o cambiar propiedades.
"""

from __future__ import annotations

import re
from typing import Any, Iterator

from ..baseobject import ScriptableObject
from ..i18n import _
from ..log import getLogger
from ..textinfo import StaticTextInfo, TextInfo
from .roles import Role, State

log = getLogger("objects")

_dynamicClassCache: dict[tuple, type] = {}

#: Procesos que muestran contenido incrustado en ventanas de otra aplicación.
HOSTED_CONTENT_PROCESSES = {"msedgewebview2", "cefsharp.browsersubprocess", "crashpad_handler"}
_hostPidCache: dict[int, int] = {}
#: Campos con lista de sugerencias visible: clave del elemento -> bool.
_suggestionsShown: dict = {}
#: Último recuento de elementos anunciado por layoutInvalidated.
_lastLayoutCount: dict = {}


#: Nombre de tipo .NET como texto de ayuda: «DataGridViewTextBoxCell(DataGridViewCell)»
#: (WinForms pone el tipo y su base en la ayuda de las celdas) o un espacio de
#: nombres («System.Windows.Forms.X»). Una palabra suelta no cuenta y los
#: nombres han de ser compuestos en CamelCase («Tamaño(KB)» no es un tipo).
_TYPE_NAME_RE = re.compile(r"^(?:[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+(?:\.[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+)*\([A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+\)|(?:System|Microsoft|Windows)(?:\.\w+)+)$", re.ASCII)


def looksLikeTypeName(text: str, className: str = "") -> bool:
	"""``True`` si ``text`` (descripción o ayuda) es un nombre de clase o de tipo
	.NET y no un texto para el usuario."""
	text = (text or "").strip()
	if not text:
		return False
	if className and text == className:
		return True
	return bool(_TYPE_NAME_RE.match(text))


def suggestionsShownFor(obj) -> bool:
	"""``True`` si el campo ``obj`` tiene ahora una lista de sugerencias abierta."""
	try:
		key = getattr(obj, "runtimeId", None) or (obj.processID, obj.windowHandle)
	except Exception:
		return False
	return bool(_suggestionsShown.get(key, False))


#: Último texto de región viva anunciado: (texto, instante monotónico).
_lastLiveText: tuple[str, float] = ("", 0.0)
#: Segundos en los que el mismo texto de región viva no se repite (NVDA: 0,5 s).
LIVE_REGION_REPEAT_WINDOW = 0.5


def shouldReportLiveText(text: str) -> bool:
	"""``False`` si ``text`` es el mismo cambio de región viva que se acaba de anunciar.

	Muchas aplicaciones (la Calculadora, páginas web) avisan de un mismo cambio
	dos veces: el evento LiveRegionChanged y el cambio de nombre de un elemento
	con LiveSetting. Sin esto se oía dos veces («Se muestra 5»).
	"""
	import time

	global _lastLiveText
	now = time.monotonic()
	norm = " ".join((text or "").split())
	last, when = _lastLiveText
	if norm and norm == last and now - when < LIVE_REGION_REPEAT_WINDOW:
		return False
	_lastLiveText = (norm, now)
	return True


#: Ventana principal oculta de Tiresias (se averigua una vez).
_hiddenMainHwnd = 0


def isHiddenMainWindow(hwnd: int) -> bool:
	"""``True`` si ``hwnd`` es la ventana principal oculta de Tiresias."""
	global _hiddenMainHwnd
	if not hwnd:
		return False
	if not _hiddenMainHwnd:
		try:
			from .. import gui

			# El HWND guardado al crearla: sin tocar wx desde este hilo.
			_hiddenMainHwnd = int(getattr(gui, "mainFrameHwnd", 0) or 0)
		except Exception:
			_hiddenMainHwnd = 0
	return bool(_hiddenMainHwnd) and int(hwnd) == _hiddenMainHwnd


_MENU_FOCUS_ROLES = (Role.POPUPMENU, Role.MENUITEM, Role.CHECKMENUITEM, Role.RADIOMENUITEM)


def _focusMenuIfNeeded(menu: Any) -> None:
	"""Tras abrirse un menú emergente sin elemento marcado, el foco pasa al menú."""
	from .. import api
	from ..events import executeEvent

	focus = api.getFocusObject()
	try:
		if focus is not None and focus.role in _MENU_FOCUS_ROLES and focus.processID == menu.processID:
			return
		if State.INVISIBLE in menu.states or State.OFFSCREEN in menu.states:
			return
	except Exception:
		return
	executeEvent("gainFocus", menu)


def dynamicClass(bases: tuple[type, ...]) -> type:
	"""Crea (o reutiliza) una clase que combina las clases dadas."""
	cls = _dynamicClassCache.get(bases)
	if cls is None:
		name = "Dynamic_" + "".join(b.__name__ for b in bases)
		cls = type(name, bases, {"__module__": __name__})
		_dynamicClassCache[bases] = cls
	return cls


class AccObject(ScriptableObject):
	"""Clase base de todos los objetos accesibles."""

	cachePropertiesByDefault = True
	#: Clase de interceptor de árbol (modo exploración) para este objeto.
	treeInterceptorClass: type | None = None
	#: Si es ``False``, no se activa el modo exploración aunque haya clase.
	shouldCreateTreeInterceptor = True
	#: El objeto no debe anunciarse como antecesor del foco.
	isPresentableFocusAncestor = True
	#: Los módulos de aplicación pueden fijar propiedades (``obj.name = ...``).
	allowPropertyOverrides = True

	def __init__(self) -> None:
		super().__init__()
		self._treeInterceptor = None

	# ---------------------------------------------------- superposiciones
	def findOverlayClasses(self, clsList: list[type]) -> None:
		"""Añade clases de comportamiento (por defecto, ninguna)."""

	def initOverlayClass(self) -> None:
		"""Las clases superpuestas pueden definirlo para inicializarse."""

	def _applyOverlays(self) -> None:
		from ..plugins import handler as pluginHandler

		clsList: list[type] = []
		self.findOverlayClasses(clsList)
		app = self.appModule
		if app:
			try:
				app.chooseObjectClass(self, clsList)
			except Exception:
				log.exception("Error en chooseObjectClass de %s", app.appName)
		pluginHandler.chooseObjectClass(self, clsList)
		if not clsList:
			self._appModuleObjectInit(app)
			return
		base = type(self)
		bases: list[type] = []
		for c in clsList + [base]:
			if c not in bases:
				bases.append(c)
		try:
			newCls = dynamicClass(tuple(bases))
		except TypeError:
			log.exception("No se pudieron combinar las clases %r", bases)
			# Sin las superposiciones, el módulo de aplicación aún corrige sus propiedades.
			self._appModuleObjectInit(app)
			return
		self.__class__ = newCls
		# Las propiedades leídas antes del cambio de clase ya no valen.
		self.invalidateCache()
		for c in reversed(newCls.__mro__):
			init = c.__dict__.get("initOverlayClass")
			if init:
				try:
					init(self)
				except Exception:
					log.exception("Error en initOverlayClass de %s", c.__name__)
		self._appModuleObjectInit(app)

	def _appModuleObjectInit(self, app) -> None:
		"""El módulo de aplicación puede corregir propiedades (``event_NVDAObject_init``)."""
		init = getattr(app, "event_NVDAObject_init", None) if app is not None else None
		if init is None:
			return
		try:
			init(self)
		except Exception:
			log.exception("Error en event_NVDAObject_init de %s", getattr(app, "appName", app))

	# ---------------------------------------------------- identidad
	def isSameAs(self, other: "AccObject") -> bool:
		return self is other

	def __eq__(self, other: object) -> bool:
		if self is other:
			return True
		if not isinstance(other, AccObject):
			return False
		try:
			return self.isSameAs(other)
		except Exception:
			return False

	def __ne__(self, other: object) -> bool:
		return not self.__eq__(other)

	def __hash__(self) -> int:
		return id(self)

	def refreshProperties(self) -> None:
		"""Olvida lo leído en este ciclo: la próxima lectura pregunta a la aplicación.

		Se usa antes de procesar un cambio (valor, nombre, estado) del foco: el
		núcleo procesa varios eventos por ciclo y las propiedades cacheadas
		serían las de antes del cambio.
		"""
		self.invalidateCache()

	def isDefunct(self) -> bool:
		"""``True`` si el objeto ya no existe en la aplicación (por defecto, según ``State.DEFUNCT``)."""
		try:
			return State.DEFUNCT in self.states
		except Exception:
			return True

	# ---------------------------------------------------- propiedades básicas
	def _get_name(self) -> str:
		return ""

	def _get_role(self) -> Role:
		return Role.UNKNOWN

	def _get_roleText(self) -> str | None:
		"""Texto de rol personalizado (si es ``None`` se usa el del rol)."""
		return None

	def _get_presentAsCell(self) -> bool:
		"""Leer el objeto como la celda de una fila («encabezado: valor», sin su
		rol ni «solo lectura») aunque su rol sea otro."""
		return False

	def _get_states(self) -> set[State]:
		return set()

	def _get_value(self) -> str:
		return ""

	def _get_description(self) -> str:
		return ""

	def _get_helpText(self) -> str:
		return ""

	def _get_placeholder(self) -> str:
		return ""

	def _get_keyboardShortcut(self) -> str:
		return ""

	def _get_location(self) -> tuple[int, int, int, int] | None:
		return None

	def _get_positionInfo(self) -> dict[str, int]:
		return {}

	def _get_landmark(self) -> str | None:
		return None

	def _get_level(self) -> int | None:
		return None

	def _get_windowHandle(self) -> int:
		return 0

	def _get_windowClassName(self) -> str:
		from .. import winapi
		from ..a11y.api_choice import normalizeClassName

		return normalizeClassName(winapi.getClassName(self.windowHandle))

	def _get_processID(self) -> int:
		from .. import winapi

		return winapi.getWindowProcessId(self.windowHandle) if self.windowHandle else 0

	def _get_appModule(self):
		"""Módulo de aplicación del objeto (ver ``appmodules.handler.getAppModuleForObject``).

		El contenido incrustado de otro proceso (p. ej. WebView2 dentro de
		WhatsApp) usa el módulo de la aplicación que lo muestra, y las
		aplicaciones UWP el del proceso que dibuja su contenido.
		"""
		from ..appmodules import handler

		return handler.getAppModuleForObject(self)

	def _findHostProcessId(self) -> int:
		"""Proceso de la ventana de nivel superior que muestra este objeto."""
		obj = self.parent
		last = None
		guard = 0
		while obj is not None and guard < 80 and obj.role != Role.DESKTOPPANE:
			last = obj
			obj = obj.parent
			guard += 1
		try:
			return last.processID if last is not None else 0
		except Exception:
			return 0

	_cache_appModule = True

	def _get_isFocusable(self) -> bool:
		return State.FOCUSABLE in self.states

	def _get_hasFocus(self) -> bool:
		return State.FOCUSED in self.states

	# ---------------------------------------------------- navegación
	def _get_parent(self) -> "AccObject | None":
		return None

	def _get_next(self) -> "AccObject | None":
		return None

	def _get_previous(self) -> "AccObject | None":
		return None

	def _get_firstChild(self) -> "AccObject | None":
		return None

	def _get_lastChild(self) -> "AccObject | None":
		return None

	def _get_children(self) -> list["AccObject"]:
		out = []
		child = self.firstChild
		count = 0
		while child is not None and count < 10000:
			out.append(child)
			child = child.next
			count += 1
		return out

	def _get_childCount(self) -> int:
		return len(self.children)

	def iterAncestors(self) -> Iterator["AccObject"]:
		obj = self.parent
		depth = 0
		while obj is not None and depth < 100:
			yield obj
			obj = obj.parent
			depth += 1

	def _get_ancestors(self) -> list["AccObject"]:
		"""Antecesores desde la raíz hasta el padre."""
		return list(reversed(list(self.iterAncestors())))

	_cache_ancestors = False

	def _get_container(self) -> "AccObject | None":
		return self.parent

	def _get_simpleParent(self) -> "AccObject | None":
		"""Padre saltándose objetos de diseño sin interés (revisión simple)."""
		obj = self.parent
		while obj is not None and obj.presentationType == "layout":
			obj = obj.parent
		return obj

	def _get_simpleNext(self) -> "AccObject | None":
		return self._simpleSibling(1)

	def _get_simplePrevious(self) -> "AccObject | None":
		return self._simpleSibling(-1)

	def _simpleSibling(self, direction: int) -> "AccObject | None":
		obj = self.next if direction > 0 else self.previous
		guard = 0
		while obj is not None and guard < 500:
			guard += 1
			if obj.presentationType == "content":
				return obj
			if obj.presentationType == "layout":
				child = obj.firstChild if direction > 0 else obj.lastChild
				if child is not None:
					if child.presentationType == "content":
						return child
					inner = child._simpleSiblingFrom(direction)
					if inner:
						return inner
			obj = obj.next if direction > 0 else obj.previous
		return None

	def _simpleSiblingFrom(self, direction: int) -> "AccObject | None":
		obj: AccObject | None = self
		guard = 0
		while obj is not None and guard < 500:
			guard += 1
			if obj.presentationType == "content":
				return obj
			obj = obj.next if direction > 0 else obj.previous
		return None

	def _get_simpleFirstChild(self) -> "AccObject | None":
		child = self.firstChild
		guard = 0
		while child is not None and guard < 500:
			guard += 1
			if child.presentationType == "content":
				return child
			if child.presentationType == "layout":
				inner = child.simpleFirstChild
				if inner is not None:
					return inner
			child = child.next
		return None

	def _get_presentationType(self) -> str:
		"""``content`` (interesante), ``layout`` (solo estructura) o ``unavailable``."""
		states = self.states
		if State.INVISIBLE in states:
			return "unavailable"
		role = self.role
		if role in (Role.PANE, Role.PANEL, Role.SECTION, Role.GROUPING, Role.UNKNOWN, Role.CUSTOM, Role.WINDOW, Role.FILLER) and not self.name:
			return "layout"
		if role in (Role.TABLEROW, Role.TABLECOLUMN, Role.TABLEBODY, Role.TABLEHEADER, Role.TABLEFOOTER):
			return "layout"
		if role == Role.STATICTEXT and not (self.name or "").strip():
			return "unavailable"
		return "content"

	# ---------------------------------------------------- acciones
	def setFocus(self) -> None:
		pass

	def doAction(self, index: int = 0) -> bool:
		"""Ejecuta la acción por defecto (pulsar, abrir...)."""
		return False

	def scrollIntoView(self) -> None:
		pass

	def _get_actionName(self) -> str:
		return ""

	# ---------------------------------------------------- texto
	#: Clase TextInfo para el texto del objeto (``None`` si no tiene texto).
	TextInfo: type | None = None

	def _get_hasText(self) -> bool:
		return self.TextInfo is not None

	def _get_basicText(self) -> str:
		# Revisión de objeto: con la etiqueta personalizada en lugar del nombre.
		from .. import labels

		parts = [p for p in (labels.displayName(self, self.name), self.value) if p]
		return " ".join(parts)

	def makeTextInfo(self, position: Any) -> TextInfo:
		if self.TextInfo is not None:
			return self.TextInfo(self, position)
		return StaticTextInfo(self, position, self.basicText)

	def _get_isEditable(self) -> bool:
		return State.EDITABLE in self.states and State.READONLY not in self.states

	# ---------------------------------------------------- interceptores
	def _get_treeInterceptor(self):
		ti = self.__dict__.get("_treeInterceptor")
		if ti is not None and ti.isAlive:
			return ti
		from .. import tree_interceptor

		ti = tree_interceptor.getTreeInterceptor(self)
		self.__dict__["_treeInterceptor"] = ti
		return ti

	_cache_treeInterceptor = False

	def _set_treeInterceptor(self, value) -> None:
		self.__dict__["_treeInterceptor"] = value

	# ---------------------------------------------------- depuración
	def _get_devInfo(self) -> list[str]:
		info = []
		for attr in ("name", "role", "roleText", "states", "value", "description", "location", "windowHandle", "windowClassName", "processID"):
			try:
				val = getattr(self, attr)
			except Exception as e:
				val = f"excepción: {e}"
			info.append(f"{attr}: {val!r}")
		app = self.appModule
		info.append(f"appModule: {app.appName if app else None}")
		info.append(f"clase python: {type(self).__mro__}")
		return info

	_cache_devInfo = False

	# ---------------------------------------------------- eventos
	def event_gainFocus(self) -> None:
		self.reportFocus()

	def reportFocus(self) -> None:
		from .. import presentation

		presentation.speakObject(self, reason=presentation.Reason.FOCUS)

	def event_foreground(self) -> None:
		from .. import presentation, speech

		speech.cancelSpeech()
		presentation.speakObject(self, reason=presentation.Reason.FOREGROUND)

	def _isFocus(self) -> bool:
		from .. import api

		return self == api.getFocusObject()

	def event_nameChange(self) -> None:
		if self._isFocus():
			from .. import speech

			speech.speakText(self.name)

	def event_valueChange(self) -> None:
		if self._isFocus():
			from .. import presentation

			presentation.speakObjectProperties(self, value=True, reason=presentation.Reason.CHANGE)

	def event_stateChange(self) -> None:
		if self._isFocus():
			from .. import presentation

			presentation.speakObjectProperties(self, states=True, reason=presentation.Reason.CHANGE)

	def event_descriptionChange(self) -> None:
		if self._isFocus():
			from .. import presentation

			presentation.speakObjectProperties(self, description=True, reason=presentation.Reason.CHANGE)

	def event_selection(self) -> None:
		"""Selección de un elemento sin cambio de foco (lo usan módulos concretos)."""

	def event_liveRegionChange(self) -> None:
		from ..config import conf

		if not conf["presentation"]["reportDynamicContentChanges"]:
			return
		if getattr(self, "UIAFrameworkId", "") in ("Chrome", "Gecko", "MicrosoftEdge") and not conf["browseMode"]["reportLiveRegions"]:
			return
		from .. import speech

		text = self.name or self.value
		if text and shouldReportLiveText(text):
			speech.speakText(text)

	def event_controllerForChange(self) -> None:
		"""Aparece o desaparece una lista de sugerencias asociada al campo."""
		from ..config import conf

		try:
			# Accesor tipado (IUIAutomationElementArray): leer ControllerFor como
			# VARIANT corrompía el montón (cierre 0xc0000374).
			relation = getattr(self, "relationElements", None)
			present = bool(relation("controllerFor")) if relation is not None else False
		except Exception:
			present = False
		# Cada evento crea un objeto nuevo: el estado se guarda por elemento.
		key = getattr(self, "runtimeId", None) or (self.processID, self.windowHandle)
		was = _suggestionsShown.get(key, False)
		if len(_suggestionsShown) > 100:
			_suggestionsShown.clear()
		_suggestionsShown[key] = present
		self.__dict__["_suggestionsShown"] = present
		if present and not was and conf["presentation"]["reportAutoSuggestionsWithSound"]:
			from ..audio import tones

			tones.playSound("suggestion")

	def event_notification(self, displayString: str = "", activityId: str = "", **kwargs) -> None:
		from ..config import conf

		if not conf["presentation"]["reportNotifications"] or not displayString:
			return
		from .. import speech
		from ..audio import tones

		tones.playSound("notification")

		speech.speakText(displayString)

	def event_alert(self) -> None:
		from .. import presentation

		presentation.speakObject(self, reason=presentation.Reason.FOCUS)

	def event_tooltipOpen(self) -> None:
		from .. import winapi
		from ..config import conf

		isBalloon = False
		try:
			hwnd = self.windowHandle
			if hwnd and winapi.getClassName(hwnd) == "tooltips_class32":
				isBalloon = bool(winapi.user32.GetWindowLongW(hwnd, -16) & 0x40)
		except Exception:
			pass
		key = "reportHelpBalloons" if isBalloon else "reportTooltips"
		if not conf["presentation"][key]:
			return
		from .. import speech

		text = self.name or self.description
		if text:
			speech.speakText(text)

	def _get_shouldAllowFocusEvent(self) -> bool:
		"""``False`` para objetos cuyo foco no se anuncia nunca.

		La ventana principal oculta de Tiresias recibe el foco un momento al
		abrir el menú o un cuadro de mensaje: no es nada que el usuario pueda usar.
		"""
		try:
			return not isHiddenMainWindow(self.windowHandle)
		except Exception:
			return True

	def event_menuStart(self) -> None:
		"""Se abre un menú: si no llega el foco, se comprueba poco después.

		Los menús emergentes Win32 (el de Tiresias, los contextuales...) no
		marcan ningún elemento al abrirse: si el foco no pasa a un elemento del
		menú, el propio menú toma el foco y se anuncia («menú»), como en NVDA.
		"""
		from .. import queue_handler
		from ..a11y import winevents

		if self.role == Role.POPUPMENU:
			queue_handler.callLater(80, _focusMenuIfNeeded, self)
		winevents.scheduleFocusCheck(120)

	def event_menuEnd(self) -> None:
		"""Se cierra un menú: el foco vuelve a la aplicación."""
		from ..a11y import winevents

		winevents.scheduleFocusCheck(120)

	def event_itemStatusChange(self) -> None:
		"""Cambia el estado de un elemento (p. ej. «descargando», «no leído»)."""
		if not self._isFocus():
			return
		status = getattr(self, "itemStatus", "")
		if status:
			from .. import speech

			speech.speakText(status)

	def event_selectionAdd(self) -> None:
		"""Un elemento se añade a la selección (listas de selección múltiple)."""

	def event_selectionRemove(self) -> None:
		"""Un elemento se quita de la selección."""

	def event_selectionWithin(self) -> None:
		"""Cambia mucho la selección dentro de un contenedor."""

	def event_layoutInvalidated(self) -> None:
		"""Cambia el número de elementos de una lista (p. ej. sugerencias)."""
		from .. import api
		from ..config import conf

		focus = api.getFocusObject()
		if focus is None or not conf["presentation"]["reportAutoSuggestionsWithSound"]:
			return
		try:
			if focus.processID != self.processID or not suggestionsShownFor(focus):
				return
			if self.role not in (Role.LIST, Role.TREEVIEW, Role.DATAGRID, Role.TABLE):
				return
			count = self.childCount
		except Exception:
			return
		key = (getattr(self, "runtimeId", None) or self.windowHandle, count)
		if _lastLayoutCount.get("key") == key:
			return
		_lastLayoutCount["key"] = key
		from .. import speech

		speech.speakMessage(_("{n} sugerencias").format(n=count) if count != 1 else _("1 sugerencia"))

	def _dragDropMessage(self, message: str) -> None:
		from ..config import conf

		if not conf["objects"]["reportDragDrop"]:
			return
		from .. import speech

		speech.speakMessage(message)

	def event_dragStart(self) -> None:
		self._dragDropMessage(_("Arrastrando {name}").format(name=self.name or _("elemento")))

	def event_dragCancel(self) -> None:
		self._dragDropMessage(_("Arrastre cancelado"))

	def event_dragComplete(self) -> None:
		"""El arrastre termina (se anuncia al soltar sobre el destino)."""

	def event_dropTargetEnter(self) -> None:
		self._dragDropMessage(_("Sobre {name}").format(name=self.name or _("destino")))

	def event_dropTargetLeave(self) -> None:
		"""Se sale de un destino de soltar (no se anuncia para no saturar)."""

	def event_dropped(self) -> None:
		self._dragDropMessage(_("Soltado en {name}").format(name=self.name) if self.name else _("Soltado"))

	def event_sortChange(self) -> None:
		"""Cambia el orden de una columna (aria-sort), aunque no tenga el foco."""
		from ..config import conf

		if not conf["objects"]["reportSortChanges"]:
			return
		states = self.states
		if State.SORTED_ASCENDING in states:
			text = _("orden ascendente")
		elif State.SORTED_DESCENDING in states:
			text = _("orden descendente")
		elif State.SORTED in states:
			text = _("ordenado")
		else:
			text = _("sin ordenar")
		from .. import speech

		speech.speakMessage(f"{self.name} {text}".strip())

	def event_activeTextPositionChange(self) -> None:
		"""El documento mueve su posición activa (enlaces internos): como el cursor."""
		self.event_caret()

	def _get_maxLength(self) -> int | None:
		"""Longitud máxima del texto de un campo (``None`` si no tiene)."""
		return None

	def _get_itemStatus(self) -> str:
		return ""

	def _get_ariaCurrent(self) -> str:
		"""Valor de ``aria-current`` (``""`` si no tiene o es ``false``)."""
		return ""

	def event_caret(self) -> None:
		pass

	def event_textChange(self) -> None:
		pass

	def event_typedCharacter(self, ch: str) -> None:
		from .. import typing_echo

		typing_echo.onTypedCharacter(self, ch)

	def event_becomeNavigatorObject(self, isFocus: bool = False) -> None:
		pass

	def event_loseFocus(self) -> None:
		pass

	def event_show(self) -> None:
		"""Aparece un objeto (MSAA): las ayudas emergentes se leen."""
		if self.role in (Role.TOOLTIP, Role.HELPBALLOON):
			self.event_tooltipOpen()

	def event_hide(self) -> None:
		"""Desaparece un objeto (MSAA)."""

	def event_windowOpened(self) -> None:
		"""Se abre una ventana: si toma el foco sin avisar, se detecta."""
		from ..a11y import winevents

		winevents.scheduleFocusCheck(150)

	def __repr__(self) -> str:
		try:
			return f"<{type(self).__name__} {self.role.name} {self.name!r}>"
		except Exception:
			return f"<{type(self).__name__}>"

