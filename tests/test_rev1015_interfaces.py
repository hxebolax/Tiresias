"""Pruebas de la revisión 1.0.15: interfaces que se leían mal.

- Elementos de árbol de Thunderbird (Gecko a través del puente MSAA→UIA) con
  ``HeadingLevel`` copiado del nivel del árbol: no son encabezados.
- RichEdit de solo lectura: nombre «RichEdit Control» fuera, rol «edición
  multilínea» con «solo lectura», como NVDA.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev1015_interfaces -v``
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_rev1015_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]

from tiresias import presentation, speech  # noqa: E402
from tiresias.a11y import uia_client as uc  # noqa: E402
from tiresias.objects import behaviors  # noqa: E402
from tiresias.objects.roles import Role, State  # noqa: E402
from tiresias.objects.uia import RICHEDIT_DEFAULT_NAME, UIAObject, uiaHeadingLevel  # noqa: E402

PROXY = "[pid:6648,providerId:0x0 Main(parent link):Microsoft: MSAA Proxy (IAccessible2) (unmanaged:uiautomationcore.dll)]"
MSFTEDIT = "[pid:18288,providerId:0x1827D8 Main:Nested [pid:14744,providerId:0x1827D8 Main:Unidentified Provider (unmanaged:msftedit.DLL)]; Hwnd(parent link):Microsoft: HWND Proxy (unmanaged:uiautomationcore.dll)]"


class _FakeElement:
	def __init__(self, props: dict) -> None:
		self.props = props

	def GetCachedPropertyValueEx(self, propId, ignoreDefault):
		return self.props.get(propId)

	def GetCurrentPropertyValueEx(self, propId, ignoreDefault):
		return self.props.get(propId)

	def GetCurrentPropertyValue(self, propId):
		return self.props.get(propId)


class _FakeUIA(UIAObject):
	def __init__(self, props: dict, windowClass: str = "MozillaWindowClass") -> None:
		super().__init__(_FakeElement(props), windowHandle=0x1234)
		self._wc = windowClass

	def _get_windowClassName(self) -> str:
		return self._wc

	def _get_parent(self):
		return None

	def _get_states(self):
		states = super()._get_states()
		return states


def _treeItem(name: str, level: int = 1) -> dict:
	return {
		uc.P_CONTROLTYPE: uc.CT_TREEITEM,
		uc.P_NAME: name,
		uc.P_FRAMEWORKID: "Gecko",
		uc.P_PROVIDERDESCRIPTION: PROXY,
		uc.P_HEADINGLEVEL: uc.HEADINGLEVEL_NONE + level,
		uc.P_LEVEL: level,
		uc.P_ISKEYBOARDFOCUSABLE: True,
		uc.P_HASKEYBOARDFOCUS: True,
	}


class HeadingLevelTests(unittest.TestCase):
	def test_nivel_de_arbol_no_es_encabezado(self) -> None:
		self.assertEqual(uiaHeadingLevel(uc.CT_TREEITEM, uc.HEADINGLEVEL1), 0)
		for ct in (uc.CT_LISTITEM, uc.CT_DATAITEM, uc.CT_TABITEM, uc.CT_BUTTON, uc.CT_MENUITEM, uc.CT_TREE):
			self.assertEqual(uiaHeadingLevel(ct, uc.HEADINGLEVEL_NONE + 2), 0, ct)

	def test_texto_y_grupos_si(self) -> None:
		self.assertEqual(uiaHeadingLevel(uc.CT_TEXT, uc.HEADINGLEVEL1), 1)
		self.assertEqual(uiaHeadingLevel(uc.CT_TEXT, uc.HEADINGLEVEL_NONE + 6), 6)
		self.assertEqual(uiaHeadingLevel(uc.CT_GROUP, uc.HEADINGLEVEL_NONE + 3), 3)
		self.assertEqual(uiaHeadingLevel(uc.CT_HYPERLINK, uc.HEADINGLEVEL_NONE + 2), 2)
		self.assertEqual(uiaHeadingLevel(uc.CT_TEXT, uc.HEADINGLEVEL_NONE + 9), 7)

	def test_sin_nivel_o_valor_raro(self) -> None:
		self.assertEqual(uiaHeadingLevel(uc.CT_TEXT, uc.HEADINGLEVEL_NONE), 0)
		self.assertEqual(uiaHeadingLevel(uc.CT_TEXT, 0), 0)
		self.assertEqual(uiaHeadingLevel(uc.CT_TEXT, None), 0)
		self.assertEqual(uiaHeadingLevel(uc.CT_TEXT, "x"), 0)

	def test_cuenta_de_thunderbird_es_elemento_de_arbol(self) -> None:
		obj = _FakeUIA(_treeItem("ana@ejemplo.com"))
		self.assertEqual(obj.role, Role.TREEVIEWITEM)
		spoken = " ".join(presentation.getObjectSpeech(obj, presentation.Reason.FOCUS))
		self.assertIn("ana@ejemplo.com", spoken)
		self.assertNotIn("encabezado", spoken)

	def test_encabezado_de_texto_sigue_siendo_encabezado(self) -> None:
		props = _treeItem("Título", 2)
		props[uc.P_CONTROLTYPE] = uc.CT_TEXT
		self.assertEqual(_FakeUIA(props).role, Role.HEADING2)


def _richEdit(readOnly: bool = True, name: str = RICHEDIT_DEFAULT_NAME) -> dict:
	return {
		uc.P_CONTROLTYPE: uc.CT_DOCUMENT,
		uc.P_NAME: name,
		uc.P_CLASSNAME: "RICHEDIT50W",
		uc.P_FRAMEWORKID: "Win32",
		uc.P_PROVIDERDESCRIPTION: MSFTEDIT,
		uc.P_ISVALUEPATTERNAVAILABLE: True,
		uc.P_VALUEISREADONLY: readOnly,
		uc.P_VALUEVALUE: "Mensaje 28\rAutor: Ana",
		uc.P_ISTEXTPATTERNAVAILABLE: True,
		uc.P_ISKEYBOARDFOCUSABLE: True,
		uc.P_HASKEYBOARDFOCUS: True,
		uc.P_NATIVEWINDOWHANDLE: 0,
	}


class RichEditTests(unittest.TestCase):
	def test_solo_lectura_es_edicion_multilinea_sin_nombre_generico(self) -> None:
		obj = _FakeUIA(_richEdit(), "RICHEDIT50W")
		self.assertEqual(obj.name, "")
		self.assertEqual(obj.role, Role.EDITABLETEXT)
		self.assertIn(State.READONLY, obj.states)
		self.assertIn(State.MULTILINE, obj.states)
		spoken = " ".join(presentation.getObjectSpeech(obj, presentation.Reason.FOCUS))
		self.assertNotIn("RichEdit", spoken)
		self.assertNotIn("documento", spoken)
		self.assertIn("solo lectura", spoken)
		self.assertIn("edición", spoken)
		clsList: list = []
		obj.findOverlayClasses(clsList)
		self.assertIn(behaviors.ReadOnlyDocument, clsList)

	def test_editable_sigue_igual(self) -> None:
		obj = _FakeUIA(_richEdit(readOnly=False), "RICHEDIT50W")
		self.assertEqual(obj.name, "")
		self.assertEqual(obj.role, Role.EDITABLETEXT)
		self.assertIn(State.EDITABLE, obj.states)
		clsList: list = []
		obj.findOverlayClasses(clsList)
		self.assertIn(behaviors.EditableTextWithCaret, clsList)
		self.assertNotIn(behaviors.ReadOnlyDocument, clsList)

	def test_nombre_real_se_conserva(self) -> None:
		obj = _FakeUIA(_richEdit(name="Mensaje"), "RICHEDIT50W")
		self.assertEqual(obj.name, "Mensaje")

	def test_otro_control_llamado_asi_no_se_toca(self) -> None:
		props = _richEdit()
		props[uc.P_CLASSNAME] = "TextBlock"
		props[uc.P_PROVIDERDESCRIPTION] = ""
		props[uc.P_CONTROLTYPE] = uc.CT_TEXT
		self.assertEqual(_FakeUIA(props, "Windows.UI.Core.CoreWindow").name, RICHEDIT_DEFAULT_NAME)


if __name__ == "__main__":
	unittest.main()


# ====================================================================== búsqueda del menú Inicio (Windows 11 26H2)
class _Obj:
	def __init__(self, name: str, role=Role.LISTITEM, rid=(1,), framework: str = "", automationId: str = "") -> None:
		self.name = name
		self.role = role
		self.runtimeId = rid
		self.UIAFrameworkId = framework
		self.UIAAutomationId = automationId
		self.value = ""

	def __eq__(self, other) -> bool:
		return isinstance(other, _Obj) and self.runtimeId == other.runtimeId

	__hash__ = object.__hash__


class StartMenuSearchTests(unittest.TestCase):
	def setUp(self) -> None:
		from tiresias.appmodules import searchhost

		self.sh = searchhost
		self.app = searchhost.AppModule.__new__(searchhost.AppModule)
		self.app._last = (None, 0.0)
		self.app._checkSeq = 0
		self.app._lastSuggestion = None

	def test_el_cuadro_de_busqueda_recibe_la_clase(self) -> None:
		box = _Obj("Cuadro de búsqueda", Role.EDITABLETEXT, automationId="SearchTextBox")
		clsList: list = [behaviors.EditableTextWithCaret]
		self.app.chooseObjectClass(box, clsList)
		self.assertIs(clsList[0], self.sh.StartMenuSearchField)
		other: list = []
		self.app.chooseObjectClass(_Obj("x", Role.BUTTON), other)
		self.assertEqual(other, [])

	def test_foco_falso_del_documento_web(self) -> None:
		from unittest import mock

		doc = _Obj("Búsqueda", Role.DOCUMENT, framework="Chrome")
		focused = mock.Mock(CurrentAutomationId="SearchTextBox")
		with mock.patch("tiresias.a11y.uia_client.getFocusedElement", return_value=focused):
			self.assertFalse(self.app.shouldProcessEvent("gainFocus", doc))
			# Otros eventos y otros objetos pasan.
			self.assertTrue(self.app.shouldProcessEvent("valueChange", doc))
			self.assertTrue(self.app.shouldProcessEvent("gainFocus", _Obj("Todos", Role.BUTTON, framework="XAML")))
		# El foco real está dentro de la página (flecha derecha sobre un resultado): es de verdad.
		with mock.patch("tiresias.a11y.uia_client.getFocusedElement", return_value=mock.Mock(CurrentAutomationId="")):
			self.assertTrue(self.app.shouldProcessEvent("gainFocus", doc))

	def test_resultado_resaltado_se_anuncia_una_vez(self) -> None:
		from unittest import mock

		field = self.sh.StartMenuSearchField.__new__(self.sh.StartMenuSearchField)
		item = _Obj(" Bloc de notas, Aplicación, Presione a la derecha ", rid=(7,))
		delays: list = []
		with mock.patch.object(self.sh.queue_handler, "callLater", side_effect=lambda d, f, *a: delays.append(d)):
			self.app.scheduleSuggestionCheck()
		self.assertEqual(tuple(delays), self.sh.TYPING_CHECK_DELAYS)
		seq = self.app._checkSeq
		with mock.patch.object(self.sh.api, "getFocusObject", return_value=field), mock.patch.object(self.app, "_selectedSuggestion", return_value=item), mock.patch.object(self.sh.presentation, "speakObject") as spk:
			self.app._checkSuggestion(seq)
			self.app._checkSuggestion(seq)  # misma sugerencia: no se repite
			spk.assert_called_once()
			self.assertEqual(self.app._lastSuggestion, "Bloc de notas, Aplicación, Presione a la derecha")
			# Una comprobación antigua (ya se escribió otra letra) no habla.
			self.app._checkSeq += 1
			self.app._checkSuggestion(seq)
			spk.assert_called_once()
			# El evento de selección del mismo elemento tampoco lo repite.
			nxt = mock.Mock()
			with mock.patch.object(speech, "cancelSpeech") as cancel:
				self.app.event_selection(item, nxt)
			spk.assert_called_once()
			cancel.assert_not_called()
		# Sin foco en el cuadro de búsqueda no se busca nada.
		with mock.patch.object(self.sh.api, "getFocusObject", return_value=_Obj("Todos", Role.BUTTON)), mock.patch.object(self.app, "_selectedSuggestion") as sel:
			self.app._checkSuggestion(self.app._checkSeq)
			sel.assert_not_called()

	def test_las_flechas_se_dejan_pasar_y_se_comprueba(self) -> None:
		from unittest import mock

		field = self.sh.StartMenuSearchField.__new__(self.sh.StartMenuSearchField)
		gesture = mock.Mock()
		with mock.patch.object(type(field), "appModule", new_callable=mock.PropertyMock, return_value=self.app), mock.patch.object(self.app, "scheduleSuggestionCheck") as sched:
			field.script_moveSuggestion(gesture)
		gesture.send.assert_called_once()
		sched.assert_called_once_with(self.sh.ARROW_CHECK_DELAYS)
		self.assertFalse(self.sh.StartMenuSearchField.announceNewLineText)


# ====================================================================== role=application (Antigravity, VS Code)
class ApplicationPassThroughTests(unittest.TestCase):
	"""Dentro de role=application se pasa a modo foco aunque el paso automático esté desactivado."""

	def setUp(self) -> None:
		from unittest import mock

		from tiresias.config import conf

		self._saved = dict(conf["browseMode"])
		conf["browseMode"]["autoPassThroughOnFocusChange"] = False
		conf["browseMode"]["passThroughAudioIndication"] = True
		self.sounds: list[str] = []
		for p in (
			mock.patch("tiresias.audio.tones.playSound", side_effect=self.sounds.append),
			mock.patch("tiresias.speech.speakMessage"),
			mock.patch("tiresias.speech.speakText"),
			mock.patch("tiresias.api.setReviewPosition"),
		):
			p.start()
			self.addCleanup(p.stop)

	def tearDown(self) -> None:
		from tiresias.config import conf

		conf["browseMode"].update(self._saved)

	def _doc(self):
		import test_browse as tb
		from test_rev1011_exploracion import makeDoc

		self.editor = tb.FakeEl(uc.CT_EDIT, "strings.xml", P_ISKEYBOARDFOCUSABLE=True, P_ISVALUEPATTERNAVAILABLE=True, P_VALUEISREADONLY=False)
		self.treeItem = tb.FakeEl(uc.CT_TREEITEM, "res", P_ISKEYBOARDFOCUSABLE=True)
		tree = tb.FakeEl(uc.CT_TREE, "Explorador de archivos", [self.treeItem])
		workbench = tb.FakeEl(uc.CT_PANE, "", [tb.group(self.editor, name="strings.xml"), tree], P_ARIAROLE="application", P_CLASSNAME="monaco-workbench")
		self.link = tb.FakeEl(uc.CT_HYPERLINK, "Ayuda", [tb.text("Ayuda")], P_ISKEYBOARDFOCUSABLE=True)
		root = tb.FakeEl(uc.CT_DOCUMENT, "Antigravity IDE", [tb.group(self.link), workbench])
		return makeDoc(root)

	def _focus(self, doc, el, role: Role) -> None:
		from unittest import mock

		obj = mock.Mock(runtimeId=el.rid, role=role, states=set(), isFocusable=True, name=el.props.get(uc.P_NAME, ""))
		with mock.patch("tiresias.input.core.manager", create=True), mock.patch.object(type(doc), "onPassThroughChanged", create=True, return_value=None):
			doc.event_gainFocus(obj, lambda: None)

	def test_foco_en_la_aplicacion_pasa_a_modo_foco_y_vuelve_al_salir(self) -> None:
		doc = self._doc()
		self.assertFalse(doc.passThrough)
		self._focus(doc, self.editor, Role.EDITABLETEXT)
		self.assertTrue(doc.passThrough)
		self._focus(doc, self.treeItem, Role.TREEVIEWITEM)
		self.assertTrue(doc.passThrough)
		# Un enlace de la página, fuera de la aplicación: se vuelve al modo exploración.
		self._focus(doc, self.link, Role.LINK)
		self.assertFalse(doc.passThrough)
		self.assertEqual(self.sounds, ["focusMode", "browseMode"])

	def test_modo_foco_fijado_por_el_usuario_se_respeta_al_salir(self) -> None:
		doc = self._doc()
		self._focus(doc, self.editor, Role.EDITABLETEXT)
		doc._focusModeLocked = True
		self._focus(doc, self.link, Role.LINK)
		self.assertTrue(doc.passThrough)


# ====================================================================== textos sueltos de Chromium
class NameGapsTests(unittest.TestCase):
	"""Chromium no publica en la vista de control los textos sueltos junto a otros hijos."""

	def setUp(self) -> None:
		from tiresias.config import conf

		self._saved = dict(conf["browseMode"])
		conf["browseMode"]["useScreenLayout"] = True
		conf["browseMode"]["maxLineLength"] = 200
		conf["browseMode"]["containerLinesApart"] = False

	def tearDown(self) -> None:
		from tiresias.config import conf

		conf["browseMode"].update(self._saved)

	def _lineas(self, *items) -> list[str]:
		import test_browse as tb

		buf = tb.build(tb.group(*items))
		return [ln for ln in buf.text.split("\n") if ln.strip()]

	def _item(self, name: str, *kids):
		import test_browse as tb

		return tb.FakeEl(uc.CT_LISTITEM, name, list(kids))

	def test_estado_de_la_lista_de_tareas_de_claude(self) -> None:
		import test_browse as tb

		items = [self._item(f"{estado}{tarea}", tb.group(tb.text(tarea))) for estado, tarea in (("listo", "Revisar memoria"), ("en progreso", "Probar Claude"), ("sin completar", "Compilar"))]
		self.assertEqual(self._lineas(tb.FakeEl(uc.CT_LIST, "", items)), ["listo Revisar memoria", "en progreso Probar Claude", "sin completar Compilar"])

	def test_texto_final_y_central(self) -> None:
		import test_browse as tb

		item = self._item("uno dos tres cuatro", tb.group(tb.text("dos")), tb.group(tb.text("cuatro")))
		lineas = " ".join(self._lineas(item))
		for palabra in ("uno", "dos", "tres", "cuatro"):
			self.assertEqual(lineas.count(palabra), 1, lineas)
		item = self._item("Tarea hecha", tb.group(tb.text("Tarea")))
		self.assertEqual(" ".join(self._lineas(item)).split(), ["Tarea", "hecha"])

	def test_no_duplica_ni_inventa(self) -> None:
		import test_browse as tb

		# Nombre igual al contenido: nada que recuperar.
		self.assertEqual(self._lineas(self._item("Hola", tb.text("Hola"))), ["Hola"])
		# aria-label distinto del contenido: se respeta lo que hay.
		self.assertEqual(self._lineas(self._item("Etiqueta", tb.text("Contenido"))), ["Contenido"])
		# Sin hijos: el nombre.
		self.assertEqual(self._lineas(self._item("Solo nombre")), ["Solo nombre"])

	def test_otros_roles_no_se_tocan(self) -> None:
		import test_browse as tb

		self.assertEqual(self._lineas(tb.group(tb.text("hijo"), name="etiqueta del grupo hijo")), ["hijo"])


# ====================================================================== Electron y ProseMirror
class ElectronShellTests(unittest.TestCase):
	def _vista(self, cls: str) -> "_FakeUIA":
		return _FakeUIA({uc.P_CONTROLTYPE: uc.CT_PANE, uc.P_NAME: "Claude", uc.P_ARIAROLE: "region", uc.P_CLASSNAME: cls, uc.P_FRAMEWORKID: "Chrome"}, "Chrome_WidgetWin_1")

	def test_la_vista_raiz_no_es_una_region(self) -> None:
		for cls in ("RootView", "BrowserRootView"):
			obj = self._vista(cls)
			self.assertEqual(obj.role, Role.PANE)
			self.assertFalse(obj.isPresentableFocusAncestor)

	def test_una_region_de_la_pagina_sigue_siendolo(self) -> None:
		obj = self._vista("mi-region")
		self.assertEqual(obj.role, Role.LANDMARK)
		self.assertTrue(obj.isPresentableFocusAncestor)


class ProseMirrorTests(unittest.TestCase):
	def _campo(self, cls: str, linea: str):
		from unittest import mock

		info = mock.Mock(isCollapsed=True, text=linea)
		obj = mock.Mock(hasText=True, makeTextInfo=mock.Mock(return_value=info), UIAClassName=cls)
		obj.name = "Trabaja con Codex"
		return obj

	def _dicho(self, obj):
		return presentation._caretContext(obj, Role.EDITABLETEXT, set(), presentation.Reason.FOCUS)

	def test_texto_de_ejemplo_es_en_blanco(self) -> None:
		self.assertEqual(self._dicho(self._campo("ProseMirror", "Trabaja con Codex")), "en blanco")

	def test_texto_de_verdad_se_lee(self) -> None:
		self.assertEqual(self._dicho(self._campo("ProseMirror", "arregla el 443")), "arregla el 443")
		self.assertEqual(self._dicho(self._campo("otro", "Trabaja con Codex")), "Trabaja con Codex")


# ====================================================================== issues abiertas de NVDA
class EnlacesTests(unittest.TestCase):
	def _texto(self, el) -> str:
		import test_browse as tb

		return tb.build(tb.group(el)).text

	def test_aria_label_manda_en_modo_exploracion(self) -> None:
		import test_browse as tb

		text = self._texto(tb.FakeEl(uc.CT_HYPERLINK, "Informe PDF", [tb.text("Pulsa aquí")]))
		self.assertIn("Informe PDF", text)
		self.assertNotIn("Pulsa aquí", text)

	def test_nombre_igual_al_texto_no_cambia(self) -> None:
		import test_browse as tb

		self.assertEqual(self._texto(tb.FakeEl(uc.CT_HYPERLINK, "Inicio", [tb.text("Inicio")])).count("Inicio"), 1)

	def test_enlace_con_icono(self) -> None:
		import test_browse as tb

		self.assertIn("Editar regla", self._texto(tb.FakeEl(uc.CT_HYPERLINK, "", P_FULLDESCRIPTION="Editar regla")))
		self.assertIn("informe", self._texto(tb.FakeEl(uc.CT_HYPERLINK, "", P_VALUEVALUE="https://x.invalid/docs/informe.pdf")))
		self.assertIn("enlace", self._texto(tb.FakeEl(uc.CT_HYPERLINK, "")))


class ListasTests(unittest.TestCase):
	def setUp(self) -> None:
		from tiresias.config import conf

		self._saved = dict(conf["documentFormatting"])
		conf["documentFormatting"]["reportLists"] = True

	def tearDown(self) -> None:
		from tiresias.config import conf

		conf["documentFormatting"].update(self._saved)

	def _prefijo(self, size) -> str:
		import test_browse as tb
		from test_rev1011_exploracion import makeDoc

		items = [tb.FakeEl(uc.CT_LISTITEM, n, [tb.text(n)], P_SIZEOFSET=size) for n in ("a", "b")]
		lista = tb.FakeEl(uc.CT_LIST, "", items)
		doc = makeDoc(tb.group(lista))
		node = next(n for n in doc.buffer.nodes if n.role == Role.LIST)
		return doc.fieldPrefix(node)

	def test_lista_virtualizada(self) -> None:
		self.assertEqual(self._prefijo(100), "lista con 100 elementos")

	def test_sin_aria_setsize_cuenta_lo_que_hay(self) -> None:
		self.assertEqual(self._prefijo(-1), "lista con 2 elementos")
		self.assertEqual(self._prefijo(0), "lista con 2 elementos")


class EstadosTests(unittest.TestCase):
	def _control(self, ct: int, props: dict) -> "_FakeUIA":
		base = {uc.P_CONTROLTYPE: ct, uc.P_NAME: "Cantidad", uc.P_FRAMEWORKID: "Chrome"}
		base.update(props)
		return _FakeUIA(base, "Chrome_RenderWidgetHostHWND")

	def test_campo_numerico_de_solo_lectura(self) -> None:
		obj = self._control(uc.CT_SPINNER, {uc.P_ISRANGEVALUEPATTERNAVAILABLE: True, uc.P_RANGEVALUEISREADONLY: True})
		self.assertIn(State.READONLY, obj.states)
		self.assertIn("solo lectura", presentation.getStatesText(obj, obj.states, obj.role, presentation.Reason.FOCUS))

	def test_sin_patron_no_es_solo_lectura(self) -> None:
		# UIA devuelve «solo lectura» cierto por defecto si el patrón no está.
		obj = self._control(uc.CT_SLIDER, {uc.P_VALUEISREADONLY: True, uc.P_RANGEVALUEISREADONLY: True})
		self.assertNotIn(State.READONLY, obj.states)

	def _estados(self, role: Role, states: set) -> list[str]:
		obj = _FakeUIA({uc.P_CONTROLTYPE: uc.CT_LISTITEM, uc.P_NAME: "x"}, "x")
		return presentation.getStatesText(obj, states, role, presentation.Reason.FOCUS)

	def test_no_seleccionado(self) -> None:
		self.assertIn("no seleccionado", self._estados(Role.LISTITEM, {State.SELECTABLE, State.FOCUSABLE}))
		joined = " ".join(self._estados(Role.LISTITEM, {State.SELECTABLE, State.FOCUSABLE, State.SELECTED}))
		self.assertNotIn("selecc", joined)
		# Sin poder seleccionarse no hay nada que decir.
		self.assertNotIn("no seleccionado", self._estados(Role.LISTITEM, {State.FOCUSABLE}))
		self.assertNotIn("no seleccionado", self._estados(Role.BUTTON, {State.SELECTABLE, State.FOCUSABLE}))

	def test_no_marcado_en_elemento_con_casilla(self) -> None:
		self.assertIn("no marcado", self._estados(Role.LISTITEM, {State.CHECKABLE}))
		self.assertNotIn("no marcado", self._estados(Role.LISTITEM, {State.CHECKABLE, State.CHECKED}))
		self.assertNotIn("no marcado", self._estados(Role.LISTITEM, set()))


class ClasesNormalizadasTests(unittest.TestCase):
	def test_windows_forms_y_atl(self) -> None:
		from tiresias.a11y import api_choice as ac

		self.assertEqual(ac.normalizeClassName("WindowsForms10.SysListView32.app.0.141b42a_r9_ad1"), "SysListView32")
		self.assertEqual(ac.normalizeClassName("WindowsForms10.Window.8.app.0.2bf8098_r6_ad1"), "Window.8")
		self.assertEqual(ac.normalizeClassName("ATL:Edit"), "Edit")
		self.assertEqual(ac.normalizeClassName("Edit"), "Edit")
		self.assertEqual(ac._decide(1, "WindowsForms10.SysListView32.app.0.141b42a_r9_ad1"), ac.API_MSAA)


class EmojiTests(unittest.TestCase):
	def _info(self, texto: str):
		from unittest import mock

		from tiresias.objects import uia_text

		info = uia_text.UIATextInfo.__new__(uia_text.UIATextInfo)
		info._range = mock.Mock()
		info._range.GetText.return_value = texto
		return info

	def test_sustitutos_partidos(self) -> None:
		alto = self._info(chr(0xD83D))
		alto._joinSurrogates()
		alto._range.MoveEndpointByUnit.assert_called_once_with(uc.EP_END, uc.TU_CHARACTER, 1)
		bajo = self._info(chr(0xDE01))
		bajo._joinSurrogates()
		bajo._range.MoveEndpointByUnit.assert_called_once_with(uc.EP_START, uc.TU_CHARACTER, -1)

	def test_caracter_normal_no_mueve_nada(self) -> None:
		for texto in ("a", "😁", ""):
			info = self._info(texto)
			info._joinSurrogates()
			info._range.MoveEndpointByUnit.assert_not_called()


class DocumentoEnAplicacionTests(ApplicationPassThroughTests):
	"""NVDA #20695: un documento dentro de una aplicación se lee en modo exploración."""

	def _docConMensaje(self):
		import test_browse as tb
		from test_rev1011_exploracion import makeDoc

		self.mensaje = tb.FakeEl(uc.CT_DOCUMENT, "Mensaje", [tb.text("Hola")], P_ARIAROLE="document", P_ISKEYBOARDFOCUSABLE=True)
		self.editor = tb.FakeEl(uc.CT_EDIT, "Redactar", P_ISKEYBOARDFOCUSABLE=True, P_ISVALUEPATTERNAVAILABLE=True, P_VALUEISREADONLY=False)
		app = tb.FakeEl(uc.CT_PANE, "", [self.mensaje, self.editor], P_ARIAROLE="application")
		return makeDoc(tb.FakeEl(uc.CT_DOCUMENT, "Teams", [app]))

	def test_el_mensaje_se_lee_en_modo_exploracion(self) -> None:
		doc = self._docConMensaje()
		self._focus(doc, self.editor, Role.EDITABLETEXT)
		self.assertTrue(doc.passThrough)
		doc._focusModeLocked = True
		self._focus(doc, self.mensaje, Role.DOCUMENT)
		self.assertFalse(doc.passThrough)
		self.assertFalse(doc._focusModeLocked)
		# De vuelta en la aplicación, las teclas vuelven a ser suyas.
		self._focus(doc, self.editor, Role.EDITABLETEXT)
		self.assertTrue(doc.passThrough)


class LineasSinDistribucionTests(unittest.TestCase):
	def test_dos_textos_en_filas_distintas_son_dos_lineas(self) -> None:
		import test_browse as tb
		from tiresias.config import conf

		saved = conf["browseMode"]["useScreenLayout"]
		conf["browseMode"]["useScreenLayout"] = False
		self.addCleanup(conf["browseMode"].__setitem__, "useScreenLayout", saved)
		raiz = tb.group(
			tb.text("Primero", P_BOUNDINGRECT=(0, 0, 100, 20)),
			tb.text("Segundo", P_BOUNDINGRECT=(0, 40, 100, 20)),
			tb.text("en la misma fila", P_BOUNDINGRECT=(120, 40, 100, 20)),
		)
		self.assertEqual([ln for ln in tb.build(raiz).text.split("\n") if ln.strip()], ["Primero", "Segundo en la misma fila"])

