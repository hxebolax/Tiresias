# -*- coding: utf-8 -*-
# Copyright (C) 2025-2026 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General GNU.

"""Pestañas de la ventana principal: General, Favoritos, Buscador e Historial."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, Callable

import wx

from tiresias.gui.helpers import isAlive, normalizeForSearch, speakMessage
from tiresias.log import getLogger

from ..zr_core.database import FAVORITE_SORTS
from ..zr_core.events import EventType
from ..zr_core.localization import COMMON_COUNTRIES, TOP_CODE, get_country_code, get_country_name, get_language_api_name, sorted_countries
from ..zr_core.models import ORDER_FIELDS, Favorite, PlaybackHistory, SearchFilters, Station
from ..zr_core.player import format_duration
from .dialogs import (
	CategoriesDialog,
	StationEditDialog,
	StationInfoDialog,
	choose_from_list,
	show_confirm,
	show_error,
	show_info,
)

if TYPE_CHECKING:
	from ..zr_core.app import RadioApp

log = getLogger("zRadioBASS.ui")

PLAY_KEYS = (wx.WXK_SPACE, wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)


def _copy(text: str) -> None:
	from tiresias import api, queue_handler

	queue_handler.queueFunction(api.copyToClip, text, False)


class BasePanel(wx.Panel):
	"""Funciones comunes de las pestañas con lista de emisoras."""

	#: Contexto de los menús contextuales de los plugins.
	plugin_context = "station"

	def __init__(self, parent: wx.Window, app: "RadioApp") -> None:
		super().__init__(parent)
		self._app = app
		self._unsubs: list[Callable[[], None]] = []

	# ------------------------------------------------------------- a implementar
	def focus_list(self) -> None:
		pass

	def refresh(self) -> None:
		pass

	def list_ctrl(self) -> wx.ListBox | None:
		return None

	def selected_station(self) -> Station | None:
		return None

	def selected_favorite(self) -> Favorite | None:
		st = self.selected_station()
		return self._app.db.get_favorite_by_url(st.url) if st is not None else None

	# ------------------------------------------------------------- eventos del bus
	def subscribe(self, event_type: EventType, handler: Callable[[Any], None]) -> None:
		"""Suscripción que llama a ``handler`` en el hilo de la interfaz mientras viva el panel."""

		def cb(data: Any) -> None:
			wx.CallAfter(self._deliver, handler, data)

		self._unsubs.append(self._app.event_bus.subscribe(event_type, cb, weak=False))

	def _deliver(self, handler: Callable[[Any], None], data: Any) -> None:
		if isAlive(self):
			handler(data)

	def dispose(self) -> None:
		for u in self._unsubs:
			try:
				u()
			except Exception:
				pass
		self._unsubs.clear()

	# ------------------------------------------------------------- acciones comunes
	def _play_station(self, station: Station, announce: str | None = None) -> None:
		top = wx.GetTopLevelParent(self)

		def failed(msg: str) -> None:
			wx.CallAfter(lambda: isAlive(top) and show_error(msg, "Error", top))

		self._app.play_station(station, announce=announce, on_fail=failed)

	def _announce_list_position(self, list_ctrl: wx.ListBox, empty: bool = False) -> None:
		idx = list_ctrl.GetSelection()
		total = list_ctrl.GetCount()
		if empty or idx == wx.NOT_FOUND or total == 0:
			speakMessage("Lista vacía")
			return
		speakMessage(f"{idx + 1} de {total}")

	def _add_to_favorites(self, station: Station) -> None:
		if self._app.db.favorite_exists(station.url):
			show_info("Esta emisora ya está en favoritos.", "Información", wx.GetTopLevelParent(self))
			return
		self._app.add_favorite(station)
		speakMessage(f"Se añadió {station.name} a favoritos.")

	def _remove_from_favorites(self, station: Station) -> None:
		fav = self._app.remove_favorite_by_url(station.url)
		if fav is not None:
			speakMessage(f"Se eliminó {station.name} de favoritos.")

	def _show_station_info(self, station: Station, favorite: Favorite | None = None) -> None:
		dlg = StationInfoDialog(wx.GetTopLevelParent(self), station=station, favorite=favorite, app=self._app)
		try:
			dlg.ShowModal()
		finally:
			dlg.Destroy()

	def _copy_url(self, station: Station) -> None:
		_copy(station.url)
		speakMessage(f"URL de {station.name} copiada al portapapeles.")

	def _vote(self, station: Station) -> None:
		app = self._app
		threading.Thread(target=lambda: speakMessage(app.vote(station)), daemon=True, name="zRadioBASS-votar").start()

	def _schedule(self, station: Station) -> None:
		from .dialogs import ScheduleRecordingDialog, show_modal

		dlg = ScheduleRecordingDialog(wx.GetTopLevelParent(self), station_name=station.name, station_url=station.url, config=self._app.config, favorites=self._app.db.get_favorites())
		try:
			if show_modal(dlg) != wx.ID_OK or not dlg.get_result():
				return
			r = dlg.get_result()
		finally:
			dlg.Destroy()
		rec = self._app.schedule_recording(r["station_url"], r["station_name"], r["start_time"], r["end_time"], r["output_path"])
		if rec is None:
			show_error("No se pudo programar la grabación.", "Error", wx.GetTopLevelParent(self))
		else:
			speakMessage("Grabación programada")

	def _station_menu(self, station: Station, extra: list[tuple[str, Callable[[], None]] | None] | None = None, favorite_actions: bool = True) -> None:
		"""Menú contextual común: reproducir, favoritos, información, copiar, votar, programar, plugins."""
		menu = wx.Menu()
		handlers: dict[int, Callable[[], None]] = {}

		def add(label: str, func: Callable[[], None], enabled: bool = True) -> None:
			item = menu.Append(wx.ID_ANY, label)
			item.Enable(enabled)
			handlers[item.GetId()] = func

		add("&Reproducir", lambda: self._play_station(station))
		if favorite_actions:
			if self._app.db.favorite_exists(station.url):
				add("&Quitar de favoritos", lambda: self._remove_from_favorites(station))
			else:
				add("&Agregar a favoritos", lambda: self._add_to_favorites(station))
		for entry in extra or []:
			if entry is None:
				menu.AppendSeparator()
			else:
				add(entry[0], entry[1])
		menu.AppendSeparator()
		add("&Información de la emisora", lambda: self._show_station_info(station, self._app.db.get_favorite_by_url(station.url)))
		add("&Copiar URL", lambda: self._copy_url(station))
		add("&Votar por la emisora", lambda: self._vote(station), enabled=bool(station.stationuuid))
		add("&Programar grabación de esta emisora...", lambda: self._schedule(station))
		plugin_items = self._app.plugin_manager.get_context_menu_items_from_plugins(self.plugin_context)
		if plugin_items:
			menu.AppendSeparator()
			for it in plugin_items:
				cb = it.get("callback")
				if cb is not None:
					add(it.get("label", "?"), (lambda c=cb: c(station)))
		popup_menu(self, menu, handlers)


def popup_menu(window: wx.Window, menu: wx.Menu, handlers: dict[int, Callable[[], None]]) -> None:
	"""Muestra ``menu`` y ejecuta (después de cerrarse) la acción elegida."""
	try:
		chosen = window.GetPopupMenuSelectionFromUser(menu)
	finally:
		menu.Destroy()
	func = handlers.get(chosen)
	if func is not None:
		wx.CallAfter(func)


# ===================================================================== General
class GeneralPanel(BasePanel):
	"""Emisoras del país elegido (o las más populares del mundo), con filtro."""

	def __init__(self, parent: wx.Window, app: "RadioApp") -> None:
		super().__init__(parent, app)
		self._stations: list[Station] = []
		self._filtered: list[Station] = []
		self._codes: list[str] = []
		self._loading = False
		self._req = 0
		sizer = wx.BoxSizer(wx.VERTICAL)
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(self, label="&País:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
		self.cmb_country = wx.Choice(self)
		row.Add(self.cmb_country, 1, wx.EXPAND | wx.ALL, 5)
		self.btn_load = wx.Button(self, label="Car&gar emisoras")
		row.Add(self.btn_load, 0, wx.ALL, 5)
		sizer.Add(row, 0, wx.EXPAND)
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(self, label="&Filtrar:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
		self.txt_search = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
		row.Add(self.txt_search, 1, wx.EXPAND | wx.ALL, 5)
		self.btn_search = wx.Button(self, label="&Buscar")
		row.Add(self.btn_search, 0, wx.ALL, 5)
		sizer.Add(row, 0, wx.EXPAND)
		sizer.Add(wx.StaticText(self, label="Listado de emisoras:"), 0, wx.ALL, 5)
		self.lst_stations = wx.ListBox(self, style=wx.LB_SINGLE)
		sizer.Add(self.lst_stations, 1, wx.EXPAND | wx.ALL, 5)
		self.SetSizer(sizer)
		self._fill_countries()
		self.btn_load.Bind(wx.EVT_BUTTON, lambda e: self._load_data())
		self.txt_search.Bind(wx.EVT_TEXT_ENTER, self._on_search)
		self.btn_search.Bind(wx.EVT_BUTTON, self._on_search)
		self.lst_stations.Bind(wx.EVT_KEY_UP, self._on_list_key)
		self.lst_stations.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
		self.lst_stations.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._play_selected())
		self._load_data()

	def _fill_countries(self) -> None:
		entries = [(TOP_CODE, "Todas las populares")]
		entries += [(c, get_country_name(c)) for c in COMMON_COUNTRIES]
		entries += [(c, n) for c, n in sorted_countries() if c not in COMMON_COUNTRIES]
		self._codes = [c for c, _n in entries]
		self.cmb_country.Set([n for _c, n in entries])
		default = self._app.config.defaultCountry or "ES"
		self.cmb_country.SetSelection(self._codes.index(default) if default in self._codes else 1)

	def selected_code(self) -> str:
		i = self.cmb_country.GetSelection()
		return self._codes[i] if 0 <= i < len(self._codes) else "ES"

	def _load_data(self) -> None:
		code = self.selected_code()
		self._app.config.defaultCountry = code
		self._req += 1
		req = self._req
		self._loading = True
		self._stations = self._filtered = []
		self.lst_stations.Set(["Cargando emisoras..."])
		self.lst_stations.SetSelection(0)
		self.btn_search.SetLabel("&Buscar")

		def fetch() -> None:
			try:
				stations = self._app.general_stations(code)
				err = None
			except Exception as e:
				log.error("Error cargando emisoras: %s", e)
				stations, err = [], str(e)
			wx.CallAfter(self._loaded, req, stations, err)

		threading.Thread(target=fetch, daemon=True, name="zRadioBASS-general").start()

	def _loaded(self, req: int, stations: list[Station], err: str | None) -> None:
		if not isAlive(self) or req != self._req:
			return
		self._loading = False
		if err:
			self._show_message("Error al cargar emisoras.")
			return
		if not stations:
			self._show_message("Sin emisoras para este país.")
			return
		self._stations = self._filtered = stations
		self._fill(stations)

	def _fill(self, stations: list[Station]) -> None:
		self.lst_stations.Set([s.name for s in stations])
		if stations:
			self.lst_stations.SetSelection(0)

	def _show_message(self, message: str) -> None:
		self._filtered = []
		self.lst_stations.Set([message])
		self.lst_stations.SetSelection(0)

	def _on_search(self, event: Any) -> None:
		query = self.txt_search.GetValue().strip()
		if self.btn_search.GetLabel() == "&Buscar":
			if not query:
				show_error("Escriba algo para buscar.", "Error", wx.GetTopLevelParent(self))
				self.txt_search.SetFocus()
				return
			q = normalizeForSearch(query)
			found = [s for s in self._stations if q in normalizeForSearch(s.name)]
			if not found:
				show_error("No se encontraron resultados.", "Búsqueda", wx.GetTopLevelParent(self))
				return
			self._filtered = found
			self._fill(found)
			self.lst_stations.SetFocus()
			self.btn_search.SetLabel("&Limpiar")
		else:
			self.txt_search.Clear()
			self._filtered = self._stations
			self._fill(self._stations)
			self.txt_search.SetFocus()
			self.btn_search.SetLabel("&Buscar")

	def _on_list_key(self, event: wx.KeyEvent) -> None:
		code = event.GetKeyCode()
		if code in PLAY_KEYS and not event.HasAnyModifiers():
			self._play_selected()
			return
		if code == wx.WXK_F1:
			self._announce_list_position(self.lst_stations, empty=not self._filtered)
			return
		event.Skip()

	def selected_station(self) -> Station | None:
		i = self.lst_stations.GetSelection()
		if i == wx.NOT_FOUND or not (0 <= i < len(self._filtered)):
			return None
		return self._filtered[i]

	def _play_selected(self) -> None:
		st = self.selected_station()
		if st is not None:
			self._play_station(st)

	def _on_context_menu(self, event: Any) -> None:
		st = self.selected_station()
		if st is not None:
			self._station_menu(st)

	def list_ctrl(self) -> wx.ListBox:
		return self.lst_stations

	def focus_list(self) -> None:
		self.lst_stations.SetFocus()

	def refresh(self) -> None:
		self._load_data()


# ===================================================================== Favoritos
class FavoritesPanel(BasePanel):
	"""Emisoras favoritas: categorías, orden, búsqueda, notas y gestión."""

	plugin_context = "favorite"

	def __init__(self, parent: wx.Window, app: "RadioApp") -> None:
		super().__init__(parent, app)
		self._favorites: list[Favorite] = []
		self._filtered: list[Favorite] = []
		self._category_ids: list[int | None] = []
		sizer = wx.BoxSizer(wx.VERTICAL)
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(self, label="Buscar &favorito:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
		self.txt_search = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
		row.Add(self.txt_search, 1, wx.EXPAND | wx.ALL, 5)
		self.btn_search = wx.Button(self, label="&Buscar")
		row.Add(self.btn_search, 0, wx.ALL, 5)
		sizer.Add(row, 0, wx.EXPAND)
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(self, label="Ca&tegoría:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
		self.choice_category = wx.Choice(self)
		row.Add(self.choice_category, 1, wx.EXPAND | wx.ALL, 5)
		row.Add(wx.StaticText(self, label="&Ordenar por:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
		self.choice_sort = wx.Choice(self, choices=[t for t, _o in FAVORITE_SORTS])
		row.Add(self.choice_sort, 1, wx.EXPAND | wx.ALL, 5)
		sizer.Add(row, 0, wx.EXPAND)
		sizer.Add(wx.StaticText(self, label="Emisoras favoritas:"), 0, wx.ALL, 5)
		self.lst_favorites = wx.ListBox(self, style=wx.LB_SINGLE)
		sizer.Add(self.lst_favorites, 1, wx.EXPAND | wx.ALL, 5)
		row = wx.BoxSizer(wx.HORIZONTAL)
		self.btn_new = wx.Button(self, label="&Nueva")
		self.btn_edit = wx.Button(self, label="&Editar")
		self.btn_delete = wx.Button(self, label="E&liminar")
		self.btn_categories = wx.Button(self, label="Cate&gorías...")
		for b in (self.btn_new, self.btn_edit, self.btn_delete, self.btn_categories):
			row.Add(b, 1, wx.ALL, 5)
		sizer.Add(row, 0, wx.EXPAND)
		self.SetSizer(sizer)
		self.choice_sort.SetSelection(max(0, min(len(FAVORITE_SORTS) - 1, int(app.config.favorites_sort))))
		self._fill_categories(int(app.config.favorites_category))
		self.txt_search.Bind(wx.EVT_TEXT_ENTER, self._on_search)
		self.btn_search.Bind(wx.EVT_BUTTON, self._on_search)
		self.choice_category.Bind(wx.EVT_CHOICE, lambda e: self._on_filter_change())
		self.choice_sort.Bind(wx.EVT_CHOICE, lambda e: self._on_filter_change())
		self.lst_favorites.Bind(wx.EVT_KEY_UP, self._on_list_key)
		self.lst_favorites.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
		self.lst_favorites.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._play_selected())
		self.btn_new.Bind(wx.EVT_BUTTON, self._on_new)
		self.btn_edit.Bind(wx.EVT_BUTTON, self._on_edit)
		self.btn_delete.Bind(wx.EVT_BUTTON, self._on_delete)
		self.btn_categories.Bind(wx.EVT_BUTTON, self._on_categories)
		for et in (EventType.FAVORITE_ADDED, EventType.FAVORITE_REMOVED, EventType.FAVORITE_UPDATED, EventType.FAVORITES_REORDERED):
			self.subscribe(et, lambda data: self._on_favorites_changed())
		for et in (EventType.CATEGORY_ADDED, EventType.CATEGORY_REMOVED, EventType.CATEGORY_UPDATED):
			self.subscribe(et, lambda data: self._on_categories_changed())
		self._load_data()

	# ------------------------------------------------------------- datos
	def _fill_categories(self, select: int | None = -1) -> None:
		cats = self._app.db.get_categories()
		self._category_ids = [-1, 0] + [c.id for c in cats]
		self.choice_category.Set(["Todas las categorías", "(sin categoría)"] + [c.name for c in cats])
		self.choice_category.SetSelection(self._category_ids.index(select) if select in self._category_ids else 0)

	def _current_category(self) -> int:
		i = self.choice_category.GetSelection()
		return self._category_ids[i] if 0 <= i < len(self._category_ids) else -1

	def _load_data(self, keep_id: int | None = None) -> None:
		cat = self._current_category()
		sort = self.choice_sort.GetSelection()
		favs = self._app.db.get_favorites(sort=max(0, sort))
		if cat == 0:
			favs = [f for f in favs if f.category_id is None]
		elif cat > 0:
			favs = [f for f in favs if f.category_id == cat]
		self._favorites = favs
		query = self.txt_search.GetValue().strip() if self.btn_search.GetLabel() == "&Limpiar" else ""
		if query:
			q = normalizeForSearch(query)
			favs = [f for f in favs if q in normalizeForSearch(f.name) or q in normalizeForSearch(f.notes or "")]
		self._filtered = favs
		self._update_list(keep_id)

	def _update_list(self, keep_id: int | None = None) -> None:
		if not self._filtered:
			self.lst_favorites.Set(["No hay favoritos."])
			self.lst_favorites.SetSelection(0)
			return
		self.lst_favorites.Set([f.name for f in self._filtered])
		idx = 0
		if keep_id is not None:
			idx = next((i for i, f in enumerate(self._filtered) if f.id == keep_id), 0)
		self.lst_favorites.SetSelection(idx)

	def _on_filter_change(self) -> None:
		self._app.config.favorites_sort = self.choice_sort.GetSelection()
		self._app.config.favorites_category = self._current_category()
		self._app.config.save()
		self._load_data()

	def _on_favorites_changed(self) -> None:
		cur = self.selected_favorite()
		self._load_data(cur.id if cur else None)

	def _on_categories_changed(self) -> None:
		self._fill_categories(self._current_category())
		self._load_data()

	# ------------------------------------------------------------- búsqueda
	def _on_search(self, event: Any) -> None:
		query = self.txt_search.GetValue().strip()
		if self.btn_search.GetLabel() == "&Buscar":
			if not query:
				show_error("Escriba algo para buscar.", "Error", wx.GetTopLevelParent(self))
				return
			q = normalizeForSearch(query)
			found = [f for f in self._favorites if q in normalizeForSearch(f.name) or q in normalizeForSearch(f.notes or "")]
			if not found:
				show_error("No se encontraron resultados.", "Búsqueda", wx.GetTopLevelParent(self))
				return
			self._filtered = found
			self._update_list()
			self.lst_favorites.SetFocus()
			self.btn_search.SetLabel("&Limpiar")
		else:
			self.txt_search.Clear()
			self.btn_search.SetLabel("&Buscar")
			self._load_data()
			self.txt_search.SetFocus()

	# ------------------------------------------------------------- lista
	def selected_favorite(self) -> Favorite | None:
		i = self.lst_favorites.GetSelection()
		if i == wx.NOT_FOUND or not (0 <= i < len(self._filtered)):
			return None
		return self._filtered[i]

	def selected_station(self) -> Station | None:
		f = self.selected_favorite()
		return f.to_station() if f else None

	def _on_list_key(self, event: wx.KeyEvent) -> None:
		code = event.GetKeyCode()
		if code in PLAY_KEYS and not event.HasAnyModifiers():
			self._play_selected()
			return
		if code == wx.WXK_F1:
			self._announce_list_position(self.lst_favorites, empty=not self._filtered)
			return
		if event.AltDown() and code == wx.WXK_UP:
			self._move_favorite(-1)
			return
		if event.AltDown() and code == wx.WXK_DOWN:
			self._move_favorite(1)
			return
		if code == wx.WXK_DELETE and not event.HasAnyModifiers():
			self._on_delete(None)
			return
		event.Skip()

	def _play_selected(self) -> None:
		f = self.selected_favorite()
		if f is not None:
			self._play_station(f.to_station())

	def _on_context_menu(self, event: Any) -> None:
		f = self.selected_favorite()
		if f is None:
			return
		extra = [
			None,
			("&Editar", lambda: self._on_edit(None)),
			("E&liminar", lambda: self._on_delete(None)),
			("&Mover a otra categoría...", self._move_to_category),
		]
		self._station_menu(f.to_station(), extra=extra, favorite_actions=False)

	def _show_station_info(self, station: Station, favorite: Favorite | None = None) -> None:
		super()._show_station_info(station, favorite or self.selected_favorite())

	# ------------------------------------------------------------- gestión
	def _on_new(self, event: Any) -> None:
		dlg = StationEditDialog(wx.GetTopLevelParent(self), categories=self._app.db.get_categories())
		try:
			if dlg.ShowModal() != wx.ID_OK or not dlg.get_result():
				return
			r = dlg.get_result()
		finally:
			dlg.Destroy()
		if self._app.db.favorite_exists(r["url"]):
			show_info("Esta emisora ya está en favoritos.", "Información", wx.GetTopLevelParent(self))
			return
		fav = Favorite(name=r["name"], url=r["url"], notes=r["notes"], category_id=r["category_id"])
		self._app.db.add_favorite(fav)
		self._app.event_bus.emit(EventType.FAVORITE_ADDED, fav)
		self._load_data(fav.id)
		self.lst_favorites.SetFocus()

	def _on_edit(self, event: Any) -> None:
		fav = self.selected_favorite()
		if fav is None:
			return
		dlg = StationEditDialog(wx.GetTopLevelParent(self), fav, categories=self._app.db.get_categories())
		try:
			if dlg.ShowModal() != wx.ID_OK or not dlg.get_result():
				return
			r = dlg.get_result()
		finally:
			dlg.Destroy()
		fav.name, fav.url, fav.notes, fav.category_id = r["name"], r["url"], r["notes"], r["category_id"]
		self._app.db.update_favorite(fav)
		self._app.event_bus.emit(EventType.FAVORITE_UPDATED, fav)
		self._load_data(fav.id)
		self.lst_favorites.SetFocus()

	def _on_delete(self, event: Any) -> None:
		fav = self.selected_favorite()
		if fav is None:
			return
		if show_confirm(f"¿Eliminar '{fav.name}' de favoritos?", "Confirmar", wx.GetTopLevelParent(self)):
			idx = self.lst_favorites.GetSelection()
			self._app.db.delete_favorite(fav.id)
			self._app.event_bus.emit(EventType.FAVORITE_REMOVED, fav)
			self._load_data()
			if self._filtered:
				self.lst_favorites.SetSelection(min(idx, len(self._filtered) - 1))
		self.lst_favorites.SetFocus()

	def _move_favorite(self, direction: int) -> None:
		fav = self.selected_favorite()
		if fav is None:
			return
		if self.choice_sort.GetSelection() != 0 or self._current_category() != -1 or self.btn_search.GetLabel() == "&Limpiar":
			speakMessage("Para mover favoritos, elija el orden personal, todas las categorías y sin búsqueda")
			return
		if self._app.db.move_favorite(fav.id, direction):
			self._app.event_bus.emit(EventType.FAVORITES_REORDERED, fav)
			self._load_data(fav.id)
			speakMessage(f"{self.lst_favorites.GetSelection() + 1} de {len(self._filtered)}")
		else:
			wx.Bell()

	def _move_to_category(self) -> None:
		fav = self.selected_favorite()
		if fav is None:
			return
		cats = self._app.db.get_categories()
		items: list[tuple[Any, str]] = [(0, "(sin categoría)")] + [(c.id, c.name) for c in cats]
		value = choose_from_list(wx.GetTopLevelParent(self), "Mover a otra categoría", "&Categoría:", items)
		if value is None:
			return
		fav.category_id = value or None
		self._app.db.update_favorite(fav)
		self._app.event_bus.emit(EventType.FAVORITE_UPDATED, fav)
		self._load_data(fav.id)

	def _on_categories(self, event: Any) -> None:
		dlg = CategoriesDialog(wx.GetTopLevelParent(self), self._app)
		try:
			dlg.ShowModal()
		finally:
			dlg.Destroy()
		self._on_categories_changed()

	def list_ctrl(self) -> wx.ListBox:
		return self.lst_favorites

	def focus_list(self) -> None:
		self.lst_favorites.SetFocus()

	def refresh(self) -> None:
		self._fill_categories(self._current_category())
		self._load_data()


# ===================================================================== Buscador
SEARCH_KINDS = ["Búsqueda general", "Por país", "Por idioma", "Por etiqueta"]
SEARCH_LABELS = ["Buscar &nombre:", "Buscar &país:", "Buscar &idioma:", "Buscar &etiqueta:"]
CODECS = [("", "Cualquiera"), ("MP3", "MP3"), ("AAC", "AAC"), ("AAC+", "AAC+"), ("OGG", "OGG Vorbis"), ("OPUS", "Opus"), ("FLAC", "FLAC"), ("WMA", "WMA")]


class SearchPanel(BasePanel):
	"""Búsqueda por nombre, país, idioma o etiqueta, con filtros avanzados."""

	def __init__(self, parent: wx.Window, app: "RadioApp") -> None:
		super().__init__(parent, app)
		self._results: list[Station] = []
		self._req = 0
		cfg = app.config
		sizer = wx.BoxSizer(wx.VERTICAL)
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(self, label="Ca&tegoría:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
		self.choice_category = wx.Choice(self, choices=SEARCH_KINDS)
		row.Add(self.choice_category, 1, wx.EXPAND | wx.ALL, 5)
		sizer.Add(row, 0, wx.EXPAND)
		row = wx.BoxSizer(wx.HORIZONTAL)
		self.lbl_search = wx.StaticText(self, label=SEARCH_LABELS[0])
		row.Add(self.lbl_search, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
		self.txt_search = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
		row.Add(self.txt_search, 1, wx.EXPAND | wx.ALL, 5)
		self.btn_choose = wx.Button(self, label="Elegir de la &lista...")
		row.Add(self.btn_choose, 0, wx.ALL, 5)
		self.btn_search = wx.Button(self, label="&Buscar")
		row.Add(self.btn_search, 0, wx.ALL, 5)
		sizer.Add(row, 0, wx.EXPAND)
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(self, label="&Ordenar por:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
		self.choice_order = wx.Choice(self, choices=[lbl for _k, lbl in ORDER_FIELDS])
		row.Add(self.choice_order, 0, wx.ALL, 5)
		self.chk_reverse = wx.CheckBox(self, label="De m&ayor a menor")
		row.Add(self.chk_reverse, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
		row.Add(wx.StaticText(self, label="&Formato:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
		self.choice_codec = wx.Choice(self, choices=[lbl for _k, lbl in CODECS])
		row.Add(self.choice_codec, 0, wx.ALL, 5)
		row.Add(wx.StaticText(self, label="Calidad &mínima (kbps):"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
		self.spin_bitrate = wx.SpinCtrl(self, min=0, max=1000, initial=0, size=(80, -1))
		row.Add(self.spin_bitrate, 0, wx.ALL, 5)
		sizer.Add(row, 0, wx.EXPAND)
		sizer.Add(wx.StaticText(self, label="Resultados:"), 0, wx.ALL, 5)
		self.lst_results = wx.ListBox(self, style=wx.LB_SINGLE)
		self.lst_results.Set(["Esperando una búsqueda."])
		self.lst_results.SetSelection(0)
		sizer.Add(self.lst_results, 1, wx.EXPAND | wx.ALL, 5)
		self.SetSizer(sizer)
		# Valores recordados
		kind = int(cfg.search_category)
		self.choice_category.SetSelection(kind if 0 <= kind < len(SEARCH_KINDS) else 0)
		self.lbl_search.SetLabel(SEARCH_LABELS[self.choice_category.GetSelection()])
		keys = [k for k, _l in ORDER_FIELDS]
		self.choice_order.SetSelection(keys.index(cfg.search_order) if cfg.search_order in keys else 0)
		self.chk_reverse.SetValue(bool(cfg.search_reverse))
		codecs = [k for k, _l in CODECS]
		self.choice_codec.SetSelection(codecs.index(cfg.search_codec) if cfg.search_codec in codecs else 0)
		self.spin_bitrate.SetValue(int(cfg.search_min_bitrate))
		self._update_choose_button()
		self.choice_category.Bind(wx.EVT_CHOICE, self._on_category_change)
		self.txt_search.Bind(wx.EVT_TEXT_ENTER, self._on_search)
		self.btn_search.Bind(wx.EVT_BUTTON, self._on_search)
		self.btn_choose.Bind(wx.EVT_BUTTON, self._on_choose)
		self.lst_results.Bind(wx.EVT_KEY_UP, self._on_list_key)
		self.lst_results.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
		self.lst_results.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._play_selected())

	def _update_choose_button(self) -> None:
		self.btn_choose.Enable(self.choice_category.GetSelection() > 0)

	def _on_category_change(self, event: Any) -> None:
		idx = self.choice_category.GetSelection()
		self.lbl_search.SetLabel(SEARCH_LABELS[idx])
		self.txt_search.Clear()
		self.lst_results.Set(["Esperando una búsqueda."])
		self.lst_results.SetSelection(0)
		self._results = []
		self.btn_search.SetLabel("&Buscar")
		self._update_choose_button()
		self._app.config.search_category = idx
		self.Layout()

	def _on_choose(self, event: Any) -> None:
		kind = self.choice_category.GetSelection()
		if kind <= 0:
			return
		self.btn_choose.Disable()
		speakMessage("Cargando la lista...")

		def fetch() -> list[tuple[Any, str]]:
			if kind == 1:
				items = sorted(self._app.list_countries(), key=lambda c: normalizeForSearch(c.name_localized or c.name))
				return [(c.code, f"{c.name_localized or c.name} ({c.station_count} emisoras)") for c in items if c.code]
			if kind == 2:
				return [(lang.name, f"{lang.name_localized or lang.name} ({lang.station_count} emisoras)") for lang in self._app.list_languages()]
			return [(t.name, f"{t.name} ({t.station_count} emisoras)") for t in self._app.list_tags()]

		def done(items: list | None) -> None:
			if not isAlive(self):
				return
			self.btn_choose.Enable()
			if not items:
				show_error("No se pudo obtener la lista. Verifique su conexión.", "Error", wx.GetTopLevelParent(self))
				return
			title = SEARCH_KINDS[kind]
			value = choose_from_list(wx.GetTopLevelParent(self), f"Elegir: {title.lower()}", "&Elementos:", items)
			if value is None:
				return
			if kind == 1:
				self.txt_search.SetValue(get_country_name(value))
			else:
				self.txt_search.SetValue(value)
			self.btn_search.SetLabel("&Buscar")
			self._on_search(None)

		from .dialogs import run_in_thread

		run_in_thread(fetch, done)

	def _filters(self, kind: int, query: str) -> SearchFilters | str:
		cfg = self._app.config
		order = ORDER_FIELDS[max(0, self.choice_order.GetSelection())][0]
		codec = CODECS[max(0, self.choice_codec.GetSelection())][0]
		f = SearchFilters(
			order=order,
			reverse=self.chk_reverse.GetValue(),
			codec=codec,
			min_bitrate=self.spin_bitrate.GetValue(),
			limit=max(10, int(cfg.searchLimit)),
			hide_broken=bool(cfg.hideBroken),
		)
		cfg.search_order = order
		cfg.search_reverse = f.reverse
		cfg.search_codec = codec
		cfg.search_min_bitrate = f.min_bitrate
		cfg.save()
		if kind == 0:
			f.name = query
		elif kind == 1:
			code = get_country_code(query)
			if not code:
				return f"No se reconoce el país «{query}». Escriba su nombre en español o su código de dos letras, o use «Elegir de la lista»."
			f.country = code
		elif kind == 2:
			f.language = get_language_api_name(query)
		else:
			f.tag = query.lower()
		return f

	def _on_search(self, event: Any) -> None:
		if self.btn_search.GetLabel() == "&Limpiar":
			self._on_category_change(None)
			self.txt_search.SetFocus()
			return
		query = self.txt_search.GetValue().strip()
		if not query:
			show_error("Escriba algo para buscar.", "Error", wx.GetTopLevelParent(self))
			return
		kind = self.choice_category.GetSelection()
		filters = self._filters(kind, query)
		if isinstance(filters, str):
			show_error(filters, "Error", wx.GetTopLevelParent(self))
			self.txt_search.SetFocus()
			return
		self._req += 1
		req = self._req
		self.lst_results.Set(["Buscando..."])
		self.lst_results.SetSelection(0)
		self._results = []
		self._app.event_bus.emit(EventType.SEARCH_STARTED, {"kind": kind, "query": query})
		speakMessage("Buscando...")

		def run() -> None:
			try:
				results = self._app.api.search_stations(filters, raise_errors=True)
				err = None
			except Exception as e:
				log.error("Error en la búsqueda: %s", e)
				results, err = [], str(e)
			wx.CallAfter(self._show_results, req, results, err)

		threading.Thread(target=run, daemon=True, name="zRadioBASS-buscar").start()

	def _show_results(self, req: int, results: list[Station], err: str | None) -> None:
		if not isAlive(self) or req != self._req:
			return
		if err:
			self._results = []
			self.lst_results.Set(["Error al buscar."])
			self.lst_results.SetSelection(0)
			self._app.event_bus.emit(EventType.SEARCH_ERROR, err)
			speakMessage("Error al buscar")
			return
		self._results = results
		self._app.event_bus.emit(EventType.SEARCH_COMPLETED, results)
		if not results:
			self.lst_results.Set(["No se encontraron resultados."])
		else:
			self.lst_results.Set([s.name for s in results])
		self.lst_results.SetSelection(0)
		self.lst_results.SetFocus()
		self.btn_search.SetLabel("&Limpiar")
		speakMessage(f"{len(results)} resultados")

	def _on_list_key(self, event: wx.KeyEvent) -> None:
		code = event.GetKeyCode()
		if code in PLAY_KEYS and not event.HasAnyModifiers():
			self._play_selected()
			return
		if code == wx.WXK_F1:
			self._announce_list_position(self.lst_results, empty=not self._results)
			return
		event.Skip()

	def selected_station(self) -> Station | None:
		i = self.lst_results.GetSelection()
		if i == wx.NOT_FOUND or not (0 <= i < len(self._results)):
			return None
		return self._results[i]

	def _play_selected(self) -> None:
		st = self.selected_station()
		if st is not None:
			self._play_station(st)

	def _on_context_menu(self, event: Any) -> None:
		st = self.selected_station()
		if st is not None:
			self._station_menu(st)

	def list_ctrl(self) -> wx.ListBox:
		return self.lst_results

	def focus_list(self) -> None:
		self.lst_results.SetFocus()


# ===================================================================== Historial
class HistoryPanel(BasePanel):
	"""Historial de reproducción (las 100 últimas, como el original, ampliable)."""

	LIMIT = 100

	def __init__(self, parent: wx.Window, app: "RadioApp") -> None:
		super().__init__(parent, app)
		self._history: list[PlaybackHistory] = []
		self._limit = self.LIMIT
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(wx.StaticText(self, label="Historial de reproducción:"), 0, wx.ALL, 5)
		self.lst_history = wx.ListBox(self, style=wx.LB_SINGLE)
		sizer.Add(self.lst_history, 1, wx.EXPAND | wx.ALL, 5)
		row = wx.BoxSizer(wx.HORIZONTAL)
		self.btn_more = wx.Button(self, label="Mostrar &más")
		self.btn_delete = wx.Button(self, label="&Quitar del historial")
		self.btn_clear = wx.Button(self, label="&Limpiar historial...")
		for b in (self.btn_more, self.btn_delete, self.btn_clear):
			row.Add(b, 1, wx.ALL, 5)
		sizer.Add(row, 0, wx.EXPAND)
		self.SetSizer(sizer)
		self.lst_history.Bind(wx.EVT_KEY_UP, self._on_list_key)
		self.lst_history.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._play_selected())
		self.lst_history.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
		self.btn_more.Bind(wx.EVT_BUTTON, self._on_more)
		self.btn_delete.Bind(wx.EVT_BUTTON, lambda e: self._delete_selected())
		self.btn_clear.Bind(wx.EVT_BUTTON, self._on_clear)
		self.subscribe(EventType.HISTORY_CHANGED, lambda data: self._load_data())
		self._load_data()

	def _load_data(self) -> None:
		self._history = self._app.db.get_history(limit=self._limit)
		self._update_list()

	def _update_list(self) -> None:
		current = self.lst_history.GetSelection()
		if not self._history:
			self.lst_history.Set(["Sin historial."])
			self.lst_history.SetSelection(0)
			return
		items = []
		for h in self._history:
			date = h.played_at.strftime("%d/%m/%Y %H:%M") if h.played_at else ""
			txt = f"{h.station_name} - {date}"
			if h.duration_seconds:
				txt += f" ({format_duration(h.duration_seconds)})"
			items.append(txt)
		self.lst_history.Set(items)
		self.lst_history.SetSelection(current if current != wx.NOT_FOUND and current < len(items) else 0)

	def _selected_entry(self) -> PlaybackHistory | None:
		i = self.lst_history.GetSelection()
		if i == wx.NOT_FOUND or not (0 <= i < len(self._history)):
			return None
		return self._history[i]

	def selected_station(self) -> Station | None:
		h = self._selected_entry()
		return h.to_station() if h else None

	def _on_list_key(self, event: wx.KeyEvent) -> None:
		code = event.GetKeyCode()
		if code in PLAY_KEYS and not event.HasAnyModifiers():
			self._play_selected()
			return
		if code == wx.WXK_F1:
			self._announce_list_position(self.lst_history, empty=not self._history)
			return
		if code == wx.WXK_DELETE and not event.HasAnyModifiers():
			self._delete_selected()
			return
		event.Skip()

	def _play_selected(self) -> None:
		st = self.selected_station()
		if st is not None:
			self._play_station(st)

	def _on_context_menu(self, event: Any) -> None:
		st = self.selected_station()
		if st is not None:
			self._station_menu(st, extra=[None, ("Quitar del &historial", self._delete_selected)])

	def _delete_selected(self) -> None:
		h = self._selected_entry()
		if h is None:
			return
		self._app.db.delete_history_entry(h.id)
		self._load_data()
		speakMessage("Quitado del historial")
		self.lst_history.SetFocus()

	def _on_more(self, event: Any) -> None:
		self._limit += self.LIMIT
		self._load_data()
		speakMessage(f"{len(self._history)} entradas")

	def _on_clear(self, event: Any) -> None:
		from .dialogs import clear_history_dialog

		clear_history_dialog(wx.GetTopLevelParent(self), self._app)
		self._load_data()
		self.lst_history.SetFocus()

	def list_ctrl(self) -> wx.ListBox:
		return self.lst_history

	def focus_list(self) -> None:
		self.lst_history.SetFocus()

	def refresh(self) -> None:
		self._load_data()
