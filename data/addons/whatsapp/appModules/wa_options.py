"""Opciones del complemento WhatsApp accesible (sección ``whatsapp``).

Las comparten el módulo de la aplicación (``whatsapp_root``), su diálogo de
ajustes (Alt+Mayúsculas+S) y la categoría «WhatsApp accesible» del diálogo de
Opciones de Tiresias (``globalPlugins/whatsapp_opciones.py``).
"""

from __future__ import annotations

from tiresias.config import conf
from tiresias.i18n import _

SECTION = "whatsapp"

DEFAULTS = {
	"filterHints": True,
	"filterPhoneNumbersInChats": False,
	"filterPhoneNumbersInMessages": True,
	"filterMaybePrefix": True,
	"autoReadNewMessages": True,
	"autoReadInBackground": False,
	"announceTyping": True,
	"newMessageSound": True,
	"silenceTableRoles": True,
}

#: (clave, etiqueta) de cada casilla, en el orden en que se muestran.
SETTINGS = [
	("filterHints", _("Ocultar las pistas de uso («Para más opciones…»)")),
	("filterPhoneNumbersInChats", _("Ocultar números de teléfono en la lista de chats")),
	("filterPhoneNumbersInMessages", _("Ocultar números de teléfono en los mensajes")),
	("filterMaybePrefix", _("Quitar el prefijo «Quizás» de los contactos no guardados")),
	("silenceTableRoles", _("No anunciar «fila», «celda» ni la posición en la lista de chats")),
	("autoReadNewMessages", _("Leer automáticamente los mensajes nuevos del chat abierto")),
	("autoReadInBackground", _("Leer mensajes nuevos aunque WhatsApp no esté en primer plano")),
	("announceTyping", _("Avisar cuando el contacto está escribiendo o grabando")),
	("newMessageSound", _("Sonido al llegar un mensaje nuevo")),
]


def registerDefaults() -> None:
	conf.registerDefaults(SECTION, DEFAULTS)


registerDefaults()
