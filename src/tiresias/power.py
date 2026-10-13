"""Evita que la pantalla se apague durante la lectura continua.

Con ``general.preventDisplayTurningOff`` activada, mientras dura una lectura
continua se pide a Windows que mantenga encendidos la pantalla y el equipo
(``SetThreadExecutionState``). Al terminar se devuelve el control a Windows.
La petición se hace siempre desde el hilo del núcleo, que es el que la
mantiene.
"""

from __future__ import annotations

import ctypes

from .config import conf, post_triggerChange
from .log import getLogger

log = getLogger("power")

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

_kernel32 = ctypes.WinDLL("kernel32")
_kernel32.SetThreadExecutionState.argtypes = [ctypes.c_uint32]
_kernel32.SetThreadExecutionState.restype = ctypes.c_uint32

#: ``True`` mientras se mantiene encendida la pantalla.
active = False
_initialized = False


def keepDisplayOn(on: bool) -> None:
	global active
	if on == active:
		return
	flags = ES_CONTINUOUS | (ES_DISPLAY_REQUIRED | ES_SYSTEM_REQUIRED if on else 0)
	if _kernel32.SetThreadExecutionState(flags) == 0:
		log.debug("SetThreadExecutionState falló")
		return
	active = on


def _onTrigger(trigger: str = "", entered: bool = False, **kw) -> None:
	if trigger != "sayAll":
		return
	if entered:
		if conf["general"]["preventDisplayTurningOff"]:
			keepDisplayOn(True)
	else:
		keepDisplayOn(False)


def initialize() -> None:
	global _initialized
	if _initialized:
		return
	_initialized = True
	post_triggerChange.register(_onTrigger)


def terminate() -> None:
	keepDisplayOn(False)
