"""Registro de los cierres inesperados de Tiresias en ``logs/fallos.log``.

Antes se usaba ``faulthandler.enable()``. En Windows, ``faulthandler`` instala
un manejador de excepciones *vectorizado*: se ejecuta con CUALQUIER excepción
SEH que tenga el bit de gravedad, también las que el sistema lanza y recoge
él mismo. COM y RPC lo hacen continuamente (``RPC_E_CANTCALLOUT_ININPUTSYNCCALL``
0x8001010D al leer un RichEdit, ``RPC_E_DISCONNECTED``, ``RPC_E_SERVERFAULT``,
violaciones de acceso dentro de un servidor COM que el propio COM convierte en
error…). Cada una dejaba en ``fallos.log`` un «Windows fatal exception» con las
pilas de todos los hilos (unos 7 KB escritos en disco en mitad de la llamada
COM), aunque el programa siguiera funcionando: cientos de KB de falsos cierres
en un minuto que tapaban los de verdad.

Aquí, como hace NVDA (``watchdog``/``_crashHandler``), solo se registran los
cierres reales:

- **Excepción SEH no gestionada** (violación de acceso, pila agotada…):
  ``SetUnhandledExceptionFilter``. Windows llama al filtro solo cuando nadie
  ha recogido la excepción, es decir, cuando el proceso se va a cerrar. Se
  escribe el código, la dirección, el módulo y las pilas de Python de todos
  los hilos, y se deja que Windows termine el proceso como siempre.
- **abort()** (error fatal de una biblioteca o del intérprete): manejador de
  ``SIGABRT`` del CRT, con las mismas pilas.

Con la variable de entorno ``TIRESIAS_FAULTHANDLER=1`` se vuelve al
``faulthandler`` completo (registra también las excepciones gestionadas), útil
solo para depurar.
"""

from __future__ import annotations

import atexit
import ctypes
import datetime
import faulthandler
import os
import threading
from ctypes import wintypes

from .log import getLogger

log = getLogger("crashLog")

EXCEPTION_CONTINUE_SEARCH = 0
SIGABRT = 22

#: Nombres de los códigos de excepción más habituales.
EXCEPTION_NAMES = {
	0xC0000005: "violación de acceso",
	0xC00000FD: "pila agotada",
	0xC0000374: "montón dañado",
	0xC0000409: "desbordamiento de búfer en la pila",
	0xC000001D: "instrucción no válida",
	0xC0000094: "división entera por cero",
	0xC0000096: "instrucción privilegiada",
	0xC0000006: "error de página de entrada",
	0x80000003: "punto de interrupción",
	0xE06D7363: "excepción de C++",
	0xC0000420: "aserción",
}


class EXCEPTION_RECORD(ctypes.Structure):
	pass


EXCEPTION_RECORD._fields_ = [
	("ExceptionCode", wintypes.DWORD),
	("ExceptionFlags", wintypes.DWORD),
	("ExceptionRecord", ctypes.POINTER(EXCEPTION_RECORD)),
	("ExceptionAddress", ctypes.c_void_p),
	("NumberParameters", wintypes.DWORD),
	("ExceptionInformation", ctypes.c_size_t * 15),
]


class EXCEPTION_POINTERS(ctypes.Structure):
	_fields_ = [("ExceptionRecord", ctypes.POINTER(EXCEPTION_RECORD)), ("ContextRecord", ctypes.c_void_p)]


_FILTER = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.POINTER(EXCEPTION_POINTERS))
_SIGNAL = ctypes.CFUNCTYPE(None, ctypes.c_int)

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.SetUnhandledExceptionFilter.argtypes = [ctypes.c_void_p]
_kernel32.SetUnhandledExceptionFilter.restype = ctypes.c_void_p
_kernel32.GetModuleHandleExW.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.HMODULE)]
_kernel32.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]

_file = None
_filterRef = None
_signalRef = None
_writing = threading.Lock()
installed = False


def describeException(code: int, address: int) -> str:
	"""Texto de una excepción: código, nombre, dirección y módulo."""
	code &= 0xFFFFFFFF
	name = EXCEPTION_NAMES.get(code, "")
	text = f"0x{code:08X}" + (f" ({name})" if name else "")
	if address:
		text += f" en 0x{address:X}"
		mod, offset = moduleOf(address)
		if mod:
			text += f" ({mod}+0x{offset:X})"
	return text


def moduleOf(address: int) -> tuple[str, int]:
	h = wintypes.HMODULE()
	# GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | UNCHANGED_REFCOUNT
	if not address or not _kernel32.GetModuleHandleExW(6, ctypes.c_void_p(address), ctypes.byref(h)) or not h.value:
		return "", 0
	buf = ctypes.create_unicode_buffer(260)
	_kernel32.GetModuleFileNameW(h, buf, 260)
	return os.path.basename(buf.value), address - h.value


def _writeCrash(header: str) -> None:
	"""Escribe la cabecera y las pilas de todos los hilos (sin lanzar excepciones)."""
	f = _file
	if f is None:
		return
	# Si dos hilos se caen a la vez, el segundo no espera para siempre.
	got = _writing.acquire(timeout=5)
	try:
		stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
		f.write(f"\n{stamp} {header}\n")
		f.flush()
		faulthandler.dump_traceback(f, all_threads=True)
		f.flush()
	except Exception:
		pass
	finally:
		if got:
			_writing.release()
	try:
		log.critical("%s (pilas de los hilos en fallos.log)", header)
		# El archivo de registro se escribe en otro hilo: se espera a que
		# llegue al disco antes de que Windows termine el proceso.
		from . import log as logModule

		logModule.flush()
	except Exception:
		pass


def _onUnhandled(pointers) -> int:
	try:
		rec = pointers.contents.ExceptionRecord.contents
		desc = describeException(rec.ExceptionCode, rec.ExceptionAddress or 0)
	except Exception:
		desc = "desconocida"
	_writeCrash(f"Cierre inesperado de Tiresias: excepción no gestionada {desc} en el hilo {threading.get_native_id()}")
	# Windows termina el proceso como siempre (y avisa al informe de errores).
	return EXCEPTION_CONTINUE_SEARCH


def _onAbort(_sig: int) -> None:
	_writeCrash(f"Cierre inesperado de Tiresias: abort() en el hilo {threading.get_native_id()} (error fatal del intérprete o de una biblioteca)")


#: Tamaño a partir del cual ``fallos.log`` se aparta (``.1``) al arrancar.
MAX_SIZE = 1024 * 1024
#: Filtro y manejador de abort() que había antes de :func:`install` (se restauran al salir).
_prevFilter = None
_prevSignal = None
_crt = None
_faulthandlerMode = False


def _rotate(path: str) -> None:
	"""``fallos.log`` no crece sin límite: si pasa de :data:`MAX_SIZE` se aparta a ``.1``."""
	try:
		if os.path.getsize(path) > MAX_SIZE:
			os.replace(path, path + ".1")
	except OSError:
		pass


def install(path: str) -> None:
	"""Empieza a registrar los cierres inesperados en ``path``."""
	global _file, _filterRef, _signalRef, installed, _prevFilter, _prevSignal, _crt, _faulthandlerMode
	_rotate(path)
	try:
		_file = open(path, "a", encoding="utf-8")
	except OSError:
		log.debug("No se pudo abrir %s", path, exc_info=True)
		return
	if os.environ.get("TIRESIAS_FAULTHANDLER") == "1":
		# Depuración: faulthandler completo (también las excepciones gestionadas).
		faulthandler.enable(_file, all_threads=True)
		_faulthandlerMode = True
		installed = True
		return
	_filterRef = _FILTER(_onUnhandled)
	_prevFilter = _kernel32.SetUnhandledExceptionFilter(ctypes.cast(_filterRef, ctypes.c_void_p))
	try:
		_signalRef = _SIGNAL(_onAbort)
		crt = ctypes.CDLL("ucrtbase")
		crt.signal.argtypes = [ctypes.c_int, ctypes.c_void_p]
		crt.signal.restype = ctypes.c_void_p
		_prevSignal = crt.signal(SIGABRT, ctypes.cast(_signalRef, ctypes.c_void_p))
		_crt = crt
	except (OSError, AttributeError):
		log.debug("No se pudo instalar el manejador de abort()", exc_info=True)
	installed = True
	atexit.register(uninstall)


def uninstall() -> None:
	"""Restaura el filtro de excepciones y el manejador de abort() anteriores.

	Se llama al terminar ``core.main`` (y en las salidas forzadas): un cierre
	nativo durante la finalización del intérprete llamaría a una retrollamada de
	Python que ya no puede ejecutarse (en 3.14 el hilo se queda colgado
	esperando el GIL) y el proceso no terminaría. Idempotente.
	"""
	global installed, _faulthandlerMode, _crt
	if not installed:
		return
	installed = False
	try:
		if _faulthandlerMode:
			faulthandler.disable()
			_faulthandlerMode = False
			return
		_kernel32.SetUnhandledExceptionFilter(_prevFilter)
		if _crt is not None:
			_crt.signal(SIGABRT, _prevSignal)
			_crt = None
	except Exception:
		log.debug("No se pudieron restaurar los manejadores de cierre", exc_info=True)
	# Las retrollamadas (_filterRef, _signalRef) se conservan: otro hilo podría
	# estar dentro de ellas en este momento.


def dumpThreads(reason: str) -> None:
	"""Vuelca las pilas de todos los hilos con un motivo (núcleo bloqueado…)."""
	f = _file
	if f is None:
		return
	try:
		stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
		f.write(f"\n{stamp} {reason}\n")
		f.flush()
		faulthandler.dump_traceback(f, all_threads=True)
		f.flush()
	except Exception:
		log.debug("No se pudieron volcar las pilas", exc_info=True)
