"""Carga de complementos globales."""

from __future__ import annotations

import importlib.util
import os
import sys

from ..log import getLogger
from . import GlobalPlugin

log = getLogger("pluginHandler")

runningPlugins: list[GlobalPlugin] = []
_sources: list[tuple[str, str]] = []  # (prefijo de paquete, carpeta)
_builtins: list[type[GlobalPlugin]] = []


def registerBuiltin(cls: type[GlobalPlugin]) -> None:
	"""Registra un complemento global incorporado en el núcleo."""
	if cls not in _builtins:
		_builtins.append(cls)


def addSource(packageName: str, folder: str) -> None:
	if (packageName, folder) not in _sources:
		_sources.append((packageName, folder))


def clearSources() -> None:
	_sources.clear()


def _loadModule(fullName: str, path: str):
	if os.path.isdir(path):
		init = os.path.join(path, "__init__.py")
		spec = importlib.util.spec_from_file_location(fullName, init, submodule_search_locations=[path])
	else:
		spec = importlib.util.spec_from_file_location(fullName, path)
	if spec is None or spec.loader is None:
		return None
	mod = importlib.util.module_from_spec(spec)
	sys.modules[fullName] = mod
	spec.loader.exec_module(mod)
	return mod


def initialize() -> None:
	for cls in _builtins:
		try:
			runningPlugins.append(cls())
		except Exception:
			log.exception("Error iniciando el complemento incorporado %s", cls)
	for pkg, folder in _sources:
		try:
			entries = sorted(os.listdir(folder))
		except OSError:
			continue
		for entry in entries:
			path = os.path.join(folder, entry)
			if entry.startswith(("_", ".")):
				continue
			if entry.endswith(".py"):
				modName = entry[:-3]
			elif os.path.isfile(os.path.join(path, "__init__.py")):
				modName = entry
			else:
				continue
			fullName = f"{pkg}.{modName}"
			try:
				mod = _loadModule(fullName, path)
				cls = getattr(mod, "GlobalPlugin", None)
				if cls is None:
					log.warning("%s no define GlobalPlugin", path)
					continue
				runningPlugins.append(cls())
				log.info("Complemento global cargado: %s", fullName)
			except Exception:
				log.exception("Error cargando el complemento global %s", path)


def terminate() -> None:
	for p in runningPlugins:
		try:
			p.terminate()
		except Exception:
			log.exception("Error terminando %r", p)
	runningPlugins.clear()
	for name in list(sys.modules):
		if any(name == pkg or name.startswith(pkg + ".") for pkg, _f in _sources):
			del sys.modules[name]


def reload() -> None:
	terminate()
	initialize()


def chooseObjectClass(obj, clsList: list[type]) -> None:
	for p in runningPlugins:
		try:
			p.chooseObjectClass(obj, clsList)
		except Exception:
			log.exception("Error en chooseObjectClass de %r", p)
