"""Cola de tareas del hilo del núcleo.

Casi todo el trabajo de Tiresias (eventos de accesibilidad, órdenes de
teclado, voz) se ejecuta en un único hilo, el «hilo del núcleo». Otros hilos
(ganchos de teclado, eventos UIA, audio, interfaz gráfica) encolan funciones
aquí con :func:`queueFunction`.
"""

from __future__ import annotations

import contextlib
import queue
import threading
import time
from typing import Any, Callable, Iterator

from .log import getLogger

log = getLogger("queue")

_queue: "queue.Queue[tuple[Callable, tuple, dict] | None]" = queue.Queue()
_coreThreadId: int | None = None
#: Marca de tiempo del inicio de la tarea en curso o, sin tarea, de la última
#: vez que el núcleo volvió a la cola (vigilancia). Se renueva en CADA tarea:
#: un lote largo de tareas cortas (ráfaga de eventos) no es un bloqueo.
lastPumpTime = time.monotonic()
#: ``True`` mientras el núcleo está ejecutando una tarea (o una fase vigilada
#: del arranque o del cierre, ver :func:`watchedPhase`).
busy = False
#: Descripción de lo que ejecuta el núcleo ahora (diagnóstico del vigilante).
currentTask: str | None = None
#: Límites de cada vuelta de :func:`pump` (tareas y segundos).
MAX_BATCH_TASKS = 200
MAX_BATCH_SECONDS = 0.5
_timers: list[tuple[float, int, Callable, tuple, dict]] = []
_timerLock = threading.Lock()
_timerSeq = 0


def setCoreThread() -> None:
	global _coreThreadId
	_coreThreadId = threading.get_ident()


def isCoreThread() -> bool:
	return threading.get_ident() == _coreThreadId


def queueFunction(func: Callable, *args: Any, **kwargs: Any) -> None:
	"""Ejecuta ``func`` en el hilo del núcleo lo antes posible."""
	if _coreThreadId is None:
		# Núcleo no iniciado (pruebas): ejecución directa.
		try:
			func(*args, **kwargs)
		except Exception:
			log.exception("Error en función encolada")
		return
	_queue.put((func, args, kwargs))


def callLater(delayMs: int, func: Callable, *args: Any, **kwargs: Any) -> int:
	"""Programa ``func`` en el hilo del núcleo tras ``delayMs`` milisegundos."""
	global _timerSeq
	with _timerLock:
		_timerSeq += 1
		_timers.append((time.monotonic() + delayMs / 1000.0, _timerSeq, func, args, kwargs))
		_timers.sort(key=lambda t: t[0])
		timerId = _timerSeq
	_queue.put((_noop, (), {}))
	return timerId


def cancelCallLater(timerId: int) -> None:
	with _timerLock:
		for i, t in enumerate(_timers):
			if t[1] == timerId:
				del _timers[i]
				return


def _noop() -> None:
	pass


def _nextTimeout() -> float:
	with _timerLock:
		if not _timers:
			return 0.1
		return max(0.0, min(0.1, _timers[0][0] - time.monotonic()))


def _runDueTimers() -> None:
	now = time.monotonic()
	due = []
	with _timerLock:
		while _timers and _timers[0][0] <= now:
			due.append(_timers.pop(0))
	for _t, _id, func, args, kwargs in due:
		_execute(func, args, kwargs)


def _describe(func: Any) -> str:
	try:
		name = getattr(func, "__qualname__", None) or getattr(func, "__name__", None) or repr(func)
		module = getattr(func, "__module__", "") or ""
		return f"{module}.{name}" if module else str(name)
	except Exception:
		return "?"


def _execute(func: Callable, args: tuple, kwargs: dict) -> None:
	global busy, lastPumpTime, currentTask
	# El vigilante mide desde el inicio de ESTA tarea (no del lote).
	lastPumpTime = time.monotonic()
	currentTask = None if func is _noop else _describe(func)
	busy = True
	try:
		func(*args, **kwargs)
	except Exception:
		log.exception("Error ejecutando %r", func)
	finally:
		busy = False
		currentTask = None


@contextlib.contextmanager
def watchedPhase(name: str) -> Iterator[None]:
	"""Marca un paso del arranque o del cierre como trabajo vigilado del núcleo.

	El arranque (``core._initializeCore``) y el cierre (``core._terminateCore``)
	no pasan por la cola: sin esto el vigilante no veía sus bloqueos y seguía
	enviando latidos al guardián. Cada paso se mide por separado.
	"""
	global busy, lastPumpTime, currentTask
	lastPumpTime = time.monotonic()
	currentTask = name
	busy = True
	try:
		yield
	finally:
		busy = False
		currentTask = None
		lastPumpTime = time.monotonic()


def frozenFor() -> float:
	"""Segundos que lleva el núcleo en la tarea o el paso actual (0 si está libre)."""
	return time.monotonic() - lastPumpTime if busy else 0.0


def pump(onCycle: Callable[[], None] | None = None) -> bool:
	"""Procesa la cola una vez. Devuelve ``False`` al recibir la orden de salir."""
	global lastPumpTime
	try:
		item = _queue.get(timeout=_nextTimeout())
	except queue.Empty:
		item = (_noop, (), {})
	lastPumpTime = time.monotonic()
	if item is None:
		return False
	func, args, kwargs = item
	batchStart = time.monotonic()
	_execute(func, args, kwargs)
	# Vacía lo que haya acumulado sin bloquear (con límite de tareas y de
	# tiempo: los temporizadores y el ciclo no deben esperar a una ráfaga).
	for _i in range(MAX_BATCH_TASKS):
		if time.monotonic() - batchStart >= MAX_BATCH_SECONDS:
			break
		try:
			item = _queue.get_nowait()
		except queue.Empty:
			break
		if item is None:
			return False
		func, args, kwargs = item
		_execute(func, args, kwargs)
	_runDueTimers()
	if onCycle:
		try:
			onCycle()
		except Exception:
			log.exception("Error en ciclo del núcleo")
	lastPumpTime = time.monotonic()
	return True


def requestQuit() -> None:
	_queue.put(None)


def pendingCount() -> int:
	return _queue.qsize()
