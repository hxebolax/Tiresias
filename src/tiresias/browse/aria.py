"""Semántica ARIA y UIA del modo exploración.

Etiquetas habladas de propiedades que no son estados simples: subtipos de
``aria-haspopup``, valor de ``aria-current``, ``aria-sort``,
``aria-orientation``, tipo de enlace, roles DPUB y otros roles que los
navegadores solo exponen con su «tipo de control localizado».
"""

from __future__ import annotations

from urllib.parse import urlsplit

from ..i18n import _
from ..objects.roles import Role

# ---------------------------------------------------------------- aria-haspopup
_HASPOPUP = {
	"true": _("submenú"),
	"menu": _("abre un menú"),
	"listbox": _("abre una lista"),
	"tree": _("abre un árbol"),
	"grid": _("abre una cuadrícula"),
	"dialog": _("abre un diálogo"),
}


def haspopupLabel(value: str | None) -> str:
	"""Texto de ``aria-haspopup`` (cadena vacía si no hay emergente)."""
	if not value or value == "false":
		return ""
	return _HASPOPUP.get(value.lower(), _HASPOPUP["true"])


# ---------------------------------------------------------------- aria-current
_CURRENT = {
	"page": _("página actual"),
	"step": _("paso actual"),
	"location": _("ubicación actual"),
	"date": _("fecha actual"),
	"time": _("hora actual"),
	"true": _("actual"),
}


def currentLabel(value: str | None) -> str:
	if not value or value == "false":
		return ""
	return _CURRENT.get(value.lower(), _CURRENT["true"])


# ---------------------------------------------------------------- aria-sort
_SORT = {
	"ascending": _("orden ascendente"),
	"descending": _("orden descendente"),
	"other": _("ordenado"),
}


def sortLabel(value: str | None) -> str:
	if not value or value == "none":
		return ""
	return _SORT.get(value.lower(), "")


# ---------------------------------------------------------------- aria-orientation
#: Roles cuya orientación por defecto es vertical (se anuncia «horizontal»).
_VERTICAL_BY_DEFAULT = {Role.LIST, Role.POPUPMENU, Role.TREEVIEW, Role.SCROLLBAR}
#: Roles en los que la orientación tiene interés (#6283).
ORIENTATION_ROLES = {Role.SLIDER, Role.SCROLLBAR, Role.TOOLBAR, Role.TABCONTROL, Role.SEPARATOR, Role.LIST, Role.POPUPMENU, Role.MENUBAR, Role.TREEVIEW, Role.RADIOBUTTON}

ORIENTATION_HORIZONTAL = 1
ORIENTATION_VERTICAL = 2


def orientationLabel(role: Role, orientation: int) -> str:
	"""Solo se anuncia la orientación que no es la habitual del rol."""
	if role not in ORIENTATION_ROLES or orientation not in (ORIENTATION_HORIZONTAL, ORIENTATION_VERTICAL):
		return ""
	if role in _VERTICAL_BY_DEFAULT:
		return _("horizontal") if orientation == ORIENTATION_HORIZONTAL else ""
	return _("vertical") if orientation == ORIENTATION_VERTICAL else ""


# ---------------------------------------------------------------- tipo de enlace
LINK_SAME_PAGE = "samePage"
LINK_SAME_SITE = "sameSite"
LINK_EXTERNAL = "external"


def linkType(url: str, documentUrl: str) -> str:
	"""Clasifica un enlace: ancla en la página, mismo sitio o externo."""
	if not url or not documentUrl:
		return ""
	try:
		a = urlsplit(url.strip())
		b = urlsplit(documentUrl.strip())
	except ValueError:
		return ""
	if a.scheme.lower() in ("javascript", "mailto", "tel"):
		return ""
	same = (a.scheme.lower(), a.netloc.lower()) == (b.scheme.lower(), b.netloc.lower())
	if same and a.fragment and (a.path or "/") == (b.path or "/") and a.query == b.query:
		return LINK_SAME_PAGE
	if same or not a.netloc:
		return LINK_SAME_SITE
	return LINK_EXTERNAL


def linkTypeLabel(url: str, documentUrl: str) -> str:
	kind = linkType(url, documentUrl)
	if kind == LINK_SAME_PAGE:
		return _("en esta página")
	if kind == LINK_EXTERNAL:
		return _("externo")
	return ""


def fragmentOf(url: str) -> str:
	try:
		return urlsplit(url).fragment
	except ValueError:
		return ""


# ---------------------------------------------------------------- tipos localizados
#: Tipos de control localizados «normales» (no aportan nada al anunciarlos).
#: Los navegadores exponen con el tipo localizado los roles que UIA no tiene
#: (DPUB, término, definición, nota al pie, capítulo...).
_PLAIN_LCT = {
	"",
	"grupo",
	"group",
	"sección",
	"section",
	"elemento de lista",
	"list item",
	"separador",
	"separator",
	"vínculo",
	"link",
	"hipervínculo",
	"hyperlink",
	"texto",
	"text",
	"descripción",
	"description",
	"región",
	"region",
	"panel",
	"pane",
	"párrafo",
	"paragraph",
	"genérico",
	"generic",
	"contenido",
	"content",
	"estado",
	"status",
	"registro",
	"log",
	"nota",
	"note",
	"etiqueta",
	"label",
	"elemento",
	"item",
}

#: Tipos localizados de figura (Edge traduce «figure» como «cifra»).
FIGURE_LCT = {"figura", "figure", "cifra"}
#: Resaltado (``<mark>``).
MARK_LCT = {"destacado", "resaltado", "mark", "highlight"}
#: Comentario (``role=comment``).
COMMENT_LCT = {"comentario", "comment"}
#: Sugerencia, inserción y eliminación.
SUGGESTION_LCT = {"sugerencia", "suggestion"}
INSERTION_LCT = {"inserción", "insertion", "insertado"}
DELETION_LCT = {"eliminación", "deletion", "eliminado"}
#: Término y definición de las listas de definición (#3858).
TERM_LCT = {"término", "term"}
DEFINITION_LCT = {"definición", "definition"}
#: Salto de página de las publicaciones digitales.
PAGEBREAK_LCT = {"salto de página", "page break", "pagebreak"}
#: Referencias (notas al pie, bibliografía, glosario).
REFERENCE_WORDS = ("referencia", "reference", "noteref", "biblioref", "glossref", "backlink", "vínculo de retroceso")
#: Imágenes sin texto alternativo según Edge («Gráfico sin descripción»).
UNLABELED_GRAPHIC_WORDS = ("sin descripción", "unlabeled", "sin etiqueta")

#: Roles de UIA en los que se mira el tipo localizado.
SEMANTIC_HOST_ROLES = {Role.GROUPING, Role.SECTION, Role.LISTITEM, Role.SEPARATOR, Role.LINK, Role.STATICTEXT, Role.PANE, Role.CUSTOM, Role.UNKNOWN, Role.REGION, Role.NOTE}


def semanticLabel(role: Role, lct: str) -> str:
	"""Tipo localizado que aporta información (capítulo, nota al pie...)."""
	if role not in SEMANTIC_HOST_ROLES:
		return ""
	lct = (lct or "").strip().lower()
	if lct in _PLAIN_LCT or lct in FIGURE_LCT or lct in MARK_LCT:
		return ""
	if role == Role.STATICTEXT and lct not in TERM_LCT | DEFINITION_LCT | COMMENT_LCT | SUGGESTION_LCT:
		return ""
	return lct


def isReferenceLct(lct: str) -> bool:
	lct = (lct or "").lower()
	return any(w in lct for w in REFERENCE_WORDS)


def isUnlabeledGraphicLct(lct: str) -> bool:
	lct = (lct or "").lower()
	return any(w in lct for w in UNLABELED_GRAPHIC_WORDS)


# ---------------------------------------------------------------- regiones vivas
LIVE_OFF = 0
LIVE_POLITE = 1
LIVE_ASSERTIVE = 2


def liveFromAria(aria: dict) -> int:
	v = (aria.get("live") or "").lower()
	if v == "assertive":
		return LIVE_ASSERTIVE
	if v == "polite":
		return LIVE_POLITE
	return LIVE_OFF
