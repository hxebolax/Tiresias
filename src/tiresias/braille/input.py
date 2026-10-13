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
		return tables.getTable(conf["braille"]["inputTable"], forInput=True)

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
		text = self._backTranslate(table, self.cells)
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

	def eraseLastCell(self) -> None:
		if not self.cells:
			self.sendKey("backspace", [])
			return
		self.cells.pop()
		table = self.table()
		if not table.contracted:
			self._applyText(self._backTranslate(table, self.cells) if self.cells else "")
		self._updateDisplay()
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


class PcBrailleKeyboard:
	"""Teclas del PC como teclado braille (se activa con una orden)."""

	def __init__(self) -> None:
		self.enabled = False
		self._down: set[int] = set()
		self._chord: set[int] = set()
		self._registered = False

	def setEnabled(self, on: bool) -> None:
		from ..input import core as inputCore

		self.enabled = bool(on)
		self._down.clear()
		self._chord.clear()
		if self.enabled and not self._registered:
			inputCore.decide_handleRawKey.register(self.onRawKey)
			self._registered = True
		elif not self.enabled and self._registered:
			inputCore.decide_handleRawKey.unregister(self.onRawKey)
			self._registered = False

	def _keyFor(self, scanCode: int) -> int | None:
		"""Número de punto (1-8), 0 para el espacio o ``None``."""
		if scanCode == _SCAN_SPACE:
			return 0
		dot = _SCAN_DOTS.get(scanCode)
		if dot is None:
			return None
		if dot > 6 and int(conf["braille"]["pcKeyboardDots"] or 8) == 6:
			return None
		return dot

	def onRawKey(self, vk: int = 0, scanCode: int = 0, extended: bool = False, pressed: bool = True, injected: bool = False) -> bool:
		"""Hilo de ganchos. ``False`` = la tecla se captura."""
		if not self.enabled or injected or extended:
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


def _executePcGesture(dots: int, space: bool) -> None:
	from ..input import core as inputCore

	mgr = inputCore.manager
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
