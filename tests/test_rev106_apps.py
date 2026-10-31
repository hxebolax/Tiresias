"""Pruebas de la revisión 1.0.6 (módulos de aplicación, herramientas de sistema,
consola, IME y complemento WhatsApp).

Usan objetos simulados: no necesitan ninguna de las aplicaciones.
Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev106_apps -v``
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_rev106_apps_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()

from tiresias import speech  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.objects.roles import Role  # noqa: E402

WA_BASE = os.path.join(ROOT, "data", "addons", "whatsapp")
#: Marcas invisibles de dirección que deben desaparecer del texto leído.
MARKS = "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u200b"


class Obj:
	"""Objeto accesible mínimo."""

	def __init__(self, name="", role=Role.LISTITEM, parent=None, children=(), **kw) -> None:
		self.name = name
		self.role = role
		self.parent = parent
		self.children = list(children)
		for c in self.children:
			c.parent = self
		for k, v in kw.items():
			setattr(self, k, v)


class Gesture:
	def __init__(self) -> None:
		self.send = mock.Mock()
		self.identifiers = []


def _waModules():
	"""Carga el complemento WhatsApp como un paquete propio (como hace el cargador)."""
	for name, path in (("rev106_wa", WA_BASE), ("rev106_wa.appModules", os.path.join(WA_BASE, "appModules")), ("rev106_wa.globalPlugins", os.path.join(WA_BASE, "globalPlugins"))):
		if name not in sys.modules:
			mod = types.ModuleType(name)
			mod.__path__ = [path]  # type: ignore[attr-defined]
			sys.modules[name] = mod
	root = importlib.import_module("rev106_wa.appModules.whatsapp_root")
	strings = importlib.import_module("rev106_wa.appModules.wa_strings")
	return root, strings


class confValues:
	"""Cambia valores de una sección de ``conf`` y los restaura al salir."""

	def __init__(self, section: str, values: dict) -> None:
		self.section = section
		self.values = values

	def __enter__(self):
		sec = conf[self.section]
		self.old = {k: sec[k] for k in self.values}
		for k, v in self.values.items():
			sec[k] = v
		return self

	def __exit__(self, *exc) -> None:
		sec = conf[self.section]
		for k, v in self.old.items():
			sec[k] = v


class SpeechMock:
	"""Sustituye las funciones de voz y guarda lo que se dice."""

	def __enter__(self):
		self.said: list[str] = []
		self._patches = [
			mock.patch.object(speech, "speakMessage", side_effect=lambda t, *a, **k: self.said.append(t)),
			mock.patch.object(speech, "speakText", side_effect=lambda t, *a, **k: self.said.append(t)),
			mock.patch.object(speech, "speak", side_effect=lambda seq, *a, **k: self.said.extend(str(s) for s in seq)),
			mock.patch.object(speech, "cancelSpeech"),
		]
		for p in self._patches:
			p.start()
		return self

	def __exit__(self, *exc) -> None:
		for p in reversed(self._patches):
			p.stop()


# ====================================================================== marcas invisibles
class InvisibleMarksTests(unittest.TestCase):
	"""Las marcas de dirección escritas como escapes siguen quitándose."""

	def test_source_has_no_literal_marks(self) -> None:
		files = [
			os.path.join(ROOT, "src", "tiresias", "appmodules", "explorer.py"),
			os.path.join(WA_BASE, "appModules", "wa_strings.py"),
			os.path.join(WA_BASE, "appModules", "whatsapp_root.py"),
		]
		for path in files:
			with open(path, encoding="utf-8") as f:
				text = f.read()
			for ch in MARKS:
				self.assertNotIn(ch, text, f"{os.path.basename(path)}: U+{ord(ch):04X} literal")

	def test_explorer_removes_all_marks(self) -> None:
		from tiresias.appmodules import explorer

		dirty = "Reloj 16:22\n" + "".join(f"{m}0{i}" for i, m in enumerate(MARKS))
		clean = explorer.cleanText(dirty)
		for ch in MARKS:
			self.assertNotIn(ch, clean)
		self.assertEqual(clean, "Reloj 16:22 0001020304050607")

	def test_whatsapp_removes_marks_and_phones(self) -> None:
		root, S = _waModules()
		self.assertTrue(S.PHONE_RE.search("\u202a+34 600 12 34 56\u202c"))
		with confValues("whatsapp", {"filterPhoneNumbersInChats": False, "filterMaybePrefix": True, "filterHints": True}):
			out = root.cleanText("\u200eQuizás \u202aAna\u202c\u200f")
		self.assertEqual(out, "Ana")
		with confValues("whatsapp", {"filterPhoneNumbersInMessages": True}):
			out = root.cleanText("Hola \u202a+34 600 12 34 56\u202c adiós", isMessage=True)
		self.assertEqual(out, "Hola adiós")


# ====================================================================== gestor de módulos
class HandlerTests(unittest.TestCase):
	def test_frame_without_corewindow_is_not_cached(self) -> None:
		"""Un marco UWP sin CoreWindow todavía no queda asociado para siempre al marco."""
		from tiresias.appmodules import handler

		obj = Obj(processID=0, windowHandle=0x1234)
		names = {10: "applicationframehost", 20: "calculatorapp"}
		with mock.patch.object(handler.winapi, "getAncestor", return_value=0x1000), mock.patch.object(handler.winapi, "getWindowProcessId", return_value=10), mock.patch.object(handler.winapi, "getProcessName", side_effect=lambda pid: names.get(pid, "")), mock.patch.object(handler, "getAppModuleForPid", side_effect=lambda pid: pid):
			handler._hostPidCache.pop(0x1000, None)
			with mock.patch.object(handler, "_coreWindowPid", return_value=0):
				self.assertEqual(handler.getAppModuleForObject(obj), 10)
			self.assertNotIn(0x1000, handler._hostPidCache)
			with mock.patch.object(handler, "_coreWindowPid", return_value=20):
				self.assertEqual(handler.getAppModuleForObject(obj), 20)
			self.assertEqual(handler._hostPidCache.pop(0x1000), 20)

	def test_sleep_apps_case_insensitive(self) -> None:
		from tiresias.appmodules import AppModule, handler

		app = AppModule.__new__(AppModule)
		app.appName = "whatsapp.root"
		app.sleepMode = True
		old = conf["appModules"]["sleepApps"]
		try:
			conf["appModules"]["sleepApps"] = ["WhatsApp.Root", "notepad"]
			self.assertTrue(handler.isSleepPersistent(app))
			handler.setSleepMode(app, False, persist=True)
			self.assertEqual(conf["appModules"]["sleepApps"], ["notepad"])
			self.assertFalse(handler.isSleepPersistent(app))
			handler.setSleepMode(app, True, persist=True)
			handler.setSleepMode(app, True, persist=True)
			self.assertEqual(conf["appModules"]["sleepApps"], ["notepad", "whatsapp.root"])
		finally:
			conf["appModules"]["sleepApps"] = old


# ====================================================================== IME
class ImeTests(unittest.TestCase):
	def test_emoji_and_clipboard_items_are_not_candidates(self) -> None:
		from tiresias import ime

		textInputHost = types.SimpleNamespace(appName="textinputhost")
		grid = Obj("Emojis", Role.LIST, UIAAutomationId="TEMPLATE_PART_Items_GridView")
		emoji = Obj("cara sonriente", parent=grid, appModule=textInputHost)
		self.assertFalse(ime.isCandidateItem(emoji))
		history = Obj("Historial", Role.LIST, parent=Obj("", Role.PANE, parent=Obj("", Role.WINDOW)))
		clip = Obj("texto copiado", parent=history, appModule=textInputHost)
		self.assertFalse(ime.isCandidateItem(clip))

	def test_modern_and_classic_candidates(self) -> None:
		from tiresias import ime

		window = Obj("", Role.WINDOW, UIAAutomationId="IME_Candidate_Window")
		ui = Obj("", Role.PANE, parent=window)
		lst = Obj("", Role.LIST, parent=ui)
		item = Obj("你", parent=lst)
		self.assertTrue(ime.isCandidateItem(item))
		classic = Obj("", Role.LIST, UIAClassName="Microsoft.IME.CandidateWindow.View")
		self.assertTrue(ime.isCandidateItem(Obj("日", Role.BUTTON, parent=classic)))

	def test_all_candidates_on_new_page(self) -> None:
		from tiresias import ime

		plugin = ime.GlobalPlugin.__new__(ime.GlobalPlugin)
		plugin._lastList = None
		lst = Obj("", Role.LIST, UIAAutomationId="IME_Candidate_Window", runtimeId=(1, 2))
		page1 = [Obj(n, parent=lst, positionInfo={"indexInGroup": i + 1}) for i, n in enumerate(("你", "尼", "泥"))]
		lst.children = page1
		nxt = mock.Mock()
		with SpeechMock() as sp, confValues("inputComposition", {"autoReportAllCandidates": True, "announceSelectedCandidate": True}):
			plugin.event_selection(page1[0], nxt)
			plugin.event_selection(page1[1], nxt)
			page2 = [Obj(n, parent=lst, positionInfo={"indexInGroup": i + 1}) for i, n in enumerate(("拟", "逆"))]
			lst.children = page2
			plugin.event_selection(page2[0], nxt)
		nxt.assert_not_called()
		self.assertEqual(sp.said, ["1 你, 2 尼, 3 泥", "2 尼", "1 拟, 2 逆"])


# ====================================================================== consola
class ConsoleReaderTests(unittest.TestCase):
	def test_ctrl_handler(self) -> None:
		from tiresias import console_reader as cr

		self.assertTrue(cr._ctrlHandler(cr.CTRL_C_EVENT))
		self.assertTrue(cr._ctrlHandler(cr.CTRL_BREAK_EVENT))
		self.assertFalse(cr._ctrlHandler(2))  # cierre de la consola: lo normal

	def test_handler_installed_after_attach(self) -> None:
		from tiresias import console_reader as cr

		fake = mock.MagicMock()
		fake.AttachConsole.return_value = 1
		fake.CreateFileW.return_value = cr.INVALID_HANDLE
		fake.SetConsoleCtrlHandler.return_value = 1
		with mock.patch.object(cr, "kernel32", fake), mock.patch.object(cr, "_ctrlHandlerInstalled", False):
			self.assertIsNone(cr._readAttached(1234))
			fake.SetConsoleCtrlHandler.assert_called_once_with(cr._ctrlHandler, True)
			fake.FreeConsole.assert_called_once()
			cr._readAttached(1234)
			fake.SetConsoleCtrlHandler.assert_called_once()

	def test_no_handler_when_attach_fails(self) -> None:
		from tiresias import console_reader as cr

		fake = mock.MagicMock()
		fake.AttachConsole.return_value = 0
		with mock.patch.object(cr, "kernel32", fake), mock.patch.object(cr, "_ctrlHandlerInstalled", False), mock.patch.object(cr, "_useHelper", False):
			self.assertIsNone(cr._readAttached(1234))
		fake.SetConsoleCtrlHandler.assert_not_called()


# ====================================================================== PuTTY
class PuttyTests(unittest.TestCase):
	def test_timeout_cancels_clipboard_ignore(self) -> None:
		from tiresias import queue_handler
		from tiresias.appmodules import putty

		got = []
		with mock.patch.object(putty.winapi, "getClipboardText", return_value="antes"), mock.patch.object(putty.winapi.user32, "GetClipboardSequenceNumber", return_value=7), mock.patch.object(putty.winapi.user32, "PostMessageW"), mock.patch.object(putty.clipboard, "ignoreNextChange") as ign, mock.patch.object(putty.clipboard, "cancelIgnore") as cancel, mock.patch.object(queue_handler, "callLater", side_effect=lambda ms, f, *a: f(*a)):
			putty.readTerminal(0x99, got.append, attempts=3)
		self.assertEqual(got, [None])
		ign.assert_called_once()
		cancel.assert_called_once()

	def test_copy_restores_clipboard(self) -> None:
		from tiresias import queue_handler
		from tiresias.appmodules import putty

		seq = iter([7, 8])
		got = []
		with mock.patch.object(putty.winapi, "getClipboardText", side_effect=["antes", "$ ls\r\nuno"]), mock.patch.object(putty.winapi, "setClipboardText") as setText, mock.patch.object(putty.winapi.user32, "GetClipboardSequenceNumber", side_effect=lambda: next(seq)), mock.patch.object(putty.winapi.user32, "PostMessageW"), mock.patch.object(putty.clipboard, "ignoreNextChange"), mock.patch.object(putty.clipboard, "cancelIgnore") as cancel, mock.patch.object(queue_handler, "callLater", side_effect=lambda ms, f, *a: f(*a)):
			putty.readTerminal(0x99, got.append)
		self.assertEqual(got, ["$ ls\r\nuno"])
		setText.assert_called_once_with("antes")
		cancel.assert_not_called()

	def test_scripts(self) -> None:
		from tiresias.appmodules import putty

		app = putty.AppModule.__new__(putty.AppModule)
		app._lastText = "$ ls\r\nuno\r\n$ "
		text = "$ ls\r\nuno\r\n$ pwd\r\n/home\r\n$ "
		with SpeechMock() as sp, mock.patch.object(putty, "terminalWindow", return_value=0x99), mock.patch.object(putty, "readTerminal", side_effect=lambda hwnd, cb: cb(text)):
			app.script_readNew(Gesture())
			app.script_readLastLine2(Gesture())
			app.script_readLastLine9(Gesture())
			with mock.patch("tiresias.gui.showBrowseableMessage") as show:
				app.script_viewTerminal(Gesture())
			show.assert_called_once()
		self.assertEqual(sp.said, ["$ pwd\n/home\n$", "/home", "No hay tantas líneas"])
		with SpeechMock() as sp, mock.patch.object(putty, "terminalWindow", return_value=0):
			app.script_readLastLine1(Gesture())
		self.assertEqual(sp.said, ["No hay ninguna terminal en primer plano"])


# ====================================================================== búsqueda de Inicio
class SearchHostTests(unittest.TestCase):
	def test_selection_of_focus_not_repeated(self) -> None:
		from tiresias.appmodules import searchhost

		app = searchhost.AppModule.__new__(searchhost.AppModule)
		app._last = (None, 0.0)
		app._checkSeq = 0
		app._lastSuggestion = None
		item = Obj("Bloc de notas", runtimeId=(1,))
		nxt = mock.Mock()
		with mock.patch.object(searchhost.api, "getFocusObject", return_value=item), mock.patch.object(searchhost.presentation, "speakObject") as spk, mock.patch.object(speech, "cancelSpeech") as cancel:
			app.event_selection(item, nxt)
		spk.assert_not_called()
		cancel.assert_not_called()
		nxt.assert_called_once()
		edit = Obj("Buscar", Role.EDITABLETEXT)
		with mock.patch.object(searchhost.api, "getFocusObject", return_value=edit), mock.patch.object(searchhost.presentation, "speakObject") as spk, mock.patch.object(speech, "cancelSpeech"):
			app.event_selection(item, nxt)
			app.event_selection(item, nxt)
		spk.assert_called_once()


# ====================================================================== WhatsApp
class WhatsAppTests(unittest.TestCase):
	def setUp(self) -> None:
		if not os.path.isdir(WA_BASE):
			self.skipTest("sin complemento de WhatsApp")
		self.wa, self.S = _waModules()

	def _node(self, name="", ct=0, cls="", children=(), **kw):
		n = self.wa.Node.__new__(self.wa.Node)
		n.el = kw.pop("el", None)
		n.name = name
		n.ct = ct
		n.cls = cls
		n.aid = ""
		n.aria = kw.pop("aria", "")
		n.focusable = kw.pop("focusable", False)
		n.hasFocus = False
		n.rangeValue = kw.pop("rangeValue", None)
		n.rangeMax = kw.pop("rangeMax", None)
		n.selected = kw.pop("selected", False)
		n.value = ""
		n.depth = 0
		n.parent = None
		n.children = list(children)
		for c in n.children:
			c.parent = n
		return n

	def _app(self):
		app = self.wa.AppModule.__new__(self.wa.AppModule)
		app._lastReadIndex = -1
		app._lastFocusedMessage = None
		app._instanceGestures = {}
		return app

	def test_incoming_message_with_delivery_words_is_read(self) -> None:
		uc = self.wa.uc
		incoming = self._node(cls="focusable-list-item", children=[self._node(cls="message-in x", children=[self._node("Ya te lo he enviado, está pendiente", uc.CT_TEXT)])])
		outgoing = self._node(cls="focusable-list-item", children=[self._node(cls="message-out", children=[self._node("hola", uc.CT_TEXT)])])
		self.assertFalse(self.wa.isOutgoingMessage(incoming, "Ya te lo he enviado, está pendiente 12:30"))
		self.assertTrue(self.wa.isOutgoingMessage(outgoing, "hola 12:30"))
		# Sin clases: se mantiene la búsqueda de las palabras de entrega.
		bare = self._node(cls="focusable-list-item", children=[self._node("hola", uc.CT_TEXT)])
		self.assertTrue(self.wa.isOutgoingMessage(bare, "hola 12:30 Leído"))
		self.assertFalse(self.wa.isOutgoingMessage(bare, "hola 12:30"))

	def test_options_complete_and_in_settings(self) -> None:
		opts = importlib.import_module("rev106_wa.appModules.wa_options")
		keys = [k for k, _l in opts.SETTINGS]
		self.assertEqual(sorted(keys), sorted(opts.DEFAULTS))
		self.assertIs(self.wa._SETTINGS, opts.SETTINGS)
		for k in opts.DEFAULTS:
			self.assertIn(k, conf["whatsapp"])
		# Cada opción se lee en el módulo.
		with open(self.wa.__file__, encoding="utf-8") as f:
			src = f.read()
		for k in keys:
			self.assertIn(f'"{k}"', src, k)

	def test_settings_panel_registered(self) -> None:
		from tiresias.gui import settings as S

		plugMod = importlib.import_module("rev106_wa.globalPlugins.whatsapp_opciones")
		try:
			plugin = plugMod.GlobalPlugin()
			self.assertIn(plugMod.PANEL_ID, S._panels)
			title, cls = S._panels[plugMod.PANEL_ID]
			self.assertEqual(cls.section, "whatsapp")
			opts = importlib.import_module("rev106_wa.appModules.wa_options")
			self.assertEqual([f.key for f in cls.fields], [k for k, _l in opts.SETTINGS])
			plugin.terminate()
			self.assertNotIn(plugMod.PANEL_ID, S._panels)
		finally:
			S.unregisterPanel(plugMod.PANEL_ID)

	def test_manual_has_anchors(self) -> None:
		with open(os.path.join(ROOT, "manual", "manual_usuario.html"), encoding="utf-8") as f:
			text = f.read()
		plugMod = importlib.import_module("rev106_wa.globalPlugins.whatsapp_opciones")
		self.assertIn(f'id="cat-{plugMod.PANEL_ID}"', text)
		opts = importlib.import_module("rev106_wa.appModules.wa_options")
		for k in opts.DEFAULTS:
			self.assertIn(f'id="opt-whatsapp-{k}"', text, k)

	def test_toggle_scripts(self) -> None:
		app = self._app()
		wa = conf["whatsapp"]
		with SpeechMock() as sp, confValues("whatsapp", {"autoReadNewMessages": True, "filterHints": True, "filterPhoneNumbersInChats": False}), mock.patch.object(self.wa.api, "getFocusObject", return_value=None):
			app.script_toggleAutoRead(Gesture())
			self.assertFalse(wa["autoReadNewMessages"])
			app.script_toggleHints(Gesture())
			self.assertFalse(wa["filterHints"])
			app.script_togglePhoneFilter(Gesture())
			self.assertTrue(wa["filterPhoneNumbersInChats"])
		self.assertEqual(len(sp.said), 3)

	def test_chat_title_twice_toggles_typing(self) -> None:
		app = self._app()
		with SpeechMock() as sp, confValues("whatsapp", {"announceTyping": True}), mock.patch.object(self.wa.inputCore, "getLastScriptRepeatCount", return_value=0), mock.patch.object(app, "_chatTitleAndStatus", return_value=("Ana", "en línea")):
			app.script_chatTitle(Gesture())
			with mock.patch.object(self.wa.inputCore, "getLastScriptRepeatCount", return_value=1):
				app.script_chatTitle(Gesture())
			self.assertFalse(conf["whatsapp"]["announceTyping"])
		self.assertEqual(sp.said, ["Ana. en línea", "Aviso de escribiendo desactivado"])

	def test_read_last_messages(self) -> None:
		uc = self.wa.uc
		app = self._app()
		msgs = [self._node(cls="focusable-list-item", children=[self._node(t, uc.CT_TEXT)]) for t in ("uno", "dos", "tres")]
		with SpeechMock() as sp, mock.patch.object(app, "_messages", return_value=msgs), mock.patch.object(self.wa.inputCore, "getLastScriptRepeatCount", return_value=0), confValues("whatsapp", {"filterHints": True}):
			app.script_readLastMessage1(Gesture())
			app.script_readLastMessage3(Gesture())
			app.script_readLastMessage4(Gesture())
			with mock.patch.object(self.wa.inputCore, "getLastScriptRepeatCount", return_value=1), mock.patch.object(app, "_focus") as focus:
				app.script_readLastMessage3(Gesture())
			focus.assert_called_once_with(msgs[0])
		self.assertEqual(sp.said, ["tres", "uno", "No hay 4 mensajes visibles"])

	def test_message_scripts_outside_message_pass_key(self) -> None:
		app = self._app()
		with SpeechMock(), mock.patch.object(self.wa.api, "getFocusObject", return_value=None):
			for name in ("script_copyMessage", "script_playPause", "script_messageMenu", "script_react"):
				g = Gesture()
				getattr(app, name)(g)
				if name != "script_react":
					g.send.assert_called_once()

	def test_go_to_chat_list_focuses_selected(self) -> None:
		uc = self.wa.uc
		app = self._app()
		cells = [self._node(f"chat {i}", uc.CT_DATAITEM, focusable=True, selected=(i == 1)) for i in range(3)]
		grid = self._node("Lista de chats", uc.CT_DATAGRID, children=cells)
		with SpeechMock() as sp, mock.patch.object(app, "_chatList", return_value=grid), mock.patch.object(app, "_focus", return_value=True) as focus:
			app.script_goToChatList(Gesture())
		focus.assert_called_once_with(cells[1])
		self.assertEqual(sp.said, [])

	def test_help_lists_every_script(self) -> None:
		app = self._app()
		with mock.patch("tiresias.gui.showBrowseableMessage") as show:
			app.script_help(Gesture())
		text = show.call_args[0][0]
		for _gid, name in type(app).iterClassGestures():
			doc = getattr(app, "script_" + name).__doc__
			self.assertIn(doc, text, name)

	def test_settings_script_runs_on_gui(self) -> None:
		app = self._app()
		with mock.patch("tiresias.gui.runOnGui") as run:
			app.script_settings(Gesture())
		run.assert_called_once_with(self.wa._showSettingsDialog)


# ====================================================================== órdenes de otras aplicaciones
class AppScriptsTests(unittest.TestCase):
	def _bare(self, modName):
		m = importlib.import_module(f"tiresias.appmodules.{modName}")
		app = m.AppModule.__new__(m.AppModule)
		app._instanceGestures = {}
		return m, app

	def test_chat_alert_mode_and_history(self) -> None:
		import collections

		m, app = self._bare("teams")
		app.history = collections.deque()
		with SpeechMock() as sp, confValues("chatApps", {"alertMode": "all"}):
			app.script_cycleAlertMode(Gesture())
			self.assertEqual(conf["chatApps"]["alertMode"], "beep")
			app.script_cycleAlertMode(Gesture())
			app.script_cycleAlertMode(Gesture())
			self.assertEqual(conf["chatApps"]["alertMode"], "all")
			app.script_alertHistory(Gesture())
		self.assertEqual(sp.said[-1], "No se ha recibido ningún aviso")
		app.history.append((0.0, "Ana se unió", "joinLeave"))
		app.appName = "ms-teams"
		with mock.patch("tiresias.gui.app_dialogs.showItemList") as show:
			app.script_alertHistory(Gesture())
		show.assert_called_once()

	def test_chat_read_last_and_copy(self) -> None:
		m, app = self._bare("discord")
		app._lastRead = None
		with SpeechMock() as sp, mock.patch.object(app, "lastMessages", return_value=["c", "b", "a"]), mock.patch("tiresias.input.core.getLastScriptRepeatCount", return_value=0):
			app.script_readLastMessage2(Gesture())
			app.script_readLastMessage10(Gesture())
			with mock.patch("tiresias.input.core.getLastScriptRepeatCount", return_value=1), mock.patch("tiresias.api.copyToClip") as copy:
				app.script_readLastMessage2(Gesture())
			copy.assert_called_once_with("b", notify=True)
		self.assertEqual(sp.said, ["b", "No hay 10 mensajes"])

	def test_explorer_read_details(self) -> None:
		m, app = self._bare("explorer")
		item = Obj("doc", Role.LISTITEM, UIAClassName="UIItem", children=[Obj("Tamaño", value="\u200e1 KB", UIAAutomationId="System.Size", UIAClassName="UIProperty")])
		with SpeechMock() as sp:
			with mock.patch.object(m.api, "getFocusObject", return_value=None):
				app.script_readDetails(Gesture())
			with mock.patch.object(m.api, "getFocusObject", return_value=item):
				app.script_readDetails(Gesture())
		self.assertEqual(sp.said, ["No hay ningún archivo seleccionado", "Tamaño 1 KB"])

	def test_foobar_times(self) -> None:
		m, app = self._bare("foobar2000")
		with SpeechMock() as sp, mock.patch.object(m.api, "getStatusBar", return_value=object()), mock.patch.object(m.api, "statusBarText", return_value="MP3 | 1:23 / 3:45"):
			app.script_elapsedTime(Gesture())
			app.script_remainingTime(Gesture())
			app.script_totalTime(Gesture())
		self.assertEqual(sp.said, ["1:23 transcurrido", "2:22 restante", "3:45 en total"])
		with SpeechMock() as sp, mock.patch.object(m.api, "getStatusBar", return_value=None):
			app.script_totalTime(Gesture())
		self.assertEqual(len(sp.said), 1)

	def test_winamp_scripts(self) -> None:
		from tiresias import queue_handler

		m, app = self._bare("winamp")
		values = {(m.IPC_GETOUTPUTTIME, 0): 83000, (m.IPC_GETOUTPUTTIME, 1): 225, (m.IPC_GET_SHUFFLE, 0): 1}
		with SpeechMock() as sp, mock.patch.object(app, "mainWindow", return_value=0x55), mock.patch.object(m, "ipc", side_effect=lambda h, msg, w=0: values.get((msg, w))):
			app.script_elapsedTime(Gesture())
			app.script_remainingTime(Gesture())
			app.script_totalTime(Gesture())
			focus = Obj("", Role.WINDOW, windowHandle=0x55)
			g = Gesture()
			with mock.patch("tiresias.api.getFocusObject", return_value=focus), mock.patch.object(m.winapi, "getClassName", return_value="Winamp v1.x"), mock.patch.object(queue_handler, "callLater", side_effect=lambda ms, f, *a: f(*a)):
				app.script_toggleShuffle(g)
			g.send.assert_called_once()
		self.assertEqual(sp.said, ["1:23 transcurrido", "2:22 restante", "3:45 en total", "aleatorio activado"])

	def test_ide_line_edit_and_kindle_page(self) -> None:
		from tiresias import queue_handler

		m, app = self._bare("devenv")
		g = Gesture()
		with mock.patch.object(queue_handler, "callLater") as later:
			app.script_lineEdit(g)
		g.send.assert_called_once()
		later.assert_called_once()
		self.assertEqual(dict(type(app).iterClassGestures()).get("kb:alt+uparrow"), "lineEdit")
		k, kapp = self._bare("kindle")
		for inBook, calls in ((False, 0), (True, 1)):
			g = Gesture()
			with mock.patch.object(k, "inBook", return_value=inBook), mock.patch.object(queue_handler, "callLater") as later:
				kapp.script_turnPage(g)
			g.send.assert_called_once()
			self.assertEqual(later.call_count, calls)


if __name__ == "__main__":
	unittest.main()
