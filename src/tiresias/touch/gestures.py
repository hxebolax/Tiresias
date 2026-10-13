"""Gestos táctiles para el gestor de entrada y sus nombres en español.

Identificadores (siempre en minúsculas tras normalizarlos):

- ``ts:<gesto>``: pantalla táctil en cualquier modo táctil.
- ``ts(<modo>):<gesto>``: solo en ese modo (``object``, ``text`` o ``browse``).
- ``tp:<gesto>`` y ``tp(<modo>):<gesto>``: el mismo gesto hecho en el panel
  táctil (touchpad). Un gesto del panel también lleva los identificadores
  ``ts`` equivalentes, así que por defecto hace lo mismo que en la pantalla.

``<gesto>`` es la acción con el número de dedos delante si son varios:
``tap``, ``doubleTap``, ``2finger_flickDown``, ``3finger_tap``,
``flickRightThenLeft``... Los gestos de borde llevan el borde delante
(``leftEdge_flickRight``); su gesto también lleva los identificadores sin
borde, así que si el gesto de borde no tiene orden se usa la del gesto normal.
"""

from __future__ import annotations

from ..baseobject import normalizeGestureId
from ..i18n import _
from . import recognizer as R

OBJECT_MODE = "object"
TEXT_MODE = "text"
BROWSE_MODE = "browse"
MODES = (OBJECT_MODE, TEXT_MODE, BROWSE_MODE)

MODE_LABELS = {
	OBJECT_MODE: _("modo objeto"),
	TEXT_MODE: _("modo texto"),
	BROWSE_MODE: _("modo exploración"),
}

SOURCE_LABELS = {
	"ts": _("pantalla táctil"),
	"tp": _("panel táctil"),
}

#: Acción (en minúsculas) -> nombre en español.
ACTION_LABELS = {
	R.TAP.lower(): _("toque"),
	R.DOUBLE_TAP.lower(): _("doble toque"),
	R.TRIPLE_TAP.lower(): _("triple toque"),
	R.TAP_AND_HOLD.lower(): _("toque y mantener"),
	R.DOUBLE_TAP_AND_HOLD.lower(): _("doble toque y mantener"),
	R.HOLD.lower(): _("mantener"),
	R.FLICK_UP.lower(): _("deslizar hacia arriba"),
	R.FLICK_DOWN.lower(): _("deslizar hacia abajo"),
	R.FLICK_LEFT.lower(): _("deslizar a la izquierda"),
	R.FLICK_RIGHT.lower(): _("deslizar a la derecha"),
	R.PINCH_IN.lower(): _("pellizcar"),
	R.PINCH_OUT.lower(): _("separar los dedos"),
	R.HOVER_DOWN.lower(): _("apoyar el dedo para explorar"),
	R.HOVER.lower(): _("explorar arrastrando el dedo"),
	R.HOVER_UP.lower(): _("levantar el dedo al explorar"),
	R.SPLIT_TAP.lower(): _("toque dividido"),
}

_DIRECTION_LABELS = {
	R.FLICK_UP: _("hacia arriba"),
	R.FLICK_DOWN: _("hacia abajo"),
	R.FLICK_LEFT: _("a la izquierda"),
	R.FLICK_RIGHT: _("a la derecha"),
}
for _first in _DIRECTION_LABELS:
	for _second in _DIRECTION_LABELS:
		if _first != _second:
			ACTION_LABELS[R.sequenceAction(_first, _second).lower()] = _("deslizar {first} y luego {second}").format(
				first=_DIRECTION_LABELS[_first], second=_DIRECTION_LABELS[_second]
			)

EDGE_LABELS = {
	"left": _("desde el borde izquierdo"),
	"right": _("desde el borde derecho"),
	"top": _("desde el borde superior"),
	"bottom": _("desde el borde inferior"),
}


def actionLabel(name: str) -> str:
	"""``2finger_flickdown`` -> ``deslizar hacia abajo con 2 dedos``;
	``leftedge_flickright`` -> ``deslizar a la derecha desde el borde izquierdo``."""
	edge, name = R.splitEdge(name)
	fingers, action = R.splitName(name)
	label = ACTION_LABELS.get(action.lower(), action)
	if fingers > 1:
		label = _("{action} con {n} dedos").format(action=label, n=fingers)
	if edge:
		label = f"{label} {EDGE_LABELS[edge]}"
	return label


def splitIdentifier(gestureId: str) -> tuple[str, str | None, str]:
	"""``ts(object):flickright`` -> (``ts``, ``object``, ``flickright``)."""
	prefix, _sep, name = gestureId.partition(":")
	prefix = prefix.lower()
	mode = None
	if "(" in prefix and prefix.endswith(")"):
		prefix, mode = prefix[:-1].split("(", 1)
	return prefix, mode, name


def isTouchIdentifier(gestureId: str) -> bool:
	return splitIdentifier(gestureId)[0] in SOURCE_LABELS


def labelForIdentifier(gestureId: str) -> str:
	"""Nombre en español de un identificador de gesto táctil.

	``ts(object):2finger_flickright`` -> «pantalla táctil: deslizar a la
	derecha con 2 dedos (modo objeto)».
	"""
	source, mode, name = splitIdentifier(gestureId)
	label = f"{SOURCE_LABELS.get(source, source)}: {actionLabel(name)}"
	if mode:
		label += f" ({MODE_LABELS.get(mode, mode)})"
	return label


def identifiersFor(name: str, mode: str, source: str = "ts", edgeName: str | None = None) -> list[str]:
	"""Identificadores de más concreto a más general.

	Con borde: primero los del gesto de borde y después los del gesto normal.
	"""
	ids = []
	for n in ([edgeName] if edgeName else []) + [name]:
		if source == "tp":
			ids += [f"tp({mode}):{n}", f"tp:{n}"]
			if n.lower() in TOUCHPAD_NO_SCREEN_IDS:
				# El panel no explora la pantalla (manual, 20.6): el toque de un
				# dedo solo hace el clic de Windows, salvo que se asigne «tp:tap».
				continue
			if n.lower() in TOUCHPAD_SCROLL_IDS:
				# Deslizar con dos dedos es desplazarse en Windows: no hereda las
				# órdenes de la pantalla (la lectura continua empezaría al
				# desplazarse). Se puede asignar como gesto del panel («tp:»).
				continue
		ids += [f"ts({mode}):{n}", f"ts:{n}"]
	return [normalizeGestureId(i) for i in ids]


#: Gestos de un dedo del panel táctil que no heredan las órdenes de la
#: pantalla (todas exploran lo que hay bajo el dedo).
TOUCHPAD_NO_SCREEN_IDS = frozenset({"tap", "hoverdown", "hover", "hoverup"})
#: Deslizamientos de dos dedos del panel táctil: en Windows desplazan el
#: contenido, así que no heredan las órdenes de la pantalla táctil.
TOUCHPAD_SCROLL_IDS = frozenset({"2finger_flickup", "2finger_flickdown", "2finger_flickleft", "2finger_flickright"})


class TouchGesture:
	"""Gesto táctil compatible con el gestor de entrada (como ``KeyboardGesture``)."""

	isModifier = False
	char: str | None = None
	modifiers: frozenset = frozenset()
	modifierNames: list[str] = []
	mainKeyName = ""
	isNVDAKeyCombination = False

	def __init__(self, event: R.TouchEvent, mode: str = OBJECT_MODE, source: str = "ts") -> None:
		self.event = event
		self.action = event.action
		self.fingers = event.fingers
		self.x = event.x
		self.y = event.y
		self.mode = mode
		self.source = source
		self.edge = event.edge
		self.name = event.edgeName or event.name
		self.identifiers = identifiersFor(event.name, mode, source, event.edgeName)
		#: Para la captura de gestos (diálogo «Gestos de entrada»).
		self.normalizedKeys = self.name.lower()

	@property
	def isHover(self) -> bool:
		return self.event.isHover

	@property
	def displayName(self) -> str:
		return actionLabel(self.name)

	def send(self) -> None:
		"""Los gestos táctiles no se reenvían a la aplicación."""

	def __repr__(self) -> str:
		return f"<TouchGesture {self.source}({self.mode}):{self.name} en {self.x},{self.y}>"
