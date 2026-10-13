"""Reproductor de audio PCM con salida WASAPI (modo compartido) o waveOut.

Todo el audio de Tiresias (voz de los sintetizadores, tonos y sonidos) pasa
por :class:`WavePlayer`, de modo que el volumen, la división de sonido
(izquierda/derecha) y la detención inmediata funcionan igual para todos.

Cada reproductor tiene su propio hilo, que:

- envía el audio al dispositivo en bloques pequeños (para poder cortar al
  instante);
- ejecuta las retrollamadas (por ejemplo, índices de voz) cuando el audio
  anterior a ellas ha sonado de verdad;
- mantiene el dispositivo despierto un rato tras hablar (``keepAudioAwakeSeconds``),
  opcionalmente con un ruido blanco muy suave (``whiteNoiseVolume``) para
  los dispositivos que se apagan con el silencio digital (#18435);
- se registra en MMCSS («Audio») y usa el tamaño de búfer elegido para
  evitar cortes y crujidos con la CPU muy cargada (#7769).

Salidas:

- **WASAPI** en modo compartido con conversión automática de formato: baja
  latencia y nombres de dispositivo completos.
- **waveOut**: la API clásica, por compatibilidad con controladores antiguos.
"""

from __future__ import annotations

import array
import collections
import ctypes
import random
import threading
import time
from ctypes import wintypes
from typing import Callable

from ..log import getLogger

log = getLogger("audio")

try:  # numpy acelera el volumen y el paneo; si no está, se usa array.
	import numpy as _np
except Exception:  # pragma: no cover - numpy es una dependencia habitual
	_np = None

winmm = ctypes.WinDLL("winmm")
kernel32 = ctypes.WinDLL("kernel32")

WAVE_MAPPER = 0xFFFFFFFF
WAVE_FORMAT_PCM = 1
CALLBACK_EVENT = 0x00050000
WHDR_DONE = 0x00000001
MMSYSERR_NOERROR = 0
MAXPNAMELEN = 32
DRV_QUERYFUNCTIONINSTANCEID = 0x0811
DRV_QUERYFUNCTIONINSTANCEIDSIZE = 0x0812

# WASAPI
AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY = 0x08000000

#: Modos de salida disponibles.
OUTPUT_MODES = ("wasapi", "waveOut")

#: Tamaños de búfer: (duración de cada bloque en ms, bloques waveOut en cola, búfer WASAPI en ms).
BUFFER_SIZES: dict[str, tuple[int, int, int]] = {
	"low": (30, 3, 60),
	"normal": (60, 4, 120),
	"high": (80, 8, 400),
}


class WAVEFORMATEX(ctypes.Structure):
	_fields_ = [
		("wFormatTag", wintypes.WORD),
		("nChannels", wintypes.WORD),
		("nSamplesPerSec", wintypes.DWORD),
		("nAvgBytesPerSec", wintypes.DWORD),
		("nBlockAlign", wintypes.WORD),
		("wBitsPerSample", wintypes.WORD),
		("cbSize", wintypes.WORD),
	]


class WAVEHDR(ctypes.Structure):
	pass


WAVEHDR._fields_ = [
	("lpData", ctypes.c_void_p),
	("dwBufferLength", wintypes.DWORD),
	("dwBytesRecorded", wintypes.DWORD),
	("dwUser", ctypes.c_size_t),
	("dwFlags", wintypes.DWORD),
	("dwLoops", wintypes.DWORD),
	("lpNext", ctypes.POINTER(WAVEHDR)),
	("reserved", ctypes.c_size_t),
]


class WAVEOUTCAPSW(ctypes.Structure):
	_fields_ = [
		("wMid", wintypes.WORD),
		("wPid", wintypes.WORD),
		("vDriverVersion", wintypes.UINT),
		("szPname", wintypes.WCHAR * MAXPNAMELEN),
		("dwFormats", wintypes.DWORD),
		("wChannels", wintypes.WORD),
		("wReserved1", wintypes.WORD),
		("dwSupport", wintypes.DWORD),
	]


HWAVEOUT = wintypes.HANDLE
winmm.waveOutOpen.argtypes = [
	ctypes.POINTER(HWAVEOUT),
	wintypes.UINT,
	ctypes.POINTER(WAVEFORMATEX),
	ctypes.c_size_t,
	ctypes.c_size_t,
	wintypes.DWORD,
]
winmm.waveOutPrepareHeader.argtypes = [HWAVEOUT, ctypes.POINTER(WAVEHDR), wintypes.UINT]
winmm.waveOutUnprepareHeader.argtypes = [HWAVEOUT, ctypes.POINTER(WAVEHDR), wintypes.UINT]
winmm.waveOutWrite.argtypes = [HWAVEOUT, ctypes.POINTER(WAVEHDR), wintypes.UINT]
winmm.waveOutReset.argtypes = [HWAVEOUT]
winmm.waveOutClose.argtypes = [HWAVEOUT]
winmm.waveOutPause.argtypes = [HWAVEOUT]
winmm.waveOutRestart.argtypes = [HWAVEOUT]
winmm.waveOutGetNumDevs.restype = wintypes.UINT
winmm.waveOutGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.POINTER(WAVEOUTCAPSW), wintypes.UINT]
winmm.waveOutMessage.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p]
winmm.waveOutMessage.restype = wintypes.UINT

kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.SetEvent.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.GetCurrentThread.restype = wintypes.HANDLE
kernel32.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]

THREAD_PRIORITY_HIGHEST = 2

try:
	_avrt = ctypes.WinDLL("avrt")
	_avrt.AvSetMmThreadCharacteristicsW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
	_avrt.AvSetMmThreadCharacteristicsW.restype = wintypes.HANDLE
	_avrt.AvRevertMmThreadCharacteristics.argtypes = [wintypes.HANDLE]
except OSError:  # pragma: no cover - avrt existe desde Vista
	_avrt = None


# ----------------------------------------------------- dispositivos
def _waveOutNames() -> list[str]:
	names = []
	for i in range(winmm.waveOutGetNumDevs()):
		caps = WAVEOUTCAPSW()
		if winmm.waveOutGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == MMSYSERR_NOERROR:
			names.append(caps.szPname)
	return names


def _waveOutEndpointId(index: int) -> str:
	"""Identificador del punto final de Core Audio que corresponde a un dispositivo waveOut."""
	size = wintypes.ULONG(0)
	if winmm.waveOutMessage(ctypes.c_void_p(index), DRV_QUERYFUNCTIONINSTANCEIDSIZE, ctypes.byref(size), None) != MMSYSERR_NOERROR:
		return ""
	if not size.value:
		return ""
	buf = ctypes.create_unicode_buffer(size.value // 2 + 1)
	if winmm.waveOutMessage(ctypes.c_void_p(index), DRV_QUERYFUNCTIONINSTANCEID, buf, ctypes.c_void_p(size.value)) != MMSYSERR_NOERROR:
		return ""
	return buf.value


def getOutputDevices() -> list[str]:
	"""Nombres completos de los dispositivos de salida activos.

	Se obtienen de Core Audio, así que no se cortan a 31 caracteres como los
	de waveOut. Si Core Audio no está disponible se usan los de waveOut.
	"""
	try:
		from . import core_audio

		names = [d.name for d in core_audio.getDevices(core_audio.eRender)]
		if names:
			return names
	except Exception:
		log.debug("Core Audio no disponible para listar dispositivos", exc_info=True)
	return _waveOutNames()


def _waveOutDeviceIdFromName(name: str) -> int:
	if not name:
		return WAVE_MAPPER
	names = _waveOutNames()
	# 1) Por el identificador del punto final (nombre completo de Core Audio).
	try:
		from . import core_audio

		dev = core_audio.findDevice(name)
	except Exception:
		dev = None
	if dev is not None:
		for i in range(len(names)):
			if _waveOutEndpointId(i) == dev.id:
				return i
	# 2) Por el nombre (cortado a 31 caracteres en waveOut).
	for i, n in enumerate(names):
		if n == name or (len(n) >= MAXPNAMELEN - 1 and name.startswith(n)):
			return i
	return WAVE_MAPPER


# ----------------------------------------------------- ajustes globales de salida
class OutputSettings:
	"""Volumen y paneo comunes. Los modifica el módulo de división de sonido."""

	#: Ganancias (izquierda, derecha) aplicadas a todo el audio de Tiresias.
	channelGains: tuple[float, float] = (1.0, 1.0)
	#: Nombre completo del dispositivo de salida (vacío = predeterminado de Windows).
	deviceName: str = ""


def _conf(key: str, default):
	try:
		from ..config import conf

		return conf["audio"][key]
	except Exception:
		return default


def _keepAwakeSeconds() -> float:
	try:
		return float(_conf("keepAudioAwakeSeconds", 30))
	except (TypeError, ValueError):
		return 30.0


def _outputMode() -> str:
	mode = _conf("outputMode", "wasapi")
	return mode if mode in OUTPUT_MODES else "wasapi"


def _bufferSize() -> tuple[int, int, int]:
	return BUFFER_SIZES.get(_conf("bufferSize", "normal"), BUFFER_SIZES["normal"])


def _whiteNoiseVolume() -> int:
	try:
		return max(0, min(100, int(_conf("whiteNoiseVolume", 0))))
	except (TypeError, ValueError):
		return 0


def _scaleSamples(samples: array.array, gain: float) -> array.array:
	if gain == 1.0:
		return samples
	if gain <= 0.0:
		return array.array("h", bytes(len(samples) * 2))
	if _np is not None:
		a = _np.frombuffer(samples.tobytes(), dtype=_np.int16).astype(_np.float32) * gain
		return array.array("h", _np.clip(a, -32768, 32767).astype(_np.int16).tobytes())
	return array.array("h", [max(-32768, min(32767, int(s * gain))) for s in samples])


def _applyGains(data: bytes, channels: int, volume: float, gains: tuple[float, float] | None = None) -> bytes:
	"""Convierte PCM 16 bits mono/estéreo a estéreo aplicando volumen y paneo."""
	gl, gr = gains if gains is not None else OutputSettings.channelGains
	gl *= volume
	gr *= volume
	samples = array.array("h")
	samples.frombytes(data[: len(data) - (len(data) % 2)])
	channels = max(1, int(channels))
	if channels > 1 and len(samples) % channels:
		# Trama incompleta al final de un bloque: se descarta (si no, los
		# canales quedarían desparejados y la asignación de abajo fallaría).
		del samples[len(samples) - len(samples) % channels :]
	if channels == 1:
		left = samples
		right = samples
	else:
		# Estéreo o más canales (se usan los dos primeros).
		left = samples[0::channels]
		right = samples[1::channels]
	left = _scaleSamples(left, gl)
	right = left if (channels == 1 and gl == gr) else _scaleSamples(right, gr)
	out = array.array("h", bytes(len(left) * 4))
	out[0::2] = left
	out[1::2] = right[: len(left)]
	return out.tobytes()


# ----------------------------------------------------- salidas
class _Backend:
	"""Salida de audio estéreo de 16 bits. Solo la usa el hilo del reproductor."""

	deviceName = ""
	mode = ""

	def __init__(self, rate: int, event: int) -> None:
		self.rate = rate
		self.event = event
		self.written = 0  # tramas enviadas desde la última reinicialización

	def open(self, deviceName: str) -> None:
		raise NotImplementedError

	def write(self, data: bytes) -> int:
		"""Envía tantas tramas como quepan; devuelve cuántas se aceptaron."""
		raise NotImplementedError

	def played(self) -> int:
		"""Tramas que ya han sonado desde la última reinicialización."""
		raise NotImplementedError

	def reset(self) -> None:
		raise NotImplementedError

	def pause(self, switch: bool) -> None:
		raise NotImplementedError

	def close(self) -> None:
		raise NotImplementedError

	def stillValid(self) -> bool:
		"""``False`` si hay que volver a abrir (p. ej. cambió el dispositivo predeterminado)."""
		return True


class _WaveOutBackend(_Backend):
	mode = "waveOut"

	def __init__(self, rate: int, event: int) -> None:
		super().__init__(rate, event)
		self.handle: HWAVEOUT | None = None
		self.pending: list[tuple[WAVEHDR, ctypes.Array, int]] = []
		self.done = 0
		self.maxPending = _bufferSize()[1]

	def open(self, deviceName: str) -> None:
		fmt = WAVEFORMATEX(WAVE_FORMAT_PCM, 2, self.rate, self.rate * 4, 4, 16, 0)
		h = HWAVEOUT()
		dev = _waveOutDeviceIdFromName(deviceName)
		res = winmm.waveOutOpen(ctypes.byref(h), dev, ctypes.byref(fmt), self.event, 0, CALLBACK_EVENT)
		if res != MMSYSERR_NOERROR and dev != WAVE_MAPPER:
			res = winmm.waveOutOpen(ctypes.byref(h), WAVE_MAPPER, ctypes.byref(fmt), self.event, 0, CALLBACK_EVENT)
		if res != MMSYSERR_NOERROR:
			raise OSError(f"waveOutOpen falló ({res})")
		self.handle = h
		self.deviceName = deviceName

	def _reap(self, force: bool = False) -> None:
		while self.pending:
			hdr, buf, frames = self.pending[0]
			if not force and not (hdr.dwFlags & WHDR_DONE):
				break
			self.pending.pop(0)
			if self.handle is not None:
				winmm.waveOutUnprepareHeader(self.handle, ctypes.byref(hdr), ctypes.sizeof(WAVEHDR))
			self.done += frames

	def write(self, data: bytes) -> int:
		self._reap()
		if len(self.pending) >= self.maxPending:
			return 0
		frames = len(data) // 4
		buf = ctypes.create_string_buffer(data, len(data))
		hdr = WAVEHDR()
		hdr.lpData = ctypes.cast(buf, ctypes.c_void_p)
		hdr.dwBufferLength = len(data)
		hdr.dwFlags = 0
		winmm.waveOutPrepareHeader(self.handle, ctypes.byref(hdr), ctypes.sizeof(WAVEHDR))
		res = winmm.waveOutWrite(self.handle, ctypes.byref(hdr), ctypes.sizeof(WAVEHDR))
		if res != MMSYSERR_NOERROR:
			winmm.waveOutUnprepareHeader(self.handle, ctypes.byref(hdr), ctypes.sizeof(WAVEHDR))
			raise OSError(f"waveOutWrite falló ({res})")
		self.pending.append((hdr, buf, frames))
		self.written += frames
		return frames

	def played(self) -> int:
		self._reap()
		return self.done

	def reset(self) -> None:
		if self.handle is not None:
			winmm.waveOutReset(self.handle)
			winmm.waveOutRestart(self.handle)
		self._reap(force=True)
		self.written = 0
		self.done = 0

	def pause(self, switch: bool) -> None:
		if self.handle is None:
			return
		if switch:
			winmm.waveOutPause(self.handle)
		else:
			winmm.waveOutRestart(self.handle)

	def close(self) -> None:
		if self.handle is None:
			return
		winmm.waveOutReset(self.handle)
		self._reap(force=True)
		winmm.waveOutClose(self.handle)
		self.handle = None


class _WasapiBackend(_Backend):
	mode = "wasapi"

	def __init__(self, rate: int, event: int) -> None:
		super().__init__(rate, event)
		self.client = None
		self.render = None
		self.bufferFrames = 0
		self.started = False
		self.deviceId = ""
		self.followsDefault = False
		self._lastCheck = 0.0

	def open(self, deviceName: str) -> None:
		import comtypes

		from . import core_audio

		core_audio.ensureCom()
		try:
			dev = core_audio.findDevice(deviceName) if deviceName else None
			imm = core_audio.getIMMDevice(dev.id if dev else None, core_audio.eRender, core_audio.eConsole)
			self.deviceId = core_audio.deviceId(imm)
			self.followsDefault = dev is None
			unk = imm.Activate(ctypes.byref(core_audio.IAudioClient._iid_), core_audio.CLSCTX_ALL, None)
			client = unk.QueryInterface(core_audio.IAudioClient)
			fmt = core_audio.WAVEFORMATEX(WAVE_FORMAT_PCM, 2, self.rate, self.rate * 4, 4, 16, 0)
			flags = AUDCLNT_STREAMFLAGS_EVENTCALLBACK | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY
			bufferMs = _bufferSize()[2]
			client.Initialize(AUDCLNT_SHAREMODE_SHARED, flags, bufferMs * 10000, 0, ctypes.byref(fmt), None)
			client.SetEventHandle(self.event)
			self.bufferFrames = client.GetBufferSize()
			svc = client.GetService(ctypes.byref(core_audio.IAudioRenderClient._iid_))
			self.render = svc.QueryInterface(core_audio.IAudioRenderClient)
			self.client = client
		except comtypes.COMError as e:
			self.client = self.render = None
			raise OSError(f"WASAPI no disponible: {e}") from e
		self.deviceName = deviceName
		self.started = False
		self.written = 0
		self._lastCheck = time.monotonic()

	def write(self, data: bytes) -> int:
		import comtypes

		try:
			padding = self.client.GetCurrentPadding()
			free = self.bufferFrames - padding
			frames = min(free, len(data) // 4)
			if frames <= 0:
				if not self.started:
					self.client.Start()
					self.started = True
				return 0
			ptr = self.render.GetBuffer(frames)
			ctypes.memmove(ptr, data, frames * 4)
			self.render.ReleaseBuffer(frames, 0)
			self.written += frames
			if not self.started:
				self.client.Start()
				self.started = True
			return frames
		except comtypes.COMError as e:
			raise OSError(f"Error de WASAPI: {e}") from e

	def played(self) -> int:
		import comtypes

		if self.client is None:
			return self.written
		try:
			return self.written - self.client.GetCurrentPadding()
		except comtypes.COMError:
			return self.written

	def reset(self) -> None:
		import comtypes

		if self.client is not None:
			try:
				self.client.Stop()
				self.client.Reset()
			except comtypes.COMError:
				log.debug("Error reiniciando WASAPI", exc_info=True)
		self.started = False
		self.written = 0

	def pause(self, switch: bool) -> None:
		import comtypes

		if self.client is None:
			return
		try:
			if switch and self.started:
				self.client.Stop()
				self.started = False
			elif not switch and not self.started and self.written:
				self.client.Start()
				self.started = True
		except comtypes.COMError:
			log.debug("Error pausando WASAPI", exc_info=True)

	def close(self) -> None:
		import comtypes

		if self.client is not None:
			try:
				self.client.Stop()
			except comtypes.COMError:
				pass
		self.render = None
		self.client = None
		self.started = False

	def stillValid(self) -> bool:
		# Si se sigue al dispositivo predeterminado y Windows lo ha cambiado,
		# hay que abrir el nuevo (como mucho una comprobación cada 2 s).
		if not self.followsDefault:
			return True
		now = time.monotonic()
		if now - self._lastCheck < 2.0:
			return True
		self._lastCheck = now
		from . import core_audio

		current = core_audio.getDefaultDeviceId(core_audio.eRender, core_audio.eConsole)
		return not current or current == self.deviceId


# ----------------------------------------------------- primer flujo
_streamOpened = False
_streamOpenedHandlers: list[Callable[[], None]] = []


def _notifyStreamOpened() -> None:
	"""Avisa (una vez) de que se ha abierto el primer flujo de audio de Tiresias.

	Hasta entonces Windows no ha creado la sesión de audio propia, así que lo
	que dependa de ella (quitarle el silencio, #3049) se hace en este momento.
	"""
	global _streamOpened
	if _streamOpened:
		return
	_streamOpened = True
	for handler in list(_streamOpenedHandlers):
		try:
			handler()
		except Exception:
			log.exception("Error en el aviso del primer flujo de audio")


def onFirstStream(handler: Callable[[], None]) -> None:
	"""Llama a ``handler`` cuando se abra el primer flujo de audio (o ya, si se abrió)."""
	if _streamOpened:
		handler()
	else:
		_streamOpenedHandlers.append(handler)


# ----------------------------------------------------- reproductor
class _Item:
	__slots__ = ("data", "callback")

	def __init__(self, data: bytes | None, callback: Callable[[], None] | None) -> None:
		self.data = data
		self.callback = callback


class WavePlayer:
	"""Reproductor PCM 16 bits. Siempre abre el dispositivo en estéreo.

	``keepAwake``: si es ``True`` (voz), mientras el dispositivo sigue abierto
	tras hablar se reproduce el ruido blanco configurado.
	"""

	def __init__(
		self,
		samplesPerSec: int,
		channels: int = 1,
		bitsPerSample: int = 16,
		name: str = "player",
		onIdle: Callable[[], None] | None = None,
		keepAwake: bool = True,
	) -> None:
		if bitsPerSample != 16:
			raise ValueError("Solo se admite PCM de 16 bits")
		self.samplesPerSec = samplesPerSec
		self.inChannels = channels
		self.name = name
		self.volume = 1.0
		#: Silencia la salida sin detener la reproducción (los índices y las
		#: retrollamadas siguen llegando). Lo usa la voz por Escritorio remoto.
		self.muted = False
		self.onIdle = onIdle
		self.keepAwake = keepAwake
		self._items: collections.deque[_Item] = collections.deque()
		self._lock = threading.RLock()
		self._event = kernel32.CreateEventW(None, False, False, None)
		self._backend: _Backend | None = None
		# Modo y búfer pedidos (configuración) al abrir la salida actual: si se
		# abrió la de reserva (WASAPI <-> waveOut), se acepta mientras el modo
		# configurado no cambie, en lugar de reabrir en cada bloque de audio.
		self._backendFor = ""
		self._marks: list[tuple[int, Callable[[], None]]] = []
		self._generation = 0
		self._resetRequested = False
		self._pauseRequested: bool | None = None
		self._paused = False
		self._lastActivity = 0.0
		self._realEnd = 0  # posición (en tramas) del final del último audio real
		self._noise: bytes = b""
		self._noiseLevel = -1
		self._running = True
		self._busy = False
		self._audible = False  # queda audio real por sonar (lo actualiza el hilo)
		#: Bytes (formato de entrada) encolados que aún no se han enviado a la salida.
		self._pendingBytes = 0
		self._bytesPerSec = max(1, samplesPerSec * channels * 2)
		#: Fallos de salida seguidos (para no llenar el registro sin dispositivo).
		self._errorStreak = 0
		self._thread = threading.Thread(target=self._run, name=f"WavePlayer-{name}", daemon=True)
		self._thread.start()

	# ------------------------------------------------------------ API pública
	def feed(self, data: bytes | None, onDone: Callable[[], None] | None = None) -> None:
		"""Encola audio (o solo una retrollamada si ``data`` es ``None``)."""
		with self._lock:
			self._items.append(_Item(data, onDone))
			if data:
				self._pendingBytes += len(data)
		kernel32.SetEvent(self._event)

	def queuedSeconds(self) -> float:
		"""Segundos de audio encolados que aún no se han enviado a la salida."""
		with self._lock:
			return self._pendingBytes / self._bytesPerSec

	def isPaused(self) -> bool:
		with self._lock:
			return bool(self._paused if self._pauseRequested is None else self._pauseRequested)

	def stop(self) -> None:
		"""Detiene la reproducción y descarta todo lo pendiente."""
		with self._lock:
			self._generation += 1
			self._items.clear()
			self._pendingBytes = 0
			self._resetRequested = True
			if self._paused:
				self._pauseRequested = False
		kernel32.SetEvent(self._event)

	def pause(self, switch: bool) -> None:
		with self._lock:
			self._pauseRequested = bool(switch)
		kernel32.SetEvent(self._event)

	def isPlaying(self) -> bool:
		with self._lock:
			return bool(self._items or self._marks or self._busy or self._audible)

	def terminate(self) -> None:
		self._running = False
		self.stop()
		self._thread.join(2)
		if self._thread.is_alive():
			# El hilo sigue dentro de una llamada a la salida (controlador
			# colgado): cerrar ahora el evento dejaría a la salida señalando un
			# handle cerrado (o reutilizado por otro objeto). Se deja abierto.
			log.warning("El reproductor %s no terminó a tiempo", self.name)
			return
		kernel32.CloseHandle(self._event)

	@property
	def outputMode(self) -> str:
		"""Salida que se está usando ahora (``"wasapi"``, ``"waveOut"`` o ``""``)."""
		b = self._backend
		return b.mode if b is not None else ""

	# ------------------------------------------------------------ hilo interno
	def _enterMmcss(self):
		handle = None
		if _avrt is not None:
			idx = wintypes.DWORD(0)
			try:
				handle = _avrt.AvSetMmThreadCharacteristicsW("Audio", ctypes.byref(idx))
			except OSError:
				handle = None
		if not handle:
			kernel32.SetThreadPriority(kernel32.GetCurrentThread(), THREAD_PRIORITY_HIGHEST)
		return handle

	def _openBackend(self) -> _Backend:
		"""Abre (o reabre) la salida si cambió el dispositivo o el modo."""
		b = self._backend
		mode = _outputMode()
		device = OutputSettings.deviceName
		# El tamaño del búfer se fija al abrir la salida: si cambia en Opciones,
		# se reabre (en el siguiente bloque de audio, sin reiniciar).
		wanted = f"{mode}|{_conf('bufferSize', 'normal')}"
		# El cambio del dispositivo predeterminado se sigue también a mitad de
		# una lectura (con retrollamadas pendientes), como NVDA: si no, la
		# lectura continua seguiría por los altavoces tras conectar unos
		# auriculares. stillValid() lo comprueba como mucho cada 2 s.
		if b is not None and b.deviceName == device and self._backendFor == wanted and b.stillValid():
			return b
		# Las retrollamadas del audio que ya no sonará en la salida anterior
		# (p. ej. los índices de voz) se ejecutan: si se perdieran, el gestor
		# de voz esperaría para siempre el final de esos enunciados.
		self._closeBackend(fireMarks=True)
		order = [mode] + [m for m in OUTPUT_MODES if m != mode]
		lastError: Exception | None = None
		for m in order:
			cls = _WasapiBackend if m == "wasapi" else _WaveOutBackend
			nb = cls(self.samplesPerSec, self._event)
			try:
				nb.open(device)
			except OSError as e:
				lastError = e
				log.debug("No se pudo abrir la salida %s", m, exc_info=True)
				continue
			if m != mode:
				log.warning("Salida %s no disponible; se usa %s", mode, m)
			self._backend = nb
			self._backendFor = wanted
			self._realEnd = 0
			_notifyStreamOpened()
			# Si el usuario retiene la pausa, se mantiene en el nuevo dispositivo.
			if self._paused:
				nb.pause(True)
			return nb
		raise OSError(f"No hay salida de audio disponible: {lastError}")

	def _closeBackend(self, fireMarks: bool = False) -> None:
		"""Cierra la salida. Con ``fireMarks`` se ejecutan las retrollamadas pendientes.

		Solo una detención pedida (:meth:`stop`) descarta las retrollamadas; si
		la salida se cierra por un cambio de dispositivo o de modo o por un
		error (unos auriculares Bluetooth que se desconectan), el audio que
		faltaba ya no sonará, pero sus retrollamadas sí tienen que llegar.
		"""
		b = self._backend
		self._backend = None
		self._backendFor = ""
		with self._lock:
			pending = [cb for _pos, cb in self._marks] if fireMarks else []
			self._marks.clear()
		self._realEnd = 0
		if b is not None:
			try:
				b.close()
			except Exception:
				log.debug("Error cerrando la salida de audio", exc_info=True)
		for cb in pending:
			try:
				cb()
			except Exception:
				log.exception("Error en retrollamada de audio")

	def _fireMarks(self) -> None:
		b = self._backend
		if not self._marks:
			return
		played = b.played() if b is not None else 1 << 62
		ready = []
		with self._lock:
			while self._marks and self._marks[0][0] <= played:
				ready.append(self._marks.pop(0)[1])
		for cb in ready:
			try:
				cb()
			except Exception:
				log.exception("Error en retrollamada de audio")

	def _handleRequests(self) -> None:
		with self._lock:
			reset = self._resetRequested
			self._resetRequested = False
			pauseReq = self._pauseRequested
			self._pauseRequested = None
			if reset:
				self._marks.clear()
		b = self._backend
		if reset and b is not None:
			try:
				b.reset()
			except Exception:
				log.debug("Error deteniendo el audio", exc_info=True)
			self._realEnd = 0
		if pauseReq is not None and pauseReq != self._paused:
			self._paused = pauseReq
			if b is not None:
				try:
					b.pause(pauseReq)
				except Exception:
					log.debug("Error pausando el audio", exc_info=True)

	def _noiseChunk(self, frames: int) -> bytes:
		level = _whiteNoiseVolume()
		if level != self._noiseLevel or len(self._noise) < frames * 4:
			self._noiseLevel = level
			amp = int(32767 * 0.05 * level / 100)
			n = max(frames, int(self.samplesPerSec * 0.2))
			rnd = random.Random(1234)
			samples = array.array("h", (rnd.randint(-amp, amp) if amp else 0 for _ in range(n * 2)))
			self._noise = samples.tobytes()
		return self._noise[: frames * 4]

	def _idle(self) -> float:
		"""Tareas sin audio pendiente. Devuelve el tiempo de espera en segundos."""
		b = self._backend
		if b is None:
			self._audible = False
			return 0.5
		if self._marks:
			return 0.01
		now = time.monotonic()
		self._audible = b.played() < self._realEnd
		if self._audible:
			return 0.01
		awake = _keepAwakeSeconds()
		if self._lastActivity and now - self._lastActivity > awake:
			self._closeBackend()
			self._lastActivity = 0.0
			if self.onIdle:
				try:
					self.onIdle()
				except Exception:
					log.exception("Error en onIdle")
			return 0.5
		if self.keepAwake and not self._paused and _whiteNoiseVolume() > 0:
			# Ruido blanco suave: mantiene vivo el dispositivo (#18435).
			chunkMs = _bufferSize()[0]
			queued = b.written - b.played()
			target = int(self.samplesPerSec * chunkMs / 1000)
			if queued < target:
				try:
					b.write(self._noiseChunk(target - queued))
				except OSError:
					log.debug("Error escribiendo ruido blanco", exc_info=True)
			return chunkMs / 2000.0
		return 0.1

	def _writeItem(self, item: _Item, gen: int) -> None:
		chunkMs = _bufferSize()[0]
		bytesPerChunk = max(2, int(self.samplesPerSec * self.inChannels * 2 * chunkMs / 1000))
		bytesPerChunk -= bytesPerChunk % (2 * self.inChannels)
		data = item.data or b""
		b = self._openBackend()
		if b.played() >= self._realEnd and b.written > b.played():
			# Solo queda ruido blanco en cola: se descarta para no retrasar la voz.
			b.reset()
			self._realEnd = 0
		for i in range(0, len(data), bytesPerChunk):
			if gen != self._generation or not self._running:
				return
			stereo = _applyGains(data[i : i + bytesPerChunk], self.inChannels, 0.0 if self.muted else self.volume)
			offset = 0
			while offset < len(stereo):
				self._handleRequests()
				if gen != self._generation or not self._running:
					return
				b = self._backend
				if b is None:
					return
				if self._paused:
					accepted = 0
				else:
					accepted = b.write(stereo[offset:])
				offset += accepted * 4
				if accepted:
					self._realEnd = b.written
					self._lastActivity = time.monotonic()
				else:
					kernel32.WaitForSingleObject(self._event, 20)
				self._fireMarks()
		if item.callback is not None and gen == self._generation:
			with self._lock:
				self._marks.append((self._realEnd, item.callback))

	def _run(self) -> None:
		mmcss = self._enterMmcss()
		try:
			from . import core_audio

			core_audio.ensureCom()
		except Exception:
			pass
		while self._running:
			self._handleRequests()
			self._fireMarks()
			with self._lock:
				item = self._items.popleft() if self._items else None
				gen = self._generation
				self._busy = item is not None
				if item is not None and item.data:
					self._pendingBytes = max(0, self._pendingBytes - len(item.data))
			if item is None:
				timeout = self._idle()
				kernel32.WaitForSingleObject(self._event, int(timeout * 1000))
				continue
			try:
				if item.data:
					self._writeItem(item, gen)
				elif item.callback is not None:
					b = self._backend
					if b is None or b.played() >= self._realEnd:
						if gen == self._generation:
							try:
								item.callback()
							except Exception:
								log.exception("Error en retrollamada de audio")
					else:
						with self._lock:
							self._marks.append((self._realEnd, item.callback))
			except Exception as e:
				# Cualquier error (no solo de la salida: también un audio con un
				# formato inesperado) se registra y el hilo sigue vivo; si muriera,
				# todo lo que se encolase después se quedaría sin sonar.
				self._errorStreak += 1
				if self._errorStreak <= 3:
					log.exception("Error de audio en %s", self.name)
				elif self._errorStreak in (10, 100) or self._errorStreak % 1000 == 0:
					log.warning("Error de audio en %s (%d seguidos): %s", self.name, self._errorStreak, e)
				if isinstance(e, OSError):
					self._closeBackend(fireMarks=True)
					time.sleep(0.2)
				elif item.callback is not None and gen == self._generation:
					# La retrollamada de un audio que no ha podido sonar también llega.
					try:
						item.callback()
					except Exception:
						log.exception("Error en retrollamada de audio")
			else:
				self._errorStreak = 0
			finally:
				self._busy = False
		self._closeBackend()
		if mmcss and _avrt is not None:
			try:
				_avrt.AvRevertMmThreadCharacteristics(mmcss)
			except OSError:
				pass
