"""Envoltorio ctypes propio de la API C del Speech SDK de Microsoft.

Solo usa la parte de síntesis local («embedded»): configuración con las
carpetas de las voces y la clave o licencia del modelo, salida a un flujo de
audio propio (PCM de 24 kHz, 16 bits, mono), lista de voces, síntesis de SSML,
marcas (bookmarks) con su posición en el audio y parada inmediata.

Las bibliotecas nativas (``Microsoft.CognitiveServices.Speech.*.dll``) están en
la carpeta ``sdk`` de este sintetizador; son de Microsoft (ver
``sdk/LICENCIA_SPEECH_SDK.txt``).
"""

from __future__ import annotations

import ctypes
import os
import threading
from ctypes import POINTER, byref, c_char_p, c_int, c_size_t, c_uint8, c_uint32, c_uint64, c_void_p
from typing import Callable

# En la raíz del complemento: los nombres de las DLL del Speech SDK son muy
# largos y, más adentro, una copia portable en una carpeta profunda superaba
# el límite de 260 caracteres de Windows (error 206 al cargar las extensiones).
SDK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "sdk")
CORE_DLL = os.path.join(SDK_DIR, "Microsoft.CognitiveServices.Speech.core.dll")

# Identificadores de propiedades y valores de enumeraciones de la API C.
SpeechServiceConnection_SynthModelKey = 3114
CancellationDetails_ReasonDetailedText = 6002
SpeechSynthesisOutputFormat_Raw24Khz16BitMonoPcm = 16
ResultReason_Canceled = 1
ResultReason_SynthesizingAudioComplete = 9
CancellationReason_Error = 1

#: Frecuencia de muestreo del formato de salida elegido.
SAMPLE_RATE = 24000
#: Bytes por segundo del formato de salida (16 bits, mono).
BYTES_PER_SECOND = SAMPLE_RATE * 2

AZACHR = c_size_t
HANDLE = c_void_p

# int (*)(void* contexto, uint8_t* datos, uint32_t tamaño)
WRITE_CALLBACK = ctypes.CFUNCTYPE(c_int, c_void_p, POINTER(c_uint8), c_uint32)
# void (*)(void* contexto)
CLOSE_CALLBACK = ctypes.CFUNCTYPE(None, c_void_p)
# void (*)(SPXSYNTHHANDLE, SPXEVENTHANDLE, void* contexto)
SYNTHESIS_CALLBACK = ctypes.CFUNCTYPE(None, HANDLE, HANDLE, c_void_p)


class SpeechSDKError(RuntimeError):
	"""Error devuelto por una función de la API C del Speech SDK."""

	def __init__(self, function: str, code: int, message: str = "") -> None:
		self.function = function
		self.code = code
		self.message = message
		text = f"{function}: error 0x{code:X}"
		if message:
			text += f" ({message})"
		super().__init__(text)


# Firma de cada función usada: (tipo devuelto, argumentos).
_PROTOTYPES: dict[str, tuple] = {
	"embedded_speech_config_create": (AZACHR, [POINTER(HANDLE)]),
	"embedded_speech_config_add_path": (AZACHR, [HANDLE, c_char_p]),
	"speech_config_get_property_bag": (AZACHR, [HANDLE, POINTER(HANDLE)]),
	"speech_config_set_audio_output_format": (AZACHR, [HANDLE, c_int]),
	"speech_config_release": (AZACHR, [HANDLE]),
	"property_bag_set_string": (AZACHR, [HANDLE, c_int, c_char_p, c_char_p]),
	"property_bag_get_string": (c_void_p, [HANDLE, c_int, c_char_p, c_char_p]),
	"property_bag_free_string": (AZACHR, [c_void_p]),
	"property_bag_release": (AZACHR, [HANDLE]),
	"audio_stream_create_push_audio_output_stream": (AZACHR, [POINTER(HANDLE)]),
	"push_audio_output_stream_set_callbacks": (AZACHR, [HANDLE, c_void_p, WRITE_CALLBACK, CLOSE_CALLBACK]),
	"audio_stream_release": (AZACHR, [HANDLE]),
	"audio_config_create_audio_output_from_stream": (AZACHR, [POINTER(HANDLE), HANDLE]),
	"audio_config_release": (AZACHR, [HANDLE]),
	"synthesizer_create_speech_synthesizer_from_config": (AZACHR, [POINTER(HANDLE), HANDLE, HANDLE]),
	"synthesizer_handle_release": (AZACHR, [HANDLE]),
	"synthesizer_get_voices_list": (AZACHR, [HANDLE, c_char_p, POINTER(HANDLE)]),
	"synthesis_voices_result_get_voice_num": (AZACHR, [HANDLE, POINTER(c_uint32)]),
	"synthesis_voices_result_get_voice_info": (AZACHR, [HANDLE, c_uint32, POINTER(HANDLE)]),
	"voice_info_get_name": (c_void_p, [HANDLE]),
	"voice_info_get_locale": (c_void_p, [HANDLE]),
	"voice_info_get_short_name": (c_void_p, [HANDLE]),
	"voice_info_get_local_name": (c_void_p, [HANDLE]),
	"voice_info_handle_release": (AZACHR, [HANDLE]),
	"synthesizer_result_handle_release": (AZACHR, [HANDLE]),
	"synthesizer_bookmark_reached_set_callback": (AZACHR, [HANDLE, SYNTHESIS_CALLBACK, c_void_p]),
	"synthesizer_bookmark_event_get_values": (AZACHR, [HANDLE, POINTER(c_uint64)]),
	"synthesizer_event_get_text": (c_void_p, [HANDLE]),
	"synthesizer_event_handle_release": (AZACHR, [HANDLE]),
	"synthesizer_speak_ssml": (AZACHR, [HANDLE, c_char_p, c_uint32, POINTER(HANDLE)]),
	"synth_result_get_reason": (AZACHR, [HANDLE, POINTER(c_int)]),
	"synth_result_get_reason_canceled": (AZACHR, [HANDLE, POINTER(c_int)]),
	"synth_result_get_canceled_error_code": (AZACHR, [HANDLE, POINTER(c_int)]),
	"synth_result_get_property_bag": (AZACHR, [HANDLE, POINTER(HANDLE)]),
	"synthesizer_stop_speaking_async": (AZACHR, [HANDLE, POINTER(HANDLE)]),
	"synthesizer_async_handle_release": (AZACHR, [HANDLE]),
	"error_get_message": (c_void_p, [HANDLE]),
	"error_get_error_code": (AZACHR, [HANDLE]),
	"error_release": (AZACHR, [HANDLE]),
}

_lib = None
_libLock = threading.Lock()
_dllDirCookie = None


def isAvailable() -> bool:
	"""``True`` si están las bibliotecas del Speech SDK."""
	return os.path.isfile(CORE_DLL)


def lib():
	"""Carga (una sola vez) la biblioteca principal del Speech SDK."""
	global _lib, _dllDirCookie
	with _libLock:
		if _lib is not None:
			return _lib
		if not isAvailable():
			raise FileNotFoundError(CORE_DLL)
		# Las extensiones (embedded.tts, onnxruntime, codec...) y
		# msvcp140_codecvt_ids.dll se cargan desde la misma carpeta.
		if _dllDirCookie is None:
			try:
				_dllDirCookie = os.add_dll_directory(SDK_DIR)
			except OSError:
				_dllDirCookie = False
		# LOAD_WITH_ALTERED_SEARCH_PATH (0x8): las dependencias se buscan
		# primero junto a la biblioteca.
		dll = ctypes.CDLL(CORE_DLL, winmode=0x8)
		for name, (restype, argtypes) in _PROTOTYPES.items():
			try:
				fn = getattr(dll, name)
			except AttributeError:
				continue
			fn.restype = restype
			fn.argtypes = argtypes
		_lib = dll
		return dll


def _errorDetails(hr: int) -> tuple[int, str]:
	"""Código y mensaje de un error de la API (puede ser un código o un objeto de error)."""
	if hr <= 0xFFFF:
		return hr, ""
	dll = lib()
	try:
		code = int(dll.error_get_error_code(c_void_p(hr)))
		msg = dll.error_get_message(c_void_p(hr))
		text = ctypes.string_at(msg).decode("utf-8", "replace") if msg else ""
		dll.error_release(c_void_p(hr))
		return code, text.strip().splitlines()[0] if text.strip() else ""
	except Exception:
		return hr, ""


def _call(name: str, *args) -> None:
	hr = getattr(lib(), name)(*args)
	if hr:
		code, message = _errorDetails(int(hr))
		raise SpeechSDKError(name, code, message)


def _sdkString(ptr: int | None, free: bool = True) -> str:
	"""Copia una cadena UTF-8 devuelta por el SDK y libera su memoria."""
	if not ptr:
		return ""
	try:
		return ctypes.string_at(ptr).decode("utf-8", "replace")
	finally:
		if free:
			lib().property_bag_free_string(c_void_p(ptr))


def _release(name: str, handle) -> None:
	if handle:
		try:
			getattr(lib(), name)(handle)
		except Exception:
			pass


class SDKVoice:
	"""Voz instalada que ofrece el motor."""

	def __init__(self, name: str, locale: str, shortName: str = "", localName: str = "") -> None:
		self.name = name
		self.locale = locale
		self.shortName = shortName
		self.localName = localName

	def __repr__(self) -> str:
		return f"SDKVoice({self.name!r}, {self.locale!r})"


class SpeechSynthesizer:
	"""Sintetizador local del Speech SDK para un paquete de voces.

	``onAudio(bytes)`` recibe el PCM según se genera y ``onBookmark(texto,
	posición)`` cada marca ``<mark>`` del SSML con su posición en bytes dentro
	del audio de esa síntesis. Ambas se llaman desde hilos del SDK.
	"""

	def __init__(self, key: str, paths: list[str]) -> None:
		lib()
		self._config = HANDLE()
		self._props = HANDLE()
		self._stream = HANDLE()
		self._audioConfig = HANDLE()
		self._handle = HANDLE()
		self.onAudio: Callable[[bytes], None] | None = None
		self.onBookmark: Callable[[str, int], None] | None = None
		# Referencias de las retrollamadas: no pueden liberarse mientras el SDK las use.
		self._writeCb = WRITE_CALLBACK(self._onWrite)
		self._closeCb = CLOSE_CALLBACK(self._onClose)
		self._bookmarkCb = SYNTHESIS_CALLBACK(self._onBookmark)
		self._lock = threading.Lock()
		try:
			_call("embedded_speech_config_create", byref(self._config))
			_call("speech_config_get_property_bag", self._config, byref(self._props))
			for p in paths:
				# El SDK espera rutas en UTF-8.
				_call("embedded_speech_config_add_path", self._config, p.encode("utf-8"))
			_call("property_bag_set_string", self._props, SpeechServiceConnection_SynthModelKey, None, key.encode("utf-8"))
			_call("speech_config_set_audio_output_format", self._config, SpeechSynthesisOutputFormat_Raw24Khz16BitMonoPcm)
			_call("audio_stream_create_push_audio_output_stream", byref(self._stream))
			_call("audio_config_create_audio_output_from_stream", byref(self._audioConfig), self._stream)
			_call("push_audio_output_stream_set_callbacks", self._stream, None, self._writeCb, self._closeCb)
			_call("synthesizer_create_speech_synthesizer_from_config", byref(self._handle), self._config, self._audioConfig)
			_call("synthesizer_bookmark_reached_set_callback", self._handle, self._bookmarkCb, None)
			self.voices = self._readVoices()
		except Exception:
			self.close()
			raise

	# ------------------------------------------------------------ voces
	def _readVoices(self) -> list[SDKVoice]:
		dll = lib()
		result = HANDLE()
		_call("synthesizer_get_voices_list", self._handle, b"", byref(result))
		voices: list[SDKVoice] = []
		try:
			num = c_uint32()
			_call("synthesis_voices_result_get_voice_num", result, byref(num))
			for i in range(num.value):
				info = HANDLE()
				_call("synthesis_voices_result_get_voice_info", result, i, byref(info))
				try:
					name = _sdkString(dll.voice_info_get_name(info))
					locale = _sdkString(dll.voice_info_get_locale(info))
					shortName = _sdkString(dll.voice_info_get_short_name(info)) if hasattr(dll, "voice_info_get_short_name") else ""
					localName = _sdkString(dll.voice_info_get_local_name(info)) if hasattr(dll, "voice_info_get_local_name") else ""
				finally:
					_release("voice_info_handle_release", info)
				if name:
					voices.append(SDKVoice(name, locale, shortName, localName))
		finally:
			_release("synthesizer_result_handle_release", result)
		return voices

	# ------------------------------------------------------------ retrollamadas del SDK
	def _onWrite(self, context, buffer, size) -> int:
		try:
			cb = self.onAudio
			if cb is not None and size:
				cb(ctypes.string_at(buffer, size))
		except Exception:
			pass
		return size

	def _onClose(self, context) -> None:
		pass

	def _onBookmark(self, hsynth, hevent, context) -> None:
		try:
			dll = lib()
			offset = c_uint64(0)
			try:
				_call("synthesizer_bookmark_event_get_values", hevent, byref(offset))
			except SpeechSDKError:
				offset.value = 0
			text = _sdkString(dll.synthesizer_event_get_text(hevent))
			# La posición llega en unidades de 100 ns: se pasa a bytes de audio.
			pos = (offset.value * BYTES_PER_SECOND) // 10_000_000
			pos -= pos % 2
			cb = self.onBookmark
			if cb is not None:
				cb(text, pos)
		except Exception:
			pass
		finally:
			_release("synthesizer_event_handle_release", hevent)

	# ------------------------------------------------------------ síntesis
	def speakSsml(self, ssml: str) -> tuple[int, str]:
		"""Sintetiza ``ssml`` (bloquea hasta terminar o detenerse).

		Devuelve ``(motivo, detalle)``: ``ResultReason_SynthesizingAudioComplete``
		si terminó, ``ResultReason_Canceled`` si se detuvo o hubo un error.
		"""
		dll = lib()
		data = ssml.encode("utf-8")
		result = HANDLE()
		with self._lock:
			_call("synthesizer_speak_ssml", self._handle, data, len(data), byref(result))
		try:
			reason = c_int(0)
			_call("synth_result_get_reason", result, byref(reason))
			detail = ""
			if reason.value == ResultReason_Canceled:
				detail = self._cancelDetail(dll, result)
			return reason.value, detail
		finally:
			_release("synthesizer_result_handle_release", result)

	@staticmethod
	def _cancelDetail(dll, result) -> str:
		try:
			why = c_int(0)
			_call("synth_result_get_reason_canceled", result, byref(why))
			if why.value != CancellationReason_Error:
				return ""
			code = c_int(0)
			_call("synth_result_get_canceled_error_code", result, byref(code))
			props = HANDLE()
			_call("synth_result_get_property_bag", result, byref(props))
			try:
				text = _sdkString(dll.property_bag_get_string(props, CancellationDetails_ReasonDetailedText, None, b""))
			finally:
				_release("property_bag_release", props)
			return f"error {code.value}: {text}" if text else f"error {code.value}"
		except Exception:
			return "error"

	def stop(self) -> None:
		"""Detiene la síntesis en curso (se puede llamar desde cualquier hilo)."""
		if not self._handle:
			return
		h = HANDLE()
		try:
			_call("synthesizer_stop_speaking_async", self._handle, byref(h))
		except SpeechSDKError:
			return
		_release("synthesizer_async_handle_release", h)

	def close(self) -> None:
		"""Libera todos los recursos nativos."""
		self.onAudio = None
		self.onBookmark = None
		if self._handle:
			try:
				lib().synthesizer_bookmark_reached_set_callback(self._handle, SYNTHESIS_CALLBACK(), None)
			except Exception:
				pass
			_release("synthesizer_handle_release", self._handle)
			self._handle = HANDLE()
		if self._stream:
			try:
				lib().push_audio_output_stream_set_callbacks(self._stream, None, WRITE_CALLBACK(), CLOSE_CALLBACK())
			except Exception:
				pass
		_release("audio_config_release", self._audioConfig)
		self._audioConfig = HANDLE()
		_release("audio_stream_release", self._stream)
		self._stream = HANDLE()
		_release("property_bag_release", self._props)
		self._props = HANDLE()
		_release("speech_config_release", self._config)
		self._config = HANDLE()
