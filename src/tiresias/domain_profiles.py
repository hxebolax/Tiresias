"""Perfiles de configuración por dominio web.

Un perfil puede tener disparadores ``dominio:ejemplo.com``. Cuando el foco
está en un documento web cuya dirección es de ese dominio (o de un
subdominio: ``correo.ejemplo.com`` también cuenta), el perfil se activa; al
salir del dominio o del navegador, se desactiva.

La dirección se obtiene por UI Automation: los navegadores (Chrome, Edge,
Firefox y los que usan Chromium) exponen la URL como valor (``ValuePattern``)
del elemento documento, que es el objeto raíz del modo exploración.
"""

from __future__ import annotations

from typing import Any

from .config import DOMAIN_TRIGGER_PREFIX, conf, domainFromUrl
from .log import getLogger
from .plugins import GlobalPlugin as _Base

log = getLogger("domainProfiles")

#: Dominio del documento con el foco (aunque no tenga perfil); lo usa el diálogo de perfiles.
currentDomain: str | None = None


def documentUrl(obj: Any) -> str:
	"""Dirección del documento web que contiene ``obj`` ("" si no hay)."""
	from .a11y import uia_client as uc

	ti = getattr(obj, "treeInterceptor", None)
	root = getattr(ti, "rootObject", None) if ti is not None else None
	if root is None:
		return ""
	try:
		value = root._prop(uc.P_VALUEVALUE, "") if hasattr(root, "_prop") else getattr(root, "value", "")
	except Exception:
		return ""
	return str(value or "")


class GlobalPlugin(_Base):
	def __init__(self) -> None:
		super().__init__()
		#: Disparador de dominio activo ahora.
		self._active: str | None = None
		self._pid = 0

	def terminate(self) -> None:
		self._setTrigger(None)

	def _hasDomainTriggers(self) -> bool:
		return any(t.startswith(DOMAIN_TRIGGER_PREFIX) for t in conf.triggers)

	def _setTrigger(self, trigger: str | None) -> None:
		if trigger == self._active:
			return
		if self._active:
			conf.exitTrigger(self._active)
		self._active = trigger
		if trigger:
			log.debug("Perfil por dominio: %s", trigger)
			conf.enterTrigger(trigger)

	def update(self, obj: Any) -> None:
		global currentDomain
		if obj is None:
			return
		try:
			pid = obj.processID
		except Exception:
			pid = 0
		url = documentUrl(obj)
		domain = domainFromUrl(url) if url else None
		if domain is None:
			if pid and pid == self._pid and currentDomain:
				# Barra de direcciones, menús del navegador...: se mantiene el dominio.
				domain = currentDomain
			else:
				currentDomain = None
				self._pid = pid
				self._setTrigger(None)
				return
		currentDomain = domain
		self._pid = pid
		if not self._hasDomainTriggers():
			self._setTrigger(None)
			return
		self._setTrigger(conf.findDomainTrigger(domain))

	def event_gainFocus(self, obj: Any, nextHandler, **kwargs) -> None:
		try:
			self.update(obj)
		except Exception:
			log.debug("No se pudo comprobar el dominio", exc_info=True)
		nextHandler()

	def event_documentLoadComplete(self, obj: Any, nextHandler, **kwargs) -> None:
		# La pestaña ha navegado a otra página (quizá de otro dominio).
		try:
			from . import api

			self.update(api.getFocusObject())
		except Exception:
			log.debug("No se pudo comprobar el dominio", exc_info=True)
		nextHandler()
