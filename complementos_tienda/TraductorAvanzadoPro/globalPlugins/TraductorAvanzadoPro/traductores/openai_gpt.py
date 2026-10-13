"""OpenAI (modelos GPT y de razonamiento) mediante la API de chat."""

from __future__ import annotations

from typing import Any

from tiresias.log import getLogger

from ..nucleo.gestor_traductores import TraductorBase
from ..utilidades import red
from ._comun import preparar_prompts

log = getLogger("TraductorAvanzadoPro")


class TraductorOpenAI(TraductorBase):
	id = "openai"
	nombre = "OpenAI GPT"
	descripcion = "Traduce textos usando modelos GPT de OpenAI (requiere API key)"
	version = "2.0.0"
	requiere_api = True
	soporta_deteccion = True
	es_ia = True

	ENDPOINT = "https://api.openai.com/v1/chat/completions"
	MODELO_DEFECTO = "gpt-4o-mini"
	MAX_TOKENS = 16384

	def _endpoint(self, servicio_config: Any) -> str:
		"""Con «URL del servidor» se puede usar cualquier API compatible con OpenAI."""
		url = getattr(servicio_config, "api_url", None)
		if url:
			url = url.rstrip("/")
			return url if url.endswith("/chat/completions") else f"{url}/chat/completions"
		return self.ENDPOINT

	def traducir(self, texto: str, idioma_origen: str = "auto", idioma_destino: str = "es", **kwargs: Any) -> str | None:
		if not texto or not texto.strip():
			return texto
		self.ultimo_error = None
		if not self.validar_api():
			self.ultimo_error = "No hay ninguna clave de OpenAI configurada"
			return None
		sc = self.configuracion_servicio()
		modelo = sc.modelo or self.MODELO_DEFECTO
		partes = []
		for trozo in self._dividir_texto(texto):
			traduccion = self._traducir_chunk(trozo, idioma_destino, sc.api_key or "", modelo, sc)
			intentos = 0
			while traduccion is None and self._ultimo_codigo in (401, 429) and intentos < len(sc.claves) - 1 and self.rotar_y_reintentar():
				intentos += 1
				traduccion = self._traducir_chunk(trozo, idioma_destino, sc.api_key or "", modelo, sc)
			if traduccion is None:
				return None
			partes.append(traduccion)
		return " ".join(partes).strip()

	def _traducir_chunk(self, texto: str, idioma_destino: str, api_key: str, modelo: str, servicio_config: Any) -> str | None:
		self._ultimo_codigo: int | None = None
		max_respuesta = self.MAX_TOKENS - self._estimar_tokens(texto) - 100
		if max_respuesta <= 0:
			self.ultimo_error = "Texto demasiado largo para OpenAI"
			return None
		sistema, usuario = preparar_prompts(servicio_config, idioma_destino, texto)
		datos: dict[str, Any] = {
			"model": modelo,
			"messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
			"temperature": 1 if modelo.startswith(("o1", "o3", "o4", "gpt-5")) else 0.3,
			"max_completion_tokens": max_respuesta,
		}
		cabeceras = {"Authorization": f"Bearer {api_key}"}
		endpoint = self._endpoint(servicio_config)
		# Hasta tres intentos adaptando los parámetros a lo que admita el modelo.
		for _ in range(3):
			try:
				respuesta = red.peticion_json(endpoint, datos, cabeceras, "POST", 60)
				return str(respuesta["choices"][0]["message"]["content"]).strip()
			except red.ErrorRed as e:
				self._ultimo_codigo = e.codigo
				mensaje = e.mensaje_api()
				if e.codigo == 400 and "max_completion_tokens" in mensaje and "max_completion_tokens" in datos:
					datos["max_tokens"] = datos.pop("max_completion_tokens")
					continue
				if e.codigo == 400 and "max_tokens" in mensaje and "max_tokens" in datos:
					datos["max_completion_tokens"] = datos.pop("max_tokens")
					continue
				if e.codigo == 400 and "temperature" in mensaje and "temperature" in datos:
					datos.pop("temperature")
					continue
				self.ultimo_error = f"Error de OpenAI: {mensaje}"
				log.error(self.ultimo_error)
				return None
			except (KeyError, IndexError, TypeError):
				self.ultimo_error = "Respuesta inesperada de OpenAI"
				return None
		return None

	@staticmethod
	def _estimar_tokens(texto: str) -> int:
		caracteres_por_token = 4 if texto.isascii() else 5
		return int(len(texto) / caracteres_por_token) + 10

	def _dividir_texto(self, texto: str, max_tokens: int = 6000) -> list[str]:
		if self._estimar_tokens(texto) <= max_tokens:
			return [texto]
		partes: list[str] = []
		actual = ""
		for palabra in texto.split():
			if self._estimar_tokens(actual + " " + palabra) < max_tokens:
				actual = f"{actual} {palabra}" if actual else palabra
			else:
				if actual:
					partes.append(actual.strip())
				actual = palabra
		if actual:
			partes.append(actual.strip())
		return partes

	def obtener_idiomas(self) -> dict[str, str]:
		from ..servicios.idiomas import IDIOMAS_COMUNES

		return dict(IDIOMAS_COMUNES)
