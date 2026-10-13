"""Navegación por la estructura de una fórmula (sin dependencias de la interfaz).

La fórmula se recorre como un árbol: izquierda y derecha se mueven entre
hermanos, abajo entra en el primer hijo y arriba sale al padre. Algunos
``mrow`` son «transparentes» (el contenido de una raíz, de un paréntesis o de
una celda): no se detiene en ellos, se pasa directamente a sus términos.
"""

from __future__ import annotations

from .mathml import INVISIBLE_OPERATORS, MathNode, mathContent
from .speech_es import BIG_OPERATORS, FUNCTIONS, SpeechGenerator, SpeechOptions, nodeText, realChildren

_TRANSPARENT_PARENTS = frozenset({"msqrt", "menclose", "mtd", "merror"})


def isTransparent(node: MathNode) -> bool:
	if node.tag != "mrow" or node.isFenced:
		return False
	p = node.parent
	if p is None:
		return False
	if p.tag in _TRANSPARENT_PARENTS:
		return True
	return p.isFenced and p.fenceContent is node


def navChildren(node: MathNode) -> list[MathNode]:
	"""Hijos navegables de un nodo."""
	tag = node.tag
	if node.isToken:
		return []
	if node.isFenced:
		content = node.fenceContent
		if content is None:
			return []
		if content.tag == "mtable":
			return navChildren(content)
		if isTransparent(content):
			return navChildren(content)
		return [content]
	if tag in ("mrow", "math"):
		out: list[MathNode] = []
		for c in node.children:
			if c.tag == "mo" and c.text in INVISIBLE_OPERATORS or c.tag == "mspace":
				continue
			if isTransparent(c):
				out.extend(navChildren(c))
			else:
				out.append(c)
		return out
	if tag in ("msqrt", "menclose", "merror", "mtd"):
		kids = node.children
		if len(kids) == 1 and isTransparent(kids[0]):
			return navChildren(kids[0])
		return [k for k in kids if not (k.tag == "mo" and k.text in INVISIBLE_OPERATORS)]
	if tag == "mtable":
		return [r for r in node.children if r.tag in ("mtr", "mlabeledtr")]
	if tag in ("mtr", "mlabeledtr"):
		return [c for c in node.children if c.tag == "mtd"]
	if tag == "mmultiscripts":
		return [c for c in node.children if c.tag not in ("none", "mprescripts")]
	return list(node.children)


def navParent(node: MathNode, top: MathNode) -> MathNode | None:
	if node is top:
		return None
	p = node.parent
	while p is not None and p is not top and (isTransparent(p) or (p.tag == "mtable" and p.parent is not None and p.parent.isFenced)):
		p = p.parent
	if p is None or p.tag == "math":
		return None
	return p


# ---------------------------------------------------------------- etiquetas
def childLabel(node: MathNode, parent: MathNode | None) -> str:
	"""Papel del nodo dentro de su padre lógico («numerador», «exponente»...)."""
	if parent is None:
		return ""
	kids = navChildren(parent)
	try:
		i = next(k for k, c in enumerate(kids) if c is node)
	except StopIteration:
		return ""
	tag = parent.tag
	base = parent.children[0] if parent.children else None
	big = base is not None and base.tag in ("mo", "mi") and base.text in BIG_OPERATORS
	limitFn = base is not None and base.tag == "mi" and base.text in FUNCTIONS
	if tag == "mfrac":
		return ("numerador", "denominador")[i] if i < 2 else ""
	if tag == "mroot":
		return ("radicando", "índice")[i] if i < 2 else ""
	if tag == "msup":
		return ("base", "exponente")[i] if i < 2 else ""
	if tag == "msub":
		if big or limitFn:
			return ("operador", "límite inferior")[i] if i < 2 else ""
		return ("base", "subíndice")[i] if i < 2 else ""
	if tag == "msubsup":
		if big:
			return ("operador", "límite inferior", "límite superior")[i] if i < 3 else ""
		return ("base", "subíndice", "superíndice")[i] if i < 3 else ""
	if tag == "munder":
		if big or limitFn:
			return ("operador", "límite inferior" if big else "condición")[i] if i < 2 else ""
		return ("base", "debajo")[i] if i < 2 else ""
	if tag == "mover":
		if big:
			return ("operador", "límite superior")[i] if i < 2 else ""
		return ("base", "encima")[i] if i < 2 else ""
	if tag == "munderover":
		if big:
			return ("operador", "límite inferior", "límite superior")[i] if i < 3 else ""
		return ("base", "debajo", "encima")[i] if i < 3 else ""
	if tag == "mtable" or (parent.isFenced and parent.fenceContent is not None and parent.fenceContent.tag == "mtable"):
		return f"fila {i + 1}"
	if tag in ("mtr", "mlabeledtr"):
		return f"columna {i + 1}"
	return ""


def structureName(node: MathNode) -> str:
	"""Nombre de la estructura («fracción», «raíz cuadrada»...)."""
	tag = node.tag
	if node.isFenced:
		content = node.fenceContent
		o, c = node.get("_open"), node.get("_close")
		if content is not None and content.tag == "mtable":
			rows = [r for r in content.children if r.tag in ("mtr", "mlabeledtr")]
			cols = max((len([x for x in r.children if x.tag == "mtd"]) for r in rows), default=0)
			kind = "determinante" if o in ("|", "∣") else "matriz"
			return f"{kind} de {len(rows)} por {cols}"
		if o in ("|", "∣") and c in ("|", "∣"):
			return "valor absoluto"
		if o in ("‖", "∥"):
			return "norma"
		if o == "{" and c == "}":
			return "conjunto"
		return {"(": "paréntesis", "[": "corchetes", "{": "llaves", "⟨": "ángulos"}.get(o, "delimitadores")
	if tag == "mfrac":
		return "número combinatorio" if node.get("linethickness") == "0" else "fracción"
	if tag == "msqrt":
		return "raíz cuadrada"
	if tag == "mroot":
		return "raíz"
	base = node.children[0] if node.children else None
	big = base is not None and base.tag in ("mo", "mi") and base.text in BIG_OPERATORS
	if big and tag in ("msub", "msubsup", "munder", "mover", "munderover"):
		from .speech_es import OPERATORS

		return OPERATORS.get(base.text, "operador")
	if base is not None and base.tag == "mi" and base.text.startswith("lim") and tag in ("munder", "msub"):
		return "límite"
	if tag == "msup":
		return "potencia"
	if tag == "msub":
		return "subíndice"
	if tag == "msubsup":
		return "subíndice y superíndice"
	if tag in ("munder", "mover", "munderover"):
		return "expresión con límites" if tag == "munderover" else ("expresión con algo debajo" if tag == "munder" else "expresión con algo encima")
	if tag == "mtable":
		rows = [r for r in node.children if r.tag in ("mtr", "mlabeledtr")]
		return f"tabla de {len(rows)} filas"
	if tag in ("mtr", "mlabeledtr"):
		return "fila"
	if tag == "mtd":
		return "celda"
	if tag == "menclose":
		return "recuadro"
	if tag == "mmultiscripts":
		return "índices múltiples"
	if tag == "mrow":
		n = len(navChildren(node))
		return f"expresión de {n} elementos" if n != 1 else "expresión"
	if tag == "mi":
		return "identificador"
	if tag == "mn":
		return "número"
	if tag == "mo":
		return "operador"
	if tag == "mtext":
		return "texto"
	return tag


def _articled(name: str) -> str:
	fem = ("fracción", "raíz", "potencia", "expresión", "matriz", "norma", "fila", "celda", "tabla")
	if name.startswith(fem):
		return "la " + name
	return "el " + name


class MathNavigator:
	"""Cursor sobre el árbol de una fórmula."""

	def __init__(self, root: MathNode) -> None:
		self.root = root
		content = mathContent(root)
		self.top: MathNode = content if content is not None else root
		self.current: MathNode = self.top
		self._history: list[MathNode] = []

	# ---------------------------------------------------------- movimientos
	def _go(self, node: MathNode | None) -> bool:
		if node is None or node is self.current:
			return False
		self._history.append(self.current)
		if len(self._history) > 100:
			del self._history[0]
		self.current = node
		return True

	def parent(self) -> MathNode | None:
		return navParent(self.current, self.top)

	def siblings(self) -> list[MathNode]:
		p = self.parent()
		if p is None:
			return [self.current]
		return navChildren(p)

	def _siblingIndex(self) -> int:
		sibs = self.siblings()
		for i, s in enumerate(sibs):
			if s is self.current:
				return i
		return 0

	def peekNext(self) -> MathNode | None:
		sibs = self.siblings()
		i = self._siblingIndex()
		return sibs[i + 1] if i + 1 < len(sibs) else None

	def peekPrevious(self) -> MathNode | None:
		sibs = self.siblings()
		i = self._siblingIndex()
		return sibs[i - 1] if i > 0 else None

	def moveNext(self) -> bool:
		return self._go(self.peekNext())

	def movePrevious(self) -> bool:
		return self._go(self.peekPrevious())

	def moveFirst(self) -> bool:
		sibs = self.siblings()
		return self._go(sibs[0]) if sibs else False

	def moveLast(self) -> bool:
		sibs = self.siblings()
		return self._go(sibs[-1]) if sibs else False

	def moveDown(self) -> bool:
		kids = navChildren(self.current)
		return self._go(kids[0]) if kids else False

	def moveUp(self) -> bool:
		return self._go(self.parent())

	def moveTop(self) -> bool:
		return self._go(self.top)

	def moveBack(self) -> bool:
		while self._history:
			node = self._history.pop()
			if node is not self.current:
				self.current = node
				return True
		return False

	def moveTo(self, node: MathNode) -> bool:
		return self._go(node)

	# ---------------------------------------------------------- tablas
	def currentCell(self) -> MathNode | None:
		n: MathNode | None = self.current
		while n is not None:
			if n.tag == "mtd":
				return n
			n = n.parent
		return None

	def cellPosition(self) -> tuple[int, int] | None:
		cell = self.currentCell()
		if cell is None or cell.parent is None:
			return None
		row = cell.parent
		table = row.parent
		if table is None:
			return None
		rows = [r for r in table.children if r.tag in ("mtr", "mlabeledtr")]
		cells = [c for c in row.children if c.tag == "mtd"]
		return rows.index(row) + 1, cells.index(cell) + 1

	def moveCell(self, dRow: int, dCol: int) -> bool:
		cell = self.currentCell()
		if cell is None or cell.parent is None or cell.parent.parent is None:
			return False
		row = cell.parent
		table = row.parent
		rows = [r for r in table.children if r.tag in ("mtr", "mlabeledtr")]
		r = rows.index(row) + dRow
		cells = [c for c in row.children if c.tag == "mtd"]
		c = cells.index(cell) + dCol
		if not (0 <= r < len(rows)):
			return False
		targetCells = [x for x in rows[r].children if x.tag == "mtd"]
		if not (0 <= c < len(targetCells)):
			return False
		return self._go(targetCells[c])

	# ---------------------------------------------------------- descripción
	def label(self, node: MathNode | None = None) -> str:
		node = node or self.current
		return childLabel(node, navParent(node, self.top))

	def whereAmI(self) -> str:
		"""Posición del cursor: «numerador de la fracción, dentro de la raíz cuadrada»."""
		parts: list[str] = []
		node = self.current
		parent = navParent(node, self.top)
		if parent is None:
			return "en la fórmula completa"
		while parent is not None:
			label = childLabel(node, parent)
			name = _articled(structureName(parent))
			if label:
				parts.append(f"{label} de {name}")
			elif parent is not self.top and not (parent.tag == "mrow" and not parent.isFenced):
				parts.append(f"dentro de {name}")
			node = parent
			parent = navParent(node, self.top)
		if not parts:
			idx = self._siblingIndex() + 1
			return f"elemento {idx} de {len(self.siblings())} de la fórmula"
		return ", ".join(parts)

	def describe(self, node: MathNode | None = None, options: SpeechOptions | None = None) -> str:
		"""Resumen de la estructura del nodo actual."""
		node = node or self.current
		name = structureName(node)
		if node.isToken:
			return f"{name}: {nodeText(node, options, pauses=False)}"
		kids = navChildren(node)
		parts = [name]
		if node.tag in ("mfrac", "msup", "msub", "msubsup", "mroot", "munder", "mover", "munderover") or node.isFenced:
			labels = [childLabel(k, node) for k in kids]
			details = []
			for k, lab in zip(kids, labels, strict=False):
				txt = nodeText(k, options, pauses=False)
				if len(txt) > 60:
					txt = structureName(k)
				details.append(f"{lab} {txt}".strip())
			if details:
				parts.append("; ".join(details))
		elif node.tag in ("mrow", "math"):
			parts.append(f"{len(kids)} elementos")
		return ", ".join(parts)

	def speechFor(self, node: MathNode | None = None, options: SpeechOptions | None = None, withLabel: bool = False) -> list:
		node = node or self.current
		seq = SpeechGenerator(options).speak(node)
		from .speech_es import _pauseAfterEndMarkers

		seq = _pauseAfterEndMarkers(seq)
		if withLabel:
			lab = self.label(node)
			if lab:
				seq = [lab] + seq
		if not seq:
			seq = [structureName(node)]
		return seq


def leafCount(node: MathNode) -> int:
	return sum(1 for n in node.iter() if n.isToken and not (n.tag == "mo" and n.text in INVISIBLE_OPERATORS))


__all__ = ["MathNavigator", "navChildren", "navParent", "childLabel", "structureName", "realChildren"]
