# -*- coding: utf-8 -*-
# Copyright (C) 2025-2026 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General GNU.

"""Cliente HTTP mínimo con la biblioteca estándar (sustituye a httpx/requests).

- HTTPS con ``ssl.create_default_context()``, que en Windows carga los
  certificados raíz del sistema (también en la versión compilada de
  Tiresias); se vuelve a llamar a ``load_default_certs`` por si acaso.
- Respuestas comprimidas con gzip.
- Caché opcional de respuestas en SQLite (sustituye a ``requests_cache``).
"""

from __future__ import annotations

import gzip
import json
import sqlite3
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from typing import Any

from tiresias.log import getLogger

log = getLogger("zRadioBASS.http")

USER_AGENT = "zRadioBASS/1.0 (Tiresias)"

_sslContext: ssl.SSLContext | None = None
_sslLock = threading.Lock()


def sslContext() -> ssl.SSLContext:
	"""Contexto TLS que verifica certificado y nombre del servidor."""
	global _sslContext
	with _sslLock:
		if _sslContext is None:
			ctx = ssl.create_default_context()
			try:
				# En Windows lee los almacenes «ROOT» y «CA» del sistema.
				ctx.load_default_certs()
			except Exception:
				log.debug("load_default_certs falló", exc_info=True)
			try:
				ctx.minimum_version = ssl.TLSVersion.TLSv1_2
			except (AttributeError, ValueError):
				pass
			_sslContext = ctx
		return _sslContext


class HttpError(Exception):
	"""Error de una petición HTTP (``status`` es 0 si no hubo respuesta)."""

	def __init__(self, message: str, status: int = 0) -> None:
		super().__init__(message)
		self.status = status

	@property
	def retryable(self) -> bool:
		"""Errores de conexión y del servidor (5xx): se puede probar con otro servidor."""
		return self.status == 0 or 500 <= self.status < 600


def buildUrl(base: str, params: dict[str, Any] | None = None) -> str:
	if not params:
		return base
	clean = {k: v for k, v in params.items() if v is not None}
	return base + ("&" if "?" in base else "?") + urllib.parse.urlencode(clean, doseq=True)


def _decode(body: bytes, encoding: str) -> bytes:
	encoding = (encoding or "").lower()
	if encoding == "gzip":
		return gzip.decompress(body)
	if encoding == "deflate":
		try:
			return zlib.decompress(body)
		except zlib.error:
			return zlib.decompress(body, -zlib.MAX_WBITS)
	return body


def get(url: str, timeout: float = 10.0, headers: dict[str, str] | None = None) -> bytes:
	"""Descarga ``url`` y devuelve el cuerpo (lanza :class:`HttpError`)."""
	h = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate", "Accept": "application/json"}
	if headers:
		h.update(headers)
	req = urllib.request.Request(url, headers=h, method="GET")
	try:
		ctx = sslContext() if url.lower().startswith("https:") else None
		with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
			body = resp.read()
			return _decode(body, resp.headers.get("Content-Encoding", ""))
	except urllib.error.HTTPError as e:
		raise HttpError(f"El servidor respondió {e.code} {e.reason}", e.code) from e
	except urllib.error.URLError as e:
		raise HttpError(f"No se pudo conectar: {e.reason}") from e
	except (OSError, ssl.SSLError, EOFError, zlib.error) as e:
		raise HttpError(f"Error de red: {e}") from e


def getJson(url: str, timeout: float = 10.0) -> Any:
	body = get(url, timeout=timeout)
	try:
		return json.loads(body.decode("utf-8"))
	except (UnicodeDecodeError, ValueError) as e:
		raise HttpError(f"Respuesta no válida del servidor: {e}", 200) from e


class ResponseCache:
	"""Caché de respuestas JSON en SQLite con caducidad en días."""

	def __init__(self, path: str) -> None:
		self.path = path
		self._lock = threading.Lock()
		self._conn: sqlite3.Connection | None = None

	def _db(self) -> sqlite3.Connection:
		if self._conn is None:
			self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
			self._conn.execute("CREATE TABLE IF NOT EXISTS responses (url TEXT PRIMARY KEY, body TEXT NOT NULL, stored REAL NOT NULL)")
			self._conn.commit()
		return self._conn

	def get(self, url: str, maxAgeDays: float) -> Any | None:
		with self._lock:
			try:
				row = self._db().execute("SELECT body, stored FROM responses WHERE url = ?", (url,)).fetchone()
			except sqlite3.Error:
				log.debug("Error leyendo la caché", exc_info=True)
				return None
		if not row:
			return None
		if time.time() - float(row[1]) > maxAgeDays * 86400:
			return None
		try:
			return json.loads(row[0])
		except ValueError:
			return None

	def put(self, url: str, data: Any) -> None:
		with self._lock:
			try:
				self._db().execute("INSERT OR REPLACE INTO responses (url, body, stored) VALUES (?, ?, ?)", (url, json.dumps(data, ensure_ascii=False), time.time()))
				self._db().commit()
			except sqlite3.Error:
				log.debug("Error escribiendo la caché", exc_info=True)

	def clear(self) -> int:
		with self._lock:
			try:
				cur = self._db().execute("DELETE FROM responses")
				self._db().commit()
				self._db().execute("VACUUM")
				return cur.rowcount
			except sqlite3.Error:
				log.debug("Error vaciando la caché", exc_info=True)
				return 0

	def purge(self, maxAgeDays: float) -> int:
		"""Borra las respuestas caducadas."""
		with self._lock:
			try:
				cur = self._db().execute("DELETE FROM responses WHERE stored < ?", (time.time() - maxAgeDays * 86400,))
				self._db().commit()
				return cur.rowcount
			except sqlite3.Error:
				return 0

	def count(self) -> int:
		with self._lock:
			try:
				return int(self._db().execute("SELECT COUNT(*) FROM responses").fetchone()[0])
			except sqlite3.Error:
				return 0

	def close(self) -> None:
		with self._lock:
			if self._conn is not None:
				try:
					self._conn.close()
				except Exception:
					pass
				self._conn = None
