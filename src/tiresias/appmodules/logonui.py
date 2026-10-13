"""Pantalla de inicio de sesión y de cambio de contraseña (``LogonUI``).

Al aparecer un diálogo (contraseña incorrecta, la contraseña caducó...) se
lee su texto completo, no solo el control con el foco.

Nota: Tiresias, como cualquier programa sin firma ``uiAccess``, solo puede
leer esta pantalla cuando se muestra en el escritorio del usuario (por
ejemplo, al cambiar la contraseña con Control+Alt+Supr desde la sesión).
"""

from __future__ import annotations

from .. import speech
from ..objects.roles import Role
from . import AppModule as BaseAppModule


class AppModule(BaseAppModule):
	def event_foreground(self, obj, nextHandler) -> None:
		nextHandler()
		texts = []
		try:
			for c in obj.children:
				if c.role == Role.STATICTEXT and c.name:
					texts.append(c.name)
		except Exception:
			pass
		if texts:
			speech.speakText(" ".join(texts))
