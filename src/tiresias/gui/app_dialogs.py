"""Diálogos de lista de los módulos de aplicación y de las herramientas de sistema.

:class:`ItemListDialog` es una lista con filtro, tipos de elemento opcionales
y botones de acción. La usan:

- la lista de elementos de Word, Excel y PowerPoint (comentarios, revisiones,
  hojas, diapositivas...);
- la lista de iconos de la bandeja del sistema;
- la lista de ventanas y la de procesos.

Todo se ejecuta en el hilo de la interfaz; las acciones que tocan objetos
accesibles se encolan en el núcleo desde quien crea el diálogo.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

import wx

from . import message_dialog
from ..i18n import _
from ..log import getLogger
from .helpers import addLabel, bringToFront, isAlive, matchesAll, normalizeForSearch, runOnGui, speakMessage

log = getLogger("gui.appDialogs")


@dataclass
class Action:
	"""Botón del diálogo: ``callback(payload)``; ``close`` cierra el diálogo antes."""

	label: str
	callback: Callable[[Any], None]
	close: bool = True
	default: bool = False


def acceleratorOf(label: str) -> str | None:
	"""Letra rápida (``&``) de una etiqueta, en minúscula; ``&&`` es un «&» literal."""
	i = 0
	while i < len(label):
		if label[i] == "&":
			if label[i + 1 : i + 2] == "&":
				i += 2
				continue
			return label[i + 1 : i + 2].lower() or None
		i += 1
	return None


def freeAccelerator(label: str, used: set[str]) -> str:
	"""``label`` con una letra rápida que no esté en ``used`` (y la añade a ``used``).

	Si la suya está ocupada, se pone en la primera letra libre de la etiqueta; si
	no queda ninguna, la etiqueta se queda sin letra rápida.
	"""
	accel = acceleratorOf(label)
	if accel is not None and accel not in used:
		used.add(accel)
		return label
	plain = "&&".join(part.replace("&", "") for part in label.split("&&"))
	i = 0
	while i < len(plain):
		if plain[i] == "&":
			i += 2
			continue
		ch = plain[i]
		if ch.isalnum() and ch.lower() not in used:
			used.add(ch.lower())
			return plain[:i] + "&" + plain[i:]
		i += 1
	return plain


class ItemListDialog(wx.Dialog):
	"""Lista de elementos con filtro y botones de acción.

	``categories`` es una lista de ``(etiqueta, proveedor)``, donde
	``proveedor()`` devuelve ``[(texto, payload), ...]``. Con una sola
	categoría no se muestra la lista de tipos.
	"""

	def __init__(self, title: str, categories: list[tuple[str, Callable[[], list[tuple[str, Any]]]]], actions: list[Action], refreshable: bool = False, emptyMessage: str = "", onRefresh: Callable[[], None] | None = None) -> None:
		super().__init__(None, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._categories = categories
		self._actions = actions
		self._items: list[tuple[str, Any]] = []
		self._shown: list[tuple[str, Any]] = []
		self._emptyMessage = emptyMessage or _("No hay elementos")
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.kind = None
		if len(categories) > 1:
			addLabel(self, sizer, _("&Tipo:"))
			self.kind = wx.Choice(self, choices=[c[0] for c in categories])
			self.kind.SetSelection(0)
			sizer.Add(self.kind, 0, wx.EXPAND | wx.ALL, 6)
			self.kind.Bind(wx.EVT_CHOICE, lambda e: self._loadCategory())
		addLabel(self, sizer, _("&Filtrar:"))
		self.filter = wx.TextCtrl(self)
		sizer.Add(self.filter, 0, wx.EXPAND | wx.ALL, 6)
		addLabel(self, sizer, _("&Elementos:"))
		self.list = wx.ListBox(self, size=(560, 320))
		sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 6)
		buttons = wx.BoxSizer(wx.HORIZONTAL)
		self._buttons: list[wx.Button] = []
		# Letras ya usadas por las etiquetas fijas: las de los botones de los
		# módulos de aplicación («&Explorar» frente a «&Elementos») se mueven a otra.
		used = {"f", "e", "c"} | ({"t"} if self.kind is not None else set()) | ({"u"} if refreshable or onRefresh is not None else set())
		for action in actions:
			btn = wx.Button(self, label=freeAccelerator(action.label, used))
			btn.Bind(wx.EVT_BUTTON, lambda e, a=action: self._run(a))
			buttons.Add(btn, 0, wx.ALL, 4)
			self._buttons.append(btn)
			if action.default:
				btn.SetDefault()
		if refreshable or onRefresh is not None:
			refresh = wx.Button(self, label=_("Act&ualizar"))
			refresh.Bind(wx.EVT_BUTTON, lambda e: onRefresh() if onRefresh is not None else self._loadCategory())
			buttons.Add(refresh, 0, wx.ALL, 4)
		close = wx.Button(self, wx.ID_CANCEL, _("&Cerrar"))
		buttons.Add(close, 0, wx.ALL, 4)
		sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_BUTTON, lambda e: self.Destroy(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, lambda e: self.Destroy())
		self.filter.Bind(wx.EVT_TEXT, lambda e: self._applyFilter())
		self.filter.Bind(wx.EVT_KEY_DOWN, self._onFilterKey)
		self.list.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._runDefault())
		self.list.Bind(wx.EVT_KEY_DOWN, self._onListKey)
		self.CentreOnScreen()
		self._loadCategory()

	# ------------------------------------------------------------ datos
	def _loadCategory(self) -> None:
		idx = self.kind.GetSelection() if self.kind is not None else 0
		provider = self._categories[idx][1] if self._categories else (lambda: [])
		try:
			self._items = list(provider() or [])
		except Exception:
			log.exception("Error obteniendo los elementos")
			self._items = []
		self._applyFilter()

	def setItems(self, items: list[tuple[str, Any]]) -> None:
		"""Sustituye los elementos (para listas que se cargan en segundo plano)."""
		self._items = list(items)
		self._applyFilter()

	def _applyFilter(self) -> None:
		query = self.filter.GetValue()
		if query.strip():
			self._shown = [it for it in self._items if matchesAll(normalizeForSearch(it[0]), query)]
		else:
			self._shown = list(self._items)
		labels = [it[0] for it in self._shown] or [self._emptyMessage]
		self.list.Set(labels)
		self.list.SetSelection(0)
		for b in self._buttons:
			b.Enable(bool(self._shown))

	def selectedPayload(self) -> Any:
		i = self.list.GetSelection()
		if 0 <= i < len(self._shown):
			return self._shown[i][1]
		return None

	# ------------------------------------------------------------ acciones
	def _run(self, action: Action) -> None:
		payload = self.selectedPayload()
		if payload is None:
			return
		if action.close:
			self.Destroy()
		try:
			action.callback(payload)
		except Exception:
			log.exception("Error en la acción %s", action.label)

	def _runDefault(self) -> None:
		for a in self._actions:
			if a.default:
				self._run(a)
				return
		if self._actions:
			self._run(self._actions[0])

	def _onFilterKey(self, evt: wx.KeyEvent) -> None:
		if evt.GetKeyCode() in (wx.WXK_DOWN, wx.WXK_UP) and self._shown:
			self.list.SetFocus()
		elif evt.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
			self._runDefault()
		else:
			evt.Skip()

	def _onListKey(self, evt: wx.KeyEvent) -> None:
		if evt.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
			self._runDefault()
		elif evt.GetKeyCode() == wx.WXK_DELETE:
			for a in self._actions:
				if getattr(a, "isDelete", False):
					self._run(a)
					return
			evt.Skip()
		else:
			evt.Skip()


_openDialogs: dict[str, ItemListDialog] = {}


def showItemList(key: str, title: str, categories: list, actions: list[Action], refreshable: bool = False, emptyMessage: str = "", initialCategory: int = 0, onRefresh: Callable[[], None] | None = None) -> None:
	"""Muestra (o reutiliza) un diálogo de lista. Seguro desde cualquier hilo."""

	def _show() -> None:
		old = _openDialogs.get(key)
		if isAlive(old):
			old.Destroy()
		dlg = ItemListDialog(title, categories, actions, refreshable, emptyMessage, onRefresh)
		if dlg.kind is not None and 0 < initialCategory < len(categories):
			dlg.kind.SetSelection(initialCategory)
			dlg._loadCategory()
		_openDialogs[key] = dlg
		dlg.Show()
		bringToFront(dlg)
		dlg.list.SetFocus()

	runOnGui(_show)


def confirm(message: str, title: str) -> bool:
	"""Pregunta Sí/No (en el hilo de la interfaz). «No» es la opción por defecto."""
	return message_dialog.messageBox(message, title, wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING) == wx.YES


# ================================================================ herramientas de sistema
def showWindowList() -> None:
	"""Lista de ventanas: cambiar a una o cerrarla."""
	from .. import system_tools

	def provider() -> list:
		return [(w.label, w) for w in system_tools.listWindows()]

	def switch(w) -> None:
		if not system_tools.switchToWindow(w.hwnd):
			speakMessage(_("La ventana ya no existe"))

	def close(w) -> None:
		if confirm(_("¿Cerrar la ventana «{title}»?").format(title=w.title), _("Cerrar ventana")):
			if not system_tools.closeWindow(w.hwnd):
				speakMessage(_("La ventana ya no existe"))
			# La ventana cerrada no se queda en la lista (se le da tiempo a cerrarse).
			dlg = _openDialogs.get("windows")
			if isAlive(dlg):
				wx.CallLater(500, lambda: dlg._loadCategory() if isAlive(dlg) else None)

	actions = [Action(_("C&ambiar a la ventana"), switch, default=True), Action(_("Cerrar &ventana..."), close, close=False)]
	showItemList("windows", _("Lista de ventanas"), [(_("Ventanas"), provider)], actions, refreshable=True, emptyMessage=_("No hay ventanas"))


def showProcessList() -> None:
	"""Lista de procesos: cambiar a su ventana o finalizarlo (con confirmación)."""
	from .. import system_tools

	state: dict = {"items": None}

	def provider() -> list:
		return state["items"] or []

	def load(dlg_key: str = "processes") -> None:
		def worker() -> None:
			items = [(p.label, p) for p in system_tools.listProcesses()]

			def deliver() -> None:
				state["items"] = items
				dlg = _openDialogs.get(dlg_key)
				if isAlive(dlg):
					dlg.setItems(items)

			wx.CallAfter(deliver)

		threading.Thread(target=worker, name="tiresias-processes", daemon=True).start()

	def switch(p) -> None:
		if p.hwnd and system_tools.switchToWindow(p.hwnd):
			return
		speakMessage(_("{name} no tiene ventana").format(name=p.name))

	def end(p) -> None:
		ok, why = system_tools.canEndProcess(p)
		if not ok:
			message_dialog.messageBox(why, _("Finalizar proceso"), wx.OK | wx.ICON_INFORMATION)
			return
		msg = _("¿Finalizar el proceso {name} (PID {pid})? Se perderán los datos que no se hayan guardado.").format(name=p.name, pid=p.pid)
		if not confirm(msg, _("Finalizar proceso")):
			return

		def worker() -> None:
			done = system_tools.endProcess(p.pid)
			speakMessage(_("Proceso {name} finalizado").format(name=p.name) if done else _("No se pudo finalizar {name}").format(name=p.name))
			load()

		threading.Thread(target=worker, daemon=True).start()

	endAction = Action(_("&Finalizar proceso..."), end, close=False)
	endAction.isDelete = True  # type: ignore[attr-defined]
	actions = [Action(_("C&ambiar a su ventana"), switch, default=True), endAction]
	showItemList("processes", _("Lista de procesos"), [(_("Procesos"), provider)], actions, emptyMessage=_("Cargando procesos..."), onRefresh=load)
	load()


def showTrayIconList(icons: list) -> None:
	"""Lista de iconos de la bandeja (obtenidos en el núcleo)."""
	from .. import queue_handler, system_tools

	def provider() -> list:
		return [(i.label, i) for i in icons]

	def activate(button: str, double: bool = False) -> Callable:
		def run(icon) -> None:
			def onCore() -> None:
				from .. import speech

				def result(ok: bool) -> None:
					if not ok:
						speech.speakMessage(_("No se encontró el icono {name}").format(name=icon.name))

				system_tools.activateTrayIcon(icon, button, double, callback=result)

			# Se deja tiempo a que el diálogo se cierre y vuelva el foco al escritorio.
			queue_handler.callLater(250, onCore)

		return run

	actions = [
		Action(_("Clic &izquierdo"), activate("left"), default=True),
		Action(_("Clic &derecho"), activate("right")),
		Action(_("&Doble clic"), activate("left", True)),
	]
	showItemList("tray", _("Iconos de la bandeja del sistema"), [(_("Iconos"), provider)], actions, emptyMessage=_("No hay iconos en la bandeja"))
