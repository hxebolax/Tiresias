"""Textos de la interfaz de WhatsApp en varios idiomas.

WhatsApp no expone identificadores estables para muchos elementos, así que
algunos se localizan por su nombre. Las listas admiten varios idiomas y se
comparan sin distinguir mayúsculas ni tildes. Si una versión de WhatsApp
cambia un texto, basta con añadirlo aquí.
"""

from __future__ import annotations

import re
import unicodedata


def normalize(text: str) -> str:
	text = unicodedata.normalize("NFKD", text or "")
	text = "".join(c for c in text if not unicodedata.combining(c))
	return text.lower().replace("…", "...").strip()


CHAT_LIST = ["Lista de chats", "Chat list"]
SEARCH_BOX = ["Buscar un chat o iniciar uno nuevo", "Search or start a new chat", "Buscar"]
COMPOSE_BOX = ["Escribe un mensaje", "Escribe un mensaje aquí", "Type a message", "Mensaje"]
VOICE_CALL = ["Llamada de voz", "Llamada", "Voice call", "Llamar"]
VIDEO_CALL = ["Videollamada", "Video call"]
ACCEPT_CALL = ["Aceptar", "Responder", "Contestar", "Accept", "Answer", "Accept call", "Answer call"]
DECLINE_CALL = ["Rechazar", "Colgar", "Decline", "Reject", "Decline call", "Reject call", "End call", "Finalizar llamada"]
READ_MORE = ["Leer más", "Read more", "Ver más"]
PLAY = ["Reproducir", "Play", "Reproducir mensaje de voz", "Play voice message"]
PAUSE = ["Pausar", "Pause", "Pausa"]
CLOSE = ["Cerrar", "Close"]
DELETE_RECORDING = ["Eliminar", "Descartar", "Delete", "Discard", "Cancelar grabación"]
REACT = ["Reaccionar", "React", "Reacciones", "Reactions"]
MENU = ["Menú", "Menu", "Más opciones", "More options", "Menú contextual", "Context menu"]
TYPING = ["escribiendo", "typing", "grabando audio", "recording audio", "grabando", "recording"]
ONLINE = ["en línea", "online"]
UNREAD_DIVIDER = re.compile(r"(\d+)\s+(mensajes? no leídos?|unread messages?|mensajes? nuevos?|new messages?)", re.I)
DELIVERY = {
	"leído": "leído",
	"leido": "leído",
	"read": "leído",
	"entregado": "entregado",
	"delivered": "entregado",
	"enviado": "enviado",
	"sent": "enviado",
	"pendiente": "pendiente",
	"pending": "pendiente",
}

#: Pista que WhatsApp añade a cada mensaje y fila.
HINT_RE = re.compile(
	r"(para (m[aá]s|ver m[aá]s) opciones[^.]*\.?|for more options[^.]*\.?|pulsa (la tecla de )?flecha[^.]*\.?)",
	re.I,
)
#: Números de teléfono (contactos no guardados).
PHONE_RE = re.compile(r"\+?\d[\d\s()\u202a\u202c\u200e\u200f\-]{7,}\d")
#: Prefijo de contacto no guardado (palabra completa: «Maybelline» no lo es).
MAYBE_RE = re.compile(r"^\s*(quiz[aá]s|maybe|talvez)\b\s*", re.I)
#: Un texto que es solo un número de teléfono (el remitente de un contacto no guardado).
ONLY_PHONE_RE = re.compile(r"^\s*~?\s*\+?\d[\d\s()\u202a\u202c\u200e\u200f\-]{7,}\d\s*$")
#: Textos que no aportan nada.
NOISE_RE = re.compile(r"\b(Se fijó el chat\.?|Chat fijado\.?|Pinned chat\.?)", re.I)


def matches(name: str, candidates: list[str], exact: bool = False) -> bool:
	n = normalize(name)
	for c in candidates:
		cn = normalize(c)
		if (n == cn) if exact else (n == cn or n.startswith(cn)):
			return True
	return False


def contains(name: str, candidates: list[str]) -> bool:
	n = normalize(name)
	return any(normalize(c) in n for c in candidates)
