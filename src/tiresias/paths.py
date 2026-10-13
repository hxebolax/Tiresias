"""Rutas del programa.

Tiresias es portable: todo lo que el lector genera o necesita vive en la
carpeta ``data`` situada junto al ejecutable (versión compilada) o en la raíz
del proyecto (ejecución desde código). Puede cambiarse con la variable de
entorno ``TIRESIAS_DATA`` o el argumento ``--data``.

Hay dos carpetas ``data``:

- :data:`DATA_DIR`: los datos del usuario (configuración, registros, caché,
  temporales, complementos...). Es la que cambian ``--data`` y la copia
  instalada (``%APPDATA%\\Tiresias``).
- :data:`PROGRAM_DATA_DIR`: lo que acompaña al programa y no cambia
  (``data\\controller``, ``data\\rdp``, ``data\\synthDrivers``, ``data\\louis``,
  ``data\\locale``, ``data\\docs``, ``data\\images``). Siempre es la de junto
  al ejecutable (o la del proyecto). Dentro de ``src`` y ``lib`` solo hay código.
"""

from __future__ import annotations

import os
import sys

FROZEN: bool = bool(getattr(sys, "frozen", False))

if FROZEN:
	APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
	SOURCE_DIR = APP_DIR
else:
	# src/tiresias/paths.py -> raíz del proyecto
	SOURCE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	APP_DIR = os.path.dirname(SOURCE_DIR)

#: Marca que deja el instalador junto al ejecutable de una copia instalada.
INSTALLED_MARKER = "instalado.json"
#: Carpeta de la configuración del sistema (modo seguro), en la carpeta del programa.
SYSTEM_CONFIG_DIR = os.path.join(APP_DIR, "systemConfig")


def isInstalledCopy() -> bool:
	"""``True`` si se ejecuta una copia instalada (no portable) de Tiresias."""
	return FROZEN and os.path.isfile(os.path.join(APP_DIR, INSTALLED_MARKER))


def userDataDir() -> str:
	"""Carpeta de datos del usuario de una copia instalada (Tiresias dentro de ``%APPDATA%``)."""
	base = os.environ.get("APPDATA") or os.path.expanduser("~")
	return os.path.join(base, "Tiresias")


def _defaultDataDir() -> str:
	if os.environ.get("TIRESIAS_DATA"):
		return os.environ["TIRESIAS_DATA"]
	if isInstalledCopy():
		# La carpeta del programa (Program Files) no se puede escribir.
		return userDataDir()
	return os.path.join(APP_DIR, "data")


DATA_DIR = _defaultDataDir()
#: Datos que acompañan al programa (símbolos, complementos incluidos...).
PROGRAM_DATA_DIR = os.path.join(APP_DIR, "data")
#: Carpeta de configuración elegida con ``--config-path`` o el modo seguro.
_configDirOverride: str | None = None


def setDataDir(path: str) -> None:
	"""Cambia la carpeta de datos (debe llamarse antes de iniciar el núcleo)."""
	global DATA_DIR
	DATA_DIR = os.path.abspath(path)


def setConfigDir(path: str | None) -> None:
	"""Usa otra carpeta para la configuración (``--config-path``, modo seguro)."""
	global _configDirOverride
	_configDirOverride = os.path.abspath(path) if path else None


def data(*parts: str) -> str:
	"""Devuelve una ruta dentro de la carpeta de datos."""
	return os.path.join(DATA_DIR, *parts)


def configDir() -> str:
	return _configDirOverride or data("config")


def profilesDir() -> str:
	return os.path.join(configDir(), "profiles")


def logsDir() -> str:
	return data("logs")


def addonsDir() -> str:
	return data("addons")


def addonDataDir(addonId: str) -> str:
	"""Carpeta de datos de un complemento (``data\\addonsData\\<id>``), creada si no existe.

	Lo que un complemento guarda (bases de datos, cachés, grabaciones...) va
	aquí y no en su propia carpeta, que se sustituye al actualizarlo.
	"""
	p = data("addonsData", addonId)
	os.makedirs(p, exist_ok=True)
	return p


def cacheDir() -> str:
	return data("cache")


def soundsDir() -> str:
	return data("sounds")


def symbolsDir() -> str:
	return data("symbols")


def voicesDir() -> str:
	"""Voces neuronales descargadas (Piper), una subcarpeta por voz."""
	return data("voices")


def speechDictsDir() -> str:
	return data("speechDicts")


def brailleTablesDir() -> str:
	return data("brailleTables")


def labelsDir() -> str:
	return data("labels")


def tempDir() -> str:
	"""Archivos temporales de Tiresias (OCR, copias de Office, adjuntos...)."""
	return data("temp")


def comtypesCacheDir() -> str:
	"""Módulos de comtypes generados en la versión compilada (``data\\cache\\comtypes``)."""
	return os.path.join(cacheDir(), "comtypes")


def cleanTempDir(maxAgeHours: float = 24.0) -> None:
	"""Borra lo que quedó en ``data\\temp`` de sesiones anteriores (lo abierto se respeta)."""
	import shutil
	import time

	folder = tempDir()
	limit = time.time() - maxAgeHours * 3600
	try:
		entries = list(os.scandir(folder))
	except OSError:
		return
	for entry in entries:
		try:
			if entry.stat().st_mtime > limit:
				continue
			if entry.is_dir(follow_symlinks=False):
				shutil.rmtree(entry.path, ignore_errors=True)
			else:
				os.remove(entry.path)
		except OSError:
			pass


def programData(*parts: str) -> str:
	"""Ruta dentro de la carpeta ``data`` del programa (binarios y documentos que lo acompañan)."""
	return os.path.join(PROGRAM_DATA_DIR, *parts)


def controllerBinDir() -> str:
	"""Bibliotecas de la API de control (``data\\controller\\x64`` y ``x86``)."""
	return programData("controller")


def rdpBinDir() -> str:
	"""Complemento de Escritorio remoto para mstsc (``data\\rdp\\x64`` y ``x86``)."""
	return programData("rdp")


def espeakDir() -> str:
	"""eSpeak NG del programa (``data\\synthDrivers\\espeak``: DLL y ``espeak-ng-data``)."""
	return programData("synthDrivers", "espeak")


def docPath(name: str) -> str:
	"""Documento para el usuario o el desarrollador (novedades, catálogo, API de control...).

	En la versión compilada está en ``data\\docs``; desde el código, en ``docs``
	de la raíz del proyecto (si no se ha copiado a ``data\\docs``).
	"""
	path = programData("docs", name)
	if os.path.isfile(path):
		return path
	return os.path.join(APP_DIR, "docs", name)


def localeDir() -> str:
	"""Catálogos de traducción (``data\\locale\\<idioma>\\LC_MESSAGES\\tiresias.mo``)."""
	return programData("locale")


def louisDir() -> str:
	"""liblouis: ``data\\louis\\liblouis.dll`` y sus tablas (``data\\louis\\tables``)."""
	return programData("louis")


def manualPath() -> str:
	"""Manual de usuario. En la versión compilada está junto al ejecutable."""
	candidates = [
		os.path.join(APP_DIR, "Manual de usuario.html"),
		os.path.join(APP_DIR, "manual", "manual_usuario.html"),
	]
	for c in candidates:
		if os.path.isfile(c):
			return c
	return candidates[-1]


def ensureDataDirs() -> None:
	"""Crea las carpetas de datos que falten."""
	for d in (
		DATA_DIR,
		configDir(),
		profilesDir(),
		logsDir(),
		addonsDir(),
		cacheDir(),
		tempDir(),
		soundsDir(),
		voicesDir(),
		symbolsDir(),
		speechDictsDir(),
		brailleTablesDir(),
		labelsDir(),
	):
		try:
			os.makedirs(d, exist_ok=True)
		except OSError:
			pass
