"""Acceso al modelo de objetos (COM) de Microsoft Office.

Word, Excel y PowerPoint publican su modelo de objetos a través de
``AccessibleObjectFromWindow(hwnd, OBJID_NATIVEOM)`` sobre la ventana del
documento. Outlook se obtiene con ``GetActiveObject`` (es de instancia única).

Las llamadas al modelo de objetos son síncronas entre procesos: si la
aplicación está ocupada (recalculando, con un diálogo modal...) pueden tardar
mucho. Para no bloquear nunca el hilo del núcleo (y para no congelar Excel,
NVDA #15281) todas las llamadas pasan por :func:`call`, que las ejecuta en un
hilo MTA propio con un tiempo máximo. Si se agota, se devuelve
:class:`OfficeBusy` y el núcleo sigue funcionando.
"""

from __future__ import annotations

import ctypes
import queue
import threading
from ctypes import wintypes
from typing import Any, Callable

from .. import winapi
from ..log import getLogger

log = getLogger("office")

OBJID_NATIVEOM = -16
#: IID de IDispatch.
_IID_IDISPATCH = "{00020400-0000-0000-C000-000000000046}"

#: Tiempo máximo por defecto de una llamada al modelo de objetos (segundos).
DEFAULT_TIMEOUT = 2.0


class OfficeBusy(Exception):
	"""La aplicación no respondió a tiempo."""


class OfficeUnavailable(Exception):
	"""No se pudo obtener el modelo de objetos."""


# ---------------------------------------------------------------- hilo de trabajo
class _Worker:
	"""Hilo MTA que ejecuta las llamadas COM con tiempo máximo.

	Si una llamada se queda colgada, el hilo se abandona (es de tipo daemon)
	y se crea otro para las siguientes.
	"""

	#: Hilos colgados (esperando a Office) como máximo: con más, las llamadas
	#: fallan enseguida con OfficeBusy en vez de crear hilos sin fin.
	MAX_HUNG_THREADS = 3

	def __init__(self) -> None:
		self._queue: queue.Queue | None = None
		self._thread: threading.Thread | None = None
		self._busy = False
		self._lock = threading.Lock()
		#: Colas (id) de los hilos abandonados que siguen dentro de una llamada.
		self._hung: set[int] = set()

	def _run(self, q: queue.Queue) -> None:
		try:
			self._runLoop(q)
		finally:
			with self._lock:
				self._hung.discard(id(q))

	def _runLoop(self, q: queue.Queue) -> None:
		try:
			import comtypes

			comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
		except Exception:
			log.debug("No se pudo iniciar COM en el hilo de Office", exc_info=True)
		while True:
			item = q.get()
			if item is None:
				break
			func, args, box, done = item
			if box.get("cancelled"):
				# Rev. 10.11: quien la pidió ya dejó de esperar (Office estaba ocupada):
				# no se ejecuta tarde (moverse por tablas o listas segundos después).
				done.set()
				continue
			try:
				box["result"] = func(*args)
			except BaseException as e:  # noqa: BLE001 - se reenvía al llamante
				box["error"] = e
			done.set()

	def _ensure(self) -> queue.Queue:
		with self._lock:
			if self._thread is None or not self._thread.is_alive() or self._busy:
				if self._busy and len(self._hung) >= self.MAX_HUNG_THREADS:
					raise OfficeBusy()
				if self._busy and self._queue is not None:
					# El hilo colgado termina cuando Office le responda (tras lo
					# que tuviera en cola); si no, quedaría esperando para siempre.
					self._hung.add(id(self._queue))
					self._queue.put(None)
				self._queue = queue.Queue()
				self._thread = threading.Thread(target=self._run, args=(self._queue,), name="tiresias-office", daemon=True)
				self._thread.start()
				self._busy = False
			return self._queue  # type: ignore[return-value]

	def call(self, func: Callable, args: tuple, timeout: float) -> Any:
		q = self._ensure()
		box: dict = {}
		done = threading.Event()
		q.put((func, args, box, done))
		if not done.wait(timeout):
			# El hilo queda ocupado con la llamada colgada: se usará otro.
			box["cancelled"] = True
			with self._lock:
				self._busy = True
			raise OfficeBusy()
		if "error" in box:
			raise box["error"]
		return box.get("result")

	def stop(self) -> None:
		with self._lock:
			if self._queue is not None:
				self._queue.put(None)
			self._thread = None
			self._queue = None


_worker = _Worker()


def call(func: Callable, *args: Any, timeout: float = DEFAULT_TIMEOUT) -> Any:
	"""Ejecuta ``func(*args)`` en el hilo de Office con tiempo máximo.

	Lanza :class:`OfficeBusy` si la aplicación no responde a tiempo y deja
	pasar las demás excepciones (``COMError`` incluido).
	"""
	return _worker.call(func, args, timeout)


def safeCall(func: Callable, *args: Any, default: Any = None, timeout: float = DEFAULT_TIMEOUT) -> Any:
	"""Como :func:`call`, pero devuelve ``default`` ante cualquier error."""
	try:
		return _worker.call(func, args, timeout)
	except OfficeBusy:
		log.debug("Office no respondió a tiempo")
		return default
	except Exception:
		log.debug("Error en la llamada a Office", exc_info=True)
		return default


def callAsync(func: Callable, *args: Any, callback: Callable[[Any], None] | None = None, onError: Callable[[BaseException], None] | None = None, timeout: float = DEFAULT_TIMEOUT) -> None:
	"""Ejecuta ``func(*args)`` en el hilo de Office sin bloquear a quien llama.

	El resultado se entrega a ``callback`` en el hilo del núcleo; si falla
	(o se agota el tiempo), se llama a ``onError(excepción)`` también en el
	núcleo. Es la forma de usar el modelo de objetos desde órdenes y eventos.
	"""
	from .. import queue_handler

	if not _asyncSlots.acquire(blocking=False):
		# Demasiadas llamadas esperando a una aplicación que no responde.
		if onError is not None:
			queue_handler.queueFunction(onError, OfficeBusy())
		return

	def runner() -> None:
		try:
			try:
				result = _worker.call(func, args, timeout)
			except BaseException as e:  # noqa: BLE001
				if onError is not None:
					queue_handler.queueFunction(onError, e)
				else:
					log.debug("Llamada a Office fallida: %r", e)
				return
			if callback is not None:
				queue_handler.queueFunction(callback, result)
		finally:
			_asyncSlots.release()

	threading.Thread(target=runner, name="tiresias-office-call", daemon=True).start()


#: Llamadas asíncronas en curso como máximo (cada una tiene su hilo).
MAX_ASYNC_CALLS = 8
_asyncSlots = threading.BoundedSemaphore(MAX_ASYNC_CALLS)


def busyMessage(error: BaseException) -> str:
	"""Mensaje para el usuario cuando una llamada al modelo de objetos falla."""
	from ..i18n import _

	if isinstance(error, OfficeBusy):
		return _("La aplicación está ocupada; inténtalo de nuevo")
	if isinstance(error, OfficeUnavailable):
		return _("No se puede acceder al documento")
	return _("No se pudo obtener la información")


def terminate() -> None:
	_worker.stop()


# ---------------------------------------------------------------- obtener el modelo
def _dispatch(punk) -> Any:
	from comtypes.client import dynamic

	return dynamic.Dispatch(punk)


_aofw = None


def _accessibleObjectFromWindow():
	"""``AccessibleObjectFromWindow`` con prototipo propio.

	Se carga una instancia propia de oleacc.dll: otros módulos fijan sus
	``argtypes`` para IAccessible en la instancia compartida de ``ctypes.oledll``.
	"""
	global _aofw
	if _aofw is None:
		fn = ctypes.OleDLL("oleacc").AccessibleObjectFromWindow
		fn.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
		_aofw = fn
	return _aofw


def nativeOMFromWindow(hwnd: int) -> Any:
	"""Objeto ``Window`` del modelo de objetos de la ventana de documento ``hwnd``.

	Se debe llamar dentro de :func:`call` (en el hilo de Office).
	"""
	import comtypes
	from comtypes.automation import IDispatch

	if not hwnd:
		raise OfficeUnavailable("sin ventana")
	ptr = ctypes.POINTER(IDispatch)()
	iid = comtypes.GUID(_IID_IDISPATCH)
	try:
		_accessibleObjectFromWindow()(wintypes.HWND(hwnd), wintypes.DWORD(OBJID_NATIVEOM & 0xFFFFFFFF), ctypes.byref(iid), ctypes.byref(ptr))
	except OSError as e:
		raise OfficeUnavailable(str(e)) from e
	if not ptr:
		raise OfficeUnavailable("modelo de objetos no disponible")
	return _dispatch(ptr)


def activeObject(progId: str) -> Any:
	"""Objeto activo registrado en la ROT (p. ej. ``Outlook.Application``)."""
	import comtypes.client

	try:
		obj = comtypes.client.GetActiveObject(progId, dynamic=True)
	except OSError as e:
		raise OfficeUnavailable(str(e)) from e
	if obj is None:
		raise OfficeUnavailable(progId)
	return obj


def findChildWindow(hwnd: int, className: str) -> int:
	"""Primera ventana descendiente de ``hwnd`` con la clase dada (o ``hwnd``)."""
	if not hwnd:
		return 0
	if winapi.getClassName(hwnd) == className:
		return hwnd
	found: list[int] = []

	def enum(child, lParam):
		if winapi.getClassName(child) == className:
			found.append(child)
			return False
		return True

	try:
		winapi.user32.EnumChildWindows(hwnd, winapi.WNDENUMPROC(enum), 0)
	except Exception:
		pass
	return found[0] if found else 0


def windowForObject(obj: Any, className: str) -> int:
	"""Ventana de clase ``className`` del objeto o de su ventana principal."""
	try:
		hwnd = obj.windowHandle
	except Exception:
		hwnd = 0
	if hwnd and winapi.getClassName(hwnd) == className:
		return hwnd
	h = hwnd
	guard = 0
	while h and guard < 30:
		if winapi.getClassName(h) == className:
			return h
		h = winapi.user32.GetParent(h) or 0
		guard += 1
	root = winapi.getAncestor(hwnd, winapi.GA_ROOT) if hwnd else winapi.getForegroundWindow()
	return findChildWindow(root, className)


# ---------------------------------------------------------------- utilidades
def comValue(v: Any) -> Any:
	"""Normaliza valores COM: ``None`` para vacíos y errores."""
	if v is None:
		return None
	return v


def columnLetters(col: int) -> str:
	"""1 → A, 27 → AA."""
	out = ""
	while col > 0:
		col, rem = divmod(col - 1, 26)
		out = chr(65 + rem) + out
	return out


def cellAddress(row: int, col: int) -> str:
	return f"{columnLetters(col)}{row}"


def pointsToCm(points: float) -> float:
	return float(points) * 2.54 / 72.0


def formatCm(points: float) -> str:
	from ..i18n import _

	cm = pointsToCm(points)
	text = f"{cm:.1f}".replace(".", ",")
	if text.endswith(",0"):
		text = text[:-2]
	return _("{n} cm").format(n=text)


def colorName(rgb: int, fmt: str | None = None) -> str:
	"""Nombre de un color BGR de Office (0xBBGGRR, como COLORREF).

	Sigue la opción ``documentFormatting.colorFormat`` (nombre, nombre y RGB,
	o nombre y hexadecimal, #8674) salvo que se indique ``fmt``.
	"""
	from ..formatting import colorName as _colorName

	try:
		rgb = int(rgb)
	except (TypeError, ValueError):
		return ""
	if rgb < 0 or rgb > 0xFFFFFF:
		return ""
	return _colorName(rgb, fmt)
