# -*- coding: utf-8 -*-
# Copyright (C) 2025-2026 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General GNU.

"""Modelos de datos de zRadio BASS (emisoras, favoritos, categorías...)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class StationCodec(Enum):
	"""Códecs de audio habituales."""

	MP3 = "mp3"
	AAC = "aac"
	OGG = "ogg"
	FLAC = "flac"
	WMA = "wma"
	OPUS = "opus"
	UNKNOWN = "unknown"


def _int(value: Any, default: int = 0) -> int:
	try:
		return int(value)
	except (TypeError, ValueError):
		return default


def _float(value: Any) -> float:
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def _str(value: Any) -> str:
	return "" if value is None else str(value)


@dataclass
class Station:
	"""Una emisora de radio (campos de la API de Radio Browser)."""

	name: str
	url: str
	stationuuid: str = ""
	url_resolved: str = ""
	country: str = ""
	countrycode: str = ""
	state: str = ""
	language: str = ""
	languagecodes: str = ""
	tags: str = ""
	codec: str = ""
	bitrate: int = 0
	hls: int = 0
	votes: int = 0
	clickcount: int = 0
	clicktrend: int = 0
	ssl_error: int = 0
	geo_lat: float = 0.0
	geo_long: float = 0.0
	has_extended_info: bool = False
	favicon: str = ""
	homepage: str = ""
	lastchangetime: str = ""
	lastchecktime: str = ""
	lastcheckoktime: str = ""
	lastlocalchecktime: str = ""
	lastcheckok: int = 1

	@classmethod
	def from_api_response(cls, data: dict[str, Any]) -> "Station":
		"""Crea una emisora a partir de un elemento JSON de la API."""
		return cls(
			name=_str(data.get("name")).strip(),
			url=_str(data.get("url")).strip(),
			stationuuid=_str(data.get("stationuuid")),
			url_resolved=_str(data.get("url_resolved")).strip(),
			country=_str(data.get("country")),
			countrycode=_str(data.get("countrycode")),
			state=_str(data.get("state")),
			language=_str(data.get("language")),
			languagecodes=_str(data.get("languagecodes")),
			tags=_str(data.get("tags")),
			codec=_str(data.get("codec")),
			bitrate=_int(data.get("bitrate")),
			hls=_int(data.get("hls")),
			votes=_int(data.get("votes")),
			clickcount=_int(data.get("clickcount")),
			clicktrend=_int(data.get("clicktrend")),
			ssl_error=_int(data.get("ssl_error")),
			geo_lat=_float(data.get("geo_lat")),
			geo_long=_float(data.get("geo_long")),
			has_extended_info=bool(data.get("has_extended_info", False)),
			favicon=_str(data.get("favicon")),
			homepage=_str(data.get("homepage")),
			lastchangetime=_str(data.get("lastchangetime")),
			lastchecktime=_str(data.get("lastchecktime")),
			lastcheckoktime=_str(data.get("lastcheckoktime")),
			lastlocalchecktime=_str(data.get("lastlocalchecktime")),
			lastcheckok=_int(data.get("lastcheckok"), 1),
		)

	@property
	def play_url(self) -> str:
		"""Dirección para reproducir (la resuelta por la API si la hay)."""
		return self.url_resolved or self.url

	def to_dict(self) -> dict[str, Any]:
		return asdict(self)

	def get_display_name(self) -> str:
		"""Nombre con país y calidad: «Radio X (España) [128 kbps]»."""
		parts = [self.name]
		if self.country:
			parts.append(f"({self.country})")
		if self.bitrate > 0:
			parts.append(f"[{self.bitrate} kbps]")
		return " ".join(parts)


@dataclass
class Category:
	"""Categoría de favoritos."""

	id: int | None = None
	name: str = ""
	description: str = ""
	color: str = "#0078D4"
	order: int = 0
	created_at: datetime | None = None

	def __post_init__(self) -> None:
		if self.created_at is None:
			self.created_at = datetime.now()


@dataclass
class Favorite:
	"""Emisora favorita."""

	id: int | None = None
	name: str = ""
	url: str = ""
	station_uuid: str | None = None
	category_id: int | None = None
	order: int = 0
	play_count: int = 0
	last_played: datetime | None = None
	notes: str = ""
	created_at: datetime | None = None

	def __post_init__(self) -> None:
		if self.created_at is None:
			self.created_at = datetime.now()

	def to_station(self) -> Station:
		return Station(name=self.name, url=self.url, stationuuid=self.station_uuid or "")

	@classmethod
	def from_station(cls, station: Station, category_id: int | None = None) -> "Favorite":
		return cls(name=station.name, url=station.url, station_uuid=station.stationuuid, category_id=category_id)


@dataclass
class PlaybackHistory:
	"""Entrada del historial de reproducción."""

	id: int | None = None
	station_name: str = ""
	station_url: str = ""
	station_uuid: str = ""
	played_at: datetime | None = None
	duration_seconds: int = 0

	def __post_init__(self) -> None:
		if self.played_at is None:
			self.played_at = datetime.now()

	@classmethod
	def from_station(cls, station: Station) -> "PlaybackHistory":
		return cls(station_name=station.name, station_url=station.url, station_uuid=station.stationuuid)

	def to_station(self) -> Station:
		return Station(name=self.station_name, url=self.station_url, stationuuid=self.station_uuid or "")


@dataclass
class ScheduledRecording:
	"""Grabación programada (se guarda en la base de datos)."""

	id: int | None = None
	station_name: str = ""
	station_url: str = ""
	start_time: datetime = field(default_factory=datetime.now)
	end_time: datetime = field(default_factory=datetime.now)
	output_path: str = ""
	#: ``pending``, ``recording``, ``done``, ``cancelled``, ``missed`` o ``failed``.
	status: str = "pending"
	error: str = ""

	@property
	def active(self) -> bool:
		return self.status in ("pending", "recording")


@dataclass
class Country:
	"""País con emisoras."""

	name: str
	code: str
	station_count: int = 0
	name_localized: str = ""

	def get_display_name(self) -> str:
		display = self.name_localized or self.name
		return f"{display} ({self.station_count} emisoras)"


@dataclass
class Language:
	"""Idioma con emisoras."""

	name: str
	station_count: int = 0
	name_localized: str = ""

	def get_display_name(self) -> str:
		display = self.name_localized or self.name
		return f"{display} ({self.station_count} emisoras)"


@dataclass
class Tag:
	"""Etiqueta o género musical."""

	name: str
	station_count: int = 0

	def get_display_name(self) -> str:
		return f"{self.name} ({self.station_count} emisoras)"


#: Campos de ordenación de la API → nombre en español.
ORDER_FIELDS = [
	("name", "Nombre"),
	("votes", "Votos"),
	("clickcount", "Popularidad (reproducciones)"),
	("clicktrend", "Tendencia"),
	("bitrate", "Calidad (kbps)"),
	("country", "País"),
	("language", "Idioma"),
	("lastchangetime", "Última modificación"),
	("random", "Al azar"),
]


@dataclass
class SearchFilters:
	"""Filtros de búsqueda de emisoras (``/json/stations/search``)."""

	name: str = ""
	country: str = ""
	language: str = ""
	tag: str = ""
	codec: str = ""
	min_bitrate: int = 0
	order: str = "name"
	reverse: bool = False
	limit: int = 100
	offset: int = 0
	hide_broken: bool = False
	name_exact: bool = False
	language_exact: bool = True
	tag_exact: bool = True

	def to_api_params(self) -> dict[str, Any]:
		params: dict[str, Any] = {}
		if self.name:
			params["name"] = self.name
			if self.name_exact:
				params["nameExact"] = "true"
		if self.country:
			params["countrycode"] = self.country
		if self.language:
			params["language"] = self.language
			if self.language_exact:
				params["languageExact"] = "true"
		if self.tag:
			params["tag"] = self.tag
			if self.tag_exact:
				params["tagExact"] = "true"
		if self.codec:
			params["codec"] = self.codec
		if self.min_bitrate > 0:
			params["bitrateMin"] = self.min_bitrate
		if self.hide_broken:
			params["hidebroken"] = "true"
		params["order"] = self.order
		params["reverse"] = str(bool(self.reverse)).lower()
		params["limit"] = self.limit
		params["offset"] = self.offset
		return params
