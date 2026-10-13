"""Braille matemático: Código Matemático Unificado para la lengua castellana (CMU).

Implementación propia de la signografía matemática española de la ONCE
(Comisión Braille Española, documento B5 «Signografía matemática») para lo
esencial:

- números con signo de número (⠼), coma decimal (⠂) y punto de millar (⠄);
- letras latinas (signo de mayúscula ⠨), letras griegas (prefijo ⠈) y el
  punto 5 (⠐) para separar un número de una letra de la a a la j;
- operaciones (+ ⠖, − ⠤, × ⠦, · ⠄, ÷ y barra ⠲), relaciones (= ⠶, ≠ ⠘⠶,
  < ⠪, > ⠕, ≤ ⠪⠶, ≥ ⠕⠶, ≈ ⠐⠶⠄...), conjuntos y lógica, flechas;
- paréntesis ⠣ ⠜, corchetes ⠷ ⠾, llaves ⠐⠇ ⠸⠂, barras ⠸;
- fracciones (numerador ⠲ denominador; las numéricas con el denominador en
  la parte inferior de la celda), con paréntesis auxiliares ⠢ ... ⠔ cuando
  el numerador o el denominador son compuestos;
- superíndices ⠡, subíndices ⠌, raíces ⠫⠱ y raíces de índice ⠫ índice ⠱;
- sumatorios, productos, integrales y límites: operador, límite inferior,
  ⠒, límite superior y ⠱ para cerrar;
- funciones de varias letras terminadas en punto 3 (sen. log. lim.);
- matrices y determinantes por filas (⠠ al principio y al final de cada fila).

La salida (:class:`BrailleResult`) incluye para cada nodo del árbol las celdas
que ocupa, para situar el cursor braille durante la navegación.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .mathml import INVISIBLE_OPERATORS, INVISIBLE_PLUS, MathNode


def _d(spec: str) -> int:
	v = 0
	for ch in spec:
		if ch.isdigit() and ch != "0":
			v |= 1 << (int(ch) - 1)
	return v


def _cells(spec: str) -> list[int]:
	"""``"46-1"`` -> celdas."""
	return [_d(p) for p in spec.split("-") if p] if spec else []


NUMBER_SIGN = _d("3456")
CAPITAL = _d("46")
GREEK_PREFIX = _d("4")
LETTER_SEPARATOR = _d("5")
GROUP_OPEN = _d("26")
GROUP_CLOSE = _d("35")
FRACTION_BAR = _d("256")
SUPERSCRIPT = _d("16")
SUBSCRIPT = _d("34")
ROOT = _cells("1246-156")
ROOT_START = _d("1246")
ROOT_INDEX_END = _d("156")
LIMIT_SEPARATOR = _d("25")
LIMIT_END = _d("156")
ROW_MARK = _d("6")
BLANK = 0

LETTERS = {
	"a": "1",
	"b": "12",
	"c": "14",
	"d": "145",
	"e": "15",
	"f": "124",
	"g": "1245",
	"h": "125",
	"i": "24",
	"j": "245",
	"k": "13",
	"l": "123",
	"m": "134",
	"n": "1345",
	"o": "135",
	"p": "1234",
	"q": "12345",
	"r": "1235",
	"s": "234",
	"t": "2345",
	"u": "136",
	"v": "1236",
	"w": "2456",
	"x": "1346",
	"y": "13456",
	"z": "1356",
	"á": "12356",
	"é": "2346",
	"í": "34",
	"ó": "346",
	"ú": "23456",
	"ü": "1256",
	"ñ": "12456",
}
DIGIT_LETTERS = {"1": "a", "2": "b", "3": "c", "4": "d", "5": "e", "6": "f", "7": "g", "8": "h", "9": "i", "0": "j"}
#: Cifras en la parte inferior de la celda (denominadores de fracciones numéricas).
LOWER_DIGITS = {"0": "356", "1": "2", "2": "23", "3": "25", "4": "256", "5": "26", "6": "235", "7": "2356", "8": "236", "9": "35"}

GREEK = {
	"α": "1",
	"β": "12",
	"γ": "1245",
	"δ": "145",
	"ε": "15",
	"ϵ": "15",
	"ζ": "1356",
	"η": "156",
	"θ": "1456",
	"ϑ": "1456",
	"ι": "24",
	"κ": "13",
	"λ": "123",
	"μ": "134",
	"µ": "134",
	"ν": "1345",
	"ξ": "1346",
	"ο": "135",
	"π": "1234",
	"ϖ": "1234",
	"ρ": "1235",
	"σ": "234",
	"ς": "234",
	"τ": "2345",
	"υ": "136",
	"φ": "124",
	"ϕ": "124",
	"χ": "12346",
	"ψ": "13456",
	"ω": "2456",
}

#: Operadores, relaciones y otros símbolos.
SYMBOLS = {
	"+": "235",
	"−": "36",
	"-": "36",
	"±": "235-25-36",
	"∓": "36-25-235",
	"×": "236",
	"·": "3",
	"⋅": "3",
	"∙": "3",
	"∗": "56-3",
	"÷": "256",
	"/": "256",
	":": "5-2",
	"∶": "5-2",
	"=": "2356",
	"≠": "45-2356",
	"<": "246",
	">": "135",
	"≤": "246-2356",
	"≥": "135-2356",
	"≮": "45-246",
	"≯": "45-135",
	"≪": "246-246",
	"≫": "135-135",
	"≈": "5-2356-3",
	"≡": "2356-2356",
	"≅": "5-26-2356",
	"∼": "5-26",
	"≃": "5-26-2356",
	"∝": "456-256",
	"≔": "56-2356",
	"(": "126",
	")": "345",
	"[": "12356",
	"]": "23456",
	"{": "5-123",
	"}": "456-2",
	"|": "456",
	"∣": "456",
	"‖": "456-123",
	"∥": "456-123",
	"⟨": "5-13",
	"〈": "5-13",
	"⟩": "46-2",
	"〉": "46-2",
	"⌊": "12356-3",
	"⌋": "6-23456",
	"⌈": "12356-2",
	"⌉": "5-23456",
	",": "2",
	";": "23",
	".": "3",
	"!": "45-3",
	"%": "456-356",
	"‰": "456-356-356",
	"°": "356",
	"′": "1256",
	"″": "1256-1256",
	"‴": "1256-1256-1256",
	"∞": "3456-1256",
	"∂": "456-145",
	"∇": "4-12456",
	"∈": "126-2",
	"∉": "45-126-2",
	"∋": "5-345",
	"⊂": "126-3",
	"⊄": "45-126-3",
	"⊆": "126-23",
	"⊈": "45-126-23",
	"⊃": "6-345",
	"⊇": "56-345",
	"∪": "456-345",
	"∩": "456-156",
	"∖": "5-3",
	"∅": "456-245",
	"∀": "46-3",
	"∃": "46-26",
	"∄": "45-46-26",
	"¬": "6-3",
	"∧": "456-26",
	"∨": "456-24",
	"⊻": "456-2346",
	"⇒": "25-135",
	"⟹": "25-135",
	"⇐": "246-25",
	"⟸": "246-25",
	"⇔": "246-25-135",
	"⟺": "246-25-135",
	"→": "25-2",
	"⟶": "25-2",
	"←": "5-25",
	"⟵": "5-25",
	"↔": "5-25-2",
	"↦": "25-25-2",
	"↑": "456-1",
	"↓": "456-3",
	"⊥": "3456-3",
	"∠": "456-246",
	"△": "6-23456",
	"∘": "6-23",
	"⊕": "246-235",
	"⊗": "246-236",
	"∴": "6-16",
	"∵": "4-34",
	"…": "3-3-3",
	"⋯": "3-3-3",
	"⋮": "3-3-3",
	"⋱": "3-3-3",
	"∫": "12346",
	"∬": "12346-12346",
	"∭": "12346-12346-12346",
	"∮": "12346-356",
	"∑": "46-4-234",
	"∏": "46-4-1234",
	"⋃": "123456-345",
	"⋂": "123456-156",
	"€": "456-15",
	"$": "456-234",
	"&": "6-12346",
	"#": "3456-13",
	"?": "26",
	"¿": "26",
	"'": "3",
	"\"": "236",
	"_": "36",
	"¯": "4-14",
	"~": "5-26",
	"^": "56-25",
	"˙": "4",
	"¨": "4-4",
	"ℏ": "125-4-14",
}

#: Acentos sobre la base (se escriben antes de la base).
ACCENTS_OVER = {"¯": "4-14", "‾": "4-14", "^": "56-25", "ˆ": "56-25", "~": "5-26", "˜": "5-26", "→": "25-2", "⃗": "25-2", "⟶": "25-2", "˙": "4", "¨": "4-4"}
ACCENTS_UNDER = {"_": "6-36", "¯": "6-36", "~": "2-26"}

BIG_OPERATORS = frozenset({"∑", "∏", "∐", "∫", "∬", "∭", "∮", "⋃", "⋂", "⋁", "⋀"})
LIMIT_NAMES = frozenset({"lim", "log", "lim sup", "lim inf", "máx", "mín", "max", "min"})


@dataclass
class BrailleResult:
	cells: list[int] = field(default_factory=list)
	#: id(nodo) -> (primera celda, celda siguiente a la última)
	ranges: dict[int, tuple[int, int]] = field(default_factory=dict)

	def rangeOf(self, node: MathNode) -> tuple[int, int] | None:
		return self.ranges.get(id(node))

	def nodeAt(self, cell: int, root: MathNode) -> MathNode | None:
		"""Nodo más profundo que ocupa la celda indicada."""
		best = None
		bestLen = 1 << 30
		for n in root.iter():
			r = self.ranges.get(id(n))
			if r and r[0] <= cell < r[1] and r[1] - r[0] <= bestLen:
				best = n
				bestLen = r[1] - r[0]
		return best


def toUnicode(cells: list[int]) -> str:
	return "".join(chr(0x2800 + (c & 0xFF)) for c in cells)


class _Translator:
	def __init__(self) -> None:
		self.out: list[int] = []
		self.ranges: dict[int, tuple[int, int]] = {}
		self.inNumber = False

	# ---------------------------------------------------------- bajo nivel
	def emit(self, cells: list[int], keepNumber: bool = False) -> None:
		self.out.extend(cells)
		if not keepNumber:
			self.inNumber = False

	def emitSpec(self, spec: str) -> None:
		self.emit(_cells(spec))

	def number(self, text: str, lower: bool = False) -> None:
		t = text.replace(" ", "").replace(" ", "")
		neg = t[:1] in ("−", "-")
		if neg:
			self.emitSpec("36")
			t = t[1:]
		# Separadores: la coma es decimal; el punto también, salvo que sea de
		# millares (grupos de tres cifras repetidos: 1.000.000).
		decimalPos = -1
		seps = [i for i, ch in enumerate(t) if ch in ",."]
		if seps:
			last = seps[-1]
			after = t[last + 1 :]
			if t[last] == ",":
				decimalPos = last
			elif not (len(after) == 3 and t.count(".") > 1):
				decimalPos = last
		first = True
		for i, ch in enumerate(t):
			if ch.isdigit():
				if lower:
					self.out.append(_d(LOWER_DIGITS[ch]))
				else:
					if first and not self.inNumber:
						self.out.append(NUMBER_SIGN)
					self.out.append(_d(LETTERS[DIGIT_LETTERS[ch]]))
				first = False
				self.inNumber = True
			elif ch in ",.":
				self.out.append(_d("2") if i == decimalPos else _d("3"))
				self.inNumber = True
			else:
				self.inNumber = False
				self.char(ch)

	def letter(self, ch: str) -> None:
		low = ch.lower()
		if low in LETTERS and ch.isalpha():
			if ch != low:
				self.out.append(CAPITAL)
			elif self.inNumber and low in "abcdefghij":
				self.out.append(LETTER_SEPARATOR)
			self.out.append(_d(LETTERS[low]))
			self.inNumber = False
			return
		lowG = ch.lower()
		if lowG in GREEK:
			if ch != lowG:
				self.out.append(CAPITAL)
			self.out.append(GREEK_PREFIX)
			self.out.append(_d(GREEK[lowG]))
			self.inNumber = False
			return
		self.char(ch)

	def char(self, ch: str) -> None:
		if ch in INVISIBLE_OPERATORS:
			if ch == INVISIBLE_PLUS:
				return
			return
		if ch.isdigit():
			self.number(ch)
			return
		if ch.isalpha() and (ch.lower() in LETTERS or ch.lower() in GREEK):
			self.letter(ch)
			return
		if ch in SYMBOLS:
			self.emit(_cells(SYMBOLS[ch]))
			return
		if ch.isspace():
			self.emit([BLANK])
			return
		if 0x2800 <= ord(ch) <= 0x28FF:
			self.emit([ord(ch) - 0x2800])
			return
		import unicodedata

		base = unicodedata.normalize("NFKD", ch)
		if base != ch and base:
			for b in base:
				if b.isalnum() or b in SYMBOLS:
					self.char(b)
			return
		# Símbolo sin representación: celda completa.
		self.emit([_d("123456")])

	def text(self, t: str) -> None:
		for ch in t:
			if ch.isdigit():
				self.number(ch)
			else:
				self.char(ch)

	# ---------------------------------------------------------- estructura
	def node(self, n: MathNode) -> None:
		start = len(self.out)
		method = getattr(self, "t_" + n.tag.replace("-", "_"), None)
		if method is not None:
			method(n)
		else:
			for c in n.children:
				self.node(c)
			if n.isToken and n.text:
				self.text(n.text)
		self.ranges[id(n)] = (start, len(self.out))

	@staticmethod
	def needsGroup(n: MathNode) -> bool:
		if n.isToken:
			return False
		if n.isFenced:
			return False
		if n.tag == "mrow":
			real = [k for k in n.children if not (k.tag == "mo" and k.text in INVISIBLE_OPERATORS)]
			if len(real) == 2 and real[0].isMo("−") and real[1].tag in ("mn", "mi"):
				return False
			return len(real) > 1
		if n.tag == "mfrac":
			return not (n.children[0].tag == "mn" and n.children[1].tag == "mn")
		return n.tag in ("msqrt", "mroot", "munderover", "msubsup")

	def grouped(self, n: MathNode, force: bool = False) -> None:
		if force or self.needsGroup(n):
			self.emit([GROUP_OPEN])
			self.node(n)
			self.emit([GROUP_CLOSE])
		else:
			self.node(n)

	def t_math(self, n: MathNode) -> None:
		for c in n.children:
			self.node(c)

	def t_mrow(self, n: MathNode) -> None:
		if n.isFenced:
			content = n.fenceContent
			o, c = n.get("_open"), n.get("_close")
			if content is not None and content.tag == "mtable":
				self.table(content, o, c, n)
				return
			if o == "(" and content is not None and content.tag == "mfrac" and content.get("linethickness") == "0":
				self.emitSpec("46-126")
				self.node(content.children[0])
				self.emitSpec("25")
				self.node(content.children[1])
				self.emitSpec("345")
				self.ranges[id(content)] = (len(self.out), len(self.out))
				return
		for c in n.children:
			self.node(c)

	def t_mi(self, n: MathNode) -> None:
		t = n.text
		if len(t) > 1 and t.replace(" ", "").isalpha() and t not in ("∞",):
			name = t.replace(" ", "")
			for ch in name:
				self.letter(ch)
			unit = "unit" in n.get("class", "").lower() or ":unit" in n.get("intent", "")
			if not unit:
				self.emitSpec("3")
			return
		if n.get("mathvariant") == "double-struck" and len(t) == 1:
			self.emitSpec("456")
		for ch in t:
			if ch.isalpha():
				self.letter(ch)
			else:
				self.char(ch)

	def t_mn(self, n: MathNode) -> None:
		self.number(n.text)

	def t_mo(self, n: MathNode) -> None:
		t = n.text
		if t in INVISIBLE_OPERATORS:
			return
		if t in SYMBOLS:
			self.emit(_cells(SYMBOLS[t]))
			return
		if t.isalpha() and len(t) > 1:
			for ch in t:
				self.letter(ch)
			self.emitSpec("3")
			return
		self.text(t)

	def t_mtext(self, n: MathNode) -> None:
		from ..braille import tables

		t = n.text
		if not t.strip():
			self.emit([BLANK])
			return
		tr = tables.getTable("es-g1").translate(t.strip())
		pre = t[:1].isspace()
		post = t[-1:].isspace()
		if pre:
			self.emit([BLANK])
		self.emit(tr.cells)
		if post:
			self.emit([BLANK])

	def t_ms(self, n: MathNode) -> None:
		self.emitSpec("236")
		self.t_mtext(n)
		self.emitSpec("236")

	def t_mspace(self, n: MathNode) -> None:
		width = n.get("width", "")
		if width and (width.endswith("em") and _num(width[:-2]) >= 0.9 or "thick" in width):
			self.emit([BLANK])

	def t_none(self, n: MathNode) -> None:
		pass

	def t_mfrac(self, n: MathNode) -> None:
		num, den = n.children
		if num.tag == "mn" and den.tag == "mn" and num.text.isdigit() and den.text.isdigit():
			self.node(num)
			start = len(self.out)
			self.number(den.text, lower=True)
			self.ranges[id(den)] = (start, len(self.out))
			self.inNumber = False
			return
		self.grouped(num)
		self.emit([FRACTION_BAR])
		self.grouped(den)

	def t_msqrt(self, n: MathNode) -> None:
		self.emit(ROOT)
		self.grouped(n.children[0])

	def t_mroot(self, n: MathNode) -> None:
		radicand, index = n.children
		self.emit([ROOT_START])
		self.node(index)
		self.emit([ROOT_INDEX_END])
		self.grouped(radicand)

	def _base(self, base: MathNode) -> None:
		if base.tag == "mrow" and not base.isFenced and len(base.children) > 1:
			self.grouped(base, force=True)
		else:
			self.node(base)

	def t_msup(self, n: MathNode) -> None:
		base, sup = n.children
		if sup.tag == "mo" and sup.text in ("′", "″", "‴", "°", "∘", "∗", "*", "+", "−"):
			self._base(base)
			start = len(self.out)
			if sup.text == "∘":
				self.char("°")
			else:
				self.node(sup)
			self.ranges[id(sup)] = (start, len(self.out))
			return
		self._base(base)
		self.emit([SUPERSCRIPT])
		self.grouped(sup)

	def t_msub(self, n: MathNode) -> None:
		base, sub = n.children
		if base.tag in ("mo", "mi") and base.text in BIG_OPERATORS:
			self._bigOp(base, sub, None)
			return
		if base.tag == "mi" and base.text in LIMIT_NAMES:
			self.node(base)
			self.node(sub)
			self.emit([LIMIT_END])
			return
		self._base(base)
		self.emit([SUBSCRIPT])
		self.grouped(sub)

	def t_msubsup(self, n: MathNode) -> None:
		base, sub, sup = n.children
		if base.tag in ("mo", "mi") and base.text in BIG_OPERATORS:
			self._bigOp(base, sub, sup)
			return
		self._base(base)
		self.emit([SUBSCRIPT])
		self.grouped(sub)
		if sup.tag == "mo" and sup.text in ("′", "″", "‴"):
			self.node(sup)
			return
		self.emit([SUPERSCRIPT])
		self.grouped(sup)

	def _bigOp(self, op: MathNode, lower: MathNode | None, upper: MathNode | None) -> None:
		self.node(op)
		if lower is not None:
			self.node(lower.fenceContent if lower.isFenced and lower.fenceContent is not None else lower)
		if upper is not None:
			self.emit([LIMIT_SEPARATOR])
			self.node(upper.fenceContent if upper.isFenced and upper.fenceContent is not None else upper)
		self.emit([LIMIT_END])

	def t_munder(self, n: MathNode) -> None:
		base, under = n.children
		if base.tag in ("mo", "mi") and base.text in BIG_OPERATORS:
			self._bigOp(base, under, None)
			return
		if base.tag == "mi" and base.text in LIMIT_NAMES:
			self.node(base)
			self.node(under)
			self.emit([LIMIT_END])
			return
		if under.tag == "mo" and under.text in ACCENTS_UNDER:
			self.emitSpec(ACCENTS_UNDER[under.text])
			self.ranges[id(under)] = (len(self.out) - len(_cells(ACCENTS_UNDER[under.text])), len(self.out))
			self.grouped(base)
			return
		self.grouped(base)
		self.emitSpec("34-34")
		self.node(under)
		self.emitSpec("3")

	def t_mover(self, n: MathNode) -> None:
		base, over = n.children
		if base.tag in ("mo", "mi") and base.text in BIG_OPERATORS:
			self._bigOp(base, None, over)
			return
		if over.tag == "mo" and over.text in ACCENTS_OVER:
			start = len(self.out)
			self.emitSpec(ACCENTS_OVER[over.text])
			self.ranges[id(over)] = (start, len(self.out))
			if over.text in ("˙", "¨") and base.tag == "mi" and base.text[:1].islower():
				self.emit([LETTER_SEPARATOR])
			self.grouped(base)
			return
		self.grouped(base)
		self.emitSpec("16-16")
		self.node(over)
		self.emitSpec("3")

	def t_munderover(self, n: MathNode) -> None:
		base, under, over = n.children
		if base.tag in ("mo", "mi") and base.text in BIG_OPERATORS:
			self._bigOp(base, under, over)
			return
		self.grouped(base)
		self.emitSpec("34-34")
		self.node(under)
		self.emitSpec("16-16")
		self.node(over)
		self.emitSpec("3")

	def t_mtable(self, n: MathNode) -> None:
		self.table(n, "", "", n)

	def table(self, table: MathNode, o: str, c: str, owner: MathNode) -> None:
		rows = [r for r in table.children if r.tag in ("mtr", "mlabeledtr")]
		multi = len(rows) > 1
		start = len(self.out)
		for i, r in enumerate(rows):
			rs = len(self.out)
			if i:
				self.emit([BLANK])
			if multi:
				self.emit([ROW_MARK])
			if o:
				self.char(o)
			cells = [x for x in r.children if x.tag == "mtd"]
			for j, cell in enumerate(cells):
				if j:
					self.emit([BLANK])
				self.node(cell)
			if multi:
				self.emit([ROW_MARK])
			if c:
				self.char(c)
			self.ranges[id(r)] = (rs, len(self.out))
		self.ranges[id(table)] = (start, len(self.out))

	def t_mtd(self, n: MathNode) -> None:
		for c in n.children:
			self.node(c)

	def t_menclose(self, n: MathNode) -> None:
		notation = n.get("notation", "longdiv")
		if "strike" in notation:
			self.emitSpec("12456")
			self.grouped(n.children[0], force=True)
			return
		if "top" in notation.split():
			self.emitSpec("4-14")
			self.grouped(n.children[0])
			return
		if "bottom" in notation.split():
			self.emitSpec("6-36")
			self.grouped(n.children[0])
			return
		self.grouped(n.children[0], force=True)

	def t_mmultiscripts(self, n: MathNode) -> None:
		kids = n.children
		if not kids:
			return
		post: list[MathNode] = []
		pre: list[MathNode] = []
		target = post
		for c in kids[1:]:
			if c.tag == "mprescripts":
				target = pre
				continue
			target.append(c)

		def scripts(lst: list[MathNode]) -> None:
			for i in range(0, len(lst) - 1, 2):
				sub, sup = lst[i], lst[i + 1]
				if sub.tag != "none":
					self.emit([SUBSCRIPT])
					self.grouped(sub)
				if sup.tag != "none":
					self.emit([SUPERSCRIPT])
					self.grouped(sup)

		if pre:
			scripts(pre)
			self.emitSpec("56")
		self._base(kids[0])
		scripts(post)


def _num(s: str) -> float:
	try:
		return float(s)
	except ValueError:
		return 0.0


def translate(root: MathNode) -> BrailleResult:
	tr = _Translator()
	tr.node(root)
	return BrailleResult(tr.out, tr.ranges)


def translateNode(node: MathNode) -> BrailleResult:
	return translate(node)
