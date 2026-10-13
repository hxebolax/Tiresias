"""Menús Win32 clásicos (clase #32768) de otros procesos.

Fallo (1.0.4): en el menú contextual de la Papelera del escritorio y en el de
SocialRSS (wxPython) solo se oía «Contexto menú»; al bajar con las flechas no
se decía nada. El foco del teclado de esas aplicaciones está en una lista
``SysListView32``, que se lee con MSAA, y los menús #32768 se leían con UIA:

- el WinEvent de foco de cada elemento iba a UIA (solo una comprobación del
  foco), los eventos de foco UIA de los elementos se descartaban porque se
  decidía la API por la ventana con el foco del teclado (la lista, MSAA) y UIA
  no sigue el foco dentro del menú (da la lista). En la 1.0.2 el foco volvía a
  la lista; en la 1.0.4, con el menú abierto, ya no se movía.

Ahora los menús #32768 se leen siempre con MSAA (como NVDA), con un menú
abierto cuenta la ventana del menú y no la del control que lo abrió, y los
elementos dicen su nombre sin el atajo, el atajo aparte, el estado y «N de M».

La prueba real usa ``menu_win32_probe.py`` (otro proceso, sin activarse): el
menú se abre y se recorre con mensajes, sin teclas reales.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import types
import unittest
from ctypes import wintypes
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias.a11y import api_choice, msaa, uia_handler, winevents  # noqa: E402
from tiresias.objects import iaccessible  # noqa: E402
from tiresias.objects.roles import Role, State  # noqa: E402

MENU_HWND = 0x900
OWNER_HWND = 0x700
FG_HWND = 0x600


class _Info:
	def __init__(self, flags=0, hwndFocus=OWNER_HWND, hwndMenuOwner=0):
		self.flags = flags
		self.hwndFocus = hwndFocus
		self.hwndMenuOwner = hwndMenuOwner


class _Fixture(unittest.TestCase):
	"""Ventanas falsas: la activa, un control (lista MSAA o campo UIA) y un menú."""

	ownerClass = "SysListView32"

	def setUp(self):
		api_choice.invalidate()
		self.info = _Info()
		self.menu = 0
		classes = {MENU_HWND: "#32768", OWNER_HWND: self.ownerClass, FG_HWND: "wxWindowNR"}
		patches = [
			mock.patch.object(api_choice, "user32", types.SimpleNamespace(GetForegroundWindow=lambda: FG_HWND)),
			mock.patch.object(api_choice, "getClassName", side_effect=lambda h: classes.get(h, "")),
			mock.patch.object(api_choice, "_pidOf", return_value=4321),
			mock.patch.object(api_choice, "activeMenuWindow", side_effect=lambda tid: self.menu),
			mock.patch.object(api_choice, "_classList", return_value=set()),
			mock.patch("tiresias.winapi.getWindowThreadId", return_value=77),
			mock.patch("tiresias.winapi.getGUIThreadInfo", side_effect=lambda tid: self.info),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)
		self.addCleanup(api_choice.invalidate)


class APIChoiceTests(_Fixture):
	def test_menu_win32_con_msaa(self):
		self.assertNotIn("#32768", api_choice.WIN32_COMMON_CLASSES)
		self.assertEqual(api_choice.chooseAPI(MENU_HWND), api_choice.API_MSAA)

	def test_el_usuario_puede_forzar_uia(self):
		with mock.patch.object(api_choice, "_classList", side_effect=lambda k: {"#32768"} if k == "uiaClasses" else set()):
			self.assertEqual(api_choice._decide(MENU_HWND, "#32768"), api_choice.API_UIA)

	def test_sin_menu_cuenta_el_foco_del_teclado(self):
		el = types.SimpleNamespace(windowHandle=MENU_HWND)
		self.assertEqual(api_choice.focusWindow(el), OWNER_HWND)

	def test_menu_emergente_cuenta_el_menu(self):
		# Menú contextual abierto: el foco del teclado sigue en la lista.
		self.info = _Info(flags=api_choice.GUI_INMENUMODE | api_choice.GUI_POPUPMENUMODE, hwndMenuOwner=OWNER_HWND)
		self.menu = MENU_HWND
		self.assertEqual(api_choice.chooseAPIForFocus(), (api_choice.API_MSAA, MENU_HWND))
		# También si UIA avisa todavía del elemento de la barra que abrió el menú.
		self.assertEqual(api_choice.focusWindow(types.SimpleNamespace(windowHandle=FG_HWND)), MENU_HWND)

	def test_solo_barra_de_menus(self):
		self.info = _Info(flags=api_choice.GUI_INMENUMODE, hwndMenuOwner=FG_HWND)
		self.assertEqual(api_choice.focusWindow(), FG_HWND)
		self.assertEqual(api_choice.focusWindow(types.SimpleNamespace(windowHandle=0x123)), 0x123)


class UIAFocusTests(_Fixture):
	"""Los eventos de foco UIA de un menú #32768 no se anuncian (lo hace MSAA)."""

	ownerClass = "Edit"

	def _onFocus(self):
		obj = types.SimpleNamespace(windowHandle=MENU_HWND, hasFocus=True, shouldAllowFocusEvent=True)
		events = []
		checks = []
		uia_handler._focusSeq = 7
		with mock.patch.object(uia_handler, "_makeObject", return_value=obj), mock.patch.object(uia_handler, "isInForegroundWindow", return_value=True), mock.patch(
			"tiresias.events.executeEvent", side_effect=lambda name, o, **kw: events.append(name)
		), mock.patch.object(winevents, "scheduleFocusCheck", side_effect=checks.append), mock.patch.object(uia_handler, "_registerLocalHandlers"), mock.patch(
			"tiresias.api.getFocusObject", return_value=None
		):
			uia_handler._onFocus(object(), 7)
		return events, checks

	def test_en_un_menu_no_se_repite(self):
		self.info = _Info(flags=api_choice.GUI_INMENUMODE | api_choice.GUI_POPUPMENUMODE, hwndMenuOwner=OWNER_HWND)
		self.menu = MENU_HWND
		events, checks = self._onFocus()
		self.assertEqual(events, [])
		self.assertEqual(len(checks), 1)

	def test_fuera_de_un_menu_se_anuncia(self):
		events, _checks = self._onFocus()
		self.assertEqual(events, ["gainFocus"])

	def test_inicio_de_menu_uia_de_una_ventana_msaa(self):
		obj = types.SimpleNamespace(windowHandle=MENU_HWND, processID=4321)
		events = []
		with mock.patch.object(uia_handler, "_makeObject", return_value=obj), mock.patch("tiresias.events.executeEvent", side_effect=lambda name, o, **kw: events.append(name)):
			uia_handler._dispatchEvent(object(), "menuStart")
		self.assertEqual(events, [])


class WinEventFilterTests(unittest.TestCase):
	"""Filtro del hilo de ganchos para el inicio de los menús #32768."""

	def setUp(self):
		api_choice.invalidate()
		self.addCleanup(api_choice.invalidate)
		self.queued = []
		for p in (
			mock.patch.object(winevents.queue_handler, "queueFunction", side_effect=lambda f, *a: self.queued.append((f.__name__, a))),
			mock.patch.object(winevents, "_focusPid", 4321),
			mock.patch.object(winevents, "_focusIsMSAA", False),
			mock.patch.object(winevents, "_isMenuWindow", side_effect=lambda h: h == MENU_HWND),
		):
			p.start()
			self.addCleanup(p.stop)

	def _menuStart(self, pid, fgPid=0):
		pids = {MENU_HWND: pid, FG_HWND: fgPid}
		with mock.patch.object(winevents, "_pidOf", side_effect=lambda h: pids.get(h, 0)), mock.patch.object(
			winevents, "_user32", types.SimpleNamespace(GetForegroundWindow=lambda: FG_HWND)
		):
			winevents.onWinEvent(msaa.EVENT_SYSTEM_MENUPOPUPSTART, MENU_HWND, msaa.OBJID_CLIENT, 0, 1)

	def test_menu_del_proceso_del_foco_uia(self):
		# Foco en un campo UIA de la aplicación (antes se descartaba).
		self._menuStart(4321)
		self.assertEqual(self.queued, [("_onMSAAEvent", ("menuStart", MENU_HWND, msaa.OBJID_CLIENT, 0))])

	def test_menu_de_la_ventana_activa(self):
		# Menú de un icono del área de notificación: su proceso es el de la ventana activa.
		self._menuStart(999, fgPid=999)
		self.assertEqual(len(self.queued), 1)

	def test_menu_de_un_proceso_en_segundo_plano(self):
		self._menuStart(999, fgPid=555)
		self.assertEqual(self.queued, [])

	def test_foco_de_un_elemento_de_menu(self):
		with mock.patch.object(winevents, "_pidOf", return_value=999):
			winevents.onWinEvent(msaa.EVENT_OBJECT_FOCUS, MENU_HWND, msaa.OBJID_CLIENT, 3, 1)
		# Desde la 1.0.11 el foco MSAA lleva además su número de secuencia (descarta focos viejos).
		self.assertEqual(len(self.queued), 1)
		name, args = self.queued[0]
		self.assertEqual((name, args[:3]), ("_onFocusWinEvent", (MENU_HWND, msaa.OBJID_CLIENT, 3)))
		self.assertIsInstance(args[3], int)


class MenuItemTextTests(unittest.TestCase):
	def _obj(self, name, role=msaa.ROLE_MENUITEM, shortcut="c"):
		class Acc:
			def accName(self, c):
				return name

			def accRole(self, c):
				return role

			def accKeyboardShortcut(self, c):
				return shortcut

		return iaccessible.IAccessibleObject(Acc(), 2, 0x900)

	def test_nombre_sin_atajo_y_atajo_aparte(self):
		o = self._obj("Copiar enlace\tCtrl+C")
		self.assertEqual(o.name, "Copiar enlace")
		self.assertEqual(o.keyboardShortcut, "c Ctrl+C")

	def test_sin_atajo(self):
		o = self._obj("Propiedades", shortcut="p")
		self.assertEqual(o.name, "Propiedades")
		self.assertEqual(o.keyboardShortcut, "p")

	def test_otro_rol_no_se_toca(self):
		o = self._obj("a\tb", role=msaa.ROLE_LISTITEM, shortcut="")
		self.assertEqual(o.name, "a\tb")
		self.assertEqual(o.keyboardShortcut, "")


# ---------------------------------------------------------------------- prueba real
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_WinEventProc = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND, wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
_user32.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, _WinEventProc, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
_user32.SetWinEventHook.restype = wintypes.HANDLE
_user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
WM_KEYDOWN, WM_KEYUP, WM_CONTEXTMENU = 0x0100, 0x0101, 0x007B
VK = {"down": (0x28, 0x50), "right": (0x27, 0x4D), "escape": (0x1B, 0x01)}


def _menus(pid):
	out = []

	@ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
	def cb(h, _l):
		if _user32.IsWindowVisible(h) and api_choice.getClassName(h) == "#32768":
			p = wintypes.DWORD()
			_user32.GetWindowThreadProcessId(h, ctypes.byref(p))
			if p.value == pid:
				out.append(int(h))
		return True

	_user32.EnumWindows(cb, 0)
	return out


class _HookThread(threading.Thread):
	"""Ganchos WinEvent fuera de contexto (como los de Tiresias) que llaman a ``winevents.onWinEvent``."""

	def __init__(self, pid):
		super().__init__(daemon=True)
		self.pid = pid
		self.ready = threading.Event()
		self.stop = False

	def run(self):
		def cb(_h, event, hwnd, idObject, idChild, thread, _t):
			winevents.onWinEvent(event, hwnd or 0, idObject, idChild, thread)

		self.proc = _WinEventProc(cb)
		hooks = [
			_user32.SetWinEventHook(msaa.EVENT_SYSTEM_MENUPOPUPSTART, msaa.EVENT_SYSTEM_MENUPOPUPSTART, None, self.proc, self.pid, 0, 0),
			_user32.SetWinEventHook(msaa.EVENT_OBJECT_FOCUS, msaa.EVENT_OBJECT_FOCUS, None, self.proc, self.pid, 0, 0),
		]
		self.ready.set()
		msg = wintypes.MSG()
		while not self.stop:
			while _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
				_user32.TranslateMessage(ctypes.byref(msg))
				_user32.DispatchMessageW(ctypes.byref(msg))
			time.sleep(0.02)
		for h in hooks:
			_user32.UnhookWinEvent(h)


class RealMenuTests(unittest.TestCase):
	"""Menú contextual wx (#32768) de otro proceso sobre una lista SysListView32."""

	@classmethod
	def setUpClass(cls):
		cls.app = subprocess.Popen(
			[sys.executable, "-X", "utf8", os.path.join(ROOT, "tests", "menu_win32_probe.py")],
			stdin=subprocess.PIPE,
			stdout=subprocess.PIPE,
			text=True,
			cwd=ROOT,
		)
		cls.info = json.loads(cls.app.stdout.readline())
		cls.pid = cls.info["pid"]

	@classmethod
	def tearDownClass(cls):
		for _i in range(4):
			ms = _menus(cls.pid)
			if not ms:
				break
			cls._key(ms[0], "escape")
			time.sleep(0.3)
		try:
			cls.app.stdin.write("quit\n")
			cls.app.stdin.flush()
			cls.app.wait(10)
		except Exception:
			cls.app.kill()

	@staticmethod
	def _key(hwnd, name):
		vk, scan = VK[name]
		lp = 1 | (scan << 16) | (0x01000000 if name != "escape" else 0)
		_user32.PostMessageW(hwnd, WM_KEYDOWN, vk, lp)
		_user32.PostMessageW(hwnd, WM_KEYUP, vk, lp | 0xC0000000)

	def _waitQueued(self, n, timeout=4.0):
		deadline = time.time() + timeout
		while time.time() < deadline and len(self.queued) < n:
			time.sleep(0.05)

	def test_menu_contextual_sobre_lista(self):
		api_choice.invalidate()
		self.queued = []
		hook = _HookThread(self.pid)
		with mock.patch.object(winevents.queue_handler, "queueFunction", side_effect=lambda f, *a: self.queued.append((f.__name__, a))), mock.patch.object(
			winevents, "_focusPid", self.pid
		), mock.patch.object(winevents, "_focusIsMSAA", False):
			hook.start()
			hook.ready.wait(5)
			try:
				_user32.PostMessageW(self.info["list"], WM_CONTEXTMENU, self.info["list"], 0xFFFFFFFF)
				deadline = time.time() + 5
				while time.time() < deadline and not _menus(self.pid):
					time.sleep(0.05)
				menus = _menus(self.pid)
				self.assertEqual(len(menus), 1, "no se abrió el menú contextual")
				menu = menus[0]
				self._waitQueued(1)
				for _i in range(5):
					# Abrir, Copiar enlace, Eliminar, Favorito, Enviar a.
					self._key(menu, "down")
					time.sleep(0.15)
				self._waitQueued(6)
				self._key(menu, "right")
				self._waitQueued(8)
				time.sleep(0.3)
				tid = _user32.GetWindowThreadProcessId(menu, None)
				active = api_choice.activeMenuWindow(tid)
				focusedInActive = iaccessible.IAccessibleObject.fromFocusedWindow(active) if active else None
			finally:
				hook.stop = True
				hook.join(5)
		names = [q[0] for q in self.queued]
		self.assertIn(("_onMSAAEvent", ("menuStart", menu, msaa.OBJID_CLIENT, 0)), self.queued)
		focusArgs = [a for n, a in self.queued if n == "_onFocusWinEvent"]
		self.assertGreaterEqual(len(focusArgs), 6, names)
		# Cada foco se procesa como en el núcleo y se recoge el objeto anunciado.
		announced = []
		with mock.patch("tiresias.events.executeEvent", side_effect=lambda name, o, **kw: announced.append(o)), mock.patch(
			"tiresias.api.getFocusObject", return_value=None
		), mock.patch.object(uia_handler, "_registerLocalHandlers"):
			# Sin el número de secuencia: aquí se reprocesan todos de golpe y, desde la
			# 1.0.11, un foco con un foco más reciente ya en cola se descarta.
			for args in focusArgs:
				winevents._onFocusWinEvent(*args[:3])
		got = [(o.name, o.role, o.keyboardShortcut, o.positionInfo.get("indexInGroup"), o.positionInfo.get("similarItemsInGroup")) for o in announced]
		self.assertEqual(
			got[:6],
			[
				("Abrir", Role.MENUITEM, "a", 1, 6),
				("Copiar enlace", Role.MENUITEM, "c Ctrl+C", 2, 6),
				("Eliminar", Role.MENUITEM, "e", 3, 6),
				("Favorito", Role.MENUITEM, "f", 4, 6),
				("Enviar a", Role.MENUITEM, "n", 5, 6),
				("Correo", Role.MENUITEM, "c", 1, 2),
			],
		)
		self.assertIn(State.UNAVAILABLE, announced[2].states)
		self.assertIn(State.CHECKED, announced[3].states)
		self.assertIn(State.HASPOPUP, announced[4].states)
		# Con el submenú abierto, el menú activo (el foco con un menú abierto) es el
		# submenú. Su elemento marcado solo lo da accFocus si la aplicación es la
		# activa (aquí no se activa, para no quitar el primer plano al usuario).
		self.assertTrue(active and active != menu)
		self.assertIsNotNone(focusedInActive)
		self.assertIn((focusedInActive.role, focusedInActive.name), ((Role.POPUPMENU, "Enviar a"), (Role.MENUITEM, "Correo")))


if __name__ == "__main__":
	unittest.main()
