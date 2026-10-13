"""Protección de la voz frente a ráfagas de salida de las consolas.

El original instalaba en NVDA una versión limitada del cambio oficial de NVDA
(PR #20177) para que una ráfaga de salida no bloqueara el lector. Tiresias no
se bloquea con las ráfagas (la voz es asíncrona, agrupa los cambios de la
consola y ya lee como mucho ``terminal.maxLinesPerUpdate`` líneas), pero una
salida continua sí puede **saturar la voz**: se encolan lote tras lote y lo que
se oye va cada vez más retrasado respecto a la pantalla.

Esta protección conserva la intención del original, adaptada a Tiresias:

- de cada ráfaga se leen como mucho las 100 líneas más recientes (o el
  máximo de Tiresias si es menor);
- se entregan a la voz en lotes de cinco líneas, y el siguiente lote solo se
  encola cuando la voz ha terminado el anterior;
- una ráfaga nueva sustituye a lo que quedara pendiente de la anterior, así
  lo que se oye corresponde siempre a lo más reciente;
- al callar la voz (Control) se descarta también lo pendiente.

Se instala envolviendo ``Terminal._speakNewText`` de Tiresias y se desinstala
por completo al desactivar la opción o descargar el complemento. La captura
completa sigue en el visor: el límite solo afecta a la lectura automática.
"""

from __future__ import annotations

import threading

from tiresias.log import getLogger

log = getLogger("consoleLog")


class ProtectorRafagas:
	MAX_LINEAS = 100
	LOTE = 5

	def __init__(self) -> None:
		self._activo = False
		self._original = None
		self._clase = None
		self._generacion = 0
		self._pendientes: list = []
		self._objeto = None
		self._cerrojo = threading.Lock()

	@property
	def activo(self) -> bool:
		return self._activo

	def maxLineas(self) -> int:
		try:
			from tiresias.config import conf

			nativo = int(conf["terminal"]["maxLinesPerUpdate"])
			if nativo > 0:
				return min(self.MAX_LINEAS, nativo)
		except Exception:
			pass
		return self.MAX_LINEAS

	def instalar(self) -> bool:
		if self._activo:
			return True
		try:
			from tiresias.objects import terminal
			from tiresias.speech import api as speechApi
		except Exception:
			log.exception("consoleLog: no se pudo comprobar la protección de ráfagas")
			return False
		clase = getattr(terminal, "Terminal", None)
		original = getattr(clase, "_speakNewText", None) if clase is not None else None
		if original is None:
			log.warning("consoleLog: esta versión de Tiresias no permite instalar la protección de ráfagas")
			return False
		protector = self

		def speakNewText(obj, added):
			protector._anunciar(obj, added)

		speakNewText._consoleLogProtector = True  # type: ignore[attr-defined]
		self._clase = clase
		self._original = original
		clase._speakNewText = speakNewText
		speechApi.pre_speechCanceled.register(self.cancelar)
		self._activo = True
		log.info("consoleLog: protección de la voz frente a ráfagas activada")
		return True

	def desinstalar(self) -> None:
		if not self._activo:
			return
		self.cancelar()
		try:
			from tiresias.speech import api as speechApi

			speechApi.pre_speechCanceled.unregister(self.cancelar)
		except Exception:
			pass
		try:
			if getattr(getattr(self._clase, "_speakNewText", None), "_consoleLogProtector", False):
				self._clase._speakNewText = self._original
		except Exception:
			log.exception("consoleLog: no se pudo retirar la protección de ráfagas")
		self._activo = False
		self._clase = None
		self._original = None

	# --------------------------------------------------------------- reparto
	def dividir(self, lineas: list[str]) -> list[list[str]]:
		"""Últimas líneas de la ráfaga, en lotes."""
		lineas = [linea for linea in (lineas or []) if linea is not None]
		maximo = self.maxLineas()
		if len(lineas) > maximo:
			lineas = lineas[-maximo:]
		return [lineas[i:i + self.LOTE] for i in range(0, len(lineas), self.LOTE)]

	def _anunciar(self, obj, added) -> None:
		lotes = self.dividir(list(added or []))
		with self._cerrojo:
			# Una ráfaga nueva sustituye a lo pendiente de la anterior.
			self._generacion += 1
			generacion = self._generacion
			self._pendientes = lotes[1:]
			self._objeto = obj
		if not lotes:
			return
		self._llamarOriginal(obj, lotes[0])
		if len(lotes) > 1:
			self._programar(generacion)

	def _llamarOriginal(self, obj, lote: list[str]) -> None:
		original = self._original
		if original is None:
			return
		try:
			original(obj, lote)
		except Exception:
			log.exception("consoleLog: error leyendo un lote de la consola")

	def _programar(self, generacion: int) -> None:
		try:
			from tiresias.speech import api as speechApi

			speechApi.whenDoneSpeaking(lambda: self._siguiente(generacion))
		except Exception:
			from tiresias import queue_handler

			queue_handler.callLater(200, self._siguiente, generacion)

	def _siguiente(self, generacion: int) -> None:
		with self._cerrojo:
			if generacion != self._generacion or not self._pendientes:
				return
			lote = self._pendientes.pop(0)
			obj = self._objeto
			quedan = bool(self._pendientes)
		self._llamarOriginal(obj, lote)
		if quedan:
			self._programar(generacion)

	def cancelar(self) -> None:
		"""Descarta los lotes pendientes (al callar la voz o con una ráfaga nueva)."""
		with self._cerrojo:
			self._generacion += 1
			self._pendientes = []
			self._objeto = None

	@property
	def pendientes(self) -> int:
		with self._cerrojo:
			return len(self._pendientes)
