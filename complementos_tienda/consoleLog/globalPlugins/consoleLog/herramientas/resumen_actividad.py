"""Resumen de actividad: herramientas de desarrollo que aparecen en la consola."""

from __future__ import annotations

import re

from . import HerramientaBase, MetadatosHerramienta

HERRAMIENTAS = {
	"Git": r"\bgit\s+\w+",
	"Docker": r"\bdocker\s+\w+",
	"NPM/Node": r"\bnpm\s+\w+|\bnode\s+",
	"Python": r"\bpython\d*\s+|\bpip\s+",
	"Comandos de red": r"\bping\s+|\bipconfig\b|\bifconfig\b|\bnetstat\b",
	"Compiladores": r"\bgcc\b|\bg\+\+|\bjavac\b|\bdotnet\b",
	"Nube": r"\baws\s+|\baz\s+|\bgcloud\s+",
}


def resumir_actividad(texto: str) -> list[str]:
	resumen = [
		"Estadísticas generales:",
		"- Total de líneas: {}".format(len(texto.splitlines())),
		"- Total de palabras: {}".format(len(texto.split())),
		"",
		"Herramientas detectadas:",
	]
	encontrado = False
	for nombre, patron in HERRAMIENTAS.items():
		menciones = re.findall(patron, texto, re.IGNORECASE)
		if menciones:
			encontrado = True
			resumen.append("- {}: {} menciones".format(nombre, len(menciones)))
	if not encontrado:
		resumen.append("- No se detectaron herramientas específicas.")
	return resumen


class HerramientaResumenActividad(HerramientaBase):
	METADATOS = MetadatosHerramienta(
		nombre="Resumen de actividad",
		version="1.0.0",
		descripcion="Analiza el texto para identificar herramientas de desarrollo y dar estadísticas",
		autor="Héctor J. Benítez Corredera",
		categoria="analisis",
	)

	def ejecutar(self, **kwargs):
		texto = self.texto_de(kwargs)
		if not texto:
			return []
		return resumir_actividad(texto)
