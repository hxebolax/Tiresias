"""Servidor de retransmisión local (conexión directa sin servidor externo).

Escucha en un puerto (IPv4 e IPv6) con TLS y reenvía los mensajes entre los
clientes del mismo canal, igual que los servidores públicos y que el
servidor local del acceso remoto de NVDA:

- Antes de unirse, un cliente solo puede enviar ``protocol_version``,
  ``join`` (con la clave del canal) o ``generate_key``.
- Al unirse recibe ``channel_joined`` con la lista de clientes, y los demás
  reciben ``client_joined``. Al salir, los demás reciben ``client_left``.
- Una vez dentro, todo lo que envía se reenvía a los demás clientes del
  canal añadiendo ``origin`` (identificador del remitente) si su protocolo
  es la versión 2 o posterior.

Si se indica ``password``, solo se admite ese canal (modo «conexión
directa»). Sin ``password`` se admite cualquier canal, como un servidor de
retransmisión público (útil para pruebas o para una red local).
"""

from __future__ import annotations

import hmac
import itertools
import select
import socket
import ssl
import threading
import time
from typing import Any

from ..log import getLogger
from . import serializer
from .certs import CertificateManager
from .connection import LineConnection
from .protocol import MessageType, generateKey

log = getLogger("remote")

PING_SECONDS = 300
HANDSHAKE_TIMEOUT = 15.0
#: Segundos que tiene un cliente para unirse al canal con la clave; si no, se desconecta.
JOIN_TIMEOUT = 20.0
#: Conexiones abiertas a la vez como máximo (unidas, esperando la clave o saludando).
MAX_CLIENTS = 64
#: Saludos TLS simultáneos como máximo.
MAX_HANDSHAKES = 16
#: Claves incorrectas desde una dirección antes de empezar a hacerla esperar.
FAIL_THRESHOLD = 3
#: Tiempo tras el que se olvidan los fallos de una dirección (s).
FAIL_WINDOW = 600.0
#: Espera máxima impuesta a una dirección que falla la clave (s).
MAX_BLOCK = 300.0


def _ipOf(addr: Any) -> str:
	try:
		return str(addr[0])
	except (TypeError, IndexError):
		return ""


class _Client:
	_ids = itertools.count(1)

	def __init__(self, server: "RelayServer", sock: ssl.SSLSocket, addr: Any) -> None:
		self.server = server
		self.id = next(self._ids)
		self.addr = addr
		self.channel: str | None = None
		self.connectionType: str | None = None
		self.protocolVersion = 1
		self.authenticated = False
		self.connectedAt = time.monotonic()
		self.conn = LineConnection(sock, self._onLine, self._onClose, name=f"servidor-cliente {self.id}")

	@property
	def ip(self) -> str:
		return _ipOf(self.addr)

	def asDict(self) -> dict:
		return {"id": self.id, "connection_type": self.connectionType}

	def start(self) -> None:
		self.conn.start()

	def close(self) -> None:
		self.conn.close()

	def send(self, type: str, origin: int | None = None, clients: list | None = None, client: dict | None = None, **payload: Any) -> None:
		msg = dict(payload)
		if self.protocolVersion > 1:
			if origin:
				msg["origin"] = origin
			if clients is not None:
				msg["clients"] = clients
			if client is not None:
				msg["client"] = client
		msg["type"] = type
		try:
			self.conn.send(serializer.serializeRaw(msg))
		except (TypeError, ValueError):
			log.exception("No se pudo reenviar un mensaje al cliente %d", self.id)

	def _onLine(self, line: bytes) -> None:
		try:
			obj = serializer.deserializeRaw(line)
		except ValueError:
			log.info("Mensaje no válido del cliente %d: se desconecta", self.id)
			self.close()
			return
		msgType = obj.get("type")
		if not isinstance(msgType, str):
			return
		if self.authenticated:
			obj.pop("origin", None)
			self.server._forward(self, obj)
			return
		if msgType == MessageType.PROTOCOL_VERSION.value:
			version = obj.get("version")
			if isinstance(version, int) and version > 0:
				self.protocolVersion = version
		elif msgType == MessageType.JOIN.value:
			self.server._join(self, obj)
		elif msgType == MessageType.GENERATE_KEY.value:
			self.send(MessageType.GENERATE_KEY.value, key=generateKey())

	def _onClose(self) -> None:
		self.server._removeClient(self)


class RelayServer:
	def __init__(
		self,
		port: int,
		password: str | None,
		certManager: CertificateManager,
		bindHosts: tuple[str, ...] = ("0.0.0.0", "::"),
	) -> None:
		self.password = password
		self.certManager = certManager
		self.fingerprint = certManager.ensureValid()
		self._context = certManager.serverContext()
		self._clients: dict[int, _Client] = {}
		self._lock = threading.RLock()
		self._stop = threading.Event()
		self._listeners: list[socket.socket] = []
		self._thread: threading.Thread | None = None
		#: Saludos TLS en curso.
		self._handshaking = 0
		#: Claves incorrectas por dirección: ip -> (fallos, instante del último).
		self._failures: dict[str, tuple[int, float]] = {}
		self.port = int(port)
		self._bind(bindHosts)

	# ------------------------------------------------------------------ escucha
	def _bind(self, hosts: tuple[str, ...]) -> None:
		errors = []
		for host in hosts:
			family = socket.AF_INET6 if ":" in host else socket.AF_INET
			s = socket.socket(family, socket.SOCK_STREAM)
			try:
				if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
					s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
				if family == socket.AF_INET6:
					s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
				s.bind((host, self.port))
				s.listen(8)
			except OSError as e:
				s.close()
				errors.append(e)
				log.info("No se pudo escuchar en %s:%d: %s", host, self.port, e)
				continue
			if self.port == 0:
				self.port = s.getsockname()[1]
			self._listeners.append(s)
		if not self._listeners:
			raise errors[0] if errors else OSError("No se pudo abrir el puerto")

	def start(self) -> None:
		self._thread = threading.Thread(target=self._run, name="Servidor remoto", daemon=True)
		self._thread.start()
		log.info("Servidor de acceso remoto escuchando en el puerto %d", self.port)

	def close(self) -> None:
		self._stop.set()
		for s in self._listeners:
			try:
				s.close()
			except OSError:
				pass
		with self._lock:
			clients = list(self._clients.values())
		for c in clients:
			c.close()
		if self._thread is not None and self._thread is not threading.current_thread():
			self._thread.join(3)
		log.info("Servidor de acceso remoto cerrado")

	@property
	def running(self) -> bool:
		return self._thread is not None and self._thread.is_alive()

	@property
	def clientCount(self) -> int:
		with self._lock:
			return sum(1 for c in self._clients.values() if c.authenticated)

	def _run(self) -> None:
		lastPing = time.monotonic()
		while not self._stop.is_set():
			try:
				readable, _w, _x = select.select(self._listeners, [], [], 1.0)
			except (OSError, ValueError):
				if self._stop.is_set():
					break
				time.sleep(0.2)
				continue
			for s in readable:
				try:
					raw, addr = s.accept()
				except OSError:
					continue
				reason = self._refusal(_ipOf(addr))
				if reason:
					log.info("Conexión remota rechazada desde %s: %s", addr, reason)
					try:
						raw.close()
					except OSError:
						pass
					continue
				threading.Thread(target=self._handshake, args=(raw, addr), name="Servidor remoto: saludo TLS", daemon=True).start()
			self._dropIdle()
			if time.monotonic() - lastPing >= PING_SECONDS:
				lastPing = time.monotonic()
				with self._lock:
					clients = [c for c in self._clients.values() if c.authenticated]
				for c in clients:
					c.send(MessageType.PING.value)

	# ------------------------------------------------------------------ límites
	def _refusal(self, ip: str) -> str:
		"""Motivo para rechazar una conexión nueva ("" si se admite); si se admite, cuenta su saludo."""
		wait = self.blockedFor(ip)
		if wait > 0:
			return f"demasiadas claves incorrectas (espera {wait:.0f} s)"
		with self._lock:
			if self._handshaking >= MAX_HANDSHAKES:
				return "demasiados saludos simultáneos"
			if len(self._clients) + self._handshaking >= MAX_CLIENTS:
				return "demasiadas conexiones"
			self._handshaking += 1
		return ""

	def blockedFor(self, ip: str) -> float:
		"""Segundos que aún debe esperar ``ip`` por haber fallado la clave (0 = nada)."""
		with self._lock:
			entry = self._failures.get(ip)
			if entry is None:
				return 0.0
			count, last = entry
			now = time.monotonic()
			if now - last > FAIL_WINDOW:
				del self._failures[ip]
				return 0.0
		if count < FAIL_THRESHOLD:
			return 0.0
		delay = min(MAX_BLOCK, 2.0 ** (count - FAIL_THRESHOLD + 1))
		return max(0.0, last + delay - now)

	def _recordFailure(self, ip: str) -> None:
		with self._lock:
			count, _last = self._failures.get(ip, (0, 0.0))
			self._failures[ip] = (count + 1, time.monotonic())
			if len(self._failures) > 4096:
				# Muchas direcciones distintas: se olvidan las más antiguas.
				for old in sorted(self._failures, key=lambda k: self._failures[k][1])[:2048]:
					del self._failures[old]

	def _dropIdle(self) -> None:
		"""Desconecta a quien no se ha unido al canal en :data:`JOIN_TIMEOUT` segundos."""
		now = time.monotonic()
		with self._lock:
			idle = [c for c in self._clients.values() if not c.authenticated and now - c.connectedAt > JOIN_TIMEOUT]
		for c in idle:
			log.info("Cliente remoto %d: no se ha unido al canal a tiempo; se desconecta", c.id)
			c.close()

	def _handshake(self, raw: socket.socket, addr: Any) -> None:
		try:
			self._handshakeInner(raw, addr)
		finally:
			with self._lock:
				self._handshaking = max(0, self._handshaking - 1)

	def _handshakeInner(self, raw: socket.socket, addr: Any) -> None:
		try:
			raw.settimeout(HANDSHAKE_TIMEOUT)
			raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
			sock = self._context.wrap_socket(raw, server_side=True)
		except (OSError, ssl.SSLError) as e:
			log.debug("Saludo TLS fallido desde %s: %s", addr, e)
			try:
				raw.close()
			except OSError:
				pass
			return
		if self._stop.is_set():
			sock.close()
			return
		client = _Client(self, sock, addr)
		with self._lock:
			self._clients[client.id] = client
		log.info("Cliente remoto %d conectado desde %s", client.id, addr)
		client.start()

	# ------------------------------------------------------------------ canal
	def _join(self, client: _Client, obj: dict) -> None:
		channel = obj.get("channel")
		valid = isinstance(channel, str) and bool(channel)
		if valid and self.password is not None:
			valid = hmac.compare_digest(channel.encode("utf-8", "surrogatepass"), self.password.encode("utf-8", "surrogatepass"))
		if not valid:
			log.info("Cliente %d: clave incorrecta", client.id)
			self._recordFailure(client.ip)
			client.send(MessageType.ERROR.value, error="incorrect_password", message="incorrect_password")
			client.close()
			return
		with self._lock:
			self._failures.pop(client.ip, None)
		ctype = obj.get("connection_type")
		client.connectionType = ctype if isinstance(ctype, str) else None
		with self._lock:
			client.channel = channel
			client.authenticated = True
			others = [c for c in self._clients.values() if c is not client and c.authenticated and c.channel == channel]
		client.send(
			MessageType.CHANNEL_JOINED.value,
			channel=channel,
			user_ids=[c.id for c in others],
			clients=[c.asDict() for c in others],
		)
		for c in others:
			c.send(MessageType.CLIENT_JOINED.value, origin=client.id, user_id=client.id, client=client.asDict())

	def _forward(self, sender: _Client, obj: dict) -> None:
		msgType = obj.pop("type")
		with self._lock:
			others = [c for c in self._clients.values() if c is not sender and c.authenticated and c.channel == sender.channel]
		for c in others:
			c.send(msgType, origin=sender.id, **obj)

	def _removeClient(self, client: _Client) -> None:
		with self._lock:
			if self._clients.pop(client.id, None) is None:
				return
			wasIn = client.authenticated
			others = [c for c in self._clients.values() if c.authenticated and c.channel == client.channel]
		log.info("Cliente remoto %d desconectado", client.id)
		if wasIn:
			for c in others:
				c.send(MessageType.CLIENT_LEFT.value, origin=client.id, user_id=client.id, client=client.asDict())
