"""Red, descargas y descompresión (solo biblioteca estándar).

La Audiocinemateca protege sus archivos con autenticación HTTP básica: cada
petición lleva la cabecera ``Authorization`` con el usuario y la contraseña
de la cuenta.
"""

from __future__ import annotations

import base64
import bz2
import gzip
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Callable

AGENTE = "Tiresias-Audiocinemateca/1.0"
TAM_BLOQUE = 64 * 1024


class Cancelado(Exception):
	"""La operación se canceló a petición del usuario."""


def hayInternet(host: str = "8.8.8.8", puerto: int = 53, tiempo: float = 3) -> bool:
	"""Comprueba si hay conexión a Internet (conecta con un servidor DNS público)."""
	try:
		with socket.create_connection((host, puerto), timeout=tiempo):
			return True
	except OSError:
		return False


def cabeceraAutenticacion(usuario: str, contrasena: str) -> str:
	credenciales = f"{usuario}:{contrasena}".encode("utf-8")
	return "Basic " + base64.b64encode(credenciales).decode("ascii")


#: Dominios a los que se envían el usuario y la contraseña (solo por https).
DOMINIOS_CONFIABLES = ("audiocinemateca.com",)


def hostConfiable(url: str) -> bool:
	"""``True`` si ``url`` es https y de la Audiocinemateca (o un subdominio)."""
	try:
		partes = urllib.parse.urlparse(url or "")
	except ValueError:
		return False
	host = (partes.hostname or "").lower().rstrip(".")
	if partes.scheme.lower() != "https" or not host:
		return False
	return any(host == d or host.endswith("." + d) for d in DOMINIOS_CONFIABLES)


def peticion(url: str, usuario: str = "", contrasena: str = "") -> urllib.request.Request:
	"""Petición con la autenticación solo para la Audiocinemateca por https.

	La cabecera va como «no redirigible»: urllib copia las cabeceras normales a
	cualquier dirección a la que redirija el servidor (también a otro dominio
	o a http), y la contraseña viajaría a terceros.
	"""
	req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
	if (usuario or contrasena) and hostConfiable(url):
		req.add_unredirected_header("Authorization", cabeceraAutenticacion(usuario, contrasena))
	return req


def abrir(url: str, usuario: str = "", contrasena: str = "", tiempo: float = 30):
	"""Abre ``url`` (con autenticación básica si se dan credenciales).

	Si el servidor redirige a otra dirección de la propia Audiocinemateca por
	https y esta pide credenciales (401), se repite una vez con la dirección final.
	"""
	try:
		return urllib.request.urlopen(peticion(url, usuario, contrasena), timeout=tiempo)
	except urllib.error.HTTPError as e:
		final = getattr(e, "url", None) or getattr(e, "filename", None) or ""
		if e.code == 401 and (usuario or contrasena) and final and final != url and hostConfiable(final):
			try:
				e.close()
			except Exception:
				pass
			return urllib.request.urlopen(peticion(final, usuario, contrasena), timeout=tiempo)
		raise


def mensajeError(error: BaseException | None) -> str:
	"""Texto en español para un error de red o de disco."""
	if error is None:
		return "No se pudo completar la operación."
	if isinstance(error, urllib.error.HTTPError):
		if error.code == 401:
			return "El usuario o la contraseña no son correctos (error 401)."
		if error.code == 403:
			return "No tiene permiso para acceder a este contenido (error 403)."
		if error.code == 404:
			return "El archivo no existe en el servidor (error 404)."
		return f"El servidor respondió con el error {error.code}: {error.reason}."
	if isinstance(error, urllib.error.URLError):
		motivo = error.reason
		if isinstance(motivo, socket.timeout) or "timed out" in str(motivo):
			return "El servidor no respondió a tiempo."
		return f"No se pudo conectar con el servidor: {motivo}."
	if isinstance(error, (socket.timeout, TimeoutError)):
		return "El servidor no respondió a tiempo."
	if isinstance(error, Cancelado):
		return "Operación cancelada."
	if isinstance(error, OSError) and error.strerror:
		return f"Error de disco o de red: {error.strerror}."
	return str(error) or error.__class__.__name__


def verificarLogin(usuario: str, contrasena: str, url: str | None = None) -> tuple[bool, str | None]:
	"""Comprueba las credenciales pidiendo un archivo protegido pequeño."""
	from . import ajustes

	try:
		with abrir(url or ajustes.URL_VERSION, usuario, contrasena, tiempo=20) as res:
			if res.status == 200:
				return True, None
			return False, f"Código de estado: {res.status}"
	except Exception as e:
		return False, mensajeError(e)


def nombreArchivoUrl(url: str) -> str:
	"""Nombre del archivo de una dirección, sin codificación de caracteres.

	Solo el último componente y sin separadores ni caracteres no válidos: un
	enlace con ``%2E%2E%5C`` («..\\») no puede escribir fuera de la carpeta de
	descargas. ``""`` si no queda un nombre válido.
	"""
	nombre = urllib.parse.unquote(urllib.parse.urlparse(url).path.split("/")[-1])
	nombre = nombre.replace("\\", "/").split("/")[-1]
	nombre = "".join("_" if c in '<>:"|?*' or ord(c) < 32 else c for c in nombre).strip(" .")
	if nombre in ("", ".", ".."):
		return ""
	return nombre


def esUrl(cadena: str) -> bool:
	try:
		r = urllib.parse.urlparse(cadena or "")
	except ValueError:
		return False
	return bool(r.scheme and r.netloc)


def descargar(
	url: str,
	destino: str,
	usuario: str = "",
	contrasena: str = "",
	progreso: Callable[[float], None] | None = None,
	cancelado: Callable[[], bool] | None = None,
) -> str:
	"""Descarga ``url`` en el archivo ``destino`` (se escribe primero como ``.part``).

	``progreso(porcentaje)`` se llama durante la descarga si se conoce el tamaño.
	Lanza :class:`Cancelado` si ``cancelado()`` devuelve verdadero.
	"""
	parcial = destino + ".part"
	try:
		with abrir(url, usuario, contrasena, tiempo=60) as res:
			total = int(res.headers.get("Content-Length") or 0)
			hecho = 0
			with open(parcial, "wb") as f:
				while True:
					if cancelado is not None and cancelado():
						raise Cancelado()
					bloque = res.read(TAM_BLOQUE)
					if not bloque:
						break
					f.write(bloque)
					hecho += len(bloque)
					if progreso is not None and total > 0:
						progreso(min(100.0, hecho * 100.0 / total))
		if total and hecho < total:
			raise OSError(0, "La descarga se interrumpió antes de terminar")
		os.replace(parcial, destino)
		return destino
	except BaseException:
		try:
			os.remove(parcial)
		except OSError:
			pass
		raise


def _descomprimir(abrirComprimido, origen: str, destino: str, progreso: Callable[[float], None] | None) -> None:
	total = os.path.getsize(origen)
	parcial = destino + ".part"
	try:
		with open(origen, "rb") as crudo, abrirComprimido(crudo) as comp, open(parcial, "wb") as salida:
			while True:
				bloque = comp.read(TAM_BLOQUE)
				if not bloque:
					break
				salida.write(bloque)
				if progreso is not None and total > 0:
					progreso(min(100.0, crudo.tell() * 100.0 / total))
		os.replace(parcial, destino)
	except BaseException:
		try:
			os.remove(parcial)
		except OSError:
			pass
		raise


def descomprimirBz2(origen: str, destino: str, progreso: Callable[[float], None] | None = None) -> None:
	_descomprimir(lambda f: bz2.BZ2File(f, "rb"), origen, destino, progreso)


def descomprimirGz(origen: str, destino: str, progreso: Callable[[float], None] | None = None) -> None:
	_descomprimir(lambda f: gzip.GzipFile(fileobj=f, mode="rb"), origen, destino, progreso)


def _fecha(v: dict) -> datetime:
	return datetime(int(v["year"]), int(v["mon"]), int(v["mday"]), int(v.get("hours", 0)), int(v.get("minutes", 0)), int(v.get("seconds", 0)))


def compararVersiones(local: dict | None, servidor: dict | None) -> bool:
	"""``True`` si la versión del servidor es más reciente que la local.

	Sin versión local (o ilegible) se considera que hay actualización.
	"""
	if not servidor:
		return False
	try:
		fServidor = _fecha(servidor)
	except Exception:
		return False
	try:
		fLocal = _fecha(local or {})
	except Exception:
		return True
	return fLocal < fServidor


MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def formatearVersion(version) -> str:
	"""Fecha legible de la versión de la base de datos («5 de marzo de 2026, 10:30»)."""
	if isinstance(version, dict):
		try:
			mes = int(version.get("mon", 0))
			nombreMes = MESES[mes - 1] if 1 <= mes <= 12 else str(mes)
			return f"{int(version.get('mday', 0))} de {nombreMes} de {int(version.get('year', 0))}, {int(version.get('hours', 0)):02d}:{int(version.get('minutes', 0)):02d}"
		except Exception:
			return str(version)
	return "desconocida" if not version else str(version)
