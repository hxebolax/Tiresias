"""Claude, de Anthropic (API Messages).

La descripción del complemento original cita Claude entre sus servicios, pero
no traía el traductor; aquí está completo: clave, rotación de claves, modelo
elegible de la lista de la API y prompts propios, como OpenAI, Gemini y
DeepSeek.

Se usa la API REST directamente (``urllib``), porque el complemento no puede
llevar bibliotecas de terceros. Para traducir basta con esfuerzo bajo
(``output_config.effort = "low"``); con los modelos que lo admiten se pide
además el modelo de respaldo automático del servidor si el principal rehúsa
la petición (``fallbacks: "default"``).
"""

from __future__ import annotations

from typing import Any

from tiresias.log import getLogger

from ..nucleo.gestor_traductores import TraductorBase
from ..utilidades import red
from ._comun import preparar_prompts

log = getLogger("TraductorAvanzadoPro")

#: Modelos que admiten el respaldo del servidor con ``fallbacks: "default"``.
_CON_RESPALDO = ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")
#: Modelos antiguos sin el parámetro de esfuerzo.
_SIN_ESFUERZO = ("claude-3", "claude-haiku-4-5", "claude-sonnet-4-5", "claude-opus-4-1", "claude-opus-4-0", "claude-sonnet-4-0", "claude-opus-4-2", "claude-sonnet-4-2")


class TraductorClaude(TraductorBase):
	id = "claude"
	nombre = "Claude (Anthropic)"
	descripcion = "Traduce textos usando los modelos Claude de Anthropic (requiere API key)"
	version = "1.0.0"
	requiere_api = True
	soporta_deteccion = True
	es_ia = True

	ENDPOINT = "https://api.anthropic.com/v1/messages"
	VERSION_API = "2023-06-01"
	MODELO_DEFECTO = "claude-opus-5-5"
	BETA_RESPALDO = "server-side-fallback-2026-07-01"

	def _cuerpo(self, modelo: str, sistema: str, usuario: str) -> tuple[dict[str, Any], dict[str, str]]:
		datos: dict[str, Any] = {
			"model": modelo,
			"max_tokens": 16000,
			"system": sistema,
			"messages": [{"role": "user", "content": usuario}],
		}
		cabeceras: dict[str, str] = {}
		if not modelo.startswith(_SIN_ESFUERZO):
			datos["output_config"] = {"effort": "low"}
		if modelo in _CON_RESPALDO:
			datos["fallbacks"] = "default"
			cabeceras["anthropic-beta"] = self.BETA_RESPALDO
		return datos, cabeceras

	def traducir(self, texto: str, idioma_origen: str = "auto", idioma_destino: str = "es", _intentos: int = 0, **kwargs: Any) -> str | None:
		if not texto or not texto.strip():
			return texto
		self.ultimo_error = None
		if not self.validar_api():
			self.ultimo_error = "No hay ninguna clave de Claude configurada"
			return None
		sc = self.configuracion_servicio()
		modelo = sc.modelo or self.MODELO_DEFECTO
		sistema, usuario = preparar_prompts(sc, idioma_destino, texto)
		datos, extra = self._cuerpo(modelo, sistema, usuario)
		cabeceras = {"x-api-key": sc.api_key or "", "anthropic-version": self.VERSION_API, **extra}
		respuesta = None
		for _ in range(3):
			try:
				respuesta = red.peticion_json(self.ENDPOINT, datos, cabeceras, "POST", 120)
				break
			except red.ErrorRed as e:
				mensaje = e.mensaje_api()
				if e.codigo == 400 and "fallbacks" in datos and ("fallback" in mensaje.lower() or "beta" in mensaje.lower()):
					# Cuenta o plataforma sin el respaldo del servidor: se pide sin él.
					datos.pop("fallbacks", None)
					cabeceras.pop("anthropic-beta", None)
					continue
				if e.codigo == 400 and "output_config" in datos and ("effort" in mensaje.lower() or "output_config" in mensaje):
					datos.pop("output_config", None)
					continue
				if e.codigo in (401, 403, 429) and _intentos < len(sc.claves) - 1 and self.rotar_y_reintentar():
					return self.traducir(texto, idioma_origen, idioma_destino, _intentos=_intentos + 1, **kwargs)
				if e.codigo == 401:
					self.ultimo_error = "La clave de Claude no es válida"
				elif e.codigo == 429:
					self.ultimo_error = "Claude: límite de peticiones alcanzado; inténtelo más tarde"
				else:
					self.ultimo_error = f"Error de Claude ({e.codigo}): {mensaje}"
				log.error(self.ultimo_error)
				return None
		if not isinstance(respuesta, dict):
			self.ultimo_error = "Respuesta inesperada de Claude"
			return None
		if respuesta.get("stop_reason") == "refusal":
			detalles = respuesta.get("stop_details") or {}
			self.ultimo_error = "Claude ha rehusado traducir este texto" + (f": {detalles.get('explanation')}" if detalles.get("explanation") else "")
			return None
		bloques = respuesta.get("content") or []
		texto_resp = "".join(str(b.get("text", "")) for b in bloques if isinstance(b, dict) and b.get("type") == "text")
		if not texto_resp.strip():
			self.ultimo_error = "Claude no devolvió texto"
			return None
		return texto_resp.strip()

	def obtener_idiomas(self) -> dict[str, str]:
		from ..servicios.idiomas import IDIOMAS_COMUNES

		return dict(IDIOMAS_COMUNES)
