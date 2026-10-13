"""Pruebas del complemento de la tienda «Audiocinemateca».

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_complemento_audiocinemateca -v``

No usan la red ni credenciales reales: las peticiones se simulan. El
reproductor se prueba con BASS en el dispositivo 0 («sin sonido»), así que
no suena nada por los altavoces. Las ventanas se crean ocultas (nunca se
muestran) para comprobar su lógica.
"""

from __future__ import annotations

import bz2
import gzip
import importlib.util
import io
import json
import math
import os
import random
import shutil
import struct
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import warnings
import wave
from unittest import mock

# Los HTTPError simulados no tienen respuesta abierta que cerrar.
warnings.filterwarnings("ignore", category=ResourceWarning, message="Implicitly cleaning up <HTTPError")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_audiocinemateca_")
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]
else:
	_TMP = paths._dataDirForTests  # type: ignore[attr-defined]

from tiresias import queue_handler  # noqa: E402
from tiresias.config import conf  # noqa: E402

ADDON = os.path.join(ROOT, "complementos_tienda", "audiocinemateca")
PKG = "tiresias_addon_audiocinemateca_pruebas"


def _cargarPaquete():
	"""Carga el complemento como lo hace Tiresias (paquete dentro de globalPlugins)."""
	for name, path in ((PKG, ADDON), (PKG + ".globalPlugins", os.path.join(ADDON, "globalPlugins"))):
		if name not in sys.modules:
			m = types.ModuleType(name)
			m.__path__ = [path]  # type: ignore[attr-defined]
			sys.modules[name] = m
	full = PKG + ".globalPlugins.audiocinemateca"
	if full in sys.modules:
		return sys.modules[full]
	carpeta = os.path.join(ADDON, "globalPlugins", "audiocinemateca")
	spec = importlib.util.spec_from_file_location(full, os.path.join(carpeta, "__init__.py"), submodule_search_locations=[carpeta])
	mod = importlib.util.module_from_spec(spec)
	sys.modules[full] = mod
	spec.loader.exec_module(mod)
	return mod


ac = _cargarPaquete()
from importlib import import_module  # noqa: E402

ajustes = import_module(ac.__name__ + ".ajustes")
bass = import_module(ac.__name__ + ".bass")
red = import_module(ac.__name__ + ".red")
catalogo = import_module(ac.__name__ + ".catalogo")
almacen = import_module(ac.__name__ + ".almacen")
credenciales = import_module(ac.__name__ + ".credenciales")
descargas = import_module(ac.__name__ + ".descargas")
reproductor = import_module(ac.__name__ + ".reproductor")
control = import_module(ac.__name__ + ".control")
panel = import_module(ac.__name__ + ".panel")

ajustes.registrarDefectos()


# ---------------------------------------------------------------------- utilidades
class Voz:
	"""Recoge lo que el complemento manda decir (sin sintetizador)."""

	def __init__(self) -> None:
		self.mensajes: list[str] = []

	def __enter__(self):
		def queue(func, *args, **kw):
			if args:
				self.mensajes.append(args[0])

		def later(ms, func, *args, **kw):
			if args:
				self.mensajes.append(args[0])
			return 0

		self._p1 = mock.patch.object(queue_handler, "queueFunction", side_effect=queue)
		self._p2 = mock.patch.object(queue_handler, "callLater", side_effect=later)
		self._p1.start()
		self._p2.start()
		return self

	def __exit__(self, *exc):
		self._p1.stop()
		self._p2.stop()

	@property
	def ultimo(self) -> str:
		return self.mensajes[-1] if self.mensajes else ""


def _carpeta() -> str:
	return tempfile.mkdtemp(dir=_TMP)


def _wav(ruta: str, segundos: float = 3.0, freq: int = 22050) -> str:
	with wave.open(ruta, "wb") as w:
		w.setnchannels(1)
		w.setsampwidth(2)
		w.setframerate(freq)
		w.writeframes(b"".join(struct.pack("<h", int(2000 * math.sin(i / 8))) for i in range(int(freq * segundos))))
	return ruta


def _ficha(**kw) -> dict:
	base = {
		"id": "x", "anio": "2000", "genero": "Drama", "pais": "España", "director": "Nadie",
		"guion": "G", "musica": "M", "fotografia": "F", "reparto": "Actor Uno, Actriz Dos",
		"productora": "P", "narracion": "Narradora", "duracion": "90", "idioma": "1",
		"filmaffinity": "", "sinopsis": "Una historia.",
	}
	base.update(kw)
	return base


def catalogoEjemplo() -> dict:
	return {
		"peliculas": [
			_ficha(id="p1", Titulo="El último tren a Gun Hill", anio="1959", genero="Western", director="John Sturges",
				filmaffinity="https://www.filmaffinity.com/es/film1.html", partes="1", enlaces=["system/files/peliculas/tren.mp3"]),
			_ficha(id="p2", Titulo="Ágora", anio="2009", director="Alejandro Amenábar", idioma="2", partes="2",
				enlaces=["system/files/peliculas/agora1.mp3", "system/files/peliculas/agora2.mp3"]),
			_ficha(id="p3", Titulo="¡Bienvenido, Mister Marshall!", anio="1953", genero="Comedia", director="Luis García Berlanga",
				partes="1", enlaces=["system/files/peliculas/marshall%20final.mp3"]),
		],
		"series": [
			_ficha(id="s1", titulo="Cuéntame cómo pasó", temporadas=3, capitulos={
				"1": [{"capitulo": "1", "titulo": "Piloto", "enlace": "system/files/series/c1x1.mp3"},
					{"capitulo": "2", "titulo": "Segundo", "enlace": "system/files/series/c1x2.mp3"}],
				"10": [{"capitulo": "1", "titulo": "Diez", "enlace": "system/files/series/c10x1.mp3"}],
				"2": [{"capitulo": "1", "titulo": "Vuelta", "enlace": "system/files/series/c2x1.mp3"}],
			}),
		],
		"documentales": [_ficha(id="d1", titulo="La Tierra desde el cielo", enlace="system/files/doc/tierra.mp3")],
		"cortometrajes": [_ficha(id="c1", titulo="El columpio", enlace="system/files/cortos/columpio.mp3")],
	}


def escribirCatalogo(carpeta: str, version: dict | None = None) -> None:
	with open(os.path.join(carpeta, "catalogo.json"), "w", encoding="utf-8") as f:
		json.dump(catalogoEjemplo(), f, ensure_ascii=False)
	with open(os.path.join(carpeta, "version.json"), "w", encoding="utf-8") as f:
		json.dump(version or {"year": 2026, "mon": 3, "mday": 5, "hours": 10, "minutes": 30, "seconds": 0}, f)


class RespuestaFalsa(io.BytesIO):
	"""Respuesta de ``urlopen`` simulada."""

	def __init__(self, datos: bytes, status: int = 200, longitud: bool = True) -> None:
		super().__init__(datos)
		self.status = status
		self.headers = {"Content-Length": str(len(datos))} if longitud else {}

	def __enter__(self):
		return self

	def __exit__(self, *exc):
		self.close()


def silencioso() -> reproductor.Reproductor:
	"""Reproductor en el dispositivo 0 de BASS (sin sonido)."""
	r = reproductor.Reproductor(numeroDispositivo=0)
	if not r.disponible:
		raise unittest.SkipTest("BASS no disponible: " + r.error)
	return r


# ====================================================================== estructura
class TestEstructura(unittest.TestCase):
	def test_manifiesto(self):
		with open(os.path.join(ADDON, "manifest.json"), encoding="utf-8-sig") as f:
			m = json.load(f)
		self.assertEqual(m["id"], "audiocinemateca")
		self.assertEqual(m["version"], "1.0.1")
		self.assertEqual(m["author"], "Héctor J. Benítez Corredera <xebolax@gmail.com>")
		self.assertEqual(m["url"], "https://github.com/nvda-es/audiocinemateca-para-nvda")
		self.assertEqual(m["minApiVersion"], "1.0")
		self.assertEqual(m["lastTestedApiVersion"], "1.0")
		self.assertTrue(m["changelog"].startswith("1.0.1 (seguridad)"))
		self.assertIn("primera versión para Tiresias", m["changelog"])
		self.assertGreater(len(m["description"]), 200)

	def test_archivos(self):
		for rel in ("doc/es/readme.html", "lib/x64/bass.dll", "lib/LICENCIA_BASS.txt"):
			self.assertTrue(os.path.isfile(os.path.join(ADDON, rel)), rel)
		# Solo el DLL que se usa; nada de sound_lib ni .pyd.
		self.assertEqual(os.listdir(os.path.join(ADDON, "lib", "x64")), ["bass.dll"])
		for raiz, _d, archivos in os.walk(ADDON):
			for a in archivos:
				self.assertFalse(a.endswith((".pyd", ".pyc")), a)
				self.assertNotIn("sound_lib", raiz)

	def test_sin_bibliotecas_de_terceros(self):
		carpeta = os.path.join(ADDON, "globalPlugins", "audiocinemateca")
		for nombre in os.listdir(carpeta):
			if nombre.endswith(".py"):
				with open(os.path.join(carpeta, nombre), encoding="utf-8") as f:
					texto = f.read()
				for prohibido in ("import sound_lib", "from sound_lib", "import requests", "import winsound", "addonHandler", "globalPluginHandler", "import ui\n"):
					self.assertNotIn(prohibido, texto, f"{prohibido} en {nombre}")

	def test_readme(self):
		with open(os.path.join(ADDON, "doc", "es", "readme.html"), encoding="utf-8") as f:
			html = f.read()
		for texto in ("lang=\"es\"", "Alt+8", "F12", "Mayúsculas+F10", "Control+F", "Ecualizador", "Temporizador de sueño",
			"Descargas", "Estadísticas", "un4seen", "GNU", "Héctor J. Benítez Corredera", "Gestos de entrada"):
			self.assertIn(texto, html)


# ====================================================================== ajustes
class TestAjustes(unittest.TestCase):
	def setUp(self):
		ajustes.restaurarDefecto()

	def test_defectos_como_el_original(self):
		self.assertEqual(ajustes.get("volumen"), 50)
		self.assertEqual(ajustes.LISTA_VELOCIDAD[ajustes.get("velocidad")], "1.0")
		self.assertEqual(ajustes.segundosAtrasar(), 15)
		self.assertEqual(ajustes.segundosAdelantar(), 30)
		self.assertEqual(ajustes.cantidadResultados(), 10)
		self.assertTrue(ajustes.hablarActivo())
		self.assertFalse(ajustes.get("ecualizadorActivo"))
		self.assertEqual(len(ajustes.LISTA_FILTROS), 12)
		self.assertEqual(len(ajustes.CAMPOS_FILTRO), 12)
		self.assertEqual(ajustes.EQ_BANDAS, [80, 230, 910, 3600, 14000])
		self.assertEqual([n for n, _v in ajustes.EQ_PRESETS], ["Normal", "Voz clara", "Cine", "Música", "Graves", "Agudos"])
		self.assertEqual([m for _n, m in ajustes.TEMPORIZADOR_OPCIONES], [0, 15, 30, 45, 60, 90, 120, -1])

	def test_put_y_validacion(self):
		ajustes.put("volumen", 77)
		self.assertEqual(conf[ajustes.SECCION]["volumen"], 77)
		ajustes.put("volumen", 500)
		self.assertEqual(ajustes.get("volumen"), 100)
		ajustes.put("velocidad", 99)
		self.assertEqual(ajustes.get("velocidad"), len(ajustes.LISTA_VELOCIDAD) - 1)
		ajustes.put("ecualizadorValores", [1, 2])
		self.assertEqual(ajustes.get("ecualizadorValores"), [0, 0, 0, 0, 0])
		ajustes.put("ecualizadorValores", [99, -99, 3, 0, 0])
		self.assertEqual(ajustes.get("ecualizadorValores"), [15, -15, 3, 0, 0])

	def test_restaurar(self):
		ajustes.put("hablar", False)
		ajustes.put("adelantar", 7)
		ajustes.restaurarDefecto()
		self.assertTrue(ajustes.get("hablar"))
		self.assertEqual(ajustes.get("adelantar"), 3)

	def test_carpetas(self):
		# Con toda la batería, la carpeta de datos puede ser la de otra prueba.
		self.assertEqual(ajustes.dirDatos(), os.path.join(paths.DATA_DIR, "addonsData", "audiocinemateca"))
		self.assertTrue(ajustes.rutaDocumentacion().endswith(os.path.join("doc", "es", "readme.html")))
		self.assertEqual(ajustes.raizComplemento(), ADDON)


# ====================================================================== credenciales
class TestCredenciales(unittest.TestCase):
	def tearDown(self):
		credenciales.borrar()

	def test_ida_y_vuelta_cifrada(self):
		credenciales.guardar("usuaria@ejemplo.es", "clave ñ:á/1")
		self.assertTrue(ajustes.hayCredenciales())
		with open(credenciales._ruta(), "rb") as f:
			crudo = f.read()
		self.assertNotIn(b"usuaria", crudo)
		self.assertNotIn("clave ñ".encode("utf-8"), crudo)
		ajustes.estado.usuario = ajustes.estado.contrasena = ""
		self.assertEqual(credenciales.cargar(), ("usuaria@ejemplo.es", "clave ñ:á/1"))

	def test_borrar_y_danado(self):
		credenciales.guardar("u", "c")
		credenciales.borrar()
		self.assertFalse(ajustes.hayCredenciales())
		self.assertEqual(credenciales.cargar(), ("", ""))
		with open(credenciales._ruta(), "wb") as f:
			f.write(b"basura")
		self.assertEqual(credenciales.cargar(), ("", ""))


# ====================================================================== red
class TestRed(unittest.TestCase):
	def test_cabecera(self):
		self.assertEqual(red.cabeceraAutenticacion("usuario", "clave"), "Basic dXN1YXJpbzpjbGF2ZQ==")

	def test_nombres_y_urls(self):
		self.assertEqual(red.nombreArchivoUrl("https://a.com/x/mi%20pel%C3%ADcula.mp3"), "mi película.mp3")
		self.assertTrue(red.esUrl("https://www.filmaffinity.com/es/film1.html"))
		self.assertFalse(red.esUrl("sin enlace"))
		self.assertFalse(red.esUrl(""))

	def test_comparar_versiones(self):
		v1 = {"year": 2026, "mon": 3, "mday": 5, "hours": 10, "minutes": 30, "seconds": 0}
		v2 = dict(v1, mday=6)
		self.assertTrue(red.compararVersiones(v1, v2))
		self.assertFalse(red.compararVersiones(v2, v1))
		self.assertFalse(red.compararVersiones(v1, v1))
		self.assertTrue(red.compararVersiones(None, v1))
		self.assertFalse(red.compararVersiones(v1, None))
		self.assertEqual(red.formatearVersion(v1), "5 de marzo de 2026, 10:30")
		self.assertEqual(red.formatearVersion(None), "desconocida")

	def test_descargar_con_autenticacion_y_progreso(self):
		datos = os.urandom(300 * 1024)
		peticiones = []

		def urlopen(req, timeout=None):
			peticiones.append(req)
			return RespuestaFalsa(datos)

		destino = os.path.join(_carpeta(), "a.mp3")
		progreso = []
		with mock.patch.object(red.urllib.request, "urlopen", side_effect=urlopen):
			red.descargar("https://audiocinemateca.com/system/files/a.mp3", destino, "usuario", "clave", progreso.append)
		with open(destino, "rb") as f:
			self.assertEqual(f.read(), datos)
		self.assertEqual(peticiones[0].get_header("Authorization"), "Basic dXN1YXJpbzpjbGF2ZQ==")
		self.assertEqual(progreso[-1], 100.0)
		self.assertFalse(os.path.exists(destino + ".part"))

	def test_descargar_cancelada_e_incompleta(self):
		destino = os.path.join(_carpeta(), "b.mp3")
		with mock.patch.object(red.urllib.request, "urlopen", return_value=RespuestaFalsa(b"x" * 500000)):
			with self.assertRaises(red.Cancelado):
				red.descargar("https://a/b.mp3", destino, cancelado=lambda: True)
		self.assertFalse(os.path.exists(destino) or os.path.exists(destino + ".part"))
		corta = RespuestaFalsa(b"x" * 10)
		corta.headers = {"Content-Length": "100"}
		with mock.patch.object(red.urllib.request, "urlopen", return_value=corta):
			with self.assertRaises(OSError):
				red.descargar("https://a/b.mp3", destino)
		self.assertFalse(os.path.exists(destino))

	def test_verificar_login(self):
		with mock.patch.object(red.urllib.request, "urlopen", return_value=RespuestaFalsa(b"ok")):
			self.assertEqual(red.verificarLogin("u", "c"), (True, None))
		error = urllib.error.HTTPError(ajustes.URL_VERSION, 401, "Unauthorized", {}, None)
		with mock.patch.object(red.urllib.request, "urlopen", side_effect=error):
			ok, msg = red.verificarLogin("u", "mala")
		self.assertFalse(ok)
		self.assertIn("401", msg)
		with mock.patch.object(red.urllib.request, "urlopen", side_effect=urllib.error.URLError("sin red")):
			ok, msg = red.verificarLogin("u", "c")
		self.assertFalse(ok)
		self.assertIn("No se pudo conectar", msg)

	def test_hay_internet(self):
		with mock.patch.object(red.socket, "create_connection", side_effect=OSError):
			self.assertFalse(red.hayInternet())
		with mock.patch.object(red.socket, "create_connection", return_value=mock.MagicMock()):
			self.assertTrue(red.hayInternet())

	def test_descomprimir(self):
		c = _carpeta()
		datos = json.dumps(catalogoEjemplo()).encode("utf-8") * 50
		with open(os.path.join(c, "c.bz2"), "wb") as f:
			f.write(bz2.compress(datos))
		with open(os.path.join(c, "v.gz"), "wb") as f:
			f.write(gzip.compress(b'{"year": 2026}'))
		progreso = []
		red.descomprimirBz2(os.path.join(c, "c.bz2"), os.path.join(c, "c.json"), progreso.append)
		red.descomprimirGz(os.path.join(c, "v.gz"), os.path.join(c, "v.json"))
		with open(os.path.join(c, "c.json"), "rb") as f:
			self.assertEqual(f.read(), datos)
		with open(os.path.join(c, "v.json"), "rb") as f:
			self.assertEqual(json.loads(f.read()), {"year": 2026})
		self.assertTrue(progreso and progreso[-1] == 100.0)
		with open(os.path.join(c, "malo.bz2"), "wb") as f:
			f.write(b"no es bz2")
		with self.assertRaises(Exception):
			red.descomprimirBz2(os.path.join(c, "malo.bz2"), os.path.join(c, "malo.json"))
		self.assertFalse(os.path.exists(os.path.join(c, "malo.json")))

	def test_mensajes_de_error(self):
		self.assertIn("usuario o la contraseña", red.mensajeError(urllib.error.HTTPError("u", 401, "x", {}, None)))
		self.assertIn("404", red.mensajeError(urllib.error.HTTPError("u", 404, "x", {}, None)))
		self.assertEqual(red.mensajeError(red.Cancelado()), "Operación cancelada.")
		self.assertEqual(red.mensajeError(None), "No se pudo completar la operación.")


# ====================================================================== catálogo
class TestCatalogo(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.carpeta = _carpeta()
		escribirCatalogo(cls.carpeta)
		cls.cat = catalogo.GestorCatalogo(cls.carpeta)
		assert cls.cat.cargar()

	def test_carga_y_orden(self):
		pel = self.cat.coleccion("peliculas")
		self.assertEqual(len(pel), 3)
		# Lo último que se añadió, primero (como el original).
		self.assertEqual(pel.titulos()[0], "¡Bienvenido, Mister Marshall!")
		self.assertEqual(pel.ultimos(2)[1]["id"], "p2")
		self.assertEqual(self.cat.version["year"], 2026)
		self.assertEqual(self.cat.buscarId("series", "s1")["titulo"], "Cuéntame cómo pasó")
		self.assertIsNone(self.cat.buscarId("series", "nada"))

	def test_catalogo_danado(self):
		c = _carpeta()
		with open(os.path.join(c, "catalogo.json"), "w") as f:
			f.write("{roto")
		g = catalogo.GestorCatalogo(c)
		self.assertFalse(g.cargar())
		self.assertFalse(g.cargado)

	def test_busqueda_titulo_sin_tildes_ni_puntuacion(self):
		pel = self.cat.coleccion("peliculas")
		self.assertEqual([d["id"] for d in pel.buscar("agora", "titulo")], ["p2"])
		self.assertEqual([d["id"] for d in pel.buscar("bienvenido mister", "titulo")], ["p3"])
		self.assertEqual([d["id"] for d in pel.buscar("el tren", "titulo")], ["p1"])
		# Falta una palabra pero está dentro de otra («gun hil» ⊂ «hill»).
		self.assertEqual([d["id"] for d in pel.buscar("tren gun hil", "titulo")], ["p1"])
		self.assertEqual(pel.buscar("inexistente", "titulo"), [])

	def test_busqueda_por_otros_campos(self):
		pel = self.cat.coleccion("peliculas")
		self.assertEqual([d["id"] for d in pel.buscar("amenabar", "director")], ["p2"])
		self.assertEqual([d["id"] for d in pel.buscar("1959", "anio")], ["p1"])
		self.assertEqual([d["id"] for d in pel.buscar("comedia", "genero")], ["p3"])
		self.assertEqual(len(pel.buscar("historia", "sinopsis")), 3)

	def test_busqueda_global_y_aleatorio(self):
		res = self.cat.buscarGlobal("el")
		cats = {c for _d, c in res}
		self.assertIn("cortometrajes", cats)
		self.assertIn("peliculas", cats)
		cat, datos = self.cat.aleatorio(random.Random(3))
		self.assertIn(cat, ajustes.CLAVES_CATEGORIA)
		self.assertIn(datos, self.cat.coleccion(cat).elementos)

	def test_temporadas_ordenadas(self):
		temporadas = catalogo.episodiosPorTemporada(self.cat.buscarId("series", "s1")["capitulos"])
		self.assertEqual([t for t, _e in temporadas], ["1", "2", "10"])
		self.assertEqual(temporadas[0][1][1]["titulo"], "Segundo")

	def test_fichas(self):
		p2 = self.cat.buscarId("peliculas", "p2")
		texto = catalogo.textoFicha(p2, "peliculas")
		self.assertIn("Título:\nÁgora", texto)
		self.assertIn("Duración:\n90 minutos", texto)
		self.assertIn("Idioma:\nEspañol latino", texto)
		serie = catalogo.textoFicha(self.cat.buscarId("series", "s1"), "series")
		self.assertIn("90 minutos por episodio", serie)
		self.assertIn("Temporadas:\n3", serie)
		self.assertIn("Idioma:\nEspañol\n", serie)
		copia = catalogo.textoCopiar(self.cat.buscarId("series", "s1"), "series")
		self.assertIn("Temporadas: 3", copia)
		self.assertTrue(copia.endswith(ajustes.URL_WEB))
		self.assertEqual(catalogo.enlaces(p2, "peliculas"), ["system/files/peliculas/agora1.mp3", "system/files/peliculas/agora2.mp3"])
		self.assertEqual(catalogo.enlaces(self.cat.buscarId("documentales", "d1"), "documentales"), ["system/files/doc/tierra.mp3"])
		self.assertEqual(catalogo.urlContenido("system/files/a.mp3"), "https://audiocinemateca.com/system/files/a.mp3")
		self.assertEqual(catalogo.urlContenido("https://otra/a.mp3"), "https://otra/a.mp3")


# ====================================================================== datos del usuario
class TestAlmacen(unittest.TestCase):
	def setUp(self):
		self.c = _carpeta()

	def test_favoritos(self):
		f = almacen.GestorFavoritos(self.c)
		f.agregar("peliculas", "p1")
		f.agregar("peliculas", "p1")
		self.assertEqual(f.obtener("peliculas"), ["p1"])
		self.assertTrue(f.alternar("series", "s1"))
		self.assertFalse(f.alternar("series", "s1"))
		self.assertEqual(almacen.GestorFavoritos(self.c).obtener("peliculas"), ["p1"])
		f.vaciar()
		self.assertEqual(almacen.GestorFavoritos(self.c).obtener("peliculas"), [])

	def test_visualizacion(self):
		v = almacen.GestorVisualizacion(self.c)
		v.guardarPosicion("https://a/b.mp3", 125.5)
		self.assertEqual(almacen.GestorVisualizacion(self.c).obtenerPosicion("https://a/b.mp3"), 125.5)
		self.assertIsNone(v.obtenerPosicion("https://a/otra.mp3"))
		with open(v.ruta, encoding="utf-8") as f:
			self.assertNotIn("https", f.read())
		v.borrarPosicion("https://a/b.mp3")
		self.assertIsNone(v.obtenerPosicion("https://a/b.mp3"))

	def test_historial(self):
		h = almacen.GestorHistorial(self.c)
		h.registrar("p1", "peliculas", "Uno")
		h.registrar("s1", "series", "Dos")
		h.registrar("p1", "peliculas", "Uno")
		self.assertEqual([e["id"] for e in h.obtener()], ["p1", "s1"])
		self.assertEqual([e["id"] for e in h.obtenerPorCategoria("series")], ["s1"])
		for i in range(250):
			h.registrar(str(i), "documentales", str(i))
		self.assertEqual(len(almacen.GestorHistorial(self.c).datos), 200)

	def test_historial_busqueda(self):
		h = almacen.GestorHistorialBusqueda(self.c)
		h.registrar("agora", "Título", 0, 0)
		h.registrar("agora", "Título", 0, 0)
		h.registrar("amenabar", "Director", 0, 4)
		self.assertEqual([e["texto"] for e in h.obtener()], ["amenabar", "agora"])
		self.assertEqual(h.obtener(categoria=1), [])
		for i in range(30):
			h.registrar(f"t{i}", "Global", -1)
		self.assertEqual(len(h.datos), 20)

	def test_listas(self):
		l = almacen.GestorListas(self.c)
		self.assertTrue(l.crearLista("Pendientes"))
		self.assertFalse(l.crearLista("Pendientes"))
		self.assertTrue(l.crearLista("Vistas"))
		self.assertTrue(l.agregarItem("Pendientes", "p1", "peliculas", "Uno"))
		self.assertFalse(l.agregarItem("Pendientes", "p1", "peliculas", "Uno"))
		self.assertTrue(l.estaEnLista("Pendientes", "p1", "peliculas"))
		self.assertTrue(l.renombrarLista("Pendientes", "Por ver"))
		self.assertEqual(l.nombres(), ["Por ver", "Vistas"])
		self.assertFalse(l.renombrarLista("Por ver", "Vistas"))
		self.assertTrue(l.quitarItem("Por ver", "p1", "peliculas"))
		self.assertEqual(l.items("Por ver"), [])
		self.assertTrue(l.eliminarLista("Vistas"))
		self.assertEqual(almacen.GestorListas(self.c).nombres(), ["Por ver"])

	def test_estadisticas(self):
		e = almacen.GestorEstadisticas(self.c)
		self.assertIsNone(e.resumen()["categoria_favorita"])
		e.registrarReproduccion("p1", "peliculas", "Uno")
		e.registrarReproduccion("p1", "peliculas", "Uno")
		e.registrarReproduccion("s1", "series", "Dos")
		e.acumularTiempo(3700)
		r = almacen.GestorEstadisticas(self.c).resumen()
		self.assertEqual(r["total_reproducciones"], 3)
		self.assertEqual(r["categoria_favorita"], "peliculas")
		self.assertEqual(r["mas_reproducido"]["titulo"], "Uno")
		self.assertEqual(r["tiempo_total_segundos"], 3700)
		self.assertEqual([i["titulo"] for i in e.top()], ["Uno", "Dos"])

	def test_archivo_danado(self):
		with open(os.path.join(self.c, "favoritos.json"), "w") as f:
			f.write("[1, 2")
		self.assertEqual(almacen.GestorFavoritos(self.c).obtener("series"), [])


# ====================================================================== descargas
class TestDescargas(unittest.TestCase):
	def _esperar(self, g, n=1):
		fin = time.time() + 5
		while len(g.obtenerFinalizadas()) < n and time.time() < fin:
			time.sleep(0.02)

	def test_completada_y_local(self):
		c = _carpeta()
		avisos = []

		def falsa(url, destino, u, p, progreso, cancelado):
			progreso(50)
			with open(destino, "wb") as f:
				f.write(b"mp3")
			return destino

		g = descargas.GestorDescargas(c, credenciales=lambda: ("u", "c"), avisar=avisos.append)
		with mock.patch.object(descargas.red, "descargar", side_effect=falsa):
			item = g.encolar("https://a.com/x/tren%20final.mp3", c, "El tren")
			self._esperar(g)
		self.assertEqual(item.estado, descargas.COMPLETADA)
		self.assertEqual(item.nombreArchivo, "tren final.mp3")
		self.assertEqual(avisos, ["Descarga completada: El tren"])
		self.assertEqual(g.buscarDescargaLocal("https://a.com/x/tren%20final.mp3"), os.path.join(c, "tren final.mp3"))
		g2 = descargas.GestorDescargas(c)
		self.assertEqual(len(g2.obtenerRegistro()), 1)
		os.remove(os.path.join(c, "tren final.mp3"))
		self.assertIsNone(g2.buscarDescargaLocal("https://a.com/x/tren%20final.mp3"))

	def test_error_cancelada_y_reintento(self):
		c = _carpeta()
		g = descargas.GestorDescargas(c, credenciales=lambda: ("u", "c"))
		with mock.patch.object(descargas.red, "descargar", side_effect=urllib.error.HTTPError("u", 401, "x", {}, None)):
			item = g.encolar("https://a/1.mp3", c, "Uno")
			self._esperar(g)
		self.assertEqual(item.estado, descargas.ERROR)
		self.assertIn("401", item.error)
		evento = threading.Event()

		def lenta(url, destino, u, p, progreso, cancelado):
			evento.set()
			while not cancelado():
				time.sleep(0.01)
			raise red.Cancelado()

		with mock.patch.object(descargas.red, "descargar", side_effect=lenta):
			item2 = g.encolar("https://a/2.mp3", c, "Dos")
			pendiente = g.encolar("https://a/3.mp3", c, "Tres")
			evento.wait(2)
			self.assertEqual(len(g.obtenerActivas()), 2)
			self.assertTrue(g.quitarPendiente(pendiente))
			self.assertTrue(g.cancelarActual())
			self._esperar(g, 3)
		self.assertEqual(item2.estado, descargas.CANCELADA)
		self.assertEqual(pendiente.estado, descargas.CANCELADA)
		with mock.patch.object(descargas.red, "descargar", return_value=None):
			nuevo = g.reintentar(item)
			self.assertIsNotNone(nuevo)
			self._esperar(g, 3)
		self.assertNotIn(item, g.obtenerFinalizadas())
		g.limpiarFinalizadas()
		self.assertEqual(g.obtenerFinalizadas(), [])


# ====================================================================== BASS y reproductor
class TestReproductor(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.wav = _wav(os.path.join(_carpeta(), "tono ñ.wav"))

	def test_version_y_dispositivos(self):
		self.assertTrue(bass.version().startswith("2.4"))
		for numero, nombre, _pred in bass.dispositivos():
			self.assertGreater(numero, 0)
			self.assertTrue(nombre)

	def test_ciclo_completo(self):
		r = silencioso()
		try:
			self.assertEqual(r.estado(), reproductor.DETENIDO)
			self.assertTrue(r.cargarArchivo(self.wav))
			self.assertAlmostEqual(r.getDuracion(), 3.0, places=1)
			r.setVolumen(30)
			self.assertAlmostEqual(r._flujo.getAtributo(bass.BASS_ATTRIB_VOL), 0.3, places=2)
			r.setVelocidad(1.5)
			self.assertAlmostEqual(r._flujo.getAtributo(bass.BASS_ATTRIB_FREQ), 22050 * 1.5, places=0)
			r.setVelocidad(9)
			self.assertEqual(r.getVelocidad(), 3.0)
			r.reproducir()
			self.assertEqual(r.estado(), reproductor.REPRODUCIENDO)
			self.assertTrue(r.estaActivo())
			self.assertEqual(r.reproducirPausar(), reproductor.PAUSADO)
			self.assertEqual(r.reproducirPausar(), reproductor.REPRODUCIENDO)
			r.pausar()
			r.setPosicion(1.0)
			self.assertAlmostEqual(r.getPosicion(), 1.0, places=1)
			r.adelantar(30)
			self.assertAlmostEqual(r.getPosicion(), r.getDuracion() - 0.1, delta=0.05)
			r.atrasar(60)
			self.assertEqual(r.getPosicion(), 0.0)
			r.aplicarEcualizador(list(zip(ajustes.EQ_BANDAS, [3, -3, 0, 6, 15])))
			self.assertEqual(r.numeroEfectos(), 5)
			r.aplicarEcualizador([(910, 2)])
			self.assertEqual(r.numeroEfectos(), 1)
			r.limpiarEcualizador()
			self.assertEqual(r.numeroEfectos(), 0)
			r.detener()
			self.assertFalse(r.estaActivo())
			self.assertEqual(r.url, "")
			self.assertFalse(r.cargarArchivo(self.wav + ".no"))
			self.assertTrue(r.error)
		finally:
			r.liberar()

	def test_formato_tiempo(self):
		self.assertEqual(reproductor.formatoTiempo(65), "01:05")
		self.assertEqual(reproductor.formatoTiempo(3725.9), "01:02:05")
		self.assertEqual(reproductor.formatoTiempo(-3), "00:00")


# ====================================================================== controlador
class TestControlador(unittest.TestCase):
	def setUp(self):
		ajustes.restaurarDefecto()
		self.carpeta = _carpeta()
		escribirCatalogo(self.carpeta)
		self.c = control.Controlador(self.carpeta, avisar=lambda m: None)
		self.c._reproductor = silencioso()
		self.c.catalogo.cargar()
		self.wav = _wav(os.path.join(self.carpeta, "tren.mp3.wav"))

	def tearDown(self):
		self.c.terminar()
		credenciales.borrar()

	def test_cabeceras(self):
		credenciales.guardar("usuario", "clave")
		self.assertEqual(self.c.cabecerasAutenticacion(), {"Authorization": "Basic dXN1YXJpbzpjbGF2ZQ=="})
		credenciales.borrar()
		self.assertEqual(self.c.cabecerasAutenticacion(), {})

	def test_reproduce_descarga_local_y_reanuda(self):
		url = catalogo.urlContenido("system/files/peliculas/tren.mp3")
		self.c.descargas.registro.append({"titulo": "Tren", "archivo": "x", "ruta": self.wav, "url": url})
		ok, pos, err = self.c.prepararContenido("system/files/peliculas/tren.mp3", "El tren", "p1", "peliculas")
		self.assertTrue(ok, err)
		self.assertIsNone(pos)
		self.assertEqual(self.c.claveMarca, url)
		self.c.comenzar()
		self.assertTrue(self.c.hayReproduccion())
		self.assertEqual(self.c.historial.obtener()[0]["id"], "p1")
		self.assertEqual(self.c.historial.obtener()[0]["url"], url)
		self.assertEqual(self.c.estadisticas.resumen()["total_reproducciones"], 1)
		self.c.reproductor.setPosicion(2.0)
		self.c.detener()
		self.assertFalse(self.c.hayReproduccion())
		self.assertAlmostEqual(self.c.visualizacion.obtenerPosicion(url), 2.0, places=1)
		ok, pos, _e = self.c.prepararContenido("system/files/peliculas/tren.mp3", "El tren", "p1", "peliculas")
		self.assertAlmostEqual(pos, 2.0, places=1)
		self.c.comenzar(pos)
		self.assertAlmostEqual(self.c.reproductor.getPosicion(), 2.0, places=1)

	def test_url_con_cabecera(self):
		credenciales.guardar("usuario", "clave")
		with mock.patch.object(self.c.reproductor, "cargarUrl", return_value=False) as cargar:
			ok, _p, err = self.c.prepararContenido("system/files/series/c1x1.mp3")
		self.assertFalse(ok)
		self.assertTrue(err)
		cargar.assert_called_once_with("https://audiocinemateca.com/system/files/series/c1x1.mp3", {"Authorization": "Basic dXN1YXJpbzpjbGF2ZQ=="})

	def test_ajustes_aplicados_al_cargar(self):
		ajustes.put("volumen", 20)
		ajustes.put("velocidad", 17)
		ajustes.put("ecualizadorActivo", True)
		ajustes.put("ecualizadorValores", [1, 2, 3, 4, 5])
		ok, _p, _e = self.c.prepararArchivo(self.wav, "https://a/b.mp3", "B")
		self.assertTrue(ok)
		r = self.c.reproductor
		self.assertEqual(r.getVolumen(), 20)
		self.assertEqual(r.getVelocidad(), 2.0)
		self.assertEqual(r.numeroEfectos(), 5)
		ajustes.put("ecualizadorActivo", False)
		self.c.comenzar()
		self.c.aplicarEcualizadorActual()
		self.assertEqual(r.numeroEfectos(), 0)

	def test_volumen_y_velocidad(self):
		ajustes.put("volumen", 99)
		self.assertEqual(self.c.cambiarVolumen(5), 100)
		self.assertEqual(self.c.cambiarVolumen(-1), 99)
		ajustes.put("velocidad", 0)
		self.assertEqual(self.c.cambiarVelocidad(-1), 0)
		self.assertEqual(self.c.cambiarVelocidad(1), 1)

	def test_temporizador(self):
		self.c.prepararArchivo(self.wav, "https://a/c.mp3")
		self.c.comenzar()
		with Voz() as voz:
			self.c.iniciarTemporizador(30)
			self.assertEqual(voz.ultimo, "Temporizador de sueño activado: 30 minutos")
			self.assertTrue(ajustes.estado.temporizadorActivo)
			self.assertIn("Temporizador de sueño: 29 minutos", self.c.infoTemporizador())
			avisado = []
			self.c.alTerminarTemporizador = lambda: avisado.append(True)
			self.c.reproductor.setPosicion(1.5)
			self.c._ejecutarTemporizador()
			self.assertEqual(voz.ultimo, "Temporizador de sueño: reproducción detenida")
		self.assertTrue(avisado)
		self.assertFalse(self.c.hayReproduccion())
		self.assertAlmostEqual(self.c.visualizacion.obtenerPosicion("https://a/c.mp3"), 1.5, places=1)
		self.assertEqual(self.c.infoTemporizador(), "Temporizador de sueño no activo")
		with Voz():
			self.c.iniciarTemporizador(5)
		self.c.cancelarTemporizador()
		self.assertFalse(ajustes.estado.temporizadorActivo)

	def test_detener_cancela_temporizador(self):
		self.c.prepararArchivo(self.wav)
		self.c.comenzar()
		with Voz():
			self.c.iniciarTemporizador(10)
		self.c.detener()
		self.assertFalse(ajustes.estado.temporizadorActivo)


# ====================================================================== complemento global
class TestComplementoGlobal(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		ajustes.restaurarDefecto()
		cls.gp = ac.GlobalPlugin()
		fin = time.time() + 10
		while cls.gp.control is None and time.time() < fin:
			time.sleep(0.02)
		assert cls.gp.control is not None
		cls.gp.control._reproductor = silencioso()
		cls.wav = _wav(os.path.join(_carpeta(), "peli.wav"), segundos=200, freq=8000)

	@classmethod
	def tearDownClass(cls):
		cls.gp.terminate()
		from tiresias import gui
		from tiresias.gui import settings as S

		assert ac.MENU_ID not in gui._addonToolsEntries
		assert panel.PANEL_ID not in S._panels

	def setUp(self):
		ajustes.restaurarDefecto()
		ajustes.estado.ventanaAbierta = False
		self.gp.control.detener()

	def _sonar(self):
		ok, _p, err = self.gp.control.prepararArchivo(self.wav, "https://a/peli.mp3", "La película")
		self.assertTrue(ok, err)
		self.gp.control.comenzar()

	def test_registro_menu_y_opciones(self):
		from tiresias import gui
		from tiresias.gui import settings as S

		etiqueta, accion, submenu = gui._addonToolsEntries[ac.MENU_ID]
		self.assertEqual(etiqueta, "&Audiocinemateca")
		self.assertTrue(submenu)
		self.assertEqual([e[0] for e in accion()], [
			"&Iniciar la Audiocinemateca", "&Opciones", "&Volver a valores por defecto", "&Documentación del complemento",
		])
		self.assertIn(panel.PANEL_ID, S._panels)
		cls = S._panels[panel.PANEL_ID][1]
		self.assertTrue(issubclass(cls, S.ConfigPanel))
		self.assertTrue({f.key for f in cls.fields} <= set(ajustes.DEFECTO))

	def test_ordenes_tienen_descripcion_y_categoria(self):
		ordenes = [n for n in dir(ac.GlobalPlugin) if n.startswith("script_")]
		self.assertEqual(len(ordenes), 15)
		for n in ordenes:
			f = getattr(ac.GlobalPlugin, n)
			self.assertTrue(f.__doc__, n)
			self.assertEqual(f.category, "Audiocinemateca", n)
			self.assertEqual(f.gestures, [], n)

	def test_sin_reproduccion_y_ventana_abierta(self):
		with Voz() as voz:
			self.gp.script_SubirVolumen(None)
			self.assertEqual(voz.ultimo, "Sin nada en reproducción")
			ajustes.estado.ventanaAbierta = True
			self.gp.script_Informacion(None)
			self.assertIn("La ventana de Audiocinemateca está abierta", voz.ultimo)
			self.gp.script_Temporizador(None)
			self.assertIn("La ventana de Audiocinemateca está abierta", voz.ultimo)
		ajustes.estado.ventanaAbierta = False

	def test_ordenes_del_reproductor(self):
		self._sonar()
		with Voz() as voz:
			self.gp.script_SubirVolumen(None)
			self.assertEqual(voz.ultimo, "Volumen al 51%")
			self.gp.script_BajarVolumen(None)
			self.assertEqual(voz.ultimo, "Volumen al 50%")
			ajustes.put("volumen", 100)
			self.gp.script_SubirVolumen(None)
			self.assertEqual(voz.ultimo, "No se puede subir más el volumen. Ya se encuentra al 100%")
			ajustes.put("volumen", 0)
			self.gp.script_BajarVolumen(None)
			self.assertEqual(voz.ultimo, "No se puede bajar más el volumen. Ya se encuentra al 0%")
			self.gp.script_SubirVelocidad(None)
			self.assertEqual(voz.ultimo, "Velocidad 1.05")
			self.gp.script_BajarVelocidad(None)
			self.assertEqual(voz.ultimo, "Velocidad 1.0")
			ajustes.put("velocidad", 0)
			self.gp.script_BajarVelocidad(None)
			self.assertEqual(voz.ultimo, "No se puede bajar más la velocidad. Ya se encuentra al mínimo posible")
			ajustes.put("velocidad", len(ajustes.LISTA_VELOCIDAD) - 1)
			self.gp.script_SubirVelocidad(None)
			self.assertEqual(voz.ultimo, "No se puede subir más la velocidad. Ya se encuentra al máximo")
			ajustes.put("velocidad", 5)
			self.gp.control.ponerVelocidad(5)
			self.gp.script_Adelantar(None)
			self.assertEqual(voz.ultimo, "Adelantando 30 segundos")
			self.assertGreaterEqual(self.gp.control.reproductor.getPosicion(), 29)
			self.gp.script_Atrasar(None)
			self.assertEqual(voz.ultimo, "Atrasando 15 segundos")
			self.gp.script_Informacion(None)
			self.assertRegex(voz.ultimo, r"^Tiempo transcurrido: 00:1\d / Tiempo total: 03:20$")
			self.gp.script_TiempoRestante(None)
			self.assertRegex(voz.ultimo, r"^Tiempo restante: 03:0\d$")
			self.gp.script_TituloActual(None)
			self.assertEqual(voz.ultimo, "Reproduciendo: La película")
			self.gp.script_ReproducirPausar(None)
			self.assertEqual(voz.ultimo, "Pausando...")
			self.gp.script_ReproducirPausar(None)
			self.assertEqual(voz.ultimo, "Reproduciendo...")
			self.gp.script_Detener(None)
			self.assertEqual(voz.ultimo, "Detenido")
			self.assertFalse(self.gp.control.hayReproduccion())

	def test_temporizador_global(self):
		with Voz() as voz:
			self.gp.script_Temporizador(None)
			self.assertEqual(voz.ultimo, "Temporizador de sueño no activo")
			self.gp.script_CancelarTemporizador(None)
			self.assertEqual(voz.ultimo, "No hay temporizador de sueño activo")
			self.gp.control.iniciarTemporizador(15)
			self.gp.script_Temporizador(None)
			self.assertIn("14 minutos", voz.ultimo)
			self.gp.script_CancelarTemporizador(None)
			self.assertEqual(voz.ultimo, "Temporizador de sueño cancelado")

	def test_iniciar_sin_internet_o_cargando(self):
		with Voz() as voz, mock.patch.object(red, "hayInternet", return_value=False):
			self.gp.iniciar()
			fin = time.time() + 3
			while self.gp._ocupado and time.time() < fin:
				time.sleep(0.02)
			self.assertEqual(voz.ultimo, "No se encontró conexión a internet. No es posible iniciar el complemento.")
		control_ = self.gp.control
		self.gp.control = None
		try:
			with Voz() as voz:
				self.gp.iniciar()
				self.assertIn("todavía se está cargando", voz.ultimo)
		finally:
			self.gp.control = control_

	def test_opciones_cambiadas(self):
		self._sonar()
		ajustes.put("volumen", 33)
		ajustes.put("velocidad", 0)
		self.gp.opcionesCambiadas({"volumen", "velocidad"})
		self.assertEqual(self.gp.control.reproductor.getVolumen(), 33)
		self.assertEqual(self.gp.control.reproductor.getVelocidad(), 0.75)


# ====================================================================== interfaz (ventanas ocultas)
class _ComplementoFalso:
	def __init__(self, c) -> None:
		self.control = c
		self.cerradas = []

	def ventanaCerrada(self, v, recargar=False):
		self.cerradas.append(recargar)

	def abrirOpciones(self):
		pass

	def restaurarDefecto(self, parent=None):
		return False

	def abrirDocumentacion(self):
		pass


class TestInterfaz(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		import wx

		cls.app = wx.App.Get() or wx.App(False)
		cls.dialogos = import_module(ac.__name__ + ".dialogos")
		cls.ventanaMod = import_module(ac.__name__ + ".ventana")

	def setUp(self):
		ajustes.restaurarDefecto()
		self.carpeta = _carpeta()
		escribirCatalogo(self.carpeta)
		self.c = control.Controlador(self.carpeta, avisar=lambda m: None)
		self.c.catalogo.cargar()

	def tearDown(self):
		self.c.terminar()
		ajustes.estado.ventanaAbierta = False

	def test_ventana_principal(self):
		comp = _ComplementoFalso(self.c)
		with Voz() as voz:
			v = self.ventanaMod.VentanaPrincipal(comp)
			try:
				self.assertTrue(ajustes.estado.ventanaAbierta)
				self.assertEqual(v.notebook.GetPageCount(), 8)
				self.assertEqual(v.notebook.GetPageText(7), "Listas (Alt+8)")
				self.assertEqual(v.listUltimos.GetStrings()[0], "¡Bienvenido, Mister Marshall!")
				self.assertEqual(v.listCategoria[1].GetStrings(), ["Cuéntame cómo pasó"])
				self.assertFalse(v.btnReproducir.IsShown())
				# Últimos contenidos de otra categoría.
				v.choiceUltimos.SetSelection(3)
				v._rellenarUltimos()
				self.assertEqual(v.listUltimos.GetStrings(), ["El columpio"])
				# Búsqueda por título y por director (cambio de filtro).
				v.txtBusqueda[0].SetValue("agora")
				v.buscarEnCategoria(0)
				self.assertEqual(v.listCategoria[0].GetStrings(), ["Ágora"])
				self.assertEqual(v._datosCategoria(0, 0)["id"], "p2")
				v.ponerFiltro(0, ajustes.LISTA_FILTROS.index("Director"))
				self.assertEqual(v.lblBusqueda[0].GetLabel(), "&Buscar películas por Director:")
				v.txtBusqueda[0].SetValue("berlanga")
				v.buscarEnCategoria(0)
				self.assertEqual(v.listCategoria[0].GetStrings(), ["¡Bienvenido, Mister Marshall!"])
				v.txtBusqueda[0].SetValue("nada de nada")
				v.buscarEnCategoria(0)
				self.assertEqual(v.listCategoria[0].GetStrings(), ["Sin resultados"])
				v.limpiarBusqueda(0)
				self.assertEqual(v.listCategoria[0].GetCount(), 3)
				self.assertEqual(self.c.historialBusqueda.obtener()[0]["texto"], "nada de nada")
				# Búsqueda global.
				v.txtGlobal.SetValue("tierra")
				v.buscarGlobal()
				self.assertEqual(v.listGlobal.GetStrings(), ["La Tierra desde el cielo [Documental]"])
				# Repetir una búsqueda del historial (por director).
				v.repetirBusqueda({"texto": "amenabar", "filtro": "Director", "indiceFiltro": 4, "categoria": 0})
				self.assertEqual(v.notebook.GetSelection(), 1)
				self.assertEqual(v.listCategoria[0].GetStrings(), ["Ágora"])
				v.repetirBusqueda({"texto": "columpio", "filtro": "Global", "categoria": -1})
				self.assertEqual(v.listGlobal.GetStrings(), ["El columpio [Cortometraje]"])
				# Favoritos.
				self.c.favoritos.agregar("peliculas", "p1")
				raiz = v.treeFavoritos.GetRootItem()
				hijo, _cookie = v.treeFavoritos.GetFirstChild(raiz)
				v.treeFavoritos.SelectItem(hijo)
				v._actualizarFavoritos()
				self.assertEqual(v.listFavoritos.GetStrings(), ["El último tren a Gun Hill"])
				# Historial.
				self.c.historial.registrar("s1", "series", "Cuéntame cómo pasó")
				v._actualizarHistorial()
				self.assertTrue(v.listHistorial.GetString(0).startswith("Cuéntame cómo pasó [Serie] - "))
				v.choiceHistorial.SetSelection(1)
				v._actualizarHistorial()
				self.assertEqual(v.listHistorial.GetStrings(), ["No hay historial"])
				# Listas personalizadas.
				self.c.listas.crearLista("Por ver")
				self.c.listas.agregarItem("Por ver", "d1", "documentales", "La Tierra desde el cielo")
				v._actualizarNombresListas()
				self.assertEqual(v.listNombres.GetStrings(), ["Por ver (1)"])
				self.assertEqual(v.listContenido.GetStrings(), ["La Tierra desde el cielo [Documental]"])
				v.listContenido.SetSelection(0)
				v._quitarDeLista()
				self.assertEqual(v.listContenido.GetStrings(), ["Lista vacía"])
				# F12 alterna los mensajes informativos.
				v._alternarHablar()
				self.assertFalse(ajustes.hablarActivo())
				self.assertEqual(voz.ultimo, "Mensajes de información desactivados")
				v._alternarHablar()
				# Volumen y velocidad desde la ventana.
				v._cambiarVolumen(1)
				self.assertEqual(v.sliderVolumen.GetValue(), 51)
				self.assertEqual(voz.ultimo, "Volumen 51%")
				v._cambiarVelocidad(1)
				self.assertEqual(voz.ultimo, "Velocidad 1.05")
				v._anunciarInfo()
				self.assertEqual(voz.ultimo, "Sin nada en reproducción")
				v.irAPestana(5)
				self.assertEqual(v.GetTitle(), "Audiocinemateca - Favoritos")
			finally:
				v.cerrar()
		self.assertFalse(ajustes.estado.ventanaAbierta)
		self.assertEqual(comp.cerradas, [False])
		self.assertFalse(self.c.catalogo.cargado)

	def test_fichas(self):
		D = self.dialogos
		serie = self.c.catalogo.buscarId("series", "s1")
		dlg = D.DialogoFicha(None, self.c, serie, "series")
		try:
			self.assertEqual(dlg.GetTitle(), "Ficha de la Serie")
			self.assertEqual(dlg.choiceTemporadas.GetStrings(), ["Temporada 1", "Temporada 2", "Temporada 10"])
			self.assertEqual(dlg.listEpisodios.GetStrings(), ["Cap. 1 - Piloto", "Cap. 2 - Segundo"])
			dlg.listEpisodios.SetSelection(1)
			self.assertEqual(dlg.enlaceSeleccionado(), ("system/files/series/c1x2.mp3", "Cuéntame cómo pasó - T1 Cap. 2 - Segundo"))
			dlg.choiceTemporadas.SetSelection(2)
			dlg._cargarEpisodios(2)
			self.assertEqual(dlg.enlaceSeleccionado()[0], "system/files/series/c10x1.mp3")
			self.assertEqual(dlg.btnFavorito.GetLabel(), "&Agregar a Favoritos")
			with Voz():
				dlg._onFavorito(None)
			self.assertEqual(dlg.btnFavorito.GetLabel(), "&Quitar de Favoritos")
			self.assertTrue(self.c.favoritos.esFavorito("series", "s1"))
		finally:
			dlg.Destroy()
		peli = self.c.catalogo.buscarId("peliculas", "p2")
		dlg = D.DialogoFicha(None, self.c, peli, "peliculas")
		try:
			self.assertEqual(dlg.GetTitle(), "Ficha de la película")
			self.assertEqual(dlg.choiceEnlaces.GetStrings(), ["Parte 1 de 2", "Parte 2 de 2"])
			dlg.choiceEnlaces.SetSelection(1)
			self.assertEqual(dlg.enlaceSeleccionado(), ("system/files/peliculas/agora2.mp3", "Ágora - Parte 2 de 2"))
			self.assertIn("Director:\nAlejandro Amenábar", dlg.txtInfo.GetValue())
		finally:
			dlg.Destroy()
		corto = self.c.catalogo.buscarId("cortometrajes", "c1")
		dlg = D.DialogoFicha(None, self.c, corto, "cortometrajes")
		try:
			self.assertEqual(dlg.GetTitle(), "Ficha del cortometraje")
			self.assertEqual(dlg.enlaceSeleccionado(), ("system/files/cortos/columpio.mp3", "El columpio"))
		finally:
			dlg.Destroy()

	def test_panel_de_opciones(self):
		import wx

		frame = wx.Frame(None)
		try:
			credenciales.guardar("lectora", "x")
			cls = panel.crearClasePanel()
			p = cls(frame)
			self.assertEqual(p.lblCuenta.GetLabel(), "Sesión iniciada como: lectora")
			self.assertTrue(p.btnCerrarSesion.IsEnabled())
			disp = p.getControl("dispositivo")
			self.assertEqual(disp.GetString(0), "Predeterminado de Windows")
			p.setControlValue("adelantar", 6)
			p.setControlValue("hablar", False)
			p.onSave()
			self.assertEqual(ajustes.segundosAdelantar(), 600)
			self.assertFalse(ajustes.hablarActivo())
			credenciales.borrar()
			p._refrescarCuenta()
			self.assertEqual(p.lblCuenta.GetLabel(), "No hay ninguna sesión iniciada.")
			self.assertFalse(p.btnCerrarSesion.IsEnabled())
		finally:
			credenciales.borrar()
			frame.Destroy()

	def _procesar(self, condicion, tiempo=5.0):
		import wx

		fin = time.time() + tiempo
		while not condicion() and time.time() < fin:
			self.app.ProcessPendingEvents()
			wx.YieldIfNeeded()
			time.sleep(0.01)
		self.app.ProcessPendingEvents()
		return condicion()

	def test_descarga_y_actualizacion_del_catalogo(self):
		D = self.dialogos
		carpeta = _carpeta()
		nueva = {"year": 2026, "mon": 4, "mday": 1, "hours": 9, "minutes": 0, "seconds": 0}
		vieja = {"year": 2026, "mon": 3, "mday": 5, "hours": 10, "minutes": 30, "seconds": 0}
		pedidas = []

		def falsa(url, destino, u="", c="", progreso=None, cancelado=None):
			pedidas.append(url)
			if url == ajustes.URL_VERSION:
				datos = gzip.compress(json.dumps(nueva).encode())
			else:
				datos = bz2.compress(json.dumps(catalogoEjemplo()).encode())
			with open(destino, "wb") as f:
				f.write(datos)
			if progreso:
				progreso(100)
			return destino

		credenciales.guardar("u", "c")
		try:
			with mock.patch.object(D.red, "descargar", side_effect=falsa):
				# Descarga inicial.
				dlg = D.DialogoDescarga(None, D.DialogoDescarga.DESCARGA, carpeta)
				try:
					self.assertTrue(self._procesar(lambda: dlg.btnAceptar.IsEnabled()))
					self.assertIn("completada", dlg.txtInfo.GetValue())
				finally:
					dlg.Destroy()
				self.assertEqual(pedidas, [ajustes.URL_VERSION, ajustes.URL_CATALOGO])
				g = catalogo.GestorCatalogo(carpeta)
				self.assertTrue(g.cargar())
				self.assertEqual(g.version, nueva)
				self.assertEqual(sorted(os.listdir(carpeta)), ["catalogo.json", "version.json"])
				# Hay actualización: la versión local no cambia hasta descargar el catálogo.
				with open(os.path.join(carpeta, "version.json"), "w") as f:
					json.dump(vieja, f)
				dlg = D.DialogoDescarga(None, D.DialogoDescarga.ACTUALIZAR, carpeta, versionLocal=vieja)
				try:
					self.assertTrue(self._procesar(lambda: dlg.btnActualizar.IsEnabled()))
					self.assertIn("Hay actualizaciones", dlg.txtInfo.GetValue())
					self.assertEqual(g.cargarVersion(), vieja)
					dlg._onActualizar(None)
					self.assertTrue(self._procesar(lambda: dlg.btnAceptar.IsEnabled()))
					self.assertTrue(dlg._actualizado)
				finally:
					dlg.Destroy()
				self.assertEqual(g.cargarVersion(), nueva)
				# Sin actualización.
				dlg = D.DialogoDescarga(None, D.DialogoDescarga.ACTUALIZAR, carpeta, versionLocal=nueva)
				try:
					self.assertTrue(self._procesar(lambda: dlg.btnAceptar.IsEnabled()))
					self.assertIn("No hay actualizaciones", dlg.txtInfo.GetValue())
					self.assertFalse(dlg.btnActualizar.IsEnabled())
				finally:
					dlg.Destroy()
			# Error de red: se ofrece Cerrar y se explica el motivo.
			with mock.patch.object(D.red, "descargar", side_effect=urllib.error.HTTPError("u", 401, "x", {}, None)):
				dlg = D.DialogoDescarga(None, D.DialogoDescarga.ACTUALIZAR, carpeta, versionLocal=nueva)
				try:
					self.assertTrue(self._procesar(lambda: dlg.btnCerrar.IsEnabled()))
					self.assertIn("usuario o la contraseña", dlg.txtInfo.GetValue())
				finally:
					dlg.Destroy()
		finally:
			credenciales.borrar()

	def test_otros_dialogos(self):
		D = self.dialogos
		eq = D.DialogoEcualizador(None)
		try:
			eq.choicePreset.SetSelection(1)
			eq._onPreset(None)
			self.assertEqual(eq.valores(), [0, 0, 4, 6, 2])
		finally:
			eq.Destroy()
		t = D.DialogoTemporizador(None)
		try:
			self.assertEqual(t.obtenerMinutos(), 0)
			t.choiceTiempo.SetSelection(5)
			self.assertEqual(t.obtenerMinutos(), 90)
			t.choiceTiempo.SetSelection(7)
			t.spinMinutos.SetValue(37)
			self.assertEqual(t.obtenerMinutos(), 37)
		finally:
			t.Destroy()
		d = D.DialogoDescargas(None, self.c)
		try:
			self.assertEqual(d.listActivas.GetStrings(), ["No hay descargas en curso"])
			self.assertEqual(d.listFinalizadas.GetStrings(), ["No hay descargas finalizadas"])
			self.assertFalse(d.btnReproducir.IsEnabled())
		finally:
			d._timer.Stop()
			d.Destroy()
		item = descargas.ItemDescarga("https://a/x.mp3", self.carpeta, "Equis")
		item.estado, item.progreso = descargas.DESCARGANDO, 42
		self.assertEqual(D.DialogoDescargas.textoActiva(item), "Equis - Descargando (42%)")
		item.estado, item.error = descargas.ERROR, "fallo"
		self.assertEqual(D.DialogoDescargas.textoFinalizada(item), "Equis - Error: fallo")
		self.c.estadisticas.registrarReproduccion("p1", "peliculas", "Uno", 7300)
		texto = D.textoResumen(self.c.estadisticas.resumen())
		self.assertIn("Total de reproducciones: 1", texto)
		self.assertIn("Tiempo total de reproducción: 2 horas y 1 minutos", texto)
		self.assertIn("Categoría favorita: Películas", texto)
		acerca = D.textoAcercaDe(self.c.catalogo.version)
		self.assertIn("Versión de la base de datos: 5 de marzo de 2026, 10:30", acerca)
		self.assertIn("BASS 2.4", acerca)
		self.assertIn("Registro de cambios", acerca)
		h = D.DialogoHistorialBusqueda(None, self.c)
		try:
			self.assertEqual(h.lista.GetStrings(), ["No hay búsquedas"])
		finally:
			h.Destroy()
		self.c.historialBusqueda.registrar("agora", "Título", 0, 0)
		h = D.DialogoHistorialBusqueda(None, self.c)
		try:
			self.assertTrue(h.lista.GetString(0).startswith("agora - Películas, por Título - "))
		finally:
			h.Destroy()
		login = D.DialogoLogin(None)
		try:
			login.txtUsuario.SetValue("u")
			login.txtOculta.SetValue("secreta")
			login.chkMostrar.SetValue(True)
			login._onMostrar(None)
			self.assertEqual(login.txtVisible.GetValue(), "secreta")
		finally:
			login.Destroy()


if __name__ == "__main__":
	unittest.main()
