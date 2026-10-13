"""Plugins de extensión (cada archivo define clases que heredan de ``PluginBase``)."""

from ..nucleo.gestor_plugins import InfoPlugin, PluginBase, TipoPlugin

__all__ = ["PluginBase", "TipoPlugin", "InfoPlugin"]
