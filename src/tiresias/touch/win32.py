"""Declaraciones Win32 propias del soporte táctil y un hilo con ventana.

Se usa una instancia propia de ``user32`` para no interferir con los
``argtypes`` que declaran otros módulos.
"""

from __future__ import annotations

import ctypes
import itertools
import threading
from ctypes import wintypes
from typing import Callable

from ..log import getLogger

log = getLogger("touch")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
LONG_PTR = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

# ---------------------------------------------------------------- constantes
WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
GWL_EXSTYLE = -20
LWA_ALPHA = 0x2
HWND_MESSAGE = -3
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
IDC_ARROW = 32512

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
SM_DIGITIZER = 94
SM_MAXIMUMTOUCHES = 95
NID_INTEGRATED_TOUCH = 0x01
NID_EXTERNAL_TOUCH = 0x02
NID_READY = 0x80

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_QUIT = 0x0012
WM_MOUSEACTIVATE = 0x0021
WM_DISPLAYCHANGE = 0x007E
WM_INPUT = 0x00FF
WM_TIMER = 0x0113
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
WM_MOUSEWHEEL = 0x020A
WM_POINTERUPDATE = 0x0245
WM_POINTERDOWN = 0x0246
WM_POINTERUP = 0x0247
WM_POINTERACTIVATE = 0x024B
WM_POINTERCAPTURECHANGED = 0x024C
WM_APP = 0x8000
SMTO_ABORTIFHUNG = 0x0002
MA_NOACTIVATE = 3
PA_NOACTIVATE = 3

POINTER_MESSAGE_FLAG_INCONTACT = 0x0004
POINTER_MESSAGE_FLAG_CANCELED = 0x8000
PT_TOUCH = 2
PT_PEN = 3

#: Firma que Windows pone en ``GetMessageExtraInfo`` de la entrada que
#: procede de un lápiz o de la pantalla táctil.
MI_WP_SIGNATURE = 0xFF515700
SIGNATURE_MASK = 0xFFFFFF00
TOKEN_QUERY = 0x0008
TokenUIAccess = 26
ANRUS_TOUCH_MODIFICATION_ACTIVE = 0x0000002
DWMWA_CLOAKED = 14

VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
VK_MBUTTON = 0x04


class POINT(ctypes.Structure):
	_fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class RECT(ctypes.Structure):
	_fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class MSG(ctypes.Structure):
	_fields_ = [
		("hwnd", wintypes.HWND),
		("message", wintypes.UINT),
		("wParam", wintypes.WPARAM),
		("lParam", wintypes.LPARAM),
		("time", wintypes.DWORD),
		("pt", POINT),
	]


class WNDCLASSEXW(ctypes.Structure):
	_fields_ = [
		("cbSize", wintypes.UINT),
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
		("hIconSm", wintypes.HICON),
	]


user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = wintypes.ATOM
user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
user32.CreateWindowExW.argtypes = [
	wintypes.DWORD,
	wintypes.LPCWSTR,
	wintypes.LPCWSTR,
	wintypes.DWORD,
	ctypes.c_int,
	ctypes.c_int,
	ctypes.c_int,
	ctypes.c_int,
	wintypes.HWND,
	wintypes.HMENU,
	wintypes.HINSTANCE,
	wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.SendMessageTimeoutW.argtypes = [
	wintypes.HWND,
	wintypes.UINT,
	wintypes.WPARAM,
	wintypes.LPARAM,
	wintypes.UINT,
	wintypes.UINT,
	ctypes.POINTER(ctypes.c_size_t),
]
user32.SendMessageTimeoutW.restype = LRESULT
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = LONG_PTR
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, LONG_PTR]
user32.SetWindowLongPtrW.restype = LONG_PTR
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
user32.SetTimer.restype = ctypes.c_size_t
user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
user32.LoadCursorW.restype = wintypes.HANDLE
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetMessageExtraInfo.restype = LONG_PTR
user32.SetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.HANDLE]
user32.RemovePropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
user32.RemovePropW.restype = wintypes.HANDLE
user32.GetPointerType.argtypes = [wintypes.UINT, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetTopWindow.argtypes = [wintypes.HWND]
user32.GetTopWindow.restype = wintypes.HWND
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
user32.WindowFromPoint.argtypes = [POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
user32.ChildWindowFromPointEx.argtypes = [wintypes.HWND, POINT, wintypes.UINT]
user32.ChildWindowFromPointEx.restype = wintypes.HWND
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.GetCurrentProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

_classCounter = itertools.count(1)


def loword(v: int) -> int:
	return v & 0xFFFF


def hiword(v: int) -> int:
	return (v >> 16) & 0xFFFF


def signedWord(v: int) -> int:
	v &= 0xFFFF
	return v - 0x10000 if v & 0x8000 else v


def pointFromLParam(lParam: int) -> tuple[int, int]:
	return signedWord(lParam), signedWord(lParam >> 16)


def virtualScreen() -> tuple[int, int, int, int]:
	"""(x, y, ancho, alto) del escritorio virtual (todos los monitores)."""
	gm = user32.GetSystemMetrics
	return gm(SM_XVIRTUALSCREEN), gm(SM_YVIRTUALSCREEN), gm(SM_CXVIRTUALSCREEN), gm(SM_CYVIRTUALSCREEN)


def touchHardware() -> tuple[bool, int]:
	"""(hay pantalla táctil lista, número máximo de contactos)."""
	try:
		digitizer = user32.GetSystemMetrics(SM_DIGITIZER)
		maxTouches = user32.GetSystemMetrics(SM_MAXIMUMTOUCHES)
	except Exception:
		return False, 0
	present = bool(digitizer & (NID_INTEGRATED_TOUCH | NID_EXTERNAL_TOUCH)) and bool(digitizer & NID_READY) and maxTouches > 0
	return present, maxTouches


def hasUiAccess() -> bool:
	"""``True`` si el proceso tiene el privilegio uiAccess (necesario para
	``RegisterPointerInputTarget``)."""
	advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
	advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
	advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
	token = wintypes.HANDLE()
	if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
		return False
	try:
		value = wintypes.DWORD()
		size = wintypes.DWORD()
		if not advapi32.GetTokenInformation(token, TokenUIAccess, ctypes.byref(value), ctypes.sizeof(value), ctypes.byref(size)):
			return False
		return bool(value.value)
	finally:
		kernel32.CloseHandle(token)


def isWindowCloaked(hwnd: int) -> bool:
	try:
		dwmapi = ctypes.WinDLL("dwmapi")
		val = wintypes.DWORD()
		res = dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), DWMWA_CLOAKED, ctypes.byref(val), ctypes.sizeof(val))
		return res == 0 and val.value != 0
	except Exception:
		return False


def mouseButtonsDown() -> bool:
	return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (VK_LBUTTON, VK_RBUTTON, VK_MBUTTON))


def cursorPos() -> tuple[int, int]:
	pt = POINT()
	user32.GetCursorPos(ctypes.byref(pt))
	return pt.x, pt.y


class WindowThread:
	"""Hilo con una ventana propia y su bucle de mensajes.

	Las subclases implementan :meth:`createWindow` (devuelve el HWND, en el
	hilo nuevo) y :meth:`wndProc`. :meth:`start` espera a que la ventana
	exista; :meth:`stop` la destruye y termina el hilo.
	"""

	threadName = "Táctil"

	def __init__(self) -> None:
		self.hwnd = 0
		self._thread: threading.Thread | None = None
		self._threadId = 0
		self._ready = threading.Event()
		self._error: BaseException | None = None
		self._proc = WNDPROC(self._wndProcWrapper)
		self._className = f"TiresiasTouch{next(_classCounter)}_{id(self):x}"
		self._atom = 0
		self.hInstance = kernel32.GetModuleHandleW(None)

	# ------------------------------------------------------------ ciclo de vida
	def start(self, timeout: float = 5.0) -> None:
		self._thread = threading.Thread(target=self._run, name=self.threadName, daemon=True)
		self._thread.start()
		self._ready.wait(timeout)
		if self._error is not None:
			err, self._error = self._error, None
			raise err
		if not self.hwnd:
			raise OSError("No se pudo crear la ventana táctil")

	def stop(self, timeout: float = 3.0) -> None:
		hwnd = self.hwnd
		if hwnd:
			user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
		if self._thread is not None and self._thread is not threading.current_thread():
			self._thread.join(timeout)
		self._thread = None

	@property
	def isRunning(self) -> bool:
		return self._thread is not None and self._thread.is_alive() and bool(self.hwnd)

	def post(self, msg: int, wParam: int = 0, lParam: int = 0) -> None:
		if self.hwnd:
			user32.PostMessageW(self.hwnd, msg, wParam, lParam)

	# ------------------------------------------------------------ hilo
	def createWindow(self) -> int:
		raise NotImplementedError

	def onDestroy(self) -> None:
		"""Limpieza en el hilo de la ventana justo antes de destruirla."""

	def wndProc(self, hwnd: int, msg: int, wParam: int, lParam: int) -> int | None:
		"""Devuelve el resultado o ``None`` para usar ``DefWindowProc``."""
		return None

	def _registerClass(self, cursor: bool = False) -> None:
		wc = WNDCLASSEXW()
		wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
		wc.lpfnWndProc = self._proc
		wc.hInstance = self.hInstance
		wc.lpszClassName = self._className
		if cursor:
			wc.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(IDC_ARROW))
		self._atom = user32.RegisterClassExW(ctypes.byref(wc))
		if not self._atom:
			raise ctypes.WinError(ctypes.get_last_error())

	def _run(self) -> None:
		self._threadId = kernel32.GetCurrentThreadId()
		try:
			self.hwnd = self.createWindow() or 0
		except BaseException as e:  # noqa: BLE001 - se reenvía a start()
			self._error = e
			self.hwnd = 0
		finally:
			self._ready.set()
		if not self.hwnd:
			self._unregister()
			return
		msg = MSG()
		while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
			user32.TranslateMessage(ctypes.byref(msg))
			user32.DispatchMessageW(ctypes.byref(msg))
		self.hwnd = 0
		self._unregister()

	def _unregister(self) -> None:
		if self._atom:
			user32.UnregisterClassW(self._className, self.hInstance)
			self._atom = 0

	def _wndProcWrapper(self, hwnd, msg, wParam, lParam):
		try:
			if msg == WM_CLOSE:
				try:
					self.onDestroy()
				finally:
					user32.DestroyWindow(hwnd)
				return 0
			if msg == WM_DESTROY:
				user32.PostQuitMessage(0)
				return 0
			res = self.wndProc(hwnd, msg, wParam, lParam)
			if res is not None:
				return res
		except Exception:
			log.exception("Error en la ventana táctil (mensaje 0x%x)", msg)
		return user32.DefWindowProcW(hwnd, msg, wParam, lParam)


def callSafely(func: Callable, *args) -> None:
	try:
		func(*args)
	except Exception:
		log.exception("Error en el soporte táctil")
