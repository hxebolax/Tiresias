"""Tareas de arranque del área de configuración, interfaz e instalación.

``core`` llama a estas funciones en momentos concretos:

- :func:`runStandaloneCommand`: antes de nada, para las órdenes que no
  inician el lector (``--create-portable``, ``--repair-com``,
  ``--install-silent``, ``--uninstall``...). Devuelve el código de salida o
  ``None`` si hay que arrancar normalmente.
- :func:`prepareConfiguration`: en el hilo principal, antes de crear la
  interfaz. Carga la política corporativa, prepara los datos de una copia
  instalada, carga la configuración (migrada y validada) y registra los
  complementos globales incorporados (perfiles por dominio, IME, capas).
- :func:`afterCoreStarted`: en el hilo del núcleo, al terminar el arranque.
  Avisos (configuración recuperada, novedades), comprobación de
  actualizaciones e instalador.
- :func:`applyConfiguration`: tras cambiar de perfil o guardar opciones.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import APP_NAME, VERSION, paths
from .config import conf
from .config.policy import Policy
from .i18n import _
from .log import getLogger

log = getLogger("startup")


# ====================================================================== órdenes sin lector
#: Archivo de registro de las órdenes sin lector (se ejecutan antes de iniciar
#: el registro normal y, en el ejecutable sin consola, stderr no existe).
COMMAND_LOG = "ordenes.log"


def runStandaloneCommand(args: argparse.Namespace) -> int | None:
	path = commandLogPath(args)
	if path is None:
		return _runCommand(args)
	handler = _startCommandLog(path)
	try:
		log.info("Orden de %s %s: %s", APP_NAME, VERSION, " ".join(sys.argv[1:]))
		code = _runCommand(args)
		log.info("Orden terminada con el código %s", code)
		return code
	except BaseException:
		log.exception("Error en la orden")
		raise
	finally:
		_stopCommandLog(handler)


def commandLogPath(args: argparse.Namespace) -> str | None:
	"""Dónde registrar la orden (``None`` si no es de las que se registran aparte)."""
	import tempfile

	if getattr(args, "apply_update", None):
		# En la copia que se actualiza (la nueva está en una carpeta temporal).
		return os.path.join(os.path.abspath(args.apply_update), "data", "logs", COMMAND_LOG)
	if args.uninstall or args.uninstall_silent:
		# Fuera de la carpeta de datos, que la desinstalación puede borrar.
		return os.path.join(tempfile.gettempdir(), "Tiresias-" + COMMAND_LOG)
	if args.install_silent:
		# En la de la copia instalada: la del instalador temporal se borra después.
		return os.path.join(paths.logsDir() if args.data else os.path.join(paths.userDataDir(), "logs"), COMMAND_LOG)
	if args.repair_com or args.copy_config_to_system or getattr(args, "secure_screens", None) is not None:
		return os.path.join(paths.logsDir(), COMMAND_LOG)
	return None


def _startCommandLog(path: str):
	import logging
	import tempfile

	from .log import log as rootLog

	handler = None
	for candidate in (path, os.path.join(tempfile.gettempdir(), "Tiresias-" + COMMAND_LOG)):
		try:
			os.makedirs(os.path.dirname(candidate), exist_ok=True)
			# Se empieza de nuevo si ha crecido demasiado.
			big = os.path.isfile(candidate) and os.path.getsize(candidate) > 1024 * 1024
			handler = logging.FileHandler(candidate, mode="w" if big else "a", encoding="utf-8")
			break
		except OSError:
			continue
	if handler is None:
		return None
	handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [pid %(process)d] %(name)s: %(message)s"))
	handler._previousLevel = rootLog.level
	if rootLog.level == logging.NOTSET or rootLog.level > logging.INFO:
		rootLog.setLevel(logging.INFO)
	rootLog.addHandler(handler)
	return handler


def _stopCommandLog(handler) -> None:
	if handler is None:
		return
	from .log import log as rootLog

	rootLog.removeHandler(handler)
	rootLog.setLevel(getattr(handler, "_previousLevel", 0))
	try:
		handler.close()
	except Exception:
		pass


def _runCommand(args: argparse.Namespace) -> int | None:
	if args.create_portable:
		return _createPortableFromCommandLine(args)
	if args.repair_com:
		from . import comrepair

		return comrepair.runFromCommandLine(noElevate=bool(getattr(args, "no_elevate", False)))
	if getattr(args, "secure_screens", None) is not None:
		# Copia elevada: registro en HKLM y, al activar, la configuración del sistema.
		from . import secure_screens

		return secure_screens.runCommand(args.secure_screens == "1", args.copy_config_to_system or None)
	if args.copy_config_to_system:
		from . import installer

		try:
			installer.copyConfigToSystem(args.copy_config_to_system)
			return 0
		except OSError:
			log.exception("No se pudo copiar la configuración al sistema")
			_logToConsole("No se pudo copiar la configuración al sistema")
			return 1
	if args.install_silent:
		from . import installer

		return installer.runSilentInstall(args)
	if getattr(args, "apply_update", None):
		from . import installer

		return installer.runApplyUpdate(args)
	if args.uninstall_silent or args.uninstall:
		from . import installer

		return installer.runUninstall(interactive=bool(args.uninstall and not args.uninstall_silent), noElevate=bool(getattr(args, "no_elevate", False)))
	if getattr(args, "import_nvda_config", None) is not None:
		from . import nvda_import

		return nvda_import.runFromCommandLine(args.import_nvda_config or None, args.import_nvda_profile, args)
	if getattr(args, "undo_nvda_import", False):
		from . import nvda_import

		return nvda_import.undoFromCommandLine()
	return None


def _logToConsole(message: str) -> None:
	try:
		print(message, file=sys.stderr)
	except Exception:
		pass


def _createPortableFromCommandLine(args: argparse.Namespace) -> int:
	from . import installer

	if not args.portable_path:
		_logToConsole("Falta --portable-path con la carpeta de destino")
		return 2
	try:
		installer.createPortableCopy(
			args.portable_path,
			copyConfig=not args.portable_no_config,
			copyAddons=not args.portable_no_addons,
		)
	except (OSError, ValueError) as e:
		_logToConsole(f"No se pudo crear la copia portable: {e}")
		return 1
	return 0


# ====================================================================== configuración
#: ``True`` si al arrancar no existía la configuración de Tiresias (``config.json``).
configWasMissing = False


def prepareConfiguration(args: argparse.Namespace | None) -> None:
	pol = Policy.load()
	pol.secureMode = bool(args and args.secure)
	conf.setPolicy(pol)
	if pol.secureMode:
		# Sin abrir archivos ni cuadros de archivos (lanzarían programas con la
		# cuenta del escritorio seguro, SYSTEM): ver secure_env.
		from . import secure_env

		secure_env.installSecureModeGuards()
	if args is not None and getattr(args, "secure_desktop", False):
		# Copia del escritorio seguro: se cierra sola al volver al escritorio del usuario.
		from . import secure_screens

		secure_screens.startDesktopWatcher()
	if paths.isInstalledCopy() and not (args and args.data):
		try:
			from . import installer

			installer.seedUserData()
		except Exception:
			log.exception("No se pudieron preparar los datos del usuario")
	global configWasMissing
	# Primer arranque: sin configuración propia se ofrece importar la de NVDA
	# y después sale la bienvenida (tiresias.first_run).
	configWasMissing = not os.path.isfile(conf.configFile)
	conf.load()
	if configWasMissing and not conf.readOnly:
		from . import first_run

		first_run.markFirstRun()
	if args is not None and args.secure:
		# Sin complementos en modo seguro.
		args.safe_mode = True


def registerBuiltins() -> None:
	"""Complementos globales incorporados (deben registrarse antes de iniciar el núcleo)."""
	from .plugins import handler as pluginHandler

	# appmodules._gsuite: Google Docs y Hojas de cálculo en el navegador (foros 3.5).
	for modName in ("domain_profiles", "ime", "config_plugin", "appmodules._gsuite"):
		try:
			mod = __import__(f"tiresias.{modName}", fromlist=["GlobalPlugin"])
			pluginHandler.registerBuiltin(mod.GlobalPlugin)
		except Exception:
			log.exception("No se pudo registrar el complemento incorporado %s", modName)


def applyConfiguration() -> None:
	"""Reaplica lo que depende de la configuración activa (hilo del núcleo)."""
	from .a11y import uia_handler

	uia_handler.applyConfig()
	try:
		from . import gesture_layouts

		gesture_layouts.apply()
	except Exception:
		log.exception("No se pudo aplicar el mapa de gestos")


# ====================================================================== tras el arranque
def afterCoreStarted(args: argparse.Namespace | None) -> None:
	from . import gesture_layouts, power

	power.initialize()
	gesture_layouts.apply()
	_reportConfigurationProblems()
	_checkNews(args)
	_startupDialogs(args)
	if not (args and (args.secure or args.minimal)):
		try:
			from . import updates

			updates.scheduleAutomaticChecks()
		except Exception:
			log.exception("No se pudo programar la comprobación de actualizaciones")
		try:
			from . import addon_store

			addon_store.scheduleAutomaticCheck()
		except Exception:
			log.exception("No se pudo programar la comprobación de complementos")
	if paths.isInstalledCopy():
		_cleanInstallerTemp()
	if args is not None and args.install:
		from . import gui

		gui.runOnGui(_showInstaller)


def _startupDialogs(args: argparse.Namespace | None) -> None:
	"""Pregunta de importar la configuración de NVDA (primer arranque) y bienvenida.

	Una detrás de otra y, en espera, cuando Tiresias se active (:mod:`.first_run`).
	"""
	try:
		from . import first_run

		first_run.start(args)
	except Exception:
		log.exception("No se pudieron preparar los diálogos de arranque")


def _cleanInstallerTemp() -> None:
	"""Borra la carpeta temporal del instalador que quedó tras instalar (hilo propio)."""
	import shutil
	import tempfile
	import threading

	folder = os.path.join(tempfile.gettempdir(), "TiresiasInstalador")
	if not os.path.isdir(folder) or os.path.normcase(paths.APP_DIR).startswith(os.path.normcase(folder)):
		return

	def clean() -> None:
		# La copia temporal se cierra al arrancar esta: se reintenta unos segundos.
		import time

		for _i in range(10):
			shutil.rmtree(folder, ignore_errors=True)
			if not os.path.isdir(folder):
				return
			time.sleep(2)

	threading.Thread(target=clean, name="Limpieza del instalador", daemon=True).start()


def _showInstaller() -> None:
	from .gui import installer_dialogs

	installer_dialogs.showInstallDialog()


def _reportConfigurationProblems() -> None:
	from . import gui, speech

	if conf.recoveredFiles:
		files = ", ".join(sorted(set(conf.recoveredFiles)))
		msg = _(
			"Algunos archivos de configuración estaban dañados ({files}). Se ha recuperado la última copia de seguridad "
			"o, si no la había, los valores por defecto. Los archivos dañados se han guardado con la extensión .corrupto."
		).format(files=files)
		speech.speakMessage(_("Configuración recuperada"))
		gui.messageBox(msg, _("Configuración recuperada"))
	elif conf.loadIssues:
		log.warning("Se corrigieron %d valores no válidos de la configuración", len(conf.loadIssues))


def _checkNews(args: argparse.Namespace | None) -> None:
	"""Tras una actualización, avisa (sin molestar) de que hay novedades (#14274)."""
	last = conf["general"]["lastRunVersion"]
	if last == VERSION:
		return
	if not conf.readOnly:
		conf["general"]["lastRunVersion"] = VERSION
	if not last or (args and args.minimal) or not conf["general"]["showNewsAfterUpdate"]:
		return
	from . import speech

	speech.speakMessage(
		_("{app} se ha actualizado a la versión {version}. Las novedades están en el menú Ayuda.").format(app=APP_NAME, version=VERSION)
	)


def newsPath() -> str:
	"""Documento de novedades (``data/docs/novedades.html`` o ``docs/novedades.html``)."""
	path = paths.docPath("novedades.html")
	if os.path.isfile(path):
		return path
	return os.path.join(paths.APP_DIR, "novedades.html")
