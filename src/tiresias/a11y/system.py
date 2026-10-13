"""Integración con el sistema: lector de pantalla activo, registro como
tecnología de asistencia y protección de la pantalla de bloqueo.

- **Indicador de lector de pantalla** (``SPI_SETSCREENREADER``): al arrancar se
  activa para que Windows y las aplicaciones sepan que hay un lector de
  pantalla (muchas muestran entonces más información accesible). Al cerrar se
  restaura el valor que había; si otro lector ya lo había activado, se deja.
- **Tecnología de asistencia de Windows**: opcionalmente se registra Tiresias
  en ``Software\\Microsoft\\Windows NT\\CurrentVersion\\Accessibility\\ATs``
  (HKCU siempre; HKLM también si Tiresias se ejecuta como administrador). Al
  desactivar la opción se borra el registro.
- **Pantalla de bloqueo**: mientras la sesión está bloqueada, solo se puede
  acceder a los objetos de la pantalla de bloqueo (LockApp) y del inicio de
  sesión. La navegación de objetos, el ratón y los eventos de otras ventanas se
  filtran con :func:`isSecureObject`, para que nadie pueda leer el contenido
  del escritorio sin desbloquear el equipo.
- **Escritorio seguro** (UAC, Ctrl+Alt+Supr, inicio de sesión): Windows solo
  deja que lo lean procesos del sistema. La copia del usuario avisa al entrar
  y vuelve a leer el foco al salir. Si la copia instalada tiene activada la
  opción de las pantallas seguras, Windows inicia allí otra copia como SYSTEM
  (ver :mod:`tiresias.secure_screens`); esta copia le avisa de que está en
  marcha mientras está activa (no en espera).
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
import winreg
from ctypes import wintypes

from .. import APP_NAME
from ..config import conf
from ..log import getLogger

log = getLogger("sistema")

user32 = ctypes.windll.user32
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
user32.SystemParametersInfoW.restype = wintypes.BOOL
user32.SendNotifyMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendNotifyMessageW.restype = wintypes.BOOL

SPI_GETSCREENREADER = 0x0046
SPI_SETSCREENREADER = 0x0047
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02
WM_SETTINGCHANGE = 0x001A
HWND_BROADCAST = 0xFFFF

AT_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\Accessibility\ATs"
AT_NAME = "tiresias"

#: Procesos que pueden leerse con la sesión bloqueada.
LOCK_SCREEN_PROCESSES = {"lockapp", "logonui", "credentialuibroker", "consent"}

_previousScreenReaderFlag: bool | None = None
_lockCache: tuple[float, bool] = (0.0, False)
_initialized = False


# ------------------------------------------------------------------ lector de pantalla
def getScreenReaderFlag() -> bool:
	val = wintypes.BOOL()
	if user32.SystemParametersInfoW(SPI_GETSCREENREADER, 0, ctypes.byref(val), 0):
		return bool(val.value)
	return False


def setScreenReaderFlag(on: bool) -> bool:
	# Sin SPIF_SENDCHANGE: ese aviso es un SendMessage a todas las ventanas
	# del escritorio y espera a que cada aplicación lo procese; al cambiar el
	# indicador algunas reinician su accesibilidad y el arranque y el cierre
	# de Tiresias llegaban a tardar 20 s. El aviso se manda sin esperar
	# (WM_SETTINGCHANGE no se puede publicar con PostMessage: error 1159).
	ok = bool(user32.SystemParametersInfoW(SPI_SETSCREENREADER, 1 if on else 0, None, SPIF_UPDATEINIFILE))
	if ok:
		user32.SendNotifyMessageW(HWND_BROADCAST, WM_SETTINGCHANGE, SPI_SETSCREENREADER, 0)
	return ok


def applyScreenReaderFlag() -> None:
	"""Activa o restaura el indicador según la opción ``system.setScreenReaderFlag``."""
	global _previousScreenReaderFlag
	# Activa (o tras la espera): Windows puede iniciar Tiresias en las pantallas seguras.
	_syncSecureScreens()
	if _onSecureScreen():
		# Copia del escritorio seguro (SYSTEM): el indicador no se toca (como NVDA).
		return
	want = conf["system"]["setScreenReaderFlag"]
	if want and _inStandby():
		# En espera otro lector tiene preferencia: el indicador es cosa suya.
		return
	if want:
		if _previousScreenReaderFlag is None:
			_previousScreenReaderFlag = getScreenReaderFlag()
		if not getScreenReaderFlag():
			setScreenReaderFlag(True)
			log.info("Indicador de lector de pantalla activado")
	elif _previousScreenReaderFlag is not None:
		_restoreScreenReaderFlag()


def _inStandby() -> bool:
	try:
		from .. import coexist

		return coexist.isStandby()
	except Exception:
		return False


def _onSecureScreen() -> bool:
	"""¿Es la copia que Windows inicia en el escritorio seguro (SYSTEM)?"""
	try:
		from .. import secure_screens

		return secure_screens.runningOnSecureScreen()
	except Exception:
		return False


def _secureMode() -> bool:
	try:
		from ..config import policy

		return bool(policy.policy.secureMode)
	except Exception:
		return False


def _syncSecureScreens() -> None:
	try:
		from .. import secure_screens

		secure_screens.syncRunning()
	except Exception:
		log.debug("No se pudo avisar a Windows de las pantallas seguras", exc_info=True)


def _stopSecureScreens() -> None:
	try:
		from .. import secure_screens

		secure_screens.setRunning(False)
	except Exception:
		log.debug("No se pudo avisar a Windows de las pantallas seguras", exc_info=True)


def secureScreensEnabled() -> bool:
	"""La opción de las pantallas seguras está activada para esta copia (HKLM)."""
	try:
		from .. import secure_screens

		return secure_screens.isEnabled()
	except Exception:
		return False


def releaseScreenReaderFlag() -> None:
	"""Tiresias cede ante otro lector: deja de ocuparse del indicador sin tocarlo.

	El otro lector lo activa por su cuenta (y lo restaura al salir); si
	Tiresias lo desactivara ahora, le quitaría el indicador a ese lector.
	"""
	global _previousScreenReaderFlag
	# En espera, Windows no debe iniciar Tiresias en las pantallas seguras.
	_stopSecureScreens()
	if _previousScreenReaderFlag is not None:
		log.info("Indicador de lector de pantalla cedido al otro lector")
	_previousScreenReaderFlag = None


def _restoreScreenReaderFlag() -> None:
	global _previousScreenReaderFlag
	if _previousScreenReaderFlag is None:
		return
	if not _previousScreenReaderFlag:
		# Solo se desactiva si estaba desactivado al arrancar (si otro lector lo
		# había activado, se deja como estaba).
		setScreenReaderFlag(False)
	_previousScreenReaderFlag = None


# ------------------------------------------------------------------ tecnología de asistencia
def _launchInfo() -> tuple[str, str]:
	from .. import paths

	if paths.FROZEN:
		return sys.executable, ""
	exe = sys.executable
	pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
	script = os.path.join(paths.SOURCE_DIR, "tiresias.pyw")
	return (pyw if os.path.isfile(pyw) else exe), f'"{script}"'


def _atValues(machine: bool = False) -> dict[str, tuple[int, object]]:
	"""Valores del registro. ``machine``: el de HKLM, que Windows puede usar en el
	escritorio seguro (inicio de sesión) con la cuenta SYSTEM: siempre con ``--secure``
	y con ``--ease-of-access`` (iniciada por Windows; ver :mod:`tiresias.secure_screens`)."""
	exe, params = _launchInfo()
	if machine:
		params = (params + " --secure --ease-of-access").strip()
	return {
		"ApplicationName": (winreg.REG_SZ, APP_NAME),
		"Description": (winreg.REG_SZ, "Lector de pantalla Tiresias"),
		"Profile": (winreg.REG_SZ, '<HCIModel><Accommodation type="severe vision"/></HCIModel>'),
		"SimpleProfile": (winreg.REG_SZ, "screenreader"),
		"ATExe": (winreg.REG_SZ, os.path.basename(exe)),
		"StartExe": (winreg.REG_SZ, exe),
		"StartParams": (winreg.REG_SZ, params),
		"TerminateOnDesktopSwitch": (winreg.REG_DWORD, 0),
	}


def canRegisterMachineWide() -> bool:
	"""HKLM solo para la copia instalada en una carpeta protegida (Archivos de programa).

	Una copia portable (o el código fuente) está en una carpeta que el usuario
	puede escribir: registrarla para todo el equipo dejaría a Windows iniciar
	como SYSTEM un ejecutable que cualquiera podría sustituir.
	"""
	from .. import paths, secure_env

	exe, _params = _launchInfo()
	return bool(paths.FROZEN and paths.isInstalledCopy() and secure_env.isTrustedDir(os.path.dirname(exe)))


def _deleteOwnMachineAT() -> None:
	"""Quita de HKLM un registro anterior que apunte a esta copia (si hay permiso)."""
	try:
		with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, AT_KEY + "\\" + AT_NAME) as k:
			startExe = winreg.QueryValueEx(k, "StartExe")[0]
	except OSError:
		return
	exe, _params = _launchInfo()
	if os.path.normcase(str(startExe)) == os.path.normcase(exe):
		_deleteAT(winreg.HKEY_LOCAL_MACHINE)


def _writeAT(root, machine: bool = False) -> bool:
	try:
		with winreg.CreateKeyEx(root, AT_KEY + "\\" + AT_NAME, 0, winreg.KEY_WRITE) as k:
			for name, (kind, value) in _atValues(machine).items():
				winreg.SetValueEx(k, name, 0, kind, value)
		return True
	except OSError:
		return False


def _deleteAT(root) -> None:
	try:
		winreg.DeleteKey(root, AT_KEY + "\\" + AT_NAME)
	except OSError:
		pass


def isRegisteredAsAT() -> bool:
	try:
		with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AT_KEY + "\\" + AT_NAME):
			return True
	except OSError:
		return False


def applyATRegistration() -> None:
	"""Registra o borra Tiresias como tecnología de asistencia según la opción."""
	if _secureMode() or _onSecureScreen():
		# Modo seguro (y la copia SYSTEM del escritorio seguro): no se toca el registro.
		return
	if conf["system"]["registerAsAT"]:
		ok = _writeAT(winreg.HKEY_CURRENT_USER)
		# HKLM solo se puede escribir con permisos de administrador, y solo para
		# la copia instalada (con --secure: ver canRegisterMachineWide).
		if canRegisterMachineWide():
			_writeAT(winreg.HKEY_LOCAL_MACHINE, machine=True)
		else:
			_deleteOwnMachineAT()
		if ok:
			log.info("Registrado como tecnología de asistencia")
	else:
		if isRegisteredAsAT():
			_deleteAT(winreg.HKEY_CURRENT_USER)
			# El de HKLM lo necesita la opción de las pantallas seguras si está activada.
			if not secureScreensEnabled():
				_deleteAT(winreg.HKEY_LOCAL_MACHINE)
			log.info("Registro de tecnología de asistencia eliminado")


# ------------------------------------------------------------------ bloqueo
class _WTSINFOEX_LEVEL1(ctypes.Structure):
	_fields_ = [
		("SessionId", wintypes.ULONG),
		("SessionState", ctypes.c_int),
		("SessionFlags", wintypes.LONG),
		("WinStationName", wintypes.WCHAR * 33),
		("UserName", wintypes.WCHAR * 21),
		("DomainName", wintypes.WCHAR * 18),
		("LogonTime", ctypes.c_int64),
		("ConnectTime", ctypes.c_int64),
		("DisconnectTime", ctypes.c_int64),
		("LastInputTime", ctypes.c_int64),
		("CurrentTime", ctypes.c_int64),
		("IncomingBytes", wintypes.DWORD),
		("OutgoingBytes", wintypes.DWORD),
		("IncomingFrames", wintypes.DWORD),
		("OutgoingFrames", wintypes.DWORD),
		("IncomingCompressedBytes", wintypes.DWORD),
		("OutgoingCompressedBytes", wintypes.DWORD),
	]


class _WTSINFOEX(ctypes.Structure):
	_fields_ = [("Level", wintypes.DWORD), ("Data", _WTSINFOEX_LEVEL1)]


WTS_CURRENT_SERVER_HANDLE = None
WTS_CURRENT_SESSION = 0xFFFFFFFF
WTSSessionInfoEx = 25
WTS_SESSIONSTATE_LOCK = 0
WTS_SESSIONSTATE_UNLOCK = 1

try:
	_wtsapi = ctypes.windll.wtsapi32
	_wtsapi.WTSQuerySessionInformationW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
	_wtsapi.WTSQuerySessionInformationW.restype = wintypes.BOOL
	_wtsapi.WTSFreeMemory.argtypes = [ctypes.c_void_p]
except (OSError, AttributeError):
	_wtsapi = None


def isSessionLocked() -> bool | None:
	"""``True`` si la sesión está bloqueada (``None`` si no se puede saber)."""
	if _wtsapi is None:
		return None
	buf = ctypes.c_void_p()
	size = wintypes.DWORD()
	if not _wtsapi.WTSQuerySessionInformationW(WTS_CURRENT_SERVER_HANDLE, WTS_CURRENT_SESSION, WTSSessionInfoEx, ctypes.byref(buf), ctypes.byref(size)):
		return None
	try:
		info = ctypes.cast(buf, ctypes.POINTER(_WTSINFOEX)).contents
		if info.Level != 1:
			return None
		flags = info.Data.SessionFlags
		if flags == WTS_SESSIONSTATE_LOCK:
			return True
		if flags == WTS_SESSIONSTATE_UNLOCK:
			return False
		return None
	finally:
		_wtsapi.WTSFreeMemory(buf)


def _foregroundProcessName() -> str:
	from .. import winapi

	fg = winapi.getForegroundWindow()
	if not fg:
		return ""
	return winapi.getProcessName(winapi.getWindowProcessId(fg))


def isLockScreenActive() -> bool:
	"""``True`` mientras la pantalla de bloqueo está activa (caché de 0,5 s)."""
	global _lockCache
	now = time.monotonic()
	if now - _lockCache[0] < 0.5:
		return _lockCache[1]
	locked = isSessionLocked()
	if locked is None:
		locked = False
	if not locked:
		try:
			locked = _foregroundProcessName() == "lockapp"
		except Exception:
			locked = False
	_lockCache = (now, bool(locked))
	return bool(locked)


def invalidateLockCache() -> None:
	global _lockCache
	_lockCache = (0.0, False)


def isSecureObject(obj) -> bool:
	"""``True`` si ``obj`` no debe leerse porque la sesión está bloqueada."""
	if obj is None or not isLockScreenActive():
		return False
	try:
		from ..objects.roles import Role

		if obj.role == Role.DESKTOPPANE:
			return False
		from .. import winapi

		pid = obj.processID
		if not pid:
			return False
		return winapi.getProcessName(pid) not in LOCK_SCREEN_PROCESSES
	except Exception:
		return True


def filterSecure(obj):
	"""Devuelve ``obj`` o ``None`` si está protegido por la pantalla de bloqueo."""
	return None if isSecureObject(obj) else obj


# ------------------------------------------------------------------ escritorio seguro
def isSecureDesktopActive() -> bool:
	"""``True`` si el escritorio de entrada no es accesible (UAC, inicio de sesión)."""
	try:
		user32.OpenInputDesktop.restype = wintypes.HANDLE
		h = user32.OpenInputDesktop(0, False, 0)
		if h:
			user32.CloseDesktop(h)
			return False
		return True
	except Exception:
		return False


# ------------------------------------------------------------------ ciclo de vida
def applyConfig() -> None:
	try:
		applyScreenReaderFlag()
	except Exception:
		log.exception("No se pudo aplicar el indicador de lector de pantalla")
	try:
		applyATRegistration()
	except Exception:
		log.exception("No se pudo actualizar el registro de tecnología de asistencia")


def initialize() -> None:
	"""Se llama desde el núcleo tras iniciar UIA."""
	global _initialized
	from ..config import post_configProfileSwitch, post_configSave

	applyConfig()
	for action in (post_configSave, post_configProfileSwitch):
		try:
			action.register(_onConfigChanged)
		except Exception:
			pass
	from . import jab

	jab.initialize()
	_scheduleCleanup()
	# Sus opciones están en las categorías «Avanzado» y «Presentación de objetos».
	_initialized = True


def _scheduleCleanup() -> None:
	"""Limpieza periódica de la caché de API por ventana (ventanas cerradas)."""
	from .. import queue_handler
	from . import api_choice

	def run() -> None:
		if not _initialized:
			return
		try:
			api_choice.cleanup()
		except Exception:
			log.debug("Error limpiando la caché de API", exc_info=True)
		queue_handler.callLater(60000, run)

	queue_handler.callLater(60000, run)


def _onConfigChanged(*args, **kwargs) -> None:
	from .. import queue_handler

	queue_handler.queueFunction(applyConfig)
	queue_handler.queueFunction(_reapplyAPIChoice)


def _reapplyAPIChoice() -> None:
	from . import api_choice

	api_choice.invalidate()


def terminate() -> None:
	global _initialized
	from . import jab

	try:
		jab.terminate()
	except Exception:
		log.exception("Error cerrando Java Access Bridge")
	# Tiresias se cierra: Windows ya no debe iniciarla en las pantallas seguras.
	_stopSecureScreens()
	try:
		_restoreScreenReaderFlag()
	except Exception:
		log.exception("No se pudo restaurar el indicador de lector de pantalla")
	_initialized = False
