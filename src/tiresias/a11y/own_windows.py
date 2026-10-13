"""Objetos MSAA de las ventanas del propio Tiresias, leídos en el hilo de la interfaz.

Las ventanas de Tiresias (menú, Opciones, mensajes, paleta de órdenes,
visores…) son de wxPython y viven en el hilo principal; el núcleo trabaja en
su propio hilo. Si el núcleo usara MSAA directamente con esas ventanas, cada
llamada sería un ``SendMessage`` al hilo de la interfaz (``WM_GETOBJECT``,
``WM_GETTEXT``…) sin tiempo máximo:

- con la interfaz ocupada (importando la configuración de NVDA, guardando las
  Opciones…) el núcleo se quedaba esperando, mudo, todo ese tiempo, y el
  vigilante no puede cancelar un ``SendMessage``;
- dentro de un mensaje enviado (una llamada «de entrada síncrona») algunos
  controles (RichEdit) no pueden hacer llamadas COM y fallan con
  ``RPC_E_CANTCALLOUT_ININPUTSYNCCALL`` (0x8001010D).

Aquí, en cambio, todo el acceso MSAA a una ventana del hilo de la interfaz se
ejecuta EN ese hilo: el núcleo envía la tarea con ``PostMessage`` a una
ventana de mensajes propia y espera el resultado con un tiempo máximo
(:data:`CALL_TIMEOUT`). Así las llamadas son directas (el mismo hilo y el
mismo apartamento COM, como hace NVDA, cuyo núcleo es el hilo de la interfaz)
y el núcleo nunca se bloquea:

- si la interfaz no responde a tiempo, la llamada falla con
  :class:`GuiBusyError` (subclase de ``OSError``, que el código MSAA ya trata
  como «sin dato») y queda un **cortacircuitos**: mientras la tarea atrasada
  no termine, las llamadas siguientes fallan al instante (un evento no
  acumula esperas). Cuando la interfaz se libera, se vuelve a comprobar el
  foco por si se perdió algún evento;
- los punteros COM de estos objetos nunca salen del hilo de la interfaz: el
  núcleo solo ve :class:`OwnAccessible`, que reenvía cada atributo o método al
  hilo de la interfaz y envuelve los punteros que devuelve. Al liberarse, el
  puntero se suelta también en el hilo de la interfaz;
- las ventanas del propio proceso que son de otros hilos (la ventana de
  anuncios para Narrador, la superposición táctil…) no se leen: son
  auxiliares, sin nada que anunciar.
"""

from __future__ import annotations

import ctypes
import itertools
import os
import threading
import time
from ctypes import POINTER, wintypes
from typing import Any, Callable

import comtypes
from comtypes import IUnknown

from ..log import getLogger

log = getLogger("ownWindows")

#: Tiempo máximo (s) que el núcleo espera a la interfaz en cada llamada.
CALL_TIMEOUT = 0.4

WM_APP = 0x8000
WM_RUN = WM_APP + 0x2A1
WM_RELEASE = WM_APP + 0x2A2
HWND_MESSAGE = -3

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.DefWindowProcW.restype = ctypes.c_ssize_t
_user32.CreateWindowExW.argtypes = [
	wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
	wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.PostMessageW.restype = wintypes.BOOL
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.DestroyWindow.argtypes = [wintypes.HWND]
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class _WNDCLASSW(ctypes.Structure):
	_fields_ = [
		("style", wintypes.UINT),
		("lpfnWndProc", _WNDPROC),
		("cbClsExtra", ctypes.c_int),
		("cbWndExtra", ctypes.c_int),
		("hInstance", wintypes.HINSTANCE),
		("hIcon", wintypes.HICON),
		("hCursor", wintypes.HANDLE),
		("hbrBackground", wintypes.HBRUSH),
		("lpszMenuName", wintypes.LPCWSTR),
		("lpszClassName", wintypes.LPCWSTR),
	]


_CLASS_NAME = "TiresiasOwnA11y"
_OWN_PID = os.getpid()
#: Clase base de todos los punteros COM de comtypes.
_COM_POINTER = next(c for c in POINTER(IUnknown).__mro__ if c.__name__ == "_compointer_base")


class GuiBusyError(OSError):
	"""La interfaz no ha respondido a tiempo (o no existe): no se lee la ventana propia."""


# ---------------------------------------------------------------------- estado
_guiThreadId = 0
_hwnd = 0
_procRef: Any = None
# RLock: un __del__ (liberación de un puntero) puede ocurrir con el cerrojo tomado.
_lock = threading.RLock()
_ids = itertools.count(1)
_pending: dict[int, "_Call"] = {}
#: Tarea que superó el tiempo máximo y aún no ha terminado (cortacircuitos).
_late: "_Call | None" = None
#: Se descartó algo por estar la interfaz ocupada (al liberarse se mira el foco).
_lostWhileBusy = False
_toRelease: list = []
_releasePosted = False
#: Estadística para el diagnóstico: llamadas, tiempos agotados y rechazos.
stats = {"calls": 0, "timeouts": 0, "rejected": 0}


class _Call:
	__slots__ = ("func", "args", "done", "result", "error", "key", "since", "reposted")

	def __init__(self, func: Callable, args: tuple) -> None:
		self.func = func
		self.args = args
		self.key = 0
		#: Instante en que superó el tiempo máximo (cortacircuitos).
		self.since = 0.0
		self.reposted = False
		self.done = threading.Event()
		self.result: Any = None
		self.error: BaseException | None = None

	def run(self) -> None:
		try:
			self.result = self.func(*self.args)
		except BaseException as e:  # noqa: BLE001 - se entrega al hilo que espera
			self.error = e
		finally:
			# Sin referencias a los argumentos (punteros COM) fuera de este hilo.
			self.func = None
			self.args = ()
			self.done.set()


# ---------------------------------------------------------------------- ventana de mensajes
def _wndProc(hwnd: int, msg: int, wParam: int, lParam: int) -> int:
	if msg == WM_RUN:
		with _lock:
			call = _pending.pop(int(wParam), None)
		if call is not None:
			call.run()
			_afterLateCall(call)
		return 0
	if msg == WM_RELEASE:
		_drainReleases()
		return 0
	return _user32.DefWindowProcW(hwnd, msg, wParam, lParam)


def initialize() -> None:
	"""Crea la ventana de mensajes (en el hilo de la interfaz, antes del bucle principal)."""
	global _guiThreadId, _hwnd, _procRef
	if _hwnd:
		return
	_guiThreadId = _kernel32.GetCurrentThreadId()
	_procRef = _WNDPROC(_wndProc)
	hInst = _kernel32.GetModuleHandleW(None)
	wc = _WNDCLASSW()
	wc.lpfnWndProc = _procRef
	wc.hInstance = hInst
	wc.lpszClassName = _CLASS_NAME
	if not _user32.RegisterClassW(ctypes.byref(wc)):
		err = ctypes.get_last_error()
		if err != 1410:  # ERROR_CLASS_ALREADY_EXISTS
			log.error("No se pudo registrar la clase de la ventana de accesibilidad propia (%d)", err)
			return
	_hwnd = _user32.CreateWindowExW(0, _CLASS_NAME, "", 0, 0, 0, 0, 0, HWND_MESSAGE, None, hInst, None) or 0
	if not _hwnd:
		log.error("No se pudo crear la ventana de accesibilidad propia (%d)", ctypes.get_last_error())


def terminate() -> None:
	"""Destruye la ventana de mensajes (hilo de la interfaz)."""
	global _hwnd
	if _hwnd and isGuiThread():
		_drainReleases()
		_user32.DestroyWindow(_hwnd)
	_hwnd = 0


# ---------------------------------------------------------------------- consultas
def isGuiThread() -> bool:
	return bool(_guiThreadId) and _kernel32.GetCurrentThreadId() == _guiThreadId


def guiThreadId() -> int:
	return _guiThreadId


def isOwnWindow(hwnd: int) -> bool:
	"""``True`` si la ventana es del proceso de Tiresias."""
	if not hwnd:
		return False
	pid = wintypes.DWORD()
	_user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
	return pid.value == _OWN_PID


def windowThread(hwnd: int) -> int:
	return int(_user32.GetWindowThreadProcessId(hwnd, None) or 0) if hwnd else 0


def isGuiWindow(hwnd: int) -> bool:
	"""``True`` si la ventana es del hilo de la interfaz de Tiresias."""
	return bool(hwnd) and bool(_guiThreadId) and windowThread(hwnd) == _guiThreadId


def mustDelegate(hwnd: int) -> bool:
	"""``True`` si los objetos MSAA de ``hwnd`` se tienen que leer en el hilo de la interfaz.

	Es así para toda ventana del propio proceso, salvo desde el propio hilo de
	la interfaz o si la ventana de mensajes no existe (pruebas sin interfaz).
	"""
	return bool(_hwnd) and isOwnWindow(hwnd) and not isGuiThread()


def isBusy() -> bool:
	"""El cortacircuitos está abierto (una tarea atrasada aún no ha terminado)."""
	late = _late
	return late is not None and not late.done.is_set()


# ---------------------------------------------------------------------- ejecución
def call(func: Callable, *args: Any, timeout: float | None = None) -> Any:
	"""Ejecuta ``func(*args)`` en el hilo de la interfaz y devuelve su resultado.

	Desde el propio hilo de la interfaz se ejecuta directamente. Las
	excepciones de ``func`` se vuelven a lanzar aquí. Si la interfaz no
	responde en ``timeout`` (por defecto :data:`CALL_TIMEOUT`) se lanza
	:class:`GuiBusyError`.
	"""
	global _late, _lostWhileBusy
	if isGuiThread():
		return func(*args)
	if not _hwnd:
		raise GuiBusyError("La interfaz de Tiresias no está disponible")
	stats["calls"] += 1
	c = _Call(func, args)
	with _lock:
		if _late is not None and not _late.done.is_set():
			if not _checkLate(_late):
				stats["rejected"] += 1
				_lostWhileBusy = True
				raise GuiBusyError("La interfaz de Tiresias está ocupada")
		key = next(_ids)
		c.key = key
		_pending[key] = c
	if not _user32.PostMessageW(_hwnd, WM_RUN, key, 0):
		with _lock:
			_pending.pop(key, None)
		raise GuiBusyError("No se pudo enviar la tarea a la interfaz")
	if not c.done.wait(CALL_TIMEOUT if timeout is None else timeout):
		with _lock:
			if not c.done.is_set():
				c.since = time.monotonic()
				_late = c
				_lostWhileBusy = True
				stats["timeouts"] += 1
		if not c.done.is_set():
			log.debug("La interfaz no responde: se deja de leer sus ventanas hasta que termine")
			raise GuiBusyError("La interfaz de Tiresias no responde")
	if c.error is not None:
		err, c.error = c.error, None
		raise err
	result, c.result = c.result, None
	return result


def _checkLate(late: _Call) -> bool:
	"""(Con ``_lock``) ``True`` si el cortacircuitos se puede cerrar ya.

	Si la tarea atrasada lleva más de 1 s, se vuelve a enviar por si el mensaje
	se perdió (un bucle modal que no lo despachó); tras 10 s se da por perdida.
	"""
	global _late
	waited = time.monotonic() - late.since
	if waited > 10.0:
		_pending.pop(late.key, None)
		_late = None
		log.debug("Tarea de la interfaz descartada tras %.0f s sin respuesta", waited)
		return True
	if waited > 1.0 and not late.reposted:
		late.reposted = True
		_user32.PostMessageW(_hwnd, WM_RUN, late.key, 0)
	return False


def _afterLateCall(call_: _Call) -> None:
	"""Hilo de la interfaz: si terminó la tarea atrasada, se cierra el cortacircuitos."""
	global _late, _lostWhileBusy
	with _lock:
		if _late is not call_:
			return
		_late = None
		lost, _lostWhileBusy = _lostWhileBusy, False
	if lost:
		# Algún evento de una ventana propia se descartó: se vuelve a mirar el foco.
		try:
			from .. import queue_handler
			from . import winevents

			queue_handler.queueFunction(winevents.scheduleFocusCheck, 30)
		except Exception:
			log.debug("No se pudo programar la comprobación del foco", exc_info=True)


# ---------------------------------------------------------------------- liberación
def _release(ptr: Any) -> None:
	"""Suelta un puntero COM en el hilo de la interfaz."""
	global _releasePosted
	if ptr is None or isGuiThread() or not _hwnd:
		return
	with _lock:
		_toRelease.append(ptr)
		post = not _releasePosted
		_releasePosted = True
	if post and not _user32.PostMessageW(_hwnd, WM_RELEASE, 0, 0):
		with _lock:
			_releasePosted = False


def _drainReleases() -> None:
	global _releasePosted
	with _lock:
		items = list(_toRelease)
		_toRelease.clear()
		_releasePosted = False
	# Los punteros se liberan aquí, al salir de esta función (hilo de la interfaz).
	del items


# ---------------------------------------------------------------------- envoltorios
def wrap(value: Any) -> Any:
	"""(Hilo de la interfaz) Envuelve los punteros COM de un resultado."""
	if isinstance(value, _COM_POINTER):
		return OwnAccessible(value) if value else None
	if isinstance(value, tuple):
		return tuple(wrap(v) for v in value)
	if isinstance(value, list):
		return [wrap(v) for v in value]
	return value


def _getAttr(ptr: Any, name: str) -> Any:
	return wrap(getattr(ptr, name))


def _callAttr(ptr: Any, name: str, args: tuple, kwargs: dict) -> Any:
	return wrap(getattr(ptr, name)(*args, **kwargs))


class _OwnMethod:
	"""Método (o propiedad con parámetros) de un :class:`OwnAccessible`."""

	__slots__ = ("_owner", "_name")

	def __init__(self, owner: "OwnAccessible", name: str) -> None:
		self._owner = owner
		self._name = name

	def __call__(self, *args: Any, **kwargs: Any) -> Any:
		return call(_callAttr, self._owner._ptr, self._name, args, kwargs)


class OwnAccessible:
	"""Puntero COM de un objeto de una ventana de la interfaz de Tiresias.

	Se crea en el hilo de la interfaz. Desde cualquier hilo, cada atributo se
	lee y cada método se ejecuta en el hilo de la interfaz (con su tiempo
	máximo); los punteros que devuelven se envuelven igual.
	"""

	__slots__ = ("_ptr", "addr", "isIAccessible", "__weakref__")

	def __init__(self, ptr: Any) -> None:
		from . import msaa

		self._ptr = ptr
		self.isIAccessible = isinstance(ptr, POINTER(msaa.IAccessible))
		#: Dirección de su IUnknown: la identidad COM del objeto.
		try:
			unk = ptr.QueryInterface(IUnknown)
			self.addr = ctypes.cast(unk, ctypes.c_void_p).value or 0
		except (comtypes.COMError, ValueError, AttributeError, OSError):
			self.addr = ctypes.cast(ptr, ctypes.c_void_p).value or 0

	@property
	def raw(self) -> Any:
		"""Puntero real: SOLO se puede usar en el hilo de la interfaz."""
		return self._ptr

	def __getattr__(self, name: str) -> Any:
		if name.startswith("__"):
			raise AttributeError(name)
		desc = getattr(type(self._ptr), name, None)
		if desc is None:
			raise AttributeError(name)
		if isinstance(desc, property):
			return call(_getAttr, self._ptr, name)
		return _OwnMethod(self, name)

	def __bool__(self) -> bool:
		return True

	def __repr__(self) -> str:
		return f"<OwnAccessible 0x{self.addr:x}>"

	def __del__(self) -> None:
		try:
			ptr = self._ptr
		except AttributeError:
			return
		self._ptr = None
		try:
			_release(ptr)
		except Exception:
			pass


#: Marca de «el mismo objeto» en los resultados de :func:`runWith`.
SAME = object()


def runWith(pacc: OwnAccessible, func: Callable, *args: Any) -> Any:
	"""Ejecuta ``func(punteroReal, *args)`` en el hilo de la interfaz.

	El resultado se envuelve; si contiene el mismo puntero recibido se
	devuelve el propio ``pacc`` (para conservar la identidad).
	"""

	def run(ptr: Any) -> Any:
		return _wrapKeeping(func(ptr, *args), ptr)

	res = call(run, pacc._ptr)
	return _restoreSame(res, pacc)


def _wrapKeeping(value: Any, same: Any) -> Any:
	if value is same:
		return SAME
	if isinstance(value, tuple):
		return tuple(_wrapKeeping(v, same) for v in value)
	if isinstance(value, list):
		return [_wrapKeeping(v, same) for v in value]
	return wrap(value)


def _restoreSame(value: Any, pacc: OwnAccessible) -> Any:
	if value is SAME:
		return pacc
	if isinstance(value, tuple):
		return tuple(_restoreSame(v, pacc) for v in value)
	if isinstance(value, list):
		return [_restoreSame(v, pacc) for v in value]
	return value


def fromHwnd(hwnd: int, func: Callable, *args: Any) -> Any:
	"""Crea en el hilo de la interfaz el objeto de una ventana propia.

	``func(hwnd, *args)`` se ejecuta en el hilo de la interfaz y su resultado
	(punteros incluidos) se envuelve. Devuelve ``None`` si la ventana es de
	otro hilo del proceso o si la interfaz no responde.
	"""
	if not isGuiWindow(hwnd):
		return None

	def run() -> Any:
		return wrap(func(hwnd, *args))

	try:
		return call(run)
	except GuiBusyError:
		return None
