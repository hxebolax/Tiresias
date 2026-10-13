"""Utilidades para probar los controladores de líneas braille sin hardware.

- :func:`connectSimulated` crea el controlador como lo haría la detección,
  pero la conexión es una :class:`MemoryTransport`: el ``responder`` contesta a
  lo que escribe el controlador (saludo inicial, petición de celdas...).
- :func:`gestureIds` devuelve los gestos producidos (identificador genérico).
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(ROOT, "src") not in sys.path:
	sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_brailleSimDataDir", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_braille_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	try:
		paths.setDataDir(_TMP)
		paths.ensureDataDirs()
	except Exception:
		pass
	paths._brailleSimDataDir = _TMP

from tiresias.braille.drivers import hwio  # noqa: E402
from tiresias.braille.drivers.base import DeviceMatch  # noqa: E402


def connectSimulated(cls, responder=None, matchType="serial", port="COM9", bluetooth=False, usbId="", outputSize=0, name=""):
	"""Crea ``cls`` conectado a una línea simulada. Devuelve (controlador, conexión)."""
	transport = hwio.MemoryTransport(kind=matchType, responder=responder, port=port, outputSize=outputSize, info={"bluetooth": bluetooth})
	opened = []

	def fakeOpen(self, match, baudrate=None, **kwargs):
		transport.onReceive = self._onReceive
		transport.onError = self._onIoError
		transport.baudrate = baudrate
		transport.openArgs = kwargs
		transport.closed = False
		opened.append((match, baudrate, kwargs))
		return transport

	transport.opened = opened
	match = DeviceMatch(matchType, usbId or name, port, bluetooth)
	with mock.patch.object(cls, "_open", fakeOpen):
		driver = cls(match=match, configName=cls.name)
	driver.lastGestures = []
	return driver, transport


def gestureIds(driver, clear=True):
	"""Identificadores genéricos (``br(x):...``) de los gestos producidos."""
	ids = [g.identifiers[-1] for g in driver.lastGestures]
	if clear:
		driver.lastGestures.clear()
	return ids


def lastGesture(driver):
	return driver.lastGestures[-1] if driver.lastGestures else None
