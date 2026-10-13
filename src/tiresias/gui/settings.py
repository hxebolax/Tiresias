"""Diálogo «Opciones» de Tiresias y diálogo de selección de sintetizador.

El diálogo de opciones muestra una lista de categorías a la izquierda y el
panel de la categoría seleccionada a la derecha. Cada panel es una subclase
de :class:`SettingsPanel`. La mayoría de paneles se describen de forma
declarativa con una lista de campos (:class:`Field`) mediante
:class:`ConfigPanel`, que crea los controles, lee los valores de la
configuración y escribe solo los que el usuario ha cambiado.

Los complementos pueden añadir sus propias categorías::

	from tiresias.gui import settings

	class MiPanel(settings.ConfigPanel):
		section = "miComplemento"
		fields = [settings.Field("activo", "Activar mi complemento", default=True)]

	settings.registerPanel("miComplemento", "Mi complemento", MiPanel)

Todas las funciones públicas deben llamarse desde el hilo de la interfaz.
"""

from __future__ import annotations

import copy
import os
import sys
import threading
from collections import OrderedDict
from dataclasses import dataclass, field as dcField
from typing import Any, Callable, Iterable, Sequence

import wx

from .. import APP_NAME, paths, queue_handler, winapi
from ..config import conf
from ..i18n import _
from ..log import getLogger
from . import context_help as _contextHelp
from . import message_dialog

log = getLogger("gui.settings")

ChoiceList = Sequence[tuple[Any, str]]


# ====================================================================== utilidades
def parentWindow() -> wx.Window | None:
	"""Ventana principal de la aplicación (padre de los diálogos), si existe."""
	app = wx.GetApp()
	if app is None:
		return None
	try:
		top = app.GetTopWindow()
	except Exception:
		top = None
	return top or None


def presentDialog(dlg: wx.TopLevelWindow) -> None:
	"""Muestra un diálogo no modal y lo trae al primer plano."""
	if not dlg.IsShown():
		dlg.Show()
	if dlg.IsIconized():
		dlg.Iconize(False)
	dlg.Raise()
	try:
		winapi.setForegroundWindow(dlg.GetHandle())
	except Exception:
		log.debug("No se pudo traer el diálogo al primer plano", exc_info=True)


def isAlive(win: Any) -> bool:
	"""``True`` si ``win`` es una ventana wx que no ha sido destruida."""
	try:
		return bool(win) and not win.IsBeingDeleted()
	except Exception:
		return False


def runOnCore(func: Callable, *args: Any, callback: Callable[[Any], None] | None = None) -> None:
	"""Ejecuta ``func`` en el hilo del núcleo y, si se indica, entrega su
	resultado a ``callback`` en el hilo de la interfaz (con ``wx.CallAfter``).

	Si ``func`` falla, ``callback`` recibe ``None``.
	"""

	def job() -> None:
		try:
			result = func(*args)
		except Exception:
			log.exception("Error ejecutando %r en el núcleo", func)
			result = None
		if callback is not None:
			wx.CallAfter(callback, result)

	queue_handler.queueFunction(job)


def runInThread(func: Callable, *args: Any, callback: Callable[[Any, BaseException | None], None] | None = None, name: str = "TiresiasOpciones") -> threading.Thread:
	"""Ejecuta ``func`` en un hilo propio (procesos, UAC, disco lento) y entrega
	``(resultado, excepción)`` a ``callback`` en el hilo de la interfaz."""

	def job() -> None:
		result: Any = None
		error: BaseException | None = None
		try:
			result = func(*args)
		except Exception as e:
			log.debug("Error ejecutando %r en un hilo propio", func, exc_info=True)
			error = e
		if callback is not None:
			wx.CallAfter(callback, result, error)

	thread = threading.Thread(target=job, name=name, daemon=True)
	thread.start()
	return thread


def showError(message: str, parent: wx.Window | None = None, caption: str | None = None) -> None:
	# Cuadro propio de Tiresias: texto recorrible y copiable (#258).
	message_dialog.messageBox(message, caption or _("Error"), wx.OK | wx.ICON_ERROR, parent)


def askYesNo(message: str, caption: str, parent: wx.Window | None = None) -> bool:
	return message_dialog.messageBox(message, caption, wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, parent) == wx.YES


def speakMessageOnCore(text: str) -> None:
	"""Anuncia un mensaje con la voz de Tiresias (encolado en el núcleo)."""

	def speak() -> None:
		from .. import speech

		speech.speakMessage(text)

	queue_handler.queueFunction(speak)


# ====================================================================== constructor de controles
class SettingsBuilder:
	"""Crea controles precedidos de su etiqueta, en el orden de tabulación correcto.

	Cada control se crea justo después de su :class:`wx.StaticText`, ambos
	con el mismo padre, para que los lectores de pantalla asocien la etiqueta.
	"""

	def __init__(self, parent: wx.Window, sizer: wx.Sizer) -> None:
		self.parent = parent
		self.sizer = sizer

	def addLabeledControl(
		self,
		label: str,
		factory: Callable[[wx.Window], wx.Window],
		vertical: bool = False,
		expand: bool = False,
		proportion: int = 0,
	) -> wx.Window:
		text = wx.StaticText(self.parent, label=label)
		ctrl = factory(self.parent)
		if vertical:
			box = wx.BoxSizer(wx.VERTICAL)
			box.Add(text, 0, wx.BOTTOM, 2)
			box.Add(ctrl, 1 if proportion else 0, wx.EXPAND)
			self.sizer.Add(box, proportion, wx.EXPAND | wx.BOTTOM, 6)
		else:
			row = wx.BoxSizer(wx.HORIZONTAL)
			row.Add(text, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
			row.Add(ctrl, 1 if expand else 0, wx.ALIGN_CENTER_VERTICAL)
			self.sizer.Add(row, 0, wx.EXPAND | wx.BOTTOM, 4)
		return ctrl

	def addCheckBox(self, label: str, value: bool = False) -> wx.CheckBox:
		ctrl = wx.CheckBox(self.parent, label=label)
		ctrl.SetValue(bool(value))
		self.sizer.Add(ctrl, 0, wx.BOTTOM, 4)
		return ctrl

	def addChoice(self, label: str, items: Iterable[str], selection: int = 0) -> wx.Choice:
		items = list(items)
		ctrl = self.addLabeledControl(label, lambda p: wx.Choice(p, choices=items))
		if items:
			ctrl.SetSelection(max(0, min(selection, len(items) - 1)))
		return ctrl  # type: ignore[return-value]

	def addSpin(self, label: str, minVal: int, maxVal: int, value: int) -> wx.SpinCtrl:
		value = max(minVal, min(maxVal, int(value)))
		return self.addLabeledControl(  # type: ignore[return-value]
			label, lambda p: wx.SpinCtrl(p, min=minVal, max=maxVal, initial=value, style=wx.SP_ARROW_KEYS)
		)

	def addSlider(self, label: str, minVal: int, maxVal: int, value: int, lineSize: int = 1, pageSize: int = 10) -> wx.Slider:
		value = max(minVal, min(maxVal, int(value)))
		ctrl = self.addLabeledControl(label, lambda p: wx.Slider(p, value=value, minValue=minVal, maxValue=maxVal, size=(250, -1)))
		ctrl.SetLineSize(max(1, int(lineSize)))
		ctrl.SetPageSize(max(1, int(pageSize)))
		return ctrl  # type: ignore[return-value]

	def addText(self, label: str, value: str = "", style: int = 0, size: tuple[int, int] = (250, -1)) -> wx.TextCtrl:
		return self.addLabeledControl(label, lambda p: wx.TextCtrl(p, value=value, style=style, size=size))  # type: ignore[return-value]

	def addButton(self, label: str) -> wx.Button:
		ctrl = wx.Button(self.parent, label=label)
		self.sizer.Add(ctrl, 0, wx.BOTTOM, 4)
		return ctrl

	def addStaticText(self, text: str) -> wx.StaticText:
		ctrl = wx.StaticText(self.parent, label=text)
		self.sizer.Add(ctrl, 0, wx.BOTTOM, 4)
		return ctrl

	def group(self, label: str) -> "SettingsBuilder":
		"""Crea un grupo con título (los controles se crean dentro del grupo)."""
		box = wx.StaticBoxSizer(wx.VERTICAL, self.parent, label)
		self.sizer.Add(box, 0, wx.EXPAND | wx.BOTTOM, 8)
		return SettingsBuilder(box.GetStaticBox(), box)


# ====================================================================== paneles
class SettingsPanel(wx.Panel):
	"""Clase base de los paneles del diálogo de opciones.

	Las subclases implementan :meth:`makeSettings` (crear controles),
	:meth:`onSave` (guardar en la configuración), :meth:`onDiscard` (deshacer
	cambios aplicados en vivo) y, opcionalmente, :meth:`isValid`.
	"""

	#: Título de la categoría (lo fija :func:`registerPanel` si no se indica).
	title = ""

	def __init__(self, parent: wx.Window) -> None:
		super().__init__(parent)
		self.mainSizer = wx.BoxSizer(wx.VERTICAL)
		self.settingsSizer = wx.BoxSizer(wx.VERTICAL)
		self.makeSettings(self.settingsSizer)
		self.mainSizer.Add(self.settingsSizer, 1, wx.EXPAND | wx.ALL, 8)
		self.SetSizer(self.mainSizer)

	def makeSettings(self, sizer: wx.BoxSizer) -> None:
		raise NotImplementedError

	def onSave(self) -> None:
		"""Guarda los valores en ``conf``. Se llama al pulsar Aceptar o Aplicar."""

	def onDiscard(self) -> None:
		"""Deshace los cambios aplicados en vivo. Se llama al cancelar."""

	def resetToFactory(self) -> None:
		"""Pone los controles de la categoría con los valores de fábrica.

		Solo cambia los controles: se guardan al pulsar Aceptar o Aplicar, y
		Cancelar los descarta. Los paneles sin opciones propias no hacen nada.
		"""

	def isValid(self) -> bool:
		"""``False`` impide guardar (el panel debe explicar el motivo)."""
		return True

	def onPanelActivated(self) -> None:
		self.Show()

	def onPanelDeactivated(self) -> None:
		self.Hide()

	def relayout(self) -> None:
		"""Recalcula la disposición tras añadir o quitar controles."""
		self.Layout()
		dlg = wx.GetTopLevelParent(self)
		if isinstance(dlg, SettingsDialog):
			dlg.relayoutContainer()


@dataclass
class Field:
	"""Descripción declarativa de un ajuste de la configuración.

	``kind`` puede ser ``bool`` (casilla), ``int`` (cuadro numérico),
	``slider`` (control deslizante), ``choice`` (lista desplegable), ``text``
	(cuadro de texto) o ``list`` (texto con valores separados por comas).
	"""

	key: str
	label: str
	kind: str = "bool"
	minVal: int = 0
	maxVal: int = 100
	choices: ChoiceList | Callable[[], ChoiceList] | None = None
	section: str | None = None
	group: str | None = None
	default: Any = None
	lineSize: int = 1
	pageSize: int = 10
	readOnly: bool = False


def Bool(key: str, label: str, **kw: Any) -> Field:
	return Field(key, label, "bool", **kw)


def Int(key: str, label: str, minVal: int, maxVal: int, **kw: Any) -> Field:
	return Field(key, label, "int", minVal=minVal, maxVal=maxVal, **kw)


def Slider(key: str, label: str, minVal: int = 0, maxVal: int = 100, **kw: Any) -> Field:
	return Field(key, label, "slider", minVal=minVal, maxVal=maxVal, **kw)


def Choice(key: str, label: str, choices: ChoiceList | Callable[[], ChoiceList], **kw: Any) -> Field:
	return Field(key, label, "choice", choices=choices, **kw)


def Text(key: str, label: str, **kw: Any) -> Field:
	return Field(key, label, "text", **kw)


def ListText(key: str, label: str, **kw: Any) -> Field:
	return Field(key, label, "list", **kw)


@dataclass
class _Bound:
	field: Field
	section: str
	ctrl: wx.Window
	original: Any
	values: list = dcField(default_factory=list)


def _confValue(section: str, key: str, default: Any = None) -> Any:
	try:
		value = conf[section][key]
	except KeyError:
		return default
	if isinstance(value, list):
		return list(value)
	return value


class ConfigPanel(SettingsPanel):
	"""Panel construido a partir de una lista de :class:`Field`.

	Las subclases indican ``section`` (sección por defecto de ``conf``) y
	``fields`` (o sobrescriben :meth:`getFields`). Pueden añadir controles
	propios en :meth:`makeHeaderSettings` / :meth:`makeExtraSettings` y
	reaccionar a los cambios guardados en :meth:`afterSave`.
	"""

	section = ""
	fields: list[Field] = []

	def getFields(self) -> list[Field]:
		return list(self.fields)

	def makeHeaderSettings(self, builder: SettingsBuilder) -> None:
		"""Controles adicionales antes de los campos declarativos."""

	def makeExtraSettings(self, builder: SettingsBuilder) -> None:
		"""Controles adicionales después de los campos declarativos."""

	def afterSave(self, changes: dict[tuple[str, str], tuple[Any, Any]]) -> None:
		"""Se llama tras guardar con los cambios ``{(sección, clave): (antes, después)}``."""

	def makeSettings(self, sizer: wx.BoxSizer) -> None:
		self._bound: dict[tuple[str, str], _Bound] = {}
		root = SettingsBuilder(self, sizer)
		self.makeHeaderSettings(root)
		groups: dict[str, SettingsBuilder] = {}
		for f in self.getFields():
			builder = root
			if f.group:
				builder = groups.get(f.group) or groups.setdefault(f.group, root.group(f.group))
			self._addField(builder, f)
		#: Grupos creados por título (para añadir controles propios a un grupo de campos).
		self._groups = groups
		self.makeExtraSettings(root)

	# --------------------------------------------------- campos
	def _addField(self, builder: SettingsBuilder, f: Field) -> None:
		section = f.section or self.section
		value = _confValue(section, f.key, f.default)
		values: list = []
		if f.kind == "bool":
			ctrl: wx.Window = builder.addCheckBox(f.label, bool(value))
		elif f.kind == "int":
			try:
				iv = int(value)
			except (TypeError, ValueError):
				iv = f.minVal
			ctrl = builder.addSpin(f.label, f.minVal, f.maxVal, iv)
		elif f.kind == "slider":
			try:
				iv = int(value)
			except (TypeError, ValueError):
				iv = f.minVal
			ctrl = builder.addSlider(f.label, f.minVal, f.maxVal, iv, f.lineSize, f.pageSize)
		elif f.kind == "choice":
			choices = f.choices() if callable(f.choices) else (f.choices or [])
			choices = list(choices)
			values = [v for v, _l in choices]
			labels = [lbl for _v, lbl in choices]
			if value not in values:
				# Valor desconocido (p. ej. un dispositivo desconectado): se conserva.
				values.append(value)
				labels.append(str(value) if value not in (None, "") else _("(sin valor)"))
			ctrl = builder.addChoice(f.label, labels, values.index(value))
		elif f.kind in ("text", "list"):
			text = ", ".join(str(v) for v in value) if f.kind == "list" and isinstance(value, (list, tuple)) else ("" if value is None else str(value))
			style = wx.TE_READONLY if f.readOnly else 0
			ctrl = builder.addText(f.label, text, style=style)
		elif f.kind == "checklist":
			# Lista de casillas: el valor es la lista de valores marcados.
			choices = list(f.choices() if callable(f.choices) else (f.choices or []))
			values = [v for v, _l in choices]
			current = list(value or [])
			ctrl = builder.addLabeledControl(f.label, lambda p: wx.CheckListBox(p, choices=[lbl for _v, lbl in choices], size=(300, -1)), vertical=True)
			for i, v in enumerate(values):
				ctrl.Check(i, v in current)
		else:
			raise ValueError(f"Tipo de campo desconocido: {f.kind}")
		if conf.isLocked(section, f.key):
			# Opción fijada por la política del equipo: se muestra pero no se puede cambiar.
			ctrl.Enable(False)
			ctrl.SetToolTip(_("Bloqueada por el administrador del equipo"))
			if isinstance(ctrl, wx.CheckBox):
				ctrl.SetLabel(ctrl.GetLabel() + " " + _("(bloqueada)"))
		self._bound[(section, f.key)] = _Bound(f, section, ctrl, value, values)

	def _readControl(self, b: _Bound) -> Any:
		ctrl = b.ctrl
		kind = b.field.kind
		if kind == "bool":
			return ctrl.GetValue()
		if kind in ("int", "slider"):
			return int(ctrl.GetValue())
		if kind == "choice":
			i = ctrl.GetSelection()
			return b.values[i] if 0 <= i < len(b.values) else b.original
		if kind == "list":
			return [p.strip() for p in ctrl.GetValue().split(",") if p.strip()]
		if kind == "checklist":
			return [v for i, v in enumerate(b.values) if ctrl.IsChecked(i)]
		return ctrl.GetValue()

	def fieldForControl(self, ctrl: wx.Window) -> tuple[str, str] | None:
		"""(sección, clave) de la opción a la que pertenece ``ctrl`` (ayuda F1)."""
		for key, b in self._bound.items():
			if b.ctrl is ctrl:
				return key
		# Controles propios con ayuda (``self._helpKeys[control] = (sección, clave)``).
		return getattr(self, "_helpKeys", {}).get(ctrl)

	def getControl(self, key: str, section: str | None = None) -> wx.Window | None:
		b = self._bound.get((section or self.section, key))
		return b.ctrl if b else None

	def getValue(self, key: str, section: str | None = None) -> Any:
		b = self._bound.get((section or self.section, key))
		return self._readControl(b) if b else None

	def lockControls(self, section: str, keys: str | Sequence[str], *ctrls: wx.Window) -> bool:
		"""Controles propios de opciones fijadas por la política: se desactivan
		(como los campos declarativos). Devuelve ``True`` si alguna está bloqueada."""
		keys = [keys] if isinstance(keys, str) else list(keys)
		if not any(conf.isLocked(section, k) for k in keys):
			return False
		for ctrl in ctrls:
			ctrl.Enable(False)
			ctrl.SetToolTip(_("Bloqueada por el administrador del equipo"))
		return True

	def updateChoices(self, key: str, choices: ChoiceList, section: str | None = None) -> None:
		"""Sustituye las opciones de una lista desplegable (p. ej. cuando llegan
		del núcleo o de un hilo) conservando el valor elegido aunque no esté."""
		b = self._bound.get((section or self.section, key))
		if not b or b.field.kind != "choice":
			return
		current = self._readControl(b)
		values = [v for v, _l in choices]
		labels = [lbl for _v, lbl in choices]
		if current not in values:
			values.append(current)
			labels.append(str(current) if current not in (None, "") else _("(sin valor)"))
		if values == b.values and labels == list(b.ctrl.GetStrings()):
			return
		b.values = values
		b.ctrl.Set(labels)
		b.ctrl.SetSelection(values.index(current))

	def setControlValue(self, key: str, value: Any, section: str | None = None) -> None:
		b = self._bound.get((section or self.section, key))
		if not b:
			return
		kind = b.field.kind
		if kind == "bool":
			b.ctrl.SetValue(bool(value))
		elif kind in ("int", "slider"):
			b.ctrl.SetValue(int(value))
		elif kind == "choice" and value in b.values:
			b.ctrl.SetSelection(b.values.index(value))
		elif kind == "list":
			b.ctrl.SetValue(", ".join(str(v) for v in value or []))
		elif kind == "checklist":
			for i, v in enumerate(b.values):
				b.ctrl.Check(i, v in (value or []))
		elif kind == "text":
			b.ctrl.SetValue("" if value is None else str(value))

	@staticmethod
	def factoryValue(section: str, key: str, default: Any = None) -> Any:
		"""Valor de fábrica de una opción (el registrado con los valores por defecto)."""
		values = conf.defaults.get(section)
		if isinstance(values, dict) and key in values:
			return copy.deepcopy(values[key])
		return copy.deepcopy(default)

	def resetToFactory(self) -> None:
		for (section, key), b in self._bound.items():
			if b.field.readOnly or conf.isLocked(section, key):
				continue
			self.setControlValue(key, self.factoryValue(section, key, b.field.default), section)
		self.resetExtraToFactory()

	def resetExtraToFactory(self) -> None:
		"""Valores de fábrica de los controles propios del panel (no declarativos)."""

	def onSave(self) -> None:
		changes: dict[tuple[str, str], tuple[Any, Any]] = {}
		for (section, key), b in self._bound.items():
			if b.field.readOnly or conf.isLocked(section, key):
				continue
			new = self._readControl(b)
			if new != b.original:
				conf[section][key] = new
				changes[(section, key)] = (b.original, new)
				b.original = new
		if changes:
			self.afterSave(changes)


# ====================================================================== listas de opciones
def _speechModeChoices() -> ChoiceList:
	return [("talk", _("Hablar")), ("onDemand", _("A demanda")), ("beeps", _("Pitidos")), ("off", _("Desactivada"))]


def _symbolLevelChoices() -> ChoiceList:
	from ..speech import symbols

	return [(lvl, symbols.LEVEL_NAMES[lvl]) for lvl in symbols.SPEECH_LEVELS]


_TYPED_CHOICES: ChoiceList = [("off", _("No")), ("always", _("Siempre")), ("editOnly", _("Solo en campos de edición"))]
_LOG_LEVELS: ChoiceList = [("DEBUG", _("Depuración")), ("INFO", _("Información")), ("WARNING", _("Advertencias")), ("ERROR", _("Errores")), ("CRITICAL", _("Solo errores graves")), ("OFF", _("Desactivado"))]
_LAYOUTS: ChoiceList = [("desktop", _("Sobremesa")), ("laptop", _("Portátil"))]
_TEXT_UNITS: ChoiceList = [("character", _("Carácter")), ("word", _("Palabra")), ("line", _("Línea")), ("paragraph", _("Párrafo"))]
_PROGRESS_MODES: ChoiceList = [("off", _("Desactivado")), ("speak", _("Voz")), ("beep", _("Pitidos")), ("both", _("Voz y pitidos"))]
_VERBOSITY: ChoiceList = [("beginner", _("Principiante")), ("normal", _("Intermedio")), ("expert", _("Experto"))]
_MAXLEN_WARNING_CHOICES: ChoiceList = [
	("off", _("Desactivado")),
	("threshold", _("Al acercarse al límite y al llegar a él")),
	("countdown", _("Cuenta atrás: cada carácter cerca del límite")),
]
_INDENTATION: ChoiceList = [("off", _("Desactivado")), ("speech", _("Voz")), ("tones", _("Tonos")), ("both", _("Voz y tonos"))]
_BRAILLE_MESSAGES: ChoiceList = [("disabled", _("Desactivados")), ("timeout", _("Usar tiempo de espera")), ("always", _("Mostrar indefinidamente"))]
_BRAILLE_TETHER: ChoiceList = [("auto", _("Automáticamente")), ("focus", _("Al foco")), ("review", _("A la revisión"))]
_BRAILLE_CONTEXT: ChoiceList = [
	("fill", _("Rellenar la línea con el contexto")),
	("changedContext", _("Mostrar solo el contexto que cambia")),
	("scroll", _("Mostrar el contexto solo al desplazar hacia atrás")),
]
_CURSOR_SHAPES: ChoiceList = [
	(0x40, _("Punto 7")),
	(0x80, _("Punto 8")),
	(0xC0, _("Puntos 7 y 8")),
	(0xFF, _("Todos los puntos")),
]


def _audioDeviceChoices() -> ChoiceList:
	items: list[tuple[Any, str]] = [("", _("Predeterminado de Windows"))]
	try:
		from ..audio import wave_player

		items += [(name, name) for name in wave_player.getOutputDevices()]
	except Exception:
		log.exception("No se pudieron obtener los dispositivos de audio")
	return items


def _soundSplitChoices() -> ChoiceList:
	try:
		from ..audio import sound_split

		return [(k, v[2]) for k, v in sound_split.MODES.items()]
	except Exception:
		log.exception("División de sonido no disponible")
		return [("off", _("División de sonido desactivada"))]


def _duckingChoices() -> ChoiceList:
	try:
		from ..audio import ducking

		return list(ducking.MODES.items())
	except Exception:
		log.exception("Atenuación no disponible")
		return [("off", _("Sin atenuación de otras aplicaciones"))]


def _brailleTableChoices() -> ChoiceList:
	try:
		from ..braille import tables

		return list(tables.listTables(forInput=False, includeAuto=True))
	except Exception:
		log.exception("No se pudo obtener la lista de tablas braille")
		return []


def _brailleInputTableChoices() -> ChoiceList:
	try:
		from ..braille import tables

		return list(tables.listTables(forInput=True, includeAuto=True))
	except Exception:
		log.exception("No se pudo obtener la lista de tablas braille de entrada")
		return []


_BRAILLE_MODES: ChoiceList = [("followCursors", _("Seguir a los cursores")), ("speechOutput", _("Mostrar lo que se dice (voz)"))]
_BRAILLE_TEXT_WRAP: ChoiceList = [
	("none", _("Desactivado (cortar en cualquier celda)")),
	("markWordCuts", _("Marcar con los puntos 7 y 8 las palabras cortadas")),
	("wordBoundaries", _("En los límites de palabra")),
	("syllableBoundaries", _("En los límites de palabra o de sílaba")),
]


def _ocrLanguageChoices() -> ChoiceList:
	items: list[tuple[Any, str]] = [("", _("Automático (idioma del sistema)"))]
	try:
		from .. import ocr

		items += [(lang, lang) for lang in ocr.availableLanguages()]
	except Exception:
		log.debug("No se pudieron obtener los idiomas de OCR", exc_info=True)
	return items


# ====================================================================== inicio con Windows y accesos directos
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = APP_NAME


def launchCommand() -> tuple[str, str]:
	"""Ejecutable y argumentos para iniciar Tiresias: ``(exe, args)``."""
	if paths.FROZEN:
		exe = sys.executable
		args = ""
	else:
		pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
		exe = pyw if os.path.isfile(pyw) else sys.executable
		args = f'"{os.path.join(paths.SOURCE_DIR, "tiresias.pyw")}"'
	defaultData = os.path.normcase(os.path.abspath(os.path.join(paths.APP_DIR, "data")))
	if os.path.normcase(os.path.abspath(paths.DATA_DIR)) != defaultData and not os.environ.get("TIRESIAS_DATA"):
		args = f'{args} --data "{paths.DATA_DIR}"'.strip()
	return exe, args


def launchCommandLine() -> str:
	exe, args = launchCommand()
	return f'"{exe}" {args}'.strip()


def isStartOnLogonEnabled() -> bool:
	import winreg

	try:
		with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
			winreg.QueryValueEx(key, _RUN_VALUE)
			return True
	except OSError:
		return False


def setStartOnLogon(enable: bool) -> None:
	"""Crea o elimina el valor ``Tiresias`` de la clave ``Run`` del usuario."""
	import winreg

	with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
		if enable:
			winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ, launchCommandLine())
		else:
			try:
				winreg.DeleteValue(key, _RUN_VALUE)
			except FileNotFoundError:
				pass


def applySecureScreens(enable: bool, onDone: Callable[[bool], None] | None = None) -> threading.Thread:
	"""Activa o desactiva el uso de Tiresias en el inicio de sesión y las pantallas seguras.

	Al activarlo se guarda la configuración y se copia a la del sistema. Puede
	pedir permiso de administrador (Control de cuentas de usuario): va en un
	hilo propio. ``onDone(estado)`` recibe en la interfaz el estado final.
	"""
	from .. import secure_screens
	from ..config import policy as policyModule

	source = None
	if enable:
		if not conf.readOnly and policyModule.isAllowed("saveConfiguration"):
			try:
				conf.save()
			except OSError:
				log.exception("No se pudo guardar la configuración antes de copiarla al sistema")
		source = paths.configDir()

	def done(result: Any, error: BaseException | None) -> None:
		if error is not None:
			log.error("Pantallas seguras: %s", error)
			state = secure_screens.isEnabled()
			showError(_("No se pudo cambiar el uso de Tiresias en el inicio de sesión y las pantallas seguras: {error}").format(error=error))
		else:
			state = bool(enable)
			if state:
				speakMessageOnCore(_("Tiresias se usará en el inicio de sesión y en las pantallas seguras"))
			else:
				speakMessageOnCore(_("Tiresias ya no se usará en el inicio de sesión ni en las pantallas seguras"))
		if not conf.readOnly:
			conf["general"]["startOnLogonScreen"] = state
		if onDone is not None:
			onDone(state)

	return runInThread(secure_screens.setEnabled, bool(enable), source, callback=done, name="TiresiasPantallasSeguras")


def createShortcut(path: str, hotkey: str = "CTRL+ALT+T") -> None:
	"""Crea un acceso directo (.lnk) a Tiresias con la tecla rápida indicada."""
	import comtypes.client

	shell = comtypes.client.CreateObject("WScript.Shell", dynamic=True)
	exe, args = launchCommand()
	sc = shell.CreateShortcut(path)
	sc.TargetPath = exe
	sc.Arguments = args
	sc.WorkingDirectory = paths.APP_DIR if paths.FROZEN else paths.SOURCE_DIR
	sc.Description = _("{app}: lector de pantalla").format(app=APP_NAME)
	sc.Hotkey = hotkey
	if paths.FROZEN:
		sc.IconLocation = f"{sys.executable},0"
	sc.Save()


def desktopShortcutPath() -> str:
	import comtypes.client

	shell = comtypes.client.CreateObject("WScript.Shell", dynamic=True)
	desktop = shell.SpecialFolders("Desktop")
	return os.path.join(str(desktop), f"{APP_NAME}.lnk")


def _languageChoices() -> ChoiceList:
	"""«Automático» y los idiomas con traducción (cada uno con su nombre en su idioma)."""
	from .. import i18n

	auto = _("Automático (idioma de Windows: {lang})").format(lang=i18n.languageNativeName(i18n.resolveLanguage("auto")))
	items: list[tuple[Any, str]] = [("auto", auto)]
	for lang in i18n.availableLanguages():
		items.append((lang, f"{i18n.languageNativeName(lang)} ({lang})"))
	return items


def _askRestartForLanguage() -> None:
	"""El idioma de la interfaz se aplica al reiniciar."""
	if askYesNo(
		_("El nuevo idioma de la interfaz se usará al reiniciar Tiresias. ¿Reiniciar ahora?"),
		_("Idioma de la interfaz"),
		parentWindow(),
	):
		from .. import core

		try:
			conf.save()
		except OSError:
			log.exception("No se pudo guardar antes de reiniciar")
		queue_handler.queueFunction(core.restart)


def _coexistReaderChoices() -> ChoiceList:
	from .. import coexist

	return coexist.readerChoices()


def _coexistDefaultReaders() -> list:
	from .. import coexist

	return list(coexist.DEFAULTS["readers"])


# ====================================================================== paneles incorporados
class GeneralPanel(ConfigPanel):
	title = _("Generales")
	section = "general"

	def getFields(self) -> list[Field]:
		gs = _("Inicio y salida")
		return [
			Choice("language", _("Idioma de la interfaz (requiere reiniciar):"), _languageChoices),
			Choice("logLevel", _("Nivel del registro:"), _LOG_LEVELS),
			Bool("preventDisplayTurningOff", _("Impedir que la pantalla se apague durante la lectura continua")),
			Bool("startOnLogon", _("Iniciar Tiresias automáticamente al iniciar sesión en Windows"), group=gs),
			Bool("showWelcomeDialogAtStartup", _("Mostrar el diálogo de bienvenida al iniciar"), group=gs),
			Bool("announceStartup", _("Anunciar el inicio de Tiresias"), group=gs),
			Bool("playStartAndExitSounds", _("Reproducir sonidos al iniciar y salir"), group=gs),
			Bool("showNewsAfterUpdate", _("Avisar de las novedades después de una actualización"), group=gs),
			Bool("askToExit", _("Mostrar opciones de salida al cerrar Tiresias"), group=gs),
			Bool("saveConfigurationOnExit", _("Guardar la configuración al salir"), group=gs),
			# El modo dormir por configuración está en «Aplicaciones», junto al permanente.
			# Convivencia: con otro lector activo, Tiresias pasa a espera (ver tiresias.coexist).
			Bool("yieldToOtherReaders", _("C&eder ante otros lectores de pantalla (NVDA, JAWS, Narrador)"), section="coexist", group=_("Otros lectores de pantalla"), default=True),
			Field("readers", _("Lectores ante los que Tiresias pasa a espera:"), "checklist", choices=_coexistReaderChoices, section="coexist", group=_("Otros lectores de pantalla"), default=_coexistDefaultReaders()),
			# Guardián: el usuario nunca se queda sin lector (ver tiresias.coexist.guardian).
			Bool("relaunchOnExit", _("Al cerrar Tiresias o si falla, iniciar el &lector de pantalla que estaba activo"), section="coexist", group=_("Otros lectores de pantalla"), default=True),
			Bool("relaunchOnHang", _("Iniciarlo también si Tiresias deja de &responder"), section="coexist", group=_("Otros lectores de pantalla"), default=True),
			Int("hangTimeout", _("Segundos sin responder antes de iniciarlo:"), 5, 600, section="coexist", group=_("Otros lectores de pantalla"), default=20),
		]

	def makeExtraSettings(self, builder: SettingsBuilder) -> None:
		# La casilla muestra lo que hay de verdad en el registro (clave Run del
		# usuario), no solo lo que dice la configuración. Si no coinciden, al
		# Aceptar se escribe en conf (el valor original sigue siendo el de conf).
		if self.getControl("startOnLogon", "general") is not None and not conf.isLocked("general", "startOnLogon"):
			self.setControlValue("startOnLogon", isStartOnLogonEnabled(), "general")
		self._makeRememberedReader(self._groups.get(_("Otros lectores de pantalla")) or builder)
		btn = builder.addButton(_("Crear acceso &directo en el escritorio (Control+Alt+T)"))
		btn.Bind(wx.EVT_BUTTON, self._onCreateShortcut)
		g = builder.group(_("Inicio de sesión, pantallas seguras y configuración del sistema"))
		self._makeSecureScreens(g)
		g.addStaticText(_("La configuración del sistema la usa Tiresias en el inicio de sesión, en las pantallas seguras y cuando se inicia con --secure."))
		btn = g.addButton(_("Copiar la configuración actual a la del &sistema..."))
		btn.Bind(wx.EVT_BUTTON, self._onCopyToSystem)
		self._copySystemButton = btn
		btn = g.addButton(_("&Quitar la configuración del sistema"))
		btn.Bind(wx.EVT_BUTTON, self._onRemoveSystem)
		btn.Enable(os.path.isdir(paths.SYSTEM_CONFIG_DIR))
		self._removeSystemButton = btn
		g = builder.group(_("Configuración de NVDA"))
		g.addStaticText(_("Usa en Tiresias los mismos ajustes que en NVDA. Se guardan los cambios de este diálogo y se abre el importador."))
		btn = g.addButton(_("&Importar la configuración de NVDA..."))
		btn.Bind(wx.EVT_BUTTON, self._onImportNvda)
		btn.Enable(not conf.readOnly)

	# --------------------------------------------------- inicio de sesión y pantallas seguras
	def _makeSecureScreens(self, g: SettingsBuilder) -> None:
		"""Casilla «Usar Tiresias durante el inicio de sesión…» (ver tiresias.secure_screens).

		Muestra lo que hay en el registro de Windows (HKLM), no solo la
		configuración. Solo se puede cambiar en la copia instalada en Archivos de
		programa; en las demás aparece desactivada con el motivo.
		"""
		from .. import secure_screens

		self._helpKeys = getattr(self, "_helpKeys", {})
		available, reason = secure_screens.availability()
		enabled = secure_screens.isEnabled()
		label = _("&Usar Tiresias durante el inicio de sesión y en las pantallas seguras (requiere permiso de administrador)")
		if not available:
			secure = secure_screens.runningOnSecureScreen() or secure_screens._secureMode()
			label += " " + (_("(no disponible en modo seguro)") if secure else _("(solo en la copia instalada)"))
		cb = g.addCheckBox(label, enabled)
		self._secureScreensCheck = cb
		self._secureScreensOriginal = enabled
		self._helpKeys[cb] = ("general", "startOnLogonScreen")
		if not available:
			cb.Enable(False)
			cb.SetToolTip(reason)
			self._secureScreensInfo = g.addStaticText(reason)
		elif not self.lockControls("general", "startOnLogonScreen", cb):
			self._secureScreensInfo = g.addStaticText(
				_(
					"Windows iniciará Tiresias en la pantalla de inicio de sesión, en el Control de cuentas de usuario y en "
					"Control+Alt+Supr, siempre en modo seguro. Al activarla se copia también la configuración actual a la del sistema."
				)
			)

	def _saveSecureScreens(self) -> None:
		cb = getattr(self, "_secureScreensCheck", None)
		if cb is None or not cb.IsEnabled() or conf.isLocked("general", "startOnLogonScreen"):
			return
		want = bool(cb.GetValue())
		if want == self._secureScreensOriginal:
			# Sin cambios: la configuración refleja lo que hay en el registro.
			if not conf.readOnly and conf["general"]["startOnLogonScreen"] != want:
				conf["general"]["startOnLogonScreen"] = want
			return
		self._secureScreensOriginal = want
		panel = self

		def done(state: bool) -> None:
			if isAlive(panel):
				panel._secureScreensOriginal = state
				panel._secureScreensCheck.SetValue(state)

		# Tras guardar todas las categorías: la configuración que se copia es la nueva.
		wx.CallAfter(applySecureScreens, want, done)

	def onSave(self) -> None:
		super().onSave()
		self._saveSecureScreens()

	# --------------------------------------------------- lector recordado (coexist.relaunch)
	def _makeRememberedReader(self, g: SettingsBuilder) -> None:
		self._helpKeys = getattr(self, "_helpKeys", {})
		self._rememberedText = g.addText(_("Lector de pantalla recordado:"), self._rememberedReaderText(), style=wx.TE_READONLY, size=(420, -1))
		self._forgetButton = g.addButton(_("&Olvidar el lector recordado"))
		self._forgetButton.Bind(wx.EVT_BUTTON, self._onForgetReader)
		self._forgetButton.Enable(self._rememberedReader() is not None)
		for ctrl in (self._rememberedText, self._forgetButton):
			self._helpKeys[ctrl] = ("coexist", "rememberedReader")
		# El tiempo solo cuenta si la casilla «deja de responder» está marcada.
		hang, timeout = self.getControl("relaunchOnHang", "coexist"), self.getControl("hangTimeout", "coexist")
		if isinstance(hang, wx.CheckBox) and timeout is not None:
			def sync(evt=None) -> None:
				timeout.Enable(hang.GetValue() and hang.IsEnabled())
				if evt is not None:
					evt.Skip()

			hang.Bind(wx.EVT_CHECKBOX, sync)
			sync()
			self._syncHang = sync

	def resetExtraToFactory(self) -> None:
		sync = getattr(self, "_syncHang", None)
		if sync is not None:
			sync()

	@staticmethod
	def _rememberedReader() -> dict | None:
		try:
			from ..coexist import relaunch

			return relaunch.loadMemory()["reader"]
		except Exception:
			log.debug("No se pudo leer el lector recordado", exc_info=True)
			return None

	def _rememberedReaderText(self) -> str:
		reader = self._rememberedReader()
		if reader is None:
			return _("Ninguno (Tiresias recuerda el lector que esté activo al arrancar o mientras funciona)")
		from ..coexist import relaunch

		label = relaunch.readerLabel(reader)
		path = reader.get("path") or ""
		return f"{label}: {path}" if path else label

	def _onForgetReader(self, evt: wx.CommandEvent) -> None:
		reader = self._rememberedReader()
		if reader is None:
			return
		from ..coexist import relaunch

		if not askYesNo(
			_("¿Olvidar {reader}? Tiresias no lo iniciará al cerrarse hasta que vuelva a verlo en funcionamiento.").format(reader=relaunch.readerLabel(reader)),
			_("Lector de pantalla recordado"),
			self,
		):
			return
		try:
			relaunch.forgetReader()
		except OSError as e:
			showError(_("No se pudo olvidar el lector recordado: {error}").format(error=e), self)
			return
		self._rememberedText.SetValue(self._rememberedReaderText())
		self._forgetButton.Enable(False)
		self._rememberedText.SetFocus()
		speakMessageOnCore(_("Lector recordado olvidado"))

	def _onImportNvda(self, evt: wx.CommandEvent) -> None:
		# Se cierran las Opciones (guardando) para que no sobrescriban lo importado.
		dlg = self.GetTopLevelParent()
		if isinstance(dlg, SettingsDialog):
			if not dlg._saveAll():
				return
			dlg._finish()
		from .. import gui

		gui.showNvdaImport()

	def _onCopyToSystem(self, evt: wx.CommandEvent) -> None:
		from .. import installer
		from ..config import policy as policyModule

		if getattr(self, "_systemBusy", False):
			return
		if not policyModule.isAllowed("saveConfiguration"):
			showError(policyModule.blockedMessage(), self)
			return
		if not askYesNo(
			_("Se guardará la configuración y se copiará a la carpeta del programa como configuración del sistema. Puede pedir permiso de administrador. ¿Continuar?"),
			_("Configuración del sistema"),
			self,
		):
			return
		try:
			conf.save()
		except OSError as e:
			showError(_("No se pudo copiar la configuración: {error}").format(error=e), self)
			return
		# La copia puede esperar al permiso de administrador (UAC) sin límite:
		# se hace en un hilo propio para no congelar la interfaz.
		self._setSystemButtonsBusy(True)
		runInThread(installer.requestCopyConfigToSystem, callback=self._onCopyToSystemDone, name="TiresiasCopiaSistema")

	def _onCopyToSystemDone(self, result: Any, error: BaseException | None) -> None:
		if not isAlive(self):
			return
		self._setSystemButtonsBusy(False)
		if error is not None:
			showError(_("No se pudo copiar la configuración: {error}").format(error=error), self)
			return
		message_dialog.messageBox(_("La configuración se ha copiado a la configuración del sistema."), _("Configuración del sistema"), wx.OK | wx.ICON_INFORMATION, self)

	def _onRemoveSystem(self, evt: wx.CommandEvent) -> None:
		from .. import installer

		if getattr(self, "_systemBusy", False):
			return
		if not askYesNo(_("¿Quitar la configuración del sistema? El modo seguro usará los valores de fábrica."), _("Configuración del sistema"), self):
			return
		self._setSystemButtonsBusy(True)
		runInThread(installer.removeSystemConfig, callback=self._onRemoveSystemDone, name="TiresiasQuitaSistema")

	def _onRemoveSystemDone(self, result: Any, error: BaseException | None) -> None:
		if not isAlive(self):
			return
		self._setSystemButtonsBusy(False)
		if error is not None:
			showError(_("No se pudo quitar la configuración del sistema: {error}").format(error=error), self)
			return
		speakMessageOnCore(_("Configuración del sistema quitada"))

	def _setSystemButtonsBusy(self, busy: bool) -> None:
		"""Mientras trabaja el hilo se ignoran nuevas pulsaciones (sin desactivar
		el botón con el foco, para no perderlo); al terminar se ajusta «Quitar»."""
		self._systemBusy = busy
		if busy:
			return
		remove = self._removeSystemButton
		enable = os.path.isdir(paths.SYSTEM_CONFIG_DIR)
		if not enable and wx.Window.FindFocus() is remove:
			self._copySystemButton.SetFocus()
		remove.Enable(enable)

	def _onCreateShortcut(self, evt: wx.CommandEvent) -> None:
		try:
			with wx.BusyCursor():
				path = desktopShortcutPath()
				createShortcut(path)
		except Exception as e:
			log.exception("No se pudo crear el acceso directo")
			showError(_("No se pudo crear el acceso directo: {error}").format(error=e), self)
			return
		message_dialog.messageBox(
			_("Se ha creado el acceso directo en el escritorio. Puede iniciar Tiresias con Control+Alt+T."),
			_("Acceso directo creado"),
			wx.OK | wx.ICON_INFORMATION,
			self,
		)

	def afterSave(self, changes: dict[tuple[str, str], tuple[Any, Any]]) -> None:
		if any(section == "coexist" for section, _key in changes):
			from .. import coexist

			queue_handler.queueFunction(coexist.applyConfiguration)
		if ("general", "language") in changes:
			from .. import i18n

			if i18n.resolveLanguage(changes[("general", "language")][1]) != i18n.LANGUAGE:
				wx.CallAfter(_askRestartForLanguage)
		if ("general", "logLevel") in changes:
			try:
				from .. import log as logModule

				logModule.setLevel(changes[("general", "logLevel")][1])
			except Exception:
				log.exception("No se pudo cambiar el nivel del registro")
		if ("general", "startOnLogon") in changes:
			before, enable = changes[("general", "startOnLogon")]
			try:
				setStartOnLogon(enable)
			except OSError as e:
				log.exception("No se pudo modificar el inicio automático")
				# El registro no ha cambiado: conf y la casilla vuelven a lo que había.
				conf["general"]["startOnLogon"] = before
				self.setControlValue("startOnLogon", before)
				b = self._bound.get(("general", "startOnLogon"))
				if b is not None:
					b.original = before
				showError(_("No se pudo configurar el inicio automático: {error}").format(error=e), self)


# ---------------------------------------------------------------------- voz
def synthSnapshot() -> dict | None:
	"""Estado del sintetizador actual (debe llamarse en el hilo del núcleo)."""
	from .. import synth as synthHandler
	from ..synth.base import VoiceInfo

	s = synthHandler.getSynth()
	if s is None:
		return None
	settings = []
	for st in s.supportedSettings:
		info: dict[str, Any] = {
			"id": st.id,
			"displayName": st.displayName,
			"kind": st.kind,
			"minVal": st.minVal,
			"maxVal": st.maxVal,
			"normalStep": st.normalStep,
			"largeStep": st.largeStep,
			"value": s.getSetting(st.id),
			"choices": [],
		}
		if st.kind == "choice":
			try:
				for key, val in s.getChoices(st.id).items():
					label = val.displayName if isinstance(val, VoiceInfo) else str(val)
					info["choices"].append((key, label))
			except Exception:
				log.exception("No se pudieron leer las opciones de %s", st.id)
		settings.append(info)
	return {"name": s.name, "description": s.description or s.name, "settings": settings}


def _changeSynthSetting(settingId: str, value: Any) -> None:
	"""Cambia un ajuste del sintetizador (hilo del núcleo)."""
	from .. import synth as synthHandler

	# synth.changeSetting ya recarga el diccionario de voz al cambiar la voz.
	synthHandler.changeSetting(settingId, value)


class SpeechPanel(ConfigPanel):
	title = _("Voz")
	section = "speech"

	#: Grupo de los modos de voz (los modos que salta Tiresias+S se añaden dentro).
	MODE_GROUP = _("Modo de voz")

	def getFields(self) -> list[Field]:
		gm = self.MODE_GROUP
		g2 = _("Mayúsculas y deletreo")
		g3 = _("Símbolos y caracteres")
		gf = _("Funcionamiento de la voz")
		gh = _("Historial y visor de voz")
		# Idioma, números y lectura continua: categorías «Idioma de la voz» y «Lectura de texto».
		return [
			Choice("speechMode", _("Modo de voz:"), _speechModeChoices(), group=gm),
			Int("beepSpeechModePitch", _("Tono del pitido en el modo de voz «pitidos» (Hz):"), 50, 5000, group=gm),
			Int("capitalPitchChange", _("Porcentaje de cambio de tono para mayúsculas:"), -100, 100, group=g2),
			Bool("sayCapitalForCapitals", _("Decir «mayúscula» antes de las mayúsculas"), group=g2),
			Bool("beepForCapitals", _("Pitido para las mayúsculas"), group=g2),
			Bool("useSpellingFunctionality", _("Usar la función de deletreo del sintetizador"), group=g2),
			Bool("delayedCharacterDescriptions", _("Descripción fonética retardada de caracteres al mover el cursor"), group=g2),
			Int("delayedCharacterDescriptionsDelay", _("Retardo de la descripción fonética (milisegundos):"), 100, 10000, group=g2),
			Choice("symbolLevel", _("Nivel de símbolos y puntuación:"), _symbolLevelChoices(), group=g3),
			Bool("reportUnknownSymbols", _("Leer por su nombre Unicode los símbolos poco comunes"), group=g3),
			Bool("unicodeNormalization", _("Normalización Unicode (letras con acentos combinados, ligaduras...)"), group=g3),
			Bool("reportNormalizedForCharacterNavigation", _("Anunciar «normalizado» al navegar por caracteres"), group=g3),
			Bool("speakEmojiNames", _("Leer el nombre de los emojis"), group=g3),
			Bool("condenseRepeatedSymbols", _("Agrupar símbolos repetidos (por ejemplo «20 guiones»)"), group=g3),
			Int("repeatedSymbolsThreshold", _("Número mínimo de repeticiones para agrupar símbolos:"), 2, 100, group=g3),
			ListText("synthPriority", _("Orden de preferencia de sintetizadores en modo automático (separados por comas):"), group=gf),
			Bool("synthFallback", _("Cambiar a otro sintetizador si el actual falla o deja de responder"), group=gf),
			Bool("trimLeadingSilence", _("Recortar el silencio del principio de cada frase (menos retraso)"), group=gf),
			Bool("cancelExpiredFocusSpeech", _("Descartar lo pendiente de los controles que ya no tienen el foco"), group=gf),
			Int("speechHistorySize", _("Tamaño del historial de voz (mensajes):"), 10, 10000, group=gh),
			Bool("showAtStartup", _("Mostrar el visor de voz al iniciar"), section="speechViewer", group=gh),
			Bool("rememberPosition", _("Recordar la posición y el tamaño del visor de voz"), section="speechViewer", group=gh),
		]

	# --------------------------------------------------- modos que salta Tiresias+S
	def makeExtraSettings(self, builder: SettingsBuilder) -> None:
		group = self._groups.get(self.MODE_GROUP) or builder
		g = group.group(_("Modos de voz que se saltan con Tiresias+S"))
		excluded = set(_confValue("speech", "excludedSpeechModes", []) or [])
		self._modeChecks: dict[str, wx.CheckBox] = {}
		self._helpKeys = getattr(self, "_helpKeys", {})
		for mode, label in _speechModeChoices():
			self._modeChecks[mode] = g.addCheckBox(label, mode in excluded)
			self._helpKeys[self._modeChecks[mode]] = ("speech", "excludedSpeechModes")
		self._originalExcluded = sorted(excluded)
		self._modesLocked = self.lockControls("speech", "excludedSpeechModes", *self._modeChecks.values())

	def _excluded(self) -> list[str]:
		return sorted(m for m, c in self._modeChecks.items() if c.GetValue())

	def resetExtraToFactory(self) -> None:
		if not self._modesLocked:
			wanted = set(self.factoryValue("speech", "excludedSpeechModes", []) or [])
			for mode, check in self._modeChecks.items():
				check.SetValue(mode in wanted)

	def isValid(self) -> bool:
		if not self._modesLocked and len(self._excluded()) >= len(self._modeChecks) - 1:
			showError(_("Debe quedar al menos un modo de voz además del actual: no se pueden excluir todos."), self)
			return False
		return True

	def makeHeaderSettings(self, builder: SettingsBuilder) -> None:
		self._synthName: str | None = None
		self._synthOriginal: dict[str, Any] = {}
		self._synthCurrent: dict[str, Any] = {}
		self._synthControls: dict[str, tuple[dict, wx.Window]] = {}
		self.synthNameCtrl = builder.addText(_("Sintetizador:"), _("Cargando..."), style=wx.TE_READONLY, size=(300, -1))
		btn = builder.addButton(_("Cambiar &sintetizador..."))
		btn.Bind(wx.EVT_BUTTON, lambda evt: showSynthSelection())
		box = wx.StaticBoxSizer(wx.VERTICAL, self, _("Ajustes del sintetizador"))
		builder.sizer.Add(box, 0, wx.EXPAND | wx.BOTTOM, 8)
		self.synthBox = box.GetStaticBox()
		self.synthSizer = box
		self.reloadSynth()

	# --------------------------------------------------- sintetizador
	def reloadSynth(self) -> None:
		"""Vuelve a leer el sintetizador actual (p. ej. tras cambiarlo)."""
		runOnCore(synthSnapshot, callback=self._onSnapshot)

	def _onSnapshot(self, snap: dict | None) -> None:
		if not isAlive(self):
			return
		for child in list(self.synthBox.GetChildren()):
			child.Destroy()
		self.synthSizer.Clear()
		self._synthControls = {}
		builder = SettingsBuilder(self.synthBox, self.synthSizer)
		if snap is None:
			self.synthNameCtrl.SetValue(_("Ninguno"))
			builder.addStaticText(_("No hay ningún sintetizador cargado."))
			self._synthName = None
			self._synthOriginal = {}
			self._synthCurrent = {}
			self.relayout()
			return
		self.synthNameCtrl.SetValue(snap["description"])
		if snap["name"] != self._synthName:
			# Nuevo sintetizador: los valores actuales pasan a ser la referencia.
			self._synthName = snap["name"]
			self._synthOriginal = {s["id"]: s["value"] for s in snap["settings"]}
		self._synthCurrent = {s["id"]: s["value"] for s in snap["settings"]}
		for s in snap["settings"]:
			label = s["displayName"]
			kind = s["kind"]
			if kind == "choice":
				keys = [k for k, _l in s["choices"]]
				labels = [lbl for _k, lbl in s["choices"]]
				sel = keys.index(s["value"]) if s["value"] in keys else 0
				ctrl: wx.Window = builder.addChoice(label + ":", labels, sel)
				ctrl.Bind(wx.EVT_CHOICE, lambda evt, info=s: self._onSynthChoice(info, evt))
			elif kind == "boolean":
				ctrl = builder.addCheckBox(label, bool(s["value"]))
				ctrl.Bind(wx.EVT_CHECKBOX, lambda evt, info=s: self._onSynthValue(info, bool(evt.IsChecked())))
			else:
				try:
					value = int(s["value"])
				except (TypeError, ValueError):
					value = s["minVal"]
				ctrl = builder.addSlider(label + ":", s["minVal"], s["maxVal"], value, s["normalStep"], s["largeStep"])
				ctrl.Bind(wx.EVT_SLIDER, lambda evt, info=s: self._onSynthValue(info, int(evt.GetEventObject().GetValue())))
			self._synthControls[s["id"]] = (s, ctrl)
		if not snap["settings"]:
			builder.addStaticText(_("Este sintetizador no tiene ajustes."))
		self.relayout()

	def _onSynthChoice(self, info: dict, evt: wx.CommandEvent) -> None:
		i = evt.GetSelection()
		# Las opciones actuales (_refreshSynthValues las cambia tras cambiar de voz),
		# no las que había al crear el control.
		info = self._synthControls.get(info["id"], (info, None))[0]
		choices = info["choices"]
		if not 0 <= i < len(choices):
			return
		self._onSynthValue(info, choices[i][0])

	def _onSynthValue(self, info: dict, value: Any) -> None:
		settingId = info["id"]
		if self._synthCurrent.get(settingId) == value:
			return
		self._synthCurrent[settingId] = value
		queue_handler.queueFunction(_changeSynthSetting, settingId, value)
		if settingId == "voice":
			# Otros ajustes (variantes, velocidad...) pueden depender de la voz.
			runOnCore(synthSnapshot, callback=lambda snap: self._refreshSynthValues(snap, skip=settingId))

	def _refreshSynthValues(self, snap: dict | None, skip: str) -> None:
		"""Actualiza los controles sin destruirlos (el foco sigue donde está)."""
		if not isAlive(self) or snap is None or snap["name"] != self._synthName:
			return
		for s in snap["settings"]:
			sid = s["id"]
			self._synthCurrent[sid] = s["value"]
			if sid == skip or sid not in self._synthControls:
				continue
			old, ctrl = self._synthControls[sid]
			if s["kind"] == "choice":
				keys = [k for k, _l in s["choices"]]
				labels = [lbl for _k, lbl in s["choices"]]
				if labels != [lbl for _k, lbl in old["choices"]]:
					ctrl.Set(labels)
				if s["value"] in keys:
					ctrl.SetSelection(keys.index(s["value"]))
			elif s["kind"] == "boolean":
				ctrl.SetValue(bool(s["value"]))
			else:
				try:
					ctrl.SetValue(int(s["value"]))
				except (TypeError, ValueError):
					pass
			self._synthControls[sid] = (s, ctrl)

	def onSave(self) -> None:
		super().onSave()
		ex = self._excluded()
		if not self._modesLocked and ex != self._originalExcluded:
			conf["speech"]["excludedSpeechModes"] = ex
			self._originalExcluded = ex
		# Los ajustes del sintetizador ya se aplicaron en vivo: nueva referencia.
		self._synthOriginal = dict(self._synthCurrent)

	def onDiscard(self) -> None:
		if not self._synthName:
			return
		changed = [k for k, v in self._synthOriginal.items() if self._synthCurrent.get(k) != v]
		if not changed:
			return
		name = self._synthName
		original = dict(self._synthOriginal)

		def revert() -> None:
			from .. import synth as synthHandler

			s = synthHandler.getSynth()
			if s is None or s.name != name:
				return
			# La voz primero: el resto de ajustes puede depender de ella.
			for key in sorted(original, key=lambda k: 0 if k == "voice" else 1):
				if original[key] is None:
					continue
				try:
					_changeSynthSetting(key, original[key])
				except Exception:
					log.exception("No se pudo restaurar %s", key)

		queue_handler.queueFunction(revert)


# ---------------------------------------------------------------------- audio
def _reloadSynthForDevice(device: str) -> None:
	"""Cambia el dispositivo de salida (núcleo).

	Los reproductores reabren la salida en el siguiente bloque de audio, así
	que no hace falta recargar el sintetizador (sus ajustes se conservan, #18836).
	"""
	from ..audio.wave_player import OutputSettings

	OutputSettings.deviceName = device


def _applyAudioModes() -> None:
	"""Aplica la atenuación y la división del sonido elegidas (núcleo)."""
	from ..audio import ducking, sound_split

	try:
		sound_split.apply()
		ducking.apply()
	except Exception:
		log.exception("Error aplicando el audio")


_OUTPUT_MODES: ChoiceList = [("wasapi", _("WASAPI (recomendado, baja latencia)")), ("waveOut", _("waveOut (compatibilidad con controladores antiguos)"))]
_VOLUME_FEEDBACK: ChoiceList = [("off", _("Ninguno")), ("sound", _("Sonido")), ("speech", _("Voz")), ("both", _("Sonido y voz"))]
_BUFFER_SIZES: ChoiceList = [
	("low", _("Pequeño (menos latencia)")),
	("normal", _("Normal")),
	("high", _("Grande (evita cortes y crujidos con el equipo muy cargado)")),
]


class AudioPanel(ConfigPanel):
	title = _("Audio")
	section = "audio"

	#: Grupo de la división del sonido (la lista de modos de la orden va dentro).
	SPLIT_GROUP = _("División del sonido")
	#: Grupo del volumen del sistema (el botón del mezclador va dentro).
	SYSTEM_GROUP = _("Volumen del sistema y mezclador")

	def getFields(self) -> list[Field]:
		# El volumen y el tema de los sonidos de Tiresias están en la categoría «Sonidos».
		go = _("Salida de audio")
		gs = self.SPLIT_GROUP
		gd = _("Atenuación de otras aplicaciones")
		gv = self.SYSTEM_GROUP
		return [
			Choice("outputMode", _("Salida de audio:"), _OUTPUT_MODES, group=go),
			Choice("outputDevice", _("Dispositivo de salida de audio:"), _audioDeviceChoices, group=go),
			Choice("bufferSize", _("Tamaño del búfer de audio:"), _BUFFER_SIZES, group=go),
			Int("keepAudioAwakeSeconds", _("Mantener el dispositivo de audio activo tras hablar (segundos):"), 0, 3600, group=go),
			Slider("whiteNoiseVolume", _("Volumen del ruido blanco que mantiene despierto el dispositivo (0 = sin ruido):"), 0, 100, lineSize=1, pageSize=10, group=go),
			Choice("soundSplitMode", _("División del sonido:"), _soundSplitChoices, group=gs),
			Bool("soundSplitApplyToOtherApps", _("Aplicar la división del sonido a las demás aplicaciones"), group=gs),
			Choice("duckingMode", _("Atenuación de otras aplicaciones:"), _duckingChoices, group=gd),
			Slider("duckingLevel", _("Volumen de las aplicaciones atenuadas (porcentaje):"), 0, 100, lineSize=5, pageSize=10, group=gd),
			Bool("duckForSounds", _("Los sonidos y pitidos de Tiresias también atenúan las demás aplicaciones"), group=gd),
			Int("mixerVolumeStep", _("Pas&o de las órdenes de volumen (porcentaje):"), 1, 50, group=gv),
			Choice("volumeChangeFeedback", _("&Aviso al cambiar el volumen general:"), _VOLUME_FEEDBACK, group=gv),
			Bool("confirmSystemMute", _("La tecla Silenciar del teclado pide una segunda pulsación antes de silenciar el &equipo"), group=gv),
			Bool("micMuteSounds", _("Confirmar con un &sonido al silenciar o activar el micrófono"), group=gv),
			Bool("unmuteOnStartup", _("Al &iniciar Tiresias, quitar el silencio del sistema y subir el volumen si está a cero"), group=gv),
			Slider("startupVolumeLevel", _("&Volumen general que se pone al iniciar si estaba a cero (porcentaje):"), 5, 100, lineSize=5, pageSize=10, group=gv),
		]

	def makeExtraSettings(self, builder: SettingsBuilder) -> None:
		# Modos que recorre la orden de división del sonido (includedSoundSplitModes).
		from ..audio import sound_split

		self._splitModes = list(sound_split.MODES)
		current = set(_confValue("audio", "includedSoundSplitModes", self._splitModes) or [])
		group = self._groups.get(self.SPLIT_GROUP) or builder
		self.splitModesList = group.addLabeledControl(
			_("Modos que recorre la orden de división del sonido:"),
			lambda p: wx.CheckListBox(p, choices=[sound_split.MODES[m][2] for m in self._splitModes], size=(420, 130)),
			vertical=True,
		)
		for i, m in enumerate(self._splitModes):
			self.splitModesList.Check(i, m in current)
		self._splitModesLocked = self.lockControls("audio", "includedSoundSplitModes", self.splitModesList)
		self._helpKeys = {self.splitModesList: ("audio", "includedSoundSplitModes")}
		group = self._groups.get(self.SYSTEM_GROUP) or builder
		btn = group.addButton(_("Abrir el &mezclador de audio..."))
		btn.Bind(wx.EVT_BUTTON, self._onMixer)

	@staticmethod
	def _onMixer(evt: wx.CommandEvent) -> None:
		from . import audio_dialogs

		audio_dialogs.showMixer()

	def resetExtraToFactory(self) -> None:
		if self._splitModesLocked:
			return
		wanted = set(self.factoryValue("audio", "includedSoundSplitModes", self._splitModes) or [])
		for i, m in enumerate(self._splitModes):
			self.splitModesList.Check(i, m in wanted)

	def onSave(self) -> None:
		super().onSave()
		if self._splitModesLocked:
			return
		modes = [m for i, m in enumerate(self._splitModes) if self.splitModesList.IsChecked(i)] or ["off"]
		if list(_confValue("audio", "includedSoundSplitModes", []) or []) != modes:
			conf["audio"]["includedSoundSplitModes"] = modes

	def afterSave(self, changes: dict[tuple[str, str], tuple[Any, Any]]) -> None:
		if ("audio", "outputDevice") in changes:
			device = changes[("audio", "outputDevice")][1]
			queue_handler.queueFunction(_reloadSynthForDevice, device)
		# El volumen de atenuación (con «Atenuar siempre») y «Aplicar la división
		# a las demás aplicaciones» también se aplican al guardar, no al cambiar de modo.
		if any(("audio", key) in changes for key in ("duckingMode", "duckingLevel", "soundSplitMode", "soundSplitApplyToOtherApps")):
			queue_handler.queueFunction(_applyAudioModes)


# ---------------------------------------------------------------------- braille
class BraillePanel(ConfigPanel):
	title = _("Braille")
	section = "braille"

	def getFields(self) -> list[Field]:
		from . import braille_panels as bp

		gl = _("Conexión de la línea")
		gt = _("Tablas y entrada")
		gs = _("Seguimiento y desplazamiento")
		gm = _("Mensajes")
		gc = _("Cursor")
		# La presentación del texto, las propiedades y el visor están en «Presentación braille».
		return [
			Bool("announceConnection", _("Anunciar la conexión y la desconexión de la línea braille"), section="brailleDisplays", group=gl),
			Bool("detectBluetooth", _("La detección automática busca también líneas Bluetooth"), section="brailleDisplays", group=gl),
			Bool("detectGenericUsb", _("Detectar adaptadores USB-serie genéricos (pueden ser otros aparatos)"), section="brailleDisplays", group=gl),
			Text("brlapiServer", _("Servidor BrlAPI de BRLTTY (equipo:puerto; «:0» para la tubería local):"), section="brailleDisplays", group=gl),
			Choice("translationTable", _("Tabla de salida:"), _brailleTableChoices, group=gt),
			Choice("inputTable", _("Tabla de entrada:"), _brailleInputTableChoices, group=gt),
			Choice("pcKeyboardDots", _("Teclado braille del PC:"), bp.PC_DOTS, group=gt),
			Bool("expandAtCursor", _("Expandir a braille informático la palabra del cursor"), group=gt),
			Choice("mode", _("Modo braille:"), _BRAILLE_MODES, group=gs),
			Choice("tetherTo", _("Braille sigue:"), _BRAILLE_TETHER, group=gs),
			Bool("followSayAll", _("Braille sigue a la lectura continua"), group=gs),
			Choice("reviewRoutingMovesSystemCaret", _("Enrutar en la revisión mueve el cursor del sistema:"), bp.REVIEW_ROUTING, group=gs),
			Bool("speakOnRouting", _("Leer el carácter al enrutar"), group=gs),
			Bool("speakOnNavigatingByUnit", _("Leer la línea al pasar de línea con la línea braille"), group=gs),
			Bool("interruptSpeechWhileScrolling", _("Interrumpir la voz al desplazar la línea braille"), group=gs),
			Int("autoScrollRate", _("Velocidad del desplazamiento automático (celdas por segundo):"), 1, 20, group=gs),
			Choice("showMessages", _("Mostrar mensajes:"), _BRAILLE_MESSAGES, group=gm),
			Int("messageTimeout", _("Duración de los mensajes (segundos):"), 1, 60, group=gm),
			Bool("showCursor", _("Mostrar el cursor"), group=gc),
			Bool("cursorBlink", _("Parpadeo del cursor"), group=gc),
			Int("cursorBlinkRate", _("Velocidad de parpadeo del cursor (milisegundos):"), 100, 2000, group=gc),
			Choice("cursorShapeFocus", _("Forma del cursor del foco:"), _CURSOR_SHAPES, group=gc),
			Choice("cursorShapeReview", _("Forma del cursor de revisión:"), _CURSOR_SHAPES, group=gc),
		]

	# --------------------------------------------------- línea braille (como NVDA: «Cambiar...»)
	def makeHeaderSettings(self, builder: SettingsBuilder) -> None:
		self.displayText = builder.addText(_("Línea braille:"), self._displayName(), style=wx.TE_READONLY, size=(360, -1))
		btn = builder.addButton(_("&Seleccionar línea braille..."))
		btn.Bind(wx.EVT_BUTTON, self._onSelectDisplay)
		self._helpKeys = {self.displayText: ("braille", "display"), btn: ("braille", "display")}

	@staticmethod
	def _displayName() -> str:
		from .. import braille

		display = braille.handler.display
		name = getattr(display, "displayName", None) or display.description
		if getattr(display, "isHardware", False) and not getattr(display, "connected", False):
			name = _("{name} (esperando conexión)").format(name=name)
		return name

	def _onSelectDisplay(self, evt: wx.CommandEvent) -> None:
		from . import braille_display_dialog

		braille_display_dialog.showDialog()
		dlg = braille_display_dialog._dialog
		if isAlive(dlg) and not getattr(dlg, "_braillePanelBound", False):
			dlg._braillePanelBound = True
			dlgId = dlg.GetId()

			def onDestroy(e: wx.WindowDestroyEvent) -> None:
				e.Skip()
				if e.GetId() == dlgId:
					# Tras cargar la línea (encolado en el núcleo antes que esto).
					runOnCore(self._displayName, callback=self._setDisplayName)

			dlg.Bind(wx.EVT_WINDOW_DESTROY, onDestroy)

	def _setDisplayName(self, name: str | None) -> None:
		if name and isAlive(self):
			self.displayText.SetValue(name)

	def makeExtraSettings(self, builder: SettingsBuilder) -> None:
		from . import braille_display_dialog

		# Un grupo por cada controlador de línea con ajustes propios.
		self._driverCtrls = braille_display_dialog.makeDriverSettings(builder)
		for _name, _s, ctrl, _values in self._driverCtrls:
			self._helpKeys[ctrl] = ("brailleDisplays", "settings")

	def resetExtraToFactory(self) -> None:
		from . import braille_display_dialog

		braille_display_dialog.resetDriverSettings(self._driverCtrls)

	def isValid(self) -> bool:
		from ..braille.drivers import brltty

		try:
			brltty.parseServer(self.getValue("brlapiServer", "brailleDisplays") or "")
		except ValueError:
			showError(_("El servidor BrlAPI debe ser equipo:puerto (por ejemplo 127.0.0.1:4101) o «:0» para la tubería local."), self)
			ctrl = self.getControl("brlapiServer", "brailleDisplays")
			if ctrl:
				ctrl.SetFocus()
			return False
		return True

	def onSave(self) -> None:
		super().onSave()
		from . import braille_display_dialog

		braille_display_dialog.saveDriverSettings(self._driverCtrls)

	def afterSave(self, changes: dict[tuple[str, str], tuple[Any, Any]]) -> None:
		from . import braille_display_dialog
		from .. import braille

		braille_display_dialog.applyDisplayChanges({k for s, k in changes if s == "brailleDisplays"})
		if any(s == "braille" for s, _k in changes):
			queue_handler.queueFunction(braille.handler.applyConfig)


# ---------------------------------------------------------------------- teclado
def _gestureLayoutChoices() -> ChoiceList:
	from .. import gesture_layouts

	return [(n, gesture_layouts.layoutLabel(n)) for n in gesture_layouts.LAYOUT_NAMES]


class KeyboardPanel(ConfigPanel):
	title = _("Teclado")
	section = "keyboard"

	def getFields(self) -> list[Field]:
		from ..speech import voice_schemes

		gm = _("Teclas que actúan como tecla Tiresias")
		ge = _("Eco de teclado")
		gk = _("Teclas")
		gg = _("Mapa de gestos y capas")
		# «Permitir la lectura rápida» está con la lectura continua (categoría «Lectura de texto»).
		return [
			Choice("layout", _("Distribución del teclado:"), _LAYOUTS),
			Bool("useInsertAsModifier", _("Insertar"), group=gm),
			Bool("useNumpadInsertAsModifier", _("Insertar del teclado numérico"), group=gm),
			Bool("useCapsLockAsModifier", _("Bloqueo de mayúsculas"), group=gm),
			Choice("speakTypedCharacters", _("Anunciar los caracteres escritos:"), _TYPED_CHOICES, group=ge),
			Choice("speakTypedWords", _("Anunciar las palabras escritas:"), _TYPED_CHOICES, group=ge),
			Bool("speakWholeEditedWord", _("Al editar una palabra que ya estaba escrita, decir la palabra completa"), group=ge),
			# Se aplica siempre (las demás propiedades de la voz del eco, con las voces por contexto).
			Int(voice_schemes.contextKey("typing", "Rate"), _("Velocidad propia del eco de teclado (cambio en porcentaje; 0 = igual que la voz):"), -80, 200, section="speech", group=ge),
			Bool("speechInterruptForCharacters", _("Interrumpir la voz al escribir caracteres"), group=ge),
			Bool("speechInterruptForEnter", _("Interrumpir la voz al pulsar Intro"), group=ge),
			Bool("beepForLowercaseWithCapsLock", _("Pitido al escribir minúsculas con el bloqueo de mayúsculas activado"), group=ge),
			Bool("alertForSpellingErrors", _("Avisar de errores ortográficos al escribir"), group=ge),
			Bool("speakCommandKeys", _("Anunciar las teclas de órdenes"), group=gk),
			Bool("announceToggleKeys", _("Anunciar las teclas de bloqueo (mayúsculas, numérico, desplazamiento)"), group=gk),
			Bool("announceInputLanguageChanges", _("Anunciar los cambios de idioma o distribución del teclado"), group=gk),
			Bool("handleInjectedKeys", _("Procesar las teclas simuladas por otras aplicaciones"), group=gk),
			Int("multiPressTimeout", _("Tiempo para pulsaciones múltiples (milisegundos):"), 100, 2000, group=gk),
			Choice("gestureLayout", _("Mapa de gestos:"), _gestureLayoutChoices, group=gg),
			Bool("layersEnabled", _("Teclas por capas (Tiresias+Alt+Espacio y una letra)"), group=gg),
			Int("layerTimeout", _("Tiempo de espera de las capas (segundos):"), 1, 60, group=gg),
		]

	def makeExtraSettings(self, builder: SettingsBuilder) -> None:
		from . import gesture_tools

		g = builder.group(_("Tecla del menú de Tiresias"))
		self.menuKeysText = g.addStaticText(_("Teclas actuales: {keys}").format(keys=gesture_tools.describeMenuKeys()))
		btn = g.addButton(_("Configurar la &tecla del menú..."))
		btn.Bind(wx.EVT_BUTTON, self._onMenuKey)
		btn2 = builder.addButton(_("Abrir &gestos de entrada (cambiar cualquier tecla)..."))
		btn2.Bind(wx.EVT_BUTTON, self._onGestures)
		g = builder.group(_("Mapa de gestos personal"))
		btn = g.addButton(_("E&xportar mis gestos..."))
		btn.Bind(wx.EVT_BUTTON, self._onExportGestures)
		btn = g.addButton(_("&Importar gestos..."))
		btn.Bind(wx.EVT_BUTTON, self._onImportGestures)

	def _onExportGestures(self, evt) -> None:
		from .. import gesture_layouts

		dlg = wx.FileDialog(self, _("Exportar gestos"), defaultFile="gestos-tiresias.json", wildcard=_("Archivos JSON (*.json)|*.json"), style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
		try:
			if dlg.ShowModal() != wx.ID_OK:
				return
			path = dlg.GetPath()
		finally:
			dlg.Destroy()
		try:
			n = gesture_layouts.exportUserMap(path)
		except OSError as e:
			showError(_("No se pudieron exportar los gestos: {error}").format(error=e), self)
			return
		message_dialog.messageBox(_("Se han exportado {n} cambios de gestos.").format(n=n), _("Exportar gestos"), wx.OK | wx.ICON_INFORMATION, self)

	def _onImportGestures(self, evt) -> None:
		from .. import gesture_layouts

		dlg = wx.FileDialog(self, _("Importar gestos"), wildcard=_("Archivos JSON (*.json)|*.json"), style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
		try:
			if dlg.ShowModal() != wx.ID_OK:
				return
			path = dlg.GetPath()
		finally:
			dlg.Destroy()
		merge = message_dialog.messageBox(
			_("¿Conservar los cambios de gestos que ya tiene? Si contesta No, se sustituirán por los del archivo."),
			_("Importar gestos"),
			wx.YES_NO | wx.ICON_QUESTION,
			self,
		) == wx.YES
		try:
			n = gesture_layouts.importUserMap(path, merge=merge)
		except (OSError, ValueError) as e:
			showError(_("No se pudieron importar los gestos: {error}").format(error=e), self)
			return
		message_dialog.messageBox(_("Se han importado {n} gestos.").format(n=n), _("Importar gestos"), wx.OK | wx.ICON_INFORMATION, self)

	def afterSave(self, changes: dict[tuple[str, str], tuple[Any, Any]]) -> None:
		if ("keyboard", "gestureLayout") in changes:
			from .. import gesture_layouts

			queue_handler.queueFunction(gesture_layouts.apply)

	def _onMenuKey(self, evt) -> None:
		from . import gesture_tools

		gesture_tools.showMenuKeyDialog(wx.GetTopLevelParent(self))
		dlg = gesture_tools._menuKeyDialog
		if isAlive(dlg) and not getattr(dlg, "_keyboardPanelBound", False):
			dlg._keyboardPanelBound = True
			dlgId = dlg.GetId()

			def onDestroy(e: wx.WindowDestroyEvent) -> None:
				e.Skip()
				# GetEventObject() no es el mismo objeto Python al destruirse: por identificador.
				if e.GetId() == dlgId:
					# Tras aplicar el mapa (encolado en el núcleo antes que esto).
					runOnCore(gesture_tools.describeMenuKeys, callback=self._setMenuKeysText)

			dlg.Bind(wx.EVT_WINDOW_DESTROY, onDestroy)

	def _setMenuKeysText(self, keys: str | None) -> None:
		if keys is None or not isAlive(self):
			return
		self.menuKeysText.SetLabel(_("Teclas actuales: {keys}").format(keys=keys))
		self.relayout()

	def _onGestures(self, evt) -> None:
		from . import config_dialogs

		config_dialogs.showInputGestures()

	def isValid(self) -> bool:
		keys = ("useInsertAsModifier", "useNumpadInsertAsModifier", "useCapsLockAsModifier")
		if not any(self.getValue(k) for k in keys):
			showError(_("Al menos una tecla debe usarse como tecla Tiresias."), self)
			ctrl = self.getControl("useInsertAsModifier")
			if ctrl:
				ctrl.SetFocus()
			return False
		return True


# ---------------------------------------------------------------------- ratón
class MousePanel(ConfigPanel):
	title = _("Ratón")
	section = "mouse"
	fields = [
		Bool("enableMouseTracking", _("Seguimiento del ratón"), group=_("Lectura bajo el ratón")),
		Choice("mouseTextUnit", _("Unidad de texto bajo el ratón:"), _TEXT_UNITS, group=_("Lectura bajo el ratón")),
		Bool("reportObjectRoleOnMouseEnter", _("Anunciar el tipo de objeto al entrar el ratón"), group=_("Lectura bajo el ratón")),
		Bool("reportMouseShapeChanges", _("Anunciar los cambios de forma del puntero"), group=_("Lectura bajo el ratón")),
		# #11898: 0 = leer en cuanto se mueve.
		Int("reportDelay", _("Esperar a que el puntero se detenga antes de leer (milisegundos, 0 = no esperar):"), 0, 5000, group=_("Lectura bajo el ratón")),
		Bool("ignoreInjectedMouseInput", _("Ignorar los movimientos del ratón simulados por otras aplicaciones"), group=_("Lectura bajo el ratón")),
		# El tono mínimo y el máximo valen para todos los tonos de coordenadas
		# (ratón, ratón por teclado, objeto navegador y cursor de revisión).
		Bool("audioCoordinatesOnMouseMove", _("Tonos de coordenadas al mover el ratón"), group=_("Tonos de coordenadas")),
		Int("audioCoordinatesMinPitch", _("Tono mínimo de las coordenadas (Hz):"), 50, 10000, group=_("Tonos de coordenadas")),
		Int("audioCoordinatesMaxPitch", _("Tono máximo de las coordenadas (Hz):"), 50, 10000, group=_("Tonos de coordenadas")),
		Int("step", _("Paso del ratón por teclado (píxeles):"), 1, 500, section="mouseKeys", group=_("Ratón por teclado"), default=10),
		Bool("announceCoordinates", _("Decir las coordenadas al mover el puntero"), section="mouseKeys", group=_("Ratón por teclado"), default=True),
		Choice("coordinates", _("Coordenadas:"), [("screen", _("De la pantalla")), ("window", _("De la ventana activa"))], section="mouseKeys", group=_("Ratón por teclado"), default="screen"),
		Bool("relativePositions", _("Guardar las posiciones respecto a la ventana (sirven aunque se mueva)"), section="mouseKeys", group=_("Ratón por teclado"), default=True),
		Bool("audioCoordinates", _("Tonos de coordenadas al mover el puntero con el teclado"), section="mouseKeys", group=_("Ratón por teclado"), default=False),
	]

	def makeSettings(self, sizer: wx.BoxSizer) -> None:
		from .. import mouse_keys  # noqa: F401  (registra los valores del ratón por teclado)

		super().makeSettings(sizer)

	def isValid(self) -> bool:
		if self.getValue("audioCoordinatesMinPitch") >= self.getValue("audioCoordinatesMaxPitch"):
			showError(_("El tono mínimo de las coordenadas debe ser menor que el máximo."), self)
			return False
		return True


class ReviewCursorPanel(ConfigPanel):
	title = _("Cursor de revisión")
	section = "reviewCursor"
	fields = [
		Bool("followFocus", _("Seguir al foco del sistema")),
		Bool("followCaret", _("Seguir al cursor del sistema")),
		Bool("followMouse", _("Seguir al cursor del ratón")),
		Bool("simpleReviewMode", _("Modo de revisión simple (omitir objetos de diseño)")),
		# #2559: tono agudo arriba y grave abajo; el paneo indica el lado.
		Bool("audioCoordinatesOnNavigatorMove", _("Tonos de coordenadas al mover el objeto navegador")),
		Bool("audioCoordinatesOnReviewMove", _("Tonos de coordenadas al mover el cursor de revisión")),
	]


class PresentationPanel(ConfigPanel):
	title = _("Presentación de objetos")
	section = "presentation"

	def getFields(self) -> list[Field]:
		gi = _("Información de los objetos")
		gn = _("Notificaciones y cambios")
		ge = _("Campos de edición")
		gp = _("Barras de progreso")
		# «Elementos en los que se puede hacer clic» está en «Formato de documento» (vale para todo).
		return [
			Bool("reportTooltips", _("Anunciar las descripciones emergentes"), group=gi),
			Bool("reportHelpBalloons", _("Anunciar los globos de ayuda"), group=gi),
			Bool("reportKeyboardShortcuts", _("Anunciar las teclas de acceso de los objetos"), group=gi),
			Bool("spellAccessKeys", _("Decir las letras de las teclas de acceso por su nombre («Alt+efe»)"), section="speech", group=gi),
			Bool("reportObjectPositionInformation", _("Anunciar la posición del objeto (por ejemplo «2 de 5»)"), group=gi),
			Bool("guessObjectPositionInformationWhenUnavailable", _("Deducir la posición del objeto cuando no esté disponible"), group=gi),
			Bool("reportObjectDescriptions", _("Anunciar las descripciones de los objetos"), group=gi),
			# #12718 y foros 1.19.
			Bool("reportGroupDescriptions", _("Anunciar la descripción de los grupos y regiones al entrar en ellos"), group=gi),
			Bool("reportObjectLanguage", _("Leer el nombre de los objetos en su idioma (con el cambio automático de idioma)"), group=gi),
			Bool("reportMultiSelect", _("Anunciar «selección múltiple» en las listas que la admiten"), group=gi),
			Bool("announceFocusAncestors", _("Anunciar los contenedores del foco al cambiar de grupo"), group=gi),
			Bool("enabled", _("Usar etiquetas personalizadas de controles"), section="labels", group=gi),
			Bool("reportNotifications", _("Anunciar las notificaciones"), group=gn),
			Bool("notificationsFromBackground", _("Anunciar también las notificaciones de las aplicaciones en segundo plano"), section="uia", group=gn),
			Bool("reportDynamicContentChanges", _("Anunciar los cambios dinámicos de contenido"), group=gn),
			Bool("reportAutoSuggestionsWithSound", _("Sonido al aparecer sugerencias automáticas"), group=gn),
			Bool("reportSuggestionItems", _("Anunciar el elemento elegido en las listas de sugerencias"), section="objects", group=gn),
			Bool("reportSelectionChanges", _("Anunciar los elementos que se seleccionan o deseleccionan en listas de selección múltiple"), section="objects", group=gn),
			Bool("reportDialogText", _("Leer el texto de los diálogos al abrirse"), section="objects", group=gn),
			Bool("reportSortChanges", _("Anunciar los cambios de orden de las columnas"), section="objects", group=gn),
			Bool("reportDragDrop", _("Anunciar las operaciones de arrastrar y soltar"), section="objects", group=gn),
			Bool("reportMaxLength", _("Anunciar la longitud máxima de los campos de edición"), section="objects", group=ge),
			# Foros 1.17: aviso de caracteres restantes al escribir.
			Choice("maxLengthWarning", _("Aviso de los caracteres que quedan al escribir:"), _MAXLEN_WARNING_CHOICES, section="objects", group=ge),
			Int("maxLengthWarningThreshold", _("Avisar cuando queden como máximo (caracteres):"), 1, 1000, section="objects", group=ge),
			Choice("progressBarOutputMode", _("Barras de progreso:"), _PROGRESS_MODES, group=gp),
			Bool("reportBackgroundProgressBars", _("Anunciar las barras de progreso en segundo plano"), group=gp),
			Int("progressBarSpeechInterval", _("Anunciar por voz cada (porcentaje):"), 1, 100, group=gp),
			Int("progressBarBeepInterval", _("Pitar cada (porcentaje):"), 1, 100, group=gp),
			Int("progressBarBeepMinHz", _("Tono del pitido al 0 % (Hz):"), 20, 2000, group=gp),
		]


class BrowseModePanel(ConfigPanel):
	title = _("Modo exploración")
	section = "browseMode"

	def getFields(self) -> list[Field]:
		gl = _("Al cargar un documento")
		gd = _("Disposición del texto")
		gn = _("Navegación")
		gf = _("Modo foco")
		gr = _("Regiones e imágenes")
		# El estilo de párrafo está en «Navegación por documentos» (como en NVDA).
		return [
			Bool("uiaDocuments", _("Modo exploración también en Word, Outlook, Acrobat y otros documentos")),
			Bool("enableOnPageLoad", _("Activar el modo exploración al cargar las páginas"), group=gl),
			Bool("autoSayAllOnPageLoad", _("Lectura continua automática al cargar una página"), group=gl),
			Bool("rememberPositionPerPage", _("Recordar la posición en cada página"), group=gl),
			Choice("loadingIndicator", _("Indicación mientras carga el documento:"), [("off", _("Ninguna")), ("beep", _("Pitidos")), ("speech", _("Voz"))], group=gl),
			Bool("reportPageSummary", _("Decir un resumen de la página al cargarla (encabezados, enlaces, regiones)"), group=gl),
			Bool("announceModeOnDocumentChange", _("Anunciar el modo al entrar en otro documento"), group=gl),
			Int("maxLineLength", _("Máximo de caracteres por línea:"), 10, 1000, group=gd),
			Int("linesPerPage", _("Líneas por página:"), 5, 500, group=gd),
			Bool("useScreenLayout", _("Usar la disposición en pantalla (enlaces en la misma línea)"), group=gd),
			# #11073 y #3997.
			Bool("breakAfterLinks", _("Sin disposición en pantalla, el texto que sigue a un enlace empieza otra línea"), group=gd),
			Bool("containerLinesApart", _("Entrada y salida de listas, tablas, regiones y otros contenedores en una línea aparte"), group=gd),
			Bool("includeLayoutTables", _("Incluir las tablas de diseño"), group=gd),
			Bool("singleLetterNavigation", _("Navegación con una sola letra"), group=gn),
			Bool("quickNavWrap", _("Volver al principio o al final al navegar con una sola letra"), group=gn),
			Bool("listItemWithinList", _("La tecla I recorre solo los elementos de la lista actual"), group=gn),
			Bool("skipBlankLines", _("Saltar las líneas en blanco al moverse con las flechas"), group=gn),
			Bool("followAnchors", _("Llevar el cursor al destino de los enlaces de la misma página"), group=gn),
			Bool("clickMovesCaret", _("Un clic del ratón mueve el cursor del modo exploración"), group=gn),
			Bool("scrollIntoView", _("Desplazar la pantalla hasta el elemento del cursor"), group=gn),
			Bool("nativeSelectionMode", _("Selección nativa: la selección se aplica también al documento"), group=gn),
			Bool("autoPassThroughOnFocusChange", _("Modo foco automático al cambiar el foco"), group=gf),
			Bool("autoPassThroughOnCaretMove", _("Modo foco automático al mover el cursor"), group=gf),
			Bool("autoFocusFocusableElements", _("Mover el foco automáticamente a los elementos enfocables"), group=gf),
			Bool("passThroughAudioIndication", _("Indicación sonora de los modos foco y exploración"), group=gf),
			Bool("trapNonCommandGestures", _("Bloquear las teclas sin orden para que no lleguen al documento"), group=gf),
			Bool("reportLiveRegions", _("Anunciar las regiones vivas"), group=gr),
			Bool("assertiveLiveRegionsInterrupt", _("Las regiones vivas urgentes interrumpen la voz"), group=gr),
			Bool("reportLandmarksOnFocusChange", _("Anunciar la salida de regiones al mover el foco"), group=gr),
			Bool("reportUnlabeledGraphics", _("Mostrar las imágenes sin texto alternativo (y decir «sin descripción» fuera del modo exploración)"), group=gr),
			# #7412, foros 1.18.
			Bool("reportGraphicFileNames", _("Decir el nombre de archivo de las imágenes sin texto alternativo"), group=gr),
		]


def _colorFormatChoices() -> ChoiceList:
	# Nombre, nombre y RGB o nombre y hexadecimal (#8674).
	from .. import formatting

	return list(formatting.COLOR_FORMATS)


class DocumentFormattingPanel(ConfigPanel):
	title = _("Formato de documento")
	section = "documentFormatting"

	def getFields(self) -> list[Field]:
		gf = _("Fuente")
		gd = _("Información del documento")
		gp = _("Páginas y espaciado")
		gt = _("Tablas")
		gs = _("Elementos")
		# Como en NVDA, valen para todos los documentos, también los de Word y Excel.
		return [
			Bool("detectFormatAfterCursor", _("Detectar los cambios de formato después del cursor")),
			Bool("reportFontName", _("Nombre de la fuente"), group=gf),
			Bool("reportFontSize", _("Tamaño de la fuente"), group=gf),
			Bool("reportFontAttributes", _("Atributos de la fuente (negrita, cursiva...)"), group=gf),
			Bool("reportSuperscriptsAndSubscripts", _("Superíndices y subíndices"), group=gf),
			Bool("reportEmphasis", _("Énfasis"), group=gf),
			Bool("reportHighlight", _("Texto resaltado"), group=gf),
			Bool("reportStyle", _("Estilo"), group=gf),
			Bool("reportColor", _("Colores"), group=gf),
			Choice("colorFormat", _("Cómo se dicen los colores:"), _colorFormatChoices, group=gf),
			Bool("reportSpellingErrors", _("Errores ortográficos"), group=gd),
			Bool("reportComments", _("Comentarios"), group=gd),
			Bool("reportRevisions", _("Revisiones del editor"), group=gd),
			Bool("reportPage", _("Páginas"), group=gp),
			Bool("reportLineNumber", _("Números de línea"), group=gp),
			Bool("reportAlignment", _("Alineación"), group=gp),
			Choice("reportLineIndentation", _("Sangría de las líneas:"), _INDENTATION, group=gp),
			Bool("ignoreBlankLinesForRLI", _("Ignorar las líneas en blanco al anunciar la sangría"), group=gp),
			Bool("reportParagraphIndentation", _("Sangría de los párrafos"), group=gp),
			Bool("reportLineSpacing", _("Interlineado"), group=gp),
			Bool("reportTables", _("Tablas"), group=gt),
			Bool("reportTableHeaders", _("Encabezados de filas y columnas de tablas"), group=gt),
			# #3566: atributo abbr de los encabezados.
			Bool("useHeaderAbbreviations", _("Usar la abreviatura de los encabezados (abbr) si la página la da"), group=gt),
			Bool("reportTableCellCoords", _("Coordenadas de las celdas"), group=gt),
			Choice("reportCellBorders", _("Bordes de las celdas:"), [("off", _("Desactivado")), ("styles", _("Estilos")), ("colorsAndStyles", _("Colores y estilos"))], group=gt),
			Bool("reportHeadings", _("Encabezados"), group=gs),
			Bool("reportLinks", _("Enlaces"), group=gs),
			Bool("reportLinkType", _("Tipo de enlace (enlaces a la misma página)"), group=gs),
			Bool("reportGraphics", _("Gráficos"), group=gs),
			Bool("reportLists", _("Listas"), group=gs),
			Bool("reportBlockQuotes", _("Citas"), group=gs),
			# #14654: comillas de <q>.
			Bool("reportQuotes", _("Citas en línea (comillas del elemento q)"), group=gs),
			Bool("reportGroupings", _("Agrupaciones"), group=gs),
			Bool("reportLandmarks", _("Puntos de referencia y regiones"), group=gs),
			Bool("reportArticles", _("Artículos"), group=gs),
			Bool("reportFrames", _("Marcos"), group=gs),
			Bool("reportFigures", _("Figuras y rótulos"), group=gs),
			Bool("reportDetails", _("Detalles y continuación del contenido"), group=gs),
			# También añade «pulsable» a los objetos con el foco (texto, grupos, imágenes...).
			Bool("reportClickable", _("Elementos en los que se puede hacer clic"), group=gs),
		]


def _ocrEngineChoices() -> ChoiceList:
	try:
		from .. import ocr

		return [(e.id, e.name) for e in ocr.ENGINES.values() if e.id == "windows" or e.isAvailable()]
	except Exception:
		log.debug("No se pudieron obtener los motores de OCR", exc_info=True)
		return [("windows", _("OCR de Windows"))]


def _tesseractLanguageChoices() -> ChoiceList:
	"""Idiomas de Tesseract (ejecuta ``tesseract --list-langs``: solo en un hilo propio)."""
	try:
		from .. import ocr

		langs = ocr.ENGINES["tesseract"].languages()
	except Exception:
		langs = []
	return [(lang, lang) for lang in langs] or [("eng", "eng"), ("spa", "spa")]


#: Listas del OCR obtenidas en un hilo propio (WinRT y ``tesseract --list-langs``
#: pueden tardar): el panel se construye con lo último conocido y se actualiza.
_ocrChoicesCache: dict[str, ChoiceList] = {}


def _collectOcrChoices() -> dict[str, ChoiceList]:
	"""Hilo propio: idiomas del OCR de Windows y de Tesseract."""
	return {"language": _ocrLanguageChoices(), "tesseractLanguage": _tesseractLanguageChoices()}


def _cachedOcrChoices(key: str) -> ChoiceList:
	if key in _ocrChoicesCache:
		return list(_ocrChoicesCache[key])
	if key == "language":
		return [("", _("Automático (idioma del sistema)"))]
	return [("eng", "eng"), ("spa", "spa")]


class OcrPanel(ConfigPanel):
	title = _("Reconocimiento de texto")
	section = "ocr"

	def getFields(self) -> list[Field]:
		from .. import ocr  # noqa: F401  (registra los valores por defecto)

		gr = _("Resultado")
		gc = _("Lectura continua (subtítulos)")
		gp = _("Documentos PDF")
		gt = _("Tesseract (si está instalado)")
		return [
			Choice("engine", _("Motor de reconocimiento:"), _ocrEngineChoices),
			Choice("language", _("Idioma del OCR de Windows:"), lambda: _cachedOcrChoices("language")),
			Bool("browseModeResult", _("Abrir el resultado en modo exploración"), group=gr),
			Bool("autoSayAll", _("Leer el resultado automáticamente con leer todo"), group=gr),
			Bool("autoRefresh", _("Actualizar periódicamente el resultado del reconocimiento"), group=gr),
			Int("autoRefreshInterval", _("Intervalo de actualización (milisegundos):"), 250, 60000, group=gr),
			Int("continuousInterval", _("Intervalo de la lectura continua (milisegundos):"), 300, 60000, group=gc),
			Int("continuousSimilarity", _("Parecido para considerar repetida una línea (por ciento):"), 50, 100, group=gc),
			Int("pdfScale", _("Resolución de las páginas PDF (multiplicador):"), 1, 4, group=gp),
			Int("pdfMaxPages", _("Máximo de páginas de un PDF (0: todas):"), 0, 5000, group=gp),
			Choice("tesseractLanguage", _("Idioma de Tesseract:"), lambda: _cachedOcrChoices("tesseractLanguage"), group=gt),
			Text("tesseractPath", _("Carpeta o ejecutable de Tesseract (vacío: buscarlo):"), group=gt),
		]

	def makeExtraSettings(self, builder: SettingsBuilder) -> None:
		runInThread(_collectOcrChoices, callback=self._onOcrChoices, name="TiresiasIdiomasOcr")

	def _onOcrChoices(self, result: dict[str, ChoiceList] | None, error: BaseException | None) -> None:
		if not result:
			return
		_ocrChoicesCache.update(result)
		if not isAlive(self):
			return
		for key, choices in result.items():
			self.updateChoices(key, choices)


_MAG_LEVELS = [(v, (str(int(v)) if float(v).is_integer() else str(v).replace(".", ",")) + " x") for v in (1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 16.0)]
_MAG_STEPS = [(0.25, "0,25"), (0.5, "0,5"), (1.0, "1"), (2.0, "2")]


def _magChoices(name: str) -> ChoiceList:
	from .. import magnifier as m

	if name == "views":
		return [(k, m.VIEW_LABELS[k].capitalize()) for k in m.VIEWS]
	if name == "tracking":
		return [(k, m.TRACKING_LABELS[k].capitalize()) for k in m.TRACKING_MODES]
	if name == "dock":
		return [(k, v.capitalize()) for k, v in m.DOCK_POSITIONS.items()]
	return [(k, m.FILTER_LABELS[k].capitalize()) for k in m.FILTER_MATRICES]


class MagnifierPanel(ConfigPanel):
	title = _("Lupa")
	section = "magnifier"

	def getFields(self) -> list[Field]:
		from .. import magnifier  # noqa: F401  (registra los valores por defecto)

		gv = _("Vista y ampliación")
		gs = _("Seguimiento")
		gw = _("Ventana acoplada, lente y foco")
		return [
			Bool("enableAtStartup", _("Activar la lupa al iniciar Tiresias")),
			Choice("view", _("Vista:"), lambda: _magChoices("views"), group=gv),
			Choice("level", _("Nivel de ampliación:"), _MAG_LEVELS, group=gv),
			Choice("step", _("Paso al aumentar o reducir:"), _MAG_STEPS, group=gv),
			Int("panStep", _("Desplazamiento de la vista (porcentaje de la pantalla):"), 1, 50, group=gv),
			Choice("filter", _("Filtro de color:"), lambda: _magChoices("filters"), group=gv),
			Int("overviewSeconds", _("Duración de la vista general (segundos):"), 1, 30, group=gv),
			Bool("followFocus", _("Seguir al foco del sistema"), group=gs),
			Bool("followCaret", _("Seguir al cursor del sistema"), group=gs),
			Bool("followReview", _("Seguir al cursor de revisión"), group=gs),
			Bool("followNavigator", _("Seguir al objeto navegador"), group=gs),
			Bool("followMouse", _("Seguir al ratón"), group=gs),
			Choice("trackingMode", _("Modo de seguimiento:"), lambda: _magChoices("tracking"), group=gs),
			Choice("dockPosition", _("Posición de la ventana acoplada:"), lambda: _magChoices("dock"), group=gw),
			Int("dockSize", _("Tamaño de la ventana acoplada (por ciento de la pantalla):"), 10, 70, group=gw),
			Int("lensWidth", _("Anchura de la lente (píxeles):"), 100, 2000, group=gw),
			Int("lensHeight", _("Altura de la lente (píxeles):"), 60, 1500, group=gw),
			Int("spotlightOpacity", _("Oscurecimiento alrededor del foco (por ciento):"), 10, 95, group=gw),
			Bool("showMouseCursor", _("Mostrar el puntero del ratón en la ventana de lupa"), group=gw),
		]

	def afterSave(self, changes: dict[tuple[str, str], tuple[Any, Any]]) -> None:
		from ..magnifier import magnifier

		if magnifier.active:
			magnifier._rebuildView()


_HIGHLIGHT_COLOR_KEYS = ("highlightColor", "highlightNavigatorColor", "highlightBrowseModeColor", "highlightMouseColor")


class VisionPanel(ConfigPanel):
	title = _("Visión")
	section = "vision"

	def getFields(self) -> list[Field]:
		from .. import vision  # noqa: F401  (registra los valores por defecto)

		gc = _("Cortina de pantalla")
		gh = _("Resaltado visual")
		return [
			Bool("screenCurtain", _("Cortina de pantalla (oscurecer la pantalla)"), group=gc),
			Bool("curtainWarnOnEnable", _("Pedir confirmación al activar la cortina con su orden"), group=gc),
			Bool("curtainPlaySounds", _("Sonido al activar o desactivar la cortina"), group=gc),
			Bool("curtainReportAtStartup", _("Anunciar al arrancar que la cortina está activada"), group=gc),
			Bool("highlightFocus", _("Resaltar el foco del sistema"), group=gh),
			Text("highlightColor", _("Color del foco (#RRGGBB):"), group=gh),
			Bool("highlightNavigator", _("Resaltar el objeto navegador"), group=gh),
			Text("highlightNavigatorColor", _("Color del objeto navegador (#RRGGBB):"), group=gh),
			Bool("highlightBrowseMode", _("Resaltar el cursor del modo exploración"), group=gh),
			Text("highlightBrowseModeColor", _("Color del cursor del modo exploración (#RRGGBB):"), group=gh),
			Bool("highlightMouse", _("Resaltar el objeto bajo el ratón"), group=gh),
			Text("highlightMouseColor", _("Color del objeto bajo el ratón (#RRGGBB):"), group=gh),
			Int("highlightThickness", _("Grosor del resaltado (píxeles):"), 1, 30, group=gh),
			Int("highlightPadding", _("Separación entre el objeto y el marco (píxeles):"), 0, 30, group=gh),
			Int("highlightRefreshInterval", _("Actualizar la posición cada (milisegundos, 0: nunca):"), 0, 10000, group=gh),
		]

	def isValid(self) -> bool:
		for key in _HIGHLIGHT_COLOR_KEYS:
			color = str(self.getValue(key) or "").strip()
			ok = len(color) == 7 and color.startswith("#")
			if ok:
				try:
					int(color[1:], 16)
				except ValueError:
					ok = False
			if not ok:
				showError(_("Los colores del resaltado deben tener el formato #RRGGBB, por ejemplo #FF0000."), self)
				ctrl = self.getControl(key)
				if ctrl:
					ctrl.SetFocus()
				return False
		return True

	def afterSave(self, changes: dict[tuple[str, str], tuple[Any, Any]]) -> None:
		from .. import vision

		if ("vision", "screenCurtain") in changes:
			queue_handler.queueFunction(vision.handler.setScreenCurtain, bool(changes[("vision", "screenCurtain")][1]))
		if any(k != ("vision", "screenCurtain") for k in changes):
			queue_handler.queueFunction(vision.handler.forceRedraw)


class ClipboardPanel(ConfigPanel):
	title = _("Portapapeles")
	section = "clipboard"
	fields = [
		Bool("announceCopy", _("Anunciar el texto copiado"), group=_("Anuncios")),
		Bool("announceCutCopyPaste", _("Distinguir cortar, copiar y pegar al usar sus teclas"), group=_("Anuncios")),
		Bool("announcePastedText", _("Leer el texto pegado"), group=_("Anuncios")),
		Bool("confirmCopyCommands", _("Decir «Copiado al portapapeles» al copiar con órdenes de Tiresias"), group=_("Anuncios")),
		Bool("historyEnabled", _("Guardar un historial del portapapeles"), group=_("Historial")),
		Int("historySize", _("Tamaño del historial (elementos):"), 1, 1000, group=_("Historial")),
		Bool("persistHistory", _("Conservar el historial al cerrar Tiresias"), group=_("Historial")),
		Choice("appendSeparator", _("Separador al añadir texto al portapapeles:"), [("newline", _("Salto de línea")), ("blankLine", _("Línea en blanco")), ("space", _("Espacio")), ("none", _("Ninguno"))]),
	]


_DIFF_CHOICES: ChoiceList = [
	("characters", _("Por caracteres (solo lo que cambia en cada línea)")),
	("lines", _("Por líneas completas")),
]
_WATCHDOG_MODES: ChoiceList = [
	("off", _("Solo registrarlo")),
	("cancel", _("Cancelar la llamada que lo bloquea")),
	("restart", _("Cancelar la llamada y, si no basta, reiniciar Tiresias")),
]


def _debugCategoryChoices() -> ChoiceList:
	from ..log import DEBUG_CATEGORIES

	labels = {
		"eventos": _("Eventos"),
		"entrada": _("Teclado y entrada"),
		"voz": _("Voz y símbolos"),
		"uia": _("UI Automation"),
		"exploracion": _("Modo exploración"),
		"sintetizador": _("Sintetizadores y audio"),
		"braille": _("Braille"),
		"complementos": _("Complementos y módulos de aplicación"),
		"ocr": _("Reconocimiento de texto"),
	}
	return [(k, labels.get(k, k)) for k in DEBUG_CATEGORIES]


class AdvancedPanel(ConfigPanel):
	title = _("Avanzado")
	section = "advanced"

	#: Grupo de Java (el estado de Java Access Bridge y su botón van dentro).
	JAVA_GROUP = _("Aplicaciones Java")

	def getFields(self) -> list[Field]:
		ge = _("Errores y registro")
		gw = _("Bloqueos del núcleo")
		gu = _("UI Automation")
		gm = _("MSAA, IAccessible2 y clases de ventana")
		gt = _("Consolas y terminales")
		gj = self.JAVA_GROUP
		gs = _("Integración con Windows")
		gd = _("Desarrollo")
		# Los visores de voz y braille están en «Voz» y en «Presentación braille»; las
		# notificaciones en segundo plano, en «Presentación de objetos».
		return [
			Bool("playErrorSound", _("Reproducir un sonido al registrarse un error"), group=ge),
			Field("debugCategories", _("Registro de depuración de estas partes:"), "checklist", choices=_debugCategoryChoices, group=ge),
			Int("watchdogTimeout", _("Tiempo para considerar bloqueado el núcleo (segundos):"), 2, 120, group=gw),
			Choice("watchdogRecovery", _("Si el núcleo se bloquea:"), _WATCHDOG_MODES, group=gw),
			Int("watchdogRestartTimeout", _("Reiniciar Tiresias si sigue bloqueado tras (segundos):"), 5, 600, group=gw),
			Int("connectionTimeout", _("Tiempo de espera de las llamadas (milisegundos, se aplica al reiniciar):"), 100, 30000, section="uia", group=gu),
			Choice("eventRegistration", _("Registro de eventos:"), [("selective", _("Selectivo (cambios de nombre y descripción solo del foco)")), ("global", _("Global (cambios de nombre y descripción de cualquier objeto)"))], section="uia", group=gu),
			Int("eventCoalesceMs", _("Agrupación de eventos repetidos (milisegundos):"), 0, 1000, group=gu),
			Bool("honorNotificationProcessing", _("Cortar la notificación anterior cuando la aplicación lo pida"), section="uia", group=gu),
			Bool("useIA2", _("Usar MSAA e &IAccessible2 en las aplicaciones sin UI Automation propio (LibreOffice, Qt…)"), section="objects", group=gm),
			ListText("msaaClasses", _("Clases de ventana que se leen con &MSAA, separadas por comas:"), section="objects", group=gm),
			ListText("uiaClasses", _("Clases de ventana que se leen siempre con &UI Automation, separadas por comas:"), section="objects", group=gm),
			Int("slowProviderThresholdMs", _("Considerar &lenta una aplicación que tarda más de (milisegundos):"), 100, 10000, section="objects", group=gm),
			Bool("preferUIAForConsoles", _("Usar UI Automation en las con&solas de Windows"), section="uia", group=gt),
			Choice("diffAlgorithm", _("Lectura del texto &nuevo en las consolas:"), _DIFF_CHOICES, section="terminal", group=gt),
			Bool("speakPasswords", _("Leer lo &escrito aunque la consola no lo muestre (contraseñas)"), section="terminal", group=gt),
			Int("maxLinesPerUpdate", _("Máximo de líneas que se leen de una &vez:"), 1, 1000, section="terminal", group=gt),
			Bool("enabled", _("Usar &Java Access Bridge con las aplicaciones Java"), section="java", group=gj),
			Bool("askToEnable", _("Preguntar si se activa Java Access &Bridge cuando hace falta"), section="java", group=gj),
			Bool("setScreenReaderFlag", _("Indicar a &Windows que hay un lector de pantalla activo"), section="system", group=gs),
			Bool("registerAsAT", _("Registrar Tiresias como &tecnología de asistencia de Windows"), section="system", group=gs),
			# addons.loadAll lo lee al cargar los complementos (al arrancar o al recargarlos).
			Bool("enableScratchpad", _("Cargar código de desarrollo desde la carpeta «scratchpad» (al reiniciar o recargar los complementos)"), group=gd),
		]

	def makeExtraSettings(self, builder: SettingsBuilder) -> None:
		self._makeJavaStatus(self._groups.get(self.JAVA_GROUP) or builder)
		btn = builder.addButton(_("Abrir carpeta de &datos"))
		btn.Bind(wx.EVT_BUTTON, self._onOpenData)
		btn = builder.addButton(_("&Restablecer valores de fábrica"))
		btn.Bind(wx.EVT_BUTTON, self._onFactoryReset)
		self._undoButton = builder.addButton(_("Des&hacer el restablecimiento de fábrica"))
		self._undoButton.Bind(wx.EVT_BUTTON, self._onUndoReset)
		self._undoButton.Enable(conf.canUndoFactoryReset)

	# --------------------------------------------------- Java Access Bridge
	def _makeJavaStatus(self, g: SettingsBuilder) -> None:
		from ..a11y import jab

		dll = jab.findDll()
		if not dll:
			status = _("Java Access Bridge: no se ha encontrado ningún Java de 64 bits instalado.")
		elif jab.isBridgeEnabled():
			status = _("Java Access Bridge: activado para este usuario ({path}).").format(path=dll)
		else:
			status = _("Java Access Bridge: encontrado ({path}) pero no activado para este usuario.").format(path=dll)
		self._jabStatus = g.addStaticText(status)
		btn = g.addButton(_("&Activar Java Access Bridge para este usuario…"))
		btn.Bind(wx.EVT_BUTTON, self._onEnableJab)
		btn.Enable(bool(dll) and not jab.isBridgeEnabled())
		self._jabButton = btn

	def _onEnableJab(self, evt: wx.CommandEvent | None) -> None:
		from ..a11y import jab

		if not askYesNo(
			_("Se activará Java Access Bridge para su usuario (jabswitch o el archivo .accessibility.properties). Las aplicaciones Java abiertas deben reiniciarse. ¿Continuar?"),
			_("Java Access Bridge"),
			self,
		):
			return
		# jabswitch puede tardar hasta 20 s: se ejecuta en un hilo propio y el
		# resultado vuelve a la interfaz con wx.CallAfter.
		self._jabButton.Enable(False)

		def work() -> bool:
			return bool(jab.enableBridge())

		runInThread(work, callback=self._onJabDone, name="TiresiasJabEnable")

	def _onJabDone(self, ok: Any, error: BaseException | None = None) -> None:
		if not isAlive(self):
			return
		if ok and error is None:
			self._jabStatus.SetLabel(_("Java Access Bridge: activado para este usuario. Reinicie las aplicaciones Java."))
			self._jabButton.Enable(False)
		else:
			self._jabButton.Enable(True)
			showError(_("No se pudo activar Java Access Bridge."), self)
		self.relayout()

	def afterSave(self, changes: dict[tuple[str, str], tuple[Any, Any]]) -> None:
		from ..a11y import api_choice, system

		if any(sec in ("java", "system") for sec, _key in changes):
			queue_handler.queueFunction(system.applyConfig)
		# La elección de API de cada ventana se recuerda: se olvida si cambia lo que la decide.
		if any(k in changes for k in (("objects", "useIA2"), ("objects", "msaaClasses"), ("objects", "uiaClasses"), ("uia", "preferUIAForConsoles"), ("java", "enabled"))):
			queue_handler.queueFunction(api_choice.invalidate)

	def _onUndoReset(self, evt: wx.CommandEvent) -> None:
		from . import system_dialogs

		system_dialogs.undoFactoryReset()
		dlg = wx.GetTopLevelParent(self)
		if isinstance(dlg, SettingsDialog):
			wx.CallAfter(dlg.closeWithoutSaving)

	def _onOpenData(self, evt: wx.CommandEvent) -> None:
		from ..config import policy as policyModule

		if not policyModule.isAllowed("openDataFolder"):
			# Política del equipo o modo seguro (como el menú Herramientas).
			showError(policyModule.blockedMessage(), self)
			return
		try:
			os.makedirs(paths.DATA_DIR, exist_ok=True)
			os.startfile(paths.DATA_DIR)
		except OSError as e:
			showError(_("No se pudo abrir la carpeta: {error}").format(error=e), self)

	def _onFactoryReset(self, evt: wx.CommandEvent) -> None:
		from ..config import policy as policyModule
		from . import system_dialogs

		if not policyModule.isAllowed("factoryReset"):
			showError(policyModule.blockedMessage(), self)
			return
		if not askYesNo(
			_("¿Seguro que desea restablecer toda la configuración a los valores de fábrica? Se cerrará este diálogo."),
			_("Restablecer valores de fábrica"),
			self,
		):
			return
		system_dialogs.resetToFactory()
		dlg = wx.GetTopLevelParent(self)
		if isinstance(dlg, SettingsDialog):
			wx.CallAfter(dlg.closeWithoutSaving)
		# Tras cerrar Opciones se ofrece deshacerlo (#19575).
		wx.CallAfter(system_dialogs.offerUndo, None)


# ====================================================================== registro de paneles
_panels: "OrderedDict[str, tuple[str, type[SettingsPanel]]]" = OrderedDict(
	[
		("general", (GeneralPanel.title, GeneralPanel)),
		("speech", (SpeechPanel.title, SpeechPanel)),
		("audio", (AudioPanel.title, AudioPanel)),
		("braille", (BraillePanel.title, BraillePanel)),
		("keyboard", (KeyboardPanel.title, KeyboardPanel)),
		("mouse", (MousePanel.title, MousePanel)),
		("reviewCursor", (ReviewCursorPanel.title, ReviewCursorPanel)),
		("presentation", (PresentationPanel.title, PresentationPanel)),
		("browseMode", (BrowseModePanel.title, BrowseModePanel)),
		("documentFormatting", (DocumentFormattingPanel.title, DocumentFormattingPanel)),
		("ocr", (OcrPanel.title, OcrPanel)),
		("vision", (VisionPanel.title, VisionPanel)),
		("magnifier", (MagnifierPanel.title, MagnifierPanel)),
		("clipboard", (ClipboardPanel.title, ClipboardPanel)),
		("advanced", (AdvancedPanel.title, AdvancedPanel)),
	]
)


def registerPanel(id: str, title: str, panelClass: type[SettingsPanel]) -> None:
	"""Añade (o sustituye) una categoría del diálogo de opciones."""
	if not (isinstance(panelClass, type) and issubclass(panelClass, SettingsPanel)):
		raise TypeError("panelClass debe heredar de SettingsPanel")
	_panels[id] = (title, panelClass)


def unregisterPanel(id: str) -> None:
	_panels.pop(id, None)


#: Categoría que va siempre al final de la lista, aunque se registren otras después.
LAST_PANEL = "advanced"
#: Orden de las categorías incorporadas, como en NVDA (General, Voz, Braille,
#: Audio, Visión, Teclado, Ratón...), con las de Tiresias en su sitio lógico.
#: No depende del orden en que los módulos registran sus categorías al arrancar.
PANEL_ORDER: tuple[str, ...] = tuple(_contextHelp.CATEGORY_IDS)
#: Las categorías de los complementos (sin sitio en :data:`PANEL_ORDER`) van detrás de esta.
ADDON_PANELS_AFTER = "apps"
#: Categorías que se han unido a otras (1.0.6): las órdenes, los complementos y
#: los perfiles que aún las nombran abren la categoría que las recoge.
PANEL_ALIASES = {"mixer": "audio", "brailleDisplays": "braille", "uia": "advanced", "objects": "advanced"}


def resolvePanelId(id: str | None) -> str | None:
	"""Identificador de la categoría, siguiendo :data:`PANEL_ALIASES`."""
	return PANEL_ALIASES.get(id, id) if id else id


def getPanelIds() -> list[str]:
	"""Categorías en el orden del cuadro de Opciones («Avanzado», la última).

	Las incorporadas siguen :data:`PANEL_ORDER`; las de los complementos van
	detrás de «Aplicaciones», en el orden en que se registraron.
	"""
	known = [i for i in PANEL_ORDER if i in _panels and i != LAST_PANEL]
	extra = [i for i in _panels if i not in PANEL_ORDER]
	pos = known.index(ADDON_PANELS_AFTER) + 1 if ADDON_PANELS_AFTER in known else len(known)
	ids = known[:pos] + extra + known[pos:]
	if LAST_PANEL in _panels:
		ids.append(LAST_PANEL)
	return ids


# ====================================================================== diálogo de opciones
class SettingsDialog(wx.Dialog):
	def __init__(self, parent: wx.Window | None, category: str | None = None) -> None:
		super().__init__(parent, title=_("Opciones"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._closeCallbacks: list[Callable[[], None]] = []
		self._ids = getPanelIds()
		self._panels: dict[str, SettingsPanel] = {}
		self._current: str | None = None
		self._updateTitle()

		main = wx.BoxSizer(wx.VERTICAL)
		body = wx.BoxSizer(wx.HORIZONTAL)
		left = wx.BoxSizer(wx.VERTICAL)
		left.Add(wx.StaticText(self, label=_("&Categorías:")), 0, wx.BOTTOM, 2)
		self.categories = wx.ListBox(self, choices=[_panels[i][0] for i in self._ids], style=wx.LB_SINGLE, size=(200, -1))
		left.Add(self.categories, 1, wx.EXPAND)
		body.Add(left, 0, wx.EXPAND | wx.ALL, 8)

		self.container = wx.ScrolledWindow(self, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
		self.container.SetScrollRate(0, 20)
		self.containerSizer = wx.BoxSizer(wx.VERTICAL)
		self.container.SetSizer(self.containerSizer)
		self.container.SetMinSize((620, 480))
		body.Add(self.container, 1, wx.EXPAND | wx.TOP | wx.BOTTOM | wx.RIGHT, 8)
		main.Add(body, 1, wx.EXPAND)

		bottom = wx.BoxSizer(wx.HORIZONTAL)
		# Sin tecla rápida: todas las letras pueden estar en uso en alguna categoría.
		self.resetButton = wx.Button(self, label=_("Valores de fábrica de esta categoría"))
		self.resetButton.SetToolTip(_("Pone las opciones de la categoría con sus valores de fábrica. Se guardan al pulsar Aceptar o Aplicar."))
		bottom.Add(self.resetButton, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 8)
		bottom.AddStretchSpacer(1)
		buttons = wx.StdDialogButtonSizer()
		self.okButton = wx.Button(self, wx.ID_OK, _("Aceptar"))
		self.cancelButton = wx.Button(self, wx.ID_CANCEL, _("Cancelar"))
		self.applyButton = wx.Button(self, wx.ID_APPLY, _("A&plicar"))
		buttons.AddButton(self.okButton)
		buttons.AddButton(self.cancelButton)
		buttons.AddButton(self.applyButton)
		buttons.Realize()
		bottom.Add(buttons, 0, wx.ALL, 8)
		main.Add(bottom, 0, wx.EXPAND)
		self.okButton.SetDefault()
		self.SetAffirmativeId(wx.ID_OK)
		self.SetEscapeId(wx.ID_CANCEL)

		self.SetSizer(main)
		self.categories.Bind(wx.EVT_LISTBOX, self._onCategory)
		self.okButton.Bind(wx.EVT_BUTTON, self._onOk)
		self.cancelButton.Bind(wx.EVT_BUTTON, self._onCancel)
		self.applyButton.Bind(wx.EVT_BUTTON, self._onApply)
		self.resetButton.Bind(wx.EVT_BUTTON, self._onResetCategory)
		self.Bind(wx.EVT_CLOSE, self._onClose)
		self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)

		category = resolvePanelId(category)
		self.selectCategory(category if category in self._ids else self._ids[0])
		main.Fit(self)
		self.SetSize((max(self.GetSize()[0], 900), max(self.GetSize()[1], 620)))
		self.CentreOnScreen()
		self.categories.SetFocus()

	# --------------------------------------------------- utilidades
	def _updateTitle(self) -> None:
		name = conf.editProfile or conf.activeProfileName
		if name:
			self.SetTitle(_("Opciones: {profile}").format(profile=name))
		else:
			self.SetTitle(_("Opciones: configuración normal"))

	def addCloseCallback(self, func: Callable[[], None]) -> None:
		self._closeCallbacks.append(func)

	def getPanel(self, id: str) -> SettingsPanel | None:
		return self._panels.get(id)

	def relayoutContainer(self) -> None:
		self.container.Layout()
		self.container.FitInside()

	def _getOrCreatePanel(self, id: str) -> SettingsPanel | None:
		panel = self._panels.get(id)
		if panel is not None:
			return panel
		title, cls = _panels[id]
		try:
			panel = cls(self.container)
		except Exception:
			log.exception("No se pudo crear el panel %s", id)
			showError(_("No se pudo mostrar la categoría «{title}».").format(title=title), self)
			return None
		if not panel.title:
			panel.title = title
		panel.Hide()
		self.containerSizer.Add(panel, 1, wx.EXPAND)
		self._panels[id] = panel
		return panel

	def selectCategory(self, id: str) -> None:
		id = resolvePanelId(id) or ""
		if id not in self._ids:
			return
		index = self._ids.index(id)
		if self.categories.GetSelection() != index:
			self.categories.SetSelection(index)
		if self._current == id:
			return
		panel = self._getOrCreatePanel(id)
		if panel is None:
			return
		self.Freeze()
		try:
			if self._current and self._current in self._panels:
				self._panels[self._current].onPanelDeactivated()
			self._current = id
			panel.onPanelActivated()
			self.relayoutContainer()
			self.container.Scroll(0, 0)
		finally:
			self.Thaw()

	def _onCategory(self, evt: wx.CommandEvent) -> None:
		i = self.categories.GetSelection()
		if 0 <= i < len(self._ids):
			self.selectCategory(self._ids[i])

	def _onCharHook(self, evt: wx.KeyEvent) -> None:
		if evt.GetKeyCode() == wx.WXK_TAB and evt.ControlDown():
			i = self.categories.GetSelection()
			step = -1 if evt.ShiftDown() else 1
			newId = self._ids[(i + step) % len(self._ids)]
			self.selectCategory(newId)
			panel = self._panels.get(newId)
			if panel is not None:
				panel.SetFocus()
				child = panel.GetChildren()
				for c in child:
					if c.AcceptsFocus():
						c.SetFocus()
						break
			return
		if evt.GetKeyCode() == wx.WXK_F1 and not evt.HasAnyModifiers():
			self.showContextHelp()
			return
		evt.Skip()

	def showContextHelp(self) -> None:
		"""F1: abre el manual en el apartado de la opción con el foco."""
		from . import context_help

		panelId = self._current
		key = None
		focus = wx.Window.FindFocus()
		panel = self._panels.get(panelId) if panelId else None
		if focus is self.categories:
			i = self.categories.GetSelection()
			panelId = self._ids[i] if 0 <= i < len(self._ids) else panelId
		elif panel is not None and isinstance(panel, ConfigPanel):
			win = focus
			while win is not None and win is not panel and key is None:
				key = panel.fieldForControl(win)
				win = win.GetParent()
		context_help.openHelp(panelId, key)

	# --------------------------------------------------- guardar / cancelar
	def _saveAll(self) -> bool:
		for id, panel in self._panels.items():
			if not panel.isValid():
				self.selectCategory(id)
				return False
		failed: list[str] = []
		for id, panel in self._panels.items():
			try:
				panel.onSave()
			except Exception:
				log.exception("Error guardando el panel %s", id)
				failed.append(id)
		from .. import core

		queue_handler.queueFunction(core.applyConfiguration)
		if failed:
			# No se cierra: el usuario sabe qué falló y puede reintentar o cancelar.
			self.selectCategory(failed[0])
			titles = ", ".join(self._panels[i].title for i in failed)
			showError(_("No se pudieron guardar las opciones de: {panels}. El resto de cambios sí se ha guardado. Encontrará los detalles en el registro.").format(panels=titles), self)
			return False
		return True

	def _onOk(self, evt: wx.CommandEvent) -> None:
		if self._saveAll():
			self._finish()

	def _onApply(self, evt: wx.CommandEvent) -> None:
		self._saveAll()

	def resetCategory(self) -> bool:
		"""Pone la categoría actual con sus valores de fábrica (sin guardar)."""
		panel = self._panels.get(self._current) if self._current else None
		if panel is None:
			return False
		try:
			panel.resetToFactory()
		except Exception:
			log.exception("No se pudieron poner los valores de fábrica de %s", self._current)
			return False
		return True

	def _onResetCategory(self, evt: wx.CommandEvent) -> None:
		if self.resetCategory():
			speakMessageOnCore(_("Valores de fábrica puestos en esta categoría. Pulse Aceptar o Aplicar para guardarlos."))

	def _onCancel(self, evt: wx.CommandEvent) -> None:
		self._discardAll()
		self._finish()

	def _onClose(self, evt: wx.CloseEvent) -> None:
		self._discardAll()
		self._finish()

	def _discardAll(self) -> None:
		for id, panel in self._panels.items():
			try:
				panel.onDiscard()
			except Exception:
				log.exception("Error descartando el panel %s", id)

	def closeWithoutSaving(self) -> None:
		self._finish()

	def _finish(self) -> None:
		global _settingsDialog
		if _settingsDialog is self:
			_settingsDialog = None
		callbacks, self._closeCallbacks = self._closeCallbacks, []
		self.Hide()
		self.Destroy()
		for func in callbacks:
			try:
				func()
			except Exception:
				log.exception("Error en la llamada de cierre de opciones")


_settingsDialog: SettingsDialog | None = None


def getSettingsDialog() -> SettingsDialog | None:
	"""Diálogo de opciones abierto, si lo hay."""
	if _settingsDialog is not None and isAlive(_settingsDialog):
		return _settingsDialog
	return None


def showSettings(category: str | None = None, onClose: Callable[[], None] | None = None) -> None:
	"""Abre el diálogo de opciones en la categoría indicada (o lo trae al frente).

	``onClose`` se llama (en el hilo de la interfaz) cuando el diálogo se cierra.
	Debe llamarse desde el hilo de la interfaz.
	"""
	global _settingsDialog
	dlg = getSettingsDialog()
	if dlg is None:
		dlg = _settingsDialog = SettingsDialog(parentWindow(), category)
	elif category:
		dlg.selectCategory(category)
	if onClose is not None:
		dlg.addCloseCallback(onClose)
	presentDialog(dlg)


def _onSynthChanged() -> None:
	"""Actualiza el panel de voz abierto tras cambiar de sintetizador."""
	dlg = getSettingsDialog()
	if dlg is None:
		return
	panel = dlg.getPanel("speech")
	if isinstance(panel, SpeechPanel) and isAlive(panel):
		panel.reloadSynth()


# ====================================================================== selección de sintetizador
class SynthSelectionDialog(wx.Dialog):
	def __init__(self, parent: wx.Window | None) -> None:
		super().__init__(parent, title=_("Seleccionar sintetizador"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._names: list[str] = ["auto"]
		self._currentName: str | None = None
		main = wx.BoxSizer(wx.VERTICAL)
		builder = SettingsBuilder(self, main)
		self.synthList = builder.addLabeledControl(
			_("&Sintetizador:"),
			lambda p: wx.ListBox(p, choices=[_("Automático (el mejor disponible)")], style=wx.LB_SINGLE, size=(360, 180)),
			vertical=True,
			proportion=1,
		)
		self.synthList.SetSelection(0)
		# El dispositivo de salida está en la categoría «Audio» (como en NVDA): una sola opción.
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
		self.CentreOnScreen()
		self.synthList.SetFocus()
		runOnCore(self._collect, callback=self._onCollected)

	@staticmethod
	def _collect() -> tuple[list[tuple[str, str]], str | None]:
		from .. import synth as synthHandler

		cur = synthHandler.getSynth()
		return synthHandler.getSynthList(), (cur.name if cur else None)

	def _onCollected(self, result: tuple[list[tuple[str, str]], str | None] | None) -> None:
		if not isAlive(self) or result is None:
			return
		synths, current = result
		self._currentName = current
		wanted = _confValue("speech", "synth", "auto") or "auto"
		prevSel = self.synthList.GetSelection()
		prevName = self._names[prevSel] if 0 <= prevSel < len(self._names) else None
		self._names = ["auto"] + [n for n, _d in synths]
		self.synthList.Set([_("Automático (el mejor disponible)")] + [d for _n, d in synths])
		if prevName and prevName != "auto":
			target = prevName
		else:
			target = wanted if wanted in self._names else (current if current in self._names else "auto")
		self.synthList.SetSelection(self._names.index(target) if target in self._names else 0)

	def _onOk(self, evt: wx.CommandEvent) -> None:
		i = self.synthList.GetSelection()
		name = self._names[i] if 0 <= i < len(self._names) else "auto"
		synthChanged = (_confValue("speech", "synth", "auto") or "auto") != name
		# Sin cambios (y con el sintetizador elegido ya cargado) no se recarga nada:
		# recargar cortaría la voz y los ajustes en curso.
		if not synthChanged and (name == "auto" or name == self._currentName):
			self._close()
			return
		if synthChanged:
			conf["speech"]["synth"] = name
		queue_handler.queueFunction(_applySynthSelection, name)
		self._close()

	def _close(self) -> None:
		global _synthDialog
		if _synthDialog is self:
			_synthDialog = None
		self.Hide()
		self.Destroy()


def _applySynthSelection(name: str) -> None:
	"""Carga el sintetizador elegido (hilo del núcleo) y avisa a la interfaz."""
	from .. import synth as synthHandler

	synthHandler.setSynth(name)
	cur = synthHandler.getSynth()
	if name not in ("auto", "") and (cur is None or cur.name != name):
		loaded = cur.description if cur else _("ninguno")

		def report() -> None:
			showError(
				_("No se pudo cargar el sintetizador seleccionado. Se está usando: {synth}.").format(synth=loaded),
				parentWindow(),
			)

		wx.CallAfter(report)
	wx.CallAfter(_onSynthChanged)


_synthDialog: SynthSelectionDialog | None = None


def showSynthSelection() -> None:
	"""Abre el diálogo «Seleccionar sintetizador» (hilo de la interfaz)."""
	global _synthDialog
	if _synthDialog is None or not isAlive(_synthDialog):
		parent = getSettingsDialog() or parentWindow()
		_synthDialog = SynthSelectionDialog(parent)
	presentDialog(_synthDialog)



# Categoría «Presentación braille» (va justo después de «Braille»).
from . import braille_panels as _braillePanels  # noqa: E402,F401

# Categorías «Navegación por documentos», «Composición de entrada (IME)» y
# «Actualizaciones y complementos» (área de configuración).
from . import config_panels as _configPanels  # noqa: E402,F401
