"""Comportamientos comunes que se mezclan con los objetos (clases superpuestas).

- :class:`EditableTextWithCaret`: lectura al mover el cursor en campos de
  edición y documentos editables, anuncio de selección (también la que hace
  el ratón o la aplicación), borrado, frases e Intro.
- :class:`ReadOnlyDocument`: documentos de solo lectura con cursor.
- :class:`EditableTextNoCaret`: campos sin patrón Text ni mensajes de edición:
  se lee el valor y un cursor «virtual» que sigue las flechas.
- :class:`Terminal` (en :mod:`.terminal`): consolas.
- :class:`ProgressBar`: pitidos o voz con el progreso.
- :class:`Dialog` y :class:`WebDialog`: lectura del texto de los diálogos.
- :class:`SelectableItem` y :class:`ListContainer`: selección en listas.
- :class:`Toast`: notificaciones emergentes de Windows 10/11.

Ninguna orden espera con ``sleep`` en el hilo del núcleo: tras enviar la
tecla a la aplicación se comprueba el cursor con temporizadores
(``queue_handler.callLater``) o al llegar el evento de cursor.
"""

from __future__ import annotations

import difflib
import time

from .. import a11y as _a11y  # noqa: F401  (registra las opciones de esta área)
from .. import api as _api
from .. import queue_handler, speech, textinfo
from ..baseobject import script
from ..config import conf
from ..extension_points import Action
from ..i18n import _
from ..log import getLogger
from ..privacy import isProtected
from .base import AccObject
from .roles import Role, State

log = getLogger("behaviors")

CAT_TEXT = _("Revisión de texto")
CAT_LIST = _("Listas y tablas")

#: Comprobación pendiente del cursor tras una orden (solo hay una a la vez).
_watch: dict | None = None
#: Intervalo entre comprobaciones del cursor (ms).
_POLL_MS = 15
#: Última selección conocida para la detección automática: (objeto, TextInfo).
_lastSelection: tuple | None = None
#: Último cursor conocido: (objeto, marca).
_lastCaret: tuple | None = None

#: Tras leer el cursor que ha movido una orden (flechas, Inicio, Avanzar
#: página...), cuando el movimiento ya ha terminado y se ha pedido leerlo:
#: ``obj``, ``info`` (TextInfo en el cursor nuevo) y ``unit`` (unidad leída).
#: Lo usa el analizador de texto (aviso de incoherencias de la línea nueva).
post_caretMoved = Action()


def notifyCaretMoved(obj, info, unit: str) -> None:
	if len(post_caretMoved):
		post_caretMoved.notify(obj=obj, info=info, unit=unit)


def _cancelWatch() -> None:
	global _watch
	if _watch is not None and _watch.get("timer") is not None:
		queue_handler.cancelCallLater(_watch["timer"])
	_watch = None


def _pollWatch() -> None:
	"""Comprueba si el cursor (o la selección) ya cambió tras una orden."""
	global _watch
	w = _watch
	if w is None:
		return
	w["timer"] = None
	obj = w["obj"]
	started = time.monotonic()
	new = None
	changed = False
	sig = w.get("sig")
	if sig is not None and not w["selection"] and started < w["deadline"]:
		# Rev. 10.11 (A4): mientras el cursor no se mueva no se crea el rango
		# (en campos Win32 e IA2 copiaba el texto completo cada 15 ms).
		if _caretSignature(obj) == sig:
			w["timer"] = queue_handler.callLater(_POLL_MS, _pollWatch)
			return
	try:
		if w["selection"]:
			new = obj.makeTextInfo(textinfo.POSITION_SELECTION)
			old = w["old"]
			changed = new.compareEndPoints(old, "startToStart") != 0 or new.compareEndPoints(old, "endToEnd") != 0
		else:
			new = obj._getCaretInfo()
			changed = new is not None and (w["old"] is None or new.bookmark != w["old"])
	except Exception:
		new = None
	now = time.monotonic()
	slow = (now - started) * 1000 > conf["objects"]["slowProviderThresholdMs"]
	if changed or now >= w["deadline"] or slow or (new is None and w["selection"]):
		_watch = None
		if _focusChange[0] != w["focusSeq"]:
			# La tecla ha llevado el foco a otro control (la celda siguiente de
			# una fila, una cuadrícula...): ya lo lee el foco; el cursor del
			# objeto anterior no se anuncia ni corta esa lectura.
			return
		try:
			w["done"](new, changed)
		except Exception:
			log.exception("Error anunciando el movimiento del cursor")
		return
	w["timer"] = queue_handler.callLater(_POLL_MS, _pollWatch)


def _caretSignature(obj):
	"""Firma barata del cursor (sin copiar el texto) o ``None`` si el control no la da."""
	try:
		func = getattr(getattr(obj, "TextInfo", None), "caretSignature", None)
		return func(obj) if func is not None else None
	except Exception:
		return None


def _rememberSelection(obj, info=None) -> None:
	global _lastSelection
	try:
		sel = info if info is not None else obj.makeTextInfo(textinfo.POSITION_SELECTION)
		_lastSelection = (obj, sel.copy())
	except Exception:
		_lastSelection = None


#: Último elemento anunciado en un cuadro combinado editable: (texto, instante).
#: Evita decirlo dos veces cuando llegan el cambio de texto del campo y la
#: selección del elemento de la lista por la misma pulsación.
_comboAnnounced: tuple[str, float] | None = None
_COMBO_REPEAT_WINDOW = 0.6


def _noteAnnounced(text: str) -> None:
	global _comboAnnounced
	_comboAnnounced = (text.strip(), time.monotonic())


def _recentlyAnnounced(text: str) -> bool:
	last = _comboAnnounced
	return bool(last) and last[0] == text.strip() and time.monotonic() - last[1] < _COMBO_REPEAT_WINDOW


def _rememberCaret(obj, info=None) -> None:
	global _lastCaret
	try:
		info = info if info is not None else obj._getCaretInfo()
		_lastCaret = (obj, info.bookmark) if info is not None else None
	except Exception:
		_lastCaret = None


class EditableText(AccObject):
	"""Base para objetos con texto editable: eco de teclado y cursor."""

	#: Tiempo máximo de espera a que el cursor se mueva tras una tecla (s).
	caretMovementTimeout = 0.25
	#: Leer la línea nueva al pulsar Intro en campos multilínea.
	announceNewLineText = True

	def _getCaretInfo(self):
		try:
			return self.makeTextInfo(textinfo.POSITION_CARET)
		except Exception:
			return None

	def _startWatch(self, old, done, selection: bool = False) -> None:
		pending = self.__dict__.pop("_pendingCaretSig", None)
		# Solo la firma tomada justo antes de esta orden (no una que quedó de otra).
		sig = pending[0] if pending and time.monotonic() - pending[1] < 1.0 else None
		global _watch
		_cancelWatch()
		_watch = {
			"obj": self,
			"old": old,
			"deadline": time.monotonic() + self.caretMovementTimeout,
			"done": done,
			"selection": selection,
			"timer": None,
			"focusSeq": _focusChange[0],
			"sig": None if selection else sig,
		}
		_watch["timer"] = queue_handler.callLater(10, _pollWatch)

	def _caretMovementScriptHelper(self, gesture, unit: str) -> None:
		old = self._getCaretInfo()
		# Firma barata del cursor antes de la tecla: la vigilancia no copia el texto (A4).
		sig = _caretSignature(self) if old is not None else None
		gesture.send()
		if old is None:
			return

		def done(info, changed: bool) -> None:
			from .. import presentation, review

			if info is None:
				info = self._getCaretInfo()
				if info is None:
					return
			_rememberCaret(self, info)
			_rememberSelection(self)
			review.handleCaretMove(self, info)
			speech.cancelSpeech()
			presentation.speakTextInfo(info, unit, reason=presentation.Reason.CARET)
			notifyCaretMoved(self, info, unit)

		# La firma va aparte (no como argumento): hay sustitutos de _startWatch
		# con la firma antigua (pruebas, módulos de aplicación).
		self.__dict__["_pendingCaretSig"] = (sig, time.monotonic())
		self._startWatch(old.bookmark, done)

	def _selectionScriptHelper(self, gesture) -> None:
		try:
			old = self.makeTextInfo(textinfo.POSITION_SELECTION)
		except Exception:
			gesture.send()
			return
		gesture.send()

		def done(new, changed: bool) -> None:
			from .. import presentation

			if new is None:
				return
			_rememberSelection(self, new)
			_rememberCaret(self)
			speech.cancelSpeech()
			presentation.speakSelectionChange(old, new)

		self._startWatch(old, done, selection=True)

	# ------------------------------------------------------- órdenes
	@script(gestures=("kb:upArrow", "kb:downArrow"))
	def script_caret_moveByLine(self, gesture) -> None:
		if self._isComboBoxEdit():
			self._comboEditArrow(gesture)
			return
		self._caretMovementScriptHelper(gesture, textinfo.UNIT_LINE)

	def _isComboBoxEdit(self) -> bool:
		"""Campo de una línea que forma parte de un cuadro combinado editable."""
		try:
			if State.MULTILINE in self.states:
				return False
			parent = self.parent
			return parent is not None and parent.role == Role.COMBOBOX
		except Exception:
			return False

	def _wholeText(self) -> str | None:
		try:
			return self.makeTextInfo(textinfo.POSITION_ALL).text
		except Exception:
			return None

	def _comboEditArrow(self, gesture) -> None:
		"""Flechas en un cuadro combinado editable: el texto se sustituye por otro
		elemento de la lista. Se anuncia en cuanto cambia (sin esperar al cursor)
		y una sola vez aunque la lista anuncie también su elemento seleccionado."""
		old = self._wholeText()
		gesture.send()
		# Los cuadros combinados cambian el texto enseguida: espera más corta.
		deadline = time.monotonic() + min(self.caretMovementTimeout, 0.12)

		def poll() -> None:
			text = self._wholeText()
			if text is None:
				return
			if text == old and time.monotonic() < deadline:
				queue_handler.callLater(10, poll)
				return
			_rememberCaret(self)
			_rememberSelection(self)
			if text == old:
				# Sin cambio (primer o último elemento): se repite el valor, salvo
				# que la lista acabe de anunciar ese mismo elemento.
				if _recentlyAnnounced(text):
					return
				speech.cancelSpeech()
				speech.speakText(text or _("en blanco"))
				return
			if _recentlyAnnounced(text):
				return
			speech.cancelSpeech()
			_noteAnnounced(text)
			speech.speakText(text or _("en blanco"))

		queue_handler.callLater(10, poll)

	@script(gestures=("kb:leftArrow", "kb:rightArrow"))
	def script_caret_moveByCharacter(self, gesture) -> None:
		self._caretMovementScriptHelper(gesture, textinfo.UNIT_CHARACTER)

	@script(gestures=("kb:control+leftArrow", "kb:control+rightArrow"))
	def script_caret_moveByWord(self, gesture) -> None:
		self._caretMovementScriptHelper(gesture, textinfo.UNIT_WORD)

	@script(gestures=("kb:control+upArrow", "kb:control+downArrow"))
	def script_caret_moveByParagraph(self, gesture) -> None:
		if textinfo.paragraphStyle() == "application" or self._isTerminalLike():
			self._caretMovementScriptHelper(gesture, textinfo.UNIT_PARAGRAPH)
			return
		# Estilo de párrafo propio: Tiresias mueve el cursor (párrafos separados por
		# saltos de línea o por líneas en blanco, según «Navegación por documentos»).
		self._moveCaretByUnit(textinfo.UNIT_PARAGRAPH, 1 if gesture.mainKeyName == "downarrow" else -1, gesture=gesture)

	@script(
		description=_("Mueve el cursor a la frase anterior o siguiente y la lee"),
		category=CAT_TEXT,
		gestures=("kb:alt+upArrow", "kb:alt+downArrow"),
	)
	def script_caret_moveBySentence(self, gesture) -> None:
		"""Frase siguiente o anterior (en un cuadro combinado, Alt+flechas lo abren)."""
		if self.role == Role.COMBOBOX or self._isTerminalLike() or self._altArrowOpensPopup():
			gesture.send()
			return
		self._moveCaretByUnit(textinfo.UNIT_SENTENCE, 1 if gesture.mainKeyName == "downarrow" else -1, gesture=gesture)

	def _altArrowOpensPopup(self) -> bool:
		"""Alt+flechas abren o cierran la lista del control (no son frases).

		El campo de un cuadro combinado editable (el cuadro de búsqueda de
		Tiresias, los de «Abrir» y «Guardar como»...) y los campos de una línea
		con lista o calendario desplegable (``haspopup``, expandido o contraído)."""
		if self._isComboBoxEdit():
			return True
		try:
			states = self.states
		except Exception:
			return False
		if State.MULTILINE in states or self.role == Role.DOCUMENT:
			return False
		return bool(states & {State.HASPOPUP, State.EXPANDED, State.COLLAPSED})

	def _isTerminalLike(self) -> bool:
		return any(k.__name__ == "Terminal" for k in type(self).__mro__)

	def _moveCaretByUnit(self, unit: str, direction: int, gesture=None) -> None:
		"""Mueve el cursor del sistema con el TextInfo (unidades que la aplicación no tiene).

		Si se da ``gesture`` y el control no tiene cursor de texto o no sabe moverse
		por esa unidad, la tecla se envía a la aplicación en vez de perderse."""
		from .. import presentation, review
		from ..audio import tones

		info = self._getCaretInfo()
		if info is None:
			if gesture is not None:
				gesture.send()
			return
		try:
			moved = info.move(unit, direction)
		except NotImplementedError:
			if gesture is not None:
				gesture.send()
			return
		if unit == textinfo.UNIT_PARAGRAPH and moved and not hasattr(info, "offsets") and textinfo.paragraphStyle() == "multiLineBreak":
			# UIA no tiene párrafos separados por líneas en blanco: se saltan los
			# párrafos hasta pasar una línea en blanco.
			for _i in range(500):
				probe = info.copy()
				probe.expand(textinfo.UNIT_PARAGRAPH)
				prev = info.copy()
				if prev.move(textinfo.UNIT_PARAGRAPH, -1):
					prev.expand(textinfo.UNIT_PARAGRAPH)
					if not prev.text.strip() and probe.text.strip():
						break
				if not info.move(textinfo.UNIT_PARAGRAPH, direction):
					break
		if not moved:
			tones.playSound("boundaryStart" if direction < 0 else "boundaryEnd")
			return
		try:
			info.updateCaret()
		except Exception:
			log.debug("No se pudo mover el cursor", exc_info=True)
		_rememberCaret(self, info)
		review.handleCaretMove(self, info)
		speech.cancelSpeech()
		presentation.speakTextInfo(info, unit, reason=presentation.Reason.CARET)
		notifyCaretMoved(self, info, unit)

	@script(gestures=("kb:home", "kb:end", "kb:pageUp", "kb:pageDown"))
	def script_caret_moveByLineBoundary(self, gesture) -> None:
		unit = textinfo.UNIT_LINE if gesture.mainKeyName in ("pageup", "pagedown") else textinfo.UNIT_CHARACTER
		self._caretMovementScriptHelper(gesture, unit)

	@script(gestures=("kb:control+home", "kb:control+end"))
	def script_caret_moveToDocumentBoundary(self, gesture) -> None:
		self._caretMovementScriptHelper(gesture, textinfo.UNIT_LINE)

	@script(
		gestures=(
			"kb:shift+upArrow",
			"kb:shift+downArrow",
			"kb:shift+leftArrow",
			"kb:shift+rightArrow",
			"kb:shift+control+leftArrow",
			"kb:shift+control+rightArrow",
			"kb:shift+control+upArrow",
			"kb:shift+control+downArrow",
			"kb:shift+home",
			"kb:shift+end",
			"kb:shift+pageUp",
			"kb:shift+pageDown",
			"kb:shift+control+home",
			"kb:shift+control+end",
			"kb:control+a",
		)
	)
	def script_caret_changeSelection(self, gesture) -> None:
		self._selectionScriptHelper(gesture)

	@script(gestures=("kb:backspace", "kb:shift+backspace"))
	def script_caret_backspaceCharacter(self, gesture) -> None:
		try:
			readOnly = State.READONLY in self.states and self.role in (Role.EDITABLETEXT, Role.DOCUMENT) and not self._isTerminalLike()
		except Exception:
			readOnly = False
		if readOnly:
			# Rev. 10.11 (B8): en un campo de solo lectura no se borra nada; antes
			# se anunciaba el carácter como si se hubiera borrado.
			gesture.send()
			return
		info = self._getCaretInfo()
		deleted = ""
		if info is not None:
			try:
				sel = self.makeTextInfo(textinfo.POSITION_SELECTION)
				if not sel.isCollapsed:
					deleted = sel.text
				else:
					c = info.copy()
					if c.move(textinfo.UNIT_CHARACTER, -1, endPoint="start"):
						deleted = c.text
			except Exception:
				deleted = ""
		gesture.send()
		if isProtected(self):
			deleted = ""
		# Rev. 1.0.14: lo borrado se anuncia siempre, como en NVDA, aunque el eco
		# de caracteres esté apagado (antes Retroceso se quedaba mudo).
		if deleted:
			speech.cancelSpeech()
			if len(deleted) == 1:
				speech.speakCharacter(deleted)
			else:
				speech.speakText(_("{text} eliminado").format(text=deleted))
		if info is not None:
			self._startWatch(info.bookmark, lambda new, changed: _rememberCaret(self, new))

	@script(gestures=("kb:control+backspace", "kb:shift+control+backspace"))
	def script_caret_backspaceWord(self, gesture) -> None:
		info = self._getCaretInfo()
		deleted = ""
		if info is not None:
			try:
				c = info.copy()
				if c.move(textinfo.UNIT_WORD, -1, endPoint="start"):
					deleted = c.text
			except Exception:
				pass
		gesture.send()
		if isProtected(self):
			return
		if deleted.strip():
			speech.cancelSpeech()
			speech.speakText(deleted)

	@script(gestures=("kb:delete", "kb:numpadDelete", "kb:shift+delete", "kb:shift+numpadDelete", "kb:control+delete", "kb:control+numpadDelete"))
	def script_caret_delete(self, gesture) -> None:
		old = self._getCaretInfo()
		gesture.send()
		if old is None or isProtected(self):
			return
		unit = textinfo.UNIT_WORD if "control" in gesture.modifierNames else textinfo.UNIT_CHARACTER
		oldText = ""
		try:
			c = old.copy()
			c.expand(textinfo.UNIT_LINE)
			oldText = c.text
		except Exception:
			pass

		def check(new, changed: bool) -> None:
			from .. import presentation

			info = new or self._getCaretInfo()
			if info is None:
				return
			_rememberCaret(self, info)
			speech.cancelSpeech()
			presentation.speakTextInfo(info, unit, reason=presentation.Reason.CARET)

		# El cursor no se mueve al suprimir: se espera a que cambie el texto.
		self._startDeleteWatch(oldText, check)

	def _startDeleteWatch(self, oldLineText: str, done) -> None:
		global _watch
		_cancelWatch()
		deadline = time.monotonic() + self.caretMovementTimeout

		def poll() -> None:
			global _watch
			w = _watch
			if w is None or w.get("kind") != "delete":
				return
			info = self._getCaretInfo()
			text = ""
			if info is not None:
				try:
					c = info.copy()
					c.expand(textinfo.UNIT_LINE)
					text = c.text
				except Exception:
					pass
			if text != oldLineText or time.monotonic() >= deadline:
				_watch = None
				done(info, text != oldLineText)
				return
			w["timer"] = queue_handler.callLater(_POLL_MS, poll)

		_watch = {"obj": self, "kind": "delete", "timer": queue_handler.callLater(10, poll)}

	def event_valueChange(self) -> None:
		# El texto cambia al escribir: ya lo anuncia el eco de teclado.
		pass

	def event_caret(self) -> None:
		from .. import review

		w = _watch
		if w is not None and w.get("obj") == self and "selection" in w:
			# Hay una orden esperando este movimiento: se comprueba ya.
			if w.get("timer") is not None:
				queue_handler.cancelCallLater(w["timer"])
			_pollWatch()
			return
		info = self._getCaretInfo()
		if info is not None:
			review.handleCaretMove(self, info)
			_rememberCaret(self, info)
		self._detectSelectionChange()

	def _detectSelectionChange(self) -> None:
		"""Anuncia la selección hecha sin teclas de Tiresias (ratón, la aplicación…)."""
		global _lastSelection
		try:
			new = self.makeTextInfo(textinfo.POSITION_SELECTION)
		except Exception:
			return
		last = _lastSelection
		_lastSelection = (self, new.copy())
		if last is None or last[0] != self:
			return
		old = last[1]
		try:
			if old.isCollapsed and new.isCollapsed:
				return
			if new.compareEndPoints(old, "startToStart") == 0 and new.compareEndPoints(old, "endToEnd") == 0:
				return
			if self._isWholeValueOfComboBox(new):
				# Flechas en un cuadro combinado editable: el texto se sustituye por
				# el elemento nuevo, seleccionado entero. El valor ya se anuncia; la
				# diferencia de selección («a seleccionado») sería un anuncio falso.
				return
		except Exception:
			return
		from .. import presentation

		presentation.speakSelectionChange(old, new)

	def _isWholeValueOfComboBox(self, sel) -> bool:
		"""``sel`` abarca todo el texto de un campo que es parte de un cuadro combinado."""
		if sel.isCollapsed:
			return False
		parent = self.parent
		if parent is None or parent.role != Role.COMBOBOX:
			return False
		whole = self.makeTextInfo(textinfo.POSITION_ALL)
		return sel.compareEndPoints(whole, "startToStart") == 0 and sel.compareEndPoints(whole, "endToEnd") == 0

	def event_typedCharacter(self, ch: str) -> None:
		super().event_typedCharacter(ch)
		# Aviso de caracteres restantes (foros 1.17).
		from . import text_limits

		text_limits.scheduleCheck(self)
		if ch == "\n" and self.announceNewLineText and (State.MULTILINE in self.states or self.role == Role.DOCUMENT):
			self._announceNewLine()

	def _announceNewLine(self) -> None:
		"""Tras Intro en un campo multilínea, lee la línea nueva si no está vacía."""
		last = _lastCaret
		old = last[1] if last is not None and last[0] == self else None

		def done(info, changed: bool) -> None:
			from .. import presentation

			if info is None or not changed:
				return
			_rememberCaret(self, info)
			_rememberSelection(self)
			line = info.copy()
			try:
				line.expand(textinfo.UNIT_LINE)
				text = line.text
			except Exception:
				return
			if text.strip():
				presentation.speakTextInfo(info, textinfo.UNIT_LINE, reason=presentation.Reason.CARET)

		if old is None:
			info = self._getCaretInfo()
			if info is not None:
				done(info, True)
			return
		self._startWatch(old, done)

	def event_gainFocus(self) -> None:
		super().event_gainFocus()
		info = self._getCaretInfo()
		if info is not None:
			from .. import review

			review.handleCaretMove(self, info)
			_rememberCaret(self, info)
		_rememberSelection(self)
		from . import text_limits

		text_limits.forget(self)
		if conf["objects"]["reportMaxLength"]:
			try:
				maxLen = self.maxLength
			except Exception:
				maxLen = None
			if maxLen:
				speech.speakMessage(_("máximo {n} caracteres").format(n=maxLen))

	def event_loseFocus(self) -> None:
		global _lastSelection
		if _watch is not None and _watch.get("obj") == self:
			_cancelWatch()
		if _lastSelection is not None and _lastSelection[0] == self:
			_lastSelection = None
		super().event_loseFocus()


class EditableTextWithCaret(EditableText):
	pass


class ReadOnlyDocument(EditableText):
	"""Documento no editable con cursor (p. ej. ayuda, visor de texto)."""

	announceNewLineText = False

	@script(gestures=("kb:backspace", "kb:shift+backspace"))
	def script_caret_backspaceCharacter(self, gesture) -> None:
		gesture.send()

	@script(gestures=("kb:delete", "kb:numpadDelete", "kb:shift+delete", "kb:shift+numpadDelete", "kb:control+delete", "kb:control+numpadDelete"))
	def script_caret_delete(self, gesture) -> None:
		gesture.send()


# ====================================================================== sin cursor
#: Cursor virtual de los campos sin cursor accesible: clave -> [valor, posición].
_virtualCarets: dict = {}


class EditableTextNoCaret(AccObject):
	"""Campo editable sin patrón Text ni mensajes de edición.

	El valor se lee con UIA (patrón Value), MSAA (``accValue``) o Java. Como no
	se sabe dónde está el cursor, se mantiene uno «virtual»: empieza al final
	del texto, sigue a las flechas, Inicio, Fin y Control+flechas, y se
	recoloca donde cambió el texto al escribir o borrar.
	"""

	def _vkey(self):
		try:
			rid = getattr(self, "runtimeId", None)
			return tuple(rid) if rid else (self.processID, self.windowHandle, self.role)
		except Exception:
			return None

	def _state(self) -> list:
		key = self._vkey()
		st = _virtualCarets.get(key)
		if st is None:
			val = self.value or ""
			st = _virtualCarets[key] = [val, len(val)]
			if len(_virtualCarets) > 50:
				_virtualCarets.pop(next(iter(_virtualCarets)))
		return st

	def _syncValue(self) -> list:
		"""Relee el valor y coloca el cursor virtual donde cambió."""
		st = self._state()
		self.invalidateCache()
		new = self.value or ""
		old = st[0]
		if new != old:
			matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
			pos = st[1]
			for tag, _i1, _i2, _j1, j2 in matcher.get_opcodes():
				if tag != "equal":
					pos = j2
			st[0], st[1] = new, max(0, min(pos, len(new)))
		return st

	def event_valueChange(self) -> None:
		self._syncValue()

	def reportFocus(self) -> None:
		if self._isRowCell():
			# Celda de otra fila (flechas arriba y abajo dentro de una columna o el
			# foco que vuelve a la lista): primero el nombre de la fila (el archivo).
			try:
				row = self.parent
				if row is not None and not _sameRow(_focusHistory[0], row):
					name = row.name
					if name:
						speech.speak([name], origin=speech.ORIGIN_FOCUS, isValid=speech.focusValidator(self))
			except Exception:
				log.debug("No se pudo leer la fila de la celda", exc_info=True)
		super().reportFocus()

	def event_gainFocus(self) -> None:
		val = self.value or ""
		_virtualCarets[self._vkey()] = [val, len(val)]
		if len(_virtualCarets) > 50:
			# Cada campo enfocado añade una entrada: sin límite crecía toda la sesión.
			_virtualCarets.pop(next(iter(_virtualCarets)))
		super().event_gainFocus()
		from . import text_limits

		text_limits.forget(self)
		if conf["objects"]["reportMaxLength"]:
			maxLen = text_limits.maxLengthOf(self)
			if maxLen:
				speech.speakMessage(_("máximo {n} caracteres").format(n=maxLen))

	def event_typedCharacter(self, ch: str) -> None:
		super().event_typedCharacter(ch)
		# Aviso de caracteres restantes (foros 1.17).
		from . import text_limits

		text_limits.scheduleCheck(self)

	#: Roles de las filas y elementos cuyas celdas de solo lectura se recorren
	#: con las flechas moviendo el foco (columnas de la vista Detalles del
	#: Explorador de Windows 11, cuadrículas).
	_ROW_ROLES = frozenset({Role.LISTITEM, Role.DATAITEM, Role.TABLEROW, Role.TREEVIEWITEM, Role.TABLECELL})

	def _isRowCell(self) -> bool:
		"""Celda de solo lectura de una fila: las flechas pasan a otra celda (otro
		foco), no mueven ningún cursor."""
		cached = getattr(self, "_rowCellCache", None)
		if cached is not None:
			return cached
		result = False
		try:
			if State.READONLY in self.states:
				parent = self.parent
				result = parent is not None and parent.role in self._ROW_ROLES
		except Exception:
			result = False
		self._rowCellCache = result
		return result

	def _get_presentAsCell(self) -> bool:
		# Se lee como una celda: «Tipo: Excel.CSV», sin «edición» ni «solo lectura».
		return self._isRowCell()

	def _afterKey(self, gesture, action) -> None:
		if self._isRowCell():
			# Las flechas llevan el foco a la celda vecina y la lee el foco; en la
			# primera o la última no pasa nada (como sin lector).
			gesture.send()
			return
		seq = _focusChange[0]
		gesture.send()

		def run() -> None:
			if _focusChange[0] != seq:
				# La tecla ha movido el foco a otro control: ya lo ha leído el foco
				# y el valor de este campo no debe cortarlo.
				return
			action()

		# El valor tarda un poco en actualizarse: se relee en el siguiente ciclo.
		queue_handler.callLater(40, run)

	@script(gestures=("kb:upArrow", "kb:downArrow"))
	def script_valueAfterKey(self, gesture) -> None:
		def speak() -> None:
			st = self._syncValue()
			st[1] = len(st[0])
			speech.cancelSpeech()
			speech.speakText(st[0] or _("en blanco"))

		self._afterKey(gesture, speak)

	@script(gestures=("kb:leftArrow", "kb:rightArrow", "kb:home", "kb:end"))
	def script_virtualCaretCharacter(self, gesture) -> None:
		name = gesture.mainKeyName.lower()

		def speak() -> None:
			st = self._syncValue()
			text, pos = st
			if name == "leftarrow":
				pos = max(0, pos - 1)
			elif name == "rightarrow":
				pos = min(len(text), pos + 1)
			elif name == "home":
				pos = 0
			else:
				pos = len(text)
			st[1] = pos
			speech.cancelSpeech()
			if isProtected(self):
				return
			if pos >= len(text):
				speech.speakMessage(_("en blanco"))
			else:
				speech.speakCharacter(text[pos])

		self._afterKey(gesture, speak)

	@script(gestures=("kb:control+leftArrow", "kb:control+rightArrow"))
	def script_virtualCaretWord(self, gesture) -> None:
		forward = "right" in gesture.mainKeyName.lower()

		def speak() -> None:
			st = self._syncValue()
			text, pos = st
			if forward:
				_s, e = textinfo.findWordBoundaries(text, pos) if text else (0, 0)
				pos = min(len(text), max(e, pos + 1)) if pos < len(text) else len(text)
			else:
				p = max(0, pos - 1)
				while p > 0 and text[p].isspace():
					p -= 1
				s, _e = textinfo.findWordBoundaries(text, p) if text else (0, 0)
				pos = s
			st[1] = pos
			speech.cancelSpeech()
			if isProtected(self):
				return
			if pos >= len(text):
				speech.speakMessage(_("en blanco"))
				return
			s, e = textinfo.findWordBoundaries(text, pos)
			speech.speakText(text[s:e].strip() or text[pos])

		self._afterKey(gesture, speak)

	@script(gestures=("kb:backspace", "kb:shift+backspace"))
	def script_virtualBackspace(self, gesture) -> None:
		st = self._syncValue()
		text, pos = st
		deleted = text[pos - 1] if 0 < pos <= len(text) else ""
		gesture.send()
		if deleted and not isProtected(self):
			speech.cancelSpeech()
			speech.speakCharacter(deleted)
		queue_handler.callLater(40, self._syncValue)


# ====================================================================== consolas
def __getattr__(name: str):
	# ``Terminal`` vive en .terminal (que importa este módulo): carga diferida.
	if name == "Terminal":
		from .terminal import Terminal

		return Terminal
	raise AttributeError(name)


# ====================================================================== barras de progreso
#: Último porcentaje anunciado de cada barra: {clave: [último, último pitido, última voz]}.
#: Se guarda fuera del objeto porque cada evento crea un objeto nuevo.
_progressState: dict = {}


class ProgressBar(AccObject):
	def _progressKey(self):
		try:
			rid = getattr(self, "runtimeId", None)
			if rid:
				return tuple(rid)
		except Exception:
			pass
		return (self.processID, self.windowHandle, self.name)

	def _percent(self) -> int | None:
		val = self.value or ""
		try:
			return int(round(float(val.rstrip("%").replace(",", "."))))
		except ValueError:
			return None

	def event_valueChange(self) -> None:
		from .. import api
		from ..audio import tones

		mode = conf["presentation"]["progressBarOutputMode"]
		if mode == "off":
			return
		pct = self._percent()
		key = self._progressKey()
		state = _progressState.get(key)
		if state is None:
			if len(_progressState) > 64:
				_progressState.clear()
			state = _progressState[key] = [None, None, None]
		if pct is None or pct == state[0]:
			return
		state[0] = pct
		pres = conf["presentation"]
		isFocus = self == api.getFocusObject()
		if not isFocus and not conf["presentation"]["reportBackgroundProgressBars"]:
			# Solo barras del primer plano.
			fg = api.getForegroundObject()
			if fg is None or fg.processID != self.processID:
				return
		if mode in ("beep", "both") and (state[1] is None or abs(pct - state[1]) >= max(1, pres["progressBarBeepInterval"]) or pct == 100):
			state[1] = pct
			tones.beep(max(20, pres["progressBarBeepMinHz"]) * 2 ** (pct / 25.0), 40)
		if mode in ("speak", "both") and (state[2] is None or abs(pct - state[2]) >= max(1, pres["progressBarSpeechInterval"]) or pct == 100):
			state[2] = pct
			speech.speakText(f"{pct}%")


# ====================================================================== diálogos
_DIALOG_CONTAINERS = (Role.PANE, Role.GROUPING, Role.SECTION, Role.PROPERTYPAGE, Role.PANEL, Role.FILLER, Role.UNKNOWN, Role.CUSTOM)


def collectDialogText(dialog: AccObject, maxItems: int = 30, timeLimit: float = 1.0) -> str:
	"""Texto informativo de un diálogo: textos estáticos y campos de solo
	lectura que no son la etiqueta de otro control."""
	texts: list[str] = []
	deadline = time.monotonic() + timeLimit
	dialogName = dialog.name

	def collect(obj: AccObject, depth: int) -> None:
		if depth > 3 or len(texts) >= maxItems or time.monotonic() > deadline:
			return
		try:
			children = obj.children
		except Exception:
			return
		for i, child in enumerate(children):
			if len(texts) >= maxItems or time.monotonic() > deadline:
				return
			try:
				role = child.role
				states = child.states
			except Exception:
				continue
			if State.INVISIBLE in states or State.OFFSCREEN in states:
				continue
			if role == Role.STATICTEXT or (role == Role.EDITABLETEXT and State.READONLY in states and State.FOCUSABLE not in states):
				text = child.name if role == Role.STATICTEXT else (child.value or child.name)
				if not text or text == dialogName or State.FOCUSABLE in states and role == Role.STATICTEXT:
					continue
				# Una etiqueta seguida del control que nombra no se repite.
				nxt = children[i + 1] if i + 1 < len(children) else None
				if nxt is not None:
					try:
						if nxt.isFocusable and nxt.name == text:
							continue
					except Exception:
						pass
				texts.append(text)
			elif role in _DIALOG_CONTAINERS and not child.isFocusable:
				collect(child, depth + 1)

	try:
		collect(dialog, 0)
	except Exception:
		log.debug("Error obteniendo el texto del diálogo", exc_info=True)
	return " ".join(texts)


class Dialog(AccObject):
	"""Diálogos: al entrar en ellos se lee su texto informativo."""

	def _get_dialogText(self) -> str:
		if not conf["objects"]["reportDialogText"]:
			return ""
		return collectDialogText(self)


class WebDialog(Dialog):
	"""Diálogo dentro de una página web (``role=dialog`` o ``alertdialog``).

	Su texto es la descripción (``aria-describedby``) o, si no la tiene, el
	texto de los primeros elementos (con límite, porque una página puede ser
	enorme)."""

	def _get_dialogText(self) -> str:
		if not conf["objects"]["reportDialogText"]:
			return ""
		desc = self.description
		if desc:
			return ""
		return collectDialogText(self, maxItems=10, timeLimit=0.5)


# ====================================================================== listas y selección
def selectedItemNames(container: AccObject, limit: int = 500) -> list[str]:
	"""Nombres de los elementos seleccionados de una lista, árbol o tabla."""
	from ..a11y import win32ctl

	names = getattr(container, "_selectedItemNames", None)
	if callable(names):
		try:
			# Solo los primeros nombres: con Control+A en una carpeta enorme serían
			# miles de llamadas entre procesos en el hilo del núcleo.
			out = names(limit)
			if out:
				return out
		except Exception:
			log.debug("No se pudo leer la selección con el patrón Selection", exc_info=True)
	try:
		if container.windowClassName == "SysListView32" and win32ctl.listViewItemCount(container.windowHandle):
			hwnd = container.windowHandle
			return [(win32ctl.listViewItemTexts(hwnd, i, 1) or [""])[0] for i in win32ctl.listViewSelectedItems(hwnd, limit)]
	except Exception:
		log.debug("No se pudo leer la selección de la lista Win32", exc_info=True)
	sel = getattr(container, "selectedChildren", None)
	if callable(sel):
		try:
			return [o.name for o in sel()[:limit]]
		except Exception:
			log.debug("No se pudo leer accSelection", exc_info=True)
	out = []
	try:
		for child in container.children[:limit]:
			if State.SELECTED in child.states:
				out.append(child.name)
	except Exception:
		log.debug("No se pudieron recorrer los hijos seleccionados", exc_info=True)
	return out


def selectedItemCount(container: AccObject) -> int | None:
	"""Número total de elementos seleccionados si la lista lo sabe sin recorrerlos."""
	from ..a11y import win32ctl

	count = getattr(container, "_selectedItemCount", None)
	if callable(count):
		try:
			n = count()
			if n is not None:
				return n
		except Exception:
			log.debug("No se pudo contar la selección", exc_info=True)
	try:
		if container.windowClassName == "SysListView32":
			return win32ctl.listViewSelectedCount(container.windowHandle)
	except Exception:
		log.debug("No se pudo contar la selección de la lista Win32", exc_info=True)
	return None


def reportSelectedItems(container: AccObject | None) -> None:
	"""Anuncia cuántos elementos hay seleccionados y cuáles (#1839)."""
	if container is None:
		speech.speakMessage(_("No hay ninguna lista"))
		return
	names = [n for n in selectedItemNames(container) if n is not None]
	if not names:
		speech.speakMessage(_("Ningún elemento seleccionado"))
		return
	# Los nombres se leen con límite; el total, si la lista lo da, es el real.
	total = max(len(names), selectedItemCount(container) or 0)
	shown = names[:15]
	text = _("{n} seleccionados: {items}").format(n=total, items=", ".join(shown)) if total > 1 else _("Seleccionado: {item}").format(item=names[0])
	if total > len(shown):
		text += " " + _("y {n} más").format(n=total - len(shown))
	speech.speakMessage(text)


class ListContainer(AccObject):
	"""Listas, árboles y tablas: orden para leer la selección."""

	@script(
		description=_("Anuncia los elementos seleccionados de la lista"),
		category=CAT_LIST,
		gesture="kb:tiresias+control+e",
		speakOnDemand=True,
		canPropagate=True,
	)
	def script_reportSelectedItems(self, gesture) -> None:
		reportSelectedItems(self)


#: Última selección anunciada sin foco: (clave del elemento, instante).
_lastSelectionEvent: tuple = ((), 0.0)


def _isRepeatedSelection(obj) -> bool:
	"""``True`` si ``obj`` ya se anunció como seleccionado hace un momento."""
	global _lastSelectionEvent
	try:
		key = tuple(getattr(obj, "runtimeId", None) or ()) or (obj.processID, obj.windowHandle, obj.name)
	except Exception:
		return False
	now = time.monotonic()
	last, when = _lastSelectionEvent
	_lastSelectionEvent = (key, now)
	return key == last and now - when < 0.4


#: Cambios de foco: [número, instante]. Con las flechas, la selección cambia a
#: la vez que el foco y los eventos llegan en cualquier orden: lo que acompaña
#: a un cambio de foco ya lo dice el foco y no se anuncia aparte.
_focusChange = [0, 0.0]
#: Espera antes de anunciar un cambio de selección (ms): el foco que suele
#: acompañarlo llega unos milisegundos después del evento de selección.
SELECTION_SETTLE_MS = 120
#: Un cambio de selección a menos de esto de un cambio de foco es parte de él (s).
SELECTION_FOCUS_WINDOW = 0.3


#: Foco anterior y actual (para saber si una celda viene de su misma fila).
_focusHistory: list = [None, None]


def _onFocusChange(obj=None) -> None:
	_focusChange[0] += 1
	_focusChange[1] = time.monotonic()
	_focusHistory[0], _focusHistory[1] = _focusHistory[1], obj


def _sameRow(prev, row) -> bool:
	"""``prev`` es la fila ``row`` o una de sus celdas."""
	if prev is None:
		return False
	try:
		if prev == row:
			return True
		isCell = getattr(prev, "_isRowCell", None)
		return bool(isCell and isCell() and prev.parent == row)
	except Exception:
		return False


_api.post_focusChange.register(_onFocusChange)


def _focusUnchanged(seq: int):
	"""Validador de voz: el foco no ha cambiado desde ``seq``."""
	return lambda: _focusChange[0] == seq


def _focusJustChanged() -> bool:
	return time.monotonic() - _focusChange[1] < SELECTION_FOCUS_WINDOW


class SelectableItem(AccObject):
	"""Elementos de lista, árbol o tabla: cambios de selección sin mover el foco."""

	def _container(self) -> AccObject | None:
		obj = self.parent
		guard = 0
		while obj is not None and guard < 4:
			if obj.role in (Role.LIST, Role.TREEVIEW, Role.TABLE, Role.DATAGRID):
				return obj
			obj = obj.parent
			guard += 1
		return None

	def _focusIsInSameList(self) -> bool:
		from .. import api

		focus = api.getFocusObject()
		if focus is None:
			return False
		try:
			if focus.processID != self.processID:
				return False
			return focus.parent == self.parent
		except Exception:
			return False

	def event_selection(self) -> None:
		"""Un elemento pasa a ser el seleccionado sin recibir el foco."""
		from .. import api, presentation

		focus = api.getFocusObject()
		if focus is None:
			return
		if self == focus:
			# El elemento con el foco vuelve a quedar seleccionado (Control+Espacio
			# en una lista en la que no quedaba nada seleccionado). Justo después
			# de llegar el foco es la selección de las flechas: ya se ha leído.
			if conf["objects"]["reportSelectionChanges"] and not _focusJustChanged():
				queue_handler.callLater(SELECTION_SETTLE_MS, self._announceSelectionChange, True, _focusChange[0])
			return
		try:
			if focus.processID != self.processID:
				return
		except Exception:
			return
		if focus.role == Role.COMBOBOX and State.COLLAPSED in focus.states:
			# Cuadro combinado cerrado: el nuevo valor ya se anuncia con su
			# cambio de valor (los proxies Win32 mandan además varias selecciones).
			return
		isCell = getattr(focus, "_isRowCell", None)
		if isCell is not None and isCell():
			# El foco está en una celda de una fila (columnas de la vista Detalles):
			# con las flechas arriba y abajo cambia la fila seleccionada y el foco
			# pasa a la celda de la otra fila, que dice el nombre de la fila.
			return
		# Listas de sugerencias: el foco sigue en el campo de edición.
		if focus.role in (Role.EDITABLETEXT, Role.COMBOBOX, Role.DOCUMENT) and conf["objects"]["reportSuggestionItems"]:
			if _isRepeatedSelection(self):
				return
			if _recentlyAnnounced(self.name or ""):
				# El campo del cuadro combinado ya ha dicho este mismo elemento.
				return
			_noteAnnounced(self.name or "")
			speech.cancelSpeech()
			# El foco sigue en el campo, no en la sugerencia: la voz vale mientras
			# el foco no cambie (con el validador del foco se descartaría siempre).
			presentation.speakObject(self, reason=presentation.Reason.FOCUS, isValid=speech.focusValidator(focus))
			return
		if self._focusIsInSameList() and State.FOCUSED not in self.states and not _isRepeatedSelection(self):
			# La selección se mueve dentro de la lista. Con las flechas, el foco
			# llega a este mismo elemento unos milisegundos después y es el foco
			# quien lo lee: solo se anuncia aquí si el foco no se ha movido.
			queue_handler.callLater(SELECTION_SETTLE_MS, self._announceSelected, _focusChange[0])

	def _announceSelected(self, seq: int) -> None:
		"""Lee el elemento seleccionado si el foco no ha cambiado entretanto."""
		from .. import api, presentation

		if _focusChange[0] != seq:
			return
		focus = api.getFocusObject()
		if focus is None or self == focus:
			return
		presentation.speakObject(self, reason=presentation.Reason.FOCUS, isValid=_focusUnchanged(seq))

	def _reportSelectionChange(self, selected: bool) -> None:
		"""Un elemento entra o sale de la selección (``selectionAdd``/``selectionRemove``).

		Solo se anuncia lo que no acompaña a un movimiento del foco: con las
		flechas, el elemento anterior sale de la selección y el nuevo entra (en
		cualquier orden respecto al foco), y eso ya lo dice el foco. Quedan
		Control+Espacio en el elemento con el foco y los cambios en otros
		elementos (Control+clic, Mayúsculas+clic...).
		"""
		from .. import api

		if not conf["objects"]["reportSelectionChanges"]:
			return
		if _focusJustChanged():
			return
		focus = api.getFocusObject()
		if focus is None:
			return
		if self != focus and not self._focusIsInSameList():
			return
		queue_handler.callLater(SELECTION_SETTLE_MS, self._announceSelectionChange, selected, _focusChange[0])

	def _announceSelectionChange(self, selected: bool, seq: int) -> None:
		from .. import api, presentation

		if _focusChange[0] != seq:
			# El foco se ha movido: era parte de la navegación con flechas.
			return
		focus = api.getFocusObject()
		if focus is not None and self == focus:
			# Control+Espacio: se dice el estado nuevo del foco, una sola vez
			# (si su cambio de estado ya lo ha dicho, no hay nada nuevo que decir).
			presentation.speakObjectProperties(self, states=True, reason=presentation.Reason.CHANGE)
			return
		name = self.name or _("elemento")
		speech.speakMessage(_("{name} seleccionado").format(name=name) if selected else _("{name} no seleccionado").format(name=name))

	def event_selectionAdd(self) -> None:
		self._reportSelectionChange(True)

	def event_selectionRemove(self) -> None:
		self._reportSelectionChange(False)

	@script(
		description=_("Anuncia los elementos seleccionados de la lista"),
		category=CAT_LIST,
		gesture="kb:tiresias+control+e",
		speakOnDemand=True,
	)
	def script_reportSelectedItems(self, gesture) -> None:
		reportSelectedItems(self._container())


# ====================================================================== notificaciones
#: Última notificación emergente leída: (texto, instante).
_lastToast: tuple[str, float] = ("", 0.0)


def toastAlreadyReported(text: str, window: float = 2.0) -> bool:
	"""``True`` si ``text`` acaba de leerse como notificación emergente."""
	return bool(text) and text == _lastToast[0] and time.monotonic() - _lastToast[1] < window


def reportToast(obj: AccObject) -> None:
	"""Lee una notificación emergente (título y textos), sin repetirla."""
	global _lastToast
	if not conf["presentation"]["reportNotifications"]:
		return
	try:
		parts = [obj.name] if obj.name else []
		for child in obj.children[:12]:
			t = child.name
			if t and t not in parts:
				parts.append(t)
		text = " ".join(parts).strip()
	except Exception:
		text = obj.name or ""
	if not text or toastAlreadyReported(text):
		return
	_lastToast = (text, time.monotonic())
	from ..audio import tones

	tones.playSound("notification")
	origin = getattr(speech, "ORIGIN_NOTIFICATION", None)
	if origin is not None:
		speech.speak([text], origin=origin)
	else:
		speech.speakText(text)


class Toast(AccObject):
	"""Notificación emergente de Windows 10/11 (``ToastView``)."""

	def event_windowOpened(self) -> None:
		reportToast(self)

	def event_alert(self) -> None:
		reportToast(self)

	def event_tooltipOpen(self) -> None:
		reportToast(self)
