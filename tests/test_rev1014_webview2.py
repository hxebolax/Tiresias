"""Revisión 1.0.14: WebView2 dentro de WinUI 3, Retroceso y complemento de WhatsApp.

Lo que contaban los usuarios de WhatsApp (la aplicación de la Microsoft Store,
WinUI 3 con WebView2): al entrar en la ventana no se oía nada ni aparecían los
controles, Control+flechas no leían y Retroceso no decía lo borrado. Causas:

- ``GetFocusedElement`` devolvía el panel ``DesktopChildSiteBridge`` de WinUI,
  sin nombre y sin foco, en vez del control web (la ventana ``Chrome_WidgetWin_0``
  con el foco del teclado solo tiene el proxy MSAA del sistema). Ahora
  :func:`uia_client.refineFocusedElement` baja hasta el descendiente con foco.
- Los eventos de foco de la página se descartaban como «internos de una ventana
  en segundo plano»: el contenido vive en una ventana de nivel superior de
  ``msedgewebview2.exe`` compuesta dentro de la de WhatsApp.
  :func:`uia_handler.isInForegroundWindow` acepta ahora el contenido cuyo
  proceso anfitrión (:func:`appmodules.handler.hostProcessId`) es el activo.
- Retroceso solo hablaba con el eco de caracteres activado.
- El complemento de WhatsApp no conocía los contenedores enfocables de la
  interfaz 2.2641 (mensajes y filas de la lista de chats).

No instala ganchos ni abre ventanas. Ejecutar con:
``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev1014_webview2 -v``
"""

from __future__ import annotations

import importlib
import os
import sys
import types
import unittest
from unittest import mock

sys.coinit_flags = 0

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import api, winapi  # noqa: E402
from tiresias.a11y import uia_client as uc  # noqa: E402
from tiresias.a11y import uia_handler  # noqa: E402
from tiresias.appmodules import handler as appHandler  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.objects import behaviors  # noqa: E402
from tiresias.objects.roles import Role  # noqa: E402
from tiresias.objects.uia import UIAObject  # noqa: E402

BRIDGE_HWND = 198290  # Microsoft.UI.Content.DesktopChildSiteBridge (WhatsApp.Root.exe)
CHROME_HWND = 198202  # Chrome_WidgetWin_0 con el foco del teclado (WhatsApp.Root.exe)
WEBVIEW_ROOT_HWND = 263170  # Chrome_WidgetWin_1, ventana de nivel superior de msedgewebview2.exe
RENDER_HWND = 788922  # Chrome_RenderWidgetHostHWND (msedgewebview2.exe)
WHATSAPP_PID = 4636
WEBVIEW_PID = 15964


class _Element:
	"""Elemento UIA falso para :func:`refineFocusedElement`."""

	def __init__(self, hwnd: int, hasFocus: bool = False, found=None) -> None:
		self.CurrentNativeWindowHandle = hwnd
		self.CurrentHasKeyboardFocus = hasFocus
		self._found = found
		self.finds: list = []

	def GetCachedPropertyValue(self, propId: int):
		if propId == uc.P_NATIVEWINDOWHANDLE:
			return self.CurrentNativeWindowHandle
		return None

	def FindFirstBuildCache(self, scope, cond, request):
		self.finds.append((scope, cond, request))
		return self._found


class _ThreadInfo:
	def __init__(self, hwndFocus: int) -> None:
		self.hwndFocus = hwndFocus


class RefineFocusedElementTests(unittest.TestCase):
	"""UIA se queda en el puente de WinUI: se baja al control web con foco."""

	def setUp(self) -> None:
		self.button = _Element(0, hasFocus=True)
		self.chrome = _Element(CHROME_HWND, found=self.button)
		self.client = mock.Mock()
		self.client.ElementFromHandleBuildCache.return_value = self.chrome
		self.user32 = mock.Mock()
		# IsChild(puente, ventana del foco): la ventana del foco está dentro del puente.
		self.user32.IsChild.side_effect = lambda parent, child: parent == BRIDGE_HWND and child == CHROME_HWND
		self.cond = object()
		patches = [
			mock.patch.object(uc, "client", self.client),
			mock.patch.object(uc, "_user32", self.user32),
			mock.patch.object(uc, "baseCacheRequest", "base"),
			mock.patch.object(uc, "createPropertyCondition", return_value=self.cond),
			mock.patch.object(winapi, "getGUIThreadInfo", return_value=_ThreadInfo(CHROME_HWND)),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def test_descends_to_the_focused_web_control(self) -> None:
		bridge = _Element(BRIDGE_HWND)
		self.assertIs(uc.refineFocusedElement(bridge), self.button)
		self.client.ElementFromHandleBuildCache.assert_called_once_with(CHROME_HWND, "base")
		scope, cond, request = self.chrome.finds[0]
		self.assertEqual(scope, uc.TreeScope_Descendants)
		self.assertIs(cond, self.cond)
		self.assertEqual(request, "base")
		uc.createPropertyCondition.assert_called_once_with(uc.P_HASKEYBOARDFOCUS, True)

	def test_uses_the_given_cache_request_and_cached_handle(self) -> None:
		bridge = _Element(BRIDGE_HWND)
		self.assertIs(uc.refineFocusedElement(bridge, "mine"), self.button)
		self.client.ElementFromHandleBuildCache.assert_called_once_with(CHROME_HWND, "mine")
		self.assertEqual(self.chrome.finds[0][2], "mine")

	def test_element_of_the_focus_window_is_kept(self) -> None:
		el = _Element(CHROME_HWND)
		self.assertIs(uc.refineFocusedElement(el), el)
		self.client.ElementFromHandleBuildCache.assert_not_called()

	def test_element_with_focus_is_kept(self) -> None:
		bridge = _Element(BRIDGE_HWND, hasFocus=True)
		self.assertIs(uc.refineFocusedElement(bridge), bridge)
		self.client.ElementFromHandleBuildCache.assert_not_called()

	def test_unrelated_window_is_kept(self) -> None:
		# El foco del teclado no está dentro de la ventana del elemento (otra aplicación).
		other = _Element(12345)
		self.assertIs(uc.refineFocusedElement(other), other)
		self.client.ElementFromHandleBuildCache.assert_not_called()

	def test_element_without_window_is_kept(self) -> None:
		el = _Element(0)
		self.assertIs(uc.refineFocusedElement(el), el)
		self.client.ElementFromHandleBuildCache.assert_not_called()

	def test_nothing_focused_below_keeps_the_element(self) -> None:
		self.chrome._found = None
		bridge = _Element(BRIDGE_HWND)
		self.assertIs(uc.refineFocusedElement(bridge), bridge)

	def test_without_thread_info_keeps_the_element(self) -> None:
		winapi.getGUIThreadInfo.return_value = None
		bridge = _Element(BRIDGE_HWND)
		self.assertIs(uc.refineFocusedElement(bridge), bridge)
		self.client.ElementFromHandleBuildCache.assert_not_called()

	def test_com_errors_keep_the_element(self) -> None:
		import comtypes

		self.client.ElementFromHandleBuildCache.side_effect = comtypes.COMError(-2147467259, "fallo", (None,) * 5)
		bridge = _Element(BRIDGE_HWND)
		self.assertIs(uc.refineFocusedElement(bridge), bridge)

	def test_none_stays_none(self) -> None:
		self.assertIsNone(uc.refineFocusedElement(None))

	def test_getFocusedElement_refines(self) -> None:
		bridge = _Element(BRIDGE_HWND)
		self.client.GetFocusedElementBuildCache.return_value = bridge
		self.assertIs(uc.getFocusedElement("base"), self.button)
		self.client.GetFocusedElement.return_value = bridge
		self.assertIs(uc.getFocusedElement(), self.button)

	def test_getFocusedElement_falls_back_to_the_keyboard_focus_window(self) -> None:
		import comtypes

		self.client.GetFocusedElementBuildCache.side_effect = comtypes.COMError(-2147467259, "fallo", (None,) * 5)
		self.assertIs(uc.getFocusedElement("base"), self.button)
		self.client.ElementFromHandleBuildCache.assert_called_once_with(CHROME_HWND, "base")
		# Sin nada con foco debajo, no hay objeto.
		self.chrome._found = None
		self.assertIsNone(uc.getFocusedElement("base"))


class FocusCheckRetryTests(unittest.TestCase):
	"""La comprobación del foco reintenta una vez si UIA no devolvió el foco."""

	def setUp(self) -> None:
		from tiresias.a11y import winevents

		self.winevents = winevents
		self._saved = winevents._focusCheckRetried
		winevents._focusCheckRetried = False

	def tearDown(self) -> None:
		self.winevents._focusCheckRetried = self._saved

	def test_retries_once_when_there_is_no_focus_object(self) -> None:
		we = self.winevents
		with mock.patch.object(api, "getFocusObject", return_value=None), mock.patch("tiresias.objects.uia.getFocusObject", return_value=None), mock.patch.object(we, "scheduleFocusCheck") as sched:
			we._checkFocus()
			sched.assert_called_once_with(300, force=False)
			we._checkFocus()
			sched.assert_called_once()

	def test_a_found_focus_resets_the_retry(self) -> None:
		we = self.winevents
		obj = mock.Mock()
		obj.shouldAllowFocusEvent = True
		we._focusCheckRetried = True
		with mock.patch.object(api, "getFocusObject", return_value=None), mock.patch("tiresias.objects.uia.getFocusObject", return_value=obj), mock.patch("tiresias.events.executeEvent") as ev, mock.patch.object(uia_handler, "_registerLocalHandlers"):
			we._checkFocus()
		ev.assert_called_once_with("gainFocus", obj)
		self.assertFalse(we._focusCheckRetried)


class HostedContentForegroundTests(unittest.TestCase):
	"""El contenido WebView2 de una ventana activa cuenta como primer plano."""

	def _obj(self, pid: int = WEBVIEW_PID, hwnd: int = RENDER_HWND):
		obj = mock.Mock()
		obj.processID = pid
		obj.windowHandle = hwnd
		return obj

	def _patch(self, hostPid: int):
		pids = {198190: WHATSAPP_PID, WEBVIEW_ROOT_HWND: WEBVIEW_PID, RENDER_HWND: WEBVIEW_PID}
		patches = [
			mock.patch.object(winapi, "getForegroundWindow", return_value=198190),
			mock.patch.object(winapi, "getWindowProcessId", side_effect=lambda h: pids.get(h, 0)),
			mock.patch.object(winapi, "getAncestor", side_effect=lambda h, flags=winapi.GA_ROOT: WEBVIEW_ROOT_HWND if h == RENDER_HWND else h),
			mock.patch.object(appHandler, "hostProcessId", return_value=hostPid),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def test_webview_content_hosted_by_the_foreground_app_is_accepted(self) -> None:
		self._patch(WHATSAPP_PID)
		obj = self._obj()
		self.assertTrue(uia_handler.isInForegroundWindow(obj))
		appHandler.hostProcessId.assert_called_once_with(obj, WEBVIEW_ROOT_HWND)

	def test_content_hosted_by_another_app_is_rejected(self) -> None:
		self._patch(hostPid=999)
		self.assertFalse(uia_handler.isInForegroundWindow(self._obj()))

	def test_same_process_needs_no_host_lookup(self) -> None:
		self._patch(hostPid=999)
		self.assertTrue(uia_handler.isInForegroundWindow(self._obj(pid=WHATSAPP_PID, hwnd=BRIDGE_HWND)))
		appHandler.hostProcessId.assert_not_called()


class StaleFocusTests(unittest.TestCase):
	"""Al volver a WhatsApp, UIA puede seguir dando el foco de la ventana anterior."""

	def _obj(self, pid: int, hwnd: int):
		obj = mock.Mock()
		obj.processID = pid
		obj.windowHandle = hwnd
		return obj

	def test_element_of_another_app_is_stale(self) -> None:
		from tiresias.objects import uia as uiaObjects

		claude = self._obj(pid=55572, hwnd=17892106)
		with mock.patch.object(winapi, "getWindowProcessId", side_effect=lambda h: WHATSAPP_PID if h == CHROME_HWND else 55572), mock.patch.object(winapi, "getAncestor", return_value=17892106), mock.patch.object(appHandler, "hostProcessId", return_value=55572):
			self.assertTrue(uiaObjects.isStaleFocus(claude, CHROME_HWND))

	def test_hosted_content_of_the_focus_window_is_current(self) -> None:
		from tiresias.objects import uia as uiaObjects

		message = self._obj(pid=WEBVIEW_PID, hwnd=RENDER_HWND)
		with mock.patch.object(winapi, "getWindowProcessId", side_effect=lambda h: WHATSAPP_PID if h == CHROME_HWND else WEBVIEW_PID), mock.patch.object(winapi, "getAncestor", return_value=WEBVIEW_ROOT_HWND), mock.patch.object(appHandler, "hostProcessId", return_value=WHATSAPP_PID) as host:
			self.assertFalse(uiaObjects.isStaleFocus(message, CHROME_HWND))
		host.assert_called_once_with(message, WEBVIEW_ROOT_HWND)

	def test_same_process_is_current_without_lookups(self) -> None:
		from tiresias.objects import uia as uiaObjects

		obj = self._obj(pid=WHATSAPP_PID, hwnd=BRIDGE_HWND)
		with mock.patch.object(winapi, "getWindowProcessId", return_value=WHATSAPP_PID), mock.patch.object(appHandler, "hostProcessId") as host:
			self.assertFalse(uiaObjects.isStaleFocus(obj, CHROME_HWND))
		host.assert_not_called()

	def test_getFocusObject_replaces_a_stale_focus(self) -> None:
		from tiresias.a11y import api_choice
		from tiresias.objects import uia as uiaObjects

		stale, fresh = object(), object()
		staleObj, freshObj = mock.Mock(name="stale"), mock.Mock(name="fresh")
		with mock.patch.object(api_choice, "chooseAPIForFocus", return_value=(api_choice.API_UIA, CHROME_HWND)), mock.patch.object(uc, "getFocusedElement", return_value=stale), mock.patch.object(uc, "focusedDescendantOfWindow", return_value=fresh) as search, mock.patch.object(uiaObjects.UIAObject, "fromElement", side_effect=lambda el, *a: staleObj if el is stale else freshObj), mock.patch.object(uiaObjects, "isStaleFocus", return_value=True):
			self.assertIs(uiaObjects.getFocusObject(), freshObj)
		search.assert_called_once()
		self.assertEqual(search.call_args[0][0], CHROME_HWND)

	def test_getFocusObject_keeps_a_current_focus(self) -> None:
		from tiresias.a11y import api_choice
		from tiresias.objects import uia as uiaObjects

		obj = mock.Mock()
		with mock.patch.object(api_choice, "chooseAPIForFocus", return_value=(api_choice.API_UIA, CHROME_HWND)), mock.patch.object(uc, "getFocusedElement", return_value=object()), mock.patch.object(uc, "focusedDescendantOfWindow") as search, mock.patch.object(uiaObjects.UIAObject, "fromElement", return_value=obj), mock.patch.object(uiaObjects, "isStaleFocus", return_value=False):
			self.assertIs(uiaObjects.getFocusObject(), obj)
		search.assert_not_called()


class HostProcessIdTests(unittest.TestCase):
	def setUp(self) -> None:
		self._saved = dict(appHandler._hostPidCache)
		appHandler._hostPidCache.clear()

	def tearDown(self) -> None:
		appHandler._hostPidCache.clear()
		appHandler._hostPidCache.update(self._saved)

	def test_hosted_content_uses_the_top_level_window_of_the_tree(self) -> None:
		obj = mock.Mock()
		obj._findHostProcessId.return_value = WHATSAPP_PID
		with mock.patch.object(winapi, "getWindowProcessId", return_value=WEBVIEW_PID), mock.patch.object(winapi, "getProcessName", return_value="msedgewebview2"):
			self.assertEqual(appHandler.hostProcessId(obj, WEBVIEW_ROOT_HWND), WHATSAPP_PID)
			# Recordado por ventana raíz: la segunda vez no se recorre el árbol.
			self.assertEqual(appHandler.hostProcessId(obj, WEBVIEW_ROOT_HWND), WHATSAPP_PID)
		obj._findHostProcessId.assert_called_once()

	def test_own_window_keeps_its_process(self) -> None:
		obj = mock.Mock()
		with mock.patch.object(winapi, "getWindowProcessId", return_value=4242), mock.patch.object(winapi, "getProcessName", return_value="notepad"):
			self.assertEqual(appHandler.hostProcessId(obj, 777), 4242)
		obj._findHostProcessId.assert_not_called()

	def test_tree_without_host_falls_back_to_the_window_process(self) -> None:
		obj = mock.Mock()
		obj._findHostProcessId.return_value = 0
		with mock.patch.object(winapi, "getWindowProcessId", return_value=WEBVIEW_PID), mock.patch.object(winapi, "getProcessName", return_value="msedgewebview2"):
			self.assertEqual(appHandler.hostProcessId(obj, WEBVIEW_ROOT_HWND), WEBVIEW_PID)


class BackspaceAlwaysSpeaksTests(unittest.TestCase):
	"""Retroceso anuncia lo borrado aunque el eco de caracteres esté desactivado."""

	def setUp(self) -> None:
		self._echo = conf["keyboard"]["speakTypedCharacters"]
		conf["keyboard"]["speakTypedCharacters"] = "off"

	def tearDown(self) -> None:
		conf["keyboard"]["speakTypedCharacters"] = self._echo

	def test_caret_backspace_speaks_the_deleted_character(self) -> None:
		obj = mock.Mock()
		obj.states = set()
		obj.role = Role.EDITABLETEXT
		obj._isTerminalLike = lambda: False
		sel = mock.Mock()
		sel.isCollapsed = True
		obj.makeTextInfo.return_value = sel
		before = mock.Mock()
		before.text = "o"
		before.move.return_value = True
		info = mock.Mock()
		info.copy.return_value = before
		obj._getCaretInfo.return_value = info
		g = mock.Mock()
		with mock.patch("tiresias.speech.speakCharacter") as sc, mock.patch("tiresias.speech.cancelSpeech"), mock.patch.object(behaviors, "isProtected", return_value=False):
			behaviors.EditableText.script_caret_backspaceCharacter(obj, g)
		g.send.assert_called_once()
		sc.assert_called_once_with("o")

	def test_caret_backspace_speaks_the_deleted_selection(self) -> None:
		obj = mock.Mock()
		obj.states = set()
		obj.role = Role.EDITABLETEXT
		obj._isTerminalLike = lambda: False
		sel = mock.Mock()
		sel.isCollapsed = False
		sel.text = "hola"
		obj.makeTextInfo.return_value = sel
		obj._getCaretInfo.return_value = mock.Mock()
		with mock.patch("tiresias.speech.speakText") as st, mock.patch("tiresias.speech.cancelSpeech"), mock.patch.object(behaviors, "isProtected", return_value=False):
			behaviors.EditableText.script_caret_backspaceCharacter(obj, mock.Mock())
		st.assert_called_once()
		self.assertIn("hola", st.call_args[0][0])

	def test_virtual_backspace_speaks_the_deleted_character(self) -> None:
		obj = mock.Mock()
		obj._syncValue.return_value = ["ab", 2]
		g = mock.Mock()
		with mock.patch("tiresias.speech.speakCharacter") as sc, mock.patch("tiresias.speech.cancelSpeech"), mock.patch.object(behaviors, "isProtected", return_value=False), mock.patch("tiresias.queue_handler.callLater"):
			behaviors.EditableTextNoCaret.script_virtualBackspace(obj, g)
		g.send.assert_called_once()
		sc.assert_called_once_with("b")

	def test_protected_field_stays_silent(self) -> None:
		obj = mock.Mock()
		obj._syncValue.return_value = ["ab", 2]
		with mock.patch("tiresias.speech.speakCharacter") as sc, mock.patch.object(behaviors, "isProtected", return_value=True), mock.patch("tiresias.queue_handler.callLater"):
			behaviors.EditableTextNoCaret.script_virtualBackspace(obj, mock.Mock())
		sc.assert_not_called()


# ====================================================================== WhatsApp
WA_BASE = os.path.join(ROOT, "data", "addons", "whatsapp")


def _waModule():
	for name, path in (("rev1014_wa", WA_BASE), ("rev1014_wa.appModules", os.path.join(WA_BASE, "appModules"))):
		if name not in sys.modules:
			mod = types.ModuleType(name)
			mod.__path__ = [path]  # type: ignore[attr-defined]
			sys.modules[name] = mod
	return importlib.import_module("rev1014_wa.appModules.whatsapp_root")


class _Node:
	"""Nodo de instantánea falso (como ``whatsapp_root.Node``)."""

	def __init__(self, focusable: bool = False, cls: str = "", ct: int = uc.CT_GROUP, children=()) -> None:
		self.focusable = focusable
		self.cls = cls
		self.ct = ct
		self.name = ""
		self.el = mock.Mock()
		self.parent = None
		self.depth = 0
		self.children = list(children)
		for c in self.children:
			c.parent = self
			c._setDepth(1)

	def _setDepth(self, depth: int) -> None:
		self.depth = depth
		for c in self.children:
			c._setDepth(depth + 1)

	@property
	def isMessage(self) -> bool:
		return "focusable-list-item" in self.cls

	def walk(self):
		yield self
		for c in self.children:
			yield from c.walk()


class WhatsAppFocusTests(unittest.TestCase):
	def setUp(self) -> None:
		self.wa = _waModule()

	def test_manifest_version_was_raised(self) -> None:
		import json

		with open(os.path.join(WA_BASE, "manifest.json"), encoding="utf-8") as f:
			self.assertEqual(json.load(f)["version"], "1.0.4")

	def test_focusable_node_climbs_to_the_focusable_container(self) -> None:
		message = _Node(cls="focusable-list-item")
		wrapper = _Node(focusable=True, children=[message])
		_Node(focusable=True, children=[wrapper])  # la fila
		self.assertIs(self.wa.focusableNode(message), wrapper)
		focusableMessage = _Node(focusable=True, cls="focusable-list-item")
		_Node(focusable=True, children=[focusableMessage])
		self.assertIs(self.wa.focusableNode(focusableMessage), focusableMessage)
		orphan = _Node()
		self.assertIs(self.wa.focusableNode(orphan), orphan)
		self.assertIsNone(self.wa.focusableNode(None))

	def test_focus_sets_focus_on_the_focusable_container(self) -> None:
		message = _Node(cls="focusable-list-item")
		wrapper = _Node(focusable=True, children=[message])
		self.assertTrue(self.wa.AppModule._focus(message))
		wrapper.el.SetFocus.assert_called_once()
		message.el.SetFocus.assert_not_called()
		self.assertFalse(self.wa.AppModule._focus(None))

	def test_inner_focusable_prefers_the_child_whatsapp_focuses(self) -> None:
		inner = _Node(focusable=True)
		cell = _Node(focusable=True, ct=uc.CT_DATAITEM, children=[_Node(), inner])
		self.assertIs(self.wa._innerFocusable(cell), inner)
		plain = _Node(focusable=True, ct=uc.CT_DATAITEM, children=[_Node()])
		self.assertIs(self.wa._innerFocusable(plain), plain)
		self.assertIsNone(self.wa._innerFocusable(None))

	def _uiaObject(self, ct: int, aria: str, focusable: bool = True, cls: str = ""):
		obj = mock.Mock(spec=UIAObject)
		obj.UIAClassName = cls
		obj.UIAAriaRole = aria
		obj.UIAControlType = ct
		obj.isFocusable = focusable
		obj.element = object()
		return obj

	def test_message_wrapper_is_read_as_a_message(self) -> None:
		app = self.wa.AppModule.__new__(self.wa.AppModule)
		obj = self._uiaObject(uc.CT_GROUP, "group")
		snap = _Node(focusable=True, children=[_Node(cls="focusable-list-item", children=[_Node(ct=uc.CT_TEXT)])])
		clsList: list = []
		with mock.patch.object(self.wa, "snapshot", return_value=snap):
			app.chooseObjectClass(obj, clsList)
		self.assertIs(clsList[0], self.wa.WAMessage)

	def test_deep_message_is_not_a_wrapper(self) -> None:
		app = self.wa.AppModule.__new__(self.wa.AppModule)
		obj = self._uiaObject(uc.CT_GROUP, "group")
		deep = _Node(focusable=True, children=[_Node(children=[_Node(children=[_Node(cls="focusable-list-item")])])])
		clsList: list = []
		with mock.patch.object(self.wa, "snapshot", return_value=deep):
			app.chooseObjectClass(obj, clsList)
		self.assertIs(clsList[0], self.wa.WACleanName)

	def test_chat_row_inner_group_is_read_as_a_chat_item(self) -> None:
		app = self.wa.AppModule.__new__(self.wa.AppModule)
		obj = self._uiaObject(uc.CT_GROUP, "group")
		obj.parent = self._uiaObject(uc.CT_DATAITEM, "gridcell")
		clsList: list = []
		with mock.patch.object(self.wa, "snapshot", return_value=_Node(focusable=True)):
			app.chooseObjectClass(obj, clsList)
		self.assertIs(clsList[0], self.wa.WAChatItem)

	def test_plain_group_keeps_the_clean_name_class(self) -> None:
		app = self.wa.AppModule.__new__(self.wa.AppModule)
		obj = self._uiaObject(uc.CT_GROUP, "group", focusable=False)
		clsList: list = []
		with mock.patch.object(self.wa, "snapshot") as snap:
			app.chooseObjectClass(obj, clsList)
		snap.assert_not_called()
		self.assertIs(clsList[0], self.wa.WACleanName)

	def test_toggle_compose_without_a_chat_says_so(self) -> None:
		app = self.wa.AppModule.__new__(self.wa.AppModule)
		app._lastFocusedMessage = None
		spoken: list[str] = []
		focus = mock.Mock()
		focus.role = Role.BUTTON
		with mock.patch.object(api, "getFocusObject", return_value=focus), mock.patch.object(self.wa.AppModule, "_mainSnapshot", return_value=None), mock.patch.object(self.wa.AppModule, "_speak", side_effect=lambda self, text: spoken.append(text), autospec=True):
			app.script_toggleComposeAndMessages(mock.Mock())
		self.assertEqual(spoken, ["No hay un chat abierto"])


if __name__ == "__main__":
	unittest.main()
