"""Celdas vigiladas de Excel guardadas por libro.

Se guardan en ``data/config/excelWatched.json`` con la ruta completa del
libro como clave, sin tocar el archivo de Excel::

	{"C:\\\\cuentas.xlsx": [["Resumen", "B12"], ["Datos", "C3"]]}
"""

from __future__ import annotations

import json
import os
import threading

from .. import paths
from ..log import getLogger

log = getLogger("excelWatched")

_lock = threading.Lock()
_data: dict[str, list[list[str]]] | None = None


def _file() -> str:
	return os.path.join(paths.configDir(), "excelWatched.json")


def _load() -> dict:
	global _data
	if _data is None:
		try:
			with open(_file(), encoding="utf-8") as f:
				raw = json.load(f)
			_data = {str(k): [[str(c[0]), str(c[1])] for c in v if isinstance(c, (list, tuple)) and len(c) == 2] for k, v in raw.items() if isinstance(v, list)}
		except FileNotFoundError:
			_data = {}
		except Exception:
			log.exception("No se pudieron leer las celdas vigiladas")
			_data = {}
	return _data


def _save() -> None:
	try:
		os.makedirs(os.path.dirname(_file()), exist_ok=True)
		tmp = _file() + ".tmp"
		with open(tmp, "w", encoding="utf-8") as f:
			json.dump(_data or {}, f, ensure_ascii=False, indent=1)
		os.replace(tmp, _file())
	except Exception:
		log.exception("No se pudieron guardar las celdas vigiladas")


def _key(book: str) -> str:
	return os.path.normcase(book or "")


def cells(book: str) -> list[tuple[str, str]]:
	"""Celdas vigiladas ``(hoja, dirección)`` del libro ``book`` (ruta completa)."""
	with _lock:
		return [tuple(c) for c in _load().get(_key(book), [])]  # type: ignore[misc]


def add(book: str, sheet: str, address: str) -> None:
	with _lock:
		data = _load()
		entry = data.setdefault(_key(book), [])
		if [sheet, address] not in entry:
			entry.append([sheet, address])
		_save()


def remove(book: str, sheet: str, address: str) -> None:
	with _lock:
		data = _load()
		entry = data.get(_key(book), [])
		if [sheet, address] in entry:
			entry.remove([sheet, address])
		if not entry:
			data.pop(_key(book), None)
		_save()


def reset() -> None:
	"""Olvida la caché (para pruebas)."""
	global _data
	with _lock:
		_data = None
