"""Diccionario multilingüe (definiciones, fonética, sinónimos, antónimos y ejemplos).

Fuentes:

- Free Dictionary API (``dictionaryapi.dev``), la del original (inglés).
- Wiktionary (``en.wiktionary.org``, API REST de definiciones), que tiene
  entradas de palabras de muchos idiomas: se usa si la primera no responde o
  no tiene la palabra.
- Si ninguna tiene la palabra, se traduce al inglés con el servicio activo y
  se busca esa traducción.

El resultado se acompaña de su traducción al idioma de destino. El original
solo buscaba en inglés en la primera fuente.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from typing import Any, Callable

from tiresias.log import getLogger

from ..nucleo.gestor_plugins import PluginBase, TipoPlugin
from ..utilidades import red

log = getLogger("TraductorAvanzadoPro")


class PluginDiccionario(PluginBase):
	id = "diccionario"
	nombre = "Diccionario Multilingüe"
	descripcion = "Busca definiciones, sinónimos y ejemplos de palabras"
	tipo = TipoPlugin.UTILIDAD
	version = "1.1.0"
	autor = "Traductor Avanzado Pro"

	ENDPOINT = "https://api.dictionaryapi.dev/api/v2/entries/{idioma}/{palabra}"
	ENDPOINT_WIKTIONARY = "https://en.wiktionary.org/api/rest_v1/page/definition/{palabra}"
	#: Wikimedia pide identificar el programa en el agente de usuario.
	AGENTE_WIKTIONARY = "TiresiasTraductorAvanzadoPro/1.0 (lector de pantalla Tiresias)"

	def _inicializar(self) -> None:
		self.ultimo_error: str | None = None

	def ejecutar(self, palabra: str = "", idioma: str = "en", *args: Any, **kwargs: Any) -> dict[str, Any] | None:
		if not palabra or not palabra.strip():
			return None
		palabra = palabra.strip().lower()
		self.ultimo_error = None
		url = self.ENDPOINT.format(idioma=urllib.parse.quote(idioma), palabra=urllib.parse.quote(palabra))
		try:
			datos = red.peticion_json(url, timeout=10)
		except red.ErrorRed as e:
			if e.codigo == 404:
				log.debug("Palabra no encontrada: %s", palabra)
				return None
			# El servicio no responde: se prueba Wiktionary.
			log.debug("Free Dictionary API: %s; se usa Wiktionary", e.mensaje)
			r = self.buscar_wiktionary(palabra, preferido=idioma)
			if r is None and self.ultimo_error is None:
				return None
			if r is None:
				self.ultimo_error = e.mensaje
			return r
		if datos and isinstance(datos, list):
			return self._procesar_resultado(datos)
		return None

	@staticmethod
	def _limpiar_html(texto: str) -> str:
		texto = re.sub(r"<style.*?</style>", "", texto or "", flags=re.S)
		texto = re.sub(r"<[^>]+>", "", texto)
		return " ".join(html.unescape(texto).split())

	def buscar_wiktionary(self, palabra: str, preferido: str = "en") -> dict[str, Any] | None:
		"""Definiciones de ``palabra`` en Wiktionary (en cualquier idioma)."""
		palabra = palabra.strip()
		if not palabra:
			return None
		self.ultimo_error = None
		url = self.ENDPOINT_WIKTIONARY.format(palabra=urllib.parse.quote(palabra.replace(" ", "_")))
		try:
			datos = red.peticion_json(url, cabeceras={"User-Agent": self.AGENTE_WIKTIONARY}, timeout=12)
		except red.ErrorRed as e:
			if e.codigo != 404:
				self.ultimo_error = e.mensaje
			return None
		if not isinstance(datos, dict) or not datos:
			return None
		orden = [preferido, self.configuracion.idioma_destino if self.configuracion else "", "en"]
		secciones = sorted(datos.items(), key=lambda kv: orden.index(kv[0]) if kv[0] in orden else len(orden))
		resultado: dict[str, Any] = {"palabra": palabra, "fonetica": "", "definiciones": [], "sinonimos": [], "antonimos": [], "ejemplos": []}
		for _codigo, entradas in secciones:
			for entrada in entradas if isinstance(entradas, list) else []:
				tipo = f"{entrada.get('partOfSpeech', '')}, {entrada.get('language', '')}".strip(", ")
				for d in entrada.get("definitions", []) or []:
					definicion = self._limpiar_html(d.get("definition", ""))
					if not definicion:
						continue
					ejemplos = [self._limpiar_html(e) for e in (d.get("examples") or []) if e]
					resultado["definiciones"].append({"tipo": tipo, "definicion": definicion, "ejemplo": ejemplos[0] if ejemplos else ""})
					resultado["ejemplos"].extend(ejemplos)
		return resultado if resultado["definiciones"] else None

	def _procesar_resultado(self, entradas: list[dict]) -> dict[str, Any]:
		primera = entradas[0] if entradas else {}
		resultado: dict[str, Any] = {"palabra": primera.get("word", ""), "fonetica": "", "definiciones": [], "sinonimos": [], "antonimos": [], "ejemplos": []}
		for datos in entradas:
			if not resultado["fonetica"]:
				for p in datos.get("phonetics", []) or []:
					if p.get("text"):
						resultado["fonetica"] = p["text"]
						break
				if not resultado["fonetica"] and datos.get("phonetic"):
					resultado["fonetica"] = datos["phonetic"]
			for significado in datos.get("meanings", []) or []:
				tipo = significado.get("partOfSpeech", "")
				for d in significado.get("definitions", []) or []:
					definicion = {"tipo": tipo, "definicion": d.get("definition", ""), "ejemplo": d.get("example", "")}
					resultado["definiciones"].append(definicion)
					if definicion["ejemplo"]:
						resultado["ejemplos"].append(definicion["ejemplo"])
					resultado["sinonimos"].extend(d.get("synonyms", []) or [])
					resultado["antonimos"].extend(d.get("antonyms", []) or [])
				resultado["sinonimos"].extend(significado.get("synonyms", []) or [])
				resultado["antonimos"].extend(significado.get("antonyms", []) or [])
		resultado["sinonimos"] = list(dict.fromkeys(resultado["sinonimos"]))
		resultado["antonimos"] = list(dict.fromkeys(resultado["antonimos"]))
		return resultado

	def buscar_sinonimos(self, palabra: str, idioma: str = "en") -> list[str]:
		r = self.ejecutar(palabra, idioma)
		return r.get("sinonimos", []) if r else []

	def obtener_texto_formateado(self, palabra: str, idioma: str = "en") -> str | None:
		r = self.ejecutar(palabra, idioma)
		if not r:
			return None
		return self.formatear(r)

	@staticmethod
	def formatear(r: dict[str, Any]) -> str:
		lineas = [f"=== {r['palabra'].upper()} ==="]
		if r["fonetica"]:
			lineas.append(f"Fonética: {r['fonetica']}")
		lineas += ["", "Definiciones:"]
		for i, d in enumerate(r["definiciones"][:8], 1):
			lineas.append(f"  {i}. [{d['tipo']}] {d['definicion']}")
			if d["ejemplo"]:
				lineas.append(f'     Ejemplo: "{d["ejemplo"]}"')
		if r["sinonimos"]:
			lineas += ["", "Sinónimos: " + ", ".join(r["sinonimos"][:10])]
		if r["antonimos"]:
			lineas.append("Antónimos: " + ", ".join(r["antonimos"][:10]))
		return "\n".join(lineas)

	def buscar_multilingue(self, palabra: str) -> tuple[str | None, str]:
		"""Busca ``palabra`` en cualquier idioma. Devuelve ``(texto, palabra en inglés)``.

		Si la palabra no es inglesa se traduce al inglés con el servicio activo;
		las definiciones se acompañan de su traducción al idioma de destino.
		"""
		palabra = palabra.strip()
		r = self.ejecutar(palabra, "en")
		if r is None:
			r = self.buscar_wiktionary(palabra, preferido=self._idioma_de(palabra))
		buscada = palabra
		principal = self.plugin_principal
		gestor = getattr(principal, "gestor_traductores", None) if principal else None
		traductor = gestor.obtener_traductor_activo() if gestor else None
		if r is None and traductor is not None:
			ingles = traductor.traducir(palabra, idioma_origen="auto", idioma_destino="en")
			if ingles and ingles.strip().lower() != palabra.lower():
				buscada = ingles.strip().split("\n")[0]
				r = self.ejecutar(buscada, "en")
		if r is None:
			return None, buscada
		texto = self.formatear(r)
		destino = self.configuracion.idioma_destino if self.configuracion else "en"
		if traductor is not None and destino and not destino.lower().startswith("en"):
			traduccion = traductor.traducir(texto, idioma_origen="en", idioma_destino=destino)
			if traduccion and traduccion.strip() and traduccion != texto:
				texto = f"{texto}\n\n=== Traducción ({destino}) ===\n{traduccion}"
		if buscada.lower() != palabra.lower():
			texto = f"«{palabra}» en inglés: {buscada}\n\n{texto}"
		return texto, buscada

	def _idioma_de(self, palabra: str) -> str:
		principal = self.plugin_principal
		gestor = getattr(principal, "gestor_plugins", None) if principal else None
		local = gestor.obtener_plugin("detector_idioma") if gestor else None
		r = local.ejecutar(palabra) if local else None
		return r["idioma"] if r and r.get("confianza", 0) > 0.3 else "en"

	def obtener_comandos(self) -> dict[str, Callable]:
		return {"buscar_palabra": self.ejecutar, "obtener_sinonimos": self.buscar_sinonimos, "obtener_definicion": self.obtener_texto_formateado}
