"""Paleta de órdenes: buscar cualquier orden por su nombre y ejecutarla.

:func:`collectEntries` se llama en el hilo del núcleo (recorre la cadena de
resolución de gestos). :func:`showCommandPalette` muestra el diálogo en el
hilo de la interfaz.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

import wx

from .. import queue_handler
from ..i18n import _
from ..log import getLogger
from .helpers import addLabel, bringToFront, fuzzyScore, isAlive, normalizeForSearch, runOnGui

log = getLogger("gui.commandPalette")

#: Espera antes de ejecutar la orden, para que el foco vuelva a la aplicación.
RUN_DELAY_MS = 200
#: Órdenes que no tiene sentido ofrecer en la paleta.
EXCLUDED_SCRIPTS = {"commandPalette"}


class DummyGesture:
	"""Gesto ficticio para ejecutar órdenes sin pulsar teclas."""

	identifiers: list[str] = []
	modifierNames: list[str] = []
	modifiers: frozenset = frozenset()
	mainKeyName = ""
	normalizedKeys = ""
	char: str | None = None
	displayName = ""
	isModifier = False
	isCharacter = False
	isNVDAKeyCombination = False
	vk = 0
	scanCode = 0
	extended = False

	def __init__(self) -> None:
		self.identifiers = []
		self.modifierNames = []

	def send(self) -> None:
		pass


@dataclass
class PaletteEntry:
	"""Una orden disponible en la paleta."""

	category: str
	description: str
	gestures: list[str]
	scriptName: str
	obj: Any = field(repr=False)
	searchText: str = field(default="", repr=False)
	#: Identificadores normalizados de los gestos (para buscar pulsando teclas).
	gestureIds: list[str] = field(default_factory=list, repr=False)
	descriptionText: str = field(default="", repr=False)

	def __post_init__(self) -> None:
		self.searchText = normalizeForSearch(" ".join([self.description, self.category, *self.gestures, self.scriptName]))
		self.descriptionText = normalizeForSearch(self.description)

	def score(self, query: str) -> float:
		"""Puntuación de búsqueda difusa (la descripción pesa más que el resto)."""
		s = fuzzyScore(self.descriptionText, query)
		if s > 0:
			return s * 2
		return fuzzyScore(self.searchText, query)

	def hasGesture(self, identifiers: list[str]) -> bool:
		from ..baseobject import normalizeGestureId

		wanted = {normalizeGestureId(g) for g in identifiers}
		return any(g in wanted for g in self.gestureIds)

	@property
	def label(self) -> str:
		text = f"{self.description} — {self.category}"
		if self.gestures:
			text += f" ({', '.join(self.gestures)})"
		return text

	def run(self) -> None:
		"""Ejecuta la orden (en el hilo del núcleo)."""
		func = getattr(self.obj, "script_" + self.scriptName, None)
		if func is None:
			log.warning("La orden %s ya no existe", self.scriptName)
			return
		gesture = DummyGesture()
		from ..input import core as inputCore

		execute = getattr(inputCore.manager, "_executeScript", None)
		if execute is not None:
			execute(func, gesture)
		else:
			func(gesture)


# ------------------------------------------------------------------ gestos
def _currentLayout() -> str:
	try:
		from ..config import conf

		return conf["keyboard"]["layout"]
	except Exception:
		return "desktop"


def _gestureApplies(gestureId: str, layout: str) -> bool:
	prefix = gestureId.split(":", 1)[0]
	if prefix.startswith("kb(") and prefix != f"kb({layout})":
		return False
	return True


def getScriptGestures(obj: Any) -> dict[str, list[str]]:
	"""Asocia cada nombre de orden de ``obj`` con sus gestos efectivos.

	Tiene en cuenta los gestos de clase, los de la instancia y los cambios
	del usuario (``gestures.json``). Solo se incluyen los gestos de la
	distribución de teclado actual.
	"""
	from ..input import gestures as gestureMap

	layout = _currentLayout()
	cls = type(obj)
	result: dict[str, list[str]] = {}
	userMap = gestureMap.userMap
	inst = obj.__dict__.get("_instanceGestures") or {} if hasattr(obj, "__dict__") else {}

	def add(gid: str, name: str | None) -> None:
		if name and _gestureApplies(gid, layout):
			lst = result.setdefault(name, [])
			if gid not in lst:
				lst.append(gid)

	iterGestures = getattr(cls, "iterClassGestures", None)
	if iterGestures is not None:
		for gid, name in iterGestures():
			if gid in inst:
				continue
			mapped = userMap.lookup(cls, gid)
			if mapped is gestureMap.UNBOUND or (isinstance(mapped, str) and mapped != name):
				continue
			add(gid, name)
	for gid, name in inst.items():
		add(gid, name)
	bindings = userMap.userBindings()
	for klass in reversed(cls.__mro__):
		for gid, name in (bindings.get(userMap.classKey(klass)) or {}).items():
			if name and userMap.lookup(cls, gid) == name:
				add(gid, name)
	return result


def gestureLabels(gestureIds: list[str]) -> list[str]:
	from ..input import keys

	return [keys.labelForGesture(g) for g in gestureIds]


def iterScripts(obj: Any) -> Iterator[tuple[str, Callable]]:
	"""(nombre, método) de las órdenes de ``obj``.

	Van primero las de la clase más concreta y, dentro de cada clase, en
	orden de definición.
	"""
	seen: set[str] = set()
	for klass in type(obj).__mro__:
		for attr in list(vars(klass)):
			if not attr.startswith("script_") or attr in seen:
				continue
			seen.add(attr)
			try:
				func = getattr(obj, attr)
			except Exception:
				continue
			if callable(func):
				yield attr[7:], func


def _categoryFor(obj: Any, func: Callable) -> str:
	cat = getattr(func, "category", None) or getattr(obj, "scriptCategory", None)
	if cat:
		return cat
	modName = type(obj).__module__
	if ".appmodules" in modName or "appModule" in type(obj).__name__:
		return _("Aplicación actual")
	if ".plugins" in modName or ".addons" in modName:
		return _("Complementos")
	return _("Varios")


# ------------------------------------------------------------------ recogida
def collectEntries() -> list[PaletteEntry]:
	"""Reúne las órdenes disponibles ahora mismo (llamar en el hilo del núcleo)."""
	from ..global_commands import commands as globalCommands
	from ..input import core as inputCore

	sources: list[tuple[Any, Callable[[Callable], bool] | None]] = []
	for item in list(inputCore.manager.chain):
		if isinstance(item, inputCore._PropagatingOnly):
			sources.append((item.obj, lambda f: bool(getattr(f, "canPropagate", False))))
		elif isinstance(item, inputCore._SleepModeFilter):
			sources.append((item.obj, lambda f: bool(getattr(f, "allowInSleepMode", False))))
		else:
			sources.append((item, None))
	if not any(obj is globalCommands for obj, _f in sources):
		sources.append((globalCommands, None))
	entries: list[PaletteEntry] = []
	seen: set[tuple[str, str]] = set()
	for obj, predicate in sources:
		try:
			gestures = getScriptGestures(obj)
			for name, func in iterScripts(obj):
				if name in EXCLUDED_SCRIPTS:
					continue
				desc = " ".join((getattr(func, "__doc__", None) or "").split())
				if not desc:
					continue
				if predicate is not None and not predicate(func):
					continue
				key = (name, desc)
				if key in seen:
					continue
				seen.add(key)
				ids = gestures.get(name, [])
				entries.append(PaletteEntry(_categoryFor(obj, func), desc, gestureLabels(ids), name, obj, gestureIds=list(ids)))
		except Exception:
			log.exception("Error reuniendo las órdenes de %r", obj)
	entries.sort(key=lambda e: (normalizeForSearch(e.category), normalizeForSearch(e.description)))
	return entries


def filterEntries(entries: list[PaletteEntry], query: str, keyFilter: list[str] | None = None) -> list[PaletteEntry]:
	"""Entradas que encajan con ``query`` (búsqueda difusa), de mejor a peor.

	Con ``keyFilter`` (identificadores de un gesto) solo quedan las órdenes
	asignadas a esa combinación de teclas.
	"""
	items = entries
	if keyFilter:
		items = [e for e in items if e.hasGesture(keyFilter)]
	query = query.strip()
	if not query:
		return list(items)
	scored = [(e.score(query), i, e) for i, e in enumerate(items)]
	scored = [t for t in scored if t[0] > 0]
	scored.sort(key=lambda t: (-t[0], t[1]))
	return [e for _s, _i, e in scored]


# ------------------------------------------------------------------ diálogo
class CommandPaletteDialog(wx.Dialog):
	def __init__(self, entries: list[PaletteEntry]) -> None:
		super().__init__(None, title=_("Paleta de órdenes"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.entries = entries
		self.visible: list[PaletteEntry] = []
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, _("&Buscar orden:"))
		self.search = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
		self.search.Bind(wx.EVT_TEXT, lambda evt: self._onSearchText())
		self.search.Bind(wx.EVT_TEXT_ENTER, lambda evt: self.execute())
		self.search.Bind(wx.EVT_KEY_DOWN, self.onSearchKey)
		sizer.Add(self.search, 0, wx.EXPAND | wx.ALL, 6)
		addLabel(self, sizer, _("Ó&rdenes:"))
		self.list = wx.ListBox(self, size=(640, 360), style=wx.LB_SINGLE)
		self.list.Bind(wx.EVT_LISTBOX_DCLICK, lambda evt: self.execute())
		sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 6)
		buttons = wx.BoxSizer(wx.HORIZONTAL)
		run = wx.Button(self, label=_("&Ejecutar"))
		run.SetDefault()
		run.Bind(wx.EVT_BUTTON, lambda evt: self.execute())
		self.byKeysButton = wx.Button(self, label=_("Buscar pulsando las &teclas..."))
		self.byKeysButton.Bind(wx.EVT_BUTTON, lambda evt: self.startKeySearch())
		cancel = wx.Button(self, wx.ID_CANCEL, _("Cancelar"))
		buttons.Add(run, 0, wx.ALL, 4)
		buttons.Add(self.byKeysButton, 0, wx.ALL, 4)
		buttons.Add(cancel, 0, wx.ALL, 4)
		sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.Close(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, self.onClose)
		self._capture = None
		#: Gesto buscado con «Buscar pulsando las teclas» (identificadores).
		self._keyFilter: list[str] | None = None
		self.CentreOnScreen()
		self.refilter()
		self.search.SetFocus()

	def _onSearchText(self) -> None:
		# Escribir de nuevo deja de filtrar por las teclas buscadas.
		self._keyFilter = None
		self.refilter()

	def refilter(self) -> None:
		query = self.search.GetValue().strip()
		self.visible = filterEntries(self.entries, query, self._keyFilter)
		self.list.Set([e.label for e in self.visible])
		if self.visible:
			self.list.SetSelection(0)

	# --------------------------------------------------- buscar por teclas (#7074)
	def startKeySearch(self) -> None:
		from . import gesture_tools

		if self._capture is not None:
			self._capture.cancel()
		self._capture = gesture_tools.startCaptureWithMessage(
			_("Pulsa la combinación de teclas cuya orden quieres buscar, o Escape para cancelar."),
			self._onKeysCaptured,
		)

	def _onKeysCaptured(self, identifiers: list[str], keysText: str) -> None:
		self._capture = None
		if not isAlive(self):
			return
		from ..input.keys import labelForGesture

		if not identifiers or keysText.lower() == "escape":
			self._keyFilter = None
			self.refilter()
			self.byKeysButton.SetFocus()
			return
		self._keyFilter = list(identifiers)
		self.search.ChangeValue("")
		self.refilter()
		label = labelForGesture(identifiers[-1])
		from .helpers import speakMessage

		if self.visible:
			speakMessage(_("{gesture}: {n} órdenes").format(gesture=label, n=len(self.visible)) if len(self.visible) != 1 else _("{gesture}: {desc}").format(gesture=label, desc=self.visible[0].description))
			self.list.SetFocus()
		else:
			speakMessage(_("{gesture} no tiene ninguna orden asignada").format(gesture=label))
			self._keyFilter = None
			self.refilter()
			self.byKeysButton.SetFocus()

	def onSearchKey(self, evt: wx.KeyEvent) -> None:
		if evt.GetKeyCode() in (wx.WXK_DOWN, wx.WXK_NUMPAD_DOWN) and not evt.HasAnyModifiers() and self.visible:
			self.list.SetFocus()
			if self.list.GetSelection() == wx.NOT_FOUND:
				self.list.SetSelection(0)
			return
		evt.Skip()

	def execute(self) -> None:
		sel = self.list.GetSelection()
		if sel == wx.NOT_FOUND or not (0 <= sel < len(self.visible)):
			wx.Bell()
			return
		entry = self.visible[sel]
		self.Close()
		queue_handler.callLater(RUN_DELAY_MS, entry.run)

	def onClose(self, evt: wx.CloseEvent) -> None:
		global _dialog
		if self._capture is not None:
			self._capture.cancel()
			self._capture = None
		_dialog = None
		self.Destroy()


_dialog: CommandPaletteDialog | None = None


def showCommandPalette(entries: list[PaletteEntry]) -> None:
	"""Muestra la paleta con ``entries`` (seguro desde cualquier hilo)."""
	entries = list(entries)

	def _show() -> None:
		global _dialog
		if isAlive(_dialog):
			_dialog.Destroy()
		_dialog = CommandPaletteDialog(entries)
		_dialog.Show()
		bringToFront(_dialog)
		_dialog.search.SetFocus()

	runOnGui(_show)
