"""Tienda de complementos: catálogo en línea, instalación y actualizaciones.

El catálogo es un JSON (``addons.catalogUrl``, la URL que fije la política
o ``complementos/catalogo.json`` del servidor de distribución, ver
:func:`updates.distributionUrl`)::

	{
		"format": "tiresias-catalogo",
		"version": 1,
		"addons": [
			{
				"id": "whatsapp",
				"name": "WhatsApp accesible",
				"version": "1.0.0",
				"author": "Proyecto Tiresias",
				"description": "…",
				"minApiVersion": "1.0",
				"lastTestedApiVersion": "1.0",
				"url": "complementos/whatsapp.tiresias-addon",
				"sha256": "…",
				"size": 14041,
				"homepage": "",
				"changelog": "Qué ha cambiado en esta versión"
			}
		]
	}

Los campos de primer nivel describen la versión más reciente; ``versions``
(opcional) guarda todas las publicadas, y la tienda ofrece la más reciente
que sea compatible con esta versión de Tiresias.

Las direcciones relativas se resuelven respecto al catálogo en línea. Si no
está disponible se usa la copia que acompaña al programa
(``docs/catalogo_complementos.json``), con las direcciones resueltas también
respecto al catálogo en línea.

Varios orígenes (desde la 1.0.13, ver :func:`updates.catalogOrigins`): con
el servidor del proyecto y GitHub se leen los dos catálogos a la vez y se
combinan por identificador (:func:`mergeCatalogs`): gana la versión más alta
y, si es la misma, el origen preferido (el servidor del proyecto). Así los
complementos que solo están en el servidor (los propietarios, que nunca se
publican en GitHub) siguen apareciendo. Si la descarga de un complemento
falla y otro origen tiene el mismo paquete (el mismo SHA-256), se descarga
de allí (:func:`downloadPackage`).
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field
from typing import Callable

from . import API_VERSION, addons, paths, updates
from .config import conf
from .config import policy as policyModule
from .i18n import _
from .log import getLogger

log = getLogger("addonStore")

CATALOG_FORMAT = "tiresias-catalogo"


@dataclass
class CatalogEntry:
	id: str
	name: str
	version: str
	author: str = ""
	description: str = ""
	minApiVersion: str = "1.0"
	lastTestedApiVersion: str = "1.0"
	url: str = ""
	sha256: str = ""
	size: int = 0
	homepage: str = ""
	changelog: str = ""
	extra: dict = field(default_factory=dict)
	#: Origen del que sale (``servidor``, ``github`` o ``propio``; vacío si no se sabe).
	origin: str = ""
	#: El mismo paquete en otros orígenes: ``{"url", "sha256", "size", "origin"}``.
	mirrors: list = field(default_factory=list)

	@property
	def isTooNew(self) -> bool:
		return addons._versionTuple(addons._parseVersion(self.minApiVersion)) > addons._versionTuple(API_VERSION)

	@property
	def isUntested(self) -> bool:
		return addons._versionTuple(addons._parseVersion(self.lastTestedApiVersion)) < addons._versionTuple(addons.API_BACKWARD_COMPAT_TO)

	def installedAddon(self) -> "addons.Addon | None":
		return addons.getAddon(self.id)

	def status(self) -> str:
		"""``available``, ``installed``, ``update``, ``older`` o ``incompatible``."""
		if self.isTooNew:
			return "incompatible"
		inst = self.installedAddon()
		if inst is None:
			return "available"
		cmp = addons.compareVersions(self.version, inst.version)
		if cmp > 0:
			return "update"
		if cmp < 0:
			return "older"
		return "installed"


def catalogUrl() -> str:
	"""Catálogo en línea del origen preferido ("" si no hay: se usa la copia local sin ir a la red)."""
	origins = updates.catalogOrigins()
	return origins[0].catalogUrl if origins else ""


def localCatalogPath() -> str:
	return paths.docPath("catalogo_complementos.json")


def _apiOk(minApi: str) -> bool:
	return addons._versionTuple(addons._parseVersion(minApi)) <= addons._versionTuple(API_VERSION)


def _bestVersion(item: dict) -> dict:
	"""La versión que se ofrece: la más reciente compatible de ``versions`` (o la de primer nivel)."""
	versions = [v for v in item.get("versions") or [] if isinstance(v, dict) and v.get("version")]
	if not versions:
		return item
	versions.sort(key=lambda v: updates.versionKey(str(v["version"])), reverse=True)
	chosen = next((v for v in versions if _apiOk(str(v.get("minApiVersion") or item.get("minApiVersion") or "1.0"))), versions[0])
	if str(chosen["version"]) == str(item.get("version")):
		return item
	# Lo propio de cada paquete no se hereda de la versión más reciente: un
	# SHA-256 o un tamaño ajenos harían fallar (o engañarían) la descarga.
	merged = {k: v for k, v in item.items() if k not in ("url", "sha256", "size", "changelog")}
	merged.update(chosen)
	return merged


def parseCatalog(data: dict, baseUrl: str = "") -> list[CatalogEntry]:
	if data.get("format") not in (None, CATALOG_FORMAT):
		raise ValueError(_("El archivo no es un catálogo de complementos de Tiresias"))
	out: list[CatalogEntry] = []
	known = set(CatalogEntry.__dataclass_fields__) - {"extra", "origin", "mirrors"}
	for item in data.get("addons") or []:
		if not isinstance(item, dict) or not item.get("id") or not item.get("version"):
			continue
		item = _bestVersion(item)
		kw = {k: item[k] for k in known if k in item}
		kw["id"] = str(kw["id"])
		kw["version"] = str(kw["version"])
		kw.setdefault("name", kw["id"])
		try:
			kw["size"] = int(kw.get("size") or 0)
		except (TypeError, ValueError):
			kw["size"] = 0
		entry = CatalogEntry(**kw)
		try:
			entry.url = updates.resolveUrl(baseUrl, entry.url)
		except updates.UnsafeUrlError as e:
			# Dirección local, de carpeta compartida o sin cifrar: el complemento no se ofrece.
			log.warning("Catálogo: se descarta %s: %s", entry.id, e)
			continue
		entry.extra = {k: v for k, v in item.items() if k not in known}
		if not policyModule.policy.isAddonBlocked(entry.id):
			out.append(entry)
	return out


def fetchCatalog(url: str | None = None) -> tuple[list[CatalogEntry], str]:
	"""Descarga el catálogo (bloqueante). Devuelve ``(entradas, origen)``.

	Sin ``url``, de los orígenes de :func:`updates.catalogOrigins`; con
	varios, los lee a la vez y los combina (:func:`mergeCatalogs`). Si no
	responde ninguno, usa la copia local.
	"""
	origins = [updates.Origin(updates.ORIGIN_OWN, "", "", url)] if url else updates.catalogOrigins()
	if not origins:
		# Sin catálogo en línea: copia local, sin red.
		local = localCatalogPath()
		if not os.path.isfile(local):
			raise ValueError(_("No hay catálogo de complementos: escriba su dirección en Opciones, categoría «Actualizaciones y complementos»."))
		return parseCatalog(updates.fetchJson(local), local), local
	if len(origins) == 1:
		origin = origins[0]
		try:
			entries = parseCatalog(updates.fetchJson(origin.catalogUrl), origin.catalogUrl)
		except Exception as e:
			return _localFallback(origin, e)
		for e in entries:
			e.origin = origin.kind
		log.info("Catálogo de complementos leído de %s: %d complementos", origin.catalogUrl, len(entries))
		return entries, origin.catalogUrl
	parsed: list[tuple[updates.Origin, list[CatalogEntry]]] = []
	errors: list[tuple[updates.Origin, BaseException]] = []
	for origin, (data, error) in zip(origins, updates.fetchAll([o.catalogUrl for o in origins])):
		if error is None and data is not None:
			try:
				parsed.append((origin, parseCatalog(data, origin.catalogUrl)))
				log.info("Catálogo de complementos leído de %s: %d complementos", origin.catalogUrl, len(parsed[-1][1]))
				continue
			except Exception as e:
				error = e
		errors.append((origin, error or ValueError("?")))
		log.info("Catálogo de complementos: no se pudo leer %s (%s): %s", origin.label, origin.catalogUrl, error)
	if not parsed:
		return _localFallback(origins[0], errors[0][1])
	return mergeCatalogs(parsed), " + ".join(o.catalogUrl for o, _e in parsed)


def _localFallback(origin: "updates.Origin", error: BaseException) -> tuple[list[CatalogEntry], str]:
	"""Copia local del catálogo cuando no responde el catálogo en línea (o lanza ``error``)."""
	local = localCatalogPath()
	if origin.catalogUrl == local or not os.path.isfile(local):
		raise error
	log.info("Catálogo en línea no disponible (%s); se usa la copia local", error)
	data = updates.fetchJson(local)
	if origin.kind == updates.ORIGIN_GITHUB:
		data = _asGithubCatalog(data)
	# La copia local es una instantánea del catálogo en línea: sus
	# direcciones relativas se resuelven respecto a él.
	entries = parseCatalog(data, origin.catalogUrl)
	for e in entries:
		e.origin = origin.kind
	return entries, local


def _asGithubCatalog(data: dict) -> dict:
	"""La copia local (del servidor del proyecto) vista como el catálogo de GitHub:
	sin complementos propietarios y con los paquetes en la versión «complementos»."""

	def fix(item: dict) -> dict:
		item = dict(item)
		url = str(item.get("url") or "")
		if url and "://" not in url:
			item["url"] = updates.githubAssetUrl(updates.GITHUB_ADDONS_TAG, url.replace("\\", "/").rsplit("/", 1)[-1])
		return item

	addonsOut = []
	for item in data.get("addons") or []:
		if not isinstance(item, dict) or item.get("proprietary"):
			continue
		item = fix(item)
		if isinstance(item.get("versions"), list):
			item["versions"] = [fix(v) for v in item["versions"] if isinstance(v, dict)]
		addonsOut.append(item)
	return dict(data, addons=addonsOut)


def _sameSha(a: str, b: str) -> bool:
	return bool(a and b) and a.strip().lower() == b.strip().lower()


def mergeCatalogs(parsed: list[tuple["updates.Origin", list[CatalogEntry]]]) -> list[CatalogEntry]:
	"""Combina los catálogos de varios orígenes (el preferido primero).

	Por identificador gana la versión más alta; con la misma, la del origen
	preferido, y la de los demás orígenes queda como réplica (``mirrors``)
	si es el mismo paquete (el mismo SHA-256).
	"""
	chosen: dict[str, CatalogEntry] = {}
	order: list[str] = []
	for origin, entries in parsed:
		for e in entries:
			e.origin = origin.kind
			current = chosen.get(e.id)
			if current is None:
				chosen[e.id] = e
				order.append(e.id)
				continue
			cmp = addons.compareVersions(e.version, current.version)
			if cmp > 0:
				chosen[e.id] = e
			elif cmp == 0 and e.url and _sameSha(e.sha256, current.sha256):
				current.mirrors.append({"url": e.url, "sha256": e.sha256, "size": e.size, "origin": origin.kind})
	return [chosen[i] for i in order]


def availableUpdates(entries: list[CatalogEntry]) -> list[CatalogEntry]:
	return [e for e in entries if e.status() == "update"]


def downloadPackage(entry: CatalogEntry, progress: Callable[[int, int], bool] | None = None) -> str:
	"""Descarga el paquete (bloqueante) comprobando tamaño y SHA-256.

	Si falla y otro origen tiene el mismo paquete (``entry.mirrors``, con el
	mismo SHA-256), se descarga de allí. Si fallan todos, se lanza el error
	del primero. Cancelar no reintenta.
	"""
	if not entry.url:
		raise ValueError(_("El catálogo no indica dónde descargar «{name}»").format(name=entry.name))
	what = _("«{name}»").format(name=entry.name)
	updates.requireChecksum(entry.url, entry.sha256, what)
	safe = re.sub(r"[^\w.-]", "_", f"{entry.id}-{entry.version}")
	dest = os.path.join(paths.cacheDir(), "complementos", f"{safe}{addons.ADDON_EXTENSION}")
	try:
		return updates.download(entry.url, dest, entry.sha256 or None, progress, size=entry.size)
	except InterruptedError:
		raise
	except Exception as first:
		for m in entry.mirrors:
			url, sha = str(m.get("url") or ""), str(m.get("sha256") or "")
			if not url or not _sameSha(sha, entry.sha256):
				continue
			log.warning("No se pudo descargar «%s» de %s (%s); se intenta en %s", entry.id, entry.origin or entry.url, first, m.get("origin") or url)
			try:
				updates.requireChecksum(url, sha, what)
				return updates.download(url, dest, sha, progress, size=int(m.get("size") or 0))
			except InterruptedError:
				raise
			except Exception as e:
				log.warning("Tampoco se pudo descargar «%s» de %s: %s", entry.id, m.get("origin") or url, e)
		raise first


def installEntry(entry: CatalogEntry, progress: Callable[[int, int], bool] | None = None) -> "addons.Addon":
	"""Descarga e instala (bloqueante). Requiere reiniciar Tiresias."""
	if not policyModule.isAllowed("addonStore") or not policyModule.isAllowed("addonInstall"):
		raise ValueError(policyModule.blockedMessage())
	path = downloadPackage(entry, progress)
	try:
		manifest, _installed = addons.inspectPackage(path)
		if str(manifest.get("id") or "") != entry.id:
			# El paquete no es el que anuncia el catálogo: no se deja que sustituya a otro.
			raise ValueError(_("El paquete descargado no corresponde a «{name}»").format(name=entry.name))
		# El identificador se vuelve a comprobar con el manifiesto que se instala de verdad.
		return addons.installFromFile(path, expectedId=entry.id)
	finally:
		try:
			os.remove(path)
		except OSError:
			pass


# ====================================================================== comprobación automática
_scheduled = False


def scheduleAutomaticCheck(delay: float = 120.0) -> None:
	"""Una vez por sesión: avisa discretamente si hay actualizaciones de complementos."""
	global _scheduled
	if _scheduled or not conf["addons"]["autoCheckUpdates"] or not policyModule.isAllowed("addonStore"):
		return
	if not catalogUrl():
		# Sin catálogo en línea: no hay nada nuevo que mirar; la tienda sigue
		# disponible con la copia local.
		return
	_scheduled = True

	def run() -> None:
		try:
			entries, _src = fetchCatalog()
			if not addons.getAddons():
				addons.discover()
			ups = availableUpdates(entries)
			log.info("Actualizaciones de complementos (%s): %s", _src, ", ".join(f"{e.id} {e.version}" for e in ups) or "ninguna")
		except Exception as e:
			log.info("No se pudieron comprobar las actualizaciones de complementos: %s", e)
			return
		if not ups:
			return
		from . import gui, queue_handler, speech

		names = ", ".join(f"{e.name} {e.version}" for e in ups)
		queue_handler.queueFunction(speech.speakMessage, _("Hay actualizaciones de complementos"))
		gui.runOnGui(
			gui.showTrayNotification,
			_("Actualizaciones de complementos"),
			_("Disponibles: {list}. Ábralas en Complementos > Tienda de complementos.").format(list=names),
		)

	t = threading.Timer(delay, run)
	t.daemon = True
	t.start()
