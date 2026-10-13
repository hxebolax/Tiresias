"""Órdenes de visión, OCR, inteligencia artificial y herramientas extra.

:func:`install` copia estas órdenes en ``GlobalCommands`` (solo las que esa
clase no define ya); así aparecen en «Gestos de entrada», en la paleta de
órdenes y en la referencia rápida como cualquier orden global. Las que no
tienen gesto se asignan desde «Gestos de entrada», se ejecutan desde la
paleta o desde los menús «Inteligencia artificial» y «Visión» (Tiresias+Alt+I
y el menú de Tiresias).
"""

from __future__ import annotations

from typing import Callable

from . import queue_handler, speech
from .baseobject import normalizeGestureId, script
from .i18n import _
from .log import getLogger

log = getLogger("visionCommands")

CAT_VISION = _("Visión")
CAT_OCR = _("Reconocimiento de texto")
CAT_AI = _("Inteligencia artificial")
CAT_MOUSE = _("Ratón")
CAT_TOOLS = _("Herramientas")


def _mag():
	from .magnifier import magnifier

	return magnifier


def _ai(name: str) -> Callable:
	from .ai import assistant

	return getattr(assistant, name)


class VisionCommands:
	# ================================================================ lupa
	@script(description=_("Lupa: cambia el filtro de color (invertir, grises, sepia, amarillo sobre negro...)"), category=CAT_VISION, gesture="kb:tiresias+shift+alt+i")
	def script_magnifierCycleFilter(self, gesture) -> None:
		_mag().cycleFilter()

	@script(description=_("Lupa: quita el filtro de color o recupera el último"), category=CAT_VISION)
	def script_magnifierToggleColorFilter(self, gesture) -> None:
		_mag().toggleColorFilter()

	@script(description=_("Lupa: cambia la vista (pantalla completa, ventana acoplada, lente, foco)"), category=CAT_VISION, gesture="kb:tiresias+shift+alt+w")
	def script_magnifierCycleView(self, gesture) -> None:
		_mag().cycleView()

	@script(description=_("Lupa: cambia el modo de seguimiento (centrado, por bordes, relativo)"), category=CAT_VISION)
	def script_magnifierCycleTrackingMode(self, gesture) -> None:
		_mag().cycleTrackingMode()

	@script(description=_("Lupa: muestra un momento toda la pantalla sin ampliar"), category=CAT_VISION, gesture="kb:tiresias+shift+l")
	def script_magnifierOverview(self, gesture) -> None:
		_mag().showOverview()

	@script(description=_("Lupa: lleva el ratón al centro de la vista ampliada"), category=CAT_VISION)
	def script_magnifierMoveMouseToView(self, gesture) -> None:
		_mag().moveMouseToView()

	@script(description=_("Lupa: activa o desactiva el seguimiento del foco"), category=CAT_VISION)
	def script_magnifierToggleFollowFocus(self, gesture) -> None:
		_mag().toggleFollow("followFocus")

	@script(description=_("Lupa: activa o desactiva el seguimiento del cursor del sistema"), category=CAT_VISION)
	def script_magnifierToggleFollowCaret(self, gesture) -> None:
		_mag().toggleFollow("followCaret")

	@script(description=_("Lupa: activa o desactiva el seguimiento del cursor de revisión"), category=CAT_VISION)
	def script_magnifierToggleFollowReview(self, gesture) -> None:
		_mag().toggleFollow("followReview")

	@script(description=_("Lupa: activa o desactiva el seguimiento del objeto navegador"), category=CAT_VISION)
	def script_magnifierToggleFollowNavigator(self, gesture) -> None:
		_mag().toggleFollow("followNavigator")

	@script(description=_("Lupa: activa o desactiva el seguimiento del ratón"), category=CAT_VISION)
	def script_magnifierToggleFollowMouse(self, gesture) -> None:
		_mag().toggleFollow("followMouse")

	@script(description=_("Lupa: activa o desactiva todos los seguimientos"), category=CAT_VISION)
	def script_magnifierToggleAllFollow(self, gesture) -> None:
		_mag().toggleAllFollow()

	@script(description=_("Lupa: anuncia su estado (vista, nivel, filtro y seguimiento)"), category=CAT_VISION, speakOnDemand=True)
	def script_magnifierReportState(self, gesture) -> None:
		_mag().reportState()

	# ================================================================ resaltado
	@script(description=_("Activa o desactiva el resaltado del foco"), category=CAT_VISION)
	def script_toggleHighlightFocus(self, gesture) -> None:
		from . import vision

		vision.handler.toggleHighlightKind("focus")

	@script(description=_("Activa o desactiva el resaltado del objeto navegador"), category=CAT_VISION)
	def script_toggleHighlightNavigator(self, gesture) -> None:
		from . import vision

		vision.handler.toggleHighlightKind("navigator")

	@script(description=_("Activa o desactiva el resaltado del cursor del modo exploración"), category=CAT_VISION)
	def script_toggleHighlightBrowseMode(self, gesture) -> None:
		from . import vision

		vision.handler.toggleHighlightKind("browseMode")

	@script(description=_("Activa o desactiva el resaltado del objeto bajo el ratón"), category=CAT_VISION)
	def script_toggleHighlightMouse(self, gesture) -> None:
		from . import vision

		vision.handler.toggleHighlightKind("mouse")

	# ================================================================ OCR
	@script(description=_("Reconoce con OCR la ventana activa (revisión de pantalla por OCR)"), category=CAT_OCR, gesture="kb:tiresias+control+shift+r")
	def script_recognizeWindowWithOcr(self, gesture) -> None:
		from . import ocr

		ocr.screenReview()

	@script(description=_("Reconoce con OCR un archivo de imagen o PDF"), category=CAT_OCR)
	def script_recognizeFileWithOcr(self, gesture) -> None:
		from . import ocr

		ocr.recognizeFileDialog()

	@script(description=_("Reconoce con OCR la imagen o el archivo del portapapeles"), category=CAT_OCR)
	def script_recognizeClipboardWithOcr(self, gesture) -> None:
		from . import ocr

		ocr.recognizeClipboard()

	@script(description=_("Lectura continua por OCR del objeto navegador: lee solo lo nuevo (subtítulos)"), category=CAT_OCR, gesture="kb:tiresias+shift+alt+r")
	def script_toggleContinuousOcr(self, gesture) -> None:
		from . import ocr

		ocr.continuous.toggle()

	@script(description=_("Cambia el idioma del reconocimiento de texto"), category=CAT_OCR)
	def script_cycleOcrLanguage(self, gesture) -> None:
		from . import ocr

		ocr.cycleLanguage()

	@script(description=_("Cambia el motor de reconocimiento de texto (Windows o Tesseract)"), category=CAT_OCR)
	def script_cycleOcrEngine(self, gesture) -> None:
		from . import ocr

		ocr.cycleEngine()

	@script(description=_("Activa o desactiva la actualización automática del resultado del OCR"), category=CAT_OCR)
	def script_toggleOcrAutoRefresh(self, gesture) -> None:
		from . import ocr

		ocr.toggleAutoRefresh()

	# ================================================================ IA
	@script(description=_("IA: describe el objeto navegador"), category=CAT_AI, gesture="kb:tiresias+g")
	def script_aiDescribeNavigator(self, gesture) -> None:
		_ai("describeNavigatorObject")()

	@script(description=_("IA: describe la ventana activa"), category=CAT_AI, gesture="kb:tiresias+shift+g")
	def script_aiDescribeWindow(self, gesture) -> None:
		_ai("describeForegroundWindow")()

	@script(description=_("IA: describe toda la pantalla"), category=CAT_AI)
	def script_aiDescribeScreen(self, gesture) -> None:
		_ai("describeScreen")()

	@script(description=_("IA: describe un archivo de imagen"), category=CAT_AI)
	def script_aiDescribeFile(self, gesture) -> None:
		_ai("describeFileDialog")()

	@script(description=_("IA: describe la imagen del portapapeles"), category=CAT_AI)
	def script_aiDescribeClipboard(self, gesture) -> None:
		_ai("describeClipboardImage")()

	@script(description=_("IA: resume el documento o la página"), category=CAT_AI)
	def script_aiSummarize(self, gesture) -> None:
		_ai("summarizeDocument")()

	@script(description=_("IA: pregunta sobre el documento o la página"), category=CAT_AI)
	def script_aiAskPage(self, gesture) -> None:
		_ai("askAboutDocument")()

	@script(description=_("IA: sugiere una etiqueta para el objeto navegador y la guarda"), category=CAT_AI)
	def script_aiSuggestLabel(self, gesture) -> None:
		_ai("suggestLabel")()

	@script(description=_("IA: pregunta cómo se hace algo en Tiresias"), category=CAT_AI)
	def script_aiHelp(self, gesture) -> None:
		_ai("askHelp")()

	@script(description=_("IA: describe un CAPTCHA para que decidas la respuesta"), category=CAT_AI)
	def script_aiDescribeCaptcha(self, gesture) -> None:
		_ai("describeCaptcha")()

	# foros 6.6: diseño visual, consejos de navegación y preguntas de seguimiento.
	@script(description=_("IA: explora la página (contenido, diseño visual y teclas para moverte) y permite preguntas de seguimiento"), category=CAT_AI, gesture="kb:tiresias+shift+e")
	def script_aiExplorePage(self, gesture) -> None:
		from .ai import explorer

		explorer.explorePage()

	# foros 6.3 (NVDA #17332).
	@script(description=_("IA: activa o desactiva el etiquetado automático de los elementos sin nombre"), category=CAT_AI)
	def script_aiToggleAutoLabel(self, gesture) -> None:
		from .ai.autolabel import autoLabeler

		autoLabeler.toggle()

	# foros 3.10.
	@script(description=_("IA: propone el orden de lectura del documento (PDF desordenado) y lo aplica si lo aceptas"), category=CAT_AI)
	def script_aiReadingOrder(self, gesture) -> None:
		from .ai import reading

		reading.suggestReadingOrder()

	@script(description=_("IA: genera texto alternativo para las imágenes sin descripción del documento (otra vez: lo detiene)"), category=CAT_AI)
	def script_aiDescribeUnlabeledImages(self, gesture) -> None:
		from .ai import reading

		reading.describeUnlabeledImages()

	# foros 10.6.
	@script(description=_("CAPTCHA: va al reto de audio; en el botón de reproducir, lo pulsa y baja la voz del lector mientras suena"), category=CAT_AI, gesture="kb:tiresias+control+shift+u")
	def script_captchaAudio(self, gesture) -> None:
		from .ai import captcha

		captcha.jumpToAudio()

	@script(description=_("CAPTCHA: baja la voz del lector unos segundos para escuchar el audio del reto (otra vez: la recupera)"), category=CAT_AI)
	def script_captchaDuck(self, gesture) -> None:
		from .ai import captcha

		captcha.toggleDuck()

	@script(description=_("IA: traduce el texto seleccionado"), category=CAT_AI, gesture="kb:tiresias+shift+t")
	def script_aiTranslateSelection(self, gesture) -> None:
		from .ai import translate

		translate.translateSelection()

	@script(description=_("IA: traduce el texto del portapapeles"), category=CAT_AI)
	def script_aiTranslateClipboard(self, gesture) -> None:
		from .ai import translate

		translate.translateClipboard()

	@script(description=_("IA: traduce lo último que se dijo"), category=CAT_AI)
	def script_aiTranslateLastSpoken(self, gesture) -> None:
		from .ai import translate

		translate.translateLastSpoken()

	@script(description=_("IA: copia la última traducción"), category=CAT_AI)
	def script_aiCopyTranslation(self, gesture) -> None:
		from .ai import translate

		translate.copyLastTranslation()

	@script(description=_("IA: cambia el idioma al que se traduce"), category=CAT_AI)
	def script_aiCycleTranslateLanguage(self, gesture) -> None:
		from .ai import translate

		translate.cycleTargetLanguage()

	@script(description=_("IA: activa o desactiva la traducción de todo lo que se dice"), category=CAT_AI)
	def script_aiToggleTranslateSpeech(self, gesture) -> None:
		from .ai import translate

		translate.toggleTranslateSpeech()

	@script(description=_("IA: agente que hace una tarea en la pantalla (pide confirmación en cada paso)"), category=CAT_AI)
	def script_aiAgent(self, gesture) -> None:
		from .ai import agent

		agent.startDialog()

	@script(description=_("IA: parada de emergencia del agente"), category=CAT_AI, gesture="kb:tiresias+shift+escape")
	def script_aiAgentStop(self, gesture) -> None:
		from .ai.agent import agent

		agent.stop()

	@script(description=_("Cara a la vista: comprueba con la cámara el encuadre y la luz"), category=CAT_AI)
	def script_aiFaceCheck(self, gesture) -> None:
		from .ai.camera import faceCheck

		faceCheck.toggle()

	@script(description=_("Menú de inteligencia artificial, OCR y visión"), category=CAT_AI, gesture="kb:tiresias+alt+i")
	def script_aiMenu(self, gesture) -> None:
		showActionsMenu()

	# ================================================================ ratón y portapapeles
	@script(description=_("Activa o desactiva el ratón por teclado (flechas mueven el puntero)"), category=CAT_MOUSE, gesture="kb:tiresias+shift+alt+k")
	def script_toggleMouseKeys(self, gesture) -> None:
		from . import mouse_keys

		mouse_keys.toggleMode()

	@script(description=_("Anuncia las coordenadas del puntero del ratón"), category=CAT_MOUSE, speakOnDemand=True)
	def script_reportMouseCoordinates(self, gesture) -> None:
		from . import mouse_keys

		mouse_keys.reportCoordinates()

	@script(description=_("Guarda la posición del ratón para esta aplicación"), category=CAT_MOUSE)
	def script_saveMousePosition(self, gesture) -> None:
		from . import mouse_keys

		mouse_keys.askSavePosition()

	@script(description=_("Lista de posiciones del ratón guardadas en esta aplicación"), category=CAT_MOUSE)
	def script_mousePositions(self, gesture) -> None:
		from . import mouse_keys

		mouse_keys.showPositions()

	@script(description=_("Doble clic en la posición del ratón"), category=CAT_MOUSE)
	def script_doubleMouseClick(self, gesture) -> None:
		from . import mouse

		mouse.click(double=True)

	@script(description=_("Añade el texto seleccionado al final del portapapeles"), category=CAT_TOOLS, gesture="kb:tiresias+shift+c")
	def script_appendSelectionToClipboard(self, gesture) -> None:
		from . import clipboard
		from .ai import translate

		clipboard.appendText(translate.selectedText())

	@script(description=_("Anuncia qué hay en el portapapeles (texto, imagen o archivos)"), category=CAT_TOOLS, speakOnDemand=True)
	def script_reportClipboardContents(self, gesture) -> None:
		from . import clipboard

		speech.speakMessage(clipboard.describeContents())

	@script(description=_("Guarda como audio WAV el texto seleccionado con la voz actual"), category=CAT_TOOLS)
	def script_exportSelectionToWav(self, gesture) -> None:
		from . import audio_export

		audio_export.exportDialog("selection")

	@script(description=_("Guarda como audio WAV el documento con la voz actual"), category=CAT_TOOLS)
	def script_exportDocumentToWav(self, gesture) -> None:
		from . import audio_export

		audio_export.exportDialog("document")

	@script(description=_("Guarda como audio WAV el texto del portapapeles con la voz actual"), category=CAT_TOOLS)
	def script_exportClipboardToWav(self, gesture) -> None:
		from . import audio_export

		audio_export.exportDialog("clipboard")


# ====================================================================== menú
def menuActions() -> list[tuple[str, str, Callable[[], None]]]:
	"""(grupo, etiqueta, función en el núcleo) de todas las acciones del menú."""
	from . import audio_export, mouse_keys, ocr
	from .ai import assistant, captcha, explorer, reading, translate
	from .ai.agent import startDialog
	from .ai.autolabel import autoLabeler
	from .ai.camera import faceCheck

	ia = _("Inteligencia artificial")
	rec = _("Reconocimiento de texto")
	tools = _("Herramientas")
	return [
		(ia, _("Describir el objeto navegador"), assistant.describeNavigatorObject),
		(ia, _("Describir la ventana activa"), assistant.describeForegroundWindow),
		(ia, _("Describir toda la pantalla"), assistant.describeScreen),
		(ia, _("Describir un archivo de imagen..."), assistant.describeFileDialog),
		(ia, _("Describir la imagen del portapapeles"), assistant.describeClipboardImage),
		(ia, _("Resumir el documento o la página"), assistant.summarizeDocument),
		(ia, _("Preguntar sobre el documento o la página..."), assistant.askAboutDocument),
		(ia, _("Explorar la página (diseño visual y cómo moverse)"), explorer.explorePage),
		(ia, _("Sugerir una etiqueta para el objeto navegador"), assistant.suggestLabel),
		(ia, _("Etiquetado automático de elementos sin nombre (activar o desactivar)"), autoLabeler.toggle),
		(ia, _("Proponer el orden de lectura del documento..."), reading.suggestReadingOrder),
		(ia, _("Texto alternativo para las imágenes sin descripción (iniciar o detener)"), reading.describeUnlabeledImages),
		(ia, _("Ayuda de Tiresias..."), assistant.askHelp),
		(ia, _("Describir un CAPTCHA"), assistant.describeCaptcha),
		(ia, _("CAPTCHA: ir al reto de audio"), captcha.jumpToAudio),
		(ia, _("CAPTCHA: bajar la voz durante el audio (activar o desactivar)"), captcha.toggleDuck),
		(ia, _("Traducir la selección"), translate.translateSelection),
		(ia, _("Traducir el portapapeles"), translate.translateClipboard),
		(ia, _("Traducir lo último que se dijo"), translate.translateLastSpoken),
		(ia, _("Copiar la última traducción"), translate.copyLastTranslation),
		(ia, _("Cambiar el idioma al que se traduce"), translate.cycleTargetLanguage),
		(ia, _("Traducir todo lo que se dice (activar o desactivar)"), translate.toggleTranslateSpeech),
		(ia, _("Agente de IA..."), startDialog),
		(ia, _("Cara a la vista (comprobar la cámara)"), faceCheck.toggle),
		(rec, _("Reconocer el objeto navegador"), ocr.recognizeNavigatorObject),
		(rec, _("Reconocer la ventana activa (revisión de pantalla por OCR)"), ocr.screenReview),
		(rec, _("Reconocer toda la pantalla"), ocr.recognizeScreen),
		(rec, _("Reconocer un archivo de imagen o PDF..."), ocr.recognizeFileDialog),
		(rec, _("Reconocer el portapapeles"), ocr.recognizeClipboard),
		(rec, _("Lectura continua del objeto navegador (activar o desactivar)"), ocr.continuous.toggle),
		(tools, _("Ratón por teclado (activar o desactivar)"), mouse_keys.toggleMode),
		(tools, _("Posiciones del ratón guardadas..."), mouse_keys.showPositions),
		(tools, _("Guardar la selección como audio WAV..."), lambda: audio_export.exportDialog("selection")),
		(tools, _("Guardar el documento como audio WAV..."), lambda: audio_export.exportDialog("document")),
		(tools, _("Guardar el portapapeles como audio WAV..."), lambda: audio_export.exportDialog("clipboard")),
	]


def showActionsMenu() -> None:
	"""Lista filtrable con todas las acciones de IA, OCR y herramientas."""
	from . import gui

	actions = menuActions()
	labels = [f"{label} ({group})" for group, label, _f in actions]

	def chosen(text: str) -> None:
		for (_group, _label, func), shown in zip(actions, labels, strict=True):
			if shown == text:
				queue_handler.queueFunction(func)
				return

	gui.chooseFromList(_("Inteligencia artificial y visión"), _("&Acciones:"), labels, chosen)


def buildMenu(frame) -> object:
	"""Submenú «Visión e IA» del menú de Tiresias (hilo de la interfaz)."""
	import wx

	menu = wx.Menu()
	subs: dict[str, wx.Menu] = {}
	for group, label, func in menuActions():
		sub = subs.get(group)
		if sub is None:
			sub = subs[group] = wx.Menu()
			menu.AppendSubMenu(sub, group)
		frame.addMenuItem(sub, label, lambda f=func: queue_handler.queueFunction(f))
	return menu


# ====================================================================== instalación
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
	for attr, func in list(vars(VisionCommands).items()):
		if not attr.startswith("script_") or attr in cls.__dict__:
			continue
		setattr(cls, attr, func)
		for g in getattr(func, "gestures", ()) or ():
			gestures.setdefault(normalizeGestureId(g), attr[7:])


def initialize() -> None:
	"""Antes de iniciar los complementos: ratón por teclado e IA."""
	from . import mouse_keys

	mouse_keys.initialize()
	try:
		from . import ai

		ai.initialize()
	except Exception:
		log.exception("No se pudo iniciar la inteligencia artificial")


def terminate() -> None:
	from . import ocr

	try:
		ocr.terminate()
	except Exception:
		log.exception("Error cerrando el OCR")
	try:
		from . import ai

		ai.terminate()
	except Exception:
		log.exception("Error cerrando la IA")
	try:
		from .ai.camera import faceCheck

		faceCheck._stop.set()
	except Exception:
		pass

