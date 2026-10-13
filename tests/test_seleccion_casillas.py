"""Regresiones de la 1.0.3 respecto a la 1.0.1: casillas, selección y listas.

- Casillas con MSAA (ventanas propias de Tiresias desde la 1.0.2): tras
  Espacio se decía «pulsado» y luego «marcado no pulsado» o «no pulsado no
  marcado». Ahora solo el estado nuevo, una vez.
- Explorador: cada archivo se leía «alfa selección múltiple 1 de 5»; ahora
  «alfa 1 de 5» («selección múltiple» solo al entrar en la lista).
- Selección: lo que acompaña a las flechas no se anuncia aparte; Control+Espacio
  y los cambios en otros elementos sí («seleccionado», «X no seleccionado»).
- Listas SysListView32 con MSAA: «1 de 4», no «1 de 5» (el encabezado no cuenta).
- Árboles SysTreeView32 con MSAA: «Rama A contraído 1 de 3 nivel 1», no «Rama A 0».
- Botones de opción UIA: «marcado».

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

_TMP = tempfile.mkdtemp(prefix="tiresias_test_selcas_")
shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
paths.setDataDir(_TMP)
paths.ensureDataDirs()

from tiresias import a11y  # noqa: E402,F401  (registra las opciones)
from tiresias import api, presentation  # noqa: E402
from tiresias.a11y import msaa, win32ctl  # noqa: E402
from tiresias.a11y import uia_client as uc  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.objects import behaviors, iaccessible, listview  # noqa: E402
from tiresias.objects.base import AccObject  # noqa: E402
from tiresias.objects.roles import Role, State  # noqa: E402
from tiresias.objects.uia import UIAObject  # noqa: E402


def tearDownModule() -> None:
	shutil.rmtree(_TMP, ignore_errors=True)


# ====================================================================== objetos de prueba
class _FakeElement:
	def __init__(self, props: dict) -> None:
		self.props = props

	def GetCachedPropertyValueEx(self, propId, ignoreDefault):
		return self.props.get(propId)

	def GetCurrentPropertyValueEx(self, propId, ignoreDefault):
		return self.props.get(propId)


class _FakeUIA(UIAObject):
	def __init__(self, props: dict, windowClass: str = "DirectUIHWND") -> None:
		super().__init__(_FakeElement(props), windowHandle=0x1234)
		self._wc = windowClass

	def _get_windowClassName(self) -> str:
		return self._wc


class _FakeMSAA(iaccessible.IAccessibleObject):
	"""Objeto MSAA con rol, estados y clase de ventana fijos."""

	def __init__(self, role: Role, bits: int, windowClass: str = "Button", childId: int = 0) -> None:
		super().__init__(object(), childId, 0x4321)
		self._r = role
		self._bits = bits
		self._wc = windowClass

	def _get_role(self) -> Role:
		return self._r

	def _get_IAccessibleStates(self) -> int:
		return self._bits

	def _get_IA2States(self) -> int:
		return 0

	def _get_IA2Attributes(self) -> dict:
		return {}

	def _get_windowClassName(self) -> str:
		return self._wc


def _changeSpeech(obj, oldStates: set, newStates: set) -> list[str]:
	"""Lo que se dice al cambiar de ``oldStates`` a ``newStates`` (evento stateChange)."""
	return presentation.getStatesText(obj, newStates, obj.role, presentation.Reason.CHANGE, changedOnly=newStates - oldStates, removed=oldStates - newStates)


# ====================================================================== casillas (MSAA)
class CheckboxMSAATests(unittest.TestCase):
	def test_la_casilla_pulsada_no_dice_pulsado(self) -> None:
		# Espacio mantenido en una casilla Win32: MSAA marca STATE_PRESSED.
		box = _FakeMSAA(Role.CHECKBOX, msaa.STATE_PRESSED | msaa.STATE_FOCUSED)
		self.assertNotIn(State.PRESSED, box.states)

	def test_espacio_marca_y_dice_solo_marcado(self) -> None:
		before = _FakeMSAA(Role.CHECKBOX, msaa.STATE_FOCUSED).states
		down = _FakeMSAA(Role.CHECKBOX, msaa.STATE_FOCUSED | msaa.STATE_PRESSED).states
		up = _FakeMSAA(Role.CHECKBOX, msaa.STATE_FOCUSED | msaa.STATE_CHECKED).states
		box = _FakeMSAA(Role.CHECKBOX, 0)
		# Al pulsar: nada (antes, «pulsado»).
		self.assertEqual(_changeSpeech(box, before, down), [])
		# Al soltar: el estado nuevo y nada más (antes, «marcado no pulsado»).
		self.assertEqual(_changeSpeech(box, down, up), ["marcado"])

	def test_espacio_desmarca_y_dice_solo_no_marcado(self) -> None:
		before = _FakeMSAA(Role.CHECKBOX, msaa.STATE_FOCUSED | msaa.STATE_CHECKED).states
		down = _FakeMSAA(Role.CHECKBOX, msaa.STATE_FOCUSED | msaa.STATE_CHECKED | msaa.STATE_PRESSED).states
		up = _FakeMSAA(Role.CHECKBOX, msaa.STATE_FOCUSED).states
		box = _FakeMSAA(Role.CHECKBOX, 0)
		self.assertEqual(_changeSpeech(box, before, down), [])
		# Antes: «no pulsado no marcado».
		self.assertEqual(_changeSpeech(box, down, up), ["no marcado"])

	def test_boton_win32_hundido_no_dice_pulsado(self) -> None:
		self.assertNotIn(State.PRESSED, _FakeMSAA(Role.BUTTON, msaa.STATE_PRESSED).states)
		self.assertNotIn(State.PRESSED, _FakeMSAA(Role.RADIOBUTTON, msaa.STATE_PRESSED | msaa.STATE_CHECKED).states)

	def test_boton_de_alternar_activado_sigue_pulsado(self) -> None:
		# El «activado» de un botón de alternar Win32 llega como STATE_CHECKED.
		self.assertIn(State.PRESSED, _FakeMSAA(Role.TOGGLEBUTTON, msaa.STATE_CHECKED).states)

	def test_boton_de_barra_de_herramientas_conserva_pulsado(self) -> None:
		# En las barras de herramientas «pulsado» es «activado» (negrita...).
		tb = _FakeMSAA(Role.BUTTON, msaa.STATE_PRESSED, windowClass="ToolbarWindow32", childId=3)
		self.assertIn(State.PRESSED, tb.states)


# ====================================================================== Explorador
class _ExplorerItem(_FakeUIA):
	def _get_positionInfo(self) -> dict:
		return {"indexInGroup": 1, "similarItemsInGroup": 5}


def _explorerItem(multi: bool = True, selected: bool = True) -> _FakeUIA:
	return _ExplorerItem(
		{
			uc.P_CONTROLTYPE: uc.CT_LISTITEM,
			uc.P_NAME: "alfa",
			uc.P_ISENABLED: True,
			uc.P_ISKEYBOARDFOCUSABLE: True,
			uc.P_HASKEYBOARDFOCUS: True,
			uc.P_ISSELECTIONITEMPATTERNAVAILABLE: True,
			uc.P_SELECTIONITEMISSELECTED: selected,
			uc.P_ISLEGACYIACCESSIBLEPATTERNAVAILABLE: True,
			uc.P_LEGACYSTATE: 0x1300004 if multi else 0x300004,
			uc.P_CLASSNAME: "UIItem",
		}
	)


class ExplorerItemTests(unittest.TestCase):
	def test_el_archivo_no_dice_seleccion_multiple(self) -> None:
		item = _explorerItem()
		self.assertEqual(item.role, Role.LISTITEM)
		self.assertNotIn(State.MULTISELECTABLE, item.states)
		text = " ".join(presentation.getObjectSpeech(item, presentation.Reason.FOCUS))
		self.assertNotIn("selecci", text)
		self.assertNotIn("seleccionado", text)
		self.assertIn("alfa", text)
		self.assertIn("1 de 5", text)

	def test_los_elementos_no_dicen_seleccion_multiple_aunque_la_tengan(self) -> None:
		# Otras API (Java...) pueden marcar también los elementos.
		for role in (Role.LISTITEM, Role.TREEVIEWITEM):
			self.assertEqual(presentation.getStatesText(None, {State.MULTISELECTABLE, State.SELECTED}, role, presentation.Reason.FOCUS), [])

	def test_la_lista_si_dice_seleccion_multiple_al_entrar(self) -> None:
		lst = _FakeUIA(
			{
				uc.P_CONTROLTYPE: uc.CT_LIST,
				uc.P_NAME: "Vista Elementos",
				uc.P_ISENABLED: True,
				uc.P_ISLEGACYIACCESSIBLEPATTERNAVAILABLE: True,
				uc.P_LEGACYSTATE: 0x1000000,
			}
		)
		self.assertIn(State.MULTISELECTABLE, lst.states)
		self.assertIn("selección múltiple", " ".join(presentation.getObjectSpeech(lst, presentation.Reason.FOCUSENTERED)))
		conf["presentation"]["reportMultiSelect"] = False
		try:
			self.assertNotIn("selección múltiple", " ".join(presentation.getObjectSpeech(lst, presentation.Reason.FOCUSENTERED)))
		finally:
			conf["presentation"]["reportMultiSelect"] = True


# ====================================================================== eventos de selección
class _Item(behaviors.SelectableItem):
	"""Elemento de lista con nombre, padre y estados fijos."""

	def __init__(self, name: str, parent=None, states=None) -> None:
		super().__init__()
		self._n = name
		self._p = parent
		self._s = set(states or ())

	def _get_name(self) -> str:
		return self._n

	def _get_role(self) -> Role:
		return Role.LISTITEM

	def _get_parent(self):
		return self._p

	def _get_states(self) -> set:
		return set(self._s)

	def _get_processID(self) -> int:
		return 7

	def isSameAs(self, other) -> bool:
		return isinstance(other, _Item) and other._n == self._n


class SelectionEventTests(unittest.TestCase):
	def setUp(self) -> None:
		self.lst = AccObject()
		self.alfa = _Item("alfa", self.lst, {State.SELECTED, State.FOCUSED})
		self.beta = _Item("beta", self.lst)
		self.later: list = []
		self._focus = None
		patches = [
			mock.patch.object(behaviors.queue_handler, "callLater", side_effect=lambda ms, f, *a: self.later.append((f, a))),
			mock.patch.object(api, "getFocusObject", side_effect=lambda: self._focus),
			mock.patch.object(behaviors.speech, "speakMessage"),
			mock.patch.object(presentation, "speakObject"),
			mock.patch.object(presentation, "speakObjectProperties"),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)
		behaviors._lastSelectionEvent = ((), 0.0)
		self.setFocus(self.alfa)
		# Lejos del último cambio de foco.
		behaviors._focusChange[1] = time.monotonic() - 5

	def setFocus(self, obj) -> None:
		self._focus = obj
		behaviors._onFocusChange(obj)

	def runLater(self) -> None:
		pending, self.later = self.later, []
		for f, a in pending:
			f(*a)

	def test_flecha_seleccion_antes_del_foco_no_se_dice_dos_veces(self) -> None:
		# Explorador: la selección del nuevo elemento llega antes que su foco.
		self.beta.event_selection()
		self.setFocus(self.beta)
		self.runLater()
		presentation.speakObject.assert_not_called()

	def test_flecha_el_elemento_anterior_no_dice_no_seleccionado(self) -> None:
		# Listas UIA: el elemento anterior sale de la selección después del foco.
		self.setFocus(self.beta)
		self.alfa.event_selectionRemove()
		self.runLater()
		behaviors.speech.speakMessage.assert_not_called()
		presentation.speakObjectProperties.assert_not_called()

	def test_flecha_msaa_seleccion_quitada_antes_del_foco(self) -> None:
		# SysListView32: selectionRemove del anterior cuando aún tiene el foco.
		self.alfa.event_selectionRemove()
		self.setFocus(self.beta)
		self.runLater()
		behaviors.speech.speakMessage.assert_not_called()
		presentation.speakObjectProperties.assert_not_called()

	def test_mayusculas_flecha_no_dice_seleccionado(self) -> None:
		self.beta.event_selectionAdd()
		self.setFocus(self.beta)
		self.runLater()
		behaviors.speech.speakMessage.assert_not_called()

	def test_control_espacio_en_el_foco_dice_el_estado_nuevo(self) -> None:
		self.alfa.event_selectionRemove()
		self.runLater()
		presentation.speakObjectProperties.assert_called_once()
		args, kwargs = presentation.speakObjectProperties.call_args
		self.assertIs(args[0], self.alfa)
		self.assertTrue(kwargs.get("states"))
		self.assertEqual(kwargs.get("reason"), presentation.Reason.CHANGE)

	def test_control_espacio_vuelve_a_seleccionar_el_foco(self) -> None:
		# Sin nada seleccionado, MSAA manda «selection» (no selectionAdd).
		self.alfa.event_selection()
		self.runLater()
		presentation.speakObjectProperties.assert_called_once()

	def test_seleccion_del_foco_recien_llegado_no_se_dice(self) -> None:
		# Foco y luego selección del mismo elemento (flechas en listas UIA).
		self.setFocus(self.beta)
		self.beta.event_selection()
		self.beta.event_selectionAdd()
		self.runLater()
		presentation.speakObjectProperties.assert_not_called()

	def test_seleccion_multiple_de_otro_elemento_si_se_dice(self) -> None:
		self.beta.event_selectionAdd()
		self.runLater()
		behaviors.speech.speakMessage.assert_called_once_with("beta seleccionado")
		self.beta.event_selectionRemove()
		self.runLater()
		behaviors.speech.speakMessage.assert_called_with("beta no seleccionado")

	def test_sin_la_opcion_no_se_dice(self) -> None:
		conf["objects"]["reportSelectionChanges"] = False
		try:
			self.beta.event_selectionAdd()
			self.alfa.event_selectionRemove()
			self.alfa.event_selection()
			self.runLater()
		finally:
			conf["objects"]["reportSelectionChanges"] = True
		behaviors.speech.speakMessage.assert_not_called()
		presentation.speakObjectProperties.assert_not_called()

	def test_seleccion_sin_foco_se_lee_mientras_el_foco_no_cambie(self) -> None:
		# Listas que mueven la selección sin mover el foco.
		self.beta.event_selection()
		self.runLater()
		presentation.speakObject.assert_called_once()
		_args, kwargs = presentation.speakObject.call_args
		isValid = kwargs["isValid"]
		self.assertTrue(isValid())
		self.setFocus(self.beta)
		self.assertFalse(isValid())


class StateDiffTests(unittest.TestCase):
	"""Control+Espacio en el foco: el estado nuevo una sola vez."""

	def _speak(self, bits: int) -> list:
		obj = _FakeMSAA(Role.LISTITEM, bits, windowClass="SysListView32", childId=2)
		with mock.patch.object(presentation.speech, "speak") as speak, mock.patch("tiresias.braille.handler"):
			presentation.speakObjectProperties(obj, states=True, reason=presentation.Reason.CHANGE)
		return [" ".join(i for i in c.args[0] if isinstance(i, str)) for c in speak.call_args_list]

	def test_dice_el_cambio_y_no_lo_repite(self) -> None:
		base = msaa.STATE_FOCUSED | msaa.STATE_SELECTABLE | msaa.STATE_FOCUSABLE
		presentation._rememberStates(_FakeMSAA(Role.LISTITEM, base | msaa.STATE_SELECTED, "SysListView32", 2), _FakeMSAA(Role.LISTITEM, base | msaa.STATE_SELECTED, "SysListView32", 2).states)
		# Control+Espacio quita la selección: «no seleccionado».
		self.assertEqual(self._speak(base), ["no seleccionado"])
		# El evento que llega después (stateChange o selectionRemove) no repite nada.
		self.assertEqual(self._speak(base), [])
		# Control+Espacio otra vez: «seleccionado».
		self.assertEqual(self._speak(base | msaa.STATE_SELECTED), ["seleccionado"])


# ====================================================================== listas y árboles Win32 (MSAA)
class Win32ListTreeTests(unittest.TestCase):
	def test_lista_de_detalles_cuenta_sin_el_encabezado(self) -> None:
		class Row(listview.ListViewItem, iaccessible.IAccessibleObject):
			def _get_windowClassName(self) -> str:
				return "SysListView32"

			def _get_IA2(self):
				return None

			def _get_IA2Attributes(self) -> dict:
				return {}

		class Pacc:
			# El proxy MSAA cuenta 4 filas y el encabezado.
			accChildCount = 5

		row = Row(Pacc(), 1, 0x77)
		with mock.patch.object(win32ctl, "listViewItemCount", return_value=4), mock.patch.object(Row, "role", Role.LISTITEM, create=True):
			self.assertEqual(row.positionInfo, {"indexInGroup": 1, "similarItemsInGroup": 4})

	def _fakeTree(self):
		# Rama A (hijo: Hoja A1), Rama B, Rama C. HTREEITEM = 10, 11, 20, 30.
		nxt = {10: 20, 20: 30}
		prev = {20: 10, 30: 20}
		parent = {11: 10}
		acc = {1: 10, 2: 11, 3: 20, 4: 30}

		def send(hwnd, msg, wParam=0, lParam=0, timeout=0):
			if msg == win32ctl.TVM_MAPACCIDTOHTREEITEM:
				return acc.get(wParam, 0)
			if msg == win32ctl.TVM_GETNEXTITEM:
				table = {win32ctl.TVGN_NEXT: nxt, win32ctl.TVGN_PREVIOUS: prev, win32ctl.TVGN_PARENT: parent}[wParam]
				return table.get(lParam, 0)
			return 0

		return send

	def test_arbol_posicion_y_nivel(self) -> None:
		with mock.patch.object(win32ctl, "sendMessage", side_effect=self._fakeTree()):
			self.assertEqual(win32ctl.treeViewItemPosition(0x99, 1), {"indexInGroup": 1, "similarItemsInGroup": 3, "level": 1})
			self.assertEqual(win32ctl.treeViewItemPosition(0x99, 3), {"indexInGroup": 2, "similarItemsInGroup": 3, "level": 1})
			self.assertEqual(win32ctl.treeViewItemPosition(0x99, 2), {"indexInGroup": 1, "similarItemsInGroup": 1, "level": 2})
			self.assertEqual(win32ctl.treeViewItemPosition(0x99, 9), {})

	def test_elemento_de_arbol_sin_el_nivel_como_valor(self) -> None:
		class Node(iaccessible.SysTreeViewItem, iaccessible.IAccessibleObject):
			def _get_windowClassName(self) -> str:
				return "SysTreeView32"

			def _get_IA2(self):
				return None

			def _get_IA2Attributes(self) -> dict:
				return {}

			def _get_name(self) -> str:
				return "Rama A"

			def _get_role(self) -> Role:
				return Role.TREEVIEWITEM

			def _get_states(self) -> set:
				return {State.COLLAPSED}

		node = Node(object(), 1, 0x99)
		with mock.patch.object(win32ctl, "sendMessage", side_effect=self._fakeTree()):
			self.assertEqual(node.value, "")
			text = " ".join(presentation.getObjectSpeech(node, presentation.Reason.FOCUS))
		# Antes: «Rama A 0 contraído».
		self.assertEqual(text, "Rama A contraído 1 de 3 nivel 1")


# ====================================================================== botones de opción UIA
class RadioUIATests(unittest.TestCase):
	def test_opcion_seleccionada_dice_marcado(self) -> None:
		radio = _FakeUIA(
			{
				uc.P_CONTROLTYPE: uc.CT_RADIOBUTTON,
				uc.P_NAME: "Opción dos",
				uc.P_ISENABLED: True,
				uc.P_ISSELECTIONITEMPATTERNAVAILABLE: True,
				uc.P_SELECTIONITEMISSELECTED: True,
			},
			"Button",
		)
		self.assertIn(State.CHECKED, radio.states)
		text = presentation.getStatesText(radio, radio.states, radio.role, presentation.Reason.FOCUS)
		self.assertEqual(text, ["marcado"])
		# Al cambiar: «marcado», sin «seleccionado».
		self.assertEqual(presentation.getStatesText(radio, radio.states, radio.role, presentation.Reason.CHANGE, changedOnly={State.SELECTED, State.CHECKED}, removed=set()), ["marcado"])


class _Edit(AccObject):
	def _get_role(self) -> Role:
		return Role.EDITABLETEXT

	def _get_processID(self) -> int:
		return 7

	def _get_parent(self):
		return None


class SuggestionValidatorTests(unittest.TestCase):
	"""Las sugerencias se leen con el foco en el campo: la voz no debe descartarse."""

	def test_sugerencia_valida_mientras_el_foco_sigue_en_el_campo(self) -> None:
		field = _Edit()
		lst = AccObject()
		beta = _Item("beta", lst)
		state = {"focus": field}
		later: list = []
		patches = [
			mock.patch.object(behaviors.queue_handler, "callLater", side_effect=lambda ms, f, *a: later.append((f, a))),
			mock.patch.object(api, "getFocusObject", side_effect=lambda: state["focus"]),
			mock.patch.object(behaviors.speech, "cancelSpeech"),
			mock.patch.object(presentation, "speakObject"),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)
		oldSug = conf["objects"]["reportSuggestionItems"]
		oldExp = conf["speech"]["cancelExpiredFocusSpeech"]
		conf["objects"]["reportSuggestionItems"] = True
		conf["speech"]["cancelExpiredFocusSpeech"] = True
		self.addCleanup(lambda: conf["objects"].__setitem__("reportSuggestionItems", oldSug))
		self.addCleanup(lambda: conf["speech"].__setitem__("cancelExpiredFocusSpeech", oldExp))
		behaviors._onFocusChange(field)
		behaviors._focusChange[1] = time.monotonic() - 5
		behaviors._comboAnnounced = None
		behaviors._lastSelectionEvent = ((), 0.0)
		beta.event_selection()
		for f, a in list(later):
			f(*a)
		presentation.speakObject.assert_called()
		isValid = presentation.speakObject.call_args.kwargs.get("isValid")
		self.assertIsNotNone(isValid)
		self.assertTrue(isValid())
		state["focus"] = _Item("alfa", lst)
		self.assertFalse(isValid())


if __name__ == "__main__":
	unittest.main()
