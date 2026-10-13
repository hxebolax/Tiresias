"""LibreTranslate (código abierto): servidor propio o públicos, con clave opcional."""

from __future__ import annotations

from typing import Any

from tiresias.log import getLogger

from ..nucleo.gestor_traductores import TraductorBase
from ..utilidades import red

log = getLogger("TraductorAvanzadoPro")


class TraductorLibreTranslate(TraductorBase):
	id = "libretranslate"
	nombre = "LibreTranslate"
	descripcion = "Traduce usando LibreTranslate (código abierto)"
	version = "2.0.0"
	#: Algunos servidores piden clave; se puede usar sin ella (por eso validar_api es siempre cierto).
	requiere_api = True
	soporta_deteccion = True

	SERVIDORES_PUBLICOS = [
		"https://libretranslate.com",
		"https://translate.argosopentech.com",
		"https://translate.terraprint.co",
	]

	def _inicializar(self) -> None:
		self._servidor_actual = 0

	def _obtener_servidor(self) -> str:
		sc = self.configuracion_servicio()
		if sc and sc.api_url:
			return sc.api_url.rstrip("/")
		return self.SERVIDORES_PUBLICOS[self._servidor_actual]

	def _obtener_api_key(self) -> str | None:
		sc = self.configuracion_servicio()
		return sc.api_key if sc else None

	def _rotar_servidor(self) -> None:
		self._servidor_actual = (self._servidor_actual + 1) % len(self.SERVIDORES_PUBLICOS)

	def adaptar_idioma(self, codigo: str) -> str:
		if not codigo or codigo == "auto":
			return "auto"
		bajo = codigo.lower().replace("_", "-")
		if bajo in ("zh-tw", "zh-hant"):
			return "zt"
		if bajo.startswith("zh"):
			return "zh"
		if bajo in ("no", "nn"):
			return "nb"
		return bajo.split("-")[0]

	def traducir(self, texto: str, idioma_origen: str = "auto", idioma_destino: str = "es", **kwargs: Any) -> str | None:
		if not texto or not texto.strip():
			return texto
		self.ultimo_error = None
		servidor = self._obtener_servidor()
		api_key = self._obtener_api_key()
		origen = self.adaptar_idioma(idioma_origen)
		if origen == "auto":
			# Como el original: se detecta antes; si no se puede, LibreTranslate detecta solo.
			origen = self._detectar_idioma_interno(texto, servidor) or "auto"
		datos = {"q": texto, "source": origen, "target": self.adaptar_idioma(idioma_destino), "format": "text"}
		if api_key:
			datos["api_key"] = api_key
		try:
			respuesta = red.peticion_json(f"{servidor}/translate", datos, metodo="POST", timeout=15)
		except red.ErrorRed as e:
			self.ultimo_error = f"Error de LibreTranslate ({servidor}): {e.mensaje_api()}"
			log.error(self.ultimo_error)
			sc = self.configuracion_servicio()
			if not (sc and sc.api_url):
				self._rotar_servidor()
			return None
		if isinstance(respuesta, dict) and respuesta.get("translatedText") is not None:
			return respuesta["translatedText"]
		self.ultimo_error = "Respuesta inesperada de LibreTranslate"
		return None

	def _detectar_idioma_interno(self, texto: str, servidor: str) -> str | None:
		datos: dict[str, Any] = {"q": texto[:500]}
		api_key = self._obtener_api_key()
		if api_key:
			datos["api_key"] = api_key
		try:
			respuesta = red.peticion_json(f"{servidor}/detect", datos, metodo="POST", timeout=10)
			if respuesta and isinstance(respuesta, list):
				return respuesta[0].get("language")
		except (red.ErrorRed, AttributeError, IndexError):
			pass
		return None

	def detectar_idioma(self, texto: str) -> str | None:
		return self._detectar_idioma_interno(texto, self._obtener_servidor())

	def obtener_idiomas(self) -> dict[str, str]:
		from ..servicios.idiomas import IDIOMAS_COMUNES

		return dict(IDIOMAS_COMUNES)

	def validar_api(self) -> bool:
		return True
