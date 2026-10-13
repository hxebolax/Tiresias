"""Referencia rápida de órdenes generada a partir del código.

Reúne TODAS las órdenes con su descripción y sus teclas (con los cambios del
usuario y el mapa de gestos elegido): órdenes globales, complementos
globales (incluidos los de los complementos instalados), modo exploración,
edición de texto y los módulos de aplicación incorporados y de los
complementos, cada una en su sección.

:func:`buildHtml` genera un documento HTML con encabezados (se recorre con
la tecla H en modo exploración) y :func:`buildText`, texto plano.
"""

from __future__ import annotations

import html
import importlib
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Iterator

from .. import APP_NAME, VERSION, i18n, paths
from ..config import conf
from ..i18n import _
from ..log import getLogger

log = getLogger("gui.keyref")


@dataclass
class Section:
	title: str
	#: {categoría: [(descripción, [teclas])]}
	categories: dict[str, list[tuple[str, list[str]]]] = field(default_factory=dict)

	@property
	def count(self) -> int:
		return sum(len(v) for v in self.categories.values())


def _layout() -> str:
	try:
		return conf["keyboard"]["layout"]
	except Exception:
		return "desktop"


def _applies(gid: str, layout: str) -> bool:
	prefix = gid.split(":", 1)[0]
	return not (prefix.startswith("kb(") and prefix != f"kb({layout})")


def classGestures(cls: type, instance: Any = None) -> dict[str, list[str]]:
	"""{orden: [gestos]} de una clase, con los cambios del usuario y de la instancia."""
	from ..input import gestures as gestureMap

	mapping: dict[str, str | None] = {}
	if hasattr(cls, "iterClassGestures"):
		for gid, name in cls.iterClassGestures():
			mapping.setdefault(gid, name)
	if instance is not None:
		for gid, name in (instance.__dict__.get("_instanceGestures") or {}).items():
			mapping[gid] = name
	user = gestureMap.userMap.userBindings()
	for klass in reversed(cls.__mro__):
		for gid, name in (user.get(f"{klass.__module__}.{klass.__qualname__}") or {}).items():
			mapping[gid] = name
	layout = _layout()
	out: dict[str, list[str]] = {}
	for gid, name in mapping.items():
		if name and _applies(gid, layout):
			out.setdefault(name, []).append(gid)
	return out


def _scripts(cls: type) -> Iterator[tuple[str, Any]]:
	seen: set[str] = set()
	for klass in cls.__mro__:
		for attr in list(vars(klass)):
			if attr.startswith("script_") and attr not in seen:
				seen.add(attr)
				func = getattr(cls, attr, None)
				if callable(func):
					yield attr[7:], func


def sectionFor(title: str, cls: type, instance: Any = None, defaultCategory: str | None = None, onlyOwn: bool = False) -> Section:
	from ..input import keys

	gestures = classGestures(cls, instance)
	sec = Section(title)
	ownNames = None
	if onlyOwn:
		ownNames = {a[7:] for a in vars(cls) if a.startswith("script_")}
	for name, func in _scripts(cls):
		if ownNames is not None and name not in ownNames:
			continue
		desc = " ".join((getattr(func, "__doc__", None) or "").split())
		gids = gestures.get(name, [])
		if not desc:
			if not gids:
				continue
			desc = name
		category = getattr(func, "category", None) or getattr(cls, "scriptCategory", None) or defaultCategory or _("Varios")
		labels = sorted({keys.labelForGesture(g) for g in gids}, key=str.lower)
		sec.categories.setdefault(category, []).append((desc, labels))
	return sec


def _appModuleNames() -> list[tuple[str, str, str]]:
	"""(nombre de módulo, paquete, carpeta) de los módulos de aplicación conocidos."""
	from ..appmodules import handler as appHandler

	out: list[tuple[str, str, str]] = []
	seen: set[str] = set()
	dirs = list(appHandler._searchDirs)
	base = os.path.dirname(appHandler.__file__)
	dirs.append(("tiresias.appmodules", base))
	for pkg, folder in dirs:
		try:
			entries = sorted(os.listdir(folder))
		except OSError:
			continue
		for entry in entries:
			name = entry
			for ext in (".py", ".pyc"):
				if name.endswith(ext):
					name = name[: -len(ext)]
			if "." in name or name.startswith("_") or name in ("handler", "__pycache__") or name in seen:
				continue
			path = os.path.join(folder, entry)
			if os.path.isdir(path) and not (os.path.isfile(os.path.join(path, "__init__.py")) or os.path.isfile(os.path.join(path, "__init__.pyc"))):
				continue
			seen.add(name)
			out.append((name, pkg, folder))
	return out


def _loadAppModule(name: str, pkg: str, folder: str) -> Any:
	from ..appmodules import handler as appHandler

	full = f"{pkg}.{name}"
	if full in sys.modules:
		return sys.modules[full]
	if pkg == "tiresias.appmodules":
		return importlib.import_module(full)
	for candidate in (os.path.join(folder, name + ".py"), os.path.join(folder, name)):
		if os.path.exists(candidate):
			return appHandler._loadFromFile(full, candidate)
	return None


def collectSections() -> list[Section]:
	"""Todas las secciones de la referencia."""
	sections: list[Section] = []
	try:
		from ..global_commands import commands

		sections.append(sectionFor(_("Órdenes globales"), type(commands), commands))
	except Exception:
		log.exception("Sin órdenes globales")
	try:
		from ..browse.document import BrowseModeDocument

		sections.append(sectionFor(_("Modo exploración (páginas web y documentos)"), BrowseModeDocument, defaultCategory=_("Modo exploración")))
	except Exception:
		log.exception("Sin órdenes del modo exploración")
	try:
		from ..objects.behaviors import EditableText

		sections.append(sectionFor(_("Edición de texto"), EditableText, defaultCategory=_("Edición de texto")))
	except Exception:
		log.exception("Sin órdenes de edición")
	try:
		from ..plugins import handler as pluginHandler

		for plugin in list(pluginHandler.runningPlugins):
			cls = type(plugin)
			mod = sys.modules.get(cls.__module__)
			doc = (mod.__doc__ or "").strip() if mod is not None else ""
			title = getattr(plugin, "displayName", None) or (doc.splitlines()[0].rstrip(".") if doc else cls.__module__)
			sec = sectionFor(_("Complemento global: {name}").format(name=title), cls, plugin, onlyOwn=False)
			if sec.count:
				sections.append(sec)
	except Exception:
		log.exception("Sin órdenes de los complementos globales")
	for name, pkg, folder in _appModuleNames():
		try:
			mod = _loadAppModule(name, pkg, folder)
			cls = getattr(mod, "AppModule", None) if mod is not None else None
			if cls is None:
				continue
			sec = sectionFor(_("Aplicación: {name}").format(name=name), cls, defaultCategory=name, onlyOwn=True)
			if sec.count:
				sections.append(sec)
		except Exception:
			log.exception("Sin órdenes del módulo de aplicación %s", name)
	return sections


def _header() -> list[str]:
	layout = _layout()
	layoutLabel = _("portátil") if layout == "laptop" else _("sobremesa")
	try:
		from .. import gesture_layouts

		mapLabel = gesture_layouts.layoutLabel(conf["keyboard"]["gestureLayout"])
	except Exception:
		mapLabel = ""
	lines = [
		_("Distribución de teclado: {layout}.").format(layout=layoutLabel),
		_("«Tiresias» es la tecla modificadora de Tiresias (Insertar por defecto)."),
	]
	if mapLabel:
		lines.append(_("Mapa de gestos: {name}.").format(name=mapLabel))
	return lines


def buildText(sections: list[Section] | None = None) -> str:
	sections = collectSections() if sections is None else sections
	lines = [_("Referencia rápida de órdenes de {app}").format(app=APP_NAME)] + _header() + [""]
	for sec in sections:
		lines.append(sec.title.upper())
		for category, items in sec.categories.items():
			lines.append(category)
			for desc, keys in items:
				lines.append(f"{desc}: {', '.join(keys) if keys else _('sin gesto asignado')}")
			lines.append("")
	return "\n".join(lines).rstrip() + "\n"


def buildHtml(sections: list[Section] | None = None) -> str:
	sections = collectSections() if sections is None else sections
	e = html.escape
	title = _("Referencia rápida de órdenes de {app}").format(app=APP_NAME)
	out = [
		"<!DOCTYPE html>",
		f'<html lang="{e(i18n.LANGUAGE.split("_")[0])}"><head><meta charset="utf-8"><title>{e(title)}</title>',
		"<style>body{font-family:'Segoe UI',Arial,sans-serif;line-height:1.5;max-width:60em;margin:auto;padding:1em}"
		"table{border-collapse:collapse;width:100%;margin-bottom:1em}th,td{border:1px solid #888;padding:.3em .5em;text-align:left;vertical-align:top}"
		"@media (prefers-color-scheme: dark){body{background:#000;color:#fff}}</style></head><body>",
		f"<h1>{e(title)}</h1>",
		f"<p>{e(APP_NAME)} {e(VERSION)}. " + " ".join(e(line) for line in _header()) + "</p>",
		f"<nav><h2>{e(_('Índice'))}</h2><ul>",
	]
	for i, sec in enumerate(sections):
		out.append(f'<li><a href="#s{i}">{e(sec.title)}</a> ({sec.count})</li>')
	out.append("</ul></nav>")
	for i, sec in enumerate(sections):
		out.append(f'<h2 id="s{i}">{e(sec.title)}</h2>')
		for category, items in sec.categories.items():
			out.append(f"<h3>{e(category)}</h3>")
			out.append(f"<table><thead><tr><th>{e(_('Orden'))}</th><th>{e(_('Teclas'))}</th></tr></thead><tbody>")
			for desc, keys in items:
				keyText = ", ".join(f"<kbd>{e(k)}</kbd>" for k in keys) if keys else e(_("sin gesto asignado"))
				out.append(f"<tr><td>{e(desc)}</td><td>{keyText}</td></tr>")
			out.append("</tbody></table>")
	out.append("</body></html>")
	return "\n".join(out)


def writeHtml(path: str | None = None) -> str:
	path = path or os.path.join(paths.cacheDir(), "referencia_ordenes.html")
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "w", encoding="utf-8") as f:
		f.write(buildHtml())
	return path
