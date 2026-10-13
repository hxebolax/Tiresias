"""Revisión 10.11: seguridad y privacidad (auditoría de hilos, cierre y seguridad).

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev1011_seguridad -v``

No instalan ganchos, no bloquean la sesión ni escriben en el registro de
Windows: todo lo que toca el sistema se simula.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_seguridad_")
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]

from tiresias import lock_guard, privacy, secure_env, winapi  # noqa: E402
from tiresias.config import conf, policy as policyModule  # noqa: E402
from tiresias.objects.roles import Role, State  # noqa: E402


class SecureMode:
	"""Activa el modo seguro de la política mientras dura el bloque."""

	def __enter__(self):
		self._old = policyModule.policy.secureMode
		policyModule.policy.secureMode = True
		return self

	def __exit__(self, *exc):
		policyModule.policy.secureMode = self._old


def script_reportCurrentFocus(gesture=None):
	pass


def script_showGui(gesture=None):
	pass


def script_speechHistory(gesture=None):
	pass


def script_navigatorObject_next(gesture=None):
	pass


def script_review_copy(gesture=None):
	pass


# ====================================================================== 1. pantalla de bloqueo
class LockScreenTests(unittest.TestCase):
	def test_lista_blanca(self):
		self.assertTrue(lock_guard.isScriptAllowedWhenLocked(script_reportCurrentFocus))
		self.assertTrue(lock_guard.isScriptAllowedWhenLocked(script_navigatorObject_next))
		self.assertFalse(lock_guard.isScriptAllowedWhenLocked(script_showGui))
		self.assertFalse(lock_guard.isScriptAllowedWhenLocked(script_speechHistory))
		self.assertFalse(lock_guard.isScriptAllowedWhenLocked(script_review_copy))

	def test_filtro_solo_con_sesion_bloqueada(self):
		with mock.patch.object(lock_guard, "_announceBlocked"):
			self.assertIs(lock_guard.filterScript(script_showGui, locked=lambda: False), script_showGui)
			self.assertIsNone(lock_guard.filterScript(script_showGui, locked=lambda: True))
			self.assertIs(lock_guard.filterScript(script_reportCurrentFocus, locked=lambda: True), script_reportCurrentFocus)
		self.assertIsNone(lock_guard.filterScript(None, locked=lambda: True))

	def test_orden_de_la_propia_pantalla_de_bloqueo(self):
		class Obj:
			processID = 1234

			def script_algo(self, gesture=None):
				pass

		with mock.patch.object(winapi, "getProcessName", return_value="lockapp"):
			self.assertTrue(lock_guard.isScriptAllowedWhenLocked(Obj().script_algo))
		with mock.patch.object(winapi, "getProcessName", return_value="explorer"):
			self.assertFalse(lock_guard.isScriptAllowedWhenLocked(Obj().script_algo))

	def test_ventanas_con_sesion_bloqueada(self):
		def _show():
			pass

		def _close():
			pass

		locked = lambda: True  # noqa: E731
		self.assertFalse(lock_guard.allowGuiCall(_show, locked=locked))
		self.assertTrue(lock_guard.allowGuiCall(_close, locked=locked))
		self.assertTrue(lock_guard.allowGuiCall(_show, locked=lambda: False))
		from tiresias.magnifier import magnifier

		self.assertTrue(lock_guard.allowGuiCall(magnifier._apply, locked=locked))

	def test_visores_ocultos_y_restaurados(self):
		class Win:
			def __init__(self):
				self.shown = True

			def Hide(self):
				self.shown = False

			def ShowWithoutActivating(self):
				self.shown = True

			def IsBeingDeleted(self):
				return False

			def __bool__(self):
				return True

		w = Win()
		with mock.patch.object(lock_guard, "_viewerWindows", return_value=[w]):
			lock_guard.onLockStateChanged(True)
			self.assertFalse(w.shown)
			lock_guard.onLockStateChanged(False)
			self.assertTrue(w.shown)

	def test_run_on_gui_rechaza(self):
		import wx

		from tiresias.gui import helpers

		called = []

		def _show():
			called.append(1)

		with mock.patch.object(wx, "GetApp", return_value=object()), mock.patch.object(wx, "IsMainThread", return_value=True), mock.patch.object(lock_guard, "isLocked", return_value=True):
			helpers.runOnGui(_show)
		self.assertEqual(called, [])
		with mock.patch.object(wx, "GetApp", return_value=object()), mock.patch.object(wx, "IsMainThread", return_value=True), mock.patch.object(lock_guard, "isLocked", return_value=False):
			helpers.runOnGui(_show)
		self.assertEqual(called, [1])


# ====================================================================== 2. escritorio seguro y modo seguro
class SecureDesktopTests(unittest.TestCase):
	def test_forzar_modo_seguro(self):
		self.assertTrue(secure_env.mustForceSecureMode(sid="S-1-5-18", desktop="Default"))
		self.assertTrue(secure_env.mustForceSecureMode(sid="S-1-5-21-1", desktop="Winlogon"))
		self.assertFalse(secure_env.mustForceSecureMode(sid="S-1-5-21-1", desktop="Default"))
		self.assertFalse(secure_env.mustForceSecureMode(sid="S-1-5-21-1", desktop=""))

	def test_este_proceso_no_es_system(self):
		self.assertFalse(secure_env.isSystemAccount())
		self.assertEqual(secure_env.threadDesktopName().lower(), "default")

	def test_carpetas_protegidas(self):
		roots = [r"C:\Program Files", r"C:\Windows"]
		self.assertTrue(secure_env.isTrustedDir(r"C:\Program Files\Java\bin", roots))
		self.assertFalse(secure_env.isTrustedDir(r"C:\Program Files Malo\bin", roots))
		self.assertFalse(secure_env.isTrustedDir(r"C:\Users\x\AppData\Local\Temp", roots))
		self.assertFalse(secure_env.isTrustedDir("", roots))

	def test_politica_modo_seguro(self):
		for f in ("openFiles", "fileDialogs", "logViewer", "remoteAccess", "ai"):
			self.assertIn(f, policyModule.SECURE_MODE_BLOCKED)
		with SecureMode():
			self.assertFalse(policyModule.isAllowed("openFiles"))
		self.assertTrue(policyModule.isAllowed("openFiles"))

	def test_startfile_bloqueado(self):
		calls = []
		guarded = secure_env.guardedStartfile(lambda *a, **k: calls.append(a))
		with mock.patch.object(secure_env, "_announceBlocked"):
			guarded("x")
			self.assertEqual(calls, [("x",)])
			with SecureMode(), self.assertRaises(OSError):
				guarded("y")
		self.assertEqual(calls, [("x",)])

	def test_cuadro_de_archivos_bloqueado(self):
		import wx

		class Base:
			def ShowModal(self):
				return wx.ID_OK

		Guarded = secure_env._guardedDialogClass(Base)
		self.assertEqual(Guarded().ShowModal(), wx.ID_OK)
		with SecureMode(), mock.patch.object(secure_env, "_announceBlocked"):
			self.assertEqual(Guarded().ShowModal(), wx.ID_CANCEL)

	def test_registro_hklm_con_secure(self):
		from tiresias.a11y import system

		vals = system._atValues(machine=True)
		self.assertIn("--secure", vals["StartParams"][1])
		self.assertNotIn("--secure", system._atValues()["StartParams"][1])
		# Desde el código fuente (o una copia portable) nunca se registra en HKLM.
		self.assertFalse(system.canRegisterMachineWide())

	def test_aplicar_registro_sin_tocar_el_registro(self):
		import winreg

		from tiresias.a11y import system

		old = conf["system"]["registerAsAT"]
		conf["system"]["registerAsAT"] = True
		try:
			with mock.patch.object(system, "_writeAT", return_value=True) as write, mock.patch.object(system, "_deleteOwnMachineAT") as delete, mock.patch.object(system, "canRegisterMachineWide", return_value=False):
				system.applyATRegistration()
			write.assert_called_once_with(winreg.HKEY_CURRENT_USER)
			delete.assert_called_once()
			with mock.patch.object(system, "_writeAT", return_value=True) as write, mock.patch.object(system, "_deleteOwnMachineAT"), mock.patch.object(system, "canRegisterMachineWide", return_value=True):
				system.applyATRegistration()
			write.assert_any_call(winreg.HKEY_LOCAL_MACHINE, machine=True)
		finally:
			conf["system"]["registerAsAT"] = old

	def test_ia_y_registro_bloqueados_en_modo_seguro(self):
		from tiresias.ai import keys

		with SecureMode(), mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-prueba"}):
			self.assertEqual(keys.getKey("anthropic"), "")
		from tiresias.gui import log_viewer

		with SecureMode(), mock.patch.object(log_viewer, "speakMessage") as speak, mock.patch.object(log_viewer, "runOnGui") as run:
			log_viewer.show()
		speak.assert_called_once()
		run.assert_not_called()

	def test_remoto_no_arranca_en_modo_seguro(self):
		from tiresias import remote

		with SecureMode(), mock.patch.object(remote, "_initialized", False), mock.patch.object(remote, "_client", None):
			remote.initialize()
			self.assertIsNone(remote._client)


# ====================================================================== 3. Java Access Bridge
class JabTests(unittest.TestCase):
	def test_elevado_solo_carpetas_protegidas(self):
		from tiresias.a11y import jab

		app = r"C:\Users\alguien\Descargas\app"
		with mock.patch.object(secure_env, "isElevated", return_value=True):
			paths_ = jab.candidateDllPaths([app])
			self.assertFalse(any(p.lower().startswith(app.lower()) for p in paths_))
			self.assertTrue(all(secure_env.isTrustedDir(os.path.dirname(p)) for p in paths_))
		with mock.patch.object(secure_env, "isElevated", return_value=False):
			self.assertTrue(jab.candidateDllPaths([app])[0].lower().startswith(app.lower()))

	def test_jabswitch_de_carpeta_no_protegida(self):
		from tiresias.a11y import jab

		dll = r"C:\Users\alguien\Descargas\app\WindowsAccessBridge-64.dll"
		with mock.patch.object(jab, "_dllPath", dll), mock.patch.object(secure_env, "isElevated", return_value=True), mock.patch.object(jab, "candidateDllPaths", return_value=[]), mock.patch.object(jab.os.path, "isfile", return_value=True):
			self.assertEqual(jab.findJabswitch(), "")


# ====================================================================== 4. portapapeles
class ClipboardTests(unittest.TestCase):
	def setUp(self):
		from tiresias import clipboard

		self.cb = clipboard
		self._history = list(clipboard.history)
		clipboard.history.clear()

	def tearDown(self):
		self.cb.history[:] = self._history

	def _fakeUser32(self, available: set[str]):
		ids = {name: i + 0xC100 for i, name in enumerate(self.cb.SENSITIVE_FORMATS + (self.cb.HISTORY_FORMAT,))}
		fake = SimpleNamespace(IsClipboardFormatAvailable=lambda fid: any(ids[n] == fid for n in available))
		return fake, ids

	def test_formatos_protegidos(self):
		fake, ids = self._fakeUser32({"ExcludeClipboardContentFromMonitorProcessing"})
		with mock.patch.object(self.cb, "_user32", return_value=fake), mock.patch.object(self.cb, "_formatId", side_effect=lambda n: ids[n]):
			self.assertTrue(self.cb.isSensitiveContent())
		fake, ids = self._fakeUser32({"CanIncludeInClipboardHistory"})
		with mock.patch.object(self.cb, "_user32", return_value=fake), mock.patch.object(self.cb, "_formatId", side_effect=lambda n: ids[n]):
			with mock.patch.object(self.cb, "_readDword", return_value=0):
				self.assertTrue(self.cb.isSensitiveContent())
			with mock.patch.object(self.cb, "_readDword", return_value=1):
				self.assertFalse(self.cb.isSensitiveContent())
			with mock.patch.object(self.cb, "_readDword", return_value=None):
				self.assertTrue(self.cb.isSensitiveContent())
		fake, ids = self._fakeUser32(set())
		with mock.patch.object(self.cb, "_user32", return_value=fake), mock.patch.object(self.cb, "_formatId", side_effect=lambda n: ids[n]):
			self.assertFalse(self.cb.isSensitiveContent())

	def test_contrasena_copiada_no_se_guarda_ni_se_dice(self):
		cb = self.cb
		seq = [cb._lastSeq + 7]
		with (
			mock.patch.object(winapi.user32, "GetClipboardSequenceNumber", side_effect=lambda: seq[0]),
			mock.patch.object(winapi, "getClipboardText", return_value="MiContraseña123"),
			mock.patch.object(cb, "isSensitiveContent", return_value=True),
			mock.patch.object(cb.speech, "speakMessage") as speak,
		):
			cb._check()
		self.assertEqual(cb.history, [])
		self.assertFalse(any("MiContraseña123" in str(c) for c in speak.call_args_list))
		with mock.patch.object(cb, "isSensitiveContent", return_value=True), mock.patch("tiresias.imaging.getClipboardFiles", return_value=[]):
			self.assertNotIn("MiContraseña123", cb.describeContents())


# ====================================================================== 5. adjuntos de Outlook
class OutlookTests(unittest.TestCase):
	def test_extensiones_con_punto_o_espacio_final(self):
		from tiresias.appmodules import outlook

		for name in ("factura.exe.", "factura.exe ", "factura.exe. . ", "a.lnk.", "disco.iso", "x.vhdx", "app.jar"):
			self.assertTrue(outlook.isBlocked(name), name)
		for name in ("informe.pdf", "foto.jpg", "texto.txt"):
			self.assertFalse(outlook.isBlocked(name), name)

	def test_marca_de_internet(self):
		from tiresias.appmodules import outlook

		folder = tempfile.mkdtemp(prefix="tiresias_motw_")
		path = os.path.join(folder, "a.docx")
		with open(path, "wb") as f:
			f.write(b"x")
		if outlook.markFromInternet(path):
			with open(path + ":Zone.Identifier", encoding="ascii") as f:
				self.assertIn("ZoneId=3", f.read())


# ====================================================================== 6 y 7. registro y eco
class PrivacyTests(unittest.TestCase):
	def test_is_protected(self):
		class Obj:
			def __init__(self, role, states):
				self.role = role
				self.states = states

		class Broken:
			@property
			def role(self):
				raise OSError("COM")

		class NoStates:
			role = Role.EDITABLETEXT

		self.assertTrue(privacy.isProtected(Obj(Role.PASSWORDEDIT, set())))
		self.assertTrue(privacy.isProtected(Obj(Role.EDITABLETEXT, {State.PROTECTED})))
		self.assertFalse(privacy.isProtected(Obj(Role.EDITABLETEXT, {State.FOCUSED})))
		self.assertTrue(privacy.isProtected(Broken()))
		self.assertFalse(privacy.isProtected(NoStates()))
		self.assertFalse(privacy.isProtected(None))

	def test_registro_sin_caracteres(self):
		from tiresias.input.gestures import KeyboardGesture

		g = KeyboardGesture(0x41, 0x1E, False, frozenset(), "a")
		g.char = "a"
		self.assertEqual(privacy.gestureLogName(g), "kb:<carácter>")
		g2 = KeyboardGesture(0x41, 0x1E, False, frozenset({"shift"}), "a")
		g2.char = "A"
		self.assertEqual(privacy.gestureLogName(g2), "kb:<carácter>")
		g3 = KeyboardGesture(0x4E, 0x31, False, frozenset({"tiresias"}), "n")
		self.assertIn("tiresias", privacy.gestureLogName(g3))
		g4 = KeyboardGesture(0x27, 0, True, frozenset(), "rightArrow")
		self.assertEqual(privacy.gestureLogName(g4), "kb:rightArrow")

	def test_eco_contrasena(self):
		from tiresias import speech, typing_echo

		class Pwd:
			role = Role.EDITABLETEXT
			states = {State.PROTECTED}
			isEditable = True

		old = conf["keyboard"]["speakTypedCharacters"]
		conf["keyboard"]["speakTypedCharacters"] = "always"
		typing_echo._recent.clear()
		try:
			with mock.patch.object(speech, "speak") as speak, mock.patch.object(speech, "speakTypedCharacter") as typed:
				typing_echo.onTypedCharacter(Pwd(), "s")
			typed.assert_not_called()
			self.assertIn("*", str(speak.call_args))
			self.assertEqual(len(typing_echo._recent), 0)
		finally:
			conf["keyboard"]["speakTypedCharacters"] = old

	def test_entrada_braille_en_contrasena(self):
		from tiresias import api, speech
		from tiresias.braille import input as brailleInput

		pwd = SimpleNamespace(role=Role.PASSWORDEDIT, states=set())
		old = conf["keyboard"]["speakTypedCharacters"]
		conf["keyboard"]["speakTypedCharacters"] = "always"
		try:
			with (
				mock.patch.object(brailleInput.winapi, "typeText"),
				mock.patch.object(api, "getFocusObject", return_value=pwd),
				mock.patch.object(speech, "speak") as speak,
				mock.patch.object(speech, "speakTypedCharacter") as typed,
			):
				brailleInput.BrailleInputHandler()._type("k")
			typed.assert_not_called()
			self.assertIn("*", str(speak.call_args))
		finally:
			conf["keyboard"]["speakTypedCharacters"] = old


# ====================================================================== 8. Audiocinemateca
ADDON = os.path.join(ROOT, "complementos_tienda", "audiocinemateca")
PKG = "tiresias_addon_audiocinemateca_pruebas"


def _addonModule(name: str):
	for pkg, path in ((PKG, ADDON), (PKG + ".globalPlugins", os.path.join(ADDON, "globalPlugins"))):
		if pkg not in sys.modules:
			m = types.ModuleType(pkg)
			m.__path__ = [path]  # type: ignore[attr-defined]
			sys.modules[pkg] = m
	full = PKG + ".globalPlugins.audiocinemateca"
	if full not in sys.modules:
		carpeta = os.path.join(ADDON, "globalPlugins", "audiocinemateca")
		m = types.ModuleType(full)
		m.__path__ = [carpeta]  # type: ignore[attr-defined]
		sys.modules[full] = m
	return importlib.import_module(full + "." + name)


class AudiocinematecaTests(unittest.TestCase):
	def test_nombre_sin_recorrido_de_ruta(self):
		red = _addonModule("red")
		url = "https://audiocinemateca.com/f/%2E%2E%5C%2E%2E%5CAppData%5CRoaming%5CStartup%5Cx.bat"
		self.assertEqual(red.nombreArchivoUrl(url), "x.bat")
		self.assertEqual(red.nombreArchivoUrl("https://a.com/x/%2E%2E"), "")
		self.assertEqual(red.nombreArchivoUrl("https://a.com/x/mi%20pel%C3%ADcula.mp3"), "mi película.mp3")
		descargas = _addonModule("descargas")
		item = descargas.ItemDescarga(url, r"C:\Musica")
		self.assertEqual(os.path.dirname(item.rutaCompleta), r"C:\Musica")

	def test_credenciales_solo_a_la_audiocinemateca(self):
		red = _addonModule("red")
		self.assertTrue(red.peticion("https://audiocinemateca.com/a.mp3", "u", "c").get_header("Authorization"))
		self.assertTrue(red.peticion("https://www.audiocinemateca.com/a.mp3", "u", "c").get_header("Authorization"))
		self.assertIsNone(red.peticion("http://audiocinemateca.com/a.mp3", "u", "c").get_header("Authorization"))
		self.assertIsNone(red.peticion("https://otro.com/a.mp3", "u", "c").get_header("Authorization"))
		self.assertIsNone(red.peticion("https://audiocinemateca.com.malo.com/a.mp3", "u", "c").get_header("Authorization"))
		req = red.peticion("https://audiocinemateca.com/a.mp3", "u", "c")
		# No redirigible: urllib no la copia al seguir una redirección.
		self.assertNotIn("Authorization", req.headers)
		self.assertIn("Authorization", req.unredirected_hdrs)

	def test_reintento_tras_redireccion_interna(self):
		red = _addonModule("red")
		calls = []

		def urlopen(req, timeout=None):
			calls.append(req.full_url)
			if len(calls) == 1:
				raise urllib.error.HTTPError("https://www.audiocinemateca.com/b.mp3", 401, "Unauthorized", {}, None)
			return "ok"

		with mock.patch.object(red.urllib.request, "urlopen", side_effect=urlopen):
			self.assertEqual(red.abrir("https://audiocinemateca.com/a.mp3", "u", "c"), "ok")
		self.assertEqual(calls, ["https://audiocinemateca.com/a.mp3", "https://www.audiocinemateca.com/b.mp3"])

		def urlopen2(req, timeout=None):
			raise urllib.error.HTTPError("https://malo.com/b.mp3", 401, "Unauthorized", {}, None)

		with mock.patch.object(red.urllib.request, "urlopen", side_effect=urlopen2), self.assertRaises(urllib.error.HTTPError):
			red.abrir("https://audiocinemateca.com/a.mp3", "u", "c")

	def test_version_del_manifiesto(self):
		import json

		with open(os.path.join(ADDON, "manifest.json"), encoding="utf-8") as f:
			self.assertEqual(json.load(f)["version"], "1.0.1")


# ====================================================================== 9. desinstalación y 16. copia al sistema
class InstallerTests(unittest.TestCase):
	def test_orden_sin_archivo_temporal(self):
		from tiresias import installer

		line = installer.uninstallCommandLine(r"C:\Program Files\Tiresias")
		self.assertIn("cmd.exe", line.lower())
		self.assertIn(r'rmdir /s /q "C:\Program Files\Tiresias"', line)
		self.assertNotIn(".cmd", line.lower().replace("cmd.exe", ""))
		self.assertIsNone(installer.uninstallCommandLine(r"C:\a%PATH%b"))
		self.assertIsNone(installer.uninstallCommandLine('C:\\a"b'))

	def test_copia_sin_enlaces(self):
		from tiresias import installer

		src = tempfile.mkdtemp(prefix="tiresias_cfg_src_")
		dst = os.path.join(tempfile.mkdtemp(prefix="tiresias_cfg_dst_"), "systemConfig")
		with open(os.path.join(src, "config.json"), "w", encoding="utf-8") as f:
			f.write("{}")
		with open(os.path.join(src, "enlace.json"), "w", encoding="utf-8") as f:
			f.write("{}")
		with mock.patch.object(installer, "isLink", side_effect=lambda p: p.endswith("enlace.json")):
			installer.copyConfigToSystem(src, dst)
		self.assertTrue(os.path.isfile(os.path.join(dst, "config.json")))
		self.assertFalse(os.path.exists(os.path.join(dst, "enlace.json")))


# ====================================================================== 10. hilos de Office
class OfficeTests(unittest.TestCase):
	def test_tope_de_hilos_colgados(self):
		from tiresias.appmodules import _office

		w = _office._Worker()
		release = threading.Event()
		started = []

		def hang():
			started.append(1)
			release.wait(5)

		with mock.patch.object(_office._Worker, "MAX_HUNG_THREADS", 1):
			with self.assertRaises(_office.OfficeBusy):
				w.call(hang, (), 0.05)
			with self.assertRaises(_office.OfficeBusy):
				w.call(hang, (), 0.05)
			self.assertEqual(len(w._hung), 1)
			before = threading.active_count()
			with self.assertRaises(_office.OfficeBusy):
				w.call(hang, (), 0.05)
			self.assertLessEqual(threading.active_count(), before)
		release.set()
		deadline = time.monotonic() + 3
		while w._hung and time.monotonic() < deadline:
			time.sleep(0.02)
		self.assertEqual(w._hung, set())
		w.stop()


# ====================================================================== 11. caché de nombres de proceso
class ProcessNameTests(unittest.TestCase):
	def test_caduca(self):
		pid = 987654
		winapi._processNameCache.pop(pid, None)
		with mock.patch.object(winapi, "getProcessImagePath", return_value=r"C:\x\lockapp.exe"):
			self.assertEqual(winapi.getProcessName(pid), "lockapp")
		with mock.patch.object(winapi, "getProcessImagePath", return_value=r"C:\x\malo.exe"):
			self.assertEqual(winapi.getProcessName(pid), "lockapp")
			winapi._processNameCache[pid] = ("lockapp", time.monotonic() - winapi.PROCESS_NAME_TTL - 1)
			self.assertEqual(winapi.getProcessName(pid), "malo")
		winapi._processNameCache.pop(pid, None)


# ====================================================================== 12 y 13. hilos de la interfaz
class GuiThreadTests(unittest.TestCase):
	def test_consola_ejecuta_en_el_nucleo(self):
		import code

		import wx

		from tiresias import queue_handler
		from tiresias.gui import python_console

		fake = SimpleNamespace(console=code.InteractiveConsole({}), more=False)
		fake._executeOnCore = lambda line: python_console.PythonConsoleFrame._executeOnCore(fake, line)
		fake._showResult = mock.Mock()
		queued = []
		with mock.patch.object(queue_handler, "queueFunction", side_effect=lambda f, *a: queued.append((f, a))):
			python_console.PythonConsoleFrame.execute(fake, "x = 6 * 7")
		self.assertEqual(len(queued), 1)
		with mock.patch.object(wx, "CallAfter") as after:
			queued[0][0](*queued[0][1])
		self.assertEqual(fake.console.locals["x"], 42)
		after.assert_called_once()

	def test_visor_ocr_desde_otro_hilo(self):
		from tiresias.gui import ocr_viewer

		result = []
		with mock.patch.object(ocr_viewer, "_dialogHwnd", 0):
			t = threading.Thread(target=lambda: result.append(ocr_viewer.isOpen()))
			t.start()
			t.join(5)
		self.assertEqual(result, [False])

	def test_ventana_principal_por_hwnd(self):
		from tiresias import gui
		from tiresias.objects import base

		with mock.patch.object(gui, "mainFrameHwnd", 4242), mock.patch.object(base, "_hiddenMainHwnd", 0):
			self.assertTrue(base.isHiddenMainWindow(4242))
			self.assertFalse(base.isHiddenMainWindow(1))


# ====================================================================== 14. claves remotas
class RemoteStoreTests(unittest.TestCase):
	def test_sin_cifrar_no_se_guarda(self):
		import json

		from tiresias.remote import dpapi, store

		folder = tempfile.mkdtemp(prefix="tiresias_remstore_")
		path = os.path.join(folder, "remoto.json")
		s = store.RemoteStore(path)
		with mock.patch.object(dpapi, "protect", side_effect=OSError("DPAPI")):
			s._data.presets.append(store.Preset(name="Casa", host="h", key="secreto"))
			s._data.autoconnectData = store.Preset(name="Auto", host="h", key="otro-secreto") if s._data.autoconnectData is None else s._data.autoconnectData
			s.save()
		with open(path, encoding="utf-8") as f:
			text = f.read()
		self.assertNotIn("secreto", text)
		json.loads(text)


# ====================================================================== 17. lupa y 18. Tesseract
class MiscTests(unittest.TestCase):
	def test_lupa_agrupa_movimientos(self):
		from tiresias.magnifier import Magnifier

		m = Magnifier()
		m.active = True
		runs = []
		with mock.patch.object(Magnifier, "view", new_callable=mock.PropertyMock, return_value="lens"), mock.patch.object(m, "_run", side_effect=lambda f, *a: runs.append(f)):
			for i in range(20):
				m.follow(100 + i, 100, "mouse")
		self.assertEqual(len(runs), 1)
		m._followPending = 0.0
		with mock.patch.object(Magnifier, "view", new_callable=mock.PropertyMock, return_value="lens"), mock.patch.object(m, "_run", side_effect=lambda f, *a: runs.append(f)):
			m.follow(300, 300, "mouse")
		self.assertEqual(len(runs), 2)

	def test_tesseract_sin_carpeta_actual(self):
		from tiresias import ocr

		eng = ocr.TesseractEngine()
		seen = []

		def isfile(p):
			seen.append(p)
			return False

		old = conf["ocr"]["tesseractPath"]
		conf["ocr"]["tesseractPath"] = ""
		try:
			with mock.patch.dict(os.environ, {"PATH": ".;relativa;C:\\Tess"}), mock.patch.object(ocr.os.path, "isfile", side_effect=isfile):
				self.assertIsNone(eng.executable())
		finally:
			conf["ocr"]["tesseractPath"] = old
		self.assertIn(os.path.join("C:\\Tess", "tesseract.exe"), seen)
		self.assertFalse(any(p.startswith(".") or p.startswith("relativa") for p in seen))

	def test_set_foreground_no_adjunta_si_no_responde(self):
		u = winapi.user32
		with (
			mock.patch.object(winapi, "getForegroundWindow", return_value=111),
			mock.patch.object(winapi, "getWindowThreadId", side_effect=lambda h: {111: 5, 222: 6}.get(h, 0)),
			mock.patch.object(winapi.kernel32, "GetCurrentThreadId", return_value=6),
			mock.patch.object(winapi, "windowResponds", side_effect=lambda h, *a: h != 111),
			mock.patch.object(u, "AttachThreadInput") as attach,
			mock.patch.object(u, "ShowWindow"),
			mock.patch.object(u, "ShowWindowAsync"),
			mock.patch.object(u, "BringWindowToTop"),
			mock.patch.object(u, "SetForegroundWindow", return_value=1),
		):
			self.assertTrue(winapi.setForegroundWindow(222))
		attach.assert_not_called()

	def test_set_foreground_ventana_colgada(self):
		u = winapi.user32
		with (
			mock.patch.object(winapi, "getForegroundWindow", return_value=111),
			mock.patch.object(winapi, "getWindowThreadId", side_effect=lambda h: {111: 5, 333: 7}.get(h, 0)),
			mock.patch.object(winapi.kernel32, "GetCurrentThreadId", return_value=6),
			mock.patch.object(winapi, "windowResponds", return_value=False),
			mock.patch.object(u, "SetForegroundWindow") as sfw,
		):
			self.assertFalse(winapi.setForegroundWindow(333))
		sfw.assert_not_called()

	def test_window_responds(self):
		with mock.patch.object(winapi.user32, "IsHungAppWindow", return_value=1):
			self.assertFalse(winapi.windowResponds(123))
		self.assertFalse(winapi.windowResponds(0))


if __name__ == "__main__":
	unittest.main()
