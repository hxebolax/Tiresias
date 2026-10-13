"""Pruebas de objetos, eventos y API de accesibilidad: MSAA/IA2, Java Access
Bridge, consolas, listas, diálogos, selección y protección de la pantalla de
bloqueo.

No se inyectan teclas ni se tocan programas del usuario. Los campos de
edición de prueba se crean en este mismo proceso (ventana ``EDIT`` oculta).

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
import tempfile
import unittest
from ctypes import wintypes
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="tiresias_test_objetos_")
shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
paths.setDataDir(_TMP)
paths.ensureDataDirs()

from tiresias import a11y  # noqa: E402,F401  (registra las opciones)
from tiresias import textinfo  # noqa: E402
from tiresias.a11y import api_choice, jab, msaa, system, win32ctl  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.objects import behaviors, terminal  # noqa: E402
from tiresias.objects.base import AccObject  # noqa: E402
from tiresias.objects.iaccessible import _IA2_ROLES, _MSAA_ROLES, EditWindowTextInfo  # noqa: E402
from tiresias.objects.jab import mapRole, parseStates  # noqa: E402
from tiresias.objects.listview import RowWithColumns  # noqa: E402
from tiresias.objects.roles import Role, State  # noqa: E402


class FakeObj(AccObject):
	"""Objeto accesible mínimo para las pruebas."""

	def __init__(self, name="", role=Role.STATICTEXT, states=(), children=(), value="", pid=100):
		super().__init__()
		self._n, self._r, self._s, self._c, self._v, self._pid = name, role, set(states), list(children), value, pid

	def _get_name(self):
		return self._n

	def _get_role(self):
		return self._r

	def _get_states(self):
		return set(self._s)

	def _get_children(self):
		return list(self._c)

	def _get_value(self):
		return self._v

	def _get_processID(self):
		return self._pid

	def _get_appModule(self):
		return None


# ====================================================================== consola
class TerminalDiffTests(unittest.TestCase):
	def test_lineas_nuevas_al_desplazarse(self):
		old = ["C:\\> dir", "a.txt", "b.txt"]
		new = ["a.txt", "b.txt", "c.txt", "C:\\>"]
		self.assertEqual(terminal.computeNewText(old, new), ["c.txt", "C:\\>"])

	def test_diferencia_por_caracteres(self):
		old = ["Descargando 45%"]
		new = ["Descargando 46%"]
		self.assertEqual(terminal.computeNewText(old, new, "characters"), ["46%"])
		self.assertEqual(terminal.computeNewText(old, new, "lines"), ["Descargando 46%"])

	def test_texto_anadido_al_final_de_la_linea(self):
		self.assertEqual(terminal.computeNewText(["C:\\>"], ["C:\\> dir"]), [" dir"])

	def test_lineas_solo_con_espacios_son_vacias(self):
		# #17689: las líneas con solo espacios no se leen.
		self.assertEqual(terminal.computeNewText(["a"], ["a", "     ", "\t"]), [])

	def test_limite_de_lineas(self):
		lines = [f"línea {i}" for i in range(500)]
		out = terminal.limitLines(lines, 60)
		self.assertEqual(len(out), 60)
		self.assertEqual(out[-1], "línea 499")
		huge = ["x" * 5000] * 10
		self.assertLessEqual(sum(len(x) for x in terminal.limitLines(huge, 100)), 20000)

	def test_cola_de_caracteres_y_contrasenas(self):
		spoken = []
		with mock.patch("tiresias.typing_echo.onTypedCharacter", lambda obj, ch: spoken.append(ch)):
			terminal._typedQueue.clear()
			terminal.queueTypedCharacter(None, "l")
			terminal.queueTypedCharacter(None, "s")
			# La consola muestra lo escrito: se anuncia como eco y no se repite.
			self.assertEqual(terminal.consumeTypedCharacters([" ls"]), [])
			self.assertEqual(spoken, ["l", "s"])
			# Contraseña: lo escrito no aparece y la salida se lee normal.
			terminal.queueTypedCharacter(None, "x")
			self.assertEqual(terminal.consumeTypedCharacters(["Acceso denegado"]), ["Acceso denegado"])
			self.assertEqual(spoken, ["l", "s"])
			terminal._typedQueue.clear()

	def test_texto_de_consola_y_cursor(self):
		from tiresias import console_reader

		screen = console_reader.ConsoleScreen(["hola", "C:\\>dir"], (7, 1), 80)
		self.assertEqual(console_reader.ConsoleScreen.fromDict(screen.toDict()), screen)
		obj = FakeObj(role=Role.TERMINAL)
		with mock.patch("tiresias.console_reader.readScreen", return_value=screen):
			info = terminal.ConsoleTextInfo(obj, textinfo.POSITION_CARET)
			self.assertEqual(info.offsets, (12, 12))
			info.expand(textinfo.UNIT_LINE)
			self.assertEqual(info.text.strip(), "C:\\>dir")

	def test_rol_terminal(self):
		self.assertEqual(terminal.Terminal._get_role(FakeObj()), Role.TERMINAL)


# ====================================================================== MSAA / IA2
class MSAATests(unittest.TestCase):
	def test_atributos_ia2(self):
		attrs = msaa.parseIA2Attributes(r"level:2;xml-roles:heading;placeholder:a\;b;sort:ascending")
		self.assertEqual(attrs["level"], "2")
		self.assertEqual(attrs["placeholder"], "a;b")
		self.assertEqual(attrs["sort"], "ascending")
		self.assertEqual(msaa.parseIA2Attributes(""), {})

	def test_tablas_de_roles(self):
		for table in (_MSAA_ROLES, _IA2_ROLES):
			for key, role in table.items():
				self.assertIsInstance(role, Role, key)
		self.assertEqual(_MSAA_ROLES[msaa.ROLE_TEXT], Role.EDITABLETEXT)
		self.assertEqual(_IA2_ROLES[msaa.IA2_ROLE_PARAGRAPH], Role.PARAGRAPH)

	def test_interfaces_ia2(self):
		# Orden de la tabla virtual de IAccessible2 1.3.
		names = [m[1].replace("_get_", "") for m in msaa.IAccessible2._methods_]
		self.assertEqual(names.index("role"), 3)
		self.assertEqual(names[-1], "attributes")
		text = [m[1].replace("_get_", "") for m in msaa.IAccessibleText._methods_]
		self.assertEqual(text.index("caretOffset"), 2)
		self.assertEqual(text.index("nCharacters"), 14)

	def test_objeto_de_ventana_inexistente(self):
		self.assertIsNone(msaa.accessibleObjectFromWindow(0))
		self.assertEqual(msaa.windowFromAccessibleObject(None), 0)


class EditWindowTests(unittest.TestCase):
	"""Campo EDIT de Win32 creado en este proceso (oculto)."""

	def setUp(self):
		user32 = ctypes.windll.user32
		user32.CreateWindowExW.restype = wintypes.HWND
		user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
		ES_MULTILINE = 0x4
		self.hwnd = user32.CreateWindowExW(0, "EDIT", "Primera frase. Segunda.\r\nOtra línea", ES_MULTILINE, 0, 0, 300, 200, None, None, None, None)
		self.assertTrue(self.hwnd)

	def tearDown(self):
		ctypes.windll.user32.DestroyWindow.argtypes = [wintypes.HWND]
		ctypes.windll.user32.DestroyWindow(self.hwnd)

	def _obj(self):
		obj = FakeObj(role=Role.EDITABLETEXT)
		obj._get_windowHandle = lambda: self.hwnd
		obj._get_windowClassName = lambda: "Edit"
		obj.__class__ = type("EditFake", (FakeObj,), {"_get_windowHandle": lambda s: self.hwnd, "_get_windowClassName": lambda s: "Edit"})
		return obj

	def test_clase_de_edicion(self):
		self.assertTrue(win32ctl.isEditClass("Edit"))
		self.assertTrue(win32ctl.isEditClass("WindowsForms10.EDIT.app.0.141b42a_r9_ad1"))
		self.assertTrue(win32ctl.isEditClass("TMemo"))
		self.assertFalse(win32ctl.isEditClass("Button"))

	def test_texto_cursor_y_lineas(self):
		obj = self._obj()
		self.assertTrue(win32ctl.editSetSelection(self.hwnd, 25, 25))
		self.assertEqual(win32ctl.editGetSelection(self.hwnd), (25, 25))
		info = EditWindowTextInfo(obj, textinfo.POSITION_CARET)
		self.assertEqual(info.offsets, (25, 25))
		info.expand(textinfo.UNIT_LINE)
		self.assertEqual(info.text, "Otra línea")
		first = EditWindowTextInfo(obj, textinfo.POSITION_FIRST)
		first.expand(textinfo.UNIT_SENTENCE)
		self.assertEqual(first.text, "Primera frase. ")
		first.collapse(end=True)
		first.updateCaret()
		self.assertEqual(win32ctl.editGetSelection(self.hwnd), (15, 15))


# ====================================================================== elección de API
class APIChoiceTests(unittest.TestCase):
	def tearDown(self):
		api_choice.invalidate()

	def test_ventana_nula_y_propia(self):
		self.assertEqual(api_choice.chooseAPI(0), api_choice.API_UIA)
		user32 = ctypes.windll.user32
		user32.CreateWindowExW.restype = wintypes.HWND
		user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
		hwnd = user32.CreateWindowExW(0, "STATIC", "x", 0, 0, 0, 10, 10, None, None, None, None)
		try:
			# Las ventanas del propio Tiresias se leen siempre con MSAA (como NVDA):
			# UIA en el mismo proceso repetía decenas de eventos por cada flecha
			# en los cuadros combinados de las Opciones (0,65 s de retraso).
			self.assertEqual(api_choice.chooseAPI(hwnd), api_choice.API_MSAA)
			self.assertEqual(api_choice.cachedAPI(hwnd), api_choice.API_MSAA)
		finally:
			user32.DestroyWindow(hwnd)

	def test_decision_por_clase(self):
		self.assertEqual(api_choice._decide(1, "SysListView32"), api_choice.API_MSAA)
		self.assertEqual(api_choice._decide(1, "Chrome_RenderWidgetHostHWND"), api_choice.API_UIA)
		self.assertEqual(api_choice._decide(1, "Button"), api_choice.API_UIA)
		conf["objects"]["msaaClasses"] = ["MiClase"]
		conf["objects"]["uiaClasses"] = ["SysListView32"]
		try:
			self.assertEqual(api_choice._decide(1, "MiClase"), api_choice.API_MSAA)
			self.assertEqual(api_choice._decide(1, "SysListView32"), api_choice.API_UIA)
		finally:
			conf["objects"]["msaaClasses"] = []
			conf["objects"]["uiaClasses"] = []

	def test_consola_clasica(self):
		old = conf["uia"]["preferUIAForConsoles"]
		try:
			conf["uia"]["preferUIAForConsoles"] = False
			self.assertEqual(api_choice._decide(1, "ConsoleWindowClass"), api_choice.API_MSAA)
			conf["uia"]["preferUIAForConsoles"] = True
			self.assertNotEqual(api_choice._decide(1, "ConsoleWindowClass"), api_choice.API_MSAA)
		finally:
			conf["uia"]["preferUIAForConsoles"] = old


# ====================================================================== Java Access Bridge
class JABTests(unittest.TestCase):
	def test_roles_y_estados(self):
		self.assertEqual(mapRole("push button"), Role.BUTTON)
		self.assertEqual(mapRole("password text"), Role.PASSWORDEDIT)
		self.assertEqual(mapRole("algo raro"), Role.UNKNOWN)
		st = parseStates("enabled,focusable,visible,showing,focused,editable,multi line")
		self.assertIn(State.FOCUSED, st)
		self.assertIn(State.MULTILINE, st)
		self.assertNotIn(State.UNAVAILABLE, st)
		self.assertIn(State.UNAVAILABLE, parseStates("focusable,visible,showing"))
		self.assertIn(State.COLLAPSED, parseStates("enabled,showing,expandable"))

	def test_estructuras(self):
		# Tamaños de las estructuras de AccessBridgePackages.h (wchar_t de 2 bytes).
		self.assertEqual(ctypes.sizeof(jab.AccessibleContextInfo), 2 * (1024 * 2 + 256 * 4) + 4 * 6 + 4 * 5)
		self.assertEqual(ctypes.sizeof(jab.AccessibleTextInfo), 12)

	def test_rutas_candidatas(self):
		paths_ = jab.candidateDllPaths([r"C:\MiApp\jre\bin"])
		self.assertTrue(paths_[0].lower().startswith(r"c:\miapp\jre\bin"))
		self.assertTrue(all(p.endswith(jab.DLL_NAME) for p in paths_))

	def test_activar_con_archivo_de_propiedades(self):
		tmp = os.path.join(_TMP, "accessibility.properties")
		with mock.patch.object(jab, "PROPERTIES_FILE", tmp), mock.patch.object(jab, "findJabswitch", return_value=""):
			self.assertFalse(jab.isBridgeEnabled())
			with open(tmp, "w", encoding="latin-1") as f:
				f.write("#assistive_technologies=com.sun.java.accessibility.AccessBridge\notra=1\n")
			self.assertFalse(jab.isBridgeEnabled())
			self.assertTrue(jab.enableBridge())
			self.assertTrue(jab.isBridgeEnabled())
			with open(tmp, encoding="latin-1") as f:
				self.assertIn("otra=1", f.read())
			self.assertTrue(jab.disableBridge())
			self.assertFalse(jab.isBridgeEnabled())

	def test_sin_puente_no_es_ventana_java(self):
		with mock.patch.object(jab, "load", return_value=False), mock.patch.object(jab, "_maybeAskToEnable"):
			self.assertFalse(jab.isJavaWindow(12345))


# ====================================================================== sistema y bloqueo
class SystemTests(unittest.TestCase):
	def tearDown(self):
		system.invalidateLockCache()

	def test_bloqueo(self):
		inLock = FakeObj("Pantalla de bloqueo", role=Role.WINDOW, pid=1)
		other = FakeObj("Documento secreto", role=Role.DOCUMENT, pid=2)
		names = {1: "lockapp", 2: "winword"}
		with mock.patch.object(system, "isLockScreenActive", return_value=True), mock.patch("tiresias.winapi.getProcessName", side_effect=lambda pid: names.get(pid, "")):
			self.assertFalse(system.isSecureObject(inLock))
			self.assertTrue(system.isSecureObject(other))
			self.assertIsNone(system.filterSecure(other))
			self.assertFalse(system.isSecureObject(FakeObj(role=Role.DESKTOPPANE, pid=2)))
		with mock.patch.object(system, "isLockScreenActive", return_value=False):
			self.assertFalse(system.isSecureObject(other))

	def test_navegador_no_sale_del_bloqueo(self):
		from tiresias import api

		other = FakeObj("Documento secreto", role=Role.DOCUMENT, pid=2)
		before = api._navigatorObject
		with mock.patch.object(system, "isSecureObject", return_value=True):
			api.setNavigatorObject(other)
		self.assertIs(api._navigatorObject, before)

	def test_estado_de_sesion(self):
		# En la sesión de pruebas el equipo no está bloqueado.
		self.assertIn(system.isSessionLocked(), (False, None))
		self.assertIsInstance(system.getScreenReaderFlag(), bool)

	def test_valores_de_tecnologia_de_asistencia(self):
		vals = system._atValues()
		self.assertEqual(vals["SimpleProfile"][1], "screenreader")
		self.assertTrue(vals["StartExe"][1])


# ====================================================================== listas y diálogos
class ListAndDialogTests(unittest.TestCase):
	def test_columnas(self):
		class Row(RowWithColumns, FakeObj):
			def columnData(self):
				return [("Nombre", "a.txt"), ("Tamaño", "3 KB"), ("Tipo", "")]

		row = Row("a.txt", role=Role.LISTITEM)
		conf["documentFormatting"]["reportTableHeaders"] = True
		self.assertEqual(row.description, "Tamaño: 3 KB")
		self.assertEqual(row._formatColumn("Tipo", ""), "Tipo: en blanco")
		conf["documentFormatting"]["reportTableHeaders"] = False
		try:
			self.assertEqual(row._formatColumn("Tamaño", "3 KB"), "3 KB")
		finally:
			conf["documentFormatting"]["reportTableHeaders"] = True
		spoken = []
		with mock.patch("tiresias.speech.speakMessage", side_effect=spoken.append), mock.patch("tiresias.objects.listview._repeatCount", return_value=0):
			row._speakColumn(1)
			row._speakColumn(5)
		self.assertEqual(spoken[0], "Tamaño: 3 KB")
		self.assertIn("6", spoken[1])

	def test_elementos_seleccionados(self):
		items = [FakeObj("uno", Role.LISTITEM, {State.SELECTED}), FakeObj("dos", Role.LISTITEM), FakeObj("tres", Role.LISTITEM, {State.SELECTED})]
		lst = FakeObj("Lista", Role.LIST, children=items)
		self.assertEqual(behaviors.selectedItemNames(lst), ["uno", "tres"])
		spoken = []
		with mock.patch("tiresias.speech.speakMessage", side_effect=spoken.append):
			behaviors.reportSelectedItems(lst)
			behaviors.reportSelectedItems(FakeObj("Vacía", Role.LIST))
		self.assertIn("2 seleccionados", spoken[0])
		self.assertIn("Ningún", spoken[1])

	def test_texto_de_dialogo(self):
		children = [
			FakeObj("¿Desea guardar los cambios?", Role.STATICTEXT),
			FakeObj("Nombre:", Role.STATICTEXT),
			FakeObj("Nombre:", Role.EDITABLETEXT, {State.FOCUSABLE}),
			FakeObj("", Role.PANE, children=[FakeObj("Se perderán.", Role.STATICTEXT)]),
			FakeObj("Guardar", Role.BUTTON, {State.FOCUSABLE}),
		]
		dlg = FakeObj("Bloc de notas", Role.DIALOG, children=children)
		self.assertEqual(behaviors.collectDialogText(dlg), "¿Desea guardar los cambios? Se perderán.")

	def test_toast_sin_repeticion(self):
		spoken = []
		toast = FakeObj("Nuevo correo", Role.WINDOW, children=[FakeObj("De: Ana", Role.STATICTEXT)])
		with mock.patch("tiresias.speech.speak", side_effect=lambda seq, **kw: spoken.append(seq)), mock.patch("tiresias.audio.tones.playSound"):
			behaviors._lastToast = ("", 0.0)
			behaviors.reportToast(toast)
			behaviors.reportToast(toast)
		self.assertEqual(len(spoken), 1)
		self.assertIn("De: Ana", spoken[0][0])


class VirtualCaretTests(unittest.TestCase):
	def test_cursor_virtual_sigue_los_cambios(self):
		class Field(behaviors.EditableTextNoCaret, FakeObj):
			pass

		f = Field("Campo", Role.EDITABLETEXT, value="hola")
		behaviors._virtualCarets.clear()
		st = f._state()
		self.assertEqual(st, ["hola", 4])
		st[1] = 2
		f._v = "hoXla"
		self.assertEqual(f._syncValue(), ["hoXla", 3])


if __name__ == "__main__":
	unittest.main()
