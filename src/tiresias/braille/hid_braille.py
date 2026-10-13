"""Compatibilidad: el controlador HID Braille está ahora en
:mod:`tiresias.braille.drivers.hidBraille` (nombre del controlador:
``hidBraille``; los gestos siguen siendo ``br(hidBraille):...``).
"""

from __future__ import annotations

from .drivers.base import BrailleGesture  # noqa: F401
from .drivers.hidBraille import BUTTON_NAMES, USAGE_PAGE_BRAILLE, HidBrailleDriver, HidLayout  # noqa: F401

BrailleDisplayDriver = HidBrailleDriver


def findDevices() -> list[str]:
	"""Rutas de las líneas braille HID conectadas (sin abrirlas)."""
	from .drivers import ports

	return [m.port for m in HidBrailleDriver.getMatches(ports.listHidDevices())]
