# -*- coding: utf-8 -*-
# Copyright (C) 2025-2026 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General GNU.

"""Reproductor de emisoras con BASS.

Volumen y silencio, pausa, recarga, dispositivo de salida, ecualizador y
balance, título de la canción (metadatos ICY/OGG/WMA/HLS), reconexión
automática si la emisora se corta y grabación de la emisora que suena a WAV.

Todo lo lento (conectar con la emisora) se hace en hilos propios; los
avisos llegan por las funciones ``set_on_*`` desde esos hilos.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import Any, Callable

from tiresias.log import getLogger

from . import bass as bassmod
from .bass import BassError

log = getLogger("zRadioBASS.player")

#: Bandas del ecualizador: graves, medios y agudos (Hz).
EQ_FREQUENCIES = (100.0, 1000.0, 8000.0)
EQ_LIMIT = 12
#: Intentos de reconexión seguidos antes de rendirse.
MAX_RECONNECTS = 5


class PlayerState(Enum):
	STOPPED = auto()
	PLAYING = auto()
	BUFFERING = auto()
	PAUSED = auto()
	ERROR = auto()


class RecordingState(Enum):
	IDLE = auto()
	RECORDING = auto()
	SCHEDULED = auto()


#: Nombres en español de los estados (para mensajes).
STATE_NAMES = {
	PlayerState.STOPPED: "detenido",
	PlayerState.PLAYING: "reproduciendo",
	PlayerState.BUFFERING: "cargando",
	PlayerState.PAUSED: "en pausa",
	PlayerState.ERROR: "error",
}


def format_duration(seconds: float | None) -> str:
	"""«1:05» o «1:02:03»."""
	s = int(seconds or 0)
	h, rem = divmod(s, 3600)
	m, sec = divmod(rem, 60)
	return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


class AudioPlayer:
	"""Reproductor de una emisora a la vez."""

	def __init__(self, loader: Callable[[], bassmod.Bass] = bassmod.get, fixed_device: int | None = None) -> None:
		"""
		``loader``: devuelve el envoltorio de BASS (se carga al reproducir por primera vez).
		``fixed_device``: dispositivo fijo (``0`` = «sin sonido» de BASS, para pruebas).
		"""
		self._loader = loader
		self._bass: bassmod.Bass | None = None
		self._fixed_device = fixed_device
		self._lock = threading.RLock()
		self._handle = 0
		self._fx = 0
		self._gen = 0
		self._state = PlayerState.STOPPED
		self._volume = 50
		self._muted = False
		self._current_url = ""
		self._current_station: Any = None
		self._title = ""
		self._last_error = ""
		self.device_name = ""
		self._device = -2
		self._eq = (0, 0, 0)
		self._pan = 0
		self.auto_reconnect = True
		self._reconnects = 0
		self._playing_since: float | None = None
		self._stopped_by_user = True
		# Grabación de la emisora que suena
		self._encoder = 0
		self._record_file = ""
		self._recording_start_time: datetime | None = None
		self._recording_state = RecordingState.IDLE
		# Hilo de vigilancia (estado, títulos, reconexión)
		self._monitor: threading.Thread | None = None
		self._disposed = False
		self._wake = threading.Event()
		# Avisos
		self._on_state_change: Callable[[PlayerState], None] | None = None
		self._on_error: Callable[[str], None] | None = None
		self._on_metadata: Callable[[dict], None] | None = None
		self._on_recording_started: Callable[[str], None] | None = None
		self._on_recording_stopped: Callable[[str], None] | None = None
		self._on_buffering: Callable[[], None] | None = None
		self._on_playing: Callable[[], None] | None = None
		self._on_reconnecting: Callable[[int], None] | None = None

	# ------------------------------------------------------------- BASS
	@property
	def bass(self) -> bassmod.Bass:
		if self._bass is None:
			b = self._loader()
			b.configure()
			b.loadPlugins()
			self._bass = b
		return self._bass

	@property
	def available(self) -> bool:
		try:
			return self.bass is not None
		except Exception:
			log.exception("BASS no está disponible")
			return False

	def _device_number(self) -> int:
		b = self.bass
		if self._fixed_device is not None:
			return b.initDevice(self._fixed_device)
		return b.initDevice(b.deviceByName(self.device_name))

	# ------------------------------------------------------------- propiedades
	@property
	def state(self) -> PlayerState:
		return self._state

	@property
	def volume(self) -> int:
		return self._volume

	@volume.setter
	def volume(self, value: int) -> None:
		self._volume = max(0, min(100, int(value)))
		self._apply_volume()

	@property
	def muted(self) -> bool:
		return self._muted

	@muted.setter
	def muted(self, value: bool) -> None:
		self._muted = bool(value)
		self._apply_volume()

	@property
	def current_station(self) -> Any:
		return self._current_station

	@current_station.setter
	def current_station(self, station: Any) -> None:
		self._current_station = station

	@property
	def current_url(self) -> str:
		return self._current_url

	@property
	def is_playing(self) -> bool:
		return self._state in (PlayerState.PLAYING, PlayerState.BUFFERING)

	@property
	def is_paused(self) -> bool:
		return self._state == PlayerState.PAUSED

	@property
	def is_active(self) -> bool:
		"""Hay una emisora cargada (sonando, cargando o en pausa)."""
		return self._state in (PlayerState.PLAYING, PlayerState.BUFFERING, PlayerState.PAUSED)

	@property
	def title(self) -> str:
		"""Título de la canción que suena (si la emisora lo envía)."""
		return self._title

	@property
	def last_error(self) -> str:
		return self._last_error

	@property
	def handle(self) -> int:
		return self._handle

	# ------------------------------------------------------------- reproducción
	def play(self, url: str, async_play: bool = True, station: Any = None) -> bool:
		"""Reproduce ``url``. Con ``async_play`` vuelve enseguida y conecta en otro hilo."""
		if not url:
			log.warning("Dirección vacía: no se puede reproducir")
			return False
		self._stop_stream()
		with self._lock:
			self._gen += 1
			gen = self._gen
			self._current_url = url
			if station is not None:
				self._current_station = station
			self._title = ""
			self._last_error = ""
			self._reconnects = 0
			self._stopped_by_user = False
		self._set_state(PlayerState.BUFFERING)
		if self._on_buffering:
			self._safe(self._on_buffering)
		if async_play:
			threading.Thread(target=self._open, args=(url, gen), daemon=True, name="zRadioBASS-conectar").start()
			return True
		return self._open(url, gen)

	def _open(self, url: str, gen: int, reconnect: bool = False) -> bool:
		try:
			b = self.bass
			dev = self._device_number()
			self._device = dev
			b.setThreadDevice(dev)
			h = b.streamFromUrl(url)
		except BassError as e:
			return self._fail(gen, str(e), reconnect)
		except Exception as e:
			log.exception("Error abriendo %s", url)
			return self._fail(gen, f"No se pudo iniciar el reproductor: {e}", reconnect)
		with self._lock:
			if gen != self._gen or self._disposed:
				# Mientras se conectaba se pidió otra emisora o detener.
				b.free(h)
				return False
			self._handle = h
			self._fx = 0
			self._apply_volume()
			self._apply_effects()
			try:
				b.play(h)
			except BassError as e:
				self._handle = 0
				b.free(h)
				return self._fail(gen, str(e), reconnect)
			self._playing_since = time.monotonic()
		self._set_state(PlayerState.PLAYING)
		log.info("Reproduciendo %s (%s)", url, b.formatName(h))
		if self._on_playing:
			self._safe(self._on_playing)
		self._ensure_monitor()
		return True

	def _fail(self, gen: int, message: str, reconnect: bool) -> bool:
		with self._lock:
			if gen != self._gen:
				return False
		log.warning("Error de reproducción: %s", message)
		if reconnect and self._try_reconnect():
			return False
		self._last_error = message
		self._set_state(PlayerState.ERROR)
		if self._on_error:
			self._safe(self._on_error, message)
		return False

	def _stop_stream(self) -> None:
		with self._lock:
			h, self._handle = self._handle, 0
			self._fx = 0
		if self._encoder:
			self.stop_recording()
		if h:
			try:
				self.bass.free(h)
			except Exception:
				log.debug("Error liberando el canal", exc_info=True)

	def stop(self) -> None:
		"""Detiene la reproducción (y la grabación de la emisora que suena)."""
		with self._lock:
			self._gen += 1
			self._stopped_by_user = True
			wasActive = self._state != PlayerState.STOPPED
		self._stop_stream()
		self._current_url = ""
		self._current_station = None
		self._title = ""
		self._playing_since = None
		if wasActive:
			self._set_state(PlayerState.STOPPED)

	def pause(self) -> None:
		h = self._handle
		if not h or self._state != PlayerState.PLAYING:
			return
		try:
			self.bass.pause(h)
		except BassError as e:
			log.warning("No se pudo pausar: %s", e)
			return
		self._set_state(PlayerState.PAUSED)

	def resume(self) -> None:
		h = self._handle
		if not h or self._state != PlayerState.PAUSED:
			return
		try:
			self.bass.play(h)
		except BassError as e:
			log.warning("No se pudo reanudar: %s", e)
			return
		self._set_state(PlayerState.PLAYING)

	def toggle_pause(self) -> None:
		if self._state == PlayerState.PAUSED:
			self.resume()
		elif self._state == PlayerState.PLAYING:
			self.pause()

	def toggle_mute(self) -> None:
		self.muted = not self._muted

	def reload(self) -> bool:
		"""Vuelve a conectar con la emisora actual."""
		url = self._current_url
		if not url:
			return False
		station = self._current_station
		return self.play(url, station=station)

	def set_volume_percent(self, percent: int) -> None:
		self.volume = percent

	def volume_up(self, step: int = 5) -> int:
		self.volume = self._volume + step
		return self._volume

	def volume_down(self, step: int = 5) -> int:
		self.volume = self._volume - step
		return self._volume

	def _apply_volume(self) -> None:
		h = self._handle
		if h and self._bass is not None:
			self._bass.setAttribute(h, bassmod.BASS_ATTRIB_VOL, 0.0 if self._muted else self._volume / 100.0)

	# ------------------------------------------------------------- dispositivos y efectos
	def list_output_devices(self) -> list[str]:
		"""Nombres de los dispositivos de salida de Windows."""
		try:
			return [name for _n, name, _f in self.bass.devices()]
		except Exception:
			log.exception("No se pudieron enumerar los dispositivos")
			return []

	def set_output_device(self, name: str) -> bool:
		"""Cambia el dispositivo de salida (``""`` = el predeterminado de Windows)."""
		self.device_name = name or ""
		h = self._handle
		if not h or self._fixed_device is not None:
			return True
		try:
			dev = self._device_number()
			if dev != self._device:
				self.bass.setChannelDevice(h, dev)
				self._device = dev
			return True
		except BassError as e:
			log.warning("No se pudo cambiar el dispositivo: %s", e)
			return False

	def set_effects(self, bass_db: int = 0, mid_db: int = 0, treble_db: int = 0, balance: int = 0) -> None:
		"""Ecualizador (−12 a +12 dB por banda) y balance (−100 izquierda a +100 derecha)."""
		clamp = lambda v: max(-EQ_LIMIT, min(EQ_LIMIT, int(v)))  # noqa: E731
		self._eq = (clamp(bass_db), clamp(mid_db), clamp(treble_db))
		self._pan = max(-100, min(100, int(balance)))
		with self._lock:
			self._apply_effects()

	@property
	def effects(self) -> tuple[int, int, int, int]:
		return (*self._eq, self._pan)

	def _apply_effects(self) -> None:
		h = self._handle
		if not h or self._bass is None:
			return
		b = self._bass
		b.setAttribute(h, bassmod.BASS_ATTRIB_PAN, self._pan / 100.0)
		if any(self._eq):
			self._fx = b.setPeakEq(h, self._fx, list(zip(EQ_FREQUENCIES, self._eq)))
		elif self._fx:
			b.removeFx(h, self._fx)
			self._fx = 0

	# ------------------------------------------------------------- vigilancia
	def _ensure_monitor(self) -> None:
		if self._monitor is not None and self._monitor.is_alive():
			return
		self._monitor = threading.Thread(target=self._monitor_loop, daemon=True, name="zRadioBASS-vigilancia")
		self._monitor.start()

	def _monitor_loop(self) -> None:
		while not self._disposed:
			try:
				self._check_channel()
			except Exception:
				log.debug("Error vigilando el canal", exc_info=True)
			self._wake.wait(1.0)
			self._wake.clear()

	def _check_channel(self) -> None:
		h = self._handle
		if not h or self._bass is None:
			# Grabación sin reproducción: nada que vigilar.
			return
		b = self._bass
		active = b.isActive(h)
		if active == bassmod.BASS_ACTIVE_STALLED and self._state == PlayerState.PLAYING:
			self._set_state(PlayerState.BUFFERING)
			if self._on_buffering:
				self._safe(self._on_buffering)
		elif active == bassmod.BASS_ACTIVE_PLAYING and self._state == PlayerState.BUFFERING:
			self._set_state(PlayerState.PLAYING)
			if self._on_playing:
				self._safe(self._on_playing)
		elif active == bassmod.BASS_ACTIVE_STOPPED and self._state in (PlayerState.PLAYING, PlayerState.BUFFERING):
			if h != self._handle:
				return
			log.info("La emisora dejó de transmitir")
			if self._encoder:
				self.stop_recording()
			if not self._try_reconnect():
				with self._lock:
					self._handle = 0
				b.free(h)
				self._last_error = bassmod.ERRORS[bassmod.BASS_ERROR_ENDED]
				self._set_state(PlayerState.ERROR)
				if self._on_error:
					self._safe(self._on_error, self._last_error)
			return
		if self._state == PlayerState.PLAYING and self._playing_since and time.monotonic() - self._playing_since > 30:
			self._reconnects = 0
		title = b.streamTitle(h)
		if title != self._title:
			self._title = title
			if title and self._on_metadata:
				self._safe(self._on_metadata, {"title": title, "station": self._current_station})
		if self._encoder and not b.encodeActive(self._encoder):
			log.warning("La grabación se detuvo sola")
			self.stop_recording()

	def _try_reconnect(self) -> bool:
		if not self.auto_reconnect or self._stopped_by_user or not self._current_url:
			return False
		if self._reconnects >= MAX_RECONNECTS:
			return False
		self._reconnects += 1
		attempt = self._reconnects
		url = self._current_url
		with self._lock:
			old, self._handle = self._handle, 0
			self._fx = 0
			self._gen += 1
			gen = self._gen
		if old:
			self.bass.free(old)
		self._set_state(PlayerState.BUFFERING)
		if self._on_reconnecting:
			self._safe(self._on_reconnecting, attempt)

		def later() -> None:
			time.sleep(min(10, 2 * attempt))
			with self._lock:
				if gen != self._gen:
					return
			self._open(url, gen, reconnect=True)

		threading.Thread(target=later, daemon=True, name="zRadioBASS-reconectar").start()
		return True

	# ------------------------------------------------------------- información
	def stream_info(self) -> dict[str, Any]:
		"""Formato, frecuencia, canales y cabeceras ICY de la emisora que suena."""
		h = self._handle
		if not h or self._bass is None:
			return {}
		b = self._bass
		info = b.channelInfo(h)
		icy = b.icyHeaders(h)
		out: dict[str, Any] = {"format": b.formatName(h), "title": self._title}
		if info is not None:
			out["frequency"] = int(info.freq)
			out["channels"] = int(info.chans)
		for key, name in (("icy-name", "name"), ("icy-genre", "genre"), ("icy-br", "bitrate"), ("icy-url", "homepage"), ("icy-description", "description")):
			if icy.get(key):
				out[name] = icy[key]
		out["buffer"] = b.bufferPercent(h)
		return out

	def get_metadata(self) -> dict:
		return {"title": self._title, "duration": 0}

	# ------------------------------------------------------------- grabación de la emisora que suena
	@property
	def is_recording(self) -> bool:
		return bool(self._encoder)

	@property
	def recording_state(self) -> RecordingState:
		return self._recording_state

	@property
	def recording_file(self) -> str:
		return self._record_file

	@property
	def recording_duration(self) -> timedelta | None:
		if self._recording_start_time is not None and self._encoder:
			return datetime.now() - self._recording_start_time
		return None

	def start_recording(self, output_path: str) -> bool:
		"""Graba la emisora que suena en un WAV (``output_path``; se cambia la extensión a .wav)."""
		with self._lock:
			if self._encoder:
				log.warning("Ya hay una grabación en curso")
				return False
			h = self._handle
			if not h or self._state not in (PlayerState.PLAYING, PlayerState.BUFFERING, PlayerState.PAUSED):
				log.warning("No hay ninguna emisora sonando para grabar")
				return False
			root, ext = os.path.splitext(output_path)
			if ext.lower() != ".wav":
				output_path = root + ".wav"
			try:
				os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
				self._encoder = self.bass.encodeToWav(h, output_path)
			except (BassError, OSError) as e:
				log.error("No se pudo empezar a grabar: %s", e)
				self._last_error = str(e)
				return False
			self._record_file = output_path
			self._recording_start_time = datetime.now()
			self._recording_state = RecordingState.RECORDING
		log.info("Grabación iniciada: %s", output_path)
		if self._on_recording_started:
			self._safe(self._on_recording_started, output_path)
		return True

	def stop_recording(self) -> str | None:
		"""Detiene la grabación. Devuelve el archivo grabado (o ``None``)."""
		with self._lock:
			enc, self._encoder = self._encoder, 0
			path, self._record_file = self._record_file, ""
			self._recording_state = RecordingState.IDLE
			self._recording_start_time = None
		if not enc:
			return None
		try:
			self.bass.encodeStop(enc)
		except Exception:
			log.debug("Error deteniendo el codificador", exc_info=True)
		log.info("Grabación detenida: %s", path)
		if path and self._on_recording_stopped:
			self._safe(self._on_recording_stopped, path)
		return path or None

	# ------------------------------------------------------------- estado
	def get_status_info(self) -> dict[str, Any]:
		station = self._current_station
		name = getattr(station, "name", "") if station is not None else ""
		dur = self.recording_duration
		return {
			"state": self._state.name,
			"is_playing": self.is_playing,
			"is_paused": self.is_paused,
			"is_recording": self.is_recording,
			"station_name": name,
			"station_url": self._current_url,
			"title": self._title,
			"volume": self._volume,
			"muted": self._muted,
			"recording_file": self._record_file,
			"recording_duration_seconds": dur.total_seconds() if dur else None,
		}

	def get_status_message(self, scheduled_count: int = 0, scheduled_recording: int = 0) -> str:
		"""Estado legible: emisora, canción, volumen y grabaciones."""
		info = self.get_status_info()
		lines = []
		name = info["station_name"] or info["station_url"]
		if self._state == PlayerState.BUFFERING:
			lines.append(f"Cargando: {name or 'emisora desconocida'}")
		elif self._state == PlayerState.PLAYING:
			lines.append(f"Reproduciendo: {name or 'emisora desconocida'}")
		elif self._state == PlayerState.PAUSED:
			lines.append(f"En pausa: {name or 'emisora desconocida'}")
		elif self._state == PlayerState.ERROR:
			lines.append(f"Error: {self._last_error or 'no se pudo reproducir'}")
		else:
			lines.append("Sin reproducción activa")
		if info["title"] and self._state in (PlayerState.PLAYING, PlayerState.PAUSED, PlayerState.BUFFERING):
			lines.append(f"Suena: {info['title']}")
		lines.append(f"Volumen: {info['volume']}%" + (" (silenciado)" if info["muted"] else ""))
		if info["is_recording"]:
			lines.append(f"Grabando ({format_duration(info['recording_duration_seconds'])})")
		if scheduled_recording:
			lines.append(f"Grabaciones programadas en curso: {scheduled_recording}")
		if scheduled_count:
			lines.append(f"Grabaciones programadas: {scheduled_count}")
		return "\n".join(lines)

	# ------------------------------------------------------------- avisos
	def _set_state(self, state: PlayerState) -> None:
		changed = state != self._state
		self._state = state
		if changed and self._on_state_change:
			self._safe(self._on_state_change, state)

	@staticmethod
	def _safe(func: Callable, *args: Any) -> None:
		try:
			func(*args)
		except Exception:
			log.exception("Error en un aviso del reproductor")

	def set_on_state_change(self, cb: Callable[[PlayerState], None] | None) -> None:
		self._on_state_change = cb

	def set_on_error(self, cb: Callable[[str], None] | None) -> None:
		self._on_error = cb

	def set_on_metadata(self, cb: Callable[[dict], None] | None) -> None:
		self._on_metadata = cb

	def set_on_recording_started(self, cb: Callable[[str], None] | None) -> None:
		self._on_recording_started = cb

	def set_on_recording_stopped(self, cb: Callable[[str], None] | None) -> None:
		self._on_recording_stopped = cb

	def set_on_buffering(self, cb: Callable[[], None] | None) -> None:
		self._on_buffering = cb

	def set_on_playing(self, cb: Callable[[], None] | None) -> None:
		self._on_playing = cb

	def set_on_reconnecting(self, cb: Callable[[int], None] | None) -> None:
		self._on_reconnecting = cb

	def dispose(self) -> None:
		"""Libera el canal y detiene la vigilancia (no libera BASS: puede compartirse)."""
		self._disposed = True
		try:
			self.stop()
		except Exception:
			log.debug("Error deteniendo al liberar", exc_info=True)
		self._wake.set()
		if self._monitor is not None:
			self._monitor.join(timeout=2)
			self._monitor = None
