"""Microsoft Word.

Combina UI Automation (texto, cursor) con el modelo de objetos de Word para
lo que UIA no ofrece:

- comentarios con sus respuestas y su estado (NVDA #14985), notas al pie y
  al final, revisiones, y moverse entre ellos (NVDA #7538);
- posición (página, sección, línea y columna) y formato completo con sangría;
- navegación por tablas con Control+Alt+flechas y títulos de fila y columna
  fijados por el usuario;
- anuncio de cambios de página, elementos de lista (NVDA #7742) y de la
  presencia de comentarios y revisiones al moverse por líneas; al moverse por
  líneas y párrafos se anuncia la entrada en una lista («lista con N
  elementos») y la salida, y hay órdenes para ir al elemento de lista
  siguiente, anterior, primero y último (foros 3.3);
- confirmación de los atajos de formato (negrita, alineación, sangría...);
- lista de elementos: encabezados, comentarios, revisiones, notas, errores
  ortográficos y gramaticales, tablas, enlaces y marcadores.

El modelo de objetos se consulta siempre en segundo plano con tiempo máximo
(:mod:`._office`), así que Word nunca puede bloquear a Tiresias.
"""

from __future__ import annotations

from .. import presentation, review, speech, textinfo, winapi
from ..baseobject import script
from ..config import conf
from ..i18n import _
from ..log import getLogger
from ..objects.base import AccObject
from ..objects.roles import Role
from . import AppModule as BaseAppModule
from . import _chart, _headers, _office, _word

log = getLogger("winword")

CAT = _("Microsoft Word")


def _notifyCaretMoved(obj, info, unit: str) -> None:
	"""Aviso ``behaviors.post_caretMoved`` cuando Word ya ha leído la línea o el párrafo nuevo."""
	from ..objects import behaviors

	behaviors.notifyCaretMoved(obj, info, unit)


#: Atajos de formato cuyo efecto se confirma (los de Word en inglés y en español).
FORMAT_SHORTCUTS = (
	"kb:control+b",
	"kb:control+i",
	"kb:control+u",
	"kb:control+n",
	"kb:control+k",
	"kb:control+s",
	"kb:control+e",
	"kb:control+l",
	"kb:control+r",
	"kb:control+j",
	"kb:control+t",
	"kb:control+q",
	"kb:control+d",
	"kb:control+m",
	"kb:control+shift+m",
	"kb:control+shift+t",
	"kb:control+1",
	"kb:control+2",
	"kb:control+5",
	"kb:control+shift+n",
	"kb:control+alt+1",
	"kb:control+alt+2",
	"kb:control+alt+3",
)


def _repeat() -> int:
	from ..input import core as inputCore

	return inputCore.getLastScriptRepeatCount()


def _fail(error: BaseException) -> None:
	speech.speakMessage(_office.busyMessage(error))


class WordDocument(AccObject):
	"""Superposición para el documento de Word (ventana ``_WwG``)."""

	scriptCategory = CAT

	def _hwnd(self) -> int:
		return _office.windowForObject(self, "_WwG")

	def _app(self):
		return self.appModule

	# ------------------------------------------------------------ posición y formato
	@script(description=_("Anuncia la página, la sección, la línea y la columna del cursor"), category=CAT, gestures=("kb(desktop):tiresias+numpadDelete", "kb(laptop):tiresias+delete"), speakOnDemand=True)
	def script_caretPos_currentDimensions(self, gesture) -> None:
		_office.callAsync(_word.om_position, self._hwnd(), callback=lambda p: speech.speakMessage(_word.positionText(p)), onError=_fail)

	@script(description=_("Lee el formato del texto en el cursor, con sangría e interlineado (dos veces: lo muestra)"), category=CAT, gesture="kb:tiresias+f", speakOnDemand=True)
	def script_reportFormatting(self, gesture) -> None:
		show = _repeat() == 1

		def done(f: dict) -> None:
			parts = _word.formattingText(f)
			if not parts:
				speech.speakMessage(_("sin información de formato"))
			elif show:
				from .. import gui

				gui.showBrowseableMessage("\n".join(parts), _("Formato"))
			else:
				speech.speakMessage(", ".join(parts))

		_office.callAsync(_word.om_formatting, self._hwnd(), callback=done, onError=_fail)

	# ------------------------------------------------------------ comentarios y notas
	@script(description=_("Lee el comentario del cursor con sus respuestas y su estado (dos veces: lo muestra en una ventana)"), category=CAT, gesture="kb:tiresias+alt+c", speakOnDemand=True)
	def script_readComment(self, gesture) -> None:
		show = _repeat() == 1

		def done(comments: list) -> None:
			if not comments:
				speech.speakMessage(_("No hay comentarios aquí"))
				return
			texts = [_word.commentText(c, withScope=show) for c in comments]
			if show:
				from .. import gui

				gui.showBrowseableMessage("\n\n".join(texts), _("Comentarios"))
			else:
				speech.speakText(" ".join(texts))

		_office.callAsync(_word.om_commentsAtCaret, self._hwnd(), callback=done, onError=_fail, timeout=4)

	@script(description=_("Lee la nota al pie o al final más cercana al cursor"), category=CAT, gesture="kb:tiresias+alt+f", speakOnDemand=True)
	def script_readNote(self, gesture) -> None:
		def done(notes: list) -> None:
			if not notes:
				speech.speakMessage(_("No hay notas en este párrafo"))
				return
			speech.speakText(_word.noteText(notes[0]))

		_office.callAsync(_word.om_notesAtCaret, self._hwnd(), callback=done, onError=_fail)

	def _moveToItem(self, kind: str, direction: int) -> None:
		def done(item: dict | None) -> None:
			if item is None:
				if kind == "comment":
					speech.speakMessage(_("No hay más comentarios") if direction > 0 else _("No hay comentarios anteriores"))
				else:
					speech.speakMessage(_("No hay más revisiones") if direction > 0 else _("No hay revisiones anteriores"))
				return
			speech.cancelSpeech()
			text = _word.commentText(item) if kind == "comment" else _word.revisionText(item)
			speech.speakText(text)
			if item.get("line"):
				speech.speakText(item["line"])

		_office.callAsync(_word.om_findNext, self._hwnd(), kind, direction, callback=done, onError=_fail, timeout=5)

	@script(description=_("Va al comentario siguiente"), category=CAT, gesture="kb:tiresias+alt+shift+pageDown")
	def script_nextComment(self, gesture) -> None:
		self._moveToItem("comment", 1)

	@script(description=_("Va al comentario anterior"), category=CAT, gesture="kb:tiresias+alt+shift+pageUp")
	def script_previousComment(self, gesture) -> None:
		self._moveToItem("comment", -1)

	@script(description=_("Va a la revisión (control de cambios) siguiente"), category=CAT, gesture="kb:tiresias+control+shift+end")
	def script_nextRevision(self, gesture) -> None:
		self._moveToItem("revision", 1)

	@script(description=_("Va a la revisión (control de cambios) anterior"), category=CAT, gesture="kb:tiresias+control+shift+home")
	def script_previousRevision(self, gesture) -> None:
		self._moveToItem("revision", -1)

	# ------------------------------------------------------------ lista de elementos
	@script(description=_("Lista de elementos del documento: encabezados, comentarios, revisiones, notas, errores ortográficos, tablas, enlaces y marcadores"), category=CAT, gesture="kb:tiresias+f7")
	def script_elementsList(self, gesture) -> None:
		hwnd = self._hwnd()
		root = winapi.getAncestor(hwnd, winapi.GA_ROOT)
		speech.speakMessage(_("Buscando elementos..."))

		def done(elements: dict) -> None:
			from ..gui import app_dialogs

			def provider(key: str):
				return lambda: [(label, (start, end, key)) for label, start, end in elements.get(key, [])]

			def go(payload) -> None:
				start, end, key = payload
				selectEnd = end if key in ("spelling", "grammar") else None

				def onCore() -> None:
					winapi.setForegroundWindow(root)
					_office.callAsync(_word.om_moveTo, hwnd, start, selectEnd, callback=lambda line: speech.speakText(line), onError=_fail)

				from .. import queue_handler

				queue_handler.callLater(200, onCore)

			categories = [(label, provider(key)) for key, label in _word.ELEMENT_KINDS]
			first = next((i for i, (k, _l) in enumerate(_word.ELEMENT_KINDS) if elements.get(k)), 0)
			app_dialogs.showItemList("wordElements", _("Lista de elementos de Word"), categories, [app_dialogs.Action(_("&Ir"), go, default=True)], initialCategory=first)

		_office.callAsync(_word.om_elements, hwnd, callback=done, onError=_fail, timeout=20)

	@script(description=_("Recorre el gráfico seleccionado o del párrafo con las flechas (dos veces: lo muestra entero)"), category=CAT, gesture="kb:tiresias+alt+g")
	def script_chart(self, gesture) -> None:
		app = self._app()
		if app is not None:
			app.openChart(_chart.om_wordChart, self._hwnd())

	# ------------------------------------------------------------ tablas
	def _tableHeaders(self, callback) -> None:
		hwnd = self._hwnd()

		def gotKey(key) -> None:
			callback(key, _headers.get(_headers.makeKey(*key)) if key else None)

		_office.callAsync(_word.om_tableKey, hwnd, callback=gotKey, onError=_fail)

	def _tableMove(self, dRow: int, dCol: int) -> None:
		hwnd = self._hwnd()
		# Como en NVDA, lo decide «Formato de documento» (vale para todos los documentos).
		reportHeaders = conf["documentFormatting"]["reportTableHeaders"]

		def withHeaders(key, headers) -> None:
			if key is None:
				speech.speakMessage(_("No estás en una tabla"))
				return

			def moved(d: dict) -> None:
				if not d.get("inTable"):
					speech.speakMessage(_("No estás en una tabla"))
					return
				speech.cancelSpeech()
				if d.get("edge"):
					speech.speakMessage(_("Borde de la tabla"))
					return
				speech.speakText(_word.cellText(d, reportHeaders))
				self._app()._lastTable = d.get("tableStart")

			_office.callAsync(_word.om_tableMove, hwnd, dRow, dCol, headers, callback=moved, onError=_fail)

		self._tableHeaders(withHeaders)

	@script(description=_("En una tabla: celda de abajo"), category=CAT, gesture="kb:control+alt+downArrow")
	def script_nextRow(self, gesture) -> None:
		self._tableMove(1, 0)

	@script(description=_("En una tabla: celda de arriba"), category=CAT, gesture="kb:control+alt+upArrow")
	def script_previousRow(self, gesture) -> None:
		self._tableMove(-1, 0)

	@script(description=_("En una tabla: celda siguiente"), category=CAT, gesture="kb:control+alt+rightArrow")
	def script_nextColumn(self, gesture) -> None:
		self._tableMove(0, 1)

	@script(description=_("En una tabla: celda anterior"), category=CAT, gesture="kb:control+alt+leftArrow")
	def script_previousColumn(self, gesture) -> None:
		self._tableMove(0, -1)

	def _setHeader(self, kind: str) -> None:
		hwnd = self._hwnd()

		def gotKey(key) -> None:
			if key is None:
				speech.speakMessage(_("No estás en una tabla"))
				return

			def gotCell(d: dict) -> None:
				k = _headers.makeKey(*key)
				current = _headers.get(k).get(kind)
				value = d["row"] if kind == "colHeaderRow" else d["col"]
				if current == value:
					_headers.set(k, kind, None)
					speech.speakMessage(_("Títulos de columna borrados") if kind == "colHeaderRow" else _("Títulos de fila borrados"))
					return
				_headers.set(k, kind, value)
				if kind == "colHeaderRow":
					speech.speakMessage(_("La fila {n} contiene los títulos de columna").format(n=value))
				else:
					speech.speakMessage(_("La columna {n} contiene los títulos de fila").format(n=value))

			_office.callAsync(_word.om_cellInfo, hwnd, None, callback=gotCell, onError=_fail)

		_office.callAsync(_word.om_tableKey, hwnd, callback=gotKey, onError=_fail)

	@script(description=_("Usa la fila actual como títulos de columna de la tabla (otra vez: los borra)"), category=CAT, gesture="kb:tiresias+control+alt+c")
	def script_setColumnHeaders(self, gesture) -> None:
		self._setHeader("colHeaderRow")

	@script(description=_("Usa la columna actual como títulos de fila de la tabla (otra vez: los borra)"), category=CAT, gesture="kb:tiresias+control+alt+r")
	def script_setRowHeaders(self, gesture) -> None:
		self._setHeader("rowHeaderCol")

	def _readHeader(self, which: str) -> None:
		hwnd = self._hwnd()

		def withHeaders(key, headers) -> None:
			if key is None:
				speech.speakMessage(_("No estás en una tabla"))
				return

			def got(d: dict) -> None:
				text = d.get(which)
				if text:
					speech.speakText(text)
				else:
					speech.speakMessage(_("Sin título de columna") if which == "colHeader" else _("Sin título de fila"))

			_office.callAsync(_word.om_cellInfo, hwnd, headers, callback=got, onError=_fail)

		self._tableHeaders(withHeaders)

	@script(description=_("Lee el título de la columna de la celda actual"), category=CAT, gesture="kb:tiresias+control+shift+c", speakOnDemand=True)
	def script_readColumnHeader(self, gesture) -> None:
		self._readHeader("colHeader")

	@script(description=_("Lee el título de la fila de la celda actual"), category=CAT, gesture="kb:tiresias+control+shift+f", speakOnDemand=True)
	def script_readRowHeader(self, gesture) -> None:
		self._readHeader("rowHeader")

	# ------------------------------------------------------------ atajos de formato
	def script_formatShortcut(self, gesture) -> None:
		# La tecla va primero: lo que se escriba después no puede adelantarse a
		# la negrita (el formato de antes se leyó al pulsar Control).
		gesture.send()
		if not conf["officeWord"]["reportFormattingShortcuts"]:
			return
		import time

		hwnd = self._hwnd()
		sentAt = time.monotonic()

		def after(new: dict) -> None:
			old = _formatBaseline(hwnd, sentAt)
			_storeFormatBaseline(hwnd, requestedAt, new)
			if old is None:
				return
			parts = _word.formatDiff(old, new)
			if parts:
				speech.speakMessage(", ".join(parts))

		requestedAt = time.monotonic()
		_office.callAsync(_word.om_formatSnapshot, hwnd, 0.08, callback=after, timeout=1.5)

	script_formatShortcut.__doc__ = _("Confirma el efecto de los atajos de formato de Word (negrita, alineación, sangría, estilos...)")
	script_formatShortcut.category = CAT  # type: ignore[attr-defined]
	script_formatShortcut.interceptsGesture = True  # type: ignore[attr-defined]

	# ------------------------------------------------------------ moverse por líneas
	def _wantsLineExtras(self) -> bool:
		df = conf["documentFormatting"]
		return bool(df["reportLists"] or df["reportComments"] or df["reportRevisions"] or df["reportPage"] or df["reportTableHeaders"])

	def script_caret_moveByLine(self, gesture) -> None:
		if not self._wantsLineExtras():
			super().script_caret_moveByLine(gesture)  # type: ignore[misc]
			return
		old = self._getCaretInfo()  # type: ignore[attr-defined]
		oldBookmark = old.bookmark if old else None
		gesture.send()
		if old is None:
			return
		from ..objects import behaviors

		# Espera sin bloquear a que Word mueva el cursor (sondeo de EditableText).
		def moved(new, changed: bool) -> None:
			new = new if new is not None else self._getCaretInfo()  # type: ignore[attr-defined]
			if new is None:
				return
			behaviors._rememberCaret(self, new)
			# Como el ayudante base: la selección deshecha con la flecha no se
			# anuncia luego como «no seleccionado» al llegar más eventos del cursor.
			behaviors._rememberSelection(self)
			self._afterLineMove(new)

		self._startWatch(oldBookmark, moved)  # type: ignore[attr-defined]

	def _afterLineMove(self, info) -> None:
		"""Lee la línea nueva con los avisos de página, tabla, lista y comentarios."""
		review.handleCaretMove(self, info)
		app = self._app()

		def plain(error=None) -> None:
			speech.cancelSpeech()
			presentation.speakTextInfo(info, textinfo.UNIT_LINE, reason=presentation.Reason.CARET)
			_notifyCaretMoved(self, info, textinfo.UNIT_LINE)

		def done(li: dict) -> None:
			speech.cancelSpeech()
			df = conf["documentFormatting"]
			pre: list[str] = []
			if df["reportPage"] and li.get("page") and li["page"] != getattr(app, "_lastPage", None):
				if getattr(app, "_lastPage", None) is not None:
					pre.append(_("página {n}").format(n=li["page"]))
				app._lastPage = li["page"]
			tableStart = li.get("tableStart") if li.get("inTable") else None
			if tableStart != getattr(app, "_lastTable", None):
				if tableStart is not None:
					pre.append(_("tabla de {rows} filas y {cols} columnas").format(rows=li.get("rows"), cols=li.get("cols")))
				elif getattr(app, "_lastTable", None) is not None:
					pre.append(_("fuera de la tabla"))
				app._lastTable = tableStart
			if df["reportLists"]:
				pre.extend(self._listParts(li))
			if pre:
				speech.speakMessage(", ".join(pre))
			presentation.speakTextInfo(info, textinfo.UNIT_LINE, reason=presentation.Reason.CARET)
			post = _word.lineSuffix(li, df["reportComments"], df["reportRevisions"])
			if post:
				speech.speakMessage(", ".join(post))
			_notifyCaretMoved(self, info, textinfo.UNIT_LINE)

		_office.callAsync(_word.om_lineInfo, self._hwnd(), callback=done, onError=plain, timeout=0.6)

	# ------------------------------------------------------------ listas (NVDA #7742, foros 3.3)
	def _listParts(self, li: dict) -> list[str]:
		"""Entrada en una lista («lista con N elementos»), salida y prefijo del elemento."""
		app = self._app()
		parts, start = _word.listTransition(getattr(app, "_lastList", None), li)
		if app is not None:
			app._lastList = start
		return parts

	def _speakWithList(self, info, unit: str) -> None:
		"""Lee ``info`` precedido de los avisos de lista (consulta a Word sin bloquear)."""

		def plain(error=None) -> None:
			speech.cancelSpeech()
			presentation.speakTextInfo(info, unit, reason=presentation.Reason.CARET)
			_notifyCaretMoved(self, info, unit)

		def done(li: dict) -> None:
			speech.cancelSpeech()
			pre = self._listParts(li)
			if pre:
				speech.speakMessage(", ".join(pre))
			presentation.speakTextInfo(info, unit, reason=presentation.Reason.CARET)
			_notifyCaretMoved(self, info, unit)

		_office.callAsync(_word.om_listInfo, self._hwnd(), callback=done, onError=plain, timeout=0.6)

	def script_caret_moveByParagraph(self, gesture) -> None:
		if not conf["documentFormatting"]["reportLists"]:
			super().script_caret_moveByParagraph(gesture)  # type: ignore[misc]
			return
		from ..audio import tones
		from ..objects import behaviors

		info = self._getCaretInfo()  # type: ignore[attr-defined]
		if info is None:
			gesture.send()
			return
		if textinfo.paragraphStyle() == "application":
			gesture.send()

			def moved(new, changed: bool) -> None:
				new = new if new is not None else self._getCaretInfo()  # type: ignore[attr-defined]
				if new is None:
					return
				behaviors._rememberCaret(self, new)
				behaviors._rememberSelection(self)
				review.handleCaretMove(self, new)
				self._speakWithList(new, textinfo.UNIT_PARAGRAPH)

			self._startWatch(info.bookmark, moved)  # type: ignore[attr-defined]
			return
		# Estilo de párrafo propio: Tiresias mueve el cursor.
		if not info.move(textinfo.UNIT_PARAGRAPH, 1 if gesture.mainKeyName == "downarrow" else -1):
			tones.playSound("boundaryStart" if gesture.mainKeyName != "downarrow" else "boundaryEnd")
			return
		try:
			info.updateCaret()
		except Exception:
			log.debug("No se pudo mover el cursor", exc_info=True)
		behaviors._rememberCaret(self, info)
		behaviors._rememberSelection(self)
		review.handleCaretMove(self, info)
		self._speakWithList(info, textinfo.UNIT_PARAGRAPH)

	script_caret_moveByParagraph.__doc__ = _("Mueve el cursor al párrafo anterior o siguiente y lo lee, con los avisos de lista")
	script_caret_moveByParagraph.category = CAT  # type: ignore[attr-defined]

	def _moveListItem(self, where: str) -> None:
		def done(d: dict) -> None:
			speech.cancelSpeech()
			if not d.get("moved"):
				reason = d.get("reason")
				if reason == "notInList":
					speech.speakMessage(_("No estás en una lista"))
				elif reason == "none":
					speech.speakMessage(_("No hay más listas") if where == "next" else _("No hay listas anteriores"))
				elif reason == "end":
					speech.speakMessage(_("Fin de la lista"))
				else:
					speech.speakMessage(_("Principio de la lista"))
				return
			app = self._app()
			parts, start = _word.listTransition(getattr(app, "_lastList", None), d)
			if app is not None:
				app._lastList = start
			# El prefijo ya va en el texto del elemento.
			intro = [p for p in parts if p != _word.listPrefix(d)]
			text = _word.listItemText(d)
			speech.speakText(", ".join(intro + [text]))

		_office.callAsync(_word.om_listItemMove, self._hwnd(), where, callback=done, onError=_fail, timeout=4)

	@script(description=_("Va al siguiente elemento de la lista (fuera de una lista, a la siguiente lista)"), category=CAT, gesture="kb:tiresias+control+alt+shift+downArrow")
	def script_nextListItem(self, gesture) -> None:
		self._moveListItem("next")

	@script(description=_("Va al elemento anterior de la lista (fuera de una lista, a la lista anterior)"), category=CAT, gesture="kb:tiresias+control+alt+shift+upArrow")
	def script_previousListItem(self, gesture) -> None:
		self._moveListItem("previous")

	@script(description=_("Va al primer elemento de la lista"), category=CAT, gesture="kb:tiresias+control+alt+home")
	def script_firstListItem(self, gesture) -> None:
		self._moveListItem("first")

	@script(description=_("Va al último elemento de la lista"), category=CAT, gesture="kb:tiresias+control+alt+end")
	def script_lastListItem(self, gesture) -> None:
		self._moveListItem("last")

	def event_gainFocus(self) -> None:
		super().event_gainFocus()  # type: ignore[misc]
		app = self._app()
		if app is not None:
			app._lastPage = None
			app._lastTable = None
			app._lastList = None


# Los atajos de formato comparten una orden; se añaden a la tabla de gestos de la clase.
for _g in FORMAT_SHORTCUTS:
	from ..baseobject import normalizeGestureId as _norm

	WordDocument._classGestures[_norm(_g)] = "formatShortcut"  # type: ignore[attr-defined]

# Formato de antes de un atajo: se lee al pulsar Control, antes de que llegue
# la letra (así la tecla se envía sin esperar a Word). {hwnd: (pedida, instantánea)}
_formatBaselines: dict[int, tuple[float, dict]] = {}
#: Una instantánea más antigua que esto (s) ya no sirve de referencia.
FORMAT_BASELINE_MAX_AGE = 10.0


def _storeFormatBaseline(hwnd: int, requestedAt: float, snap: dict) -> None:
	prev = _formatBaselines.get(hwnd)
	if snap and (prev is None or prev[0] <= requestedAt):
		_formatBaselines[hwnd] = (requestedAt, snap)


def _formatBaseline(hwnd: int, sentAt: float) -> dict | None:
	"""Instantánea pedida antes de enviar el atajo (y reciente), o ``None``."""
	entry = _formatBaselines.get(hwnd)
	if entry is None or entry[0] > sentAt or sentAt - entry[0] > FORMAT_BASELINE_MAX_AGE:
		return None
	return entry[1]


def _onModifierDown(name: str) -> None:
	"""Hilo del núcleo: Control pulsado en un documento de Word."""
	if name != "control" or not conf["officeWord"]["reportFormattingShortcuts"]:
		return
	from .. import api

	focus = api.getFocusObject()
	if not isinstance(focus, WordDocument):
		return
	import time

	hwnd = focus._hwnd()
	requestedAt = time.monotonic()
	_office.callAsync(_word.om_formatSnapshot, hwnd, callback=lambda snap: _storeFormatBaseline(hwnd, requestedAt, snap), timeout=0.4)


try:
	from ..input import core as _inputCore

	_inputCore.post_modifierDown.register(_onModifierDown)
except Exception:
	log.debug("No se pudo registrar la lectura previa del formato", exc_info=True)


def useWordDocument(clsList: list[type]) -> None:
	"""Añade :class:`WordDocument` y trata el documento como editable.

	El UIA de Word no publica el patrón de valor, así que el documento parecería
	de solo lectura y se perdería el eco de Retroceso y Suprimir.
	"""
	from ..objects import behaviors

	for i, cls in enumerate(clsList):
		if cls is behaviors.ReadOnlyDocument:
			clsList[i] = behaviors.EditableTextWithCaret
	clsList.insert(0, WordDocument)


def isWordDocument(obj) -> bool:
	try:
		return obj.windowClassName == "_WwG" and obj.role in (Role.DOCUMENT, Role.EDITABLETEXT)
	except Exception:
		return False


class AppModule(_chart.ChartNavigationMixin, BaseAppModule):
	def __init__(self, processID: int, appName: str | None = None) -> None:
		super().__init__(processID, appName)
		self._lastPage = None
		self._lastTable = None
		#: Inicio de la lista del cursor (para anunciar la entrada y la salida, #7742).
		self._lastList = None

	def chooseObjectClass(self, obj, clsList: list[type]) -> None:
		if isWordDocument(obj):
			useWordDocument(clsList)
