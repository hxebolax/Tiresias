"""Configuración de Windows (``SystemSettings``).

La aplicación se ejecuta dentro de ``ApplicationFrameHost``: el gestor de
módulos la reconoce por el proceso que dibuja su contenido.

- Los grupos y vínculos que repiten su nombre en la descripción se leen una
  sola vez.
- Los conmutadores dicen su estado nuevo al cambiarlos con el espacio aunque
  Configuración no mueva el foco.
"""

from __future__ import annotations

from .. import api, presentation
from ..objects.roles import Role
from . import AppModule as BaseAppModule
from ._chat import normalize


class AppModule(BaseAppModule):
	def event_NVDAObject_init(self, obj) -> None:
		try:
			if obj.role in (Role.GROUPING, Role.LINK, Role.BUTTON, Role.LISTITEM, Role.TOGGLEBUTTON, Role.SWITCH):
				desc = obj.description
				if desc and normalize(desc) == normalize(obj.name):
					obj.description = ""
		except Exception:
			pass

	def event_stateChange(self, obj, nextHandler) -> None:
		# El conmutador puede ser un descendiente del elemento con el foco.
		try:
			focus = api.getFocusObject()
			if obj.role in (Role.SWITCH, Role.TOGGLEBUTTON, Role.CHECKBOX) and focus is not None and obj != focus and focus.role in (Role.LISTITEM, Role.GROUPING, Role.BUTTON):
				presentation.speakObjectProperties(obj, states=True, reason=presentation.Reason.CHANGE)
				return
		except Exception:
			pass
		nextHandler()
