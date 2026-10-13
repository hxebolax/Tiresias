"""Audio de una traducción con la voz de Google Translate (botón «Escuchar»).

Google devuelve MP3; los trozos de 200 caracteres se concatenan (los MP3 se
pueden unir trama a trama) y el resultado lo reproduce el reproductor del
complemento (``wx.media``).
"""

from __future__ import annotations

import random
import threading
import urllib.parse
from typing import Callable

from . import red


class GestorTTSGoogle:
	URL_BASE = "https://translate.google.com/translate_tts?ie=UTF-8&tl={idioma}&client=tw-ob&q={texto}"
	MAX_LONGITUD_PARTE = 200

	def __init__(self) -> None:
		self.detener_evento = threading.Event()
		self._error: str | None = None
		#: Pausa entre trozos (como el original, para no parecer un robot).
		self.pausa = (0.5, 1.5)

	def obtener_audio(self, texto: str, idioma: str, callback_progreso: Callable[[int], None] | None = None) -> bytes | None:
		"""Descarga el audio de ``texto`` (bloquea: usar en un hilo)."""
		self.detener_evento.clear()
		self._error = None
		partes = self._dividir_texto(texto)
		total = len(partes)
		audio = b""
		for i, parte in enumerate(partes):
			if self.detener_evento.is_set():
				self._error = "Operación cancelada"
				return None
			datos = self._descargar_parte(parte, idioma)
			if not datos:
				return None
			audio += datos
			if callback_progreso:
				try:
					callback_progreso(int((i + 1) * 100 / total))
				except Exception:
					pass
			if total > 1 and i < total - 1 and self.pausa[1] > 0:
				self.detener_evento.wait(random.uniform(*self.pausa))
		return audio

	def _dividir_texto(self, texto: str) -> list[str]:
		partes: list[str] = []
		actual = ""
		for palabra in texto.split():
			if len(actual) + len(palabra) + 1 <= self.MAX_LONGITUD_PARTE:
				actual = f"{actual} {palabra}" if actual else palabra
			else:
				if actual:
					partes.append(actual)
				# Una «palabra» más larga que el máximo (sin espacios) se corta.
				while len(palabra) > self.MAX_LONGITUD_PARTE:
					partes.append(palabra[: self.MAX_LONGITUD_PARTE])
					palabra = palabra[self.MAX_LONGITUD_PARTE :]
				actual = palabra
		if actual:
			partes.append(actual)
		return partes or [texto]

	def _descargar_parte(self, texto: str, idioma: str) -> bytes | None:
		codigo = (idioma or "en").replace("_", "-")
		if not codigo.lower().startswith("zh"):
			# DeepL usa «EN-GB», «PT-BR»...: Google solo necesita el idioma.
			codigo = codigo.split("-")[0].lower()
		url = self.URL_BASE.format(idioma=urllib.parse.quote(codigo), texto=urllib.parse.quote(texto))
		try:
			return red.peticion(url, timeout=20)
		except red.ErrorRed as e:
			self._error = e.mensaje
			return None

	def detener(self) -> None:
		self.detener_evento.set()

	@property
	def ultimo_error(self) -> str | None:
		return self._error
