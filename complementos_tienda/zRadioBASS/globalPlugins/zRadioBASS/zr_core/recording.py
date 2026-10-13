# -*- coding: utf-8 -*-
# Copyright (C) 2025-2026 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General GNU.

"""Grabaciones programadas.

Cada grabación programada abre su propia conexión con la emisora como canal
de decodificación de BASS (no suena por los altavoces) y la guarda en WAV
con BASSenc. Así funciona aunque no se esté escuchando nada, aunque se
escuche otra emisora y aunque se detenga la reproducción. Si la emisora se
corta, se vuelve a conectar hasta la hora de fin.

Las grabaciones programadas se guardan en la base de datos: sobreviven al
reinicio de Tiresias (el original las perdía). Las que debían empezar
mientras Tiresias estaba cerrado empiezan al arrancar si aún no ha llegado
su hora de fin; si ya pasó, quedan como «perdidas».
"""

from __future__ import annotations

import ctypes
import os
import re
import threading
import time
from datetime import datetime
from typing import Any, Callable

from tiresias.log import getLogger

from . import bass as bassmod
from .bass import BassError
from .models import ScheduledRecording

log = getLogger("zRadioBASS.recording")

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

#: Estados de una grabación programada → texto en español.
STATUS_NAMES = {
	"pending": "pendiente",
	"recording": "grabando",
	"done": "terminada",
	"cancelled": "cancelada",
	"missed": "perdida (Tiresias no estaba en marcha)",
	"failed": "fallida",
}


def safe_filename(name: str, default: str = "radio") -> str:
	"""Nombre de archivo válido en Windows a partir de ``name``."""
	clean = _INVALID.sub("_", name or "").strip().rstrip(".")
	return clean or default


def recording_filename(station_name: str, when: datetime | None = None) -> str:
	"""«Emisora_AAAAMMDD_HHMMSS.wav» (como el original)."""
	when = when or datetime.now()
	return f"{safe_filename(station_name)}_{when.strftime('%Y%m%d_%H%M%S')}.wav"


def unique_path(path: str) -> str:
	"""``path`` o, si ya existe, ``nombre (2).wav``, ``nombre (3).wav``..."""
	if not os.path.exists(path):
		return path
	root, ext = os.path.splitext(path)
	i = 2
	while os.path.exists(f"{root} ({i}){ext}"):
		i += 1
	return f"{root} ({i}){ext}"


class StreamRecorder:
	"""Graba una emisora en WAV sin reproducirla (canal de decodificación)."""

	BUFFER = 65536

	def __init__(self, loader: Callable[[], bassmod.Bass], url: str, path: str, end_time: datetime | None = None, on_finish: Callable[["StreamRecorder"], None] | None = None) -> None:
		self._loader = loader
		self.url = url
		self.path = path
		self.end_time = end_time
		self.on_finish = on_finish
		self.error = ""
		self.bytes = 0
		self.started_at: datetime | None = None
		self._stop = threading.Event()
		self._thread: threading.Thread | None = None
		self._reconnects = 0

	@property
	def running(self) -> bool:
		return self._thread is not None and self._thread.is_alive()

	def start(self) -> None:
		self._thread = threading.Thread(target=self._run, daemon=True, name="zRadioBASS-grabar")
		self._thread.start()

	def stop(self, wait: float = 5.0) -> None:
		self._stop.set()
		if self._thread is not None and self._thread is not threading.current_thread():
			self._thread.join(timeout=wait)

	def _expired(self) -> bool:
		return self._stop.is_set() or (self.end_time is not None and datetime.now() >= self.end_time)

	def _open(self, b: bassmod.Bass) -> tuple[int, int]:
		b.initDevice(bassmod.NO_SOUND_DEVICE)
		b.setThreadDevice(bassmod.NO_SOUND_DEVICE)
		h = b.streamFromUrl(self.url, decode=True)
		return h, 0

	def _run(self) -> None:
		b = None
		h = enc = 0
		self.started_at = datetime.now()
		try:
			b = self._loader()
			b.configure()
			b.loadPlugins()
			os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
			h, _x = self._open(b)
			enc = b.encodeToWav(h, self.path)
			buf = ctypes.create_string_buffer(self.BUFFER)
			while not self._expired():
				n = b.getData(h, buf, self.BUFFER)
				if n > 0:
					self.bytes += n
					continue
				if n < 0 or b.isActive(h) == bassmod.BASS_ACTIVE_STOPPED:
					code = b.errorCode()
					log.info("La emisora grabada se cortó (%s); se vuelve a conectar", bassmod.ERRORS.get(code, code))
					# Se cierra este tramo y se sigue en un archivo nuevo para no corromper el WAV.
					b.encodeStop(enc)
					b.free(h)
					h = enc = 0
					if not self._reconnect_wait():
						break
					h, _x = self._open(b)
					self.path = unique_path(self.path)
					enc = b.encodeToWav(h, self.path)
					continue
				time.sleep(0.05)
		except BassError as e:
			self.error = str(e)
			log.warning("Error en la grabación programada: %s", e)
		except Exception as e:
			self.error = str(e)
			log.exception("Error en la grabación programada")
		finally:
			if b is not None:
				if enc:
					b.encodeStop(enc)
				if h:
					b.free(h)
			if self.on_finish:
				try:
					self.on_finish(self)
				except Exception:
					log.exception("Error al terminar la grabación")

	def _reconnect_wait(self) -> bool:
		self._reconnects += 1
		delay = min(30, 2 * self._reconnects)
		end = time.monotonic() + delay
		while time.monotonic() < end:
			if self._expired():
				return False
			time.sleep(0.2)
		return not self._expired()


class RecordingScheduler:
	"""Arranca y detiene las grabaciones programadas a su hora."""

	INTERVAL = 2.0

	def __init__(self, db: Any, loader: Callable[[], bassmod.Bass], on_event: Callable[[str, ScheduledRecording], None] | None = None, recorder_factory: Callable[..., Any] | None = None) -> None:
		"""
		``on_event(tipo, grabación)``: ``started``, ``finished``, ``failed``, ``missed``,
		``cancelled`` o ``scheduled``.
		"""
		self._db = db
		self._loader = loader
		self._on_event = on_event
		self._factory = recorder_factory or StreamRecorder
		self._running: dict[int, Any] = {}
		self._lock = threading.RLock()
		self._thread: threading.Thread | None = None
		self._stopEvent = threading.Event()

	# ------------------------------------------------------------- API
	def schedule(self, station_url: str, station_name: str, start_time: datetime, end_time: datetime, output_path: str) -> ScheduledRecording | None:
		"""Programa una grabación. ``None`` si las horas no son válidas."""
		if start_time >= end_time:
			log.error("La hora de inicio debe ser anterior a la de fin")
			return None
		if end_time <= datetime.now():
			log.error("La hora de fin ya ha pasado")
			return None
		root, ext = os.path.splitext(output_path)
		if ext.lower() != ".wav":
			output_path = root + ".wav"
		rec = ScheduledRecording(station_name=station_name, station_url=station_url, start_time=start_time, end_time=end_time, output_path=output_path)
		self._db.add_scheduled_recording(rec)
		self._emit("scheduled", rec)
		self.check_now()
		return rec

	def cancel(self, rec_id: int) -> bool:
		with self._lock:
			recorder = self._running.pop(rec_id, None)
		if recorder is not None:
			recorder.on_finish = None
			recorder.stop()
		recs = {r.id: r for r in self._db.get_scheduled_recordings(active_only=False)}
		rec = recs.get(rec_id)
		if rec is None or not rec.active:
			return False
		self._db.update_scheduled_status(rec_id, "cancelled")
		rec.status = "cancelled"
		self._emit("cancelled", rec)
		return True

	def cancel_by_index(self, index: int) -> bool:
		"""Compatibilidad con el original: cancela la n.ª de las activas."""
		active = self.active()
		if 0 <= index < len(active):
			return self.cancel(active[index].id)
		return False

	def active(self) -> list[ScheduledRecording]:
		return self._db.get_scheduled_recordings(active_only=True)

	def all(self) -> list[ScheduledRecording]:
		return self._db.get_scheduled_recordings(active_only=False)

	def running_count(self) -> int:
		with self._lock:
			return sum(1 for r in self._running.values() if r.running)

	def running_recorders(self) -> dict[int, Any]:
		with self._lock:
			return dict(self._running)

	# ------------------------------------------------------------- hilo
	def start(self) -> None:
		if self._thread is not None and self._thread.is_alive():
			return
		self._stopEvent.clear()
		self._thread = threading.Thread(target=self._loop, daemon=True, name="zRadioBASS-planificador")
		self._thread.start()

	def stop(self) -> None:
		"""Detiene el planificador y las grabaciones en curso (quedan como terminadas)."""
		self._stopEvent.set()
		if self._thread is not None:
			self._thread.join(timeout=3)
			self._thread = None
		with self._lock:
			running = list(self._running.items())
			self._running.clear()
		for rec_id, recorder in running:
			recorder.on_finish = None
			recorder.stop()
			try:
				# Si Tiresias vuelve a arrancar antes de la hora de fin, seguirá grabando.
				self._db.update_scheduled_status(rec_id, "pending" if recorder.end_time and recorder.end_time > datetime.now() else "done")
			except Exception:
				log.debug("No se pudo actualizar el estado", exc_info=True)

	def check_now(self) -> None:
		try:
			self._tick()
		except Exception:
			log.exception("Error en el planificador de grabaciones")

	def _loop(self) -> None:
		while not self._stopEvent.is_set():
			self.check_now()
			self._stopEvent.wait(self.INTERVAL)

	def _tick(self) -> None:
		now = datetime.now()
		for rec in self._db.get_scheduled_recordings(active_only=True):
			with self._lock:
				isRunning = rec.id in self._running
			if now >= rec.end_time:
				if isRunning:
					self._finish(rec.id)
				elif rec.status == "pending":
					self._db.update_scheduled_status(rec.id, "missed")
					rec.status = "missed"
					self._emit("missed", rec)
				else:
					self._db.update_scheduled_status(rec.id, "done")
				continue
			if rec.start_time <= now and not isRunning:
				self._begin(rec)

	def _begin(self, rec: ScheduledRecording) -> None:
		path = unique_path(rec.output_path)
		recorder = self._factory(self._loader, rec.station_url, path, rec.end_time, self._recorderFinished)
		recorder.rec_id = rec.id
		with self._lock:
			self._running[rec.id] = recorder
		self._db.update_scheduled_status(rec.id, "recording")
		rec.status = "recording"
		rec.output_path = path
		log.info("Empieza la grabación programada de %s en %s", rec.station_name, path)
		recorder.start()
		self._emit("started", rec)

	def _finish(self, rec_id: int) -> None:
		with self._lock:
			recorder = self._running.get(rec_id)
		if recorder is not None:
			recorder.stop()

	def _recorderFinished(self, recorder: Any) -> None:
		rec_id = getattr(recorder, "rec_id", None)
		with self._lock:
			self._running.pop(rec_id, None)
		recs = {r.id: r for r in self._db.get_scheduled_recordings(active_only=False)}
		rec = recs.get(rec_id)
		if rec is None:
			return
		rec.output_path = recorder.path
		if recorder.error and not recorder.bytes:
			self._db.update_scheduled_status(rec_id, "failed", recorder.error)
			rec.status, rec.error = "failed", recorder.error
			self._emit("failed", rec)
		else:
			self._db.update_scheduled_status(rec_id, "done", recorder.error)
			rec.status = "done"
			self._emit("finished", rec)

	def _emit(self, kind: str, rec: ScheduledRecording) -> None:
		if self._on_event:
			try:
				self._on_event(kind, rec)
			except Exception:
				log.exception("Error avisando de la grabación programada")
