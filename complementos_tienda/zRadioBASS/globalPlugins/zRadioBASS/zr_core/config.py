# -*- coding: utf-8 -*-
# Copyright (C) 2025-2026 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General GNU.

"""Configuración de zRadio BASS.

Hay dos tipos de datos:

- **Opciones** (las de la categoría «zRadio BASS» del cuadro de Opciones de
  Tiresias): se guardan en la configuración de Tiresias, sección
  ``zRadioBASS`` (``conf.registerDefaults``), y respetan los perfiles.
- **Estado** (volumen, silencio, última emisora, última pestaña, tamaño de
  la ventana, plugins desactivados...): se guarda al momento en
  ``data\\addonsData\\zRadioBASS\\estado.json``, como hacía el original con su
  ``config.json``, para que persista aunque Tiresias no guarde la
  configuración al salir.
"""

from __future__ import annotations

import ctypes
import json
import os
import threading
from ctypes import wintypes
from pathlib import Path
from typing import Any

from tiresias import paths
from tiresias.config import conf
from tiresias.log import getLogger

log = getLogger("zRadioBASS.config")

ADDON_ID = "zRadioBASS"
SECTION = "zRadioBASS"

#: Opciones (cuadro de Opciones de Tiresias) con sus valores de fábrica.
DEFAULTS: dict[str, Any] = {
	# General
	"checkInternetOnStart": True,
	"rememberLastStation": True,
	"resumeOnStart": False,
	"defaultCountry": "ES",
	"searchLimit": 10000,
	"hideBroken": False,
	# Reproducción
	"outputDevice": "",
	"volumeStep": 5,
	"autoReconnect": True,
	"announceTitle": False,
	"announceConnected": False,
	# Efectos
	"eqBass": 0,
	"eqMid": 0,
	"eqTreble": 0,
	"balance": 0,
	# Caché de la API
	"cacheEnabled": True,
	"cacheDays": 3,
	# Grabaciones
	"recordingDirectory": "",
}

#: Estado que se guarda al momento en ``estado.json``.
STATE_DEFAULTS: dict[str, Any] = {
	"volume": 50,
	"muted": False,
	"last_tab": 0,
	"window_width": 800,
	"window_height": 600,
	"last_station_name": "",
	"last_station_url": "",
	"last_station_uuid": "",
	"disabled_plugins": [],
	"plugin_settings": {},
	"favorites_sort": 0,
	"favorites_category": -1,
	"search_category": 0,
	"search_order": "name",
	"search_reverse": False,
	"search_codec": "",
	"search_min_bitrate": 0,
}

_MAX_PATH = 260
_CSIDL_MYMUSIC = 13


def registerDefaults() -> None:
	conf.registerDefaults(SECTION, DEFAULTS)


def userMusicFolder() -> str:
	"""Carpeta «Música» del usuario (``""`` si no se puede averiguar)."""
	try:
		buf = ctypes.create_unicode_buffer(_MAX_PATH)
		shell32 = ctypes.WinDLL("shell32")
		shell32.SHGetFolderPathW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR]
		if shell32.SHGetFolderPathW(None, _CSIDL_MYMUSIC, None, 0, buf) == 0 and buf.value:
			return buf.value
	except Exception:
		log.debug("No se pudo obtener la carpeta Música", exc_info=True)
	return ""


class ConfigManager:
	"""Acceso a las opciones (``conf``) y al estado (``estado.json``).

	Las opciones y el estado se leen y escriben como atributos
	(``config.volume``, ``config.cacheEnabled``...). Se admiten también los
	nombres del complemento original (``cache_enabled``, ``recording_directory``...).
	"""

	_ALIASES = {
		"check_internet_on_start": "checkInternetOnStart",
		"remember_last_station": "rememberLastStation",
		"cache_enabled": "cacheEnabled",
		"cache_duration_days": "cacheDays",
		"recording_directory": "recordingDirectory",
		"default_country": "defaultCountry",
		"search_limit": "searchLimit",
	}

	def __init__(self, dataDir: str | None = None) -> None:
		registerDefaults()
		object.__setattr__(self, "_lock", threading.RLock())
		object.__setattr__(self, "_data_dir", Path(dataDir or paths.addonDataDir(ADDON_ID)))
		self._data_dir.mkdir(parents=True, exist_ok=True)
		object.__setattr__(self, "_state_path", self._data_dir / "estado.json")
		object.__setattr__(self, "_state", dict(STATE_DEFAULTS))
		self.load()

	# ------------------------------------------------------------- atributos
	def __getattr__(self, name: str) -> Any:
		name = ConfigManager._ALIASES.get(name, name)
		if name in DEFAULTS:
			try:
				return conf[SECTION][name]
			except KeyError:
				return DEFAULTS[name]
		state = self.__dict__.get("_state")
		if state is not None and name in STATE_DEFAULTS:
			return state.get(name, STATE_DEFAULTS[name])
		raise AttributeError(name)

	def __setattr__(self, name: str, value: Any) -> None:
		name = ConfigManager._ALIASES.get(name, name)
		if name in DEFAULTS:
			conf[SECTION][name] = value
		elif name in STATE_DEFAULTS:
			with self._lock:
				self._state[name] = value
		else:
			object.__setattr__(self, name, value)

	def get(self, key: str, default: Any = None) -> Any:
		try:
			return getattr(self, key)
		except AttributeError:
			return default

	def set(self, key: str, value: Any) -> None:
		"""Cambia un valor y guarda el estado."""
		setattr(self, key, value)
		self.save()

	def update(self, **kwargs: Any) -> None:
		for k, v in kwargs.items():
			setattr(self, k, v)
		self.save()

	# ------------------------------------------------------------- disco
	def load(self) -> bool:
		if not self._state_path.exists():
			return False
		try:
			with open(self._state_path, encoding="utf-8") as f:
				data = json.load(f)
		except (OSError, ValueError):
			log.warning("No se pudo leer %s; se usan los valores por defecto", self._state_path, exc_info=True)
			return False
		if not isinstance(data, dict):
			return False
		with self._lock:
			for k, v in data.items():
				if k in STATE_DEFAULTS and isinstance(v, type(STATE_DEFAULTS[k])):
					self._state[k] = v
		return True

	def save(self) -> bool:
		"""Guarda el estado en ``estado.json`` (escritura atómica)."""
		with self._lock:
			data = dict(self._state)
			tmp = str(self._state_path) + ".tmp"
			try:
				with open(tmp, "w", encoding="utf-8") as f:
					json.dump(data, f, indent=2, ensure_ascii=False)
				os.replace(tmp, self._state_path)
				return True
			except OSError:
				log.exception("No se pudo guardar el estado de zRadio BASS")
				return False

	def reset(self) -> None:
		"""Vuelve a los valores de fábrica (opciones y estado)."""
		for k, v in DEFAULTS.items():
			conf[SECTION][k] = v
		with self._lock:
			self._state.clear()
			self._state.update(STATE_DEFAULTS)
		self.save()

	def validate_volume(self, volume: int) -> int:
		return max(0, min(100, int(volume)))

	# ------------------------------------------------------------- carpetas
	@property
	def data_dir(self) -> Path:
		return self._data_dir

	@property
	def plugins_dir(self) -> Path:
		p = self._data_dir / "plugins"
		p.mkdir(parents=True, exist_ok=True)
		return p

	@property
	def cache_dir(self) -> Path:
		p = self._data_dir / "cache"
		p.mkdir(parents=True, exist_ok=True)
		return p

	@property
	def database_path(self) -> Path:
		return self._data_dir / "zradiobass.db"

	@property
	def recordings_dir(self) -> Path:
		"""Carpeta de grabaciones: la elegida en Opciones o la carpeta Música del usuario."""
		chosen = (self.recordingDirectory or "").strip()
		if chosen and os.path.isdir(chosen):
			return Path(chosen)
		music = userMusicFolder()
		if music and os.path.isdir(music):
			return Path(music)
		p = self._data_dir / "grabaciones"
		p.mkdir(parents=True, exist_ok=True)
		return p

	# ------------------------------------------------------------- última emisora
	def remember_station(self, name: str, url: str, uuid: str = "") -> None:
		if not self.rememberLastStation:
			return
		with self._lock:
			self._state["last_station_name"] = name or ""
			self._state["last_station_url"] = url or ""
			self._state["last_station_uuid"] = uuid or ""
		self.save()

	def plugin_settings(self, pluginId: str) -> dict:
		"""Diccionario de opciones de un plugin (se guarda con :meth:`save`)."""
		with self._lock:
			allSettings = self._state.setdefault("plugin_settings", {})
			return allSettings.setdefault(pluginId, {})


_config_instance: ConfigManager | None = None
_config_lock = threading.Lock()


def get_config() -> ConfigManager:
	"""Instancia compartida de la configuración."""
	global _config_instance
	with _config_lock:
		if _config_instance is None:
			_config_instance = ConfigManager()
		return _config_instance


def set_config(config: ConfigManager | None) -> None:
	"""Sustituye la instancia compartida (pruebas y descarga del complemento)."""
	global _config_instance
	with _config_lock:
		_config_instance = config
