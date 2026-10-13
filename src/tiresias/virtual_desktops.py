"""Anuncio del nombre del escritorio virtual al cambiar de escritorio.

Como NVDA desde la 2023.2 (``eventHandler.handlePossibleDesktopNameChange``):
en Windows 10 1903 y posteriores, al cambiar de escritorio virtual
(Control+Windows+Flecha izquierda o derecha), al crear uno (Control+Windows+D)
y al cerrarlo (Control+Windows+F4), Windows cambia el nombre de la ventana del
escritorio (clase ``#32769``) y avisa con ``EVENT_OBJECT_NAMECHANGE``.

- En el hilo de los ganchos (:mod:`tiresias.a11y.winevents`) solo se compara la
  ventana con la del escritorio y se lee su título guardado
  (``InternalGetWindowText``, sin mensajes a otro proceso); el resto, aquí, en
  el hilo del núcleo.
- Como NVDA, se espera 250 ms (llegan varios eventos por cambio) y se dice el
  último nombre. Si el título está vacío, el nombre sale del registro
  (``HKCU\\...\\Explorer\\VirtualDesktops``: ``CurrentVirtualDesktop`` y
  ``Desktops\\{GUID}\\Name``); un escritorio sin nombre es «Escritorio N»,
  como lo llama Windows.
- El mismo nombre no se repite si llega otra vez enseguida.

NVDA no tiene opción para desactivarlo; Tiresias tampoco.
"""

from __future__ import annotations

import ctypes
import sys
import time
import uuid
import winreg
from ctypes import wintypes

from .i18n import _
from .log import getLogger

log = getLogger("virtualDesktops")

#: Espera antes de anunciar (milisegundos), como NVDA.
ANNOUNCE_DELAY_MS = 250
#: Segundos en los que el mismo nombre no se vuelve a anunciar.
REPEAT_WINDOW = 1.0
#: Windows 10 1903: desde aquí el escritorio cambia de nombre (como NVDA).
MIN_BUILD = 18362

VIRTUAL_DESKTOPS_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\VirtualDesktops"

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetDesktopWindow.restype = wintypes.HWND
_user32.InternalGetWindowText.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.InternalGetWindowText.restype = ctypes.c_int

_desktopHwnd = 0


def desktopWindow() -> int:
	"""Ventana del escritorio (``#32769``), leída una vez."""
	global _desktopHwnd
	if not _desktopHwnd:
		try:
			_desktopHwnd = int(_user32.GetDesktopWindow() or 0)
		except Exception:
			_desktopHwnd = 0
	return _desktopHwnd


def isSupported() -> bool:
	try:
		return sys.getwindowsversion().build >= MIN_BUILD
	except Exception:
		return False


_SUPPORTED = isSupported()


def isDesktopNameChange(hwnd: int) -> bool:
	"""(Hilo de los ganchos) ``True`` si el evento de nombre es del escritorio."""
	return _SUPPORTED and bool(hwnd) and hwnd == desktopWindow()


def readDesktopTitle(hwnd: int) -> str:
	"""Título guardado de la ventana del escritorio (sin enviar mensajes)."""
	buf = ctypes.create_unicode_buffer(260)
	try:
		_user32.InternalGetWindowText(hwnd, buf, 260)
	except Exception:
		return ""
	return buf.value.strip()


# ====================================================================== registro
def parseGuids(blob: bytes | None) -> list[uuid.UUID]:
	"""Lista de GUID de ``VirtualDesktopIDs`` (16 bytes cada uno)."""
	if not blob:
		return []
	data = bytes(blob)
	return [uuid.UUID(bytes_le=data[i : i + 16]) for i in range(0, len(data) - 15, 16)]


def desktopName(current: uuid.UUID | None, ids: list[uuid.UUID], names: dict[uuid.UUID, str]) -> str:
	"""Nombre del escritorio ``current``: el suyo o «Escritorio N»."""
	if current is None:
		return ""
	name = (names.get(current) or "").strip()
	if name:
		return name
	if current in ids:
		return _("Escritorio {n}").format(n=ids.index(current) + 1)
	return ""


def _guidKey(g: uuid.UUID) -> str:
	return "{" + str(g).upper() + "}"


def registryDesktopName() -> str:
	"""Nombre del escritorio actual según el registro (``""`` si no se sabe)."""
	try:
		with winreg.OpenKey(winreg.HKEY_CURRENT_USER, VIRTUAL_DESKTOPS_KEY) as k:
			try:
				ids = parseGuids(winreg.QueryValueEx(k, "VirtualDesktopIDs")[0])
			except OSError:
				ids = []
			try:
				cur = parseGuids(winreg.QueryValueEx(k, "CurrentVirtualDesktop")[0])
			except OSError:
				cur = []
	except OSError:
		return ""
	current = cur[0] if cur else None
	if current is None:
		return ""
	names: dict[uuid.UUID, str] = {}
	try:
		with winreg.OpenKey(winreg.HKEY_CURRENT_USER, VIRTUAL_DESKTOPS_KEY + "\\Desktops\\" + _guidKey(current)) as k:
			value = winreg.QueryValueEx(k, "Name")[0]
			if isinstance(value, str):
				names[current] = value
	except OSError:
		pass
	return desktopName(current, ids, names)


# ====================================================================== núcleo
_pendingName = ""
_timer: int | None = None
_lastAnnounced: tuple[str, float] = ("", 0.0)
#: Último evento que traía el nombre en el título.
_lastTitleTime = 0.0
#: Segundos tras un evento con nombre en los que un título vacío se toma como
#: la vuelta del título a su valor normal (del mismo cambio), no otro cambio.
EMPTY_AFTER_TITLE = 3.0


def onNameChange(title: str) -> None:
	"""(Hilo del núcleo) La ventana del escritorio cambió de nombre."""
	global _pendingName, _timer, _lastTitleTime
	from . import queue_handler

	now = time.monotonic()
	if title:
		_pendingName = title
		_lastTitleTime = now
	elif _lastTitleTime and now - _lastTitleTime < EMPTY_AFTER_TITLE:
		return
	if _timer is not None:
		queue_handler.cancelCallLater(_timer)
	_timer = queue_handler.callLater(ANNOUNCE_DELAY_MS, _announce)


def _announce() -> None:
	global _pendingName, _timer, _lastAnnounced
	_timer = None
	name, _pendingName = _pendingName, ""
	if not name:
		try:
			name = registryDesktopName()
		except Exception:
			log.debug("No se pudo leer el escritorio virtual del registro", exc_info=True)
			name = ""
	if not name:
		return
	now = time.monotonic()
	lastName, lastTime = _lastAnnounced
	if name == lastName and now - lastTime < REPEAT_WINDOW:
		return
	_lastAnnounced = (name, now)
	from . import speech

	speech.speakMessage(name)
