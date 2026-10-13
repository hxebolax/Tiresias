"""Decodificador Base64: busca cadenas Base64 y muestra su contenido legible."""

from __future__ import annotations

import base64
import binascii
import re

from . import HerramientaBase, MetadatosHerramienta

#: Al menos 8 caracteres para evitar falsos positivos.
PATRON_BASE64 = re.compile(r"(?<![A-Za-z0-9+/=])(?:[A-Za-z0-9+/]{4}){2,}(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?(?![A-Za-z0-9+/=])")


def _legible(texto: str) -> bool:
	if not texto or not any(c.isalnum() for c in texto):
		return False
	imprimibles = sum(1 for c in texto if c.isprintable() or c in "\r\n\t")
	return imprimibles / len(texto) >= 0.9


def decodificar_base64(texto: str) -> list[str]:
	resultados = []
	vistos: set[str] = set()
	for cadena in PATRON_BASE64.findall(texto or ""):
		if cadena in vistos or len(cadena) < 8:
			continue
		vistos.add(cadena)
		try:
			decodificado = base64.b64decode(cadena, validate=True).decode("utf-8")
		except (binascii.Error, UnicodeDecodeError, ValueError):
			continue
		if _legible(decodificado):
			resultados.append("{} -> {}".format(cadena, decodificado))
	return resultados


class HerramientaBase64(HerramientaBase):
	METADATOS = MetadatosHerramienta(
		nombre="Decodificador Base64",
		version="1.0.0",
		descripcion="Busca y decodifica cadenas de texto en formato Base64",
		autor="Héctor J. Benítez Corredera",
		categoria="desarrollo",
	)

	def ejecutar(self, **kwargs):
		return decodificar_base64(self.texto_de(kwargs))
