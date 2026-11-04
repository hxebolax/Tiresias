"""Conexión TLS con mensajes por líneas.

Un único hilo hace toda la entrada y salida de cada socket TLS (OpenSSL no
admite leer y escribir a la vez desde hilos distintos). Los demás hilos
solo encolan bytes con :meth:`LineConnection.send` y despiertan al hilo de
E/S con un par de sockets, así que enviar nunca bloquea a quien llama (por
ejemplo, al gancho de teclado o al hilo del núcleo).
"""

from __future__ import annotations

import collections
import select
import socket
import ssl
import threading
from typing import Callable, Union

from ..log import getLogger

log = getLogger("remote")

#: Tamaño máximo predeterminado de una línea, terminada o no (protege la memoria).
MAX_LINE = 32 * 1024 * 1024
#: Segundos que puede tardar en salir un mensaje antes de dar la conexión por perdida.
WRITE_TIMEOUT = 20.0

#: Límite de tamaño de línea: un número de bytes o una función que lo devuelve
#: (se consulta en cada línea, así puede cambiar, p. ej., al autenticarse).
MaxLine = Union[int, Callable[[], int]]


class LineConnection:
	def __init__(
		self,
		sock: ssl.SSLSocket,
		onLine: Callable[[bytes], None],
		onClose: Callable[[], None] | None = None,
		name: str = "remoto",
		maxLine: MaxLine = MAX_LINE,
	) -> None:
		self.sock = sock
		self._maxLine = maxLine
		self._onLine = onLine
		self._onClose = onClose
		self._name = name
		self._out: collections.deque[bytes] = collections.deque()
		self._outLock = threading.Lock()
		self._wakeR, self._wakeW = socket.socketpair()
		self._wakeR.setblocking(False)
		self._wakeW.setblocking(False)
		self._closing = False
		self.closed = threading.Event()
		self._buffer = bytearray()
		self._thread: threading.Thread | None = None

	def start(self) -> None:
		self._thread = threading.Thread(target=self._run, name=f"E/S {self._name}", daemon=True)
		self._thread.start()

	@property
	def isOpen(self) -> bool:
		return not self._closing and not self.closed.is_set()

	def send(self, data: bytes) -> bool:
		"""Encola ``data`` para enviarlo (no bloquea). ``False`` si está cerrada."""
		if not self.isOpen:
			return False
		with self._outLock:
			self._out.append(data)
		self._wake()
		return True

	def close(self) -> None:
		"""Cierra la conexión (se puede llamar desde cualquier hilo)."""
		self._closing = True
		self._wake()

	def lineLimit(self) -> int:
		"""Tamaño máximo actual (en bytes) de una línea."""
		limit = self._maxLine
		try:
			return int(limit() if callable(limit) else limit)
		except Exception:
			log.exception("No se pudo obtener el límite de línea de %s", self._name)
			return MAX_LINE

	def wait(self, timeout: float | None = None) -> bool:
		return self.closed.wait(timeout)

	def _wake(self) -> None:
		try:
			self._wakeW.send(b"\0")
		except (BlockingIOError, OSError):
			pass

	# ------------------------------------------------------------------ hilo de E/S
	def _run(self) -> None:
		try:
			while not self._closing:
				self._flush()
				if self._closing:
					break
				try:
					readable, _w, errored = select.select([self.sock, self._wakeR], [], [self.sock], 30)
				except (OSError, ValueError):
					break
				if self._wakeR in readable:
					try:
						while self._wakeR.recv(4096):
							pass
					except (BlockingIOError, OSError):
						pass
				if self.sock in errored:
					break
				if self.sock in readable and not self._read():
					break
			if self._closing:
				# Intenta vaciar lo pendiente antes de cerrar (p. ej. un último mensaje).
				try:
					self._flush()
				except Exception:
					pass
		except (OSError, ssl.SSLError) as e:
			log.debug("Conexión %s cerrada: %s", self._name, e)
		except Exception:
			log.exception("Error en la conexión %s", self._name)
		finally:
			self._shutdown()

	def _flush(self) -> None:
		while True:
			with self._outLock:
				if not self._out:
					return
				data = self._out.popleft()
			self.sock.settimeout(WRITE_TIMEOUT)
			self.sock.sendall(data)

	def _read(self) -> bool:
		"""Lee todo lo disponible. ``False`` si el otro extremo cerró."""
		self.sock.setblocking(False)
		try:
			while True:
				try:
					chunk = self.sock.recv(65536)
				except (ssl.SSLWantReadError, ssl.SSLWantWriteError, BlockingIOError):
					return True
				if not chunk:
					return False
				if not self._feed(chunk):
					return False
				if self._closing:
					return True
		finally:
			try:
				self.sock.settimeout(WRITE_TIMEOUT)
			except OSError:
				pass

	def _feed(self, chunk: bytes) -> bool:
		"""Añade ``chunk`` al búfer y entrega las líneas completas.

		Solo busca el salto de línea en lo recién llegado (no en todo el
		búfer, que sería cuadrático) y comprueba el tamaño de cada línea
		completa y de lo que queda sin terminar. ``False`` si alguna se pasa
		del límite: hay que cerrar la conexión.
		"""
		buf = self._buffer
		start = len(buf)
		buf += chunk
		consumed = 0
		pos = buf.find(b"\n", start)
		while pos != -1:
			line = bytes(buf[consumed:pos])
			consumed = pos + 1
			limit = self.lineLimit()
			if len(line) > limit:
				log.warning("Mensaje remoto de %d bytes (máximo %d): se cierra la conexión %s", len(line), limit, self._name)
				return False
			if line.strip():
				try:
					self._onLine(line)
				except Exception:
					log.exception("Error procesando un mensaje remoto")
			if self._closing:
				# Quien procesa la línea pidió cerrar: no se entrega nada más.
				del buf[:]
				return True
			pos = buf.find(b"\n", consumed)
		if consumed:
			del buf[:consumed]
		limit = self.lineLimit()
		if len(buf) > limit:
			log.warning("Mensaje remoto sin terminar de más de %d bytes: se cierra la conexión %s", limit, self._name)
			return False
		return True

	def _shutdown(self) -> None:
		self._closing = True
		for s in (self.sock, self._wakeR, self._wakeW):
			try:
				s.close()
			except OSError:
				pass
		with self._outLock:
			self._out.clear()
		self.closed.set()
		cb, self._onClose = self._onClose, None
		if cb is not None:
			try:
				cb()
			except Exception:
				log.exception("Error al cerrar la conexión %s", self._name)
