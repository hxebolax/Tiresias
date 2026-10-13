"""Controladores de líneas braille físicas incluidos en Tiresias.

Cada módulo de este paquete define ``BrailleDisplayDriver`` (el nombre del
módulo es el del controlador, que aparece en los gestos ``br(<nombre>):``).
La infraestructura común está en:

- :mod:`.hwio`: conexiones serie, HID, USB bulk (Win32) y simulada;
- :mod:`.ports`: enumeración de dispositivos USB, HID y puertos COM/Bluetooth;
- :mod:`.base`: controlador base (conexión, reconexión, gestos);
- :mod:`.detect`: detección automática;
- :mod:`.auto`: el controlador «Automático».
"""

from __future__ import annotations

import importlib

from ...log import getLogger

log = getLogger("braille.drivers")

#: Controladores incluidos, en el orden en que los prueba la detección
#: automática (el estándar HID Braille el último: es la alternativa genérica).
DRIVER_NAMES: list[str] = [
	"freedomScientific",
	"brailliantB",
	"brailleNote",
	"hims",
	"baum",
	"handyTech",
	"alva",
	"eurobraille",
	"papenmeier",
	"seika",
	# Comparte el chip CP210x con las Seika: lo prueba después (tryClaimedPorts).
	"superBrl",
	"seikaNotetaker",
	# La MobilLine antes que la ProfiLine: el controlador de la ProfiLine
	# también acepta el identificador de la MobilLine (como en NVDA).
	"hedoMobilLine",
	"hedoProfiLine",
	"nattiqbraille",
	"dotPad",
	# Comparte el chip FTDI con otras líneas: se prueba después (tryClaimedPorts).
	"albatross",
	# Sin detección automática (puerto serie elegido a mano o DLL del fabricante).
	"ecoBraille",
	"lilli",
	"brltty",
	"hidBraille",
]


#: Controladores que fallaron al importarse (se avisa una sola vez).
_failed: set[str] = set()


def initialize() -> None:
	"""Prepara los gestos de las líneas.

	Sus opciones están en la categoría «Braille» del cuadro de Opciones.
	"""
	from .base import registerDecider

	registerDecider()


def getDriverClass(name: str):
	"""Clase de un controlador (incluidos los de complementos)."""
	from .. import getDriverClass as _get

	return _get(name)


def availableDrivers() -> list[str]:
	"""Nombres de los controladores incluidos que se pueden cargar."""
	out = []
	for name in DRIVER_NAMES:
		try:
			importlib.import_module(f"{__name__}.{name}")
		except ModuleNotFoundError:
			continue
		except Exception:
			if name not in _failed:
				_failed.add(name)
				log.exception("No se pudo cargar el controlador braille %s", name)
			continue
		out.append(name)
	return out


def hardwareDriverChoices() -> list[tuple[str, str]]:
	"""(nombre, descripción) de las líneas físicas, ordenadas por descripción."""
	out = []
	for name in availableDrivers():
		try:
			cls = getDriverClass(name)
		except Exception:
			continue
		out.append((name, cls.description))
	out.sort(key=lambda p: p[1].lower())
	return out
