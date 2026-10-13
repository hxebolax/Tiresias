"""Órdenes del acceso remoto (complemento global incorporado)."""

from __future__ import annotations

from ..baseobject import script
from ..i18n import _
from ..plugins import GlobalPlugin

CAT_REMOTE = _("Acceso remoto")


def _client():
	from . import getClient

	return getClient()


class RemoteGlobalPlugin(GlobalPlugin):
	#: Marca que usa el cliente para reconocer la orden de alternar control.
	isRemotePlugin = True
	scriptCategory = CAT_REMOTE

	@script(description=_("Conecta o desconecta el acceso remoto (sin conexión, abre el diálogo Conectar)"), category=CAT_REMOTE, gesture="kb:tiresias+alt+r")
	def script_toggleRemoteConnection(self, gesture) -> None:
		client = _client()
		if client is None:
			return
		if client.isActive:
			_confirmDisconnect(client)
		else:
			from ..gui import remote_dialogs

			remote_dialogs.showConnectDialog()

	@script(description=_("Alterna entre controlar el equipo local y el equipo remoto"), category=CAT_REMOTE, gesture="kb:tiresias+alt+tab")
	def script_toggleRemoteControl(self, gesture) -> None:
		client = _client()
		if client is not None:
			client.toggleRemoteKeyControl(gesture)

	@script(description=_("Abre el diálogo para conectar con otro equipo por acceso remoto"), category=CAT_REMOTE)
	def script_remoteConnect(self, gesture) -> None:
		client = _client()
		if client is not None and client.isActive:
			from .. import speech

			speech.speakMessage(_("Ya hay una sesión de acceso remoto. Desconecta antes de iniciar otra."))
			return
		from ..gui import remote_dialogs

		remote_dialogs.showConnectDialog()

	@script(description=_("Desconecta la sesión de acceso remoto"), category=CAT_REMOTE)
	def script_remoteDisconnect(self, gesture) -> None:
		client = _client()
		if client is None or not client.isActive:
			from .. import speech

			speech.speakMessage(_("Sin conexión de acceso remoto"))
			return
		_confirmDisconnect(client)

	@script(description=_("Silencia o devuelve el sonido del equipo remoto"), category=CAT_REMOTE)
	def script_toggleRemoteMute(self, gesture) -> None:
		client = _client()
		if client is not None:
			client.toggleMute()

	@script(description=_("Envía el texto del portapapeles al otro equipo"), category=CAT_REMOTE)
	def script_pushClipboard(self, gesture) -> None:
		client = _client()
		if client is not None:
			client.pushClipboard()

	@script(description=_("Copia al portapapeles el enlace nvdaremote:// para que el otro equipo se conecte"), category=CAT_REMOTE)
	def script_copyRemoteLink(self, gesture) -> None:
		client = _client()
		if client is not None:
			client.copyLink()

	@script(description=_("Envía Control+Alt+Supr al equipo controlado"), category=CAT_REMOTE)
	def script_sendRemoteSAS(self, gesture) -> None:
		client = _client()
		if client is not None:
			client.sendSAS()

	@script(description=_("Anuncia el estado de la conexión de acceso remoto"), category=CAT_REMOTE, speakOnDemand=True)
	def script_reportRemoteStatus(self, gesture) -> None:
		from .. import speech

		client = _client()
		speech.speakMessage(client.statusText() if client is not None else _("Acceso remoto no disponible"))

	@script(description=_("Anuncia el estado de la voz por Escritorio remoto (RDP)"), category=CAT_REMOTE, speakOnDemand=True)
	def script_reportRdpStatus(self, gesture) -> None:
		from .. import speech
		from . import rdp

		speech.speakMessage(rdp.statusText())

	@script(description=_("Abre las opciones del acceso remoto"), category=CAT_REMOTE)
	def script_remoteSettings(self, gesture) -> None:
		from .. import gui

		gui.showSettings("remote")


def _confirmDisconnect(client) -> None:
	from ..config import conf

	try:
		confirm = conf["remote"]["confirmDisconnectAsFollower"]
	except KeyError:
		confirm = True
	if client.isFollower and client.isConnected and confirm:
		from ..gui import remote_dialogs

		remote_dialogs.confirmDisconnect()
	else:
		client.disconnect()
