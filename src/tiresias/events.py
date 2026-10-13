"""Despacho de eventos de accesibilidad.

Cada evento (``gainFocus``, ``nameChange``, ``valueChange``...) pasa por esta
cadena, en orden, hasta que alguien no llama a ``nextHandler``:

1. Complementos globales: ``event_<nombre>(obj, nextHandler, **kw)``.
2. Módulo de aplicación: ``event_<nombre>(obj, nextHandler, **kw)``.
3. Interceptor de árbol (modo exploración): igual que el anterior.
4. El propio objeto: ``event_<nombre>(**kw)``.
"""

from __future__ import annotations

from typing import Any

from . import api, presentation, speech, tree_interceptor
from .config import conf
from .extension_points import Action
from .log import getLogger
from .objects.roles import Role, State

log = getLogger("events")

#: Se notifica tras procesar un evento: ``eventName``, ``obj``.
post_event = Action()

#: Roles de antecesores que se anuncian al entrar el foco en ellos.
ANNOUNCED_ANCESTOR_ROLES = {
	Role.DIALOG,
	Role.GROUPING,
	Role.PROPERTYPAGE,
	Role.LIST,
	Role.TREEVIEW,
	Role.TABLE,
	Role.DATAGRID,
	Role.TOOLBAR,
	Role.LANDMARK,
	Role.REGION,
	Role.FORM,
	Role.ARTICLE,
	Role.TABCONTROL,
	Role.DOCUMENT,
	Role.STATUSBAR,
	Role.MENUBAR,
	Role.ALERT,
}

_ANCESTOR_ROLES_NEED_NAME = {Role.GROUPING, Role.PANE, Role.PANEL, Role.SECTION, Role.TOOLBAR, Role.TABCONTROL, Role.DOCUMENT, Role.LIST, Role.TREEVIEW, Role.MENUBAR}

_lastFocusAncestors: list = []

#: Contenedores genéricos cuyo foco, sin nombre, no dice nada al usuario.
_TRANSIENT_CONTAINER_ROLES = {Role.PANE, Role.PANEL, Role.SECTION, Role.GROUPING, Role.WINDOW}
#: Segundos tras un foco en los que un foco vacío en su antecesor se ignora.
TRANSIENT_FOCUS_WINDOW = 1.0
#: Instante (monotónico) del último foco aceptado.
_lastFocusTime = 0.0


def _plugins():
	from .plugins import handler

	return handler.runningPlugins


def executeEvent(eventName: str, obj: Any, **kwargs: Any) -> None:
	"""Ejecuta un evento sobre ``obj`` a través de toda la cadena."""
	if log.isEnabledFor(10):
		log.debug("Evento %s en %r %s", eventName, obj, kwargs or "")
	try:
		from .a11y import system

		if system.isSecureObject(obj):
			# Pantalla de bloqueo activa: nada de fuera de ella se anuncia.
			log.debug("Evento %s descartado: objeto protegido por la pantalla de bloqueo", eventName)
			return
		if not _appAcceptsEvent(eventName, obj, kwargs):
			return
		if eventName == "gainFocus":
			if isTransientContainerFocus(obj):
				log.debug("Foco transitorio en un contenedor vacío antecesor del foco: se ignora")
				return
			if not _doPreGainFocus(obj):
				return
		app = None
		try:
			app = obj.appModule
		except Exception:
			app = None
		if app is not None and app.sleepMode:
			# Modo dormir: el foco y el primer plano ya están actualizados
			# (_doPreGainFocus), pero no se anuncia nada: ni el objeto, ni el
			# modo exploración, ni los complementos globales (como NVDA).
			return
		_runChain(eventName, obj, app, kwargs)
		post_event.notify(eventName=eventName, obj=obj)
	except Exception:
		log.exception("Error en el evento %s de %r", eventName, obj)


def _appAcceptsEvent(eventName: str, obj: Any, kwargs: dict) -> bool:
	"""Filtro de eventos del módulo de aplicación (``AppModule.shouldProcessEvent``)."""
	try:
		app = obj.appModule
	except Exception:
		return True
	filt = getattr(app, "shouldProcessEvent", None) if app is not None else None
	if filt is None:
		return True
	try:
		return bool(filt(eventName, obj, **kwargs))
	except Exception:
		log.exception("Error en el filtro de eventos de %r", app)
		return True


def _runChain(eventName: str, obj: Any, app: Any, kwargs: dict) -> None:
	handlers: list = []
	attr = "event_" + eventName
	for p in _plugins():
		f = getattr(p, attr, None)
		if f:
			handlers.append(("ext", f))
	if app is not None and not app.sleepMode:
		f = getattr(app, attr, None)
		if f:
			handlers.append(("ext", f))
	ti = None
	try:
		ti = obj.treeInterceptor if eventName not in ("foreground",) else None
	except Exception:
		ti = None
	if ti is not None:
		f = getattr(ti, attr, None)
		if f:
			handlers.append(("ext", f))
	objFunc = getattr(obj, attr, None)

	def call(i: int) -> None:
		if i >= len(handlers):
			if objFunc is not None and (app is None or not app.sleepMode):
				objFunc(**kwargs)
			return
		_kind, f = handlers[i]
		f(obj, lambda: call(i + 1), **kwargs)

	call(0)


def _isAnnouncedAncestor(obj: Any) -> bool:
	try:
		role = obj.role
		if role not in ANNOUNCED_ANCESTOR_ROLES:
			return False
		if not obj.isPresentableFocusAncestor:
			return False
		if role in _ANCESTOR_ROLES_NEED_NAME and not obj.name:
			return False
		if obj.presentationType != "content":
			return False
		return True
	except Exception:
		return False


def isTransientContainerFocus(obj: Any) -> bool:
	"""``True`` si el foco en ``obj`` es un rebote vacío que no debe cortar la voz.

	Algunas aplicaciones (islas XAML, marcos web) dan el foco un instante al
	contenedor sin nombre que rodea al elemento recién anunciado. Aceptarlo
	descarta la voz del elemento (ya no es el foco) y no dice nada a cambio.
	Se ignora solo si: llega poco después del foco anterior, el contenedor es
	genérico (panel, sección, agrupación, ventana), no tiene nombre ni valor,
	el foco anterior sigue vivo y el contenedor es uno de sus antecesores.
	"""
	import time

	old = api.getFocusObject()
	if old is None or obj is old:
		return False
	if time.monotonic() - _lastFocusTime > TRANSIENT_FOCUS_WINDOW:
		return False
	try:
		if obj.role not in _TRANSIENT_CONTAINER_ROLES or obj.name or obj.value:
			return False
		if not any(obj == anc for anc in api.getFocusAncestors()[1:]):
			return False
		# El foco anterior tiene que seguir existiendo (un elemento UIA borrado
		# no marca DEFUNCT: se pregunta a la aplicación). Si no, el contenedor
		# es el foco de verdad y no se puede ignorar.
		return not _isDefunct(old)
	except Exception:
		return False


def _isDefunct(obj: Any) -> bool:
	"""``True`` si ``obj`` ya no existe en la aplicación."""
	check = getattr(obj, "isDefunct", None)
	if check is not None:
		try:
			return bool(check())
		except Exception:
			return True
	try:
		return State.DEFUNCT in obj.states
	except Exception:
		return True


#: Máximo de antecesores que se suben al calcular la línea del foco.
MAX_ANCESTOR_DEPTH = 100


def computeAncestors(obj: Any) -> list:
	"""Antecesores de ``obj`` (de la raíz al padre) reutilizando los del foco anterior.

	Como NVDA (``api.setFocusObject``): se sube desde el padre de ``obj`` hasta
	encontrar un objeto que ya estaba en la línea del foco anterior (o el propio
	foco anterior); desde ahí se reutiliza esa línea en vez de seguir subiendo
	(cada paso es una llamada a la aplicación y crear un objeto).
	"""
	oldLine = api.getFocusAncestors()
	oldFocus = api.getFocusObject()
	if oldFocus is not None:
		oldLine = oldLine + [oldFocus]
	chain: list = []
	cur = obj.parent
	depth = 0
	while cur is not None and depth < MAX_ANCESTOR_DEPTH:
		for i in range(len(oldLine) - 1, -1, -1):
			try:
				same = cur is oldLine[i] or cur == oldLine[i]
			except Exception:
				same = False
			if same:
				return oldLine[:i] + [cur] + list(reversed(chain))
		chain.append(cur)
		try:
			cur = cur.parent
		except Exception:
			break
		depth += 1
	chain.reverse()
	return chain


def _doPreGainFocus(obj: Any) -> bool:
	global _lastFocusAncestors, _lastFocusTime
	import time

	from .appmodules import handler as appHandler
	from .input import core as inputCore

	_lastFocusTime = time.monotonic()
	oldFocus = api.getFocusObject()
	try:
		ancestors = computeAncestors(obj)
	except Exception:
		ancestors = []
	# Primer plano: el antecesor hijo del escritorio.
	newForeground = ancestors[1] if len(ancestors) > 1 else (ancestors[0] if ancestors and obj.role in (Role.WINDOW, Role.DIALOG) else obj)
	if len(ancestors) == 1:
		newForeground = obj
	oldForeground = api.getForegroundObject()
	api.setFocusObject(obj, ancestors)
	try:
		app = obj.appModule
	except Exception:
		app = None
	appHandler.handleForegroundApp(app)
	ti = tree_interceptor.update(obj, ancestors)
	obj.treeInterceptor = ti
	inputCore.manager.updateChain()
	if conf["reviewCursor"]["followFocus"]:
		api.setNavigatorObject(obj, isFocus=True)
	if oldFocus is not None and oldFocus != obj:
		try:
			executeEvent("loseFocus", oldFocus)
		except Exception:
			pass
	foregroundChanged = newForeground is not None and (oldForeground is None or newForeground != oldForeground)
	if foregroundChanged:
		api.setForegroundObject(newForeground)
	if app is not None and app.sleepMode:
		# El primer plano se actualiza también en modo dormir: si no, al volver
		# a la ventana anterior no se anunciaría (seguiría siendo «la misma»).
		_lastFocusAncestors = ancestors
		return True
	if foregroundChanged:
		speech.cancelSpeech()
		if newForeground != obj:
			executeEvent("foreground", newForeground)
	if conf["presentation"]["announceFocusAncestors"]:
		# Antecesores nuevos respecto al foco anterior.
		diff = 0
		old = _lastFocusAncestors
		while diff < len(ancestors) and diff < len(old) and ancestors[diff] == old[diff]:
			diff += 1
		for anc in ancestors[max(diff, 2) :]:
			if ti is not None and anc == ti.rootObject:
				continue
			if _isAnnouncedAncestor(anc):
				executeEvent("focusEntered", anc)
	_lastFocusAncestors = ancestors
	return True


def _focusEnteredDefault(obj: Any) -> None:
	if obj.role in (Role.MENUBAR, Role.POPUPMENU, Role.MENUITEM):
		return
	presentation.speakObject(obj, reason=presentation.Reason.FOCUSENTERED)


# El evento focusEntered por defecto para todos los objetos.
def _installDefaults() -> None:
	from .objects.base import AccObject

	if not hasattr(AccObject, "event_focusEntered"):
		AccObject.event_focusEntered = lambda self: _focusEnteredDefault(self)  # type: ignore[attr-defined]


_installDefaults()


def isFocusLost() -> bool:
	"""``True`` si no hay foco o el objeto con el foco ya no existe (también UIA)."""
	focus = api.getFocusObject()
	if focus is None:
		return True
	return _isDefunct(focus)
