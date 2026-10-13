# -*- coding: utf-8 -*-
# Copyright (C) 2025-2026 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General GNU.

"""zRadio BASS para Tiresias: reproductor de radios en línea con motor BASS.

- Búsqueda de emisoras por nombre, país, idioma y etiqueta (API de Radio Browser).
- Favoritos con categorías, notas, orden y contador de reproducciones.
- Historial de reproducción.
- Grabación de emisoras a WAV y grabaciones programadas.
- Volumen, silencio, pausa, dispositivo de salida, ecualizador y balance.
- Sistema de plugins (incluye un plugin de ejemplo y otro de estadísticas).

Las órdenes no tienen gesto asignado (como en el original): se asignan en
Tiresias > Preferencias > Gestos de entrada > «zRadio BASS».
"""

from __future__ import annotations

import os
import threading

from tiresias.baseobject import script
from tiresias.log import getLogger
from tiresias.plugins import GlobalPlugin as _BaseGlobalPlugin

log = getLogger("zRadioBASS")

CATEGORY = "zRadio BASS"
ADDON_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
README = os.path.join(ADDON_DIR, "doc", "es", "readme.html")
TOOLS_MENU_ID = "zRadioBASS"


def _secureMode() -> bool:
	try:
		from tiresias.config import policy

		return bool(policy.policy.secureMode)
	except Exception:
		return False


def _speak(text: str) -> None:
	"""Habla un mensaje (las órdenes se ejecutan en el hilo del núcleo)."""
	from tiresias import queue_handler, speech

	if text:
		queue_handler.queueFunction(speech.speakMessage, text)


class GlobalPlugin(_BaseGlobalPlugin):
	"""Complemento global de zRadio BASS."""

	def __init__(self) -> None:
		super().__init__()
		self._app = None
		self._main_window = None
		self._opening = False
		if _secureMode():
			log.info("zRadio BASS no se activa en modo seguro")
			return
		from .zr_core.app import RadioApp
		from .zr_core.config import ConfigManager, set_config

		config = ConfigManager()
		set_config(config)
		self._app = RadioApp(config, speak=_speak)
		self._app.message = self._message
		try:
			from .zr_ui import settings_panel

			settings_panel.register(lambda: self._app)
		except Exception:
			log.exception("No se pudo añadir la categoría de zRadio BASS a las opciones")
		try:
			from tiresias import gui

			gui.registerToolsMenuItem(TOOLS_MENU_ID, "&zRadio BASS", self._show_main_window)
		except Exception:
			log.exception("No se pudo añadir zRadio BASS al menú Herramientas")
		self._app.startup()
		log.info("zRadio BASS inicializado correctamente")

	def terminate(self) -> None:
		if self._app is None:
			return
		try:
			from tiresias import gui

			gui.unregisterToolsMenuItem(TOOLS_MENU_ID)
		except Exception:
			pass
		try:
			from .zr_ui import settings_panel

			settings_panel.unregister()
		except Exception:
			pass
		win, self._main_window = self._main_window, None
		if win is not None:
			from tiresias.gui.helpers import isAlive, runOnGui

			def destroy() -> None:
				if isAlive(win):
					win.destroy()

			runOnGui(destroy)
		try:
			self._app.terminate()
		except Exception:
			log.exception("Error terminando zRadio BASS")
		from .zr_core import events
		from .zr_core.config import set_config

		set_config(None)
		events.reset_event_bus()
		self._app = None
		super().terminate()

	# ------------------------------------------------------------- interfaz
	def _message(self, text: str, title: str = "", error: bool = False) -> None:
		"""Cuadro de mensaje desde cualquier hilo (lo usan los plugins)."""
		from tiresias.gui.helpers import runOnGui

		def show() -> None:
			from .zr_ui.dialogs import show_error, show_info

			parent = self._visible_window()
			(show_error if error else show_info)(text, title or "zRadio BASS", parent)

		runOnGui(show)

	def _visible_window(self):
		"""La ventana principal si está abierta (para usarla como padre de los diálogos)."""
		from tiresias.gui.helpers import isAlive

		win = self._main_window
		try:
			return win if isAlive(win) and win.IsShown() else None
		except RuntimeError:
			return None

	def _show_main_window(self) -> None:
		"""Abre la ventana principal (comprueba Internet antes si está activado)."""
		app = self._app
		if app is None or self._opening:
			return
		if app.config.checkInternetOnStart:
			self._opening = True

			def check() -> None:
				ok = app.internet.is_connected(force_check=True)
				from tiresias.gui.helpers import runOnGui

				runOnGui(self._open_window, ok)

			threading.Thread(target=check, daemon=True, name="zRadioBASS-internet").start()
		else:
			from tiresias.gui.helpers import runOnGui

			runOnGui(self._open_window, True)

	def _open_window(self, connected: bool) -> None:
		self._opening = False
		app = self._app
		if app is None:
			return
		from .zr_core.events import EventType
		from .zr_ui.dialogs import show_error

		app.event_bus.emit(EventType.INTERNET_CONNECTED if connected else EventType.INTERNET_DISCONNECTED, None)
		if not connected:
			show_error("zRadio necesita conexión a Internet para funcionar.\nVerifique su conexión e intente nuevamente.", "Sin conexión")
			return
		from tiresias.gui.helpers import isAlive

		from .zr_ui.main_window import MainWindow

		if not isAlive(self._main_window):
			self._main_window = MainWindow(None, app, open_settings=self._open_settings, readme_path=README)
		self._main_window.show_and_focus()

	@staticmethod
	def _open_settings() -> None:
		from tiresias import gui

		from .zr_ui import settings_panel

		gui.showSettings(settings_panel.PANEL_ID)

	def _schedule_dialog(self) -> None:
		from .zr_ui.dialogs import schedule_recording_dialog

		parent = self._visible_window()
		if schedule_recording_dialog(parent, self._app):
			_speak("Grabación programada")

	def _scheduled_list(self) -> None:
		from .zr_ui.dialogs import ScheduledRecordingsDialog, show_modal

		parent = self._visible_window()
		dlg = ScheduledRecordingsDialog(parent, self._app)
		try:
			show_modal(dlg)
		finally:
			dlg.Destroy()

	# ------------------------------------------------------------- órdenes
	def _ready(self) -> bool:
		if self._app is None:
			_speak("zRadio BASS no está disponible")
			return False
		return True

	@script(description="Muestra la ventana principal de zRadio BASS", category=CATEGORY)
	def script_show_main_window(self, gesture) -> None:
		if self._ready():
			self._show_main_window()

	@script(description="Bajar volumen de la radio", category=CATEGORY)
	def script_volume_down(self, gesture) -> None:
		if self._ready():
			_speak(self._app.volume_step(-1))

	@script(description="Subir volumen de la radio", category=CATEGORY)
	def script_volume_up(self, gesture) -> None:
		if self._ready():
			_speak(self._app.volume_step(1))

	@script(description="Detener reproducción de la radio", category=CATEGORY)
	def script_stop(self, gesture) -> None:
		if not self._ready():
			return
		_speak("Reproducción detenida" if self._app.stop() else "No hay nada reproduciéndose")

	@script(description="Pausar o reanudar la radio", category=CATEGORY)
	def script_toggle_pause(self, gesture) -> None:
		if self._ready():
			_speak(self._app.toggle_pause())

	@script(description="Recargar la emisora actual", category=CATEGORY)
	def script_reload(self, gesture) -> None:
		if not self._ready():
			return
		_speak("Recargando emisora..." if self._app.reload() else "No hay ninguna emisora para recargar")

	@script(description="Silenciar o restaurar el audio", category=CATEGORY)
	def script_toggle_mute(self, gesture) -> None:
		if not self._ready():
			return
		if not self._app.player.is_active:
			_speak("No hay nada para silenciar")
			return
		_speak("Silenciado" if self._app.toggle_mute() else "Silencio desactivado")

	@script(description="Anunciar la emisora en reproducción", category=CATEGORY)
	def script_current_station(self, gesture) -> None:
		if self._ready():
			_speak(self._app.current_station_message())

	@script(description="Anunciar el título de la canción que suena", category=CATEGORY)
	def script_current_title(self, gesture) -> None:
		if self._ready():
			_speak(self._app.current_title_message())

	@script(description="Anunciar información del estado del reproductor", category=CATEGORY)
	def script_player_status(self, gesture) -> None:
		if self._ready():
			_speak(self._app.status_message())

	@script(description="Anunciar estado de grabación", category=CATEGORY)
	def script_recording_status(self, gesture) -> None:
		if self._ready():
			_speak(self._app.recording_status_message())

	@script(description="Iniciar grabación de la emisora actual", category=CATEGORY)
	def script_start_recording(self, gesture) -> None:
		if not self._ready():
			return
		ok, msg = self._app.start_recording_current()
		_speak("Grabación iniciada" if ok else msg)

	@script(description="Detener grabación actual", category=CATEGORY)
	def script_stop_recording(self, gesture) -> None:
		if not self._ready():
			return
		if not self._app.player.is_recording:
			_speak("No hay ninguna grabación activa")
			return
		_speak("Grabación guardada" if self._app.stop_recording_current() else "Grabación detenida")

	@script(description="Abrir diálogo para programar grabación", category=CATEGORY)
	def script_schedule_recording(self, gesture) -> None:
		if self._ready():
			from tiresias.gui.helpers import runOnGui

			runOnGui(self._schedule_dialog)

	@script(description="Ver las grabaciones programadas", category=CATEGORY)
	def script_scheduled_recordings(self, gesture) -> None:
		if self._ready():
			from tiresias.gui.helpers import runOnGui

			runOnGui(self._scheduled_list)

	@script(description="Reproducir la última emisora escuchada", category=CATEGORY)
	def script_play_last_station(self, gesture) -> None:
		if not self._ready():
			return
		c = self._app.config
		if not c.rememberLastStation or not c.last_station_url:
			_speak("No hay ninguna emisora recordada")
			return
		self._app.play_last_station(announce=False)
		_speak(c.last_station_name or c.last_station_url)

	def _play_favorite(self, position: int) -> None:
		if self._ready():
			_speak(self._app.play_favorite(position) or "")

	@script(description="Reproducir favorito 1", category=CATEGORY)
	def script_play_favorite_1(self, gesture) -> None:
		self._play_favorite(1)

	@script(description="Reproducir favorito 2", category=CATEGORY)
	def script_play_favorite_2(self, gesture) -> None:
		self._play_favorite(2)

	@script(description="Reproducir favorito 3", category=CATEGORY)
	def script_play_favorite_3(self, gesture) -> None:
		self._play_favorite(3)

	@script(description="Reproducir favorito 4", category=CATEGORY)
	def script_play_favorite_4(self, gesture) -> None:
		self._play_favorite(4)

	@script(description="Reproducir favorito 5", category=CATEGORY)
	def script_play_favorite_5(self, gesture) -> None:
		self._play_favorite(5)

	@script(description="Reproducir siguiente favorito", category=CATEGORY)
	def script_next_favorite(self, gesture) -> None:
		if self._ready():
			_speak(self._app.next_favorite(1))

	@script(description="Reproducir favorito anterior", category=CATEGORY)
	def script_previous_favorite(self, gesture) -> None:
		if self._ready():
			_speak(self._app.next_favorite(-1))
