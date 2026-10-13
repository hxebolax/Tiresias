"""Discord.

Usa la base de chats (:mod:`._chat`): Alt+1 a Alt+0 para los últimos
mensajes del canal, modos de aviso y limitación de ráfagas de eventos al
desplazarse rápido por mensajes, que congelaban otros lectores (NVDA #18507).
"""

from __future__ import annotations

from ._chat import ChatAppModule


class AppModule(ChatAppModule):
	messageListHints = ("mensajes en", "messages in", "mensaje", "message")
