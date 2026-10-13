"""Conversor de marcas de tiempo Unix (segundos o milisegundos) a fecha y hora local."""

from __future__ import annotations

import datetime
import re

from . import HerramientaBase, MetadatosHerramienta

#: 10 dígitos (segundos, de 2001 a 2286) o 13 (milisegundos, de 2009 a 2128).
PATRON = re.compile(r"\b(1[0-9]{9}|[1-4][0-9]{12})\b")


def convertir_marcas(texto: str) -> list[str]:
	resultados = []
	vistos: set[str] = set()
	for valor in PATRON.findall(texto or ""):
		if valor in vistos:
			continue
		vistos.add(valor)
		try:
			ts = int(valor)
			if len(valor) == 13:
				ts = ts / 1000.0
			fecha = datetime.datetime.fromtimestamp(ts)
		except (OverflowError, OSError, ValueError):
			continue
		resultados.append("{} -> {}".format(valor, fecha.strftime("%d/%m/%Y %H:%M:%S")))
	return resultados


class HerramientaMarcasTiempo(HerramientaBase):
	METADATOS = MetadatosHerramienta(
		nombre="Conversor de marcas de tiempo",
		version="1.0.0",
		descripcion="Convierte números de marcas de tiempo Unix a fechas y horas legibles",
		autor="Héctor J. Benítez Corredera",
		categoria="analisis",
	)

	def ejecutar(self, **kwargs):
		return convertir_marcas(self.texto_de(kwargs))
