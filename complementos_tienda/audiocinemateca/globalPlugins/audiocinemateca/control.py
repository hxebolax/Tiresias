"""Lógica del complemento sin interfaz: gestores de datos, reproductor,
reproducción con reanudación, temporizador de sueño y avisos por voz.

La ventana principal, los diálogos y las órdenes globales usan una única
instancia de :class:`Controlador` (la crea el complemento global).
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from . import ajustes, almacen, catalogo, credenciales, descargas
from .reproductor import PAUSADO, REPRODUCIENDO, Reproductor, formatoTiempo

SIN_REPRODUCCION = "Sin nada en reproducción"


def hablar(mensaje: str, retardo: float = 0.0) -> None:
	"""Anuncia ``mensaje`` con la voz de Tiresias (seguro desde cualquier hilo).

	Con ``retardo`` (segundos) se espera un poco antes de hablar, para que el
	aviso no lo corte el anuncio del foco al abrirse o cerrarse una ventana.
	"""
	if not mensaje:
		return
	try:
		from tiresias import queue_handler, speech

		if retardo > 0:
			queue_handler.callLater(int(retardo * 1000), speech.speakMessage, mensaje)
		else:
			queue_handler.queueFunction(speech.speakMessage, mensaje)
	except Exception:
		pass


def informar(mensaje: str, retardo: float = 0.1) -> None:
	"""Mensaje informativo: solo se dice si los mensajes informativos están activados."""
	if ajustes.hablarActivo():
		hablar(mensaje, retardo)


class Controlador:
	def __init__(self, carpeta: str | None = None, avisar: Callable[[str], None] | None = None) -> None:
		self.carpeta = carpeta or ajustes.dirDatos()
		self.avisar = avisar or hablar
		credenciales.cargar()
		self.catalogo = catalogo.GestorCatalogo(self.carpeta)
		self.favoritos = almacen.GestorFavoritos(self.carpeta)
		self.visualizacion = almacen.GestorVisualizacion(self.carpeta)
		self.historial = almacen.GestorHistorial(self.carpeta)
		self.historialBusqueda = almacen.GestorHistorialBusqueda(self.carpeta)
		self.listas = almacen.GestorListas(self.carpeta)
		self.estadisticas = almacen.GestorEstadisticas(self.carpeta)
		self.descargas = descargas.GestorDescargas(self.carpeta, avisar=self.avisar)
		self._reproductor: Reproductor | None = None
		self._lockRepro = threading.RLock()
		#: Dirección limpia (sin credenciales) de lo que suena: clave de la marca de visualización.
		self.claveMarca = ""
		self._posicionInicio = 0.0
		self._timer: threading.Timer | None = None
		self._finTemporizador: float | None = None

	# -------------------------------------------------- reproductor
	@property
	def reproductor(self) -> Reproductor:
		with self._lockRepro:
			if self._reproductor is None:
				self._reproductor = Reproductor(ajustes.get("dispositivo"))
			return self._reproductor

	def reproductorCreado(self) -> bool:
		return self._reproductor is not None

	def hayReproduccion(self) -> bool:
		return self._reproductor is not None and self._reproductor.estaActivo()

	def cabecerasAutenticacion(self, url: str | None = None) -> dict[str, str]:
		"""Cabecera de autenticación; con ``url``, solo si es de la Audiocinemateca por https."""
		from .red import cabeceraAutenticacion, hostConfiable

		if not ajustes.hayCredenciales():
			return {}
		if url is not None and not hostConfiable(url):
			return {}
		return {"Authorization": cabeceraAutenticacion(ajustes.estado.usuario, ajustes.estado.contrasena)}

	def _aplicarAjustes(self) -> None:
		r = self.reproductor
		r.setVolumen(ajustes.get("volumen"))
		r.setVelocidad(ajustes.velocidadActual())
		if ajustes.get("ecualizadorActivo"):
			r.aplicarEcualizador(list(zip(ajustes.EQ_BANDAS, ajustes.get("ecualizadorValores"))), ajustes.EQ_ANCHO_BANDA)

	def aplicarEcualizadorActual(self) -> None:
		"""Pone o quita el ecualizador en lo que esté sonando según las opciones."""
		if not self.hayReproduccion():
			return
		if ajustes.get("ecualizadorActivo"):
			self.reproductor.aplicarEcualizador(list(zip(ajustes.EQ_BANDAS, ajustes.get("ecualizadorValores"))), ajustes.EQ_ANCHO_BANDA)
		else:
			self.reproductor.limpiarEcualizador()

	def guardarPosicionActual(self) -> None:
		"""Guarda la marca de visualización y suma el tiempo escuchado."""
		if not self.hayReproduccion():
			return
		posicion = self.reproductor.getPosicion()
		if self.claveMarca:
			self.visualizacion.guardarPosicion(self.claveMarca, posicion)
		self.estadisticas.acumularTiempo(max(0.0, posicion - self._posicionInicio))
		self._posicionInicio = posicion

	def prepararContenido(self, enlace: str, titulo: str = "", idContenido="", categoria: str = "") -> tuple[bool, float | None, str]:
		"""Carga un contenido del catálogo (el archivo descargado si existe).

		Puede tardar (conecta con el servidor): llamar desde un hilo propio.
		Devuelve ``(cargado, posición guardada o None, mensaje de error)``.
		"""
		url = catalogo.urlContenido(enlace)
		local = self.descargas.buscarDescargaLocal(url)
		return self._preparar(url, local, titulo, idContenido, categoria)

	def prepararArchivo(self, ruta: str, url: str = "", titulo: str = "") -> tuple[bool, float | None, str]:
		"""Carga un archivo descargado (reproducción sin conexión)."""
		return self._preparar(url or ruta, ruta, titulo, "", "")

	def _preparar(self, url: str, local: str | None, titulo: str, idContenido, categoria: str) -> tuple[bool, float | None, str]:
		with self._lockRepro:
			self.guardarPosicionActual()
			r = self.reproductor
			r.detener()
			if local:
				ok = r.cargarArchivo(local)
			else:
				ok = r.cargarUrl(url, self.cabecerasAutenticacion(url))
			if not ok:
				self.claveMarca = ""
				return False, None, r.error or "Error al cargar el contenido."
			self.claveMarca = url
			r.titulo = titulo
			r.idContenido = idContenido
			r.categoria = categoria
			self._aplicarAjustes()
			return True, self.visualizacion.obtenerPosicion(url), ""

	def comenzar(self, posicion: float | None = None) -> None:
		"""Empieza a sonar lo preparado (desde ``posicion`` si se indica) y lo anota."""
		r = self.reproductor
		r.reproducir()
		if posicion:
			r.setPosicion(posicion)
		self._posicionInicio = r.getPosicion()
		if r.idContenido and r.categoria:
			self.historial.registrar(r.idContenido, r.categoria, r.titulo, url=self.claveMarca)
			self.estadisticas.registrarReproduccion(r.idContenido, r.categoria, r.titulo)

	def detener(self) -> None:
		"""Detiene guardando la posición; cancela el temporizador de sueño si estaba activo."""
		self.guardarPosicionActual()
		if self._reproductor is not None:
			self._reproductor.detener()
		self.claveMarca = ""
		if ajustes.estado.temporizadorActivo:
			self.cancelarTemporizador()

	def reproducirPausar(self) -> int:
		return self.reproductor.reproducirPausar()

	# -------------------------------------------------- volumen, velocidad y saltos
	def cambiarVolumen(self, delta: int) -> int:
		nuevo = max(0, min(100, ajustes.get("volumen") + delta))
		ajustes.put("volumen", nuevo)
		self.reproductor.setVolumen(nuevo)
		return nuevo

	def ponerVolumen(self, valor: int) -> None:
		valor = max(0, min(100, int(valor)))
		ajustes.put("volumen", valor)
		if self._reproductor is not None:
			self._reproductor.setVolumen(valor)

	def cambiarVelocidad(self, delta: int) -> int:
		nuevo = max(0, min(len(ajustes.LISTA_VELOCIDAD) - 1, ajustes.get("velocidad") + delta))
		ajustes.put("velocidad", nuevo)
		self.reproductor.setVelocidad(float(ajustes.LISTA_VELOCIDAD[nuevo]))
		return nuevo

	def ponerVelocidad(self, indice: int) -> None:
		indice = max(0, min(len(ajustes.LISTA_VELOCIDAD) - 1, int(indice)))
		ajustes.put("velocidad", indice)
		if self._reproductor is not None:
			self._reproductor.setVelocidad(float(ajustes.LISTA_VELOCIDAD[indice]))

	def atrasar(self) -> None:
		self.reproductor.atrasar(ajustes.segundosAtrasar())

	def adelantar(self) -> None:
		self.reproductor.adelantar(ajustes.segundosAdelantar())

	def textoTiempos(self) -> tuple[str, str]:
		r = self.reproductor
		return formatoTiempo(r.getPosicion()), formatoTiempo(r.getDuracion())

	def textoRestante(self) -> str:
		r = self.reproductor
		return formatoTiempo(max(0.0, r.getDuracion() - r.getPosicion()))

	def estaSonando(self) -> bool:
		return self._reproductor is not None and self._reproductor.estado() == REPRODUCIENDO

	def estaPausado(self) -> bool:
		return self._reproductor is not None and self._reproductor.estado() == PAUSADO

	def setDispositivo(self, nombre: str) -> bool:
		ajustes.put("dispositivo", nombre or "")
		if self._reproductor is None:
			return True
		return self._reproductor.setDispositivo(nombre or "")

	# -------------------------------------------------- temporizador de sueño
	def iniciarTemporizador(self, minutos: int) -> None:
		self._pararTimer()
		ajustes.estado.temporizadorActivo = True
		ajustes.estado.temporizadorMinutos = int(minutos)
		self._finTemporizador = time.time() + minutos * 60
		self._timer = threading.Timer(minutos * 60, self._ejecutarTemporizador)
		self._timer.daemon = True
		self._timer.start()
		hablar(f"Temporizador de sueño activado: {minutos} minutos")

	def _pararTimer(self) -> None:
		if self._timer is not None:
			self._timer.cancel()
			self._timer = None

	def cancelarTemporizador(self) -> None:
		self._pararTimer()
		self._finTemporizador = None
		ajustes.estado.temporizadorActivo = False
		ajustes.estado.temporizadorMinutos = 0

	def segundosTemporizador(self) -> float:
		if not ajustes.estado.temporizadorActivo or self._finTemporizador is None:
			return 0.0
		return max(0.0, self._finTemporizador - time.time())

	def infoTemporizador(self) -> str:
		restante = self.segundosTemporizador()
		if restante <= 0:
			return "Temporizador de sueño no activo"
		minutos, segundos = int(restante // 60), int(restante % 60)
		if minutos > 0:
			return f"Temporizador de sueño: {minutos} minutos y {segundos} segundos restantes"
		return f"Temporizador de sueño: {segundos} segundos restantes"

	def _ejecutarTemporizador(self) -> None:
		self._timer = None
		self._finTemporizador = None
		ajustes.estado.temporizadorActivo = False
		ajustes.estado.temporizadorMinutos = 0
		if self.hayReproduccion():
			self.guardarPosicionActual()
			self.reproductor.detener()
			self.claveMarca = ""
			hablar("Temporizador de sueño: reproducción detenida")
		if self.alTerminarTemporizador is not None:
			try:
				self.alTerminarTemporizador()
			except Exception:
				pass

	#: Función a la que se avisa (desde el hilo del temporizador) al detener la reproducción.
	alTerminarTemporizador: Callable[[], None] | None = None

	# -------------------------------------------------- cierre
	def terminar(self) -> None:
		self.cancelarTemporizador()
		try:
			self.descargas.cancelarTodo()
		except Exception:
			pass
		if self._reproductor is not None:
			try:
				self.guardarPosicionActual()
			except Exception:
				pass
			self._reproductor.liberar()
			self._reproductor = None
