"""Analizador de trazas de error: archivos y líneas de las trazas de Python (y otras)."""

from __future__ import annotations

import os
import re

from . import HerramientaBase, MetadatosHerramienta

#: (lenguaje, patrón con grupos ruta y línea).
PATRONES = [
	("Python", re.compile(r'File "(.+?)", line (\d+)')),
	("Node.js", re.compile(r"at .*?\(?((?:[A-Za-z]:)?[\\/][^():\s]+\.(?:js|ts|mjs|cjs)):(\d+):\d+\)?")),
	("Java", re.compile(r"at [\w.$<>]+\(([\w$]+\.java):(\d+)\)")),
	("C#/.NET", re.compile(r" in (.+?\.cs):line (\d+)")),
]


def analizar_trazas(texto: str) -> list[str]:
	vistos: set[str] = set()
	resultados: list[str] = []
	errores = re.findall(r"^\s*((?:[\w.]+(?:Error|Exception)|Traceback \(most recent call last\)).*)$", texto or "", re.MULTILINE)
	for lenguaje, patron in PATRONES:
		for ruta, linea in patron.findall(texto or ""):
			item = "{}:{} -> {} ({})".format(os.path.basename(ruta.replace("\\", "/")), linea, ruta, lenguaje)
			if item not in vistos:
				vistos.add(item)
				resultados.append(item)
	for error in errores:
		error = error.strip()
		if error and not error.startswith("Traceback") and error not in vistos:
			vistos.add(error)
			resultados.append("Error: {}".format(error))
	return resultados


class HerramientaStackTrace(HerramientaBase):
	METADATOS = MetadatosHerramienta(
		nombre="Analizador de StackTrace",
		version="1.0.0",
		descripcion="Analiza el log en busca de errores de Python y extrae rutas de archivos",
		autor="Héctor J. Benítez Corredera",
		categoria="desarrollo",
	)

	def ejecutar(self, **kwargs):
		resultados = analizar_trazas(self.texto_de(kwargs))
		return resultados or ["No se han encontrado trazas de error (stack traces) en el texto."]
