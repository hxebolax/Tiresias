"""Comprobación, descarga y aplicación de las actualizaciones de Tiresias.

Orígenes de distribución (desde la 1.0.13)
------------------------------------------
Las actualizaciones y la tienda de complementos pueden salir de dos
orígenes oficiales, según la opción ``update.origin``
(«Origen de las actualizaciones y de la tienda»):

- ``ambos`` (por defecto): el servidor del proyecto y GitHub. Se consultan
  los dos a la vez; gana la versión más alta y, si es la misma, el servidor
  del proyecto (el preferido). Si un origen no responde se usa el otro sin
  molestar, y si falla una descarga se intenta en el otro.
- ``servidor``: solo el servidor del proyecto (:data:`DISTRIBUTION_URL`).
- ``github``: solo GitHub (:data:`GITHUB_REPO`), ver :func:`githubDistributionUrl`.
- ``propio``: solo el servidor que escribe el usuario en ``update.serverUrl``.

Por compatibilidad, una configuración anterior con ``update.serverUrl``
escrita y sin ``update.origin`` es un servidor propio, y la política
``distributionUrl`` (o ``updateUrl`` y ``addonCatalogUrl``, y las opciones
``update.checkUrl`` y ``addons.catalogUrl``) siguen mandando sobre todo lo
demás (:func:`currentOrigin`, :func:`updateOrigins`, :func:`catalogOrigins`).

En GitHub (``tools/publicar.py``)::

	releases/download/distribucion/actualizacion.json   manifiesto (URL absolutas)
	releases/download/distribucion/catalogo.json        catálogo sin complementos propietarios
	releases/download/v<versión>/...                    instalador, portable, código y .sha256
	releases/download/complementos/<id>-<versión>.tiresias-addon (y .sha256)

GitHub redirige cada descarga a otro dominio (``*.githubusercontent.com``):
``urllib`` sigue la redirección, :func:`openUrl` rechaza las que pasan de
``https`` a ``http`` y el SHA-256 se comprueba igual sobre lo descargado.

Servidor de distribución
------------------------
Todo lo publicado en el servidor del proyecto cuelga de una sola dirección
base, :data:`DISTRIBUTION_URL` (la puede sustituir un servidor propio:
la opción ``update.serverUrl`` o la política ``distributionUrl``)::

	<base>/actualizacion.json            manifiesto de actualización
	<base>/versiones.json                historial de versiones publicadas
	<base>/novedades.html                novedades
	<base>/descargas/<versión>/...       instalador, ZIP portable y código fuente
	<base>/complementos/catalogo.json    catálogo de la tienda

Lo genera ``tools/publicar.py`` (ver ``docs/publicacion.md``). Dentro de
los JSON del servidor las direcciones son **relativas al propio JSON** y se
resuelven con :func:`resolveUrl` (la carpeta se puede servir desde cualquier
dirección sin regenerarla); los de GitHub llevan direcciones absolutas.

Manifiesto (``actualizacion.json``)::

	{
		"format": "tiresias-actualizacion",
		"formatVersion": 1,
		"version": "1.0.2",
		"date": "2026-10-07",
		"url": "descargas/1.0.2/Tiresias-1.0.2-instalador.exe",
		"sha256": "…", "size": 123,
		"minWindows": "10.0.17763",
		"notes": "Novedades en pocas palabras",
		"notesUrl": "novedades.html",
		"portable": {"url": "descargas/1.0.2/Tiresias-1.0.2-portable.zip", "sha256": "…", "size": 123},
		"source": {"url": "descargas/1.0.2/Tiresias-1.0.2-codigo-fuente.zip", "sha256": "…", "size": 123},
		"channels": {"beta": { …los mismos campos… }}
	}

Lo de primer nivel es el canal estable; ``channels.beta`` (opcional) es el
canal de pruebas, que solo se ofrece con ``update.channel = "beta"``.
También vale una ruta de archivo o ``file://`` (útil en una red local).

Cómo se aplica una actualización
--------------------------------
- **Copia instalada**: se descarga el instalador y se ejecuta. Su Tiresias
  cierra la copia en ejecución y muestra el diálogo de instalación, que
  actualiza la carpeta conservando la configuración.
- **Copia portable**: se descarga el ZIP portable, se descomprime en la caché
  y se ejecuta el ``Tiresias.exe`` nuevo con ``--apply-update <carpeta>
  --wait-pid <pid>``. Esta copia se cierra; la nueva espera a que termine,
  sustituye los archivos del programa (con copia de seguridad para deshacer
  si algo falla), conserva la configuración y los complementos del usuario y
  vuelve a abrir Tiresias (ver :func:`installer.applyPortableUpdate`).
- **Desde el código**: se descarga el ZIP del código fuente y se abre su
  carpeta.

La descarga comprueba siempre el tamaño y el SHA-256. Las conexiones HTTPS
verifican el certificado del servidor con ``ssl.create_default_context``.

La comprobación automática (``update.autoCheck``, cada
``update.intervalHours`` horas) es discreta (#2257): si hay una versión
nueva se dice una frase corta, se muestra un globo en el área de
notificación y aparece «Instalar la actualización» en el menú Ayuda. Nunca
abre ventanas por sí sola. La comprobación manual (menú Ayuda) sí muestra un
diálogo con el resultado.

Todo el trabajo de red se hace en hilos propios: nunca en el núcleo ni en la
interfaz.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from typing import Callable

from . import APP_NAME, VERSION, paths
from .config import conf
from .config import policy as policyModule
from .i18n import _
from .log import getLogger

log = getLogger("updates")

#: ---------------------------------------------------------------------------
#: SERVIDOR DE DISTRIBUCIÓN DEL PROYECTO. De aquí salen todas sus direcciones:
#: manifiesto, catálogo de complementos, novedades y descargas. Vacía: esta
#: compilación no tiene distribución oficial (ni servidor ni GitHub): no se
#: comprueba nada y la tienda usa la copia local.
#: ---------------------------------------------------------------------------
DISTRIBUTION_URL = "https://xebolax.synology.me/Tiresias"

#: ---------------------------------------------------------------------------
#: GITHUB: segundo origen oficial (versiones de GitHub del repositorio).
#: Vacío: no se usa GitHub.
#: ---------------------------------------------------------------------------
GITHUB_URL = "https://github.com"
GITHUB_REPO = "hxebolax/Tiresias"
#: Versión fija con el manifiesto y el catálogo (se sustituyen en cada publicación).
GITHUB_DIST_TAG = "distribucion"
#: Versión fija con los paquetes de los complementos (``<id>-<versión>.tiresias-addon``).
GITHUB_ADDONS_TAG = "complementos"
#: Nombre del catálogo en la versión «distribucion» (los recursos no tienen carpetas).
GITHUB_CATALOG_FILE = "catalogo.json"

#: Valores de ``update.origin`` (en config/schema.py y config/validation.py).
ORIGIN_BOTH = "ambos"
ORIGIN_SERVER = "servidor"
ORIGIN_GITHUB = "github"
ORIGIN_OWN = "propio"
ORIGINS = (ORIGIN_BOTH, ORIGIN_SERVER, ORIGIN_GITHUB, ORIGIN_OWN)
#: Tiempo de espera de cada origen cuando se consultan varios a la vez.
ORIGIN_TIMEOUT = 10

#: Rutas relativas a la dirección base.
UPDATE_MANIFEST = "actualizacion.json"
VERSIONS_FILE = "versiones.json"
CATALOG_FILE = "complementos/catalogo.json"
NEWS_FILE = "novedades.html"
MANUAL_FILE = "manual/"
DOWNLOADS_DIR = "descargas"

MANIFEST_FORMAT = "tiresias-actualizacion"
#: Canales (las opciones ``update.serverUrl`` y ``update.channel`` están en config/schema.py).
CHANNELS = ("estable", "beta")

USER_AGENT = f"{APP_NAME}/{VERSION}"
TIMEOUT = 20


# ====================================================================== direcciones
def _userServerUrl() -> str:
	try:
		return str(conf["update"]["serverUrl"] or "").strip()
	except KeyError:
		return ""


def originSetting() -> str:
	"""Valor de la opción ``update.origin`` (``ambos`` si falta o no es válido)."""
	try:
		value = str(conf["update"]["origin"] or "")
	except KeyError:
		value = ""
	return value if value in ORIGINS else ORIGIN_BOTH


def currentOrigin() -> str:
	"""Origen en vigor: ``ambos``, ``servidor``, ``github`` o ``propio``.

	La política ``distributionUrl`` lo fija a ``propio``. Una configuración
	anterior a la 1.0.13 con ``update.serverUrl`` escrita (y la opción en su
	valor por defecto) también es ``propio``: así sigue funcionando igual.
	"""
	if policyModule.policy.url("distribution"):
		return ORIGIN_OWN
	value = originSetting()
	if value == ORIGIN_BOTH and _userServerUrl():
		return ORIGIN_OWN
	return value


def _join(base: str, rel: str) -> str:
	if "://" in base:
		return base + "/" + rel
	return os.path.join(base, *rel.split("/"))


def distributionUrl() -> str:
	"""Dirección base del servidor de distribución: el propio o el del proyecto ("" si no hay)."""
	own = policyModule.policy.url("distribution") or (_userServerUrl() if currentOrigin() == ORIGIN_OWN else "")
	return (own or DISTRIBUTION_URL or "").strip().rstrip("/")


def distributionFile(rel: str) -> str:
	"""Dirección de ``rel`` en el servidor de distribución ("" si no hay servidor)."""
	base = distributionUrl()
	if not base:
		return ""
	return _join(base, rel)


def githubRepoUrl(repo: str | None = None) -> str:
	"""Página del repositorio en GitHub ("" si no se usa GitHub)."""
	repo = GITHUB_REPO if repo is None else repo
	if not (GITHUB_URL and repo):
		return ""
	return f"{GITHUB_URL.rstrip('/')}/{repo.strip('/')}"


def githubAssetUrl(tag: str, name: str, repo: str | None = None) -> str:
	"""Dirección de descarga de un recurso de una versión de GitHub."""
	base = githubRepoUrl(repo)
	if not base:
		return ""
	return f"{base}/releases/download/{urllib.parse.quote(tag, safe='')}/{urllib.parse.quote(name, safe='')}"


def githubReleasePageUrl(tag: str, repo: str | None = None) -> str:
	"""Página de una versión de GitHub (con sus notas)."""
	base = githubRepoUrl(repo)
	return f"{base}/releases/tag/{urllib.parse.quote(tag, safe='')}" if base else ""


def githubDistributionUrl() -> str:
	"""Base de la versión fija «distribucion» de GitHub ("" si no se usa GitHub)."""
	base = githubRepoUrl()
	return f"{base}/releases/download/{GITHUB_DIST_TAG}" if base else ""


@dataclass(frozen=True)
class Origin:
	"""Un origen de distribución: de dónde se leen el manifiesto y el catálogo."""

	#: ``servidor`` (el del proyecto), ``github`` o ``propio``.
	kind: str
	#: Dirección base (para mostrarla); puede estar vacía con una dirección concreta.
	base: str = ""
	manifestUrl: str = ""
	catalogUrl: str = ""

	@property
	def label(self) -> str:
		"""Nombre para los mensajes («el servidor del proyecto», «GitHub»...)."""
		if self.kind == ORIGIN_SERVER:
			return _("el servidor del proyecto")
		if self.kind == ORIGIN_GITHUB:
			return _("GitHub")
		return _("el servidor propio")


def _serverOrigin(kind: str, base: str) -> Origin:
	return Origin(kind, base, _join(base, UPDATE_MANIFEST), _join(base, CATALOG_FILE))


def _githubOrigin() -> Origin | None:
	base = githubDistributionUrl()
	if not base:
		return None
	return Origin(ORIGIN_GITHUB, githubRepoUrl(), base + "/" + UPDATE_MANIFEST, base + "/" + GITHUB_CATALOG_FILE)


def distributionOrigins() -> list[Origin]:
	"""Orígenes de distribución según ``update.origin``, el preferido primero."""
	current = currentOrigin()
	if current == ORIGIN_OWN:
		own = (policyModule.policy.url("distribution") or _userServerUrl()).strip().rstrip("/")
		if own:
			return [_serverOrigin(ORIGIN_OWN, own)]
		# «Servidor propio» sin dirección: el del proyecto (como antes con la dirección vacía).
		current = ORIGIN_SERVER
	server = (DISTRIBUTION_URL or "").strip().rstrip("/")
	if not server:
		# Compilación sin distribución oficial: ni servidor ni GitHub.
		return []
	out: list[Origin] = []
	if current in (ORIGIN_BOTH, ORIGIN_SERVER):
		out.append(_serverOrigin(ORIGIN_SERVER, server))
	if current in (ORIGIN_BOTH, ORIGIN_GITHUB):
		gh = _githubOrigin()
		if gh is not None:
			out.append(gh)
	return out


def updateOrigins() -> list[Origin]:
	"""Orígenes del manifiesto de actualización. Una dirección concreta
	(política ``updateUrl`` u opción ``update.checkUrl``) manda sobre todo."""
	try:
		url = policyModule.policy.url("update") or conf["update"]["checkUrl"] or ""
	except KeyError:
		url = policyModule.policy.url("update")
	url = str(url or "").strip()
	if url:
		return [Origin(ORIGIN_OWN, "", url, "")]
	return [o for o in distributionOrigins() if o.manifestUrl]


def catalogOrigins() -> list[Origin]:
	"""Orígenes del catálogo de la tienda. Una dirección concreta
	(política ``addonCatalogUrl`` u opción ``addons.catalogUrl``) manda sobre todo."""
	try:
		url = policyModule.policy.url("addonCatalog") or conf["addons"]["catalogUrl"] or ""
	except KeyError:
		url = policyModule.policy.url("addonCatalog")
	url = str(url or "").strip()
	if url:
		return [Origin(ORIGIN_OWN, "", "", url)]
	return [o for o in distributionOrigins() if o.catalogUrl]


def describeOrigins(origins: list[Origin] | None = None) -> str:
	"""Frase con los orígenes en uso (para Opciones)."""
	origins = distributionOrigins() if origins is None else origins
	parts = [f"{o.label} ({o.base or o.manifestUrl or o.catalogUrl})" for o in origins]
	if not parts:
		return ""
	if len(parts) == 1:
		return _("Se consulta {origin}.").format(origin=parts[0])
	return _("Se consultan {first} y {second}; si los dos tienen la misma versión, se prefiere el primero.").format(first=", ".join(parts[:-1]), second=parts[-1])


def hasOfficialRepository() -> bool:
	"""``True`` si hay algún origen de distribución configurado."""
	return bool(distributionOrigins())


def projectPageUrl() -> str:
	"""Portada del proyecto en el origen preferido."""
	origins = distributionOrigins()
	if origins and origins[0].kind == ORIGIN_GITHUB:
		return githubRepoUrl()
	base = distributionUrl() if origins else ""
	return base + "/" if "://" in base else base


# ====================================================================== red
class UnsafeUrlError(ValueError):
	"""Un JSON publicado en la red indica una dirección que no se acepta."""


def resolveUrl(base: str, ref: str) -> str:
	"""Resuelve una dirección relativa (``complementos/x.tiresias-addon``) respecto a ``base``.

	Si ``base`` es una dirección de red (lo publicado en un servidor), ``ref``
	solo puede llevar a otra dirección ``https`` (o ``http`` si el propio JSON
	llegó por ``http``): nunca a archivos locales, carpetas compartidas
	(``\\\\servidor\\x``), ``file://`` ni otros esquemas, que además se
	saltarían la comprobación obligatoria del SHA-256. Lanza
	:class:`UnsafeUrlError` en ese caso. Con una ``base`` local (servidor
	propio escrito por el usuario) se admite cualquier ruta.
	"""
	if not ref:
		return ref
	if isRemoteUrl(base):
		return _resolveFromRemote(base, ref)
	if "://" in ref or os.path.isabs(ref):
		return ref
	if "://" in base:
		return urllib.parse.urljoin(base, ref)
	return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(base)), ref))


def _resolveFromRemote(base: str, ref: str) -> str:
	bad = UnsafeUrlError(_("Dirección no permitida en un archivo publicado en la red: {url}").format(url=ref))
	text = ref.strip()
	if "\\" in text or os.path.splitdrive(text)[0] or any(ord(c) < 32 for c in text):
		# Rutas de Windows, carpetas compartidas o caracteres de control.
		raise bad
	baseScheme = urllib.parse.urlparse(base).scheme.lower()
	resolved = urllib.parse.urljoin(base, text)
	parts = urllib.parse.urlparse(resolved)
	scheme = parts.scheme.lower()
	allowed = ("https",) if baseScheme == "https" else ("https", "http")
	if scheme not in allowed or not parts.hostname:
		raise bad
	return resolved


_sslContext: ssl.SSLContext | None = None


def sslContext() -> ssl.SSLContext:
	"""Contexto TLS que verifica el certificado y el nombre del servidor.

	``create_default_context`` carga en Windows los certificados raíz del
	sistema (almacenes «ROOT» y «CA»), también en la versión compilada.
	"""
	global _sslContext
	if _sslContext is None:
		ctx = ssl.create_default_context()
		ctx.minimum_version = ssl.TLSVersion.TLSv1_2
		_sslContext = ctx
	return _sslContext


def fileUrlPath(url: str) -> str:
	"""Ruta de una dirección ``file://``, también de un recurso de red
	(``file://servidor/compartida/x`` → ``\\\\servidor\\compartida\\x``)."""
	parts = urllib.parse.urlparse(url)
	path = urllib.request.url2pathname(parts.path)
	host = parts.netloc
	if host and host.lower() != "localhost":
		return "\\\\" + host + path
	return path


def isRemoteUrl(url: str) -> bool:
	"""``True`` para http, https y demás direcciones de red (no archivos locales)."""
	return "://" in url and not url.lower().startswith("file://")


def requireChecksum(url: str, sha256: str | None, what: str) -> None:
	"""Lo que se descarga de la red se comprueba siempre con su SHA-256."""
	if isRemoteUrl(url) and not (sha256 or "").strip():
		raise ValueError(_("El servidor no indica la suma de comprobación (SHA-256) de {what}: no se descarga por seguridad.").format(what=what))


def openUrl(url: str, timeout: float = TIMEOUT, noCache: bool = False):
	"""Abre una dirección web, ``file://`` o una ruta local."""
	if "://" not in url:
		return open(url, "rb")
	if url.lower().startswith("file://"):
		return open(fileUrlPath(url), "rb")
	headers = {"User-Agent": USER_AGENT}
	if noCache:
		# Los JSON cambian con cada publicación: que ningún intermediario dé una copia vieja.
		headers["Cache-Control"] = "no-cache"
		headers["Pragma"] = "no-cache"
	req = urllib.request.Request(url, headers=headers)
	if url.lower().startswith("https://"):
		resp = urllib.request.urlopen(req, timeout=timeout, context=sslContext())
		# urllib sigue las redirecciones (GitHub manda cada descarga a otro
		# dominio, *.githubusercontent.com), pero lo pedido por https nunca se
		# acepta si la redirección acaba en una dirección sin cifrar.
		final = resp.geturl() if hasattr(resp, "geturl") else url
		if isinstance(final, str) and not final.lower().startswith("https://"):
			resp.close()
			raise UnsafeUrlError(_("Redirección no permitida a una dirección sin cifrar: {url}").format(url=final))
		return resp
	return urllib.request.urlopen(req, timeout=timeout)


#: Reintentos ante cortes de conexión pasajeros (redes inestables, Wi-Fi...).
RETRIES = 3


def _isTransient(e: BaseException) -> bool:
	"""Corte de conexión que merece reintentar (no errores HTTP ni de certificado)."""
	import http.client
	import urllib.error

	if isinstance(e, urllib.error.HTTPError) or isinstance(e, ssl.SSLCertVerificationError):
		return False
	if isinstance(e, urllib.error.URLError):
		e = e.reason if isinstance(e.reason, BaseException) else e
	return isinstance(e, (ConnectionError, http.client.RemoteDisconnected, http.client.IncompleteRead, TimeoutError))


def _withRetries(func: Callable, url: str):
	for attempt in range(RETRIES):
		try:
			return func()
		except Exception as e:
			if "://" not in url or url.lower().startswith("file://") or attempt == RETRIES - 1 or not _isTransient(e):
				raise
			log.debug("Conexión cortada con %s (%s); se reintenta", url, e)
			time.sleep(0.5 * (attempt + 1))


def fetchJson(url: str, timeout: float = TIMEOUT) -> dict:
	def get() -> bytes:
		with openUrl(url, timeout, noCache=True) as resp:
			return resp.read(4 * 1024 * 1024)

	data = _withRetries(get, url)
	obj = json.loads(data.decode("utf-8-sig"))
	if not isinstance(obj, dict):
		raise ValueError("la respuesta no es un objeto JSON")
	return obj


def fetchAll(urls: list[str], timeout: float | None = None) -> list[tuple[dict | None, BaseException | None]]:
	"""Lee varios JSON a la vez (bloqueante). Devuelve ``(datos, error)`` en el mismo orden.

	Cada origen tiene su tiempo de espera; el que no termina a tiempo cuenta
	como fallo (su hilo, de fondo, se abandona).
	"""
	timeout = ORIGIN_TIMEOUT if timeout is None else timeout
	results: list[tuple[dict | None, BaseException | None]] = [(None, None)] * len(urls)
	done = [threading.Event() for _u in urls]

	def work(i: int, url: str) -> None:
		try:
			results[i] = (fetchJson(url, timeout), None)
		except BaseException as e:  # noqa: BLE001 - se informa al que llama
			results[i] = (None, e)
		finally:
			done[i].set()

	for i, url in enumerate(urls):
		threading.Thread(target=work, args=(i, url), name="Origen de distribución", daemon=True).start()
	deadline = time.monotonic() + 2 * timeout + 1
	out = []
	for i, url in enumerate(urls):
		if done[i].wait(max(0.0, deadline - time.monotonic())):
			out.append(results[i])
		else:
			out.append((None, TimeoutError(_("No responde: {url}").format(url=url))))
	return out


def download(
	url: str,
	dest: str,
	sha256: str | None = None,
	progress: Callable[[int, int], bool] | None = None,
	timeout: float = TIMEOUT,
	size: int = 0,
) -> str:
	"""Descarga ``url`` en ``dest`` comprobando el tamaño y el SHA-256 si se indican.

	``progress(descargado, total)`` puede devolver ``False`` para cancelar. Si
	la conexión se corta, se vuelve a empezar (hasta :data:`RETRIES` veces).
	"""
	return _withRetries(lambda: _download(url, dest, sha256, progress, timeout, size), url)


def _download(url: str, dest: str, sha256: str | None, progress: Callable[[int, int], bool] | None, timeout: float, size: int) -> str:
	os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
	tmp = dest + ".part"
	h = hashlib.sha256()
	done = 0
	damaged = _("El archivo descargado está dañado (la suma de comprobación no coincide)")
	with openUrl(url, timeout) as resp:
		try:
			total = int(resp.headers.get("Content-Length") or 0)
		except Exception:
			try:
				total = os.fstat(resp.fileno()).st_size
			except Exception:
				total = 0
		if size and total and total != size:
			raise ValueError(_("El servidor ofrece un archivo de tamaño distinto al publicado ({got} bytes en lugar de {want})").format(got=total, want=size))
		total = total or size
		try:
			with open(tmp, "wb") as f:
				while True:
					chunk = resp.read(65536)
					if not chunk:
						break
					f.write(chunk)
					h.update(chunk)
					done += len(chunk)
					if size and done > size:
						raise ValueError(damaged)
					if progress is not None and progress(done, total) is False:
						raise InterruptedError(_("Descarga cancelada"))
		except BaseException:
			_remove(tmp)
			raise
	if (size and done != size) or (sha256 and h.hexdigest().lower() != sha256.strip().lower()):
		_remove(tmp)
		raise ValueError(damaged)
	os.replace(tmp, dest)
	return dest


def _remove(path: str) -> None:
	try:
		os.remove(path)
	except OSError:
		pass


def fileSha256(path: str) -> str:
	h = hashlib.sha256()
	with open(path, "rb") as f:
		for chunk in iter(lambda: f.read(65536), b""):
			h.update(chunk)
	return h.hexdigest()


# ====================================================================== versiones
def versionTuple(v: str | None) -> tuple[int, ...]:
	parts = [int(p) for p in re.findall(r"\d+", str(v or ""))[:4]]
	return tuple(parts + [0] * (4 - len(parts)))


_PRERELEASE = re.compile(r"(?i)(?:[-.~]?)(alfa|alpha|a|beta|b|rc|pre)\.?(\d*)$")
_PRERELEASE_RANK = {"alfa": 0, "alpha": 0, "a": 0, "beta": 1, "b": 1, "pre": 2, "rc": 2}


def versionKey(v: str | None) -> tuple:
	"""Clave para ordenar versiones: ``1.1.0b1`` < ``1.1.0rc1`` < ``1.1.0``."""
	text = str(v or "").strip()
	m = _PRERELEASE.search(text)
	if m and re.search(r"\d", text[: m.start()]):
		base = text[: m.start()]
		pre = (0, _PRERELEASE_RANK[m.group(1).lower()], int(m.group(2) or 0))
	else:
		base = text
		pre = (1, 0, 0)
	nums = [int(p) for p in re.findall(r"\d+", base)[:4]]
	return tuple(nums + [0] * (4 - len(nums))) + pre


def compareVersions(a: str | None, b: str | None) -> int:
	ka, kb = versionKey(a), versionKey(b)
	return (ka > kb) - (ka < kb)


def windowsVersion() -> tuple[int, ...]:
	try:
		w = sys.getwindowsversion()
		return (w.major, w.minor, w.build, 0)
	except AttributeError:
		return (0, 0, 0, 0)


def isWindowsSupported(minWindows: str | None) -> bool:
	if not minWindows:
		return True
	return windowsVersion() >= versionTuple(minWindows)


# ====================================================================== actualizaciones
@dataclass
class UpdateInfo:
	version: str
	url: str
	sha256: str = ""
	notes: str = ""
	notesUrl: str = ""
	size: int = 0
	date: str = ""
	minWindows: str = ""
	channel: str = "estable"
	#: Paquete elegido para esta copia: ``installer``, ``portable`` o ``source``.
	package: str = "installer"
	#: Origen del que sale (``servidor``, ``github`` o ``propio``; vacío si no se sabe).
	origin: str = ""
	#: La misma versión y el mismo paquete en los demás orígenes (para reintentar la descarga).
	mirrors: list = field(default_factory=list)

	@property
	def supported(self) -> bool:
		return isWindowsSupported(self.minWindows)


def copyKind() -> str:
	"""``instalada``, ``portable`` o ``codigo`` (ejecución desde el código fuente)."""
	if not paths.FROZEN:
		return "codigo"
	return "instalada" if paths.isInstalledCopy() else "portable"


#: Paquete preferido para cada tipo de copia (y los de reserva). Una copia
#: portable solo se actualiza con el ZIP portable: el instalador crearía una
#: copia instalada aparte en lugar de actualizar la portable.
_PACKAGES = {
	"instalada": ("installer",),
	"portable": ("portable",),
	"codigo": ("source", "installer"),
}


def updateUrl() -> str:
	"""Dirección del manifiesto del origen preferido ("" si no hay ninguno)."""
	origins = updateOrigins()
	return origins[0].manifestUrl if origins else ""


def _noUrlMessage() -> str:
	return _("No hay dirección para buscar actualizaciones. Escriba la del servidor en Opciones, categoría «Actualizaciones y complementos».")


def isEnabled() -> bool:
	return policyModule.isAllowed("updateCheck")


def currentChannel() -> str:
	ch = str(conf["update"]["channel"] or "estable")
	return ch if ch in CHANNELS else "estable"


def _candidates(data: dict, channel: str) -> list[tuple[str, dict]]:
	out = [("estable", data)]
	if channel == "beta":
		beta = (data.get("channels") or {}).get("beta")
		if isinstance(beta, dict) and beta.get("version"):
			out.append(("beta", beta))
	return out


def _packageFor(entry: dict, kind: str) -> tuple[str, dict]:
	for name in _PACKAGES.get(kind, ("installer",)):
		if name == "installer":
			pkg = entry.get("installer") if isinstance(entry.get("installer"), dict) else entry
		else:
			pkg = entry.get(name)
		if isinstance(pkg, dict) and pkg.get("url"):
			return name, pkg
	if "installer" not in _PACKAGES.get(kind, ("installer",)):
		# Sin el paquete propio de esta copia: no hay nada que descargar.
		return _PACKAGES[kind][0], {}
	return "installer", entry


def parseUpdate(data: dict, baseUrl: str = "", channel: str | None = None, kind: str | None = None, current: str = VERSION) -> UpdateInfo | None:
	"""Información de la versión publicada si es más reciente que ``current``."""
	if data.get("format") not in (None, MANIFEST_FORMAT):
		raise ValueError(_("El archivo no es un manifiesto de actualización de Tiresias"))
	channel = channel or currentChannel()
	kind = kind or copyKind()
	best: tuple[str, dict] | None = None
	for name, entry in _candidates(data, channel):
		if not entry.get("version"):
			continue
		if best is None or versionKey(entry["version"]) > versionKey(best[1]["version"]):
			best = (name, entry)
	if best is None or versionKey(best[1]["version"]) <= versionKey(current):
		return None
	name, entry = best
	package, pkg = _packageFor(entry, kind)
	try:
		size = int(pkg.get("size") or 0)
	except (TypeError, ValueError):
		size = 0
	# Una dirección de descarga no permitida invalida el manifiesto (UnsafeUrlError).
	url = resolveUrl(baseUrl, str(pkg.get("url") or ""))
	try:
		notesUrl = resolveUrl(baseUrl, str(entry.get("notesUrl") or data.get("notesUrl") or ""))
	except UnsafeUrlError as e:
		log.warning("%s", e)
		notesUrl = ""
	return UpdateInfo(
		version=str(entry["version"]),
		url=url,
		sha256=str(pkg.get("sha256") or ""),
		notes=str(entry.get("notes") or ""),
		notesUrl=notesUrl,
		size=size,
		date=str(entry.get("date") or ""),
		minWindows=str(entry.get("minWindows") or data.get("minWindows") or ""),
		channel=name,
		package=package,
	)


def checkForUpdate(url: str | None = None) -> UpdateInfo | None:
	"""Comprueba (bloqueante: llamar desde un hilo propio).

	Con varios orígenes (:func:`updateOrigins`) los consulta a la vez y elige
	la versión más alta del canal; si es la misma, la del origen preferido
	(el primero), y guarda las demás en ``mirrors`` para reintentar la
	descarga. Un origen que no responde o publica algo no válido se ignora
	(queda en el registro); solo si fallan todos se lanza el error.
	"""
	origins = [Origin(ORIGIN_OWN, "", url, "")] if url else updateOrigins()
	if not origins:
		raise ValueError(_noUrlMessage())
	if len(origins) == 1:
		# Un solo origen: los errores llegan tal cual (como antes de la 1.0.13).
		results: list[tuple[dict | None, BaseException | None]] = [(fetchJson(origins[0].manifestUrl), None)]
	else:
		results = fetchAll([o.manifestUrl for o in origins])
	found: list[tuple[int, UpdateInfo]] = []
	errors: list[tuple[Origin, BaseException]] = []
	answered = 0
	for i, (origin, (data, error)) in enumerate(zip(origins, results)):
		info = None
		if error is None and data is not None:
			try:
				info = parseUpdate(data, origin.manifestUrl)
			except Exception as e:
				error = e
		if error is not None or data is None:
			if len(origins) == 1:
				raise error if error is not None else ValueError(_noUrlMessage())
			errors.append((origin, error or ValueError("?")))
			log.info("Actualizaciones: no se pudo consultar %s (%s): %s", origin.label, origin.manifestUrl, error)
			continue
		answered += 1
		log.info(
			"Actualizaciones (%s): publicada la %s, esta es la %s%s",
			origin.manifestUrl,
			data.get("version") or "?",
			VERSION,
			f"; disponible la {info.version} ({info.channel})" if info else "",
		)
		if info is not None:
			info.origin = origin.kind
			found.append((i, info))
	if not answered:
		raise ConnectionError(
			_("No se pudo consultar ningún origen de actualizaciones: {detail}").format(detail="; ".join(f"{o.label}: {e}" for o, e in errors))
		)
	try:
		# Estado del programa, no del perfil activo (que podría ser el de una aplicación).
		conf.setGlobal("update", "lastCheck", int(time.time()))
	except Exception:
		pass
	if not found:
		return None
	# La versión más alta; con la misma, el origen preferido (el de menor índice).
	found.sort(key=lambda t: (versionKey(t[1].version), -t[0]), reverse=True)
	best = found[0][1]
	best.mirrors = [
		other
		for _i, other in found[1:]
		if versionKey(other.version) == versionKey(best.version) and other.package == best.package and other.url and other.sha256
	]
	if len(origins) > 1:
		log.info("Actualizaciones: se ofrece la %s de %s%s", best.version, best.origin, f" (también en {', '.join(m.origin for m in best.mirrors)})" if best.mirrors else "")
	return best


#: Actualización encontrada y aún no instalada (para el menú Ayuda).
pendingUpdate: UpdateInfo | None = None
_checking = threading.Lock()
#: Se pidió una comprobación manual mientras había otra en curso.
_manualWaiting = False


def checkNow(manual: bool = False) -> None:
	"""Comprueba en segundo plano. ``manual``: muestra siempre el resultado."""
	from . import gui, speech

	if not isEnabled():
		if manual:
			gui.messageBox(policyModule.blockedMessage(), _("Buscar actualización"))
		return
	if not updateUrl():
		# Sin dirección: la automática no hace nada ni deja mensajes; la manual
		# explica dónde escribir una.
		if manual:
			gui.runOnGui(gui.messageBox, _noUrlMessage(), _("Buscar actualización"))
		return
	global _manualWaiting
	if not _checking.acquire(blocking=False):
		if manual:
			# La comprobación en curso (quizá la automática) mostrará el resultado.
			_manualWaiting = True
			speech.speakMessage(_("Ya se está buscando una actualización"))
		return
	_manualWaiting = manual
	if manual:
		speech.speakMessage(_("Buscando actualizaciones..."))

	def run() -> None:
		global pendingUpdate
		try:
			info = checkForUpdate()
			error = None
		except Exception as e:
			log.info("No se pudo comprobar si hay actualizaciones: %s", e)
			info, error = None, e
		finally:
			showResult = manual or _manualWaiting
			_checking.release()
		skipped = info is not None and not showResult and info.version == conf["update"]["skippedVersion"]
		if info is not None and info.supported and not skipped:
			# Una versión omitida no vuelve a ofrecerse en el menú Ayuda salvo que se busque a mano.
			pendingUpdate = info
		if showResult:
			gui.runOnGui(_showResult, info, error)
		elif info is not None and info.supported and info.version != conf["update"]["skippedVersion"]:
			_notifyDiscreetly(info)

	threading.Thread(target=run, name="Actualizaciones", daemon=True).start()


def _notifyDiscreetly(info: UpdateInfo) -> None:
	from . import gui, queue_handler, speech

	msg = _("Hay una versión nueva de {app}: {version}. Puede instalarla desde el menú Ayuda.").format(app=APP_NAME, version=info.version)
	queue_handler.queueFunction(speech.speakMessage, _("Actualización de {app} disponible").format(app=APP_NAME))
	gui.runOnGui(gui.showTrayNotification, _("Actualización disponible"), msg)


def _showResult(info: UpdateInfo | None, error: Exception | None) -> None:
	from . import gui

	if error is not None:
		gui.messageBox(_("No se pudo comprobar si hay actualizaciones: {error}").format(error=error), _("Buscar actualización"))
		return
	if info is None:
		gui.messageBox(_("Tiene la versión más reciente de {app} ({version}).").format(app=APP_NAME, version=VERSION), _("Buscar actualización"))
		return
	if not info.supported:
		gui.messageBox(
			_("Hay una versión nueva de {app} ({version}), pero necesita Windows {minWindows} o posterior.").format(app=APP_NAME, version=info.version, minWindows=info.minWindows),
			_("Buscar actualización"),
		)
		return
	gui.showUpdateDialog(info)


# ====================================================================== automática
_scheduler: threading.Thread | None = None
_stop = threading.Event()


def _due() -> bool:
	sec = conf["update"]
	if not sec["autoCheck"] or not isEnabled() or not updateUrl():
		return False
	last = int(sec["lastCheck"] or 0)
	return time.time() - last >= max(1, int(sec["intervalHours"])) * 3600


def scheduleAutomaticChecks(firstDelay: float = 60.0) -> None:
	"""Comprueba en segundo plano cuando toca (se revisa cada hora)."""
	global _scheduler
	reportApplyResult()
	if _scheduler is not None or not isEnabled():
		return

	def loop() -> None:
		if _stop.wait(firstDelay):
			return
		while True:
			try:
				if _due():
					checkNow(manual=False)
			except Exception:
				log.exception("Error en la comprobación automática")
			if _stop.wait(3600):
				return

	_scheduler = threading.Thread(target=loop, name="Actualizaciones automáticas", daemon=True)
	_scheduler.start()


def stop() -> None:
	_stop.set()


# ====================================================================== descarga y aplicación
def downloadDir() -> str:
	return os.path.join(paths.cacheDir(), "actualizaciones")


def _cleanDownloadDir(keep: str = "") -> None:
	folder = downloadDir()
	if not os.path.isdir(folder):
		return
	for name in os.listdir(folder):
		p = os.path.join(folder, name)
		if keep and os.path.normcase(p) == os.path.normcase(keep):
			continue
		if os.path.isdir(p):
			shutil.rmtree(p, ignore_errors=True)
		else:
			_remove(p)


def downloadUpdate(info: UpdateInfo, progress: Callable[[int, int], bool] | None = None) -> str:
	"""Descarga el paquete de ``info`` en la caché (bloqueante), con tamaño y SHA-256.

	Si falla y otro origen publica la misma versión (``info.mirrors``), se
	intenta allí; cada descarga se comprueba con su propio SHA-256. Si fallan
	todas, se lanza el error del origen preferido. Cancelar no reintenta.
	"""
	try:
		return _downloadUpdateFrom(info, progress)
	except InterruptedError:
		raise
	except Exception as first:
		if not info.mirrors:
			raise
		for alt in info.mirrors:
			log.warning("No se pudo descargar la versión %s de %s (%s); se intenta en %s", info.version, info.origin or info.url, first, alt.origin or alt.url)
			try:
				return _downloadUpdateFrom(alt, progress)
			except InterruptedError:
				raise
			except Exception as e:
				log.warning("Tampoco se pudo descargar de %s: %s", alt.origin or alt.url, e)
		raise first


def _downloadUpdateFrom(info: UpdateInfo, progress: Callable[[int, int], bool] | None = None) -> str:
	if not info.url:
		if info.package == "portable":
			raise ValueError(
				_("La versión {version} no tiene paquete para copias portables. Descárguela desde la página del proyecto.").format(version=info.version)
			)
		raise ValueError(_("El manifiesto no indica dónde descargar la versión {version}").format(version=info.version))
	requireChecksum(info.url, info.sha256, _("la versión {version}").format(version=info.version))
	raw = urllib.parse.unquote(urllib.parse.urlparse(info.url).path) if "://" in info.url else info.url
	# El nombre se limpia después de descodificarlo: «%2F..%2F» no sale de la carpeta.
	name = re.sub(r"[^\w.-]", "_", os.path.basename(raw.replace("\\", "/"))) or f"Tiresias-{info.version}.exe"
	dest = os.path.join(downloadDir(), name)
	_cleanDownloadDir()
	return download(info.url, dest, info.sha256 or None, progress, size=info.size)


def applyMessage(path: str) -> str:
	"""Qué va a pasar al aplicar ``path`` (para decirlo antes de hacerlo)."""
	if path.lower().endswith(".exe"):
		return _("Descarga terminada. Se abre el instalador.")
	if path.lower().endswith(".zip") and copyKind() == "portable":
		return _("Descarga terminada. {app} se cerrará, se actualizará y volverá a abrirse en unos segundos.").format(app=APP_NAME)
	return _("Descarga terminada. Se abre la carpeta con el archivo descargado.")


def preparePackage(path: str) -> str | None:
	"""Trabajo lento antes de aplicar (bloqueante, en un hilo propio): descomprime
	el ZIP portable y devuelve su carpeta. ``None`` si no hace falta."""
	if path.lower().endswith(".zip") and copyKind() == "portable":
		try:
			return extractPortable(path)
		except zipfile.BadZipFile:
			raise ValueError(_("El paquete de actualización no es válido")) from None
	return None


def installDownloaded(path: str, prepared: str | None = None) -> None:
	"""Aplica el paquete descargado según el tipo de copia (``prepared``: lo de :func:`preparePackage`)."""
	if path.lower().endswith(".exe"):
		# El instalador cierra esta copia y actualiza la carpeta instalada.
		os.startfile(path)
	elif path.lower().endswith(".zip") and copyKind() == "portable":
		startPortableUpdate(path, prepared)
	else:
		# Código fuente (o paquete que no se puede aplicar solo): se abre su carpeta.
		os.startfile(os.path.dirname(path))


#: Tamaño máximo del ZIP portable descomprimido (protege de las «bombas ZIP»).
MAX_PORTABLE_UNCOMPRESSED = 2 * 1024**3


def extractPortable(zipPath: str, dest: str | None = None) -> str:
	"""Descomprime el ZIP portable y devuelve la carpeta que contiene ``Tiresias.exe``."""
	dest = dest or os.path.splitext(zipPath)[0]
	shutil.rmtree(dest, ignore_errors=True)
	root = os.path.abspath(dest)
	with zipfile.ZipFile(zipPath) as z:
		infos = z.infolist()
		for member in infos:
			target = os.path.abspath(os.path.join(root, member.filename))
			if not (target == root or target.startswith(root + os.sep)):
				raise ValueError(_("El paquete de actualización no es válido"))
		# zipfile no escribe más de lo que declara cada entrada: basta con sumarlo.
		if sum(m.file_size for m in infos) > MAX_PORTABLE_UNCOMPRESSED:
			raise ValueError(_("El paquete de actualización es demasiado grande al descomprimirlo"))
		z.extractall(root)
	for folder in (root, os.path.join(root, APP_NAME)):
		if os.path.isfile(os.path.join(folder, "Tiresias.exe")):
			return folder
	for name in os.listdir(root):
		folder = os.path.join(root, name)
		if os.path.isfile(os.path.join(folder, "Tiresias.exe")):
			return folder
	raise ValueError(_("El paquete de actualización no contiene Tiresias.exe"))


def startPortableUpdate(zipPath: str, newDir: str | None = None) -> None:
	"""Prepara la versión nueva, la lanza para que actualice esta carpeta y cierra Tiresias."""
	from . import core

	newDir = newDir or extractPortable(zipPath)
	exe = os.path.join(newDir, "Tiresias.exe")
	cmd = [exe, "--apply-update", paths.APP_DIR, "--wait-pid", str(os.getpid())]
	log.info("Actualización portable: %s", " ".join(cmd))
	subprocess.Popen(cmd, cwd=newDir, close_fds=True)
	# El guardián no relanza el otro lector ni retiene los archivos: termina enseguida.
	from .coexist import guardian

	guardian.setExitKind("update")
	core.requestQuit()


RESULT_FILE = "actualizacion_resultado.json"


def reportApplyResult() -> None:
	"""Tras una actualización portable fallida, lo dice al arrancar (el éxito lo dicen las novedades)."""
	path = os.path.join(paths.DATA_DIR, RESULT_FILE)
	if not os.path.isfile(path):
		return
	try:
		with open(path, encoding="utf-8") as f:
			result = json.load(f)
	except (OSError, ValueError):
		result = {}
	_remove(path)
	if result.get("ok", True):
		return
	from . import gui, queue_handler, speech

	msg = _("No se pudo actualizar {app} a la versión {version}: {error}. Se mantiene la versión {current}.").format(
		app=APP_NAME, version=result.get("version") or "?", error=result.get("error") or "?", current=VERSION
	)
	log.warning(msg)
	queue_handler.queueFunction(speech.speakMessage, _("No se pudo aplicar la actualización"))
	gui.runOnGui(gui.messageBox, msg, _("Actualización de {app}").format(app=APP_NAME))
