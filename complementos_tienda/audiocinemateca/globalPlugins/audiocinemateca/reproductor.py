"""Reproductor de audio del complemento, sobre BASS (``bass.py``).

Reproduce direcciones de Internet (con la cabecera de autenticación de la
cuenta) y archivos descargados, con volumen, velocidad, avance, retroceso,
posición, ecualizador de 5 bandas y elección del dispositivo de salida.
Todas sus operaciones se pueden llamar desde cualquier hilo.
"""

from __future__ import annotations

import threading

from . import bass

DETENIDO = 0
REPRODUCIENDO = 1
PAUSADO = 2


def formatoTiempo(segundos: float) -> str:
	"""``HH:MM:SS`` o ``MM:SS``."""
	try:
		segundos = int(max(0, segundos))
	except (TypeError, ValueError):
		segundos = 0
	horas, resto = divmod(segundos, 3600)
	minutos, segs = divmod(resto, 60)
	if horas:
		return f"{horas:02d}:{minutos:02d}:{segs:02d}"
	return f"{minutos:02d}:{segs:02d}"


class Reproductor:
	DETENIDO = DETENIDO
	REPRODUCIENDO = REPRODUCIENDO
	PAUSADO = PAUSADO

	def __init__(self, dispositivo: str = "", numeroDispositivo: int | None = None) -> None:
		self._lock = threading.RLock()
		self._flujo: bass.Flujo | None = None
		self._url = ""
		self.titulo = ""
		self.idContenido = ""
		self.categoria = ""
		self._volumen = 50
		self._velocidad = 1.0
		self._frecuenciaOriginal = 0.0
		self._efectos: list[int] = []
		self._nombreDispositivo = dispositivo or ""
		self._numero = -1
		self.disponible = False
		self.error = ""
		self._iniciar(numeroDispositivo)

	# -------------------------------------------------- salida
	def _iniciar(self, numero: int | None = None) -> None:
		try:
			bass.cargar()
			if numero is None:
				numero = self._numeroPorNombre(self._nombreDispositivo)
			try:
				self._numero = bass.iniciar(numero)
			except bass.BassError:
				if numero == -1:
					raise
				# El dispositivo guardado ya no existe: se usa el predeterminado.
				self._numero = bass.iniciar(-1)
			self.disponible = True
			self.error = ""
		except Exception as e:
			self.disponible = False
			self.error = str(e)

	@staticmethod
	def _numeroPorNombre(nombre: str) -> int:
		if not nombre:
			return -1
		try:
			for numero, n, _pred in bass.dispositivos():
				if n == nombre:
					return numero
		except Exception:
			pass
		return -1

	def obtenerDispositivos(self) -> list[str]:
		"""Nombres de los dispositivos de salida disponibles."""
		try:
			return [n for _num, n, _p in bass.dispositivos()]
		except Exception:
			return []

	def setDispositivo(self, nombre: str) -> bool:
		"""Cambia el dispositivo de salida (``""`` = predeterminado de Windows)."""
		with self._lock:
			if not self.disponible:
				return False
			numero = self._numeroPorNombre(nombre)
			try:
				nuevo = bass.iniciar(numero)
			except bass.BassError:
				return False
			if self._flujo is not None:
				try:
					self._flujo.setDispositivo(nuevo)
				except bass.BassError:
					pass
			self._numero = nuevo
			self._nombreDispositivo = nombre or ""
			return True

	@property
	def url(self) -> str:
		return self._url

	# -------------------------------------------------- carga
	def _preparar(self, crear) -> bool:
		with self._lock:
			self.detener()
			if not self.disponible:
				self._iniciar()
				if not self.disponible:
					return False
			bass.seleccionar(self._numero)
			try:
				self._flujo = crear()
			except Exception as e:
				self.error = str(e)
				self._flujo = None
				return False
			try:
				self._frecuenciaOriginal = float(self._flujo.info().freq)
			except Exception:
				self._frecuenciaOriginal = 0.0
			self._efectos = []
			self._aplicarVolumen()
			self._aplicarVelocidad()
			return True

	def cargarUrl(self, url: str, cabeceras: dict[str, str] | None = None) -> bool:
		"""Prepara una dirección de Internet (no empieza a sonar)."""
		ok = self._preparar(lambda: bass.Flujo.desdeUrl(url, cabeceras))
		if ok:
			self._url = url
		return ok

	def cargarArchivo(self, ruta: str) -> bool:
		"""Prepara un archivo local (no empieza a sonar)."""
		ok = self._preparar(lambda: bass.Flujo.desdeArchivo(ruta))
		if ok:
			self._url = ruta
		return ok

	# -------------------------------------------------- control
	def reproducir(self) -> None:
		with self._lock:
			if self._flujo is not None:
				try:
					self._flujo.reproducir()
				except bass.BassError as e:
					self.error = str(e)

	def pausar(self) -> None:
		with self._lock:
			if self._flujo is not None:
				try:
					self._flujo.pausar()
				except bass.BassError:
					pass

	def reproducirPausar(self) -> int:
		with self._lock:
			estado = self.estado()
			if estado == REPRODUCIENDO:
				self.pausar()
			elif estado == PAUSADO:
				self.reproducir()
			return self.estado()

	def detener(self) -> None:
		with self._lock:
			if self._flujo is not None:
				try:
					self._flujo.detener()
					self._flujo.liberar()
				except Exception:
					pass
			self._flujo = None
			self._efectos = []
			self._url = ""
			self.titulo = ""
			self.idContenido = ""
			self.categoria = ""

	def estado(self) -> int:
		with self._lock:
			if self._flujo is None:
				return DETENIDO
			try:
				act = self._flujo.actividad()
			except Exception:
				return DETENIDO
			if act in (bass.BASS_ACTIVE_PLAYING, bass.BASS_ACTIVE_STALLED):
				# «Atascado» es que espera datos de la red: sigue reproduciendo.
				return REPRODUCIENDO
			if act in (bass.BASS_ACTIVE_PAUSED, bass.BASS_ACTIVE_PAUSED_DEVICE):
				return PAUSADO
			return DETENIDO

	def estaActivo(self) -> bool:
		return self.estado() in (REPRODUCIENDO, PAUSADO)

	def tieneFlujo(self) -> bool:
		return self._flujo is not None

	# -------------------------------------------------- volumen y velocidad
	def setVolumen(self, valor: int) -> None:
		with self._lock:
			self._volumen = max(0, min(100, int(valor)))
			self._aplicarVolumen()

	def getVolumen(self) -> int:
		return self._volumen

	def _aplicarVolumen(self) -> None:
		if self._flujo is not None:
			try:
				self._flujo.setAtributo(bass.BASS_ATTRIB_VOL, self._volumen / 100.0)
			except bass.BassError:
				pass

	def setVelocidad(self, valor: float) -> None:
		"""Factor de velocidad (1.0 = normal); se cambia la frecuencia de muestreo."""
		with self._lock:
			self._velocidad = max(0.5, min(3.0, float(valor)))
			self._aplicarVelocidad()

	def getVelocidad(self) -> float:
		return self._velocidad

	def _aplicarVelocidad(self) -> None:
		if self._flujo is not None and self._frecuenciaOriginal > 0:
			try:
				self._flujo.setAtributo(bass.BASS_ATTRIB_FREQ, self._frecuenciaOriginal * self._velocidad)
			except bass.BassError:
				pass

	# -------------------------------------------------- posición
	def getPosicion(self) -> float:
		with self._lock:
			if self._flujo is None:
				return 0.0
			try:
				return self._flujo.posicion()
			except Exception:
				return 0.0

	def setPosicion(self, segundos: float) -> None:
		with self._lock:
			if self._flujo is None:
				return
			try:
				self._flujo.setPosicion(max(0.0, float(segundos)))
			except bass.BassError as e:
				self.error = str(e)

	def getDuracion(self) -> float:
		with self._lock:
			if self._flujo is None:
				return 0.0
			try:
				return self._flujo.duracion()
			except Exception:
				return 0.0

	def adelantar(self, segundos: float) -> None:
		with self._lock:
			if self._flujo is None:
				return
			nueva = self.getPosicion() + segundos
			duracion = self.getDuracion()
			if duracion > 0 and nueva >= duracion:
				# BASS no admite colocarse justo en el final: se va a una décima antes.
				nueva = max(0.0, duracion - 0.1)
			self.setPosicion(nueva)

	def atrasar(self, segundos: float) -> None:
		with self._lock:
			if self._flujo is None:
				return
			self.setPosicion(max(0.0, self.getPosicion() - segundos))

	formatoTiempo = staticmethod(formatoTiempo)

	# -------------------------------------------------- ecualizador
	def aplicarEcualizador(self, bandas: list[tuple[float, float]], anchoBanda: float = 12.0) -> None:
		"""Pone una banda paramétrica por cada ``(frecuencia, ganancia)``."""
		with self._lock:
			if self._flujo is None:
				return
			self.limpiarEcualizador()
			for frecuencia, ganancia in bandas:
				f = float(max(80, min(16000, frecuencia)))
				g = float(max(-15, min(15, ganancia)))
				try:
					self._efectos.append(self._flujo.ponerEcualizador(f, anchoBanda, g))
				except bass.BassError as e:
					self.error = str(e)

	def limpiarEcualizador(self) -> None:
		with self._lock:
			if self._flujo is not None:
				for fx in self._efectos:
					try:
						self._flujo.quitarEfecto(fx)
					except Exception:
						pass
			self._efectos = []

	def numeroEfectos(self) -> int:
		return len(self._efectos)

	# -------------------------------------------------- cierre
	def liberar(self) -> None:
		"""Detiene lo que suene y libera la salida de audio (la DLL es solo de este complemento)."""
		with self._lock:
			self.detener()
			if self.disponible:
				bass.liberarTodo()
				self.disponible = False
