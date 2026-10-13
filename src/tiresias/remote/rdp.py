"""Voz y braille por Escritorio remoto (canal virtual dinámico «TiresiasRdp»).

Petición de NVDA #3564: oír y leer en braille, con el lector del propio
equipo, lo que dice el lector que se ejecuta dentro de una sesión de
Escritorio remoto.

Dos papeles, que pueden estar activos a la vez en el mismo Tiresias:

- **Equipo cliente** (opción ``rdp.receiveFromRemote``): el usuario ejecuta
  aquí ``mstsc.exe``. ``tiresiasRdpClient.dll`` (registrada en HKCU, ver
  :mod:`.rdp_registration`) se carga en ``mstsc.exe`` y une el canal con la
  tubería ``\\\\.\\pipe\\TiresiasRdp.<sesión>``, que sirve
  :class:`RdpClientSide`. Cada ventana de Escritorio remoto con el canal
  abierto es una :class:`_Link` con una :class:`~.session.LeaderSession`:
  la voz recibida se habla aquí, las celdas braille se muestran cuando la
  ventana de Escritorio remoto está en primer plano y las teclas de la línea
  braille local se envían entonces al equipo remoto.
- **Equipo remoto** (opción ``rdp.sendToClient``): Tiresias se ejecuta dentro
  de la sesión. :class:`RdpServerSide` abre el canal con
  ``WTSVirtualChannelOpenEx`` y, con una :class:`~.session.FollowerSession`,
  envía la voz, los pitidos, los sonidos y el braille. Con
  ``rdp.muteLocalSpeech`` silencia su propia voz mientras el Tiresias del
  cliente está escuchando.

Los mensajes son los del acceso remoto (JSON por líneas, :mod:`.serializer`).
El Tiresias del cliente se anuncia con ``client_joined``; la biblioteca envía
``client_left`` si la tubería se cierra.

Otros clientes que cargan complementos de canal virtual dinámico de Microsoft
usan la misma biblioteca sin cambios: Windows App / Escritorio remoto de Azure
(``msrdc.exe``), Parallels Client, Omnissa Horizon Client (valores ``View
Enabled``/``Horizon Enabled``; en el servidor, ``vdp_rdpvcbridge.dll``) y
Citrix Workspace app (``wfica32.exe``, opción ``rdp.citrixClient``: ver
:class:`~.rdp_registration.CitrixRegistration`). En una sesión de Citrix el
servidor abre el canal con la misma ``WTSVirtualChannelOpenEx``; el
administrador debe permitirlo en la directiva «Virtual channel allow list for
DVC» (VDA 2407 o posterior) con :func:`citrixAllowListEntry`.

Variables de entorno para pruebas: ``TIRESIAS_RDP_CHANNEL_PIPE`` (el lado
remoto usa esa tubería como canal, sin comprobar que la sesión sea remota) y
``TIRESIAS_RDP_REGROOT`` (raíz del registro, ver :mod:`.rdp_registration`).
"""

from __future__ import annotations

import os
import queue
import threading
from typing import Any, Callable

from .. import queue_handler
from ..i18n import _
from ..log import getLogger
from . import rdp_io, serializer
from .local_machine import TiresiasMachine
from .protocol import ConnectionMode, MessageType
from .session import FollowerSession, LeaderSession

log = getLogger("rdp")

SECTION = "rdp"
DEFAULTS = {
	#: Equipo cliente: registrar el complemento de mstsc y recibir la voz.
	"receiveFromRemote": False,
	#: Dentro de una sesión remota: enviar la voz y el braille al cliente.
	"sendToClient": True,
	#: Dentro de una sesión remota: callar la voz propia mientras el cliente escucha.
	"muteLocalSpeech": True,
	#: Equipo cliente: registrar el complemento también en Citrix Workspace app.
	"citrixClient": False,
}

#: Programas cliente conocidos (nombre del ejecutable en minúsculas).
CLIENT_PROGRAMS = {
	"mstsc.exe": _("Conexión a Escritorio remoto"),
	"msrdc.exe": "Windows App",
	"wfica32.exe": "Citrix Workspace",
	"wfica.exe": "Citrix Workspace",
	"vmware-remotemks.exe": "Omnissa Horizon",
	"horizon-protocol.exe": "Omnissa Horizon",
	"vmware-view.exe": "Omnissa Horizon",
	"horizon-client.exe": "Omnissa Horizon",
}
#: Ventanas de Horizon Client: el canal vive en un proceso hijo suyo.
HORIZON_WINDOW_PROGRAMS = ("vmware-view.exe", "horizon-client.exe")
#: Cada cuánto se comprueba el registro de Citrix mientras está pendiente (segundos).
CITRIX_CHECK_INTERVAL = 30.0

#: Identificador con el que cada extremo ve al otro.
PEER_ID = "rdp"
#: Dueño del tamaño de línea remoto en ``braille.handler`` (el acceso remoto usa ``"remote"``).
BRAILLE_OWNER = "rdp"
#: Dueño del silencio de los pitidos y sonidos locales (:func:`tiresias.audio.tones.setMuted`).
TONES_OWNER = "rdp"
#: Líneas más largas se descartan (protección ante datos corruptos).
MAX_LINE = 4 * 1024 * 1024
#: Mensajes pendientes de escribir como máximo (si el otro lado no lee).
MAX_PENDING = 1000


def _noop(*args: Any, **kwargs: Any) -> None:
	pass


def _conf(key: str) -> Any:
	from ..config import conf

	try:
		return conf[SECTION][key]
	except KeyError:
		return DEFAULTS[key]


def _coreDispatch(func: Callable, *args: Any) -> None:
	queue_handler.queueFunction(func, *args)


# ====================================================================== transporte
class StreamTransport:
	"""Transporte de las sesiones de acceso remoto sobre un :class:`~.rdp_io.OverlappedStream`.

	Ofrece lo que usan :class:`~.session.RemoteSession` (``send``,
	``onMessage``, ``connected``, ``close``, ``stopReconnecting``). Un hilo lee
	y separa las líneas; otro escribe lo encolado, así ``send`` nunca bloquea.
	"""

	def __init__(self, stream: Any, name: str = "rdp") -> None:
		self.stream = stream
		self.name = name
		self.connected = False
		self.onMessage: Callable[[dict], None] = _noop
		self.onDisconnected: Callable[[], None] = _noop
		self._queue: queue.Queue[bytes | None] = queue.Queue(MAX_PENDING)
		self._lost = threading.Event()
		self._threads: list[threading.Thread] = []

	def start(self) -> None:
		self.connected = True
		for target, label in ((self._readLoop, "lectura"), (self._writeLoop, "escritura")):
			t = threading.Thread(target=target, name=f"Escritorio remoto ({self.name}): {label}", daemon=True)
			self._threads.append(t)
			t.start()

	def send(self, type: MessageType | str, **payload: Any) -> bool:
		if not self.connected:
			return False
		try:
			data = serializer.serialize(type, **payload)
		except (TypeError, ValueError):
			log.exception("No se pudo codificar el mensaje %s", type)
			return False
		try:
			self._queue.put_nowait(data)
		except queue.Full:
			log.debug("Cola de Escritorio remoto llena: se descarta %s", type)
			return False
		return True

	def stopReconnecting(self) -> None:
		pass

	def close(self) -> None:
		self._finish(notify=False)

	def join(self, timeout: float = 3.0) -> None:
		for t in self._threads:
			if t is not threading.current_thread():
				t.join(timeout)

	def _finish(self, notify: bool = True) -> None:
		if self._lost.is_set():
			return
		self._lost.set()
		self.connected = False
		try:
			self.stream.close()
		except Exception:
			log.debug("Error cerrando el flujo", exc_info=True)
		try:
			self._queue.put_nowait(None)
		except queue.Full:
			pass
		if notify:
			try:
				self.onDisconnected()
			except Exception:
				log.exception("Error en onDisconnected")

	def _readLoop(self) -> None:
		buf = b""
		try:
			while not self._lost.is_set():
				data = self.stream.read()
				if not data:
					break
				buf += data
				if b"\n" not in buf:
					if len(buf) > MAX_LINE:
						log.warning("Línea demasiado larga en el canal de Escritorio remoto: se descarta")
						buf = b""
					continue
				*lines, buf = buf.split(b"\n")
				for line in lines:
					line = line.strip()
					if not line:
						continue
					try:
						obj = serializer.deserialize(line)
					except ValueError:
						log.debug("Mensaje no válido en el canal de Escritorio remoto: %r", line[:200])
						continue
					try:
						self.onMessage(obj)
					except Exception:
						log.exception("Error atendiendo un mensaje de Escritorio remoto")
		finally:
			self._finish()

	def _writeLoop(self) -> None:
		while True:
			item = self._queue.get()
			if item is None or self._lost.is_set():
				break
			if not self.stream.write(item):
				break
		self._finish()


# ====================================================================== efectos locales
class RdpMachine(TiresiasMachine):
	""":class:`TiresiasMachine` sin lo que no tiene sentido por Escritorio remoto.

	El teclado y el portapapeles ya los lleva el propio protocolo RDP, y
	Control+Alt+Supr tiene su propia combinación en el cliente
	(Control+Alt+Fin): esos mensajes se ignoran.
	"""

	def __init__(self, owner: Any) -> None:
		super().__init__(client=None)
		self.owner = owner

	def speak(self, sequence: list, priority: int = 0) -> None:
		if log.isEnabledFor(10):
			log.debug("Voz: %s", " ".join(s for s in sequence if isinstance(s, str)))
		super().speak(sequence, priority)

	def sendKey(self, vk: int, extended: bool, pressed: bool, scan: int | None = None) -> None:
		pass

	def sendSAS(self) -> None:
		pass

	def setClipboardText(self, text: str) -> None:
		pass

	def setBrailleDisplaySize(self, size: int) -> None:
		self.owner._onBrailleSize(size)

	def onClientJoined(self, session, client: dict) -> None:
		self.owner._onPeerJoined(session, client)

	def onClientLeft(self, session, client: dict) -> None:
		self.owner._onPeerLeft(session, client)

	def onMotd(self, session, motd: str, forceDisplay: bool) -> None:
		pass

	def onServerError(self, session, error: str) -> None:
		log.debug("Error recibido por Escritorio remoto: %s", error)

	def onVersionMismatch(self, session) -> None:
		pass

	def onRemoteNotConnected(self, session) -> None:
		pass


def brailleGesturePayload(gesture: Any, func: Any) -> dict:
	"""Mensaje ``braille_input`` para un gesto de la línea braille local."""
	from .. import braille

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
	return payload


# ====================================================================== equipo cliente
class _Link:
	"""Una ventana de Escritorio remoto (un proceso del cliente) con el canal abierto."""

	def __init__(self, owner: "RdpClientSide", stream: Any, pid: int) -> None:
		self.owner = owner
		self.pid = pid
		exe, parent = owner.processInfo(pid) if pid else ("", 0)
		#: Ejecutable del programa cliente (``mstsc.exe``, ``wfica32.exe``...).
		self.exe = (exe or "").lower()
		#: Procesos cuya ventana en primer plano muestra el braille de esta conexión.
		self.windowPids = {pid}
		if parent and owner.processInfo(parent)[0].lower() in HORIZON_WINDOW_PROGRAMS:
			self.windowPids.add(parent)
		self.machine = owner.machineFactory(owner)
		self.transport = StreamTransport(stream, name=f"cliente {pid}")
		self.session = LeaderSession(self.transport, self.machine, owner.dispatch)
		self.transport.onDisconnected = lambda: owner.dispatch(owner._linkLost, self)
		self.active = False


class RdpClientSide:
	"""Equipo cliente: tubería para la biblioteca de mstsc y sesiones de quien escucha."""

	def __init__(
		self,
		pipeName: str | None = None,
		dispatch: Callable[..., None] = _coreDispatch,
		tiresiasHooks: bool = True,
		machineFactory: Callable[[Any], Any] | None = None,
		processInfo: Callable[[int], tuple[str, int]] | None = None,
	) -> None:
		self.pipeName = pipeName or rdp_io.pipeName()
		self.dispatch = dispatch
		#: Nombre del ejecutable y PID del padre de un proceso (inyectable en las pruebas).
		self.processInfo = processInfo or rdp_io.processInfo
		#: Crea el objeto que produce los efectos locales de cada conexión.
		self.machineFactory = machineFactory or RdpMachine
		#: ``False`` en las pruebas sin Tiresias (sin braille, foco ni gestos).
		self.tiresiasHooks = tiresiasHooks
		self.links: list[_Link] = []
		self._listener: rdp_io.PipeListener | None = None
		self._hooked = False
		self._lastBraille: tuple[str, int] | None = None

	@property
	def running(self) -> bool:
		return self._listener is not None and self._listener.running

	def start(self) -> None:
		if self.running:
			return
		self._listener = rdp_io.PipeListener(self.pipeName, self._onConnection)
		self._listener.start()

	def stop(self) -> None:
		if self._listener is not None:
			self._listener.stop()
			self._listener = None
		for link in list(self.links):
			link.transport.close()
			self._removeLink(link)

	# --- hilo de la tubería
	def _onConnection(self, stream: Any, pid: int) -> None:
		link = _Link(self, stream, pid)
		link.transport.start()
		self.dispatch(self._linkReady, link)

	# --- hilo del núcleo
	def _linkReady(self, link: _Link) -> None:
		if not link.transport.connected:
			return
		self.links.append(link)
		log.info("Canal de Escritorio remoto conectado (%s, proceso %d)", link.exe or "?", link.pid)
		name, cells = self._brailleInfo()
		link.session.setBrailleInfo(name, cells)
		# Se anuncia al equipo remoto como quien controla (empieza a enviar)
		# y, al registrarlo localmente, se le envía el tamaño de la línea.
		link.session.send(MessageType.CLIENT_JOINED, client={"id": PEER_ID, "connection_type": ConnectionMode.LEADER.value})
		link.session.handleClientJoined(client={"id": PEER_ID, "connection_type": ConnectionMode.FOLLOWER.value})
		self._hook()
		self._updateForeground()

	def _linkLost(self, link: _Link) -> None:
		log.info("Canal de Escritorio remoto cerrado (proceso %d)", link.pid)
		self._removeLink(link)

	def _removeLink(self, link: _Link) -> None:
		if link in self.links:
			self.links.remove(link)
		if link.active:
			link.active = False
			if self.tiresiasHooks:
				link.machine.setReceivingBraille(False)
		if not self.links:
			self._unhook()

	def _onPeerJoined(self, session, client: dict) -> None:
		pass

	def _onPeerLeft(self, session, client: dict) -> None:
		pass

	def _onBrailleSize(self, size: int) -> None:
		pass

	# --- braille
	def _brailleInfo(self) -> tuple[str, int]:
		if not self.tiresiasHooks:
			return ("noBraille", 0)
		try:
			from .. import braille

			display = braille.handler.display
			return (display.name, int(display.numCells))
		except Exception:
			return ("noBraille", 0)

	def _activeLink(self) -> _Link | None:
		return next((link for link in self.links if link.active), None)

	def _updateForeground(self) -> None:
		if not self.tiresiasHooks:
			return
		from .. import winapi

		fg = winapi.getForegroundWindow()
		pid = winapi.getWindowProcessId(fg) if fg else 0
		self._setForegroundPid(pid)

	def _setForegroundPid(self, pid: int) -> None:
		# Primero se desactiva la ventana que deja de estar en primer plano y
		# después se activa la nueva: al pasar de una ventana de Escritorio remoto
		# a otra, la línea no vuelve a mostrar lo local tras activar la nueva.
		changes = [(link, pid != 0 and pid in link.windowPids) for link in self.links]
		for link, state in changes:
			if not state and link.active:
				link.active = False
				link.machine.setReceivingBraille(False)
		for link, state in changes:
			if state and not link.active:
				link.active = True
				link.machine.setReceivingBraille(True)
		info = self._brailleInfo()
		if info != self._lastBraille:
			# Se ha cambiado de línea braille: se anuncia el tamaño nuevo.
			self._lastBraille = info
			for link in self.links:
				link.session.setBrailleInfo(*info)
				link.session.sendBrailleInfo()

	def _onFocus(self, obj: Any = None) -> None:
		self._updateForeground()

	def _onBrailleGesture(self, gesture: Any) -> bool:
		link = self._activeLink()
		if link is None or not link.transport.connected:
			return True
		from ..input import core as inputCore

		try:
			func = inputCore.manager.findScript(gesture)
		except Exception:
			func = None
		link.session.sendBrailleInput(**brailleGesturePayload(gesture, func))
		return False

	def _hook(self) -> None:
		if self._hooked or not self.tiresiasHooks:
			return
		from .. import api
		from ..input import core as inputCore

		api.post_focusChange.register(self._onFocus)
		inputCore.decide_executeBrailleGesture.register(self._onBrailleGesture)
		self._hooked = True

	def _unhook(self) -> None:
		if not self._hooked:
			return
		from .. import api
		from ..input import core as inputCore

		api.post_focusChange.unregister(self._onFocus)
		inputCore.decide_executeBrailleGesture.unregister(self._onBrailleGesture)
		self._hooked = False
		self._lastBraille = None


# ====================================================================== equipo remoto
class RdpServerSide:
	"""Dentro de una sesión remota: abre el canal y envía la voz y el braille."""

	#: Esperas entre intentos de abrir el canal (segundos).
	RETRY_DELAYS = (5, 15, 30, 60)

	def __init__(
		self,
		openChannel: Callable[[], Any] | None = None,
		isRemote: Callable[[], bool] | None = None,
		dispatch: Callable[..., None] = _coreDispatch,
		tiresiasHooks: bool = True,
	) -> None:
		testPipe = os.environ.get("TIRESIAS_RDP_CHANNEL_PIPE")
		if openChannel is None:
			openChannel = (lambda: rdp_io.openPipeAsChannel(testPipe)) if testPipe else rdp_io.openDynamicChannel
		if isRemote is None:
			isRemote = (lambda: True) if testPipe else rdp_io.isRemoteSession
		self._open = openChannel
		self._isRemote = isRemote
		self.dispatch = dispatch
		self.tiresiasHooks = tiresiasHooks
		self.session: FollowerSession | None = None
		self.transport: StreamTransport | None = None
		self.machine = RdpMachine(self)
		self._stop = threading.Event()
		self._wake = threading.Event()
		self._thread: threading.Thread | None = None
		self._hooked = False
		self._muted = False
		self._setCells = False
		self.attempts = 0

	@property
	def running(self) -> bool:
		return self._thread is not None and self._thread.is_alive()

	@property
	def listening(self) -> bool:
		"""Hay un Tiresias escuchando en el equipo cliente."""
		s = self.session
		return s is not None and s.hasLeaders and s.transport.connected

	def start(self) -> None:
		if self.running:
			return
		self._stop.clear()
		self._thread = threading.Thread(target=self._run, name="Escritorio remoto: canal", daemon=True)
		self._thread.start()

	def stop(self) -> None:
		self._stop.set()
		self._wake.set()
		transport = self.transport
		if transport is not None:
			transport.close()
		# WTSVirtualChannelOpenEx no se puede interrumpir: el hilo es de fondo y
		# termina solo al volver de la llamada.
		self._thread = None
		self._detach()

	# --- hilo del canal
	def _run(self) -> None:
		failures = 0
		while not self._stop.is_set():
			if not self._isRemote():
				failures = 0
				self._sleep(10)
				continue
			try:
				stream = self._open()
			except OSError as e:
				self.attempts += 1
				delay = self.RETRY_DELAYS[min(failures, len(self.RETRY_DELAYS) - 1)]
				if failures == 0:
					log.info("El cliente de Escritorio remoto no tiene el canal de Tiresias (%s); se reintentará", e)
				failures += 1
				self._sleep(delay)
				continue
			self.attempts += 1
			failures = 0
			if self._stop.is_set():
				stream.close()
				break
			transport = StreamTransport(stream, name="servidor")
			lost = threading.Event()
			transport.onDisconnected = lost.set
			session = FollowerSession(transport, self.machine, self.dispatch)
			self.transport = transport
			self.session = session
			transport.start()
			log.info("Canal de Escritorio remoto abierto con el equipo cliente")
			self.dispatch(self._attach, session)
			while not lost.is_set() and not self._stop.is_set():
				lost.wait(1.0)
			transport.close()
			self.dispatch(self._detachIfCurrent, session)
			log.info("Canal de Escritorio remoto cerrado")
			self._sleep(2)

	def _sleep(self, seconds: float) -> None:
		self._wake.wait(seconds)
		self._wake.clear()

	def retryNow(self) -> None:
		self._wake.set()

	# --- hilo del núcleo
	def _attach(self, session: FollowerSession) -> None:
		if session is not self.session:
			return
		self._hook()

	def _detachIfCurrent(self, session: FollowerSession) -> None:
		if session is self.session:
			self._detach()

	def _detach(self) -> None:
		self._unhook()
		self._setMuted(False)
		if self._setCells:
			self._setCells = False
			if self.tiresiasHooks:
				from .. import braille

				braille.handler.setRemoteNumCells(0, owner=BRAILLE_OWNER)
		self.session = None
		self.transport = None

	def _onPeerJoined(self, session, client: dict) -> None:
		if session is not self.session:
			return
		log.info("El Tiresias del equipo cliente escucha")
		self.applyMute()
		if self.tiresiasHooks:
			from .. import speech

			speech.speakMessage(_("Voz enviada al equipo cliente"))

	def _onPeerLeft(self, session, client: dict) -> None:
		if session is not self.session:
			return
		log.info("El Tiresias del equipo cliente ya no escucha")
		self._setMuted(False)
		self._onBrailleSize(0)

	def _onBrailleSize(self, size: int) -> None:
		if not self.tiresiasHooks:
			return
		from .. import braille

		self._setCells = size > 0
		braille.handler.setRemoteNumCells(size, owner=BRAILLE_OWNER)

	# --- silencio de la voz local
	def applyMute(self) -> None:
		self._setMuted(bool(_conf("muteLocalSpeech")) and self.listening)

	def _setMuted(self, state: bool) -> None:
		if state == self._muted and not state:
			return
		self._muted = state
		if not self.tiresiasHooks:
			return
		from .. import synth as synthHandler

		player = getattr(synthHandler.getSynth(), "_player", None)
		if player is not None and hasattr(player, "muted"):
			player.muted = state
		# Como dice el manual (19.13.1): tampoco suenan los pitidos ni los sonidos
		# locales (se siguen enviando al cliente: los avisos van antes del volumen).
		from ..audio import tones

		tones.setMuted(TONES_OWNER, state)
		if state:
			log.info("Voz, pitidos y sonidos locales silenciados mientras se envían al equipo cliente")

	def _onSynthChanged(self, synth: Any = None) -> None:
		if self._muted:
			self._setMuted(True)

	# --- salida local -> cliente
	def _listening(self) -> FollowerSession | None:
		s = self.session
		return s if s is not None and s.hasLeaders else None

	def _onSpeechQueued(self, speechSequence: list | None = None, priority: int = 0, **kw: Any) -> None:
		"""``pre_speechQueued``: la voz se envía con su prioridad real."""
		self._onPreSpeech(speechSequence or [], priority)

	def _onPreSpeech(self, sequence: list, priority: int = 0) -> None:
		s = self._listening()
		if s is not None and sequence:
			s.sendSpeech(sequence, priority)

	def _onSpeechCanceled(self) -> None:
		s = self._listening()
		if s is not None:
			s.sendCancel()

	def _onSpeechPaused(self, switch: bool) -> None:
		s = self._listening()
		if s is not None:
			s.sendPause(switch)

	def _onBeep(self, hz: float, length: int, left: int = 50, right: int = 50) -> None:
		s = self._listening()
		if s is not None:
			s.sendTone(hz, length, left, right)

	def _onPlaySound(self, name: str = "", fileName: str = "") -> None:
		s = self._listening()
		if s is None or name.startswith("remote"):
			return
		from .local_machine import nvdaWavePath

		s.sendWave(fileName or (nvdaWavePath(name) if name else ""), name)

	def _onDisplayUpdate(self, cells: list) -> None:
		s = self._listening()
		if s is not None:
			s.sendDisplay(cells)

	def _hook(self) -> None:
		if self._hooked or not self.tiresiasHooks:
			return
		from .. import braille, synth as synthHandler
		from ..audio import tones
		from ..speech import api as speechApi

		speechApi.pre_speechQueued.register(self._onSpeechQueued)
		speechApi.pre_speechCanceled.register(self._onSpeechCanceled)
		speechApi.post_speechPaused.register(self._onSpeechPaused)
		tones.pre_beep.register(self._onBeep)
		tones.pre_playSound.register(self._onPlaySound)
		braille.post_displayUpdate.register(self._onDisplayUpdate)
		synthHandler.synthChanged.register(self._onSynthChanged)
		self._hooked = True

	def _unhook(self) -> None:
		if not self._hooked:
			return
		from .. import braille, synth as synthHandler
		from ..audio import tones
		from ..speech import api as speechApi

		speechApi.pre_speechQueued.unregister(self._onSpeechQueued)
		speechApi.pre_speechCanceled.unregister(self._onSpeechCanceled)
		speechApi.post_speechPaused.unregister(self._onSpeechPaused)
		tones.pre_beep.unregister(self._onBeep)
		tones.pre_playSound.unregister(self._onPlaySound)
		braille.post_displayUpdate.unregister(self._onDisplayUpdate)
		synthHandler.synthChanged.unregister(self._onSynthChanged)
		self._hooked = False


# ====================================================================== gestión
_client: RdpClientSide | None = None
_server: RdpServerSide | None = None
_initialized = False


def registerDefaults() -> None:
	from ..config import conf

	conf.registerDefaults(SECTION, DEFAULTS)


def getClientSide() -> RdpClientSide | None:
	return _client


def getServerSide() -> RdpServerSide | None:
	return _server


def initialize() -> None:
	"""Hilo del núcleo (lo llama :func:`tiresias.remote.initialize`)."""
	global _initialized
	if _initialized:
		return
	registerDefaults()
	from .. import config

	config.post_configProfileSwitch.register(_onProfileSwitch)
	_initialized = True
	applyConfig(startup=True)


def _onProfileSwitch() -> None:
	# Los cambios de perfil pueden notificarse desde la interfaz: al núcleo.
	queue_handler.queueFunction(applyConfig)


def applyConfig(startup: bool = False) -> str:
	"""Pone en marcha o detiene cada papel según las opciones (hilo del núcleo).

	Devuelve el resultado de :func:`syncRegistration` (``"error"`` si falla).
	"""
	global _client, _server
	receive = bool(_conf("receiveFromRemote"))
	# Registro del complemento de mstsc: solo si el usuario lo ha pedido.
	try:
		result = syncRegistration(receive, startup=startup)
	except Exception:
		log.exception("No se pudo actualizar el registro del complemento de Escritorio remoto")
		result = "error"
	# Citrix Workspace usa el mismo objeto COM: va después del registro anterior.
	_applyCitrix(receive, startup=startup)
	if receive:
		if _client is None:
			_client = RdpClientSide()
		_client.start()
	elif _client is not None:
		_client.stop()
		_client = None
	if _conf("sendToClient"):
		if _server is None:
			_server = RdpServerSide()
		_server.start()
		_server.applyMute()
	elif _server is not None:
		_server.stop()
		_server = None
	return result


def syncRegistration(enabled: bool, startup: bool = False) -> str:
	"""Registra o quita el complemento. Devuelve ``"registered"``, ``"unregistered"``, ``"missing"`` o ``""``.

	Al arrancar con la opción desactivada solo se borra un registro que
	apunte a esta copia de Tiresias (puede haber otra copia que lo use).
	"""
	from .. import paths
	from .rdp_registration import ARCHES, RdpRegistration, dllPath

	reg = RdpRegistration()
	if enabled:
		dlls = {arch: dllPath(arch) for arch in ARCHES}
		current = reg.registeredPaths()
		wanted = {a: os.path.abspath(p) for a, p in dlls.items() if os.path.isfile(p)}
		if not wanted:
			log.error("No se encuentra tiresiasRdpClient.dll en %s", paths.rdpBinDir())
			return "missing"
		if reg.addinRegistered() and reg.horizonEnabled() and {a: os.path.normcase(p) for a, p in current.items()} == {a: os.path.normcase(p) for a, p in wanted.items()}:
			return ""
		reg.register(dlls)
		return "registered"
	if startup and not reg.pointsTo(paths.APP_DIR):
		return ""
	return "unregistered" if reg.unregister() else ""


# ====================================================================== Citrix Workspace
_citrixResult = ""
_citrixWatcher: "_CitrixWatcher | None" = None
#: Serializa los cambios del registro de Citrix entre el hilo del núcleo
#: (opciones) y el vigilante: al desmarcar la opción, el vigilante no puede
#: volver a registrar el complemento justo después de quitarlo.
_citrixLock = threading.Lock()


def syncCitrix(enabled: bool) -> str:
	"""Pone o quita el complemento en Citrix Workspace app (solo HKCU).

	Devuelve ``"registered"``, ``"unregistered"``, ``"pending"`` (Citrix aún
	no tiene configuración de usuario: hay que abrir una sesión una vez),
	``"notInstalled"`` o ``""`` (sin cambios). Solo se registra si también
	está registrado el objeto COM del complemento (:func:`syncRegistration`).
	"""
	from .rdp_registration import CitrixRegistration, RdpRegistration

	ctx = CitrixRegistration()
	if not enabled:
		return "unregistered" if ctx.unregister() else ""
	if not RdpRegistration().isRegistered():
		return "missing"
	state = ctx.state()
	if state == ctx.REGISTERED:
		return ""
	if state == ctx.READY:
		return "registered" if ctx.register() else "pending"
	return "pending" if state == ctx.NO_SESSION else "notInstalled"


class _CitrixWatcher:
	"""Mientras Citrix no tenga configuración de usuario, la vigila y registra el complemento.

	Citrix Workspace app copia su configuración al usuario al abrir la
	primera sesión (y una actualización puede rehacerla): se comprueba cada
	:data:`CITRIX_CHECK_INTERVAL` segundos en un hilo propio, solo lecturas
	del registro salvo cuando hay que registrar.
	"""

	def __init__(self, interval: float = CITRIX_CHECK_INTERVAL, onRegistered: Callable[[], None] | None = None, isWanted: Callable[[], bool] | None = None) -> None:
		self.interval = interval
		self.onRegistered = onRegistered or _announceCitrixReady
		#: ¿Sigue pedida la opción? (por defecto, las opciones de Tiresias).
		self.isWanted = isWanted or _citrixWanted
		self._stop = threading.Event()
		self._thread = threading.Thread(target=self._run, name="Escritorio remoto: Citrix", daemon=True)

	def start(self) -> None:
		self._thread.start()

	def stop(self) -> None:
		self._stop.set()

	@property
	def running(self) -> bool:
		return self._thread.is_alive()

	def _run(self) -> None:
		global _citrixResult
		while not self._stop.wait(self.interval):
			try:
				with _citrixLock:
					# Se comprueba con el cerrojo: si entretanto se ha desmarcado la
					# opción (o se ha parado el vigilante), no se registra nada.
					if self._stop.is_set() or not self.isWanted():
						break
					result = syncCitrix(True)
			except OSError:
				log.debug("Comprobación de Citrix fallida", exc_info=True)
				continue
			if result == "registered":
				_citrixResult = result
				log.info("Citrix Workspace ya tiene configuración de usuario: complemento registrado")
				self.onRegistered()


def _citrixWanted() -> bool:
	return bool(_conf("receiveFromRemote") and _conf("citrixClient"))


def _announceCitrixReady() -> None:
	def speak() -> None:
		from .. import speech

		speech.speakMessage(_("Tiresias ya puede recibir la voz de Citrix. Cierra la sesión de Citrix y vuelve a abrirla."))

	_coreDispatch(speak)


def _applyCitrix(receive: bool, startup: bool = False) -> str:
	"""Hilo del núcleo: registro de Citrix según las opciones y vigilancia si queda pendiente."""
	global _citrixResult, _citrixWatcher
	enabled = receive and bool(_conf("citrixClient"))
	if not enabled and _citrixWatcher is not None:
		# Se para el vigilante antes de quitar el registro.
		_citrixWatcher.stop()
		_citrixWatcher = None
	try:
		from .. import paths
		from .rdp_registration import RdpRegistration

		with _citrixLock:
			reg = RdpRegistration()
			if not enabled and startup and reg.isRegistered() and not reg.pointsTo(paths.APP_DIR):
				# Al arrancar sin la opción: el registro es de otra copia de Tiresias.
				result = ""
			else:
				result = syncCitrix(enabled)
	except OSError:
		log.exception("No se pudo actualizar el registro del complemento en Citrix Workspace")
		result = "error"
	_citrixResult = result
	if enabled:
		if _citrixWatcher is None or not _citrixWatcher.running:
			_citrixWatcher = _CitrixWatcher()
			_citrixWatcher.start()
	elif _citrixWatcher is not None:
		_citrixWatcher.stop()
		_citrixWatcher = None
	return result


def citrixResult() -> str:
	"""Resultado del último cambio del registro de Citrix (para el panel de opciones)."""
	return _citrixResult


def citrixStatusText() -> str:
	"""Estado del complemento en Citrix Workspace app de este equipo."""
	from .rdp_registration import CitrixRegistration

	try:
		state = CitrixRegistration().state()
	except OSError as e:
		return _("No se pudo consultar el registro: {error}").format(error=e)
	if state == CitrixRegistration.REGISTERED:
		return _("Registrado para el usuario actual: Citrix Workspace cargará Tiresias al abrir la próxima sesión.")
	if not (_conf("receiveFromRemote") and _conf("citrixClient")):
		if state == CitrixRegistration.NOT_INSTALLED:
			return _("Citrix Workspace no está instalado en este equipo.")
		return _("No registrado.")
	if state == CitrixRegistration.NO_SESSION:
		return _("Pendiente: abre una vez cualquier sesión de Citrix; Tiresias se registrará solo y te avisará.")
	if state == CitrixRegistration.NOT_INSTALLED:
		return _("Citrix Workspace no está instalado (la versión de Microsoft Store no admite complementos).")
	return _("No registrado: falta el complemento de Escritorio remoto (marca «Recibir la voz de los equipos remotos»).")


def citrixAllowListEntry(executable: str | None = None) -> str:
	"""Entrada para la directiva de Citrix «Virtual channel allow list for DVC».

	Formato de Citrix: ``<proceso del servidor>,<complemento del cliente>,<oyente>``.
	El proceso es el de este Tiresias (el que abre el canal en el servidor).
	"""
	import sys

	from .rdp_registration import CITRIX_PLUGIN

	exe = os.path.abspath(executable or sys.executable)
	return f"{exe},{CITRIX_PLUGIN},{rdp_io.CHANNEL_NAME}"


def statusText() -> str:
	"""Estado para el panel de opciones y la orden de estado."""
	parts = []
	server = _server
	if server is not None and server.running:
		if server.listening:
			parts.append(_("Sesión remota: enviando la voz al equipo cliente."))
		elif server.transport is not None and server.transport.connected:
			parts.append(_("Sesión remota: canal abierto; el Tiresias del equipo cliente aún no escucha."))
		elif os.environ.get("TIRESIAS_RDP_CHANNEL_PIPE"):
			parts.append(_("Sesión remota: el equipo cliente no tiene activada la recepción de la voz de Tiresias."))
		else:
			kind = rdp_io.remoteKind()
			if kind == rdp_io.KIND_CITRIX:
				parts.append(
					_(
						"Sesión de Citrix: no hay canal con el equipo cliente. Comprueba que allí Tiresias tenga marcadas "
						"«Recibir la voz» y «Cargar el complemento también en Citrix Workspace», y que la directiva de Citrix "
						"«Virtual channel allow list for DVC» incluya: {entry}"
					).format(entry=citrixAllowListEntry())
				)
			elif kind == rdp_io.KIND_HORIZON:
				parts.append(_("Sesión de Omnissa Horizon: el equipo cliente no tiene activada la recepción de la voz de Tiresias."))
			elif kind:
				parts.append(_("Sesión remota: el equipo cliente no tiene activada la recepción de la voz de Tiresias."))
	client = _client
	if client is not None and client.running:
		n = len(client.links)
		if n:
			programs = sorted({CLIENT_PROGRAMS.get(link.exe, link.exe or "?") for link in client.links})
			parts.append(_("Recibiendo la voz de {n} conexión(es) ({programs}).").format(n=n, programs=", ".join(programs)))
		else:
			parts.append(_("Esperando conexiones de Escritorio remoto."))
	if not parts:
		parts.append(_("Escritorio remoto: sin conexiones."))
	return " ".join(parts)


def terminate() -> None:
	global _client, _server, _initialized, _citrixWatcher
	if _citrixWatcher is not None:
		_citrixWatcher.stop()
		_citrixWatcher = None
	if _client is not None:
		_client.stop()
		_client = None
	if _server is not None:
		_server.stop()
		_server = None
	if _initialized:
		from .. import config

		config.post_configProfileSwitch.unregister(_onProfileSwitch)
	_initialized = False
