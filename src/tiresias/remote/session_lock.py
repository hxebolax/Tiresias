"""Aviso de bloqueo y desbloqueo de la sesión de Windows.

Una ventana oculta (nunca visible) en un hilo propio se registra con
``WTSRegisterSessionNotification`` y recibe ``WM_WTSSESSION_CHANGE``. Lo usa
el acceso remoto para devolver el teclado al equipo local cuando el usuario
bloquea el equipo (``Windows+L``, Control+Alt+Supr, suspensión...).
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

from ..log import getLogger

log = getLogger("remote")

WM_WTSSESSION_CHANGE = 0x02B1
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_QUIT = 0x0012
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
NOTIFY_FOR_THIS_SESSION = 0

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
	_fields_ = [
		("style", wintypes.UINT),
		("lpfnWndProc", WNDPROC),
		("cbClsExtra", ctypes.c_int),
		("cbWndExtra", ctypes.c_int),
		("hInstance", wintypes.HINSTANCE),
		("hIcon", wintypes.HICON),
		("hCursor", wintypes.HANDLE),
		("hbrBackground", wintypes.HBRUSH),
		("lpszMenuName", wintypes.LPCWSTR),
		("lpszClassName", wintypes.LPCWSTR),
	]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
_user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.DefWindowProcW.restype = LRESULT
_user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
_user32.RegisterClassW.restype = wintypes.ATOM
_user32.CreateWindowExW.argtypes = [
	wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
	ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
	wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.DestroyWindow.argtypes = [wintypes.HWND]
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
_user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
_user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
_user32.PostQuitMessage.argtypes = [ctypes.c_int]
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_wtsapi32.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
_wtsapi32.WTSRegisterSessionNotification.restype = wintypes.BOOL
_wtsapi32.WTSUnRegisterSessionNotification.argtypes = [wintypes.HWND]
_wtsapi32.WTSUnRegisterSessionNotification.restype = wintypes.BOOL

_CLASS_NAME = "TiresiasAvisoSesion"
ERROR_CLASS_ALREADY_EXISTS = 1410

#: Ventanas vivas: hwnd -> monitor. El procedimiento de ventana es uno solo para
#: todo el módulo y nunca se libera (la clase de ventana se registra una vez y
#: Windows guarda su dirección: un procedimiento por monitor quedaría liberado
#: al destruir el primero y la segunda ventana llamaría a memoria liberada).
_monitors: dict[int, "SessionLockMonitor"] = {}
_monitorsLock = threading.Lock()
_classLock = threading.Lock()
_classRegistered = False


def _moduleWndProc(hwnd: int, msg: int, wParam: int, lParam: int) -> int:
	with _monitorsLock:
		monitor = _monitors.get(hwnd or 0)
	if monitor is not None:
		return monitor._wndProc(hwnd, msg, wParam, lParam)
	return _user32.DefWindowProcW(hwnd, msg, wParam, lParam)


#: Referencia permanente al procedimiento (no se libera nunca).
_WNDPROC = WNDPROC(_moduleWndProc)


def _ensureClass(hinst: int) -> bool:
	global _classRegistered
	with _classLock:
		if _classRegistered:
			return True
		wc = WNDCLASSW()
		wc.lpfnWndProc = _WNDPROC
		wc.hInstance = hinst
		wc.lpszClassName = _CLASS_NAME
		if not _user32.RegisterClassW(ctypes.byref(wc)):
			err = ctypes.get_last_error()
			if err != ERROR_CLASS_ALREADY_EXISTS:
				log.warning("No se pudo registrar la clase de la ventana de aviso de sesión (%d)", err)
				return False
		_classRegistered = True
		return True


class SessionLockMonitor:
	"""Llama a ``callback(locked: bool)`` desde su propio hilo al bloquear o desbloquear."""

	def __init__(self, callback: Callable[[bool], None]) -> None:
		self.callback = callback
		self.hwnd: int | None = None
		self.registered = False
		self._thread: threading.Thread | None = None
		self._ready = threading.Event()

	def start(self) -> bool:
		self._thread = threading.Thread(target=self._run, name="Aviso de sesión", daemon=True)
		self._thread.start()
		self._ready.wait(5)
		return self.registered

	def stop(self) -> None:
		if self.hwnd:
			_user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
		if self._thread is not None:
			self._thread.join(3)
		self._thread = None

	def _run(self) -> None:
		hinst = _kernel32.GetModuleHandleW(None)
		if not _ensureClass(hinst):
			self._ready.set()
			return
		# Ventana emergente sin WS_VISIBLE: nunca se muestra ni recibe el foco.
		hwnd = _user32.CreateWindowExW(0, _CLASS_NAME, "Tiresias - aviso de sesión", 0x80000000, 0, 0, 0, 0, None, None, hinst, None)
		if not hwnd:
			log.warning("No se pudo crear la ventana de aviso de sesión (%d)", ctypes.get_last_error())
			self._ready.set()
			return
		with _monitorsLock:
			_monitors[hwnd] = self
		self.hwnd = hwnd
		self.registered = bool(_wtsapi32.WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_THIS_SESSION))
		if not self.registered:
			log.warning("WTSRegisterSessionNotification falló (%d)", ctypes.get_last_error())
		self._ready.set()
		msg = wintypes.MSG()
		try:
			while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
				_user32.TranslateMessage(ctypes.byref(msg))
				_user32.DispatchMessageW(ctypes.byref(msg))
		finally:
			with _monitorsLock:
				if _monitors.get(hwnd) is self:
					del _monitors[hwnd]
			self.hwnd = None

	def _wndProc(self, hwnd: int, msg: int, wParam: int, lParam: int) -> int:
		try:
			if msg == WM_WTSSESSION_CHANGE and wParam in (WTS_SESSION_LOCK, WTS_SESSION_UNLOCK):
				self.callback(wParam == WTS_SESSION_LOCK)
				return 0
			if msg == WM_CLOSE:
				if self.registered:
					_wtsapi32.WTSUnRegisterSessionNotification(hwnd)
					self.registered = False
				_user32.DestroyWindow(hwnd)
				return 0
			if msg == WM_DESTROY:
				_user32.PostQuitMessage(0)
				return 0
		except Exception:
			log.exception("Error en el aviso de sesión")
		return _user32.DefWindowProcW(hwnd, msg, wParam, lParam)
