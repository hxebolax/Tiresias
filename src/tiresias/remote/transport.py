"""Transporte del cliente: conexión TLS a un servidor de retransmisión.

:class:`RelayTransport` se conecta en un hilo propio, envía la versión del
protocolo y se une al canal (o pide una clave), y vuelve a conectar si la
conexión se pierde. Todas las retrollamadas (``onConnected``,
``onMessage``...) se llaman desde hilos de red: quien las use debe pasar el
trabajo a su propio hilo (el núcleo de Tiresias, la interfaz...).

Certificados: primero se intenta validar el certificado con las autoridades
de Windows. Si falla (servidor propio con certificado autofirmado), se lee
su huella SHA-256: si está entre las de confianza se conecta sin validar la
cadena pero comprobando que la huella coincide; si no, se avisa con
``onCertificateFailed(huella)`` y no se reintenta.
"""

from __future__ import annotations

import hashlib
import socket
import ssl
import threading
from typing import Any, Callable

from ..log import getLogger
from . import serializer
from .connection import LineConnection
from .protocol import PROTOCOL_VERSION, MessageType, hostPortToAddress

log = getLogger("remote")


class CertificateRejected(Exception):
	def __init__(self, fingerprint: str | None) -> None:
		super().__init__(f"Certificado no confiable ({fingerprint})")
		self.fingerprint = fingerprint


def fingerprintOf(derCert: bytes) -> str:
	"""Huella SHA-256 de un certificado DER (hexadecimal en minúsculas)."""
	return hashlib.sha256(derCert).hexdigest().lower()


def formatFingerprint(fp: str | None) -> str:
	"""``"ab12cd..."`` -> ``"AB:12:CD:..."`` (para mostrarla al usuario)."""
	if not fp:
		return "?"
	fp = fp.upper()
	return ":".join(fp[i : i + 2] for i in range(0, len(fp), 2))


def _noop(*args: Any, **kwargs: Any) -> None:
	pass


class RelayTransport:
	def __init__(
		self,
		hostname: str,
		port: int,
		*,
		channel: str | None,
		connectionType: str | None,
		protocolVersion: int = PROTOCOL_VERSION,
		insecure: bool = False,
		trustedFingerprint: str | None = None,
		isTrusted: Callable[[str, str], bool] | None = None,
		timeout: float = 10.0,
		reconnect: bool = True,
		reconnectDelay: float = 5.0,
		name: str = "remoto",
	) -> None:
		self.hostname = hostname
		self.port = int(port)
		self.channel = channel
		self.connectionType = connectionType
		self.protocolVersion = protocolVersion
		self.insecure = insecure
		self.trustedFingerprint = trustedFingerprint.lower() if trustedFingerprint else None
		self._isTrusted = isTrusted or (lambda address, fp: False)
		self.timeout = timeout
		self.reconnect = reconnect
		self.reconnectDelay = reconnectDelay
		self.name = name
		self.connected = False
		self.successfulConnects = 0
		self.failedAttempts = 0
		self.lastFailFingerprint: str | None = None
		self.lastError: BaseException | None = None
		self.connectedEvent = threading.Event()
		self._stop = threading.Event()
		self._conn: LineConnection | None = None
		self._thread: threading.Thread | None = None
		#: Retrollamadas (se llaman desde hilos de red).
		self.onConnected: Callable[[], None] = _noop
		self.onDisconnected: Callable[[], None] = _noop
		self.onConnectionFailed: Callable[[BaseException], None] = _noop
		self.onCertificateFailed: Callable[[str | None], None] = _noop
		self.onMessage: Callable[[dict], None] = _noop

	# ------------------------------------------------------------------ datos
	@property
	def address(self) -> tuple[str, int]:
		return (self.hostname, self.port)

	@property
	def addressKey(self) -> str:
		"""Clave con la que se guarda la huella de este servidor."""
		return hostPortToAddress(self.address)

	@property
	def running(self) -> bool:
		return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

	# ------------------------------------------------------------------ control
	def start(self) -> None:
		self._stop.clear()
		self._thread = threading.Thread(target=self._connectorLoop, name=f"Conector {self.name}", daemon=True)
		self._thread.start()

	def close(self) -> None:
		"""Desconecta y deja de reintentar (seguro desde cualquier hilo)."""
		self._stop.set()
		conn = self._conn
		if conn is not None:
			conn.close()

	def stopReconnecting(self) -> None:
		self.reconnect = False

	def join(self, timeout: float | None = None) -> None:
		if self._thread is not None and self._thread is not threading.current_thread():
			self._thread.join(timeout)

	def send(self, type: MessageType | str, **payload: Any) -> bool:
		"""Envía un mensaje si hay conexión (no bloquea; seguro desde cualquier hilo)."""
		conn = self._conn
		if conn is None or not self.connected:
			return False
		try:
			data = serializer.serialize(type, **payload)
		except (TypeError, ValueError):
			log.exception("No se pudo codificar el mensaje %s", type)
			return False
		return conn.send(data)

	# ------------------------------------------------------------------ hilo
	def _connectorLoop(self) -> None:
		while not self._stop.is_set():
			try:
				sock = self._open()
			except CertificateRejected as e:
				self.lastFailFingerprint = e.fingerprint
				self.lastError = e
				self.failedAttempts += 1
				log.info("Certificado no confiable para %s (huella %s)", self.addressKey, e.fingerprint)
				self._stop.set()
				self._safe(self.onCertificateFailed, e.fingerprint)
				break
			except (OSError, ssl.SSLError, ValueError) as e:
				self.lastError = e
				self.failedAttempts += 1
				log.info("No se pudo conectar con %s: %s", self.addressKey, e)
				if self._stop.is_set():
					break
				self._safe(self.onConnectionFailed, e)
				if not self.reconnect:
					break
				self._stop.wait(self.reconnectDelay)
				continue
			if self._stop.is_set():
				try:
					sock.close()
				except OSError:
					pass
				break
			conn = LineConnection(sock, self._onLine, name=self.name)
			self._conn = conn
			self.connected = True
			self.successfulConnects += 1
			self.failedAttempts = 0
			self.connectedEvent.set()
			conn.start()
			# Saludo: versión del protocolo y unión al canal (o petición de clave).
			self.send(MessageType.PROTOCOL_VERSION, version=self.protocolVersion)
			if self.channel is not None:
				self.send(MessageType.JOIN, channel=self.channel, connection_type=self.connectionType)
			else:
				self.send(MessageType.GENERATE_KEY)
			self._safe(self.onConnected)
			while not conn.wait(0.5):
				if self._stop.is_set():
					conn.close()
			conn.wait(5)
			self.connected = False
			self.connectedEvent.clear()
			self._conn = None
			self._safe(self.onDisconnected)
			if self._stop.is_set() or not self.reconnect:
				break
			self._stop.wait(self.reconnectDelay)
		self.connected = False
		log.debug("Fin del conector %s", self.name)

	@staticmethod
	def _safe(func: Callable, *args: Any) -> None:
		try:
			func(*args)
		except Exception:
			log.exception("Error en una retrollamada del acceso remoto")

	def _onLine(self, line: bytes) -> None:
		try:
			obj = serializer.deserialize(line)
		except ValueError:
			log.warning("Mensaje remoto no válido: %r", line[:200])
			return
		if obj.get("type") == MessageType.PING.value:
			return
		self.onMessage(obj)

	# ------------------------------------------------------------------ sockets
	def _rawSocket(self) -> socket.socket:
		sock = socket.create_connection(self.address, timeout=self.timeout)
		try:
			sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
		except OSError:
			pass
		try:
			# Detecta conexiones muertas: sondeo tras 60 s de silencio, cada 2 s.
			sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 60000, 2000))  # type: ignore[attr-defined]
		except (AttributeError, OSError, ValueError):
			try:
				sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
			except OSError:
				pass
		return sock

	@staticmethod
	def _context(verify: bool) -> ssl.SSLContext:
		if verify:
			ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
		else:
			ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
			ctx.check_hostname = False
			ctx.verify_mode = ssl.CERT_NONE
		ctx.minimum_version = ssl.TLSVersion.TLSv1_2
		return ctx

	def _wrap(self, verify: bool) -> ssl.SSLSocket:
		raw = self._rawSocket()
		try:
			return self._context(verify).wrap_socket(raw, server_hostname=self.hostname)
		except BaseException:
			try:
				raw.close()
			except OSError:
				pass
			raise

	def fetchFingerprint(self) -> str | None:
		"""Huella del certificado que presenta el servidor (sin validarlo)."""
		sock = self._wrap(verify=False)
		try:
			der = sock.getpeercert(True)
			return fingerprintOf(der) if der else None
		finally:
			try:
				sock.close()
			except OSError:
				pass

	def _open(self) -> ssl.SSLSocket:
		if not self.insecure:
			try:
				return self._wrap(verify=True)
			except ssl.SSLCertVerificationError:
				fp = None
				try:
					fp = self.fetchFingerprint()
				except (OSError, ssl.SSLError):
					log.debug("No se pudo leer la huella de %s", self.addressKey, exc_info=True)
				if fp and (fp == self.trustedFingerprint or self._isTrusted(self.addressKey, fp)):
					self.trustedFingerprint = fp
					self.insecure = True
				else:
					raise CertificateRejected(fp) from None
		sock = self._wrap(verify=False)
		if self.trustedFingerprint:
			der = sock.getpeercert(True)
			fp = fingerprintOf(der) if der else None
			if fp != self.trustedFingerprint:
				try:
					sock.close()
				except OSError:
					pass
				raise CertificateRejected(fp)
		return sock
