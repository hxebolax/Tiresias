"""Analizador de texto: incoherencias de escritura (como el Text Analyzer de JAWS).

Funciones puras (sin UIA ni configuración) para poder probarlas:

- :func:`analyze`: incidencias de un texto completo.
- :func:`formatIssues`: incidencias de formato a partir de tramos de formato.
- :func:`issuesInRange`, :func:`nextIssue`: búsqueda por posición.

Tipos de incidencia (``Issue.kind``):

- ``unclosed``: paréntesis, corchete, llave, comilla o signo de apertura
  (¿ ¡) sin cerrar dentro de su párrafo.
- ``unopened``: cierre sin apertura.
- ``doubleSpace``: dos o más espacios seguidos dentro de una línea.
- ``spaceBeforePunct``: espacio antes de coma, punto, punto y coma...
- ``lowercaseAfterPeriod``: minúscula al empezar una frase tras un punto.
- ``repeatedWord``: palabra repetida («el el»).
- ``mixedCase``: mayúsculas raras dentro de una palabra («hOla»).
- ``format``: formato incoherente (lo calcula :func:`formatIssues`).

Los pares se comprueban por párrafo (hasta la siguiente línea en blanco),
así un paréntesis que se cierra en la línea siguiente no es un error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..i18n import _

KINDS = ("unclosed", "unopened", "doubleSpace", "spaceBeforePunct", "lowercaseAfterPeriod", "repeatedWord", "mixedCase", "format")

#: Opciones por defecto: qué se comprueba.
DEFAULT_CHECKS = {
	"brackets": True,
	"quotes": True,
	"spanishMarks": True,
	"doubleSpace": True,
	"spaceBeforePunct": True,
	"lowercaseAfterPeriod": True,
	"repeatedWord": True,
	"mixedCase": False,
	"format": True,
}

_PAIRS = {"(": ")", "[": "]", "{": "}", "«": "»", "“": "”"}
_SPANISH = {"¿": "?", "¡": "!"}
_CLOSERS = {v: k for k, v in _PAIRS.items()}

#: Abreviaturas tras las que una minúscula es normal.
ABBREVIATIONS = {
	"etc", "p. ej", "ej", "sr", "sra", "srta", "dr", "dra", "ud", "uds", "vd", "vds", "pág", "págs", "núm", "nº", "aprox",
	"vs", "e.g", "i.e", "cf", "fig", "vol", "cap", "art", "tel", "av", "avda", "dña", "lic", "ing", "prof",
	"mr", "mrs", "ms", "st", "approx", "min", "máx", "mín", "ss", "a.c", "d.c",
}

_NAMES = {
	"unclosed": _("sin cerrar"),
	"unopened": _("sin abrir"),
	"doubleSpace": _("espacio doble"),
	"spaceBeforePunct": _("espacio antes de puntuación"),
	"lowercaseAfterPeriod": _("minúscula tras punto"),
	"repeatedWord": _("palabra repetida"),
	"mixedCase": _("mayúsculas raras"),
	"format": _("formato incoherente"),
}


@dataclass(frozen=True)
class Issue:
	start: int
	end: int
	kind: str
	message: str

	def __lt__(self, other: "Issue") -> bool:
		return (self.start, self.end, self.kind) < (other.start, other.end, other.kind)


def kindName(kind: str) -> str:
	return _NAMES.get(kind, kind)


def _charName(ch: str) -> str:
	names = {
		"(": _("paréntesis"),
		")": _("paréntesis"),
		"[": _("corchete"),
		"]": _("corchete"),
		"{": _("llave"),
		"}": _("llave"),
		"«": _("comillas angulares"),
		"»": _("comillas angulares"),
		"“": _("comillas"),
		"”": _("comillas"),
		'"': _("comillas"),
		"¿": _("signo de interrogación"),
		"?": _("signo de interrogación"),
		"¡": _("signo de exclamación"),
		"!": _("signo de exclamación"),
	}
	return names.get(ch, ch)


def _paragraphs(text: str):
	"""(inicio, fin) de cada párrafo: bloques separados por líneas en blanco."""
	start = 0
	for m in re.finditer(r"\n[ \t\r]*\n", text):
		yield start, m.start()
		start = m.end()
	yield start, len(text)


def _checkPairs(text: str, start: int, end: int, checks: dict, out: list[Issue]) -> None:
	stack: list[tuple[str, int]] = []
	spanishOpen: dict[str, list[int]] = {"¿": [], "¡": []}
	straightQuotes: list[int] = []
	for i in range(start, end):
		ch = text[i]
		if checks.get("brackets", True) and ch in "([{" or checks.get("quotes", True) and ch in "«“":
			stack.append((ch, i))
		elif checks.get("brackets", True) and ch in ")]}" or checks.get("quotes", True) and ch in "»”":
			opener = _CLOSERS[ch]
			if ch == ")":
				# «1) primer punto», «a) opción»: numeración de listas, no es un error.
				lineStart = max(start, text.rfind("\n", start, i) + 1)
				if re.fullmatch(r"[ \t]*[0-9a-zA-Z]{1,3}", text[lineStart:i]):
					continue
			# Busca su apertura (tolerando otras mal anidadas por encima).
			for j in range(len(stack) - 1, -1, -1):
				if stack[j][0] == opener:
					del stack[j]
					break
			else:
				out.append(Issue(i, i + 1, "unopened", _("{name} de cierre sin abrir").format(name=_charName(ch))))
		elif checks.get("quotes", True) and ch == '"':
			straightQuotes.append(i)
		elif checks.get("spanishMarks", True) and ch in _SPANISH:
			spanishOpen[ch].append(i)
		elif checks.get("spanishMarks", True) and ch in "?!":
			opener = "¿" if ch == "?" else "¡"
			if spanishOpen[opener]:
				spanishOpen[opener].pop()
	for ch, i in stack:
		out.append(Issue(i, i + 1, "unclosed", _("{name} sin cerrar").format(name=_charName(ch))))
	if len(straightQuotes) % 2:
		i = straightQuotes[-1]
		out.append(Issue(i, i + 1, "unclosed", _("comillas sin cerrar")))
	for opener, positions in spanishOpen.items():
		for i in positions:
			out.append(Issue(i, i + 1, "unclosed", _("{name} de apertura sin cerrar").format(name=_charName(opener))))


_DOUBLE_SPACE = re.compile(r"(?<=\S)[ \u00a0]{2,}(?=\S)")
_SPACE_BEFORE = re.compile(r"(?<=[^\s(\[{¿¡«“])[ \u00a0]+(?=[,;:!?)\]}»”]|\.(?![.\d]))")
_SENTENCE = re.compile(r"(?<![.…])([^\s.…]*)\.[ \u00a0]+([a-zñáéíóúü])")
_WORD = re.compile(r"\b(\w+)\b[ \u00a0]+\b(\1)\b", re.IGNORECASE)
_MIXED = re.compile(r"\b[a-záéíóúñü]+[A-ZÁÉÍÓÚÑÜ]+[a-záéíóúñü]*[A-ZÁÉÍÓÚÑÜ]*\b|\b[A-ZÁÉÍÓÚÑÜ]{2,}[a-záéíóúñü]+\b")
#: Palabras que se repiten a propósito con frecuencia.
_REPEAT_OK = {"que", "no", "si", "sí", "ja", "je", "bla", "muy", "tan", "poco", "had", "that", "very"}


def _isAbbreviation(word: str, text: str, dot: int) -> bool:
	w = word.lower().strip("(«“\"'")
	if not w:
		return True
	if w in ABBREVIATIONS:
		return True
	# «p. ej.», «a. C.»: mira también la palabra anterior.
	prev = text[max(0, dot - 8) : dot].lower()
	if re.search(r"\b(p\. ej|a\. c|d\. c)$", prev):
		return True
	# Iniciales y abreviaturas de una letra («J. R. R.»), números («1.º»).
	if len(w) == 1 or w.isdigit():
		return True
	# Direcciones y archivos («ejemplo.com», «v1.2») no llegan aquí con espacio.
	return False


def analyze(text: str, checks: dict | None = None) -> list[Issue]:
	"""Incidencias del texto, ordenadas por posición."""
	c = dict(DEFAULT_CHECKS)
	if checks:
		c.update(checks)
	out: list[Issue] = []
	if not text:
		return out
	if c["brackets"] or c["quotes"] or c["spanishMarks"]:
		for s, e in _paragraphs(text):
			_checkPairs(text, s, e, c, out)
	if c["doubleSpace"]:
		for m in _DOUBLE_SPACE.finditer(text):
			out.append(Issue(m.start(), m.end(), "doubleSpace", _("espacio doble")))
	if c["spaceBeforePunct"]:
		for m in _SPACE_BEFORE.finditer(text):
			punct = text[m.end()]
			out.append(Issue(m.start(), m.end(), "spaceBeforePunct", _("espacio antes de {char}").format(char=_punctName(punct))))
	if c["lowercaseAfterPeriod"]:
		for m in _SENTENCE.finditer(text):
			if _isAbbreviation(m.group(1), text, m.start(1) + len(m.group(1))):
				continue
			pos = m.start(2)
			out.append(Issue(pos, pos + 1, "lowercaseAfterPeriod", _("minúscula después de punto")))
	if c["repeatedWord"]:
		for m in _WORD.finditer(text):
			w = m.group(1)
			if w.lower() in _REPEAT_OK or w.isdigit():
				continue
			out.append(Issue(m.start(2), m.end(2), "repeatedWord", _("palabra repetida: {word}").format(word=w)))
	if c["mixedCase"]:
		for m in _MIXED.finditer(text):
			out.append(Issue(m.start(), m.end(), "mixedCase", _("mayúsculas raras en {word}").format(word=m.group(0))))
	out.sort()
	return out


def _punctName(ch: str) -> str:
	names = {
		",": _("coma"),
		";": _("punto y coma"),
		":": _("dos puntos"),
		".": _("punto"),
		"!": _("cierre de exclamación"),
		"?": _("cierre de interrogación"),
		")": _("cierre de paréntesis"),
		"]": _("cierre de corchete"),
		"}": _("cierre de llave"),
		"»": _("cierre de comillas"),
		"”": _("cierre de comillas"),
		"%": _("signo de porcentaje"),
	}
	return names.get(ch, ch)


# ------------------------------------------------------------------ formato
@dataclass(frozen=True)
class FormatRun:
	"""Tramo de texto con el mismo formato: ``[start, end)`` en el texto."""

	start: int
	end: int
	fontName: str | None = None
	fontSize: float | None = None


def _fmtLabel(run: FormatRun) -> str:
	parts = []
	if run.fontName:
		parts.append(run.fontName)
	if run.fontSize:
		size = run.fontSize
		parts.append(_("{size} puntos").format(size=int(size) if float(size).is_integer() else size))
	return " ".join(parts)


def formatIssues(text: str, runs: list[FormatRun]) -> list[Issue]:
	"""Formato incoherente.

	- Cambio de fuente o de tamaño dentro de una palabra.
	- Un tramo corto (hasta 3 palabras) con una fuente o un tamaño distinto
	  del texto que lo rodea por los dos lados (que sí coinciden entre sí).
	"""
	out: list[Issue] = []

	def fmt(r: FormatRun) -> tuple:
		return (r.fontName, r.fontSize)

	for i in range(1, len(runs)):
		a, b = runs[i - 1], runs[i]
		if fmt(a) == fmt(b):
			continue
		pos = b.start
		if 0 < pos < len(text) and text[pos - 1].isalnum() and text[pos].isalnum():
			out.append(Issue(pos, pos + 1, "format", _("cambio de formato dentro de una palabra: {fmt}").format(fmt=_fmtLabel(b))))
	for i in range(1, len(runs) - 1):
		prev, cur, nxt = runs[i - 1], runs[i], runs[i + 1]
		if fmt(prev) != fmt(nxt) or fmt(cur) == fmt(prev):
			continue
		chunk = text[cur.start : cur.end]
		if not chunk.strip() or len(chunk.split()) > 3:
			continue
		out.append(Issue(cur.start, cur.end, "format", _("formato distinto del texto que lo rodea: {fmt}").format(fmt=_fmtLabel(cur))))
	# Sin duplicados en la misma posición.
	seen: set = set()
	unique = []
	for it in sorted(out):
		if (it.start, it.kind) in seen:
			continue
		seen.add((it.start, it.kind))
		unique.append(it)
	return unique


# ------------------------------------------------------------------ búsqueda
def issuesInRange(issues: list[Issue], start: int, end: int) -> list[Issue]:
	"""Incidencias que empiezan en ``[start, end)``."""
	return [i for i in issues if start <= i.start < end]


def nextIssue(issues: list[Issue], offset: int, direction: int) -> Issue | None:
	"""Siguiente (1) o anterior (-1) incidencia respecto a ``offset``."""
	if direction > 0:
		for it in issues:
			if it.start > offset:
				return it
		return None
	for it in reversed(issues):
		if it.start < offset:
			return it
	return None


def describe(issues: list[Issue]) -> str:
	"""Frase con las incidencias (para anunciarlas)."""
	return "; ".join(i.message for i in issues)
