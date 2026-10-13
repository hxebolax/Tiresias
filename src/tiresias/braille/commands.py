"""Órdenes braille que se añaden a las órdenes globales.

:func:`install` las añade a ``GlobalCommands`` (como el soporte táctil), así
aparecen en «Gestos de entrada», en la ayuda de entrada y en la paleta de
órdenes, y se pueden reasignar. Los gestos ``bk:`` son los del teclado
braille de cualquier línea (y del teclado braille del PC).
"""

from __future__ import annotations

from typing import Any

from ..baseobject import normalizeGestureId, script
from ..config import conf
from ..i18n import _

CAT_BRAILLE = _("Braille")


def _speak(text: str) -> None:
	from .. import speech

	speech.speakMessage(text)


def _handler():
	from . import handler

	return handler


def _input():
	from . import input as brailleInput

	return brailleInput.handler


def _cycle(key: str, values: list[tuple[Any, str]]) -> str:
	cur = conf["braille"][key]
	keys = [v for v, _l in values]
	idx = (keys.index(cur) + 1) % len(values) if cur in keys else 0
	conf["braille"][key] = values[idx][0]
	_handler().applyConfig()
	return values[idx][1]


# ====================================================================== modos
def script_braille_toggleMode(self, gesture) -> None:
	if conf["braille"]["mode"] == "speechOutput":
		conf["braille"]["mode"] = "followCursors"
		msg = _("braille sigue a los cursores")
	else:
		conf["braille"]["mode"] = "speechOutput"
		msg = _("braille muestra la voz")
	_handler().applyConfig()
	_speak(msg)


def script_braille_toggleAutoScroll(self, gesture) -> None:
	h = _handler()
	if not h.enabled:
		_speak(_("no hay línea braille"))
		return
	h.setAutoScroll(not h.autoScrollActive)
	_speak(_("desplazamiento automático activado") if h.autoScrollActive else _("desplazamiento automático desactivado"))


def _changeRate(delta: int) -> None:
	rate = max(1, min(20, int(conf["braille"]["autoScrollRate"] or 10) + delta))
	conf["braille"]["autoScrollRate"] = rate
	_handler()._scheduleAutoScroll()
	_speak(_("{n} celdas por segundo").format(n=rate))


def script_braille_increaseAutoScrollRate(self, gesture) -> None:
	_changeRate(1)


def script_braille_decreaseAutoScrollRate(self, gesture) -> None:
	_changeRate(-1)


def script_braille_cycleSplitView(self, gesture) -> None:
	values = [
		("off", _("línea sin dividir")),
		("speech", _("línea dividida: última frase dicha")),
		("review", _("línea dividida: cursor de revisión")),
		("title", _("línea dividida: título de la ventana")),
		("clock", _("línea dividida: hora y fecha")),
	]
	_speak(_cycle("splitView", values))


def script_braille_toFocus(self, gesture) -> None:
	_handler().toFocus()


def script_braille_toggleViewer(self, gesture) -> None:
	h = _handler()
	h.setViewer(not h.viewerActive)
	_speak(_("visor braille activado") if h.viewerActive else _("visor braille desactivado"))


# ====================================================================== opciones
def script_braille_toggleShowCursor(self, gesture) -> None:
	conf["braille"]["showCursor"] = not conf["braille"]["showCursor"]
	_handler().applyConfig()
	_speak(_("cursor braille visible") if conf["braille"]["showCursor"] else _("cursor braille oculto"))


def script_braille_cycleCursorShape(self, gesture) -> None:
	shapes = [(0x40, _("punto 7")), (0x80, _("punto 8")), (0xC0, _("puntos 7 y 8")), (0xFF, _("todos los puntos"))]
	key = "cursorShapeReview" if _handler()._source == "review" else "cursorShapeFocus"
	_speak(_("forma del cursor: {shape}").format(shape=_cycle(key, shapes)))


def script_braille_cycleFocusContextPresentation(self, gesture) -> None:
	values = [
		("fill", _("rellenar la línea con el contexto")),
		("changedContext", _("mostrar solo el contexto que cambia")),
		("scroll", _("mostrar el contexto al desplazar hacia atrás")),
	]
	_speak(_cycle("focusContextPresentation", values))


def script_braille_cycleShowMessages(self, gesture) -> None:
	values = [("disabled", _("mensajes braille desactivados")), ("timeout", _("mensajes braille con tiempo de espera")), ("always", _("mensajes braille indefinidos"))]
	_speak(_cycle("showMessages", values))


def script_braille_toggleShowSelection(self, gesture) -> None:
	conf["braille"]["showSelection"] = not conf["braille"]["showSelection"]
	_handler().applyConfig()
	_speak(_("mostrar la selección activado") if conf["braille"]["showSelection"] else _("mostrar la selección desactivado"))


def script_braille_toggleUnicodeNormalization(self, gesture) -> None:
	conf["braille"]["unicodeNormalization"] = not conf["braille"]["unicodeNormalization"]
	_handler().applyConfig()
	_speak(_("normalización Unicode activada") if conf["braille"]["unicodeNormalization"] else _("normalización Unicode desactivada"))


def script_braille_cycleTextWrap(self, gesture) -> None:
	values = [
		("none", _("ajuste del texto desactivado")),
		("markWordCuts", _("marcar las palabras cortadas")),
		("wordBoundaries", _("ajustar en los límites de palabra")),
		("syllableBoundaries", _("ajustar en los límites de palabra o sílaba")),
	]
	_speak(_cycle("textWrap", values))


def script_braille_cycleReviewRoutingMovesSystemCaret(self, gesture) -> None:
	values = [
		("never", _("enrutar en la revisión no mueve el cursor del sistema")),
		("onlyWhenAutoTethered", _("enrutar en la revisión mueve el cursor del sistema solo con seguimiento automático")),
		("always", _("enrutar en la revisión mueve siempre el cursor del sistema")),
	]
	_speak(_cycle("reviewRoutingMovesSystemCaret", values))


def script_braille_toggleSpeakOnRouting(self, gesture) -> None:
	conf["braille"]["speakOnRouting"] = not conf["braille"]["speakOnRouting"]
	_speak(_("leer al enrutar activado") if conf["braille"]["speakOnRouting"] else _("leer al enrutar desactivado"))


def script_braille_cycleOutputTable(self, gesture) -> None:
	"""Alterna entre la tabla de salida y la de entrada elegidas (#19479)."""
	from . import tables

	b = conf["braille"]
	out = b["translationTable"]
	inp = b["inputTable"]
	if tables.resolveName(out) == tables.resolveName(inp, forInput=True):
		_speak(_("las tablas de entrada y de salida son la misma"))
		return
	# Solo se intercambian si cada tabla sirve para su nuevo sentido.
	newOut = tables.getTable(inp)
	newIn = tables.getTable(out, True)
	if not newOut.forOutput or not newIn.forInput:
		bad = newOut if not newOut.forOutput else newIn
		if bad is newOut:
			msg = _("No se pueden intercambiar las tablas: {table} no sirve como tabla de salida")
		else:
			msg = _("No se pueden intercambiar las tablas: {table} no sirve como tabla de entrada")
		_speak(msg.format(table=bad.displayName))
		return
	b["translationTable"], b["inputTable"] = inp, out
	_handler().applyConfig()
	_speak(_("salida: {out}; entrada: {inp}").format(out=tables.getTable(inp).displayName, inp=tables.getTable(out, True).displayName))


# ====================================================================== línea
def script_braille_selectRange(self, gesture) -> None:
	h = _handler()
	indexes = list(getattr(gesture, "routingIndexes", None) or [])
	if not indexes and getattr(gesture, "routingIndex", None) is not None:
		indexes = [gesture.routingIndex]
	if not indexes:
		return
	if len(indexes) >= 2:
		error = h.selectRange(min(indexes), max(indexes))
	else:
		# Dos pulsaciones: la primera marca el inicio y la segunda selecciona.
		# Se guarda la posición en el texto (no la celda), por si la ventana
		# se desplaza entre las dos pulsaciones.
		anchor = getattr(h, "_selectAnchor", None)
		if anchor is None:
			anchor = h.selectionAnchorAt(indexes[0])
			if anchor is None:
				_speak(_("No se puede seleccionar desde la línea braille aquí"))
				return
			h._selectAnchor = anchor
			_speak(_("inicio de la selección marcado"))
			return
		h._selectAnchor = None
		error = h.selectFromAnchor(anchor, indexes[0])
	if error:
		_speak(error)


def script_braille_reportFormatting(self, gesture) -> None:
	index = getattr(gesture, "routingIndex", None)
	h = _handler()
	if index is None:
		cell = h._cursorCell()
		index = (cell - h.windowStart) if cell is not None else 0
	text = h.formattingAtCell(index)
	_speak(text or _("sin información de formato"))


# ====================================================================== entrada braille
def script_braille_dots(self, gesture) -> None:
	_input().input(getattr(gesture, "dots", 0))


def script_braille_eraseLastCell(self, gesture) -> None:
	_input().eraseLastCell()


def script_braille_translate(self, gesture) -> None:
	_input().translate()


def _toggle(*mods: str) -> None:
	_speak(_input().toggleModifiers(mods))


def script_braille_toggleControl(self, gesture) -> None:
	_toggle("control")


def script_braille_toggleAlt(self, gesture) -> None:
	_toggle("alt")


def script_braille_toggleShift(self, gesture) -> None:
	_toggle("shift")


def script_braille_toggleWindows(self, gesture) -> None:
	_toggle("windows")


def script_braille_toggleTiresiasKey(self, gesture) -> None:
	_toggle("tiresias")


def script_braille_toggleControlShift(self, gesture) -> None:
	_toggle("control", "shift")


def script_braille_toggleAltShift(self, gesture) -> None:
	_toggle("alt", "shift")


def script_braille_togglePcKeyboard(self, gesture) -> None:
	from . import input as brailleInput

	kb = brailleInput.pcKeyboard
	kb.setEnabled(not kb.enabled)
	if kb.enabled:
		dotsN = int(conf["braille"]["pcKeyboardDots"] or 8)
		_speak(_("teclado braille del PC activado, {n} puntos").format(n=dotsN))
	else:
		_speak(_("teclado braille del PC desactivado"))


# ====================================================================== instalación
#: (función, descripción, gestos)
_SCRIPTS: list[tuple[Any, str, tuple[str, ...]]] = [
	(script_braille_toggleMode, _("Alterna el modo braille: seguir a los cursores o mostrar lo que se dice"), ("kb:tiresias+alt+t",)),
	(script_braille_toggleAutoScroll, _("Activa o desactiva el desplazamiento automático de la línea braille"), ("kb:tiresias+alt+k",)),
	(script_braille_increaseAutoScrollRate, _("Aumenta la velocidad del desplazamiento automático del braille"), ("kb:tiresias+alt+l",)),
	(script_braille_decreaseAutoScrollRate, _("Reduce la velocidad del desplazamiento automático del braille"), ("kb:tiresias+alt+j",)),
	(script_braille_cycleSplitView, _("Divide la línea braille y elige qué se muestra en la parte derecha"), ("kb:tiresias+alt+b",)),
	(script_braille_toFocus, _("Lleva la línea braille al foco"), ()),
	(script_braille_toggleViewer, _("Abre o cierra el visor braille"), ()),
	(script_braille_toggleShowCursor, _("Muestra u oculta el cursor braille"), ()),
	(script_braille_cycleCursorShape, _("Cambia la forma del cursor braille"), ()),
	(script_braille_cycleFocusContextPresentation, _("Cambia la presentación del contexto del foco en braille"), ()),
	(script_braille_cycleShowMessages, _("Cambia cómo se muestran los mensajes en braille"), ()),
	(script_braille_toggleShowSelection, _("Activa o desactiva la indicación de la selección en braille"), ()),
	(script_braille_toggleUnicodeNormalization, _("Activa o desactiva la normalización Unicode en braille"), ()),
	(script_braille_cycleTextWrap, _("Cambia el ajuste del texto en la línea braille"), ()),
	(script_braille_cycleReviewRoutingMovesSystemCaret, _("Cambia si enrutar en la revisión mueve el cursor del sistema"), ()),
	(script_braille_toggleSpeakOnRouting, _("Activa o desactiva la lectura del carácter al enrutar"), ()),
	(script_braille_cycleOutputTable, _("Intercambia las tablas braille de salida y de entrada"), ()),
	(script_braille_selectRange, _("Selecciona el texto entre dos celdas de la línea braille"), ()),
	(script_braille_reportFormatting, _("Anuncia el formato del texto bajo la celda braille"), ()),
	(script_braille_dots, _("Escribe con el teclado braille"), ("bk:dots",)),
	(script_braille_eraseLastCell, _("Borra la última celda o carácter escrito con el teclado braille"), ("bk:dot7",)),
	(script_braille_translate, _("Traduce las celdas braille pendientes"), ("bk:dot7+dot8",)),
	(script_braille_toggleControl, _("Teclado braille: Control para la siguiente tecla"), ("bk:space+dot1+dot4+dot8",)),
	(script_braille_toggleAlt, _("Teclado braille: Alt para la siguiente tecla"), ("bk:space+dot1+dot8",)),
	(script_braille_toggleShift, _("Teclado braille: Mayúsculas para la siguiente tecla"), ("bk:space+dot2+dot3+dot4+dot8",)),
	(script_braille_toggleWindows, _("Teclado braille: Windows para la siguiente tecla"), ("bk:space+dot2+dot4+dot5+dot6+dot8",)),
	(script_braille_toggleTiresiasKey, _("Teclado braille: tecla Tiresias para la siguiente tecla"), ("bk:space+dot2+dot3+dot4+dot5+dot8",)),
	(script_braille_toggleControlShift, _("Teclado braille: Control y Mayúsculas para la siguiente tecla"), ()),
	(script_braille_toggleAltShift, _("Teclado braille: Alt y Mayúsculas para la siguiente tecla"), ()),
	(script_braille_togglePcKeyboard, _("Usa las teclas F D S J K L del teclado como teclado braille"), ("kb:tiresias+control+alt+b",)),
]

#: Gestos por defecto de órdenes que ya existen en las órdenes globales.
DEFAULT_GESTURES = {
	"bk:dot8": "braille_enter",
}

_installed: set[type] = set()


def install(cls: type) -> None:
	"""Añade las órdenes braille a ``cls`` (``GlobalCommands``)."""
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
			setattr(cls, name, script(description=description, category=CAT_BRAILLE, gestures=keys)(func))
		for g in keys:
			gestures.setdefault(normalizeGestureId(g), name[7:])
	for gid, scriptName in DEFAULT_GESTURES.items():
		if hasattr(cls, "script_" + scriptName):
			gestures.setdefault(normalizeGestureId(gid), scriptName)
