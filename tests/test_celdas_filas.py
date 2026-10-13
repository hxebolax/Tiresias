"""Regresión de la 1.0.3: celdas de las filas con las flechas (vista Detalles).

En el Explorador de Windows 11, vista Detalles, las flechas derecha e izquierda
llevan el foco UIA de un archivo a sus columnas (Fecha de modificación, Tipo,
Tamaño...), que son campos de solo lectura sin cursor (``EditableTextNoCaret``).
La flecha pulsada en una celda ejecutaba el cursor virtual del campo: 40 ms
después cortaba la lectura de la celda nueva (que ya había llegado por el foco)
y decía «en blanco» o un carácter de la celda anterior. Solo se oía bien la
primera flecha (desde el archivo, que no tiene esa orden).

Aquí se recorre una fila varias veces en las dos direcciones, con la aplicación
rápida (el foco llega antes que los temporizadores) y lenta (después), y se
comprueba que se oye cada celda y nada más.

No se inyectan teclas ni se tocan programas del usuario.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="tiresias_test_celdas_")
shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
paths.setDataDir(_TMP)
paths.ensureDataDirs()

from tiresias import a11y  # noqa: E402,F401  (registra las opciones)
from tiresias import api, presentation, speech  # noqa: E402
from tiresias.input.gestures import KeyboardGesture  # noqa: E402
from tiresias.objects import behaviors, text_limits  # noqa: E402
from tiresias.objects.base import AccObject  # noqa: E402
from tiresias.objects.roles import Role, State  # noqa: E402

VK = {"rightarrow": 0x27, "leftarrow": 0x25, "uparrow": 0x26, "downarrow": 0x28, "home": 0x24, "end": 0x23}


def tearDownModule() -> None:
	shutil.rmtree(_TMP, ignore_errors=True)


# ====================================================================== objetos de prueba
class _List(AccObject):
	def _get_role(self) -> Role:
		return Role.LIST

	def _get_name(self) -> str:
		return "Vista Elementos"


class _Row(behaviors.SelectableItem):
	"""Archivo de la vista Detalles (la columna Nombre es la propia fila)."""

	def __init__(self, name: str, parent) -> None:
		super().__init__()
		self._n = name
		self._p = parent

	def _get_name(self) -> str:
		return self._n

	def _get_role(self) -> Role:
		return Role.LISTITEM

	def _get_parent(self):
		return self._p

	def _get_states(self) -> set:
		return {State.SELECTABLE, State.FOCUSABLE}

	def _get_processID(self) -> int:
		return 7

	def isSameAs(self, other) -> bool:
		return type(other) is _Row and other._n == self._n


class _Cell(behaviors.EditableTextNoCaret):
	"""Columna de un archivo: campo de solo lectura sin cursor (``UIProperty``)."""

	def __init__(self, column: str, value: str, row, readOnly: bool = True) -> None:
		super().__init__()
		self._n = column
		self._v = value
		self._p = row
		self._ro = readOnly
		self.runtimeId = (42, id(self))

	def _get_name(self) -> str:
		return self._n

	def _get_value(self) -> str:
		return self._v

	def _get_role(self) -> Role:
		return Role.EDITABLETEXT

	def _get_parent(self):
		return self._p

	def _get_states(self) -> set:
		states = {State.FOCUSABLE}
		if self._ro:
			states.add(State.READONLY)
		return states

	def _get_processID(self) -> int:
		return 7

	def isSameAs(self, other) -> bool:
		return other is self


class _FakeApp:
	"""Vista Detalles: el foco va del archivo a sus columnas con las flechas.

	``fast``: el foco llega antes que los temporizadores de Tiresias (lo normal);
	si no, después (una aplicación lenta).
	"""

	COLUMNS = (("Fecha de modificación", "07/10/2026 13:25"), ("Tipo", "Excel.CSV"), ("Tamaño", "12 KB"))

	def __init__(self, test: "RowCellsTests", names=("datos.csv", "imagen", "informe")) -> None:
		self.test = test
		self.lst = _List()
		self.rows = []
		for name in names:
			row = _Row(name, self.lst)
			cells = [row] + [_Cell(col, f"{val} {name}", row) for col, val in self.COLUMNS]
			self.rows.append(cells)
		self.r = 0
		self.c = 0
		self.pending = None

	def focusObject(self):
		return self.rows[self.r][self.c]

	def handleKey(self, key: str) -> None:
		r, c = self.r, self.c
		if key == "rightarrow":
			c = min(c + 1, len(self.rows[r]) - 1)
		elif key == "leftarrow":
			c = max(c - 1, 0)
		elif key == "downarrow":
			r = min(r + 1, len(self.rows) - 1)
		elif key == "uparrow":
			r = max(r - 1, 0)
		if (r, c) == (self.r, self.c):
			return
		rowChanged = r != self.r
		self.r, self.c = r, c
		obj = self.focusObject()

		def dispatch() -> None:
			if rowChanged:
				# El Explorador manda la selección del archivo nuevo antes que el foco.
				self.rows[r][0].event_selection()
			self.test.focus(obj)

		if self.test.fast:
			dispatch()
		else:
			self.pending = dispatch


class RowCellsTests(unittest.TestCase):
	fast = True

	def setUp(self) -> None:
		self.log: list[tuple[str, str]] = []
		self.later: list = []
		patches = [
			mock.patch.object(behaviors.queue_handler, "callLater", side_effect=self._callLater),
			mock.patch.object(presentation, "speakObject", side_effect=lambda obj, reason=None, isValid=None: self.log.append(("say", f"{obj.name} {obj.value or ''}".strip()))),
			mock.patch.object(speech, "speak", side_effect=lambda seq, *a, **k: self.log.append(("say", " ".join(str(s) for s in seq)))),
			mock.patch.object(speech, "speakMessage", side_effect=lambda text, *a, **k: self.log.append(("say", text))),
			mock.patch.object(speech, "speakText", side_effect=lambda text, *a, **k: self.log.append(("say", text))),
			mock.patch.object(speech, "speakCharacter", side_effect=lambda ch, *a, **k: self.log.append(("say", ch))),
			mock.patch.object(speech, "cancelSpeech", side_effect=lambda *a, **k: self.log.append(("cancel", ""))),
			mock.patch.object(text_limits, "maxLengthOf", return_value=None),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)
		self.addCleanup(api.setFocusObject, None, [])
		behaviors._lastSelectionEvent = ((), 0.0)
		self.app = _FakeApp(self)
		self.focus(self.app.focusObject())
		behaviors._focusChange[1] = time.monotonic() - 5

	def _callLater(self, ms, func, *args):
		self.later.append((func, args))
		return len(self.later)

	def focus(self, obj) -> None:
		api.setFocusObject(obj, [])
		obj.event_gainFocus()

	def runTimers(self) -> None:
		for _i in range(10):
			if not self.later:
				return
			pending, self.later = self.later, []
			for f, a in pending:
				f(*a)

	def press(self, key: str) -> str:
		"""Pulsa ``key`` como lo hace Tiresias con el gancho y devuelve lo que se oye."""
		self.log = []
		gesture = KeyboardGesture(VK[key], 0, True, frozenset(), key)
		gesture.send = lambda: self.app.handleKey(key)
		focus = api.getFocusObject()
		func = focus.getScript(gesture)
		# InputManager: corta la voz y ejecuta la orden, o deja pasar la tecla.
		speech.cancelSpeech()
		if func is not None:
			func(gesture)
		else:
			gesture.send()
		if self.app.pending is None:
			self.runTimers()
		else:
			# Aplicación lenta: los temporizadores de Tiresias van antes que el foco.
			self.runTimers()
			pending, self.app.pending = self.app.pending, None
			pending()
			self.runTimers()
		return self.heard()

	def heard(self) -> str:
		"""Lo que se oye: lo dicho después del último corte de la voz."""
		out: list[str] = []
		for kind, text in self.log:
			if kind == "cancel":
				out = []
			else:
				out.append(text)
		return " | ".join(out)

	# ---------------------------------------------------------------- pruebas
	def test_derecha_recorre_todas_las_columnas(self) -> None:
		self.assertEqual(self.press("rightarrow"), "Fecha de modificación 07/10/2026 13:25 datos.csv")
		self.assertEqual(self.press("rightarrow"), "Tipo Excel.CSV datos.csv")
		self.assertEqual(self.press("rightarrow"), "Tamaño 12 KB datos.csv")
		# Última columna: el Explorador no mueve el foco y no se dice nada (ni
		# «en blanco» ni un carácter del valor).
		self.assertEqual(self.press("rightarrow"), "")

	def test_izquierda_vuelve_por_todas_las_columnas(self) -> None:
		for _i in range(3):
			self.press("rightarrow")
		self.assertEqual(self.press("leftarrow"), "Tipo Excel.CSV datos.csv")
		self.assertEqual(self.press("leftarrow"), "Fecha de modificación 07/10/2026 13:25 datos.csv")
		self.assertEqual(self.press("leftarrow"), "datos.csv")
		self.assertEqual(self.press("leftarrow"), "")

	def test_ida_y_vuelta_varias_veces(self) -> None:
		expected = {
			1: "Fecha de modificación 07/10/2026 13:25 datos.csv",
			2: "Tipo Excel.CSV datos.csv",
			3: "Tamaño 12 KB datos.csv",
			0: "datos.csv",
		}
		col = 0
		for _vuelta in range(3):
			for key in ("rightarrow",) * 3 + ("leftarrow",) * 3:
				col = col + 1 if key == "rightarrow" else col - 1
				self.assertEqual(self.press(key), expected[col], f"{key} hacia la columna {col}")

	def test_las_flechas_en_una_celda_no_usan_el_cursor_virtual(self) -> None:
		self.press("rightarrow")
		self.press("rightarrow")
		self.press("leftarrow")
		said = [t for k, t in self.log if k == "say"]
		self.assertNotIn("en blanco", said)
		self.assertTrue(all(len(t) > 1 for t in said), said)
		self.assertEqual(self.later, [])

	def test_arriba_y_abajo_en_una_columna_dicen_el_archivo_y_la_celda(self) -> None:
		self.press("rightarrow")
		self.assertEqual(self.press("downarrow"), "imagen | Fecha de modificación 07/10/2026 13:25 imagen")
		self.assertEqual(self.press("downarrow"), "informe | Fecha de modificación 07/10/2026 13:25 informe")
		self.assertEqual(self.press("uparrow"), "imagen | Fecha de modificación 07/10/2026 13:25 imagen")
		# Dentro de la misma fila ya no se repite el archivo.
		self.assertEqual(self.press("rightarrow"), "Tipo Excel.CSV imagen")
		self.assertEqual(self.press("leftarrow"), "Fecha de modificación 07/10/2026 13:25 imagen")
		self.assertEqual(self.press("leftarrow"), "imagen")

	def test_abajo_en_la_columna_nombre_lee_el_archivo(self) -> None:
		self.assertEqual(self.press("downarrow"), "imagen")
		self.assertEqual(self.press("rightarrow"), "Fecha de modificación 07/10/2026 13:25 imagen")


class RowCellsSlowAppTests(RowCellsTests):
	"""El foco llega después de los temporizadores de Tiresias."""

	fast = False


class NoCaretFieldTests(unittest.TestCase):
	"""Los campos sin cursor que no son celdas siguen con su cursor virtual."""

	def setUp(self) -> None:
		self.log: list = []
		self.later: list = []
		patches = [
			mock.patch.object(behaviors.queue_handler, "callLater", side_effect=lambda ms, f, *a: self.later.append((f, a))),
			mock.patch.object(speech, "speakMessage", side_effect=lambda text, *a, **k: self.log.append(text)),
			mock.patch.object(speech, "speakCharacter", side_effect=lambda ch, *a, **k: self.log.append(ch)),
			mock.patch.object(speech, "speakText", side_effect=lambda text, *a, **k: self.log.append(text)),
			mock.patch.object(speech, "cancelSpeech"),
			mock.patch.object(presentation, "speakObject"),
			mock.patch.object(text_limits, "maxLengthOf", return_value=None),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)
		self.addCleanup(api.setFocusObject, None, [])
		dialog = AccObject()
		self.field = _Cell("Nombre", "hola", dialog, readOnly=False)
		api.setFocusObject(self.field, [])
		self.field.event_gainFocus()

	def _press(self, key: str, moveFocusTo=None) -> None:
		gesture = KeyboardGesture(VK[key], 0, True, frozenset(), key)

		def send() -> None:
			if moveFocusTo is not None:
				api.setFocusObject(moveFocusTo, [])

		gesture.send = send
		self.field.getScript(gesture)(gesture)
		pending, self.later = self.later, []
		for f, a in pending:
			f(*a)

	def test_campo_editable_lee_el_caracter(self) -> None:
		self.assertFalse(self.field._isRowCell())
		self._press("home")
		self._press("rightarrow")
		self.assertEqual(self.log, ["h", "o"])

	def test_si_la_tecla_mueve_el_foco_no_se_lee_el_campo_anterior(self) -> None:
		other = AccObject()
		self._press("rightarrow", moveFocusTo=other)
		self.assertEqual(self.log, [])


class CaretWatchFocusTests(unittest.TestCase):
	"""Campos con cursor: si la tecla mueve el foco, no se anuncia el cursor viejo."""

	def test_el_foco_cambia_antes_de_moverse_el_cursor(self) -> None:
		done = mock.Mock()
		obj = mock.Mock()
		obj._getCaretInfo.return_value = None
		behaviors._watch = {"obj": obj, "old": "b", "deadline": 0, "done": done, "selection": False, "timer": None, "focusSeq": behaviors._focusChange[0]}
		behaviors._onFocusChange(AccObject())
		self.addCleanup(api.setFocusObject, None, [])
		behaviors._pollWatch()
		done.assert_not_called()
		self.assertIsNone(behaviors._watch)

	def test_sin_cambio_de_foco_se_anuncia(self) -> None:
		done = mock.Mock()
		obj = mock.Mock()
		obj._getCaretInfo.return_value = None
		behaviors._watch = {"obj": obj, "old": "b", "deadline": 0, "done": done, "selection": False, "timer": None, "focusSeq": behaviors._focusChange[0]}
		behaviors._pollWatch()
		done.assert_called_once()


# ====================================================================== cómo se leen las celdas
from tiresias.a11y import uia_client as uc  # noqa: E402
from tiresias.objects.base import looksLikeTypeName  # noqa: E402
from tiresias.objects.uia import UIAObject  # noqa: E402


class _FakeElement:
	def __init__(self, props: dict) -> None:
		self.props = props

	def GetCachedPropertyValueEx(self, propId, ignoreDefault):
		return self.props.get(propId)

	def GetCurrentPropertyValueEx(self, propId, ignoreDefault):
		return self.props.get(propId)


class _FakeUIA(UIAObject):
	def __init__(self, props: dict) -> None:
		super().__init__(_FakeElement(props), windowHandle=0x1234)

	def _get_windowClassName(self) -> str:
		return "HwndWrapper"

	def _get_parent(self):
		return None


def _speech(obj, reason=presentation.Reason.FOCUS) -> str:
	return " ".join(presentation.getObjectSpeech(obj, reason))


class CellSpeechTests(unittest.TestCase):
	"""Celdas como en NVDA: «Tipo: Excel.CSV», sin «edición» ni «solo lectura»."""

	def setUp(self) -> None:
		self.row = _Row("datos.csv", _List())

	def test_celda_del_explorador(self) -> None:
		cell = _Cell("Tipo", "Excel.CSV", self.row)
		self.assertTrue(cell.presentAsCell)
		self.assertEqual(_speech(cell), "Tipo: Excel.CSV")

	def test_fecha_sin_marcas_invisibles(self) -> None:
		cell = _Cell("Fecha de modificación", "\u200e07/\u200e10/\u200e2026 \u200f\u200e13:25", self.row)
		self.assertEqual(_speech(cell), "Fecha de modificación: 07/10/2026 13:25")

	def test_celda_vacia_solo_dice_la_columna(self) -> None:
		# Tamaño de una carpeta.
		self.assertEqual(_speech(_Cell("Tamaño", "", self.row)), "Tamaño")

	def test_consulta_dice_celda(self) -> None:
		said = _speech(_Cell("Tipo", "Excel.CSV", self.row), presentation.Reason.QUERY)
		self.assertIn("celda", said)
		self.assertNotIn("solo lectura", said)
		self.assertNotIn("edición", said)

	def test_campo_de_solo_lectura_normal_no_cambia(self) -> None:
		field = _Cell("Ruta", "C:\\datos", AccObject())
		self.assertFalse(field.presentAsCell)
		said = _speech(field)
		self.assertIn("edición", said)
		self.assertIn("solo lectura", said)
		self.assertNotIn("Ruta:", said)

	def test_braille_de_la_celda(self) -> None:
		from tiresias.braille import presenter

		text = presenter.objectText(_Cell("Fecha", "‎07/‎10/‎2026", self.row))
		self.assertIn("Fecha", text)
		self.assertIn("07/10/2026", text)
		self.assertNotIn("‎", text)
		self.assertNotIn(presenter.STATE_BRAILLE[State.READONLY], text.split())
		field = presenter.objectText(_Cell("Ruta", "C:", AccObject()))
		self.assertIn(presenter.STATE_BRAILLE[State.READONLY], field.split())

	def test_campo_editable_dentro_de_una_fila_no_es_celda(self) -> None:
		field = _Cell("Nombre", "alfa", self.row, readOnly=False)
		self.assertFalse(field.presentAsCell)
		self.assertIn("edición", _speech(field))


class TypeNameDescriptionTests(unittest.TestCase):
	"""DataGridView: la ayuda «DataGridViewTextBoxCell(DataGridViewCell)» no se lee."""

	def test_nombres_de_tipo(self) -> None:
		self.assertTrue(looksLikeTypeName("DataGridViewTextBoxCell(DataGridViewCell)"))
		self.assertTrue(looksLikeTypeName("DataGridViewCheckBoxCell(DataGridViewCell)"))
		self.assertTrue(looksLikeTypeName("System.Windows.Forms.DataGridViewCell"))
		self.assertTrue(looksLikeTypeName("MiClase", "MiClase"))

	def test_textos_para_el_usuario(self) -> None:
		for text in ("Guardar", "PowerPoint", "Abre el archivo (Ctrl+O)", "Nombre del archivo", "Windows", "Tamaño(KB)", "Size(KB)", "Total(MB)", ""):
			self.assertFalse(looksLikeTypeName(text), text)

	def test_descripcion_uia_filtrada(self) -> None:
		cell = _FakeUIA({uc.P_CONTROLTYPE: uc.CT_DATAITEM, uc.P_NAME: "Tipo Fila 0", uc.P_HELPTEXT: "DataGridViewTextBoxCell(DataGridViewCell)"})
		self.assertEqual(cell.description, "")
		self.assertNotIn("DataGridView", _speech(cell))

	def test_descripcion_uia_normal_se_conserva(self) -> None:
		btn = _FakeUIA({uc.P_CONTROLTYPE: uc.CT_BUTTON, uc.P_NAME: "Abrir", uc.P_HELPTEXT: "Abre un archivo"})
		self.assertEqual(btn.description, "Abre un archivo")

	def test_descripcion_igual_a_la_clase(self) -> None:
		obj = _FakeUIA({uc.P_CONTROLTYPE: uc.CT_CUSTOM, uc.P_NAME: "x", uc.P_CLASSNAME: "FancyPanel", uc.P_HELPTEXT: "FancyPanel"})
		self.assertEqual(obj.description, "")


class WPFCellTests(unittest.TestCase):
	"""DataGridCell de WPF: tipo «personalizado» con GridItem/TableItem → celda."""

	def _cell(self, extra=None):
		props = {uc.P_CONTROLTYPE: uc.CT_CUSTOM, uc.P_NAME: "Texto", uc.P_CLASSNAME: "DataGridCell", uc.P_LOCALIZEDCONTROLTYPE: "personalizado", uc.P_ISINVOKEPATTERNAVAILABLE: True}
		props.update(extra or {})
		return _FakeUIA(props)

	def test_con_griditem_es_celda(self) -> None:
		cell = self._cell({uc.P_ISGRIDITEMPATTERNAVAILABLE: True})
		self.assertEqual(cell.role, Role.TABLECELL)
		said = _speech(cell)
		self.assertTrue(said.startswith("Texto"), said)
		self.assertNotIn("personalizado", said)
		self.assertNotIn("pulsable", said)

	def test_con_tableitem_es_celda(self) -> None:
		self.assertEqual(self._cell({uc.P_ISTABLEITEMPATTERNAVAILABLE: True}).role, Role.TABLECELL)

	def test_personalizado_sin_patron_de_celda_no_cambia(self) -> None:
		obj = self._cell()
		self.assertEqual(obj.role, Role.CUSTOM)
		said = _speech(obj)
		self.assertIn("personalizado", said)
		self.assertIn("pulsable", said)


if __name__ == "__main__":
	unittest.main()
