# -*- coding: utf-8 -*-
# Copyright (C) 2025-2026 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General GNU.

"""Sistema de plugins de zRadio BASS.

Un plugin es un archivo ``.py`` con una clase que hereda de
:class:`PluginBase`. Se buscan en la carpeta ``plugins`` del complemento
(los incluidos) y en ``data\\addonsData\\zRadioBASS\\plugins`` (los del
usuario). Los plugins importan lo que necesitan del módulo ``zradiobass``::

	from zradiobass import PluginBase, EventType

	class MiPlugin(PluginBase):
		PLUGIN_ID = "mi_plugin"
		PLUGIN_NAME = "Mi plugin"

		def on_load(self):
			self.subscribe(EventType.PLAYBACK_STARTED, self.al_empezar)
			return True

		def on_unload(self):
			return True

		def al_empezar(self, station):
			self.app.speak(f"Suena {station.name}")
"""

from __future__ import annotations

import importlib.util
import sys
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable

from tiresias.log import getLogger

from .events import EventBus, EventType

log = getLogger("zRadioBASS.plugins")

#: Nombre del módulo que importan los plugins.
API_MODULE_NAME = "zradiobass"


class PluginState(Enum):
	UNLOADED = auto()
	LOADED = auto()
	ACTIVE = auto()
	ERROR = auto()
	DISABLED = auto()


#: Estados en español.
PLUGIN_STATE_NAMES = {
	PluginState.UNLOADED: "sin cargar",
	PluginState.LOADED: "cargado",
	PluginState.ACTIVE: "activo",
	PluginState.ERROR: "error",
	PluginState.DISABLED: "desactivado",
}


@dataclass
class PluginMetadata:
	id: str
	name: str
	version: str = "1.0.0"
	author: str = ""
	description: str = ""
	min_app_version: str = "1.0.0"
	dependencies: list[str] = field(default_factory=list)
	homepage: str = ""


class PluginBase(ABC):
	"""Clase base de los plugins.

	Atributos disponibles en el plugin:

	- ``self.event_bus``: bus de eventos (``self.subscribe`` cancela solo las
	  suscripciones al descargar el plugin).
	- ``self.app``: la aplicación (``speak``, ``message``, ``player``, ``db``,
	  ``api``, ``config``, ``play_station``...). Puede ser ``None`` en pruebas.
	- ``self.settings``: diccionario de opciones propias que persiste
	  (``self.save_settings()`` lo guarda).
	"""

	PLUGIN_ID: str = ""
	PLUGIN_NAME: str = ""
	PLUGIN_VERSION: str = "1.0.0"
	PLUGIN_AUTHOR: str = ""
	PLUGIN_DESCRIPTION: str = ""
	PLUGIN_DEPENDENCIES: list[str] = []

	def __init__(self, event_bus: EventBus, app: Any = None) -> None:
		self._event_bus = event_bus
		self._app = app
		self._state = PluginState.UNLOADED
		self._unsubscribers: list[Callable[[], None]] = []
		self._metadata = PluginMetadata(
			id=self.PLUGIN_ID or self.__class__.__name__,
			name=self.PLUGIN_NAME or self.__class__.__name__,
			version=self.PLUGIN_VERSION,
			author=self.PLUGIN_AUTHOR,
			description=self.PLUGIN_DESCRIPTION,
			dependencies=list(self.PLUGIN_DEPENDENCIES),
		)

	@property
	def metadata(self) -> PluginMetadata:
		return self._metadata

	@property
	def state(self) -> PluginState:
		return self._state

	@property
	def event_bus(self) -> EventBus:
		return self._event_bus

	@property
	def app(self) -> Any:
		return self._app

	@property
	def _config(self) -> Any:
		return getattr(self._app, "config", None)

	@property
	def settings(self) -> dict:
		cfg = self._config
		if cfg is None:
			if not hasattr(self, "_localSettings"):
				self._localSettings: dict = {}
			return self._localSettings
		return cfg.plugin_settings(self.metadata.id)

	def save_settings(self) -> None:
		cfg = self._config
		if cfg is not None:
			cfg.save()

	@property
	def data_dir(self) -> Path:
		"""Carpeta de datos del plugin (dentro de la del complemento)."""
		cfg = self._config
		base = Path(cfg.data_dir) if cfg is not None else Path(".")
		p = base / "plugins_data" / self.metadata.id
		p.mkdir(parents=True, exist_ok=True)
		return p

	def subscribe(self, event_type: EventType, callback: Callable[[Any], None]) -> Callable[[], None]:
		"""Se suscribe a un evento; la suscripción se cancela sola al descargar."""
		unsub = self._event_bus.subscribe(event_type, callback, weak=False)
		self._unsubscribers.append(unsub)
		return unsub

	def _unsubscribe_all(self) -> None:
		for unsub in self._unsubscribers:
			try:
				unsub()
			except Exception:
				pass
		self._unsubscribers.clear()

	@abstractmethod
	def on_load(self) -> bool:
		"""Inicializa el plugin. ``True`` si se cargó bien."""

	@abstractmethod
	def on_unload(self) -> bool:
		"""Libera recursos. ``True`` si se descargó bien."""

	def on_enable(self) -> None:
		"""Se llama al activar el plugin desde el administrador."""

	def on_disable(self) -> None:
		"""Se llama al desactivar el plugin desde el administrador."""

	def get_settings_panel(self, parent: Any) -> Any:
		"""Panel wx con las opciones del plugin (o ``None``).

		El panel puede tener un método ``save()`` que se llama al aceptar.
		"""
		return None

	def get_menu_items(self) -> list[dict[str, Any]]:
		"""Elementos para el submenú Plugins: ``{"label": ..., "callback": función(evento)}``."""
		return []

	def get_context_menu_items(self, context: str) -> list[dict[str, Any]]:
		"""Elementos del menú contextual de las listas.

		``context`` es ``"station"`` (General, Buscador, Historial) o
		``"favorite"``. ``callback`` recibe la emisora (:class:`Station`).
		"""
		return []


class PluginManager:
	"""Descubre, carga y descarga los plugins."""

	def __init__(self, event_bus: EventBus, app: Any = None, builtin_dir: Path | None = None, user_dir: Path | None = None, disabled: Callable[[], list[str]] | None = None, set_disabled: Callable[[list[str]], None] | None = None) -> None:
		self._event_bus = event_bus
		self._app = app
		self._builtin_dir = Path(builtin_dir) if builtin_dir else Path(__file__).parent.parent / "plugins"
		self._user_dir = Path(user_dir) if user_dir else None
		self._get_disabled = disabled or (lambda: [])
		self._set_disabled = set_disabled or (lambda ids: None)
		self._plugins: dict[str, PluginBase] = {}
		self._plugin_classes: dict[str, type[PluginBase]] = {}
		self._plugin_paths: dict[str, Path] = {}
		self._errors: dict[str, str] = {}
		self._modules: list[str] = []
		self._lock = threading.RLock()
		install_api_module()
		if self._user_dir is not None:
			try:
				self._user_dir.mkdir(parents=True, exist_ok=True)
			except OSError:
				pass

	@property
	def user_dir(self) -> Path | None:
		return self._user_dir

	@property
	def builtin_dir(self) -> Path:
		return self._builtin_dir

	# ------------------------------------------------------------- descubrir
	def discover_plugins(self) -> list[str]:
		found: list[str] = []
		dirs = [self._builtin_dir] + ([self._user_dir] if self._user_dir is not None else [])
		with self._lock:
			for folder in dirs:
				if not folder.is_dir():
					continue
				for path in sorted(folder.glob("*.py")):
					if path.name.startswith("_"):
						continue
					cls = self._load_plugin_class(path)
					if cls is None:
						continue
					pid = cls.PLUGIN_ID or path.stem
					if pid in self._plugin_classes and self._plugin_paths.get(pid) != path:
						log.warning("Plugin %s duplicado; se usa %s", pid, self._plugin_paths[pid])
						continue
					self._plugin_classes[pid] = cls
					self._plugin_paths[pid] = path
					found.append(pid)
		return found

	def _load_plugin_class(self, path: Path) -> type[PluginBase] | None:
		modName = f"zradiobass_plugin_{path.stem}"
		try:
			spec = importlib.util.spec_from_file_location(modName, str(path))
			if spec is None or spec.loader is None:
				return None
			module = importlib.util.module_from_spec(spec)
			sys.modules[modName] = module
			spec.loader.exec_module(module)
			self._modules.append(modName)
		except Exception as e:
			log.exception("Error cargando el plugin %s", path)
			self._errors[path.stem] = str(e)
			sys.modules.pop(modName, None)
			return None
		for name in dir(module):
			obj = getattr(module, name)
			if isinstance(obj, type) and issubclass(obj, PluginBase) and obj is not PluginBase and obj.__module__ == modName:
				return obj
		return None

	# ------------------------------------------------------------- cargar y descargar
	def load_plugin(self, plugin_id: str) -> bool:
		with self._lock:
			if plugin_id in self._plugins:
				return True
			cls = self._plugin_classes.get(plugin_id)
			if cls is None:
				log.error("Plugin %s no encontrado", plugin_id)
				return False
			for dep in getattr(cls, "PLUGIN_DEPENDENCIES", []) or []:
				if dep not in self._plugins and not self.load_plugin(dep):
					self._errors[plugin_id] = f"Falta el plugin {dep}"
					return False
			try:
				plugin = cls(self._event_bus, self._app)
				ok = plugin.on_load()
			except Exception as e:
				log.exception("Error cargando el plugin %s", plugin_id)
				self._errors[plugin_id] = str(e)
				self._event_bus.emit(EventType.PLUGIN_ERROR, {"plugin_id": plugin_id, "error": str(e)})
				return False
			if not ok:
				plugin._state = PluginState.ERROR
				self._errors[plugin_id] = "El plugin no se pudo cargar"
				plugin._unsubscribe_all()
				return False
			plugin._state = PluginState.LOADED
			self._plugins[plugin_id] = plugin
			self._errors.pop(plugin_id, None)
		log.info("Plugin cargado: %s", plugin_id)
		self._event_bus.emit(EventType.PLUGIN_LOADED, plugin.metadata)
		return True

	def unload_plugin(self, plugin_id: str) -> bool:
		with self._lock:
			plugin = self._plugins.get(plugin_id)
			if plugin is None:
				return True
			try:
				ok = plugin.on_unload()
			except Exception as e:
				log.exception("Error descargando el plugin %s", plugin_id)
				self._errors[plugin_id] = str(e)
				ok = False
			plugin._unsubscribe_all()
			del self._plugins[plugin_id]
			plugin._state = PluginState.UNLOADED
		self._event_bus.emit(EventType.PLUGIN_UNLOADED, plugin.metadata)
		log.info("Plugin descargado: %s", plugin_id)
		return bool(ok)

	def load_all_plugins(self) -> dict[str, bool]:
		disabled = set(self._get_disabled())
		return {pid: self.load_plugin(pid) for pid in list(self._plugin_classes) if pid not in disabled}

	def unload_all_plugins(self) -> dict[str, bool]:
		return {pid: self.unload_plugin(pid) for pid in list(self._plugins)}

	def reload_plugin(self, plugin_id: str) -> bool:
		self.unload_plugin(plugin_id)
		return self.load_plugin(plugin_id)

	def rediscover(self) -> list[str]:
		"""Descarga todo, vuelve a leer las carpetas y carga los activados."""
		self.unload_all_plugins()
		with self._lock:
			self._plugin_classes.clear()
			self._plugin_paths.clear()
			self._errors.clear()
			for name in self._modules:
				sys.modules.pop(name, None)
			self._modules.clear()
		found = self.discover_plugins()
		self.load_all_plugins()
		return found

	def shutdown(self) -> None:
		"""Descarga los plugins y olvida sus módulos (al descargar el complemento)."""
		self.unload_all_plugins()
		with self._lock:
			for name in self._modules:
				sys.modules.pop(name, None)
			self._modules.clear()
		uninstall_api_module()

	# ------------------------------------------------------------- consultas
	def get_plugin(self, plugin_id: str) -> PluginBase | None:
		return self._plugins.get(plugin_id)

	def get_loaded_plugins(self) -> list[PluginBase]:
		return list(self._plugins.values())

	def get_all_plugin_ids(self) -> list[str]:
		return list(self._plugin_classes)

	def get_plugin_path(self, plugin_id: str) -> Path | None:
		return self._plugin_paths.get(plugin_id)

	def get_plugin_error(self, plugin_id: str) -> str:
		return self._errors.get(plugin_id, "")

	def is_builtin(self, plugin_id: str) -> bool:
		p = self._plugin_paths.get(plugin_id)
		return bool(p and p.parent == self._builtin_dir)

	def get_plugin_metadata(self, plugin_id: str) -> PluginMetadata | None:
		if plugin_id in self._plugins:
			return self._plugins[plugin_id].metadata
		cls = self._plugin_classes.get(plugin_id)
		if cls is None:
			return None
		return PluginMetadata(
			id=cls.PLUGIN_ID or plugin_id,
			name=cls.PLUGIN_NAME or cls.__name__,
			version=cls.PLUGIN_VERSION,
			author=cls.PLUGIN_AUTHOR,
			description=cls.PLUGIN_DESCRIPTION,
			dependencies=list(getattr(cls, "PLUGIN_DEPENDENCIES", []) or []),
		)

	def get_plugin_state(self, plugin_id: str) -> PluginState:
		if plugin_id in self._plugins:
			return self._plugins[plugin_id].state
		if not self.is_plugin_enabled(plugin_id):
			return PluginState.DISABLED
		if plugin_id in self._errors:
			return PluginState.ERROR
		return PluginState.UNLOADED

	def enable_plugin(self, plugin_id: str) -> bool:
		disabled = [p for p in self._get_disabled() if p != plugin_id]
		self._set_disabled(disabled)
		ok = self.load_plugin(plugin_id)
		plugin = self._plugins.get(plugin_id)
		if plugin is not None:
			try:
				plugin.on_enable()
			except Exception:
				log.exception("Error en on_enable de %s", plugin_id)
		return ok

	def disable_plugin(self, plugin_id: str) -> bool:
		disabled = list(self._get_disabled())
		if plugin_id not in disabled:
			disabled.append(plugin_id)
			self._set_disabled(disabled)
		plugin = self._plugins.get(plugin_id)
		if plugin is not None:
			try:
				plugin.on_disable()
			except Exception:
				log.exception("Error en on_disable de %s", plugin_id)
		return self.unload_plugin(plugin_id)

	def is_plugin_enabled(self, plugin_id: str) -> bool:
		return plugin_id not in self._get_disabled()

	def is_plugin_loaded(self, plugin_id: str) -> bool:
		return plugin_id in self._plugins

	def get_menu_items_from_plugins(self) -> list[dict[str, Any]]:
		items: list[dict[str, Any]] = []
		for plugin in list(self._plugins.values()):
			try:
				items.extend(plugin.get_menu_items() or [])
			except Exception:
				log.exception("Error obteniendo el menú de %s", plugin.metadata.id)
		return items

	def get_context_menu_items_from_plugins(self, context: str) -> list[dict[str, Any]]:
		items: list[dict[str, Any]] = []
		for plugin in list(self._plugins.values()):
			try:
				items.extend(plugin.get_context_menu_items(context) or [])
			except Exception:
				log.exception("Error obteniendo el menú contextual de %s", plugin.metadata.id)
		return items


def install_api_module() -> None:
	"""Publica el módulo ``zradiobass`` que importan los plugins."""
	from . import plugin_api

	sys.modules[API_MODULE_NAME] = plugin_api


def uninstall_api_module() -> None:
	sys.modules.pop(API_MODULE_NAME, None)
