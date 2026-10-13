# -*- coding: utf-8 -*-
# Copyright (C) 2025-2026 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General GNU.

"""Base de datos SQLite de zRadio BASS.

Guarda favoritos con categorías, historial de reproducción, grabaciones
programadas y las cachés de países, idiomas y etiquetas. El esquema es el
del complemento original (más la tabla de grabaciones programadas), así que
una base de datos ``zradiobass.db`` de NVDA también se puede usar.

Las fechas se guardan en hora local con formato ISO.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from tiresias.log import getLogger

from .models import Category, Favorite, PlaybackHistory, ScheduledRecording, Station

log = getLogger("zRadioBASS.database")

#: Tablas de caché admitidas por :meth:`DatabaseManager.is_cache_valid`.
CACHE_TABLES = ("cache_countries", "cache_languages", "cache_tags")

#: Ordenaciones de favoritos: (título, cláusula ORDER BY).
FAVORITE_SORTS = [
	("Orden personal", '"order", name COLLATE NOCASE'),
	("Nombre", "name COLLATE NOCASE"),
	("Más escuchadas", 'play_count DESC, "order"'),
	("Escuchadas recientemente", "last_played IS NULL, last_played DESC, \"order\""),
	("Añadidas recientemente", "created_at DESC, id DESC"),
]


def _now() -> str:
	return datetime.now().isoformat(timespec="seconds")


def _parseDate(value: Any) -> datetime | None:
	if not value:
		return None
	try:
		return datetime.fromisoformat(str(value).replace("Z", ""))
	except ValueError:
		return None


class _Result:
	"""Resultado ya leído de una consulta (se puede usar fuera del cerrojo)."""

	def __init__(self, rows: list, rowcount: int, lastrowid: int | None) -> None:
		self._rows = rows
		self.rowcount = rowcount
		self.lastrowid = lastrowid

	def fetchone(self) -> Any:
		return self._rows[0] if self._rows else None

	def fetchall(self) -> list:
		return list(self._rows)


class _LockedConnection:
	"""Una sola conexión SQLite compartida por todos los hilos, con cerrojo.

	Cada sentencia se ejecuta y se lee entera dentro del cerrojo, así que
	ningún hilo usa la conexión a la vez que otro ni después de cerrarla.
	"""

	def __init__(self, path: str) -> None:
		self._lock = threading.RLock()
		self._conn: sqlite3.Connection | None = sqlite3.connect(path, check_same_thread=False, timeout=10)
		self._conn.row_factory = sqlite3.Row
		self._conn.execute("PRAGMA foreign_keys = ON")

	def _c(self) -> sqlite3.Connection:
		if self._conn is None:
			raise sqlite3.ProgrammingError("La base de datos de zRadio BASS está cerrada")
		return self._conn

	def execute(self, sql: str, params: Any = ()) -> _Result:
		with self._lock:
			cur = self._c().execute(sql, params)
			rows = cur.fetchall() if cur.description else []
			return _Result(rows, cur.rowcount, cur.lastrowid)

	def executescript(self, script: str) -> None:
		with self._lock:
			self._c().executescript(script)

	def commit(self) -> None:
		with self._lock:
			self._c().commit()

	def close(self) -> None:
		with self._lock:
			if self._conn is not None:
				try:
					self._conn.close()
				finally:
					self._conn = None

	@property
	def closed(self) -> bool:
		return self._conn is None


class DatabaseManager:
	"""Operaciones sobre la base de datos (seguras desde cualquier hilo)."""

	def __init__(self, db_path: str | Path) -> None:
		self._db_path = str(db_path)
		self._conn = _LockedConnection(self._db_path)
		# Las operaciones de varias sentencias se hacen enteras sin mezclarse.
		self._writeLock = self._conn._lock
		self._init_database()

	@property
	def conn(self) -> _LockedConnection:
		return self._conn

	@property
	def path(self) -> str:
		return self._db_path

	def close(self) -> None:
		"""Cierra la base de datos (las llamadas posteriores fallan con un error)."""
		self._conn.close()

	def _init_database(self) -> None:
		c = self.conn
		with self._writeLock:
			c.executescript(
				"""
				CREATE TABLE IF NOT EXISTS categories (
					id INTEGER PRIMARY KEY AUTOINCREMENT,
					name TEXT NOT NULL UNIQUE,
					description TEXT DEFAULT '',
					color TEXT DEFAULT '#0078D4',
					"order" INTEGER DEFAULT 0,
					created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
				);
				CREATE TABLE IF NOT EXISTS favorites (
					id INTEGER PRIMARY KEY AUTOINCREMENT,
					name TEXT NOT NULL,
					url TEXT NOT NULL,
					station_uuid TEXT,
					category_id INTEGER,
					"order" INTEGER DEFAULT 0,
					play_count INTEGER DEFAULT 0,
					last_played TIMESTAMP,
					notes TEXT DEFAULT '',
					created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
					FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
				);
				CREATE TABLE IF NOT EXISTS history (
					id INTEGER PRIMARY KEY AUTOINCREMENT,
					station_name TEXT NOT NULL,
					station_url TEXT NOT NULL,
					station_uuid TEXT DEFAULT '',
					played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
					duration_seconds INTEGER DEFAULT 0
				);
				CREATE TABLE IF NOT EXISTS cache_countries (
					code TEXT PRIMARY KEY,
					name TEXT NOT NULL,
					name_localized TEXT,
					station_count INTEGER DEFAULT 0,
					updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
				);
				CREATE TABLE IF NOT EXISTS cache_languages (
					name TEXT PRIMARY KEY,
					station_count INTEGER DEFAULT 0,
					updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
				);
				CREATE TABLE IF NOT EXISTS cache_tags (
					name TEXT PRIMARY KEY,
					station_count INTEGER DEFAULT 0,
					updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
				);
				CREATE TABLE IF NOT EXISTS statistics (
					id INTEGER PRIMARY KEY AUTOINCREMENT,
					total_play_time_seconds INTEGER DEFAULT 0,
					total_stations_played INTEGER DEFAULT 0,
					favorite_station_uuid TEXT,
					last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
				);
				CREATE TABLE IF NOT EXISTS scheduled_recordings (
					id INTEGER PRIMARY KEY AUTOINCREMENT,
					station_name TEXT NOT NULL,
					station_url TEXT NOT NULL,
					start_time TEXT NOT NULL,
					end_time TEXT NOT NULL,
					output_path TEXT NOT NULL,
					status TEXT DEFAULT 'pending',
					error TEXT DEFAULT ''
				);
				CREATE INDEX IF NOT EXISTS idx_favorites_category ON favorites(category_id);
				CREATE INDEX IF NOT EXISTS idx_favorites_order ON favorites("order");
				CREATE INDEX IF NOT EXISTS idx_history_played_at ON history(played_at);
				"""
			)
			cur = c.execute("SELECT COUNT(*) FROM categories WHERE name = 'General'")
			if cur.fetchone()[0] == 0:
				c.execute('INSERT INTO categories (name, description, "order", created_at) VALUES (?, ?, 0, ?)', ("General", "Categoría por defecto", _now()))
			c.commit()

	# ------------------------------------------------------------- categorías
	@staticmethod
	def _category(row: sqlite3.Row) -> Category:
		return Category(
			id=row["id"],
			name=row["name"],
			description=row["description"] or "",
			color=row["color"] or "#0078D4",
			order=row["order"] or 0,
			created_at=_parseDate(row["created_at"]),
		)

	def get_categories(self) -> list[Category]:
		rows = self.conn.execute('SELECT * FROM categories ORDER BY "order", name COLLATE NOCASE').fetchall()
		return [self._category(r) for r in rows]

	def get_category(self, category_id: int | None) -> Category | None:
		if category_id is None:
			return None
		row = self.conn.execute("SELECT * FROM categories WHERE id = ?", (category_id,)).fetchone()
		return self._category(row) if row else None

	def add_category(self, category: Category) -> int:
		with self._writeLock:
			c = self.conn
			if not category.order:
				category.order = (c.execute('SELECT MAX("order") FROM categories').fetchone()[0] or 0) + 1
			cur = c.execute(
				'INSERT INTO categories (name, description, color, "order", created_at) VALUES (?, ?, ?, ?, ?)',
				(category.name, category.description, category.color, category.order, _now()),
			)
			c.commit()
			category.id = cur.lastrowid
			return int(cur.lastrowid)

	def update_category(self, category: Category) -> bool:
		with self._writeLock:
			cur = self.conn.execute(
				'UPDATE categories SET name = ?, description = ?, color = ?, "order" = ? WHERE id = ?',
				(category.name, category.description, category.color, category.order, category.id),
			)
			self.conn.commit()
			return cur.rowcount > 0

	def delete_category(self, category_id: int) -> bool:
		"""Borra una categoría; sus favoritos quedan sin categoría."""
		with self._writeLock:
			c = self.conn
			c.execute("UPDATE favorites SET category_id = NULL WHERE category_id = ?", (category_id,))
			cur = c.execute("DELETE FROM categories WHERE id = ?", (category_id,))
			c.commit()
			return cur.rowcount > 0

	def _category_exists(self, name: str) -> bool:
		return self.conn.execute("SELECT 1 FROM categories WHERE name = ?", (name,)).fetchone() is not None

	def category_id_by_name(self, name: str) -> int | None:
		row = self.conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()
		return int(row[0]) if row else None

	def count_favorites_in_category(self, category_id: int) -> int:
		return int(self.conn.execute("SELECT COUNT(*) FROM favorites WHERE category_id = ?", (category_id,)).fetchone()[0])

	# ------------------------------------------------------------- favoritos
	@staticmethod
	def _favorite(row: sqlite3.Row) -> Favorite:
		return Favorite(
			id=row["id"],
			name=row["name"],
			url=row["url"],
			station_uuid=row["station_uuid"],
			category_id=row["category_id"],
			order=row["order"] or 0,
			play_count=row["play_count"] or 0,
			last_played=_parseDate(row["last_played"]),
			notes=row["notes"] or "",
			created_at=_parseDate(row["created_at"]),
		)

	def get_favorites(self, category_id: int | None = None, limit: int | None = None, offset: int = 0, sort: int = 0) -> list[Favorite]:
		"""Favoritos (de una categoría si se indica), con la ordenación ``sort`` de :data:`FAVORITE_SORTS`."""
		query = "SELECT * FROM favorites"
		params: list[Any] = []
		if category_id is not None:
			query += " WHERE category_id = ?"
			params.append(category_id)
		order = FAVORITE_SORTS[sort][1] if 0 <= sort < len(FAVORITE_SORTS) else FAVORITE_SORTS[0][1]
		query += f" ORDER BY {order}"
		if limit is not None:
			query += " LIMIT ? OFFSET ?"
			params.extend([limit, offset])
		return [self._favorite(r) for r in self.conn.execute(query, params).fetchall()]

	def get_favorite_by_id(self, favorite_id: int) -> Favorite | None:
		row = self.conn.execute("SELECT * FROM favorites WHERE id = ?", (favorite_id,)).fetchone()
		return self._favorite(row) if row else None

	def get_favorite_by_url(self, url: str) -> Favorite | None:
		row = self.conn.execute("SELECT * FROM favorites WHERE url = ?", (url,)).fetchone()
		return self._favorite(row) if row else None

	def add_favorite(self, favorite: Favorite) -> int:
		with self._writeLock:
			c = self.conn
			next_order = (c.execute('SELECT MAX("order") FROM favorites').fetchone()[0] or 0) + 1
			created = (favorite.created_at or datetime.now()).isoformat(timespec="seconds")
			cur = c.execute(
				'INSERT INTO favorites (name, url, station_uuid, category_id, "order", notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
				(favorite.name, favorite.url, favorite.station_uuid, favorite.category_id, next_order, favorite.notes, created),
			)
			c.commit()
			favorite.id = cur.lastrowid
			favorite.order = next_order
			return int(cur.lastrowid)

	def update_favorite(self, favorite: Favorite) -> bool:
		with self._writeLock:
			cur = self.conn.execute(
				'UPDATE favorites SET name = ?, url = ?, station_uuid = ?, category_id = ?, "order" = ?, notes = ? WHERE id = ?',
				(favorite.name, favorite.url, favorite.station_uuid, favorite.category_id, favorite.order, favorite.notes, favorite.id),
			)
			self.conn.commit()
			return cur.rowcount > 0

	def delete_favorite(self, favorite_id: int) -> bool:
		with self._writeLock:
			cur = self.conn.execute("DELETE FROM favorites WHERE id = ?", (favorite_id,))
			self.conn.commit()
			return cur.rowcount > 0

	def favorite_exists(self, url: str) -> bool:
		return self.conn.execute("SELECT 1 FROM favorites WHERE url = ?", (url,)).fetchone() is not None

	def increment_play_count(self, favorite_id: int) -> None:
		with self._writeLock:
			self.conn.execute("UPDATE favorites SET play_count = play_count + 1, last_played = ? WHERE id = ?", (_now(), favorite_id))
			self.conn.commit()

	def increment_play_count_by_url(self, url: str) -> bool:
		with self._writeLock:
			cur = self.conn.execute("UPDATE favorites SET play_count = play_count + 1, last_played = ? WHERE url = ?", (_now(), url))
			self.conn.commit()
			return cur.rowcount > 0

	def reorder_favorites(self, order_map: dict[int, int]) -> None:
		with self._writeLock:
			for fav_id, new_order in order_map.items():
				self.conn.execute('UPDATE favorites SET "order" = ? WHERE id = ?', (new_order, fav_id))
			self.conn.commit()

	def move_favorite(self, favorite_id: int, direction: int) -> bool:
		"""Sube (-1) o baja (1) un favorito en el orden personal."""
		favorites = self.get_favorites()
		idx = next((i for i, f in enumerate(favorites) if f.id == favorite_id), None)
		if idx is None:
			return False
		new_idx = idx + direction
		if new_idx < 0 or new_idx >= len(favorites):
			return False
		favorites[idx], favorites[new_idx] = favorites[new_idx], favorites[idx]
		self.reorder_favorites({f.id: i for i, f in enumerate(favorites)})
		return True

	def search_favorites(self, query: str) -> list[Favorite]:
		rows = self.conn.execute(
			'SELECT * FROM favorites WHERE name LIKE ? OR notes LIKE ? ORDER BY "order", name', (f"%{query}%", f"%{query}%")
		).fetchall()
		return [self._favorite(r) for r in rows]

	# ------------------------------------------------------------- historial
	def add_to_history(self, station: Station) -> int:
		with self._writeLock:
			cur = self.conn.execute(
				"INSERT INTO history (station_name, station_url, station_uuid, played_at) VALUES (?, ?, ?, ?)",
				(station.name, station.url, station.stationuuid or "", _now()),
			)
			self.conn.commit()
			return int(cur.lastrowid)

	def set_history_duration(self, history_id: int, seconds: int) -> None:
		with self._writeLock:
			self.conn.execute("UPDATE history SET duration_seconds = ? WHERE id = ?", (int(seconds), history_id))
			self.conn.commit()

	def get_history(self, limit: int = 50, offset: int = 0) -> list[PlaybackHistory]:
		rows = self.conn.execute("SELECT * FROM history ORDER BY played_at DESC, id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
		return [
			PlaybackHistory(
				id=r["id"],
				station_name=r["station_name"],
				station_url=r["station_url"],
				station_uuid=r["station_uuid"] or "",
				played_at=_parseDate(r["played_at"]),
				duration_seconds=r["duration_seconds"] or 0,
			)
			for r in rows
		]

	def delete_history_entry(self, history_id: int) -> bool:
		with self._writeLock:
			cur = self.conn.execute("DELETE FROM history WHERE id = ?", (history_id,))
			self.conn.commit()
			return cur.rowcount > 0

	def clear_history(self, older_than_days: int | None = None) -> int:
		"""Borra el historial (o solo lo anterior a ``older_than_days`` días)."""
		with self._writeLock:
			if older_than_days is not None:
				cutoff = (datetime.now() - timedelta(days=older_than_days)).isoformat(timespec="seconds")
				cur = self.conn.execute("DELETE FROM history WHERE played_at < ?", (cutoff,))
			else:
				cur = self.conn.execute("DELETE FROM history")
			self.conn.commit()
			return cur.rowcount

	def get_most_played_stations(self, limit: int = 10) -> list[dict[str, Any]]:
		rows = self.conn.execute(
			"""SELECT station_name, station_url, station_uuid, COUNT(*) AS play_count,
				SUM(duration_seconds) AS total_seconds
			FROM history GROUP BY station_url ORDER BY play_count DESC, total_seconds DESC LIMIT ?""",
			(limit,),
		).fetchall()
		return [
			{"name": r["station_name"], "url": r["station_url"], "uuid": r["station_uuid"], "play_count": r["play_count"], "total_seconds": r["total_seconds"] or 0}
			for r in rows
		]

	def history_totals(self) -> dict[str, int]:
		row = self.conn.execute("SELECT COUNT(*), COALESCE(SUM(duration_seconds), 0), COUNT(DISTINCT station_url) FROM history").fetchone()
		return {"plays": int(row[0]), "seconds": int(row[1]), "stations": int(row[2])}

	# ------------------------------------------------------------- grabaciones programadas
	@staticmethod
	def _scheduled(row: sqlite3.Row) -> ScheduledRecording:
		return ScheduledRecording(
			id=row["id"],
			station_name=row["station_name"],
			station_url=row["station_url"],
			start_time=_parseDate(row["start_time"]) or datetime.now(),
			end_time=_parseDate(row["end_time"]) or datetime.now(),
			output_path=row["output_path"],
			status=row["status"] or "pending",
			error=row["error"] or "",
		)

	def add_scheduled_recording(self, rec: ScheduledRecording) -> int:
		with self._writeLock:
			cur = self.conn.execute(
				"INSERT INTO scheduled_recordings (station_name, station_url, start_time, end_time, output_path, status, error) VALUES (?, ?, ?, ?, ?, ?, ?)",
				(
					rec.station_name,
					rec.station_url,
					rec.start_time.isoformat(timespec="seconds"),
					rec.end_time.isoformat(timespec="seconds"),
					rec.output_path,
					rec.status,
					rec.error,
				),
			)
			self.conn.commit()
			rec.id = cur.lastrowid
			return int(cur.lastrowid)

	def update_scheduled_status(self, rec_id: int, status: str, error: str = "") -> None:
		with self._writeLock:
			self.conn.execute("UPDATE scheduled_recordings SET status = ?, error = ? WHERE id = ?", (status, error, rec_id))
			self.conn.commit()

	def get_scheduled_recordings(self, active_only: bool = True) -> list[ScheduledRecording]:
		query = "SELECT * FROM scheduled_recordings"
		if active_only:
			query += " WHERE status IN ('pending', 'recording')"
		query += " ORDER BY start_time"
		return [self._scheduled(r) for r in self.conn.execute(query).fetchall()]

	def delete_scheduled_recording(self, rec_id: int) -> bool:
		with self._writeLock:
			cur = self.conn.execute("DELETE FROM scheduled_recordings WHERE id = ?", (rec_id,))
			self.conn.commit()
			return cur.rowcount > 0

	def clear_finished_recordings(self) -> int:
		with self._writeLock:
			cur = self.conn.execute("DELETE FROM scheduled_recordings WHERE status NOT IN ('pending', 'recording')")
			self.conn.commit()
			return cur.rowcount

	# ------------------------------------------------------------- cachés
	def cache_countries(self, countries: list[dict[str, Any]]) -> None:
		with self._writeLock:
			c = self.conn
			c.execute("DELETE FROM cache_countries")
			now = _now()
			for country in countries:
				code = country.get("iso_3166_1") or country.get("code") or ""
				if not code:
					continue
				c.execute(
					"INSERT OR REPLACE INTO cache_countries (code, name, name_localized, station_count, updated_at) VALUES (?, ?, ?, ?, ?)",
					(code, country.get("name", ""), country.get("name_localized", ""), int(country.get("stationcount", country.get("station_count", 0)) or 0), now),
				)
			c.commit()

	def get_cached_countries(self) -> list[dict[str, Any]]:
		return [dict(r) for r in self.conn.execute("SELECT * FROM cache_countries ORDER BY name").fetchall()]

	def cache_languages(self, languages: list[dict[str, Any]]) -> None:
		self._cacheNamed("cache_languages", languages)

	def get_cached_languages(self) -> list[dict[str, Any]]:
		return [dict(r) for r in self.conn.execute("SELECT * FROM cache_languages ORDER BY station_count DESC").fetchall()]

	def cache_tags(self, tags: list[dict[str, Any]]) -> None:
		self._cacheNamed("cache_tags", tags)

	def get_cached_tags(self) -> list[dict[str, Any]]:
		return [dict(r) for r in self.conn.execute("SELECT * FROM cache_tags ORDER BY station_count DESC").fetchall()]

	def _cacheNamed(self, table: str, items: list[dict[str, Any]]) -> None:
		with self._writeLock:
			c = self.conn
			c.execute(f"DELETE FROM {table}")
			now = _now()
			for it in items:
				if it.get("name"):
					c.execute(
						f"INSERT OR REPLACE INTO {table} (name, station_count, updated_at) VALUES (?, ?, ?)",
						(it["name"], int(it.get("stationcount", it.get("station_count", 0)) or 0), now),
					)
			c.commit()

	def is_cache_valid(self, table: str, max_age_days: int = 3) -> bool:
		if table not in CACHE_TABLES:
			raise ValueError(table)
		result = self.conn.execute(f"SELECT MAX(updated_at) FROM {table}").fetchone()[0]
		last = _parseDate(result)
		if last is None:
			return False
		return (datetime.now() - last) < timedelta(days=max_age_days)

	def clear_caches(self) -> None:
		with self._writeLock:
			for t in CACHE_TABLES:
				self.conn.execute(f"DELETE FROM {t}")
			self.conn.commit()

	# ------------------------------------------------------------- exportar / importar
	def export_favorites_json(self) -> str:
		"""Favoritos y categorías en JSON (compatible con el complemento original)."""
		categories = self.get_categories()
		names = {c.id: c.name for c in categories}
		data = {
			"version": "1.1",
			"exported_at": _now(),
			"categories": [{"name": c.name, "description": c.description, "color": c.color} for c in categories],
			"favorites": [
				{
					"name": f.name,
					"url": f.url,
					"station_uuid": f.station_uuid,
					"notes": f.notes,
					"category": names.get(f.category_id, ""),
				}
				for f in self.get_favorites()
			],
		}
		return json.dumps(data, indent=2, ensure_ascii=False)

	def import_favorites_json(self, json_data: str) -> tuple[int, int]:
		"""Importa favoritos. Devuelve ``(categorías importadas, favoritos importados)``.

		Las emisoras cuya dirección ya está en favoritos no se duplican.
		"""
		data = json.loads(json_data)
		if not isinstance(data, dict):
			raise ValueError("El archivo no contiene favoritos de zRadio")
		cats = favs = 0
		for cat in data.get("categories", []) or []:
			name = str(cat.get("name", "")).strip()
			if name and not self._category_exists(name):
				self.add_category(Category(name=name, description=cat.get("description", "") or "", color=cat.get("color", "#0078D4") or "#0078D4"))
				cats += 1
		for fav in data.get("favorites", []) or []:
			url = str(fav.get("url", "")).strip()
			name = str(fav.get("name", "")).strip()
			if not url or not name or self.favorite_exists(url):
				continue
			catName = str(fav.get("category", "") or "").strip()
			self.add_favorite(
				Favorite(
					name=name,
					url=url,
					station_uuid=fav.get("station_uuid") or None,
					notes=fav.get("notes", "") or "",
					category_id=self.category_id_by_name(catName) if catName else None,
				)
			)
			favs += 1
		return cats, favs
