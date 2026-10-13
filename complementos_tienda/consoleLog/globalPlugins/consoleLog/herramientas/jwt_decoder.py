"""Decodificador de JWT: muestra encabezado y carga útil (no valida la firma)."""

from __future__ import annotations

import base64
import datetime
import json
import re

from . import HerramientaBase, MetadatosHerramienta

PATRON_JWT = re.compile(r"\bey[A-Za-z0-9_-]+\.ey[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*")
CAMPOS_FECHA = ("exp", "iat", "nbf", "auth_time")


def _decodificar_parte(parte: str) -> dict:
	parte += "=" * (-len(parte) % 4)
	return json.loads(base64.urlsafe_b64decode(parte.encode("ascii")).decode("utf-8"))


def decodificar_jwts(texto: str) -> list[str]:
	resultados = []
	vistos: set[str] = set()
	for token in PATRON_JWT.findall(texto or ""):
		if token in vistos:
			continue
		vistos.add(token)
		try:
			cabecera_b64, carga_b64 = token.split(".")[:2]
			cabecera = _decodificar_parte(cabecera_b64)
			carga = _decodificar_parte(carga_b64)
		except (ValueError, UnicodeError):
			continue
		lineas = [
			"JWT {}...".format(token[:20]),
			"Encabezado:",
			json.dumps(cabecera, indent=2, ensure_ascii=False),
			"Carga útil:",
			json.dumps(carga, indent=2, ensure_ascii=False),
		]
		fechas = []
		for campo in CAMPOS_FECHA:
			valor = carga.get(campo) if isinstance(carga, dict) else None
			if isinstance(valor, (int, float)):
				try:
					fechas.append("{}: {}".format(campo, datetime.datetime.fromtimestamp(valor).strftime("%d/%m/%Y %H:%M:%S")))
				except (OverflowError, OSError, ValueError):
					pass
		if fechas:
			lineas += ["Fechas:"] + fechas
		lineas.append("Aviso: la firma no se ha comprobado; decodificar no garantiza la autenticidad del token.")
		resultados.append("\n".join(lineas))
	return resultados


class HerramientaJWT(HerramientaBase):
	METADATOS = MetadatosHerramienta(
		nombre="Decodificador JWT",
		version="1.0.0",
		descripcion="Busca y decodifica tokens JWT en el texto",
		autor="Héctor J. Benítez Corredera",
		categoria="edición",
	)

	def ejecutar(self, **kwargs):
		resultados = decodificar_jwts(self.texto_de(kwargs))
		return resultados or ["No se encontraron tokens JWT válidos."]
