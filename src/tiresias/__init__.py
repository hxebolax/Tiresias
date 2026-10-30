"""Tiresias: lector de pantalla para Windows escrito en Python.

Este paquete contiene el núcleo del lector. La estructura general es:

- ``core``: arranque, hilos y bucle principal.
- ``config``: configuración, perfiles y esquema de valores por defecto.
- ``speech``, ``synth``, ``audio``: voz, sintetizadores y sonido.
- ``objects``, ``textinfo``, ``a11y``: modelo de objetos accesibles (UIA/MSAA).
- ``input``, ``scripting``, ``commands``: teclado, ratón y órdenes.
- ``browse``: modo exploración para documentos web.
- ``appmodules``, ``plugins``, ``addons``: extensibilidad.
- ``gui``: interfaz gráfica (wxPython).
"""

APP_NAME = "Tiresias"
APP_ID = "tiresias"
VERSION = "1.0.14"
VERSION_TUPLE = (1, 0, 14)
# Versión de la API para complementos. Un complemento declara ``minApiVersion``.
API_VERSION = (1, 0)
COPYRIGHT = "Copyright (C) 2026 Proyecto Tiresias"
URL = ""

# Biblioteca de Visual C++ moderna antes que la antigua de winrt (necesaria
# para onnxruntime, que usan las voces Piper): ver msvc_runtime.py.
try:
	from . import msvc_runtime as _msvcRuntime

	_msvcRuntime.preload()
except Exception:  # pragma: no cover - nunca debe impedir el arranque
	pass
