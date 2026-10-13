"""Estado global del lector: foco, primer plano, objeto navegador y revisión.

Los complementos deben usar estas funciones para conocer dónde está el
usuario::

	from tiresias import api
	obj = api.getFocusObject()
"""

from __future__ import annotations

from typing import Any

from .extension_points import Action
from .log import getLogger

log = getLogger("api")

_focusObject = None
_focusAncestors: list = []
_foregroundObject = None
_navigatorObject = None
_reviewPosition = None
_reviewPositionObj = None
_mouseObject = None
_desktopObject = None

#: Tras cambiar el foco: ``obj``.
post_focusChange = Action()
#: Tras cambiar el objeto navegador: ``obj``.
post_navigatorObjectChange = Action()
#: Tras cambiar la posición de revisión: ``info``.
post_reviewMove = Action()


def getFocusObject():
	return _focusObject


def getFocusAncestors() -> list:
	return list(_focusAncestors)


def setFocusObject(obj, ancestors: list | None = None) -> None:
	"""Establece el objeto con foco (lo usa el manejador de eventos)."""
	global _focusObject, _focusAncestors, _reviewPosition, _reviewPositionObj
	if _navigatorObject is None and obj is not _focusObject:
		# Sin objeto navegador propio, el navegador es el foco: la posición de
		# revisión guardada era la del foco anterior.
		_reviewPosition = None
		_reviewPositionObj = None
	_focusObject = obj
	if ancestors is None:
		try:
			ancestors = obj.ancestors if obj is not None else []
		except Exception:
			ancestors = []
	_focusAncestors = ancestors
	post_focusChange.notify(obj=obj)


def getForegroundObject():
	return _foregroundObject


def setForegroundObject(obj) -> None:
	global _foregroundObject
	_foregroundObject = obj


def getNavigatorObject():
	return _navigatorObject or _focusObject


def setNavigatorObject(obj, isFocus: bool = False) -> None:
	global _navigatorObject, _reviewPosition, _reviewPositionObj
	from .a11y import system

	if system.isSecureObject(obj):
		# Con la sesión bloqueada no se sale de la pantalla de bloqueo.
		return
	_navigatorObject = obj
	_reviewPosition = None
	_reviewPositionObj = None
	if obj is not None:
		try:
			obj.event_becomeNavigatorObject(isFocus=isFocus)
		except Exception:
			log.debug("Error en becomeNavigatorObject", exc_info=True)
	post_navigatorObjectChange.notify(obj=obj)


def getReviewPosition():
	"""Posición (TextInfo) del cursor de revisión."""
	global _reviewPosition, _reviewPositionObj
	if _reviewPosition is not None:
		return _reviewPosition
	obj = getNavigatorObject()
	if obj is None:
		return None
	from . import review

	_reviewPosition = review.getPositionForCurrentMode(obj)
	_reviewPositionObj = obj
	return _reviewPosition


def setReviewPosition(info, clearNavigatorObject: bool = False, isCaret: bool = False) -> None:
	global _reviewPosition, _reviewPositionObj, _navigatorObject
	_reviewPosition = info.copy() if info is not None else None
	_reviewPositionObj = getattr(info, "obj", None)
	if clearNavigatorObject and _reviewPositionObj is not None:
		_navigatorObject = _reviewPositionObj
	post_reviewMove.notify(info=_reviewPosition, isCaret=isCaret)


def getMouseObject():
	return _mouseObject


def setMouseObject(obj) -> None:
	global _mouseObject
	_mouseObject = obj


def getDesktopObject():
	global _desktopObject
	if _desktopObject is None:
		from .objects.uia import getDesktopObject as _get

		_desktopObject = _get()
	return _desktopObject


def getCaretObject():
	"""El objeto que contiene el cursor del sistema (foco o modo exploración)."""
	focus = getFocusObject()
	if focus is None:
		return None
	ti = getattr(focus, "treeInterceptor", None)
	if ti is not None and not ti.passThrough:
		return ti
	return focus


def getStatusBar():
	"""Busca la barra de estado de la ventana en primer plano."""
	from .objects.roles import Role

	fg = getForegroundObject()
	if fg is None:
		return None
	# El módulo de la aplicación puede saber dónde está su barra de estado.
	try:
		app = fg.appModule
		bar = app.getStatusBar() if app is not None else None
		if bar is not None:
			return bar
	except Exception:
		log.debug("Error en la barra de estado del módulo de aplicación", exc_info=True)
	try:
		from .a11y import uia_client as uc
		from .objects.uia import UIAObject

		cond = uc.createPropertyCondition(uc.P_CONTROLTYPE, uc.CT_STATUSBAR)
		el = fg.element.FindFirstBuildCache(uc.TreeScope_Descendants, cond, uc.baseCacheRequest)
		if el:
			return UIAObject.fromElement(el)
	except Exception:
		log.debug("No se encontró barra de estado", exc_info=True)
	# Alternativa: hijo directo con rol barra de estado.
	try:
		for child in fg.children:
			if child.role == Role.STATUSBAR:
				return child
	except Exception:
		log.debug("No se pudieron recorrer los hijos del primer plano", exc_info=True)
	return None


def getStatusBarTextFromApp() -> str | None:
	"""Texto de la barra de estado que da el módulo de la aplicación (o ``None``)."""
	fg = getForegroundObject() or getFocusObject()
	try:
		app = fg.appModule if fg is not None else None
		return app.getStatusBarText() if app is not None else None
	except Exception:
		log.debug("Error leyendo la barra de estado del módulo de aplicación", exc_info=True)
		return None


def statusBarText(bar: Any) -> str:
	"""Texto de una barra de estado con el estado de sus conmutadores (NVDA #5687)."""
	from .i18n import _
	from .objects.roles import Role, State

	parts: list[str] = []
	try:
		children = bar.children
	except Exception:
		children = []
	for c in children:
		try:
			name = c.name or c.value
			if not name:
				continue
			states = c.states
			if c.role in (Role.TOGGLEBUTTON, Role.CHECKBOX, Role.SWITCH, Role.BUTTON) and (State.PRESSED in states or State.CHECKED in states or State.ON in states):
				name = _("{name} activado").format(name=name)
			elif c.role in (Role.TOGGLEBUTTON, Role.CHECKBOX, Role.SWITCH) or State.CHECKABLE in states:
				name = _("{name} desactivado").format(name=name)
			parts.append(name)
		except Exception:
			continue
	return " ".join(parts) or (bar.name or "")


def isObjectInForeground(obj: Any) -> bool:
	fg = getForegroundObject()
	if fg is None or obj is None:
		return False
	try:
		return obj.processID == fg.processID
	except Exception:
		return False


def copyToClip(text: str, notify: bool = False) -> bool:
	from . import clipboard, winapi

	clipboard.ignoreNextChange()
	ok = winapi.setClipboardText(text)
	if not ok:
		clipboard.cancelIgnore()
	if ok:
		from .audio import tones

		tones.playSound("copy")
	if notify:
		from . import speech
		from .config import conf
		from .i18n import _

		if not ok:
			speech.speakMessage(_("No se pudo copiar"))
		elif conf["clipboard"]["confirmCopyCommands"]:
			# Se puede desactivar: el sonido de copia basta para algunos (#9273).
			speech.speakMessage(_("Copiado al portapapeles"))
	return ok


def getClipData() -> str:
	from . import winapi

	return winapi.getClipboardText() or ""
