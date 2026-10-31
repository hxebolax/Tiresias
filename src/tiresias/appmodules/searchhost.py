"""Búsqueda y menú Inicio de Windows 10 y 11.

Un solo módulo para ``SearchHost``, ``SearchApp``, ``SearchUI`` y
``StartMenuExperienceHost`` (alias en ``EXECUTABLE_ALIASES``): antes había
dos archivos idénticos que además cortaban la cadena de eventos.

Al escribir en la búsqueda, el resultado resaltado cambia de selección sin
recibir el foco: se lee una sola vez cada vez que cambia.

Rev. 1.0.15: la «experiencia de búsqueda refinada» de Windows 11 26H2
(compilación 26300 y posteriores; NVDA #20530, #17951) muestra los resultados
en una página web (WebView2 con Chromium) dentro de la ventana de búsqueda:

- El foco del teclado se queda en el cuadro de búsqueda (XAML) mientras la
  página marca como seleccionado el mejor resultado y, con las flechas, los
  siguientes. Como no hay foco ni llegan eventos de selección desde la página,
  nadie decía qué resultado estaba resaltado (NVDA y Narrador leen «Todos
  pestaña seleccionado» o nada; JAWS sí lee la sugerencia). Tiresias busca el
  elemento seleccionado de la página al escribir y al mover las flechas, y lo
  anuncia cuando cambia.
- La página manda a veces un foco falso a su documento al cargar resultados:
  Tiresias decía «Búsqueda: contenido web región, Búsqueda» y las flechas
  dejaban de servir. Se descarta si el foco real de UIA sigue en el cuadro.
"""

from __future__ import annotations

import time

from .. import api, presentation, queue_handler, speech
from ..baseobject import script
from ..log import getLogger
from ..objects import behaviors
from ..objects.roles import Role
from . import AppModule as BaseAppModule

log = getLogger("appmodules.searchhost")

#: Identificador del cuadro de búsqueda (Windows 10 y 11).
SEARCH_BOX_ID = "SearchTextBox"
#: Retardos (ms) de las comprobaciones del resultado resaltado tras escribir:
#: los resultados locales llegan enseguida y los de Internet tardan más.
TYPING_CHECK_DELAYS = (250, 800, 1800)
#: Retardos tras mover las flechas: la selección cambia al instante.
ARROW_CHECK_DELAYS = (80, 400)


class StartMenuSearchField(behaviors.EditableTextWithCaret):
	"""Cuadro de búsqueda del menú Inicio.

	Con los resultados en la página web, las flechas arriba y abajo (y
	Avanzar y Retroceder página) no mueven el cursor del cuadro sino el
	resultado resaltado: se dejan pasar y se anuncia el resultado nuevo. Si el
	foco se va de verdad a un resultado (menú Inicio clásico), lo anuncia el
	foco como siempre.
	"""

	#: El texto del cuadro no se lee al cerrarse el menú (NVDA #7370).
	announceNewLineText = False

	@script(gestures=("kb:upArrow", "kb:downArrow", "kb:pageUp", "kb:pageDown"))
	def script_moveSuggestion(self, gesture) -> None:
		gesture.send()
		app = self.appModule
		if app is not None:
			app.scheduleSuggestionCheck(ARROW_CHECK_DELAYS)

	def event_gainFocus(self) -> None:
		app = self.appModule
		if app is not None:
			app.resetSuggestion()
		super().event_gainFocus()
		if app is not None and (self.value or ""):
			# Se vuelve al cuadro con texto (Mayúsculas+Tab desde los filtros): el
			# resultado resaltado sigue ahí.
			app.scheduleSuggestionCheck(ARROW_CHECK_DELAYS)

	def event_valueChange(self) -> None:
		super().event_valueChange()
		app = self.appModule
		if app is not None:
			app.scheduleSuggestionCheck(TYPING_CHECK_DELAYS)

	def event_controllerForChange(self) -> None:
		super().event_controllerForChange()
		app = self.appModule
		if app is not None:
			app.scheduleSuggestionCheck(TYPING_CHECK_DELAYS)


class AppModule(BaseAppModule):
	#: Rev. 10.11: los resultados son una página WebView2; si su documento
	#: recibe un foco falso, las letras que se escriben en la búsqueda no deben
	#: convertirse en navegación rápida (NVDA #17951).
	disableBrowseModeByDefault = True

	def __init__(self, processID: int, appName: str | None = None) -> None:
		super().__init__(processID, appName)
		self._last = (None, 0.0)
		self._checkSeq = 0
		self._lastSuggestion: str | None = None

	# ------------------------------------------------------------ objetos
	def chooseObjectClass(self, obj, clsList: list[type]) -> None:
		if getattr(obj, "UIAAutomationId", "") == SEARCH_BOX_ID and obj.role == Role.EDITABLETEXT:
			clsList.insert(0, StartMenuSearchField)

	def shouldProcessEvent(self, eventName: str, obj, **kwargs) -> bool:
		if eventName == "gainFocus" and self._isFakeWebFocus(obj):
			log.debug("Foco falso del documento de resultados descartado: el foco sigue en el cuadro de búsqueda")
			return False
		return True

	def _isFakeWebFocus(self, obj) -> bool:
		"""Foco en la página de resultados mientras el foco real está en el cuadro de búsqueda."""
		try:
			if getattr(obj, "UIAFrameworkId", "") != "Chrome":
				return False
			from ..a11y import uia_client as uc

			el = uc.getFocusedElement()
			if el is None:
				return False
			return str(el.CurrentAutomationId or "") == SEARCH_BOX_ID
		except Exception:
			return False

	# ------------------------------------------------------------ resultado resaltado
	def resetSuggestion(self) -> None:
		self._lastSuggestion = None
		self._checkSeq += 1

	def scheduleSuggestionCheck(self, delays=TYPING_CHECK_DELAYS) -> None:
		"""Comprueba (varias veces, los resultados llegan poco a poco) qué resultado está resaltado."""
		self._checkSeq += 1
		seq = self._checkSeq
		for delay in delays:
			queue_handler.callLater(delay, self._checkSuggestion, seq)

	def _checkSuggestion(self, seq: int) -> None:
		if seq != self._checkSeq:
			return
		focus = api.getFocusObject()
		if not isinstance(focus, StartMenuSearchField):
			return
		try:
			suggestion = self._selectedSuggestion(focus)
		except Exception:
			log.debug("No se pudo buscar el resultado resaltado", exc_info=True)
			return
		if suggestion is None:
			return
		name = " ".join((suggestion.name or "").split())
		if not name or name == self._lastSuggestion:
			return
		self._lastSuggestion = name
		self._announce(suggestion)

	def _selectedSuggestion(self, searchField):
		"""Elemento seleccionado de la lista de resultados que controla el cuadro de búsqueda."""
		from ..a11y import uia_client as uc
		from ..objects.uia import UIAObject

		element = getattr(searchField, "element", None)
		if element is None:
			return None
		cond = uc.createPropertyCondition(uc.P_SELECTIONITEMISSELECTED, True)
		containers = uc.elementArray(element, uc.P_CONTROLLERFOR)
		if not containers:
			fg = api.getForegroundObject()
			root = getattr(fg, "element", None)
			containers = [root] if root is not None else []
		for container in containers:
			try:
				found = container.FindFirstBuildCache(uc.TreeScope_Descendants, cond, uc.baseCacheRequest)
			except Exception:
				continue
			if found is not None:
				return UIAObject.fromElement(found)
		return None

	def _announce(self, obj) -> None:
		try:
			self._last = (getattr(obj, "runtimeId", None), time.monotonic())
			behaviors._noteAnnounced(obj.name or "")
		except Exception:
			pass
		presentation.speakObject(obj, reason=presentation.Reason.FOCUS)

	# ------------------------------------------------------------ eventos
	def event_selection(self, obj, nextHandler) -> None:
		try:
			role = obj.role
			rid = getattr(obj, "runtimeId", None)
			# Con las flechas en los resultados el foco llega al elemento y ya lo
			# lee: su selección no debe cortarlo y repetirlo.
			isFocus = obj == api.getFocusObject()
		except Exception:
			nextHandler()
			return
		if role in (Role.LISTITEM, Role.BUTTON, Role.DATAITEM, Role.MENUITEM, Role.TREEVIEWITEM) and not isFocus:
			now = time.monotonic()
			if rid is not None and rid == self._last[0] and now - self._last[1] < 0.5:
				return
			name = " ".join((obj.name or "").split())
			if name and name == self._lastSuggestion and now - self._last[1] < 2.0:
				# Ya lo anunció la comprobación del resultado resaltado.
				return
			self._lastSuggestion = name or self._lastSuggestion
			speech.cancelSpeech()
			self._announce(obj)
		nextHandler()
