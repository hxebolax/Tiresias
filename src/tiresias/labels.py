"""Etiquetas personalizadas para controles sin nombre (o con nombre inútil).

Se guardan por aplicación en ``data/labels/<aplicación>.json`` y se
identifican por el identificador de automatización, la clase y el rol.

La etiqueta sustituye al nombre original allí donde se muestra el control:
voz, braille, revisión de objeto y de pantalla, deletreo del nombre y, en
modo exploración, el texto del documento y la lista de elementos
(:func:`displayName` y :func:`bufferLookup`).
"""

from __future__ import annotations

import json
import os
from typing import Any

from . import paths
from .config import conf
from .log import getLogger

log = getLogger("labels")

_cache: dict[str, dict[str, str]] = {}


def _appName(obj: Any) -> str:
	app = obj.appModule
	return app.appName if app else "global"


def keyFor(automationId: str, className: str, role: int, name: str, size: tuple[int, int] | None) -> str | None:
	"""Clave de un control a partir de sus datos (la misma para objetos y nodos del modo exploración)."""
	if automationId:
		return f"id:{automationId}|{int(role)}"
	if name:
		return f"name:{name}|{className}|{int(role)}"
	if size:
		# Sin identificador: tamaño del control (último recurso).
		return f"pos:{className}|{int(role)}|{size[0]}x{size[1]}"
	return None


def _key(obj: Any) -> str | None:
	aid = getattr(obj, "UIAAutomationId", "") or ""
	cls = getattr(obj, "UIAClassName", "") or obj.windowClassName or ""
	role = int(obj.role)
	if aid:
		return keyFor(aid, cls, role, "", None)
	name = obj.name or ""
	if name:
		return keyFor("", cls, role, name, None)
	loc = obj.location
	return keyFor("", cls, role, "", (loc[2], loc[3]) if loc else None)


def _file(app: str) -> str:
	return os.path.join(paths.labelsDir(), f"{app}.json")


def _load(app: str) -> dict[str, str]:
	if app not in _cache:
		try:
			with open(_file(app), encoding="utf-8") as f:
				_cache[app] = dict(json.load(f))
		except FileNotFoundError:
			_cache[app] = {}
		except (OSError, ValueError):
			log.exception("Etiquetas no válidas para %s", app)
			_cache[app] = {}
	return _cache[app]


def getLabel(obj: Any) -> str | None:
	if not conf["labels"]["enabled"]:
		return None
	try:
		data = _load(_appName(obj))
	except Exception:
		return None
	if not data:
		# Sin etiquetas en esta aplicación: no hace falta consultar el control.
		return None
	try:
		key = _key(obj)
	except Exception:
		return None
	if not key:
		return None
	return data.get(key)


def displayName(obj: Any, name: str | None = None) -> str:
	"""Nombre que se muestra del objeto: su etiqueta personalizada o su nombre.

	Lo usan la voz, el braille, la revisión y las listas, para que la etiqueta
	sustituya al nombre original en todas partes. ``name``: nombre ya leído
	(para no volver a pedirlo).
	"""
	label = getLabel(obj)
	if label:
		return label
	if name is not None:
		return name
	try:
		return obj.name or ""
	except Exception:
		return ""


def bufferLookup(appName: str, fallbackClass: str = ""):
	"""Función ``nodo -> etiqueta`` para el búfer del modo exploración, o ``None``.

	Los nodos del búfer no son objetos: se reconocen con los mismos datos que
	los controles (identificador, clase, rol, nombre y tamaño). En las páginas
	web la clase de los objetos suele ser la de la ventana del navegador
	(``fallbackClass``), así que se prueban las dos.
	"""
	if not conf["labels"]["enabled"]:
		return None
	app = appName or "global"

	def lookup(node: Any) -> str | None:
		data = _load(app)
		if not data:
			return None
		aid = getattr(node, "automationId", "") or ""
		role = int(getattr(node, "role", 0) or 0)
		name = getattr(node, "name", "") or ""
		loc = getattr(node, "location", None)
		size = (loc[2], loc[3]) if loc and len(loc) >= 4 else None
		classes = [getattr(node, "className", "") or ""]
		if fallbackClass and fallbackClass not in classes:
			classes.append(fallbackClass)
		for cls in classes:
			key = keyFor(aid, cls, role, "" if aid else name, None if (aid or name) else size)
			if key and key in data:
				return data[key]
		return None

	return lookup


def setLabel(obj: Any, label: str | None) -> bool:
	key = _key(obj)
	if not key:
		return False
	app = _appName(obj)
	data = _load(app)
	if label:
		data[key] = label
	else:
		data.pop(key, None)
	# Escritura segura (archivo temporal y sustitución), como el gestor de etiquetas.
	_save(app, data)
	_refreshDocument(obj)
	return True


def _refreshDocument(obj: Any) -> None:
	"""Vuelve a cargar el documento en modo exploración del objeto (si lo tiene),
	para que la etiqueta nueva aparezca en su texto y en la lista de elementos."""
	try:
		ti = getattr(obj, "treeInterceptor", None)
		rebuild = getattr(ti, "requestRebuild", None) if ti is not None else None
		if rebuild is not None:
			rebuild()
	except Exception:
		log.debug("No se pudo actualizar el documento", exc_info=True)


# ====================================================================== gestor de etiquetas
def _save(app: str, data: dict[str, str]) -> None:
	os.makedirs(paths.labelsDir(), exist_ok=True)
	path = _file(app)
	if not data:
		_cache[app] = {}
		try:
			os.remove(path)
		except OSError:
			pass
		return
	tmp = path + ".tmp"
	with open(tmp, "w", encoding="utf-8") as f:
		json.dump(data, f, ensure_ascii=False, indent="\t", sort_keys=True)
	os.replace(tmp, path)
	_cache[app] = dict(data)


def listApps() -> list[str]:
	"""Aplicaciones con etiquetas guardadas."""
	try:
		names = [fn[:-5] for fn in os.listdir(paths.labelsDir()) if fn.lower().endswith(".json")]
	except OSError:
		names = []
	return sorted((n for n in names if _load(n)), key=str.lower)


def getAll(app: str) -> dict[str, str]:
	return dict(_load(app))


def describeKey(key: str) -> str:
	"""Texto legible del identificador de un control."""
	from .i18n import _

	kind, _sep, rest = key.partition(":")
	parts = rest.split("|")
	if kind == "id":
		return _("identificador {id}").format(id=parts[0])
	if kind == "name":
		return _("nombre original «{name}»").format(name=parts[0])
	if kind == "pos":
		return _("control sin nombre ({cls}, {size})").format(cls=parts[0] or "?", size=parts[-1])
	return key


def setLabelByKey(app: str, key: str, label: str | None) -> None:
	data = _load(app)
	if label:
		data[key] = label
	else:
		data.pop(key, None)
	_save(app, data)


def deleteApp(app: str) -> None:
	_save(app, {})


EXPORT_FORMAT = "tiresias-etiquetas"


def exportLabels(fileName: str, apps: list[str] | None = None) -> int:
	"""Exporta las etiquetas (de todas las aplicaciones o de las indicadas)."""
	apps = listApps() if apps is None else apps
	data = {app: getAll(app) for app in apps if getAll(app)}
	with open(fileName, "w", encoding="utf-8") as f:
		json.dump({"format": EXPORT_FORMAT, "version": 1, "labels": data}, f, ensure_ascii=False, indent="\t", sort_keys=True)
	return sum(len(v) for v in data.values())


def importLabels(fileName: str, replace: bool = False) -> int:
	"""Importa etiquetas. ``replace``: sustituye las de las aplicaciones importadas."""
	with open(fileName, encoding="utf-8-sig") as f:
		data = json.load(f)
	if not isinstance(data, dict) or data.get("format") != EXPORT_FORMAT or not isinstance(data.get("labels"), dict):
		raise ValueError("El archivo no es una exportación de etiquetas de Tiresias")
	count = 0
	for app, labels in data["labels"].items():
		if not isinstance(labels, dict) or not app or any(c in app for c in '\\/:*?"<>|'):
			continue
		current = {} if replace else _load(str(app))
		for k, v in labels.items():
			if isinstance(k, str) and isinstance(v, str) and v:
				current[k] = v
				count += 1
		_save(str(app), current)
	return count
