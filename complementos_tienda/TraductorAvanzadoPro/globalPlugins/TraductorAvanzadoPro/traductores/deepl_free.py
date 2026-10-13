"""DeepL gratuito (el servicio de la extensión del navegador, sin clave)."""

from __future__ import annotations

import json
import random
import time
from typing import Any

from tiresias.log import getLogger

from ..nucleo.gestor_traductores import TraductorBase
from ..utilidades import red

log = getLogger("TraductorAvanzadoPro")

IDIOMAS_DEEPL = {
	"auto": "Detectar automáticamente",
	"AR": "Árabe",
	"BG": "Búlgaro",
	"CS": "Checo",
	"DA": "Danés",
	"DE": "Alemán",
	"EL": "Griego",
	"EN": "Inglés",
	"EN-GB": "Inglés (Reino Unido)",
	"EN-US": "Inglés (Estados Unidos)",
	"ES": "Español",
	"ET": "Estonio",
	"FI": "Finés",
	"FR": "Francés",
	"HU": "Húngaro",
	"ID": "Indonesio",
	"IT": "Italiano",
	"JA": "Japonés",
	"KO": "Coreano",
	"LT": "Lituano",
	"LV": "Letón",
	"NB": "Noruego (Bokmål)",
	"NL": "Neerlandés",
	"PL": "Polaco",
	"PT": "Portugués",
	"PT-BR": "Portugués (Brasil)",
	"PT-PT": "Portugués (Portugal)",
	"RO": "Rumano",
	"RU": "Ruso",
	"SK": "Eslovaco",
	"SL": "Esloveno",
	"SV": "Sueco",
	"TR": "Turco",
	"UK": "Ucraniano",
	"ZH": "Chino simplificado",
}


def adaptar_deepl(codigo: str) -> str:
	"""Código de DeepL: mayúsculas, ``NB`` para noruego y ``ZH`` para chino."""
	if not codigo or codigo == "auto":
		return "auto"
	alto = codigo.upper().replace("_", "-")
	if alto in ("NO", "NN"):
		return "NB"
	if alto.startswith("ZH"):
		return "ZH"
	return alto


class TraductorDeepLFree(TraductorBase):
	id = "deepl_free"
	nombre = "DeepL (Gratuito)"
	descripcion = "Traduce textos usando el servicio gratuito de DeepL"
	version = "2.0.0"
	requiere_api = False
	soporta_deteccion = True

	ENDPOINT = "https://www2.deepl.com/jsonrpc?client=chrome-extension,1.5.1"

	def adaptar_idioma(self, codigo: str) -> str:
		return adaptar_deepl(codigo)

	def _obtener_headers(self) -> dict[str, str]:
		return {
			"Accept": "*/*",
			"Accept-Language": "en-US,en;q=0.9",
			"Authorization": "None",
			"Content-Type": "application/json; charset=utf-8",
			"User-Agent": "DeepLBrowserExtension/1.5.1 Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
			"Origin": "chrome-extension://cofdbpoegempjloogbagkncekinflcnj",
			"Referer": "https://www.deepl.com/",
		}

	def _construir_body(self, texto: str, idioma_origen: str, idioma_destino: str) -> str:
		uid = random.randint(1000000000, 9999999999)
		cuenta_i = texto.count("i")
		ts = int(time.time() * 1000)
		if cuenta_i > 0:
			cuenta_i += 1
			ts = ts - ts % cuenta_i + cuenta_i
		variante: dict[str, str] = {}
		destino = self.adaptar_idioma(idioma_destino)
		if "-" in destino:
			idioma, region = destino.split("-", 1)
			variante["regionalVariant"] = f"{idioma.lower()}-{region}"
			destino = idioma
		origen = self.adaptar_idioma(idioma_origen)
		if origen != "auto" and "-" in origen:
			origen = origen.split("-")[0]
		cuerpo = json.dumps(
			{
				"jsonrpc": "2.0",
				"method": "LMT_handle_texts",
				"params": {
					"commonJobParams": variante,
					"texts": [{"text": texto}],
					"splitting": "newlines",
					"lang": {"source_lang_user_selected": origen, "target_lang": destino},
					"timestamp": ts,
				},
				"id": uid,
			},
			separators=(",", ":"),
			ensure_ascii=False,
		)
		if (uid + 3) % 13 == 0 or (uid + 5) % 29 == 0:
			return cuerpo.replace('"method":"', '"method" : "')
		return cuerpo.replace('"method":"', '"method": "')

	def traducir(self, texto: str, idioma_origen: str = "auto", idioma_destino: str = "ES", **kwargs: Any) -> str | None:
		if not texto or not texto.strip():
			return texto
		self.ultimo_error = None
		cuerpo = self._construir_body(texto, idioma_origen, idioma_destino)
		try:
			respuesta = red.peticion(self.ENDPOINT, cuerpo.encode("utf-8"), self._obtener_headers(), "POST", 12)
		except red.ErrorRed as e:
			if e.codigo == 429:
				self.ultimo_error = "DeepL ha limitado las peticiones gratuitas (demasiadas solicitudes). Espere un rato o use otro servicio."
			else:
				self.ultimo_error = f"DeepL: {e.mensaje_api()}"
			log.error("Error DeepL gratuito: %s", self.ultimo_error)
			return None
		return self._extraer_traduccion(respuesta.decode("utf-8", "replace"))

	def _extraer_traduccion(self, respuesta: str) -> str | None:
		try:
			datos = json.loads(respuesta)
			if "error" in datos:
				self.ultimo_error = f"DeepL: {datos['error'].get('message', datos['error'])}"
				return None
			return datos["result"]["texts"][0]["text"]
		except (ValueError, KeyError, IndexError, TypeError, AttributeError):
			self.ultimo_error = "Respuesta inesperada de DeepL"
			return None

	def obtener_idiomas(self) -> dict[str, str]:
		return dict(IDIOMAS_DEEPL)
