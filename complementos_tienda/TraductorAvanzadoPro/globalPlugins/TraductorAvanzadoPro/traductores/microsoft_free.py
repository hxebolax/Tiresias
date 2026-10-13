"""Microsoft Translator gratuito, sin clave.

Primero se intenta, como el original, el token público del traductor de Edge
(``edge.microsoft.com/translate/auth``) con la API de Microsoft Translator.
Si ese servicio no responde (Microsoft lo ha retirado en algunas regiones),
se usa el traductor web de Bing (``bing.com/translator``), que es el mismo
motor: se leen de la página los parámetros de la sesión y se traduce con
``ttranslatev3``.
"""

from __future__ import annotations

import re
import time
import urllib.parse
from typing import Any

from tiresias.log import getLogger

from ..nucleo.gestor_traductores import TraductorBase
from ..utilidades import red
from ..utilidades.texto import dividir_por_longitud

log = getLogger("TraductorAvanzadoPro")


class TraductorMicrosoftFree(TraductorBase):
	id = "microsoft_free"
	nombre = "Microsoft Translator (Gratuito)"
	descripcion = "Traduce textos usando Microsoft Translator sin API key"
	version = "2.1.0"
	requiere_api = False
	soporta_deteccion = True

	ENDPOINT_TOKEN = "https://edge.microsoft.com/translate/auth"
	ENDPOINT_TRANSLATE = "https://api.cognitive.microsofttranslator.com/translate"
	ENDPOINT_DETECT = "https://api.cognitive.microsofttranslator.com/detect"
	BING_PAGINA = "https://www.bing.com/translator"
	BING_TRADUCIR = "https://www.bing.com/ttranslatev3"
	#: El token de Edge dura 10 minutos; se renueva antes.
	VIGENCIA_TOKEN = 8 * 60
	#: Bing admite como mucho 1000 caracteres por petición.
	TROZO_BING = 1000

	def _inicializar(self) -> None:
		self._token: str | None = None
		self._hora_token = 0.0
		#: Tras fallar el token de Edge se usa Bing durante un rato sin volver a probarlo.
		self._edge_fallido_hasta = 0.0
		self._bing: dict[str, Any] | None = None

	def adaptar_idioma(self, codigo: str) -> str:
		if not codigo or codigo == "auto":
			return "auto"
		bajo = codigo.lower().replace("_", "-")
		return {
			"zh": "zh-Hans",
			"zh-cn": "zh-Hans",
			"zh-hans": "zh-Hans",
			"zh-tw": "zh-Hant",
			"zh-hant": "zh-Hant",
			"no": "nb",
			"tl": "fil",
			"pt-br": "pt",
			"pt-pt": "pt-pt",
			"en-us": "en",
			"en-gb": "en",
		}.get(bajo, codigo)

	# ------------------------------------------------------------ API con token de Edge
	def _obtener_token(self, forzar: bool = False) -> str | None:
		if not forzar and self._token and time.monotonic() - self._hora_token < self.VIGENCIA_TOKEN:
			return self._token
		if time.monotonic() < self._edge_fallido_hasta:
			return None
		try:
			token = red.peticion(self.ENDPOINT_TOKEN, timeout=10).decode("utf-8").strip()
		except red.ErrorRed as e:
			log.debug("Token de Edge no disponible (%s); se usará el traductor web de Bing", e.mensaje)
			self._token = None
			self._edge_fallido_hasta = time.monotonic() + 30 * 60
			return None
		self._token = token or None
		self._hora_token = time.monotonic()
		return self._token

	def _traducir_api(self, texto: str, origen: str, destino: str) -> str | None:
		params = {"api-version": "3.0", "to": destino}
		if origen != "auto":
			params["from"] = origen
		url = f"{self.ENDPOINT_TRANSLATE}?{urllib.parse.urlencode(params)}"
		for intento in range(2):
			token = self._obtener_token(forzar=intento > 0)
			if not token:
				return None
			try:
				respuesta = red.peticion_json(url, [{"Text": texto}], {"Authorization": f"Bearer {token}"}, "POST", 12)
			except red.ErrorRed as e:
				if e.codigo == 401 and intento == 0:
					continue
				self.ultimo_error = f"Error de Microsoft: {e.mensaje_api()}"
				return None
			try:
				return respuesta[0]["translations"][0]["text"]
			except (KeyError, IndexError, TypeError):
				self.ultimo_error = "Respuesta inesperada de Microsoft"
				return None
		return None

	# ------------------------------------------------------------ traductor web de Bing
	def _sesion_bing(self, forzar: bool = False) -> dict[str, Any] | None:
		if not forzar and self._bing and time.monotonic() < self._bing["caduca"]:
			return self._bing
		sesion = red.crear_sesion()
		try:
			html = red.peticion(self.BING_PAGINA, sesion=sesion, timeout=15).decode("utf-8", "replace")
		except red.ErrorRed as e:
			self.ultimo_error = f"No se pudo abrir el traductor de Bing: {e.mensaje}"
			return None
		ig = re.search(r'IG:"([^"]+)"', html)
		iid = re.search(r'data-iid="([^"]+)"', html)
		abuso = re.search(r"params_AbusePreventionHelper\s*=\s*\[([^\]]+)\]", html)
		if not (ig and abuso):
			self.ultimo_error = "El traductor de Bing ha cambiado y no se pudo usar"
			return None
		partes = [p.strip().strip('"') for p in abuso.group(1).split(",")]
		if len(partes) < 2:
			self.ultimo_error = "El traductor de Bing ha cambiado y no se pudo usar"
			return None
		try:
			vigencia = int(partes[2]) / 1000.0 if len(partes) > 2 else 3600.0
		except ValueError:
			vigencia = 3600.0
		self._bing = {
			"sesion": sesion,
			"ig": ig.group(1),
			"iid": iid.group(1) if iid else "translator.5023",
			"clave": partes[0],
			"token": partes[1],
			"caduca": time.monotonic() + max(60.0, vigencia - 300),
			"contador": 0,
		}
		return self._bing

	def _traducir_bing(self, texto: str, origen: str, destino: str) -> str | None:
		partes = []
		for trozo in dividir_por_longitud(texto, self.TROZO_BING):
			resultado = None
			for intento in range(2):
				datos = self._sesion_bing(forzar=intento > 0)
				if not datos:
					return None
				datos["contador"] += 1
				url = f"{self.BING_TRADUCIR}?isVertical=1&IG={datos['ig']}&IID={datos['iid']}.{datos['contador']}"
				cuerpo = red.codificar_formulario({"fromLang": "auto-detect" if origen == "auto" else origen, "to": destino, "text": trozo, "token": datos["token"], "key": datos["clave"]})
				try:
					respuesta = red.peticion_json(url, cuerpo, {"Content-Type": "application/x-www-form-urlencoded", "Referer": self.BING_PAGINA}, "POST", 15, sesion=datos["sesion"])
				except red.ErrorRed as e:
					self.ultimo_error = f"Error del traductor de Bing: {e.mensaje}"
					continue
				try:
					resultado = respuesta[0]["translations"][0]["text"]
					break
				except (KeyError, IndexError, TypeError):
					# Token caducado o petición rechazada: se pide una sesión nueva.
					self.ultimo_error = "Respuesta inesperada del traductor de Bing"
					continue
			if resultado is None:
				return None
			partes.append(resultado)
		return "".join(partes)

	# ------------------------------------------------------------ interfaz común
	def traducir(self, texto: str, idioma_origen: str = "auto", idioma_destino: str = "es", **kwargs: Any) -> str | None:
		if not texto or not texto.strip():
			return texto
		self.ultimo_error = None
		origen = self.adaptar_idioma(idioma_origen)
		destino = self.adaptar_idioma(idioma_destino)
		resultado = self._traducir_api(texto, origen, destino)
		if resultado is None:
			resultado = self._traducir_bing(texto, origen, destino)
		if resultado is None:
			log.error("Microsoft Translator: %s", self.ultimo_error)
		return resultado

	def detectar_idioma(self, texto: str) -> str | None:
		token = self._obtener_token()
		if token:
			try:
				respuesta = red.peticion_json(f"{self.ENDPOINT_DETECT}?api-version=3.0", [{"Text": texto[:500]}], {"Authorization": f"Bearer {token}"}, "POST", 10)
				return respuesta[0]["language"]
			except (red.ErrorRed, KeyError, IndexError, TypeError):
				pass
		datos = self._sesion_bing()
		if not datos:
			return None
		datos["contador"] += 1
		url = f"{self.BING_TRADUCIR}?isVertical=1&IG={datos['ig']}&IID={datos['iid']}.{datos['contador']}"
		cuerpo = red.codificar_formulario({"fromLang": "auto-detect", "to": "en", "text": texto[:500], "token": datos["token"], "key": datos["clave"]})
		try:
			respuesta = red.peticion_json(url, cuerpo, {"Content-Type": "application/x-www-form-urlencoded", "Referer": self.BING_PAGINA}, "POST", 15, sesion=datos["sesion"])
			return respuesta[0]["detectedLanguage"]["language"]
		except (red.ErrorRed, KeyError, IndexError, TypeError):
			return None

	def obtener_idiomas(self) -> dict[str, str]:
		from ..servicios.idiomas import IDIOMAS_COMUNES

		idiomas = dict(IDIOMAS_COMUNES)
		idiomas["pt-pt"] = "Portugués (Portugal)"
		return idiomas
