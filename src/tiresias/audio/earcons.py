"""Sonidos de los controles (earcons): un sonido por rol, estado y límite.

Peticiones #4089 (sonido por tipo de control y estado) y #13612 (aviso
sonoro al llegar a un límite). Modos (``earcons.mode``):

- ``off``: desactivado;
- ``withSpeech``: suena el sonido y además se dice el rol o el estado;
- ``insteadOfSpeech``: el sonido sustituye al texto del rol o del estado.

Con ``earcons.positional`` el sonido se panoramiza según la posición
horizontal del objeto en su monitor (audio posicional).

Los sonidos se generan en memoria (tema «default») y pueden sustituirse con
archivos ``.wav`` del mismo nombre en ``data/sounds/<tema>`` (por ejemplo
``role_button.wav``). :func:`tones.exportTheme` crea esos archivos como
punto de partida.

La integración con la presentación es mínima: ``presentation.speakObject`` y
``speakObjectProperties`` abren un contexto (:func:`objectContext`,
:func:`statesContext`) y, dentro de él, ``getObjectSpeech``/``getStatesText``
preguntan con :func:`roleHandled`/:func:`stateHandled` si deben omitir el texto.
"""

from __future__ import annotations

import ctypes
from contextlib import contextmanager
from ctypes import wintypes
from typing import Any, Iterator

from ..config import conf
from ..i18n import _
from ..log import getLogger
from ..objects.roles import Role, State
from . import tones

log = getLogger("earcons")

MODES = {
	"off": _("Sonidos de los controles desactivados"),
	"withSpeech": _("Sonidos de los controles y voz"),
	"insteadOfSpeech": _("Sonidos de los controles en lugar del rol y el estado"),
}
ORDER = list(MODES)

# Notas: (hz, ms, timbre). Do5 = 523,25 Hz.
_ROLE_RECIPES: dict[str, tuple[str, list]] = {
	"role_button": (_("Botón"), [(880, 35, "pluck")]),
	"role_toggleButton": (_("Botón de alternancia"), [(880, 30, "pluck"), (1175, 30, "pluck")]),
	"role_menuButton": (_("Botón de menú"), [(880, 30, "pluck"), (660, 40, "pluck")]),
	"role_link": (_("Enlace"), [(1500, 22, "pure"), (2000, 28, "pure")]),
	"role_checkBox": (_("Casilla de verificación"), [(700, 35, "square")]),
	"role_radioButton": (_("Botón de opción"), [(900, 40, "bell")]),
	"role_edit": (_("Campo de edición"), [(500, 35, "soft"), (620, 35, "soft")]),
	"role_passwordEdit": (_("Campo de contraseña"), [(620, 35, "soft"), (500, 35, "soft")]),
	"role_comboBox": (_("Cuadro combinado"), [(600, 28, "pluck"), (800, 28, "pluck"), (600, 28, "pluck")]),
	"role_list": (_("Lista"), [(400, 45, "bell")]),
	"role_listItem": (_("Elemento de lista"), [(1300, 22, "pure")]),
	"role_treeView": (_("Vista de árbol"), [(350, 45, "bell")]),
	"role_treeViewItem": (_("Elemento de árbol"), [(1100, 22, "pure"), (900, 22, "pure")]),
	"role_tab": (_("Pestaña"), [(1000, 28, "square"), (1300, 28, "square")]),
	"role_menu": (_("Menú"), [(800, 30, "bell"), (1000, 40, "bell")]),
	"role_menuItem": (_("Elemento de menú"), [(1600, 22, "pluck")]),
	"role_slider": (_("Control deslizante"), [(500, 25, "pure"), (700, 25, "pure"), (900, 25, "pure")]),
	"role_spinButton": (_("Botón de número"), [(700, 25, "soft"), (900, 25, "soft")]),
	"role_progressBar": (_("Barra de progreso"), [(300, 45, "square")]),
	"role_heading": (_("Encabezado"), [(523.25, 60, "pluck")]),
	"role_heading1": (_("Encabezado de nivel 1"), [(523.25, 60, "pluck")]),
	"role_heading2": (_("Encabezado de nivel 2"), [(587.33, 60, "pluck")]),
	"role_heading3": (_("Encabezado de nivel 3"), [(659.25, 60, "pluck")]),
	"role_heading4": (_("Encabezado de nivel 4"), [(698.46, 60, "pluck")]),
	"role_heading5": (_("Encabezado de nivel 5"), [(783.99, 60, "pluck")]),
	"role_heading6": (_("Encabezado de nivel 6"), [(880.0, 60, "pluck")]),
	"role_table": (_("Tabla"), [(330, 50, "bell")]),
	"role_graphic": (_("Gráfico"), [(1800, 25, "bell"), (1400, 35, "bell")]),
	"role_dialog": (_("Diálogo"), [(392, 60, "bell"), (523.25, 80, "bell")]),
	"role_landmark": (_("Punto de referencia"), [(220, 45, "pluck")]),
	"role_document": (_("Documento"), [(262, 60, "soft")]),
	"role_switch": (_("Interruptor"), [(1175, 30, "pluck"), (880, 30, "pluck")]),
}

_STATE_RECIPES: dict[str, tuple[str, list]] = {
	"state_checked": (_("Marcado"), [(880, 25, "pure"), (1320, 35, "pure")]),
	"state_notChecked": (_("No marcado"), [(1320, 25, "pure"), (880, 35, "pure")]),
	"state_halfChecked": (_("Parcialmente marcado"), [(1100, 45, "pure")]),
	"state_expanded": (_("Expandido"), [(600, 30, "bell"), (900, 40, "bell")]),
	"state_collapsed": (_("Contraído"), [(900, 30, "bell"), (600, 40, "bell")]),
	"state_unavailable": (_("No disponible"), [(200, 50, "square")]),
	"state_visited": (_("Visitado"), [(1700, 22, "pure")]),
	"state_required": (_("Obligatorio"), [(1000, 20, "square"), (0, 15), (1000, 20, "square")]),
	"state_invalidEntry": (_("Entrada no válida"), [(150, 60, "square")]),
	"state_busy": (_("Ocupado"), [(400, 30, "soft"), (0, 20), (400, 30, "soft")]),
	"state_hasPopup": (_("Abre un menú"), [(1200, 22, "pluck")]),
}

ROLE_SOUNDS: dict[Role, str] = {
	Role.BUTTON: "role_button",
	Role.TOGGLEBUTTON: "role_toggleButton",
	Role.MENUBUTTON: "role_menuButton",
	Role.SPLITBUTTON: "role_menuButton",
	Role.DROPDOWNBUTTON: "role_menuButton",
	Role.LINK: "role_link",
	Role.CHECKBOX: "role_checkBox",
	Role.RADIOBUTTON: "role_radioButton",
	Role.EDITABLETEXT: "role_edit",
	Role.PASSWORDEDIT: "role_passwordEdit",
	Role.COMBOBOX: "role_comboBox",
	Role.LIST: "role_list",
	Role.LISTITEM: "role_listItem",
	Role.DATAITEM: "role_listItem",
	Role.TREEVIEW: "role_treeView",
	Role.TREEVIEWITEM: "role_treeViewItem",
	Role.TAB: "role_tab",
	Role.MENUBAR: "role_menu",
	Role.POPUPMENU: "role_menu",
	Role.MENU: "role_menu",
	Role.MENUITEM: "role_menuItem",
	Role.CHECKMENUITEM: "role_menuItem",
	Role.RADIOMENUITEM: "role_menuItem",
	Role.SLIDER: "role_slider",
	Role.SPINBUTTON: "role_spinButton",
	Role.PROGRESSBAR: "role_progressBar",
	Role.HEADING: "role_heading",
	Role.HEADING1: "role_heading1",
	Role.HEADING2: "role_heading2",
	Role.HEADING3: "role_heading3",
	Role.HEADING4: "role_heading4",
	Role.HEADING5: "role_heading5",
	Role.HEADING6: "role_heading6",
	Role.TABLE: "role_table",
	Role.DATAGRID: "role_table",
	Role.GRAPHIC: "role_graphic",
	Role.DIALOG: "role_dialog",
	Role.LANDMARK: "role_landmark",
	Role.REGION: "role_landmark",
	Role.DOCUMENT: "role_document",
	Role.SWITCH: "role_switch",
}

STATE_SOUNDS: dict[State, str] = {
	State.CHECKED: "state_checked",
	State.PRESSED: "state_checked",
	State.ON: "state_checked",
	State.HALFCHECKED: "state_halfChecked",
	State.EXPANDED: "state_expanded",
	State.COLLAPSED: "state_collapsed",
	State.UNAVAILABLE: "state_unavailable",
	State.VISITED: "state_visited",
	State.REQUIRED: "state_required",
	State.INVALID_ENTRY: "state_invalidEntry",
	State.BUSY: "state_busy",
	State.HASPOPUP: "state_hasPopup",
}

#: Estados cuyo valor negativo («no marcado») tiene sonido propio.
NEGATIVE_STATE_SOUNDS: dict[State, str] = {
	State.CHECKED: "state_notChecked",
	State.PRESSED: "state_notChecked",
	State.ON: "state_notChecked",
}

_CHECKABLE_ROLES = {Role.CHECKBOX, Role.CHECKMENUITEM}


def registerSounds() -> None:
	"""Añade los sonidos de roles y estados al catálogo de :mod:`tones`."""
	for name, (desc, notes) in {**_ROLE_RECIPES, **_STATE_RECIPES}.items():
		tones.registerSound(name, notes, desc)


registerSounds()


# ---------------------------------------------------------------- opciones
def mode() -> str:
	try:
		m = conf["earcons"]["mode"]
	except KeyError:
		return "off"
	return m if m in MODES else "off"


def isActive() -> bool:
	try:
		return mode() != "off" and bool(conf["audio"]["playSounds"])
	except KeyError:
		return False


def cycleMode() -> str:
	cur = mode()
	nxt = ORDER[(ORDER.index(cur) + 1) % len(ORDER)]
	conf["earcons"]["mode"] = nxt
	return MODES[nxt]


# ---------------------------------------------------------------- posición
class _RECT(ctypes.Structure):
	_fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class _MONITORINFO(ctypes.Structure):
	_fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _RECT), ("rcWork", _RECT), ("dwFlags", wintypes.DWORD)]


_user32 = ctypes.WinDLL("user32")
_user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
_user32.MonitorFromPoint.restype = wintypes.HMONITOR
_user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
MONITOR_DEFAULTTONEAREST = 2


def monitorRect(x: int, y: int) -> tuple[int, int, int, int]:
	"""(izquierda, arriba, derecha, abajo) del monitor que contiene el punto."""
	mon = _user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), MONITOR_DEFAULTTONEAREST)
	info = _MONITORINFO()
	info.cbSize = ctypes.sizeof(info)
	if mon and _user32.GetMonitorInfoW(mon, ctypes.byref(info)):
		r = info.rcMonitor
		return r.left, r.top, r.right, r.bottom
	return 0, 0, _user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1)


def panForRect(location: tuple[int, int, int, int] | None, monitor: tuple[int, int, int, int] | None = None) -> float | None:
	"""Paneo entre -1 y 1 según el centro horizontal de ``location`` en su monitor."""
	if not location:
		return None
	left, top, width, height = location
	if width <= 0 and height <= 0:
		return None
	cx = left + width / 2.0
	cy = top + height / 2.0
	mLeft, _mTop, mRight, _mBottom = monitor or monitorRect(int(cx), int(cy))
	span = mRight - mLeft
	if span <= 0:
		return None
	return max(-1.0, min(1.0, (cx - mLeft) / span * 2.0 - 1.0))


def panFor(obj: Any) -> float | None:
	if not conf["earcons"]["positional"]:
		return None
	try:
		return panForRect(obj.location)
	except Exception:
		return None


# ---------------------------------------------------------------- reproducción y contexto
def roleSound(obj: Any, role: Role) -> str | None:
	if role == Role.HEADING:
		level = getattr(obj, "level", None)
		if isinstance(level, int) and 1 <= level <= 6:
			return f"role_heading{level}"
	return ROLE_SOUNDS.get(role)


class _Context:
	def __init__(self) -> None:
		self.roles: set[Role] = set()
		self.states: set[State] = set()
		self.negative: set[State] = set()


_stack: list[_Context] = []

#: Motivos (``presentation.Reason.value``) en los que suenan rol y estados.
_OBJECT_REASONS = {"focus", "query", "mouse"}


def _play(names: list[str], pan: float | None) -> None:
	for name in names:
		tones.playSound(name, pan=pan)


def soundsForObject(obj: Any, role: Role, states: set[State], reason: str) -> tuple[list[str], _Context]:
	"""Sonidos que corresponden a un objeto y lo que cubren (sin reproducir)."""
	ctx = _Context()
	names: list[str] = []
	if reason not in _OBJECT_REASONS:
		return names, ctx
	if conf["earcons"]["roles"]:
		try:
			custom = obj.roleText
		except Exception:
			custom = None
		name = None if custom else roleSound(obj, role)
		if name:
			names.append(name)
			ctx.roles.add(role)
	if conf["earcons"]["states"]:
		for st in sorted(states):
			name = STATE_SOUNDS.get(st)
			if not name or (st == State.PRESSED and role != Role.TOGGLEBUTTON) or (st == State.ON and role != Role.SWITCH):
				continue
			if name not in names:
				names.append(name)
			ctx.states.add(st)
		if role in _CHECKABLE_ROLES and State.CHECKED not in states and State.HALFCHECKED not in states:
			names.append(NEGATIVE_STATE_SOUNDS[State.CHECKED])
			ctx.negative.add(State.CHECKED)
		elif role == Role.SWITCH and State.ON not in states:
			names.append(NEGATIVE_STATE_SOUNDS[State.ON])
			ctx.negative.add(State.ON)
		elif role == Role.TOGGLEBUTTON and State.PRESSED not in states and reason == "query":
			names.append(NEGATIVE_STATE_SOUNDS[State.PRESSED])
			ctx.negative.add(State.PRESSED)
	return names, ctx


@contextmanager
def objectContext(obj: Any, reason: Any) -> Iterator[None]:
	"""Reproduce los sonidos de un objeto y, dentro del bloque, informa de qué omitir."""
	ctx = _Context()
	if isActive():
		try:
			reasonValue = getattr(reason, "value", str(reason))
			names, ctx = soundsForObject(obj, obj.role, set(obj.states), reasonValue)
			_play(names, panFor(obj))
		except Exception:
			log.debug("Error con los sonidos del objeto", exc_info=True)
			ctx = _Context()
	_stack.append(ctx)
	try:
		yield
	finally:
		_stack.pop()


@contextmanager
def statesContext(obj: Any, added: set[State], removed: set[State]) -> Iterator[None]:
	"""Cambios de estado: suenan los estados añadidos y los negativos quitados."""
	ctx = _Context()
	if isActive() and conf["earcons"]["states"]:
		try:
			role = obj.role
			names: list[str] = []
			for st in sorted(added):
				name = STATE_SOUNDS.get(st)
				if name:
					names.append(name)
					ctx.states.add(st)
			for st in sorted(removed):
				name = NEGATIVE_STATE_SOUNDS.get(st)
				if name and st not in added:
					if st == State.ON and role != Role.SWITCH:
						continue
					names.append(name)
					ctx.negative.add(st)
			_play(names, panFor(obj))
		except Exception:
			log.debug("Error con los sonidos de estado", exc_info=True)
			ctx = _Context()
	_stack.append(ctx)
	try:
		yield
	finally:
		_stack.pop()


def _suppress() -> bool:
	return bool(_stack) and mode() == "insteadOfSpeech"


def roleHandled(role: Role) -> bool:
	"""``True`` si el texto del rol debe omitirse porque ya sonó su sonido."""
	return _suppress() and role in _stack[-1].roles


def stateHandled(state: State, negative: bool = False) -> bool:
	"""``True`` si el texto del estado (o de su negativo) debe omitirse."""
	if not _suppress():
		return False
	ctx = _stack[-1]
	return state in (ctx.negative if negative else ctx.states)


def soundDescriptions() -> list[tuple[str, str]]:
	"""[(nombre del sonido, descripción)] de los sonidos de roles y estados."""
	return [(n, d) for n, (d, _notes) in {**_ROLE_RECIPES, **_STATE_RECIPES}.items()]


def preview(name: str) -> None:
	tones.playSound(name)
