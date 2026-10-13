"""Microsoft Teams (nuevo y clásico).

Usa la base de chats (:mod:`._chat`): Alt+1 a Alt+0 para los últimos
mensajes, modos de aviso para las reuniones y eliminación de lecturas dobles
de tarjetas adaptables y avisos (NVDA #14448).
"""

from __future__ import annotations

from ._chat import ChatAppModule


class AppModule(ChatAppModule):
	messageListHints = ("mensajes de chat", "chat messages", "historial de chat", "chat history", "mensaje", "message")
	# Teams es una aplicación web: mejor en modo foco (el usuario puede pasar
	# a modo exploración con Tiresias+Espacio para leer mensajes largos).
	disableBrowseModeByDefault = True
