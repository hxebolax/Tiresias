"""Captura de la entrada táctil de la pantalla.

Hay dos formas de recibir los toques antes que las aplicaciones:

1. **Destino de entrada de puntero** (``RegisterPointerInputTarget``): Windows
   envía todos los toques a una ventana de mensajes de Tiresias. Es lo que usa
   NVDA instalado, pero exige el privilegio *uiAccess*, que una copia portable
   (sin firmar y fuera de «Archivos de programa») no tiene. Se intenta solo si
   el proceso tiene uiAccess.
2. **Superposición transparente** (la forma normal en Tiresias): una ventana
   casi invisible (opacidad 1/255) que cubre todo el escritorio virtual, siempre
   encima y que nunca se activa (``WS_EX_TOPMOST | WS_EX_LAYERED |
   WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE``). Recibe los mensajes ``WM_POINTER*``
   de los dedos (y del lápiz) y los pasa al reconocedor de gestos. Al
   responderlos, Windows no los convierte en clics para las aplicaciones.

Como la superposición también taparía el ratón, en cuanto se mueve el ratón
real (o Tiresias hace un clic simulado) la ventana se vuelve transparente a la
entrada (``WS_EX_TRANSPARENT``) y deja pasar el ratón; tras unos segundos sin
actividad del ratón vuelve a capturar los toques.

Limitaciones: las ventanas que Windows coloca por encima de las demás ventanas
«siempre encima» (menú Inicio, centro de notificaciones, teclado táctil y
otras interfaces del sistema) reciben los toques directamente.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Callable

from . import win32 as W
from .recognizer import GestureRecognizer, RecognizerSettings, TouchEvent

log = W.log

TIMER_RECOGNIZER = 1
TIMER_MAINTAIN = 2
WM_APP_PASSTHROUGH = W.WM_APP + 1
MAINTAIN_MS = 250
#: Segundos sin mover el ratón para volver a capturar los toques.
MOUSE_IDLE_SECONDS = 2.0
#: Cada cuánto se vuelve a poner la superposición encima de todo.
TOPMOST_SECONDS = 2.0

#: Desactiva la respuesta visual y los gestos del sistema sobre la ventana
#: (mantener pulsado = clic derecho, deslizamientos de lápiz...).
_TABLET_PROPERTY = "MicrosoftTabletPenServiceProperty"
_TABLET_FLAGS = 0x00000001 | 0x00000008 | 0x00000010 | 0x00010000 | 0x00080000 | 0x00100000


#: Segundos sin volver a la cola del núcleo para considerarlo bloqueado.
FROZEN_SECONDS = 3.0


def coreFrozen() -> bool:
	"""¿El núcleo lleva más de :data:`FROZEN_SECONDS` sin atender la cola?"""
	from .. import queue_handler

	return bool(queue_handler.busy) and time.monotonic() - queue_handler.lastPumpTime > FROZEN_SECONDS


def _declarePointerApi() -> bool:
	try:
		W.user32.RegisterPointerInputTarget.argtypes = [wintypes.HWND, wintypes.DWORD]
		W.user32.UnregisterPointerInputTarget.argtypes = [wintypes.HWND, wintypes.DWORD]
		return True
	except AttributeError:
		return False


class TouchInputWindow(W.WindowThread):
	"""Ventana que recibe los toques y los convierte en gestos.

	:param onEvents: se llama en el hilo de la ventana con la lista de gestos
		reconocidos (debe limitarse a encolar trabajo).
	:param useTarget: usar ``RegisterPointerInputTarget`` (requiere uiAccess).
	:param show: mostrar la superposición (``False`` en pruebas).
	:param passthrough: crearla ya transparente a la entrada (pruebas).
	"""

	threadName = "Táctil"

	def __init__(
		self,
		onEvents: Callable[[list[TouchEvent]], None],
		settings: RecognizerSettings | None = None,
		useTarget: bool = False,
		show: bool = True,
		passthrough: bool = False,
		sequenceFilter: Callable[[str, int], bool] | None = None,
	) -> None:
		super().__init__()
		self.recognizer = GestureRecognizer(settings, sequenceFilter)
		self.onEvents = onEvents
		self.mode = "target" if useTarget else "overlay"
		self._show = show
		self._passthrough = passthrough
		#: Creada transparente a propósito (pruebas): no vuelve a capturar sola.
		self._forcePassthrough = passthrough
		self._lastMouseActivity = time.monotonic() if passthrough else 0.0
		self._lastCursor: tuple[int, int] | None = None
		self._lastTopmost = 0.0
		self._screen = W.virtualScreen()
		self._registeredTarget = False

	# ------------------------------------------------------------ estado
	@property
	def isCapturing(self) -> bool:
		"""``True`` si la superposición está tapando la pantalla ahora mismo."""
		return self.mode == "overlay" and bool(self.hwnd) and self._show and not self._passthrough

	@property
	def isPassthrough(self) -> bool:
		return self._passthrough

	def exStyle(self) -> int:
		return int(W.user32.GetWindowLongPtrW(self.hwnd, W.GWL_EXSTYLE)) if self.hwnd else 0

	# ------------------------------------------------------------ creación
	def createWindow(self) -> int:
		self._registerClass(cursor=True)
		if self.mode == "target":
			return self._createTargetWindow()
		return self._createOverlay()

	def _createTargetWindow(self) -> int:
		if not _declarePointerApi():
			raise OSError("RegisterPointerInputTarget no está disponible")
		hwnd = W.user32.CreateWindowExW(0, self._className, "Tiresias: entrada táctil", 0, 0, 0, 0, 0, W.HWND_MESSAGE, None, self.hInstance, None)
		if not hwnd:
			raise ctypes.WinError(ctypes.get_last_error())
		if not W.user32.RegisterPointerInputTarget(hwnd, W.PT_TOUCH):
			err = ctypes.get_last_error()
			W.user32.DestroyWindow(hwnd)
			raise OSError(err, "RegisterPointerInputTarget falló")
		self._registeredTarget = True
		try:
			oleacc = ctypes.WinDLL("oleacc")
			oleacc.AccSetRunningUtilityState(wintypes.HWND(hwnd), W.ANRUS_TOUCH_MODIFICATION_ACTIVE, W.ANRUS_TOUCH_MODIFICATION_ACTIVE)
		except Exception:
			log.debug("AccSetRunningUtilityState no disponible", exc_info=True)
		log.info("Entrada táctil: destino de puntero registrado (uiAccess)")
		return hwnd

	def _createOverlay(self) -> int:
		x, y, w, h = self._screen
		ex = W.WS_EX_TOPMOST | W.WS_EX_LAYERED | W.WS_EX_TOOLWINDOW | W.WS_EX_NOACTIVATE
		if self._passthrough:
			ex |= W.WS_EX_TRANSPARENT
		hwnd = W.user32.CreateWindowExW(ex, self._className, "Tiresias: superposición táctil", W.WS_POPUP, x, y, w, h, None, None, self.hInstance, None)
		if not hwnd:
			raise ctypes.WinError(ctypes.get_last_error())
		# Opacidad 1 de 255: invisible a la vista pero recibe los toques.
		W.user32.SetLayeredWindowAttributes(hwnd, 0, 1, W.LWA_ALPHA)
		W.user32.SetPropW(hwnd, _TABLET_PROPERTY, wintypes.HANDLE(_TABLET_FLAGS))
		self._lastCursor = W.cursorPos()
		if self._show:
			W.user32.ShowWindow(hwnd, W.SW_SHOWNOACTIVATE)
			self._raise(hwnd)
		W.user32.SetTimer(hwnd, TIMER_MAINTAIN, MAINTAIN_MS, None)
		log.info("Entrada táctil: superposición creada en %d,%d (%dx%d)", x, y, w, h)
		return hwnd

	def _raise(self, hwnd: int) -> None:
		W.user32.SetWindowPos(hwnd, W.HWND_TOPMOST, 0, 0, 0, 0, W.SWP_NOMOVE | W.SWP_NOSIZE | W.SWP_NOACTIVATE)
		self._lastTopmost = time.monotonic()

	def onDestroy(self) -> None:
		hwnd = self.hwnd
		if not hwnd:
			return
		W.user32.KillTimer(hwnd, TIMER_RECOGNIZER)
		W.user32.KillTimer(hwnd, TIMER_MAINTAIN)
		if self._registeredTarget:
			try:
				oleacc = ctypes.WinDLL("oleacc")
				oleacc.AccSetRunningUtilityState(wintypes.HWND(hwnd), W.ANRUS_TOUCH_MODIFICATION_ACTIVE, 0)
			except Exception:
				pass
			W.user32.UnregisterPointerInputTarget(hwnd, W.PT_TOUCH)
			self._registeredTarget = False
		if self.mode == "overlay":
			W.user32.RemovePropW(hwnd, _TABLET_PROPERTY)

	# ------------------------------------------------------------ ratón
	def allowMouseThrough(self) -> None:
		"""Deja pasar el ratón unos segundos (seguro desde cualquier hilo).

		Lo usan los clics simulados de Tiresias para que no los reciba la
		superposición. Desde otro hilo se espera a que la ventana lo aplique.
		"""
		self._lastMouseActivity = time.monotonic()
		if self.mode != "overlay" or not self.hwnd:
			return
		if W.kernel32.GetCurrentThreadId() == self._threadId:
			self._setTransparent(True)
			return
		result = ctypes.c_size_t()
		W.user32.SendMessageTimeoutW(self.hwnd, WM_APP_PASSTHROUGH, 1, 0, W.SMTO_ABORTIFHUNG, 500, ctypes.byref(result))

	def _setTransparent(self, on: bool) -> None:
		"""Solo en el hilo de la ventana."""
		if self.mode != "overlay" or not self.hwnd:
			self._passthrough = on
			return
		style = int(W.user32.GetWindowLongPtrW(self.hwnd, W.GWL_EXSTYLE))
		new = (style | W.WS_EX_TRANSPARENT) if on else (style & ~W.WS_EX_TRANSPARENT)
		if new != style:
			W.user32.SetWindowLongPtrW(self.hwnd, W.GWL_EXSTYLE, new)
		if on != self._passthrough:
			log.debug("Superposición táctil: %s", "deja pasar el ratón" if on else "captura los toques")
		self._passthrough = on

	def _maintain(self, hwnd: int) -> None:
		now = time.monotonic()
		frozen = coreFrozen()
		if frozen and not self._passthrough and not self.recognizer.isTouching:
			# Núcleo bloqueado: los gestos no se atenderían; los toques pasan a
			# las aplicaciones hasta que se recupere.
			log.warning("Núcleo bloqueado: la superposición táctil deja pasar los toques")
			self._setTransparent(True)
		if self._passthrough:
			pos = W.cursorPos()
			if pos != self._lastCursor or W.mouseButtonsDown():
				self._lastCursor = pos
				self._lastMouseActivity = now
			elif now - self._lastMouseActivity >= MOUSE_IDLE_SECONDS and not self._forcePassthrough and not frozen:
				self._lastCursor = pos
				self._setTransparent(False)
		if not self.recognizer.isTouching:
			screen = W.virtualScreen()
			if screen != self._screen:
				self._screen = screen
				if self.recognizer.settings.bounds is not None:
					# Los gestos de borde se miden sobre la superposición.
					self.recognizer.settings.bounds = screen
				x, y, w, h = screen
				W.user32.SetWindowPos(hwnd, W.HWND_TOPMOST, x, y, w, h, W.SWP_NOACTIVATE)
				self._lastTopmost = now
			elif self._show and now - self._lastTopmost >= TOPMOST_SECONDS:
				self._raise(hwnd)

	def _onMouseMessage(self, msg: int) -> int:
		extra = int(W.user32.GetMessageExtraInfo()) & 0xFFFFFFFF
		if (extra & W.SIGNATURE_MASK) == W.MI_WP_SIGNATURE:
			# Ratón simulado por Windows a partir de un toque o del lápiz.
			return 0
		if msg == W.WM_MOUSEMOVE:
			pos = W.cursorPos()
			if pos == self._lastCursor:
				# Windows envía movimientos sin desplazamiento (p. ej. al
				# aparecer la ventana bajo el puntero): no es el usuario.
				return 0
			self._lastCursor = pos
		self._lastMouseActivity = time.monotonic()
		self._setTransparent(True)
		return 0

	# ------------------------------------------------------------ toques
	def _schedule(self, hwnd: int) -> None:
		deadline = self.recognizer.nextDeadline()
		if deadline is None:
			W.user32.KillTimer(hwnd, TIMER_RECOGNIZER)
			return
		ms = max(1, int((deadline - time.monotonic()) * 1000) + 1)
		W.user32.SetTimer(hwnd, TIMER_RECOGNIZER, ms, None)

	def _deliver(self, events: list[TouchEvent]) -> None:
		if events:
			try:
				self.onEvents(events)
			except Exception:
				log.exception("Error entregando gestos táctiles")

	def _onPointer(self, hwnd: int, msg: int, wParam: int, lParam: int) -> int | None:
		pid = W.loword(wParam)
		flags = W.hiword(wParam)
		ptype = wintypes.DWORD(0)
		if W.user32.GetPointerType(pid, ctypes.byref(ptype)) and ptype.value not in (W.PT_TOUCH, W.PT_PEN):
			return None
		x, y = W.pointFromLParam(lParam)
		t = time.monotonic()
		rec = self.recognizer
		if flags & W.POINTER_MESSAGE_FLAG_CANCELED:
			events = rec.cancel(t)
		elif msg == W.WM_POINTERDOWN:
			events = rec.down(pid, x, y, t)
		elif msg == W.WM_POINTERUP or not (flags & W.POINTER_MESSAGE_FLAG_INCONTACT):
			events = rec.up(pid, x, y, t)
		else:
			events = rec.move(pid, x, y, t)
		self._deliver(events)
		self._schedule(hwnd)
		return 0

	def wndProc(self, hwnd: int, msg: int, wParam: int, lParam: int) -> int | None:
		if msg in (W.WM_POINTERDOWN, W.WM_POINTERUPDATE, W.WM_POINTERUP):
			return self._onPointer(hwnd, msg, wParam, lParam)
		if msg == W.WM_POINTERCAPTURECHANGED:
			self.recognizer.cancel(time.monotonic())
			self._schedule(hwnd)
			return 0
		if msg == WM_APP_PASSTHROUGH:
			self._lastMouseActivity = time.monotonic()
			self._setTransparent(bool(wParam))
			return 1
		if msg == W.WM_POINTERACTIVATE:
			return W.PA_NOACTIVATE
		if msg == W.WM_MOUSEACTIVATE:
			return W.MA_NOACTIVATE
		if msg == W.WM_TIMER:
			if wParam == TIMER_RECOGNIZER:
				W.user32.KillTimer(hwnd, TIMER_RECOGNIZER)
				self._deliver(self.recognizer.poll(time.monotonic()))
				self._schedule(hwnd)
			elif wParam == TIMER_MAINTAIN:
				self._maintain(hwnd)
			return 0
		if self.mode == "overlay" and msg in (W.WM_MOUSEMOVE, W.WM_LBUTTONDOWN, W.WM_RBUTTONDOWN, W.WM_MBUTTONDOWN, W.WM_MOUSEWHEEL):
			return self._onMouseMessage(msg)
		if msg == W.WM_DISPLAYCHANGE and self.mode == "overlay":
			self._screen = (0, 0, 0, 0)
			self._maintain(hwnd)
			return 0
		return None
