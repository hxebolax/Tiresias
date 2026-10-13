# -*- coding: utf-8 -*-
# Copyright (C) 2025-2026 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General GNU.

"""Plugin de ejemplo de zRadio BASS.

Sirve de referencia para escribir plugins propios. Muestra cómo:

- definir los metadatos del plugin;
- suscribirse a eventos (``self.subscribe``: se cancelan solos al descargar);
- añadir elementos al submenú Plugins y al menú contextual de las listas;
- tener opciones propias que se guardan (``self.settings`` y ``self.save_settings()``)
  con un panel de configuración (``get_settings_panel``);
- hablar y mostrar mensajes con ``self.app``.

Para crear uno nuevo, copie este archivo en ``data\\addonsData\\zRadioBASS\\plugins``,
cambie ``PLUGIN_ID`` y el nombre de la clase, y use «Recargar plugins» en el
administrador de plugins (Herramientas > Plugins > Administrar plugins...).
"""

from __future__ import annotations

from typing import Any

from zradiobass import EventType, PluginBase, Station, log


class ExamplePlugin(PluginBase):
	"""Plugin de demostración para desarrolladores."""

	PLUGIN_ID = "example_plugin"
	PLUGIN_NAME = "Plugin de ejemplo"
	PLUGIN_VERSION = "1.0.0"
	PLUGIN_AUTHOR = "Héctor J. Benítez Corredera"
	PLUGIN_DESCRIPTION = "Plugin de demostración para desarrolladores"

	def on_load(self) -> bool:
		log.info("Cargando plugin: %s", self.PLUGIN_NAME)
		self.subscribe(EventType.PLAYBACK_STARTED, self._on_playback_started)
		self.subscribe(EventType.PLAYBACK_STOPPED, self._on_playback_stopped)
		return True

	def on_unload(self) -> bool:
		log.info("Descargando plugin: %s", self.PLUGIN_NAME)
		return True

	# ------------------------------------------------------------- eventos
	def _on_playback_started(self, station: Station | None) -> None:
		name = station.name if station is not None else "desconocida"
		log.debug("[Plugin de ejemplo] Reproduciendo: %s", name)
		if self.settings.get("announce", False) and self.app is not None:
			self.app.speak(f"Plugin de ejemplo: empieza a sonar {name}")

	def _on_playback_stopped(self, data: Any = None) -> None:
		log.debug("[Plugin de ejemplo] Reproducción detenida")

	# ------------------------------------------------------------- menús
	def get_menu_items(self) -> list[dict[str, Any]]:
		return [{"label": "Acerca del plugin de ejemplo...", "callback": self._show_about}]

	def get_context_menu_items(self, context: str) -> list[dict[str, Any]]:
		if context == "station":
			return [{"label": "[Ejemplo] Información adicional", "callback": self._show_station_info}]
		return []

	def _show_about(self, event: Any = None) -> None:
		text = f"Este es un plugin de demostración.\n\nVersión: {self.PLUGIN_VERSION}\nAutor: {self.PLUGIN_AUTHOR}"
		if self.app is not None:
			self.app.message(text, "Acerca del plugin de ejemplo", False)

	def _show_station_info(self, station: Station | None = None) -> None:
		if station is None:
			text = "Esta función podría mostrar información adicional sobre la emisora seleccionada."
		else:
			text = (
				f"Esta función podría mostrar información adicional sobre la emisora seleccionada.\n\n"
				f"Emisora: {station.name}\nDirección: {station.url}"
			)
		if self.app is not None:
			self.app.message(text, "Información", False)

	# ------------------------------------------------------------- opciones
	def get_settings_panel(self, parent: Any) -> Any:
		import wx

		plugin = self

		class Panel(wx.Panel):
			def __init__(self, parent: Any) -> None:
				super().__init__(parent)
				sizer = wx.BoxSizer(wx.VERTICAL)
				self.check = wx.CheckBox(self, label="&Anunciar cada emisora que empiece a sonar")
				self.check.SetValue(bool(plugin.settings.get("announce", False)))
				sizer.Add(self.check, 0, wx.ALL, 6)
				self.SetSizer(sizer)

			def save(self) -> None:
				plugin.settings["announce"] = self.check.GetValue()
				plugin.save_settings()

		return Panel(parent)
