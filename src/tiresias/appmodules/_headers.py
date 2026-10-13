"""Títulos de fila y columna definidos por el usuario en tablas de Word y hojas de Excel.

Se guardan en ``data/config/officeHeaders.json`` sin tocar los documentos del
usuario. La clave es el documento (ruta completa) más la tabla (Word) o la
hoja (Excel); el valor indica la fila que contiene los títulos de columna y
la columna que contiene los títulos de fila::

	{"C:\\\\informe.docx|1": {"colHeaderRow": 1, "rowHeaderCol": 1}}
"""

from __future__ import annotations

import json
import os
import threading

from .. import paths
from ..log import getLogger

log = getLogger("officeHeaders")

_lock = threading.Lock()
_data: dict[str, dict[str, int]] | None = None


def _file() -> str:
	return os.path.join(paths.configDir(), "officeHeaders.json")


def _load() -> dict:
	global _data
	if _data is None:
		try:
			with open(_file(), encoding="utf-8") as f:
				raw = json.load(f)
			_data = {str(k): {kk: int(vv) for kk, vv in v.items()} for k, v in raw.items() if isinstance(v, dict)}
		except FileNotFoundError:
			_data = {}
		except Exception:
			log.exception("No se pudieron leer los títulos de tablas")
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
		log.exception("No se pudieron guardar los títulos de tablas")


def makeKey(document: str, part: object) -> str:
	return f"{document}|{part}"


def get(key: str) -> dict[str, int]:
	with _lock:
		return dict(_load().get(key, {}))


def set(key: str, kind: str, value: int | None) -> None:  # noqa: A001 - nombre corto a propósito
	"""``kind``: ``colHeaderRow`` o ``rowHeaderCol``; ``None`` lo borra."""
	with _lock:
		data = _load()
		entry = data.setdefault(key, {})
		if value is None:
			entry.pop(kind, None)
		else:
			entry[kind] = int(value)
		if not entry:
			data.pop(key, None)
		_save()


def reset() -> None:
	"""Olvida la caché (para pruebas)."""
	global _data
	with _lock:
		_data = None
