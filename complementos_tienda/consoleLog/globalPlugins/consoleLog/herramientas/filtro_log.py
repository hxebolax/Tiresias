"""Filtro de errores y advertencias: deja solo las líneas relevantes."""

from __future__ import annotations

import re

from . import HerramientaBase, MetadatosHerramienta

PATRON_ERROR = re.compile(r"error|fault|fail|exception|critical|fatal", re.IGNORECASE)
PATRON_AVISO = re.compile(r"warning|warn|alert", re.IGNORECASE)


def filtrar_log(texto: str) -> list[str]:
	return [linea.strip() for linea in (texto or "").splitlines() if PATRON_ERROR.search(linea) or PATRON_AVISO.search(linea)]


class HerramientaFiltroLog(HerramientaBase):
	METADATOS = MetadatosHerramienta(
		nombre="Filtro de errores y advertencias",
		version="1.0.0",
		descripcion="Filtra el contenido para mostrar solo líneas con errores o advertencias",
		autor="Héctor J. Benítez Corredera",
		categoria="analisis",
	)

	def ejecutar(self, **kwargs):
		return filtrar_log(self.texto_de(kwargs))
