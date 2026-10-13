"""Embellecedor de JSON: encuentra los bloques JSON de la salida y los indenta."""

from __future__ import annotations

import json

from . import HerramientaBase, MetadatosHerramienta

#: Límite de posiciones de inicio que se prueban (protege con salidas enormes).
MAX_CANDIDATOS = 20000


def extraer_bloques_json(texto: str) -> list[str]:
	"""Bloques JSON válidos (objetos o listas no triviales), ya formateados."""
	decodificador = json.JSONDecoder()
	bloques: list[str] = []
	i = 0
	probados = 0
	n = len(texto or "")
	while i < n and probados < MAX_CANDIDATOS:
		inicio = min((p for p in (texto.find("{", i), texto.find("[", i)) if p != -1), default=-1)
		if inicio == -1:
			break
		probados += 1
		try:
			datos, fin = decodificador.raw_decode(texto, inicio)
		except ValueError:
			i = inicio + 1
			continue
		if isinstance(datos, (dict, list)) and datos:
			bloques.append(json.dumps(datos, indent=4, ensure_ascii=False))
			i = fin
		else:
			i = inicio + 1
	return bloques


class HerramientaJSON(HerramientaBase):
	METADATOS = MetadatosHerramienta(
		nombre="Embellecedor de JSON",
		version="1.0.0",
		descripcion="Detecta bloques JSON en la consola y los muestra formateados y legibles",
		autor="Héctor J. Benítez Corredera",
		categoria="desarrollo",
	)

	def ejecutar(self, **kwargs):
		return extraer_bloques_json(self.texto_de(kwargs))
