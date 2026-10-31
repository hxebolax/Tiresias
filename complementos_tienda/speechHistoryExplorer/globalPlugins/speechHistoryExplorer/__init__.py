"""Explorador del historial de voz para Tiresias.

Permite recorrer con la voz lo último que ha dicho Tiresias (elemento
anterior y siguiente, con un pitido paneado al llegar a un extremo), copiar
al portapapeles el elemento en el que se está y abrir un diálogo con todos
los elementos recientes para buscarlos, seleccionarlos y copiarlos.

No guarda un historial propio: usa el de Tiresias (``speech.getHistory()``),
cuyo tamaño máximo es la opción «Tamaño del historial de voz». Lo que el
propio explorador dice al navegar se marca con el origen :data:`ORIGIN` y se
descuenta, así esas frases no mueven la posición ni aparecen en la lista.

Basado en Speech History Explorer para NVDA, de Tyler Spivey (Clip Copy,
2012), James Scholes (Speech History, 2015-2021) y David CM (2022-2023),
licencia GPL versión 2. Código propio para Tiresias.
"""

from __future__ import annotations

from tiresias.baseobject import script
from tiresias.log import getLogger
from tiresias.plugins import GlobalPlugin as _BaseGlobalPlugin

from . import options

log = getLogger("speechHistoryExplorer")

CATEGORY = "Explorador del historial de voz"
#: Origen con que se marcan en el historial de Tiresias las frases que dice el
#: propio explorador (al navegar): no cuentan como elementos nuevos.
ORIGIN = "speechHistoryExplorer"

#: Gestos. El original usa NVDA+Mayúsculas+F11/F12 (anterior/siguiente),
#: NVDA+Control+F12 (copiar) y NVDA+Alt+F12 (diálogo), pero en Tiresias
#: Tiresias+Mayúsculas+F11 ya es la lista de procesos: anterior y siguiente
#: van en Tiresias+Alt+F11/F12 (par simétrico y libre) y el diálogo pasa a
#: Tiresias+Mayúsculas+F12. Copiar conserva la tecla original.
GESTURE_PREVIOUS = "kb:tiresias+alt+f11"
GESTURE_NEXT = "kb:tiresias+alt+f12"
GESTURE_COPY = "kb:tiresias+control+f12"
GESTURE_DIALOG = "kb:tiresias+shift+f12"

EMPTY_MESSAGE = "El historial de voz está vacío"
SECURE_MESSAGE = "No se puede copiar en una pantalla segura"
COPY_FAILED_MESSAGE = "No se pudo copiar"

#: Pitidos (frecuencia, duración): extremo del historial y acción realizada.
EDGE_BEEP = (220, 100)
ACTION_BEEP = (1500, 120)


# ====================================================================== historial
def _originOf(entry) -> str:
	return entry[2] if len(entry) > 2 else ""


def historyEntries() -> list:
	"""Entradas del historial de Tiresias sin las frases del propio explorador (la más reciente al final)."""
	from tiresias.speech import api as speechApi

	return [e for e in speechApi.getHistory() if _originOf(e) != ORIGIN]


def historyTexts() -> list[str]:
	"""Textos del historial (el más reciente al final)."""
	return [e[1] for e in historyEntries()]


def clearHistory() -> None:
	from tiresias.speech import api as speechApi

	speechApi.clearHistory()


def trimText(text: str) -> str:
	"""Aplica a ``text`` el recorte de espacios configurado para copiar."""
	if options.get("trimWhitespaceFromStart"):
		text = text.lstrip()
	if options.get("trimWhitespaceFromEnd"):
		text = text.rstrip()
	return text


# ====================================================================== pitidos y voz
def beepLeft() -> None:
	from tiresias.audio import tones

	tones.beep(EDGE_BEEP[0], EDGE_BEEP[1], 100, 0)


def beepRight() -> None:
	from tiresias.audio import tones

	tones.beep(EDGE_BEEP[0], EDGE_BEEP[1], 0, 100)


def beepCenter(hz: float = ACTION_BEEP[0], ms: int = ACTION_BEEP[1]) -> None:
	from tiresias.audio import tones

	tones.beep(hz, ms)


def beepEdge(older: bool) -> None:
	"""Pitido al no haber más elementos: a la izquierda (más antiguos) o a la derecha (más recientes)."""
	if not options.get("beepWhenPerformingActions"):
		return
	if options.get("beepPanning"):
		(beepLeft if older else beepRight)()
	else:
		beepCenter(*EDGE_BEEP)


def beepAction() -> None:
	"""Pitido de acción realizada (copiar), si está activado."""
	if options.get("beepWhenPerformingActions"):
		beepCenter()


def speakItem(text: str) -> None:
	"""Dice un elemento del historial sin que cuente como elemento nuevo (origen propio)."""
	from tiresias.speech import api as speechApi

	with speechApi.speechOrigin(ORIGIN), speechApi.allowOnDemand():
		speechApi.speakText(text)


def speakNotice(text: str) -> None:
	"""Mensaje del explorador (tampoco cuenta como elemento del historial)."""
	from tiresias.speech import api as speechApi

	with speechApi.speechOrigin(ORIGIN), speechApi.allowOnDemand():
		speechApi.speakMessage(text)


# ====================================================================== portapapeles
def isSecureContext() -> bool:
	"""Modo seguro o pantalla de bloqueo: no se copia nada al portapapeles."""
	try:
		from tiresias.config.policy import policy

		if policy.secureMode:
			return True
	except Exception:
		pass
	try:
		from tiresias.a11y import system

		return bool(system.isLockScreenActive())
	except Exception:
		return False


def copyText(text: str) -> bool:
	"""Copia ``text`` al portapapeles (en el hilo del núcleo) y pita si está activado."""
	from tiresias import api

	if isSecureContext():
		speakNotice(SECURE_MESSAGE)
		return False
	ok = api.copyToClip(text)
	if ok:
		beepAction()
	else:
		speakNotice(COPY_FAILED_MESSAGE)
	return ok


# ====================================================================== complemento
class GlobalPlugin(_BaseGlobalPlugin):
	scriptCategory = CATEGORY

	def __init__(self) -> None:
		super().__init__()
		#: Instantánea de los textos del historial (el más reciente al final)
		#: sobre la que se navega; ``None`` hasta la primera orden.
		self._items: list[str] | None = None
		#: Posición: 0 es el más reciente, 1 el anterior, etc.
		self._pos = 0
		options.registerDefaults()
		try:
			options.registerPanel()
		except Exception:
			log.debug("No se pudo añadir la categoría del Explorador del historial de voz", exc_info=True)

	def terminate(self) -> None:
		try:
			options.unregisterPanel()
		except Exception:
			pass
		try:
			from . import dialog

			dialog.closeDialog()
		except Exception:
			log.debug("No se pudo cerrar el diálogo del historial", exc_info=True)
		super().terminate()

	# ---------------------------------------------------------------- posición
	@property
	def position(self) -> int:
		"""Índice del elemento actual desde el más reciente (0)."""
		return self._pos

	def resetPosition(self) -> None:
		"""Olvida la navegación: la próxima orden parte del elemento más reciente."""
		self._items = None
		self._pos = 0

	def _sync(self) -> list[str]:
		"""Vuelve al elemento más reciente si Tiresias ha dicho algo nuevo desde la última orden."""
		live = historyTexts()
		if self._items is None or live != self._items:
			self._items = live
			self._pos = 0
		return self._items

	def _itemAt(self, pos: int) -> str:
		items = self._items or []
		return items[len(items) - 1 - pos]

	def currentText(self) -> str | None:
		"""Texto del elemento actual (el más reciente si no se ha navegado), o ``None`` si no hay historial."""
		items = self._sync()
		if not items:
			return None
		self._pos = max(0, min(self._pos, len(items) - 1))
		return self._itemAt(self._pos)

	# ---------------------------------------------------------------- órdenes
	@script(
		description="Dice el elemento anterior (más antiguo) del historial de voz de Tiresias",
		category=CATEGORY,
		gesture=GESTURE_PREVIOUS,
		speakOnDemand=True,
	)
	def script_previousItem(self, gesture) -> None:
		items = self._sync()
		if not items:
			speakNotice(EMPTY_MESSAGE)
			return
		self._pos += 1
		if self._pos > len(items) - 1:
			beepEdge(older=True)
			self._pos -= 1
		speakItem(self._itemAt(self._pos))

	@script(
		description="Dice el elemento siguiente (más reciente) del historial de voz de Tiresias",
		category=CATEGORY,
		gesture=GESTURE_NEXT,
		speakOnDemand=True,
	)
	def script_nextItem(self, gesture) -> None:
		items = self._sync()
		if not items:
			speakNotice(EMPTY_MESSAGE)
			return
		self._pos -= 1
		if self._pos < 0:
			beepEdge(older=False)
			self._pos += 1
		speakItem(self._itemAt(self._pos))

	@script(
		description="Copia al portapapeles el elemento actual del historial de voz (el más reciente si no has navegado)",
		category=CATEGORY,
		gesture=GESTURE_COPY,
		speakOnDemand=True,
	)
	def script_copyItem(self, gesture) -> None:
		text = self.currentText()
		if text is None:
			speakNotice(EMPTY_MESSAGE)
			return
		copyText(trimText(text))

	@script(
		description="Abre el diálogo con los elementos recientes del historial de voz de Tiresias",
		category=CATEGORY,
		gesture=GESTURE_DIALOG,
	)
	def script_showHistory(self, gesture) -> None:
		from . import dialog

		dialog.showHistoryDialog(self)
