"""Motor propio de lectura de matemáticas en español.

Convierte un árbol MathML normalizado (:mod:`.mathml`) en una secuencia de
voz natural en español, al estilo de ClearSpeak (estilo «natural») o de
MathSpeak (estilo «estructural», con marcas explícitas de inicio y fin).

Niveles de verbosidad:

- ``breve``: lo mínimo para entender la expresión.
- ``normal``: lectura natural con marcas de fin cuando hacen falta.
- ``detallado``: marca el inicio y el fin de cada estructura y sus partes.

La salida es una lista de cadenas y :class:`Pause`. :func:`toText` la
convierte en texto plano (las pausas se escriben como comas).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .mathml import (
	CLOSE_FENCES,
	FUNCTION_APPLY,
	INVISIBLE_OPERATORS,
	INVISIBLE_PLUS,
	INVISIBLE_SEPARATOR,
	INVISIBLE_TIMES,
	OPEN_FENCES,
	MathNode,
)

VERBOSITIES = ("breve", "normal", "detallado")
STYLES = ("natural", "estructural")


class Pause:
	"""Pausa en la lectura (milisegundos)."""

	__slots__ = ("ms",)

	def __init__(self, ms: int) -> None:
		self.ms = ms

	def __repr__(self) -> str:
		return f"Pause({self.ms})"


SHORT = Pause(150)
MEDIUM = Pause(300)
LONG = Pause(450)


@dataclass
class SpeechOptions:
	verbosity: str = "normal"
	style: str = "natural"
	#: Decir «mayúscula» tras las letras mayúsculas.
	sayCapitals: bool = True


# ====================================================================== vocabulario
NUMBERS_1_19 = ["cero", "un", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce", "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve"]

#: Denominadores de fracciones sencillas (singular, plural).
DENOMINATORS = {
	2: ("medio", "medios"),
	3: ("tercio", "tercios"),
	4: ("cuarto", "cuartos"),
	5: ("quinto", "quintos"),
	6: ("sexto", "sextos"),
	7: ("séptimo", "séptimos"),
	8: ("octavo", "octavos"),
	9: ("noveno", "novenos"),
	10: ("décimo", "décimos"),
	11: ("onceavo", "onceavos"),
	12: ("doceavo", "doceavos"),
	13: ("treceavo", "treceavos"),
	14: ("catorceavo", "catorceavos"),
	15: ("quinceavo", "quinceavos"),
	16: ("dieciseisavo", "dieciseisavos"),
	17: ("diecisieteavo", "diecisieteavos"),
	18: ("dieciochoavo", "dieciochoavos"),
	19: ("diecinueveavo", "diecinueveavos"),
	20: ("veinteavo", "veinteavos"),
	100: ("centésimo", "centésimos"),
	1000: ("milésimo", "milésimos"),
}

#: Ordinales femeninos (potencias y raíces).
ORDINALS_F = {4: "cuarta", 5: "quinta", 6: "sexta", 7: "séptima", 8: "octava", 9: "novena", 10: "décima"}

GREEK_NAMES = {
	"α": "alfa",
	"β": "beta",
	"γ": "gamma",
	"δ": "delta",
	"ε": "épsilon",
	"ϵ": "épsilon",
	"ζ": "dseta",
	"η": "eta",
	"θ": "theta",
	"ϑ": "theta",
	"ι": "iota",
	"κ": "kappa",
	"ϰ": "kappa",
	"λ": "lambda",
	"μ": "mi",
	"µ": "mi",
	"ν": "ni",
	"ξ": "xi",
	"ο": "ómicron",
	"π": "pi",
	"ϖ": "pi",
	"ρ": "ro",
	"ϱ": "ro",
	"σ": "sigma",
	"ς": "sigma",
	"τ": "tau",
	"υ": "ípsilon",
	"φ": "fi",
	"ϕ": "fi",
	"χ": "ji",
	"ψ": "psi",
	"ω": "omega",
}
for _lo, _name in list(GREEK_NAMES.items()):
	_up = _lo.upper()
	if _up != _lo and _up not in GREEK_NAMES:
		GREEK_NAMES[_up] = _name + "|mayúscula"

FUNCTIONS = {
	"sin": "seno",
	"sen": "seno",
	"cos": "coseno",
	"tan": "tangente",
	"tg": "tangente",
	"cot": "cotangente",
	"cotg": "cotangente",
	"ctg": "cotangente",
	"sec": "secante",
	"csc": "cosecante",
	"cosec": "cosecante",
	"arcsin": "arco seno",
	"arcsen": "arco seno",
	"asin": "arco seno",
	"arccos": "arco coseno",
	"acos": "arco coseno",
	"arctan": "arco tangente",
	"arctg": "arco tangente",
	"atan": "arco tangente",
	"arccot": "arco cotangente",
	"sinh": "seno hiperbólico",
	"senh": "seno hiperbólico",
	"cosh": "coseno hiperbólico",
	"tanh": "tangente hiperbólica",
	"tgh": "tangente hiperbólica",
	"coth": "cotangente hiperbólica",
	"log": "logaritmo",
	"ln": "logaritmo neperiano",
	"lg": "logaritmo decimal",
	"exp": "exponencial",
	"det": "determinante",
	"dim": "dimensión",
	"ker": "núcleo",
	"deg": "grado",
	"gcd": "máximo común divisor",
	"mcd": "máximo común divisor",
	"lcm": "mínimo común múltiplo",
	"mcm": "mínimo común múltiplo",
	"max": "máximo",
	"máx": "máximo",
	"min": "mínimo",
	"mín": "mínimo",
	"sup": "supremo",
	"inf": "ínfimo",
	"lim": "límite",
	"lim sup": "límite superior",
	"lim inf": "límite inferior",
	"limsup": "límite superior",
	"liminf": "límite inferior",
	"arg": "argumento",
	"sgn": "signo",
	"sign": "signo",
	"mod": "módulo",
	"Re": "parte real",
	"Im": "parte imaginaria",
	"ℜ": "parte real",
	"ℑ": "parte imaginaria",
	"tr": "traza",
	"rank": "rango",
	"rg": "rango",
	"Pr": "probabilidad",
	"hom": "homomorfismos",
	"argmax": "argumento máximo",
	"argmin": "argumento mínimo",
}
TRIG_INVERSE = {"sin": "arco seno", "sen": "arco seno", "cos": "arco coseno", "tan": "arco tangente", "tg": "arco tangente", "cot": "arco cotangente", "sec": "arco secante", "csc": "arco cosecante"}
#: Letras que se leen como funciones si van seguidas de paréntesis.
FUNCTION_LETTERS = set("fghFGHφψΦΨ")

NUMBER_SETS = {
	"ℕ": ("naturales", "los números naturales"),
	"ℤ": ("enteros", "los números enteros"),
	"ℚ": ("racionales", "los números racionales"),
	"ℝ": ("reales", "los números reales"),
	"ℂ": ("complejos", "los números complejos"),
	"ℙ": ("primos", "los números primos"),
	"ℍ": ("cuaterniones", "los cuaterniones"),
	"𝕀": ("irracionales", "los números irracionales"),
}

SPECIAL_IDENTIFIERS = {
	"∞": "infinito",
	"∅": "conjunto vacío",
	"∂": "parcial",
	"∇": "nabla",
	"ℏ": "h barra",
	"ℓ": "ele",
	"ℵ": "álef",
	"℘": "pe de Weierstrass",
	"ı": "i",
	"ȷ": "jota",
	"⊤": "verdadero",
	"△": "triángulo",
	"∠": "ángulo",
	"□": "cuadrado",
	"…": "puntos suspensivos",
	"⋯": "puntos suspensivos",
	"y": "i griega",
	"Y": "i griega",
}

OPERATORS = {
	"+": "más",
	"−": "menos",
	"±": "más menos",
	"∓": "menos más",
	"×": "por",
	"·": "por",
	"⋅": "por",
	"∙": "por",
	"∗": "por",
	"⋆": "estrella",
	"÷": "entre",
	"/": "entre",
	"∕": "entre",
	"∘": "compuesta con",
	"⊕": "suma directa",
	"⊗": "producto tensorial",
	"⊙": "producto",
	"=": "igual a",
	"≠": "distinto de",
	"<": "menor que",
	">": "mayor que",
	"≤": "menor o igual que",
	"≥": "mayor o igual que",
	"≦": "menor o igual que",
	"≧": "mayor o igual que",
	"≮": "no menor que",
	"≯": "no mayor que",
	"≰": "ni menor ni igual que",
	"≱": "ni mayor ni igual que",
	"≪": "mucho menor que",
	"≫": "mucho mayor que",
	"≈": "aproximadamente igual a",
	"≃": "asintóticamente igual a",
	"≅": "congruente con",
	"≡": "idéntico a",
	"≢": "no idéntico a",
	"∼": "semejante a",
	"≁": "no semejante a",
	"∝": "proporcional a",
	"≔": "se define como",
	"≜": "se define como",
	"≝": "igual por definición a",
	"≐": "tiende al límite",
	"∈": "pertenece a",
	"∉": "no pertenece a",
	"∋": "contiene al elemento",
	"∌": "no contiene al elemento",
	"⊂": "contenido en",
	"⊆": "contenido o igual a",
	"⊊": "contenido estrictamente en",
	"⊄": "no contenido en",
	"⊈": "ni contenido ni igual a",
	"⊃": "contiene a",
	"⊇": "contiene o es igual a",
	"⊅": "no contiene a",
	"∪": "unión",
	"∩": "intersección",
	"∖": "menos",
	"∀": "para todo",
	"∃": "existe",
	"∄": "no existe",
	"¬": "no",
	"∧": "y",
	"∨": "o",
	"⊻": "o exclusivo",
	"⇒": "implica",
	"⟹": "implica",
	"⇐": "es implicado por",
	"⟸": "es implicado por",
	"⇔": "si y solo si",
	"⟺": "si y solo si",
	"∴": "por lo tanto",
	"∵": "porque",
	"⊢": "deduce",
	"⊨": "satisface",
	"→": "flecha a la derecha",
	"⟶": "flecha a la derecha",
	"←": "flecha a la izquierda",
	"⟵": "flecha a la izquierda",
	"↔": "flecha doble",
	"⟷": "flecha doble",
	"↦": "se aplica en",
	"↑": "flecha arriba",
	"↓": "flecha abajo",
	"⇑": "flecha doble arriba",
	"⇓": "flecha doble abajo",
	"⊥": "perpendicular a",
	"∥": "paralelo a",
	"∦": "no paralelo a",
	"‖": "doble barra",
	"|": "barra vertical",
	"∤": "no divide a",
	"!": "factorial",
	"%": "por ciento",
	"‰": "por mil",
	"°": "grados",
	"′": "prima",
	"″": "doble prima",
	"‴": "triple prima",
	"∠": "ángulo",
	"∡": "ángulo medido",
	"∞": "infinito",
	"∂": "parcial",
	"∇": "nabla",
	"∫": "integral",
	"∬": "integral doble",
	"∭": "integral triple",
	"∮": "integral de línea cerrada",
	"∑": "sumatorio",
	"∏": "productorio",
	"∐": "coproducto",
	"⋃": "unión",
	"⋂": "intersección",
	"⋁": "disyunción",
	"⋀": "conjunción",
	"⨁": "suma directa",
	"⨂": "producto tensorial",
	",": "coma",
	";": "punto y coma",
	":": "dos puntos",
	".": "punto",
	"…": "puntos suspensivos",
	"⋯": "puntos suspensivos",
	"⋮": "puntos suspensivos verticales",
	"⋱": "puntos suspensivos diagonales",
	"∶": "es a",
	"∷": "como",
	"#": "número de elementos de",
	"&": "y",
	"~": "tilde",
	"^": "circunflejo",
	"_": "guion bajo",
	"¯": "barra",
	"†": "daga",
	"∅": "conjunto vacío",
	"mod": "módulo",
}

RELATIONS = frozenset({"=", "≠", "<", ">", "≤", "≥", "≈", "≡", "∼", "≃", "≅", "∝", "∈", "∉", "⊂", "⊆", "⊃", "⊇", "⇒", "⇔", "⟹", "⟺", "→", "≔", "≪", "≫", "⊥", "∥", "↦"})
BIG_OPERATORS = frozenset({"∑", "∏", "∐", "∫", "∬", "∭", "∮", "⋃", "⋂", "⋁", "⋀", "⨁", "⨂"})
INTEGRALS = frozenset({"∫", "∬", "∭", "∮"})

FENCE_NAMES = {
	"(": ("paréntesis", "abre paréntesis", "cierra paréntesis"),
	"[": ("corchete", "abre corchete", "cierra corchete"),
	"{": ("llave", "abre llave", "cierra llave"),
	"⟨": ("ángulo", "abre ángulo", "cierra ángulo"),
	"〈": ("ángulo", "abre ángulo", "cierra ángulo"),
	"⟦": ("doble corchete", "abre doble corchete", "cierra doble corchete"),
}

ACCENT_NAMES = {
	"^": "circunflejo",
	"ˆ": "circunflejo",
	"̂": "circunflejo",
	"¯": "barra",
	"‾": "barra",
	"̄": "barra",
	"_": "barra",
	"~": "tilde",
	"˜": "tilde",
	"∼": "tilde",
	"˙": "punto",
	"¨": "dos puntos",
	"ˇ": "carón",
	"˘": "breve",
	"´": "acento agudo",
	"`": "acento grave",
	"˚": "anillo",
	"⏞": "con llave superior",
	"⏟": "con llave inferior",
	"⃗": "vector",
}

ENCLOSE_NAMES = {
	"box": "recuadro",
	"roundedbox": "recuadro redondeado",
	"circle": "círculo",
	"longdiv": "división larga",
	"actuarial": "símbolo actuarial",
	"radical": "raíz cuadrada",
	"top": "línea superior",
	"bottom": "línea inferior",
	"left": "línea izquierda",
	"right": "línea derecha",
	"updiagonalstrike": "tachado",
	"downdiagonalstrike": "tachado",
	"verticalstrike": "tachado vertical",
	"horizontalstrike": "tachado horizontal",
	"madruwb": "símbolo factorial árabe",
	"phasorangle": "ángulo de fase",
}

#: Unidades: abreviatura -> (singular, plural).
UNITS = {
	"m": ("metro", "metros"),
	"cm": ("centímetro", "centímetros"),
	"mm": ("milímetro", "milímetros"),
	"km": ("kilómetro", "kilómetros"),
	"dm": ("decímetro", "decímetros"),
	"µm": ("micrómetro", "micrómetros"),
	"μm": ("micrómetro", "micrómetros"),
	"nm": ("nanómetro", "nanómetros"),
	"g": ("gramo", "gramos"),
	"kg": ("kilogramo", "kilogramos"),
	"mg": ("miligramo", "miligramos"),
	"t": ("tonelada", "toneladas"),
	"s": ("segundo", "segundos"),
	"ms": ("milisegundo", "milisegundos"),
	"min": ("minuto", "minutos"),
	"h": ("hora", "horas"),
	"L": ("litro", "litros"),
	"l": ("litro", "litros"),
	"mL": ("mililitro", "mililitros"),
	"ml": ("mililitro", "mililitros"),
	"cl": ("centilitro", "centilitros"),
	"N": ("newton", "newtons"),
	"J": ("julio", "julios"),
	"kJ": ("kilojulio", "kilojulios"),
	"W": ("vatio", "vatios"),
	"kW": ("kilovatio", "kilovatios"),
	"kWh": ("kilovatio hora", "kilovatios hora"),
	"V": ("voltio", "voltios"),
	"A": ("amperio", "amperios"),
	"mA": ("miliamperio", "miliamperios"),
	"Ω": ("ohmio", "ohmios"),
	"Hz": ("hercio", "hercios"),
	"kHz": ("kilohercio", "kilohercios"),
	"MHz": ("megahercio", "megahercios"),
	"Pa": ("pascal", "pascales"),
	"kPa": ("kilopascal", "kilopascales"),
	"atm": ("atmósfera", "atmósferas"),
	"K": ("kelvin", "kelvin"),
	"°C": ("grado Celsius", "grados Celsius"),
	"℃": ("grado Celsius", "grados Celsius"),
	"°F": ("grado Fahrenheit", "grados Fahrenheit"),
	"mol": ("mol", "moles"),
	"cd": ("candela", "candelas"),
	"rad": ("radián", "radianes"),
	"cal": ("caloría", "calorías"),
	"kcal": ("kilocaloría", "kilocalorías"),
	"C": ("culombio", "culombios"),
	"T": ("tesla", "teslas"),
	"eV": ("electronvoltio", "electronvoltios"),
	"B": ("byte", "bytes"),
	"KB": ("kilobyte", "kilobytes"),
	"MB": ("megabyte", "megabytes"),
	"GB": ("gigabyte", "gigabytes"),
	"€": ("euro", "euros"),
	"$": ("dólar", "dólares"),
}
#: Unidades de varias letras que se reconocen aunque no estén marcadas.
_UNAMBIGUOUS_UNITS = {u for u in UNITS if len(u) > 1 and u not in ("ms", "min", "cd", "rad", "cal", "mod", "Pa", "atm")} | {"km", "cm", "mm", "kg", "mg", "Hz", "°C", "℃", "kWh"}


def _isInvisible(node: MathNode) -> bool:
	return node.tag == "mo" and node.text in INVISIBLE_OPERATORS


def realChildren(node: MathNode) -> list[MathNode]:
	"""Hijos sin operadores invisibles ni espacios."""
	return [c for c in node.children if not _isInvisible(c) and c.tag != "mspace"]


def isNumberToken(node: MathNode) -> bool:
	return node.tag == "mn"


def intValue(node: MathNode) -> int | None:
	if node.tag == "mn" and node.text.isdigit():
		try:
			return int(node.text)
		except ValueError:
			return None
	return None


def isSimple(node: MathNode) -> bool:
	"""Expresión que se puede leer sin marcas de inicio y fin."""
	if node.tag in ("mi", "mn", "mtext", "ms"):
		return len(node.text) <= 12
	if node.tag == "mo":
		return node.text in ("∞", "∅", "…")
	if node.tag == "mrow" and not node.isFenced:
		kids = realChildren(node)
		if len(kids) == 2 and kids[0].isMo("−", "+") and kids[1].tag in ("mi", "mn"):
			return True
		visibleOps = [c for c in node.children if c.tag == "mo" and c.text not in (INVISIBLE_TIMES,)]
		if not visibleOps and 1 < len(kids) <= 3 and all(k.tag in ("mi", "mn") for k in kids):
			return True
	return False


def baseOf(node: MathNode) -> MathNode:
	while node.tag in ("msub", "msup", "msubsup", "munder", "mover", "munderover", "mmultiscripts") and node.children:
		node = node.children[0]
	return node


def isFunctionName(node: MathNode) -> bool:
	b = baseOf(node)
	return b.tag == "mi" and b.text in FUNCTIONS


def isBigOperator(node: MathNode) -> bool:
	return node.tag in ("mo", "mi") and node.text in BIG_OPERATORS


def numberToWords(n: int) -> str:
	if 0 <= n < 20:
		return NUMBERS_1_19[n] if n != 1 else "uno"
	return str(n)


def formatNumber(text: str) -> str:
	"""Prepara un número para la voz española (coma decimal, sin separadores de miles)."""
	t = text.strip().replace(" ", "").replace(" ", "").replace(" ", "")
	neg = ""
	if t[:1] in ("−", "-"):
		neg = "menos "
		t = t[1:]
	if re.fullmatch(r"\d{1,3}(\.\d{3})+", t) and len(t.split(".")) > 2:
		t = t.replace(".", "")
	elif re.fullmatch(r"\d{1,3}(,\d{3})+", t) and len(t.split(",")) > 2:
		t = t.replace(",", "")
	elif re.fullmatch(r"\d{1,3}(\.\d{3})+,\d+", t):
		t = t.replace(".", "")
	elif re.fullmatch(r"\d{1,3}(,\d{3})+\.\d+", t):
		t = t.replace(",", "")
	m = re.fullmatch(r"(\d*)[.,](\d+)", t)
	if m:
		ip, dp = m.group(1) or "0", m.group(2)
		return f"{neg}{ip} coma {dp}"
	return neg + t


def characterName(ch: str) -> str:
	"""Nombre en español de un carácter suelto."""
	if ch in OPERATORS:
		return OPERATORS[ch]
	if ch in SPECIAL_IDENTIFIERS:
		return SPECIAL_IDENTIFIERS[ch]
	if ch in GREEK_NAMES:
		return GREEK_NAMES[ch].replace("|", " ")
	try:
		from ..speech.symbols import processor

		name = processor.characterName(ch)
		if name and name != ch:
			return name
	except Exception:
		pass
	try:
		return unicodedata.name(ch).lower()
	except ValueError:
		return ch


# ====================================================================== generador
class SpeechGenerator:
	def __init__(self, options: SpeechOptions | None = None) -> None:
		self.opts = options or SpeechOptions()

	@property
	def v(self) -> str:
		return self.opts.verbosity

	@property
	def structural(self) -> bool:
		return self.opts.style == "estructural"

	# ------------------------------------------------------------ entrada
	def speak(self, node: MathNode | None) -> list:
		if node is None:
			return []
		method = getattr(self, "_" + node.tag.replace("-", "_"), None)
		if method is None:
			out: list = []
			for c in node.children:
				out.extend(self.speak(c))
			if node.isToken and node.text:
				out.append(node.text)
			return out
		return method(node)

	# ------------------------------------------------------------ contexto
	def _isTrailing(self, node: MathNode) -> bool:
		"""¿Termina la estructura donde acaba su contexto (no hace falta marca de fin)?"""
		n = node
		while n.parent is not None:
			p = n.parent
			if p.tag == "math":
				return True
			if p.tag == "mrow":
				if p.isFenced:
					return True
				kids = realChildren(p)
				if not kids or kids[-1] is not n:
					return False
				n = p
				continue
			if p.tag in ("mtd", "mtr", "mtable"):
				return True
			return False
		return True

	def _ancestorTags(self, node: MathNode) -> list[str]:
		out = []
		n = node.parent
		while n is not None:
			out.append(n.tag)
			n = n.parent
		return out

	def _inLimitScript(self, node: MathNode) -> bool:
		n = node
		while n.parent is not None:
			p = n.parent
			if p.tag in ("munder", "msub", "munderover") and n is not p.children[0]:
				b = p.children[0]
				return b.tag == "mi" and b.text in ("lim", "lim sup", "lim inf", "limsup", "liminf")
			n = p
		return False

	# ------------------------------------------------------------ elementos
	def _math(self, node: MathNode) -> list:
		out: list = []
		for c in node.children:
			out.extend(self.speak(c))
		return out

	def _mrow(self, node: MathNode) -> list:
		if node.isFenced:
			return self._fenced(node)
		kids = node.children
		if len(kids) >= 2 and kids[0].isMo("{") and kids[1].tag == "mtable" and len(realChildren(node)) == 2:
			return self._cases(kids[1])
		return self._sequence(kids, node)

	def _sequence(self, kids: list[MathNode], parent: MathNode) -> list:
		out: list = []
		real = [k for k in kids if not _isInvisible(k) and k.tag != "mspace"]
		longRow = len(real) > 5
		hasMapping = any(k.isMo(":") for k in kids)
		inSet = parent.parent is not None and parent.parent.isFenced and parent.parent.get("_open") == "{" or parent.isFenced and parent.get("_open") == "{"
		skip: set[int] = set()
		lastNumber: int | None = None
		prevReal: MathNode | None = None
		for i, c in enumerate(kids):
			if i in skip or c.tag == "mspace":
				continue
			nxt = self._nextReal(kids, i)
			if c.tag == "mo":
				t = c.text
				if t in INVISIBLE_OPERATORS:
					if t == INVISIBLE_PLUS:
						out.append("y")
					elif t == INVISIBLE_SEPARATOR:
						out.append(SHORT)
					continue
				if t in ("/", "·", "⋅") and prevReal is not None and self._isUnit(prevReal) and nxt is not None and self._isUnit(nxt[1]):
					out.append("por")
					prevReal = c
					continue
				out.extend(self._operatorInRow(c, prevReal, nxt[1] if nxt else None, longRow, hasMapping, inSet))
				prevReal = c
				continue
			# Funciones: «seno de x», «f de x».
			if self._isFunctionHead(c, nxt[1] if nxt else None, kids, i):
				out.extend(self.speak(c))
				if nxt is not None:
					j, arg = nxt
					out.append("de")
					if arg.isFenced and arg.get("_open") == "(" and self._simpleArguments(arg):
						out.extend(self._sequence(self._argumentList(arg), arg))
						skip.add(j)
				prevReal = c
				continue
			# Unidades: «5 cm» -> «5 centímetros».
			if self._isUnit(c) and (lastNumber is not None or (prevReal is not None and self._isUnit(prevReal))):
				out.extend(self._unitSpeech(c, plural=lastNumber != 1))
				prevReal = c
				continue
			if prevReal is not None and prevReal.isFenced and c.isFenced and prevReal.get("_open") in ("(", "[") and c.get("_open") in ("(", "["):
				out.append("por")
			out.extend(self.speak(c))
			if c.tag == "mn":
				try:
					lastNumber = int(c.text) if c.text.isdigit() else 2
				except ValueError:
					lastNumber = 2
			elif not self._isUnit(c):
				lastNumber = None
			prevReal = c
		return out

	@staticmethod
	def _nextReal(kids: list[MathNode], i: int) -> tuple[int, MathNode] | None:
		for j in range(i + 1, len(kids)):
			k = kids[j]
			if k.tag == "mo" and k.text in (INVISIBLE_TIMES, INVISIBLE_SEPARATOR):
				continue
			if k.tag == "mo" and k.text == FUNCTION_APPLY:
				continue
			if k.tag == "mspace":
				continue
			return j, k
		return None

	def _isFunctionHead(self, c: MathNode, nxt: MathNode | None, kids: list[MathNode], i: int) -> bool:
		if nxt is None:
			return False
		if nxt.tag == "mo" and nxt.text not in OPEN_FENCES and nxt.text not in ("−", "∂", "|"):
			return False
		explicit = i + 1 < len(kids) and kids[i + 1].isMo(FUNCTION_APPLY)
		b = baseOf(c)
		if b.tag != "mi":
			return False
		if b.text in ("lim", "lim sup", "lim inf", "limsup", "liminf", "max", "min", "sup", "inf", "mod") and c.tag in ("munder", "munderover"):
			return False
		if b.text in FUNCTIONS:
			if b.text in ("lim", "lim sup", "lim inf", "limsup", "liminf") and c.tag != "mi":
				return False
			return b.text not in ("mod",)
		if explicit:
			return True
		if b.text in FUNCTION_LETTERS and nxt.isFenced and nxt.get("_open") == "(":
			return True
		return False

	def _simpleArguments(self, fenced: MathNode) -> bool:
		content = fenced.fenceContent
		if content is None:
			return True
		if isSimple(content):
			return True
		if content.tag == "mrow" and not content.isFenced:
			parts = [k for k in content.children if not k.isMo(",")]
			return all(isSimple(p) for p in parts) and any(k.isMo(",") for k in content.children)
		return False

	@staticmethod
	def _argumentList(fenced: MathNode) -> list[MathNode]:
		content = fenced.fenceContent
		if content is None:
			return []
		if content.tag == "mrow" and not content.isFenced:
			return list(content.children)
		return [content]

	def _operatorInRow(self, node: MathNode, prev: MathNode | None, nxt: MathNode | None, longRow: bool, hasMapping: bool, inSet: bool) -> list:
		t = node.text
		out: list = []
		if t in ("|", "∣") and inSet:
			return [SHORT, "tales que"]
		if t == ":" and inSet:
			return [SHORT, "tales que"]
		if t in ("→", "⟶"):
			if self._inLimitScript(node):
				return ["tiende a"]
			if hasMapping:
				return ["en"]
			if prev is not None and nxt is not None and prev.tag == "mi" and (nxt.tag in ("mn", "mi") or nxt.isMo("∞")) and not self.v == "detallado":
				return ["tiende a"]
		if t == "," :
			return ["coma", SHORT] if self.v != "breve" else [SHORT]
		if t == ";":
			return ["punto y coma", MEDIUM] if self.v != "breve" else [MEDIUM]
		if t in RELATIONS and (longRow or self.v == "detallado"):
			out.append(SHORT)
			out.extend(self._mo(node))
			out.append(SHORT)
			return out
		if t in BIG_OPERATORS and nxt is not None:
			return self._mo(node) + ["de"]
		return self._mo(node)

	# ------------------------------------------------------------ fichas
	def _mi(self, node: MathNode) -> list:
		t = node.text
		variant = node.get("mathvariant")
		if not t:
			return []
		if node.get("class", "").lower().find("unit") >= 0 or ":unit" in node.get("intent", ""):
			return self._unitSpeech(node, plural=True)
		if variant == "double-struck" and t in "NZQRCPH" and len(t) == 1:
			t = {"N": "ℕ", "Z": "ℤ", "Q": "ℚ", "R": "ℝ", "C": "ℂ", "P": "ℙ", "H": "ℍ"}[t]
		if t in NUMBER_SETS:
			short, long_ = NUMBER_SETS[t]
			return [short if self.v == "breve" else long_]
		if t in FUNCTIONS:
			return [FUNCTIONS[t]]
		if t in SPECIAL_IDENTIFIERS:
			name = SPECIAL_IDENTIFIERS[t]
			if t == "Y" and self.opts.sayCapitals and self.v != "breve":
				name += " mayúscula"
			return [name]
		if t in GREEK_NAMES:
			name = GREEK_NAMES[t]
			if "|" in name:
				base, cap = name.split("|")
				name = base + (" " + cap if self.v != "breve" and self.opts.sayCapitals else "")
			return [self._withVariant(name, variant)]
		if len(t) == 1:
			if t.isalpha():
				name = t
				if t.isupper() and self.opts.sayCapitals and self.v != "breve":
					name = f"{t} mayúscula"
				return [self._withVariant(name, variant)]
			return [characterName(t)]
		# Varias letras.
		if t.isupper() and len(t) <= 4 and t.isalpha():
			return [self._withVariant(" ".join(t), variant)]
		return [self._withVariant(t, variant)]

	def _withVariant(self, name: str, variant: str) -> str:
		if self.v == "breve" or not variant or variant in ("italic", "normal"):
			return name
		label = {
			"bold": "negrita",
			"bold-italic": "negrita",
			"double-struck": "doble",
			"script": "caligráfica",
			"bold-script": "caligráfica negrita",
			"fraktur": "gótica",
			"bold-fraktur": "gótica negrita",
			"sans-serif": "",
			"monospace": "",
		}.get(variant, "")
		return f"{name} {label}" if label else name

	def _mn(self, node: MathNode) -> list:
		return [formatNumber(node.text)]

	def _mo(self, node: MathNode) -> list:
		t = node.text
		if t in INVISIBLE_OPERATORS:
			return ["y"] if t == INVISIBLE_PLUS else []
		if t in OPERATORS:
			return [OPERATORS[t]]
		if t in CLOSE_FENCES or t in OPEN_FENCES:
			return [self._fenceWord(t, t in OPEN_FENCES)]
		if t in FUNCTIONS:
			return [FUNCTIONS[t]]
		if len(t) > 1:
			return [" ".join(characterName(ch) for ch in t)]
		return [characterName(t)]

	def _mtext(self, node: MathNode) -> list:
		t = node.text.strip()
		return [t] if t else []

	def _ms(self, node: MathNode) -> list:
		return ["comillas", node.text, "comillas"]

	def _mspace(self, node: MathNode) -> list:
		return []

	def _mglyph(self, node: MathNode) -> list:
		alt = node.get("alt")
		return [alt] if alt else []

	def _none(self, node: MathNode) -> list:
		return []

	def _merror(self, node: MathNode) -> list:
		return ["error"] + self._math(node)

	def _mtd(self, node: MathNode) -> list:
		return self._math(node)

	def _mtr(self, node: MathNode) -> list:
		out: list = []
		for i, c in enumerate(node.children):
			if i:
				out.append(SHORT)
			out.extend(self.speak(c))
		return out

	# ------------------------------------------------------------ unidades
	def _isUnit(self, node: MathNode) -> bool:
		if node.tag == "msup" and node.children:
			return self._isUnit(node.children[0])
		if node.tag not in ("mi", "mtext"):
			return False
		t = node.text.strip()
		if node.get("class", "").lower().find("unit") >= 0 or ":unit" in node.get("intent", ""):
			return True
		if t in _UNAMBIGUOUS_UNITS:
			return True
		if t in UNITS and (node.tag == "mtext" or node.get("mathvariant") == "normal"):
			return True
		return False

	def _unitSpeech(self, node: MathNode, plural: bool) -> list:
		if node.tag == "msup" and len(node.children) == 2:
			base = node.children[0]
			exp = intValue(node.children[1])
			words = self._unitSpeech(base, plural)
			if exp == 2:
				return words + (["cuadrados"] if plural else ["cuadrado"])
			if exp == 3:
				return words + (["cúbicos"] if plural else ["cúbico"])
			return words + ["elevado a"] + self.speak(node.children[1])
		t = node.text.strip()
		if t in UNITS:
			sing, plur = UNITS[t]
			return [plur if plural else sing]
		return [t]

	# ------------------------------------------------------------ delimitadores
	def _fenceWord(self, ch: str, opening: bool) -> str:
		if ch in ("|", "∣"):
			return "barra vertical"
		if ch in ("‖", "∥"):
			return "doble barra"
		if ch in ("⌊", "⌋"):
			return "abre suelo" if opening else "cierra suelo"
		if ch in ("⌈", "⌉"):
			return "abre techo" if opening else "cierra techo"
		key = ch if opening else CLOSE_FENCES.get(ch, ch)
		names = FENCE_NAMES.get(key)
		if names is None:
			return characterName(ch)
		if self.v == "breve":
			if key == "(":
				return "paréntesis" if opening else "cierra"
			return names[0] if opening else "cierra " + names[0]
		return names[1] if opening else names[2]

	def _fenced(self, node: MathNode) -> list:
		o = node.get("_open")
		c = node.get("_close")
		content = node.fenceContent
		if content is None:
			content = MathNode("mrow")
		if content.tag == "mtable":
			return self._matrix(content, o, c)
		if o == "(" and content.tag == "mfrac" and content.get("linethickness") == "0":
			a, b = content.children[0], content.children[1]
			if self.v == "breve":
				return self.speak(a) + ["sobre"] + self.speak(b)
			return ["el número combinatorio"] + self.speak(a) + ["sobre"] + self.speak(b) + ([SHORT] if not self._isTrailing(node) else [])
		inner = self.speak(content)
		end = not self._isTrailing(node) and not isSimple(content)
		if o in ("|", "∣") and c in ("|", "∣"):
			if self.structural:
				return ["inicio de valor absoluto"] + inner + ["fin de valor absoluto"]
			out = ["valor absoluto de"] + inner
			if end or self.v == "detallado":
				out += [SHORT, "fin del valor absoluto"] if self.v != "breve" else [SHORT]
			return out
		if o in ("‖", "∥") and c in ("‖", "∥"):
			out = ["norma de"] + inner
			if end or self.v == "detallado":
				out += [SHORT, "fin de la norma"] if self.v != "breve" else [SHORT]
			return out
		if o == "⌊" and c == "⌋":
			out = ["parte entera por defecto de"] + inner
			return out + ([SHORT, "fin de parte entera"] if end else [])
		if o == "⌈" and c == "⌉":
			out = ["parte entera por exceso de"] + inner
			return out + ([SHORT, "fin de parte entera"] if end else [])
		if o == "{" and c == "}":
			return self._set(content, node)
		if o in ("⟨", "〈") and c in ("⟩", "〉") and content.tag == "mrow" and any(k.isMo(",", "|") for k in content.children):
			return ["el producto escalar de"] + self._sequence(content.children, content) + ([SHORT] if end else [])
		# Paréntesis y corchetes normales.
		if o == "(" and c == ")" and content.tag in ("mi", "mn") and self.v != "detallado" and not self.structural:
			# (x) se lee «x»; (3) «3».
			return inner
		openWord = self._fenceWord(o, True) if o else ""
		closeWord = self._fenceWord(c, False) if c else ""
		out: list = []
		if openWord:
			out.append(openWord)
		out.extend(inner)
		if closeWord:
			out.append(closeWord)
		return out

	def _set(self, content: MathNode, node: MathNode) -> list:
		kids = content.children if content.tag == "mrow" and not content.isFenced else [content]
		real = [k for k in kids if not _isInvisible(k)]
		if not real or (content.tag == "mrow" and not content.children):
			return ["el conjunto vacío" if self.v != "breve" else "conjunto vacío"]
		sepIdx = next((i for i, k in enumerate(kids) if k.isMo("|", "∣", ":")), None)
		pre = "conjunto" if self.v == "breve" else "el conjunto"
		if sepIdx is not None:
			before = self._sequence(kids[:sepIdx], content)
			after = self._sequence(kids[sepIdx + 1 :], content)
			out = [pre, "de los"] + before + [SHORT, "tales que"] + after
		else:
			out = [pre] + self.speak(content)
		if self.v == "detallado" or (not self._isTrailing(node) and self.v != "breve"):
			out += [SHORT, "fin del conjunto"]
		return out

	# ------------------------------------------------------------ fracciones
	def _mfrac(self, node: MathNode) -> list:
		num, den = node.children[0], node.children[1]
		if node.get("linethickness") == "0":
			return self.speak(num) + ["sobre"] + self.speak(den)
		deriv = self._derivative(num, den)
		if deriv is not None and not self.structural:
			return deriv
		a, b = intValue(num), intValue(den)
		if a is not None and b is not None and 0 < a < 20 and b in DENOMINATORS and not self.structural:
			sing, plur = DENOMINATORS[b]
			return [f"{NUMBERS_1_19[a]} {sing if a == 1 else plur}"]
		numS = self.speak(num)
		denS = self.speak(den)
		simple = isSimple(num) and isSimple(den)
		if self.structural:
			if self.v == "breve":
				return ["fracción"] + numS + ["sobre"] + denS + ["fin fracción"]
			return ["inicio de fracción"] + numS + [SHORT, "sobre"] + denS + [SHORT, "fin de fracción"]
		if simple:
			if self.v == "detallado":
				return ["fracción"] + numS + ["sobre"] + denS
			return numS + ["sobre"] + denS
		if self.v == "breve":
			return ["fracción"] + numS + [SHORT, "sobre"] + denS + [SHORT, "fin fracción"]
		if self.v == "detallado":
			return ["inicio de fracción", SHORT, "numerador"] + numS + [SHORT, "denominador"] + denS + [SHORT, "fin de fracción"]
		out = ["fracción con numerador"] + numS + [SHORT, "y denominador"] + denS
		if not self._isTrailing(node):
			out += [SHORT, "fin de fracción"]
		return out

	def _derivative(self, num: MathNode, den: MathNode) -> list | None:
		"""dy/dx -> «derivada de y respecto de x»."""

		def split(n: MathNode) -> tuple[str, int, list[MathNode]] | None:
			kids = realChildren(n) if n.tag == "mrow" and not n.isFenced else [n]
			if not kids:
				return None
			first = kids[0]
			order = 1
			d = first
			if first.tag == "msup" and len(first.children) == 2:
				d = first.children[0]
				order = intValue(first.children[1]) or 0
			if d.tag in ("mi", "mo") and d.text in ("d", "∂", "ⅆ"):
				return ("∂" if d.text == "∂" else "d", order, kids[1:])
			return None

		top = split(num)
		bottom = split(den)
		if top is None or bottom is None or top[0] != bottom[0] or not bottom[2]:
			return None
		kind, order, fn = top
		var = bottom[2]
		if len(var) == 1 and var[0].tag == "msup":
			var = [var[0].children[0]]
		if not all(v.tag in ("mi",) for v in var) or len(var) > 1 and order <= 1:
			return None
		ordWord = {1: "", 2: "segunda", 3: "tercera", 4: "cuarta"}.get(order, f"de orden {order}")
		name = "derivada parcial" if kind == "∂" else "derivada"
		if ordWord:
			name = f"{name} {ordWord}"
		if self.v == "breve":
			if order > 1:
				return None
			out = (["d"] if kind == "d" else ["parcial"]) + (self.speak(MathNode("mrow", children=[c.copy() for c in fn])) if fn else []) + ["sobre", "d" if kind == "d" else "parcial"] + self.speak(var[0])
			return out
		out = [name]
		if fn:
			out += ["de"] + self.speak(MathNode("mrow", children=[c.copy() for c in fn]))
		out += ["respecto de"] + self.speak(var[0])
		return out

	# ------------------------------------------------------------ raíces
	def _msqrt(self, node: MathNode) -> list:
		return self._root(node.children[0], None, node)

	def _mroot(self, node: MathNode) -> list:
		return self._root(node.children[0], node.children[1], node)

	def _root(self, radicand: MathNode, index: MathNode | None, node: MathNode) -> list:
		idx = intValue(index) if index is not None else 2
		if index is None or idx == 2:
			name = "raíz cuadrada"
		elif idx == 3:
			name = "raíz cúbica"
		elif idx in ORDINALS_F:
			name = "raíz " + ORDINALS_F[idx]
		elif index.tag == "mi" and index.text == "n":
			name = "raíz enésima"
		else:
			name = None
		head: list = [name] if name else ["raíz de índice"] + self.speak(index) + [SHORT]
		body = self.speak(radicand)
		if self.structural:
			return ["inicio de"] + head + body + [SHORT, "fin de raíz"]
		if isSimple(radicand):
			return head + ["de"] + body
		if self.v == "breve":
			return ([("raíz" if name == "raíz cuadrada" else name)] if name else head) + ["de"] + body + [SHORT, "fin raíz"]
		if self.v == "detallado":
			return ["inicio de"] + head + [SHORT] + body + [SHORT, "fin de raíz"]
		out = head + ["de"] + body
		if not self._isTrailing(node):
			out += [SHORT, "fin de raíz"]
		return out

	# ------------------------------------------------------------ índices
	def _msup(self, node: MathNode) -> list:
		base, exp = node.children[0], node.children[1]
		return self._power(base, exp, node)

	def _power(self, base: MathNode, exp: MathNode, node: MathNode, prefix: list | None = None) -> list:
		baseS = prefix if prefix is not None else self.speak(base)
		# Primas, grados y otros superíndices especiales.
		if exp.tag == "mo" and exp.text in ("′", "″", "‴", "°", "∘", "∗", "†", "+", "−", "*"):
			word = {"′": "prima", "″": "doble prima", "‴": "triple prima", "°": "grados", "∘": "grados", "∗": "asterisco", "*": "asterisco", "†": "daga", "+": "más", "−": "menos"}[exp.text]
			if exp.text in ("°", "∘") and intValue(base) == 1:
				word = "grado"
			return baseS + [word]
		if exp.tag == "mi" and exp.text in ("T", "⊤") and baseOf(base).tag == "mi" and (baseOf(base).text.isupper() or baseOf(base).get("mathvariant") == "bold"):
			return baseS + ["traspuesta"]
		bb = baseOf(base)
		if bb.tag == "mi" and bb.text in FUNCTIONS and base.tag == "mi":
			if self._isMinusOne(exp):
				if bb.text in TRIG_INVERSE:
					return [TRIG_INVERSE[bb.text]]
				return baseS + ["inversa"]
		if prefix is None and base.tag == "mi" and base.text in FUNCTION_LETTERS and self._isMinusOne(exp):
			return baseS + ["inversa"]
		if self.structural:
			return baseS + ["superíndice"] + self.speak(exp) + [SHORT, "fin de superíndice"]
		n = intValue(exp)
		if n == 2:
			return baseS + ["al cuadrado"]
		if n == 3:
			return baseS + ["al cubo"]
		if n in ORDINALS_F:
			if self.v == "detallado":
				return baseS + ["elevado a la", ORDINALS_F[n], "potencia"]
			return baseS + ["a la", ORDINALS_F[n]]
		expS = self.speak(exp)
		if exp.tag == "mn":
			return baseS + (["a la"] if self.v == "breve" else ["elevado a"]) + expS
		if isSimple(exp):
			if self.v == "breve":
				return baseS + ["a la"] + expS
			out = baseS + ["elevado a"] + expS
			if self.v == "detallado":
				out += [SHORT, "fin del exponente"]
			return out
		out = baseS + ["elevado a"] + expS
		if self.v == "breve":
			return out + [SHORT]
		if self.v == "detallado" or not self._isTrailing(node):
			out += [SHORT, "fin del exponente"]
		return out

	@staticmethod
	def _isMinusOne(exp: MathNode) -> bool:
		if exp.tag == "mn" and exp.text in ("-1", "−1"):
			return True
		kids = realChildren(exp) if exp.tag == "mrow" else []
		return len(kids) == 2 and kids[0].isMo("−") and intValue(kids[1]) == 1

	def _msub(self, node: MathNode) -> list:
		base, sub = node.children[0], node.children[1]
		if isBigOperator(base):
			return self._largeOp(base, sub, None, node)
		if base.tag == "mi" and base.text in ("lim", "lim sup", "lim inf", "limsup", "liminf", "max", "min", "sup", "inf"):
			return self._limitLike(base, sub, node)
		if base.tag == "mi" and base.text == "log":
			return ["logaritmo en base"] + self.speak(sub) + ([SHORT] if not isSimple(sub) else [])
		return self.speak(base) + self._subscript(sub, node)

	def _subscript(self, sub: MathNode, node: MathNode) -> list:
		subS = self.speak(sub)
		if self.structural:
			return ["subíndice"] + subS + [SHORT, "fin de subíndice"]
		word = "subíndice" if self.v == "detallado" else "sub"
		out = [word] + subS
		if not isSimple(sub) and (self.v == "detallado" or not self._isTrailing(node)):
			out += [SHORT, "fin del subíndice"]
		elif self.v == "detallado" and not self._isTrailing(node):
			out += [SHORT]
		return out

	def _msubsup(self, node: MathNode) -> list:
		base, sub, sup = node.children
		if isBigOperator(base):
			return self._largeOp(base, sub, sup, node)
		if base.tag == "mi" and base.text == "log":
			return ["logaritmo en base"] + self.speak(sub) + self._power(MathNode("mrow"), sup, node, prefix=[])
		prefix = self.speak(base) + self._subscript(sub, node)
		return self._power(base, sup, node, prefix=prefix)

	def _munder(self, node: MathNode) -> list:
		base, under = node.children
		if isBigOperator(base):
			return self._largeOp(base, under, None, node)
		if base.tag == "mi" and base.text in FUNCTIONS:
			return self._limitLike(base, under, node)
		if under.tag == "mo" and under.text in ("_", "¯", "‾", "̲"):
			return self.speak(base) + ["subrayado"]
		if under.tag == "mo" and under.text in ACCENT_NAMES:
			return self.speak(base) + [ACCENT_NAMES[under.text]]
		if self.v == "breve":
			return self.speak(base) + ["bajo"] + self.speak(under)
		return self.speak(base) + ["con"] + self.speak(under) + ["debajo"]

	def _mover(self, node: MathNode) -> list:
		base, over = node.children
		if isBigOperator(base):
			return self._largeOp(base, None, over, node)
		if over.tag == "mo" and over.text in ("→", "⃗", "⟶"):
			return ["vector"] + self.speak(base)
		if over.tag == "mo" and over.text in ACCENT_NAMES:
			name = ACCENT_NAMES[over.text]
			if name == "barra" and base.tag != "mi" and not isSimple(base):
				return ["línea sobre"] + self.speak(base) + ([SHORT, "fin de línea"] if not self._isTrailing(node) else [])
			if name == "circunflejo":
				name = "circunflejo" if self.v == "detallado" else "sombrero"
			return self.speak(base) + [name]
		if self.v == "breve":
			return self.speak(base) + ["sobre"] + self.speak(over)
		return self.speak(base) + ["con"] + self.speak(over) + ["encima"]

	def _munderover(self, node: MathNode) -> list:
		base, under, over = node.children
		if isBigOperator(base):
			return self._largeOp(base, under, over, node)
		if self.v == "breve":
			return self.speak(base) + ["bajo"] + self.speak(under) + ["sobre"] + self.speak(over)
		return self.speak(base) + ["con"] + self.speak(under) + ["debajo y"] + self.speak(over) + ["encima"]

	def _largeOp(self, op: MathNode, lower: MathNode | None, upper: MathNode | None, node: MathNode) -> list:
		name = OPERATORS.get(op.text, characterName(op.text))
		out: list = [name]
		if lower is not None and upper is not None:
			out += ["desde"] + self.speak(lower) + ["hasta"] + self.speak(upper)
		elif lower is not None:
			kids = realChildren(lower) if lower.tag == "mrow" else []
			if op.text in INTEGRALS:
				out += ["sobre"] + self.speak(lower)
			elif kids and any(k.isMo("∈", "⊂", "⊆", "<", ">", "≤", "≥") for k in kids):
				out += ["para"] + self.speak(lower)
			else:
				out += ["sobre"] + self.speak(lower)
		elif upper is not None:
			out += ["hasta"] + self.speak(upper)
		if self.v != "breve" and (lower is not None or upper is not None):
			out.append(SHORT)
		out.append("de")
		return out

	def _limitLike(self, base: MathNode, under: MathNode, node: MathNode) -> list:
		name = FUNCTIONS.get(base.text, base.text)
		kids = realChildren(under) if under.tag == "mrow" else []
		if base.text.startswith("lim") and any(k.isMo("→", "⟶", "↘", "↗") for k in kids):
			cond = ["cuando"] + self.speak(under)
		else:
			cond = ["para"] + self.speak(under)
		return [name] + cond + ([SHORT] if self.v != "breve" else []) + ["de"]

	def _mmultiscripts(self, node: MathNode) -> list:
		kids = node.children
		if not kids:
			return []
		base = kids[0]
		post: list[MathNode] = []
		pre: list[MathNode] = []
		target = post
		for c in kids[1:]:
			if c.tag == "mprescripts":
				target = pre
				continue
			target.append(c)
		out: list = []
		for i in range(0, len(pre) - 1, 2):
			sub, sup = pre[i], pre[i + 1]
			if sub.tag != "none":
				out += ["subíndice previo"] + self.speak(sub)
			if sup.tag != "none":
				out += ["superíndice previo"] + self.speak(sup)
		if out:
			out.append(SHORT)
		out += self.speak(base)
		for i in range(0, len(post) - 1, 2):
			sub, sup = post[i], post[i + 1]
			if sub.tag != "none":
				out += ["sub"] + self.speak(sub)
			if sup.tag != "none":
				out += ["superíndice"] + self.speak(sup)
		return out

	# ------------------------------------------------------------ tablas
	def _mtable(self, node: MathNode) -> list:
		rows = [r for r in node.children if r.tag in ("mtr", "mlabeledtr")]
		nRows = len(rows)
		if nRows and all(any(c.isMo("=", "<", ">", "≤", "≥", "≠") for c in r.iter()) for r in rows):
			label = "ecuación"
			out: list = [f"sistema de {nRows} ecuaciones" if nRows != 1 else "1 ecuación"]
		else:
			label = "fila"
			nCols = max((len([c for c in r.children if c.tag == "mtd"]) for r in rows), default=0)
			out = [f"tabla de {nRows} filas y {nCols} columnas" if self.v != "breve" else f"tabla {nRows} por {nCols}"]
		for i, r in enumerate(rows, 1):
			out.append(MEDIUM)
			out.append(f"{label} {i}")
			cells = [c for c in r.children if c.tag == "mtd"]
			for j, c in enumerate(cells):
				if j:
					out.append(SHORT)
				out.extend(self.speak(c))
		if self.v != "breve":
			out += [MEDIUM, "fin de la tabla" if label == "fila" else "fin del sistema"]
		return out

	def _cases(self, table: MathNode) -> list:
		rows = [r for r in table.children if r.tag in ("mtr", "mlabeledtr")]
		out: list = [f"{len(rows)} casos" if len(rows) != 1 else "1 caso"]
		for i, r in enumerate(rows, 1):
			out += [MEDIUM, f"caso {i}"]
			cells = [c for c in r.children if c.tag == "mtd"]
			for j, c in enumerate(cells):
				if j:
					out.append(SHORT)
					txt = c.textContent().strip().lower()
					if not (txt.startswith("si") or txt.startswith("if") or txt.startswith("en otro") or txt.startswith("otherwise") or txt.startswith("para")):
						out.append("si")
				out.extend(self.speak(c))
		if self.v != "breve":
			out += [MEDIUM, "fin de los casos"]
		return out

	def _matrix(self, table: MathNode, o: str, c: str) -> list:
		rows = [r for r in table.children if r.tag in ("mtr", "mlabeledtr")]
		nRows = len(rows)
		nCols = max((len([x for x in r.children if x.tag == "mtd"]) for r in rows), default=0)
		det = o in ("|", "∣") and c in ("|", "∣")
		kind = "determinante" if det else "matriz"
		if not det and nCols == 1 and nRows > 1:
			head = f"vector columna de {nRows} componentes"
			out: list = [head]
			for i, r in enumerate(rows, 1):
				out.append(SHORT)
				if self.v == "detallado":
					out.append(f"componente {i}")
				out.extend(self._mtr(r))
			if self.v != "breve":
				out += [SHORT, "fin del vector"]
			return out
		if not det and nRows == 1 and nCols > 1:
			out = [f"vector fila de {nCols} componentes"]
			cells = [x for x in rows[0].children if x.tag == "mtd"]
			for j, cell in enumerate(cells, 1):
				out.append(SHORT)
				if self.v == "detallado":
					out.append(f"componente {j}")
				out.extend(self.speak(cell))
			if self.v != "breve":
				out += [SHORT, "fin del vector"]
			return out
		out = [f"{kind} de {nRows} por {nCols}"]
		for i, r in enumerate(rows, 1):
			out.append(MEDIUM)
			if self.v != "breve":
				out.append(f"fila {i}")
			cells = [x for x in r.children if x.tag == "mtd"]
			for j, cell in enumerate(cells, 1):
				if j > 1 or self.v == "detallado":
					out.append(SHORT)
				if self.v == "detallado":
					out.append(f"columna {j}")
				out.extend(self.speak(cell))
		if self.v != "breve":
			out += [MEDIUM, f"fin {'del' if det else 'de la'} {kind}"]
		return out

	# ------------------------------------------------------------ otros
	def _menclose(self, node: MathNode) -> list:
		notations = node.get("notation", "longdiv").split()
		names = [ENCLOSE_NAMES.get(n, n) for n in notations]
		label = " y ".join(dict.fromkeys(names))
		inner = self._math(node)
		if self.v == "breve":
			return [label] + inner
		return [label, SHORT] + inner + [SHORT, f"fin de {label}"]

	def _mlabeledtr(self, node: MathNode) -> list:
		return self._mtr(node)


# ====================================================================== utilidades
def toText(seq: list, pauses: bool = True) -> str:
	"""Convierte la secuencia en texto (pausas como comas si ``pauses``)."""
	parts: list[str] = []
	for item in seq:
		if isinstance(item, Pause):
			if pauses and parts and not parts[-1].endswith(","):
				parts[-1] = parts[-1] + ","
			continue
		s = str(item).strip()
		if s:
			parts.append(s)
	text = " ".join(parts)
	text = re.sub(r"\s+", " ", text).strip()
	return text.rstrip(",").strip()


def toSpeechSequence(seq: list, usePauses: bool = True) -> list:
	"""Secuencia para :func:`tiresias.speech.speak` (cadenas y pausas)."""
	from ..speech.commands import BreakCommand

	out: list = []
	buf: list[str] = []
	for item in seq:
		if isinstance(item, Pause):
			if buf:
				out.append(" ".join(buf))
				buf = []
			if usePauses and out and not isinstance(out[-1], BreakCommand):
				out.append(BreakCommand(item.ms))
			continue
		s = str(item).strip()
		if s:
			buf.append(s)
	if buf:
		out.append(" ".join(buf))
	while out and isinstance(out[-1], BreakCommand):
		out.pop()
	return out


def _pauseAfterEndMarkers(seq: list) -> list:
	"""Añade una pausa tras cada marca de fin («fin de fracción»...)."""
	out: list = []
	for item in seq:
		out.append(item)
		if isinstance(item, str) and item.startswith("fin "):
			out.append(SHORT)
	return out


def speakNode(node: MathNode, options: SpeechOptions | None = None) -> list:
	return _pauseAfterEndMarkers(SpeechGenerator(options).speak(node))


def nodeText(node: MathNode, options: SpeechOptions | None = None, pauses: bool = True) -> str:
	return toText(speakNode(node, options), pauses)
