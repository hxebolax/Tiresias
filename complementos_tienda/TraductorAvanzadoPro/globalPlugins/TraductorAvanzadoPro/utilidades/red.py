"""Peticiones HTTP del Traductor Avanzado Pro (solo biblioteca estándar).

Todas las conexiones de los traductores, diccionarios y listas de modelos
pasan por :func:`peticion`, que:

- verifica los certificados con el almacén de Windows (el original los
  desactivaba para todo el proceso de NVDA; aquí no se hace);
- descomprime las respuestas gzip y deflate;
- convierte los errores HTTP en :class:`ErrorRed` con el código y el cuerpo.

Las pruebas sustituyen :data:`_abrir` para simular las respuestas.
"""

from __future__ import annotations

import gzip
import http.cookiejar
import json
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
import zlib
from typing import Any, Callable

AGENTE = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"

#: Función que abre la petición (``urllib.request.urlopen``); se cambia en las pruebas.
_abrir: Callable[..., Any] = urllib.request.urlopen
_contexto: ssl.SSLContext | None = None


def _abrir_sesion(sesion: Any, req: urllib.request.Request, timeout: float) -> Any:
	"""Abre ``req`` con una sesión (cookies); las pruebas lo sustituyen."""
	return sesion.open(req, timeout=timeout)


def crear_sesion() -> urllib.request.OpenerDirector:
	"""Sesión HTTP que conserva las cookies (la usa el traductor web de Bing)."""
	return urllib.request.build_opener(
		urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
		urllib.request.HTTPSHandler(context=contexto_ssl()),
	)


class ErrorRed(Exception):
	"""Fallo de red o respuesta HTTP de error."""

	def __init__(self, mensaje: str, codigo: int | None = None, cuerpo: str = "") -> None:
		super().__init__(mensaje)
		self.mensaje = mensaje
		self.codigo = codigo
		self.cuerpo = cuerpo

	def mensaje_api(self) -> str:
		"""Mensaje de error que devuelve la API en JSON (``error.message``) o el texto."""
		try:
			datos = json.loads(self.cuerpo)
		except (ValueError, TypeError):
			return self.cuerpo.strip()[:300] or self.mensaje
		if isinstance(datos, dict):
			err = datos.get("error")
			if isinstance(err, dict) and err.get("message"):
				return str(err["message"])
			if isinstance(err, str):
				return err
			if datos.get("message"):
				return str(datos["message"])
		return self.mensaje


def contexto_ssl() -> ssl.SSLContext:
	global _contexto
	if _contexto is None:
		_contexto = ssl.create_default_context()
	return _contexto


def _descomprimir(datos: bytes, codificacion: str) -> bytes:
	codificacion = (codificacion or "").lower()
	if "gzip" in codificacion or datos[:2] == b"\x1f\x8b":
		try:
			return gzip.decompress(datos)
		except OSError:
			return datos
	if "deflate" in codificacion:
		try:
			return zlib.decompress(datos)
		except zlib.error:
			return zlib.decompress(datos, -zlib.MAX_WBITS)
	return datos


def peticion(
	url: str,
	datos: bytes | dict | list | None = None,
	cabeceras: dict[str, str] | None = None,
	metodo: str | None = None,
	timeout: float = 12,
	sesion: Any = None,
) -> bytes:
	"""Hace una petición y devuelve el cuerpo (bytes).

	``datos`` puede ser ``bytes`` o un objeto que se envía como JSON
	(``Content-Type: application/json``). ``sesion`` (de :func:`crear_sesion`)
	conserva las cookies entre peticiones. Lanza :class:`ErrorRed` si falla.
	"""
	heads = {"User-Agent": AGENTE, "Accept-Encoding": "gzip, deflate"}
	if isinstance(datos, (dict, list)):
		datos = json.dumps(datos, ensure_ascii=False).encode("utf-8")
		heads["Content-Type"] = "application/json"
	if cabeceras:
		heads.update(cabeceras)
	req = urllib.request.Request(url, data=datos, headers=heads, method=metodo)
	try:
		abierta = _abrir_sesion(sesion, req, timeout) if sesion is not None else _abrir(req, timeout=timeout, context=contexto_ssl())
		with abierta as resp:
			cuerpo = resp.read()
			info = getattr(resp, "headers", None) or getattr(resp, "info", lambda: {})()
			try:
				codif = info.get("Content-Encoding", "") if info else ""
			except Exception:
				codif = ""
			return _descomprimir(cuerpo, codif)
	except urllib.error.HTTPError as e:
		try:
			cuerpo = _descomprimir(e.read() or b"", e.headers.get("Content-Encoding", "") if e.headers else "").decode("utf-8", "replace")
		except Exception:
			cuerpo = ""
		raise ErrorRed(f"Error HTTP {e.code}: {e.reason}", e.code, cuerpo) from None
	except urllib.error.URLError as e:
		raise ErrorRed(f"Error de conexión: {e.reason}") from None
	except (socket.timeout, TimeoutError):
		raise ErrorRed("Tiempo de espera agotado") from None
	except ssl.SSLError as e:
		raise ErrorRed(f"Error SSL: {e}") from None
	except OSError as e:
		raise ErrorRed(f"Error de red: {e}") from None


def peticion_json(url: str, datos: Any = None, cabeceras: dict[str, str] | None = None, metodo: str | None = None, timeout: float = 12, sesion: Any = None) -> Any:
	"""Como :func:`peticion`, pero devuelve el JSON de la respuesta ya decodificado."""
	cuerpo = peticion(url, datos, cabeceras, metodo, timeout, sesion)
	try:
		return json.loads(cuerpo.decode("utf-8", "surrogatepass"))
	except ValueError as e:
		raise ErrorRed(f"Respuesta no válida: {e}") from None


def codificar_formulario(campos: dict[str, Any]) -> bytes:
	"""Cuerpo ``application/x-www-form-urlencoded``."""
	return urllib.parse.urlencode(campos, encoding="utf-8", errors="surrogatepass").encode("ascii")


def verificar_conexion_internet(url: str = "https://www.google.com", timeout: float = 5) -> bool:
	"""``True`` si se puede abrir ``url`` (no se lanza ninguna excepción)."""
	try:
		peticion(url, metodo="HEAD", timeout=timeout)
		return True
	except ErrorRed as e:
		# Una respuesta HTTP (aunque sea de error) demuestra que hay conexión.
		return e.codigo is not None


def realizar_solicitud_https(url: str, timeout: float = 30, headers: dict[str, str] | None = None, data: bytes | None = None, method: str = "GET") -> dict[str, Any]:
	"""Compatibilidad con el original: ``{'exito', 'datos', 'error'}``."""
	try:
		return {"exito": True, "datos": peticion(url, data, headers, method, timeout), "error": None}
	except ErrorRed as e:
		return {"exito": False, "datos": None, "error": e.mensaje}


def descargar_archivo(url: str, ruta_destino: str, callback_progreso: Callable[[float], None] | None = None) -> bool:
	"""Descarga ``url`` en ``ruta_destino`` informando del porcentaje."""
	req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
	try:
		with _abrir(req, timeout=60, context=contexto_ssl()) as resp, open(ruta_destino, "wb") as f:
			total = int(resp.headers.get("Content-Length") or 0)
			hecho = 0
			while True:
				bloque = resp.read(8192)
				if not bloque:
					break
				f.write(bloque)
				hecho += len(bloque)
				if callback_progreso and total:
					callback_progreso(hecho * 100.0 / total)
		return True
	except Exception:
		return False
