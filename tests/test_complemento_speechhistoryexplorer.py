"""Pruebas del complemento «Explorador del historial de voz» (complementos_tienda/speechHistoryExplorer).

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_complemento_speechhistoryexplorer -v``
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
ADDON = os.path.join(ROOT, "complementos_tienda", "speechHistoryExplorer")
sys.path.insert(0, os.path.join(ADDON, "globalPlugins"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_speechhistoryexplorer_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]
else:
	_TMP = paths._dataDirForTests  # type: ignore[attr-defined]

from tiresias.baseobject import normalizeGestureId  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.speech import api as speechApi  # noqa: E402

_oldBytecode = sys.dont_write_bytecode
sys.dont_write_bytecode = True  # No deja __pycache__ en la carpeta del complemento.
import speechHistoryExplorer as shx  # noqa: E402
from speechHistoryExplorer import dialog, options  # noqa: E402

sys.dont_write_bytecode = _oldBytecode


class FakeHistory:
	"""Historial de voz simulado: lo que el complemento dice se añade con su origen, como hace Tiresias."""

	def __init__(self, texts=()):
		self.entries = [speechApi.HistoryEntry(time.time(), t, speechApi.ORIGIN_FOCUS) for t in texts]
		self.spoken: list[str] = []
		self.notices: list[str] = []

	def add(self, text: str, origin: str = speechApi.ORIGIN_FOCUS) -> None:
		self.entries.append(speechApi.HistoryEntry(time.time(), text.strip(), origin))

	def getHistory(self):
		return list(self.entries)

	def clearHistory(self):
		self.entries.clear()

	def speakText(self, text, symbolLevel=None, priority=None):
		self.spoken.append(text)
		self.add(text, speechApi.currentOrigin())

	def speakMessage(self, text, priority=None):
		self.notices.append(text)
		self.add(text, speechApi.currentOrigin())


def _defaults() -> None:
	for k, v in options.DEFAULTS.items():
		conf[options.SECTION][k] = v


# ====================================================================== manifiesto y archivos
class TestPaquete(unittest.TestCase):
	def test_manifiesto(self):
		with open(os.path.join(ADDON, "manifest.json"), encoding="utf-8-sig") as f:
			m = json.load(f)
		self.assertEqual(m["id"], "speechHistoryExplorer")
		self.assertEqual(m["name"], "Explorador del historial de voz")
		self.assertEqual(m["version"], "1.0.0")
		self.assertEqual(m["url"], "https://github.com/davidacm/SpeechHistoryExplorer")
		self.assertIn("Tyler Spivey, James Scholes y David CM", m["author"])
		self.assertTrue(m["changelog"].startswith("Primera versión para Tiresias"))
		self.assertEqual((m["minApiVersion"], m["lastTestedApiVersion"]), ("1.0", "1.0"))
		for text in ("Tiresias+Alt+F11", "Tiresias+Alt+F12", "Tiresias+Control+F12", "Tiresias+Mayúsculas+F12"):
			self.assertIn(text, m["description"])

	def test_archivos(self):
		for rel in ("doc/es/readme.html", "globalPlugins/speechHistoryExplorer/__init__.py", "globalPlugins/speechHistoryExplorer/options.py",
				"globalPlugins/speechHistoryExplorer/dialog.py"):
			self.assertTrue(os.path.isfile(os.path.join(ADDON, rel)), rel)

	def test_readme_documenta_todo(self):
		with open(os.path.join(ADDON, "doc", "es", "readme.html"), encoding="utf-8") as f:
			html = f.read()
		for text in ("Tiresias+Alt+F11", "Tiresias+Alt+F12", "Tiresias+Control+F12", "Tiresias+Mayúsculas+F12", "Tiresias+Mayúsculas+F11",
				"Tiresias+Alt+X", "Tamaño del historial de voz", "Copiar elemento", "Copiar todo", "Limpiar historial", "Actualizar", "Cerrar",
				"Buscar", "Recortar los espacios del principio", "Recortar los espacios del final", "Pitar al realizar acciones",
				"Pitido a la izquierda o a la derecha", "izquierda", "derecha", "GPL", "Tyler Spivey", "James Scholes", "David CM"):
			self.assertIn(text, html)

	def test_sin_modulos_ausentes_en_compilada(self):
		folder = os.path.join(ADDON, "globalPlugins", "speechHistoryExplorer")
		for fn in os.listdir(folder):
			if fn.endswith(".py"):
				with open(os.path.join(folder, fn), encoding="utf-8") as f:
					src = f.read()
				self.assertNotRegex(src, r"^\s*(import datetime|from datetime)", fn)
				self.assertNotIn("winsound", src, fn)


# ====================================================================== complemento global
class TestComplemento(unittest.TestCase):
	def setUp(self):
		self.plugin = shx.GlobalPlugin()
		_defaults()
		self.hist = FakeHistory(["uno", "dos", "tres"])
		self._patches = [
			mock.patch.object(speechApi, "getHistory", self.hist.getHistory),
			mock.patch.object(speechApi, "clearHistory", self.hist.clearHistory),
			mock.patch.object(speechApi, "speakText", self.hist.speakText),
			mock.patch.object(speechApi, "speakMessage", self.hist.speakMessage),
			mock.patch("tiresias.audio.tones.beep"),
			mock.patch("tiresias.api.copyToClip", return_value=True),
			mock.patch.object(shx, "isSecureContext", return_value=False),
		]
		started = [p.start() for p in self._patches]
		self.beep = started[4]
		self.copy = started[5]

	def tearDown(self):
		for p in self._patches:
			p.stop()
		self.plugin.terminate()
		_defaults()

	def test_opciones_por_defecto(self):
		self.assertEqual(conf["speechHistoryExplorer"]["trimWhitespaceFromStart"], False)
		self.assertEqual(conf["speechHistoryExplorer"]["trimWhitespaceFromEnd"], True)
		self.assertEqual(conf["speechHistoryExplorer"]["beepWhenPerformingActions"], True)
		self.assertEqual(conf["speechHistoryExplorer"]["beepPanning"], True)
		conf["speechHistoryExplorer"]["beepPanning"] = "sí"
		self.assertEqual(options.get("beepPanning"), True)
		# El tamaño es la opción de Tiresias, no una propia.
		self.assertNotIn("speechHistorySize", options.DEFAULTS)
		self.assertEqual(options.getHistorySize(), conf["speech"]["speechHistorySize"])

	def test_panel_registrado(self):
		from tiresias.gui import settings as S

		self.assertIn(options.PANEL_ID, S._panels)
		title, cls = S._panels[options.PANEL_ID]
		self.assertEqual(title, "Explorador del historial de voz")
		self.assertTrue(issubclass(cls, S.ConfigPanel))
		fields = {f.key: f for f in cls.fields}
		self.assertEqual(fields["speechHistorySize"].section, "speech")
		self.assertEqual((fields["speechHistorySize"].minVal, fields["speechHistorySize"].maxVal), (10, 10000))
		for key in options.DEFAULTS:
			self.assertEqual(fields[key].kind, "bool", key)
			self.assertIsNone(fields[key].section, key)
		self.plugin.terminate()
		self.assertNotIn(options.PANEL_ID, S._panels)

	def test_panel_real_guarda(self):
		import wx

		app = wx.App.Get() or wx.App(False)  # noqa: F841
		frame = wx.Frame(None)
		oldSize = conf["speech"]["speechHistorySize"]
		try:
			panel = options.panelClass()(frame)
			size = panel.getControl("speechHistorySize", "speech")
			self.assertIsInstance(size, wx.SpinCtrl)
			self.assertEqual(size.GetValue(), oldSize)
			labels = [c.GetLabel() for c in panel.GetChildren() if isinstance(c, (wx.StaticText, wx.CheckBox))]
			for label in options.LABELS.values():
				self.assertIn(label, labels)
			start = panel.getControl("trimWhitespaceFromStart")
			end = panel.getControl("trimWhitespaceFromEnd")
			self.assertFalse(start.GetValue())
			self.assertTrue(end.GetValue())
			size.SetValue(777)
			start.SetValue(True)
			end.SetValue(False)
			panel.getControl("beepPanning").SetValue(False)
			panel.onSave()
			self.assertEqual(conf["speech"]["speechHistorySize"], 777)
			self.assertEqual(conf["speechHistoryExplorer"]["trimWhitespaceFromStart"], True)
			self.assertEqual(conf["speechHistoryExplorer"]["trimWhitespaceFromEnd"], False)
			self.assertEqual(conf["speechHistoryExplorer"]["beepPanning"], False)
			panel.resetToFactory()
			panel.onSave()
			self.assertEqual(conf["speech"]["speechHistorySize"], 500)
			self.assertEqual(conf["speechHistoryExplorer"]["trimWhitespaceFromStart"], False)
			self.assertEqual(conf["speechHistoryExplorer"]["trimWhitespaceFromEnd"], True)
			self.assertEqual(conf["speechHistoryExplorer"]["beepPanning"], True)
		finally:
			conf["speech"]["speechHistorySize"] = oldSize
			frame.Destroy()

	def test_gestos(self):
		expected = {
			"kb:tiresias+alt+f11": "previousItem",
			"kb:tiresias+alt+f12": "nextItem",
			"kb:tiresias+control+f12": "copyItem",
			"kb:tiresias+shift+f12": "showHistory",
		}
		self.assertEqual(dict(shx.GlobalPlugin._classGestures), expected)

	def test_descripcion_y_categoria(self):
		names = [n for n in dir(shx.GlobalPlugin) if n.startswith("script_")]
		self.assertEqual(len(names), 4)
		for n in names:
			func = getattr(shx.GlobalPlugin, n)
			self.assertTrue(func.__doc__, n)
			self.assertEqual(func.category, "Explorador del historial de voz", n)
		for n in ("previousItem", "nextItem", "copyItem"):
			self.assertTrue(getattr(shx.GlobalPlugin, "script_" + n).speakOnDemand, n)

	def test_gestos_sin_conflictos(self):
		# Ningún gesto del complemento está ya en el núcleo ni en los demás complementos.
		mine = [normalizeGestureId(g) for g in shx.GlobalPlugin._classGestures]
		pattern = re.compile(r"kb(?:\([a-z]+\))?:[A-Za-z0-9+]+")
		used = set()
		for base in (os.path.join(ROOT, "src", "tiresias"), os.path.join(ROOT, "data", "addons"), os.path.join(ROOT, "complementos_tienda")):
			for dirpath, _dirs, files in os.walk(base):
				if os.path.abspath(dirpath).startswith(os.path.abspath(ADDON)):
					continue
				for fn in files:
					if fn.endswith(".py"):
						with open(os.path.join(dirpath, fn), encoding="utf-8", errors="replace") as f:
							for m in pattern.findall(f.read()):
								used.add(normalizeGestureId(m.split(":", 1)[0].split("(")[0] + ":" + m.split(":", 1)[1]))
		for g in mine:
			self.assertNotIn(g, used, g)

	# ---------------------------------------------------------------- navegación
	def test_anterior_y_siguiente(self):
		p = self.plugin
		p.script_previousItem(None)
		self.assertEqual(self.hist.spoken, ["dos"])
		self.beep.assert_not_called()
		p.script_previousItem(None)
		self.assertEqual(self.hist.spoken[-1], "uno")
		# Al principio del historial: pitido a la izquierda y se repite el elemento.
		p.script_previousItem(None)
		self.assertEqual(self.hist.spoken[-1], "uno")
		self.beep.assert_called_once_with(220, 100, 100, 0)
		self.assertEqual(p.position, 2)
		p.script_nextItem(None)
		self.assertEqual(self.hist.spoken[-1], "dos")
		p.script_nextItem(None)
		self.assertEqual(self.hist.spoken[-1], "tres")
		# Al final: pitido a la derecha.
		p.script_nextItem(None)
		self.assertEqual(self.hist.spoken[-1], "tres")
		self.assertEqual(self.beep.call_args_list[-1], mock.call(220, 100, 0, 100))
		self.assertEqual(p.position, 0)
		# Lo dicho por el explorador se marcó con su origen y no cuenta como elemento.
		self.assertEqual(shx.historyTexts(), ["uno", "dos", "tres"])
		self.assertEqual([e.origin for e in self.hist.entries[3:]], [shx.ORIGIN] * 6)

	def test_vuelve_al_mas_reciente_si_tiresias_habla(self):
		p = self.plugin
		p.script_previousItem(None)
		p.script_previousItem(None)
		self.assertEqual(p.position, 2)
		self.hist.add("cuatro")
		p.script_previousItem(None)
		self.assertEqual(p.position, 1)
		self.assertEqual(self.hist.spoken[-1], "tres")
		self.hist.add("cinco", speechApi.ORIGIN_MESSAGE)
		p.script_nextItem(None)
		# Posición nueva 0 → no hay más recientes: pitido y se dice el último.
		self.assertEqual(self.hist.spoken[-1], "cinco")
		self.assertEqual(self.beep.call_args_list[-1], mock.call(220, 100, 0, 100))

	def test_pitidos_segun_opciones(self):
		p = self.plugin
		conf["speechHistoryExplorer"]["beepPanning"] = False
		p.script_nextItem(None)
		self.beep.assert_called_once_with(220, 100)
		conf["speechHistoryExplorer"]["beepWhenPerformingActions"] = False
		p.script_nextItem(None)
		p.script_copyItem(None)
		self.beep.assert_called_once()
		self.copy.assert_called_once_with("tres")

	def test_historial_vacio(self):
		self.hist.entries.clear()
		for name in ("previousItem", "nextItem", "copyItem"):
			getattr(self.plugin, "script_" + name)(None)
		self.assertEqual(self.hist.notices, [shx.EMPTY_MESSAGE] * 3)
		self.assertEqual(self.hist.spoken, [])
		self.copy.assert_not_called()
		# El aviso tampoco cuenta como elemento del historial.
		self.assertEqual(shx.historyTexts(), [])

	# ---------------------------------------------------------------- copiar
	def test_copiar_el_actual_con_recorte(self):
		p = self.plugin
		self.hist.add("  hola  ")
		self.hist.entries[-1] = speechApi.HistoryEntry(0, "  hola  ", speechApi.ORIGIN_FOCUS)
		p.script_copyItem(None)
		self.copy.assert_called_once_with("  hola")
		self.beep.assert_called_once_with(1500, 120)
		conf["speechHistoryExplorer"]["trimWhitespaceFromStart"] = True
		p.script_copyItem(None)
		self.assertEqual(self.copy.call_args[0][0], "hola")
		conf["speechHistoryExplorer"]["trimWhitespaceFromEnd"] = False
		p.script_copyItem(None)
		self.assertEqual(self.copy.call_args[0][0], "hola  ")
		conf["speechHistoryExplorer"]["trimWhitespaceFromStart"] = False
		p.script_copyItem(None)
		self.assertEqual(self.copy.call_args[0][0], "  hola  ")
		# Copia el elemento al que se ha navegado.
		p.script_previousItem(None)
		p.script_copyItem(None)
		self.assertEqual(self.copy.call_args[0][0], "tres")

	def test_copiar_falla_o_pantalla_segura(self):
		self.copy.return_value = False
		self.plugin.script_copyItem(None)
		self.beep.assert_not_called()
		self.assertEqual(self.hist.notices, [shx.COPY_FAILED_MESSAGE])
		with mock.patch.object(shx, "isSecureContext", return_value=True):
			self.plugin.script_copyItem(None)
		self.assertEqual(self.copy.call_count, 1)
		self.assertEqual(self.hist.notices[-1], shx.SECURE_MESSAGE)

	def test_reiniciar_posicion(self):
		p = self.plugin
		p.script_previousItem(None)
		self.assertEqual(p.position, 1)
		p.resetPosition()
		self.assertEqual(p.position, 0)
		self.assertEqual(p.currentText(), "tres")


# ====================================================================== diálogo
class TestDialogo(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		import wx

		cls.app = wx.App.Get() or wx.App(False)

	def setUp(self):
		_defaults()
		self.plugin = shx.GlobalPlugin()
		self.hist = FakeHistory(["primero", "segundo de prueba", "Tercero con Árbol"])
		self.hist.add("eco del explorador", shx.ORIGIN)
		self._patches = [
			mock.patch.object(speechApi, "getHistory", self.hist.getHistory),
			mock.patch.object(speechApi, "clearHistory", self.hist.clearHistory),
			mock.patch.object(speechApi, "speakMessage", self.hist.speakMessage),
			mock.patch("tiresias.audio.tones.beep"),
			mock.patch("tiresias.api.copyToClip", return_value=True),
			mock.patch.object(shx, "isSecureContext", return_value=False),
		]
		started = [p.start() for p in self._patches]
		self.beep = started[3]
		self.copy = started[4]
		self.dlg = dialog.HistoryDialog(self.plugin)

	def tearDown(self):
		import wx

		if not self.dlg.closed:
			self.dlg.Destroy()
		wx.GetApp().ProcessPendingEvents()
		for p in self._patches:
			p.stop()
		self.plugin.terminate()
		_defaults()

	def _items(self):
		return [self.dlg.list.GetItemText(i) for i in range(self.dlg.list.GetItemCount())]

	def test_lista_mas_reciente_primero_sin_ecos(self):
		self.assertEqual(self._items(), ["Tercero con Árbol", "segundo de prueba", "primero"])
		self.assertEqual(self.dlg.GetTitle(), "Elementos del historial de voz")
		self.assertEqual(self.dlg.list.GetFirstSelected(), 0)
		self.assertEqual(self.dlg.full.GetValue(), "Tercero con Árbol")
		self.assertTrue(self.dlg.copyButton.IsEnabled())

	def test_vista_previa_recortada(self):
		self.assertEqual(dialog.preview("a" * 150), "a" * 100 + "…")
		self.assertEqual(dialog.preview("línea 1\n  línea 2"), "línea 1 línea 2")

	def test_busqueda(self):
		self.assertEqual(dialog.filterHistory(["Árbol alto", "arbol", "casa"], "ARBOL"), ["Árbol alto", "arbol"])
		self.assertEqual(dialog.filterHistory(["segundo de prueba", "prueba"], "prueba segundo"), ["segundo de prueba"])
		self.dlg.search.SetValue("prueba")
		self.dlg.onSearch(mock.Mock())
		self.assertEqual(self._items(), ["segundo de prueba"])
		self.assertEqual(self.dlg.full.GetValue(), "segundo de prueba")
		self.dlg.search.SetValue("")
		self.dlg.onSearch(mock.Mock())
		self.assertEqual(len(self._items()), 3)
		self.dlg.search.SetValue("nada de nada")
		self.dlg.onSearch(mock.Mock())
		self.assertEqual(self._items(), [])
		self.assertEqual(self.dlg.full.GetValue(), "")
		self.assertFalse(self.dlg.copyButton.IsEnabled())
		self.assertFalse(self.dlg.copyAllButton.IsEnabled())

	def test_seleccion_multiple_y_copiar(self):
		self.dlg.list.Select(1)
		self.dlg.updateSelection()
		self.assertEqual(self.dlg.full.GetValue(), "Tercero con Árbol\nsegundo de prueba")
		self.dlg.copySelected()
		self.copy.assert_called_once_with("Tercero con Árbol\nsegundo de prueba")
		self.beep.assert_called_once_with(1500, 120)

	def test_copiar_todo_respeta_la_busqueda(self):
		self.dlg.copyAll()
		self.copy.assert_called_once_with("Tercero con Árbol\nsegundo de prueba\nprimero")
		self.dlg.search.SetValue("segundo")
		self.dlg.onSearch(mock.Mock())
		self.dlg.copyAll()
		self.assertEqual(self.copy.call_args[0][0], "segundo de prueba")

	def test_actualizar(self):
		self.hist.add("cuarto")
		self.assertEqual(len(self._items()), 3)
		self.dlg.reload()
		self.assertEqual(self._items()[0], "cuarto")

	def test_limpiar_historial(self):
		with mock.patch.object(self.dlg, "confirmClear", return_value=False):
			self.dlg.clear()
		self.assertEqual(len(self.hist.entries), 4)
		self.assertFalse(self.dlg.closed)
		with mock.patch.object(self.dlg, "confirmClear", return_value=True):
			self.dlg.clear()
		self.assertEqual(self.hist.entries, [])
		self.assertTrue(self.dlg.closed)
		self.assertIsNone(self.plugin._items)

	def test_una_sola_instancia(self):
		import wx

		dialog._dialog = None
		with mock.patch.object(dialog, "bringToFront"):
			dialog.showHistoryDialog(self.plugin)
			first = dialog._dialog
			self.assertIsInstance(first, dialog.HistoryDialog)
			self.hist.add("nuevo")
			dialog.showHistoryDialog(self.plugin)
			self.assertIs(dialog._dialog, first)
			self.assertEqual(first.list.GetItemText(0), "nuevo")
			dialog.closeDialog()
			self.assertTrue(first.closed)
			self.assertIsNone(dialog._dialog)
		wx.GetApp().ProcessPendingEvents()


if __name__ == "__main__":
	unittest.main()
