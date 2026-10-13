"""Base de los entornos de desarrollo de escritorio (Visual Studio, Eclipse).

- Lee el elemento seleccionado de las listas de autocompletado
  (IntelliSense, asistente de contenido) aunque el foco siga en el editor.
- Anuncia la línea nueva tras borrar o mover líneas con atajos (NVDA #6660).
"""

from __future__ import annotations

import time

from .. import api, presentation, speech, textinfo
from ..baseobject import normalizeGestureId
from ..i18n import _
from ..objects.roles import Role
from . import AppModule as BaseAppModule

CAT = _("Entornos de desarrollo")

#: Atajos que borran, mueven o duplican líneas (Visual Studio y Eclipse).
LINE_EDIT_GESTURES = (
	"kb:control+l",
	"kb:control+shift+l",
	"kb:control+d",
	"kb:control+e",
	"kb:alt+upArrow",
	"kb:alt+downArrow",
	"kb:control+alt+upArrow",
	"kb:control+alt+downArrow",
)


class IDEAppModule(BaseAppModule):
	#: Nombres (sin distinguir mayúsculas) de las listas de autocompletado.
	completionListNames: tuple[str, ...] = ("completion", "intellisense", "content assist", "asistente", "sugerencias", "suggestions")

	def __init__(self, processID: int, appName: str | None = None) -> None:
		super().__init__(processID, appName)
		self._lastCompletion = ("", 0.0)

	def isCompletionItem(self, obj) -> bool:
		try:
			if obj.role not in (Role.LISTITEM, Role.MENUITEM, Role.DATAITEM):
				return False
			focus = api.getFocusObject()
			if focus is None or focus.role not in (Role.EDITABLETEXT, Role.DOCUMENT):
				return False
			parent = obj.parent
			name = (parent.name if parent is not None else "").lower()
			aid = (getattr(parent, "UIAAutomationId", "") or "").lower()
			cls = (getattr(obj, "UIAClassName", "") or "").lower()
			return any(n in name or n in aid for n in self.completionListNames) or "intellisense" in cls or "completion" in cls
		except Exception:
			return False

	def event_selection(self, obj, nextHandler) -> None:
		if self.isCompletionItem(obj):
			name = obj.name
			now = time.monotonic()
			if name and not (name == self._lastCompletion[0] and now - self._lastCompletion[1] < 0.3):
				self._lastCompletion = (name, now)
				speech.cancelSpeech()
				presentation.speakObject(obj, reason=presentation.Reason.FOCUS)
			return
		nextHandler()

	def script_lineEdit(self, gesture) -> None:
		gesture.send()
		from .. import queue_handler

		def report() -> None:
			obj = api.getCaretObject()
			focus = api.getFocusObject()
			if focus is None or focus.role not in (Role.EDITABLETEXT, Role.DOCUMENT):
				# No es el editor (lista, cuadro combinado...): la tecla ya hizo lo suyo.
				return
			try:
				info = obj.makeTextInfo(textinfo.POSITION_CARET)
				info.expand(textinfo.UNIT_LINE)
			except Exception:
				return
			speech.cancelSpeech()
			presentation.speakTextInfo(info, textinfo.UNIT_LINE, reason=presentation.Reason.CARET)

		queue_handler.callLater(60, report)


IDEAppModule.script_lineEdit.__doc__ = _("En el editor: borra, mueve o duplica líneas con los atajos del entorno y lee la línea resultante")
IDEAppModule.script_lineEdit.category = CAT  # type: ignore[attr-defined]
for _g in LINE_EDIT_GESTURES:
	IDEAppModule._classGestures[normalizeGestureId(_g)] = "lineEdit"  # type: ignore[attr-defined]
