"""Catálogo de la Audiocinemateca: carga, colecciones, búsqueda y fichas.

El catálogo es un JSON con las listas ``peliculas``, ``series``,
``documentales`` y ``cortometrajes``. Cada colección se muestra al revés (lo
último que se añadió, primero). Las películas usan la clave ``Titulo`` (con
mayúscula) y pueden tener varias partes (``enlaces``); las series tienen
``capitulos`` (temporada -> lista de episodios con ``capitulo``, ``titulo`` y
``enlace``); los documentales y cortometrajes, un ``enlace``.
"""

from __future__ import annotations

import json
import os
import random
import textwrap

from . import ajustes

#: Signos de puntuación que se quitan al buscar (los de ``string.punctuation``).
PUNTUACION = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"
_DIACRITICOS = (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"))
#: Palabras que no cuentan al buscar por conjuntos de palabras.
PALABRAS_VACIAS = {"a", "y", "el", "la", "los", "las", "en", "un", "una", "unos", "de", "del"}
#: Máximo de resultados que se añaden por coincidencia parcial de texto.
LIMITE_PARCIALES = 100


def titulo(datos: dict) -> str:
	"""Título de un elemento (las películas usan ``Titulo``)."""
	return str(datos.get("Titulo") or datos.get("titulo") or "")


def _normalizar(texto: str) -> str:
	texto = str(texto).lower()
	for s in PUNTUACION:
		texto = texto.replace(s, "")
	for original, cambio in _DIACRITICOS:
		texto = texto.replace(original, cambio)
	return texto


def campoBusqueda(datos: dict, campo: str) -> str:
	if campo in ("titulo", "Titulo"):
		return titulo(datos)
	valor = datos.get(campo, "")
	return "" if valor is None else str(valor)


def buscarEn(elementos: list[dict], valor: str, campo: str) -> list[dict]:
	"""Busca ``valor`` en ``campo`` de cada elemento (sin tildes ni puntuación).

	Coincide si están todas las palabras buscadas (sin artículos), si falta
	solo una pero aparece como parte de otra palabra, o si el texto buscado
	aparece tal cual dentro del campo (estas últimas solo mientras haya 100
	resultados o menos).
	"""
	resultados: list[dict] = []
	valorN = _normalizar(valor).strip()
	if not valorN:
		return resultados
	buscadas = set(valorN.split()) - PALABRAS_VACIAS
	for item in elementos:
		crudo = campoBusqueda(item, campo)
		if not crudo:
			continue
		texto = _normalizar(crudo)
		palabras = set(texto.split())
		if buscadas and buscadas.issubset(palabras):
			resultados.append(item)
		elif buscadas & palabras and len(buscadas - palabras) == 1 and next(iter(buscadas - palabras)) in texto:
			resultados.append(item)
		elif valorN in texto and len(resultados) <= LIMITE_PARCIALES:
			resultados.append(item)
	return resultados


class Coleccion:
	"""Una categoría del catálogo, de lo más reciente a lo más antiguo."""

	def __init__(self, clave: str, datos: list[dict]) -> None:
		self.clave = clave
		self.datos = list(datos or [])
		self.elementos = list(reversed(self.datos))

	def __len__(self) -> int:
		return len(self.elementos)

	def titulos(self) -> list[str]:
		return [titulo(d) for d in self.elementos]

	def get(self, indice: int) -> dict:
		return self.elementos[indice]

	def buscar(self, valor: str, campo: str) -> list[dict]:
		return buscarEn(self.elementos, valor, campo)

	def porId(self, idItem) -> dict | None:
		for d in self.datos:
			if d.get("id") == idItem:
				return d
		return None

	def ultimos(self, cantidad: int) -> list[dict]:
		return self.elementos[: max(0, cantidad)]


def episodiosPorTemporada(capitulos: dict) -> list[tuple[str, list[dict]]]:
	"""Temporadas ordenadas (``[(temporada, [episodios])]``)."""

	def orden(t: str):
		try:
			return (0, int(t))
		except (TypeError, ValueError):
			return (1, str(t))

	if not isinstance(capitulos, dict):
		return []
	return [(str(t), list(capitulos[t] or [])) for t in sorted(capitulos, key=orden)]


class GestorCatalogo:
	"""Carga el catálogo (``catalogo.json``) y su versión (``version.json``)."""

	def __init__(self, carpeta: str | None = None) -> None:
		carpeta = carpeta or ajustes.dirDatos()
		self.carpeta = carpeta
		self.rutaCatalogo = os.path.join(carpeta, "catalogo.json")
		self.rutaVersion = os.path.join(carpeta, "version.json")
		self.version: dict = {}
		self.colecciones: dict[str, Coleccion] = {}
		self.cargado = False

	def existe(self) -> bool:
		return os.path.isfile(self.rutaCatalogo)

	def cargar(self) -> bool:
		"""Lee el catálogo y la versión del disco. Devuelve si se pudo cargar."""
		self.cargarVersion()
		try:
			with open(self.rutaCatalogo, encoding="utf-8") as f:
				datos = json.load(f)
			self.colecciones = {c: Coleccion(c, datos.get(c, [])) for c in ajustes.CLAVES_CATEGORIA}
			self.cargado = True
		except Exception:
			self.colecciones = {}
			self.cargado = False
		return self.cargado

	def cargarVersion(self) -> dict:
		try:
			with open(self.rutaVersion, encoding="utf-8") as f:
				v = json.load(f)
			self.version = v if isinstance(v, dict) else {}
		except Exception:
			self.version = {}
		return self.version

	def limpiar(self) -> None:
		"""Libera la memoria del catálogo (al cerrar la ventana)."""
		self.colecciones = {}
		self.cargado = False

	def coleccion(self, clave: str) -> Coleccion | None:
		return self.colecciones.get(clave)

	def buscarId(self, categoria: str, idItem) -> dict | None:
		col = self.coleccion(categoria)
		return col.porId(idItem) if col else None

	def buscarGlobal(self, texto: str) -> list[tuple[dict, str]]:
		"""Busca por título en todas las categorías: ``[(datos, categoría)]``."""
		res: list[tuple[dict, str]] = []
		for clave in ajustes.CLAVES_CATEGORIA:
			col = self.coleccion(clave)
			if col is None:
				continue
			res.extend((d, clave) for d in col.buscar(texto, "titulo"))
		return res

	def aleatorio(self, rnd: random.Random | None = None) -> tuple[str, dict] | None:
		"""Un elemento al azar de una categoría al azar (con contenido)."""
		rnd = rnd or random
		disponibles = [c for c in ajustes.CLAVES_CATEGORIA if self.coleccion(c) and len(self.coleccion(c))]
		if not disponibles:
			return None
		categoria = rnd.choice(disponibles)
		return categoria, rnd.choice(self.coleccion(categoria).elementos)


# ---------------------------------------------------------------- fichas
def partirTexto(texto: str, longitud: int) -> str:
	return "\n".join(textwrap.wrap(str(texto or ""), longitud))


def idioma(datos: dict) -> str:
	return "Español" if str(datos.get("idioma", "")) == "1" else "Español latino"


def textoFicha(datos: dict, categoria: str) -> str:
	"""Texto completo de la ficha que se muestra en el diálogo."""
	duracion = str(datos.get("duracion", "") or "")
	if categoria == "series":
		duracion += " minutos por episodio"
	else:
		duracion += " minutos"
	campos = [
		("Título", titulo(datos)),
		("Año", datos.get("anio", "")),
		("Género", datos.get("genero", "")),
		("País", datos.get("pais", "")),
		("Director", datos.get("director", "")),
		("Guion", datos.get("guion", "")),
		("Música", datos.get("musica", "")),
		("Fotografía", datos.get("fotografia", "")),
		("Reparto", partirTexto(datos.get("reparto", ""), 70)),
		("Productora", datos.get("productora", "")),
		("Narración", datos.get("narracion", "")),
		("Duración", duracion),
	]
	if categoria == "series":
		campos.append(("Temporadas", str(datos.get("temporadas", ""))))
	campos += [("Idioma", idioma(datos)), ("Sinopsis", partirTexto(datos.get("sinopsis", ""), 100))]
	return "".join(f"{etiqueta}:\n{'' if valor is None else valor}\n\n" for etiqueta, valor in campos)


def textoCopiar(datos: dict, categoria: str) -> str:
	"""Texto que se copia al portapapeles (Control+C o «Copiar información»)."""
	lineas = [
		titulo(datos),
		f"Año: {datos.get('anio', '')}",
		f"Género: {datos.get('genero', '')}",
		f"Director: {datos.get('director', '')}",
	]
	if categoria == "series":
		lineas.append(f"Temporadas: {datos.get('temporadas', '')}")
	lineas += [f"Sinopsis: {datos.get('sinopsis', '')}", ajustes.URL_WEB]
	return "\n".join(lineas)


def enlaces(datos: dict, categoria: str) -> list[str]:
	"""Enlaces reproducibles de una película (partes), documental o cortometraje."""
	if categoria == "peliculas":
		lista = datos.get("enlaces") or []
		return [str(e) for e in (lista if isinstance(lista, list) else [lista])]
	enlace = datos.get("enlace")
	return [str(enlace)] if enlace else []


def urlContenido(enlace: str) -> str:
	"""Dirección completa de un enlace del catálogo (relativo a la web)."""
	enlace = str(enlace or "")
	if enlace.startswith(("http://", "https://")):
		return enlace
	return ajustes.URL_BASE + enlace.lstrip("/")
