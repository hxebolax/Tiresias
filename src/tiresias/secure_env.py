"""Entorno de ejecución sensible: cuenta SYSTEM, escritorio seguro y elevación.

- :func:`mustForceSecureMode`: Tiresias corre como SYSTEM o en un escritorio
  que no es el del usuario («Winlogon»: inicio de sesión, UAC, Control+Alt+Supr).
  Entonces se fuerza el modo seguro (configuración del sistema, de solo
  lectura, sin complementos ni funciones que den acceso al sistema), como hace
  NVDA en ``nvda.pyw`` con ``isRunningOnSecureDesktop``.
- :func:`isTrustedDir`: carpetas que un usuario sin privilegios no puede
  escribir (Archivos de programa y Windows). Sirve para no cargar bibliotecas
  ni ejecutar programas de carpetas que un atacante podría preparar.
- :func:`installSecureModeGuards`: en modo seguro, ``os.startfile`` y los
  cuadros de abrir o guardar archivos de wx quedan bloqueados en todo el
  proceso (también en los complementos), porque abren el Explorador, el
  navegador o el programa asociado con la cuenta con la que corre Tiresias.
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

from .log import getLogger

log = getLogger("secureEnv")

#: SID de la cuenta LocalSystem.
SYSTEM_SID = "S-1-5-18"
TOKEN_QUERY = 0x0008
TokenUser = 1
UOI_NAME = 2


def _advapi():
	adv = ctypes.WinDLL("advapi32", use_last_error=True)
	adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
	adv.OpenProcessToken.restype = wintypes.BOOL
	adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
	adv.GetTokenInformation.restype = wintypes.BOOL
	adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
	adv.ConvertSidToStringSidW.restype = wintypes.BOOL
	return adv


def processUserSid() -> str:
	"""SID (texto) del usuario del proceso actual; ``""`` si no se puede saber."""
	if sys.platform != "win32":
		return ""
	try:
		adv = _advapi()
		k32 = ctypes.WinDLL("kernel32", use_last_error=True)
		k32.GetCurrentProcess.restype = wintypes.HANDLE
		k32.CloseHandle.argtypes = [wintypes.HANDLE]
		k32.LocalFree.argtypes = [ctypes.c_void_p]
		token = wintypes.HANDLE()
		if not adv.OpenProcessToken(k32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
			return ""
		try:
			size = wintypes.DWORD(0)
			adv.GetTokenInformation(token, TokenUser, None, 0, ctypes.byref(size))
			if not size.value:
				return ""
			buf = ctypes.create_string_buffer(size.value)
			if not adv.GetTokenInformation(token, TokenUser, buf, size, ctypes.byref(size)):
				return ""
			psid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
			text = wintypes.LPWSTR()
			if not adv.ConvertSidToStringSidW(psid, ctypes.byref(text)):
				return ""
			try:
				return text.value or ""
			finally:
				k32.LocalFree(text)
		finally:
			k32.CloseHandle(token)
	except Exception:
		log.debug("No se pudo leer el usuario del proceso", exc_info=True)
		return ""


def isSystemAccount() -> bool:
	return processUserSid() == SYSTEM_SID


def threadDesktopName() -> str:
	"""Nombre del escritorio del hilo actual (``Default``, ``Winlogon``...)."""
	if sys.platform != "win32":
		return ""
	try:
		u32 = ctypes.WinDLL("user32", use_last_error=True)
		k32 = ctypes.WinDLL("kernel32")
		u32.GetThreadDesktop.argtypes = [wintypes.DWORD]
		u32.GetThreadDesktop.restype = wintypes.HANDLE
		u32.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
		u32.GetUserObjectInformationW.restype = wintypes.BOOL
		h = u32.GetThreadDesktop(k32.GetCurrentThreadId())
		if not h:
			return ""
		buf = ctypes.create_unicode_buffer(256)
		needed = wintypes.DWORD(0)
		if not u32.GetUserObjectInformationW(h, UOI_NAME, buf, ctypes.sizeof(buf), ctypes.byref(needed)):
			return ""
		# El manejador de GetThreadDesktop no se cierra (no es propio).
		return buf.value
	except Exception:
		log.debug("No se pudo leer el escritorio del hilo", exc_info=True)
		return ""


def mustForceSecureMode(sid: str | None = None, desktop: str | None = None) -> bool:
	"""``True`` si hay que forzar el modo seguro: cuenta SYSTEM o escritorio que no es «Default»."""
	sid = processUserSid() if sid is None else sid
	desktop = threadDesktopName() if desktop is None else desktop
	if sid == SYSTEM_SID:
		return True
	return bool(desktop) and desktop.lower() != "default"


def isElevated() -> bool:
	try:
		return bool(ctypes.windll.shell32.IsUserAnAdmin())
	except Exception:
		return False


def trustedRoots() -> list[str]:
	"""Carpetas protegidas: Archivos de programa (64 y 32 bits) y Windows."""
	roots = []
	for var in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)", "SystemRoot"):
		v = os.environ.get(var)
		if v:
			roots.append(v)
	if not roots:
		roots = [r"C:\Program Files", r"C:\Program Files (x86)", r"C:\Windows"]
	return roots


def _norm(path: str) -> str:
	try:
		path = os.path.realpath(path)
	except (OSError, ValueError):
		path = os.path.abspath(path)
	return os.path.normcase(path).rstrip("\\/")


def isTrustedDir(path: str, roots: list[str] | None = None) -> bool:
	"""``True`` si ``path`` está dentro de una carpeta protegida (sin seguir trucos de ``..``)."""
	if not path:
		return False
	p = _norm(path)
	for root in roots if roots is not None else trustedRoots():
		r = _norm(root)
		if r and (p == r or p.startswith(r + os.sep)):
			return True
	return False


# ------------------------------------------------------------------ guardas del modo seguro
_startfileGuarded = False
_wxGuarded = False


def _blockedMessage() -> str:
	try:
		from .config import policy

		return policy.blockedMessage()
	except Exception:
		return "Esta función no está disponible en modo seguro."


def _announceBlocked() -> None:
	try:
		from . import queue_handler, speech

		queue_handler.queueFunction(speech.speakMessage, _blockedMessage())
	except Exception:
		pass


def guardedStartfile(original):
	"""``os.startfile`` que se niega en modo seguro (o si la política lo bloquea)."""

	def startfile(*args, **kwargs):
		from .config import policy

		if not policy.isAllowed("openFiles"):
			log.warning("Bloqueado en modo seguro: abrir %r", args[0] if args else "")
			_announceBlocked()
			raise OSError(_blockedMessage())
		return original(*args, **kwargs)

	startfile._tiresiasGuarded = True  # type: ignore[attr-defined]
	return startfile


def _guardedDialogClass(base):
	class Guarded(base):  # type: ignore[misc, valid-type]
		def ShowModal(self) -> int:  # noqa: N802 - API de wx
			from .config import policy

			if not policy.isAllowed("fileDialogs"):
				log.warning("Bloqueado en modo seguro: %s", base.__name__)
				_announceBlocked()
				import wx

				return wx.ID_CANCEL
			return super().ShowModal()

	Guarded.__name__ = base.__name__
	Guarded.__qualname__ = base.__qualname__
	Guarded._tiresiasGuarded = True
	return Guarded


def installSecureModeGuards() -> None:
	"""Bloquea ``os.startfile`` y los cuadros de archivos de wx en todo el proceso.

	wx no se importa aquí (el orden de importación de comtypes y wx decide el
	apartamento COM de cada hilo): si aún no está cargado, sus cuadros se
	protegen al volver a llamar a esta función tras crear la interfaz
	(``lock_guard.startMonitor``).
	"""
	global _startfileGuarded, _wxGuarded
	if not _startfileGuarded:
		_startfileGuarded = True
		if hasattr(os, "startfile") and not getattr(os.startfile, "_tiresiasGuarded", False):
			os.startfile = guardedStartfile(os.startfile)
		log.info("Modo seguro: bloqueado abrir archivos, carpetas y direcciones")
	wx = sys.modules.get("wx")
	if wx is not None and not _wxGuarded:
		_wxGuarded = True
		for name in ("FileDialog", "DirDialog"):
			cls = getattr(wx, name, None)
			if cls is not None and not getattr(cls, "_tiresiasGuarded", False):
				setattr(wx, name, _guardedDialogClass(cls))
		log.info("Modo seguro: bloqueados los cuadros de abrir y guardar archivos")
