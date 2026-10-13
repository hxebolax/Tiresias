"""Órdenes táctiles y gestos táctiles por defecto de las órdenes globales.

:func:`install` añade a ``GlobalCommands`` las órdenes propias del soporte
táctil y asocia gestos táctiles (``ts:...``) a órdenes ya existentes. Así
aparecen en «Gestos de entrada», en la ayuda de entrada y en la paleta de
órdenes, y el usuario las puede reasignar como cualquier otra.
"""

from __future__ import annotations

from ..baseobject import normalizeGestureId, script
from ..i18n import _

CAT_TOUCH = _("Interacción táctil")

#: Elementos que recorren los deslizamientos en el modo táctil de exploración:
#: (identificador de navegación rápida o None para líneas, nombre).
BROWSE_ELEMENTS: list[tuple[str | None, str]] = [
	(None, _("líneas")),
	("heading", _("encabezados")),
	("link", _("enlaces")),
	("formField", _("campos de formulario")),
	("button", _("botones")),
	("edit", _("campos de edición")),
	("list", _("listas")),
	("table", _("tablas")),
	("landmark", _("puntos de referencia")),
	("graphic", _("gráficos")),
	("paragraph", _("párrafos")),
]

#: Gestos táctiles por defecto de órdenes globales existentes.
DEFAULT_GESTURES: dict[str, str] = {
	# Exploración y activación (cualquier modo).
	"ts:tap": "touch_newExplore",
	"ts:hoverDown": "touch_newExplore",
	"ts:hover": "touch_explore",
	"ts:hoverUp": "touch_hoverUp",
	"ts:doubleTap": "review_activate",
	"ts:splitTap": "review_activate",
	"ts:tapAndHold": "touch_rightClick",
	"ts:3finger_tap": "touch_changeMode",
	"ts:2finger_tap": "touch_stopSpeech",
	"ts:2finger_doubleTap": "showGui",
	"ts:2finger_flickDown": "review_sayAll",
	"ts:2finger_flickUp": "navigatorObject_current",
	"ts:3finger_flickUp": "reviewMode_next",
	"ts:3finger_flickDown": "reviewMode_previous",
	"ts:3finger_flickLeft": "navigatorObject_toFocus",
	"ts:3finger_flickRight": "touch_moveFocusToNavigator",
	"ts:4finger_doubleTap": "toggleInputHelp",
	"ts:4finger_tap": "touch_reportMode",
	# Modo objeto.
	"ts(object):flickRight": "navigatorObject_nextInFlow",
	"ts(object):flickLeft": "navigatorObject_previousInFlow",
	"ts(object):flickUp": "navigatorObject_parent",
	"ts(object):flickDown": "navigatorObject_firstChild",
	"ts(object):2finger_flickRight": "navigatorObject_next",
	"ts(object):2finger_flickLeft": "navigatorObject_previous",
	# Modo texto (cursor de revisión).
	"ts(text):flickUp": "review_previousLine",
	"ts(text):flickDown": "review_nextLine",
	"ts(text):flickLeft": "review_previousCharacter",
	"ts(text):flickRight": "review_nextCharacter",
	"ts(text):2finger_flickLeft": "review_previousWord",
	"ts(text):2finger_flickRight": "review_nextWord",
	# Modo exploración (páginas web y documentos).
	"ts(browse):flickRight": "touch_browseNext",
	"ts(browse):flickLeft": "touch_browsePrevious",
	"ts(browse):flickDown": "touch_browseNextElementType",
	"ts(browse):flickUp": "touch_browsePreviousElementType",
	"ts(browse):2finger_flickRight": "navigatorObject_nextInFlow",
	"ts(browse):2finger_flickLeft": "navigatorObject_previousInFlow",
	# Secuencias de dos deslizamientos (en cualquier modo). Contrarias:
	"ts:flickRightThenLeft": "navigatorObject_toFocus",
	"ts:flickLeftThenRight": "reportCurrentFocus",
	"ts:flickUpThenDown": "review_currentLine",
	"ts:flickDownThenUp": "dateTime",
	# En L:
	"ts:flickRightThenDown": "touch_tab",
	"ts:flickLeftThenUp": "touch_shiftTab",
	"ts:flickDownThenRight": "touch_enter",
	"ts:flickDownThenLeft": "touch_escape",
	"ts:flickUpThenRight": "title",
	"ts:flickUpThenLeft": "speakForeground",
	"ts:flickRightThenUp": "reportStatusLine",
	"ts:flickLeftThenDown": "touch_applicationsKey",
	# Gestos de borde (solo si se activan en las opciones). Si un gesto de
	# borde no tiene orden, se usa la del deslizamiento normal.
	"ts:leftEdge_flickRight": "touch_escape",
	"ts:rightEdge_flickLeft": "navigatorObject_toFocus",
	"ts:topEdge_flickDown": "title",
	"ts:bottomEdge_flickUp": "reportStatusLine",
}

_browseIndex = 0


def _handler():
	from .handler import handler

	return handler


# ====================================================================== órdenes
def script_touch_toggleSupport(self, gesture) -> None:
	from .. import speech
	from ..config import conf

	h = _handler()
	if not h.hasTouchScreen():
		# Sin pantalla táctil no se cambia nada: solo se avisa.
		speech.speakMessage(h.setEnabled(True))
		return
	speech.speakMessage(h.setEnabled(not conf["touch"]["enabled"]))


def script_touch_toggleTouchpad(self, gesture) -> None:
	from .. import speech
	from ..config import conf

	speech.speakMessage(_handler().setTouchpadEnabled(not conf["touch"]["touchpadEnabled"]))


def script_touch_changeMode(self, gesture) -> None:
	from .. import speech

	speech.speakMessage(_handler().cycleMode())


def script_touch_reportMode(self, gesture) -> None:
	from .. import speech
	from .gestures import MODE_LABELS

	speech.speakMessage(MODE_LABELS[_handler().effectiveMode()])


def script_touch_newExplore(self, gesture) -> None:
	x, y = getattr(gesture, "x", None), getattr(gesture, "y", None)
	if x is None:
		return
	_handler().explore(x, y, new=True)


def script_touch_explore(self, gesture) -> None:
	x, y = getattr(gesture, "x", None), getattr(gesture, "y", None)
	if x is None:
		return
	_handler().explore(x, y)


def _isTouchKey(obj) -> bool:
	"""¿Es una tecla del teclado táctil de Windows?"""
	from ..objects.roles import Role

	if obj is None:
		return False
	cls = (getattr(obj, "UIAClassName", "") or "").lower()
	if cls == "crootkey":
		return True
	if obj.role not in (Role.BUTTON,):
		return False
	try:
		from .. import winapi

		proc = winapi.getProcessName(obj.processID).lower()
	except Exception:
		proc = ""
	return proc in ("textinputhost.exe", "textinputhost", "tabtip.exe", "tabtip")


def script_touch_hoverUp(self, gesture) -> None:
	from .. import api
	from ..config import conf

	if not conf["touch"]["touchTyping"]:
		return
	obj = api.getNavigatorObject()
	if _isTouchKey(obj):
		obj.doAction()


def script_touch_rightClick(self, gesture) -> None:
	from .. import api, mouse, speech

	obj = api.getNavigatorObject()
	x = y = None
	try:
		pt = api.getReviewPosition().pointAtStart
		x, y = pt.x, pt.y
	except Exception:
		pass
	if x is None:
		loc = obj.location if obj is not None else None
		if not loc:
			speech.speakMessage(_("el objeto no tiene ubicación"))
			return
		lx, ly, w, h = loc
		x, y = lx + w // 2, ly + h // 2
	speech.speakMessage(_("clic derecho"))
	mouse.click(x, y, button="right")


def _sendKey(name: str) -> None:
	from ..input.gestures import sendKey

	sendKey(name)


def script_touch_tab(self, gesture) -> None:
	_sendKey("tab")


def script_touch_shiftTab(self, gesture) -> None:
	_sendKey("shift+tab")


def script_touch_enter(self, gesture) -> None:
	_sendKey("enter")


def script_touch_escape(self, gesture) -> None:
	_sendKey("escape")


def script_touch_applicationsKey(self, gesture) -> None:
	_sendKey("applications")


def script_touch_stopSpeech(self, gesture) -> None:
	from .. import speech

	speech.cancelSpeech()


def script_touch_moveFocusToNavigator(self, gesture) -> None:
	from .. import api, speech

	obj = api.getNavigatorObject()
	if obj is None:
		return
	obj.setFocus()
	speech.speakMessage(_("foco movido"))


def _browseMove(direction: int) -> None:
	from .. import speech, textinfo

	doc = _handler().browseDocument()
	if doc is None:
		speech.speakMessage(_("no hay ningún documento en modo exploración"))
		return
	key, _label = BROWSE_ELEMENTS[_browseIndex % len(BROWSE_ELEMENTS)]
	if key is None:
		doc._moveByUnit(textinfo.UNIT_LINE, direction)
	else:
		doc.quickNav(key, direction)


def _browseType(direction: int) -> None:
	global _browseIndex
	from .. import speech

	_browseIndex = (_browseIndex + direction) % len(BROWSE_ELEMENTS)
	speech.speakMessage(BROWSE_ELEMENTS[_browseIndex][1])


def script_touch_browseNext(self, gesture) -> None:
	_browseMove(1)


def script_touch_browsePrevious(self, gesture) -> None:
	_browseMove(-1)


def script_touch_browseNextElementType(self, gesture) -> None:
	_browseType(1)


def script_touch_browsePreviousElementType(self, gesture) -> None:
	_browseType(-1)


#: (función, descripción, gestos de teclado propios)
_SCRIPTS = [
	(script_touch_toggleSupport, _("Activa o desactiva la interacción táctil"), ("kb:tiresias+control+alt+t",)),
	(script_touch_toggleTouchpad, _("Activa o desactiva los gestos en el panel táctil (touchpad)"), ()),
	(script_touch_changeMode, _("Cambia el modo táctil (objeto, texto, exploración)"), ()),
	(script_touch_reportMode, _("Anuncia el modo táctil actual"), ()),
	(script_touch_newExplore, _("Lee el objeto y el texto que hay bajo el dedo"), ()),
	(script_touch_explore, _("Lee lo que hay bajo el dedo si ha cambiado al arrastrarlo"), ()),
	(script_touch_hoverUp, _("Al levantar el dedo: pulsa la tecla del teclado táctil si la escritura táctil está activada"), ()),
	(script_touch_rightClick, _("Clic derecho en la posición del objeto navegador (abre el menú contextual)"), ()),
	(script_touch_stopSpeech, _("Hace callar la voz"), ()),
	(script_touch_moveFocusToNavigator, _("Lleva el foco al objeto navegador"), ()),
	(script_touch_tab, _("Pulsa Tabulador (control siguiente)"), ()),
	(script_touch_shiftTab, _("Pulsa Mayúsculas+Tabulador (control anterior)"), ()),
	(script_touch_enter, _("Pulsa Intro"), ()),
	(script_touch_escape, _("Pulsa Escape (atrás, cerrar)"), ()),
	(script_touch_applicationsKey, _("Pulsa la tecla Aplicaciones (menú contextual)"), ()),
	(script_touch_browseNext, _("Modo táctil de exploración: va al siguiente elemento del tipo elegido"), ()),
	(script_touch_browsePrevious, _("Modo táctil de exploración: va al elemento anterior del tipo elegido"), ()),
	(script_touch_browseNextElementType, _("Modo táctil de exploración: elige el siguiente tipo de elemento"), ()),
	(script_touch_browsePreviousElementType, _("Modo táctil de exploración: elige el tipo de elemento anterior"), ()),
]

#: Órdenes que no deben cortar la voz al ejecutarse (la exploración decide
#: ella misma si hay algo nuevo que decir).
_NO_SPEECH_INTERRUPT = {"script_touch_newExplore", "script_touch_explore", "script_touch_hoverUp"}

_installed: set[type] = set()


def install(cls: type) -> None:
	"""Añade las órdenes y los gestos táctiles a ``cls`` (``GlobalCommands``)."""
	if cls in _installed:
		return
	_installed.add(cls)
	gestures = cls.__dict__.get("_classGestures")
	if gestures is None:
		gestures = {}
		cls._classGestures = gestures  # type: ignore[attr-defined]
	for func, description, keys in _SCRIPTS:
		name = func.__name__
		if name not in cls.__dict__:
			wrapped = script(description=description, category=CAT_TOUCH, gestures=keys, allowInSleepMode=name == "script_touch_toggleSupport")(func)
			if name in _NO_SPEECH_INTERRUPT:
				wrapped.noSpeechInterrupt = True  # type: ignore[attr-defined]
			setattr(cls, name, wrapped)
		for g in keys:
			gestures.setdefault(normalizeGestureId(g), name[7:])
	for gid, scriptName in DEFAULT_GESTURES.items():
		if hasattr(cls, "script_" + scriptName):
			gestures.setdefault(normalizeGestureId(gid), scriptName)
