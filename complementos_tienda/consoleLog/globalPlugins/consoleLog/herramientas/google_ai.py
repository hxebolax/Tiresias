"""Chat de inteligencia artificial sobre el contenido de la consola.

Una sola ventana de chat por sesión: si ya está abierta, se trae al frente
y, si hay selección nueva en el visor, se usa como contexto.
"""

from __future__ import annotations

from . import HerramientaBase, MetadatosHerramienta


class HerramientaGoogleAI(HerramientaBase):
	METADATOS = MetadatosHerramienta(
		nombre="Google AI (Gemini/Gemma) y otros proveedores",
		version="1.2.0",
		descripcion="Asistente de IA con varias claves, historial y archivos adjuntos",
		autor="Héctor J. Benítez Corredera",
		categoria="ia",
	)

	def inicializar(self) -> bool:
		self._dialogo = None
		return True

	def ejecutar(self, **kwargs):
		from tiresias.gui.helpers import bringToFront, isAlive

		from ..interfaz.chat_ia import ChatIADialog

		visor = kwargs.get("visor")
		texto = kwargs.get("texto", "") or ""
		seleccionado = kwargs.get("seleccionado", "") or ""
		if isAlive(self._dialogo):
			self._dialogo.actualizar_contexto(texto, seleccionado)
			bringToFront(self._dialogo)
			return None
		self._dialogo = ChatIADialog(visor, self, texto, seleccionado)
		self._dialogo.Show()
		bringToFront(self._dialogo)
		return None

	def olvidar_dialogo(self, dialogo) -> None:
		if self._dialogo is dialogo:
			self._dialogo = None

	def terminar(self) -> None:
		from tiresias.gui.helpers import isAlive, runOnGui

		dialogo, self._dialogo = self._dialogo, None

		def cerrar() -> None:
			if isAlive(dialogo):
				try:
					dialogo.Destroy()
				except Exception:
					pass

		if dialogo is not None:
			runOnGui(cerrar)
