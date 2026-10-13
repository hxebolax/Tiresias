"""Sonda de ``test_salida_modal.py``: salir con un diálogo modal abierto.

Abre un diálogo modal (``kind``: el cuadro de Tiresias, un cuadro nativo de
Windows o dos cuadros seguidos, como cuando al cancelar uno se abre otro) y,
con el diálogo abierto, pide salir como hace el núcleo
(``gui.exitMainLoop``). Imprime un JSON con lo que devolvió cada diálogo y si
el bucle principal terminó.

Uso: exit_modal_probe.py tiresias|nativo|encadenado
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import wx  # noqa: E402


def main() -> int:
	kind = sys.argv[1]
	app = wx.App(False)
	frame = wx.Frame(None, title="Prueba de salida")
	from tiresias import gui
	from tiresias.gui import message_dialog

	results: list = []

	def openDialog() -> None:
		# Con el diálogo abierto se pide salir (desde otro hilo, como el núcleo).
		import threading

		threading.Timer(0.6, gui.exitMainLoop).start()
		if kind == "nativo":
			results.append(wx.MessageBox("Pregunta nativa", "Prueba", wx.OK | wx.CANCEL, frame))
			return
		dlg = message_dialog.MessageDialog(frame, "Pregunta de Tiresias", "Prueba", wx.YES_NO | wx.ICON_QUESTION)
		try:
			results.append(dlg.ShowModal())
		finally:
			dlg.Destroy()
		if kind == "encadenado":
			# Al cancelar el primero se abre otro: también debe cerrarse.
			dlg2 = message_dialog.MessageDialog(frame, "Segunda pregunta", "Prueba", wx.OK)
			try:
				results.append(dlg2.ShowModal())
			finally:
				dlg2.Destroy()

	wx.CallLater(300, openDialog)
	# Seguridad: si la salida no funciona, la prueba no se queda colgada.
	guard = wx.CallLater(15000, lambda: (results.append("bloqueado"), os._exit(3)))
	app.MainLoop()
	guard.Stop()
	print(json.dumps({"results": results, "mainLoopEnded": True}))
	return 0


if __name__ == "__main__":
	sys.exit(main())
