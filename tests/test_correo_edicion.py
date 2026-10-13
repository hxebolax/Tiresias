"""«edición» al final de cada trozo de un correo leído con Thunderbird.

Thunderbird 102 (Gecko sin proveedor UIA propio) se lee con el puente
MSAA→UIA del sistema, que convierte cada trozo de texto (``ROLE_SYSTEM_TEXT``
sin «solo lectura») en un ``Edit`` con valor modificable. El modo exploración
lo trataba como un campo de formulario y añadía «edición» tras cada párrafo
(en un correo de texto plano, solo al final). NVDA lo lee con IAccessible2 y
no dice nada. También se comprueba que las plantillas por tipo de control
quitan el rol en el modo exploración.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
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
	_TMP = tempfile.mkdtemp(prefix="tiresias_correo_test_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()

from test_browse import FakeEl  # noqa: E402

from tiresias import presentation  # noqa: E402
from tiresias.a11y import uia_client as uc  # noqa: E402
from tiresias.browse.buffer import VirtualBuffer  # noqa: E402
from tiresias.browse.document import BrowseModeDocument  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.objects.roles import Role, State  # noqa: E402
from tiresias.objects.uia import UIAObject, isMsaaProxyProvider, looksLikeTextLeaf  # noqa: E402

PROXY = "[pid:1,providerId:0x0 Main(parent link):Microsoft: MSAA Proxy (IAccessible2) (unmanaged:UIAutomationCore.DLL)]"
NATIVE = "[pid:1,providerId:0x0 Main(parent link):Unidentified Provider (unmanaged:xul.dll)]"


class RootEl(FakeEl):
	"""Documento con marco y proveedor (se leen una vez al construir el búfer)."""

	def __init__(self, children: list, framework: str = "Gecko", provider: str = PROXY) -> None:
		super().__init__(uc.CT_DOCUMENT, "Reunión del jueves", children)
		self.CurrentFrameworkId = framework
		self.provider = provider

	def GetCurrentPropertyValue(self, propId: int):
		return self.provider if propId == uc.P_PROVIDERDESCRIPTION else self.props.get(propId)


def leaf(text: str) -> FakeEl:
	"""Trozo de texto de Gecko tal como lo da el puente MSAA (Thunderbird 102)."""
	return FakeEl(uc.CT_EDIT, text, P_ISVALUEPATTERNAVAILABLE=True, P_VALUEVALUE="", P_ISKEYBOARDFOCUSABLE=False, P_ISENABLED=True, P_LEGACYSTATE=0)


def field(name: str, value: str = "", **props) -> FakeEl:
	base = dict(P_ISVALUEPATTERNAVAILABLE=True, P_VALUEVALUE=value, P_ISKEYBOARDFOCUSABLE=True, P_ISENABLED=True, P_LEGACYSTATE=0x100000)
	base.update(props)
	return FakeEl(uc.CT_EDIT, name, **base)


def mailBody() -> list:
	return [
		leaf("Hola, buenos días."),
		leaf("Te escribo para confirmar la reunión."),
		FakeEl(uc.CT_HYPERLINK, "este enlace", [], P_ISKEYBOARDFOCUSABLE=True, P_VALUEVALUE="https://ejemplo.org"),
		leaf("Un saludo."),
		leaf("Ana Pruebas"),
	]


def makeDoc(root: FakeEl) -> BrowseModeDocument:
	buf = VirtualBuffer(root)
	buf.build()
	doc = BrowseModeDocument.__new__(BrowseModeDocument)
	doc.__dict__.update(rootObject=None, buffer=buf, caret=0)
	return doc


def lines(doc: BrowseModeDocument) -> list[str]:
	buf = doc.buffer
	out = []
	off = 0
	while off < len(buf.text):
		s, e = buf.lineBounds(off)
		out.append(" ".join(x for x in doc.compactSpeech(doc.getRangeSpeech(s, e)) if isinstance(x, str)))
		if e <= off:
			break
		off = e
	return out


class Base(unittest.TestCase):
	def setUp(self) -> None:
		self._saved = dict(conf["browseMode"])
		self._templates = conf["presentation"]["roleTemplates"]
		conf["browseMode"]["useScreenLayout"] = False
		conf["presentation"]["roleTemplates"] = {}

	def tearDown(self) -> None:
		for k, v in self._saved.items():
			conf["browseMode"][k] = v
		conf["presentation"]["roleTemplates"] = self._templates


class TextLeafPredicateTests(unittest.TestCase):
	def _get(self, el: FakeEl):
		return lambda p, d=None: el.props.get(p, d)

	def test_trozo_de_texto(self) -> None:
		self.assertTrue(looksLikeTextLeaf(self._get(leaf("Hola"))))

	def test_campos_de_verdad(self) -> None:
		# Enfocable, desactivado, con valor o contraseña: siguen siendo campos.
		self.assertFalse(looksLikeTextLeaf(self._get(field("Nombre"))))
		self.assertFalse(looksLikeTextLeaf(self._get(field("Desactivado", "no", P_ISKEYBOARDFOCUSABLE=False, P_ISENABLED=False, P_LEGACYSTATE=0x1))))
		self.assertFalse(looksLikeTextLeaf(self._get(field("Caja", "texto", P_ISKEYBOARDFOCUSABLE=False, P_LEGACYSTATE=0))))
		self.assertFalse(looksLikeTextLeaf(self._get(field("Clave", P_ISKEYBOARDFOCUSABLE=False, P_LEGACYSTATE=0, P_ISPASSWORD=True))))
		self.assertFalse(looksLikeTextLeaf(self._get(FakeEl(uc.CT_TEXT, "texto"))))

	def test_proveedor(self) -> None:
		self.assertTrue(isMsaaProxyProvider(PROXY))
		self.assertFalse(isMsaaProxyProvider(NATIVE))
		self.assertFalse(isMsaaProxyProvider(None))


class ThunderbirdBrowseTests(Base):
	def test_el_cuerpo_del_correo_no_dice_edicion(self) -> None:
		doc = makeDoc(RootEl(mailBody()))
		roles = {n.name: n.role for n in doc.buffer.nodes}
		self.assertEqual(roles["Hola, buenos días."], Role.STATICTEXT)
		self.assertEqual(roles["Ana Pruebas"], Role.STATICTEXT)
		spoken = lines(doc)
		self.assertTrue(spoken)
		for line in spoken:
			self.assertNotIn("edición", line)
		self.assertIn("Ana Pruebas", spoken[-1])
		# Los trozos son texto en línea (antes cada uno era un campo en su propia línea).
		self.assertEqual(spoken[0], "Hola, buenos días. Te escribo para confirmar la reunión.")
		# Ni un campo de formulario para la tecla F / E.
		self.assertFalse([n for n in doc.buffer.nodes if n.role == Role.EDITABLETEXT])

	def test_texto_plano_no_termina_en_edicion(self) -> None:
		doc = makeDoc(RootEl([leaf("Hola, buenos días.\n\nUn saludo."), leaf("-- \nAna Pruebas")]))
		spoken = lines(doc)
		self.assertEqual(spoken[-1], "Ana Pruebas")

	def test_campos_de_formulario_de_gecko_siguen_diciendo_edicion(self) -> None:
		doc = makeDoc(RootEl([leaf("Texto."), field("Nombre", "Juan"), field("Desactivado", "no", P_ISKEYBOARDFOCUSABLE=False, P_ISENABLED=False, P_LEGACYSTATE=0x1)]))
		roles = {n.name: n.role for n in doc.buffer.nodes}
		self.assertEqual(roles["Nombre"], Role.EDITABLETEXT)
		self.assertEqual(roles["Desactivado"], Role.EDITABLETEXT)
		self.assertTrue(any("edición" in s for s in lines(doc)))

	def test_firefox_con_uia_propio_y_chrome_no_cambian(self) -> None:
		# Un role="textbox" sin tabindex en Firefox (UIA propio) o en Chrome sigue siendo un campo.
		for fw, prov in (("Gecko", NATIVE), ("Chrome", PROXY)):
			doc = makeDoc(RootEl([leaf("Caja aria")], framework=fw, provider=prov))
			node = next(n for n in doc.buffer.nodes if n.name == "Caja aria")
			self.assertEqual(node.role, Role.EDITABLETEXT, fw)


class RoleTemplateBrowseTests(Base):
	def test_plantilla_sin_rol_quita_edicion(self) -> None:
		doc = makeDoc(RootEl([field("Nombre", "Juan")], framework="Chrome"))
		self.assertTrue(any("edición" in s for s in lines(doc)))
		conf["presentation"]["roleTemplates"] = {"editabletext": "{name} {value}"}
		self.assertFalse(any("edición" in s for s in lines(doc)))

	def test_plantilla_con_rol_y_estados(self) -> None:
		doc = makeDoc(RootEl([FakeEl(uc.CT_CHECKBOX, "Acepto", [], P_ISTOGGLEPATTERNAVAILABLE=True, P_TOGGLESTATE=0, P_ISKEYBOARDFOCUSABLE=True)], framework="Chrome"))
		self.assertIn("casilla de verificación no marcado", " ".join(lines(doc)))
		conf["presentation"]["roleTemplates"] = {"checkbox": "{name} {role}"}
		text = " ".join(lines(doc))
		self.assertIn("casilla de verificación", text)
		self.assertNotIn("no marcado", text)


# ====================================================================== objetos (foco, navegador de objetos)
class _FakeElement:
	def __init__(self, props: dict) -> None:
		self.props = props

	def GetCachedPropertyValueEx(self, propId, ignoreDefault):
		return self.props.get(propId)

	def GetCurrentPropertyValueEx(self, propId, ignoreDefault):
		return self.props.get(propId)


class _FakeUIA(UIAObject):
	def __init__(self, props: dict, windowClass: str = "MozillaWindowClass") -> None:
		super().__init__(_FakeElement(props), windowHandle=0x1234)
		self._wc = windowClass

	def _get_windowClassName(self) -> str:
		return self._wc

	def _get_parent(self):
		return None


def _objProps(ct: int = uc.CT_EDIT, framework: str = "Gecko", provider: str = PROXY, extra: dict | None = None) -> dict:
	props = {
		uc.P_CONTROLTYPE: ct,
		uc.P_NAME: "Departamento de Pruebas",
		uc.P_FRAMEWORKID: framework,
		uc.P_PROVIDERDESCRIPTION: provider,
		uc.P_ISVALUEPATTERNAVAILABLE: True,
		uc.P_VALUEISREADONLY: False,
		uc.P_VALUEVALUE: "",
		uc.P_ISKEYBOARDFOCUSABLE: False,
		uc.P_ISENABLED: True,
		uc.P_LEGACYSTATE: 0,
	}
	props.update(extra or {})
	return props


class ObjectRoleTests(unittest.TestCase):
	def test_trozo_de_texto_de_thunderbird_es_texto(self) -> None:
		obj = _FakeUIA(_objProps())
		self.assertEqual(obj.role, Role.STATICTEXT)
		self.assertNotIn("edición", " ".join(presentation.getObjectSpeech(obj, presentation.Reason.QUERY)))

	def test_campos_reales_siguen_siendo_edicion(self) -> None:
		focusable = _FakeUIA(_objProps(extra={uc.P_ISKEYBOARDFOCUSABLE: True, uc.P_LEGACYSTATE: 0x100000}))
		self.assertEqual(focusable.role, Role.EDITABLETEXT)
		self.assertIn("edición", presentation.getObjectSpeech(focusable, presentation.Reason.QUERY))
		self.assertEqual(_FakeUIA(_objProps(provider=NATIVE)).role, Role.EDITABLETEXT)
		self.assertEqual(_FakeUIA(_objProps(framework="Win32"), "Edit").role, Role.EDITABLETEXT)

	def test_cuerpo_de_outlook_y_word_de_solo_lectura_no_dice_edicion(self) -> None:
		# Panel de lectura de Outlook (control _WwG de Word, documento de solo lectura).
		props = _objProps(ct=uc.CT_DOCUMENT, framework="Win32", provider="", extra={uc.P_NAME: "Mensaje", uc.P_CLASSNAME: "_WwG", uc.P_VALUEISREADONLY: True, uc.P_ISKEYBOARDFOCUSABLE: True})
		obj = _FakeUIA(props, "_WwG")
		self.assertEqual(obj.role, Role.DOCUMENT)
		self.assertIn(State.READONLY, obj.states)
		for reason in (presentation.Reason.FOCUS, presentation.Reason.QUERY, presentation.Reason.FOCUSENTERED):
			self.assertNotIn("edición", " ".join(presentation.getObjectSpeech(obj, reason)))


if __name__ == "__main__":
	unittest.main()
