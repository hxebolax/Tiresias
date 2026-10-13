"""Herramientas del visor (menú «Plugins»): sistema de complementos internos.

Cada módulo de esta carpeta define una clase que hereda de
:class:`HerramientaBase` con sus :class:`MetadatosHerramienta`. Se activan o
desactivan en las opciones («Herramientas») y aparecen en el menú «Plugins»
del visor, agrupadas por categorías si se desea.

``ejecutar(**kwargs)`` recibe:

- ``texto``: el contenido completo del visor;
- ``seleccionado``: el texto seleccionado (las herramientas usan primero la
  selección y, si no hay, todo el documento);
- ``visor``: la ventana del visor (padre de los diálogos propios);
- ``complemento``: el complemento global (configuración, definiciones...);
- ``destino`` y ``tipo_consola``: en las llamadas directas desde una orden.

Lo que devuelve lo presenta el visor: un texto se muestra en un cuadro de
lectura, una lista en una lista para copiar un elemento y ``None`` significa
que la herramienta ya se ha encargado de todo.
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from typing import Any

from tiresias.log import getLogger

log = getLogger("consoleLog")

#: Nombres visibles de las categorías del menú.
NOMBRES_CATEGORIAS = {
	"analisis": "Análisis",
	"desarrollo": "Desarrollo",
	"edición": "Edición y formatos",
	"edicion": "Edición y formatos",
	"utilidades": "Utilidades",
	"portapapeles": "Portapapeles",
	"acciones": "Acciones",
	"ia": "Inteligencia artificial",
	"general": "General",
}


def nombre_categoria(categoria: str) -> str:
	c = (categoria or "general").lower()
	return NOMBRES_CATEGORIAS.get(c, c.capitalize())


@dataclass
class MetadatosHerramienta:
	nombre: str
	version: str
	descripcion: str
	autor: str
	categoria: str = "general"
	dependencias: list = field(default_factory=list)


class HerramientaBase:
	METADATOS: MetadatosHerramienta | None = None

	def __init__(self) -> None:
		self._habilitado = True
		self._inicializado = False

	@property
	def habilitado(self) -> bool:
		return self._habilitado

	@habilitado.setter
	def habilitado(self, valor: bool) -> None:
		self._habilitado = bool(valor)

	@property
	def inicializado(self) -> bool:
		return self._inicializado

	def inicializar(self) -> bool:
		return True

	def ejecutar(self, **kwargs: Any) -> Any:
		raise NotImplementedError

	def terminar(self) -> None:
		pass

	def obtener_metadatos(self) -> MetadatosHerramienta | None:
		return self.METADATOS

	@staticmethod
	def texto_de(kwargs: dict, preferir_seleccion: bool = True) -> str:
		"""La selección si la hay; si no, todo el documento."""
		if preferir_seleccion and kwargs.get("seleccionado"):
			return str(kwargs.get("seleccionado") or "")
		return str(kwargs.get("texto") or "")


class GestorHerramientas:
	def __init__(self, complemento: Any = None) -> None:
		self._complemento = complemento
		self._herramientas: dict[str, HerramientaBase] = {}
		self._directorio = os.path.dirname(os.path.abspath(__file__))

	def _descubrir(self) -> list[str]:
		nombres = []
		try:
			for archivo in sorted(os.listdir(self._directorio)):
				if archivo.endswith(".py") and not archivo.startswith("_"):
					nombres.append(archivo[:-3])
		except OSError:
			log.warning("consoleLog: carpeta de herramientas no encontrada: %s", self._directorio)
		return nombres

	def _modulo(self, nombre: str):
		return importlib.import_module("{}.{}".format(__name__, nombre))

	@staticmethod
	def _clase(modulo) -> type | None:
		for valor in vars(modulo).values():
			if isinstance(valor, type) and issubclass(valor, HerramientaBase) and valor is not HerramientaBase and valor.__module__ == modulo.__name__:
				return valor
		return None

	def metadatos(self, nombre: str) -> MetadatosHerramienta | None:
		h = self._herramientas.get(nombre)
		if h is not None:
			return h.obtener_metadatos()
		try:
			clase = self._clase(self._modulo(nombre))
			return clase.METADATOS if clase else None
		except Exception:
			log.exception("consoleLog: no se pudo leer la herramienta %s", nombre)
			return None

	def cargar_plugins(self, habilitadas: list[str]) -> None:
		cargadas = 0
		errores = []
		for nombre in self._descubrir():
			if nombre in habilitadas and nombre not in self._herramientas:
				if self._cargar(nombre):
					cargadas += 1
				else:
					errores.append(nombre)
		if errores:
			log.error("consoleLog: %d herramientas cargadas, %d con errores: %s", cargadas, len(errores), ", ".join(errores))
		else:
			log.debug("consoleLog: %d herramientas cargadas", cargadas)

	def _cargar(self, nombre: str) -> bool:
		try:
			clase = self._clase(self._modulo(nombre))
			if clase is None:
				log.warning("consoleLog: %s no define ninguna herramienta", nombre)
				return False
			h = clase()
			h.complemento = self._complemento  # type: ignore[attr-defined]
			if h.inicializar():
				h._inicializado = True
				self._herramientas[nombre] = h
				return True
			log.warning("consoleLog: no se pudo inicializar la herramienta %s", nombre)
		except Exception:
			log.exception("consoleLog: error cargando la herramienta %s", nombre)
		return False

	def _descargar(self, nombre: str) -> bool:
		h = self._herramientas.pop(nombre, None)
		if h is None:
			return False
		try:
			h.terminar()
		except Exception:
			log.exception("consoleLog: error descargando la herramienta %s", nombre)
		return True

	def descargar_plugins(self) -> None:
		for nombre in list(self._herramientas):
			self._descargar(nombre)

	def sincronizar(self, habilitadas: list[str]) -> None:
		"""Carga las nuevas habilitadas y descarga las que se han desactivado."""
		for nombre in list(self._herramientas):
			if nombre not in habilitadas:
				self._descargar(nombre)
		self.cargar_plugins(habilitadas)

	def habilitar_plugin(self, nombre: str) -> bool:
		return nombre in self._herramientas or self._cargar(nombre)

	def deshabilitar_plugin(self, nombre: str) -> bool:
		return self._descargar(nombre)

	def obtener_plugin(self, nombre: str) -> HerramientaBase | None:
		return self._herramientas.get(nombre)

	def listar_plugins_cargados(self) -> list[str]:
		return list(self._herramientas)

	def listar_plugins_disponibles(self) -> list[str]:
		return self._descubrir()

	def opciones_lista(self) -> list[tuple[str, str]]:
		"""(identificador, «nombre: descripción») de todas las herramientas."""
		salida = []
		for nombre in self._descubrir():
			meta = self.metadatos(nombre)
			if meta is None:
				continue
			salida.append((nombre, "{}: {}".format(meta.nombre, meta.descripcion)))
		return salida
