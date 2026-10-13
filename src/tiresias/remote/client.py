"""Cliente del acceso remoto: une sesiones, transporte, teclado e interfaz.

Hay como mucho una sesión a la vez: controlando otro equipo
(:class:`~.session.LeaderSession`) o controlado por otro
(:class:`~.session.FollowerSession`). Las funciones públicas se llaman en el
hilo del núcleo (las órdenes, y la interfaz mediante ``queueFunction``).

Teclado (equipo que controla): mientras se controla el equipo remoto, el
gancho de teclado entrega cada tecla a :meth:`RemoteClient._onRawKey`, que la
envía al otro equipo y la captura. La única excepción es la orden «alternar
control», que se detecta en el propio hilo de ganchos para que los cambios de
modo sean instantáneos y coherentes con las teclas que siguen pulsadas:

- Al pasar a controlar el equipo remoto, las teclas que el usuario aún tiene
  pulsadas (modificadores, tecla Tiresias y la tecla principal) se sueltan en
  el equipo local (``_localPendingUps``).
- Al volver al equipo local se sueltan en el remoto todas las teclas que
  seguían pulsadas allí, y su liberación física se descarta en el local
  (``_swallowUps``), para no dejar modificadores pegados en ningún equipo.
"""

from __future__ import annotations

import socket
import threading
from typing import Any

from .. import queue_handler, winapi
from ..config import conf
from ..i18n import _
from ..log import getLogger
from . import cues
from .certs import CertificateManager
from .local_machine import VK_NONE, TiresiasMachine, muteOnLocalControl, nvdaWavePath
from .protocol import SERVER_PORT, ConnectionInfo, ConnectionMode, addressToHostPort, hostPortToAddress
from .server import RelayServer
from .session import FollowerSession, LeaderSession, RemoteSession
from .store import AUTOCONNECT_DATA_NAME, KIND_HOST, Preset, RemoteStore
from .transport import RelayTransport

log = getLogger("remote")

#: Teclas cuya pulsación sola puede hacer algo (Alt abre menús, Windows el Inicio).
_ACTION_MODIFIERS = {0x12, 0xA4, 0xA5, 0x5B, 0x5C}
_WINDOWS_VKS = {0x5B, 0x5C}
VK_L = 0x4C


def _say(text: str, interrupt: bool = False) -> None:
	from .. import speech

	if interrupt:
		speech.cancelSpeech()
	speech.speakMessage(text)


def localIPv4Addresses() -> list[str]:
	"""Direcciones IPv4 de este equipo (las privadas primero, sin la de bucle local)."""
	addrs: list[str] = []
	try:
		for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
			ip = info[4][0]
			if not ip.startswith("127.") and ip not in addrs:
				addrs.append(ip)
	except OSError:
		pass

	def priority(ip: str) -> int:
		if ip.startswith("192.168.") or ip.startswith("10."):
			return 0
		if ip.startswith("172."):
			return 1
		if ip.startswith("169.254."):
			return 3
		return 2

	return sorted(addrs, key=priority)


def _confValue(key: str, default: Any) -> Any:
	try:
		return conf["remote"][key]
	except KeyError:
		return default


class RemoteClient:
	def __init__(self, store: RemoteStore, certManager: CertificateManager) -> None:
		self.store = store
		self.certManager = certManager
		self.machine = TiresiasMachine(self)
		self.session: RemoteSession | None = None
		self.server: RelayServer | None = None
		#: Datos de conexión que ve el usuario (para el enlace y el menú).
		self.info: ConnectionInfo | None = None
		#: Puerto del servidor local si este equipo lo aloja.
		self.hostPort: int | None = None
		self.presetName: str | None = None
		self._starting = False
		#: Número del arranque del servidor local en curso: un arranque que
		#: termina después de cancelarse (o de empezar otro) se descarta.
		self._startAttempt = 0
		self._followerFailNotified = False
		self._hooksFor: RemoteSession | None = None
		# Teclado (ver el docstring del módulo).
		self.sendingKeys = False
		self._keyLock = threading.RLock()
		self._remoteDown: set[tuple[int, bool]] = set()
		self._localPendingUps: set[int] = set()
		self._swallowUps: set[int] = set()
		self._hookSwitched: str | None = None
		#: Se controlaba el equipo remoto cuando se bloqueó la sesión de Windows.
		self._wasSendingBeforeLock = False
		self._lockMonitor = None

	# ================================================================ estado
	@property
	def mode(self) -> ConnectionMode | None:
		return self.session.mode if self.session is not None else None

	@property
	def isConnected(self) -> bool:
		return self.session is not None and self.session.transport.connected

	@property
	def isConnecting(self) -> bool:
		return self._starting or (self.session is not None and not self.session.transport.connected)

	@property
	def isActive(self) -> bool:
		"""Hay una sesión (conectada o intentando conectar)."""
		return self._starting or self.session is not None

	@property
	def isLeader(self) -> bool:
		return isinstance(self.session, LeaderSession)

	@property
	def isFollower(self) -> bool:
		return isinstance(self.session, FollowerSession)

	def statusText(self) -> str:
		if self._starting:
			return _("Iniciando el servidor local...")
		s = self.session
		if s is None:
			return _("Sin conexión")
		where = self.info.getAddress() if self.info else "?"
		if self.hostPort is not None:
			where = _("servidor local en el puerto {port}").format(port=self.hostPort)
		if not s.transport.connected:
			return _("Conectando con {where}...").format(where=where)
		role = _("controlando otro equipo") if self.isLeader else _("controlado por otro equipo")
		n = s.otherClientsCount
		others = _("nadie más conectado") if n == 0 else (_("1 equipo más conectado") if n == 1 else _("{n} equipos más conectados").format(n=n))
		text = _("Conectado a {where}, {role}, {others}").format(where=where, role=role, others=others)
		if self.isLeader:
			text += ", " + (_("teclado en el equipo remoto") if self.sendingKeys else _("teclado en el equipo local"))
			if self.machine.isMuted:
				text += ", " + _("remoto silenciado")
		return text

	# ================================================================ conexión
	def connect(self, info: ConnectionInfo, hostPort: int | None = None, presetName: str | None = None) -> bool:
		"""Inicia una sesión. Con ``hostPort`` este equipo aloja el servidor."""
		if self.isActive:
			_say(_("Ya hay una sesión de acceso remoto. Desconecta antes de iniciar otra."))
			return False
		self.presetName = presetName
		self._followerFailNotified = False
		if hostPort is not None:
			self._starting = True
			self._startAttempt += 1
			_say(_("Iniciando el servidor en el puerto {port}").format(port=hostPort))
			threading.Thread(target=self._startServerThread, args=(info, int(hostPort), self._startAttempt), name="Iniciar servidor remoto", daemon=True).start()
			return True
		self._startSession(info, info, None)
		return True

	def connectPreset(self, preset: Preset) -> bool:
		if not preset.key:
			# Sin clave (p. ej., cifrada por otro usuario u otro equipo y no se pudo
			# descifrar) la conexión no puede funcionar: se avisa y no se conecta.
			if self.store.keyUnavailable(preset.name):
				msg = _("El preajuste {name} no tiene clave: no se pudo descifrar (se guardó con otro usuario de Windows o en otro equipo). Edítalo y escribe la clave otra vez.")
			else:
				msg = _("El preajuste {name} no tiene clave. Edítalo y escribe la clave.")
			log.warning("El preajuste %s no tiene clave: no se conecta", preset.name)
			_say(msg.format(name=preset.name))
			return False
		mode = ConnectionMode(preset.mode)
		if preset.kind == KIND_HOST:
			info = ConnectionInfo(hostname="localhost", mode=mode, key=preset.key, port=preset.port)
			return self.connect(info, hostPort=preset.port, presetName=preset.name)
		try:
			host, port = addressToHostPort(preset.host, preset.port or SERVER_PORT)
		except ValueError:
			if preset.name == AUTOCONNECT_DATA_NAME:
				_say(_("La conexión automática del acceso remoto tiene un servidor no válido"))
			else:
				_say(_("El preajuste {name} tiene un servidor no válido").format(name=preset.name))
			return False
		info = ConnectionInfo(hostname=host, mode=mode, key=preset.key, port=port)
		return self.connect(info, presetName=preset.name)

	def _startServerThread(self, info: ConnectionInfo, port: int, attempt: int = 0) -> None:
		try:
			server = RelayServer(port, info.key, self.certManager)
			server.start()
		except Exception as e:
			log.warning("No se pudo iniciar el servidor de acceso remoto en el puerto %d: %s", port, e)
			queue_handler.queueFunction(self._serverFailed, port, str(e), attempt)
			return
		# La resolución de nombres puede tardar: se hace aquí, no en el hilo del núcleo.
		ips = localIPv4Addresses()
		queue_handler.queueFunction(self._serverStarted, info, server, attempt, ips)

	def _isCurrentStart(self, attempt: int) -> bool:
		return self._starting and attempt == self._startAttempt

	def _serverFailed(self, port: int, error: str, attempt: int = 0) -> None:
		if not self._isCurrentStart(attempt):
			# Arranque cancelado o sustituido por otro: no se anuncia.
			return
		self._starting = False
		_say(_("No se pudo abrir el puerto {port}: {error}").format(port=port, error=error))

	def _serverStarted(self, info: ConnectionInfo, server: RelayServer, attempt: int = 0, ips: list[str] | None = None) -> None:
		if not self._isCurrentStart(attempt):
			# Se canceló mientras arrancaba, o ya hay otro arranque en curso.
			threading.Thread(target=server.close, daemon=True).start()
			return
		self._starting = False
		self.hostPort = server.port
		if ips is None:
			ips = localIPv4Addresses()
		public = ConnectionInfo(hostname=ips[0] if ips else socket.gethostname(), mode=info.mode, key=info.key, port=server.port)
		local = ConnectionInfo(hostname="127.0.0.1", mode=info.mode, key=info.key, port=server.port, insecure=True, trustedFingerprint=server.fingerprint)
		self._startSession(local, public, server)

	def _startSession(self, info: ConnectionInfo, public: ConnectionInfo, server: RelayServer | None) -> None:
		transport = RelayTransport(
			info.hostname,
			info.port,
			channel=info.key,
			connectionType=info.mode.value,
			insecure=info.insecure,
			trustedFingerprint=info.trustedFingerprint,
			isTrusted=self.store.isTrusted,
			timeout=float(_confValue("connectTimeout", 10)),
			reconnect=True,
			reconnectDelay=float(_confValue("reconnectDelay", 5)),
			name="controlador" if info.mode is ConnectionMode.LEADER else "controlado",
		)
		cls = LeaderSession if info.mode is ConnectionMode.LEADER else FollowerSession
		holder: dict[str, RemoteSession] = {}
		session: RemoteSession = cls(transport, self.machine, dispatch=self._makeDispatch(holder))
		holder["session"] = session
		session._connectInfo = info  # type: ignore[attr-defined]
		session._intentionalClose = False  # type: ignore[attr-defined]
		transport.onConnected = lambda: queue_handler.queueFunction(self._onConnected, session)
		transport.onDisconnected = lambda: queue_handler.queueFunction(self._onDisconnected, session)
		transport.onConnectionFailed = lambda e: queue_handler.queueFunction(self._onConnectionFailed, session, e)
		transport.onCertificateFailed = lambda fp: queue_handler.queueFunction(self._onCertificateFailed, session, fp)
		self.session = session
		self.server = server
		self.info = public
		if server is None:
			self.hostPort = None
		self.machine.isMuted = isinstance(session, LeaderSession) and muteOnLocalControl()
		self._registerHooks(session)
		log.info("Acceso remoto: conectando con %s como %s", info.getAddress(), info.mode.value)
		transport.start()
		if server is None:
			_say(_("Conectando con {address}").format(address=public.getAddress()))

	def _makeDispatch(self, holder: dict):
		def dispatch(func, *args: Any) -> None:
			queue_handler.queueFunction(self._dispatchIfCurrent, holder, func, *args)

		return dispatch

	def _dispatchIfCurrent(self, holder: dict, func, *args: Any) -> None:
		# Los mensajes de una sesión ya cerrada se descartan.
		if self.session is not None and holder.get("session") is self.session:
			func(*args)

	def disconnect(self, silent: bool = False) -> None:
		"""Cierra la sesión y el servidor local (hilo del núcleo)."""
		if self._starting:
			self._starting = False
			self._startAttempt += 1
		session, server = self.session, self.server
		if session is None and server is None:
			return
		if self.sendingKeys:
			self._switchToLocal(announce=False)
		if session is not None:
			session._intentionalClose = True  # type: ignore[attr-defined]
			self._unregisterHooks()
			session.close()
		self.session = None
		self.server = None
		self.hostPort = None
		self.info = None
		self.presetName = None
		self.machine.isMuted = False
		try:
			self.machine.setReceivingBraille(False)
			from .. import braille

			braille.handler.setRemoteNumCells(0, owner="remote")
		except Exception:
			log.debug("Error restaurando el braille", exc_info=True)
		if server is not None:
			threading.Thread(target=server.close, name="Cerrar servidor remoto", daemon=True).start()
		log.info("Acceso remoto desconectado")
		if not silent:
			cues.disconnected()

	def performAutoconnect(self) -> None:
		if self.isActive:
			return
		if self.store.autoconnectCustom:
			data = self.store.autoconnectData
			if data is None:
				return
			if not data.key:
				log.warning("La conexión automática no tiene clave: no se conecta")
				if self.store.autoconnectKeyUnavailable():
					msg = _("Conexión automática del acceso remoto: no se pudo descifrar la clave (se guardó con otro usuario de Windows o en otro equipo). Escríbela otra vez en las opciones del acceso remoto.")
				else:
					msg = _("Conexión automática del acceso remoto: falta la clave. Escríbela en las opciones del acceso remoto.")
				_say(msg)
				return
			log.info("Conexión automática con los datos de las opciones")
			self.connectPreset(data)
			return
		name = self.store.autoconnect
		if not name:
			return
		preset = self.store.getPreset(name)
		if preset is None:
			log.warning("El preajuste de conexión automática %r no existe", name)
			return
		log.info("Conexión automática con el preajuste %s", name)
		self.connectPreset(preset)

	def terminate(self) -> None:
		self.disconnect(silent=True)

	# ================================================================ sucesos del transporte
	def _onConnected(self, session: RemoteSession) -> None:
		if session is not self.session:
			return
		self._followerFailNotified = False
		if self.info is not None and self.hostPort is None:
			self.store.addRecent(hostPortToAddress((self.info.hostname, self.info.port)))
		if isinstance(session, LeaderSession):
			self._updateBrailleInfo(session)
			cues.connected()
			if self.hostPort is not None:
				_say(_("Servidor iniciado en el puerto {port}. Esperando al equipo que se va a controlar.").format(port=self.hostPort))
			else:
				_say(_("Conectado"))
		else:
			cues.connectedAsFollower()
			if self.hostPort is not None:
				_say(_("Servidor iniciado en el puerto {port}").format(port=self.hostPort))

	def _onDisconnected(self, session: RemoteSession) -> None:
		if session is not self.session or getattr(session, "_intentionalClose", False):
			return
		session.resetClients()
		if self.sendingKeys:
			self._switchToLocal(announce=False)
		self.machine.setReceivingBraille(False)
		if session.transport.reconnect:
			cues.clientLeft()
			_say(_("Se ha perdido la conexión de acceso remoto. Reintentando..."))
		else:
			self.disconnect()

	def _onConnectionFailed(self, session: RemoteSession, error: BaseException) -> None:
		if session is not self.session:
			return
		if session.transport.successfulConnects > 0:
			return
		if isinstance(session, LeaderSession):
			info = self.info
			self.disconnect(silent=True)
			msg = _("No se pudo conectar con el equipo remoto ({address}): {error}").format(address=info.getAddress() if info else "?", error=error)
			_say(msg)
			from .. import gui

			gui.messageBox(msg, _("Error de conexión"), _wxIconWarning())
		elif not self._followerFailNotified:
			self._followerFailNotified = True
			_say(_("No se pudo conectar con el servidor de acceso remoto. Se seguirá intentando."))

	def _onCertificateFailed(self, session: RemoteSession, fingerprint: str | None) -> None:
		if session is not self.session:
			return
		transport = session.transport
		info: ConnectionInfo = getattr(session, "_connectInfo")
		presetName = self.presetName
		address = transport.addressKey
		self.disconnect(silent=True)
		if not fingerprint:
			_say(_("No se pudo comprobar el certificado del servidor {address}").format(address=address))
			return
		_say(_("El certificado del servidor no es de confianza. Revisa la huella."))

		def answered(choice: str) -> None:
			if choice not in ("always", "once"):
				queue_handler.queueFunction(_say, _("Conexión cancelada"))
				return
			if choice == "always":
				self.store.trust(address, fingerprint)
			newInfo = ConnectionInfo(hostname=info.hostname, mode=info.mode, key=info.key, port=info.port, insecure=True, trustedFingerprint=fingerprint)
			queue_handler.queueFunction(self.connect, newInfo, None, presetName)

		from ..gui import remote_dialogs

		remote_dialogs.showCertificateDialog(address, fingerprint, answered)

	# ================================================================ sucesos de la sesión
	def _onClientJoined(self, session: RemoteSession, client: dict) -> None:
		if session is not self.session:
			return
		cues.clientJoined()
		ctype = client.get("connection_type")
		if isinstance(session, LeaderSession) and ctype == ConnectionMode.FOLLOWER.value:
			_say(_("Equipo controlado conectado. Usa la orden de alternar control para manejarlo."))
		elif isinstance(session, FollowerSession) and ctype == ConnectionMode.LEADER.value:
			_say(_("Un equipo remoto controla ahora este equipo"))
		else:
			_say(_("Otro equipo se ha unido a la sesión"))

	def _onClientLeft(self, session: RemoteSession, client: dict) -> None:
		if session is not self.session:
			return
		cues.clientLeft()
		ctype = client.get("connection_type")
		if isinstance(session, LeaderSession) and ctype == ConnectionMode.FOLLOWER.value:
			if not session.hasFollowers and self.sendingKeys:
				self._switchToLocal(announce=False)
				_say(_("El equipo controlado se ha desconectado. Controlando el equipo local"))
			else:
				_say(_("El equipo controlado se ha desconectado"))
		elif isinstance(session, FollowerSession) and ctype == ConnectionMode.LEADER.value:
			_say(_("El equipo que controlaba se ha desconectado"))
		else:
			_say(_("Un equipo ha salido de la sesión"))

	def _onMotd(self, session: RemoteSession, motd: str, force: bool) -> None:
		address = session.transport.addressKey
		if not force and not self.store.shouldShowMotd(address, session.motdDigest(motd)):
			return
		from .. import gui

		gui.messageBox(motd, _("Mensaje del servidor de acceso remoto"))

	def _onServerError(self, session: RemoteSession, error: str) -> None:
		if session is not self.session:
			return
		if error == "incorrect_password":
			_say(_("La clave no es correcta para este servidor. Se cancela la conexión."))
			self.disconnect(silent=True)
		else:
			_say(_("Error del servidor de acceso remoto: {error}").format(error=error or "?"))

	# ================================================================ órdenes
	def _requireConnected(self) -> bool:
		if not self.isConnected:
			_say(_("Sin conexión de acceso remoto"))
			return False
		return True

	def _requireLeader(self) -> bool:
		if not self._requireConnected():
			return False
		if not self.isLeader:
			_say(_("Este equipo no es el que controla"))
			return False
		return True

	def toggleMute(self) -> None:
		if not self._requireLeader():
			return
		self.machine.isMuted = not self.machine.isMuted
		if self.machine.isMuted:
			from .. import speech

			speech.cancelSpeech()
		_say(_("Equipo remoto silenciado") if self.machine.isMuted else _("Equipo remoto con sonido"))

	def pushClipboard(self) -> None:
		if not self._requireConnected():
			return
		session = self.session
		assert session is not None
		if session.otherClientsCount < 1:
			_say(_("No hay nadie más conectado"))
			return
		try:
			text = winapi.getClipboardText()
		except Exception:
			text = None
		if not text:
			_say(_("El portapapeles no contiene texto"))
			return
		if session.pushClipboard(text):
			cues.clipboardPushed()
		else:
			_say(_("No se pudo enviar el portapapeles"))

	def copyLink(self) -> None:
		if self.session is None or self.info is None:
			_say(_("Sin conexión de acceso remoto"))
			return
		url = self.info.getURLToConnect()
		from .. import clipboard

		clipboard.ignoreNextChange()
		if winapi.setClipboardText(url):
			_say(_("Enlace copiado"))
		else:
			_say(_("No se pudo copiar el enlace"))

	def sendSAS(self) -> None:
		if not self._requireLeader():
			return
		assert isinstance(self.session, LeaderSession)
		self.session.sendSAS()
		_say(_("Control+Alt+Supr enviado"))

	# ================================================================ alternar control
	def toggleRemoteKeyControl(self, gesture: Any = None) -> None:
		"""Orden «alternar control». Si el gancho ya cambió de modo, solo lo anuncia."""
		with self._keyLock:
			switched, self._hookSwitched = self._hookSwitched, None
		if switched == "remote":
			self._afterSwitchToRemote()
			return
		if switched == "local":
			self._afterSwitchToLocal()
			return
		if self.sendingKeys:
			self._switchToLocal()
			return
		if not self._requireLeader():
			return
		assert isinstance(self.session, LeaderSession)
		if not self.session.hasFollowers:
			_say(_("No hay ningún equipo controlado conectado"))
			return
		from ..input import core as inputCore

		with self._keyLock:
			self._beginRemote(inputCore.manager, None)
		self._afterSwitchToRemote()

	def _beginRemote(self, manager: Any, mainVk: int | None) -> None:
		"""Pasa el teclado al equipo remoto (con ``_keyLock``)."""
		pending = set(getattr(manager, "_modVks", set()))
		if getattr(manager, "_tiresiasDown", False) and getattr(manager, "_tiresiasVk", None):
			pending.add(manager._tiresiasVk[0])
		if mainVk is not None:
			pending.add(mainVk)
		self._localPendingUps = pending
		self._remoteDown = set()
		self._swallowUps = set()
		self.sendingKeys = True

	def _endRemote(self, mainVk: int | None) -> None:
		"""Devuelve el teclado al equipo local (con ``_keyLock``)."""
		session = self.session
		held = list(self._remoteDown)
		if isinstance(session, LeaderSession) and held:
			if any(vk in _ACTION_MODIFIERS for vk, _e in held):
				# Evita que soltar Alt o Windows abra menús en el equipo remoto.
				session.sendKey(VK_NONE, False, True)
				session.sendKey(VK_NONE, False, False)
			for vk, ext in held:
				session.sendKey(vk, ext, False)
		self._swallowUps = {vk for vk, _e in held}
		if mainVk is not None:
			self._swallowUps.add(mainVk)
		self._remoteDown = set()
		self._localPendingUps = set()
		self.sendingKeys = False

	def _switchToLocal(self, announce: bool = True) -> None:
		with self._keyLock:
			if self.sendingKeys:
				self._endRemote(None)
			self._hookSwitched = None
		if announce:
			self._afterSwitchToLocal()
		else:
			self.machine.setReceivingBraille(False)

	def _afterSwitchToRemote(self) -> None:
		session = self.session
		if isinstance(session, LeaderSession):
			self._updateBrailleInfo(session)
			session.sendBrailleInfo()
		if self.machine.isMuted:
			self.machine.isMuted = False
		self.machine.setReceivingBraille(True)
		_say(_("Controlando el equipo remoto"), interrupt=True)

	def _lockLocalWorkstation(self) -> None:
		self.machine.setReceivingBraille(False)
		try:
			winapi.user32.LockWorkStation()
		except Exception:
			log.debug("No se pudo bloquear el equipo", exc_info=True)

	def onSessionLockChanged(self, locked: bool) -> None:
		"""La sesión de Windows se bloquea o desbloquea (hilo del núcleo)."""
		if locked:
			if self.sendingKeys:
				self._switchToLocal(announce=False)
				self._wasSendingBeforeLock = True
				log.info("Sesión bloqueada: el teclado vuelve al equipo local")
			return
		if not self._wasSendingBeforeLock:
			return
		self._wasSendingBeforeLock = False
		session = self.session
		if self.sendingKeys or not isinstance(session, LeaderSession) or not session.transport.connected or not session.hasFollowers:
			return
		from ..input import core as inputCore

		with self._keyLock:
			self._beginRemote(inputCore.manager, None)
		log.info("Sesión desbloqueada: se vuelve a controlar el equipo remoto")
		self._afterSwitchToRemote()

	def _afterSwitchToLocal(self) -> None:
		self.machine.setReceivingBraille(False)
		if muteOnLocalControl() and not self.machine.isMuted:
			self.machine.isMuted = True
		_say(_("Controlando el equipo local"), interrupt=True)

	@staticmethod
	def _updateBrailleInfo(session: LeaderSession) -> None:
		try:
			from .. import braille

			display = braille.handler.display
			session.setBrailleInfo(display.name, display.numCells)
		except Exception:
			log.debug("No se pudo leer la línea braille", exc_info=True)

	@staticmethod
	def _isToggleScript(func: Any) -> bool:
		return getattr(func, "__name__", "") == "script_toggleRemoteControl" and getattr(getattr(func, "__self__", None), "isRemotePlugin", False)

	# ================================================================ ganchos (hilo de ganchos)
	def _onDecideGesture(self, gesture: Any) -> bool:
		"""Antes de ejecutar un gesto local: detecta «alternar control» al instante."""
		if self.sendingKeys or not isinstance(self.session, LeaderSession):
			return True
		from ..input import core as inputCore

		manager = inputCore.manager
		if manager.inputHelp or not self.session.hasFollowers or not self.session.transport.connected:
			return True
		try:
			func = manager.findScript(gesture)
		except Exception:
			return True
		if self._isToggleScript(func):
			with self._keyLock:
				self._beginRemote(manager, getattr(gesture, "vk", None))
				self._hookSwitched = "remote"
		return True

	def _onRawKey(self, vk: int, scanCode: int, extended: bool, pressed: bool, injected: bool) -> bool:
		"""``False`` captura la tecla (enviada al equipo remoto o descartada)."""
		with self._keyLock:
			if not self.sendingKeys:
				if vk in self._swallowUps:
					if not pressed:
						self._swallowUps.discard(vk)
					return False
				return True
			if injected:
				return True
			if vk in self._localPendingUps:
				# Tecla que ya estaba pulsada al cambiar: se suelta en el equipo local.
				if not pressed:
					self._localPendingUps.discard(vk)
				return True
			session = self.session
			if not isinstance(session, LeaderSession):
				return True
			key = (vk, bool(extended))
			if pressed and vk == VK_L and any(v in _WINDOWS_VKS for v, _e in self._remoteDown):
				# Windows+L bloquea siempre el equipo local: el teclado vuelve a él
				# (soltando Windows en el remoto) y se bloquea este equipo.
				self._endRemote(vk)
				self._wasSendingBeforeLock = True
				queue_handler.queueFunction(self._lockLocalWorkstation)
				return False
			if pressed and self._isToggleGesture(vk, scanCode, extended):
				self._endRemote(vk)
				self._hookSwitched = "local"
				queue_handler.queueFunction(self.toggleRemoteKeyControl)
				return False
			if pressed:
				self._remoteDown.add(key)
			else:
				self._remoteDown.discard(key)
			session.sendKey(vk, bool(extended), pressed, scanCode)
			return False

	def _isToggleGesture(self, vk: int, scanCode: int, extended: bool) -> bool:
		from ..input import core as inputCore
		from ..input import keys
		from ..input.gestures import KeyboardGesture

		manager = inputCore.manager
		if vk in keys.MODIFIER_VKS:
			return False
		try:
			if manager._isTiresiasKey(vk, extended):
				return False
			mods: set[str] = set()
			for v, e in self._remoteDown:
				name = keys.MODIFIER_VKS.get(v)
				if name:
					mods.add(name)
				elif manager._isTiresiasKey(v, e):
					mods.add("tiresias")
			fg = winapi.getForegroundWindow()
			hkl = winapi.user32.GetKeyboardLayout(winapi.getWindowThreadId(fg) if fg else 0)
			gesture = KeyboardGesture(vk, scanCode, extended, frozenset(mods), keys.vkName(vk, extended, hkl), conf["keyboard"]["layout"])
			return self._isToggleScript(manager.findScript(gesture))
		except Exception:
			log.debug("Error comprobando el gesto de alternar", exc_info=True)
			return False

	def _onBrailleGesture(self, gesture: Any) -> bool:
		"""Gestos de la línea braille local mientras se controla el equipo remoto."""
		if not self.sendingKeys or not isinstance(self.session, LeaderSession):
			return True
		from .. import braille
		from ..input import core as inputCore

		try:
			func = inputCore.manager.findScript(gesture)
		except Exception:
			func = None
		if self._isToggleScript(func):
			return True
		payload: dict[str, Any] = {
			"source": braille.handler.display.name,
			"id": getattr(gesture, "normalizedKeys", "") or "+".join(getattr(gesture, "keys", []) or []),
			"dots": int(getattr(gesture, "dots", 0) or 0),
			"space": bool(getattr(gesture, "space", False)),
		}
		idx = getattr(gesture, "routingIndex", None)
		if isinstance(idx, int):
			payload["routingIndex"] = idx
			payload["cellIndexes"] = [idx]
		name = getattr(func, "__name__", "")
		if name.startswith("script_"):
			payload["scriptPath"] = ["globalCommands", "GlobalCommands", name[7:]]
		self.session.sendBrailleInput(**payload)
		return False

	# ================================================================ salida local -> remoto (controlado)
	def _follower(self) -> FollowerSession | None:
		s = self.session
		return s if isinstance(s, FollowerSession) and s.hasLeaders else None

	def _onSpeechQueued(self, speechSequence: list | None = None, priority: int = 0, **kw: Any) -> None:
		"""``pre_speechQueued``: la voz se envía con su prioridad real, como NVDA."""
		self._onPreSpeech(speechSequence or [], priority)

	def _onPreSpeech(self, sequence: list, priority: int = 0) -> None:
		s = self._follower()
		if s is not None and sequence:
			s.sendSpeech(sequence, priority)

	def _onSpeechCanceled(self) -> None:
		s = self._follower()
		if s is not None:
			s.sendCancel()

	def _onSpeechPaused(self, switch: bool) -> None:
		s = self._follower()
		if s is not None:
			s.sendPause(switch)

	def _onBeep(self, hz: float, length: int, left: int = 50, right: int = 50) -> None:
		s = self._follower()
		if s is not None:
			s.sendTone(hz, length, left, right)

	def _onPlaySound(self, name: str = "", fileName: str = "") -> None:
		s = self._follower()
		if s is None:
			return
		if name.startswith("remote"):
			# Avisos propios del acceso remoto: no se reenvían.
			return
		s.sendWave(fileName or (nvdaWavePath(name) if name else ""), name)

	def _onDisplayUpdate(self, cells: list) -> None:
		s = self._follower()
		if s is not None:
			s.sendDisplay(cells)

	# ================================================================ registro de ganchos
	def _registerHooks(self, session: RemoteSession) -> None:
		self._unregisterHooks()
		from .. import braille
		from ..audio import tones
		from ..input import core as inputCore
		from ..speech import api as speechApi

		if isinstance(session, FollowerSession):
			speechApi.pre_speechQueued.register(self._onSpeechQueued)
			speechApi.pre_speechCanceled.register(self._onSpeechCanceled)
			speechApi.post_speechPaused.register(self._onSpeechPaused)
			tones.pre_beep.register(self._onBeep)
			tones.pre_playSound.register(self._onPlaySound)
			braille.post_displayUpdate.register(self._onDisplayUpdate)
		else:
			inputCore.decide_handleRawKey.register(self._onRawKey)
			inputCore.decide_executeGesture.register(self._onDecideGesture)
			inputCore.decide_executeBrailleGesture.register(self._onBrailleGesture)
			self._startLockMonitor()
		self._hooksFor = session

	def _startLockMonitor(self) -> None:
		if self._lockMonitor is not None:
			return
		try:
			from .session_lock import SessionLockMonitor

			monitor = SessionLockMonitor(lambda locked: queue_handler.queueFunction(self.onSessionLockChanged, locked))
			monitor.start()
			self._lockMonitor = monitor
		except Exception:
			log.exception("No se pudo vigilar el bloqueo de la sesión")

	def _stopLockMonitor(self) -> None:
		monitor, self._lockMonitor = self._lockMonitor, None
		self._wasSendingBeforeLock = False
		if monitor is not None:
			try:
				monitor.stop()
			except Exception:
				log.debug("Error deteniendo el aviso de sesión", exc_info=True)

	def _unregisterHooks(self) -> None:
		if self._hooksFor is None:
			return
		from .. import braille
		from ..audio import tones
		from ..input import core as inputCore
		from ..speech import api as speechApi

		speechApi.pre_speechQueued.unregister(self._onSpeechQueued)
		speechApi.pre_speechCanceled.unregister(self._onSpeechCanceled)
		speechApi.post_speechPaused.unregister(self._onSpeechPaused)
		tones.pre_beep.unregister(self._onBeep)
		tones.pre_playSound.unregister(self._onPlaySound)
		braille.post_displayUpdate.unregister(self._onDisplayUpdate)
		inputCore.decide_handleRawKey.unregister(self._onRawKey)
		inputCore.decide_executeGesture.unregister(self._onDecideGesture)
		inputCore.decide_executeBrailleGesture.unregister(self._onBrailleGesture)
		self._hooksFor = None
		self._stopLockMonitor()
		with self._keyLock:
			self._swallowUps = set()


def _wxIconWarning() -> int:
	import wx

	return wx.OK | wx.ICON_WARNING
