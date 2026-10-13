"""Conversión propia de ecuaciones de Office (OMML) a MathML.

Word guarda las ecuaciones en OMML (``m:oMath``). Este módulo convierte los
elementos habituales: texto, fracciones, raíces, índices, delimitadores,
operadores n-arios (sumatorios, integrales), funciones, límites, acentos,
barras, cuadros, agrupaciones, matrices y matrices de ecuaciones.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .mathml import FUNCTION_APPLY, MathNode, mi, mn, mo, mtext

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "{" + M_NS + "}"
W = "{" + W_NS + "}"

_OPERATOR_CHARS = set("+-−±∓×÷·⋅∗=≠<>≤≥≈≡∼∝∈∉⊂⊆⊃⊇∪∩∖∀∃¬∧∨⇒⇔→←↔↦∞∂∇!%°′″,;:|‖()[]{}⟨⟩⌊⌋⌈⌉/…⋯∘⊥∥∑∏∫∬∭∮")
_FUNC_NAMES = {"sin", "cos", "tan", "cot", "sec", "csc", "sen", "tg", "log", "ln", "exp", "lim", "max", "min", "det", "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh", "sup", "inf", "gcd", "mcd", "mcm"}


def _val(el: ET.Element | None, default: str = "") -> str:
	if el is None:
		return default
	return el.get(M + "val", el.get("val", default))


def _prop(el: ET.Element, prName: str, child: str) -> ET.Element | None:
	pr = el.find(M + prName)
	if pr is None:
		return None
	return pr.find(M + child)


def _row(nodes: list[MathNode]) -> MathNode:
	if len(nodes) == 1:
		return nodes[0]
	return MathNode("mrow", children=nodes)


def _container(el: ET.Element | None) -> MathNode:
	if el is None:
		return MathNode("mrow")
	return _row(_children(el))


def _children(el: ET.Element) -> list[MathNode]:
	out: list[MathNode] = []
	for c in el:
		res = _convert(c)
		if res is None:
			continue
		if isinstance(res, list):
			out.extend(res)
		else:
			out.append(res)
	return out


def _runText(el: ET.Element) -> str:
	parts = []
	for t in el.iter():
		if t.tag in (M + "t", W + "t") and t.text:
			parts.append(t.text)
	return "".join(parts)


def _tokenize(text: str, plain: bool) -> list[MathNode]:
	"""Divide el texto de un «run» en fichas MathML."""
	out: list[MathNode] = []
	if plain and text.strip() and not re.search(r"[\d" + re.escape("".join(_OPERATOR_CHARS)) + r"]", text):
		# Texto normal (m:sty="p"): nombre de función o palabra.
		word = text.strip()
		if word in _FUNC_NAMES or len(word) > 1:
			return [mi(word, mathvariant="normal") if word not in _FUNC_NAMES else mi(word)]
	for m in re.finditer(r"\d+(?:[.,]\d+)?|[A-Za-zÀ-ÿͰ-Ͽ]+|\s+|.", text):
		tok = m.group(0)
		if tok.isspace():
			continue
		if tok[0].isdigit():
			out.append(mn(tok))
		elif tok.isalpha():
			if tok in _FUNC_NAMES:
				out.append(mi(tok))
			else:
				out.extend(mi(ch) for ch in tok)
		else:
			out.append(mo(tok))
	return out


def _convert(el: ET.Element):
	tag = el.tag
	if not tag.startswith(M):
		if tag == W + "r":
			txt = _runText(el)
			return [mtext(txt)] if txt.strip() else None
		return None
	name = tag[len(M) :]
	if name.endswith("Pr") or name in ("ctrlPr", "argPr"):
		return None
	if name in ("oMathPara", "oMath", "e", "num", "den", "sub", "sup", "deg", "lim", "fName"):
		kids = _children(el)
		return kids
	if name == "r":
		txt = _runText(el)
		if not txt:
			return None
		rpr = el.find(M + "rPr")
		plain = False
		if rpr is not None:
			sty = rpr.find(M + "sty")
			plain = _val(sty) == "p" or rpr.find(M + "nor") is not None
			if rpr.find(M + "nor") is not None and not re.search(r"[\d=+\-]", txt):
				return [mtext(txt)]
		return _tokenize(txt, plain)
	if name == "f":
		ftype = _val(_prop(el, "fPr", "type"), "bar")
		num = _container(el.find(M + "num"))
		den = _container(el.find(M + "den"))
		if ftype == "lin":
			return MathNode("mrow", children=[num, mo("/"), den])
		frac = MathNode("mfrac", children=[num, den])
		if ftype == "noBar":
			frac.attrs["linethickness"] = "0"
		return frac
	if name == "rad":
		e = _container(el.find(M + "e"))
		degEl = el.find(M + "deg")
		hide = _val(_prop(el, "radPr", "degHide"), "0") in ("1", "on", "true")
		if degEl is None or hide or not _children(degEl):
			return MathNode("msqrt", children=[e])
		return MathNode("mroot", children=[e, _container(degEl)])
	if name == "sSup":
		return MathNode("msup", children=[_container(el.find(M + "e")), _container(el.find(M + "sup"))])
	if name == "sSub":
		return MathNode("msub", children=[_container(el.find(M + "e")), _container(el.find(M + "sub"))])
	if name == "sSubSup":
		return MathNode("msubsup", children=[_container(el.find(M + "e")), _container(el.find(M + "sub")), _container(el.find(M + "sup"))])
	if name == "sPre":
		return MathNode("mmultiscripts", children=[_container(el.find(M + "e")), MathNode("mprescripts"), _container(el.find(M + "sub")), _container(el.find(M + "sup"))])
	if name == "d":
		dpr = el.find(M + "dPr")
		beg = "("
		end = ")"
		sep = "|"
		if dpr is not None:
			b = dpr.find(M + "begChr")
			e_ = dpr.find(M + "endChr")
			s = dpr.find(M + "sepChr")
			if b is not None:
				beg = _val(b, "")
			if e_ is not None:
				end = _val(e_, "")
			if s is not None:
				sep = _val(s, "|")
		items: list[MathNode] = []
		for i, e in enumerate(el.findall(M + "e")):
			if i:
				items.append(mo(sep))
			items.append(_container(e))
		inner = _row(items) if items else MathNode("mrow")
		parts: list[MathNode] = []
		if beg:
			parts.append(mo(beg))
		parts.append(inner)
		if end:
			parts.append(mo(end))
		return MathNode("mrow", children=parts)
	if name == "nary":
		chrEl = _prop(el, "naryPr", "chr")
		op = _val(chrEl, "∫") if chrEl is not None else "∫"
		limLoc = _val(_prop(el, "naryPr", "limLoc"), "")
		subHide = _val(_prop(el, "naryPr", "subHide"), "0") in ("1", "on", "true")
		supHide = _val(_prop(el, "naryPr", "supHide"), "0") in ("1", "on", "true")
		sub = None if subHide else el.find(M + "sub")
		sup = None if supHide else el.find(M + "sup")
		sub = sub if sub is not None and _children(sub) else None
		sup = sup if sup is not None and _children(sup) else None
		under = limLoc == "undOvr" or (limLoc == "" and op not in ("∫", "∬", "∭", "∮"))
		opNode = mo(op)
		if sub is not None and sup is not None:
			head = MathNode("munderover" if under else "msubsup", children=[opNode, _container(sub), _container(sup)])
		elif sub is not None:
			head = MathNode("munder" if under else "msub", children=[opNode, _container(sub)])
		elif sup is not None:
			head = MathNode("mover" if under else "msup", children=[opNode, _container(sup)])
		else:
			head = opNode
		return [head, _container(el.find(M + "e"))]
	if name == "func":
		fname = _container(el.find(M + "fName"))
		return [fname, mo(FUNCTION_APPLY), _container(el.find(M + "e"))]
	if name == "limLow":
		return MathNode("munder", children=[_container(el.find(M + "e")), _container(el.find(M + "lim"))])
	if name == "limUpp":
		return MathNode("mover", children=[_container(el.find(M + "e")), _container(el.find(M + "lim"))])
	if name == "acc":
		chrEl = _prop(el, "accPr", "chr")
		ch = _val(chrEl, "̂") if chrEl is not None else "̂"
		ch = {"̂": "^", "̄": "¯", "̅": "¯", "̃": "~", "̇": "˙", "̈": "¨", "⃗": "→", "̌": "ˇ", "̆": "˘"}.get(ch, ch)
		return MathNode("mover", {"accent": "true"}, [_container(el.find(M + "e")), mo(ch)])
	if name == "bar":
		pos = _val(_prop(el, "barPr", "pos"), "bot")
		e = _container(el.find(M + "e"))
		if pos == "top":
			return MathNode("mover", {"accent": "true"}, [e, mo("¯")])
		return MathNode("munder", {"accentunder": "true"}, [e, mo("_")])
	if name in ("box", "phant"):
		return _children(el.find(M + "e")) if el.find(M + "e") is not None else None
	if name == "borderBox":
		return MathNode("menclose", {"notation": "box"}, [_container(el.find(M + "e"))])
	if name == "groupChr":
		chrEl = _prop(el, "groupChrPr", "chr")
		ch = _val(chrEl, "⏟") if chrEl is not None else "⏟"
		pos = _val(_prop(el, "groupChrPr", "pos"), "bot")
		e = _container(el.find(M + "e"))
		if pos == "top":
			return MathNode("mover", children=[e, mo(ch)])
		return MathNode("munder", children=[e, mo(ch)])
	if name == "m":
		rows = []
		for r in el.findall(M + "mr"):
			rows.append(MathNode("mtr", children=[MathNode("mtd", children=[_container(e)]) for e in r.findall(M + "e")]))
		return MathNode("mtable", children=rows)
	if name == "eqArr":
		rows = [MathNode("mtr", children=[MathNode("mtd", children=[_container(e)])]) for e in el.findall(M + "e")]
		return MathNode("mtable", children=rows)
	if name == "t":
		return _tokenize(el.text or "", False)
	# Elemento desconocido: se convierten sus hijos.
	return _children(el)


def ommlElementToMathML(el: ET.Element) -> str:
	kids = _children(el)
	root = MathNode("math", children=[_row(kids) if kids else MathNode("mrow")])
	return root.toMathML()


def findOMath(xml: str) -> list[ET.Element]:
	"""Elementos ``m:oMath`` (o ``m:oMathPara``) de un documento o fragmento XML."""
	try:
		root = ET.fromstring(xml)
	except ET.ParseError:
		m = re.search(r"<m:oMath(?:Para)?[\s>].*</m:oMath(?:Para)?>", xml, re.DOTALL)
		if not m:
			return []
		frag = m.group(0)
		wrapped = f'<root xmlns:m="{M_NS}" xmlns:w="{W_NS}">{frag}</root>'
		try:
			root = ET.fromstring(wrapped)
		except ET.ParseError:
			return []
	out: list[ET.Element] = []
	paras = list(root.iter(M + "oMathPara"))
	inPara = set()
	for p in paras:
		out.append(p)
		for o in p.iter(M + "oMath"):
			inPara.add(id(o))
	for o in root.iter(M + "oMath"):
		if id(o) not in inPara:
			out.append(o)
	return out


def ommlToMathML(xml: str) -> list[str]:
	"""Convierte todas las ecuaciones OMML de ``xml`` a MathML."""
	return [ommlElementToMathML(e) for e in findOMath(xml)]
