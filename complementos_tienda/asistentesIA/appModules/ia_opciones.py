"""Opciones del complemento «Asistentes de IA accesibles» (sección ``asistentesIA``).

Las comparten los módulos de aplicación y la categoría del mismo nombre del
diálogo de Opciones de Tiresias (``globalPlugins/asistentesia_opciones.py``).
"""

from __future__ import annotations

from tiresias.config import conf
from tiresias.i18n import _

SECTION = "asistentesIA"

DEFAULTS = {
	"anunciarFin": True,
	"sonidoFin": True,
	"avisarEnSegundoPlano": True,
	"leerRespuesta": False,
}

#: (clave, etiqueta) de cada casilla, en el orden en que se muestran.
SETTINGS = [
	("anunciarFin", _("Avisar cuando el asistente termina de trabajar")),
	("sonidoFin", _("Sonido al terminar")),
	("avisarEnSegundoPlano", _("Avisar también si la aplicación no está en primer plano")),
	("leerRespuesta", _("Leer la respuesta automáticamente al terminar")),
]


def registerDefaults() -> None:
	conf.registerDefaults(SECTION, DEFAULTS)


registerDefaults()
