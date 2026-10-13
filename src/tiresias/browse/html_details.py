"""Detalles de HTML y ARIA del modo exploración (foros 1.18 y 1.20).

- Imágenes sin texto alternativo con su nombre de archivo (#7412): UIA no
  expone el ``src``; se lee del atributo IA2 ``src`` del mismo objeto
  (:mod:`tiresias.a11y.ia2_bridge`).
- ``aria-describedby`` en grupos, regiones y otros contenedores (#12718).
- Comillas del elemento ``<q>`` (#14654): los navegadores no publican el
  elemento, solo las comillas que genera el CSS como hojas de texto sueltas;
  se anuncian como «cita» y «fin de cita».
- ``abbr`` de los encabezados de tabla (#3566): lo expone Firefox (atributo IA2
  ``abbr``); Chrome y Edge no lo publican por ninguna API.
- ``aria-braillelabel`` y ``aria-brailleroledescription`` (#11829) en la línea
  braille del modo exploración.
"""

from __future__ import annotations

from typing import Any

from .. import presentation as _presentation
from ..config import conf
from ..i18n import _
from ..log import getLogger
from ..objects.roles import Role

log = getLogger("vbuf.details")

#: Tiempo máximo (s) que una construcción del búfer dedica a buscar nombres de archivo.
GRAPHIC_BUDGET = 1.5
#: Lo mismo cuando el búfer se construye en el hilo del núcleo.
CORE_GRAPHIC_BUDGET = 0.3

#: Contenedores cuya descripción (aria-describedby) se dice al entrar (los mismos que fuera del modo exploración).
DESCRIBED_CONTAINER_ROLES = _presentation.DESCRIBED_CONTAINER_ROLES

# ====================================================================== imágenes


def _frameworkOf(buf: Any) -> str:
	fw = getattr(buf, "_frameworkId", None)
	if fw is None:
		try:
			fw = str(buf.rootElement.CurrentFrameworkId or "")
		except Exception:
			fw = ""
		try:
			buf._frameworkId = fw
		except Exception:
			pass
	return fw


def _resolver(buf: Any):
	from ..a11y import ia2_bridge

	res = getattr(buf, "_ia2Resolver", None)
	if res is None:
		res = ia2_bridge.PathResolver(lifetime=5.0)
		try:
			buf._ia2Resolver = res
		except Exception:
			pass
	return res


def nodeIA2Attributes(buf: Any, node: Any) -> dict[str, str]:
	"""Atributos IA2 del objeto de un nodo del búfer (vacío si no se encuentra)."""
	from ..a11y import ia2_bridge

	if node.element is None or _frameworkOf(buf) not in ia2_bridge.WEB_FRAMEWORKS:
		return {}
	res = _resolver(buf)
	from .. import queue_handler

	# En el núcleo (actualización parcial, región viva, abreviaturas de los
	# encabezados al navegar por una tabla) el tiempo es más corto.
	onCore = queue_handler.isCoreThread()
	if onCore:
		# El tiempo gastado al construir el búfer caduca con la caché del
		# resolutor; si no, las consultas posteriores no se harían nunca.
		res._fresh()
	budget = CORE_GRAPHIC_BUDGET if onCore else GRAPHIC_BUDGET
	if res.spent > budget:
		return {}
	try:
		# El camino sale del árbol completo de UIA, que es el que coincide con IA2
		# (la caché del búfer usa la vista de control, en la que Chrome omite los
		# contenedores genéricos). Se pide una sola vez por construcción.
		if getattr(buf, "rootParent", None) is not None:
			# Actualización parcial (solo un subárbol): el camino se calcula en vivo
			# hasta el documento.
			path = None
		else:
			path = res.rawPath(buf.rootElement, node.rid) if node.rid else None
			if path is None:
				return {}
		return ia2_bridge.attributesForElement(node.element, path=path, resolver=res, frameworkId=_frameworkOf(buf), live=False)
	except Exception:
		log.debug("No se pudieron leer los atributos IA2 del nodo", exc_info=True)
		return {}


def graphicFileName(buf: Any, node: Any) -> str:
	"""Nombre del archivo de una imagen del búfer (``""`` si no se conoce)."""
	cached = node.aria.get("_src")
	if cached is None:
		from ..a11y import ia2_bridge

		src = nodeIA2Attributes(buf, node).get("src", "")
		cached = ia2_bridge.fileNameFromURL(src)
		node.aria["_src"] = cached
	return cached


def graphicText(buf: Any, node: Any) -> str:
	"""Texto de una imagen sin texto alternativo en el búfer (#7412)."""
	bm = conf["browseMode"]
	interactive = node.isFocusable or (node.parent is not None and node.parent.role == Role.LINK)
	if not interactive and not bm["reportUnlabeledGraphics"]:
		return ""
	text = _("gráfico") if interactive else _("gráfico sin descripción")
	if bm["reportGraphicFileNames"]:
		name = graphicFileName(buf, node)
		if name:
			text = f"{text} {name}"
	return text


# ====================================================================== descripciones


def containerDescription(buf: Any, node: Any) -> str:
	"""Descripción (aria-describedby, title) de un grupo o región al entrar (#12718).

	No se repite si el texto descrito está dentro del propio contenedor (se
	va a leer igualmente).
	"""
	if node.role not in DESCRIBED_CONTAINER_ROLES or not conf["presentation"]["reportGroupDescriptions"]:
		return ""
	desc = " ".join((node.description or "").split())
	if not desc or desc == node.name:
		return ""
	if buf is not None and node.end > node.start:
		inner = " ".join(buf.text[node.start : min(node.end, node.start + 4000)].split())
		if desc in inner:
			return ""
	return desc


# ====================================================================== comillas (<q>)
#: Comillas que el CSS pone en ``<q>`` según el idioma.
QUOTE_CHARS = frozenset("“”„‟«»‹›‘’‚‛「」『』\"'")
#: Comillas que cierran cada apertura.
_CLOSERS = {
	"“": "”",
	"„": "“”",
	"‟": "”",
	"«": "»",
	"»": "«",
	"‹": "›",
	"›": "‹",
	"‘": "’",
	"‚": "‘’",
	"‛": "’",
	"「": "」",
	"『": "』",
	'"': '"',
	"'": "'",
}


def _quoteChar(node: Any) -> str:
	if node.role != Role.STATICTEXT or node.children:
		return ""
	t = (node.name or "").strip()
	return t if len(t) == 1 and t in QUOTE_CHARS else ""


def quoteKind(node: Any) -> str | None:
	"""``"open"``, ``"close"`` o ``None`` para una hoja de texto con solo unas comillas."""
	ch = _quoteChar(node)
	if not ch:
		return None
	siblings = node.parent.children if node.parent is not None else [node]
	stack: list[str] = []
	for s in siblings:
		c = _quoteChar(s)
		if not c:
			continue
		if stack and c in _CLOSERS.get(stack[-1], ""):
			kind = "close"
			stack.pop()
		else:
			kind = "open"
			stack.append(c)
		if s is node:
			return kind
	return None


def quoteSpeech(node: Any, text: str) -> str:
	"""Texto hablado de un trozo: las comillas de ``<q>`` se dicen como «cita» y «fin de cita»."""
	if node.role != Role.STATICTEXT or not conf["documentFormatting"]["reportQuotes"]:
		return text
	kind = quoteKind(node)
	if kind == "open":
		return _("cita")
	if kind == "close":
		return _("fin de cita")
	return text


# ====================================================================== abbr


def headerAbbreviation(doc: Any, node: Any) -> str:
	"""Abreviatura (``abbr``) de una celda de encabezado o ``""``."""
	if node is None or not conf["documentFormatting"]["useHeaderAbbreviations"]:
		return ""
	if node.role not in (Role.TABLECOLUMNHEADER, Role.TABLEROWHEADER, Role.HEADERITEM):
		return ""
	val = node.aria.get("abbr")
	if val is None:
		val = ""
		buf = getattr(doc, "buffer", None)
		# Solo Firefox publica el atributo (IA2); en Chrome y Edge no hay de dónde leerlo.
		if buf is not None and _frameworkOf(buf) == "Gecko":
			val = nodeIA2Attributes(buf, node).get("abbr", "").strip()
		node.aria["abbr"] = val
	return val


# ====================================================================== braille


def brailleLabelLine(doc: Any, start: int, end: int, withMap: bool = False) -> tuple | None:
	"""Línea braille con ``aria-braillelabel`` y ``aria-brailleroledescription`` (#11829).

	Devuelve ``None`` si la línea no tiene ninguno (se muestra el texto tal cual).
	Con ``withMap`` devuelve también, por cada carácter del texto, su posición
	en el búfer (para los pulsadores de enrutamiento).
	"""
	buf = doc.buffer
	if buf is None:
		return None
	reps: list[tuple[int, int, str]] = []
	seen: set[int] = set()
	from .buffer import ATOMIC_ROLES

	labelled = ATOMIC_ROLES | {Role.LINK}
	for _cs, _ce, node in buf.chunksInRange(start, end):
		# El trozo puede ser el texto de un enlace o botón (o de un hijo suyo).
		target = None
		n = node
		for _i in range(4):
			if n is None:
				break
			if n.role in labelled and (n.aria.get("braillelabel") or n.aria.get("brailleroledescription")):
				target = n
				break
			n = n.parent
		if target is None or id(target) in seen:
			continue
		seen.add(id(target))
		s, e = max(start, target.start), min(end, target.end)
		if e <= s:
			continue
		label = target.aria.get("braillelabel") or " ".join(buf.text[s:e].split())
		roleText = target.aria.get("brailleroledescription", "")
		reps.append((s, e, f"{label} {roleText}".strip()))
	if not reps:
		return None
	pieces: list[str] = []
	offsets: list[int] = []
	pos = start
	caret = doc.caret
	newCursor = None
	for s, e, rep in sorted(reps):
		if s < pos:
			continue
		pieces.append(buf.text[pos:s])
		offsets.extend(range(pos, s))
		outPos = sum(len(p) for p in pieces)
		if newCursor is None and pos <= caret < s:
			newCursor = outPos - (s - caret)
		elif newCursor is None and s <= caret < e:
			newCursor = outPos + min(caret - s, len(rep))
		pieces.append(rep)
		# Cada carácter de la etiqueta apunta al carácter equivalente del elemento.
		offsets.extend(s + min(i, e - s - 1) for i in range(len(rep)))
		pos = e
	tailStart = sum(len(p) for p in pieces)
	pieces.append(buf.text[pos:end])
	offsets.extend(range(pos, end))
	text = "".join(pieces)
	if newCursor is None:
		newCursor = tailStart + max(0, caret - pos)
	newCursor = max(0, min(newCursor, len(text)))
	if withMap:
		return text, newCursor, offsets
	return text, newCursor
