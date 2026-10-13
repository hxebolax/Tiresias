"""Prueba del auxiliar del punto de conexión de NVDA (``tiresiasNvdaWindow.exe /serve``).

Lo lanza ``test_coexistencia.py`` en un proceso aparte (el servidor RPC solo
se puede registrar una vez por proceso). Para no tocar el NVDA real del
usuario, todo ocurre en un escritorio propio y vacío: el punto de conexión
depende del escritorio del hilo que llama (``NvdaCtlr.<sesión>.<escritorio>``),
así que el de este escritorio está libre aunque NVDA esté en ejecución.

Comprueba que:

- un programa con la biblioteca cliente llega a Tiresias a través del
  auxiliar (con el PID del programa original);
- las marcas de un speakSsml síncrono vuelven al programa;
- Tiresias rechaza el reenvío de procesos que no son su auxiliar;
- al cerrar el auxiliar el punto de conexión queda libre al instante.

Imprime un JSON con los resultados en la última línea.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias.controller import server as srv  # noqa: E402

CLIENT = os.path.join(ROOT, "data", "controller", "x64", "tiresiasControllerClient.dll")
BRIDGE = os.path.join(ROOT, "data", "controller", "x64", "tiresiasNvdaWindow.exe")

u32 = ctypes.windll.user32
u32.CreateDesktopW.restype = wt.HANDLE
u32.CreateDesktopW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.c_void_p]
u32.SetThreadDesktop.argtypes = [wt.HANDLE]
u32.CloseDesktop.argtypes = [wt.HANDLE]
u32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]


class Recorder(srv.Handlers):
	def __init__(self) -> None:
		self.calls: list = []
		self.server: srv.ControllerServer | None = None

	def testIfRunning(self, pid):
		return 0

	def speakText(self, pid, text):
		self.calls.append(["speakText", pid, text])
		return 0

	def cancelSpeech(self, pid):
		self.calls.append(["cancel", pid])
		return 0

	def brailleMessage(self, pid, text):
		self.calls.append(["braille", pid, text])
		return 0

	def speakSsml(self, pid, text, level, priority, asynchronous):
		self.calls.append(["ssml", pid, asynchronous])
		if not asynchronous:
			for name in ("uno", "dos"):
				self.server.markReached(name)
		return 0

	def isSpeaking(self, pid):
		return 0, True


def _windowOf(pid: int) -> int:
	"""Ventana de nivel superior del proceso ``pid`` (o 0)."""
	found = []
	PROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

	def cb(hwnd, lp):
		p = wt.DWORD()
		u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
		if p.value == pid:
			found.append(hwnd)
			return False
		return True

	def run() -> None:
		# En un hilo nuevo: está en el escritorio del proceso (el del auxiliar).
		deadline = time.monotonic() + 3
		while not found and time.monotonic() < deadline:
			u32.EnumWindows(PROC(cb), 0)
			if not found:
				time.sleep(0.05)

	t = threading.Thread(target=run)
	t.start()
	t.join(5)
	return found[0] if found else 0


def winClass(hwnd: int) -> str:
	buf = ctypes.create_unicode_buffer(256)
	u32.GetClassNameW(hwnd, buf, 256)
	return buf.value


def winTitle(hwnd: int) -> str:
	buf = ctypes.create_unicode_buffer(256)
	u32.GetWindowTextW(hwnd, buf, 256)
	return buf.value


def main() -> int:
	result: dict = {"ok": False}
	session = wt.DWORD(0)
	ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session))
	deskName = f"TiresiasPrueba{os.getpid()}"
	hDesk = u32.CreateDesktopW(deskName, None, None, 0, 0x10000000, None)  # GENERIC_ALL
	if not hDesk:
		print(json.dumps({"ok": False, "error": "CreateDesktop"}))
		return 1
	ns = f"{session.value}.{deskName}"
	rec = Recorder()
	server = srv.ControllerServer(rec)
	rec.server = server
	if server.start() != 0:
		print(json.dumps({"ok": False, "error": "server.start"}))
		return 1
	# El punto de Tiresias tiene otro nombre: así el cliente no lo encuentra
	# directamente y tiene que pasar por el auxiliar (punto de NVDA).
	server.namespace = ns
	relayPrefix = "TiresiasPruebaReenvio."
	if server.listen(relayPrefix) != 0:
		print(json.dumps({"ok": False, "error": "listen"}))
		return 1
	bridge = subprocess.Popen([BRIDGE, str(os.getpid()), "/serve", "NvdaCtlr." + ns, relayPrefix + ns], creationflags=0x08000000)
	server.setRelayPid(bridge.pid)
	out: dict = {}

	def clientThread() -> None:
		try:
			if not u32.SetThreadDesktop(hDesk):
				out["error"] = "SetThreadDesktop"
				return
			c = ctypes.WinDLL(CLIENT)
			deadline = time.monotonic() + 5
			st = -1
			while time.monotonic() < deadline:
				st = c.nvdaController_testIfRunning()
				if st == 0:
					break
				time.sleep(0.05)
			out["testIfRunning"] = st
			out["speakText"] = c.nvdaController_speakText("hola desde el puente")
			out["braille"] = c.nvdaController_brailleMessage("braille")
			out["cancel"] = c.nvdaController_cancelSpeech()
			pid = wt.ULONG()
			out["getProcessId"] = [c.nvdaController_getProcessId(ctypes.byref(pid)), pid.value]
			speaking = ctypes.c_ubyte()
			out["isSpeaking"] = [c.nvdaController_isSpeaking(ctypes.byref(speaking)), speaking.value]
			marks: list[str] = []
			CB = ctypes.WINFUNCTYPE(ctypes.c_ulong, wt.LPCWSTR)
			cb = CB(lambda m: (marks.append(m), 0)[1])
			c.nvdaController_setOnSsmlMarkReachedCallback(cb)
			out["ssmlSync"] = c.nvdaController_speakSsml("<speak>a <mark name='uno'/> b</speak>", -1, 0, 0)
			c.nvdaController_setOnSsmlMarkReachedCallback(None)
			out["marks"] = marks
			out["ssmlAsync"] = c.nvdaController_speakSsml("<speak>asíncrono</speak>", -1, 0, 1)
			# Reenvío no autorizado: Tiresias deja de aceptar al auxiliar.
			server.setRelayPid(0)
			out["denied"] = c.nvdaController_speakText("no autorizado")
			server.setRelayPid(bridge.pid)
			# Al cerrar el auxiliar, el punto de conexión de NVDA queda libre.
			bridge.terminate()
			bridge.wait(5)
			out["afterClose"] = c.nvdaController_testIfRunning()
			# Como hace NVDA al arrancar: WM_QUIT a la ventana «NVDA» del auxiliar.
			b2 = subprocess.Popen([BRIDGE, str(os.getpid()), "/window", "/serve", "NvdaCtlr." + ns, relayPrefix + ns], creationflags=0x08000000)
			server.setRelayPid(b2.pid)
			deadline = time.monotonic() + 5
			while time.monotonic() < deadline and c.nvdaController_testIfRunning() != 0:
				time.sleep(0.05)
			hwnd = _windowOf(b2.pid)
			out["window"] = [winClass(hwnd), winTitle(hwnd)] if hwnd else None
			if hwnd:
				u32.PostMessageW(hwnd, 0x0012, 0, 0)  # WM_QUIT
			try:
				out["quitExit"] = b2.wait(5)
			except subprocess.TimeoutExpired:
				b2.kill()
				out["quitExit"] = None
			out["afterQuit"] = c.nvdaController_testIfRunning()
		except Exception as e:  # pragma: no cover - diagnóstico
			out["error"] = repr(e)

	t = threading.Thread(target=clientThread)
	t.start()
	t.join(30)
	# El propio proceso puede ocupar ahora el punto de conexión liberado.
	server.namespace = ns
	out["relisten"] = server.listen("NvdaCtlr.")
	out["calls"] = rec.calls
	out["ownPid"] = os.getpid()
	if bridge.poll() is None:
		bridge.kill()
	server.stop()
	u32.CloseDesktop(hDesk)
	result.update(out)
	result["ok"] = "error" not in out
	print(json.dumps(result, ensure_ascii=False))
	return 0


if __name__ == "__main__":
	sys.exit(main())
