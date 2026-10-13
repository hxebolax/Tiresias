"""Lector de pantalla falso para las pruebas de convivencia.

Crea una ventana oculta de la clase y el título indicados (por ejemplo
``wxWindowClassNR`` / ``NVDA`` o ``JFWUI2`` / ``JAWS``) y espera hasta que
se cierre su entrada estándar o pasen los segundos indicados. Las pruebas lo
ejecutan con una copia del intérprete de Python renombrada como ``nvda.exe``
o ``jfw.exe``, para que el nombre del proceso sea el del lector.

Uso: fake_reader.py <clase> <título> [segundos]

También funciona con una copia de ``pythonw.exe`` (sin entrada ni salida
estándar), como la que inicia el guardián en ``tests/test_relanzar_lector.py``.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
import threading
import time

u32 = ctypes.windll.user32
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
u32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
u32.DefWindowProcW.restype = ctypes.c_ssize_t
u32.CreateWindowExW.restype = wt.HWND
u32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]


class WNDCLASSW(ctypes.Structure):
	_fields_ = [
		("style", wt.UINT),
		("lpfnWndProc", WNDPROC),
		("cbClsExtra", ctypes.c_int),
		("cbWndExtra", ctypes.c_int),
		("hInstance", wt.HINSTANCE),
		("hIcon", wt.HICON),
		("hCursor", wt.HANDLE),
		("hbrBackground", wt.HBRUSH),
		("lpszMenuName", wt.LPCWSTR),
		("lpszClassName", wt.LPCWSTR),
	]


def main() -> int:
	cls = sys.argv[1]
	title = sys.argv[2]
	seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 60.0
	proc = WNDPROC(lambda h, m, w, lp: u32.DefWindowProcW(h, m, w, lp))
	wc = WNDCLASSW()
	wc.lpfnWndProc = proc
	wc.lpszClassName = cls
	if not u32.RegisterClassW(ctypes.byref(wc)):
		return 2
	hwnd = u32.CreateWindowExW(0x80, cls, title, 0x80000000, 0, 0, 0, 0, None, None, None, None)  # WS_EX_TOOLWINDOW, WS_POPUP
	if not hwnd:
		return 3
	if sys.stdout is not None:
		print("listo", flush=True)
	done = threading.Event()

	def watchStdin() -> None:
		try:
			sys.stdin.read()
		except Exception:
			pass
		done.set()

	# Con pythonw (lo inicia el guardián de Tiresias) no hay entrada estándar:
	# termina al pasar los segundos indicados o cuando la prueba lo cierra.
	if sys.stdin is not None:
		threading.Thread(target=watchStdin, daemon=True).start()
	deadline = time.monotonic() + seconds
	msg = wt.MSG()
	while not done.is_set() and time.monotonic() < deadline:
		while u32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
			u32.TranslateMessage(ctypes.byref(msg))
			u32.DispatchMessageW(ctypes.byref(msg))
		time.sleep(0.05)
	u32.DestroyWindow(hwnd)
	return 0


if __name__ == "__main__":
	sys.exit(main())
