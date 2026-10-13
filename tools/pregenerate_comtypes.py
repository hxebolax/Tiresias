"""Genera de antemano los módulos de comtypes que Tiresias usa.

En la versión compilada la carpeta ``comtypes.gen`` no se puede escribir,
así que las envolturas COM deben existir antes de compilar.
"""

from __future__ import annotations

import os

import comtypes.client

TYPELIBS = [
	"UIAutomationCore.dll",
	os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "Speech", "Common", "sapi.dll"),
	os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "wshom.ocx"),
	"oleacc.dll",
]

for lib in TYPELIBS:
	try:
		mod = comtypes.client.GetModule(lib)
		print(f"Generado: {lib} -> {mod.__name__}")
	except Exception as e:  # noqa: BLE001
		print(f"No se pudo generar {lib}: {e}")

# Objetos que se crean dinámicamente y generan sus propios módulos.
for progId in ("SAPI.SpVoice", "SAPI.SpMemoryStream", "SAPI.SpAudioFormat", "WScript.Shell"):
	try:
		comtypes.client.CreateObject(progId)
		print(f"Probado: {progId}")
	except Exception as e:  # noqa: BLE001
		print(f"No disponible {progId}: {e}")
