"""Braille: presentación del foco, del cursor y de mensajes en líneas braille.

Los controladores de línea braille heredan de :class:`BrailleDisplayDriver`
y pueden venir en complementos (carpeta ``brailleDisplayDrivers``). Tiresias
incluye «Sin braille» y el «Visor braille» en pantalla.
"""

from __future__ import annotations

import importlib
import types
from typing import Any

from .. import api, queue_handler
from ..baseobject import ScriptableObject
from ..config import conf
from ..extension_points import Action
from ..i18n import _
from ..log import getLogger
from . import tables  # noqa: F401  (submódulo accesible como braille.tables)
from .presenter import BraillePresenter, objectProperties, objectText  # noqa: F401

log = getLogger("braille")

#: Tras actualizar la línea: ``cells``, ``text``.
post_displayUpdate = Action()


class BrailleDisplayDriver(ScriptableObject):
	"""Clase base de los controladores de línea braille.

	Las teclas de la línea se convierten en gestos ``br(<nombre>):<tecla>``
	que se asocian a órdenes como cualquier otro gesto.
	"""

	name = ""
	description = ""
	numCells = 0

	@classmethod
	def check(cls) -> bool:
		return False

	def display(self, cells: list[int]) -> None:
		raise NotImplementedError

	def terminate(self) -> None:
		pass


class NoBrailleDriver(BrailleDisplayDriver):
	name = "noBraille"
	description = _("Sin braille")
	numCells = 0

	@classmethod
	def check(cls) -> bool:
		return True

	def display(self, cells: list[int]) -> None:
		pass


class ViewerDriver(BrailleDisplayDriver):
	"""Visor braille en pantalla (útil para personas que ayudan o para pruebas)."""

	name = "viewer"
	description = _("Visor braille en pantalla")

	@classmethod
	def check(cls) -> bool:
		return True

	def __init__(self) -> None:
		super().__init__()
		self.numCells = conf["braille"]["numCellsForViewer"]
		from ..gui import braille_viewer

		braille_viewer.show(self.numCells)

	def display(self, cells: list[int]) -> None:
		from ..gui import braille_viewer

		braille_viewer.update(cells, self._text, self._labels)

	_text = ""
	_labels: list[str] | None = None

	def terminate(self) -> None:
		from ..gui import braille_viewer

		braille_viewer.close()


_externalDrivers: dict[str, types.ModuleType] = {}
_BUILTIN = {"noBraille": NoBrailleDriver, "viewer": ViewerDriver}


def registerDriverModule(name: str, module: types.ModuleType) -> None:
	_externalDrivers[name] = module


def _coexistStandby() -> bool:
	"""Tiresias está en espera porque otro lector de pantalla tiene preferencia."""
	try:
		from .. import coexist

		return coexist.isStandby()
	except Exception:
		return False


def _pendingHardware(driver: BrailleDisplayDriver) -> bool:
	"""Línea física aún sin conectar o detección automática esperando una línea."""
	if driver.numCells > 0:
		return False
	try:
		from .drivers.auto import AutoDetectDriver
		from .drivers.base import HardwareDriver
	except Exception:
		return False
	return isinstance(driver, (HardwareDriver, AutoDetectDriver))


def getDriverClass(name: str) -> type[BrailleDisplayDriver]:
	if name in _BUILTIN:
		return _BUILTIN[name]
	if name == "hidBraille":
		from .hid_braille import BrailleDisplayDriver as HidDriver

		return HidDriver
	if name in _externalDrivers:
		return _externalDrivers[name].BrailleDisplayDriver
	mod = importlib.import_module(f"{__name__}.drivers.{name}")
	return mod.BrailleDisplayDriver


def getDisplayList() -> list[tuple[str, str]]:
	out = []
	# «Automático» y las líneas físicas incluidas (paquete ``drivers``).
	from .drivers import hardwareDriverChoices

	hardware = [n for n, _d in hardwareDriverChoices()]
	for name in list(_BUILTIN) + ["auto"] + hardware + [n for n in _externalDrivers if n not in hardware]:
		try:
			cls = getDriverClass(name)
			if cls.check():
				out.append((name, cls.description))
		except Exception:
			log.debug("Controlador braille %s no disponible", name, exc_info=True)
	return out


class BrailleHandler(BraillePresenter):
	"""Gestor braille: controlador de la línea más la presentación
	(:class:`~.presenter.BraillePresenter`)."""

	def __init__(self) -> None:
		self.display: BrailleDisplayDriver = NoBrailleDriver()
		self._initPresenter()
		#: El visor en pantalla refleja lo que muestra una línea braille real.
		self._mirror = False
		#: Acceso remoto: celdas de la línea de quien controla este equipo (0 = ninguna).
		#: Es la combinación de ``_remoteSizes`` (la menor mayor que 0).
		self.remoteNumCells = 0
		#: Tamaño remoto por dueño (acceso remoto, Escritorio remoto...): así,
		#: al terminar uno no se borra el del otro.
		self._remoteSizes: dict[Any, int] = {}
		#: Acceso remoto: celdas recibidas del equipo controlado (``None`` = mostrar lo local).
		#: Son las del último dueño de ``_remoteCellsBy`` que las ha enviado.
		self._remoteCells: list[int] | None = None
		self._remoteCellsBy: dict[Any, list[int]] = {}

	# --------------------------------------------------------- controlador
	def setDisplay(self, name: str, persist: bool = True, instance: BrailleDisplayDriver | None = None, **driverArgs: Any) -> bool:
		"""Cambia de línea. ``instance``: controlador ya creado (detección
		automática o reconexión); ``driverArgs`` se pasan al constructor."""
		if instance is None and name not in ("noBraille", "viewer") and _coexistStandby():
			# Otro lector de pantalla tiene preferencia: la línea se abrirá al activarse.
			if persist:
				conf["braille"]["display"] = name
			log.info("Tiresias en espera: la línea braille %s se usará al activarse", name)
			return True
		try:
			if instance is not None:
				new = instance
			else:
				cls = getDriverClass(name)
				if not cls.check():
					raise RuntimeError(f"{name} no disponible")
				new = cls(**driverArgs)
		except Exception:
			log.exception("No se pudo cargar la línea braille %s", name)
			return False
		if new is not self.display:
			try:
				self.display.terminate()
			except Exception:
				pass
		self.display = new
		if persist:
			conf["braille"]["display"] = name
		if self._mirror:
			from ..gui import braille_viewer

			if new.numCells > 0 and not isinstance(new, ViewerDriver):
				braille_viewer.show(new.numCells)
			elif _pendingHardware(new):
				# Línea física que aún está conectando (o detección automática):
				# el espejo se mantiene y se ajusta al conectar (``_activate``
				# vuelve a llamar aquí con las celdas ya conocidas).
				pass
			else:
				self._mirror = False
				if not isinstance(new, ViewerDriver):
					braille_viewer.close()
		self._refresh()
		self._updateBlink()
		self.updateSplit()
		return True

	@property
	def viewerActive(self) -> bool:
		"""``True`` si el visor braille está abierto (como línea o como espejo)."""
		return self._mirror or isinstance(self.display, ViewerDriver)

	def setViewer(self, on: bool, persist: bool = True) -> None:
		"""Abre o cierra el visor braille.

		Con una línea braille real conectada, el visor se abre como espejo de
		ella (sin sustituirla); si no hay línea, el visor hace de línea.
		"""
		from ..gui import braille_viewer

		realDisplay = self.display.numCells > 0 and not isinstance(self.display, ViewerDriver)
		if on:
			if realDisplay:
				if not self._mirror:
					self._mirror = True
					braille_viewer.show(self.display.numCells)
					self._refresh()
			elif not isinstance(self.display, ViewerDriver):
				self.setDisplay("viewer", persist=persist)
		else:
			if self._mirror:
				self._mirror = False
				braille_viewer.close()
			if isinstance(self.display, ViewerDriver):
				self.setDisplay("noBraille", persist=persist)

	@property
	def enabled(self) -> bool:
		return self.numCells > 0

	def terminate(self) -> None:
		for attr in ("_blinkTimer", "_messageTimer", "_autoScrollTimer", "_updateTimer", "_splitTimer"):
			timer = getattr(self, attr, None)
			if timer is not None:
				queue_handler.cancelCallLater(timer)
				setattr(self, attr, None)
		self._autoScroll = False
		try:
			self.display.terminate()
		except Exception:
			pass
		self.display = NoBrailleDriver()

	def _writeCells(self, cells: list[int], text: str, labels: list[str] | None = None) -> None:
		"""Escribe en la línea real (ajustando al tamaño) y en el visor espejo.

		``labels``: texto de cada celda (el visor lo muestra alineado)."""
		local = self.display.numCells
		if local <= 0:
			return
		out = (list(cells) + [0] * local)[:local]
		if isinstance(self.display, ViewerDriver):
			self.display._text = text
			self.display._labels = labels
		try:
			self.display.display(out)
		except Exception:
			log.exception("Error mostrando en la línea braille")
		if self._mirror:
			from ..gui import braille_viewer

			braille_viewer.update(out, text, labels)

	# --------------------------------------------------------- acceso remoto
	@property
	def numCells(self) -> int:
		"""Celdas con las que se trabaja: las de la línea o, si este equipo está
		controlado por acceso remoto, la menor entre la local y la remota."""
		local = self.display.numCells
		remote = self.remoteNumCells
		if remote > 0 and (local <= 0 or remote < local):
			return remote
		return local

	def setRemoteNumCells(self, numCells: int, owner: Any = "remote") -> None:
		"""Tamaño de la línea del equipo que controla (0 = ninguna) según ``owner``.

		Cada dueño (acceso remoto, Escritorio remoto) pone el suyo; se usa el
		menor mayor que 0 de todos."""
		size = max(0, int(numCells or 0))
		if size:
			self._remoteSizes[owner] = size
		else:
			self._remoteSizes.pop(owner, None)
		sizes = [s for s in self._remoteSizes.values() if s > 0]
		numCells = min(sizes) if sizes else 0
		if numCells == self.remoteNumCells:
			return
		hadCells = self.enabled
		self.remoteNumCells = numCells
		self._updateBlink()
		self.updateSplit()
		if self.enabled and not hadCells:
			# Hasta ahora no se presentaba nada en braille: se presenta el foco.
			try:
				focus = api.getFocusObject()
			except Exception:
				focus = None
			if focus is not None:
				self.handleObject(focus)
				return
		if self._translation is not None:
			self._ensureCursorVisible()
		self._refresh()

	def showRemoteCells(self, cells: list[int] | None, owner: Any = "remote") -> None:
		"""Muestra celdas recibidas del equipo controlado (``None`` vuelve a lo local).

		``owner``: quién las envía; ``None`` de un dueño solo quita las suyas (si
		otro sigue mostrando celdas remotas, se ven las de ese)."""
		self._remoteCellsBy.pop(owner, None)
		if cells is not None:
			self._remoteCellsBy[owner] = list(cells)
		self._remoteCells = list(self._remoteCellsBy[next(reversed(self._remoteCellsBy))]) if self._remoteCellsBy else None
		if self._remoteCells is not None and not self._messageActive:
			self._writeCells(self._remoteCells, "")
		elif self._remoteCells is None:
			self._refresh()


handler = BrailleHandler()


def _onSpeechRequested(text: str = "", **kwargs: Any) -> None:
	handler.onSpeech(text)


def initialize() -> None:
	from .. import events
	from ..speech import api as speechApi

	api.post_reviewMove.register(handler.handleReviewMove)
	api.post_navigatorObjectChange.register(handler.handleNavigatorObject)
	events.post_event.register(handler.onEvent)
	speechApi.post_speechRequested.register(_onSpeechRequested)
	_registerKeyCounter(True)
	from . import drivers

	drivers.initialize()
	name = conf["braille"]["display"]
	if name and name != "noBraille":
		# Sin persistir: si la línea configurada falla, no se pierde la elección.
		if not handler.setDisplay(name, persist=False):
			handler.setDisplay("noBraille", persist=False)


def _registerKeyCounter(on: bool) -> None:
	"""Cuenta las pulsaciones (para quitar los mensajes al escribir, como NVDA)."""
	from . import presenter

	try:
		from ..input import core as inputCore

		if on:
			inputCore.decide_handleRawKey.register(presenter.countKey)
		else:
			inputCore.decide_handleRawKey.unregister(presenter.countKey)
	except Exception:
		log.debug("No se pudo %s el contador de teclas", "registrar" if on else "quitar", exc_info=True)


# «Evitar dividir palabras» (wordWrap) -> «Ajuste del texto» (textWrap): ahora en
# config/migrations.py (_brailleWordWrap), que también arregla los perfiles.


def terminate() -> None:
	from .. import events
	from ..speech import api as speechApi

	for point, func in (
		(api.post_reviewMove, handler.handleReviewMove),
		(api.post_navigatorObjectChange, handler.handleNavigatorObject),
		(events.post_event, handler.onEvent),
		(speechApi.post_speechRequested, _onSpeechRequested),
	):
		try:
			point.unregister(func)
		except Exception:
			pass
	_registerKeyCounter(False)
	handler.terminate()
	from . import liblouis

	liblouis.terminate()
