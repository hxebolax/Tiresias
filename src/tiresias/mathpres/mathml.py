"""Árbol MathML de Tiresias: análisis tolerante y normalización.

El análisis usa ``html.parser`` (no XML estricto) para aceptar el MathML que
devuelven los navegadores (``innerHTML``), con entidades HTML, prefijos de
espacio de nombres (``m:mi``) o etiquetas mal cerradas.

Tras el análisis, :func:`normalize` deja el árbol en una forma canónica que
usan la voz, el braille y la navegación:

- se eliminan los envoltorios sin significado (``mstyle``, ``mpadded``,
  ``semantics``, ``maction``...) y ``mphantom``;
- ``mfenced`` se convierte en ``mrow`` con sus delimitadores;
- el MathML de contenido básico se convierte en MathML de presentación;
- los elementos con varios hijos donde se espera uno reciben un ``mrow``;
- en cada ``mrow`` se agrupan los paréntesis, corchetes, llaves y barras en
  grupos «delimitados» (``mrow`` con los atributos internos ``_open`` y
  ``_close``) para poder leerlos como una unidad y navegar por ellos.
"""

from __future__ import annotations

import html
import re
import unicodedata
from html.parser import HTMLParser
from typing import Iterator

TOKEN_TAGS = frozenset({"mi", "mn", "mo", "mtext", "ms", "mspace", "mglyph"})
#: Elementos que admiten un único hijo (si tienen varios, se infiere un mrow).
_SINGLE_CHILD = frozenset({"msqrt", "mtd", "menclose", "merror", "mpadded", "mstyle", "mphantom", "math"})
_WRAPPERS = frozenset({"mstyle", "mpadded", "semantics", "maction", "mlabeledtr_label"})
_REMOVE = frozenset({"mphantom", "maligngroup", "malignmark", "annotation", "annotation-xml", "none_removed", "script", "style"})
_VOID = frozenset({"mspace", "mglyph", "none", "mprescripts", "malignmark", "maligngroup", "br", "img", "sep"})

OPEN_FENCES = {
	"(": ")",
	"[": "]",
	"{": "}",
	"⟨": "⟩",
	"〈": "〉",
	"⌊": "⌋",
	"⌈": "⌉",
	"⟦": "⟧",
	"⟮": "⟯",
	"❲": "❳",
}
CLOSE_FENCES = {v: k for k, v in OPEN_FENCES.items()}
AMBIGUOUS_FENCES = frozenset({"|", "‖", "∣", "∥", "¦"})

INVISIBLE_TIMES = "⁢"
FUNCTION_APPLY = "⁡"
INVISIBLE_SEPARATOR = "⁣"
INVISIBLE_PLUS = "⁤"
INVISIBLE_OPERATORS = frozenset({INVISIBLE_TIMES, FUNCTION_APPLY, INVISIBLE_SEPARATOR, INVISIBLE_PLUS})

#: Normalización de caracteres de operadores.
_MO_NORMALIZE = {
	"-": "−",
	"‐": "−",
	"–": "−",
	"'": "′",
	"''": "″",
	"'''": "‴",
	"*": "∗",
	"<=": "≤",
	">=": "≥",
	"!=": "≠",
	"->": "→",
	"=>": "⇒",
	"<->": "↔",
	"<=>": "⇔",
	"...": "…",
	"⩽": "≤",
	"⩾": "≥",
	"∣": "|",
}

_WS = re.compile(r"\s+")


class MathNode:
	"""Nodo del árbol MathML."""

	__slots__ = ("tag", "attrs", "children", "text", "parent")

	def __init__(self, tag: str, attrs: dict | None = None, children: list["MathNode"] | None = None, text: str = "") -> None:
		self.tag = tag
		self.attrs: dict[str, str] = dict(attrs or {})
		self.children: list[MathNode] = []
		self.text = text
		self.parent: MathNode | None = None
		for c in children or ():
			self.append(c)

	# ---------------------------------------------------------- estructura
	def append(self, child: "MathNode") -> None:
		child.parent = self
		self.children.append(child)

	def setChildren(self, children: list["MathNode"]) -> None:
		self.children = []
		for c in children:
			self.append(c)

	@property
	def index(self) -> int:
		if self.parent is None:
			return 0
		for i, c in enumerate(self.parent.children):
			if c is self:
				return i
		return 0

	@property
	def isToken(self) -> bool:
		return self.tag in TOKEN_TAGS

	@property
	def isFenced(self) -> bool:
		return self.tag == "mrow" and "_open" in self.attrs

	@property
	def fenceContent(self) -> "MathNode | None":
		"""Contenido de un grupo delimitado (sin los delimitadores)."""
		if not self.isFenced:
			return None
		return self.children[1] if len(self.children) >= 2 else None

	def get(self, name: str, default: str = "") -> str:
		return self.attrs.get(name, default)

	def iter(self) -> Iterator["MathNode"]:
		yield self
		for c in self.children:
			yield from c.iter()

	def textContent(self) -> str:
		if self.isToken:
			return self.text
		return "".join(c.textContent() for c in self.children)

	def path(self) -> tuple[int, ...]:
		out: list[int] = []
		n: MathNode | None = self
		while n is not None and n.parent is not None:
			out.append(n.index)
			n = n.parent
		return tuple(reversed(out))

	def root(self) -> "MathNode":
		n = self
		while n.parent is not None:
			n = n.parent
		return n

	def nodeAtPath(self, path: tuple[int, ...]) -> "MathNode | None":
		n: MathNode = self
		for i in path:
			if i >= len(n.children):
				return None
			n = n.children[i]
		return n

	def copy(self) -> "MathNode":
		return MathNode(self.tag, self.attrs, [c.copy() for c in self.children], self.text)

	def isMo(self, *chars: str) -> bool:
		return self.tag == "mo" and (not chars or self.text in chars)

	# ---------------------------------------------------------- serialización
	def toMathML(self, pretty: bool = False, _depth: int = 0) -> str:
		ind = "  " * _depth if pretty else ""
		nl = "\n" if pretty else ""
		attrs = "".join(f' {k}="{html.escape(v, quote=True)}"' for k, v in self.attrs.items() if not k.startswith("_"))
		if self.tag == "math" and _depth == 0 and "xmlns" not in self.attrs:
			attrs = ' xmlns="http://www.w3.org/1998/Math/MathML"' + attrs
		if self.isToken:
			if self.tag in ("mspace", "mglyph") and not self.text:
				return f"{ind}<{self.tag}{attrs}/>{nl}"
			return f"{ind}<{self.tag}{attrs}>{html.escape(self.text, quote=False)}</{self.tag}>{nl}"
		if not self.children:
			return f"{ind}<{self.tag}{attrs}/>{nl}"
		inner = "".join(c.toMathML(pretty, _depth + 1) for c in self.children)
		return f"{ind}<{self.tag}{attrs}>{nl}{inner}{ind}</{self.tag}>{nl}"

	def __repr__(self) -> str:
		if self.isToken:
			return f"<{self.tag} {self.text!r}>"
		return f"<{self.tag} {len(self.children)} hijos>"


def mi(text: str, **attrs: str) -> MathNode:
	return MathNode("mi", attrs, text=text)


def mn(text: str, **attrs: str) -> MathNode:
	return MathNode("mn", attrs, text=text)


def mo(text: str, **attrs: str) -> MathNode:
	return MathNode("mo", attrs, text=text)


def mtext(text: str) -> MathNode:
	return MathNode("mtext", text=text)


def mrow(*children: MathNode) -> MathNode:
	return MathNode("mrow", children=list(children))


# ====================================================================== análisis
def _localName(tag: str) -> str:
	tag = tag.lower()
	if ":" in tag:
		tag = tag.split(":", 1)[1]
	return tag


class _Builder(HTMLParser):
	def __init__(self) -> None:
		super().__init__(convert_charrefs=True)
		self.root = MathNode("#document")
		self.stack: list[MathNode] = [self.root]

	@property
	def top(self) -> MathNode:
		return self.stack[-1]

	def handle_starttag(self, tag: str, attrs: list) -> None:
		name = _localName(tag)
		node = MathNode(name, {_localName(k): (v if v is not None else "") for k, v in attrs})
		if name == "sep":
			# <cn>1<sep/>2</cn>: separa las dos partes del número.
			self.top.text += " "
		self.top.append(node)
		if name not in _VOID:
			self.stack.append(node)

	def handle_startendtag(self, tag: str, attrs: list) -> None:
		name = _localName(tag)
		node = MathNode(name, {_localName(k): (v if v is not None else "") for k, v in attrs})
		if name == "sep":
			self.top.text += " "
		self.top.append(node)

	def handle_endtag(self, tag: str) -> None:
		name = _localName(tag)
		for i in range(len(self.stack) - 1, 0, -1):
			if self.stack[i].tag == name:
				del self.stack[i:]
				return

	def handle_data(self, data: str) -> None:
		top = self.top
		if top.tag in TOKEN_TAGS or top.tag in ("annotation", "ci", "cn", "csymbol", "#text"):
			top.text += data
		elif data.strip():
			# Texto suelto dentro de un elemento de disposición: se trata como mtext.
			top.append(MathNode("#text", text=data))


_XML_PREFIX = re.compile(r"^.*?(?=<(?:[\w-]+:)?math[\s>/])", re.DOTALL | re.IGNORECASE)
_XML_DECL = re.compile(r"<\?xml[^>]*\?>|<!DOCTYPE[^>]*>|<!--.*?-->", re.DOTALL | re.IGNORECASE)
_CDATA = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)


def stripExtraneousXml(markup: str) -> str:
	"""Quita lo que haya antes de la etiqueta ``<math>``."""
	return _XML_PREFIX.sub("", markup, count=1)


def looksLikeMathML(text: str) -> bool:
	t = text.strip()
	return bool(re.search(r"<(?:[\w-]+:)?(math|mrow|mi|mn|mo|mfrac|msup|msub|msqrt|apply|semantics)[\s>/]", t[:2000], re.IGNORECASE))


def parse(markup: str) -> MathNode:
	"""Analiza MathML (tolerante) y devuelve el elemento ``math`` normalizado.

	Si el texto no contiene ``<math>``, el contenido se envuelve en uno.
	"""
	if not isinstance(markup, str):
		markup = markup.decode("utf-8", "replace")
	markup = _XML_DECL.sub("", markup)
	markup = _CDATA.sub(lambda m: html.escape(m.group(1), quote=False), markup)
	if re.search(r"<(?:[\w-]+:)?math[\s>/]", markup, re.IGNORECASE):
		markup = stripExtraneousXml(markup)
	b = _Builder()
	b.feed(markup)
	b.close()
	mathEl = next((n for n in b.root.iter() if n.tag == "math"), None)
	if mathEl is None:
		mathEl = MathNode("math", children=list(b.root.children))
	else:
		mathEl.parent = None
	return normalize(mathEl)


# ====================================================================== normalización
def _variantFromChar(ch: str) -> tuple[str, str]:
	"""Convierte un carácter matemático (𝑥, 𝐱, ℝ...) en (carácter, variante)."""
	if len(ch) != 1 or ord(ch) < 0x2100:
		return ch, ""
	try:
		name = unicodedata.name(ch)
	except ValueError:
		return ch, ""
	variant = ""
	if "DOUBLE-STRUCK" in name:
		variant = "double-struck"
	elif "FRAKTUR" in name or "BLACK-LETTER" in name:
		variant = "fraktur"
	elif "SCRIPT" in name:
		variant = "bold-script" if "BOLD" in name else "script"
	elif "MATHEMATICAL" in name:
		if "BOLD" in name and "ITALIC" in name:
			variant = "bold-italic"
		elif "BOLD" in name:
			variant = "bold"
		elif "SANS-SERIF" in name:
			variant = "sans-serif"
		elif "MONOSPACE" in name:
			variant = "monospace"
		elif "ITALIC" in name:
			variant = "italic"
	if not variant:
		return ch, ""
	base = unicodedata.normalize("NFKC", ch)
	if base == ch:
		return ch, ""
	return base, variant


def normalizeIdentifierText(text: str) -> tuple[str, str]:
	"""Texto de un ``mi`` sin caracteres matemáticos especiales y su variante."""
	out = []
	variant = ""
	for ch in text:
		b, v = _variantFromChar(ch)
		out.append(b)
		if v and v != "italic":
			variant = v
	return "".join(out), variant


def _cleanToken(node: MathNode) -> None:
	t = node.text.replace(" ", " ")
	if node.tag == "mtext":
		node.text = _WS.sub(" ", t)
		return
	t = _WS.sub(" ", t).strip()
	if node.tag == "mi":
		base, variant = normalizeIdentifierText(t)
		if variant and "mathvariant" not in node.attrs:
			node.attrs["mathvariant"] = variant
		node.text = base
	elif node.tag == "mn":
		node.text = unicodedata.normalize("NFKC", t).replace(" ", "")
	elif node.tag == "mo":
		t = _MO_NORMALIZE.get(t, t)
		node.text = t
	else:
		node.text = t


def _contentToPresentation(node: MathNode) -> MathNode:
	from .content import toPresentation

	return toPresentation(node)


_CONTENT_TAGS = frozenset({"apply", "ci", "cn", "csymbol", "bind", "set", "list", "vector", "matrix", "interval", "lambda", "piecewise", "cs", "share", "cerror", "cbytes"})


def _normalizeChildren(node: MathNode) -> list[MathNode]:
	out: list[MathNode] = []
	for c in node.children:
		res = _normalizeNode(c)
		if res is None:
			continue
		if isinstance(res, list):
			out.extend(res)
		else:
			out.append(res)
	return out


def _normalizeNode(node: MathNode):  # -> MathNode | list[MathNode] | None
	tag = node.tag
	if tag == "#text":
		t = _WS.sub(" ", node.text).strip()
		return MathNode("mtext", text=t) if t else None
	if tag in _REMOVE:
		return None
	if tag in _CONTENT_TAGS:
		return _normalizeNode(_contentToPresentation(node))
	if tag == "semantics":
		# Primer hijo de presentación; si solo hay anotaciones, se usa la de contenido.
		pres = [c for c in node.children if c.tag not in ("annotation", "annotation-xml")]
		if pres:
			return _normalizeNode(pres[0])
		for c in node.children:
			if c.tag == "annotation-xml" and c.children:
				return _normalizeNode(c.children[0])
		for c in node.children:
			if c.tag == "annotation" and c.text.strip():
				return MathNode("mtext", text=c.text.strip())
		return None
	if tag == "maction":
		kids = [c for c in node.children]
		if not kids:
			return None
		try:
			sel = int(node.get("selection", "1")) - 1
		except ValueError:
			sel = 0
		return _normalizeNode(kids[max(0, min(sel, len(kids) - 1))])
	if tag in ("mstyle", "mpadded"):
		kids = _normalizeChildren(node)
		if tag == "mstyle" and "mathvariant" in node.attrs:
			for k in kids:
				if k.tag == "mi" and "mathvariant" not in k.attrs:
					k.attrs["mathvariant"] = node.attrs["mathvariant"]
		return kids
	if tag == "mfenced":
		return _expandMfenced(node)
	if node.isToken:
		new = MathNode(tag, node.attrs, text=node.text)
		_cleanToken(new)
		if tag in ("mi", "mn", "mo") and not new.text and tag != "mo":
			return None
		if tag == "mo" and not new.text:
			return None
		if tag == "mtext" and not new.text.strip():
			# Espacio de texto: se conserva como espacio.
			return MathNode("mspace", {"width": "thinmathspace"})
		return new
	if tag == "html" or tag == "body" or tag == "span" or tag == "div" or tag == "#document":
		return _normalizeChildren(node)
	new = MathNode(tag, {k: v for k, v in node.attrs.items()})
	kids = _normalizeChildren(node)
	if tag == "math" or tag in _SINGLE_CHILD:
		if tag == "math":
			new.setChildren([_inferRow(kids)] if kids else [])
		else:
			new.setChildren([_inferRow(kids)] if kids else [MathNode("mrow")])
		return new
	if tag == "mrow":
		if not kids:
			return None
		new.setChildren(kids)
		_groupFences(new)
		if len(new.children) == 1 and not new.attrs:
			return new.children[0]
		return new
	if tag in ("mfrac", "mroot", "msub", "msup", "munder", "mover") and len(kids) != 2:
		kids = (kids + [MathNode("mrow"), MathNode("mrow")])[:2] if len(kids) < 2 else kids[:2]
	elif tag in ("msubsup", "munderover") and len(kids) != 3:
		kids = (kids + [MathNode("mrow")] * 3)[:3]
	new.setChildren(kids)
	return new


def _inferRow(kids: list[MathNode]) -> MathNode:
	if len(kids) == 1:
		return kids[0]
	row = MathNode("mrow", children=kids)
	_groupFences(row)
	if len(row.children) == 1:
		return row.children[0]
	return row


def _expandMfenced(node: MathNode) -> MathNode:
	open_ = node.get("open", "(")
	close = node.get("close", ")")
	seps = re.sub(r"\s", "", node.get("separators", ","))
	kids = _normalizeChildren(node)
	inner: list[MathNode] = []
	for i, k in enumerate(kids):
		if i > 0 and seps:
			inner.append(mo(seps[min(i - 1, len(seps) - 1)]))
		inner.append(k)
	parts: list[MathNode] = []
	if open_:
		parts.append(mo(open_))
	content = inner[0] if len(inner) == 1 else MathNode("mrow", children=inner)
	if inner:
		parts.append(content)
	if close:
		parts.append(mo(close))
	if open_ and close and inner:
		return MathNode("mrow", {"_open": open_, "_close": close}, parts)
	row = MathNode("mrow", children=parts)
	_groupFences(row)
	return row if len(row.children) != 1 else row.children[0]


# ---------------------------------------------------------------- delimitadores
def _isOperand(node: MathNode) -> bool:
	if node.tag == "mo":
		return node.text in CLOSE_FENCES or node.text in ("′", "″", "‴", "!", "%", "°")
	return node.tag != "mspace"


def _makeGroup(items: list[MathNode], closeNode: MathNode | None) -> MathNode:
	openNode = items[0]
	inner = items[1:]
	if inner:
		content = inner[0] if len(inner) == 1 else MathNode("mrow", children=inner)
	else:
		content = MathNode("mrow")
	if len(inner) > 1:
		_groupFences(content)
	children = [openNode, content]
	attrs = {"_open": openNode.text, "_close": closeNode.text if closeNode is not None else ""}
	if closeNode is not None:
		children.append(closeNode)
	return MathNode("mrow", attrs, children)


def _groupFences(row: MathNode) -> None:
	"""Agrupa los delimitadores emparejados de un ``mrow``."""
	kids = row.children
	if len(kids) < 2 or row.isFenced:
		return
	out: list[MathNode] = []
	stack: list[tuple[int, str]] = []
	for idx, node in enumerate(kids):
		ch = node.text if node.tag == "mo" else None
		if ch in OPEN_FENCES:
			stack.append((len(out), ch))
			out.append(node)
			continue
		if ch in CLOSE_FENCES:
			want = CLOSE_FENCES[ch]
			pos = next((k for k in range(len(stack) - 1, -1, -1) if stack[k][1] == want), None)
			if pos is None:
				out.append(node)
				continue
			start = stack[pos][0]
			del stack[pos:]
			group = _makeGroup(out[start:], node)
			del out[start:]
			out.append(group)
			continue
		if ch in AMBIGUOUS_FENCES:
			top = stack[-1] if stack else None
			if top is not None and top[1] == ch and len(out) - 1 > top[0] and out and _isOperand(out[-1]):
				start = top[0]
				stack.pop()
				group = _makeGroup(out[start:], node)
				del out[start:]
				out.append(group)
				continue
			# Abre un grupo si hay otra barra igual más adelante.
			if any(k.tag == "mo" and k.text == ch for k in kids[idx + 1 :]):
				if not out or not _isOperand(out[-1]) or _barCanOpenAfterOperand(kids, idx):
					stack.append((len(out), ch))
			out.append(node)
			continue
		out.append(node)
	row.setChildren(out)


def _barCanOpenAfterOperand(kids: list[MathNode], idx: int) -> bool:
	"""``2|x|``: la barra tras un número abre un valor absoluto si la siguiente
	barra va precedida de un operando y no hay operadores de relación entre ellas."""
	ch = kids[idx].text
	for j in range(idx + 1, len(kids)):
		k = kids[j]
		if k.tag == "mo" and k.text == ch:
			return j > idx + 1 and _isOperand(kids[j - 1])
		if k.tag == "mo" and k.text in ("=", "<", ">", "≤", "≥", ",", ";", ":"):
			return False
	return False


def normalize(mathEl: MathNode) -> MathNode:
	res = _normalizeNode(mathEl)
	if isinstance(res, list) or res is None or res.tag != "math":
		kids = res if isinstance(res, list) else ([res] if res is not None else [])
		root = MathNode("math", mathEl.attrs)
		root.setChildren([_inferRow(kids)] if kids else [])
		res = root
	for k in ("alttext", "display"):
		if k in mathEl.attrs:
			res.attrs[k] = mathEl.attrs[k]
	return res


def fromLinearText(text: str) -> MathNode:
	"""Árbol mínimo a partir de texto lineal (p. ej. ``x² + 1``)."""
	from .latex import linearTextToMathML

	return parse(linearTextToMathML(text))


def mathContent(root: MathNode) -> MathNode | None:
	"""Contenido del elemento ``math`` (su único hijo normalizado)."""
	if root.tag == "math":
		return root.children[0] if root.children else None
	return root
