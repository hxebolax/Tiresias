"""Datos del usuario: favoritos, marcas de visualización, historiales, listas
personalizadas y estadísticas. Cada uno se guarda en un JSON propio dentro de
la carpeta de datos del complemento (escritura atómica y con cerrojo, porque
se usan desde la ventana, las órdenes globales y el temporizador de sueño).
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
from datetime import datetime

from . import ajustes


def _ahora() -> str:
	return datetime.now().strftime("%Y-%m-%d %H:%M")


class AlmacenJson:
	"""Archivo JSON con valor por defecto, carga tolerante y guardado atómico."""

	archivo = ""
	defecto: object = None

	def __init__(self, carpeta: str | None = None) -> None:
		self.ruta = os.path.join(carpeta or ajustes.dirDatos(), self.archivo)
		self._lock = threading.RLock()
		self.datos = copy.deepcopy(self.defecto)
		self.cargar()

	def cargar(self) -> None:
		with self._lock:
			try:
				with open(self.ruta, encoding="utf-8") as f:
					datos = json.load(f)
				self.datos = self._normalizar(datos)
			except FileNotFoundError:
				self.datos = copy.deepcopy(self.defecto)
			except Exception:
				# Archivo dañado: se empieza de cero (como el original).
				self.datos = copy.deepcopy(self.defecto)

	def _normalizar(self, datos):
		if not isinstance(datos, type(self.defecto)):
			return copy.deepcopy(self.defecto)
		return datos

	def guardar(self) -> None:
		with self._lock:
			tmp = self.ruta + ".tmp"
			try:
				with open(tmp, "w", encoding="utf-8") as f:
					json.dump(self.datos, f, ensure_ascii=False, indent="\t")
				os.replace(tmp, self.ruta)
			except OSError:
				try:
					os.remove(tmp)
				except OSError:
					pass

	def vaciar(self) -> None:
		with self._lock:
			self.datos = copy.deepcopy(self.defecto)
			self.guardar()


# ---------------------------------------------------------------- favoritos
class GestorFavoritos(AlmacenJson):
	"""Favoritos por categoría (listas de identificadores)."""

	archivo = "favoritos.json"
	defecto = {c: [] for c in ajustes.CLAVES_CATEGORIA}

	def _normalizar(self, datos):
		datos = super()._normalizar(datos)
		for c in ajustes.CLAVES_CATEGORIA:
			if not isinstance(datos.get(c), list):
				datos[c] = []
		return datos

	def agregar(self, categoria: str, idItem) -> None:
		with self._lock:
			lista = self.datos.setdefault(categoria, [])
			if idItem not in lista:
				lista.append(idItem)
				self.guardar()

	def quitar(self, categoria: str, idItem) -> None:
		with self._lock:
			lista = self.datos.get(categoria, [])
			if idItem in lista:
				lista.remove(idItem)
				self.guardar()

	def alternar(self, categoria: str, idItem) -> bool:
		"""Agrega o quita; devuelve si queda como favorito."""
		if self.esFavorito(categoria, idItem):
			self.quitar(categoria, idItem)
			return False
		self.agregar(categoria, idItem)
		return True

	def esFavorito(self, categoria: str, idItem) -> bool:
		return idItem in self.datos.get(categoria, [])

	def obtener(self, categoria: str) -> list:
		return list(self.datos.get(categoria, []))


# ---------------------------------------------------------------- marcas de visualización
class GestorVisualizacion(AlmacenJson):
	"""Posición en la que se dejó cada contenido (clave: SHA-256 de su dirección)."""

	archivo = "visualizacion.json"
	defecto: dict = {}

	@staticmethod
	def firma(url: str) -> str:
		return hashlib.sha256(str(url).encode("utf-8")).hexdigest()

	def guardarPosicion(self, url: str, segundos: float) -> None:
		if not url:
			return
		with self._lock:
			self.datos[self.firma(url)] = float(segundos)
			self.guardar()

	def obtenerPosicion(self, url: str) -> float | None:
		v = self.datos.get(self.firma(url))
		try:
			return None if v is None else float(v)
		except (TypeError, ValueError):
			return None

	def borrarPosicion(self, url: str) -> None:
		with self._lock:
			if self.datos.pop(self.firma(url), None) is not None:
				self.guardar()


# ---------------------------------------------------------------- historial de reproducción
class GestorHistorial(AlmacenJson):
	"""Contenidos reproducidos (el más reciente primero, sin repetir)."""

	archivo = "historial.json"
	defecto: list = []
	MAXIMO = 200

	def registrar(self, idContenido, categoria: str, titulo: str, posicion: float = 0.0, duracion: float = 0.0, url: str = "") -> None:
		entrada = {
			"id": idContenido,
			"categoria": categoria,
			"titulo": titulo,
			"fecha": _ahora(),
			"posicion": posicion,
			"duracion": duracion,
			"url": url,
		}
		with self._lock:
			self.datos = [e for e in self.datos if not (e.get("id") == idContenido and e.get("categoria") == categoria)]
			self.datos.insert(0, entrada)
			del self.datos[self.MAXIMO :]
			self.guardar()

	def obtener(self, limite: int = 50) -> list[dict]:
		return list(self.datos[:limite])

	def obtenerPorCategoria(self, categoria: str, limite: int = 50) -> list[dict]:
		return [e for e in self.datos if e.get("categoria") == categoria][:limite]


# ---------------------------------------------------------------- historial de búsqueda
class GestorHistorialBusqueda(AlmacenJson):
	"""Últimas búsquedas: texto, filtro y pestaña (-1 = búsqueda global)."""

	archivo = "historial_busqueda.json"
	defecto: list = []
	MAXIMO = 20

	def registrar(self, texto: str, filtro: str, categoria: int, indiceFiltro: int = 0) -> None:
		entrada = {"texto": texto, "filtro": filtro, "indiceFiltro": indiceFiltro, "categoria": categoria, "fecha": _ahora()}
		with self._lock:
			if self.datos and self.datos[0].get("texto") == texto and self.datos[0].get("categoria") == categoria:
				self.datos.pop(0)
			self.datos.insert(0, entrada)
			del self.datos[self.MAXIMO :]
			self.guardar()

	def obtener(self, categoria: int | None = None, limite: int = 10) -> list[dict]:
		datos = self.datos if categoria is None else [e for e in self.datos if e.get("categoria") == categoria]
		return list(datos[:limite])


# ---------------------------------------------------------------- listas personalizadas
class GestorListas(AlmacenJson):
	"""Listas con nombre propio; cada una guarda sus elementos (id, categoría, título)."""

	archivo = "listas.json"
	defecto: dict = {}

	def _normalizar(self, datos):
		datos = super()._normalizar(datos)
		for nombre, lista in list(datos.items()):
			if not isinstance(lista, dict) or not isinstance(lista.get("items"), list):
				datos[nombre] = {"fecha_creacion": _ahora(), "items": []}
		return datos

	def crearLista(self, nombre: str) -> bool:
		with self._lock:
			if not nombre or nombre in self.datos:
				return False
			self.datos[nombre] = {"fecha_creacion": _ahora(), "items": []}
			self.guardar()
			return True

	def eliminarLista(self, nombre: str) -> bool:
		with self._lock:
			if nombre in self.datos:
				del self.datos[nombre]
				self.guardar()
				return True
			return False

	def renombrarLista(self, actual: str, nuevo: str) -> bool:
		with self._lock:
			if actual in self.datos and nuevo and nuevo not in self.datos:
				# Conserva el orden de las listas.
				self.datos = {(nuevo if k == actual else k): v for k, v in self.datos.items()}
				self.guardar()
				return True
			return False

	def nombres(self) -> list[str]:
		return list(self.datos.keys())

	def agregarItem(self, nombre: str, idItem, categoria: str, titulo: str) -> bool:
		with self._lock:
			if nombre not in self.datos:
				return False
			items = self.datos[nombre]["items"]
			if any(i.get("id") == idItem and i.get("categoria") == categoria for i in items):
				return False
			items.append({"id": idItem, "categoria": categoria, "titulo": titulo, "fecha": _ahora()})
			self.guardar()
			return True

	def quitarItem(self, nombre: str, idItem, categoria: str) -> bool:
		with self._lock:
			items = self.datos.get(nombre, {}).get("items", [])
			for i, item in enumerate(items):
				if item.get("id") == idItem and item.get("categoria") == categoria:
					items.pop(i)
					self.guardar()
					return True
			return False

	def items(self, nombre: str) -> list[dict]:
		return list(self.datos.get(nombre, {}).get("items", []))

	def estaEnLista(self, nombre: str, idItem, categoria: str) -> bool:
		return any(i.get("id") == idItem and i.get("categoria") == categoria for i in self.items(nombre))


# ---------------------------------------------------------------- estadísticas
class GestorEstadisticas(AlmacenJson):
	"""Reproducciones, tiempo escuchado y contenidos más escuchados."""

	archivo = "estadisticas.json"
	defecto = {
		"total_reproducciones": 0,
		"tiempo_total_segundos": 0.0,
		"por_categoria": {c: 0 for c in ajustes.CLAVES_CATEGORIA},
		"contenidos": {},
	}

	def _normalizar(self, datos):
		base = copy.deepcopy(self.defecto)
		if isinstance(datos, dict):
			for k in base:
				if isinstance(datos.get(k), type(base[k])) or (k == "tiempo_total_segundos" and isinstance(datos.get(k), (int, float))):
					base[k] = datos[k]
			for c in ajustes.CLAVES_CATEGORIA:
				base["por_categoria"].setdefault(c, 0)
		return base

	def registrarReproduccion(self, idContenido, categoria: str, titulo: str, segundos: float = 0.0) -> None:
		with self._lock:
			d = self.datos
			d["total_reproducciones"] += 1
			d["tiempo_total_segundos"] = float(d["tiempo_total_segundos"]) + float(segundos)
			if categoria in d["por_categoria"]:
				d["por_categoria"][categoria] += 1
			clave = f"{categoria}:{idContenido}"
			info = d["contenidos"].setdefault(clave, {"titulo": titulo, "categoria": categoria, "veces": 0, "tiempo_total": 0.0})
			info["veces"] += 1
			info["tiempo_total"] = float(info.get("tiempo_total", 0.0)) + float(segundos)
			self.guardar()

	def acumularTiempo(self, segundos: float) -> None:
		if segundos <= 0:
			return
		with self._lock:
			self.datos["tiempo_total_segundos"] = float(self.datos["tiempo_total_segundos"]) + float(segundos)
			self.guardar()

	def resumen(self) -> dict:
		d = self.datos
		masReproducido = None
		maximo = 0
		for info in d["contenidos"].values():
			if info.get("veces", 0) > maximo:
				maximo = info["veces"]
				masReproducido = info
		porCategoria = dict(d["por_categoria"])
		favorita = max(porCategoria, key=porCategoria.get) if porCategoria and max(porCategoria.values()) > 0 else None
		return {
			"total_reproducciones": d["total_reproducciones"],
			"tiempo_total_segundos": d["tiempo_total_segundos"],
			"por_categoria": porCategoria,
			"mas_reproducido": masReproducido,
			"categoria_favorita": favorita,
		}

	def top(self, limite: int = 10) -> list[dict]:
		return sorted(self.datos["contenidos"].values(), key=lambda x: x.get("veces", 0), reverse=True)[:limite]
