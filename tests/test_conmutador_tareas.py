"""Pruebas del conmutador de tareas (Alt+Tab) y de los focos transitorios vacíos.

Fallo del registro del usuario (7-10-2026, 19:19:07): con el primer Alt+Tab
Windows 11 da el foco al elemento «Documento1 - Word» y, unos 150 ms después,
a un panel sin nombre de la isla XAML («Windows.UI.Input.InputSite.WindowClass»).
Ese foco vacío descartaba la voz del elemento (ya no era el foco) y el gestor
de voz reanudaba «Conmutación de tareas» desde el principio: el usuario oía el
conmutador dos veces y nunca la ventana elegida.

Se reproduce solo con eventos simulados: no se pulsa Alt+Tab de verdad ni se
toca ninguna ventana del usuario.

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

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_conmutador_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]

from tiresias import a11y  # noqa: E402,F401  (registra las opciones)
from tiresias import api, events, presentation, winapi  # noqa: E402
from tiresias.a11y import system, winevents  # noqa: E402
from tiresias.a11y import uia_client as uc  # noqa: E402
from tiresias.appmodules import explorer  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.objects.roles import Role, State  # noqa: E402
from tiresias.objects.uia import UIAObject  # noqa: E402
from tiresias.speech import api as speech  # noqa: E402
from tiresias.speech import languages  # noqa: E402
from tiresias.speech import plugin as speechPlugin  # noqa: E402
from tiresias.speech.commands import IndexCommand  # noqa: E402

# Ventanas simuladas: identificador -> clase.
HWND_SWITCHER = 0x100
HWND_INPUTSITE = 0x101
HWND_SOCIAL = 0x200
HWND_DESKTOP_APP = 0x300
_CLASSES = {
	HWND_SWITCHER: "XamlExplorerHostIslandWindow",
	HWND_INPUTSITE: explorer.INPUT_SITE_CLASS,
	HWND_SOCIAL: "WindowsForms10.Window.8.app.0.1",
	HWND_DESKTOP_APP: "Progman",
}
_ROOTS = {HWND_INPUTSITE: HWND_SWITCHER}


def _className(hwnd):
	return _CLASSES.get(hwnd, "")


def _ancestor(hwnd, flags=winapi.GA_ROOT):
	return _ROOTS.get(hwnd, hwnd)


class FakeSynth:
	"""Sintetizador falso: guarda lo que recibe."""

	name = "fake"
	language = "es_ES"
	availableLanguages = ("es_ES",)

	def __init__(self) -> None:
		self.sent: list[list] = []
		self.cancelled = 0

	def speak(self, seq: list) -> None:
		self.sent.append(list(seq))

	def cancel(self) -> None:
		self.cancelled += 1

	def pause(self, switch: bool) -> None:
		pass

	def getSetting(self, sid):
		return "v1" if sid == "voice" else 50

	def isSupported(self, sid) -> bool:
		return True

	@property
	def availableVoices(self):
		return {}

	def texts(self) -> list[str]:
		return [" ".join(x for x in seq if isinstance(x, str)).strip() for seq in self.sent]

	def lastIndex(self, i: int = -1) -> int:
		return [x.index for x in self.sent[i] if isinstance(x, IndexCommand)][-1]


class Obj:
	"""Objeto accesible simulado con los eventos por defecto de Tiresias."""

	treeInterceptor = None
	isPresentableFocusAncestor = True
	presentationType = "content"
	processID = 1
	UIAClassName = ""
	windowClassName = ""

	def __init__(self, name, role, parent=None, hwnd=0, app=None, value="") -> None:
		self.name = name
		self.role = role
		self.parent = parent
		self.windowHandle = hwnd
		self.appModule = app
		self.value = value
		self.states = {State.FOCUSABLE}

	@property
	def ancestors(self) -> list:
		out = []
		p = self.parent
		while p is not None:
			out.insert(0, p)
			p = p.parent
		return out

	def __repr__(self) -> str:
		return f"<Obj {self.role.name} {self.name!r}>"

	def event_gainFocus(self) -> None:
		presentation.speakObject(self, reason=presentation.Reason.FOCUS)

	def event_foreground(self) -> None:
		speech.cancelSpeech()
		presentation.speakObject(self, reason=presentation.Reason.FOREGROUND)

	def event_focusEntered(self) -> None:
		events._focusEnteredDefault(self)

	def event_loseFocus(self) -> None:
		pass


def _fakeSpeakObject(obj, reason=presentation.Reason.QUERY, isValid=None) -> None:
	"""Como ``presentation.speakObject`` pero sin consultar propiedades reales."""
	text = obj.name + (" lista" if obj.role == Role.LIST else "")
	if not text.strip():
		return
	if reason in (presentation.Reason.FOCUS, presentation.Reason.FOCUSENTERED):
		speech.speak([text], origin=speech.ORIGIN_FOCUS, isValid=isValid if isValid is not None else presentation._focusValidator(obj, reason))
	else:
		speech.speak([text])


class _FakeElement:
	def __init__(self, props: dict) -> None:
		self.props = props

	def GetCachedPropertyValueEx(self, propId, ignoreDefault):
		return self.props.get(propId)

	def GetCurrentPropertyValueEx(self, propId, ignoreDefault):
		return self.props.get(propId)


class _FakeUIA(UIAObject):
	"""Objeto UIA con propiedades fijas y el módulo de aplicación que se le diga."""

	def __init__(self, props: dict, hwnd: int, app) -> None:
		super().__init__(_FakeElement(props), windowHandle=hwnd)
		self._app = app

	def _get_appModule(self):
		return self._app

	def _get_windowClassName(self) -> str:
		return _className(self._windowHandle)


class _Scenario(unittest.TestCase):
	"""Escenario del registro: SocialRSS con el foco y luego Alt+Tab."""

	def setUp(self) -> None:
		from tiresias import synth
		from tiresias.input import core as inputCore

		self.synth = FakeSynth()
		self._oldSynth = synth._current
		synth._current = self.synth  # type: ignore[assignment]
		languages._supportedCache = None
		speech._manager = None
		self.mgr = speech.getManager()
		self._oldConf = {
			"speechMode": conf["speech"]["speechMode"],
			"cancelExpired": conf["speech"]["cancelExpiredFocusSpeech"],
			"ancestors": conf["presentation"]["announceFocusAncestors"],
		}
		conf["speech"]["speechMode"] = "talk"
		conf["speech"]["cancelExpiredFocusSpeech"] = True
		conf["presentation"]["announceFocusAncestors"] = True
		self.altDown = True
		patches = [
			mock.patch.object(presentation, "speakObject", _fakeSpeakObject),
			mock.patch.object(system, "isSecureObject", return_value=False),
			mock.patch("tiresias.appmodules.handler.handleForegroundApp"),
			mock.patch("tiresias.tree_interceptor.update", return_value=None),
			mock.patch.object(inputCore, "manager", mock.Mock()),
			mock.patch.object(winapi, "getClassName", side_effect=_className),
			mock.patch.object(winapi, "getAncestor", side_effect=_ancestor),
			mock.patch.object(winapi, "isKeyDown", side_effect=lambda vk: self.altDown and vk == winapi.VK_MENU),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)
		api.post_focusChange.register(speechPlugin._onFocusChange)
		self.addCleanup(api.post_focusChange.unregister, speechPlugin._onFocusChange)
		api.setFocusObject(None, [])
		api.setForegroundObject(None)
		events._lastFocusAncestors = []
		events._lastFocusTime = 0.0
		# Árbol simulado.
		self.explorerApp = explorer.AppModule(4321, "explorer")
		self.desktop = Obj("Escritorio", Role.DESKTOPPANE)
		self.social = Obj("SocialRSS Accessible Suite", Role.WINDOW, self.desktop, HWND_SOCIAL)
		self.mastodon = Obj("Mastodon - Inicio", Role.LIST, self.social, HWND_SOCIAL)
		self.post = Obj("Jesús Pavón Abián", Role.LISTITEM, self.mastodon, HWND_SOCIAL)
		self.switcher = Obj("Conmutación de tareas", Role.WINDOW, self.desktop, HWND_SWITCHER, self.explorerApp)
		self.apps = Obj("Aplicaciones en ejecución", Role.LIST, self.switcher, HWND_INPUTSITE, self.explorerApp)
		self.word = Obj("Documento1 - Word", Role.LISTITEM, self.apps, HWND_INPUTSITE, self.explorerApp)
		self.whatsapp = Obj("WhatsApp Beta", Role.LISTITEM, self.apps, HWND_INPUTSITE, self.explorerApp)

	def tearDown(self) -> None:
		from tiresias import synth

		self.mgr.cancel()
		synth._current = self._oldSynth
		languages._supportedCache = None
		conf["speech"]["speechMode"] = self._oldConf["speechMode"]
		conf["speech"]["cancelExpiredFocusSpeech"] = self._oldConf["cancelExpired"]
		conf["presentation"]["announceFocusAncestors"] = self._oldConf["ancestors"]
		api.setFocusObject(None, [])
		api.setForegroundObject(None)
		events._lastFocusAncestors = []

	def focusSocial(self) -> None:
		self.altDown = False
		events.executeEvent("gainFocus", self.post)
		self.mgr.cancel()
		self.synth.sent.clear()
		self.altDown = True

	def inputSitePane(self) -> _FakeUIA:
		pane = _FakeUIA({uc.P_CONTROLTYPE: uc.CT_PANE, uc.P_NAME: "", uc.P_CLASSNAME: explorer.INPUT_SITE_CLASS}, HWND_INPUTSITE, self.explorerApp)
		pane._applyOverlays()
		return pane

	def finishSpeech(self) -> None:
		"""Deja que el sintetizador falso termine todo lo enviado."""
		for _ in range(20):
			if not self.mgr._sent:
				break
			self.mgr._indexReached(self.mgr._sent[0].endIndex)


class AltTabTests(_Scenario):
	def test_primer_alt_tab_dice_solo_la_ventana_elegida(self) -> None:
		self.focusSocial()
		events.executeEvent("gainFocus", self.word)
		self.finishSpeech()
		self.assertEqual(self.synth.texts(), ["Documento1 Word"])
		self.assertIs(api.getForegroundObject(), self.switcher)

	def test_foco_vacio_del_panel_no_corta_la_lectura(self) -> None:
		self.focusSocial()
		events.executeEvent("gainFocus", self.word)
		events.executeEvent("windowOpened", self.switcher)
		cancelled = self.synth.cancelled
		pane = self.inputSitePane()
		self.assertIsInstance(pane, explorer.TaskSwitcherInputSite)
		self.assertFalse(pane.shouldAllowFocusEvent)
		# La comprobación del foco (150 ms tras windowOpened) encuentra el panel.
		with mock.patch("tiresias.objects.uia.getFocusObject", return_value=pane), mock.patch.object(winevents, "_menuStillOpen", return_value=False):
			winevents._checkFocus()
		self.assertIs(api.getFocusObject(), self.word)
		self.assertEqual(self.synth.cancelled, cancelled, "el foco vacío no debe cortar la voz")
		self.finishSpeech()
		texts = self.synth.texts()
		self.assertEqual(texts, ["Documento1 Word"])
		self.assertNotIn("Conmutación de tareas", " ".join(texts))

	def test_siguiente_tab_no_repite_la_lista(self) -> None:
		self.focusSocial()
		events.executeEvent("gainFocus", self.word)
		self.finishSpeech()
		events.executeEvent("gainFocus", self.whatsapp)
		self.finishSpeech()
		self.assertEqual(self.synth.texts(), ["Documento1 Word", "WhatsApp Beta"])

	def test_sin_alt_se_anuncia_el_conmutador(self) -> None:
		# Windows+Tab o Control+Alt+Tab (Alt suelta): se dice dónde se está.
		self.focusSocial()
		self.altDown = False
		events.executeEvent("gainFocus", self.word)
		self.finishSpeech()
		self.assertEqual(self.synth.texts(), ["Conmutación de tareas", "Aplicaciones en ejecución lista", "Documento1 Word"])

	def test_la_seleccion_tras_el_foco_no_repite(self) -> None:
		self.focusSocial()
		events.executeEvent("gainFocus", self.word)
		before = len(self.synth.sent)
		with mock.patch.object(presentation, "speakObject") as speak:
			self.explorerApp.event_selection(self.word, lambda: None)
		speak.assert_not_called()
		self.assertEqual(len(self.synth.sent), before)

	def test_panel_input_site(self) -> None:
		pane = mock.Mock(role=Role.PANE, UIAClassName=explorer.INPUT_SITE_CLASS, windowClassName="", windowHandle=0)
		pane.name = ""
		self.assertTrue(explorer.isTaskSwitcherInputSite(pane))
		pane.name = "Algo"
		self.assertFalse(explorer.isTaskSwitcherInputSite(pane))
		# Panel sin nombre dentro de la ventana del conmutador.
		other = mock.Mock(role=Role.PANE, UIAClassName="", windowClassName="", windowHandle=HWND_SWITCHER)
		other.name = ""
		self.assertTrue(explorer.isTaskSwitcherInputSite(other))
		# Panel sin nombre de otra aplicación: no se toca.
		desk = mock.Mock(role=Role.PANE, UIAClassName="", windowClassName="", windowHandle=HWND_DESKTOP_APP)
		desk.name = ""
		self.assertFalse(explorer.isTaskSwitcherInputSite(desk))
		item = mock.Mock(role=Role.LISTITEM, UIAClassName=explorer.INPUT_SITE_CLASS, windowHandle=HWND_INPUTSITE)
		item.name = ""
		self.assertFalse(explorer.isTaskSwitcherInputSite(item))
		# El escritorio (otro panel del explorador) no recibe la clase.
		clsList: list = []
		self.explorerApp.chooseObjectClass(desk, clsList)
		self.assertEqual(clsList, [])


class TransientContainerFocusTests(_Scenario):
	"""Patrón general: foco vacío en un antecesor sin nombre justo después."""

	def setUp(self) -> None:
		super().setUp()
		self.altDown = False
		self.window = Obj("Aplicación", Role.WINDOW, self.desktop, HWND_SOCIAL)
		self.pane = Obj("", Role.PANE, self.window, HWND_SOCIAL)
		self.list = Obj("Resultados", Role.LIST, self.pane, HWND_SOCIAL)
		self.item = Obj("Primer resultado", Role.LISTITEM, self.list, HWND_SOCIAL)
		events.executeEvent("gainFocus", self.item)

	def test_contenedor_vacio_antecesor_se_ignora(self) -> None:
		self.assertTrue(events.isTransientContainerFocus(self.pane))
		cancelled = self.synth.cancelled
		events.executeEvent("gainFocus", self.pane)
		self.assertIs(api.getFocusObject(), self.item)
		self.assertEqual(self.synth.cancelled, cancelled)
		self.finishSpeech()
		self.assertIn("Primer resultado", self.synth.texts())

	def test_con_nombre_o_valor_se_acepta(self) -> None:
		self.pane.name = "Panel de resultados"
		self.assertFalse(events.isTransientContainerFocus(self.pane))
		self.pane.name = ""
		self.pane.value = "3 elementos"
		self.assertFalse(events.isTransientContainerFocus(self.pane))

	def test_pasado_el_plazo_se_acepta(self) -> None:
		events._lastFocusTime = time.monotonic() - events.TRANSIENT_FOCUS_WINDOW - 0.5
		self.assertFalse(events.isTransientContainerFocus(self.pane))
		events.executeEvent("gainFocus", self.pane)
		self.assertIs(api.getFocusObject(), self.pane)

	def test_si_el_foco_anterior_desaparece_se_acepta(self) -> None:
		self.item.states = {State.DEFUNCT}
		self.assertFalse(events.isTransientContainerFocus(self.pane))

	def test_contenedor_que_no_es_antecesor_se_acepta(self) -> None:
		other = Obj("", Role.PANE, self.window, HWND_SOCIAL)
		self.assertFalse(events.isTransientContainerFocus(other))

	def test_listas_y_documentos_no_son_contenedores_genericos(self) -> None:
		self.list.name = ""
		self.assertFalse(events.isTransientContainerFocus(self.list))


if __name__ == "__main__":
	unittest.main()
