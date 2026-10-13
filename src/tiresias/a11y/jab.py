"""Java Access Bridge (JAB): accesibilidad de las aplicaciones Java (Swing/AWT).

Funcionamiento:

- La biblioteca ``WindowsAccessBridge-64.dll`` viene con cualquier JRE/JDK
  moderno (``bin``). Se busca en ``JAVA_HOME``, en el registro de JavaSoft, en
  las carpetas habituales de Program Files (Oracle, Adoptium, Microsoft,
  Zulu, Corretto, BellSoft…), en el ``PATH`` y, al aparecer una ventana Java,
  junto al ejecutable del proceso (JRE incluido con la aplicación).
- La carga es diferida (#20833): no se toca nada hasta que aparece la primera
  ventana Java (clase ``SunAwt*``), así el arranque no se ralentiza.
- La biblioteca necesita un hilo con bucle de mensajes: :class:`_BridgeThread`
  llama a ``Windows_run`` y bombea mensajes. Los eventos (foco, cursor,
  nombre, valor, estado, descendiente activo) llegan a ese hilo y solo se
  encolan en el núcleo. Solo se procesan si el foco está dentro de la ventana
  Java (#14344).
- Para que la máquina virtual cargue el puente, Java Access Bridge tiene que
  estar activado en el usuario (``jabswitch -enable`` o el archivo
  ``%USERPROFILE%\\.accessibility.properties``). Tiresias lo comprueba y, si
  hace falta, pregunta antes de activarlo (:func:`enableBridge`).
"""

from __future__ import annotations

import ctypes
import glob
import os
import subprocess
import threading
import winreg
from ctypes import wintypes

from ..config import conf
from ..i18n import _
from ..log import getLogger

log = getLogger("jab")

DLL_NAME = "WindowsAccessBridge-64.dll"
PROPERTIES_FILE = os.path.join(os.path.expanduser("~"), ".accessibility.properties")
PROPERTIES_LINE = "assistive_technologies=com.sun.java.accessibility.AccessBridge"

MAX_STRING_SIZE = 1024
SHORT_STRING_SIZE = 256
MAX_ACTION_INFO = 256
MAX_ACTIONS_TO_DO = 32

JOBJECT64 = ctypes.c_int64
jint = ctypes.c_int
vmID_t = ctypes.c_long

# Bits de AccessibleContextInfo.accessibleInterfaces.
INTERFACE_VALUE = 1
INTERFACE_ACTION = 2
INTERFACE_COMPONENT = 4
INTERFACE_SELECTION = 8
INTERFACE_TABLE = 16
INTERFACE_TEXT = 32
INTERFACE_HYPERTEXT = 64


class AccessibleContextInfo(ctypes.Structure):
	_fields_ = [
		("name", wintypes.WCHAR * MAX_STRING_SIZE),
		("description", wintypes.WCHAR * MAX_STRING_SIZE),
		("role", wintypes.WCHAR * SHORT_STRING_SIZE),
		("role_en_US", wintypes.WCHAR * SHORT_STRING_SIZE),
		("states", wintypes.WCHAR * SHORT_STRING_SIZE),
		("states_en_US", wintypes.WCHAR * SHORT_STRING_SIZE),
		("indexInParent", jint),
		("childrenCount", jint),
		("x", jint),
		("y", jint),
		("width", jint),
		("height", jint),
		("accessibleComponent", wintypes.BOOL),
		("accessibleAction", wintypes.BOOL),
		("accessibleSelection", wintypes.BOOL),
		("accessibleText", wintypes.BOOL),
		("accessibleInterfaces", wintypes.BOOL),
	]


class AccessibleTextInfo(ctypes.Structure):
	_fields_ = [("charCount", jint), ("caretIndex", jint), ("indexAtPoint", jint)]


class AccessibleTextSelectionInfo(ctypes.Structure):
	_fields_ = [("selectionStartIndex", jint), ("selectionEndIndex", jint), ("selectedText", wintypes.WCHAR * MAX_STRING_SIZE)]


class AccessibleTextRectInfo(ctypes.Structure):
	_fields_ = [("x", jint), ("y", jint), ("width", jint), ("height", jint)]


class AccessibleActionInfo(ctypes.Structure):
	_fields_ = [("name", wintypes.WCHAR * SHORT_STRING_SIZE)]


class AccessibleActions(ctypes.Structure):
	_fields_ = [("actionsCount", jint), ("actionInfo", AccessibleActionInfo * MAX_ACTION_INFO)]


class AccessibleActionsToDo(ctypes.Structure):
	_fields_ = [("actionsCount", jint), ("actions", AccessibleActionInfo * MAX_ACTIONS_TO_DO)]


# Prototipos de las retrollamadas de eventos.
FocusGainedFP = ctypes.CFUNCTYPE(None, vmID_t, JOBJECT64, JOBJECT64)
CaretUpdateFP = ctypes.CFUNCTYPE(None, vmID_t, JOBJECT64, JOBJECT64)
PropertyStringChangeFP = ctypes.CFUNCTYPE(None, vmID_t, JOBJECT64, JOBJECT64, wintypes.LPWSTR, wintypes.LPWSTR)
PropertyCaretChangeFP = ctypes.CFUNCTYPE(None, vmID_t, JOBJECT64, JOBJECT64, ctypes.c_int, ctypes.c_int)
PropertyDescendentChangeFP = ctypes.CFUNCTYPE(None, vmID_t, JOBJECT64, JOBJECT64, JOBJECT64, JOBJECT64)
PropertyChangeFP = ctypes.CFUNCTYPE(None, vmID_t, JOBJECT64, JOBJECT64)

bridge = None  # La DLL cargada (ctypes.CDLL) cuando está disponible.
_thread: "_BridgeThread | None" = None
_loadAttempted = False
_dllPath = ""
_callbacks: list = []
_askedThisSession = False
_lock = threading.Lock()


# ------------------------------------------------------------------ búsqueda de la DLL
def _registryJavaHomes() -> list[str]:
	out: list[str] = []
	bases = (
		r"SOFTWARE\JavaSoft\Java Runtime Environment",
		r"SOFTWARE\JavaSoft\JRE",
		r"SOFTWARE\JavaSoft\Java Development Kit",
		r"SOFTWARE\JavaSoft\JDK",
	)
	for base in bases:
		try:
			with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
				i = 0
				while True:
					try:
						sub = winreg.EnumKey(k, i)
					except OSError:
						break
					i += 1
					try:
						with winreg.OpenKey(k, sub) as v:
							home, _t = winreg.QueryValueEx(v, "JavaHome")
							if home:
								out.append(home)
					except OSError:
						continue
		except OSError:
			continue
	return out


def candidateDllPaths(extraDirs: list[str] | None = None) -> list[str]:
	"""Rutas donde puede estar ``WindowsAccessBridge-64.dll``, en orden de preferencia.

	Primero la carpeta de la aplicación Java (``extraDirs``, su JRE incluido).
	Como cualquier programa puede crear una ventana «SunAwt*» y dejar una DLL
	junto a él, con Tiresias elevado solo valen carpetas protegidas
	(:func:`_allowedDir`): sin elevar, esa DLL no consigue más permisos de los
	que ya tiene quien la deja.
	"""
	dirs: list[str] = list(extraDirs or [])
	home = os.environ.get("JAVA_HOME")
	if home:
		dirs.append(os.path.join(home, "bin"))
	dirs.extend(os.path.join(h, "bin") for h in _registryJavaHomes())
	for pf in {os.environ.get("ProgramW6432", ""), os.environ.get("ProgramFiles", "")} - {""}:
		for vendor in ("Java", "Eclipse Adoptium", "Microsoft", "Zulu", "Amazon Corretto", "BellSoft", "OpenJDK", "AdoptOpenJDK", "Eclipse Foundation", "Semeru"):
			dirs.extend(sorted(glob.glob(os.path.join(pf, vendor, "*", "bin")), reverse=True))
	for p in os.environ.get("PATH", "").split(os.pathsep):
		if p and os.path.isfile(os.path.join(p, "java.exe")):
			dirs.append(p)
	dirs.append(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32"))
	seen: set[str] = set()
	out: list[str] = []
	for d in dirs:
		if not d or not os.path.isabs(d) or not _allowedDir(d):
			continue
		path = os.path.normcase(os.path.join(d, DLL_NAME))
		if path not in seen:
			seen.add(path)
			out.append(os.path.join(d, DLL_NAME))
	return out


def findDll(extraDirs: list[str] | None = None) -> str:
	for path in candidateDllPaths(extraDirs):
		if os.path.isfile(path):
			return path
	return ""


def _allowedDir(folder: str) -> bool:
	"""¿Se puede cargar una DLL o ejecutar un programa de ``folder``?

	Con Tiresias elevado (reiniciado como administrador), solo carpetas que un
	usuario sin privilegios no puede escribir (Archivos de programa, Windows):
	si no, un programa cualquiera conseguiría ejecutar código como administrador.
	"""
	from .. import secure_env

	return not secure_env.isElevated() or secure_env.isTrustedDir(folder)


def findJabswitch() -> str:
	dll = _dllPath or findDll()
	if dll and _allowedDir(os.path.dirname(dll)):
		exe = os.path.join(os.path.dirname(dll), "jabswitch.exe")
		if os.path.isfile(exe):
			return exe
	for path in candidateDllPaths():
		exe = os.path.join(os.path.dirname(path), "jabswitch.exe")
		if os.path.isfile(exe):
			return exe
	return ""


# ------------------------------------------------------------------ activación en el usuario
def isBridgeEnabled() -> bool:
	"""``True`` si el archivo de propiedades del usuario activa el puente."""
	try:
		with open(PROPERTIES_FILE, encoding="latin-1") as f:
			for line in f:
				line = line.strip()
				if line.startswith("#"):
					continue
				if line.replace(" ", "").lower().startswith("assistive_technologies=") and "accessbridge" in line.lower():
					return True
	except OSError:
		return False
	return False


def enableBridge() -> bool:
	"""Activa Java Access Bridge para el usuario actual (``jabswitch -enable`` o propiedades)."""
	exe = findJabswitch()
	if exe:
		try:
			subprocess.run([exe, "-enable"], capture_output=True, timeout=20, creationflags=0x08000000)
		except (OSError, subprocess.SubprocessError):
			log.debug("jabswitch falló", exc_info=True)
	if isBridgeEnabled():
		return True
	try:
		lines: list[str] = []
		if os.path.isfile(PROPERTIES_FILE):
			with open(PROPERTIES_FILE, encoding="latin-1") as f:
				lines = [ln.rstrip("\r\n") for ln in f if not ln.strip().lower().startswith("assistive_technologies")]
		lines.append(PROPERTIES_LINE)
		lines.append("screen_magnifier_present=true")
		with open(PROPERTIES_FILE, "w", encoding="latin-1") as f:
			f.write("\n".join(dict.fromkeys(lines)) + "\n")
		return True
	except OSError:
		log.exception("No se pudo escribir %s", PROPERTIES_FILE)
		return False


def disableBridge() -> bool:
	exe = findJabswitch()
	if exe:
		try:
			subprocess.run([exe, "-disable"], capture_output=True, timeout=20, creationflags=0x08000000)
		except (OSError, subprocess.SubprocessError):
			pass
	if not isBridgeEnabled():
		return True
	try:
		with open(PROPERTIES_FILE, encoding="latin-1") as f:
			lines = [ln for ln in f if not (ln.strip().lower().startswith("assistive_technologies") and "accessbridge" in ln.lower())]
		with open(PROPERTIES_FILE, "w", encoding="latin-1") as f:
			f.writelines(lines)
		return True
	except OSError:
		return False


# ------------------------------------------------------------------ carga
def _declare(dll) -> None:
	p = ctypes.POINTER
	dll.Windows_run.argtypes = []
	dll.Windows_run.restype = wintypes.BOOL
	dll.isJavaWindow.argtypes = [wintypes.HWND]
	dll.isJavaWindow.restype = wintypes.BOOL
	dll.getAccessibleContextFromHWND.argtypes = [wintypes.HWND, p(vmID_t), p(JOBJECT64)]
	dll.getAccessibleContextFromHWND.restype = wintypes.BOOL
	dll.getHWNDFromAccessibleContext.argtypes = [vmID_t, JOBJECT64]
	dll.getHWNDFromAccessibleContext.restype = wintypes.HWND
	dll.getAccessibleContextWithFocus.argtypes = [wintypes.HWND, p(vmID_t), p(JOBJECT64)]
	dll.getAccessibleContextWithFocus.restype = wintypes.BOOL
	dll.getAccessibleContextInfo.argtypes = [vmID_t, JOBJECT64, p(AccessibleContextInfo)]
	dll.getAccessibleContextInfo.restype = wintypes.BOOL
	dll.getAccessibleChildFromContext.argtypes = [vmID_t, JOBJECT64, jint]
	dll.getAccessibleChildFromContext.restype = JOBJECT64
	dll.getAccessibleParentFromContext.argtypes = [vmID_t, JOBJECT64]
	dll.getAccessibleParentFromContext.restype = JOBJECT64
	dll.releaseJavaObject.argtypes = [vmID_t, JOBJECT64]
	dll.releaseJavaObject.restype = None
	dll.isSameObject.argtypes = [vmID_t, JOBJECT64, JOBJECT64]
	dll.isSameObject.restype = wintypes.BOOL
	dll.getAccessibleTextInfo.argtypes = [vmID_t, JOBJECT64, p(AccessibleTextInfo), jint, jint]
	dll.getAccessibleTextInfo.restype = wintypes.BOOL
	dll.getAccessibleTextSelectionInfo.argtypes = [vmID_t, JOBJECT64, p(AccessibleTextSelectionInfo)]
	dll.getAccessibleTextSelectionInfo.restype = wintypes.BOOL
	dll.getAccessibleTextRange.argtypes = [vmID_t, JOBJECT64, jint, jint, wintypes.LPWSTR, ctypes.c_short]
	dll.getAccessibleTextRange.restype = wintypes.BOOL
	dll.getAccessibleTextLineBounds.argtypes = [vmID_t, JOBJECT64, jint, p(jint), p(jint)]
	dll.getAccessibleTextLineBounds.restype = wintypes.BOOL
	dll.getAccessibleTextRect.argtypes = [vmID_t, JOBJECT64, p(AccessibleTextRectInfo), jint]
	dll.getAccessibleTextRect.restype = wintypes.BOOL
	dll.setCaretPosition.argtypes = [vmID_t, JOBJECT64, ctypes.c_int]
	dll.setCaretPosition.restype = wintypes.BOOL
	dll.selectTextRange.argtypes = [vmID_t, JOBJECT64, ctypes.c_int, ctypes.c_int]
	dll.selectTextRange.restype = wintypes.BOOL
	dll.getCurrentAccessibleValueFromContext.argtypes = [vmID_t, JOBJECT64, wintypes.LPWSTR, ctypes.c_short]
	dll.getCurrentAccessibleValueFromContext.restype = wintypes.BOOL
	dll.getAccessibleActions.argtypes = [vmID_t, JOBJECT64, p(AccessibleActions)]
	dll.getAccessibleActions.restype = wintypes.BOOL
	dll.doAccessibleActions.argtypes = [vmID_t, JOBJECT64, p(AccessibleActionsToDo), p(jint)]
	dll.doAccessibleActions.restype = wintypes.BOOL
	dll.requestFocus.argtypes = [vmID_t, JOBJECT64]
	dll.requestFocus.restype = wintypes.BOOL
	dll.getVirtualAccessibleName.argtypes = [vmID_t, JOBJECT64, wintypes.LPWSTR, ctypes.c_int]
	dll.getVirtualAccessibleName.restype = wintypes.BOOL
	dll.getAccessibleContextAt.argtypes = [vmID_t, JOBJECT64, jint, jint, p(JOBJECT64)]
	dll.getAccessibleContextAt.restype = wintypes.BOOL
	dll.getTopLevelObject.argtypes = [vmID_t, JOBJECT64]
	dll.getTopLevelObject.restype = JOBJECT64
	for name, proto in (
		("setFocusGainedFP", FocusGainedFP),
		("setCaretUpdateFP", CaretUpdateFP),
		("setPropertyNameChangeFP", PropertyStringChangeFP),
		("setPropertyValueChangeFP", PropertyStringChangeFP),
		("setPropertyStateChangeFP", PropertyStringChangeFP),
		("setPropertyDescriptionChangeFP", PropertyStringChangeFP),
		("setPropertyCaretChangeFP", PropertyCaretChangeFP),
		("setPropertyActiveDescendentChangeFP", PropertyDescendentChangeFP),
		("setPropertyTextChangeFP", PropertyChangeFP),
	):
		getattr(dll, name).argtypes = [proto]
		getattr(dll, name).restype = None


class _BridgeThread(threading.Thread):
	"""Hilo que inicia el puente y bombea sus mensajes."""

	def __init__(self, path: str) -> None:
		super().__init__(name="JavaAccessBridge", daemon=True)
		self.path = path
		self.ready = threading.Event()
		self.ok = False
		self.threadId = 0

	def run(self) -> None:
		global bridge
		user32 = ctypes.windll.user32
		self.threadId = ctypes.windll.kernel32.GetCurrentThreadId()
		try:
			dll = ctypes.CDLL(self.path)
			_declare(dll)
			dll.Windows_run()
			_registerCallbacks(dll)
			bridge = dll
			self.ok = True
			log.info("Java Access Bridge cargado: %s", self.path)
		except (OSError, AttributeError):
			log.warning("No se pudo cargar Java Access Bridge desde %s", self.path, exc_info=True)
		finally:
			self.ready.set()
		if not self.ok:
			return
		msg = wintypes.MSG()
		while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
			user32.TranslateMessage(ctypes.byref(msg))
			user32.DispatchMessageW(ctypes.byref(msg))
		bridge = None

	def stop(self) -> None:
		if self.threadId:
			ctypes.windll.user32.PostThreadMessageW(self.threadId, 0x0012, 0, 0)  # WM_QUIT


def load(extraDirs: list[str] | None = None) -> bool:
	"""Carga el puente (una sola vez). Devuelve ``True`` si está disponible."""
	global _thread, _loadAttempted, _dllPath
	if bridge is not None:
		return True
	if not conf["java"]["enabled"]:
		return False
	with _lock:
		if _thread is not None and _thread.ok:
			return True
		path = findDll(extraDirs)
		if not path:
			if not _loadAttempted:
				log.info("Java Access Bridge no encontrado (no hay ningún JRE de 64 bits con %s)", DLL_NAME)
			_loadAttempted = True
			return False
		if _loadAttempted and path == _dllPath:
			return False
		_loadAttempted = True
		_dllPath = path
		_thread = _BridgeThread(path)
		_thread.start()
		_thread.ready.wait(5)
		return _thread.ok


def isAvailable() -> bool:
	return bridge is not None


def isJavaWindow(hwnd: int) -> bool:
	"""``True`` si ``hwnd`` es una ventana Java con el puente activo (carga diferida)."""
	if not conf["java"]["enabled"]:
		return False
	if bridge is None:
		from .. import winapi

		exeDir = ""
		try:
			exeDir = os.path.dirname(winapi.getProcessImagePath(winapi.getWindowProcessId(hwnd)))
		except Exception:
			pass
		if not load([exeDir] if exeDir else None):
			_maybeAskToEnable()
			return False
	try:
		return bool(bridge.isJavaWindow(hwnd))
	except (OSError, AttributeError):
		return False


def _maybeAskToEnable() -> None:
	"""Si hay una ventana Java pero el puente no está activado, pregunta una vez."""
	global _askedThisSession
	if _askedThisSession or not conf["java"]["askToEnable"] or isBridgeEnabled():
		return
	if not findDll():
		return
	_askedThisSession = True
	try:
		from .. import gui

		gui.runOnGui(_askToEnable)
	except Exception:
		log.debug("No se pudo preguntar por Java Access Bridge", exc_info=True)


def _askToEnable() -> None:
	import wx

	from .. import queue_handler, speech

	from ..gui import message_dialog

	# Cuadro propio con el texto recorrible (#258).
	res = message_dialog.messageBox(
		_(
			"Esta aplicación es de Java y Java Access Bridge no está activado, así que Tiresias no puede leerla bien.\n\n"
			"¿Activar Java Access Bridge para este usuario? Habrá que volver a abrir la aplicación Java."
		),
		_("Java Access Bridge"),
		wx.YES_NO | wx.ICON_QUESTION,
	)
	if res == wx.YES:
		ok = enableBridge()
		queue_handler.queueFunction(
			speech.speakMessage,
			_("Java Access Bridge activado. Vuelva a abrir la aplicación Java.") if ok else _("No se pudo activar Java Access Bridge"),
		)


def initialize() -> None:
	"""Nada que hacer al arrancar: la carga es diferida (#20833)."""


def terminate() -> None:
	global _thread, bridge
	if _thread is not None:
		_thread.stop()
		_thread.join(2)
	_thread = None
	bridge = None


# ------------------------------------------------------------------ eventos
def _release(vmID: int, *objs: int) -> None:
	if bridge is None:
		return
	for o in objs:
		if o:
			try:
				bridge.releaseJavaObject(vmID, o)
			except OSError:
				pass


def _isStandby() -> bool:
	try:
		from .. import coexist

		return coexist.isStandby()
	except Exception:
		return False


def _queue(eventName: str, vmID: int, source: int, **kwargs) -> None:
	from .. import queue_handler

	if _isStandby():
		# Otro lector tiene preferencia: los eventos Java no se procesan (como los
		# de UIA y los WinEvents en espera). El objeto del evento se suelta ya.
		_release(vmID, source)
		return
	queue_handler.queueFunction(_dispatch, eventName, vmID, source, kwargs)


def releaseObject(vmID: int, context: int) -> None:
	"""Suelta un objeto Java en el hilo del núcleo (desde cualquier hilo).

	Los objetos se liberan al recogerlos el recolector de Python, que puede
	ejecutarse en cualquier hilo; el puente se usa siempre desde el núcleo.
	"""
	if not context or bridge is None:
		return
	from .. import queue_handler

	if queue_handler.isCoreThread() or queue_handler._coreThreadId is None:
		_release(vmID, context)
	else:
		queue_handler.queueFunction(_release, vmID, context)


def _registerCallbacks(dll) -> None:
	def focusGained(vmID, event, source):
		_queue("gainFocus", vmID, source)
		_release(vmID, event)

	def caretUpdate(vmID, event, source):
		_queue("caret", vmID, source)
		_release(vmID, event)

	def nameChange(vmID, event, source, old, new):
		_queue("nameChange", vmID, source)
		_release(vmID, event)

	def valueChange(vmID, event, source, old, new):
		_queue("valueChange", vmID, source)
		_release(vmID, event)

	def stateChange(vmID, event, source, old, new):
		_queue("stateChange", vmID, source, oldState=old or "", newState=new or "")
		_release(vmID, event)

	def descriptionChange(vmID, event, source, old, new):
		_queue("descriptionChange", vmID, source)
		_release(vmID, event)

	def caretChange(vmID, event, source, old, new):
		_queue("caret", vmID, source)
		_release(vmID, event)

	def descendentChange(vmID, event, source, oldDesc, newDesc):
		if newDesc:
			_queue("activeDescendantChange", vmID, newDesc)
		_release(vmID, event, source, oldDesc)

	def textChange(vmID, event, source):
		_queue("textChange", vmID, source)
		_release(vmID, event)

	pairs = (
		("setFocusGainedFP", FocusGainedFP(focusGained)),
		("setCaretUpdateFP", CaretUpdateFP(caretUpdate)),
		("setPropertyNameChangeFP", PropertyStringChangeFP(nameChange)),
		("setPropertyValueChangeFP", PropertyStringChangeFP(valueChange)),
		("setPropertyStateChangeFP", PropertyStringChangeFP(stateChange)),
		("setPropertyDescriptionChangeFP", PropertyStringChangeFP(descriptionChange)),
		("setPropertyCaretChangeFP", PropertyCaretChangeFP(caretChange)),
		("setPropertyActiveDescendentChangeFP", PropertyDescendentChangeFP(descendentChange)),
		("setPropertyTextChangeFP", PropertyChangeFP(textChange)),
	)
	for name, cb in pairs:
		_callbacks.append(cb)
		try:
			getattr(dll, name)(cb)
		except (OSError, AttributeError):
			log.debug("No se pudo registrar %s", name, exc_info=True)


def _dispatch(eventName: str, vmID: int, source: int, kwargs: dict) -> None:
	from .. import api
	from ..events import executeEvent
	from ..objects.jab import JABObject

	obj = JABObject.fromContext(vmID, source)
	if obj is None:
		return
	try:
		hwnd = obj.windowHandle
		root = ctypes.windll.user32.GetAncestor(hwnd, 2) if hwnd else 0
		fg = ctypes.windll.user32.GetForegroundWindow()
		# #14344: solo eventos de la ventana Java en primer plano.
		if root and fg and root != fg:
			return
	except Exception:
		pass
	if eventName == "activeDescendantChange":
		focus = api.getFocusObject()
		if isinstance(focus, JABObject):
			eventName = "gainFocus"
		else:
			return
	if eventName == "gainFocus":
		focus = api.getFocusObject()
		if focus is not None and obj == focus:
			return
	elif eventName in ("nameChange", "valueChange", "descriptionChange", "caret", "textChange"):
		focus = api.getFocusObject()
		if focus is None or obj != focus:
			if eventName != "valueChange":
				return
	executeEvent(eventName, obj)
