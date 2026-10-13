# -*- coding: utf-8 -*-
# Copyright (C) 2025-2026 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General GNU.

"""Envoltorio ctypes propio de la biblioteca de audio BASS (un4seen.com).

Sustituye a ``sound_lib``/``libloader`` del complemento original. Solo
declara las funciones que usa zRadio BASS:

- ``bass.dll``: reproducción de emisoras por HTTP/HTTPS, volumen, pausa,
  dispositivos de salida, metadatos ICY/OGG/HLS y decodificación.
- ``bassenc.dll``: grabación a WAV (``BASS_Encode_Start`` con ``BASS_ENCODE_PCM``).
- ``bass_fx.dll``: ecualizador de tres bandas (``BASS_FX_BFX_PEAKEQ``).
- Complementos de formato: ``bass_aac``, ``bassflac``, ``bassopus``,
  ``basshls`` (emisoras HLS, .m3u8) y ``basswma``.

BASS es gratuita para uso no comercial; ver ``bass/LICENCIA-BASS.txt``.

Si otro componente del proceso ya cargó un ``bass.dll``, se reutiliza ese
módulo: los complementos de BASS se enlazan por nombre con el ``bass.dll``
que ya esté cargado, así que usar otra copia los dejaría sin efecto.
"""

from __future__ import annotations

import ctypes
import os
import threading
from ctypes import POINTER, Structure, c_char_p, c_float, c_int, c_uint, c_ulonglong, c_void_p, wintypes

from tiresias.log import getLogger

log = getLogger("zRadioBASS.bass")

#: Carpeta con las DLL x64 de BASS incluidas en el complemento.
DLL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bass")

DWORD = c_uint
QWORD = c_ulonglong
HSTREAM = DWORD
HPLUGIN = DWORD
HFX = DWORD
HENCODE = DWORD

# --------------------------------------------------------------------- constantes
BASS_OK = 0
BASS_ERROR_ALREADY = 14
BASS_ERROR_ENDED = 45
BASS_ERROR_UNKNOWN = -1

#: Descripción en español de los códigos de error de BASS.
ERRORS = {
	0: "sin error",
	1: "memoria insuficiente",
	2: "no se pudo abrir la dirección o el archivo",
	3: "no se encontró un controlador de sonido disponible",
	4: "se perdió el búfer de sonido",
	5: "identificador no válido",
	6: "formato de muestra no admitido",
	7: "posición no válida",
	8: "BASS no está inicializado",
	9: "no se pudo iniciar la reproducción",
	10: "error de SSL/TLS al conectar",
	11: "hay que reinicializar el dispositivo",
	14: "ya estaba inicializado",
	17: "el archivo no contiene audio",
	18: "no quedan canales libres",
	19: "tipo de dato no válido",
	20: "parámetro no válido",
	21: "sin 3D",
	22: "sin EAX",
	23: "dispositivo de sonido no válido",
	24: "no se está reproduciendo",
	25: "frecuencia no válida",
	27: "no es un archivo",
	29: "no hay hardware disponible",
	31: "el archivo está vacío",
	32: "no hay conexión a Internet o no se pudo conectar con la emisora",
	33: "no se pudo crear el archivo",
	34: "efecto no disponible",
	37: "no disponible",
	38: "el canal es de decodificación",
	39: "falta una versión suficiente de DirectX",
	40: "se agotó el tiempo de conexión",
	41: "formato de la emisora no admitido",
	42: "configuración de altavoces no disponible",
	43: "versión de BASS no válida",
	44: "códec no disponible o no admitido",
	45: "la emisora ha terminado la transmisión",
	46: "el dispositivo está ocupado",
	47: "la emisora no se puede transmitir",
	48: "protocolo no admitido",
	49: "acceso denegado",
	-1: "error desconocido",
}

# Configuración
BASS_CONFIG_BUFFER = 0
BASS_CONFIG_UPDATEPERIOD = 1
BASS_CONFIG_NET_TIMEOUT = 11
BASS_CONFIG_NET_BUFFER = 12
BASS_CONFIG_NET_PREBUF = 15
BASS_CONFIG_NET_AGENT = 16
BASS_CONFIG_NET_PLAYLIST = 21
BASS_CONFIG_DEV_DEFAULT = 36
BASS_CONFIG_NET_READTIMEOUT = 37
BASS_CONFIG_UNICODE = 42
BASS_CONFIG_ENCODE_PRIORITY = 0x10300

# Opciones de creación
BASS_SAMPLE_FLOAT = 0x100
BASS_STREAM_BLOCK = 0x100000
BASS_STREAM_DECODE = 0x200000
BASS_STREAM_STATUS = 0x800000
BASS_UNICODE = 0x80000000

# Dispositivos
BASS_DEVICE_ENABLED = 1
BASS_DEVICE_DEFAULT = 2
BASS_DEVICE_INIT = 4
#: Dispositivo «sin sonido» de BASS (decodifica sin enviar nada a los altavoces).
NO_SOUND_DEVICE = 0
DEFAULT_DEVICE = -1

# Estado de un canal
BASS_ACTIVE_STOPPED = 0
BASS_ACTIVE_PLAYING = 1
BASS_ACTIVE_STALLED = 2
BASS_ACTIVE_PAUSED = 3
BASS_ACTIVE_PAUSED_DEVICE = 4

# Atributos
BASS_ATTRIB_VOL = 2
BASS_ATTRIB_PAN = 3

# Etiquetas (metadatos)
BASS_TAG_OGG = 2
BASS_TAG_HTTP = 3
BASS_TAG_ICY = 4
BASS_TAG_META = 5
BASS_TAG_WMA = 8
BASS_TAG_WMA_META = 11
BASS_TAG_HLS_EXTINF = 0x14000

# Posiciones del archivo de red
BASS_FILEPOS_DOWNLOAD = 1
BASS_FILEPOS_CONNECTED = 4
BASS_FILEPOS_BUFFER = 5
BASS_FILEPOS_BUFFERING = 9

BASS_POS_BYTE = 0
BASS_DATA_AVAILABLE = 0

# BASSenc
BASS_ENCODE_PCM = 64
BASS_ENCODE_AUTOFREE = 0x40000
BASS_ACTIVE_ENC_STOPPED = 0

# BASS_FX
BASS_FX_BFX_PEAKEQ = 0x10004
BASS_BFX_CHANALL = -1

#: Tipos de canal → nombre del formato.
CHANNEL_TYPES = {
	0x10002: "OGG Vorbis",
	0x10003: "MP1",
	0x10004: "MP2",
	0x10005: "MP3",
	0x10006: "AIFF",
	0x10007: "Core Audio",
	0x10008: "Media Foundation",
	0x10300: "WMA",
	0x10301: "WMA (MP3)",
	0x10900: "FLAC",
	0x10901: "FLAC (OGG)",
	0x10B00: "AAC",
	0x10B01: "MP4 (AAC)",
	0x11200: "Opus",
	0x40000: "WAV",
	0x50001: "WAV PCM",
	0x50003: "WAV coma flotante",
}

#: Complementos de formato que se cargan (en este orden).
FORMAT_PLUGINS = ("bass_aac.dll", "bassflac.dll", "bassopus.dll", "basshls.dll", "basswma.dll")


class BASS_DEVICEINFO(Structure):
	_fields_ = [("name", c_char_p), ("driver", c_char_p), ("flags", DWORD)]


class BASS_CHANNELINFO(Structure):
	_fields_ = [
		("freq", DWORD),
		("chans", DWORD),
		("flags", DWORD),
		("ctype", DWORD),
		("origres", DWORD),
		("plugin", HPLUGIN),
		("sample", DWORD),
		("filename", c_char_p),
	]


class BASS_BFX_PEAKEQ(Structure):
	_fields_ = [
		("lBand", c_int),
		("fBandwidth", c_float),
		("fQ", c_float),
		("fCenter", c_float),
		("fGain", c_float),
		("lChannel", c_int),
	]


class BassError(Exception):
	"""Error de BASS con su código y su descripción en español."""

	def __init__(self, code: int, action: str = "") -> None:
		self.code = code
		desc = ERRORS.get(code, f"código {code}")
		super().__init__(f"{action}: {desc}" if action else desc)


def decodeText(raw: bytes | None) -> str:
	"""Texto de BASS (UTF-8 con BASS_CONFIG_UNICODE; las emisoras antiguas usan Latin-1)."""
	if not raw:
		return ""
	try:
		return raw.decode("utf-8")
	except UnicodeDecodeError:
		return raw.decode("cp1252", "replace")


def _readMultiString(addr: int) -> list[str]:
	"""Lee una serie de cadenas terminadas en nulo que acaba con una cadena vacía."""
	out: list[str] = []
	if not addr:
		return out
	for _i in range(256):
		raw = ctypes.string_at(addr)
		if not raw:
			break
		out.append(decodeText(raw))
		addr += len(raw) + 1
	return out


class Bass:
	"""Funciones de BASS, BASSenc y BASS_FX cargadas con ctypes."""

	def __init__(self, dllDir: str = DLL_DIR) -> None:
		self.dllDir = dllDir
		self.shared = False
		path = os.path.join(dllDir, "bass.dll")
		if not os.path.isfile(path):
			raise OSError(f"No se encuentra {path}")
		try:
			self._dllCookie = os.add_dll_directory(dllDir)
		except (OSError, AttributeError):
			self._dllCookie = None
		kernel = ctypes.WinDLL("kernel32", use_last_error=True)
		kernel.GetModuleHandleW.restype = c_void_p
		kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
		kernel.GetModuleFileNameW.argtypes = [c_void_p, ctypes.c_wchar_p, DWORD]
		existing = kernel.GetModuleHandleW("bass.dll")
		if existing:
			buf = ctypes.create_unicode_buffer(1024)
			kernel.GetModuleFileNameW(c_void_p(existing), buf, 1024)
			loadedPath = buf.value
			if os.path.normcase(os.path.abspath(loadedPath)) != os.path.normcase(os.path.abspath(path)):
				# Otro componente ya cargó BASS: se comparte para que los complementos funcionen.
				self.shared = True
				log.info("Se reutiliza el bass.dll ya cargado en el proceso: %s", loadedPath)
				path = loadedPath
		self.bass = ctypes.WinDLL(path)
		self.bassenc = self._optional("bassenc.dll")
		self.bassfx = self._optional("bass_fx.dll")
		self._declare()
		self.version = self.bass.BASS_GetVersion()
		self.plugins: dict[str, int] = {}
		self._lock = threading.RLock()
		self._agent: c_char_p | None = None
		self._configured = False

	def _optional(self, name: str):
		p = os.path.join(self.dllDir, name)
		if not os.path.isfile(p):
			log.warning("No se encuentra %s: la función que lo usa no estará disponible", name)
			return None
		try:
			return ctypes.WinDLL(p)
		except OSError:
			log.exception("No se pudo cargar %s", name)
			return None

	# ------------------------------------------------------------- declaraciones
	def _declare(self) -> None:
		b = self.bass

		def fn(lib, name: str, res, *args):
			f = getattr(lib, name)
			f.restype = res
			f.argtypes = list(args)
			return f

		fn(b, "BASS_GetVersion", DWORD)
		fn(b, "BASS_ErrorGetCode", c_int)
		fn(b, "BASS_SetConfig", wintypes.BOOL, DWORD, DWORD)
		fn(b, "BASS_GetConfig", DWORD, DWORD)
		fn(b, "BASS_SetConfigPtr", wintypes.BOOL, DWORD, c_void_p)
		fn(b, "BASS_Init", wintypes.BOOL, c_int, DWORD, DWORD, wintypes.HWND, c_void_p)
		fn(b, "BASS_Free", wintypes.BOOL)
		fn(b, "BASS_GetDeviceInfo", wintypes.BOOL, DWORD, POINTER(BASS_DEVICEINFO))
		fn(b, "BASS_SetDevice", wintypes.BOOL, DWORD)
		fn(b, "BASS_GetDevice", DWORD)
		fn(b, "BASS_PluginLoad", HPLUGIN, c_void_p, DWORD)
		fn(b, "BASS_StreamCreateURL", HSTREAM, c_void_p, DWORD, DWORD, c_void_p, c_void_p)
		fn(b, "BASS_StreamFree", wintypes.BOOL, HSTREAM)
		fn(b, "BASS_StreamGetFilePosition", QWORD, HSTREAM, DWORD)
		fn(b, "BASS_ChannelPlay", wintypes.BOOL, DWORD, wintypes.BOOL)
		fn(b, "BASS_ChannelPause", wintypes.BOOL, DWORD)
		fn(b, "BASS_ChannelStop", wintypes.BOOL, DWORD)
		fn(b, "BASS_ChannelIsActive", DWORD, DWORD)
		fn(b, "BASS_ChannelSetAttribute", wintypes.BOOL, DWORD, DWORD, c_float)
		fn(b, "BASS_ChannelGetAttribute", wintypes.BOOL, DWORD, DWORD, POINTER(c_float))
		fn(b, "BASS_ChannelGetTags", c_void_p, DWORD, DWORD)
		fn(b, "BASS_ChannelGetInfo", wintypes.BOOL, DWORD, POINTER(BASS_CHANNELINFO))
		fn(b, "BASS_ChannelGetData", DWORD, DWORD, c_void_p, DWORD)
		fn(b, "BASS_ChannelGetLevel", DWORD, DWORD)
		fn(b, "BASS_ChannelSetDevice", wintypes.BOOL, DWORD, DWORD)
		fn(b, "BASS_ChannelGetDevice", DWORD, DWORD)
		fn(b, "BASS_ChannelSetFX", HFX, DWORD, DWORD, c_int)
		fn(b, "BASS_ChannelRemoveFX", wintypes.BOOL, DWORD, HFX)
		fn(b, "BASS_FXSetParameters", wintypes.BOOL, HFX, c_void_p)
		fn(b, "BASS_ChannelGetPosition", QWORD, DWORD, DWORD)
		fn(b, "BASS_ChannelBytes2Seconds", ctypes.c_double, DWORD, QWORD)
		if self.bassenc is not None:
			e = self.bassenc
			fn(e, "BASS_Encode_GetVersion", DWORD)
			fn(e, "BASS_Encode_Start", HENCODE, DWORD, c_void_p, DWORD, c_void_p, c_void_p)
			fn(e, "BASS_Encode_Stop", wintypes.BOOL, DWORD)
			fn(e, "BASS_Encode_IsActive", DWORD, DWORD)
		if self.bassfx is not None:
			fn(self.bassfx, "BASS_FX_GetVersion", DWORD)

	# ------------------------------------------------------------- utilidades
	@property
	def versionText(self) -> str:
		v = self.version
		return f"{v >> 24 & 0xFF}.{v >> 16 & 0xFF}.{v >> 8 & 0xFF}.{v & 0xFF}"

	def errorCode(self) -> int:
		return int(self.bass.BASS_ErrorGetCode())

	def check(self, ok, action: str = ""):
		"""Lanza :class:`BassError` si ``ok`` es falso (0)."""
		if not ok:
			raise BassError(self.errorCode(), action)
		return ok

	@property
	def canRecord(self) -> bool:
		return self.bassenc is not None

	@property
	def hasEffects(self) -> bool:
		return self.bassfx is not None

	def configure(self, userAgent: str = "zRadioBASS/1.0 (Tiresias)") -> None:
		"""Opciones globales: textos en UTF-8, listas de reproducción y red."""
		with self._lock:
			if self._configured:
				return
			b = self.bass
			b.BASS_SetConfig(BASS_CONFIG_UNICODE, 1)
			# Las direcciones .pls/.m3u de muchas emisoras se resuelven solas.
			b.BASS_SetConfig(BASS_CONFIG_NET_PLAYLIST, 1)
			# La salida «por defecto» sigue al dispositivo predeterminado de Windows.
			b.BASS_SetConfig(BASS_CONFIG_DEV_DEFAULT, 1)
			b.BASS_SetConfig(BASS_CONFIG_NET_TIMEOUT, 15000)
			b.BASS_SetConfig(BASS_CONFIG_NET_READTIMEOUT, 20000)
			b.BASS_SetConfig(BASS_CONFIG_NET_BUFFER, 5000)
			self._agent = c_char_p(userAgent.encode("ascii", "replace"))
			b.BASS_SetConfigPtr(BASS_CONFIG_NET_AGENT, ctypes.cast(self._agent, c_void_p))
			if self.bassenc is not None:
				# El grabador va antes que el ecualizador: se graba la emisora tal cual.
				b.BASS_SetConfig(BASS_CONFIG_ENCODE_PRIORITY, 10000)
			if self.bassfx is not None:
				try:
					self.bassfx.BASS_FX_GetVersion()
				except Exception:
					log.debug("BASS_FX_GetVersion falló", exc_info=True)
			self._configured = True

	def loadPlugins(self) -> dict[str, int]:
		"""Carga los complementos de formato (AAC, FLAC, Opus, HLS, WMA)."""
		with self._lock:
			for name in FORMAT_PLUGINS:
				if self.plugins.get(name):
					continue
				p = os.path.join(self.dllDir, name)
				if not os.path.isfile(p):
					log.warning("Complemento de BASS no encontrado: %s", p)
					continue
				h = self.bass.BASS_PluginLoad(ctypes.c_wchar_p(p), BASS_UNICODE)
				if h:
					self.plugins[name] = int(h)
					log.debug("Complemento de BASS cargado: %s", name)
				else:
					code = self.errorCode()
					if code == BASS_ERROR_ALREADY:
						self.plugins[name] = -1
					else:
						log.warning("No se pudo cargar %s: %s", name, ERRORS.get(code, code))
			return dict(self.plugins)

	# ------------------------------------------------------------- dispositivos
	def devices(self) -> list[tuple[int, str, int]]:
		"""Dispositivos de salida: ``(número, nombre, indicadores)``.

		Sin el 0 («sin sonido») ni el «Default» virtual de BASS (sin
		controlador), que es el que se usa para «Predeterminado de Windows».
		"""
		self.configure()
		out = []
		info = BASS_DEVICEINFO()
		i = 1
		while i < 64 and self.bass.BASS_GetDeviceInfo(i, ctypes.byref(info)):
			if info.flags & BASS_DEVICE_ENABLED and info.driver:
				out.append((i, decodeText(info.name), int(info.flags)))
			i += 1
		return out

	def defaultDevice(self) -> int:
		for num, _name, flags in self.devices():
			if flags & BASS_DEVICE_DEFAULT:
				return num
		return 1

	def deviceByName(self, name: str) -> int:
		"""Número del dispositivo llamado ``name`` (``-1``, el predeterminado, si no está)."""
		if not name:
			return DEFAULT_DEVICE
		for num, devName, _flags in self.devices():
			if devName == name:
				return num
		return DEFAULT_DEVICE

	def initDevice(self, device: int, freq: int = 44100) -> int:
		"""Inicializa un dispositivo (si ya lo estaba no es un error). Devuelve su número."""
		with self._lock:
			self.configure()
			ok = self.bass.BASS_Init(device, freq, 0, None, None)
			if not ok:
				code = self.errorCode()
				if code != BASS_ERROR_ALREADY:
					raise BassError(code, "No se pudo inicializar el dispositivo de sonido")
			if device == DEFAULT_DEVICE:
				# BASS_Init(-1) inicializa el predeterminado: se busca cuál es.
				if ok:
					return int(self.bass.BASS_GetDevice())
				info = BASS_DEVICEINFO()
				i = 1
				while i < 64 and self.bass.BASS_GetDeviceInfo(i, ctypes.byref(info)):
					if info.flags & BASS_DEVICE_DEFAULT and info.flags & BASS_DEVICE_INIT:
						return i
					i += 1
				return self.defaultDevice()
			return device

	def setThreadDevice(self, device: int) -> None:
		self.bass.BASS_SetDevice(device)

	# ------------------------------------------------------------- canales
	def streamFromUrl(self, url: str, decode: bool = False) -> int:
		flags = BASS_UNICODE | (BASS_STREAM_DECODE | BASS_STREAM_BLOCK if decode else 0)
		h = self.bass.BASS_StreamCreateURL(ctypes.c_wchar_p(url), 0, flags, None, None)
		return int(self.check(h, "No se pudo abrir la emisora"))

	def free(self, handle: int) -> None:
		if handle:
			self.bass.BASS_StreamFree(handle)

	def play(self, handle: int, restart: bool = False) -> None:
		self.check(self.bass.BASS_ChannelPlay(handle, bool(restart)), "No se pudo reproducir")

	def pause(self, handle: int) -> None:
		self.check(self.bass.BASS_ChannelPause(handle), "No se pudo pausar")

	def isActive(self, handle: int) -> int:
		return int(self.bass.BASS_ChannelIsActive(handle))

	def setAttribute(self, handle: int, attrib: int, value: float) -> None:
		self.bass.BASS_ChannelSetAttribute(handle, attrib, float(value))

	def getAttribute(self, handle: int, attrib: int) -> float:
		v = c_float(0)
		self.bass.BASS_ChannelGetAttribute(handle, attrib, ctypes.byref(v))
		return float(v.value)

	def setChannelDevice(self, handle: int, device: int) -> None:
		self.check(self.bass.BASS_ChannelSetDevice(handle, device), "No se pudo cambiar el dispositivo")

	def channelInfo(self, handle: int) -> BASS_CHANNELINFO | None:
		info = BASS_CHANNELINFO()
		if self.bass.BASS_ChannelGetInfo(handle, ctypes.byref(info)):
			return info
		return None

	def formatName(self, handle: int) -> str:
		info = self.channelInfo(handle)
		if info is None:
			return ""
		return CHANNEL_TYPES.get(int(info.ctype), f"0x{int(info.ctype):X}")

	def bufferPercent(self, handle: int) -> int:
		"""Porcentaje de llenado del búfer de red (para «Conectando… 40 %»)."""
		v = self.bass.BASS_StreamGetFilePosition(handle, BASS_FILEPOS_BUFFERING)
		if v == 0xFFFFFFFFFFFFFFFF:
			return 100
		return int(min(100, v))

	def getData(self, handle: int, buf, length: int) -> int:
		"""Lee datos de un canal de decodificación (``-1`` si hubo error)."""
		n = self.bass.BASS_ChannelGetData(handle, buf, length)
		return -1 if n == 0xFFFFFFFF else int(n)

	def level(self, handle: int) -> int:
		v = self.bass.BASS_ChannelGetLevel(handle)
		return -1 if v == 0xFFFFFFFF else int(v)

	def positionSeconds(self, handle: int) -> float:
		pos = self.bass.BASS_ChannelGetPosition(handle, BASS_POS_BYTE)
		if pos == 0xFFFFFFFFFFFFFFFF:
			return 0.0
		return float(self.bass.BASS_ChannelBytes2Seconds(handle, pos))

	# ------------------------------------------------------------- metadatos
	def tags(self, handle: int, kind: int) -> list[str]:
		addr = self.bass.BASS_ChannelGetTags(handle, kind)
		if not addr:
			return []
		if kind in (BASS_TAG_META, BASS_TAG_HLS_EXTINF):
			return [decodeText(ctypes.string_at(addr))]
		return _readMultiString(addr)

	def streamTitle(self, handle: int) -> str:
		"""Título de la canción (Shoutcast/Icecast, OGG, WMA o HLS), o cadena vacía."""
		meta = self.tags(handle, BASS_TAG_META)
		if meta:
			title = parseStreamTitle(meta[0])
			if title:
				return title
		ogg = self.tags(handle, BASS_TAG_OGG)
		if ogg:
			fields = {}
			for item in ogg:
				k, _s, v = item.partition("=")
				fields[k.strip().lower()] = v.strip()
			artist, title = fields.get("artist", ""), fields.get("title", "")
			if artist and title:
				return f"{artist} - {title}"
			if title:
				return title
		for item in self.tags(handle, BASS_TAG_WMA_META) + self.tags(handle, BASS_TAG_WMA):
			k, _s, v = item.partition("=")
			if k.strip().lower() in ("title", "caption") and v.strip():
				return v.strip()
		hls = self.tags(handle, BASS_TAG_HLS_EXTINF)
		if hls:
			# #EXTINF:10,title="Canción" artist="Artista" o #EXTINF:10,Texto
			_d, _s, rest = hls[0].partition(",")
			rest = rest.strip()
			if rest:
				return parseHlsTitle(rest)
		return ""

	def icyHeaders(self, handle: int) -> dict[str, str]:
		"""Cabeceras ICY/HTTP de la emisora (``icy-name``, ``icy-genre``, ``icy-br``...)."""
		out: dict[str, str] = {}
		for kind in (BASS_TAG_ICY, BASS_TAG_HTTP):
			for line in self.tags(handle, kind):
				k, sep, v = line.partition(":")
				if sep and k.strip():
					out.setdefault(k.strip().lower(), v.strip())
		return out

	# ------------------------------------------------------------- efectos
	def setPeakEq(self, handle: int, fx: int, bands: list[tuple[float, float]]) -> int:
		"""Aplica un ecualizador de picos con ``bands`` = [(frecuencia, ganancia dB)].

		Si ``fx`` es 0 se crea el efecto. Devuelve el identificador del efecto
		(0 si BASS_FX no está disponible).
		"""
		if self.bassfx is None or not handle:
			return 0
		if not fx:
			fx = int(self.bass.BASS_ChannelSetFX(handle, BASS_FX_BFX_PEAKEQ, 0))
			if not fx:
				log.debug("No se pudo crear el ecualizador: %s", ERRORS.get(self.errorCode()))
				return 0
		for i, (freq, gain) in enumerate(bands):
			p = BASS_BFX_PEAKEQ(i, 1.0, 0.0, float(freq), float(gain), BASS_BFX_CHANALL)
			self.bass.BASS_FXSetParameters(fx, ctypes.byref(p))
		return fx

	def removeFx(self, handle: int, fx: int) -> None:
		if handle and fx:
			self.bass.BASS_ChannelRemoveFX(handle, fx)

	# ------------------------------------------------------------- grabación
	def encodeToWav(self, handle: int, path: str) -> int:
		"""Empieza a grabar el canal ``handle`` en un archivo WAV. Devuelve el codificador."""
		if self.bassenc is None:
			raise BassError(37, "La grabación no está disponible (falta bassenc.dll)")
		h = self.bassenc.BASS_Encode_Start(handle, ctypes.c_wchar_p(path), BASS_ENCODE_PCM | BASS_ENCODE_AUTOFREE | BASS_UNICODE, None, None)
		return int(self.check(h, "No se pudo empezar a grabar"))

	def encodeStop(self, encoder: int) -> None:
		if encoder and self.bassenc is not None:
			self.bassenc.BASS_Encode_Stop(encoder)

	def encodeActive(self, encoder: int) -> bool:
		if not encoder or self.bassenc is None:
			return False
		return int(self.bassenc.BASS_Encode_IsActive(encoder)) != BASS_ACTIVE_ENC_STOPPED


def parseStreamTitle(meta: str) -> str:
	"""Extrae ``StreamTitle='...'`` de los metadatos Shoutcast/Icecast."""
	key = "StreamTitle='"
	i = meta.find(key)
	if i < 0:
		return ""
	start = i + len(key)
	end = meta.find("';", start)
	if end < 0:
		end = meta.rfind("'")
		if end < start:
			end = len(meta)
	return meta[start:end].strip()


def parseHlsTitle(text: str) -> str:
	"""Título de una línea ``#EXTINF`` de HLS (atributos ``title=``/``artist=`` o texto)."""
	import re

	attrs = dict(re.findall(r'(\w+)="([^"]*)"', text))
	if attrs:
		title = attrs.get("title", "")
		artist = attrs.get("artist", "")
		if artist and title:
			return f"{artist} - {title}"
		return title or artist
	return text


_instance: Bass | None = None
_instanceLock = threading.Lock()


def get(dllDir: str = DLL_DIR) -> Bass:
	"""Instancia compartida del envoltorio (carga las DLL la primera vez)."""
	global _instance
	with _instanceLock:
		if _instance is None:
			_instance = Bass(dllDir)
		return _instance
