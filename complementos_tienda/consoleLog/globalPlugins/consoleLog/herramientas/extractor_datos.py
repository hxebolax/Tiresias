"""Extractor de datos: URL, rutas de archivos y direcciones IP."""

from __future__ import annotations

import ipaddress
import re

from . import HerramientaBase, MetadatosHerramienta

PATRONES = {
	"urls": re.compile(r"https?://[^\s<>\"']+|www\.[^\s<>\"']+"),
	"rutas": re.compile(r"(?:[a-zA-Z]:\\(?:[^\\/:*?\"<>|\r\n]+\\)*[^\\/:*?\"<>|\r\n\s]*)|(?:(?<![\w:/.])/(?:[^/\s]+/)+[^/\s]*)"),
	"ips": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
}
NOMBRES = {"urls": "URL", "rutas": "RUTA", "ips": "IP"}


def extraer_datos(texto: str) -> dict[str, list[str]]:
	resultados: dict[str, list[str]] = {}
	for categoria, patron in PATRONES.items():
		vistos: set[str] = set()
		unicos = []
		for item in patron.findall(texto or ""):
			item = item.rstrip(".,;:)]}")
			if categoria == "ips":
				try:
					ipaddress.IPv4Address(item)
				except ValueError:
					continue
			if item and item not in vistos:
				vistos.add(item)
				unicos.append(item)
		resultados[categoria] = unicos
	return resultados


def como_lista(resultados: dict[str, list[str]]) -> list[str]:
	return ["[{}] {}".format(NOMBRES.get(cat, cat.upper()), item) for cat, lista in resultados.items() for item in lista]


def valor_de_elemento(elemento: str) -> str:
	"""Quita la etiqueta «[URL] » de un elemento de la lista."""
	return elemento.split("]", 1)[1].strip() if elemento.startswith("[") and "]" in elemento else elemento


class HerramientaExtractorDatos(HerramientaBase):
	METADATOS = MetadatosHerramienta(
		nombre="Extractor de datos (URL, rutas, IP)",
		version="1.0.0",
		descripcion="Busca y extrae URL, rutas de archivos y direcciones IP del terminal",
		autor="Héctor J. Benítez Corredera",
		categoria="analisis",
	)

	def ejecutar(self, **kwargs):
		return extraer_datos(self.texto_de(kwargs))
