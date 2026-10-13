"""Ayuda contextual (F1) del diálogo de opciones.

Esquema de anclas del manual:

- cada opción: ``opt-<sección>-<clave>`` (por ejemplo ``opt-general-language``);
  la sección y la clave son las de la configuración (:func:`optionAnchor`);
- cada categoría del cuadro de Opciones: ``cat-<categoría>`` (por ejemplo
  ``cat-general``), con el identificador del panel (:data:`CATEGORY_ANCHORS`).

F1 abre el manual en la opción con el foco; si el manual no tiene su ancla,
en la de su categoría; si tampoco, en el apartado del manual que la explica
hoy (:data:`PANEL_ANCHORS`) y, en último caso, al principio de las Opciones.

Windows no conserva el ``#ancla`` al abrir un archivo local, así que se abre
una pequeña página intermedia (en la caché) que salta al ancla del manual.
"""

from __future__ import annotations

import os
import re
import urllib.request
from typing import Any

from .. import paths
from ..i18n import _
from ..log import getLogger

log = getLogger("gui.contextHelp")

#: Categorías del cuadro de Opciones (identificador del panel) en el orden de la
#: lista, como en NVDA, con las propias de Tiresias en su sitio lógico. Las de los
#: complementos se colocan detrás de «Aplicaciones» y «Avanzado» siempre es la
#: última (ver :func:`tiresias.gui.settings.getPanelIds`).
CATEGORY_IDS = (
	"general",
	"speech",
	"speechReading",
	"speechLanguage",
	"voiceContexts",
	"braille",
	"brailleAdvanced",
	"audio",
	"sounds",
	"vision",
	"magnifier",
	"keyboard",
	"mouse",
	"touch",
	"reviewCursor",
	"presentation",
	"verbosity",
	"inputComposition",
	"browseMode",
	"documentFormatting",
	"documentNavigation",
	"math",
	"ocr",
	"ai",
	"clipboard",
	"productivity",
	"apps",
	"controller",
	"remote",
	"rdp",
	"updates",
	"advanced",
)

#: Ancla de cada categoría: ``cat-<categoría>``.
CATEGORY_ANCHORS = {pid: f"cat-{pid}" for pid in CATEGORY_IDS}

#: Apartado del manual que explica hoy cada categoría (respaldo si falta ``cat-…``).
PANEL_ANCHORS = {
	"general": "op-generales",
	"updates": "op-actualizaciones",
	"speech": "op-voz",
	"speechReading": "op-voz-lectura-voz",
	"speechLanguage": "op-voz-idioma",
	"voiceContexts": "op-voz-contextos",
	"verbosity": "op-verbosidad",
	"audio": "op-audio",
	"sounds": "op-sonidos",
	"braille": "op-braille",
	"brailleAdvanced": "op-braille-presentacion",
	"keyboard": "op-teclado",
	"inputComposition": "op-ime",
	"mouse": "op-raton",
	"touch": "tactil-opciones",
	"reviewCursor": "op-revision",
	"presentation": "op-presentacion",
	"browseMode": "op-exploracion",
	"documentNavigation": "op-navegacion-documentos",
	"documentFormatting": "op-formato",
	"ocr": "op-ocr",
	"vision": "op-vision",
	"magnifier": "op-lupa",
	"clipboard": "op-portapapeles",
	"apps": "op-aplicaciones",
	"productivity": "opciones-productividad",
	"controller": "programas-externos",
	"remote": "remoto-opciones",
	"rdp": "rdp-opciones",
	"advanced": "op-avanzado",
	"math": "mates-opciones",
	"ai": "op-ia",
}


def optionAnchor(section: str, key: str) -> str:
	"""Ancla de una opción: ``opt-<sección>-<clave>``."""
	return f"opt-{section}-{key}"


def categoryAnchor(panelId: str) -> str:
	"""Ancla de una categoría: ``cat-<categoría>`` (también para las de complementos)."""
	return CATEGORY_ANCHORS.get(panelId) or f"cat-{panelId}"


def panelOptions(panel: Any) -> list[tuple[str, str, str]]:
	"""Opciones con ayuda propia de un panel ya creado: ``[(ancla, sección, clave)]``.

	Incluye los campos declarativos y los controles propios con ``_helpKeys``.
	"""
	keys: list[tuple[str, str]] = list(getattr(panel, "_bound", {}) or {})
	for key in (getattr(panel, "_helpKeys", {}) or {}).values():
		if key not in keys:
			keys.append(key)
	return [(optionAnchor(sec, k), sec, k) for sec, k in keys]


_ids: set[str] | None = None


def manualIds() -> set[str]:
	"""Anclas que existen en el manual (se leen una vez)."""
	global _ids
	if _ids is None:
		try:
			with open(paths.manualPath(), encoding="utf-8") as f:
				_ids = set(re.findall(r'\bid="([^"]+)"', f.read()))
		except OSError:
			_ids = set()
	return _ids


def anchorFor(panelId: str | None, key: tuple[str, str] | None) -> str:
	ids = manualIds()
	if key is not None:
		candidate = optionAnchor(key[0], key[1])
		if candidate in ids:
			return candidate
	if panelId:
		cat = categoryAnchor(panelId)
		if cat in ids:
			return cat
	anchor = PANEL_ANCHORS.get(panelId or "", "")
	if anchor and (anchor in ids or not ids):
		return anchor
	return "opciones" if "opciones" in ids else ""


def addonHelpFor(panelId: str | None) -> str | None:
	"""Ayuda propia de la categoría de un complemento, o ``None``.

	La clase del panel puede indicarla con ``helpPath``; si no, se usa el
	``readme.html`` del complemento que la registró.
	"""
	if not panelId:
		return None
	try:
		from . import settings

		entry = settings._panels.get(panelId)
	except Exception:
		return None
	if not entry:
		return None
	cls = entry[1]
	path = getattr(cls, "helpPath", None)
	if isinstance(path, str) and os.path.isfile(path):
		return path
	module = getattr(cls, "__module__", "") or ""
	if not module.startswith("tiresias_addons."):
		return None
	from .. import addons

	pkg = ".".join(module.split(".")[:2])
	for addon in addons.getAddons():
		if addon.packageName == pkg:
			return addon.docPath()
	return None


def openHelp(panelId: str | None, key: tuple[str, str] | None = None) -> str:
	"""Abre el manual en el ancla adecuada. Devuelve el ancla usada.

	En la categoría de un complemento se abre la ayuda del complemento.
	"""
	own = addonHelpFor(panelId)
	if own:
		try:
			os.startfile(own)
			return ""
		except OSError:
			log.exception("No se pudo abrir la ayuda del complemento")
	manual = paths.manualPath()
	anchor = anchorFor(panelId, key)
	if not os.path.isfile(manual):
		from .settings import showError

		showError(_("No se encontró el manual de usuario:\n{path}").format(path=manual))
		return anchor
	url = "file:" + urllib.request.pathname2url(os.path.abspath(manual)) + (f"#{anchor}" if anchor else "")
	page = os.path.join(paths.cacheDir(), "ayuda.html")
	try:
		os.makedirs(os.path.dirname(page), exist_ok=True)
		with open(page, "w", encoding="utf-8") as f:
			f.write(
				'<!DOCTYPE html><html><head><meta charset="utf-8">'
				f'<meta http-equiv="refresh" content="0; url={url}"><title>{_("Manual de usuario")}</title>'
				f'<script>location.replace("{url}");</script></head>'
				f'<body><a href="{url}">{_("Abrir el manual de usuario")}</a></body></html>'
			)
		os.startfile(page)
	except OSError:
		log.exception("No se pudo abrir la ayuda")
		try:
			os.startfile(manual)
		except OSError:
			pass
	return anchor
