"""Diálogos del área de configuración, complementos e instalación.

- Ajustes rápidos: buscar cualquier opción de cualquier panel y cambiarla.
- Gestor de etiquetas personalizadas (ver, editar, borrar, exportar e importar).
- Tienda de complementos (catálogo, instalar, actualizar, registro de cambios).
- Actualización de Tiresias disponible.
- Crear copia portable.
- Reparar los registros COM de accesibilidad.
- Novedades, licencia y restablecer valores de fábrica (con «Deshacer», #19575).

Todo se ejecuta en el hilo de la interfaz; la red y las copias de archivos
van en hilos propios.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Callable

import wx

from . import message_dialog
from .. import APP_NAME, VERSION, paths, queue_handler
from ..config import conf
from ..config import policy as policyModule
from ..i18n import _
from ..log import getLogger
from .helpers import bringToFront, isAlive, normalizeForSearch, speakMessage
from .settings import Field, SettingsBuilder, askYesNo, parentWindow, showError

log = getLogger("gui.systemDialogs")

_dialogs: dict[str, wx.Dialog] = {}


def _single(key: str, factory: Callable[[], wx.Dialog]) -> wx.Dialog:
	dlg = _dialogs.get(key)
	if dlg is None or not isAlive(dlg):
		dlg = factory()
		_dialogs[key] = dlg
		dlg.Show()
	bringToFront(dlg)
	return dlg


class _Dialog(wx.Dialog):
	key = ""

	def __init__(self, title: str) -> None:
		super().__init__(parentWindow(), title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		#: Se marca al cerrar: los hilos de descarga lo consultan sin tocar wx.
		self.closed = threading.Event()
		self.Bind(wx.EVT_CLOSE, lambda evt: self.close())

	def close(self) -> None:
		self.closed.set()
		if _dialogs.get(self.key) is self:
			_dialogs.pop(self.key, None)
		self.Hide()
		self.Destroy()

	def finish(self, main: wx.Sizer, minSize: tuple[int, int] = (500, 300)) -> None:
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(main, 1, wx.EXPAND | wx.ALL, 10)
		self.SetSizer(outer)
		outer.Fit(self)
		w, h = self.GetSize()
		self.SetSize((max(w, minSize[0]), max(h, minSize[1])))
		self.CentreOnScreen()

	def buttonRow(self, sizer: wx.Sizer, specs: list[tuple[str, Callable[[wx.CommandEvent], None]]]) -> list[wx.Button]:
		row = wx.BoxSizer(wx.HORIZONTAL)
		out = []
		for label, handler in specs:
			b = wx.Button(self, label=label)
			b.Bind(wx.EVT_BUTTON, handler)
			row.Add(b, 0, wx.RIGHT, 6)
			out.append(b)
		sizer.Add(row, 0, wx.TOP | wx.BOTTOM, 4)
		return out

	def closeButton(self, sizer: wx.Sizer) -> wx.Button:
		b = wx.Button(self, wx.ID_CLOSE, _("&Cerrar"))
		sizer.Add(b, 0, wx.ALIGN_RIGHT | wx.TOP, 8)
		self.SetEscapeId(wx.ID_CLOSE)
		b.Bind(wx.EVT_BUTTON, lambda evt: self.close())
		return b


def _runInThread(func: Callable[[], Any], done: Callable[[Any, Exception | None], None]) -> None:
	def run() -> None:
		try:
			result, error = func(), None
		except Exception as e:
			log.debug("Error en segundo plano", exc_info=True)
			result, error = None, e
		wx.CallAfter(done, result, error)

	threading.Thread(target=run, name="Tarea de la interfaz", daemon=True).start()


# ====================================================================== ajustes rápidos
class SettingEntry:
	def __init__(self, panelId: str, panelTitle: str, field: Field, section: str) -> None:
		self.panelId = panelId
		self.panelTitle = panelTitle
		self.field = field
		self.section = section

	@property
	def label(self) -> str:
		return self.field.label.replace("&", "").rstrip(":").strip()

	def choices(self) -> list[tuple[Any, str]]:
		c = self.field.choices
		try:
			return list(c() if callable(c) else (c or []))
		except Exception:
			log.debug("Sin opciones para %s", self.field.key, exc_info=True)
			return []

	def value(self) -> Any:
		try:
			return conf[self.section][self.field.key]
		except KeyError:
			return self.field.default

	def valueText(self, value: Any = None) -> str:
		value = self.value() if value is None else value
		kind = self.field.kind
		if kind == "bool":
			return _("activado") if value else _("desactivado")
		if kind == "choice":
			for v, lbl in self.choices():
				if v == value:
					return lbl
		if kind == "list" and isinstance(value, (list, tuple)):
			return ", ".join(str(v) for v in value)
		if kind == "checklist" and isinstance(value, (list, tuple)):
			labels = dict(self.choices())
			return ", ".join(str(labels.get(v, v)) for v in value) or _("ninguno")
		return str(value)

	@property
	def locked(self) -> bool:
		return conf.isLocked(self.section, self.field.key)


def collectSettings() -> list[SettingEntry]:
	"""Todas las opciones declarativas de todos los paneles de Opciones."""
	from . import settings

	out: list[SettingEntry] = []
	seen: set[tuple[str, str]] = set()
	# En el orden del cuadro de Opciones.
	for panelId in settings.getPanelIds():
		title, cls = settings._panels[panelId]
		if not issubclass(cls, settings.ConfigPanel):
			continue
		try:
			if "getFields" in {k for klass in cls.__mro__ if klass is not settings.ConfigPanel for k in vars(klass)}:
				# getFields no usa el estado del panel: se llama sin crear la ventana.
				fields = cls.getFields(cls.__new__(cls))
			else:
				fields = list(cls.fields)
		except Exception:
			log.debug("No se pudieron leer las opciones del panel %s", panelId, exc_info=True)
			continue
		for f in fields:
			section = f.section or cls.section
			if f.readOnly or (section, f.key) in seen:
				continue
			seen.add((section, f.key))
			out.append(SettingEntry(panelId, title, f, section))
	return out


class QuickSettingsDialog(_Dialog):
	key = "quickSettings"

	def __init__(self) -> None:
		super().__init__(_("Ajustes rápidos"))
		self.entries = collectSettings()
		self.visible: list[SettingEntry] = []
		self.editor: wx.Window | None = None
		self.editorValues: list[Any] = []
		main = wx.BoxSizer(wx.VERTICAL)
		b = SettingsBuilder(self, main)
		self.filter = b.addText(_("&Buscar opción:"), size=(360, -1))
		self.list = b.addLabeledControl(
			_("&Opciones:"), lambda p: wx.ListCtrl(p, style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=(680, 300)), vertical=True, proportion=1
		)
		for i, (t, w) in enumerate(((_("Opción"), 360), (_("Categoría"), 150), (_("Valor"), 160))):
			self.list.InsertColumn(i, t, width=w)
		self.box = wx.StaticBoxSizer(wx.VERTICAL, self, _("Cambiar la opción seleccionada"))
		main.Add(self.box, 0, wx.EXPAND | wx.TOP, 6)
		self.editorSizer = wx.BoxSizer(wx.VERTICAL)
		self.box.Add(self.editorSizer, 0, wx.EXPAND | wx.ALL, 4)
		self.applyButton, self.openButton = self.buttonRow(
			main, [(_("A&plicar"), self._onApply), (_("&Abrir en Opciones"), self._onOpen)]
		)
		self.closeButton(main)
		self.filter.Bind(wx.EVT_TEXT, lambda evt: self._refresh())
		self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda evt: self._buildEditor())
		self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda evt: self._focusEditor())
		self.finish(main, (720, 560))
		self._refresh()
		self.filter.SetFocus()

	def _refresh(self) -> None:
		query = normalizeForSearch(self.filter.GetValue())
		words = query.split()
		self.visible = []
		for e in self.entries:
			hay = normalizeForSearch(f"{e.label} {e.panelTitle} {e.section} {e.field.key}")
			if all(w in hay for w in words):
				self.visible.append(e)
		self.list.DeleteAllItems()
		for i, e in enumerate(self.visible):
			self.list.InsertItem(i, e.label + (" " + _("(bloqueada)") if e.locked else ""))
			self.list.SetItem(i, 1, e.panelTitle)
			self.list.SetItem(i, 2, e.valueText())
		if self.visible:
			self.list.Select(0)
			self.list.Focus(0)
		self._buildEditor()

	def _selected(self) -> SettingEntry | None:
		i = self.list.GetFirstSelected()
		return self.visible[i] if 0 <= i < len(self.visible) else None

	def _buildEditor(self) -> None:
		self.editorSizer.Clear(True)
		self.editor = None
		self.editorValues = []
		e = self._selected()
		box = self.box.GetStaticBox()
		if e is None:
			self.applyButton.Enable(False)
			self.openButton.Enable(False)
			self.Layout()
			return
		f = e.field
		b = SettingsBuilder(box, self.editorSizer)
		value = e.value()
		if f.kind == "bool":
			self.editor = b.addCheckBox(e.label, bool(value))
		elif f.kind in ("int", "slider"):
			try:
				iv = int(value)
			except (TypeError, ValueError):
				iv = f.minVal
			self.editor = b.addSpin(e.label + ":", f.minVal, f.maxVal, iv)
		elif f.kind == "choice":
			choices = e.choices()
			self.editorValues = [v for v, _l in choices]
			labels = [lbl for _v, lbl in choices]
			if value not in self.editorValues:
				self.editorValues.append(value)
				labels.append(str(value))
			self.editor = b.addChoice(e.label + ":", labels, self.editorValues.index(value))
		elif f.kind == "checklist":
			# Lista de casillas: el valor es la lista de los marcados (no un texto).
			choices = e.choices()
			self.editorValues = [v for v, _l in choices]
			current = list(value or [])
			self.editor = b.addLabeledControl(e.label + ":", lambda p: wx.CheckListBox(p, choices=[lbl for _v, lbl in choices], size=(360, -1)), vertical=True)
			for i, v in enumerate(self.editorValues):
				self.editor.Check(i, v in current)
		else:
			text = ", ".join(str(v) for v in value) if f.kind == "list" and isinstance(value, (list, tuple)) else str(value if value is not None else "")
			self.editor = b.addText(e.label + ":", text, size=(360, -1))
		if e.locked:
			self.editor.Enable(False)
			b.addStaticText(policyModule.blockedMessage())
		self.applyButton.Enable(not e.locked)
		self.openButton.Enable(True)
		self.Layout()

	def _focusEditor(self) -> None:
		if self.editor is not None and self.editor.IsEnabled():
			self.editor.SetFocus()

	def _readEditor(self, e: SettingEntry) -> Any:
		ctrl = self.editor
		kind = e.field.kind
		if kind == "bool":
			return ctrl.GetValue()
		if kind in ("int", "slider"):
			return int(ctrl.GetValue())
		if kind == "choice":
			i = ctrl.GetSelection()
			return self.editorValues[i] if 0 <= i < len(self.editorValues) else e.value()
		if kind == "list":
			return [p.strip() for p in ctrl.GetValue().split(",") if p.strip()]
		if kind == "checklist":
			return [v for i, v in enumerate(self.editorValues) if ctrl.IsChecked(i)]
		return ctrl.GetValue()

	def _onApply(self, evt: wx.CommandEvent) -> None:
		e = self._selected()
		if e is None or self.editor is None or e.locked:
			return
		new = self._readEditor(e)
		old = e.value()
		if new != old:
			conf[e.section][e.field.key] = new
			applyPanelChange(e, old, new)
			from .. import core

			queue_handler.queueFunction(core.applyConfiguration)
		i = self.list.GetFirstSelected()
		self.list.SetItem(i, 2, e.valueText(new))
		speakMessage(_("{option}: {value}").format(option=e.label, value=e.valueText(new)))

	def _onOpen(self, evt: wx.CommandEvent) -> None:
		e = self._selected()
		if e is None:
			return
		from . import settings

		self.close()
		settings.showSettings(e.panelId)


def applyPanelChange(e: SettingEntry, old: Any, new: Any) -> None:
	"""Lo mismo que hace el panel de Opciones al guardar la opción (su ``afterSave``).

	Ningún ``afterSave`` usa el estado del panel, así que se llama sin crear la
	ventana. Si el panel no tiene ``afterSave`` propio, se aplican los efectos
	inmediatos conocidos (:func:`applySettingChange`).
	"""
	from . import settings

	cls = settings._panels.get(e.panelId, (None, None))[1]
	if cls is not None and issubclass(cls, settings.ConfigPanel) and cls.afterSave is not settings.ConfigPanel.afterSave:
		try:
			cls.afterSave(cls.__new__(cls), {(e.section, e.field.key): (old, new)})
			return
		except Exception:
			log.exception("Error aplicando %s.%s desde los ajustes rápidos", e.section, e.field.key)
	applySettingChange(e.section, e.field.key, new)


def applySettingChange(section: str, key: str, value: Any) -> None:
	"""Efectos inmediatos de algunas opciones (los mismos que en el diálogo de opciones)."""
	if (section, key) == ("general", "logLevel"):
		from .. import log as logModule

		logModule.setLevel(value)
	elif (section, key) == ("general", "startOnLogon"):
		from . import settings

		try:
			settings.setStartOnLogon(bool(value))
		except OSError as e:
			showError(_("No se pudo configurar el inicio automático: {error}").format(error=e))
	elif (section, key) == ("braille", "display"):
		from .. import braille

		queue_handler.queueFunction(braille.handler.setDisplay, value)


def showQuickSettings() -> None:
	_single("quickSettings", QuickSettingsDialog)


# ====================================================================== etiquetas
class LabelsManagerDialog(_Dialog):
	key = "labels"

	def __init__(self) -> None:
		super().__init__(_("Etiquetas personalizadas"))
		from .. import labels

		self.labels = labels
		self.apps: list[str] = []
		self.keys: list[str] = []
		main = wx.BoxSizer(wx.VERTICAL)
		b = SettingsBuilder(self, main)
		self.appList = b.addLabeledControl(_("&Aplicaciones:"), lambda p: wx.ListBox(p, size=(300, 140)), vertical=True)
		self.list = b.addLabeledControl(
			_("&Etiquetas de la aplicación:"), lambda p: wx.ListCtrl(p, style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=(600, 220)), vertical=True, proportion=1
		)
		self.list.InsertColumn(0, _("Etiqueta"), width=260)
		self.list.InsertColumn(1, _("Control"), width=320)
		(self.editButton, self.deleteButton, self.deleteAppButton) = self.buttonRow(
			main,
			[
				(_("E&ditar..."), self._onEdit),
				(_("&Borrar"), self._onDelete),
				(_("Borrar &todas las de la aplicación"), self._onDeleteApp),
			],
		)
		self.buttonRow(main, [(_("E&xportar..."), self._onExport), (_("&Importar..."), self._onImport)])
		self.closeButton(main)
		self.appList.Bind(wx.EVT_LISTBOX, lambda evt: self._refreshLabels())
		self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._onEdit)
		self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda evt: self._update())
		self.finish(main, (640, 520))
		self._refreshApps()
		self.appList.SetFocus()

	def _refreshApps(self, select: str | None = None) -> None:
		self.apps = self.labels.listApps()
		self.appList.Set(self.apps or [])
		if self.apps:
			self.appList.SetSelection(self.apps.index(select) if select in self.apps else 0)
		self._refreshLabels()

	def _app(self) -> str | None:
		i = self.appList.GetSelection()
		return self.apps[i] if 0 <= i < len(self.apps) else None

	def _refreshLabels(self, select: int = 0) -> None:
		app = self._app()
		data = self.labels.getAll(app) if app else {}
		self.keys = sorted(data, key=lambda k: data[k].lower())
		self.list.DeleteAllItems()
		for i, k in enumerate(self.keys):
			self.list.InsertItem(i, data[k])
			self.list.SetItem(i, 1, self.labels.describeKey(k))
		if self.keys:
			select = max(0, min(select, len(self.keys) - 1))
			self.list.Select(select)
			self.list.Focus(select)
		self._update()

	def _update(self) -> None:
		has = self.list.GetFirstSelected() >= 0
		self.editButton.Enable(has)
		self.deleteButton.Enable(has)
		self.deleteAppButton.Enable(self._app() is not None)

	def _selectedKey(self) -> str | None:
		i = self.list.GetFirstSelected()
		return self.keys[i] if 0 <= i < len(self.keys) else None

	def _onEdit(self, evt: Any) -> None:
		app, key = self._app(), self._selectedKey()
		if not app or not key:
			return
		current = self.labels.getAll(app).get(key, "")
		dlg = wx.TextEntryDialog(self, _("Nueva etiqueta (vacía para borrarla):"), _("Editar etiqueta"), current)
		try:
			if dlg.ShowModal() != wx.ID_OK:
				return
			value = dlg.GetValue().strip()
		finally:
			dlg.Destroy()
		i = self.list.GetFirstSelected()
		self.labels.setLabelByKey(app, key, value or None)
		self._refreshApps(app) if not value and len(self.keys) == 1 else self._refreshLabels(i)
		self.list.SetFocus()

	def _onDelete(self, evt: Any) -> None:
		app, key = self._app(), self._selectedKey()
		if not app or not key:
			return
		i = self.list.GetFirstSelected()
		self.labels.setLabelByKey(app, key, None)
		if len(self.keys) == 1:
			self._refreshApps()
		else:
			self._refreshLabels(i)
		speakMessage(_("Etiqueta borrada"))

	def _onDeleteApp(self, evt: Any) -> None:
		app = self._app()
		if not app or not askYesNo(_("¿Borrar todas las etiquetas de «{app}»?").format(app=app), _("Borrar etiquetas"), self):
			return
		self.labels.deleteApp(app)
		self._refreshApps()

	def _onExport(self, evt: Any) -> None:
		dlg = wx.FileDialog(self, _("Exportar etiquetas"), defaultFile="etiquetas-tiresias.json", wildcard=_("Archivos JSON (*.json)|*.json"), style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
		try:
			if dlg.ShowModal() != wx.ID_OK:
				return
			path = dlg.GetPath()
		finally:
			dlg.Destroy()
		try:
			n = self.labels.exportLabels(path)
		except OSError as e:
			showError(_("No se pudieron exportar las etiquetas: {error}").format(error=e), self)
			return
		message_dialog.messageBox(_("Se han exportado {n} etiquetas.").format(n=n), _("Exportar etiquetas"), wx.OK | wx.ICON_INFORMATION, self)

	def _onImport(self, evt: Any) -> None:
		dlg = wx.FileDialog(self, _("Importar etiquetas"), wildcard=_("Archivos JSON (*.json)|*.json"), style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
		try:
			if dlg.ShowModal() != wx.ID_OK:
				return
			path = dlg.GetPath()
		finally:
			dlg.Destroy()
		try:
			n = self.labels.importLabels(path)
		except (OSError, ValueError) as e:
			showError(_("No se pudieron importar las etiquetas: {error}").format(error=e), self)
			return
		self._refreshApps(self._app())
		message_dialog.messageBox(_("Se han importado {n} etiquetas.").format(n=n), _("Importar etiquetas"), wx.OK | wx.ICON_INFORMATION, self)


def showLabelsManager() -> None:
	_single("labels", LabelsManagerDialog)


# ====================================================================== tienda de complementos
_STORE_FILTERS = [("available", _("Disponibles para instalar")), ("update", _("Actualizaciones")), ("installed", _("Instalados")), ("all", _("Todos"))]


def _statusLabel(status: str) -> str:
	return {
		"available": _("No instalado"),
		"installed": _("Instalado"),
		"update": _("Actualización disponible"),
		"older": _("Instalada una versión más reciente"),
		"incompatible": _("Incompatible"),
	}.get(status, status)


class AddonStoreDialog(_Dialog):
	key = "addonStore"

	def __init__(self) -> None:
		super().__init__(_("Tienda de complementos"))
		self.entries: list = []
		self.visible: list = []
		self.source = ""
		self.changed = False
		self.busy = False
		main = wx.BoxSizer(wx.VERTICAL)
		b = SettingsBuilder(self, main)
		self.filter = b.addChoice(_("&Mostrar:"), [lbl for _k, lbl in _STORE_FILTERS], 0)
		self.search = b.addText(_("&Buscar:"), size=(300, -1))
		self.list = b.addLabeledControl(
			_("Com&plementos:"), lambda p: wx.ListCtrl(p, style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=(680, 240)), vertical=True, proportion=1
		)
		for i, (t, w) in enumerate(((_("Nombre"), 220), (_("Versión"), 80), (_("Estado"), 200), (_("Autor"), 160))):
			self.list.InsertColumn(i, t, width=w)
		self.details = b.addText(_("&Detalles:"), "", style=wx.TE_MULTILINE | wx.TE_READONLY, size=(680, 140))
		self.status = wx.StaticText(self, label=_("Cargando el catálogo..."))
		main.Add(self.status, 0, wx.BOTTOM, 4)
		self.installButton, self.webButton, self.reloadButton = self.buttonRow(
			main, [(_("&Instalar"), self._onInstall), (_("Página &web"), self._onWeb), (_("&Recargar el catálogo"), lambda evt: self._load())]
		)
		self.closeButton(main)
		self.filter.Bind(wx.EVT_CHOICE, lambda evt: self._refresh())
		self.search.Bind(wx.EVT_TEXT, lambda evt: self._refresh())
		self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda evt: self._details())
		self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._onInstall)
		self.finish(main, (720, 600))
		self.list.SetFocus()
		self._load()

	def _load(self) -> None:
		from .. import addon_store, addons

		self.status.SetLabel(_("Cargando el catálogo..."))
		self.reloadButton.Enable(False)

		def work():
			if not addons.getAddons():
				addons.discover()
			return addon_store.fetchCatalog()

		_runInThread(work, self._onLoaded)

	def _onLoaded(self, result: Any, error: Exception | None) -> None:
		if not isAlive(self):
			return
		self.reloadButton.Enable(True)
		if error is not None:
			self.status.SetLabel(_("No se pudo cargar el catálogo: {error}").format(error=error))
			speakMessage(self.status.GetLabel())
			return
		self.entries, self.source = result
		ups = sum(1 for e in self.entries if e.status() == "update")
		msg = _("{n} complementos en el catálogo; {u} actualizaciones.").format(n=len(self.entries), u=ups)
		self.status.SetLabel(msg)
		if ups and self.filter.GetSelection() == 0:
			self.filter.SetSelection(1)
		self._refresh()
		speakMessage(msg)

	def _refresh(self) -> None:
		kind = _STORE_FILTERS[max(0, self.filter.GetSelection())][0]
		words = normalizeForSearch(self.search.GetValue()).split()
		out = []
		for e in self.entries:
			st = e.status()
			# Instalado o no según la carpeta de complementos: un complemento instalado
			# cuya entrada del catálogo es incompatible sigue siendo «instalado».
			installed = e.installedAddon() is not None
			if kind == "available" and installed:
				continue
			if kind == "update" and st != "update":
				continue
			if kind == "installed" and not installed:
				continue
			hay = normalizeForSearch(f"{e.name} {e.description} {e.author}")
			if all(w in hay for w in words):
				out.append(e)
		self.visible = sorted(out, key=lambda e: e.name.lower())
		self.list.DeleteAllItems()
		for i, e in enumerate(self.visible):
			self.list.InsertItem(i, e.name)
			self.list.SetItem(i, 1, e.version)
			self.list.SetItem(i, 2, _statusLabel(e.status()))
			self.list.SetItem(i, 3, e.author)
		if self.visible:
			self.list.Select(0)
			self.list.Focus(0)
		self._details()

	def _selected(self) -> Any:
		i = self.list.GetFirstSelected()
		return self.visible[i] if 0 <= i < len(self.visible) else None

	def _details(self) -> None:
		e = self._selected()
		if e is None:
			self.details.SetValue("")
			self.installButton.Enable(False)
			self.webButton.Enable(False)
			return
		st = e.status()
		lines = [e.description or _("Sin descripción.")]
		if e.extra.get("proprietary"):
			lines.append(_("Software propietario de sus titulares: para usarlo necesitas una licencia válida."))
		inst = e.installedAddon()
		if inst is not None:
			lines.append(_("Versión instalada: {v}").format(v=inst.version))
		if e.changelog:
			lines += ["", _("Cambios de esta versión:"), e.changelog]
		if e.isTooNew:
			lines.append(_("Requiere una versión más reciente de Tiresias."))
		elif e.isUntested:
			lines.append(_("No se ha probado con esta versión de Tiresias."))
		if e.size:
			lines.append(_("Tamaño: {kb} KB").format(kb=max(1, e.size // 1024)))
		self.details.SetValue("\n".join(lines))
		self.installButton.SetLabel(_("&Actualizar") if st == "update" else (_("R&einstalar") if st in ("installed", "older") else _("&Instalar")))
		self.installButton.Enable(st != "incompatible" and not self.busy)
		self.webButton.Enable(bool(e.homepage))

	def _onInstall(self, evt: Any) -> None:
		from .. import addon_store

		e = self._selected()
		if e is None or self.busy or e.isTooNew:
			return
		if e.status() == "older" and not askYesNo(
			_("Tiene instalada una versión más reciente de «{name}». ¿Instalar la {version} del catálogo?").format(name=e.name, version=e.version), self.GetTitle(), self
		):
			return
		if e.extra.get("proprietary") and e.installedAddon() is None and not askYesNo(
			_("«{name}» es software propietario de sus titulares y no forma parte del software libre de Tiresias. Para usarlo necesitas una licencia válida. ¿Instalarlo?").format(name=e.name), self.GetTitle(), self
		):
			return
		self.busy = True
		self.installButton.Enable(False)
		self.status.SetLabel(_("Descargando {name}...").format(name=e.name))
		speakMessage(self.status.GetLabel())
		last = [-1]

		def progress(done: int, total: int) -> bool:
			if total:
				pct = done * 100 // total
				if pct // 25 != last[0] // 25:
					last[0] = pct
					wx.CallAfter(self._setStatus, _("Descargando {name}: {pct} %").format(name=e.name, pct=pct))
			return not self.closed.is_set()

		_runInThread(lambda: addon_store.installEntry(e, progress), lambda r, err: self._onInstalled(e, r, err))

	def _setStatus(self, text: str) -> None:
		if isAlive(self):
			self.status.SetLabel(text)

	def _onInstalled(self, entry: Any, addon: Any, error: Exception | None) -> None:
		if not isAlive(self):
			if error is None and addon is not None:
				# La tienda se cerró mientras se instalaba: que no pase desapercibido.
				speakMessage(_("«{name}» {version} instalado. Reinicie Tiresias para usarlo.").format(name=addon.name, version=addon.version))
			return
		self.busy = False
		if error is not None:
			self.status.SetLabel(_("No se pudo instalar: {error}").format(error=error))
			showError(self.status.GetLabel(), self)
		else:
			self.changed = True
			self.status.SetLabel(_("«{name}» {version} instalado. Reinicie Tiresias para usarlo.").format(name=addon.name, version=addon.version))
			speakMessage(self.status.GetLabel())
		self._refresh()

	def _onWeb(self, evt: Any) -> None:
		e = self._selected()
		if e is not None and e.homepage.lower().startswith(("http://", "https://")):
			# Solo páginas web: una dirección del catálogo nunca abre programas ni archivos.
			import webbrowser

			webbrowser.open(e.homepage)

	def close(self) -> None:
		changed = self.changed
		super().close()
		if changed and askYesNo(_("¿Reiniciar Tiresias ahora para usar los complementos instalados?"), _("Tienda de complementos"), parentWindow()):
			from .. import core

			queue_handler.queueFunction(core.restart)


def showAddonStore() -> None:
	if not policyModule.isAllowed("addonStore"):
		showError(policyModule.blockedMessage(), parentWindow(), _("Tienda de complementos"))
		return
	_single("addonStore", AddonStoreDialog)


# ====================================================================== actualización de Tiresias
class UpdateDialog(_Dialog):
	key = "update"

	def __init__(self, info: Any) -> None:
		super().__init__(_("Actualización de {app}").format(app=APP_NAME))
		self.info = info
		self.busy = False
		main = wx.BoxSizer(wx.VERTICAL)
		b = SettingsBuilder(self, main)
		text = _("Hay una versión nueva de {app}: {new} (tiene la {old}).").format(app=APP_NAME, new=info.version, old=VERSION)
		if getattr(info, "channel", "estable") == "beta":
			text += " " + _("Es una versión de prueba (canal beta).")
		if getattr(info, "size", 0):
			text += " " + _("Tamaño de la descarga: {mb:.1f} MB.").format(mb=info.size / (1024 * 1024))
		if info.notes:
			text += "\n\n" + info.notes
		# Texto en un campo de solo lectura para poder recorrerlo (#258).
		self.text = b.addText(_("&Información:"), text, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(520, 160))
		self.status = wx.StaticText(self, label="")
		main.Add(self.status, 0, wx.BOTTOM, 4)
		self.installButton, self.notesButton, self.skipButton = self.buttonRow(
			main,
			[(_("&Descargar e instalar"), self._onInstall), (_("Ver las &novedades"), self._onNotes), (_("&Omitir esta versión"), self._onSkip)],
		)
		self.notesButton.Enable(bool(info.notesUrl))
		self.installButton.Enable(bool(info.url))
		self.closeButton(main).SetLabel(_("&Recordar más tarde"))
		self.finish(main, (560, 340))
		self.text.SetFocus()

	def _onNotes(self, evt: Any) -> None:
		import webbrowser

		webbrowser.open(self.info.notesUrl)

	def _onSkip(self, evt: Any) -> None:
		# Estado del programa, no del perfil activo.
		conf.setGlobal("update", "skippedVersion", self.info.version)
		from .. import updates

		if updates.pendingUpdate is not None and updates.pendingUpdate.version == self.info.version:
			# El menú Ayuda deja de ofrecerla.
			updates.pendingUpdate = None
		self.close()

	def _onInstall(self, evt: Any) -> None:
		from .. import updates

		if self.busy:
			return
		self.busy = True
		self.installButton.Enable(False)
		last = [-1]

		def progress(done: int, total: int) -> bool:
			if total:
				pct = done * 100 // total
				if pct // 10 != last[0] // 10:
					last[0] = pct
					wx.CallAfter(self._status, _("Descargando: {pct} %").format(pct=pct))
			return not self.closed.is_set()

		def work() -> tuple[str, str | None]:
			# Descarga y, si es una copia portable, descompresión: todo fuera de la interfaz.
			path = updates.downloadUpdate(self.info, progress)
			return path, updates.preparePackage(path)

		self._status(_("Descargando la actualización..."))
		_runInThread(work, self._onDownloaded)

	def _status(self, text: str) -> None:
		if isAlive(self):
			self.status.SetLabel(text)
			speakMessage(text)

	def _onDownloaded(self, result: Any, error: Exception | None) -> None:
		from .. import updates

		if not isAlive(self):
			return
		self.busy = False
		if error is not None:
			self.installButton.Enable(True)
			self._status(_("No se pudo descargar: {error}").format(error=error))
			return
		path, prepared = result
		self._status(updates.applyMessage(path))
		try:
			updates.installDownloaded(path, prepared)
		except Exception as e:
			log.exception("No se pudo aplicar la actualización")
			self.installButton.Enable(True)
			showError(_("No se pudo abrir el instalador: {error}").format(error=e), self)
			return
		self.close()


def showUpdateDialog(info: Any) -> None:
	dlg = _dialogs.get("update")
	if dlg is not None and isAlive(dlg):
		dlg.close()
	_single("update", lambda: UpdateDialog(info))


# ====================================================================== copia portable
class CreatePortableDialog(_Dialog):
	key = "portable"

	def __init__(self) -> None:
		super().__init__(_("Crear copia portable"))
		main = wx.BoxSizer(wx.VERTICAL)
		b = SettingsBuilder(self, main)
		intro = _(
			"Una copia portable funciona sin instalar desde cualquier carpeta, por ejemplo una memoria USB. "
			"Elija una carpeta vacía (o una copia portable anterior para actualizarla)."
		)
		b.addText(_("Información:"), intro, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(480, 70))
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(self, label=_("&Carpeta de destino:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
		default = os.path.join(os.path.expanduser("~"), "Desktop", "Tiresias portable")
		self.path = wx.TextCtrl(self, value=default, size=(320, -1))
		row.Add(self.path, 1, wx.ALIGN_CENTER_VERTICAL)
		browse = wx.Button(self, label=_("E&xaminar..."))
		row.Add(browse, 0, wx.LEFT, 6)
		main.Add(row, 0, wx.EXPAND | wx.BOTTOM, 6)
		self.copyConfig = b.addCheckBox(_("Copiar la configuración &actual (opciones, perfiles, gestos, etiquetas, diccionarios)"), True)
		self.copyAddons = b.addCheckBox(_("Copiar los complementos &instalados"), True)
		self.launch = b.addCheckBox(_("Abrir la carpeta al &terminar"), False)
		self.okButton, = self.buttonRow(main, [(_("C&rear"), self._onCreate)])
		self.closeButton(main).SetLabel(_("Ca&ncelar"))
		browse.Bind(wx.EVT_BUTTON, self._onBrowse)
		self.finish(main, (560, 320))
		self.path.SetFocus()

	def _onBrowse(self, evt: Any) -> None:
		dlg = wx.DirDialog(self, _("Carpeta de la copia portable"), self.path.GetValue())
		try:
			if dlg.ShowModal() == wx.ID_OK:
				self.path.SetValue(dlg.GetPath())
		finally:
			dlg.Destroy()

	def _onCreate(self, evt: Any) -> None:
		from .. import installer

		dest = self.path.GetValue().strip()
		if not dest:
			showError(_("Escriba la carpeta de destino."), self)
			return
		self.okButton.Enable(False)
		speakMessage(_("Creando la copia portable..."))
		cfg, add, launch = self.copyConfig.GetValue(), self.copyAddons.GetValue(), self.launch.GetValue()

		def done(result: Any, error: Exception | None) -> None:
			if not isAlive(self):
				return
			self.okButton.Enable(True)
			if error is not None:
				showError(_("No se pudo crear la copia portable: {error}").format(error=error), self)
				return
			message_dialog.messageBox(_("Copia portable creada en:\n{path}").format(path=result), self.GetTitle(), wx.OK | wx.ICON_INFORMATION, self)
			if launch:
				try:
					os.startfile(result)
				except OSError:
					pass
			self.close()

		_runInThread(lambda: installer.createPortableCopy(dest, copyConfig=cfg, copyAddons=add), done)


def showCreatePortable() -> None:
	if not policyModule.isAllowed("createPortable"):
		showError(policyModule.blockedMessage(), parentWindow(), _("Crear copia portable"))
		return
	_single("portable", CreatePortableDialog)


# ====================================================================== reparación COM
def runComRepair() -> None:
	from .. import comrepair

	if not askYesNo(
		_(
			"Esta herramienta vuelve a registrar las bibliotecas de accesibilidad de Windows. Sirve cuando Tiresias no lee los navegadores, "
			"los menús o los cuadros de diálogo, por ejemplo después de desinstalar programas o de usar limpiadores del registro.\n\n"
			"Necesita permiso de administrador y tarda unos segundos. ¿Continuar?"
		),
		_("Reparar los registros COM"),
		parentWindow(),
	):
		return
	speakMessage(_("Reparando los registros COM..."))

	def done(code: Any, error: Exception | None) -> None:
		if error is not None:
			showError(_("No se pudo ejecutar la reparación: {error}").format(error=error), parentWindow())
		elif code == 0:
			message_dialog.messageBox(_("La reparación ha terminado. Reinicie Windows para que todos los programas usen los registros reparados."), _("Reparar los registros COM"), wx.OK | wx.ICON_INFORMATION)
		elif code == 5:
			showError(_("La reparación necesita permiso de administrador."), parentWindow())
		else:
			showError(_("Algunas bibliotecas no se pudieron registrar (código {code}). Consulte el registro de Tiresias.").format(code=code), parentWindow())

	_runInThread(comrepair.runElevated, done)


# ====================================================================== novedades, licencia y restablecer
def showNews() -> None:
	from .. import startup

	path = startup.newsPath()
	try:
		os.startfile(path)
	except OSError:
		showError(_("No se encontró el documento de novedades:\n{path}").format(path=path), parentWindow(), _("Novedades"))


def showLicense() -> None:
	from . import dialogs

	for p in (os.path.join(paths.APP_DIR, "LICENSE.txt"), os.path.join(paths.APP_DIR, "LICENCIA.txt")):
		if os.path.isfile(p):
			with open(p, encoding="utf-8", errors="replace") as f:
				dialogs.showBrowseableMessage(f.read(), _("Licencia"))
			return
	showError(_("No se encontró el archivo de licencia."), parentWindow(), _("Licencia"))


def askFactoryReset(parent: wx.Window | None = None) -> bool:
	"""Pide confirmación, restablece y ofrece deshacer (#19575)."""
	if not policyModule.isAllowed("factoryReset"):
		showError(policyModule.blockedMessage(), parent or parentWindow())
		return False
	if not askYesNo(
		_("¿Seguro que desea restablecer toda la configuración a los valores de fábrica? Los perfiles se conservan."),
		_("Restablecer valores de fábrica"),
		parent or parentWindow(),
	):
		return False
	resetToFactory()
	offerUndo(parent)
	return True


def resetToFactory() -> None:
	from .. import core

	conf.resetToFactoryDefaults()
	queue_handler.queueFunction(core.applyConfiguration)


def offerUndo(parent: wx.Window | None = None) -> None:
	dlg = message_dialog.MessageDialog(
		parent or parentWindow(),
		_("Se han restablecido los valores de fábrica. Si ha sido un error, puede deshacerlo ahora o más tarde desde Preferencias > Deshacer el restablecimiento de fábrica (hasta que cierre Tiresias)."),
		_("Restablecer valores de fábrica"),
		wx.YES_NO | wx.NO_DEFAULT | wx.ICON_INFORMATION,
	)
	dlg.SetYesNoLabels(_("&Deshacer"), _("&Aceptar"))
	try:
		if dlg.ShowModal() == wx.ID_YES:
			undoFactoryReset()
	finally:
		dlg.Destroy()


def undoFactoryReset() -> None:
	from .. import core

	if conf.undoFactoryReset():
		queue_handler.queueFunction(core.applyConfiguration)
		speakMessage(_("Configuración anterior recuperada"))
	else:
		speakMessage(_("No hay nada que deshacer"))
