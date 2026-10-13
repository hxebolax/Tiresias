"""Panel de entrada de Windows (``TextInputHost``): emojis, historial del portapapeles e IME.

- Panel de emojis (Windows+punto): se lee el emoji, kaomoji o símbolo
  seleccionado al moverse, aunque el foco siga en el campo donde se escribe,
  y la categoría al cambiarla.
- Historial del portapapeles (Windows+V): se anuncia al abrirse y se leen sus
  elementos.
- Candidatos del IME (chino, japonés, coreano): se lee el candidato
  seleccionado.
- Teclado táctil: se anuncia al aparecer.
"""

from __future__ import annotations

import time

from .. import presentation, speech
from ..objects.roles import Role
from . import AppModule as BaseAppModule


class AppModule(BaseAppModule):
	def __init__(self, processID: int, appName: str | None = None) -> None:
		super().__init__(processID, appName)
		self._last = ("", 0.0)

	def _speakOnce(self, obj, text: str) -> None:
		now = time.monotonic()
		if not text or (text == self._last[0] and now - self._last[1] < 0.4):
			return
		self._last = (text, now)
		speech.cancelSpeech()
		presentation.speakObject(obj, reason=presentation.Reason.FOCUS)

	def event_selection(self, obj, nextHandler) -> None:
		try:
			if obj.role in (Role.LISTITEM, Role.TAB, Role.BUTTON, Role.DATAITEM, Role.MENUITEM):
				self._speakOnce(obj, obj.name)
				return
		except Exception:
			pass
		nextHandler()

	def event_windowOpened(self, obj, nextHandler) -> None:
		try:
			name = obj.name
		except Exception:
			name = ""
		if name:
			speech.speakText(name)
		nextHandler()

	def event_nameChange(self, obj, nextHandler) -> None:
		# Algunos elementos del panel de emojis solo cambian de nombre al
		# moverse (la casilla de vista previa).
		try:
			if obj.role in (Role.LISTITEM, Role.STATICTEXT) and getattr(obj, "UIAAutomationId", "") in ("PreviewText", "SkinTonePreview"):
				self._speakOnce(obj, obj.name)
				return
		except Exception:
			pass
		nextHandler()
