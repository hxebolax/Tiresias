"""Búsqueda y menú Inicio de Windows 10 y 11.

Un solo módulo para ``SearchHost``, ``SearchApp``, ``SearchUI`` y
``StartMenuExperienceHost`` (alias en ``EXECUTABLE_ALIASES``): antes había
dos archivos idénticos que además cortaban la cadena de eventos.

Al escribir en la búsqueda, el resultado resaltado cambia de selección sin
recibir el foco: se lee una sola vez cada vez que cambia.
"""

from __future__ import annotations

import time

from .. import api, presentation, speech
from ..objects.roles import Role
from . import AppModule as BaseAppModule


class AppModule(BaseAppModule):
	#: Rev. 10.11: los resultados son una página WebView2; si su documento
	#: recibe un foco falso, las letras que se escriben en la búsqueda no deben
	#: convertirse en navegación rápida (NVDA #17951).
	disableBrowseModeByDefault = True

	def __init__(self, processID: int, appName: str | None = None) -> None:
		super().__init__(processID, appName)
		self._last = (None, 0.0)

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
			self._last = (rid, now)
			try:
				# Rev. 10.11: la lista de sugerencias (SelectableItem) no lo repite.
				from ..objects import behaviors

				behaviors._noteAnnounced(obj.name or "")
			except Exception:
				pass
			speech.cancelSpeech()
			presentation.speakObject(obj, reason=presentation.Reason.FOCUS)
		nextHandler()
