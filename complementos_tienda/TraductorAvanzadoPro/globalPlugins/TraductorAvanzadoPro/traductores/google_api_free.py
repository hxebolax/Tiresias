"""Google Translate con la API gratuita (sin clave)."""

from __future__ import annotations

import random
import re
import time
import urllib.parse
from typing import Any

from tiresias.log import getLogger

from ..nucleo.gestor_traductores import TraductorBase
from ..utilidades import red
from ..utilidades.texto import dividir_por_longitud

log = getLogger("TraductorAvanzadoPro")


class TraductorGoogleApiFree(TraductorBase):
	id = "google_api_free"
	nombre = "Google Translate (API Gratuita)"
	descripcion = "Traduce textos usando la API gratuita de Google Translate sin necesidad de clave"
	version = "2.0.0"
	requiere_api = False
	soporta_deteccion = True

	ENDPOINTS = [
		"https://translate.googleapis.com/translate_a/single",
		"https://translate.google.com/translate_a/single",
		"https://translate.google.es/translate_a/single",
		"https://translate.google.co.uk/translate_a/single",
	]
	#: Puntuación por la que se corta el texto largo (también la de otros alfabetos).
	PATRON_DIVISION = re.compile(r"[،؛؟]|[　-〿︐-︟︰-﹯！-｠]|[.,!?;:]")
	TAMANO_TROZO = 3000
	#: Servicio alternativo de Google (el de la extensión del navegador) si los anteriores fallan.
	ENDPOINT_ALTERNATIVO = "https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl={origen}&tl={destino}"
	#: Minutos que se deja de usar el servicio principal tras un «demasiadas peticiones».
	PAUSA_LIMITE = 10 * 60

	def _inicializar(self) -> None:
		self._ultimo_idioma_detectado: str | None = None
		self._principal_bloqueado_hasta = 0.0

	def adaptar_idioma(self, codigo: str) -> str:
		if not codigo or codigo == "auto":
			return "auto"
		bajo = codigo.lower().replace("_", "-")
		if bajo in ("zh", "zh-cn", "zh-hans"):
			return "zh-CN"
		if bajo in ("zh-tw", "zh-hant"):
			return "zh-TW"
		if bajo in ("nb", "nn"):
			return "no"
		if bajo.startswith(("en-", "pt-", "es-", "fr-")):
			return bajo.split("-")[0]
		return codigo

	def traducir(self, texto: str, idioma_origen: str = "auto", idioma_destino: str = "es", **kwargs: Any) -> str | None:
		if not texto or not texto.strip():
			return texto
		self.ultimo_error = None
		origen = self.adaptar_idioma(idioma_origen)
		destino = self.adaptar_idioma(idioma_destino)
		endpoint = random.choice(self.ENDPOINTS)
		partes = []
		for trozo in dividir_por_longitud(texto, self.TAMANO_TROZO, self.PATRON_DIVISION):
			traduccion = None
			if time.monotonic() >= self._principal_bloqueado_hasta:
				traduccion = self._traducir_trozo(trozo, origen, destino, endpoint)
				if traduccion is None and endpoint != self.ENDPOINTS[0] and time.monotonic() >= self._principal_bloqueado_hasta:
					# Otro dominio puede estar bloqueado: se reintenta con el principal.
					traduccion = self._traducir_trozo(trozo, origen, destino, self.ENDPOINTS[0])
			if traduccion is None:
				traduccion = self._traducir_alternativo(trozo, origen, destino)
			if traduccion is None:
				return None
			partes.append(traduccion)
		return "".join(partes).strip()

	def _traducir_trozo(self, texto: str, origen: str, destino: str, endpoint: str) -> str | None:
		parametros = urllib.parse.urlencode(
			{"client": "gtx", "sl": origen, "tl": destino, "dt": "t", "dj": "1", "q": texto},
			encoding="utf-8",
			errors="surrogatepass",
		)
		try:
			respuesta = red.peticion_json(f"{endpoint}?{parametros}", timeout=12)
		except red.ErrorRed as e:
			self.ultimo_error = e.mensaje
			log.debug("Google: %s", e.mensaje)
			if e.codigo == 429:
				self._principal_bloqueado_hasta = time.monotonic() + self.PAUSA_LIMITE
			return None
		if not isinstance(respuesta, dict):
			self.ultimo_error = "Respuesta inesperada de Google"
			return None
		if respuesta.get("src"):
			self._ultimo_idioma_detectado = respuesta["src"]
		frases = respuesta.get("sentences")
		if not isinstance(frases, list):
			self.ultimo_error = "Respuesta inesperada de Google"
			return None
		return "".join(str(f.get("trans", "")) for f in frases if isinstance(f, dict))

	def _traducir_alternativo(self, texto: str, origen: str, destino: str) -> str | None:
		url = self.ENDPOINT_ALTERNATIVO.format(origen=urllib.parse.quote(origen), destino=urllib.parse.quote(destino))
		try:
			respuesta = red.peticion_json(url, red.codificar_formulario({"q": texto}), {"Content-Type": "application/x-www-form-urlencoded"}, "POST", 12)
		except red.ErrorRed as e:
			self.ultimo_error = f"Google: {e.mensaje}"
			return None
		if not isinstance(respuesta, list) or not respuesta:
			self.ultimo_error = "Respuesta inesperada de Google"
			return None
		partes = []
		for elemento in respuesta:
			if isinstance(elemento, list) and elemento:
				partes.append(str(elemento[0]))
				if len(elemento) > 1 and elemento[1]:
					self._ultimo_idioma_detectado = str(elemento[1])
			elif isinstance(elemento, str):
				partes.append(elemento)
		self.ultimo_error = None
		return "".join(partes)

	def _dividir_texto(self, texto: str, tamano_max: int = 3000) -> list[str]:
		return dividir_por_longitud(texto, tamano_max, self.PATRON_DIVISION)

	def detectar_idioma(self, texto: str) -> str | None:
		self._ultimo_idioma_detectado = None
		if self.traducir(texto[:100], "auto", "en") is None:
			return None
		return self._ultimo_idioma_detectado

	def obtener_idiomas(self) -> dict[str, str]:
		from ..servicios.idiomas import IDIOMAS_COMUNES

		return dict(IDIOMAS_COMUNES)
