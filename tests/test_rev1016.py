"""Pruebas de la revisión 1.0.16: lo que contaban los usuarios del foro.

- Firefox: los elementos de lista solo leían la viñeta («•») y no su texto,
  porque el UIA propio de Gecko deja los trozos de texto fuera de la vista de
  control. El búfer usa en Gecko la vista sin filtrar.
- La viñeta va en la misma línea que el contenido del elemento.
- Formato de la hora configurable (el del reloj de Windows, 24 o 12 horas).
- Menú de Tiresias ordenado, sin letras de acceso repetidas.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev1016 -v``
"""

from __future__ import annotations

import collections
import datetime
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_rev1016_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]

from tiresias import time_format  # noqa: E402
from tiresias.a11y import uia_client as uc  # noqa: E402
from tiresias.config import conf  # noqa: E402

GECKO = "[pid:41300,providerId:0x0 Main(parent link):Unidentified Provider (unmanaged:xul.dll)]"
GECKO_PROXY = "[pid:6648,providerId:0x0 Main(parent link):Microsoft: MSAA Proxy (IAccessible2) (unmanaged:uiautomationcore.dll)]"


# ====================================================================== Firefox: viñetas
class _Doc:
	"""Documento falso: árbol distinto según la vista que se pida a la caché."""

	def __init__(self, framework: str, provider: str, control, raw) -> None:
		self.CurrentFrameworkId = framework
		self._provider = provider
		self._control = control
		self._raw = raw
		self.requests: list = []

	def GetCurrentPropertyValue(self, propId: int):
		return self._provider if propId == uc.P_PROVIDERDESCRIPTION else None

	def BuildUpdatedCache(self, request):
		self.requests.append(request)
		return self._raw if request is uc.rawTreeCacheRequest else self._control


class GeckoListTests(unittest.TestCase):
	def setUp(self) -> None:
		self._saved = dict(conf["browseMode"])
		conf["browseMode"]["useScreenLayout"] = False
		conf["browseMode"]["maxLineLength"] = 200
		conf["browseMode"]["containerLinesApart"] = False
		self._raw = uc.rawTreeCacheRequest
		self._tree = uc.treeCacheRequest
		uc.rawTreeCacheRequest = object()
		uc.treeCacheRequest = object()

	def tearDown(self) -> None:
		conf["browseMode"].update(self._saved)
		uc.rawTreeCacheRequest = self._raw
		uc.treeCacheRequest = self._tree

	def _trees(self):
		"""(vista de control, vista sin filtrar) de una lista como la de Firefox 159."""
		import test_browse as tb

		def lista(full: bool):
			items = []
			for texto in ("Primer elemento de la lista", "Segundo elemento"):
				kids = [tb.text("• ")] + ([tb.text(texto)] if full else [])
				items.append(tb.FakeEl(uc.CT_LISTITEM, "", kids))
			return tb.FakeEl(uc.CT_DOCUMENT, "Prueba", [tb.FakeEl(uc.CT_LIST, "", items)])

		return lista(False), lista(True)

	def _build(self, framework: str, provider: str):
		from tiresias.browse.buffer import VirtualBuffer

		control, raw = self._trees()
		doc = _Doc(framework, provider, control, raw)
		buf = VirtualBuffer(doc)
		buf.build()
		return doc, [ln for ln in buf.text.split("\n") if ln.strip()]

	def test_gecko_usa_la_vista_sin_filtrar(self) -> None:
		doc, lineas = self._build("Gecko", GECKO)
		self.assertEqual(doc.requests, [uc.rawTreeCacheRequest])
		self.assertEqual(lineas, ["• Primer elemento de la lista", "• Segundo elemento"])

	def test_chromium_y_puente_msaa_siguen_con_la_vista_de_control(self) -> None:
		doc, _l = self._build("Chrome", "")
		self.assertEqual(doc.requests, [uc.treeCacheRequest])
		doc, _l = self._build("Gecko", GECKO_PROXY)
		self.assertEqual(doc.requests, [uc.treeCacheRequest])

	def test_sin_uia_iniciado_no_falla(self) -> None:
		uc.rawTreeCacheRequest = None
		doc, _l = self._build("Gecko", GECKO)
		self.assertEqual(doc.requests, [uc.treeCacheRequest])


class ListMarkerTests(unittest.TestCase):
	def setUp(self) -> None:
		self._saved = dict(conf["browseMode"])
		conf["browseMode"]["useScreenLayout"] = False
		conf["browseMode"]["maxLineLength"] = 200
		conf["browseMode"]["containerLinesApart"] = False

	def tearDown(self) -> None:
		conf["browseMode"].update(self._saved)

	def test_marcadores(self) -> None:
		from tiresias.browse.buffer import Node, isListMarker
		from tiresias.objects.roles import Role

		def nodo(name: str, role=Role.STATICTEXT) -> Node:
			n = Node()
			n.name = name
			n.role = role
			return n

		for m in ("•", "◦", "▪", "1.", "12)", "a.", "iv.", "(3)", "→", "-"):
			self.assertTrue(isListMarker(nodo(m)), m)
		for m in ("Hola mundo", "", "12345.", "•", "texto largo."):
			if m == "•":
				self.assertFalse(isListMarker(nodo(m, Role.LINK)))
			else:
				self.assertFalse(isListMarker(nodo(m)), m)

	def test_la_vineta_va_con_el_bloque(self) -> None:
		import test_browse as tb

		item = tb.FakeEl(uc.CT_LISTITEM, "", [tb.text("• "), tb.group(tb.text("Texto en un div"))])
		para = tb.FakeEl(uc.CT_LISTITEM, "", [tb.text("2. "), tb.group(tb.text("Párrafo uno")), tb.group(tb.text("Párrafo dos"))])
		buf = tb.build(tb.FakeEl(uc.CT_LIST, "", [item, para]))
		lineas = [ln.strip() for ln in buf.text.split("\n") if ln.strip()]
		self.assertEqual(lineas, ["• Texto en un div", "2. Párrafo uno", "Párrafo dos"])


# ====================================================================== formato de la hora
class TimeFormatTests(unittest.TestCase):
	def setUp(self) -> None:
		self._saved = conf["general"].get("timeFormat", "system")

	def tearDown(self) -> None:
		conf["general"]["timeFormat"] = self._saved

	def test_por_defecto_el_del_sistema(self) -> None:
		self.assertEqual(conf.defaults["general"]["timeFormat"], "system")
		from tiresias.config import validation

		self.assertEqual(validation.CHOICES[("general", "timeFormat")], time_format.MODES)

	def test_24_y_12_horas(self) -> None:
		with mock.patch.object(time_format, "designators", return_value=("a. m.", "p. m.")):
			cases = [((15, 5), "15:05", "3:05 p. m."), ((0, 7), "00:07", "12:07 a. m."), ((12, 30), "12:30", "12:30 p. m."), ((9, 0), "09:00", "9:00 a. m.")]
			for (h, m), h24, h12 in cases:
				d = datetime.datetime(2026, 11, 4, h, m)
				self.assertEqual(time_format.formatTime(d, "24"), h24)
				self.assertEqual(time_format.formatTime(d, "12"), h12)

	def test_sistema_usa_windows_y_si_falla_24_horas(self) -> None:
		d = datetime.datetime(2026, 11, 4, 15, 5)
		with mock.patch.object(time_format, "_windowsTime", return_value="3:05 p. m."):
			self.assertEqual(time_format.formatTime(d, "system"), "3:05 p. m.")
		with mock.patch.object(time_format, "_windowsTime", return_value=""):
			self.assertEqual(time_format.formatTime(d, "system"), "15:05")
		# Con Windows de verdad, la hora real tiene minutos.
		self.assertIn("05", time_format.formatTime(d, "system"))

	def test_lee_la_configuracion(self) -> None:
		d = datetime.datetime(2026, 11, 4, 15, 5)
		conf["general"]["timeFormat"] = "12"
		with mock.patch.object(time_format, "designators", return_value=("a. m.", "p. m.")):
			self.assertEqual(time_format.formatTime(d), "3:05 p. m.")
		conf["general"]["timeFormat"] = "raro"
		self.assertEqual(time_format.currentMode(), "system")

	def test_orden_de_la_hora(self) -> None:
		from tiresias import global_commands

		conf["general"]["timeFormat"] = "12"
		spoken = []
		with (
			mock.patch.object(global_commands, "repeatCount", return_value=0),
			mock.patch.object(global_commands.speech, "speakMessage", side_effect=spoken.append),
			mock.patch.object(time_format, "designators", return_value=("a. m.", "p. m.")),
		):
			global_commands.GlobalCommands.script_dateTime(object(), None)
		self.assertEqual(len(spoken), 1)
		self.assertRegex(spoken[0], r"^\d{1,2}:\d\d [ap]\. m\.$")


# ====================================================================== portapapeles
class ClipboardSilenceTests(unittest.TestCase):
	"""Un complemento (modo juego de TCA-Portapapeles) calla «Copiado: …»; el historial sigue."""

	def setUp(self) -> None:
		from tiresias import clipboard

		self.cb = clipboard
		self._saved = dict(conf["clipboard"])
		self._history = list(clipboard.history)
		conf["clipboard"]["announceCopy"] = True
		conf["clipboard"]["historyEnabled"] = True
		clipboard.history.clear()
		self.seq = [100]

	def tearDown(self) -> None:
		conf["clipboard"].update(self._saved)
		self.cb.history[:] = self._history
		self.cb._silencedBy.clear()

	def _copiar(self, text: str) -> list[str]:
		self.seq[0] += 1
		spoken: list[str] = []
		with (
			mock.patch.object(self.cb.winapi.user32, "GetClipboardSequenceNumber", return_value=self.seq[0]),
			mock.patch.object(self.cb.winapi, "getClipboardText", return_value=text),
			mock.patch.object(self.cb, "isSensitiveContent", return_value=False),
			mock.patch.object(self.cb.speech, "speakMessage", side_effect=spoken.append),
		):
			self.cb._check()
		return spoken

	def test_callar_y_volver(self) -> None:
		self.assertEqual(self._copiar("uno"), ["Copiado: uno"])
		self.cb.silenceAnnouncements("tcaPortapapeles")
		self.assertTrue(self.cb.announcementsSilenced())
		self.assertEqual(self._copiar("dos"), [])
		self.assertEqual([t for _ts, t in self.cb.history], ["uno", "dos"])
		self.cb.silenceAnnouncements("tcaPortapapeles", False)
		self.assertFalse(self.cb.announcementsSilenced())
		self.assertEqual(self._copiar("tres"), ["Copiado: tres"])

	def test_nombre_antiguo(self) -> None:
		self.assertIs(self.cb._focusIsEditable, self.cb.focusIsEditable)


# ====================================================================== menú
class MenuTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		import wx

		cls._app = wx.App.Get() or wx.App(False)

	def _walk(self, menu, problems: list, path: str = "") -> list[str]:
		labels = []
		keys = collections.Counter()
		for item in menu.GetMenuItems():
			if item.IsSeparator():
				labels.append("—")
				continue
			label = item.GetItemLabel()
			if "&" in label:
				keys[label[label.index("&") + 1].lower()] += 1
			labels.append(label.replace("&", ""))
			if item.GetSubMenu():
				self._walk(item.GetSubMenu(), problems, path + "/" + label.replace("&", ""))
		problems.extend(f"{path}: «{k}» repetida" for k, n in keys.items() if n > 1)
		return labels

	def test_menu_ordenado_sin_letras_repetidas(self) -> None:
		from tiresias import gui

		frame = gui.MainFrame("prueba")
		try:
			menu = gui._buildMainMenu(frame)
			problems: list[str] = []
			top = self._walk(menu, problems)
			self.assertEqual(problems, [])
			main = [lbl for lbl in top if lbl in ("Preferencias", "Herramientas", "Visión e IA", "Acceso remoto", "Complementos", "Ayuda")]
			self.assertEqual(main, ["Preferencias", "Herramientas", "Visión e IA", "Acceso remoto", "Complementos", "Ayuda"])
			sub = {i.GetItemLabel().replace("&", ""): i.GetSubMenu() for i in menu.GetMenuItems() if i.GetSubMenu()}
			tools = self._walk(sub["Herramientas"], [])
			self.assertEqual(tools[0], "Paleta de órdenes...")
			self.assertIn("Herramientas avanzadas", tools)
			self.assertNotIn("Recargar complementos", tools)
			self.assertIn("Recargar complementos", self._walk(sub["Complementos"], []))
			advanced = next(i.GetSubMenu() for i in sub["Herramientas"].GetMenuItems() if i.GetItemLabel().replace("&", "") == "Herramientas avanzadas")
			self.assertEqual(self._walk(advanced, [])[0], "Visor de registro...")
			prefs = self._walk(sub["Preferencias"], [])
			self.assertEqual(prefs[:3], ["Opciones...", "Ajustes rápidos...", "Perfiles de configuración..."])
			vision = self._walk(sub["Visión e IA"], [])
			self.assertEqual(vision[:6], ["Describir con IA", "Documentos y páginas con IA", "Traducción", "CAPTCHA", "Reconocimiento de texto (OCR)", "Ratón y audio"])
			self.assertEqual(vision[-2:], ["Agente de IA...", "Ayuda de Tiresias con IA..."])
			menu.Destroy()
		finally:
			frame.Destroy()

	def test_lista_de_acciones_sin_letras_de_acceso(self) -> None:
		from tiresias import vision_commands

		labels = [vision_commands._actionLabel(g, lbl) for g, lbl, _f in vision_commands.menuActions()]
		self.assertTrue(all("&" not in lbl for lbl in labels))
		self.assertIn("Agente de IA...", labels)
		self.assertIn("Describir toda la pantalla (Describir con IA)", labels)


if __name__ == "__main__":
	unittest.main()
