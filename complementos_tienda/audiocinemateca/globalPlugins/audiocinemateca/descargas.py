"""Cola de descargas en segundo plano.

Las descargas se hacen de una en una en un hilo propio, con autenticación
HTTP básica. Al terminar cada una se avisa por voz. Las completadas se
anotan en ``descargas.json`` para reproducirlas después sin conexión.
"""

from __future__ import annotations

import json
import os
import threading
from collections import deque
from typing import Callable

from . import ajustes, red

PENDIENTE = 0
DESCARGANDO = 1
COMPLETADA = 2
ERROR = 3
CANCELADA = 4


class ItemDescarga:
	"""Un elemento de la cola de descargas."""

	def __init__(self, url: str, directorio: str, titulo: str = "") -> None:
		self.url = url
		self.directorio = directorio
		self.titulo = titulo
		self.nombreArchivo = red.nombreArchivoUrl(url) or "descarga.mp3"
		self.estado = PENDIENTE
		self.progreso = 0
		self.error: str | None = None
		self.cancelar = False

	@property
	def rutaCompleta(self) -> str:
		# Siempre dentro de la carpeta elegida (nunca «..\» ni rutas absolutas).
		nombre = os.path.basename(self.nombreArchivo.replace("/", "\\")) or "descarga.mp3"
		return os.path.join(self.directorio, nombre)

	@property
	def nombre(self) -> str:
		return self.titulo or self.nombreArchivo


class GestorDescargas:
	"""Cola de descargas, ítems finalizados de la sesión y registro en disco."""

	def __init__(
		self,
		carpeta: str | None = None,
		credenciales: Callable[[], tuple[str, str]] | None = None,
		avisar: Callable[[str], None] | None = None,
	) -> None:
		self.cola: deque[ItemDescarga] = deque()
		self.actual: ItemDescarga | None = None
		self.finalizadas: list[ItemDescarga] = []
		self._lock = threading.RLock()
		self._hilo: threading.Thread | None = None
		self._credenciales = credenciales or (lambda: (ajustes.estado.usuario, ajustes.estado.contrasena))
		self._avisar = avisar
		self.rutaRegistro = os.path.join(carpeta or ajustes.dirDatos(), "descargas.json")
		self.registro: list[dict] = []
		self._cargarRegistro()

	# -------------------------------------------------- registro en disco
	def _cargarRegistro(self) -> None:
		try:
			with open(self.rutaRegistro, encoding="utf-8") as f:
				datos = json.load(f)
			self.registro = [d for d in datos if isinstance(d, dict)] if isinstance(datos, list) else []
		except Exception:
			self.registro = []

	def _guardarRegistro(self) -> None:
		tmp = self.rutaRegistro + ".tmp"
		try:
			with open(tmp, "w", encoding="utf-8") as f:
				json.dump(self.registro, f, ensure_ascii=False, indent="\t")
			os.replace(tmp, self.rutaRegistro)
		except OSError:
			pass

	def obtenerRegistro(self) -> list[dict]:
		return list(self.registro)

	def limpiarRegistro(self) -> None:
		with self._lock:
			self.registro = []
			self._guardarRegistro()

	def buscarDescargaLocal(self, url: str) -> str | None:
		"""Ruta local de ``url`` si ya se descargó y el archivo sigue existiendo."""
		for item in reversed(self.registro):
			if item.get("url") == url and os.path.isfile(item.get("ruta", "")):
				return item["ruta"]
		return None

	# -------------------------------------------------- cola
	def encolar(self, url: str, directorio: str, titulo: str = "") -> ItemDescarga:
		item = ItemDescarga(url, directorio, titulo)
		with self._lock:
			self.cola.append(item)
			if self._hilo is None or not self._hilo.is_alive():
				self._hilo = threading.Thread(target=self._procesar, name="AudiocinematecaDescargas", daemon=True)
				self._hilo.start()
		return item

	def _procesar(self) -> None:
		while True:
			with self._lock:
				if not self.cola:
					self.actual = None
					return
				item = self.cola.popleft()
				self.actual = item
			self._descargar(item)
			with self._lock:
				self.finalizadas.append(item)

	def _descargar(self, item: ItemDescarga) -> None:
		item.estado = DESCARGANDO
		usuario, contrasena = self._credenciales()

		def progreso(p: float) -> None:
			item.progreso = int(p)

		try:
			os.makedirs(item.directorio, exist_ok=True)
			red.descargar(item.url, item.rutaCompleta, usuario, contrasena, progreso, lambda: item.cancelar)
		except red.Cancelado:
			item.estado = CANCELADA
			return
		except Exception as e:
			item.estado = ERROR
			item.error = red.mensajeError(e)
			return
		item.estado = COMPLETADA
		item.progreso = 100
		with self._lock:
			self.registro.append({"titulo": item.titulo, "archivo": item.nombreArchivo, "ruta": item.rutaCompleta, "url": item.url})
			self._guardarRegistro()
		if self._avisar is not None:
			try:
				self._avisar(f"Descarga completada: {item.nombre}")
			except Exception:
				pass

	def cancelarActual(self) -> bool:
		"""Cancela la descarga en curso. Devuelve si había alguna."""
		with self._lock:
			item = self.actual
			if item is not None and item.estado == DESCARGANDO:
				item.cancelar = True
				return True
		return False

	def quitarPendiente(self, item: ItemDescarga) -> bool:
		"""Quita de la cola una descarga que aún no ha empezado (queda como cancelada)."""
		with self._lock:
			if item in self.cola:
				self.cola.remove(item)
				item.estado = CANCELADA
				self.finalizadas.append(item)
				return True
		return False

	def reintentar(self, item: ItemDescarga) -> ItemDescarga | None:
		if item.estado not in (ERROR, CANCELADA):
			return None
		nuevo = self.encolar(item.url, item.directorio, item.titulo)
		with self._lock:
			if item in self.finalizadas:
				self.finalizadas.remove(item)
		return nuevo

	def obtenerActivas(self) -> list[ItemDescarga]:
		with self._lock:
			res = []
			if self.actual is not None and self.actual.estado == DESCARGANDO:
				res.append(self.actual)
			res.extend(self.cola)
			return res

	def obtenerFinalizadas(self) -> list[ItemDescarga]:
		with self._lock:
			return list(self.finalizadas)

	def limpiarFinalizadas(self) -> None:
		with self._lock:
			self.finalizadas.clear()

	def hayActivas(self) -> bool:
		return bool(self.obtenerActivas())

	def cancelarTodo(self) -> None:
		"""Al cerrar Tiresias: vacía la cola y cancela la descarga en curso."""
		with self._lock:
			self.cola.clear()
			if self.actual is not None:
				self.actual.cancelar = True
