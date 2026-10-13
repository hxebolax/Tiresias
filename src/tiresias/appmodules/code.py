"""Visual Studio Code y editores basados en él (Cursor, VSCodium, Windsurf...).

- El banco de trabajo (la ventana completa) no usa el modo exploración: el
  editor, los paneles y las listas se manejan en modo foco y el editor nunca
  entra en modo exploración por error. Las vistas web (vista previa de
  Markdown, detalles de extensiones...) sí lo usan, porque son documentos
  propios dentro del banco de trabajo.
- Las notificaciones (avisos de VS Code) se leen una sola vez.
- Tiresias+Fin lee la barra de estado (línea, columna, rama, errores...).
"""

from __future__ import annotations

import time

from .. import api, speech
from ..a11y import uia_client as uc
from ..config import conf
from ..objects.base import AccObject
from ..objects.roles import Role
from . import AppModule as BaseAppModule


class Workbench(AccObject):
	"""Documento raíz del banco de trabajo: sin modo exploración."""

	shouldCreateTreeInterceptor = False


def isWorkbenchDocument(obj) -> bool:
	"""El documento más externo de la ventana (no una vista web interior)."""
	try:
		if obj.role != Role.DOCUMENT:
			return False
		parent = obj.parent
		guard = 0
		while parent is not None and guard < 25:
			if parent.role == Role.DOCUMENT:
				return False
			if parent.role in (Role.WINDOW, Role.DESKTOPPANE):
				break
			parent = parent.parent
			guard += 1
		return True
	except Exception:
		return False


class AppModule(BaseAppModule):
	def __init__(self, processID: int, appName: str | None = None) -> None:
		super().__init__(processID, appName)
		self._lastAlert = ("", 0.0)
		#: RuntimeId de documento -> si es el banco de trabajo (evita recorrer antecesores).
		self._workbenchCache: dict[tuple, bool] = {}

	def chooseObjectClass(self, obj, clsList: list[type]) -> None:
		try:
			if obj.role != Role.DOCUMENT or getattr(obj, "UIAFrameworkId", "") != "Chrome":
				return
			rid = obj.runtimeId
		except Exception:
			return
		isWb = self._workbenchCache.get(rid)
		if isWb is None:
			isWb = isWorkbenchDocument(obj)
			if len(self._workbenchCache) > 500:
				self._workbenchCache.clear()
			self._workbenchCache[rid] = isWb
		if isWb:
			clsList.insert(0, Workbench)

	def _speakOnce(self, text: str) -> None:
		text = " ".join((text or "").split())
		now = time.monotonic()
		if not text or (text == self._lastAlert[0] and now - self._lastAlert[1] < 2.0):
			return
		self._lastAlert = (text, now)
		speech.speakText(text)

	def event_liveRegionChange(self, obj, nextHandler) -> None:
		# VS Code anuncia notificaciones y resultados con regiones vivas
		# (a veces por duplicado: alerta + estado).
		if not conf["presentation"]["reportDynamicContentChanges"]:
			return
		try:
			text = obj.name or obj.value
		except Exception:
			text = ""
		self._speakOnce(text)

	def event_alert(self, obj, nextHandler) -> None:
		try:
			text = obj.name or " ".join(c.name for c in obj.children if c.name)
		except Exception:
			text = ""
		self._speakOnce(text)

	def getStatusBar(self):
		fg = api.getForegroundObject()
		if fg is None or not hasattr(fg, "element"):
			return None
		from ..objects.uia import UIAObject

		try:
			cond = uc.createPropertyCondition(uc.P_AUTOMATIONID, "workbench.parts.statusbar")
			el = fg.element.FindFirstBuildCache(uc.TreeScope_Descendants, cond, uc.baseCacheRequest)
			if el:
				return UIAObject.fromElement(el)
		except Exception:
			pass
		return None
