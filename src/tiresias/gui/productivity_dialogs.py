"""Diálogos y paneles de opciones de las funciones de productividad.

- Historial de notificaciones (con búsqueda y filtro por aplicación).
- Reglas de notificaciones y su editor.
- Lista de vigilancias.
- Lista de marcadores de texto del documento actual.
- Paneles «Productividad» y «Programas externos» del diálogo de opciones.

Todo se ejecuta en el hilo de la interfaz; lo que toca objetos accesibles se
encola en el núcleo.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable

import wx

from . import message_dialog
from .. import queue_handler
from ..config import conf
from ..i18n import _
from ..log import getLogger
from .helpers import addLabel, bringToFront, isAlive, matchesAll, normalizeForSearch, runOnGui, speakMessage

log = getLogger("gui.productivity")


def _pkg():
	from .. import productivity

	return productivity


def _clock(ts: float) -> str:
	if time.localtime(ts)[:3] == time.localtime()[:3]:
		return time.strftime("%H:%M:%S", time.localtime(ts))
	return time.strftime("%d/%m %H:%M", time.localtime(ts))


def _preview(text: str, n: int = 160) -> str:
	line = " ".join(text.split())
	return line if len(line) <= n else line[:n] + "…"


def _onCore(func: Callable, *args: Any, callback: Callable[[Any], None] | None = None) -> None:
	"""Ejecuta ``func`` en el núcleo y entrega el resultado a ``callback`` en la interfaz."""

	def job() -> None:
		try:
			res = func(*args)
		except Exception:
			log.exception("Error en el núcleo")
			res = None
		if callback is not None:
			wx.CallAfter(callback, res)

	queue_handler.queueFunction(job)


# ====================================================================== historial
class NotificationHistoryDialog(wx.Dialog):
	def __init__(self) -> None:
		super().__init__(None, title=_("Historial de notificaciones"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
		self.items: list = []
		self.visible: list = []
		self._apps: list[str] = []
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, _("&Buscar:"))
		self.search = wx.TextCtrl(self)
		self.search.Bind(wx.EVT_TEXT, lambda evt: self.refilter())
		self.search.Bind(wx.EVT_KEY_DOWN, self.onSearchKey)
		sizer.Add(self.search, 0, wx.EXPAND | wx.ALL, 6)
		addLabel(self, sizer, _("&Aplicación:"))
		self.appCtrl = wx.Choice(self, choices=[_("Todas")])
		self.appCtrl.SetSelection(0)
		self.appCtrl.Bind(wx.EVT_CHOICE, lambda evt: self.refilter())
		sizer.Add(self.appCtrl, 0, wx.ALL, 6)
		addLabel(self, sizer, _("&Notificaciones (la más reciente primero):"))
		self.list = wx.ListBox(self, size=(640, 260), style=wx.LB_SINGLE)
		self.list.Bind(wx.EVT_LISTBOX, lambda evt: self.showSelected())
		sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 6)
		addLabel(self, sizer, _("&Detalles:"))
		self.full = wx.TextCtrl(self, size=(640, 110), style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
		sizer.Add(self.full, 0, wx.EXPAND | wx.ALL, 6)
		buttons = wx.BoxSizer(wx.HORIZONTAL)
		self.copyButton = wx.Button(self, label=_("&Copiar"))
		self.copyButton.Bind(wx.EVT_BUTTON, lambda evt: self.copySelected())
		self.copyButton.SetDefault()
		self.ruleButton = wx.Button(self, label=_("Crear &regla con esta..."))
		self.ruleButton.Bind(wx.EVT_BUTTON, lambda evt: self.ruleFromSelected())
		rules = wx.Button(self, label=_("R&eglas..."))
		rules.Bind(wx.EVT_BUTTON, lambda evt: showNotificationRules(self))
		self.deleteButton = wx.Button(self, label=_("&Quitar"))
		self.deleteButton.Bind(wx.EVT_BUTTON, lambda evt: self.deleteSelected())
		clear = wx.Button(self, label=_("Borrar &todo"))
		clear.Bind(wx.EVT_BUTTON, lambda evt: self.clear())
		close = wx.Button(self, wx.ID_CANCEL, _("Cerrar"))
		for b in (self.copyButton, self.ruleButton, rules, self.deleteButton, clear, close):
			buttons.Add(b, 0, wx.ALL, 4)
		sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.Close(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, self.onClose)
		self.CentreOnScreen()
		self.reload()
		self.list.SetFocus()

	def reload(self) -> None:
		store = _pkg().notificationStore
		self.items = list(reversed(store.entries())) if store is not None else []
		apps = sorted({e.app for e in self.items if e.app})
		if apps != self._apps:
			cur = self._selectedApp()
			self._apps = apps
			self.appCtrl.Set([_("Todas")] + apps)
			self.appCtrl.SetSelection(apps.index(cur) + 1 if cur in apps else 0)
		self.refilter()

	def _selectedApp(self) -> str:
		i = self.appCtrl.GetSelection()
		return self._apps[i - 1] if 0 < i <= len(self._apps) else ""

	def refilter(self) -> None:
		query = self.search.GetValue().strip()
		app = self._selectedApp()
		self.visible = [e for e in self.items if (not app or e.app == app) and (not query or matchesAll(normalizeForSearch(f"{e.text} {e.app}"), query))]
		self.list.Set([f"{_clock(e.time)} {e.app or '?'}, {e.sourceLabel}: {_preview(e.text)}" for e in self.visible])
		if self.visible:
			self.list.SetSelection(0)
		self.showSelected()

	def onSearchKey(self, evt: wx.KeyEvent) -> None:
		if evt.GetKeyCode() in (wx.WXK_DOWN, wx.WXK_NUMPAD_DOWN) and not evt.HasAnyModifiers() and self.visible:
			self.list.SetFocus()
			return
		evt.Skip()

	def selected(self):
		sel = self.list.GetSelection()
		if sel == wx.NOT_FOUND or not (0 <= sel < len(self.visible)):
			return None
		return self.visible[sel]

	def showSelected(self) -> None:
		from ..productivity.notifications import ACTION_LABELS

		e = self.selected()
		if e is None:
			self.full.SetValue("")
		else:
			lines = [e.text, "", _("Aplicación: {app}").format(app=e.app or "?"), _("Tipo: {kind}").format(kind=e.sourceLabel), _("Hora: {time}").format(time=time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(e.time)))]
			if e.rule:
				lines.append(_("Regla aplicada: {rule} ({action})").format(rule=e.rule, action=ACTION_LABELS.get(e.action, e.action)))
			self.full.SetValue("\n".join(lines))
		for b in (self.copyButton, self.ruleButton, self.deleteButton):
			b.Enable(e is not None)

	def copySelected(self) -> None:
		e = self.selected()
		if e is None:
			wx.Bell()
			return
		from .. import api

		queue_handler.queueFunction(api.copyToClip, e.text, True)

	def ruleFromSelected(self) -> None:
		from ..productivity.notifications import Rule

		e = self.selected()
		if e is None:
			return
		words = " ".join(e.text.split()[:6])
		rule = Rule(name=_("Avisos de {app}").format(app=e.app) if e.app else "", apps=e.app, pattern=re.escape(words))
		editRule(self, rule, isNew=True)

	def deleteSelected(self) -> None:
		e = self.selected()
		if e is None:
			return
		_pkg().notificationStore.remove(e)
		sel = self.list.GetSelection()
		self.reload()
		if self.visible:
			self.list.SetSelection(min(sel, len(self.visible) - 1))
			self.showSelected()
		self.list.SetFocus()

	def clear(self) -> None:
		if message_dialog.messageBox(_("¿Borrar todo el historial de notificaciones?"), _("Confirmar"), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self) != wx.YES:
			return
		_pkg().notificationStore.clear()
		self.reload()
		self.list.SetFocus()

	def onClose(self, evt: wx.CloseEvent) -> None:
		global _historyDialog
		_historyDialog = None
		self.Destroy()


_historyDialog: NotificationHistoryDialog | None = None


def showNotificationHistory() -> None:
	def _show() -> None:
		global _historyDialog
		if _pkg().notificationStore is None:
			return
		if isAlive(_historyDialog):
			_historyDialog.reload()
		else:
			_historyDialog = NotificationHistoryDialog()
			_historyDialog.Show()
		bringToFront(_historyDialog)
		_historyDialog.list.SetFocus()

	runOnGui(_show)


# ====================================================================== reglas
class RuleDialog(wx.Dialog):
	def __init__(self, parent: wx.Window | None, rule, isNew: bool) -> None:
		from ..audio import tones
		from ..productivity.notifications import ACTION_LABELS, PRIORITY_LABELS, SOURCE_LABELS

		super().__init__(parent, title=_("Nueva regla de notificaciones") if isNew else _("Editar regla de notificaciones"))
		self.rule = rule
		sizer = wx.BoxSizer(wx.VERTICAL)
		grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=6)

		def labeled(label: str, ctrl_factory):
			grid.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
			ctrl = ctrl_factory()
			grid.Add(ctrl, 1, wx.EXPAND)
			return ctrl

		self.name = labeled(_("&Nombre:"), lambda: wx.TextCtrl(self, value=rule.name, size=(320, -1)))
		self.apps = labeled(_("&Aplicaciones (procesos separados por comas; vacío = todas):"), lambda: wx.TextCtrl(self, value=rule.apps))
		self.pattern = labeled(_("&Texto (expresión regular; vacío = cualquiera):"), lambda: wx.TextCtrl(self, value=rule.pattern))
		self._actions = list(ACTION_LABELS)
		self.action = labeled(_("A&cción:"), lambda: wx.Choice(self, choices=[ACTION_LABELS[a] for a in self._actions]))
		self.action.SetSelection(self._actions.index(rule.action) if rule.action in self._actions else 0)
		self._priorities = list(PRIORITY_LABELS)
		self.priority = labeled(_("&Prioridad de la voz:"), lambda: wx.Choice(self, choices=[PRIORITY_LABELS[p] for p in self._priorities]))
		self.priority.SetSelection(self._priorities.index(rule.priority) if rule.priority in self._priorities else 0)
		self._sounds = [""] + list(tones.availableSounds())
		self.sound = labeled(_("&Sonido:"), lambda: wx.Choice(self, choices=[_("(ninguno)")] + self._sounds[1:]))
		self.sound.SetSelection(self._sounds.index(rule.sound) if rule.sound in self._sounds else 0)
		sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 8)
		playBtn = wx.Button(self, label=_("Pro&bar el sonido"))
		playBtn.Bind(wx.EVT_BUTTON, self.onPlay)
		sizer.Add(playBtn, 0, wx.LEFT, 8)
		box = wx.StaticBoxSizer(wx.VERTICAL, self, _("Se aplica a"))
		self._sources = list(SOURCE_LABELS)
		self.sourceChecks = []
		for s in self._sources:
			cb = wx.CheckBox(box.GetStaticBox(), label=SOURCE_LABELS[s])
			cb.SetValue(not rule.sources or s in rule.sources)
			box.Add(cb, 0, wx.ALL, 3)
			self.sourceChecks.append(cb)
		sizer.Add(box, 0, wx.EXPAND | wx.ALL, 8)
		self.caseSensitive = wx.CheckBox(self, label=_("Distinguir &mayúsculas y minúsculas"))
		self.caseSensitive.SetValue(rule.caseSensitive)
		sizer.Add(self.caseSensitive, 0, wx.ALL, 6)
		self.enabled = wx.CheckBox(self, label=_("Regla act&iva"))
		self.enabled.SetValue(rule.enabled)
		sizer.Add(self.enabled, 0, wx.ALL, 6)
		addLabel(self, sizer, _("Te&xto de prueba:"))
		testRow = wx.BoxSizer(wx.HORIZONTAL)
		self.testText = wx.TextCtrl(self, size=(300, -1))
		testRow.Add(self.testText, 1, wx.ALL, 2)
		testBtn = wx.Button(self, label=_("Comp&robar"))
		testBtn.Bind(wx.EVT_BUTTON, self.onTest)
		testRow.Add(testBtn, 0, wx.ALL, 2)
		sizer.Add(testRow, 0, wx.EXPAND | wx.ALL, 6)
		btns = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
		sizer.Add(btns, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
		self.Bind(wx.EVT_BUTTON, self.onOk, id=wx.ID_OK)
		self.SetSizerAndFit(sizer)
		self.CentreOnScreen()
		self.name.SetFocus()

	def _readRule(self):
		from ..productivity.notifications import Rule

		sources = [s for s, cb in zip(self._sources, self.sourceChecks) if cb.GetValue()]
		if len(sources) == len(self._sources):
			sources = []
		return Rule(
			name=self.name.GetValue().strip(),
			enabled=self.enabled.GetValue(),
			apps=self.apps.GetValue().strip(),
			pattern=self.pattern.GetValue(),
			caseSensitive=self.caseSensitive.GetValue(),
			sources=sources,
			action=self._actions[max(0, self.action.GetSelection())],
			priority=self._priorities[max(0, self.priority.GetSelection())],
			sound=self._sounds[max(0, self.sound.GetSelection())],
		)

	def onPlay(self, evt) -> None:
		name = self._sounds[max(0, self.sound.GetSelection())]
		if name:
			from ..audio import tones

			queue_handler.queueFunction(tones.playSound, name)

	def onTest(self, evt) -> None:
		rule = self._readRule()
		if not rule.isValid():
			message_dialog.messageBox(_("La expresión regular no es válida."), _("Error"), wx.OK | wx.ICON_ERROR, self)
			return
		ok = rule.matches("", self.testText.GetValue()) if not rule.appList() else rule.matches(rule.appList()[0], self.testText.GetValue())
		speakMessage(_("El texto coincide con la regla") if ok else _("El texto no coincide con la regla"))

	def onOk(self, evt) -> None:
		rule = self._readRule()
		if not rule.isValid():
			message_dialog.messageBox(_("La expresión regular no es válida. Corrígela antes de guardar."), _("Error"), wx.OK | wx.ICON_ERROR, self)
			self.pattern.SetFocus()
			return
		if not any(cb.GetValue() for cb in self.sourceChecks):
			message_dialog.messageBox(_("Marca al menos un tipo de aviso."), _("Error"), wx.OK | wx.ICON_ERROR, self)
			return
		self.rule = rule
		self.EndModal(wx.ID_OK)


def editRule(parent: wx.Window | None, rule, isNew: bool = False) -> bool:
	"""Edita ``rule``; si se acepta, la guarda (nueva o sustituyendo la original)."""
	store = _pkg().notificationStore
	dlg = RuleDialog(parent, rule, isNew)
	try:
		if dlg.ShowModal() != wx.ID_OK:
			return False
		newRule = dlg.rule
	finally:
		dlg.Destroy()
	rules = list(store.rules)
	if isNew or rule not in rules:
		rules.append(newRule)
	else:
		rules[rules.index(rule)] = newRule
	store.rules = rules
	try:
		store.saveRules()
	except OSError as e:
		message_dialog.messageBox(_("No se pudieron guardar las reglas:\n{error}").format(error=e), _("Error"), wx.OK | wx.ICON_ERROR, parent)
	if isAlive(_rulesDialog):
		_rulesDialog.reload(newRule)
	return True


class RulesDialog(wx.Dialog):
	def __init__(self, parent: wx.Window | None) -> None:
		super().__init__(parent, title=_("Reglas de notificaciones"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(
			wx.StaticText(self, label=_("Se aplica la primera regla activa que coincida con la aplicación y el texto del aviso.")),
			0,
			wx.ALL,
			6,
		)
		addLabel(self, sizer, _("&Reglas:"))
		self.list = wx.ListBox(self, size=(560, 220), style=wx.LB_SINGLE)
		self.list.Bind(wx.EVT_LISTBOX_DCLICK, lambda evt: self.onEdit())
		sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 6)
		row = wx.BoxSizer(wx.HORIZONTAL)
		specs = [
			(_("&Añadir..."), self.onAdd),
			(_("&Editar..."), self.onEdit),
			(_("&Quitar"), self.onRemove),
			(_("&Subir"), lambda: self.onMove(-1)),
			(_("&Bajar"), lambda: self.onMove(1)),
			(_("Activar o &desactivar"), self.onToggle),
		]
		for label, func in specs:
			b = wx.Button(self, label=label)
			b.Bind(wx.EVT_BUTTON, lambda evt, f=func: f())
			row.Add(b, 0, wx.ALL, 3)
		sizer.Add(row, 0, wx.ALL, 4)
		close = wx.Button(self, wx.ID_CANCEL, _("Cerrar"))
		sizer.Add(close, 0, wx.ALIGN_RIGHT | wx.ALL, 6)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.Close(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, self.onClose)
		self.SetSizerAndFit(sizer)
		self.CentreOnScreen()
		self.reload()
		self.list.SetFocus()

	@property
	def store(self):
		return _pkg().notificationStore

	def reload(self, select=None) -> None:
		rules = self.store.rules
		self.list.Set([r.describe() for r in rules])
		if rules:
			idx = rules.index(select) if select in rules else 0
			self.list.SetSelection(idx)

	def _sel(self) -> int:
		i = self.list.GetSelection()
		return i if 0 <= i < len(self.store.rules) else -1

	def _save(self, select=None) -> None:
		try:
			self.store.saveRules()
		except OSError as e:
			message_dialog.messageBox(_("No se pudieron guardar las reglas:\n{error}").format(error=e), _("Error"), wx.OK | wx.ICON_ERROR, self)
		self.reload(select)

	def onAdd(self) -> None:
		from ..productivity.notifications import Rule

		editRule(self, Rule(), isNew=True)
		self.list.SetFocus()

	def onEdit(self) -> None:
		i = self._sel()
		if i < 0:
			return
		editRule(self, self.store.rules[i])
		self.list.SetFocus()

	def onRemove(self) -> None:
		i = self._sel()
		if i < 0:
			return
		rules = list(self.store.rules)
		del rules[i]
		self.store.rules = rules
		self._save(rules[min(i, len(rules) - 1)] if rules else None)
		self.list.SetFocus()

	def onMove(self, delta: int) -> None:
		i = self._sel()
		j = i + delta
		rules = list(self.store.rules)
		if i < 0 or not 0 <= j < len(rules):
			wx.Bell()
			return
		rules[i], rules[j] = rules[j], rules[i]
		self.store.rules = rules
		self._save(rules[j])
		self.list.SetFocus()

	def onToggle(self) -> None:
		i = self._sel()
		if i < 0:
			return
		rule = self.store.rules[i]
		rule.enabled = not rule.enabled
		self._save(rule)
		speakMessage(_("Regla activada") if rule.enabled else _("Regla desactivada"))

	def onClose(self, evt) -> None:
		global _rulesDialog
		_rulesDialog = None
		self.Destroy()


_rulesDialog: RulesDialog | None = None


def showNotificationRules(parent: wx.Window | None = None) -> None:
	def _show() -> None:
		global _rulesDialog
		if _pkg().notificationStore is None:
			return
		if not isAlive(_rulesDialog):
			_rulesDialog = RulesDialog(parent if isAlive(parent) else None)
			_rulesDialog.Show()
		bringToFront(_rulesDialog)
		_rulesDialog.list.SetFocus()

	runOnGui(_show)


# ====================================================================== vigilancias
def _watchRows() -> list[tuple[int, str, str]]:
	mgr = _pkg().watchManager
	if mgr is None:
		return []
	rows = []
	for w in mgr.watches:
		last = _preview(w.lastText, 120) if w.lastText else _("sin texto todavía")
		rows.append((w.slot, w.describe(), last))
	return rows


class WatchesDialog(wx.Dialog):
	def __init__(self) -> None:
		super().__init__(None, title=_("Vigilancias"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.rows: list = []
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, _("&Vigilancias activas:"))
		self.list = wx.ListBox(self, size=(600, 200), style=wx.LB_SINGLE)
		sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 6)
		row = wx.BoxSizer(wx.HORIZONTAL)
		read = wx.Button(self, label=_("&Leer contenido"))
		read.Bind(wx.EVT_BUTTON, lambda evt: self.onRead())
		read.SetDefault()
		remove = wx.Button(self, label=_("&Quitar"))
		remove.Bind(wx.EVT_BUTTON, lambda evt: self.onRemove())
		clear = wx.Button(self, label=_("Quitar &todas"))
		clear.Bind(wx.EVT_BUTTON, lambda evt: self.onClear())
		close = wx.Button(self, wx.ID_CANCEL, _("Cerrar"))
		for b in (read, remove, clear, close):
			row.Add(b, 0, wx.ALL, 3)
		sizer.Add(row, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.Close(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, self.onClose)
		self.SetSizerAndFit(sizer)
		self.CentreOnScreen()
		self.reload()

	def reload(self) -> None:
		_onCore(_watchRows, callback=self._fill)

	def _fill(self, rows) -> None:
		if not isAlive(self):
			return
		self.rows = rows or []
		if self.rows:
			self.list.Set([f"{desc}. {last}" for _slot, desc, last in self.rows])
			self.list.SetSelection(0)
		else:
			self.list.Set([_("No hay vigilancias. Usa Tiresias+Control+Alt+V sobre el objeto navegador para vigilarlo.")])

	def _slot(self) -> int | None:
		i = self.list.GetSelection()
		if 0 <= i < len(self.rows):
			return self.rows[i][0]
		return None

	def onRead(self) -> None:
		slot = self._slot()
		if slot is None:
			wx.Bell()
			return

		def read() -> None:
			from .. import speech

			w = _pkg().watchManager.get(slot)
			if w is not None:
				speech.speakMessage(w.lastText or _("sin texto"))

		queue_handler.queueFunction(read)

	def onRemove(self) -> None:
		slot = self._slot()
		if slot is None:
			wx.Bell()
			return

		def remove() -> None:
			mgr = _pkg().watchManager
			w = mgr.get(slot)
			if w is not None:
				mgr.remove(w)

		_onCore(remove, callback=lambda _r: self.reload())
		speakMessage(_("Vigilancia {n} quitada").format(n=slot))

	def onClear(self) -> None:
		if not self.rows:
			return
		_onCore(lambda: _pkg().watchManager.clear(), callback=lambda _r: self.reload())
		speakMessage(_("Vigilancias quitadas"))

	def onClose(self, evt) -> None:
		global _watchesDialog
		_watchesDialog = None
		self.Destroy()


_watchesDialog: WatchesDialog | None = None


def showWatches() -> None:
	def _show() -> None:
		global _watchesDialog
		if isAlive(_watchesDialog):
			_watchesDialog.reload()
		else:
			_watchesDialog = WatchesDialog()
			_watchesDialog.Show()
		bringToFront(_watchesDialog)
		_watchesDialog.list.SetFocus()

	runOnGui(_show)


# ====================================================================== marcadores de texto
class TextBookmarksDialog(wx.Dialog):
	def __init__(self, ctx, items: list[tuple[int, str]]) -> None:
		super().__init__(None, title=_("Marcadores de texto"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.ctx = ctx
		self.items = list(items)
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, _("&Marcadores de «{doc}»:").format(doc=ctx.docName or ctx.appName))
		self.list = wx.ListBox(self, choices=[label for _p, label in self.items], size=(560, 220), style=wx.LB_SINGLE)
		self.list.Bind(wx.EVT_LISTBOX_DCLICK, lambda evt: self.onGo())
		if self.items:
			self.list.SetSelection(0)
		sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 6)
		row = wx.BoxSizer(wx.HORIZONTAL)
		go = wx.Button(self, label=_("&Ir"))
		go.Bind(wx.EVT_BUTTON, lambda evt: self.onGo())
		go.SetDefault()
		remove = wx.Button(self, label=_("&Quitar"))
		remove.Bind(wx.EVT_BUTTON, lambda evt: self.onRemove())
		close = wx.Button(self, wx.ID_CANCEL, _("Cerrar"))
		for b in (go, remove, close):
			row.Add(b, 0, wx.ALL, 3)
		sizer.Add(row, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.Close(), id=wx.ID_CANCEL)
		# Sin esto, Close() volvía a enviar ID_CANCEL y el diálogo no se cerraba nunca.
		self.Bind(wx.EVT_CLOSE, lambda evt: self.Destroy())
		self.SetSizerAndFit(sizer)
		self.CentreOnScreen()

	def _pos(self) -> int | None:
		i = self.list.GetSelection()
		return self.items[i][0] if 0 <= i < len(self.items) else None

	def onGo(self) -> None:
		pos = self._pos()
		if pos is None:
			return
		ctx = self.ctx
		self.Close()
		# Se espera a que vuelva el foco a la aplicación antes de mover el cursor.
		queue_handler.callLater(400, ctx.moveTo, pos)

	def onRemove(self) -> None:
		i = self.list.GetSelection()
		pos = self._pos()
		if pos is None:
			return
		ctx = self.ctx

		def remove() -> None:
			from ..productivity.text_bookmarks import relocate

			store = _pkg().bookmarkStore
			marks = [bm for bm in store.get(ctx.key) if relocate(bm, ctx.text) != pos]
			store.set(ctx.key, marks)

		queue_handler.queueFunction(remove)
		del self.items[i]
		self.list.Delete(i)
		if self.items:
			self.list.SetSelection(min(i, len(self.items) - 1))
		speakMessage(_("marcador quitado"))


def showTextBookmarks(ctx, items: list[tuple[int, str]]) -> None:
	def _show() -> None:
		dlg = TextBookmarksDialog(ctx, items)
		dlg.Show()
		bringToFront(dlg)
		dlg.list.SetFocus()

	runOnGui(_show)


# ====================================================================== menú
def appendToolsMenu(frame, menu: wx.Menu) -> None:
	"""Añade las entradas de productividad al menú Herramientas."""
	add = frame.addMenuItem
	add(menu, _("Historial de &notificaciones..."), showNotificationHistory)
	add(menu, _("Reglas de noti&ficaciones..."), lambda: showNotificationRules())
	add(menu, _("Vigi&lancias..."), showWatches)


# ====================================================================== opciones
def registerSettingsPanels() -> None:
	from . import settings

	class ProductivityPanel(settings.ConfigPanel):
		title = _("Productividad")
		section = "textAnalyzer"

		def getFields(self) -> list:
			B, I = settings.Bool, settings.Int
			gA = _("Analizador de texto")
			gN = _("Historial de notificaciones")
			gW = _("Vigilancia de objetos")
			gF = _("Buscar en la ventana")
			return [
				B("brackets", _("Paréntesis, corchetes y llaves sin cerrar"), group=gA),
				B("quotes", _("Comillas sin cerrar"), group=gA),
				B("spanishMarks", _("Signos de apertura ¿ ¡ sin cerrar"), group=gA),
				B("doubleSpace", _("Espacios dobles"), group=gA),
				B("spaceBeforePunct", _("Espacio antes de signos de puntuación"), group=gA),
				B("lowercaseAfterPeriod", _("Minúscula al empezar una frase tras un punto"), group=gA),
				B("repeatedWord", _("Palabras repetidas"), group=gA),
				B("mixedCase", _("Mayúsculas raras dentro de una palabra"), group=gA),
				B("format", _("Formato incoherente (fuente o tamaño)"), group=gA),
				B("lineSound", _("Sonido al pasar por una línea con incoherencias"), group=gA),
				B("lineSpeak", _("Describir las incoherencias al leer cada línea"), group=gA),
				B("keepHistory", _("Guardar el historial de notificaciones"), section="notifications", group=gN),
				I("historySize", _("Número máximo de notificaciones guardadas:"), 10, 5000, section="notifications", group=gN),
				B("recordNotifications", _("Guardar las notificaciones de las aplicaciones"), section="notifications", group=gN),
				B("recordToasts", _("Guardar los avisos emergentes de Windows"), section="notifications", group=gN),
				B("recordLiveRegions", _("Guardar los cambios de las regiones vivas"), section="notifications", group=gN),
				B("applyRules", _("Aplicar las reglas de notificaciones"), section="notifications", group=gN),
				I("maxWatches", _("Número máximo de vigilancias:"), 1, 10, section="watch", group=gW),
				I("intervalMs", _("Intervalo de comprobación (milisegundos):"), 250, 10000, section="watch", group=gW),
				B("onlyNewText", _("Anunciar solo el texto nuevo"), section="watch", group=gW),
				B("playSound", _("Sonido al cambiar un objeto vigilado"), section="watch", group=gW),
				B("announceSlot", _("Decir el número de la vigilancia"), section="watch", group=gW),
				B("onlyWhenAppInForeground", _("Anunciar solo si su aplicación está en primer plano"), section="watch", group=gW),
				B("showInBraille", _("Mostrar los cambios en braille"), section="watch", group=gW),
				B("moveFocus", _("Mover también el foco al resultado si se puede"), section="windowFind", group=gF),
				B("caseSensitive", _("Distinguir mayúsculas y minúsculas"), section="windowFind", group=gF),
				B("includeOffscreen", _("Buscar también en los elementos que no se ven (desplazándose hasta ellos)"), section="windowFind", group=gF),
			]

		def makeExtraSettings(self, builder) -> None:
			btn = builder.addButton(_("&Reglas de notificaciones..."))
			btn.Bind(wx.EVT_BUTTON, lambda evt: showNotificationRules(wx.GetTopLevelParent(self)))

		def afterSave(self, changes) -> None:
			if ("notifications", "historySize") in changes:
				store = _pkg().notificationStore
				if store is not None:
					store.setMaxEntries(conf["notifications"]["historySize"])

	class ControllerPanel(settings.ConfigPanel):
		title = _("Programas externos")
		section = "controller"

		def getFields(self) -> list:
			B = settings.Bool
			return [
				B("enabled", _("Permitir que los juegos y programas hablen a través de Tiresias (API de control)")),
				B("nvdaCompatible", _("Atender también a los programas hechos para NVDA (nvdaControllerClient, Tolk...)")),
				B("nvdaWindow", _("Crear la ventana de identificación de NVDA que buscan algunas bibliotecas (Tolk)")),
				B("interrupt", _("Cortar la voz con cada texto nuevo de un programa")),
				B("speechToBraille", _("Mostrar en braille los textos que los programas mandan hablar")),
				B("allowBraille", _("Mostrar los mensajes braille de los programas")),
				B("onlyForeground", _("Atender solo al programa que está en primer plano")),
			]

		def makeExtraSettings(self, builder) -> None:
			self.status = builder.addText(_("Estado:"), "", style=wx.TE_MULTILINE | wx.TE_READONLY, size=(420, 80))
			btn = builder.addButton(_("Actualizar el &estado"))
			btn.Bind(wx.EVT_BUTTON, lambda evt: self.refreshStatus())
			folder = builder.addButton(_("Abrir la carpeta de la API para &desarrolladores"))
			folder.Bind(wx.EVT_BUTTON, self.onOpenFolder)
			self.refreshStatus()

		def refreshStatus(self) -> None:
			from .. import controller

			def done(text) -> None:
				if isAlive(self.status):
					self.status.SetValue(text or "")

			_onCore(controller.statusText, callback=done)

		def onOpenFolder(self, evt) -> None:
			import os

			from ..controller.server import controllerDir

			folder = controllerDir()
			try:
				os.startfile(folder)
			except OSError as e:
				message_dialog.messageBox(_("No se pudo abrir la carpeta: {error}").format(error=e), _("Error"), wx.OK | wx.ICON_ERROR, self)

		def afterSave(self, changes) -> None:
			from .. import controller

			queue_handler.queueFunction(controller.applyConfiguration)

	settings.registerPanel("productivity", ProductivityPanel.title, ProductivityPanel)
	settings.registerPanel("controller", ControllerPanel.title, ControllerPanel)
