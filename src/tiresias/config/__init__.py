"""Gestión de la configuración y perfiles.

Uso::

	from tiresias.config import conf
	rate = conf["speech"]["synths"]["espeak"]["rate"]
	conf["keyboard"]["speakTypedWords"] = "always"

La configuración se organiza en capas: valores por defecto, configuración
base del usuario (``data/config/config.json``), perfiles
(``data/config/profiles/<nombre>.json``) y, encima de todo, los valores
bloqueados por la política corporativa (``policy.json``). Al leer una clave
se consulta la capa superior que la defina. Al escribir se modifica la capa
en edición (el perfil manual activo o, si no hay, la configuración base).

Al cargar, cada archivo se migra a la versión actual del esquema
(:mod:`.migrations`) y se validan los tipos y rangos (:mod:`.validation`).
Un archivo dañado se aparta (``.corrupto``) y se recupera la copia de
seguridad (``.bak``) que se hace antes de cada guardado.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import threading
import time
from collections.abc import MutableMapping
from typing import Any, Iterator

from .. import paths
from ..extension_points import Action
from ..log import log
from . import migrations, schema, validation
from .policy import Policy, policy as _initialPolicy

_MISSING = object()
#: Esperas (s) antes de cada reintento de leer un archivo que no se pudo abrir.
READ_RETRY_DELAYS = (0.2, 0.5, 1.0)

#: Se notifica tras cambiar de perfil o recargar la configuración.
post_configProfileSwitch = Action()
#: Se notifica antes de guardar (los módulos pueden volcar su estado).
pre_configSave = Action()
#: Se notifica tras guardar.
post_configSave = Action()
#: Se notifica tras restablecer/recargar desde disco.
post_configReset = Action()
#: Se notifica al entrar o salir de un disparador (``trigger``, ``entered``),
#: tenga o no un perfil asociado (p. ej. la lectura continua).
post_triggerChange = Action()

#: Disparador por dominio web: ``dominio:ejemplo.com``.
DOMAIN_TRIGGER_PREFIX = "dominio:"
#: Disparador por aplicación: ``app:notepad``.
APP_TRIGGER_PREFIX = "app:"

#: Secciones que no dependen del perfil (como ``BASE_ONLY_SECTIONS`` de NVDA): se
#: leen y se guardan siempre en la configuración normal aunque haya un perfil
#: activo o en edición. Los complementos pueden añadir las suyas.
BASE_ONLY_SECTIONS: set[str] = {"general", "update", "addons", "coexist", "controller"}
#: Excepciones dentro de esas secciones: sí pueden cambiar con el perfil.
PROFILE_ALLOWED_KEYS: set[tuple[str, str]] = {("general", "preventDisplayTurningOff")}
#: Opciones sueltas de otras secciones que tampoco dependen del perfil (se usan
#: al arrancar o son el sitio de una ventana).
BASE_ONLY_KEYS: set[tuple[str, str]] = {
	("speechViewer", "showAtStartup"),
	("speechViewer", "position"),
	("brailleViewer", "showAtStartup"),
	("brailleViewer", "x"),
	("brailleViewer", "y"),
}
#: Opciones cuyo valor es un diccionario que se sustituye entero: vale el de la
#: capa más alta que lo tenga (un perfil puede quitar entradas de la
#: configuración normal). Las demás opciones de tipo diccionario (``speech.synths``,
#: ``brailleDisplays.ports`` y ``brailleDisplays.settings``) guardan ajustes de
#: cada sintetizador o línea y se combinan ajuste a ajuste entre las capas.
ATOMIC_KEYS: set[tuple[str, str]] = {
	("braille", "roleAbbreviations"),
	("presentation", "roleTemplates"),
}


def isBaseOnly(path: tuple[str, ...]) -> bool:
	"""``True`` si la opción ``path`` no depende del perfil (siempre en la configuración normal)."""
	if len(path) < 2:
		return False
	key = (path[0], path[1])
	if key in BASE_ONLY_KEYS:
		return True
	return path[0] in BASE_ONLY_SECTIONS and key not in PROFILE_ALLOWED_KEYS


def _walk(d: dict, path: tuple[str, ...]) -> Any:
	node: Any = d
	for key in path:
		if not isinstance(node, dict) or key not in node:
			return _MISSING
		node = node[key]
	return node


def _deepMerge(target: dict, src: dict) -> dict:
	for k, v in src.items():
		if isinstance(v, dict) and isinstance(target.get(k), dict):
			_deepMerge(target[k], v)
		else:
			target[k] = copy.deepcopy(v)
	return target


def _prune(d: dict, defaults: dict) -> dict:
	"""Elimina de ``d`` los valores iguales a los de ``defaults``."""
	out: dict = {}
	for k, v in d.items():
		dv = defaults.get(k, _MISSING) if isinstance(defaults, dict) else _MISSING
		if isinstance(v, dict):
			sub = _prune(v, dv if isinstance(dv, dict) else {})
			if sub or dv is _MISSING:
				out[k] = sub
		elif v != dv:
			out[k] = v
	return out


_invalidNameChars = re.compile(r'[\\/:*?"<>|]')


def isValidProfileName(name: str) -> bool:
	return bool(name.strip()) and not _invalidNameChars.search(name)


def domainFromUrl(url: str) -> str | None:
	"""Dominio de una dirección web, sin ``www.`` (``None`` si no es web)."""
	m = re.match(r"^[a-z][a-z0-9+.-]*://(?:[^@/]*@)?([^/:?#]+)", (url or "").strip(), re.I)
	if not m:
		return None
	host = m.group(1).lower().rstrip(".")
	if host.startswith("www."):
		host = host[4:]
	return host or None


def normalizeDomain(text: str) -> str:
	"""Normaliza lo que escribe el usuario: «https://www.Ejemplo.com/x» -> «ejemplo.com»."""
	text = (text or "").strip()
	dom = domainFromUrl(text) if "://" in text else None
	if dom is None:
		dom = text.lower().split("/")[0].split(":")[0].rstrip(".")
		if dom.startswith("www."):
			dom = dom[4:]
	return dom


class Profile:
	def __init__(self, name: str, data: dict | None = None) -> None:
		self.name = name
		self.data: dict = data or {}
		self.dirty = False
		#: Versión del esquema del archivo (si es más reciente que la del programa, se conserva).
		self.fileVersion = schema.SCHEMA_VERSION

	@property
	def fileName(self) -> str:
		return os.path.join(paths.profilesDir(), self.name + ".json")


class ConfigView(MutableMapping):
	"""Vista de una sección de la configuración."""

	def __init__(self, manager: "ConfigManager", path: tuple[str, ...]) -> None:
		self._manager = manager
		self._path = path

	def __getitem__(self, key: str) -> Any:
		return self._manager._get(self._path + (key,))

	def __setitem__(self, key: str, value: Any) -> None:
		self._manager._set(self._path + (key,), value)

	def __delitem__(self, key: str) -> None:
		self._manager._delete(self._path + (key,))

	def __iter__(self) -> Iterator[str]:
		return iter(self._manager._keys(self._path))

	def __len__(self) -> int:
		return len(self._manager._keys(self._path))

	def __contains__(self, key: object) -> bool:
		return isinstance(key, str) and self._manager._exists(self._path + (key,))

	def get(self, key: str, default: Any = None) -> Any:
		if key in self:
			return self[key]
		return default

	def setdefault(self, key: str, default: Any = None) -> Any:
		if key not in self:
			self[key] = default
		return self[key]

	def dict(self) -> dict:
		"""Copia resuelta de esta sección: cada clave con el valor que se lee de ella
		(capas fusionadas, salvo las opciones globales y las de diccionario entero)."""
		out: dict = {}
		for key in self._manager._keys(self._path):
			try:
				value = self._manager._get(self._path + (key,))
			except KeyError:
				continue
			out[key] = value.dict() if isinstance(value, ConfigView) else copy.deepcopy(value)
		return out

	def __repr__(self) -> str:
		return f"ConfigView({'/'.join(self._path)})"


class ConfigManager:
	def __init__(self) -> None:
		self._lock = threading.RLock()
		self.defaults: dict = schema.getDefaults()
		self.base: dict = {}
		self.baseFileVersion = schema.SCHEMA_VERSION
		self.profiles: dict[str, Profile] = {}
		#: Perfiles activados por disparadores (aplicación, lectura continua...).
		self.triggeredProfiles: list[str] = []
		#: Perfil activado manualmente (tiene prioridad sobre los disparados).
		self.manualProfile: str | None = None
		#: Perfil que se está editando desde el diálogo de perfiles.
		self.editProfile: str | None = None
		#: {"app:notepad": "Bloc de notas", "sayAll": "Lectura", "dominio:ejemplo.com": "Web"}
		self.triggers: dict[str, str] = {}
		self.triggersEnabled = True
		#: Datos propios de cada perfil: {"nombre": {"enabled": bool, "readOnly": bool}}.
		self.profileMeta: dict[str, dict] = {}
		self.baseDirty = False
		#: Solo lectura (modo seguro): nunca se escribe en disco.
		self.readOnly = False
		self.policy: Policy = _initialPolicy
		self._policyLayer: dict = {}
		#: Problemas corregidos o archivos recuperados en la última carga (para avisar al usuario).
		self.loadIssues: list[str] = []
		self.recoveredFiles: list[str] = []
		#: Archivos que existen pero no se pudieron abrir al cargar (bloqueados, sin permiso).
		self.unreadableFiles: list[str] = []
		#: Rutas de esos archivos: no se sobrescriben al guardar (ver :meth:`_mayWrite`).
		self._protectedPaths: set[str] = set()
		#: Estado anterior al último «restablecer valores de fábrica» (para deshacerlo).
		self._undoReset: tuple[dict, str | None, list[str]] | None = None
		#: Disparadores activos ahora mismo (tengan o no perfil).
		self.activeTriggers: set[str] = set()

	# --- política ---
	def setPolicy(self, pol: Policy) -> None:
		with self._lock:
			self.policy = pol
			self._policyLayer = pol.lockedLayer()
			# Se valida la capa de la política como cualquier otra (las secciones de
			# los módulos se validan al registrarse, en :meth:`registerDefaults`). Un
			# valor no válido se descarta: la opción sigue bloqueada, con su valor por defecto.
			for issue in validation.validate(self._policyLayer, self.defaults):
				log.warning("Valor bloqueado por la política no válido: %s", issue)
		from . import policy as policyModule

		policyModule.policy = pol

	def isLocked(self, section: str, key: str | None = None) -> bool:
		path = (section,) if key is None else (section, key)
		return self.policy.isLocked(path)

	# --- capas ---
	def isProfileEnabled(self, name: str) -> bool:
		return bool(self.profileMeta.get(name, {}).get("enabled", True))

	def isProfileReadOnly(self, name: str) -> bool:
		return bool(self.profileMeta.get(name, {}).get("readOnly", False))

	def setProfileEnabled(self, name: str, enabled: bool) -> None:
		"""Activa o desactiva un perfil concreto (#14593): desactivado no lo activan sus disparadores."""
		if name not in self.profiles:
			return
		self.profileMeta.setdefault(name, {})["enabled"] = bool(enabled)
		self._writeMeta()
		post_configProfileSwitch.notify()

	def setProfileReadOnly(self, name: str, readOnly: bool) -> None:
		"""Un perfil de solo lectura no se guarda nunca: los cambios duran hasta salir."""
		if name not in self.profiles:
			return
		self.profileMeta.setdefault(name, {})["readOnly"] = bool(readOnly)
		self._writeMeta()

	def _activeProfileNames(self) -> list[str]:
		names = []
		if self.triggersEnabled:
			names = [n for n in self.triggeredProfiles if n in self.profiles and self.isProfileEnabled(n)]
		if self.manualProfile and self.manualProfile in self.profiles:
			if self.manualProfile in names:
				names.remove(self.manualProfile)
			names.append(self.manualProfile)
		return names

	def _layers(self, path: tuple[str, ...] = ()) -> list[dict]:
		"""Capas de abajo a arriba (las que cuentan para ``path``, si se indica).

		Las opciones globales (:func:`isBaseOnly`) no miran los perfiles. En las
		opciones de diccionario entero (:data:`ATOMIC_KEYS`) solo cuenta la capa
		más alta que las tenga.
		"""
		if path and isBaseOnly(path):
			layers = [self.defaults, self.base]
		else:
			layers = [self.defaults, self.base] + [self.profiles[n].data for n in self._activeProfileNames()]
		if self._policyLayer:
			layers.append(self._policyLayer)
		if len(path) >= 2 and (path[0], path[1]) in ATOMIC_KEYS:
			prefix = (path[0], path[1])
			for layer in reversed(layers):
				if _walk(layer, prefix) is not _MISSING:
					return [layer]
		return layers

	def _editLayer(self) -> tuple[dict, Profile | None]:
		name = self.editProfile or self.manualProfile
		if not name:
			names = self._activeProfileNames()
			name = names[-1] if names else None
		if name and name in self.profiles:
			return self.profiles[name].data, self.profiles[name]
		return self.base, None

	@property
	def activeProfileName(self) -> str | None:
		names = self._activeProfileNames()
		return names[-1] if names else None

	@property
	def activeProfileNames(self) -> list[str]:
		return list(self._activeProfileNames())

	def _get(self, path: tuple[str, ...]) -> Any:
		isSection = False
		for layer in reversed(self._layers(path)):
			node = _walk(layer, path)
			if node is _MISSING:
				continue
			if isinstance(node, dict):
				isSection = True
				break
			return node
		if isSection:
			return ConfigView(self, path)
		raise KeyError("/".join(path))

	def _exists(self, path: tuple[str, ...]) -> bool:
		return any(_walk(layer, path) is not _MISSING for layer in self._layers(path))

	def _keys(self, path: tuple[str, ...]) -> list[str]:
		keys: dict[str, None] = {}
		for layer in self._layers(path):
			node = _walk(layer, path)
			if isinstance(node, dict):
				# Copia atómica (``list(dict)`` no ejecuta código Python): otro hilo
				# puede añadir claves a la vez y recorrer el original daría
				# «dictionary changed size during iteration». Sin cerrojo: esto se
				# lee en cada tecla desde el hilo de los ganchos.
				for k in list(node):
					keys[k] = None
		return list(keys)

	def _set(self, path: tuple[str, ...], value: Any) -> None:
		if self.policy.isLocked(path):
			log.info("Opción bloqueada por la política: %s", ".".join(path))
			return
		with self._lock:
			if isinstance(value, ConfigView):
				value = value.dict()
			layer, profile = self._layerForWrite(path)
			node = layer
			for key in path[:-1]:
				nxt = node.get(key)
				if not isinstance(nxt, dict):
					nxt = {}
					node[key] = nxt
				node = nxt
			node[path[-1]] = copy.deepcopy(value) if isinstance(value, (dict, list)) else value
			if profile:
				profile.dirty = True
			else:
				self.baseDirty = True
				if isBaseOnly(path):
					self._dropFromProfiles(path)

	def _layerForWrite(self, path: tuple[str, ...]) -> tuple[dict, Profile | None]:
		"""Capa en la que se escribe ``path``: la configuración normal para las
		opciones globales; si no, la capa en edición. Antes de cambiar una entrada
		de una opción de diccionario entero, se copia en esa capa el diccionario
		que está en vigor (si no, las demás entradas dejarían de verse)."""
		if isBaseOnly(path):
			return self.base, None
		layer, profile = self._editLayer()
		if len(path) > 2 and (path[0], path[1]) in ATOMIC_KEYS:
			prefix = (path[0], path[1])
			if not isinstance(_walk(layer, prefix), dict):
				try:
					current = self._get(prefix)
				except KeyError:
					current = {}
				current = current.dict() if isinstance(current, ConfigView) else {}
				sec = layer.get(prefix[0])
				if not isinstance(sec, dict):
					sec = layer[prefix[0]] = {}
				sec[prefix[1]] = current
		return layer, profile

	def _dropFromProfiles(self, path: tuple[str, ...]) -> None:
		"""Quita una opción global de los perfiles (versiones antiguas la guardaban ahí)."""
		for profile in self.profiles.values():
			parent = _walk(profile.data, path[:-1])
			if isinstance(parent, dict) and path[-1] in parent:
				del parent[path[-1]]
				if not parent and len(path) == 2 and profile.data.get(path[0]) is parent:
					del profile.data[path[0]]
				profile.dirty = True

	def _delete(self, path: tuple[str, ...]) -> None:
		with self._lock:
			layer, profile = self._layerForWrite(path)
			parent = _walk(layer, path[:-1]) if len(path) > 1 else layer
			if isinstance(parent, dict) and path[-1] in parent:
				del parent[path[-1]]
				if profile:
					profile.dirty = True
				else:
					self.baseDirty = True

	def setGlobal(self, section: str, key: str, value: Any) -> None:
		"""Guarda un estado que no depende del perfil (complementos desactivados,
		última comprobación de actualizaciones...) en la configuración normal y lo
		quita de los perfiles activos, que si no lo taparían."""
		path = (section, key)
		if self.policy.isLocked(path):
			log.info("Opción bloqueada por la política: %s", ".".join(path))
			return
		with self._lock:
			node = self.base.setdefault(section, {})
			if not isinstance(node, dict):
				node = self.base[section] = {}
			node[key] = copy.deepcopy(value) if isinstance(value, (dict, list)) else value
			self.baseDirty = True
			for name in self._activeProfileNames():
				profile = self.profiles.get(name)
				sec = profile.data.get(section) if profile else None
				if isinstance(sec, dict) and key in sec:
					del sec[key]
					profile.dirty = True

	def __getitem__(self, section: str) -> ConfigView:
		val = self._get((section,))
		if not isinstance(val, ConfigView):
			raise KeyError(section)
		return val

	def __contains__(self, section: str) -> bool:
		return self._exists((section,))

	def registerDefaults(self, section: str, values: dict) -> None:
		"""Permite a complementos añadir valores por defecto propios."""
		with self._lock:
			existing = self.defaults.setdefault(section, {})
			for k, v in values.items():
				if k not in existing:
					existing[k] = copy.deepcopy(v)
			# Los valores ya cargados de esa sección se validan ahora.
			sectionDefaults = {section: existing}
			for data in [self.base] + [p.data for p in self.profiles.values()]:
				if isinstance(data.get(section), dict):
					# Se corrige en el sitio (la sección es el mismo diccionario).
					for issue in validation.validate({section: data[section]}, sectionDefaults):
						log.warning("Configuración corregida: %s", issue)
			# La política se cargó antes de que existieran estos valores: se valida ahora.
			if isinstance(self._policyLayer.get(section), dict):
				for issue in validation.validate({section: self._policyLayer[section]}, sectionDefaults):
					log.warning("Valor bloqueado por la política no válido: %s", issue)

	# --- disco ---
	@property
	def configFile(self) -> str:
		return os.path.join(paths.configDir(), "config.json")

	@property
	def triggersFile(self) -> str:
		return os.path.join(paths.configDir(), "profileTriggers.json")

	@property
	def metaFile(self) -> str:
		return os.path.join(paths.configDir(), "profileMeta.json")

	@staticmethod
	def _parseJson(path: str) -> dict:
		with open(path, encoding="utf-8-sig") as f:
			data = json.load(f)
		if not isinstance(data, dict):
			raise ValueError("el archivo no contiene un objeto JSON")
		return data

	def _readJson(self, path: str) -> dict:
		"""Lee un JSON; si está dañado lo aparta y recupera la copia ``.bak``.

		Un archivo que no se puede ABRIR (bloqueado un momento por un antivirus
		o por OneDrive, sin permiso, solo en la nube y sin conexión) no está
		dañado: se reintenta y, si sigue sin poder leerse, se usa la copia de
		seguridad solo en memoria y ese archivo no se sobrescribe al guardar
		(:meth:`_unreadable`). Antes se trataba como dañado y la copia antigua
		acababa pisando la configuración buena.
		"""
		try:
			return self._parseJson(path)
		except FileNotFoundError:
			return {}
		except ValueError:
			log.exception("No se pudo leer %s", path)
		except OSError:
			log.warning("No se pudo abrir %s (¿bloqueado por otro programa?): se reintenta", path, exc_info=True)
			corrupt = False
			for delay in READ_RETRY_DELAYS:
				time.sleep(delay)
				try:
					return self._parseJson(path)
				except FileNotFoundError:
					return {}
				except ValueError:
					log.exception("No se pudo leer %s", path)
					corrupt = True
					break
				except OSError:
					continue
			if not corrupt:
				return self._unreadable(path)
		if not self.readOnly:
			try:
				shutil.copy2(path, path + ".corrupto")
			except OSError:
				pass
		backup = path + ".bak"
		try:
			data = self._parseJson(backup)
			log.warning("Se ha recuperado la copia de seguridad %s", backup)
			self.recoveredFiles.append(os.path.basename(path))
			if not self.readOnly:
				try:
					shutil.copy2(backup, path)
				except OSError:
					pass
			return data
		except (OSError, ValueError):
			self.recoveredFiles.append(os.path.basename(path))
			log.warning("Sin copia de seguridad válida de %s: se usarán los valores por defecto", path)
			return {}

	def _unreadable(self, path: str) -> dict:
		"""El archivo existe pero no se puede abrir: copia de seguridad en memoria y no se guarda encima."""
		log.error("No se puede leer %s: se usa la copia de seguridad y no se guardará encima hasta reiniciar", path)
		self.unreadableFiles.append(os.path.basename(path))
		self._protectedPaths.add(os.path.normcase(os.path.abspath(path)))
		try:
			return self._parseJson(path + ".bak")
		except (OSError, ValueError):
			return {}

	def _mayWrite(self, path: str) -> bool:
		"""``False`` para los archivos que no se pudieron leer al cargar (no se pisan)."""
		if os.path.normcase(os.path.abspath(path)) in self._protectedPaths:
			log.warning("No se guarda %s: no se pudo leer al arrancar y se perderían sus valores", path)
			return False
		return True

	@staticmethod
	def _writeJson(path: str, data: dict) -> None:
		os.makedirs(os.path.dirname(path), exist_ok=True)
		tmp = path + ".tmp"
		with open(tmp, "w", encoding="utf-8") as f:
			json.dump(data, f, ensure_ascii=False, indent="\t", sort_keys=True)
		if os.path.isfile(path):
			# Copia de seguridad de la última versión buena antes de sustituirla.
			try:
				with open(path, encoding="utf-8-sig") as f:
					json.load(f)
				shutil.copy2(path, path + ".bak")
			except (OSError, ValueError):
				pass
		os.replace(tmp, path)

	def _loadConfigData(self, path: str, label: str) -> tuple[dict, int]:
		data = self._readJson(path)
		fileVersion = migrations.getVersion(data)
		migrated = migrations.migrate(data)
		if migrated:
			log.info("%s migrado desde la versión %d del esquema", label, migrated[0])
		for issue in validation.validate(data, self.defaults):
			self.loadIssues.append(f"{label}: {issue}")
			log.warning("Configuración corregida (%s): %s", label, issue)
		return data, max(fileVersion, schema.SCHEMA_VERSION)

	def _versioned(self, data: dict, version: int) -> dict:
		out = dict(data)
		out[migrations.VERSION_KEY] = version
		return out

	def load(self) -> None:
		with self._lock:
			self.loadIssues = []
			self.recoveredFiles = []
			self.unreadableFiles = []
			self._protectedPaths = set()
			self.base, self.baseFileVersion = self._loadConfigData(self.configFile, "config.json")
			self.profiles = {}
			try:
				for fn in sorted(os.listdir(paths.profilesDir())):
					if fn.lower().endswith(".json"):
						name = fn[:-5]
						data, version = self._loadConfigData(os.path.join(paths.profilesDir(), fn), fn)
						p = Profile(name, data)
						p.fileVersion = version
						self.profiles[name] = p
			except FileNotFoundError:
				pass
			self.triggers = {k: v for k, v in self._readJson(self.triggersFile).items() if isinstance(v, str)}
			meta = self._readJson(self.metaFile)
			self.profileMeta = {k: dict(v) for k, v in meta.items() if isinstance(v, dict) and k in self.profiles}
			self.triggeredProfiles = [n for n in self.triggeredProfiles if n in self.profiles]
			if self.manualProfile not in self.profiles:
				self.manualProfile = None
			self.baseDirty = False
		post_configReset.notify()

	def _writeMeta(self) -> None:
		if self.readOnly or not self._mayWrite(self.metaFile):
			return
		try:
			self._writeJson(self.metaFile, {k: v for k, v in self.profileMeta.items() if k in self.profiles})
		except OSError:
			log.exception("No se pudieron guardar los datos de los perfiles")

	def save(self) -> None:
		if self.readOnly:
			log.info("Configuración de solo lectura (modo seguro): no se guarda")
			return
		pre_configSave.notify()
		with self._lock:
			try:
				if self._mayWrite(self.configFile):
					self._writeJson(self.configFile, self._versioned(_prune(self.base, self.defaults), self.baseFileVersion))
				for p in self.profiles.values():
					if self.isProfileReadOnly(p.name) or not self._mayWrite(p.fileName):
						continue
					self._writeJson(p.fileName, self._versioned(p.data, p.fileVersion))
					p.dirty = False
				if self._mayWrite(self.triggersFile):
					self._writeJson(self.triggersFile, self.triggers)
				self._writeMeta()
				self.baseDirty = False
			except OSError:
				log.exception("No se pudo guardar la configuración")
				raise
		post_configSave.notify()

	def resetToFactoryDefaults(self) -> None:
		"""Vuelve a los valores de fábrica (se puede deshacer con :meth:`undoFactoryReset`, #19575)."""
		with self._lock:
			self._undoReset = (copy.deepcopy(self.base), self.manualProfile, list(self.triggeredProfiles))
			self.base = {}
			self.manualProfile = None
			self.triggeredProfiles = []
			self.baseDirty = True
		post_configReset.notify()
		post_configProfileSwitch.notify()

	@property
	def canUndoFactoryReset(self) -> bool:
		return self._undoReset is not None

	def undoFactoryReset(self) -> bool:
		"""Recupera la configuración anterior al último restablecimiento."""
		with self._lock:
			if self._undoReset is None:
				return False
			base, manual, triggered = self._undoReset
			self._undoReset = None
			self.base = base
			self.manualProfile = manual if manual in self.profiles else None
			self.triggeredProfiles = [n for n in triggered if n in self.profiles]
			self.baseDirty = True
		post_configReset.notify()
		post_configProfileSwitch.notify()
		return True

	def revertToSaved(self) -> None:
		manual = self.manualProfile
		self.load()
		if manual in self.profiles:
			self.manualProfile = manual
		post_configProfileSwitch.notify()

	# --- perfiles ---
	def createProfile(self, name: str, copyFrom: str | None = None) -> Profile:
		if not isValidProfileName(name):
			raise ValueError("Nombre de perfil no válido")
		if name in self.profiles:
			raise ValueError("Ya existe un perfil con ese nombre")
		data = copy.deepcopy(self.profiles[copyFrom].data) if copyFrom in self.profiles else {}
		p = Profile(name, data)
		self.profiles[name] = p
		if not self.readOnly:
			self._writeJson(p.fileName, self._versioned(p.data, p.fileVersion))
		return p

	def deleteProfile(self, name: str) -> None:
		p = self.profiles.pop(name, None)
		if not p:
			return
		if not self.readOnly:
			for fn in (p.fileName, p.fileName + ".bak"):
				try:
					os.remove(fn)
				except OSError:
					pass
		self.triggers = {k: v for k, v in self.triggers.items() if v != name}
		self.profileMeta.pop(name, None)
		self._writeMeta()
		if self.manualProfile == name:
			self.manualProfile = None
		if name in self.triggeredProfiles:
			self.triggeredProfiles.remove(name)
		post_configProfileSwitch.notify()

	def renameProfile(self, old: str, new: str) -> None:
		if not isValidProfileName(new) or new in self.profiles:
			raise ValueError("Nombre de perfil no válido o repetido")
		p = self.profiles.pop(old)
		if not self.readOnly:
			try:
				os.remove(p.fileName)
			except OSError:
				pass
		p.name = new
		self.profiles[new] = p
		if not self.readOnly:
			self._writeJson(p.fileName, self._versioned(p.data, p.fileVersion))
		self.triggers = {k: (new if v == old else v) for k, v in self.triggers.items()}
		if old in self.profileMeta:
			self.profileMeta[new] = self.profileMeta.pop(old)
			self._writeMeta()
		if self.manualProfile == old:
			self.manualProfile = new
		self.triggeredProfiles = [new if n == old else n for n in self.triggeredProfiles]

	def setManualProfile(self, name: str | None) -> None:
		self.manualProfile = name if name in self.profiles else None
		post_configProfileSwitch.notify()

	def setTrigger(self, trigger: str, profileName: str | None) -> None:
		if profileName:
			self.triggers[trigger] = profileName
		else:
			self.triggers.pop(trigger, None)

	def enterTrigger(self, trigger: str) -> None:
		if trigger not in self.activeTriggers:
			self.activeTriggers.add(trigger)
			post_triggerChange.notify(trigger=trigger, entered=True)
		name = self.triggers.get(trigger)
		if name and name in self.profiles and name not in self.triggeredProfiles:
			self.triggeredProfiles.append(name)
			if self.isProfileEnabled(name) and self.triggersEnabled:
				post_configProfileSwitch.notify()

	def exitTrigger(self, trigger: str) -> None:
		if trigger in self.activeTriggers:
			self.activeTriggers.discard(trigger)
			post_triggerChange.notify(trigger=trigger, entered=False)
		name = self.triggers.get(trigger)
		if name and name in self.triggeredProfiles:
			# Otro disparador activo puede seguir usando el mismo perfil.
			if any(self.triggers.get(t) == name for t in self.activeTriggers):
				return
			self.triggeredProfiles.remove(name)
			if self.isProfileEnabled(name) and self.triggersEnabled:
				post_configProfileSwitch.notify()

	def exitAllAppTriggers(self) -> None:
		self._exitTriggersWithPrefix(APP_TRIGGER_PREFIX)

	def exitAllDomainTriggers(self) -> None:
		self._exitTriggersWithPrefix(DOMAIN_TRIGGER_PREFIX)

	def _exitTriggersWithPrefix(self, prefix: str) -> None:
		for trig in [t for t in self.activeTriggers if t.startswith(prefix)]:
			self.exitTrigger(trig)
		changed = False
		for trig, name in self.triggers.items():
			if trig.startswith(prefix) and name in self.triggeredProfiles and not any(self.triggers.get(t) == name for t in self.activeTriggers):
				self.triggeredProfiles.remove(name)
				changed = True
		if changed:
			post_configProfileSwitch.notify()

	def findDomainTrigger(self, domain: str) -> str | None:
		"""Disparador de dominio que corresponde a ``domain`` (o a un dominio padre)."""
		domain = (domain or "").lower()
		while domain:
			trig = DOMAIN_TRIGGER_PREFIX + domain
			if trig in self.triggers:
				return trig
			if "." not in domain:
				break
			domain = domain.split(".", 1)[1]
		return None


conf = ConfigManager()


def registerDefaults(section: str, values: dict) -> None:
	conf.registerDefaults(section, values)
