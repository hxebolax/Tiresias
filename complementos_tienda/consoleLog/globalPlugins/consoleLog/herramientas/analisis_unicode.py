"""Análisis de texto Unicode: dirección (RTL/LTR), emoji, formato ANSI y ancho en columnas.

Da acceso a los ayudantes de texto bidireccional y de emoji del procesador de
texto, que el original incluía pero no mostraba en ningún menú.
"""

from __future__ import annotations

from ..procesador_texto import ProcesadorTexto
from . import HerramientaBase, MetadatosHerramienta


class HerramientaAnalisisUnicode(HerramientaBase):
	METADATOS = MetadatosHerramienta(
		nombre="Análisis de texto Unicode",
		version="1.0.0",
		descripcion="Dirección del texto, emoji, formato ANSI y ancho de visualización",
		autor="Héctor J. Benítez Corredera",
		categoria="analisis",
	)

	def ejecutar(self, **kwargs):
		return ProcesadorTexto().obtener_info_texto(self.texto_de(kwargs))
