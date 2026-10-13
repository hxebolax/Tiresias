"""Copiar salida: envía el documento (o la selección) al portapapeles."""

from __future__ import annotations

from tiresias.log import getLogger

from . import HerramientaBase, MetadatosHerramienta

log = getLogger("consoleLog")


def copiar(texto: str) -> bool:
	from tiresias import api

	if not texto:
		return False
	try:
		# Tiresias reproduce su sonido de copia.
		return bool(api.copyToClip(texto))
	except Exception:
		log.exception("consoleLog: error al copiar al portapapeles")
		return False


class HerramientaCopiarSalida(HerramientaBase):
	METADATOS = MetadatosHerramienta(
		nombre="Copiar salida al portapapeles",
		version="2.0.0",
		descripcion="Copia el contenido completo de la consola al portapapeles",
		autor="Héctor J. Benítez Corredera",
		categoria="portapapeles",
	)

	def ejecutar(self, **kwargs):
		return copiar(self.texto_de(kwargs))
