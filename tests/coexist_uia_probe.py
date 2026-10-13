"""Prueba de la notificación UIA que usa Tiresias para avisar a Narrador.

Lo lanza ``test_coexistencia.py``. Este proceso hace de cliente UIA (como
Narrador): se registra para las notificaciones de todo el escritorio y lanza
otro proceso que llama a ``announce.raiseUiaNotification``. Imprime un JSON
con las notificaciones recibidas en la última línea. No activa Narrador.

Uso: coexist_uia_probe.py [emitir]
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

TEXT = "Prueba de convivencia: notificación para Narrador"


def emit() -> None:
	import comtypes  # noqa: F401  (COM en este hilo)

	from tiresias.coexist import announce

	print(json.dumps({"emitted": announce.raiseUiaNotification(TEXT)}), flush=True)


def listen() -> None:
	from comtypes import COMObject

	from tiresias.a11y import uia_client as uc

	uc.initialize(2000)
	got: list = []

	class Handler(COMObject):
		_com_interfaces_ = [uc.UIA.IUIAutomationNotificationEventHandler]

		def IUIAutomationNotificationEventHandler_HandleNotificationEvent(self, sender, kind, processing, text, activity):
			try:
				name = sender.CachedName
			except Exception:
				name = ""
			got.append([kind, processing, text, activity, name])

	handler = Handler()
	uc.client.AddNotificationEventHandler(uc.client.GetRootElement(), uc.TreeScope_Subtree, uc.baseCacheRequest, handler)
	proc = subprocess.Popen([sys.executable, "-X", "utf8", __file__, "emitir"], stdout=subprocess.PIPE, text=True, encoding="utf-8")
	msg = wt.MSG()
	u32 = ctypes.windll.user32
	deadline = time.monotonic() + 15
	while time.monotonic() < deadline:
		while u32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
			u32.TranslateMessage(ctypes.byref(msg))
			u32.DispatchMessageW(ctypes.byref(msg))
		if proc.poll() is not None and got:
			break
		time.sleep(0.02)
	out = proc.communicate(timeout=10)[0]
	uc.client.RemoveAllEventHandlers()
	emitted = None
	for line in out.splitlines():
		if line.startswith("{"):
			emitted = json.loads(line).get("emitted")
	print(json.dumps({"emitted": emitted, "received": [g for g in got if g[2] == TEXT], "pid": os.getpid()}, ensure_ascii=False))


if __name__ == "__main__":
	if sys.argv[1:] == ["emitir"]:
		emit()
	else:
		listen()
