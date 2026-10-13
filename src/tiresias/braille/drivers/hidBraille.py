"""Líneas braille con el estándar HID Braille (página de uso 0x41).

La mayoría de las líneas modernas lo admiten por USB y Bluetooth. Las celdas
se escriben en las matrices «celda de 8 puntos» o «de 6 puntos» de cada fila
(admite líneas de varias filas) y las teclas se leen de los botones de la
página braille.

Nombres de teclas (gestos ``br(hidBraille):...``): ``dot1``...``dot8``,
``space`` (las barras espaciadoras izquierda y derecha también se llaman
``space``), ``panLeft``, ``panRight``, ``rockerUp``, ``rockerDown``,
``rockerPress``, ``joystickUp``/``Down``/``Left``/``Right``/``Center``,
``dpadUp``/``Down``/``Left``/``Right``/``Center``, ``routing`` y
``multiRouting`` (primera fila de enrutamiento, con una o varias teclas
pulsadas), ``routing2``/``multiRouting2`` (segunda fila).
"""

from __future__ import annotations

from typing import Any

from ...i18n import _
from ...log import getLogger
from . import hwio
from .base import DeviceMatch, DisplayNotFound, HardwareDriver
from .ports import DeviceInfo

log = getLogger("braille.hidBraille")

USAGE_PAGE_BRAILLE = 0x41
USAGE_BRAILLE_DISPLAY = 0x01
USAGE_BRAILLE_ROW = 0x02
USAGE_8DOT_CELL = 0x03
USAGE_6DOT_CELL = 0x04
USAGE_NUMBER_OF_CELLS = 0x05
USAGE_ROUTER_SET_1 = 0xFA
USAGE_ROUTER_SET_2 = 0xFB
USAGE_ROUTER_SET_3 = 0xFC
USAGE_ROUTER_KEY = 0x100
USAGE_ROW_ROUTER_KEY = 0x101

#: Uso HID -> nombre de tecla.
BUTTON_NAMES = {
	0x201: "dot1",
	0x202: "dot2",
	0x203: "dot3",
	0x204: "dot4",
	0x205: "dot5",
	0x206: "dot6",
	0x207: "dot7",
	0x208: "dot8",
	0x209: "space",
	0x20A: "space",
	0x20B: "space",
	0x210: "joystickCenter",
	0x211: "joystickUp",
	0x212: "joystickDown",
	0x213: "joystickLeft",
	0x214: "joystickRight",
	0x215: "dpadCenter",
	0x216: "dpadUp",
	0x217: "dpadDown",
	0x218: "dpadLeft",
	0x219: "dpadRight",
	0x21A: "panLeft",
	0x21B: "panRight",
	0x21C: "rockerUp",
	0x21D: "rockerDown",
	0x21E: "rockerPress",
}

ROUTER_SETS = {USAGE_ROUTER_SET_1: "routing", USAGE_ROUTER_SET_2: "routing2", USAGE_ROUTER_SET_3: "routing2"}


class HidLayout:
	"""Disposición de un dispositivo HID Braille a partir de sus capacidades.

	Recibe listas de objetos con los campos de ``HIDP_BUTTON_CAPS`` y
	``HIDP_VALUE_CAPS`` (en las pruebas bastan objetos simples).
	"""

	def __init__(self, inputButtonCaps: list[Any], outputValueCaps: list[Any], inputValueCaps: list[Any]) -> None:
		#: Índice de datos -> clave de tecla (nombre o («routing», índice)).
		self.keys: dict[int, Any] = {}
		#: Filas de celdas: (id de informe, colección, uso, celdas).
		self.rows: list[tuple[int, int, int, int]] = []
		#: Índice de datos del valor «número de celdas», si lo hay.
		self.numCellsIndex: int | None = None
		routers: dict[tuple[str, int], list[int]] = {}
		for bc in inputButtonCaps:
			if bc.IsRange:
				pairs = [(bc.Range.UsageMin + i, idx) for i, idx in enumerate(range(bc.Range.DataIndexMin, bc.Range.DataIndexMax + 1))]
				if bc.Range.UsageMin == bc.Range.UsageMax:
					pairs = [(bc.Range.UsageMin, idx) for _u, idx in pairs]
			else:
				pairs = [(bc.NotRange.Usage, bc.NotRange.DataIndex)]
			if bc.UsagePage != USAGE_PAGE_BRAILLE:
				for usage, idx in pairs:
					self.keys[idx] = f"usagePage{bc.UsagePage}Usage{usage}"
				continue
			for usage, idx in pairs:
				group = ROUTER_SETS.get(bc.LinkUsage) if bc.LinkUsagePage == USAGE_PAGE_BRAILLE else None
				if group is None and usage in (USAGE_ROUTER_KEY, USAGE_ROW_ROUTER_KEY):
					group = "routing"
				if group is not None:
					routers.setdefault((group, bc.LinkCollection), []).append(idx)
				else:
					self.keys[idx] = BUTTON_NAMES.get(usage, f"brailleUsage{usage:X}")
		# La posición de cada tecla de enrutamiento es su orden dentro de la colección.
		for (group, _link), indexes in routers.items():
			for pos, idx in enumerate(sorted(indexes)):
				self.keys[idx] = (group, pos)
		for vc in outputValueCaps:
			usage = vc.Range.UsageMin if vc.IsRange else vc.NotRange.Usage
			if vc.UsagePage == USAGE_PAGE_BRAILLE and usage in (USAGE_8DOT_CELL, USAGE_6DOT_CELL) and vc.ReportCount > 0:
				self.rows.append((vc.ReportID, vc.LinkCollection, usage, vc.ReportCount))
		self.rows.sort(key=lambda r: (r[1], r[0]))
		for vc in inputValueCaps:
			usage = vc.Range.UsageMin if vc.IsRange else vc.NotRange.Usage
			if vc.UsagePage == USAGE_PAGE_BRAILLE and usage == USAGE_NUMBER_OF_CELLS:
				self.numCellsIndex = vc.Range.DataIndexMin if vc.IsRange else vc.NotRange.DataIndex

	@property
	def totalCells(self) -> int:
		return sum(r[3] for r in self.rows)

	@property
	def numRows(self) -> int:
		return len(self.rows)


class HidBrailleDriver(HardwareDriver):
	name = "hidBraille"
	description = _("Línea braille HID estándar (USB o Bluetooth)")
	supportsSerialPorts = False
	keyOrder = ["space", "dot1", "dot2", "dot3", "dot4", "dot5", "dot6", "dot7", "dot8"]
	dotKeys = {f"dot{i}": i for i in range(1, 9)}
	spaceKeys = frozenset({"space"})
	gestureMap = {
		"panLeft": "braille_scrollBack",
		"panRight": "braille_scrollForward",
		"rockerUp": "braille_previousLine",
		"rockerDown": "braille_nextLine",
		"rockerPress": "braille_toFocus",
		"routing": "braille_routeTo",
		"multiRouting": "braille_selectRange",
		"routing2": "braille_reportFormatting",
		# El joystick y la cruceta los atienden las órdenes globales
		# «Línea braille: flecha arriba...» (braille_upArrow...), que además
		# aplican los modificadores activados desde la línea.
		"space+dot1": "kb:upArrow",
		"space+dot4": "kb:downArrow",
		"space+dot3": "kb:leftArrow",
		"space+dot6": "kb:rightArrow",
		"space+dot1+dot3": "kb:shift+tab",
		"space+dot4+dot6": "kb:tab",
		"space+dot1+dot3+dot4": "kb:alt",
		"space+dot1+dot5": "kb:escape",
		"space+dot3+dot4": "kb:windows",
		"space+dot1+dot4+dot5": "kb:windows+d",
		"space+dot2+dot3+dot4+dot5": "kb:alt+tab",
		"space+dot1+dot3+dot4+dot5": "showGui",
		"space+dot1+dot2+dot3+dot4+dot5+dot6": "sayAll",
		"space+dot7": "kb:backspace",
		"space+dot8": "kb:enter",
	}
	#: Nombres de las teclas del estándar HID Braille (las tiene cada línea según su modelo).
	keyDescriptions = {
		**{f"dot{i}": _("punto {n} del teclado braille").format(n=i) for i in range(1, 9)},
		"space": _("barra espaciadora"),
		"panLeft": _("tecla de desplazamiento izquierda (hacia atrás)"),
		"panRight": _("tecla de desplazamiento derecha (hacia delante)"),
		"rockerUp": _("balancín hacia arriba"),
		"rockerDown": _("balancín hacia abajo"),
		"rockerPress": _("pulsación del balancín"),
		"joystickUp": _("joystick hacia arriba"),
		"joystickDown": _("joystick hacia abajo"),
		"joystickLeft": _("joystick hacia la izquierda"),
		"joystickRight": _("joystick hacia la derecha"),
		"joystickCenter": _("pulsación central del joystick"),
		"dpadUp": _("cruceta: flecha arriba"),
		"dpadDown": _("cruceta: flecha abajo"),
		"dpadLeft": _("cruceta: flecha izquierda"),
		"dpadRight": _("cruceta: flecha derecha"),
		"dpadCenter": _("pulsación central de la cruceta"),
		"routing": _("botón de enrutamiento sobre cada celda"),
		"multiRouting": _("dos botones de enrutamiento pulsados a la vez (seleccionan el texto entre ellos)"),
		"routing2": _("botón de la segunda fila de enrutamiento (si la línea la tiene)"),
	}

	@classmethod
	def matchDevice(cls, dev: DeviceInfo, allowGeneric: bool = True) -> DeviceMatch | None:
		if dev.kind == "hid" and dev.usagePage == USAGE_PAGE_BRAILLE and dev.usage in (0, USAGE_BRAILLE_DISPLAY):
			return DeviceMatch("hid", dev.usbId or dev.product, dev.path, dev.bluetooth, dev)
		return None

	@classmethod
	def getPortChoices(cls) -> list[tuple[str, str]]:
		from . import ports

		choices = [("auto", _("Automático")), ("usb", _("USB")), ("bluetooth", _("Bluetooth"))]
		# Varias líneas HID conectadas a la vez: se puede elegir una concreta.
		for dev in ports.listHidDevices():
			m = cls.matchDevice(dev)
			if m is not None:
				kind = _("Bluetooth") if dev.bluetooth else _("USB")
				choices.append((dev.path, f"{dev.product or _('Línea HID')} ({kind})"))
		return choices

	@classmethod
	def candidateMatches(cls, port: str) -> list[DeviceMatch]:
		from . import ports

		if port and port.startswith("\\\\"):
			for dev in ports.listHidDevices():
				if dev.path.lower() == port.lower():
					m = cls.matchDevice(dev)
					return [m] if m else []
			return []
		return super().candidateMatches(port)

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		self._layout: HidLayout | None = None
		super().__init__(*args, **kwargs)

	# ------------------------------------------------------------ conexión
	def _connect(self, match: DeviceMatch) -> None:
		dev = hwio.HidDevice(match.port, self._onReceive, self._onIoError, info=match.info, start=False)
		self._io = dev
		if dev.usagePage != USAGE_PAGE_BRAILLE:
			raise DisplayNotFound("No es una línea braille HID")
		layout = HidLayout(dev.buttonCaps(hwio.HidP_Input), dev.valueCaps(hwio.HidP_Output), dev.valueCaps(hwio.HidP_Input))
		self._setLayout(layout, dev.product)
		if self.numCells <= 0:
			raise DisplayNotFound("La línea no indica sus celdas")
		dev.start()

	def _setLayout(self, layout: HidLayout, product: str = "") -> None:
		self._layout = layout
		self._maxCells = layout.totalCells
		self.numCells = layout.totalCells
		self.numRows = max(1, layout.numRows)
		self.deviceName = product or self.description
		self.model = "".join(ch for ch in (product or "") if ch.isalnum())

	# ------------------------------------------------------------ entrada
	def _getData(self, report: bytes) -> list[tuple[int, int]]:
		return self._io.getData(report)  # type: ignore[union-attr]

	def _handleData(self, data: bytes) -> None:
		layout = self._layout
		if layout is None:
			return
		try:
			items = self._getData(data)
		except hwio.IoError as e:
			log.debug("Informe HID no válido: %s", e)
			return
		down = set()
		for index, value in items:
			if index == layout.numCellsIndex and layout.numRows == 1:
				# Algunas líneas reservan celdas (p. ej. para su propio menú).
				if 0 < value <= self._maxCells:
					self.numCells = value
				continue
			key = layout.keys.get(index)
			if key is not None and value:
				down.add(key)
		self._keysChanged(down)

	# ------------------------------------------------------------ salida
	def _writeCells(self, cells: list[int]) -> None:
		layout = self._layout
		if layout is None or self._io is None:
			return
		data = bytes(c & 0xFF for c in cells) + bytes(max(0, self._maxCells - len(cells)))
		byReport: dict[int, list[tuple[int, int, int, bytes]]] = {}
		pos = 0
		for reportId, link, usage, count in layout.rows:
			byReport.setdefault(reportId, []).append((USAGE_PAGE_BRAILLE, link, usage, data[pos : pos + count]))
			pos += count
		for reportId, values in byReport.items():
			report = self._io.makeOutputReport(reportId, values)  # type: ignore[union-attr]
			self._io.write(report)


BrailleDisplayDriver = HidBrailleDriver
