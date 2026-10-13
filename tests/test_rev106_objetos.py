"""Pruebas de la revisión 1.0.6 (objetos, comportamientos y APIs de accesibilidad).

- Alt+flechas (frases) en los campos de edición: una sola orden; en los
  cuadros combinados (también en su campo de edición) y en los campos con
  lista desplegable la tecla va a la aplicación; sin cursor, también.
- Control+flechas arriba y abajo (párrafo propio) sin cursor: la tecla no se pierde.
- Lectura de la selección de una lista: nombres con límite y total real.
- Órdenes de las filas con columnas (Control+Tiresias+número, Control+Alt+flechas).
- ``fileNameFromURL`` descarta las URL ``javascript:``.
- ``TextInfo.getFormatInfo`` admite ``keys`` también en la clase base.

No se envían teclas reales: los gestos son simulados.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev106_objetos -v``
"""

from __future__ import annotations

import ast
import inspect
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_rev106_objetos_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()

from tiresias import a11y  # noqa: E402,F401  (registra las opciones)
from tiresias import textinfo  # noqa: E402
from tiresias.a11y import ia2_bridge, win32ctl  # noqa: E402
from tiresias.objects import behaviors, listview  # noqa: E402
from tiresias.objects.base import AccObject  # noqa: E402
from tiresias.objects.roles import Role, State  # noqa: E402


class FakeGesture:
	def __init__(self, key: str, modifiers=()) -> None:
		self.mainKeyName = key
		self.modifierNames = list(modifiers)
		self.identifiers = ["kb:" + "+".join([*modifiers, key])]
		self.send = mock.MagicMock()


class _MemText(textinfo.OffsetsTextInfo):
	"""Texto en memoria con el cursor en el propio objeto."""

	def _getStoryText(self) -> str:
		return self.obj._text

	def _getCaretOffset(self) -> int:
		return self.obj._caret

	def _setCaretOffset(self, offset: int) -> None:
		self.obj._caret = offset


class _NoSentenceText(_MemText):
	def move(self, unit, direction, endPoint=None):
		if unit == textinfo.UNIT_SENTENCE:
			raise NotImplementedError
		return super().move(unit, direction, endPoint)


class FakeParent(AccObject):
	def __init__(self, role) -> None:
		super().__init__()
		self._r = role

	def _get_role(self):
		return self._r

	def _get_appModule(self):
		return None


class FakeEdit(behaviors.EditableTextWithCaret):
	TextInfo = _MemText

	def __init__(self, text="", caret=0, role=Role.EDITABLETEXT, states=(State.EDITABLE,), parent=None) -> None:
		super().__init__()
		self._text, self._caret, self._r, self._s, self._p = text, caret, role, set(states), parent

	def _get_role(self):
		return self._r

	def _get_states(self):
		return set(self._s)

	def _get_parent(self):
		return self._p

	def _get_appModule(self):
		return None

	def _get_windowClassName(self):
		return ""


class _SpeechPatches(unittest.TestCase):
	"""Sustituye la voz, la presentación y la revisión por simulacros."""

	def setUp(self) -> None:
		from tiresias import presentation, review, speech
		from tiresias.audio import tones

		self.speakTextInfo = self._patch(presentation, "speakTextInfo")
		self._patch(review, "handleCaretMove")
		self._patch(speech, "cancelSpeech")
		self.speakMessage = self._patch(speech, "speakMessage")
		self.speakSpelling = self._patch(speech, "speakSpelling")
		self.playSound = self._patch(tones, "playSound")

	def _patch(self, target, name):
		p = mock.patch.object(target, name)
		m = p.start()
		self.addCleanup(p.stop)
		return m


# ====================================================================== frases
class SentenceScriptTests(_SpeechPatches):
	TEXT = "Hola mundo. Adiós amigo. Fin."

	def test_una_sola_orden_con_descripcion(self) -> None:
		tree = ast.parse(inspect.getsource(behaviors))
		cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "EditableText")
		names = [f.name for f in cls.body if isinstance(f, ast.FunctionDef)]
		self.assertEqual(names.count("script_caret_moveBySentence"), 1)
		func = behaviors.EditableText.script_caret_moveBySentence
		self.assertTrue(func.__doc__)
		self.assertEqual(func.category, behaviors.CAT_TEXT)
		from tiresias.baseobject import normalizeGestureId

		gestures = dict(behaviors.EditableText.iterClassGestures())
		self.assertEqual(gestures[normalizeGestureId("kb:alt+downArrow")], "caret_moveBySentence")
		self.assertEqual(gestures[normalizeGestureId("kb:alt+upArrow")], "caret_moveBySentence")

	def test_en_texto_mueve_por_frase(self) -> None:
		obj = FakeEdit(self.TEXT, 0, states=(State.EDITABLE, State.MULTILINE))
		g = FakeGesture("downArrow".lower(), ("alt",))
		obj.script_caret_moveBySentence(g)
		g.send.assert_not_called()
		self.assertEqual(obj._caret, self.TEXT.index("Adiós"))
		self.speakTextInfo.assert_called_once()
		self.assertEqual(self.speakTextInfo.call_args[0][1], textinfo.UNIT_SENTENCE)
		# Y hacia atrás vuelve al principio.
		obj.script_caret_moveBySentence(FakeGesture("uparrow", ("alt",)))
		self.assertEqual(obj._caret, 0)

	def test_ultima_frase_suena_el_limite(self) -> None:
		start = self.TEXT.index("Fin")
		obj = FakeEdit(self.TEXT, start, states=(State.EDITABLE, State.MULTILINE))
		g = FakeGesture("downarrow", ("alt",))
		obj.script_caret_moveBySentence(g)
		g.send.assert_not_called()
		self.assertEqual(obj._caret, start)
		self.playSound.assert_called_once_with("boundaryEnd")

	def test_en_cuadro_combinado_envia_la_tecla(self) -> None:
		obj = FakeEdit(self.TEXT, 0, role=Role.COMBOBOX)
		g = FakeGesture("downarrow", ("alt",))
		obj.script_caret_moveBySentence(g)
		g.send.assert_called_once()
		self.assertEqual(obj._caret, 0)
		self.speakTextInfo.assert_not_called()

	def test_en_el_campo_de_un_combo_editable_envia_la_tecla(self) -> None:
		# El campo del cuadro de búsqueda de Tiresias: Alt+Flecha abajo abre la lista.
		obj = FakeEdit(self.TEXT, 0, parent=FakeParent(Role.COMBOBOX))
		g = FakeGesture("downarrow", ("alt",))
		obj.script_caret_moveBySentence(g)
		g.send.assert_called_once()
		self.assertEqual(obj._caret, 0)

	def test_campo_con_lista_desplegable_envia_la_tecla(self) -> None:
		obj = FakeEdit(self.TEXT, 0, states=(State.EDITABLE, State.HASPOPUP, State.COLLAPSED))
		g = FakeGesture("downarrow", ("alt",))
		obj.script_caret_moveBySentence(g)
		g.send.assert_called_once()

	def test_multilinea_con_popup_sigue_moviendo_por_frase(self) -> None:
		obj = FakeEdit(self.TEXT, 0, states=(State.EDITABLE, State.MULTILINE, State.HASPOPUP))
		g = FakeGesture("downarrow", ("alt",))
		obj.script_caret_moveBySentence(g)
		g.send.assert_not_called()
		self.assertEqual(obj._caret, self.TEXT.index("Adiós"))

	def test_sin_cursor_envia_la_tecla(self) -> None:
		obj = FakeEdit(self.TEXT, 0, states=(State.EDITABLE, State.MULTILINE))
		obj._getCaretInfo = lambda: None
		g = FakeGesture("downarrow", ("alt",))
		obj.script_caret_moveBySentence(g)
		g.send.assert_called_once()
		self.speakTextInfo.assert_not_called()

	def test_unidad_no_implementada_envia_la_tecla(self) -> None:
		obj = FakeEdit(self.TEXT, 0, states=(State.EDITABLE, State.MULTILINE))
		obj.TextInfo = _NoSentenceText
		g = FakeGesture("downarrow", ("alt",))
		obj.script_caret_moveBySentence(g)
		g.send.assert_called_once()
		self.assertEqual(obj._caret, 0)

	def test_en_consola_envia_la_tecla(self) -> None:
		from tiresias.objects.terminal import Terminal

		cls = type("FakeTerminalEdit", (Terminal, FakeEdit), {})
		obj = cls(self.TEXT, 0)
		g = FakeGesture("downarrow", ("alt",))
		obj.script_caret_moveBySentence(g)
		g.send.assert_called_once()


class ParagraphScriptTests(_SpeechPatches):
	def test_parrafo_propio_sin_cursor_envia_la_tecla(self) -> None:
		obj = FakeEdit("uno\ndos", 0, states=(State.EDITABLE, State.MULTILINE))
		obj._getCaretInfo = lambda: None
		g = FakeGesture("downarrow", ("control",))
		with mock.patch.object(textinfo, "paragraphStyle", return_value="singleLineBreak"):
			obj.script_caret_moveByParagraph(g)
		g.send.assert_called_once()

	def test_parrafo_propio_mueve_el_cursor(self) -> None:
		obj = FakeEdit("uno\ndos\ntres", 0, states=(State.EDITABLE, State.MULTILINE))
		g = FakeGesture("downarrow", ("control",))
		with mock.patch.object(textinfo, "paragraphStyle", return_value="singleLineBreak"):
			obj.script_caret_moveByParagraph(g)
		g.send.assert_not_called()
		self.assertEqual(obj._caret, 4)


# ====================================================================== selección de listas
class FakeList(AccObject):
	def __init__(self, names, total=None, cls="") -> None:
		super().__init__()
		self._names, self._total, self._cls = names, total, cls
		self.limits: list = []

	def _get_role(self):
		return Role.LIST

	def _get_appModule(self):
		return None

	def _get_windowClassName(self):
		return self._cls

	def _selectedItemNames(self, limit=None):
		self.limits.append(limit)
		return self._names[:limit] if limit is not None else list(self._names)

	def _selectedItemCount(self):
		return self._total


class SelectedItemsTests(_SpeechPatches):
	def test_nombres_con_limite_y_total_real(self) -> None:
		names = [f"archivo{i}" for i in range(2000)]
		lst = FakeList(names, total=2000)
		behaviors.reportSelectedItems(lst)
		self.assertEqual(lst.limits, [500])
		msg = self.speakMessage.call_args[0][0]
		self.assertTrue(msg.startswith("2000 seleccionados: archivo0, archivo1"), msg)
		self.assertTrue(msg.endswith("y 1985 más"), msg)

	def test_sin_total_usa_los_nombres(self) -> None:
		lst = FakeList(["a", "b"], total=None)
		behaviors.reportSelectedItems(lst)
		self.assertEqual(self.speakMessage.call_args[0][0], "2 seleccionados: a, b")

	def test_uno_seleccionado(self) -> None:
		behaviors.reportSelectedItems(FakeList(["solo"], total=1))
		self.assertEqual(self.speakMessage.call_args[0][0], "Seleccionado: solo")

	def test_ninguno_y_sin_lista(self) -> None:
		behaviors.reportSelectedItems(FakeList([], total=0))
		self.assertEqual(self.speakMessage.call_args[0][0], "Ningún elemento seleccionado")
		behaviors.reportSelectedItems(None)
		self.assertEqual(self.speakMessage.call_args[0][0], "No hay ninguna lista")

	def test_listview_win32_cuenta_con_lvm(self) -> None:
		lst = FakeList([], cls="SysListView32")
		lst._selectedItemCount = None
		with mock.patch.object(win32ctl, "listViewSelectedCount", return_value=7) as cnt:
			self.assertEqual(behaviors.selectedItemCount(lst), 7)
		cnt.assert_called_once()

	def test_lvm_getselectedcount(self) -> None:
		with mock.patch.object(win32ctl, "sendMessage", return_value=12) as send:
			self.assertEqual(win32ctl.listViewSelectedCount(5), 12)
		self.assertEqual(send.call_args[0][1], win32ctl.LVM_GETSELECTEDCOUNT)
		with mock.patch.object(win32ctl, "sendMessage", return_value=None):
			self.assertIsNone(win32ctl.listViewSelectedCount(5))

	def test_orden_de_la_lista_y_del_elemento(self) -> None:
		lst = FakeList(["x", "y"], total=2)

		class Item(behaviors.SelectableItem):
			def _get_parent(self):
				return lst

			def _get_role(self):
				return Role.LISTITEM

			def _get_appModule(self):
				return None

		Item().script_reportSelectedItems(FakeGesture("e", ("tiresias", "control")))
		self.assertEqual(self.speakMessage.call_args[0][0], "2 seleccionados: x, y")
		self.speakMessage.reset_mock()

		class Container(behaviors.ListContainer, FakeList):
			pass

		Container(["z"], total=1).script_reportSelectedItems(FakeGesture("e", ("tiresias", "control")))
		self.assertEqual(self.speakMessage.call_args[0][0], "Seleccionado: z")

	def test_uia_lee_solo_los_primeros_nombres(self) -> None:
		from tiresias.objects.uia import UIAObject

		class Arr:
			Length = 10000

			def __init__(self) -> None:
				self.calls = 0

			def GetElement(self, i):
				self.calls += 1
				return mock.Mock(CurrentName=f"e{i}")

		arr = Arr()
		pat = mock.Mock()
		pat.GetCurrentSelection.return_value = arr
		obj = UIAObject.__new__(UIAObject)
		obj._pattern = lambda pid, iface: pat
		self.assertEqual(obj._selectedItemNames(3), ["e0", "e1", "e2"])
		self.assertEqual(arr.calls, 3)
		self.assertEqual(obj._selectedItemCount(), 10000)
		obj._pattern = lambda pid, iface: None
		self.assertIsNone(obj._selectedItemCount())
		self.assertEqual(obj._selectedItemNames(), [])


# ====================================================================== filas con columnas
class FakeRow(listview.RowWithColumns):
	COLS = [("Nombre", "a.txt"), ("Tamaño", "3 KB"), ("Tipo", "")]

	def columnData(self):
		return list(self.COLS)

	def _get_name(self):
		return "a.txt"

	def _get_windowHandle(self):
		return 1

	def _get_appModule(self):
		return None


class RowColumnsTests(_SpeechPatches):
	def setUp(self) -> None:
		super().setUp()
		listview._columnCursor = (None, 0)
		self.repeat = self._patch(listview, "_repeatCount")
		self.repeat.return_value = 0

	def test_leer_columna_por_numero(self) -> None:
		row = FakeRow()
		row.script_readColumn(FakeGesture("2", ("tiresias", "control")))
		self.assertEqual(self.speakMessage.call_args[0][0], "Tamaño: 3 KB")
		row.script_readColumn(FakeGesture("3", ("tiresias", "control")))
		self.assertEqual(self.speakMessage.call_args[0][0], "Tipo: en blanco")
		row.script_readColumn(FakeGesture("0", ("tiresias", "control")))
		self.assertEqual(self.speakMessage.call_args[0][0], "No hay columna 10")

	def test_dos_pulsaciones_deletrea(self) -> None:
		self.repeat.return_value = 1
		FakeRow().script_readColumn(FakeGesture("1", ("tiresias", "control")))
		self.speakSpelling.assert_called_once_with("a.txt")

	def test_columna_siguiente_anterior_y_extremos(self) -> None:
		row = FakeRow()
		row.script_nextColumn(FakeGesture("rightarrow", ("control", "alt")))
		self.assertEqual(self.speakMessage.call_args[0][0], "Nombre: a.txt")
		row.script_nextColumn(FakeGesture("rightarrow", ("control", "alt")))
		self.assertEqual(self.speakMessage.call_args[0][0], "Tamaño: 3 KB")
		row.script_previousColumn(FakeGesture("leftarrow", ("control", "alt")))
		self.assertEqual(self.speakMessage.call_args[0][0], "Nombre: a.txt")
		row.script_previousColumn(FakeGesture("leftarrow", ("control", "alt")))
		self.playSound.assert_called_once_with("boundary")
		row.script_lastColumn(FakeGesture("end", ("control", "alt")))
		self.assertEqual(self.speakMessage.call_args[0][0], "Tipo: en blanco")
		row.script_firstColumn(FakeGesture("home", ("control", "alt")))
		self.assertEqual(self.speakMessage.call_args[0][0], "Nombre: a.txt")

	def test_descripcion_con_las_columnas(self) -> None:
		self.assertEqual(FakeRow().description, "Tamaño: 3 KB")


# ====================================================================== varios
class VirtualCaretTests(unittest.TestCase):
	def test_cursores_virtuales_con_limite(self) -> None:
		class NoCaret(behaviors.EditableTextNoCaret):
			def __init__(self, n) -> None:
				super().__init__()
				self.runtimeId = (42, n)

			def _get_value(self):
				return "texto"

			def _get_appModule(self):
				return None

		behaviors._virtualCarets.clear()
		old = behaviors.conf["objects"]["reportMaxLength"]
		behaviors.conf["objects"]["reportMaxLength"] = False
		try:
			with mock.patch.object(AccObject, "event_gainFocus"):
				for i in range(200):
					NoCaret(i).event_gainFocus()
		finally:
			behaviors.conf["objects"]["reportMaxLength"] = old
		self.assertLessEqual(len(behaviors._virtualCarets), 50)
		self.assertIn((42, 199), behaviors._virtualCarets)


class JavaNavigationTests(unittest.TestCase):
	def test_hijos_con_el_puente_fallando(self) -> None:
		import types

		from tiresias.a11y import jab as jabApi
		from tiresias.objects.jab import JABObject

		bridge = mock.MagicMock()
		bridge.getAccessibleChildFromContext.side_effect = OSError("violación de acceso")
		info = types.SimpleNamespace(childrenCount=3, indexInParent=0)
		with mock.patch.object(jabApi, "bridge", bridge), mock.patch.object(JABObject, "info", new_callable=mock.PropertyMock, return_value=info):
			obj = JABObject(1, 2, 3)
			self.assertIsNone(obj.firstChild)
			self.assertIsNone(obj.lastChild)
			self.assertEqual(obj.children, [])
		with mock.patch.object(jabApi, "bridge", None), mock.patch.object(JABObject, "info", new_callable=mock.PropertyMock, return_value=info):
			self.assertIsNone(JABObject(1, 2, 3).firstChild)


class OverlayTests(unittest.TestCase):
	def test_mro_imposible_aun_inicia_el_modulo(self) -> None:
		app = mock.MagicMock()

		class A(AccObject):
			pass

		class B(A):
			pass

		class Obj(AccObject):
			def findOverlayClasses(self, clsList):
				clsList.extend([A, B])

			def _get_appModule(self):
				return app

		obj = Obj()
		with mock.patch("tiresias.objects.base.log"):
			obj._applyOverlays()
		self.assertIs(type(obj), Obj)
		app.event_NVDAObject_init.assert_called_once_with(obj)


class MiscTests(unittest.TestCase):
	def test_url_javascript_sin_nombre(self) -> None:
		self.assertEqual(ia2_bridge.fileNameFromURL("javascript:void(0)"), "")
		self.assertEqual(ia2_bridge.fileNameFromURL("JavaScript:alert(1)"), "")
		self.assertEqual(ia2_bridge.fileNameFromURL("https://x.org/img/foto_de_la_playa.png"), "foto de la playa")

	def test_getformatinfo_base_admite_keys(self) -> None:
		info = textinfo.StaticTextInfo(None, textinfo.POSITION_FIRST, "hola")
		self.assertEqual(info.getFormatInfo({"fontName"}), {})
		self.assertEqual(info.getFormatInfo(), {})


if __name__ == "__main__":
	unittest.main()
