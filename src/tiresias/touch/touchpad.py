"""Gestos en el panel táctil de precisión (touchpad) mediante Raw Input.

Tiresias se registra con ``RegisterRawInputDevices`` para recibir, en una
ventana de mensajes oculta y aunque no tenga el foco (``RIDEV_INPUTSINK``),
los informes HID de los paneles táctiles de precisión (página de uso 0x0D
«Digitalizador», uso 0x05 «Panel táctil»). Cada informe trae los contactos de
los dedos: identificador, X, Y y «tip switch» (dedo apoyado). Se leen con
``HidP_GetUsageValue`` y ``HidP_GetUsages`` de ``hid.dll`` y se pasan al mismo
reconocedor de gestos que la pantalla táctil, con las coordenadas del panel
llevadas a la pantalla.

Windows sigue procesando el panel con normalidad (mueve el puntero, hace
clic al tocar, desplaza con dos dedos...): Raw Input solo permite observar,
no bloquear. Por eso, por defecto, solo se reconocen los gestos de varios
dedos.

La lógica que no necesita Windows (:class:`TouchpadLayout`,
:class:`FrameAssembler`, :class:`ContactTracker`, :func:`parseRawInputBuffer`
y :func:`layoutFromCaps`) se puede probar con datos simulados.
"""

from __future__ import annotations

import ctypes
import struct
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Callable, Protocol

from . import win32 as W
from .recognizer import GestureRecognizer, RecognizerSettings

log = W.log

# ---------------------------------------------------------------- usos HID
PAGE_GENERIC = 0x01
PAGE_DIGITIZER = 0x0D
PAGE_BUTTON = 0x09
USAGE_X = 0x30
USAGE_Y = 0x31
USAGE_TOUCHPAD = 0x05
USAGE_FINGER = 0x22
USAGE_TIP_SWITCH = 0x42
USAGE_CONFIDENCE = 0x47
USAGE_CONTACT_ID = 0x51
USAGE_CONTACT_COUNT = 0x54

HidP_Input = 0
HIDP_STATUS_SUCCESS = 0x00110000

RIM_TYPEHID = 2
RID_INPUT = 0x10000003
RIDI_PREPARSEDDATA = 0x20000005
RIDEV_REMOVE = 0x00000001
RIDEV_INPUTSINK = 0x00000100
RIDEV_DEVNOTIFY = 0x00002000
WM_INPUT_DEVICE_CHANGE = 0x00FE
GIDC_REMOVAL = 2

#: Tamaño de RAWINPUTHEADER en 64 bits (DWORD, DWORD, HANDLE, WPARAM).
_HEADER_SIZE = struct.calcsize("IIQQ")


# ====================================================================== estructuras HID
class _CapsRange(ctypes.Structure):
	_fields_ = [
		("UsageMin", wintypes.USHORT),
		("UsageMax", wintypes.USHORT),
		("StringMin", wintypes.USHORT),
		("StringMax", wintypes.USHORT),
		("DesignatorMin", wintypes.USHORT),
		("DesignatorMax", wintypes.USHORT),
		("DataIndexMin", wintypes.USHORT),
		("DataIndexMax", wintypes.USHORT),
	]


class _CapsNotRange(ctypes.Structure):
	_fields_ = [
		("Usage", wintypes.USHORT),
		("Reserved1", wintypes.USHORT),
		("StringIndex", wintypes.USHORT),
		("Reserved2", wintypes.USHORT),
		("DesignatorIndex", wintypes.USHORT),
		("Reserved3", wintypes.USHORT),
		("DataIndex", wintypes.USHORT),
		("Reserved4", wintypes.USHORT),
	]


class _CapsUnion(ctypes.Union):
	_fields_ = [("Range", _CapsRange), ("NotRange", _CapsNotRange)]


class HIDP_VALUE_CAPS(ctypes.Structure):
	_anonymous_ = ("u",)
	_fields_ = [
		("UsagePage", wintypes.USHORT),
		("ReportID", ctypes.c_ubyte),
		("IsAlias", ctypes.c_ubyte),
		("BitField", wintypes.USHORT),
		("LinkCollection", wintypes.USHORT),
		("LinkUsage", wintypes.USHORT),
		("LinkUsagePage", wintypes.USHORT),
		("IsRange", ctypes.c_ubyte),
		("IsStringRange", ctypes.c_ubyte),
		("IsDesignatorRange", ctypes.c_ubyte),
		("IsAbsolute", ctypes.c_ubyte),
		("HasNull", ctypes.c_ubyte),
		("Reserved", ctypes.c_ubyte),
		("BitSize", wintypes.USHORT),
		("ReportCount", wintypes.USHORT),
		("Reserved2", wintypes.USHORT * 5),
		("UnitsExp", wintypes.ULONG),
		("Units", wintypes.ULONG),
		("LogicalMin", wintypes.LONG),
		("LogicalMax", wintypes.LONG),
		("PhysicalMin", wintypes.LONG),
		("PhysicalMax", wintypes.LONG),
		("u", _CapsUnion),
	]


class HIDP_BUTTON_CAPS(ctypes.Structure):
	_anonymous_ = ("u",)
	_fields_ = [
		("UsagePage", wintypes.USHORT),
		("ReportID", ctypes.c_ubyte),
		("IsAlias", ctypes.c_ubyte),
		("BitField", wintypes.USHORT),
		("LinkCollection", wintypes.USHORT),
		("LinkUsage", wintypes.USHORT),
		("LinkUsagePage", wintypes.USHORT),
		("IsRange", ctypes.c_ubyte),
		("IsStringRange", ctypes.c_ubyte),
		("IsDesignatorRange", ctypes.c_ubyte),
		("IsAbsolute", ctypes.c_ubyte),
		("ReportCount", wintypes.USHORT),
		("Reserved2", wintypes.USHORT),
		("Reserved", wintypes.ULONG * 9),
		("u", _CapsUnion),
	]


class HIDP_CAPS(ctypes.Structure):
	_fields_ = [
		("Usage", wintypes.USHORT),
		("UsagePage", wintypes.USHORT),
		("InputReportByteLength", wintypes.USHORT),
		("OutputReportByteLength", wintypes.USHORT),
		("FeatureReportByteLength", wintypes.USHORT),
		("Reserved", wintypes.USHORT * 17),
		("NumberLinkCollectionNodes", wintypes.USHORT),
		("NumberInputButtonCaps", wintypes.USHORT),
		("NumberInputValueCaps", wintypes.USHORT),
		("NumberInputDataIndices", wintypes.USHORT),
		("NumberOutputButtonCaps", wintypes.USHORT),
		("NumberOutputValueCaps", wintypes.USHORT),
		("NumberOutputDataIndices", wintypes.USHORT),
		("NumberFeatureButtonCaps", wintypes.USHORT),
		("NumberFeatureValueCaps", wintypes.USHORT),
		("NumberFeatureDataIndices", wintypes.USHORT),
	]


class RAWINPUTDEVICE(ctypes.Structure):
	_fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT), ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND)]


def _capsUsages(cap) -> range:
	if cap.IsRange:
		return range(cap.Range.UsageMin, cap.Range.UsageMax + 1)
	return range(cap.NotRange.Usage, cap.NotRange.Usage + 1)


# ====================================================================== disposición del panel
@dataclass
class FingerSlot:
	"""Colección lógica de un dedo dentro del informe."""

	link: int
	xMin: int
	xMax: int
	yMin: int
	yMax: int
	hasContactId: bool = True
	hasConfidence: bool = False


@dataclass
class TouchpadLayout:
	"""Qué campos trae el informe del panel y en qué colecciones."""

	fingers: list[FingerSlot] = field(default_factory=list)
	#: Colección del recuento de contactos (``None`` si no lo hay).
	contactCountLink: int | None = None

	@property
	def isUsable(self) -> bool:
		return bool(self.fingers)


def layoutFromCaps(valueCaps, buttonCaps) -> TouchpadLayout:
	"""Construye la disposición a partir de las capacidades HID de entrada."""
	xs: dict[int, tuple[int, int]] = {}
	ys: dict[int, tuple[int, int]] = {}
	ids: set[int] = set()
	countLink = None
	for cap in valueCaps:
		usages = _capsUsages(cap)
		link = int(cap.LinkCollection)
		if cap.UsagePage == PAGE_GENERIC:
			if USAGE_X in usages:
				xs[link] = (int(cap.LogicalMin), int(cap.LogicalMax))
			if USAGE_Y in usages:
				ys[link] = (int(cap.LogicalMin), int(cap.LogicalMax))
		elif cap.UsagePage == PAGE_DIGITIZER:
			if USAGE_CONTACT_ID in usages:
				ids.add(link)
			if USAGE_CONTACT_COUNT in usages and countLink is None:
				countLink = link
	confidence: set[int] = set()
	for cap in buttonCaps:
		if cap.UsagePage == PAGE_DIGITIZER and USAGE_CONFIDENCE in _capsUsages(cap):
			confidence.add(int(cap.LinkCollection))
	fingers = []
	for link in sorted(set(xs) & set(ys)):
		(x0, x1), (y0, y1) = xs[link], ys[link]
		if x1 <= x0 or y1 <= y0:
			continue
		fingers.append(FingerSlot(link, x0, x1, y0, y1, link in ids, link in confidence))
	return TouchpadLayout(fingers, countLink)


# ====================================================================== lectura de informes
class ReportAccessor(Protocol):
	"""Lee campos de un informe HID (``hid.dll`` o datos simulados)."""

	def value(self, page: int, usage: int, link: int) -> int | None: ...

	def pressed(self, page: int, link: int) -> set[int] | None: ...


class HidReport:
	"""Acceso a un informe HID real con ``HidP_GetUsageValue``/``HidP_GetUsages``."""

	_hid = None

	def __init__(self, preparsed: ctypes.Array, report: bytes) -> None:
		self._pp = preparsed
		self._buf = ctypes.create_string_buffer(report, len(report))
		self._len = len(report)
		hid = HidReport._getHid()
		self._getValue = hid.HidP_GetUsageValue
		self._getUsages = hid.HidP_GetUsages

	@classmethod
	def _getHid(cls):
		if cls._hid is None:
			hid = ctypes.WinDLL("hid")
			hid.HidP_GetUsageValue.argtypes = [
				ctypes.c_int,
				wintypes.USHORT,
				wintypes.USHORT,
				wintypes.USHORT,
				ctypes.POINTER(wintypes.ULONG),
				ctypes.c_void_p,
				ctypes.c_char_p,
				wintypes.ULONG,
			]
			hid.HidP_GetUsageValue.restype = ctypes.c_long
			hid.HidP_GetUsages.argtypes = [
				ctypes.c_int,
				wintypes.USHORT,
				wintypes.USHORT,
				ctypes.POINTER(wintypes.USHORT),
				ctypes.POINTER(wintypes.ULONG),
				ctypes.c_void_p,
				ctypes.c_char_p,
				wintypes.ULONG,
			]
			hid.HidP_GetUsages.restype = ctypes.c_long
			hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
			hid.HidP_GetCaps.restype = ctypes.c_long
			hid.HidP_GetValueCaps.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wintypes.USHORT), ctypes.c_void_p]
			hid.HidP_GetValueCaps.restype = ctypes.c_long
			hid.HidP_GetButtonCaps.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wintypes.USHORT), ctypes.c_void_p]
			hid.HidP_GetButtonCaps.restype = ctypes.c_long
			cls._hid = hid
		return cls._hid

	def value(self, page: int, usage: int, link: int) -> int | None:
		v = wintypes.ULONG()
		res = self._getValue(HidP_Input, page, link, usage, ctypes.byref(v), self._pp, self._buf, self._len)
		return int(v.value) if (res & 0xFFFFFFFF) == HIDP_STATUS_SUCCESS else None

	def pressed(self, page: int, link: int) -> set[int] | None:
		arr = (wintypes.USHORT * 32)()
		n = wintypes.ULONG(32)
		res = self._getUsages(HidP_Input, page, link, arr, ctypes.byref(n), self._pp, self._buf, self._len)
		if (res & 0xFFFFFFFF) != HIDP_STATUS_SUCCESS:
			return None
		return {int(arr[i]) for i in range(n.value)}


def readLayout(preparsed: ctypes.Array) -> TouchpadLayout:
	"""Lee las capacidades de entrada de un dispositivo y su disposición."""
	hid = HidReport._getHid()
	caps = HIDP_CAPS()
	if (hid.HidP_GetCaps(preparsed, ctypes.byref(caps)) & 0xFFFFFFFF) != HIDP_STATUS_SUCCESS:
		return TouchpadLayout()
	nv = wintypes.USHORT(caps.NumberInputValueCaps)
	values = (HIDP_VALUE_CAPS * max(1, nv.value))()
	if nv.value and (hid.HidP_GetValueCaps(HidP_Input, values, ctypes.byref(nv), preparsed) & 0xFFFFFFFF) != HIDP_STATUS_SUCCESS:
		nv.value = 0
	nb = wintypes.USHORT(caps.NumberInputButtonCaps)
	buttons = (HIDP_BUTTON_CAPS * max(1, nb.value))()
	if nb.value and (hid.HidP_GetButtonCaps(HidP_Input, buttons, ctypes.byref(nb), preparsed) & 0xFFFFFFFF) != HIDP_STATUS_SUCCESS:
		nb.value = 0
	return layoutFromCaps(list(values)[: nv.value], list(buttons)[: nb.value])


@dataclass
class Contact:
	cid: int
	x: int
	y: int
	tip: bool


class FrameAssembler:
	"""Reúne los contactos de un «fotograma» del panel.

	Los paneles pueden enviar todos los dedos en un informe o repartirlos en
	varios (modo híbrido): el primero trae el recuento de contactos y los
	siguientes, recuento 0. Devuelve la lista completa cuando la tiene.
	"""

	def __init__(self, layout: TouchpadLayout) -> None:
		self.layout = layout
		self._expected = 0
		self._contacts: list[Contact] = []

	def feed(self, report: ReportAccessor) -> list[Contact] | None:
		layout = self.layout
		count = None
		if layout.contactCountLink is not None:
			count = report.value(PAGE_DIGITIZER, USAGE_CONTACT_COUNT, layout.contactCountLink)
		if count:
			self._expected = count
			self._contacts = []
		elif count is None and not self._expected:
			# Sin recuento: cada informe es un fotograma completo.
			self._expected = len(layout.fingers)
			self._contacts = []
		elif count == 0 and not self._expected:
			return []
		for i, slot in enumerate(layout.fingers):
			if len(self._contacts) >= self._expected:
				break
			x = report.value(PAGE_GENERIC, USAGE_X, slot.link)
			y = report.value(PAGE_GENERIC, USAGE_Y, slot.link)
			if x is None or y is None:
				continue
			cid = report.value(PAGE_DIGITIZER, USAGE_CONTACT_ID, slot.link) if slot.hasContactId else None
			buttons = report.pressed(PAGE_DIGITIZER, slot.link) or set()
			tip = USAGE_TIP_SWITCH in buttons
			if slot.hasConfidence and USAGE_CONFIDENCE not in buttons:
				# Contacto que el panel considera accidental (palma de la mano).
				tip = False
			if count is None and not tip and cid is None:
				continue
			self._contacts.append(Contact(i if cid is None else cid, x, y, tip))
		if len(self._contacts) >= self._expected or count is None:
			frame = self._contacts
			self._contacts = []
			self._expected = 0
			return frame
		return None


class ContactTracker:
	"""Compara fotogramas y produce eventos ``down``/``move``/``up`` por dedo."""

	def __init__(self, mapPoint: Callable[[FingerSlot | None, int, int], tuple[int, int]] | None = None) -> None:
		self._active: dict[int, tuple[int, int]] = {}
		self.mapPoint = mapPoint or (lambda slot, x, y: (x, y))

	def update(self, frame: list[Contact], slot: FingerSlot | None = None) -> list[tuple[str, int, int, int]]:
		events: list[tuple[str, int, int, int]] = []
		seen: set[int] = set()
		for c in frame:
			x, y = self.mapPoint(slot, c.x, c.y)
			if c.tip:
				seen.add(c.cid)
				if c.cid not in self._active:
					events.append(("down", c.cid, x, y))
				elif self._active[c.cid] != (x, y):
					events.append(("move", c.cid, x, y))
				self._active[c.cid] = (x, y)
			elif c.cid in self._active:
				events.append(("up", c.cid, x, y))
				del self._active[c.cid]
				seen.add(c.cid)
		for cid in [k for k in self._active if k not in seen]:
			x, y = self._active.pop(cid)
			events.append(("up", cid, x, y))
		return events

	def reset(self) -> list[tuple[str, int, int, int]]:
		events = [("up", cid, x, y) for cid, (x, y) in self._active.items()]
		self._active.clear()
		return events


def scaleToScreen(slot: FingerSlot, x: int, y: int, screen: tuple[int, int, int, int]) -> tuple[int, int]:
	"""Lleva un punto del panel (unidades lógicas) a la pantalla."""
	sx, sy, sw, sh = screen
	fx = (x - slot.xMin) / max(1, slot.xMax - slot.xMin)
	fy = (y - slot.yMin) / max(1, slot.yMax - slot.yMin)
	fx = min(1.0, max(0.0, fx))
	fy = min(1.0, max(0.0, fy))
	return int(sx + fx * (sw - 1)), int(sy + fy * (sh - 1))


def parseRawInputBuffer(buf: bytes) -> tuple[int, list[bytes]] | None:
	"""Separa un ``RAWINPUT`` de tipo HID en (dispositivo, informes)."""
	if len(buf) < _HEADER_SIZE + 8:
		return None
	dwType, _dwSize, hDevice, _wParam = struct.unpack_from("IIQQ", buf, 0)
	if dwType != RIM_TYPEHID:
		return None
	sizeHid, count = struct.unpack_from("II", buf, _HEADER_SIZE)
	start = _HEADER_SIZE + 8
	if sizeHid == 0 or start + sizeHid * count > len(buf):
		return None
	reports = [bytes(buf[start + i * sizeHid : start + (i + 1) * sizeHid]) for i in range(count)]
	return hDevice, reports


# ====================================================================== ventana de Raw Input
class _Device:
	def __init__(self, preparsed: ctypes.Array, layout: TouchpadLayout) -> None:
		self.preparsed = preparsed
		self.layout = layout
		self.assembler = FrameAssembler(layout)


class TouchpadInput(W.WindowThread):
	"""Ventana oculta que recibe los informes del panel táctil y reconoce gestos.

	:param onEvents: se llama en el hilo de la ventana con la lista de gestos
		reconocidos (coordenadas ya llevadas a la pantalla).
	"""

	threadName = "Panel táctil"

	def __init__(
		self,
		onEvents: Callable[[list], None],
		settings: RecognizerSettings | None = None,
		sequenceFilter: Callable[[str, int], bool] | None = None,
	) -> None:
		super().__init__()
		self.onEvents = onEvents
		self.recognizer = GestureRecognizer(settings, sequenceFilter)
		self._devices: dict[int, _Device | None] = {}
		self._tracker = ContactTracker()
		self._screen = W.virtualScreen()
		self._registered = False

	def _onContact(self, kind: str, cid: int, x: int, y: int, t: float) -> None:
		rec = self.recognizer
		if kind == "down":
			events = rec.down(cid, x, y, t)
		elif kind == "move":
			events = rec.move(cid, x, y, t)
		else:
			events = rec.up(cid, x, y, t)
		if events:
			try:
				self.onEvents(events)
			except Exception:
				log.exception("Error entregando gestos del panel táctil")

	def _schedule(self, hwnd: int) -> None:
		deadline = self.recognizer.nextDeadline()
		if deadline is None:
			W.user32.KillTimer(hwnd, 1)
			return
		ms = max(1, int((deadline - time.monotonic()) * 1000) + 1)
		W.user32.SetTimer(hwnd, 1, ms, None)

	@staticmethod
	def _declare() -> None:
		u = W.user32
		u.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT]
		u.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p, ctypes.POINTER(wintypes.UINT), wintypes.UINT]
		u.GetRawInputData.restype = wintypes.UINT
		u.GetRawInputDeviceInfoW.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p, ctypes.POINTER(wintypes.UINT)]
		u.GetRawInputDeviceInfoW.restype = wintypes.UINT

	def createWindow(self) -> int:
		self._declare()
		self._registerClass()
		hwnd = W.user32.CreateWindowExW(0, self._className, "Tiresias: panel táctil", 0, 0, 0, 0, 0, W.HWND_MESSAGE, None, self.hInstance, None)
		if not hwnd:
			raise ctypes.WinError(ctypes.get_last_error())
		dev = RAWINPUTDEVICE(PAGE_DIGITIZER, USAGE_TOUCHPAD, RIDEV_INPUTSINK | RIDEV_DEVNOTIFY, hwnd)
		if not W.user32.RegisterRawInputDevices(ctypes.byref(dev), 1, ctypes.sizeof(RAWINPUTDEVICE)):
			err = ctypes.get_last_error()
			W.user32.DestroyWindow(hwnd)
			raise OSError(err, "RegisterRawInputDevices falló")
		self._registered = True
		log.info("Panel táctil: escuchando informes de paneles de precisión")
		return hwnd

	def onDestroy(self) -> None:
		W.user32.KillTimer(self.hwnd, 1)
		if self._registered:
			dev = RAWINPUTDEVICE(PAGE_DIGITIZER, USAGE_TOUCHPAD, RIDEV_REMOVE, None)
			W.user32.RegisterRawInputDevices(ctypes.byref(dev), 1, ctypes.sizeof(RAWINPUTDEVICE))
			self._registered = False

	def _deviceFor(self, hDevice: int) -> _Device | None:
		if hDevice in self._devices:
			return self._devices[hDevice]
		dev = None
		try:
			size = wintypes.UINT(0)
			W.user32.GetRawInputDeviceInfoW(hDevice, RIDI_PREPARSEDDATA, None, ctypes.byref(size))
			if size.value:
				buf = (ctypes.c_ubyte * size.value)()
				if W.user32.GetRawInputDeviceInfoW(hDevice, RIDI_PREPARSEDDATA, buf, ctypes.byref(size)) not in (0, 0xFFFFFFFF):
					layout = readLayout(buf)
					if layout.isUsable:
						dev = _Device(buf, layout)
						log.info("Panel táctil detectado: %d dedos como máximo", len(layout.fingers))
		except Exception:
			log.debug("No se pudo leer el panel táctil", exc_info=True)
		self._devices[hDevice] = dev
		return dev

	def _mapPoint(self, slot: FingerSlot | None, x: int, y: int) -> tuple[int, int]:
		if slot is None:
			return x, y
		return scaleToScreen(slot, x, y, self._screen)

	def _onInput(self, lParam: int) -> None:
		size = wintypes.UINT(0)
		W.user32.GetRawInputData(lParam, RID_INPUT, None, ctypes.byref(size), _HEADER_SIZE)
		if not size.value:
			return
		buf = (ctypes.c_ubyte * size.value)()
		got = W.user32.GetRawInputData(lParam, RID_INPUT, buf, ctypes.byref(size), _HEADER_SIZE)
		if got in (0, 0xFFFFFFFF):
			return
		parsed = parseRawInputBuffer(bytes(buf))
		if parsed is None:
			return
		hDevice, reports = parsed
		dev = self._deviceFor(hDevice)
		if dev is None:
			return
		slot = dev.layout.fingers[0]
		for report in reports:
			frame = dev.assembler.feed(HidReport(dev.preparsed, report))
			if frame is None:
				continue
			self._tracker.mapPoint = self._mapPoint
			t = time.monotonic()
			for kind, cid, x, y in self._tracker.update(frame, slot):
				self._onContact(kind, cid, x, y, t)
		self._schedule(self.hwnd)

	def wndProc(self, hwnd: int, msg: int, wParam: int, lParam: int) -> int | None:
		if msg == W.WM_INPUT:
			self._onInput(lParam)
			return None
		if msg == WM_INPUT_DEVICE_CHANGE:
			if wParam == GIDC_REMOVAL:
				self._devices.pop(lParam, None)
				t = time.monotonic()
				for kind, cid, x, y in self._tracker.reset():
					self._onContact(kind, cid, x, y, t)
				self._schedule(hwnd)
			return 0
		if msg == W.WM_TIMER and wParam == 1:
			W.user32.KillTimer(hwnd, 1)
			events = self.recognizer.poll(time.monotonic())
			if events:
				try:
					self.onEvents(events)
				except Exception:
					log.exception("Error entregando gestos del panel táctil")
			self._schedule(hwnd)
			return 0
		return None
