"""Hilos de ganchos del sistema.

Hay dos hilos, cada uno con su bucle de mensajes:

- **Ganchos de bajo nivel** (:class:`LowLevelHooks`, hilo «GanchoTeclado»):
  solo los ganchos ``WH_KEYBOARD_LL`` y ``WH_MOUSE_LL``. No hace nada más,
  para que una avalancha de eventos de accesibilidad no retrase nunca una
  pulsación (si una retrollamada tarda más que ``LowLevelHooksTimeout``,
  Windows quita el gancho sin avisar). Las retrollamadas deben ser muy
  rápidas: solo deciden si una tecla se captura y encolan el trabajo en el
  hilo del núcleo.
- **Eventos WinEvent** (:class:`HookThread`, hilo «Hooks»): los ganchos
  ``SetWinEventHook`` de los eventos de accesibilidad.

Un vigilante ligero (hilo «VigilanteGancho») comprueba cada pocos segundos
si Windows ha registrado entrada del usuario que los ganchos no han visto
(``GetLastInputInfo``). Si es así, pide al hilo de los ganchos que los
reinstale. ``UnhookWindowsHookEx`` falla con un gancho que Windows ya había
quitado: así se distingue una pérdida real (se avisa con la voz) de una
falsa alarma (la reinstalación es inocua y silenciosa).
"""

from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes
from typing import Callable

from .. import winapi
from ..log import getLogger

log = getLogger("hooks")

KeyCallback = Callable[[int, int, int, bool, bool], bool]
MouseCallback = Callable[[int, int, int, bool], bool]

#: Mensaje de hilo que pide reinstalar los ganchos de bajo nivel.
WM_REINSTALL_HOOKS = 0x8000 + 0x154  # WM_APP + 0x154
#: Cada cuánto mira el vigilante si los ganchos siguen vivos (s).
CHECK_SECONDS = 2.0
#: Entrada sin ver por los ganchos durante más de esto (ms): sospecha.
LOST_MS = 1500
#: Edad mínima de la última entrada para juzgarla (ms): la retrollamada de
#: una pulsación muy reciente puede estar esperando todavía.
SETTLE_MS = 500
#: Sospechas seguidas necesarias antes de reinstalar.
SUSPICIONS_TO_ACT = 2
#: Espera máxima entre reinstalaciones silenciosas (falsas alarmas) (s).
MAX_BACKOFF_SECONDS = 60.0
ERROR_INVALID_HOOK_HANDLE = 1404

# Funciones propias (una instancia aparte de user32: sus firmas no afectan al resto).
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class LASTINPUTINFO(ctypes.Structure):
	_fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


_user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
_user32.GetLastInputInfo.restype = wintypes.BOOL
_kernel32.GetTickCount.restype = wintypes.DWORD
_user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_user32.OpenInputDesktop.restype = wintypes.HANDLE
_user32.CloseDesktop.argtypes = [wintypes.HANDLE]
_user32.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
_user32.GetUserObjectInformationW.restype = wintypes.BOOL
_user32.IsHungAppWindow.argtypes = [wintypes.HWND]
_user32.IsHungAppWindow.restype = wintypes.BOOL
UOI_NAME = 2
DESKTOP_READOBJECTS = 0x0001


def tickCount() -> int:
	return int(_kernel32.GetTickCount())


def lastInputTick() -> int | None:
	"""Instante (``GetTickCount``) de la última entrada del usuario en la sesión."""
	info = LASTINPUTINFO()
	info.cbSize = ctypes.sizeof(LASTINPUTINFO)
	if not _user32.GetLastInputInfo(ctypes.byref(info)):
		return None
	return int(info.dwTime)


def isNormalInputDesktop() -> bool:
	"""``True`` si la entrada va al escritorio normal («Default»).

	En el escritorio seguro (UAC, inicio de sesión, Control+Alt+Supr) los
	ganchos de Tiresias no ven las teclas, y eso no es una pérdida del gancho.
	"""
	h = _user32.OpenInputDesktop(0, False, DESKTOP_READOBJECTS)
	if not h:
		return False
	try:
		buf = ctypes.create_unicode_buffer(64)
		needed = wintypes.DWORD()
		if not _user32.GetUserObjectInformationW(h, UOI_NAME, buf, ctypes.sizeof(buf), ctypes.byref(needed)):
			return False
		return buf.value.lower() == "default"
	finally:
		_user32.CloseDesktop(h)


def hookSeemsLost(lastInput: int | None, lastHook: int, now: int, lostMs: int = LOST_MS, settleMs: int = SETTLE_MS) -> bool:
	"""¿Hubo entrada del usuario que los ganchos no vieron?

	Todos los valores son ``GetTickCount`` (32 bits, con vuelta a cero cada
	49,7 días: las restas se hacen módulo 2^32).
	"""
	if lastInput is None:
		return False
	ahead = (lastInput - lastHook) & 0xFFFFFFFF
	if ahead == 0 or ahead >= 0x80000000:
		# Los ganchos vieron la última entrada (o algo posterior).
		return False
	if ahead < lostMs:
		return False
	age = (now - lastInput) & 0xFFFFFFFF
	return settleMs <= age < 0x80000000


def _announce(message: str) -> None:
	"""Aviso por voz desde cualquier hilo (se habla en el hilo del núcleo)."""
	from .. import queue_handler

	def speak() -> None:
		from .. import speech

		try:
			from ..audio import tones

			tones.beep(440, 80)
		except Exception:
			pass
		speech.speakMessage(message)

	try:
		queue_handler.queueFunction(speak)
	except Exception:
		log.debug("No se pudo anunciar %r", message, exc_info=True)


# ====================================================================== bajo nivel
class LowLevelHooks:
	"""Ganchos de teclado y ratón de bajo nivel, en un hilo dedicado."""

	threadName = "GanchoTeclado"

	def __init__(self) -> None:
		self._thread: threading.Thread | None = None
		self._threadId = 0
		self._ready = threading.Event()
		self.keyCallback: KeyCallback | None = None
		self.mouseCallback: MouseCallback | None = None
		self._kbHook = None
		self._mouseHook = None
		self._keyProc = winapi.HOOKPROC(self._onKey)
		self._mouseProc = winapi.HOOKPROC(self._onMouse)
		#: ``time`` de la última llamada a cualquiera de los dos ganchos.
		self.lastHookTick = 0
		#: Reinstalaciones hechas tras una pérdida real (diagnóstico).
		self.recoveredCount = 0
		#: Reinstalaciones silenciosas (falsas alarmas).
		self.silentReinstalls = 0
		self._installFailedAnnounced = False
		self._watchThread: threading.Thread | None = None
		self._stopWatch = threading.Event()
		self._suspicions = 0
		self._backoffUntil = 0.0
		self._backoff = 0.0

	@property
	def isRunning(self) -> bool:
		return self._thread is not None and self._thread.is_alive()

	@property
	def isInstalled(self) -> bool:
		return bool(self._kbHook) and bool(self._mouseHook)

	def start(self) -> None:
		if self.isRunning:
			return
		self._ready.clear()
		self._stopWatch.clear()
		self._thread = threading.Thread(target=self._run, name=self.threadName, daemon=True)
		self._thread.start()
		self._ready.wait(5)
		self._watchThread = threading.Thread(target=self._watchLoop, name="VigilanteGancho", daemon=True)
		self._watchThread.start()

	def stop(self) -> None:
		self._stopWatch.set()
		thread, threadId = self._thread, self._threadId
		if threadId:
			winapi.user32.PostThreadMessageW(threadId, winapi.WM_QUIT, 0, 0)
		if thread is not None:
			thread.join(3)
			if thread.is_alive():
				# Saldrá al procesar WM_QUIT; quita solo sus propios ganchos.
				log.warning("El hilo de los ganchos de teclado no terminó a tiempo")
		self._thread = None
		self._threadId = 0

	def requestReinstall(self) -> bool:
		"""Pide al hilo de los ganchos que los reinstale (seguro desde cualquier hilo)."""
		if not self._threadId:
			return False
		return bool(winapi.user32.PostThreadMessageW(self._threadId, WM_REINSTALL_HOOKS, 0, 0))

	# ------------------------------------------------------------ hilo de los ganchos
	def _setHook(self, kind: int, proc) -> int | None:
		hmod = winapi.kernel32.GetModuleHandleW(None)
		return winapi.user32.SetWindowsHookExW(kind, proc, hmod, 0) or None

	def _unhook(self, handle) -> bool:
		"""``False`` si Windows ya lo había quitado (o no se pudo quitar)."""
		return bool(winapi.user32.UnhookWindowsHookEx(handle))

	def _install(self) -> bool:
		self.lastHookTick = tickCount()
		kb = self._setHook(winapi.WH_KEYBOARD_LL, self._keyProc)
		if not kb:
			log.error("No se pudo instalar el gancho de teclado (%d)", ctypes.get_last_error())
		mouse = self._setHook(winapi.WH_MOUSE_LL, self._mouseProc)
		if not mouse:
			log.error("No se pudo instalar el gancho de ratón (%d)", ctypes.get_last_error())
		self._kbHook, self._mouseHook = kb, mouse
		if not kb:
			if not self._installFailedAnnounced:
				self._installFailedAnnounced = True
				from ..i18n import _

				_announce(_("Tiresias no ha podido capturar el teclado: sus órdenes no funcionarán. Se seguirá intentando."))
			return False
		if self._installFailedAnnounced:
			self._installFailedAnnounced = False
			from ..i18n import _

			_announce(_("Tiresias ya captura el teclado"))
		return bool(mouse)

	def _reinstall(self) -> None:
		"""Hilo de los ganchos: quita y vuelve a poner los dos ganchos."""
		kbLost = False
		mouseLost = False
		if self._kbHook:
			kbLost = not self._unhook(self._kbHook)
		if self._mouseHook:
			mouseLost = not self._unhook(self._mouseHook)
		wasFailing = self._installFailedAnnounced
		self._kbHook = self._mouseHook = None
		ok = self._install()
		if kbLost or mouseLost:
			self.recoveredCount += 1
			self._backoff = 0.0
			log.warning("Windows había quitado el gancho de %s; reinstalado", "teclado" if kbLost else "ratón")
			if kbLost and ok:
				from ..i18n import _

				_announce(_("Tiresias había perdido el teclado y lo ha recuperado"))
		elif ok and not wasFailing:
			self.silentReinstalls += 1
			# Falsa alarma (entrada táctil, de lápiz...): se espera más la próxima vez.
			self._backoff = min(MAX_BACKOFF_SECONDS, max(CHECK_SECONDS * 2, self._backoff * 2))
			self._backoffUntil = time.monotonic() + self._backoff
			log.debug("Ganchos reinstalados sin pérdida (falsa alarma); espera %.0f s", self._backoff)

	def _run(self) -> None:
		self._threadId = winapi.kernel32.GetCurrentThreadId()
		self._install()
		self._ready.set()
		msg = winapi.MSG()
		while winapi.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
			if msg.message == WM_REINSTALL_HOOKS and not msg.hwnd:
				try:
					self._reinstall()
				except Exception:
					log.exception("Error reinstalando los ganchos")
				continue
			winapi.user32.TranslateMessage(ctypes.byref(msg))
			winapi.user32.DispatchMessageW(ctypes.byref(msg))
		kb, mouse = self._kbHook, self._mouseHook
		self._kbHook = self._mouseHook = None
		if kb:
			self._unhook(kb)
		if mouse:
			self._unhook(mouse)

	# ------------------------------------------------------------ vigilante
	def checkOnce(self) -> bool:
		"""Una comprobación del vigilante. Devuelve ``True`` si pidió reinstalar."""
		if not self._threadId:
			return False
		if not self._kbHook:
			# La instalación falló: se reintenta en cada comprobación.
			return self.requestReinstall()
		if time.monotonic() < self._backoffUntil:
			return False
		if not hookSeemsLost(lastInputTick(), self.lastHookTick, tickCount()) or not isNormalInputDesktop():
			self._suspicions = 0
			return False
		self._suspicions += 1
		if self._suspicions < SUSPICIONS_TO_ACT:
			return False
		self._suspicions = 0
		return self.requestReinstall()

	def _watchLoop(self) -> None:
		while not self._stopWatch.wait(CHECK_SECONDS):
			try:
				self.checkOnce()
			except Exception:
				log.debug("Error en el vigilante de los ganchos", exc_info=True)

	# ------------------------------------------------------------ retrollamadas
	def _onKey(self, nCode: int, wParam: int, lParam: int) -> int:
		if nCode == winapi.HC_ACTION:
			kb = ctypes.cast(lParam, ctypes.POINTER(winapi.KBDLLHOOKSTRUCT)).contents
			self.lastHookTick = kb.time
			callback = self.keyCallback
			if callback is not None and kb.dwExtraInfo != winapi.TIRESIAS_INJECTION_MARK:
				isUp = wParam in (winapi.WM_KEYUP, winapi.WM_SYSKEYUP)
				# Las teclas que llegan por acceso remoto cuentan como pulsadas por el usuario.
				injected = bool(kb.flags & winapi.LLKHF_INJECTED) and kb.dwExtraInfo != winapi.REMOTE_INJECTION_MARK
				try:
					swallow = callback(kb.vkCode, kb.scanCode, kb.flags, isUp, injected)
				except Exception:
					log.exception("Error en el gancho de teclado")
					swallow = False
				if swallow:
					return 1
		return winapi.user32.CallNextHookEx(None, nCode, wParam, lParam)

	def _onMouse(self, nCode: int, wParam: int, lParam: int) -> int:
		if nCode == winapi.HC_ACTION:
			ms = ctypes.cast(lParam, ctypes.POINTER(winapi.MSLLHOOKSTRUCT)).contents
			self.lastHookTick = ms.time
			callback = self.mouseCallback
			if callback is not None and ms.dwExtraInfo != winapi.TIRESIAS_INJECTION_MARK:
				injected = bool(ms.flags & winapi.LLMHF_INJECTED)
				try:
					if callback(wParam, ms.pt.x, ms.pt.y, injected):
						return 1
				except Exception:
					log.exception("Error en el gancho de ratón")
		return winapi.user32.CallNextHookEx(None, nCode, wParam, lParam)


# ====================================================================== WinEvent
class HookThread:
	"""Ganchos WinEvent en su hilo y, aparte, los de teclado y ratón.

	Conserva la interfaz de siempre (``keyCallback``, ``mouseCallback``,
	``start``, ``stop``, ``isRunning``): ``start`` arranca también los ganchos
	de bajo nivel si hay alguna retrollamada de teclado o ratón (con
	``--no-input`` no la hay y solo se instalan los WinEvent).
	"""

	def __init__(self) -> None:
		self._thread: threading.Thread | None = None
		self._threadId = 0
		self._ready = threading.Event()
		self.lowLevel = LowLevelHooks()
		self._winEventHooks: list = []
		self._winEventRequests: list[tuple] = []
		self._winEventProcs: list = []

	# Compatibilidad: las retrollamadas viven en los ganchos de bajo nivel.
	@property
	def keyCallback(self) -> KeyCallback | None:
		return self.lowLevel.keyCallback

	@keyCallback.setter
	def keyCallback(self, value: KeyCallback | None) -> None:
		self.lowLevel.keyCallback = value

	@property
	def mouseCallback(self) -> MouseCallback | None:
		return self.lowLevel.mouseCallback

	@mouseCallback.setter
	def mouseCallback(self, value: MouseCallback | None) -> None:
		self.lowLevel.mouseCallback = value

	def start(self, winEvents: list[tuple]) -> None:
		if self.keyCallback is not None or self.mouseCallback is not None:
			self.lowLevel.start()
		if self.isRunning:
			return
		self._winEventRequests = winEvents
		# Se puede volver a arrancar tras stop() (convivencia con otros lectores).
		self._ready.clear()
		self._winEventProcs = []
		self._thread = threading.Thread(target=self._run, name="Hooks", daemon=True)
		self._thread.start()
		self._ready.wait(5)
		# Cambios de idioma o distribución del teclado: hilo propio (no este).
		from . import input_language

		input_language.start()

	def stop(self) -> None:
		from . import input_language

		input_language.stop()
		self.lowLevel.stop()
		thread, threadId = self._thread, self._threadId
		if threadId:
			winapi.user32.PostThreadMessageW(threadId, winapi.WM_QUIT, 0, 0)
		if thread is not None:
			thread.join(3)
			if thread.is_alive():
				log.warning("El hilo de los WinEvent no terminó a tiempo")
		# Aunque el hilo tarde en salir, se puede arrancar otro: cada hilo quita
		# solo sus propios ganchos.
		self._thread = None
		self._threadId = 0

	@property
	def isRunning(self) -> bool:
		return self._thread is not None and self._thread.is_alive()

	# ------------------------------------------------------------------ hilo
	def _run(self) -> None:
		self._threadId = winapi.kernel32.GetCurrentThreadId()
		hooks: list = []
		for request in self._winEventRequests:
			evMin, evMax, callback = request[:3]
			# Cuarto elemento opcional: True = solo los eventos del propio proceso
			# (diálogos de Tiresias, que se leen con MSAA). El resto omite el propio.
			ownOnly = len(request) > 3 and bool(request[3])
			proc = winapi.WINEVENTPROC(self._makeWinEventProc(callback))
			self._winEventProcs.append(proc)
			if ownOnly:
				h = winapi.user32.SetWinEventHook(evMin, evMax, None, proc, os.getpid(), 0, winapi.WINEVENT_OUTOFCONTEXT)
			else:
				h = winapi.user32.SetWinEventHook(evMin, evMax, None, proc, 0, 0, winapi.WINEVENT_OUTOFCONTEXT | winapi.WINEVENT_SKIPOWNPROCESS)
			if h:
				hooks.append(h)
			else:
				log.warning("No se pudo registrar WinEvent %x-%x", evMin, evMax)
		self._winEventHooks = hooks
		self._ready.set()
		msg = winapi.MSG()
		while winapi.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
			winapi.user32.TranslateMessage(ctypes.byref(msg))
			winapi.user32.DispatchMessageW(ctypes.byref(msg))
		for h in hooks:
			winapi.user32.UnhookWinEvent(h)
		if self._winEventHooks is hooks:
			self._winEventHooks = []

	@staticmethod
	def _makeWinEventProc(callback: Callable) -> Callable:
		def proc(hHook, event, hwnd, idObject, idChild, threadId, timestamp):
			try:
				callback(event, hwnd, idObject, idChild, threadId)
			except Exception:
				log.exception("Error en WinEvent")

		return proc

	def getKeyStateFromForeground(self, vk: int) -> int:
		"""Lee el estado de una tecla compartiendo la entrada del primer plano.

		Si la ventana de primer plano no responde, no se comparte su entrada
		(``AttachThreadInput`` podría bloquear): se lee el estado propio.
		"""
		fg = winapi.getForegroundWindow()
		fgThread = winapi.getWindowThreadId(fg) if fg else 0
		cur = winapi.kernel32.GetCurrentThreadId()
		attached = False
		if fgThread and fgThread != cur and not _user32.IsHungAppWindow(fg):
			attached = bool(winapi.user32.AttachThreadInput(cur, fgThread, True))
		try:
			return winapi.user32.GetKeyState(vk)
		finally:
			if attached:
				winapi.user32.AttachThreadInput(cur, fgThread, False)


hookThread = HookThread()
