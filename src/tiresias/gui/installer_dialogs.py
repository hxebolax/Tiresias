"""Diálogo de instalación de Tiresias.

Lo muestra ``Tiresias.exe --install`` (el instalador descomprimido) o el
menú Herramientas de una copia portable compilada. Como Tiresias ya está
hablando, la instalación es accesible desde el primer momento.

Para instalar en Archivos de programa hace falta permiso de administrador:
la parte que lo necesita (copiar el programa, accesos directos comunes y
registro de desinstalación) la hace una copia elevada con
``--install-silent``; lo que es del usuario (copiar su configuración e
iniciar al iniciar sesión) se hace después en este proceso.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

import wx

from . import message_dialog
from .. import APP_NAME, VERSION, paths
from ..i18n import _
from ..log import getLogger
from .helpers import bringToFront, isAlive, speakMessage
from .settings import SettingsBuilder, parentWindow, showError

log = getLogger("gui.installer")

_dialog: "InstallDialog | None" = None


class InstallDialog(wx.Dialog):
	def __init__(self) -> None:
		from .. import installer

		super().__init__(parentWindow(), title=_("Instalar {app} {version}").format(app=APP_NAME, version=VERSION), style=wx.DEFAULT_DIALOG_STYLE)
		self.installer = installer
		#: ``True`` mientras se instala: el diálogo no se puede cerrar.
		self._busy = False
		main = wx.BoxSizer(wx.VERTICAL)
		b = SettingsBuilder(self, main)
		info = installer.installedInfo()
		try:
			runCommand = installer.runAtLogonCommand()
		except OSError:
			runCommand = ""
		defaults = installer.installDialogDefaults(
			info,
			hasOwnConfig=not paths.FROZEN or os.path.isfile(os.path.join(paths.configDir(), "config.json")),
			fromInstallerTemp=installer.isInstallerTempCopy(),
			runCommand=runCommand,
		)
		text = _(
			"Se instalará {app} {version} en este equipo. Podrá iniciarlo desde el menú Inicio o con Control+Alt+T, "
			"y desinstalarlo desde Configuración de Windows > Aplicaciones."
		).format(app=APP_NAME, version=VERSION)
		if info.get("DisplayVersion"):
			text += "\n\n" + _("Ya hay una copia instalada (versión {v}): se actualizará conservando su configuración.").format(v=info["DisplayVersion"])
		# Texto en un campo de solo lectura para poder recorrerlo con las flechas (#258).
		self.info = b.addText(_("In&formación:"), text, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(500, 110))
		self.allUsers = b.addCheckBox(_("Instalar para &todos los usuarios (en Archivos de programa; pide permiso de administrador)"), defaults["allUsers"])
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(self, label=_("&Carpeta:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
		self.folder = wx.TextCtrl(self, value=info.get("InstallLocation") or installer.defaultInstallDir(True), size=(360, -1))
		row.Add(self.folder, 1)
		main.Add(row, 0, wx.EXPAND | wx.BOTTOM, 6)
		self.desktop = b.addCheckBox(_("Acceso directo en el &escritorio (Control+Alt+T)"), defaults["desktop"])
		self.startMenu = b.addCheckBox(_("Accesos directos en el &menú Inicio"), defaults["startMenu"])
		self.logon = b.addCheckBox(_("Iniciar Tiresias al iniciar &sesión en Windows"), defaults["logon"])
		self.copyConfig = b.addCheckBox(_("Copiar la configuración de esta c&opia (opciones, perfiles, gestos, complementos)"), defaults["copyConfig"])
		self.launch = b.addCheckBox(_("I&niciar la copia instalada al terminar"), True)
		self.status = wx.StaticText(self, label="")
		main.Add(self.status, 0, wx.BOTTOM, 4)
		buttons = wx.StdDialogButtonSizer()
		self.ok = wx.Button(self, wx.ID_OK, _("&Instalar"))
		cancel = wx.Button(self, wx.ID_CANCEL, _("Cancelar"))
		self.cancel = cancel
		buttons.AddButton(self.ok)
		buttons.AddButton(cancel)
		buttons.Realize()
		main.Add(buttons, 0, wx.ALIGN_RIGHT | wx.TOP, 8)
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(main, 1, wx.EXPAND | wx.ALL, 10)
		self.SetSizerAndFit(outer)
		self.ok.SetDefault()
		self.SetEscapeId(wx.ID_CANCEL)
		self.ok.Bind(wx.EVT_BUTTON, self._onInstall)
		cancel.Bind(wx.EVT_BUTTON, lambda evt: self._close())
		self.Bind(wx.EVT_CLOSE, self._onCloseEvent)
		self.allUsers.Bind(wx.EVT_CHECKBOX, self._onScope)
		self.CentreOnScreen()
		self.info.SetFocus()

	def _onScope(self, evt: Any) -> None:
		self.folder.SetValue(self.installer.defaultInstallDir(self.allUsers.GetValue()))

	def _onCloseEvent(self, evt: Any) -> None:
		if self._busy and evt.CanVeto():
			evt.Veto()
			speakMessage(_("Instalando, espere por favor..."))
			return
		self._close(force=True)

	def _close(self, force: bool = False) -> None:
		global _dialog
		if self._busy and not force:
			# A mitad de la instalación no se cierra (quedaría a medias y sin aviso).
			speakMessage(_("Instalando, espere por favor..."))
			return
		if _dialog is self:
			_dialog = None
		self.Hide()
		self.Destroy()

	def _setBusy(self, busy: bool) -> None:
		self._busy = busy
		for ctrl in (self.ok, self.cancel, self.allUsers, self.folder, self.desktop, self.startMenu, self.logon, self.copyConfig, self.launch):
			ctrl.Enable(not busy)
		if busy:
			# El foco no puede quedarse en un control desactivado.
			self.info.SetFocus()

	def _onInstall(self, evt: Any) -> None:
		inst = self.installer
		if not paths.FROZEN:
			showError(_("Solo se puede instalar la versión compilada de Tiresias (Tiresias.bat, opción «instalador»)."), self)
			return
		target = os.path.expandvars(self.folder.GetValue().strip())
		if not target:
			showError(_("Escriba la carpeta de instalación."), self)
			return
		if not os.path.isabs(target):
			showError(_("Escriba la ruta completa de la carpeta de instalación, con la unidad (por ejemplo, C:\\Program Files\\Tiresias)."), self)
			return
		target = inst.resolveInstallDir(target)
		try:
			notEmpty = os.path.isdir(target) and bool(os.listdir(target)) and not inst.isTiresiasFolder(target)
		except OSError:
			notEmpty = False
		if notEmpty:
			showError(_("La carpeta {folder} no está vacía y no es una copia de {app}. Elija una carpeta vacía o la de una copia de {app}.").format(folder=target, app=APP_NAME), self)
			return
		self._setBusy(True)
		self.status.SetLabel(_("Instalando..."))
		speakMessage(_("Instalando, espere por favor..."))
		allUsers = self.allUsers.GetValue()
		desktop, startMenu, logon = self.desktop.GetValue(), self.startMenu.GetValue(), self.logon.GetValue()
		copyConfig, launch = self.copyConfig.GetValue(), self.launch.GetValue()

		def work() -> str:
			# El inicio automático (None) lo decide este proceso, con la cuenta del usuario.
			opts = inst.InstallOptions(targetDir=target, allUsers=allUsers, desktopShortcut=desktop, startMenu=startMenu, startOnLogon=None, copyConfig=False, launchAfter=False)
			exe = os.path.join(target, inst.EXE_NAME)
			if allUsers and not inst.isElevated():
				# La copia elevada recibe «todos los usuarios» y --no-elevate; no inicia nada.
				exeSelf, base = inst._launch()
				code = inst.shellExecuteElevated(exeSelf, inst.quoteArgs(base + inst.elevatedInstallArgs(opts)), wait=True)
				if code != 0:
					raise OSError(_("la instalación terminó con el código {code}. Los detalles están en el archivo logs\\ordenes.log de la carpeta %APPDATA%\\Tiresias.").format(code=code))
			else:
				exe = inst.install(opts)
			# Lo que pertenece al usuario se hace en este proceso (no en el elevado).
			userDir = paths.userDataDir()
			if copyConfig and not inst.isInside(paths.DATA_DIR, userDir):
				inst.copyUserData(paths.DATA_DIR, userDir, includeAddons=True)
			if logon:
				inst.setRunAtLogon(exe, True)
			else:
				inst.removeRunAtLogonIfFrom(exe)
			return exe

		def done(exe: Any, error: Exception | None) -> None:
			if not isAlive(self):
				return
			self._setBusy(False)
			if error is not None:
				self.status.SetLabel("")
				showError(_("No se pudo instalar {app}: {error}").format(app=APP_NAME, error=error), self)
				return
			self.status.SetLabel(_("Instalación terminada."))
			message_dialog.messageBox(_("{app} se ha instalado correctamente.").format(app=APP_NAME), self.GetTitle(), wx.OK | wx.ICON_INFORMATION, self)
			self._close()
			if launch:
				# La copia instalada sustituye a esta al arrancar.
				try:
					subprocess.Popen([exe], cwd=os.path.dirname(exe), close_fds=True)
				except OSError:
					log.exception("No se pudo iniciar la copia instalada")

		from .system_dialogs import _runInThread

		_runInThread(work, done)


def showInstallDialog() -> None:
	global _dialog
	from ..config import policy as policyModule

	# También con --install: la política del administrador y el modo seguro lo impiden.
	if not policyModule.isAllowed("install"):
		showError(policyModule.blockedMessage(), parentWindow(), _("Instalar {app}").format(app=APP_NAME))
		return
	if _dialog is None or not isAlive(_dialog):
		_dialog = InstallDialog()
		_dialog.Show()
	bringToFront(_dialog)
