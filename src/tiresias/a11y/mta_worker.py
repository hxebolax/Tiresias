"""Hilo de trabajo COM (apartamento MTA) para tareas que pueden bloquearse.

Registrar o quitar manejadores de eventos UIA contacta con los proveedores de
las aplicaciones: con una aplicación colgada, la llamada puede tardar lo que
tarde su tiempo de espera. NVDA hace estos registros en su hilo MTA de UIA,
nunca en el hilo principal; aquí se hacen en un hilo propio con una cola, en
orden, para que el núcleo no se quede esperando.

Las tareas se ejecutan en el orden en que se envían; las excepciones se
registran y no detienen el hilo.
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable

from ..log import getLogger

log = getLogger("mtaWorker")


class MTAWorker:
	"""Hilo con apartamento MTA que ejecuta funciones en orden."""

	def __init__(self, name: str) -> None:
		self.name = name
		self._queue: "queue.Queue[tuple[Callable, tuple, dict] | None]" = queue.Queue()
		self._thread: threading.Thread | None = None
		self._lock = threading.Lock()
		#: Se ejecuta en el propio hilo (pruebas o sin hilo): ``submit`` llama directamente.
		self.synchronous = False

	@property
	def isRunning(self) -> bool:
		t = self._thread
		return t is not None and t.is_alive()

	def isWorkerThread(self) -> bool:
		t = self._thread
		return t is not None and threading.current_thread() is t

	def start(self) -> None:
		with self._lock:
			if self.isRunning:
				return
			self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
			self._thread.start()

	def submit(self, func: Callable, *args: Any, **kwargs: Any) -> None:
		"""Ejecuta ``func`` en el hilo (arranca el hilo si hace falta)."""
		if self.synchronous or self.isWorkerThread():
			self._call(func, args, kwargs)
			return
		if not self.isRunning:
			self.start()
		self._queue.put((func, args, kwargs))

	def stop(self, timeout: float = 3.0) -> bool:
		"""Termina el hilo tras las tareas pendientes. ``True`` si terminó a tiempo."""
		t = self._thread
		if t is None or not t.is_alive():
			return True
		self._queue.put(None)
		t.join(timeout)
		if t.is_alive():
			log.warning("El hilo %s no terminó en %.0f s (una aplicación no responde)", self.name, timeout)
			return False
		self._thread = None
		return True

	def wait(self, timeout: float = 3.0) -> bool:
		"""Espera a que se hayan ejecutado las tareas enviadas hasta ahora."""
		if self.synchronous or not self.isRunning or self.isWorkerThread():
			return True
		done = threading.Event()
		self._queue.put((done.set, (), {}))
		return done.wait(timeout)

	@staticmethod
	def _call(func: Callable, args: tuple, kwargs: dict) -> None:
		try:
			func(*args, **kwargs)
		except Exception:
			log.exception("Error en la tarea %r", func)

	def _run(self) -> None:
		try:
			import comtypes

			comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
		except OSError:
			pass
		while True:
			item = self._queue.get()
			if item is None:
				break
			func, args, kwargs = item
			self._call(func, args, kwargs)
