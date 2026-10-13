"""Prueba de las ventanas propias leídas en el hilo de la interfaz (se ejecuta aparte).

Crea un diálogo wx (como el cuadro de mensaje de Tiresias: RichEdit de solo
lectura, etiqueta, casilla, lista y botones) y, desde un hilo MTA que hace de
núcleo, lo lee con MSAA a través de :mod:`tiresias.a11y.own_windows`:

- los objetos son ``OwnAccessible`` y todas las llamadas COM se hacen en el
  hilo de la interfaz;
- con la interfaz ocupada, la primera llamada falla en ~``CALL_TIMEOUT`` y las
  siguientes al instante (cortacircuitos); al liberarse vuelve a funcionar;
- un objeto de una ventana ya destruida no hace caer el proceso.

Escribe el resultado en JSON por la salida estándar.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import comtypes  # noqa: E402
import wx  # noqa: E402

from tiresias.a11y import msaa, own_windows  # noqa: E402
from tiresias.objects.iaccessible import IAccessibleObject  # noqa: E402


def main() -> int:
	app = wx.App(False)
	own_windows.initialize()
	keep = wx.Frame(None, title="mantener")
	dlg = wx.Dialog(None, title="Prueba propia")
	s = wx.BoxSizer(wx.VERTICAL)
	st = wx.StaticText(dlg, label="&Mensaje:")
	rich = wx.TextCtrl(dlg, value="Hola\r\nmundo", style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
	chk = wx.CheckBox(dlg, label="Casilla")
	lst = wx.ListBox(dlg, choices=["uno", "dos", "tres"])
	btn = wx.Button(dlg, wx.ID_OK, "Aceptar")
	for w in (st, rich, chk, lst, btn):
		s.Add(w)
	dlg.SetSizerAndFit(s)
	out: dict = {}
	guiThread = threading.get_ident()
	calledIn: set = set()
	realCall = own_windows._Call.run

	def tracedRun(self):
		calledIn.add(threading.get_ident())
		return realCall(self)

	own_windows._Call.run = tracedRun

	def worker() -> None:
		comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
		try:
			time.sleep(0.3)
			pacc = msaa.accessibleObjectFromWindow(dlg.GetHandle())
			out["tipo"] = type(pacc).__name__
			obj = IAccessibleObject.fromWindow(dlg.GetHandle())
			out["nombre"] = obj.name
			out["rol"] = obj.role.name
			kids = obj.children
			out["hijos"] = len(kids)
			names = []
			for k in kids:
				names.append((k.role.name, k.name))
			out["hijosNombres"] = names
			item = IAccessibleObject.fromWindow(lst.GetHandle())
			items = item.children
			out["lista"] = [(i.name, i.positionInfo) for i in items]
			out["mismo"] = obj == IAccessibleObject.fromWindow(dlg.GetHandle())
			out["hilos"] = sorted(calledIn) == [guiThread]
			# Interfaz ocupada: el hilo principal duerme 1,5 s.
			wx.CallAfter(time.sleep, 1.5)
			time.sleep(0.2)
			t0 = time.monotonic()
			r1 = IAccessibleObject.fromWindow(chk.GetHandle())
			out["ocupada1_ms"] = round((time.monotonic() - t0) * 1000)
			out["ocupada1"] = r1 is None
			t0 = time.monotonic()
			r2 = [IAccessibleObject.fromWindow(btn.GetHandle()) for _i in range(20)]
			out["ocupada20_ms"] = round((time.monotonic() - t0) * 1000)
			out["ocupada20"] = all(r is None for r in r2)
			out["nombreOcupada"] = obj.__class__._get_name(obj)
			time.sleep(1.8)
			r3 = IAccessibleObject.fromWindow(chk.GetHandle())
			out["libre"] = r3.name if r3 is not None else None
			# Objeto de una ventana destruida.
			stale = IAccessibleObject.fromWindow(rich.GetHandle())
			done = threading.Event()
			wx.CallAfter(lambda: (dlg.Destroy(), done.set()))
			done.wait(5)
			time.sleep(0.2)
			out["destruida"] = [stale.__class__._get_name(stale), stale.__class__._get_children(stale)]
			out["stats"] = dict(own_windows.stats)
		except Exception as e:
			out["error"] = repr(e)
		finally:
			wx.CallAfter(keep.Destroy)

	threading.Thread(target=worker, daemon=True).start()
	dlg.Show()
	app.MainLoop()
	print(json.dumps(out, ensure_ascii=False))
	return 0


if __name__ == "__main__":
	sys.exit(main())
