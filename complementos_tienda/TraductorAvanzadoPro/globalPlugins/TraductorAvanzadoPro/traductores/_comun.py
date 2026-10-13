"""Funciones comunes de los traductores (prompts de IA y nombres de idioma).

Empieza por «_», así que el gestor de traductores no lo carga como servicio.
"""

from __future__ import annotations

from typing import Any

PROMPTS_DEFECTO = {
	"sistema": "Eres un traductor profesional. Tu tarea es traducir el texto al idioma indicado manteniendo el tono y el contexto.",
	"usuario": "Traduce el siguiente texto al {idioma_destino}. Devuelve únicamente la traducción, sin explicaciones ni texto adicional:\n\n{texto}",
}


def nombre_idioma_prompt(codigo: str) -> str:
	"""«español (es)» para usar en los prompts de las IA."""
	from ..servicios.idiomas import IDIOMAS_COMUNES

	nombre = IDIOMAS_COMUNES.get(codigo) or IDIOMAS_COMUNES.get(codigo.split("-")[0].lower())
	return f"{nombre.lower()} ({codigo})" if nombre else codigo


def preparar_prompts(servicio_config: Any, idioma_destino: str, texto: str) -> tuple[str, str]:
	"""Prompt de sistema y de usuario con los marcadores sustituidos.

	Si el prompt del usuario no tiene ``{texto}``, el texto se añade al final
	(el original fallaba al formatear prompts con llaves sueltas).
	"""
	sistema = (getattr(servicio_config, "prompt_sistema", None) or PROMPTS_DEFECTO["sistema"]).strip()
	plantilla = getattr(servicio_config, "prompt_usuario", None) or PROMPTS_DEFECTO["usuario"]
	idioma = nombre_idioma_prompt(idioma_destino)
	usuario = plantilla.replace("{idioma_destino}", idioma)
	if "{texto}" in usuario:
		usuario = usuario.replace("{texto}", texto)
	else:
		usuario = f"{usuario.rstrip()}\n\n{texto}"
	return sistema, usuario
