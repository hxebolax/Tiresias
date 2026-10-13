"""Traducción simultánea en segundo plano.

El filtro de voz de Tiresias (``filter_speechSequence``) se ejecuta en el hilo
del núcleo: si hiciera allí la petición de red, toda la voz se congelaría. Por
eso el filtro deja pasar el texto original al momento (o la traducción, si ya
está en la caché) y encola el texto aquí; cuando llega la traducción se habla
en el hilo del núcleo con prioridad «a continuación».
"""

from __future__ import annotations

import queue
import threading
from typing import TYPE_CHECKING, Any

from tiresias import queue_handler
from tiresias.log import getLogger

if TYPE_CHECKING:
	pass

log = getLogger("TraductorAvanzadoPro")


class TraductorAsync:
	#: Textos pendientes como máximo (si se acumulan más, se descartan los nuevos).
	MAXIMO_PENDIENTES = 100

	def __init__(self, plugin: Any) -> None:
		self.plugin = plugin
		self.cola: queue.Queue = queue.Queue()
		self.pendientes: set[str] = set()
		self.bloqueo = threading.Lock()
		self._detenido = False
		self._hilo: threading.Thread | None = None
		self._traducciones_desde_guardado = 0
		#: Cada cuántas traducciones se guarda la caché en disco.
		self._intervalo_guardado = 5

	def iniciar(self) -> None:
		if self._hilo is not None and self._hilo.is_alive():
			return
		self._detenido = False
		self._hilo = threading.Thread(target=self._bucle, name="TraductorAvanzadoPro-Async", daemon=True)
		self._hilo.start()

	def detener(self) -> None:
		self._detenido = True
		try:
			self.cola.put_nowait(None)
		except Exception:
			pass

	def esperar(self, timeout: float = 2.0) -> None:
		if self._hilo is not None:
			self._hilo.join(timeout)

	@staticmethod
	def _clave(texto: str, idioma_destino: str, servicio: str) -> str:
		return f"{servicio}|{idioma_destino}|{texto}"

	def encolar(self, texto: str, app: str | None = None) -> bool:
		"""Encola ``texto``; ``False`` si ya estaba pendiente o la cola está llena."""
		if self._detenido:
			return False
		config = self.plugin.configuracion
		clave = self._clave(texto, config.idioma_destino, config.servicio_activo)
		with self.bloqueo:
			if clave in self.pendientes or len(self.pendientes) >= self.MAXIMO_PENDIENTES:
				return False
			self.pendientes.add(clave)
		self.cola.put_nowait((texto, clave, app))
		return True

	def vaciar(self) -> None:
		"""Descarta lo pendiente (al desactivar la traducción simultánea)."""
		try:
			while True:
				elemento = self.cola.get_nowait()
				if elemento is None:
					self.cola.put_nowait(None)
					break
		except queue.Empty:
			pass
		with self.bloqueo:
			self.pendientes.clear()

	def _bucle(self) -> None:
		while True:
			elemento = self.cola.get()
			if elemento is None or self._detenido:
				break
			texto, clave, app = elemento
			try:
				self._procesar(texto, app)
			except Exception:
				log.exception("Error en el traductor asíncrono")
			finally:
				with self.bloqueo:
					self.pendientes.discard(clave)

	def _procesar(self, texto: str, app: str | None) -> None:
		if not texto or not texto.strip():
			return
		plugin = self.plugin
		if not plugin._traduccion_activa:
			return
		traduccion = plugin._traducir_texto_fondo(texto, app)
		if not traduccion or traduccion == texto or not plugin._traduccion_activa:
			return
		self._traducciones_desde_guardado += 1
		if self._traducciones_desde_guardado >= self._intervalo_guardado and plugin.configuracion.cache_habilitada:
			try:
				plugin.cache.guardar_todo()
				self._traducciones_desde_guardado = 0
			except Exception:
				log.exception("Error al guardar la caché")
		queue_handler.queueFunction(plugin._hablar_traduccion, traduccion)
