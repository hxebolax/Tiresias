"""Compacta salidas repetitivas conservando el orden."""

from __future__ import annotations

from . import HerramientaBase, MetadatosHerramienta


def compactar(texto: str) -> str:
	lineas = texto.splitlines()
	if not lineas:
		return "No hay contenido para compactar."
	salida = []
	anterior = lineas[0]
	cantidad = 1
	for linea in lineas[1:]:
		if linea == anterior:
			cantidad += 1
			continue
		salida.append("{}  [{} ×]".format(anterior, cantidad) if cantidad > 1 else anterior)
		anterior, cantidad = linea, 1
	salida.append("{}  [{} ×]".format(anterior, cantidad) if cantidad > 1 else anterior)
	return "\n".join(salida)


class HerramientaLineasUnicas(HerramientaBase):
	METADATOS = MetadatosHerramienta(
		nombre="Compactar líneas consecutivas",
		version="1.0.0",
		descripcion="Agrupa mensajes consecutivos idénticos e indica su cantidad",
		autor="Héctor J. Benítez Corredera",
		categoria="edición",
	)

	def ejecutar(self, **kwargs):
		return compactar(self.texto_de(kwargs))
