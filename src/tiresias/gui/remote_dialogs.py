"""Interfaz del acceso remoto: diálogo Conectar, certificados, submenú y opciones.

Todo se ejecuta en el hilo de la interfaz. Las acciones sobre la conexión se
encolan en el hilo del núcleo (:func:`_onCore`).
"""

from __future__ import annotations

import os
from typing import Callable

import wx

from . import message_dialog
from .. import queue_handler
from ..i18n import _
from ..log import getLogger
from .helpers import bringToFront, isAlive, runOnGui, speakMessage

log = getLogger("gui.remote")


def _client():
	from .. import remote

	return remote.getClient()


def _onCore(func: Callable, *args) -> None:
	queue_handler.queueFunction(func, *args)


MODE_LABELS = [_("Controlar otro equipo"), _("Permitir que controlen este equipo")]
KIND_LABELS = [_("Usar un servidor de retransmisión u otro equipo"), _("Alojar el servidor en este equipo (conexión directa)")]


# ====================================================================== Conectar
class ConnectDialog(wx.Dialog):
	"""Diálogo «Conectar con otro equipo» con preajustes guardados."""

	def __init__(self) -> None:
		super().__init__(None, title=_("Acceso remoto: conectar con otro equipo"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		client = _client()
		self.store = client.store if client is not None else None
		sizer = wx.BoxSizer(wx.VERTICAL)

		# Preajustes
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(self, label=_("&Preajuste:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
		self.presetChoice = wx.Choice(self, choices=[])
		row.Add(self.presetChoice, 1, wx.ALIGN_CENTER_VERTICAL)
		sizer.Add(row, 0, wx.EXPAND | wx.ALL, 6)
		row = wx.BoxSizer(wx.HORIZONTAL)
		self.savePresetBtn = wx.Button(self, label=_("&Guardar como preajuste..."))
		self.deletePresetBtn = wx.Button(self, label=_("&Eliminar preajuste"))
		row.Add(self.savePresetBtn, 0, wx.RIGHT, 6)
		row.Add(self.deletePresetBtn, 0)
		sizer.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

		self.modeBox = wx.RadioBox(self, label=_("&Modo"), choices=MODE_LABELS, majorDimension=1, style=wx.RA_SPECIFY_COLS)
		sizer.Add(self.modeBox, 0, wx.EXPAND | wx.ALL, 6)
		self.kindBox = wx.RadioBox(self, label=_("&Tipo de conexión"), choices=KIND_LABELS, majorDimension=1, style=wx.RA_SPECIFY_COLS)
		sizer.Add(self.kindBox, 0, wx.EXPAND | wx.ALL, 6)

		self.hostLabel = wx.StaticText(self, label=_("&Servidor (dirección, dirección:puerto o enlace nvdaremote://):"))
		sizer.Add(self.hostLabel, 0, wx.LEFT | wx.RIGHT | wx.TOP, 6)
		recent = self.store.recentHosts() if self.store is not None else []
		self.hostCombo = wx.ComboBox(self, choices=recent, style=wx.CB_DROPDOWN)
		sizer.Add(self.hostCombo, 0, wx.EXPAND | wx.ALL, 6)

		row = wx.BoxSizer(wx.HORIZONTAL)
		self.portLabel = wx.StaticText(self, label=_("P&uerto del servidor local:"))
		row.Add(self.portLabel, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
		from ..remote.protocol import SERVER_PORT

		self.portSpin = wx.SpinCtrl(self, min=1, max=65535, initial=SERVER_PORT, style=wx.SP_ARROW_KEYS)
		row.Add(self.portSpin, 0, wx.ALIGN_CENTER_VERTICAL)
		sizer.Add(row, 0, wx.ALL, 6)

		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(self, label=_("&Clave:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
		self.keyText = wx.TextCtrl(self, size=(220, -1))
		row.Add(self.keyText, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
		self.generateBtn = wx.Button(self, label=_("Ge&nerar clave"))
		row.Add(self.generateBtn, 0, wx.ALIGN_CENTER_VERTICAL)
		sizer.Add(row, 0, wx.EXPAND | wx.ALL, 6)

		self.autoCheck = wx.CheckBox(self, label=_("Conectar automáticamente con estos datos al &iniciar Tiresias"))
		self.autoCheck.SetValue(bool(self.store is not None and self.store.autoconnectCustom))
		sizer.Add(self.autoCheck, 0, wx.ALL, 6)

		buttons = wx.BoxSizer(wx.HORIZONTAL)
		ok = wx.Button(self, wx.ID_OK, _("C&onectar"))
		ok.SetDefault()
		cancel = wx.Button(self, wx.ID_CANCEL, _("Cancelar"))
		buttons.Add(ok, 0, wx.ALL, 4)
		buttons.Add(cancel, 0, wx.ALL, 4)
		sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)

		self.presetChoice.Bind(wx.EVT_CHOICE, self.onPreset)
		self.savePresetBtn.Bind(wx.EVT_BUTTON, self.onSavePreset)
		self.deletePresetBtn.Bind(wx.EVT_BUTTON, self.onDeletePreset)
		self.kindBox.Bind(wx.EVT_RADIOBOX, lambda evt: self._updateKind())
		self.generateBtn.Bind(wx.EVT_BUTTON, self.onGenerate)
		self.hostCombo.Bind(wx.EVT_KILL_FOCUS, self.onHostLeave)
		self.Bind(wx.EVT_BUTTON, self.onOk, id=wx.ID_OK)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.Close(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, self.onClose)

		self._fillPresets()
		if recent:
			self.hostCombo.SetValue(recent[0])
		if self.store is not None and self.store.autoconnectCustom:
			# Se parte de los datos de la conexión automática.
			self._showPreset(self.store.autoconnectData)
		self._updateKind()
		self.CentreOnScreen()

	# --------------------------------------------------------------- preajustes
	def _fillPresets(self, select: str | None = None) -> None:
		names = [p.name for p in self.store.getPresets()] if self.store is not None else []
		self.presetChoice.SetItems([_("(ninguno)")] + names)
		idx = names.index(select) + 1 if select in names else 0
		self.presetChoice.SetSelection(idx)
		self.deletePresetBtn.Enable(idx > 0)

	def _selectedPresetName(self) -> str | None:
		i = self.presetChoice.GetSelection()
		return self.presetChoice.GetString(i) if i > 0 else None

	def onPreset(self, evt: wx.CommandEvent) -> None:
		name = self._selectedPresetName()
		self.deletePresetBtn.Enable(name is not None)
		if name is None or self.store is None:
			return
		self._showPreset(self.store.getPreset(name))

	def _showPreset(self, p) -> None:
		if p is None:
			return
		from ..remote.protocol import ConnectionMode
		from ..remote.store import KIND_HOST

		self.modeBox.SetSelection(0 if p.mode == ConnectionMode.LEADER.value else 1)
		self.kindBox.SetSelection(1 if p.kind == KIND_HOST else 0)
		self.hostCombo.SetValue(p.host)
		self.portSpin.SetValue(p.port)
		self.keyText.SetValue(p.key)
		self._updateKind()

	def _currentPreset(self, name: str):
		from ..remote.protocol import ConnectionMode
		from ..remote.store import KIND_HOST, KIND_RELAY, Preset

		mode = ConnectionMode.LEADER if self.modeBox.GetSelection() == 0 else ConnectionMode.FOLLOWER
		kind = KIND_HOST if self.kindBox.GetSelection() == 1 else KIND_RELAY
		return Preset(name=name, mode=mode.value, kind=kind, host=self.hostCombo.GetValue().strip(), port=int(self.portSpin.GetValue()), key=self.keyText.GetValue().strip())

	def onSavePreset(self, evt: wx.CommandEvent) -> None:
		if self.store is None:
			return
		self._applyLink()
		current = self._selectedPresetName() or ""
		dlg = wx.TextEntryDialog(self, _("Nombre del preajuste:"), _("Guardar preajuste de conexión"), current)
		try:
			if dlg.ShowModal() != wx.ID_OK:
				return
			name = dlg.GetValue().strip()
		finally:
			dlg.Destroy()
		if not name:
			return
		if self.store.getPreset(name) is not None and name.lower() != current.lower():
			if message_dialog.messageBox(_("Ya existe un preajuste llamado «{name}». ¿Quieres sustituirlo?").format(name=name), _("Guardar preajuste de conexión"), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self) != wx.YES:
				return
		self.store.savePreset(self._currentPreset(name))
		self._fillPresets(select=name)
		speakMessage(_("Preajuste guardado"))

	def onDeletePreset(self, evt: wx.CommandEvent) -> None:
		name = self._selectedPresetName()
		if name is None or self.store is None:
			return
		if message_dialog.messageBox(_("¿Eliminar el preajuste «{name}»?").format(name=name), _("Eliminar preajuste"), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self) != wx.YES:
			return
		self.store.deletePreset(name)
		self._fillPresets()
		self.presetChoice.SetFocus()

	# --------------------------------------------------------------- campos
	def _updateKind(self) -> None:
		host = self.kindBox.GetSelection() == 1
		self.hostCombo.Enable(not host)
		self.hostLabel.Enable(not host)
		self.portSpin.Enable(host)
		self.portLabel.Enable(host)

	def onGenerate(self, evt: wx.CommandEvent) -> None:
		from ..remote.protocol import generateKey

		key = generateKey()
		self.keyText.SetValue(key)
		self.keyText.SetFocus()
		speakMessage(_("Clave generada: {key}").format(key=" ".join(key)))

	def onHostLeave(self, evt: wx.FocusEvent) -> None:
		evt.Skip()
		wx.CallAfter(self._applyLink, True)

	def _applyLink(self, announce: bool = False) -> bool:
		"""Si el servidor es un enlace nvdaremote://, rellena el resto de campos."""
		if not isAlive(self):
			return False
		from ..remote.protocol import URL_PREFIX, ConnectionInfo, ConnectionMode, URLParsingError, hostPortToAddress

		text = self.hostCombo.GetValue().strip()
		if not text.lower().startswith(URL_PREFIX):
			return False
		try:
			info = ConnectionInfo.fromURL(text)
		except URLParsingError as e:
			if announce:
				speakMessage(_("Enlace no válido: {error}").format(error=e))
			return False
		self.kindBox.SetSelection(0)
		self.modeBox.SetSelection(0 if info.mode is ConnectionMode.LEADER else 1)
		self.hostCombo.SetValue(hostPortToAddress((info.hostname, info.port)))
		self.keyText.SetValue(info.key)
		self._updateKind()
		if announce:
			speakMessage(_("Datos del enlace aplicados: {mode}").format(mode=MODE_LABELS[self.modeBox.GetSelection()]))
		return True

	def onOk(self, evt: wx.CommandEvent) -> None:
		from ..remote.protocol import ConnectionInfo, ConnectionMode, addressToHostPort

		self._applyLink()
		client = _client()
		if client is None:
			self.Close()
			return
		key = self.keyText.GetValue().strip()
		if not key:
			message_dialog.messageBox(_("Escribe la clave de la sesión (la misma en los dos equipos) o pulsa «Generar clave»."), _("Falta la clave"), wx.OK | wx.ICON_WARNING, self)
			self.keyText.SetFocus()
			return
		mode = ConnectionMode.LEADER if self.modeBox.GetSelection() == 0 else ConnectionMode.FOLLOWER
		presetName = self._selectedPresetName()
		if self.kindBox.GetSelection() == 0:
			try:
				addressToHostPort(self.hostCombo.GetValue().strip())
			except ValueError:
				message_dialog.messageBox(_("Escribe la dirección del servidor o del otro equipo, por ejemplo nvdaremote.com o 192.168.1.20:6837."), _("Servidor no válido"), wx.OK | wx.ICON_WARNING, self)
				self.hostCombo.SetFocus()
				return
		self._saveAutoconnect()
		if self.kindBox.GetSelection() == 1:
			port = int(self.portSpin.GetValue())
			info = ConnectionInfo(hostname="localhost", mode=mode, key=key, port=port)
			self.Destroy()
			_onCore(client.connect, info, port, presetName)
			return
		host, port = addressToHostPort(self.hostCombo.GetValue().strip())
		info = ConnectionInfo(hostname=host, mode=mode, key=key, port=port)
		self.Destroy()
		_onCore(client.connect, info, None, presetName)

	def _saveAutoconnect(self) -> None:
		"""Guarda o quita los datos de la conexión automática según la casilla."""
		if self.store is None:
			return
		from ..remote.store import AUTOCONNECT_DATA_NAME

		if self.autoCheck.GetValue():
			data = self._currentPreset(AUTOCONNECT_DATA_NAME)
			if not self.store.autoconnectCustom or data != self.store.autoconnectData:
				self.store.setAutoconnect(data=data, custom=True)
		elif self.store.autoconnectCustom:
			self.store.setAutoconnect()

	def onClose(self, evt: wx.Event) -> None:
		self.Destroy()


_connectDialog: ConnectDialog | None = None


def showConnectDialog() -> None:
	"""Abre el diálogo Conectar (seguro desde cualquier hilo)."""

	def _show() -> None:
		global _connectDialog
		client = _client()
		if client is not None and client.isActive:
			message_dialog.messageBox(
				_("Ya hay una sesión de acceso remoto. Desconecta antes de iniciar otra."),
				_("Acceso remoto"),
				wx.OK | wx.ICON_WARNING,
			)
			return
		if not isAlive(_connectDialog):
			_connectDialog = ConnectDialog()
		_connectDialog.Show()
		bringToFront(_connectDialog)
		if _connectDialog.presetChoice.GetCount() > 1:
			_connectDialog.presetChoice.SetFocus()
		else:
			_connectDialog.modeBox.SetFocus()

	runOnGui(_show)


# ====================================================================== certificados
class CertificateDialog(wx.Dialog):
	def __init__(self, address: str, fingerprint: str, callback: Callable[[str], None]) -> None:
		super().__init__(None, title=_("Certificado no verificado"))
		from ..remote.transport import formatFingerprint

		self._callback = callback
		self._answered = False
		sizer = wx.BoxSizer(wx.VERTICAL)
		message = _(
			"No se puede verificar la identidad del servidor {address}.\n"
			"Es normal si el otro equipo aloja su propio servidor (conexión directa). "
			"Comprueba con la otra persona que la huella SHA-256 de su certificado es esta:\n\n"
			"{fingerprint}\n\n"
			"Si no coincide, no te conectes: alguien podría estar interceptando la conexión."
		).format(address=address, fingerprint=formatFingerprint(fingerprint))
		sizer.Add(wx.StaticText(self, label=_("&Información del certificado:")), 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
		self.text = wx.TextCtrl(self, value=message, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(520, 200))
		sizer.Add(self.text, 1, wx.EXPAND | wx.ALL, 8)
		buttons = wx.BoxSizer(wx.HORIZONTAL)
		always = wx.Button(self, wx.ID_YES, _("Confiar &siempre"))
		once = wx.Button(self, wx.ID_NO, _("Solo &esta vez"))
		cancel = wx.Button(self, wx.ID_CANCEL, _("&Cancelar"))
		cancel.SetDefault()
		for b in (always, once, cancel):
			buttons.Add(b, 0, wx.ALL, 4)
		sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		always.Bind(wx.EVT_BUTTON, lambda evt: self._answer("always"))
		once.Bind(wx.EVT_BUTTON, lambda evt: self._answer("once"))
		cancel.Bind(wx.EVT_BUTTON, lambda evt: self._answer("cancel"))
		self.Bind(wx.EVT_CLOSE, lambda evt: self._answer("cancel"))
		self.CentreOnScreen()

	def _answer(self, choice: str) -> None:
		if self._answered:
			return
		self._answered = True
		callback = self._callback
		self.Destroy()
		try:
			callback(choice)
		except Exception:
			log.exception("Error tras el diálogo de certificado")


def showCertificateDialog(address: str, fingerprint: str, callback: Callable[[str], None]) -> None:
	"""Pregunta si confiar en un certificado. ``callback("always"|"once"|"cancel")``
	se llama en el hilo de la interfaz."""

	def _show() -> None:
		dlg = CertificateDialog(address, fingerprint, callback)
		dlg.Show()
		bringToFront(dlg)
		dlg.text.SetFocus()

	runOnGui(_show)


# ====================================================================== desconectar
def confirmDisconnect() -> None:
	"""Pide confirmación antes de desconectar (equipo controlado)."""

	def _ask() -> None:
		from . import mainFrame

		parent = mainFrame if isAlive(mainFrame) else None
		if parent is not None:
			parent.prePopup()
		try:
			answer = message_dialog.messageBox(
				_("¿Seguro que quieres cerrar la sesión de acceso remoto? El otro equipo dejará de controlar este."),
				_("Confirmar desconexión"),
				wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
				parent,
			)
		finally:
			if parent is not None:
				parent.postPopup()
		if answer == wx.YES:
			client = _client()
			if client is not None:
				_onCore(client.disconnect)

	runOnGui(_ask)


# ====================================================================== submenú
def buildMenu(frame) -> wx.Menu:
	"""Submenú «Acceso remoto» del menú de Tiresias (hilo de la interfaz)."""
	add = frame.addMenuItem
	menu = wx.Menu()
	client = _client()
	active = client is not None and client.isActive
	connected = client is not None and client.isConnected
	leader = connected and client.isLeader
	if not active:
		add(menu, _("&Conectar..."), showConnectDialog)
	else:
		item = add(menu, _("&Desconectar"), _menuDisconnect)
		item.Enable(True)
	item = add(menu, _("&Alternar control entre equipo local y remoto"), lambda: _onCore(client.toggleRemoteKeyControl) if client else None)
	item.Enable(bool(leader))
	item = add(menu, _("&Silenciar el equipo remoto"), lambda: _onCore(client.toggleMute) if client else None, wx.ITEM_CHECK, bool(client and client.machine.isMuted))
	item.Enable(bool(leader))
	item = add(menu, _("Enviar el &portapapeles"), lambda: _onCore(client.pushClipboard) if client else None)
	item.Enable(bool(connected))
	item = add(menu, _("Copiar el &enlace de conexión"), lambda: _onCore(client.copyLink) if client else None)
	item.Enable(bool(active))
	item = add(menu, _("Enviar Control+Alt+&Supr"), lambda: _onCore(client.sendSAS) if client else None)
	item.Enable(bool(leader))
	add(menu, _("&Estado de la conexión"), lambda: _onCore(_speakStatus))
	menu.AppendSeparator()
	add(menu, _("&Opciones de acceso remoto..."), lambda: _showRemoteSettings())
	return menu


def _menuDisconnect() -> None:
	from ..remote import plugin

	client = _client()
	if client is not None:
		_onCore(plugin._confirmDisconnect, client)


def _speakStatus() -> None:
	from .. import speech

	client = _client()
	speech.speakMessage(client.statusText() if client is not None else _("Acceso remoto no disponible"))


def _showRemoteSettings() -> None:
	from . import settings

	settings.showSettings("remote")


# ====================================================================== opciones
def registerSettingsPanel() -> None:
	from . import settings

	class RemotePanel(settings.ConfigPanel):
		title = _("Acceso remoto")
		section = "remote"
		fields = [
			settings.Bool("playSounds", _("Reproducir sonidos al conectar, desconectar y recibir el portapapeles")),
			settings.Bool("muteOnLocalControl", _("Silenciar el equipo remoto mientras se controla el equipo local")),
			settings.Bool("confirmDisconnectAsFollower", _("Pedir confirmación antes de desconectar cuando este equipo está controlado")),
			settings.Int("connectTimeout", _("Tiempo de espera de la conexión (segundos):"), 3, 120),
			settings.Int("reconnectDelay", _("Reintentar la conexión cada (segundos):"), 2, 120),
		]

		def makeExtraSettings(self, builder) -> None:
			from ..remote.protocol import SERVER_PORT, ConnectionMode
			from ..remote.store import KIND_HOST

			client = _client()
			self._store = client.store if client is not None else None
			store = self._store
			names = [p.name for p in store.getPresets()] if store is not None else []
			# Valores de la lista: "" no conectar, None los datos de abajo, o el nombre de un preajuste.
			self._autoValues: list[str | None] = ["", None] + names
			labels = [_("No"), _("Sí, con los datos de conexión siguientes")] + [_("Sí, con el preajuste «{name}»").format(name=n) for n in names]
			if store is not None and store.autoconnectCustom:
				sel = 1
			else:
				current = store.autoconnect if store is not None else ""
				sel = self._autoValues.index(current) if current in self._autoValues else 0
			group = builder.group(_("Conexión automática"))
			self._autoChoice = group.addChoice(_("Conectar &automáticamente al iniciar Tiresias:"), labels, sel)
			data = store.autoconnectData if store is not None else None
			recent = store.recentHosts() if store is not None else []
			self._autoMode = group.addChoice(_("&Modo:"), MODE_LABELS, 0 if data is not None and data.mode == ConnectionMode.LEADER.value else 1)
			self._autoKind = group.addChoice(_("&Tipo de conexión:"), KIND_LABELS, 1 if data is not None and data.kind == KIND_HOST else 0)
			host = data.host if data is not None and data.host else (recent[0] if recent else "")
			self._autoHost = group.addLabeledControl(
				_("&Servidor (dirección, dirección:puerto o enlace nvdaremote://):"),
				lambda p: wx.ComboBox(p, value=host, choices=recent, style=wx.CB_DROPDOWN, size=(300, -1)),
			)
			self._autoPort = group.addSpin(_("P&uerto del servidor local:"), 1, 65535, data.port if data is not None else SERVER_PORT)
			self._autoKey = group.addText(_("C&lave:"), data.key if data is not None else "")
			self._autoGenerate = group.addButton(_("&Generar clave"))
			self._autoGenerate.Bind(wx.EVT_BUTTON, self._onGenerate)
			self._autoChoice.Bind(wx.EVT_CHOICE, lambda evt: self._updateAuto())
			self._autoKind.Bind(wx.EVT_CHOICE, lambda evt: self._updateAuto())
			self._autoHost.Bind(wx.EVT_KILL_FOCUS, self._onHostLeave)
			self._updateAuto()
			if not names:
				builder.addStaticText(_("Para crear preajustes, usa el botón «Guardar como preajuste» del diálogo Conectar."))
			fp = _localFingerprint()
			builder.addText(
				_("Huella del certificado de este equipo (para la conexión directa):"),
				fp or _("se creará la primera vez que alojes el servidor"),
				style=wx.TE_READONLY,
				size=(420, -1),
			)
			n = len(self._store.trustedCertificates()) if self._store is not None else 0
			self._forgetBtn = builder.addButton(_("&Olvidar los certificados de confianza ({n})").format(n=n))
			self._forgetBtn.Enable(n > 0)
			self._forgetBtn.Bind(wx.EVT_BUTTON, self._onForget)
			btn = builder.addButton(_("Abrir el diálogo Co&nectar..."))
			btn.Bind(wx.EVT_BUTTON, lambda evt: showConnectDialog())

		def _autoValue(self) -> str | None:
			i = self._autoChoice.GetSelection()
			return self._autoValues[i] if 0 <= i < len(self._autoValues) else ""

		def _updateAuto(self) -> None:
			custom = self._autoValue() is None
			host = self._autoKind.GetSelection() == 1
			for ctrl in (self._autoMode, self._autoKind, self._autoKey, self._autoGenerate):
				_enableLabeled(ctrl, custom)
			_enableLabeled(self._autoHost, custom and not host)
			_enableLabeled(self._autoPort, custom and host)

		def _onGenerate(self, evt: wx.CommandEvent) -> None:
			from ..remote.protocol import generateKey

			key = generateKey()
			self._autoKey.SetValue(key)
			self._autoKey.SetFocus()
			speakMessage(_("Clave generada: {key}").format(key=" ".join(key)))

		def _onHostLeave(self, evt: wx.FocusEvent) -> None:
			evt.Skip()
			wx.CallAfter(self._applyLink, True)

		def _applyLink(self, announce: bool = False) -> bool:
			"""Si el servidor es un enlace nvdaremote://, rellena el resto de campos."""
			if not isAlive(self):
				return False
			from ..remote.protocol import URL_PREFIX, ConnectionInfo, ConnectionMode, URLParsingError, hostPortToAddress

			text = self._autoHost.GetValue().strip()
			if not text.lower().startswith(URL_PREFIX):
				return False
			try:
				info = ConnectionInfo.fromURL(text)
			except URLParsingError as e:
				if announce:
					speakMessage(_("Enlace no válido: {error}").format(error=e))
				return False
			self._autoKind.SetSelection(0)
			self._autoMode.SetSelection(0 if info.mode is ConnectionMode.LEADER else 1)
			self._autoHost.SetValue(hostPortToAddress((info.hostname, info.port)))
			self._autoKey.SetValue(info.key)
			self._updateAuto()
			if announce:
				speakMessage(_("Datos del enlace aplicados: {mode}").format(mode=MODE_LABELS[self._autoMode.GetSelection()]))
			return True

		def _autoPreset(self):
			from ..remote.protocol import ConnectionMode
			from ..remote.store import AUTOCONNECT_DATA_NAME, KIND_HOST, KIND_RELAY, Preset

			mode = ConnectionMode.LEADER if self._autoMode.GetSelection() == 0 else ConnectionMode.FOLLOWER
			kind = KIND_HOST if self._autoKind.GetSelection() == 1 else KIND_RELAY
			return Preset(
				name=AUTOCONNECT_DATA_NAME,
				mode=mode.value,
				kind=kind,
				host=self._autoHost.GetValue().strip(),
				port=int(self._autoPort.GetValue()),
				key=self._autoKey.GetValue().strip(),
			)

		def isValid(self) -> bool:
			if not super().isValid():
				return False
			if self._store is None or self._autoValue() is not None:
				return True
			from ..remote.protocol import addressToHostPort

			self._applyLink()
			if not self._autoKey.GetValue().strip():
				message_dialog.messageBox(
					_("Para conectar automáticamente escribe la clave de la sesión (la misma en los dos equipos) o pulsa «Generar clave»."),
					_("Falta la clave"),
					wx.OK | wx.ICON_WARNING,
					self,
				)
				self._autoKey.SetFocus()
				return False
			if self._autoKind.GetSelection() == 0:
				try:
					addressToHostPort(self._autoHost.GetValue().strip())
				except ValueError:
					message_dialog.messageBox(
						_("Escribe la dirección del servidor o del otro equipo, por ejemplo nvdaremote.com o 192.168.1.20:6837."),
						_("Servidor no válido"),
						wx.OK | wx.ICON_WARNING,
						self,
					)
					self._autoHost.SetFocus()
					return False
			return True

		def resetExtraToFactory(self) -> None:
			self._autoChoice.SetSelection(0)
			self._updateAuto()

		def _onForget(self, evt: wx.CommandEvent) -> None:
			if self._store is None:
				return
			if message_dialog.messageBox(
				_("¿Olvidar todas las huellas de certificados de confianza? La próxima conexión a esos servidores volverá a pedir confirmación."),
				_("Olvidar certificados"),
				wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
				self,
			) != wx.YES:
				return
			self._store.clearTrusted()
			self._forgetBtn.SetLabel(_("&Olvidar los certificados de confianza ({n})").format(n=0))
			self._forgetBtn.Enable(False)
			speakMessage(_("Certificados olvidados"))

		def onSave(self) -> None:
			super().onSave()
			if self._store is not None:
				value = self._autoValue()
				custom = value is None
				data = self._autoPreset()
				# Los datos escritos se guardan aunque no se usen, para no perderlos.
				keep = custom or bool(data.host or data.key)
				old = self._store.autoconnectData
				changed = (
					custom != self._store.autoconnectCustom
					or (not custom and value != self._store.autoconnect)
					or (keep and data != old)
				)
				if changed:
					self._store.setAutoconnect(name=value or "", data=data if keep else None, custom=custom)

	# Su sitio en la lista lo da ``settings.getPanelIds``.
	settings.registerPanel("remote", RemotePanel.title, RemotePanel)


def _enableLabeled(ctrl: wx.Window, enable: bool) -> None:
	"""Activa o desactiva un control y la etiqueta que lo precede."""
	ctrl.Enable(enable)
	prev = ctrl.GetPrevSibling()
	if isinstance(prev, wx.StaticText):
		prev.Enable(enable)


def _localFingerprint() -> str:
	from ..remote import remoteDir
	from ..remote.transport import formatFingerprint

	try:
		with open(os.path.join(remoteDir(), "servidor.huella"), encoding="ascii") as f:
			fp = f.read().strip()
		return formatFingerprint(fp) if fp else ""
	except OSError:
		return ""
