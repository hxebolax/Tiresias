"""Aplicación wx de prueba (otro proceso) con un menú contextual Win32 (#32768)
sobre una lista en vista de informe (``SysListView32``), como SocialRSS o el
escritorio. La usa ``test_menus_win32.py``.

- Se muestra sin activarse (no quita el primer plano al usuario).
- El menú se abre con ``WM_CONTEXTMENU`` enviado a la lista (lo mismo que la
  tecla Aplicaciones) y se recorre con ``WM_KEYDOWN`` enviados a su hilo.
- Escribe en la salida una línea JSON con el proceso y las ventanas; termina
  al leer «quit» en la entrada (o a los 60 s).

Ningún elemento del menú hace nada.
"""

import json
import os
import sys
import threading

import wx


class Frame(wx.Frame):
	def __init__(self):
		super().__init__(None, title="Prueba de menús Win32", pos=(40, 40), size=(420, 260))
		p = wx.Panel(self)
		self.lc = wx.ListCtrl(p, style=wx.LC_REPORT, size=(380, 150))
		self.lc.InsertColumn(0, "Autor")
		for i, a in enumerate(("Ana", "Luis")):
			self.lc.InsertItem(i, a)
		self.lc.Bind(wx.EVT_CONTEXT_MENU, self.onContext)

	def onContext(self, evt):
		m = wx.Menu()
		m.Append(wx.ID_ANY, "&Abrir")
		m.Append(wx.ID_ANY, "&Copiar enlace\tCtrl+C")
		e = m.Append(wx.ID_ANY, "&Eliminar")
		e.Enable(False)
		m.AppendSeparator()
		fav = m.AppendCheckItem(wx.ID_ANY, "&Favorito")
		fav.Check(True)
		sub = wx.Menu()
		sub.Append(wx.ID_ANY, "&Correo")
		sub.Append(wx.ID_ANY, "&Escritorio")
		m.AppendSubMenu(sub, "E&nviar a")
		m.Append(wx.ID_ANY, "&Propiedades")
		self.lc.PopupMenu(m)
		m.Destroy()


def main():
	app = wx.App(False)
	f = Frame()
	f.ShowWithoutActivating()

	def readStdin():
		for line in sys.stdin:
			if line.strip() == "quit":
				break
		wx.CallAfter(f.Destroy)

	threading.Thread(target=readStdin, daemon=True).start()
	wx.CallLater(60000, f.Destroy)
	print(json.dumps({"pid": os.getpid(), "frame": f.GetHandle(), "list": f.lc.GetHandle()}), flush=True)
	app.MainLoop()


if __name__ == "__main__":
	main()
