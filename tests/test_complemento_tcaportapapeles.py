"""Pruebas del complemento «TCA-Portapapeles» (complementos_tienda/tcaPortapapeles).

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m pytest tests\\test_complemento_tcaportapapeles.py -q``

Ninguna prueba toca el portapapeles real, la red ni el teclado: se simulan.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
import wave
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
ADDON = os.path.join(ROOT, "complementos_tienda", "tcaPortapapeles")
sys.path.insert(0, os.path.join(ADDON, "globalPlugins"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_tcaportapapeles_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]
else:
	_TMP = paths._dataDirForTests  # type: ignore[attr-defined]

from tiresias.baseobject import normalizeGestureId  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.input import core as inputCore  # noqa: E402

_oldBytecode = sys.dont_write_bytecode
sys.dont_write_bytecode = True  # No deja __pycache__ en la carpeta del complemento.
import tcaPortapapeles as tca  # noqa: E402
from tcaPortapapeles import dialogos, historial, juego, opciones, portapapeles, texto  # noqa: E402

sys.dont_write_bytecode = _oldBytecode

SPEAK = "tiresias.speech.api.speakMessage"
SPEAK_TEXT = "tiresias.speech.api.speakText"


class FakeGesture:
	isModifier = False

	def __init__(self, keys: str, vk: int = 0) -> None:
		gid = normalizeGestureId("kb:" + keys)
		self.identifiers = [gid.replace("kb:", "kb(desktop):", 1), gid]
		parts = gid.split(":", 1)[1].split("+")
		self.modifiers = frozenset(parts[:-1])
		self.vk = vk


def _elemento(textoEl: str, formatos=None, archivos=None) -> portapapeles.Elemento:
	return portapapeles.Elemento(textoEl, dict(formatos or {}), list(archivos or []))


def _dropfiles(rutas: list[str]) -> bytes:
	"""Estructura DROPFILES con rutas en UTF-16 (como la pone el Explorador)."""
	cuerpo = ("\0".join(rutas) + "\0\0").encode("utf-16-le")
	cabecera = (20).to_bytes(4, "little") + bytes(8) + bytes(4) + (1).to_bytes(4, "little")
	return cabecera + cuerpo


def _resetConf() -> None:
	opciones.registerDefaults()
	for k, v in opciones.DEFAULTS.items():
		conf[opciones.SECCION][k] = list(v) if isinstance(v, list) else v


# ====================================================================== paquete
class TestPaquete(unittest.TestCase):
	def test_manifiesto(self):
		with open(os.path.join(ADDON, "manifest.json"), encoding="utf-8-sig") as f:
			m = json.load(f)
		self.assertEqual(m["id"], "tcaPortapapeles")
		self.assertEqual(m["name"], "TCA-Portapapeles")
		self.assertEqual(m["version"], "1.0.0")
		self.assertEqual(m["url"], "https://github.com/peterrc87/TCA_Portapapeles")
		self.assertTrue(m["author"].startswith("Proyecto Tiresias (basado en TCA-Portapapeles de Peter Reina"))
		self.assertIn("Héctor J. Benítez Corredera", m["author"])
		self.assertTrue(m["changelog"].startswith("Primera versión para Tiresias"))
		self.assertEqual((m["minApiVersion"], m["lastTestedApiVersion"]), ("1.0", "1.0"))
		self.assertIn("Tiresias+Control+Mayúsculas+V", m["description"])

	def test_archivos_y_sonidos(self):
		self.assertTrue(os.path.isfile(os.path.join(ADDON, "doc", "es", "readme.html")))
		for nombre in list(tca.SONIDOS.values()) + [tca.SONIDO_HISTORIAL]:
			ruta = os.path.join(tca.SONIDOS_DIR, nombre)
			self.assertTrue(os.path.isfile(ruta), nombre)
			with wave.open(ruta) as w:
				# Tiresias reproduce WAV de 16 bits.
				self.assertEqual(w.getsampwidth(), 2, nombre)

	def test_readme_documenta_todo(self):
		with open(os.path.join(ADDON, "doc", "es", "readme.html"), encoding="utf-8") as f:
			html = f.read()
		for t in ("Tiresias+Control+Mayúsculas+V", "Sin selección", "Pegar en el foco", "Borrar todo", "Refrescar", "Modo juego",
				"Conservar los signos de puntuación", "Tiresias+Alt+V", "Tiresias+C", "Teclas del portapapeles", "GPL",
				"Peter Reina", "Escape", "F1", "Google Translate", "Herramientas"):
			self.assertIn(t, html)
		for tecla in ("H", "L", "E", "P", "A", "J"):
			self.assertIn(f"<td>{tecla}</td>", html)

	def test_sin_modulos_ausentes_en_compilada(self):
		folder = os.path.join(ADDON, "globalPlugins", "tcaPortapapeles")
		for fn in os.listdir(folder):
			if fn.endswith(".py"):
				with open(os.path.join(folder, fn), encoding="utf-8") as f:
					src = f.read()
				self.assertNotRegex(src, r"^\s*(import datetime|from datetime)", fn)
				self.assertNotIn("winsound", src, fn)
				# Nada de la API de NVDA: el complemento usa la de Tiresias.
				self.assertNotRegex(src, r"^\s*import (ui|api|gui|globalPluginHandler|addonHandler)\b", fn)
				# Nunca se cambian los tipos de ctypes.windll (los comparte todo Tiresias).
				self.assertNotIn("windll.user32", src, fn)

	def test_carga_como_complemento(self):
		# Igual que addons.loadAll(): manifiesto, paquete y complemento global.
		from tiresias import addons
		from tiresias.plugins import handler as pluginHandler

		dst = os.path.join(tempfile.mkdtemp(prefix="tiresias_tca_carga_"), "tcaPortapapeles")
		shutil.copytree(ADDON, dst, ignore=shutil.ignore_patterns("__pycache__"))
		try:
			addon = addons.Addon(dst, addons._readManifest(dst))
			self.assertEqual(addon.id, "tcaPortapapeles")
			self.assertTrue(addon.isCompatible)
			self.assertIsNone(addon.incompatibilityReason())
			self.assertTrue(addon.docPath().endswith("readme.html"))
			pkg = addon.packageName
			addons._ensurePackage(pkg, dst)
			addons._ensurePackage(f"{pkg}.globalPlugins", addon.subdir("globalPlugins"))
			old = sys.dont_write_bytecode
			sys.dont_write_bytecode = True
			try:
				mod = pluginHandler._loadModule(f"{pkg}.globalPlugins.tcaPortapapeles", os.path.join(addon.subdir("globalPlugins"), "tcaPortapapeles"))
			finally:
				sys.dont_write_bytecode = old
			cls = mod.GlobalPlugin
			cls.vigilar = False
			p = cls()
			try:
				self.assertIn(p._decidir, inputCore.decide_executeGesture.handlers())
				self.assertEqual(p.getScript(FakeGesture("tiresias+control+shift+v")).__name__, "script_capa")
			finally:
				p.terminate()
			# Se puede empaquetar e inspeccionar como cualquier complemento.
			paquete = addons.createPackage(dst, os.path.join(os.path.dirname(dst), "tca.tiresias-addon"))
			manifest, _instalado = addons.inspectPackage(paquete)
			self.assertEqual(manifest["id"], "tcaPortapapeles")
		finally:
			for name in [n for n in sys.modules if n.startswith("tiresias_addons.tcaPortapapeles")]:
				del sys.modules[name]
			shutil.rmtree(os.path.dirname(dst), ignore_errors=True)


# ====================================================================== texto
class TestTexto(unittest.TestCase):
	def test_estadisticas(self):
		e = texto.estadisticas("Hola mundo.\nSegunda línea\n\nOtro párrafo")
		self.assertEqual((e.sinEspacios, e.conEspacios, e.palabras, e.lineas, e.parrafos), (33, 36, 6, 4, 2))
		e = texto.estadisticas("palabra")
		self.assertEqual((e.sinEspacios, e.conEspacios, e.palabras, e.lineas, e.parrafos), (7, 7, 1, 1, 1))
		e = texto.estadisticas("a b\r\nc")
		self.assertEqual((e.sinEspacios, e.conEspacios, e.lineas, e.parrafos), (3, 4, 2, 1))

	def test_mensaje_singular_y_plural(self):
		msg = texto.mensajeEstadisticas(texto.estadisticas("palabra"))
		self.assertEqual(msg, "7 caracteres (sin espacios).\n7 caracteres (con espacios).\n1 palabra.\n1 línea.\n1 párrafo.")
		msg = texto.mensajeEstadisticas(texto.Estadisticas(1, 2, 0, 2, 0))
		self.assertEqual(msg, "1 carácter (sin espacios).\n2 caracteres (con espacios).\n0 palabras.\n2 líneas.\n0 párrafos.")

	def test_trocear(self):
		self.assertEqual(texto.trocear("if event.GetUnicodeKey()"), ["if", "eventGetUnicodeKey"])
		self.assertEqual(texto.trocear("¿Hola, qué tal? ¡Bien!"), ["Hola", "qué", "tal", "Bien"])
		self.assertEqual(texto.trocear("¿Hola, qué tal?", conservarSignos=True), ["¿Hola,", "qué", "tal?"])

	def test_unir_en_orden_original(self):
		palabras = texto.trocear("Hola, como estás, el perro tiene hambre")
		self.assertEqual(texto.unirSeleccion(palabras, [6, 0, 4]), "Hola perro hambre")
		self.assertEqual(texto.unirSeleccion(palabras, [4, 4, 99]), "perro")


# ====================================================================== portapapeles (sin tocarlo)
class TestPortapapeles(unittest.TestCase):
	def test_texto_para_mostrar(self):
		self.assertEqual(portapapeles.textoParaMostrar("hola", []), "hola")
		self.assertEqual(portapapeles.textoParaMostrar(None, ["C:\\a\\b.txt"]), "b.txt")
		self.assertEqual(portapapeles.textoParaMostrar("x", ["C:\\a\\b.txt", "C:\\c\\carpeta\\"]), "(2) Archivos: b.txt, carpeta")
		self.assertEqual(portapapeles.textoParaMostrar(None, [], {portapapeles.CF_DIB: b"x"}), "(Imagen)")
		self.assertEqual(portapapeles.textoParaMostrar(None, [], {49999: b"x"}), "(Contenido con formato)")

	def test_dropfiles(self):
		rutas = ["C:\\uno.txt", "D:\\Carpeta con ñ"]
		self.assertEqual(portapapeles.archivosDeDropfiles(_dropfiles(rutas)), rutas)
		self.assertEqual(portapapeles.archivosDeDropfiles(b"corto"), [])

	def test_texto_unicode_y_limpieza(self):
		self.assertEqual(portapapeles.textoUnicode("añ€\0basura".encode("utf-16-le")), "añ€")
		for t in ("off", " Echo is off. ", "ECHO está desactivado"):
			self.assertTrue(portapapeles.esTextoDeLimpieza(t), t)
		self.assertFalse(portapapeles.esTextoDeLimpieza("offset"))

	def test_formatos_excluidos(self):
		for fmt in (portapapeles.CF_BITMAP, portapapeles.CF_ENHMETAFILE, portapapeles.CF_METAFILEPICT, portapapeles.CF_PALETTE):
			self.assertIn(fmt, portapapeles.FORMATOS_NO_GLOBALES)
		self.assertNotIn(portapapeles.CF_UNICODETEXT, portapapeles.FORMATOS_NO_GLOBALES)
		self.assertIn("Ole Private Data", portapapeles.FORMATOS_PRIVADOS)

	def test_dlls_propias(self):
		# Cargar las funciones no cambia las de ctypes.windll.
		before = ctypes.windll.user32.SetClipboardData.argtypes
		u, _k, _s = portapapeles._api()
		self.assertIsNot(u, ctypes.windll.user32)
		self.assertEqual(ctypes.windll.user32.SetClipboardData.argtypes, before)
		self.assertIsInstance(portapapeles.secuencia(), int)

	def test_escribir_sin_formatos_usa_texto(self):
		with mock.patch.object(portapapeles, "escribirTexto", return_value=True) as et:
			self.assertTrue(portapapeles.escribirTodo(_elemento("hola")))
		et.assert_called_once_with("hola")


# ====================================================================== historial
class TestHistorial(unittest.TestCase):
	def test_agregar_y_subir(self):
		h = historial.Historial()
		self.assertTrue(h.agregar(_elemento("a")))
		self.assertTrue(h.agregar(_elemento("b")))
		self.assertTrue(h.agregar(_elemento("a")))
		self.assertEqual([e.texto for e in h.elementos], ["a", "b"])
		self.assertEqual(len(h), 2)

	def test_mismo_contenido_conserva_formatos_completos(self):
		h = historial.Historial()
		h.agregar(_elemento("a", {13: b"a\0"}))
		completo = _elemento("a", {13: b"a\0", 49500: b"<b>a</b>"})
		self.assertFalse(h.agregar(completo))
		self.assertIs(h.elementos[0], completo)
		self.assertFalse(h.agregar(_elemento("a")))
		self.assertIs(h.elementos[0], completo)

	def test_ignora_vacios_y_limpieza(self):
		h = historial.Historial()
		self.assertFalse(h.agregar(_elemento("   \r\n")))
		self.assertFalse(h.agregar(_elemento("echo off")))
		self.assertTrue(h.agregar(_elemento("(Imagen)", {portapapeles.CF_DIB: b"x"})))
		self.assertTrue(h.agregar(_elemento("off", {49500: b"x"})))
		self.assertEqual(len(h), 2)

	def test_maximo(self):
		h = historial.Historial()
		for i in range(60):
			h.agregar(_elemento(f"t{i}"))
		self.assertEqual(len(h), historial.MAXIMO)
		self.assertEqual(h.elementos[0].texto, "t59")
		self.assertEqual(h.elementos[-1].texto, "t10")

	def test_borrar(self):
		h = historial.Historial()
		for t in ("a", "b", "c"):
			h.agregar(_elemento(t))
		b = h.elementos[1]
		self.assertTrue(h.borrar(b))
		self.assertFalse(h.borrar(b))
		self.assertEqual([e.texto for e in h.elementos], ["c", "a"])
		# Lo borrado se puede volver a copiar.
		self.assertTrue(h.agregar(_elemento("b")))
		h.borrarTodo()
		self.assertEqual(len(h), 0)
		self.assertTrue(h.agregar(_elemento("c")))

	def test_elementos_es_copia(self):
		h = historial.Historial()
		h.agregar(_elemento("a"))
		h.elementos.clear()
		self.assertEqual(len(h), 1)


class TestVigilante(unittest.TestCase):
	def test_comprobar(self):
		seq = [1]
		llamadas = []
		v = historial.Vigilante(200, lambda: llamadas.append(1), lambda: seq[0])
		self.assertEqual(v.intervalo, 0.2)
		self.assertFalse(v.comprobar())
		seq[0] = 2
		self.assertTrue(v.comprobar())
		self.assertFalse(v.comprobar())
		self.assertEqual(llamadas, [1])
		v.pausar()
		self.assertTrue(v.pausado)
		seq[0] = 3
		self.assertFalse(v.comprobar())
		seq[0] = 4
		v.reanudar()
		# Lo cambiado durante la pausa no cuenta.
		self.assertFalse(v.comprobar())
		seq[0] = 5
		self.assertTrue(v.comprobar())
		self.assertEqual(llamadas, [1, 1])
		v.cambiarIntervalo(5)
		self.assertEqual(v.intervalo, 0.02)

	def test_error_no_detiene(self):
		seq = [1]

		def falla():
			raise RuntimeError("x")

		v = historial.Vigilante(100, falla, lambda: seq[0])
		seq[0] = 2
		self.assertTrue(v.comprobar())

	def test_hilo(self):
		seq = [1]
		llamadas = []
		v = historial.Vigilante(20, lambda: llamadas.append(seq[0]), lambda: seq[0])
		v.start()
		try:
			seq[0] = 7
			for _i in range(100):
				if llamadas:
					break
				time.sleep(0.02)
		finally:
			v.detener()
			v.join(2)
		self.assertEqual(llamadas, [7])
		self.assertFalse(v.is_alive())


# ====================================================================== modo juego (sin red)
class _Respuesta:
	def __init__(self, datos) -> None:
		self._datos = json.dumps(datos).encode("utf-8")

	def read(self):
		return self._datos

	def __enter__(self):
		return self

	def __exit__(self, *a):
		return False


class TestJuego(unittest.TestCase):
	def test_trozos(self):
		self.assertEqual(juego.trozos("abc", 10), ["abc"])
		partes = juego.trozos("uno dos tres cuatro", 8)
		self.assertEqual("".join(partes), "uno dos tres cuatro")
		self.assertTrue(all(len(p) <= 8 for p in partes))
		self.assertEqual(juego.trozos("", 5), [])

	def test_traducir_google(self):
		pedidas = []

		def abrir(req):
			pedidas.append(req.full_url)
			return _Respuesta({"sentences": [{"trans": "Hola "}, {"trans": "mundo"}], "src": "en"})

		with mock.patch.object(juego, "_abrir", side_effect=abrir):
			self.assertEqual(juego.traducir("Hello world", "es"), "Hola mundo")
		self.assertEqual(len(pedidas), 1)
		self.assertIn("tl=es", pedidas[0])
		self.assertIn("sl=auto", pedidas[0])
		self.assertTrue(pedidas[0].startswith("https://"))

	def test_traducir_alternativa(self):
		def abrir(req):
			if "translate_a/single" in req.full_url:
				raise OSError("sin servicio")
			self.assertIn("tl=fr", req.full_url)
			self.assertEqual(req.data, b"q=Hola")
			return _Respuesta([["Bonjour", "es"]])

		with mock.patch.object(juego, "_abrir", side_effect=abrir):
			self.assertEqual(juego.traducir("Hola", "fr"), "Bonjour")

	def test_traducir_falla(self):
		with mock.patch.object(juego, "_abrir", side_effect=OSError("sin red")):
			with self.assertRaises(OSError):
				juego.traducir("Hola", "en")

	def test_traductor(self):
		entregas = []
		t = juego.Traductor(lambda: "en", lambda o, r: entregas.append((o, r)), lambda texto_, destino: texto_.upper() + destino)
		t.procesar("hola")
		self.assertEqual(entregas, [("hola", "HOLAen")])
		t = juego.Traductor(lambda: "en", lambda o, r: entregas.append((o, r)), mock.Mock(side_effect=RuntimeError("x")))
		t.procesar("adiós")
		self.assertEqual(entregas[-1], ("adiós", None))

	def test_traductor_en_hilo_en_orden(self):
		entregas = []
		t = juego.Traductor(lambda: "es", lambda o, r: entregas.append(r), lambda texto_, destino: "<" + texto_ + ">")
		t.start()
		for x in ("a", "b", "c"):
			t.pedir(x)
		t.detener()
		t.join(2)
		self.assertEqual(entregas, ["<a>", "<b>", "<c>"])

	def test_cola_limitada(self):
		t = juego.Traductor(lambda: "es", lambda o, r: None)
		for i in range(juego.MAX_COLA + 5):
			t.pedir(str(i))
		self.assertEqual(t._cola.qsize(), juego.MAX_COLA)
		self.assertEqual(t._cola.get_nowait(), "5")


# ====================================================================== complemento global
class TestComplemento(unittest.TestCase):
	def setUp(self):
		_resetConf()
		tca.GlobalPlugin.vigilar = False
		self.plugin = tca.GlobalPlugin()
		self.plugin.enHilo = False

	def tearDown(self):
		self.plugin.terminate()
		_resetConf()

	# ---------------------------------------------------------------- opciones y registro
	def test_opciones_por_defecto(self):
		s = conf[opciones.SECCION]
		self.assertTrue(s["activado"] and s["voz"] and s["audio"] and s["historial"] and s["sonidoHistorial"])
		self.assertFalse(s["vozCopiado"])
		self.assertFalse(s["modoJuego"])
		self.assertEqual((s["intervalo"], s["intervaloJuego"], s["idiomaJuego"]), (200, 200, "es"))
		self.assertEqual(list(s["teclasSeleccionarTodo"]), ["control+a", "control+e"])
		s["intervalo"] = 333
		s["idiomaJuego"] = "xx"
		self.assertEqual(opciones.get("intervalo"), 200)
		self.assertEqual(opciones.get("idiomaJuego"), "es")
		s["teclasCopiar"] = ["control+c", " control+insert ", ""]
		self.assertEqual(opciones.get("teclasCopiar"), ["control+c", "control+insert"])

	def test_panel_registrado(self):
		from tiresias.gui import settings as S

		self.assertIn(opciones.PANEL_ID, S._panels)
		title, cls = S._panels[opciones.PANEL_ID]
		self.assertEqual(title, "TCA-Portapapeles")
		self.assertTrue(issubclass(cls, S.ConfigPanel))
		fields = {f.key: f for f in cls.fields}
		self.assertEqual(set(fields), set(opciones.DEFAULTS) - {"modoJuego"})
		self.assertEqual([v for v, _l in fields["intervalo"].choices], [100, 200, 300, 400, 500, 1000])
		self.assertEqual([lbl for _v, lbl in fields["idiomaJuego"].choices][:3], ["Alemán", "Árabe", "Croata"])
		self.assertEqual(fields["teclasCopiar"].kind, "list")
		self.plugin.terminate()
		self.assertNotIn(opciones.PANEL_ID, S._panels)

	def test_panel_real_guarda_y_aplica(self):
		import wx

		app = wx.App.Get() or wx.App(False)  # noqa: F841
		frame = wx.Frame(None)
		try:
			panel = opciones.panelClass()(frame)
			def todos(w):
				for c in w.GetChildren():
					yield c
					yield from todos(c)

			labels = [c.GetLabel() for c in todos(panel) if isinstance(c, wx.StaticText)]
			self.assertIn("&Tiempo de actualización del monitor del portapapeles:", labels)
			self.assertIn("Teclas de &copiar:", labels)
			intervalo = panel.getControl("intervalo")
			self.assertEqual(intervalo.GetStringSelection(), "2 décimas de segundo")
			idioma = panel.getControl("idiomaJuego")
			self.assertEqual(idioma.GetStringSelection(), "Español")
			teclas = panel.getControl("teclasCopiar")
			self.assertEqual(teclas.GetValue(), "control+c")
			voz = panel.getControl("voz")
			intervalo.SetSelection(5)
			teclas.SetValue("control+c, control+insert")
			voz.SetValue(False)
			panel.onSave()
			self.assertEqual(conf[opciones.SECCION]["intervalo"], 1000)
			self.assertEqual(list(conf[opciones.SECCION]["teclasCopiar"]), ["control+c", "control+insert"])
			self.assertFalse(conf[opciones.SECCION]["voz"])
			# Al guardar se aplican las teclas nuevas.
			self.assertEqual(self.plugin._teclas.get("kb:control+insert"), "copy")
			panel.resetToFactory()
			panel.onSave()
			self.assertEqual(list(conf[opciones.SECCION]["teclasCopiar"]), ["control+c"])
			self.assertIsNone(self.plugin._teclas.get("kb:control+insert"))
		finally:
			frame.Destroy()

	def test_menu_herramientas(self):
		from tiresias import gui

		self.assertIn(tca.MENU_ID, gui._addonToolsEntries)
		label, action, submenu = gui._addonToolsEntries[tca.MENU_ID]
		self.assertEqual(label, "&TCA-Portapapeles")
		self.assertTrue(submenu)
		self.assertEqual([e[0] for e in action()], ["&Historial de TCA-Portapapeles...", "Desactivar los &anuncios", "Activar el &modo juego"])
		with mock.patch.object(self.plugin, "script_activarDesactivar") as orden:
			# Se ejecuta en el núcleo (en las pruebas, directamente).
			dict(action())["Desactivar los &anuncios"]()
		orden.assert_called_once_with(None)
		self.plugin.terminate()
		self.assertNotIn(tca.MENU_ID, gui._addonToolsEntries)

	# ---------------------------------------------------------------- gestos
	def test_gestos_directos(self):
		self.assertEqual(dict(tca.GlobalPlugin._classGestures), {"kb:tiresias+control+shift+v": "capa"})

	def test_descripcion_y_categoria(self):
		names = [n for n in dir(tca.GlobalPlugin) if n.startswith("script_")]
		self.assertEqual(sorted(names), sorted("script_" + n for n in ["capa", *tca.GESTOS_CAPA.values()]))
		for n in names:
			func = getattr(tca.GlobalPlugin, n)
			self.assertTrue(func.__doc__, n)
			self.assertEqual(func.category, "TCA-Portapapeles", n)
		for n in ("leerPortapapeles", "estadisticasSeleccion", "ayudaCapa"):
			self.assertTrue(getattr(tca.GlobalPlugin, "script_" + n).speakOnDemand, n)

	def test_gestos_sin_conflictos(self):
		mine = [normalizeGestureId(g) for g in tca.GlobalPlugin._classGestures]
		pattern = re.compile(r"kb(?:\([a-z]+\))?:[A-Za-z0-9+]+")
		used = set()
		bases = [os.path.join(ROOT, "src", "tiresias"), os.path.join(ROOT, "data", "addons"), os.path.join(ROOT, "complementos_tienda")]
		for base in bases:
			for dirpath, _dirs, files in os.walk(base):
				if os.path.normpath(dirpath).startswith(os.path.normpath(ADDON)):
					continue
				for fn in files:
					if fn.endswith(".py"):
						with open(os.path.join(dirpath, fn), encoding="utf-8", errors="replace") as f:
							for m in pattern.findall(f.read()):
								used.add(normalizeGestureId("kb:" + m.split(":", 1)[1]))
		for g in mine:
			self.assertNotIn(g, used, g)

	def test_capa(self):
		p = self.plugin
		self.assertIsNone(p.getScript(FakeGesture("h")))
		with mock.patch("tiresias.audio.tones.beep") as beep:
			p.script_capa(None)
		beep.assert_called_once_with(100, 10)
		self.assertTrue(p.capaActiva)
		for gid, name in tca.GESTOS_CAPA.items():
			g = FakeGesture(gid.split(":", 1)[1])
			self.assertTrue(p._decidir(g))
			self.assertTrue(p.capaActiva, gid)
			self.assertEqual(p.getScript(g).__name__, "script_" + name, gid)
		p._decidir(FakeGesture("tiresias+control+shift+v"))
		self.assertTrue(p.capaActiva)
		self.assertTrue(p._decidir(FakeGesture("x")))
		self.assertFalse(p.capaActiva)
		self.assertIsNone(p.getScript(FakeGesture("h")))
		with mock.patch("tiresias.audio.tones.beep"):
			p.script_capa(None)
		with mock.patch("tiresias.audio.tones.beep") as beep:
			p.getScript(FakeGesture("escape"))(None)
		beep.assert_called_once_with(120, 100)
		self.assertFalse(p.capaActiva)

	def test_ayuda_capa(self):
		with mock.patch(SPEAK) as speak:
			self.plugin.script_ayudaCapa(None)
		msg = speak.call_args[0][0]
		for parte in ("H: historial", "L: leer el portapapeles", "E: estadísticas", "P: copiar parte", "A: activar", "J: modo juego", "Escape: salir"):
			self.assertIn(parte, msg)

	def test_decisor_registrado(self):
		self.assertIn(self.plugin._decidir, inputCore.decide_executeGesture.handlers())
		self.plugin.terminate()
		self.assertNotIn(self.plugin._decidir, inputCore.decide_executeGesture.handlers())

	def test_modo_seguro(self):
		from tiresias.gui import settings as S

		self.plugin.terminate()
		with mock.patch.object(tca, "isSecureMode", return_value=True):
			p = tca.GlobalPlugin()
		try:
			self.assertNotIn(p._decidir, inputCore.decide_executeGesture.handlers())
			self.assertNotIn(opciones.PANEL_ID, S._panels)
			self.assertIsNone(p.getScript(FakeGesture("tiresias+control+shift+v")))
		finally:
			p.terminate()

	# ---------------------------------------------------------------- observación de teclas
	def _decidir(self, keys: str, vk: int = 0):
		with mock.patch("tiresias.queue_handler.queueFunction") as q, mock.patch.object(portapapeles, "secuencia", return_value=41):
			self.assertTrue(self.plugin._decidir(FakeGesture(keys, vk)))
		return q

	def test_decidir_encola_y_deja_pasar(self):
		casos = {"control+a": "selectAll", "control+e": "selectAll", "control+c": "copy", "control+x": "cut", "control+v": "paste", "control+z": "undo", "control+y": "redo"}
		vks = {"control+c": 0x43, "control+x": 0x58, "control+v": 0x56}
		for keys, accion in casos.items():
			q = self._decidir(keys, vks.get(keys, 0))
			q.assert_called_once_with(self.plugin._alPulsar, accion, 41, keys in vks)
		for keys in ("c", "control+shift+c", "control+b", "tiresias+control+c"):
			self._decidir(keys).assert_not_called()

	def test_decidir_desactivado_juego_y_ayuda(self):
		self.plugin._activo = False
		self._decidir("control+c", 0x43).assert_not_called()
		self.plugin._activo = True
		self.plugin._juego = True
		self._decidir("control+c", 0x43).assert_not_called()
		self.plugin._juego = False
		with mock.patch.object(inputCore.manager, "inputHelp", True):
			self._decidir("control+c", 0x43).assert_not_called()

	def test_teclas_configurables(self):
		conf[opciones.SECCION]["teclasPegar"] = ["control+v", "shift+insert"]
		conf[opciones.SECCION]["teclasSeleccionarTodo"] = ["control+a"]
		self.plugin.aplicarOpciones()
		self._decidir("shift+insert").assert_called_once()
		self._decidir("control+e").assert_not_called()

	def _pulsar(self, accion, seqAntes=1, delNucleo=False, seqDespues=None, nucleoCopia=False, nucleoPegado=False, consola=False):
		with mock.patch(SPEAK) as speak, mock.patch("tiresias.audio.tones.playWaveFile") as play, \
				mock.patch.object(portapapeles, "secuencia", return_value=seqAntes if seqDespues is None else seqDespues), \
				mock.patch.object(tca, "nucleoAnunciaCopia", return_value=nucleoCopia), \
				mock.patch.object(tca, "nucleoAnunciaPegado", return_value=nucleoPegado), \
				mock.patch.object(tca, "focoEnConsola", return_value=consola), \
				mock.patch.object(tca, "focoDormido", return_value=False), \
				mock.patch.object(tca, "ESPERA_COPIA", 0), \
				mock.patch("tiresias.queue_handler.callLater") as later:
			self.plugin._alPulsar(accion, seqAntes, delNucleo)
		return [c[0][0] for c in speak.call_args_list], [os.path.basename(c[0][0]) for c in play.call_args_list], later

	def test_anuncios_directos(self):
		for accion, msg, wav in (("selectAll", "Seleccionar todo", "todo.wav"), ("undo", "Deshacer", "deshacer.wav"), ("redo", "Rehacer", "rehacer.wav"), ("paste", "Pegar", "pegar.wav")):
			speak, play, _later = self._pulsar(accion)
			self.assertEqual(speak, [msg], accion)
			self.assertEqual(play, [wav], accion)

	def test_pegar_si_tiresias_ya_lo_anuncia(self):
		speak, play, _l = self._pulsar("paste", delNucleo=True, nucleoPegado=True)
		self.assertEqual((speak, play), ([], ["pegar.wav"]))
		# Con otra tecla (no la de Tiresias) se dice siempre.
		speak, play, _l = self._pulsar("paste", delNucleo=False, nucleoPegado=True)
		self.assertEqual(speak, ["Pegar"])

	def test_copiar_cambia_el_portapapeles(self):
		for accion, msg, wav in (("copy", "Copiar", "copiar.wav"), ("cut", "Cortar", "cortar.wav")):
			speak, play, _l = self._pulsar(accion, seqAntes=1, seqDespues=2)
			self.assertEqual((speak, play), ([msg], [wav]), accion)
			speak, play, _l = self._pulsar(accion, seqAntes=1, seqDespues=2, delNucleo=True, nucleoCopia=True)
			self.assertEqual((speak, play), ([], [wav]), accion)

	def test_copiar_sin_seleccion(self):
		speak, play, later = self._pulsar("copy", seqAntes=5)
		self.assertEqual((speak, play), (["Sin selección"], []))
		later.assert_not_called()
		speak, play, _l = self._pulsar("cut", seqAntes=5, consola=True)
		self.assertEqual((speak, play), ([], []))
		conf[opciones.SECCION]["voz"] = False
		speak, _p, _l = self._pulsar("copy", seqAntes=5)
		self.assertEqual(speak, [])

	def test_copiar_espera_al_portapapeles(self):
		with mock.patch("tiresias.queue_handler.callLater") as later, mock.patch.object(portapapeles, "secuencia", return_value=1), \
				mock.patch.object(tca, "focoDormido", return_value=False), mock.patch(SPEAK) as speak:
			self.plugin._alPulsar("copy", 1, True)
		speak.assert_not_called()
		later.assert_called_once()
		self.assertEqual(later.call_args[0][0], tca.PASO_COPIA)
		self.assertEqual(later.call_args[0][1], self.plugin._comprobarCopia)

	def test_voz_y_sonido_por_separado(self):
		conf[opciones.SECCION]["audio"] = False
		speak, play, _l = self._pulsar("undo")
		self.assertEqual((speak, play), (["Deshacer"], []))
		conf[opciones.SECCION]["audio"] = True
		conf[opciones.SECCION]["voz"] = False
		speak, play, _l = self._pulsar("undo")
		self.assertEqual((speak, play), ([], ["deshacer.wav"]))

	def test_nada_en_modo_dormir_o_desactivado(self):
		with mock.patch.object(tca, "focoDormido", return_value=True), mock.patch(SPEAK) as speak:
			self.plugin._alPulsar("undo", 1, False)
		speak.assert_not_called()
		self.plugin._activo = False
		with mock.patch.object(tca, "focoDormido", return_value=False), mock.patch(SPEAK) as speak:
			self.plugin._alPulsar("undo", 1, False)
		speak.assert_not_called()

	def test_nucleo_anuncia(self):
		cb = conf["clipboard"]
		old = {k: cb[k] for k in ("announceCopy", "announceCutCopyPaste", "announcePastedText")}
		try:
			cb["announceCopy"], cb["announceCutCopyPaste"], cb["announcePastedText"] = True, True, False
			self.assertTrue(tca.nucleoAnunciaCopia())
			with mock.patch("tiresias.clipboard.focusIsEditable", return_value=True):
				self.assertTrue(tca.nucleoAnunciaPegado())
			with mock.patch("tiresias.clipboard.focusIsEditable", return_value=False):
				self.assertFalse(tca.nucleoAnunciaPegado())
			cb["announceCopy"] = False
			self.assertFalse(tca.nucleoAnunciaCopia())
			cb["announceCopy"], cb["announceCutCopyPaste"] = True, False
			with mock.patch.object(portapapeles, "hayTexto", return_value=True), mock.patch("tiresias.clipboard.isSensitiveContent", return_value=False):
				self.assertTrue(tca.nucleoAnunciaCopia())
			with mock.patch.object(portapapeles, "hayTexto", return_value=False):
				self.assertFalse(tca.nucleoAnunciaCopia())
				with mock.patch("tiresias.clipboard.focusIsEditable", return_value=True):
					self.assertFalse(tca.nucleoAnunciaPegado())
		finally:
			for k, v in old.items():
				cb[k] = v

	def test_tecla_del_nucleo(self):
		self.assertTrue(tca.teclaDelNucleo(FakeGesture("control+c", 0x43), "copy"))
		self.assertTrue(tca.teclaDelNucleo(FakeGesture("shift+insert", 0x2D), "paste"))
		self.assertFalse(tca.teclaDelNucleo(FakeGesture("control+e", 0x45), "copy"))

	def test_activar_desactivar(self):
		with mock.patch(SPEAK) as speak, mock.patch("tiresias.audio.tones.beep") as beep:
			self.plugin.script_activarDesactivar(None)
		self.assertFalse(self.plugin.anunciosActivos)
		self.assertFalse(conf[opciones.SECCION]["activado"])
		self.assertEqual(speak.call_args[0][0], "TCA-Portapapeles desactivado")
		beep.assert_called_once_with(100, 150)
		with mock.patch(SPEAK) as speak, mock.patch("tiresias.audio.tones.beep") as beep:
			self.plugin.script_activarDesactivar(None)
		self.assertTrue(self.plugin.anunciosActivos)
		self.assertEqual(speak.call_args[0][0], "TCA-Portapapeles activado")
		beep.assert_called_once_with(400, 150)

	# ---------------------------------------------------------------- historial
	def test_cambio_del_portapapeles_al_historial(self):
		el = _elemento("copiado", {13: b"x"})
		with mock.patch("tiresias.clipboard.isSensitiveContent", return_value=False), mock.patch.object(portapapeles, "leerTodo", return_value=el), \
				mock.patch("tiresias.audio.tones.playWaveFile") as play, mock.patch(SPEAK_TEXT) as speakText:
			self.plugin._alCambiarHistorial()
			self.plugin._alCambiarHistorial()
		self.assertEqual([e.texto for e in self.plugin.historial.elementos], ["copiado"])
		self.assertEqual([os.path.basename(c[0][0]) for c in play.call_args_list], ["historial.wav"])
		speakText.assert_not_called()
		conf[opciones.SECCION]["vozCopiado"] = True
		with mock.patch("tiresias.audio.tones.playWaveFile"), mock.patch(SPEAK_TEXT) as speakText:
			self.plugin.agregarAlHistorial(_elemento("otro"))
		speakText.assert_called_once_with("otro")

	def test_contenido_protegido_no_se_guarda(self):
		with mock.patch("tiresias.clipboard.isSensitiveContent", return_value=True), mock.patch.object(portapapeles, "leerTodo") as leer:
			self.plugin._alCambiarHistorial()
		leer.assert_not_called()
		self.assertEqual(len(self.plugin.historial), 0)

	def test_abrir_historial_mensajes(self):
		with mock.patch(SPEAK) as speak, mock.patch.object(dialogos, "mostrarHistorial") as mostrar:
			self.plugin.script_mostrarHistorial(None)
			self.assertEqual(speak.call_args[0][0], tca.MSG_HISTORIAL_VACIO)
			self.plugin.historial.agregar(_elemento("a"))
			conf[opciones.SECCION]["historial"] = False
			self.plugin.script_mostrarHistorial(None)
			self.assertEqual(speak.call_args[0][0], tca.MSG_HISTORIAL_DESACTIVADO)
			conf[opciones.SECCION]["historial"] = True
			self.plugin._juego = True
			self.plugin.script_mostrarHistorial(None)
			self.assertEqual(speak.call_args[0][0], tca.MSG_JUEGO_ACTIVO)
			self.plugin._juego = False
			with mock.patch.object(dialogos, "hayVentana", return_value=True):
				self.plugin.script_mostrarHistorial(None)
			self.assertEqual(speak.call_args[0][0], tca.MSG_DOS_VENTANAS)
			mostrar.assert_not_called()
			with mock.patch.object(tca, "isSecureContext", return_value=False):
				self.plugin.script_mostrarHistorial(None)
		mostrar.assert_called_once_with(self.plugin)

	def test_pegar_en_el_foco(self):
		el = _elemento("del historial", {13: b"x"})
		copia = _elemento("lo que había", {13: b"y"})
		vig = mock.Mock()
		self.plugin._vigilante = vig
		orden = []
		pendientes = []
		with mock.patch.object(portapapeles, "leerTodo", return_value=copia), \
				mock.patch.object(portapapeles, "escribirTodo", side_effect=lambda e: orden.append(("escribir", e.texto)) or True), \
				mock.patch("tiresias.clipboard.ignoreNextChange", side_effect=lambda: orden.append(("ignorar",))), \
				mock.patch("tiresias.winapi.getForegroundWindow", return_value=1234), \
				mock.patch("tiresias.winapi.getClassName", return_value="Notepad"), \
				mock.patch("tiresias.input.gestures.sendKey", side_effect=lambda k: orden.append(("tecla", k))), \
				mock.patch.object(tca, "isSecureContext", return_value=False), \
				mock.patch("tiresias.queue_handler.callLater", side_effect=lambda ms, f, *a: pendientes.append((ms, f, a))), \
				mock.patch(SPEAK) as speak:
			self.plugin.pegarElemento(el)
			vig.pausar.assert_called_once()
			self.assertEqual(orden, [("ignorar",), ("escribir", "del historial"), ("tecla", "control+v")])
			speak.assert_called_once_with(tca.MSG_PEGADO)
			ms, f, a = pendientes.pop(0)
			self.assertEqual(ms, tca.RETRASO_RESTAURAR)
			f(*a)
			self.assertEqual(orden[-2:], [("ignorar",), ("escribir", "lo que había")])
			vig.reanudar.assert_not_called()
			ms, f, a = pendientes.pop(0)
			f(*a)
		vig.reanudar.assert_called_once()
		self.plugin._vigilante = None

	def test_pegar_en_consola_clasica(self):
		with mock.patch.object(portapapeles, "leerTodo", return_value=None), mock.patch.object(portapapeles, "escribirTodo", return_value=True), \
				mock.patch("tiresias.clipboard.ignoreNextChange"), mock.patch("tiresias.winapi.getForegroundWindow", return_value=77), \
				mock.patch("tiresias.winapi.getClassName", return_value="ConsoleWindowClass"), \
				mock.patch("tiresias.winapi.user32.SendMessageTimeoutW") as send, mock.patch("tiresias.input.gestures.sendKey") as key, \
				mock.patch.object(tca, "isSecureContext", return_value=False), mock.patch("tiresias.queue_handler.callLater"):
			self.plugin.pegarElemento(_elemento("dir"))
		send.assert_called_once_with(77, 0x0111, 0xFFF1, 0, 0x0002, 2000, None)
		key.assert_not_called()

	def test_pegar_falla(self):
		vig = mock.Mock()
		self.plugin._vigilante = vig
		with mock.patch.object(portapapeles, "leerTodo", return_value=None), mock.patch.object(portapapeles, "escribirTodo", return_value=False), \
				mock.patch("tiresias.clipboard.ignoreNextChange"), mock.patch("tiresias.clipboard.cancelIgnore") as cancel, \
				mock.patch("tiresias.input.gestures.sendKey") as key, mock.patch.object(tca, "isSecureContext", return_value=False), mock.patch(SPEAK) as speak:
			self.plugin.pegarElemento(_elemento("x"))
		cancel.assert_called_once()
		key.assert_not_called()
		speak.assert_called_once_with(tca.MSG_NO_PEGADO)
		vig.reanudar.assert_called_once()
		self.plugin._vigilante = None

	# ---------------------------------------------------------------- otras órdenes
	def test_leer_portapapeles(self):
		with mock.patch("tiresias.clipboard.isSensitiveContent", return_value=False), mock.patch.object(portapapeles, "leerTextoOArchivos", return_value="x" * 5000), \
				mock.patch(SPEAK_TEXT) as speakText:
			self.plugin.script_leerPortapapeles(None)
		speakText.assert_called_once_with("x" * 5000)
		with mock.patch("tiresias.clipboard.isSensitiveContent", return_value=False), mock.patch.object(portapapeles, "leerTextoOArchivos", return_value=None), \
				mock.patch(SPEAK) as speak:
			self.plugin.script_leerPortapapeles(None)
		speak.assert_called_once_with(tca.MSG_SIN_TEXTO)
		with mock.patch("tiresias.clipboard.isSensitiveContent", return_value=True), mock.patch.object(portapapeles, "leerTextoOArchivos") as leer, \
				mock.patch(SPEAK) as speak:
			self.plugin.script_leerPortapapeles(None)
		leer.assert_not_called()
		speak.assert_called_once_with(tca.MSG_PROTEGIDO)

	def test_estadisticas(self):
		with mock.patch.object(tca, "textoSeleccionado", return_value="Dos palabras"), mock.patch(SPEAK) as speak:
			self.plugin.script_estadisticasSeleccion(None)
		self.assertEqual(speak.call_args[0][0], "11 caracteres (sin espacios).\n12 caracteres (con espacios).\n2 palabras.\n1 línea.\n1 párrafo.")
		with mock.patch.object(tca, "textoSeleccionado", return_value=None), mock.patch(SPEAK) as speak:
			self.plugin.script_estadisticasSeleccion(None)
		speak.assert_called_once_with("Sin selección")

	def test_texto_seleccionado(self):
		info = mock.Mock(isCollapsed=False, text="hola")
		obj = mock.Mock()
		obj.makeTextInfo.return_value = info
		with mock.patch("tiresias.api.getCaretObject", return_value=obj):
			self.assertEqual(tca.textoSeleccionado(), "hola")
			info.isCollapsed = True
			self.assertIsNone(tca.textoSeleccionado())
			obj.makeTextInfo.side_effect = NotImplementedError
			self.assertIsNone(tca.textoSeleccionado())

	def test_copiar_parte(self):
		with mock.patch.object(dialogos, "mostrarPartes") as mostrar, mock.patch(SPEAK) as speak, mock.patch.object(tca, "isSecureContext", return_value=False):
			with mock.patch.object(tca, "textoSeleccionado", return_value=None):
				self.plugin.script_copiarParteSeleccion(None)
			self.assertEqual(speak.call_args[0][0], "Sin selección")
			with mock.patch.object(tca, "textoSeleccionado", return_value="¡Hola!"):
				self.plugin.script_copiarParteSeleccion(None)
			self.assertEqual(speak.call_args[0][0], tca.MSG_UN_ELEMENTO)
			with mock.patch.object(tca, "textoSeleccionado", return_value="..."):
				self.plugin.script_copiarParteSeleccion(None)
			self.assertEqual(speak.call_args[0][0], "Sin selección")
			mostrar.assert_not_called()
			with mock.patch.object(tca, "textoSeleccionado", return_value="Hola, mundo"):
				self.plugin.script_copiarParteSeleccion(None)
			mostrar.assert_called_once_with(self.plugin, "Hola, mundo")

	def test_copiar_texto(self):
		with mock.patch("tiresias.api.copyToClip", return_value=True) as copy, mock.patch.object(tca, "isSecureContext", return_value=False):
			self.assertTrue(self.plugin.copiarTexto("Hola perro"))
		copy.assert_called_once_with("Hola perro", notify=True)
		with mock.patch("tiresias.api.copyToClip") as copy, mock.patch.object(tca, "isSecureContext", return_value=True), mock.patch(SPEAK):
			self.assertFalse(self.plugin.copiarTexto("x"))
		copy.assert_not_called()

	# ---------------------------------------------------------------- modo juego
	def test_modo_juego(self):
		with mock.patch(SPEAK) as speak, mock.patch("tiresias.audio.tones.beep") as beep:
			self.plugin.script_modoJuego(None)
		self.assertTrue(self.plugin.modoJuegoActivo)
		self.assertTrue(conf[opciones.SECCION]["modoJuego"])
		self.assertEqual(speak.call_args[0][0], "Modo juego de TCA-Portapapeles activado")
		beep.assert_called_once_with(400, 150)
		# Las demás órdenes quedan bloqueadas.
		with mock.patch(SPEAK) as speak:
			for orden in (self.plugin.script_activarDesactivar, self.plugin.script_copiarParteSeleccion, self.plugin.script_mostrarHistorial):
				orden(None)
				self.assertEqual(speak.call_args[0][0], tca.MSG_JUEGO_ACTIVO)
		self.assertTrue(self.plugin.anunciosActivos)
		with mock.patch(SPEAK) as speak, mock.patch("tiresias.audio.tones.beep") as beep:
			self.plugin.script_modoJuego(None)
		self.assertFalse(self.plugin.modoJuegoActivo)
		self.assertEqual(speak.call_args[0][0], "Modo juego de TCA-Portapapeles desactivado")
		beep.assert_called_once_with(100, 150)

	def test_modo_juego_con_ventana_abierta(self):
		with mock.patch.object(dialogos, "hayVentana", return_value=True), mock.patch(SPEAK) as speak:
			self.plugin.script_modoJuego(None)
		self.assertFalse(self.plugin.modoJuegoActivo)
		speak.assert_called_once_with(tca.MSG_VENTANA_JUEGO)

	def test_modo_juego_pausa_el_historial(self):
		vig = mock.Mock()
		self.plugin._vigilante = vig
		with mock.patch(SPEAK), mock.patch("tiresias.audio.tones.beep"):
			self.plugin.script_modoJuego(None)
			vig.pausar.assert_called_once()
			self.plugin.script_modoJuego(None)
		vig.reanudar.assert_called_once()
		self.plugin._vigilante = None

	def test_modo_juego_traduce(self):
		with mock.patch(SPEAK), mock.patch("tiresias.audio.tones.beep"):
			self.plugin.script_modoJuego(None)
		conf[opciones.SECCION]["idiomaJuego"] = "fr"
		with mock.patch.object(juego, "_abrir", return_value=_Respuesta({"sentences": [{"trans": "Bonjour"}]})) as abrir, mock.patch(SPEAK_TEXT) as speakText:
			self.assertTrue(self.plugin.textoDelJuego("Hola"))
			self.assertFalse(self.plugin.textoDelJuego("Hola"))
			self.assertFalse(self.plugin.textoDelJuego("echo off"))
			self.assertFalse(self.plugin.textoDelJuego("  "))
		abrir.assert_called_once()
		self.assertIn("tl=fr", abrir.call_args[0][0].full_url)
		speakText.assert_called_once_with("Bonjour")
		with mock.patch.object(juego, "_abrir", side_effect=OSError("sin red")), mock.patch(SPEAK) as speak, mock.patch(SPEAK_TEXT) as speakText:
			self.plugin.textoDelJuego("Uno")
			self.plugin.textoDelJuego("Dos")
		speak.assert_called_once_with(tca.MSG_NO_TRADUCIDO)
		self.assertEqual([c[0][0] for c in speakText.call_args_list], ["Uno", "Dos"])

	def test_modo_juego_lee_del_portapapeles(self):
		with mock.patch(SPEAK), mock.patch("tiresias.audio.tones.beep"):
			self.plugin.script_modoJuego(None)
		with mock.patch("tiresias.clipboard.isSensitiveContent", return_value=False), mock.patch.object(portapapeles, "leerTextoOArchivos", return_value="Hello"), \
				mock.patch.object(self.plugin, "textoDelJuego") as td:
			self.plugin._alCambiarJuego()
		td.assert_called_once_with("Hello")
		with mock.patch("tiresias.clipboard.isSensitiveContent", return_value=True), mock.patch.object(self.plugin, "textoDelJuego") as td:
			self.plugin._alCambiarJuego()
		td.assert_not_called()

	def test_modo_juego_recordado(self):
		self.plugin.terminate()
		conf[opciones.SECCION]["modoJuego"] = True
		self.plugin = tca.GlobalPlugin()
		self.plugin.enHilo = False
		self.assertTrue(self.plugin.modoJuegoActivo)
		self._decidir("control+c", 0x43).assert_not_called()

	def test_hilos_reales(self):
		# Con la vigilancia activada se arrancan y se paran los hilos (portapapeles simulado).
		self.plugin.terminate()
		tca.GlobalPlugin.vigilar = True
		try:
			with mock.patch.object(portapapeles, "secuencia", return_value=10):
				p = tca.GlobalPlugin()
				try:
					self.assertTrue(p._vigilante.is_alive())
					with mock.patch(SPEAK), mock.patch("tiresias.audio.tones.beep"):
						p.script_modoJuego(None)
					self.assertTrue(p._vigilanteJuego.is_alive())
					self.assertTrue(p._traductor.is_alive())
					self.assertTrue(p._vigilante.pausado)
					vig, vigJ, trad = p._vigilante, p._vigilanteJuego, p._traductor
				finally:
					p.terminate()
			for hilo in (vig, vigJ, trad):
				hilo.join(2)
				self.assertFalse(hilo.is_alive())
		finally:
			tca.GlobalPlugin.vigilar = False
			_resetConf()
		self.plugin = tca.GlobalPlugin()


# ====================================================================== ventanas
class TestDialogos(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		import wx

		cls.app = wx.App.Get() or wx.App(False)

	def setUp(self):
		_resetConf()
		tca.GlobalPlugin.vigilar = False
		self.plugin = tca.GlobalPlugin()
		self.plugin.enHilo = False

	def tearDown(self):
		self.plugin.terminate()
		dialogos._ventana = None

	def test_prevista(self):
		self.assertEqual(dialogos.prevista("a\n  b\tc"), "a b c")
		largo = dialogos.prevista("x" * 500)
		self.assertEqual(len(largo), dialogos.PREVISTA + 1)
		self.assertTrue(largo.endswith("…"))

	def test_historial(self):
		import wx

		for t in ("uno", "dos\nlíneas", "tres"):
			self.plugin.historial.agregar(_elemento(t))
		d = dialogos.HistorialDialogo(self.plugin)
		try:
			self.assertEqual(d.GetTitle(), "Historial de TCA-Portapapeles")
			self.assertEqual(list(d.lista.GetItems()), ["tres", "dos líneas", "uno"])
			self.assertEqual(d.lista.GetSelection(), 0)
			labels = [b.GetLabel() for b in d.GetChildren() if isinstance(b, wx.Button)]
			self.assertEqual(labels, ["&Pegar en el foco", "&Borrar", "Borrar &todo", "&Refrescar", "&Cerrar"])
			d.lista.SetSelection(1)
			d.borrar()
			self.assertEqual(list(d.lista.GetItems()), ["tres", "uno"])
			self.assertEqual(d.lista.GetSelection(), 1)
			self.plugin.historial.agregar(_elemento("cuatro"))
			d.refrescar()
			self.assertEqual(list(d.lista.GetItems()), ["cuatro", "tres", "uno"])
			with mock.patch("tiresias.gui.message_dialog.messageBox", return_value=wx.NO):
				d.borrarTodo()
			self.assertEqual(len(self.plugin.historial), 3)
			d.lista.SetSelection(2)
			with mock.patch.object(self.plugin, "pegarElemento") as pegar:
				d.pegar()
			self.assertEqual(pegar.call_args[0][0].texto, "uno")
		finally:
			if dialogos.isAlive(d):
				d.Destroy()

	def test_historial_borrar_todo_cierra(self):
		import wx

		self.plugin.historial.agregar(_elemento("uno"))
		d = dialogos.HistorialDialogo(self.plugin)
		with mock.patch("tiresias.gui.message_dialog.messageBox", return_value=wx.YES):
			d.borrarTodo()
		self.assertEqual(len(self.plugin.historial), 0)
		wx.SafeYield()
		self.assertFalse(dialogos.isAlive(d) and d.IsShown())

	def test_partes(self):
		import wx

		d = dialogos.PartesDialogo(self.plugin, "Hola, como estás, el perro tiene hambre")
		try:
			self.assertEqual(d.GetTitle(), "Selector de trozos de texto para copiar al portapapeles")
			self.assertEqual(list(d.lista.GetItems()), ["Hola", "como", "estás", "el", "perro", "tiene", "hambre"])
			with mock.patch("tiresias.gui.message_dialog.messageBox") as box:
				d.copiar()
			self.assertEqual(box.call_args[0][0], dialogos.MSG_NINGUNA)
			d.signos.SetValue(True)
			d.cambiarSignos()
			self.assertEqual(list(d.lista.GetItems())[:3], ["Hola,", "como", "estás,"])
			d.signos.SetValue(False)
			d.cambiarSignos()
			for i in (6, 0, 4):
				d.lista.Check(i)
			with mock.patch.object(self.plugin, "copiarTexto") as copiar:
				d.copiar()
			copiar.assert_called_once_with("Hola perro hambre")
		finally:
			if dialogos.isAlive(d):
				d.Destroy()

	def test_una_sola_ventana(self):
		import wx

		self.plugin.historial.agregar(_elemento("uno"))
		with mock.patch.object(dialogos, "bringToFront"):
			dialogos._mostrar(lambda: dialogos.HistorialDialogo(self.plugin))
			primera = dialogos.ventanaAbierta()
			self.assertIsInstance(primera, dialogos.HistorialDialogo)
			self.assertTrue(dialogos.hayVentana())
			dialogos._mostrar(lambda: dialogos.PartesDialogo(self.plugin, "a b"))
			self.assertIs(dialogos.ventanaAbierta(), primera)
		with mock.patch(SPEAK) as speak:
			self.plugin.script_copiarParteSeleccion(None)
		speak.assert_called_once_with(tca.MSG_DOS_VENTANAS)
		primera.Close()
		wx.SafeYield()
		self.assertFalse(dialogos.hayVentana())


if __name__ == "__main__":
	unittest.main()
