"""Formateador SQL ligero: una cláusula por línea."""

from __future__ import annotations

import re

from . import HerramientaBase, MetadatosHerramienta

PALABRAS_CLAVE = [
	"SELECT", "FROM", "WHERE", "INNER JOIN", "LEFT JOIN", "RIGHT JOIN", "FULL JOIN", "CROSS JOIN",
	"GROUP BY", "ORDER BY", "HAVING", "LIMIT", "OFFSET", "UNION ALL", "UNION",
	"INSERT INTO", "VALUES", "UPDATE", "SET", "DELETE FROM", "AND", "OR",
]
#: Cláusulas que van sangradas (condiciones dentro de WHERE/HAVING/JOIN).
SANGRADAS = ("AND", "OR")


def formatear_sql(texto: str) -> str:
	sql = " ".join((texto or "").split())
	if not sql:
		return ""
	# Las palabras clave compuestas primero, para no partir «INNER JOIN» en «JOIN».
	patron = "|".join(re.escape(k).replace(r"\ ", r"\s+") for k in sorted(PALABRAS_CLAVE, key=len, reverse=True))
	cadenas: list[str] = []

	def proteger(m: re.Match) -> str:
		cadenas.append(m.group(0))
		return "\x00{}\x00".format(len(cadenas) - 1)

	# Las cadenas entre comillas no se tocan.
	sql = re.sub(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"", proteger, sql)

	def salto(m: re.Match) -> str:
		clave = " ".join(m.group(0).upper().split())
		return "\n{}{}".format("  " if clave in SANGRADAS else "", clave)

	sql = re.sub(r"\b(?:{})\b".format(patron), salto, sql, flags=re.IGNORECASE)
	for i, c in enumerate(cadenas):
		sql = sql.replace("\x00{}\x00".format(i), c)
	return "\n".join(linea.rstrip() for linea in sql.strip().splitlines())


class HerramientaSQL(HerramientaBase):
	METADATOS = MetadatosHerramienta(
		nombre="Formateador SQL Lite",
		version="1.0.0",
		descripcion="Intenta dar formato legible a consultas SQL",
		autor="Héctor J. Benítez Corredera",
		categoria="edición",
	)

	def ejecutar(self, **kwargs):
		resultado = formatear_sql(self.texto_de(kwargs))
		return [resultado] if resultado else ["No hay ninguna consulta SQL que formatear."]
