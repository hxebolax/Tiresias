"""Aplicación de escritorio de Claude (``claude.exe``).

La conversación es un ``role="feed"`` con un ``article`` por mensaje. Mientras
Claude trabaja, el feed lleva ``aria-busy``.
"""

from __future__ import annotations

from tiresias.a11y import uia_client as uc

from . import ia_motor as M


class AppModule(M.AsistenteAppModule):
	nombreAsistente = "Claude"

	def buscarConversacion(self, raiz):
		return self._buscar(raiz, uc.P_ARIAROLE, "feed")

	def analizar(self, nodo: M.Nodo) -> list[M.Mensaje]:
		return M.mensajesClaude(nodo)

	def buscarEntrada(self, raiz):
		return self._buscar(raiz, uc.P_ARIAROLE, "textbox")

	def estaTrabajando(self, raiz) -> bool | None:
		feed = self.buscarConversacion(raiz)
		if feed is None:
			return None
		try:
			return "busy=true" in str(feed.GetCurrentPropertyValue(uc.P_ARIAPROPERTIES) or "")
		except Exception:
			return None
