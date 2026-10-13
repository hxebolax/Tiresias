"""Google Gemini (API generateContent)."""

from __future__ import annotations

import urllib.parse
from typing import Any

from tiresias.log import getLogger

from ..nucleo.gestor_traductores import TraductorBase
from ..utilidades import red
from ._comun import preparar_prompts

log = getLogger("TraductorAvanzadoPro")


class TraductorGemini(TraductorBase):
	id = "gemini"
	nombre = "Google Gemini"
	descripcion = "Traduce textos usando la IA Gemini de Google (requiere API key)"
	version = "1.0.0"
	requiere_api = True
	soporta_deteccion = True
	es_ia = True

	ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
	#: El original usaba «gemini-1.5-flash», que Google ya ha retirado.
	MODELO_DEFECTO = "gemini-2.5-flash"

	def traducir(self, texto: str, idioma_origen: str = "auto", idioma_destino: str = "es", _intentos: int = 0, **kwargs: Any) -> str | None:
		if not texto or not texto.strip():
			return texto
		self.ultimo_error = None
		if not self.validar_api():
			self.ultimo_error = "No hay ninguna clave de Gemini configurada"
			return None
		sc = self.configuracion_servicio()
		modelo = (sc.modelo or self.MODELO_DEFECTO).removeprefix("models/")
		sistema, usuario = preparar_prompts(sc, idioma_destino, texto)
		datos = {
			"system_instruction": {"parts": [{"text": sistema}]},
			"contents": [{"role": "user", "parts": [{"text": usuario}]}],
			"generationConfig": {"temperature": 0.2, "maxOutputTokens": 8192},
		}
		url = self.ENDPOINT.format(modelo=urllib.parse.quote(modelo, safe="-._"))
		try:
			respuesta = red.peticion_json(url, datos, {"x-goog-api-key": sc.api_key or ""}, "POST", 60)
		except red.ErrorRed as e:
			if e.codigo in (401, 403, 429) and _intentos < len(sc.claves) - 1 and self.rotar_y_reintentar():
				return self.traducir(texto, idioma_origen, idioma_destino, _intentos=_intentos + 1, **kwargs)
			self.ultimo_error = f"Error de Gemini ({e.codigo}) con el modelo «{modelo}»: {e.mensaje_api()}"
			if e.codigo == 404:
				self.ultimo_error += ". Compruebe el nombre del modelo (por ejemplo, gemini-2.5-flash)."
			log.error(self.ultimo_error)
			return None
		try:
			partes = respuesta["candidates"][0]["content"]["parts"]
			texto_resp = "".join(str(p.get("text", "")) for p in partes if isinstance(p, dict) and not p.get("thought"))
			if texto_resp.strip():
				return texto_resp.strip()
		except (KeyError, IndexError, TypeError):
			pass
		motivo = ""
		try:
			motivo = respuesta.get("promptFeedback", {}).get("blockReason", "") or respuesta["candidates"][0].get("finishReason", "")
		except Exception:
			pass
		self.ultimo_error = f"Gemini no devolvió texto{f' ({motivo})' if motivo else ''}"
		return None

	def obtener_idiomas(self) -> dict[str, str]:
		from ..servicios.idiomas import IDIOMAS_COMUNES

		return dict(IDIOMAS_COMUNES)
