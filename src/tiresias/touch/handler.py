"""Gestor del soporte táctil: activa la captura, los modos y ejecuta gestos.

Hilos:

- La ventana táctil (:mod:`.overlay`) y la del panel táctil (:mod:`.touchpad`)
  tienen su propio hilo con bucle de mensajes. Ahí se reconocen los gestos y
  solo se encolan en el núcleo (``queue_handler.queueFunction``). Los
  movimientos de exploración se agrupan: si llegan varios antes de que el
  núcleo los atienda, solo se procesa el último.
- Todo lo demás (activar y desactivar, modos, ejecutar órdenes, explorar) se
  hace en el hilo del núcleo.
"""

from __future__ import annotations

import threading
from typing import Any

from .. import queue_handler
from ..config import conf
from ..i18n import _
from . import recognizer as R
from . import win32 as W
from .explorer import ScreenExplorer
from .gestures import BROWSE_MODE, MODE_LABELS, OBJECT_MODE, TEXT_MODE, TouchGesture

log = W.log

DEFAULTS = {
	# Solo tiene efecto si hay pantalla táctil; sin ella nunca se activa.
	"enabled": True,
	"touchTyping": False,
	"textUnit": "line",
	"multiTapTimeout": 300,
	"touchpadEnabled": False,
	"touchpadSingleFinger": False,
	"liftedSequentialFlicks": False,
	"edgeGestures": False,
	"edgeMargin": 24,
}


class TouchHandler:
	def __init__(self) -> None:
		self.mode = OBJECT_MODE
		self.window: Any = None
		self.touchpad: Any = None
		self.explorer = ScreenExplorer()
		self.inputAllowed = False
		self.initialized = False
		self._hoverLock = threading.Lock()
		self._pendingHover: dict[str, tuple[R.TouchEvent, str]] = {}
		self._lastError = ""
		#: Opciones de reconocimiento con las que se creó la captura activa.
		self._appliedKey: tuple | None = None

	# ------------------------------------------------------------ ciclo de vida
	def initialize(self, inputAllowed: bool = True) -> None:
		"""Hilo del núcleo. ``inputAllowed=False`` con ``--no-input``."""
		from ..config import post_configProfileSwitch

		conf.registerDefaults("touch", DEFAULTS)
		self.inputAllowed = inputAllowed
		self.initialized = True
		present, maxTouches = W.touchHardware()
		log.info("Pantalla táctil: %s (contactos: %d)", "sí" if present else "no", maxTouches)
		post_configProfileSwitch.register(self._onProfileSwitch)
		self.apply()

	def terminate(self) -> None:
		from ..config import post_configProfileSwitch

		try:
			post_configProfileSwitch.unregister(self._onProfileSwitch)
		except Exception:
			pass
		self._stopWindow()
		self._stopTouchpad()
		self.initialized = False

	def _onProfileSwitch(self, *args, **kwargs) -> None:
		queue_handler.queueFunction(self._afterProfileSwitch)

	@staticmethod
	def _recognizerKey() -> tuple:
		"""Opciones con las que se crean los reconocedores (umbrales y bordes)."""
		touch = conf["touch"]
		return tuple(touch.get(k) for k in ("multiTapTimeout", "edgeGestures", "edgeMargin"))

	def _afterProfileSwitch(self) -> None:
		"""Hilo del núcleo: si el perfil cambia los umbrales, se recrea la captura."""
		if not self.initialized:
			return
		key = self._recognizerKey()
		if key != self._appliedKey and (self.window is not None or self.touchpad is not None):
			self.reload()
		else:
			self.apply()

	# ------------------------------------------------------------ estado
	@staticmethod
	def hasTouchScreen() -> bool:
		return W.touchHardware()[0]

	@property
	def isActive(self) -> bool:
		return self.window is not None and self.window.isRunning

	@property
	def isTouchpadActive(self) -> bool:
		return self.touchpad is not None and self.touchpad.isRunning

	def wantsTouch(self) -> bool:
		return self.inputAllowed and bool(conf["touch"]["enabled"]) and self.hasTouchScreen()

	def wantsTouchpad(self) -> bool:
		return self.inputAllowed and bool(conf["touch"]["touchpadEnabled"])

	def apply(self) -> None:
		"""Arranca o para la captura según la configuración (hilo del núcleo)."""
		if not self.initialized:
			return
		if self.wantsTouch():
			if self.window is None:
				self._startWindow()
		else:
			self._stopWindow()
		if self.wantsTouchpad():
			if self.touchpad is None:
				self._startTouchpad()
		else:
			self._stopTouchpad()

	def reload(self) -> None:
		"""Vuelve a crear la captura (tras cambiar los umbrales)."""
		self._stopWindow()
		self._stopTouchpad()
		self.apply()

	def recognizerSettings(self, edges: bool = True) -> R.RecognizerSettings:
		s = R.RecognizerSettings()
		touch = conf["touch"]
		try:
			self._appliedKey = self._recognizerKey()
		except Exception:
			self._appliedKey = None
		try:
			s.multiTapTimeout = max(100, int(touch["multiTapTimeout"])) / 1000.0
		except (KeyError, TypeError, ValueError):
			pass
		# Las distancias se adaptan a la densidad de la pantalla (96 ppp = 1).
		try:
			dpi = W.user32.GetDpiForSystem()
		except Exception:
			dpi = 96
		scale = max(1.0, dpi / 96.0) if dpi else 1.0
		s.maxTapDrift *= scale
		s.minFlickDistance *= scale
		s.minPinchDistance *= scale
		try:
			if edges and touch["edgeGestures"]:
				s.edgeMargin = max(4, int(touch["edgeMargin"])) * scale
				s.bounds = W.virtualScreen()
		except (KeyError, TypeError, ValueError):
			pass
		return s

	def sequenceFilter(self, action: str, fingers: int) -> bool:
		"""¿Esperar un segundo deslizamiento tras ``action``? (hilo de la ventana)

		Solo si está activada la opción y hay alguna secuencia que empiece por
		ese deslizamiento con una orden asignada; así los deslizamientos
		simples no se retrasan sin necesidad.
		"""
		try:
			if not conf["touch"]["liftedSequentialFlicks"]:
				return False
		except KeyError:
			return False
		return R.makeName(action, fingers).lower() + "then" in self._boundSequencePrefixes()

	@staticmethod
	def _boundSequencePrefixes() -> set[str]:
		from ..global_commands import GlobalCommands
		from ..input import gestures as gestureMap

		names: set[str] = set()
		gids = [g for g, _s in GlobalCommands.iterClassGestures()]
		for bindings in gestureMap.userMap.userBindings().values():
			gids += [g for g, sname in bindings.items() if sname]
		unbound = {g for b in gestureMap.userMap.userBindings().values() for g, sname in b.items() if sname is None}
		for gid in gids:
			if gid in unbound:
				continue
			prefix, _sep, name = gid.partition(":")
			if not prefix.startswith(("ts", "tp")):
				continue
			_edge, name = R.splitEdge(name)
			head, sep, _rest = name.partition("then")
			if sep:
				names.add(head + "then")
		return names

	def _startWindow(self) -> None:
		from .overlay import TouchInputWindow

		settings = self.recognizerSettings()
		attempts = []
		if W.hasUiAccess():
			attempts.append(True)
		attempts.append(False)
		for useTarget in attempts:
			win = TouchInputWindow(lambda events: self._onEvents(events, "ts"), settings, useTarget=useTarget, sequenceFilter=self.sequenceFilter)
			try:
				win.start()
			except Exception as e:
				log.warning("No se pudo iniciar la entrada táctil (%s): %s", "destino de puntero" if useTarget else "superposición", e)
				self._lastError = str(e)
				win.stop()
				continue
			self.window = win
			self.explorer.reset()
			return
		self.window = None

	def _stopWindow(self) -> None:
		win, self.window = self.window, None
		if win is not None:
			win.stop()
			log.info("Entrada táctil detenida")

	def _startTouchpad(self) -> None:
		from .touchpad import TouchpadInput

		tp = TouchpadInput(lambda events: self._onEvents(events, "tp"), self.recognizerSettings(edges=False), sequenceFilter=self.sequenceFilter)
		try:
			tp.start()
		except Exception as e:
			log.warning("No se pudo escuchar el panel táctil: %s", e)
			self._lastError = str(e)
			tp.stop()
			self.touchpad = None
			return
		self.touchpad = tp

	def _stopTouchpad(self) -> None:
		tp, self.touchpad = self.touchpad, None
		if tp is not None:
			tp.stop()
			log.info("Panel táctil detenido")

	def setEnabled(self, enable: bool) -> str:
		"""Cambia la interacción táctil y devuelve el mensaje para el usuario."""
		if enable and not self.hasTouchScreen():
			return _("Interacción táctil no disponible: no se ha detectado ninguna pantalla táctil")
		conf["touch"]["enabled"] = enable
		self.apply()
		if not enable:
			return _("Interacción táctil desactivada")
		if not self.inputAllowed:
			return _("Interacción táctil activada; no se capturan toques porque Tiresias se inició sin entrada")
		if not self.isActive:
			return _("No se pudo activar la interacción táctil")
		return _("Interacción táctil activada")

	def setTouchpadEnabled(self, enable: bool) -> str:
		conf["touch"]["touchpadEnabled"] = enable
		self.apply()
		if not enable:
			return _("Gestos en el panel táctil desactivados")
		if self.inputAllowed and not self.isTouchpadActive:
			return _("No se pudieron activar los gestos en el panel táctil")
		return _("Gestos en el panel táctil activados")

	@property
	def overlayHwnd(self) -> int:
		win = self.window
		if win is not None and win.mode == "overlay":
			return int(win.hwnd or 0)
		return 0

	def allowMouseThrough(self) -> None:
		"""Antes de un clic simulado: la superposición deja pasar el ratón."""
		win = self.window
		if win is not None and win.mode == "overlay":
			try:
				win.allowMouseThrough()
			except Exception:
				log.debug("No se pudo apartar la superposición", exc_info=True)

	# ------------------------------------------------------------ modos
	def availableModes(self) -> list[str]:
		modes = [OBJECT_MODE, TEXT_MODE]
		if self.browseDocument() is not None:
			modes.append(BROWSE_MODE)
		return modes

	@staticmethod
	def browseDocument() -> Any:
		"""Documento en modo exploración con el foco (o ``None``)."""
		from .. import api

		focus = api.getFocusObject()
		ti = getattr(focus, "treeInterceptor", None) if focus is not None else None
		if ti is None or getattr(ti, "passThrough", True) or not hasattr(ti, "quickNav"):
			return None
		return ti

	def effectiveMode(self) -> str:
		if self.mode == BROWSE_MODE and self.browseDocument() is None:
			return OBJECT_MODE
		return self.mode

	def cycleMode(self) -> str:
		modes = self.availableModes()
		cur = self.effectiveMode()
		i = modes.index(cur) if cur in modes else -1
		self.mode = modes[(i + 1) % len(modes)]
		return MODE_LABELS[self.mode]

	# ------------------------------------------------------------ gestos
	def _onEvents(self, events: list[R.TouchEvent], source: str) -> None:
		"""Hilo de la ventana: filtra y encola."""
		singleFinger = True
		if source == "tp":
			try:
				singleFinger = bool(conf["touch"]["touchpadSingleFinger"])
			except Exception:
				singleFinger = False
		for ev in events:
			if ev.fingers == 1 and not singleFinger:
				continue
			if source == "tp" and ev.action in R.HOVER_ACTIONS:
				# El panel táctil no explora la pantalla (manual, 20.6).
				continue
			if ev.action == R.HOVER:
				with self._hoverLock:
					queued = source in self._pendingHover
					self._pendingHover[source] = (ev, source)
				if not queued:
					queue_handler.queueFunction(self._processHover, source)
				continue
			queue_handler.queueFunction(self.executeEvent, ev, source)

	def _processHover(self, source: str) -> None:
		with self._hoverLock:
			item = self._pendingHover.pop(source, None)
		if item is not None:
			self.executeEvent(*item)

	def executeEvent(self, event: R.TouchEvent, source: str = "ts") -> None:
		"""Hilo del núcleo: crea el gesto y lo pasa al gestor de entrada."""
		from ..input import core as inputCore

		gesture = TouchGesture(event, self.effectiveMode(), source)
		if log.isEnabledFor(10):
			log.debug("Gesto táctil %s", gesture.identifiers[0])
		inputCore.manager.executeTouchGesture(gesture)

	def explore(self, x: int, y: int, new: bool = False) -> None:
		self.explorer.moveTo(x, y, new=new, overlayHwnd=self.overlayHwnd)


handler = TouchHandler()


def initialize(inputAllowed: bool = True) -> None:
	handler.initialize(inputAllowed)
	try:
		from .. import gui

		gui.runOnGui(_registerPanel)
	except Exception:
		log.debug("No se pudo registrar el panel de opciones táctiles", exc_info=True)


def _registerPanel() -> None:
	from ..gui import touch_panel

	touch_panel.register()


def terminate() -> None:
	handler.terminate()


def allowMouseThrough() -> None:
	"""Para :mod:`tiresias.mouse`: apartar la superposición antes de un clic."""
	handler.allowMouseThrough()
