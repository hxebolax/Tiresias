"""Convierte texto delimitado (CSV, TSV, punto y coma, barras) en columnas alineadas."""

from __future__ import annotations

import csv
import io

from . import HerramientaBase, MetadatosHerramienta


def alinear_tabla(texto: str) -> str:
	muestra = (texto or "")[:8192]
	if not muestra.strip():
		return "No hay contenido que alinear."
	try:
		dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\t|")
		filas = [fila for fila in csv.reader(io.StringIO(texto), dialecto) if fila]
	except (csv.Error, UnicodeError):
		return "No se pudo detectar una tabla delimitada válida."
	if not filas or max(len(fila) for fila in filas) < 2:
		return "El contenido no contiene al menos dos columnas."
	columnas = max(len(fila) for fila in filas)
	anchos = [min(80, max((len(fila[i].strip()) if i < len(fila) else 0) for fila in filas)) for i in range(columnas)]
	salida = []
	for fila in filas:
		celdas = [c.strip() for c in fila] + [""] * (columnas - len(fila))
		salida.append(" | ".join(celda[: anchos[i]].ljust(anchos[i]) for i, celda in enumerate(celdas)).rstrip())
	return "\n".join(salida)


class HerramientaTablaDelimitada(HerramientaBase):
	METADATOS = MetadatosHerramienta(
		nombre="Alinear tabla delimitada",
		version="1.0.0",
		descripcion="Detecta CSV, TSV, punto y coma o barras y alinea sus columnas",
		autor="Héctor J. Benítez Corredera",
		categoria="edición",
	)

	def ejecutar(self, **kwargs):
		return alinear_tabla(self.texto_de(kwargs))
