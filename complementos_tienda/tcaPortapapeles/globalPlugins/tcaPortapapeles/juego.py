"""Modo juego: traduce y lee lo que los juegos copian al portapapeles.

El idioma de origen se detecta solo y se traduce al idioma elegido en las
opciones con el servicio gratuito de Google Translate (sin clave). Las
traducciones se hacen en un hilo propio, una detrás de otra, y se leen en
el mismo orden en que llegaron al portapapeles.
"""

from __future__ import annotations

import json
import queue
import ssl
import threading
import urllib.parse
import urllib.request
from typing import Callable

#: Servicio principal y alternativo de Google Translate.
URL_GOOGLE = "https://translate.googleapis.com/translate_a/single"
URL_ALTERNATIVA = "https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl=auto&tl={destino}"
AGENTE = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
TIEMPO_ESPERA = 10
#: Tamaño máximo de cada trozo que se envía a traducir.
TROZO = 3000
#: Textos esperando traducción como máximo (si se acumulan, se descartan los más antiguos).
MAX_COLA = 20

_contexto: ssl.SSLContext | None = None


def _ssl() -> ssl.SSLContext:
	global _contexto
	if _contexto is None:
		_contexto = ssl.create_default_context()
	return _contexto


def _abrir(req: urllib.request.Request):
	"""Abre la petición (las pruebas lo sustituyen: nunca se conectan a la red)."""
	return urllib.request.urlopen(req, timeout=TIEMPO_ESPERA, context=_ssl())


def _pedirJson(url: str, datos: bytes | None = None):
	cabeceras = {"User-Agent": AGENTE}
	if datos is not None:
		cabeceras["Content-Type"] = "application/x-www-form-urlencoded;charset=utf-8"
	req = urllib.request.Request(url, data=datos, headers=cabeceras)
	with _abrir(req) as r:
		return json.loads(r.read().decode("utf-8"))


def trozos(texto: str, tam: int = TROZO) -> list[str]:
	"""Divide ``texto`` en trozos de como mucho ``tam`` caracteres, cortando por líneas o espacios."""
	salida = []
	resto = texto
	while len(resto) > tam:
		corte = resto.rfind("\n", 0, tam)
		if corte < tam // 3:
			corte = resto.rfind(" ", 0, tam)
		if corte < tam // 3:
			corte = tam
		salida.append(resto[:corte])
		resto = resto[corte:]
	if resto:
		salida.append(resto)
	return salida


def _traducirTrozo(texto: str, destino: str) -> str:
	params = urllib.parse.urlencode({"client": "gtx", "sl": "auto", "tl": destino, "dt": "t", "dj": "1", "q": texto}, encoding="utf-8")
	try:
		datos = _pedirJson(f"{URL_GOOGLE}?{params}")
		frases = datos.get("sentences") if isinstance(datos, dict) else None
		if isinstance(frases, list):
			return "".join(str(f.get("trans", "")) for f in frases if isinstance(f, dict))
	except Exception:
		pass
	# Servicio alternativo (el de la extensión de Google para el navegador).
	datos = _pedirJson(URL_ALTERNATIVA.format(destino=urllib.parse.quote(destino)), urllib.parse.urlencode({"q": texto}).encode("utf-8"))
	partes = []
	if isinstance(datos, list):
		for e in datos:
			if isinstance(e, list) and e:
				partes.append(str(e[0]))
			elif isinstance(e, str):
				partes.append(e)
	if not partes:
		raise ValueError("Respuesta inesperada del servicio de traducción")
	return "".join(partes)


def traducir(texto: str, destino: str) -> str:
	"""Traduce ``texto`` (idioma detectado automáticamente) a ``destino``. Bloquea: usar en un hilo."""
	return "".join(_traducirTrozo(t, destino) for t in trozos(texto)).strip()


class Traductor(threading.Thread):
	"""Hilo que traduce los textos en orden y entrega cada resultado a ``entregar(original, traduccion)``.

	Si la traducción falla, ``traduccion`` es ``None``.
	"""

	def __init__(self, idioma: Callable[[], str], entregar: Callable[[str, str | None], None], traducirFn: Callable[[str, str], str] = traducir) -> None:
		super().__init__(name="TCA-Portapapeles-juego", daemon=True)
		self._idioma = idioma
		self._entregar = entregar
		self._traducir = traducirFn
		self._cola: queue.Queue[str | None] = queue.Queue()

	def pedir(self, texto: str) -> None:
		while self._cola.qsize() >= MAX_COLA:
			try:
				self._cola.get_nowait()
			except queue.Empty:
				break
		self._cola.put(texto)

	def detener(self) -> None:
		self._cola.put(None)

	def procesar(self, texto: str) -> None:
		try:
			resultado: str | None = self._traducir(texto, self._idioma())
		except Exception:
			from tiresias.log import getLogger

			getLogger("tcaPortapapeles").debug("No se pudo traducir en el modo juego", exc_info=True)
			resultado = None
		self._entregar(texto, resultado)

	def run(self) -> None:
		while True:
			texto = self._cola.get()
			if texto is None:
				return
			self.procesar(texto)
