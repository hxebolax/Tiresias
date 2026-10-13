"""Carga y gestión de módulos de aplicación."""

from __future__ import annotations

import ctypes
import importlib
import importlib.util
import os
import sys
import threading
import types
from ctypes import wintypes

from .. import winapi
from ..log import getLogger
from . import AppModule

log = getLogger("appModuleHandler")

_running: dict[int, AppModule] = {}
_lock = threading.RLock()
#: Carpetas extra con módulos de aplicación (de complementos): [(prefijo, ruta)].
_searchDirs: list[tuple[str, str]] = []
_lastForegroundApp: AppModule | None = None

#: Ejecutable (sin extensión, en minúsculas) → nombre del módulo que lo atiende.
#: Sirve para ejecutables con caracteres no válidos en Python y para
#: aplicaciones que comparten módulo.
EXECUTABLE_ALIASES: dict[str, str] = {
	# El signo + no es válido en un módulo de Python.
	"notepad++": "notepadplusplus",
	# Calculadora de Windows 11.
	"calculatorapp": "calculator",
	# Búsqueda y menú Inicio (Windows 10 y 11) comparten módulo.
	"searchapp": "searchhost",
	"searchui": "searchhost",
	"startmenuexperiencehost": "searchhost",
	# Configuración rápida de Windows 11 24H2.
	"shellhost": "shellexperiencehost",
	# Teclado táctil, panel de emojis e historial del portapapeles.
	"windowsinternal.composableshell.experiences.textinput.inputapp": "textinputhost",
	"lockapphost": "lockapp",
	# Editores basados en Visual Studio Code.
	"code - insiders": "code",
	"code-insiders": "code",
	"codium": "code",
	"vscodium": "code",
	"cursor": "code",
	"windsurf": "code",
	"antigravity": "code",
	"kiro": "code",
	"positron": "code",
	"azuredatastudio": "code",
	"azuredatastudio-insiders": "code",
	# Basados en Visual Studio.
	"ssms": "devenv",
	# Basados en Eclipse.
	"dbeaver": "eclipse",
	"springtoolsuite4": "eclipse",
	"sts": "eclipse",
	"zendstudio": "eclipse",
	"zend-eclipse-php": "eclipse",
	# Microsoft Teams (nuevo y clásico).
	"ms-teams": "teams",
	"msteams": "teams",
	# LibreOffice y OpenOffice.
	"soffice.bin": "soffice",
	"scalc": "soffice",
	"swriter": "soffice",
	"simpress": "soffice",
	# KiTTY es una variante de PuTTY.
	"kitty": "putty",
	# Reproductores.
	"foobar2000.x64": "foobar2000",
	"winamp64": "winamp",
	# Telegram y Discord (versiones alternativas).
	"telegram desktop": "telegram",
	"discordcanary": "discord",
	"discordptb": "discord",
	# Kindle para PC.
	"kindle for pc": "kindle",
	# Betterbird es una variante de Thunderbird (rev. 10.11).
	"betterbird": "thunderbird",
}

#: Procesos anfitriones: la aplicación real se deduce de otra forma.
HOST_PROCESSES = {"javaw", "java", "wwahost", "applicationframehost"}


def registerExecutableAlias(executableName: str, moduleName: str) -> None:
	"""Asocia un ejecutable a un módulo (para complementos)."""
	EXECUTABLE_ALIASES[executableName.lower()] = moduleName


def moduleNameForProcess(appName: str) -> str:
	low = appName.lower()
	alias = EXECUTABLE_ALIASES.get(low)
	if alias:
		return alias
	return low.replace(".", "_").replace(" ", "_").replace("-", "_").replace("+", "plus")


def addSearchDir(packageName: str, path: str) -> None:
	with _lock:
		if (packageName, path) not in _searchDirs:
			_searchDirs.insert(0, (packageName, path))


def clearSearchDirs() -> None:
	with _lock:
		_searchDirs.clear()


def _loadFromFile(fullName: str, path: str) -> types.ModuleType | None:
	try:
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
	except Exception:
		log.exception("Error cargando el módulo de aplicación %s", path)
		sys.modules.pop(fullName, None)
		return None


def _findModule(modName: str) -> types.ModuleType | None:
	# Los módulos de apoyo (``_office``, ``_chat``...) no son de ninguna aplicación.
	if not modName or modName.startswith("_") or modName in ("handler",):
		return None
	for pkg, folder in list(_searchDirs):
		for candidate in (os.path.join(folder, modName + ".py"), os.path.join(folder, modName)):
			if os.path.isfile(candidate) or os.path.isfile(os.path.join(candidate, "__init__.py")):
				fullName = f"{pkg}.{modName}"
				mod = sys.modules.get(fullName) or _loadFromFile(fullName, candidate)
				if mod is not None:
					return mod
	try:
		return importlib.import_module(f"{__package__}.{modName}")
	except ModuleNotFoundError as e:
		if e.name and e.name.endswith(modName):
			return None
		log.exception("Error importando el módulo de aplicación %s", modName)
	except Exception:
		log.exception("Error importando el módulo de aplicación %s", modName)
	return None


# ---------------------------------------------------------------- aplicaciones alojadas
def _processCommandLine(pid: int) -> list[str]:
	try:
		import psutil

		return psutil.Process(pid).cmdline()
	except Exception:
		return []


def _javaAppName(cmdline: list[str]) -> str:
	"""Nombre de la aplicación Java según su línea de órdenes (``-jar x.jar`` o clase principal)."""
	args = cmdline[1:]
	i = 0
	while i < len(args):
		a = args[i]
		if a == "-jar" and i + 1 < len(args):
			base = os.path.basename(args[i + 1])
			return os.path.splitext(base)[0].lower()
		if a in ("-cp", "-classpath", "--class-path", "-p", "--module-path"):
			i += 2
			continue
		if a.startswith("-"):
			i += 1
			continue
		# Primera palabra que no es opción: la clase principal.
		return a.rsplit(".", 1)[-1].lower()
	return ""


def _packageAppName(pid: int) -> str:
	"""Nombre de la aplicación empaquetada (wwahost) a partir de su AUMID."""
	kernel32 = ctypes.windll.kernel32
	h = kernel32.OpenProcess(winapi.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
	if not h:
		return ""
	try:
		length = wintypes.UINT(0)
		fn = getattr(kernel32, "GetApplicationUserModelId", None)
		if fn is None:
			return ""
		fn(h, ctypes.byref(length), None)
		if not length.value:
			return ""
		buf = ctypes.create_unicode_buffer(length.value)
		if fn(h, ctypes.byref(length), buf) != 0:
			return ""
		return packageNameFromAumid(buf.value)
	finally:
		kernel32.CloseHandle(h)


def packageNameFromAumid(aumid: str) -> str:
	"""``Microsoft.Kindle_8wekyb3d8bbwe!App`` → ``microsoft.kindle``."""
	family = aumid.split("!", 1)[0]
	return family.split("_", 1)[0].lower()


def getAppNameFromHost(pid: int, exeName: str | None = None) -> str:
	"""Nombre de la aplicación alojada en un proceso anfitrión (javaw, wwahost).

	Devuelve el nombre del ejecutable si el proceso no es un anfitrión o no se
	puede averiguar la aplicación.
	"""
	exeName = exeName if exeName is not None else winapi.getProcessName(pid)
	if exeName in ("javaw", "java"):
		name = _javaAppName(_processCommandLine(pid))
		return name or exeName
	if exeName == "wwahost":
		return _packageAppName(pid) or exeName
	return exeName


def _create(pid: int) -> AppModule:
	exeName = winapi.getProcessName(pid)
	appName = getAppNameFromHost(pid, exeName) if exeName in HOST_PROCESSES else exeName
	mod = None
	if appName:
		mod = _findModule(moduleNameForProcess(appName))
		if mod is None and appName != exeName:
			# Sin módulo para la aplicación alojada: el del anfitrión.
			mod = _findModule(moduleNameForProcess(exeName))
	cls = getattr(mod, "AppModule", None) if mod else None
	try:
		app = cls(pid, appName) if cls else AppModule(pid, appName)
	except Exception:
		log.exception("Error creando el módulo de aplicación de %s", appName)
		app = AppModule(pid, appName)
	log.debug("Módulo de aplicación para %s (%d): %r", appName, pid, app)
	return app


def getAppModuleForPid(pid: int) -> AppModule | None:
	if not pid:
		return None
	with _lock:
		app = _running.get(pid)
		# Windows reutiliza los PID: si el proceso de este módulo ya terminó, el PID
		# es de otro programa. Solo se comprueba con el handle propio del módulo
		# (barato); sin él (procesos protegidos) no se puede saber y se conserva.
		if app is not None and app.__dict__.get("_processHandle") and not app.isAlive:
			app = None
		if app is None:
			app = _create(pid)
			_running[pid] = app
		return app


_hostPidCache: dict[int, int] = {}


def _coreWindowPid(rootHwnd: int) -> int:
	"""Proceso de la ventana ``Windows.UI.Core.CoreWindow`` dentro de un marco UWP."""
	from ._office import findChildWindow

	child = findChildWindow(rootHwnd, "Windows.UI.Core.CoreWindow")
	if not child:
		return 0
	pid = winapi.getWindowProcessId(child)
	return pid if winapi.getProcessName(pid) != "applicationframehost" else 0


def getAppModuleForObject(obj) -> AppModule | None:
	"""Módulo de aplicación de un objeto accesible.

	Se usa el proceso de la ventana principal, así el contenido incrustado de
	otro proceso (WebView2 dentro de WhatsApp) usa el módulo de quien lo
	muestra. Las aplicaciones UWP dentro de ``ApplicationFrameHost`` usan el
	proceso que dibuja su contenido.
	"""
	from ..objects.base import HOSTED_CONTENT_PROCESSES

	pid = obj.processID
	hwnd = obj.windowHandle
	root = winapi.getAncestor(hwnd, winapi.GA_ROOT) if hwnd else 0
	if root:
		rootPid = winapi.getWindowProcessId(root)
		if rootPid:
			rootName = winapi.getProcessName(rootPid)
			if rootName == "applicationframehost":
				if not pid or winapi.getProcessName(pid) == "applicationframehost":
					hostPid = _hostPidCache.get(root)
					if not hostPid:
						hostPid = _coreWindowPid(root)
						if hostPid:
							_hostPidCache[root] = hostPid
						else:
							# La CoreWindow aún no está (la aplicación arranca) o se
							# separó del marco (minimizada): no se recuerda el marco
							# como aplicación, se vuelve a buscar la próxima vez.
							hostPid = rootPid
					pid = hostPid
				return getAppModuleForPid(pid)
			pid = rootPid
		if winapi.getProcessName(pid) in HOSTED_CONTENT_PROCESSES:
			hostPid = _hostPidCache.get(root)
			if hostPid is None:
				hostPid = obj._findHostProcessId() or pid
				_hostPidCache[root] = hostPid
			pid = hostPid
	return getAppModuleForPid(pid)


def getRunningModules() -> list[AppModule]:
	with _lock:
		return list(_running.values())


def cleanup() -> None:
	"""Descarga los módulos de procesos que ya terminaron."""
	with _lock:
		for pid, app in list(_running.items()):
			if not app.isAlive:
				try:
					app.terminate()
				except Exception:
					log.exception("Error terminando %r", app)
				del _running[pid]
		if len(_hostPidCache) > 200:
			_hostPidCache.clear()


def reloadAll() -> None:
	with _lock:
		for app in _running.values():
			try:
				app.terminate()
			except Exception:
				log.exception("Error terminando %r", app)
		_running.clear()
		_hostPidCache.clear()
		for name in list(sys.modules):
			if name.startswith(__package__ + ".") and name not in (__name__,) and not name.split(".")[-1].startswith("_"):
				del sys.modules[name]
			elif any(name.startswith(pkg + ".") for pkg, _p in _searchDirs):
				del sys.modules[name]


def handleForegroundApp(app: AppModule | None) -> None:
	"""Gestiona perfiles y avisos al cambiar de aplicación en primer plano."""
	global _lastForegroundApp
	if app is _lastForegroundApp:
		return
	from ..config import conf

	old = _lastForegroundApp
	_lastForegroundApp = app
	if old is not None:
		try:
			old.event_appModule_loseFocus()
		except Exception:
			log.exception("Error en loseFocus de %r", old)
		conf.exitTrigger(f"app:{old.appName}")
	if app is not None:
		conf.enterTrigger(f"app:{app.appName}")
		try:
			app.event_appModule_gainFocus()
		except Exception:
			log.exception("Error en gainFocus de %r", app)


def getForegroundApp() -> AppModule | None:
	return _lastForegroundApp


# ---------------------------------------------------------------- modo dormir
def setSleepMode(app: AppModule, state: bool, persist: bool = True) -> None:
	"""Activa o desactiva el modo dormir de una aplicación.

	Con ``persist`` se recuerda para la próxima vez que se abra (lista
	``appModules.sleepApps`` de la configuración).
	"""
	from ..config import conf

	app.sleepMode = bool(state)
	with _lock:
		for other in _running.values():
			if other is not app and other.appName == app.appName:
				other.sleepMode = bool(state)
	if persist:
		# Sin distinguir mayúsculas, como al cargar el módulo: si el usuario
		# escribió «WhatsApp.Root» en el panel, desactivarlo debe quitarlo.
		low = app.appName.lower()
		apps = [n for n in (conf["appModules"]["sleepApps"] or []) if n.lower() != low]
		if state:
			apps.append(app.appName)
		conf["appModules"]["sleepApps"] = apps


def isSleepPersistent(app: AppModule) -> bool:
	from ..config import conf

	low = app.appName.lower()
	return any(n.lower() == low for n in (conf["appModules"]["sleepApps"] or []))


# ---------------------------------------------------------------- inicio
def initialize() -> None:
	"""Registra el panel «Aplicaciones» del diálogo de opciones."""
	try:
		from .. import gui

		gui.runOnGui(_registerPanel)
	except Exception:
		log.debug("No se pudo registrar el panel de aplicaciones", exc_info=True)


def _registerPanel() -> None:
	from ..gui import apps_panel

	apps_panel.register()


def terminate() -> None:
	with _lock:
		for app in _running.values():
			try:
				app.terminate()
			except Exception:
				pass
		_running.clear()
	try:
		from . import _office

		_office.terminate()
	except Exception:
		pass
