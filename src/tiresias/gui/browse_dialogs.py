"""Diálogos del modo exploración: lista de elementos, búsqueda, lectura rápida y web flexible."""

from __future__ import annotations

from typing import Any, Callable

import wx

from .. import queue_handler
from ..i18n import _
from ..log import getLogger
from .helpers import addLabel, bringToFront, isAlive, matchesAll, normalizeForSearch, runOnGui

log = getLogger("gui.browseDialogs")

#: (clave, etiqueta) de los tipos de elemento, en el orden de las pestañas.
ELEMENT_KINDS: list[tuple[str, str]] = [
	("link", _("Enlaces")),
	("heading", _("Encabezados")),
	("formField", _("Campos de formulario")),
	("button", _("Botones")),
	("landmark", _("Puntos de referencia")),
	("table", _("Tablas")),
	("graphic", _("Gráficos")),
	("clickable", _("Pulsables")),
	("tab", _("Pestañas")),
	("figure", _("Figuras")),
	("article", _("Artículos")),
	("annotation", _("Anotaciones")),
	("error", _("Errores")),
	("frame", _("Marcos")),
	("prominent", _("Destacados")),
]

#: Tipos que se calculan al abrir su pestaña (necesitan consultar el documento).
LAZY_KINDS = {"prominent"}
#: Tipos que se muestran anidados por nivel.
NESTED_KINDS = {"heading", "landmark"}

_lastKind = "link"


def _runOnCore(func: Callable[[], Any], then: Callable[[Any], None]) -> None:
	"""Ejecuta ``func`` en el núcleo y entrega el resultado a ``then`` en la interfaz."""

	def work() -> None:
		try:
			result = func()
		except Exception:
			log.exception("Error en el documento")
			result = None
		runOnGui(then, result)

	queue_handler.queueFunction(work)


class ElementsListDialog(wx.Dialog):
	"""Lista de enlaces, encabezados, campos... con una pestaña por tipo.

	``data`` asocia cada tipo con una lista de (etiqueta, desplazamiento, nivel).
	"""

	def __init__(self, doc: Any, data: dict[str, list[tuple[str, int, int]]], caret: int) -> None:
		super().__init__(None, title=_("Lista de elementos"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.doc = doc
		self.data = dict(data)
		self.caret = caret
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, _("&Filtrar por:"))
		self.filterText = wx.TextCtrl(self)
		self.filterText.Bind(wx.EVT_TEXT, self.onFilter)
		sizer.Add(self.filterText, 0, wx.EXPAND | wx.ALL, 6)
		self.book = wx.Notebook(self)
		self.trees: dict[str, wx.TreeCtrl] = {}
		for key, label in ELEMENT_KINDS:
			page = wx.Panel(self.book)
			ps = wx.BoxSizer(wx.VERTICAL)
			tree = wx.TreeCtrl(page, size=(480, 300), style=wx.TR_HAS_BUTTONS | wx.TR_HIDE_ROOT | wx.TR_SINGLE | wx.TR_LINES_AT_ROOT)
			tree.SetName(label)
			tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, lambda evt: self.finish(True))
			tree.Bind(wx.EVT_TREE_SEL_CHANGED, lambda evt: self.updateButtons())
			ps.Add(tree, 1, wx.EXPAND | wx.ALL, 2)
			page.SetSizer(ps)
			self.trees[key] = tree
			self.book.AddPage(page, label)
		keys = [k for k, _l in ELEMENT_KINDS]
		self.book.SetSelection(keys.index(_lastKind) if _lastKind in keys else 0)
		self.book.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.onKindChange)
		sizer.Add(self.book, 1, wx.EXPAND | wx.ALL, 6)
		buttons = wx.BoxSizer(wx.HORIZONTAL)
		self.activateButton = wx.Button(self, label=_("&Activar"))
		self.activateButton.SetDefault()
		self.activateButton.Bind(wx.EVT_BUTTON, lambda evt: self.finish(True))
		self.moveButton = wx.Button(self, label=_("&Mover a"))
		self.moveButton.Bind(wx.EVT_BUTTON, lambda evt: self.finish(False))
		cancel = wx.Button(self, wx.ID_CANCEL, _("Cancelar"))
		for b in (self.activateButton, self.moveButton, cancel):
			buttons.Add(b, 0, wx.ALL, 4)
		sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.Close(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, self.onClose)
		self.CentreOnScreen()
		self.populate(selectNearCaret=True)

	# ------------------------------------------------------------------ datos
	@property
	def kind(self) -> str:
		return ELEMENT_KINDS[max(0, self.book.GetSelection())][0]

	@property
	def tree(self) -> wx.TreeCtrl:
		return self.trees[self.kind]

	def populate(self, selectNearCaret: bool = False) -> None:
		kind = self.kind
		if kind not in self.data:
			self._loadLazy(kind)
		tree = self.tree
		tree.Freeze()
		try:
			tree.DeleteAllItems()
			root = tree.AddRoot("")
			elements = self.data.get(kind)
			if elements is None:
				tree.AppendItem(root, _("Calculando..."))
				return
			query = self.filterText.GetValue().strip()
			nested = kind in NESTED_KINDS and not query
			stack: list[tuple[int, wx.TreeItemId]] = []
			items: list[tuple[int, wx.TreeItemId]] = []
			for label, offset, level in elements:
				if query and not matchesAll(normalizeForSearch(label), query):
					continue
				parent = root
				if nested:
					level = level or 1
					while stack and stack[-1][0] >= level:
						stack.pop()
					if stack:
						parent = stack[-1][1]
				text = label or _("(sin etiqueta)")
				if kind == "heading" and level and not nested:
					text = _("{label} (nivel {level})").format(label=text, level=level)
				item = tree.AppendItem(parent, text)
				tree.SetItemData(item, offset)
				if nested:
					stack.append((level, item))
				items.append((offset, item))
			if nested:
				tree.ExpandAll()
			target = None
			if items:
				target = items[0][1]
				if selectNearCaret:
					for offset, item in items:
						if offset <= self.caret:
							target = item
						else:
							break
			if target is not None:
				tree.SelectItem(target)
				tree.EnsureVisible(target)
		finally:
			tree.Thaw()
			self.updateButtons()

	def _loadLazy(self, kind: str) -> None:
		if kind in self.__dict__.setdefault("_loading", set()):
			return
		self._loading.add(kind)
		doc = self.doc

		def done(result: Any) -> None:
			if not isAlive(self):
				return
			self.data[kind] = result or []
			if self.kind == kind:
				self.populate(selectNearCaret=True)

		_runOnCore(lambda: doc.getElements(kind), done)

	def selectedOffset(self) -> int | None:
		tree = self.tree
		item = tree.GetSelection()
		if not item.IsOk() or item == tree.GetRootItem():
			return None
		data = tree.GetItemData(item)
		return data if isinstance(data, int) else None

	def updateButtons(self) -> None:
		has = self.selectedOffset() is not None
		self.activateButton.Enable(has)
		self.moveButton.Enable(has)

	# ------------------------------------------------------------------ eventos
	def onKindChange(self, evt: wx.BookCtrlEvent) -> None:
		global _lastKind
		_lastKind = self.kind
		self.populate(selectNearCaret=True)
		evt.Skip()

	def onFilter(self, evt: wx.CommandEvent) -> None:
		self.populate(selectNearCaret=False)

	def finish(self, activate: bool) -> None:
		offset = self.selectedOffset()
		if offset is None:
			wx.Bell()
			return
		doc = self.doc
		self.Close()
		queue_handler.queueFunction(doc.moveToOffsetFromGui, offset, activate)

	def onClose(self, evt: wx.CloseEvent) -> None:
		global _dialog
		_dialog = None
		# Los árboles emiten cambios de selección mientras se destruyen.
		for tree in self.trees.values():
			tree.Unbind(wx.EVT_TREE_SEL_CHANGED)
		self.Destroy()


_dialog: ElementsListDialog | None = None


def showElementsList(doc: Any, data: dict[str, list[tuple[str, int, int]]], caret: int) -> None:
	"""Muestra la lista de elementos de ``doc`` (seguro desde cualquier hilo)."""

	def _show() -> None:
		global _dialog
		if isAlive(_dialog):
			_dialog.Close()
		_dialog = ElementsListDialog(doc, data, caret)
		_dialog.Show()
		bringToFront(_dialog)
		_dialog.tree.SetFocus()

	runOnGui(_show)


# ====================================================================== búsqueda
class FindDialog(wx.Dialog):
	"""Buscar en el documento: historial, mayúsculas, palabra completa y expresiones regulares (#18422)."""

	def __init__(self, doc: Any, text: str, history: list[str], options: dict) -> None:
		super().__init__(None, title=_("Buscar"))
		self.doc = doc
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, _("&Texto a buscar:"))
		self.text = wx.ComboBox(self, value=text, choices=history, style=wx.CB_DROPDOWN)
		sizer.Add(self.text, 0, wx.EXPAND | wx.ALL, 6)
		self.caseSensitive = wx.CheckBox(self, label=_("Distinguir &mayúsculas y minúsculas"))
		self.caseSensitive.SetValue(bool(options.get("caseSensitive")))
		self.wholeWord = wx.CheckBox(self, label=_("Solo &palabras completas"))
		self.wholeWord.SetValue(bool(options.get("wholeWord")))
		self.regex = wx.CheckBox(self, label=_("Usar &expresión regular"))
		self.regex.SetValue(bool(options.get("regex")))
		for cb in (self.caseSensitive, self.wholeWord, self.regex):
			sizer.Add(cb, 0, wx.ALL, 4)
		buttons = wx.BoxSizer(wx.HORIZONTAL)
		nextB = wx.Button(self, label=_("Buscar &siguiente"))
		nextB.SetDefault()
		nextB.Bind(wx.EVT_BUTTON, lambda evt: self.finish(1))
		prevB = wx.Button(self, label=_("Buscar &anterior"))
		prevB.Bind(wx.EVT_BUTTON, lambda evt: self.finish(-1))
		cancel = wx.Button(self, wx.ID_CANCEL, _("Cancelar"))
		for b in (nextB, prevB, cancel):
			buttons.Add(b, 0, wx.ALL, 4)
		sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.Destroy(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, lambda evt: self.Destroy())
		self.CentreOnScreen()

	def finish(self, direction: int) -> None:
		text = self.text.GetValue()
		if not text:
			wx.Bell()
			return
		opts = {"caseSensitive": self.caseSensitive.GetValue(), "wholeWord": self.wholeWord.GetValue(), "regex": self.regex.GetValue()}
		doc = self.doc
		self.Destroy()
		queue_handler.queueFunction(lambda: doc.find(text, direction, **opts))


def showFindDialog(doc: Any, text: str, history: list[str], options: dict) -> None:
	def _show() -> None:
		dlg = FindDialog(doc, text, history, options)
		dlg.Show()
		bringToFront(dlg)
		dlg.text.SetFocus()
		dlg.text.SelectAll()

	runOnGui(_show)


# ====================================================================== lectura rápida
SKIM_RULES = [
	("firstSentence", _("Primera frase de cada párrafo (y los encabezados)")),
	("headings", _("Solo encabezados")),
	("contains", _("Párrafos que contienen el texto")),
	("regex", _("Párrafos que cumplen la expresión regular")),
]


class SkimDialog(wx.Dialog):
	"""Lectura rápida: aplica una regla y muestra un resumen navegable."""

	def __init__(self, doc: Any) -> None:
		super().__init__(None, title=_("Lectura rápida"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.doc = doc
		self.results: list[tuple[str, int]] = []
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.rule = wx.RadioBox(self, label=_("&Regla"), choices=[label for _k, label in SKIM_RULES], majorDimension=1, style=wx.RA_SPECIFY_COLS)
		sizer.Add(self.rule, 0, wx.EXPAND | wx.ALL, 6)
		addLabel(self, sizer, _("&Texto o expresión:"))
		# Intro en el texto aplica la regla (no «Ir al resultado» con los resultados viejos).
		self.text = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
		self.text.Bind(wx.EVT_TEXT_ENTER, lambda evt: self.compute())
		sizer.Add(self.text, 0, wx.EXPAND | wx.ALL, 6)
		apply = wx.Button(self, label=_("&Aplicar la regla"))
		apply.Bind(wx.EVT_BUTTON, lambda evt: self.compute())
		sizer.Add(apply, 0, wx.ALL, 4)
		addLabel(self, sizer, _("R&esultados:"))
		self.list = wx.ListBox(self, size=(520, 280))
		self.list.Bind(wx.EVT_LISTBOX_DCLICK, lambda evt: self.goTo())
		sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 6)
		buttons = wx.BoxSizer(wx.HORIZONTAL)
		go = wx.Button(self, label=_("&Ir al resultado"))
		go.Bind(wx.EVT_BUTTON, lambda evt: self.goTo())
		go.SetDefault()
		read = wx.Button(self, label=_("&Leer todos"))
		read.Bind(wx.EVT_BUTTON, lambda evt: self.readAll())
		cancel = wx.Button(self, wx.ID_CANCEL, _("Cerrar"))
		for b in (go, read, cancel):
			buttons.Add(b, 0, wx.ALL, 4)
		sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.Destroy(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, lambda evt: self.Destroy())
		self.CentreOnScreen()
		self.compute()

	def compute(self) -> None:
		rule = SKIM_RULES[max(0, self.rule.GetSelection())][0]
		text = self.text.GetValue()
		doc = self.doc

		def done(result: Any) -> None:
			if not isAlive(self):
				return
			self.results = result or []
			self.list.Set([t if len(t) < 200 else t[:200] + "…" for t, _o in self.results] or [_("(sin resultados)")])
			if self.results:
				self.list.SetSelection(0)

		_runOnCore(lambda: doc.skimResults(rule, text), done)

	def _selected(self) -> int | None:
		i = self.list.GetSelection()
		if i == wx.NOT_FOUND or i >= len(self.results):
			return None
		return self.results[i][1]

	def goTo(self) -> None:
		offset = self._selected()
		if offset is None:
			wx.Bell()
			return
		doc = self.doc
		self.Destroy()
		queue_handler.queueFunction(doc.moveToOffsetFromGui, offset, False)

	def readAll(self) -> None:
		if not self.results:
			wx.Bell()
			return
		from .. import speech

		texts = [t for t, _o in self.results]
		queue_handler.queueFunction(lambda: (speech.cancelSpeech(), speech.speak(texts)))


def showSkimDialog(doc: Any) -> None:
	def _show() -> None:
		dlg = SkimDialog(doc)
		dlg.Show()
		bringToFront(dlg)
		dlg.rule.SetFocus()

	runOnGui(_show)


# ====================================================================== web flexible
class FlexWebDialog(wx.Dialog):
	"""Gestión de la web flexible: elementos ocultos, inicio de lectura y orden visual por sitio."""

	def __init__(self, doc: Any, currentSite: str) -> None:
		from ..browse import flexweb

		super().__init__(None, title=_("Web flexible"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.doc = doc
		self.data = flexweb.allSites()
		self.changed: set[str] = set()
		#: Ámbitos de textos de IA que se borrarán al aceptar.
		self.removedAi: set[str] = set()
		from ..ai import labelstore

		for scope in labelstore.allScopes():
			self.data.setdefault(flexweb.siteKey(scope), {})
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, _("&Sitios:"))
		self.sites = wx.ListBox(self, size=(420, 120))
		self.sites.Bind(wx.EVT_LISTBOX, lambda evt: self.showSite())
		sizer.Add(self.sites, 0, wx.EXPAND | wx.ALL, 6)
		addLabel(self, sizer, _("&Reglas del sitio:"))
		self.rules = wx.ListBox(self, size=(420, 160))
		sizer.Add(self.rules, 1, wx.EXPAND | wx.ALL, 6)
		self.visual = wx.CheckBox(self, label=_("Orden de lectura &visual por columnas"))
		self.visual.Bind(wx.EVT_CHECKBOX, self.onVisual)
		sizer.Add(self.visual, 0, wx.ALL, 6)
		buttons = wx.BoxSizer(wx.HORIZONTAL)
		delRule = wx.Button(self, label=_("&Quitar la regla"))
		delRule.Bind(wx.EVT_BUTTON, lambda evt: self.removeRule())
		delSite = wx.Button(self, label=_("Quitar &todo el sitio"))
		delSite.Bind(wx.EVT_BUTTON, lambda evt: self.removeSite())
		ok = wx.Button(self, wx.ID_OK, _("Aceptar"))
		ok.Bind(wx.EVT_BUTTON, lambda evt: self.save())
		cancel = wx.Button(self, wx.ID_CANCEL, _("Cancelar"))
		for b in (delRule, delSite, ok, cancel):
			buttons.Add(b, 0, wx.ALL, 4)
		sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.Destroy(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, lambda evt: self.Destroy())
		self.siteKeys = sorted(self.data)
		if currentSite not in self.siteKeys:
			self.siteKeys.insert(0, currentSite)
			self.data[currentSite] = {}
		self.sites.Set(self.siteKeys)
		self.sites.SetSelection(self.siteKeys.index(currentSite))
		self.showSite()
		self.CentreOnScreen()

	@property
	def site(self) -> str | None:
		i = self.sites.GetSelection()
		return self.siteKeys[i] if i != wx.NOT_FOUND else None

	def _entries(self) -> list[tuple[str, Any]]:
		from ..browse import flexweb

		entry = self.data.get(self.site or "", {})
		out: list[tuple[str, Any]] = []
		for i, rule in enumerate(entry.get("hidden") or []):
			out.append((_("Oculto: {what}").format(what=flexweb.describeRule(rule)), ("hidden", i)))
		if entry.get("start"):
			out.append((_("Inicio de lectura: {what}").format(what=flexweb.describeRule(entry["start"])), ("start", 0)))
		# Orden de lectura propio y textos generados con IA (foros 3.10 y 6.3).
		for scope, ops in sorted((entry.get("readingOrder") or {}).items()):
			where = _("todo el sitio") if scope == flexweb.SITE_SCOPE else scope
			out.append((_("Orden de lectura propio ({n} cambios): {where}").format(n=len(ops), where=where), ("order", scope)))
		from ..ai import labelstore

		for scope, n in sorted(labelstore.scopesForSite(self.site or "").items()):
			if scope not in self.removedAi:
				out.append((_("Textos de IA ({n}): {where}").format(n=n, where=scope), ("ai", scope)))
		return out

	def showSite(self) -> None:
		entries = self._entries()
		self.rules.Set([label for label, _k in entries] or [_("(sin reglas)")])
		self.visual.SetValue(bool(self.data.get(self.site or "", {}).get("visualOrder")))

	def onVisual(self, evt: wx.CommandEvent) -> None:
		site = self.site
		if site is None:
			return
		entry = self.data.setdefault(site, {})
		if self.visual.GetValue():
			entry["visualOrder"] = True
		else:
			entry.pop("visualOrder", None)
		self.changed.add(site)

	def removeRule(self) -> None:
		site = self.site
		entries = self._entries()
		i = self.rules.GetSelection()
		if site is None or i == wx.NOT_FOUND or i >= len(entries):
			wx.Bell()
			return
		kind, idx = entries[i][1]
		entry = self.data.setdefault(site, {})
		if kind == "hidden":
			del entry["hidden"][idx]
		elif kind == "order":
			(entry.get("readingOrder") or {}).pop(idx, None)
			if not entry.get("readingOrder"):
				entry.pop("readingOrder", None)
		elif kind == "ai":
			self.removedAi.add(idx)
		else:
			entry.pop("start", None)
		self.changed.add(site)
		self.showSite()

	def removeSite(self) -> None:
		site = self.site
		if site is None:
			return
		self.data[site] = {}
		from ..ai import labelstore

		self.removedAi.update(labelstore.scopesForSite(site))
		self.changed.add(site)
		self.showSite()

	def save(self) -> None:
		from ..ai import labelstore
		from ..browse import flexweb

		for site in self.changed:
			flexweb.replaceSite(site, self.data.get(site) or {})
		for scope in self.removedAi:
			labelstore.removeScope(scope)
		doc = self.doc
		changed = bool(self.changed)
		self.Destroy()
		if changed:
			queue_handler.queueFunction(doc.requestRebuild)


def showFlexWebDialog(doc: Any) -> None:
	from ..browse import flexweb

	site = flexweb.siteKey(doc._documentKey())

	def _show() -> None:
		dlg = FlexWebDialog(doc, site)
		dlg.Show()
		bringToFront(dlg)
		dlg.sites.SetFocus()

	runOnGui(_show)
