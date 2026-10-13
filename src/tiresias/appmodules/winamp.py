"""Winamp.

Usa la interfaz de mensajes de Winamp (IPC) para:

- anunciar el estado de «aleatorio» (S) y «repetir» (R) al cambiarlo;
- decir el tiempo transcurrido, restante y total (Control+Mayúsculas+E, R, T);
- anunciar la canción nueva al cambiar (también en segundo plano).
"""

from __future__ import annotations

import ctypes
import re

from .. import queue_handler, speech, winapi
from ..baseobject import script
from ..i18n import _
from ._media import MediaAppModule

CAT = _("Winamp")

WM_USER = 0x0400
IPC_GETOUTPUTTIME = 105
IPC_GET_SHUFFLE = 250
IPC_GET_REPEAT = 251
SMTO_ABORTIFHUNG = 0x0002


def ipc(hwnd: int, msg: int, wParam: int = 0) -> int | None:
	"""Mensaje IPC a Winamp con tiempo máximo (no se cuelga si Winamp no responde)."""
	if not hwnd:
		return None
	result = winapi.ULONG_PTR()
	ok = winapi.user32.SendMessageTimeoutW(hwnd, WM_USER, wParam, msg, SMTO_ABORTIFHUNG, 500, ctypes.byref(result))
	if not ok:
		return None
	value = int(result.value)
	# Los valores negativos llegan como enteros sin signo.
	if value >= 1 << 63:
		value -= 1 << 64
	return value


_TITLE_SUFFIX = re.compile(r"\s*-\s*Winamp.*$")
_TITLE_NUMBER = re.compile(r"^\d+\.\s*")


class AppModule(MediaAppModule):
	scriptCategory = CAT
	mainWindowClass = "Winamp v1.x"

	def trackFromTitle(self, title: str) -> str | None:
		# «12. Artista - Título - Winamp» (y «[Detenido]» o «[En pausa]» al final).
		if not title or "[" in title.rsplit("Winamp", 1)[-1]:
			return None
		title = _TITLE_NUMBER.sub("", _TITLE_SUFFIX.sub("", title))
		return title or None

	def _toggleReport(self, gesture, msg: int, label: str) -> None:
		from .. import api

		gesture.send()
		focus = api.getFocusObject()
		try:
			cls = winapi.getClassName(focus.windowHandle) if focus is not None else ""
		except Exception:
			cls = ""
		if cls not in ("Winamp v1.x", "Winamp PE", "Winamp EQ", "BaseWindow_RootWnd"):
			# En un cuadro de texto de Winamp la letra solo se escribe.
			return

		def report() -> None:
			val = ipc(self.mainWindow(), msg)
			if val is None:
				return
			speech.speakMessage(_("{what} activado").format(what=label) if val else _("{what} desactivado").format(what=label))

		queue_handler.callLater(80, report)

	@script(description=_("Activa o desactiva el orden aleatorio y lo anuncia"), category=CAT, gesture="kb:s")
	def script_toggleShuffle(self, gesture) -> None:
		self._toggleReport(gesture, IPC_GET_SHUFFLE, _("aleatorio"))

	@script(description=_("Activa o desactiva la repetición y lo anuncia"), category=CAT, gesture="kb:r")
	def script_toggleRepeat(self, gesture) -> None:
		self._toggleReport(gesture, IPC_GET_REPEAT, _("repetir"))

	def _times(self) -> tuple[int | None, int | None]:
		hwnd = self.mainWindow()
		pos = ipc(hwnd, IPC_GETOUTPUTTIME, 0)
		length = ipc(hwnd, IPC_GETOUTPUTTIME, 1)
		if pos is None or length is None or pos < 0 or length <= 0:
			return None, None
		return pos // 1000, length

	@script(description=_("Tiempo transcurrido de la canción"), category=CAT, gesture="kb:control+shift+e", speakOnDemand=True)
	def script_elapsedTime(self, gesture) -> None:
		self.speakTimes("elapsed", *self._times())

	@script(description=_("Tiempo restante de la canción"), category=CAT, gesture="kb:control+shift+r", speakOnDemand=True)
	def script_remainingTime(self, gesture) -> None:
		self.speakTimes("remaining", *self._times())

	@script(description=_("Duración total de la canción"), category=CAT, gesture="kb:control+shift+t", speakOnDemand=True)
	def script_totalTime(self, gesture) -> None:
		self.speakTimes("total", *self._times())
