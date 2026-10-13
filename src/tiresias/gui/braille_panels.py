"""Categoría «Presentación braille» del cuadro de Opciones.

Va justo después de «Braille» (la línea, las tablas, la entrada y el
seguimiento) y reúne:

- cómo se presenta el texto (párrafos, ajuste, contexto, selección, formato,
  errores, emojis, caracteres no definidos, regiones vivas, línea dividida);
- el orden y la visibilidad de las propiedades de los objetos (#7232, #7887);
- el diálogo de abreviaturas de rol (#4105);
- el visor braille.
"""

from __future__ import annotations

from typing import Any

import wx

from .. import queue_handler
from ..config import conf
from ..i18n import _
from ..log import getLogger
from . import settings
from .settings import Bool, Choice, ConfigPanel, Field, Int

log = getLogger("gui.braillePanels")

_PARAGRAPH_MARKERS = [("", _("Ninguna (salto de línea)")), (" ", _("Espacio")), ("¶", _("Marca de párrafo (¶)"))]
_FORMAT_DISPLAY = [
	("off", _("No mostrar")),
	("liblouis", _("Indicadores de énfasis de la tabla braille")),
	("dots78", _("Subrayado con los puntos 7 y 8")),
]
_UNDEFINED = [
	("hex", _("Código hexadecimal (\\x...)")),
	("allDots", _("Celda con todos los puntos")),
	("questionMark", _("Signo de interrogación")),
	("omit", _("No mostrar")),
]
_SPLIT = [
	("off", _("Sin dividir")),
	("speech", _("Última frase dicha")),
	("review", _("Línea del cursor de revisión")),
	("title", _("Título de la ventana")),
	("clock", _("Hora y fecha")),
]
#: Opciones de «Enrutar en la revisión...» (las usa la categoría «Braille»).
REVIEW_ROUTING = [
	("never", _("Nunca")),
	("onlyWhenAutoTethered", _("Solo con seguimiento automático")),
	("always", _("Siempre")),
]
#: Opciones de «Teclado braille del PC» (las usa la categoría «Braille»).
PC_DOTS = [(8, _("8 puntos (A S D F, J K L Ñ)")), (6, _("6 puntos (S D F, J K L)"))]


class BraillePresentationPanel(ConfigPanel):
	title = _("Presentación braille")
	section = "braille"

	def getFields(self) -> list[Field]:
		gp = _("Texto")
		gv = _("Visor braille")
		# La línea, las tablas, la entrada y el seguimiento están en la categoría «Braille».
		return [
			Bool("readByParagraph", _("Leer por párrafos"), group=gp),
			Choice("paragraphStartMarker", _("Marca de inicio de párrafo (al leer por párrafos):"), _PARAGRAPH_MARKERS, group=gp),
			Choice("textWrap", _("Ajuste del texto:"), settings._BRAILLE_TEXT_WRAP, group=gp),
			Choice("focusContextPresentation", _("Presentación del contexto del foco:"), settings._BRAILLE_CONTEXT, group=gp),
			Bool("showSelection", _("Mostrar la selección"), group=gp),
			Bool("markSelectedItem", _("Subrayar con los puntos 7 y 8 el elemento seleccionado de listas y árboles"), group=gp),
			Choice("fontFormattingDisplay", _("Formato del texto:"), _FORMAT_DISPLAY, group=gp),
			Bool("showSpellingErrors", _("Subrayar los errores ortográficos con los puntos 7 y 8"), group=gp),
			Bool("showEmojiNames", _("Mostrar el nombre de los emojis"), group=gp),
			Choice("undefinedCharacters", _("Caracteres que la tabla no define:"), _UNDEFINED, group=gp),
			Bool("unicodeNormalization", _("Normalización Unicode (letras con acentos combinados, ligaduras...)"), group=gp),
			Bool("reportLiveRegions", _("Mostrar las regiones vivas"), group=gp),
			Choice("splitView", _("Dividir la línea; parte derecha:"), _SPLIT, group=gp),
			Bool("showAtStartup", _("Mostrar el visor braille al iniciar"), section="brailleViewer", group=gv),
			Int("numCellsForViewer", _("Número de celdas del visor braille:"), 10, 120, group=gv),
			Bool("routeOnHover", _("Enrutar al dejar el puntero sobre una celda"), section="brailleViewer", group=gv),
			Int("hoverDwellTime", _("Espera para enrutar con el puntero (milisegundos):"), 200, 5000, section="brailleViewer", group=gv),
		]

	def makeExtraSettings(self, builder: settings.SettingsBuilder) -> None:
		from ..braille import presenter

		group = builder.group(_("Propiedades de los objetos en braille"))
		group.addStaticText(_("Marque las propiedades que se muestran y ordénelas con los botones."))
		labels = presenter.propertyLabels()
		order = [k for k in (conf["braille"]["propertyOrder"] or []) if k in labels]
		order += [k for k in presenter.PROPERTY_KEYS if k not in order]
		hidden = set(conf["braille"]["hiddenProperties"] or [])
		self._propKeys = order
		self._propList = group.addLabeledControl(
			_("Propi&edades:"),
			lambda p: wx.CheckListBox(p, choices=[labels[k] for k in order], size=(320, 180)),
			vertical=True,
		)
		for i, k in enumerate(order):
			self._propList.Check(i, k not in hidden)
		if order:
			self._propList.SetSelection(0)
		row = wx.BoxSizer(wx.HORIZONTAL)
		up = wx.Button(group.parent, label=_("&Subir"))
		down = wx.Button(group.parent, label=_("&Bajar"))
		row.Add(up, 0, wx.RIGHT, 6)
		row.Add(down, 0)
		group.sizer.Add(row, 0, wx.BOTTOM, 6)
		up.Bind(wx.EVT_BUTTON, lambda e: self._move(-1))
		down.Bind(wx.EVT_BUTTON, lambda e: self._move(1))
		roles = builder.addButton(_("&Abreviaturas de los roles..."))
		roles.Bind(wx.EVT_BUTTON, self._onRoles)
		self._roleAbbreviations: dict[str, str] | None = None
		# Opciones fijadas por la política: los controles propios se desactivan.
		self._propsLocked = self.lockControls("braille", ("propertyOrder", "hiddenProperties"), self._propList, up, down)
		self._rolesLocked = self.lockControls("braille", "roleAbbreviations", roles)
		self._helpKeys = {self._propList: ("braille", "propertyOrder"), up: ("braille", "propertyOrder"), down: ("braille", "propertyOrder"), roles: ("braille", "roleAbbreviations")}

	def _fillProperties(self, order: list[str], hidden: set[str]) -> None:
		from ..braille import presenter

		labels = presenter.propertyLabels()
		order = [k for k in order if k in labels]
		order += [k for k in presenter.PROPERTY_KEYS if k not in order]
		self._propKeys = order
		self._propList.Set([labels[k] for k in order])
		for i, k in enumerate(order):
			self._propList.Check(i, k not in hidden)
		if order:
			self._propList.SetSelection(0)

	def resetExtraToFactory(self) -> None:
		if not self._propsLocked:
			order = list(self.factoryValue("braille", "propertyOrder", []) or [])
			self._fillProperties(order, set(self.factoryValue("braille", "hiddenProperties", []) or []))
		if not self._rolesLocked:
			self._roleAbbreviations = dict(self.factoryValue("braille", "roleAbbreviations", {}) or {})

	def _move(self, delta: int) -> None:
		lst = self._propList
		i = lst.GetSelection()
		j = i + delta
		if i < 0 or not (0 <= j < len(self._propKeys)):
			return
		keys = self._propKeys
		checked = [lst.IsChecked(k) for k in range(len(keys))]
		keys[i], keys[j] = keys[j], keys[i]
		checked[i], checked[j] = checked[j], checked[i]
		from ..braille import presenter

		labels = presenter.propertyLabels()
		lst.Set([labels[k] for k in keys])
		for k, c in enumerate(checked):
			lst.Check(k, c)
		lst.SetSelection(j)
		lst.SetFocus()

	def _onRoles(self, evt: wx.CommandEvent) -> None:
		current = self._roleAbbreviations
		if current is None:
			current = dict(conf["braille"]["roleAbbreviations"] or {})
		dlg = RoleAbbreviationsDialog(self, current)
		try:
			if dlg.ShowModal() == wx.ID_OK:
				self._roleAbbreviations = dlg.result()
		finally:
			dlg.Destroy()

	def onSave(self) -> None:
		super().onSave()
		changed = False
		lst = self._propList
		order = list(self._propKeys)
		hidden = [k for i, k in enumerate(order) if not lst.IsChecked(i)]
		if not self._propsLocked and order != list(conf["braille"]["propertyOrder"] or []):
			conf["braille"]["propertyOrder"] = order
			changed = True
		if not self._propsLocked and sorted(hidden) != sorted(conf["braille"]["hiddenProperties"] or []):
			conf["braille"]["hiddenProperties"] = hidden
			changed = True
		if not self._rolesLocked and self._roleAbbreviations is not None and self._roleAbbreviations != dict(conf["braille"]["roleAbbreviations"] or {}):
			conf["braille"]["roleAbbreviations"] = dict(self._roleAbbreviations)
			changed = True
		if changed:
			self.afterSave({})

	def afterSave(self, changes: dict[tuple[str, str], tuple[Any, Any]]) -> None:
		from .. import braille

		if ("braille", "numCellsForViewer") in changes:
			queue_handler.queueFunction(braille.handler.reloadViewer)
		queue_handler.queueFunction(braille.handler.applyConfig)


class RoleAbbreviationsDialog(wx.Dialog):
	"""Abreviaturas de rol en braille (#4105)."""

	def __init__(self, parent: wx.Window, overrides: dict[str, str]) -> None:
		super().__init__(parent, title=_("Abreviaturas de los roles en braille"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		from ..braille import presenter
		from ..objects.roles import Role, roleLabel

		self._overrides = dict(overrides)
		self._roles = sorted((r for r in Role if roleLabel(r)), key=lambda r: roleLabel(r).lower())
		self._defaults = {r.name: presenter.defaultRoleAbbreviation(r) for r in self._roles}
		main = wx.BoxSizer(wx.VERTICAL)
		main.Add(
			wx.StaticText(self, label=_("Elija un rol y escriba su abreviatura. Déjela vacía para no mostrar el rol.")),
			0,
			wx.ALL,
			8,
		)
		main.Add(wx.StaticText(self, label=_("R&oles:")), 0, wx.LEFT | wx.RIGHT, 8)
		self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=(460, 300))
		self.list.InsertColumn(0, _("Rol"), width=260)
		self.list.InsertColumn(1, _("Abreviatura"), width=180)
		for i, r in enumerate(self._roles):
			self.list.InsertItem(i, roleLabel(r))
			self.list.SetItem(i, 1, self._value(r.name))
		main.Add(self.list, 1, wx.EXPAND | wx.ALL, 8)
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(self, label=_("A&breviatura:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
		self.edit = wx.TextCtrl(self, size=(200, -1))
		row.Add(self.edit, 0, wx.RIGHT, 6)
		self.resetBtn = wx.Button(self, label=_("&Restablecer"))
		row.Add(self.resetBtn, 0)
		main.Add(row, 0, wx.ALL, 8)
		buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
		main.Add(buttons, 0, wx.EXPAND | wx.ALL, 8)
		self.SetSizerAndFit(main)
		self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._onSelect)
		self.edit.Bind(wx.EVT_TEXT, self._onEdit)
		self.resetBtn.Bind(wx.EVT_BUTTON, self._onReset)
		self._updating = False
		if self._roles:
			self.list.Select(0)
			self.list.Focus(0)

	def _value(self, name: str) -> str:
		return self._overrides.get(name, self._defaults.get(name, ""))

	def _current(self):
		i = self.list.GetFirstSelected()
		return self._roles[i] if 0 <= i < len(self._roles) else None

	def _onSelect(self, evt: wx.ListEvent) -> None:
		r = self._current()
		if r is None:
			return
		self._updating = True
		self.edit.SetValue(self._value(r.name))
		self._updating = False

	def _onEdit(self, evt: wx.CommandEvent) -> None:
		if self._updating:
			return
		r = self._current()
		if r is None:
			return
		val = self.edit.GetValue().strip()
		if val == self._defaults.get(r.name, ""):
			self._overrides.pop(r.name, None)
		else:
			self._overrides[r.name] = val
		self.list.SetItem(self.list.GetFirstSelected(), 1, val)

	def _onReset(self, evt: wx.CommandEvent) -> None:
		r = self._current()
		if r is None:
			return
		self._overrides.pop(r.name, None)
		self._updating = True
		self.edit.SetValue(self._defaults.get(r.name, ""))
		self._updating = False
		self.list.SetItem(self.list.GetFirstSelected(), 1, self._defaults.get(r.name, ""))

	def result(self) -> dict[str, str]:
		return dict(self._overrides)


def _register() -> None:
	"""Añade la categoría «Presentación braille» (su sitio en la lista lo da ``settings.getPanelIds``)."""
	settings.registerPanel("brailleAdvanced", BraillePresentationPanel.title, BraillePresentationPanel)


_register()
