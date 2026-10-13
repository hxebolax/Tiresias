"""Ejemplo de uso de la API de control de Tiresias desde Python (ctypes).

Funciona con Python de 32 o de 64 bits: se elige la biblioteca adecuada.
Ejecutar con Tiresias (o NVDA) en marcha::

	python ejemplo.py
"""

import ctypes
import ctypes.wintypes as wt
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
ARCH = "x64" if struct.calcsize("P") == 8 else "x86"
# En el programa compilado: data\controller\examples -> data\controller\<arq>.
# Desde el código fuente: controller\examples -> data\controller\<arq>.
_candidates = [
	os.path.join(HERE, "..", ARCH, "tiresiasControllerClient.dll"),
	os.path.join(HERE, "..", "..", "data", "controller", ARCH, "tiresiasControllerClient.dll"),
]
dll = ctypes.WinDLL(next((p for p in _candidates if os.path.isfile(p)), _candidates[0]))

TIRESIAS_SPEAK_INTERRUPT = 0x1
TIRESIAS_SPEAK_SPELL = 0x2
TIRESIAS_SPEAK_BRAILLE = 0x4

if dll.tiresiasController_testIfRunning() != 0:
	raise SystemExit("No hay ningún lector de pantalla en ejecución")

version = wt.ULONG()
if dll.tiresiasController_getApiVersion(ctypes.byref(version)) == 0:
	print(f"Tiresias, API {version.value >> 16}.{version.value & 0xFFFF}")

dll.tiresiasController_speakText("Hola desde el ejemplo en Python.")
dll.tiresiasController_brailleMessage("Ejemplo en braille")
dll.tiresiasController_speakTextEx("abc", TIRESIAS_SPEAK_INTERRUPT | TIRESIAS_SPEAK_SPELL)

MarkCallback = ctypes.WINFUNCTYPE(ctypes.c_ulong, wt.LPCWSTR)


def onMark(name):
	print("Marca alcanzada:", name)
	return 0


callback = MarkCallback(onMark)  # hay que conservar la referencia
dll.tiresiasController_setOnSsmlMarkReachedCallback(callback)
dll.tiresiasController_speakSsml('<speak>Uno <mark name="uno"/> dos <mark name="dos"/></speak>', -1, 0, False)
dll.tiresiasController_setOnSsmlMarkReachedCallback(None)

speaking = ctypes.c_ubyte()
dll.tiresiasController_isSpeaking(ctypes.byref(speaking))
print("Hablando:", bool(speaking.value))
