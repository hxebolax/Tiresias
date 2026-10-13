"""«Automático»: detecta la línea braille conectada y usa su controlador.

Mientras no hay ninguna línea, este controlador ocupa su lugar con cero
celdas y la detección sigue en segundo plano. Al encontrar una, la instala
en el gestor braille; si después se desconecta, se vuelve aquí.
"""

from __future__ import annotations

from ... import queue_handler
from ...i18n import _
from ...log import getLogger
from .. import BrailleDisplayDriver as _Base
from .base import HardwareDriver
from .detect import Detector

log = getLogger("braille.auto")


class AutoDetectDriver(_Base):
	name = "auto"
	description = _("Automático")
	numCells = 0
	isHardware = False
	configName = "auto"

	@classmethod
	def check(cls) -> bool:
		return True

	def __init__(self) -> None:
		super().__init__()
		self.numCells = 0
		self._terminated = False
		self._detector = Detector(self._onFound)
		self._detector.start()
		log.debug("Detección automática de líneas braille iniciada")

	def rescan(self) -> None:
		self._detector.rescan()

	def _onFound(self, driver: HardwareDriver) -> None:
		# Hilo del detector.
		queue_handler.queueFunction(self._install, driver)

	def _install(self, driver: HardwareDriver) -> None:
		from .. import handler

		if self._terminated or handler.display is not self:
			driver.terminate()
			return
		driver.configName = "auto"
		if handler.setDisplay(driver.name, persist=False, instance=driver):
			driver._activate()
		else:
			driver.terminate()

	def display(self, cells: list[int]) -> None:
		pass

	def terminate(self) -> None:
		self._terminated = True
		self._detector.stop()


BrailleDisplayDriver = AutoDetectDriver
