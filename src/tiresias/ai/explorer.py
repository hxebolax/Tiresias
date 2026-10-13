"""Explorar la página con IA (foros 6.6, como Page Explorer de JAWS).

Envía al servicio de IA, en una sesión de chat con preguntas de seguimiento:

- la **estructura** de la página (título, regiones, encabezados con su
  nivel, formularios y sus campos, tablas, listas, marcos y gráficos sin
  descripción, con la posición de cada parte en la página) o, fuera del modo
  exploración, los controles de la ventana;
- las **teclas de Tiresias** que sirven allí (navegación rápida y órdenes del
  modo exploración, o navegación de objetos en las aplicaciones), con las
  asignaciones actuales del usuario;
- el principio del **texto**;
- y, si la opción ``exploreWithScreenshot`` está activada (lo está por
  defecto), una **captura de la ventana** para analizar el diseño visual.

La respuesta tiene tres partes: para qué sirve la página, cómo está
distribuida visualmente y qué teclas llevan a cada parte.
"""

from __future__ import annotations

import time
from typing import Any

from .. import api, imaging, queue_handler, speech
from ..config import conf
from ..i18n import _
from ..log import getLogger
from ..objects.roles import HEADING_ROLES, Role, roleLabel

log = getLogger("aiExplorer")

#: Máximo de líneas de cada tipo en la estructura.
MAX_ITEMS = 150
#: Máximo de caracteres de texto de la página (además de la estructura).
MAX_TEXT = 30000
#: Máximo de objetos y de segundos al recorrer una ventana (se hace en el hilo del núcleo).
MAX_OBJECTS = 400
MAX_WALK_SECONDS = 1.5

EXPLORE_SYSTEM = (
	"Eres el explorador de páginas de Tiresias. Te paso la estructura de una página o ventana entre etiquetas <estructura>, "
	"las teclas de Tiresias disponibles entre etiquetas <teclas>, el principio del texto entre etiquetas <texto> y, a veces, "
	"una captura de la ventana. Las posiciones son píxeles desde la esquina superior izquierda del documento."
)
EXPLORE_PROMPT = (
	"Haz un recorrido de esta página en tres partes, con frases cortas:\n"
	"1. Qué es y para qué sirve, y su contenido principal, en dos o tres frases.\n"
	"2. Diseño visual: cómo está distribuida (cabecera, menús, columnas, barras laterales, pie, avisos o ventanas superpuestas), "
	"qué destaca a la vista y dónde están los formularios y los botones importantes. Relaciona cada zona con sus regiones o encabezados.\n"
	"3. Consejos de navegación: para cada parte importante, qué teclas de Tiresias de la lista <teclas> llevan hasta ella "
	"(por ejemplo, «pulsa D hasta la región principal» o «pulsa 2 para ir al encabezado Ofertas»). Usa solo teclas de esa lista.\n"
	"Termina diciendo que se pueden hacer preguntas de seguimiento."
)


def _pos(node: Any, origin: tuple[int, int]) -> str:
	loc = node.location
	if not loc:
		return ""
	return _(" (x={x}, y={y}, {w}×{h})").format(x=loc[0] - origin[0], y=loc[1] - origin[1], w=loc[2], h=loc[3])


def _text(buf: Any, node: Any, limit: int = 100) -> str:
	return " ".join(buf.text[node.start : node.end].split())[:limit]


def bufferStructure(doc: Any) -> str:
	"""Estructura legible del búfer del modo exploración."""
	from ..browse.buffer import FORM_FIELD_ROLES

	buf = doc.buffer
	root = buf.root
	origin = (root.location[0], root.location[1]) if root is not None and root.location else (0, 0)
	lines: list[str] = []
	title = ""
	try:
		title = doc.rootObject.name or ""
	except Exception:
		pass
	lines.append(_("Título: {title}").format(title=title or _("sin título")))
	try:
		lines.append(_("Dirección: {url}").format(url=doc._documentKey()))
	except Exception:
		pass
	nodes = [n for n in buf.nodes if n.end > n.start]
	landmarks = [n for n in buf.nodes if n.role in (Role.LANDMARK, Role.REGION)]
	headings = [n for n in nodes if n.role in HEADING_ROLES]
	fields = [n for n in nodes if n.role in FORM_FIELD_ROLES and n.role not in (Role.LIST, Role.TREEVIEW)]
	tables = [n for n in nodes if n.role in (Role.TABLE, Role.DATAGRID) and not n.layoutTable]
	lists = [n for n in nodes if n.role == Role.LIST]
	frames = [n for n in nodes if n.role == Role.FRAME]
	links = sum(1 for n in nodes if n.role == Role.LINK)
	graphics = [n for n in nodes if n.role == Role.GRAPHIC]
	unlabeled = sum(1 for n in graphics if n.unlabeled or not n.name)
	dialogs = [n for n in nodes if n.role == Role.DIALOG]
	lines.append(
		_("Resumen: {h} encabezados, {l} enlaces, {r} regiones, {f} campos de formulario, {t} tablas, {li} listas, {g} gráficos ({u} sin descripción)").format(
			h=len(headings), l=links, r=len(landmarks), f=len(fields), t=len(tables), li=len(lists), g=len(graphics), u=unlabeled
		)
	)
	if landmarks:
		lines.append(_("Regiones:"))
		for n in landmarks[:MAX_ITEMS]:
			name = " ".join(p for p in (n.name, n.landmark or roleLabel(n.role)) if p)
			lines.append(f"- {name}{_pos(n, origin)}")
	if headings:
		lines.append(_("Encabezados:"))
		for n in headings[:MAX_ITEMS]:
			lines.append(_("- nivel {level}: {text}{pos}").format(level=n.headingLevel() or "?", text=_text(buf, n), pos=_pos(n, origin)))
	if fields:
		lines.append(_("Campos de formulario y botones:"))
		for n in fields[:MAX_ITEMS]:
			region = next((a for a in n.ancestors() if a.role in (Role.LANDMARK, Role.REGION, Role.DIALOG)), None)
			where = _(" en {region}").format(region=region.name or region.landmark) if region is not None and (region.name or region.landmark) else ""
			lines.append(f"- {roleLabel(n.role)}: {n.name or _text(buf, n, 60) or _('sin nombre')}{where}{_pos(n, origin)}")
	if tables:
		lines.append(_("Tablas:"))
		for n in tables[:MAX_ITEMS]:
			size = _("{r} filas y {c} columnas").format(r=n.tableSize[0], c=n.tableSize[1]) if n.tableSize else ""
			lines.append(f"- {n.name or _text(buf, n, 40)} {size}{_pos(n, origin)}")
	if lists:
		lines.append(_("Listas: {n}").format(n=len(lists)))
	if frames:
		lines.append(_("Marcos:"))
		for n in frames[:MAX_ITEMS]:
			lines.append(f"- {n.name or _('sin nombre')}{_pos(n, origin)}")
	if dialogs:
		lines.append(_("Diálogos abiertos:"))
		for n in dialogs[:MAX_ITEMS]:
			lines.append(f"- {n.name or _text(buf, n, 60)}")
	return "\n".join(lines)


def windowStructure(fg: Any) -> str:
	"""Controles de una ventana sin modo exploración."""
	lines = [_("Ventana: {name}").format(name=(fg.name if fg is not None else "") or _("sin título"))]
	origin = (0, 0)
	try:
		loc = fg.location
		origin = (loc[0], loc[1]) if loc else (0, 0)
	except Exception:
		pass
	count = [0]
	# Cada hijo es una llamada a otra aplicación: con un límite de tiempo, una
	# ventana lenta no bloquea el hilo del núcleo.
	deadline = time.monotonic() + MAX_WALK_SECONDS
	cut = [False]

	def walk(obj: Any, depth: int) -> None:
		if obj is None or depth > 14 or count[0] > MAX_OBJECTS or cut[0]:
			return
		if time.monotonic() > deadline:
			cut[0] = True
			return
		try:
			children = list(obj.children)
		except Exception:
			return
		for c in children:
			count[0] += 1
			if count[0] > MAX_OBJECTS or cut[0]:
				return
			if time.monotonic() > deadline:
				cut[0] = True
				return
			try:
				name = c.name or ""
				role = c.role
				loc = c.location
			except Exception:
				continue
			if name or role not in (Role.PANE, Role.GROUPING, Role.UNKNOWN, Role.SECTION):
				pos = _(" (x={x}, y={y})").format(x=loc[0] - origin[0], y=loc[1] - origin[1]) if loc else ""
				lines.append(f"{'  ' * min(depth, 8)}- {roleLabel(role)}: {name}{pos}")
			walk(c, depth + 1)

	walk(fg, 0)
	if cut[0]:
		lines.append(_("(estructura incompleta: la ventana tarda demasiado en responder)"))
	return "\n".join(lines)


def keyTable(cls: type, categories: set[str] | None = None) -> list[str]:
	"""«teclas: descripción» de las órdenes de ``cls`` que tienen tecla."""
	try:
		from ..gui.gesture_tools import gesturesFor
		from ..input import gestures
		from ..input.keys import labelForGesture
	except Exception:
		return []
	state = gestures.userMap.userBindings()
	classGestures = dict(cls.iterClassGestures())
	out = []
	for attr in sorted(dir(cls)):
		if not attr.startswith("script_"):
			continue
		func = getattr(cls, attr, None)
		desc = ((getattr(func, "__doc__", None) or "").strip().splitlines() or [""])[0]
		if not desc:
			continue
		cat = getattr(func, "category", None) or getattr(cls, "scriptCategory", None)
		if categories is not None and cat not in categories:
			continue

		class _Info:
			pass

		info = _Info()
		info.cls = cls  # type: ignore[attr-defined]
		info.name = attr[7:]  # type: ignore[attr-defined]
		info.classGestures = classGestures  # type: ignore[attr-defined]
		gids = sorted(g for g in gesturesFor(state, info) if g.startswith("kb"))
		if gids:
			out.append(f"{', '.join(labelForGesture(g) for g in gids)}: {desc}")
	return out


def navigationKeys(inBrowse: bool) -> str:
	from ..global_commands import CAT_FOCUS, CAT_NAV, CAT_REVIEW, GlobalCommands

	lines: list[str] = []
	if inBrowse:
		from ..browse.document import BrowseModeDocument

		lines.extend(keyTable(BrowseModeDocument))
	lines.extend(keyTable(GlobalCommands, {CAT_NAV, CAT_FOCUS} if inBrowse else {CAT_NAV, CAT_FOCUS, CAT_REVIEW}))
	return "\n".join(lines)


def buildPrompt(structure: str, keys: str, text: str) -> str:
	text = text[:MAX_TEXT]
	return f"<estructura>\n{structure}\n</estructura>\n\n<teclas>\n{keys}\n</teclas>\n\n<texto>\n{text}\n</texto>\n\n{EXPLORE_PROMPT}"


def explorePage() -> None:
	"""Orden: recorrido de la página con IA (contenido, diseño visual y teclas)."""
	from . import assistant

	provider = assistant.checkProvider()
	if provider is None:
		return
	doc = assistant.currentBrowseDocument()
	try:
		if doc is not None:
			structure = bufferStructure(doc)
			text = doc.buffer.text
			title = doc.rootObject.name or _("la página")
		else:
			fg = api.getForegroundObject()
			structure = windowStructure(fg)
			title = (fg.name if fg is not None else "") or _("la ventana")
			_t, text = assistant.currentDocumentText()
		keys = navigationKeys(doc is not None)
	except Exception:
		log.exception("No se pudo preparar la exploración")
		speech.speakMessage(_("No se pudo leer la estructura de la página"))
		return
	limit = assistant.contextLimit(provider)
	prompt = buildPrompt(structure[:limit], keys, text[: max(0, min(MAX_TEXT, limit - len(structure)))])
	system = assistant.systemPrompt(EXPLORE_SYSTEM)
	sessionTitle = _("Exploración de {name}").format(name=title)
	shown = _("Explora la página: contenido, diseño visual y cómo moverse")
	if not conf["ai"]["exploreWithScreenshot"]:
		assistant.startSession(sessionTitle, prompt, system=system, shownText=shown)
		return
	r = assistant._foregroundRect()
	if r is None:
		assistant.startSession(sessionTitle, prompt, system=system, shownText=shown)
		return
	rect, hwnd = r

	def go() -> None:
		import threading

		speech.speakMessage(_("Capturando"))

		def worker() -> None:
			try:
				png = assistant._imageToPng(imaging.captureRect(rect, hwnd))
			except Exception:
				log.exception("No se pudo capturar la ventana")
				png = None
			queue_handler.queueFunction(assistant.startSession, sessionTitle, prompt, [png] if png else None, system, shown)

		threading.Thread(target=worker, name="IA-explorar", daemon=True).start()

	assistant.withImagePrivacy(go)
