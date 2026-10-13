# -*- coding: utf-8 -*-
# Copyright (C) 2025-2026 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General GNU.

"""Cliente de la API de Radio Browser (radio-browser.info) con ``urllib``.

Sustituye a ``pyradios``/``httpx`` del original:

- Elección de servidor: resolución DNS de ``all.api.radio-browser.info`` y
  búsqueda inversa de los nombres (el método que recomienda Radio Browser);
  si falla, la lista ``/json/servers``; y si también falla, una lista fija.
  Se elige uno al azar y, ante errores de conexión o 5xx, se prueba el
  siguiente (hasta tres reintentos).
- Caché de respuestas en SQLite (opción «Usar caché», con caducidad en días).

Ningún método se llama en el hilo de la interfaz ni en el del núcleo: la
interfaz los ejecuta en hilos propios.
"""

from __future__ import annotations

import random
import socket
import threading
import urllib.parse
from typing import Any, Callable

from tiresias.log import getLogger

from . import net
from .localization import get_country_name, get_language_name
from .models import Country, Language, SearchFilters, Station, Tag

log = getLogger("zRadioBASS.api")

#: Servidores conocidos (último recurso si fallan el DNS y ``/json/servers``).
FALLBACK_SERVERS = ["de1.api.radio-browser.info", "de2.api.radio-browser.info", "fi1.api.radio-browser.info", "nl1.api.radio-browser.info", "at1.api.radio-browser.info"]
DISCOVERY_HOST = "all.api.radio-browser.info"
#: Puntos de la API que no se guardan en esta caché: votos, clics y
#: estadísticas (cambian siempre) y las listas de países, idiomas y etiquetas
#: (van a las tablas de caché de la base de datos, como en el original).
_NO_CACHE_PREFIXES = ("vote/", "url/", "stats", "servers", "countries", "languages", "tags")


def discover_servers(timeout: float = 5.0) -> list[str]:
	"""Nombres de los servidores de la API disponibles."""
	hosts: list[str] = []
	old = socket.getdefaulttimeout()
	try:
		socket.setdefaulttimeout(timeout)
		infos = socket.getaddrinfo(DISCOVERY_HOST, 443, 0, socket.SOCK_STREAM)
		for info in infos:
			ip = info[4][0]
			try:
				name = socket.gethostbyaddr(ip)[0].lower().rstrip(".")
			except (OSError, socket.herror, socket.gaierror):
				continue
			if name.endswith(".api.radio-browser.info") and name not in hosts:
				hosts.append(name)
	except OSError as e:
		log.debug("No se pudieron descubrir servidores por DNS: %s", e)
	finally:
		socket.setdefaulttimeout(old)
	if not hosts:
		try:
			data = net.getJson(f"https://{DISCOVERY_HOST}/json/servers", timeout=timeout)
			for item in data or []:
				name = str(item.get("name", "")).lower()
				if name.endswith(".api.radio-browser.info") and name not in hosts:
					hosts.append(name)
		except net.HttpError as e:
			log.debug("No se pudo obtener /json/servers: %s", e)
	if not hosts:
		hosts = list(FALLBACK_SERVERS)
	return hosts


class RadioBrowserAPI:
	"""Acceso a la API de Radio Browser."""

	TIMEOUT = 15
	MAX_RETRIES = 3

	def __init__(
		self,
		base_url: str | None = None,
		cache: net.ResponseCache | None = None,
		cacheSettings: Callable[[], tuple[bool, int]] | None = None,
	) -> None:
		"""
		``base_url``: servidor fijo (``https://de1.api.radio-browser.info``); sin él se elige solo.
		``cache``: caché de respuestas; ``cacheSettings`` devuelve ``(activada, días)``.
		"""
		self._lock = threading.RLock()
		self._fixed = bool(base_url)
		self._available_servers: list[str] = [base_url.rstrip("/")] if base_url else []
		self._base_url: str | None = base_url.rstrip("/") if base_url else None
		self._cache = cache
		self._cacheSettings = cacheSettings or (lambda: (cache is not None, 3))
		#: Número de peticiones hechas a la red (las de la caché no cuentan).
		self.requests = 0

	# ------------------------------------------------------------- servidores
	@property
	def base_url(self) -> str:
		with self._lock:
			if self._base_url is None:
				self._available_servers = ["https://" + h for h in discover_servers()]
				self._base_url = random.choice(self._available_servers)
				log.info("Servidor de Radio Browser elegido: %s", self._base_url)
			return self._base_url

	@property
	def servers(self) -> list[str]:
		_ = self.base_url
		return list(self._available_servers)

	def _rotate_server(self) -> str:
		with self._lock:
			if self._fixed:
				return self._base_url or ""
			if len(self._available_servers) <= 1:
				self._available_servers = ["https://" + h for h in discover_servers()]
			if self._base_url in self._available_servers and len(self._available_servers) > 1:
				i = self._available_servers.index(self._base_url)
				self._base_url = self._available_servers[(i + 1) % len(self._available_servers)]
			else:
				self._base_url = random.choice(self._available_servers)
			log.info("Se cambia al servidor de Radio Browser %s", self._base_url)
			return self._base_url

	# ------------------------------------------------------------- peticiones
	@staticmethod
	def _cacheKey(endpoint: str, params: dict | None) -> str:
		if not params:
			return endpoint
		return endpoint + "?" + urllib.parse.urlencode(sorted((k, str(v)) for k, v in params.items()))

	def _get(self, endpoint: str, params: dict | None = None, useCache: bool = True) -> Any:
		cacheable = useCache and self._cache is not None and not endpoint.startswith(_NO_CACHE_PREFIXES)
		enabled, days = self._cacheSettings()
		key = self._cacheKey(endpoint, params)
		if cacheable and enabled:
			cached = self._cache.get(key, days)
			if cached is not None:
				return cached
		lastError: Exception | None = None
		for attempt in range(self.MAX_RETRIES + 1):
			url = net.buildUrl(f"{self.base_url}/json/{endpoint}", params)
			try:
				self.requests += 1
				data = net.getJson(url, timeout=self.TIMEOUT)
				if cacheable and enabled:
					self._cache.put(key, data)
				return data
			except net.HttpError as e:
				lastError = e
				if not e.retryable or attempt >= self.MAX_RETRIES:
					break
				log.warning("Error en %s (%s); se prueba otro servidor", self._base_url, e)
				self._rotate_server()
		log.error("Error definitivo en la petición %s: %s", endpoint, lastError)
		raise lastError if lastError else net.HttpError("Error desconocido")

	@staticmethod
	def _stations(data: Any) -> list[Station]:
		return [Station.from_api_response(item) for item in (data or []) if isinstance(item, dict)]

	# ------------------------------------------------------------- emisoras
	def get_stations_by_uuid(self, station_uuid: str) -> list[Station]:
		if not station_uuid:
			return []
		try:
			return self._stations(self._get(f"stations/byuuid/{urllib.parse.quote(station_uuid)}"))
		except net.HttpError as e:
			log.error("Error obteniendo la emisora %s: %s", station_uuid, e)
			return []

	def search_stations(self, filters: SearchFilters | None = None, raise_errors: bool = False, **kwargs: Any) -> list[Station]:
		"""Busca emisoras con ``filters`` o con argumentos sueltos (``name``, ``country``...)."""
		if filters is not None:
			params = filters.to_api_params()
		else:
			params = {
				"limit": kwargs.get("limit", 100),
				"offset": kwargs.get("offset", 0),
				"order": kwargs.get("order", "name"),
				"reverse": str(kwargs.get("reverse", False)).lower(),
			}
			if kwargs.get("name"):
				params["name"] = kwargs["name"]
				params["nameExact"] = str(kwargs.get("name_exact", False)).lower()
			for key in ("country", "countrycode", "language", "tag", "codec"):
				if kwargs.get(key):
					params[key] = kwargs[key]
			if kwargs.get("hidebroken"):
				params["hidebroken"] = "true"
		try:
			return self._stations(self._get("stations/search", params))
		except net.HttpError as e:
			log.error("Error buscando emisoras: %s", e)
			if raise_errors:
				raise
			return []

	def search_by_name(self, name: str, exact: bool = False, limit: int = 100) -> list[Station]:
		return self.search_stations(name=name, name_exact=exact, limit=limit)

	def _byExact(self, kind: str, value: str, limit: int, raise_errors: bool, hidebroken: bool = False) -> list[Station]:
		params: dict[str, Any] = {"limit": limit}
		if hidebroken:
			params["hidebroken"] = "true"
		try:
			return self._stations(self._get(f"stations/{kind}/{urllib.parse.quote(value, safe='')}", params))
		except net.HttpError as e:
			log.error("Error obteniendo emisoras (%s %s): %s", kind, value, e)
			if raise_errors:
				raise
			return []

	def get_stations_by_country(self, countrycode: str, limit: int = 500, raise_errors: bool = False, hidebroken: bool = False) -> list[Station]:
		return self._byExact("bycountrycodeexact", countrycode.upper(), limit, raise_errors, hidebroken)

	def get_stations_by_language(self, language: str, limit: int = 500, raise_errors: bool = False, hidebroken: bool = False) -> list[Station]:
		return self._byExact("bylanguageexact", language, limit, raise_errors, hidebroken)

	def get_stations_by_tag(self, tag: str, limit: int = 500, raise_errors: bool = False, hidebroken: bool = False) -> list[Station]:
		return self._byExact("bytagexact", tag, limit, raise_errors, hidebroken)

	def get_top_stations(self, limit: int = 100, raise_errors: bool = False, hidebroken: bool = False) -> list[Station]:
		params: dict[str, Any] = {"limit": limit}
		if hidebroken:
			params["hidebroken"] = "true"
		try:
			return self._stations(self._get("stations/topvote", params))
		except net.HttpError as e:
			log.error("Error obteniendo las emisoras más votadas: %s", e)
			if raise_errors:
				raise
			return []

	def get_top_clicked(self, limit: int = 100) -> list[Station]:
		try:
			return self._stations(self._get("stations/topclick", {"limit": limit}))
		except net.HttpError as e:
			log.error("Error obteniendo las emisoras más escuchadas: %s", e)
			return []

	def get_recent_stations(self, limit: int = 100) -> list[Station]:
		try:
			return self._stations(self._get("stations/lastchange", {"limit": limit}))
		except net.HttpError as e:
			log.error("Error obteniendo las emisoras recientes: %s", e)
			return []

	# ------------------------------------------------------------- países, idiomas, etiquetas
	def get_countries(self) -> list[Country]:
		try:
			data = self._get("countries")
		except net.HttpError as e:
			log.error("Error obteniendo los países: %s", e)
			return []
		out = []
		for item in data or []:
			name = item.get("name", "")
			code = item.get("iso_3166_1", "") or ""
			if not name:
				continue
			out.append(Country(name=name, code=code, station_count=int(item.get("stationcount", 0) or 0), name_localized=get_country_name(code) if code else ""))
		return out

	def get_countries_with_localization(self, localization_dict: dict[str, str]) -> list[Country]:
		"""Países con el nombre localizado según ``{nombre_local: código}``."""
		countries = self.get_countries()
		code_to_local = {v.upper(): k for k, v in localization_dict.items()}
		for c in countries:
			if c.code.upper() in code_to_local:
				c.name_localized = code_to_local[c.code.upper()]
		return countries

	def get_languages(self) -> list[Language]:
		try:
			data = self._get("languages", {"order": "stationcount", "reverse": "true"})
		except net.HttpError as e:
			log.error("Error obteniendo los idiomas: %s", e)
			return []
		return [
			Language(name=item.get("name", ""), station_count=int(item.get("stationcount", 0) or 0), name_localized=get_language_name(item.get("name", "")))
			for item in data or []
			if item.get("name")
		]

	def search_languages(self, query: str) -> list[Language]:
		q = query.lower()
		return [lang for lang in self.get_languages() if q in lang.name.lower() or q in lang.name_localized.lower()]

	def get_tags(self, limit: int = 500) -> list[Tag]:
		try:
			data = self._get("tags", {"order": "stationcount", "reverse": "true", "limit": limit})
		except net.HttpError as e:
			log.error("Error obteniendo las etiquetas: %s", e)
			return []
		return [Tag(name=item.get("name", ""), station_count=int(item.get("stationcount", 0) or 0)) for item in data or [] if item.get("name")]

	def search_tags(self, query: str) -> list[Tag]:
		q = query.lower()
		return [t for t in self.get_tags() if q in t.name.lower()]

	def get_codecs(self) -> list[tuple[str, int]]:
		try:
			data = self._get("codecs", {"order": "stationcount", "reverse": "true"})
		except net.HttpError as e:
			log.error("Error obteniendo los códecs: %s", e)
			return []
		return [(str(i.get("name", "")), int(i.get("stationcount", 0) or 0)) for i in data or [] if i.get("name")]

	# ------------------------------------------------------------- estadísticas, votos y clics
	def get_stats(self) -> dict[str, Any]:
		try:
			data = self._get("stats", useCache=False)
			return data if isinstance(data, dict) else {}
		except net.HttpError as e:
			log.error("Error obteniendo las estadísticas: %s", e)
			return {}

	def vote_for_station(self, station_uuid: str) -> tuple[bool, str]:
		"""Vota por una emisora. Devuelve ``(correcto, mensaje del servidor)``."""
		if not station_uuid:
			return False, ""
		try:
			data = self._get(f"vote/{urllib.parse.quote(station_uuid)}", useCache=False)
		except net.HttpError as e:
			log.error("Error votando: %s", e)
			return False, str(e)
		if isinstance(data, dict):
			return bool(data.get("ok", False)), str(data.get("message", ""))
		return False, ""

	def click_station(self, station_uuid: str) -> bool:
		"""Cuenta una reproducción de la emisora (lo pide Radio Browser a sus clientes)."""
		if not station_uuid:
			return False
		try:
			data = self._get(f"url/{urllib.parse.quote(station_uuid)}", useCache=False)
			return bool(isinstance(data, dict) and data.get("ok", False))
		except net.HttpError as e:
			log.debug("No se pudo registrar el clic: %s", e)
			return False

	# ------------------------------------------------------------- caché
	def clear_cache(self) -> int:
		return self._cache.clear() if self._cache is not None else 0

	def close(self) -> None:
		if self._cache is not None:
			self._cache.close()
