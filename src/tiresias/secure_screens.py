"""Pantallas seguras de Windows: inicio de sesión, Control de cuentas de usuario y Ctrl+Alt+Supr.

Windows no deja que un programa de la sesión del usuario lea esas pantallas:
están en otro escritorio («Winlogon») y sus ventanas son de la cuenta SYSTEM.
Lo que sí hace es iniciar en ellas, como SYSTEM, las tecnologías de asistencia
registradas para todo el equipo. Es lo mismo que hace NVDA instalado
(``easeOfAccess.py``, ``config.setStartOnLogonScreen`` e
``installer.registerEaseOfAccess``):

- **Registro** en ``HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Accessibility\\ATs\\tiresias``
  (vista de 64 bits): ``ApplicationName``, ``Description``, ``Profile``,
  ``SimpleProfile`` (``screenreader``), ``ATExe``, ``StartExe`` (ruta del
  ejecutable), ``StartParams`` (``--secure --ease-of-access``) y
  ``TerminateOnDesktopSwitch`` = 0. Solo HKLM: lo lee ATBroker.exe, el
  intermediario de «Accesibilidad» de Windows, que inicia el programa.
- **Inicio de sesión**: el valor ``Configuration`` (``REG_SZ``, nombres
  separados por comas) de ``HKLM\\...\\Accessibility`` lleva las tecnologías
  que Windows inicia en la pantalla de inicio de sesión. Es la opción «Usar
  NVDA durante el inicio de sesión» (``AutoStartContext.ON_LOGON_SCREEN``).
- **Control de cuentas de usuario, Ctrl+Alt+Supr y bloqueo**: la copia de la
  sesión del usuario avisa a ATBroker de que está en marcha escribiendo 3 en
  ``HKCU\\...\\AccessibilityTemp\\tiresias`` y pulsando Windows+U (que
  ATBroker intercepta y no abre la Configuración); al salir escribe 2. Con
  ese aviso, cuando Windows pasa al escritorio seguro inicia allí la
  tecnología registrada (``StartExe StartParams``) con la cuenta SYSTEM
  (``easeOfAccess.notify`` de NVDA).

La copia que se inicia en el escritorio seguro (``core.main``):

- fuerza el modo seguro (:func:`tiresias.secure_env.mustForceSecureMode`):
  configuración del sistema (``systemConfig`` en la carpeta del programa, de
  solo lectura), sin complementos, sin guardián que inicie otros lectores,
  sin la API de control ni su ventana «NVDA», sin abrir archivos;
- usa un mutex de instancia propio de ese escritorio, para no pelearse con la
  Tiresias del usuario (cada escritorio tiene su copia);
- termina sola cuando la entrada vuelve al escritorio del usuario
  («Default»): :class:`DesktopWatcher`.

Solo la copia **instalada para todos los usuarios en Archivos de programa**
puede usarse: Windows ejecuta ``StartExe`` como SYSTEM, así que la carpeta
no debe poder escribirla un usuario sin privilegios (una copia portable o
instalada en ``%LOCALAPPDATA%`` permitiría a cualquiera cambiar el
ejecutable y obtener permisos de SYSTEM).

Activar o desactivar la opción escribe en HKLM: si Tiresias no se ejecuta
como administrador, una copia elevada (``--secure-screens 1|0``, con el
permiso del Control de cuentas de usuario) hace el cambio y, al activarla,
copia también la configuración actual a la del sistema
(``--copy-config-to-system``) en el mismo paso.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Callable

from . import paths
from .log import getLogger

log = getLogger("pantallasSeguras")

#: Nombre de Tiresias como tecnología de asistencia (igual que ``a11y.system.AT_NAME``).
AT_NAME = "tiresias"
ACCESSIBILITY_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Accessibility"
ATS_KEY = ACCESSIBILITY_KEY + r"\ATs"
AT_KEY = ATS_KEY + "\\" + AT_NAME
TEMP_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\AccessibilityTemp"
CONFIGURATION_VALUE = "Configuration"
#: Argumento con el que Windows (ATBroker) inicia Tiresias.
EASE_OF_ACCESS_ARG = "--ease-of-access"
#: Señales de ``AccessibilityTemp`` (``easeOfAccess.notify`` de NVDA).
SIGNAL_STARTED = 3
SIGNAL_STOPPED = 2
#: Escritorio normal del usuario.
USER_DESKTOP = "default"
#: Intervalo (s) y comprobaciones seguidas de la vigilancia del escritorio.
WATCH_INTERVAL = 0.4
WATCH_CONFIRM = 2
#: Plazo (s) para cerrarse de forma ordenada antes de forzar la salida.
LEAVE_EXIT_TIMEOUT = 8.0


# ====================================================================== registro de Windows
class WinRegistry:
	"""Acceso mínimo al registro (las pruebas lo sustituyen por uno falso)."""

	def _view(self) -> int:
		import winreg

		return winreg.KEY_WOW64_64KEY

	def getValue(self, root, key: str, name: str):
		"""Valor o ``None`` si no existe la clave o el valor."""
		import winreg

		try:
			with winreg.OpenKey(root, key, 0, winreg.KEY_READ | self._view()) as k:
				return winreg.QueryValueEx(k, name)[0]
		except FileNotFoundError:
			return None

	def keyExists(self, root, key: str) -> bool:
		import winreg

		try:
			with winreg.OpenKey(root, key, 0, winreg.KEY_READ | self._view()):
				return True
		except FileNotFoundError:
			return False

	def setValues(self, root, key: str, values: dict) -> None:
		"""``values``: ``{nombre: (tipo, valor)}``."""
		import winreg

		with winreg.CreateKeyEx(root, key, 0, winreg.KEY_READ | winreg.KEY_WRITE | self._view()) as k:
			for name, (kind, value) in values.items():
				winreg.SetValueEx(k, name, 0, kind, value)

	def deleteKey(self, root, key: str) -> None:
		import winreg

		try:
			winreg.DeleteKeyEx(root, key, self._view(), 0)
		except FileNotFoundError:
			pass


registry = WinRegistry()


def _hklm():
	import winreg

	return winreg.HKEY_LOCAL_MACHINE


def _hkcu():
	import winreg

	return winreg.HKEY_CURRENT_USER


# ====================================================================== disponibilidad
def exePath() -> str:
	"""Ejecutable que Windows iniciaría (``StartExe``)."""
	from .a11y import system

	return system._launchInfo()[0]


def runningOnSecureScreen() -> bool:
	"""¿Esta copia es la del escritorio seguro (cuenta SYSTEM o escritorio que no es «Default»)?"""
	global _secureScreen
	if _secureScreen is None:
		from . import secure_env

		_secureScreen = secure_env.mustForceSecureMode()
	return _secureScreen


_secureScreen: bool | None = None


def _secureMode() -> bool:
	try:
		from .config import policy

		return bool(policy.policy.secureMode)
	except Exception:
		return False


def availability() -> tuple[bool, str]:
	"""``(disponible, motivo)``: la opción solo vale en la copia instalada en Archivos de programa."""
	from .i18n import _

	if runningOnSecureScreen() or _secureMode():
		return False, _("No se puede cambiar en modo seguro.")
	if not (paths.FROZEN and paths.isInstalledCopy()):
		return False, _(
			"Solo en la copia instalada: esta copia de Tiresias es portable. Windows solo puede iniciar en el inicio de sesión "
			"y en las pantallas seguras un lector instalado para todos los usuarios en Archivos de programa."
		)
	from . import secure_env

	if not secure_env.isTrustedDir(os.path.dirname(exePath())):
		return False, _(
			"Solo en la copia instalada para todos los usuarios en Archivos de programa: esta copia está en una carpeta "
			"que un usuario sin privilegios puede modificar."
		)
	return True, ""


def isAvailable() -> bool:
	return availability()[0]


# ====================================================================== estado en el registro
def readConfiguration(root=None) -> list[str]:
	"""Tecnologías de ``Accessibility\\Configuration`` (HKLM: las del inicio de sesión)."""
	value = registry.getValue(_hklm() if root is None else root, ACCESSIBILITY_KEY, CONFIGURATION_VALUE)
	if not isinstance(value, str) or not value.strip():
		return []
	return [v for v in value.split(",") if v]


def _writeConfiguration(names: list[str], root=None) -> None:
	import winreg

	registry.setValues(_hklm() if root is None else root, ACCESSIBILITY_KEY, {CONFIGURATION_VALUE: (winreg.REG_SZ, ",".join(names))})


def isStartOnLogonScreen() -> bool:
	return AT_NAME in [n.strip().lower() for n in readConfiguration()]


def registeredExe() -> str:
	"""``StartExe`` del registro de Tiresias en HKLM (``""`` si no está registrada)."""
	value = registry.getValue(_hklm(), AT_KEY, "StartExe")
	return str(value) if value else ""


def _samePath(a: str, b: str) -> bool:
	if not a or not b:
		return False
	return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def isRegisteredForThisCopy(exe: str | None = None) -> bool:
	return _samePath(registeredExe(), exe or exePath())


def isEnabled() -> bool:
	"""``True`` si esta copia está registrada en HKLM y en el inicio de sesión."""
	try:
		return isRegisteredForThisCopy() and isStartOnLogonScreen()
	except OSError:
		log.debug("No se pudo leer el registro de las pantallas seguras", exc_info=True)
		return False


# ====================================================================== cambios (administrador)
def machineValues() -> dict:
	from .a11y import system

	return system._atValues(machine=True)


def applyMachine(enable: bool, exe: str | None = None) -> None:
	"""Registra (o quita) esta copia en HKLM. Necesita permisos de administrador.

	Al quitar, el registro ``ATs\\tiresias`` solo se borra si es de esta copia
	(otra copia instalada puede ser la registrada).
	"""
	exe = exe or exePath()
	names = readConfiguration()
	others = [n for n in names if n.strip().lower() != AT_NAME]
	if enable:
		registry.setValues(_hklm(), AT_KEY, machineValues())
		if others + [AT_NAME] != names:
			_writeConfiguration(others + [AT_NAME])
		log.info("Tiresias registrada para el inicio de sesión y las pantallas seguras (%s)", exe)
		return
	if others != names:
		_writeConfiguration(others)
	if isRegisteredForThisCopy(exe):
		registry.deleteKey(_hklm(), AT_KEY)
	log.info("Tiresias ya no se usa en el inicio de sesión ni en las pantallas seguras")


def unregisterIfFrom(exe: str) -> bool:
	"""Desinstalación: quita el registro si es de la copia ``exe`` (necesita administrador)."""
	try:
		if not isRegisteredForThisCopy(exe):
			return False
		applyMachine(False, exe)
		return True
	except OSError:
		log.exception("No se pudo quitar Tiresias de las pantallas seguras")
		return False


def elevatedArguments(enable: bool, copyConfigFrom: str | None = None) -> list[str]:
	"""Argumentos de la copia elevada que hace el cambio (y la copia de la configuración)."""
	args = ["--secure-screens", "1" if enable else "0"]
	if enable and copyConfigFrom:
		args += ["--copy-config-to-system", copyConfigFrom]
	return args


def setEnabled(enable: bool, copyConfigFrom: str | None = None) -> None:
	"""Activa o desactiva la opción (hilo propio: puede esperar al Control de cuentas).

	Al activarla se copia ``copyConfigFrom`` a la configuración del sistema.
	Lanza ``OSError`` con el motivo si no se puede.
	"""
	from . import installer, secure_env

	ok, reason = availability()
	if not ok:
		raise OSError(reason)
	if not enable:
		# Antes de quitar el registro: con él, Windows atiende el aviso.
		setRunning(False)
	if secure_env.isElevated():
		applyMachine(enable)
		if enable and copyConfigFrom:
			installer.copyConfigToSystem(copyConfigFrom)
	else:
		exe, base = installer._launch()
		code = installer.shellExecuteElevated(exe, installer.quoteArgs(base + elevatedArguments(enable, copyConfigFrom)), wait=True)
		if code == 3:
			raise OSError("se ha cambiado el registro, pero no se pudo copiar la configuración al sistema")
		if code != 0:
			raise OSError(f"la copia con permisos de administrador terminó con el código {code}")
	if isEnabled() != bool(enable):
		raise OSError("el registro de Windows no ha cambiado")
	if enable:
		syncRunning()


def runCommand(enable: bool, copyConfigFrom: str | None = None) -> int:
	"""``--secure-screens 1|0`` (copia elevada). 0 bien; 1 registro; 2 no disponible; 3 copia; 5 sin permisos."""
	from . import installer, secure_env

	ok, reason = availability()
	if not ok:
		log.error("Pantallas seguras: %s", reason)
		return 2
	if not secure_env.isElevated():
		log.error("Las pantallas seguras necesitan permisos de administrador")
		return 5
	try:
		applyMachine(enable)
	except OSError:
		log.exception("No se pudo cambiar el registro de las pantallas seguras")
		return 1
	if enable and copyConfigFrom:
		try:
			installer.copyConfigToSystem(copyConfigFrom)
		except OSError:
			log.exception("No se pudo copiar la configuración al sistema")
			return 3
	return 0


# ====================================================================== aviso a Windows (sesión del usuario)
#: Último aviso enviado: ``True`` en marcha, ``False`` detenida, ``None`` ninguno.
_running: bool | None = None
_runningLock = threading.Lock()


def _inStandby() -> bool:
	try:
		from . import coexist

		return bool(coexist.isStandby())
	except Exception:
		return False


def shouldAnnounceRunning() -> bool:
	"""Solo la copia de la sesión del usuario, activa y con la opción activada."""
	if runningOnSecureScreen() or not paths.FROZEN or _inStandby():
		return False
	return isEnabled()


def _sendWinU() -> None:
	"""Windows+U soltando antes las teclas modificadoras pulsadas (como NVDA)."""
	from . import winapi

	VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_U = 0x10, 0x11, 0x12, 0x5B, 0x55
	keys = [(vk, False) for vk in (VK_SHIFT, VK_CONTROL, VK_MENU) if winapi.isKeyDown(vk)]
	keys += [(VK_LWIN, True), (VK_U, True)]
	inputs = []
	# Se sueltan las que sobran y se pulsan las que hacen falta...
	for vk, desired in keys:
		inputs.append(winapi.makeKeyInput(vk, up=not desired, extended=vk == VK_LWIN))
	# ...y al revés.
	for vk, desired in reversed(keys):
		inputs.append(winapi.makeKeyInput(vk, up=desired, extended=vk == VK_LWIN))
	winapi.sendInputs(inputs)


def notify(signal: int) -> bool:
	"""Avisa a ATBroker (``AccessibilityTemp`` y Windows+U). Solo con el registro de esta copia."""
	import winreg

	if not isRegisteredForThisCopy():
		return False
	try:
		registry.setValues(_hkcu(), TEMP_KEY, {AT_NAME: (winreg.REG_DWORD, int(signal))})
		_sendWinU()
		return True
	except OSError:
		log.exception("No se pudo avisar a Windows (señal %d)", signal)
		return False


def setRunning(running: bool) -> None:
	"""Avisa a Windows de que Tiresias está en marcha (o ya no) solo si cambia."""
	global _running
	with _runningLock:
		if running:
			if _running is True or not shouldAnnounceRunning():
				return
			if notify(SIGNAL_STARTED):
				_running = True
				log.info("Windows sabe que Tiresias está en marcha: la usará en las pantallas seguras")
		else:
			if _running is not True:
				return
			notify(SIGNAL_STOPPED)
			_running = False


def syncRunning() -> None:
	"""Activa el aviso si procede (al arrancar, al activarse tras la espera, al cambiar opciones)."""
	try:
		setRunning(True)
	except Exception:
		log.exception("No se pudo avisar a Windows de que Tiresias está en marcha")


# ====================================================================== copia del escritorio seguro
class DesktopWatcher:
	"""Detecta que la entrada ha vuelto al escritorio del usuario («Default»).

	Solo actúa si esta copia está en otro escritorio (``Winlogon``) y tras
	:data:`WATCH_CONFIRM` comprobaciones seguidas (los cambios de escritorio
	pasan por estados intermedios). Si no se puede abrir el escritorio de
	entrada no se decide nada.
	"""

	def __init__(self, ownDesktop: str, onLeave: Callable[[], None], inputDesktop: Callable[[], str | None] | None = None, confirm: int = WATCH_CONFIRM) -> None:
		self.ownDesktop = (ownDesktop or "").lower()
		self.onLeave = onLeave
		self.inputDesktop = inputDesktop or inputDesktopName
		self.confirm = max(1, int(confirm))
		self.count = 0
		self.left = False

	@property
	def active(self) -> bool:
		return bool(self.ownDesktop) and self.ownDesktop != USER_DESKTOP

	def check(self) -> bool:
		"""Una comprobación; ``True`` cuando se decide salir (una sola vez)."""
		if self.left or not self.active:
			return False
		name = self.inputDesktop()
		if name and name.lower() == USER_DESKTOP:
			self.count += 1
		else:
			self.count = 0
		if self.count >= self.confirm:
			self.left = True
			try:
				self.onLeave()
			except Exception:
				log.exception("Error al salir del escritorio seguro")
			return True
		return False

	def run(self, stop: threading.Event, interval: float = WATCH_INTERVAL) -> None:
		while not stop.wait(interval):
			if self.check():
				return


def inputDesktopName() -> str | None:
	"""Nombre del escritorio que recibe la entrada (``None`` si no se puede abrir)."""
	if sys.platform != "win32":
		return None
	import ctypes
	from ctypes import wintypes

	u32 = ctypes.WinDLL("user32", use_last_error=True)
	u32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
	u32.OpenInputDesktop.restype = wintypes.HANDLE
	u32.CloseDesktop.argtypes = [wintypes.HANDLE]
	u32.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
	u32.GetUserObjectInformationW.restype = wintypes.BOOL
	h = u32.OpenInputDesktop(0, False, 0x0001)  # DESKTOP_READOBJECTS
	if not h:
		return None
	try:
		buf = ctypes.create_unicode_buffer(256)
		needed = wintypes.DWORD(0)
		if not u32.GetUserObjectInformationW(h, 2, buf, ctypes.sizeof(buf), ctypes.byref(needed)):  # UOI_NAME
			return None
		return buf.value
	finally:
		u32.CloseDesktop(h)


_watcherStop = threading.Event()
_watcher: DesktopWatcher | None = None


def leaveSecureDesktop() -> None:
	"""La entrada ha vuelto al escritorio del usuario: esta copia se calla y se cierra."""
	from . import core, queue_handler

	log.info("La entrada ha vuelto al escritorio del usuario: se cierra la copia del escritorio seguro")

	def silence() -> None:
		try:
			from . import speech
			from .speech import api as speechApi

			speech.cancelSpeech()
			speechApi.setSuspended(True)
		except Exception:
			log.debug("No se pudo callar la voz", exc_info=True)

	try:
		queue_handler.queueFunction(silence)
	except Exception:
		log.debug("No se pudo encolar el silencio", exc_info=True)
	core.requestQuit()

	def force() -> None:
		time.sleep(LEAVE_EXIT_TIMEOUT)
		core._forceExit("la copia del escritorio seguro no se ha cerrado al volver al escritorio del usuario")

	threading.Thread(target=force, name="Salida del escritorio seguro", daemon=True).start()


def startDesktopWatcher(ownDesktop: str | None = None) -> DesktopWatcher | None:
	"""Vigila la vuelta al escritorio del usuario (solo en la copia del escritorio seguro)."""
	global _watcher
	if _watcher is not None:
		return _watcher
	if ownDesktop is None:
		from . import secure_env

		ownDesktop = secure_env.threadDesktopName()
	watcher = DesktopWatcher(ownDesktop, leaveSecureDesktop)
	if not watcher.active:
		return None
	_watcher = watcher
	_watcherStop.clear()
	threading.Thread(target=watcher.run, args=(_watcherStop,), name="Vigilancia del escritorio seguro", daemon=True).start()
	log.info("Copia del escritorio seguro (%s): se cerrará al volver al escritorio del usuario", ownDesktop)
	return watcher


def stopDesktopWatcher() -> None:
	global _watcher
	_watcherStop.set()
	_watcher = None
