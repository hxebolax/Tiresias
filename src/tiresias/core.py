"""Arranque, hilos y bucle principal de Tiresias.

Hilos:

- Principal: interfaz gráfica (wxPython).
- Núcleo (MTA): eventos de accesibilidad, órdenes y voz (``queue_handler``).
- Ganchos: teclado, ratón y WinEvents.
- Audio y sintetizadores: uno por reproductor/sintetizador.
- Vigilante: detecta bloqueos del núcleo y lo registra.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
import threading
import time

from . import APP_NAME, VERSION, i18n, log as logModule, paths, queue_handler, winapi
from .config import conf
from .log import getLogger

log = getLogger("core")

MUTEX_NAME = "Tiresias_LectorDePantalla_Instancia"
MAIN_WINDOW_TITLE = "Tiresias - ventana principal oculta"

_quitRequested = False
_restartRequested = False
_coreThread: threading.Thread | None = None
_startTime = time.monotonic()
args: argparse.Namespace | None = None
_mutex = None

#: Pasos del arranque que han fallado (se anuncian al terminar de arrancar).
_initFailures: list[str] = []
#: Este arranque es sin complementos porque los anteriores no terminaron (ver :func:`_beginStartupAttempt`).
_autoSafeMode = False
#: Archivo (en ``data\\temp``) con los arranques que empezaron y no llegaron a terminar.
STARTUP_PENDING_FILE = "arranques_pendientes.json"
#: Arranques seguidos sin terminar a partir de los cuales se arranca sin complementos.
STARTUP_FAILURES_FOR_SAFE_MODE = 2
#: Plazo (s) de cada paso del cierre (o de la tarea en curso tras pedir salir) antes de forzar la salida.
SHUTDOWN_STEP_TIMEOUT = 20.0
#: Plazo (s) para que la interfaz termine tras cerrarse el núcleo antes de forzar la salida.
GUI_EXIT_TIMEOUT = 15.0
#: Espera (s) a la ventana de otra copia que tiene el mutex de instancia.
INSTANCE_WINDOW_WAIT = 10.0
_exitLock = threading.Lock()
_exitClaimed = False
_exitDone = threading.Event()


def parseArgs(argv: list[str]) -> argparse.Namespace:
	p = argparse.ArgumentParser(prog="tiresias", description=f"{APP_NAME} {VERSION}: lector de pantalla")
	p.add_argument("--data", help="Carpeta de datos alternativa")
	p.add_argument("--debug", action="store_true", help="Registro detallado y salida por consola")
	p.add_argument("--log-level", default=None, help="Nivel de registro (DEBUG, INFO, WARNING, ERROR)")
	p.add_argument("--no-sounds", action="store_true", help="No reproducir sonidos de inicio y salida")
	# Por defecto, como en otros lectores, la nueva copia sustituye a la que
	# esté en ejecución (--replace lo pide de forma explícita). Con
	# --no-replace no se toca la copia en ejecución y esta termina sin iniciar.
	replace = p.add_mutually_exclusive_group()
	replace.add_argument("-r", "--replace", dest="replace", action="store_true", default=True, help="Sustituir a la copia de Tiresias en ejecución (comportamiento por defecto)")
	replace.add_argument("--no-replace", dest="replace", action="store_false", help="No iniciar si ya hay una copia de Tiresias en ejecución")
	p.add_argument("-k", "--check-running", dest="check_running", action="store_true", help="Solo comprueba si Tiresias está en ejecución: código de salida 0 si lo está y 1 si no")
	p.add_argument("--quit", action="store_true", help="Cerrar la instancia en ejecución y salir")
	p.add_argument("--safe-mode", action="store_true", help="Iniciar sin complementos")
	p.add_argument("--synth", help="Forzar un sintetizador (espeak, sapi5, onecore, silence...)")
	p.add_argument("--no-input", action="store_true", help="No instalar los ganchos de teclado y ratón (pruebas)")
	p.add_argument("--exit-after", type=float, default=0, help="Salir automáticamente tras N segundos (pruebas)")
	p.add_argument("--restart-after", type=float, default=0, help="Reiniciar automáticamente tras N segundos (pruebas del guardián)")
	p.add_argument("--force-active", action="store_true", help="Iniciar activo aunque haya otro lector de pantalla en ejecución (NVDA, JAWS, Narrador...)")
	# Arranque e instalación (área de configuración).
	p.add_argument("--lang", help="Idioma de la interfaz para esta sesión (es, en, auto...)")
	p.add_argument("-m", "--minimal", action="store_true", help="Sin sonidos, sin icono de notificación, sin diálogo de bienvenida ni mensaje de inicio")
	p.add_argument("-s", "--secure", action="store_true", help="Modo seguro: configuración del sistema de solo lectura, sin complementos, consola ni acceso a archivos")
	p.add_argument("--disable-addons", dest="safe_mode_addons", action="store_true", help="Iniciar sin complementos (igual que --safe-mode)")
	p.add_argument("-c", "--config-path", help="Carpeta de configuración alternativa")
	p.add_argument("--debug-logging", action="store_true", help="Registro de depuración en esta sesión (sin consola)")
	p.add_argument("--create-portable", action="store_true", help="Crear una copia portable en --portable-path y salir")
	p.add_argument("--portable-path", help="Carpeta de destino de la copia portable")
	p.add_argument("--portable-no-config", action="store_true", help="No copiar la configuración actual a la copia portable")
	p.add_argument("--portable-no-addons", action="store_true", help="No copiar los complementos instalados a la copia portable")
	p.add_argument("--install", action="store_true", help="Iniciar Tiresias y mostrar el instalador")
	p.add_argument("--install-silent", action="store_true", help="Instalar sin preguntar y salir")
	p.add_argument("--install-dir", help="Carpeta de instalación (por defecto, Archivos de programa)")
	p.add_argument("--launch", action="store_true", help="Con --install-silent: iniciar la copia instalada al terminar")
	p.add_argument("--no-desktop-shortcut", action="store_true", help="Con --install-silent: sin acceso directo en el escritorio")
	p.add_argument("--no-start-menu", action="store_true", help="Con --install-silent: sin accesos directos en el menú Inicio")
	p.add_argument("--start-on-logon", action="store_true", help="Con --install-silent: iniciar Tiresias al iniciar sesión")
	p.add_argument("--all-users", choices=("0", "1"), default=None, help="Con --install-silent: 1 para todos los usuarios, 0 solo para el usuario actual")
	p.add_argument("--no-elevate", action="store_true", help="No pedir permiso de administrador (lo usan las copias ya elevadas)")
	p.add_argument("--uninstall", action="store_true", help="Desinstalar Tiresias (pide confirmación)")
	p.add_argument("--uninstall-silent", action="store_true", help="Desinstalar sin preguntar")
	# Actualización de una copia portable (la lanza updates.startPortableUpdate).
	p.add_argument("--apply-update", metavar="CARPETA", help="Actualizar la copia portable de CARPETA con esta versión, volver a abrirla y salir")
	p.add_argument("--wait-pid", type=int, default=0, help="Con --apply-update: esperar a que termine este proceso")
	p.add_argument("--repair-com", action="store_true", help="Reparar los registros COM de accesibilidad de Windows y salir (requiere administrador)")
	p.add_argument("--copy-config-to-system", help="Copiar la configuración indicada a la configuración del sistema y salir (requiere administrador)")
	p.add_argument("--secure-screens", choices=("0", "1"), default=None, help="1 usa la copia instalada en el inicio de sesión y las pantallas seguras; 0 deja de usarla; y sale (requiere administrador)")
	p.add_argument("--ease-of-access", dest="ease_of_access", action="store_true", help="Lo usa Windows al iniciar Tiresias en el inicio de sesión o en una pantalla segura")
	# Importador de la configuración de NVDA (nvda_import).
	p.add_argument("--import-nvda-config", nargs="?", const="", default=None, metavar="CARPETA", help="Importar la configuración de NVDA (la instalada o la de la carpeta indicada, también NVDA portable) y salir")
	p.add_argument("--import-nvda-profile", metavar="NOMBRE", help="Con --import-nvda-config: importar en un perfil nuevo con este nombre en lugar de en la configuración normal")
	p.add_argument("--undo-nvda-import", action="store_true", help="Deshacer la última importación de la configuración de NVDA y salir")
	ns = p.parse_known_args(argv)[0]
	if ns.safe_mode_addons:
		ns.safe_mode = True
	if ns.minimal:
		ns.no_sounds = True
	if paths.FROZEN and "depuracion" in os.path.basename(sys.executable).lower():
		ns.debug = True
	return ns


# ------------------------------------------------------------------ instancia única
def _findRunningInstance() -> int:
	return winapi.user32.FindWindowW(None, MAIN_WINDOW_TITLE) or 0


winapi.user32.FindWindowW.argtypes = [winapi.wintypes.LPCWSTR, winapi.wintypes.LPCWSTR]
winapi.user32.FindWindowW.restype = winapi.wintypes.HWND


_SYNCHRONIZE = 0x00100000
_PROCESS_TERMINATE = 0x0001
_WAIT_OBJECT_0 = 0
winapi.kernel32.OpenMutexW.argtypes = [winapi.wintypes.DWORD, winapi.wintypes.BOOL, winapi.wintypes.LPCWSTR]
winapi.kernel32.OpenMutexW.restype = winapi.wintypes.HANDLE
winapi.kernel32.WaitForSingleObject.argtypes = [winapi.wintypes.HANDLE, winapi.wintypes.DWORD]
winapi.kernel32.WaitForSingleObject.restype = winapi.wintypes.DWORD
winapi.kernel32.TerminateProcess.argtypes = [winapi.wintypes.HANDLE, winapi.wintypes.UINT]
winapi.kernel32.TerminateProcess.restype = winapi.wintypes.BOOL


#: Escritorio de esta copia si no es el del usuario (``Winlogon``): su mutex es otro.
_instanceDesktop = ""


def instanceMutexName() -> str:
	"""Mutex de instancia: el de siempre en el escritorio del usuario y uno propio
	en el escritorio seguro, para que la copia que Windows inicia allí (SYSTEM)
	no choque con la del usuario (los nombres sin prefijo son de la sesión)."""
	return f"{MUTEX_NAME}_{_instanceDesktop}" if _instanceDesktop else MUTEX_NAME


def _instanceMutexExists() -> bool:
	"""``True`` si otra copia ha creado el mutex de instancia (aunque aún no tenga ventana)."""
	h = winapi.kernel32.OpenMutexW(_SYNCHRONIZE, False, instanceMutexName())
	if h:
		winapi.kernel32.CloseHandle(h)
		return True
	return False


def isRunning() -> bool:
	"""¿Hay otra copia de Tiresias en ejecución en esta sesión?"""
	return bool(_findRunningInstance()) or _instanceMutexExists()


ERROR_ALREADY_EXISTS = 183
_k32le = ctypes.WinDLL("kernel32", use_last_error=True)
_k32le.CreateMutexW.argtypes = [ctypes.c_void_p, winapi.wintypes.BOOL, winapi.wintypes.LPCWSTR]
_k32le.CreateMutexW.restype = winapi.wintypes.HANDLE


def _createInstanceMutex() -> tuple[int, bool]:
	"""Crea (o abre) el mutex de instancia: ``(manejador, ¿ya existía?)``."""
	h = _k32le.CreateMutexW(None, False, instanceMutexName()) or 0
	existed = bool(h) and ctypes.get_last_error() == ERROR_ALREADY_EXISTS
	return h, existed


def _acquireInstanceMutex(replace: bool) -> tuple[int, int | None]:
	"""Toma el mutex de instancia: ``(manejador, código de salida o None para seguir)``.

	Comprobar «¿hay otra copia?» y crear el mutex después dejaba una carrera:
	dos copias iniciadas a la vez (clave Run y el atajo de teclado) pasaban
	las dos la comprobación y quedaban dos lectores. Aquí, si el mutex ya
	existía:

	- puede ser solo una consulta momentánea (el guardián o ``--check-running``
	  lo abren un instante): se reintenta;
	- si hay otra copia con ventana: con ``--replace`` (por defecto) se cierra
	  y se toma el mutex; con ``--no-replace`` esta copia termina;
	- si hay otra copia sin ventana tras :data:`INSTANCE_WINDOW_WAIT` s
	  (bloqueada al arrancar): se sigue, como antes.
	"""
	for _attempt in range(3):
		h, existed = _createInstanceMutex()
		if not existed:
			return h, None
		winapi.kernel32.CloseHandle(h)
		time.sleep(0.3)
		if not _instanceMutexExists():
			continue
		hwnd = _waitForInstanceWindow(INSTANCE_WINDOW_WAIT)
		if not hwnd:
			if not _instanceMutexExists():
				continue
			h, _existed = _createInstanceMutex()
			return h, None
		if not replace:
			return 0, 0
		if not _closeRunningInstance(replacing=True):
			return 0, 1
	h, _existed = _createInstanceMutex()
	return h, None


def _waitForInstanceWindow(timeout: float) -> int:
	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		hwnd = _findRunningInstance()
		if hwnd or not _instanceMutexExists():
			return hwnd
		time.sleep(0.1)
	return _findRunningInstance()


#: Eventos «esta copia sustituye a la anterior» (viven mientras viva esta copia; ver coexist.guardian).
_replacingHandles: list = []


def _closeRunningInstance(timeout: float = 8.0, replacing: bool = False) -> bool:
	"""Cierra la copia en ejecución; si no responde, termina su proceso.

	``replacing``: esta copia sustituye a la anterior, así que el guardián de
	la anterior no debe iniciar el lector recordado (espera a esta). Si no
	(``--quit``, desinstalar), se espera también a que termine su guardián.
	Devuelve ``True`` si al final no queda ninguna copia en ejecución.
	"""
	from .coexist import relaunch

	hwnd = _findRunningInstance()
	if not hwnd and _instanceMutexExists():
		# Otra copia está arrancando: se espera a que cree su ventana.
		hwnd = _waitForInstanceWindow(5.0)
	if not hwnd:
		return True
	pid = winapi.getWindowProcessId(hwnd)
	if pid == os.getpid():
		return True
	if replacing and pid:
		_replacingHandles.append(relaunch.markReplacing(pid))
	hProcess = winapi.kernel32.OpenProcess(_SYNCHRONIZE | _PROCESS_TERMINATE, False, pid) if pid else None
	try:
		winapi.user32.PostMessageW(hwnd, winapi.WM_CLOSE, 0, 0)
		if hProcess:
			if winapi.kernel32.WaitForSingleObject(hProcess, int(timeout * 1000)) == _WAIT_OBJECT_0:
				if not replacing:
					# El guardián decide en unas décimas y termina: así sus archivos quedan libres.
					relaunch.waitGuardianGone(pid, 5.0)
				return True
			# La copia anterior no se cierra (bloqueada): se termina su proceso.
			winapi.kernel32.TerminateProcess(hProcess, 1)
			return winapi.kernel32.WaitForSingleObject(hProcess, 3000) == _WAIT_OBJECT_0
		deadline = time.monotonic() + timeout
		while time.monotonic() < deadline:
			if not _findRunningInstance():
				time.sleep(0.3)
				return True
			time.sleep(0.1)
		return False
	finally:
		if hProcess:
			winapi.kernel32.CloseHandle(hProcess)


# ------------------------------------------------------------------ arranque
def main(argv: list[str] | None = None) -> int:
	global args, _mutex, _instanceDesktop
	args = parseArgs(sys.argv[1:] if argv is None else argv)
	from . import secure_env

	# Cuenta SYSTEM o escritorio seguro (inicio de sesión, UAC): nunca el menú,
	# la consola ni los archivos del sistema sin iniciar sesión (como NVDA).
	# Sin guardián ni API de control; se cierra al volver al escritorio del
	# usuario (ver secure_screens).
	args.secure_desktop = secure_env.mustForceSecureMode()
	if args.secure_desktop:
		args.secure = True
		args.minimal = True
		desktop = secure_env.threadDesktopName()
		if desktop and desktop.lower() != "default":
			_instanceDesktop = desktop
	if args.data:
		paths.setDataDir(args.data)
	if args.config_path:
		paths.setConfigDir(args.config_path)
	if args.secure:
		# Modo seguro: configuración del sistema (carpeta del programa), de solo lectura.
		paths.setConfigDir(paths.SYSTEM_CONFIG_DIR)
		conf.readOnly = True
	standalone = _runStandaloneCommand(args)
	if standalone is not None:
		return standalone
	if args.check_running:
		# Solo informa con el código de salida (no crea carpetas ni registro).
		return 0 if isRunning() else 1
	paths.ensureDataDirs()
	if args.quit:
		return 0 if _closeRunningInstance() else 1
	# Windows (ATBroker) la inicia en el escritorio del usuario con otra copia en
	# marcha: se respeta esa copia. En el escritorio seguro sí sustituye a la
	# anterior (puede estar cerrándose tras un cambio de escritorio rápido).
	replace = bool(args.replace) and not (args.ease_of_access and not args.secure_desktop)
	if isRunning():
		if not replace:
			# --no-replace: se respeta la copia que ya está funcionando.
			return 0
		if not _closeRunningInstance(replacing=True):
			return 1
	_mutex, code = _acquireInstanceMutex(replace)
	if code is not None:
		return code
	if args.debug_logging:
		args.log_level = "DEBUG"
	logModule.initialize("DEBUG" if args.debug else (args.log_level or "INFO"), toConsole=args.debug)
	log.info("Iniciando %s %s (Python %s, %s)", APP_NAME, VERSION, sys.version.split()[0], "compilado" if paths.FROZEN else "desde código")
	log.info("Carpeta de datos: %s", paths.DATA_DIR)
	if logModule.fallbackLogsDir:
		log.error("No se puede escribir en %s: el registro va a %s", paths.logsDir(), logModule.fallbackLogsDir)
	try:
		# Guardián: si Tiresias se cierra o falla, inicia el lector de pantalla recordado.
		from .coexist import guardian

		guardian.start(args)
	except Exception:
		log.exception("No se pudo iniciar el guardián")
	# Solo los cierres de verdad: faulthandler.enable() anotaba como «fatal» cada
	# excepción que COM/RPC lanzan y recogen ellos mismos (ver crash_log.py).
	from . import crash_log

	# En la carpeta del registro en uso (la alternativa si data\logs no admite escritura).
	crash_log.install(os.path.join(logModule.logsDir(), "fallos.log"))
	# Restos de data\temp de sesiones anteriores (OCR, copias de Office, adjuntos).
	paths.cleanTempDir()
	_prepareConfiguration()
	# Si los últimos arranques no terminaron (cierre o bloqueo al arrancar), sin complementos.
	_beginStartupAttempt(args)
	try:
		if not args.log_level and not args.debug:
			logModule.setLevel(conf["general"]["logLevel"])
	except Exception:
		log.exception("Nivel de registro no válido en la configuración")
	try:
		i18n.initialize(args.lang or conf["general"]["language"])
	except Exception:
		log.exception("No se pudo preparar el idioma de la interfaz")
	from . import startup

	# Tras elegir el idioma: sus cadenas se traducen al importarlos.
	startup.registerBuiltins()
	try:
		logModule.applyDebugCategories(conf["advanced"]["debugCategories"])
	except Exception:
		log.exception("Categorías de depuración no válidas en la configuración")
	try:
		ctypes.windll.shcore.SetProcessDpiAwareness(2)
	except Exception:
		pass

	# comtypes inicializa COM (STA) en el hilo que lo importa por primera vez:
	# se importa aquí para que el hilo del núcleo pueda usar MTA.
	try:
		import comtypes  # noqa: F401

		_useComtypesCache()
		import wx

		from . import gui
	except (ImportError, OSError) as e:
		# Smart App Control o WDAC bloquean DLL sin firmar descargadas de Internet.
		from . import app_control

		if not app_control.isBlockedError(e):
			raise
		app_control.report(e, log)
		return 3

	app = wx.App(redirect=False)
	app.SetAppName(APP_NAME)
	# Cierre de sesión y apagado de Windows: sin esto, wx cerraba la ventana
	# principal, que lo veta (y Windows mostraba «Tiresias impide apagar»).
	app.Bind(wx.EVT_QUERY_END_SESSION, _onQueryEndSession)
	app.Bind(wx.EVT_END_SESSION, _onEndSession)
	gui.initialize(app, MAIN_WINDOW_TITLE)
	_startCoreThread()
	app.MainLoop()
	log.info("Bucle de la interfaz terminado")
	if _coreThread is not None:
		_coreThread.join(10)
	if _claimExit():
		_processExitSteps()
	logModule.log.info("%s cerrado", APP_NAME)
	crash_log.uninstall()
	return 0


def _claimExit() -> bool:
	"""Solo un camino (el normal o una salida forzada) hace los pasos finales."""
	global _exitClaimed
	with _exitLock:
		if _exitClaimed:
			return False
		_exitClaimed = True
		return True


def _processExitSteps() -> None:
	"""Marcador para el guardián, mutex de instancia y, si se pidió, la copia nueva."""
	global _mutex
	try:
		try:
			# Marcador de salida para el guardián (y «Volver a <lector>»).
			from .coexist import guardian

			guardian.onProcessExit(_restartRequested, _quitRequested)
		except Exception:
			log.exception("No se pudo preparar la salida para el guardián")
		if _mutex:
			# Se libera antes de reiniciar para que la copia nueva no espere a esta.
			winapi.kernel32.CloseHandle(_mutex)
			_mutex = None
		if _restartRequested:
			_spawnNewInstance()
	finally:
		_exitDone.set()


def _saveConfigurationWithTimeout(timeout: float = 2.0) -> None:
	"""Guarda la configuración si nadie la tiene bloqueada (salidas forzadas y fin de sesión)."""
	if not conf._lock.acquire(timeout=timeout):
		log.warning("No se guarda la configuración: está bloqueada por otro hilo")
		return
	try:
		if conf["general"]["saveConfigurationOnExit"] and not conf.readOnly:
			try:
				from . import synth

				synth.saveCurrentSettings()
			except Exception:
				log.debug("No se pudieron anotar los ajustes de la voz", exc_info=True)
			conf.save()
	except Exception:
		log.exception("No se pudo guardar la configuración")
	finally:
		conf._lock.release()


def _forceExit(reason: str) -> None:
	"""Termina el proceso aunque el núcleo o la interfaz no respondan (cierre bloqueado).

	Antes, un paso del cierre bloqueado dejaba un proceso vivo para siempre,
	sin voz ni teclado, y el guardián no actuaba porque seguía recibiendo
	latidos. Ahora se vuelcan las pilas, se guarda la configuración si se puede,
	se escribe el marcador del guardián (que decide como en una salida normal)
	y se termina el proceso.
	"""
	log.error("Salida forzada de Tiresias: %s", reason)
	try:
		from . import crash_log

		crash_log.dumpThreads(f"Salida forzada: {reason}")
	except Exception:
		pass
	if _claimExit():
		_saveConfigurationWithTimeout()
		_processExitSteps()
	else:
		# El camino normal ya está en los pasos finales: se le deja terminar.
		_exitDone.wait(5.0)
	from . import watchdog

	watchdog.flushAndExit(0)


def _startGuiExitTimer() -> None:
	"""Si la interfaz no termina tras cerrarse el núcleo, se fuerza la salida."""

	def wait() -> None:
		time.sleep(GUI_EXIT_TIMEOUT)
		if _exitDone.is_set():
			return
		_forceExit(f"la interfaz no ha terminado {GUI_EXIT_TIMEOUT:.0f} s después de cerrarse el núcleo")

	threading.Thread(target=wait, name="Plazo de salida", daemon=True).start()


# ------------------------------------------------------------------ fin de sesión de Windows
def _onQueryEndSession(evt) -> None:
	"""WM_QUERYENDSESSION: Tiresias nunca impide cerrar la sesión ni apagar.

	No se llama a ``Skip``: el manejador por defecto de wx cerraría la ventana
	principal, que veta el cierre (y Tiresias se iba antes de tiempo).
	"""
	log.info("Windows pregunta si puede cerrar la sesión: sí")


def _onEndSession(evt) -> None:
	"""WM_ENDSESSION: Windows terminará el proceso en cuanto esto vuelva.

	Como NVDA (``onEndSession``): se guarda la configuración, se calla la voz y
	se deja el marcador de salida del guardián (que no inicia otro lector si
	Windows se está apagando). Todo de forma síncrona y breve.
	"""
	global _quitRequested
	log.info("Windows cierra la sesión")
	_quitRequested = True
	try:
		from . import synth

		s = synth.getSynth()
		if s is not None:
			s.cancel()
	except Exception:
		pass
	_saveConfigurationWithTimeout()
	try:
		from .coexist import guardian, relaunch

		guardian.writeMarkerNow(relaunch.EXIT_USER)
	except Exception:
		log.debug("No se pudo escribir el marcador de salida", exc_info=True)
	try:
		queue_handler.requestQuit()
	except Exception:
		pass
	try:
		logModule.flush(1.0)
	except Exception:
		pass


def _useComtypesCache() -> None:
	"""Versión compilada: los módulos que genere comtypes van a ``data\\cache\\comtypes``.

	Los de UIA, MSAA, SAPI y WScript ya van generados en ``lib\\comtypes\\gen``
	(``tools/pregenerate_comtypes.py``). Si hiciera falta otro, comtypes lo
	escribiría junto al ejecutable o en ``%TEMP%``; así queda dentro de ``data``.
	"""
	if not paths.FROZEN:
		return
	folder = paths.comtypesCacheDir()
	try:
		os.makedirs(folder, exist_ok=True)
		import comtypes.gen

		original = [p for p in comtypes.gen.__path__ if os.path.normcase(p) != os.path.normcase(folder)]
		if "comtypes.client" not in sys.modules:
			# comtypes.client elige al importarse la carpeta de escritura mirando si
			# se puede escribir en la primera (y si no, crea otra en %TEMP%).
			comtypes.gen.__path__ = [folder] + original
		import comtypes.client

		# Los módulos ya generados (lib) tienen preferencia; los nuevos, a data.
		comtypes.gen.__path__ = original + [folder]
		comtypes.client.gen_dir = folder
		log.debug("Caché de comtypes: %s", folder)
	except Exception:
		log.warning("No se pudo preparar la caché de comtypes en %s", folder, exc_info=True)


def _prepareConfiguration() -> None:
	"""Política, configuración (migrada y validada) y datos de la copia instalada."""
	from . import startup

	startup.prepareConfiguration(args)


# ------------------------------------------------------------------ arranques fallidos
def _startupPendingPath() -> str:
	return os.path.join(paths.tempDir(), STARTUP_PENDING_FILE)


def _readStartupFailures() -> int:
	"""Arranques seguidos que empezaron y no terminaron (0 si no hay constancia)."""
	import json

	try:
		with open(_startupPendingPath(), encoding="utf-8") as f:
			data = json.load(f)
		count = data.get("pendientes", 0) if isinstance(data, dict) else 0
		return count if isinstance(count, int) and not isinstance(count, bool) and count > 0 else 0
	except (OSError, ValueError):
		return 0


def _beginStartupAttempt(ns: argparse.Namespace | None) -> bool:
	"""Anota que empieza un arranque; tras varios sin terminar, arranca sin complementos.

	Un complemento que cierra o bloquea Tiresias al cargarse hacía que cada
	arranque fallara igual (y el guardián volvía a abrir el otro lector cada
	vez). Si los :data:`STARTUP_FAILURES_FOR_SAFE_MODE` últimos arranques no
	llegaron a terminar, este se hace sin complementos y se avisa. Al terminar
	bien el arranque (:func:`_startupCompleted`) la cuenta vuelve a cero, así
	que el siguiente reinicio normal vuelve a cargarlos. Devuelve ``True`` si
	se ha activado el arranque sin complementos.
	"""
	import json

	global _autoSafeMode
	failures = _readStartupFailures()
	_autoSafeMode = False
	if ns is not None and failures >= STARTUP_FAILURES_FOR_SAFE_MODE and not getattr(ns, "safe_mode", False):
		ns.safe_mode = True
		_autoSafeMode = True
		log.warning("Los %d últimos arranques no terminaron: se arranca sin complementos", failures)
	path = _startupPendingPath()
	try:
		os.makedirs(os.path.dirname(path), exist_ok=True)
		with open(path, "w", encoding="utf-8") as f:
			json.dump({"pendientes": failures + 1, "pid": os.getpid(), "hora": time.time()}, f)
	except OSError:
		log.debug("No se pudo anotar el arranque", exc_info=True)
	return _autoSafeMode


def _startupCompleted() -> None:
	"""El arranque ha terminado: se borra la cuenta de arranques sin terminar."""
	try:
		os.remove(_startupPendingPath())
	except FileNotFoundError:
		pass
	except OSError:
		log.debug("No se pudo borrar la cuenta de arranques", exc_info=True)


def _runStandaloneCommand(ns: argparse.Namespace) -> int | None:
	"""Órdenes que no inician el lector (copia portable, reparación COM...)."""
	from . import startup

	return startup.runStandaloneCommand(ns)


def _startCoreThread() -> None:
	global _coreThread
	_coreThread = threading.Thread(target=_coreMain, name="Núcleo", daemon=True)
	_coreThread.start()
	threading.Thread(target=_watchdog, name="Vigilante", daemon=True).start()


def _coreMain() -> None:
	import comtypes

	comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
	queue_handler.setCoreThread()
	from . import watchdog

	# Permite al vigilante cancelar llamadas COM que bloqueen el núcleo.
	watchdog.registerCoreThread()
	try:
		try:
			_initializeCore()
		except Exception:
			log.critical("Error grave al iniciar el núcleo", exc_info=True)
			_initFailures.append(i18n._("el núcleo"))
		finally:
			# Pase lo que pase en el arranque, el teclado y los eventos funcionan
			# (antes, un fallo de UIA dejaba Tiresias vivo pero sin ganchos).
			_ensureInputStarted()
			_reportStartupProblems()
		_loop()
	finally:
		try:
			_terminateCore()
		except BaseException:
			log.critical("Error grave al cerrar el núcleo", exc_info=True)
		finally:
			from . import gui

			try:
				gui.exitMainLoop()
			finally:
				_startGuiExitTimer()


def _initStep(name: str, func, *a, critical: bool = False, **kw):
	"""Ejecuta un paso del arranque vigilado y aislado: su fallo no impide los demás.

	``critical``: el fallo se anuncia al usuario al terminar de arrancar
	(:func:`_reportStartupProblems`). Devuelve lo que devuelva ``func`` (o
	``None`` si falla).
	"""
	with queue_handler.watchedPhase(f"arranque: {name}"):
		try:
			return func(*a, **kw)
		except Exception:
			log.exception("Error al iniciar: %s", name)
			if critical:
				_initFailures.append(name)
			return None


def _ensureInputStarted() -> None:
	"""Instala los ganchos si el arranque no llegó a hacerlo (y Tiresias no está en espera)."""
	try:
		from . import coexist

		if coexist.isStandby():
			return
	except Exception:
		pass
	try:
		startInput()
	except Exception:
		log.exception("No se pudieron instalar los ganchos de teclado y ratón")


def _reportStartupProblems() -> None:
	"""Avisa (voz y registro) de lo que no ha ido bien al arrancar."""
	from .i18n import _

	messages: list[str] = []
	if _initFailures:
		messages.append(
			_("Tiresias se ha iniciado con errores en: {parts}. Los detalles están en el registro.").format(parts=", ".join(_initFailures))
		)
	if logModule.fallbackLogsDir:
		messages.append(
			_("No se puede escribir en la carpeta de datos {folder}: la configuración no se guardará. El registro está en {logs}.").format(
				folder=paths.DATA_DIR, logs=logModule.fallbackLogsDir
			)
		)
	unreadable = list(getattr(conf, "unreadableFiles", []) or [])
	if unreadable:
		messages.append(
			_(
				"No se ha podido leer {files} (otro programa lo tenía bloqueado o no hay permiso). Se usa la copia de seguridad "
				"y ese archivo no se guardará hasta reiniciar Tiresias."
			).format(files=", ".join(sorted(set(unreadable))))
		)
	if _autoSafeMode:
		messages.append(
			_("Tiresias se ha iniciado sin complementos porque los últimos arranques no terminaron. Para volver a cargarlos, reinicie Tiresias.")
		)
	if not messages:
		return
	for m in messages:
		log.warning("Aviso de arranque: %s", m)
	try:
		from .audio import tones

		if _initFailures:
			tones.playSound("error")
	except Exception:
		pass
	try:
		from . import speech

		for m in messages:
			speech.speakMessage(m)
	except Exception:
		log.exception("No se pudieron anunciar los problemas del arranque")


def _initializeCore() -> None:
	from . import addons, api, braille, clipboard, events, synth, vision
	from .a11y import uia_client, uia_handler
	from .appmodules import handler as appHandler
	from .audio import ducking, sound_split, tones
	from .audio.wave_player import OutputSettings
	from .input import core as inputCore
	from .input import gestures
	from .objects.uia import getFocusObject
	from .plugins import handler as pluginHandler
	from .speech import dictionaries
	from .speech import symbols

	_ = i18n._
	# Cada paso va aislado y vigilado (_initStep): el fallo de uno (UIA sin
	# registrar, gestures.json dañado...) ya no impide los siguientes, en
	# especial la voz y los ganchos de teclado. Los críticos se anuncian.
	try:
		OutputSettings.deviceName = conf["audio"]["outputDevice"]
	except Exception:
		log.exception("Dispositivo de audio no válido en la configuración")
	# Quitar el silencio del sistema antes del primer sonido (#3049).
	from .audio import manager as audioManager

	_initStep(_("audio"), audioManager.initializeEarly)
	# Convivencia: si otro lector de pantalla está activo, Tiresias arranca en espera.
	from . import coexist

	# Las pruebas automáticas (--exit-after) se hacen con NVDA abierto: arrancan
	# activas salvo con TIRESIAS_COEXIST_TEST=1, que prueba la espera de verdad.
	testRun = bool(args and args.exit_after) and os.environ.get("TIRESIAS_COEXIST_TEST") != "1"
	_initStep(_("convivencia"), coexist.initialize, forceActive=bool(args and getattr(args, "force_active", False)) or testRun)

	def standby() -> bool:
		try:
			return bool(coexist.isStandby())
		except Exception:
			return False

	if conf["general"]["playStartAndExitSounds"] and not (args and args.no_sounds) and not standby():
		_initStep(_("sonido de inicio"), tones.playSound, "start")
	_initStep(_("símbolos"), symbols.processor.load, critical=True)
	_initStep(_("diccionarios de voz"), dictionaries.loadDefault, critical=True)
	if not (args and args.safe_mode):
		_initStep(_("complementos"), addons.loadAll)
	try:
		wanted = (args.synth if args and args.synth else None) or conf["speech"]["synth"]
	except Exception:
		wanted = "auto"
	_initStep(_("sintetizador"), synth.setSynth, wanted, critical=True)
	_initStep(_("diccionario de la voz"), _loadVoiceDict)
	synth.synthChanged.register(lambda synth=None: _loadVoiceDict())
	from . import speech

	if conf["general"]["announceStartup"] and not (args and args.minimal):
		_initStep(_("anuncio de inicio"), speech.speakMessage, _("{app} iniciado").format(app=APP_NAME))
	_initStep(_("UI Automation"), uia_client.initialize, conf["uia"]["connectionTimeout"], critical=True)
	_initStep(_("eventos de UI Automation"), uia_handler.initialize, critical=True)
	# MSAA/IA2, Java Access Bridge, indicador de lector de pantalla y bloqueo.
	from .a11y import system as a11ySystem

	_initStep(_("MSAA y accesibilidad del sistema"), a11ySystem.initialize, critical=True)
	_initStep(_("gestos de entrada"), gestures.userMap.load, critical=True)
	# Antes de los complementos: registra el complemento incorporado de órdenes.
	_initStep(_("acceso remoto"), _initRemote)
	# Panel de opciones de los módulos de aplicación.
	_initStep(_("módulos de aplicación"), appHandler.initialize, critical=True)
	# Órdenes y enganches del núcleo de voz (complemento incorporado).
	_initStep(_("órdenes de voz"), _initSpeechPlugin)
	# Matemáticas: complemento incorporado y panel de opciones.
	_initStep(_("matemáticas"), _initMathpres)
	# Ratón por teclado (complemento incorporado), IA y su panel de opciones.
	_initStep(_("visión e IA"), _initVisionCommands)
	# Productividad: analizador de texto, notificaciones, vigilancias, búsqueda y marcadores.
	_initStep(_("productividad"), _initProductivity)
	# API de control para juegos y programas (compatible con nvdaControllerClient).
	_initStep(_("API de control"), _initController)
	_initStep(_("complementos globales"), pluginHandler.initialize, critical=True)
	_initStep(_("braille"), braille.initialize, critical=True)
	_initStep(_("visión"), vision.handler.initialize, critical=True)
	_initStep(_("lupa"), _initMagnifier, critical=True)
	_initStep(_("atenuación"), ducking.initialize)
	_initStep(_("mezclador de audio"), audioManager.initialize)
	_initStep(_("división de sonido"), sound_split.apply)
	_initStep(_("portapapeles"), clipboard.initialize, critical=True)
	if not standby():
		# En espera no hay ganchos: se instalan al activarse (coexist).
		_initStep(_("teclado y ratón"), startInput, critical=True)
	# Pantalla y panel táctil: con --no-input nunca se capturan toques.
	_initStep(_("táctil"), _initTouch, not (args and args.no_input) and not standby())
	if args and args.exit_after:
		queue_handler.callLater(int(args.exit_after * 1000), requestQuit)
	if args and getattr(args, "restart_after", 0):
		queue_handler.callLater(int(args.restart_after * 1000), restart)
	from .config import post_configProfileSwitch

	post_configProfileSwitch.register(lambda: queue_handler.queueFunction(applyConfiguration, True))

	def initialFocus() -> None:
		obj = getFocusObject() if not standby() else None
		if obj is not None:
			events.executeEvent("gainFocus", obj)
			uia_handler._registerLocalHandlers(obj)

	_initStep(_("foco inicial"), initialFocus)
	_initStep(_("cadena de órdenes"), inputCore.manager.updateChain)
	queue_handler.callLater(15000, _periodicCleanup)
	_initStep(_("inicio automático"), _refreshStartOnLogon)
	from . import gui

	# La bienvenida (y antes, en el primer arranque, la pregunta de importar la
	# configuración de NVDA) la decide startup.afterCoreStarted (first_run).
	if conf["speechViewer"]["showAtStartup"]:
		_initStep(_("visor de voz"), gui.toggleSpeechViewer)
	if conf["brailleViewer"]["showAtStartup"]:
		# No se guarda como línea elegida: es solo el visor de esta sesión.
		_initStep(_("visor braille"), braille.handler.setViewer, True, persist=False)
	log.info("Núcleo iniciado en %.2f s", time.monotonic() - _startTime)
	# El arranque ha llegado al final: ya no cuenta como arranque fallido.
	_startupCompleted()
	# Vigilancia de otros lectores y anuncio de la espera (si procede).
	_initStep(_("vigilancia de otros lectores"), coexist.afterCoreStarted)
	from . import startup

	_initStep(_("tareas posteriores al arranque"), startup.afterCoreStarted, args)
	del api, appHandler


def _initRemote() -> None:
	from . import remote

	remote.initialize()


def _initSpeechPlugin() -> None:
	from .speech import plugin as speechPlugin

	speechPlugin.initialize()


def _initMathpres() -> None:
	from . import mathpres

	mathpres.initialize()


def _initVisionCommands() -> None:
	from . import vision_commands

	vision_commands.initialize()


def _initProductivity() -> None:
	from . import productivity

	productivity.initialize()


def _initController() -> None:
	from . import controller

	if args is not None and getattr(args, "secure_desktop", False):
		# Escritorio seguro (SYSTEM): ni punto de conexión al que lleguen los
		# programas del usuario ni la ventana «NVDA» que haría salir a NVDA.
		log.info("API de control desactivada en el escritorio seguro")
		return
	controller.initialize()


def _initMagnifier() -> None:
	from .magnifier import magnifier

	magnifier.initialize()


def _initTouch(inputAllowed: bool) -> None:
	from .touch import handler as touchHandler

	touchHandler.initialize(inputAllowed=inputAllowed)


def startInput() -> None:
	"""Instala los ganchos de teclado y ratón y los WinEvents (hilo del núcleo).

	Con ``--no-input`` solo los WinEvents. Se llama al arrancar y al activarse
	Tiresias tras estar en espera (:mod:`tiresias.coexist`).
	"""
	from .a11y import winevents
	from .input import core as inputCore
	from .input.hooks import hookThread

	if hookThread.isRunning:
		return
	if args and args.no_input:
		# Solo eventos WinEvent (sin ganchos de teclado ni ratón).
		hookThread.start(winevents.WIN_EVENTS)
	else:
		inputCore.manager.start(winevents.WIN_EVENTS)


def stopInput() -> None:
	"""Quita los ganchos y olvida las teclas pulsadas (Tiresias pasa a espera)."""
	from .input import core as inputCore

	inputCore.manager.stop()
	inputCore.manager.resetState()


def _loadVoiceDict() -> None:
	from . import synth
	from .speech import dictionaries

	s = synth.getSynth()
	if s is not None:
		dictionaries.loadVoiceDict(s.name, s.getSetting("voice"))


def _cycle() -> None:
	from . import baseobject

	baseobject.invalidateCaches()


def _loop() -> None:
	while not _quitRequested:
		if not queue_handler.pump(_cycle):
			break


def _periodicCleanup() -> None:
	from . import tree_interceptor
	from .appmodules import handler as appHandler

	try:
		appHandler.cleanup()
		tree_interceptor.cleanup()
	except Exception:
		log.exception("Error en la limpieza periódica")
	queue_handler.callLater(15000, _periodicCleanup)


def _refreshStartOnLogon() -> None:
	"""Actualiza la clave Run solo si la ruta registrada ya no es la actual.

	Se llama una vez al arrancar: la copia portable puede haberse movido. No se
	reescribe el registro si el valor ya es correcto.
	"""
	if not conf["general"]["startOnLogon"] or (args is not None and args.secure):
		# En modo seguro (y como SYSTEM en el escritorio seguro) no se escribe la clave Run.
		return
	try:
		import winreg

		from .gui import settings as guiSettings

		wanted = guiSettings.launchCommandLine()
		current = None
		try:
			with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
				current = winreg.QueryValueEx(key, APP_NAME)[0]
		except OSError:
			current = None
		if current != wanted:
			guiSettings.setStartOnLogon(True)
			log.info("Ruta de inicio automático actualizada")
	except Exception:
		log.debug("No se pudo actualizar el inicio automático", exc_info=True)


def _terminateAudioManager() -> None:
	from .audio import manager as audioManager

	audioManager.terminate()


def _terminateCore() -> None:
	from . import addons, braille, clipboard, power, synth, tree_interceptor, vision
	from .a11y import uia_handler
	from .appmodules import handler as appHandler
	from .audio import ducking, sound_split, tones
	from .input import core as inputCore
	from .plugins import handler as pluginHandler

	log.info("Cerrando el núcleo")
	from . import coexist

	# En espera no se hace ruido al salir: el otro lector tiene preferencia.
	try:
		quietExit = coexist.isStandby()
	except Exception:
		quietExit = False
	# Cada paso va vigilado (queue_handler.watchedPhase): si uno se bloquea, el
	# vigilante fuerza la salida (core._watchdog) en lugar de dejar el proceso
	# vivo para siempre. La entrada se para la primera: con el núcleo ya fuera
	# de la cola, el gancho se tragaría órdenes que nadie ejecutaría.
	steps = [
		("entrada", inputCore.manager.stop),
		("convivencia con otros lectores", coexist.terminate),
		("comprobación automática de actualizaciones", _terminateUpdates),
		("pantalla encendida durante la lectura continua", power.terminate),
		("acceso remoto", _terminateRemote),
		("API de control", _terminateController),
		("productividad", _terminateProductivity),
		("táctil", _terminateTouch),
		("portapapeles", clipboard.terminate),
		("interceptores", tree_interceptor.terminateAll),
		("complementos globales", pluginHandler.terminate),
		("módulos de aplicación", appHandler.terminate),
		("eventos UIA", uia_handler.terminate),
		("sistema y API de accesibilidad", _terminateA11ySystem),
		("OCR e IA", _terminateVisionTools),
		("lupa", _terminateMagnifier),
		("visión", vision.handler.terminate),
		("braille", braille.terminate),
		("atenuación", ducking.terminate),
		("mezclador de audio", _terminateAudioManager),
		("división de sonido", sound_split.terminate),
	]
	for name, func in steps:
		_terminateStep(name, func)

	def saveConfig() -> None:
		synth.saveCurrentSettings()
		if conf["general"]["saveConfigurationOnExit"]:
			conf.save()

	_terminateStep("configuración", saveConfig)
	try:
		playExit = conf["general"]["playStartAndExitSounds"] and not (args and args.no_sounds) and not quietExit
	except Exception:
		playExit = False
	if playExit:

		def exitSound() -> None:
			tones.playSound("exit")
			time.sleep(0.45)

		_terminateStep("sonido de salida", exitSound)
	_terminateStep("sintetizador", synth.terminate)
	_terminateStep("sonidos", tones.terminate)
	del addons


def _terminateStep(name: str, func) -> None:
	"""Un paso del cierre, vigilado y aislado (también de ``SystemExit`` de un complemento)."""
	with queue_handler.watchedPhase(f"cierre: {name}"):
		try:
			func()
		except BaseException:
			log.exception("Error cerrando %s", name)


def _terminateVisionTools() -> None:
	from . import vision_commands

	vision_commands.terminate()


def _terminateA11ySystem() -> None:
	from . import console_reader
	from .a11y import system as a11ySystem

	a11ySystem.terminate()
	console_reader.terminate()


def _terminateMagnifier() -> None:
	from .magnifier import magnifier

	magnifier.terminate()


def _terminateController() -> None:
	from . import controller

	controller.terminate()


def _terminateUpdates() -> None:
	from . import updates

	updates.stop()


def _terminateProductivity() -> None:
	from . import productivity

	productivity.terminate()


def _terminateRemote() -> None:
	from . import remote

	remote.terminate()


def _terminateTouch() -> None:
	from .touch import handler as touchHandler

	touchHandler.terminate()


def _watchdog() -> None:
	from . import watchdog

	reported = False
	while _coreThread is not None and _coreThread.is_alive():
		time.sleep(1.0)
		try:
			timeout = conf["advanced"]["watchdogTimeout"]
		except Exception:
			timeout = 6
		# Desde el inicio de la tarea o del paso de arranque/cierre en curso.
		frozenFor = queue_handler.frozenFor()
		frozen = frozenFor > timeout
		task = queue_handler.currentTask
		if frozenFor < 2.0:
			# Latido para el guardián (detecta si Tiresias deja de responder).
			try:
				from .coexist import guardian

				guardian.beat()
			except Exception:
				pass
		if _quitRequested and frozenFor >= SHUTDOWN_STEP_TIMEOUT:
			# Se pidió salir y el núcleo no avanza (una tarea o un paso del cierre
			# bloqueado): se termina el proceso en vez de dejarlo vivo y mudo.
			_forceExit(f"el núcleo lleva {frozenFor:.0f} s bloqueado al cerrar ({task or '?'})")
			return
		if frozen:
			# Recuperación: cancelar llamadas COM y, si no basta, reinicio controlado
			# (nunca durante el cierre: ahí se fuerza la salida, arriba).
			try:
				watchdog.recover(frozenFor, allowRestart=not _quitRequested)
			except Exception:
				log.exception("Error en la recuperación del núcleo")
		elif frozenFor >= 1.0 and not _quitRequested:
			# Vía rápida (como NVDA): si el usuario ya ha dejado la ventana del foco,
			# la llamada bloqueada se cancela sin esperar al tiempo normal. recover
			# no reinicia antes de watchdogRestartTimeout.
			try:
				from .a11y import winevents

				if winevents.shouldRecoverEarly():
					watchdog.recover(frozenFor, allowRestart=False)
			except Exception:
				log.debug("Error en la recuperación rápida del núcleo", exc_info=True)
		if frozen and not reported:
			reported = True
			log.warning("El núcleo no responde desde hace %d s (%s); volcado de hilos en fallos.log", timeout, task or "?")
			from . import crash_log

			crash_log.dumpThreads("El núcleo no responde desde hace %d s (%s)" % (timeout, task or "?"))
			try:
				from . import synth

				s = synth.getSynth()
				if s is not None:
					s.cancel()
			except Exception:
				pass
		elif not frozen:
			if reported:
				watchdog.onRecovered()
			reported = False


# ------------------------------------------------------------------ acciones
def requestQuit() -> None:
	"""Cierra Tiresias (seguro llamarlo desde cualquier hilo)."""
	global _quitRequested
	_quitRequested = True
	queue_handler.requestQuit()


#: Argumentos extra para la copia que se inicia al reiniciar (p. ej. registro de depuración).
_restartExtraArgs: list[str] = []


def restart(safeMode: bool = False, debugLogging: bool = False) -> None:
	"""Reinicia Tiresias. ``safeMode``: la copia nueva arranca sin complementos.

	``debugLogging``: la copia nueva registra con nivel de depuración.
	Un reinicio normal tras un arranque sin complementos vuelve a cargarlos.
	"""
	global _restartRequested, _restartExtraArgs
	_restartRequested = True
	if args is not None:
		args.safe_mode = bool(safeMode)
	_restartExtraArgs = ["--debug-logging"] if debugLogging else []
	requestQuit()


def _launchCommand() -> list[str]:
	if paths.FROZEN:
		return [sys.executable]
	script = os.path.join(paths.SOURCE_DIR, "tiresias.pyw")
	exe = sys.executable
	pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
	return [pyw if os.path.isfile(pyw) else exe, script]


def isElevated() -> bool:
	try:
		return bool(ctypes.windll.shell32.IsUserAnAdmin())
	except Exception:
		return False


def restartAsAdmin() -> None:
	"""Inicia una copia elevada (pide permiso con UAC); esa copia cierra esta."""
	from . import speech
	from .i18n import _

	if isElevated():
		speech.speakMessage(_("Tiresias ya se está ejecutando como administrador"))
		return
	cmd = _launchCommand()
	# Con las mismas opciones que un reinicio normal (modo seguro, sin
	# complementos, configuración alternativa...): antes se perdían.
	params = subprocess.list2cmdline(cmd[1:] + ["--data", paths.DATA_DIR] + restartArguments())

	def run() -> None:
		# ShellExecute con «runas» no vuelve hasta que se responde al control de
		# cuentas (UAC). En el núcleo eso lo bloqueaba: el vigilante cancelaba,
		# el guardián abría el otro lector a los 20 s y a los 30 s se reiniciaba
		# Tiresias sin elevar con el UAC aún abierto. Por eso va en su propio hilo.
		try:
			res = _shellExecuteRunas(cmd[0], params)
		except Exception:
			log.exception("No se pudo reiniciar como administrador")
			res = 0
		if res <= 32:
			queue_handler.queueFunction(speech.speakMessage, _("No se pudo reiniciar como administrador"))

	threading.Thread(target=run, name="Reiniciar como administrador", daemon=True).start()


def _shellExecuteRunas(exe: str, params: str) -> int:
	"""``ShellExecuteW(None, "runas", exe, params)``: el resultado (> 32 si se inició)."""
	shell32 = ctypes.WinDLL("shell32")
	shell32.ShellExecuteW.argtypes = [
		winapi.wintypes.HWND,
		winapi.wintypes.LPCWSTR,
		winapi.wintypes.LPCWSTR,
		winapi.wintypes.LPCWSTR,
		winapi.wintypes.LPCWSTR,
		ctypes.c_int,
	]
	shell32.ShellExecuteW.restype = ctypes.c_ssize_t
	# ShellExecute necesita COM inicializado en el hilo que lo llama.
	ole32 = ctypes.windll.ole32
	initialized = ole32.CoInitializeEx(None, 0x2 | 0x4) >= 0  # APARTMENTTHREADED | DISABLE_OLE1DDE
	try:
		return int(shell32.ShellExecuteW(None, "runas", exe, params, None, 1))
	finally:
		if initialized:
			ole32.CoUninitialize()


def _spawnNewInstance() -> None:
	cmd = _launchCommand() + ["--data", paths.DATA_DIR] + restartArguments() + list(_restartExtraArgs)
	try:
		subprocess.Popen(cmd, close_fds=True)
	except OSError:
		log.exception("No se pudo reiniciar")


def restartArguments() -> list[str]:
	"""Opciones de la línea de órdenes que debe conservar una copia reiniciada."""
	out: list[str] = []
	if args is None:
		return out
	if args.safe_mode:
		out.append("--safe-mode")
	if args.secure:
		out.append("--secure")
	if args.config_path:
		out += ["--config-path", args.config_path]
	if args.lang:
		out += ["--lang", args.lang]
	if args.minimal:
		out.append("--minimal")
	# Una sesión sin ganchos (pruebas) o con la voz forzada sigue así tras reiniciar.
	if args.no_input:
		out.append("--no-input")
	if args.synth:
		out += ["--synth", args.synth]
	try:
		from . import coexist

		if coexist.isForced() and coexist.runningReaders():
			# Activado a propósito junto a otro lector: sigue así tras reiniciar.
			out.append("--force-active")
	except Exception:
		pass
	return out


def applyConfiguration(fromProfileSwitch: bool = False) -> None:
	"""Aplica la configuración actual (tras cambiar de perfil o restaurar)."""
	from . import braille, synth
	from .audio import ducking, sound_split
	from .audio.wave_player import OutputSettings

	OutputSettings.deviceName = conf["audio"]["outputDevice"]
	logModule.applyDebugCategories(conf["advanced"]["debugCategories"])
	try:
		# Nivel del registro: tras restablecer o volver a lo guardado (es global, no de
		# perfil). ``--log-level`` y ``--debug`` mandan sobre la configuración.
		wantedLevel = logModule.LEVELS.get(str(conf["general"]["logLevel"]).upper())
		overridden = args is not None and (getattr(args, "log_level", None) or getattr(args, "debug", False))
		if wantedLevel is not None and not overridden and logModule.log.level != wantedLevel:
			logModule.setLevel(conf["general"]["logLevel"])
	except Exception:
		log.exception("No se pudo aplicar el nivel del registro")

	def _autoSynthName() -> str | None:
		"""El que elegiría ``setSynth("auto")``: el primero disponible por prioridad."""
		available = {name for name, _desc in synth.getSynthList()}
		for candidate in list(conf["speech"]["synthPriority"]) + synth.getDriverNames():
			if candidate != "silence" and candidate in available:
				return candidate
		return None

	wanted = conf["speech"]["synth"]
	current = synth.getSynth()
	# Sintetizador que pidió la configuración aplicada la vez anterior (p. ej. un perfil).
	previous = getattr(applyConfiguration, "lastWantedSynth", None)
	applyConfiguration.lastWantedSynth = wanted
	if current is None or (wanted not in ("auto", "") and wanted != current.name):
		synth.setSynth(wanted)
	elif wanted in ("auto", "") and previous not in (None, "auto", "") and previous == current.name and _autoSynthName() != current.name:
		# Se sale de un perfil que había elegido otro sintetizador: vuelve la elección automática.
		synth.setSynth("auto")
	else:
		section = conf["speech"]["synths"].get(current.name)
		if section is not None:
			current.loadSettings(section.dict() if hasattr(section, "dict") else dict(section))
	sessionViewer = braille.handler.display.name == "viewer" and conf["braille"]["display"] in ("noBraille", "")
	# ``configName``: una línea detectada en modo «Automático» se llama «auto».
	if getattr(braille.handler.display, "configName", braille.handler.display.name) != conf["braille"]["display"] and not sessionViewer:
		braille.handler.setDisplay(conf["braille"]["display"])
	# Tabla, modo, ajuste... pueden cambiar con el perfil: se vuelve a traducir.
	braille.handler.applyConfig()
	try:
		sound_split.apply()
		ducking.apply()
	except Exception:
		log.exception("Error aplicando audio")
	try:
		_applyVisionConfiguration()
	except Exception:
		log.exception("Error aplicando la visión")
	try:
		from . import startup

		startup.applyConfiguration()
	except Exception:
		log.exception("Error aplicando la configuración de interfaz y entrada")
	if not fromProfileSwitch:
		# API de control: sus opciones son globales (no cambian con el perfil), pero
		# sí al restablecer o volver a lo guardado. La convivencia ya escucha esos avisos.
		try:
			from . import controller

			controller.applyConfiguration()
		except Exception:
			log.exception("Error aplicando las opciones de la API de control")
	if fromProfileSwitch:
		from .audio import tones

		tones.playSound("profileSwitch")


def _applyVisionConfiguration() -> None:
	"""Cortina, lupa y resaltado según la configuración activa (perfil o restaurada)."""
	from . import vision
	from .magnifier import magnifier

	wantCurtain = bool(conf["vision"]["screenCurtain"])
	if wantCurtain != vision.handler.curtainActive:
		vision.handler.setScreenCurtain(wantCurtain, announce=False)
	# Vista, nivel, filtros y seguimiento pueden haber cambiado con el perfil.
	magnifier.applyConfiguration()
	vision.handler.forceRedraw()


def reloadPlugins() -> None:
	from . import addons, events, api
	from .appmodules import handler as appHandler
	from .input import core as inputCore
	from .plugins import handler as pluginHandler
	from . import extension_points

	# Los complementos globales y módulos de aplicación que terminan ahora: sus
	# métodos registrados en puntos de extensión se dan de baja aunque el
	# complemento no lo haga en su terminate() (si no, el viejo y el nuevo
	# reaccionarían los dos a cada aviso).
	try:
		owners = list(pluginHandler.runningPlugins) + list(getattr(appHandler, "_running", {}).values())
	except Exception:
		owners = []
	pluginHandler.terminate()
	appHandler.reloadAll()
	try:
		removed = extension_points.unregisterOwnedBy(owners)
		if removed:
			log.info("Recarga de complementos: %d manejadores de puntos de extensión dados de baja", removed)
	except Exception:
		log.exception("No se pudieron dar de baja los manejadores de los complementos")
	del owners
	if not (args and args.safe_mode):
		# Sin complementos (--safe-mode, --disable-addons, modo seguro): recargar
		# no debe cargarlos.
		addons.loadAll()
	pluginHandler.initialize()
	focus = api.getFocusObject()
	if focus is not None:
		from .objects.uia import getFocusObject

		obj = getFocusObject()
		if obj is not None:
			api.setFocusObject(None)
			events.executeEvent("gainFocus", obj)
	inputCore.manager.updateChain()


def uptime() -> float:
	return time.monotonic() - _startTime
