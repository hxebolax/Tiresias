"""Herramientas comunes para asignar gestos: captura de teclas y conflictos.

- :func:`startCapture`: espera la siguiente combinación de teclas.
- :func:`checkGesture`: dice si una combinación se puede usar (reservada por
  Windows, tecla de uso normal en las aplicaciones o ya usada por otra orden).
- :func:`confirmAssignment`: pregunta al usuario y resuelve el conflicto.
- :class:`ScriptGesturesDialog`: diálogo para configurar las teclas de una
  orden concreta (por ejemplo, la del menú de Tiresias).
"""

from __future__ import annotations

from typing import Any, Callable

import wx

from . import message_dialog
from .. import queue_handler
from ..i18n import _
from ..log import getLogger
from .helpers import addLabel, bringToFront, isAlive, speakMessage

log = getLogger("gestureTools")

#: Combinaciones que Windows se reserva o que no conviene capturar nunca.
RESERVED = {
	"control+alt+delete": _("Windows la reserva para la pantalla de seguridad"),
	"control+alt+numpaddelete": _("Windows la reserva para la pantalla de seguridad"),
	"windows+l": _("Windows la usa para bloquear el equipo"),
	"alt+tab": _("Windows la usa para cambiar de ventana"),
	"alt+shift+tab": _("Windows la usa para cambiar de ventana"),
	"control+alt+tab": _("Windows la usa para cambiar de ventana"),
	"control+shift+escape": _("Windows la usa para abrir el Administrador de tareas"),
	"control+escape": _("Windows la usa para abrir el menú Inicio"),
	"alt+escape": _("Windows la usa para cambiar de ventana"),
	"windows+tab": _("Windows la usa para la vista de tareas"),
	"windows+d": _("Windows la usa para mostrar el escritorio"),
	"windows+e": _("Windows la usa para abrir el Explorador"),
	"windows+r": _("Windows la usa para el cuadro Ejecutar"),
	"windows+i": _("Windows la usa para abrir Configuración"),
	"windows+x": _("Windows la usa para el menú de vínculos rápidos"),
	"windows+a": _("Windows la usa para la configuración rápida"),
	"windows+n": _("Windows la usa para las notificaciones"),
	"windows+b": _("Windows la usa para el área de notificación"),
	"windows+m": _("Windows la usa para minimizar ventanas"),
	"windows+control+enter": _("Windows la usa para activar Narrador"),
	"windows+u": _("Windows la usa para la configuración de accesibilidad"),
	"windows+v": _("Windows la usa para el historial del portapapeles"),
	"windows+h": _("Windows la usa para el dictado"),
	"windows+period": _("Windows la usa para el panel de emojis"),
	"windows+.": _("Windows la usa para el panel de emojis"),
	"alt+f4": _("cierra la ventana activa en todas las aplicaciones"),
	"control+alt+t": _("es la tecla de acceso directo para iniciar Tiresias"),
}

#: Teclas que las aplicaciones usan constantemente.
COMMON = {
	"tab",
	"shift+tab",
	"enter",
	"numpadenter",
	"escape",
	"space",
	"backspace",
	"delete",
	"uparrow",
	"downarrow",
	"leftarrow",
	"rightarrow",
	"home",
	"end",
	"pageup",
	"pagedown",
	"applications",
	"shift+f10",
	"control+c",
	"control+v",
	"control+x",
	"control+z",
	"control+y",
	"control+a",
	"control+s",
	"control+f",
	"control+p",
	"control+n",
	"control+o",
	"control+w",
	"control+tab",
	"control+shift+tab",
	"alt",
	"f1",
	"f2",
	"f3",
	"f4",
	"f5",
	"f6",
	"f10",
}


def _normalizeKeys(keys: str) -> str:
	"""Teclas en el orden de :func:`normalizeGestureId` (tiresias, control,
	shift, alt, windows): así «alt+shift+tab» coincide con «shift+alt+tab»."""
	from ..baseobject import normalizeGestureId

	return normalizeGestureId("kb:" + keys).partition(":")[2]


RESERVED = {_normalizeKeys(k): v for k, v in RESERVED.items()}
COMMON = {_normalizeKeys(k) for k in COMMON}


def splitGesture(gid: str) -> tuple[str | None, str]:
	"""``kb(laptop):tiresias+m`` -> (``laptop``, ``tiresias+m``)."""
	prefix, _sep, keys = gid.partition(":")
	layout = prefix[3:-1] if prefix.startswith("kb(") and prefix.endswith(")") else None
	return layout, keys


def overlap(a: str, b: str) -> bool:
	"""Dos gestos chocan si tienen las mismas teclas en la misma distribución."""
	la, ka = splitGesture(a)
	lb, kb = splitGesture(b)
	if _gestureFamily(a) != _gestureFamily(b):
		# Un gesto táctil o de línea braille no choca con una tecla.
		return False
	if la is None and lb is None:
		# Gestos táctiles: el modo (``ts(object)``) hace de distribución.
		la, lb = _gestureVariant(a), _gestureVariant(b)
	return ka == kb and (la is None or lb is None or la == lb)


def _gestureFamily(gid: str) -> str:
	"""``kb(laptop):x`` -> ``kb``; ``ts(object):tap`` -> ``ts``."""
	return gid.partition(":")[0].split("(", 1)[0].lower()


def _gestureVariant(gid: str) -> str | None:
	prefix = gid.partition(":")[0]
	if "(" in prefix and prefix.endswith(")"):
		return prefix[prefix.index("(") + 1 : -1].lower()
	return None


def _classKey(cls: type) -> str:
	return f"{cls.__module__}.{cls.__qualname__}"


def lookupUser(state: dict, cls: type, gid: str) -> tuple[bool, str | None]:
	for klass in cls.__mro__:
		m = state.get(_classKey(klass))
		if m and gid in m:
			return True, m[gid]
	return False, None


def targetOf(state: dict, info: Any, gid: str) -> str | None:
	found, value = lookupUser(state, info.cls, gid)
	return value if found else info.classGestures.get(gid)


def gesturesFor(state: dict, info: Any) -> list[str]:
	candidates = set(info.classGestures)
	for klass in info.cls.__mro__:
		candidates |= set(state.get(_classKey(klass), {}))
	return [g for g in candidates if targetOf(state, info, g) == info.name]


def checkGesture(scripts: list, state: dict, gid: str, exclude: Any = None) -> dict:
	"""Analiza si ``gid`` se puede usar.

	Devuelve ``{"reserved": motivo|None, "common": bool, "typing": bool,
	"conflicts": [(info, gesto), ...]}``.
	"""
	_layout, keys = splitGesture(gid)
	parts = keys.split("+")
	mods = {p for p in parts if p in ("tiresias", "control", "shift", "alt", "windows")}
	result: dict = {"reserved": RESERVED.get(keys), "common": keys in COMMON, "typing": False, "conflicts": []}
	if not (mods - {"shift"}) and len(parts[-1]) == 1:
		# Una letra, número o signo sin modificadores escribe texto.
		result["typing"] = True
	for info in scripts:
		if exclude is not None and info.classKey == exclude.classKey and info.name == exclude.name:
			continue
		for g in gesturesFor(state, info):
			if overlap(g, gid):
				result["conflicts"].append((info, g))
				break
	return result


def removeGesture(state: dict, info: Any, gid: str) -> None:
	m = state.setdefault(info.classKey, {})
	if m.get(gid) == info.name:
		del m[gid]
	if targetOf(state, info, gid) == info.name:
		m[gid] = None


def confirmAssignment(parent: wx.Window, scripts: list, state: dict, info: Any, gid: str) -> bool:
	"""Comprueba ``gid`` y pregunta al usuario. Si acepta, quita el gesto a
	las órdenes en conflicto (en ``state``). Devuelve ``True`` si se puede asignar."""
	from ..input.keys import labelForGesture

	label = labelForGesture(gid)
	report = checkGesture(scripts, state, gid, exclude=info)
	if report["reserved"]:
		message_dialog.messageBox(
			_("No se puede usar {gesture}: {reason}.").format(gesture=label, reason=report["reserved"]),
			_("Combinación no disponible"),
			wx.OK | wx.ICON_ERROR,
			parent,
		)
		return False
	warnings: list[str] = []
	if report["typing"]:
		warnings.append(_("Esta tecla escribe texto: si la asignas, dejarás de poder escribirla en las aplicaciones."))
	elif report["common"]:
		warnings.append(_("Las aplicaciones usan mucho esta tecla; si la asignas, dejará de llegar a ellas."))
	for other, _g in report["conflicts"]:
		warnings.append(_("Ya la usa la orden «{desc}» ({cat}).").format(desc=other.description, cat=other.category))
	if not warnings:
		return True
	msg = _("Atención con {gesture}:").format(gesture=label) + "\n\n" + "\n".join(warnings)
	if report["conflicts"]:
		msg += "\n\n" + _("¿Quieres asignarla igualmente? Las otras órdenes se quedarán sin esta combinación.")
	else:
		msg += "\n\n" + _("¿Quieres asignarla igualmente?")
	if message_dialog.messageBox(msg, _("Comprobar combinación de teclas"), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, parent) != wx.YES:
		return False
	for other, g in report["conflicts"]:
		removeGesture(state, other, g)
	return True


class _Capture:
	"""Espera la siguiente combinación de teclas (gancho del núcleo)."""

	def __init__(self, onCaptured: Callable[[list[str], str], None]) -> None:
		from ..input import core as inputCore

		self._done = False
		self._onCaptured = onCaptured
		self._inputCore = inputCore

		def capture(gesture: Any) -> bool:
			if self._done:
				return True
			self._done = True
			if inputCore.manager.captureFunc is capture:
				inputCore.manager.captureFunc = None
			wx.CallAfter(self._onCaptured, list(gesture.identifiers), getattr(gesture, "normalizedKeys", ""))
			return True

		self._func = capture
		inputCore.manager.captureFunc = capture

	def cancel(self) -> None:
		self._done = True
		if self._inputCore.manager.captureFunc is self._func:
			self._inputCore.manager.captureFunc = None


def startCapture(onCaptured: Callable[[list[str], str], None]) -> _Capture:
	message = _("Pulsa la combinación de teclas que quieras asignar, o Escape para cancelar.")
	speakMessage(message)
	return _Capture(onCaptured)


def startCaptureWithMessage(message: str, onCaptured: Callable[[list[str], str], None]) -> _Capture:
	"""Como :func:`startCapture`, con otro mensaje (p. ej. buscar una orden por sus teclas)."""
	speakMessage(message)
	return _Capture(onCaptured)


def chooseGestureVariant(parent: wx.Window, identifiers: list[str]) -> str | None:
	"""Pregunta si el gesto vale para todas las distribuciones o solo la actual."""
	from ..input.keys import labelForGesture

	if identifiers and _gestureFamily(identifiers[0]) in ("ts", "tp"):
		return _chooseTouchVariant(parent, identifiers)
	generic = next((g for g in identifiers if g.startswith("kb:")), identifiers[-1])
	specific = next((g for g in identifiers if g.startswith("kb(")), None)
	if not specific:
		return generic
	options = [generic, specific]
	labels = [
		_("{gesture} (todas las distribuciones)").format(gesture=labelForGesture(generic)),
		_("{gesture} (solo esta distribución de teclado)").format(gesture=labelForGesture(specific)),
	]
	dlg = wx.SingleChoiceDialog(parent, _("Elige cómo asignar el gesto:"), _("Añadir gesto"), labels)
	try:
		if dlg.ShowModal() != wx.ID_OK:
			return None
		return options[dlg.GetSelection()]
	finally:
		dlg.Destroy()


def _chooseTouchVariant(parent: wx.Window, identifiers: list[str]) -> str | None:
	"""Gesto táctil: en todos los modos o solo en el modo táctil actual."""
	from ..input.keys import labelForGesture

	options: list[str] = []
	labels: list[str] = []
	for gid in identifiers:
		if _gestureVariant(gid) is None:
			labels.append(_("{gesture} (en todos los modos táctiles)").format(gesture=labelForGesture(gid)))
		else:
			labels.append(_("{gesture} (solo en este modo táctil)").format(gesture=labelForGesture(gid)))
		options.append(gid)
	# Primero lo más habitual: pantalla táctil en todos los modos.
	order = sorted(range(len(options)), key=lambda i: (_gestureFamily(options[i]) != "ts", _gestureVariant(options[i]) is not None))
	options = [options[i] for i in order]
	labels = [labels[i] for i in order]
	if len(options) == 1:
		return options[0]
	dlg = wx.SingleChoiceDialog(parent, _("Elige cómo asignar el gesto táctil:"), _("Añadir gesto"), labels)
	try:
		if dlg.ShowModal() != wx.ID_OK:
			return None
		return options[dlg.GetSelection()]
	finally:
		dlg.Destroy()


# ====================================================================== diálogo
class ScriptGesturesDialog(wx.Dialog):
	"""Configura las combinaciones de teclas de una sola orden."""

	def __init__(self, parent: wx.Window | None, cls: type, scriptName: str, title: str, defaults: list[str]) -> None:
		super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		from ..baseobject import normalizeGestureId
		from ..input import gestures

		self._cls = cls
		self._scriptName = scriptName
		self._defaults = [normalizeGestureId(g) for g in defaults]
		self._state: dict = gestures.userMap.userBindings()
		self._scripts: list = []
		self._info: Any = None
		self._capture: _Capture | None = None
		self._replace: str | None = None
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.status = wx.StaticText(self, label=_("Cargando órdenes..."))
		sizer.Add(self.status, 0, wx.ALL, 6)
		addLabel(self, sizer, _("&Combinaciones asignadas:"))
		self.list = wx.ListBox(self, size=(420, 140))
		sizer.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
		row = wx.BoxSizer(wx.HORIZONTAL)
		self.addBtn = wx.Button(self, label=_("&Añadir..."))
		self.changeBtn = wx.Button(self, label=_("Ca&mbiar..."))
		self.removeBtn = wx.Button(self, label=_("&Quitar"))
		self.resetBtn = wx.Button(self, label=_("&Restablecer"))
		for b in (self.addBtn, self.changeBtn, self.removeBtn, self.resetBtn):
			row.Add(b, 0, wx.ALL, 4)
		sizer.Add(row, 0, wx.ALL, 4)
		btns = wx.StdDialogButtonSizer()
		ok = wx.Button(self, wx.ID_OK, _("Aceptar"))
		cancel = wx.Button(self, wx.ID_CANCEL, _("Cancelar"))
		btns.AddButton(ok)
		btns.AddButton(cancel)
		btns.Realize()
		sizer.Add(btns, 0, wx.ALIGN_RIGHT | wx.ALL, 6)
		self.SetSizerAndFit(sizer)
		ok.SetDefault()
		self.addBtn.Bind(wx.EVT_BUTTON, lambda e: self._startCapture(None))
		self.changeBtn.Bind(wx.EVT_BUTTON, lambda e: self._startCapture(self._selected()))
		self.removeBtn.Bind(wx.EVT_BUTTON, self._onRemove)
		self.resetBtn.Bind(wx.EVT_BUTTON, self._onReset)
		ok.Bind(wx.EVT_BUTTON, self._onOk)
		cancel.Bind(wx.EVT_BUTTON, lambda e: self._close())
		self.Bind(wx.EVT_CLOSE, lambda e: self._close())
		for b in (self.addBtn, self.changeBtn, self.removeBtn, self.resetBtn):
			b.Disable()
		from .config_dialogs import collectScripts

		def collect():
			return collectScripts()

		from .settings import runOnCore

		runOnCore(collect, callback=self._onScripts)

	def _onScripts(self, scripts: list | None) -> None:
		if not isAlive(self):
			return
		self._scripts = scripts or []
		key = _classKey(self._cls)
		self._info = next((s for s in self._scripts if s.classKey == key and s.name == self._scriptName), None)
		if self._info is None:
			self.status.SetLabel(_("No se encontró la orden."))
			return
		self.status.SetLabel(self._info.description)
		for b in (self.addBtn, self.changeBtn, self.removeBtn, self.resetBtn):
			b.Enable()
		self._refresh()
		self.list.SetFocus()

	def _current(self) -> list[str]:
		if self._info is None:
			return []
		return sorted(gesturesFor(self._state, self._info))

	def _refresh(self, select: str | None = None) -> None:
		from ..input.keys import labelForGesture

		gids = self._current()
		self.list.Set([labelForGesture(g) for g in gids] or [_("(sin combinación: la orden no tiene tecla)")])
		self._gids = gids
		if gids:
			self.list.SetSelection(gids.index(select) if select in gids else 0)

	def _selected(self) -> str | None:
		i = self.list.GetSelection()
		gids = getattr(self, "_gids", [])
		return gids[i] if 0 <= i < len(gids) else None

	def _startCapture(self, replace: str | None) -> None:
		if self._info is None:
			return
		self._replace = replace
		self.status.SetLabel(_("Pulsa la nueva combinación (Escape cancela)..."))
		self._capture = startCapture(self._onCaptured)

	def _onCaptured(self, identifiers: list[str], normalizedKeys: str) -> None:
		if not isAlive(self):
			return
		self._capture = None
		self.status.SetLabel(self._info.description if self._info else "")
		if not identifiers or normalizedKeys == "escape":
			speakMessage(_("Cancelado"))
			return
		gid = chooseGestureVariant(self, identifiers)
		if gid is None:
			return
		from ..baseobject import normalizeGestureId

		gid = normalizeGestureId(gid)
		if gid in self._current():
			speakMessage(_("Esa combinación ya está asignada a esta orden"))
			return
		if not confirmAssignment(self, self._scripts, self._state, self._info, gid):
			return
		if self._replace:
			removeGesture(self._state, self._info, self._replace)
		self._state.setdefault(self._info.classKey, {})[gid] = self._info.name
		self._refresh(gid)
		from ..input.keys import labelForGesture

		speakMessage(_("Asignada {gesture}").format(gesture=labelForGesture(gid)))
		self.list.SetFocus()

	def _onRemove(self, evt) -> None:
		gid = self._selected()
		if gid and self._info is not None:
			if len(self._current()) == 1:
				if self._info.name == "showGui":
					# La orden es abrir el menú: no se puede «usar desde el menú».
					warning = _("Si quitas la última combinación, el menú de Tiresias solo se podrá abrir desde su icono del área de notificación o desde la paleta de órdenes. ¿Continuar?")
				else:
					warning = _("Si quitas la última combinación, la orden solo se podrá usar desde el menú o la paleta de órdenes. ¿Continuar?")
				if message_dialog.messageBox(
					warning,
					_("Quitar combinación"),
					wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
					self,
				) != wx.YES:
					return
			removeGesture(self._state, self._info, gid)
			self._refresh()

	def _onReset(self, evt) -> None:
		if self._info is None:
			return
		for g in self._current():
			removeGesture(self._state, self._info, g)
		m = self._state.setdefault(self._info.classKey, {})
		for g in list(m):
			if m[g] is None and g in self._info.classGestures and self._info.classGestures[g] == self._info.name:
				del m[g]
		for g in self._defaults:
			if targetOf(self._state, self._info, g) != self._info.name:
				m[g] = self._info.name
		self._refresh()

	def _onOk(self, evt) -> None:
		from .config_dialogs import _applyGestureMap

		if self._capture is not None:
			self._capture.cancel()
		state = {k: dict(v) for k, v in self._state.items() if v}
		queue_handler.queueFunction(_applyGestureMap, state)
		self._close()

	def _close(self) -> None:
		global _menuKeyDialog
		if self._capture is not None:
			self._capture.cancel()
		_menuKeyDialog = None
		self.Destroy()


_menuKeyDialog: ScriptGesturesDialog | None = None


def showMenuKeyDialog(parent: wx.Window | None = None) -> None:
	"""Configurar la tecla que abre el menú de Tiresias (hilo de la interfaz)."""
	global _menuKeyDialog
	if isAlive(_menuKeyDialog):
		bringToFront(_menuKeyDialog)
		return
	from ..global_commands import GlobalCommands

	_menuKeyDialog = ScriptGesturesDialog(
		parent,
		GlobalCommands,
		"showGui",
		_("Tecla del menú de Tiresias"),
		["kb:tiresias+m", "kb:tiresias+applications"],
	)
	_menuKeyDialog.Show()
	bringToFront(_menuKeyDialog)


def describeMenuKeys(keyboardOnly: bool = False) -> str:
	"""Texto con las teclas actuales del menú (para mostrar en Opciones).

	``keyboardOnly``: solo las del teclado (sin gestos táctiles ni de braille),
	como en el diálogo de bienvenida.
	"""
	from ..global_commands import GlobalCommands
	from ..input import gestures
	from ..input.keys import labelForGesture

	state = gestures.userMap.userBindings()
	classGestures = dict(GlobalCommands.iterClassGestures())

	class _Info:
		cls = GlobalCommands
		name = "showGui"

	info = _Info()
	info.classGestures = classGestures  # type: ignore[attr-defined]
	gids = sorted(gesturesFor(state, info))
	if keyboardOnly:
		gids = [g for g in gids if g.startswith("kb")]
	return ", ".join(labelForGesture(g) for g in gids) or _("ninguna")
