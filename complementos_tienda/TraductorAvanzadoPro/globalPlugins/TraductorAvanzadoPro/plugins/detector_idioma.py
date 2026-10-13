"""Detector de idioma local (sin conexión): alfabetos y palabras frecuentes.

Se usa cuando no se puede consultar a Google y desde otros plugins mediante
los comandos ``detectar_idioma`` y ``descripcion_idioma``.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from ..nucleo.gestor_plugins import PluginBase, TipoPlugin


class PluginDetectorIdioma(PluginBase):
	id = "detector_idioma"
	nombre = "Detector de Idioma"
	descripcion = "Detecta el idioma de un texto con información detallada"
	tipo = TipoPlugin.UTILIDAD
	version = "1.0.0"
	autor = "Traductor Avanzado Pro"

	PATRONES_IDIOMA = {
		"es": ["que", "de", "en", "la", "el", "es", "y", "un", "por", "con", "para", "los", "del", "una", "las", "se", "no"],
		"en": ["the", "is", "are", "and", "or", "to", "a", "in", "it", "of", "for", "on", "with", "this", "that", "you"],
		"fr": ["le", "la", "les", "de", "et", "est", "un", "une", "que", "pour", "dans", "avec", "des", "pas", "vous"],
		"de": ["der", "die", "das", "und", "ist", "von", "mit", "für", "auf", "nicht", "ein", "eine", "ich", "sie", "zu"],
		"it": ["che", "di", "il", "la", "e", "un", "per", "non", "sono", "con", "una", "gli", "della"],
		"pt": ["que", "de", "o", "a", "e", "em", "um", "uma", "para", "com", "não", "os", "as", "você", "do", "da"],
		"nl": ["de", "het", "een", "en", "van", "in", "is", "op", "te", "dat", "die", "niet", "ik"],
		"pl": ["i", "w", "nie", "na", "do", "to", "że", "się", "z", "jest", "jak"],
		"ru": ["и", "в", "не", "на", "с", "что", "это", "как", "но", "по", "для"],
	}

	CARACTERES_ESPECIALES = {
		"ja": "぀-ゟ゠-ヿ",
		"zh": "一-鿿",
		"ko": "가-힯ᄀ-ᇿ",
		"ar": "؀-ۿ",
		"he": "֐-׿",
		"el": "Ͱ-Ͽ",
		"ru": "Ѐ-ӿ",
		"th": "฀-๿",
		"hi": "ऀ-ॿ",
	}

	NOMBRES_RESPALDO = {
		"es": "Español",
		"en": "Inglés",
		"fr": "Francés",
		"de": "Alemán",
		"it": "Italiano",
		"pt": "Portugués",
		"ru": "Ruso",
		"zh": "Chino",
		"ja": "Japonés",
		"ko": "Coreano",
		"ar": "Árabe",
		"he": "Hebreo",
		"hi": "Hindi",
		"el": "Griego",
		"th": "Tailandés",
		"nl": "Neerlandés",
		"pl": "Polaco",
	}

	METODOS = {"caracteres": "por alfabeto", "patrones": "por palabras frecuentes"}

	def ejecutar(self, texto: str = "", *args: Any, **kwargs: Any) -> dict[str, Any] | None:
		if not texto or not texto.strip():
			return None
		texto = texto.strip().lower()
		especial = self._detectar_por_caracteres(texto)
		if especial:
			return {"idioma": especial, "nombre": self._obtener_nombre_idioma(especial), "confianza": 0.95, "metodo": "caracteres"}
		idioma, confianza = self._detectar_por_patrones(texto)
		return {"idioma": idioma, "nombre": self._obtener_nombre_idioma(idioma), "confianza": confianza, "metodo": "patrones"}

	def _detectar_por_caracteres(self, texto: str) -> str | None:
		letras = [c for c in texto if not c.isspace()]
		if not letras:
			return None
		compacto = "".join(letras)
		# El japonés usa también kanji (chinos): se mira antes el silabario.
		for idioma, rango in self.CARACTERES_ESPECIALES.items():
			coincidencias = len(re.findall(f"[{rango}]", compacto))
			if coincidencias and coincidencias / len(compacto) > 0.1:
				return idioma
		return None

	def _detectar_por_patrones(self, texto: str) -> tuple[str, float]:
		palabras = re.findall(r"\w+", texto)
		if not palabras:
			return ("en", 0.0)
		puntuaciones = {idioma: sum(1 for p in palabras if p in patrones) / len(palabras) for idioma, patrones in self.PATRONES_IDIOMA.items()}
		mejor = max(puntuaciones, key=puntuaciones.get)
		confianza = min(puntuaciones[mejor] * 5, 1.0)
		if confianza > 0.1:
			return (mejor, confianza)
		return ("en", 0.3)

	def _obtener_nombre_idioma(self, codigo: str) -> str:
		principal = self.plugin_principal
		if principal is not None and getattr(principal, "gestor_idiomas", None):
			return principal.gestor_idiomas.obtener_nombre_idioma(codigo)
		return self.NOMBRES_RESPALDO.get(codigo, codigo.upper())

	def obtener_descripcion_detallada(self, texto: str) -> str:
		r = self.ejecutar(texto)
		if not r:
			return "No se pudo detectar el idioma"
		return f"Idioma detectado: {r['nombre']} ({r['idioma']})\nConfianza: {int(r['confianza'] * 100)}%\nMétodo de detección: {self.METODOS.get(r['metodo'], r['metodo'])}"

	def obtener_comandos(self) -> dict[str, Callable]:
		return {"detectar_idioma": self.ejecutar, "descripcion_idioma": self.obtener_descripcion_detallada}
