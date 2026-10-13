"""Sistema de plugins de servicios de traducción.

Cada servicio es una clase que hereda de :class:`TraductorBase` en un archivo
de la carpeta ``traductores`` del complemento. Además se cargan los archivos
``.py`` que el usuario ponga en ``data\\addonsData\\TraductorAvanzadoPro\\traductores``
(así no se pierden al actualizar el complemento). El archivo se carga dentro
del paquete ``traductores`` del complemento, de modo que se usa importación
relativa::

	from ..nucleo.gestor_traductores import TraductorBase

	class MiTraductor(TraductorBase):
		id = "mi_traductor"
		nombre = "Mi traductor"
		descripcion = "Lo que hace"
		requiere_api = True

		def traducir(self, texto, idioma_origen="auto", idioma_destino="es", **kwargs):
			return texto_traducido
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from tiresias.log import getLogger

if TYPE_CHECKING:
	from .configuracion import GestorConfiguracion

log = getLogger("TraductorAvanzadoPro")


@dataclass
class InfoTraductor:
	id: str
	nombre: str
	descripcion: str
	requiere_api: bool
	soporta_deteccion: bool
	idiomas_soportados: list[str]
	version: str


class TraductorBase(ABC):
	"""Clase base de todos los servicios de traducción."""

	id: str = ""
	nombre: str = ""
	descripcion: str = ""
	version: str = "1.0.0"
	requiere_api: bool = False
	soporta_deteccion: bool = True
	idiomas_soportados: list[str] = []
	#: ``True`` en los servicios de IA (modelo y prompts configurables).
	es_ia: bool = False

	def __init__(self, configuracion: "GestorConfiguracion") -> None:
		self.configuracion = configuracion
		#: Último error legible (lo anuncia el complemento si la traducción falla).
		self.ultimo_error: str | None = None
		self._inicializar()

	def _inicializar(self) -> None:
		"""Inicialización propia de cada servicio."""

	@abstractmethod
	def traducir(self, texto: str, idioma_origen: str = "auto", idioma_destino: str = "es", **kwargs: Any) -> str | None:
		"""Devuelve la traducción o ``None`` si falla."""

	def detectar_idioma(self, texto: str) -> str | None:
		return None

	def obtener_idiomas(self) -> dict[str, str]:
		return {}

	def adaptar_idioma(self, codigo: str) -> str:
		"""Código de idioma tal como lo espera el servicio (``zh`` → ``zh-CN``...)."""
		return codigo

	def configuracion_servicio(self):
		return self.configuracion.obtener_api(self.id)

	def validar_api(self) -> bool:
		if not self.requiere_api:
			return True
		sc = self.configuracion_servicio()
		return sc is not None and sc.api_key is not None

	def rotar_y_reintentar(self) -> bool:
		"""Pasa a la siguiente clave si la rotación de claves está activa."""
		sc = self.configuracion_servicio()
		if sc and sc.rotar():
			log.info("Rotando clave API para %s", self.nombre)
			try:
				self.configuracion.guardar()
			except Exception:
				pass
			return True
		return False

	def obtener_info(self) -> InfoTraductor:
		return InfoTraductor(self.id, self.nombre, self.descripcion, self.requiere_api, self.soporta_deteccion, list(self.idiomas_soportados), self.version)


class GestorTraductores:
	"""Carga, registra y entrega los servicios de traducción."""

	def __init__(self, configuracion: "GestorConfiguracion", ruta_traductores: str, base_package: str, ruta_usuario: str | None = None) -> None:
		self.configuracion = configuracion
		self.ruta_traductores = ruta_traductores
		self.base_package = base_package
		self.ruta_usuario = ruta_usuario
		self.traductores: dict[str, TraductorBase] = {}
		self._clases_traductores: dict[str, type[TraductorBase]] = {}
		#: Errores de carga (archivo, mensaje), para el panel «Servicios».
		self.errores: list[tuple[str, str]] = []

	def cargar_traductores(self) -> None:
		if not os.path.isdir(self.ruta_traductores):
			log.warning("Directorio de traductores no encontrado: %s", self.ruta_traductores)
			return
		for archivo in sorted(os.listdir(self.ruta_traductores)):
			if archivo.startswith("_") or not archivo.endswith(".py"):
				continue
			self._cargar_modulo(archivo[:-3])
		if self.ruta_usuario and os.path.isdir(self.ruta_usuario):
			for archivo in sorted(os.listdir(self.ruta_usuario)):
				if archivo.startswith("_") or not archivo.endswith(".py"):
					continue
				self._cargar_archivo_usuario(os.path.join(self.ruta_usuario, archivo))
		log.info("Cargados %d traductores", len(self.traductores))

	def _registrar_clases(self, modulo: Any) -> None:
		for nombre_attr in dir(modulo):
			attr = getattr(modulo, nombre_attr)
			if isinstance(attr, type) and issubclass(attr, TraductorBase) and attr is not TraductorBase and attr.__module__ == modulo.__name__:
				self._registrar_traductor(attr)

	def _cargar_modulo(self, nombre_modulo: str) -> None:
		try:
			modulo = importlib.import_module(f"{self.base_package}.traductores.{nombre_modulo}")
			self._registrar_clases(modulo)
		except Exception as e:
			self.errores.append((nombre_modulo, str(e)))
			log.exception("Error al cargar el traductor %s", nombre_modulo)

	def _cargar_archivo_usuario(self, ruta: str) -> None:
		nombre = os.path.splitext(os.path.basename(ruta))[0]
		nombre_completo = f"{self.base_package}.traductores.usuario_{nombre}"
		try:
			spec = importlib.util.spec_from_file_location(nombre_completo, ruta)
			if spec is None or spec.loader is None:
				return
			modulo = importlib.util.module_from_spec(spec)
			sys.modules[nombre_completo] = modulo
			spec.loader.exec_module(modulo)
			self._registrar_clases(modulo)
		except Exception as e:
			sys.modules.pop(nombre_completo, None)
			self.errores.append((os.path.basename(ruta), str(e)))
			log.exception("Error al cargar el traductor del usuario %s", ruta)

	def _registrar_traductor(self, clase: type[TraductorBase]) -> None:
		try:
			traductor = clase(self.configuracion)
		except Exception as e:
			self.errores.append((clase.__name__, str(e)))
			log.exception("Error al registrar el traductor %s", clase.__name__)
			return
		if not traductor.id:
			log.warning("Traductor sin ID: %s", clase.__name__)
			return
		self.traductores[traductor.id] = traductor
		self._clases_traductores[traductor.id] = clase

	def registrar(self, clase: type[TraductorBase]) -> None:
		"""Registra un traductor desde código (otros complementos o pruebas)."""
		self._registrar_traductor(clase)

	def obtener_traductor(self, id_traductor: str) -> TraductorBase | None:
		return self.traductores.get(id_traductor)

	def obtener_traductor_activo(self) -> TraductorBase | None:
		id_activo = self.configuracion.servicio_activo
		traductor = self.traductores.get(id_activo)
		if traductor is None and self.traductores:
			traductor = self.traductores.get("google_api_free") or next(iter(self.traductores.values()))
			log.warning("Traductor %s no encontrado, usando %s", id_activo, traductor.id)
		return traductor

	def listar_traductores(self) -> list[dict[str, Any]]:
		"""Servicios ordenados: primero los gratuitos, luego los que piden clave."""
		lista = [
			{
				"id": t.id,
				"nombre": t.nombre,
				"descripcion": t.descripcion,
				"requiere_api": t.requiere_api,
				"api_configurada": t.validar_api() if t.requiere_api else True,
				"version": t.version,
				"es_ia": t.es_ia,
				"soporta_deteccion": t.soporta_deteccion,
			}
			for t in self.traductores.values()
		]
		lista.sort(key=lambda d: (d["requiere_api"], d["nombre"].lower()))
		return lista

	def recargar_traductor(self, id_traductor: str) -> bool:
		clase = self._clases_traductores.get(id_traductor)
		if clase is None:
			return False
		try:
			self.traductores[id_traductor] = clase(self.configuracion)
			return True
		except Exception:
			log.exception("Error al recargar el traductor %s", id_traductor)
			return False
