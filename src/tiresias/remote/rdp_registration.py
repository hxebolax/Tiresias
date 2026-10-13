"""Registro del complemento de Escritorio remoto para el usuario actual (HKCU).

El cliente de Escritorio remoto (``mstsc.exe``) carga al conectarse los
complementos de canal virtual dinámico que aparecen en
``HKCU\\Software\\Microsoft\\Terminal Server Client\\Default\\AddIns\\<nombre>``
(valor ``Name`` = CLSID). El CLSID se registra como servidor COM en proceso
en ``HKCU\\Software\\Classes\\CLSID`` (la vista de 64 bits, para el
``mstsc.exe`` normal) y en ``HKCU\\Software\\Classes\\WOW6432Node\\CLSID``
(lo que ve el ``mstsc.exe`` de 32 bits de ``SysWOW64``). No hace falta ser
administrador.

La misma clave ``AddIns`` sirve para los clientes que cargan complementos de
``mstsc.exe``: la aplicación Windows App / Escritorio remoto de Azure
(``msrdc.exe``) y Parallels Client. Para Omnissa (VMware) Horizon Client se
añaden los valores ``View Enabled`` (hasta la versión 2406) y ``Horizon
Enabled`` (2412 y posteriores) = 1, según la guía del SDK «RDPVCBridge» de
Omnissa; ``mstsc.exe`` los ignora.

Citrix Workspace app para Windows (:class:`CitrixRegistration`) carga los
mismos complementos de canal virtual dinámico de Microsoft por su «adaptador
DVC» (``vddvc0n.dll``) si aparecen en su configuración de usuario:
``HKCU\\Software\\Citrix\\ICA Client\\Engine\\Configuration\\Advanced\\Modules``,
subclave ``DVCPlugin_<nombre>`` (``DvcNames`` y ``PluginClassId``) y el
nombre añadido a la lista ``DvcPlugins`` de la subclave ``DVCAdapter``.
Citrix crea esa configuración de usuario al abrir la primera sesión.

Solo se registra cuando el usuario marca «Recibir la voz de los equipos
remotos» (y, para Citrix, «Cargar el complemento también en Citrix
Workspace»); al desmarcarlas, y al desinstalar, se borra todo.

Las pruebas usan otra raíz (por ejemplo ``Software\\TiresiasPruebas\\Software``);
también se puede cambiar con la variable de entorno ``TIRESIAS_RDP_REGROOT``.
"""

from __future__ import annotations

import os
import winreg
from typing import Callable

from ..log import getLogger

log = getLogger("rdp")

CLSID = "{8E634465-D682-43F3-8342-0381D3C85B3E}"
ADDIN_NAME = "TiresiasRdp"
DLL_NAME = "tiresiasRdpClient.dll"
DESCRIPTION = "Tiresias: voz y braille por Escritorio remoto"
ARCHES = ("x64", "x86")
#: Valores de la clave AddIns con los que Omnissa Horizon Client carga el complemento.
HORIZON_VALUES = ("View Enabled", "Horizon Enabled")

_VIEW = winreg.KEY_WOW64_64KEY


def defaultRoot() -> str:
	return os.environ.get("TIRESIAS_RDP_REGROOT") or "Software"


def dllPath(arch: str, appDir: str | None = None) -> str:
	"""Ruta de la biblioteca de cada arquitectura (``<programa>\\data\\rdp\\<arq>``).

	``appDir`` es la carpeta del programa (la que contiene ``data``); por
	defecto, la de esta copia de Tiresias.
	"""
	if appDir is None:
		from .. import paths

		return os.path.join(paths.rdpBinDir(), arch, DLL_NAME)
	return os.path.join(appDir, "data", "rdp", arch, DLL_NAME)


class RdpRegistration:
	def __init__(self, root: str | None = None) -> None:
		self.root = (root or defaultRoot()).rstrip("\\")

	# ------------------------------------------------------------------ rutas
	def classKey(self, arch: str) -> str:
		node = "Classes\\CLSID" if arch == "x64" else "Classes\\WOW6432Node\\CLSID"
		return f"{self.root}\\{node}\\{CLSID}"

	@property
	def addinKey(self) -> str:
		return f"{self.root}\\Microsoft\\Terminal Server Client\\Default\\AddIns\\{ADDIN_NAME}"

	# ------------------------------------------------------------------ consulta
	@staticmethod
	def _readDefault(path: str) -> str | None:
		try:
			with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | _VIEW) as k:
				value, _t = winreg.QueryValueEx(k, "")
				return str(value)
		except OSError:
			return None

	def registeredPaths(self) -> dict[str, str]:
		"""Biblioteca registrada para cada arquitectura (solo las que hay)."""
		out = {}
		for arch in ARCHES:
			p = self._readDefault(self.classKey(arch) + "\\InprocServer32")
			if p:
				out[arch] = p
		return out

	def addinRegistered(self) -> bool:
		try:
			with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.addinKey, 0, winreg.KEY_READ | _VIEW) as k:
				value, _t = winreg.QueryValueEx(k, "Name")
				return str(value).upper() == CLSID
		except OSError:
			return False

	def isRegistered(self) -> bool:
		return self.addinRegistered() and bool(self.registeredPaths())

	def pointsTo(self, folder: str) -> bool:
		"""``True`` si alguna biblioteca registrada está dentro de ``folder``."""
		base = os.path.normcase(os.path.abspath(folder)) + os.sep
		return any(os.path.normcase(os.path.abspath(p)).startswith(base) for p in self.registeredPaths().values())

	# ------------------------------------------------------------------ cambios
	def register(self, dlls: dict[str, str]) -> list[str]:
		"""Registra las bibliotecas que existan. Devuelve las arquitecturas registradas.

		Lanza :class:`FileNotFoundError` si no existe ninguna.
		"""
		done = []
		for arch in ARCHES:
			path = dlls.get(arch)
			if not path or not os.path.isfile(path):
				# Sin biblioteca de esa arquitectura: no se deja un registro roto.
				self._deleteTree(self.classKey(arch))
				continue
			key = self.classKey(arch)
			with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_WRITE | _VIEW) as k:
				winreg.SetValueEx(k, "", 0, winreg.REG_SZ, DESCRIPTION)
			with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key + "\\InprocServer32", 0, winreg.KEY_WRITE | _VIEW) as k:
				winreg.SetValueEx(k, "", 0, winreg.REG_SZ, os.path.abspath(path))
				winreg.SetValueEx(k, "ThreadingModel", 0, winreg.REG_SZ, "Free")
			done.append(arch)
		if not done:
			raise FileNotFoundError(f"No se encuentra {DLL_NAME}")
		with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.addinKey, 0, winreg.KEY_WRITE | _VIEW) as k:
			winreg.SetValueEx(k, "Name", 0, winreg.REG_SZ, CLSID)
			# Omnissa Horizon Client solo carga los complementos marcados así.
			for name in HORIZON_VALUES:
				winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, 1)
		log.info("Complemento de Escritorio remoto registrado (%s) en HKCU\\%s", ", ".join(done), self.root)
		return done

	def horizonEnabled(self) -> bool:
		"""``True`` si la clave AddIns tiene los valores que lee Horizon Client."""
		try:
			with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.addinKey, 0, winreg.KEY_READ | _VIEW) as k:
				return all(winreg.QueryValueEx(k, name)[0] == 1 for name in HORIZON_VALUES)
		except OSError:
			return False

	def unregister(self) -> bool:
		"""Borra el registro. Devuelve ``True`` si había algo."""
		had = self.addinRegistered() or bool(self.registeredPaths())
		self._deleteTree(self.addinKey)
		for arch in ARCHES:
			self._deleteTree(self.classKey(arch))
		if had:
			log.info("Complemento de Escritorio remoto desregistrado de HKCU\\%s", self.root)
		return had

	@staticmethod
	def _deleteTree(path: str) -> None:
		try:
			with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | winreg.KEY_WRITE | _VIEW) as k:
				while True:
					try:
						sub = winreg.EnumKey(k, 0)
					except OSError:
						break
					RdpRegistration._deleteTree(f"{path}\\{sub}")
		except FileNotFoundError:
			return
		try:
			winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, path, _VIEW, 0)
		except FileNotFoundError:
			pass


# ====================================================================== Citrix Workspace
CITRIX_PLUGIN = "TiresiasRdp"
CITRIX_MODULES = "Citrix\\ICA Client\\Engine\\Configuration\\Advanced\\Modules"
CITRIX_ADAPTER = "DVCAdapter"
CITRIX_PLUGINS_VALUE = "DvcPlugins"


def _citrixInstalled() -> bool:
	"""Citrix Workspace app (no la de Microsoft Store) está instalada en el equipo o para el usuario."""
	for hive, path in ((winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\Citrix\\ICA Client"), (winreg.HKEY_CURRENT_USER, "Software\\Citrix\\ICA Client")):
		for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
			try:
				winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view).Close()
				return True
			except OSError:
				continue
	return False


class CitrixRegistration:
	"""El complemento en la configuración de usuario de Citrix Workspace app (HKCU).

	Necesita el registro COM de :class:`RdpRegistration` (mismo CLSID): Citrix
	crea el objeto como ``mstsc.exe``, con la arquitectura de ``wfica32.exe``
	(32 bits hasta ahora; 64 bits en las versiones nuevas).
	"""

	#: Estados de :meth:`state`.
	NOT_INSTALLED = "notInstalled"
	NO_SESSION = "noSession"
	READY = "ready"
	REGISTERED = "registered"

	def __init__(self, root: str | None = None, installed: Callable[[], bool] | None = None) -> None:
		self.root = (root or defaultRoot()).rstrip("\\")
		self._installed = installed or _citrixInstalled

	@property
	def modulesKey(self) -> str:
		return f"{self.root}\\{CITRIX_MODULES}"

	@property
	def adapterKey(self) -> str:
		return f"{self.modulesKey}\\{CITRIX_ADAPTER}"

	@property
	def pluginKey(self) -> str:
		return f"{self.modulesKey}\\DVCPlugin_{CITRIX_PLUGIN}"

	# ------------------------------------------------------------------ consulta
	def _plugins(self) -> tuple[list[str], int] | None:
		"""Lista ``DvcPlugins`` y su tipo; ``None`` si Citrix aún no ha creado la configuración del usuario."""
		try:
			with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.adapterKey, 0, winreg.KEY_READ | _VIEW) as k:
				value, kind = winreg.QueryValueEx(k, CITRIX_PLUGINS_VALUE)
		except OSError:
			return None
		if kind not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) or not isinstance(value, str):
			return None
		return [p.strip() for p in value.split(",") if p.strip()], kind

	def _pluginClassId(self) -> str | None:
		try:
			with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.pluginKey, 0, winreg.KEY_READ | _VIEW) as k:
				return str(winreg.QueryValueEx(k, "PluginClassId")[0])
		except OSError:
			return None

	def isRegistered(self) -> bool:
		plugins = self._plugins()
		return plugins is not None and CITRIX_PLUGIN in plugins[0] and (self._pluginClassId() or "").upper() == CLSID

	def state(self) -> str:
		if self.isRegistered():
			return self.REGISTERED
		if self._plugins() is not None:
			return self.READY
		return self.NO_SESSION if self._installed() else self.NOT_INSTALLED

	# ------------------------------------------------------------------ cambios
	def register(self) -> bool:
		"""Añade el complemento. ``False`` si Citrix aún no tiene configuración de usuario."""
		plugins = self._plugins()
		if plugins is None:
			return False
		names, kind = plugins
		with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.pluginKey, 0, winreg.KEY_WRITE | _VIEW) as k:
			winreg.SetValueEx(k, "DvcNames", 0, winreg.REG_SZ, CITRIX_PLUGIN)
			winreg.SetValueEx(k, "PluginClassId", 0, winreg.REG_SZ, CLSID)
		if CITRIX_PLUGIN not in names:
			# Se conservan los complementos que ya había (los de Citrix y otros).
			with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.adapterKey, 0, winreg.KEY_SET_VALUE | _VIEW) as k:
				winreg.SetValueEx(k, CITRIX_PLUGINS_VALUE, 0, kind, ",".join(names + [CITRIX_PLUGIN]))
		log.info("Complemento de Escritorio remoto registrado en Citrix Workspace (HKCU\\%s)", self.modulesKey)
		return True

	def unregister(self) -> bool:
		"""Quita el complemento de la configuración de Citrix. ``True`` si estaba."""
		had = False
		plugins = self._plugins()
		if plugins is not None and CITRIX_PLUGIN in plugins[0]:
			names, kind = plugins
			with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.adapterKey, 0, winreg.KEY_SET_VALUE | _VIEW) as k:
				winreg.SetValueEx(k, CITRIX_PLUGINS_VALUE, 0, kind, ",".join(n for n in names if n != CITRIX_PLUGIN))
			had = True
		if self._pluginClassId() is not None:
			had = True
		RdpRegistration._deleteTree(self.pluginKey)
		if had:
			log.info("Complemento de Escritorio remoto quitado de Citrix Workspace")
		return had


def unregisterIfFrom(folder: str, root: str | None = None) -> bool:
	"""Desinstalación: borra el registro si apunta a la copia de ``folder``.

	También quita la entrada de Citrix Workspace, que usa el mismo objeto COM.
	"""
	reg = RdpRegistration(root)
	try:
		if reg.pointsTo(folder):
			CitrixRegistration(root).unregister()
			return reg.unregister()
	except OSError:
		log.exception("No se pudo quitar el complemento de Escritorio remoto")
	return False
