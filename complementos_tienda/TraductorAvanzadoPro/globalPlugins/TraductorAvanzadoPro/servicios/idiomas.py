"""Idiomas disponibles para traducir.

El original solo ofrecía en sus diálogos 11 idiomas comunes. Aquí la lista
general tiene todos los idiomas habituales de Google Translate; cada servicio
convierte el código a su formato (DeepL en mayúsculas, Microsoft ``zh-Hans``...)
con :meth:`TraductorBase.adaptar_idioma`. Se pueden añadir o renombrar idiomas
con un archivo ``idiomas.json`` (``{"servicio": {"código": "nombre"}}``) en la
carpeta de datos del complemento.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from tiresias.log import getLogger

if TYPE_CHECKING:
	from ..nucleo.configuracion import GestorConfiguracion

log = getLogger("TraductorAvanzadoPro")

AUTO = "auto"

IDIOMAS_COMUNES: dict[str, str] = {
	"auto": "Detectar automáticamente",
	"af": "Afrikáans",
	"sq": "Albanés",
	"de": "Alemán",
	"am": "Amárico",
	"ar": "Árabe",
	"hy": "Armenio",
	"az": "Azerí",
	"bn": "Bengalí",
	"be": "Bielorruso",
	"my": "Birmano",
	"bs": "Bosnio",
	"bg": "Búlgaro",
	"km": "Camboyano (jemer)",
	"kn": "Canarés",
	"ca": "Catalán",
	"cs": "Checo",
	"zh": "Chino simplificado",
	"zh-TW": "Chino tradicional",
	"si": "Cingalés",
	"ko": "Coreano",
	"ht": "Criollo haitiano",
	"hr": "Croata",
	"da": "Danés",
	"sk": "Eslovaco",
	"sl": "Esloveno",
	"es": "Español",
	"eo": "Esperanto",
	"et": "Estonio",
	"eu": "Euskera",
	"fi": "Finés",
	"fr": "Francés",
	"cy": "Galés",
	"gl": "Gallego",
	"ka": "Georgiano",
	"el": "Griego",
	"gu": "Guyaratí",
	"ha": "Hausa",
	"he": "Hebreo",
	"hi": "Hindi",
	"nl": "Neerlandés",
	"hu": "Húngaro",
	"id": "Indonesio",
	"en": "Inglés",
	"ga": "Irlandés",
	"is": "Islandés",
	"it": "Italiano",
	"ja": "Japonés",
	"jv": "Javanés",
	"kk": "Kazajo",
	"ky": "Kirguís",
	"ku": "Kurdo",
	"lo": "Lao",
	"la": "Latín",
	"lv": "Letón",
	"lt": "Lituano",
	"lb": "Luxemburgués",
	"mk": "Macedonio",
	"ms": "Malayo",
	"ml": "Malayalam",
	"mt": "Maltés",
	"mi": "Maorí",
	"mr": "Maratí",
	"mn": "Mongol",
	"ne": "Nepalí",
	"no": "Noruego",
	"pa": "Panyabí",
	"fa": "Persa",
	"pl": "Polaco",
	"pt": "Portugués",
	"ro": "Rumano",
	"ru": "Ruso",
	"sr": "Serbio",
	"sw": "Suajili",
	"sv": "Sueco",
	"tl": "Tagalo (filipino)",
	"th": "Tailandés",
	"ta": "Tamil",
	"tt": "Tártaro",
	"te": "Telugu",
	"tr": "Turco",
	"uk": "Ucraniano",
	"ur": "Urdu",
	"uz": "Uzbeko",
	"vi": "Vietnamita",
	"yi": "Yidis",
	"yo": "Yoruba",
	"zu": "Zulú",
}


class GestorIdiomas:
	def __init__(self, configuracion: "GestorConfiguracion") -> None:
		self.configuracion = configuracion
		self.idiomas_cache: dict[str, dict[str, str]] = {}
		self._cargar_idiomas_personalizados()

	def _cargar_idiomas_personalizados(self) -> None:
		for carpeta in (getattr(self.configuracion, "ruta_config", None), os.path.join(getattr(self.configuracion, "ruta_complemento", "") or "", "datos")):
			if not carpeta:
				continue
			ruta = os.path.join(carpeta, "idiomas.json")
			if not os.path.isfile(ruta):
				continue
			try:
				with open(ruta, encoding="utf-8-sig") as f:
					datos = json.load(f)
				for servicio, idiomas in (datos or {}).items():
					if isinstance(idiomas, dict):
						self.idiomas_cache.setdefault(str(servicio), {}).update({str(k): str(v) for k, v in idiomas.items()})
			except (OSError, ValueError):
				log.warning("Error cargando idiomas de %s", ruta, exc_info=True)

	def obtener_idiomas(self, servicio: str | None = None) -> dict[str, str]:
		if servicio and servicio in self.idiomas_cache:
			return dict(self.idiomas_cache[servicio])
		idiomas = dict(IDIOMAS_COMUNES)
		idiomas.update(self.idiomas_cache.get("comunes", {}))
		return idiomas

	def obtener_lista_idiomas(self, servicio: str | None = None, incluir_auto: bool = True) -> list[tuple[str, str]]:
		"""Pares ``(código, nombre)`` ordenados por nombre («Detectar» el primero)."""
		idiomas = self.obtener_idiomas(servicio)
		auto = idiomas.pop(AUTO, None)
		lista = sorted(idiomas.items(), key=lambda kv: _clave_orden(kv[1]))
		if incluir_auto and auto:
			lista.insert(0, (AUTO, auto))
		return lista

	def obtener_nombre_idioma(self, codigo: str) -> str:
		if not codigo:
			return ""
		if codigo in IDIOMAS_COMUNES:
			return IDIOMAS_COMUNES[codigo]
		for idiomas in self.idiomas_cache.values():
			if codigo in idiomas:
				return idiomas[codigo]
		bajo = codigo.lower()
		for cod, nombre in IDIOMAS_COMUNES.items():
			if cod.lower() == bajo:
				return nombre
		base = bajo.replace("_", "-").split("-")[0]
		if base in IDIOMAS_COMUNES:
			return IDIOMAS_COMUNES[base]
		from ..utilidades import lector

		return lector.nombre_idioma(codigo) or codigo.upper()

	def obtener_codigo_por_nombre(self, nombre: str) -> str | None:
		bajo = nombre.lower()
		for codigo, n in IDIOMAS_COMUNES.items():
			if n.lower() == bajo:
				return codigo
		for idiomas in self.idiomas_cache.values():
			for codigo, n in idiomas.items():
				if n.lower() == bajo:
					return codigo
		return None

	def registrar_idiomas_servicio(self, servicio: str, idiomas: dict[str, str]) -> None:
		self.idiomas_cache[servicio] = dict(idiomas)

	def obtener_idioma_sistema(self) -> str:
		from ..utilidades import lector

		return lector.idioma_interfaz()

	def es_idioma_valido(self, codigo: str, servicio: str | None = None) -> bool:
		return codigo in self.obtener_idiomas(servicio)


def _clave_orden(nombre: str) -> str:
	import unicodedata

	return "".join(c for c in unicodedata.normalize("NFD", nombre.lower()) if unicodedata.category(c) != "Mn")
