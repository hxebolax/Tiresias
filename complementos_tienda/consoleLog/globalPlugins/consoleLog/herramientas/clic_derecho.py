"""Clic derecho en la consola: pega el portapapeles y devuelve el puntero a su sitio.

En Console Host (y en muchas terminales) el clic derecho pega el
portapapeles. Se hace en el centro de la ventana de la consola y el puntero
del ratón vuelve después a donde estaba.
"""

from __future__ import annotations

import time

from tiresias.log import getLogger

from .. import avisos
from . import HerramientaBase, MetadatosHerramienta

log = getLogger("consoleLog")


def centro_ventana(rect: tuple[int, int, int, int]) -> tuple[int, int]:
	"""Centro de un rectángulo (x, y, ancho, alto)."""
	x, y, ancho, alto = rect
	return x + ancho // 2, y + alto // 2


def clic_derecho_en_ventana(hwnd: int) -> bool:
	from tiresias import mouse, winapi

	if not hwnd:
		return False
	try:
		cx, cy = centro_ventana(winapi.getWindowRect(hwnd))
		anterior = winapi.getCursorPos()
		mouse.click(cx, cy, "right")
		time.sleep(0.05)
		mouse.moveTo(*anterior)
		avisos.pitido(600, 200)
		return True
	except Exception:
		log.exception("consoleLog: error en el clic derecho")
		return False


class HerramientaClicDerecho(HerramientaBase):
	METADATOS = MetadatosHerramienta(
		nombre="Clic derecho en consola",
		version="2.0.0",
		descripcion="Permite pegar el portapapeles en consolas mediante clic derecho",
		autor="Héctor J. Benítez Corredera",
		categoria="acciones",
	)

	def ejecutar(self, **kwargs):
		destino = kwargs.get("destino")
		hwnd = int(getattr(destino, "hwnd", 0) or kwargs.get("hwnd") or 0)
		return clic_derecho_en_ventana(hwnd)
