# -*- coding: utf-8 -*-
# Copyright (C) 2025-2026 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General GNU.

"""Bus de eventos de zRadio BASS (publicador/suscriptor entre componentes y plugins)."""

from __future__ import annotations

import threading
import time
import weakref
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Callable

from tiresias.log import getLogger

log = getLogger("zRadioBASS.events")


class EventType(Enum):
	"""Tipos de eventos del sistema."""

	# Reproducción
	PLAYBACK_STARTED = auto()
	PLAYBACK_STOPPED = auto()
	PLAYBACK_PAUSED = auto()
	PLAYBACK_RESUMED = auto()
	PLAYBACK_ERROR = auto()
	BUFFERING_STARTED = auto()
	BUFFERING_ENDED = auto()
	# Volumen
	VOLUME_CHANGED = auto()
	MUTE_TOGGLED = auto()
	# Metadatos (título de la canción)
	METADATA_UPDATED = auto()
	# Favoritos
	FAVORITE_ADDED = auto()
	FAVORITE_REMOVED = auto()
	FAVORITE_UPDATED = auto()
	FAVORITES_REORDERED = auto()
	# Categorías
	CATEGORY_ADDED = auto()
	CATEGORY_REMOVED = auto()
	CATEGORY_UPDATED = auto()
	# Búsqueda
	SEARCH_STARTED = auto()
	SEARCH_COMPLETED = auto()
	SEARCH_ERROR = auto()
	# Interfaz
	WINDOW_OPENED = auto()
	WINDOW_CLOSED = auto()
	TAB_CHANGED = auto()
	# Plugins
	PLUGIN_LOADED = auto()
	PLUGIN_UNLOADED = auto()
	PLUGIN_ERROR = auto()
	# Configuración
	CONFIG_CHANGED = auto()
	# Conexión
	INTERNET_CONNECTED = auto()
	INTERNET_DISCONNECTED = auto()
	# Grabación
	RECORDING_STARTED = auto()
	RECORDING_STOPPED = auto()
	RECORDING_SCHEDULED = auto()
	SCHEDULE_CHANGED = auto()
	# Historial
	HISTORY_CHANGED = auto()


@dataclass
class Event:
	"""Un evento emitido (tipo, datos, emisor y momento)."""

	type: EventType
	data: Any = None
	source: str | None = None
	timestamp: float | None = None

	def __post_init__(self) -> None:
		if self.timestamp is None:
			self.timestamp = time.time()


EventCallback = Callable[[Any], None]


class _StrongRef:
	"""Referencia «fuerte» con la misma interfaz que ``weakref.ref``."""

	def __init__(self, obj: Any) -> None:
		self._obj = obj

	def __call__(self) -> Any:
		return self._obj


class EventBus:
	"""Bus de eventos seguro entre hilos.

	Con ``weak=True`` (por defecto) se guarda una referencia débil: los
	métodos de objetos que desaparecen dejan de recibir eventos solos. Las
	funciones sueltas y las lambdas deben suscribirse con ``weak=False``.
	Los suscriptores se llaman en el hilo que emite el evento.
	"""

	def __init__(self) -> None:
		self._subscribers: dict[EventType, list] = {}
		self._lock = threading.RLock()
		self._enabled = True
		#: Último evento emitido de cada tipo (útil para depurar y en pruebas).
		self.lastEvents: dict[EventType, Event] = {}

	def subscribe(self, event_type: EventType, callback: EventCallback, weak: bool = True) -> Callable[[], None]:
		"""Suscribe ``callback``; devuelve una función que cancela la suscripción."""
		with self._lock:
			if weak:
				try:
					ref: Any = weakref.WeakMethod(callback)  # type: ignore[arg-type]
				except TypeError:
					ref = weakref.ref(callback)
			else:
				ref = _StrongRef(callback)
			self._subscribers.setdefault(event_type, []).append(ref)

		def unsubscribe() -> None:
			self._unsubscribe(event_type, ref)

		return unsubscribe

	def _unsubscribe(self, event_type: EventType, ref: Any) -> None:
		with self._lock:
			try:
				self._subscribers.get(event_type, []).remove(ref)
			except ValueError:
				pass

	def unsubscribe_all(self, event_type: EventType | None = None) -> None:
		with self._lock:
			if event_type is None:
				self._subscribers.clear()
			else:
				self._subscribers.pop(event_type, None)

	def emit(self, event_type: EventType, data: Any = None, source: str | None = None) -> int:
		"""Emite un evento. Devuelve cuántos suscriptores lo recibieron."""
		if not self._enabled:
			return 0
		event = Event(type=event_type, data=data, source=source)
		self.lastEvents[event_type] = event
		with self._lock:
			refs = list(self._subscribers.get(event_type, []))
		notified = 0
		alive = []
		for ref in refs:
			callback = ref()
			if callback is None:
				continue
			alive.append(ref)
			try:
				callback(data)
				notified += 1
			except Exception:
				log.exception("Error en un suscriptor del evento %s", event_type.name)
		with self._lock:
			current = self._subscribers.get(event_type)
			if current is not None:
				# Se quitan las referencias muertas (conservando altas nuevas).
				self._subscribers[event_type] = [r for r in current if r() is not None]
		return notified

	def emit_async(self, event_type: EventType, data: Any = None, source: str | None = None) -> None:
		"""Emite el evento en un hilo aparte."""
		threading.Thread(target=self.emit, args=(event_type, data, source), daemon=True, name="zRadioBASS-evento").start()

	def enable(self) -> None:
		self._enabled = True

	def disable(self) -> None:
		self._enabled = False

	@property
	def is_enabled(self) -> bool:
		return self._enabled

	def get_subscriber_count(self, event_type: EventType) -> int:
		with self._lock:
			return sum(1 for r in self._subscribers.get(event_type, []) if r() is not None)


_global_event_bus: EventBus | None = None
_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
	"""Bus de eventos global (el que usan el complemento y los plugins)."""
	global _global_event_bus
	with _bus_lock:
		if _global_event_bus is None:
			_global_event_bus = EventBus()
		return _global_event_bus


def reset_event_bus() -> None:
	"""Olvida el bus global (al descargar el complemento)."""
	global _global_event_bus
	with _bus_lock:
		if _global_event_bus is not None:
			_global_event_bus.unsubscribe_all()
		_global_event_bus = None
