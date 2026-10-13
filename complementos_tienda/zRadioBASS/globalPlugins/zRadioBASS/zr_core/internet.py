# -*- coding: utf-8 -*-
# Copyright (C) 2025-2026 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General GNU.

"""Comprobación de la conexión a Internet y de la accesibilidad de una emisora.

Las comprobaciones abren una conexión TCP (hasta 3 segundos): nunca se
llaman desde el hilo de la interfaz ni desde el del núcleo.
"""

from __future__ import annotations

import socket
import threading
from urllib.parse import urlparse

from tiresias.log import getLogger

log = getLogger("zRadioBASS.internet")


class InternetChecker:
	"""Comprueba si hay Internet y si se puede conectar con una dirección."""

	TEST_HOSTS = [("8.8.8.8", 53), ("1.1.1.1", 53), ("208.67.222.222", 53)]
	TIMEOUT = 3

	def __init__(self) -> None:
		self._cached_status: bool | None = None
		self._lock = threading.Lock()

	@staticmethod
	def _connect(host: str, port: int, timeout: float) -> bool:
		try:
			with socket.create_connection((host, port), timeout=timeout):
				return True
		except OSError:
			return False

	def is_connected(self, force_check: bool = False) -> bool:
		"""``True`` si hay conexión a Internet (el resultado se recuerda)."""
		if not force_check and self._cached_status is not None:
			return self._cached_status
		with self._lock:
			for host, port in self.TEST_HOSTS:
				if self._connect(host, port, self.TIMEOUT):
					self._cached_status = True
					return True
			self._cached_status = False
			log.warning("No hay conexión a Internet")
			return False

	def check_url(self, url: str, timeout: float | None = None) -> bool:
		"""``True`` si se puede abrir una conexión con el servidor de ``url``."""
		if not url:
			return False
		try:
			parsed = urlparse(url)
			host = parsed.hostname
			port = parsed.port or (443 if parsed.scheme == "https" else 80)
		except ValueError:
			return False
		if not host:
			return False
		ok = self._connect(host, port, timeout or self.TIMEOUT)
		if not ok:
			log.debug("Dirección no accesible: %s", url)
		return ok

	def test_internet(self, url: str | None = None) -> bool:
		return self.check_url(url) if url else self.is_connected()

	@staticmethod
	def resolve_host(hostname: str) -> str | None:
		try:
			return socket.gethostbyname(hostname)
		except OSError:
			return None

	def clear_cache(self) -> None:
		with self._lock:
			self._cached_status = None

	def check_radio_browser_api(self) -> bool:
		return self.check_url("https://all.api.radio-browser.info")
