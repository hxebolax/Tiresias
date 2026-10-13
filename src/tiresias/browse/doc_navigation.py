"""Opciones de «Navegación por documentos» (sección ``documentNavigation``).

La tecla P del modo exploración salta de párrafo en párrafo. Muchas páginas
no marcan sus párrafos, así que además se reconocen los **párrafos de
texto**: bloques de texto de cierta longitud que terminan en un signo de
puntuación final (expresión regular ``textParagraphRegex``).

``paragraphQuickNav``:

- ``role``: solo los párrafos marcados como tales por la página;
- ``text``: solo los párrafos de texto según la expresión regular;
- ``both``: los dos (por defecto).
"""

from __future__ import annotations

import re
from typing import Any, Callable

from ..config import conf
from ..log import getLogger
from ..objects.roles import Role

log = getLogger("docNavigation")

_cache: tuple[str, re.Pattern | None] = ("", None)

#: Roles que pueden ser un párrafo de texto.
TEXT_BLOCK_ROLES = {Role.STATICTEXT, Role.PARAGRAPH, Role.SECTION, Role.LISTITEM, Role.BLOCKQUOTE}


def compileRegex(pattern: str) -> re.Pattern | None:
	"""Compila la expresión (``None`` si no es válida)."""
	global _cache
	if _cache[0] == pattern:
		return _cache[1]
	try:
		rx: re.Pattern | None = re.compile(pattern, re.S)
	except re.error:
		log.warning("Expresión de párrafo de texto no válida: %r", pattern)
		rx = None
	_cache = (pattern, rx)
	return rx


def isTextParagraph(text: str, pattern: str | None = None, minLength: int | None = None) -> bool:
	sec = conf["documentNavigation"]
	pattern = sec["textParagraphRegex"] if pattern is None else pattern
	minLength = sec["textParagraphMinLength"] if minLength is None else minLength
	text = (text or "").strip()
	if len(text) < minLength:
		return False
	rx = compileRegex(pattern)
	return bool(rx and rx.search(text))


def _isRoleParagraph(n: Any) -> bool:
	return n.role == Role.PARAGRAPH or getattr(n, "ariaRole", "") == "paragraph"


def paragraphPredicate(buffer: Any, rolePredicate: Callable[[Any], bool] | None = None) -> Callable[[Any], bool]:
	"""Predicado de la tecla P según ``documentNavigation.paragraphQuickNav``."""
	mode = conf["documentNavigation"]["paragraphQuickNav"]
	rolePred = rolePredicate or _isRoleParagraph
	if mode == "role":
		return rolePred
	text = getattr(buffer, "text", "") or ""

	def isText(n: Any) -> bool:
		if n.role not in TEXT_BLOCK_ROLES:
			return False
		if n.role == Role.STATICTEXT:
			# El texto dentro de un párrafo ya cuenta con el párrafo.
			parent = getattr(n, "parent", None)
			while parent is not None:
				if _isRoleParagraph(parent):
					return False
				parent = getattr(parent, "parent", None)
		elif n.role != Role.PARAGRAPH and getattr(n, "children", None):
			# Contenedores con hijos: se evalúan los hijos.
			return False
		return isTextParagraph(text[n.start : n.end])

	if mode == "text":
		return isText
	return lambda n: rolePred(n) or isText(n)
