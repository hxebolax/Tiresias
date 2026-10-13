"""Pruebas del controlador de las líneas Papenmeier BRAILLEX (protocolos nuevo
y antiguo) con líneas simuladas."""

from __future__ import annotations

import re
import unittest
from unittest import mock

import braille_sim  # noqa: F401
from braille_sim import connectSimulated, gestureIds

from tiresias.braille.drivers import base
from tiresias.braille.drivers import papenmeier as pm
from tiresias.braille.drivers.papenmeier import PapenmeierDriver
from tiresias.braille.drivers.ports import DeviceInfo

NEW_REQUEST = b"\x02B\x50\x50\x03"
OLD_REQUEST = b"\x02S\x00\x00\x00\x00\x03"


# ---------------------------------------------------------------- tramas de la línea
def newIdentity(code: int) -> bytes:
	return bytes((0x02, 0x42, 0x50, 0x50, 0x30 | (code >> 4), 0x30 | (code & 0x0F), 0x30, 0x31, 0x30, 0x03))


def elKeys(numbers, pairs: int = 16) -> bytes:
	"""Trama 'K' de la familia EL: pares (teclas n+4..n+7, teclas n..n+3), n = 4 + 8·par."""
	data = bytearray()
	for p in range(pairs):
		first = 4 + 8 * p
		high = low = 0
		for n in numbers:
			if first <= n < first + 4:
				low |= 1 << (n - first)
			elif first + 4 <= n < first + 8:
				high |= 1 << (n - first - 4)
		data += bytes((0x30 | high, 0x30 | low))
	return bytes((0x02, 0x4B, 0x50 | (pairs >> 4), 0x50 | (pairs & 0x0F))) + bytes(data) + b"\x03"


def trioKeys(numbers, size: int = 32) -> bytes:
	"""Trama 'K' del Trio: un byte por cada 4 teclas, la primera en el bit 3."""
	data = bytearray()
	for i in range(size):
		value = 0
		for n in numbers:
			if 4 * i <= n < 4 * i + 4:
				value |= 1 << (3 - (n - 4 * i))
		data.append(0x30 | value)
	length = size // 2
	return bytes((0x02, 0x4B, 0x50 | (length >> 4), 0x50 | (length & 0x0F))) + bytes(data) + b"\x03"


def trioKeyboard(thumbs: int, dots: int, scancode: bool = False) -> bytes:
	first = 0x38 if scancode else 0x30
	return bytes((0x02, 0x4C, 0x50, 0x52, first, 0x30 | thumbs, 0x30 | (dots >> 4), 0x30 | (dots & 0x0F), 0x03))


def oldIdentity(model: int) -> bytes:
	return bytes((0x02, 0x49, model, 0x01, 0x05, 0x00, 0x00, 0x00, 0x00, 0x03))


def oldKey(index: int, pressed: bool, mods: int = 0) -> bytes:
	code = 0x300 + 3 * index
	return bytes((0x02, 0x4B, code >> 8, code & 0xFF, 0x00, 0x00, 1 if pressed else 0, 0x00, mods, 0x03))


class _Responder:
	"""Contesta a la identificación a partir de la petición número ``fromRequest``."""

	def __init__(self, request: bytes, reply: bytes, fromRequest: int = 1) -> None:
		self.request = request
		self.reply = reply
		self.fromRequest = fromRequest
		self.count = 0

	def __call__(self, data: bytes):
		if data == self.request:
			self.count += 1
			if self.count >= self.fromRequest:
				return self.reply
		return None


class _Base(unittest.TestCase):
	def setUp(self) -> None:
		patcher = mock.patch.object(PapenmeierDriver, "identifyTimeout", 0.05)
		patcher.start()
		self.addCleanup(patcher.stop)

	def connectNew(self, code: int, **kwargs):
		kwargs.setdefault("usbId", "VID_0403&PID_F208")
		return connectSimulated(PapenmeierDriver, responder=_Responder(NEW_REQUEST, newIdentity(code)), **kwargs)

	def connectOld(self, model: int, fromRequest: int = 1, **kwargs):
		return connectSimulated(PapenmeierDriver, responder=_Responder(OLD_REQUEST, oldIdentity(model), fromRequest), **kwargs)


# ======================================================================= conexión
class ConnectionTests(_Base):
	def test_new_el40s_usb(self) -> None:
		drv, t = self.connectNew(0x55)
		self.assertEqual((drv.numCells, drv.model, drv.deviceName), (40, "EL40s", "BRAILLEX EL 40s"))
		self.assertEqual(t.writes[0], NEW_REQUEST)
		self.assertEqual([o[1] for o in t.opened], [57600])
		self.assertEqual(drv._protocol, "new")

	def test_new_models(self) -> None:
		for code, model, cells in ((0x5B, "EL2D80s", 80), (0x61, "EL80c", 80), (0x5E, "EL20c", 20), (0x63, "LivePlus", 40), (0x64, "Live20", 20)):
			drv, _t = self.connectNew(code)
			self.assertEqual((drv.model, drv.numCells), (model, cells))

	def test_trio_answers_at_115200(self) -> None:
		# A 57600 no contesta; a 115200 se envía la petición dos veces.
		responder = _Responder(NEW_REQUEST, newIdentity(0x59), fromRequest=2)
		drv, t = connectSimulated(PapenmeierDriver, responder=responder, usbId="VID_0403&PID_F208")
		self.assertEqual((drv.model, drv.numCells, drv.deviceName), ("Trio", 40, "BRAILLEX Trio"))
		self.assertEqual([o[1] for o in t.opened], [57600, 115200])
		self.assertEqual(t.writes[:3], [NEW_REQUEST, NEW_REQUEST, NEW_REQUEST])

	def test_bluetooth_live_only_new_protocol(self) -> None:
		drv, t = self.connectNew(0x62, usbId="", name="braillex live 0815", bluetooth=True, port="COM12")
		self.assertEqual(drv.model, "Live")
		self.assertTrue(drv.displayName.endswith("(Bluetooth)"))
		with self.assertRaises(base.DisplayNotFound):
			connectSimulated(PapenmeierDriver, responder=_Responder(OLD_REQUEST, oldIdentity(64)), name="braillex trio 1", bluetooth=True)

	def test_old_protocol_on_com_port(self) -> None:
		drv, t = self.connectOld(64)
		self.assertEqual((drv.numCells, drv.model, drv.deviceName), (40, "EL2D40", "BRAILLEX EL 2D-40"))
		self.assertEqual(drv._protocol, "old")
		self.assertFalse(drv._eab)
		self.assertEqual([o[1] for o in t.opened], [19200])
		# Petición de identificación y modo «puntos» en las 40 celdas de texto (tras 13 de estado).
		self.assertEqual(t.writes[0], OLD_REQUEST)
		self.assertEqual(t.writes[1], b"\x02S\x02\x0d\x00\x2f" + b"\x01" * 40 + b"\x03")

	def test_old_protocol_eab_at_38400(self) -> None:
		drv, t = self.connectOld(66, fromRequest=2)
		self.assertEqual((drv.model, drv.numCells), ("EL80", 80))
		self.assertTrue(drv._eab)
		self.assertEqual([o[1] for o in t.opened], [19200, 38400])

	def test_usb_tries_new_then_old(self) -> None:
		drv, t = self.connectOld(68, usbId="VID_0403&PID_6001")
		self.assertEqual(drv.model, "EL40P")
		self.assertEqual([o[1] for o in t.opened], [57600, 115200, 19200])
		self.assertEqual(t.writes[:4], [NEW_REQUEST, NEW_REQUEST, NEW_REQUEST, OLD_REQUEST])

	def test_no_answer(self) -> None:
		with self.assertRaises(base.DisplayNotFound):
			connectSimulated(PapenmeierDriver, responder=lambda d: None, usbId="VID_0403&PID_F208")

	def test_unknown_model(self) -> None:
		with self.assertRaises(base.DisplayNotFound):
			self.connectNew(0x7E)

	def test_disconnect_resets(self) -> None:
		drv, t = self.connectNew(0x55)
		t.feed(b"\x02K\x50")
		with mock.patch("tiresias.queue_handler.queueFunction"):
			t.fail()
		self.assertEqual(drv.numCells, 0)
		self.assertEqual(drv._buffer, bytearray())


# ======================================================================= salida
class OutputTests(_Base):
	def test_el40s_cells(self) -> None:
		drv, t = self.connectNew(0x55)
		drv.display([0x01, 0x80, 0xFF, 0x12])
		expected = (
			b"\x02C\x52\x5c"  # 40 celdas + 2 + 2 posiciones de los módulos laterales = 44
			+ b"\x30" * 4  # módulo izquierdo
			+ b"\x38\x30"  # punto 1 -> bit 7
			+ b"\x30\x31"  # punto 8 -> bit 0
			+ b"\x3f\x3f"
			+ b"\x34\x38"  # puntos 2 y 5 -> 0x48
			+ b"\x30" * 72
			+ b"\x30" * 4  # módulo derecho
			+ b"\x03"
		)
		self.assertEqual(t.writes[-1], expected)

	def test_el2d80s_vertical_module(self) -> None:
		drv, t = self.connectNew(0x5B)
		drv.display([0x01])
		frame = t.writes[-1]
		self.assertEqual(frame[:4], b"\x02C\x56\x58")  # 20 + 4 + 80 = 104
		self.assertEqual(frame[4 : 4 + 44], b"\x30" * 44)
		self.assertEqual(frame[48:50], b"\x38\x30")
		self.assertEqual(len(frame), 4 + 2 * 104 + 1)

	def test_trio_cells(self) -> None:
		drv, t = self.connectNew(0x59)
		drv.display([0x07])
		self.assertEqual(t.writes[-1], b"\x02C\x52\x58" + b"\x3e\x30" + b"\x30" * 78 + b"\x03")

	def test_old_cells(self) -> None:
		drv, t = self.connectOld(64)
		drv.display([0x01, 0x02, 0x03])
		self.assertEqual(t.writes[-1], b"\x02S\x00\x0d\x00\x2f" + bytes((1, 2, 3)) + bytes(37) + b"\x03")

	def test_old_cells_no_status(self) -> None:
		drv, t = self.connectOld(70)
		drv.display([0xFF] * 20)
		self.assertEqual(t.writes[-1], b"\x02S\x00\x00\x00\x1b" + b"\xff" * 20 + b"\x03")


# ======================================================================= entrada
class NewProtocolInputTests(_Base):
	def test_literal_bar_frame(self) -> None:
		drv, t = self.connectNew(0x55)
		t.feed(b"\x02K\x50\x53\x30\x30\x30\x30\x30\x32\x03")  # tecla 21 = up
		t.feed(b"\x02K\x50\x53" + b"\x30" * 6 + b"\x03")
		self.assertEqual(gestureIds(drv), ["br(papenmeier):up"])

	def test_el_keys(self) -> None:
		drv, t = self.connectNew(0x55)
		cases = [
			({25}, "br(papenmeier):left"),
			({26}, "br(papenmeier):right2"),
			({20}, "br(papenmeier):up2"),
			({23}, "br(papenmeier):dn2"),
			({28, 21}, "br(papenmeier):l1+up"),
			({29}, "br(papenmeier):l2"),
			({112}, "br(papenmeier):r1"),
			({113, 24}, "br(papenmeier):r2+right"),
		]
		for keys, expected in cases:
			t.feed(elKeys(keys))
			t.feed(elKeys(set()))
			self.assertEqual(gestureIds(drv), [expected], keys)

	def test_el_routing_two_rows(self) -> None:
		drv, t = self.connectNew(0x55)
		t.feed(elKeys({32 + 2 * 5}))
		t.feed(elKeys(set()))
		g = drv.lastGestures[-1]
		self.assertEqual(gestureIds(drv), ["br(papenmeier):routing"])
		self.assertEqual(g.routingIndexes, [5])
		t.feed(elKeys({32 + 2 * 39 + 1}))
		t.feed(elKeys(set()))
		g = drv.lastGestures[-1]
		self.assertEqual(gestureIds(drv), ["br(papenmeier):routing2"])
		self.assertEqual(g.routingIndexes, [39])
		t.feed(elKeys({32 + 2 * 3, 32 + 2 * 7}))
		t.feed(elKeys(set()))
		g = drv.lastGestures[-1]
		self.assertEqual(gestureIds(drv), ["br(papenmeier):multirouting"])
		self.assertEqual(g.routingIndexes, [3, 7])

	def test_el2d80s_vertical_keys(self) -> None:
		drv, t = self.connectNew(0x5B)
		for keys, expected in (
			({28}, "br(papenmeier):status1"),
			({29 + 2 * 19}, "br(papenmeier):upperstatus20"),
			({68}, "br(papenmeier):l1"),
			({69, 22}, "br(papenmeier):dn+l2"),
			({72 + 2 * 79}, "br(papenmeier):routing"),
			({72 + 160 + 1}, "br(papenmeier):r2"),
		):
			t.feed(elKeys(keys, pairs=30))
			t.feed(elKeys(set(), pairs=30))
			self.assertEqual(gestureIds(drv), [expected], keys)

	def test_byte_by_byte_and_garbage(self) -> None:
		drv, t = self.connectNew(0x55)
		stream = b"\x55\x03\x30" + elKeys({25, 28}) + b"\x02\x99" + elKeys(set())
		for b in stream:
			t.feed(bytes((b,)))
		self.assertEqual(gestureIds(drv), ["br(papenmeier):l1+left"])

	def test_trio_keys(self) -> None:
		drv, t = self.connectNew(0x59)
		for keys, expected in (
			({22}, "br(papenmeier):up"),
			({21}, "br(papenmeier):dn"),
			({18}, "br(papenmeier):left"),
			({17}, "br(papenmeier):right2"),
			({31, 23}, "br(papenmeier):l1+up2"),
			({30}, "br(papenmeier):l2"),
			({119}, "br(papenmeier):r1"),
			({118}, "br(papenmeier):r2"),
		):
			t.feed(trioKeys(keys))
			t.feed(trioKeys(set()))
			self.assertEqual(gestureIds(drv), [expected], keys)
		t.feed(trioKeys({32 + 2 * 3}))
		t.feed(trioKeys(set()))
		g = drv.lastGestures[-1]
		self.assertEqual(gestureIds(drv), ["br(papenmeier):routing"])
		self.assertEqual(g.routingIndexes, [3])

	def test_trio_literal_key_frame(self) -> None:
		drv, t = self.connectNew(0x59)
		# Byte 5 (teclas 20-23) = 0x32: bit 1 -> tecla 22 (up).
		t.feed(b"\x02K\x50\x53\x30\x30\x30\x30\x30\x32\x03")
		t.feed(b"\x02K\x50\x53" + b"\x30" * 6 + b"\x03")
		self.assertEqual(gestureIds(drv), ["br(papenmeier):up"])

	def test_trio_braille_keyboard(self) -> None:
		drv, t = self.connectNew(0x59)
		t.feed(trioKeyboard(0, 0x03))
		g = drv.lastGestures[-1]
		self.assertEqual(gestureIds(drv), ["br(papenmeier):dot1+dot2"])
		self.assertEqual((g.dots, g.space), (0x03, False))
		t.feed(trioKeyboard(0x02, 0x01))
		g = drv.lastGestures[-1]
		self.assertEqual(gestureIds(drv), ["br(papenmeier):dot1+space"])
		self.assertEqual((g.dots, g.space), (0x01, True))
		t.feed(trioKeyboard(0x02, 0))
		g = drv.lastGestures[-1]
		self.assertEqual(gestureIds(drv), ["br(papenmeier):space"])
		self.assertTrue(g.space)
		t.feed(trioKeyboard(0, 0xC0))
		self.assertEqual(drv.lastGestures[-1].dots, 0xC0)
		self.assertEqual(gestureIds(drv), ["br(papenmeier):dot7+dot8"])
		t.feed(trioKeyboard(0x01, 0x01))
		self.assertEqual(gestureIds(drv), ["br(papenmeier):dot1+rt"])
		t.feed(trioKeyboard(0x04, 0x09))
		self.assertEqual(gestureIds(drv), ["br(papenmeier):dot1+dot4+lt"])
		# Códigos de teclado de PC y tramas vacías: no producen gestos.
		t.feed(trioKeyboard(0x00, 0x1E, scancode=True))
		t.feed(trioKeyboard(0, 0))
		self.assertEqual(gestureIds(drv), [])

	def test_keyboard_byte_by_byte(self) -> None:
		drv, t = self.connectNew(0x62)
		for b in trioKeyboard(0x02, 0x08):
			t.feed(bytes((b,)))
		self.assertEqual(gestureIds(drv), ["br(papenmeier):dot4+space"])


class OldProtocolInputTests(_Base):
	def test_routing_and_status(self) -> None:
		drv, t = self.connectOld(64)  # 13 celdas de estado
		t.feed(oldKey(13 + 4, True))
		t.feed(oldKey(13 + 4, False))
		g = drv.lastGestures[-1]
		self.assertEqual(gestureIds(drv), ["br(papenmeier):routing"])
		self.assertEqual(g.routingIndexes, [4])
		t.feed(oldKey(256 + 13 + 39, True))
		t.feed(oldKey(256 + 13 + 39, False))
		g = drv.lastGestures[-1]
		self.assertEqual(gestureIds(drv), ["br(papenmeier):routing2"])
		self.assertEqual(g.routingIndexes, [39])
		t.feed(oldKey(2, True))
		t.feed(oldKey(2, False))
		t.feed(oldKey(256, True))
		t.feed(oldKey(256, False))
		self.assertEqual(gestureIds(drv), ["br(papenmeier):status3", "br(papenmeier):upperstatus1"])

	def test_literal_key_frame(self) -> None:
		drv, t = self.connectOld(64)
		# Código 0x0333 = 0x300 + 3·17 -> celda 4 tras 13 de estado.
		t.feed(b"\x02K\x03\x33\x00\x00\x01\x00\x00\x03")
		t.feed(b"\x02K\x03\x33\x00\x00\x00\x00\x00\x03")
		self.assertEqual(gestureIds(drv), ["br(papenmeier):routing"])
		self.assertEqual(drv.lastGestures, [])

	def test_front_keys_without_eab(self) -> None:
		drv, t = self.connectOld(64)
		# Posiciones: l1, l2, left, up, r2, dn, right, r1, reportf.
		t.feed(oldKey(-255, True))
		t.feed(oldKey(-252, True))
		t.feed(oldKey(-252, False))
		t.feed(oldKey(-255, False))
		t.feed(oldKey(-247, True))
		t.feed(oldKey(-247, False))
		self.assertEqual(gestureIds(drv), ["br(papenmeier):l1+up", "br(papenmeier):reportf"])

	def test_eab_keys_and_modifiers(self) -> None:
		drv, t = self.connectOld(66, fromRequest=2)
		t.feed(oldKey(-255, True))
		t.feed(oldKey(-255, False))
		t.feed(oldKey(-248, True))
		t.feed(oldKey(-248, False))
		self.assertEqual(gestureIds(drv), ["br(papenmeier):left", "br(papenmeier):dn2"])
		# l1 (bit 0x04) mantenida mientras se mueve la barra hacia arriba.
		t.feed(oldKey(-253, True, mods=0x04))
		t.feed(oldKey(-253, False, mods=0x04))
		t.feed(oldKey(-240, False, mods=0))
		self.assertEqual(gestureIds(drv), ["br(papenmeier):l1+up"])

	def test_old_byte_by_byte(self) -> None:
		drv, t = self.connectOld(70)
		for b in b"\x00\x7f" + oldKey(5, True) + oldKey(5, False):
			t.feed(bytes((b,)))
		g = drv.lastGestures[-1]
		self.assertEqual(gestureIds(drv), ["br(papenmeier):routing"])
		self.assertEqual(g.routingIndexes, [5])


# ======================================================================= detección
class DetectionTests(unittest.TestCase):
	def test_matches(self) -> None:
		devs = [
			DeviceInfo("serial", "COM3", usbId="VID_0403&PID_F208"),
			DeviceInfo("serial", "COM4", usbId="VID_0403&PID_6001"),
			DeviceInfo("serial", "COM5", bluetooth=True, bluetoothName="braillex trio 0042"),
			DeviceInfo("serial", "COM6", bluetooth=True, bluetoothName="BRAILLEX Live 20"),
			DeviceInfo("serial", "COM7", bluetooth=True, bluetoothName="Otro aparato"),
			DeviceInfo("hid", r"\\?\hid#1", usbId="VID_0403&PID_F208"),
			DeviceInfo("serial", "COM8", usbId="VID_1234&PID_5678"),
		]
		self.assertEqual([m.port for m in PapenmeierDriver.getMatches(devs, allowGeneric=False)], ["COM3", "COM5", "COM6"])
		matches = PapenmeierDriver.getMatches(devs, allowGeneric=True)
		self.assertEqual([m.port for m in matches], ["COM3", "COM4", "COM5", "COM6"])
		self.assertEqual([m.type for m in matches], ["serial"] * 4)
		self.assertEqual([m.bluetooth for m in matches], [False, False, True, True])
		self.assertEqual([m.port for m in PapenmeierDriver.getMatches(devs, bluetooth=False)], ["COM3", "COM4"])
		self.assertEqual([m.port for m in PapenmeierDriver.getMatches(devs, usb=False)], ["COM5", "COM6"])

	def test_generic_is_subset(self) -> None:
		self.assertTrue(PapenmeierDriver.genericUsbIds <= PapenmeierDriver.usbSerialIds | PapenmeierDriver.usbHidIds | PapenmeierDriver.usbBulkIds)
		self.assertIn("VID_0403&PID_6001", PapenmeierDriver.genericUsbIds)


# ======================================================================= mapa de gestos
class GestureMapTests(unittest.TestCase):
	def test_values_and_keys(self) -> None:
		ident = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
		for keys, target in PapenmeierDriver.gestureMap.items():
			self.assertTrue(target.startswith("kb:") or ident.match(target), target)
			names = keys.split("+")
			for name in names:
				self.assertIn(name, pm.NAMED_KEYS, keys)
			# Ninguna orden en combinaciones solo de puntos (sirven para escribir).
			self.assertFalse(all(n in PapenmeierDriver.dotKeys for n in names), keys)

	def test_key_order_known(self) -> None:
		for name in PapenmeierDriver.keyOrder:
			self.assertIn(name, pm.NAMED_KEYS)

	def test_effective_map(self) -> None:
		m = PapenmeierDriver.effectiveGestureMap("EL40s")
		self.assertEqual(m["br(papenmeier):left"], "braille_scrollBack")
		self.assertEqual(m["br(papenmeier):dot1+space"], "kb:upArrow")
		self.assertEqual(m["br(papenmeier):l1+up"], "title")


if __name__ == "__main__":
	unittest.main()
