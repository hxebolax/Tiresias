"""Envoltorio ctypes propio de la biblioteca de audio BASS (``bass.dll``, x64).

Solo declara lo que usa el complemento: iniciar la salida de audio, elegir el
dispositivo, crear flujos desde un archivo o una dirección de Internet,
reproducir, pausar, detener, volumen, frecuencia (velocidad), posición,
duración y el ecualizador paramétrico DX8 de BASS.

BASS es © Un4seen Developments (https://www.un4seen.com). Es gratuita para
uso no comercial; cualquier uso comercial necesita una licencia de Un4seen.
El aviso completo está en ``lib\\LICENCIA_BASS.txt`` del complemento.
"""

from __future__ import annotations

import ctypes
import os
import threading
from ctypes import POINTER, Structure, byref, c_char_p, c_double, c_float, c_int, c_uint32, c_uint64, c_void_p, c_wchar_p

DWORD = c_uint32
QWORD = c_uint64
BOOL = c_int
HSTREAM = DWORD
HFX = DWORD

# ---------------------------------------------------------------- constantes
BASS_OK = 0
BASS_ERROR_FILEOPEN = 2
BASS_ERROR_DRIVER = 3
BASS_ERROR_HANDLE = 5
BASS_ERROR_FORMAT = 6
BASS_ERROR_POSITION = 7
BASS_ERROR_INIT = 8
BASS_ERROR_ALREADY = 14
BASS_ERROR_ILLPARAM = 20
BASS_ERROR_DEVICE = 23
BASS_ERROR_NOTAVAIL = 37
BASS_ERROR_NONET = 32
BASS_ERROR_TIMEOUT = 40
BASS_ERROR_FILEFORM = 41
BASS_ERROR_SSL = 10
BASS_ERROR_UNKNOWN = -1

BASS_CONFIG_NET_TIMEOUT = 11
BASS_CONFIG_NET_BUFFER = 12
BASS_CONFIG_NET_AGENT = 16
BASS_CONFIG_DEV_DEFAULT = 36
BASS_CONFIG_UNICODE = 42

BASS_DEVICE_ENABLED = 1
BASS_DEVICE_DEFAULT = 2
BASS_DEVICE_INIT = 4

BASS_STREAM_DECODE = 0x200000
BASS_STREAM_AUTOFREE = 0x40000
BASS_UNICODE = 0x80000000
BASS_SAMPLE_FLOAT = 256

BASS_ATTRIB_FREQ = 1
BASS_ATTRIB_VOL = 2

BASS_POS_BYTE = 0

BASS_ACTIVE_STOPPED = 0
BASS_ACTIVE_PLAYING = 1
BASS_ACTIVE_STALLED = 2
BASS_ACTIVE_PAUSED = 3
BASS_ACTIVE_PAUSED_DEVICE = 4

BASS_FX_DX8_PARAMEQ = 7

#: Mensajes en español de los errores más habituales de BASS.
MENSAJES_ERROR = {
	BASS_ERROR_FILEOPEN: "No se pudo abrir el archivo o la dirección.",
	BASS_ERROR_DRIVER: "No hay un controlador de audio disponible.",
	BASS_ERROR_HANDLE: "El flujo de audio no es válido.",
	BASS_ERROR_FORMAT: "El formato de salida no está admitido.",
	BASS_ERROR_POSITION: "La posición pedida no es válida.",
	BASS_ERROR_INIT: "La salida de audio no está iniciada.",
	BASS_ERROR_ALREADY: "La salida de audio ya estaba iniciada.",
	BASS_ERROR_SSL: "No se admite la conexión segura (SSL).",
	BASS_ERROR_ILLPARAM: "Parámetro no válido.",
	BASS_ERROR_DEVICE: "El dispositivo de audio no es válido.",
	BASS_ERROR_NONET: "No hay conexión a Internet.",
	BASS_ERROR_NOTAVAIL: "La operación no está disponible.",
	BASS_ERROR_TIMEOUT: "El servidor no respondió a tiempo.",
	BASS_ERROR_FILEFORM: "El formato del archivo no está admitido.",
}


class BASS_DEVICEINFO(Structure):
	_fields_ = [("name", c_char_p), ("driver", c_char_p), ("flags", DWORD)]


class BASS_CHANNELINFO(Structure):
	_fields_ = [
		("freq", DWORD),
		("chans", DWORD),
		("flags", DWORD),
		("ctype", DWORD),
		("origres", DWORD),
		("plugin", DWORD),
		("sample", DWORD),
		("filename", c_void_p),
	]


class BASS_DX8_PARAMEQ(Structure):
	_fields_ = [("fCenter", c_float), ("fBandwidth", c_float), ("fGain", c_float)]


class BassError(Exception):
	"""Error devuelto por BASS (``codigo`` es el de ``BASS_ErrorGetCode``)."""

	def __init__(self, codigo: int, funcion: str = "") -> None:
		self.codigo = codigo
		self.funcion = funcion
		texto = MENSAJES_ERROR.get(codigo, f"Error de BASS {codigo}.")
		super().__init__(f"{texto} ({funcion}, código {codigo})" if funcion else texto)


# ---------------------------------------------------------------- carga de la DLL
def rutaDll() -> str:
	"""Ruta de ``bass.dll`` dentro del complemento (``lib\\x64``)."""
	raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
	return os.path.join(raiz, "lib", "x64", "bass.dll")


_dll = None
_lockCarga = threading.Lock()


def _declarar(dll) -> None:
	def f(nombre, res, *args):
		fn = getattr(dll, nombre)
		fn.restype = res
		fn.argtypes = list(args)

	f("BASS_GetVersion", DWORD)
	f("BASS_ErrorGetCode", c_int)
	f("BASS_SetConfig", BOOL, DWORD, DWORD)
	f("BASS_GetConfig", DWORD, DWORD)
	f("BASS_SetConfigPtr", BOOL, DWORD, c_void_p)
	f("BASS_Init", BOOL, c_int, DWORD, DWORD, c_void_p, c_void_p)
	f("BASS_Free", BOOL)
	f("BASS_SetDevice", BOOL, DWORD)
	f("BASS_GetDevice", DWORD)
	f("BASS_GetDeviceInfo", BOOL, DWORD, POINTER(BASS_DEVICEINFO))
	f("BASS_StreamCreateFile", HSTREAM, BOOL, c_void_p, QWORD, QWORD, DWORD)
	f("BASS_StreamCreateURL", HSTREAM, c_void_p, DWORD, DWORD, c_void_p, c_void_p)
	f("BASS_StreamFree", BOOL, HSTREAM)
	f("BASS_ChannelPlay", BOOL, DWORD, BOOL)
	f("BASS_ChannelPause", BOOL, DWORD)
	f("BASS_ChannelStop", BOOL, DWORD)
	f("BASS_ChannelIsActive", DWORD, DWORD)
	f("BASS_ChannelSetAttribute", BOOL, DWORD, DWORD, c_float)
	f("BASS_ChannelGetAttribute", BOOL, DWORD, DWORD, POINTER(c_float))
	f("BASS_ChannelGetInfo", BOOL, DWORD, POINTER(BASS_CHANNELINFO))
	f("BASS_ChannelGetPosition", QWORD, DWORD, DWORD)
	f("BASS_ChannelSetPosition", BOOL, DWORD, QWORD, DWORD)
	f("BASS_ChannelGetLength", QWORD, DWORD, DWORD)
	f("BASS_ChannelBytes2Seconds", c_double, DWORD, QWORD)
	f("BASS_ChannelSeconds2Bytes", QWORD, DWORD, c_double)
	f("BASS_ChannelSetDevice", BOOL, DWORD, DWORD)
	f("BASS_ChannelGetData", DWORD, DWORD, c_void_p, DWORD)
	f("BASS_ChannelSetFX", HFX, DWORD, DWORD, c_int)
	f("BASS_ChannelRemoveFX", BOOL, DWORD, HFX)
	f("BASS_FXSetParameters", BOOL, HFX, c_void_p)
	f("BASS_FXGetParameters", BOOL, HFX, c_void_p)


def cargar(ruta: str | None = None):
	"""Carga ``bass.dll`` (una sola vez) y devuelve el objeto de la DLL."""
	global _dll
	with _lockCarga:
		if _dll is None:
			ruta = ruta or rutaDll()
			if not os.path.isfile(ruta):
				raise OSError(f"No se encuentra la biblioteca de audio BASS: {ruta}")
			dll = ctypes.WinDLL(ruta)
			_declarar(dll)
			_dll = dll
		return _dll


def dll():
	return cargar()


def ultimoError() -> int:
	return int(dll().BASS_ErrorGetCode())


def _comprobar(resultado, funcion: str):
	"""Lanza :class:`BassError` si una función BOOL de BASS devolvió falso."""
	if not resultado:
		raise BassError(ultimoError(), funcion)
	return resultado


def version() -> str:
	"""Versión de BASS como texto (por ejemplo ``2.4.16.0``)."""
	v = int(dll().BASS_GetVersion())
	return f"{(v >> 24) & 0xFF}.{(v >> 16) & 0xFF}.{(v >> 8) & 0xFF}.{v & 0xFF}"


# ---------------------------------------------------------------- salida de audio
def iniciar(dispositivo: int = -1, frecuencia: int = 44100) -> int:
	"""Inicia la salida de audio y devuelve el número de dispositivo en uso.

	``-1`` es el dispositivo predeterminado de Windows (y lo sigue aunque
	cambie); ``0`` es «sin sonido» (solo para pruebas). Si el dispositivo ya
	estaba iniciado, simplemente se selecciona.
	"""
	d = dll()
	d.BASS_SetConfig(BASS_CONFIG_UNICODE, 1)
	d.BASS_SetConfig(BASS_CONFIG_DEV_DEFAULT, 1)
	if d.BASS_Init(int(dispositivo), int(frecuencia), 0, None, None):
		return int(d.BASS_GetDevice())
	codigo = ultimoError()
	if codigo != BASS_ERROR_ALREADY:
		raise BassError(codigo, "BASS_Init")
	numero = int(dispositivo)
	if numero == -1:
		numero = _predeterminadoIniciado()
	if numero >= 0:
		d.BASS_SetDevice(numero)
	return int(d.BASS_GetDevice())


def _predeterminadoIniciado() -> int:
	"""Número del dispositivo predeterminado ya iniciado (o -1)."""
	info = BASS_DEVICEINFO()
	d = dll()
	i = 1
	while i <= 64 and d.BASS_GetDeviceInfo(i, byref(info)):
		if info.flags & BASS_DEVICE_DEFAULT and info.flags & BASS_DEVICE_INIT:
			return i
		i += 1
	return -1


def seleccionar(numero: int) -> None:
	"""Usa ``numero`` en las llamadas siguientes de este hilo (BASS lo guarda por hilo)."""
	if numero is not None and numero >= 0:
		dll().BASS_SetDevice(int(numero))


def liberar(numero: int | None = None) -> None:
	"""Libera la salida de audio (del dispositivo ``numero`` o del actual)."""
	try:
		if numero is not None and numero >= 0:
			dll().BASS_SetDevice(int(numero))
		dll().BASS_Free()
	except Exception:
		pass


def liberarTodo() -> None:
	"""Libera todos los dispositivos que esta copia de BASS tenga iniciados."""
	try:
		d = dll()
		info = BASS_DEVICEINFO()
		i = 0
		while i <= 64 and d.BASS_GetDeviceInfo(i, byref(info)):
			if info.flags & BASS_DEVICE_INIT:
				d.BASS_SetDevice(i)
				d.BASS_Free()
			i += 1
	except Exception:
		pass


def dispositivos() -> list[tuple[int, str, bool]]:
	"""Dispositivos de salida reales: ``(número de BASS, nombre, predeterminado)``.

	El 0 («Sin sonido») no se incluye.
	"""
	d = dll()
	d.BASS_SetConfig(BASS_CONFIG_UNICODE, 1)
	res: list[tuple[int, str, bool]] = []
	info = BASS_DEVICEINFO()
	i = 1
	while d.BASS_GetDeviceInfo(i, byref(info)):
		# Sin controlador es la entrada «Default» (la que sigue al predeterminado).
		if info.flags & BASS_DEVICE_ENABLED and info.name and info.driver:
			nombre = info.name.decode("utf-8", "replace")
			res.append((i, nombre, bool(info.flags & BASS_DEVICE_DEFAULT)))
		i += 1
		if i > 64:
			break
	return res


def dispositivoIniciado(numero: int) -> bool:
	info = BASS_DEVICEINFO()
	if not dll().BASS_GetDeviceInfo(int(numero), byref(info)):
		return False
	return bool(info.flags & BASS_DEVICE_INIT)


# ---------------------------------------------------------------- flujos
class Flujo:
	"""Un flujo de BASS (archivo o dirección de Internet)."""

	def __init__(self, handle: int, origen: str) -> None:
		self.handle = int(handle)
		self.origen = origen
		self._liberado = False

	# -- creación
	@classmethod
	def desdeArchivo(cls, ruta: str, decodificar: bool = False) -> "Flujo":
		flags = BASS_UNICODE | (BASS_STREAM_DECODE if decodificar else 0)
		h = dll().BASS_StreamCreateFile(False, c_wchar_p(ruta), 0, 0, flags)
		if not h:
			raise BassError(ultimoError(), "BASS_StreamCreateFile")
		return cls(h, ruta)

	@classmethod
	def desdeUrl(cls, url: str, cabeceras: dict[str, str] | None = None, decodificar: bool = False) -> "Flujo":
		"""Crea un flujo de Internet. Las cabeceras HTTP extra (por ejemplo la de
		autenticación) se añaden tras la dirección, cada una terminada en CRLF."""
		texto = url
		if cabeceras:
			texto = url + "\r\n" + "".join(f"{k}: {v}\r\n" for k, v in cabeceras.items())
		flags = BASS_UNICODE | (BASS_STREAM_DECODE if decodificar else 0)
		h = dll().BASS_StreamCreateURL(c_wchar_p(texto), 0, flags, None, None)
		if not h:
			raise BassError(ultimoError(), "BASS_StreamCreateURL")
		return cls(h, url)

	# -- control
	def reproducir(self, reiniciar: bool = False) -> None:
		_comprobar(dll().BASS_ChannelPlay(self.handle, bool(reiniciar)), "BASS_ChannelPlay")

	def pausar(self) -> None:
		_comprobar(dll().BASS_ChannelPause(self.handle), "BASS_ChannelPause")

	def detener(self) -> None:
		dll().BASS_ChannelStop(self.handle)

	def liberar(self) -> None:
		if not self._liberado:
			self._liberado = True
			dll().BASS_StreamFree(self.handle)

	def actividad(self) -> int:
		return int(dll().BASS_ChannelIsActive(self.handle))

	# -- atributos
	def setAtributo(self, atributo: int, valor: float) -> None:
		_comprobar(dll().BASS_ChannelSetAttribute(self.handle, atributo, float(valor)), "BASS_ChannelSetAttribute")

	def getAtributo(self, atributo: int) -> float:
		v = c_float()
		_comprobar(dll().BASS_ChannelGetAttribute(self.handle, atributo, byref(v)), "BASS_ChannelGetAttribute")
		return float(v.value)

	def info(self) -> BASS_CHANNELINFO:
		i = BASS_CHANNELINFO()
		_comprobar(dll().BASS_ChannelGetInfo(self.handle, byref(i)), "BASS_ChannelGetInfo")
		return i

	# -- posición
	def posicionBytes(self) -> int:
		v = int(dll().BASS_ChannelGetPosition(self.handle, BASS_POS_BYTE))
		return 0 if v == 0xFFFFFFFFFFFFFFFF else v

	def longitudBytes(self) -> int:
		v = int(dll().BASS_ChannelGetLength(self.handle, BASS_POS_BYTE))
		return 0 if v == 0xFFFFFFFFFFFFFFFF else v

	def bytesASegundos(self, n: int) -> float:
		v = float(dll().BASS_ChannelBytes2Seconds(self.handle, int(n)))
		return max(0.0, v)

	def segundosABytes(self, s: float) -> int:
		v = int(dll().BASS_ChannelSeconds2Bytes(self.handle, float(s)))
		return 0 if v == 0xFFFFFFFFFFFFFFFF else v

	def posicion(self) -> float:
		return self.bytesASegundos(self.posicionBytes())

	def duracion(self) -> float:
		return self.bytesASegundos(self.longitudBytes())

	def setPosicion(self, segundos: float) -> None:
		_comprobar(dll().BASS_ChannelSetPosition(self.handle, self.segundosABytes(max(0.0, segundos)), BASS_POS_BYTE), "BASS_ChannelSetPosition")

	def setDispositivo(self, numero: int) -> None:
		_comprobar(dll().BASS_ChannelSetDevice(self.handle, int(numero)), "BASS_ChannelSetDevice")

	def leerDatos(self, n: int) -> bytes:
		"""Lee ``n`` bytes decodificados (solo flujos creados con ``decodificar``)."""
		buf = ctypes.create_string_buffer(n)
		r = int(dll().BASS_ChannelGetData(self.handle, buf, n))
		if r == 0xFFFFFFFF:
			return b""
		return buf.raw[:r]

	# -- efectos
	def ponerEcualizador(self, centro: float, anchoBanda: float, ganancia: float) -> int:
		"""Añade una banda del ecualizador paramétrico DX8; devuelve su identificador."""
		fx = int(dll().BASS_ChannelSetFX(self.handle, BASS_FX_DX8_PARAMEQ, 0))
		if not fx:
			raise BassError(ultimoError(), "BASS_ChannelSetFX")
		p = BASS_DX8_PARAMEQ(float(centro), float(anchoBanda), float(ganancia))
		if not dll().BASS_FXSetParameters(fx, byref(p)):
			codigo = ultimoError()
			dll().BASS_ChannelRemoveFX(self.handle, fx)
			raise BassError(codigo, "BASS_FXSetParameters")
		return fx

	def quitarEfecto(self, fx: int) -> None:
		dll().BASS_ChannelRemoveFX(self.handle, int(fx))
