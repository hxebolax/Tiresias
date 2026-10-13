"""Composición de entrada (IME de chino, japonés, coreano...).

Sin inyectar código en otros procesos, Tiresias usa lo que Windows expone
por UI Automation:

- **Texto en composición**: el evento ``TextEdit_TextChanged`` con el tipo
  ``Composition`` (lo que se está escribiendo con el IME, aún sin confirmar)
  y ``CompositionFinalized`` (el texto confirmado). Se vigila solo el campo
  con el foco.
- **Candidatos**: la ventana de candidatos del IME moderno de Windows
  (``IME_Candidate_Window`` / ``IME_Prediction_Window`` en el proceso
  ``TextInputHost``) avisa de la selección con ``ElementSelected``; las
  ventanas clásicas (``Microsoft.IME.CandidateWindow.View``) también.

Opciones (sección ``inputComposition``):

- ``reportCompositionStringChanges``: leer el texto en composición;
- ``reportCompositionFinalized``: leer el texto al confirmarlo;
- ``announceSelectedCandidate``: leer el candidato seleccionado;
- ``autoReportAllCandidates``: leer todos los candidatos al abrirse la lista.
"""

from __future__ import annotations

import threading
from typing import Any

import comtypes
from comtypes import COMObject

from . import queue_handler, speech
from .a11y import uia_client as _uc
from .config import conf
from .log import getLogger
from .plugins import GlobalPlugin as _Base

log = getLogger("ime")

CANDIDATE_LIST_IDS = ("IME_Candidate_Window", "IME_Prediction_Window")
CANDIDATE_CLASSES = ("Microsoft.IME.CandidateWindow.View", "Microsoft.IME.UIManager.CandidateWindow.Host")
CANDIDATE_APPS = ("textinputhost", "windowsinternal.composableshell.experiences.textinput.inputapp")

#: TextEditChangeType de UIA.
CHANGE_COMPOSITION = 2
CHANGE_COMPOSITION_FINALIZED = 3


def isCandidateList(obj: Any) -> bool:
	try:
		aid = getattr(obj, "UIAAutomationId", "") or ""
		cls = getattr(obj, "UIAClassName", "") or ""
	except Exception:
		return False
	return aid in CANDIDATE_LIST_IDS or cls in CANDIDATE_CLASSES


#: Niveles de antecesores en los que se busca la lista de candidatos (el IME
#: moderno mete la lista dentro de ``IME_Candidate_Window`` y de un panel).
CANDIDATE_ANCESTOR_LEVELS = 3


def isCandidateItem(obj: Any) -> bool:
	"""Elemento de una lista de candidatos del IME.

	Solo cuenta si uno de sus antecesores cercanos es la lista de candidatos:
	``TextInputHost`` también muestra el panel de emojis y el historial del
	portapapeles, cuyos elementos no son candidatos (antes se leían todos los
	emojis del grupo de una vez y el módulo del panel nunca recibía la selección).
	"""
	from .objects.roles import Role

	try:
		anc = obj.parent
		if anc is None:
			return False
		if isCandidateList(anc):
			return True
		if obj.role != Role.LISTITEM:
			return False
		for _i in range(CANDIDATE_ANCESTOR_LEVELS - 1):
			anc = anc.parent
			if anc is None:
				return False
			if isCandidateList(anc):
				return True
	except Exception:
		return False
	return False


def candidateText(obj: Any) -> str:
	name = (obj.name or "").strip()
	try:
		info = obj.positionInfo or {}
	except Exception:
		info = {}
	index = info.get("indexInGroup")
	return f"{index} {name}" if index and not name.startswith(str(index)) else name


def allCandidates(listObj: Any) -> list[str]:
	from .objects.roles import Role

	out = []
	try:
		for child in listObj.children:
			if child.role == Role.LISTITEM and child.name:
				out.append(candidateText(child))
	except Exception:
		log.debug("No se pudieron leer los candidatos", exc_info=True)
	return out


class _TextEditHandler(COMObject):
	"""Recibe los cambios de composición (hilo de UIA) y los pasa al núcleo."""

	_com_interfaces_ = [_uc.UIA.IUIAutomationTextEditTextChangedEventHandler]

	def IUIAutomationTextEditTextChangedEventHandler_HandleTextEditTextChangedEvent(self, sender, changeType, eventStrings):
		try:
			strings = [str(s) for s in (eventStrings or ()) if s]
		except Exception:
			strings = []
		queue_handler.queueFunction(_onTextEdit, int(changeType), strings)


_lastComposition = ""


def _onTextEdit(changeType: int, strings: list[str]) -> None:
	global _lastComposition
	text = " ".join(strings).strip()
	sec = conf["inputComposition"]
	if changeType == CHANGE_COMPOSITION:
		if not sec["reportCompositionStringChanges"] or not text:
			return
		# Solo lo nuevo respecto a la composición anterior (como al escribir).
		new = text[len(_lastComposition):] if text.startswith(_lastComposition) else text
		_lastComposition = text
		if new:
			speech.speakText(new)
	elif changeType == CHANGE_COMPOSITION_FINALIZED:
		_lastComposition = ""
		if sec["reportCompositionFinalized"] and text:
			speech.speakText(text)


class GlobalPlugin(_Base):
	def __init__(self) -> None:
		super().__init__()
		self._handler: _TextEditHandler | None = None
		#: Puntero COM propio al manejador (lo mantiene vivo entre registros).
		self._handlerPtr = None
		self._registrations = 0
		self._element = None
		self._lock = threading.Lock()
		self._lastList: tuple | None = None

	def terminate(self) -> None:
		self._unregister()
		self._handlerPtr = None

	# --------------------------------------------------------- composición
	def _wanted(self) -> bool:
		sec = conf["inputComposition"]
		return bool(sec["reportCompositionStringChanges"] or sec["reportCompositionFinalized"])

	def _unregister(self) -> None:
		from .a11y import uia_client as uc

		if self._element is not None and self._handlerPtr is not None:
			# Una baja por cada tipo de cambio registrado.
			for _i in range(self._registrations):
				try:
					uc.client.RemoveTextEditTextChangedEventHandler(self._element, self._handlerPtr)
				except (comtypes.COMError, AttributeError, TypeError):
					break
		self._element = None
		self._registrations = 0

	def _ensureHandler(self) -> bool:
		"""Crea el manejador y guarda una referencia COM propia.

		Sin esa referencia, al quitar el último registro UIA suelta el objeto,
		su contador llega a cero y comtypes vacía sus interfaces: el siguiente
		registro fallaría con «Interface ... not supported».
		"""
		if self._handlerPtr is not None:
			return True
		try:
			self._handler = _TextEditHandler()
			self._handlerPtr = self._handler.QueryInterface(_uc.UIA.IUIAutomationTextEditTextChangedEventHandler)
		except Exception:
			log.debug("Sin manejador de composición", exc_info=True)
			self._handler = self._handlerPtr = None
			return False
		return True

	def _register(self, obj: Any) -> None:
		from .a11y import uia_client as uc

		self._unregister()
		client = uc.client
		if client is None or not hasattr(client, "AddTextEditTextChangedEventHandler"):
			return
		try:
			if not obj.hasText:
				return
			el = obj.element
		except Exception:
			return
		if not self._ensureHandler():
			return
		self._element = el
		for changeType in (CHANGE_COMPOSITION, CHANGE_COMPOSITION_FINALIZED):
			try:
				client.AddTextEditTextChangedEventHandler(el, uc.TreeScope_Element, changeType, uc.baseCacheRequest, self._handlerPtr)
			except (comtypes.COMError, TypeError):
				log.debug("No se pudo vigilar la composición", exc_info=True)
				break
			self._registrations += 1
		if not self._registrations:
			self._element = None

	def event_gainFocus(self, obj: Any, nextHandler, **kwargs) -> None:
		global _lastComposition
		_lastComposition = ""
		if self._wanted() and not isCandidateItem(obj) and not isCandidateList(obj):
			try:
				self._register(obj)
			except Exception:
				log.debug("Error registrando la composición", exc_info=True)
		elif not self._wanted():
			self._unregister()
		nextHandler()

	# --------------------------------------------------------- candidatos
	def event_selection(self, obj: Any, nextHandler, **kwargs) -> None:
		if not isCandidateItem(obj):
			nextHandler()
			return
		sec = conf["inputComposition"]
		parent = None
		try:
			parent = obj.parent
		except Exception:
			pass
		if sec["autoReportAllCandidates"] and parent is not None:
			# Lista nueva o página nueva de candidatos (como NVDA): se leen todos.
			items = allCandidates(parent)
			key = (tuple(getattr(parent, "runtimeId", ()) or ()), tuple(items))
			if items and key != self._lastList:
				self._lastList = key
				speech.speakText(", ".join(items))
				return
		if sec["announceSelectedCandidate"]:
			speech.speakText(candidateText(obj))

	def event_windowOpened(self, obj: Any, nextHandler, **kwargs) -> None:
		if isCandidateList(obj):
			# Lista nueva: se volverán a leer todos los candidatos.
			self._lastList = None
		nextHandler()
