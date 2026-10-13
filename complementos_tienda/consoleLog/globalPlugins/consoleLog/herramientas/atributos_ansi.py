"""Atributos ANSI: colores y estilos presentes en el texto de la consola."""

from __future__ import annotations

from ..procesador_texto import AnalizadorANSI
from . import HerramientaBase, MetadatosHerramienta


def tramos_con_formato(linea: str, analizador: AnalizadorANSI | None = None) -> list[tuple[str, str]]:
	"""(texto, descripción) de cada tramo de la línea que tiene formato distinto del normal.

	El estado se arrastra entre líneas si se pasa el mismo ``analizador``.
	"""
	analizador = analizador or AnalizadorANSI()
	tramos: list[tuple[str, str]] = []
	pos = 0
	secuencias = list(AnalizadorANSI._PATRON_ANSI.finditer(linea))
	for i, m in enumerate(secuencias + [None]):
		fin = m.start() if m is not None else len(linea)
		texto = linea[pos:fin]
		if texto.strip():
			descripcion = analizador.formatear_atributos()
			if descripcion != "atributos por defecto":
				tramos.append((texto.strip(), descripcion))
		if m is None:
			break
		analizador.analizar(m.group(0))
		pos = m.end()
	return tramos


def analizar_por_lineas(texto: str) -> list[tuple[int, str]]:
	resultados = []
	analizador = AnalizadorANSI()
	for numero, linea in enumerate(texto.splitlines(), 1):
		tramos = tramos_con_formato(linea, analizador)
		if tramos:
			resultados.append((numero, "; ".join("«{}»: {}".format(t, d) for t, d in tramos)))
	return resultados


def informe_ansi(texto: str) -> str:
	if not texto:
		return "No hay texto para analizar."
	if "\x1b[" not in texto:
		return (
			"No se detectaron secuencias de formato ANSI en el texto.\n\n"
			"Nota: la mayoría de las terminales entregan el texto ya sin colores; "
			"las secuencias solo aparecen si se desactiva «Limpiar los códigos ANSI» "
			"y la terminal las expone."
		)
	resultados = analizar_por_lineas(texto)
	if not resultados:
		return "No se encontraron atributos de formato significativos."
	partes = [
		"=== Informe de atributos ANSI ===",
		"Líneas analizadas: {}".format(len(texto.splitlines())),
		"Secciones con formato: {}".format(len(resultados)),
		"",
	]
	partes += ["Línea {}: {}".format(n, d) for n, d in resultados[:50]]
	if len(resultados) > 50:
		partes.append("... y {} secciones más".format(len(resultados) - 50))
	partes += ["", "=== Texto sin formato ANSI ===", AnalizadorANSI.limpiar_ansi(texto)]
	return "\n".join(partes)


class HerramientaAtributosANSI(HerramientaBase):
	METADATOS = MetadatosHerramienta(
		nombre="Atributos de texto (ANSI)",
		version="1.0.0",
		descripcion="Analiza colores y formato ANSI del contenido de consola",
		autor="Héctor J. Benítez Corredera",
		categoria="analisis",
	)

	def ejecutar(self, **kwargs):
		return informe_ansi(self.texto_de(kwargs))
