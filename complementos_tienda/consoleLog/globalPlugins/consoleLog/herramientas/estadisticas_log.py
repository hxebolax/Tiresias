"""Estadísticas del registro: tamaño, niveles, repeticiones y líneas destacadas."""

from __future__ import annotations

import re
from collections import Counter

from . import HerramientaBase, MetadatosHerramienta

NIVELES = {
	"ERROR": re.compile(r"\b(?:error|fatal|critical|exception|failed)\b", re.IGNORECASE),
	"WARNING": re.compile(r"\b(?:warn(?:ing)?|deprecated)\b", re.IGNORECASE),
	"INFO": re.compile(r"\binfo\b", re.IGNORECASE),
	"DEBUG": re.compile(r"\b(?:debug|trace)\b", re.IGNORECASE),
}


def _n(valor: int) -> str:
	return "{:,}".format(valor).replace(",", ".")


def estadisticas(texto: str) -> str:
	lineas = texto.splitlines()
	no_vacias = [linea for linea in lineas if linea.strip()]
	niveles: Counter = Counter()
	for linea in no_vacias:
		for nivel, patron in NIVELES.items():
			if patron.search(linea):
				niveles[nivel] += 1
				break
	repeticiones = Counter(linea.strip() for linea in no_vacias)
	repetidas = sum(c - 1 for c in repeticiones.values() if c > 1)
	mas_repetidas = [(c, linea) for linea, c in repeticiones.most_common(5) if c > 1]
	informe = [
		"Estadísticas del contenido",
		"",
		"Caracteres: {}".format(_n(len(texto))),
		"Líneas: {}".format(_n(len(lineas))),
		"Líneas no vacías: {}".format(_n(len(no_vacias))),
		"Palabras: {}".format(_n(len(re.findall(r"\S+", texto)))),
		"Líneas duplicadas: {}".format(_n(repetidas)),
		"",
		"Niveles detectados:",
	]
	informe += ["{}: {}".format(nivel, _n(niveles[nivel])) for nivel in ("ERROR", "WARNING", "INFO", "DEBUG")]
	if mas_repetidas:
		informe += ["", "Líneas más repetidas:"]
		for cantidad, linea in mas_repetidas:
			resumen = linea if len(linea) <= 160 else linea[:157] + "..."
			informe.append("{} veces: {}".format(cantidad, resumen))
	return "\n".join(informe)


class HerramientaEstadisticas(HerramientaBase):
	METADATOS = MetadatosHerramienta(
		nombre="Estadísticas del registro",
		version="1.0.0",
		descripcion="Resume tamaño, niveles, repeticiones y líneas destacadas",
		autor="Héctor J. Benítez Corredera",
		categoria="analisis",
	)

	def ejecutar(self, **kwargs):
		return estadisticas(self.texto_de(kwargs))
