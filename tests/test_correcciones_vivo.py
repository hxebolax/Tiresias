"""Pruebas de los fallos encontrados en la prueba en vivo (ganchos reales).

- Composición de entrada (IME): el manejador COM sigue sirviendo tras quitar
  y volver a poner el registro (antes fallaba con «Interface ... not supported»).
- «página 2» falso en controles sin paginación y estado de formato estable
  por control.
- Fin en un campo: «en blanco» al final del texto y al final de una línea.
- RichEdit y documentos editables que no son web ni Word: «edición multilínea».
- La ventana principal oculta de Tiresias no se anuncia nunca.

No se inyectan teclas ni se tocan programas del usuario.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import gc
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="tiresias_test_vivo_")
shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
paths.setDataDir(_TMP)
paths.ensureDataDirs()

from tiresias import a11y  # noqa: E402,F401  (registra las opciones)
from tiresias import formatting, presentation, textinfo  # noqa: E402
from tiresias.a11y import uia_client as uc  # noqa: E402
from tiresias.objects import base  # noqa: E402
from tiresias.objects.roles import Role, State  # noqa: E402
from tiresias.objects.uia import UIAObject  # noqa: E402
from tiresias.objects.uia_text import UIATextInfo  # noqa: E402


def tearDownModule() -> None:
	shutil.rmtree(_TMP, ignore_errors=True)


# ====================================================================== IME
class ImeHandlerTests(unittest.TestCase):
	def test_el_manejador_conserva_sus_interfaces(self) -> None:
		from tiresias import ime

		plugin = ime.GlobalPlugin()
		self.assertTrue(plugin._ensureHandler())
		iid = uc.UIA.IUIAutomationTextEditTextChangedEventHandler._iid_
		# UIA toma y suelta referencias al registrar y quitar el manejador.
		for _i in range(3):
			extra = plugin._handlerPtr.QueryInterface(uc.UIA.IUIAutomationTextEditTextChangedEventHandler)
			del extra
			gc.collect()
		self.assertIn(iid, plugin._handler._com_pointers_)
		# El mismo puntero sirve para el siguiente registro.
		self.assertTrue(plugin._ensureHandler())
		plugin.terminate()
		self.assertIsNone(plugin._handlerPtr)

	def test_registro_y_baja_repetidos(self) -> None:
		from tiresias import ime

		plugin = ime.GlobalPlugin()
		client = mock.Mock()
		obj = mock.Mock(hasText=True, element=object())
		with mock.patch.object(uc, "client", client):
			for _i in range(3):
				plugin._register(obj)
				self.assertEqual(plugin._registrations, 2)
			self.assertEqual(client.AddTextEditTextChangedEventHandler.call_count, 6)
			# Cada registro nuevo quita los dos anteriores.
			self.assertEqual(client.RemoveTextEditTextChangedEventHandler.call_count, 4)
			for call in client.AddTextEditTextChangedEventHandler.call_args_list:
				self.assertIs(call.args[4], plugin._handlerPtr)
			plugin.terminate()


# ====================================================================== páginas
class _FakeRange:
	"""Rango UIA mínimo: un documento de ``length`` caracteres en páginas de ``page``."""

	def __init__(self, length: int, page: int | None, start: int = 0, end: int = 0) -> None:
		self.length, self.page, self.start, self.end = length, page, start, end

	def Clone(self):
		return _FakeRange(self.length, self.page, self.start, self.end)

	def MoveEndpointByRange(self, ep, other, otherEp):
		val = other.start if otherEp == uc.EP_START else other.end
		if ep == uc.EP_START:
			self.start = val
		else:
			self.end = val

	def ExpandToEnclosingUnit(self, unit):
		if unit == uc.TU_PAGE and self.page:
			first = (min(self.start, self.length - 1) // self.page) * self.page
			self.start, self.end = first, min(first + self.page, self.length)
		else:
			# Sin páginas (o unidad documento): el documento entero.
			self.start, self.end = 0, self.length

	def CompareEndpoints(self, ep, other, otherEp):
		a = self.start if ep == uc.EP_START else self.end
		b = other.start if otherEp == uc.EP_START else other.end
		return (a > b) - (a < b)

	def Move(self, unit, count):
		if unit != uc.TU_PAGE or not self.page:
			return -1 if self.start > 0 and count < 0 else 0
		moved = 0
		while count < 0 and self.start > 0:
			self.start = max(0, self.start - self.page)
			self.end = self.start + self.page
			moved -= 1
			count += 1
		return moved


class PageNumberTests(unittest.TestCase):
	def _info(self, rng):
		return UIATextInfo(None, None, _range=rng)

	def test_sin_paginacion_no_hay_pagina(self) -> None:
		# Un campo de edición: la «página» es el documento entero.
		info = self._info(_FakeRange(40, None, 30, 30))
		self.assertIsNone(info.pageNumber)

	def test_documento_paginado(self) -> None:
		self.assertEqual(self._info(_FakeRange(100, 10, 5, 5)).pageNumber, 1)
		self.assertEqual(self._info(_FakeRange(100, 10, 25, 25)).pageNumber, 3)
		# Al final de una página (sin pasar a la siguiente) sigue siendo esa página.
		self.assertEqual(self._info(_FakeRange(100, 10, 19, 19)).pageNumber, 2)

	def test_collect_no_anuncia_pagina_sin_paginacion(self) -> None:
		info = self._info(_FakeRange(40, None, 30, 30))
		self.assertNotIn("page", formatting.collect(info))


class FormatStateKeyTests(unittest.TestCase):
	def test_clave_estable_por_control(self) -> None:
		a = mock.Mock(runtimeId=(42, 1, 2))
		b = mock.Mock(runtimeId=(42, 1, 2))
		c = mock.Mock(runtimeId=(42, 1, 3))
		self.assertEqual(formatting._stateKey(a), formatting._stateKey(b))
		self.assertNotEqual(formatting._stateKey(a), formatting._stateKey(c))

	def test_sin_runtime_id_usa_la_ventana(self) -> None:
		a = mock.Mock(runtimeId=None, windowHandle=0x100, IAccessibleChildID=0)
		b = mock.Mock(runtimeId=None, windowHandle=0x200, IAccessibleChildID=0)
		self.assertNotEqual(formatting._stateKey(a), formatting._stateKey(b))
		self.assertIsNone(formatting._stateKey(None))


# ====================================================================== final del texto
class _Story(textinfo.OffsetsTextInfo):
	def __init__(self, text: str, caret: int) -> None:
		self._text, self._caret = text, caret
		super().__init__(None, textinfo.POSITION_CARET)

	def _getStoryText(self) -> str:
		return self._text

	def _getCaretOffset(self) -> int:
		return self._caret


class EndOfTextTests(unittest.TestCase):
	def test_caracter_tras_el_final_esta_vacio(self) -> None:
		info = _Story("Juan", 4)
		info.expand(textinfo.UNIT_CHARACTER)
		self.assertEqual(info.text, "")
		info = _Story("Juan", 4)
		info.expand(textinfo.UNIT_WORD)
		self.assertEqual(info.text, "")

	def test_caracter_dentro_del_texto(self) -> None:
		info = _Story("Juan", 3)
		info.expand(textinfo.UNIT_CHARACTER)
		self.assertEqual(info.text, "n")

	def test_en_blanco_al_final_y_en_saltos_de_linea(self) -> None:
		for text, caret in (("Juan", 4), ("uno\ndos", 3), ("uno\r\ndos", 3)):
			with mock.patch("tiresias.speech.speak") as speak, mock.patch("tiresias.braille.handler"):
				presentation.speakTextInfo(_Story(text, caret), textinfo.UNIT_CHARACTER, reason=presentation.Reason.CARET)
			spoken = [s for call in speak.call_args_list for s in call.args[0] if isinstance(s, str)]
			self.assertIn("en blanco", spoken, (text, caret))
			self.assertNotIn("salto de línea", spoken)


# ====================================================================== edición multilínea
class _FakeElement:
	def __init__(self, props: dict) -> None:
		self.props = props

	def GetCachedPropertyValueEx(self, propId, ignoreDefault):
		return self.props.get(propId)

	def GetCurrentPropertyValueEx(self, propId, ignoreDefault):
		return self.props.get(propId)


class _FakeUIA(UIAObject):
	def __init__(self, props: dict, windowClass: str = "") -> None:
		super().__init__(_FakeElement(props), windowHandle=0x1234)
		self._wc = windowClass

	def _get_windowClassName(self) -> str:
		return self._wc


def _docProps(framework: str = "Win32", readOnly: bool = False, cls: str = "RICHEDIT50W") -> dict:
	return {
		uc.P_CONTROLTYPE: uc.CT_DOCUMENT,
		uc.P_ISVALUEPATTERNAVAILABLE: True,
		uc.P_VALUEISREADONLY: readOnly,
		uc.P_FRAMEWORKID: framework,
		uc.P_CLASSNAME: cls,
		uc.P_ISENABLED: True,
	}


class MultilineEditTests(unittest.TestCase):
	def test_richedit_es_edicion_multilinea(self) -> None:
		obj = _FakeUIA(_docProps(), "RICHEDIT50W")
		self.assertEqual(obj.role, Role.EDITABLETEXT)
		self.assertIn(State.MULTILINE, obj.states)
		self.assertIn(State.EDITABLE, obj.states)
		self.assertIn("multilínea", presentation.getStatesText(obj, obj.states, obj.role, presentation.Reason.QUERY))

	def test_al_enfocar_dice_edicion_multilinea(self) -> None:
		class Field(base.AccObject):
			def _get_name(self):
				return "Notas:"

			def _get_role(self):
				return Role.EDITABLETEXT

			def _get_states(self):
				return {State.EDITABLE, State.MULTILINE, State.FOCUSABLE}

			def _get_value(self):
				return ""

			def _get_processID(self):
				return 1

			def _get_appModule(self):
				return None

		speechText = " ".join(presentation.getObjectSpeech(Field(), presentation.Reason.FOCUS))
		self.assertIn("edición multilínea", speechText)
		# Y no se repite con los estados.
		self.assertEqual(speechText.count("multilínea"), 1)

	def test_documentos_web_y_word_siguen_siendo_documentos(self) -> None:
		for fw in ("Chrome", "Gecko", "MicrosoftEdge"):
			self.assertEqual(_FakeUIA(_docProps(framework=fw, cls=""), "Chrome_RenderWidgetHostHWND").role, Role.DOCUMENT, fw)
		self.assertEqual(_FakeUIA(_docProps(cls="_WwG"), "_WwG").role, Role.DOCUMENT)
		# Los documentos de solo lectura no cambian (modo exploración, visores)...
		self.assertEqual(_FakeUIA(_docProps(readOnly=True, cls="Visor"), "Visor").role, Role.DOCUMENT)
		# ...salvo los RichEdit: en NVDA son «edición multilínea» de solo lectura (1.0.15).
		self.assertEqual(_FakeUIA(_docProps(readOnly=True), "RICHEDIT50W").role, Role.EDITABLETEXT)

	def test_multilinea_no_se_repite_al_mover_el_cursor(self) -> None:
		obj = _FakeUIA(_docProps(), "RICHEDIT50W")
		text = presentation.getStatesText(obj, obj.states, obj.role, presentation.Reason.CARET)
		self.assertNotIn("multilínea", text)


# ====================================================================== selección repetida
class SelectionEchoTests(unittest.TestCase):
	def test_seleccion_repetida_se_dice_una_vez(self) -> None:
		from tiresias.objects import behaviors

		item = mock.Mock(runtimeId=(7, 7))
		other = mock.Mock(runtimeId=(7, 8))
		behaviors._lastSelectionEvent = ((), 0.0)
		self.assertFalse(behaviors._isRepeatedSelection(item))
		self.assertTrue(behaviors._isRepeatedSelection(item))
		self.assertFalse(behaviors._isRepeatedSelection(other))

	def test_combo_cerrado_no_repite_el_valor(self) -> None:
		from tiresias import api
		from tiresias.objects import behaviors

		combo = mock.Mock(role=Role.COMBOBOX, states={State.COLLAPSED, State.FOCUSED}, processID=5)
		item = mock.Mock(spec=behaviors.SelectableItem, processID=5)
		with mock.patch.object(api, "getFocusObject", return_value=combo), mock.patch("tiresias.presentation.speakObject") as speak:
			behaviors.SelectableItem.event_selection(item)
		speak.assert_not_called()


# ====================================================================== volver a la ventana anterior
class RestoreForegroundTests(unittest.TestCase):
	def test_vuelve_a_la_aplicacion_anterior(self) -> None:
		from tiresias.gui import helpers

		with mock.patch.object(helpers.winapi, "user32") as u32, mock.patch.object(helpers.winapi, "getForegroundWindow", return_value=0x900), mock.patch.object(
			helpers.winapi, "getWindowProcessId", return_value=1
		), mock.patch.object(helpers.winapi, "setForegroundWindow") as setFg:
			u32.IsWindow.return_value = 1
			u32.IsWindowVisible.return_value = 1
			helpers.restorePreviousForeground(0x100)
			setFg.assert_called_once_with(0x100)

	def test_al_cerrar_el_dialogo_vuelve_antes_de_ocultarse(self) -> None:
		from tiresias.gui import helpers

		win = mock.Mock(_prevForegroundHwnd=0x100)
		with mock.patch.object(helpers.wx, "GetTopLevelWindows", return_value=[win]), mock.patch.object(helpers.winapi, "user32") as u32, mock.patch.object(
			helpers.winapi, "getForegroundWindow", return_value=0x900
		), mock.patch.object(helpers.winapi, "getWindowProcessId", return_value=os.getpid()), mock.patch.object(helpers.winapi, "setForegroundWindow") as setFg:
			u32.IsWindow.return_value = 1
			u32.IsWindowVisible.return_value = 1
			# El diálogo (de Tiresias) aún es la ventana activa: se vuelve a la aplicación.
			helpers._restoreOnClose(win)
			setFg.assert_called_once_with(0x100)
			# Solo una vez.
			helpers._restoreOnClose(win)
			setFg.assert_called_once()

	def test_no_roba_el_foco_a_otra_ventana_de_tiresias(self) -> None:
		from tiresias.gui import helpers

		with mock.patch.object(helpers.winapi, "user32") as u32, mock.patch.object(helpers.winapi, "getForegroundWindow", return_value=0x900), mock.patch.object(
			helpers.winapi, "getWindowProcessId", return_value=os.getpid()
		), mock.patch.object(helpers.winapi, "setForegroundWindow") as setFg:
			u32.IsWindow.return_value = 1
			u32.IsWindowVisible.return_value = 1
			helpers.restorePreviousForeground(0x100)
			setFg.assert_not_called()


# ====================================================================== foco en segundo plano
class BackgroundFocusTests(unittest.TestCase):
	def _check(self, objPid, objHwnd, rootPid, fg=0x10, fgPid=1, root=0x20):
		from tiresias import winapi
		from tiresias.a11y import uia_handler

		obj = mock.Mock(processID=objPid, windowHandle=objHwnd)
		pids = {fg: fgPid, root: rootPid}
		with mock.patch.object(winapi, "getForegroundWindow", return_value=fg), mock.patch.object(
			winapi, "getWindowProcessId", side_effect=lambda h: pids.get(h, 0)
		), mock.patch.object(winapi, "getAncestor", return_value=root):
			return uia_handler.isInForegroundWindow(obj)

	def test_mismo_proceso_que_la_ventana_activa(self) -> None:
		self.assertTrue(self._check(objPid=1, objHwnd=0x30, rootPid=1))

	def test_ventana_de_otro_proceso_en_segundo_plano(self) -> None:
		# Chromium avisa del foco interno de una ventana inactiva.
		self.assertFalse(self._check(objPid=2, objHwnd=0x30, rootPid=2))

	def test_contenido_incrustado_de_otro_proceso(self) -> None:
		# WebView2: el contenido es de otro proceso, pero su ventana raíz es la activa.
		self.assertTrue(self._check(objPid=2, objHwnd=0x30, rootPid=1))


# ====================================================================== ventana oculta
class HiddenMainWindowTests(unittest.TestCase):
	def tearDown(self) -> None:
		base._hiddenMainHwnd = 0

	def test_la_ventana_oculta_no_recibe_foco(self) -> None:
		# Desde la 1.0.11 se usa el HWND guardado al crear la ventana (gui.mainFrameHwnd)
		# para no llamar a wx desde el hilo del núcleo.
		with mock.patch("tiresias.gui.mainFrameHwnd", 0x5555, create=True):
			base._hiddenMainHwnd = 0
			self.assertTrue(base.isHiddenMainWindow(0x5555))
			self.assertFalse(base.isHiddenMainWindow(0x6666))
			self.assertFalse(base.isHiddenMainWindow(0))
			hidden = _FakeUIA({uc.P_CONTROLTYPE: uc.CT_PANE})
			hidden._windowHandle = 0x5555
			self.assertFalse(hidden.shouldAllowFocusEvent)
			other = _FakeUIA({uc.P_CONTROLTYPE: uc.CT_PANE})
			self.assertTrue(other.shouldAllowFocusEvent)


if __name__ == "__main__":
	unittest.main()
