"""Órdenes y eventos de las funciones de productividad (complemento incorporado).

Categorías: «Analizador de texto», «Notificaciones», «Vigilancia»,
«Búsqueda en ventanas», «Marcadores de texto» y «Programas externos».
"""

from __future__ import annotations

import time

from .. import api, queue_handler, speech
from ..baseobject import script
from ..config import conf
from ..i18n import _, ngettext
from ..input import core as inputCore
from ..log import getLogger
from ..plugins import GlobalPlugin
from . import text_analyzer, text_context
from .notifications import ACTION_BRAILLE, ACTION_SILENCE, ACTION_SPEAK, PRIORITY_HIGH, SOURCE_LIVEREGION, SOURCE_NOTIFICATION, SOURCE_TOAST, Entry

log = getLogger("productivity")

CAT_ANALYZER = _("Analizador de texto")
CAT_NOTIFICATIONS = _("Notificaciones")
CAT_WATCH = _("Vigilancia")
CAT_FIND = _("Búsqueda en ventanas")
CAT_BOOKMARKS = _("Marcadores de texto")
CAT_CONTROLLER = _("Programas externos")

#: Órdenes del modo exploración que mueven el cursor por líneas (para el aviso
#: del analizador). Mueven el cursor y leen la línea sin esperar, así que al
#: terminar la orden (``post_scriptExecuted``) el cursor ya está en la línea nueva.
#: Las de los campos de edición (flechas, Control+flechas, Control+Inicio...)
#: esperan a que la aplicación mueva el cursor: avisan con
#: ``behaviors.post_caretMoved`` después de leer la línea nueva.
LINE_SCRIPTS = {
	"script_nextLine",
	"script_previousLine",
	"script_nextParagraph",
	"script_previousParagraph",
}
#: Unidades leídas tras mover el cursor que cuentan como «pasar por una línea».
LINE_UNITS = ("line", "paragraph")


def _pkg():
	from .. import productivity

	return productivity


def _repeat() -> int:
	return inputCore.getLastScriptRepeatCount()


# ------------------------------------------------------------------ analizador
_analysisCache: tuple | None = None


def analyzerChecks() -> dict:
	c = conf["textAnalyzer"]
	return {k: bool(c[k]) for k in text_analyzer.DEFAULT_CHECKS}


def analyzeContext(ctx: text_context.TextContext) -> list[text_analyzer.Issue]:
	"""Incidencias de todo el texto del contexto (con caché)."""
	global _analysisCache
	checks = analyzerChecks()
	sig = (ctx.key, len(ctx.text), hash(ctx.text), tuple(sorted(checks.items())))
	if _analysisCache is not None and _analysisCache[0] == sig:
		return _analysisCache[1]
	issues = text_analyzer.analyze(ctx.text, checks)
	if checks.get("format") and ctx.kind == "edit":
		try:
			runs = ctx.formatRuns()
			if runs:
				issues = sorted(issues + text_analyzer.formatIssues(ctx.text, runs))
		except Exception:
			log.debug("No se pudo analizar el formato", exc_info=True)
	_analysisCache = (sig, issues)
	return issues


def _lineIssuesAtCaret(obj=None) -> tuple[list[text_analyzer.Issue], str] | None:
	"""Incidencias de la línea del cursor analizando solo su párrafo (rápido).

	``obj``: objeto cuyo cursor se analiza (por defecto, el del foco)."""
	from .. import textinfo

	checks = analyzerChecks()
	checks["format"] = False
	caretObj = api.getCaretObject() if obj is None else obj
	focus = api.getFocusObject() if obj is None else obj
	if caretObj is not None and caretObj is not focus and getattr(caretObj, "buffer", None) is not None:
		text = caretObj.buffer.text
		caret = caretObj.caret
		ctx = text_context.TextContext(None, text, caret, "", "")
		pStart, pEnd = _paragraphBounds(text, caret)
		lStart, lEnd = ctx.lineBounds(caret)
		issues = text_analyzer.analyze(text[pStart:pEnd], checks)
		rel = [i for i in issues if lStart - pStart <= i.start < max(lEnd - pStart, lStart - pStart + 1)]
		return rel, text[lStart:lEnd]
	if not text_context.isTextObject(focus):
		return None
	try:
		caretInfo = focus.makeTextInfo(textinfo.POSITION_CARET)
		para = caretInfo.copy()
		para.expand(textinfo.UNIT_PARAGRAPH)
		line = caretInfo.copy()
		line.expand(textinfo.UNIT_LINE)
		before = para.copy()
		before.setEndPoint(line, "endToStart")
		paraText = para.text or ""
		lineText = line.text or ""
		lStart = len(before.text or "")
	except Exception:
		return None
	issues = text_analyzer.analyze(paraText, checks)
	lEnd = lStart + len(lineText)
	rel = [i for i in issues if lStart <= i.start < max(lEnd, lStart + 1)]
	return rel, lineText


def _paragraphBounds(text: str, offset: int) -> tuple[int, int]:
	import re

	start = 0
	for m in re.finditer(r"\n[ \t\r]*\n", text[:offset]):
		start = m.end()
	m = re.search(r"\n[ \t\r]*\n", text[offset:])
	end = offset + m.start() if m else len(text)
	return start, end


def _onScriptExecuted(script=None, gesture=None) -> None:
	name = getattr(script, "__name__", "")
	if name not in LINE_SCRIPTS:
		return
	_reportLineIssues()


def _onCaretMoved(obj=None, info=None, unit: str = "") -> None:
	"""``behaviors.post_caretMoved``: el cursor ya está en la línea nueva y se ha pedido leerla."""
	if unit not in LINE_UNITS:
		return
	_reportLineIssues(obj)


def _reportLineIssues(obj=None) -> None:
	"""Sonido y descripción de las incoherencias de la línea del cursor, detrás de su lectura."""
	c = conf["textAnalyzer"]
	if not (c["lineSound"] or c["lineSpeak"]):
		return
	try:
		res = _lineIssuesAtCaret(obj)
	except Exception:
		log.debug("Error analizando la línea", exc_info=True)
		return
	if not res or not res[0]:
		return
	issues = res[0]
	from ..audio import tones
	from ..speech import api as speechApi
	from ..speech.commands import WaveFileCommand

	if speechApi.getSpeechMode() == speechApi.SpeechMode.talk:
		# En la cola de voz, detrás de la línea que se acaba de pedir leer: el
		# sonido suena y la descripción se dice cuando termina la línea (sin
		# cortarla ni quedar cortados por ella).
		seq: list = []
		if c["lineSound"]:
			seq.append(WaveFileCommand("textIssue"))
		if c["lineSpeak"]:
			seq.append(text_analyzer.describe(issues))
		speech.speak(seq)
		return
	# Voz desactivada o en pitidos: el sonido se oye igualmente.
	if c["lineSound"]:
		tones.playSound("textIssue")
	if c["lineSpeak"]:
		speech.speak([text_analyzer.describe(issues)])


# ------------------------------------------------------------------ notificaciones
def _toastText(obj) -> str:
	try:
		texts = [c.name for c in obj.children if c.name] if not obj.name or len(obj.name) < 3 else []
		return " ".join([obj.name or ""] + texts).strip()
	except Exception:
		return obj.name or ""


def handleNotification(source: str, obj, text: str, nextHandler) -> None:
	"""Guarda el aviso y aplica las reglas (hilo del núcleo)."""
	pkg = _pkg()
	store = pkg.notificationStore
	text = (text or "").strip()
	if store is None or not text:
		nextHandler()
		return
	c = conf["notifications"]
	app = text_context.appNameOf(obj)
	rule = store.findRule(app, text, source) if c["applyRules"] else None
	action = rule.action if rule else ACTION_SPEAK
	wanted = {SOURCE_NOTIFICATION: "recordNotifications", SOURCE_TOAST: "recordToasts", SOURCE_LIVEREGION: "recordLiveRegions"}
	if c["keepHistory"] and c[wanted[source]]:
		store.setMaxEntries(c["historySize"])
		store.add(Entry(time.time(), app, source, text, action, rule.name if rule else ""))
	if rule is None:
		nextHandler()
		return
	if rule.sound:
		from ..audio import tones

		tones.playSound(rule.sound)
	if action == ACTION_SILENCE:
		return
	if action == ACTION_BRAILLE:
		try:
			from .. import braille

			braille.handler.message(text)
		except Exception:
			log.debug("No se pudo mostrar en braille", exc_info=True)
		return
	if rule.priority == PRIORITY_HIGH:
		speech.cancelSpeech()
	nextHandler()


# ------------------------------------------------------------------ complemento
class ProductivityGlobalPlugin(GlobalPlugin):
	def __init__(self) -> None:
		super().__init__()
		from ..objects import behaviors

		inputCore.post_scriptExecuted.register(_onScriptExecuted)
		behaviors.post_caretMoved.register(_onCaretMoved)

	def terminate(self) -> None:
		from ..objects import behaviors

		inputCore.post_scriptExecuted.unregister(_onScriptExecuted)
		behaviors.post_caretMoved.unregister(_onCaretMoved)

	# --------------------------------------------------- eventos
	def event_notification(self, obj, nextHandler, displayString: str = "", **kwargs) -> None:
		handleNotification(SOURCE_NOTIFICATION, obj, displayString, nextHandler)

	def event_liveRegionChange(self, obj, nextHandler, **kwargs) -> None:
		try:
			text = obj.name or obj.value or ""
		except Exception:
			text = ""
		handleNotification(SOURCE_LIVEREGION, obj, text, nextHandler)

	def event_windowOpened(self, obj, nextHandler, **kwargs) -> None:
		if text_context.appNameOf(obj).lower() != "shellexperiencehost":
			nextHandler()
			return
		handleNotification(SOURCE_TOAST, obj, _toastText(obj), nextHandler)

	# --------------------------------------------------- analizador de texto
	def _issueJump(self, direction: int) -> None:
		ctx = text_context.get()
		if ctx is None:
			speech.speakMessage(_("No hay texto que analizar aquí"))
			return
		issues = analyzeContext(ctx)
		if not issues:
			speech.speakMessage(_("No se han encontrado incoherencias"))
			return
		if direction > 0:
			cands = [i for i in issues if i.start > ctx.caret]
			target = cands[0] if cands else None
		else:
			cands = [i for i in issues if i.start < ctx.caret]
			target = cands[-1] if cands else None
		if target is None:
			speech.speakMessage(_("No hay más incoherencias") if direction > 0 else _("No hay incoherencias antes"))
			return
		ctx.moveTo(target.start)
		sameLine = [i for i in issues if ctx.lineBounds(target.start) == ctx.lineBounds(i.start)]
		speech.speak([text_analyzer.describe(sameLine if len(sameLine) > 1 else [target])])

	@script(description=_("Va a la siguiente incoherencia del texto (paréntesis sin cerrar, espacios dobles...)"), category=CAT_ANALYZER, gesture="kb:tiresias+control+alt+i")
	def script_nextTextIssue(self, gesture) -> None:
		self._issueJump(1)

	@script(description=_("Va a la incoherencia anterior del texto"), category=CAT_ANALYZER, gesture="kb:tiresias+control+shift+alt+i")
	def script_previousTextIssue(self, gesture) -> None:
		self._issueJump(-1)

	@script(description=_("Describe las incoherencias de la línea actual; pulsado dos veces, resume las de todo el texto"), category=CAT_ANALYZER, gesture="kb:tiresias+control+alt+d")
	def script_describeTextIssues(self, gesture) -> None:
		if _repeat() >= 1:
			ctx = text_context.get()
			if ctx is None:
				speech.speakMessage(_("No hay texto que analizar aquí"))
				return
			issues = analyzeContext(ctx)
			if not issues:
				speech.speakMessage(_("No se han encontrado incoherencias en el texto"))
				return
			counts: dict[str, int] = {}
			for i in issues:
				counts[i.kind] = counts.get(i.kind, 0) + 1
			parts = [f"{n} {text_analyzer.kindName(k)}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1])]
			speech.speakMessage(ngettext("{n} incoherencia", "{n} incoherencias", len(issues)).format(n=len(issues)) + ": " + ", ".join(parts))
			return
		res = _lineIssuesAtCaret()
		if res is None:
			speech.speakMessage(_("No hay texto que analizar aquí"))
			return
		issues, _line = res
		if not issues:
			speech.speakMessage(_("Sin incoherencias en esta línea"))
			return
		speech.speakMessage(text_analyzer.describe(issues))

	@script(description=_("Activa o desactiva el sonido al pasar por una línea con incoherencias"), category=CAT_ANALYZER)
	def script_toggleTextIssueSound(self, gesture) -> None:
		c = conf["textAnalyzer"]
		c["lineSound"] = not c["lineSound"]
		speech.speakMessage(_("Sonido de incoherencias activado") if c["lineSound"] else _("Sonido de incoherencias desactivado"))

	@script(description=_("Activa o desactiva la descripción de incoherencias al leer cada línea"), category=CAT_ANALYZER)
	def script_toggleTextIssueSpeech(self, gesture) -> None:
		c = conf["textAnalyzer"]
		c["lineSpeak"] = not c["lineSpeak"]
		speech.speakMessage(_("Descripción de incoherencias activada") if c["lineSpeak"] else _("Descripción de incoherencias desactivada"))

	# --------------------------------------------------- notificaciones
	@script(description=_("Muestra el historial de notificaciones"), category=CAT_NOTIFICATIONS, gesture="kb:tiresias+control+shift+alt+n")
	def script_showNotificationHistory(self, gesture) -> None:
		from ..gui import productivity_dialogs

		productivity_dialogs.showNotificationHistory()

	@script(description=_("Lee la última notificación; pulsado dos veces, la copia al portapapeles"), category=CAT_NOTIFICATIONS, gesture="kb:tiresias+control+alt+n")
	def script_readLastNotification(self, gesture) -> None:
		store = _pkg().notificationStore
		last = store.last() if store is not None else None
		if last is None:
			speech.speakMessage(_("No hay notificaciones en el historial"))
			return
		if _repeat() >= 1:
			api.copyToClip(last.text, True)
			return
		ago = int(time.time() - last.time)
		when = _("hace {n} segundos").format(n=ago) if ago < 120 else time.strftime("%H:%M", time.localtime(last.time))
		speech.speakMessage(f"{last.text}. {last.app}, {when}")

	@script(description=_("Abre las reglas de notificaciones"), category=CAT_NOTIFICATIONS)
	def script_showNotificationRules(self, gesture) -> None:
		from ..gui import productivity_dialogs

		productivity_dialogs.showNotificationRules()

	# --------------------------------------------------- vigilancia
	def _addWatch(self, kind: str) -> None:
		from .watch import KIND_OBJECT, KIND_REGION, objectText

		mgr = _pkg().watchManager
		obj = api.getNavigatorObject()
		if mgr is None or obj is None:
			speech.speakMessage(_("No hay objeto navegador"))
			return
		if kind == KIND_OBJECT:
			existing = mgr.findByObject(obj)
			if existing is not None:
				mgr.remove(existing)
				speech.speakMessage(_("Vigilancia {n} quitada").format(n=existing.slot))
				return
		rect = None
		if kind == KIND_REGION:
			rect = obj.location
			if not rect:
				speech.speakMessage(_("El objeto no tiene posición en pantalla"))
				return
			for w in list(mgr.watches):
				if w.kind == KIND_REGION and w.rect == rect:
					mgr.remove(w)
					speech.speakMessage(_("Vigilancia {n} quitada").format(n=w.slot))
					return
		label = obj.name or getattr(obj, "roleText", "") or ""
		app = text_context.appNameOf(obj)
		initial = objectText(obj) if kind == KIND_OBJECT else ""
		w = mgr.add(kind, obj, app, label[:80], rect, initial)
		if w is None:
			speech.speakMessage(_("Ya hay {n} vigilancias, el máximo. Quita alguna antes.").format(n=mgr.maxWatches()))
			return
		if kind == KIND_REGION:
			speech.speakMessage(_("Vigilando con OCR la región de {label}, vigilancia {n}").format(label=label or _("el objeto"), n=w.slot))
		else:
			speech.speakMessage(_("Vigilando {label}, vigilancia {n}").format(label=label or _("el objeto"), n=w.slot))

	@script(description=_("Vigila el objeto navegador y anuncia sus cambios (pulsar otra vez para dejar de vigilarlo)"), category=CAT_WATCH, gesture="kb:tiresias+control+alt+v")
	def script_toggleObjectWatch(self, gesture) -> None:
		from .watch import KIND_OBJECT

		self._addWatch(KIND_OBJECT)

	@script(description=_("Vigila con OCR la región de pantalla del objeto navegador (para programas sin accesibilidad)"), category=CAT_WATCH, gesture="kb:tiresias+control+shift+alt+v")
	def script_toggleRegionWatch(self, gesture) -> None:
		from .watch import KIND_REGION

		self._addWatch(KIND_REGION)

	@script(description=_("Muestra la lista de vigilancias"), category=CAT_WATCH, gesture="kb:tiresias+control+alt+l")
	def script_showWatches(self, gesture) -> None:
		from ..gui import productivity_dialogs

		productivity_dialogs.showWatches()

	@script(description=_("Quita todas las vigilancias"), category=CAT_WATCH)
	def script_clearWatches(self, gesture) -> None:
		mgr = _pkg().watchManager
		if mgr is None or not mgr.watches:
			speech.speakMessage(_("No hay vigilancias"))
			return
		n = len(mgr.watches)
		mgr.clear()
		speech.speakMessage(ngettext("{n} vigilancia quitada", "{n} vigilancias quitadas", n).format(n=n))

	# --------------------------------------------------- búsqueda en ventanas
	def _askFind(self, direction: int) -> None:
		from ..gui import dialogs

		finder = _pkg().windowFinder
		fg = api.getForegroundObject()

		def onText(text: str) -> None:
			text = text.strip()
			if not text:
				return
			finder.remember(text)
			# Se espera a que el diálogo se cierre y vuelva la ventana original.
			queue_handler.callLater(350, finder.find, text, direction, fg)

		dialogs.askText(_("Buscar en la ventana"), _("Texto a buscar en la ventana actual:"), finder.lastQuery, onText)

	@script(description=_("Busca un texto en cualquier parte de la ventana actual y lleva allí el navegador"), category=CAT_FIND, gesture="kb:tiresias+control+alt+f")
	def script_windowFind(self, gesture) -> None:
		self._askFind(1)

	@script(description=_("Busca la siguiente aparición del texto en la ventana actual"), category=CAT_FIND, gesture="kb:tiresias+alt+f3")
	def script_windowFindNext(self, gesture) -> None:
		finder = _pkg().windowFinder
		if not finder.lastQuery:
			self._askFind(1)
			return
		finder.find(finder.lastQuery, 1)

	@script(description=_("Busca la aparición anterior del texto en la ventana actual"), category=CAT_FIND, gesture="kb:tiresias+shift+alt+f3")
	def script_windowFindPrevious(self, gesture) -> None:
		finder = _pkg().windowFinder
		if not finder.lastQuery:
			self._askFind(-1)
			return
		finder.find(finder.lastQuery, -1)

	# --------------------------------------------------- marcadores de texto
	@script(description=_("Pone o quita un marcador de texto en la línea del cursor (en cualquier aplicación)"), category=CAT_BOOKMARKS, gesture="kb:tiresias+control+alt+k")
	def script_toggleTextBookmark(self, gesture) -> None:
		ctx = text_context.get()
		if ctx is None:
			speech.speakMessage(_("No hay texto aquí"))
			return
		placed = _pkg().bookmarkStore.toggle(ctx.key, ctx.text, ctx.caret, ctx.lineBounds)
		speech.speakMessage(_("marcador puesto") if placed else _("marcador quitado"))

	def _jumpBookmark(self, direction: int) -> None:
		ctx = text_context.get()
		if ctx is None:
			speech.speakMessage(_("No hay texto aquí"))
			return
		pos, wrapped = _pkg().bookmarkStore.neighbour(ctx.key, ctx.text, ctx.caret, direction, ctx.lineBounds)
		if pos is None:
			speech.speakMessage(_("No hay marcadores en este documento"))
			return
		if wrapped:
			from ..audio import tones

			tones.playSound("wrap")
		ctx.moveTo(pos)

	@script(description=_("Va al siguiente marcador de texto"), category=CAT_BOOKMARKS, gesture="kb:tiresias+control+alt+j")
	def script_nextTextBookmark(self, gesture) -> None:
		self._jumpBookmark(1)

	@script(description=_("Va al marcador de texto anterior"), category=CAT_BOOKMARKS, gesture="kb:tiresias+control+alt+h")
	def script_previousTextBookmark(self, gesture) -> None:
		self._jumpBookmark(-1)

	@script(description=_("Muestra la lista de marcadores de texto del documento actual"), category=CAT_BOOKMARKS)
	def script_listTextBookmarks(self, gesture) -> None:
		ctx = text_context.get()
		if ctx is None:
			speech.speakMessage(_("No hay texto aquí"))
			return
		from ..gui import productivity_dialogs
		from .text_bookmarks import relocate

		marks = _pkg().bookmarkStore.get(ctx.key)
		if not marks:
			speech.speakMessage(_("No hay marcadores en este documento"))
			return
		items = []
		for bm in marks:
			pos = relocate(bm, ctx.text)
			s, e = ctx.lineBounds(pos)
			line = " ".join(ctx.text[s:e].split()) or _("línea en blanco")
			lineNo = ctx.text.count("\n", 0, pos) + 1
			items.append((pos, _("Línea {n}: {text}").format(n=lineNo, text=line[:100])))
		productivity_dialogs.showTextBookmarks(ctx, items)

	# --------------------------------------------------- programas externos
	@script(description=_("Silencia o reactiva lo que dicen los juegos y programas a través de Tiresias"), category=CAT_CONTROLLER, gesture="kb:tiresias+shift+alt+g")
	def script_toggleControllerMute(self, gesture) -> None:
		from .. import controller

		controller.setMuted(not controller.isMuted())
		if controller.isMuted():
			speech.cancelSpeech()
			speech.speakMessage(_("Programas externos silenciados"))
		else:
			speech.speakMessage(_("Programas externos con voz"))

	@script(description=_("Informa del estado de la API de control y de los programas que la usan"), category=CAT_CONTROLLER)
	def script_controllerStatus(self, gesture) -> None:
		from .. import controller

		speech.speakMessage(controller.statusText())
