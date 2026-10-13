"""Detección del idioma de un texto con Google Translate."""

from __future__ import annotations

import threading
import urllib.parse
from typing import Any, Callable

from tiresias.log import getLogger

from ..nucleo.gestor_plugins import PluginBase, TipoPlugin
from ..utilidades import lector, red

log = getLogger("TraductorAvanzadoPro")


class PluginDetectorGoogle(PluginBase):
	id = "detector_google"
	nombre = "Detector de Idioma Google"
	descripcion = "Detecta el idioma de un texto utilizando Google Translate"
	tipo = TipoPlugin.SERVICIO
	version = "1.0.0"
	autor = "Traductor Avanzado Pro"

	def _inicializar(self) -> None:
		self.url_base = "https://translate.googleapis.com/translate_a/single"

	def detectar(self, texto: str) -> str | None:
		"""Código del idioma de ``texto`` o ``None`` (bloquea: usar en un hilo)."""
		texto = (texto or "")[:5000].strip()
		if not texto:
			return None
		params = urllib.parse.urlencode({"client": "gtx", "sl": "auto", "dt": "t", "q": texto, "tl": "en"}, encoding="utf-8", errors="surrogatepass")
		try:
			datos = red.peticion_json(f"{self.url_base}?{params}", timeout=10)
			if isinstance(datos, list) and len(datos) > 2 and datos[2]:
				return str(datos[2])
		except red.ErrorRed as e:
			log.debug("Detector de Google: %s; se prueba el servicio alternativo", e.mensaje)
		# Servicio alternativo de Google (el de la extensión del navegador).
		try:
			datos = red.peticion_json(
				"https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl=auto&tl=en",
				red.codificar_formulario({"q": texto[:1000]}),
				{"Content-Type": "application/x-www-form-urlencoded"},
				"POST",
				10,
			)
		except red.ErrorRed as e:
			log.error("Detector de Google: %s", e.mensaje)
			return None
		if isinstance(datos, list) and datos and isinstance(datos[0], list) and len(datos[0]) > 1 and datos[0][1]:
			return str(datos[0][1])
		return None

	def nombre_de(self, codigo: str) -> str:
		principal = self.plugin_principal
		if principal is not None and getattr(principal, "gestor_idiomas", None):
			return principal.gestor_idiomas.obtener_nombre_idioma(codigo)
		return lector.nombre_idioma(codigo) or codigo

	def ejecutar(self, *args: Any, **kwargs: Any) -> str | None:
		"""Detecta (en segundo plano) el idioma del texto dado o del seleccionado y lo anuncia."""
		texto = kwargs.get("texto") or (args[0] if args else None)
		alAcabar: Callable[[str | None], None] | None = kwargs.get("callback")
		if not texto:
			from ..utilidades.texto import obtener_texto_seleccionado

			res = obtener_texto_seleccionado()
			texto = res["texto"] if res["exito"] else ""
		if not texto:
			lector.mensaje("No hay texto seleccionado para detectar el idioma")
			return None
		lector.mensaje("Detectando idioma...")

		def proceso() -> None:
			codigo = self.detectar(texto)
			if codigo:
				lector.mensaje(f"Idioma detectado: {self.nombre_de(codigo)}")
			else:
				local = None
				principal = self.plugin_principal
				if principal is not None and getattr(principal, "gestor_plugins", None):
					local = principal.gestor_plugins.obtener_plugin("detector_idioma")
				resultado = local.ejecutar(texto) if local else None
				if resultado:
					lector.mensaje(f"No se pudo usar Google. Detección local: {resultado['nombre']}, confianza {int(resultado['confianza'] * 100)} %")
				else:
					lector.mensaje("No se pudo detectar el idioma")
			if alAcabar:
				alAcabar(codigo)

		threading.Thread(target=proceso, name="TraductorAvanzadoPro-Detector", daemon=True).start()
		return "DETECCION_INICIADA"

	def obtener_comandos(self) -> dict[str, Callable]:
		return {"detectar_idioma_google": self.ejecutar}
