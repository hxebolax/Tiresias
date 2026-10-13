"""Proceso auxiliar de 32 bits para las voces SAPI 5 de 32 bits y SAPI 4.

Tiresias es de 64 bits y no puede cargar motores de voz de 32 bits. El
auxiliar ``tiresiasSapi32.exe`` (``data\\synthDrivers\\sapi32``, código en
``sapi32_host``) los carga, sintetiza en memoria y devuelve PCM de 16 bits,
22050 Hz, mono por su salida estándar. Aquí está:

- :class:`HostProcess`: arranque, protocolo y parada del auxiliar.
- :class:`Host32SynthDriver`: base común de ``sapi5_32`` y ``sapi4`` (heredan
  de :class:`~tiresias.synth.base.AudioSynthDriver`, que se encarga del hilo,
  la cola, los índices, el volumen y la reproducción).
- Comprobaciones del registro (vista de 32 bits) para ``check()``.

Si el auxiliar muere, el enunciado siguiente arranca otro; si tampoco
funciona, el error llega al contador de fallos de la clase base y el
vigilante de ``synth/__init__.py`` cambia a otro sintetizador.
"""

from __future__ import annotations

import itertools
import os
import queue
import struct
import subprocess
import threading
import time
from collections import OrderedDict
from collections.abc import Callable

from ..log import getLogger
from .base import AudioSynthDriver, VoiceInfo

log = getLogger("synth.sapi32")

HOST_EXE = "tiresiasSapi32.exe"
PROTOCOL_VERSION = 1
CREATE_NO_WINDOW = 0x08000000
#: Bits de ``flags`` en la petición de hablar: la velocidad / el tono son válidos.
FLAG_RATE = 1
FLAG_PITCH = 2
#: Segundos que puede tardar en responder una petición (arranque, voces...).
REQUEST_TIMEOUT = 10.0
#: Segundos sin recibir nada del auxiliar mientras habla: se da por colgado.
IDLE_TIMEOUT = 15.0

CLSID_SPVOICE = "{96749377-3391-11D2-9EE3-00C04F797396}"
CLSID_TTS_ENUMERATOR = "{D67C0280-C743-11cd-80E5-00AA003E4B50}"
SAPI5_TOKENS = r"SOFTWARE\Microsoft\Speech\Voices\Tokens"
SAPI4_ENGINES = r"SOFTWARE\Voice\TextToSpeech\Engine"


class HostError(RuntimeError):
	"""El auxiliar de 32 bits no está, no arranca, ha muerto o no responde."""


def hostPath() -> str:
	from .. import paths

	return paths.programData("synthDrivers", "sapi32", HOST_EXE)


# ------------------------------------------------------------------ registro (vista de 32 bits)
def _openKey32(root, path: str):
	import winreg

	return winreg.OpenKey(root, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY)


def _keyExists32(root, path: str) -> bool:
	try:
		_openKey32(root, path).Close()
		return True
	except OSError:
		return False


def _subkeys32(root, path: str) -> list[str]:
	import winreg

	try:
		key = _openKey32(root, path)
	except OSError:
		return []
	out: list[str] = []
	try:
		i = 0
		while True:
			try:
				out.append(winreg.EnumKey(key, i))
			except OSError:
				break
			i += 1
	finally:
		key.Close()
	return out


def _clsidRegistered32(clsid: str) -> bool:
	import winreg

	return _keyExists32(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\InprocServer32") or _keyExists32(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\LocalServer32")


def sapi5Registry32() -> bool:
	"""``True`` si SAPI 5 de 32 bits está registrado y hay alguna voz de 32 bits."""
	import winreg

	if not _keyExists32(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{CLSID_SPVOICE}"):
		return False
	return bool(_subkeys32(winreg.HKEY_LOCAL_MACHINE, SAPI5_TOKENS) or _subkeys32(winreg.HKEY_CURRENT_USER, SAPI5_TOKENS))


def sapi4Registry() -> bool | None:
	"""Motores SAPI 4 según el registro: ``False`` si seguro que no hay ninguno.

	``None`` si el registro no basta para saberlo (entonces se pregunta al
	auxiliar). SAPI 4 solo existe en 32 bits.
	"""
	import winreg

	if not _clsidRegistered32(CLSID_TTS_ENUMERATOR):
		return False
	if not _keyExists32(winreg.HKEY_LOCAL_MACHINE, SAPI4_ENGINES):
		return None
	engines = _subkeys32(winreg.HKEY_LOCAL_MACHINE, SAPI4_ENGINES)
	# Restos de motores desinstalados: la clave queda, pero su CLSID ya no.
	return any(_clsidRegistered32(e) for e in engines)


# ------------------------------------------------------------------ proceso auxiliar
class HostProcess:
	"""Un proceso ``tiresiasSapi32.exe`` (modo ``sapi5`` o ``sapi4``)."""

	def __init__(self, mode: str, exe: str | None = None, launcher: Callable = subprocess.Popen) -> None:
		self.mode = mode
		self.exe = exe or hostPath()
		self._launcher = launcher
		self._proc = None
		self._frames: queue.Queue[tuple[int | None, bytes]] = queue.Queue()
		self._writeLock = threading.Lock()
		self._dead = False
		self.info: dict[str, str] = {}

	@property
	def pid(self) -> int | None:
		p = self._proc
		return getattr(p, "pid", None) if p is not None else None

	def isAlive(self) -> bool:
		p = self._proc
		return p is not None and not self._dead and p.poll() is None

	def start(self, timeout: float = REQUEST_TIMEOUT) -> None:
		if not os.path.isfile(self.exe):
			raise HostError(f"No se encuentra {self.exe}")
		cmd = [self.exe, self.mode, "--parent", str(os.getpid())]
		try:
			self._proc = self._launcher(
				cmd,
				stdin=subprocess.PIPE,
				stdout=subprocess.PIPE,
				stderr=subprocess.DEVNULL,
				cwd=os.path.dirname(self.exe),
				creationflags=CREATE_NO_WINDOW,
			)
		except OSError as e:
			raise HostError(f"No se pudo iniciar el auxiliar de 32 bits: {e}") from e
		threading.Thread(target=self._reader, args=(self._proc.stdout, self._frames), name=f"Sapi32-{self.mode}-lector", daemon=True).start()
		payload = self.request(b"H", b"", "h", timeout)
		self.info = dict(part.split("=", 1) for part in payload.decode("utf-8", "replace").split(";") if "=" in part)
		if self.info.get("mode") != self.mode or self.info.get("protocol") != str(PROTOCOL_VERSION):
			self.kill()
			raise HostError(f"Auxiliar de 32 bits incompatible: {self.info}")

	@staticmethod
	def _reader(stream, frames: queue.Queue) -> None:
		try:
			while True:
				head = stream.read(5)
				if len(head) < 5:
					break
				length, kind = struct.unpack("<IB", head)
				payload = stream.read(length - 1) if length > 1 else b""
				if len(payload) < length - 1:
					break
				frames.put((kind, payload))
		except (OSError, ValueError):
			pass
		frames.put((None, b""))

	def send(self, kind: bytes, payload: bytes = b"") -> None:
		p = self._proc
		if p is None or self._dead:
			raise HostError("El auxiliar de 32 bits no está en marcha")
		try:
			with self._writeLock:
				p.stdin.write(struct.pack("<IB", len(payload) + 1, kind[0]) + payload)
				p.stdin.flush()
		except (OSError, ValueError) as e:
			self._dead = True
			raise HostError(f"El auxiliar de 32 bits no acepta órdenes: {e}") from e

	def _next(self, timeout: float) -> tuple[int | None, bytes]:
		try:
			kind, payload = self._frames.get(timeout=timeout)
		except queue.Empty:
			raise TimeoutError from None
		if kind is None:
			self._dead = True
			# Para quien espere después (no se vuelve a leer nada).
			self._frames.put((None, b""))
			raise HostError(f"El auxiliar de 32 bits ha terminado (código {self._exitCode()})")
		return kind, payload

	def _exitCode(self):
		p = self._proc
		try:
			return p.wait(0.5) if p is not None else None
		except Exception:
			return None

	def request(self, kind: bytes, payload: bytes, expect: str, timeout: float = REQUEST_TIMEOUT) -> bytes:
		"""Envía una petición y espera su respuesta (se descarta el audio atrasado)."""
		self.send(kind, payload)
		deadline = time.monotonic() + timeout
		while True:
			left = deadline - time.monotonic()
			if left <= 0:
				self.kill()
				raise HostError("El auxiliar de 32 bits no responde")
			try:
				got, data = self._next(left)
			except TimeoutError:
				continue
			if got == ord(expect):
				return data

	def listVoices(self) -> list[tuple[str, str, str, str]]:
		data = self.request(b"L", b"", "l").decode("utf-8", "replace")
		out = []
		for line in data.split("\n"):
			if not line.strip():
				continue
			parts = (line.split("\t") + ["", "", "", ""])[:4]
			out.append((parts[0], parts[1], parts[2], parts[3]))
		return out

	def setVoice(self, voiceId: str) -> tuple[int, str]:
		data = self.request(b"V", voiceId.encode("utf-8"), "v")
		hr = struct.unpack("<i", data[:4])[0] if len(data) >= 4 else -1
		return hr, data[4:].decode("utf-8", "replace")

	def speak(
		self,
		seq: int,
		text: str,
		emit: Callable[[bytes], None],
		isCancelled: Callable[[], bool],
		rate: int | None = None,
		pitch: int | None = None,
		idleTimeout: float = IDLE_TIMEOUT,
	) -> bool:
		"""Sintetiza ``text`` y llama a ``emit`` con cada trozo de PCM.

		Devuelve ``False`` si se canceló. Lanza :class:`HostError` si el
		auxiliar falla, muere o deja de responder.
		"""
		flags = (FLAG_RATE if rate is not None else 0) | (FLAG_PITCH if pitch is not None else 0)
		header = struct.pack("<IIII", seq, flags, (rate or 0) & 0xFFFFFFFF, (pitch or 0) & 0xFFFFFFFF)
		self.send(b"S", header + text.encode("utf-8", "replace"))
		last = time.monotonic()
		while True:
			if isCancelled():
				return False
			try:
				kind, payload = self._next(0.05)
			except TimeoutError:
				if time.monotonic() - last > idleTimeout:
					self.kill()
					raise HostError("El auxiliar de 32 bits no responde") from None
				continue
			except HostError:
				if isCancelled():
					return False
				raise
			last = time.monotonic()
			if len(payload) < 4:
				continue
			frameSeq = struct.unpack_from("<I", payload)[0]
			if frameSeq != seq:
				# Restos de un enunciado anterior cancelado.
				continue
			if kind == ord("a"):
				if not isCancelled():
					emit(payload[4:])
			elif kind == ord("d"):
				hr = struct.unpack_from("<i", payload, 4)[0] if len(payload) >= 8 else 0
				cancelled = len(payload) >= 9 and payload[8] != 0
				if hr < 0 and not cancelled:
					raise HostError(f"Error del motor de voz: 0x{hr & 0xFFFFFFFF:08X}")
				return not cancelled

	def cancel(self, upToSeq: int) -> None:
		"""Calla todo enunciado con número ``<= upToSeq`` (no espera respuesta)."""
		if not self.isAlive():
			return
		try:
			self.send(b"C", struct.pack("<I", upToSeq & 0xFFFFFFFF))
		except HostError:
			pass

	def stop(self, timeout: float = 1.5) -> None:
		p = self._proc
		if p is None:
			return
		if p.poll() is None and not self._dead:
			try:
				self.send(b"Q")
			except HostError:
				pass
			try:
				p.wait(timeout)
			except Exception:
				pass
		self.kill()

	def kill(self) -> None:
		p = self._proc
		self._dead = True
		if p is None:
			return
		try:
			if p.poll() is None:
				p.kill()
				p.wait(2)
		except Exception:
			pass
		for stream in (p.stdin, p.stdout):
			try:
				if stream:
					stream.close()
			except Exception:
				pass


# ------------------------------------------------------------------ voces sin auxiliar (check)
_probeCache: dict[str, tuple[float, list]] = {}
#: Segundos que se recuerda la lista de voces obtenida en ``check()``.
PROBE_CACHE_SECONDS = 60.0


def probeVoices(mode: str, exe: str | None = None) -> list[tuple[str, str, str, str]]:
	"""Voces que ve un auxiliar nuevo (se recuerda un rato: ``check()`` es frecuente)."""
	now = time.monotonic()
	cached = _probeCache.get(mode)
	if cached and now - cached[0] < PROBE_CACHE_SECONDS:
		return cached[1]
	host = HostProcess(mode, exe)
	try:
		host.start()
		voices = host.listVoices()
	except HostError:
		log.debug("No se pudieron enumerar las voces %s de 32 bits", mode, exc_info=True)
		voices = []
	finally:
		host.stop()
	_probeCache[mode] = (now, voices)
	return voices


def _uiLocale() -> str:
	try:
		import ctypes

		buf = ctypes.create_unicode_buffer(85)
		if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85):
			return buf.value.replace("-", "_")
	except Exception:
		pass
	return ""


def defaultVoice(voices: OrderedDict[str, VoiceInfo]) -> str:
	"""Voz inicial: la del idioma de Windows; si no, una en español; si no, la primera."""
	loc = _uiLocale().lower()
	for wanted in (loc, loc.split("_")[0], "es"):
		if not wanted:
			continue
		for key, v in voices.items():
			lang = (v.language or "").lower()
			if lang == wanted or (len(wanted) == 2 and lang.split("_")[0] == wanted):
				return key
	return next(iter(voices), "")


# ------------------------------------------------------------------ base de los controladores
class Host32SynthDriver(AudioSynthDriver):
	"""Sintetizador cuyo motor vive en el auxiliar de 32 bits."""

	#: Modo del auxiliar: ``"sapi5"`` o ``"sapi4"``.
	hostMode = ""
	sampleRate = 22050

	def __init__(self) -> None:
		self._hostLock = threading.RLock()
		self._host: HostProcess | None = None
		self._seqCounter = itertools.count(1)
		self._lastSeq = 0
		self._voiceDirty = True
		host = self._getHost()
		try:
			self._voices = self._voicesFromList(host.listVoices())
		except BaseException:
			self._killHost()
			raise
		if not self._voices:
			host.stop()
			self._host = None
			raise RuntimeError(f"No hay voces {self.hostMode} de 32 bits")
		super().__init__()
		self._settings["voice"] = defaultVoice(self._voices)
		self._voiceDirty = True
		self._ensureWorker()

	# --------------------------------------------------- para subclases
	def _voicesFromList(self, entries: list[tuple[str, str, str, str]]) -> OrderedDict[str, VoiceInfo]:
		raise NotImplementedError

	def _buildRequest(self, items: list) -> tuple[str, int | None, int | None]:
		"""``(texto, velocidad, tono)`` para el auxiliar (``None`` = sin cambio)."""
		raise NotImplementedError

	def _onVoiceApplied(self, hr: int, info: str) -> None:
		"""Respuesta del auxiliar al elegir la voz (SAPI 4: márgenes de la voz)."""

	def _postProcess(self, data: bytes) -> bytes:
		"""Audio completo de un trozo antes de reproducirlo (solo si :meth:`_wantsWholeSegment`)."""
		return data

	def _wantsWholeSegment(self) -> bool:
		"""``True``: se espera al audio entero del trozo (p. ej. para acelerarlo); si no, suena según llega."""
		return False

	# --------------------------------------------------- voces
	def _getAvailable_voice(self) -> OrderedDict[str, VoiceInfo]:
		return self._voices

	def _set_voice(self, value: str) -> None:
		self._voiceDirty = True

	# --------------------------------------------------- proceso
	def _getHost(self) -> HostProcess:
		with self._hostLock:
			host = self._host
			if host is not None and host.isAlive():
				return host
			if host is not None:
				log.warning("El auxiliar %s de 32 bits ha terminado; se inicia otro", self.hostMode)
				host.kill()
			self._host = None
			host = HostProcess(self.hostMode)
			host.start()
			self._host = host
			self._voiceDirty = True
			return host

	def _killHost(self) -> None:
		with self._hostLock:
			host, self._host = self._host, None
		if host is not None:
			host.kill()

	def _applyVoice(self, host: HostProcess) -> None:
		self._voiceDirty = False
		wanted = self._settings.get("voice") or ""
		if not wanted:
			return
		hr, info = host.setVoice(wanted)
		if hr < 0:
			log.warning("No se pudo seleccionar la voz %s (0x%08X)", wanted, hr & 0xFFFFFFFF)
		self._onVoiceApplied(hr, info)

	def releaseResources(self) -> None:
		"""En espera: se cierra el auxiliar (se vuelve a abrir al hablar o al activarse)."""
		self._killHost()

	def restoreResources(self) -> None:
		host = self._getHost()
		if self._voiceDirty:
			self._applyVoice(host)

	# --------------------------------------------------- síntesis
	def _synthesizeSegment(self, items, emit, isCancelled) -> None:
		whole = self._wantsWholeSegment()
		chunks: list[bytes] = []
		sent = [False]

		def onAudio(data: bytes) -> None:
			if whole:
				chunks.append(data)
			else:
				sent[0] = True
				emit(data)

		for attempt in (0, 1):
			if isCancelled():
				return
			try:
				host = self._getHost()
				if self._voiceDirty:
					self._applyVoice(host)
				# Después de elegir la voz: en SAPI 4 los valores dependen de ella.
				text, rate, pitch = self._buildRequest(items)
				if not text.strip():
					return
				seq = next(self._seqCounter)
				self._lastSeq = seq
				if isCancelled():
					return
				done = host.speak(seq, text, onAudio, isCancelled, rate, pitch)
			except HostError as e:
				if isCancelled():
					return
				log.warning("Fallo del auxiliar %s de 32 bits: %s", self.hostMode, e)
				self._killHost()
				# Un reintento con un auxiliar nuevo, si aún no ha sonado nada.
				if attempt or sent[0]:
					raise
				chunks.clear()
				continue
			if done and chunks and not isCancelled():
				emit(self._postProcess(b"".join(chunks)))
			return

	def _cancelSynthesis(self) -> None:
		host = self._host
		if host is not None:
			host.cancel(self._lastSeq)

	def terminate(self) -> None:
		try:
			super().terminate()
		finally:
			with self._hostLock:
				host, self._host = self._host, None
			if host is not None:
				host.stop()
