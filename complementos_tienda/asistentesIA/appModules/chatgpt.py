"""Aplicación de escritorio de Codex (``ChatGPT.exe``, paquete ``OpenAI.Codex``).

La conversación es una lista plana dentro de una región; los mensajes los
separan rótulos ocultos («Tú dijiste:», «ChatGPT dijo:»). No hay indicador de
ocupado en la conversación: mientras trabaja, el cuadro de escribir tiene un
botón de detener.

Además se acorta la descripción de los botones de «Mensajes de usuarios», que
traen el turno entero y se leían durante minutos al pasar con Tab.
"""

from __future__ import annotations

import re

from tiresias.a11y import uia_client as uc

from . import ia_motor as M

#: Largo de la descripción de los botones que llevan a cada mensaje.
LARGO_DESCRIPCION = 120

_RE_IR_AL_MENSAJE = re.compile(r"^(ir al mensaje|go to .*message)", re.I)


def acortar(texto: str, largo: int = LARGO_DESCRIPCION) -> str:
	texto = " ".join((texto or "").split())
	if len(texto) <= largo:
		return texto
	return texto[:largo].rsplit(" ", 1)[0] + "…"


class AppModule(M.AsistenteAppModule):
	nombreAsistente = "Codex"

	def event_NVDAObject_init(self, obj) -> None:
		if getattr(obj, "UIAControlType", 0) != uc.CT_BUTTON:
			return
		try:
			if _RE_IR_AL_MENSAJE.match(obj.name or ""):
				obj.description = acortar(obj.description)
		except Exception:
			pass

	def buscarConversacion(self, raiz):
		principal = self._buscar(raiz, uc.P_ARIAROLE, "main")
		if principal is None:
			return None
		return self._buscar(principal, uc.P_ARIAROLE, "region")

	def analizar(self, nodo: M.Nodo) -> list[M.Mensaje]:
		return M.mensajesCodex(nodo)

	def buscarEntrada(self, raiz):
		return self._buscar(raiz, uc.P_ARIAROLE, "textbox")
