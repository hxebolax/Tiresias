"""Analizador de indentación: estructura, cambios de nivel e inconsistencias."""

from __future__ import annotations

from ..procesador_texto import DetectorIndentacion
from . import HerramientaBase, MetadatosHerramienta

_detector = DetectorIndentacion()


def estadisticas_indentacion(lineas: list[str]) -> dict:
	con = maximo = espacios = tabs = 0
	for linea in lineas:
		if linea and linea[0] in (" ", "\t"):
			con += 1
			maximo = max(maximo, _detector.obtener_nivel_indentacion(linea))
			if linea[0] == " ":
				espacios += 1
			else:
				tabs += 1
	if espacios > tabs:
		tipo = "espacios"
	elif tabs > espacios:
		tipo = "tabulaciones"
	elif espacios and tabs:
		tipo = "mixto (espacios y tabulaciones)"
	else:
		tipo = "sin indentación"
	return {"con_indentacion": con, "nivel_maximo": maximo, "tipo_predominante": tipo, "usa_espacios": espacios, "usa_tabs": tabs}


def cambios_nivel(lineas: list[str]) -> list[tuple[int, int, int, str]]:
	cambios = []
	anterior = 0
	for i, linea in enumerate(lineas, 1):
		if not linea.strip():
			continue
		actual = _detector.obtener_nivel_indentacion(linea)
		if actual != anterior:
			cambios.append((i, anterior, actual, "→ aumento" if actual > anterior else "← disminución"))
			anterior = actual
	return cambios


def inconsistencias(lineas: list[str]) -> list[tuple[int, str]]:
	salida = []
	for i, linea in enumerate(lineas, 1):
		if not linea or linea[0] not in (" ", "\t"):
			continue
		sangria = linea[: len(linea) - len(linea.lstrip(" \t"))]
		if " " in sangria and "\t" in sangria:
			salida.append((i, "mezcla de espacios y tabulaciones"))
	return salida


def informe_indentacion(texto: str) -> str:
	if not texto:
		return "No hay texto para analizar."
	lineas = texto.splitlines()
	est = estadisticas_indentacion(lineas)
	informe = [
		"=== Informe de indentación ===",
		"Total de líneas: {}".format(len(lineas)),
		"Líneas con indentación: {}".format(est["con_indentacion"]),
		"Nivel máximo de indentación: {} espacios".format(est["nivel_maximo"]),
		"Tipo predominante: {}".format(est["tipo_predominante"]),
	]
	inc = inconsistencias(lineas)
	if inc:
		informe += ["", "Inconsistencias detectadas:"]
		informe += ["  Línea {}: {}".format(n, d) for n, d in inc[:20]]
		if len(inc) > 20:
			informe.append("  ... y {} más".format(len(inc) - 20))
	cam = cambios_nivel(lineas)
	if cam:
		informe += ["", "Cambios de nivel de indentación:"]
		informe += ["  Línea {}: {} → {} ({})".format(n, a, b, d) for n, a, b, d in cam[:30]]
		if len(cam) > 30:
			informe.append("  ... y {} más".format(len(cam) - 30))
	indentadas = [(i + 1, linea) for i, linea in enumerate(lineas) if linea and linea[0] in (" ", "\t")]
	if indentadas:
		informe += ["", "Detalle de indentación (líneas indentadas):"]
		informe += ["  Línea {} [{}]: {}".format(n, _detector.detectar_indentacion(linea), linea.strip()[:60]) for n, linea in indentadas[:50]]
	return "\n".join(informe)


class HerramientaIndentacion(HerramientaBase):
	METADATOS = MetadatosHerramienta(
		nombre="Analizador de indentación",
		version="1.0.0",
		descripcion="Analiza la estructura de indentación del código",
		autor="Héctor J. Benítez Corredera",
		categoria="desarrollo",
	)

	def ejecutar(self, **kwargs):
		return informe_indentacion(self.texto_de(kwargs))
