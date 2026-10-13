"""Pruebas de los controladores braille portados de NVDA en la versión 1.0.12:
EcoBraille, Caiku Albatross, MDV Lilli, hedo ProfiLine y MobilLine,
SuperBraille, Nattiq nBraille y Dot Pad.

No se abre ningún puerto ni dispositivo real: cada línea se simula con una
:class:`~tiresias.braille.drivers.hwio.MemoryTransport` que contesta a lo
que escribe el controlador.
"""

from __future__ import annotations

import os
import struct
import tempfile
import threading
import time
import unittest
from unittest import mock

import braille_sim  # noqa: F401  (prepara rutas y datos)
from braille_sim import connectSimulated, gestureIds

from tiresias.baseobject import normalizeGestureId
from tiresias.braille.drivers import (
	DRIVER_NAMES,
	albatross,
	base,
	detect,
	dotPad,
	ecoBraille,
	getDriverClass,
	hedoMobilLine,
	hedoProfiLine,
	hwio,
	lilli,
	nattiqbraille,
	superBrl,
)
from tiresias.braille.drivers.base import DeviceMatch
from tiresias.braille.drivers.ports import DeviceInfo

NEW_DRIVERS = ["ecoBraille", "albatross", "lilli", "hedoProfiLine", "hedoMobilLine", "superBrl", "nattiqbraille", "dotPad"]

#: ``output_dots_map`` de ecoBraille.py de NVDA (256 valores).
NVDA_ECO_TABLE = bytes.fromhex(
	"0010203040506070011121314151617102122232425262720313233343536373"
	"0414243444546474051525354555657506162636465666760717273747576777"
	"8090a0b0c0d0e0f08191a1b1c1d1e1f18292a2b2c2d2e2f28393a3b3c3d3e3f3"
	"8494a4b4c4d4e4f48595a5b5c5d5e5f58696a6b6c6d6e6f68797a7b7c7d7e7f7"
	"081828384858687809192939495969790a1a2a3a4a5a6a7a0b1b2b3b4b5b6b7b"
	"0c1c2c3c4c5c6c7c0d1d2d3d4d5d6d7d0e1e2e3e4e5e6e7e0f1f2f3f4f5f6f7f"
	"8898a8b8c8d8e8f88999a9b9c9d9e9f98a9aaabacadaeafa8b9babbbcbdbebfb"
	"8c9cacbcccdcecfc8d9dadbdcdddedfd8e9eaebecedeeefe8f9fafbfcfdfefff"
)


class _Line(hwio.MemoryTransport):
	"""Línea simulada que puede enviar datos al abrirse (las que hablan primero)."""

	def __init__(self, onOpen=None, responder=None, **kw):
		super().__init__(responder=responder, kind="serial", port="COM9", **kw)
		self.onOpen = onOpen
		self.purges = 0

	def opened_(self):
		if self.onOpen is not None:
			self.onOpen(self)


def connectWith(cls, transport, matchType="serial", port="COM9", usbId=""):
	"""Como ``connectSimulated`` pero con una conexión simulada propia."""
	opened = []

	def fakeOpen(self, match, baudrate=None, **kwargs):
		transport.onReceive = self._onReceive
		transport.onError = self._onIoError
		transport.baudrate = baudrate
		transport.openArgs = kwargs
		transport.closed = False
		opened.append((match, baudrate, kwargs))
		transport.opened_()
		return transport

	transport.opened = opened
	match = DeviceMatch(matchType, usbId, port, False)
	with mock.patch.object(cls, "_open", fakeOpen):
		driver = cls(match=match, configName=cls.name)
	driver.lastGestures = []
	return driver, transport


def later(delay, func, *args):
	t = threading.Timer(delay, func, args)
	t.daemon = True
	t.start()
	return t


# ====================================================================== comunes
class RegistryTests(unittest.TestCase):
	def test_registered_with_nvda_names(self) -> None:
		for name in NEW_DRIVERS:
			self.assertIn(name, DRIVER_NAMES)
			cls = getDriverClass(name)
			self.assertEqual(cls.name, name)
			self.assertTrue(cls.description)
			self.assertTrue(cls.isHardware)
		# Los que no tienen identificador propio no participan en la detección.
		self.assertFalse(getDriverClass("ecoBraille").supportsAutoDetection)
		self.assertFalse(getDriverClass("lilli").supportsAutoDetection)
		# Orden: la MobilLine antes que la ProfiLine; la SuperBraille tras la Seika.
		self.assertLess(DRIVER_NAMES.index("hedoMobilLine"), DRIVER_NAMES.index("hedoProfiLine"))
		self.assertLess(DRIVER_NAMES.index("seika"), DRIVER_NAMES.index("superBrl"))
		self.assertLess(DRIVER_NAMES.index("hims"), DRIVER_NAMES.index("albatross"))
		self.assertEqual(DRIVER_NAMES[-1], "hidBraille")

	def test_nvda_import_names(self) -> None:
		from tiresias import nvda_import

		for name in NEW_DRIVERS:
			self.assertEqual(nvda_import.tiresiasBrailleDriver(name), name)

	def test_nvda_gesture_key_aliases(self) -> None:
		from tiresias import nvda_import

		tr = lambda gid: nvda_import.translateGesture(gid)[0]  # noqa: E731
		self.assertEqual(tr("br(albatross):secondRouting"), "br(albatross):routing2")
		self.assertEqual(tr("br(albatross):home1+multiSecondRouting"), "br(albatross):home1+multirouting2")
		self.assertEqual(tr("br(albatross):home1+multiRouting"), "br(albatross):home1+multirouting")
		self.assertEqual(tr("br(lilli):route"), "br(lilli):routing")
		self.assertEqual(tr("br(lilli):SLF"), "br(lilli):slf")
		self.assertEqual(tr("br(ecoBraille):F1"), "br(ecobraille):f1")
		# Otros controladores no se tocan (p. ej. «route» no es un alias fuera de la Lilli).
		self.assertEqual(tr("br(baum):route"), "br(baum):route")
		# Los gestos traducidos coinciden con los que produce la línea.
		g = base.buildGesture("albatross", {("routing2", 3)})
		self.assertEqual(g.identifiers[-1], tr("br(albatross):secondRouting"))
		g = base.buildGesture("lilli", {("routing", 3)})
		self.assertEqual(g.identifiers[-1], tr("br(lilli):route"))

	def test_gesture_maps(self) -> None:
		from tiresias.global_commands import commands

		for name in NEW_DRIVERS:
			cls = getDriverClass(name)
			known = set(cls.keyOrder) | set(cls.keyDescriptions) | {"routing", "multiRouting", "routing2", "multiRouting2"}
			for keys, target in cls.gestureMap.items():
				if target.startswith("kb:"):
					self.assertTrue(target[3:], target)
				else:
					self.assertTrue(hasattr(commands, "script_" + target), f"{name}: {target}")
				for k in keys.split("+"):
					self.assertIn(k, known, f"{name}: {keys}")

	def test_attribution_headers(self) -> None:
		for name in NEW_DRIVERS:
			mod = __import__(f"tiresias.braille.drivers.{name}", fromlist=["x"])
			doc = " ".join((mod.__doc__ or "").split())
			self.assertIn("NVDA", doc, name)
			self.assertIn("Licencia Pública General de GNU", doc, name)
			self.assertIn("Copyright", doc, name)


class ClaimedPortsTests(unittest.TestCase):
	def test_try_claimed_ports(self) -> None:
		class First(base.HardwareDriver):
			name = "first"
			usbSerialIds = frozenset({"VID_1111&PID_2222"})

		class Second(base.HardwareDriver):
			name = "second"
			usbSerialIds = frozenset({"VID_1111&PID_2222"})

		class Sharing(Second):
			name = "sharing"
			tryClaimedPorts = True

		devs = [DeviceInfo("serial", "COM5", usbId="VID_1111&PID_2222")]
		classes = {"first": First, "second": Second, "sharing": Sharing}
		cands = detect.findCandidates(devs, ["first", "second", "sharing"], classes=classes)
		self.assertEqual([(n, m.port) for n, m in cands], [("first", "COM5"), ("sharing", "COM5")])

	def test_seika_and_superbraille_share_cp210x(self) -> None:
		devs = [DeviceInfo("serial", "COM3", usbId="VID_10C4&PID_EA60")]
		classes = {"seika": getDriverClass("seika"), "superBrl": superBrl.SuperBrailleDriver}
		cands = detect.findCandidates(devs, ["seika", "superBrl"], allowGeneric=True, classes=classes)
		self.assertEqual([n for n, _m in cands], ["seika", "superBrl"])
		# Sin permitir los chips genéricos no se prueba ninguno.
		self.assertEqual(detect.findCandidates(devs, ["seika", "superBrl"], allowGeneric=False, classes=classes), [])


# =================================================================== EcoBraille
def ecoPacket(kind: int, a: int = 0, b: int = 0, c: int = 0, d: int = 0) -> bytes:
	return bytes((0x10, 0x02, kind, a, b, c, d, 0x10, 0x03))


def ecoKeys(value: int) -> bytes:
	return ecoPacket(0x88, *value.to_bytes(4, "big"))


def ecoConnect(model: int | None = 0x40, port: str = "auto"):
	def onOpen(t):
		if model is not None:
			t.feed(ecoPacket(0xF1, model))

	with mock.patch.object(base, "getConfiguredPort", return_value=port):
		return connectWith(ecoBraille.EcoBrailleDriver, _Line(onOpen))


class EcoBrailleTests(unittest.TestCase):
	def test_identify_40(self) -> None:
		drv, t = ecoConnect(0x40)
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(drv.deviceName, "EcoBraille 40")
		self.assertEqual(t.writes, [b"\x61\x10\x02\xf1\x57\x57\x57\x10\x03", b"\x10\x02\xbc\x00\x00\x00\x00\x00\x10\x03"])
		_m, baud, kwargs = t.opened[0]
		self.assertEqual(baud, 19200)
		self.assertEqual(kwargs.get("parity"), "N")
		self.assertEqual(kwargs.get("stopBits"), 1)

	def test_identify_20_and_80(self) -> None:
		self.assertEqual(ecoConnect(0x20)[0].numCells, 20)
		self.assertEqual(ecoConnect(0x80)[0].numCells, 80)

	def test_manual_port_without_identification_assumes_80(self) -> None:
		with mock.patch.object(ecoBraille, "INIT_TIMEOUT", 0.05):
			drv, t = ecoConnect(None, port="COM9")
		self.assertEqual(drv.numCells, 80)
		self.assertEqual(len(t.writes), 2)

	def test_auto_port_requires_identification(self) -> None:
		with mock.patch.object(ecoBraille, "INIT_TIMEOUT", 0.05):
			with self.assertRaises(base.DisplayNotFound):
				ecoConnect(None, port="auto")

	def test_dot_table_matches_nvda(self) -> None:
		self.assertEqual(len(NVDA_ECO_TABLE), 256)
		self.assertEqual(ecoBraille.OUTPUT_DOTS_MAP, NVDA_ECO_TABLE)

	def test_write_cells(self) -> None:
		drv, t = ecoConnect(0x20)
		drv.display([0x01, 0xFF, 0x40, 0x80])
		expected = b"\x10\x02\xbc" + bytes(5) + bytes((0x10, 0xFF, 0x80, 0x08)) + bytes(16) + b"\x10\x03"
		self.assertEqual(t.writes[-1], expected)
		self.assertEqual(len(t.writes[-1]), 3 + 5 + 20 + 2)

	def test_keys(self) -> None:
		drv, t = ecoConnect()
		for value, name in ((0x01, "f1"), (0x0400, "f0"), (0x0200, "a"), (0x4000, "s"), (0x100000, "t1"), (0x80000, "t2"), (0x40000, "t3"), (0x20000, "t4"), (0x10000, "t5")):
			t.feed(ecoKeys(value))
			self.assertEqual(gestureIds(drv), [f"br(ecobraille):{name}"])

	def test_key_combination(self) -> None:
		drv, t = ecoConnect()
		t.feed(ecoKeys(0x01 | 0x02))
		self.assertEqual(gestureIds(drv), ["br(ecobraille):f1+f2"])

	def test_routing_and_status_keys(self) -> None:
		drv, t = ecoConnect()
		t.feed(ecoKeys(0x85000000))
		self.assertEqual(drv.lastGestures[-1].routingIndex, 5)
		self.assertEqual(gestureIds(drv), ["br(ecobraille):routing"])
		for status in (0xD0, 0xD1, 0xD5, 0xD6):
			t.feed(ecoKeys(status << 24))
		t.feed(ecoKeys(0x80 + 45 << 24))  # Fuera de las 40 celdas.
		self.assertEqual(gestureIds(drv), [])

	def test_stream_resync(self) -> None:
		drv, t = ecoConnect()
		stream = b"\x00\x99" + ecoKeys(0x08) + b"\x10\x02\x88\x00" + ecoKeys(0x10)
		for b in stream:
			t.feed(bytes((b,)))
		self.assertEqual(gestureIds(drv), ["br(ecobraille):f4", "br(ecobraille):f5"])

	def test_terminate(self) -> None:
		drv, t = ecoConnect(0x20)
		drv.terminate()
		self.assertEqual(t.writes[-2], ecoBraille.cellsPacket([0] * 20))
		self.assertEqual(t.writes[-1], b"\x61\x10\x02\xf1\x57\x57\x57\x10\x03")
		self.assertTrue(t.closed)

	def test_auto_port_candidates_skip_bluetooth(self) -> None:
		devs = [DeviceInfo("serial", "COM1"), DeviceInfo("serial", "COM4", bluetooth=True, bluetoothName="X")]
		with mock.patch("tiresias.braille.drivers.ports.listComPorts", return_value=devs):
			self.assertEqual([m.port for m in ecoBraille.EcoBrailleDriver.candidateMatches("auto")], ["COM1"])
			self.assertEqual([m.port for m in ecoBraille.EcoBrailleDriver.candidateMatches("COM4")], ["COM4"])


# ==================================================================== Albatross
def albatrossLine(settings: int = 0x00, baud: int = 19200, packets: int = 30) -> _Line:
	"""Línea que envía paquetes de inicialización tras vaciar el búfer."""
	line = _Line()

	def purge():
		line.purges += 1
		if line.purges % albatross.RESET_COUNT == 0 and line.baudrate == baud:
			later(0.05, line.feed, bytes((0xFF, settings)) * packets)

	line.purge = purge
	return line


def albatrossConnect(settings: int = 0x00, **kw):
	with mock.patch.object(albatross, "RESET_SLEEP", 0), mock.patch.object(albatross.AlbatrossDriver, "_startKeepAlive"):
		return connectWith(albatross.AlbatrossDriver, albatrossLine(settings, **kw))


class AlbatrossTests(unittest.TestCase):
	def test_connect_46(self) -> None:
		drv, t = albatrossConnect(0x00)
		self.assertEqual(drv.numCells, 46)
		self.assertEqual(drv.deviceName, "Caiku Albatross 46")
		self.assertEqual(t.writes[0], b"\xfe\xfd")
		_m, baud, kwargs = t.opened[0]
		self.assertEqual(baud, 19200)
		self.assertEqual(kwargs.get("parity"), "N")

	def test_connect_80(self) -> None:
		drv, t = albatrossConnect(0x80)
		self.assertEqual(drv.numCells, 80)
		self.assertEqual(drv.model, "Albatross80")

	def test_fallback_9600(self) -> None:
		with mock.patch.object(albatross, "INIT_TIMEOUT", 0.3):
			drv, t = albatrossConnect(0x00, baud=9600)
		self.assertEqual(drv.numCells, 46)
		self.assertEqual([o[1] for o in t.opened], [19200, 9600])

	def test_no_init_packets(self) -> None:
		with mock.patch.object(albatross, "INIT_TIMEOUT", 0.05):
			with self.assertRaises(base.DisplayNotFound):
				albatrossConnect(0x00, baud=1)

	def test_single_packet_not_enough(self) -> None:
		# Un solo paquete (podrían ser datos leídos a otra velocidad) no basta.
		with mock.patch.object(albatross, "INIT_TIMEOUT", 0.3):
			with self.assertRaises(base.DisplayNotFound):
				albatrossConnect(0x00, packets=1)

	def test_too_many_status_cells(self) -> None:
		with mock.patch.object(base, "_announce") as announce, mock.patch.object(albatross, "INIT_TIMEOUT", 0.5):
			with self.assertRaises(base.DisplayNotFound):
				albatrossConnect(0xFF)
		announce.assert_called_once()
		self.assertIn("14", announce.call_args[0][0])

	def test_reverse_bits(self) -> None:
		self.assertEqual(albatross.reverseBits(0x01), 0x80)
		self.assertEqual(albatross.reverseBits(0x03), 0xC0)
		self.assertEqual(albatross.reverseBits(0xF0), 0x0F)

	def test_display_only_changed_cells(self) -> None:
		drv, t = albatrossConnect()
		drv.display([0x01, 0x00, 0x03])
		self.assertEqual(t.writes[-1], b"\xfb\x01\x80\x03\xc0\xfc")
		count = len(t.writes)
		drv.display([0x01, 0x00, 0x03])
		self.assertEqual(len(t.writes), count)
		drv.display([0x01, 0x02, 0x03])
		self.assertEqual(t.writes[-1], b"\xfb\x02\x40\xfc")

	def test_keys(self) -> None:
		drv, t = albatrossConnect(0x80)
		t.feed(bytes((97,)))  # left: no es tecla de control.
		t.feed(bytes((83, 83)))  # f1 sola.
		t.feed(bytes((83, 84, 85, 83)))  # f1+f2+f3
		t.feed(bytes((207,)))  # right
		self.assertEqual(
			gestureIds(drv),
			["br(albatross):left", "br(albatross):f1", "br(albatross):f1+f2+f3", "br(albatross):right"],
		)

	def test_split_control_packet(self) -> None:
		drv, t = albatrossConnect()
		t.feed(bytes((91,)))
		t.feed(bytes((92,)))
		self.assertEqual(gestureIds(drv), [])
		t.feed(bytes((91,)))
		self.assertEqual(gestureIds(drv), ["br(albatross):end1+home1"])

	def test_invalid_combination_ignored(self) -> None:
		drv, t = albatrossConnect()
		t.feed(bytes((83, 84, 85, 86, 87)))
		self.assertEqual(gestureIds(drv), [])
		t.feed(bytes((97,)))
		self.assertEqual(gestureIds(drv), ["br(albatross):left"])

	def test_routing_rows(self) -> None:
		drv, t = albatrossConnect(0x80)
		t.feed(bytes((2,)))
		t.feed(bytes((150,)))
		t.feed(bytes((43,)))
		t.feed(bytes((191,)))
		g = drv.lastGestures
		self.assertEqual([x.routingIndex for x in g], [0, 79, 0, 79])
		self.assertEqual(gestureIds(drv), ["br(albatross):routing", "br(albatross):routing", "br(albatross):routing2", "br(albatross):routing2"])
		t.feed(bytes((91, 3, 4, 91)))
		self.assertEqual(drv.lastGestures[-1].routingIndexes, [1, 2])
		self.assertEqual(gestureIds(drv), ["br(albatross):home1+multirouting"])

	def test_routing_beyond_46_cells_ignored(self) -> None:
		drv, t = albatrossConnect(0x00)
		t.feed(bytes((111 + 10,)))  # índice 50
		self.assertEqual(gestureIds(drv), [])

	def test_key_layouts(self) -> None:
		# Lados intercambiados (bit 6 del byte de ajustes).
		drv, t = albatrossConnect(0x40)
		t.feed(bytes((83, 83)))
		t.feed(bytes((193, 193)))
		t.feed(bytes((97,)))
		self.assertEqual(gestureIds(drv), ["br(albatross):f9", "br(albatross):f1", "br(albatross):left"])
		# Todas como las del lado derecho (bit 4).
		drv, t = albatrossConnect(0x10)
		t.feed(bytes((83, 83)))
		t.feed(bytes((193, 193)))
		self.assertEqual(gestureIds(drv), ["br(albatross):f9", "br(albatross):f9"])
		# Todas como las del lado izquierdo (bits 4 y 6).
		drv, t = albatrossConnect(0x50)
		t.feed(bytes((193, 193)))
		self.assertEqual(gestureIds(drv), ["br(albatross):f1"])

	def test_reinit_during_session_redraws(self) -> None:
		drv, t = albatrossConnect()
		drv.display([0x01, 0x02])
		t.writes.clear()
		t.feed(b"\xff\x00\xff\x00")
		self.assertEqual(t.writes[0], b"\xfe\xfd")
		self.assertEqual(t.writes[-1], b"\xfb\x01\x80\x02\x40\xfc")
		# Un byte de ajustes con el valor de una tecla no se toma por tecla.
		t.feed(b"\xff\x53")
		self.assertEqual(gestureIds(drv), [])

	def test_status_cells_during_session(self) -> None:
		drv, t = albatrossConnect()
		with mock.patch.object(base, "_announce") as announce:
			t.feed(b"\xff\xff")
		announce.assert_called_once()
		self.assertEqual(t.writes[-1], b"\xfe\xfd")

	def test_keep_alive_tick(self) -> None:
		drv, t = albatrossConnect()
		drv._writeTime = time.monotonic()
		drv._keepAliveTick()
		self.assertEqual(t.writes, [b"\xfe\xfd"])
		drv._writeTime = time.monotonic() - 2
		drv._keepAliveTick()
		self.assertEqual(t.writes[-1], b"\xfb\xfc")

	def test_keep_alive_thread_stops(self) -> None:
		with mock.patch.object(albatross, "RESET_SLEEP", 0), mock.patch.object(albatross, "KC_INTERVAL", 0.05):
			drv, t = connectWith(albatross.AlbatrossDriver, albatrossLine())
			thread = drv._kcThread
			self.assertIsNotNone(thread)
			deadline = time.monotonic() + 2
			while b"\xfb\xfc" not in t.writes and time.monotonic() < deadline:
				time.sleep(0.02)
			self.assertIn(b"\xfb\xfc", t.writes)
			drv.terminate()
		thread.join(1)
		self.assertFalse(thread.is_alive())
		self.assertTrue(t.closed)

	def test_terminate_blanks(self) -> None:
		drv, t = albatrossConnect()
		drv.display([0x01])
		drv.terminate()
		self.assertEqual(t.writes[-1], b"\xfb\x01\x00\xfc")
		self.assertTrue(t.closed)

	def test_detection_by_bus_description(self) -> None:
		usb = DeviceInfo("usb", r"\\?\usb#1", usbId="VID_0403&PID_6001", extra={"busReportedDeviceDescription": "Albatross Braille Display", "instanceId": r"USB\VID_0403&PID_6001\A1B2C3"})
		com = DeviceInfo("serial", "COM5", usbId="VID_0403&PID_6001", extra={"instanceId": r"FTDIBUS\VID_0403+PID_6001+A1B2C3A\0000"})
		other = DeviceInfo("serial", "COM6", usbId="VID_0403&PID_6001", extra={"instanceId": r"FTDIBUS\VID_0403+PID_6001+ZZZZA\0000"})
		cls = albatross.AlbatrossDriver
		self.assertEqual([m.port for m in cls.getMatches([usb, com, other], allowGeneric=False)], ["COM5"])
		# Sin la descripción del bus no se reconoce.
		self.assertEqual(cls.getMatches([com, other]), [])
		# Detección completa: aunque HIMS reclame el chip FTDI (genérico), se prueba también.
		classes = {"hims": getDriverClass("hims"), "albatross": cls}
		cands = detect.findCandidates([usb, com], ["hims", "albatross"], allowGeneric=True, classes=classes)
		self.assertEqual([(n, m.port) for n, m in cands], [("hims", "COM5"), ("albatross", "COM5")])

	def test_manual_selection_tries_ftdi_ports(self) -> None:
		com = DeviceInfo("serial", "COM5", usbId="VID_0403&PID_6001")
		with mock.patch("tiresias.braille.drivers.ports.listAll", return_value=[com]):
			self.assertEqual([m.port for m in albatross.AlbatrossDriver.candidateMatches("usb")], ["COM5"])


# ======================================================================== Lilli
class _FakeLilliDll:
	def __init__(self, keys=(), init=1):
		self.keys = list(keys)
		self.init = init
		self.written: list[bytes] = []
		self.closed = 0

	def Init408USB(self):
		return self.init

	def ReadBuf(self):
		return self.keys.pop(0) if self.keys else 0

	def WriteBuf(self, data):
		self.written.append(bytes(data))

	def Close408USB(self):
		self.closed += 1


class LilliTests(unittest.TestCase):
	def test_not_available_without_dll(self) -> None:
		with mock.patch.object(lilli, "findDll", return_value=None):
			self.assertFalse(lilli.LilliDriver.check())
			self.assertEqual(lilli.LilliDriver.candidateMatches("auto"), [])
		with mock.patch.object(lilli, "findDll", return_value=r"C:\x\lilli.dll"):
			self.assertTrue(lilli.LilliDriver.check())
			self.assertEqual([m.type for m in lilli.LilliDriver.candidateMatches("auto")], ["dll"])

	def test_dll_architecture(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:

			def pe(name, machine):
				data = bytearray(512)
				data[:2] = b"MZ"
				struct.pack_into("<I", data, 0x3C, 0x80)
				data[0x80:0x84] = b"PE\x00\x00"
				struct.pack_into("<H", data, 0x84, machine)
				path = os.path.join(tmp, name)
				with open(path, "wb") as f:
					f.write(data)
				return path

			x86 = pe("x86.dll", 0x014C)
			x64 = pe("x64.dll", 0x8664)
			self.assertEqual(lilli.dllMachine(x86), 0x014C)
			self.assertEqual(lilli.dllMachine(x64), 0x8664)
			self.assertEqual(lilli.dllMachine(os.path.join(tmp, "no.dll")), 0)
			with mock.patch.object(lilli, "_candidatePaths", return_value=[x86, x64]), mock.patch.object(lilli, "_PROCESS_MACHINE", 0x8664):
				self.assertEqual(lilli.findDll(), x64)
			with mock.patch.object(lilli, "_candidatePaths", return_value=[x86]), mock.patch.object(lilli, "_PROCESS_MACHINE", 0x8664):
				self.assertIsNone(lilli.findDll())

	def test_open_fails_without_display(self) -> None:
		drv = lilli.LilliDriver.__new__(lilli.LilliDriver)
		with mock.patch.object(lilli, "loadDll", return_value=None):
			with self.assertRaises(base.DisplayNotFound):
				lilli.LilliDriver._open(drv, DeviceMatch("dll", "", "lilli"))
		with mock.patch.object(lilli, "loadDll", return_value=_FakeLilliDll(init=0)):
			with self.assertRaises(base.DisplayNotFound):
				lilli.LilliDriver._open(drv, DeviceMatch("dll", "", "lilli"))

	def _connect(self):
		return connectSimulated(lilli.LilliDriver, matchType="dll", port="lilli")

	def test_connect_and_cells(self) -> None:
		drv, t = self._connect()
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(drv.deviceName, "MDV Lilli")
		drv.display([0x01, 0x10, 0xFF])
		self.assertEqual(t.writes[-1], bytes((0x08, 0x40, 0xFF)) + bytes(37))

	def test_cell_conversion(self) -> None:
		self.assertEqual([lilli.convertLilliCell(1 << b) for b in range(8)], [0x08, 0x04, 0x02, 0x80, 0x40, 0x20, 0x01, 0x10])

	def test_keys(self) -> None:
		drv, t = self._connect()
		for code, name in ((11, "lf"), (12, "up"), (13, "rg"), (14, "dn"), (1, "f1"), (27, "slf"), (64, "sfup")):
			t.feed(code.to_bytes(2, "little"))
			self.assertEqual(gestureIds(drv), [f"br(lilli):{name}"])
		t.feed((0x101 + 7).to_bytes(2, "little"))
		self.assertEqual(drv.lastGestures[-1].routingIndex, 7)
		self.assertEqual(gestureIds(drv), ["br(lilli):routing"])
		t.feed((15).to_bytes(2, "little") + (0x200).to_bytes(2, "little"))
		self.assertEqual(gestureIds(drv), [])

	def test_transport_with_fake_dll(self) -> None:
		dll = _FakeLilliDll(keys=[11, 0x105])
		received = []
		with mock.patch.object(lilli, "KEY_CHECK_INTERVAL", 0.01):
			tr = lilli.LilliTransport(dll, received.append)
			deadline = time.monotonic() + 2
			while len(received) < 2 and time.monotonic() < deadline:
				time.sleep(0.01)
			tr.write(b"\x01\x02")
			tr.close()
		self.assertEqual(received, [(11).to_bytes(2, "little"), (0x105).to_bytes(2, "little")])
		self.assertEqual(dll.written, [b"\x01\x02"])
		self.assertEqual(dll.closed, 1)
		self.assertFalse(tr._thread.is_alive())
		with self.assertRaises(hwio.IoError):
			tr.write(b"\x00")


# ========================================================================= hedo
class HedoProfiLineTests(unittest.TestCase):
	def _connect(self, ack=True):
		blank = b"\x01" + bytes(160)
		return connectSimulated(hedoProfiLine.HedoProfiLineDriver, lambda d: b"\x7e" if ack and d == blank else None, usbId="VID_0403&PID_DE59")

	def test_connect(self) -> None:
		drv, t = self._connect()
		self.assertEqual(drv.numCells, 80)
		self.assertEqual(t.writes, [b"\x01" + bytes(160)] * 2)
		_m, baud, kwargs = t.opened[0]
		self.assertEqual((baud, kwargs.get("parity"), kwargs.get("stopBits")), (19200, "O", 1))

	def test_no_ack(self) -> None:
		with mock.patch.object(hedoProfiLine, "ACK_TIMEOUT", 0.05):
			with self.assertRaises(base.DisplayNotFound):
				self._connect(ack=False)

	def test_write_cells(self) -> None:
		drv, t = self._connect()
		drv.display([0x01, 0xFF])
		self.assertEqual(t.writes[-1], b"\x01" + bytes(4) + b"\x01\xff" + bytes(78))
		self.assertEqual(len(t.writes[-1]), 85)

	def test_keys(self) -> None:
		drv, t = self._connect()
		t.feed(b"\x04\x84")
		t.feed(b"\x07\x13\x87\x93")
		t.feed(b"\x7e")
		t.feed(b"\x25\xa5")
		self.assertEqual(gestureIds(drv), ["br(hedoprofiline):k1", "br(hedoprofiline):b2+b5", "br(hedoprofiline):routing"])

	def test_routing_index(self) -> None:
		drv, t = self._connect()
		t.feed(b"\x6f")
		self.assertEqual(drv.lastGestures[-1].routingIndex, 79)

	def test_detection(self) -> None:
		devs = [DeviceInfo("serial", "COM3", usbId="VID_0403&PID_DE59"), DeviceInfo("serial", "COM4", usbId="VID_0403&PID_DE58")]
		self.assertEqual([m.port for m in hedoProfiLine.HedoProfiLineDriver.getMatches(devs, allowGeneric=False)], ["COM3", "COM4"])
		classes = {"hedoMobilLine": hedoMobilLine.HedoMobilLineDriver, "hedoProfiLine": hedoProfiLine.HedoProfiLineDriver}
		cands = detect.findCandidates(devs, ["hedoMobilLine", "hedoProfiLine"], classes=classes)
		self.assertEqual(sorted((n, m.port) for n, m in cands), [("hedoMobilLine", "COM4"), ("hedoProfiLine", "COM3")])


class HedoMobilLineTests(unittest.TestCase):
	def _connect(self):
		blank = b"\x01" + bytes(42)
		return connectSimulated(hedoMobilLine.HedoMobilLineDriver, lambda d: b"\x30" if d == blank else None, usbId="VID_0403&PID_DE58")

	def test_connect(self) -> None:
		drv, t = self._connect()
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(t.writes, [b"\x01" + bytes(42)] * 2)
		_m, baud, kwargs = t.opened[0]
		self.assertEqual((baud, kwargs.get("parity")), (9600, "O"))

	def test_no_ack(self) -> None:
		with mock.patch.object(hedoMobilLine, "ACK_TIMEOUT", 0.05):
			with self.assertRaises(base.DisplayNotFound):
				connectSimulated(hedoMobilLine.HedoMobilLineDriver, lambda d: None)

	def test_write_cells(self) -> None:
		drv, t = self._connect()
		drv.display([0x3F])
		self.assertEqual(t.writes[-1], b"\x01\x00\x00\x3f" + bytes(39))

	def test_keys(self) -> None:
		drv, t = self._connect()
		t.feed(b"\x01\x10\x20")  # B1 pulsada
		t.feed(b"\x00\x10\x20")  # suelta
		t.feed(b"\x02\x10\x20")  # B2
		t.feed(b"\x02\x10\x21")  # B2 + K1
		t.feed(b"\x00\x10\x21")  # se suelta B2
		t.feed(b"\x00\x10\x20")
		t.feed(b"\x45")
		self.assertEqual(gestureIds(drv), ["br(hedomobilline):b1", "br(hedomobilline):b2+k1", "br(hedomobilline):routing"])
		t.feed(b"\x30")  # confirmación: no es tecla
		self.assertEqual(gestureIds(drv), [])


# ================================================================= SuperBraille
REPLY_SUPER = b"\x00\x05\x28\x00v3.2    "


class SuperBrailleTests(unittest.TestCase):
	def _connect(self, reply=REPLY_SUPER, chunks=False):
		def responder(d):
			if d == b"\xff\xff\x0a":
				return [bytes((b,)) for b in reply] if chunks else reply
			return None

		return connectSimulated(superBrl.SuperBrailleDriver, responder, usbId="VID_10C4&PID_EA60")

	def test_connect(self) -> None:
		drv, t = self._connect()
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(drv.version, "v3.2")
		self.assertEqual(t.writes, [b"\xff\xff\x0a"])
		_m, baud, kwargs = t.opened[0]
		self.assertEqual((baud, kwargs.get("parity")), (9600, "N"))

	def test_reply_in_chunks(self) -> None:
		drv, t = self._connect(chunks=True)
		self.assertEqual(drv.numCells, 40)

	def test_no_reply(self) -> None:
		with mock.patch.object(superBrl, "TIMEOUT", 0.05):
			with self.assertRaises(base.DisplayNotFound):
				self._connect(reply=b"")

	def test_write_cells(self) -> None:
		drv, t = self._connect(reply=b"\x00\x05\x02\x00ver12345")
		drv.display([0x01, 0x80])
		self.assertEqual(t.writes[-1], b"\xff\xff\x04\x00\x99\x00\x50\x00\x00\x01\x00\x80")

	def test_terminate_waits_and_closes(self) -> None:
		drv, t = self._connect()
		with mock.patch.object(superBrl.time, "sleep") as sleep:
			drv.terminate()
		sleep.assert_called_once_with(superBrl.CLOSE_DELAY)
		self.assertTrue(t.closed)

	def test_numpad_scripts(self) -> None:
		gestures = superBrl.SuperBrailleDriver._classGestures
		self.assertEqual(gestures.get(normalizeGestureId("kb:numpadMinus")), "scrollBack")
		self.assertEqual(gestures.get(normalizeGestureId("kb:numpadPlus")), "scrollForward")
		drv, t = self._connect()
		from tiresias.global_commands import commands

		with mock.patch.object(type(commands), "script_braille_scrollBack") as back, mock.patch.object(type(commands), "script_braille_scrollForward") as fwd:
			drv.script_scrollBack(None)
			drv.script_scrollForward(None)
		back.assert_called_once()
		fwd.assert_called_once()


# ================================================================ Nattiq nBraille
class NattiqTests(unittest.TestCase):
	def _connect(self, cells=b"40"):
		def responder(d):
			if d == b"0":
				return b"0" + cells
			return None

		with mock.patch.object(nattiqbraille, "RESET_TIMEOUT", 0.05), mock.patch.object(nattiqbraille, "INIT_TIMEOUT", 0.2):
			return connectSimulated(nattiqbraille.NattiqBrailleDriver, responder, usbId="VID_2341&PID_8036")

	def test_connect(self) -> None:
		drv, t = self._connect()
		self.assertEqual(drv.numCells, 40)
		self.assertEqual(t.writes, [b"reset", b"0"])
		_m, baud, kwargs = t.opened[0]
		self.assertEqual((baud, kwargs.get("parity")), (10_000_000, "N"))

	def test_no_answer(self) -> None:
		with self.assertRaises(base.DisplayNotFound):
			self._connect(cells=b"xx")

	def test_write_cells(self) -> None:
		drv, t = self._connect(cells=b"05")
		drv.display([0, 1, 255])
		self.assertEqual(t.writes[-1], b"0-1-255-0-0")

	def test_keys(self) -> None:
		drv, t = self._connect()
		t.feed(b"2345")
		t.feed(b"1")
		t.feed(b"0")
		t.feed(b"7")
		self.assertEqual(
			gestureIds(drv),
			["br(nattiqbraille):tback", "br(nattiqbraille):tadvance", "br(nattiqbraille):tnext", "br(nattiqbraille):tprevious", "br(nattiqbraille):routing"],
		)
		t.feed(b"\r\n?")
		self.assertEqual(gestureIds(drv), [])

	def test_routing_index(self) -> None:
		drv, t = self._connect()
		t.feed(b"139")
		self.assertEqual(drv.lastGestures[-1].routingIndex, 39)
		t.feed(b"145")  # fuera de la línea
		self.assertEqual(len(drv.lastGestures), 1)

	def test_terminate_resets(self) -> None:
		drv, t = self._connect()
		drv.terminate()
		self.assertEqual(t.writes[-1], b"reset")
		self.assertTrue(t.closed)

	def test_generic_usb_id(self) -> None:
		devs = [DeviceInfo("serial", "COM7", usbId="VID_2341&PID_8036")]
		self.assertEqual(nattiqbraille.NattiqBrailleDriver.getMatches(devs, allowGeneric=False), [])
		self.assertEqual(len(nattiqbraille.NattiqBrailleDriver.getMatches(devs, allowGeneric=True)), 1)


# ====================================================================== Dot Pad
def board(features=0xC0 | 0x20 | 0x04 | 0x02, textRows=1, textCols=20, graphicRows=10, graphicCols=30) -> bytes:
	return bytes((features, 8, 0, 4, textRows, textCols, 0, 0, graphicRows, graphicCols, 0, 0))


class _DotPad:
	"""Dot Pad simulado: contesta a las peticiones con paquetes del protocolo."""

	def __init__(self, info=None, displayCode=0, name=b"DotPad320A"):
		self.info = board() if info is None else info
		self.displayCode = displayCode
		self.name = name
		self.lines: list[tuple[int, bytes, int]] = []

	def __call__(self, data: bytes):
		body = data[4:]
		dest, cmd, seq, payload = body[0], struct.unpack(">H", body[1:3])[0], body[3], body[4:-1]
		if cmd == dotPad.REQ_DEVICE_NAME and self.name is not None:
			return dotPad.buildPacket(dotPad.RSP_DEVICE_NAME, self.name)
		if cmd == dotPad.REQ_BOARD_INFORMATION:
			return dotPad.buildPacket(dotPad.RSP_BOARD_INFORMATION, self.info)
		if cmd == dotPad.REQ_DISPLAY_LINE:
			self.lines.append((dest, bytes(payload), seq))
			if self.displayCode is None:
				return None
			return dotPad.buildPacket(dotPad.RSP_DISPLAY_LINE, bytes((self.displayCode,)), dest)
		return None


def dotPadConnect(device=None, destination="text"):
	device = device or _DotPad()
	with mock.patch.object(dotPad.DotPadDriver, "asyncDisplay", False), mock.patch.object(dotPad.DotPadDriver, "getSetting", return_value=destination):
		drv, t = connectSimulated(dotPad.DotPadDriver, device, usbId="VID_0403&PID_6010")
	return drv, t, device


def keysPacket(group: int, data: bytes) -> bytes:
	return dotPad.buildPacket(0x0300 | group, data)


class DotPadTests(unittest.TestCase):
	def test_packet_format(self) -> None:
		self.assertEqual(dotPad.buildPacket(dotPad.REQ_DEVICE_NAME), b"\xaa\x55\x00\x05\x00\x01\x00\x00\xa4")

	def test_connect_text(self) -> None:
		drv, t, dev = dotPadConnect()
		self.assertEqual(drv.numCells, 20)
		self.assertEqual(drv.model, "DotPad320A")
		self.assertEqual(t.writes[0], b"\xaa\x55\x00\x05\x00\x01\x00\x00\xa4")
		self.assertEqual(t.writes[1], dotPad.buildPacket(dotPad.REQ_BOARD_INFORMATION))
		_m, baud, kwargs = t.opened[0]
		self.assertEqual((baud, kwargs.get("parity")), (115200, "N"))

	def test_no_answer(self) -> None:
		with mock.patch.object(dotPad, "RESPONSE_TIMEOUT", 0.05):
			with self.assertRaises(base.DisplayNotFound):
				dotPadConnect(_DotPad(name=None))

	def test_no_display_raises(self) -> None:
		with self.assertRaises(base.DisplayNotFound):
			dotPadConnect(_DotPad(info=board(features=0x20)))

	def test_display_text_line(self) -> None:
		drv, t, dev = dotPadConnect()
		drv.display([0x01, 0x03])
		cells = b"\x00" + bytes((0x01, 0x03)) + bytes(18)
		self.assertEqual(dev.lines, [(0, cells, 0x80)])
		self.assertEqual(t.writes[-1], dotPad.buildPacket(dotPad.REQ_DISPLAY_LINE, cells, 0, 0x80))
		self.assertEqual(t.writes[-1][:4], b"\xaa\x55\x00\x1a")
		# Sin cambios no se reenvía.
		count = len(t.writes)
		drv.display([0x01, 0x03])
		self.assertEqual(len(t.writes), count)

	def test_rejected_line_is_resent(self) -> None:
		drv, t, dev = dotPadConnect(_DotPad(displayCode=1))
		drv.display([0x07])
		drv.display([0x07])
		self.assertEqual(len(dev.lines), 2)

	def test_no_ack_does_not_block_other_updates(self) -> None:
		with mock.patch.object(dotPad, "RESPONSE_TIMEOUT", 0.05):
			drv, t, dev = dotPadConnect()
			dev.displayCode = None
			drv.display([0x07])
			drv.display([0x07])
		self.assertEqual(len(dev.lines), 2)

	def test_graphic_destination(self) -> None:
		drv, t, dev = dotPadConnect(destination="graphic")
		self.assertEqual(drv.numCells, 20)  # 30 celdas x 2 puntos / 3
		drv.display([0x01, 0x08])
		self.assertEqual(len(dev.lines), 10)
		dest, data, seq = dev.lines[0]
		self.assertEqual((dest, seq), (1, 0))  # la fila de texto es la 0
		self.assertEqual(data, b"\x00" + bytes((0x01, 0x00, 0x01)) + bytes(27))
		self.assertTrue(all(d == b"\x00" + bytes(30) for _dest, d, _s in dev.lines[1:]))

	def test_graphic_only_device(self) -> None:
		drv, t, dev = dotPadConnect(_DotPad(info=board(features=0x80, textRows=0, textCols=0)))
		self.assertEqual(drv.numCells, 20)
		drv.display([0xFF])
		self.assertEqual(dev.lines[0][0], 0)
		# Punto 1..8 en el orden de columnas del Dot Pad: la celda 0 recibe 0xFF.
		self.assertEqual(dev.lines[0][1][1], 0xFF)

	def test_graphic_buffer_bits(self) -> None:
		g = dotPad.GraphicBuffer(3, 1)
		g.drawBrailleCells(0, 0, [0x08 | 0x80])  # puntos 4 y 8: columna derecha
		self.assertEqual(g.row(0), bytes((0x10 | 0x80, 0, 0)))

	def test_keys_braille_input(self) -> None:
		drv, t, dev = dotPadConnect()
		t.feed(keysPacket(0x12, b"\x10\x80\x00"))  # punto 1 + espacio
		t.feed(keysPacket(0x12, b"\x00\x00\x00"))
		g = drv.lastGestures[-1]
		self.assertEqual(gestureIds(drv), ["br(dotpad):dot1+space"])
		self.assertEqual((g.dots, g.space), (1, True))

	def test_keys_function_and_pan(self) -> None:
		drv, t, dev = dotPadConnect()
		t.feed(keysPacket(0x32, b"\x80"))
		t.feed(keysPacket(0x32, b"\x00"))
		t.feed(keysPacket(0x12, b"\x00\x04\x00"))  # panLeft (tecla 13)
		t.feed(keysPacket(0x12, b"\x00\x00\x00"))
		t.feed(keysPacket(0x12, b"\x00\x00\x40"))  # navUp (tecla 17)
		t.feed(keysPacket(0x12, b"\x00\x00\x00"))
		self.assertEqual(gestureIds(drv), ["br(dotpad):f1", "br(dotpad):panleft", "br(dotpad):navup"])

	def test_keys_across_groups(self) -> None:
		drv, t, dev = dotPadConnect()
		t.feed(keysPacket(0x32, b"\x40"))  # f2
		t.feed(keysPacket(0x12, b"\x00\x02\x00"))  # panRight (tecla 14)
		t.feed(keysPacket(0x12, b"\x00\x00\x00"))
		t.feed(keysPacket(0x32, b"\x00"))
		self.assertEqual(gestureIds(drv), ["br(dotpad):f2+panright"])

	def test_routing_group_not_interpreted(self) -> None:
		drv, t, dev = dotPadConnect()
		t.feed(keysPacket(0x22, b"\x80"))
		t.feed(keysPacket(0x22, b"\x00"))
		self.assertEqual(gestureIds(drv), [])

	def test_bad_checksum_and_resync(self) -> None:
		drv, t, dev = dotPadConnect()
		bad = bytearray(keysPacket(0x32, b"\x80"))
		bad[-1] ^= 0xFF
		t.feed(b"\x00\xaa\x13" + bytes(bad))
		self.assertEqual(gestureIds(drv), [])
		good = keysPacket(0x32, b"\x80") + keysPacket(0x32, b"\x00")
		for b in good:
			t.feed(bytes((b,)))
		self.assertEqual(gestureIds(drv), ["br(dotpad):f1"])

	def test_async_writer(self) -> None:
		device = _DotPad()
		with mock.patch.object(dotPad.DotPadDriver, "getSetting", return_value="text"):
			drv, t = connectSimulated(dotPad.DotPadDriver, device)
		writer = drv._writer
		self.assertIsNotNone(writer)
		drv.display([0x05])
		deadline = time.monotonic() + 2
		while not device.lines and time.monotonic() < deadline:
			time.sleep(0.01)
		self.assertEqual(device.lines[0][1][:2], b"\x00\x05")
		drv.terminate()
		self.assertFalse(writer.is_alive())
		# Al cerrar se borra la línea (de forma síncrona) y se cierra el puerto.
		self.assertEqual(device.lines[-1][1], b"\x00" + bytes(20))
		self.assertTrue(t.closed)

	def test_switch_destination(self) -> None:
		drv, t, dev = dotPadConnect()
		drv.display([0x01])
		with mock.patch.object(dotPad.DotPadDriver, "getSetting", return_value="graphic"), mock.patch.object(base, "_showInitial") as show:
			drv.applySettings()
		show.assert_called_once()
		self.assertEqual(drv._destination, "graphic")
		# Se ha borrado la línea de texto.
		self.assertIn((0, b"\x00" + bytes(20), 0x80), dev.lines)

	def test_generic_usb_id(self) -> None:
		devs = [DeviceInfo("serial", "COM8", usbId="VID_0403&PID_6010")]
		self.assertEqual(dotPad.DotPadDriver.getMatches(devs, allowGeneric=False), [])
		self.assertEqual(len(dotPad.DotPadDriver.getMatches(devs, allowGeneric=True)), 1)


if __name__ == "__main__":
	unittest.main()
