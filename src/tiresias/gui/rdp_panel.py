"""Categoría «Escritorio remoto» del cuadro de Opciones (voz por RDP, NVDA #3564)."""

from __future__ import annotations

from typing import Any

import wx

from . import message_dialog
from .. import queue_handler
from ..i18n import _
from . import settings as S
from .helpers import runOnGui, speakMessage


class RdpPanel(S.ConfigPanel):
	title = _("Escritorio remoto")
	section = "rdp"
	fields = [
		S.Bool("receiveFromRemote", _("&Recibir la voz de los equipos remotos")),
		S.Bool("citrixClient", _("Cargar el complemento también en Citrix &Workspace")),
		S.Bool("sendToClient", _("&Enviar la voz al equipo cliente cuando Tiresias se ejecuta dentro de una sesión remota")),
		S.Bool("muteLocalSpeech", _("&Silenciar la voz local mientras el equipo cliente la recibe")),
	]

	def makeHeaderSettings(self, builder: S.SettingsBuilder) -> None:
		builder.addStaticText(
			_(
				"En el equipo desde el que te conectas, marca «Recibir la voz de los equipos remotos» "
				"(y, si usas Citrix, «Cargar el complemento también en Citrix Workspace»). "
				"En el equipo remoto, Tiresias debe ejecutarse dentro de la sesión con «Enviar la voz al equipo cliente» marcada."
			)
		)

	def makeExtraSettings(self, builder: S.SettingsBuilder) -> None:
		from ..remote import rdp

		builder.addText(_("Estado:"), rdp.statusText(), style=wx.TE_READONLY | wx.TE_MULTILINE, size=(420, 60))
		builder.addText(_("Complemento del cliente de Escritorio remoto:"), _registrationText(), style=wx.TE_READONLY | wx.TE_MULTILINE, size=(420, 60))
		builder.addText(_("Complemento en Citrix Workspace:"), rdp.citrixStatusText(), style=wx.TE_READONLY | wx.TE_MULTILINE, size=(420, 60))
		self._allowEntry = rdp.citrixAllowListEntry()
		builder.addText(
			_("Entrada para la directiva de Citrix «Virtual channel allow list for DVC» (para el administrador):"),
			self._allowEntry,
			style=wx.TE_READONLY,
			size=(420, -1),
		)
		copyButton = builder.addButton(_("C&opiar la entrada para el administrador de Citrix"))
		copyButton.Bind(wx.EVT_BUTTON, self._onCopyAllowEntry)
		# La opción de Citrix solo tiene sentido si se recibe la voz.
		receive = self.getControl("receiveFromRemote")
		if receive is not None:
			receive.Bind(wx.EVT_CHECKBOX, self._onReceiveToggled)
			self._onReceiveToggled()

	def _onReceiveToggled(self, evt: wx.CommandEvent | None = None) -> None:
		from ..config import conf

		citrix = self.getControl("citrixClient")
		if citrix is not None and not conf.isLocked("rdp", "citrixClient"):
			citrix.Enable(bool(self.getValue("receiveFromRemote")))
		if evt is not None:
			evt.Skip()

	def _onCopyAllowEntry(self, evt: wx.CommandEvent) -> None:
		from .. import api

		# Copiar y anunciarlo es trabajo del núcleo (la voz no se usa desde la interfaz).
		queue_handler.queueFunction(api.copyToClip, self._allowEntry, True)

	def afterSave(self, changes: dict[tuple[str, str], tuple[Any, Any]]) -> None:
		receiveChanged = ("rdp", "receiveFromRemote") in changes
		newValue = changes.get(("rdp", "receiveFromRemote"), (None, None))[1]
		citrixChanged = ("rdp", "citrixClient") in changes

		def apply() -> None:
			from ..remote import rdp

			result = rdp.applyConfig()
			if receiveChanged:
				runOnGui(_announceRegistration, result, bool(newValue))
			citrix = rdp.citrixResult()
			if (citrixChanged or receiveChanged) and citrix and not (citrix == "missing" and result in ("missing", "error")):
				# Si falta el complemento de Escritorio remoto, ya lo explica el aviso anterior.
				runOnGui(_announceCitrix, citrix)

		queue_handler.queueFunction(apply)


def _registrationText() -> str:
	from ..remote.rdp_registration import RdpRegistration

	try:
		reg = RdpRegistration()
		paths = reg.registeredPaths()
		if not reg.addinRegistered() or not paths:
			return _("No registrado: el cliente de Escritorio remoto de este equipo no cargará Tiresias.")
		bits = {"x64": _("64 bits"), "x86": _("32 bits")}
		return _("Registrado para el usuario actual ({arches}): {path}").format(arches=", ".join(bits[a] for a in sorted(paths)), path=next(iter(paths.values())))
	except OSError as e:
		return _("No se pudo consultar el registro: {error}").format(error=e)


def _announceRegistration(result: str, enabled: bool) -> None:
	if result == "registered":
		message_dialog.messageBox(
			_(
				"Se ha registrado el complemento de Tiresias para el cliente de Escritorio remoto. "
				"Si tienes abierta alguna Conexión a Escritorio remoto, ciérrala y vuelve a abrirla para que lo cargue."
			),
			_("Escritorio remoto"),
			wx.OK | wx.ICON_INFORMATION,
		)
	elif result == "missing":
		message_dialog.messageBox(
			_("No se encuentra el complemento tiresiasRdpClient.dll en la carpeta «rdp» del programa. Vuelve a instalar Tiresias."),
			_("Escritorio remoto"),
			wx.OK | wx.ICON_ERROR,
		)
	elif result == "error":
		message_dialog.messageBox(
			_("No se pudo cambiar el registro del complemento de Escritorio remoto. Consulta el registro de Tiresias."),
			_("Escritorio remoto"),
			wx.OK | wx.ICON_ERROR,
		)
	elif result == "unregistered" and not enabled:
		speakMessage(_("Complemento de Escritorio remoto quitado"))


def _announceCitrix(result: str) -> None:
	if result == "registered":
		message_dialog.messageBox(
			_(
				"Se ha registrado el complemento de Tiresias en Citrix Workspace. Si tienes abierta alguna sesión de Citrix, "
				"ciérrala y vuelve a abrirla. El administrador de Citrix debe permitir el canal de Tiresias en el servidor "
				"(directiva «Virtual channel allow list for DVC»): lo explica el manual."
			),
			_("Citrix Workspace"),
			wx.OK | wx.ICON_INFORMATION,
		)
	elif result == "pending":
		message_dialog.messageBox(
			_(
				"Citrix Workspace todavía no ha creado tu configuración de usuario. Abre una vez cualquier sesión de Citrix: "
				"Tiresias se registrará solo y te avisará. Después, cierra esa sesión y vuelve a abrirla."
			),
			_("Citrix Workspace"),
			wx.OK | wx.ICON_INFORMATION,
		)
	elif result == "notInstalled":
		message_dialog.messageBox(
			_(
				"No se encuentra Citrix Workspace app en este equipo. Instálala desde la página de Citrix "
				"(la versión de Microsoft Store no admite complementos) y vuelve a marcar la opción."
			),
			_("Citrix Workspace"),
			wx.OK | wx.ICON_WARNING,
		)
	elif result == "missing":
		message_dialog.messageBox(
			_(
				"No se ha registrado el complemento en Citrix Workspace porque falta el complemento de Escritorio remoto, "
				"que Citrix Workspace necesita. Marca «Recibir la voz de los equipos remotos» y comprueba que Tiresias lo "
				"registra; después vuelve a marcar esta opción."
			),
			_("Citrix Workspace"),
			wx.OK | wx.ICON_WARNING,
		)
	elif result == "error":
		message_dialog.messageBox(
			_("No se pudo cambiar la configuración de Citrix Workspace. Consulta el registro de Tiresias."),
			_("Citrix Workspace"),
			wx.OK | wx.ICON_ERROR,
		)
	elif result == "unregistered":
		speakMessage(_("Complemento quitado de Citrix Workspace"))


def register() -> None:
	"""Añade la categoría (va después de «Acceso remoto»; ver ``settings.PANEL_ORDER``)."""
	S.registerPanel("rdp", RdpPanel.title, RdpPanel)
