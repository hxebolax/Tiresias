"""Notificaciones emergentes de Windows (toasts) y centro de actividades."""

from __future__ import annotations

import time

from .. import speech
from ..config import conf
from . import AppModule as BaseAppModule

_lastToast = ("", 0.0)


class AppModule(BaseAppModule):
	def event_windowOpened(self, obj, nextHandler) -> None:
		global _lastToast
		from ..objects.behaviors import Toast

		if not conf["presentation"]["reportNotifications"] or isinstance(obj, Toast):
			# Las notificaciones emergentes (Toast) se leen en el propio objeto.
			return nextHandler()
		try:
			texts = [c.name for c in obj.children if c.name] if not obj.name or len(obj.name) < 3 else []
			text = " ".join([obj.name] + texts).strip()
		except Exception:
			# Rev. 10.11: el nombre puede fallar igual que los hijos (objeto ya cerrado).
			try:
				text = obj.name or ""
			except Exception:
				text = ""
		now = time.monotonic()
		if text and not (text == _lastToast[0] and now - _lastToast[1] < 2):
			_lastToast = (text, now)
			speech.speak([text], origin=speech.ORIGIN_NOTIFICATION)
		nextHandler()

	def event_liveRegionChange(self, obj, nextHandler) -> None:
		nextHandler()
