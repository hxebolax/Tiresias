"""Diálogos de configuración de Tiresias.

Contiene los perfiles de configuración, el administrador de complementos,
los gestos de entrada, los diccionarios de pronunciación, la puntuación y
los símbolos, el diálogo de bienvenida y «Acerca de».

Todas las funciones públicas deben llamarse desde el hilo de la interfaz.
Lo que toca objetos de accesibilidad o el núcleo se encola con
:mod:`tiresias.queue_handler`.
"""

from __future__ import annotations

import os
import sys
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable

import wx

from . import message_dialog
from .. import APP_NAME, COPYRIGHT, VERSION, paths, queue_handler
from ..config import conf, isValidProfileName, post_configProfileSwitch
from ..i18n import _
from ..log import getLogger
from .settings import (
	SettingsBuilder,
	askYesNo,
	getSettingsDialog,
	isAlive,
	parentWindow,
	presentDialog,
	runInThread,
	runOnCore,
	showError,
	showSettings,
	speakMessageOnCore,
)

log = getLogger("gui.configDialogs")

_dialogs: dict[str, wx.Dialog] = {}


def _existing(key: str) -> wx.Dialog | None:
	dlg = _dialogs.get(key)
	if dlg is not None and isAlive(dlg):
		return dlg
	_dialogs.pop(key, None)
	return None


def _showSingleton(key: str, factory: Callable[[], wx.Dialog]) -> wx.Dialog:
	dlg = _existing(key)
	if dlg is None:
		dlg = factory()
		_dialogs[key] = dlg
	presentDialog(dlg)
	return dlg


def _saveConfig() -> None:
	"""Guarda la configuración en el hilo del núcleo."""

	def save() -> None:
		try:
			conf.save()
		except Exception:
			log.exception("No se pudo guardar la configuración")

	queue_handler.queueFunction(save)


def _ownProcessNames() -> set[str]:
	names = {"python", "pythonw", APP_NAME.lower()}
	names.add(os.path.splitext(os.path.basename(sys.executable))[0].lower())
	return names


def _focusAppName() -> str | None:
	"""Nombre del módulo de aplicación del foco (hilo del núcleo)."""
	from .. import api

	focus = api.getFocusObject()
	if focus is None:
		return None
	app = focus.appModule
	name = getattr(app, "appName", None) if app is not None else None
	if not name or name.lower() in _ownProcessNames():
		return None
	return name


class _ModelessDialog(wx.Dialog):
	"""Diálogo no modal que se registra como único y se destruye al cerrarse."""

	dialogKey = ""

	def __init__(self, parent: wx.Window | None, title: str) -> None:
		super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.Bind(wx.EVT_CLOSE, self._onCloseEvent)

	def _onCloseEvent(self, evt: wx.CloseEvent) -> None:
		self.onCancel()

	def onCancel(self) -> None:
		self.closeDialog()

	def closeDialog(self) -> None:
		if _dialogs.get(self.dialogKey) is self:
			_dialogs.pop(self.dialogKey, None)
		self.Hide()
		self.Destroy()

	def _finishLayout(self, main: wx.Sizer, minSize: tuple[int, int] | None = None) -> None:
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(main, 1, wx.EXPAND | wx.ALL, 10)
		self.SetSizer(outer)
		outer.Fit(self)
		if minSize:
			size = self.GetSize()
			self.SetSize((max(size[0], minSize[0]), max(size[1], minSize[1])))
		self.CentreOnScreen()

	def _okCancelButtons(self, main: wx.Sizer, onOk: Callable[[wx.CommandEvent], None]) -> tuple[wx.Button, wx.Button]:
		buttons = wx.StdDialogButtonSizer()
		ok = wx.Button(self, wx.ID_OK, _("Aceptar"))
		cancel = wx.Button(self, wx.ID_CANCEL, _("Cancelar"))
		buttons.AddButton(ok)
		buttons.AddButton(cancel)
		buttons.Realize()
		main.Add(buttons, 0, wx.ALIGN_RIGHT | wx.TOP, 8)
		ok.SetDefault()
		self.SetAffirmativeId(wx.ID_OK)
		self.SetEscapeId(wx.ID_CANCEL)
		ok.Bind(wx.EVT_BUTTON, onOk)
		cancel.Bind(wx.EVT_BUTTON, lambda evt: self.onCancel())
		return ok, cancel

	def _closeButton(self, sizer: wx.Sizer) -> wx.Button:
		btn = wx.Button(self, wx.ID_CLOSE, _("&Cerrar"))
		sizer.Add(btn, 0, wx.ALIGN_RIGHT | wx.TOP, 8)
		btn.SetDefault()
		self.SetEscapeId(wx.ID_CLOSE)
		btn.Bind(wx.EVT_BUTTON, lambda evt: self.onCancel())
		return btn


def _addButtonRow(parent: wx.Window, sizer: wx.Sizer, specs: list[tuple[str, Callable[[wx.CommandEvent], None]]]) -> list[wx.Button]:
	row = wx.BoxSizer(wx.HORIZONTAL)
	buttons = []
	for label, handler in specs:
		btn = wx.Button(parent, label=label)
		btn.Bind(wx.EVT_BUTTON, handler)
		row.Add(btn, 0, wx.RIGHT, 6)
		buttons.append(btn)
	sizer.Add(row, 0, wx.TOP | wx.BOTTOM, 4)
	return buttons


# ====================================================================== perfiles
def _triggerLabel(trigger: str) -> str:
	if trigger == "sayAll":
		return _("Lectura continua")
	if trigger.startswith("app:"):
		return _("Aplicación {app}").format(app=trigger[4:])
	if trigger.startswith("dominio:"):
		return _("Sitio web {domain}").format(domain=trigger[len("dominio:"):])
	return trigger


def _currentDomain() -> str:
	try:
		from .. import domain_profiles

		return domain_profiles.currentDomain or ""
	except Exception:
		return ""


def askDomain(parent: wx.Window, default: str = "") -> str | None:
	"""Pide un dominio web («ejemplo.com»). ``None`` si se cancela."""
	from ..config import normalizeDomain

	dlg = wx.TextEntryDialog(
		parent,
		_("Dominio del sitio web (por ejemplo, ejemplo.com). También se aplica a sus subdominios:"),
		_("Perfil para un sitio web"),
		default or _currentDomain(),
	)
	try:
		if dlg.ShowModal() != wx.ID_OK:
			return None
		domain = normalizeDomain(dlg.GetValue())
	finally:
		dlg.Destroy()
	if not domain or " " in domain or "." not in domain:
		showError(_("Escriba un dominio válido, por ejemplo ejemplo.com."), parent)
		return None
	return domain


class NewProfileDialog(wx.Dialog):
	"""Pide el nombre y el disparador de un perfil nuevo (modal)."""

	def __init__(self, parent: wx.Window, appName: str | None) -> None:
		super().__init__(parent, title=_("Nuevo perfil"))
		main = wx.BoxSizer(wx.VERTICAL)
		b = SettingsBuilder(self, main)
		self.nameCtrl = b.addText(_("&Nombre del perfil:"), size=(300, -1))
		self._triggers: list[str | None] = [None]
		labels = [_("Activar manualmente")]
		if appName:
			self._triggers.append(f"app:{appName}")
			labels.append(_("Al usar la aplicación actual ({app})").format(app=appName))
		self._triggers.append("sayAll")
		labels.append(_("Durante la lectura continua"))
		self._triggers.append("dominio:")
		domain = _currentDomain()
		labels.append(_("Al visitar un sitio web ({domain})...").format(domain=domain) if domain else _("Al visitar un sitio web..."))
		self.triggerCtrl = b.addChoice(_("&Usar este perfil:"), labels, 0)
		self._copyNames: list[str | None] = [None] + sorted(conf.profiles, key=str.lower)
		self.copyCtrl = b.addChoice(
			_("&Copiar los ajustes de:"), [_("(ninguno: perfil vacío)")] + [n for n in self._copyNames if n], 0
		)
		buttons = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
		main.Add(buttons, 0, wx.EXPAND | wx.TOP, 8)
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(main, 1, wx.EXPAND | wx.ALL, 10)
		self.SetSizer(outer)
		outer.Fit(self)
		self.FindWindow(wx.ID_OK).SetLabel(_("Aceptar"))
		self.FindWindow(wx.ID_CANCEL).SetLabel(_("Cancelar"))
		self.Bind(wx.EVT_BUTTON, self._onOk, id=wx.ID_OK)
		self.CentreOnParent()
		self.nameCtrl.SetFocus()

	@property
	def profileName(self) -> str:
		return self.nameCtrl.GetValue().strip()

	@property
	def trigger(self) -> str | None:
		i = self.triggerCtrl.GetSelection()
		return self._triggers[i] if 0 <= i < len(self._triggers) else None

	@property
	def copyFrom(self) -> str | None:
		i = self.copyCtrl.GetSelection()
		return self._copyNames[i] if 0 <= i < len(self._copyNames) else None

	def _onOk(self, evt: wx.CommandEvent) -> None:
		name = self.profileName
		if not isValidProfileName(name):
			showError(_("El nombre del perfil no es válido. No puede estar vacío ni contener \\ / : * ? \" < > |"), self)
			self.nameCtrl.SetFocus()
			return
		if name in conf.profiles:
			showError(_("Ya existe un perfil con ese nombre."), self)
			self.nameCtrl.SetFocus()
			return
		evt.Skip()


class TriggersDialog(wx.Dialog):
	"""Edita qué perfil se activa con cada disparador (modal)."""

	def __init__(self, parent: wx.Window, appName: str | None) -> None:
		super().__init__(parent, title=_("Disparadores de perfiles"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.triggers: dict[str, str] = dict(conf.triggers)
		order = []
		if appName:
			order.append(f"app:{appName}")
		order.append("sayAll")
		order += sorted(t for t in self.triggers if t not in order)
		self._order = order
		self._profiles: list[str | None] = [None] + sorted(conf.profiles, key=str.lower)
		main = wx.BoxSizer(wx.VERTICAL)
		b = SettingsBuilder(self, main)
		self.list = b.addLabeledControl(
			_("&Disparadores:"),
			lambda p: wx.ListBox(p, choices=[self._itemLabel(t) for t in order], size=(420, 180)),
			vertical=True,
			proportion=1,
		)
		self.profileCtrl = b.addChoice(
			_("&Perfil:"), [_("(configuración normal)")] + [n for n in self._profiles if n], 0
		)
		_addButtonRow(self, main, [(_("Añadir un &sitio web..."), self._onAddDomain), (_("&Quitar el disparador"), self._onRemoveTrigger)])
		buttons = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
		main.Add(buttons, 0, wx.EXPAND | wx.TOP, 8)
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(main, 1, wx.EXPAND | wx.ALL, 10)
		self.SetSizer(outer)
		outer.Fit(self)
		self.FindWindow(wx.ID_OK).SetLabel(_("Aceptar"))
		self.FindWindow(wx.ID_CANCEL).SetLabel(_("Cancelar"))
		self.list.Bind(wx.EVT_LISTBOX, lambda evt: self._syncChoice())
		self.profileCtrl.Bind(wx.EVT_CHOICE, self._onProfile)
		if order:
			self.list.SetSelection(0)
		self._syncChoice()
		self.CentreOnParent()
		self.list.SetFocus()

	def _itemLabel(self, trigger: str) -> str:
		profile = self.triggers.get(trigger)
		return f"{_triggerLabel(trigger)}: {profile or _('(configuración normal)')}"

	def _syncChoice(self) -> None:
		i = self.list.GetSelection()
		if not 0 <= i < len(self._order):
			return
		profile = self.triggers.get(self._order[i])
		self.profileCtrl.SetSelection(self._profiles.index(profile) if profile in self._profiles else 0)

	def _onAddDomain(self, evt: wx.CommandEvent) -> None:
		domain = askDomain(self)
		if domain is None:
			return
		trigger = "dominio:" + domain
		if trigger not in self._order:
			self._order.append(trigger)
			self.list.Append(self._itemLabel(trigger))
		i = self._order.index(trigger)
		self.list.SetSelection(i)
		self._syncChoice()
		self.profileCtrl.SetFocus()

	def _onRemoveTrigger(self, evt: wx.CommandEvent) -> None:
		i = self.list.GetSelection()
		if not 0 <= i < len(self._order):
			return
		trigger = self._order[i]
		self.triggers.pop(trigger, None)
		if trigger.startswith("dominio:"):
			del self._order[i]
			self.list.Delete(i)
			if self._order:
				self.list.SetSelection(min(i, len(self._order) - 1))
		else:
			self.list.SetString(i, self._itemLabel(trigger))
		self._syncChoice()
		self.list.SetFocus()

	def _onProfile(self, evt: wx.CommandEvent) -> None:
		i = self.list.GetSelection()
		if not 0 <= i < len(self._order):
			return
		trigger = self._order[i]
		profile = self._profiles[self.profileCtrl.GetSelection()]
		if profile:
			self.triggers[trigger] = profile
		else:
			self.triggers.pop(trigger, None)
		self.list.SetString(i, self._itemLabel(trigger))


class ProfilesDialog(_ModelessDialog):
	dialogKey = "profiles"

	def __init__(self, parent: wx.Window | None, appName: str | None = None) -> None:
		super().__init__(parent, _("Perfiles de configuración"))
		self.appName = appName
		self._names: list[str | None] = []
		self._editing: str | None = None
		self._prevManual: str | None = None
		#: Diccionarios de otros perfiles abiertos ({"name", "prev"} de cada uno).
		self._dictEdits: list[dict[str, str | None]] = []
		main = wx.BoxSizer(wx.VERTICAL)
		b = SettingsBuilder(self, main)
		self.list = b.addLabeledControl(
			_("&Perfiles:"), lambda p: wx.ListBox(p, style=wx.LB_SINGLE, size=(420, 200)), vertical=True, proportion=1
		)
		(
			self.activateButton,
			self.newButton,
			self.renameButton,
			self.deleteButton,
			self.triggersButton,
			self.editButton,
		) = _addButtonRow(
			self,
			main,
			[
				(_("&Activar manualmente"), self._onActivate),
				(_("&Nuevo..."), self._onNew),
				(_("Ca&mbiar nombre..."), self._onRename),
				(_("&Eliminar"), self._onDelete),
				(_("&Disparadores..."), self._onTriggers),
				(_("Ed&itar"), self._onEdit),
			],
		)
		# Activar o desactivar cada perfil por separado (#14593) y perfiles de solo lectura.
		self.enableButton, self.readOnlyButton, self.dictButton = _addButtonRow(
			self,
			main,
			[
				(_("Desactivar e&ste perfil"), self._onToggleEnabled),
				(_("Solo &lectura"), self._onToggleReadOnly),
				(_("Diccionari&o del perfil..."), self._onProfileDict),
			],
		)
		self.disableTriggers = b.addCheckBox(_("Desactivar &temporalmente todos los disparadores"), not conf.triggersEnabled)
		self.disableTriggers.Bind(wx.EVT_CHECKBOX, self._onDisableTriggers)
		self._closeButton(main)
		self.list.Bind(wx.EVT_LISTBOX, lambda evt: self._updateButtons())
		self.list.Bind(wx.EVT_LISTBOX_DCLICK, self._onActivate)
		self._finishLayout(main, (520, 380))
		self.refresh(conf.activeProfileName)
		self.list.SetFocus()
		if appName is None:
			runOnCore(_focusAppName, callback=self._setAppName)

	def _setAppName(self, name: str | None) -> None:
		if isAlive(self) and name and not self.appName:
			self.appName = name

	# --------------------------------------------------- lista
	def _label(self, name: str | None) -> str:
		states = []
		if name is None:
			label = _("(configuración normal)")
			if conf.activeProfileName is None:
				states.append(_("activa"))
		else:
			label = name
			if conf.manualProfile == name:
				states.append(_("activado manualmente"))
			if name in conf.triggeredProfiles and conf.triggersEnabled and conf.isProfileEnabled(name):
				states.append(_("activado por disparador"))
			if not conf.isProfileEnabled(name):
				states.append(_("desactivado"))
			if conf.isProfileReadOnly(name):
				states.append(_("solo lectura"))
			triggers = [_triggerLabel(t) for t, p in conf.triggers.items() if p == name]
			if triggers:
				states.append(_("disparadores: {list}").format(list=", ".join(triggers)))
		if self._editing is not None and name == self._editing:
			states.append(_("en edición"))
		return ", ".join([label] + states)

	def refresh(self, select: str | None = None) -> None:
		if not isAlive(self):
			return
		self._names = [None] + sorted(conf.profiles, key=str.lower)
		self.list.Set([self._label(n) for n in self._names])
		index = self._names.index(select) if select in self._names else 0
		self.list.SetSelection(index)
		self._updateButtons()

	def _selected(self) -> str | None:
		i = self.list.GetSelection()
		return self._names[i] if 0 <= i < len(self._names) else None

	def _updateButtons(self) -> None:
		name = self._selected()
		isProfile = name is not None
		if isProfile and conf.manualProfile == name:
			self.activateButton.SetLabel(_("Des&activar"))
		else:
			self.activateButton.SetLabel(_("&Activar manualmente"))
		self.activateButton.Enable(isProfile or conf.manualProfile is not None)
		self.renameButton.Enable(isProfile)
		self.deleteButton.Enable(isProfile)
		self.enableButton.Enable(isProfile)
		self.readOnlyButton.Enable(isProfile)
		self.dictButton.Enable(isProfile)
		if isProfile:
			self.enableButton.SetLabel(_("Desactivar e&ste perfil") if conf.isProfileEnabled(name) else _("Activar e&ste perfil"))
			self.readOnlyButton.SetLabel(_("Pe&rmitir cambios") if conf.isProfileReadOnly(name) else _("Solo &lectura"))
		self.Layout()

	# --------------------------------------------------- acciones
	def _onActivate(self, evt: wx.CommandEvent) -> None:
		name = self._selected()
		if name is None or conf.manualProfile == name:
			conf.setManualProfile(None)
		else:
			conf.setManualProfile(name)
		self.refresh(name)

	def _onNew(self, evt: wx.CommandEvent) -> None:
		dlg = NewProfileDialog(self, self.appName)
		try:
			if dlg.ShowModal() != wx.ID_OK:
				return
			name, trigger = dlg.profileName, dlg.trigger
		finally:
			copyFrom = dlg.copyFrom
			dlg.Destroy()
		if trigger == "dominio:":
			domain = askDomain(self)
			if domain is None:
				return
			trigger = "dominio:" + domain
		manual = trigger is None
		if trigger and trigger in conf.triggers and conf.triggers[trigger] in conf.profiles:
			if not askYesNo(
				_("El disparador «{trigger}» ya usa el perfil «{profile}». ¿Desea sustituirlo?").format(
					trigger=_triggerLabel(trigger), profile=conf.triggers[trigger]
				),
				_("Nuevo perfil"),
				self,
			):
				trigger = None
		try:
			conf.createProfile(name, copyFrom)
		except (ValueError, OSError) as e:
			showError(_("No se pudo crear el perfil: {error}").format(error=e), self)
			return
		if trigger:
			conf.setTrigger(trigger, name)
		elif manual:
			conf.setManualProfile(name)
		self.refresh(name)

	def _onRename(self, evt: wx.CommandEvent) -> None:
		old = self._selected()
		if old is None:
			return
		dlg = wx.TextEntryDialog(self, _("Nuevo nombre del perfil:"), _("Cambiar nombre del perfil"), old)
		try:
			if dlg.ShowModal() != wx.ID_OK:
				return
			new = dlg.GetValue().strip()
		finally:
			dlg.Destroy()
		if new == old:
			return
		if not isValidProfileName(new) or new in conf.profiles:
			showError(_("El nombre no es válido o ya existe un perfil con ese nombre."), self)
			return
		try:
			conf.renameProfile(old, new)
		except (ValueError, OSError, KeyError) as e:
			showError(_("No se pudo cambiar el nombre: {error}").format(error=e), self)
			return
		if self._editing == old:
			self._editing = new
			conf.editProfile = new
		# El perfil manual que se restaura al terminar la edición también cambia de nombre.
		if self._prevManual == old:
			self._prevManual = new
		for state in self._dictEdits:
			for key in ("name", "prev"):
				if state[key] == old:
					state[key] = new
		openDict = _existing("dict-profile")
		if openDict is not None and getattr(openDict, "profileName", None) == old:
			openDict.profileName = new
		self.refresh(new)

	def _onDelete(self, evt: wx.CommandEvent) -> None:
		name = self._selected()
		if name is None:
			return
		if self._editing == name:
			showError(_("No se puede eliminar un perfil mientras se está editando."), self)
			return
		if not askYesNo(_("¿Seguro que desea eliminar el perfil «{name}»?").format(name=name), _("Eliminar perfil"), self):
			return
		conf.deleteProfile(name)
		self.refresh(None)

	def _onTriggers(self, evt: wx.CommandEvent) -> None:
		dlg = TriggersDialog(self, self.appName)
		try:
			if dlg.ShowModal() != wx.ID_OK:
				return
			newTriggers = dict(dlg.triggers)
		finally:
			dlg.Destroy()
		for trigger in list(conf.triggers):
			if trigger not in newTriggers:
				conf.setTrigger(trigger, None)
		for trigger, profile in newTriggers.items():
			conf.setTrigger(trigger, profile)
		self.refresh(self._selected())

	def _onEdit(self, evt: wx.CommandEvent) -> None:
		if getSettingsDialog() is not None:
			showError(_("Cierre primero el diálogo de opciones."), self)
			return
		name = self._selected()
		self._prevManual = conf.manualProfile
		if name is None:
			if conf.activeProfileName is not None:
				showError(
					_("Para editar la configuración normal, desactive primero los perfiles activos (o desactive temporalmente los disparadores)."),
					self,
				)
				return
			conf.editProfile = None
		else:
			conf.editProfile = name
			if conf.activeProfileName != name:
				# Se activa mientras se edita para que el diálogo muestre sus valores.
				conf.setManualProfile(name)
		self._editing = name
		self.refresh(name)
		showSettings(onClose=self._onSettingsClosed)

	def _onSettingsClosed(self) -> None:
		editing = self._editing
		self._editing = None
		conf.editProfile = None
		if editing is not None and conf.manualProfile != self._prevManual:
			conf.setManualProfile(self._prevManual)
		if isAlive(self):
			self.refresh(editing)

	def _onToggleEnabled(self, evt: wx.CommandEvent) -> None:
		name = self._selected()
		if name is None:
			return
		enabled = not conf.isProfileEnabled(name)
		conf.setProfileEnabled(name, enabled)
		speakMessageOnCore(_("Perfil {name} activado").format(name=name) if enabled else _("Perfil {name} desactivado: sus disparadores no lo activarán").format(name=name))
		self.refresh(name)

	def _onToggleReadOnly(self, evt: wx.CommandEvent) -> None:
		name = self._selected()
		if name is None:
			return
		readOnly = not conf.isProfileReadOnly(name)

		def apply() -> str | None:
			# En el núcleo y en orden: primero se guarda lo pendiente y después se
			# protege (si se marcara antes, conf.save() se saltaría el perfil).
			profile = conf.profiles.get(name)
			if profile is None:
				return None
			if readOnly and profile.dirty:
				try:
					conf.save()
				except Exception as e:
					log.exception("No se pudo guardar el perfil antes de protegerlo")
					return str(e) or e.__class__.__name__
			conf.setProfileReadOnly(name, readOnly)
			return None

		def done(error: str | None) -> None:
			if not isAlive(self):
				return
			if error:
				showError(_("No se pudo guardar el perfil antes de marcarlo de solo lectura: {error}").format(error=error), self)
			self.refresh(name)

		runOnCore(apply, callback=done)

	def _onProfileDict(self, evt: wx.CommandEvent) -> None:
		name = self._selected()
		if name is None:
			return
		from ..speech import dictionaries

		# Solo puede haber un diccionario de perfil abierto (todos editan el mismo
		# diccionario en memoria, el del perfil activo).
		existing = _existing("dict-profile")
		if existing is not None:
			if getattr(existing, "profileName", None) != name:
				showError(_("Ya está abierto el diccionario del perfil «{name}». Ciérrelo antes de abrir el de otro perfil.").format(name=getattr(existing, "profileName", "")), self)
			presentDialog(existing)
			return
		dictionaries.ensureProfileDict()
		if conf.activeProfileName != name:
			# El diccionario de otro perfil se edita activándolo mientras dura la edición.
			# Nombre y perfil manual anterior en un diccionario: si se cambia el
			# nombre de alguno mientras dura la edición, _onRename los actualiza.
			state = {"name": name, "prev": conf.manualProfile}
			edits = self._dictEdits
			edits.append(state)
			conf.setManualProfile(name)
			dictionaries.ensureProfileDict()
			dlg = SpeechDictDialog(self, "profile")
			_dialogs[dlg.dialogKey] = dlg
			dlgId = dlg.GetId()

			def onDestroy(evt: wx.WindowDestroyEvent) -> None:
				evt.Skip()
				# Durante la destrucción GetEventObject() es otro objeto Python
				# (un wx.Window genérico): se compara por identificador.
				if evt.GetId() != dlgId:
					return
				if state in edits:
					edits.remove(state)
				if conf.manualProfile == state["name"]:
					conf.setManualProfile(state["prev"])
					if isAlive(self):
						self.refresh(state["name"])

			dlg.Bind(wx.EVT_WINDOW_DESTROY, onDestroy)
			presentDialog(dlg)
			self.refresh(name)
			return
		showSpeechDictionary("profile")

	def _onDisableTriggers(self, evt: wx.CommandEvent) -> None:
		conf.triggersEnabled = not self.disableTriggers.GetValue()
		post_configProfileSwitch.notify()
		self.refresh(self._selected())

	def onCancel(self) -> None:
		# Si el diálogo de opciones sigue editando un perfil, la edición se
		# termina (y se restaura el perfil manual) cuando ese diálogo se cierra.
		_saveConfig()
		self.closeDialog()


def showProfiles(appName: str | None = None) -> None:
	"""Abre el diálogo «Perfiles de configuración».

	``appName`` es el nombre de la aplicación que tenía el foco antes de abrir
	el menú de Tiresias. Si no se indica, se consulta en el hilo del núcleo.
	"""
	_showSingleton("profiles", lambda: ProfilesDialog(parentWindow(), appName))


# ====================================================================== complementos
class AddonsDialog(_ModelessDialog):
	dialogKey = "addons"

	def __init__(self, parent: wx.Window | None) -> None:
		super().__init__(parent, _("Administrador de complementos"))
		from .. import addons

		self._addonsModule = addons
		self._changed = False
		self._installed: set[str] = set()
		self._items: list[Any] = []
		main = wx.BoxSizer(wx.VERTICAL)
		b = SettingsBuilder(self, main)
		self.list = b.addLabeledControl(
			_("Complementos &instalados:"),
			lambda p: wx.ListCtrl(p, style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=(620, 220)),
			vertical=True,
			proportion=1,
		)
		for i, (title, width) in enumerate(((_("Nombre"), 200), (_("Estado"), 170), (_("Versión"), 80), (_("Autor"), 160))):
			self.list.InsertColumn(i, title, width=width)
		self.desc = b.addText(_("&Descripción:"), "", style=wx.TE_MULTILINE | wx.TE_READONLY, size=(620, 90))
		(
			self.installButton,
			self.toggleButton,
			self.removeButton,
			self.helpButton,
			self.folderButton,
		) = _addButtonRow(
			self,
			main,
			[
				(_("Instalar desde &archivo..."), self._onInstall),
				(_("Desacti&var"), self._onToggle),
				(_("&Eliminar"), self._onRemove),
				(_("A&yuda del complemento"), self._onHelp),
				(_("Abrir ca&rpeta"), self._onFolder),
			],
		)
		self.overrideButton, self.storeButton = _addButtonRow(
			self,
			main,
			[
				(_("Activar de todos &modos"), self._onOverride),
				(_("&Tienda de complementos..."), self._onStore),
			],
		)
		from ..config import policy as policyModule

		self.installButton.Enable(policyModule.isAllowed("addonInstall"))
		self.storeButton.Enable(policyModule.isAllowed("addonStore"))
		self._closeButton(main)
		self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda evt: self._updateDetails())
		self.list.Bind(wx.EVT_LIST_ITEM_DESELECTED, lambda evt: self._updateDetails())
		self._finishLayout(main, (680, 460))
		self.refresh()
		self.list.SetFocus()

	# --------------------------------------------------- lista
	def _status(self, addon: Any) -> str:
		addons = self._addonsModule
		if os.path.basename(addon.path) in addons.pendingRemovals() or addon.id in addons.pendingRemovals():
			return _("Se eliminará al reiniciar")
		if addon.isBlocked:
			return _("Bloqueado por el administrador")
		if not addon.isCompatible:
			return _("Incompatible") if addon.isTooNew else _("No probado con esta versión")
		if addon.compatibilityOverridden and addon.isUntested:
			return _("Activado de todos modos") if addon.isEnabled else _("Desactivado")
		if addon.loadError:
			return _("Error")
		if addon.id in self._installed:
			return _("Instalado, requiere reiniciar")
		return _("Activado") if addon.isEnabled else _("Desactivado")

	def refresh(self, selectId: str | None = None) -> None:
		addons = self._addonsModule
		try:
			items = addons.getAddons() or addons.discover()
		except Exception:
			log.exception("No se pudieron obtener los complementos")
			items = []
		self._items = sorted(items, key=lambda a: a.name.lower())
		self.list.DeleteAllItems()
		for i, addon in enumerate(self._items):
			self.list.InsertItem(i, addon.name)
			self.list.SetItem(i, 1, self._status(addon))
			self.list.SetItem(i, 2, addon.version)
			self.list.SetItem(i, 3, addon.author)
		if self._items:
			index = 0
			for i, addon in enumerate(self._items):
				if addon.id == selectId:
					index = i
			self.list.Select(index)
			self.list.Focus(index)
		self._updateDetails()

	def _selected(self) -> Any | None:
		i = self.list.GetFirstSelected()
		return self._items[i] if 0 <= i < len(self._items) else None

	def _updateDetails(self) -> None:
		addon = self._selected()
		has = addon is not None
		if has:
			lines = [addon.description or _("Sin descripción.")]
			if addon.url:
				lines.append(_("Página web: {url}").format(url=addon.url))
			if addon.loadError:
				lines.append(_("Error: {error}").format(error=addon.loadError))
			reason = addon.incompatibilityReason()
			if reason:
				lines.append(reason)
			if addon.changelog:
				lines += ["", _("Cambios de esta versión:"), addon.changelog]
			self.desc.SetValue("\n".join(lines))
			self.toggleButton.SetLabel(_("Desacti&var") if addon.isEnabled else _("Acti&var"))
			self.helpButton.Enable(addon.docPath() is not None)
		else:
			self.desc.SetValue("")
			self.helpButton.Enable(False)
		self.overrideButton.Enable(has and addon.isUntested and not addon.isTooNew)
		if has and addon.isUntested:
			self.overrideButton.SetLabel(_("Quitar «activar de todos &modos»") if addon.compatibilityOverridden else _("Activar de todos &modos"))
		self.toggleButton.Enable(has)
		self.removeButton.Enable(has)

	# --------------------------------------------------- acciones
	def _onInstall(self, evt: wx.CommandEvent) -> None:
		if getattr(self, "_installing", False):
			return
		dlg = wx.FileDialog(
			self,
			_("Elegir el complemento que desea instalar"),
			wildcard=_("Complementos de Tiresias (*.tiresias-addon)|*.tiresias-addon"),
			style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
		)
		try:
			if dlg.ShowModal() != wx.ID_OK:
				return
			path = dlg.GetPath()
		finally:
			dlg.Destroy()
		try:
			manifest, existing = self._addonsModule.inspectPackage(path)
		except Exception as e:
			showError(_("No se pudo instalar el complemento: {error}").format(error=e), self)
			return
		if existing is not None:
			newVersion = str(manifest.get("version", ""))
			cmp = self._addonsModule.compareVersions(newVersion, existing.version)
			if cmp > 0:
				question = _("¿Actualizar «{name}» de la versión {old} a la {new}?")
			elif cmp < 0:
				question = _("Ya está instalada la versión {old} de «{name}», más reciente que la {new}. ¿Instalar la versión anterior?")
			else:
				question = _("La versión {new} de «{name}» ya está instalada. ¿Volver a instalarla?")
			if not askYesNo(question.format(name=existing.name, old=existing.version, new=newVersion), _("Instalar complemento"), self):
				return
		# Descomprimir y copiar puede tardar: en un hilo propio (como la tienda).
		self._installing = True
		speakMessageOnCore(_("Instalando el complemento..."))
		runInThread(self._addonsModule.installFromFile, path, callback=lambda addon, error: self._onInstalled(path, addon, error), name="TiresiasInstalaComplemento")

	def _onInstalled(self, path: str, addon: Any, error: BaseException | None) -> None:
		if not isAlive(self):
			return
		self._installing = False
		if error is not None or addon is None:
			log.error("Error instalando %s", path, exc_info=error)
			showError(_("No se pudo instalar el complemento: {error}").format(error=error), self)
			return
		self._installed.add(addon.id)
		self._changed = True
		self.refresh(addon.id)
		message_dialog.messageBox(
			_("Se ha instalado «{name}» {version}. Reinicie Tiresias para usarlo.").format(name=addon.name, version=addon.version),
			_("Complemento instalado"),
			wx.OK | wx.ICON_INFORMATION,
			self,
		)

	def _onToggle(self, evt: wx.CommandEvent) -> None:
		addon = self._selected()
		if addon is None:
			return
		self._addonsModule.setEnabled(addon.id, not addon.isEnabled)
		self._changed = True
		self.refresh(addon.id)

	def _onOverride(self, evt: wx.CommandEvent) -> None:
		addon = self._selected()
		if addon is None or not addon.isUntested:
			return
		if not addon.compatibilityOverridden and not askYesNo(
			_("«{name}» no se ha probado con esta versión de Tiresias y puede no funcionar bien o provocar errores. ¿Activarlo de todos modos?").format(name=addon.name),
			_("Complemento no probado"),
			self,
		):
			return
		self._addonsModule.setCompatibilityOverride(addon.id, not addon.compatibilityOverridden)
		self._changed = True
		self.refresh(addon.id)

	def _onStore(self, evt: wx.CommandEvent) -> None:
		from . import system_dialogs

		system_dialogs.showAddonStore()

	def _onRemove(self, evt: wx.CommandEvent) -> None:
		addon = self._selected()
		if addon is None:
			return
		if not askYesNo(
			_("¿Seguro que desea eliminar el complemento «{name}»? Se eliminará al reiniciar Tiresias.").format(name=addon.name),
			_("Eliminar complemento"),
			self,
		):
			return
		try:
			self._addonsModule.markForRemoval(addon.id)
		except OSError as e:
			showError(_("No se pudo marcar el complemento para eliminarlo: {error}").format(error=e), self)
			return
		self._changed = True
		self.refresh(addon.id)

	def _onHelp(self, evt: wx.CommandEvent) -> None:
		addon = self._selected()
		path = addon.docPath() if addon is not None else None
		if not path:
			return
		try:
			os.startfile(path)
		except OSError as e:
			showError(_("No se pudo abrir la ayuda: {error}").format(error=e), self)

	def _onFolder(self, evt: wx.CommandEvent) -> None:
		addon = self._selected()
		folder = addon.path if addon is not None and os.path.isdir(addon.path) else paths.addonsDir()
		try:
			os.makedirs(folder, exist_ok=True)
			os.startfile(folder)
		except OSError as e:
			showError(_("No se pudo abrir la carpeta: {error}").format(error=e), self)

	def onCancel(self) -> None:
		changed = self._changed
		self.closeDialog()
		if not changed:
			return
		_saveConfig()
		if askYesNo(_("¿Reiniciar Tiresias ahora para aplicar los cambios?"), _("Administrador de complementos"), parentWindow()):
			from .. import core

			queue_handler.queueFunction(core.restart)


def showAddonsManager() -> None:
	"""Abre el «Administrador de complementos»."""
	_showSingleton("addons", lambda: AddonsDialog(parentWindow()))


# ====================================================================== gestos de entrada
#: Descripciones de órdenes de edición que no tienen descripción propia.
_FALLBACK_DESCRIPTIONS = {
	"caret_moveByLine": _("Mueve el cursor por líneas y lee la línea"),
	"caret_moveByCharacter": _("Mueve el cursor por caracteres y lee el carácter"),
	"caret_moveByWord": _("Mueve el cursor por palabras y lee la palabra"),
	"caret_moveByParagraph": _("Mueve el cursor por párrafos y lee el párrafo"),
	"caret_moveByLineBoundary": _("Mueve el cursor al inicio o al final de la línea o por páginas"),
	"caret_moveToDocumentBoundary": _("Mueve el cursor al inicio o al final del documento"),
	"caret_changeSelection": _("Cambia la selección y la anuncia"),
	"caret_backspaceCharacter": _("Borra el carácter anterior y lo anuncia"),
	"caret_backspaceWord": _("Borra la palabra anterior y la anuncia"),
	"caret_delete": _("Borra el texto en el cursor y lee el carácter siguiente"),
}


@dataclass
class ScriptInfo:
	cls: type
	classKey: str
	name: str
	description: str
	category: str
	classGestures: dict[str, str]


def _classKey(cls: type) -> str:
	return f"{cls.__module__}.{cls.__qualname__}"


def _scriptsForClass(cls: type, defaultCategory: str, ownOnly: bool = False) -> list[ScriptInfo]:
	"""Órdenes de ``cls``; con ``ownOnly``, solo las definidas en la propia clase."""
	classGestures = dict(cls.iterClassGestures()) if hasattr(cls, "iterClassGestures") else {}
	boundNames = set(classGestures.values())
	result = []
	for attr in sorted(vars(cls)) if ownOnly else dir(cls):
		if not attr.startswith("script_"):
			continue
		func = getattr(cls, attr, None)
		if not callable(func):
			continue
		name = attr[7:]
		desc = (getattr(func, "__doc__", None) or "").strip()
		if not desc:
			if name not in boundNames:
				continue
			desc = _FALLBACK_DESCRIPTIONS.get(name) or _("Orden {name}").format(name=name)
		category = getattr(func, "category", None) or getattr(cls, "scriptCategory", None) or defaultCategory
		result.append(ScriptInfo(cls, _classKey(cls), name, desc.splitlines()[0].strip(), category, classGestures))
	return result


def collectScripts() -> list[ScriptInfo]:
	"""Recoge las órdenes disponibles (debe llamarse en el hilo del núcleo)."""
	from ..global_commands import GlobalCommands

	misc = _("Varios")
	sources: list[tuple[type, str]] = [(GlobalCommands, misc)]
	try:
		from ..browse.document import BrowseModeDocument

		sources.append((BrowseModeDocument, _("Modo exploración")))
	except Exception:
		log.exception("No se pudieron obtener las órdenes del modo exploración")
	try:
		from ..mathpres.interaction import MathInteractor

		sources.append((MathInteractor, _("Matemáticas")))
	except Exception:
		log.exception("No se pudieron obtener las órdenes de exploración de fórmulas")
	try:
		from ..objects.behaviors import EditableText

		sources.append((EditableText, _("Edición de texto")))
	except Exception:
		log.exception("No se pudieron obtener las órdenes de edición")
	try:
		# Órdenes propias del controlador de la línea braille activa.
		from .. import braille

		display = braille.handler.display
		if any(a.startswith("script_") for a in dir(type(display))):
			sources.append((type(display), _("Braille")))
	except Exception:
		log.exception("No se pudieron obtener las órdenes del controlador braille")
	try:
		from ..plugins import handler as pluginHandler

		for plugin in list(pluginHandler.runningPlugins):
			sources.append((type(plugin), misc))
	except Exception:
		log.exception("No se pudieron obtener las órdenes de los complementos globales")
	try:
		from .. import api

		focus = api.getFocusObject()
		app = focus.appModule if focus is not None else None
		appName = getattr(app, "appName", "") if app is not None else ""
		if app is not None and appName.lower() not in _ownProcessNames():
			sources.append((type(app), _("Aplicación {app}").format(app=appName)))
	except Exception:
		log.exception("No se pudo obtener el módulo de la aplicación actual")
	result: list[ScriptInfo] = []
	seen: set[type] = set()
	for cls, category in sources:
		if cls in seen:
			continue
		seen.add(cls)
		try:
			result.extend(_scriptsForClass(cls, category))
		except Exception:
			log.exception("Error recogiendo las órdenes de %r", cls)
	# Órdenes propias del objeto con el foco, su documento y sus contenedores
	# (Word, Excel, Hojas de cálculo de Google, listas con columnas, documento
	# de OCR...): solo las definidas en cada clase, para no repetir las de arriba.
	try:
		for cls, category in _focusScriptClasses([c for c, _cat in sources]):
			if cls in seen:
				continue
			seen.add(cls)
			result.extend(_scriptsForClass(cls, category, ownOnly=True))
	except Exception:
		log.exception("No se pudieron obtener las órdenes del objeto con el foco")
	return result


def _focusScriptClasses(listed: list[type]) -> list[tuple[type, str]]:
	"""Clases con órdenes propias del foco, su documento y sus contenedores."""
	from .. import api

	focus = api.getFocusObject()
	if focus is None:
		return []
	objects: list = [focus]
	ti = getattr(focus, "treeInterceptor", None)
	if ti is not None:
		objects.append(ti)
	try:
		objects.extend(reversed(api.getFocusAncestors()))
	except Exception:
		pass
	app = getattr(focus, "appModule", None)
	appName = getattr(app, "appName", "") if app is not None else ""
	out: list[tuple[type, str]] = []
	for obj in objects:
		for klass in type(obj).__mro__:
			if not any(a.startswith("script_") and callable(f) for a, f in vars(klass).items()):
				continue
			if any(issubclass(src, klass) for src in listed) or any(k is klass for k, _c in out):
				continue
			if ".appmodules." in klass.__module__ and appName:
				category = _("Aplicación {app}").format(app=appName)
			else:
				category = _("Objeto actual")
			out.append((klass, category))
	return out


def _applyGestureMap(state: dict[str, dict[str, str | None]]) -> None:
	"""Reconstruye y guarda el mapa de gestos del usuario (hilo del núcleo)."""
	from ..input import core as inputCore
	from ..input import gestures

	m = gestures.userMap
	m.reset()
	for classKey, bindings in state.items():
		for gid, scriptName in bindings.items():
			if scriptName is None:
				m.unbind(classKey, gid)
			else:
				m.bind(classKey, gid, scriptName)
	try:
		m.save()
	except OSError:
		log.exception("No se pudo guardar el mapa de gestos")
	inputCore.manager.updateChain()


class InputGesturesDialog(_ModelessDialog):
	dialogKey = "gestures"

	def __init__(self, parent: wx.Window | None) -> None:
		super().__init__(parent, _("Gestos de entrada"))
		from ..baseobject import normalizeGestureId
		from ..input import gestures, keys

		self._keys = keys
		self._normalize = normalizeGestureId
		self._state: dict[str, dict[str, str | None]] = gestures.userMap.userBindings()
		self._scripts: list[ScriptInfo] = []
		self._capturing: ScriptInfo | None = None
		self._captureHandled = True
		self._captureFuncRef: Callable | None = None
		main = wx.BoxSizer(wx.VERTICAL)
		b = SettingsBuilder(self, main)
		self.filterCtrl = b.addText(_("&Filtrar por:"), size=(300, -1))
		self.tree = b.addLabeledControl(
			_("&Órdenes:"),
			lambda p: wx.TreeCtrl(p, style=wx.TR_HAS_BUTTONS | wx.TR_HIDE_ROOT | wx.TR_SINGLE | wx.TR_LINES_AT_ROOT, size=(600, 360)),
			vertical=True,
			proportion=1,
		)
		self.statusText = wx.StaticText(self, label=_("Cargando órdenes..."))
		main.Add(self.statusText, 0, wx.BOTTOM, 4)
		self.addButton, self.removeButton, self.resetButton = _addButtonRow(
			self,
			main,
			[
				(_("&Añadir"), self._onAdd),
				(_("&Quitar"), self._onRemove),
				(_("&Restablecer valores de fábrica"), self._onReset),
			],
		)
		self._okCancelButtons(main, self._onOk)
		self.filterCtrl.Bind(wx.EVT_TEXT, lambda evt: self._rebuildTree())
		self.tree.Bind(wx.EVT_TREE_SEL_CHANGED, lambda evt: self._updateButtons())
		self._finishLayout(main, (680, 560))
		self._updateButtons()
		self.tree.SetFocus()
		runOnCore(collectScripts, callback=self._onScripts)

	def _onScripts(self, scripts: list[ScriptInfo] | None) -> None:
		if not isAlive(self):
			return
		self._scripts = scripts or []
		self.statusText.SetLabel("")
		self._rebuildTree()

	# --------------------------------------------------- estado de gestos
	def _lookupUser(self, cls: type, gid: str) -> tuple[bool, str | None]:
		for klass in cls.__mro__:
			m = self._state.get(_classKey(klass))
			if m and gid in m:
				return True, m[gid]
		return False, None

	def _target(self, info: ScriptInfo, gid: str) -> str | None:
		found, value = self._lookupUser(info.cls, gid)
		return value if found else info.classGestures.get(gid)

	def gesturesFor(self, info: ScriptInfo) -> list[str]:
		candidates = set(info.classGestures)
		for klass in info.cls.__mro__:
			candidates |= set(self._state.get(_classKey(klass), {}))
		result = [g for g in candidates if self._target(info, g) == info.name]
		return sorted(result, key=lambda g: self._keys.labelForGesture(g).lower())

	def addGesture(self, info: ScriptInfo, gid: str) -> str:
		gid = self._normalize(gid)
		self._state.setdefault(info.classKey, {})[gid] = info.name
		return gid

	def removeGesture(self, info: ScriptInfo, gid: str) -> None:
		m = self._state.setdefault(info.classKey, {})
		if m.get(gid) == info.name:
			del m[gid]
		if self._target(info, gid) == info.name:
			m[gid] = None

	# --------------------------------------------------- árbol
	def _rebuildTree(self, select: tuple[str, str, str | None] | None = None) -> None:
		"""Reconstruye el árbol. ``select`` = (clase, orden, gesto o None)."""
		if select is None:
			select = self._selectionKey()
		filt = self.filterCtrl.GetValue().strip().lower()
		tree = self.tree
		tree.Freeze()
		try:
			tree.DeleteAllItems()
			root = tree.AddRoot(_("Órdenes"))
			byCategory: dict[str, list[ScriptInfo]] = {}
			for info in self._scripts:
				byCategory.setdefault(info.category, []).append(info)
			toSelect = None
			for category in sorted(byCategory, key=str.lower):
				catMatch = bool(filt) and filt in category.lower()
				entries = []
				for info in sorted(byCategory[category], key=lambda i: i.description.lower()):
					gids = self.gesturesFor(info)
					labels = [self._keys.labelForGesture(g) for g in gids]
					if filt and not catMatch and filt not in info.description.lower() and not any(filt in lbl.lower() for lbl in labels):
						continue
					entries.append((info, gids, labels))
				if not entries:
					continue
				catItem = tree.AppendItem(root, category)
				tree.SetItemData(catItem, ("category", category))
				for info, gids, labels in entries:
					sItem = tree.AppendItem(catItem, info.description)
					tree.SetItemData(sItem, ("script", info))
					if select and select[0] == info.classKey and select[1] == info.name and select[2] is None:
						toSelect = sItem
					for gid, label in zip(gids, labels):
						gItem = tree.AppendItem(sItem, label)
						tree.SetItemData(gItem, ("gesture", info, gid))
						if select and select[0] == info.classKey and select[1] == info.name and select[2] == gid:
							toSelect = gItem
					if select and toSelect is None and select[0] == info.classKey and select[1] == info.name:
						toSelect = sItem
				if filt or (select and toSelect is not None and tree.GetItemParent(toSelect) in (catItem,)):
					tree.Expand(catItem)
			if filt:
				tree.ExpandAll()
			if toSelect is not None:
				tree.EnsureVisible(toSelect)
				tree.SelectItem(toSelect)
			else:
				first, _cookie = tree.GetFirstChild(root)
				if first.IsOk():
					tree.SelectItem(first)
		finally:
			tree.Thaw()
		self._updateButtons()

	def _selectedData(self) -> Any:
		item = self.tree.GetSelection()
		if not item.IsOk():
			return None
		try:
			return self.tree.GetItemData(item)
		except Exception:
			return None

	def _selectionKey(self) -> tuple[str, str, str | None] | None:
		data = self._selectedData()
		if not data:
			return None
		if data[0] == "script":
			return (data[1].classKey, data[1].name, None)
		if data[0] == "gesture":
			return (data[1].classKey, data[1].name, data[2])
		return None

	def _selectedScript(self) -> ScriptInfo | None:
		data = self._selectedData()
		if data and data[0] in ("script", "gesture"):
			return data[1]
		return None

	def _updateButtons(self) -> None:
		if not isAlive(self):
			return
		data = self._selectedData()
		self.addButton.Enable(bool(data) and data[0] in ("script", "gesture") and self._captureHandled)
		self.removeButton.Enable(bool(data) and data[0] == "gesture")

	# --------------------------------------------------- acciones
	def _onAdd(self, evt: wx.CommandEvent) -> None:
		info = self._selectedScript()
		if info is None:
			return
		from ..input import core as inputCore

		self._capturing = info
		self._captureHandled = False

		def capture(gesture: Any) -> bool:
			# Hilo del núcleo: solo se atiende la primera pulsación.
			if self._captureHandled:
				return True
			self._captureHandled = True
			if inputCore.manager.captureFunc is capture:
				inputCore.manager.captureFunc = None
			wx.CallAfter(self._onCaptured, list(gesture.identifiers), getattr(gesture, "normalizedKeys", ""))
			return True

		self._captureFuncRef = capture
		inputCore.manager.captureFunc = capture
		message = _("Pulse la combinación de teclas (o haga el gesto táctil) que desee asignar, o Escape para cancelar.")
		self.statusText.SetLabel(message)
		speakMessageOnCore(message)
		self._updateButtons()

	def _cancelCapture(self) -> None:
		try:
			from ..input import core as inputCore

			if self._captureFuncRef is not None and inputCore.manager.captureFunc is self._captureFuncRef:
				inputCore.manager.captureFunc = None
		except Exception:
			log.debug("No se pudo cancelar la captura", exc_info=True)
		self._captureFuncRef = None
		self._captureHandled = True

	def _onCaptured(self, identifiers: list[str], normalizedKeys: str) -> None:
		if not isAlive(self):
			return
		info = self._capturing
		self._capturing = None
		self._captureFuncRef = None
		self.statusText.SetLabel("")
		self._updateButtons()
		if info is None or not identifiers:
			return
		if normalizedKeys == "escape":
			speakMessageOnCore(_("Cancelado"))
			return
		from . import gesture_tools

		gid = gesture_tools.chooseGestureVariant(self, identifiers)
		if gid is None:
			return
		gid = self._normalize(gid)
		if not gesture_tools.confirmAssignment(self, self._scripts, self._state, info, gid):
			return
		gid = self.addGesture(info, gid)
		self._rebuildTree((info.classKey, info.name, gid))
		self.tree.SetFocus()

	def _onRemove(self, evt: wx.CommandEvent) -> None:
		data = self._selectedData()
		if not data or data[0] != "gesture":
			return
		info, gid = data[1], data[2]
		self.removeGesture(info, gid)
		self._rebuildTree((info.classKey, info.name, None))
		self.tree.SetFocus()

	def _onReset(self, evt: wx.CommandEvent) -> None:
		if not askYesNo(
			_("¿Seguro que desea restablecer todos los gestos a los valores de fábrica? Se perderán todos los cambios de gestos, también los de otras aplicaciones."),
			_("Restablecer gestos"),
			self,
		):
			return
		self._state = {}
		self._rebuildTree()

	def _onOk(self, evt: wx.CommandEvent) -> None:
		self._cancelCapture()
		state = {k: dict(v) for k, v in self._state.items() if v}
		queue_handler.queueFunction(_applyGestureMap, state)
		self.closeDialog()

	def onCancel(self) -> None:
		self._cancelCapture()
		self.closeDialog()


def showInputGestures() -> None:
	"""Abre el diálogo «Gestos de entrada».

	Las órdenes de la aplicación actual se leen del foco en el momento de
	llamar a esta función (en el hilo del núcleo).
	"""
	_showSingleton("gestures", lambda: InputGesturesDialog(parentWindow()))


# ====================================================================== diccionarios
_DICT_TYPES = [
	("anywhere", _("En cualquier lugar")),
	("word", _("Palabra completa")),
	("startOfWord", _("Principio de palabra")),
	("endOfWord", _("Final de palabra")),
	("partOfWord", _("Parte de una palabra")),
	("regex", _("Expresión regular")),
]
#: Explicación de cada tipo (#19657).
_DICT_TYPE_HELP = {
	"anywhere": _("Se sustituye en cualquier lugar, también dentro de otras palabras. «can» cambia «can», «canción» y «escanear»."),
	"word": _("Solo cuando el patrón es una palabra completa. «can» cambia «can» pero no «canción»."),
	"startOfWord": _("Solo al principio de una palabra. «can» cambia «can» y «canción», pero no «escanear»."),
	"endOfWord": _("Solo al final de una palabra. «can» cambia «can» y «Duncan», pero no «canción»."),
	"partOfWord": _("Solo dentro de una palabra más larga, nunca como palabra suelta. «can» cambia «canción» y «escanear», pero no «can»."),
	"regex": _("El patrón es una expresión regular de Python; la sustitución puede usar grupos como \\1."),
}
#: Por qué no se puede editar el diccionario del perfil sin un perfil activo.
_NO_PROFILE_DICT_MESSAGE = _(
	"No hay ningún perfil activo. El diccionario del perfil se guarda con cada perfil: active un perfil "
	"(o edítelo desde Perfiles de configuración, botón Diccionario del perfil) para editar su diccionario."
)
_DICT_TITLES = {
	"default": _("Diccionario por defecto"),
	"voice": _("Diccionario de voz"),
	"temp": _("Diccionario temporal"),
	"profile": _("Diccionario del perfil"),
}


class DictEntryDialog(wx.Dialog):
	"""Edita una entrada de diccionario (modal), con prueba en vivo."""

	def __init__(self, parent: wx.Window, title: str, entry: Any | None = None) -> None:
		super().__init__(parent, title=title)
		main = wx.BoxSizer(wx.VERTICAL)
		b = SettingsBuilder(self, main)
		self.patternCtrl = b.addText(_("&Patrón:"), entry.pattern if entry else "", size=(360, -1))
		self.replacementCtrl = b.addText(_("&Sustitución:"), entry.replacement if entry else "", size=(360, -1))
		self.commentCtrl = b.addText(_("C&omentario:"), entry.comment if entry else "", size=(360, -1))
		self.caseCtrl = b.addCheckBox(_("&Distingue mayúsculas"), bool(entry.caseSensitive) if entry else False)
		self.enabledCtrl = b.addCheckBox(_("Entrada a&ctiva"), bool(getattr(entry, "enabled", True)) if entry else True)
		types = [t for t, _l in _DICT_TYPES]
		current = entry.type if entry and entry.type in types else "anywhere"
		self.typeCtrl = b.addChoice(_("&Tipo:"), [lbl for _t, lbl in _DICT_TYPES], types.index(current))
		self.typeHelp = b.addText(_("Qué hace este tipo:"), "", style=wx.TE_MULTILINE | wx.TE_READONLY, size=(360, 60))
		g = b.group(_("Probar la entrada"))
		self.testCtrl = g.addText(_("Te&xto de prueba:"), "", size=(360, -1))
		self.resultCtrl = g.addText(_("Resultado:"), "", style=wx.TE_READONLY, size=(360, -1))
		buttons = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
		main.Add(buttons, 0, wx.EXPAND | wx.TOP, 8)
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(main, 1, wx.EXPAND | wx.ALL, 10)
		self.SetSizer(outer)
		outer.Fit(self)
		self.FindWindow(wx.ID_OK).SetLabel(_("Aceptar"))
		self.FindWindow(wx.ID_CANCEL).SetLabel(_("Cancelar"))
		self.Bind(wx.EVT_BUTTON, self._onOk, id=wx.ID_OK)
		for ctrl in (self.patternCtrl, self.replacementCtrl, self.testCtrl):
			ctrl.Bind(wx.EVT_TEXT, lambda evt: self._updateTest())
		self.caseCtrl.Bind(wx.EVT_CHECKBOX, lambda evt: self._updateTest())
		self.typeCtrl.Bind(wx.EVT_CHOICE, lambda evt: self._onType())
		self._onType()
		self.CentreOnParent()
		self.patternCtrl.SetFocus()

	def _kind(self) -> str:
		return _DICT_TYPES[max(0, self.typeCtrl.GetSelection())][0]

	def _onType(self) -> None:
		self.typeHelp.SetValue(_DICT_TYPE_HELP.get(self._kind(), ""))
		self._updateTest()

	def _updateTest(self) -> None:
		text = self.testCtrl.GetValue()
		if not text or not self.patternCtrl.GetValue():
			self.resultCtrl.SetValue(text)
			return
		e = self.makeEntry()
		e.enabled = True
		self.resultCtrl.SetValue(e.apply(text) if e._compiled else _("(patrón no válido)"))

	def makeEntry(self) -> Any:
		from ..speech.dictionaries import Entry

		e = Entry(
			self.patternCtrl.GetValue(),
			self.replacementCtrl.GetValue(),
			self.caseCtrl.GetValue(),
			self._kind(),
			self.commentCtrl.GetValue(),
			self.enabledCtrl.GetValue(),
		)
		e.compile()
		return e

	def _onOk(self, evt: wx.CommandEvent) -> None:
		import re

		pattern = self.patternCtrl.GetValue()
		if not pattern:
			showError(_("El patrón no puede estar vacío."), self)
			self.patternCtrl.SetFocus()
			return
		if self._kind() == "regex":
			try:
				rx = re.compile(pattern)
			except re.error as e:
				showError(_("La expresión regular no es válida: {error}").format(error=e), self)
				self.patternCtrl.SetFocus()
				return
			# La sustitución también se valida (grupos como \1 o \g<nombre> que no existen).
			try:
				rx.sub(self.replacementCtrl.GetValue(), "")
			except (re.error, IndexError) as e:
				showError(_("La sustitución no es válida para esta expresión regular: {error}").format(error=e), self)
				self.replacementCtrl.SetFocus()
				return
		evt.Skip()


class SpeechDictDialog(_ModelessDialog):
	def __init__(self, parent: wx.Window | None, kind: str) -> None:
		from ..speech import dictionaries

		self.kind = kind
		self.dialogKey = f"dict-{kind}"
		#: Perfil cuyo diccionario se edita (solo con ``kind == "profile"``).
		self.profileName = conf.activeProfileName if kind == "profile" else None
		if kind == "profile":
			# Diccionario del perfil activo (se aplica solo mientras el perfil está activo).
			dictionaries.ensureProfileDict()
		if kind == "voice":
			dictionaries.ensureVoiceDict()
		self.speechDict = {"default": dictionaries.defaultDict, "voice": dictionaries.voiceDict, "temp": dictionaries.tempDict, "profile": dictionaries.profileDict}[kind]
		title = _DICT_TITLES[kind]
		if kind == "profile" and conf.activeProfileName:
			title = _("{title} ({name})").format(title=title, name=conf.activeProfileName)
		if kind == "voice" and self.speechDict.fileName:
			title = _("{title} ({name})").format(title=title, name=os.path.splitext(os.path.basename(self.speechDict.fileName))[0])
		super().__init__(parent, title)
		self.entries = [e.copy() for e in self.speechDict]
		#: Índices de ``entries`` visibles con el filtro actual.
		self._visible: list[int] = []
		#: Sin un perfil activo el diccionario del perfil no tiene dónde guardarse:
		#: se explica y no se deja editar (antes los cambios se perdían sin avisar).
		self.readOnly = kind == "profile" and not self.profileName
		main = wx.BoxSizer(wx.VERTICAL)
		if self.readOnly:
			main.Add(wx.StaticText(self, label=_NO_PROFILE_DICT_MESSAGE), 0, wx.BOTTOM, 8)
		b = SettingsBuilder(self, main)
		self.filterCtrl = b.addText(_("&Filtrar por:"), size=(300, -1))
		self.list = b.addLabeledControl(
			_("&Entradas del diccionario (se aplican en este orden):"),
			lambda p: wx.ListCtrl(p, style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=(700, 280)),
			vertical=True,
			proportion=1,
		)
		for i, (colTitle, width) in enumerate(
			((_("Patrón"), 140), (_("Sustitución"), 140), (_("Activa"), 60), (_("Distingue mayúsculas"), 90), (_("Tipo"), 130), (_("Comentario"), 130))
		):
			self.list.InsertColumn(i, colTitle, width=width)
		self.addButton, self.editButton, self.removeButton, self.toggleButton = _addButtonRow(
			self,
			main,
			[(_("&Añadir..."), self._onAdd), (_("E&ditar..."), self._onEdit), (_("&Quitar"), self._onRemove), (_("Ac&tivar o desactivar"), self._onToggle)],
		)
		self.upButton, self.downButton, self.clearButton, self.importButton, self.exportButton = _addButtonRow(
			self,
			main,
			[
				(_("&Subir"), lambda evt: self._onMove(-1)),
				(_("Ba&jar"), lambda evt: self._onMove(1)),
				(_("Quitar t&odo"), self._onClear),
				(_("&Importar..."), self._onImport),
				(_("E&xportar..."), self._onExport),
			],
		)
		self._okCancelButtons(main, self._onOk)
		self.filterCtrl.Bind(wx.EVT_TEXT, lambda evt: self._refresh(self._selectedIndex()))
		self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._onEdit)
		self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda evt: self._updateButtons())
		self.list.Bind(wx.EVT_LIST_ITEM_DESELECTED, lambda evt: self._updateButtons())
		self.list.Bind(wx.EVT_KEY_DOWN, self._onListKey)
		self._finishLayout(main, (760, 480))
		self._refresh(0)
		self.list.SetFocus()

	def _selectedIndex(self) -> int | None:
		i = self.list.GetFirstSelected()
		return self._visible[i] if 0 <= i < len(self._visible) else None

	def _refresh(self, select: int | None = None) -> None:
		types = dict(_DICT_TYPES)
		filt = self.filterCtrl.GetValue().strip().lower()
		self._visible = [
			i for i, e in enumerate(self.entries) if not filt or filt in e.pattern.lower() or filt in e.replacement.lower() or filt in e.comment.lower()
		]
		self.list.DeleteAllItems()
		for row, i in enumerate(self._visible):
			e = self.entries[i]
			self.list.InsertItem(row, e.pattern)
			self.list.SetItem(row, 1, e.replacement)
			self.list.SetItem(row, 2, _("Sí") if e.enabled else _("No"))
			self.list.SetItem(row, 3, _("Sí") if e.caseSensitive else _("No"))
			self.list.SetItem(row, 4, types.get(e.type, e.type))
			self.list.SetItem(row, 5, e.comment)
		if self._visible:
			row = self._visible.index(select) if select in self._visible else 0
			if select is not None and select not in self._visible:
				row = min(range(len(self._visible)), key=lambda r: abs(self._visible[r] - select))
			self.list.Select(row)
			self.list.Focus(row)
			self.list.EnsureVisible(row)
		self._updateButtons()

	def _updateButtons(self) -> None:
		idx = self._selectedIndex()
		has = idx is not None
		filtered = bool(self.filterCtrl.GetValue().strip())
		self.editButton.Enable(has)
		self.removeButton.Enable(has)
		self.toggleButton.Enable(has)
		# Con un filtro activo el orden no se puede cambiar (no se ven todas).
		self.upButton.Enable(has and not filtered and idx > 0)
		self.downButton.Enable(has and not filtered and idx is not None and idx < len(self.entries) - 1)
		self.clearButton.Enable(bool(self.entries))
		self.exportButton.Enable(bool(self.entries))
		if self.readOnly:
			for btn in (self.addButton, self.editButton, self.removeButton, self.toggleButton, self.upButton, self.downButton, self.clearButton, self.importButton):
				btn.Enable(False)

	def _blocked(self) -> bool:
		"""``True`` (y lo explica) si el diccionario no se puede editar."""
		if self.readOnly:
			speakMessageOnCore(_NO_PROFILE_DICT_MESSAGE)
			return True
		return False

	def _onListKey(self, evt: wx.KeyEvent) -> None:
		key = evt.GetKeyCode()
		if self.readOnly and (key in (wx.WXK_DELETE, wx.WXK_SPACE) or (evt.AltDown() and key in (wx.WXK_UP, wx.WXK_DOWN))):
			self._blocked()
			return
		if key == wx.WXK_DELETE:
			self._onRemove(None)
		elif key == wx.WXK_SPACE:
			self._onToggle(None)
		elif evt.AltDown() and key in (wx.WXK_UP, wx.WXK_DOWN):
			self._onMove(-1 if key == wx.WXK_UP else 1)
		else:
			evt.Skip()

	def _onAdd(self, evt: wx.CommandEvent) -> None:
		if self._blocked():
			return
		dlg = DictEntryDialog(self, _("Añadir entrada"))
		try:
			if dlg.ShowModal() != wx.ID_OK:
				return
			self.entries.append(dlg.makeEntry())
		finally:
			dlg.Destroy()
		self.filterCtrl.ChangeValue("")
		self._refresh(len(self.entries) - 1)
		self.list.SetFocus()

	def _onEdit(self, evt: wx.CommandEvent) -> None:
		if self._blocked():
			return
		i = self._selectedIndex()
		if i is None:
			return
		dlg = DictEntryDialog(self, _("Editar entrada"), self.entries[i])
		try:
			if dlg.ShowModal() != wx.ID_OK:
				return
			self.entries[i] = dlg.makeEntry()
		finally:
			dlg.Destroy()
		self._refresh(i)
		self.list.SetFocus()

	def _onRemove(self, evt: wx.CommandEvent | None) -> None:
		if self._blocked():
			return
		i = self._selectedIndex()
		if i is None:
			return
		del self.entries[i]
		self._refresh(min(i, len(self.entries) - 1) if self.entries else None)
		self.list.SetFocus()

	def _onToggle(self, evt: wx.CommandEvent | None) -> None:
		if self._blocked():
			return
		i = self._selectedIndex()
		if i is None:
			return
		e = self.entries[i]
		e.enabled = not e.enabled
		self._refresh(i)
		speakMessageOnCore(_("activa") if e.enabled else _("desactivada"))
		self.list.SetFocus()

	def _onMove(self, direction: int) -> None:
		if self._blocked():
			return
		i = self._selectedIndex()
		if i is None or self.filterCtrl.GetValue().strip():
			return
		j = i + direction
		if not 0 <= j < len(self.entries):
			wx.Bell()
			return
		self.entries[i], self.entries[j] = self.entries[j], self.entries[i]
		self._refresh(j)
		self.list.SetFocus()

	def _onClear(self, evt: wx.CommandEvent) -> None:
		if self._blocked():
			return
		if not self.entries:
			return
		if not askYesNo(_("¿Quitar todas las entradas de este diccionario?"), _("Quitar todo"), self):
			return
		self.entries = []
		self._refresh(None)
		self.list.SetFocus()

	def _onImport(self, evt: wx.CommandEvent) -> None:
		if self._blocked():
			return
		from ..speech import dictionaries

		with wx.FileDialog(self, _("Importar entradas de diccionario"), wildcard=_("Diccionarios (*.json)|*.json"), style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			path = dlg.GetPath()
		try:
			imported = dictionaries.readEntries(path)
		except (OSError, ValueError) as e:
			showError(_("No se pudo importar el diccionario: {error}").format(error=e), self)
			return
		existing = {(e.pattern, e.type, e.caseSensitive) for e in self.entries}
		added = [e for e in imported if (e.pattern, e.type, e.caseSensitive) not in existing]
		self.entries.extend(added)
		self.filterCtrl.ChangeValue("")
		self._refresh(len(self.entries) - 1 if added else None)
		speakMessageOnCore(_("{n} entradas importadas").format(n=len(added)))
		self.list.SetFocus()

	def _onExport(self, evt: wx.CommandEvent) -> None:
		from ..speech import dictionaries

		with wx.FileDialog(
			self,
			_("Exportar el diccionario"),
			defaultFile=_("diccionario.json"),
			wildcard=_("Diccionarios (*.json)|*.json"),
			style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
		) as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			path = dlg.GetPath()
		try:
			dictionaries.writeEntries(path, self.entries)
		except OSError as e:
			showError(_("No se pudo exportar el diccionario: {error}").format(error=e), self)
			return
		speakMessageOnCore(_("Diccionario exportado"))

	def _onOk(self, evt: wx.CommandEvent) -> None:
		from ..speech import dictionaries

		if self.readOnly:
			self.closeDialog()
			return
		for e in self.entries:
			e.compile()
		if self.kind == "profile":
			# Se guarda en el archivo del perfil que se abrió, aunque el perfil
			# activo haya cambiado mientras tanto (un desencadenante, por
			# ejemplo): antes las entradas iban a parar al diccionario del otro
			# perfil o, sin perfil activo, se perdían.
			try:
				dictionaries.saveProfileDict(self.profileName, self.entries)
			except OSError as e:
				showError(_("No se pudo guardar el diccionario: {error}").format(error=e), self)
				return
			self.closeDialog()
			return
		self.speechDict[:] = self.entries
		if self.kind != "temp":
			if not self.speechDict.fileName:
				if self.kind == "voice":
					showError(_("No hay un diccionario de voz cargado; los cambios solo durarán hasta cerrar Tiresias."), self)
				else:
					showError(_("Este diccionario no tiene un archivo donde guardarse; los cambios solo durarán hasta cerrar Tiresias."), self)
			else:
				try:
					self.speechDict.save()
				except OSError as e:
					showError(_("No se pudo guardar el diccionario: {error}").format(error=e), self)
					return
		self.closeDialog()


def showSpeechDictionary(kind: str) -> None:
	"""Abre un diccionario de pronunciación: ``default``, ``voice``, ``temp`` o ``profile``."""
	if kind not in _DICT_TITLES:
		raise ValueError(f"Tipo de diccionario desconocido: {kind}")
	if kind == "profile" and not conf.activeProfileName:
		showError(_NO_PROFILE_DICT_MESSAGE, parentWindow(), _("Diccionario del perfil"))
		return
	_showSingleton(f"dict-{kind}", lambda: SpeechDictDialog(parentWindow(), kind))


# ====================================================================== símbolos
def _preserveChoices() -> list[tuple[str, str]]:
	from ..speech import symbols

	return [
		(symbols.PRESERVE_NEVER, _("Nunca")),
		(symbols.PRESERVE_ALWAYS, _("Siempre")),
		(symbols.PRESERVE_NOREP, _("Solo si no se dice el símbolo")),
	]


def _symbolDisplay(sym: str) -> str:
	if len(sym) == 1 and (sym.isspace() or not sym.isprintable()):
		try:
			return unicodedata.name(sym).lower()
		except ValueError:
			return f"U+{ord(sym):04X}"
	return sym


class SymbolsDialog(_ModelessDialog):
	dialogKey = "symbols"

	def __init__(self, parent: wx.Window | None) -> None:
		super().__init__(parent, _("Puntuación y símbolos"))
		from ..speech import symbols

		self._symbolsModule = symbols
		self.processor = symbols.processor
		self.processor.ensureLoaded()
		self.symbols = {k: symbols.Symbol(s.symbol, s.name, s.level, s.preserve) for k, s in self.processor.symbols.items()}
		#: Tablas editadas por idioma (cada idioma tiene la suya).
		self._tables: dict[str, dict] = {self.processor.language: self.symbols}
		self._languages = symbols.availableLanguages()
		self._levels = list(symbols.LEVEL_NAMES)
		self._preserve = _preserveChoices()
		self._visible: list[str] = []
		self._updating = False
		main = wx.BoxSizer(wx.VERTICAL)
		b = SettingsBuilder(self, main)
		from ..speech import languages as speechLanguages

		self.languageCtrl = b.addChoice(
			_("&Idioma de la tabla:"),
			[speechLanguages.languageName(lang) for lang in self._languages],
			self._languages.index(self.processor.language) if self.processor.language in self._languages else 0,
		)
		self.languageCtrl.Bind(wx.EVT_CHOICE, self._onLanguage)
		self.filterCtrl = b.addText(_("&Filtrar por:"), size=(300, -1))
		self.list = b.addLabeledControl(
			_("&Símbolos:"),
			lambda p: wx.ListCtrl(p, style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=(600, 280)),
			vertical=True,
			proportion=1,
		)
		for i, (colTitle, width) in enumerate(((_("Símbolo"), 120), (_("Nombre"), 220), (_("Nivel"), 110), (_("Conservar"), 150))):
			self.list.InsertColumn(i, colTitle, width=width)
		g = b.group(_("Cambiar el símbolo seleccionado"))
		self.nameCtrl = g.addText(_("&Nombre:"), size=(300, -1))
		self.levelCtrl = g.addChoice(_("Ni&vel:"), [symbols.LEVEL_NAMES[lvl] for lvl in self._levels], 0)
		self.preserveCtrl = g.addChoice(_("&Conservar el símbolo:"), [lbl for _v, lbl in self._preserve], 0)
		self.addButton, self.removeButton, self.resetButton = _addButtonRow(
			self, main, [(_("&Añadir..."), self._onAdd), (_("&Quitar"), self._onRemove), (_("&Restablecer"), self._onReset)]
		)
		self._okCancelButtons(main, self._onOk)
		self.filterCtrl.Bind(wx.EVT_TEXT, lambda evt: self._refresh(self._selectedSymbol()))
		self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda evt: self._loadFields())
		self.list.Bind(wx.EVT_LIST_ITEM_DESELECTED, lambda evt: self._loadFields())
		self.nameCtrl.Bind(wx.EVT_TEXT, self._onFieldChange)
		self.levelCtrl.Bind(wx.EVT_CHOICE, self._onFieldChange)
		self.preserveCtrl.Bind(wx.EVT_CHOICE, self._onFieldChange)
		self._finishLayout(main, (660, 560))
		self._refresh(None)
		self.list.SetFocus()

	def _row(self, sym: Any) -> list[str]:
		levelName = self._symbolsModule.LEVEL_NAMES.get(sym.level, str(sym.level))
		preserve = dict(self._preserve).get(sym.preserve, sym.preserve)
		return [_symbolDisplay(sym.symbol), sym.name, levelName, preserve]

	def _refresh(self, select: str | None) -> None:
		filt = self.filterCtrl.GetValue().strip().lower()
		self._visible = [
			k
			for k, s in sorted(self.symbols.items(), key=lambda kv: kv[0])
			if not filt or filt in k.lower() or filt in s.name.lower() or filt in _symbolDisplay(k).lower()
		]
		self.list.DeleteAllItems()
		for i, k in enumerate(self._visible):
			row = self._row(self.symbols[k])
			self.list.InsertItem(i, row[0])
			for col in range(1, 4):
				self.list.SetItem(i, col, row[col])
		if self._visible:
			index = self._visible.index(select) if select in self._visible else 0
			self.list.Select(index)
			self.list.Focus(index)
			self.list.EnsureVisible(index)
		self._loadFields()

	def _selectedSymbol(self) -> str | None:
		i = self.list.GetFirstSelected()
		return self._visible[i] if 0 <= i < len(self._visible) else None

	def _loadFields(self) -> None:
		key = self._selectedSymbol()
		has = key is not None
		self._updating = True
		try:
			for ctrl in (self.nameCtrl, self.levelCtrl, self.preserveCtrl, self.removeButton):
				ctrl.Enable(has)
			if has:
				sym = self.symbols[key]
				self.nameCtrl.ChangeValue(sym.name)
				self.levelCtrl.SetSelection(self._levels.index(sym.level) if sym.level in self._levels else len(self._levels) - 1)
				values = [v for v, _l in self._preserve]
				self.preserveCtrl.SetSelection(values.index(sym.preserve) if sym.preserve in values else 0)
			else:
				self.nameCtrl.ChangeValue("")
		finally:
			self._updating = False

	def _onFieldChange(self, evt: wx.CommandEvent) -> None:
		if self._updating:
			return
		key = self._selectedSymbol()
		if key is None:
			return
		sym = self.symbols[key]
		sym.name = self.nameCtrl.GetValue()
		sym.level = self._levels[self.levelCtrl.GetSelection()]
		sym.preserve = self._preserve[self.preserveCtrl.GetSelection()][0]
		i = self._visible.index(key)
		row = self._row(sym)
		for col in range(1, 4):
			self.list.SetItem(i, col, row[col])

	def _onAdd(self, evt: wx.CommandEvent) -> None:
		dlg = wx.TextEntryDialog(self, _("Símbolo:"), _("Añadir símbolo"))
		try:
			if dlg.ShowModal() != wx.ID_OK:
				return
			sym = dlg.GetValue()
		finally:
			dlg.Destroy()
		if not sym:
			return
		if sym not in self.symbols:
			self.symbols[sym] = self._symbolsModule.Symbol(sym, sym, self._symbolsModule.LEVEL_ALL, self._symbolsModule.PRESERVE_NEVER)
		self.filterCtrl.ChangeValue("")
		self._refresh(sym)
		self.nameCtrl.SetFocus()
		self.nameCtrl.SelectAll()

	def _onRemove(self, evt: wx.CommandEvent) -> None:
		key = self._selectedSymbol()
		if key is None:
			return
		i = self._visible.index(key)
		del self.symbols[key]
		nxt = self._visible[i + 1] if i + 1 < len(self._visible) else (self._visible[i - 1] if i > 0 else None)
		self._refresh(nxt)
		self.list.SetFocus()

	def _onReset(self, evt: wx.CommandEvent) -> None:
		if not askYesNo(
			_("¿Seguro que desea restablecer todos los símbolos a los valores de fábrica?"), _("Restablecer símbolos"), self
		):
			return
		Symbol = self._symbolsModule.Symbol
		self.symbols = {k: Symbol(s.symbol, s.name, s.level, s.preserve) for k, s in self.processor.defaults.items()}
		self._tables[self.processor.language] = self.symbols
		self._refresh(self._selectedSymbol())
		self.list.SetFocus()

	def _onLanguage(self, evt: wx.CommandEvent) -> None:
		i = self.languageCtrl.GetSelection()
		if not 0 <= i < len(self._languages):
			return
		lang = self._languages[i]
		proc = self._symbolsModule.getProcessor(lang)
		if proc is None:
			return
		self.processor = proc
		if lang not in self._tables:
			Symbol = self._symbolsModule.Symbol
			self._tables[lang] = {k: Symbol(s.symbol, s.name, s.level, s.preserve) for k, s in proc.symbols.items()}
		self.symbols = self._tables[lang]
		self.filterCtrl.ChangeValue("")
		self._refresh(None)

	def _onOk(self, evt: wx.CommandEvent) -> None:
		if getattr(self, "_saving", False):
			return
		self._saving = True
		symbols = self._symbolsModule
		tables = {lang: dict(table) for lang, table in self._tables.items()}

		def apply() -> str | None:
			# En el núcleo, que es quien lee la tabla al hablar.
			for lang, table in tables.items():
				proc = symbols.getProcessor(lang)
				if proc is None:
					continue
				try:
					proc.replaceSymbols(table)
					proc.saveUser()
				except Exception as e:
					log.exception("No se pudieron guardar los símbolos (%s)", lang)
					return str(e) or e.__class__.__name__
			return None

		def done(error: str | None) -> None:
			if not isAlive(self):
				return
			self._saving = False
			if error:
				showError(_("No se pudieron guardar los símbolos: {error}").format(error=error), self)
				return
			self.closeDialog()

		runOnCore(apply, callback=done)


def showSymbols() -> None:
	"""Abre el diálogo «Puntuación y símbolos»."""
	_showSingleton("symbols", lambda: SymbolsDialog(parentWindow()))


# ====================================================================== bienvenida
class WelcomeDialog(_ModelessDialog):
	dialogKey = "welcome"

	#: Casillas de las teclas que actúan como tecla Tiresias (opción del teclado, etiqueta).
	_MODIFIER_KEYS = (
		("useInsertAsModifier", _("I&nsertar")),
		("useNumpadInsertAsModifier", _("Insertar del teclado numé&rico")),
		("useCapsLockAsModifier", _("&Bloqueo de mayúsculas")),
	)

	def __init__(self, parent: wx.Window | None, imported: bool = False) -> None:
		super().__init__(parent, _("Bienvenido a Tiresias"))
		main = wx.BoxSizer(wx.VERTICAL)
		# Texto en un campo de solo lectura: se puede recorrer con las flechas (#258).
		self.intro = SettingsBuilder(self, main).addText(_("&Información:"), self._introText(imported), style=wx.TE_MULTILINE | wx.TE_READONLY, size=(560, 230))
		# Los controles muestran la configuración actual (tras importar la de NVDA, la importada).
		g = SettingsBuilder(self, main).group(_("Opciones"))
		layouts = [("desktop", _("Sobremesa")), ("laptop", _("Portátil"))]
		self._layouts = [v for v, _l in layouts]
		current = conf["keyboard"]["layout"]
		self.layoutCtrl = g.addChoice(
			_("&Distribución del teclado:"), [lbl for _v, lbl in layouts], self._layouts.index(current) if current in self._layouts else 0
		)
		keys = SettingsBuilder(self, main).group(_("Teclas que actúan como tecla Tiresias"))
		self.modifierCtrls = {key: keys.addCheckBox(label, conf["keyboard"][key]) for key, label in self._MODIFIER_KEYS}
		self.capsCtrl = self.modifierCtrls["useCapsLockAsModifier"]
		g = SettingsBuilder(self, main).group(_("Al iniciar"))
		# Los mismos textos que en Opciones, categoría Generales.
		self.logonCtrl = g.addCheckBox(_("Iniciar Tiresias automáticamente al iniciar &sesión en Windows"), conf["general"]["startOnLogon"])
		self.showCtrl = g.addCheckBox(_("&Mostrar el diálogo de bienvenida al iniciar"), conf["general"]["showWelcomeDialogAtStartup"])
		# Pistas de documentación (#1690): tutorial y manual a un botón.
		_addButtonRow(
			self,
			main,
			[
				(_("&Tutorial de primeros pasos..."), lambda evt: self._openTutorial()),
				(_("Abrir el manual de &usuario"), lambda evt: self._openManual()),
			],
		)
		btn = wx.Button(self, wx.ID_OK, _("Aceptar"))
		main.Add(btn, 0, wx.ALIGN_RIGHT | wx.TOP, 8)
		btn.SetDefault()
		self.SetAffirmativeId(wx.ID_OK)
		self.SetEscapeId(wx.ID_OK)
		btn.Bind(wx.EVT_BUTTON, self._onOk)
		self._finishLayout(main)
		self.intro.SetFocus()

	@staticmethod
	def _introText(imported: bool) -> str:
		menuKeys = _("Tiresias+M o Tiresias+Aplicaciones")
		try:
			from . import gesture_tools

			# Las teclas reales del menú (se pueden cambiar en Opciones > Teclado).
			menuKeys = gesture_tools.describeMenuKeys(keyboardOnly=True)
		except Exception:
			log.debug("No se pudieron leer las teclas del menú", exc_info=True)
		voice = ""
		try:
			from .. import synth

			s = synth.getSynth()
			if s is not None:
				voice = s.description or s.name
		except Exception:
			log.debug("No se pudo leer el sintetizador", exc_info=True)
		parts = []
		if imported:
			parts.append(
				_("Se ha importado su configuración de NVDA. Las opciones de abajo muestran ya los valores importados: revíselas, cambie lo que quiera y pulse Aceptar.")
			)
		parts.append(_("Tiresias es un lector de pantalla: lee en voz alta lo que aparece en la pantalla y le permite manejar Windows con el teclado."))
		parts.append(
			_(
				"La mayoría de órdenes se usan manteniendo pulsada la tecla Tiresias. Las teclas que sirven como tecla Tiresias se eligen abajo; "
				"de fábrica sirven las tres: Insertar, Insertar del teclado numérico y Bloqueo de mayúsculas. Con Bloqueo de mayúsculas como tecla Tiresias, "
				"el bloqueo de mayúsculas se activa o desactiva pulsando esa tecla dos veces seguidas."
			)
		)
		parts.append(
			"\n".join(
				[
					_("Órdenes básicas:"),
					_("{keys}: abre el menú de Tiresias, con las opciones, las herramientas, la ayuda y la salida.").format(keys=menuKeys)
					if menuKeys != _("ninguna")
					else _("El menú de Tiresias no tiene ninguna tecla asignada: se abre desde el icono del área de notificación."),
					_("Tiresias+1: ayuda de entrada; al pulsar una tecla se anuncia qué hace sin ejecutarla."),
					_("Tiresias+Control+V: opciones de voz. Tiresias+Control+S: elegir el sintetizador."),
					_("Tiresias+Q: cierra Tiresias."),
				]
			)
		)
		if voice:
			parts.append(
				_("Voz actual: {voice}. De fábrica, Tiresias usa Eloquence si está disponible y, si no, eSpeak NG.").format(voice=voice)
			)
		parts.append(
			_("El tutorial de primeros pasos le enseña lo básico practicando y el manual de usuario lo explica todo. Los dos tienen un botón aquí debajo y están en el menú Ayuda del menú de Tiresias.")
		)
		return "\n\n".join(parts)

	def _onOk(self, evt: wx.CommandEvent | None = None) -> bool:
		modifiers = {key: ctrl.GetValue() for key, ctrl in self.modifierCtrls.items()}
		if not any(modifiers.values()):
			showError(_("Al menos una tecla debe usarse como tecla Tiresias."), self)
			self.modifierCtrls["useInsertAsModifier"].SetFocus()
			return False
		kb = conf["keyboard"]
		layout = self._layouts[self.layoutCtrl.GetSelection()]
		layoutChanged = kb["layout"] != layout
		if layoutChanged:
			kb["layout"] = layout
		for key, value in modifiers.items():
			# Se aplica en la siguiente pulsación (input.core lo lee en cada tecla).
			if kb[key] != value:
				kb[key] = value
		if layoutChanged:
			from ..input import core as inputCore

			runOnCore(inputCore.manager.updateChain)
		show = self.showCtrl.GetValue()
		if conf["general"]["showWelcomeDialogAtStartup"] != show:
			conf["general"]["showWelcomeDialogAtStartup"] = show
		logon = self.logonCtrl.GetValue()
		if conf["general"]["startOnLogon"] != logon:
			try:
				from .settings import setStartOnLogon

				setStartOnLogon(logon)
				# Solo se escribe en conf si el registro ha cambiado.
				conf["general"]["startOnLogon"] = logon
			except OSError as e:
				showError(_("No se pudo configurar el inicio automático: {error}").format(error=e), self)
		from .. import first_run

		# Primer arranque terminado: ni la pregunta de NVDA ni esta bienvenida forzada vuelven a salir.
		first_run.welcomeAccepted()
		_saveConfig()
		self.closeDialog()
		return True

	def _openTutorial(self) -> None:
		if not self._onOk():
			return
		from . import tutorial

		tutorial.show()

	def _openManual(self) -> None:
		from .. import gui

		gui.showUserManual()

	def onCancel(self) -> None:
		# Cerrar el diálogo de bienvenida equivale a aceptarlo.
		self._onOk()


def showWelcome(imported: bool = False) -> None:
	"""Abre el diálogo de bienvenida (al iniciar o desde el menú Ayuda).

	``imported``: se acaba de importar la configuración de NVDA (primer arranque).
	"""
	_showSingleton("welcome", lambda: WelcomeDialog(parentWindow(), imported))


# ====================================================================== acerca de
class AboutDialog(_ModelessDialog):
	dialogKey = "about"

	def _onCopyVersion(self, evt: wx.CommandEvent) -> None:
		if _copyVersion():
			speakMessageOnCore(_("Versión copiada: {version}").format(version=VERSION))
		else:
			showError(_("No se pudo abrir el portapapeles."), self)

	def __init__(self, parent: wx.Window | None) -> None:
		super().__init__(parent, _("Acerca de {app}").format(app=APP_NAME))
		main = wx.BoxSizer(wx.VERTICAL)
		lines = [
			f"{APP_NAME} {VERSION}",
			_("Lector de pantalla para Windows escrito en Python."),
			COPYRIGHT,
			"",
			_("Tiresias es software libre de código abierto, distribuido con una licencia compatible con la GPL. Puede usarlo, estudiarlo, modificarlo y compartirlo libremente."),
			"",
			_("Python {version}").format(version=sys.version.split()[0]),
			_("wxPython {version}").format(version=wx.version()),
			_("Carpeta de datos: {path}").format(path=paths.DATA_DIR),
		]
		b = SettingsBuilder(self, main)
		self.info = b.addText(_("&Información:"), "\n".join(lines), style=wx.TE_MULTILINE | wx.TE_READONLY, size=(480, 220))
		_addButtonRow(self, main, [(_("&Copiar el número de versión"), self._onCopyVersion)])
		btn = wx.Button(self, wx.ID_OK, _("Aceptar"))
		main.Add(btn, 0, wx.ALIGN_RIGHT | wx.TOP, 8)
		btn.SetDefault()
		self.SetEscapeId(wx.ID_OK)
		btn.Bind(wx.EVT_BUTTON, lambda evt: self.closeDialog())
		self._finishLayout(main)
		self.info.SetFocus()


def _copyVersion() -> bool:
	text = f"{APP_NAME} {VERSION}"
	if wx.TheClipboard.Open():
		try:
			wx.TheClipboard.SetData(wx.TextDataObject(text))
			return True
		finally:
			wx.TheClipboard.Close()
	return False


def showAbout() -> None:
	"""Abre el diálogo «Acerca de Tiresias»."""
	_showSingleton("about", lambda: AboutDialog(parentWindow()))
