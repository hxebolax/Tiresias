"""Puente entre el complemento y Tiresias (voz, braille, ventanas, teclas).

Equivale al ``utilidades/nvda.py`` del original. Todas las funciones son
seguras desde cualquier hilo: lo que debe ocurrir en el hilo del núcleo se
encola con ``queue_handler`` y lo que es de la interfaz con ``runOnGui``.
"""

from __future__ import annotations

import collections
import os
import time
from typing import Any

from tiresias import queue_handler
from tiresias.log import getLogger

log = getLogger("TraductorAvanzadoPro")

#: Hasta cuándo se silencia la voz (lo consulta el filtro de voz del complemento).
_silencio_hasta = 0.0
#: Mensajes recientes del complemento: el filtro de voz no los traduce ni los
#: toma como «último texto verbalizado».
mensajes_recientes: collections.deque[str] = collections.deque(maxlen=30)


def _en_nucleo(func, *args, **kwargs) -> None:
	if queue_handler.isCoreThread():
		try:
			func(*args, **kwargs)
		except Exception:
			log.exception("Error en %r", func)
	else:
		queue_handler.queueFunction(func, *args, **kwargs)


def mensaje(texto: str) -> None:
	"""Mensaje del complemento (voz en el idioma de la interfaz y braille)."""
	if not texto:
		return
	from tiresias import speech

	mensajes_recientes.append(texto)
	_en_nucleo(speech.speakMessage, texto)


def es_mensaje_propio(texto: str) -> bool:
	return texto in mensajes_recientes


def hablar_texto(texto: str, siguiente: bool = False) -> None:
	"""Habla un texto (una traducción) y lo muestra en braille.

	A diferencia de :func:`mensaje`, no fuerza el idioma de la interfaz: así la
	detección de idioma de Tiresias puede leer la traducción con la voz adecuada.
	``siguiente`` usa la prioridad «a continuación» (no interrumpe lo que se dice).
	"""
	if not texto:
		return

	def _hablar() -> None:
		from tiresias import speech

		prioridad = speech.Priority.NEXT if siguiente else speech.Priority.NORMAL
		speech.speak([texto], priority=prioridad)

	_en_nucleo(_hablar)
	braille(texto)


def braille(texto: str) -> None:
	"""Muestra ``texto`` en la línea braille (si hay una)."""

	def _mostrar() -> None:
		try:
			from tiresias import braille as br

			br.handler.message(texto)
		except Exception:
			log.debug("No se pudo mostrar en braille", exc_info=True)

	_en_nucleo(_mostrar)


def cancelar_voz() -> None:
	from tiresias import speech

	_en_nucleo(speech.cancelSpeech)


def silenciar_sintetizador(duracion: float, texto: str | None = None) -> None:
	"""Silencia la voz ``duracion`` segundos (por ejemplo, al pegar una traducción).

	No cambia el modo de voz guardado en la configuración: el filtro de voz del
	complemento descarta lo que se diga mientras dure el silencio.
	"""
	global _silencio_hasta
	if texto:
		mensaje(texto)
		time.sleep(0.1)
	_silencio_hasta = time.monotonic() + max(0.0, duracion)


def silenciado() -> bool:
	return time.monotonic() < _silencio_hasta


def mensaje_navegable(titulo: str, texto: str) -> None:
	"""Muestra ``texto`` en una ventana de solo lectura recorrible."""
	from tiresias import gui

	gui.showBrowseableMessage(texto, titulo)


def objeto_foco() -> Any:
	from tiresias import api

	return api.getFocusObject()


def objeto_navegador() -> Any:
	from tiresias import api

	return api.getNavigatorObject()


def objeto_cursor() -> Any:
	"""Objeto con el cursor del sistema (el documento en modo exploración)."""
	from tiresias import api

	return api.getCaretObject()


def app_actual() -> str:
	"""Nombre de la aplicación con el foco ("" si no se sabe)."""
	try:
		obj = objeto_foco()
		app = getattr(obj, "appModule", None) if obj is not None else None
		if app is None:
			from tiresias.appmodules import handler

			app = handler.getForegroundApp()
		return str(getattr(app, "appName", "") or "")
	except Exception:
		return ""


def enviar_teclas(nombre: str) -> None:
	"""Envía una combinación de teclas (``"control+v"``) a la aplicación."""

	def _enviar() -> None:
		from tiresias.input.gestures import sendKey

		sendKey(nombre)

	_en_nucleo(_enviar)


def abrir_url(url: str) -> None:
	"""Abre una dirección o un archivo con el programa predeterminado."""
	try:
		import wx

		if wx.LaunchDefaultBrowser(url):
			return
	except Exception:
		pass
	try:
		os.startfile(url)  # type: ignore[attr-defined]
	except OSError:
		log.exception("No se pudo abrir %s", url)


def nombre_idioma(codigo: str) -> str:
	"""Nombre de un idioma según Tiresias ("" si no lo conoce)."""
	try:
		from tiresias.speech import languages

		nombre = languages.languageName(codigo)
		if nombre and nombre.lower() != codigo.lower().replace("-", "_"):
			return nombre
	except Exception:
		pass
	return ""


def idioma_interfaz() -> str:
	"""Código de dos letras del idioma de la interfaz de Tiresias."""
	try:
		from tiresias.speech import languages

		return languages.base(languages.interfaceLanguage()) or "es"
	except Exception:
		return "es"
