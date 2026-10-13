"""Detección automática de líneas braille.

Compara los dispositivos USB, HID y puertos serie (incluidos los Bluetooth)
con los identificadores que declara cada controlador y prueba a conectar en
segundo plano. Los dispositivos USB se prueban antes que los Bluetooth; entre
controladores manda el orden de :data:`tiresias.braille.drivers.DRIVER_NAMES`
(el estándar HID Braille va el último, como alternativa).
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from ...config import conf
from ...log import getLogger
from . import ports
from .base import DeviceMatch, DisplayNotFound, HardwareDriver

log = getLogger("braille.detect")

#: Segundos entre exploraciones de dispositivos.
SCAN_INTERVAL = 2.0
#: Los puertos Bluetooth se exploran con menos frecuencia (abrirlos es lento).
BLUETOOTH_INTERVAL = 10.0
#: Tiempo antes de reintentar un dispositivo que no respondió.
RETRY_USB = 5.0
RETRY_BLUETOOTH = 30.0


def _setting(key: str, default):
	try:
		return conf["brailleDisplays"][key]
	except KeyError:
		return default


def excludedDrivers() -> list[str]:
	return list(_setting("excludedFromAuto", []) or [])


def driversForAutoDetection() -> list[str]:
	"""Controladores que participan en la detección automática, en orden."""
	from . import availableDrivers, getDriverClass

	excluded = set(excludedDrivers())
	out = []
	for name in availableDrivers():
		if name in excluded:
			continue
		try:
			cls = getDriverClass(name)
		except Exception:
			log.debug("Controlador %s no disponible", name, exc_info=True)
			continue
		if getattr(cls, "supportsAutoDetection", False):
			out.append(name)
	return out


def findCandidates(
	devices: list[ports.DeviceInfo],
	driverNames: list[str],
	bluetooth: bool = True,
	allowGeneric: bool = False,
	classes: dict[str, type[HardwareDriver]] | None = None,
) -> list[tuple[str, DeviceMatch]]:
	"""Pares (controlador, dispositivo) que se pueden probar, USB primero.

	Cada dispositivo se asigna al primer controlador que lo reconoce, salvo
	los controladores con ``tryClaimedPorts``, que lo prueban después.
	"""
	from . import getDriverClass

	usb: list[tuple[str, DeviceMatch]] = []
	bt: list[tuple[str, DeviceMatch]] = []
	claimed: set[str] = set()
	for name in driverNames:
		cls = classes[name] if classes is not None else getDriverClass(name)
		shares = bool(getattr(cls, "tryClaimedPorts", False))
		for m in cls.getMatches(devices, usb=True, bluetooth=bluetooth, allowGeneric=allowGeneric):
			if m.port in claimed and not shares:
				continue
			claimed.add(m.port)
			(bt if m.bluetooth else usb).append((name, m))
	return usb + bt


class Detector:
	"""Busca líneas en segundo plano hasta que una conecta.

	``onFound`` recibe el controlador ya conectado (en el hilo del detector).
	"""

	def __init__(self, onFound: Callable[[HardwareDriver], None], driverNames: list[str] | None = None) -> None:
		self._onFound = onFound
		self._driverNames = driverNames
		self._stop = threading.Event()
		self._wake = threading.Event()
		self._failed: dict[str, float] = {}
		self._thread = threading.Thread(target=self._run, name="braille-detect", daemon=True)

	def start(self) -> None:
		self._thread.start()

	def rescan(self) -> None:
		self._failed.clear()
		self._wake.set()

	def stop(self) -> None:
		"""Pide parar sin esperar al hilo (se llama desde el hilo del núcleo).

		Si el hilo está a mitad de una conexión, al terminarla ve la parada y
		cierra él mismo el controlador que haya abierto.
		"""
		self._stop.set()
		self._wake.set()

	def _run(self) -> None:
		lastBluetooth = -1e9
		while not self._stop.is_set():
			try:
				names = self._driverNames if self._driverNames is not None else driversForAutoDetection()
				now = time.monotonic()
				withBt = bool(_setting("detectBluetooth", True)) and now - lastBluetooth >= BLUETOOTH_INTERVAL
				if withBt:
					lastBluetooth = now
				if self._tryAll(names, withBt):
					return
			except Exception:
				log.exception("Error en la detección automática de líneas braille")
			self._wake.wait(SCAN_INTERVAL)
			self._wake.clear()

	def _tryAll(self, names: list[str], withBluetooth: bool) -> bool:
		from . import getDriverClass

		devices = ports.listAll()
		candidates = findCandidates(devices, names, bluetooth=withBluetooth, allowGeneric=bool(_setting("detectGenericUsb", False)))
		# BRLTTY no es un dispositivo: se prueba si su servicio está en marcha.
		if "brltty" in names:
			try:
				cls = getDriverClass("brltty")
				candidates[:0] = [("brltty", m) for m in cls.getMatches(devices)]
			except Exception:
				log.debug("BRLTTY no disponible", exc_info=True)
		for name, match in candidates:
			if self._stop.is_set():
				return True
			key = f"{name}|{match.type}|{match.port}"
			retry = RETRY_BLUETOOTH if match.bluetooth else RETRY_USB
			if time.monotonic() - self._failed.get(key, -1e9) < retry:
				continue
			cls = getDriverClass(name)
			try:
				driver = cls(match=match, configName="auto")
			except DisplayNotFound as e:
				log.debug("Detección: %s", e)
				self._failed[key] = time.monotonic()
				continue
			except Exception:
				log.debug("Detección: error probando %s en %s", name, match.port, exc_info=True)
				self._failed[key] = time.monotonic()
				continue
			if self._stop.is_set():
				driver.terminate()
				return True
			self._onFound(driver)
			return True
		return False


def testConnection(name: str, port: str, timeout: float = 20.0) -> tuple[bool, str, int]:
	"""Prueba a conectar con una línea (en un hilo secundario).

	Devuelve (conectada, nombre del aparato y conexión, celdas).
	"""
	from . import getDriverClass

	pairs: list[tuple[str, DeviceMatch]] = []
	if name == "auto":
		# Una pasada de la detección automática.
		names = driversForAutoDetection()
		devices = ports.listAll()
		pairs = findCandidates(devices, names, bluetooth=bool(_setting("detectBluetooth", True)), allowGeneric=bool(_setting("detectGenericUsb", False)))
		if "brltty" in names:
			try:
				pairs = [("brltty", m) for m in getDriverClass("brltty").getMatches(devices)] + pairs
			except Exception:
				log.debug("BRLTTY no disponible", exc_info=True)
	else:
		cls = getDriverClass(name)
		if not getattr(cls, "isHardware", False):
			return True, cls.description, 0
		try:
			pairs = [(name, m) for m in cls.candidateMatches(port or "auto")]
		except Exception:
			log.debug("Error buscando dispositivos", exc_info=True)
	deadline = time.monotonic() + timeout
	for driverName, match in pairs:
		if time.monotonic() > deadline:
			break
		cls = getDriverClass(driverName)
		try:
			driver = cls(match=match, configName=name)
		except Exception as e:
			log.debug("Prueba de %s en %s: %s", name, match.port, e)
			continue
		try:
			return True, f"{driver.displayName} — {match.describe()}", driver.numCells
		finally:
			driver.terminate()
	return False, "", 0
