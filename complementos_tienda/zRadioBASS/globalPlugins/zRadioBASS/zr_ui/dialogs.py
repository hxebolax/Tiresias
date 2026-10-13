# -*- coding: utf-8 -*-
# Copyright (C) 2025-2026 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General GNU.

"""Diálogos de zRadio BASS.

Todos se crean en el hilo de la interfaz. Los cuadros de mensaje son los de
Tiresias (texto recorrible y copiable).
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable

import wx

from tiresias.gui import message_dialog
from tiresias.gui.helpers import addLabel, isAlive, normalizeForSearch, speakMessage
from tiresias.log import getLogger

from ..zr_core.models import Category, Favorite, Station
from ..zr_core.recording import STATUS_NAMES, recording_filename, safe_filename

if TYPE_CHECKING:
	from ..zr_core.app import RadioApp

log = getLogger("zRadioBASS.ui")

DATE_FORMAT = "%d/%m/%Y %H:%M"


# ===================================================================== mensajes
def _owner(parent: wx.Window | None) -> tuple[wx.Window | None, bool]:
	"""Ventana dueña de un cuadro y si hay que usar la ventana oculta de Tiresias."""
	if parent is not None and isAlive(parent):
		return parent, False
	from tiresias import gui

	if isAlive(gui.mainFrame):
		return gui.mainFrame, True
	return None, False


def _box(message: str, title: str, style: int, parent: wx.Window | None) -> int:
	owner, useFrame = _owner(parent)
	if useFrame:
		owner.prePopup()
	try:
		return message_dialog.messageBox(message, title, style, owner)
	finally:
		if useFrame:
			owner.postPopup()


def show_error(message: str, title: str | None = None, parent: wx.Window | None = None) -> None:
	_box(message, title or "Error", wx.OK | wx.ICON_ERROR, parent)


def show_info(message: str, title: str | None = None, parent: wx.Window | None = None) -> None:
	_box(message, title or "Información", wx.OK | wx.ICON_INFORMATION, parent)


def show_confirm(message: str, title: str | None = None, parent: wx.Window | None = None) -> bool:
	return _box(message, title or "Confirmar", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, parent) == wx.YES


def show_modal(dlg: wx.Dialog) -> int:
	"""Muestra un diálogo modal; si no tiene padre visible, lo trae al primer plano."""
	from tiresias import gui

	useFrame = (dlg.GetParent() is None or dlg.GetParent() is gui.mainFrame) and isAlive(gui.mainFrame)
	if useFrame:
		gui.mainFrame.prePopup()
	try:
		dlg.CentreOnScreen()
		dlg.Raise()
		return dlg.ShowModal()
	finally:
		if useFrame:
			gui.mainFrame.postPopup()


def default_parent(parent: wx.Window | None) -> wx.Window | None:
	if parent is not None and isAlive(parent):
		return parent
	from tiresias import gui

	return gui.mainFrame if isAlive(gui.mainFrame) else None


def _buttons(dlg: wx.Dialog, sizer: wx.Sizer, okLabel: str = "&Aceptar", cancelLabel: str = "&Cancelar") -> tuple[wx.Button, wx.Button]:
	row = wx.BoxSizer(wx.HORIZONTAL)
	ok = wx.Button(dlg, wx.ID_OK, okLabel)
	cancel = wx.Button(dlg, wx.ID_CANCEL, cancelLabel)
	row.Add(ok, 0, wx.ALL, 4)
	row.Add(cancel, 0, wx.ALL, 4)
	sizer.Add(row, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
	ok.SetDefault()
	dlg.SetEscapeId(wx.ID_CANCEL)
	return ok, cancel


# ===================================================================== lista con filtro
class FilterListDialog(wx.Dialog):
	"""Lista para elegir un elemento, con un cuadro para filtrar (países, idiomas...)."""

	def __init__(self, parent: wx.Window | None, title: str, prompt: str, items: list[tuple[Any, str]]) -> None:
		super().__init__(default_parent(parent), title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._items = items
		self._visible = list(items)
		self.value: Any = None
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, "&Filtrar:")
		self.filter = wx.TextCtrl(self)
		sizer.Add(self.filter, 0, wx.EXPAND | wx.ALL, 6)
		addLabel(self, sizer, prompt)
		self.list = wx.ListBox(self, size=(420, 300), style=wx.LB_SINGLE)
		sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 6)
		_buttons(self, sizer)
		self.SetSizerAndFit(sizer)
		self.filter.Bind(wx.EVT_TEXT, lambda e: self._refilter())
		self.filter.Bind(wx.EVT_KEY_DOWN, self._onFilterKey)
		self.list.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._accept())
		self.Bind(wx.EVT_BUTTON, lambda e: self._accept(), id=wx.ID_OK)
		self._refilter()
		self.list.SetFocus()

	def _refilter(self) -> None:
		q = normalizeForSearch(self.filter.GetValue().strip())
		self._visible = [it for it in self._items if not q or all(t in normalizeForSearch(it[1]) for t in q.split())]
		self.list.Set([lbl for _v, lbl in self._visible])
		if self._visible:
			self.list.SetSelection(0)

	def _onFilterKey(self, evt: wx.KeyEvent) -> None:
		if evt.GetKeyCode() in (wx.WXK_DOWN, wx.WXK_NUMPAD_DOWN) and self._visible:
			self.list.SetFocus()
			return
		evt.Skip()

	def _accept(self) -> None:
		i = self.list.GetSelection()
		if i == wx.NOT_FOUND or not (0 <= i < len(self._visible)):
			wx.Bell()
			return
		self.value = self._visible[i][0]
		self.EndModal(wx.ID_OK)


def choose_from_list(parent: wx.Window | None, title: str, prompt: str, items: list[tuple[Any, str]]) -> Any:
	"""Pide elegir un elemento; devuelve su valor o ``None`` si se cancela."""
	dlg = FilterListDialog(parent, title, prompt, items)
	try:
		if show_modal(dlg) == wx.ID_OK:
			return dlg.value
		return None
	finally:
		dlg.Destroy()


# ===================================================================== emisora (nueva / editar)
class StationEditDialog(wx.Dialog):
	"""Crear o editar un favorito: nombre, dirección, categoría y notas."""

	def __init__(self, parent: wx.Window | None, station: Favorite | None = None, title: str | None = None, categories: list[Category] | None = None) -> None:
		if title is None:
			title = "Nueva emisora" if station is None else "Editar emisora"
		super().__init__(default_parent(parent), title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._station = station
		self._result: dict | None = None
		self._categories = categories or []
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, "&Nombre de la emisora:")
		self.txt_name = wx.TextCtrl(self, size=(420, -1))
		sizer.Add(self.txt_name, 0, wx.EXPAND | wx.ALL, 6)
		addLabel(self, sizer, "&URL de la emisora:")
		self.txt_url = wx.TextCtrl(self)
		sizer.Add(self.txt_url, 0, wx.EXPAND | wx.ALL, 6)
		addLabel(self, sizer, "Ca&tegoría:")
		self.choice_category = wx.Choice(self, choices=["(sin categoría)"] + [c.name for c in self._categories])
		sizer.Add(self.choice_category, 0, wx.EXPAND | wx.ALL, 6)
		addLabel(self, sizer, "N&otas (opcional):")
		self.txt_notes = wx.TextCtrl(self, size=(-1, 90), style=wx.TE_MULTILINE)
		sizer.Add(self.txt_notes, 1, wx.EXPAND | wx.ALL, 6)
		_buttons(self, sizer)
		self.SetSizerAndFit(sizer)
		self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
		self.choice_category.SetSelection(0)
		if station is not None:
			self.txt_name.SetValue(station.name)
			self.txt_url.SetValue(station.url)
			self.txt_notes.SetValue(station.notes or "")
			for i, c in enumerate(self._categories):
				if c.id == station.category_id:
					self.choice_category.SetSelection(i + 1)
		self.txt_name.SetFocus()

	def _on_ok(self, event: wx.CommandEvent) -> None:
		name = self.txt_name.GetValue().strip()
		url = self.txt_url.GetValue().strip()
		if not name:
			show_error("El nombre de la emisora no puede estar vacío.", "Error", self)
			self.txt_name.SetFocus()
			return
		if not url:
			show_error("La URL de la emisora no puede estar vacía.", "Error", self)
			self.txt_url.SetFocus()
			return
		if "://" not in url:
			show_error("La URL debe empezar por http:// o https://.", "Error", self)
			self.txt_url.SetFocus()
			return
		sel = self.choice_category.GetSelection()
		category_id = self._categories[sel - 1].id if sel > 0 else None
		self._result = {"name": name, "url": url, "notes": self.txt_notes.GetValue().strip(), "category_id": category_id}
		self.EndModal(wx.ID_OK)

	def get_result(self) -> dict | None:
		return self._result


# ===================================================================== información de la emisora
def station_info_text(station: Station | None, favorite: Favorite | None = None, category_name: str = "", stream: dict | None = None) -> str:
	"""Texto completo de información de una emisora (como el original)."""
	lines: list[str] = []
	na = "No disponible"
	if station is not None:
		s = station
		lines.append("=== Información básica ===")
		lines.append(f"Nombre: {s.name or na}")
		lines.append(f"URL: {s.url or na}")
		if s.url_resolved and s.url_resolved != s.url:
			lines.append(f"URL resuelta: {s.url_resolved}")
		if s.stationuuid:
			lines.append(f"UUID: {s.stationuuid}")
		lines.append("")
		lines.append("=== Ubicación ===")
		if s.country:
			lines.append(f"País: {s.country}")
		if s.countrycode:
			lines.append(f"Código de país: {s.countrycode}")
		if s.state:
			lines.append(f"Estado/Provincia: {s.state}")
		if s.geo_lat or s.geo_long:
			lines.append(f"Coordenadas: {s.geo_lat}, {s.geo_long}")
		lines.append("")
		lines.append("=== Idioma y contenido ===")
		if s.language:
			lines.append(f"Idioma: {s.language}")
		if s.languagecodes:
			lines.append(f"Códigos de idioma: {s.languagecodes}")
		if s.tags:
			lines.append(f"Etiquetas: {s.tags}")
		lines.append("")
		lines.append("=== Información técnica ===")
		if s.codec:
			lines.append(f"Codec: {s.codec}")
		if s.bitrate > 0:
			lines.append(f"Bitrate: {s.bitrate} kbps")
		if s.hls:
			lines.append("HLS (HTTP Live Streaming): Sí")
		if s.ssl_error:
			lines.append("Error SSL: Sí")
		if s.stationuuid:
			lines.append(f"Estado: {'Funcionando' if s.lastcheckok else 'No disponible'}")
		lines.append("")
		lines.append("=== Estadísticas ===")
		if s.votes:
			lines.append(f"Votos: {s.votes}")
		if s.clickcount:
			lines.append(f"Reproducciones totales: {s.clickcount}")
		if s.clicktrend:
			trend = "Subiendo" if s.clicktrend > 0 else "Bajando"
			lines.append(f"Tendencia: {trend} ({s.clicktrend})")
		lines.append("")
		lines.append("=== Fechas ===")
		if s.lastchangetime:
			lines.append(f"Última modificación: {s.lastchangetime}")
		if s.lastchecktime:
			lines.append(f"Última verificación: {s.lastchecktime}")
		if s.lastcheckoktime:
			lines.append(f"Última verificación OK: {s.lastcheckoktime}")
		lines.append("")
		lines.append("=== Enlaces ===")
		if s.favicon:
			lines.append(f"Icono: {s.favicon}")
		if s.homepage:
			lines.append(f"Página web: {s.homepage}")
	if stream:
		lines.append("")
		lines.append("=== Transmisión en curso ===")
		if stream.get("name"):
			lines.append(f"Nombre que envía la emisora: {stream['name']}")
		if stream.get("title"):
			lines.append(f"Suena ahora: {stream['title']}")
		if stream.get("format"):
			lines.append(f"Formato: {stream['format']}")
		if stream.get("bitrate"):
			lines.append(f"Calidad: {stream['bitrate']} kbps")
		if stream.get("frequency"):
			lines.append(f"Frecuencia: {stream['frequency']} Hz, {'estéreo' if stream.get('channels') == 2 else str(stream.get('channels', '')) + ' canales'}")
		if stream.get("genre"):
			lines.append(f"Género: {stream['genre']}")
		if stream.get("description"):
			lines.append(f"Descripción: {stream['description']}")
	if favorite is not None:
		f = favorite
		lines.append("")
		lines.append("--- Información de favorito ---")
		if category_name:
			lines.append(f"Categoría: {category_name}")
		if f.play_count > 0:
			lines.append(f"Veces reproducida: {f.play_count}")
		if f.last_played:
			lines.append(f"Última reproducción: {f.last_played.strftime(DATE_FORMAT)}")
		if f.created_at:
			lines.append(f"Añadida a favoritos: {f.created_at.strftime(DATE_FORMAT)}")
		if f.notes:
			lines.append(f"Notas: {f.notes}")
	if not lines:
		lines.append("No hay información disponible para esta emisora.")
	return "\n".join(lines)


class StationInfoDialog(wx.Dialog):
	"""Información detallada de una emisora (se completa con la API si hace falta)."""

	def __init__(self, parent: wx.Window | None, station: Station | None = None, favorite: Favorite | None = None, app: "RadioApp | None" = None, title: str | None = None) -> None:
		super().__init__(default_parent(parent), title=title or "Información de la emisora", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._station = station
		self._favorite = favorite
		self._app = app
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, "&Información de la emisora:")
		self.txt_info = wx.TextCtrl(self, size=(560, 380), style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
		sizer.Add(self.txt_info, 1, wx.EXPAND | wx.ALL, 6)
		row = wx.BoxSizer(wx.HORIZONTAL)
		self.btn_copy = wx.Button(self, label="Co&piar")
		self.btn_vote = wx.Button(self, label="&Votar por la emisora")
		self.btn_web = wx.Button(self, label="Abrir la página &web")
		close = wx.Button(self, wx.ID_CANCEL, "&Cerrar")
		for b in (self.btn_copy, self.btn_vote, self.btn_web, close):
			row.Add(b, 0, wx.ALL, 4)
		sizer.Add(row, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.btn_copy.Bind(wx.EVT_BUTTON, self._on_copy)
		self.btn_vote.Bind(wx.EVT_BUTTON, self._on_vote)
		self.btn_web.Bind(wx.EVT_BUTTON, self._on_web)
		self._refresh_buttons()
		self._show()
		self.txt_info.SetFocus()
		if app is not None and station is not None and station.stationuuid and not station.country:
			self.txt_info.SetValue("Obteniendo la información de Radio Browser...")
			threading.Thread(target=self._fetch, daemon=True, name="zRadioBASS-info").start()

	def _fetch(self) -> None:
		try:
			full = self._app.station_details(self._station)
		except Exception:
			log.debug("No se pudo completar la emisora", exc_info=True)
			full = self._station
		wx.CallAfter(self._loaded, full)

	def _loaded(self, station: Station) -> None:
		if not isAlive(self):
			return
		self._station = station
		self._refresh_buttons()
		self._show()

	def _show(self) -> None:
		category = ""
		stream = None
		if self._app is not None:
			if self._favorite is not None and self._favorite.category_id:
				cat = self._app.db.get_category(self._favorite.category_id)
				category = cat.name if cat else ""
			p = self._app.player
			if self._station is not None and p.is_active and p.current_station is not None and p.current_station.url == self._station.url:
				stream = p.stream_info()
		self.txt_info.SetValue(station_info_text(self._station, self._favorite, category, stream))
		self.txt_info.SetInsertionPoint(0)

	def _refresh_buttons(self) -> None:
		s = self._station
		self.btn_vote.Enable(bool(self._app is not None and s is not None and s.stationuuid))
		self.btn_web.Enable(bool(s is not None and s.homepage))

	def _on_copy(self, event: wx.CommandEvent) -> None:
		from tiresias import api, queue_handler

		queue_handler.queueFunction(api.copyToClip, self.txt_info.GetValue(), True)

	def _on_vote(self, event: wx.CommandEvent) -> None:
		station = self._station
		app = self._app
		if station is None or app is None:
			return
		self.btn_vote.Disable()

		def run() -> None:
			msg = app.vote(station)
			speakMessage(msg)
			wx.CallAfter(lambda: isAlive(self) and self.btn_vote.Enable())

		threading.Thread(target=run, daemon=True, name="zRadioBASS-votar").start()

	def _on_web(self, event: wx.CommandEvent) -> None:
		if self._station is not None and self._station.homepage:
			import webbrowser

			webbrowser.open(self._station.homepage)


# ===================================================================== categorías
class CategoryEditDialog(wx.Dialog):
	"""Crear o editar una categoría de favoritos."""

	def __init__(self, parent: wx.Window | None, category: Category | None = None) -> None:
		super().__init__(default_parent(parent), title="Nueva categoría" if category is None else "Editar categoría")
		self._category = category
		self._result: dict | None = None
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, "&Nombre de la categoría:")
		self.txt_name = wx.TextCtrl(self, size=(360, -1))
		sizer.Add(self.txt_name, 0, wx.EXPAND | wx.ALL, 6)
		addLabel(self, sizer, "&Descripción (opcional):")
		self.txt_description = wx.TextCtrl(self)
		sizer.Add(self.txt_description, 0, wx.EXPAND | wx.ALL, 6)
		_buttons(self, sizer)
		self.SetSizerAndFit(sizer)
		self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
		if category is not None:
			self.txt_name.SetValue(category.name)
			self.txt_description.SetValue(category.description or "")
		self.txt_name.SetFocus()

	def _on_ok(self, event: wx.CommandEvent) -> None:
		name = self.txt_name.GetValue().strip()
		if not name:
			show_error("El nombre de la categoría no puede estar vacío.", "Error", self)
			self.txt_name.SetFocus()
			return
		self._result = {"name": name, "description": self.txt_description.GetValue().strip()}
		self.EndModal(wx.ID_OK)

	def get_result(self) -> dict | None:
		return self._result


class CategoriesDialog(wx.Dialog):
	"""Gestionar las categorías de favoritos (nueva, editar, eliminar, mover)."""

	def __init__(self, parent: wx.Window | None, app: "RadioApp") -> None:
		super().__init__(default_parent(parent), title="Categorías de favoritos", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		from ..zr_core.events import EventType

		self._EventType = EventType
		self._app = app
		self._cats: list[Category] = []
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, "Ca&tegorías:")
		self.list = wx.ListBox(self, size=(380, 220), style=wx.LB_SINGLE)
		sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 6)
		row = wx.BoxSizer(wx.HORIZONTAL)
		self.btn_new = wx.Button(self, label="&Nueva...")
		self.btn_edit = wx.Button(self, label="&Editar...")
		self.btn_delete = wx.Button(self, label="E&liminar")
		self.btn_up = wx.Button(self, label="&Subir")
		self.btn_down = wx.Button(self, label="&Bajar")
		for b in (self.btn_new, self.btn_edit, self.btn_delete, self.btn_up, self.btn_down):
			row.Add(b, 0, wx.ALL, 4)
		sizer.Add(row, 0, wx.ALL, 2)
		close = wx.Button(self, wx.ID_CANCEL, "&Cerrar")
		sizer.Add(close, 0, wx.ALIGN_RIGHT | wx.ALL, 6)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.btn_new.Bind(wx.EVT_BUTTON, self._on_new)
		self.btn_edit.Bind(wx.EVT_BUTTON, self._on_edit)
		self.btn_delete.Bind(wx.EVT_BUTTON, self._on_delete)
		self.btn_up.Bind(wx.EVT_BUTTON, lambda e: self._move(-1))
		self.btn_down.Bind(wx.EVT_BUTTON, lambda e: self._move(1))
		self.list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_edit)
		self.list.Bind(wx.EVT_KEY_DOWN, self._on_key)
		self._reload()
		self.list.SetFocus()

	def _reload(self, select_id: int | None = None) -> None:
		db = self._app.db
		self._cats = db.get_categories()
		self.list.Set([f"{c.name} ({db.count_favorites_in_category(c.id)} emisoras)" + (f" - {c.description}" if c.description else "") for c in self._cats])
		idx = 0
		if select_id is not None:
			idx = next((i for i, c in enumerate(self._cats) if c.id == select_id), 0)
		if self._cats:
			self.list.SetSelection(idx)
		has = bool(self._cats)
		for b in (self.btn_edit, self.btn_delete, self.btn_up, self.btn_down):
			b.Enable(has)

	def _selected(self) -> Category | None:
		i = self.list.GetSelection()
		return self._cats[i] if 0 <= i < len(self._cats) else None

	def _on_key(self, evt: wx.KeyEvent) -> None:
		code = evt.GetKeyCode()
		if code == wx.WXK_DELETE:
			self._on_delete(None)
			return
		if evt.AltDown() and code == wx.WXK_UP:
			self._move(-1)
			return
		if evt.AltDown() and code == wx.WXK_DOWN:
			self._move(1)
			return
		evt.Skip()

	def _on_new(self, event: Any) -> None:
		dlg = CategoryEditDialog(self)
		try:
			if dlg.ShowModal() == wx.ID_OK and dlg.get_result():
				r = dlg.get_result()
				if self._app.db._category_exists(r["name"]):
					show_error("Ya existe una categoría con ese nombre.", "Error", self)
					return
				cat = Category(name=r["name"], description=r["description"])
				self._app.db.add_category(cat)
				self._app.event_bus.emit(self._EventType.CATEGORY_ADDED, cat)
				self._reload(cat.id)
		finally:
			dlg.Destroy()
		self.list.SetFocus()

	def _on_edit(self, event: Any) -> None:
		cat = self._selected()
		if cat is None:
			return
		dlg = CategoryEditDialog(self, cat)
		try:
			if dlg.ShowModal() == wx.ID_OK and dlg.get_result():
				r = dlg.get_result()
				if r["name"] != cat.name and self._app.db._category_exists(r["name"]):
					show_error("Ya existe una categoría con ese nombre.", "Error", self)
					return
				cat.name, cat.description = r["name"], r["description"]
				self._app.db.update_category(cat)
				self._app.event_bus.emit(self._EventType.CATEGORY_UPDATED, cat)
				self._reload(cat.id)
		finally:
			dlg.Destroy()
		self.list.SetFocus()

	def _on_delete(self, event: Any) -> None:
		cat = self._selected()
		if cat is None:
			return
		if not show_confirm(f"¿Eliminar la categoría «{cat.name}»? Sus emisoras seguirán en favoritos, sin categoría.", "Confirmar", self):
			return
		self._app.db.delete_category(cat.id)
		self._app.event_bus.emit(self._EventType.CATEGORY_REMOVED, cat)
		self._reload()
		self.list.SetFocus()

	def _move(self, direction: int) -> None:
		i = self.list.GetSelection()
		j = i + direction
		if not (0 <= i < len(self._cats)) or not (0 <= j < len(self._cats)):
			wx.Bell()
			return
		cats = list(self._cats)
		cats[i], cats[j] = cats[j], cats[i]
		for n, c in enumerate(cats):
			c.order = n + 1
			self._app.db.update_category(c)
		moved = cats[j]
		self._app.event_bus.emit(self._EventType.CATEGORY_UPDATED, moved)
		self._reload(moved.id)
		speakMessage(f"{j + 1} de {len(cats)}")


# ===================================================================== programar grabación
class ScheduleRecordingDialog(wx.Dialog):
	"""Programar una grabación: emisora, dirección, inicio, fin y nombre del archivo."""

	def __init__(self, parent: wx.Window | None, station_name: str = "", station_url: str = "", config: Any = None, favorites: list[Favorite] | None = None) -> None:
		super().__init__(default_parent(parent), title="Programar grabación", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._config = config
		self._favorites = favorites or []
		self._result: dict | None = None
		now = datetime.now()
		start = (now + timedelta(minutes=5)).replace(second=0, microsecond=0)
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, "&Emisora a grabar:")
		self.txt_station = wx.TextCtrl(self, value=station_name, size=(420, -1))
		sizer.Add(self.txt_station, 0, wx.EXPAND | wx.ALL, 6)
		addLabel(self, sizer, "&URL de la emisora:")
		self.txt_url = wx.TextCtrl(self, value=station_url)
		sizer.Add(self.txt_url, 0, wx.EXPAND | wx.ALL, 6)
		self.btn_fav = wx.Button(self, label="Elegir de &favoritos...")
		self.btn_fav.Enable(bool(self._favorites))
		sizer.Add(self.btn_fav, 0, wx.ALL, 6)
		addLabel(self, sizer, "&Inicio (formato DD/MM/AAAA HH:MM):")
		self.txt_start = wx.TextCtrl(self, value=start.strftime(DATE_FORMAT))
		sizer.Add(self.txt_start, 0, wx.EXPAND | wx.ALL, 6)
		addLabel(self, sizer, "Fi&n (formato DD/MM/AAAA HH:MM):")
		self.txt_end = wx.TextCtrl(self, value=(start + timedelta(hours=1)).strftime(DATE_FORMAT))
		sizer.Add(self.txt_end, 0, wx.EXPAND | wx.ALL, 6)
		addLabel(self, sizer, "Nombre del &archivo (sin extensión):")
		self.txt_filename = wx.TextCtrl(self, value=os.path.splitext(recording_filename(station_name or "radio", now))[0])
		sizer.Add(self.txt_filename, 0, wx.EXPAND | wx.ALL, 6)
		folder = str(config.recordings_dir) if config is not None else ""
		self.lbl_folder = wx.StaticText(self, label=f"Se guardará en formato WAV en: {folder}")
		sizer.Add(self.lbl_folder, 0, wx.ALL, 6)
		_buttons(self, sizer, okLabel="&Programar")
		self.SetSizerAndFit(sizer)
		self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
		self.btn_fav.Bind(wx.EVT_BUTTON, self._on_favorite)
		self.txt_station.SetFocus()

	def _on_favorite(self, event: wx.CommandEvent) -> None:
		value = choose_from_list(self, "Elegir de favoritos", "Fa&voritos:", [(f, f.name) for f in self._favorites])
		if value is None:
			return
		self.txt_station.SetValue(value.name)
		self.txt_url.SetValue(value.url)
		self.txt_filename.SetValue(os.path.splitext(recording_filename(value.name))[0])
		self.txt_start.SetFocus()

	def _on_ok(self, event: wx.CommandEvent) -> None:
		name = self.txt_station.GetValue().strip()
		url = self.txt_url.GetValue().strip()
		filename = self.txt_filename.GetValue().strip()
		if not name or not url:
			show_error("Debe especificar la emisora y su URL.", "Error", self)
			(self.txt_station if not name else self.txt_url).SetFocus()
			return
		try:
			start = datetime.strptime(self.txt_start.GetValue().strip(), DATE_FORMAT)
		except ValueError:
			show_error("Formato de fecha de inicio incorrecto.\nUse DD/MM/AAAA HH:MM (ej: 25/12/2026 18:30)", "Error", self)
			self.txt_start.SetFocus()
			return
		try:
			end = datetime.strptime(self.txt_end.GetValue().strip(), DATE_FORMAT)
		except ValueError:
			show_error("Formato de fecha de fin incorrecto.\nUse DD/MM/AAAA HH:MM (ej: 25/12/2026 19:30)", "Error", self)
			self.txt_end.SetFocus()
			return
		if start <= datetime.now() - timedelta(minutes=1):
			show_error("La fecha de inicio debe ser futura.", "Error", self)
			self.txt_start.SetFocus()
			return
		if start >= end:
			show_error("La hora de inicio debe ser anterior a la de fin.", "Error", self)
			self.txt_end.SetFocus()
			return
		if not filename:
			show_error("Especifique un nombre para el archivo.", "Error", self)
			self.txt_filename.SetFocus()
			return
		folder = self._config.recordings_dir if self._config is not None else os.path.join(os.path.expanduser("~"), "Music")
		self._result = {
			"station_name": name,
			"station_url": url,
			"start_time": start,
			"end_time": end,
			"output_path": os.path.join(str(folder), safe_filename(filename) + ".wav"),
		}
		self.EndModal(wx.ID_OK)

	def get_result(self) -> dict | None:
		return self._result


class ScheduledRecordingsDialog(wx.Dialog):
	"""Ver y gestionar las grabaciones programadas."""

	def __init__(self, parent: wx.Window | None, app: "RadioApp") -> None:
		super().__init__(default_parent(parent), title="Grabaciones programadas", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._app = app
		self._recs: list = []
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.chk_all = wx.CheckBox(self, label="Mostrar también las &terminadas, canceladas y perdidas")
		sizer.Add(self.chk_all, 0, wx.ALL, 6)
		addLabel(self, sizer, "&Grabaciones:")
		self.list = wx.ListBox(self, size=(560, 240), style=wx.LB_SINGLE)
		sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 6)
		row = wx.BoxSizer(wx.HORIZONTAL)
		self.btn_new = wx.Button(self, label="&Programar...")
		self.btn_cancel_rec = wx.Button(self, label="Ca&ncelar grabación")
		self.btn_delete = wx.Button(self, label="&Quitar de la lista")
		self.btn_clear = wx.Button(self, label="&Limpiar terminadas")
		self.btn_folder = wx.Button(self, label="Abrir la carpeta de grabacione&s")
		for b in (self.btn_new, self.btn_cancel_rec, self.btn_delete, self.btn_clear, self.btn_folder):
			row.Add(b, 0, wx.ALL, 4)
		sizer.Add(row, 0, wx.ALL, 2)
		close = wx.Button(self, wx.ID_CANCEL, "&Cerrar")
		sizer.Add(close, 0, wx.ALIGN_RIGHT | wx.ALL, 6)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.chk_all.Bind(wx.EVT_CHECKBOX, lambda e: self._reload())
		self.btn_new.Bind(wx.EVT_BUTTON, self._on_new)
		self.btn_cancel_rec.Bind(wx.EVT_BUTTON, self._on_cancel_rec)
		self.btn_delete.Bind(wx.EVT_BUTTON, self._on_delete)
		self.btn_clear.Bind(wx.EVT_BUTTON, self._on_clear)
		self.btn_folder.Bind(wx.EVT_BUTTON, self._on_folder)
		self.list.Bind(wx.EVT_LISTBOX, lambda e: self._update_buttons())
		self.list.Bind(wx.EVT_KEY_DOWN, self._on_key)
		self._reload()
		self.list.SetFocus()

	def _reload(self) -> None:
		allRecs = self.chk_all.GetValue()
		self._recs = self._app.scheduler.all() if allRecs else self._app.scheduler.active()
		items = []
		for i, r in enumerate(self._recs, 1):
			status = STATUS_NAMES.get(r.status, r.status)
			txt = f"{i}. {r.station_name} - {r.start_time.strftime(DATE_FORMAT)} a {r.end_time.strftime('%H:%M') if r.end_time.date() == r.start_time.date() else r.end_time.strftime(DATE_FORMAT)} - {status}"
			if r.error:
				txt += f" ({r.error})"
			txt += f" - {os.path.basename(r.output_path)}"
			items.append(txt)
		if not items:
			items = ["No hay grabaciones programadas."]
		self.list.Set(items)
		self.list.SetSelection(0)
		self._update_buttons()

	def _selected(self) -> Any:
		i = self.list.GetSelection()
		return self._recs[i] if 0 <= i < len(self._recs) else None

	def _update_buttons(self) -> None:
		r = self._selected()
		self.btn_cancel_rec.Enable(bool(r and r.active))
		self.btn_delete.Enable(bool(r and not r.active))

	def _on_key(self, evt: wx.KeyEvent) -> None:
		if evt.GetKeyCode() == wx.WXK_DELETE:
			r = self._selected()
			if r is not None:
				(self._on_cancel_rec if r.active else self._on_delete)(None)
			return
		evt.Skip()

	def _on_new(self, event: Any) -> None:
		schedule_recording_dialog(self, self._app)
		self._reload()

	def _on_cancel_rec(self, event: Any) -> None:
		r = self._selected()
		if r is None or not r.active:
			return
		if show_confirm(f"¿Desea cancelar esta grabación programada?\n\n{r.station_name}", "Confirmar", self):
			if self._app.cancel_scheduled_recording(r.id):
				speakMessage("Grabación programada cancelada.")
			self._reload()
		self.list.SetFocus()

	def _on_delete(self, event: Any) -> None:
		r = self._selected()
		if r is None or r.active:
			return
		self._app.db.delete_scheduled_recording(r.id)
		self._reload()
		self.list.SetFocus()

	def _on_clear(self, event: Any) -> None:
		n = self._app.db.clear_finished_recordings()
		speakMessage(f"Se quitaron {n} grabaciones terminadas")
		self._reload()
		self.list.SetFocus()

	def _on_folder(self, event: Any) -> None:
		err = self._app.open_recordings_folder()
		if err:
			show_error(err, "Error", self)


def schedule_recording_dialog(parent: wx.Window | None, app: "RadioApp") -> bool:
	"""Abre «Programar grabación» con la emisora actual y programa si se acepta."""
	p = app.player
	name = url = ""
	if p.current_station is not None and p.is_active:
		name = p.current_station.name
		url = p.current_station.url or p.current_url
	dlg = ScheduleRecordingDialog(parent, station_name=name, station_url=url, config=app.config, favorites=app.db.get_favorites())
	try:
		if show_modal(dlg) != wx.ID_OK or not dlg.get_result():
			return False
		r = dlg.get_result()
	finally:
		dlg.Destroy()
	rec = app.schedule_recording(r["station_url"], r["station_name"], r["start_time"], r["end_time"], r["output_path"])
	if rec is None:
		show_error("No se pudo programar la grabación.", "Error", parent)
		return False
	show_info(
		"Grabación programada correctamente.\n\n"
		f"Emisora: {r['station_name']}\nInicio: {r['start_time'].strftime(DATE_FORMAT)}\nFin: {r['end_time'].strftime(DATE_FORMAT)}\nArchivo: {rec.output_path}",
		"Grabación programada",
		parent,
	)
	return True


# ===================================================================== limpiar historial
def clear_history_dialog(parent: wx.Window | None, app: "RadioApp") -> int | None:
	"""Pregunta qué parte del historial borrar. Devuelve cuántas entradas se borraron."""
	options = [(None, "Todo el historial"), (7, "Lo anterior a 7 días"), (30, "Lo anterior a 30 días"), (90, "Lo anterior a 90 días")]
	dlg = wx.SingleChoiceDialog(default_parent(parent), "¿Qué desea eliminar del historial?", "Limpiar historial", [lbl for _v, lbl in options])
	try:
		if show_modal(dlg) != wx.ID_OK:
			return None
		days = options[dlg.GetSelection()][0]
	finally:
		dlg.Destroy()
	what = "todo el historial" if days is None else f"el historial anterior a {days} días"
	if not show_confirm(f"¿Está seguro de que desea eliminar {what}?", "Confirmar", parent):
		return None
	from ..zr_core.events import EventType

	count = app.db.clear_history(days)
	app.event_bus.emit(EventType.HISTORY_CHANGED, None)
	show_info(f"Se eliminaron {count} registros del historial", "Historial limpiado", parent)
	return count


# ===================================================================== plugins
class PluginsDialog(wx.Dialog):
	"""Administrador de plugins: activar, desactivar, configurar, recargar."""

	def __init__(self, parent: wx.Window | None, app: "RadioApp") -> None:
		super().__init__(default_parent(parent), title="Administrar plugins", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._app = app
		self._ids: list[str] = []
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, "&Plugins (la casilla indica si está activado):")
		self.list = wx.CheckListBox(self, size=(480, 200))
		sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 6)
		addLabel(self, sizer, "&Detalles:")
		self.details = wx.TextCtrl(self, size=(480, 130), style=wx.TE_MULTILINE | wx.TE_READONLY)
		sizer.Add(self.details, 0, wx.EXPAND | wx.ALL, 6)
		row = wx.BoxSizer(wx.HORIZONTAL)
		self.btn_settings = wx.Button(self, label="C&onfigurar...")
		self.btn_reload = wx.Button(self, label="&Recargar plugins")
		self.btn_folder = wx.Button(self, label="Abrir la carpeta de plugins del &usuario")
		for b in (self.btn_settings, self.btn_reload, self.btn_folder):
			row.Add(b, 0, wx.ALL, 4)
		sizer.Add(row, 0, wx.ALL, 2)
		close = wx.Button(self, wx.ID_CANCEL, "&Cerrar")
		sizer.Add(close, 0, wx.ALIGN_RIGHT | wx.ALL, 6)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.list.Bind(wx.EVT_CHECKLISTBOX, self._on_check)
		self.list.Bind(wx.EVT_LISTBOX, lambda e: self._show_details())
		self.btn_settings.Bind(wx.EVT_BUTTON, self._on_settings)
		self.btn_reload.Bind(wx.EVT_BUTTON, self._on_reload)
		self.btn_folder.Bind(wx.EVT_BUTTON, self._on_folder)
		self._reload()
		self.list.SetFocus()

	def _reload(self, select: str | None = None) -> None:
		pm = self._app.plugin_manager
		self._ids = sorted(pm.get_all_plugin_ids(), key=lambda i: (pm.get_plugin_metadata(i).name if pm.get_plugin_metadata(i) else i).casefold())
		labels = []
		for pid in self._ids:
			md = pm.get_plugin_metadata(pid)
			labels.append(f"{md.name if md else pid} {md.version if md else ''}".strip())
		self.list.Set(labels)
		for i, pid in enumerate(self._ids):
			self.list.Check(i, pm.is_plugin_enabled(pid))
		if self._ids:
			idx = self._ids.index(select) if select in self._ids else 0
			self.list.SetSelection(idx)
		self._show_details()

	def _selected(self) -> str | None:
		i = self.list.GetSelection()
		return self._ids[i] if 0 <= i < len(self._ids) else None

	def _show_details(self) -> None:
		from ..zr_core.plugin_manager import PLUGIN_STATE_NAMES

		pid = self._selected()
		pm = self._app.plugin_manager
		if pid is None:
			self.details.SetValue("No hay plugins.")
			self.btn_settings.Disable()
			return
		md = pm.get_plugin_metadata(pid)
		lines = [
			f"Nombre: {md.name}",
			f"Identificador: {md.id}",
			f"Versión: {md.version}",
			f"Autor: {md.author or 'desconocido'}",
			f"Descripción: {md.description or '(sin descripción)'}",
			f"Estado: {PLUGIN_STATE_NAMES.get(pm.get_plugin_state(pid), '')}",
			f"Origen: {'incluido con zRadio BASS' if pm.is_builtin(pid) else 'plugin del usuario'}",
			f"Archivo: {pm.get_plugin_path(pid)}",
		]
		if md.dependencies:
			lines.append("Necesita: " + ", ".join(md.dependencies))
		err = pm.get_plugin_error(pid)
		if err:
			lines.append(f"Último error: {err}")
		self.details.SetValue("\n".join(lines))
		from ..zr_core.plugin_manager import PluginBase

		plugin = pm.get_plugin(pid)
		self.btn_settings.Enable(plugin is not None and type(plugin).get_settings_panel is not PluginBase.get_settings_panel)

	def _on_check(self, event: wx.CommandEvent) -> None:
		i = event.GetInt()
		if not (0 <= i < len(self._ids)):
			return
		pid = self._ids[i]
		pm = self._app.plugin_manager
		if self.list.IsChecked(i):
			ok = pm.enable_plugin(pid)
			speakMessage("Plugin activado" if ok else "No se pudo activar el plugin")
		else:
			pm.disable_plugin(pid)
			speakMessage("Plugin desactivado")
		self.list.SetSelection(i)
		self._show_details()

	def _on_settings(self, event: Any) -> None:
		pid = self._selected()
		plugin = self._app.plugin_manager.get_plugin(pid) if pid else None
		if plugin is None:
			return
		dlg = wx.Dialog(self, title=f"Opciones de {plugin.metadata.name}")
		sizer = wx.BoxSizer(wx.VERTICAL)
		panel = None
		try:
			panel = plugin.get_settings_panel(dlg)
		except Exception:
			log.exception("Error creando el panel de %s", pid)
		if panel is None:
			dlg.Destroy()
			show_info("Este plugin no tiene opciones.", "Opciones", self)
			return
		sizer.Add(panel, 1, wx.EXPAND | wx.ALL, 6)
		_buttons(dlg, sizer)
		dlg.SetSizerAndFit(sizer)
		try:
			if dlg.ShowModal() == wx.ID_OK and hasattr(panel, "save"):
				panel.save()
		finally:
			dlg.Destroy()

	def _on_reload(self, event: Any) -> None:
		pid = self._selected()
		found = self._app.plugin_manager.rediscover()
		speakMessage(f"Plugins recargados: {len(found)}")
		self._reload(pid)

	def _on_folder(self, event: Any) -> None:
		folder = self._app.plugin_manager.user_dir
		if folder is None:
			return
		try:
			os.makedirs(folder, exist_ok=True)
			os.startfile(str(folder))  # noqa: S606
		except OSError as e:
			show_error(f"No se pudo abrir la carpeta: {e}", "Error", self)


# ===================================================================== estadísticas del servidor
def server_stats_text(stats: dict, server: str) -> str:
	if not stats:
		return "No se pudieron obtener las estadísticas del servidor."
	names = {
		"supported_version": "Versión de la API",
		"software_version": "Versión del programa",
		"status": "Estado",
		"stations": "Emisoras",
		"stations_broken": "Emisoras que no funcionan",
		"tags": "Etiquetas",
		"clicks_last_hour": "Reproducciones en la última hora",
		"clicks_last_day": "Reproducciones en el último día",
		"languages": "Idiomas",
		"countries": "Países",
	}
	lines = [f"Servidor: {server}", ""]
	for key, label in names.items():
		if key in stats:
			lines.append(f"{label}: {stats[key]}")
	for key, value in stats.items():
		if key not in names:
			lines.append(f"{key}: {value}")
	return "\n".join(lines)


def run_in_thread(func: Callable[[], Any], done: Callable[[Any], None]) -> None:
	"""Ejecuta ``func`` en un hilo y pasa el resultado a ``done`` en el hilo de la interfaz."""

	def job() -> None:
		try:
			result = func()
		except Exception:
			log.exception("Error en una tarea de fondo")
			result = None
		wx.CallAfter(done, result)

	threading.Thread(target=job, daemon=True, name="zRadioBASS-tarea").start()
