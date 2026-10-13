"""Pruebas de la pasada final de la 1.0.6.

- MSAA con ventanas de otros procesos: una ventana cuyo hilo no atiende
  mensajes no puede bloquear el núcleo (``SendMessageTimeout`` con
  ``WM_GETOBJECT`` y memoria de ventanas lentas).
- Diccionario del perfil: sin perfil activo se explica y no se deja editar;
  se guarda en el perfil que se abrió aunque el activo cambie.
- Lectura de números por dígitos, pares o tríos con puntos y comas según el
  idioma de la voz («1.500», «1,5», «1.500,25», «3.14» en inglés).

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev106_final -v``
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_rev106_final_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()

# Proceso auxiliar: crea una lista (LISTBOX) con dos elementos, escribe su
# hwnd y, según el modo, atiende mensajes o se queda sin atenderlos unos
# segundos (como una aplicación ocupada creando ventanas).
_HELPER = r'''
import ctypes, sys, time
from ctypes import wintypes
u = ctypes.WinDLL("user32", use_last_error=True)
u.CreateWindowExW.restype = wintypes.HWND
u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u.SendMessageW.restype = wintypes.LPARAM
mode = sys.argv[1]
WS_OVERLAPPEDWINDOW = 0x00CF0000
hwnd = u.CreateWindowExW(0, "LISTBOX", "Lista de prueba", WS_OVERLAPPEDWINDOW, 0, 0, 200, 200, None, None, None, None)
LB_ADDSTRING = 0x0180
for t in ("uno", "dos"):
	buf = ctypes.create_unicode_buffer(t)
	u.SendMessageW(hwnd, LB_ADDSTRING, 0, ctypes.cast(buf, ctypes.c_void_p).value)
sys.stdout.write("%d\n" % hwnd)
sys.stdout.flush()
if mode == "busy":
	time.sleep(4.0)
end = time.monotonic() + float(sys.argv[2])
msg = wintypes.MSG()
PM_REMOVE = 1
while time.monotonic() < end:
	while u.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
		u.TranslateMessage(ctypes.byref(msg))
		u.DispatchMessageW(ctypes.byref(msg))
	time.sleep(0.01)
u.DestroyWindow(hwnd)
'''


def _startHelper(mode: str, seconds: float):
	proc = subprocess.Popen(
		[sys.executable, "-c", _HELPER, mode, str(seconds)],
		stdout=subprocess.PIPE, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
	)
	line = proc.stdout.readline().strip()
	return proc, int(line or 0)


@unittest.skipUnless(sys.platform == "win32", "solo Windows")
class MsaaVentanasDeOtrosProcesosTests(unittest.TestCase):
	def setUp(self):
		from tiresias.a11y import msaa

		self.msaa = msaa
		msaa._slowThreads.clear()
		self.procs = []

	def tearDown(self):
		self.msaa._slowThreads.clear()
		for p in self.procs:
			try:
				p.wait(timeout=8)
			except subprocess.TimeoutExpired:
				p.kill()
				p.wait()
			if p.stdout:
				p.stdout.close()

	def _helper(self, mode, seconds):
		proc, hwnd = _startHelper(mode, seconds)
		self.procs.append(proc)
		self.assertTrue(hwnd, "el proceso auxiliar no creó la ventana")
		return hwnd

	def test_ventana_que_responde_se_lee(self):
		msaa = self.msaa
		hwnd = self._helper("pump", 3)
		self.assertTrue(msaa._isForeignWindow(hwnd))
		res = msaa.accessibleObjectFromEvent(hwnd, msaa.OBJID_CLIENT, 0)
		self.assertIsNotNone(res)
		pacc, child = res
		self.assertEqual(child, 0)
		self.assertEqual(pacc.accRole(0), 0x21)  # ROLE_SYSTEM_LIST
		# Evento de un elemento simple: el contenedor con su childId, como oleacc.
		pacc2, child2 = msaa.accessibleObjectFromEvent(hwnd, msaa.OBJID_CLIENT, 2)
		self.assertEqual(child2, 2)
		self.assertEqual(pacc2.accName(2), "dos")
		self.assertIsNotNone(msaa.accessibleObjectFromWindow(hwnd, msaa.OBJID_WINDOW))
		self.assertFalse(msaa._slowThreads)

	def test_ventana_ocupada_no_bloquea_y_se_recuerda(self):
		msaa = self.msaa
		hwnd = self._helper("busy", 3)
		t0 = time.monotonic()
		res = msaa.accessibleObjectFromEvent(hwnd, msaa.OBJID_CLIENT, 0)
		first = time.monotonic() - t0
		self.assertIsNone(res)
		self.assertLess(first, msaa.GETOBJECT_TIMEOUT_MS / 1000 + 1.0)
		self.assertTrue(msaa._slowThreads, "el hilo lento no se recordó")
		# Mientras sigue sin responder, se omite enseguida (solo la sonda corta).
		t0 = time.monotonic()
		self.assertIsNone(msaa.accessibleObjectFromWindow(hwnd))
		self.assertIsNone(msaa.accessibleObjectFromEvent(hwnd, msaa.OBJID_CLIENT, 1))
		self.assertLess(time.monotonic() - t0, 0.5)
		# Cuando vuelve a atender mensajes, se lee con normalidad.
		deadline = time.monotonic() + 8
		res = None
		while time.monotonic() < deadline and res is None:
			time.sleep(0.3)
			res = msaa.accessibleObjectFromEvent(hwnd, msaa.OBJID_CLIENT, 0)
		self.assertIsNotNone(res)
		self.assertFalse(msaa._slowThreads)

	def test_memoria_caduca(self):
		msaa = self.msaa
		hwnd = self._helper("pump", 2)
		msaa.markSlowWindow(hwnd, seconds=-1)
		self.assertFalse(msaa.isSlowWindow(hwnd))
		self.assertFalse(msaa._slowThreads)



class DiccionarioDelPerfilTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		import wx

		cls.wx = wx
		cls.app = wx.App.Get() or wx.App(False)

	def setUp(self):
		from tiresias.config import conf
		from tiresias.speech import dictionaries

		self.conf = conf
		self.d = dictionaries
		self._oldKey = dictionaries._profileKey
		self.addCleanup(self._restore)

	def _restore(self):
		self.d._profileKey = self._oldKey
		self.d.profileDict.clear()
		self.d.profileDict.fileName = None

	def _active(self, name):
		return mock.patch.object(type(self.conf), "activeProfileName", new_callable=mock.PropertyMock, return_value=name)

	def _entry(self, pattern="abc", replacement="xyz"):
		from tiresias.speech.dictionaries import Entry

		e = Entry(pattern, replacement, False, "anywhere", "", True)
		e.compile()
		return e

	def test_guardar_perfil_no_activo_va_a_su_archivo(self):
		d = self.d
		d._profileKey = "Otro"
		d.saveProfileDict("Lectura", [self._entry()])
		with open(d.profileDictFile("Lectura"), encoding="utf-8") as f:
			self.assertEqual(json.load(f)["entries"][0]["pattern"], "abc")
		self.assertEqual(len(d.profileDict), 0, "no debe tocar el diccionario cargado de otro perfil")
		d._profileKey = "Lectura"
		d.saveProfileDict("Lectura", [self._entry("uno", "dos")])
		self.assertEqual([e.pattern for e in d.profileDict], ["uno"])
		with self.assertRaises(OSError):
			d.saveProfileDict("", [])

	def test_sin_perfil_activo_no_deja_editar_y_lo_explica(self):
		from tiresias.gui import config_dialogs

		with self._active(None), mock.patch.object(config_dialogs, "speakMessageOnCore") as speak:
			dlg = config_dialogs.SpeechDictDialog(None, "profile")
			try:
				self.assertTrue(dlg.readOnly)
				for btn in (dlg.addButton, dlg.importButton, dlg.clearButton):
					self.assertFalse(btn.IsEnabled())
				dlg._onAdd(None)
				speak.assert_called_once()
				self.assertIn("perfil", speak.call_args[0][0])
				texts = [w.GetLabel() for w in dlg.GetChildren() if isinstance(w, self.wx.StaticText)]
				self.assertTrue(any("No hay ningún perfil activo" in t for t in texts))
			finally:
				dlg.Destroy()

	def test_se_guarda_en_el_perfil_abierto_aunque_cambie_el_activo(self):
		from tiresias.gui import config_dialogs

		d = self.d
		path = d.profileDictFile("Trabajo")
		if os.path.exists(path):
			os.remove(path)
		with self._active("Trabajo"):
			dlg = config_dialogs.SpeechDictDialog(None, "profile")
		self.assertFalse(dlg.readOnly)
		self.assertEqual(dlg.profileName, "Trabajo")
		dlg.entries.append(self._entry())
		# Mientras el diálogo está abierto, se desactiva el perfil (un desencadenante).
		with self._active(None):
			d.ensureProfileDict()
			with mock.patch.object(config_dialogs, "showError") as err:
				dlg._onOk(None)
			err.assert_not_called()
		with open(path, encoding="utf-8") as f:
			self.assertEqual([e["pattern"] for e in json.load(f)["entries"]], ["abc"])
		self.assertEqual(len(d.profileDict), 0)


class LecturaDeNumerosTests(unittest.TestCase):
	def setUp(self):
		from tiresias.speech import numbers

		self.n = numbers

	def test_espanol_por_digitos(self):
		f = lambda t: self.n.applyNumberMode(t, "digits", "es")  # noqa: E731
		self.assertEqual(f("1.500"), "1 5 0 0")
		self.assertEqual(f("1,5"), "1 coma 5")
		self.assertEqual(f("1.500,25"), "1 5 0 0 coma 2 5")
		self.assertEqual(f("cuesta 1.500.000 euros."), "cuesta 1 5 0 0 0 0 0 euros.")
		# Sin reglas de miles ni decimales: cada signo por su nombre.
		self.assertEqual(f("3.14"), "3 punto 1 4")
		self.assertEqual(f("versión 1.0.6"), "versión 1 punto 0 punto 6")
		self.assertEqual(f("2026"), "2 0 2 6")
		# Ninguna cifra pegada a un punto o una coma (la voz no lee un decimal).
		self.assertNotRegex(f("1.500 y 1,5 y 1.500,25 y 3.14"), r"\d[.,]|[.,]\d")

	def test_ingles_por_digitos(self):
		f = lambda t: self.n.applyNumberMode(t, "digits", "en_US")  # noqa: E731
		self.assertEqual(f("3.14"), "3 point 1 4")
		self.assertEqual(f("1,500"), "1 5 0 0")
		self.assertEqual(f("1,500.25"), "1 5 0 0 point 2 5")
		self.assertEqual(f("1.500"), "1 point 5 0 0")

	def test_pares_y_trios(self):
		n = self.n
		self.assertEqual(n.applyNumberMode("1.500", "triples", "es"), "1 500")
		self.assertEqual(n.applyNumberMode("1.500,25", "triples", "es"), "1 500 coma 25")
		self.assertEqual(n.applyNumberMode("12.345,6789", "pairs", "es"), "12 34 5 coma 67 89")
		self.assertEqual(n.applyNumberMode("1.500", "full", "es"), "1.500")
		self.assertEqual(n.applyNumberMode("123456", "digits"), "1 2 3 4 5 6")

	def test_process_text_usa_el_idioma_de_lectura(self):
		from tiresias.config import conf
		from tiresias.speech import api

		sp = conf["speech"]
		old = (sp["numberReading"], sp["symbolLevel"])
		self.addCleanup(lambda: (sp.__setitem__("numberReading", old[0]), sp.__setitem__("symbolLevel", old[1])))
		sp["numberReading"] = "digits"
		sp["symbolLevel"] = 0
		self.assertIn("1 5 0 0", api.processText("1.500", language="es"))
		self.assertIn("3 point 1 4", api.processText("3.14", language="en"))


if __name__ == "__main__":
	unittest.main()
