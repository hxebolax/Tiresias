"""Zoom Workplace.

Usa la base de chats (:mod:`._chat`): modos de aviso para las alertas de la
reunión (entradas y salidas, manos levantadas, silenciar, grabación,
compartir pantalla, chat) con Tiresias+Alt+Mayúsculas+A, historial de avisos
y Alt+1 a Alt+0 para los últimos mensajes del chat.
"""

from __future__ import annotations

from ._chat import ChatAppModule


class AppModule(ChatAppModule):
	messageListHints = ("chat", "mensaje", "message")

	def event_nameChange(self, obj, nextHandler) -> None:
		# Zoom anuncia muchas alertas cambiando el nombre de una etiqueta
		# emergente (no de una región viva).
		try:
			from ..objects.roles import Role

			role = obj.role
			if role == Role.STATICTEXT and obj.name:
				# Rev. 10.11: solo las etiquetas de un aviso; el indicador de quién
				# habla o el cronómetro de la reunión cambian sin parar.
				parent = obj.parent
				if parent is None or parent.role not in (Role.TOOLTIP, Role.ALERT, Role.DIALOG):
					nextHandler()
					return
			if role in (Role.TOOLTIP, Role.ALERT, Role.STATICTEXT) and obj.name:
				self.handleIncoming(obj.name, "nameChange")
				return
		except Exception:
			pass
		nextHandler()

	def event_tooltipOpen(self, obj, nextHandler) -> None:
		try:
			text = obj.name or obj.description
		except Exception:
			text = ""
		self.handleIncoming(text, "tooltip")
