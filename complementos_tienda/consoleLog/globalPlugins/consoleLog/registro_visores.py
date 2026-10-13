"""Registro de visores: una única apertura (pendiente o visible) por consola.

Las órdenes se ejecutan en el hilo del núcleo y los visores viven en el de la
interfaz, así que todas las operaciones están protegidas con un cerrojo.
"""

from __future__ import annotations

import threading
from typing import Any


class RegistroVisores:
	def __init__(self) -> None:
		self._visores: dict[Any, Any] = {}
		self._pendientes: dict[Any, Any] = {}
		self._cerrojo = threading.RLock()

	def obtener(self, clave: Any) -> Any | None:
		with self._cerrojo:
			return self._visores.get(clave)

	def reservar(self, clave: Any, recurso: Any = None) -> bool:
		"""Reserva una consola antes de su primera captura."""
		with self._cerrojo:
			if clave in self._visores or clave in self._pendientes:
				return False
			self._pendientes[clave] = recurso
			return True

	def esta_pendiente(self, clave: Any) -> bool:
		with self._cerrojo:
			return clave in self._pendientes

	def coincide_reserva(self, clave: Any, recurso: Any) -> bool:
		with self._cerrojo:
			return clave in self._pendientes and self._pendientes[clave] is recurso

	def registrar(self, clave: Any, visor: Any) -> bool:
		"""Convierte una reserva en un visor abierto sin sustituir otro."""
		with self._cerrojo:
			if clave in self._visores:
				return False
			self._pendientes.pop(clave, None)
			self._visores[clave] = visor
			return True

	def liberar_reserva(self, clave: Any, recurso: Any = None) -> bool:
		"""Libera una reserva (opcionalmente solo si la creó ``recurso``)."""
		with self._cerrojo:
			if clave not in self._pendientes:
				return False
			if recurso is not None and self._pendientes[clave] is not recurso:
				return False
			del self._pendientes[clave]
			return True

	def retirar(self, clave: Any, visor: Any = None) -> bool:
		"""Retira solo el visor que coincide con la instancia indicada."""
		with self._cerrojo:
			actual = self._visores.get(clave)
			if actual is None or (visor is not None and actual is not visor):
				return False
			del self._visores[clave]
			return True

	def visores(self) -> tuple:
		with self._cerrojo:
			return tuple(self._visores.values())

	def recursos_pendientes(self) -> tuple:
		with self._cerrojo:
			return tuple(self._pendientes.values())

	def limpiar(self) -> None:
		with self._cerrojo:
			self._visores.clear()
			self._pendientes.clear()

	@property
	def cantidad(self) -> int:
		with self._cerrojo:
			return len(self._visores)
