"""Menús virtuales del lanzador de aplicaciones y de las notas rápidas.

Con doble pulsación de la orden de cada módulo se activa un menú sin
ventana: flechas izquierda y derecha para las categorías, arriba y abajo
para los elementos, letras para saltar a una categoría, Intro para ejecutar
(lanzador), F1, F2 y F3 para leer, copiar o pegar (notas) y Escape para
salir. Mientras está activo, el resto de teclas solo dan la ayuda.

La lógica no depende del teclado: el complemento global traduce las teclas
a llamadas de :class:`MenuVirtual` (en el hilo del núcleo).
"""

from __future__ import annotations

from typing import Callable

from . import datos, estado, sistema

AYUDA_LANZADOR = "Use flechas derecha e izquierda para moverse por las categorías, flechas arriba y abajo para seleccionar item, enter para activarlo o escape para salir"
AYUDA_NOTAS = (
	"Use flechas derecha e izquierda para moverse por las categorías, flechas arriba y abajo para seleccionar item, "
	"F1 para escuchar el contenido de la nota, F2 para copiar al portapapeles, F3 para pegar en el foco o escape para salir"
)


class _EstadoModulo:
	def __init__(self) -> None:
		self.catIndex = 0
		self.itemIndex = 0
		self.catTotal = 0
		self.primeraVez = True


class MenuVirtual:
	"""Estado y órdenes de los menús virtuales."""

	def __init__(self, decir: Callable[[str], None] | None = None) -> None:
		self.decir = decir or sistema.mensaje
		self.pitido = sistema.pitido
		self.ejecutarAccion = lambda elem: sistema.ejecutar(elem)
		self.pegar = lambda texto: sistema.pegarEnFoco(texto)
		self.copiar = sistema.copiarAlPortapapeles
		self.activo = False
		self.modulo = datos.LANZADOR
		self.estados = {datos.LANZADOR: _EstadoModulo(), datos.NOTAS: _EstadoModulo()}
		self.categorias: list[str] = []
		self.elementos: list[list] = []

	# ------------------------------------------------------------------ utilidades
	@property
	def est(self) -> _EstadoModulo:
		return self.estados[self.modulo]

	@property
	def base(self) -> datos.BaseDatos:
		return datos.BaseDatos(self.modulo)

	@property
	def esNotas(self) -> bool:
		return self.modulo == datos.NOTAS

	def _leerCategorias(self) -> None:
		b = self.base
		b.comprobar()
		self.categorias = b.nombresCategorias()

	def _leerElementos(self, indice: int) -> None:
		if not self.categorias:
			self.elementos = []
			return
		if indice > len(self.categorias) - 1:
			indice = 0
		self.elementos = self.base.elementos(indice)

	def ayuda(self) -> None:
		self.decir(AYUDA_NOTAS if self.esNotas else AYUDA_LANZADOR)

	# ------------------------------------------------------------------ activar / salir
	def activar(self, modulo: str) -> bool:
		"""Activa el menú de ``modulo``. Devuelve ``True`` si queda activo."""
		if self.activo:
			# La orden pulsada dos veces con el menú abierto lo cierra.
			self.salir()
			return False
		if estado.ventanaAbierta:
			self.decir(estado.MSG_INSTANCIA)
			return False
		self.modulo = modulo
		self._leerCategorias()
		est = self.est
		if not self.categorias:
			self.decir("No hay categorías")
			return False
		if est.catTotal != len(self.categorias):
			est.catIndex = 0
			est.itemIndex = -1
		if est.catIndex > len(self.categorias) - 1:
			est.catIndex = 0
			est.itemIndex = -1
		estado.ventanaAbierta = True
		self.activo = True
		self.decir("Menú activado")
		if est.primeraVez:
			self.ayuda()
			est.primeraVez = False
			est.catIndex = 0
			est.itemIndex = -1
		self._leerElementos(est.catIndex)
		est.catTotal = len(self.categorias)
		self.decir(self.categorias[est.catIndex])
		return True

	def terminar(self) -> None:
		"""Desactiva el menú y devuelve el teclado a la normalidad."""
		if self.activo:
			self.est.catTotal = len(self.categorias)
		self.activo = False
		estado.ventanaAbierta = False

	def salir(self) -> None:
		self.decir("Saliendo del menú")
		self.terminar()

	# ------------------------------------------------------------------ categorías
	def siguienteCategoria(self) -> None:
		est = self.est
		est.catIndex = est.catIndex + 1 if est.catIndex < len(self.categorias) - 1 else 0
		self._leerElementos(est.catIndex)
		self.decir(self.categorias[est.catIndex])
		est.itemIndex = -1

	def anteriorCategoria(self) -> None:
		est = self.est
		est.catIndex = est.catIndex - 1 if est.catIndex > 0 else len(self.categorias) - 1
		self._leerElementos(est.catIndex)
		self.decir(self.categorias[est.catIndex])
		est.itemIndex = -1

	def saltarACategoria(self, letra: str) -> None:
		"""Va a la siguiente categoría que empieza por ``letra``."""
		est = self.est
		letra = letra.lower()
		n = len(self.categorias)
		for paso in range(1, n):
			i = (est.catIndex + paso) % n
			if self.categorias[i][:1].lower() == letra:
				est.catIndex = i
				self._leerElementos(i)
				self.decir(self.categorias[i])
				est.itemIndex = -1
				return
		if self.categorias and self.categorias[est.catIndex][:1].lower() == letra:
			self.decir(self.categorias[est.catIndex])
		else:
			self.pitido(200, 30)

	# ------------------------------------------------------------------ elementos
	def _sinElementos(self) -> None:
		self.decir("Sin notas" if self.esNotas else "Sin acción")

	def siguienteElemento(self) -> None:
		est = self.est
		if not self.elementos:
			self._sinElementos()
			return
		est.itemIndex = est.itemIndex + 1 if est.itemIndex < len(self.elementos) - 1 else 0
		self.decir(self.elementos[est.itemIndex][1])

	def anteriorElemento(self) -> None:
		est = self.est
		if not self.elementos:
			self._sinElementos()
			return
		est.itemIndex = est.itemIndex - 1 if est.itemIndex > 0 else len(self.elementos) - 1
		self.decir(self.elementos[est.itemIndex][1])

	def _elementoActual(self) -> list | None:
		"""Elemento elegido, o ``None`` (y se avisa) si no hay ninguno."""
		est = self.est
		if est.itemIndex < 0:
			self.ayuda()
			return None
		if not self.elementos:
			self.decir("Esta categoría no tiene notas" if self.esNotas else "Esta categoría no tiene acciones")
			return None
		if est.itemIndex > len(self.elementos) - 1:
			est.itemIndex = 0
		return self.elementos[est.itemIndex]

	# ------------------------------------------------------------------ lanzador
	def ejecutar(self) -> None:
		elem = self._elementoActual()
		if elem is None:
			return
		self.decir("Ejecutando acción")
		self.salir()
		if sistema.rutaNoEncontrada(elem):
			self.decir(sistema.mensajeRutaNoEncontrada(elem, False))
			return
		self.ejecutarAccion(elem)

	# ------------------------------------------------------------------ notas
	def verNota(self) -> None:
		elem = self._elementoActual()
		if elem is not None:
			self.decir(elem[2])

	def copiarNota(self) -> None:
		elem = self._elementoActual()
		if elem is None:
			return
		if self.copiar(elem[2]):
			self.decir("Se ha copiado la nota {} al portapapeles".format(elem[1]))
		else:
			self.decir("No se pudo copiar la nota {} al portapapeles".format(elem[1]))
		self.salir()

	def pegarNota(self) -> None:
		elem = self._elementoActual()
		if elem is None:
			return
		self.salir()
		self.pegar(elem[2])

	# ------------------------------------------------------------------ teclas
	def accionParaTecla(self, tecla: str) -> Callable[[], None]:
		"""Función que atiende ``tecla`` (nombre normalizado, p. ej. ``uparrow``)."""
		comunes = {
			"rightarrow": self.siguienteCategoria,
			"leftarrow": self.anteriorCategoria,
			"downarrow": self.siguienteElemento,
			"uparrow": self.anteriorElemento,
			"escape": self.salir,
		}
		if tecla in comunes:
			return comunes[tecla]
		if self.esNotas:
			propias = {"f1": self.verNota, "f2": self.copiarNota, "f3": self.pegarNota}
		else:
			propias = {"enter": self.ejecutar, "numpadenter": self.ejecutar}
		if tecla in propias:
			return propias[tecla]
		if len(tecla) == 1 and tecla.isalnum():
			return lambda: self.saltarACategoria(tecla)
		return self.ayuda
