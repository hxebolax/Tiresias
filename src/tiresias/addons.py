"""Gestión de complementos.

Un complemento es una carpeta dentro de ``data/addons`` (o un archivo
``.tiresias-addon``, que es un ZIP con esa carpeta) con esta estructura::

	miComplemento/
		manifest.json           (obligatorio)
		appModules/             módulos de aplicación (whatsapp_root.py ...)
		globalPlugins/          complementos globales
		synthDrivers/           sintetizadores
		brailleDisplayDrivers/  controladores de líneas braille
		doc/es/readme.html      documentación (opcional)
		installTasks.py         onInstall() / onUninstall() (opcional)

Ejemplo de ``manifest.json``::

	{
		"id": "miComplemento",
		"name": "Mi complemento",
		"version": "1.0.0",
		"author": "Nombre <correo>",
		"description": "Qué hace",
		"minApiVersion": "1.0",
		"lastTestedApiVersion": "1.0",
		"url": ""
	}
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import types
import zipfile

from . import API_VERSION, paths
from .config import conf
from .i18n import _
from .log import getLogger

log = getLogger("addons")

ADDON_EXTENSION = ".tiresias-addon"
_PENDING_FILE = "pending.json"

#: Versión más antigua de la API con la que esta versión sigue siendo compatible.
#: Un complemento cuyo ``lastTestedApiVersion`` sea anterior se considera «no
#: probado»: no se carga salvo que el usuario lo active de todos modos.
API_BACKWARD_COMPAT_TO = (1, 0)


def _parseVersion(v: str | None) -> tuple[int, ...]:
	if not v:
		return (0,)
	return tuple(int(p) for p in re.findall(r"\d+", str(v))[:3]) or (0,)


def _versionTuple(v: tuple[int, ...]) -> tuple[int, int, int]:
	t = tuple(v) + (0, 0, 0)
	return (t[0], t[1], t[2])


def _fmtVersion(v: tuple[int, ...]) -> str:
	return ".".join(str(p) for p in v)


def compareVersions(a: str | None, b: str | None) -> int:
	"""-1, 0 o 1 según ``a`` sea anterior, igual o posterior a ``b``.

	Mismo criterio que la tienda y las actualizaciones (:func:`updates.versionKey`):
	cuatro números y versiones previas («1.1.0b1» < «1.1.0»).
	"""
	from .updates import versionKey

	ka, kb = versionKey(a), versionKey(b)
	return (ka > kb) - (ka < kb)


def _readManifest(folder: str) -> dict | None:
	jsonPath = os.path.join(folder, "manifest.json")
	if os.path.isfile(jsonPath):
		try:
			# utf-8-sig: el Bloc de notas puede guardar el manifiesto con BOM.
			with open(jsonPath, encoding="utf-8-sig") as f:
				data = json.load(f)
			return data if isinstance(data, dict) else None
		except (OSError, ValueError):
			log.exception("Manifiesto no válido en %s", folder)
			return None
	iniPath = os.path.join(folder, "manifest.ini")
	if os.path.isfile(iniPath):
		data: dict[str, str] = {}
		try:
			with open(iniPath, encoding="utf-8-sig") as f:
				text = f.read()
			for m in re.finditer(r'^(\w+)\s*=\s*(?:"""(.*?)"""|"(.*?)"|(.*?))\s*$', text, re.M | re.S):
				data[m.group(1)] = next(g for g in m.groups()[1:] if g is not None)
			data.setdefault("id", data.get("name", os.path.basename(folder)))
			data.setdefault("description", data.get("summary", ""))
			return data
		except OSError:
			return None
	return None


class Addon:
	def __init__(self, folder: str, manifest: dict) -> None:
		self.path = folder
		self.manifest = manifest
		self.id = str(manifest.get("id") or os.path.basename(folder))
		self.name = str(manifest.get("name") or self.id)
		self.version = str(manifest.get("version", ""))
		self.author = str(manifest.get("author", ""))
		self.description = str(manifest.get("description", ""))
		self.url = str(manifest.get("url", ""))
		self.minApiVersion = _parseVersion(manifest.get("minApiVersion"))
		# Sin lastTestedApiVersion se supone probado con su versión mínima.
		self.lastTestedApiVersion = _parseVersion(manifest.get("lastTestedApiVersion") or manifest.get("minApiVersion") or "1.0")
		self.changelog = str(manifest.get("changelog", "") or "")
		self.loadError: str | None = None

	@property
	def isTooNew(self) -> bool:
		"""Necesita una versión de Tiresias más reciente (no se puede forzar)."""
		# Tuplas de la misma longitud: «1.0.0» no es más nueva que la API 1.0.
		return _versionTuple(self.minApiVersion) > _versionTuple(API_VERSION)

	@property
	def isUntested(self) -> bool:
		"""No se ha probado con esta versión de la API (se puede activar de todos modos)."""
		return _versionTuple(self.lastTestedApiVersion) < _versionTuple(API_BACKWARD_COMPAT_TO)

	@property
	def compatibilityOverridden(self) -> bool:
		return self.id in (conf["addons"]["overrideCompatibility"] or [])

	@property
	def isBlocked(self) -> bool:
		"""Bloqueado por la política corporativa."""
		from .config import policy

		return policy.policy.isAddonBlocked(self.id)

	@property
	def isCompatible(self) -> bool:
		if self.isTooNew:
			return False
		return not self.isUntested or self.compatibilityOverridden

	def incompatibilityReason(self) -> str | None:
		if self.isTooNew:
			return _("Requiere una versión más reciente de Tiresias (API {need}; esta versión tiene la {have}).").format(
				need=_fmtVersion(self.minApiVersion), have=_fmtVersion(API_VERSION)
			)
		if self.isUntested and not self.compatibilityOverridden:
			return _("No se ha probado con esta versión de Tiresias (probado hasta la API {tested}).").format(tested=_fmtVersion(self.lastTestedApiVersion))
		return None

	@property
	def isEnabled(self) -> bool:
		return self.id not in conf["addons"]["disabled"]

	@property
	def packageName(self) -> str:
		safe = re.sub(r"\W", "_", self.id)
		return f"tiresias_addons.{safe}"

	def docPath(self) -> str | None:
		for rel in ("doc/es/readme.html", "doc/es/README.html", "doc/readme.html", "readme.html", "doc/es/readme.md"):
			p = os.path.join(self.path, rel)
			if os.path.isfile(p):
				return p
		return None

	def subdir(self, name: str) -> str:
		return os.path.join(self.path, name)

	def __repr__(self) -> str:
		return f"<Addon {self.id} {self.version}>"


_addons: dict[str, Addon] = {}
_pkg = types.ModuleType("tiresias_addons")
_pkg.__path__ = []  # type: ignore[attr-defined]
sys.modules.setdefault("tiresias_addons", _pkg)


def _pendingPath() -> str:
	return os.path.join(paths.addonsDir(), _PENDING_FILE)


def _readPending() -> dict:
	try:
		with open(_pendingPath(), encoding="utf-8") as f:
			return json.load(f)
	except (OSError, ValueError):
		return {}


def _writePending(data: dict) -> None:
	os.makedirs(paths.addonsDir(), exist_ok=True)
	with open(_pendingPath(), "w", encoding="utf-8") as f:
		json.dump(data, f, ensure_ascii=False, indent="\t")


#: Las eliminaciones pendientes se hacen una sola vez, al arrancar: no al recargar
#: los complementos (Tiresias+Control+F3) con el complemento todavía cargado.
_pendingProcessed = False


def _processPending() -> None:
	data = _readPending()
	left: list[str] = []
	for addonId in data.get("remove", []):
		if not isinstance(addonId, str) or addonId in ("", ".", "..") or os.path.basename(addonId) != addonId or "/" in addonId:
			# Nunca fuera de la carpeta de complementos (ni la carpeta entera).
			log.warning("Eliminación pendiente no válida: %r", addonId)
			continue
		folder = os.path.join(paths.addonsDir(), addonId)
		_runInstallTask(folder, "onUninstall")
		shutil.rmtree(folder, ignore_errors=True)
		if os.path.isdir(folder):
			# Algún archivo en uso: se vuelve a intentar en el próximo arranque.
			log.warning("No se pudo eliminar del todo el complemento %s; se reintentará", addonId)
			left.append(addonId)
			continue
		log.info("Complemento eliminado: %s", addonId)
		# Que ni la copia instalada ni la actualización de una portable vuelvan
		# a copiar el complemento incluido (installer.updateBundledAddons).
		try:
			open(os.path.join(paths.addonsDir(), f".{addonId}.eliminado"), "w").close()
		except OSError:
			pass
	if left:
		data["remove"] = left
		_writePending(data)
	elif data:
		try:
			os.remove(_pendingPath())
		except OSError:
			pass


def discover() -> list[Addon]:
	_addons.clear()
	base = paths.addonsDir()
	try:
		entries = sorted(os.listdir(base))
	except OSError:
		return []
	for entry in entries:
		folder = os.path.join(base, entry)
		if not os.path.isdir(folder) or entry.startswith((".", "_")) or entry.endswith(".tmp"):
			continue
		manifest = _readManifest(folder)
		if manifest is None:
			log.warning("Carpeta sin manifiesto en complementos: %s", entry)
			continue
		addon = Addon(folder, manifest)
		_addons[addon.id] = addon
	return list(_addons.values())


def getAddons() -> list[Addon]:
	return list(_addons.values())


def getAddon(addonId: str) -> Addon | None:
	return _addons.get(addonId)


def _loadModuleFile(fullName: str, path: str):
	if os.path.isdir(path):
		spec = importlib.util.spec_from_file_location(fullName, os.path.join(path, "__init__.py"), submodule_search_locations=[path])
	else:
		spec = importlib.util.spec_from_file_location(fullName, path)
	if spec is None or spec.loader is None:
		return None
	mod = importlib.util.module_from_spec(spec)
	sys.modules[fullName] = mod
	spec.loader.exec_module(mod)
	return mod


def _ensurePackage(name: str, path: str) -> None:
	if name in sys.modules:
		return
	mod = types.ModuleType(name)
	mod.__path__ = [path]  # type: ignore[attr-defined]
	sys.modules[name] = mod


def loadAll() -> None:
	"""Registra los componentes de todos los complementos activados."""
	from . import braille, synth
	from .appmodules import handler as appHandler
	from .plugins import handler as pluginHandler

	global _pendingProcessed
	if not _pendingProcessed:
		_pendingProcessed = True
		_processPending()
	discover()
	appHandler.clearSearchDirs()
	pluginHandler.clearSources()
	toLoad = list(_addons.values())
	if conf["advanced"]["enableScratchpad"]:
		# Bloc de pruebas para desarrolladores: data/scratchpad se carga como
		# un complemento más, sin empaquetar ni instalar.
		scratch = paths.data("scratchpad")
		for sub in ("appModules", "globalPlugins", "synthDrivers", "brailleDisplayDrivers"):
			os.makedirs(os.path.join(scratch, sub), exist_ok=True)
		toLoad.append(Addon(scratch, {"id": "scratchpad", "name": "Bloc de pruebas", "version": "0"}))
	for addon in toLoad:
		if not addon.isEnabled:
			continue
		if addon.isBlocked:
			addon.loadError = _("Bloqueado por la política del equipo")
			log.warning("Complemento bloqueado por la política: %s", addon.id)
			continue
		if not addon.isCompatible:
			addon.loadError = addon.incompatibilityReason() or _("Incompatible")
			log.warning("Complemento incompatible: %s", addon.id)
			continue
		pkg = addon.packageName
		_ensurePackage(pkg, addon.path)
		if addon.path not in sys.path:
			# Permite que los complementos importen sus propios módulos auxiliares.
			sys.path.append(addon.path)
		try:
			appDir = addon.subdir("appModules")
			if os.path.isdir(appDir):
				_ensurePackage(f"{pkg}.appModules", appDir)
				appHandler.addSearchDir(f"{pkg}.appModules", appDir)
			gpDir = addon.subdir("globalPlugins")
			if os.path.isdir(gpDir):
				_ensurePackage(f"{pkg}.globalPlugins", gpDir)
				pluginHandler.addSource(f"{pkg}.globalPlugins", gpDir)
			for kind, register in (("synthDrivers", synth.registerDriverModule), ("brailleDisplayDrivers", braille.registerDriverModule)):
				folder = addon.subdir(kind)
				if not os.path.isdir(folder):
					continue
				_ensurePackage(f"{pkg}.{kind}", folder)
				for fn in sorted(os.listdir(folder)):
					p = os.path.join(folder, fn)
					if fn.startswith("_"):
						continue
					if fn.endswith(".py"):
						modName = fn[:-3]
					elif os.path.isfile(os.path.join(p, "__init__.py")):
						modName = fn
					else:
						continue
					try:
						mod = _loadModuleFile(f"{pkg}.{kind}.{modName}", p)
						if mod is not None:
							register(modName, mod)
					except Exception:
						log.exception("Error cargando %s de %s", fn, addon.id)
			log.info("Complemento cargado: %s %s", addon.id, addon.version)
		except Exception as e:
			addon.loadError = str(e)
			log.exception("Error cargando el complemento %s", addon.id)


def _runInstallTask(folder: str, func: str) -> None:
	path = os.path.join(folder, "installTasks.py")
	if not os.path.isfile(path):
		return
	try:
		mod = _loadModuleFile(f"tiresias_install_{abs(hash(folder))}", path)
		f = getattr(mod, func, None)
		if f:
			f()
	except Exception:
		log.exception("Error en %s de %s", func, folder)


def inspectPackage(filePath: str) -> tuple[dict, "Addon | None"]:
	"""Lee el manifiesto de un paquete sin instalarlo: ``(manifiesto, complemento instalado con ese id)``."""
	if not zipfile.is_zipfile(filePath):
		raise ValueError(_("El archivo no es un complemento válido"))
	with zipfile.ZipFile(filePath) as z:
		names = z.namelist()
		cand = [n for n in names if n.replace("\\", "/").split("/")[-1] == "manifest.json" and n.count("/") <= 1]
		if not cand:
			raise ValueError(_("El complemento no tiene manifiesto"))
		try:
			manifest = json.loads(z.read(sorted(cand, key=len)[0]).decode("utf-8-sig"))
		except ValueError:
			raise ValueError(_("El manifiesto del complemento no es válido")) from None
	if not isinstance(manifest, dict):
		raise ValueError(_("El manifiesto del complemento no es válido"))
	addonId = str(manifest.get("id") or "")
	if not _addons:
		discover()
	return manifest, _addons.get(addonId)


#: Identificadores admitidos: letras, cifras, «_», «.» y «-», empezando por letra o cifra
#: (las carpetas que empiezan por «.» o «_» no se cargan nunca, ver :func:`discover`).
_ADDON_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,99}")
#: Tamaño máximo de un complemento descomprimido (protege de las «bombas ZIP»).
MAX_ADDON_UNCOMPRESSED = 1024**3


def isValidAddonId(addonId: str) -> bool:
	"""``True`` si ``addonId`` sirve como nombre de carpeta de complemento."""
	return bool(_ADDON_ID.fullmatch(addonId or "")) and not addonId.endswith((".tmp", "."))


def installFromFile(filePath: str, expectedId: str | None = None) -> Addon:
	"""Instala un paquete ``.tiresias-addon``. Requiere reiniciar Tiresias.

	Si ya hay un complemento con el mismo identificador, se sustituye: la
	interfaz debe preguntar antes con :func:`inspectPackage`. ``expectedId``
	(la tienda): el manifiesto que se instala debe tener ese identificador.
	"""
	from .config import policy

	if not policy.isAllowed("addonInstall"):
		raise ValueError(policy.blockedMessage())
	if not zipfile.is_zipfile(filePath):
		raise ValueError(_("El archivo no es un complemento válido"))
	base = paths.addonsDir()
	os.makedirs(base, exist_ok=True)
	with zipfile.ZipFile(filePath) as z:
		names = z.namelist()
		for n in names:
			if not _isSafeMember(n):
				raise ValueError(_("El paquete contiene rutas no válidas"))
		# zipfile no escribe más de lo que declara cada entrada: basta con sumarlo.
		if sum(i.file_size for i in z.infolist()) > MAX_ADDON_UNCOMPRESSED:
			raise ValueError(_("El complemento es demasiado grande al descomprimirlo"))
		prefix = ""
		if "manifest.json" not in names and "manifest.ini" not in names:
			tops = {n.split("/")[0] for n in names if "/" in n}
			if len(tops) == 1:
				prefix = tops.pop() + "/"
		# Carpeta propia de esta instalación (la tienda y el administrador pueden coincidir).
		tmp = tempfile.mkdtemp(prefix="_install", suffix=".tmp", dir=base)
		tmpAbs = os.path.abspath(tmp)
		for n in names:
			if not n.startswith(prefix) or n.endswith("/"):
				continue
			target = os.path.abspath(os.path.join(tmpAbs, n[len(prefix) :]))
			if os.path.commonpath([tmpAbs, target]) != tmpAbs:
				shutil.rmtree(tmp, ignore_errors=True)
				raise ValueError(_("El paquete contiene rutas no válidas"))
			os.makedirs(os.path.dirname(target), exist_ok=True)
			with z.open(n) as src, open(target, "wb") as dst:
				shutil.copyfileobj(src, dst)
	manifest = _readManifest(tmp)
	if manifest is None:
		shutil.rmtree(tmp, ignore_errors=True)
		raise ValueError(_("El complemento no tiene manifiesto"))
	addon = Addon(tmp, manifest)
	if expectedId is not None and addon.id != expectedId:
		shutil.rmtree(tmp, ignore_errors=True)
		raise ValueError(_("El paquete no corresponde al complemento esperado ({id})").format(id=expectedId))
	if not isValidAddonId(addon.id):
		shutil.rmtree(tmp, ignore_errors=True)
		raise ValueError(_("El identificador del complemento no es válido: {id}").format(id=addon.id))
	if addon.isTooNew:
		shutil.rmtree(tmp, ignore_errors=True)
		raise ValueError(_("El complemento requiere una versión más reciente de Tiresias"))
	if addon.isBlocked:
		shutil.rmtree(tmp, ignore_errors=True)
		raise ValueError(_("El administrador del equipo ha bloqueado este complemento"))
	safeId = addon.id
	final = os.path.join(base, safeId)
	backup: str | None = None
	if os.path.isdir(final):
		# La versión anterior se aparta (sin borrarla) y la nueva ocupa su sitio;
		# si algo falla, la anterior vuelve intacta y sin haber ejecutado su onUninstall.
		backup = final + ".old.tmp"
		shutil.rmtree(backup, ignore_errors=True)
		try:
			os.replace(final, backup)
		except OSError:
			shutil.rmtree(tmp, ignore_errors=True)
			raise
	try:
		os.replace(tmp, final)
	except OSError:
		if backup is not None:
			try:
				os.replace(backup, final)
			except OSError:
				log.exception("No se pudo restaurar la versión anterior de %s (sigue en %s)", addon.id, backup)
		shutil.rmtree(tmp, ignore_errors=True)
		raise
	if backup is not None:
		_runInstallTask(backup, "onUninstall")
		shutil.rmtree(backup, ignore_errors=True)
	try:
		os.remove(os.path.join(base, f".{safeId}.eliminado"))
	except OSError:
		pass
	# Si estaba marcado para eliminar, la versión recién instalada se queda.
	pending = _readPending()
	if pending.get("remove"):
		keep = [r for r in pending["remove"] if r not in (safeId, addon.id)]
		if keep != pending["remove"]:
			pending["remove"] = keep
			_writePending(pending)
	_runInstallTask(final, "onInstall")
	addon = Addon(final, manifest)
	_addons[addon.id] = addon
	return addon


def _isSafeMember(name: str) -> bool:
	"""Una entrada del ZIP que queda dentro de la carpeta del complemento."""
	n = name.replace("\\", "/")
	if not n or n.startswith("/") or ":" in n or os.path.splitdrive(n)[0]:
		return False
	return ".." not in n.split("/")


def createPackage(folder: str, outFile: str | None = None) -> str:
	"""Empaqueta una carpeta de complemento en un archivo ``.tiresias-addon``."""
	manifest = _readManifest(folder)
	if manifest is None:
		raise ValueError("Falta manifest.json")
	addonId = manifest.get("id") or os.path.basename(folder)
	version = manifest.get("version", "0")
	outFile = outFile or os.path.join(os.path.dirname(folder), f"{addonId}-{version}{ADDON_EXTENSION}")
	with zipfile.ZipFile(outFile, "w", zipfile.ZIP_DEFLATED) as z:
		for root, dirs, files in os.walk(folder):
			dirs[:] = [d for d in dirs if d != "__pycache__"]
			for fn in files:
				full = os.path.join(root, fn)
				z.write(full, os.path.relpath(full, folder))
	return outFile


def setEnabled(addonId: str, enabled: bool) -> None:
	disabled = list(conf["addons"]["disabled"])
	if enabled and addonId in disabled:
		disabled.remove(addonId)
	elif not enabled and addonId not in disabled:
		disabled.append(addonId)
	# No depende del perfil (como en NVDA): un complemento desactivado lo está siempre.
	conf.setGlobal("addons", "disabled", disabled)


def setCompatibilityOverride(addonId: str, override: bool) -> None:
	"""Permite cargar un complemento no probado con esta versión («activar de todos modos»)."""
	ids = list(conf["addons"]["overrideCompatibility"] or [])
	if override and addonId not in ids:
		ids.append(addonId)
	elif not override and addonId in ids:
		ids.remove(addonId)
	conf.setGlobal("addons", "overrideCompatibility", ids)


def markForRemoval(addonId: str) -> None:
	data = _readPending()
	remove = set(data.get("remove", []))
	addon = _addons.get(addonId)
	remove.add(os.path.basename(addon.path) if addon else addonId)
	data["remove"] = sorted(remove)
	_writePending(data)


def pendingRemovals() -> list[str]:
	return list(_readPending().get("remove", []))
