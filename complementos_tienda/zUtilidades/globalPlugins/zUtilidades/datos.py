"""Bases de datos de zUtilidades (lanzador de aplicaciones y notas rápidas).

Cada módulo (``zLauncher`` y ``zNotes``) tiene su carpeta dentro de
``data\\addonsData\\zUtilidades``:

- ``index.json``: lista ordenada de categorías ``{"nombre", "archivo"}``.
- Un archivo por categoría (nombre aleatorio de 15 letras y cifras con
  extensión ``.json``) con la lista ordenada de elementos.

Los elementos son listas, igual que en el complemento original de NVDA:

- ``["app", nombre, ruta, usaParámetros, parámetros, administrador]``
- ``["cmd", nombre, órdenes, pausar, administrador]``
- ``["fol", nombre, carpeta]``
- ``["adr", nombre, accesoDirecto, administrador]``
- ``["sap", nombre, idAplicación, administrador]`` (aplicación instalada)
- ``["txt", nombre, contenido]`` (nota rápida)

Este módulo no usa wx: se puede probar sin interfaz.
"""

from __future__ import annotations

import json
import os
import pickle
import secrets
import shutil
import threading

#: Identificador del complemento (carpeta de datos).
ADDON_ID = "zUtilidades"
#: Módulos con base de datos propia.
LANZADOR = "zLauncher"
NOTAS = "zNotes"
MODULOS = (LANZADOR, NOTAS)

INDICE = "index.json"
VERSION = 1
_LETRAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"

#: Tipos de elemento.
TIPO_APP = "app"
TIPO_CMD = "cmd"
TIPO_CARPETA = "fol"
TIPO_ACCESO = "adr"
TIPO_INSTALADA = "sap"
TIPO_NOTA = "txt"

_lock = threading.RLock()
#: Carpeta base (se puede cambiar en las pruebas); ``None``: la de Tiresias.
_baseDir: str | None = None


def setBaseDir(path: str | None) -> None:
	"""Cambia la carpeta de datos (pruebas). ``None`` vuelve a la de Tiresias."""
	global _baseDir
	_baseDir = path


def baseDir() -> str:
	"""Carpeta ``data\\addonsData\\zUtilidades`` (creada si no existe)."""
	if _baseDir:
		os.makedirs(_baseDir, exist_ok=True)
		return _baseDir
	from tiresias import paths

	return paths.addonDataDir(ADDON_ID)


def moduloDir(modulo: str) -> str:
	"""Carpeta de la base de datos de un módulo (creada si no existe)."""
	if modulo not in MODULOS:
		raise ValueError(f"Módulo desconocido: {modulo}")
	p = os.path.join(baseDir(), modulo)
	os.makedirs(p, exist_ok=True)
	return p


# ====================================================================== archivos
def _leerJson(path: str, defecto):
	try:
		with open(path, encoding="utf-8-sig") as f:
			return json.load(f)
	except FileNotFoundError:
		return defecto
	except (OSError, ValueError):
		return defecto


def _escribirJson(path: str, datos) -> None:
	"""Escribe de forma atómica (archivo temporal y sustitución)."""
	tmp = path + ".tmp"
	with open(tmp, "w", encoding="utf-8") as f:
		json.dump(datos, f, ensure_ascii=False, indent="\t")
	os.replace(tmp, path)


def generarNombreArchivo(existentes, longitud: int = 15) -> str:
	"""Nombre aleatorio para el archivo de una categoría que no esté en ``existentes``."""
	existentes = set(existentes)
	while True:
		nombre = "".join(secrets.choice(_LETRAS) for _ in range(longitud)) + ".json"
		if nombre not in existentes:
			return nombre


def _normalizarElemento(e) -> list | None:
	"""Comprueba y completa un elemento leído de disco (o de una copia antigua)."""
	if not isinstance(e, (list, tuple)) or len(e) < 3:
		return None
	e = list(e)
	tipo = e[0]
	if not isinstance(tipo, str) or not isinstance(e[1], str):
		return None
	largo = {TIPO_APP: 6, TIPO_CMD: 5, TIPO_CARPETA: 3, TIPO_ACCESO: 4, TIPO_INSTALADA: 4, TIPO_NOTA: 3}.get(tipo)
	if largo is None:
		return None
	defectos = {
		TIPO_APP: ["app", "", "", False, "", False],
		TIPO_CMD: ["cmd", "", "", False, False],
		TIPO_CARPETA: ["fol", "", ""],
		TIPO_ACCESO: ["adr", "", "", False],
		TIPO_INSTALADA: ["sap", "", "", False],
		TIPO_NOTA: ["txt", "", ""],
	}[tipo]
	e = (e + defectos[len(e):])[:largo]
	for i, d in enumerate(defectos):
		if isinstance(d, bool):
			e[i] = bool(e[i])
		elif isinstance(d, str) and not isinstance(e[i], str):
			e[i] = "" if e[i] is None else str(e[i])
	return e


# ====================================================================== base de datos
class BaseDatos:
	"""Base de datos de un módulo: categorías y elementos de cada categoría."""

	def __init__(self, modulo: str) -> None:
		if modulo not in MODULOS:
			raise ValueError(f"Módulo desconocido: {modulo}")
		self.modulo = modulo

	# ------------------------------------------------------------------ rutas
	@property
	def carpeta(self) -> str:
		return moduloDir(self.modulo)

	@property
	def archivoIndice(self) -> str:
		return os.path.join(self.carpeta, INDICE)

	def rutaCategoria(self, archivo: str) -> str:
		return os.path.join(self.carpeta, os.path.basename(archivo))

	# ------------------------------------------------------------------ categorías
	def _leerIndice(self) -> list[dict]:
		datos = _leerJson(self.archivoIndice, None)
		if not isinstance(datos, dict):
			return []
		res = []
		for c in datos.get("categorias") or []:
			if isinstance(c, dict) and isinstance(c.get("nombre"), str) and isinstance(c.get("archivo"), str):
				res.append({"nombre": c["nombre"], "archivo": os.path.basename(c["archivo"])})
		return res

	def _guardarIndice(self, categorias: list[dict]) -> None:
		_escribirJson(self.archivoIndice, {"version": VERSION, "categorias": categorias})

	def categorias(self) -> list[dict]:
		"""Categorías ``{"nombre", "archivo"}`` en su orden."""
		with _lock:
			return self._leerIndice()

	def nombresCategorias(self) -> list[str]:
		return [c["nombre"] for c in self.categorias()]

	def comprobar(self) -> int:
		"""Quita del índice las categorías cuyo archivo no existe. Devuelve cuántas."""
		with _lock:
			cats = self._leerIndice()
			buenas = [c for c in cats if os.path.isfile(self.rutaCategoria(c["archivo"]))]
			if len(buenas) != len(cats) or not os.path.isfile(self.archivoIndice):
				self._guardarIndice(buenas)
			return len(cats) - len(buenas)

	def añadirCategoria(self, nombre: str) -> int:
		"""Añade una categoría al final. Devuelve su posición."""
		with _lock:
			cats = self._leerIndice()
			if nombre in [c["nombre"] for c in cats]:
				raise ValueError("Categoría duplicada")
			archivo = generarNombreArchivo([c["archivo"] for c in cats] + os.listdir(self.carpeta))
			self._guardarElementos(archivo, [])
			cats.append({"nombre": nombre, "archivo": archivo})
			self._guardarIndice(cats)
			return len(cats) - 1

	def renombrarCategoria(self, indice: int, nombre: str) -> None:
		with _lock:
			cats = self._leerIndice()
			if any(c["nombre"] == nombre for i, c in enumerate(cats) if i != indice):
				raise ValueError("Categoría duplicada")
			cats[indice]["nombre"] = nombre
			self._guardarIndice(cats)

	def borrarCategoria(self, indice: int) -> None:
		"""Borra la categoría y todos sus elementos."""
		with _lock:
			cats = self._leerIndice()
			c = cats.pop(indice)
			try:
				os.remove(self.rutaCategoria(c["archivo"]))
			except OSError:
				pass
			self._guardarIndice(cats)

	def moverCategoria(self, indice: int, delta: int) -> int | None:
		"""Mueve una categoría arriba (-1) o abajo (+1). ``None`` si ya está en el extremo."""
		with _lock:
			cats = self._leerIndice()
			nuevo = indice + delta
			if not cats or not 0 <= indice < len(cats) or not 0 <= nuevo < len(cats):
				return None
			cats.insert(nuevo, cats.pop(indice))
			self._guardarIndice(cats)
			return nuevo

	# ------------------------------------------------------------------ elementos
	def _leerElementos(self, archivo: str) -> list[list]:
		datos = _leerJson(self.rutaCategoria(archivo), None)
		if not isinstance(datos, dict):
			return []
		res = []
		for e in datos.get("elementos") or []:
			n = _normalizarElemento(e)
			if n is not None:
				res.append(n)
		return res

	def _guardarElementos(self, archivo: str, elementos: list[list]) -> None:
		_escribirJson(self.rutaCategoria(archivo), {"version": VERSION, "elementos": elementos})

	def _archivo(self, indiceCategoria: int) -> str:
		return self._leerIndice()[indiceCategoria]["archivo"]

	def elementos(self, indiceCategoria: int) -> list[list]:
		"""Elementos de una categoría (lista vacía si no existe)."""
		with _lock:
			cats = self._leerIndice()
			if not 0 <= indiceCategoria < len(cats):
				return []
			return self._leerElementos(cats[indiceCategoria]["archivo"])

	def nombresElementos(self, indiceCategoria: int) -> list[str]:
		return [e[1] for e in self.elementos(indiceCategoria)]

	def guardarElementos(self, indiceCategoria: int, elementos: list[list]) -> None:
		with _lock:
			self._guardarElementos(self._archivo(indiceCategoria), elementos)

	def añadirElemento(self, indiceCategoria: int, elemento: list) -> int:
		with _lock:
			archivo = self._archivo(indiceCategoria)
			el = self._leerElementos(archivo)
			if elemento[1] in [e[1] for e in el]:
				raise ValueError("Elemento duplicado")
			el.append(list(elemento))
			self._guardarElementos(archivo, el)
			return len(el) - 1

	def sustituirElemento(self, indiceCategoria: int, indice: int, elemento: list) -> None:
		with _lock:
			archivo = self._archivo(indiceCategoria)
			el = self._leerElementos(archivo)
			if any(e[1] == elemento[1] for i, e in enumerate(el) if i != indice):
				raise ValueError("Elemento duplicado")
			el[indice] = list(elemento)
			self._guardarElementos(archivo, el)

	def borrarElemento(self, indiceCategoria: int, indice: int) -> None:
		with _lock:
			archivo = self._archivo(indiceCategoria)
			el = self._leerElementos(archivo)
			del el[indice]
			self._guardarElementos(archivo, el)

	def moverElemento(self, indiceCategoria: int, indice: int, delta: int) -> int | None:
		"""Mueve un elemento dentro de su categoría. ``None`` si ya está en el extremo."""
		with _lock:
			archivo = self._archivo(indiceCategoria)
			el = self._leerElementos(archivo)
			nuevo = indice + delta
			if not el or not 0 <= indice < len(el) or not 0 <= nuevo < len(el):
				return None
			el.insert(nuevo, el.pop(indice))
			self._guardarElementos(archivo, el)
			return nuevo

	def moverACategoria(self, origen: int, indice: int, destino: int, nuevoNombre: str | None = None) -> None:
		"""Pasa un elemento a otra categoría (al final), con otro nombre si se indica."""
		with _lock:
			cats = self._leerIndice()
			if origen == destino:
				raise ValueError("La categoría de destino es la misma")
			aOrig, aDest = cats[origen]["archivo"], cats[destino]["archivo"]
			elOrig = self._leerElementos(aOrig)
			elDest = self._leerElementos(aDest)
			elem = list(elOrig[indice])
			if nuevoNombre is not None:
				elem[1] = nuevoNombre
			if elem[1] in [e[1] for e in elDest]:
				raise ValueError("Elemento duplicado")
			elDest.append(elem)
			del elOrig[indice]
			self._guardarElementos(aDest, elDest)
			self._guardarElementos(aOrig, elOrig)

	# ------------------------------------------------------------------ todo
	def borrarTodo(self) -> None:
		"""Vuelve a valores por defecto: borra toda la base de datos del módulo."""
		with _lock:
			shutil.rmtree(self.carpeta, ignore_errors=True)
			moduloDir(self.modulo)
			self._guardarIndice([])


# ====================================================================== validación
#: Mensajes de validación (los mismos textos que el original).
MSG_VACIO_CATEGORIA = "El campo no puede quedar en blanco.\n\nIntroduzca un nombre para añadir una categoría."
MSG_DUPLICADO_CATEGORIA = "No puede duplicar el nombre de una categoría.\n\nModifique el nombre para poder continuar."
MSG_DUPLICADO_ACCION = "No puede duplicar el nombre de una acción.\n\nModifique el nombre para poder continuar."
MSG_DUPLICADO_NOTA = "No puede duplicar el nombre de una Nota.\n\nModifique el nombre para poder continuar."


def estaEnLista(lista, buscar) -> bool:
	return buscar in lista


def validarCategoria(nombre: str, existentes: list[str], actual: str | None = None) -> str | None:
	"""Mensaje de error para el nombre de una categoría, o ``None`` si vale.

	``actual``: nombre que tenía al editarla (puede quedarse igual).
	"""
	if nombre == "":
		return MSG_VACIO_CATEGORIA
	if actual is not None and nombre == actual:
		return None
	if estaEnLista(existentes, nombre):
		return MSG_DUPLICADO_CATEGORIA
	return None


def nombreDuplicado(nombre: str, existentes: list[str], actual: str | None = None) -> bool:
	"""¿``nombre`` ya está en ``existentes``? (al editar, puede quedarse igual)."""
	if actual is not None and nombre == actual:
		return False
	return estaEnLista(existentes, nombre)


# ====================================================================== copias antiguas (NVDA)
class _UnpicklerSeguro(pickle.Unpickler):
	"""Lee los ``.dat`` del complemento de NVDA sin permitir objetos arbitrarios.

	Solo contienen números, cadenas, booleanos y listas: cualquier referencia
	a una clase o función se rechaza.
	"""

	def find_class(self, module, name):  # noqa: D401
		raise pickle.UnpicklingError(f"Objeto no permitido en la copia: {module}.{name}")


def leerDatPickle(path: str) -> list:
	"""Lee un ``.dat`` del original: versión y uno o dos objetos más."""
	res = []
	with open(path, "rb") as f:
		up = _UnpicklerSeguro(f)
		while True:
			try:
				res.append(up.load())
			except EOFError:
				break
	return res


def convertirDesdeNVDA(carpeta: str) -> int:
	"""Convierte una base de datos del complemento de NVDA (``index.dat`` y
	``*.dat`` con pickle) que esté en ``carpeta`` al formato de Tiresias.

	Escribe ``index.json`` y un ``.json`` por categoría en la misma carpeta y
	borra los ``.dat``. Devuelve el número de categorías convertidas.
	"""
	indice = os.path.join(carpeta, "index.dat")
	partes = leerDatPickle(indice)
	if len(partes) < 3 or partes[0] != 1.0:
		raise ValueError("Índice de la copia no válido")
	nombres, archivos = partes[1], partes[2]
	if not isinstance(nombres, list) or not isinstance(archivos, list) or len(nombres) != len(archivos):
		raise ValueError("Índice de la copia no válido")
	cats = []
	usados: set[str] = set()
	for nombre, archivo in zip(nombres, archivos):
		if not isinstance(nombre, str) or not isinstance(archivo, str):
			continue
		ruta = os.path.join(carpeta, os.path.basename(archivo))
		elementos: list = []
		if os.path.isfile(ruta):
			datos = leerDatPickle(ruta)
			if len(datos) >= 2 and datos[0] == 1.0 and isinstance(datos[1], list):
				elementos = [n for n in (_normalizarElemento(e) for e in datos[1]) if n is not None]
		else:
			continue
		nuevo = generarNombreArchivo(usados)
		usados.add(nuevo)
		_escribirJson(os.path.join(carpeta, nuevo), {"version": VERSION, "elementos": elementos})
		cats.append({"nombre": nombre, "archivo": nuevo})
	for fn in os.listdir(carpeta):
		if fn.lower().endswith(".dat"):
			try:
				os.remove(os.path.join(carpeta, fn))
			except OSError:
				pass
	_escribirJson(os.path.join(carpeta, INDICE), {"version": VERSION, "categorias": cats})
	return len(cats)
