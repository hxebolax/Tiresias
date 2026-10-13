"""E/S de Windows para la voz por Escritorio remoto (sin dependencias de Tiresias).

- :class:`OverlappedStream`: lectura y escritura de un identificador abierto
  en modo superpuesto (tubería con nombre o canal virtual), con parada
  inmediata desde otro hilo.
- :class:`PipeListener`: servidor de la tubería ``\\\\.\\pipe\\TiresiasRdp.<sesión>``
  (equipo cliente): acepta una conexión por cada ventana de Escritorio
  remoto con el canal abierto.
- :func:`openDynamicChannel`: abre el canal virtual dinámico desde dentro de
  la sesión remota (``WTSVirtualChannelOpenEx``; en las sesiones de Omnissa
  Horizon, ``VDP_VirtualChannelOpenEx`` de ``vdp_rdpvcbridge.dll``).
- :func:`isRemoteSession` y :func:`remoteKind` (RDP, Citrix ICA u Horizon).
- :func:`processInfo`: nombre y proceso padre del programa cliente.

En el canal virtual cada lectura empieza con una cabecera
``CHANNEL_PDU_HEADER`` (longitud y banderas, 8 bytes) seguida de un trozo de
datos; las escrituras van sin cabecera. :class:`OverlappedStream` la quita si
se crea con ``pduHeader=True``.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import threading

from ..log import getLogger

log = getLogger("rdp")

CHANNEL_NAME = "TiresiasRdp"
PIPE_PREFIX = "\\\\.\\pipe\\TiresiasRdp."

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

INVALID_HANDLE_VALUE = wt.HANDLE(-1).value
ERROR_IO_PENDING = 997
ERROR_PIPE_CONNECTED = 535
ERROR_BROKEN_PIPE = 109
ERROR_OPERATION_ABORTED = 995
ERROR_ACCESS_DENIED = 5
ERROR_PIPE_BUSY = 231
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102
INFINITE = 0xFFFFFFFF

PIPE_ACCESS_DUPLEX = 0x3
FILE_FLAG_OVERLAPPED = 0x40000000
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
PIPE_TYPE_BYTE = 0x0
PIPE_READMODE_BYTE = 0x0
PIPE_TYPE_MESSAGE = 0x4
PIPE_READMODE_MESSAGE = 0x2
PIPE_WAIT = 0x0
PIPE_REJECT_REMOTE_CLIENTS = 0x8
PIPE_UNLIMITED_INSTANCES = 255
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
DUPLICATE_SAME_ACCESS = 0x2
SM_REMOTESESSION = 0x1000

PDU_HEADER_SIZE = 8
READ_SIZE = 65536


class OVERLAPPED(ctypes.Structure):
	_fields_ = [
		("Internal", ctypes.c_void_p),
		("InternalHigh", ctypes.c_void_p),
		("Offset", wt.DWORD),
		("OffsetHigh", wt.DWORD),
		("hEvent", wt.HANDLE),
	]


class SECURITY_ATTRIBUTES(ctypes.Structure):
	_fields_ = [("nLength", wt.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p), ("bInheritHandle", wt.BOOL)]


kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
kernel32.CreateEventW.restype = wt.HANDLE
kernel32.SetEvent.argtypes = [wt.HANDLE]
kernel32.ResetEvent.argtypes = [wt.HANDLE]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.WaitForMultipleObjects.argtypes = [wt.DWORD, ctypes.POINTER(wt.HANDLE), wt.BOOL, wt.DWORD]
kernel32.WaitForMultipleObjects.restype = wt.DWORD
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
kernel32.WaitForSingleObject.restype = wt.DWORD
kernel32.ReadFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.POINTER(OVERLAPPED)]
kernel32.ReadFile.restype = wt.BOOL
kernel32.WriteFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.POINTER(OVERLAPPED)]
kernel32.WriteFile.restype = wt.BOOL
kernel32.GetOverlappedResult.argtypes = [wt.HANDLE, ctypes.POINTER(OVERLAPPED), ctypes.POINTER(wt.DWORD), wt.BOOL]
kernel32.GetOverlappedResult.restype = wt.BOOL
kernel32.CancelIoEx.argtypes = [wt.HANDLE, ctypes.POINTER(OVERLAPPED)]
kernel32.CancelIoEx.restype = wt.BOOL
kernel32.CreateNamedPipeW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.POINTER(SECURITY_ATTRIBUTES)]
kernel32.CreateNamedPipeW.restype = wt.HANDLE
kernel32.ConnectNamedPipe.argtypes = [wt.HANDLE, ctypes.POINTER(OVERLAPPED)]
kernel32.ConnectNamedPipe.restype = wt.BOOL
kernel32.DisconnectNamedPipe.argtypes = [wt.HANDLE]
kernel32.SetNamedPipeHandleState.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD), ctypes.c_void_p, ctypes.c_void_p]
kernel32.SetNamedPipeHandleState.restype = wt.BOOL
kernel32.GetNamedPipeClientProcessId.argtypes = [wt.HANDLE, ctypes.POINTER(wt.ULONG)]
kernel32.GetNamedPipeClientProcessId.restype = wt.BOOL
kernel32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
kernel32.CreateFileW.restype = wt.HANDLE
kernel32.GetCurrentProcess.restype = wt.HANDLE
kernel32.DuplicateHandle.argtypes = [wt.HANDLE, wt.HANDLE, wt.HANDLE, ctypes.POINTER(wt.HANDLE), wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.DuplicateHandle.restype = wt.BOOL
kernel32.ProcessIdToSessionId.argtypes = [wt.DWORD, ctypes.POINTER(wt.DWORD)]
kernel32.ProcessIdToSessionId.restype = wt.BOOL
kernel32.LocalFree.argtypes = [ctypes.c_void_p]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wt.LPCWSTR, wt.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wt.ULONG)]
advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wt.BOOL


def _check(ok: bool, what: str) -> None:
	if not ok:
		err = ctypes.get_last_error()
		raise OSError(err, f"{what}: {ctypes.FormatError(err).strip()}")


def currentSessionId() -> int:
	sid = wt.DWORD(0)
	if not kernel32.ProcessIdToSessionId(kernel32.GetCurrentProcessId(), ctypes.byref(sid)):
		return 0
	return int(sid.value)


def pipeName(sessionId: int | None = None) -> str:
	"""Nombre de la tubería que usa la biblioteca de mstsc.exe en esta sesión."""
	return f"{PIPE_PREFIX}{currentSessionId() if sessionId is None else sessionId}"


# ====================================================================== flujo
class StreamClosed(Exception):
	pass


class OverlappedStream:
	"""Identificador en modo superpuesto con lecturas y escrituras interrumpibles.

	``read()`` y ``write()`` bloquean el hilo que las llama (cada una se usa
	desde un solo hilo); ``close()`` se puede llamar desde cualquiera y
	despierta a los dos.
	"""

	def __init__(self, handle: int, pduHeader: bool = False, writeTimeout: float = 5.0) -> None:
		self.handle = handle
		self.pduHeader = pduHeader
		self.writeTimeoutMs = int(writeTimeout * 1000)
		self._stop = kernel32.CreateEventW(None, True, False, None)
		self._readEvent = kernel32.CreateEventW(None, True, False, None)
		self._writeEvent = kernel32.CreateEventW(None, True, False, None)
		self._readBuf = ctypes.create_string_buffer(READ_SIZE)
		self._lock = threading.Lock()
		self._busy = 0
		self._closed = False
		self._handleClosed = False

	@property
	def closed(self) -> bool:
		return self._closed

	def _enter(self) -> None:
		with self._lock:
			if self._closed:
				raise StreamClosed()
			self._busy += 1

	def _leave(self) -> None:
		with self._lock:
			self._busy -= 1
			last = self._closed and self._busy == 0
		if last:
			self._release()

	def _wait(self, event: int, timeoutMs: int) -> int:
		handles = (wt.HANDLE * 2)(self._stop, event)
		return kernel32.WaitForMultipleObjects(2, handles, False, timeoutMs)

	def _finish(self, ov: OVERLAPPED, event: int, timeoutMs: int) -> int | None:
		"""Espera a que acabe una operación; ``None`` si se para o caduca."""
		w = self._wait(event, timeoutMs)
		n = wt.DWORD(0)
		if w != WAIT_OBJECT_0 + 1:
			kernel32.CancelIoEx(self.handle, ctypes.byref(ov))
			kernel32.GetOverlappedResult(self.handle, ctypes.byref(ov), ctypes.byref(n), True)
			return None
		if not kernel32.GetOverlappedResult(self.handle, ctypes.byref(ov), ctypes.byref(n), False):
			return None
		return int(n.value)

	def read(self) -> bytes:
		"""Lee lo que haya (``b""`` si se cierra o hay un error)."""
		try:
			self._enter()
		except StreamClosed:
			return b""
		try:
			while True:
				ov = OVERLAPPED()
				ov.hEvent = self._readEvent
				kernel32.ResetEvent(self._readEvent)
				ok = kernel32.ReadFile(self.handle, self._readBuf, READ_SIZE, None, ctypes.byref(ov))
				if not ok:
					err = ctypes.get_last_error()
					if err != ERROR_IO_PENDING:
						if err not in (ERROR_BROKEN_PIPE, ERROR_OPERATION_ABORTED):
							log.debug("ReadFile: error %d", err)
						return b""
				n = self._finish(ov, self._readEvent, INFINITE)
				if not n:
					return b""
				data = self._readBuf.raw[:n]
				if self.pduHeader:
					data = data[PDU_HEADER_SIZE:]
					if not data:
						continue
				return data
		finally:
			self._leave()

	def write(self, data: bytes) -> bool:
		try:
			self._enter()
		except StreamClosed:
			return False
		try:
			view = memoryview(data)
			while len(view):
				buf = ctypes.create_string_buffer(bytes(view), len(view))
				ov = OVERLAPPED()
				ov.hEvent = self._writeEvent
				kernel32.ResetEvent(self._writeEvent)
				ok = kernel32.WriteFile(self.handle, buf, len(view), None, ctypes.byref(ov))
				if not ok and ctypes.get_last_error() != ERROR_IO_PENDING:
					return False
				n = self._finish(ov, self._writeEvent, self.writeTimeoutMs)
				if not n:
					return False
				view = view[n:]
			return True
		finally:
			self._leave()

	def close(self) -> None:
		with self._lock:
			if self._closed:
				return
			self._closed = True
			idle = self._busy == 0
		kernel32.SetEvent(self._stop)
		if idle:
			self._release()

	def _release(self) -> None:
		with self._lock:
			if self._handleClosed:
				return
			self._handleClosed = True
		try:
			kernel32.DisconnectNamedPipe(self.handle)
		except Exception:
			pass
		kernel32.CloseHandle(self.handle)
		for h in (self._readEvent, self._writeEvent, self._stop):
			kernel32.CloseHandle(h)


# ====================================================================== servidor de la tubería
def _userSidString() -> str:
	"""SID del usuario actual en texto (``S-1-5-21-...``)."""
	TOKEN_QUERY = 0x8
	TokenUser = 1
	advapi32.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
	advapi32.GetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)]
	advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.LPWSTR)]
	token = wt.HANDLE()
	_check(advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)), "OpenProcessToken")
	try:
		size = wt.DWORD(0)
		advapi32.GetTokenInformation(token, TokenUser, None, 0, ctypes.byref(size))
		buf = ctypes.create_string_buffer(size.value)
		_check(advapi32.GetTokenInformation(token, TokenUser, buf, size, ctypes.byref(size)), "GetTokenInformation")
		psid = ctypes.c_void_p.from_buffer(buf).value
		text = wt.LPWSTR()
		_check(advapi32.ConvertSidToStringSidW(psid, ctypes.byref(text)), "ConvertSidToStringSid")
		try:
			return str(text.value)
		finally:
			kernel32.LocalFree(text)
	finally:
		kernel32.CloseHandle(token)


class _SecurityAttributes:
	"""Solo el usuario actual y el sistema pueden abrir la tubería."""

	def __init__(self) -> None:
		self._sd = ctypes.c_void_p()
		self.sa: SECURITY_ATTRIBUTES | None = None
		try:
			sddl = f"D:P(A;;GA;;;{_userSidString()})(A;;GA;;;SY)"
			_check(advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(self._sd), None), "ConvertStringSecurityDescriptor")
			sa = SECURITY_ATTRIBUTES()
			sa.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
			sa.lpSecurityDescriptor = self._sd.value
			sa.bInheritHandle = False
			self.sa = sa
		except OSError:
			log.exception("No se pudo preparar la seguridad de la tubería; se usa la predeterminada")

	def pointer(self):
		return ctypes.byref(self.sa) if self.sa is not None else None

	def free(self) -> None:
		if self._sd.value:
			kernel32.LocalFree(self._sd)
			self._sd = ctypes.c_void_p()


class PipeListener:
	"""Acepta conexiones en la tubería de Tiresias (un hilo propio).

	``onConnection(stream, clientPid)`` se llama en ese hilo con cada
	conexión nueva; quien la recibe se encarga de ella (y de cerrarla).
	"""

	def __init__(self, name: str, onConnection, retryDelay: float = 5.0, messageMode: bool = False) -> None:
		self.name = name
		self.onConnection = onConnection
		self.retryDelay = retryDelay
		#: Tubería de mensajes (cada lectura devuelve una escritura completa,
		#: como el canal virtual). Solo para simular el canal en las pruebas.
		self.messageMode = messageMode
		self._stop = kernel32.CreateEventW(None, True, False, None)
		self._thread: threading.Thread | None = None
		self._sec: _SecurityAttributes | None = None
		#: Último error al crear la tubería (``None`` si funciona).
		self.lastError: OSError | None = None
		self.listening = threading.Event()

	@property
	def running(self) -> bool:
		return self._thread is not None and self._thread.is_alive()

	def start(self) -> None:
		if self.running:
			return
		kernel32.ResetEvent(self._stop)
		self._sec = _SecurityAttributes()
		self._thread = threading.Thread(target=self._run, name="Escritorio remoto: tubería", daemon=True)
		self._thread.start()

	def stop(self, timeout: float = 3.0) -> None:
		kernel32.SetEvent(self._stop)
		t = self._thread
		if t is not None and t is not threading.current_thread():
			t.join(timeout)
		self._thread = None
		self.listening.clear()
		if self._sec is not None:
			self._sec.free()
			self._sec = None

	def _createInstance(self, first: bool) -> int:
		mode = PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED | (FILE_FLAG_FIRST_PIPE_INSTANCE if first else 0)
		h = kernel32.CreateNamedPipeW(
			self.name,
			mode,
			(PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE if self.messageMode else PIPE_TYPE_BYTE | PIPE_READMODE_BYTE) | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
			PIPE_UNLIMITED_INSTANCES,
			READ_SIZE,
			READ_SIZE,
			0,
			self._sec.pointer() if self._sec is not None else None,
		)
		if h == INVALID_HANDLE_VALUE or not h:
			err = ctypes.get_last_error()
			raise OSError(err, f"CreateNamedPipe {self.name}: {ctypes.FormatError(err).strip()}")
		return h

	def _run(self) -> None:
		event = kernel32.CreateEventW(None, True, False, None)
		first = True
		try:
			while kernel32.WaitForSingleObject(self._stop, 0) != WAIT_OBJECT_0:
				try:
					h = self._createInstance(first)
				except OSError as e:
					if self.lastError is None or self.lastError.errno != e.errno:
						log.warning("No se pudo crear la tubería de Escritorio remoto: %s", e)
					self.lastError = e
					self.listening.clear()
					first = True
					kernel32.WaitForSingleObject(self._stop, int(self.retryDelay * 1000))
					continue
				if first:
					log.info("Escuchando las conexiones de Escritorio remoto en %s", self.name)
				first = False
				self.lastError = None
				self.listening.set()
				ov = OVERLAPPED()
				ov.hEvent = event
				kernel32.ResetEvent(event)
				connected = bool(kernel32.ConnectNamedPipe(h, ctypes.byref(ov)))
				if not connected:
					err = ctypes.get_last_error()
					if err == ERROR_PIPE_CONNECTED:
						connected = True
					elif err == ERROR_IO_PENDING:
						handles = (wt.HANDLE * 2)(self._stop, event)
						w = kernel32.WaitForMultipleObjects(2, handles, False, INFINITE)
						n = wt.DWORD(0)
						if w == WAIT_OBJECT_0 + 1 and kernel32.GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(n), False):
							connected = True
						elif w != WAIT_OBJECT_0 + 1:
							kernel32.CancelIoEx(h, ctypes.byref(ov))
							kernel32.GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(n), True)
				if not connected:
					kernel32.CloseHandle(h)
					continue
				pid = wt.ULONG(0)
				kernel32.GetNamedPipeClientProcessId(h, ctypes.byref(pid))
				stream = OverlappedStream(h)
				try:
					self.onConnection(stream, int(pid.value))
				except Exception:
					log.exception("Error atendiendo una conexión de Escritorio remoto")
					stream.close()
		finally:
			kernel32.CloseHandle(event)
			self.listening.clear()


def connectPipe(name: str) -> OverlappedStream:
	"""Conecta como cliente a una tubería (lo usan las pruebas)."""
	h = kernel32.CreateFileW(name, GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
	if h == INVALID_HANDLE_VALUE or not h:
		err = ctypes.get_last_error()
		raise OSError(err, f"No se pudo abrir {name}: {ctypes.FormatError(err).strip()}")
	return OverlappedStream(h)


# ====================================================================== sesión remota
WTS_CURRENT_SESSION = 0xFFFFFFFF
WTS_CURRENT_SERVER_HANDLE = None
WTS_CHANNEL_OPTION_DYNAMIC = 0x1
WTSVirtualFileHandle = 1
WTSClientProtocolType = 16
#: Valores de ``WTSClientProtocolType``.
PROTOCOL_CONSOLE = 0
PROTOCOL_ICA = 1
PROTOCOL_RDP = 2

#: Tipos de sesión remota de :func:`remoteKind`.
KIND_RDP = "rdp"
KIND_CITRIX = "citrix"
KIND_HORIZON = "horizon"

HORIZON_BRIDGE_DLL = "vdp_rdpvcbridge.dll"

_wtsapi32 = None
_bridge: object = None  # None: sin comprobar; False: no hay puente de Horizon


def _wts():
	global _wtsapi32
	if _wtsapi32 is None:
		dll = ctypes.WinDLL("wtsapi32", use_last_error=True)
		dll.WTSVirtualChannelOpenEx.argtypes = [wt.DWORD, ctypes.c_char_p, wt.DWORD]
		dll.WTSVirtualChannelOpenEx.restype = wt.HANDLE
		dll.WTSVirtualChannelQuery.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wt.DWORD)]
		dll.WTSVirtualChannelQuery.restype = wt.BOOL
		dll.WTSVirtualChannelClose.argtypes = [wt.HANDLE]
		dll.WTSVirtualChannelClose.restype = wt.BOOL
		dll.WTSFreeMemory.argtypes = [ctypes.c_void_p]
		dll.WTSQuerySessionInformationW.argtypes = [wt.HANDLE, wt.DWORD, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wt.DWORD)]
		dll.WTSQuerySessionInformationW.restype = wt.BOOL
		_wtsapi32 = dll
	return _wtsapi32


class ChannelApi:
	"""Las cuatro funciones de canal virtual que usa :func:`openDynamicChannel`.

	Son las de ``wtsapi32`` (RDP y Citrix, que atiende la misma API dentro de
	las sesiones ICA) o las equivalentes ``VDP_*`` del puente de Omnissa
	Horizon (``vdp_rdpvcbridge.dll``, sesiones Blast y PCoIP).
	"""

	def __init__(self, openEx, query, close, freeMemory, name: str = "WTS") -> None:
		self.openEx = openEx
		self.query = query
		self.close = close
		self.freeMemory = freeMemory
		self.name = name


def _wtsChannelApi() -> ChannelApi:
	wts = _wts()
	return ChannelApi(wts.WTSVirtualChannelOpenEx, wts.WTSVirtualChannelQuery, wts.WTSVirtualChannelClose, wts.WTSFreeMemory)


def _systemDir() -> str:
	buf = ctypes.create_unicode_buffer(260)
	kernel32.GetSystemDirectoryW(buf, 260)
	return buf.value


def _horizonBridge():
	"""``vdp_rdpvcbridge.dll`` del agente de Horizon (solo de la carpeta del sistema) o ``None``."""
	global _bridge
	if _bridge is None:
		_bridge = False
		path = os.path.join(_systemDir(), HORIZON_BRIDGE_DLL)
		if os.path.isfile(path):
			try:
				dll = ctypes.CDLL(path, use_last_error=True)
				dll.VDP_VirtualChannelOpenEx.argtypes = [wt.DWORD, ctypes.c_char_p, wt.DWORD]
				dll.VDP_VirtualChannelOpenEx.restype = wt.HANDLE
				dll.VDP_VirtualChannelQuery.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wt.DWORD)]
				dll.VDP_VirtualChannelQuery.restype = wt.BOOL
				dll.VDP_VirtualChannelClose.argtypes = [wt.HANDLE]
				dll.VDP_VirtualChannelClose.restype = wt.BOOL
				dll.VDP_FreeMemory.argtypes = [ctypes.c_void_p]
				dll.VDP_FreeMemory.restype = None
				dll.VDP_IsHorizonSession.argtypes = [wt.DWORD]
				dll.VDP_IsHorizonSession.restype = wt.BOOL
				_bridge = dll
				log.info("Puente de canales virtuales de Horizon disponible: %s", path)
			except (OSError, AttributeError):
				log.warning("No se pudo cargar %s", path, exc_info=True)
	return _bridge or None


def isHorizonSession() -> bool:
	"""``True`` dentro de una sesión de Omnissa Horizon (Blast o PCoIP) con el agente instalado."""
	bridge = _horizonBridge()
	if bridge is None:
		return False
	try:
		return bool(bridge.VDP_IsHorizonSession(WTS_CURRENT_SESSION))
	except OSError:
		return False


def channelApi() -> ChannelApi:
	"""API de canal para la sesión actual: la del puente de Horizon en sus sesiones; si no, ``wtsapi32``."""
	if isHorizonSession():
		b = _horizonBridge()
		return ChannelApi(b.VDP_VirtualChannelOpenEx, b.VDP_VirtualChannelQuery, b.VDP_VirtualChannelClose, b.VDP_FreeMemory, name="VDP")
	return _wtsChannelApi()


def clientProtocol() -> int | None:
	"""``WTSClientProtocolType`` de la sesión actual (0 consola, 1 ICA/Citrix, 2 RDP)."""
	try:
		wts = _wts()
		buf = ctypes.c_void_p()
		size = wt.DWORD(0)
		if wts.WTSQuerySessionInformationW(WTS_CURRENT_SERVER_HANDLE, WTS_CURRENT_SESSION, WTSClientProtocolType, ctypes.byref(buf), ctypes.byref(size)):
			try:
				return int(ctypes.c_ushort.from_address(buf.value).value) if buf.value else None
			finally:
				wts.WTSFreeMemory(buf)
	except Exception:
		log.debug("WTSQuerySessionInformation falló", exc_info=True)
	return None


def remoteKind() -> str:
	"""``"citrix"``, ``"horizon"``, ``"rdp"`` o ``""`` (sesión local)."""
	protocol = clientProtocol()
	if protocol == PROTOCOL_ICA:
		return KIND_CITRIX
	if isHorizonSession():
		return KIND_HORIZON
	if protocol == PROTOCOL_RDP:
		return KIND_RDP
	try:
		if user32.GetSystemMetrics(SM_REMOTESESSION):
			return KIND_RDP
	except Exception:
		pass
	return ""


def isRemoteSession() -> bool:
	"""``True`` si Tiresias se ejecuta en una sesión remota con canales virtuales.

	Sesiones de Escritorio remoto (RDP), de Citrix (ICA) y de Omnissa Horizon.
	Con algunos adaptadores gráficos (RemoteFX, escritorios Citrix de una sola
	sesión) ``SM_REMOTESESSION`` es 0: por eso se consulta también el
	protocolo del cliente.
	"""
	try:
		if user32.GetSystemMetrics(SM_REMOTESESSION):
			return True
	except Exception:
		pass
	return remoteKind() != ""


def openDynamicChannel(name: str = CHANNEL_NAME, api: ChannelApi | None = None) -> OverlappedStream:
	"""Abre el canal virtual dinámico con el cliente de esta sesión.

	Bloquea hasta que el cliente responde: llámala en un hilo propio. Lanza
	:class:`OSError` si el cliente no tiene el complemento (o, en Citrix, si
	la directiva de la lista de permitidos no deja abrir el canal).
	"""
	if api is None:
		api = channelApi()
	h = api.openEx(WTS_CURRENT_SESSION, name.encode("ascii"), WTS_CHANNEL_OPTION_DYNAMIC)
	if not h:
		err = ctypes.get_last_error()
		raise OSError(err, f"{api.name}VirtualChannelOpenEx: {ctypes.FormatError(err).strip()}")
	try:
		buf = ctypes.c_void_p()
		size = wt.DWORD(0)
		_check(api.query(h, WTSVirtualFileHandle, ctypes.byref(buf), ctypes.byref(size)), f"{api.name}VirtualChannelQuery")
		try:
			fileHandle = wt.HANDLE.from_address(buf.value).value
			dup = wt.HANDLE()
			proc = kernel32.GetCurrentProcess()
			_check(kernel32.DuplicateHandle(proc, fileHandle, proc, ctypes.byref(dup), 0, False, DUPLICATE_SAME_ACCESS), "DuplicateHandle")
		finally:
			api.freeMemory(buf)
	finally:
		api.close(h)
	return OverlappedStream(dup.value, pduHeader=True)


# ====================================================================== procesos del cliente
class PROCESSENTRY32W(ctypes.Structure):
	_fields_ = [
		("dwSize", wt.DWORD),
		("cntUsage", wt.DWORD),
		("th32ProcessID", wt.DWORD),
		("th32DefaultHeapID", ctypes.c_void_p),
		("th32ModuleID", wt.DWORD),
		("cntThreads", wt.DWORD),
		("th32ParentProcessID", wt.DWORD),
		("pcPriClassBase", ctypes.c_long),
		("dwFlags", wt.DWORD),
		("szExeFile", wt.WCHAR * 260),
	]


TH32CS_SNAPPROCESS = 0x2
kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
kernel32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32FirstW.restype = wt.BOOL
kernel32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.restype = wt.BOOL
kernel32.GetSystemDirectoryW.argtypes = [wt.LPWSTR, wt.UINT]
kernel32.GetSystemDirectoryW.restype = wt.UINT


def processInfo(pid: int) -> tuple[str, int]:
	"""Nombre del ejecutable y PID del proceso padre (``("", 0)`` si no existe).

	Omnissa Horizon Client carga los complementos en un proceso hijo de la
	ventana (``vmware-remotemks.exe``): el braille sigue a la ventana del
	proceso del canal o a la de su padre.
	"""
	snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
	if snap == INVALID_HANDLE_VALUE or not snap:
		return ("", 0)
	try:
		entry = PROCESSENTRY32W()
		entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
		ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
		while ok:
			if entry.th32ProcessID == pid:
				return (entry.szExeFile, int(entry.th32ParentProcessID))
			ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
	finally:
		kernel32.CloseHandle(snap)
	return ("", 0)


def openPipeAsChannel(name: str) -> OverlappedStream:
	"""Canal simulado para pruebas: una tubería de mensajes con las mismas cabeceras.

	El otro extremo debe crearla con ``PipeListener(..., messageMode=True)``
	y escribir cada trozo con su ``CHANNEL_PDU_HEADER``.
	"""
	stream = connectPipe(name)
	mode = wt.DWORD(PIPE_READMODE_MESSAGE)
	if not kernel32.SetNamedPipeHandleState(stream.handle, ctypes.byref(mode), None, None):
		err = ctypes.get_last_error()
		stream.close()
		raise OSError(err, f"SetNamedPipeHandleState: {ctypes.FormatError(err).strip()}")
	stream.pduHeader = True
	return stream
