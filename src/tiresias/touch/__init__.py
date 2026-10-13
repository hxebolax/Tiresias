"""Soporte de pantalla táctil y de panel táctil de precisión.

Módulos:

- :mod:`.recognizer`: reconocimiento de gestos (puro, sin Windows).
- :mod:`.gestures`: gestos para el gestor de entrada (``ts:...``, ``tp:...``)
  y sus nombres en español.
- :mod:`.overlay`: captura de los toques (superposición transparente o,
  con uiAccess, ``RegisterPointerInputTarget``).
- :mod:`.touchpad`: gestos en el panel táctil con Raw Input e informes HID.
- :mod:`.explorer`: qué hay bajo el dedo y su lectura.
- :mod:`.handler`: activación, modos y ejecución de los gestos.
- :mod:`.commands`: órdenes táctiles y gestos por defecto.
"""
