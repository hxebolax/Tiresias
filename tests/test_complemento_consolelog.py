"""Pruebas del complemento «Visor de consola» (complementos_tienda/consoleLog).

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_complemento_consolelog -v``

Sin ganchos ni sonido: los pitidos, el portapapeles, la voz y la red se
sustituyen por dobles de prueba. Las ventanas wx se construyen sin mostrarse.
"""

from __future__ import annotations

import base64
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
ADDON = os.path.join(ROOT, "complementos_tienda", "consoleLog")
sys.path.insert(0, os.path.join(ADDON, "globalPlugins"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_consolelog_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]
else:
	_TMP = paths._dataDirForTests  # type: ignore[attr-defined]

from tiresias.config import conf  # noqa: E402

_oldBytecode = sys.dont_write_bytecode
sys.dont_write_bytecode = True  # No deja __pycache__ en la carpeta del complemento.
import consoleLog as cl  # noqa: E402
from consoleLog import avisos, deteccion, ia, lanzador, lectores, markdown_html, protector_rafagas, seguimiento  # noqa: E402
from consoleLog import configuracion as cfg  # noqa: E402
from consoleLog import definiciones_ventana as dv  # noqa: E402
from consoleLog import procesador_texto as pt  # noqa: E402
from consoleLog.herramientas import GestorHerramientas, HerramientaBase, nombre_categoria  # noqa: E402
from consoleLog.registro_visores import RegistroVisores  # noqa: E402

# Se restablece en tearDownModule: las importaciones perezosas tampoco dejan __pycache__.
cfg.registrarValores()

_parches: list = []
HABLADO: list[str] = []
PORTAPAPELES: list[str] = []


def setUpModule() -> None:
	from tiresias import api
	from tiresias.audio import tones
	from tiresias.speech import api as speechApi

	def copiar(texto, notify=False):
		PORTAPAPELES.append(texto)
		return True

	_parches.extend(
		[
			mock.patch.object(tones, "beep", lambda *a, **k: None),
			mock.patch.object(tones, "playSound", lambda *a, **k: None),
			mock.patch.object(avisos, "sonidoAlerta", lambda: HABLADO.append("<sonido alerta>")),
			mock.patch.object(api, "copyToClip", copiar),
			mock.patch.object(speechApi, "speakMessage", lambda texto, *a, **k: HABLADO.append(texto)),
		]
	)
	for p in _parches:
		p.start()


def tearDownModule() -> None:
	for p in reversed(_parches):
		p.stop()
	sys.dont_write_bytecode = _oldBytecode


class _Opciones:
	"""Cambia opciones del complemento durante una prueba y las restablece."""

	def __init__(self, **valores) -> None:
		self.valores = valores
		self.viejos: dict = {}

	def __enter__(self):
		for k, v in self.valores.items():
			self.viejos[k] = conf[cfg.SECCION][k]
			conf[cfg.SECCION][k] = v
		return self

	def __exit__(self, *exc):
		for k, v in self.viejos.items():
			conf[cfg.SECCION][k] = v


# ====================================================================== paquete
class TestPaquete(unittest.TestCase):
	def test_manifiesto(self):
		with open(os.path.join(ADDON, "manifest.json"), encoding="utf-8-sig") as f:
			m = json.load(f)
		self.assertEqual(m["id"], "consoleLog")
		self.assertEqual(m["version"], "1.0.0")
		self.assertEqual(m["author"], "Héctor J. Benítez Corredera <xebolax@gmail.com>")
		self.assertEqual(m["url"], "https://github.com/nvda-es/consoleLog")
		self.assertTrue(m["changelog"].startswith("Primera versión para Tiresias"))
		self.assertEqual((m["minApiVersion"], m["lastTestedApiVersion"]), ("1.0", "1.0"))
		self.assertGreater(len(m["description"]), 300)

	def test_archivos(self):
		for rel in ("doc/es/readme.html", "LICENCIAS_TERCEROS.txt", "globalPlugins/consoleLog/__init__.py"):
			self.assertTrue(os.path.isfile(os.path.join(ADDON, rel)), rel)

	def test_sin_bibliotecas_de_terceros(self):
		prohibidos = ("import requests", "import httpx", "wcwidth", "from bidi", "arabic_reshaper", "import emoji", "winsound", "globalPluginHandler", "addonHandler")
		for carpeta, _dirs, archivos in os.walk(os.path.join(ADDON, "globalPlugins")):
			for a in archivos:
				if a.endswith(".py"):
					with open(os.path.join(carpeta, a), encoding="utf-8") as f:
						codigo = f.read()
					for p in prohibidos:
						self.assertNotIn(p, codigo, "{} en {}".format(p, a))

	def test_readme_documenta_todo(self):
		with open(os.path.join(ADDON, "doc", "es", "readme.html"), encoding="utf-8") as f:
			doc = f.read()
		for texto in (
			"Muestra el visor de consola",
			"Copia el contenido completo de la consola al portapapeles",
			"Pega el contenido del portapapeles mediante clic derecho",
			"Abre el lanzador de consolas",
			"Control+F", "F3", "Control+G", "Control+S", "Control+P", "F1", "F2", "F5", "Control+Mayúsculas+F", "Escape",
			"Seguimiento automático", "Conservar", "Límite del visor", "ráfagas", "Alertas", "Definiciones de ventana",
			"Lanzador", "Google AI", "Generador de informe IA", "F6", "Control+Intro",
			"Calculadora Express", "Decodificador JWT", "Embellecedor de JSON", "Formateador SQL", "Base64",
			"marcas de tiempo", "StackTrace", "indentación", "ANSI", "Estadísticas del registro", "Compactar líneas",
			"tabla delimitada", "Monitor de recursos", "Extractor de datos", "Historial de comandos", "Filtro de errores",
			"Copiar salida", "Clic derecho", "Análisis de texto Unicode",
			"Licencia Pública General de GNU", "MIT", "Taylor Arndt",
		):
			self.assertIn(texto, doc, texto)


# ====================================================================== configuración
class TestConfiguracion(unittest.TestCase):
	def test_valores_por_defecto(self):
		self.assertTrue(cfg.valor("conservarHistorial"))
		self.assertEqual(cfg.valor("intervaloSeguimiento"), 750)
		self.assertEqual(cfg.maxCaracteres(), 5_000_000)
		self.assertEqual(cfg.patronesAlerta(), ["ERROR", "CRITICAL", "FATAL"])
		self.assertEqual(set(cfg.herramientasHabilitadas()), set(cfg.HERRAMIENTAS_DEFECTO))

	def test_intervalo_y_limite(self):
		with _Opciones(intervaloSeguimiento=50, limiteMilesCaracteres=0):
			self.assertEqual(cfg.intervalo(), cfg.INTERVALO_MIN)
			self.assertEqual(cfg.maxCaracteres(), 0)
		with _Opciones(intervaloSeguimiento=99999):
			self.assertEqual(cfg.intervalo(), cfg.INTERVALO_MAX)

	def test_migra_modelos_retirados(self):
		with _Opciones(iaModeloGoogle="gemini-1.5-pro"):
			cfg.migrarModelo()
			self.assertEqual(cfg.valor("iaModeloGoogle"), cfg.MODELO_GOOGLE_DEFECTO)
		with _Opciones(iaModeloGoogle="gemini-3.5-flash"):
			cfg.migrarModelo()
			self.assertEqual(cfg.valor("iaModeloGoogle"), "gemini-3.5-flash")

	def test_carpeta_de_datos(self):
		self.assertTrue(cfg.carpetaDatos().endswith(os.path.join("addonsData", "consoleLog")))
		self.assertTrue(os.path.isdir(cfg.carpetaDatos()))


# ====================================================================== seguimiento
class TestSeguimiento(unittest.TestCase):
	def test_normalizar(self):
		self.assertEqual(seguimiento.normalizar_captura("a\r\nb\rc\n\n"), "a\nb\nc")

	def test_agregado_al_final(self):
		act = seguimiento.calcular_actualizacion("doc\nuno", "uno", "uno\ndos")
		self.assertTrue(act.es_agregado)
		self.assertEqual(act.texto, "\ndos")
		self.assertEqual((act.inicio, act.fin), (len("doc\nuno"), len("doc\nuno")))

	def test_sin_cambios(self):
		self.assertIsNone(seguimiento.calcular_actualizacion("x", "x", "x\n"))

	def test_linea_de_progreso_se_actualiza_en_su_sitio(self):
		anterior = "a\nb\nc\nprogreso 10%"
		nueva = "a\nb\nc\nprogreso 20%"
		act = seguimiento.calcular_actualizacion(anterior, anterior, nueva)
		self.assertEqual(act.texto, "progreso 20%")
		self.assertEqual(act.inicio, anterior.index("progreso"))
		self.assertFalse(act.reinicio)

	def test_historial_conservado_al_desplazarse(self):
		anterior = "l1\nl2\nl3\nl4"
		nueva = "l3\nl4\nl5\nl6"
		act = seguimiento.calcular_actualizacion(anterior, anterior, nueva, True)
		self.assertEqual(act.texto, "\nl5\nl6")
		self.assertTrue(act.es_agregado)
		act = seguimiento.calcular_actualizacion(anterior, anterior, nueva, False)
		self.assertTrue(act.reinicio)
		self.assertEqual(act.texto, nueva)

	def test_redibujado(self):
		act = seguimiento.calcular_actualizacion("htop A", "htop A", "vim B")
		self.assertTrue(act.reinicio)
		self.assertEqual((act.inicio, act.fin, act.texto), (0, 6, "vim B"))

	def test_solapamiento_kmp(self):
		self.assertEqual(seguimiento.solapamiento_lineas("a\nb\nc", "b\nc\nd"), 2)
		self.assertEqual(seguimiento.solapamiento_lineas("a\nb", "x\ny"), 0)
		self.assertEqual(seguimiento.solapamiento_lineas("a\na\na", "a\na\nb"), 2)

	def test_recortar_lineas_completas(self):
		texto = "uno\ndos\ntres\ncuatro"
		recortado, quitados = seguimiento.recortar_documento(texto, 10)
		self.assertEqual(recortado, "cuatro")
		self.assertEqual(quitados, len(texto) - len("cuatro"))
		self.assertEqual(seguimiento.recortar_documento(texto, 0), (texto, 0))

	def test_trasladar_posicion(self):
		act = seguimiento.ActualizacionDocumento(5, 8, "abcdef")
		self.assertEqual(seguimiento.trasladar_posicion(3, act), 3)
		self.assertEqual(seguimiento.trasladar_posicion(10, act), 13)
		self.assertEqual(seguimiento.trasladar_posicion(6, act), 5)

	def test_intervalo_adaptativo(self):
		self.assertEqual(seguimiento.adaptar_intervalo(750, 750, 100), 750)
		self.assertEqual(seguimiento.adaptar_intervalo(750, 750, 2000), 3000)
		self.assertEqual(seguimiento.adaptar_intervalo(750, 3000, 100), 2750)
		self.assertEqual(seguimiento.adaptar_intervalo(750, 750, 99999), 10000)


# ====================================================================== registro de visores
class TestRegistro(unittest.TestCase):
	def test_ciclo(self):
		r = RegistroVisores()
		recurso, otro = object(), object()
		self.assertTrue(r.reservar("k", recurso))
		self.assertFalse(r.reservar("k", otro))
		self.assertTrue(r.esta_pendiente("k"))
		self.assertTrue(r.coincide_reserva("k", recurso))
		self.assertFalse(r.liberar_reserva("k", otro))
		visor = object()
		self.assertTrue(r.registrar("k", visor))
		self.assertFalse(r.esta_pendiente("k"))
		self.assertIs(r.obtener("k"), visor)
		self.assertEqual(r.cantidad, 1)
		self.assertFalse(r.retirar("k", object()))
		self.assertTrue(r.retirar("k", visor))
		self.assertEqual(r.cantidad, 0)
		r.reservar("j", recurso)
		self.assertEqual(r.recursos_pendientes(), (recurso,))
		r.limpiar()
		self.assertEqual(r.recursos_pendientes(), ())


# ====================================================================== detección
def _obj(**kw):
	return SimpleNamespace(**kw)


class TestDeteccion(unittest.TestCase):
	def _destino(self, clase="", app="", producto="", foco_terminal=False):
		d = deteccion.DestinoConsola(clase=clase, nombreApp=app, producto=producto, focoEsTerminal=foco_terminal, hwnd=1)
		d.tipo = deteccion.tipo_consola(d)
		return d

	def test_consolas_reconocidas(self):
		self.assertEqual(self._destino("ConsoleWindowClass").tipo, "clasica")
		self.assertEqual(self._destino("CASCADIA_HOSTING_WINDOW_CLASS").tipo, "terminal")
		self.assertEqual(self._destino("X", producto="Windows Terminal").tipo, "terminal")
		self.assertEqual(self._destino("PuTTY", "putty").tipo, "putty")
		for app in ("mintty", "alacritty", "wezterm-gui", "mobaxterm", "ttermpro", "royalts"):
			self.assertTrue(deteccion.es_ventana_consola(self._destino("Otra", app)), app)
		self.assertEqual(self._destino("Notepad", "notepad").tipo, "desconocida")
		self.assertFalse(deteccion.es_ventana_consola(self._destino("Notepad", "notepad")))
		self.assertTrue(deteccion.es_ventana_consola(self._destino("Rara", "rara", foco_terminal=True)))

	def test_instantanea(self):
		from tiresias.objects.roles import Role

		app = _obj(appName="WindowsTerminal", productName="Windows Terminal")
		fg = _obj(appModule=app, windowHandle=100, processID=7, windowClassName="CASCADIA_HOSTING_WINDOW_CLASS", name="PowerShell")
		elemento = object()
		foco = _obj(windowHandle=101, name="Terminal", role=Role.TERMINAL, element=elemento, processID=7)
		d = deteccion.instantanea(fg, foco)
		self.assertEqual((d.hwnd, d.hwndFoco, d.pid, d.tipo), (100, 101, 7, "terminal"))
		self.assertIs(d.elemento, elemento)
		self.assertTrue(d.focoEsTerminal)
		# El foco de otro proceso no se guarda como área de texto.
		foco2 = _obj(windowHandle=5, name="x", role=None, element=elemento, processID=99)
		self.assertIsNone(deteccion.instantanea(fg, foco2).elemento)

	def test_identidad(self):
		class User32:
			def GetAncestor(self, hwnd, flags):
				return 555

			def GetWindowThreadProcessId(self, hwnd, pid):
				pid._obj.value = 42

		d = deteccion.DestinoConsola(tipo="clasica", hwnd=123, pid=1, titulo="Símbolo del sistema")
		ident = deteccion.obtener_identidad(d, User32())
		self.assertEqual(ident, deteccion.IdentidadConsola("clasica", 555, 42))
		self.assertEqual(deteccion.etiqueta_consola(d, ident), "Símbolo del sistema [42:22B]")
		self.assertIsNone(deteccion.obtener_identidad(deteccion.DestinoConsola()))

	def test_perfiles(self):
		det = deteccion.DetectorTerminal()
		self.assertEqual(det.detectar_aplicacion(deteccion.DestinoConsola(nombreApp="WindowsTerminal")), "windowsterminal")
		self.assertEqual(det.detectar_aplicacion(deteccion.DestinoConsola(nombreApp="conemu64")), "conemu64")
		self.assertEqual(det.detectar_aplicacion(deteccion.DestinoConsola(nombreApp="xyz", titulo="htop - servidor")), "htop")
		self.assertEqual(det.detectar_aplicacion(deteccion.DestinoConsola(nombreApp="xyz")), "default")
		self.assertTrue(det.obtener_perfil("htop").condensar_simbolos)
		self.assertFalse(det.obtener_perfil("cmd").limpiar_ansi)
		self.assertIn("Terminal: Windows Terminal", det.obtener_info_perfil("windowsterminal"))
		p = deteccion.PerfilTerminal.from_dict(det.obtener_perfil("wezterm").to_dict())
		self.assertEqual(p.nombre_mostrar, "WezTerm")


# ====================================================================== procesamiento de texto
class TestProcesadorTexto(unittest.TestCase):
	def test_limpiar_ansi(self):
		texto = "\x1b[31mrojo\x1b[0m \x1b]0;titulo\x07fin \x1b[2K\x1b[1;32mok"
		self.assertEqual(pt.AnalizadorANSI.limpiar_ansi(texto), "rojo fin ok")

	def test_atributos(self):
		a = pt.AnalizadorANSI()
		a.analizar("\x1b[1;4;31;44mX")
		self.assertEqual(a.formatear_atributos(), "texto rojo, fondo azul, negrita, subrayado")
		a.reiniciar()
		a.analizar("\x1b[38;5;208m\x1b[48;2;1;2;3m")
		self.assertEqual(a.formatear_atributos(), "texto color208, fondo RGB(1,2,3)")
		self.assertEqual(a.formatear_atributos("breve"), "color208, fondo RGB")
		a.analizar("\x1b[0m")
		self.assertEqual(a.formatear_atributos(), "atributos por defecto")

	def test_anchos(self):
		self.assertEqual(pt.AyudanteUnicode.obtener_ancho_texto("ab"), 2)
		self.assertEqual(pt.AyudanteUnicode.obtener_ancho_texto("漢字"), 4)
		self.assertEqual(pt.AyudanteUnicode.obtener_ancho_texto("e\u0301"), 1)
		self.assertEqual(pt.AyudanteUnicode.extraer_rango_columnas("漢字ab", 3, 5), "字a")

	def test_bidi(self):
		b = pt.AyudanteBidi()
		self.assertTrue(b.es_rtl("שלום"))
		self.assertEqual(b.detectar_direccion("hello"), "ltr")
		self.assertEqual(b.procesar_texto("שלום"), "םולש")
		self.assertEqual(b.procesar_linea_a_linea("abc\nשלום\n"), "abc\nםולש\n")
		self.assertIn("derecha a izquierda", b.obtener_info_direccion("שלום עולם"))

	def test_emoji(self):
		e = pt.AyudanteEmoji()
		familia = "\U0001F468\u200d\U0001F469\u200d\U0001F467"
		texto = "hola 👍🏽 y {} 🇪🇸".format(familia)
		self.assertTrue(e.contiene_emoji(texto))
		lista = e.extraer_lista_emoji(texto)
		self.assertEqual(lista, ["👍🏽", familia, "🇪🇸"])
		self.assertEqual(e.contar_emoji(texto), 3)
		self.assertEqual(e.obtener_ancho_texto_con_emoji("a👍"), 3)
		self.assertIn("thumbs up", e.obtener_descripcion_emoji("👍"))
		self.assertFalse(e.contiene_emoji("sin emoji"))

	def test_indentacion_y_simbolos(self):
		self.assertEqual(pt.DetectorIndentacion.detectar_indentacion("\t  x"), "1 tabulación, 2 espacios")
		self.assertEqual(pt.DetectorIndentacion.detectar_indentacion("x"), "sin indentación")
		self.assertEqual(pt.DetectorIndentacion.obtener_nivel_indentacion("\t x"), 5)
		c = pt.CondensadorSimbolos()
		self.assertEqual(c.condensar("a ===== b -- c"), "a 5 igual b -- c")
		c.simbolos = "#"
		self.assertEqual(c.condensar("#### x"), "4 almohadilla x")

	def test_puntuacion(self):
		self.assertEqual(pt.FiltroPuntuacion(0).filtrar("Hola, ¿qué tal? (bien)"), "Hola qué tal bien")
		self.assertEqual(pt.FiltroPuntuacion(1).filtrar("a, b; c (d)"), "a, b; c d")
		self.assertEqual(pt.FiltroPuntuacion(3).filtrar("a-b"), "a-b")
		self.assertEqual(pt.FiltroPuntuacion(2).nombre_nivel(), "Mayoría")

	def test_tuberia(self):
		p = pt.ProcesadorTexto()
		self.assertEqual(p.procesar_texto("\x1b[31m=====\x1b[0m", limpiar_ansi=True, condensar_simbolos=True), "5 igual")
		self.assertEqual(p.procesar_texto("\x1b[31mx", limpiar_ansi=False), "\x1b[31mx")
		self.assertIn("Ancho de visualización", p.obtener_info_texto("hola 👍"))


# ====================================================================== definiciones de ventana
class TestDefiniciones(unittest.TestCase):
	def test_filtros_y_regiones(self):
		g = dv.GestorDefinicionesVentana()
		self.assertEqual(len(g.listar_definiciones()), 4)
		self.assertEqual(g.obtener_definiciones_activas(), [])
		texto = "\n".join("fila {}".format(i) for i in range(1, 26))
		self.assertEqual(g.aplicar_filtros(texto), texto)
		g.habilitar_definicion("barra_estado")
		filtrado = g.aplicar_filtros(texto)
		self.assertNotIn("fila 24", filtrado)
		self.assertIn("fila 25", filtrado)
		d = g.crear_definicion_interactiva("Cabecera Uno", 1, 2, 1, 4, dv.MODO_MONITORIZAR)
		self.assertEqual(d.extraer_texto(texto), "fila\nfila")
		self.assertIs(g.obtener_definicion("cabecera_uno"), d)
		self.assertTrue(g.hay_monitorizadas())
		self.assertEqual(g.detectar_cambios(texto), {"cabecera_uno": "fila\nfila"})
		self.assertEqual(g.detectar_cambios(texto), {})
		self.assertIs(g.obtener_ventana_en_posicion(1, 2), d)
		self.assertIn("Activas: 2", g.obtener_resumen())
		self.assertTrue(g.eliminar_definicion("cabecera_uno"))
		self.assertFalse(g.eliminar_definicion("cabecera_uno"))

	def test_validacion_y_persistencia(self):
		d = dv.DefinicionVentana("x", 0, -3, 5, 2, "raro")
		self.assertEqual((d.fila_superior, d.fila_inferior, d.columna_izquierda, d.columna_derecha, d.modo), (1, 1, 5, 5, "anunciar"))
		ruta = os.path.join(_TMP, "defs_prueba.json")
		g = dv.GestorDefinicionesVentana(ruta)
		g.agregar_definicion("mia", dv.DefinicionVentana("Mía", 3, 4, 1, 10, dv.MODO_SILENCIO, True, "prueba"))
		g.habilitar_definicion("panel_derecho")
		self.assertTrue(g.guardar_definiciones())
		g2 = dv.GestorDefinicionesVentana(ruta)
		self.assertEqual(g2.obtener_definicion("mia").descripcion, "prueba")
		self.assertTrue(g2.obtener_definicion("panel_derecho").habilitada)
		self.assertIn("modo: Silencio", g2.obtener_definicion("mia").obtener_descripcion())


# ====================================================================== Markdown
class TestMarkdown(unittest.TestCase):
	def test_estructura(self):
		md = "# Título\n\nTexto **negrita** y *cursiva* con `código <b>`.\n\n- uno\n- dos\n\n1. a\n2. b\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n> cita\n\n---\n\n```python\nprint('<hola>')\n```"
		h = markdown_html.markdown_a_html(md)
		for parte in ("<h1>Título</h1>", "<strong>negrita</strong>", "<em>cursiva</em>", "<code>código &lt;b&gt;</code>", "<ul><li>uno</li><li>dos</li></ul>", "<ol><li>a</li><li>b</li></ol>", '<th scope="col">A</th>', "<td>2</td>", "<blockquote><p>cita</p></blockquote>", "<hr>", 'class="language-python"', "print(&#x27;&lt;hola&gt;&#x27;)"):
			self.assertIn(parte, h)

	def test_seguridad(self):
		h = markdown_html.markdown_a_html("<script>alert(1)</script> [x](javascript:alert(1)) [web](https://ejemplo.es)")
		self.assertNotIn("<script>", h)
		self.assertNotIn('href="javascript', h)
		self.assertIn('<a href="https://ejemplo.es">web</a>', h)

	def test_texto_y_documento(self):
		self.assertEqual(markdown_html.html_a_texto("<h2>Hola</h2><p>a<br>b</p>"), "Hola\na\nb")
		doc = markdown_html.documento_html("Informe <1>", "<p>x</p>")
		self.assertIn("<title>Informe &lt;1&gt;</title>", doc)
		self.assertIn('lang="es"', doc)


# ====================================================================== herramientas
class TestHerramientas(unittest.TestCase):
	def setUp(self):
		self.g = GestorHerramientas(SimpleNamespace(definiciones=dv.GestorDefinicionesVentana()))
		self.g.cargar_plugins(cfg.HERRAMIENTAS_DEFECTO)

	def tearDown(self):
		self.g.descargar_plugins()

	def ejecutar(self, nombre, texto, **kw):
		return self.g.obtener_plugin(nombre).ejecutar(texto=texto, **kw)

	def test_descubrimiento_y_metadatos(self):
		disponibles = self.g.listar_plugins_disponibles()
		self.assertEqual(sorted(disponibles), sorted(cfg.HERRAMIENTAS_DEFECTO))
		self.assertEqual(sorted(self.g.listar_plugins_cargados()), sorted(cfg.HERRAMIENTAS_DEFECTO))
		for nombre in disponibles:
			meta = self.g.metadatos(nombre)
			self.assertTrue(meta.nombre and meta.descripcion and meta.categoria, nombre)
			self.assertIsInstance(self.g.obtener_plugin(nombre), HerramientaBase)
		self.assertEqual(nombre_categoria("ia"), "Inteligencia artificial")
		self.g.sincronizar(["filtro_log"])
		self.assertEqual(self.g.listar_plugins_cargados(), ["filtro_log"])
		self.assertTrue(self.g.habilitar_plugin("json_beauty"))
		self.assertTrue(self.g.deshabilitar_plugin("json_beauty"))

	def test_seleccion_preferida(self):
		r = self.ejecutar("filtro_log", "ERROR uno\nnada", seleccionado="warning dos")
		self.assertEqual(r, ["warning dos"])

	def test_texto(self):
		self.assertEqual(self.ejecutar("lineas_unicas", "a\na\na\nb"), "a  [3 ×]\nb")
		sql = self.ejecutar("sql_formatter", "select a from t where x = 'from' and y=1 order by a")[0]
		self.assertEqual(sql, "SELECT a\nFROM t\nWHERE x = 'from'\n  AND y=1\nORDER BY a")
		self.assertEqual(self.ejecutar("tabla_delimitada", "a,bb\nccc,d"), "a   | bb\nccc | d")
		self.assertIn("Líneas duplicadas: 1", self.ejecutar("estadisticas_log", "ERROR x\nERROR x\ninfo y"))
		self.assertIn("ERROR: 2", self.ejecutar("estadisticas_log", "ERROR x\nERROR x\ninfo y"))
		self.assertIn("Git: 1 menciones", "\n".join(self.ejecutar("resumen_actividad", "$ git status\nok")))

	def test_desarrollo(self):
		trazas = self.ejecutar("stacktrace_analyzer", 'Traceback (most recent call last):\n  File "C:\\p\\app.py", line 12, in f\nValueError: malo')
		self.assertIn("app.py:12 -> C:\\p\\app.py (Python)", trazas)
		self.assertIn("Error: ValueError: malo", trazas)
		bloques = self.ejecutar("json_beauty", 'log {"a": [1, 2], "b": {"c": true}} y [3, 4] y {} fin')
		self.assertEqual(len(bloques), 2)
		self.assertEqual(json.loads(bloques[0]), {"a": [1, 2], "b": {"c": True}})
		cadena = base64.b64encode("hola mundo secreto".encode()).decode()
		self.assertEqual(self.ejecutar("base64_decoder", "token " + cadena), ["{} -> hola mundo secreto".format(cadena)])

		def b64(d):
			return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")

		token = "{}.{}.firma".format(b64({"alg": "HS256", "typ": "JWT"}), b64({"sub": "123", "exp": 1700000000}))
		jwt = self.ejecutar("jwt_decoder", "Bearer " + token)[0]
		self.assertIn('"alg": "HS256"', jwt)
		self.assertIn('"sub": "123"', jwt)
		self.assertIn("exp: ", jwt)
		self.assertIn("firma no se ha comprobado", jwt)
		self.assertEqual(self.ejecutar("jwt_decoder", "nada"), ["No se encontraron tokens JWT válidos."])
		informe = self.ejecutar("analizador_indentacion", "def f():\n    x = 1\n\t y\n")
		self.assertIn("Inconsistencias detectadas", informe)
		self.assertIn("Línea 2 [4 espacios]", informe)
		self.assertIn("Nivel máximo de indentación: 5 espacios", informe)

	def test_analisis(self):
		r = self.ejecutar("extractor_datos", "ver https://ejemplo.es/a, ip 192.168.1.10 y 999.1.1.1 en C:\\Users\\x\\a.txt y /usr/local/bin")
		self.assertEqual(r["urls"], ["https://ejemplo.es/a"])
		self.assertEqual(r["ips"], ["192.168.1.10"])
		self.assertIn("C:\\Users\\x\\a.txt", r["rutas"])
		self.assertIn("/usr/local/bin", r["rutas"])
		from consoleLog.herramientas.extractor_datos import como_lista, valor_de_elemento

		lista = como_lista(r)
		self.assertIn("[URL] https://ejemplo.es/a", lista)
		self.assertEqual(valor_de_elemento("[IP] 192.168.1.10"), "192.168.1.10")
		marcas = self.ejecutar("timestamp_converter", "t=1700000000 y 1700000000123")
		self.assertEqual(len(marcas), 2)
		self.assertTrue(marcas[0].startswith("1700000000 -> "))
		historial = self.ejecutar("historial_comandos", "C:\\Users\\a>dir\nPS C:\\x> ls\nuser@host:~$ make\n$ git log\n>>> 1+1\nsalida")
		self.assertEqual(historial, ["dir", "ls", "make", "git log", "1+1"])
		h = self.g.obtener_plugin("historial_comandos")
		self.assertEqual(h.obtener_ultimo_comando("$ a\n$ b"), "b")
		self.assertEqual(h.obtener_comandos_unicos("$ a\n$ b\n$ a"), ["a", "b"])
		ansi = self.ejecutar("atributos_ansi", "\x1b[1;31mfallo\x1b[0m\nnormal")
		self.assertIn("Línea 1: «fallo»: texto rojo, negrita", ansi)
		self.assertIn("No se detectaron secuencias", self.ejecutar("atributos_ansi", "sin color"))
		self.assertIn("Dirección", self.ejecutar("analisis_unicode", "hola"))

	def test_calculadora(self):
		r = self.ejecutar("calculadora_express", "total 10 + 5 * 2, 2^10, 7 / 2, fecha 2026-10-08 y 10/08/2026, 2^5000")
		self.assertIn("10 + 5 * 2 = 20", r)
		self.assertIn("2^10 = 1024", r)
		self.assertIn("7 / 2 = 3.5", r)
		self.assertFalse(any("2026" in x for x in r))
		self.assertFalse(any("5000" in x for x in r))
		from consoleLog.herramientas.calculadora_express import evaluar

		with self.assertRaises(ValueError):
			evaluar("__import__('os')")
		with self.assertRaises(ValueError):
			evaluar("+".join(["1"] * 50))

	def test_utilidades(self):
		PORTAPAPELES.clear()
		self.assertTrue(self.ejecutar("copiar_salida", "contenido"))
		self.assertEqual(PORTAPAPELES, ["contenido"])
		self.assertFalse(self.ejecutar("copiar_salida", ""))
		recursos = self.ejecutar("monitor_recursos", "")
		self.assertTrue(any(r.startswith("Uso de memoria RAM") for r in recursos))
		self.assertTrue(any(r.startswith("Versión de Tiresias") for r in recursos))
		informe = self.ejecutar("definiciones_ventana", "a\nb")
		self.assertIn("Definiciones de ventana", informe)
		self.assertIn("filas 1-2, columnas 1-1", informe)

	def test_clic_derecho(self):
		from tiresias import mouse, winapi

		with mock.patch.object(winapi, "getWindowRect", return_value=(100, 200, 400, 300)), mock.patch.object(winapi, "getCursorPos", return_value=(5, 6)), mock.patch.object(mouse, "click") as click, mock.patch.object(mouse, "moveTo") as mover:
			self.assertTrue(self.g.obtener_plugin("clic_derecho").ejecutar(destino=deteccion.DestinoConsola(hwnd=9)))
		click.assert_called_once_with(300, 350, "right")
		mover.assert_called_once_with(5, 6)
		self.assertFalse(self.g.obtener_plugin("clic_derecho").ejecutar(destino=deteccion.DestinoConsola(hwnd=0)))


# ====================================================================== lectores
class TestLectores(unittest.TestCase):
	def test_limpiar(self):
		self.assertEqual(lectores.limpiar_texto("a  \r\nb\t \n\n  \n"), "a\nb")

	def test_lectura_por_bloques(self):
		llamadas = []

		def leerFilas(fila, filas):
			llamadas.append((fila, filas))
			return ["f{}   ".format(fila + i) for i in range(filas)]

		with mock.patch.object(lectores, "CELDAS_POR_BLOQUE", 100):
			texto = lectores.leer_buffer_por_bloques(leerFilas, 40, 7)
		self.assertEqual(llamadas, [(0, 2), (2, 2), (4, 2), (6, 1)])
		self.assertEqual(texto.splitlines(), ["f{}".format(i) for i in range(7)])
		senal = threading.Event()
		senal.set()
		with self.assertRaises(lectores.LecturaCancelada):
			lectores.leer_buffer_por_bloques(leerFilas, 40, 7, senal)

	def test_puntuacion_candidatos(self):
		visible = lectores.puntuar_candidato(False, "TermControl", 100, 3)
		oculto = lectores.puntuar_candidato(True, "TermControl", 900, 0)
		sin_pista = lectores.puntuar_candidato(False, "Edit", 900, 0)
		self.assertGreater(visible, oculto)
		self.assertGreater(visible, sin_pista)

	def test_clasica_con_alternativas(self):
		destino = deteccion.DestinoConsola(tipo="clasica", pid=5, hwnd=1)
		with mock.patch.object(lectores.LectorClasico, "leer", side_effect=lectores.LectorNoDisponible("x")), mock.patch.object(lectores.LectorUIA, "leer", return_value="por uia"):
			self.assertEqual(lectores.leer_destino(destino), "por uia")
		from tiresias import console_reader

		with mock.patch.object(lectores.LectorClasico, "leer", side_effect=lectores.AccesoDenegado(lectores.MENSAJE_ELEVADA)), mock.patch.object(lectores.LectorUIA, "leer", side_effect=Exception("uia")), mock.patch.object(console_reader, "readVisibleLines", return_value=["visible  ", ""]):
			self.assertEqual(lectores.leer_destino(destino), "visible")
		with mock.patch.object(lectores.LectorClasico, "leer", side_effect=lectores.AccesoDenegado(lectores.MENSAJE_ELEVADA)), mock.patch.object(lectores.LectorUIA, "leer", side_effect=Exception("uia")), mock.patch.object(console_reader, "readVisibleLines", return_value=None):
			with self.assertRaises(lectores.AccesoDenegado):
				lectores.leer_destino(destino)

	def test_tipos(self):
		with mock.patch.object(lectores.LectorPutty, "leer", return_value="putty"):
			self.assertEqual(lectores.leer_destino(deteccion.DestinoConsola(tipo="putty")), "putty")
		with mock.patch.object(lectores.LectorUIA, "leer", return_value="wt"):
			self.assertEqual(lectores.leer_destino(deteccion.DestinoConsola(tipo="terminal")), "wt")

	def test_clasico_no_disponible_con_consola_propia(self):
		from tiresias import console_reader

		with mock.patch.object(console_reader, "hasOwnConsole", return_value=True):
			with self.assertRaises(lectores.LectorNoDisponible):
				lectores.LectorClasico().leer(deteccion.DestinoConsola(pid=1))

	def _esperar(self, gestor):
		for _i in range(200):
			if not gestor.activa:
				return
			threading.Event().wait(0.01)

	def test_gestor_exito_error_y_cancelacion(self):
		entregados = []
		listo = threading.Event()

		def entregar(funcion, *args):
			funcion(*args)
			listo.set()

		g = lectores.GestorLectores(entregar=entregar, leer=lambda destino, senal: "texto crudo")
		resultados = []
		self.assertTrue(g.leer_consola(None, resultados.append, entregados.append, emitir_beep=False, procesar=str.upper))
		self.assertTrue(listo.wait(2))
		self.assertEqual(resultados, ["TEXTO CRUDO"])
		self._esperar(g)
		listo.clear()

		def falla(destino, senal):
			raise Exception("sin acceso")

		g2 = lectores.GestorLectores(entregar=entregar, leer=falla)
		g2.leer_consola(None, resultados.append, entregados.append, emitir_beep=False)
		self.assertTrue(listo.wait(2))
		self.assertEqual(entregados, ["sin acceso"])

		bloqueo = threading.Event()

		def lento(destino, senal):
			bloqueo.wait(2)
			return "tarde"

		g3 = lectores.GestorLectores(entregar=entregar, leer=lento)
		otros = []
		self.assertTrue(g3.leer_consola(None, otros.append, otros.append, emitir_beep=False))
		self.assertFalse(g3.leer_consola(None, otros.append, otros.append, emitir_beep=False))
		g3.cancelar_lectura()
		bloqueo.set()
		self._esperar(g3)
		self.assertEqual(otros, [])
		self.assertFalse(g3.activa)


# ====================================================================== protección de ráfagas
class TestProtector(unittest.TestCase):
	def setUp(self):
		from tiresias.objects import terminal

		self.terminal = terminal
		self.original = terminal.Terminal._speakNewText
		self.leido: list[list[str]] = []
		terminal.Terminal._speakNewText = lambda obj, added: self.leido.append(list(added))
		self.p = protector_rafagas.ProtectorRafagas()
		self.pendientes_voz: list = []

	def tearDown(self):
		self.p.desinstalar()
		self.terminal.Terminal._speakNewText = self.original

	def test_instalar_y_desinstalar(self):
		envoltura_previa = self.terminal.Terminal._speakNewText
		self.assertTrue(self.p.instalar())
		self.assertTrue(self.p.activo)
		self.assertIsNot(self.terminal.Terminal._speakNewText, envoltura_previa)
		self.p.desinstalar()
		self.assertFalse(self.p.activo)
		self.assertIs(self.terminal.Terminal._speakNewText, envoltura_previa)

	def test_lotes_reemplazo_y_cancelacion(self):
		from tiresias.speech import api as speechApi

		with mock.patch.object(speechApi, "whenDoneSpeaking", side_effect=self.pendientes_voz.append), _OpcionesTerminal(200):
			self.p.instalar()
			lineas = ["l{}".format(i) for i in range(150)]
			self.terminal.Terminal._speakNewText(object(), lineas)
			# Solo las 100 más recientes, en lotes de 5; el primero enseguida.
			self.assertEqual(self.leido, [["l50", "l51", "l52", "l53", "l54"]])
			self.assertEqual(self.p.pendientes, 19)
			self.pendientes_voz.pop(0)()
			self.assertEqual(self.leido[-1], ["l55", "l56", "l57", "l58", "l59"])
			# Una ráfaga nueva sustituye a lo pendiente.
			self.terminal.Terminal._speakNewText(object(), ["nueva"])
			self.assertEqual(self.p.pendientes, 0)
			for cb in list(self.pendientes_voz):
				cb()
			self.assertEqual(self.leido[-1], ["nueva"])
			self.assertEqual(len(self.leido), 3)
			# Callar la voz descarta lo pendiente.
			self.terminal.Terminal._speakNewText(object(), ["x{}".format(i) for i in range(12)])
			speechApi.pre_speechCanceled.notify()
			self.assertEqual(self.p.pendientes, 0)

	def test_respeta_el_maximo_de_tiresias(self):
		with _OpcionesTerminal(20):
			self.assertEqual(self.p.maxLineas(), 20)
			self.assertEqual(sum(len(l) for l in self.p.dividir(["x"] * 50)), 20)


class _OpcionesTerminal:
	def __init__(self, maximo: int) -> None:
		self.maximo = maximo

	def __enter__(self):
		self.viejo = conf["terminal"]["maxLinesPerUpdate"]
		conf["terminal"]["maxLinesPerUpdate"] = self.maximo

	def __exit__(self, *exc):
		conf["terminal"]["maxLinesPerUpdate"] = self.viejo


# ====================================================================== lanzador
class TestLanzador(unittest.TestCase):
	def _gestor(self):
		g = lanzador.GestorLanzador()
		g._consolas = {
			"cmd": lanzador.InfoConsola("CMD", "cmd", True, "cmd.exe"),
			"powershell": lanzador.InfoConsola("PowerShell", "powershell", True, "powershell.exe"),
			"wt": lanzador.InfoConsola("Windows Terminal", "wt", False),
			"git-bash": lanzador.InfoConsola("Git Bash", "git-bash", True, r"C:\Git"),
			"vs-64": lanzador.InfoConsola("VS 64", "vs-64", True, r"C:\VS\vcvars64.bat"),
			"pwsh": lanzador.InfoConsola("PS7", "pwsh", True, r"C:\PS7\pwsh.exe"),
			"wsl": lanzador.InfoConsola("WSL", "wsl", True, r"C:\Windows\System32\wsl.exe"),
			"msys2": lanzador.InfoConsola("MSYS2", "msys2", True, r"C:\msys64"),
		}
		g._detectadas.set()
		return g

	def test_comandos(self):
		g = self._gestor()
		d = r"C:\mi carpeta"
		self.assertEqual(g.construir_comando("cmd", d), ("cmd.exe", '/k pushd "C:\\mi carpeta"'))
		self.assertEqual(g.construir_comando("powershell", r"C:\it's"), ("powershell.exe", "-NoExit -Command \"Set-Location -LiteralPath 'C:\\it''s'\""))
		self.assertEqual(g.construir_comando("pwsh", d)[0], r"C:\PS7\pwsh.exe")
		self.assertEqual(g.construir_comando("wt", d), ("wt.exe", '-d "C:\\mi carpeta"'))
		self.assertEqual(g.construir_comando("git-bash", d), (r"C:\Git\git-bash.exe", '--cd="C:\\mi carpeta"'))
		self.assertEqual(g.construir_comando("vs-64", d), ("cmd.exe", '/k pushd "C:\\VS" && call "C:\\VS\\vcvars64.bat" && pushd "C:\\mi carpeta"'))
		self.assertEqual(g.construir_comando("wsl", d), (r"C:\Windows\System32\wsl.exe", '--cd "C:\\mi carpeta"'))
		self.assertIn("msys2_shell.cmd", g.construir_comando("msys2", d)[1])
		with self.assertRaises(ValueError):
			g.construir_comando("nada", d)

	def test_opciones(self):
		g = self._gestor()
		nombres = [o.nombre for o in g.opciones(False)]
		self.assertEqual(nombres[:4], ["Abrir CMD aquí", "Abrir CMD como administrador", "Abrir PowerShell aquí", "Abrir PowerShell como administrador"])
		self.assertNotIn("Abrir Windows Terminal aquí", nombres)
		todas = g.opciones(True)
		wt = [o for o in todas if o.tipo == "wt"]
		self.assertEqual(len(wt), 2)
		self.assertFalse(wt[0].disponible)
		self.assertTrue(wt[0].nombre.endswith("(no instalada)"))
		self.assertEqual(todas[1].clave, "cmd|1")
		vs = [o for o in todas if o.tipo == "vs-64"][0]
		self.assertEqual(vs.script_vs, r"C:\VS\vcvars64.bat")

	def test_directorio_valido(self):
		carpeta = tempfile.mkdtemp(dir=_TMP)
		archivo = os.path.join(carpeta, "a.txt")
		with open(archivo, "w") as f:
			f.write("x")
		self.assertEqual(lanzador.GestorLanzador.encontrar_directorio_valido(carpeta), carpeta)
		self.assertEqual(lanzador.GestorLanzador.encontrar_directorio_valido(archivo), carpeta)
		self.assertEqual(lanzador.GestorLanzador.encontrar_directorio_valido(os.path.join(carpeta, "no", "existe.txt")), carpeta)
		self.assertIsNone(lanzador.GestorLanzador.encontrar_directorio_valido(None))
		self.assertTrue(os.path.isabs(lanzador.GestorLanzador.carpeta_escritorio()))
		g = self._gestor()
		self.assertEqual(g.obtener_directorio(False, 0, ""), lanzador.GestorLanzador.carpeta_escritorio())

	def test_abrir_usa_runas(self):
		g = self._gestor()
		llamadas = []
		hecho = threading.Event()

		def shell(*args):
			llamadas.append(args)
			hecho.set()
			return 42

		with mock.patch.object(lanzador.ctypes.windll.shell32, "ShellExecuteW", side_effect=shell):
			g.abrir_consola("cmd", r"C:\x", como_admin=True)
			self.assertTrue(hecho.wait(2))
		self.assertEqual(llamadas[0][1:5], ("runas", "cmd.exe", '/k pushd "C:\\x"', r"C:\x"))

	def test_deteccion_sin_procesos(self):
		g = lanzador.GestorLanzador()
		with mock.patch.object(lanzador, "_ejecutarSilencioso", return_value=(1, b"")), mock.patch.object(lanzador.shutil, "which", return_value=None), mock.patch.object(lanzador.os, "walk", return_value=iter([])):
			hecho = threading.Event()
			g.detectar_en_segundo_plano(hecho.set)
			self.assertTrue(hecho.wait(5))
		disponibles = [c.identificador for c in g.obtener_consolas_disponibles()]
		self.assertIn("cmd", disponibles)
		self.assertNotIn("powershell", disponibles)
		self.assertEqual(len(g.obtener_todas_consolas()), 9)


# ====================================================================== IA
class TestIA(unittest.TestCase):
	def test_claves_cifradas(self):
		ruta = os.path.join(_TMP, "claves_prueba.json")
		ia.guardar_claves(["clave-falsa-1", " ", "clave-falsa-2"], ruta)
		with open(ruta, encoding="utf-8") as f:
			self.assertNotIn("clave-falsa", f.read())
		self.assertEqual(ia.cargar_claves(ruta), ["clave-falsa-1", "clave-falsa-2"])
		ia.guardar_claves([], ruta)
		self.assertFalse(os.path.exists(ruta))
		self.assertEqual(ia.cargar_claves(ruta), [])
		self.assertEqual(ia.separar_claves("a\n\n b \n"), ["a", "b"])

	def test_cuerpo_y_respuesta(self):
		cuerpo = ia.cuerpo_google([ia.Turno("user", "hola"), ia.Turno("model", "qué"), ia.Turno("user", "x")], "sistema", 100)
		self.assertEqual([c["role"] for c in cuerpo["contents"]], ["user", "model", "user"])
		self.assertEqual(cuerpo["systemInstruction"]["parts"][0]["text"], "sistema")
		self.assertEqual(cuerpo["generationConfig"]["maxOutputTokens"], 100)
		self.assertEqual(ia.texto_respuesta_google({"candidates": [{"content": {"parts": [{"text": "a"}, {"text": "b"}]}}]}), "ab")
		with self.assertRaises(ia.ErrorIA):
			ia.texto_respuesta_google({"promptFeedback": {"blockReason": "SAFETY"}})

	def test_rotacion_de_claves(self):
		llamadas = []

		def peticion(url, clave, cuerpo=None, timeout=60):
			llamadas.append((url, clave))
			if clave == "k1":
				raise urllib.error.HTTPError(url, 429, "cuota", {}, io.BytesIO(b"{}"))
			return {"candidates": [{"content": {"parts": [{"text": "respuesta"}]}}]}

		with mock.patch.object(ia, "_peticion", side_effect=peticion):
			cliente = ia.ClienteGoogle(["k1", "k2"], "gemini-x")
			self.assertEqual(cliente.chat([ia.Turno("user", "hola")]), "respuesta")
		self.assertEqual([c for _u, c in llamadas], ["k1", "k2"])
		self.assertTrue(llamadas[0][0].endswith("/models/gemini-x:generateContent"))
		self.assertNotIn("k1", llamadas[0][0])
		with self.assertRaises(ia.ErrorIA):
			ia.ClienteGoogle([], "m").chat([ia.Turno("user", "x")])

	def test_listado_de_modelos(self):
		ruta = os.path.join(_TMP, "modelos_prueba.json")
		if os.path.exists(ruta):
			os.remove(ruta)
		datos = {"models": [{"name": "models/gemini-3.6-flash"}, {"name": "models/gemma-4"}, {"name": "models/embedding-001"}]}
		with mock.patch.object(ia, "_peticion", return_value=datos):
			self.assertEqual(ia.ListadorModelos(ruta).obtener_modelos(["k"]), ["gemini-3.6-flash", "gemma-4"])
		with mock.patch.object(ia, "_peticion", side_effect=Exception("red")):
			self.assertEqual(ia.ListadorModelos(ruta).obtener_modelos(["k"]), ["gemini-3.6-flash", "gemma-4"])
		os.remove(ruta)
		with mock.patch.object(ia, "_peticion", side_effect=Exception("red")):
			self.assertEqual(ia.ListadorModelos(ruta).obtener_modelos(["k"]), ia.MODELOS_RESERVA)

	def test_proveedores_de_tiresias(self):
		from tiresias.ai import providers

		falso = mock.Mock()
		falso.name = "Falso"
		falso.chat.return_value = providers.Message("assistant", "hecho")
		with mock.patch.object(providers, "getProvider", return_value=falso):
			cliente = ia.ClienteTiresias("anthropic")
			self.assertEqual(cliente.chat([ia.Turno("user", "a"), ia.Turno("model", "b")], "sis"), "hecho")
			self.assertEqual(cliente.nombre, "Falso")
		mensajes, sistema, _maximo = falso.chat.call_args[0]
		self.assertEqual([(m.role, m.text) for m in mensajes], [("user", "a"), ("assistant", "b")])
		self.assertEqual(sistema, "sis")
		with _Opciones(iaProveedor="local"):
			self.assertIsInstance(ia.cliente_actual(), ia.ClienteTiresias)
		with _Opciones(iaProveedor="google"):
			self.assertIsInstance(ia.cliente_actual(), ia.ClienteGoogle)

	def test_prompts(self):
		self.assertIn("2026-10-08", ia.prompt_informe("2026-10-08"))
		self.assertIn("POSIBLES SOLUCIONES", ia.prompt_informe("x"))
		p = ia.construir_prompt("¿por qué?", "sel", "consola", [{"nombre": "a.txt", "texto": "datos"}])
		self.assertIn("[CONSOLA - SELECCIÓN]\nsel", p)
		self.assertIn("[CONSOLA - COMPLETO]\nconsola", p)
		self.assertIn("[ARCHIVO: a.txt]\ndatos", p)
		self.assertTrue(p.endswith("Pregunta: ¿por qué?"))
		self.assertEqual(ia.construir_prompt("solo"), "solo")


# ====================================================================== complemento global
class TestComplemento(unittest.TestCase):
	def setUp(self):
		HABLADO.clear()
		self.c = cl.ComplementoConsoleLog()

	def tearDown(self):
		self.c.terminate()

	def test_ordenes(self):
		ordenes = ("script_mostrarVisorConsola", "script_copiarSalidaRapida", "script_clicDerechoConsola", "script_abrirLanzador")
		for nombre in ordenes:
			f = getattr(cl.ComplementoConsoleLog, nombre)
			self.assertTrue(f.__doc__, nombre)
			self.assertEqual(f.category, "Visor de consola", nombre)
			self.assertEqual(f.gestures, [], nombre)

	def test_panel_y_protector(self):
		from tiresias.gui import settings
		from tiresias.objects import terminal

		self.assertIn("consoleLog", settings._panels)
		# Desactivada de fábrica: Tiresias ya limita las ráfagas.
		self.assertFalse(self.c.protector.activo)
		with _Opciones(proteccionRafagas=True):
			self.c.aplicar_configuracion()
			self.assertTrue(self.c.protector.activo)
		self.c.terminate()
		self.assertNotIn("consoleLog", settings._panels)
		self.assertFalse(getattr(terminal.Terminal._speakNewText, "_consoleLogProtector", False))
		self.c = cl.ComplementoConsoleLog()

	def test_aplicar_configuracion(self):
		with _Opciones(proteccionRafagas=True, herramientasHabilitadas=["filtro_log"]):
			self.c.aplicar_configuracion()
			self.assertTrue(self.c.protector.activo)
			self.assertEqual(self.c.herramientas.listar_plugins_cargados(), ["filtro_log"])
		self.c.aplicar_configuracion()
		self.assertFalse(self.c.protector.activo)

	def test_procesado_con_perfil_y_regiones(self):
		d = deteccion.DestinoConsola(nombreApp="htop", titulo="htop")
		with _Opciones(condensarSimbolos=False):
			captura = self.c.procesar_texto_consola("\x1b[32m=====\x1b[0m cpu", d)
		self.assertEqual(captura.texto, "5 igual cpu")
		with _Opciones(habilitarProcesamiento=False):
			self.assertEqual(self.c.procesar_texto_consola("\x1b[1mx", d).texto, "\x1b[1mx")
		self.c.definiciones.agregar_definicion("s", dv.DefinicionVentana("S", 1, 1, 1, 80, dv.MODO_SILENCIO))
		captura = self.c.procesar_texto_consola("cabecera\ncuerpo", deteccion.DestinoConsola())
		self.assertEqual((captura.texto, captura.sin_filtrar), ("cuerpo", "cabecera\ncuerpo"))
		self.assertEqual(self.c.preparador(None)("a\nb").texto, "b")

	def test_vigilar_regiones(self):
		self.c.definiciones.agregar_definicion("m", dv.DefinicionVentana("Estado", 2, 2, 1, 80, dv.MODO_MONITORIZAR))
		self.c.vigilar_regiones("a\nuno", anunciar=False)
		HABLADO.clear()
		self.c.vigilar_regiones("a\nuno")
		self.assertEqual(HABLADO, [])
		self.c.vigilar_regiones("a\ndos")
		self.assertEqual(HABLADO, ["Cambio en Estado: dos"])

	def test_no_es_consola(self):
		destino = deteccion.DestinoConsola(clase="Notepad", nombreApp="notepad", hwnd=1)
		with mock.patch.object(self.c, "destino_actual", return_value=destino), mock.patch.object(self.c, "_bloqueada", return_value=False):
			self.c.script_mostrarVisorConsola(None)
			self.c.script_copiarSalidaRapida(None)
			self.c.script_clicDerechoConsola(None)
		self.assertEqual(HABLADO, ["Esta no es una ventana de consola.", "Esta no es una ventana de consola.", "La ventana enfocada no es una consola."])

	def test_apertura_reservada_y_errores(self):
		destino = deteccion.DestinoConsola(tipo="clasica", clase="ConsoleWindowClass", hwnd=77, pid=3)
		ident = deteccion.obtener_identidad(destino)

		class GestorFalso:
			def __init__(self):
				self.exito = self.error = None
				self.cancelado = False

			def leer_consola(self, destino, exito, error, emitir_beep=True, procesar=None):
				self.exito, self.error, self.procesar = exito, error, procesar
				return True

			def cancelar_lectura(self):
				self.cancelado = True

		g = GestorFalso()
		self.assertTrue(self.c.abrir_visor(destino, g))
		self.assertTrue(self.c.registro.esta_pendiente(ident))
		self.assertFalse(self.c.abrir_visor(destino, GestorFalso()))
		self.assertEqual(HABLADO[-1], "El visor de esta consola ya se está abriendo.")
		g.error("Acceso denegado")
		self.assertFalse(self.c.registro.esta_pendiente(ident))
		self.assertEqual(HABLADO[-1], "Acceso denegado")
		g2 = GestorFalso()
		self.c.abrir_visor(destino, g2)
		g2.exito(g2.procesar("   "))
		self.assertFalse(self.c.registro.esta_pendiente(ident))
		self.assertEqual(HABLADO[-1], "No se encontró texto en la consola")

	def test_copia_rapida(self):
		destino = deteccion.DestinoConsola(tipo="terminal", clase="CASCADIA_HOSTING_WINDOW_CLASS", hwnd=5)
		PORTAPAPELES.clear()

		def leer(destino, exito, error, emitir_beep=True, procesar=None):
			exito(procesar("\x1b[31mhola\x1b[0m"))
			return True

		with mock.patch.object(self.c._lector_copia, "leer_consola", side_effect=leer):
			self.assertTrue(self.c.copiar_consola(destino))
		self.assertEqual(PORTAPAPELES, ["hola"])
		self.assertEqual(HABLADO[-1], "Contenido de consola copiado")


# ====================================================================== interfaz (sin mostrar ventanas)
class TestInterfaz(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		import wx

		cls.wx = wx
		cls.app = wx.App.Get() or wx.App(False)
		cls._foco = mock.patch.object(wx.Window, "SetFocus", lambda self: None)
		cls._foco.start()

	@classmethod
	def tearDownClass(cls):
		cls._foco.stop()

	def setUp(self):
		HABLADO.clear()
		self.ventanas = []
		self.complemento = SimpleNamespace(
			herramientas=GestorHerramientas(SimpleNamespace(definiciones=dv.GestorDefinicionesVentana())),
			definiciones=dv.GestorDefinicionesVentana(),
			desregistrar_visor=mock.Mock(),
			vigilar_regiones=mock.Mock(),
			preparador=lambda destino: None,
		)
		self.complemento.herramientas.cargar_plugins(cfg.HERRAMIENTAS_DEFECTO)

	def tearDown(self):
		for v in self.ventanas:
			try:
				v.Destroy()
			except Exception:
				pass
		self.complemento.herramientas.descargar_plugins()

	def _visor(self, texto="uno\ndos\ntres"):
		from consoleLog.interfaz.visor import VisorConsola

		gestor = mock.Mock()
		gestor.leer_consola.return_value = True
		v = VisorConsola(self.complemento, texto, deteccion.DestinoConsola(tipo="clasica"), deteccion.IdentidadConsola("clasica", 1, 2), gestor, "cmd [2:1]")
		self.ventanas.append(v)
		return v

	def test_visor_menus_y_barra(self):
		v = self._visor()
		self.assertEqual(v.GetTitle(), "Visor de consola — cmd [2:1]")
		self.assertEqual(v.texto_control.GetValue(), "uno\ndos\ntres")
		etiquetas = [v.GetMenuBar().GetMenuLabelText(i) for i in range(v.GetMenuBar().GetMenuCount())]
		self.assertEqual(etiquetas, ["Archivo", "Edición", "Ver", "Plugins", "Ayuda"])
		plugins = v.GetMenuBar().GetMenu(3)
		categorias = [i.GetItemLabelText() for i in plugins.GetMenuItems()]
		self.assertIn("Inteligencia artificial", categorias)
		self.assertIn("Análisis", categorias)
		self.assertNotIn("Clic derecho en consola", str([i.GetItemLabelText() for m in plugins.GetMenuItems() if m.GetSubMenu() for i in m.GetSubMenu().GetMenuItems()]))
		self.assertEqual(v._barra_estado.GetStatusText(0), "Línea: 1 de 3")
		with _Opciones(categorizarHerramientas=False):
			v.aplicar_cambios()
			plano = [i.GetItemLabelText() for i in v.GetMenuBar().GetMenu(3).GetMenuItems()]
			self.assertIn("Calculadora Express", plano)

	def test_buscar_e_ir_a_linea(self):
		v = self._visor("alfa\nbeta ERROR\ngamma error")
		self.assertEqual(v.buscar("error", "adelante"), 10)
		self.assertEqual(v.buscar("error", "adelante"), 22)
		self.assertEqual(v.buscar("error", "adelante"), 10)
		self.assertEqual(v.buscar("error", "atras"), 22)
		self.assertEqual(v.buscar("zeta", "adelante"), -1)
		self.assertEqual(HABLADO[-1], "No se encontró: zeta")
		self.assertTrue(v.ir_a_linea("3"))
		self.assertEqual(v.texto_control.GetInsertionPoint(), v.texto_control.XYToPosition(0, 2))
		self.assertFalse(v.ir_a_linea("9"))
		self.assertFalse(v.ir_a_linea("x"))

	def test_seguimiento_conserva_la_posicion(self):
		v = self._visor("l1\nl2\nl3")
		t = v.texto_control
		t.SetInsertionPoint(1)
		with _Opciones(alertasHabilitadas=True, alertasVoz=True, alertasSonido=True):
			act = v.aplicar_captura("l1\nl2\nl3\nl4 FATAL fallo")
		self.assertTrue(act.es_agregado)
		self.assertEqual(t.GetValue(), "l1\nl2\nl3\nl4 FATAL fallo")
		self.assertEqual(t.GetInsertionPoint(), 1)
		self.assertIn("<sonido alerta>", HABLADO)
		self.assertIn("Alerta detectada: l4 FATAL fallo", HABLADO)
		HABLADO.clear()
		self.assertIsNone(v.aplicar_captura("l1\nl2\nl3\nl4 FATAL fallo"))
		self.assertEqual(HABLADO, [])
		# Al final se sigue el final.
		t.SetInsertionPointEnd()
		v.aplicar_captura("l1\nl2\nl3\nl4 FATAL fallo\nl5")
		self.assertEqual(t.GetInsertionPoint(), t.GetLastPosition())
		# Historial conservado al desplazarse el búfer.
		v.aplicar_captura("l4 FATAL fallo\nl5\nl6")
		self.assertEqual(t.GetValue(), "l1\nl2\nl3\nl4 FATAL fallo\nl5\nl6")
		self.complemento.vigilar_regiones.assert_called()

	def test_limite_del_documento(self):
		with _Opciones(limiteMilesCaracteres=0):
			v = self._visor("a")
		with mock.patch.object(cfg, "maxCaracteres", return_value=8):
			v.aplicar_captura("a\nbbbb\ncccc")
		self.assertEqual(v.texto_control.GetValue(), "cccc")

	def test_refresco_y_errores(self):
		v = self._visor()
		v._al_refrescar(None)
		self.assertTrue(v._lectura_activa)
		v._al_refrescar(None)
		self.assertEqual(v._gestor_lectores.leer_consola.call_count, 1)
		with mock.patch("tiresias.gui.messageBox") as caja:
			v._al_error_refresco("falló")
		caja.assert_called_once()
		self.assertFalse(v._lectura_activa)
		v.establecer_seguimiento(True)
		self.assertTrue(v._timer.IsRunning())
		self.assertIn("Seguimiento activado", HABLADO)
		with mock.patch("tiresias.gui.messageBox") as caja:
			v._al_error_refresco("falló")
		caja.assert_not_called()
		self.assertEqual(v._intervalo_actual, 1500)
		v.establecer_seguimiento(False)
		self.assertFalse(v._timer.IsRunning())

	def test_herramientas_desde_el_visor(self):
		from consoleLog.interfaz import dialogos

		v = self._visor("ERROR uno\nok")
		PORTAPAPELES.clear()
		self.assertTrue(v.ejecutar_herramienta("copiar_salida"))
		self.assertEqual(PORTAPAPELES, ["ERROR uno\nok"])
		with mock.patch.object(dialogos.DialogoLista, "ShowModal", return_value=self.wx.ID_CANCEL) as lista:
			self.assertEqual(v.ejecutar_herramienta("filtro_log"), ["ERROR uno"])
		lista.assert_called_once()
		with mock.patch.object(dialogos.DialogoTexto, "ShowModal", return_value=self.wx.ID_OK) as texto:
			v.ejecutar_herramienta("estadisticas_log")
		texto.assert_called_once()
		with mock.patch("tiresias.gui.messageBox") as caja:
			v.ejecutar_herramienta("json_beauty")
		caja.assert_called_once()

	def test_cierre(self):
		v = self._visor()
		v.cerrar_desde_complemento()
		self.ventanas.remove(v)
		self.complemento.desregistrar_visor.assert_called_once()
		v._gestor_lectores.cancelar_lectura.assert_called_once()

	def test_dialogos(self):
		from consoleLog.interfaz import dialogos, opciones
		from consoleLog.interfaz.chat_ia import ChatIADialog
		from consoleLog.interfaz.informe_ia import InformeIADialog
		from consoleLog.interfaz.lanzador_dialogo import LanzadorDialogo

		ajustes = opciones.AjustesDialog(None)
		self.ventanas.append(ajustes)
		self.assertEqual([ajustes.notebook.GetPageText(i) for i in range(ajustes.notebook.GetPageCount())], ["Visual", "Procesamiento", "Lanzador", "Plugins", "Alertas", "IA"])
		alertas = ajustes.paneles[4]
		alertas._patrones.SetValue("PANIC\n\nOOM")
		with _Opciones(alertasPatrones=list(cfg.DEFAULTS["alertasPatrones"])):
			alertas.onSave()
			self.assertEqual(cfg.patronesAlerta(), ["PANIC", "OOM"])
		panel = opciones.PanelConsoleLog(ajustes)
		self.assertGreater(len(panel._bound), 25)

		g = lanzador.GestorLanzador()
		g._consolas = {"cmd": lanzador.InfoConsola("CMD", "cmd", True, "cmd.exe")}
		with _Opciones(lanzadorRecordarUltima=True, lanzadorUltimaOpcion="cmd|1"):
			dlg = LanzadorDialogo(None, g, r"C:\x")
			self.ventanas.append(dlg)
			self.assertEqual(dlg.opcion_seleccionada().clave, "cmd|1")

		with _Opciones(iaProveedor="tiresias"):
			chat = ChatIADialog(None, mock.Mock(), "consola completa", "seleccion", usar_webview=False)
		self.ventanas.append(chat)
		self.assertTrue(chat.cb_seleccion.IsChecked())
		chat.cb_consola.SetValue(True)
		peticion = chat.construir_peticion("¿qué pasa?")
		self.assertIn("[CONSOLA - SELECCIÓN]\nseleccion", peticion)
		self.assertIn("[CONSOLA - COMPLETO]\nconsola completa", peticion)
		chat.agregar_mensaje("Tú", "**hola**")
		chat.agregar_mensaje("IA", "# Respuesta")
		self.assertEqual(chat.navegar(1), "Tú: **hola**")
		self.assertEqual(chat.navegar(1), "IA: # Respuesta")
		self.assertEqual(chat.navegar(1), "Tú: **hola**")
		self.assertIn("hola", chat.vista.control.GetValue())

		informe = InformeIADialog(None, "# Resumen\n\n- punto", usar_webview=False)
		self.ventanas.append(informe)
		self.assertIn("Resumen", informe.vista.control.GetValue())

		j = dialogos.DialogoJSON(None, ['{"a": 1}', "[2]"])
		self.ventanas.append(j)
		j._ir(1)
		self.assertEqual(j.txt.GetValue(), "[2]")
		d = dialogos.DefinicionesDialog(None, dv.GestorDefinicionesVentana(), "texto")
		self.ventanas.append(d)
		self.assertEqual(d.lista.GetCount(), 4)


if __name__ == "__main__":
	unittest.main()
