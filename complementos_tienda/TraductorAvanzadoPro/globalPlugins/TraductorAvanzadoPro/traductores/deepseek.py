"""DeepSeek (API de chat compatible con OpenAI)."""

from __future__ import annotations

from typing import Any

from tiresias.log import getLogger

from ..nucleo.gestor_traductores import TraductorBase
from ..utilidades import red
from ._comun import preparar_prompts

log = getLogger("TraductorAvanzadoPro")


class TraductorDeepSeek(TraductorBase):
	id = "deepseek"
	nombre = "DeepSeek"
	descripcion = "Traduce textos usando la API de DeepSeek (requiere API key)"
	version = "1.0.0"
	requiere_api = True
	soporta_deteccion = True
	es_ia = True

	ENDPOINT = "https://api.deepseek.com/v1/chat/completions"
	MODELO_DEFECTO = "deepseek-chat"

	def traducir(self, texto: str, idioma_origen: str = "auto", idioma_destino: str = "es", _intentos: int = 0, **kwargs: Any) -> str | None:
		if not texto or not texto.strip():
			return texto
		self.ultimo_error = None
		if not self.validar_api():
			self.ultimo_error = "No hay ninguna clave de DeepSeek configurada"
			return None
		sc = self.configuracion_servicio()
		sistema, usuario = preparar_prompts(sc, idioma_destino, texto)
		datos = {
			"model": sc.modelo or self.MODELO_DEFECTO,
			"messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
			"temperature": 0.1,
			"stream": False,
		}
		try:
			respuesta = red.peticion_json(self.ENDPOINT, datos, {"Authorization": f"Bearer {sc.api_key}"}, "POST", 90)
		except red.ErrorRed as e:
			if e.codigo in (401, 402, 429) and _intentos < len(sc.claves) - 1 and self.rotar_y_reintentar():
				return self.traducir(texto, idioma_origen, idioma_destino, _intentos=_intentos + 1, **kwargs)
			if e.codigo == 402:
				self.ultimo_error = "DeepSeek: sin saldo suficiente en la cuenta de la API."
			else:
				self.ultimo_error = f"Error de DeepSeek: {e.mensaje_api()}"
			log.error(self.ultimo_error)
			return None
		try:
			return str(respuesta["choices"][0]["message"]["content"]).strip()
		except (KeyError, IndexError, TypeError):
			self.ultimo_error = "Respuesta inesperada de DeepSeek"
			return None

	def obtener_idiomas(self) -> dict[str, str]:
		from ..servicios.idiomas import IDIOMAS_COMUNES

		return dict(IDIOMAS_COMUNES)
