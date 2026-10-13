"""Generador de informe IA: diagnóstico y soluciones a partir del registro, en HTML navegable."""

from __future__ import annotations

import datetime
import threading

from tiresias.log import getLogger

from . import HerramientaBase, MetadatosHerramienta

log = getLogger("consoleLog")
#: Caracteres finales del registro que se envían (lo más reciente).
MAX_CONTEXTO = 30000


class HerramientaInformeIA(HerramientaBase):
	METADATOS = MetadatosHerramienta(
		nombre="Generador de informe IA",
		version="1.0.0",
		descripcion="Analiza el log completo y genera un informe detallado con soluciones sugeridas",
		autor="Héctor J. Benítez Corredera",
		categoria="ia",
	)

	def ejecutar(self, **kwargs):
		import wx

		from tiresias.gui import messageBox

		from .. import avisos, ia
		from ..interfaz.informe_ia import InformeIADialog

		visor = kwargs.get("visor")
		texto = self.texto_de(kwargs)
		if not texto.strip():
			messageBox("No hay contenido en la consola para analizar.", "Informe IA", wx.OK | wx.ICON_WARNING, visor)
			return None
		cliente = ia.cliente_actual()
		progreso = wx.ProgressDialog(
			"IA pensando...",
			"Analizando el registro de la consola para generar un informe detallado...",
			parent=visor,
			style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE,
		)
		progreso.Pulse()
		avisos.anunciar("Generando el informe con {}...".format(cliente.nombre))
		temporizador = wx.Timer(progreso)
		progreso.Bind(wx.EVT_TIMER, lambda evt: progreso.Pulse() if progreso else None, temporizador)
		temporizador.Start(400)

		def terminar() -> None:
			try:
				temporizador.Stop()
				progreso.Destroy()
			except Exception:
				pass

		def mostrar(informe: str) -> None:
			terminar()
			avisos.anunciar("Informe listo.")
			InformeIADialog.mostrar(visor, informe)

		def fallo(mensaje: str) -> None:
			terminar()
			messageBox(mensaje, "Error de IA", wx.OK | wx.ICON_ERROR, visor)

		def hilo() -> None:
			try:
				instrucciones = ia.prompt_informe(datetime.date.today().isoformat())
				respuesta = cliente.chat([ia.Turno("user", texto[-MAX_CONTEXTO:])], instrucciones)
				wx.CallAfter(mostrar, respuesta)
			except Exception as e:  # noqa: BLE001
				log.debug("consoleLog: error generando el informe", exc_info=True)
				wx.CallAfter(fallo, str(e))

		threading.Thread(target=hilo, name="consoleLogInforme", daemon=True).start()
		return None
