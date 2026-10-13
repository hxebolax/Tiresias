"""Anuncios a través del lector de pantalla que tiene preferencia.

Mientras Tiresias está en espera no usa su propia voz: para avisar de que
cede, habla a través del lector activo.

- **NVDA**: «NVDA Controller Client» (``speakText`` y ``brailleMessage`` en
  ``NvdaCtlr.<sesión>.<escritorio>``) con el cliente incluido en
  ``tiresiasControllerServer.dll``. Antes se espera a que NVDA responda a
  ``testIfRunning`` (si acaba de arrancar) y se comprueba con
  ``getProcessId`` que quien responde no es el propio Tiresias.
- **JAWS**: objeto COM ``FreedomSci.JawsApi``, método ``SayString``.
- **Narrador**: evento de notificación UIA (``UiaRaiseNotificationEvent``)
  desde una ventana propia de Tiresias con un proveedor UIA mínimo, que
  Narrador lee (como cualquier cliente UIA).
- **Otros, o si lo anterior falla**: un tono suave.

Los anuncios se hacen en un hilo propio (con COM inicializado): esperar a
que el lector esté listo puede tardar varios segundos y nunca debe bloquear
el núcleo.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import queue
import threading
import time
from typing import Callable

from ..log import getLogger
from .detect import JAWS, NARRATOR, NVDA, ReaderInfo, narratorRunningState

log = getLogger("coexist")

#: Lo que se espera como mucho a que el lector esté listo (s).
READY_TIMEOUT = 30.0

PATH_NVDA = "nvda"
PATH_JAWS = "jaws"
PATH_NARRATOR = "narrator"
PATH_TONE = "tone"
PATH_NONE = "none"


# ------------------------------------------------------------------ NVDA
def speakThroughNvda(text: str, reader: ReaderInfo | None, timeout: float, valid: Callable[[], bool]) -> bool:
	from ..controller import server

	client = server.nvdaClient()
	if client is None:
		return False
	deadline = time.monotonic() + timeout
	status = -1
	while valid() and time.monotonic() < deadline:
		status = client.testIfRunning()
		if status == 0:
			break
		time.sleep(0.5)
	if status != 0:
		log.info("NVDA no responde a testIfRunning (estado %d)", status)
		return False
	st, pid = client.getProcessId()
	if st == 0 and pid in (os.getpid(), 0):
		# Quien responde es Tiresias (su auxiliar): no es NVDA.
		log.warning("El punto de conexión de NVDA lo atiende Tiresias: no se anuncia por NVDA")
		return False
	if st == 0 and reader is not None and pid != reader.pid:
		log.debug("NVDA responde con el PID %d (detectado %d)", pid, reader.pid)
	if not valid():
		return False
	res = client.speakText(text)
	if res != 0:
		log.info("NVDA no aceptó speakText (estado %d)", res)
		return False
	client.brailleMessage(text)
	return True


# ------------------------------------------------------------------ JAWS
REGDB_E_CLASSNOTREG = -2147221164
#: Errores de «clase no registrada» o ProgID desconocido (CO_E_CLASSSTRING).
CO_E_CLASSSTRING = -2147221005


def speakThroughJaws(text: str, timeout: float, valid: Callable[[], bool]) -> bool:
	try:
		import comtypes.client
	except ImportError:
		return False
	deadline = time.monotonic() + timeout
	api = None
	while valid() and time.monotonic() < deadline:
		try:
			if api is None:
				api = comtypes.client.CreateObject("FreedomSci.JawsApi", dynamic=True)
			if api.SayString(text, False):
				return True
		except Exception as e:
			code = getattr(e, "hresult", None) or getattr(e, "winerror", None)
			if code in (REGDB_E_CLASSNOTREG, CO_E_CLASSSTRING):
				# La API de JAWS no está registrada: no sirve esperar.
				log.info("La API COM de JAWS (FreedomSci.JawsApi) no está registrada")
				return False
			log.debug("JAWS todavía no acepta SayString", exc_info=True)
			api = None
		time.sleep(0.5)
	return False


# ------------------------------------------------------------------ Narrador (UIA)
NotificationKind_Other = 4
NotificationProcessing_ImportantAll = 0


UIA_NamePropertyId = 30005
UIA_ControlTypePropertyId = 30003
UIA_PaneControlTypeId = 50033

_providerClass = None


def _providerType():
	"""Proveedor UIA mínimo de una ventana de Tiresias (solo para lanzar notificaciones)."""
	global _providerClass
	if _providerClass is not None:
		return _providerClass
	import comtypes.client
	from comtypes import COMObject

	UIA = comtypes.client.GetModule("UIAutomationCore.dll")
	uia = ctypes.WinDLL("uiautomationcore")
	uia.UiaHostProviderFromHwnd.argtypes = [wt.HWND, ctypes.POINTER(ctypes.POINTER(UIA.IRawElementProviderSimple))]
	uia.UiaHostProviderFromHwnd.restype = ctypes.HRESULT

	class NotificationProvider(COMObject):
		_com_interfaces_ = [UIA.IRawElementProviderSimple]

		def __init__(self, hwnd: int) -> None:
			super().__init__()
			self.hwnd = hwnd

		def _get_ProviderOptions(self):
			# Sin UseComThreading: UI Automation llama al proveedor desde sus hilos
			# (el hilo de los anuncios no atiende mensajes).
			return UIA.ProviderOptions_ServerSideProvider

		def GetPatternProvider(self, patternId):
			return None

		def GetPropertyValue(self, propertyId):
			if propertyId == UIA_NamePropertyId:
				return "Tiresias"
			if propertyId == UIA_ControlTypePropertyId:
				return UIA_PaneControlTypeId
			return None

		def _get_HostRawElementProvider(self):
			host = ctypes.POINTER(UIA.IRawElementProviderSimple)()
			uia.UiaHostProviderFromHwnd(self.hwnd, ctypes.byref(host))
			if host:
				# La referencia es para quien llama; Python suelta la suya al salir.
				host.AddRef()
			return host

	NotificationProvider.UIA = UIA
	_providerClass = NotificationProvider
	return _providerClass


WM_GETOBJECT = 0x003D
UiaRootObjectId = -25
_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class _WNDCLASSW(ctypes.Structure):
	_fields_ = [
		("style", wt.UINT),
		("lpfnWndProc", _WNDPROC),
		("cbClsExtra", ctypes.c_int),
		("cbWndExtra", ctypes.c_int),
		("hInstance", wt.HINSTANCE),
		("hIcon", wt.HICON),
		("hCursor", wt.HANDLE),
		("hbrBackground", wt.HBRUSH),
		("lpszMenuName", wt.LPCWSTR),
		("lpszClassName", wt.LPCWSTR),
	]


#: Ventanas de notificación vivas, por identificador (las atiende un único procedimiento).
_windows: dict[int, "NotificationWindow"] = {}
_classRegistered = False


_defU32 = ctypes.WinDLL("user32")
_defU32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
_defU32.DefWindowProcW.restype = ctypes.c_ssize_t


def _classWndProc(hwnd, msg, wParam, lParam):
	window = _windows.get(int(hwnd or 0))
	if window is not None:
		return window._wndProc(hwnd, msg, wParam, lParam)
	return _defU32.DefWindowProcW(hwnd, msg, wParam, lParam)


#: Debe vivir tanto como la clase de ventana registrada (todo el proceso).
_classProc = _WNDPROC(_classWndProc)


def _registerClass(u32, name: str) -> None:
	global _classRegistered
	if _classRegistered:
		return
	wc = _WNDCLASSW()
	wc.lpfnWndProc = _classProc
	wc.lpszClassName = name
	u32.RegisterClassW(ctypes.byref(wc))
	_classRegistered = True


class NotificationWindow:
	"""Ventana propia de Tiresias que expone un proveedor UIA y lanza notificaciones.

	UI Automation resuelve el elemento que lanza el evento pidiendo a su
	ventana el proveedor con ``WM_GETOBJECT``; por eso la ventana es propia
	(no la de wx) y vive en el hilo que la crea, que debe atender sus
	mensajes mientras Narrador consulta el elemento (:meth:`pump`).
	"""

	CLASS_NAME = "TiresiasAnunciosUIA"

	def __init__(self) -> None:
		self._u32 = ctypes.WinDLL("user32", use_last_error=True)
		self._uia = ctypes.WinDLL("uiautomationcore")
		u32 = self._u32
		u32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
		u32.DefWindowProcW.restype = ctypes.c_ssize_t
		u32.CreateWindowExW.restype = wt.HWND
		u32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
		u32.DestroyWindow.argtypes = [wt.HWND]
		self._uia.UiaReturnRawElementProvider.argtypes = [wt.HWND, wt.WPARAM, wt.LPARAM, ctypes.c_void_p]
		self._uia.UiaReturnRawElementProvider.restype = ctypes.c_ssize_t
		self._uia.UiaRaiseNotificationEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
		self._uia.UiaRaiseNotificationEvent.restype = ctypes.HRESULT
		self.hwnd = 0
		self._provider = None
		self._providerPtr = None
		cls = _providerType()
		_registerClass(u32, self.CLASS_NAME)
		# Visible pero fuera de la pantalla, de 1×1 y sin activarse: UI Automation
		# no entrega a otros procesos los eventos de ventanas ocultas.
		# WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE: no sale en Alt+Tab ni en la barra de tareas.
		self.hwnd = int(u32.CreateWindowExW(0x08000080, self.CLASS_NAME, "Tiresias", 0x90000000, -32000, -32000, 1, 1, None, None, None, None) or 0)
		if not self.hwnd:
			raise OSError("No se pudo crear la ventana de notificaciones UIA")
		self._provider = cls(self.hwnd)
		self._providerPtr = self._provider.QueryInterface(cls.UIA.IRawElementProviderSimple)
		_windows[self.hwnd] = self

	def _wndProc(self, hwnd, msg, wParam, lParam):
		if msg == WM_GETOBJECT and ctypes.c_long(lParam & 0xFFFFFFFF).value == UiaRootObjectId and self._providerPtr is not None:
			return self._uia.UiaReturnRawElementProvider(hwnd, wParam, lParam, ctypes.cast(self._providerPtr, ctypes.c_void_p))
		return self._u32.DefWindowProcW(hwnd, msg, wParam, lParam)

	def notify(self, text: str, activityId: str = "Tiresias.Convivencia") -> bool:
		oleaut = ctypes.WinDLL("oleaut32")
		oleaut.SysAllocString.argtypes = [wt.LPCWSTR]
		oleaut.SysAllocString.restype = ctypes.c_void_p
		oleaut.SysFreeString.argtypes = [ctypes.c_void_p]
		display = oleaut.SysAllocString(text)
		activity = oleaut.SysAllocString(activityId)
		try:
			self._uia.UiaRaiseNotificationEvent(ctypes.cast(self._providerPtr, ctypes.c_void_p), NotificationKind_Other, NotificationProcessing_ImportantAll, display, activity)
			return True
		except OSError:
			log.debug("UiaRaiseNotificationEvent falló", exc_info=True)
			return False
		finally:
			oleaut.SysFreeString(display)
			oleaut.SysFreeString(activity)

	def pump(self, seconds: float) -> None:
		"""Atiende los mensajes de la ventana (las consultas de UIA) un rato."""
		msg = wt.MSG()
		deadline = time.monotonic() + seconds
		while time.monotonic() < deadline:
			while self._u32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
				self._u32.TranslateMessage(ctypes.byref(msg))
				self._u32.DispatchMessageW(ctypes.byref(msg))
			time.sleep(0.02)

	def destroy(self) -> None:
		if self.hwnd:
			self._u32.DestroyWindow(self.hwnd)
			_windows.pop(self.hwnd, None)
			self.hwnd = 0
		self._providerPtr = None
		self._provider = None


def raiseUiaNotification(text: str) -> bool:
	"""Lanza una notificación UIA desde una ventana de Tiresias (hilo de anuncios).

	La ventana se crea solo para el anuncio: los clientes UIA de otros
	procesos tardan un momento en enterarse de una ventana nueva, así que se
	espera atendiendo sus mensajes antes y después de la notificación.
	"""
	try:
		window = NotificationWindow()
	except Exception:
		log.debug("No se pudo preparar la ventana de notificaciones UIA", exc_info=True)
		return False
	try:
		window.pump(1.0)
		ok = window.notify(text)
		# Narrador pide el nombre y la posición del elemento a la ventana.
		window.pump(1.5)
		return ok
	finally:
		window.destroy()


def speakThroughNarrator(text: str, timeout: float, valid: Callable[[], bool]) -> bool:
	deadline = time.monotonic() + timeout
	# Narrador tarda en estar listo tras arrancar: se espera a su indicador.
	while valid() and time.monotonic() < deadline and narratorRunningState() is not True:
		time.sleep(0.5)
	if not valid():
		return False
	return raiseUiaNotification(text)


# ------------------------------------------------------------------ tono
def playTone() -> None:
	"""Dos tonos suaves y graves (Tiresias en espera)."""
	from .. import queue_handler
	from ..audio import tones

	queue_handler.queueFunction(tones.beep, 392, 90, 20, 20)
	queue_handler.callLater(130, tones.beep, 294, 120, 20, 20)


# ------------------------------------------------------------------ hilo
class Announcer:
	"""Hilo que entrega los anuncios por el lector activo."""

	def __init__(self) -> None:
		self._queue: queue.Queue = queue.Queue()
		self._thread: threading.Thread | None = None
		#: Último camino usado (para el registro y las pruebas).
		self.lastPath = PATH_NONE

	def start(self) -> None:
		if self._thread is not None and self._thread.is_alive():
			return
		self._thread = threading.Thread(target=self._run, name="Anuncios de convivencia", daemon=True)
		self._thread.start()

	def stop(self) -> None:
		if self._thread is not None:
			self._queue.put(None)
			self._thread.join(2)
			self._thread = None

	def announce(self, reader: ReaderInfo, text: str, valid: Callable[[], bool] = lambda: True, timeout: float = READY_TIMEOUT, onDone: Callable[[str], None] | None = None) -> None:
		self.start()
		self._queue.put((reader, text, valid, timeout, onDone))

	def _run(self) -> None:
		try:
			ctypes.windll.ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
		except Exception:
			pass
		while True:
			item = self._queue.get()
			if item is None:
				break
			reader, text, valid, timeout, onDone = item
			try:
				path = self.deliver(reader, text, valid, timeout)
			except Exception:
				log.exception("Error anunciando a través de %s", reader.name)
				path = PATH_NONE
			self.lastPath = path
			if onDone is not None:
				try:
					onDone(path)
				except Exception:
					log.exception("Error tras el anuncio")

	@staticmethod
	def deliver(reader: ReaderInfo, text: str, valid: Callable[[], bool], timeout: float) -> str:
		"""Entrega el anuncio y devuelve el camino usado (hilo del anunciador)."""
		if not valid():
			return PATH_NONE
		ok = False
		path = PATH_TONE
		if reader.id == NVDA:
			ok, path = speakThroughNvda(text, reader, timeout, valid), PATH_NVDA
		elif reader.id == JAWS:
			ok, path = speakThroughJaws(text, timeout, valid), PATH_JAWS
		elif reader.id == NARRATOR:
			ok, path = speakThroughNarrator(text, timeout, valid), PATH_NARRATOR
		if ok:
			log.info("Anuncio de convivencia entregado por %s: %s", path, text)
			return path
		if not valid():
			return PATH_NONE
		log.info("Anuncio de convivencia con un tono (no se pudo hablar por %s)", reader.name)
		playTone()
		return PATH_TONE
