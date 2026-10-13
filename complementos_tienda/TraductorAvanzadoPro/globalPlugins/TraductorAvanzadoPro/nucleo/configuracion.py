"""Configuración del Traductor Avanzado Pro.

Las opciones normales van en la configuración de Tiresias (sección
``TraductorAvanzadoPro``: se guardan con los perfiles como cualquier otra).
Las claves de API y los ajustes de cada servicio (modelo, prompts, servidor,
rotación de claves) van aparte, cifradas, en ``apis.json`` dentro de la
carpeta de datos del complemento (``data\\addonsData\\TraductorAvanzadoPro``):
el original las guardaba en ``%USERPROFILE%\\traductorpro_apis.json``.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from typing import Any

from tiresias.log import getLogger

from ..utilidades import seguridad

log = getLogger("TraductorAvanzadoPro")

#: Identificador del complemento (carpeta de datos) y sección de la configuración.
ID_COMPLEMENTO = "TraductorAvanzadoPro"
SECCION = "TraductorAvanzadoPro"

#: Opciones de idioma de destino por servicio (se conservan del original).
CLAVES_IDIOMA_SERVICIO = (
	"idioma_destino_google",
	"idioma_destino_deepl",
	"idioma_destino_libretranslate",
	"idioma_destino_microsoft",
	"idioma_destino_openai",
)


def obtener_idioma_sistema() -> str:
	"""Idioma de la interfaz de Tiresias (dos letras)."""
	from ..utilidades import lector

	return lector.idioma_interfaz() or "en"


def valores_por_defecto(idioma: str | None = None) -> dict[str, Any]:
	idioma = idioma or obtener_idioma_sistema()
	valores: dict[str, Any] = {
		"servicio_activo": "google_api_free",
		"idioma_origen": "auto",
		"idioma_destino": idioma,
		"idioma_destino_alternativo": "en",
		"cache_habilitada": True,
		"historial_habilitado": True,
		"mostrar_resultados": False,
		"intercambio_automatico_idioma": False,
		"sonidos_habilitados": True,
		#: Volumen de los sonidos del complemento (abrir y cerrar la capa), 0-100.
		"volumen_sonido": 100,
		#: Volumen del reproductor de audio del botón «Escuchar» (0-100).
		"volumen_reproductor": 50,
		#: Velocidad del reproductor: índice de 0,5x a 2x (2 = 1x).
		"velocidad_audio": 2,
		#: Saltos del reproductor: índice de 1 s, 5 s, 10 s, 15 s, 30 s y 1 min.
		"salto_atras": 1,
		"salto_adelante": 1,
		"gui_idioma_origen": "auto",
		"gui_idioma_destino": idioma,
		#: Plugins de extensión desactivados por el usuario (IDs).
		"plugins_desactivados": [],
	}
	for clave in CLAVES_IDIOMA_SERVICIO:
		valores[clave] = idioma
	return valores


@dataclass
class ConfiguracionServicio:
	"""Ajustes de un servicio: claves (cifradas), rotación, servidor, modelo y prompts."""

	claves: list[str] = field(default_factory=list)
	usar_rotacion: bool = False
	indice_actual: int = 0
	api_url: str | None = None
	modelo: str | None = None
	prompt_sistema: str | None = None
	prompt_usuario: str | None = None
	parametros_extra: dict[str, Any] = field(default_factory=dict)

	@property
	def api_key(self) -> str | None:
		"""Clave en uso (la del índice actual si hay rotación; si no, la primera)."""
		if not self.claves:
			return None
		if self.usar_rotacion:
			if not 0 <= self.indice_actual < len(self.claves):
				self.indice_actual = 0
			clave = self.claves[self.indice_actual]
		else:
			clave = self.claves[0]
		return seguridad.decodificar_api_key(clave) or None

	def claves_planas(self) -> list[str]:
		return [seguridad.decodificar_api_key(c) for c in self.claves]

	def rotar(self) -> bool:
		"""Pasa a la siguiente clave si la rotación está activa y hay más de una."""
		if not self.usar_rotacion or len(self.claves) <= 1:
			return False
		self.indice_actual = (self.indice_actual + 1) % len(self.claves)
		return True

	def agregar_clave(self, clave: str) -> None:
		clave = (clave or "").strip()
		if clave and clave not in self.claves_planas():
			self.claves.append(seguridad.codificar_api_key(clave))

	def eliminar_clave(self, clave_plana: str) -> None:
		planas = self.claves_planas()
		if clave_plana in planas:
			del self.claves[planas.index(clave_plana)]
			if self.indice_actual >= len(self.claves):
				self.indice_actual = max(0, len(self.claves) - 1)

	def a_diccionario(self) -> dict[str, Any]:
		return {
			"claves": list(self.claves),
			"usar_rotacion": self.usar_rotacion,
			"indice_actual": self.indice_actual,
			"api_url": self.api_url,
			"modelo": self.modelo,
			"prompt_sistema": self.prompt_sistema,
			"prompt_usuario": self.prompt_usuario,
			"parametros_extra": dict(self.parametros_extra or {}),
		}

	@classmethod
	def desde_diccionario(cls, datos: dict[str, Any]) -> "ConfiguracionServicio":
		claves = [str(c) for c in datos.get("claves") or [] if c]
		if not claves and datos.get("api_key"):
			# Formato muy antiguo: una sola clave en claro.
			claves = [seguridad.codificar_api_key(str(datos["api_key"]))]
		return cls(
			claves=claves,
			usar_rotacion=bool(datos.get("usar_rotacion", False)),
			indice_actual=int(datos.get("indice_actual", 0) or 0),
			api_url=datos.get("api_url") or None,
			modelo=datos.get("modelo") or None,
			prompt_sistema=datos.get("prompt_sistema") or None,
			prompt_usuario=datos.get("prompt_usuario") or None,
			parametros_extra=dict(datos.get("parametros_extra") or {}),
		)


class VistaConfiguracion:
	"""Acceso por atributos a la sección de la configuración de Tiresias.

	``config.cache_habilitada`` lee ``conf["TraductorAvanzadoPro"]["cache_habilitada"]``
	y asignarlo lo escribe (se guarda con la configuración de Tiresias).
	"""

	def __init__(self, gestor: "GestorConfiguracion") -> None:
		object.__setattr__(self, "_gestor", gestor)

	def __getattr__(self, nombre: str) -> Any:
		if nombre == "servicios":
			return self._gestor.servicios
		from tiresias.config import conf

		try:
			return conf[SECCION][nombre]
		except KeyError:
			raise AttributeError(nombre) from None

	def __setattr__(self, nombre: str, valor: Any) -> None:
		from tiresias.config import conf

		if nombre == "servicios":
			self._gestor.servicios = valor
			return
		conf[SECCION][nombre] = valor


class GestorConfiguracion:
	"""Carga y guarda la configuración del complemento."""

	SECCION_CONFIG = SECCION

	def __init__(self, ruta_complemento: str, ruta_datos: str | None = None) -> None:
		from tiresias import paths
		from tiresias.config import conf

		self.ruta_complemento = ruta_complemento
		self.ruta_config = ruta_datos or paths.addonDataDir(ID_COMPLEMENTO)
		self.ruta_cache = os.path.join(self.ruta_config, "cache")
		self.ruta_modelos = os.path.join(self.ruta_config, "modelos")
		self.ruta_apis = os.path.join(self.ruta_config, "apis.json")
		self.ruta_historial = os.path.join(self.ruta_config, "historial.json")
		self.ruta_traductores_usuario = os.path.join(self.ruta_config, "traductores")
		self.ruta_plugins_usuario = os.path.join(self.ruta_config, "plugins")
		for carpeta in (self.ruta_cache, self.ruta_modelos, self.ruta_traductores_usuario, self.ruta_plugins_usuario):
			os.makedirs(carpeta, exist_ok=True)
		conf.registerDefaults(SECCION, valores_por_defecto())
		self._bloqueo = threading.RLock()
		self.servicios: dict[str, ConfiguracionServicio] = self._cargar_apis()
		self.config = VistaConfiguracion(self)

	# ------------------------------------------------------------ APIs
	def _cargar_apis(self) -> dict[str, ConfiguracionServicio]:
		try:
			with open(self.ruta_apis, encoding="utf-8") as f:
				datos = json.load(f)
		except FileNotFoundError:
			return {}
		except (OSError, ValueError):
			log.exception("No se pudo leer %s", self.ruta_apis)
			return {}
		servicios = {}
		if isinstance(datos, dict):
			for nombre, valor in datos.items():
				if isinstance(valor, dict):
					servicios[str(nombre)] = ConfiguracionServicio.desde_diccionario(valor)
		return servicios

	def _guardar_apis(self) -> None:
		with self._bloqueo:
			datos = {nombre: s.a_diccionario() for nombre, s in self.servicios.items()}
			tmp = self.ruta_apis + ".tmp"
			try:
				with open(tmp, "w", encoding="utf-8") as f:
					json.dump(datos, f, indent="\t", ensure_ascii=False)
				os.replace(tmp, self.ruta_apis)
			except OSError:
				log.exception("No se pudieron guardar las claves de API")

	def guardar(self) -> None:
		"""Guarda las claves y ajustes de los servicios.

		Las opciones normales ya están en la configuración de Tiresias, que se
		guarda al salir (o con «Guardar configuración»).
		"""
		self._guardar_apis()

	def obtener_api(self, servicio: str) -> ConfiguracionServicio | None:
		return self.servicios.get(servicio)

	def establecer_api(
		self,
		servicio: str,
		api_key: str | None = None,
		api_url: str | None = None,
		modelo: str | None = None,
		claves: list[str] | None = None,
		usar_rotacion: bool = False,
		**kwargs: Any,
	) -> ConfiguracionServicio:
		"""Crea o actualiza los ajustes de ``servicio``.

		``claves`` son claves ya cifradas; ``api_key`` es una sola clave en claro.
		Los argumentos que no se pasan conservan su valor (el original los
		borraba, de modo que al guardar las claves se perdían modelo y prompts).
		"""
		with self._bloqueo:
			s = self.servicios.setdefault(servicio, ConfiguracionServicio())
			if claves is not None:
				s.claves = list(claves)
			elif api_key:
				s.claves = [seguridad.codificar_api_key(api_key)]
			s.usar_rotacion = bool(usar_rotacion)
			if s.indice_actual >= len(s.claves):
				s.indice_actual = 0
			if api_url is not None:
				s.api_url = api_url.strip().rstrip("/") or None
			if modelo is not None:
				s.modelo = modelo.strip() or None
			if "prompt_sistema" in kwargs:
				s.prompt_sistema = kwargs["prompt_sistema"] or None
			if "prompt_usuario" in kwargs:
				s.prompt_usuario = kwargs["prompt_usuario"] or None
			if "parametros_extra" in kwargs:
				s.parametros_extra = dict(kwargs["parametros_extra"] or {})
			return s

	def restablecer(self) -> None:
		"""Vuelve a los valores de fábrica (no borra las claves de API)."""
		from tiresias.config import conf

		for clave, valor in valores_por_defecto().items():
			conf[SECCION][clave] = valor

	# ------------------------------------------------------------ accesos directos
	def _leer(self, clave: str) -> Any:
		from tiresias.config import conf

		return conf[SECCION][clave]

	def _escribir(self, clave: str, valor: Any) -> None:
		from tiresias.config import conf

		conf[SECCION][clave] = valor

	servicio_activo = property(lambda s: s._leer("servicio_activo"), lambda s, v: s._escribir("servicio_activo", v))
	idioma_destino = property(lambda s: s._leer("idioma_destino"), lambda s, v: s._escribir("idioma_destino", v))
	idioma_origen = property(lambda s: s._leer("idioma_origen"), lambda s, v: s._escribir("idioma_origen", v))
	idioma_destino_alternativo = property(lambda s: s._leer("idioma_destino_alternativo"), lambda s, v: s._escribir("idioma_destino_alternativo", v))
	cache_habilitada = property(lambda s: bool(s._leer("cache_habilitada")), lambda s, v: s._escribir("cache_habilitada", bool(v)))
	historial_habilitado = property(lambda s: bool(s._leer("historial_habilitado")), lambda s, v: s._escribir("historial_habilitado", bool(v)))
	mostrar_resultados = property(lambda s: bool(s._leer("mostrar_resultados")), lambda s, v: s._escribir("mostrar_resultados", bool(v)))
	sonidos_habilitados = property(lambda s: bool(s._leer("sonidos_habilitados")), lambda s, v: s._escribir("sonidos_habilitados", bool(v)))
	intercambio_automatico_idioma = property(lambda s: bool(s._leer("intercambio_automatico_idioma")), lambda s, v: s._escribir("intercambio_automatico_idioma", bool(v)))
