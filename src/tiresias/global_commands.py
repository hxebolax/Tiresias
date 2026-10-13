"""Órdenes globales de Tiresias (disponibles en cualquier aplicación).

Los gestos ``kb(desktop)`` corresponden a la distribución de sobremesa (con
teclado numérico) y ``kb(laptop)`` a la de portátil.
"""

from __future__ import annotations

import datetime

from . import api, presentation, review, speech, textinfo, winapi
from .audio import tones
from .baseobject import ScriptableObject, script
from .config import conf
from .i18n import _
from .input import core as inputCore
from .log import getLogger
from .objects.roles import Role
from .speech import sayall

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
CAT_BRAILLE = _("Braille")
CAT_DOC = _("Formato de documento")
CAT_AUDIO = _("Audio")

_MONTHS = [
	_("enero"),
	_("febrero"),
	_("marzo"),
	_("abril"),
	_("mayo"),
	_("junio"),
	_("julio"),
	_("agosto"),
	_("septiembre"),
	_("octubre"),
	_("noviembre"),
	_("diciembre"),
]
_WEEKDAYS = [_("lunes"), _("martes"), _("miércoles"), _("jueves"), _("viernes"), _("sábado"), _("domingo")]


def repeatCount() -> int:
	return inputCore.getLastScriptRepeatCount()


def _speakOrSpell(text: str, emptyMessage: str) -> None:
	if not text:
		speech.speakMessage(emptyMessage)
		return
	count = repeatCount()
	if count == 0:
		speech.speakText(text)
	elif count == 1:
		speech.speakSpelling(text)
	else:
		speech.speakSpelling(text, useCharacterDescriptions=True)


def policyBlocks(feature: str) -> bool:
	"""``True`` (y lo dice) si la política o el modo seguro no permiten ``feature``.

	Las órdenes de teclado tienen que respetar lo mismo que el menú, que oculta
	esas entradas: si no, la tecla abriría lo que el administrador ha prohibido.
	"""
	from .config import policy as policyModule

	if policyModule.isAllowed(feature):
		return False
	speech.speakMessage(policyModule.blockedMessage())
	return True


def _toggleSetting(section: str, key: str, onMsg: str, offMsg: str) -> None:
	val = not conf[section][key]
	conf[section][key] = val
	speech.speakMessage(onMsg if val else offMsg)


def _cycle(section: str, key: str, values: list[tuple[str, str]]) -> None:
	cur = conf[section][key]
	keysList = [v for v, _l in values]
	i = keysList.index(cur) if cur in keysList else -1
	nxt = values[(i + 1) % len(values)]
	conf[section][key] = nxt[0]
	speech.speakMessage(nxt[1])


class GlobalCommands(ScriptableObject):
	# ================================================================ entrada
	@script(description=_("Activa o desactiva la ayuda de entrada: al pulsar una tecla se anuncia qué hace sin ejecutarla"), category=CAT_INPUT, gesture="kb:tiresias+1", bypassInputHelp=True, allowInSleepMode=True)
	def script_toggleInputHelp(self, gesture) -> None:
		inputCore.manager.inputHelp = not inputCore.manager.inputHelp
		speech.speakMessage(_("Ayuda de entrada activada") if inputCore.manager.inputHelp else _("Ayuda de entrada desactivada"))

	@script(description=_("La siguiente tecla se envía directamente a la aplicación"), category=CAT_INPUT, gesture="kb:tiresias+f2")
	def script_passNextKeyThrough(self, gesture) -> None:
		inputCore.manager.passNextKey = True
		speech.speakMessage(_("Pasar la siguiente tecla"))

	@script(description=_("Cambia cuándo se anuncian los caracteres escritos"), category=CAT_INPUT, gesture="kb:tiresias+2")
	def script_toggleSpeakTypedCharacters(self, gesture) -> None:
		_cycle("keyboard", "speakTypedCharacters", [("off", _("anunciar caracteres escritos: no")), ("always", _("anunciar caracteres escritos: siempre")), ("editOnly", _("anunciar caracteres escritos: solo en campos de edición"))])

	@script(description=_("Cambia cuándo se anuncian las palabras escritas"), category=CAT_INPUT, gesture="kb:tiresias+3")
	def script_toggleSpeakTypedWords(self, gesture) -> None:
		_cycle("keyboard", "speakTypedWords", [("off", _("anunciar palabras escritas: no")), ("always", _("anunciar palabras escritas: siempre")), ("editOnly", _("anunciar palabras escritas: solo en campos de edición"))])

	@script(description=_("Activa o desactiva el anuncio de las teclas de órdenes"), category=CAT_INPUT, gesture="kb:tiresias+4")
	def script_toggleSpeakCommandKeys(self, gesture) -> None:
		_toggleSetting("keyboard", "speakCommandKeys", _("anunciar teclas de órdenes activado"), _("anunciar teclas de órdenes desactivado"))

	@script(description=_("Activa o desactiva la lectura de cambios dinámicos de contenido"), category=CAT_SPEECH, gesture="kb:tiresias+5")
	def script_toggleReportDynamicContentChanges(self, gesture) -> None:
		_toggleSetting("presentation", "reportDynamicContentChanges", _("anunciar cambios dinámicos activado"), _("anunciar cambios dinámicos desactivado"))

	@script(description=_("Activa o desactiva que el cursor de revisión siga al cursor del sistema"), category=CAT_REVIEW, gesture="kb:tiresias+6")
	def script_toggleCaretMovesReviewCursor(self, gesture) -> None:
		_toggleSetting("reviewCursor", "followCaret", _("la revisión sigue al cursor"), _("la revisión no sigue al cursor"))

	@script(description=_("Cambia el estilo de párrafo: el de la aplicación, un salto de línea o varios saltos de línea"), category=CAT_SYSTEMCARET)
	def script_cycleParagraphStyle(self, gesture) -> None:
		_cycle("documentNavigation", "paragraphStyle", [("application", _("párrafos de la aplicación")), ("singleLineBreak", _("párrafos de un salto de línea")), ("multiLineBreak", _("párrafos de varios saltos de línea"))])

	@script(description=_("Activa o desactiva que el objeto navegador siga al foco"), category=CAT_NAV, gesture="kb:tiresias+7")
	def script_toggleFocusMovesNavigatorObject(self, gesture) -> None:
		_toggleSetting("reviewCursor", "followFocus", _("el navegador sigue al foco"), _("el navegador no sigue al foco"))

	@script(description=_("Activa o desactiva el modo dormir en la aplicación actual (dos veces: lo recuerda para siempre)"), category=CAT_MISC, gestures=("kb(desktop):tiresias+shift+s", "kb(laptop):tiresias+shift+z"), allowInSleepMode=True)
	def script_toggleCurrentAppSleepMode(self, gesture) -> None:
		from .appmodules import handler as appHandler

		focus = api.getFocusObject()
		app = focus.appModule if focus else None
		if app is None:
			return
		if repeatCount() == 1:
			# Segunda pulsación: el estado actual se guarda en la configuración.
			appHandler.setSleepMode(app, app.sleepMode, persist=True)
			inputCore.manager.updateChain()
			msg = _("Modo dormir permanente para {app}") if app.sleepMode else _("{app} ya no tiene modo dormir permanente")
			speech.speakMessage(msg.format(app=app.appName), priority=speech.Priority.NOW)
			return
		appHandler.setSleepMode(app, not app.sleepMode, persist=False)
		inputCore.manager.updateChain()
		speech.speakMessage(_("Modo dormir activado") if app.sleepMode else _("Modo dormir desactivado"))

	# ================================================================ cursor del sistema
	@script(description=_("Lee la línea actual (dos veces: la deletrea; tres: deletreo fonético)"), category=CAT_SYSTEMCARET, gestures=("kb(desktop):tiresias+upArrow", "kb(laptop):tiresias+l"), speakOnDemand=True)
	def script_reportCurrentLine(self, gesture) -> None:
		obj = api.getCaretObject()
		if obj is None:
			return
		try:
			info = obj.makeTextInfo(textinfo.POSITION_CARET)
			info.expand(textinfo.UNIT_LINE)
		except Exception:
			speech.speakMessage(_("sin cursor"))
			return
		_speakOrSpell(info.text.rstrip("\r\n"), _("en blanco"))

	@script(description=_("Lee el texto seleccionado (dos veces: lo deletrea; tres: deletreo fonético; cuatro: lo muestra)"), category=CAT_SYSTEMCARET, gestures=("kb(desktop):tiresias+shift+upArrow", "kb(laptop):tiresias+shift+s"), speakOnDemand=True)
	def script_reportCurrentSelection(self, gesture) -> None:
		obj = api.getCaretObject()
		text = ""
		try:
			info = obj.makeTextInfo(textinfo.POSITION_SELECTION)
			text = info.text
		except Exception:
			pass
		if not text:
			speech.speakMessage(_("sin selección"))
			return
		count = repeatCount()
		if count == 0:
			speech.speakText(_("{text} seleccionado").format(text=text) if len(text) < 2000 else _("{n} caracteres seleccionados").format(n=len(text)))
		elif count == 1:
			speech.speakSpelling(text)
		elif count == 2:
			speech.speakSpelling(text, useCharacterDescriptions=True)
		else:
			# Cuatro pulsaciones: la selección en una ventana navegable.
			from . import gui

			gui.showBrowseableMessage(text, _("Selección"))

	@script(description=_("Lee desde el cursor del sistema hasta el final"), category=CAT_SYSTEMCARET, gestures=("kb(desktop):tiresias+downArrow", "kb(laptop):tiresias+a"), speakOnDemand=True)
	def script_sayAll(self, gesture) -> None:
		sayall.readText(sayall.CURSOR_CARET)

	@script(description=_("Lee el formato del texto en el cursor"), category=CAT_DOC, gesture="kb:tiresias+f", speakOnDemand=True)
	def script_reportFormatting(self, gesture) -> None:
		from . import formatting

		obj = api.getCaretObject()
		try:
			info = obj.makeTextInfo(textinfo.POSITION_CARET)
			parts = formatting.fullDescription(info)
		except Exception:
			parts = []
		if not parts:
			speech.speakMessage(_("sin información de formato"))
			return
		if repeatCount() == 1:
			from . import gui

			gui.showBrowseableMessage("\n".join(parts), _("Formato"))
		else:
			speech.speakMessage(", ".join(parts))

	# ================================================================ foco
	@script(description=_("Anuncia el objeto con foco (dos veces: lo deletrea; tres: lo copia)"), category=CAT_FOCUS, gesture="kb:tiresias+tab", speakOnDemand=True)
	def script_reportCurrentFocus(self, gesture) -> None:
		focus = api.getFocusObject()
		if focus is None:
			speech.speakMessage(_("sin foco"))
			return
		count = repeatCount()
		if count == 0:
			presentation.speakObject(focus, reason=presentation.Reason.QUERY)
		elif count == 1:
			from . import labels

			speech.speakSpelling(labels.displayName(focus))
		else:
			api.copyToClip(" ".join(presentation.getObjectSpeech(focus)), notify=True)

	@script(description=_("Lee el título de la ventana (dos veces: lo deletrea; tres: lo copia)"), category=CAT_FOCUS, gesture="kb:tiresias+t", speakOnDemand=True)
	def script_title(self, gesture) -> None:
		fg = api.getForegroundObject()
		title = fg.name if fg else winapi.getWindowText(winapi.getForegroundWindow())
		count = repeatCount()
		if count == 2:
			api.copyToClip(title or "", notify=True)
			return
		_speakOrSpell(title or "", _("sin título"))

	@script(description=_("Lee todos los controles de la ventana activa"), category=CAT_FOCUS, gesture="kb:tiresias+b", speakOnDemand=True)
	def script_speakForeground(self, gesture) -> None:
		fg = api.getForegroundObject()
		if fg is not None:
			speech.speakText(fg.name)
			sayall.readObjects(fg)

	@script(description=_("Lee la barra de estado (dos veces: la deletrea; tres: la copia)"), category=CAT_FOCUS, gestures=("kb(desktop):tiresias+end", "kb(laptop):tiresias+shift+end"), speakOnDemand=True)
	def script_reportStatusLine(self, gesture) -> None:
		text = api.getStatusBarTextFromApp()
		if text is None:
			bar = api.getStatusBar()
			if bar is None:
				speech.speakMessage(_("no se encontró la barra de estado"))
				return
			text = api.statusBarText(bar)
		if repeatCount() == 2:
			api.copyToClip(text, notify=True)
			return
		_speakOrSpell(text, _("barra de estado vacía"))

	@script(description=_("Anuncia la tecla de acceso del objeto con foco"), category=CAT_FOCUS, gestures=("kb(desktop):shift+numpad2", "kb(laptop):tiresias+control+shift+."), speakOnDemand=True)
	def script_reportFocusObjectAccelerator(self, gesture) -> None:
		focus = api.getFocusObject()
		ks = focus.keyboardShortcut if focus else ""
		speech.speakMessage(ks or _("sin tecla de acceso"))

	@script(description=_("Anuncia el destino del enlace en el cursor o foco"), category=CAT_TOOLS, gesture="kb:tiresias+k", speakOnDemand=True)
	def script_reportLinkDestination(self, gesture) -> None:
		obj = api.getNavigatorObject()
		caret = api.getCaretObject()
		target = None
		if caret is not None and hasattr(caret, "buffer"):
			try:
				target = caret.makeTextInfo(textinfo.POSITION_CARET).getEnclosingObject()
			except Exception:
				target = None
		target = target or obj
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
			pass
		if not url:
			speech.speakMessage(_("destino del enlace desconocido"))
			return
		if repeatCount() == 1:
			from . import gui

			gui.showBrowseableMessage(url, _("Destino del enlace"))
		else:
			speech.speakText(url)

	# ================================================================ información
	@script(description=_("Anuncia la hora (dos veces: la fecha)"), category=CAT_MISC, gesture="kb:tiresias+f12", speakOnDemand=True)
	def script_dateTime(self, gesture) -> None:
		now = datetime.datetime.now()
		if repeatCount() == 0:
			speech.speakMessage(now.strftime("%H:%M"))
		else:
			speech.speakMessage(f"{_WEEKDAYS[now.weekday()]}, {now.day} de {_MONTHS[now.month - 1]} de {now.year}")

	@script(description=_("Anuncia el estado de la batería"), category=CAT_MISC, gesture="kb:tiresias+shift+b", speakOnDemand=True)
	def script_sayBatteryStatus(self, gesture) -> None:
		s = winapi.getPowerStatus()
		if s is None or (s.BatteryFlag & 0xFF) == 128:
			speech.speakMessage(_("sin batería"))
			return
		parts = []
		pct = s.BatteryLifePercent & 0xFF
		if pct != 255:
			parts.append(_("batería al {pct} por ciento").format(pct=pct))
		if s.ACLineStatus == 1:
			parts.append(_("conectado a la corriente"))
		elif s.BatteryLifeTime != 0xFFFFFFFF:
			h, m = divmod(s.BatteryLifeTime // 60, 60)
			parts.append(_("quedan {h} horas y {m} minutos").format(h=h, m=m))
		speech.speakMessage(", ".join(parts))

	@script(description=_("Lee el texto del portapapeles (dos veces: lo deletrea)"), category=CAT_TOOLS, gesture="kb:tiresias+c", speakOnDemand=True)
	def script_reportClipboardText(self, gesture) -> None:
		text = api.getClipData()
		if not text:
			speech.speakMessage(_("El portapapeles no contiene texto"))
			return
		if len(text) > 1000 and repeatCount() == 0:
			speech.speakMessage(_("El portapapeles contiene {n} caracteres. {start}").format(n=len(text), start=text[:300]))
			return
		_speakOrSpell(text, "")

	@script(description=_("Anuncia el nombre de la aplicación y de su módulo"), category=CAT_TOOLS, gesture="kb:tiresias+control+f1", speakOnDemand=True)
	def script_reportAppModuleInfo(self, gesture) -> None:
		focus = api.getFocusObject()
		app = focus.appModule if focus else None
		if app is None:
			speech.speakMessage(_("sin aplicación"))
			return
		mod = type(app).__module__
		modText = _("módulo {name}").format(name=mod.rsplit(".", 1)[-1]) if mod != "tiresias.appmodules" else _("sin módulo específico")
		speech.speakMessage(f"{app.productName} {app.productVersion}, {app.appName}.exe, {modText}")

	@script(description=_("Registra información del objeto navegador para desarrolladores (dos veces: la muestra)"), category=CAT_TOOLS, gesture="kb:tiresias+f1")
	def script_navigatorObjectDevInfo(self, gesture) -> None:
		obj = api.getNavigatorObject()
		if obj is None:
			return
		info = "\n".join(obj.devInfo)
		log.info("Información del objeto navegador:\n%s", info)
		from . import gui

		gui.showBrowseableMessage(info, _("Información para desarrolladores"))

	# ================================================================ voz
	@script(description=_("Cambia el modo de voz: activada, a demanda, pitidos, desactivada"), category=CAT_SPEECH, gesture="kb:tiresias+s", allowInSleepMode=True)
	def script_speechMode(self, gesture) -> None:
		# Se saltan los modos excluidos en las opciones de voz.
		nxt = speech.nextSpeechMode()
		speech.setSpeechMode(nxt)
		speech.speak([speech.SPEECH_MODE_LABELS[nxt]], force=True)

	@script(description=_("Cambia el nivel de lectura de símbolos y puntuación"), category=CAT_SPEECH, gesture="kb:tiresias+p")
	def script_cycleSpeechSymbolLevel(self, gesture) -> None:
		from .speech.symbols import LEVEL_NAMES, SPEECH_LEVELS

		cur = conf["speech"]["symbolLevel"]
		i = SPEECH_LEVELS.index(cur) if cur in SPEECH_LEVELS else 0
		nxt = SPEECH_LEVELS[(i + 1) % len(SPEECH_LEVELS)]
		conf["speech"]["symbolLevel"] = nxt
		speech.speakMessage(_("nivel de símbolos {level}").format(level=LEVEL_NAMES[nxt]))

	@script(description=_("Repite lo último que se dijo (dos veces: lo muestra)"), category=CAT_SPEECH, gesture="kb:tiresias+x", speakOnDemand=True)
	def script_repeatLastSpokenInformation(self, gesture) -> None:
		history = speech.getHistory()
		# Se descarta lo dicho por esta misma orden.
		text = history[-1][1] if history else ""
		if repeatCount() == 1 and len(history) >= 2:
			from . import gui

			gui.showBrowseableMessage(history[-2][1], _("Lo último dicho"))
			return
		if text:
			speech.speakText(text)

	@script(description=_("Copia al portapapeles lo último que se dijo"), category=CAT_SPEECH, gesture="kb:tiresias+control+x")
	def script_copyLastSpokenInformation(self, gesture) -> None:
		history = speech.getHistory()
		if history:
			api.copyToClip(history[-1][1], notify=True)

	@script(description=_("Abre el historial de voz (buscar, copiar, exportar)"), category=CAT_SPEECH, gesture="kb:tiresias+alt+x")
	def script_speechHistory(self, gesture) -> None:
		from . import gui

		gui.showSpeechHistory()

	# Anillo de ajustes de voz
	@script(description=_("Aumenta el ajuste de voz actual"), category=CAT_SPEECH, gestures=("kb(desktop):tiresias+control+upArrow", "kb(laptop):tiresias+shift+control+upArrow"))
	def script_increaseSynthSetting(self, gesture) -> None:
		from .synth import ring

		speech.speakMessage(ring.change(1))

	@script(description=_("Disminuye el ajuste de voz actual"), category=CAT_SPEECH, gestures=("kb(desktop):tiresias+control+downArrow", "kb(laptop):tiresias+control+shift+downArrow"))
	def script_decreaseSynthSetting(self, gesture) -> None:
		from .synth import ring

		speech.speakMessage(ring.change(-1))

	@script(description=_("Aumenta mucho el ajuste de voz actual"), category=CAT_SPEECH, gestures=("kb(desktop):tiresias+control+pageUp", "kb(laptop):tiresias+shift+control+pageUp"))
	def script_increaseLargeSynthSetting(self, gesture) -> None:
		from .synth import ring

		speech.speakMessage(ring.change(1, large=True))

	@script(description=_("Disminuye mucho el ajuste de voz actual"), category=CAT_SPEECH, gestures=("kb(desktop):tiresias+control+pageDown", "kb(laptop):tiresias+control+shift+pageDown"))
	def script_decreaseLargeSynthSetting(self, gesture) -> None:
		from .synth import ring

		speech.speakMessage(ring.change(-1, large=True))

	@script(description=_("Pasa al siguiente ajuste de voz del anillo"), category=CAT_SPEECH, gestures=("kb(desktop):tiresias+control+rightArrow", "kb(laptop):tiresias+shift+control+rightArrow"))
	def script_nextSynthSetting(self, gesture) -> None:
		from .synth import ring

		ring.move(1)
		speech.speakMessage(ring.describe())

	@script(description=_("Pasa al ajuste de voz anterior del anillo"), category=CAT_SPEECH, gestures=("kb(desktop):tiresias+control+leftArrow", "kb(laptop):tiresias+shift+control+leftArrow"))
	def script_previousSynthSetting(self, gesture) -> None:
		from .synth import ring

		ring.move(-1)
		speech.speakMessage(ring.describe())

	# ================================================================ navegación de objetos
	def _setNavigator(self, obj, notFoundMsg: str) -> None:
		if obj is None:
			speech.speakMessage(notFoundMsg)
			tones.playSound("boundary")
			return
		api.setNavigatorObject(obj)
		# Tono de coordenadas del objeto (#2559), antes de hablar.
		from . import mouse

		mouse.navigatorAudioCoordinates(obj)
		presentation.speakObject(obj, reason=presentation.Reason.QUERY)
		from . import vision

		vision.handler.onNavigatorChange(obj)

	def _simple(self) -> bool:
		return conf["reviewCursor"]["simpleReviewMode"]

	@script(description=_("Anuncia el objeto navegador (dos veces: lo deletrea; tres: lo copia)"), category=CAT_NAV, gestures=("kb(desktop):tiresias+numpad5", "kb(laptop):tiresias+shift+o"), speakOnDemand=True)
	def script_navigatorObject_current(self, gesture) -> None:
		obj = api.getNavigatorObject()
		if obj is None:
			speech.speakMessage(_("sin objeto navegador"))
			return
		count = repeatCount()
		if count == 0:
			presentation.speakObject(obj, reason=presentation.Reason.QUERY)
		elif count == 1:
			from . import labels

			speech.speakSpelling(labels.displayName(obj) or obj.value or "")
		else:
			api.copyToClip(" ".join(presentation.getObjectSpeech(obj)), notify=True)

	@script(description=_("Mueve el objeto navegador a su contenedor"), category=CAT_NAV, gestures=("kb(desktop):tiresias+numpad8", "kb(laptop):tiresias+shift+upArrow"))
	def script_navigatorObject_parent(self, gesture) -> None:
		obj = api.getNavigatorObject()
		if obj is None:
			return
		parent = obj.simpleParent if self._simple() else obj.parent
		self._setNavigator(parent, _("sin contenedor"))

	@script(description=_("Mueve el objeto navegador al siguiente objeto"), category=CAT_NAV, gestures=("kb(desktop):tiresias+numpad6", "kb(laptop):tiresias+shift+rightArrow"))
	def script_navigatorObject_next(self, gesture) -> None:
		obj = api.getNavigatorObject()
		if obj is None:
			return
		nxt = obj.simpleNext if self._simple() else obj.next
		self._setNavigator(nxt, _("sin siguiente"))

	@script(description=_("Mueve el objeto navegador al objeto anterior"), category=CAT_NAV, gestures=("kb(desktop):tiresias+numpad4", "kb(laptop):tiresias+shift+leftArrow"))
	def script_navigatorObject_previous(self, gesture) -> None:
		obj = api.getNavigatorObject()
		if obj is None:
			return
		prev = obj.simplePrevious if self._simple() else obj.previous
		self._setNavigator(prev, _("sin anterior"))

	@script(description=_("Mueve el objeto navegador a su primer hijo"), category=CAT_NAV, gestures=("kb(desktop):tiresias+numpad2", "kb(laptop):tiresias+shift+downArrow"))
	def script_navigatorObject_firstChild(self, gesture) -> None:
		obj = api.getNavigatorObject()
		if obj is None:
			return
		child = obj.simpleFirstChild if self._simple() else obj.firstChild
		self._setNavigator(child, _("sin hijos"))

	def _flow(self, direction: int):
		obj = api.getNavigatorObject()
		if obj is None:
			return None
		simple = self._simple()
		if direction > 0:
			child = obj.simpleFirstChild if simple else obj.firstChild
			if child is not None:
				return child
			cur = obj
			while cur is not None:
				nxt = cur.simpleNext if simple else cur.next
				if nxt is not None:
					return nxt
				cur = cur.simpleParent if simple else cur.parent
			return None
		prev = obj.simplePrevious if simple else obj.previous
		if prev is None:
			return obj.simpleParent if simple else obj.parent
		# Último descendiente del anterior.
		cur = prev
		for _i in range(50):
			last = None
			child = cur.simpleFirstChild if simple else cur.firstChild
			while child is not None:
				last = child
				child = child.simpleNext if simple else child.next
			if last is None:
				break
			cur = last
		return cur

	@script(description=_("Mueve el navegador al siguiente objeto en orden lineal"), category=CAT_NAV, gestures=("kb(desktop):tiresias+numpad3", "kb(laptop):shift+tiresias+]", "kb(laptop):shift+tiresias+plus"))
	def script_navigatorObject_nextInFlow(self, gesture) -> None:
		self._setNavigator(self._flow(1), _("sin siguiente"))

	@script(description=_("Mueve el navegador al objeto anterior en orden lineal"), category=CAT_NAV, gestures=("kb(desktop):tiresias+numpad9", "kb(laptop):shift+tiresias+[", "kb(laptop):shift+tiresias+`"))
	def script_navigatorObject_previousInFlow(self, gesture) -> None:
		self._setNavigator(self._flow(-1), _("sin anterior"))

	@script(description=_("Lleva el objeto navegador al foco"), category=CAT_NAV, gestures=("kb(desktop):tiresias+numpadMinus", "kb(laptop):tiresias+backspace"))
	def script_navigatorObject_toFocus(self, gesture) -> None:
		focus = api.getFocusObject()
		if focus is None:
			return
		api.setNavigatorObject(focus, isFocus=True)
		caret = api.getCaretObject()
		try:
			if caret is not None:
				api.setReviewPosition(caret.makeTextInfo(textinfo.POSITION_CARET))
		except Exception:
			pass
		from . import mouse

		mouse.navigatorAudioCoordinates(focus)  # #2559
		speech.speakMessage(_("al foco"))
		presentation.speakObject(focus, reason=presentation.Reason.QUERY)

	@script(description=_("Lleva el foco al objeto navegador (dos veces: también el cursor)"), category=CAT_NAV, gestures=("kb(desktop):tiresias+shift+numpadMinus", "kb(laptop):tiresias+shift+backspace"))
	def script_navigatorObject_moveFocus(self, gesture) -> None:
		obj = api.getNavigatorObject()
		if obj is None:
			return
		if repeatCount() == 0:
			obj.setFocus()
			speech.speakMessage(_("foco movido"))
		else:
			info = api.getReviewPosition()
			try:
				info.updateCaret()
				speech.speakMessage(_("cursor movido"))
			except Exception:
				speech.speakMessage(_("no se puede mover el cursor"))

	@script(description=_("Activa el objeto navegador (pulsar, abrir...)"), category=CAT_NAV, gestures=("kb(desktop):tiresias+numpadEnter", "kb(laptop):tiresias+enter"))
	def script_review_activate(self, gesture) -> None:
		obj = api.getNavigatorObject()
		if obj is None:
			return
		action = obj.actionName
		if obj.doAction():
			speech.speakMessage(action)
		else:
			speech.speakMessage(_("sin acción"))

	@script(description=_("Anuncia tamaño y posición del objeto navegador"), category=CAT_NAV, gestures=("kb(desktop):tiresias+shift+numpadDelete", "kb(laptop):tiresias+shift+delete"), speakOnDemand=True)
	def script_navigatorObject_currentDimensions(self, gesture) -> None:
		obj = api.getNavigatorObject()
		loc = obj.location if obj else None
		if not loc:
			speech.speakMessage(_("sin ubicación"))
			return
		x, y, w, h = loc
		sw = winapi.user32.GetSystemMetrics(0) or 1
		sh = winapi.user32.GetSystemMetrics(1) or 1
		speech.speakMessage(_("{w} por {h} píxeles, a {left} por ciento del borde izquierdo y {top} por ciento del borde superior").format(w=w, h=h, left=round(100 * x / sw), top=round(100 * y / sh)))

	@script(description=_("Anuncia la posición del cursor del sistema en pantalla"), category=CAT_SYSTEMCARET, gestures=("kb(desktop):tiresias+numpadDelete", "kb(laptop):tiresias+delete"), speakOnDemand=True)
	def script_caretPos_currentDimensions(self, gesture) -> None:
		caret = api.getCaretObject()
		try:
			pt = caret.makeTextInfo(textinfo.POSITION_CARET).pointAtStart
		except Exception:
			pt = None
		if pt is None:
			speech.speakMessage(_("posición desconocida"))
			return
		sw = winapi.user32.GetSystemMetrics(0) or 1
		sh = winapi.user32.GetSystemMetrics(1) or 1
		speech.speakMessage(_("a {left} por ciento del borde izquierdo y {top} por ciento del borde superior").format(left=round(100 * pt.x / sw), top=round(100 * pt.y / sh)))

	@script(description=_("Etiqueta el objeto navegador con un nombre personalizado"), category=CAT_TOOLS, gesture="kb:tiresias+control+shift+l")
	def script_labelNavigatorObject(self, gesture) -> None:
		from . import gui, labels, queue_handler

		obj = api.getNavigatorObject()
		if obj is None:
			return
		current = labels.getLabel(obj) or ""

		def done(text: str) -> None:
			def apply() -> None:
				if labels.setLabel(obj, text.strip() or None):
					speech.speakMessage(_("etiqueta guardada") if text.strip() else _("etiqueta eliminada"))
				else:
					speech.speakMessage(_("no se puede etiquetar este objeto"))

			queue_handler.queueFunction(apply)

		gui.askText(_("Etiqueta personalizada"), _("Nombre para este control (vacío para quitar la etiqueta):"), current, done)

	# ================================================================ revisión
	def _reviewMove(self, unit: str, direction: int, speakUnit: str | None = None) -> None:
		info = api.getReviewPosition()
		if info is None:
			return
		info = info.copy()
		try:
			info.expand(unit)
			info.collapse()
			if direction:
				moved = info.move(unit, direction)
				if not moved:
					# Límite con dirección (#13612).
					tones.playSound("boundaryStart" if direction < 0 else "boundaryEnd")
					speech.speakMessage(_("inicio") if direction < 0 else _("final"))
		except Exception:
			log.debug("Error moviendo la revisión", exc_info=True)
			return
		api.setReviewPosition(info)
		self._reviewTone(info)
		presentation.speakTextInfo(info, speakUnit or unit, reason=presentation.Reason.REVIEW)

	@staticmethod
	def _reviewTone(info) -> None:
		"""Tono de coordenadas del cursor de revisión (#2559), si está activado."""
		from . import mouse

		mouse.reviewAudioCoordinates(info)

	def _reviewTo(self, which: str) -> None:
		info = api.getReviewPosition()
		if info is None:
			return
		info = info.copy()
		if which == "top":
			info.expand(textinfo.UNIT_STORY)
			info.collapse()
			unit = textinfo.UNIT_LINE
		elif which == "bottom":
			info.expand(textinfo.UNIT_STORY)
			info.collapse(end=True)
			info.move(textinfo.UNIT_CHARACTER, -1)
			unit = textinfo.UNIT_LINE
		elif which == "lineStart":
			info.expand(textinfo.UNIT_LINE)
			info.collapse()
			unit = textinfo.UNIT_CHARACTER
		else:
			info.expand(textinfo.UNIT_LINE)
			info.collapse(end=True)
			info.move(textinfo.UNIT_CHARACTER, -1)
			c = info.copy()
			c.expand(textinfo.UNIT_CHARACTER)
			if c.text in ("\n", "\r"):
				info.move(textinfo.UNIT_CHARACTER, -1)
			unit = textinfo.UNIT_CHARACTER
		api.setReviewPosition(info)
		self._reviewTone(info)
		presentation.speakTextInfo(info, unit, reason=presentation.Reason.REVIEW)

	def _reviewCurrent(self, unit: str) -> None:
		info = api.getReviewPosition()
		if info is None:
			return
		c = info.copy()
		c.expand(unit)
		count = repeatCount()
		if count == 0:
			presentation.speakTextInfo(info, unit, reason=presentation.Reason.REVIEW)
		elif unit == textinfo.UNIT_CHARACTER:
			ch = c.text[:1]
			if count == 1:
				speech.speakSpelling(ch, useCharacterDescriptions=True)
			else:
				speech.speakMessage(_("{dec}, hexadecimal {hex}").format(dec=ord(ch), hex=f"{ord(ch):X}") if ch else _("en blanco"))
		else:
			speech.speakSpelling(c.text.rstrip("\r\n"), useCharacterDescriptions=count >= 2)

	@script(description=_("Revisión: primera línea"), category=CAT_REVIEW, gestures=("kb(desktop):shift+numpad7", "kb(laptop):tiresias+control+home"))
	def script_review_top(self, gesture) -> None:
		self._reviewTo("top")

	@script(description=_("Revisión: línea anterior"), category=CAT_REVIEW, gestures=("kb(desktop):numpad7", "kb(laptop):tiresias+upArrow"))
	def script_review_previousLine(self, gesture) -> None:
		self._reviewMove(textinfo.UNIT_LINE, -1)

	@script(description=_("Revisión: línea actual (dos veces: deletrea)"), category=CAT_REVIEW, gestures=("kb(desktop):numpad8", "kb(laptop):tiresias+shift+."), speakOnDemand=True)
	def script_review_currentLine(self, gesture) -> None:
		self._reviewCurrent(textinfo.UNIT_LINE)

	@script(description=_("Revisión: línea siguiente"), category=CAT_REVIEW, gestures=("kb(desktop):numpad9", "kb(laptop):tiresias+downArrow"))
	def script_review_nextLine(self, gesture) -> None:
		self._reviewMove(textinfo.UNIT_LINE, 1)

	@script(description=_("Revisión: última línea"), category=CAT_REVIEW, gestures=("kb(desktop):shift+numpad9", "kb(laptop):tiresias+control+end"))
	def script_review_bottom(self, gesture) -> None:
		self._reviewTo("bottom")

	@script(description=_("Revisión: página anterior"), category=CAT_REVIEW, gestures=("kb(desktop):tiresias+pageUp", "kb(laptop):tiresias+shift+pageUp"))
	def script_review_previousPage(self, gesture) -> None:
		self._reviewMove(textinfo.UNIT_PAGE, -1, textinfo.UNIT_LINE)

	@script(description=_("Revisión: página siguiente"), category=CAT_REVIEW, gestures=("kb(desktop):tiresias+pageDown", "kb(laptop):tiresias+shift+pageDown"))
	def script_review_nextPage(self, gesture) -> None:
		self._reviewMove(textinfo.UNIT_PAGE, 1, textinfo.UNIT_LINE)

	@script(description=_("Revisión: palabra anterior"), category=CAT_REVIEW, gestures=("kb(desktop):numpad4", "kb(laptop):tiresias+control+leftArrow"))
	def script_review_previousWord(self, gesture) -> None:
		self._reviewMove(textinfo.UNIT_WORD, -1)

	@script(description=_("Revisión: palabra actual (dos veces: deletrea)"), category=CAT_REVIEW, gestures=("kb(desktop):numpad5", "kb(laptop):tiresias+control+."), speakOnDemand=True)
	def script_review_currentWord(self, gesture) -> None:
		self._reviewCurrent(textinfo.UNIT_WORD)

	@script(description=_("Revisión: palabra siguiente"), category=CAT_REVIEW, gestures=("kb(desktop):numpad6", "kb(laptop):tiresias+control+rightArrow"))
	def script_review_nextWord(self, gesture) -> None:
		self._reviewMove(textinfo.UNIT_WORD, 1)

	@script(description=_("Revisión: inicio de línea"), category=CAT_REVIEW, gestures=("kb(desktop):shift+numpad1", "kb(laptop):tiresias+home"))
	def script_review_startOfLine(self, gesture) -> None:
		self._reviewTo("lineStart")

	@script(description=_("Revisión: carácter anterior"), category=CAT_REVIEW, gestures=("kb(desktop):numpad1", "kb(laptop):tiresias+leftArrow"))
	def script_review_previousCharacter(self, gesture) -> None:
		self._reviewMove(textinfo.UNIT_CHARACTER, -1)

	@script(description=_("Revisión: carácter actual (dos veces: fonético; tres: código)"), category=CAT_REVIEW, gestures=("kb(desktop):numpad2", "kb(laptop):tiresias+."), speakOnDemand=True)
	def script_review_currentCharacter(self, gesture) -> None:
		self._reviewCurrent(textinfo.UNIT_CHARACTER)

	@script(description=_("Revisión: carácter siguiente"), category=CAT_REVIEW, gestures=("kb(desktop):numpad3", "kb(laptop):tiresias+rightArrow"))
	def script_review_nextCharacter(self, gesture) -> None:
		self._reviewMove(textinfo.UNIT_CHARACTER, 1)

	@script(description=_("Revisión: final de línea"), category=CAT_REVIEW, gestures=("kb(desktop):shift+numpad3", "kb(laptop):tiresias+end"))
	def script_review_endOfLine(self, gesture) -> None:
		self._reviewTo("lineEnd")

	@script(description=_("Lee desde el cursor de revisión hasta el final"), category=CAT_REVIEW, gestures=("kb(desktop):numpadPlus", "kb(laptop):tiresias+shift+a"), speakOnDemand=True)
	def script_review_sayAll(self, gesture) -> None:
		sayall.readText(sayall.CURSOR_REVIEW)

	@script(description=_("Cambia al modo de revisión siguiente (objeto, documento, pantalla)"), category=CAT_REVIEW, gestures=("kb(desktop):tiresias+numpad7", "kb(laptop):tiresias+pageUp"))
	def script_reviewMode_next(self, gesture) -> None:
		mode = review.nextMode(1)
		speech.speakMessage(review.MODE_LABELS[mode] if mode else _("no hay modo siguiente"))

	@script(description=_("Cambia al modo de revisión anterior"), category=CAT_REVIEW, gestures=("kb(desktop):tiresias+numpad1", "kb(laptop):tiresias+pageDown"))
	def script_reviewMode_previous(self, gesture) -> None:
		mode = review.nextMode(-1)
		speech.speakMessage(review.MODE_LABELS[mode] if mode else _("no hay modo anterior"))

	_copyStart = None

	@script(description=_("Marca el inicio del texto a copiar en el cursor de revisión"), category=CAT_REVIEW, gesture="kb:tiresias+f9")
	def script_review_markStartForCopy(self, gesture) -> None:
		info = api.getReviewPosition()
		if info is None:
			return
		GlobalCommands._copyStart = info.copy()
		speech.speakMessage(_("inicio marcado"))

	@script(description=_("Copia desde la marca hasta el cursor de revisión (dos veces: selecciona)"), category=CAT_REVIEW, gesture="kb:tiresias+f10")
	def script_review_copy(self, gesture) -> None:
		start = GlobalCommands._copyStart
		end = api.getReviewPosition()
		if start is None or end is None:
			speech.speakMessage(_("no hay marca de inicio"))
			return
		try:
			r = start.copy()
			endChar = end.copy()
			endChar.expand(textinfo.UNIT_CHARACTER)
			r.setEndPoint(endChar, "endToEnd")
			if repeatCount() == 1:
				r.updateSelection()
				speech.speakMessage(_("seleccionado"))
				return
			text = r.text
		except Exception:
			speech.speakMessage(_("no se pudo copiar"))
			return
		if text:
			api.copyToClip(text, notify=True)
		else:
			speech.speakMessage(_("nada que copiar"))

	# ================================================================ ratón
	@script(description=_("Clic izquierdo en la posición del ratón"), category=CAT_MOUSE, gestures=("kb:numpadDivide", "kb(laptop):tiresias+[", "kb(laptop):tiresias+`"))
	def script_leftMouseClick(self, gesture) -> None:
		from . import mouse

		speech.speakMessage(_("clic izquierdo"))
		mouse.click()

	@script(description=_("Clic derecho en la posición del ratón"), category=CAT_MOUSE, gestures=("kb:numpadMultiply", "kb(laptop):tiresias+]", "kb(laptop):tiresias+plus"))
	def script_rightMouseClick(self, gesture) -> None:
		from . import mouse

		speech.speakMessage(_("clic derecho"))
		mouse.click(button="right")

	@script(description=_("Bloquea o desbloquea el botón izquierdo"), category=CAT_MOUSE, gestures=("kb:shift+numpadDivide", "kb(laptop):tiresias+control+[", "kb(laptop):tiresias+control+`"))
	def script_toggleLeftMouseButton(self, gesture) -> None:
		from . import mouse

		speech.speakMessage(_("botón izquierdo bloqueado") if mouse.toggleLock("left") else _("botón izquierdo desbloqueado"))

	@script(description=_("Bloquea o desbloquea el botón derecho"), category=CAT_MOUSE, gestures=("kb:shift+numpadMultiply", "kb(laptop):tiresias+control+]", "kb(laptop):tiresias+control+plus"))
	def script_toggleRightMouseButton(self, gesture) -> None:
		from . import mouse

		speech.speakMessage(_("botón derecho bloqueado") if mouse.toggleLock("right") else _("botón derecho desbloqueado"))

	@script(description=_("Mueve el ratón al objeto navegador"), category=CAT_MOUSE, gestures=("kb:tiresias+numpadDivide", "kb(laptop):tiresias+shift+m"))
	def script_moveMouseToNavigatorObject(self, gesture) -> None:
		from . import mouse

		info = api.getReviewPosition()
		pt = None
		try:
			pt = info.pointAtStart if info else None
		except Exception:
			pt = None
		if pt is not None:
			mouse.moveTo(pt.x, pt.y)
			speech.speakMessage(_("ratón movido"))
			return
		obj = api.getNavigatorObject()
		loc = obj.location if obj else None
		if not loc:
			speech.speakMessage(_("sin ubicación"))
			return
		x, y, w, h = loc
		mouse.moveTo(x + w // 2, y + h // 2)
		speech.speakMessage(_("ratón movido"))

	@script(description=_("Lleva el objeto navegador al objeto bajo el ratón"), category=CAT_MOUSE, gestures=("kb:tiresias+numpadMultiply", "kb(laptop):tiresias+shift+n"))
	def script_moveNavigatorObjectToMouse(self, gesture) -> None:
		from .objects.uia import getObjectFromPoint

		x, y = winapi.getCursorPos()
		obj = getObjectFromPoint(x, y)
		self._setNavigator(obj, _("nada bajo el ratón"))

	@script(description=_("Activa o desactiva el seguimiento del ratón"), category=CAT_MOUSE, gesture="kb:tiresias+alt+m")
	def script_toggleMouseTracking(self, gesture) -> None:
		_toggleSetting("mouse", "enableMouseTracking", _("seguimiento del ratón activado"), _("seguimiento del ratón desactivado"))

	# ================================================================ presentación
	@script(description=_("Cambia la forma de anunciar las barras de progreso"), category=CAT_MISC, gesture="kb:tiresias+u")
	def script_toggleProgressBarOutput(self, gesture) -> None:
		_cycle("presentation", "progressBarOutputMode", [("off", _("barras de progreso: no anunciar")), ("speak", _("barras de progreso: voz")), ("beep", _("barras de progreso: pitidos")), ("both", _("barras de progreso: voz y pitidos"))])

	# ================================================================ configuración
	@script(description=_("Muestra el menú de Tiresias"), category=CAT_CONFIG, gestures=("kb:tiresias+m", "kb:tiresias+applications"), allowInSleepMode=True)
	def script_showGui(self, gesture) -> None:
		from . import gui

		gui.showMenu()

	@script(description=_("Cierra Tiresias"), category=CAT_CONFIG, gesture="kb:tiresias+q", allowInSleepMode=True)
	def script_quit(self, gesture) -> None:
		from . import gui

		gui.askQuit()

	@script(description=_("Abre las opciones generales"), category=CAT_CONFIG, gesture="kb:tiresias+control+g")
	def script_activateGeneralSettingsDialog(self, gesture) -> None:
		from . import gui

		gui.showSettings("general")

	@script(description=_("Abre la selección de sintetizador"), category=CAT_CONFIG, gesture="kb:tiresias+control+s")
	def script_activateSynthesizerDialog(self, gesture) -> None:
		from . import gui

		gui.showSynthSelection()

	@script(description=_("Abre las opciones de voz"), category=CAT_CONFIG, gesture="kb:tiresias+control+v")
	def script_activateVoiceDialog(self, gesture) -> None:
		from . import gui

		gui.showSettings("speech")

	@script(description=_("Abre las opciones de braille"), category=CAT_CONFIG, gesture="kb:tiresias+control+a")
	def script_activateBrailleSettingsDialog(self, gesture) -> None:
		from . import gui

		gui.showSettings("braille")

	@script(description=_("Abre el diálogo Seleccionar línea braille"), category=CAT_CONFIG)
	def script_activateBrailleDisplayDialog(self, gesture) -> None:
		from .gui import braille_display_dialog, runOnGui

		runOnGui(braille_display_dialog.showDialog)

	@script(description=_("Abre las opciones de audio"), category=CAT_CONFIG, gesture="kb:tiresias+control+u")
	def script_activateAudioSettingsDialog(self, gesture) -> None:
		from . import gui

		gui.showSettings("audio")

	@script(description=_("Abre las opciones de teclado"), category=CAT_CONFIG, gesture="kb:tiresias+control+k")
	def script_activateKeyboardSettingsDialog(self, gesture) -> None:
		from . import gui

		gui.showSettings("keyboard")

	@script(description=_("Abre las opciones de ratón"), category=CAT_CONFIG, gesture="kb:tiresias+control+m")
	def script_activateMouseSettingsDialog(self, gesture) -> None:
		from . import gui

		gui.showSettings("mouse")

	@script(description=_("Abre las opciones de presentación de objetos"), category=CAT_CONFIG, gesture="kb:tiresias+control+o")
	def script_activateObjectPresentationDialog(self, gesture) -> None:
		from . import gui

		gui.showSettings("presentation")

	@script(description=_("Abre las opciones del modo exploración"), category=CAT_CONFIG, gesture="kb:tiresias+control+b")
	def script_activateBrowseModeDialog(self, gesture) -> None:
		from . import gui

		gui.showSettings("browseMode")

	@script(description=_("Abre las opciones de formato de documento"), category=CAT_CONFIG, gesture="kb:tiresias+control+d")
	def script_activateDocumentFormattingDialog(self, gesture) -> None:
		from . import gui

		gui.showSettings("documentFormatting")

	@script(description=_("Abre los perfiles de configuración"), category=CAT_CONFIG, gesture="kb:tiresias+control+p")
	def script_activateConfigProfilesDialog(self, gesture) -> None:
		from . import gui

		gui.showProfiles()

	@script(description=_("Guarda la configuración"), category=CAT_CONFIG, gesture="kb:tiresias+control+c")
	def script_saveConfiguration(self, gesture) -> None:
		from . import synth

		if policyBlocks("saveConfiguration"):
			return
		synth.saveCurrentSettings()
		try:
			conf.save()
			speech.speakMessage(_("Configuración guardada"))
		except OSError:
			speech.speakMessage(_("No se pudo guardar la configuración"))

	@script(description=_("Vuelve a la configuración guardada (tres veces: valores de fábrica)"), category=CAT_CONFIG, gesture="kb:tiresias+control+r")
	def script_revertConfiguration(self, gesture) -> None:
		from . import core

		if repeatCount() == 0:
			conf.revertToSaved()
			core.applyConfiguration()
			speech.speakMessage(_("Configuración restaurada a la última guardada"))
		elif repeatCount() == 2:
			if policyBlocks("factoryReset"):
				return
			conf.resetToFactoryDefaults()
			core.applyConfiguration()
			speech.speakMessage(_("Configuración restablecida a los valores de fábrica"))

	@script(description=_("Abre la consola de Python (para desarrolladores)"), category=CAT_TOOLS, gesture="kb:tiresias+control+z")
	def script_activatePythonConsole(self, gesture) -> None:
		from . import gui

		if policyBlocks("pythonConsole"):
			return
		gui.showPythonConsole()

	@script(description=_("Recarga los complementos y módulos de aplicación"), category=CAT_TOOLS, gesture="kb:tiresias+control+f3")
	def script_reloadPlugins(self, gesture) -> None:
		from . import core

		core.reloadPlugins()
		speech.speakMessage(_("Complementos recargados"))

	@script(description=_("Paleta de órdenes: busca y ejecuta cualquier orden por su nombre"), category=CAT_TOOLS, gesture="kb:tiresias+shift+p")
	def script_commandPalette(self, gesture) -> None:
		from . import gui
		from .gui import command_palette

		entries = command_palette.collectEntries()
		gui.showCommandPalette(entries)

	@script(description=_("Lista de ventanas abiertas: cambiar a una o cerrarla"), category=CAT_TOOLS, gesture="kb:tiresias+f11")
	def script_windowList(self, gesture) -> None:
		from .gui import app_dialogs

		app_dialogs.showWindowList()

	@script(description=_("Lista de procesos: cambiar a su ventana o finalizarlo"), category=CAT_TOOLS, gesture="kb:tiresias+shift+f11")
	def script_processList(self, gesture) -> None:
		from .gui import app_dialogs

		app_dialogs.showProcessList()

	@script(description=_("Lista de iconos de la bandeja del sistema para pulsarlos"), category=CAT_TOOLS, gesture="kb:tiresias+control+f11")
	def script_trayIconList(self, gesture) -> None:
		from . import system_tools
		from .gui import app_dialogs

		def show(icons: list) -> None:
			if not icons:
				speech.speakMessage(_("No hay iconos en la bandeja"))
				return
			app_dialogs.showTrayIconList(icons)

		system_tools.collectTrayIcons(show)

	@script(description=_("Abre el historial del portapapeles"), category=CAT_TOOLS, gesture="kb:tiresias+alt+v")
	def script_clipboardHistory(self, gesture) -> None:
		from . import gui

		gui.showClipboardHistory()

	# ================================================================ OCR y visión
	@script(description=_("Reconoce el texto del objeto navegador con el OCR de Windows"), category=CAT_VISION, gesture="kb:tiresias+r")
	def script_recognizeWithOcr(self, gesture) -> None:
		from . import ocr

		ocr.recognizeNavigatorObject()

	@script(description=_("Reconoce el texto de toda la pantalla con OCR"), category=CAT_VISION, gesture="kb:tiresias+shift+r")
	def script_recognizeScreenWithOcr(self, gesture) -> None:
		from . import ocr

		ocr.recognizeScreen()

	@script(description=_("Activa o desactiva la cortina de pantalla (pantalla en negro)"), category=CAT_VISION, gesture="kb:tiresias+control+escape")
	def script_toggleScreenCurtain(self, gesture) -> None:
		from . import vision

		vision.handler.toggleScreenCurtain()

	@script(description=_("Activa o desactiva el resaltado visual del foco"), category=CAT_VISION, gesture="kb:tiresias+shift+h")
	def script_toggleFocusHighlight(self, gesture) -> None:
		from . import vision

		vision.handler.toggleHighlight()

	@script(description=_("Activa o desactiva la lupa"), category=CAT_VISION, gesture="kb:tiresias+shift+w")
	def script_toggleMagnifier(self, gesture) -> None:
		from .magnifier import magnifier

		magnifier.toggle()

	@script(description=_("Aumenta la ampliación de la lupa"), category=CAT_VISION, gestures=("kb:tiresias+alt+plus", "kb:tiresias+alt+numpadPlus"))
	def script_magnifierZoomIn(self, gesture) -> None:
		from .magnifier import magnifier

		magnifier.zoom(1)

	@script(description=_("Reduce la ampliación de la lupa"), category=CAT_VISION, gestures=("kb:tiresias+alt+-", "kb:tiresias+alt+numpadMinus"))
	def script_magnifierZoomOut(self, gesture) -> None:
		from .magnifier import magnifier

		magnifier.zoom(-1)

	@script(description=_("Lupa: desplaza la vista a la izquierda"), category=CAT_VISION, gesture="kb:tiresias+alt+leftArrow")
	def script_magnifierPanLeft(self, gesture) -> None:
		from .magnifier import magnifier

		magnifier.pan(-1, 0)

	@script(description=_("Lupa: desplaza la vista a la derecha"), category=CAT_VISION, gesture="kb:tiresias+alt+rightArrow")
	def script_magnifierPanRight(self, gesture) -> None:
		from .magnifier import magnifier

		magnifier.pan(1, 0)

	@script(description=_("Lupa: desplaza la vista hacia arriba"), category=CAT_VISION, gesture="kb:tiresias+alt+upArrow")
	def script_magnifierPanUp(self, gesture) -> None:
		from .magnifier import magnifier

		magnifier.pan(0, -1)

	@script(description=_("Lupa: desplaza la vista hacia abajo"), category=CAT_VISION, gesture="kb:tiresias+alt+downArrow")
	def script_magnifierPanDown(self, gesture) -> None:
		from .magnifier import magnifier

		magnifier.pan(0, 1)

	@script(description=_("Lupa: lleva la vista al borde izquierdo"), category=CAT_VISION, gesture="kb:tiresias+shift+alt+leftArrow")
	def script_magnifierLeftEdge(self, gesture) -> None:
		from .magnifier import magnifier

		magnifier.panToEdge("left")

	@script(description=_("Lupa: lleva la vista al borde derecho"), category=CAT_VISION, gesture="kb:tiresias+shift+alt+rightArrow")
	def script_magnifierRightEdge(self, gesture) -> None:
		from .magnifier import magnifier

		magnifier.panToEdge("right")

	@script(description=_("Lupa: lleva la vista al borde superior"), category=CAT_VISION, gesture="kb:tiresias+shift+alt+upArrow")
	def script_magnifierTopEdge(self, gesture) -> None:
		from .magnifier import magnifier

		magnifier.panToEdge("top")

	@script(description=_("Lupa: lleva la vista al borde inferior"), category=CAT_VISION, gesture="kb:tiresias+shift+alt+downArrow")
	def script_magnifierBottomEdge(self, gesture) -> None:
		from .magnifier import magnifier

		magnifier.panToEdge("bottom")

	@script(description=_("Lupa: invierte los colores de la pantalla"), category=CAT_VISION, gesture="kb:tiresias+shift+i")
	def script_magnifierInvertColors(self, gesture) -> None:
		from .magnifier import magnifier

		magnifier.toggleInvert()

	# ================================================================ audio
	@script(description=_("Cambia la división del sonido (voz a un lado, aplicaciones al otro)"), category=CAT_AUDIO, gesture="kb:tiresias+alt+s")
	def script_cycleSoundSplit(self, gesture) -> None:
		from .audio import sound_split

		speech.speakMessage(sound_split.cycle())

	@script(description=_("Cambia el modo de atenuación de otras aplicaciones al hablar"), category=CAT_AUDIO, gesture="kb:tiresias+shift+d")
	def script_cycleAudioDuckingMode(self, gesture) -> None:
		from .audio import ducking

		speech.speakMessage(ducking.cycle())

	# ================================================================ braille
	@script(description=_("Cambia lo que sigue la línea braille: automático, foco o revisión"), category=CAT_BRAILLE, gesture="kb:tiresias+control+t")
	def script_braille_toggleTether(self, gesture) -> None:
		from . import braille

		speech.speakMessage(braille.handler.cycleTether())

	@script(description=_("Desplaza la línea braille hacia atrás"), category=CAT_BRAILLE, gestures=("br(hidBraille):panLeft",))
	def script_braille_scrollBack(self, gesture) -> None:
		from . import braille

		braille.handler.scrollBack()

	@script(description=_("Desplaza la línea braille hacia delante"), category=CAT_BRAILLE, gestures=("br(hidBraille):panRight",))
	def script_braille_scrollForward(self, gesture) -> None:
		from . import braille

		braille.handler.scrollForward()

	@script(description=_("Mueve el cursor a la celda braille pulsada"), category=CAT_BRAILLE, gestures=("br(hidBraille):routing",))
	def script_braille_routeTo(self, gesture) -> None:
		from . import braille

		braille.handler.routeTo(getattr(gesture, "routingIndex", 0))

	def _brailleKey(self, name: str) -> None:
		# Primero se traduce lo pendiente del teclado braille y se aplican los
		# modificadores activados desde la línea (Control, Alt...).
		from .braille import input as brailleInput

		brailleInput.handler.translate()
		brailleInput.handler.sendKey(name)

	@script(description=_("Línea braille: flecha arriba"), category=CAT_BRAILLE, gestures=("br(hidBraille):joystickUp", "br(hidBraille):dpadUp"))
	def script_braille_upArrow(self, gesture) -> None:
		self._brailleKey("upArrow")

	@script(description=_("Línea braille: flecha abajo"), category=CAT_BRAILLE, gestures=("br(hidBraille):joystickDown", "br(hidBraille):dpadDown"))
	def script_braille_downArrow(self, gesture) -> None:
		self._brailleKey("downArrow")

	@script(description=_("Línea braille: flecha izquierda"), category=CAT_BRAILLE, gestures=("br(hidBraille):joystickLeft", "br(hidBraille):dpadLeft"))
	def script_braille_leftArrow(self, gesture) -> None:
		self._brailleKey("leftArrow")

	@script(description=_("Línea braille: flecha derecha"), category=CAT_BRAILLE, gestures=("br(hidBraille):joystickRight", "br(hidBraille):dpadRight"))
	def script_braille_rightArrow(self, gesture) -> None:
		self._brailleKey("rightArrow")

	@script(description=_("Línea braille: Intro"), category=CAT_BRAILLE, gestures=("br(hidBraille):joystickCenter", "br(hidBraille):dpadCenter"))
	def script_braille_enter(self, gesture) -> None:
		self._brailleKey("enter")

	@script(description=_("Lleva la línea braille a la línea anterior"), category=CAT_BRAILLE, gestures=("br(hidBraille):rockerUp",))
	def script_braille_previousLine(self, gesture) -> None:
		from . import braille

		# Fuera de un texto (#4097) se usa la línea anterior de la revisión.
		if not braille.handler.previousLine():
			self._reviewMove(textinfo.UNIT_LINE, -1)

	@script(description=_("Lleva la línea braille a la línea siguiente"), category=CAT_BRAILLE, gestures=("br(hidBraille):rockerDown",))
	def script_braille_nextLine(self, gesture) -> None:
		from . import braille

		if not braille.handler.nextLine():
			self._reviewMove(textinfo.UNIT_LINE, 1)

	# Espacio+puntos 4 6, como en todas las líneas (Espacio+puntos 4 5 es Fin en las demás).
	@script(description=_("Línea braille: Tabulador"), category=CAT_BRAILLE, gestures=("br(hidBraille):space+dot4+dot6",))
	def script_braille_tab(self, gesture) -> None:
		self._brailleKey("tab")

	@script(description=_("Línea braille: Escape"), category=CAT_BRAILLE, gestures=("br(hidBraille):space+dot1+dot5",))
	def script_braille_escape(self, gesture) -> None:
		self._brailleKey("escape")

	# ================================================================ interceptores
	@script(description=_("Sale del objeto incrustado al documento que lo contiene"), category=_("Modo exploración"), gesture="kb:tiresias+control+space")
	def script_moveToParentTreeInterceptor(self, gesture) -> None:
		focus = api.getFocusObject()
		for anc in reversed(api.getFocusAncestors()):
			ti = getattr(anc, "treeInterceptor", None)
			if ti is not None and not ti.contains(focus):
				anc.setFocus()
				return
		speech.speakMessage(_("no está en un objeto incrustado"))


# Órdenes táctiles y gestos de pantalla táctil (ts:...) de las órdenes globales.
from .touch import commands as _touchCommands  # noqa: E402

_touchCommands.install(GlobalCommands)

# Órdenes braille (modos, desplazamiento automático, entrada braille...).
from .braille import commands as _brailleCommands  # noqa: E402

_brailleCommands.install(GlobalCommands)

# Órdenes equivalentes a las de NVDA que faltaban (formato, voz, revisión,
# ubicación, ratón, diálogos, perfiles, reinicio...).
from . import global_commands_extra as _extraCommands  # noqa: E402

_extraCommands.install(GlobalCommands)

# Órdenes de audio: mezclador, micrófono, dispositivos, sonidos de controles y voces Piper.
from .audio import commands as _audioCommands  # noqa: E402

_audioCommands.install(GlobalCommands)

# Lupa, resaltado, OCR, inteligencia artificial, ratón por teclado y portapapeles.
from . import vision_commands as _visionCommands  # noqa: E402

_visionCommands.install(GlobalCommands)

commands = GlobalCommands()
