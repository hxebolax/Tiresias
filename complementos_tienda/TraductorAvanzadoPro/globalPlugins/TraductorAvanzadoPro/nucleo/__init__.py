"""Núcleo del Traductor Avanzado Pro: configuración, plugins, traductores, caché e historial."""

from .cache import GestorCache
from .configuracion import GestorConfiguracion
from .gestor_plugins import GestorPlugins
from .gestor_traductores import GestorTraductores
from .historial import GestorHistorial

__all__ = ["GestorConfiguracion", "GestorPlugins", "GestorTraductores", "GestorCache", "GestorHistorial"]
