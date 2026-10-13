"""Tipos de navegación rápida añadidos al modo exploración.

Se suman a ``document.QUICK_NAV``. Una tecla vacía significa «sin gesto»:
la orden existe (siguiente y anterior) y se puede asignar en «Gestos de
entrada» o usar desde la paleta de órdenes.

Teclas: 7, 8 y 9 (encabezados de nivel 7 a 9), ñ (anotación), guion
(error) y punto (vistazo: lo que destaca visualmente).
"""

from __future__ import annotations

from ..i18n import _
from ..objects.roles import HEADING_ROLES, Role, State
from . import aria as ariaSem


def _headingLevel(level: int):
	return lambda n: n.role in HEADING_ROLES and n.headingLevel() == level


_ANNOTATION_FMTS = {"mark", "comment", "insertion", "deletion", "suggestion"}


def isAnnotation(n) -> bool:
	return n.fmt in _ANNOTATION_FMTS or bool(n.relations.get("details")) or n.role in (Role.COMMENT, Role.SUGGESTION)


def isError(n) -> bool:
	inv = (n.aria.get("invalid") or "").lower()
	return inv in ("true", "spelling", "grammar") or State.INVALID_ENTRY in n.states


def isReference(n) -> bool:
	return n.role == Role.LINK and (ariaSem.isReferenceLct(n.lct) or n.ariaRole in ("doc-noteref", "doc-biblioref", "doc-glossref", "doc-backlink"))


def isPageBreak(n) -> bool:
	return n.role == Role.SEPARATOR and (n.lct in ariaSem.PAGEBREAK_LCT or n.ariaRole == "doc-pagebreak")


#: (tecla, identificador, singular, plural, predicado).
EXTRA_QUICK_NAV = [
	("7", "heading7", _("encabezado de nivel 7"), _("encabezados de nivel 7"), _headingLevel(7)),
	("8", "heading8", _("encabezado de nivel 8"), _("encabezados de nivel 8"), _headingLevel(8)),
	("9", "heading9", _("encabezado de nivel 9"), _("encabezados de nivel 9"), _headingLevel(9)),
	("ñ", "annotation", _("anotación"), _("anotaciones"), isAnnotation),
	("-", "error", _("error"), _("errores"), isError),
	(".", "glance", _("elemento destacado"), _("elementos destacados"), lambda n: False),
	("", "slider", _("deslizador"), _("deslizadores"), lambda n: n.role == Role.SLIDER),
	("", "clickable", _("elemento pulsable"), _("elementos pulsables"), lambda n: n.clickable),
	("", "grouping", _("agrupación"), _("agrupaciones"), lambda n: n.role == Role.GROUPING and bool(n.name)),
	("", "figure", _("figura"), _("figuras"), lambda n: n.role == Role.FIGURE),
	("", "toggleButton", _("botón de alternar"), _("botones de alternar"), lambda n: n.role in (Role.TOGGLEBUTTON, Role.SWITCH)),
	("", "progressBar", _("barra de progreso"), _("barras de progreso"), lambda n: n.role == Role.PROGRESSBAR),
	("", "verticalParagraph", _("párrafo alineado verticalmente"), _("párrafos alineados verticalmente"), lambda n: False),
	("", "sameStyle", _("texto del mismo estilo"), _("textos del mismo estilo"), lambda n: False),
	("", "differentStyle", _("texto de distinto estilo"), _("textos de distinto estilo"), lambda n: False),
	("", "reference", _("referencia"), _("referencias"), isReference),
	("", "pageBreak", _("salto de página"), _("saltos de página"), isPageBreak),
	("", "mainLandmark", _("contenido principal"), _("contenidos principales"), lambda n: n.role == Role.LANDMARK and n.landmark in (_("principal"), "main")),
]

#: Tipos cuyo predicado depende de la posición del cursor (estilo, alineación...).
DYNAMIC_KINDS = {"glance", "verticalParagraph", "sameStyle", "differentStyle"}


#: Tiempo máximo (s) que una búsqueda por estilo dedica a consultar la aplicación.
STYLE_SEARCH_BUDGET = 2.0


def _budgeted(pred, budget: float | None = None):
	"""Predicado que deja de consultar la aplicación pasado un tiempo (M8).

	Cada bloque nuevo cuesta varias llamadas al documento (estilo del texto);
	en una página enorme la búsqueda dejaba el lector sin responder.
	"""
	import time

	limit = STYLE_SEARCH_BUDGET if budget is None else budget
	start = [None]

	def check(n) -> bool:
		now = time.monotonic()
		if start[0] is None:
			start[0] = now
		elif now - start[0] > limit:
			return False
		return pred(n)

	return check


def dynamicPredicate(doc, ident: str, pred):
	"""Predicado definitivo de un tipo (algunos dependen del cursor o de opciones)."""
	from ..config import conf

	buf = doc.buffer
	if ident in DYNAMIC_KINDS:
		from . import style

		node = buf.nodeAt(doc.caret)
		cur = buf.blockOf(node) if node is not None else None
		blocks = {id(b) for b in style.textBlocks(buf)}
		if ident == "glance":
			return _budgeted(lambda n: id(n) in blocks and style.isProminent(doc, n))
		if ident == "verticalParagraph":
			return lambda n: id(n) in blocks and style.isVerticallyAligned(cur, n)
		ref = style.blockStyle(doc, cur) if cur is not None else None
		if ref is None:
			return lambda n: False
		if ident == "sameStyle":
			return _budgeted(lambda n: id(n) in blocks and n is not cur and style.blockStyle(doc, n) == ref)
		return _budgeted(lambda n: id(n) in blocks and n is not cur and style.blockStyle(doc, n) not in (None, ref))
	if ident == "listItem" and conf["browseMode"]["listItemWithinList"]:
		# Solo los elementos de la lista actual (#8193).
		node = buf.nodeAt(doc.caret)
		lst = next((a for a in ([node] + list(node.ancestors()) if node is not None else []) if a.role == Role.LIST), None)
		if lst is not None:
			return lambda n: pred(n) and next((a for a in n.ancestors() if a.role == Role.LIST), None) is lst
	return pred
