"""Gestor de entrada: decide qué hacer con cada tecla.

En el hilo de los ganchos de teclado se identifica el gesto y se busca la
orden asociada en la «cadena de resolución» (complementos globales, módulo de
aplicación, modo exploración, objeto con foco y órdenes globales). Si hay
orden, la tecla se captura y la orden se ejecuta en el hilo del núcleo; si
no, la tecla llega a la aplicación con normalidad.

Protecciones de estabilidad (como NVDA):

- Los modificadores se olvidan al cambiar de escritorio (las teclas soltadas
  en el escritorio seguro no llegan al gancho) y, en cada pulsación, se
  descartan los que Windows ya no da por pulsados (``GetAsyncKeyState``).
- Mientras haya órdenes que reenvían su tecla sin terminar (las del cursor,
  que capturan la tecla y la mandan después con ``gesture.send()``), las
  teclas siguientes sin orden no pasan directamente: se encolan detrás y se
  reenvían en orden. Así no se adelanta una letra a un Retroceso.
- Los bloqueos (mayúsculas, numérico, desplazamiento) se leen de Windows
  tras cada cambio en lugar de contarse.
- Si la ventana de primer plano ya no es la de la cadena (se acaba de cambiar
  de aplicación y el foco aún no se ha procesado), solo se usan los
  complementos y las órdenes globales.
"""

from __future__ import annotations

import ctypes
import threading
import time
import unicodedata
from ctypes import wintypes
from typing import Any, Callable

from .. import queue_handler, winapi
from ..config import conf
from ..extension_points import Action, Decider
from ..i18n import _
from ..log import getLogger
from . import keys
from .gestures import KeyboardGesture
from .hooks import hookThread

log = getLogger("inputCore")

#: Antes de ejecutar un gesto: ``gesture``. Si algún manejador devuelve
#: ``False`` el gesto no se procesa (se deja pasar a la aplicación).
decide_executeGesture = Decider()
#: Tras ejecutar una orden: ``script``, ``gesture``.
post_scriptExecuted = Action()
#: Clic con el botón izquierdo del ratón (en el hilo del núcleo): ``x``, ``y``.
post_mouseClick = Action()
#: Cada tecla en bruto, en el hilo de ganchos y antes de cualquier proceso:
#: ``vk``, ``scanCode``, ``extended``, ``pressed``, ``injected``. Si un
#: manejador devuelve ``False`` la tecla se captura y Tiresias la ignora (lo
#: usa el acceso remoto para enviar las teclas al otro equipo). Debe ser muy rápido.
decide_handleRawKey = Decider()
#: Antes de ejecutar un gesto de la línea braille: ``gesture``. ``False`` lo descarta.
decide_executeBrailleGesture = Decider()
#: Se pulsa un modificador sin otras teclas (hilo del núcleo): ``name``
#: (``"control"``, ``"shift"``, ``"alt"`` o ``"windows"``). Lo usa Word para
#: leer el formato antes de un atajo (Control+N...).
post_modifierDown = Action()

_DEAD_TO_COMBINING = {
	"´": "́",  # ´ agudo
	"`": "̀",  # grave
	"^": "̂",  # circunflejo
	"¨": "̈",  # ¨ diéresis
	"~": "̃",  # tilde
	"ˇ": "̌",  # ˇ
	"˘": "̆",  # ˘
	"°": "̊",  # °
	"¸": "̧",  # ¸ cedilla
}

#: Letras que combinan las distribuciones de teclado latinas con cada tecla muerta.
_DEAD_KEY_BASES = {
	"´": "aeiouy",
	"`": "aeiou",
	"^": "aeiou",
	"¨": "aeiouy",
	"~": "ano",
	"¸": "c",
}

DUMMY_VK = 0xE8  # Tecla sin asignar para evitar que Alt/Windows abran menús.
VK_PACKET = 0xE7  # Carácter Unicode inyectado (dictado, panel de emojis, teclados en pantalla).
TOGGLE_VKS = (winapi.VK_CAPITAL, winapi.VK_NUMLOCK, winapi.VK_SCROLL)
_TOGGLE_ATTRS = {winapi.VK_CAPITAL: "_capsToggled", winapi.VK_NUMLOCK: "_numToggled", winapi.VK_SCROLL: "_scrollToggled"}
#: Mensajes de los botones del ratón (y la rueda) que cuentan como «otra tecla» con Mayúsculas.
_MOUSE_PRESS_MSGS = frozenset({0x0201, 0x0204, 0x0207, 0x020A, 0x020B, 0x020E})
#: Espera antes de leer el estado real de un bloqueo tras pulsarlo (ms).
TOGGLE_CHECK_MS = 60
#: Una orden que reenvía su tecla de forma diferida nunca retiene las demás más de esto (s).
DEFER_TIMEOUT = 2.0

# Teclas especiales de Windows (StickyKeys).
SPI_GETSTICKYKEYS = 0x003A
SKF_STICKYKEYSON = 0x00000001
SKF_TRISTATE = 0x00000080


class STICKYKEYS(ctypes.Structure):
	_fields_ = [("cbSize", wintypes.UINT), ("dwFlags", wintypes.DWORD)]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
_user32.SystemParametersInfoW.restype = wintypes.BOOL


def stickyKeysFlags() -> int:
	sk = STICKYKEYS()
	sk.cbSize = ctypes.sizeof(STICKYKEYS)
	try:
		if _user32.SystemParametersInfoW(SPI_GETSTICKYKEYS, sk.cbSize, ctypes.byref(sk), 0):
			return int(sk.dwFlags)
	except Exception:
		pass
	return 0


def composeDeadKey(dead: str | None, ch: str | None) -> str | None:
	"""Lo que escribe la aplicación tras una tecla muerta ``dead`` y la tecla ``ch``.

	Como Windows: con espacio sale el acento solo; con una letra que tenga
	forma acentuada, la letra acentuada; en otro caso, el acento y la tecla
	(«´» + «n» = «´n», «´» + «1» = «´1»).
	"""
	if not dead or not ch:
		return ch
	if ch == " ":
		return dead
	comb = _DEAD_TO_COMBINING.get(dead)
	bases = _DEAD_KEY_BASES.get(dead)
	if bases is not None and ch.lower() not in bases:
		# Las distribuciones latinas solo combinan estas letras («´» + «n» = «´n»).
		return dead + ch
	if comb and ch.isalpha():
		composed = unicodedata.normalize("NFC", ch + comb)
		if len(composed) == 1:
			return composed
	return dead + ch


def isInterceptingScript(func) -> bool:
	"""¿La orden captura su tecla y la reenvía después (``gesture.send()``)?

	Se marca con el atributo ``interceptsGesture``. Sin él se sigue la regla
	de NVDA: las órdenes sin descripción (las del cursor y la navegación,
	que acompañan a una tecla normal) lo son.
	"""
	flag = getattr(func, "interceptsGesture", None)
	if flag is not None:
		return bool(flag)
	return not (getattr(func, "__doc__", None) or "").strip()


class InputManager:
	def __init__(self) -> None:
		self.chain: list[Any] = []
		#: Parte de la cadena que vale en cualquier ventana (complementos y globales).
		self._globalChain: list[Any] = []
		#: Ventana de primer plano cuando se calculó la cadena (0: no se comprueba).
		self._chainFg = 0
		self.inputHelp = False
		self.passNextKey = False
		self.captureFunc: Callable[[KeyboardGesture], bool] | None = None
		self._mods: set[str] = set()
		self._modVks: set[int] = set()
		#: Modificadores capturados (ayuda de entrada o captura de gestos).
		self._swallowedMods: set[int] = set()
		self._altGr = False
		#: Llegó el Control izquierdo falso que precede a AltGr.
		self._altGrCtrlPending = False
		self._tiresiasDown = False
		self._tiresiasVk: tuple[int, bool] | None = None
		self._tiresiasUsed = False
		self._lastTiresiasRelease: tuple[tuple[int, bool], float] | None = None
		#: Teclas capturadas cuya liberación hay que capturar también: (vk, extendida).
		self._swallowed: set[tuple[int, bool]] = set()
		#: Teclas que se dejan pasar tal cual (pasar la siguiente tecla).
		self._passing: set[tuple[int, bool]] = set()
		self._capsToggled = False
		self._numToggled = False
		self._scrollToggled = False
		self._deadKey: str | None = None
		self._highSurrogate: str | None = None
		self._lastScript = None
		self._lastScriptTime = 0.0
		self._lastScriptRepeat = 0
		self._lastMousePos: tuple[int, int] | None = None
		self._mouseTimer: int | None = None
		self._otherKeyWhileShift = False
		self._shiftAlone = False
		#: Olvidar las teclas pulsadas en la próxima tecla (cambio de escritorio).
		self._resetPending = False
		# Órdenes que reenvían su tecla (protección del orden de las teclas).
		self._sendLock = threading.Lock()
		self._interceptPending = 0
		self._deferCount = 0
		self._held: list[KeyboardGesture] = []
		# Teclas especiales de Windows (StickyKeys).
		self._latched: set[str] = set()
		self._locked: set[str] = set()
		self._keyCounter = 0
		self._modDownCounter: dict[str, int] = {}
		self._stickyCache: tuple[float, int] = (0.0, 0)

	# ------------------------------------------------------------------ inicio
	def start(self, winEvents: list) -> None:
		hookThread.keyCallback = self._onKey
		hookThread.mouseCallback = self._onMouse
		hookThread.start(winEvents)
		self.refreshToggleStates()

	def stop(self) -> None:
		hookThread.keyCallback = None
		hookThread.mouseCallback = None
		hookThread.stop()

	def resetState(self) -> None:
		"""Olvida las teclas que se creían pulsadas (al ceder ante otro lector).

		Sin ganchos no llegan las teclas soltadas: al volver a activarse no
		debe quedar ningún modificador ni la tecla Tiresias «pulsados».
		"""
		self._resetKeys()
		self._lastTiresiasRelease = None
		self.passNextKey = False
		self.captureFunc = None
		self.inputHelp = False
		with self._sendLock:
			self._interceptPending = 0
			self._deferCount = 0
			self._held = []
		if self._mouseTimer is not None and self._mouseTimer >= 0:
			queue_handler.cancelCallLater(self._mouseTimer)
		self._mouseTimer = None

	def _resetKeys(self) -> None:
		self._mods.clear()
		self._modVks.clear()
		self._swallowedMods.clear()
		self._swallowed.clear()
		self._passing.clear()
		self._altGr = False
		self._altGrCtrlPending = False
		self._tiresiasDown = False
		self._tiresiasVk = None
		self._tiresiasUsed = False
		self._deadKey = None
		self._highSurrogate = None
		self._shiftAlone = False
		self._otherKeyWhileShift = False
		self._latched.clear()
		self._locked.clear()
		self._modDownCounter.clear()

	def onDesktopSwitch(self) -> None:
		"""Cambio de escritorio (escritorio seguro, bloqueo, UAC).

		Las teclas soltadas en otro escritorio no llegan al gancho: se olvidan
		las que se creían pulsadas en la próxima tecla (en el hilo del gancho,
		para no tocar el estado desde dos hilos) y se vuelven a leer los
		bloqueos, que la pantalla de inicio de sesión puede cambiar.
		"""
		self._resetPending = True
		try:
			self.refreshToggleStates()
		except Exception:
			log.debug("No se pudieron leer los bloqueos", exc_info=True)

	# ------------------------------------------------------------------ bloqueos
	def _readToggleState(self, vk: int) -> bool | None:
		try:
			return bool(hookThread.getKeyStateFromForeground(vk) & 1)
		except Exception:
			try:
				return bool(winapi.user32.GetKeyState(vk) & 1)
			except Exception:
				return None

	def refreshToggleStates(self) -> None:
		"""Lee de Windows el estado de los tres bloqueos."""
		for vk, attr in _TOGGLE_ATTRS.items():
			state = self._readToggleState(vk)
			if state is not None:
				setattr(self, attr, state)

	def _toggleMessage(self, vk: int, on: bool) -> str:
		if vk == winapi.VK_CAPITAL:
			return _("bloqueo de mayúsculas activado") if on else _("bloqueo de mayúsculas desactivado")
		if vk == winapi.VK_NUMLOCK:
			return _("bloqueo numérico activado") if on else _("bloqueo numérico desactivado")
		return _("bloqueo de desplazamiento activado") if on else _("bloqueo de desplazamiento desactivado")

	def _afterToggleKey(self, vk: int, quiet: bool) -> None:
		"""Hilo del gancho: un bloqueo llegó a Windows. Se prevé el cambio (para
		el eco inmediato) y se confirma leyendo el estado real un poco después."""
		attr = _TOGGLE_ATTRS[vk]
		setattr(self, attr, not getattr(self, attr))
		announce = bool(conf["keyboard"]["announceToggleKeys"]) and not quiet
		if queue_handler._coreThreadId is not None:
			queue_handler.callLater(TOGGLE_CHECK_MS, self._checkToggle, vk, announce)
		else:
			queue_handler.queueFunction(self._checkToggle, vk, announce)

	def _checkToggle(self, vk: int, announce: bool) -> None:
		attr = _TOGGLE_ATTRS[vk]
		state = self._readToggleState(vk)
		if state is None:
			state = getattr(self, attr)
		setattr(self, attr, state)
		if announce:
			_speakText(self._toggleMessage(vk, state))

	# ------------------------------------------------------------------ cadena
	def updateChain(self) -> None:
		"""Recalcula los objetos que pueden atender gestos (hilo del núcleo)."""
		from .. import api
		from ..appmodules import handler as appHandler
		from ..global_commands import commands as globalCommands
		from ..plugins import handler as pluginHandler

		plugins: list[Any] = list(pluginHandler.runningPlugins)
		try:
			fg = winapi.getForegroundWindow()
		except Exception:
			fg = 0
		chain: list[Any] = list(plugins)
		focus = api.getFocusObject()
		app = None
		try:
			app = focus.appModule if focus is not None else appHandler.getForegroundApp()
		except Exception:
			app = None
		if app is not None:
			if app.sleepMode:
				self.chain = [_SleepModeFilter(globalCommands)]
				self._globalChain = self.chain
				self._chainFg = fg
				return
			chain.append(app)
		# Controlador de la línea braille (también los de complementos): sus
		# órdenes propias y los gestos que el usuario le asigne.
		chain.append(_brailleDisplayScripts)
		if focus is not None:
			ti = getattr(focus, "treeInterceptor", None)
			if ti is not None:
				chain.append(ti)
			chain.append(focus)
			for anc in reversed(api.getFocusAncestors()):
				chain.append(_PropagatingOnly(anc))
		chain.append(globalCommands)
		self._globalChain = plugins + [_brailleDisplayScripts, globalCommands]
		self.chain = chain
		self._chainFg = fg

	def _chainFor(self, fg: int) -> list[Any]:
		"""La cadena que vale para la ventana de primer plano ``fg``."""
		chain = self.chain
		chainFg = self._chainFg
		if chainFg and fg and fg != chainFg and self._globalChain:
			# Se acaba de cambiar de ventana y el foco nuevo aún no se ha
			# procesado: las órdenes del documento o la aplicación anteriores
			# no deben atender (ni tragarse) estas teclas.
			return list(self._globalChain)
		return chain

	def findScript(self, gesture: KeyboardGesture, fg: int | None = None):
		chain = self.chain if fg is None else self._chainFor(fg)
		for obj in list(chain):
			try:
				func = obj.getScript(gesture)
			except Exception:
				log.exception("Error buscando la orden en %r", obj)
				continue
			if func:
				# Pantalla de bloqueo: solo las órdenes seguras (ver lock_guard).
				from ..lock_guard import filterScript

				return filterScript(func)
		return None

	# ------------------------------------------------------------------ teclado
	def _isTiresiasKey(self, vk: int, extended: bool) -> bool:
		kb = conf["keyboard"]
		if vk == winapi.VK_INSERT:
			return kb["useInsertAsModifier"] if extended else kb["useNumpadInsertAsModifier"]
		if vk == winapi.VK_CAPITAL:
			return kb["useCapsLockAsModifier"]
		return False

	def _coreFrozen(self) -> bool:
		timeout = conf["advanced"]["watchdogTimeout"]
		return queue_handler.busy and time.monotonic() - queue_handler.lastPumpTime > timeout

	def _stickyFlags(self) -> int:
		"""Opciones de las teclas especiales de Windows (se leen como mucho una vez por segundo)."""
		now = time.monotonic()
		stamp, flags = self._stickyCache
		if now - stamp >= 1.0:
			flags = stickyKeysFlags()
			self._stickyCache = (now, flags)
		return flags

	def _capturing(self) -> bool:
		"""Ayuda de entrada o captura de gestos: ninguna tecla debe hacer nada."""
		return self.inputHelp or self.captureFunc is not None

	def _onKey(self, vk: int, scan: int, flags: int, isUp: bool, injected: bool) -> bool:
		extended = bool(flags & winapi.LLKHF_EXTENDED)
		if self._resetPending:
			self._resetPending = False
			self._resetKeys()
		if len(decide_handleRawKey) and not decide_handleRawKey.decide(vk=vk, scanCode=scan, extended=extended, pressed=not isUp, injected=injected):
			return True
		if injected and not conf["keyboard"]["handleInjectedKeys"]:
			return False
		# AltGr genera un Control izquierdo falso con este código de exploración
		# (justo antes de Alt derecha). Solo lo hacen las distribuciones con
		# AltGr: con las demás, Alt derecha es una Alt normal.
		if vk == 0xA2 and scan == 0x21D:
			if not isUp:
				self._altGrCtrlPending = True
			return False
		key = (vk, extended)
		if vk in keys.MODIFIER_VKS:
			return self._onModifier(vk, isUp)
		# Pasar la siguiente tecla: pasa todo (también la tecla Tiresias) hasta
		# que se suelten las teclas que se dejaron pasar.
		if isUp:
			if key in self._passing:
				self._passing.discard(key)
				return False
		elif self._passing or (self.passNextKey and self.captureFunc is None):
			self.passNextKey = False
			self._passing.add(key)
			return False
		if self._isTiresiasKey(vk, extended):
			return self._onTiresiasKey(vk, extended, isUp)
		if isUp:
			if key in self._swallowed:
				self._swallowed.discard(key)
				return True
			return False
		self._otherKeyWhileShift = True
		self._keyCounter += 1
		swallow = self._onKeyDown(vk, scan, extended)
		if not swallow:
			# La tecla llegó a la aplicación: su liberación también debe llegar.
			self._swallowed.discard(key)
			if vk in TOGGLE_VKS:
				self._afterToggleKey(vk, self._isSleeping())
		return swallow

	def _onModifier(self, vk: int, isUp: bool) -> bool:
		name = keys.MODIFIER_VKS[vk]
		if vk == 0xA5:
			# AltGr si el sistema acaba de mandar su Control falso.
			self._altGr = not isUp and self._altGrCtrlPending
			self._altGrCtrlPending = False
		if isUp:
			swallowed = vk in self._swallowedMods
			self._swallowedMods.discard(vk)
			self._modVks.discard(vk)
			if not any(keys.MODIFIER_VKS.get(v) == name for v in self._modVks):
				self._mods.discard(name)
			alone = self._modDownCounter.pop(name, None) == self._keyCounter
			# Mayúsculas pulsada y soltada sola: pausa o reanuda la voz
			# (no al escribir mayúsculas ni con Mayúsculas+Tab).
			if name == "shift" and self._shiftAlone and not self._otherKeyWhileShift and not swallowed:
				queue_handler.queueFunction(_pauseSpeechToggle)
			if name == "shift":
				self._shiftAlone = False
			if alone and not swallowed:
				self._stickyRelease(name)
			return swallowed
		if vk in self._swallowedMods:
			# Repetición de un modificador capturado.
			return True
		alone = not self._mods and not self._tiresiasDown
		first = vk not in self._modVks
		if first:
			self._modVks.add(vk)
			self._modDownCounter.setdefault(name, self._keyCounter)
			if name == "control" and alone:
				queue_handler.queueFunction(_cancelSpeech)
			elif name == "shift":
				self._shiftAlone = alone
				self._otherKeyWhileShift = False
			else:
				self._otherKeyWhileShift = True
			if alone and len(post_modifierDown):
				queue_handler.queueFunction(post_modifierDown.notify, name=name)
		self._mods.add(name)
		if self._capturing():
			# Ayuda de entrada y captura de gestos: el modificador no llega a
			# Windows (Windows sola no abre Inicio, Alt no activa los menús).
			self._swallowedMods.add(vk)
			if first and self.inputHelp:
				queue_handler.queueFunction(_speakText, keys.labelForKey(name))
			return True
		return False

	def _stickyRelease(self, name: str) -> None:
		"""Un modificador se soltó sin pulsar otra tecla: teclas especiales de Windows."""
		flags = self._stickyFlags()
		if not flags & SKF_STICKYKEYSON:
			if self._latched or self._locked:
				self._latched.clear()
				self._locked.clear()
			return
		if name in self._locked:
			self._locked.discard(name)
		elif name in self._latched:
			self._latched.discard(name)
			if flags & SKF_TRISTATE:
				self._locked.add(name)
		else:
			self._latched.add(name)

	def _stickyMods(self) -> set[str]:
		if not (self._latched or self._locked):
			return set()
		if not self._stickyFlags() & SKF_STICKYKEYSON:
			self._latched.clear()
			self._locked.clear()
			return set()
		return self._latched | self._locked

	def _onTiresiasKey(self, vk: int, extended: bool, isUp: bool) -> bool:
		key = (vk, extended)
		if not isUp:
			self._otherKeyWhileShift = True
			self._keyCounter += 1
			if not self._tiresiasDown:
				self._tiresiasDown = True
				self._tiresiasVk = key
				self._tiresiasUsed = False
				if self.inputHelp:
					queue_handler.queueFunction(_speakText, _("Tiresias"))
			return True
		self._tiresiasDown = False
		if not self._tiresiasUsed:
			if self._stickyFlags() & SKF_STICKYKEYSON:
				# Con las teclas especiales, la tecla Tiresias se queda enganchada
				# para la tecla siguiente (como NVDA); no hay doble pulsación.
				self._stickyRelease("tiresias")
				return True
			if self._capturing():
				# En la ayuda de entrada o al capturar gestos no se hace nada.
				self._lastTiresiasRelease = None
				return True
			now = time.monotonic()
			last = self._lastTiresiasRelease
			timeout = conf["keyboard"]["multiPressTimeout"] / 1000.0
			if last and last[0] == key and now - last[1] < timeout:
				self._lastTiresiasRelease = None
				self._sendNativeModifier(vk, extended)
			else:
				self._lastTiresiasRelease = (key, now)
		return True

	def _sendNativeModifier(self, vk: int, extended: bool) -> None:
		winapi.sendInputs([winapi.makeKeyInput(vk, extended=extended), winapi.makeKeyInput(vk, up=True, extended=extended)])
		if vk == winapi.VK_CAPITAL:
			self._capsToggled = not self._capsToggled
			if conf["keyboard"]["announceToggleKeys"]:
				queue_handler.queueFunction(_speakText, self._toggleMessage(vk, self._capsToggled))

	def _validateModifiers(self) -> None:
		"""Descarta los modificadores que Windows ya no da por pulsados.

		Tiresias no captura los modificadores normales (salvo en la ayuda de
		entrada), así que su estado en Windows es fiable. Cubre las teclas
		soltadas en otro escritorio o con el gancho perdido.
		"""
		stale = [v for v in self._modVks if v not in self._swallowedMods and not winapi.isKeyDown(v)]
		if not stale:
			return
		for v in stale:
			self._modVks.discard(v)
			if v == 0xA5:
				self._altGr = False
		self._mods = {keys.MODIFIER_VKS[v] for v in self._modVks}

	def _computeChar(self, vk: int, scan: int, hkl: int, mods: set[str] | frozenset[str]) -> tuple[str | None, str | None]:
		"""(carácter que escribiría la tecla, tecla muerta pendiente después).

		No cambia el estado: la tecla muerta se apunta solo si la tecla llega
		a la aplicación (:meth:`_commitChar`).
		"""
		state = (ctypes.c_ubyte * 256)()
		if "shift" in mods:
			state[0x10] = 0x80
			state[0xA0] = 0x80
		if "control" in mods or self._altGr:
			state[0x11] = 0x80
			state[0xA2] = 0x80
		if "alt" in mods or self._altGr:
			state[0x12] = 0x80
			state[0xA5 if self._altGr else 0xA4] = 0x80
		if self._capsToggled:
			state[0x14] = 0x01
		buf = ctypes.create_unicode_buffer(8)
		res = winapi.user32.ToUnicodeEx(vk, scan, state, buf, 8, 4, hkl)
		if res < 0:
			return None, (buf.value[:1] or None)
		if res == 0:
			return None, self._deadKey
		return composeDeadKey(self._deadKey, buf.value[:res]), None

	def _commitChar(self, gesture: KeyboardGesture) -> None:
		"""La tecla llegó a la aplicación: la tecla muerta pendiente cambia."""
		dead = getattr(gesture, "deadAfter", _NOT_COMPUTED)
		if dead is not _NOT_COMPUTED:
			self._deadKey = dead

	def _onPacket(self, scan: int) -> bool:
		"""Carácter Unicode inyectado (``VK_PACKET``): es texto, nunca una orden."""
		ch = chr(scan) if scan else ""
		if 0xD800 <= scan < 0xDC00:
			self._highSurrogate = ch
			return False
		if 0xDC00 <= scan < 0xE000:
			high, self._highSurrogate = self._highSurrogate, None
			ch = (high + ch).encode("utf-16", "surrogatepass").decode("utf-16") if high else ""
		else:
			self._highSurrogate = None
		if ch and ch.isprintable() and not self._isSleeping():
			if conf["keyboard"]["speechInterruptForCharacters"]:
				queue_handler.queueFunction(_cancelSpeech)
			queue_handler.queueFunction(_typedCharacter, ch)
		return False

	def _onKeyDown(self, vk: int, scan: int, extended: bool) -> bool:
		key = (vk, extended)
		if self._coreFrozen():
			return False
		self._validateModifiers()
		if vk == VK_PACKET:
			return self._onPacket(scan)
		fg = winapi.getForegroundWindow()
		hkl = winapi.user32.GetKeyboardLayout(winapi.getWindowThreadId(fg) if fg else 0)
		mods = set(self._mods)
		sticky = self._stickyMods()
		if sticky:
			mods |= sticky
			self._latched.clear()
		if self._tiresiasDown or "tiresias" in mods:
			mods.add("tiresias")
			self._tiresiasUsed = True
		if self._altGr:
			# AltGr es Control+Alt para Windows: así se guarda al capturarla y
			# así se buscan las órdenes cuando no escribe ningún carácter.
			mods.add("control")
		mainName = keys.vkName(vk, extended, hkl)
		if self._numToggled and mainName in ("numpaddivide", "numpadmultiply", "numpadplus", "numpadminus"):
			mainName = "numlock" + mainName
		gesture = KeyboardGesture(vk, scan, extended, frozenset(mods), mainName, conf["keyboard"]["layout"])
		# Modo dormir: Tiresias no anuncia nada en esa aplicación (ni pitidos ni bloqueos).
		quiet = self._isSleeping()
		onlyShift = not (mods - {"shift"})
		if onlyShift or self._altGr:
			try:
				gesture.char, gesture.deadAfter = self._computeChar(vk, scan, hkl, mods)
			except Exception:
				gesture.char = None
			ch = gesture.char
			if ch and len(ch) == 1 and ch.isalpha() and ch.islower() and self._capsToggled and "shift" in mods and conf["keyboard"]["beepForLowercaseWithCapsLock"] and not quiet:
				# Bloq Mayús activado y Mayúsculas pulsada: se escribe en minúscula
				# sin querer; se avisa con un pitido.
				queue_handler.queueFunction(_beep, 3000, 40)
		# Captura de gestos (diálogo de gestos de entrada, capas...).
		if self.captureFunc is not None:
			func = self.captureFunc
			queue_handler.queueFunction(func, gesture)
			self._swallowed.add(key)
			return True
		typesAltGr = self._altGr and "tiresias" not in mods and bool(gesture.char) and not self.inputHelp
		if typesAltGr:
			# AltGr que escribe un carácter (@, #, €...): es texto, no una orden.
			if self._shouldTrapInBrowseMode(gesture, fg):
				self._swallowed.add(key)
				return True
			self._commitChar(gesture)
			self._queueTyped(gesture)
			return False
		if not decide_executeGesture.decide(gesture=gesture):
			return False
		func = self.findScript(gesture, fg)
		if log.isEnabledFor(10):
			from ..privacy import gestureLogName

			# Sin el carácter escrito: el registro no guarda contraseñas ni texto.
			log.debug("Gesto %s -> %s", gestureLogName(gesture), getattr(func, "__name__", None))
		if self.inputHelp and not (func and getattr(func, "bypassInputHelp", False)):
			queue_handler.queueFunction(_reportInputHelp, gesture, func)
			if vk == winapi.VK_NUMLOCK:
				# Como NVDA (#4226): Bloq Num siempre llega a Windows, o el
				# teclado y Windows dejarían de estar de acuerdo.
				return False
			self._swallowed.add(key)
			self._preventMenuActivation()
			return True
		if func is not None:
			isRepeat = key in self._swallowed
			self._swallowed.add(key)
			self._preventMenuActivation()
			from ..speech import sayall

			resume = getattr(func, "resumeSayAll", False) and sayall.isRunning() and conf["keyboard"]["allowSkimReadingInSayAll"]
			intercepts = isInterceptingScript(func)
			if intercepts:
				with self._sendLock:
					self._interceptPending += 1
			queue_handler.queueFunction(self._runScript, func, gesture, resume, intercepts, isRepeat)
			return True
		# Sin orden asociada.
		if "tiresias" in mods and not quiet:
			# Tiresias+tecla sin orden: no llega a la aplicación (salvo en una
			# aplicación dormida, donde Tiresias no debe molestar).
			self._swallowed.add(key)
			self._preventMenuActivation()
			return True
		if self._shouldTrapInBrowseMode(gesture, fg):
			self._swallowed.add(key)
			return True
		queue_handler.queueFunction(self._clearLastScript)
		held = self._holdIfPending(gesture)
		if held:
			self._swallowed.add(key)
		self._commitChar(gesture)
		if not quiet:
			self._afterPassedKey(gesture)
		return held

	def _isSleeping(self) -> bool:
		"""La aplicación con el foco está en modo dormir (solo se atienden sus órdenes permitidas)."""
		chain = self.chain
		return bool(chain) and isinstance(chain[0], _SleepModeFilter)

	def _shouldTrapInBrowseMode(self, gesture: KeyboardGesture, fg: int | None = None) -> bool:
		if not conf["browseMode"]["trapNonCommandGestures"]:
			return False
		if gesture.modifiers - {"shift"} and not self._altGr:
			return False
		if not gesture.char or gesture.char.isspace():
			return False
		chain = self.chain if fg is None else self._chainFor(fg)
		for obj in chain:
			passThrough = getattr(obj, "passThrough", None)
			if passThrough is not None and hasattr(obj, "buffer"):
				return not passThrough
		return False

	def _preventMenuActivation(self) -> None:
		if {"alt", "windows"} & self._mods:
			winapi.sendInputs([winapi.makeKeyInput(DUMMY_VK), winapi.makeKeyInput(DUMMY_VK, up=True)])

	def _queueTyped(self, gesture: KeyboardGesture) -> None:
		if gesture.char and gesture.char.isprintable():
			queue_handler.queueFunction(_typedCharacter, gesture.char)

	def _afterPassedKey(self, gesture: KeyboardGesture) -> None:
		kb = conf["keyboard"]
		# Tab, Escape, Retroceso e Intro producen caracteres de control: no son
		# texto escrito y no se anuncian (el foco o el cursor ya lo dirán).
		isChar = bool(gesture.char) and gesture.char.isprintable() and not (gesture.modifiers - {"shift"})
		if isChar:
			if kb["speechInterruptForCharacters"]:
				queue_handler.queueFunction(_cancelSpeech)
			self._queueTyped(gesture)
			return
		if gesture.mainKeyName in ("enter", "numpadenter"):
			if kb["speechInterruptForEnter"]:
				queue_handler.queueFunction(_cancelSpeech)
			queue_handler.queueFunction(_typedCharacter, "\n")
			return
		queue_handler.queueFunction(_cancelSpeech)
		if kb["speakCommandKeys"]:
			queue_handler.queueFunction(_speakText, gesture.displayName)

	# ------------------------------------------------------------------ orden de las teclas
	def _holdIfPending(self, gesture: KeyboardGesture) -> bool:
		"""Hilo del gancho: si hay órdenes que reenvían su tecla sin terminar,
		la tecla no pasa ya: se encola detrás de ellas y se reenvía en orden."""
		if self._interceptPending <= 0 and self._deferCount <= 0:
			return False
		queue_handler.queueFunction(self._sendHeld, gesture)
		return True

	def _sendHeld(self, gesture: KeyboardGesture) -> None:
		"""Hilo del núcleo: reenvía una tecla retenida (o la guarda si una orden
		diferida aún no ha mandado la suya)."""
		if self._deferCount > 0:
			self._held.append(gesture)
			return
		try:
			gesture.send()
		except Exception:
			log.exception("No se pudo reenviar la tecla %r", gesture)

	def deferInterceptedSend(self, timeout: float = DEFER_TIMEOUT) -> Callable[[], None]:
		"""Para órdenes que reenvían su tecla más tarde (tras una llamada asíncrona).

		Mientras no se llame a la función devuelta (en el hilo del núcleo,
		justo después de ``gesture.send()`` o al decidir no enviarla), las
		teclas sin orden que se pulsen se guardan y se reenvían después, en
		orden. Se libera sola pasado ``timeout``.
		"""
		with self._sendLock:
			self._deferCount += 1
		done = [False]

		def release() -> None:
			if done[0]:
				return
			done[0] = True
			with self._sendLock:
				self._deferCount = max(0, self._deferCount - 1)
				flush = self._deferCount == 0
			if flush:
				held, self._held = self._held, []
				for g in held:
					try:
						g.send()
					except Exception:
						log.exception("No se pudo reenviar la tecla %r", g)

		if queue_handler._coreThreadId is not None:
			queue_handler.callLater(int(timeout * 1000), release)
		return release

	def _runScript(self, func, gesture: KeyboardGesture, resumeSayAll: bool = False, intercepts: bool = False, isRepeat: bool = False) -> None:
		try:
			self._executeScript(func, gesture, resumeSayAll, isRepeat=isRepeat)
		finally:
			if intercepts:
				with self._sendLock:
					self._interceptPending = max(0, self._interceptPending - 1)

	# ------------------------------------------------------------------ braille
	def executeBrailleGesture(self, gesture) -> None:
		"""Teclas de una línea braille (llamado en el hilo del núcleo)."""
		from ..braille import input as brailleInput

		# Los acordes de puntos y espacio también responden a los gestos
		# genéricos del teclado braille (``bk:dot1+dot2``, ``bk:dots``).
		brailleInput.addKeyboardIdentifiers(gesture)
		if len(decide_executeBrailleGesture) and not decide_executeBrailleGesture.decide(gesture=gesture):
			return
		func = self.findScript(gesture)
		if self.inputHelp and not (func and getattr(func, "bypassInputHelp", False)):
			_reportInputHelp(gesture, func)
			return
		if func is not None:
			self._executeScript(func, gesture)
			return
		dots = getattr(gesture, "dots", 0)
		space = getattr(gesture, "space", False)
		if dots or space:
			brailleInput.handler.handleGesture(gesture)

	# ------------------------------------------------------------------ táctil
	def executeTouchGesture(self, gesture) -> None:
		"""Gestos de la pantalla o el panel táctil (hilo del núcleo).

		La exploración con el dedo (``hover*``) no se captura en el diálogo de
		gestos ni se anuncia en la ayuda de entrada: así se puede seguir
		explorando la pantalla mientras tanto.
		"""
		isHover = getattr(gesture, "isHover", False)
		if self.captureFunc is not None and not isHover:
			self.captureFunc(gesture)
			return
		if not decide_executeGesture.decide(gesture=gesture):
			return
		func = self.findScript(gesture)
		if self.inputHelp:
			if isHover:
				if func is not None and gesture.action != "hoverUp":
					self._executeScript(func, gesture)
				return
			if not (func and getattr(func, "bypassInputHelp", False)):
				_reportInputHelp(gesture, func)
				return
		if func is not None:
			self._executeScript(func, gesture)

	# ------------------------------------------------------------------ ejecución
	def getLastScriptRepeatCount(self) -> int:
		return self._lastScriptRepeat

	def _clearLastScript(self) -> None:
		"""Una tecla sin orden entre dos pulsaciones: ya no es una doble pulsación."""
		self._lastScript = None
		self._lastScriptRepeat = 0

	def _executeScript(self, func, gesture: KeyboardGesture, resumeSayAll: bool = False, isRepeat: bool = False) -> None:
		from .. import speech
		from ..speech import sayall

		now = time.monotonic()
		key = getattr(func, "__func__", func)
		timeout = conf["keyboard"]["multiPressTimeout"] / 1000.0
		if key is self._lastScript and now - self._lastScriptTime < timeout:
			if not isRepeat:
				# Mantener la tecla pulsada (repetición automática) no cuenta
				# como pulsarla dos o tres veces.
				self._lastScriptRepeat += 1
		else:
			self._lastScriptRepeat = 0
		self._lastScript = key
		self._lastScriptTime = now
		if not getattr(func, "noSpeechInterrupt", False):
			speech.cancelSpeech()
		try:
			if getattr(func, "speakOnDemand", False):
				with speech.allowOnDemand():
					func(gesture)
			else:
				func(gesture)
		except Exception:
			# El sonido de error (advanced.playErrorSound) lo pone el registro (log.py).
			log.exception("Error ejecutando la orden %s", getattr(func, "__name__", func))
		post_scriptExecuted.notify(script=func, gesture=gesture)
		if resumeSayAll:
			# Se reanuda con el mismo cursor con el que se empezó (sistema, revisión o tabla).
			sayall.resume()

	# ------------------------------------------------------------------ ratón
	def _onMouse(self, msg: int, x: int, y: int, injected: bool) -> bool:
		if msg in _MOUSE_PRESS_MSGS:
			# Mayúsculas+clic (o rueda) no es «Mayúsculas sola»; como en
			# Windows, un clic suelta los modificadores enganchados.
			self._otherKeyWhileShift = True
			self._keyCounter += 1
			if self._latched:
				self._latched.clear()
			return False
		if msg == winapi.WM_LBUTTONUP and not injected:
			# Clic del usuario (el modo exploración mueve allí su cursor, #4896).
			if len(post_mouseClick):
				queue_handler.queueFunction(post_mouseClick.notify, x=x, y=y)
			return False
		if msg != winapi.WM_MOUSEMOVE:
			return False
		if injected and conf["mouse"]["ignoreInjectedMouseInput"]:
			return False
		self._lastMousePos = (x, y)
		if self._mouseTimer is None:
			self._mouseTimer = -1
			queue_handler.queueFunction(self._scheduleMouse)
		return False

	def _scheduleMouse(self) -> None:
		self._mouseTimer = queue_handler.callLater(80, self._processMouse)

	def _processMouse(self) -> None:
		self._mouseTimer = None
		pos = self._lastMousePos
		if pos is None:
			return
		from .. import mouse

		try:
			mouse.handleMouseMove(*pos)
		except Exception:
			log.debug("Error procesando el ratón", exc_info=True)


#: Marca de «carácter no calculado» (``KeyboardGesture.deadAfter``).
_NOT_COMPUTED = object()


class _PropagatingOnly:
	"""Envuelve un antecesor del foco: solo sus órdenes con ``canPropagate``."""

	def __init__(self, obj: Any) -> None:
		self.obj = obj

	def getScript(self, gesture):
		func = self.obj.getScript(gesture)
		if func and getattr(func, "canPropagate", False):
			return func
		return None


class _BrailleDisplayScripts:
	"""Órdenes del controlador braille activo (se resuelve en cada búsqueda,
	así un cambio de línea no exige recalcular la cadena)."""

	def getScript(self, gesture):
		try:
			from .. import braille

			display = braille.handler.display
		except Exception:
			return None
		getter = getattr(display, "getScript", None)
		return getter(gesture) if getter is not None else None


_brailleDisplayScripts = _BrailleDisplayScripts()


class _SleepModeFilter:
	def __init__(self, obj: Any) -> None:
		self.obj = obj

	def getScript(self, gesture):
		func = self.obj.getScript(gesture)
		if func and getattr(func, "allowInSleepMode", False):
			return func
		return None


# ---------------------------------------------------------------------- ayudas
def _cancelSpeech() -> None:
	from .. import speech

	speech.cancelSpeech()


def _pauseSpeechToggle() -> None:
	from .. import speech, synth

	s = synth.getSynth()
	if speech.isPaused():
		speech.pauseSpeech(False)
	elif s is not None and getattr(s, "_speaking", False):
		speech.pauseSpeech(True)


def _brailleInput(dots: int, space: bool) -> None:
	"""Escritura desde un teclado braille (la usa el acceso remoto).

	Pasa por la entrada braille (``braille.input``): tabla de entrada,
	signos de mayúscula y número, braille contraído y modificadores.
	"""
	from ..braille import input as brailleInput

	brailleInput.handler.handleGesture(brailleInput.BrailleKeyboardGesture(dots, space))


def _beep(hz: float, ms: int) -> None:
	from ..audio import tones

	tones.beep(hz, ms)


def _speakText(text: str) -> None:
	from .. import speech

	speech.speakMessage(text)


def _typedCharacter(ch: str) -> None:
	from .. import api

	focus = api.getFocusObject()
	if focus is None:
		from .. import typing_echo

		typing_echo.onTypedCharacter(None, ch)
		return
	from ..events import executeEvent

	executeEvent("typedCharacter", focus, ch=ch)


def _reportInputHelp(gesture: KeyboardGesture, func) -> None:
	from .. import speech

	parts = [gesture.displayName.replace("+", " ")]
	if gesture.char and len(gesture.char) == 1 and not (gesture.modifiers - {"shift"}):
		from ..speech.symbols import processor

		parts = [processor.characterName(gesture.char)]
	if func is not None:
		desc = (func.__doc__ or "").strip()
		if desc:
			parts.append(desc)
	speech.cancelSpeech()
	# speakMessage también lo muestra en la línea braille.
	speech.speakMessage(". ".join(parts))


manager = InputManager()


def getLastScriptRepeatCount() -> int:
	return manager.getLastScriptRepeatCount()
