"""Enlace con ``tiresiasControllerServer.dll`` (servidor RPC nativo).

La biblioteca nativa recibe las llamadas RPC de los programas y llama a las
funciones de :class:`Handlers` en hilos del propio RPC (nunca en el núcleo).
Este módulo solo se ocupa de cargarla, de los puntos de conexión y de las
retrollamadas; la lógica está en :mod:`tiresias.controller`.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import threading
import time
from typing import Callable

from .. import paths
from ..log import getLogger

log = getLogger("controller")

RPC_S_OK = 0
RPC_S_DUPLICATE_ENDPOINT = 1740
ERROR_SERVICE_NOT_ACTIVE = 1062
ERROR_CALL_NOT_IMPLEMENTED = 120

TIRESIAS_PREFIX = "TiresiasCtlr."
NVDA_PREFIX = "NvdaCtlr."

_TextFunc = ctypes.WINFUNCTYPE(wt.ULONG, wt.ULONG, wt.LPCWSTR)
_VoidFunc = ctypes.WINFUNCTYPE(wt.ULONG, wt.ULONG)
_SsmlFunc = ctypes.WINFUNCTYPE(wt.ULONG, wt.ULONG, wt.LPCWSTR, ctypes.c_long, ctypes.c_long, ctypes.c_int)
_BoolOutFunc = ctypes.WINFUNCTYPE(wt.ULONG, wt.ULONG, ctypes.POINTER(ctypes.c_int))
_TextFlagsFunc = ctypes.WINFUNCTYPE(wt.ULONG, wt.ULONG, wt.LPCWSTR, wt.ULONG)
_BoolInFunc = ctypes.WINFUNCTYPE(wt.ULONG, wt.ULONG, ctypes.c_int)


class TcsCallbacks(ctypes.Structure):
	"""Debe coincidir con ``TcsCallbacks`` de ``controller/src/server.c``."""

	_fields_ = [
		("size", wt.ULONG),
		("speakText", _TextFunc),
		("cancelSpeech", _VoidFunc),
		("brailleMessage", _TextFunc),
		("speakSsml", _SsmlFunc),
		("isSpeaking", _BoolOutFunc),
		("speakTextEx", _TextFlagsFunc),
		("pauseSpeech", _BoolInFunc),
		("testIfRunning", _VoidFunc),
	]


class Handlers:
	"""Lo que hace Tiresias con cada llamada (se ejecuta en hilos RPC).

	Todas devuelven un código de error de Windows (0 = correcto).
	"""

	def testIfRunning(self, pid: int) -> int:
		return 0

	def speakText(self, pid: int, text: str) -> int:
		return ERROR_CALL_NOT_IMPLEMENTED

	def cancelSpeech(self, pid: int) -> int:
		return ERROR_CALL_NOT_IMPLEMENTED

	def brailleMessage(self, pid: int, text: str) -> int:
		return ERROR_CALL_NOT_IMPLEMENTED

	def speakSsml(self, pid: int, ssml: str, symbolLevel: int, priority: int, asynchronous: bool) -> int:
		return ERROR_CALL_NOT_IMPLEMENTED

	def isSpeaking(self, pid: int) -> tuple[int, bool]:
		return ERROR_CALL_NOT_IMPLEMENTED, False

	def speakTextEx(self, pid: int, text: str, flags: int) -> int:
		return ERROR_CALL_NOT_IMPLEMENTED

	def pauseSpeech(self, pid: int, pause: bool) -> int:
		return ERROR_CALL_NOT_IMPLEMENTED


def controllerDir() -> str:
	"""Carpeta con las bibliotecas nativas (``<programa>\\data\\controller``)."""
	return paths.controllerBinDir()


def serverDllPath() -> str:
	return os.path.join(controllerDir(), "x64", "tiresiasControllerServer.dll")


def desktopNamespace() -> str:
	"""``"<sesión>.<escritorio>"``, igual que calculan los clientes."""
	k32 = ctypes.windll.kernel32
	u32 = ctypes.windll.user32
	session = wt.DWORD(0)
	k32.ProcessIdToSessionId(k32.GetCurrentProcessId(), ctypes.byref(session))
	u32.GetThreadDesktop.restype = wt.HANDLE
	u32.GetThreadDesktop.argtypes = [wt.DWORD]
	hDesk = u32.GetThreadDesktop(k32.GetCurrentThreadId())
	buf = ctypes.create_unicode_buffer(64)
	needed = wt.DWORD(0)
	u32.GetUserObjectInformationW.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)]
	name = "Default"
	if hDesk and u32.GetUserObjectInformationW(hDesk, 2, buf, ctypes.sizeof(buf), ctypes.byref(needed)):  # UOI_NAME
		name = buf.value or "Default"
	return f"{session.value}.{name}"


#: Llamadas RPC que se están atendiendo ahora mismo (dentro de Python).
_active = 0
_activeLock = threading.Lock()
#: Retrollamadas de servidores ya detenidos (la biblioteca nativa sigue cargada).
_retainedCallbacks: list = []


def activeCalls() -> int:
	return _active


def _guard(func: Callable[..., int], default: int = 1) -> Callable[..., int]:
	"""Ninguna excepción de Python puede cruzar a código nativo."""

	def wrapper(*args):
		global _active
		with _activeLock:
			_active += 1
		try:
			res = func(*args)
			return int(res or 0) & 0xFFFFFFFF
		except Exception:
			log.exception("Error atendiendo una llamada de la API de control")
			return default
		finally:
			with _activeLock:
				_active -= 1

	return wrapper


class ControllerServer:
	"""Carga el servidor nativo y lo conecta con unos :class:`Handlers`."""

	def __init__(self, handlers: Handlers) -> None:
		self.handlers = handlers
		self._dll = None
		self._callbacks: TcsCallbacks | None = None
		self.namespace = desktopNamespace()
		self.endpoints: dict[str, bool] = {}

	@property
	def isLoaded(self) -> bool:
		return self._dll is not None

	def start(self) -> int:
		path = serverDllPath()
		if not os.path.isfile(path):
			log.warning("No se encuentra %s: la API de control no estará disponible", path)
			return ERROR_CALL_NOT_IMPLEMENTED
		dll = ctypes.WinDLL(path)
		dll.tcs_initialize.argtypes = [ctypes.POINTER(TcsCallbacks)]
		dll.tcs_initialize.restype = ctypes.c_long
		dll.tcs_listen.argtypes = [wt.LPCWSTR]
		dll.tcs_listen.restype = ctypes.c_long
		dll.tcs_terminate.argtypes = [ctypes.c_int]
		dll.tcs_terminate.restype = ctypes.c_long
		dll.tcs_ssmlMarkReached.argtypes = [wt.LPCWSTR]
		dll.tcs_ssmlMarkReached.restype = ctypes.c_long
		if hasattr(dll, "tcs_setRelayPid"):
			dll.tcs_setRelayPid.argtypes = [wt.ULONG]
			dll.tcs_setRelayPid.restype = None
		h = self.handlers

		def _isSpeaking(pid, out):
			res, value = h.isSpeaking(pid)
			out[0] = 1 if value else 0
			return res

		cb = TcsCallbacks()
		cb.size = ctypes.sizeof(TcsCallbacks)
		cb.speakText = _TextFunc(_guard(lambda pid, t: h.speakText(pid, t or "")))
		cb.cancelSpeech = _VoidFunc(_guard(lambda pid: h.cancelSpeech(pid)))
		cb.brailleMessage = _TextFunc(_guard(lambda pid, t: h.brailleMessage(pid, t or "")))
		cb.speakSsml = _SsmlFunc(_guard(lambda pid, s, lvl, pri, asy: h.speakSsml(pid, s or "", lvl, pri, bool(asy))))
		cb.isSpeaking = _BoolOutFunc(_guard(_isSpeaking))
		cb.speakTextEx = _TextFlagsFunc(_guard(lambda pid, t, f: h.speakTextEx(pid, t or "", f)))
		cb.pauseSpeech = _BoolInFunc(_guard(lambda pid, p: h.pauseSpeech(pid, bool(p))))
		cb.testIfRunning = _VoidFunc(_guard(lambda pid: h.testIfRunning(pid), ERROR_SERVICE_NOT_ACTIVE))
		status = dll.tcs_initialize(ctypes.byref(cb))
		if status != RPC_S_OK:
			log.error("No se pudo registrar la API de control (estado RPC %d)", status)
			return status
		# Las retrollamadas deben vivir mientras viva la biblioteca.
		self._callbacks = cb
		self._dll = dll
		return RPC_S_OK

	def listen(self, prefix: str) -> int:
		"""Abre un punto de conexión; devuelve el estado RPC."""
		if self._dll is None:
			return ERROR_CALL_NOT_IMPLEMENTED
		endpoint = prefix + self.namespace
		if self.endpoints.get(endpoint):
			return RPC_S_OK
		status = self._dll.tcs_listen(endpoint)
		if status == RPC_S_OK:
			self.endpoints[endpoint] = True
			log.info("API de control escuchando en ncalrpc:[%s]", endpoint)
		return status

	def setRelayPid(self, pid: int) -> bool:
		"""Proceso del auxiliar al que se aceptan llamadas reenviadas (0 = ninguno)."""
		if self._dll is None or not hasattr(self._dll, "tcs_setRelayPid"):
			return False
		self._dll.tcs_setRelayPid(int(pid) & 0xFFFFFFFF)
		return True

	@property
	def supportsRelay(self) -> bool:
		"""La biblioteca acepta llamadas reenviadas por ``tiresiasNvdaWindow.exe``."""
		return self._dll is not None and hasattr(self._dll, "tcs_setRelayPid")

	def isListening(self, prefix: str) -> bool:
		return bool(self.endpoints.get(prefix + self.namespace))

	def markReached(self, name: str) -> int:
		"""Avisa al cliente de una marca SSML (solo desde el hilo de la llamada)."""
		if self._dll is None:
			return ERROR_CALL_NOT_IMPLEMENTED
		return self._dll.tcs_ssmlMarkReached(name)

	def stop(self) -> None:
		if self._dll is None:
			return
		try:
			# Sin esperar dentro del RPC: las llamadas en curso terminan solas
			# (ven que se cierra) y aquí se les da un momento para salir de Python.
			self._dll.tcs_terminate(0)
		except Exception:
			log.exception("Error deteniendo la API de control")
		deadline = time.monotonic() + 2.0
		while _active and time.monotonic() < deadline:
			time.sleep(0.02)
		# La biblioteca no se descarga: el RPC puede seguir teniendo hilos
		# dentro de ella hasta que termine el proceso. Por lo mismo, las
		# retrollamadas se conservan vivas: si se liberasen con el servidor, una
		# llamada tardía saltaría a memoria ya liberada.
		if self._callbacks is not None:
			_retainedCallbacks.append(self._callbacks)


# ------------------------------------------------------------------ cliente de NVDA
class NvdaClient:
	"""Cliente del punto de conexión de NVDA (``NvdaCtlr.<sesión>.<escritorio>``).

	Usa las exportaciones ``tcs_nvda*`` de la biblioteca del servidor. Sirve
	para hablar a través de NVDA cuando Tiresias está en espera porque NVDA
	tiene preferencia. El escritorio es el del hilo que llama.
	"""

	def __init__(self, dll) -> None:
		self._dll = dll
		dll.tcs_nvdaTestIfRunning.argtypes = []
		dll.tcs_nvdaTestIfRunning.restype = wt.ULONG
		dll.tcs_nvdaSpeakText.argtypes = [wt.LPCWSTR]
		dll.tcs_nvdaSpeakText.restype = wt.ULONG
		dll.tcs_nvdaCancelSpeech.argtypes = []
		dll.tcs_nvdaCancelSpeech.restype = wt.ULONG
		dll.tcs_nvdaBrailleMessage.argtypes = [wt.LPCWSTR]
		dll.tcs_nvdaBrailleMessage.restype = wt.ULONG
		dll.tcs_nvdaGetProcessId.argtypes = [ctypes.POINTER(wt.ULONG)]
		dll.tcs_nvdaGetProcessId.restype = wt.ULONG

	def testIfRunning(self) -> int:
		return int(self._dll.tcs_nvdaTestIfRunning())

	def speakText(self, text: str) -> int:
		return int(self._dll.tcs_nvdaSpeakText(text))

	def cancelSpeech(self) -> int:
		return int(self._dll.tcs_nvdaCancelSpeech())

	def brailleMessage(self, text: str) -> int:
		return int(self._dll.tcs_nvdaBrailleMessage(text))

	def getProcessId(self) -> tuple[int, int]:
		"""``(estado, pid)``: NVDA anterior a 2024.1 responde con un error."""
		pid = wt.ULONG(0)
		status = int(self._dll.tcs_nvdaGetProcessId(ctypes.byref(pid)))
		return status, pid.value


_nvdaClient: NvdaClient | None = None
_nvdaClientLock = threading.Lock()


def nvdaClient() -> NvdaClient | None:
	"""Cliente de NVDA (``None`` si falta la biblioteca o es antigua)."""
	global _nvdaClient
	with _nvdaClientLock:
		if _nvdaClient is None:
			path = serverDllPath()
			if not os.path.isfile(path):
				return None
			try:
				dll = ctypes.WinDLL(path)
				if not hasattr(dll, "tcs_nvdaSpeakText"):
					log.warning("La biblioteca %s no incluye el cliente de NVDA", path)
					return None
				_nvdaClient = NvdaClient(dll)
			except OSError:
				log.exception("No se pudo cargar %s", path)
				return None
		return _nvdaClient
