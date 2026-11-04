"""Historial de TCA-Portapapeles y vigilante del portapapeles.

- :class:`Historial` guarda los elementos (el más reciente primero, como mucho
  :data:`MAXIMO`). Si se copia algo cuyo texto ya está, se sube al principio.
- :class:`Vigilante` es un hilo que mira el número de secuencia del
  portapapeles cada cierto tiempo y avisa cuando cambia. Se puede pausar (al
  pegar desde el historial, para no guardar lo que pone el propio complemento).
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from .portapapeles import Elemento, esTextoDeLimpieza

#: Número máximo de elementos del historial (el del original).
MAXIMO = 50


class Historial:
	def __init__(self, maximo: int = MAXIMO) -> None:
		self.maximo = maximo
		self._elementos: list[Elemento] = []
		self._lock = threading.Lock()

	def __len__(self) -> int:
		with self._lock:
			return len(self._elementos)

	@property
	def elementos(self) -> list[Elemento]:
		"""Copia de la lista (el más reciente primero)."""
		with self._lock:
			return list(self._elementos)

	def agregar(self, elemento: Elemento) -> bool:
		"""Añade ``elemento``; ``True`` si es nuevo (hay que avisar)."""
		texto = elemento.texto
		if not texto.strip() and not elemento.tieneFormatos:
			return False
		if esTextoDeLimpieza(texto) and not elemento.tieneFormatos:
			return False
		with self._lock:
			if self._elementos and self._elementos[0].texto == texto:
				# El mismo contenido otra vez (la aplicación lo vuelve a poner o
				# lo escribe en dos veces): se quedan los formatos más completos.
				if len(elemento.formatos) >= len(self._elementos[0].formatos):
					self._elementos[0] = elemento
				return False
			for i, e in enumerate(self._elementos):
				if e.texto == texto:
					del self._elementos[i]
					break
			self._elementos.insert(0, elemento)
			del self._elementos[self.maximo :]
			return True

	def borrar(self, elemento: Elemento) -> bool:
		"""Borra ``elemento`` (por identidad); ``False`` si ya no estaba."""
		with self._lock:
			for i, e in enumerate(self._elementos):
				if e is elemento:
					del self._elementos[i]
					return True
		return False

	def borrarTodo(self) -> None:
		with self._lock:
			self._elementos.clear()


class Vigilante(threading.Thread):
	"""Hilo que llama a ``alCambiar()`` cuando cambia el portapapeles.

	``secuencia`` devuelve el número de secuencia del portapapeles (las pruebas
	lo sustituyen). ``alCambiar`` se ejecuta en este hilo.
	"""

	def __init__(self, intervaloMs: int, alCambiar: Callable[[], None], secuencia: Callable[[], int], nombre: str = "TCA-Portapapeles") -> None:
		super().__init__(name=nombre, daemon=True)
		self.intervalo = max(20, int(intervaloMs)) / 1000.0
		self._alCambiar = alCambiar
		self._secuencia = secuencia
		self._parar = threading.Event()
		self._pausado = threading.Event()
		self._ultima = secuencia()

	@property
	def pausado(self) -> bool:
		return self._pausado.is_set()

	def pausar(self) -> None:
		self._pausado.set()

	def reanudar(self) -> None:
		"""Sigue vigilando a partir de ahora (lo cambiado durante la pausa no cuenta)."""
		self._ultima = self._secuencia()
		self._pausado.clear()

	def cambiarIntervalo(self, intervaloMs: int) -> None:
		self.intervalo = max(20, int(intervaloMs)) / 1000.0

	def detener(self) -> None:
		self._parar.set()

	def comprobar(self) -> bool:
		"""Una vuelta del bucle: ``True`` si el portapapeles cambió y se avisó."""
		seq = self._secuencia()
		if seq == self._ultima:
			return False
		self._ultima = seq
		if self._pausado.is_set():
			return False
		# Margen para que la aplicación termine de escribir todos los formatos.
		if self._parar.wait(0.05) or self._pausado.is_set():
			return False
		try:
			self._alCambiar()
		except Exception:
			from tiresias.log import getLogger

			getLogger("tcaPortapapeles").debug("Error atendiendo un cambio del portapapeles", exc_info=True)
			time.sleep(0.05)
		return True

	def run(self) -> None:
		while not self._parar.wait(self.intervalo):
			self.comprobar()
