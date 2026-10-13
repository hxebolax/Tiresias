"""Diálogo «Importar configuración de NVDA» y pregunta del primer arranque.

Muestra lo que se ha encontrado en la carpeta de NVDA, deja elegir las
categorías (voz, teclado, braille, otras opciones, perfiles, gestos,
diccionarios y símbolos), enseña la vista previa de los cambios y los avisos
de lo que no tiene equivalente, e importa en la configuración normal o en un
perfil nuevo. Antes de importar se hace una copia de seguridad que se puede
deshacer desde el mismo diálogo.

Todo se ejecuta en el hilo de la interfaz: leer la configuración de NVDA es
rápido (archivos de texto pequeños). Lo que hay que aplicar en el núcleo
(sintetizador, línea braille...) lo encola :func:`nvda_import.reloadAfterImport`.
"""

from __future__ import annotations

import os

import wx

from . import message_dialog
from .. import nvda_import
from ..config import conf
from ..i18n import _
from ..log import getLogger
from .helpers import bringToFront, isAlive, runOnGui, speakMessage
from .settings import parentWindow, showError

log = getLogger("gui.nvdaImport")

_dialog: "NvdaImportDialog | None" = None


class NvdaImportDialog(wx.Dialog):
	def __init__(self, parent: wx.Window | None, folder: str | None = None) -> None:
		super().__init__(parent, title=_("Importar configuración de NVDA"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.plan: nvda_import.Plan | None = None
		self.folder = folder or nvda_import.findNvdaConfig() or ""
		main = wx.BoxSizer(wx.VERTICAL)

		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(self, label=_("&Carpeta de la configuración de NVDA:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
		self.folderText = wx.TextCtrl(self, value=self.folder, style=wx.TE_READONLY, size=(420, -1))
		row.Add(self.folderText, 1, wx.EXPAND | wx.RIGHT, 6)
		self.chooseButton = wx.Button(self, label=_("&Elegir carpeta (NVDA portable)..."))
		row.Add(self.chooseButton, 0)
		main.Add(row, 0, wx.EXPAND | wx.BOTTOM, 6)

		main.Add(wx.StaticText(self, label=_("&Lo que se ha encontrado:")), 0, wx.BOTTOM, 2)
		self.summary = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP, size=(-1, 110))
		main.Add(self.summary, 0, wx.EXPAND | wx.BOTTOM, 6)

		main.Add(wx.StaticText(self, label=_("&Qué importar:")), 0, wx.BOTTOM, 2)
		self.categories = wx.CheckListBox(self, choices=[nvda_import.categoryLabel(c) for c in nvda_import.CATEGORIES], size=(-1, 140))
		for i in range(len(nvda_import.CATEGORIES)):
			self.categories.Check(i, True)
		main.Add(self.categories, 0, wx.EXPAND | wx.BOTTOM, 6)

		self.useDefaults = wx.CheckBox(self, label=_("Aplicar también los valores &por defecto de NVDA que no aparecen en su configuración"))
		self.useDefaults.SetValue(True)
		main.Add(self.useDefaults, 0, wx.BOTTOM, 6)

		self.target = wx.RadioBox(
			self,
			label=_("Importar en"),
			choices=[_("la configuración &normal"), _("un perfil nue&vo")],
			majorDimension=1,
			style=wx.RA_SPECIFY_COLS,
		)
		main.Add(self.target, 0, wx.EXPAND | wx.BOTTOM, 4)
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(self, label=_("Nombre del per&fil nuevo:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
		self.profileName = wx.TextCtrl(self, value=_("Como NVDA"), size=(240, -1))
		self.profileName.Enable(False)
		row.Add(self.profileName, 0)
		main.Add(row, 0, wx.BOTTOM, 6)

		main.Add(wx.StaticText(self, label=_("Vis&ta previa de los cambios:")), 0, wx.BOTTOM, 2)
		self.preview = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP, size=(-1, 170))
		main.Add(self.preview, 1, wx.EXPAND | wx.BOTTOM, 6)
		main.Add(wx.StaticText(self, label=_("&Avisos (lo que no tiene equivalente):")), 0, wx.BOTTOM, 2)
		self.notices = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 120))
		main.Add(self.notices, 1, wx.EXPAND | wx.BOTTOM, 6)

		buttons = wx.BoxSizer(wx.HORIZONTAL)
		self.importButton = wx.Button(self, label=_("&Importar"))
		self.undoButton = wx.Button(self, label=_("&Deshacer la última importación"))
		self.reportButton = wx.Button(self, label=_("Ver el inf&orme de la última importación"))
		closeButton = wx.Button(self, wx.ID_CLOSE, _("Ce&rrar"))
		for b in (self.importButton, self.undoButton, self.reportButton):
			buttons.Add(b, 0, wx.RIGHT, 6)
		buttons.AddStretchSpacer()
		buttons.Add(closeButton, 0)
		main.Add(buttons, 0, wx.EXPAND | wx.TOP, 4)

		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(main, 1, wx.EXPAND | wx.ALL, 10)
		self.SetSizer(outer)
		outer.Fit(self)
		self.SetSize((max(self.GetSize()[0], 820), max(self.GetSize()[1], 760)))
		self.CentreOnScreen()
		self.SetEscapeId(wx.ID_CLOSE)

		self.chooseButton.Bind(wx.EVT_BUTTON, self._onChoose)
		self.categories.Bind(wx.EVT_CHECKLISTBOX, lambda evt: self._refreshPreview())
		self.useDefaults.Bind(wx.EVT_CHECKBOX, lambda evt: self._load())
		self.target.Bind(wx.EVT_RADIOBOX, self._onTarget)
		self.importButton.Bind(wx.EVT_BUTTON, self._onImport)
		self.undoButton.Bind(wx.EVT_BUTTON, self._onUndo)
		self.reportButton.Bind(wx.EVT_BUTTON, self._onReport)
		closeButton.Bind(wx.EVT_BUTTON, lambda evt: self.close())
		self.Bind(wx.EVT_CLOSE, lambda evt: self.close())

		self._load()
		self._updateButtons()
		self.categories.SetFocus()

	# ------------------------------------------------------------ datos
	def _selectedCategories(self) -> set[str]:
		return {c for i, c in enumerate(nvda_import.CATEGORIES) if self.categories.IsChecked(i)}

	def _load(self) -> None:
		self.plan = None
		if not self.folder:
			self.summary.SetValue(_("No se ha encontrado la configuración de NVDA instalado. Si usas NVDA portable, elige su carpeta."))
			self.preview.SetValue("")
			self.notices.SetValue("")
			self._updateButtons()
			return
		try:
			with wx.BusyCursor():
				self.plan = nvda_import.buildPlan(self.folder, useNvdaDefaults=self.useDefaults.GetValue())
		except Exception as e:
			log.exception("No se pudo leer la configuración de NVDA")
			self.summary.SetValue(_("No se pudo leer la configuración de NVDA: {error}").format(error=e))
			self._updateButtons()
			return
		self.summary.SetValue("\n".join(self.plan.summary))
		for i, cat in enumerate(nvda_import.CATEGORIES):
			label = nvda_import.categoryLabel(cat) + " " + _("({count})").format(count=self.plan.count(cat))
			self.categories.SetString(i, label)
		self._refreshPreview()

	def _refreshPreview(self) -> None:
		if self.plan is None:
			return
		cats = self._selectedCategories()
		self.preview.SetValue("\n".join(nvda_import.previewLines(self.plan, cats)))
		self.notices.SetValue("\n".join(nvda_import.noticeLines(self.plan, cats)))
		self._updateButtons()

	def _updateButtons(self) -> None:
		self.importButton.Enable(self.plan is not None and bool(self._selectedCategories()) and not conf.readOnly)
		self.undoButton.Enable(nvda_import.canUndo() and not conf.readOnly)
		self.reportButton.Enable(os.path.isfile(os.path.join(_configDir(), nvda_import.REPORT_FILE)))

	# ------------------------------------------------------------ acciones
	def _onChoose(self, evt: wx.CommandEvent) -> None:
		with wx.DirDialog(self, _("Elige la carpeta de NVDA portable o su carpeta userConfig"), defaultPath=self.folder or "", style=wx.DD_DIR_MUST_EXIST) as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			chosen = dlg.GetPath()
		folder = nvda_import.resolveFolder(chosen)
		if folder is None:
			showError(_("En esa carpeta no hay configuración de NVDA (falta nvda.ini, también en «userConfig»)."), self)
			return
		self.folder = folder
		self.folderText.SetValue(folder)
		self._load()

	def _onTarget(self, evt: wx.CommandEvent) -> None:
		self.profileName.Enable(self.target.GetSelection() == 1)
		if self.target.GetSelection() == 1:
			self.profileName.SetFocus()

	def _onImport(self, evt: wx.CommandEvent) -> None:
		if self.plan is None:
			return
		cats = self._selectedCategories()
		profile = self.profileName.GetValue().strip() if self.target.GetSelection() == 1 else None
		existing = nvda_import.findProfileName(conf, profile) if profile is not None else None
		if existing is not None:
			# Sin distinguir mayúsculas: en Windows «Lectura» y «lectura» son el mismo archivo.
			showError(_("Ya existe un perfil llamado «{name}». Escribe otro nombre.").format(name=existing), self)
			self.profileName.SetFocus()
			return
		try:
			with wx.BusyCursor():
				result = nvda_import.applyPlan(self.plan, cats, profile)
		except nvda_import.ImportError_ as e:
			showError(str(e), self)
			return
		except Exception as e:
			log.exception("No se pudo importar la configuración de NVDA")
			showError(_("No se pudo importar: {error}").format(error=e), self)
			if nvda_import.canUndo():
				# Puede haber cambiado algo antes del error: se recarga y se puede deshacer.
				nvda_import.reloadAfterImport()
			self._updateButtons()
			return
		msg = _(
			"Importación terminada: {settings} opciones, {profiles} perfiles, {gestures} gestos, {dicts} entradas de diccionario y {symbols} símbolos.\n\n"
			"Copia de seguridad: {backup}\nInforme: {report}\n\n"
			"Si no te gusta el resultado, pulsa «Deshacer la última importación»."
		).format(
			settings=result.settings,
			profiles=result.profiles,
			gestures=result.gestures,
			dicts=result.dictEntries,
			symbols=result.symbols,
			backup=result.backup,
			report=result.report,
		)
		if profile is not None:
			msg += "\n\n" + _(
				"El perfil «{name}» queda activado para que pruebes los ajustes de NVDA. Para volver a los tuyos, desactívalo en Perfiles de configuración."
			).format(name=profile)
		if result.skipped:
			msg += "\n\n" + _("No se ha importado:") + "\n" + "\n".join(result.skipped)
		if any(c.path == ("general", "language") and c.changes for c in self.plan.changes if c.category in cats):
			msg += "\n\n" + _("El idioma de la interfaz se aplicará al reiniciar Tiresias.")

		def showResult() -> None:
			# Con la configuración ya aplicada (la voz puede haber cambiado).
			if not isAlive(self):
				return
			message_dialog.messageBox(msg, _("Importar configuración de NVDA"), wx.OK | wx.ICON_INFORMATION, self)
			if isAlive(self):
				self._load()
				self._updateButtons()

		nvda_import.reloadAfterImport(then=lambda: runOnGui(showResult), activateProfile=profile)

	def _onUndo(self, evt: wx.CommandEvent) -> None:
		if (
			message_dialog.messageBox(
				_("Se restaurará la configuración de Tiresias que había antes de la última importación. ¿Continuar?"),
				_("Deshacer la importación"),
				wx.YES_NO | wx.ICON_QUESTION,
				self,
			)
			!= wx.YES
		):
			return
		try:
			folder = nvda_import.undoLastImport()
		except nvda_import.ImportError_ as e:
			showError(str(e), self)
			return
		except OSError as e:
			showError(_("No se pudo deshacer: {error}").format(error=e), self)
			return
		nvda_import.reloadAfterImport()
		speakMessage(_("Importación deshecha"))
		message_dialog.messageBox(_("Se ha restaurado la configuración anterior (copia {folder}).").format(folder=folder), _("Deshacer la importación"), wx.OK | wx.ICON_INFORMATION, self)
		self._load()
		self._updateButtons()

	def _onReport(self, evt: wx.CommandEvent) -> None:
		path = os.path.join(_configDir(), nvda_import.REPORT_FILE)
		try:
			with open(path, encoding="utf-8") as f:
				text = f.read()
		except OSError as e:
			showError(_("No se pudo leer el informe: {error}").format(error=e), self)
			return
		from .. import gui

		gui.showBrowseableMessage(text, _("Informe de la importación de NVDA"))

	def close(self) -> None:
		global _dialog
		if _dialog is self:
			_dialog = None
		self.Hide()
		self.Destroy()


def _configDir() -> str:
	from .. import paths

	return paths.configDir()


def show(folder: str | None = None) -> None:
	"""Abre el diálogo (hilo de la interfaz)."""
	global _dialog
	if conf.readOnly:
		showError(_("La configuración es de solo lectura (modo seguro): no se puede importar."), parentWindow())
		return
	if isAlive(_dialog):
		bringToFront(_dialog)
		return
	_dialog = NvdaImportDialog(parentWindow(), folder)
	_dialog.Show()
	bringToFront(_dialog)


def askOnFirstRun(folder: str, onAnswer=None, then=None) -> None:
	"""Primer arranque: ofrece usar los mismos ajustes que NVDA (hilo de la interfaz).

	``onAnswer(importar)`` se llama en cuanto se responde. ``then()`` se llama
	(en el hilo de la interfaz) cuando todo ha terminado: con «No», enseguida;
	con «Sí», con la configuración ya aplicada y el resumen cerrado. Así la
	bienvenida (:mod:`tiresias.first_run`) sale después y con lo importado.
	"""

	finished = False

	def finish() -> None:
		# Una sola vez y pase lo que pase: si no, el primer arranque se quedaría sin bienvenida.
		nonlocal finished
		if finished:
			return
		finished = True
		if then is not None:
			then()

	handedOff = False
	try:
		handedOff = _askAndImport(folder, onAnswer, finish)
	except Exception:
		log.exception("Error en la importación de NVDA del primer arranque")
	finally:
		if not handedOff:
			finish()


def _askAndImport(folder: str, onAnswer, finish) -> bool:
	"""Pregunta e importa. Devuelve ``True`` si ``finish`` lo llamará la recarga."""
	dlg = message_dialog.MessageDialog(
		parentWindow(),
		_("Se ha encontrado la configuración de NVDA. ¿Quieres usar los mismos ajustes en Tiresias?")
		+ "\n\n"
		+ _("Se importarán la voz, el teclado, el braille, las demás opciones, los perfiles, los gestos, los diccionarios y los símbolos. Antes se hace una copia de seguridad, y puedes revisarlo o deshacerlo en Herramientas > Importar configuración de NVDA."),
		_("Configuración de NVDA"),
		wx.YES_NO | wx.ICON_QUESTION,
	)
	try:
		answer = dlg.ShowModal()
	finally:
		dlg.Destroy()
	if onAnswer is not None:
		try:
			onAnswer(answer == wx.ID_YES)
		except Exception:
			log.exception("Error al anotar la respuesta del primer arranque")
	if answer != wx.ID_YES:
		return False
	try:
		with wx.BusyCursor():
			plan = nvda_import.buildPlan(folder)
			result = nvda_import.applyPlan(plan)
	except Exception as e:
		log.exception("No se pudo importar la configuración de NVDA en el primer arranque")
		showError(_("No se pudo importar la configuración de NVDA: {error}").format(error=e), parentWindow())
		if nvda_import.canUndo():
			# Lo que se haya llegado a escribir se aplica (y se puede deshacer desde el menú).
			nvda_import.reloadAfterImport(then=lambda: runOnGui(finish))
			return True
		return False
	msg = _(
		"Listo: {settings} opciones, {profiles} perfiles, {gestures} gestos, {dicts} entradas de diccionario y {symbols} símbolos. "
		"El informe con lo que no tiene equivalente está en {report}."
	).format(
		settings=result.settings,
		profiles=result.profiles,
		gestures=result.gestures,
		dicts=result.dictEntries,
		symbols=result.symbols,
		report=result.report,
	)
	if result.skipped:
		msg += " " + _("No se ha importado: {items}.").format(items="; ".join(result.skipped))
	if any(c.path == ("general", "language") and c.changes for c in plan.changes):
		msg += " " + _("El idioma de la interfaz se aplicará al reiniciar Tiresias.")

	def showResult() -> None:
		try:
			message_dialog.messageBox(msg, _("Configuración de NVDA"), wx.OK | wx.ICON_INFORMATION, parentWindow())
		except Exception:
			log.exception("No se pudo mostrar el resumen de la importación de NVDA")
		finally:
			finish()

	# La configuración se aplica en el núcleo (voz incluida, aunque cambie el
	# sintetizador); el aviso se dice ya con la voz nueva y después se muestra
	# el resumen.
	nvda_import.reloadAfterImport(_("Configuración de NVDA importada"), then=lambda: runOnGui(showResult))
	return True
