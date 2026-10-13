"""Sistema de plugins de extensión (OCR, diccionario, detectores, historial...).

Cada plugin es una clase que hereda de :class:`PluginBase` en un archivo de la
carpeta ``plugins`` del complemento o de
``data\\addonsData\\TraductorAvanzadoPro\\plugins`` (plugins del usuario, que
no se pierden al actualizar). Los plugins pueden exponer «comandos» (hooks)
que otros usan con :meth:`GestorPlugins.ejecutar_hook`, y se pueden activar o
desactivar en la categoría del complemento de las Opciones.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable

from tiresias.log import getLogger

if TYPE_CHECKING:
	from .configuracion import GestorConfiguracion

log = getLogger("TraductorAvanzadoPro")


class TipoPlugin(Enum):
	UTILIDAD = "utilidad"
	PROCESADOR = "procesador"
	INTERFAZ = "interfaz"
	SERVICIO = "servicio"


NOMBRES_TIPO = {
	TipoPlugin.UTILIDAD: "Utilidad",
	TipoPlugin.PROCESADOR: "Procesador",
	TipoPlugin.INTERFAZ: "Interfaz",
	TipoPlugin.SERVICIO: "Servicio",
}


@dataclass
class InfoPlugin:
	id: str
	nombre: str
	descripcion: str
	tipo: TipoPlugin
	version: str
	autor: str
	habilitado: bool


class PluginBase(ABC):
	"""Clase base de los plugins de extensión."""

	id: str = ""
	nombre: str = ""
	descripcion: str = ""
	tipo: TipoPlugin = TipoPlugin.UTILIDAD
	version: str = "1.0.0"
	autor: str = ""

	def __init__(self, configuracion: "GestorConfiguracion", plugin_principal: Any = None) -> None:
		self.configuracion = configuracion
		self.plugin_principal = plugin_principal
		self._habilitado = True
		self._inicializar()

	def _inicializar(self) -> None:
		"""Inicialización propia del plugin."""

	@abstractmethod
	def ejecutar(self, *args: Any, **kwargs: Any) -> Any:
		"""Funcionalidad principal del plugin."""

	def activar(self) -> None:
		self._habilitado = True
		self._al_activar()

	def desactivar(self) -> None:
		self._habilitado = False
		self._al_desactivar()

	def _al_activar(self) -> None:
		pass

	def _al_desactivar(self) -> None:
		pass

	def terminar(self) -> None:
		"""Se llama al descargar el complemento."""

	@property
	def esta_habilitado(self) -> bool:
		return self._habilitado

	def obtener_info(self) -> InfoPlugin:
		return InfoPlugin(self.id, self.nombre, self.descripcion, self.tipo, self.version, self.autor, self._habilitado)

	def obtener_comandos(self) -> dict[str, Callable]:
		"""Comandos (hooks) que expone el plugin: ``{nombre: función}``."""
		return {}

	def obtener_elementos_menu(self) -> list[dict[str, Any]]:
		"""Entradas para el submenú del complemento: ``{"etiqueta": str, "accion": callable}``."""
		return []


class GestorPlugins:
	def __init__(self, configuracion: "GestorConfiguracion", ruta_plugins: str, base_package: str, ruta_usuario: str | None = None) -> None:
		self.configuracion = configuracion
		self.ruta_plugins = ruta_plugins
		self.base_package = base_package
		self.ruta_usuario = ruta_usuario
		self.plugins: dict[str, PluginBase] = {}
		self._clases_plugins: dict[str, type[PluginBase]] = {}
		self._hooks: dict[str, list[Callable]] = {}
		self.errores: list[tuple[str, str]] = []

	def cargar_plugins(self, plugin_principal: Any = None) -> None:
		if not os.path.isdir(self.ruta_plugins):
			log.warning("Directorio de plugins no encontrado: %s", self.ruta_plugins)
			return
		for archivo in sorted(os.listdir(self.ruta_plugins)):
			if archivo.startswith("_") or not archivo.endswith(".py"):
				continue
			self._cargar_modulo(archivo[:-3], plugin_principal)
		if self.ruta_usuario and os.path.isdir(self.ruta_usuario):
			for archivo in sorted(os.listdir(self.ruta_usuario)):
				if archivo.startswith("_") or not archivo.endswith(".py"):
					continue
				self._cargar_archivo_usuario(os.path.join(self.ruta_usuario, archivo), plugin_principal)
		self.aplicar_desactivados()
		log.info("Cargados %d plugins", len(self.plugins))

	def _registrar_clases(self, modulo: Any, plugin_principal: Any) -> None:
		for nombre_attr in dir(modulo):
			attr = getattr(modulo, nombre_attr)
			if isinstance(attr, type) and issubclass(attr, PluginBase) and attr is not PluginBase and attr.__module__ == modulo.__name__:
				self._registrar_plugin(attr, plugin_principal)

	def _cargar_modulo(self, nombre_modulo: str, plugin_principal: Any) -> None:
		try:
			modulo = importlib.import_module(f"{self.base_package}.plugins.{nombre_modulo}")
			self._registrar_clases(modulo, plugin_principal)
		except Exception as e:
			self.errores.append((nombre_modulo, str(e)))
			log.exception("Error al cargar el plugin %s", nombre_modulo)

	def _cargar_archivo_usuario(self, ruta: str, plugin_principal: Any) -> None:
		nombre = os.path.splitext(os.path.basename(ruta))[0]
		nombre_completo = f"{self.base_package}.plugins.usuario_{nombre}"
		try:
			spec = importlib.util.spec_from_file_location(nombre_completo, ruta)
			if spec is None or spec.loader is None:
				return
			modulo = importlib.util.module_from_spec(spec)
			sys.modules[nombre_completo] = modulo
			spec.loader.exec_module(modulo)
			self._registrar_clases(modulo, plugin_principal)
		except Exception as e:
			sys.modules.pop(nombre_completo, None)
			self.errores.append((os.path.basename(ruta), str(e)))
			log.exception("Error al cargar el plugin del usuario %s", ruta)

	def _registrar_plugin(self, clase: type[PluginBase], plugin_principal: Any = None) -> None:
		try:
			plugin = clase(self.configuracion, plugin_principal)
		except Exception as e:
			self.errores.append((clase.__name__, str(e)))
			log.exception("Error al registrar el plugin %s", clase.__name__)
			return
		if not plugin.id:
			log.warning("Plugin sin ID: %s", clase.__name__)
			return
		self.plugins[plugin.id] = plugin
		self._clases_plugins[plugin.id] = clase
		for nombre_hook, callback in plugin.obtener_comandos().items():
			self.registrar_hook(nombre_hook, callback)

	def registrar(self, clase: type[PluginBase], plugin_principal: Any = None) -> None:
		self._registrar_plugin(clase, plugin_principal)

	def aplicar_desactivados(self) -> None:
		"""Desactiva los plugins que el usuario ha desmarcado en las Opciones."""
		try:
			desactivados = set(self.configuracion.config.plugins_desactivados or [])
		except AttributeError:
			desactivados = set()
		for pid, plugin in self.plugins.items():
			if pid in desactivados and plugin.esta_habilitado:
				plugin.desactivar()
			elif pid not in desactivados and not plugin.esta_habilitado:
				plugin.activar()

	def obtener_plugin(self, id_plugin: str) -> PluginBase | None:
		"""Plugin habilitado con ese ID (``None`` si no existe o está desactivado)."""
		plugin = self.plugins.get(id_plugin)
		return plugin if plugin is not None and plugin.esta_habilitado else None

	def listar_plugins(self, tipo: TipoPlugin | None = None) -> list[dict[str, Any]]:
		lista = []
		for plugin in self.plugins.values():
			if tipo is None or plugin.tipo == tipo:
				info = plugin.obtener_info()
				lista.append(
					{
						"id": info.id,
						"nombre": info.nombre,
						"descripcion": info.descripcion,
						"tipo": info.tipo.value,
						"version": info.version,
						"autor": info.autor,
						"habilitado": info.habilitado,
					}
				)
		lista.sort(key=lambda d: d["nombre"].lower())
		return lista

	def ejecutar_plugin(self, id_plugin: str, *args: Any, **kwargs: Any) -> Any:
		plugin = self.plugins.get(id_plugin)
		if plugin is None:
			raise ValueError(f"Plugin no encontrado: {id_plugin}")
		if not plugin.esta_habilitado:
			raise RuntimeError(f"Plugin deshabilitado: {id_plugin}")
		return plugin.ejecutar(*args, **kwargs)

	def registrar_hook(self, nombre_hook: str, callback: Callable) -> None:
		self._hooks.setdefault(nombre_hook, []).append(callback)

	def ejecutar_hook(self, nombre_hook: str, *args: Any, **kwargs: Any) -> list[Any]:
		resultados = []
		for callback in self._hooks.get(nombre_hook, []):
			dueno = getattr(callback, "__self__", None)
			if isinstance(dueno, PluginBase) and not dueno.esta_habilitado:
				continue
			try:
				resultados.append(callback(*args, **kwargs))
			except Exception:
				log.exception("Error en el hook %s", nombre_hook)
		return resultados

	def habilitar_plugin(self, id_plugin: str) -> bool:
		plugin = self.plugins.get(id_plugin)
		if plugin:
			plugin.activar()
			return True
		return False

	def deshabilitar_plugin(self, id_plugin: str) -> bool:
		plugin = self.plugins.get(id_plugin)
		if plugin:
			plugin.desactivar()
			return True
		return False

	def terminar(self) -> None:
		for plugin in self.plugins.values():
			try:
				plugin.terminar()
			except Exception:
				log.exception("Error al terminar el plugin %s", plugin.id)
