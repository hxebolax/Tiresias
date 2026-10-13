# -*- coding: utf-8 -*-
# Copyright (C) 2025-2026 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General GNU.

"""Ventana principal de zRadio BASS.

Pestañas General, Favoritos, Buscador e Historial; controles de
reproducción (Detener, Pausar, Recargar, Silenciar, Volumen), estado de lo
que suena y botones Herramientas, Ayuda y Cerrar. Al cerrarla (Escape) solo
se oculta: la radio sigue sonando.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Callable

import wx

from tiresias.gui.helpers import bringToFront, isAlive, speakMessage
from tiresias.log import getLogger

from ..zr_core.events import EventType
from ..zr_core.player import STATE_NAMES, PlayerState, format_duration
from .dialogs import (
	PluginsDialog,
	ScheduledRecordingsDialog,
	clear_history_dialog,
	run_in_thread,
	schedule_recording_dialog,
	server_stats_text,
	show_confirm,
	show_error,
	show_info,
)
from .panels import FavoritesPanel, GeneralPanel, HistoryPanel, SearchPanel, popup_menu

if TYPE_CHECKING:
	from ..zr_core.app import RadioApp

log = getLogger("zRadioBASS.ui")

HELP_TEXT = (
	"zRadio BASS para Tiresias\n\n"
	"Use las pestañas para navegar entre secciones (Control+1 a Control+4 van directamente a cada una).\n"
	"Pulse Intro o Espacio para reproducir una emisora y F1 para saber su posición en la lista.\n"
	"Use el menú contextual (tecla Aplicaciones o Mayúsculas+F10) para más opciones: favoritos, información, copiar la URL, votar, programar una grabación.\n"
	"En Favoritos, Alt+Flecha arriba y Alt+Flecha abajo mueven la emisora y Suprimir la elimina.\n"
	"Alt+V lleva al volumen. Escape cierra la ventana; la radio sigue sonando.\n\n"
	"Grabación:\n"
	"- Puede grabar la emisora actual desde el botón Herramientas > Grabación.\n"
	"- Las grabaciones se guardan en formato WAV.\n"
	"- Puede programar grabaciones para un horario específico; se graban aunque no esté escuchando nada.\n\n"
	"El manual completo está en el botón Ayuda > Abrir el manual, o en el Administrador de complementos."
)


def _calculate_position(width: int, height: int) -> tuple[int, int]:
	sw = wx.SystemSettings.GetMetric(wx.SYS_SCREEN_X)
	sh = wx.SystemSettings.GetMetric(wx.SYS_SCREEN_Y)
	return max(0, (sw - width) // 2), max(0, (sh - height) // 2)


class MainWindow(wx.Dialog):
	"""Ventana principal (no modal)."""

	def __init__(self, parent: wx.Window | None, app: "RadioApp", open_settings: Callable[[], None] | None = None, readme_path: str = "") -> None:
		self._app = app
		self._config = app.config
		self._open_settings = open_settings
		self._readme = readme_path
		self._unsubs: list[Callable[[], None]] = []
		width = max(500, int(self._config.window_width))
		height = max(400, int(self._config.window_height))
		super().__init__(
			parent,
			title="zRadio BASS",
			pos=_calculate_position(width, height),
			size=(width, height),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX | wx.MINIMIZE_BOX,
		)
		self._init_ui()
		self._setup_events()
		self._sync_player_state()
		app.event_bus.emit(EventType.WINDOW_OPENED, None)

	# ------------------------------------------------------------- interfaz
	def _init_ui(self) -> None:
		panel = wx.Panel(self)
		self._panel = panel
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.notebook = wx.Notebook(panel)
		self.panel_general = GeneralPanel(self.notebook, self._app)
		self.notebook.AddPage(self.panel_general, "General")
		self.panel_favorites = FavoritesPanel(self.notebook, self._app)
		self.notebook.AddPage(self.panel_favorites, "Favoritos")
		self.panel_search = SearchPanel(self.notebook, self._app)
		self.notebook.AddPage(self.panel_search, "Buscador")
		self.panel_history = HistoryPanel(self.notebook, self._app)
		self.notebook.AddPage(self.panel_history, "Historial")
		sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 5)

		row = wx.BoxSizer(wx.HORIZONTAL)
		self.btn_stop = wx.Button(panel, label="&Detener")
		self.btn_pause = wx.Button(panel, label="Pa&usar")
		self.btn_reload = wx.Button(panel, label="&Recargar")
		self.btn_mute = wx.Button(panel, label="&Silenciar")
		for b in (self.btn_stop, self.btn_pause, self.btn_reload, self.btn_mute):
			row.Add(b, 1, wx.ALL, 5)
		row.Add(wx.StaticText(panel, label="&Volumen:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 10)
		self.slider_volume = wx.Slider(panel, value=self._app.player.volume, minValue=0, maxValue=100, style=wx.SL_HORIZONTAL)
		self.slider_volume.SetLineSize(1)
		self.slider_volume.SetPageSize(max(1, int(self._config.volumeStep)))
		self.slider_volume.SetName("Volumen")
		row.Add(self.slider_volume, 2, wx.ALL | wx.EXPAND, 5)
		sizer.Add(row, 0, wx.EXPAND)

		sizer.Add(wx.StaticText(panel, label="Estado:"), 0, wx.LEFT | wx.RIGHT, 8)
		self.txt_status = wx.TextCtrl(panel, size=(-1, 60), style=wx.TE_MULTILINE | wx.TE_READONLY)
		self.txt_status.SetName("Estado")
		sizer.Add(self.txt_status, 0, wx.EXPAND | wx.ALL, 5)

		row = wx.BoxSizer(wx.HORIZONTAL)
		self.btn_tools = wx.Button(panel, label="&Herramientas")
		self.btn_help = wx.Button(panel, wx.ID_HELP, "A&yuda")
		self.btn_close = wx.Button(panel, wx.ID_CANCEL, "&Cerrar")
		for b in (self.btn_tools, self.btn_help, self.btn_close):
			row.Add(b, 1, wx.ALL, 5)
		sizer.Add(row, 0, wx.EXPAND)
		panel.SetSizer(sizer)
		self.SetEscapeId(wx.ID_NONE)
		last = int(self._config.last_tab)
		if 0 <= last < self.notebook.GetPageCount():
			self.notebook.SetSelection(last)

	def _setup_events(self) -> None:
		self.Bind(wx.EVT_CLOSE, self._on_close)
		self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
		self.Bind(wx.EVT_SHOW, self._on_show)
		self.Bind(wx.EVT_SIZE, self._on_size)
		self.btn_stop.Bind(wx.EVT_BUTTON, self._on_stop)
		self.btn_pause.Bind(wx.EVT_BUTTON, self._on_pause)
		self.btn_reload.Bind(wx.EVT_BUTTON, self._on_reload)
		self.btn_mute.Bind(wx.EVT_BUTTON, self._on_mute)
		self.slider_volume.Bind(wx.EVT_SLIDER, self._on_volume_change)
		self.btn_tools.Bind(wx.EVT_BUTTON, self._on_show_tools_menu)
		self.btn_help.Bind(wx.EVT_BUTTON, self._on_help)
		self.btn_close.Bind(wx.EVT_BUTTON, lambda e: self._on_close(None))
		self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self._on_tab_changed)
		# Tiempo de grabación y título al día mientras la ventana está abierta.
		self._timer = wx.Timer(self)
		self.Bind(wx.EVT_TIMER, self._on_timer, self._timer)
		self._timer.Start(2000)
		bus = self._app.event_bus
		for et in (
			EventType.PLAYBACK_STARTED,
			EventType.PLAYBACK_STOPPED,
			EventType.PLAYBACK_PAUSED,
			EventType.PLAYBACK_RESUMED,
			EventType.PLAYBACK_ERROR,
			EventType.BUFFERING_STARTED,
			EventType.BUFFERING_ENDED,
			EventType.METADATA_UPDATED,
			EventType.RECORDING_STARTED,
			EventType.RECORDING_STOPPED,
			EventType.SCHEDULE_CHANGED,
			EventType.VOLUME_CHANGED,
			EventType.MUTE_TOGGLED,
		):
			self._unsubs.append(bus.subscribe(et, self._on_bus_event, weak=False))
		# Como el original: al empezar a sonar, el foco va a «Detener».
		self._unsubs.append(bus.subscribe(EventType.PLAYBACK_STARTED, lambda data: wx.CallAfter(self._focus_stop), weak=False))

	def _focus_stop(self) -> None:
		if isAlive(self) and self.IsShown() and self.IsActive() and self.btn_stop.IsEnabled():
			self.btn_stop.SetFocus()

	def _on_bus_event(self, data: Any) -> None:
		wx.CallAfter(self._sync_safe)

	def _sync_safe(self) -> None:
		if isAlive(self):
			self._sync_player_state()

	# ------------------------------------------------------------- estado
	def _sync_player_state(self) -> None:
		p = self._app.player
		active = p.is_active
		self.btn_stop.Enable(active or p.state == PlayerState.ERROR)
		self.btn_reload.Enable(bool(p.current_url))
		self.btn_mute.Enable(True)
		self.btn_pause.Enable(p.state in (PlayerState.PLAYING, PlayerState.PAUSED))
		self.btn_pause.SetLabel("Rean&udar" if p.state == PlayerState.PAUSED else "Pa&usar")
		self.btn_mute.SetLabel("Quitar &silencio" if p.muted else "&Silenciar")
		if self.slider_volume.GetValue() != p.volume:
			self.slider_volume.SetValue(p.volume)
		self._update_status(force=True)

	def _update_status(self, force: bool = False) -> None:
		"""Texto de estado; con el foco en él solo se cambia si se pide (no interrumpe la lectura)."""
		if not force and self.FindFocus() is self.txt_status:
			return
		status = self._app.status_message()
		if self.txt_status.GetValue() != status:
			self.txt_status.SetValue(status)

	def _on_timer(self, event: Any) -> None:
		if self.IsShown():
			self._update_status()

	# ------------------------------------------------------------- reproducción
	def _on_stop(self, event: Any) -> None:
		if self._app.stop():
			speakMessage("Reproducción detenida")
		self._sync_player_state()
		self._focus_current_list()

	def _on_pause(self, event: Any) -> None:
		speakMessage(self._app.toggle_pause())
		self._sync_player_state()

	def _on_reload(self, event: Any) -> None:
		if self._app.reload():
			speakMessage("Recargando emisora...")

	def _on_mute(self, event: Any) -> None:
		muted = self._app.toggle_mute()
		speakMessage("Silenciado" if muted else "Silencio desactivado")
		self._sync_player_state()

	def _on_volume_change(self, event: Any) -> None:
		self._app.set_volume(self.slider_volume.GetValue())

	# ------------------------------------------------------------- herramientas
	def _build_tools_menu(self) -> tuple[wx.Menu, dict[int, Callable[[], None]]]:
		handlers: dict[int, Callable[[], None]] = {}
		p = self._app.player

		def add(menu: wx.Menu, label: str, func: Callable[[], None], enabled: bool = True) -> None:
			item = menu.Append(wx.ID_ANY, label)
			item.Enable(enabled)
			handlers[item.GetId()] = func

		menu = wx.Menu()
		rec = wx.Menu()
		add(rec, "&Grabar emisora actual", self._on_start_recording, p.is_active and not p.is_recording)
		add(rec, "&Detener grabación", self._on_stop_recording, p.is_recording)
		rec.AppendSeparator()
		add(rec, "&Programar grabación...", lambda: schedule_recording_dialog(self, self._app))
		add(rec, "&Ver grabaciones programadas...", self._on_view_scheduled)
		rec.AppendSeparator()
		add(rec, "&Abrir carpeta de grabaciones", self._on_open_recordings_folder)
		menu.AppendSubMenu(rec, "Gra&bación")
		menu.AppendSeparator()
		c = self._config
		add(menu, "Reproducir la ú&ltima emisora", self._on_play_last, bool(c.rememberLastStation and c.last_station_url))
		add(menu, "&Información de lo que suena...", self._on_now_playing_info, p.is_active)
		menu.AppendSeparator()
		add(menu, "&Exportar favoritos...", self._on_export)
		add(menu, "&Importar favoritos...", self._on_import)
		add(menu, "Gestionar &categorías...", self._on_categories)
		menu.AppendSeparator()
		add(menu, "&Limpiar historial...", self._on_clear_history)
		add(menu, "Es&tadísticas del servidor de Radio Browser...", self._on_server_stats)
		menu.AppendSeparator()
		plugins = wx.Menu()
		for item in self._app.plugin_manager.get_menu_items_from_plugins():
			cb = item.get("callback")
			if cb is not None:
				add(plugins, item.get("label", "?"), (lambda c=cb: c(None)))
		if plugins.GetMenuItemCount():
			plugins.AppendSeparator()
		add(plugins, "&Administrar plugins...", self._on_plugins)
		menu.AppendSubMenu(plugins, "&Plugins")
		menu.AppendSeparator()
		add(menu, "C&onfiguración...", self._on_settings)
		return menu, handlers

	def _on_show_tools_menu(self, event: Any) -> None:
		menu, handlers = self._build_tools_menu()
		popup_menu(self.btn_tools, menu, handlers)

	def _on_start_recording(self) -> None:
		ok, msg = self._app.start_recording_current()
		if ok:
			show_info(f"Grabación iniciada.\n\nArchivo: {os.path.basename(msg)}", "Grabación", self)
		else:
			show_error(msg, "Error", self)
		self._sync_player_state()

	def _on_stop_recording(self) -> None:
		p = self._app.player
		if not p.is_recording:
			return
		d = p.recording_duration
		result = self._app.stop_recording_current()
		if result:
			dur = f"\nDuración: {format_duration(d.total_seconds())}" if d else ""
			show_info(f"Grabación guardada.\n\nArchivo: {result}{dur}", "Grabación completada", self)
		else:
			show_info("Grabación detenida.", "Grabación", self)
		self._sync_player_state()

	def _on_view_scheduled(self) -> None:
		dlg = ScheduledRecordingsDialog(self, self._app)
		try:
			dlg.ShowModal()
		finally:
			dlg.Destroy()

	def _on_open_recordings_folder(self) -> None:
		err = self._app.open_recordings_folder()
		if err:
			show_error(err, "Error", self)

	def _on_play_last(self) -> None:
		if not self._app.play_last_station():
			show_info("No hay ninguna emisora recordada.", "Información", self)

	def _on_now_playing_info(self) -> None:
		from .dialogs import StationInfoDialog

		st = self._app.player.current_station
		if st is None:
			return
		dlg = StationInfoDialog(self, station=st, favorite=self._app.db.get_favorite_by_url(st.url), app=self._app)
		try:
			dlg.ShowModal()
		finally:
			dlg.Destroy()

	def _on_export(self) -> None:
		with wx.FileDialog(self, "Exportar favoritos", defaultFile="favoritos zRadio.json", wildcard="Archivos JSON (*.json)|*.json", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			path = dlg.GetPath()
		try:
			with open(path, "w", encoding="utf-8") as f:
				f.write(self._app.db.export_favorites_json())
		except OSError as e:
			show_error(f"Error al exportar: {e}", "Error", self)
			return
		show_info("Favoritos exportados correctamente", "Exportación completada", self)

	def _on_import(self) -> None:
		with wx.FileDialog(self, "Importar favoritos", wildcard="Archivos JSON (*.json)|*.json", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			path = dlg.GetPath()
		try:
			with open(path, encoding="utf-8-sig") as f:
				cats, favs = self._app.db.import_favorites_json(f.read())
		except (OSError, ValueError, KeyError, TypeError) as e:
			show_error(f"Error al importar: {e}", "Error", self)
			return
		self._app.event_bus.emit(EventType.FAVORITE_ADDED, None)
		self._app.event_bus.emit(EventType.CATEGORY_ADDED, None)
		show_info(f"Importados: {cats} categorías, {favs} favoritos", "Importación completada", self)
		self.panel_favorites.refresh()

	def _on_categories(self) -> None:
		from .dialogs import CategoriesDialog

		dlg = CategoriesDialog(self, self._app)
		try:
			dlg.ShowModal()
		finally:
			dlg.Destroy()
		self.panel_favorites.refresh()

	def _on_clear_history(self) -> None:
		clear_history_dialog(self, self._app)
		self.panel_history.refresh()

	def _on_server_stats(self) -> None:
		speakMessage("Consultando el servidor...")
		app = self._app

		def done(result: Any) -> None:
			if isAlive(self):
				stats, server = result if result else ({}, "")
				show_info(server_stats_text(stats, server), "Estadísticas del servidor", self)

		run_in_thread(lambda: (app.api.get_stats(), app.api.base_url), done)

	def _on_plugins(self) -> None:
		dlg = PluginsDialog(self, self._app)
		try:
			dlg.ShowModal()
		finally:
			dlg.Destroy()

	def _on_settings(self) -> None:
		if self._open_settings is not None:
			self._open_settings()

	def _on_help(self, event: Any) -> None:
		menu = wx.Menu()
		handlers: dict[int, Callable[[], None]] = {}
		item = menu.Append(wx.ID_ANY, "&Ayuda rápida...")
		handlers[item.GetId()] = lambda: show_info(HELP_TEXT, "Ayuda", self)
		item = menu.Append(wx.ID_ANY, "Abrir el &manual")
		item.Enable(bool(self._readme and os.path.isfile(self._readme)))
		handlers[item.GetId()] = self._open_manual
		item = menu.Append(wx.ID_ANY, "Acerca de &BASS...")
		handlers[item.GetId()] = self._about_bass
		popup_menu(self.btn_help, menu, handlers)

	def _open_manual(self) -> None:
		try:
			os.startfile(self._readme)  # noqa: S606
		except OSError as e:
			show_error(f"No se pudo abrir el manual: {e}", "Error", self)

	def _about_bass(self) -> None:
		try:
			b = self._app.player.bass
			version = b.versionText
			plugins = ", ".join(n for n, h in b.plugins.items() if h)
			devs = len(b.devices())
		except Exception as e:
			show_error(f"BASS no está disponible: {e}", "Error", self)
			return
		show_info(
			f"Motor de audio: BASS {version} (un4seen.com).\n"
			f"Complementos de formato cargados: {plugins or 'ninguno'}.\n"
			f"Grabación: {'disponible' if b.canRecord else 'no disponible'}. Ecualizador: {'disponible' if b.hasEffects else 'no disponible'}.\n"
			f"Dispositivos de salida: {devs}.\n\n"
			"BASS es gratuita para uso no comercial. Copyright (c) 1999-2024 Un4seen Developments Ltd.",
			"Acerca de BASS",
			self,
		)

	# ------------------------------------------------------------- teclado y pestañas
	def _on_key(self, event: wx.KeyEvent) -> None:
		code = event.GetKeyCode()
		if event.ControlDown() and not event.AltDown() and ord("1") <= code <= ord("4"):
			idx = code - ord("1")
			if idx < self.notebook.GetPageCount():
				self.notebook.SetSelection(idx)
				self._focus_current_list()
			return
		if event.AltDown() and not event.ControlDown() and code == ord("V"):
			self.slider_volume.SetFocus()
			return
		if code == wx.WXK_ESCAPE and not event.HasAnyModifiers():
			self._on_close(None)
			return
		event.Skip()

	def _on_tab_changed(self, event: wx.BookCtrlEvent) -> None:
		self._config.last_tab = event.GetSelection()
		self._config.save()
		self._app.event_bus.emit(EventType.TAB_CHANGED, event.GetSelection())
		event.Skip()

	def _focus_current_list(self) -> None:
		page = self.notebook.GetCurrentPage()
		if hasattr(page, "focus_list"):
			page.focus_list()

	def _on_show(self, event: wx.ShowEvent) -> None:
		if event.IsShown():
			wx.CallAfter(self._sync_safe)
		event.Skip()

	def _on_size(self, event: wx.SizeEvent) -> None:
		if not self.IsMaximized() and not self.IsIconized():
			w, h = self.GetSize()
			self._config.window_width = int(w)
			self._config.window_height = int(h)
		event.Skip()

	def show_and_focus(self) -> None:
		self._sync_player_state()
		bringToFront(self)
		self._focus_current_list()

	def _on_close(self, event: Any) -> None:
		"""Oculta la ventana (no la destruye; la radio sigue sonando)."""
		self._config.save()
		self._app.event_bus.emit(EventType.WINDOW_CLOSED, None)
		self.Hide()

	def destroy(self) -> None:
		try:
			self._timer.Stop()
		except Exception:
			pass
		for u in self._unsubs:
			try:
				u()
			except Exception:
				pass
		self._unsubs.clear()
		for page in (self.panel_general, self.panel_favorites, self.panel_search, self.panel_history):
			try:
				page.dispose()
			except Exception:
				pass
		self.Destroy()

	# ------------------------------------------------------------- compatibilidad
	@property
	def status_text(self) -> str:
		return self.txt_status.GetValue()

	def player_state_name(self) -> str:
		return STATE_NAMES.get(self._app.player.state, "")

	def confirm(self, message: str) -> bool:
		return show_confirm(message, "Confirmar", self)
