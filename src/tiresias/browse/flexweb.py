"""Web flexible: ajustes del usuario guardados por sitio web.

- **Elementos ocultos**: bloques que el modo exploración no muestra
  (publicidad, menús repetidos...).
- **Inicio de lectura**: elemento en el que se coloca el cursor al cargar
  la página (antes de la lectura continua automática).
- **Orden visual**: lee por columnas según la posición en pantalla (útil en
  PDF sin etiquetar y maquetaciones a varias columnas).
- **Orden de lectura propio** (foros 3.10): operaciones de orden hechas a
  mano o con IA (``readingOrder``), por documento o para todo el sitio
  (``browse/reading_order.py``).

Los elementos se identifican por su tipo de control y su AutomationId (el
``id`` HTML) o, si no tiene, por su nombre o su clase. Se guardan en
``data/config/flexibleWeb.json``.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any
from urllib.parse import urlsplit

from .. import paths
from ..log import getLogger

log = getLogger("flexWeb")

_lock = threading.Lock()
_data: dict[str, dict] | None = None


def _file() -> str:
	return os.path.join(paths.configDir(), "flexibleWeb.json")


def _load() -> dict[str, dict]:
	global _data
	if _data is None:
		try:
			with open(_file(), encoding="utf-8") as f:
				data = json.load(f)
			_data = data if isinstance(data, dict) else {}
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
		log.exception("No se pudieron guardar las reglas de la web flexible")


def siteKey(documentKey: str) -> str:
	"""Sitio de una dirección (``www.ejemplo.com``); para archivos, la carpeta."""
	try:
		u = urlsplit(documentKey)
	except ValueError:
		return documentKey
	if u.netloc:
		return u.netloc.lower()
	if u.scheme == "file":
		return "file:" + os.path.dirname(u.path)
	return documentKey


def describeRule(rule: dict) -> str:
	parts = []
	if rule.get("id"):
		parts.append("#" + rule["id"])
	if rule.get("name"):
		parts.append("«" + rule["name"] + "»")
	if rule.get("cls"):
		parts.append("." + rule["cls"])
	if rule.get("text"):
		parts.append(rule["text"])
	return " ".join(parts) or "?"


def ruleForNode(node: Any) -> dict | None:
	"""Regla que identifica ``node`` o su antecesor identificable más cercano."""
	n = node
	# Nunca el documento entero (el nodo raíz, sin padre): ocultarlo dejaría
	# vacías todas las páginas del sitio.
	while n is not None and n.parent is not None:
		ct = 0
		try:
			from ..a11y import uia_client as uc

			ct = int(n.element.GetCachedPropertyValue(uc.P_CONTROLTYPE) or 0) if n.element is not None else 0
		except Exception:
			ct = 0
		# Solo por clase si se conoce el tipo de control (la regla queda más acotada).
		if n.automationId or (n.name and n.role.name not in ("STATICTEXT",)) or (n.className and ct):
			return {"ct": ct, "id": n.automationId, "name": "" if n.automationId else n.name[:80], "cls": "" if (n.automationId or n.name) else n.className[:60]}
		n = n.parent
	return None


#: Una regla que ocultaría más de esta fracción del texto de la página se rechaza.
MAX_HIDDEN_FRACTION = 0.5


def _nodeControlType(n: Any) -> int:
	try:
		from ..a11y import uia_client as uc

		return int(n.element.GetCachedPropertyValue(uc.P_CONTROLTYPE) or 0) if n.element is not None else 0
	except Exception:
		return 0


def hiddenFraction(rule: dict, buffer: Any) -> float:
	"""Parte del texto de la página que ocultaría ``rule`` (rev. 10.11, M9).

	Las reglas por clase o por nombre valen para todo el sitio: una clase
	genérica («container», «row») podía dejar las páginas vacías.
	"""
	text = getattr(buffer, "text", "") or ""
	if not text:
		return 0.0
	covered = 0
	hiddenIds: set[int] = set()
	for n in buffer.nodes:
		if n.parent is not None and id(n.parent) in hiddenIds:
			hiddenIds.add(id(n))
			continue
		if n.parent is not None and SiteRules._match(rule, n, _nodeControlType(n)):
			hiddenIds.add(id(n))
			covered += max(0, n.end - n.start)
	return covered / len(text)


class SiteRules:
	def __init__(self, site: str, data: dict) -> None:
		self.site = site
		self.hidden: list[dict] = list(data.get("hidden") or [])
		self.start: dict | None = data.get("start") or None
		self.visualOrder: bool = bool(data.get("visualOrder"))

	@staticmethod
	def _match(rule: dict, node: Any, ct: int) -> bool:
		if rule.get("ct") and ct and rule["ct"] != ct:
			return False
		if rule.get("id"):
			return node.automationId == rule["id"]
		if rule.get("name"):
			return node.name == rule["name"]
		if rule.get("cls"):
			return node.className == rule["cls"]
		return False

	def matches(self, node: Any, ct: int) -> bool:
		"""¿El nodo está oculto? (se llama al construir el búfer)."""
		return any(self._match(r, node, ct) for r in self.hidden)

	def findStart(self, nodes: list) -> Any:
		if not self.start:
			return None
		for n in nodes:
			ct = 0
			try:
				from ..a11y import uia_client as uc

				ct = int(n.element.GetCachedPropertyValue(uc.P_CONTROLTYPE) or 0) if n.element is not None else 0
			except Exception:
				pass
			if self._match(self.start, n, ct):
				return n
		return None


def rulesFor(documentKey: str) -> SiteRules:
	site = siteKey(documentKey)
	with _lock:
		data = _load().get(site) or {}
	return SiteRules(site, data)


def _isEmpty(entry: dict) -> bool:
	return not entry.get("hidden") and not entry.get("start") and not entry.get("visualOrder") and not entry.get("readingOrder")


def _update(site: str, func) -> None:
	with _lock:
		data = _load()
		entry = data.setdefault(site, {})
		func(entry)
		if _isEmpty(entry):
			data.pop(site, None)
		_save()


def addHidden(documentKey: str, rule: dict) -> None:
	_update(siteKey(documentKey), lambda e: e.setdefault("hidden", []).append(rule))


def removeHidden(documentKey: str, index: int) -> None:
	def f(e: dict) -> None:
		lst = e.get("hidden") or []
		if 0 <= index < len(lst):
			del lst[index]

	_update(siteKey(documentKey), f)


def setStart(documentKey: str, rule: dict | None) -> None:
	def f(e: dict) -> None:
		if rule:
			e["start"] = rule
		else:
			e.pop("start", None)

	_update(siteKey(documentKey), f)


def setVisualOrder(documentKey: str, value: bool) -> None:
	def f(e: dict) -> None:
		if value:
			e["visualOrder"] = True
		else:
			e.pop("visualOrder", None)

	_update(siteKey(documentKey), f)


def allSites() -> dict[str, dict]:
	with _lock:
		return json.loads(json.dumps(_load()))


def replaceSite(site: str, entry: dict) -> None:
	"""Sustituye todas las reglas de un sitio (desde el diálogo de gestión)."""
	with _lock:
		data = _load()
		if not _isEmpty(entry):
			data[site] = entry
		else:
			data.pop(site, None)
		_save()


# ====================================================================== orden de lectura (foros 3.10)
#: Clave de las operaciones de orden que valen para todo el sitio.
SITE_SCOPE = "*"


def _orderScope(ro: dict, documentKey: str) -> str:
	"""Dónde están (o irán) las operaciones de orden de un documento."""
	if documentKey in ro:
		return documentKey
	if SITE_SCOPE in ro:
		return SITE_SCOPE
	return documentKey


def readingOrderOps(documentKey: str) -> list[dict]:
	"""Operaciones de orden de lectura manual o con IA de un documento."""
	with _lock:
		ro = (_load().get(siteKey(documentKey)) or {}).get("readingOrder") or {}
		return json.loads(json.dumps(ro.get(_orderScope(ro, documentKey)) or []))


def readingOrderScope(documentKey: str) -> str | None:
	"""``document``, ``site`` o ``None`` si no hay orden propio."""
	with _lock:
		ro = (_load().get(siteKey(documentKey)) or {}).get("readingOrder") or {}
	if documentKey in ro:
		return "document"
	if SITE_SCOPE in ro:
		return "site"
	return None


def addReadingOrderOp(documentKey: str, op: dict) -> None:
	def f(e: dict) -> None:
		ro = e.setdefault("readingOrder", {})
		ops = ro.setdefault(_orderScope(ro, documentKey), [])
		ops.append(op)
		del ops[: max(0, len(ops) - 300)]

	_update(siteKey(documentKey), f)


def undoReadingOrder(documentKey: str, everything: bool = False) -> int:
	"""Quita la última operación (o todas). Devuelve cuántas quedan (-1 si no había)."""
	result = [-1]

	def f(e: dict) -> None:
		ro = e.get("readingOrder") or {}
		scope = _orderScope(ro, documentKey)
		ops = ro.get(scope) or []
		if not ops:
			return
		if everything:
			ops.clear()
		else:
			ops.pop()
		result[0] = len(ops)
		if not ops:
			ro.pop(scope, None)
		if not ro:
			e.pop("readingOrder", None)

	_update(siteKey(documentKey), f)
	return result[0]


def toggleReadingOrderScope(documentKey: str) -> str | None:
	"""Pasa el orden de este documento a todo el sitio o al revés. Devuelve el ámbito nuevo."""
	result: list[str | None] = [None]

	def f(e: dict) -> None:
		ro = e.get("readingOrder") or {}
		if documentKey in ro:
			ro[SITE_SCOPE] = ro.pop(documentKey)
			result[0] = "site"
		elif SITE_SCOPE in ro:
			ro[documentKey] = ro.pop(SITE_SCOPE)
			result[0] = "document"
		if ro:
			e["readingOrder"] = ro

	_update(siteKey(documentKey), f)
	return result[0]


def _resetForTests(path: str | None = None) -> None:
	global _data
	_data = None
