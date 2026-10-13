"""Acceso al portapapeles de Windows (mediante Tiresias)."""

from __future__ import annotations


class MonitorPortapapeles:
	def __init__(self) -> None:
		self._ultimo_contenido: str | None = None

	def obtener_texto(self) -> str | None:
		try:
			from tiresias import api

			texto = api.getClipData()
		except Exception:
			return None
		if isinstance(texto, str) and texto:
			self._ultimo_contenido = texto
			return texto
		return None

	def establecer_texto(self, texto: str) -> bool:
		"""Copia ``texto`` (con el sonido de copia de Tiresias)."""
		if not texto:
			return False
		try:
			from tiresias import api

			ok = bool(api.copyToClip(texto))
		except Exception:
			return False
		if ok:
			self._ultimo_contenido = texto
		return ok

	def limpiar(self) -> bool:
		try:
			from tiresias import winapi

			ok = bool(winapi.setClipboardText(""))
		except Exception:
			return False
		if ok:
			self._ultimo_contenido = None
		return ok

	def tiene_texto(self) -> bool:
		texto = self.obtener_texto()
		return texto is not None and bool(texto.strip())

	@property
	def ultimo_contenido(self) -> str | None:
		return self._ultimo_contenido
