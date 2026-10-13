"""OCR con traducción: reconoce el texto del objeto navegador y lo traduce.

Usa el OCR de Tiresias (``tiresias.ocr``: Windows OCR o Tesseract, el motor
y el idioma elegidos en las Opciones de Tiresias). En el original, el texto
reconocido no llegaba a traducirse (llamaba a una función que no existía) y
acababa en el portapapeles; aquí se traduce y se muestra o se lee como
cualquier otra traducción.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from tiresias.log import getLogger

from ..nucleo.gestor_plugins import PluginBase, TipoPlugin
from ..utilidades import lector

log = getLogger("TraductorAvanzadoPro")


class PluginOCR(PluginBase):
	id = "ocr_traductor"
	nombre = "Traductor OCR"
	descripcion = "Realiza OCR sobre el objeto actual y traduce el texto detectado"
	tipo = TipoPlugin.SERVICIO
	version = "1.1.0"
	autor = "Traductor Avanzado Pro"

	def _rectangulo(self) -> tuple[Any, tuple[int, int, int, int] | None, int]:
		obj = lector.objeto_navegador() or lector.objeto_foco()
		if obj is None:
			return None, None, 0
		try:
			loc = obj.location
		except Exception:
			loc = None
		if not loc or len(loc) != 4 or loc[2] <= 0 or loc[3] <= 0:
			return obj, None, 0
		hwnd = 0
		try:
			from tiresias import winapi

			hwnd = winapi.getAncestor(obj.windowHandle, winapi.GA_ROOT) if obj.windowHandle else 0
		except Exception:
			hwnd = 0
		return obj, tuple(int(v) for v in loc), hwnd

	@staticmethod
	def reconocer(rect: tuple[int, int, int, int], hwnd: int = 0) -> str:
		"""Captura y reconoce ``rect`` (bloquea: usar en un hilo)."""
		from tiresias import imaging, ocr

		lineas = ocr.recognizeImage(imaging.captureRect(rect, hwnd))
		return "\n".join(ln.text for ln in lineas if ln.text.strip())

	def ejecutar(self, *args: Any, **kwargs: Any) -> str | None:
		"""Reconoce el objeto navegador en segundo plano y traduce el texto."""
		alAcabar: Callable[[str], None] | None = kwargs.get("callback")
		try:
			from tiresias import ocr

			if not ocr.getEngine().isAvailable():
				lector.mensaje("El reconocimiento de texto no está disponible: instale un idioma de OCR de Windows o Tesseract")
				return None
		except Exception:
			log.exception("Plugin OCR: no se pudo cargar el OCR de Tiresias")
			lector.mensaje("Sistema OCR no compatible")
			return None
		obj, rect, hwnd = self._rectangulo()
		if rect is None:
			lector.mensaje("No se puede determinar la ubicación del objeto")
			return None
		lector.mensaje("Realizando OCR...")

		def proceso() -> None:
			try:
				texto = self.reconocer(rect, hwnd)
			except Exception as e:
				log.exception("Plugin OCR: error en el reconocimiento")
				lector.mensaje(f"Error en el reconocimiento: {e}")
				return
			if not texto.strip():
				lector.mensaje("No se encontró texto")
				return
			if alAcabar:
				alAcabar(texto)
				return
			principal = self.plugin_principal
			if principal is not None and hasattr(principal, "_traducir_texto_largo"):
				principal._traducir_texto_largo(texto)
			else:
				from tiresias import api

				api.copyToClip(texto)
				lector.mensaje("OCR completado, texto copiado al portapapeles")

		threading.Thread(target=proceso, name="TraductorAvanzadoPro-OCR", daemon=True).start()
		return "OCR_INICIADO"

	def obtener_comandos(self) -> dict[str, Callable]:
		return {"traducir_ocr": self.ejecutar}
