# -*- coding: utf-8 -*-
# Copyright (C) 2025-2026 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General GNU.

"""Aplicación zRadio BASS: une configuración, base de datos, API, reproductor,
planificador de grabaciones, eventos y plugins.

Las órdenes de teclado, la ventana principal y los plugins usan esta clase.
No depende de wx: los mensajes se dicen con ``speak`` y los cuadros de
mensaje se piden con ``message`` (la interfaz instala su función).
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from typing import Callable

from tiresias.log import getLogger

from . import bass as bassmod
from . import net
from .api_client import RadioBrowserAPI
from .config import ConfigManager
from .database import DatabaseManager
from .events import EventBus, EventType
from .internet import InternetChecker
from .localization import TOP_CODE, get_country_name, get_language_name
from .models import Country, Favorite, Language, ScheduledRecording, Station, Tag
from .player import AudioPlayer, PlayerState, format_duration
from .plugin_manager import PluginManager
from .recording import STATUS_NAMES, RecordingScheduler, recording_filename

log = getLogger("zRadioBASS.app")


def _defaultSpeak(text: str) -> None:
	from tiresias import queue_handler, speech

	queue_handler.queueFunction(speech.speakMessage, text)


class RadioApp:
	"""Núcleo del complemento (sin interfaz gráfica)."""

	def __init__(
		self,
		config: ConfigManager,
		db: DatabaseManager | None = None,
		api: RadioBrowserAPI | None = None,
		player: AudioPlayer | None = None,
		event_bus: EventBus | None = None,
		bass_loader: Callable[[], bassmod.Bass] = bassmod.get,
		speak: Callable[[str], None] | None = None,
		load_plugins: bool = True,
		builtin_plugins_dir: str | None = None,
	) -> None:
		self.config = config
		self.event_bus = event_bus or EventBus()
		self.db = db or DatabaseManager(config.database_path)
		self.cache = net.ResponseCache(str(config.cache_dir / "api_cache.db"))
		self.api = api or RadioBrowserAPI(cache=self.cache, cacheSettings=lambda: (bool(self.config.cacheEnabled), int(self.config.cacheDays)))
		self.bass_loader = bass_loader
		self.player = player or AudioPlayer(loader=bass_loader)
		self.internet = InternetChecker()
		self.speak: Callable[[str], None] = speak or _defaultSpeak
		#: ``message(texto, título, error)``: cuadro de mensaje (lo instala la interfaz).
		self.message: Callable[[str, str, bool], None] = lambda text, title="", error=False: self.speak(text)
		self.scheduler = RecordingScheduler(self.db, bass_loader, on_event=self._on_schedule_event)
		self._lock = threading.RLock()
		self._history_id: int | None = None
		self._history_started: float | None = None
		self._history_station: Station | None = None
		self._pending_announce: str | None = None
		self._started_once = False
		self._current_favorite_index = 0
		# Estado inicial del reproductor desde lo guardado
		self.player.volume = int(config.volume)
		self.player.muted = bool(config.muted)
		self.apply_options()
		self._setup_player_callbacks()
		self.plugin_manager = PluginManager(
			self.event_bus,
			app=self,
			builtin_dir=builtin_plugins_dir,
			user_dir=config.plugins_dir,
			disabled=lambda: list(self.config.disabled_plugins),
			set_disabled=self._set_disabled_plugins,
		)
		if load_plugins:
			self.plugin_manager.discover_plugins()
			self.plugin_manager.load_all_plugins()

	# ------------------------------------------------------------- arranque y cierre
	def startup(self) -> None:
		"""Pone en marcha el planificador y, si se pidió, la última emisora."""
		self.scheduler.start()
		try:
			days = max(1, int(self.config.cacheDays))
			threading.Thread(target=self.cache.purge, args=(days,), daemon=True, name="zRadioBASS-cache").start()
		except Exception:
			log.debug("No se pudo limpiar la caché", exc_info=True)
		if self.config.resumeOnStart and self.config.rememberLastStation and self.config.last_station_url:
			self.play_last_station(announce=False)

	def terminate(self) -> None:
		self._close_history_entry()
		try:
			self.scheduler.stop()
		except Exception:
			log.exception("Error deteniendo el planificador")
		try:
			self.player.dispose()
		except Exception:
			log.exception("Error liberando el reproductor")
		try:
			self.plugin_manager.shutdown()
		except Exception:
			log.exception("Error descargando los plugins")
		self.config.save()
		self.api.close()
		self.db.close()

	def apply_options(self) -> None:
		"""Lleva las opciones al reproductor (dispositivo, efectos, reconexión)."""
		c = self.config
		self.player.auto_reconnect = bool(c.autoReconnect)
		self.player.set_effects(int(c.eqBass), int(c.eqMid), int(c.eqTreble), int(c.balance))
		if (c.outputDevice or "") != self.player.device_name:
			self.player.set_output_device(c.outputDevice or "")
		self.event_bus.emit(EventType.CONFIG_CHANGED, None)

	def _set_disabled_plugins(self, ids: list[str]) -> None:
		self.config.disabled_plugins = list(ids)
		self.config.save()

	# ------------------------------------------------------------- avisos del reproductor
	def _setup_player_callbacks(self) -> None:
		p = self.player
		p.set_on_state_change(self._on_state_change)
		p.set_on_error(self._on_error)
		p.set_on_metadata(self._on_metadata)
		p.set_on_playing(self._on_playing)
		p.set_on_buffering(lambda: self.event_bus.emit(EventType.BUFFERING_STARTED, self.player.current_station))
		p.set_on_recording_started(lambda path: self.event_bus.emit(EventType.RECORDING_STARTED, {"path": path, "scheduled": False}))
		p.set_on_recording_stopped(lambda path: self.event_bus.emit(EventType.RECORDING_STOPPED, {"path": path, "scheduled": False}))
		p.set_on_reconnecting(self._on_reconnecting)

	def _on_state_change(self, state: PlayerState) -> None:
		if state == PlayerState.PAUSED:
			self.event_bus.emit(EventType.PLAYBACK_PAUSED, self.player.current_station)
		elif state == PlayerState.STOPPED:
			self._close_history_entry()

	def _on_playing(self) -> None:
		station = self.player.current_station
		with self._lock:
			first = not self._started_once
			self._started_once = True
			announce, self._pending_announce = self._pending_announce, None
		if first:
			# Primera vez que suena esta petición: historial, estadísticas y eventos.
			self._close_history_entry()
			if station is not None:
				try:
					self._history_id = self.db.add_to_history(station)
					self._history_started = time.monotonic()
					self._history_station = station
				except Exception:
					log.exception("No se pudo añadir al historial")
				self.event_bus.emit(EventType.HISTORY_CHANGED, station)
			self.event_bus.emit(EventType.BUFFERING_ENDED, station)
			self.event_bus.emit(EventType.PLAYBACK_STARTED, station)
			if announce:
				self.speak(announce)
			elif self.config.announceConnected and station is not None:
				self.speak(f"Conectado: {station.name}")
		else:
			self.event_bus.emit(EventType.BUFFERING_ENDED, station)
			if self.player.state == PlayerState.PLAYING:
				self.event_bus.emit(EventType.PLAYBACK_RESUMED, station)

	def _on_error(self, error: str) -> None:
		self._close_history_entry()
		self.event_bus.emit(EventType.PLAYBACK_ERROR, error)
		self.speak(f"Error de reproducción: {error}")

	def _on_metadata(self, data: dict) -> None:
		self.event_bus.emit(EventType.METADATA_UPDATED, data)
		if self.config.announceTitle and data.get("title"):
			self.speak(data["title"])

	def _on_reconnecting(self, attempt: int) -> None:
		self.speak(f"Se cortó la emisora. Reconectando, intento {attempt}")

	def _close_history_entry(self) -> None:
		with self._lock:
			hid, started = self._history_id, self._history_started
			self._history_id = self._history_started = None
			self._history_station = None
		if hid is not None and started is not None:
			try:
				self.db.set_history_duration(hid, int(time.monotonic() - started))
				self.event_bus.emit(EventType.HISTORY_CHANGED, None)
			except Exception:
				log.debug("No se pudo guardar la duración", exc_info=True)

	# ------------------------------------------------------------- reproducción
	def play_station(self, station: Station, announce: str | None = None, check_url: bool = True, on_fail: Callable[[str], None] | None = None) -> None:
		"""Reproduce una emisora (comprueba la conexión en otro hilo).

		``announce``: texto que se dice cuando empieza a sonar.
		``on_fail(mensaje)``: se llama si no se puede conectar (si no, se dice).
		"""
		url = station.play_url if isinstance(station, Station) else getattr(station, "url", "")
		if not url:
			self.speak("La emisora no tiene dirección")
			return

		def run() -> None:
			if check_url and not self.internet.check_url(url):
				msg = "No se pudo conectar con la emisora. Verifique su conexión o intente más tarde."
				if on_fail:
					on_fail(msg)
				else:
					self.speak("No se pudo conectar con la emisora")
				self.event_bus.emit(EventType.PLAYBACK_ERROR, msg)
				return
			self._close_history_entry()
			with self._lock:
				self._started_once = False
				self._pending_announce = announce
			self.player.play(url, station=station)
			self.config.remember_station(station.name, station.url, station.stationuuid)
			try:
				self.db.increment_play_count_by_url(station.url)
			except Exception:
				log.debug("No se pudo contar la reproducción", exc_info=True)
			if station.stationuuid:
				threading.Thread(target=self.api.click_station, args=(station.stationuuid,), daemon=True, name="zRadioBASS-clic").start()

		threading.Thread(target=run, daemon=True, name="zRadioBASS-reproducir").start()

	def stop(self) -> bool:
		"""Detiene la reproducción. ``False`` si no había nada sonando."""
		if self.player.state == PlayerState.STOPPED:
			return False
		self.player.stop()
		self._close_history_entry()
		self.event_bus.emit(EventType.PLAYBACK_STOPPED, None)
		return True

	def reload(self) -> bool:
		station = self.player.current_station
		if station is None and not self.player.current_url:
			return False
		if station is not None:
			self.play_station(station, check_url=False)
		else:
			self.player.reload()
		return True

	def toggle_pause(self) -> str:
		st = self.player.state
		if st == PlayerState.PLAYING:
			self.player.pause()
			return "En pausa"
		if st == PlayerState.PAUSED:
			self.player.resume()
			self.event_bus.emit(EventType.PLAYBACK_RESUMED, self.player.current_station)
			return "Reanudado"
		if st == PlayerState.BUFFERING:
			return "La emisora todavía se está cargando"
		return "No hay nada reproduciéndose"

	def set_volume(self, value: int) -> int:
		value = max(0, min(100, int(value)))
		self.player.volume = value
		self.config.volume = value
		self.config.save()
		self.event_bus.emit(EventType.VOLUME_CHANGED, value)
		return value

	def volume_step(self, direction: int) -> str:
		"""Sube (1) o baja (-1) el volumen el paso configurado. Devuelve el mensaje."""
		cur = self.player.volume
		if direction > 0 and cur >= 100:
			return "Volumen al máximo"
		if direction < 0 and cur <= 0:
			return "Volumen al mínimo"
		step = max(1, int(self.config.volumeStep))
		return f"{self.set_volume(cur + step * direction)}%"

	def toggle_mute(self) -> bool:
		self.player.toggle_mute()
		self.config.muted = self.player.muted
		self.config.save()
		self.event_bus.emit(EventType.MUTE_TOGGLED, self.player.muted)
		return self.player.muted

	def play_last_station(self, announce: bool = True) -> bool:
		c = self.config
		if not c.rememberLastStation or not c.last_station_url:
			return False
		st = Station(name=c.last_station_name or c.last_station_url, url=c.last_station_url, stationuuid=c.last_station_uuid or "")
		self.play_station(st, announce=st.name if announce else None)
		return True

	# ------------------------------------------------------------- favoritos
	def play_favorite(self, position: int) -> str | None:
		"""Reproduce el favorito ``position`` (1-5 en las órdenes rápidas). Mensaje si no se puede."""
		favorites = self.db.get_favorites(limit=max(5, position))
		if position < 1 or position > len(favorites):
			return f"No hay emisora favorita en la posición {position}"
		fav = favorites[position - 1]
		self._current_favorite_index = position - 1
		self.play_station(fav.to_station(), announce=None)
		return fav.name

	def play_favorite_by_index(self, index: int) -> str | None:
		favorites = self.db.get_favorites()
		if not favorites:
			return None
		total = len(favorites)
		self._current_favorite_index = index % total
		fav = favorites[self._current_favorite_index]
		self.play_station(fav.to_station())
		return f"{self._current_favorite_index + 1} de {total}. {fav.name}"

	def next_favorite(self, direction: int = 1) -> str:
		favorites = self.db.get_favorites()
		if not favorites:
			return "No hay favoritos guardados"
		return self.play_favorite_by_index(self._current_favorite_index + direction) or ""

	def add_favorite(self, station: Station, category_id: int | None = None) -> Favorite | None:
		if self.db.favorite_exists(station.url):
			return None
		fav = Favorite.from_station(station, category_id)
		self.db.add_favorite(fav)
		self.event_bus.emit(EventType.FAVORITE_ADDED, fav)
		return fav

	def remove_favorite_by_url(self, url: str) -> Favorite | None:
		fav = self.db.get_favorite_by_url(url)
		if fav is None:
			return None
		self.db.delete_favorite(fav.id)
		self.event_bus.emit(EventType.FAVORITE_REMOVED, fav)
		return fav

	def vote(self, station: Station) -> str:
		if not station.stationuuid:
			return "Esta emisora no está en Radio Browser: no se puede votar."
		ok, msg = self.api.vote_for_station(station.stationuuid)
		if ok:
			return f"Voto registrado para {station.name}."
		return f"No se pudo votar: {msg or 'el servidor no aceptó el voto (solo se puede votar una vez cada 10 minutos por emisora)'}."

	def station_details(self, station: Station) -> Station:
		"""Completa una emisora con los datos de la API (si tiene identificador)."""
		if station.stationuuid and not station.country:
			found = self.api.get_stations_by_uuid(station.stationuuid)
			if found:
				return found[0]
		return station

	# ------------------------------------------------------------- listas de la API (con caché)
	def list_countries(self) -> list[Country]:
		c = self.config
		if c.cacheEnabled and self.db.is_cache_valid("cache_countries", int(c.cacheDays)):
			rows = self.db.get_cached_countries()
			if rows:
				return [Country(name=r["name"], code=r["code"], station_count=r["station_count"] or 0, name_localized=r["name_localized"] or get_country_name(r["code"])) for r in rows]
		countries = self.api.get_countries()
		if countries and c.cacheEnabled:
			self.db.cache_countries([{"iso_3166_1": x.code, "name": x.name, "name_localized": x.name_localized, "stationcount": x.station_count} for x in countries])
		return countries

	def list_languages(self) -> list[Language]:
		c = self.config
		if c.cacheEnabled and self.db.is_cache_valid("cache_languages", int(c.cacheDays)):
			rows = self.db.get_cached_languages()
			if rows:
				return [Language(name=r["name"], station_count=r["station_count"] or 0, name_localized=get_language_name(r["name"])) for r in rows]
		langs = self.api.get_languages()
		if langs and c.cacheEnabled:
			self.db.cache_languages([{"name": x.name, "stationcount": x.station_count} for x in langs])
		return langs

	def list_tags(self) -> list[Tag]:
		c = self.config
		if c.cacheEnabled and self.db.is_cache_valid("cache_tags", int(c.cacheDays)):
			rows = self.db.get_cached_tags()
			if rows:
				return [Tag(name=r["name"], station_count=r["station_count"] or 0) for r in rows]
		tags = self.api.get_tags(limit=2000)
		if tags and c.cacheEnabled:
			self.db.cache_tags([{"name": x.name, "stationcount": x.station_count} for x in tags])
		return tags

	def general_stations(self, country_code: str) -> list[Station]:
		"""Emisoras de la pestaña General («TOP» = las más votadas del mundo)."""
		limit = max(10, int(self.config.searchLimit))
		hide = bool(self.config.hideBroken)
		if country_code == TOP_CODE:
			return self.api.get_top_stations(limit=min(limit, 2000), raise_errors=True, hidebroken=hide)
		return self.api.get_stations_by_country(country_code, limit=limit, raise_errors=True, hidebroken=hide)

	def clear_cache(self) -> int:
		n = self.api.clear_cache()
		self.db.clear_caches()
		return n

	# ------------------------------------------------------------- grabación
	def start_recording_current(self) -> tuple[bool, str]:
		"""Graba la emisora que suena. Devuelve ``(correcto, mensaje o ruta)``."""
		if not self.player.is_active:
			return False, "No hay ninguna emisora reproduciéndose"
		if self.player.is_recording:
			return False, "Ya hay una grabación en curso"
		station = self.player.current_station
		name = station.name if station is not None else "radio"
		path = str(self.config.recordings_dir / recording_filename(name))
		if self.player.start_recording(path):
			return True, self.player.recording_file
		return False, f"Error al iniciar la grabación: {self.player.last_error}" if self.player.last_error else "Error al iniciar la grabación"

	def stop_recording_current(self) -> str | None:
		return self.player.stop_recording()

	def schedule_recording(self, station_url: str, station_name: str, start_time: datetime, end_time: datetime, output_path: str) -> ScheduledRecording | None:
		return self.scheduler.schedule(station_url, station_name, start_time, end_time, output_path)

	def cancel_scheduled_recording(self, rec_id: int) -> bool:
		return self.scheduler.cancel(rec_id)

	@property
	def is_recording(self) -> bool:
		return self.player.is_recording or self.scheduler.running_count() > 0

	def recording_status_message(self) -> str:
		parts = []
		if self.player.is_recording:
			d = self.player.recording_duration
			parts.append(f"Grabando - {format_duration(d.total_seconds() if d else 0)}")
		running = self.scheduler.running_recorders()
		for _rid, rec in running.items():
			if rec.running and rec.started_at:
				parts.append(f"Grabación programada en curso - {format_duration((datetime.now() - rec.started_at).total_seconds())}")
		pending = [r for r in self.scheduler.active() if r.status == "pending"]
		if parts:
			msg = ". ".join(parts)
			if pending:
				msg += f". {len(pending)} grabaciones programadas"
			return msg
		if pending:
			return f"No grabando. {len(pending)} grabaciones programadas"
		return "No hay grabación activa"

	def _on_schedule_event(self, kind: str, rec: ScheduledRecording) -> None:
		self.event_bus.emit(EventType.SCHEDULE_CHANGED, rec)
		if kind == "scheduled":
			self.event_bus.emit(EventType.RECORDING_SCHEDULED, rec)
		elif kind == "started":
			self.event_bus.emit(EventType.RECORDING_STARTED, {"path": rec.output_path, "scheduled": True, "recording": rec})
			self.speak(f"Empieza la grabación programada de {rec.station_name}")
		elif kind == "finished":
			self.event_bus.emit(EventType.RECORDING_STOPPED, {"path": rec.output_path, "scheduled": True, "recording": rec})
			self.speak(f"Terminó la grabación programada de {rec.station_name}")
		elif kind == "failed":
			self.event_bus.emit(EventType.RECORDING_STOPPED, {"path": rec.output_path, "scheduled": True, "recording": rec})
			self.speak(f"Falló la grabación programada de {rec.station_name}: {rec.error}")
		elif kind == "missed":
			self.speak(f"Grabación programada perdida: {rec.station_name} ({STATUS_NAMES['missed']})")

	# ------------------------------------------------------------- estado
	def status_message(self) -> str:
		active = self.scheduler.active()
		pending = sum(1 for r in active if r.status == "pending")
		return self.player.get_status_message(scheduled_count=pending, scheduled_recording=self.scheduler.running_count())

	def current_station_message(self) -> str:
		station = self.player.current_station
		if station is None or not self.player.is_active:
			return "No hay ninguna emisora reproduciéndose"
		return f"Emisora: {station.name}"

	def current_title_message(self) -> str:
		if not self.player.is_active:
			return "No hay ninguna emisora reproduciéndose"
		return self.player.title or "La emisora no envía el título de la canción"

	def open_recordings_folder(self) -> str | None:
		"""Abre la carpeta de grabaciones en el Explorador (``None`` si va bien)."""
		folder = str(self.config.recordings_dir)
		if not os.path.isdir(folder):
			return f"La carpeta de grabaciones no existe:\n{folder}"
		try:
			os.startfile(folder)  # noqa: S606
		except OSError as e:
			return f"No se pudo abrir la carpeta: {e}"
		return None
