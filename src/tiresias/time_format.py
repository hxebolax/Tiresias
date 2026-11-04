"""Formato de la hora que dice Tiresias (orden de la hora, braille).

``general.timeFormat`` elige el formato:

- ``"system"``: el mismo que el reloj de Windows (formato corto del usuario,
  sin segundos), con ``GetTimeFormatEx``. Si Windows usa 12 horas, Tiresias
  también («3:45 p. m.»).
- ``"24"``: siempre 24 horas («15:45»).
- ``"12"``: siempre 12 horas con a. m. y p. m. («3:45 p. m.»).
"""

from __future__ import annotations

import ctypes
import datetime
from ctypes import wintypes

from .i18n import _
from .log import getLogger

log = getLogger("timeFormat")

MODES = ("system", "24", "12")

_TIME_NOSECONDS = 0x2
_LOCALE_S1159 = 0x28  # designador de la mañana (a. m.)
_LOCALE_S2359 = 0x29  # designador de la tarde (p. m.)


class _SYSTEMTIME(ctypes.Structure):
	_fields_ = [
		("wYear", wintypes.WORD),
		("wMonth", wintypes.WORD),
		("wDayOfWeek", wintypes.WORD),
		("wDay", wintypes.WORD),
		("wHour", wintypes.WORD),
		("wMinute", wintypes.WORD),
		("wSecond", wintypes.WORD),
		("wMilliseconds", wintypes.WORD),
	]


def _systemTime(now: datetime.datetime) -> _SYSTEMTIME:
	return _SYSTEMTIME(now.year, now.month, (now.weekday() + 1) % 7, now.day, now.hour, now.minute, now.second, 0)


def _windowsTime(now: datetime.datetime) -> str:
	"""Hora con el formato corto de Windows del usuario; "" si falla."""
	try:
		buf = ctypes.create_unicode_buffer(80)
		st = _systemTime(now)
		if ctypes.windll.kernel32.GetTimeFormatEx(None, _TIME_NOSECONDS, ctypes.byref(st), None, buf, len(buf)):
			return buf.value.strip()
	except Exception:
		log.debug("GetTimeFormatEx falló", exc_info=True)
	return ""


def _localeString(lctype: int) -> str:
	try:
		buf = ctypes.create_unicode_buffer(32)
		if ctypes.windll.kernel32.GetLocaleInfoEx(None, lctype, buf, len(buf)):
			return buf.value.strip()
	except Exception:
		log.debug("GetLocaleInfoEx falló", exc_info=True)
	return ""


def designators() -> tuple[str, str]:
	"""Designadores de mañana y tarde de Windows («a. m.», «p. m.»)."""
	return (_localeString(_LOCALE_S1159) or _("a. m."), _localeString(_LOCALE_S2359) or _("p. m."))


def currentMode() -> str:
	try:
		from .config import conf

		mode = str(conf["general"].get("timeFormat", "system"))
	except Exception:
		mode = "system"
	return mode if mode in MODES else "system"


def formatTime(now: datetime.datetime | None = None, mode: str | None = None) -> str:
	"""La hora (sin segundos) en el formato elegido."""
	now = now or datetime.datetime.now()
	mode = mode or currentMode()
	if mode == "system":
		text = _windowsTime(now)
		if text:
			return text
		mode = "24"
	if mode == "12":
		am, pm = designators()
		hour = now.hour % 12 or 12
		return f"{hour}:{now.minute:02d} {am if now.hour < 12 else pm}"
	return now.strftime("%H:%M")
