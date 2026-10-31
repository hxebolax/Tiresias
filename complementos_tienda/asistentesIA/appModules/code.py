"""Antigravity y los editores basados en Visual Studio Code.

Conserva todo lo del módulo ``code`` de Tiresias y añade las órdenes de los
asistentes para el panel de agente de Antigravity. En un editor sin ese panel
las órdenes avisan de que no hay conversación.
"""

from __future__ import annotations

from tiresias.a11y import uia_client as uc
from tiresias.appmodules.code import AppModule as CodeAppModule

from tiresias.i18n import _
from tiresias.log import getLogger

from . import ia_motor as M

log = getLogger("asistentesIA")

#: Iconos de la cabecera del panel de agente, en orden.
ICONOS = (_("Nueva conversación"), _("Conversaciones anteriores"), _("Más opciones"), _("Cerrar el panel del agente"))


class AppModule(CodeAppModule, M.AsistenteAppModule):
	nombreAsistente = "Antigravity"

	def __init__(self, processID: int, appName: str | None = None) -> None:
		super().__init__(processID, appName)
		self._iniciarAsistente()

	def event_NVDAObject_init(self, obj) -> None:
		super().event_NVDAObject_init(obj)
		if not (self.appName or "").lower().startswith("antigravity"):
			return
		try:
			if getattr(obj, "UIAControlType", 0) in (uc.CT_HYPERLINK, uc.CT_BUTTON) and not obj.name:
				nombre = self._nombreIcono(obj)
				if nombre:
					obj.name = nombre
		except Exception:
			log.debug("No se pudo nombrar el icono", exc_info=True)

	def _nombreIcono(self, obj) -> str:
		"""Nombre de un icono de la cabecera del panel de agente (no publican ninguno).

		Sus textos solo existen como descripciones emergentes del ratón. Son
		hermanos de la conversación y siempre van en el mismo orden.
		"""
		cls = str(getattr(obj, "UIAClassName", "") or "")
		if not cls.startswith(("group relative", "popover-trigger")):
			return ""
		walker = uc.client.ControlViewWalker
		padre = walker.GetParentElement(obj.element)
		if padre is None:
			return ""
		if "popover-trigger" in str(padre.CurrentClassName or ""):
			return ICONOS[2]
		iconos = 0
		propio = None
		hijo = walker.GetFirstChildElement(padre)
		conversacion = False
		while hijo is not None:
			if str(hijo.CurrentAutomationId or "") == "conversation":
				conversacion = True
				break
			if hijo.CurrentControlType in (uc.CT_HYPERLINK, uc.CT_BUTTON):
				if uc.compareElements(hijo, obj.element):
					propio = iconos
				iconos += 1
			hijo = walker.GetNextSiblingElement(hijo)
		return ICONOS[propio] if conversacion and propio is not None and propio < len(ICONOS) else ""

	def buscarConversacion(self, raiz):
		return self._buscar(raiz, uc.P_AUTOMATIONID, "conversation")

	def analizar(self, nodo: M.Nodo) -> list[M.Mensaje]:
		return M.mensajesAntigravity(nodo)

	def buscarEntrada(self, raiz):
		conv = self.buscarConversacion(raiz)
		if conv is None:
			return None
		return self._buscar(conv, uc.P_ARIAROLE, "combobox")
