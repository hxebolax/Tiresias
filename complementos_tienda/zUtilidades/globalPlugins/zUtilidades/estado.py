"""Estado compartido de zUtilidades durante la sesión y opciones.

- ``ventanaAbierta``: hay una ventana del complemento (o un menú virtual)
  abierta; no se permiten dos a la vez («Ya hay una instancia...»).
- Posición (categoría y elemento) y control con el foco de cada módulo: al
  volver a abrir la ventana se recuperan, solo durante la sesión.
"""

from __future__ import annotations

from . import datos

SECCION = "zUtilidades"
DEFECTOS = {
	"tituloCaptura": False,
	"urlCaptura": False,
}
#: Etiquetas de las opciones (las mismas que el original).
ETIQUETAS = (
	("tituloCaptura", "Capturar el título de la ventana en las notas rápidas (desde cualquier parte)"),
	("urlCaptura", "Anexar la URL del documento a las notas rápidas cuando se copia texto de una página web."),
)

MSG_INSTANCIA = "Ya hay una instancia de zUtilidades abierta.\n\nNo es posible tener dos instancias a la vez."

#: Hay una ventana (o un menú virtual) de zUtilidades abierta.
ventanaAbierta = False


class Sesion:
	"""Lo que se recuerda de un módulo mientras Tiresias está en marcha."""

	def __init__(self) -> None:
		self.reiniciar()

	def reiniciar(self) -> None:
		self.posicion = [0, 0]
		self.foco = "categorias"


sesiones = {datos.LANZADOR: Sesion(), datos.NOTAS: Sesion()}


def registrarOpciones() -> None:
	from tiresias.config import conf

	conf.registerDefaults(SECCION, DEFECTOS)


def opcion(clave: str) -> bool:
	try:
		from tiresias.config import conf

		return bool(conf[SECCION][clave])
	except Exception:
		return bool(DEFECTOS.get(clave, False))


def ponerOpcion(clave: str, valor: bool) -> None:
	from tiresias.config import conf

	conf[SECCION][clave] = bool(valor)
