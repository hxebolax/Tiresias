"""Historial de comandos: órdenes escritas tras los indicadores habituales."""

from __future__ import annotations

import re

from . import HerramientaBase, MetadatosHerramienta

PATRONES_PROMPT = [
	re.compile(r"^[A-Za-z]:\\[^>]*>(.+)$"),  # CMD: C:\Users\Usuario>orden
	re.compile(r"^PS [A-Za-z]:\\[^>]*>(.+)$"),  # PowerShell: PS C:\Users>orden
	re.compile(r"^PS [^>]*>(.+)$"),  # PowerShell en otras unidades o rutas
	re.compile(r"^[\w.-]+@[\w.-]+(?::[^$#]*)?[$#] (.+)$"),  # bash: usuario@equipo:~$ orden
	re.compile(r"^\$ (.+)$"),  # bash: $ orden
	re.compile(r"^# (.+)$"),  # root: # orden
	re.compile(r"^>>> (.+)$"),  # Python
	re.compile(r"^> (.+)$"),  # indicador genérico
]


def extraer_comandos(texto: str) -> list[str]:
	comandos = []
	for linea in (texto or "").splitlines():
		linea = linea.strip()
		if not linea:
			continue
		for patron in PATRONES_PROMPT:
			m = patron.match(linea)
			if m:
				comando = m.group(1).strip()
				if comando:
					comandos.append(comando)
				break
	return comandos


class HerramientaHistorialComandos(HerramientaBase):
	METADATOS = MetadatosHerramienta(
		nombre="Historial de comandos",
		version="2.0.0",
		descripcion="Extrae y lista los comandos ejecutados en la consola",
		autor="Héctor J. Benítez Corredera",
		categoria="analisis",
	)

	def ejecutar(self, **kwargs):
		return extraer_comandos(self.texto_de(kwargs))

	def obtener_ultimo_comando(self, texto: str) -> str:
		comandos = extraer_comandos(texto)
		return comandos[-1] if comandos else ""

	def obtener_comandos_unicos(self, texto: str) -> list[str]:
		vistos: set[str] = set()
		unicos = []
		for c in extraer_comandos(texto):
			if c not in vistos:
				vistos.add(c)
				unicos.append(c)
		return unicos
