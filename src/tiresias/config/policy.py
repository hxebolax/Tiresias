"""Política corporativa y modo seguro.

Un administrador puede dejar un archivo ``policy.json`` en la carpeta del
programa (junto a ``Tiresias.exe``) para fijar opciones y limitar funciones
en todos los usuarios del equipo (#16599, #9284, #18018). Ejemplo::

	{
		"lockedSettings": {
			"general.language": "es",
			"update.autoCheck": false,
			"speech.synth": "espeak"
		},
		"blockedAddons": ["miComplemento"],
		"allowAddonInstall": false,
		"allowAddonStore": false,
		"allowUpdateCheck": false,
		"allowPythonConsole": false,
		"allowFactoryReset": true,
		"allowCreatePortable": true,
		"distributionUrl": "https://intranet/tiresias",
		"updateUrl": "https://intranet/tiresias/actualizacion.json",
		"addonCatalogUrl": "https://intranet/tiresias/catalogo.json",
		"message": "Configuración gestionada por el departamento de informática."
	}

- ``lockedSettings``: opciones con un valor fijo. Se aplican por encima de
  todos los perfiles, no se pueden cambiar y aparecen desactivadas en Opciones.
- ``blockedAddons``: complementos que no se cargan nunca.
- ``allow*``: funciones permitidas (todas lo están si no se indica).

El **modo seguro** (``--secure``) aplica además sus propias restricciones:
la configuración es de solo lectura y se lee de la configuración del sistema
(``systemConfig`` en la carpeta del programa), no se cargan complementos y
no hay consola de Python, tienda, actualizaciones ni acceso a archivos.
"""

from __future__ import annotations

import json
import os
from typing import Any

from .. import paths
from ..log import getLogger

log = getLogger("policy")

POLICY_FILE = "policy.json"

#: Funciones que se pueden limitar y si se permiten por defecto.
FEATURES = {
	"addonInstall": "allowAddonInstall",
	"addonStore": "allowAddonStore",
	"updateCheck": "allowUpdateCheck",
	"pythonConsole": "allowPythonConsole",
	"factoryReset": "allowFactoryReset",
	"createPortable": "allowCreatePortable",
	"install": "allowInstall",
	"openDataFolder": "allowOpenDataFolder",
	"saveConfiguration": "allowSaveConfiguration",
}

#: Funciones desactivadas siempre en modo seguro.
SECURE_MODE_BLOCKED = {
	"addonInstall",
	"addonStore",
	"updateCheck",
	"pythonConsole",
	"factoryReset",
	"createPortable",
	"install",
	"openDataFolder",
	"saveConfiguration",
	# Abrir archivos, carpetas o direcciones (manual, ayuda, Explorador...) y
	# los cuadros de abrir o guardar archivos: en el escritorio seguro lanzarían
	# programas con la cuenta SYSTEM (ver secure_env.installSecureModeGuards).
	"openFiles",
	"fileDialogs",
	"logViewer",
	"remoteAccess",
	"ai",
	# «Volver a <lector>»: en el escritorio seguro iniciaría NVDA o JAWS como SYSTEM.
	"launchReaders",
}


class Policy:
	def __init__(self, data: dict | None = None, path: str | None = None) -> None:
		self.path = path
		self.data: dict = data or {}
		self.secureMode = False

	# --------------------------------------------------------- carga
	@classmethod
	def load(cls, path: str | None = None) -> "Policy":
		path = path or os.path.join(paths.APP_DIR, POLICY_FILE)
		try:
			with open(path, encoding="utf-8-sig") as f:
				data = json.load(f)
			if not isinstance(data, dict):
				raise ValueError("la política debe ser un objeto JSON")
			log.info("Política corporativa cargada de %s", path)
			return cls(data, path)
		except FileNotFoundError:
			return cls({}, None)
		except (OSError, ValueError):
			# Una política dañada no debe dejar el equipo sin restricciones
			# silenciosamente: se registra y se aplica una política vacía.
			log.exception("No se pudo leer la política %s", path)
			return cls({}, None)

	@property
	def active(self) -> bool:
		return bool(self.data) or self.secureMode

	@property
	def message(self) -> str:
		return str(self.data.get("message", "") or "")

	# --------------------------------------------------------- opciones bloqueadas
	@property
	def lockedSettings(self) -> dict[tuple[str, ...], Any]:
		raw = self.data.get("lockedSettings") or {}
		out: dict[tuple[str, ...], Any] = {}
		if isinstance(raw, dict):
			for k, v in raw.items():
				parts = tuple(p for p in str(k).split(".") if p)
				if len(parts) >= 2:
					out[parts] = v
		return out

	def lockedLayer(self) -> dict:
		"""Capa de configuración con los valores bloqueados."""
		layer: dict = {}
		for parts, value in self.lockedSettings.items():
			node = layer
			for p in parts[:-1]:
				node = node.setdefault(p, {})
			node[parts[-1]] = value
		return layer

	def isLocked(self, path: tuple[str, ...]) -> bool:
		locked = self.lockedSettings
		for i in range(1, len(path) + 1):
			if path[:i] in locked:
				return True
		return False

	# --------------------------------------------------------- complementos y funciones
	@property
	def blockedAddons(self) -> set[str]:
		raw = self.data.get("blockedAddons") or []
		return {str(a) for a in raw} if isinstance(raw, list) else set()

	def isAddonBlocked(self, addonId: str) -> bool:
		return addonId in self.blockedAddons

	def isAllowed(self, feature: str) -> bool:
		if self.secureMode and feature in SECURE_MODE_BLOCKED:
			return False
		key = FEATURES.get(feature)
		if key is None:
			return True
		return bool(self.data.get(key, True))

	def url(self, kind: str) -> str:
		"""URL fijada por la política: ``distribution`` (servidor base), ``update`` o ``addonCatalog``."""
		return str(self.data.get(f"{kind}Url", "") or "")


#: Política en vigor (la carga ``config.conf.load``).
policy = Policy()


def isAllowed(feature: str) -> bool:
	return policy.isAllowed(feature)


def blockedMessage() -> str:
	"""Texto para explicar por qué una función no está disponible."""
	from ..i18n import _

	if policy.secureMode:
		return _("Esta función no está disponible en modo seguro.")
	msg = _("El administrador del equipo ha desactivado esta función.")
	if policy.message:
		msg += "\n" + policy.message
	return msg
