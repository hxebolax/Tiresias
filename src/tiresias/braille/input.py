"""Entrada braille: escribir con el teclado braille de la línea (o del PC).

- Con una tabla **integral** cada celda se traduce al momento: el búfer
  guarda las celdas de la palabra actual para resolver los signos que
  afectan a lo siguiente (mayúscula, número) y se corrige lo escrito si la
  traducción cambia.
- Con una tabla **contraída** las celdas se acumulan (se ven en la línea en
  la posición del cursor) y la palabra se traduce al pulsar espacio, Intro o
  la orden «traducir».
- Los **conmutadores de modificadores** (Control, Alt, Mayúsculas, Windows y
  Tiresias) se aplican a la siguiente celda o tecla emulada: Control activado
  + celda «c» = Control+C; Tiresias + celda = la orden de Tiresias+tecla.
- El **teclado braille del PC** (opcional) convierte las teclas F D S J K L
  (y A, Ñ para los puntos 7 y 8, y la barra espaciadora) en un teclado
  braille de 6 u 8 puntos, independiente de la distribución del teclado.
"""

from __future__ import annotations

import time
from typing import Any

from .. import queue_handler, winapi
from ..config import conf
from ..i18n import _
from ..log import getLogger
from . import tables

log = getLogger("brailleInput")

MODIFIERS = ("control", "alt", "shift", "windows", "tiresias")
#: Segundos tras escribir en los que un movimiento del cursor se atribuye a
#: la propia entrada braille (y no reinicia la palabra en curso).
OWN_OUTPUT_WINDOW = 0.5
_MOD_NAMES = {
	"control": _("Control"),
	"alt": _("Alt"),
	"shift": _("Mayúsculas"),
	"windows": _("Windows"),
	"tiresias": _("Tiresias"),
}


def gestureKeyboardIds(dots: int, space: bool) -> list[str]:
	"""Identificadores genéricos del teclado braille (``bk:``) de un acorde."""
	keys = (["space"] if space else []) + [f"dot{i + 1}" for i in range(8) if dots & (1 << i)]
	if not keys:
		return []
	from ..baseobject import normalizeGestureId

	ids = [normalizeGestureId("bk:" + "+".join(keys))]
	if dots and not space:
		ids.append("bk:dots")
	return ids


def addKeyboardIdentifiers(gesture: Any) -> None:
	"""Añade a un gesto de línea los identificadores ``bk:`` si es de puntos."""
	dots = getattr(gesture, "dots", 0) or 0
	space = bool(getattr(gesture, "space", False))
	if not (dots or space) or getattr(gesture, "_bkAdded", False):
		return
	try:
		ids = list(gesture.identifiers)
		for gid in gestureKeyboardIds(dots, space):
			if gid not in ids:
				ids.append(gid)
		gesture.identifiers = ids
		gesture._bkAdded = True
	except Exception:
		log.debug("No se pudieron añadir los identificadores bk", exc_info=True)


class BrailleKeyboardGesture:
	"""Gesto del teclado braille emulado con el teclado del PC."""

	modifierNames: list[str] = []
	mainKeyName = ""
	char: str | None = None
	isModifier = False
	routingIndex = None
	routingIndexes: list[int] = []

	def __init__(self, dots: int, space: bool) -> None:
		from ..baseobject import normalizeGestureId

		self.dots = dots
		self.space = space
		keys = (["space"] if space else []) + [f"dot{i + 1}" for i in range(8) if dots & (1 << i)]
		self.keys = keys
		name = "+".join(keys)
		self.normalizedKeys = name
		self.identifiers = [normalizeGestureId(f"br(pcKeyboard):{name}")] + gestureKeyboardIds(dots, space)
		self._bkAdded = True
		self.displayName = _("teclado braille: {keys}").format(keys=name)

	def send(self) -> None:
		pass


class BrailleInputHandler:
	def __init__(self) -> None:
		self.cells: list[int] = []
		#: Texto ya escrito a partir de ``cells`` (tablas integrales).
		self.typed = ""
		self.modifiers: set[str] = set()
		#: Momento (``time.monotonic``) de lo último que ha escrito o borrado.
		self._ownOutputTime = -1e9

	# ---------------------------------------------------------- tabla
	@staticmethod
	def table() -> tables.Table:
		if pcKeyboard.perkins:
			# El modo Perkins escribe braille literario de 6 puntos (su propia tabla).
			from . import perkins

			return perkins.inputTable()
		return tables.getTable(conf["braille"]["inputTable"], forInput=True)

	def _wordText(self, table: tables.Table, cells: list[int]) -> str:
		"""Texto de las celdas de la palabra en curso."""
		text = self._backTranslate(table, cells)
		if pcKeyboard.perkins and text:
			from . import perkins

			text = perkins.fixSpanishMarks(text)
		return text

	def _backTranslate(self, table: tables.Table, cells: list[int]) -> str:
		try:
			return table.backTranslate(cells)
		except Exception:
			log.debug("Error traduciendo la entrada braille", exc_info=True)
			if isinstance(table, tables.LouisTable):
				tables.markBroken(table)
				return self._backTranslate(self.table(), cells)
			return ""

	# ---------------------------------------------------------- salida
	def _type(self, text: str) -> None:
		if not text:
			return
		self._ownOutputTime = time.monotonic()
		winapi.typeText(text)
		if conf["keyboard"]["speakTypedCharacters"] != "off" and len(text) == 1:
			from .. import api, speech
			from ..privacy import isProtected

			if isProtected(api.getFocusObject()):
				# Campo de contraseña: como con el teclado, solo un asterisco.
				with speech.speechOrigin(speech.ORIGIN_TYPING):
					speech.speak(speech.contextSequence("typing", ["*"]))
				return
			speech.speakTypedCharacter(text)

	def _backspace(self, count: int) -> None:
		from ..input.gestures import sendKey

		self._ownOutputTime = time.monotonic()
		for _i in range(count):
			sendKey("backspace")

	def _updateDisplay(self) -> None:
		from . import handler

		pending = self.cells if (self.table().contracted or not self.typed) else []
		handler.setInputCells(pending if self.cells else [])

	def reset(self) -> None:
		self.cells = []
		self.typed = ""
		self._updateDisplay()

	def onFocusChange(self) -> None:
		"""El foco cambia: se descarta lo pendiente y los modificadores."""
		self.modifiers = set()
		if self.cells or self.typed:
			self.cells = []
			self.typed = ""
			try:
				from . import handler

				handler._inputCells = []
			except Exception:
				pass

	def onCaretMove(self) -> None:
		"""El cursor se ha movido (o se ha escrito con el teclado normal).

		Si no lo ha causado la propia entrada braille, la palabra en curso se
		da por terminada: lo siguiente no corrige lo ya escrito.
		"""
		if not (self.cells or self.typed):
			return
		if time.monotonic() - self._ownOutputTime <= OWN_OUTPUT_WINDOW:
			return
		self.reset()

	# ---------------------------------------------------------- celdas
	def input(self, dots: int) -> None:
		"""Una celda escrita con el teclado braille (sin espacio)."""
		dots &= 0xFF
		if not dots:
			return
		table = self.table()
		if self.modifiers:
			self._inputWithModifiers(table, dots)
			return
		self.cells.append(dots)
		if table.contracted:
			self._updateDisplay()
			return
		text = self._wordText(table, self.cells)
		self._applyText(text)
		self._updateDisplay()
		if not text and len(self.cells) > 4:
			# Celdas que no producen texto: se descartan para no bloquear la escritura.
			self.reset()

	def _applyText(self, text: str) -> None:
		old = self.typed
		common = 0
		while common < min(len(old), len(text)) and old[common] == text[common]:
			common += 1
		if len(old) > common:
			self._backspace(len(old) - common)
		new = text[common:]
		if new:
			self._type(new)
		self.typed = text

	def _inputWithModifiers(self, table: tables.Table, dots: int) -> None:
		text = self._backTranslate(table, [dots]) or self._backTranslate(tables.getTable("es-comp8"), [dots])
		mods = [m for m in MODIFIERS if m in self.modifiers]
		self.modifiers = set()
		if not text:
			from .. import speech

			speech.speakMessage(_("combinación braille desconocida"))
			return
		key = text[0].lower()
		self.sendKey(key, mods)

	def sendKey(self, keyName: str, mods: list[str] | None = None) -> None:
		"""Envía una tecla con los modificadores indicados (o los activos)."""
		from ..input import core as inputCore
		from ..input.gestures import KeyboardGesture

		if mods is None:
			mods = [m for m in MODIFIERS if m in self.modifiers]
			self.modifiers = set()
		name = "+".join(mods + [keyName])
		if "tiresias" in mods:
			gesture = KeyboardGesture.fromName(name)
			func = inputCore.manager.findScript(gesture)
			if func is None:
				from .. import speech

				speech.speakMessage(_("{gesture} no tiene ninguna orden").format(gesture=name.replace("+", " ")))
				return
			inputCore.manager._executeScript(func, gesture)
			return
		try:
			gesture = KeyboardGesture.fromName(name)
			if gesture.vk:
				gesture.send()
				return
		except Exception:
			log.debug("No se pudo enviar %s", name, exc_info=True)
		if not mods and len(keyName) == 1:
			self._type(keyName)

	def space(self) -> None:
		table = self.table()
		if self.modifiers:
			self.sendKey("space")
			return
		if table.contracted and self.cells:
			text = self._backTranslate(table, self.cells)
			self.cells = []
			self.typed = ""
			self._updateDisplay()
			self._type(text + " ")
			return
		self.cells = []
		self.typed = ""
		self._updateDisplay()
		self._type(" ")

	def translate(self) -> None:
		"""Traduce lo pendiente (braille contraído) sin añadir espacio."""
		table = self.table()
		if self.cells and table.contracted:
			text = self._backTranslate(table, self.cells)
			self.cells = []
			self.typed = ""
			self._updateDisplay()
			self._type(text)
			return
		self.cells = []
		self.typed = ""
		self._updateDisplay()

	def enter(self) -> None:
		self.translate()
		self.sendKey("enter")

	def eraseLastCell(self, announce: bool = True) -> None:
		if not self.cells:
			self.sendKey("backspace", [])
			return
		self.cells.pop()
		table = self.table()
		if not table.contracted:
			self._applyText(self._wordText(table, self.cells) if self.cells else "")
		self._updateDisplay()
		if announce:
			from .. import speech

			speech.speakMessage(_("celda borrada"))

	# ---------------------------------------------------------- modificadores
	def toggleModifier(self, mod: str) -> str:
		if mod in self.modifiers:
			self.modifiers.discard(mod)
			return _("{mod} desactivado").format(mod=_MOD_NAMES[mod])
		self.modifiers.add(mod)
		return _("{mod} activado").format(mod=_MOD_NAMES[mod])

	def toggleModifiers(self, mods: tuple[str, ...]) -> str:
		names = " ".join(_MOD_NAMES[m] for m in mods)
		if all(m in self.modifiers for m in mods):
			for m in mods:
				self.modifiers.discard(m)
			return _("{mod} desactivado").format(mod=names)
		self.modifiers.update(mods)
		return _("{mod} activado").format(mod=names)

	# ---------------------------------------------------------- gestos sin orden
	def handleGesture(self, gesture: Any) -> None:
		"""Gesto de puntos o espacio sin orden asignada (hilo del núcleo)."""
		dots = getattr(gesture, "dots", 0) or 0
		space = bool(getattr(gesture, "space", False))
		if space and dots:
			from .. import speech

			# Espacio + puntos sin orden: no se escribe nada (antes escribía una letra).
			speech.speakMessage(_("combinación braille sin orden asignada"))
			return
		if space:
			self.space()
		elif dots:
			self.input(dots)


handler = BrailleInputHandler()


# ====================================================================== teclado braille del PC
#: Códigos de exploración (posición física, no dependen de la distribución).
_SCAN_DOTS = {0x21: 1, 0x20: 2, 0x1F: 3, 0x24: 4, 0x25: 5, 0x26: 6, 0x1E: 7, 0x27: 8}
_SCAN_SPACE = 0x39
#: Modo Perkins: las teclas de los lados hacen de las de la máquina.
#: A (a la izquierda de S) es la tecla de interlineado y Ñ (a la derecha de
#: L; «;» en los teclados ingleses), la de retroceso, como en la Perkins.
_SCAN_PERKINS_LINE = 0x1E
_SCAN_PERKINS_BACK = 0x27
_SCAN_ENTER = 0x1C
_SCAN_BACKSPACE = 0x0E
#: Teclas de una sola pulsación del modo Perkins (no forman acordes).
_PERKINS_SPECIAL = {_SCAN_PERKINS_LINE: "line", _SCAN_PERKINS_BACK: "back", _SCAN_ENTER: "line", _SCAN_BACKSPACE: "back"}


class PcBrailleKeyboard:
	"""Teclas del PC como teclado braille (se activa con una orden).

	Tiene dos formas:

	- **teclado braille del PC** (Tiresias+Control+Alt+B): F D S J K L (y A,
	  Ñ para los puntos 7 y 8) en cualquier sitio;
	- **modo Perkins** (Tiresias+Control+Mayúsculas+B): como una máquina
	  Perkins. Solo actúa al escribir en un campo de texto, un documento o
	  una consola (en los demás sitios el teclado es el normal), usa seis
	  puntos, A es la tecla de interlineado y Ñ la de retroceso (además de
	  Intro y Retroceso), suena como la máquina y toca la campana al acercarse
	  al final de la línea. Las demás teclas del teclado siguen funcionando.
	"""

	def __init__(self) -> None:
		self.enabled = False
		self.perkins = False
		self._down: set[int] = set()
		self._chord: set[int] = set()
		self._special: set[int] = set()
		self._registered = False
		#: Foco actual y si es un sitio donde se escribe (lo actualiza el núcleo).
		self._focusObj: Any = None
		self._focusEditable = False
		self._focusRegistered = False

	def setEnabled(self, on: bool, perkins: bool = False) -> None:
		from ..input import core as inputCore

		self.enabled = bool(on)
		self.perkins = self.enabled and bool(perkins)
		self._down.clear()
		self._chord.clear()
		self._special.clear()
		if self.enabled and not self._registered:
			inputCore.decide_handleRawKey.register(self.onRawKey)
			self._registered = True
		elif not self.enabled and self._registered:
			inputCore.decide_handleRawKey.unregister(self.onRawKey)
			self._registered = False
		if self.perkins:
			self._watchFocus()
			from . import perkins as perkinsModule

			perkinsModule.machine.reset()

	# ---------------------------------------------------------- foco (modo Perkins)
	def _watchFocus(self) -> None:
		from .. import api

		if not self._focusRegistered:
			api.post_focusChange.register(self._onFocusChange)
			self._focusRegistered = True
		self._onFocusChange(api.getFocusObject())

	def _onFocusChange(self, obj: Any = None) -> None:
		"""Hilo del núcleo: anota si el foco nuevo es un sitio donde se escribe."""
		from .. import clipboard

		self._focusObj = obj
		try:
			self._focusEditable = obj is not None and clipboard.focusIsEditable()
		except Exception:
			self._focusEditable = False
		if self.perkins:
			from . import perkins as perkinsModule

			perkinsModule.machine.reset()

	def perkinsActiveHere(self) -> bool:
		"""¿El modo Perkins actúa ahora? (en un campo de texto y fuera del modo exploración).

		Se llama en el hilo de los ganchos: solo lee atributos ya calculados.
		"""
		if not self.perkins:
			return False
		if not conf["braille"]["perkinsOnlyInEditable"]:
			return True
		if not self._focusEditable:
			return False
		obj = self._focusObj
		ti = obj.__dict__.get("_treeInterceptor") if obj is not None else None
		# En el modo exploración de una página, las letras son de navegación rápida.
		return ti is None or bool(getattr(ti, "_passThrough", True))

	def _keyFor(self, scanCode: int) -> int | None:
		"""Número de punto (1-8), 0 para el espacio o ``None``."""
		if scanCode == _SCAN_SPACE:
			return 0
		dot = _SCAN_DOTS.get(scanCode)
		if dot is None:
			return None
		if dot > 6 and (self.perkins or int(conf["braille"]["pcKeyboardDots"] or 8) == 6):
			return None
		return dot

	def onRawKey(self, vk: int = 0, scanCode: int = 0, extended: bool = False, pressed: bool = True, injected: bool = False) -> bool:
		"""Hilo de ganchos. ``False`` = la tecla se captura."""
		if not self.enabled or injected:
			return True
		if self.perkins:
			if scanCode in self._special:
				# La soltura de una tecla especial que se capturó al pulsarla.
				if not pressed:
					self._special.discard(scanCode)
				else:
					queue_handler.queueFunction(_executePerkinsKey, _PERKINS_SPECIAL[scanCode])
				return False
			if not self.perkinsActiveHere():
				if self._down or self._chord:
					self._down.clear()
					self._chord.clear()
				return True
			special = _PERKINS_SPECIAL.get(scanCode)
			if special is not None and not extended:
				if not pressed or self._down:
					return True
				from ..input import core as inputCore

				mgr = inputCore.manager
				if mgr._tiresiasDown or mgr._mods:
					return True
				self._special.add(scanCode)
				queue_handler.queueFunction(_executePerkinsKey, special)
				return False
		if extended:
			return True
		key = self._keyFor(scanCode)
		if key is None:
			return True
		if pressed:
			if scanCode in self._down:
				return False
			from ..input import core as inputCore

			mgr = inputCore.manager
			if not self._down and (mgr._tiresiasDown or mgr._mods):
				# Con modificadores la tecla funciona como siempre (atajos).
				return True
			if self.perkins and not self._down:
				# La máquina suena al bajar la primera tecla, no al soltarlas.
				from . import perkins as perkinsModule

				perkinsModule.machine.keyDown(key == 0)
			self._down.add(scanCode)
			self._chord.add(key)
			return False
		if scanCode not in self._down:
			return True
		self._down.discard(scanCode)
		if not self._down and self._chord:
			chord = self._chord
			self._chord = set()
			dots = 0
			for k in chord:
				if k:
					dots |= 1 << (k - 1)
			queue_handler.queueFunction(_executePcGesture, dots, 0 in chord)
		return False


def _executePerkinsKey(action: str) -> None:
	"""Interlineado (A o Intro) o retroceso (Ñ o Retroceso) del modo Perkins (hilo del núcleo)."""
	from . import perkins as perkinsModule

	if action == "line":
		perkinsModule.machine.newLine()
		handler.enter()
	else:
		perkinsModule.machine.backspace()
		handler.eraseLastCell(announce=False)


def _executePcGesture(dots: int, space: bool) -> None:
	from ..input import core as inputCore

	mgr = inputCore.manager
	if pcKeyboard.perkins and bool(dots) != bool(space):
		# Una celda o un espacio: el carro avanza (y quizá suena la campana).
		from . import perkins as perkinsModule

		perkinsModule.machine.cell()
	gesture = BrailleKeyboardGesture(dots, space)
	capture = getattr(mgr, "captureFunc", None)
	if capture is not None:
		# «Gestos de entrada» esperando un gesto: se captura (aunque no haya
		# ninguna línea conectada que registre el decisor de los gestos braille).
		try:
			capture(gesture)
		except Exception:
			log.exception("Error capturando el gesto del teclado braille")
		return
	mgr.executeBrailleGesture(gesture)


pcKeyboard = PcBrailleKeyboard()
