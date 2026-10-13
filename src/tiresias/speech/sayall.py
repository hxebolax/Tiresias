"""Lectura continua («leer todo») desde el cursor del sistema o de revisión.

- **Unidad** (``speech/sayAllUnit``): por líneas, por frases o por párrafos
  (foros 2.1). El cursor avanza con la unidad leída.
- **Sin pausas** (``speech/sayAllWithoutPauses``): las líneas que no acaban
  una frase se unen a la siguiente para que el sintetizador no haga una
  pausa en cada salto de línea; el cursor se actualiza en los finales de
  frase.
- **Mayúsculas** (``speech/capitalsInSayAll``, #3286): indica las palabras
  que empiezan por mayúscula o están en mayúsculas.
- **Cambio de idioma** también fuera del modo exploración (idioma del texto
  del documento).
- **Leer todo en tablas**: lee una fila (hacia la derecha) o una columna
  (hacia abajo) desde la celda actual del modo exploración.
- **Reanudación tras hojear**: :func:`resume` sigue con el mismo cursor con
  el que se empezó (sistema, revisión o tabla).
- **Navegación sin detener la lectura**: :func:`skip` salta frases o
  párrafos y :func:`restart` vuelve a empezar en la línea actual (tras
  cambiar la velocidad, por ejemplo).
- **Velocidad de la lectura continua** (``speech/sayAllRateMode``, foros
  2.1): :func:`changeRate` (Re Pág y Av Pág durante la lectura) cambia una
  velocidad propia de la lectura continua (``sayAllRateOffset``, se
  recuerda), solo la de la lectura en curso (vuelve a la normal al acabar) o
  la de la voz (modo ``global``). Las dos primeras no tocan los ajustes del
  sintetizador: se aplican con ``RateCommand`` en lo que se envía, así que
  los perfiles con disparador «lectura continua» siguen funcionando igual.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from .. import api, queue_handler, textinfo
from ..config import conf
from ..i18n import _
from ..log import getLogger
from . import api as speech
from .commands import CallbackCommand, LangChangeCommand, RateCommand

log = getLogger("sayAll")

CURSOR_CARET = "caret"
CURSOR_REVIEW = "review"
CURSOR_TABLE = "table"

#: Unidades que se adelantan al sintetizador.
LOOKAHEAD = 4
#: Límite de líneas y caracteres que se unen en modo «sin pausas».
MERGE_MAX_LINES = 12
MERGE_MAX_CHARS = 900

_sentenceEnd = re.compile(r"[.!?…:;][\"'»”’)\]]*\s*$")


#: Unidades de lectura (opción ``speech/sayAllUnit``).
UNITS = {"line": textinfo.UNIT_LINE, "sentence": textinfo.UNIT_SENTENCE, "paragraph": textinfo.UNIT_PARAGRAPH}
#: Límite del cambio de velocidad propio de la lectura continua (puntos).
RATE_OFFSET_LIMIT = 100

#: Cambio de velocidad de la lectura en curso (modo ``temporary``).
_sessionRateOffset = 0


def rateOffset() -> int:
	"""Puntos que se suman a la velocidad de la voz durante la lectura continua."""
	try:
		base = int(conf["speech"]["sayAllRateOffset"])
	except (TypeError, ValueError):
		base = 0
	if conf["speech"]["sayAllRateMode"] == "temporary":
		return base + _sessionRateOffset
	return base


def withRate(seq: list, offset: int | None = None) -> list:
	"""Aplica a ``seq`` la velocidad propia de la lectura continua.

	Los cambios de velocidad que ya lleve la secuencia (esquemas de voz) se
	desplazan también, para que al volver a «normal» se vuelva a la velocidad
	de la lectura continua y no a la de la voz.
	"""
	if offset is None:
		offset = rateOffset()
	if not offset:
		return seq
	out: list = [RateCommand(offset=offset)]
	for item in seq:
		if isinstance(item, RateCommand):
			out.append(RateCommand(offset=item.offset + offset, multiplier=item.multiplier))
		else:
			out.append(item)
	return out


_lineBreaks = re.compile(r"\s*[\r\n]+\s*")


def _joinLines(seq: list) -> list:
	"""Quita los saltos de línea internos de un párrafo (evita pausas)."""
	out: list = []
	for item in seq:
		if isinstance(item, str) and ("\n" in item or "\r" in item):
			item = _lineBreaks.sub(" ", item)
		out.append(item)
	return out


def _endsSentence(seq: list) -> bool:
	for item in reversed(seq):
		if isinstance(item, str):
			if not item.strip():
				continue
			return bool(_sentenceEnd.search(item))
	return True


def _seqLength(seq: list) -> int:
	return sum(len(i) for i in seq if isinstance(i, str))


def mergeWithoutPauses(lines: list[tuple[Callable[[], None], list]]) -> list:
	"""Une varias líneas en una sola secuencia sin cortes a mitad de frase.

	``lines`` es una lista de ``(llamada, secuencia)``. La llamada de la
	primera línea va al principio; las de las demás se aplazan hasta el
	siguiente final de frase (o el final), de forma que los índices del
	sintetizador solo caen entre frases.
	"""
	out: list = []
	deferred: list[Callable[[], None]] = []
	for i, (callback, seq) in enumerate(lines):
		if i == 0:
			out.append(CallbackCommand(callback))
		else:
			deferred.append(callback)
		for item in seq:
			if isinstance(item, str):
				if out and isinstance(out[-1], str):
					out[-1] = f"{out[-1].rstrip()} {item.lstrip()}"
				else:
					out.append(item)
				if deferred and _sentenceEnd.search(item):
					out.extend(CallbackCommand(cb) for cb in deferred)
					deferred = []
			else:
				out.append(item)
	out.extend(CallbackCommand(cb) for cb in deferred)
	return out


def _capitalize(seq: list) -> list:
	mode = conf["speech"]["capitalsInSayAll"]
	if mode == "off":
		return seq
	out: list = []
	for item in seq:
		if isinstance(item, str):
			out.extend(speech.capitalizedTextSequence(item, mode))
		else:
			out.append(item)
	return out


class _Reader:
	def __init__(self, info: textinfo.TextInfo, cursor: str) -> None:
		self.cursor = cursor
		self.reader = info.copy()
		self.reader.collapse()
		#: Donde empezó la lectura (para reanudar si aún no se ha alcanzado ninguna unidad).
		self.startPosition = self.reader.copy()
		self.unit = UNITS.get(conf["speech"]["sayAllUnit"], textinfo.UNIT_LINE)
		self.withoutPauses = bool(conf["speech"]["sayAllWithoutPauses"]) and self.unit == textinfo.UNIT_LINE
		#: Por párrafos y sin pausas: los saltos de línea dentro del párrafo no paran la voz.
		self.joinLines = bool(conf["speech"]["sayAllWithoutPauses"]) and self.unit == textinfo.UNIT_PARAGRAPH
		self.queued = 0
		self.finished = False
		self.active = True
		#: Inicio de la última unidad alcanzada por la voz.
		self.lastPosition: textinfo.TextInfo | None = None

	def start(self) -> None:
		for _i in range(LOOKAHEAD):
			if not self._queueNext():
				break

	def _unitSequence(self, unitInfo: textinfo.TextInfo) -> list:
		doc = getattr(unitInfo, "doc", None)
		if doc is not None:
			s, e = unitInfo.offsets  # type: ignore[attr-defined]
			return doc.compactSpeech(doc.getRangeSpeech(s, e))
		text = unitInfo.text
		if not text.strip():
			return []
		from ..presentation import _languageOf

		lang = _languageOf(unitInfo)
		if lang:
			return [LangChangeCommand(lang), text, LangChangeCommand(None)]
		return [text]

	def _readUnit(self) -> tuple[textinfo.TextInfo, list] | None:
		"""Lee la unidad siguiente y avanza. ``None`` si no hay más."""
		if self.finished:
			return None
		unitInfo = self.reader.copy()
		try:
			unitInfo.expand(self.unit)
		except Exception:
			self.finished = True
			return None
		prev = getattr(self, "_prevUnit", None)
		try:
			if prev is not None and unitInfo.compareEndPoints(prev, "startToStart") <= 0:
				# Tras la última línea algunos proveedores (campos Win32) dejan el
				# cursor al final y expanden hacia atrás: se repetiría la línea.
				self.finished = True
				return None
		except Exception:
			pass
		self._prevUnit = unitInfo.copy()
		seq = self._unitSequence(unitInfo)
		if self.joinLines:
			seq = _joinLines(seq)
		moved = 0
		try:
			moved = self.reader.move(self.unit, 1)
		except Exception:
			moved = 0
		if not moved or self.reader.compareEndPoints(unitInfo, "startToStart") <= 0:
			self.finished = True
		return unitInfo, seq

	def _makeCallback(self, unitInfo: textinfo.TextInfo) -> Callable[[], None]:
		bookmarkInfo = unitInfo.copy()
		bookmarkInfo.collapse()

		def onUnitStart(info=bookmarkInfo) -> None:
			if not self.active:
				return
			self.lastPosition = info
			self._updateCursor(info)
			self.queued -= 1
			self._queueNext()

		return onUnitStart

	def _queueNext(self) -> bool:
		if not self.active or self.finished:
			return False
		lines: list[tuple[Callable[[], None], list]] = []
		chars = 0
		while True:
			res = self._readUnit()
			if res is None:
				break
			unitInfo, seq = res
			lines.append((self._makeCallback(unitInfo), _capitalize(seq)))
			chars += _seqLength(seq)
			if not self.withoutPauses or self.finished:
				break
			# Sin pausas: se sigue mientras la línea no acabe una frase.
			if not seq or _endsSentence(seq) or len(lines) >= MERGE_MAX_LINES or chars >= MERGE_MAX_CHARS:
				break
		if not lines:
			self.finished = True
			speech.speak([CallbackCommand(self._onEnd)], origin=speech.ORIGIN_SAYALL)
			return False
		self.queued += len(lines)
		speechSeq = mergeWithoutPauses(lines)
		if self.finished:
			speechSeq.append(CallbackCommand(self._onEnd))
		speech.speak(withRate(speechSeq), origin=speech.ORIGIN_SAYALL)
		return not self.finished

	def _updateCursor(self, info: textinfo.TextInfo) -> None:
		try:
			if self.cursor == CURSOR_CARET:
				info.updateCaret()
				if conf["reviewCursor"]["followCaret"]:
					api.setReviewPosition(info, isCaret=True)
			else:
				api.setReviewPosition(info)
		except Exception:
			log.debug("No se pudo actualizar el cursor en lectura continua", exc_info=True)
		# Braille sigue a la lectura continua (opción «followSayAll»).
		try:
			from .. import braille

			braille.handler.handleSayAllLine(info, self.cursor == CURSOR_CARET)
		except Exception:
			log.debug("No se pudo mostrar la línea en braille", exc_info=True)

	def _onEnd(self) -> None:
		stop(finished=True)


class _ItemsReader:
	"""Lee una lista fija de elementos (celdas de una tabla)."""

	def __init__(self, items: list[tuple[Callable[[], None], list]], cursor: str = CURSOR_TABLE) -> None:
		self.items = list(items)
		self.cursor = cursor
		self.index = 0
		self.active = True
		self.finished = False
		self.lastPosition = None

	def start(self) -> None:
		for _i in range(LOOKAHEAD):
			if not self._queueNext():
				break

	def _queueNext(self) -> bool:
		if not self.active or self.index >= len(self.items):
			return False
		action, seq = self.items[self.index]
		self.index += 1
		last = self.index >= len(self.items)

		def onStart(action=action) -> None:
			if not self.active:
				return
			try:
				action()
			except Exception:
				log.debug("Error moviendo el cursor de la tabla", exc_info=True)
			self._queueNext()

		out: list = [CallbackCommand(onStart)] + _capitalize(seq)
		if last:
			self.finished = True
			out.append(CallbackCommand(lambda: stop(finished=True)))
		speech.speak(withRate(out), origin=speech.ORIGIN_SAYALL)
		return not last


_reader: Any = None
#: Cursor de la última lectura continua (para reanudar tras hojear).
_lastCursor = CURSOR_CARET
_lastTableDirection: tuple[int, int] = (1, 0)
#: La lectura se empezó con una orden en el modo de voz «a demanda»: como en
#: NVDA, sigue hablando hasta el final (también al saltar, reanudar o cambiar
#: la velocidad).
_onDemand = False


def isRunning() -> bool:
	return _reader is not None and _reader.active


def startedOnDemand() -> bool:
	"""``True`` si la lectura en curso puede hablar en el modo «a demanda»."""
	return _onDemand and isRunning()


def _beginReading(keep: bool) -> None:
	"""Anota si la lectura que empieza puede hablar en el modo «a demanda»."""
	global _onDemand
	_onDemand = bool(speech._onDemandAllowed) or (keep and _onDemand)


def _checkStarted(reader: Any) -> None:
	"""Si la voz no ha encolado nada (voz desactivada, en pitidos, a demanda o
	en espera), la lectura no se queda «en marcha» sin avanzar: se detiene
	(si no, las teclas de navegación de la lectura continua seguirían
	capturadas)."""
	if _reader is reader and reader.active and not speech.isSpeaking():
		stop()


def currentCursor() -> str:
	return _reader.cursor if _reader is not None else _lastCursor


def _startInfo(cursor: str) -> textinfo.TextInfo | None:
	try:
		if cursor == CURSOR_CARET:
			obj = api.getCaretObject()
			if obj is not None:
				return obj.makeTextInfo(textinfo.POSITION_CARET)
			return None
		return api.getReviewPosition()
	except Exception:
		log.debug("No hay texto para leer", exc_info=True)
		return None


def readText(cursor: str = CURSOR_CARET, info: textinfo.TextInfo | None = None, keepRate: bool = False) -> None:
	"""Empieza a leer. ``keepRate`` conserva el cambio de velocidad de la
	lectura en curso (al saltar, al reanudar o tras cambiar la velocidad)."""
	global _reader, _lastCursor, _sessionRateOffset
	stop()
	if not keepRate:
		_sessionRateOffset = 0
	if cursor == CURSOR_TABLE:
		readTable(*_lastTableDirection, keepRate=keepRate)
		return
	if info is None:
		info = _startInfo(cursor)
	if info is None:
		return
	speech.cancelSpeech()
	_beginReading(keepRate)
	conf.enterTrigger("sayAll")
	_lastCursor = cursor
	reader = _reader = _Reader(info, cursor)
	reader.start()
	_checkStarted(reader)


def resume() -> None:
	"""Reanuda la lectura continua con el mismo cursor (tras hojear)."""
	readText(_lastCursor, keepRate=True)


def restart() -> None:
	"""Vuelve a empezar desde la unidad que se estaba leyendo."""
	r = _reader
	if r is None or not r.active:
		return
	if isinstance(r, _Reader):
		pos = r.lastPosition or r.startPosition
		cursor = r.cursor
		readText(cursor, pos.copy() if pos is not None else None, keepRate=True)
	elif isinstance(r, _ItemsReader):
		remaining = r.items[max(0, r.index - LOOKAHEAD) :]
		_startItems(remaining, keep=True)


def changeRate(direction: int) -> int | None:
	"""Sube (1) o baja (-1) la velocidad durante la lectura continua (foros 2.1).

	Según ``speech/sayAllRateMode`` cambia la velocidad propia de la lectura
	continua, solo la de esta lectura o la de la voz. Devuelve el cambio
	resultante (puntos sobre la voz; ``None`` en modo global o sin cambio).
	"""
	global _sessionRateOffset
	from .. import synth

	s = synth.getSynth()
	if s is None or not s.isSupported("rate"):
		return None
	sp = conf["speech"]
	try:
		step = int(sp["sayAllRateStep"]) or 5
	except (TypeError, ValueError):
		step = 5
	mode = sp["sayAllRateMode"]
	if mode == "global":
		synth.changeSetting("rate", int(s.getSetting("rate") or 0) + direction * step)
		restart()
		return None
	cur = rateOffset()
	new = max(-RATE_OFFSET_LIMIT, min(RATE_OFFSET_LIMIT, cur + direction * step))
	if new == cur:
		from ..audio import tones

		tones.playSound("boundary")
		return None
	if mode == "temporary":
		_sessionRateOffset += new - cur
	else:
		sp["sayAllRateOffset"] = new
	# Se reanuda desde la unidad actual para que el cambio se oiga ya.
	restart()
	return new


def skip(unit: str, direction: int) -> bool:
	"""Salta ``direction`` unidades desde lo que se está leyendo y sigue leyendo."""
	r = _reader
	if not isinstance(r, _Reader) or not r.active:
		return False
	# Desde la unidad que se está leyendo (``r.reader`` va adelantado
	# LOOKAHEAD unidades); si aún no se ha alcanzado ninguna, desde el inicio.
	pos = (r.lastPosition or r.startPosition).copy()
	try:
		moved = pos.move(unit, direction)
	except Exception:
		moved = 0
	if not moved:
		from ..audio import tones

		tones.playSound("boundary")
		return False
	readText(r.cursor, pos, keepRate=True)
	return True


def _startItems(items: list, keep: bool = False) -> None:
	global _reader, _lastCursor
	stop()
	if not items:
		return
	speech.cancelSpeech()
	_beginReading(keep)
	conf.enterTrigger("sayAll")
	_lastCursor = CURSOR_TABLE
	reader = _reader = _ItemsReader(items)
	reader.start()
	_checkStarted(reader)


def tableItems(doc: Any, dRow: int, dCol: int) -> list[tuple[Callable[[], None], list]] | None:
	"""Celdas desde la actual en la dirección indicada (``None`` si no hay tabla)."""
	cur = doc._currentCell() if hasattr(doc, "_currentCell") else None
	if cur is None:
		return None
	table, cell = cur
	cells = doc.buffer.tables.get(id(table), {})
	row, col = cell.rowCol
	headers = conf["documentFormatting"]["reportTableHeaders"]
	coords = conf["documentFormatting"]["reportTableCellCoords"]
	items: list = []
	while (row, col) in cells:
		target = cells[(row, col)]
		parts: list[str] = []
		if headers:
			if dRow and col != 1:
				h = cells.get((row, 1))
				if h is not None and h.role.name == "TABLEROWHEADER":
					parts.append(doc.buffer.text[h.start : h.end].strip())
			if dCol and row != 1:
				h = cells.get((1, col))
				if h is not None:
					parts.append(doc.buffer.text[h.start : h.end].strip())
		if coords:
			parts.append(_("fila {n}").format(n=row) if dRow else _("columna {n}").format(n=col))
		seq = doc.compactSpeech(doc.getRangeSpeech(target.start, target.end))
		if not any(isinstance(i, str) and i.strip() for i in seq):
			seq = [_("en blanco")]
		start = target.start

		def move(doc=doc, start=start, target=target) -> None:
			doc.caret = start
			try:
				doc._afterCaretMove(target)
			except Exception:
				pass

		items.append((move, [" ".join(p for p in parts if p)] + seq if any(parts) else seq))
		row += dRow
		col += dCol
	return items


def readTable(dRow: int, dCol: int, keepRate: bool = False) -> bool:
	"""Lee la columna (``dRow=1``) o la fila (``dCol=1``) desde la celda actual."""
	global _lastTableDirection, _sessionRateOffset
	doc = _browseDocument()
	items = tableItems(doc, dRow, dCol) if doc is not None else None
	if not items:
		speech.speakMessage(_("no está en una tabla"))
		return False
	_lastTableDirection = (dRow, dCol)
	if not keepRate:
		_sessionRateOffset = 0
	_startItems(items, keep=keepRate)
	return True


def _browseDocument() -> Any:
	focus = api.getFocusObject()
	ti = getattr(focus, "treeInterceptor", None) if focus is not None else None
	if ti is not None and hasattr(ti, "buffer") and not getattr(ti, "passThrough", False):
		return ti
	return None


def readObjects(obj: Any) -> None:
	"""Lee todos los objetos de una ventana (Tiresias+B)."""
	from .. import presentation

	parts: list[str] = []

	def walk(o: Any, depth: int) -> None:
		if depth > 12 or len(parts) > 400:
			return
		for child in o.children:
			try:
				if child.presentationType == "content":
					s = " ".join(presentation.getObjectSpeech(child, presentation.Reason.SAYALL))
					if s:
						parts.append(s)
				walk(child, depth + 1)
			except Exception:
				continue

	walk(obj, 0)
	speech.speak(withRate(["\n".join(parts)]) if parts else [], origin=speech.ORIGIN_SAYALL)


def stop(finished: bool = False) -> None:
	global _reader
	if _reader is None:
		return
	_reader.active = False
	_reader = None
	conf.exitTrigger("sayAll")


def _onCancel() -> None:
	r = _reader
	if r is not None and r.active:
		r.active = False
		# Se detiene solo esta lectura: si antes de que se ejecute la tarea
		# encolada empieza otra (volver a pulsar «leer todo», reanudar tras
		# hojear), la nueva sigue.
		queue_handler.queueFunction(_stopReader, r)


def _stopReader(reader: Any) -> None:
	if _reader is reader:
		stop()


speech.pre_speechCanceled.register(_onCancel)
