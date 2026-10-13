"""Telegram Desktop.

Usa la base de chats (:mod:`._chat`): Alt+1 a Alt+0 para los últimos
mensajes, modos de aviso e historial de avisos.
"""

from __future__ import annotations

from ._chat import ChatAppModule


class AppModule(ChatAppModule):
	messageListHints = ("historial", "history", "mensaje", "message")
