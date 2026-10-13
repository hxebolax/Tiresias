# -*- coding: utf-8 -*-
# Copyright (C) 2025-2026 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General GNU.

"""Plugin de estadísticas de uso de zRadio BASS.

- Cuenta el tiempo total de escucha y las emisoras reproducidas.
- Muestra las emisoras más escuchadas (del historial).
- Guarda los datos en ``statistics.json`` en la carpeta de datos del complemento.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from zradiobass import EventType, PluginBase, Station, format_duration, log


class StatisticsPlugin(PluginBase):
	"""Rastrea y muestra estadísticas de uso del reproductor."""

	PLUGIN_ID = "statistics_plugin"
	PLUGIN_NAME = "Estadísticas de uso"
	PLUGIN_VERSION = "1.0.0"
	PLUGIN_AUTHOR = "Héctor J. Benítez Corredera"
	PLUGIN_DESCRIPTION = "Rastrea y muestra estadísticas de uso del reproductor"

	def __init__(self, event_bus: Any, app: Any = None) -> None:
		super().__init__(event_bus, app)
		self._session_start: datetime | None = None
		self._current_station: Station | None = None
		self._total_time_seconds = 0
		self._stations_played = 0
		self._first_use = ""

	def on_load(self) -> bool:
		log.info("Cargando plugin: %s", self.PLUGIN_NAME)
		self.subscribe(EventType.PLAYBACK_STARTED, self._on_playback_started)
		self.subscribe(EventType.PLAYBACK_STOPPED, self._on_playback_stopped)
		self.subscribe(EventType.PLAYBACK_ERROR, self._on_playback_stopped)
		self.subscribe(EventType.PLAYBACK_PAUSED, self._on_playback_stopped)
		self.subscribe(EventType.PLAYBACK_RESUMED, self._on_playback_resumed)
		self._load_statistics()
		return True

	def on_unload(self) -> bool:
		if self._session_start:
			self._end_session()
		self._save_statistics()
		log.info("Plugin descargado: %s", self.PLUGIN_NAME)
		return True

	# ------------------------------------------------------------- eventos
	def _on_playback_started(self, station: Station | None) -> None:
		if self._session_start:
			self._end_session()
		self._session_start = datetime.now()
		self._current_station = station
		self._stations_played += 1
		self._save_statistics()

	def _on_playback_resumed(self, station: Station | None = None) -> None:
		if not self._session_start:
			self._session_start = datetime.now()

	def _on_playback_stopped(self, data: Any = None) -> None:
		self._end_session()
		self._save_statistics()

	def _end_session(self) -> None:
		if self._session_start:
			self._total_time_seconds += int((datetime.now() - self._session_start).total_seconds())
			self._session_start = None

	# ------------------------------------------------------------- datos
	def _stats_file(self) -> str:
		cfg = self._config
		base = str(cfg.data_dir) if cfg is not None else str(self.data_dir)
		return os.path.join(base, "statistics.json")

	def _load_statistics(self) -> None:
		path = self._stats_file()
		if not os.path.isfile(path):
			self._first_use = datetime.now().isoformat(timespec="seconds")
			return
		try:
			with open(path, encoding="utf-8") as f:
				data = json.load(f)
			self._total_time_seconds = int(data.get("total_time_seconds", 0))
			self._stations_played = int(data.get("stations_played", 0))
			self._first_use = str(data.get("first_use", "")) or datetime.now().isoformat(timespec="seconds")
		except (OSError, ValueError):
			log.warning("No se pudieron leer las estadísticas", exc_info=True)

	def _save_statistics(self) -> None:
		data = {
			"total_time_seconds": self._total_time_seconds,
			"stations_played": self._stations_played,
			"first_use": self._first_use,
			"last_updated": datetime.now().isoformat(timespec="seconds"),
		}
		try:
			with open(self._stats_file(), "w", encoding="utf-8") as f:
				json.dump(data, f, indent=2)
		except OSError:
			log.warning("No se pudieron guardar las estadísticas", exc_info=True)

	def total_seconds(self) -> int:
		"""Tiempo total de escucha, incluida la sesión en curso."""
		extra = int((datetime.now() - self._session_start).total_seconds()) if self._session_start else 0
		return self._total_time_seconds + extra

	@property
	def stations_played(self) -> int:
		return self._stations_played

	def build_report(self) -> str:
		total = self.total_seconds()
		hours, rem = divmod(total, 3600)
		minutes = rem // 60
		lines = [
			"Estadísticas de uso de zRadio:",
			"",
			f"Tiempo total de escucha: {hours} horas, {minutes} minutos",
			f"Emisoras reproducidas: {self._stations_played}",
		]
		if self._first_use:
			try:
				lines.append(f"Desde: {datetime.fromisoformat(self._first_use).strftime('%d/%m/%Y')}")
			except ValueError:
				pass
		db = getattr(self.app, "db", None)
		if db is not None:
			try:
				totals = db.history_totals()
				lines.append(f"Emisoras distintas en el historial: {totals['stations']}")
				top = db.get_most_played_stations(10)
				if top:
					lines.append("")
					lines.append("Emisoras más escuchadas:")
					for i, item in enumerate(top, 1):
						dur = format_duration(item.get("total_seconds", 0))
						lines.append(f"{i}. {item['name']}: {item['play_count']} veces, {dur}")
			except Exception:
				log.debug("No se pudo leer el historial", exc_info=True)
		return "\n".join(lines)

	# ------------------------------------------------------------- menú
	def get_menu_items(self) -> list[dict[str, Any]]:
		return [
			{"label": "Ver estadísticas de uso...", "callback": self._show_statistics},
			{"label": "Reiniciar estadísticas de uso", "callback": self._reset_statistics},
		]

	def _show_statistics(self, event: Any = None) -> None:
		if self.app is not None:
			self.app.message(self.build_report(), "Estadísticas de uso", False)

	def _reset_statistics(self, event: Any = None) -> None:
		self._total_time_seconds = 0
		self._stations_played = 0
		self._first_use = datetime.now().isoformat(timespec="seconds")
		if self._session_start:
			self._session_start = datetime.now()
		self._save_statistics()
		if self.app is not None:
			self.app.speak("Estadísticas de uso reiniciadas")
