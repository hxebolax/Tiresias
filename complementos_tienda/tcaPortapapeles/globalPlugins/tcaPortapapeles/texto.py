"""Estadísticas de un texto y troceado en palabras (funciones puras)."""

from __future__ import annotations

import re
import string
from dataclasses import dataclass

#: Signos que se quitan al trocear en palabras (los de ASCII más ¿ y ¡, como el original).
SIGNOS = string.punctuation + "¿¡"
_SIGNOS_RE = re.compile("[" + re.escape(SIGNOS) + "]")
_PALABRA_RE = re.compile(r"\w+")


@dataclass(frozen=True)
class Estadisticas:
	sinEspacios: int
	conEspacios: int
	palabras: int
	lineas: int
	parrafos: int


def estadisticas(texto: str) -> Estadisticas:
	"""Cuenta caracteres (sin y con espacios, sin los saltos de línea), palabras, líneas y párrafos.

	Un párrafo es un bloque de líneas con texto separado de otro por líneas en blanco.
	"""
	lineas = texto.splitlines()
	sinEspacios = sum(1 for c in texto if not c.isspace())
	conEspacios = sum(1 for c in texto if c not in "\r\n\x0b\x0c\x1c\x1d\x1e\x85  ")
	parrafos = 0
	enBloque = False
	for linea in lineas:
		if linea.strip():
			if not enBloque:
				parrafos += 1
			enBloque = True
		else:
			enBloque = False
	return Estadisticas(sinEspacios, conEspacios, len(_PALABRA_RE.findall(texto)), len(lineas), parrafos)


def _plural(n: int, singular: str, plural: str) -> str:
	return f"{n} {singular if n == 1 else plural}"


def mensajeEstadisticas(e: Estadisticas) -> str:
	return "\n".join(
		[
			_plural(e.sinEspacios, "carácter", "caracteres") + " (sin espacios).",
			_plural(e.conEspacios, "carácter", "caracteres") + " (con espacios).",
			_plural(e.palabras, "palabra", "palabras") + ".",
			_plural(e.lineas, "línea", "líneas") + ".",
			_plural(e.parrafos, "párrafo", "párrafos") + ".",
		]
	)


def trocear(texto: str, conservarSignos: bool = False) -> list[str]:
	"""Palabras de ``texto`` en su orden; sin signos de puntuación salvo que se pida conservarlos."""
	if not conservarSignos:
		texto = _SIGNOS_RE.sub("", texto)
	return texto.split()


def unirSeleccion(palabras: list[str], marcadas: list[int]) -> str:
	"""Las palabras marcadas en el orden del texto original (no en el que se marcaron)."""
	return " ".join(palabras[i] for i in sorted(set(marcadas)) if 0 <= i < len(palabras))
