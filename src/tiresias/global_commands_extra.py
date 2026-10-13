"""Órdenes globales que completan las de :mod:`tiresias.global_commands`.

Recoge las órdenes equivalentes a las de NVDA que faltaban: conmutadores de
formato de documento, voz, revisión, ubicación, ratón, apertura de cada
panel de opciones y herramienta, perfiles, reinicio, registro, etc.

:func:`install` copia estas órdenes en ``GlobalCommands`` (solo las que esa
clase no define ya), de modo que el mapa de gestos del usuario, la paleta de
órdenes, el diálogo de gestos y la referencia rápida las tratan como órdenes
globales normales. Las que no tienen gesto se asignan desde «Gestos de
entrada» o se ejecutan desde la paleta de órdenes.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from . import api, queue_handler, speech, textinfo, winapi
from .baseobject import ScriptableObject, normalizeGestureId, script
from .config import conf
from .i18n import _
from .input import core as inputCore
from .log import getLogger
from .objects.roles import Role

log = getLogger("globalCommands")

CAT_MISC = _("Varios")
CAT_SPEECH = _("Voz")
CAT_NAV = _("Navegación de objetos")
CAT_REVIEW = _("Cursor de revisión")
CAT_SYSTEMCARET = _("Cursor del sistema")
CAT_FOCUS = _("Foco del sistema")
CAT_MOUSE = _("Ratón")
CAT_CONFIG = _("Configuración")
CAT_TOOLS = _("Herramientas")
CAT_INPUT = _("Entrada")
CAT_VISION = _("Visión")
CAT_DOC = _("Formato de documento")
CAT_PROFILES = _("Perfiles de configuración")

#: Desplazamiento del ratón en «muescas» de la rueda por cada orden.
SCROLL_NOTCHES = 1


def repeatCount() -> int:
	return inputCore.getLastScriptRepeatCount()


def _onOff(value: bool, what: str) -> str:
	return (_("{what}: activado") if value else _("{what}: desactivado")).format(what=what)


def _toggle(section: str, key: str, what: str) -> bool:
	value = not conf[section][key]
	conf[section][key] = value
	speech.speakMessage(_onOff(value, what))
	return value


def _cycle(section: str, key: str, values: list[tuple[Any, str]], what: str) -> Any:
	cur = conf[section][key]
	keys = [v for v, _l in values]
	i = keys.index(cur) if cur in keys else -1
	value, label = values[(i + 1) % len(values)]
	conf[section][key] = value
	speech.speakMessage(_("{what}: {value}").format(what=what, value=label))
	return value


def _onGui(func: Callable, *args: Any) -> None:
	from . import gui

	gui.runOnGui(func, *args)


# ====================================================================== ubicación
def _screenSize() -> tuple[int, int]:
	return winapi.user32.GetSystemMetrics(0) or 1, winapi.user32.GetSystemMetrics(1) or 1


def describePoint(x: int, y: int) -> str:
	sw, sh = _screenSize()
	return _("posición {x}, {y}: a {left} por ciento del borde izquierdo y {top} por ciento del borde superior").format(x=x, y=y, left=round(100 * x / sw), top=round(100 * y / sh))


def describeRect(x: int, y: int, w: int, h: int) -> str:
	sw, sh = _screenSize()
	return _("{w} por {h} píxeles, en {x}, {y}: a {left} por ciento del borde izquierdo y {top} por ciento del borde superior").format(
		w=w, h=h, x=x, y=y, left=round(100 * x / sw), top=round(100 * y / sh)
	)


def textLocation(info: Any) -> str | None:
	"""Ubicación en pantalla del carácter de ``info`` (``None`` si no se conoce)."""
	if info is None:
		return None
	try:
		c = info.copy()
		c.expand(textinfo.UNIT_CHARACTER)
		rects = c.boundingRects
		if rects:
			x, y, w, h = rects[0]
			return describeRect(int(x), int(y), int(w), int(h))
	except Exception:
		pass
	try:
		pt = info.pointAtStart
	except Exception:
		pt = None
	if pt is not None:
		return describePoint(int(pt.x), int(pt.y))
	return None


def objectLocation(obj: Any) -> str | None:
	loc = None
	try:
		loc = obj.location if obj is not None else None
	except Exception:
		loc = None
	if not loc:
		return None
	x, y, w, h = loc
	return describeRect(x, y, w, h)


# ====================================================================== detalles (aria-details y anotaciones)
_P_ANNOTATIONOBJECTS = 30156


def _elementsFromProperty(obj: Any, propId: int) -> list:
	try:
		from .a11y import uia_client as uc

		# Accesor tipado: estas matrices de elementos no se leen como VARIANT.
		return uc.elementArray(obj.element, propId)
	except Exception:
		return []


def _elementText(element: Any, depth: int = 0) -> str:
	try:
		name = element.CurrentName or ""
	except Exception:
		name = ""
	if name.strip() or depth >= 3:
		return name.strip()
	parts: list[str] = []
	try:
		from .a11y import uia_client as uc

		walker = uc.client.ControlViewWalker
		child = walker.GetFirstChildElement(element)
		count = 0
		while child and count < 40:
			t = _elementText(child, depth + 1)
			if t:
				parts.append(t)
			child = walker.GetNextSiblingElement(child)
			count += 1
	except Exception:
		pass
	return " ".join(parts)


def detailsSummary(obj: Any) -> str:
	"""Resumen de los detalles (aria-details) o anotaciones (comentarios) de ``obj``."""
	from .a11y import uia_client as uc

	cur = obj
	for _i in range(4):
		if cur is None or not hasattr(cur, "element"):
			break
		texts = [_elementText(el) for el in _elementsFromProperty(cur, uc.P_DESCRIBEDBY) + _elementsFromProperty(cur, _P_ANNOTATIONOBJECTS)]
		texts = [t for t in texts if t]
		if texts:
			return "\n".join(texts)
		try:
			cur = cur.parent
			if cur is not None and cur.role in (Role.DOCUMENT, Role.WINDOW, Role.PANE):
				break
		except Exception:
			break
	return ""


# ====================================================================== modo dormir en perfiles (#3721)
#: Aplicaciones que se durmieron por la opción ``sleepMode.enabled`` del perfil activo.
_profileSlept: list = []
#: Aplicaciones que el usuario despertó a mano mientras el perfil las dormía.
_userWoken: list = []


def _onProfileSwitch() -> None:
	queue_handler.queueFunction(applyProfileSleepMode)


def _onFocusChange() -> None:
	if _profileSlept or conf["sleepMode"]["enabled"]:
		queue_handler.queueFunction(applyProfileSleepMode)


def applyProfileSleepMode() -> None:
	"""Duerme la aplicación en primer plano si la configuración activa lo pide."""
	try:
		from .appmodules import handler as appHandler

		app = appHandler.getForegroundApp()
	except Exception:
		app = None
	if app is not None and getattr(app, "processID", None) == os.getpid():
		# Nunca se duerme el propio Tiresias (sus diálogos tienen que hablar).
		app = None
	want = bool(conf["sleepMode"]["enabled"])
	if not want and not _profileSlept and not _userWoken:
		return
	changed = False
	for a in list(_profileSlept):
		if a is app and want and not a.sleepMode:
			# El usuario lo despertó con la orden: se respeta mientras siga aquí.
			_profileSlept.remove(a)
			_userWoken.append(a)
		elif a is not app or not want:
			_profileSlept.remove(a)
			if a.sleepMode:
				a.sleepMode = False
				changed = True
	for a in list(_userWoken):
		if a is not app or not want:
			_userWoken.remove(a)
	if want and app is not None and not app.sleepMode and app not in _userWoken:
		app.sleepMode = True
		_profileSlept.append(app)
		changed = True
		# Indicación al activarse el modo dormir (#13532).
		speech.speakMessage(_("Modo dormir activado"))
	if changed:
		inputCore.manager.updateChain()


# ====================================================================== órdenes
class ExtraCommands(ScriptableObject):
	"""Órdenes que :func:`install` añade a ``GlobalCommands``."""

	# ------------------------------------------------------------ entrada
	@script(description=_("Cambia entre la distribución de teclado de sobremesa y la de portátil"), category=CAT_INPUT)
	def script_toggleKeyboardLayout(self, gesture) -> None:
		layout = "laptop" if conf["keyboard"]["layout"] == "desktop" else "desktop"
		conf["keyboard"]["layout"] = layout
		inputCore.manager.updateChain()
		speech.speakMessage(_("Distribución de teclado: portátil") if layout == "laptop" else _("Distribución de teclado: sobremesa"))

	# ------------------------------------------------------------ voz
	@script(description=_("Cambia el cambio automático de idioma: desactivado, solo idioma, idioma y dialecto"), category=CAT_SPEECH)
	def script_cycleSpeechAutomaticLanguageSwitching(self, gesture) -> None:
		sp = conf["speech"]
		if not sp["autoLanguageSwitching"]:
			sp["autoLanguageSwitching"], sp["autoDialectSwitching"] = True, False
			msg = _("cambio automático de idioma: solo idioma")
		elif not sp["autoDialectSwitching"]:
			sp["autoDialectSwitching"] = True
			msg = _("cambio automático de idioma: idioma y dialecto")
		else:
			sp["autoLanguageSwitching"], sp["autoDialectSwitching"] = False, False
			msg = _("cambio automático de idioma: desactivado")
		speech.speakMessage(msg)

	@script(description=_("Activa o desactiva la descripción fonética retardada de caracteres al mover el cursor"), category=CAT_SPEECH)
	def script_toggleDelayedCharacterDescriptions(self, gesture) -> None:
		_toggle("speech", "delayedCharacterDescriptions", _("descripción retardada de caracteres"))

	@script(description=_("Activa o desactiva la normalización Unicode de la voz"), category=CAT_SPEECH)
	def script_speech_cycleUnicodeNormalization(self, gesture) -> None:
		_toggle("speech", "unicodeNormalization", _("normalización Unicode"))

	@script(description=_("Activa o desactiva la lectura de los nombres de emojis (CLDR)"), category=CAT_SPEECH)
	def script_toggleReportCLDR(self, gesture) -> None:
		_toggle("speech", "speakEmojiNames", _("nombres de emojis"))

	def _ringExtreme(self, last: bool) -> None:
		from . import synth

		s = synth.getSynth()
		setting = synth.ring.current
		if s is None or setting is None:
			speech.speakMessage(_("Sin ajustes"))
			return
		if setting.kind == "numeric":
			synth.changeSetting(setting.id, setting.maxVal if last else setting.minVal)
		elif setting.kind == "boolean":
			synth.changeSetting(setting.id, bool(last))
		elif setting.kind == "choice":
			keys = list(s.getChoices(setting.id).keys())
			if keys:
				synth.changeSetting(setting.id, keys[-1] if last else keys[0])
		speech.speakMessage(synth.ring.valueText(setting))

	@script(description=_("Pone el ajuste actual del anillo de voz en su primer valor"), category=CAT_SPEECH)
	def script_firstValueSynthRing(self, gesture) -> None:
		self._ringExtreme(False)

	@script(description=_("Pone el ajuste actual del anillo de voz en su último valor"), category=CAT_SPEECH)
	def script_lastValueSynthRing(self, gesture) -> None:
		self._ringExtreme(True)

	@script(description=_("Anuncia el idioma del texto en el cursor (dos veces: lo muestra)"), category=CAT_SYSTEMCARET, speakOnDemand=True)
	def script_reportCaretLanguage(self, gesture) -> None:
		from . import i18n, synth

		lang = None
		obj = api.getCaretObject()
		try:
			info = obj.makeTextInfo(textinfo.POSITION_CARET)
			getter = getattr(info, "getLanguage", None)
			lang = getter() if getter else None
		except Exception:
			lang = None
		if lang:
			text = _("idioma del texto: {lang}").format(lang=i18n.languageName(lang))
		else:
			s = synth.getSynth()
			voiceLang = getattr(s, "language", "") if s is not None else ""
			text = _("idioma del texto desconocido; idioma de la voz: {lang}").format(lang=i18n.languageName(voiceLang)) if voiceLang else _("idioma del texto desconocido")
		if repeatCount() == 1:
			from . import gui

			gui.showBrowseableMessage(text, _("Idioma"))
		else:
			speech.speakMessage(text)

	# ------------------------------------------------------------ cursor del sistema
	def _caretLineParts(self) -> tuple[Any, Any] | None:
		obj = api.getCaretObject()
		if obj is None:
			return None
		try:
			caret = obj.makeTextInfo(textinfo.POSITION_CARET)
			line = caret.copy()
			line.expand(textinfo.UNIT_LINE)
			return caret, line
		except Exception:
			return None

	@script(description=_("Lee desde el inicio de la línea hasta el cursor"), category=CAT_SYSTEMCARET, gesture="kb:tiresias+shift+alt+home", speakOnDemand=True)
	def script_sayFromLineStartToCaret(self, gesture) -> None:
		# Petición #15093 de NVDA.
		parts = self._caretLineParts()
		if parts is None:
			speech.speakMessage(_("sin cursor"))
			return
		caret, line = parts
		try:
			r = line.copy()
			r.setEndPoint(caret, "endToStart")
			text = r.text.rstrip("\r\n")
		except Exception:
			text = ""
		if text.strip():
			speech.speakText(text)
		else:
			speech.speakMessage(_("en blanco"))

	@script(description=_("Lee desde el cursor hasta el final de la línea"), category=CAT_SYSTEMCARET, gesture="kb:tiresias+shift+alt+end", speakOnDemand=True)
	def script_sayFromCaretToLineEnd(self, gesture) -> None:
		# Petición #15093 de NVDA.
		parts = self._caretLineParts()
		if parts is None:
			speech.speakMessage(_("sin cursor"))
			return
		caret, line = parts
		try:
			r = line.copy()
			r.setEndPoint(caret, "startToStart")
			text = r.text.rstrip("\r\n")
		except Exception:
			text = ""
		if text.strip():
			speech.speakText(text)
		else:
			speech.speakMessage(_("en blanco"))

	@script(
		description=_("Anuncia cuántos caracteres hay escritos en el campo con el foco y cuántos quedan hasta su longitud máxima"),
		category=CAT_SYSTEMCARET,
		gesture="kb:tiresias+control+l",
		speakOnDemand=True,
	)
	def script_reportRemainingCharacters(self, gesture) -> None:
		# Foros 1.17 (#7910 de NVDA): caracteres restantes.
		from .objects import text_limits

		text_limits.reportRemaining(api.getFocusObject())

	# ------------------------------------------------------------ formato
	def _formatAt(self, info: Any) -> list[str]:
		from . import formatting

		if info is None:
			return []
		try:
			return formatting.fullDescription(info)
		except Exception:
			log.debug("Error leyendo el formato", exc_info=True)
			return []

	def _reviewInfo(self) -> Any:
		return api.getReviewPosition()

	def _caretInfo(self) -> Any:
		obj = api.getCaretObject()
		try:
			return obj.makeTextInfo(textinfo.POSITION_CARET) if obj is not None else None
		except Exception:
			return None

	def _reportFormat(self, info: Any, show: bool) -> None:
		parts = self._formatAt(info)
		if not parts:
			speech.speakMessage(_("sin información de formato"))
			return
		if show:
			from . import gui

			gui.showBrowseableMessage("\n".join(parts), _("Formato"))
		else:
			speech.speakMessage(", ".join(parts))

	@script(description=_("Anuncia el formato del texto en el cursor de revisión (dos veces: lo muestra)"), category=CAT_REVIEW, gesture="kb:tiresias+shift+f", speakOnDemand=True)
	def script_reportOrShowFormattingAtReview(self, gesture) -> None:
		self._reportFormat(self._reviewInfo(), repeatCount() == 1)

	@script(description=_("Anuncia el formato del texto en el cursor de revisión"), category=CAT_REVIEW, speakOnDemand=True)
	def script_reportFormattingAtReview(self, gesture) -> None:
		self._reportFormat(self._reviewInfo(), False)

	@script(description=_("Muestra en una ventana el formato del texto en el cursor de revisión"), category=CAT_REVIEW)
	def script_showFormattingAtReview(self, gesture) -> None:
		self._reportFormat(self._reviewInfo(), True)

	@script(description=_("Anuncia el formato del texto en el cursor del sistema"), category=CAT_DOC, speakOnDemand=True)
	def script_reportFormattingAtCaret(self, gesture) -> None:
		self._reportFormat(self._caretInfo(), False)

	@script(description=_("Muestra en una ventana el formato del texto en el cursor del sistema"), category=CAT_DOC)
	def script_showFormattingAtCaret(self, gesture) -> None:
		self._reportFormat(self._caretInfo(), True)

	@script(description=_("Anuncia los detalles o comentarios del elemento en el cursor (dos veces: los muestra)"), category=CAT_SYSTEMCARET, gesture="kb:tiresias+d", speakOnDemand=True)
	def script_reportDetailsSummary(self, gesture) -> None:
		obj = None
		caret = api.getCaretObject()
		try:
			if caret is not None and hasattr(caret, "buffer"):
				obj = caret.makeTextInfo(textinfo.POSITION_CARET).getEnclosingObject()
		except Exception:
			obj = None
		obj = obj or api.getFocusObject()
		text = detailsSummary(obj) if obj is not None else ""
		if not text:
			speech.speakMessage(_("sin detalles"))
			return
		if repeatCount() == 1:
			from . import gui

			gui.showBrowseableMessage(text, _("Detalles"))
		else:
			speech.speakText(text)

	# ------------------------------------------------------------ revisión
	@script(description=_("Anuncia el símbolo en el cursor de revisión (dos veces: lo muestra con su texto)"), category=CAT_REVIEW, speakOnDemand=True)
	def script_review_currentSymbol(self, gesture) -> None:
		from .speech.symbols import processor

		info = api.getReviewPosition()
		ch = ""
		if info is not None:
			try:
				c = info.copy()
				c.expand(textinfo.UNIT_CHARACTER)
				ch = c.text[:1]
			except Exception:
				ch = ""
		if not ch or ch.isalnum() or ch.isspace():
			speech.speakMessage(_("sin símbolo"))
			return
		name = processor.characterName(ch)
		if not name or name == ch:
			speech.speakMessage(_("sin símbolo"))
			return
		if repeatCount() == 1:
			from . import gui

			gui.showBrowseableMessage(_("Símbolo: {sym}\nSe lee: {name}").format(sym=ch, name=name), _("Símbolo"))
		else:
			speech.speakMessage(name)

	def _reviewSelectionEdge(self, end: bool) -> None:
		pos = api.getReviewPosition()
		obj = getattr(pos, "obj", None) if pos is not None else None
		obj = obj or api.getCaretObject()
		try:
			sel = obj.makeTextInfo(textinfo.POSITION_SELECTION)
		except Exception:
			sel = None
		if sel is None or sel.isCollapsed:
			speech.speakMessage(_("sin selección"))
			return
		info = sel.copy()
		if end:
			info.collapse(end=True)
			info.move(textinfo.UNIT_CHARACTER, -1)
		else:
			info.collapse()
		api.setReviewPosition(info)
		from . import mouse, presentation

		mouse.reviewAudioCoordinates(info)  # #2559

		presentation.speakTextInfo(info, textinfo.UNIT_CHARACTER, reason=presentation.Reason.REVIEW)

	@script(description=_("Lleva el cursor de revisión al principio de la selección"), category=CAT_REVIEW, gesture="kb:tiresias+alt+home")
	def script_review_startOfSelection(self, gesture) -> None:
		self._reviewSelectionEdge(False)

	@script(description=_("Lleva el cursor de revisión al final de la selección"), category=CAT_REVIEW, gesture="kb:tiresias+alt+end")
	def script_review_endOfSelection(self, gesture) -> None:
		self._reviewSelectionEdge(True)

	@script(description=_("Lleva el cursor de revisión a la marca de inicio para copiar"), category=CAT_REVIEW, gesture="kb:tiresias+shift+f9")
	def script_review_moveToStartMarkedForCopy(self, gesture) -> None:
		start = getattr(self, "_copyStart", None)
		if start is None:
			speech.speakMessage(_("no hay marca de inicio"))
			return
		info = start.copy()
		api.setReviewPosition(info)
		from . import mouse, presentation

		mouse.reviewAudioCoordinates(info)  # #2559

		presentation.speakTextInfo(info, textinfo.UNIT_CHARACTER, reason=presentation.Reason.REVIEW)

	@script(description=_("Lee la barra de estado y lleva a ella el objeto navegador"), category=CAT_NAV, speakOnDemand=True)
	def script_reviewCursorToStatusLine(self, gesture) -> None:
		from . import presentation

		bar = api.getStatusBar()
		if bar is None:
			speech.speakMessage(_("no se encontró la barra de estado"))
			return
		api.setNavigatorObject(bar)
		try:
			api.setReviewPosition(bar.makeTextInfo(textinfo.POSITION_FIRST))
		except Exception:
			pass
		text = " ".join(c.name for c in bar.children if c.name) or bar.name
		if text:
			speech.speakText(text)
		else:
			presentation.speakObject(bar, reason=presentation.Reason.QUERY)

	@script(description=_("Activa o desactiva el modo de revisión simple (omitir objetos de diseño)"), category=CAT_NAV)
	def script_toggleSimpleReviewMode(self, gesture) -> None:
		_toggle("reviewCursor", "simpleReviewMode", _("modo de revisión simple"))

	# ------------------------------------------------------------ ubicación
	@script(description=_("Anuncia la ubicación del texto en el cursor de revisión, o del objeto navegador"), category=CAT_NAV, speakOnDemand=True)
	def script_reportReviewCursorLocation(self, gesture) -> None:
		text = textLocation(api.getReviewPosition()) or objectLocation(api.getNavigatorObject())
		speech.speakMessage(text or _("sin ubicación"))

	@script(description=_("Anuncia la ubicación del objeto navegador"), category=CAT_NAV, speakOnDemand=True)
	def script_reportCurrentNavigatorObjectLocation(self, gesture) -> None:
		speech.speakMessage(objectLocation(api.getNavigatorObject()) or _("sin ubicación"))

	@script(description=_("Anuncia la ubicación del texto en el cursor del sistema, o del foco si no hay cursor"), category=CAT_SYSTEMCARET, speakOnDemand=True)
	def script_reportCaretLocation(self, gesture) -> None:
		text = textLocation(self._caretInfo()) or objectLocation(api.getFocusObject())
		speech.speakMessage(text or _("sin ubicación"))

	@script(description=_("Anuncia la ubicación del objeto con el foco"), category=CAT_FOCUS, speakOnDemand=True)
	def script_reportFocusObjectLocation(self, gesture) -> None:
		speech.speakMessage(objectLocation(api.getFocusObject()) or _("sin ubicación"))

	# ------------------------------------------------------------ ratón
	def _scroll(self, amount: int, horizontal: bool, message: str) -> None:
		from . import mouse

		mouse.scroll(amount, horizontal=horizontal)
		speech.speakMessage(message)

	@script(description=_("Desplaza hacia arriba con la rueda del ratón en la posición del puntero"), category=CAT_MOUSE)
	def script_mouseScrollUp(self, gesture) -> None:
		self._scroll(SCROLL_NOTCHES, False, _("rueda arriba"))

	@script(description=_("Desplaza hacia abajo con la rueda del ratón en la posición del puntero"), category=CAT_MOUSE)
	def script_mouseScrollDown(self, gesture) -> None:
		self._scroll(-SCROLL_NOTCHES, False, _("rueda abajo"))

	@script(description=_("Desplaza a la izquierda con la rueda del ratón en la posición del puntero"), category=CAT_MOUSE)
	def script_mouseScrollLeft(self, gesture) -> None:
		self._scroll(-SCROLL_NOTCHES, True, _("rueda a la izquierda"))

	@script(description=_("Desplaza a la derecha con la rueda del ratón en la posición del puntero"), category=CAT_MOUSE)
	def script_mouseScrollRight(self, gesture) -> None:
		self._scroll(SCROLL_NOTCHES, True, _("rueda a la derecha"))

	@script(description=_("Activa o desactiva los tonos de coordenadas al mover el ratón"), category=CAT_MOUSE)
	def script_toggleMouseAudioCoordinates(self, gesture) -> None:
		_toggle("mouse", "audioCoordinatesOnMouseMove", _("tonos de coordenadas del ratón"))

	# #2559: coordenadas por sonido del objeto navegador y del cursor de revisión.
	@script(description=_("Activa o desactiva los tonos de coordenadas al mover el objeto navegador"), category=CAT_NAV)
	def script_toggleNavigatorAudioCoordinates(self, gesture) -> None:
		_toggle("reviewCursor", "audioCoordinatesOnNavigatorMove", _("tonos de coordenadas del navegador"))

	@script(description=_("Activa o desactiva los tonos de coordenadas al mover el cursor de revisión"), category=CAT_REVIEW)
	def script_toggleReviewAudioCoordinates(self, gesture) -> None:
		_toggle("reviewCursor", "audioCoordinatesOnReviewMove", _("tonos de coordenadas de la revisión"))

	# #11898: retardo para leer lo que hay bajo el ratón (0 = sin espera).
	@script(description=_("Cambia la espera antes de leer lo que hay bajo el ratón"), category=CAT_MOUSE)
	def script_cycleMouseReportDelay(self, gesture) -> None:
		_cycle(
			"mouse",
			"reportDelay",
			[(0, _("sin espera")), (250, _("250 milisegundos")), (500, _("500 milisegundos")), (1000, _("1 segundo"))],
			_("espera del ratón"),
		)

	@script(description=_("Cambia la cantidad de texto que se lee al mover el ratón"), category=CAT_MOUSE)
	def script_toggleMouseTextResolution(self, gesture) -> None:
		_cycle("mouse", "mouseTextUnit", [("character", _("carácter")), ("word", _("palabra")), ("line", _("línea")), ("paragraph", _("párrafo"))], _("texto bajo el ratón"))

	# ------------------------------------------------------------ visión
	@script(description=_("Anuncia si la cortina de pantalla está activada"), category=CAT_VISION, speakOnDemand=True)
	def script_reportScreenCurtainState(self, gesture) -> None:
		from . import vision

		speech.speakMessage(vision.handler.curtainStateText())

	# ------------------------------------------------------------ herramientas
	@script(description=_("Muestra en una ventana el destino del enlace en el cursor o el foco"), category=CAT_TOOLS)
	def script_reportLinkDestinationInWindow(self, gesture) -> None:
		target = None
		caret = api.getCaretObject()
		if caret is not None and hasattr(caret, "buffer"):
			try:
				target = caret.makeTextInfo(textinfo.POSITION_CARET).getEnclosingObject()
			except Exception:
				target = None
		target = target or api.getNavigatorObject()
		while target is not None and target.role != Role.LINK:
			target = target.parent
			if target is not None and target.role in (Role.DOCUMENT, Role.WINDOW):
				target = None
		if target is None:
			speech.speakMessage(_("no es un enlace"))
			return
		url = ""
		try:
			from .a11y import uia_client as uc

			url = target._prop(uc.P_VALUEVALUE, "") or ""
		except Exception:
			url = ""
		if not url:
			speech.speakMessage(_("destino del enlace desconocido"))
			return
		from . import gui

		gui.showBrowseableMessage(url, _("Destino del enlace"))

	@script(description=_("Abre o cierra el visor de voz"), category=CAT_TOOLS)
	def script_toggleSpeechViewer(self, gesture) -> None:
		from . import gui

		gui.toggleSpeechViewer()

	@script(description=_("Abre o cierra el visor braille"), category=CAT_TOOLS)
	def script_toggleBrailleViewer(self, gesture) -> None:
		from . import gui

		gui.toggleBrailleViewer()

	@script(description=_("Abre el visor del registro"), category=CAT_TOOLS)
	def script_activateLogViewer(self, gesture) -> None:
		from . import gui

		gui.showLogViewer()

	@script(description=_("Marca el final actual del registro; al pulsar otra vez, copia lo registrado desde la marca"), category=CAT_TOOLS, gesture="kb:tiresias+control+shift+f1")
	def script_log_markStartThenCopy(self, gesture) -> None:
		from . import log as logModule

		if not logModule.hasMark():
			logModule.markStart()
			speech.speakMessage(_("Inicio del registro marcado; pulse otra vez para copiar"))
			return
		text = logModule.getTextSinceMark()
		logModule.clearMark()
		if not text.strip():
			speech.speakMessage(_("No hay nada nuevo en el registro"))
			return
		api.copyToClip(text, notify=True)

	@script(description=_("Abre la carpeta de configuración del usuario"), category=CAT_TOOLS)
	def script_openUserConfigurationDirectory(self, gesture) -> None:
		from . import paths
		from .global_commands import policyBlocks

		if policyBlocks("openDataFolder"):
			return
		folder = paths.configDir()

		def _open() -> None:
			try:
				os.makedirs(folder, exist_ok=True)
				os.startfile(folder)
			except OSError:
				log.exception("No se pudo abrir la carpeta de configuración")
				queue_handler.queueFunction(speech.speakMessage, _("No se pudo abrir la carpeta de configuración"))

		_onGui(_open)

	@script(description=_("Abre el administrador de complementos"), category=CAT_TOOLS)
	def script_activateAddonsManager(self, gesture) -> None:
		from . import gui

		gui.showAddonsManager()

	@script(description=_("Reinicia Tiresias"), category=CAT_TOOLS, gesture="kb:tiresias+shift+q", allowInSleepMode=True)
	def script_restart(self, gesture) -> None:
		from . import core

		speech.speakMessage(_("Reiniciando"))
		core.restart()

	# ------------------------------------------------------------ diálogos de opciones
	def _settings(self, category: str) -> None:
		from . import gui

		gui.showSettings(category)

	# «Seleccionar línea braille» (activateBrailleDisplayDialog) está en
	# GlobalCommands: abre su propio diálogo, no las opciones de braille.

	@script(description=_("Abre las opciones del cursor de revisión"), category=CAT_CONFIG)
	def script_activateReviewCursorDialog(self, gesture) -> None:
		self._settings("reviewCursor")

	@script(description=_("Abre las opciones de visión"), category=CAT_CONFIG)
	def script_activateVisionSettingsDialog(self, gesture) -> None:
		self._settings("vision")

	@script(description=_("Abre las opciones de la lupa"), category=CAT_CONFIG, gesture="kb:tiresias+control+w")
	def script_activateMagnifierSettingsDialog(self, gesture) -> None:
		self._settings("magnifier")

	@script(description=_("Abre las opciones del reconocimiento de texto (OCR)"), category=CAT_CONFIG)
	def script_activateWindowsOCRSettings(self, gesture) -> None:
		self._settings("ocr")

	@script(description=_("Abre las opciones avanzadas"), category=CAT_CONFIG)
	def script_activateAdvancedSettings(self, gesture) -> None:
		self._settings("advanced")

	@script(description=_("Abre las opciones del portapapeles"), category=CAT_CONFIG)
	def script_activateClipboardSettings(self, gesture) -> None:
		self._settings("clipboard")

	@script(description=_("Abre las opciones de UI Automation (categoría Avanzado)"), category=CAT_CONFIG)
	def script_activateUIASettings(self, gesture) -> None:
		# Las opciones de UI Automation están en «Avanzado» (grupo «UI Automation»).
		self._settings("uia")

	@script(description=_("Abre el diccionario de voz por defecto"), category=CAT_CONFIG)
	def script_activateDefaultDictionaryDialog(self, gesture) -> None:
		from . import gui

		gui.showSpeechDictionary("default")

	@script(description=_("Abre el diccionario de la voz actual"), category=CAT_CONFIG)
	def script_activateVoiceDictionaryDialog(self, gesture) -> None:
		from . import gui

		gui.showSpeechDictionary("voice")

	@script(description=_("Abre el diccionario de voz temporal"), category=CAT_CONFIG)
	def script_activateTemporaryDictionaryDialog(self, gesture) -> None:
		from . import gui

		gui.showSpeechDictionary("temp")

	@script(description=_("Abre la pronunciación de puntuación y símbolos"), category=CAT_CONFIG)
	def script_activateSpeechSymbolsDialog(self, gesture) -> None:
		from . import gui

		gui.showSymbols()

	@script(description=_("Abre los gestos de entrada"), category=CAT_CONFIG)
	def script_activateInputGesturesDialog(self, gesture) -> None:
		from . import gui

		gui.showInputGestures()

	# ------------------------------------------------------------ perfiles
	@script(description=_("Anuncia el perfil de configuración activo"), category=CAT_PROFILES, speakOnDemand=True)
	def script_reportActiveConfigurationProfile(self, gesture) -> None:
		name = conf.activeProfileName
		if not name:
			speech.speakMessage(_("configuración normal"))
		elif name == conf.manualProfile:
			speech.speakMessage(_("perfil {name}, activado manualmente").format(name=name))
		else:
			speech.speakMessage(_("perfil {name}").format(name=name))

	@script(description=_("Activa o desactiva todos los disparadores de perfiles (hasta reiniciar Tiresias)"), category=CAT_PROFILES)
	def script_toggleConfigProfileTriggers(self, gesture) -> None:
		from .config import post_configProfileSwitch

		conf.triggersEnabled = not conf.triggersEnabled
		post_configProfileSwitch.notify()
		speech.speakMessage(_("disparadores de perfiles activados") if conf.triggersEnabled else _("disparadores de perfiles desactivados"))


# ------------------------------------------------------------------ formato de documento
#: Conmutadores booleanos: (nombre de la orden, clave, qué se anuncia).
DOC_TOGGLES: list[tuple[str, str, str]] = [
	("toggleReportFontName", "reportFontName", _("nombre de la fuente")),
	("toggleReportFontSize", "reportFontSize", _("tamaño de la fuente")),
	("toggleReportFontAttributes", "reportFontAttributes", _("atributos de la fuente")),
	("toggleReportSuperscriptsAndSubscripts", "reportSuperscriptsAndSubscripts", _("superíndices y subíndices")),
	("toggleReportRevisions", "reportRevisions", _("revisiones")),
	("toggleReportEmphasis", "reportEmphasis", _("énfasis")),
	("toggleReportHighlightedText", "reportHighlight", _("texto resaltado")),
	("toggleReportColor", "reportColor", _("colores")),
	("toggleReportAlignment", "reportAlignment", _("alineación")),
	("toggleReportStyle", "reportStyle", _("estilo")),
	("toggleReportSpellingErrors", "reportSpellingErrors", _("errores ortográficos")),
	("toggleReportPage", "reportPage", _("páginas")),
	("toggleReportLineNumber", "reportLineNumber", _("números de línea")),
	("toggleignoreBlankLinesForReportLineIndentation", "ignoreBlankLinesForRLI", _("ignorar las líneas en blanco en la sangría")),
	("toggleReportParagraphIndentation", "reportParagraphIndentation", _("sangría de los párrafos")),
	("toggleReportLineSpacing", "reportLineSpacing", _("interlineado")),
	("toggleReportTables", "reportTables", _("tablas")),
	("toggleReportTableHeaders", "reportTableHeaders", _("encabezados de tabla")),
	("toggleReportTableCellCoords", "reportTableCellCoords", _("coordenadas de las celdas")),
	("toggleReportLinks", "reportLinks", _("enlaces")),
	("toggleReportLinkType", "reportLinkType", _("tipo de enlace")),
	("toggleReportGraphics", "reportGraphics", _("gráficos")),
	("toggleReportComments", "reportComments", _("comentarios")),
	("toggleReportLists", "reportLists", _("listas")),
	("toggleReportHeadings", "reportHeadings", _("encabezados")),
	("toggleReportGroupings", "reportGroupings", _("agrupaciones")),
	("toggleReportBlockQuotes", "reportBlockQuotes", _("citas")),
	("toggleReportLandmarks", "reportLandmarks", _("regiones y puntos de referencia")),
	("toggleReportArticles", "reportArticles", _("artículos")),
	("toggleReportFrames", "reportFrames", _("marcos")),
	("toggleReportClickable", "reportClickable", _("elementos pulsables")),
	("toggleReportFigures", "reportFigures", _("figuras y rótulos")),
	("toggleReportQuotes", "reportQuotes", _("citas en línea")),
	("toggleReportDetails", "reportDetails", _("detalles y continuación del contenido")),
	("toggleUseHeaderAbbreviations", "useHeaderAbbreviations", _("abreviatura de los encabezados")),
	("toggleDetectFormatAfterCursor", "detectFormatAfterCursor", _("cambios de formato después del cursor")),
]

#: Conmutadores con varios valores: (orden, clave, qué se anuncia, valores).
DOC_CYCLES: list[tuple[str, str, str, list[tuple[str, str]]]] = [
	(
		"toggleReportLineIndentation",
		"reportLineIndentation",
		_("sangría de las líneas"),
		[("off", _("desactivada")), ("speech", _("voz")), ("tones", _("tonos")), ("both", _("voz y tonos"))],
	),
	(
		"toggleReportCellBorders",
		"reportCellBorders",
		_("bordes de las celdas"),
		[("off", _("desactivado")), ("styles", _("estilos")), ("colorsAndStyles", _("colores y estilos"))],
	),
	(
		# #8674: valores RGB o hexadecimales de los colores.
		"cycleColorFormat",
		"colorFormat",
		_("forma de decir los colores"),
		[("name", _("solo el nombre")), ("nameAndRgb", _("nombre y valores RGB")), ("nameAndHex", _("nombre y código hexadecimal"))],
	),
]


def _resetFormatting() -> None:
	try:
		from . import formatting

		formatting.reset()
	except Exception:
		pass


def _makeDocToggle(name: str, key: str, what: str) -> Callable:
	def func(self, gesture) -> None:
		_toggle("documentFormatting", key, what)
		_resetFormatting()

	func.__name__ = "script_" + name
	func.__qualname__ = "ExtraCommands.script_" + name
	return script(description=_("Activa o desactiva el anuncio de: {what}").format(what=what), category=CAT_DOC)(func)


def _makeDocCycle(name: str, key: str, what: str, values: list[tuple[str, str]]) -> Callable:
	def func(self, gesture) -> None:
		_cycle("documentFormatting", key, values, what)
		_resetFormatting()

	func.__name__ = "script_" + name
	func.__qualname__ = "ExtraCommands.script_" + name
	return script(description=_("Cambia el anuncio de: {what}").format(what=what), category=CAT_DOC)(func)


for _name, _key, _what in DOC_TOGGLES:
	setattr(ExtraCommands, "script_" + _name, _makeDocToggle(_name, _key, _what))
for _name, _key, _what, _values in DOC_CYCLES:
	setattr(ExtraCommands, "script_" + _name, _makeDocCycle(_name, _key, _what, _values))


# ------------------------------------------------------------------ instalación
_installed: set[type] = set()


def install(cls: type) -> None:
	"""Añade a ``cls`` (``GlobalCommands``) las órdenes que no tenga ya."""
	if cls in _installed:
		return
	_installed.add(cls)
	gestures = cls.__dict__.get("_classGestures")
	if gestures is None:
		gestures = {}
		cls._classGestures = gestures  # type: ignore[attr-defined]
	for attr, func in list(vars(ExtraCommands).items()):
		# Órdenes y métodos auxiliares; nunca atributos especiales ni de clase.
		if attr.startswith("__") or attr in ("_classGestures",) or not callable(func):
			continue
		if attr in cls.__dict__:
			continue
		setattr(cls, attr, func)
		if attr.startswith("script_"):
			for g in getattr(func, "gestures", ()) or ():
				gestures.setdefault(normalizeGestureId(g), attr[7:])
	try:
		from .config import post_configProfileSwitch

		post_configProfileSwitch.register(_onProfileSwitch)
		# Al cambiar de aplicación sin cambio de perfil (opción en la configuración base).
		api.post_focusChange.register(_onFocusChange)
	except Exception:
		log.exception("No se pudo registrar el modo dormir por perfil")
