"""Envoltorios ctypes de la API de Windows que usa Tiresias.

Se centralizan aquí las declaraciones para no repetirlas por el código.
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t

# ---------------------------------------------------------------- constantes
WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
HC_ACTION = 0
WM_QUIT = 0x0012
WM_TIMER = 0x0113
WM_USER = 0x0400
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MOUSEWHEEL = 0x020A
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_CLOSE = 0x0010
WM_CLIPBOARDUPDATE = 0x031D

LLKHF_EXTENDED = 0x01
LLKHF_INJECTED = 0x10
LLKHF_ALTDOWN = 0x20
LLKHF_UP = 0x80
LLMHF_INJECTED = 0x01

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

#: Marca que Tiresias pone en ``dwExtraInfo`` de las teclas que inyecta.
TIRESIAS_INJECTION_MARK = 0x54495245  # "TIRE"
#: Teclas recibidas por acceso remoto: Tiresias las trata como pulsadas por el usuario.
REMOTE_INJECTION_MARK = 0x52454D54  # "REMT"

GA_PARENT = 1
GA_ROOT = 2
GA_ROOTOWNER = 3
SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOW = 5
SW_RESTORE = 9

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_CAPITAL = 0x14
VK_NUMLOCK = 0x90
VK_SCROLL = 0x91
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_INSERT = 0x2D

WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002

EVENT_SYSTEM_ALERT = 0x0002
EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_SYSTEM_MENUSTART = 0x0004
EVENT_SYSTEM_MENUEND = 0x0005
EVENT_SYSTEM_MENUPOPUPSTART = 0x0006
EVENT_SYSTEM_MENUPOPUPEND = 0x0007
EVENT_SYSTEM_SWITCHSTART = 0x0014
EVENT_SYSTEM_SWITCHEND = 0x0015
EVENT_SYSTEM_DESKTOPSWITCH = 0x0020
EVENT_SYSTEM_DIALOGSTART = 0x0010
EVENT_OBJECT_CREATE = 0x8000
EVENT_OBJECT_DESTROY = 0x8001
EVENT_OBJECT_SHOW = 0x8002
EVENT_OBJECT_HIDE = 0x8003
EVENT_OBJECT_FOCUS = 0x8005
EVENT_OBJECT_SELECTION = 0x8006
EVENT_OBJECT_STATECHANGE = 0x800A
EVENT_OBJECT_LOCATIONCHANGE = 0x800B
EVENT_OBJECT_NAMECHANGE = 0x800C
EVENT_OBJECT_DESCRIPTIONCHANGE = 0x800D
EVENT_OBJECT_VALUECHANGE = 0x800E
EVENT_OBJECT_LIVEREGIONCHANGED = 0x8019

OBJID_WINDOW = 0
OBJID_CLIENT = -4
OBJID_CARET = -8
CHILDID_SELF = 0

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


# --------------------------------------------------------------- estructuras
class POINT(ctypes.Structure):
	_fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class RECT(ctypes.Structure):
	_fields_ = [
		("left", wintypes.LONG),
		("top", wintypes.LONG),
		("right", wintypes.LONG),
		("bottom", wintypes.LONG),
	]


class KBDLLHOOKSTRUCT(ctypes.Structure):
	_fields_ = [
		("vkCode", wintypes.DWORD),
		("scanCode", wintypes.DWORD),
		("flags", wintypes.DWORD),
		("time", wintypes.DWORD),
		("dwExtraInfo", ULONG_PTR),
	]


class MSLLHOOKSTRUCT(ctypes.Structure):
	_fields_ = [
		("pt", POINT),
		("mouseData", wintypes.DWORD),
		("flags", wintypes.DWORD),
		("time", wintypes.DWORD),
		("dwExtraInfo", ULONG_PTR),
	]


class MOUSEINPUT(ctypes.Structure):
	_fields_ = [
		("dx", wintypes.LONG),
		("dy", wintypes.LONG),
		("mouseData", wintypes.DWORD),
		("dwFlags", wintypes.DWORD),
		("time", wintypes.DWORD),
		("dwExtraInfo", ULONG_PTR),
	]


class KEYBDINPUT(ctypes.Structure):
	_fields_ = [
		("wVk", wintypes.WORD),
		("wScan", wintypes.WORD),
		("dwFlags", wintypes.DWORD),
		("time", wintypes.DWORD),
		("dwExtraInfo", ULONG_PTR),
	]


class HARDWAREINPUT(ctypes.Structure):
	_fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
	_fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
	_anonymous_ = ("u",)
	_fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class GUITHREADINFO(ctypes.Structure):
	_fields_ = [
		("cbSize", wintypes.DWORD),
		("flags", wintypes.DWORD),
		("hwndActive", wintypes.HWND),
		("hwndFocus", wintypes.HWND),
		("hwndCapture", wintypes.HWND),
		("hwndMenuOwner", wintypes.HWND),
		("hwndMoveSize", wintypes.HWND),
		("hwndCaret", wintypes.HWND),
		("rcCaret", RECT),
	]


class SYSTEM_POWER_STATUS(ctypes.Structure):
	_fields_ = [
		("ACLineStatus", ctypes.c_byte),
		("BatteryFlag", ctypes.c_byte),
		("BatteryLifePercent", ctypes.c_byte),
		("SystemStatusFlag", ctypes.c_byte),
		("BatteryLifeTime", wintypes.DWORD),
		("BatteryFullLifeTime", wintypes.DWORD),
	]


class MSG(ctypes.Structure):
	_fields_ = [
		("hwnd", wintypes.HWND),
		("message", wintypes.UINT),
		("wParam", wintypes.WPARAM),
		("lParam", wintypes.LPARAM),
		("time", wintypes.DWORD),
		("pt", POINT),
	]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
WINEVENTPROC = ctypes.WINFUNCTYPE(
	None,
	wintypes.HANDLE,
	wintypes.DWORD,
	wintypes.HWND,
	wintypes.LONG,
	wintypes.LONG,
	wintypes.DWORD,
	wintypes.DWORD,
)
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

# --------------------------------------------------------------- prototipos
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.PeekMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SetWinEventHook.argtypes = [
	wintypes.DWORD,
	wintypes.DWORD,
	wintypes.HMODULE,
	WINEVENTPROC,
	wintypes.DWORD,
	wintypes.DWORD,
	wintypes.DWORD,
]
user32.SetWinEventHook.restype = wintypes.HANDLE
user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.InternalGetWindowText.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowEnabled.argtypes = [wintypes.HWND]
user32.WindowFromPoint.argtypes = [POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.GetKeyState.argtypes = [ctypes.c_int]
user32.GetKeyState.restype = ctypes.c_short
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetKeyboardState.argtypes = [ctypes.POINTER(ctypes.c_ubyte)]
user32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
user32.GetKeyboardLayout.restype = wintypes.HKL
user32.ToUnicodeEx.argtypes = [
	wintypes.UINT,
	wintypes.UINT,
	ctypes.POINTER(ctypes.c_ubyte),
	wintypes.LPWSTR,
	ctypes.c_int,
	wintypes.UINT,
	wintypes.HKL,
]
user32.MapVirtualKeyExW.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.HKL]
user32.MapVirtualKeyExW.restype = wintypes.UINT
user32.GetKeyNameTextW.argtypes = [wintypes.LONG, wintypes.LPWSTR, ctypes.c_int]
user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = LRESULT
user32.SendMessageTimeoutW.argtypes = [
	wintypes.HWND,
	wintypes.UINT,
	wintypes.WPARAM,
	wintypes.LPARAM,
	wintypes.UINT,
	wintypes.UINT,
	ctypes.POINTER(ULONG_PTR),
]
user32.SendMessageTimeoutW.restype = LRESULT
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumChildWindows.argtypes = [wintypes.HWND, WNDENUMPROC, wintypes.LPARAM]
user32.GetDesktopWindow.restype = wintypes.HWND
user32.GetShellWindow.restype = wintypes.HWND
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindowAsync.restype = wintypes.BOOL
user32.IsHungAppWindow.argtypes = [wintypes.HWND]
user32.IsHungAppWindow.restype = wintypes.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
user32.AddClipboardFormatListener.argtypes = [wintypes.HWND]
user32.RemoveClipboardFormatListener.argtypes = [wintypes.HWND]
user32.GetDpiForWindow.argtypes = [wintypes.HWND]
user32.GetDpiForWindow.restype = wintypes.UINT
user32.MessageBeep.argtypes = [wintypes.UINT]
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.GetCaretPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetFocus.restype = wintypes.HWND
user32.GetLastInputInfo.argtypes = [ctypes.c_void_p]

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.GetCurrentProcessId.restype = wintypes.DWORD
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetSystemPowerStatus.argtypes = [ctypes.POINTER(SYSTEM_POWER_STATUS)]
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.GetTickCount64.restype = ctypes.c_ulonglong


# --------------------------------------------------------------- utilidades
def getWindowText(hwnd: int) -> str:
	if not hwnd:
		return ""
	pid = wintypes.DWORD()
	tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
	if pid.value == os.getpid() and tid != kernel32.GetCurrentThreadId():
		# Ventana de Tiresias de otro hilo: GetWindowText le enviaría WM_GETTEXT y
		# esperaría a la interfaz aunque esté ocupada. El título guardado basta.
		buf = ctypes.create_unicode_buffer(1024)
		user32.InternalGetWindowText(hwnd, buf, 1024)
		return buf.value
	n = user32.GetWindowTextLengthW(hwnd)
	buf = ctypes.create_unicode_buffer(n + 2)
	user32.GetWindowTextW(hwnd, buf, n + 2)
	return buf.value


def getClassName(hwnd: int) -> str:
	if not hwnd:
		return ""
	buf = ctypes.create_unicode_buffer(256)
	user32.GetClassNameW(hwnd, buf, 256)
	return buf.value


def getWindowProcessId(hwnd: int) -> int:
	pid = wintypes.DWORD()
	user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
	return pid.value


def getWindowThreadId(hwnd: int) -> int:
	return user32.GetWindowThreadProcessId(hwnd, None)


#: pid -> (nombre, instante monotónico en que se leyó).
_processNameCache: dict[int, tuple[str, float]] = {}
#: Segundos que vale un nombre: Windows reutiliza los PID de procesos que
#: terminan, y un nombre viejo aplicaría otro módulo de aplicación (o daría por
#: buena la pantalla de bloqueo a otro proceso, ver a11y.system.isSecureObject).
PROCESS_NAME_TTL = 10.0


def getProcessImagePath(pid: int) -> str:
	h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
	if not h:
		return ""
	try:
		size = wintypes.DWORD(1024)
		buf = ctypes.create_unicode_buffer(size.value)
		if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
			return buf.value
		return ""
	finally:
		kernel32.CloseHandle(h)


def getProcessName(pid: int) -> str:
	"""Nombre del ejecutable sin extensión, en minúsculas (``notepad``)."""
	now = time.monotonic()
	cached = _processNameCache.get(pid)
	if cached is not None and now - cached[1] < PROCESS_NAME_TTL:
		return cached[0]
	path = getProcessImagePath(pid)
	name = os.path.splitext(os.path.basename(path))[0].lower() if path else ""
	if len(_processNameCache) >= 2000:
		# Se olvidan los caducados (y, si no basta, todos).
		for k in [k for k, v in _processNameCache.items() if now - v[1] >= PROCESS_NAME_TTL]:
			del _processNameCache[k]
		if len(_processNameCache) >= 2000:
			_processNameCache.clear()
	if name:
		_processNameCache[pid] = (name, now)
	else:
		_processNameCache.pop(pid, None)
	return name


def getForegroundWindow() -> int:
	return user32.GetForegroundWindow() or 0


def getAncestor(hwnd: int, flags: int = GA_ROOT) -> int:
	return user32.GetAncestor(hwnd, flags) or 0


def getWindowRect(hwnd: int) -> tuple[int, int, int, int]:
	r = RECT()
	user32.GetWindowRect(hwnd, ctypes.byref(r))
	return (r.left, r.top, r.right - r.left, r.bottom - r.top)


def getCursorPos() -> tuple[int, int]:
	p = POINT()
	user32.GetCursorPos(ctypes.byref(p))
	return (p.x, p.y)


def getGUIThreadInfo(threadId: int = 0) -> GUITHREADINFO | None:
	info = GUITHREADINFO()
	info.cbSize = ctypes.sizeof(GUITHREADINFO)
	if user32.GetGUIThreadInfo(threadId, ctypes.byref(info)):
		return info
	return None


def isKeyToggled(vk: int) -> bool:
	return bool(user32.GetKeyState(vk) & 1)


def isKeyDown(vk: int) -> bool:
	return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def sendInputs(inputs: list[INPUT]) -> int:
	if not inputs:
		return 0
	arr = (INPUT * len(inputs))(*inputs)
	return user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def makeKeyInput(vk: int, up: bool = False, extended: bool = False, scan: int = 0) -> INPUT:
	inp = INPUT()
	inp.type = INPUT_KEYBOARD
	inp.ki.wVk = vk
	inp.ki.wScan = scan or user32.MapVirtualKeyExW(vk, 0, None)
	flags = 0
	if up:
		flags |= KEYEVENTF_KEYUP
	if extended:
		flags |= KEYEVENTF_EXTENDEDKEY
	inp.ki.dwFlags = flags
	inp.ki.dwExtraInfo = TIRESIAS_INJECTION_MARK
	return inp


def makeUnicodeInput(ch: str, up: bool = False) -> INPUT:
	inp = INPUT()
	inp.type = INPUT_KEYBOARD
	inp.ki.wVk = 0
	inp.ki.wScan = ord(ch)
	inp.ki.dwFlags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
	inp.ki.dwExtraInfo = TIRESIAS_INJECTION_MARK
	return inp


def typeText(text: str) -> None:
	"""Escribe texto en la aplicación con foco mediante SendInput Unicode."""
	inputs: list[INPUT] = []
	for ch in text:
		if ch == "\n":
			inputs.append(makeKeyInput(0x0D))
			inputs.append(makeKeyInput(0x0D, up=True))
			continue
		inputs.append(makeUnicodeInput(ch))
		inputs.append(makeUnicodeInput(ch, up=True))
	sendInputs(inputs)


def mouseEvent(flags: int, x: int = 0, y: int = 0, data: int = 0) -> None:
	inp = INPUT()
	inp.type = INPUT_MOUSE
	inp.mi.dx = x
	inp.mi.dy = y
	inp.mi.mouseData = data
	inp.mi.dwFlags = flags
	inp.mi.dwExtraInfo = TIRESIAS_INJECTION_MARK
	sendInputs([inp])


#: Plazo para comprobar que una ventana responde antes de adjuntar su entrada.
RESPONSIVE_TIMEOUT_MS = 200


def windowResponds(hwnd: int, timeoutMs: int = RESPONSIVE_TIMEOUT_MS) -> bool:
	"""``True`` si el hilo de ``hwnd`` procesa mensajes (``WM_NULL`` con plazo).

	``IsHungAppWindow`` solo marca una aplicación tras unos 5 s sin responder;
	``SendMessageTimeout`` con ``SMTO_ABORTIFHUNG`` lo detecta en ``timeoutMs``.
	"""
	if not hwnd:
		return False
	try:
		if user32.IsHungAppWindow(hwnd):
			return False
		res = ULONG_PTR()
		return bool(user32.SendMessageTimeoutW(hwnd, 0x0000, 0, 0, 0x0002 | 0x0008, int(timeoutMs), ctypes.byref(res)))  # WM_NULL, SMTO_ABORTIFHUNG|SMTO_NOTIMEOUTIFNOTHUNG
	except Exception:
		return False


def setForegroundWindow(hwnd: int) -> bool:
	"""Trae una ventana al frente sorteando el bloqueo de primer plano.

	Nunca se bloquea por una aplicación colgada: solo se adjunta la entrada de
	la ventana activa si responde (:func:`windowResponds`) y, si la ventana a
	traer es de otro hilo, se muestra sin esperarla (``ShowWindowAsync``).
	"""
	if not hwnd:
		return False
	fg = getForegroundWindow()
	if fg == hwnd:
		return True
	curThread = kernel32.GetCurrentThreadId()
	fgThread = getWindowThreadId(fg) if fg else 0
	ownWindow = getWindowThreadId(hwnd) == curThread
	if not ownWindow and not windowResponds(hwnd):
		return False
	attached = False
	if fgThread and fgThread != curThread and windowResponds(fg):
		attached = bool(user32.AttachThreadInput(curThread, fgThread, True))
	try:
		if ownWindow:
			user32.ShowWindow(hwnd, SW_SHOW)
		else:
			user32.ShowWindowAsync(hwnd, SW_SHOW)
		user32.BringWindowToTop(hwnd)
		ok = bool(user32.SetForegroundWindow(hwnd))
	finally:
		if attached:
			user32.AttachThreadInput(curThread, fgThread, False)
	return ok


def getPowerStatus() -> SYSTEM_POWER_STATUS | None:
	s = SYSTEM_POWER_STATUS()
	if kernel32.GetSystemPowerStatus(ctypes.byref(s)):
		return s
	return None


# --------------------------------------------------------------- portapapeles
def getClipboardText() -> str | None:
	for _attempt in range(5):
		if user32.OpenClipboard(None):
			break
		kernel32.Sleep(20)
	else:
		return None
	try:
		if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
			return None
		h = user32.GetClipboardData(CF_UNICODETEXT)
		if not h:
			return None
		p = kernel32.GlobalLock(h)
		if not p:
			return None
		try:
			return ctypes.wstring_at(p)
		finally:
			kernel32.GlobalUnlock(h)
	finally:
		user32.CloseClipboard()


def setClipboardText(text: str) -> bool:
	data = ctypes.create_unicode_buffer(text)
	size = ctypes.sizeof(data)
	for _attempt in range(5):
		if user32.OpenClipboard(None):
			break
		kernel32.Sleep(20)
	else:
		return False
	try:
		user32.EmptyClipboard()
		h = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
		if not h:
			return False
		p = kernel32.GlobalLock(h)
		ctypes.memmove(p, data, size)
		kernel32.GlobalUnlock(h)
		return bool(user32.SetClipboardData(CF_UNICODETEXT, h))
	finally:
		user32.CloseClipboard()


kernel32.Sleep.argtypes = [wintypes.DWORD]
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = wintypes.LONG
user32.IsIconic.argtypes = [wintypes.HWND]
