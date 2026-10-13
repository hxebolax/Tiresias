"""Diálogo «Seleccionar línea braille» y ajustes de las líneas de la categoría «Braille».

El diálogo permite elegir el controlador (o «Automático»), el puerto
(Automático, USB, Bluetooth, un puerto COM o un dispositivo concreto),
probar la conexión y decidir qué líneas busca la detección automática.
La categoría «Braille» del cuadro de Opciones usa las funciones de abajo para
los ajustes propios de cada controlador.
"""

from __future__ import annotations

import threading
from typing import Any

import wx

from .. import queue_handler
from ..config import conf
from ..i18n import _
from ..log import getLogger
from .settings import SettingsBuilder, isAlive, parentWindow, speakMessageOnCore

log = getLogger("gui.brailleDisplay")

_dialog: "BrailleDisplayDialog | None" = None


def _driverClass(name: str):
	from .. import braille

	return braille.getDriverClass(name)


def _isHardware(name: str) -> bool:
	try:
		return bool(getattr(_driverClass(name), "isHardware", False))
	except Exception:
		return False


class BrailleDisplayDialog(wx.Dialog):
	def __init__(self, parent: wx.Window | None) -> None:
		super().__init__(parent, title=_("Seleccionar línea braille"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		from .. import braille
		from ..braille import drivers
		from ..braille.drivers import detect

		self._displays = braille.getDisplayList()
		self._names = [n for n, _d in self._displays]
		self._portValues: list[str] = []
		self._portToken = 0
		self._testing = False
		main = wx.BoxSizer(wx.VERTICAL)
		builder = SettingsBuilder(self, main)
		self.displayList = builder.addLabeledControl(
			_("&Línea braille:"),
			lambda p: wx.ListBox(p, choices=[d for _n, d in self._displays], style=wx.LB_SINGLE, size=(380, 200)),
			vertical=True,
			proportion=1,
		)
		self.portChoice = builder.addChoice(_("&Puerto:"), [_("Automático")])
		self.testButton = builder.addButton(_("P&robar la conexión"))
		self.resultText = builder.addLabeledControl(
			_("Resultado de la prueba:"),
			lambda p: wx.TextCtrl(p, value="", style=wx.TE_READONLY | wx.TE_MULTILINE, size=(380, 50)),
			vertical=True,
		)
		group = builder.group(_("Detección automática"))
		self._hardware = drivers.hardwareDriverChoices()
		self.autoList = group.addLabeledControl(
			_("Líneas que se &buscan automáticamente:"),
			lambda p: wx.CheckListBox(p, choices=[d for _n, d in self._hardware], size=(380, 160)),
			vertical=True,
		)
		excluded = set(detect.excludedDrivers())
		for i, (name, _d) in enumerate(self._hardware):
			self.autoList.Check(i, name not in excluded)
		buttons = wx.StdDialogButtonSizer()
		ok = wx.Button(self, wx.ID_OK, _("Aceptar"))
		cancel = wx.Button(self, wx.ID_CANCEL, _("Cancelar"))
		buttons.AddButton(ok)
		buttons.AddButton(cancel)
		buttons.Realize()
		main.Add(buttons, 0, wx.ALIGN_RIGHT | wx.TOP, 8)
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(main, 1, wx.EXPAND | wx.ALL, 10)
		self.SetSizer(outer)
		outer.Fit(self)
		ok.SetDefault()
		self.SetEscapeId(wx.ID_CANCEL)
		ok.Bind(wx.EVT_BUTTON, self._onOk)
		cancel.Bind(wx.EVT_BUTTON, lambda evt: self._close())
		self.Bind(wx.EVT_CLOSE, lambda evt: self._close())
		self.displayList.Bind(wx.EVT_LISTBOX, lambda evt: self._onDisplayChanged())
		self.testButton.Bind(wx.EVT_BUTTON, self._onTest)
		current = conf["braille"]["display"] or "noBraille"
		self.displayList.SetSelection(self._names.index(current) if current in self._names else 0)
		self._onDisplayChanged()
		self.CentreOnScreen()
		self.displayList.SetFocus()

	# ------------------------------------------------------------ selección
	def _selectedName(self) -> str:
		i = self.displayList.GetSelection()
		return self._names[i] if 0 <= i < len(self._names) else "noBraille"

	def _selectedPort(self) -> str:
		i = self.portChoice.GetSelection()
		return self._portValues[i] if 0 <= i < len(self._portValues) else "auto"

	def _onDisplayChanged(self) -> None:
		name = self._selectedName()
		hardware = _isHardware(name)
		self.portChoice.Enable(hardware)
		self.testButton.Enable(hardware or name == "auto")
		self.autoList.Enable(name == "auto")
		self.resultText.SetValue("")
		self._portValues = ["auto"]
		self.portChoice.Set([_("Automático")])
		self.portChoice.SetSelection(0)
		if not hardware:
			return
		# Los puertos se enumeran en segundo plano (puede tardar un poco).
		self._portToken += 1
		token = self._portToken

		def work() -> None:
			try:
				choices = _driverClass(name).getPortChoices()
			except Exception:
				log.exception("No se pudieron obtener los puertos de %s", name)
				choices = [("auto", _("Automático"))]
			wx.CallAfter(self._onPorts, token, name, choices)

		threading.Thread(target=work, name="braille-ports", daemon=True).start()

	def _onPorts(self, token: int, name: str, choices: list[tuple[str, str]]) -> None:
		if not isAlive(self) or token != self._portToken:
			return
		from ..braille.drivers.base import getConfiguredPort, portLabel

		wanted = getConfiguredPort(name)
		values = [v for v, _l in choices]
		labels = [lbl for _v, lbl in choices]
		if wanted not in values:
			# Puerto guardado que ahora no está presente: se conserva.
			values.append(wanted)
			labels.append(_("{port} (no presente)").format(port=portLabel(wanted)))
		self._portValues = values
		self.portChoice.Set(labels)
		self.portChoice.SetSelection(values.index(wanted))

	# ------------------------------------------------------------ prueba
	def _onTest(self, evt: wx.CommandEvent) -> None:
		if self._testing:
			return
		name = self._selectedName()
		port = self._selectedPort()
		from .. import braille

		display = braille.handler.display
		if getattr(display, "name", "") == name and getattr(display, "connected", False):
			# No se abre dos veces el mismo dispositivo.
			msg = _("Conectada ahora: {name}, {cells} celdas.").format(name=display.displayName, cells=display.numCells)
			self._showResult(msg)
			return
		self._testing = True
		self.testButton.Disable()
		self._showResult(_("Probando la conexión..."))

		def work() -> None:
			from ..braille.drivers import detect

			try:
				ok, desc, cells = detect.testConnection(name, port)
			except Exception:
				log.exception("Error probando la línea braille")
				ok, desc, cells = False, "", 0
			wx.CallAfter(self._onTestDone, ok, desc, cells)

		threading.Thread(target=work, name="braille-test", daemon=True).start()

	def _onTestDone(self, ok: bool, desc: str, cells: int) -> None:
		if not isAlive(self):
			return
		self._testing = False
		self.testButton.Enable()
		if ok:
			msg = _("Línea encontrada: {desc}, {cells} celdas.").format(desc=desc, cells=cells)
		else:
			msg = _("No se ha encontrado la línea. Comprueba que está encendida y conectada, y el puerto elegido.")
		self._showResult(msg)

	def _showResult(self, msg: str) -> None:
		self.resultText.SetValue(msg)
		speakMessageOnCore(msg)

	# ------------------------------------------------------------ aceptar
	def _onOk(self, evt: wx.CommandEvent) -> None:
		from ..braille.drivers.base import setConfiguredPort

		name = self._selectedName()
		if _isHardware(name):
			setConfiguredPort(name, self._selectedPort())
		excluded = [n for i, (n, _d) in enumerate(self._hardware) if not self.autoList.IsChecked(i)]
		conf["brailleDisplays"]["excludedFromAuto"] = excluded
		conf["braille"]["display"] = name
		queue_handler.queueFunction(_applyDisplay, name)
		self._close()

	def _close(self) -> None:
		global _dialog
		if _dialog is self:
			_dialog = None
		self.Hide()
		self.Destroy()


def _applyDisplay(name: str) -> None:
	"""Hilo del núcleo: carga la línea elegida (si no conecta, sigue esperándola)."""
	from .. import braille

	if not braille.handler.setDisplay(name):
		from .. import speech

		speech.speakMessage(_("No se pudo cargar el controlador de la línea braille."))


def showDialog() -> None:
	"""Abre el diálogo (hilo de la interfaz)."""
	global _dialog
	if _dialog is not None and isAlive(_dialog):
		_dialog.Raise()
		_dialog.displayList.SetFocus()
		return
	_dialog = BrailleDisplayDialog(parentWindow())
	_dialog.Show()
	_dialog.Raise()


# ======================================================================= categoría «Braille»
# La categoría «Braille» del cuadro de Opciones (``settings.BraillePanel``) muestra
# la línea actual con el botón «Seleccionar línea braille...», las opciones de
# conexión y detección (sección ``brailleDisplays``) y, con estas funciones, un
# grupo por cada controlador con ajustes propios.

#: (controlador, ajuste, control, valores de la lista)
DriverControls = list[tuple[str, Any, wx.Window, list]]


def makeDriverSettings(builder: SettingsBuilder) -> DriverControls:
	"""Un grupo por cada controlador de línea con ajustes propios."""
	from ..braille import drivers

	ctrls: DriverControls = []
	for name, desc in drivers.hardwareDriverChoices():
		try:
			cls = _driverClass(name)
		except Exception:
			continue
		settings = getattr(cls, "driverSettings", ())
		if not settings:
			continue
		group = builder.group(desc)
		for s in settings:
			value = cls.getSetting(s.key)
			values: list = []
			if s.kind == "bool":
				ctrl = group.addCheckBox(s.label, bool(value))
			elif s.kind == "int":
				ctrl = group.addSpin(s.label, s.minVal, s.maxVal, int(value))
			else:
				values = [v for v, _l in s.choices]
				labels = [lbl for _v, lbl in s.choices]
				if value not in values:
					# Valor guardado desconocido: se conserva (como en ConfigPanel).
					values.append(value)
					labels.append(str(value) if value not in (None, "") else _("(sin valor)"))
				ctrl = group.addChoice(s.label, labels, values.index(value))
			ctrls.append((name, s, ctrl, values))
	return ctrls


def _setDriverControl(s: Any, ctrl: wx.Window, values: list, value: Any) -> None:
	if s.kind == "bool":
		ctrl.SetValue(bool(value))
	elif s.kind == "int":
		ctrl.SetValue(int(value))
	elif value in values:
		ctrl.SetSelection(values.index(value))


def resetDriverSettings(ctrls: DriverControls) -> None:
	"""Pone los ajustes de los controladores con sus valores de fábrica (sin guardar)."""
	for _name, s, ctrl, values in ctrls:
		_setDriverControl(s, ctrl, values, s.default)


def saveDriverSettings(ctrls: DriverControls) -> None:
	"""Guarda los ajustes de los controladores que han cambiado y los aplica."""
	from ..braille.drivers.base import getDriverSetting, setDriverSetting

	changed: set[str] = set()
	for name, s, ctrl, values in ctrls:
		if s.kind == "bool":
			value: Any = bool(ctrl.GetValue())
		elif s.kind == "int":
			value = int(ctrl.GetValue())
		else:
			i = ctrl.GetSelection()
			value = values[i] if 0 <= i < len(values) else s.default
		if getDriverSetting(name, s.key, s.default) != value:
			setDriverSetting(name, s.key, value)
			changed.add(name)
	if changed:
		queue_handler.queueFunction(_applyDriverSettings, changed)


def applyDisplayChanges(keys: set[str]) -> None:
	"""Aplica los cambios de la sección ``brailleDisplays`` (detección y BRLTTY)."""
	if keys & {"detectBluetooth", "detectGenericUsb"}:
		queue_handler.queueFunction(_rescan)
	if "brlapiServer" in keys:
		queue_handler.queueFunction(_reconnectBrltty)


def _applyDriverSettings(names: set[str]) -> None:
	"""Hilo del núcleo: la línea activa aplica sus ajustes cambiados."""
	from .. import braille

	display = braille.handler.display
	if display.name in names and hasattr(display, "applySettings"):
		try:
			display.applySettings()
		except Exception:
			log.exception("Error aplicando los ajustes de la línea braille")


def _rescan() -> None:
	from .. import braille

	rescan = getattr(braille.handler.display, "rescan", None)
	if rescan is not None:
		rescan()


def _reconnectBrltty() -> None:
	"""Si BRLTTY está en uso, se reconecta con el servidor nuevo."""
	from .. import braille

	if braille.handler.display.name == "brltty":
		braille.handler.setDisplay("brltty", persist=False, configName=getattr(braille.handler.display, "configName", "brltty"))
