"""Etiquetas y textos alternativos generados con IA para el modo exploración.

Los usan el etiquetado automático (foros 6.3, NVDA #17332) y el texto
alternativo de las imágenes de los PDF (foros 3.10). Se guardan en
``data/config/aiLabels.json`` como ``{ámbito: {huella: texto}}``:

- el ámbito de una imagen es la dirección del documento (sus imágenes son
  suyas); el de un botón o un enlace es el sitio, porque suele repetirse en
  todas sus páginas;
- la huella identifica el elemento sin depender del desplazamiento de la
  página: tipo, identificador de automatización o, si no tiene, destino del
  enlace, tamaño, nombre del contenedor con nombre más cercano y cuántos
  hermanos iguales le preceden.

Al construir el búfer (``VirtualBuffer.aiLabels``), los elementos sin nombre
que tengan texto guardado lo usan como nombre.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from .. import paths
from ..log import getLogger
from ..objects.roles import Role

log = getLogger("aiLabels")

#: Elementos que se pueden etiquetar (sin nombre).
LABEL_ROLES = {
	Role.GRAPHIC,
	Role.BUTTON,
	Role.TOGGLEBUTTON,
	Role.SPLITBUTTON,
	Role.MENUBUTTON,
	Role.LINK,
	Role.MENUITEM,
	Role.TAB,
}
#: Máximo de textos por ámbito.
MAX_PER_SCOPE = 3000

_lock = threading.Lock()
_data: dict[str, dict[str, str]] | None = None


def _file() -> str:
	return os.path.join(paths.configDir(), "aiLabels.json")


def _load() -> dict[str, dict[str, str]]:
	global _data
	if _data is None:
		try:
			with open(_file(), encoding="utf-8") as f:
				data = json.load(f)
			_data = {str(k): dict(v) for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}
		except (OSError, ValueError):
			_data = {}
	return _data


def _save() -> None:
	try:
		os.makedirs(os.path.dirname(_file()), exist_ok=True)
		tmp = _file() + ".tmp"
		with open(tmp, "w", encoding="utf-8") as f:
			json.dump(_data or {}, f, ensure_ascii=False, indent=1)
		os.replace(tmp, _file())
	except OSError:
		log.exception("No se pudieron guardar las etiquetas de IA")


def _resetForTests() -> None:
	global _data
	_data = None


def _size(node: Any) -> tuple[int, int]:
	loc = getattr(node, "location", None)
	return (int(loc[2]), int(loc[3])) if loc else (0, 0)


def fingerprint(node: Any) -> str:
	"""Huella estable de un elemento del búfer (ver el docstring del módulo)."""
	role = int(node.role)
	if node.automationId:
		return f"{role}|id:{node.automationId}"
	url = node.url if node.role == Role.LINK else ""
	anc = ""
	for a in node.ancestors():
		if a.role == Role.LINK:
			url = url or a.url
			continue
		if a.name:
			anc = a.name[:40]
			break
	w, h = _size(node)
	k = 0
	parent = node.parent
	if parent is not None:
		sibs = parent.children
		idx = next((i for i, c in enumerate(sibs) if c is node), len(sibs))
		k = sum(1 for c in sibs[:idx] if c.role == node.role and _size(c) == (w, h))
	return f"{role}|{url}|{w}x{h}|{anc}|{k}"


def scopeFor(documentKey: str, node: Any) -> str:
	from ..browse import flexweb

	return documentKey if node.role == Role.GRAPHIC else flexweb.siteKey(documentKey)


class Lookup:
	"""Textos de un documento (los del documento tapan a los del sitio)."""

	def __init__(self, entries: dict[str, str]) -> None:
		self.entries = entries

	def get(self, node: Any) -> str | None:
		if node.role not in LABEL_ROLES or node.name:
			return None
		try:
			return self.entries.get(fingerprint(node))
		except Exception:
			return None


def lookupFor(documentKey: str) -> Lookup | None:
	from ..browse import flexweb

	with _lock:
		data = _load()
		entries = dict(data.get(flexweb.siteKey(documentKey)) or {})
		entries.update(data.get(documentKey) or {})
	return Lookup(entries) if entries else None


def get(documentKey: str, node: Any) -> str | None:
	lk = lookupFor(documentKey)
	return lk.get(node) if lk is not None else None


def setText(documentKey: str, fp: str, text: str, scope: str) -> None:
	"""Guarda ``text`` para la huella ``fp`` en ``scope`` (vacío: lo borra)."""
	with _lock:
		data = _load()
		entry = data.setdefault(scope, {})
		if text:
			entry[fp] = text
			while len(entry) > MAX_PER_SCOPE:
				entry.pop(next(iter(entry)))
		else:
			entry.pop(fp, None)
		if not entry:
			data.pop(scope, None)
		_save()


def setLabel(documentKey: str, node: Any, text: str) -> str:
	"""Guarda el texto de ``node``; devuelve su huella."""
	fp = fingerprint(node)
	setText(documentKey, fp, text, scopeFor(documentKey, node))
	return fp


def scopesForSite(site: str) -> dict[str, int]:
	"""Ámbitos (documentos o el sitio) de un sitio con cuántos textos tiene cada uno."""
	from ..browse import flexweb

	with _lock:
		return {scope: len(v) for scope, v in _load().items() if scope == site or flexweb.siteKey(scope) == site}


def allScopes() -> list[str]:
	with _lock:
		return list(_load())


def removeScope(scope: str) -> None:
	with _lock:
		if _load().pop(scope, None) is not None:
			_save()
