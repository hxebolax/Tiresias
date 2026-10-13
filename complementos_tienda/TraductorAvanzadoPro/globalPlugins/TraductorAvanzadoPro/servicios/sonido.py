"""Sonidos del complemento (abrir y cerrar la capa de órdenes).

Se reproducen con el reproductor de audio de Tiresias (respetan el volumen de
los sonidos de Tiresias y el dispositivo de salida) y, además, con el volumen
propio del complemento (opción «Volumen de los sonidos»). Si el usuario pone
un ``.wav`` con el mismo nombre en ``sonidos`` dentro de la carpeta de datos
del complemento, se usa ese.
"""

from __future__ import annotations

import os
import threading
import wave
from typing import TYPE_CHECKING

from tiresias.log import getLogger

if TYPE_CHECKING:
	from ..nucleo.configuracion import GestorConfiguracion

log = getLogger("TraductorAvanzadoPro")


class GestorSonidos:
	SONIDOS = {
		"abrir": "open.wav",
		"cerrar": "close.wav",
		"traduciendo": "translating.wav",
		"completado": "complete.wav",
		"error": "error.wav",
		"notificacion": "notification.wav",
	}

	def __init__(self, ruta_sonidos: str, configuracion: "GestorConfiguracion") -> None:
		self.ruta_sonidos = ruta_sonidos
		self.configuracion = configuracion
		self.ruta_usuario = os.path.join(getattr(configuracion, "ruta_config", "") or "", "sonidos")
		self._reproductores: dict[tuple[int, int], object] = {}
		self._bloqueo = threading.Lock()
		self._datos: dict[str, tuple[float, bytes, int, int]] = {}

	def _ruta(self, nombre_sonido: str) -> str | None:
		archivo = self.SONIDOS.get(nombre_sonido, f"{nombre_sonido}.wav")
		for carpeta in (self.ruta_usuario, self.ruta_sonidos):
			ruta = os.path.join(carpeta, archivo)
			if carpeta and os.path.isfile(ruta):
				return ruta
		return None

	def _leer(self, ruta: str) -> tuple[bytes, int, int]:
		mtime = os.path.getmtime(ruta)
		guardado = self._datos.get(ruta)
		if guardado and guardado[0] == mtime:
			return guardado[1], guardado[2], guardado[3]
		with wave.open(ruta, "rb") as w:
			if w.getsampwidth() != 2:
				raise ValueError("Solo se admiten WAV de 16 bits")
			datos = (w.readframes(w.getnframes()), w.getframerate(), w.getnchannels())
		self._datos[ruta] = (mtime, *datos)
		return datos

	def volumen(self) -> float:
		"""Volumen efectivo (0-1): el de los sonidos de Tiresias por el del complemento."""
		try:
			propio = max(0, min(100, int(self.configuracion.config.volumen_sonido))) / 100.0
		except Exception:
			propio = 0.5
		try:
			from tiresias.audio import tones

			general = tones._soundVolume()
		except Exception:
			general = 1.0
		return propio * general

	def reproducir(self, nombre_sonido: str) -> bool:
		if not self.configuracion.sonidos_habilitados:
			return False
		ruta = self._ruta(nombre_sonido)
		if not ruta:
			log.debug("Sonido no encontrado: %s", nombre_sonido)
			return False
		try:
			from tiresias.audio import tones
			from tiresias.audio.wave_player import WavePlayer

			if len(tones.pre_playSound):
				tones.pre_playSound.notify(name="", fileName=ruta)
			vol = self.volumen()
			if vol <= 0:
				return False
			datos, frecuencia, canales = self._leer(ruta)
			with self._bloqueo:
				clave = (frecuencia, canales)
				rep = self._reproductores.get(clave)
				if rep is None:
					rep = self._reproductores[clave] = WavePlayer(frecuencia, canales, name=f"traductor{frecuencia}", keepAwake=False)
			rep.stop()
			rep.volume = vol
			rep.feed(datos)
			return True
		except Exception:
			log.debug("Error reproduciendo el sonido %s", nombre_sonido, exc_info=True)
			return False

	def listar_sonidos(self) -> list[str]:
		sonidos = set()
		for carpeta in (self.ruta_sonidos, self.ruta_usuario):
			try:
				sonidos.update(a[:-4] for a in os.listdir(carpeta) if a.lower().endswith(".wav"))
			except OSError:
				pass
		return sorted(sonidos)

	def existe_sonido(self, nombre_sonido: str) -> bool:
		return self._ruta(nombre_sonido) is not None

	def terminar(self) -> None:
		with self._bloqueo:
			for rep in self._reproductores.values():
				try:
					rep.terminate()
				except Exception:
					pass
			self._reproductores.clear()
