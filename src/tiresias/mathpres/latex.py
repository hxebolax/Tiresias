"""Conversión LaTeX → MathML y MathML → LaTeX (código propio).

Cubre lo habitual en textos y en el portapapeles: fracciones, raíces,
potencias, subíndices, sumatorios, productos, integrales, límites, matrices
y entornos (``pmatrix``, ``cases``, ``align``...), letras griegas, funciones,
acentos, conjuntos de números, operadores y flechas. También acepta el
texto alternativo de Wikipedia (``{\\displaystyle ...}``) y los delimitadores
``$...$``, ``\\(...\\)`` y ``\\[...\\]``.
"""

from __future__ import annotations

import re

from .mathml import (
	FUNCTION_APPLY,
	OPEN_FENCES,
	MathNode,
	mi,
	mn,
	mo,
	mtext,
)

GREEK = {
	"alpha": "α",
	"beta": "β",
	"gamma": "γ",
	"delta": "δ",
	"epsilon": "ϵ",
	"varepsilon": "ε",
	"zeta": "ζ",
	"eta": "η",
	"theta": "θ",
	"vartheta": "ϑ",
	"iota": "ι",
	"kappa": "κ",
	"varkappa": "ϰ",
	"lambda": "λ",
	"mu": "μ",
	"nu": "ν",
	"xi": "ξ",
	"omicron": "ο",
	"pi": "π",
	"varpi": "ϖ",
	"rho": "ρ",
	"varrho": "ϱ",
	"sigma": "σ",
	"varsigma": "ς",
	"tau": "τ",
	"upsilon": "υ",
	"phi": "ϕ",
	"varphi": "φ",
	"chi": "χ",
	"psi": "ψ",
	"omega": "ω",
	"Gamma": "Γ",
	"Delta": "Δ",
	"Theta": "Θ",
	"Lambda": "Λ",
	"Xi": "Ξ",
	"Pi": "Π",
	"Sigma": "Σ",
	"Upsilon": "Υ",
	"Phi": "Φ",
	"Psi": "Ψ",
	"Omega": "Ω",
}

#: Símbolos que se convierten en identificadores (mi).
IDENT_SYMBOLS = {
	"infty": "∞",
	"partial": "∂",
	"nabla": "∇",
	"emptyset": "∅",
	"varnothing": "∅",
	"hbar": "ℏ",
	"ell": "ℓ",
	"aleph": "ℵ",
	"Re": "ℜ",
	"Im": "ℑ",
	"wp": "℘",
	"top": "⊤",
	"bot": "⊥",
	"imath": "ı",
	"jmath": "ȷ",
	"angle": "∠",
	"triangle": "△",
	"square": "□",
	"degree": "°",
	"prime": "′",
	"dagger": "†",
}

#: Operadores y relaciones (mo).
OPERATORS = {
	"cdot": "·",
	"times": "×",
	"div": "÷",
	"pm": "±",
	"mp": "∓",
	"ast": "∗",
	"star": "⋆",
	"circ": "∘",
	"bullet": "∙",
	"oplus": "⊕",
	"ominus": "⊖",
	"otimes": "⊗",
	"odot": "⊙",
	"leq": "≤",
	"le": "≤",
	"leqslant": "≤",
	"geq": "≥",
	"ge": "≥",
	"geqslant": "≥",
	"neq": "≠",
	"ne": "≠",
	"approx": "≈",
	"equiv": "≡",
	"sim": "∼",
	"simeq": "≃",
	"cong": "≅",
	"propto": "∝",
	"ll": "≪",
	"gg": "≫",
	"doteq": "≐",
	"coloneqq": "≔",
	"in": "∈",
	"notin": "∉",
	"ni": "∋",
	"subset": "⊂",
	"subseteq": "⊆",
	"subsetneq": "⊊",
	"supset": "⊃",
	"supseteq": "⊇",
	"not\\subset": "⊄",
	"cup": "∪",
	"cap": "∩",
	"setminus": "∖",
	"backslash": "∖",
	"forall": "∀",
	"exists": "∃",
	"nexists": "∄",
	"neg": "¬",
	"lnot": "¬",
	"land": "∧",
	"wedge": "∧",
	"lor": "∨",
	"vee": "∨",
	"Rightarrow": "⇒",
	"implies": "⇒",
	"Leftarrow": "⇐",
	"impliedby": "⇐",
	"Leftrightarrow": "⇔",
	"iff": "⇔",
	"to": "→",
	"rightarrow": "→",
	"longrightarrow": "⟶",
	"leftarrow": "←",
	"gets": "←",
	"longleftarrow": "⟵",
	"leftrightarrow": "↔",
	"mapsto": "↦",
	"uparrow": "↑",
	"downarrow": "↓",
	"Uparrow": "⇑",
	"Downarrow": "⇓",
	"perp": "⊥",
	"parallel": "∥",
	"mid": "|",
	"nmid": "∤",
	"ldots": "…",
	"dots": "…",
	"dotsc": "…",
	"dotsb": "⋯",
	"cdots": "⋯",
	"vdots": "⋮",
	"ddots": "⋱",
	"therefore": "∴",
	"because": "∵",
	"colon": ":",
	"vdash": "⊢",
	"models": "⊨",
	"triangleq": "≜",
	"lbrace": "{",
	"rbrace": "}",
	"langle": "⟨",
	"rangle": "⟩",
	"lfloor": "⌊",
	"rfloor": "⌋",
	"lceil": "⌈",
	"rceil": "⌉",
	"lvert": "|",
	"rvert": "|",
	"vert": "|",
	"lVert": "‖",
	"rVert": "‖",
	"Vert": "‖",
	"|": "‖",
	"{": "{",
	"}": "}",
	"%": "%",
	"#": "#",
	"&": "&",
	"_": "_",
	"$": "$",
}

#: Operadores grandes (con límites encima y debajo en modo destacado).
BIG_OPERATORS = {
	"sum": "∑",
	"prod": "∏",
	"coprod": "∐",
	"bigcup": "⋃",
	"bigcap": "⋂",
	"bigvee": "⋁",
	"bigwedge": "⋀",
	"bigoplus": "⨁",
	"bigotimes": "⨂",
}
INTEGRALS = {"int": "∫", "iint": "∬", "iiint": "∭", "oint": "∮"}

FUNCTION_NAMES = {
	"sin",
	"cos",
	"tan",
	"cot",
	"sec",
	"csc",
	"arcsin",
	"arccos",
	"arctan",
	"sinh",
	"cosh",
	"tanh",
	"coth",
	"log",
	"ln",
	"lg",
	"exp",
	"det",
	"dim",
	"ker",
	"deg",
	"gcd",
	"arg",
	"hom",
	"Pr",
	"sen",
	"tg",
	"arcsen",
	"arctg",
	"senh",
	"tgh",
	"mcd",
	"mcm",
	"lcm",
	"sgn",
}
#: Funciones cuyos límites van debajo (lim, max...).
LIMIT_FUNCTIONS = {"lim", "limsup", "liminf", "max", "min", "sup", "inf", "argmax", "argmin"}

ACCENTS = {
	"hat": "^",
	"widehat": "^",
	"bar": "¯",
	"overline": "¯",
	"vec": "→",
	"overrightarrow": "→",
	"overleftarrow": "←",
	"tilde": "~",
	"widetilde": "~",
	"dot": "˙",
	"ddot": "¨",
	"check": "ˇ",
	"breve": "˘",
	"acute": "´",
	"grave": "`",
	"mathring": "˚",
	"overbrace": "⏞",
}
UNDER_ACCENTS = {"underline": "_", "underbrace": "⏟", "underleftarrow": "←", "underrightarrow": "→"}

FONTS = {
	"mathbf": "bold",
	"boldsymbol": "bold",
	"bm": "bold",
	"mathbb": "double-struck",
	"mathcal": "script",
	"mathscr": "script",
	"mathfrak": "fraktur",
	"mathit": "italic",
	"mathsf": "sans-serif",
	"mathtt": "monospace",
	"mathrm": "normal",
	"mathup": "normal",
	"textbf": "bold",
}
TEXT_COMMANDS = {"text", "textrm", "mbox", "textit", "textnormal", "hbox", "texttt", "textsf", "textup"}
SPACES = {",": "0.167em", ":": "0.222em", ";": "0.278em", "!": "-0.167em", "quad": "1em", "qquad": "2em", " ": "0.25em", "enspace": "0.5em", "thinspace": "0.167em", "medspace": "0.222em", "thickspace": "0.278em"}
IGNORED = {"displaystyle", "textstyle", "scriptstyle", "scriptscriptstyle", "limits", "nolimits", "nonumber", "notag", "left.", "right.", "big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr", "biggl", "biggr", "Biggl", "Biggr", "middle", "strut", "label", "tag", "allowbreak", "phantom", "hphantom", "vphantom", "relax"}

MATRIX_ENVS = {
	"matrix": ("", ""),
	"smallmatrix": ("", ""),
	"pmatrix": ("(", ")"),
	"bmatrix": ("[", "]"),
	"Bmatrix": ("{", "}"),
	"vmatrix": ("|", "|"),
	"Vmatrix": ("‖", "‖"),
}

_SUPERSCRIPTS = str.maketrans({"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9", "⁺": "+", "⁻": "-", "⁼": "=", "⁽": "(", "⁾": ")", "ⁿ": "n", "ⁱ": "i"})
_SUBSCRIPTS = str.maketrans({"₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9", "₊": "+", "₋": "-", "₌": "=", "₍": "(", "₎": ")"})


class LatexError(ValueError):
	pass


# ====================================================================== léxico
_TOKEN = re.compile(
	r"(?P<cmd>\\(?:[A-Za-z]+\*?|.))"
	r"|(?P<num>\d+(?:\.\d+)?|\.\d+)"
	r"|(?P<ws>\s+)"
	r"|(?P<comment>(?<!\\)%[^\n]*)"
	r"|(?P<ch>.)",
	re.DOTALL,
)


def _tokenize(src: str) -> list[tuple[str, str]]:
	out: list[tuple[str, str]] = []
	for m in _TOKEN.finditer(src):
		kind = m.lastgroup
		val = m.group(0)
		if kind == "comment":
			continue
		if kind == "ws":
			out.append(("ws", val))
			continue
		out.append((kind, val))
	return out


def stripDelimiters(src: str) -> str:
	s = src.strip()
	for a, b in (("$$", "$$"), ("\\[", "\\]"), ("\\(", "\\)"), ("$", "$")):
		if s.startswith(a) and s.endswith(b) and len(s) > len(a) + len(b) - 1:
			return s[len(a) : len(s) - len(b)].strip()
	m = re.match(r"^\\begin\{(equation|equation\*|displaymath|math)\}(.*)\\end\{\1\}$", s, re.DOTALL)
	if m:
		return m.group(2).strip()
	return s


def looksLikeLatex(text: str) -> bool:
	t = text.strip()
	if not t:
		return False
	if re.search(r"\\[A-Za-z]+", t) or re.search(r"[\^_]\{?", t):
		return True
	return t.startswith("$") and t.endswith("$")


# ====================================================================== analizador
class _Parser:
	def __init__(self, src: str) -> None:
		self.toks = _tokenize(src)
		self.pos = 0

	# ----------------------------------------------------------- utilidades
	def peek(self, skipWs: bool = True) -> tuple[str, str] | None:
		p = self.pos
		while p < len(self.toks) and skipWs and self.toks[p][0] == "ws":
			p += 1
		return self.toks[p] if p < len(self.toks) else None

	def next(self, skipWs: bool = True) -> tuple[str, str] | None:
		while self.pos < len(self.toks) and skipWs and self.toks[self.pos][0] == "ws":
			self.pos += 1
		if self.pos >= len(self.toks):
			return None
		t = self.toks[self.pos]
		self.pos += 1
		return t

	def skipWs(self) -> None:
		while self.pos < len(self.toks) and self.toks[self.pos][0] == "ws":
			self.pos += 1

	def readRawGroup(self) -> str:
		"""Lee ``{...}`` como texto sin analizar (para \\text, \\begin...)."""
		self.skipWs()
		t = self.next()
		if t is None:
			return ""
		if t[1] != "{":
			return t[1]
		depth = 1
		out = []
		while self.pos < len(self.toks):
			kind, val = self.toks[self.pos]
			self.pos += 1
			if val == "{" and kind == "ch":
				depth += 1
			elif val == "}" and kind == "ch":
				depth -= 1
				if depth == 0:
					break
			out.append(val)
		return "".join(out)

	def readOptional(self) -> list[MathNode] | None:
		t = self.peek()
		if t is None or t[1] != "[":
			return None
		self.next()
		items = self.parseList(stop={"]"})
		t = self.next()
		return items

	def readArg(self) -> MathNode:
		"""Un argumento: grupo ``{...}`` o un único símbolo."""
		self.skipWs()
		t = self.peek()
		if t is None:
			return MathNode("mrow")
		if t[1] == "{" and t[0] == "ch":
			self.next()
			items = self.parseList(stop={"}"})
			self.next()
			return _row(items)
		atom = self.parseAtom()
		return atom if atom is not None else MathNode("mrow")

	# ----------------------------------------------------------- gramática
	def parseList(self, stop: set[str]) -> list[MathNode]:
		items: list[MathNode] = []
		while True:
			t = self.peek()
			if t is None:
				break
			kind, val = t
			if val in stop and (kind == "ch" or kind == "cmd"):
				break
			if kind == "cmd" and val in ("\\right", "\\end") and ("\\right" in stop or "\\end" in stop):
				break
			if kind == "cmd" and val == "\\\\" and "\\\\" in stop:
				break
			if kind == "ch" and val == "&" and "&" in stop:
				break
			atom = self.parseAtom()
			if atom is None:
				continue
			atom = self.parseScripts(atom)
			if isinstance(atom, list):
				items.extend(atom)
			else:
				items.append(atom)
		return items

	def parseScripts(self, base: MathNode):
		sub = sup = None
		primes = 0
		while True:
			t = self.peek()
			if t is None:
				break
			if t[1] == "'" and t[0] == "ch":
				self.next()
				primes += 1
				continue
			if t[1] == "^" and t[0] == "ch" and sup is None:
				self.next()
				sup = self.readArg()
				continue
			if t[1] == "_" and t[0] == "ch" and sub is None:
				self.next()
				sub = self.readArg()
				continue
			break
		if sup is not None and sup.tag == "mo" and sup.text == "∘":
			sup = mo("°")
		if primes:
			p = mo("′″‴⁗"[min(primes, 4) - 1])
			sup = p if sup is None else _row([p, sup])
		if sub is None and sup is None:
			return base
		limits = base.attrs.pop("_limits", "") == "1"
		if limits:
			if sub is not None and sup is not None:
				return MathNode("munderover", children=[base, sub, sup])
			if sub is not None:
				return MathNode("munder", children=[base, sub])
			return MathNode("mover", children=[base, sup])
		if sub is not None and sup is not None:
			return MathNode("msubsup", children=[base, sub, sup])
		if sub is not None:
			return MathNode("msub", children=[base, sub])
		return MathNode("msup", children=[base, sup])

	def parseAtom(self) -> MathNode | None:
		t = self.next()
		if t is None:
			return None
		kind, val = t
		if kind == "num":
			return mn(val)
		if kind == "ch":
			if val == "{":
				items = self.parseList(stop={"}"})
				self.next()
				if len(items) == 1 and items[0].tag == "mo" and items[0].text in (",", "."):
					# 3{,}5: separador decimal.
					items[0].attrs["_decimal"] = "1"
					return items[0]
				return _row(items, keep=True)
			if val == "}":
				return None
			if val in "^_":
				# Script sin base: base vacía.
				self.pos -= 1
				return MathNode("mrow")
			if val == "~":
				return MathNode("mspace", {"width": "0.25em"})
			if val.isalpha():
				return mi(val)
			if val.isdigit():
				return mn(val)
			sup = val.translate(_SUPERSCRIPTS)
			if sup != val:
				return MathNode("msup", children=[MathNode("mrow"), mn(sup) if sup.isdigit() else mi(sup)])
			return mo(val)
		# Órdenes.
		name = val[1:]
		if name in IGNORED:
			if name in ("label", "tag"):
				self.readRawGroup()
			elif name in ("phantom", "hphantom", "vphantom"):
				self.readArg()
			return None
		if name == "left":
			return self.parseLeftRight()
		if name in ("right", "middle"):
			d = self._readDelimiter()
			return mo(d) if d else None
		if name in SPACES:
			return MathNode("mspace", {"width": SPACES[name]})
		if name in ("frac", "dfrac", "tfrac", "cfrac"):
			num = self.readArg()
			den = self.readArg()
			return MathNode("mfrac", children=[num, den])
		if name in ("binom", "dbinom", "tbinom"):
			top = self.readArg()
			bot = self.readArg()
			frac = MathNode("mfrac", {"linethickness": "0"}, [top, bot])
			return MathNode("mrow", {"_open": "(", "_close": ")"}, [mo("("), frac, mo(")")])
		if name == "sqrt":
			opt = self.readOptional()
			body = self.readArg()
			if opt:
				return MathNode("mroot", children=[body, _row(opt)])
			return MathNode("msqrt", children=[body])
		if name in GREEK:
			return mi(GREEK[name])
		if name in IDENT_SYMBOLS:
			return mi(IDENT_SYMBOLS[name]) if name not in ("degree", "prime") else mo(IDENT_SYMBOLS[name])
		if name in OPERATORS:
			return mo(OPERATORS[name])
		if name in BIG_OPERATORS:
			node = mo(BIG_OPERATORS[name])
			node.attrs["_limits"] = "1"
			self._applyLimitsModifier(node)
			return node
		if name in INTEGRALS:
			node = mo(INTEGRALS[name])
			self._applyLimitsModifier(node)
			return node
		if name in FUNCTION_NAMES:
			return mi(name)
		if name in LIMIT_FUNCTIONS:
			node = mi({"limsup": "lim sup", "liminf": "lim inf"}.get(name, name))
			node.attrs["_limits"] = "1"
			return node
		if name in ("operatorname", "operatorname*"):
			txt = self.readRawGroup().strip()
			node = mi(txt)
			if name.endswith("*"):
				node.attrs["_limits"] = "1"
			return node
		if name in TEXT_COMMANDS:
			return mtext(self.readRawGroup())
		if name in FONTS:
			arg = self.readArg()
			variant = FONTS[name]
			if variant == "normal" and arg.tag == "mrow" and arg.children and all(c.tag == "mi" and len(c.text) == 1 for c in arg.children):
				# \mathrm{cm}: una sola palabra (unidad o nombre).
				arg = mi("".join(c.text for c in arg.children))
			for n in arg.iter():
				if n.tag == "mi":
					n.attrs["mathvariant"] = variant
				elif n.tag == "mn" and variant == "bold":
					n.attrs["mathvariant"] = variant
			return arg
		if name in ACCENTS:
			arg = self.readArg()
			acc = mo(ACCENTS[name])
			return MathNode("mover", {"accent": "true"}, [arg, acc])
		if name in UNDER_ACCENTS:
			arg = self.readArg()
			return MathNode("munder", {"accentunder": "true"}, [arg, mo(UNDER_ACCENTS[name])])
		if name in ("overset", "stackrel"):
			top = self.readArg()
			base = self.readArg()
			return MathNode("mover", children=[base, top])
		if name == "underset":
			bot = self.readArg()
			base = self.readArg()
			return MathNode("munder", children=[base, bot])
		if name in ("boxed", "fbox"):
			return MathNode("menclose", {"notation": "box"}, [self.readArg()])
		if name in ("cancel", "bcancel", "xcancel", "sout"):
			notation = {"cancel": "updiagonalstrike", "bcancel": "downdiagonalstrike", "xcancel": "updiagonalstrike downdiagonalstrike", "sout": "horizontalstrike"}[name]
			return MathNode("menclose", {"notation": notation}, [self.readArg()])
		if name == "pmod":
			arg = self.readArg()
			return MathNode("mrow", {"_open": "(", "_close": ")"}, [mo("("), _row([mi("mod"), arg]), mo(")")])
		if name in ("bmod", "mod"):
			return mi("mod")
		if name == "not":
			nxt = self.parseAtom()
			if nxt is not None and nxt.tag == "mo":
				neg = {"=": "≠", "∈": "∉", "⊂": "⊄", "⊆": "⊈", "<": "≮", ">": "≯", "≤": "≰", "≥": "≱", "∃": "∄", "|": "∤", "≡": "≢", "∼": "≁"}
				return mo(neg.get(nxt.text, nxt.text + "̸"))
			return nxt
		if name == "begin":
			env = self.readRawGroup().strip()
			return self.parseEnvironment(env)
		if name == "end":
			self.readRawGroup()
			return None
		if name in ("\\", "newline", "cr"):
			return None
		if name in ("color", "textcolor"):
			self.readRawGroup()
			return self.readArg() if name == "textcolor" else None
		if name in ("mathop",):
			return self.readArg()
		if name == "lbrack":
			return mo("[")
		if name == "rbrack":
			return mo("]")
		if len(name) == 1 and not name.isalpha():
			return mo(name)
		# Orden desconocida: se conserva su nombre.
		return mi(name)

	def _applyLimitsModifier(self, node: MathNode) -> None:
		t = self.peek()
		if t and t[0] == "cmd" and t[1] in ("\\limits", "\\nolimits"):
			self.next()
			if t[1] == "\\limits":
				node.attrs["_limits"] = "1"
			else:
				node.attrs.pop("_limits", None)

	def _readDelimiter(self) -> str:
		t = self.next()
		if t is None:
			return ""
		kind, val = t
		if kind == "cmd":
			name = val[1:]
			if name in OPERATORS:
				return OPERATORS[name]
			return {"{": "{", "}": "}", "|": "‖"}.get(name, "")
		if val == ".":
			return ""
		return val

	def parseLeftRight(self) -> MathNode:
		open_ = self._readDelimiter()
		items: list[MathNode] = []
		while True:
			items.extend(self.parseList(stop={"\\right", "\\middle"}))
			t = self.peek()
			if t is None:
				close = ""
				break
			self.next()
			if t[1] == "\\middle":
				d = self._readDelimiter()
				items.append(mo(d or "|"))
				continue
			close = self._readDelimiter()
			break
		content = _row(items)
		parts = []
		if open_:
			parts.append(mo(open_))
		parts.append(content)
		if close:
			parts.append(mo(close))
		if open_ or close:
			attrs = {"_open": open_, "_close": close} if open_ else {}
			if not open_:
				return MathNode("mrow", children=parts)
			return MathNode("mrow", attrs, parts)
		return content

	def parseEnvironment(self, env: str) -> MathNode:
		base = env.rstrip("*")
		if base == "array" or base in ("tabular",):
			self.readRawGroup()  # especificación de columnas
		rows: list[list[MathNode]] = []
		cells: list[MathNode] = []
		while True:
			items = self.parseList(stop={"&", "\\\\", "\\end"})
			cells.append(_row(items))
			t = self.next()
			if t is None:
				rows.append(cells)
				break
			if t[1] == "&":
				continue
			if t[1] == "\\\\":
				rows.append(cells)
				cells = []
				continue
			if t[1] == "\\end":
				self.readRawGroup()
				rows.append(cells)
				break
		rows = [r for r in rows if not (len(r) == 1 and r[0].tag == "mrow" and not r[0].children)]
		table = MathNode("mtable", children=[MathNode("mtr", children=[MathNode("mtd", children=[c]) for c in r]) for r in rows])
		if base in MATRIX_ENVS:
			o, c = MATRIX_ENVS[base]
			if o:
				return MathNode("mrow", {"_open": o, "_close": c}, [mo(o), table, mo(c)])
			return table
		if base in ("cases", "dcases"):
			return MathNode("mrow", children=[mo("{"), table])
		if base == "rcases":
			return MathNode("mrow", children=[table, mo("}")])
		return table


def _mergeDecimals(items: list[MathNode]) -> list[MathNode]:
	out: list[MathNode] = []
	i = 0
	while i < len(items):
		n = items[i]
		if n.tag == "mo" and n.attrs.get("_decimal") and out and out[-1].tag == "mn" and i + 1 < len(items) and items[i + 1].tag == "mn":
			out[-1] = mn(out[-1].text + n.text + items[i + 1].text)
			i += 2
			continue
		n.attrs.pop("_decimal", None)
		out.append(n)
		i += 1
	return out


def _row(items: list[MathNode], keep: bool = False) -> MathNode:
	items = _insertFunctionApply(_mergeDecimals(items))
	if len(items) == 1 and not keep:
		return items[0]
	if len(items) == 1 and items[0].tag != "mrow":
		return items[0]
	return MathNode("mrow", children=items)


def _isFunctionName(node: MathNode) -> bool:
	base = node
	while base.tag in ("msub", "msup", "msubsup", "munder", "mover", "munderover") and base.children:
		base = base.children[0]
	return base.tag == "mi" and (base.text in FUNCTION_NAMES or base.text in LIMIT_FUNCTIONS or base.text in ("lim sup", "lim inf"))


def _insertFunctionApply(items: list[MathNode]) -> list[MathNode]:
	out: list[MathNode] = []
	for i, n in enumerate(items):
		out.append(n)
		if _isFunctionName(n) and i + 1 < len(items):
			nxt = items[i + 1]
			if not (nxt.tag == "mo" and nxt.text not in OPEN_FENCES and nxt.text not in ("|", "−", "∂")):
				lim = n.tag in ("munder", "munderover") or (n.tag == "mi" and n.text in LIMIT_FUNCTIONS)
				if not lim:
					out.append(mo(FUNCTION_APPLY))
	return out


def latexToTree(src: str) -> MathNode:
	"""Convierte LaTeX en un elemento ``math`` (sin normalizar)."""
	src = stripDelimiters(src)
	p = _Parser(src)
	items = p.parseList(stop=set())
	root = MathNode("math")
	root.append(_row(items) if items else MathNode("mrow"))
	for n in root.iter():
		n.attrs.pop("_limits", None)
	return root


def latexToMathML(src: str) -> str:
	tree = latexToTree(src)
	tree.attrs["alttext"] = stripDelimiters(src)
	return tree.toMathML()


def linearTextToMathML(text: str) -> str:
	"""Texto lineal con superíndices Unicode (x² + 1) a MathML."""
	t = re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ]+", lambda m: "^{" + m.group(0).translate(_SUPERSCRIPTS) + "}", text)
	t = re.sub(r"[₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎]+", lambda m: "_{" + m.group(0).translate(_SUBSCRIPTS) + "}", t)
	t = t.replace("√", "\\sqrt ")
	return latexToMathML(t)


# ====================================================================== MathML → LaTeX
_REV_GREEK = {v: k for k, v in GREEK.items()}
_REV_GREEK["ε"] = "varepsilon"
_REV_GREEK["ϵ"] = "epsilon"
_REV_GREEK["φ"] = "varphi"
_REV_GREEK["ϕ"] = "phi"
_REV_OPS: dict[str, str] = {}
for _k, _v in OPERATORS.items():
	if len(_k) > 1 and _v not in _REV_OPS:
		_REV_OPS[_v] = _k
_REV_OPS.update({"−": "-", "∗": "*", "{": "\\{", "}": "\\}", "%": "\\%", "#": "\\#", "&": "\\&", "|": "|", "‖": "\\|", "≤": "\\leq", "≥": "\\geq", "→": "\\to", "…": "\\ldots", "′": "'", "″": "''", "‴": "'''", "°": "^\\circ", "∘": "\\circ"})
for _k in list(_REV_OPS):
	if _REV_OPS[_k] and _REV_OPS[_k][0].isalpha():
		_REV_OPS[_k] = "\\" + _REV_OPS[_k]
_REV_IDENT = {v: k for k, v in IDENT_SYMBOLS.items()}
_REV_BIG = {v: k for k, v in BIG_OPERATORS.items()}
_REV_BIG.update({v: k for k, v in INTEGRALS.items()})
_REV_ACCENT = {"^": "hat", "¯": "overline", "→": "vec", "~": "tilde", "˙": "dot", "¨": "ddot", "ˇ": "check", "˘": "breve", "´": "acute", "`": "grave", "˚": "mathring", "⏞": "overbrace", "‾": "overline", "⃗": "vec"}
_REV_UNDER = {"_": "underline", "¯": "underline", "⏟": "underbrace"}
_DOUBLE_STRUCK = {"ℕ": "N", "ℤ": "Z", "ℚ": "Q", "ℝ": "R", "ℂ": "C", "ℙ": "P", "ℍ": "H"}


def _texGroup(s: str) -> str:
	if len(s) == 1 or re.fullmatch(r"\\[A-Za-z]+", s) or re.fullmatch(r"\d", s):
		return s
	return "{" + s + "}"


def _texToken(node: MathNode) -> str:
	t = node.text
	if node.tag == "mn":
		return t
	if node.tag == "mtext":
		return "\\text{" + t + "}"
	if node.tag == "mspace":
		return "\\,"
	if node.tag == "mo":
		if t in ("⁡", "⁢", "⁣", "⁤"):
			return ""
		if t in _REV_BIG:
			return "\\" + _REV_BIG[t]
		if t in _REV_OPS:
			return _REV_OPS[t]
		return t
	if node.tag == "mi":
		variant = node.get("mathvariant")
		if t in _DOUBLE_STRUCK:
			return "\\mathbb{" + _DOUBLE_STRUCK[t] + "}"
		if t in _REV_GREEK:
			out = "\\" + _REV_GREEK[t]
		elif t in _REV_IDENT:
			out = "\\" + _REV_IDENT[t]
		elif t in FUNCTION_NAMES and t not in ("sen", "tg", "arcsen", "arctg", "senh", "tgh", "mcd", "mcm", "lcm", "sgn"):
			out = "\\" + t
		elif t in LIMIT_FUNCTIONS:
			out = "\\" + t
		elif t in ("lim sup", "lim inf"):
			out = "\\" + t.replace(" ", "")
		elif len(t) > 1 and t.isalpha() and (variant == "normal" or "unit" in node.get("class", "").lower()):
			return "\\mathrm{" + t + "}"
		elif len(t) > 1 and t.isalpha():
			out = "\\operatorname{" + t + "}"
		else:
			out = t
		if variant == "bold":
			return "\\mathbf{" + out + "}"
		if variant == "double-struck":
			return "\\mathbb{" + out + "}"
		if variant in ("script", "bold-script"):
			return "\\mathcal{" + out + "}"
		if variant == "fraktur":
			return "\\mathfrak{" + out + "}"
		if variant == "normal" and len(t) == 1 and t.isalpha():
			return "\\mathrm{" + out + "}"
		return out
	return t


def toLatex(node: MathNode) -> str:
	"""Serializa un árbol normalizado como LaTeX."""
	tag = node.tag
	if node.isToken:
		return _texToken(node)
	k = node.children
	if tag == "math":
		return toLatex(k[0]) if k else ""
	if tag == "mrow":
		if node.isFenced and node.fenceContent is not None and node.fenceContent.tag == "mtable":
			return _texTable(node.fenceContent, node.get("_open"), node.get("_close"))
		if node.isFenced and node.fenceContent is not None and node.fenceContent.tag == "mfrac" and node.fenceContent.get("linethickness") == "0":
			f = node.fenceContent
			return "\\binom{" + toLatex(f.children[0]) + "}{" + toLatex(f.children[1]) + "}"
		if len(k) == 2 and k[0].isMo("{") and k[1].tag == "mtable":
			return _texTable(k[1], "{", "")
		parts = []
		prev = ""
		for c in k:
			s = toLatex(c)
			if not s:
				continue
			if prev and (re.search(r"\\[A-Za-z]+$", prev) or re.search(r"[\^_][A-Za-z0-9]$", prev)) and re.match(r"[A-Za-z0-9]", s):
				parts.append(" ")
			parts.append(s)
			prev = s
		return "".join(parts)
	if tag == "mfrac":
		if node.get("linethickness") == "0":
			return "\\binom{" + toLatex(k[0]) + "}{" + toLatex(k[1]) + "}"
		return "\\frac{" + toLatex(k[0]) + "}{" + toLatex(k[1]) + "}"
	if tag == "msqrt":
		return "\\sqrt{" + toLatex(k[0]) + "}"
	if tag == "mroot":
		return "\\sqrt[" + toLatex(k[1]) + "]{" + toLatex(k[0]) + "}"
	if tag in ("msup", "msub", "msubsup"):
		base = toLatex(k[0])
		if k[0].tag in ("mrow",) and not k[0].isFenced or k[0].tag in ("mfrac", "msup", "msub", "msubsup"):
			base = "{" + base + "}"
		if tag == "msup":
			sup = k[1]
			if sup.tag == "mo" and sup.text in ("′", "″", "‴", "°"):
				return base + _texToken(sup)
			return base + "^" + _texGroup(toLatex(sup))
		if tag == "msub":
			return base + "_" + _texGroup(toLatex(k[1]))
		return base + "_" + _texGroup(toLatex(k[1])) + "^" + _texGroup(toLatex(k[2]))
	if tag in ("munder", "mover", "munderover"):
		base = k[0]
		if tag == "mover" and k[1].tag == "mo" and k[1].text in _REV_ACCENT:
			return "\\" + _REV_ACCENT[k[1].text] + "{" + toLatex(base) + "}"
		if tag == "munder" and k[1].tag == "mo" and k[1].text in _REV_UNDER:
			return "\\" + _REV_UNDER[k[1].text] + "{" + toLatex(base) + "}"
		isOp = (base.tag == "mo" and base.text in _REV_BIG) or (base.tag == "mi" and (base.text in LIMIT_FUNCTIONS or base.text in ("lim sup", "lim inf")))
		b = toLatex(base)
		if isOp:
			if tag == "munder":
				return b + "_" + _texGroup(toLatex(k[1]))
			if tag == "mover":
				return b + "^" + _texGroup(toLatex(k[1]))
			return b + "_" + _texGroup(toLatex(k[1])) + "^" + _texGroup(toLatex(k[2]))
		if tag == "munder":
			return "\\underset{" + toLatex(k[1]) + "}{" + b + "}"
		if tag == "mover":
			return "\\overset{" + toLatex(k[1]) + "}{" + b + "}"
		return "\\overset{" + toLatex(k[2]) + "}{\\underset{" + toLatex(k[1]) + "}{" + b + "}}"
	if tag == "mtable":
		return _texTable(node, "", "")
	if tag == "menclose":
		notation = node.get("notation", "longdiv")
		inner = toLatex(k[0]) if k else ""
		if "box" in notation:
			return "\\boxed{" + inner + "}"
		if "strike" in notation:
			return "\\cancel{" + inner + "}"
		return inner
	if tag == "mmultiscripts":
		return _texMultiscripts(node)
	if tag in ("mtr", "mtd", "merror"):
		return " ".join(toLatex(c) for c in k)
	return "".join(toLatex(c) for c in k)


def _texTable(table: MathNode, open_: str, close: str) -> str:
	env = {("(", ")"): "pmatrix", ("[", "]"): "bmatrix", ("{", "}"): "Bmatrix", ("|", "|"): "vmatrix", ("‖", "‖"): "Vmatrix", ("{", ""): "cases"}.get((open_, close), "matrix")
	rows = []
	for r in table.children:
		cells = [toLatex(c) for c in r.children if c.tag in ("mtd",)] or [toLatex(r)]
		rows.append(" & ".join(cells))
	body = " \\\\ ".join(rows)
	return "\\begin{" + env + "} " + body + " \\end{" + env + "}"


def _texMultiscripts(node: MathNode) -> str:
	k = node.children
	base = toLatex(k[0]) if k else ""
	post: list[MathNode] = []
	pre: list[MathNode] = []
	target = post
	for c in k[1:]:
		if c.tag == "mprescripts":
			target = pre
			continue
		target.append(c)

	def scripts(lst: list[MathNode]) -> str:
		out = ""
		for i in range(0, len(lst) - 1, 2):
			sub, sup = lst[i], lst[i + 1]
			if sub.tag != "none":
				out += "_" + _texGroup(toLatex(sub))
			if sup.tag != "none":
				out += "^" + _texGroup(toLatex(sup))
		return out

	preTex = scripts(pre)
	return ("{}" + preTex if preTex else "") + _texGroup(base) + scripts(post)
