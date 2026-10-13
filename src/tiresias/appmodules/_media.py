"""Base común de los reproductores (Spotify, foobar2000, Winamp).

Anuncia la canción nueva cuando cambia el título de la ventana principal
(opción «Anunciar los cambios de canción» del panel Aplicaciones), aunque el
reproductor esté en segundo plano. Las subclases indican cómo sacar la
canción del título con :meth:`MediaAppModule.trackFromTitle`.
"""

from __future__ import annotations

import re

from .. import queue_handler, speech, winapi
from ..config import conf
from ..i18n import _
from ..log import getLogger
from . import AppModule as BaseAppModule

log = getLogger("mediaApps")

POLL_MS = 1000


def formatSeconds(seconds: float) -> str:
	seconds = max(0, int(seconds))
	h, rem = divmod(seconds, 3600)
	m, s = divmod(rem, 60)
	return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def parseTime(text: str) -> int | None:
	"""``1:23`` → 83; ``1:02:03`` → 3723."""
	parts = text.strip().split(":")
	try:
		nums = [int(p) for p in parts]
	except ValueError:
		return None
	total = 0
	for n in nums:
		total = total * 60 + n
	return total


_TIME_PAIR = re.compile(r"(\d+(?::\d{2}){1,2})\s*/\s*(\d+(?::\d{2}){1,2})")


def parseElapsedTotal(text: str) -> tuple[int, int] | None:
	"""Busca «transcurrido / total» en un texto (barra de estado)."""
	m = _TIME_PAIR.search(text or "")
	if not m:
		return None
	a, b = parseTime(m.group(1)), parseTime(m.group(2))
	if a is None or b is None:
		return None
	return a, b


class MediaAppModule(BaseAppModule):
	#: Clase de la ventana principal (``None``: la primera ventana visible con título).
	mainWindowClass: str | None = None

	def __init__(self, processID: int, appName: str | None = None) -> None:
		super().__init__(processID, appName)
		self._lastTrack: str | None = None
		self._timer: int | None = None
		try:
			self._timer = queue_handler.callLater(POLL_MS, self._poll)
		except Exception:
			log.debug("No se pudo programar la vigilancia del reproductor", exc_info=True)

	def terminate(self) -> None:
		if self._timer is not None:
			queue_handler.cancelCallLater(self._timer)
			self._timer = None

	def trackFromTitle(self, title: str) -> str | None:
		"""Canción a partir del título; ``None`` si no se está reproduciendo."""
		return title or None

	def mainWindow(self) -> int:
		found: list[int] = []
		pid = self.processID
		cls = self.mainWindowClass

		def enum(hwnd, lParam):
			if winapi.getWindowProcessId(hwnd) != pid:
				return True
			if cls is not None:
				if winapi.getClassName(hwnd) == cls:
					found.append(hwnd)
					return False
			elif winapi.user32.IsWindowVisible(hwnd) and winapi.getWindowText(hwnd):
				found.append(hwnd)
				return False
			return True

		winapi.user32.EnumWindows(winapi.WNDENUMPROC(enum), 0)
		return found[0] if found else 0

	def checkTrack(self, title: str) -> str | None:
		"""Compara el título con la canción anterior; devuelve la canción nueva o ``None``."""
		track = self.trackFromTitle(title)
		if track and track != self._lastTrack:
			first = self._lastTrack is None
			self._lastTrack = track
			return None if first else track
		return None

	def _poll(self) -> None:
		self._timer = None
		if not self.isAlive:
			return
		try:
			if conf["media"]["announceTrackChanges"] and not self.sleepMode:
				hwnd = self.mainWindow()
				new = self.checkTrack(winapi.getWindowText(hwnd) if hwnd else "")
				if new:
					speech.speakMessage(new)
		except Exception:
			log.debug("Error vigilando el reproductor", exc_info=True)
		self._timer = queue_handler.callLater(POLL_MS, self._poll)

	def speakTimes(self, which: str, elapsed: int | None, total: int | None) -> None:
		if elapsed is None or total is None:
			speech.speakMessage(_("No se pudo obtener el tiempo de reproducción"))
			return
		if which == "elapsed":
			speech.speakMessage(_("{t} transcurrido").format(t=formatSeconds(elapsed)))
		elif which == "remaining":
			speech.speakMessage(_("{t} restante").format(t=formatSeconds(total - elapsed)))
		else:
			speech.speakMessage(_("{t} en total").format(t=formatSeconds(total)))
