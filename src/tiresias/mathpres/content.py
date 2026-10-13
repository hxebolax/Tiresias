"""Conversión de MathML de contenido (básico) a MathML de presentación.

Así la voz, el braille y la navegación solo trabajan con presentación. Se
cubren las operaciones habituales: aritmética, potencias y raíces,
relaciones, lógica, conjuntos, funciones elementales, derivadas, integrales,
sumatorios, límites, vectores, matrices e intervalos.
"""

from __future__ import annotations

from .mathml import MathNode, mi, mn, mo, mrow

_INFIX = {
	"plus": "+",
	"eq": "=",
	"neq": "≠",
	"lt": "<",
	"gt": ">",
	"leq": "≤",
	"geq": "≥",
	"approx": "≈",
	"equivalent": "≡",
	"and": "∧",
	"or": "∨",
	"xor": "⊻",
	"implies": "⇒",
	"in": "∈",
	"notin": "∉",
	"subset": "⊆",
	"prsubset": "⊂",
	"notsubset": "⊈",
	"notprsubset": "⊄",
	"union": "∪",
	"intersect": "∩",
	"setdiff": "∖",
	"compose": "∘",
	"factorof": "|",
	"tendsto": "→",
	"cartesianproduct": "×",
	"vectorproduct": "×",
	"scalarproduct": "·",
	"outerproduct": "⊗",
	"rem": "mod",
}

_FUNCTIONS = {
	"sin": "sin",
	"cos": "cos",
	"tan": "tan",
	"cot": "cot",
	"sec": "sec",
	"csc": "csc",
	"arcsin": "arcsin",
	"arccos": "arccos",
	"arctan": "arctan",
	"sinh": "sinh",
	"cosh": "cosh",
	"tanh": "tanh",
	"exp": "exp",
	"ln": "ln",
	"log": "log",
	"max": "max",
	"min": "min",
	"gcd": "gcd",
	"lcm": "lcm",
	"arg": "arg",
	"real": "Re",
	"imaginary": "Im",
	"determinant": "det",
	"card": "#",
	"inverse": "inverse",
}


def _txt(node: MathNode) -> str:
	return node.text.strip()


def _opName(node: MathNode) -> str:
	if node.tag == "csymbol":
		return _txt(node) or node.get("cd", "")
	if node.tag == "ci":
		return ""
	return node.tag


def _wrap(node: MathNode) -> MathNode:
	"""Pone entre paréntesis un argumento compuesto."""
	if node.tag in ("mi", "mn", "msub", "msup", "mfrac", "msqrt", "mroot") or node.isFenced:
		return node
	return MathNode("mrow", {"_open": "(", "_close": ")"}, [mo("("), node, mo(")")])


def _qualifiers(apply_: MathNode) -> tuple[dict[str, MathNode], list[MathNode]]:
	quals: dict[str, MathNode] = {}
	args: list[MathNode] = []
	for c in apply_.children[1:]:
		if c.tag in ("bvar", "lowlimit", "uplimit", "degree", "logbase", "condition", "domainofapplication", "momentabout"):
			inner = c.children[0] if c.children else MathNode("mrow")
			quals[c.tag] = toPresentation(inner)
			if c.tag == "bvar":
				deg = next((d for d in c.children if d.tag == "degree"), None)
				if deg is not None and deg.children:
					quals["bvardegree"] = toPresentation(deg.children[0])
		elif c.tag == "interval":
			kids = [toPresentation(k) for k in c.children]
			if len(kids) == 2:
				quals["lowlimit"], quals["uplimit"] = kids
		else:
			args.append(toPresentation(c))
	return quals, args


def _join(args: list[MathNode], op: str) -> MathNode:
	out: list[MathNode] = []
	for i, a in enumerate(args):
		if i:
			out.append(mo(op))
		out.append(a)
	return mrow(*out) if len(out) != 1 else out[0]


def toPresentation(node: MathNode) -> MathNode:
	tag = node.tag
	if tag == "ci":
		if node.children:
			return toPresentation(node.children[0])
		return mi(_txt(node))
	if tag == "cn":
		t = node.get("type", "")
		parts = [p.strip() for p in node.text.split("\n") if p.strip()]
		if node.children and any(c.tag == "sep" for c in node.children) or t in ("rational", "e-notation", "complex-cartesian"):
			txt = node.text.strip().split()
			if len(txt) >= 2:
				a, b = txt[0], txt[1]
				if t == "rational":
					return MathNode("mfrac", children=[mn(a), mn(b)])
				if t == "e-notation":
					return mrow(mn(a), mo("×"), MathNode("msup", children=[mn("10"), mn(b)]))
				if t == "complex-cartesian":
					return mrow(mn(a), mo("+"), mn(b), mo("⁢"), mi("i"))
		return mn(parts[0] if parts else _txt(node))
	if tag == "csymbol":
		return mi(_txt(node))
	if tag in ("set", "list", "vector"):
		kids = [toPresentation(c) for c in node.children if c.tag not in ("bvar", "condition")]
		cond = next((c for c in node.children if c.tag == "condition"), None)
		bvar = next((c for c in node.children if c.tag == "bvar"), None)
		o, c_ = ("{", "}") if tag == "set" else ("(", ")")
		if cond is not None and bvar is not None and bvar.children:
			inner = mrow(toPresentation(bvar.children[0]), mo("|"), toPresentation(cond.children[0]) if cond.children else MathNode("mrow"))
		else:
			inner = _join(kids, ",") if kids else MathNode("mrow")
		if tag == "vector" and kids:
			table = MathNode("mtable", children=[MathNode("mtr", children=[MathNode("mtd", children=[k])]) for k in kids])
			inner = table
		return MathNode("mrow", {"_open": o, "_close": c_}, [mo(o), inner, mo(c_)])
	if tag == "matrix":
		rows = []
		for r in node.children:
			if r.tag == "matrixrow":
				rows.append(MathNode("mtr", children=[MathNode("mtd", children=[toPresentation(c)]) for c in r.children]))
		return MathNode("mrow", {"_open": "(", "_close": ")"}, [mo("("), MathNode("mtable", children=rows), mo(")")])
	if tag == "interval":
		closure = node.get("closure", "closed")
		o = "[" if closure in ("closed", "closed-open") else "("
		c_ = "]" if closure in ("closed", "open-closed") else ")"
		kids = [toPresentation(c) for c in node.children]
		return MathNode("mrow", {"_open": o, "_close": c_}, [mo(o), _join(kids, ","), mo(c_)])
	if tag == "piecewise":
		rows = []
		for p in node.children:
			if p.tag == "piece" and len(p.children) >= 2:
				rows.append(MathNode("mtr", children=[MathNode("mtd", children=[toPresentation(p.children[0])]), MathNode("mtd", children=[mrow(MathNode("mtext", text="si "), toPresentation(p.children[1]))])]))
			elif p.tag == "otherwise" and p.children:
				rows.append(MathNode("mtr", children=[MathNode("mtd", children=[toPresentation(p.children[0])]), MathNode("mtd", children=[MathNode("mtext", text="en otro caso")])]))
		return mrow(mo("{"), MathNode("mtable", children=rows))
	if tag in ("pi", "exponentiale", "imaginaryi", "infinity", "emptyset", "true", "false", "eulergamma", "notanumber", "naturalnumbers", "integers", "rationals", "reals", "complexes", "primes"):
		return mi(
			{
				"pi": "π",
				"exponentiale": "e",
				"imaginaryi": "i",
				"infinity": "∞",
				"emptyset": "∅",
				"true": "verdadero",
				"false": "falso",
				"eulergamma": "γ",
				"notanumber": "NaN",
				"naturalnumbers": "ℕ",
				"integers": "ℤ",
				"rationals": "ℚ",
				"reals": "ℝ",
				"complexes": "ℂ",
				"primes": "ℙ",
			}[tag]
		)
	if tag in ("apply", "bind"):
		if not node.children:
			return MathNode("mrow")
		head = node.children[0]
		name = _opName(head)
		quals, args = _qualifiers(node)
		return _apply(name, head, quals, args)
	if tag in ("math", "mrow", "semantics"):
		return MathNode(tag, node.attrs, [toPresentation(c) for c in node.children], node.text)
	if node.isToken:
		return node
	# Elemento de presentación dentro de contenido u operador suelto.
	if not node.children:
		return mi(tag)
	return MathNode(tag, node.attrs, [toPresentation(c) for c in node.children], node.text)


def _apply(name: str, head: MathNode, quals: dict, args: list[MathNode]) -> MathNode:
	if name in _INFIX and name != "plus":
		return _join(args, _INFIX[name])
	if name == "plus":
		out: list[MathNode] = []
		for i, a in enumerate(args):
			if i:
				out.append(mo("+"))
			out.append(a)
		return mrow(*out) if len(out) != 1 else out[0]
	if name == "minus":
		if len(args) == 1:
			return mrow(mo("−"), _wrap(args[0]))
		return _join(args, "−")
	if name == "times":
		out = []
		for i, a in enumerate(args):
			if i:
				simple = a.tag in ("mi",) and out and out[-1].tag in ("mn", "mi")
				out.append(mo("⁢" if simple else "·"))
			out.append(_wrap(a) if a.tag == "mrow" and not a.isFenced else a)
		return mrow(*out) if len(out) != 1 else out[0]
	if name in ("divide", "quotient"):
		return MathNode("mfrac", children=args[:2] if len(args) >= 2 else args + [MathNode("mrow")])
	if name == "power":
		base = args[0] if args else MathNode("mrow")
		exp = args[1] if len(args) > 1 else MathNode("mrow")
		return MathNode("msup", children=[_wrap(base) if base.tag == "mrow" else base, exp])
	if name == "root":
		deg = quals.get("degree")
		radicand = args[0] if args else MathNode("mrow")
		if deg is None or (deg.tag == "mn" and deg.text == "2"):
			return MathNode("msqrt", children=[radicand])
		return MathNode("mroot", children=[radicand, deg])
	if name == "not":
		return mrow(mo("¬"), _wrap(args[0]) if args else MathNode("mrow"))
	if name == "abs":
		return MathNode("mrow", {"_open": "|", "_close": "|"}, [mo("|"), args[0] if args else MathNode("mrow"), mo("|")])
	if name == "floor":
		return MathNode("mrow", {"_open": "⌊", "_close": "⌋"}, [mo("⌊"), args[0] if args else MathNode("mrow"), mo("⌋")])
	if name == "ceiling":
		return MathNode("mrow", {"_open": "⌈", "_close": "⌉"}, [mo("⌈"), args[0] if args else MathNode("mrow"), mo("⌉")])
	if name == "factorial":
		return mrow(_wrap(args[0]) if args else MathNode("mrow"), mo("!"))
	if name == "conjugate":
		return MathNode("mover", children=[args[0] if args else MathNode("mrow"), mo("¯")])
	if name == "transpose":
		return MathNode("msup", children=[args[0] if args else MathNode("mrow"), mi("T")])
	if name in ("log",) and "logbase" in quals:
		return mrow(MathNode("msub", children=[mi("log"), quals["logbase"]]), mo("⁡"), _wrap(args[0]) if args else MathNode("mrow"))
	if name in ("diff", "partialdiff"):
		d = "d" if name == "diff" else "∂"
		var = quals.get("bvar", mi("x"))
		deg = quals.get("bvardegree")
		dNum: MathNode = mi(d) if name == "diff" else mo(d)
		dDen: MathNode = mi(d) if name == "diff" else mo(d)
		if deg is not None:
			num = mrow(MathNode("msup", children=[dNum, deg]), args[0] if args else MathNode("mrow"))
			den = mrow(dDen, MathNode("msup", children=[var, deg.copy()]))
		else:
			num = mrow(dNum, args[0] if args else MathNode("mrow"))
			den = mrow(dDen, var)
		return MathNode("mfrac", children=[num, den])
	if name == "int":
		op = mo("∫")
		low, up = quals.get("lowlimit"), quals.get("uplimit")
		cond = quals.get("condition") or quals.get("domainofapplication")
		if low is not None and up is not None:
			op = MathNode("msubsup", children=[op, low, up])
		elif cond is not None:
			op = MathNode("msub", children=[op, cond])
		body = args[0] if args else MathNode("mrow")
		parts = [op, body]
		if "bvar" in quals:
			parts += [mo("⁢"), mi("d"), quals["bvar"]]
		return mrow(*parts)
	if name in ("sum", "product"):
		sym = mo("∑" if name == "sum" else "∏")
		low, up = quals.get("lowlimit"), quals.get("uplimit")
		var = quals.get("bvar")
		cond = quals.get("condition")
		if low is not None and var is not None:
			lower = mrow(var, mo("="), low)
		else:
			lower = cond
		if lower is not None and up is not None:
			op = MathNode("munderover", children=[sym, lower, up])
		elif lower is not None:
			op = MathNode("munder", children=[sym, lower])
		else:
			op = sym
		return mrow(op, args[0] if args else MathNode("mrow"))
	if name == "limit":
		var = quals.get("bvar", mi("x"))
		low = quals.get("lowlimit")
		cond = quals.get("condition")
		under = mrow(var, mo("→"), low) if low is not None else (cond or var)
		return mrow(MathNode("munder", children=[mi("lim"), under]), args[0] if args else MathNode("mrow"))
	if name in ("max", "min") and len(args) > 1:
		return mrow(mi(name), mo("⁡"), MathNode("mrow", {"_open": "{", "_close": "}"}, [mo("{"), _join(args, ","), mo("}")]))
	if name in _FUNCTIONS or head.tag in ("ci", "csymbol") or not name:
		fname = _FUNCTIONS.get(name, name)
		fnode = mi(fname) if fname else toPresentation(head)
		if not args:
			return fnode
		if len(args) == 1 and args[0].tag in ("mi", "mn") and name in _FUNCTIONS:
			return mrow(fnode, mo("⁡"), args[0])
		return mrow(fnode, mo("⁡"), MathNode("mrow", {"_open": "(", "_close": ")"}, [mo("("), _join(args, ","), mo(")")]))
	# Operador desconocido: nombre(args).
	return mrow(mi(name), mo("⁡"), MathNode("mrow", {"_open": "(", "_close": ")"}, [mo("("), _join(args, ","), mo(")")]))
