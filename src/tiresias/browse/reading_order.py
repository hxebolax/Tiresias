"""Orden de lectura a mano o con IA (foros 3.10: PDF y páginas desordenadas).

El orden se guarda en las reglas de la web flexible (``flexweb``) como una
lista de operaciones por documento (o para todo el sitio). Cada operación
fija el orden de los hijos de un contenedor::

	{"container": clave, "order": [claves de los hijos], "desc": "texto"}

Al construir el búfer, los hijos de ese contenedor se recorren en ese orden
(manda la última operación de cada contenedor) y los que no estén en la
lista se quedan detrás del hijo que los precedía. Deshacer quita la última
operación; borrar la lista devuelve el orden original.

Las claves no dependen de la posición en pantalla: tipo de control más el
identificador de automatización o, si no tiene, el principio de su texto,
con un número de repetición si dos hermanos coinciden. Se calculan siempre
sobre el orden original de los hijos (el de la caché UIA), así que son las
mismas al construir el búfer y al dar la orden.
"""

from __future__ import annotations

from typing import Any

from ..a11y import uia_client as uc
from .buffer import Node, VirtualBuffer, _cached

#: Clave del contenedor raíz del documento.
ROOT_KEY = "@raiz"
#: Caracteres de texto que identifican un elemento sin identificador.
KEY_TEXT_LEN = 48
#: Máximo de operaciones guardadas por documento.
MAX_OPS = 300


def elementText(el: Any, limit: int = KEY_TEXT_LEN) -> str:
	"""Principio del texto de un elemento: su nombre o el de sus descendientes."""
	own = " ".join(str(_cached(el, uc.P_NAME, "") or "").split())
	if own:
		return own[:limit]
	parts: list[str] = []
	total = 0
	stack = [el]
	visited = 0
	while stack and visited < 80 and total < limit:
		e = stack.pop()
		visited += 1
		if e is not el:
			name = " ".join(str(_cached(e, uc.P_NAME, "") or "").split())
			if name:
				parts.append(name)
				total += len(name) + 1
				# El nombre de un elemento ya resume a sus hijos.
				continue
		try:
			kids = e.GetCachedChildren()
			n = kids.Length if kids else 0
		except Exception:
			n = 0
		for i in range(n - 1, -1, -1):
			try:
				stack.append(kids.GetElement(i))
			except Exception:
				pass
	return " ".join(parts)[:limit]


def elementKey(el: Any) -> str:
	ct = int(_cached(el, uc.P_CONTROLTYPE, 0) or 0)
	aid = str(_cached(el, uc.P_AUTOMATIONID, "") or "")
	if aid:
		return f"{ct}#{aid}"
	return f"{ct}:{elementText(el)}"


def keysFor(elements: list) -> list[str]:
	"""Claves de una lista de hermanos (con número de repetición)."""
	seen: dict[str, int] = {}
	out = []
	for el in elements:
		k = elementKey(el)
		n = seen.get(k, 0)
		seen[k] = n + 1
		out.append(k if n == 0 else f"{k}~{n}")
	return out


def applyOrder(items: list, keys: list[str], order: list[str]) -> list:
	"""Reordena ``items`` (con sus ``keys``) según ``order``.

	Los que no están en ``order`` van detrás del elemento que los precedía en
	el orden original (o al principio si no había ninguno).
	"""
	pos = {k: i for i, k in enumerate(order)}
	listed = sorted(((pos[k], i) for i, k in enumerate(keys) if k in pos))
	out = [items[i] for _p, i in listed]
	outIdx = [i for _p, i in listed]
	anchor: int | None = None
	lastAfter: dict[int | None, int | None] = {}
	for i, k in enumerate(keys):
		if k in pos:
			anchor = i
			continue
		ref = lastAfter.get(anchor, anchor)
		at = 0 if ref is None else outIdx.index(ref) + 1
		out.insert(at, items[i])
		outIdx.insert(at, i)
		lastAfter[anchor] = i
	return out


class ReadingOrder:
	"""Operaciones de orden de un documento, listas para aplicar al construir el búfer."""

	def __init__(self, ops: list[dict]) -> None:
		self.byContainer: dict[str, list[str]] = {}
		for op in ops or []:
			if isinstance(op, dict) and isinstance(op.get("container"), str) and isinstance(op.get("order"), list):
				self.byContainer[op["container"]] = [str(k) for k in op["order"]]
		#: Tipos de control de los contenedores identificados por su texto: solo
		#: para ellos se calcula el texto (rev. 10.11, M10: se recorrían hasta 80
		#: descendientes de cada contenedor de la página en cada construcción).
		self._textCts: set[int] = set()
		for key in self.byContainer:
			head, sep, _rest = key.partition(":")
			if sep and head.isdigit() and "#" not in head:
				self._textCts.add(int(head))

	def __bool__(self) -> bool:
		return bool(self.byContainer)

	def _containerKey(self, el: Any) -> str | None:
		ct = int(_cached(el, uc.P_CONTROLTYPE, 0) or 0)
		aid = str(_cached(el, uc.P_AUTOMATIONID, "") or "")
		if aid:
			return f"{ct}#{aid}"
		if ct not in self._textCts:
			return None
		return f"{ct}:{elementText(el)}"

	def reorder(self, el: Any, kids: list, isRoot: bool) -> list | None:
		"""Nuevo orden de ``kids`` (hijos de ``el``) o ``None`` si no hay regla."""
		if not self.byContainer or len(kids) < 2:
			return None
		key = ROOT_KEY if isRoot else self._containerKey(el)
		if key is None:
			return None
		order = self.byContainer.get(key)
		if order is None:
			return None
		return applyOrder(kids, keysFor(kids), order)


# ====================================================================== órdenes
def containerKey(buf: VirtualBuffer, node: Node) -> str | None:
	if node is buf.root and node.parent is None:
		return ROOT_KEY
	if node.element is None:
		return None
	return elementKey(node.element)


def childKeys(node: Node) -> dict[tuple, str]:
	"""RuntimeId -> clave de cada hijo (sobre el orden original de la caché)."""
	try:
		kids = node.element.GetCachedChildren()
		elements = [kids.GetElement(i) for i in range(kids.Length if kids else 0)]
	except Exception:
		return {}
	out: dict[tuple, str] = {}
	for el, key in zip(elements, keysFor(elements), strict=False):
		rid = _cached(el, uc.P_RUNTIMEID, None)
		if rid:
			out[tuple(rid)] = key
	return out


def currentOrder(node: Node) -> list[str]:
	"""Claves de los hijos de ``node`` en el orden en que se leen ahora."""
	keys = childKeys(node)
	return [keys[c.rid] for c in node.children if c.rid in keys]


def splitAtCommonAncestor(a: Node, b: Node) -> tuple[Node, Node, Node] | None:
	"""(antecesor común, hijo que contiene ``a``, hijo que contiene ``b``)."""
	chainA = [a] + list(a.ancestors())
	where = {id(n): i for i, n in enumerate(chainA)}
	prev = None
	n: Node | None = b
	while n is not None:
		if id(n) in where:
			i = where[id(n)]
			if i == 0 or prev is None:
				# Uno contiene al otro: no se pueden intercambiar.
				return None
			return n, chainA[i - 1], prev
		prev = n
		n = n.parent
	return None


def blockText(buf: VirtualBuffer, node: Node, limit: int = 60) -> str:
	return " ".join(buf.text[node.start : node.end].split())[:limit]


def planMove(buf: VirtualBuffer, moving: Node, target: Node, after: bool) -> dict | None:
	"""Operación que coloca ``moving`` antes o después de ``target``.

	Si están en contenedores distintos, se mueve el bloque que contiene a
	``moving`` dentro del antecesor común de los dos.
	"""
	split = splitAtCommonAncestor(moving, target)
	if split is None:
		return None
	parent, a, b = split
	ck = containerKey(buf, parent)
	if ck is None:
		return None
	keys = childKeys(parent)
	ka, kb = keys.get(a.rid), keys.get(b.rid)
	if not ka or not kb or ka == kb:
		return None
	order = [k for k in currentOrder(parent) if k != ka]
	if kb not in order:
		return None
	i = order.index(kb)
	order.insert(i + 1 if after else i, ka)
	return {"container": ck, "order": order, "desc": blockText(buf, a)}


def planOrder(buf: VirtualBuffer, parent: Node, children: list[Node]) -> dict | None:
	"""Operación que fija el orden de ``children`` (hijos de ``parent``)."""
	ck = containerKey(buf, parent)
	if ck is None:
		return None
	keys = childKeys(parent)
	order = [keys[c.rid] for c in children if c.rid in keys]
	if len(order) < 2:
		return None
	return {"container": ck, "order": order, "desc": blockText(buf, parent)}
