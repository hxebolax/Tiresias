"""Diálogos del núcleo de voz: alfabeto fonético, esquemas de voz y sonido y
plantillas de anuncio por tipo de control.

Todas las funciones públicas deben llamarse desde el hilo de la interfaz.
"""

from __future__ import annotations

import copy
from typing import Any

import wx

from ..config import conf
from ..i18n import _
from ..log import getLogger
from .config_dialogs import _addButtonRow, _ModelessDialog, _showSingleton
from .settings import SettingsBuilder, askYesNo, parentWindow, showError, speakMessageOnCore

log = getLogger("gui.speechDialogs")


# ====================================================================== alfabeto fonético
class PhoneticAlphabetDialog(_ModelessDialog):
	"""Edita las descripciones fonéticas de los caracteres por idioma (#6811)."""

	dialogKey = "phoneticAlphabet"

	def __init__(self, parent: wx.Window | None) -> None:
		super().__init__(parent, _("Alfabeto fonético"))
		from ..speech import languages, symbols

		self._symbols = symbols
		self._languages = symbols.descriptionLanguages()
		self._tables: dict[str, dict[str, str]] = {}
		self.lang = symbols.baseLanguage(languages.interfaceLanguage())
		if self.lang not in self._languages:
			self._languages.append(self.lang)
		self._keys: list[str] = []
		self._updating = False
		main = wx.BoxSizer(wx.VERTICAL)
		b = SettingsBuilder(self, main)
		self.langCtrl = b.addChoice(_("&Idioma:"), [languages.languageName(l) for l in self._languages], self._languages.index(self.lang))
		self.list = b.addLabeledControl(
			_("&Caracteres:"),
			lambda p: wx.ListCtrl(p, style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=(420, 260)),
			vertical=True,
			proportion=1,
		)
		self.list.InsertColumn(0, _("Carácter"), width=90)
		self.list.InsertColumn(1, _("Descripción"), width=300)
		self.descCtrl = b.addText(_("&Descripción del carácter seleccionado:"), size=(300, -1))
		self.addButton, self.removeButton, self.resetButton = _addButtonRow(
			self, main, [(_("&Añadir carácter..."), self._onAdd), (_("&Quitar"), self._onRemove), (_("&Restablecer este idioma"), self._onReset)]
		)
		self._okCancelButtons(main, self._onOk)
		self.langCtrl.Bind(wx.EVT_CHOICE, self._onLanguage)
		self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda evt: self._loadField())
		self.descCtrl.Bind(wx.EVT_TEXT, self._onDesc)
		self._finishLayout(main, (480, 480))
		self._refresh(None)
		self.list.SetFocus()

	def _table(self) -> dict[str, str]:
		if self.lang not in self._tables:
			self._tables[self.lang] = dict(self._symbols.getCharacterDescriptions(self.lang))
		return self._tables[self.lang]

	def _refresh(self, select: str | None) -> None:
		table = self._table()
		self._keys = sorted(table)
		self.list.DeleteAllItems()
		for i, k in enumerate(self._keys):
			self.list.InsertItem(i, k)
			self.list.SetItem(i, 1, table[k])
		if self._keys:
			i = self._keys.index(select) if select in self._keys else 0
			self.list.Select(i)
			self.list.Focus(i)
			self.list.EnsureVisible(i)
		self._loadField()

	def _selected(self) -> str | None:
		i = self.list.GetFirstSelected()
		return self._keys[i] if 0 <= i < len(self._keys) else None

	def _loadField(self) -> None:
		k = self._selected()
		self._updating = True
		try:
			self.descCtrl.Enable(k is not None)
			self.removeButton.Enable(k is not None)
			self.descCtrl.ChangeValue(self._table().get(k, "") if k else "")
		finally:
			self._updating = False

	def _onDesc(self, evt: wx.CommandEvent) -> None:
		if self._updating:
			return
		k = self._selected()
		if k is None:
			return
		self._table()[k] = self.descCtrl.GetValue()
		self.list.SetItem(self._keys.index(k), 1, self.descCtrl.GetValue())

	def _onLanguage(self, evt: wx.CommandEvent) -> None:
		i = self.langCtrl.GetSelection()
		if 0 <= i < len(self._languages):
			self.lang = self._languages[i]
			self._refresh(None)

	def _onAdd(self, evt: wx.CommandEvent) -> None:
		dlg = wx.TextEntryDialog(self, _("Carácter (una sola letra, cifra o símbolo):"), _("Añadir carácter"))
		try:
			if dlg.ShowModal() != wx.ID_OK:
				return
			ch = dlg.GetValue().strip().lower()
		finally:
			dlg.Destroy()
		if len(ch) != 1:
			showError(_("Escriba un solo carácter."), self)
			return
		self._table().setdefault(ch, ch)
		self._refresh(ch)
		self.descCtrl.SetFocus()
		self.descCtrl.SelectAll()

	def _onRemove(self, evt: wx.CommandEvent) -> None:
		k = self._selected()
		if k is None:
			return
		del self._table()[k]
		self._refresh(None)
		self.list.SetFocus()

	def _onReset(self, evt: wx.CommandEvent) -> None:
		if not askYesNo(_("¿Volver al alfabeto fonético de fábrica de este idioma?"), _("Restablecer"), self):
			return
		self._tables[self.lang] = dict(self._symbols.BUILTIN_CHARACTER_DESCRIPTIONS.get(self.lang, {}))
		self._refresh(None)
		self.list.SetFocus()

	def _onOk(self, evt: wx.CommandEvent) -> None:
		for lang, table in self._tables.items():
			try:
				self._symbols.saveUserDescriptions(lang, {k: v for k, v in table.items() if k})
			except OSError as e:
				showError(_("No se pudo guardar el alfabeto fonético: {error}").format(error=e), self)
				return
		self.closeDialog()


def showPhoneticAlphabet() -> None:
	_showSingleton("phoneticAlphabet", lambda: PhoneticAlphabetDialog(parentWindow()))


# ====================================================================== esquemas
class VoiceSchemesDialog(_ModelessDialog):
	"""Crea y edita esquemas de voz y sonido propios."""

	dialogKey = "voiceSchemes"

	def __init__(self, parent: wx.Window | None) -> None:
		super().__init__(parent, _("Esquemas de voz y sonido"))
		from ..audio import tones
		from ..speech import voice_schemes as vs

		self.vs = vs
		self.schemes: dict[str, dict[str, dict]] = copy.deepcopy(vs.userSchemes())
		#: Nombre original de cada esquema que ya existía (los cambios de nombre
		#: y los borrados se aplican al esquema elegido solo al Aceptar).
		self._origins: dict[str, str] = {n: n for n in self.schemes}
		self._originalNames = frozenset(self.schemes)
		#: Funciones que se llaman tras guardar (p. ej. refrescar el panel de Opciones).
		self.onSaved: list = []
		self._sounds = [""] + sorted(tones.availableSounds())
		self._updating = False
		main = wx.BoxSizer(wx.VERTICAL)
		b = SettingsBuilder(self, main)
		self.schemeList = b.addLabeledControl(_("&Esquemas propios:"), lambda p: wx.ListBox(p, size=(300, 110)), vertical=True)
		self.newButton, self.copyButton, self.renameButton, self.deleteButton = _addButtonRow(
			self,
			main,
			[(_("&Nuevo..."), self._onNew), (_("&Copiar de uno de fábrica..."), self._onCopy), (_("Ca&mbiar nombre..."), self._onRename), (_("&Borrar"), self._onDelete)],
		)
		g = b.group(_("Atributo del esquema seleccionado"))
		# Texto, colores, tipos de control y estados (foros 2.4, #4089).
		self.attrCtrl = g.addChoice(_("&Atributo:"), [vs.ATTRIBUTE_LABELS[a] for a in vs.ATTRIBUTES], 0)
		self.pitchCtrl = g.addSpin(_("&Tono (cambio en porcentaje):"), -80, 80, 0)
		self.rateCtrl = g.addSpin(_("&Velocidad (cambio en porcentaje):"), -80, 200, 0)
		self.volumeCtrl = g.addSpin(_("V&olumen (cambio en porcentaje):"), -90, 0, 0)
		self.soundCtrl = g.addChoice(_("&Sonido:"), [_("(ninguno)")] + self._sounds[1:], 0)
		self.replaceCtrl = g.addCheckBox(_("El sonido sustituye a la &palabra («enlace», «botón», «marcado»...)"))
		self._okCancelButtons(main, self._onOk)
		self.schemeList.Bind(wx.EVT_LISTBOX, lambda evt: self._loadAttr())
		self.attrCtrl.Bind(wx.EVT_CHOICE, lambda evt: self._loadAttr())
		for c in (self.pitchCtrl, self.rateCtrl, self.volumeCtrl):
			c.Bind(wx.EVT_SPINCTRL, self._onChange)
			c.Bind(wx.EVT_TEXT, self._onChange)
		self.soundCtrl.Bind(wx.EVT_CHOICE, self._onChange)
		self.replaceCtrl.Bind(wx.EVT_CHECKBOX, self._onChange)
		self._finishLayout(main, (520, 520))
		self._refresh(None)
		self.schemeList.SetFocus()

	def _names(self) -> list[str]:
		return sorted(self.schemes)

	def _selected(self) -> str | None:
		i = self.schemeList.GetSelection()
		names = self._names()
		return names[i] if 0 <= i < len(names) else None

	def _refresh(self, select: str | None) -> None:
		names = self._names()
		self.schemeList.Set(names)
		if names:
			self.schemeList.SetSelection(names.index(select) if select in names else 0)
		self._loadAttr()

	def _attr(self) -> str:
		return self.vs.ATTRIBUTES[max(0, self.attrCtrl.GetSelection())]

	def _loadAttr(self) -> None:
		name = self._selected()
		has = name is not None
		for c in (self.attrCtrl, self.pitchCtrl, self.rateCtrl, self.volumeCtrl, self.soundCtrl, self.replaceCtrl, self.renameButton, self.deleteButton):
			c.Enable(has)
		self._updating = True
		try:
			style = self.schemes.get(name, {}).get(self._attr(), {}) if has else {}
			self.pitchCtrl.SetValue(int(style.get("pitch", 0) or 0))
			self.rateCtrl.SetValue(int(style.get("rate", 0) or 0))
			self.volumeCtrl.SetValue(int(style.get("volume", 0) or 0))
			sound = style.get("sound", "")
			self.soundCtrl.SetSelection(self._sounds.index(sound) if sound in self._sounds else 0)
			self.replaceCtrl.SetValue(bool(style.get("replaceLabel", False)))
		finally:
			self._updating = False

	def _onChange(self, evt: wx.CommandEvent) -> None:
		if self._updating:
			return
		name = self._selected()
		if name is None:
			return
		style: dict[str, Any] = {}
		for key, ctrl in (("pitch", self.pitchCtrl), ("rate", self.rateCtrl), ("volume", self.volumeCtrl)):
			if ctrl.GetValue():
				style[key] = int(ctrl.GetValue())
		sound = self._sounds[max(0, self.soundCtrl.GetSelection())]
		if sound:
			style["sound"] = sound
			if self.replaceCtrl.GetValue():
				style["replaceLabel"] = True
		scheme = self.schemes.setdefault(name, {})
		if style:
			scheme[self._attr()] = style
		else:
			scheme.pop(self._attr(), None)

	def _askName(self, title: str, value: str = "") -> str | None:
		dlg = wx.TextEntryDialog(self, _("Nombre del esquema:"), title, value)
		try:
			if dlg.ShowModal() != wx.ID_OK:
				return None
			name = dlg.GetValue().strip()
		finally:
			dlg.Destroy()
		if not name:
			return None
		if name in self.schemes or name in self.vs.BUILTIN_SCHEMES:
			showError(_("Ya existe un esquema con ese nombre."), self)
			return None
		return name

	def _onNew(self, evt: wx.CommandEvent) -> None:
		name = self._askName(_("Nuevo esquema"))
		if name:
			self.schemes[name] = {}
			self._refresh(name)
			self.attrCtrl.SetFocus()

	def _onCopy(self, evt: wx.CommandEvent) -> None:
		keys = list(self.vs.BUILTIN_SCHEMES)
		dlg = wx.SingleChoiceDialog(self, _("Esquema de fábrica que se copia:"), _("Copiar esquema"), [self.vs.BUILTIN_LABELS[k] for k in keys])
		try:
			if dlg.ShowModal() != wx.ID_OK:
				return
			src = keys[dlg.GetSelection()]
		finally:
			dlg.Destroy()
		name = self._askName(_("Nombre de la copia"), self.vs.BUILTIN_LABELS[src].split(" (")[0] + " " + _("(copia)"))
		if name:
			self.schemes[name] = copy.deepcopy(self.vs.BUILTIN_SCHEMES[src])
			self._refresh(name)

	def _onRename(self, evt: wx.CommandEvent) -> None:
		old = self._selected()
		if old is None:
			return
		new = self._askName(_("Cambiar nombre"), old)
		if new:
			self.schemes[new] = self.schemes.pop(old)
			if old in self._origins:
				self._origins[new] = self._origins.pop(old)
			self._refresh(new)

	def _onDelete(self, evt: wx.CommandEvent) -> None:
		name = self._selected()
		if name is None or not askYesNo(_("¿Borrar el esquema «{name}»?").format(name=name), _("Borrar esquema"), self):
			return
		del self.schemes[name]
		self._origins.pop(name, None)
		self._refresh(None)
		self.schemeList.SetFocus()

	def _onOk(self, evt: wx.CommandEvent) -> None:
		try:
			self.vs.saveUserSchemes(self.schemes)
		except OSError as e:
			showError(_("No se pudieron guardar los esquemas: {error}").format(error=e), self)
			return
		# El esquema elegido sigue al cambio de nombre o se quita si se borró.
		current = conf["speech"]["voiceScheme"]
		if current and current in self._originalNames:
			renamed = next((n for n, o in self._origins.items() if o == current), None)
			target = renamed if renamed is not None else (current if current in self.schemes else "")
			if target != current:
				conf["speech"]["voiceScheme"] = target
		callbacks = list(self.onSaved)
		self.closeDialog()
		for func in callbacks:
			try:
				func()
			except Exception:
				log.exception("Error al avisar del cambio de esquemas")


def showVoiceSchemes(onClose: Any = None) -> None:
	"""Abre el editor de esquemas; ``onClose`` se llama tras guardar con Aceptar."""
	dlg = _showSingleton("voiceSchemes", lambda: VoiceSchemesDialog(parentWindow()))
	if onClose is not None and onClose not in dlg.onSaved:
		dlg.onSaved.append(onClose)


# ====================================================================== plantillas
class RoleTemplatesDialog(_ModelessDialog):
	"""Plantillas de anuncio por tipo de control (#7232, #17483)."""

	dialogKey = "roleTemplates"

	def __init__(self, parent: wx.Window | None) -> None:
		super().__init__(parent, _("Plantillas de anuncio de controles"))
		from ..objects.roles import ROLE_LABELS
		from ..speech import verbosity

		self.verbosity = verbosity
		self.templates = dict(verbosity.getTemplates())
		self._roles = sorted(
			((verbosity.roleKey(r), lbl) for r, lbl in ROLE_LABELS.items() if lbl),
			key=lambda kv: kv[1].lower(),
		)
		self._updating = False
		main = wx.BoxSizer(wx.VERTICAL)
		b = SettingsBuilder(self, main)
		b.addStaticText(
			_("Marcadores: {name} nombre, {role} tipo, {value} valor, {states} estados, {description} descripción, {shortcut} tecla de acceso, {position} posición, {level} nivel. Lo que no aparezca en la plantilla no se dice. Deje la plantilla vacía para usar el orden general.")
		)
		self.list = b.addLabeledControl(
			_("&Tipos de control:"),
			lambda p: wx.ListCtrl(p, style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=(520, 260)),
			vertical=True,
			proportion=1,
		)
		self.list.InsertColumn(0, _("Tipo"), width=200)
		self.list.InsertColumn(1, _("Plantilla"), width=300)
		self.templateCtrl = b.addText(_("&Plantilla del tipo seleccionado:"), size=(400, -1))
		self.exampleCtrl = b.addText(_("Ejemplo:"), style=wx.TE_READONLY, size=(400, -1))
		self.clearButton, self.clearAllButton = _addButtonRow(
			self, main, [(_("&Usar el orden general"), self._onClear), (_("&Quitar todas las plantillas"), self._onClearAll)]
		)
		self._okCancelButtons(main, self._onOk)
		self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda evt: self._load())
		self.templateCtrl.Bind(wx.EVT_TEXT, self._onText)
		self._finishLayout(main, (600, 520))
		self._refresh(0)
		self.list.SetFocus()

	def _refresh(self, select: int) -> None:
		self.list.DeleteAllItems()
		for i, (key, label) in enumerate(self._roles):
			self.list.InsertItem(i, label)
			self.list.SetItem(i, 1, self.templates.get(key, ""))
		if self._roles:
			select = max(0, min(select, len(self._roles) - 1))
			self.list.Select(select)
			self.list.Focus(select)
			self.list.EnsureVisible(select)
		self._load()

	def _index(self) -> int:
		return self.list.GetFirstSelected()

	def _load(self) -> None:
		i = self._index()
		self._updating = True
		try:
			key = self._roles[i][0] if 0 <= i < len(self._roles) else None
			self.templateCtrl.ChangeValue(self.templates.get(key, "") if key else "")
			self._example()
		finally:
			self._updating = False

	def _example(self) -> None:
		i = self._index()
		if not 0 <= i < len(self._roles):
			self.exampleCtrl.SetValue("")
			return
		template = self.templateCtrl.GetValue()
		err = self.verbosity.validateTemplate(template) if template.strip() else None
		if err:
			self.exampleCtrl.SetValue(err)
			return
		label = self._roles[i][1]
		props = {
			"name": _("Aceptar"),
			"role": label,
			"value": _("valor"),
			"states": _("marcado"),
			"description": _("descripción"),
			"shortcut": "Alt+ a",
			"position": _("2 de 5"),
			"level": "2",
		}
		if template.strip():
			import string

			class _D(dict):
				def __missing__(self, k: str) -> str:
					return ""

			text = string.Formatter().vformat(template, (), _D(props))
		else:
			text = " ".join(props[p] for p in self.verbosity.getOrder() if props.get(p))
		self.exampleCtrl.SetValue(" ".join(text.split()))

	def _onText(self, evt: wx.CommandEvent) -> None:
		if self._updating:
			return
		i = self._index()
		if not 0 <= i < len(self._roles):
			return
		key = self._roles[i][0]
		value = self.templateCtrl.GetValue()
		if value.strip():
			self.templates[key] = value
		else:
			self.templates.pop(key, None)
		self.list.SetItem(i, 1, value)
		self._example()

	def _onClear(self, evt: wx.CommandEvent) -> None:
		self.templateCtrl.SetValue("")
		self.templateCtrl.SetFocus()

	def _onClearAll(self, evt: wx.CommandEvent) -> None:
		if not self.templates or not askYesNo(_("¿Quitar todas las plantillas?"), _("Plantillas"), self):
			return
		self.templates.clear()
		self._refresh(self._index())

	def _onOk(self, evt: wx.CommandEvent) -> None:
		for key, template in self.templates.items():
			err = self.verbosity.validateTemplate(template)
			if err:
				label = dict(self._roles).get(key, key)
				showError(_("Plantilla de «{role}»: {error}").format(role=label, error=err), self)
				return
		conf["presentation"]["roleTemplates"] = dict(self.templates)
		speakMessageOnCore(_("Plantillas guardadas"))
		self.closeDialog()


def showRoleTemplates() -> None:
	_showSingleton("roleTemplates", lambda: RoleTemplatesDialog(parentWindow()))
