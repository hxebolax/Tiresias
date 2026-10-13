"""Calculadora de Windows 10 y 11 (``CalculatorApp.exe``, alias ``calculator``).

- No repite el número de la pantalla mientras se escribe: ya lo dice el eco
  de teclado. Sí lee el resultado al pulsar Intro, = o un operador, y los
  avisos de cambio de modo y de memoria.
- Tiresias+Fin (leer la barra de estado) dice el modo de cálculo actual
  (NVDA #20222), la expresión y la pantalla.
"""

from __future__ import annotations

import time

from .. import api, speech
from ..a11y import uia_client as uc
from ..config import conf
from ..log import getLogger
from . import AppModule as BaseAppModule

log = getLogger("calculator")

#: Teclas cuyo eco ya dice lo que muestra la pantalla.
_ECHOED = set("0123456789,.")
#: Tiempo durante el que se considera que la pantalla cambió por lo escrito.
ECHO_WINDOW = 0.6


class AppModule(BaseAppModule):
	def __init__(self, processID: int, appName: str | None = None) -> None:
		super().__init__(processID, appName)
		self._lastTyped = ("", 0.0)
		self._lastSpoken = ("", 0.0)

	def event_typedCharacter(self, obj, nextHandler, ch: str = "", **kwargs) -> None:
		self._lastTyped = (ch, time.monotonic())
		nextHandler()

	def shouldSpeakDisplay(self, displayString: str, now: float | None = None) -> bool:
		"""Si se debe leer una actualización de la pantalla."""
		now = time.monotonic() if now is None else now
		ch, t = self._lastTyped
		if ch and ch in _ECHOED and now - t < ECHO_WINDOW:
			return False
		if displayString == self._lastSpoken[0] and now - self._lastSpoken[1] < 1.0:
			return False
		return True

	def event_notification(self, obj, nextHandler, displayString: str = "", activityId: str = "", **kwargs) -> None:
		if not conf["presentation"]["reportNotifications"]:
			return
		if activityId == "DisplayUpdated" and not self.shouldSpeakDisplay(displayString):
			return
		self._lastSpoken = (displayString, time.monotonic())
		speech.speakText(displayString)

	def event_nameChange(self, obj, nextHandler) -> None:
		# La pantalla también cambia de nombre: la notificación ya lo dice.
		if getattr(obj, "UIAAutomationId", "") in ("CalculatorResults", "CalculatorExpression"):
			return
		nextHandler()

	def _texts(self) -> dict[str, str]:
		fg = api.getForegroundObject()
		out: dict[str, str] = {}
		if fg is None or not hasattr(fg, "element"):
			return out
		for aid in ("Header", "CalculatorExpression", "CalculatorResults"):
			try:
				cond = uc.createPropertyCondition(uc.P_AUTOMATIONID, aid)
				el = fg.element.FindFirstBuildCache(uc.TreeScope_Descendants, cond, uc.baseCacheRequest)
				if el:
					out[aid] = el.CachedName or ""
			except Exception:
				continue
		return out

	def getStatusBarText(self) -> str | None:
		t = self._texts()
		expr = t.get("CalculatorExpression", "").strip()
		if expr.endswith((" es", " is")):
			# Expresión vacía («La expresión es»).
			t["CalculatorExpression"] = ""
		parts = [t.get(k, "") for k in ("Header", "CalculatorExpression", "CalculatorResults")]
		parts = [p for p in parts if p and p.strip()]
		return ", ".join(parts) if parts else None
