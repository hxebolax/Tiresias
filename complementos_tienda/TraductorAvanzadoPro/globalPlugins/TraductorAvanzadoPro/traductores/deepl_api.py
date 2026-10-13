"""DeepL con la API oficial (cuentas Free y Pro; requiere clave)."""

from __future__ import annotations

from typing import Any

from tiresias.log import getLogger

from ..nucleo.gestor_traductores import TraductorBase
from ..utilidades import red
from .deepl_free import IDIOMAS_DEEPL, adaptar_deepl

log = getLogger("TraductorAvanzadoPro")


class TraductorDeepLAPI(TraductorBase):
	id = "deepl_api"
	nombre = "DeepL API"
	descripcion = "Traduce usando la API oficial de DeepL (requiere API key)"
	version = "2.0.0"
	requiere_api = True
	soporta_deteccion = True

	ENDPOINT_FREE = "https://api-free.deepl.com/v2/translate"
	ENDPOINT_PRO = "https://api.deepl.com/v2/translate"

	@staticmethod
	def _es_cuenta_pro(api_key: str) -> bool:
		"""Las claves de la API Free terminan en «:fx»."""
		return not api_key.endswith(":fx")

	def _obtener_endpoint(self, api_key: str) -> str:
		return self.ENDPOINT_PRO if self._es_cuenta_pro(api_key) else self.ENDPOINT_FREE

	def adaptar_idioma(self, codigo: str) -> str:
		return adaptar_deepl(codigo)

	def _destino(self, codigo: str) -> str:
		"""DeepL ya no admite «EN» ni «PT» solos como destino."""
		c = self.adaptar_idioma(codigo)
		return {"EN": "EN-US", "PT": "PT-PT"}.get(c, c)

	def traducir(self, texto: str, idioma_origen: str = "auto", idioma_destino: str = "ES", _intentos: int = 0, **kwargs: Any) -> str | None:
		if not texto or not texto.strip():
			return texto
		self.ultimo_error = None
		if not self.validar_api():
			self.ultimo_error = "No hay ninguna clave de DeepL API configurada"
			return None
		sc = self.configuracion_servicio()
		api_key = sc.api_key or ""
		campos = {"text": texto, "target_lang": self._destino(idioma_destino)}
		origen = self.adaptar_idioma(idioma_origen)
		if origen and origen != "auto":
			campos["source_lang"] = origen.split("-")[0]
		if kwargs.get("formality"):
			campos["formality"] = kwargs["formality"]
		cabeceras = {"Authorization": f"DeepL-Auth-Key {api_key}", "Content-Type": "application/x-www-form-urlencoded"}
		try:
			respuesta = red.peticion_json(self._obtener_endpoint(api_key), red.codificar_formulario(campos), cabeceras, "POST", 15)
		except red.ErrorRed as e:
			if e.codigo in (403, 456) and _intentos < len(sc.claves) and self.rotar_y_reintentar():
				return self.traducir(texto, idioma_origen, idioma_destino, _intentos=_intentos + 1, **kwargs)
			if e.codigo == 403:
				self.ultimo_error = "La clave de DeepL no es válida"
			elif e.codigo == 456:
				self.ultimo_error = "Cuota de traducción agotada para la clave actual de DeepL"
			else:
				self.ultimo_error = f"Error de DeepL: {e.mensaje_api()}"
			log.error("DeepL API: %s", self.ultimo_error)
			return None
		traducciones = respuesta.get("translations") if isinstance(respuesta, dict) else None
		if traducciones:
			return traducciones[0].get("text")
		self.ultimo_error = "Respuesta inesperada de DeepL"
		return None

	def detectar_idioma(self, texto: str) -> str | None:
		"""DeepL indica el idioma de origen detectado al traducir."""
		sc = self.configuracion_servicio()
		if not sc or not sc.api_key:
			return None
		try:
			respuesta = red.peticion_json(
				self._obtener_endpoint(sc.api_key),
				red.codificar_formulario({"text": texto[:200], "target_lang": "EN-US"}),
				{"Authorization": f"DeepL-Auth-Key {sc.api_key}"},
				"POST",
				15,
			)
			return str(respuesta["translations"][0]["detected_source_language"]).lower()
		except (red.ErrorRed, KeyError, IndexError, TypeError):
			return None

	def obtener_uso(self) -> dict[str, int] | None:
		"""``{'character_count', 'character_limit'}`` de la clave actual."""
		sc = self.configuracion_servicio()
		if not sc or not sc.api_key:
			return None
		base = "https://api.deepl.com" if self._es_cuenta_pro(sc.api_key) else "https://api-free.deepl.com"
		try:
			return red.peticion_json(f"{base}/v2/usage", cabeceras={"Authorization": f"DeepL-Auth-Key {sc.api_key}"}, timeout=10)
		except red.ErrorRed as e:
			self.ultimo_error = e.mensaje_api()
			return None

	def obtener_idiomas(self) -> dict[str, str]:
		return dict(IDIOMAS_DEEPL)
