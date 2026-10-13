"""Sesiones del acceso remoto: qué hace cada equipo con cada mensaje.

- :class:`LeaderSession` (este equipo controla otro): envía teclas, braille
  y portapapeles; recibe voz, cancelaciones, pitidos, sonidos y braille.
- :class:`FollowerSession` (este equipo es controlado): recibe teclas,
  braille, portapapeles y Control+Alt+Supr; envía voz, cancelaciones,
  pitidos, sonidos y braille a los equipos que lo controlan.

Las sesiones no dependen de Tiresias: hablan con un objeto
:class:`LocalMachine` (en Tiresias, :class:`tiresias.remote.local_machine.TiresiasMachine`;
en las pruebas, un registrador). Los mensajes llegan en hilos de red; la
sesión los entrega a ``dispatch`` (en Tiresias, la cola del hilo del núcleo),
salvo las teclas, que se inyectan en seguida para no depender del núcleo.
"""

from __future__ import annotations

import hashlib
import inspect
from typing import Any, Callable

from ..log import getLogger
from .protocol import ConnectionMode, MessageType
from .transport import RelayTransport

log = getLogger("remote")

Dispatch = Callable[..., None]


def callWithSupportedKwargs(func: Callable, **kwargs: Any) -> Any:
	"""Llama a ``func`` solo con los argumentos que acepta (los mensajes
	pueden traer campos nuevos o desconocidos)."""
	try:
		params = inspect.signature(func).parameters
	except (TypeError, ValueError):
		return func(**kwargs)
	if any(p.kind == p.VAR_KEYWORD for p in params.values()):
		return func(**kwargs)
	return func(**{k: v for k, v in kwargs.items() if k in params})


def _directDispatch(func: Callable, *args: Any, **kwargs: Any) -> None:
	func(*args, **kwargs)


class LocalMachine:
	"""Lo que una sesión necesita del equipo local (implementación vacía)."""

	isMuted = False

	# --- salida recibida (controlando otro equipo)
	def speak(self, sequence: list, priority: int = 0) -> None: ...
	def cancelSpeech(self) -> None: ...
	def pauseSpeech(self, switch: bool) -> None: ...
	def beep(self, hz: float, length: int, left: int = 50, right: int = 50) -> None: ...
	def playWave(self, fileName: str = "", name: str = "") -> None: ...
	def display(self, cells: list[int]) -> None: ...

	# --- entrada recibida (controlado por otro equipo)
	def sendKey(self, vk: int, extended: bool, pressed: bool, scan: int | None = None) -> None: ...
	def brailleInput(self, **kwargs: Any) -> None: ...
	def sendSAS(self) -> None: ...
	def setBrailleDisplaySize(self, size: int) -> None: ...

	# --- común
	def setClipboardText(self, text: str) -> None: ...
	def onClientJoined(self, session: "RemoteSession", client: dict) -> None: ...
	def onClientLeft(self, session: "RemoteSession", client: dict) -> None: ...
	def onMotd(self, session: "RemoteSession", motd: str, forceDisplay: bool) -> None: ...
	def onServerError(self, session: "RemoteSession", error: str) -> None: ...
	def onVersionMismatch(self, session: "RemoteSession") -> None: ...
	def onRemoteNotConnected(self, session: "RemoteSession") -> None: ...


class RemoteSession:
	mode: ConnectionMode
	#: Mensajes que se atienden en el hilo de red, sin pasar por ``dispatch``.
	immediate: frozenset[str] = frozenset()

	def __init__(self, transport: RelayTransport, local: LocalMachine, dispatch: Dispatch | None = None) -> None:
		self.transport = transport
		self.local = local
		self.dispatch: Dispatch = dispatch or _directDispatch
		#: Clientes del canal: id -> {"id", "connection_type", ...}.
		self.clients: dict[Any, dict] = {}
		self.channelJoined = False
		self._handlers: dict[str, Callable[..., None]] = {}
		self.register(MessageType.CHANNEL_JOINED, self.handleChannelJoined)
		self.register(MessageType.CLIENT_JOINED, self.handleClientJoined)
		self.register(MessageType.CLIENT_LEFT, self.handleClientLeft)
		self.register(MessageType.SET_CLIPBOARD_TEXT, self.handleClipboard)
		self.register(MessageType.MOTD, self.handleMotd)
		self.register(MessageType.VERSION_MISMATCH, self.handleVersionMismatch)
		self.register(MessageType.ERROR, self.handleError)
		transport.onMessage = self._onMessage

	def register(self, type: MessageType, handler: Callable[..., None]) -> None:
		self._handlers[type.value] = handler

	# ------------------------------------------------------------------ recepción
	def _onMessage(self, obj: dict) -> None:
		msgType = obj.pop("type", None)
		handler = self._handlers.get(msgType) if isinstance(msgType, str) else None
		if handler is None:
			log.debug("Mensaje remoto sin manejador: %s", msgType)
			return
		if msgType in self.immediate:
			self._call(handler, obj)
		else:
			self.dispatch(self._call, handler, obj)

	@staticmethod
	def _call(handler: Callable[..., None], obj: dict) -> None:
		try:
			callWithSupportedKwargs(handler, **obj)
		except Exception:
			log.exception("Error atendiendo un mensaje remoto con %r", handler)

	# ------------------------------------------------------------------ canal
	def handleChannelJoined(self, channel: str = "", clients: list | None = None, origin: Any = None, **kw: Any) -> None:
		self.channelJoined = True
		for client in clients or []:
			if isinstance(client, dict):
				self.handleClientJoined(client=client)

	def handleClientJoined(self, client: dict | None = None, user_id: Any = None, **kw: Any) -> None:
		if not isinstance(client, dict):
			client = {"id": user_id, "connection_type": None}
		self.clients[client.get("id")] = dict(client)
		self.local.onClientJoined(self, client)
		self._clientsChanged()

	def handleClientLeft(self, client: dict | None = None, user_id: Any = None, **kw: Any) -> None:
		if not isinstance(client, dict):
			client = self.clients.get(user_id) or {"id": user_id, "connection_type": None}
		self.clients.pop(client.get("id"), None)
		self.local.onClientLeft(self, client)
		self._clientsChanged()

	def _clientsChanged(self) -> None:
		pass

	def resetClients(self) -> None:
		"""Se pierde la conexión: el canal se vacía."""
		self.clients.clear()
		self.channelJoined = False
		self._clientsChanged()

	def clientsOfType(self, mode: ConnectionMode) -> list[dict]:
		return [c for c in self.clients.values() if c.get("connection_type") == mode.value]

	@property
	def leaders(self) -> list[dict]:
		return self.clientsOfType(ConnectionMode.LEADER)

	@property
	def followers(self) -> list[dict]:
		return self.clientsOfType(ConnectionMode.FOLLOWER)

	@property
	def otherClientsCount(self) -> int:
		return len(self.clients)

	# ------------------------------------------------------------------ sistema
	def handleClipboard(self, text: str = "", **kw: Any) -> None:
		if isinstance(text, str):
			self.local.setClipboardText(text)

	def handleMotd(self, motd: str = "", force_display: bool = False, **kw: Any) -> None:
		if motd:
			self.local.onMotd(self, str(motd), bool(force_display))

	def motdDigest(self, motd: str) -> str:
		return hashlib.sha1(motd.encode("utf-8", errors="surrogatepass")).hexdigest()

	def handleVersionMismatch(self, **kw: Any) -> None:
		self.transport.stopReconnecting()
		self.local.onVersionMismatch(self)
		self.transport.close()

	def handleError(self, error: str = "", message: str = "", **kw: Any) -> None:
		err = str(error or message or "")
		if err == "incorrect_password":
			self.transport.stopReconnecting()
		self.local.onServerError(self, err)

	# ------------------------------------------------------------------ envío
	def send(self, type: MessageType, **payload: Any) -> bool:
		return self.transport.send(type, **payload)

	def pushClipboard(self, text: str) -> bool:
		return self.send(MessageType.SET_CLIPBOARD_TEXT, text=text)

	def close(self) -> None:
		self.transport.close()


class FollowerSession(RemoteSession):
	"""Este equipo es controlado."""

	mode = ConnectionMode.FOLLOWER
	immediate = frozenset({MessageType.KEY.value})

	def __init__(self, transport: RelayTransport, local: LocalMachine, dispatch: Dispatch | None = None) -> None:
		super().__init__(transport, local, dispatch)
		self.leaderDisplaySizes: dict[Any, int] = {}
		self.register(MessageType.KEY, self.handleKey)
		self.register(MessageType.SET_BRAILLE_INFO, self.handleBrailleInfo)
		self.register(MessageType.SET_DISPLAY_SIZE, self.handleDisplaySize)
		self.register(MessageType.BRAILLE_INPUT, self.handleBrailleInput)
		self.register(MessageType.SEND_SAS, self.handleSAS)

	# --- entrada
	def handleKey(self, vk_code: int | None = None, extended: bool = False, pressed: bool = True, scan_code: int | None = None, **kw: Any) -> None:
		if not isinstance(vk_code, int):
			return
		self.local.sendKey(vk_code, bool(extended), bool(pressed), scan_code if isinstance(scan_code, int) else None)

	def handleBrailleInput(self, **kwargs: Any) -> None:
		self.local.brailleInput(**kwargs)

	def handleSAS(self, **kw: Any) -> None:
		self.local.sendSAS()

	# --- braille
	def handleBrailleInfo(self, name: str | None = None, numCells: int = 0, origin: Any = None, **kw: Any) -> None:
		if origin is not None and origin not in self.clients:
			# Información de un cliente desconocido (protocolo 1 o mensaje adelantado).
			self.clients[origin] = {"id": origin, "connection_type": ConnectionMode.LEADER.value}
		key = origin if origin is not None else "?"
		try:
			self.leaderDisplaySizes[key] = max(0, int(numCells or 0))
		except (TypeError, ValueError):
			self.leaderDisplaySizes[key] = 0
		self._applyDisplaySize()

	def handleDisplaySize(self, sizes: list | None = None, **kw: Any) -> None:
		if isinstance(sizes, list):
			self.leaderDisplaySizes = {i: int(s) for i, s in enumerate(sizes) if isinstance(s, (int, float))}
			self._applyDisplaySize()

	@property
	def remoteDisplaySize(self) -> int:
		"""Celdas de la línea más pequeña de los equipos que controlan (0 = ninguna)."""
		sizes = [s for s in self.leaderDisplaySizes.values() if s > 0]
		return min(sizes) if sizes else 0

	def _applyDisplaySize(self) -> None:
		self.local.setBrailleDisplaySize(self.remoteDisplaySize)

	def _clientsChanged(self) -> None:
		known = set(self.clients)
		for k in list(self.leaderDisplaySizes):
			if k not in known and k != "?":
				del self.leaderDisplaySizes[k]
		if not self.leaders:
			self.leaderDisplaySizes.clear()
		self._applyDisplaySize()

	@property
	def hasLeaders(self) -> bool:
		return bool(self.leaders)

	@property
	def hasBrailleLeaders(self) -> bool:
		return self.remoteDisplaySize > 0

	# --- salida hacia quien controla
	def sendSpeech(self, sequence: list, priority: int = 0) -> bool:
		if not self.hasLeaders:
			return False
		try:
			prio = int(priority or 0)
		except (TypeError, ValueError):
			prio = 0
		return self.send(MessageType.SPEAK, sequence=list(sequence), priority=prio)

	def sendCancel(self) -> bool:
		return self.hasLeaders and self.send(MessageType.CANCEL)

	def sendPause(self, switch: bool) -> bool:
		return self.hasLeaders and self.send(MessageType.PAUSE_SPEECH, switch=bool(switch))

	def sendTone(self, hz: float, length: int, left: int = 50, right: int = 50) -> bool:
		return self.hasLeaders and self.send(MessageType.TONE, hz=hz, length=int(length), left=int(left), right=int(right))

	def sendWave(self, fileName: str, name: str = "") -> bool:
		payload: dict[str, Any] = {"fileName": fileName, "asynchronous": True}
		if name:
			payload["tiresiasSound"] = name
		return self.hasLeaders and self.send(MessageType.WAVE, **payload)

	def sendDisplay(self, cells: list[int]) -> bool:
		return self.hasBrailleLeaders and self.send(MessageType.DISPLAY, cells=[int(c) & 0xFF for c in cells])


class LeaderSession(RemoteSession):
	"""Este equipo controla a otro."""

	mode = ConnectionMode.LEADER

	def __init__(self, transport: RelayTransport, local: LocalMachine, dispatch: Dispatch | None = None) -> None:
		super().__init__(transport, local, dispatch)
		#: Datos de la línea braille local que se anuncian a los equipos controlados.
		self.brailleName = "noBraille"
		self.brailleCells = 0
		self.register(MessageType.SPEAK, self.handleSpeak)
		self.register(MessageType.CANCEL, self.handleCancel)
		self.register(MessageType.PAUSE_SPEECH, self.handlePause)
		self.register(MessageType.TONE, self.handleTone)
		self.register(MessageType.WAVE, self.handleWave)
		self.register(MessageType.DISPLAY, self.handleDisplay)
		self.register(MessageType.NVDA_NOT_CONNECTED, self.handleNotConnected)
		self.register(MessageType.SET_BRAILLE_INFO, self.handleOtherBrailleInfo)

	# --- salida recibida
	def handleSpeak(self, sequence: list | None = None, priority: Any = 0, **kw: Any) -> None:
		try:
			prio = int(priority or 0)
		except (TypeError, ValueError):
			prio = 0
		if sequence:
			self.local.speak(list(sequence), prio)

	def handleCancel(self, **kw: Any) -> None:
		self.local.cancelSpeech()

	def handlePause(self, switch: bool = False, **kw: Any) -> None:
		self.local.pauseSpeech(bool(switch))

	def handleTone(self, hz: float = 0, length: int = 0, left: int = 50, right: int = 50, **kw: Any) -> None:
		try:
			self.local.beep(float(hz), int(length), int(left), int(right))
		except (TypeError, ValueError):
			pass

	def handleWave(self, fileName: str = "", tiresiasSound: str = "", **kw: Any) -> None:
		self.local.playWave(fileName=str(fileName or ""), name=str(tiresiasSound or ""))

	def handleDisplay(self, cells: list | None = None, **kw: Any) -> None:
		if isinstance(cells, list):
			self.local.display([int(c) & 0xFF for c in cells if isinstance(c, (int, float))])

	def handleNotConnected(self, **kw: Any) -> None:
		self.local.onRemoteNotConnected(self)

	def handleOtherBrailleInfo(self, **kw: Any) -> None:
		# Otro equipo que controla anuncia su línea. No se responde: si los dos
		# equipos que controlan respondieran al del otro (NVDA también lo hace),
		# se enviarían ``set_braille_info`` sin fin. La línea propia ya se
		# anuncia al entrar cualquier cliente (:meth:`handleClientJoined`).
		pass

	def handleClientJoined(self, client: dict | None = None, user_id: Any = None, **kw: Any) -> None:
		super().handleClientJoined(client=client, user_id=user_id, **kw)
		self.sendBrailleInfo()

	@property
	def hasFollowers(self) -> bool:
		return bool(self.followers)

	# --- envío
	def setBrailleInfo(self, name: str, numCells: int) -> None:
		self.brailleName = name or "noBraille"
		self.brailleCells = max(0, int(numCells or 0))

	def sendBrailleInfo(self) -> bool:
		return self.send(MessageType.SET_BRAILLE_INFO, name=self.brailleName, numCells=self.brailleCells)

	def sendKey(self, vk: int, extended: bool, pressed: bool, scan: int | None = None) -> bool:
		payload: dict[str, Any] = {"vk_code": int(vk), "extended": bool(extended), "pressed": bool(pressed)}
		if scan is not None:
			payload["scan_code"] = int(scan)
		return self.send(MessageType.KEY, **payload)

	def sendSAS(self) -> bool:
		return self.send(MessageType.SEND_SAS)

	def sendBrailleInput(self, **payload: Any) -> bool:
		return self.send(MessageType.BRAILLE_INPUT, **payload)
