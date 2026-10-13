"""Pruebas del complemento de la tienda «Traductor Avanzado Pro».

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_complemento_traductor -v``

Las peticiones de los servicios de pago (DeepL API, OpenAI, Gemini, DeepSeek,
Claude) se simulan: no se usan claves reales. Los servicios gratuitos sin
clave (Google, Microsoft, diccionario) se prueban además con una petición
real de solo lectura en :class:`PruebasRedReal` (se saltan si no hay red).
Las ventanas se crean ocultas (nunca se muestran) y no se reproduce sonido.
"""

from __future__ import annotations

import gzip
import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.parse
import warnings
import wave
from importlib import import_module
from unittest import mock

warnings.filterwarnings("ignore", category=ResourceWarning)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_traductor_")
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]
else:
	_TMP = paths._dataDirForTests  # type: ignore[attr-defined]

from tiresias.config import conf  # noqa: E402

ADDON = os.path.join(ROOT, "complementos_tienda", "TraductorAvanzadoPro")
PKG = "tiresias_addon_traductor_pruebas"


def _cargarPaquete():
	"""Carga el complemento como Tiresias (paquete dentro de globalPlugins)."""
	for name, path in ((PKG, ADDON), (PKG + ".globalPlugins", os.path.join(ADDON, "globalPlugins"))):
		if name not in sys.modules:
			m = types.ModuleType(name)
			m.__path__ = [path]  # type: ignore[attr-defined]
			sys.modules[name] = m
	full = PKG + ".globalPlugins.TraductorAvanzadoPro"
	if full in sys.modules:
		return sys.modules[full]
	carpeta = os.path.join(ADDON, "globalPlugins", "TraductorAvanzadoPro")
	spec = importlib.util.spec_from_file_location(full, os.path.join(carpeta, "__init__.py"), submodule_search_locations=[carpeta])
	mod = importlib.util.module_from_spec(spec)
	sys.modules[full] = mod
	spec.loader.exec_module(mod)
	return mod


tap = _cargarPaquete()
red = import_module(tap.__name__ + ".utilidades.red")
seguridad = import_module(tap.__name__ + ".utilidades.seguridad")
lector = import_module(tap.__name__ + ".utilidades.lector")
texto_mod = import_module(tap.__name__ + ".utilidades.texto")
tts_mod = import_module(tap.__name__ + ".utilidades.tts")
modelos_mod = import_module(tap.__name__ + ".utilidades.modelos_ia")
configuracion_mod = import_module(tap.__name__ + ".nucleo.configuracion")
cache_mod = import_module(tap.__name__ + ".nucleo.cache")
historial_mod = import_module(tap.__name__ + ".nucleo.historial")
gt_mod = import_module(tap.__name__ + ".nucleo.gestor_traductores")
gp_mod = import_module(tap.__name__ + ".nucleo.gestor_plugins")
async_mod = import_module(tap.__name__ + ".nucleo.traductor_async")
idiomas_mod = import_module(tap.__name__ + ".servicios.idiomas")
comun = import_module(tap.__name__ + ".traductores._comun")

SECCION = configuracion_mod.SECCION


# ====================================================================== red simulada
class Respuesta:
	def __init__(self, cuerpo: bytes | str | dict | list, cabeceras: dict | None = None) -> None:
		if isinstance(cuerpo, (dict, list)):
			cuerpo = json.dumps(cuerpo).encode("utf-8")
		elif isinstance(cuerpo, str):
			cuerpo = cuerpo.encode("utf-8")
		self._datos = io.BytesIO(cuerpo)
		self.headers = cabeceras or {}

	def read(self, n: int = -1) -> bytes:
		return self._datos.read(n)

	def __enter__(self):
		return self

	def __exit__(self, *a):
		return False


def error_http(url: str, codigo: int, cuerpo: dict | str = "") -> urllib.error.HTTPError:
	datos = json.dumps(cuerpo).encode() if isinstance(cuerpo, dict) else cuerpo.encode()
	return urllib.error.HTTPError(url, codigo, "Error", {}, io.BytesIO(datos))


class ServidorSimulado:
	"""Sustituye ``red._abrir``: anota cada petición y responde con ``manejador``."""

	def __init__(self, manejador) -> None:
		self.manejador = manejador
		self.peticiones: list[dict] = []

	def __call__(self, req, timeout=None, context=None):
		cabeceras = {k.lower(): v for k, v in req.header_items()}
		cuerpo = req.data
		p = {"url": req.full_url, "metodo": req.get_method(), "cabeceras": cabeceras, "cuerpo": cuerpo}
		try:
			p["json"] = json.loads(cuerpo.decode("utf-8")) if cuerpo else None
		except ValueError:
			p["json"] = None
		self.peticiones.append(p)
		resultado = self.manejador(p)
		if isinstance(resultado, Exception):
			raise resultado
		return resultado if isinstance(resultado, Respuesta) else Respuesta(resultado)

	def __enter__(self):
		self._parches = [mock.patch.object(red, "_abrir", self), mock.patch.object(red, "_abrir_sesion", lambda sesion, req, timeout: self(req, timeout))]
		for p in self._parches:
			p.start()
		return self

	def __exit__(self, *a):
		for p in self._parches:
			p.stop()


def nuevaConfiguracion() -> "configuracion_mod.GestorConfiguracion":
	carpeta = tempfile.mkdtemp(prefix="tap_datos_", dir=_TMP)
	return configuracion_mod.GestorConfiguracion(os.path.join(ADDON, "globalPlugins", "TraductorAvanzadoPro"), carpeta)


def traductor(cls_nombre: str, modulo: str, configuracion=None):
	mod = import_module(f"{tap.__name__}.traductores.{modulo}")
	return getattr(mod, cls_nombre)(configuracion or nuevaConfiguracion())


def conClave(configuracion, servicio: str, *claves: str, rotacion: bool = False, **kw):
	configuracion.establecer_api(servicio, claves=[seguridad.codificar_api_key(c) for c in claves], usar_rotacion=rotacion, **kw)
	return configuracion


# ====================================================================== seguridad y configuración
class PruebasSeguridad(unittest.TestCase):
	def test_dpapi_ida_y_vuelta(self):
		cod = seguridad.codificar_api_key("sk-prueba-1234567890")
		self.assertTrue(cod.startswith(seguridad.PREFIJO_DPAPI))
		self.assertNotIn("sk-prueba", cod)
		self.assertEqual(seguridad.decodificar_api_key(cod), "sk-prueba-1234567890")

	def test_formato_del_original(self):
		import base64

		antiguo = base64.b64encode("clave-antigua"[::-1].encode()).decode()
		self.assertEqual(seguridad.decodificar_api_key(antiguo), "clave-antigua")
		self.assertEqual(seguridad.decodificar_api_key("b64:" + antiguo), "clave-antigua")
		self.assertEqual(seguridad.decodificar_api_key("dpapi:basura"), "")
		self.assertEqual(seguridad.codificar_api_key(""), "")

	def test_censurar(self):
		self.assertEqual(seguridad.censurar("abcd1234efgh"), "abcd****efgh")
		self.assertEqual(seguridad.censurar("corta"), "*****")

	def test_modo_seguro(self):
		from tiresias.config import policy

		with mock.patch.object(policy.policy, "secureMode", True):
			self.assertTrue(seguridad.es_modo_seguro())
			plugin = tap.GlobalPlugin()
			self.assertFalse(plugin._inicializado)
			plugin.terminate()
		self.assertFalse(seguridad.es_modo_seguro())


class PruebasConfiguracion(unittest.TestCase):
	def test_valores_por_defecto(self):
		c = nuevaConfiguracion()
		for clave in ("servicio_activo", "idioma_origen", "idioma_destino", "idioma_destino_alternativo", "cache_habilitada", "historial_habilitado", "mostrar_resultados", "intercambio_automatico_idioma", "sonidos_habilitados", "volumen_sonido", "velocidad_audio", "gui_idioma_origen", "gui_idioma_destino", "idioma_destino_google", "idioma_destino_deepl", "plugins_desactivados", "volumen_reproductor", "salto_atras", "salto_adelante"):
			self.assertIn(clave, conf[SECCION])
		self.assertEqual(c.config.servicio_activo, conf[SECCION]["servicio_activo"])
		self.assertEqual(conf.defaults[SECCION]["servicio_activo"], "google_api_free")
		self.assertEqual(conf.defaults[SECCION]["idioma_origen"], "auto")
		self.assertEqual(conf.defaults[SECCION]["idioma_destino_alternativo"], "en")

	def test_vista_escribe_en_conf(self):
		c = nuevaConfiguracion()
		anterior = c.config.mostrar_resultados
		try:
			c.config.mostrar_resultados = not anterior
			self.assertEqual(conf[SECCION]["mostrar_resultados"], not anterior)
			self.assertEqual(c.mostrar_resultados, not anterior)
		finally:
			c.config.mostrar_resultados = anterior

	def test_servicio_y_rotacion(self):
		s = configuracion_mod.ConfiguracionServicio()
		s.agregar_clave("uno")
		s.agregar_clave("dos")
		s.agregar_clave("uno")
		self.assertEqual(s.claves_planas(), ["uno", "dos"])
		self.assertEqual(s.api_key, "uno")
		self.assertFalse(s.rotar())
		s.usar_rotacion = True
		self.assertTrue(s.rotar())
		self.assertEqual(s.api_key, "dos")
		self.assertTrue(s.rotar())
		self.assertEqual(s.api_key, "uno")
		s.eliminar_clave("uno")
		self.assertEqual(s.claves_planas(), ["dos"])

	def test_apis_cifradas_en_disco(self):
		c = nuevaConfiguracion()
		conClave(c, "openai", "sk-secreta-ABCDEFGH", rotacion=True, modelo="gpt-x")
		c.establecer_api("openai", claves=c.obtener_api("openai").claves, usar_rotacion=True, prompt_sistema="sis")
		c.guardar()
		with open(c.ruta_apis, encoding="utf-8") as f:
			bruto = f.read()
		self.assertNotIn("sk-secreta", bruto)
		otra = configuracion_mod.GestorConfiguracion(c.ruta_complemento, c.ruta_config)
		sc = otra.obtener_api("openai")
		self.assertEqual(sc.api_key, "sk-secreta-ABCDEFGH")
		# Guardar las claves no borra el modelo ni el prompt (el original sí).
		self.assertEqual(sc.modelo, "gpt-x")
		self.assertEqual(sc.prompt_sistema, "sis")
		self.assertTrue(sc.usar_rotacion)

	def test_restablecer(self):
		c = nuevaConfiguracion()
		c.config.intercambio_automatico_idioma = True
		c.restablecer()
		self.assertFalse(c.intercambio_automatico_idioma)


# ====================================================================== caché e historial
class PruebasCache(unittest.TestCase):
	def setUp(self):
		self.c = nuevaConfiguracion()
		self.c.cache_habilitada = True
		self.cache = cache_mod.GestorCache(self.c)

	def test_por_aplicacion_y_global(self):
		self.cache.guardar("hello", "hola", "es", app="notepad")
		self.cache.guardar("world", "mundo", "es")
		self.assertEqual(self.cache.obtener("hello", "es", app="notepad"), "hola")
		self.assertIsNone(self.cache.obtener("hello", "es", app="otra"))
		self.assertEqual(self.cache.obtener("world", "es", app="notepad"), "mundo")
		self.assertIsNone(self.cache.obtener("hello", "fr", app="notepad"))

	def test_persistencia_y_limpieza_por_aplicacion(self):
		self.cache.guardar("a b", "c d", "es", app="app con espacios")
		self.cache.guardar("x", "y", "es", app="otra")
		self.cache.guardar_todo()
		nueva = cache_mod.GestorCache(self.c)
		nueva.cargar()
		self.assertEqual(nueva.obtener("a b", "es", app="app con espacios"), "c d")
		self.assertEqual(nueva.limpiar_aplicacion("app con espacios"), 1)
		otra = cache_mod.GestorCache(self.c)
		otra.cargar()
		self.assertIsNone(otra.obtener("a b", "es", app="app con espacios"))
		self.assertEqual(otra.obtener("x", "es", app="otra"), "y")
		otra.limpiar()
		self.assertEqual(os.listdir(self.c.ruta_cache), [])

	def test_desactivada(self):
		self.c.cache_habilitada = False
		try:
			self.cache.guardar("a", "b", "es")
			self.assertIsNone(self.cache.obtener("a", "es"))
		finally:
			self.c.cache_habilitada = True

	def test_limpia_lo_menos_usado(self):
		with mock.patch.object(cache_mod.GestorCache, "TAMANO_MAXIMO_MEMORIA", 10):
			for i in range(10):
				self.cache.guardar(f"t{i}", f"r{i}", "es")
			for _ in range(3):
				self.cache.obtener("t0", "es")
			self.cache.guardar("nuevo", "n", "es")
			stats = self.cache.obtener_estadisticas()
			self.assertLessEqual(stats["total_entradas"], 10)
			self.assertEqual(self.cache.obtener("t0", "es"), "r0")
			self.assertEqual(self.cache.obtener("nuevo", "es"), "n")

	def test_alias_agregar(self):
		self.cache.agregar("uno", "one", "en")
		self.assertEqual(self.cache.obtener("uno", "en"), "one")


class PruebasHistorial(unittest.TestCase):
	def test_agregar_persistir_y_eliminar(self):
		c = nuevaConfiguracion()
		c.historial_habilitado = True
		h = historial_mod.GestorHistorial(c)
		self.assertTrue(h.agregar("hello", "hola", "en", "es", "google_api_free"))
		self.assertFalse(h.agregar("hello", "hola", "en", "es"))
		h.agregar("bye", "adiós", "en", "es", "deepl_free")
		self.assertEqual(h.obtener_ultimo().texto_original, "bye")
		otro = historial_mod.GestorHistorial(c)
		self.assertEqual(otro.obtener_tamano(), 2)
		self.assertEqual([e.texto_original for e in otro.buscar("ADI")], ["bye"])
		self.assertTrue(otro.eliminar(otro.obtener_por_indice(0)))
		self.assertEqual(historial_mod.GestorHistorial(c).obtener_tamano(), 1)
		entradas, paginas = otro.listar_paginado(0, 20)
		self.assertEqual((len(entradas), paginas), (1, 1))
		otro.limpiar()
		self.assertTrue(historial_mod.GestorHistorial(c).esta_vacio())

	def test_desactivado(self):
		c = nuevaConfiguracion()
		c.historial_habilitado = False
		try:
			h = historial_mod.GestorHistorial(c)
			self.assertFalse(h.agregar("a", "b"))
		finally:
			c.historial_habilitado = True


# ====================================================================== utilidades
class PruebasUtilidades(unittest.TestCase):
	def test_gzip_y_error_http(self):
		def manejador(p):
			if "gzip" in p["url"]:
				return Respuesta(gzip.compress(b'{"ok": 1}'), {"Content-Encoding": "gzip"})
			return error_http(p["url"], 403, {"error": {"message": "clave mala"}})

		with ServidorSimulado(manejador):
			self.assertEqual(red.peticion_json("https://x/gzip"), {"ok": 1})
			with self.assertRaises(red.ErrorRed) as ctx:
				red.peticion("https://x/otro")
		self.assertEqual(ctx.exception.codigo, 403)
		self.assertEqual(ctx.exception.mensaje_api(), "clave mala")

	def test_conexion(self):
		with ServidorSimulado(lambda p: urllib.error.URLError("sin red")):
			self.assertFalse(red.verificar_conexion_internet())
		with ServidorSimulado(lambda p: error_http(p["url"], 405)):
			self.assertTrue(red.verificar_conexion_internet())

	def test_texto(self):
		self.assertEqual(texto_mod.limpiar_texto("  a\n\n b \ud800"), "a b")
		self.assertEqual(texto_mod.dividir_oraciones("Hola. ¿Qué tal? Bien"), ["Hola.", "¿Qué tal?", "Bien"])
		self.assertEqual(texto_mod.contar_palabras("uno dos tres"), 3)
		self.assertEqual(texto_mod.truncar_texto("abcdefghij", 6), "abc...")
		self.assertTrue(texto_mod.es_texto_traducible(" a "))
		self.assertFalse(texto_mod.es_texto_traducible(" ... "))
		largo = "Frase uno. " * 500
		trozos = texto_mod.dividir_por_longitud(largo, 300)
		self.assertEqual("".join(trozos), largo)
		self.assertTrue(all(len(t) <= 300 for t in trozos))

	def test_prompts(self):
		sc = configuracion_mod.ConfiguracionServicio()
		sistema, usuario = comun.preparar_prompts(sc, "es", "Hello {world}")
		self.assertEqual(sistema, comun.PROMPTS_DEFECTO["sistema"])
		self.assertIn("español (es)", usuario)
		self.assertTrue(usuario.endswith("Hello {world}"))
		sc.prompt_usuario = "Pasa a {idioma_destino}"
		_s, usuario = comun.preparar_prompts(sc, "fr", "texto")
		self.assertEqual(usuario, "Pasa a francés (fr)\n\ntexto")

	def test_tts_trozos_y_descarga(self):
		g = tts_mod.GestorTTSGoogle()
		g.pausa = (0, 0)
		partes = g._dividir_texto("palabra " * 80)
		self.assertTrue(all(len(p) <= 200 for p in partes))
		self.assertGreater(len(partes), 1)
		with ServidorSimulado(lambda p: Respuesta(b"MP3")) as srv:
			progreso = []
			audio = g.obtener_audio("palabra " * 80, "EN-GB", progreso.append)
		self.assertEqual(audio, b"MP3" * len(partes))
		self.assertEqual(progreso[-1], 100)
		self.assertIn("tl=en&", srv.peticiones[0]["url"])

	def test_listado_modelos_claude_paginado(self):
		def manejador(p):
			self.assertEqual(p["cabeceras"]["x-api-key"], "clave")
			self.assertEqual(p["cabeceras"]["anthropic-version"], "2023-06-01")
			if "after_id" in p["url"]:
				return {"data": [{"id": "claude-b"}], "has_more": False}
			return {"data": [{"id": "claude-a"}], "has_more": True, "last_id": "claude-a"}

		carpeta = tempfile.mkdtemp(dir=_TMP)
		lista = modelos_mod.ListadorModelosIA(carpeta)
		with ServidorSimulado(manejador) as srv:
			self.assertEqual(lista.obtener_modelos("claude", "clave"), ["claude-a", "claude-b"])
			self.assertEqual(lista.obtener_modelos("claude", "clave"), ["claude-a", "claude-b"])
		self.assertEqual(len(srv.peticiones), 2)
		lista.borrar_cache("claude")
		with ServidorSimulado(lambda p: error_http(p["url"], 401, {"error": {"message": "invalid x-api-key"}})):
			self.assertEqual(lista.obtener_modelos("claude", "clave"), [])
		self.assertIn("invalid x-api-key", lista.ultimo_error)

	def test_listado_modelos_openai_gemini_deepseek(self):
		def manejador(p):
			if "generativelanguage" in p["url"]:
				return {"models": [{"name": "models/gemini-2.5-flash"}]}
			return {"data": [{"id": "m2"}, {"id": "m1"}]}

		lista = modelos_mod.ListadorModelosIA(tempfile.mkdtemp(dir=_TMP))
		with ServidorSimulado(manejador) as srv:
			self.assertEqual(lista.obtener_modelos("openai", "k"), ["m1", "m2"])
			self.assertEqual(lista.obtener_modelos("deepseek", "k"), ["m1", "m2"])
			self.assertEqual(lista.obtener_modelos("gemini", "k"), ["gemini-2.5-flash"])
		self.assertEqual(srv.peticiones[0]["cabeceras"]["authorization"], "Bearer k")


# ====================================================================== traductores
class PruebasTraductores(unittest.TestCase):
	def test_google(self):
		t = traductor("TraductorGoogleApiFree", "google_api_free")

		def manejador(p):
			q = urllib.parse.parse_qs(urllib.parse.urlsplit(p["url"]).query)
			self.assertEqual(q["tl"], ["zh-CN"])
			return {"sentences": [{"trans": "你好"}, {"trans": "世界"}], "src": "en"}

		with ServidorSimulado(manejador):
			self.assertEqual(t.traducir("Hello world", "auto", "zh"), "你好世界")
		with ServidorSimulado(lambda p: {"sentences": [{"trans": "x"}], "src": "fr"}):
			self.assertEqual(t.detectar_idioma("Bonjour"), "fr")
		with ServidorSimulado(lambda p: error_http(p["url"], 429)):
			self.assertIsNone(t.traducir("Hello", "auto", "es"))
		self.assertIn("429", t.ultimo_error)

	def test_google_servicio_alternativo(self):
		t = traductor("TraductorGoogleApiFree", "google_api_free")

		def manejador(p):
			if "clients5.google.com" in p["url"]:
				self.assertEqual(urllib.parse.parse_qs(p["cuerpo"].decode())["q"], ["Hello"])
				return [["Hola", "en"]]
			return error_http(p["url"], 429, "Sorry...")

		with ServidorSimulado(manejador) as srv:
			self.assertEqual(t.traducir("Hello", "auto", "es"), "Hola")
			self.assertEqual(t._ultimo_idioma_detectado, "en")
			# Tras el 429 se va directo al alternativo durante un rato.
			self.assertEqual(t.traducir("Hello", "auto", "es"), "Hola")
		urls = [p["url"] for p in srv.peticiones]
		self.assertEqual(sum("clients5" in u for u in urls), 2)
		self.assertLessEqual(sum("translate_a/single" in u for u in urls), 2)

	def test_google_texto_largo_en_trozos(self):
		t = traductor("TraductorGoogleApiFree", "google_api_free")
		largo = "Frase de prueba. " * 400
		with ServidorSimulado(lambda p: {"sentences": [{"trans": "T"}]}) as srv:
			self.assertEqual(t.traducir(largo, "es", "en"), "T" * len(srv.peticiones))
		self.assertGreater(len(srv.peticiones), 1)

	def test_deepl_gratuito(self):
		t = traductor("TraductorDeepLFree", "deepl_free")

		def manejador(p):
			self.assertEqual(p["metodo"], "POST")
			params = p["json"]["params"]
			self.assertEqual(params["lang"]["target_lang"], "EN")
			self.assertEqual(params["commonJobParams"], {"regionalVariant": "en-GB"})
			return {"jsonrpc": "2.0", "result": {"texts": [{"text": "Hello"}]}}

		with ServidorSimulado(manejador):
			self.assertEqual(t.traducir("Hola", "auto", "en-GB"), "Hello")
		with ServidorSimulado(lambda p: error_http(p["url"], 429)):
			self.assertIsNone(t.traducir("Hola", "auto", "en"))
		self.assertIn("limitado", t.ultimo_error)
		self.assertEqual(t.adaptar_idioma("no"), "NB")
		self.assertEqual(t.adaptar_idioma("zh-TW"), "ZH")

	def test_deepl_api_endpoints_y_rotacion(self):
		c = conClave(nuevaConfiguracion(), "deepl_api", "pro-1", "free-2:fx", rotacion=True)
		t = traductor("TraductorDeepLAPI", "deepl_api", c)

		def manejador(p):
			campos = urllib.parse.parse_qs(p["cuerpo"].decode())
			self.assertEqual(campos["target_lang"], ["EN-US"])
			if p["cabeceras"]["authorization"] == "DeepL-Auth-Key pro-1":
				self.assertTrue(p["url"].startswith("https://api.deepl.com/"))
				return error_http(p["url"], 456)
			self.assertTrue(p["url"].startswith("https://api-free.deepl.com/"))
			return {"translations": [{"text": "Hello", "detected_source_language": "ES"}]}

		with ServidorSimulado(manejador) as srv:
			self.assertEqual(t.traducir("Hola", "auto", "en"), "Hello")
		self.assertEqual(len(srv.peticiones), 2)
		self.assertEqual(c.obtener_api("deepl_api").api_key, "free-2:fx")
		with ServidorSimulado(lambda p: {"character_count": 10, "character_limit": 500000}):
			self.assertEqual(t.obtener_uso()["character_limit"], 500000)
		sin = traductor("TraductorDeepLAPI", "deepl_api")
		self.assertIsNone(sin.traducir("Hola"))

	def test_microsoft_token_y_renovacion(self):
		t = traductor("TraductorMicrosoftFree", "microsoft_free")
		estado = {"tokens": 0, "traducciones": 0}

		def manejador(p):
			if "edge.microsoft.com" in p["url"]:
				estado["tokens"] += 1
				return Respuesta(f"token{estado['tokens']}".encode())
			estado["traducciones"] += 1
			self.assertIn("to=zh-Hans", p["url"])
			if p["cabeceras"]["authorization"] == "Bearer token1":
				return error_http(p["url"], 401)
			self.assertEqual(p["json"], [{"Text": "Hello"}])
			return [{"translations": [{"text": "你好"}]}]

		with ServidorSimulado(manejador):
			self.assertEqual(t.traducir("Hello", "auto", "zh"), "你好")
		self.assertEqual(estado, {"tokens": 2, "traducciones": 2})

	def test_microsoft_respaldo_bing(self):
		t = traductor("TraductorMicrosoftFree", "microsoft_free")
		pagina = 'var x; IG:"IGPRUEBA", data-iid="translator.5023" params_AbusePreventionHelper = [1234,"TOKENPRUEBA",3600000];'

		def manejador(p):
			if "edge.microsoft.com" in p["url"]:
				return error_http(p["url"], 404)
			if p["url"] == "https://www.bing.com/translator":
				return Respuesta(pagina)
			self.assertRegex(p["url"], r"IG=IGPRUEBA&IID=translator\.5023\.\d+$")
			campos = urllib.parse.parse_qs(p["cuerpo"].decode())
			self.assertEqual((campos["fromLang"], campos["token"], campos["key"]), (["auto-detect"], ["TOKENPRUEBA"], ["1234"]))
			self.assertIn(campos["to"], (["es"], ["en"]))
			return [{"translations": [{"text": "Buenos días", "to": "es"}], "detectedLanguage": {"language": "en"}}]

		with ServidorSimulado(manejador) as srv:
			self.assertEqual(t.traducir("Good morning", "auto", "es"), "Buenos días")
			self.assertEqual(t.detectar_idioma("Good morning"), "en")
		# El token de Edge no se vuelve a pedir tras fallar.
		self.assertEqual(sum("edge.microsoft.com" in p["url"] for p in srv.peticiones), 1)

	def test_libretranslate(self):
		c = conClave(nuevaConfiguracion(), "libretranslate", "lt-key", api_url="http://localhost:5000/")
		t = traductor("TraductorLibreTranslate", "libretranslate", c)

		def manejador(p):
			self.assertTrue(p["url"].startswith("http://localhost:5000/"))
			self.assertEqual(p["json"]["api_key"], "lt-key")
			if p["url"].endswith("/detect"):
				return [{"language": "en", "confidence": 90}]
			self.assertEqual((p["json"]["source"], p["json"]["target"]), ("en", "zt"))
			return {"translatedText": "哈囉"}

		with ServidorSimulado(manejador):
			self.assertEqual(t.traducir("Hello", "auto", "zh-TW"), "哈囉")
		self.assertTrue(t.validar_api())

	def test_openai_parametros(self):
		c = conClave(nuevaConfiguracion(), "openai", "sk-a")
		t = traductor("TraductorOpenAI", "openai_gpt", c)

		def manejador(p):
			datos = p["json"]
			self.assertEqual(p["cabeceras"]["authorization"], "Bearer sk-a")
			self.assertEqual(datos["model"], "gpt-4o-mini")
			self.assertIn("español (es)", datos["messages"][1]["content"])
			if "max_completion_tokens" in datos:
				return error_http(p["url"], 400, {"error": {"message": "Unsupported parameter: 'max_completion_tokens'"}})
			return {"choices": [{"message": {"content": " Hola "}}]}

		with ServidorSimulado(manejador) as srv:
			self.assertEqual(t.traducir("Hello", "auto", "es"), "Hola")
		self.assertEqual(len(srv.peticiones), 2)

	def test_openai_rotacion(self):
		c = conClave(nuevaConfiguracion(), "openai", "sk-1", "sk-2", rotacion=True)
		t = traductor("TraductorOpenAI", "openai_gpt", c)

		def manejador(p):
			if p["cabeceras"]["authorization"] == "Bearer sk-1":
				return error_http(p["url"], 429, {"error": {"message": "quota"}})
			return {"choices": [{"message": {"content": "ok"}}]}

		with ServidorSimulado(manejador):
			self.assertEqual(t.traducir("x", "auto", "es"), "ok")

	def test_gemini(self):
		c = conClave(nuevaConfiguracion(), "gemini", "g-key")
		t = traductor("TraductorGemini", "gemini", c)

		def manejador(p):
			self.assertIn("/models/gemini-2.5-flash:generateContent", p["url"])
			self.assertNotIn("g-key", p["url"])
			self.assertEqual(p["cabeceras"]["x-goog-api-key"], "g-key")
			self.assertIn("system_instruction", p["json"])
			return {"candidates": [{"content": {"parts": [{"text": "Hola", "thought": False}]}}]}

		with ServidorSimulado(manejador):
			self.assertEqual(t.traducir("Hello", "auto", "es"), "Hola")
		with ServidorSimulado(lambda p: error_http(p["url"], 404, {"error": {"message": "model not found"}})):
			self.assertIsNone(t.traducir("Hello", "auto", "es"))
		self.assertIn("nombre del modelo", t.ultimo_error)

	def test_deepseek(self):
		c = conClave(nuevaConfiguracion(), "deepseek", "ds")
		t = traductor("TraductorDeepSeek", "deepseek", c)
		with ServidorSimulado(lambda p: {"choices": [{"message": {"content": "Hola"}}]}) as srv:
			self.assertEqual(t.traducir("Hello", "auto", "es"), "Hola")
		self.assertEqual(srv.peticiones[0]["json"]["model"], "deepseek-chat")
		with ServidorSimulado(lambda p: error_http(p["url"], 402)):
			self.assertIsNone(t.traducir("Hello", "auto", "es"))
		self.assertIn("saldo", t.ultimo_error)

	def test_claude(self):
		c = conClave(nuevaConfiguracion(), "claude", "sk-ant")
		t = traductor("TraductorClaude", "claude", c)

		def manejador(p):
			h = p["cabeceras"]
			self.assertEqual(h["x-api-key"], "sk-ant")
			self.assertEqual(h["anthropic-version"], "2023-06-01")
			self.assertEqual(h["anthropic-beta"], "server-side-fallback-2026-07-01")
			d = p["json"]
			self.assertEqual(d["model"], "claude-opus-5-5")
			self.assertEqual(d["output_config"], {"effort": "low"})
			self.assertEqual(d["fallbacks"], "default")
			self.assertNotIn("thinking", d)
			self.assertNotIn("temperature", d)
			return {"content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": "Hola"}], "stop_reason": "end_turn"}

		with ServidorSimulado(manejador):
			self.assertEqual(t.traducir("Hello", "auto", "es"), "Hola")
		with ServidorSimulado(lambda p: {"content": [], "stop_reason": "refusal", "stop_details": {"explanation": "no"}}):
			self.assertIsNone(t.traducir("Hello", "auto", "es"))
		self.assertIn("rehusado", t.ultimo_error)

	def test_claude_sin_respaldo_y_modelo_antiguo(self):
		c = conClave(nuevaConfiguracion(), "claude", "sk-ant", modelo="claude-haiku-4-5")
		t = traductor("TraductorClaude", "claude", c)
		with ServidorSimulado(lambda p: {"content": [{"type": "text", "text": "ok"}]}) as srv:
			self.assertEqual(t.traducir("x", "auto", "es"), "ok")
		d = srv.peticiones[0]["json"]
		self.assertNotIn("fallbacks", d)
		self.assertNotIn("output_config", d)
		c.establecer_api("claude", claves=c.obtener_api("claude").claves, modelo="claude-opus-5-5")

		def manejador(p):
			if "fallbacks" in p["json"]:
				return error_http(p["url"], 400, {"error": {"message": "fallbacks: unknown beta"}})
			return {"content": [{"type": "text", "text": "ok2"}]}

		with ServidorSimulado(manejador) as srv:
			self.assertEqual(t.traducir("x", "auto", "es"), "ok2")
		self.assertNotIn("anthropic-beta", srv.peticiones[1]["cabeceras"])

	def test_gestor_traductores_y_usuario(self):
		c = nuevaConfiguracion()
		with open(os.path.join(c.ruta_traductores_usuario, "mio.py"), "w", encoding="utf-8") as f:
			f.write("from ..nucleo.gestor_traductores import TraductorBase\n\nclass Mio(TraductorBase):\n\tid = 'mio'\n\tnombre = 'Mi traductor'\n\tdef traducir(self, texto, idioma_origen='auto', idioma_destino='es', **kw):\n\t\treturn texto.upper()\n")
		g = gt_mod.GestorTraductores(c, os.path.join(ADDON, "globalPlugins", "TraductorAvanzadoPro", "traductores"), tap.__name__, c.ruta_traductores_usuario)
		g.cargar_traductores()
		ids = set(g.traductores)
		self.assertEqual(ids, {"google_api_free", "deepl_free", "deepl_api", "microsoft_free", "libretranslate", "openai", "gemini", "deepseek", "claude", "mio"})
		self.assertEqual(g.errores, [])
		self.assertEqual(g.obtener_traductor("mio").traducir("hola"), "HOLA")
		lista = g.listar_traductores()
		self.assertFalse(lista[0]["requiere_api"])
		c.config.servicio_activo = "no_existe"
		try:
			self.assertEqual(g.obtener_traductor_activo().id, "google_api_free")
		finally:
			c.config.servicio_activo = "google_api_free"
		self.assertTrue(g.recargar_traductor("claude"))


# ====================================================================== plugins
class PruebasPlugins(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.c = nuevaConfiguracion()
		cls.gestor = gp_mod.GestorPlugins(cls.c, os.path.join(ADDON, "globalPlugins", "TraductorAvanzadoPro", "plugins"), tap.__name__, cls.c.ruta_plugins_usuario)
		cls.gestor.cargar_plugins(None)

	def test_carga(self):
		self.assertEqual(set(self.gestor.plugins), {"detector_google", "detector_idioma", "diccionario", "historial_inteligente", "ocr_traductor"})
		self.assertEqual(self.gestor.errores, [])
		self.assertIn("traducir_ocr", self.gestor._hooks)

	def test_desactivar_desde_opciones(self):
		self.c.config.plugins_desactivados = ["diccionario"]
		try:
			self.gestor.aplicar_desactivados()
			self.assertIsNone(self.gestor.obtener_plugin("diccionario"))
			with self.assertRaises(RuntimeError):
				self.gestor.ejecutar_plugin("diccionario", "x")
			self.assertEqual(self.gestor.ejecutar_hook("obtener_sinonimos", "x"), [])
		finally:
			self.c.config.plugins_desactivados = []
			self.gestor.aplicar_desactivados()
		self.assertIsNotNone(self.gestor.obtener_plugin("diccionario"))

	def test_detector_local(self):
		d = self.gestor.obtener_plugin("detector_idioma")
		self.assertEqual(d.ejecutar("el perro de la casa es grande y bonito")["idioma"], "es")
		self.assertEqual(d.ejecutar("the dog is in the house with the cat")["idioma"], "en")
		self.assertEqual(d.ejecutar("Привет мир, как дела")["idioma"], "ru")
		self.assertEqual(d.ejecutar("こんにちは世界")["idioma"], "ja")
		self.assertIn("Confianza", d.obtener_descripcion_detallada("bonjour le monde et la vie"))

	def test_detector_google(self):
		d = self.gestor.obtener_plugin("detector_google")
		with ServidorSimulado(lambda p: [[["Hello", "Hola"]], None, "es"]):
			self.assertEqual(d.detectar("Hola"), "es")
		with ServidorSimulado(lambda p: urllib.error.URLError("x")):
			self.assertIsNone(d.detectar("Hola"))

	def test_diccionario(self):
		d = self.gestor.obtener_plugin("diccionario")
		respuesta = [{"word": "house", "phonetic": "/haʊs/", "meanings": [{"partOfSpeech": "noun", "definitions": [{"definition": "A building.", "example": "a big house", "synonyms": ["home"]}], "synonyms": ["home", "dwelling"], "antonyms": []}]}]
		with ServidorSimulado(lambda p: respuesta):
			r = d.ejecutar("House")
			texto = d.obtener_texto_formateado("house")
		self.assertEqual(r["fonetica"], "/haʊs/")
		self.assertEqual(r["sinonimos"], ["home", "dwelling"])
		self.assertIn("=== HOUSE ===", texto)
		self.assertIn("Ejemplo", texto)
		with ServidorSimulado(lambda p: error_http(p["url"], 404)):
			self.assertIsNone(d.ejecutar("zzzz"))
			self.assertIsNone(d.ultimo_error)

	def test_diccionario_wiktionary(self):
		d = self.gestor.obtener_plugin("diccionario")
		wikt = {"es": [{"partOfSpeech": "Noun", "language": "Spanish", "definitions": [{"definition": "<a href='/wiki/house'>house</a>, home<style>.x{}</style>", "examples": ["Mi <b>casa</b> es tu casa."]}]}]}

		def manejador(p):
			if "dictionaryapi.dev" in p["url"]:
				return error_http(p["url"], 522)
			self.assertIn("en.wiktionary.org/api/rest_v1/page/definition/casa", p["url"])
			self.assertIn("Tiresias", p["cabeceras"]["user-agent"])
			return wikt

		with ServidorSimulado(manejador):
			r = d.ejecutar("casa")
		self.assertEqual(r["definiciones"][0], {"tipo": "Noun, Spanish", "definicion": "house, home", "ejemplo": "Mi casa es tu casa."})

	def test_diccionario_multilingue(self):
		d = self.gestor.obtener_plugin("diccionario")
		traductor_falso = mock.Mock()
		traductor_falso.traducir.side_effect = lambda t, idioma_origen, idioma_destino: "house" if idioma_destino == "en" else "TRADUCIDO"
		principal = types.SimpleNamespace(gestor_traductores=mock.Mock(obtener_traductor_activo=lambda: traductor_falso))
		d.plugin_principal = principal
		respuesta = [{"word": "house", "meanings": [{"partOfSpeech": "noun", "definitions": [{"definition": "A building."}]}]}]

		def manejador(p):
			return respuesta if p["url"].endswith("/en/house") else error_http(p["url"], 404)

		destino = self.c.config.idioma_destino
		self.c.config.idioma_destino = "es"
		try:
			with ServidorSimulado(manejador):
				texto, palabra = d.buscar_multilingue("casa")
		finally:
			self.c.config.idioma_destino = destino
			d.plugin_principal = None
		self.assertEqual(palabra, "house")
		self.assertIn("«casa» en inglés: house", texto)
		self.assertIn("TRADUCIDO", texto)

	def test_historial_inteligente(self):
		h = historial_mod.GestorHistorial(nuevaConfiguracion())
		h.agregar("hello", "hola", "en", "es", "google_api_free")
		h.agregar("bye", "au revoir", "en", "fr", "deepl_free")
		h.agregar("cat", "gato", "en", "es", "google_api_free")
		p = self.gestor.obtener_plugin("historial_inteligente")
		p.establecer_historial(h)
		stats = p.obtener_estadisticas()
		self.assertEqual((stats["total"], stats["idioma_mas_usado"], stats["servicio_mas_usado"]), (3, "es", "google_api_free"))
		self.assertEqual(len(p.buscar_avanzado("", {"idioma": "fr"})), 1)
		self.assertEqual(len(p.buscar_avanzado("GAT", {"servicio": "google_api_free"})), 1)
		carpeta = tempfile.mkdtemp(dir=_TMP)
		ruta_csv = p.exportar_csv(os.path.join(carpeta, "h.csv"))
		with open(ruta_csv, encoding="utf-8-sig") as f:
			contenido = f.read()
		self.assertIn("Texto Original;Traducción", contenido)
		self.assertIn("cat;gato", contenido)
		ruta_json = p.ejecutar("exportar_json", ruta=os.path.join(carpeta, "h.json"))
		with open(ruta_json, encoding="utf-8") as f:
			self.assertEqual(len(json.load(f)), 3)
		self.assertIn("Total de traducciones: 3", p.obtener_resumen_texto())

	def test_ocr_reconocer(self):
		p = self.gestor.obtener_plugin("ocr_traductor")
		linea = types.SimpleNamespace(text="Hello OCR")
		with mock.patch("tiresias.imaging.captureRect", return_value=object()), mock.patch("tiresias.ocr.recognizeImage", return_value=[linea, types.SimpleNamespace(text=" ")]):
			self.assertEqual(p.reconocer((0, 0, 10, 10)), "Hello OCR")


# ====================================================================== complemento global
class TraductorFalso:
	id = "falso"
	nombre = "Falso"
	soporta_deteccion = True
	ultimo_error = None

	def __init__(self) -> None:
		self.llamadas: list[tuple] = []

	def traducir(self, texto, idioma_origen="auto", idioma_destino="es", **kw):
		self.llamadas.append((texto, idioma_origen, idioma_destino))
		return f"[{idioma_destino}] {texto}"

	def detectar_idioma(self, texto):
		return "es"


class Gesto:
	def __init__(self, *ids: str) -> None:
		self.identifiers = list(ids)


class PruebasComplemento(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		from tiresias import gui
		from tiresias.gui import settings
		from tiresias.speech import api as speechApi

		cls.speechApi = speechApi
		cls.plugin = tap.GlobalPlugin()
		cls.gui = gui
		cls.settings = settings

	@classmethod
	def tearDownClass(cls):
		cls.plugin.terminate()

	def setUp(self):
		self.plugin._traduccion_activa = False
		self.plugin._traduccion_en_curso = False
		self.plugin.configuracion.cache_habilitada = True
		self.plugin.configuracion.intercambio_automatico_idioma = False
		self.plugin.configuracion.idioma_origen = "auto"
		self.plugin.configuracion.idioma_destino = "es"
		self.plugin.configuracion.idioma_destino_alternativo = "en"

	def test_inicio_registra_todo(self):
		p = self.plugin
		self.assertTrue(p._inicializado)
		self.assertIn(p._filtrar_secuencia_voz, self.speechApi.filter_speechSequence.handlers())
		self.assertIn("TraductorAvanzadoPro", self.settings._panels)
		self.assertIn("TraductorAvanzadoPro", self.gui._addonToolsEntries)
		etiqueta, accion, submenu = self.gui._addonToolsEntries["TraductorAvanzadoPro"]
		self.assertTrue(submenu)
		entradas = accion()
		self.assertIn("&Configuración...", [e[0] for e in entradas if e])
		self.assertIn("&Apoyar el proyecto", [e[0] for e in entradas if e])
		self.assertEqual(len(p.gestor_traductores.traductores), 9)
		self.assertEqual(len(p.gestor_plugins.plugins), 5)
		self.assertTrue(p.configuracion.ruta_config.endswith(os.path.join("addonsData", "TraductorAvanzadoPro")))

	def test_gestos_y_descripciones(self):
		cls = type(self.plugin)
		gestos = dict(cls.iterClassGestures())
		self.assertEqual(gestos["kb:tiresias+control+shift+t"], "activar_capa_comandos")
		self.assertEqual(gestos["kb:tiresias+control+shift+g"], "detectar_idioma")
		ordenes = [n for n in dir(cls) if n.startswith("script_")]
		self.assertGreaterEqual(len(ordenes), 24)
		for n in ordenes:
			f = getattr(cls, n)
			self.assertTrue(f.__doc__, n)
			self.assertEqual(f.category, "Traductor Avanzado Pro", n)
		for nombre in tap.GESTOS_CAPA.values():
			self.assertTrue(hasattr(cls, "script_" + nombre), nombre)

	def test_capa_de_ordenes(self):
		p = self.plugin
		with mock.patch.object(p.gestor_sonidos, "reproducir") as sonar:
			p._activar_capa()
			self.assertTrue(p._capa_comandos_activa)
			sonar.assert_called_with("abrir")
			f = p.getScript(Gesto("kb(desktop):t", "kb:t"))
			self.assertEqual(f.__name__, "script_alternar_traduccion")
			self.assertTrue(p._capa_comandos_activa)
			self.assertEqual(p.getScript(Gesto("kb(desktop):escape", "kb:escape")).__name__, "script_cerrar_capa")
			# Una tecla que no es de la capa la cierra y no se queda con ella.
			self.assertIsNone(p.getScript(Gesto("kb(desktop):q", "kb:q")))
			self.assertFalse(p._capa_comandos_activa)
			self.assertIsNone(p.getScript(Gesto("kb(desktop):t", "kb:t")))
			self.assertEqual(p.getScript(Gesto("kb(desktop):tiresias+control+shift+t", "kb:tiresias+control+shift+t")).__name__, "script_activar_capa_comandos")
			# Con la capa abierta, su propio atajo la cierra (no la vuelve a abrir).
			p._activar_capa()
			f = p.getScript(Gesto("kb(desktop):tiresias+control+shift+t", "kb:tiresias+control+shift+t"))
			self.assertTrue(p._capa_comandos_activa)
			f(None)
			self.assertFalse(p._capa_comandos_activa)
			sonar.assert_called_with("cerrar")

	def test_filtro_inactivo_y_ultimo_hablado(self):
		p = self.plugin
		seq = ["Archivo", "menú"]
		self.assertIs(p._filtrar_secuencia_voz(seq), seq)
		self.assertEqual(p._ultimo_texto_hablado, "Archivo menú")
		lector.mensajes_recientes.append("Mensaje propio")
		p._filtrar_secuencia_voz(["Mensaje propio"])
		self.assertEqual(p._ultimo_texto_hablado, "Archivo menú")

	def test_filtro_activo_cache_y_cola(self):
		p = self.plugin
		p.cache.guardar("File", "Archivo", "es", app=lector.app_actual() or None)
		p._traduccion_activa = True
		from tiresias.speech.commands import BreakCommand

		orden = BreakCommand(10)
		with mock.patch.object(p.traductor_async, "encolar") as encolar:
			nueva = p._filtrar_secuencia_voz(["File", orden, "Edit", "..."])
		self.assertEqual(nueva, ["Archivo", orden, "Edit", "..."])
		encolar.assert_called_once()
		self.assertEqual(encolar.call_args[0][0], "Edit")
		# Las traducciones propias no se vuelven a traducir.
		p._textos_propios.add("Editar")
		with mock.patch.object(p.traductor_async, "encolar") as encolar:
			self.assertEqual(p._filtrar_secuencia_voz(["Editar"]), ["Editar"])
		encolar.assert_not_called()

	def test_filtro_escritura_y_silencio(self):
		p = self.plugin
		p._traduccion_activa = True
		with mock.patch.object(p.traductor_async, "encolar") as encolar, self.speechApi.speechOrigin(self.speechApi.ORIGIN_TYPING):
			p._filtrar_secuencia_voz(["hola"])
		encolar.assert_not_called()
		lector.silenciar_sintetizador(0.3)
		self.assertEqual(p._filtrar_secuencia_voz(["algo"]), [])
		time.sleep(0.35)
		self.assertFalse(lector.silenciado())

	def test_filtro_integrado_en_speak(self):
		"""El filtro se aplica de verdad dentro de ``speech.speak``."""
		p = self.plugin
		p.cache.guardar("Open", "Abrir", "es", app=lector.app_actual() or None)
		p._traduccion_activa = True
		vistos = []
		with mock.patch.object(self.speechApi, "getManager") as gestor, mock.patch.object(p.traductor_async, "encolar"):
			gestor.return_value.speak.side_effect = lambda seq, *a, **k: vistos.append([i for i in seq if isinstance(i, str)])
			self.speechApi.speak(["Open"])
		self.assertTrue(vistos)
		self.assertIn("Abrir", " ".join(vistos[0]))

	def test_traducir_texto_cache_historial_e_intercambio(self):
		p = self.plugin
		falso = TraductorFalso()
		with mock.patch.object(p.gestor_traductores, "obtener_traductor_activo", return_value=falso):
			self.assertEqual(p._traducir_texto("hello world", "app"), "[es] hello world")
			self.assertEqual(p._traducir_texto("hello world", "app"), "[es] hello world")
			self.assertEqual(len(falso.llamadas), 1)
			self.assertEqual(p.historial.obtener_ultimo().texto_traducido, "[es] hello world")
			p.configuracion.intercambio_automatico_idioma = True
			with mock.patch.object(p.gestor_plugins.plugins["detector_google"], "detectar", return_value="es"):
				self.assertEqual(p._traducir_texto("hola amigo", "app"), "[en] hola amigo")
			p.configuracion.intercambio_automatico_idioma = False
			falso.traducir = lambda *a, **k: None
			falso.ultimo_error = "fallo simulado"
			self.assertIsNone(p._traducir_texto("otra cosa", "app"))
			self.assertEqual(p._ultimo_error, "fallo simulado")

	def test_traduccion_asincrona(self):
		p = self.plugin
		falso = TraductorFalso()
		p._traduccion_activa = True
		hablado = threading.Event()
		dichos = []

		def hablar(t):
			dichos.append(t)
			hablado.set()

		with mock.patch.object(p.gestor_traductores, "obtener_traductor_activo", return_value=falso), mock.patch.object(p, "_hablar_traduccion", side_effect=hablar):
			self.assertTrue(p.traductor_async.encolar("asynchronous text", "app"))
			self.assertFalse(p.traductor_async.encolar("asynchronous text", "app"))
			self.assertTrue(hablado.wait(5))
		self.assertEqual(dichos, ["[es] asynchronous text"])
		self.assertEqual(p._ultimo_texto_traducido, "[es] asynchronous text")

	def test_ordenes_basicas(self):
		p = self.plugin
		dichos = []
		with mock.patch.object(lector, "mensaje", side_effect=dichos.append):
			p.script_intercambiar_idiomas(None)
			self.assertEqual((p.configuracion.idioma_destino, p.configuracion.idioma_destino_alternativo), ("en", "es"))
			p.script_alternar_intercambio_auto(None)
			self.assertTrue(p.configuracion.intercambio_automatico_idioma)
			p.script_alternar_cache(None)
			self.assertFalse(p.configuracion.cache_habilitada)
			p.script_alternar_cache(None)
			p._ultimo_texto_traducido = None
			p.script_copiar_ultima_traduccion(None)
			with mock.patch.object(p, "_veces_pulsado", return_value=0):
				p.script_limpiar_toda_cache(None)
			with mock.patch.object(p.cache, "limpiar") as limpiar, mock.patch.object(p, "_veces_pulsado", return_value=1):
				p.script_limpiar_toda_cache(None)
			limpiar.assert_called_once_with()
			p._traduccion_activa = True
			p.script_traducir_portapapeles(None)
			p._traduccion_activa = False
		self.assertIn("Idiomas intercambiados. Nuevo destino: Inglés", dichos)
		self.assertIn("Intercambio automático activado", dichos)
		self.assertIn("Caché de traducción desactivada", dichos)
		self.assertIn("No hay traducción para copiar", dichos)
		self.assertIn("Pulse dos veces para limpiar toda la caché de todas las aplicaciones", dichos)
		self.assertIn("Toda la caché de traducción ha sido limpiada", dichos)
		self.assertIn("Desactive la traducción simultánea para realizar esta acción.", dichos)

	def test_traducir_portapapeles_y_mostrar(self):
		p = self.plugin
		falso = TraductorFalso()
		dichos = []
		listo = threading.Event()
		with mock.patch.object(p.monitor_portapapeles, "obtener_texto", return_value="clipboard text"), mock.patch.object(p.gestor_traductores, "obtener_traductor_activo", return_value=falso), mock.patch.object(lector, "hablar_texto", side_effect=lambda t, siguiente=False: (dichos.append(t), listo.set())):
			p.configuracion.mostrar_resultados = False
			p.script_traducir_portapapeles(None)
			self.assertTrue(listo.wait(5))
		self.assertEqual(dichos, ["[es] clipboard text"])
		self.assertFalse(p._traduccion_en_curso)

	def test_alternar_traduccion(self):
		p = self.plugin
		with mock.patch.object(lector, "mensaje") as mensaje:
			p.script_alternar_traduccion(None)
			self.assertTrue(p._traduccion_activa)
			p.script_alternar_traduccion(None)
			self.assertFalse(p._traduccion_activa)
		self.assertEqual([c.args[0] for c in mensaje.call_args_list], ["Traducción activada", "Traducción desactivada"])

	def test_sonidos(self):
		s = self.plugin.gestor_sonidos
		self.assertTrue(s.existe_sonido("abrir"))
		self.assertTrue(s.existe_sonido("cerrar"))
		self.assertEqual(s.listar_sonidos(), ["close", "open"])
		datos, frecuencia, canales = s._leer(s._ruta("abrir"))
		self.assertEqual((frecuencia, canales), (44100, 2))
		self.assertGreater(len(datos), 1000)
		with mock.patch("tiresias.audio.wave_player.WavePlayer") as Rep:
			self.assertTrue(s.reproducir("abrir"))
		Rep.return_value.feed.assert_called_once()
		self.assertGreater(Rep.return_value.volume, 0)


# ====================================================================== interfaz (ventanas ocultas)
class PruebasInterfaz(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		import wx

		cls.wx = wx
		cls.app = wx.App.Get() or wx.App(False)
		cls.plugin = tap.GlobalPlugin()
		cls.dialogos = import_module(tap.__name__ + ".interfaces.dialogos")
		cls.panel_mod = import_module(tap.__name__ + ".interfaces.panel_opciones")

	@classmethod
	def tearDownClass(cls):
		cls.plugin.terminate()

	def test_dialogo_traduccion(self):
		d = self.dialogos.DialogoTraduccion(self.plugin, "Hello")
		try:
			self.assertEqual(d.lbl_contador.GetValue(), "5")
			self.assertIn("Interfaz de traducción - ", d.GetTitle())
			self.dialogos._seleccionar_codigo(d.combo_origen, "en")
			self.dialogos._seleccionar_codigo(d.combo_destino, "es")
			d.txt_destino.SetValue("Hola")
			with mock.patch.object(lector, "mensaje"):
				d._on_intercambiar(None)
			self.assertEqual((self.dialogos._codigo(d.combo_origen), self.dialogos._codigo(d.combo_destino)), ("es", "en"))
			self.assertEqual(d.txt_origen.GetValue(), "Hola")
			self.assertIsNotNone(d.ayuda.texto_ayuda(d.btn_pegar))
		finally:
			d.Destroy()

	def test_historial_y_exportar(self):
		self.plugin.historial.agregar("one", "uno", "en", "es", "google_api_free")
		self.plugin.historial.agregar("two", "dos", "en", "es", "deepl_free")
		d = self.dialogos.DialogoHistorial(self.plugin)
		try:
			self.assertGreaterEqual(d.lista.GetItemCount(), 2)
			d.txt_buscar.SetValue("dos")
			d.refiltrar()
			self.assertEqual(d.lista.GetItemCount(), 1)
			self.assertIn("two", d.txt_completo.GetValue())
		finally:
			d.Destroy()

	def test_gestion_api_y_configuracion_ia(self):
		c = nuevaConfiguracion()
		d = self.dialogos.DialogoGestionAPI(None, c, "openai", "OpenAI GPT")
		try:
			d.txt_nueva_clave.SetValue("sk-1111111111")
			with mock.patch.object(lector, "mensaje"):
				d._on_anadir(None)
			d.txt_nueva_clave.SetValue("sk-2222222222")
			d.txt_url.SetValue("http://localhost:1234/v1")
			d.chk_rotacion.SetValue(True)
			with mock.patch.object(d, "EndModal"):
				d._on_guardar(None)
		finally:
			d.Destroy()
		sc = c.obtener_api("openai")
		self.assertEqual(sc.claves_planas(), ["sk-1111111111", "sk-2222222222"])
		self.assertTrue(sc.usar_rotacion)
		self.assertEqual(sc.api_url, "http://localhost:1234/v1")
		with ServidorSimulado(lambda p: {"data": [{"id": "gpt-x"}]}):
			ia = self.dialogos.DialogoConfiguracionIA(None, c, "openai", "OpenAI GPT", "gpt-4o-mini")
			try:
				ia.combo_modelo.SetValue("gpt-x")
				ia.txt_usuario.SetValue("Traduce al {idioma_destino}: {texto}")
				with mock.patch.object(ia, "EndModal"):
					ia._on_guardar(None)
			finally:
				ia.Destroy()
		self.assertEqual(c.obtener_api("openai").modelo, "gpt-x")
		self.assertEqual(c.obtener_api("openai").prompt_usuario, "Traduce al {idioma_destino}: {texto}")

	def test_seleccion_rapida_e_idiomas(self):
		d = self.dialogos.DialogoSeleccionRapida(self.plugin)
		try:
			self.dialogos._seleccionar_codigo(d.combo_servicio, "microsoft_free")
			d._on_servicio_cambiado(None)
			self.assertFalse(d.combo_modelo.IsEnabled())
			self.dialogos._seleccionar_codigo(d.combo_destino, "fr")
			with mock.patch.object(lector, "mensaje") as m:
				self.plugin._aplicar_seleccion_rapida(d.obtener_valores())
			self.assertEqual(self.plugin.configuracion.servicio_activo, "microsoft_free")
			self.assertEqual(self.plugin.configuracion.idioma_destino, "fr")
			self.assertIn("Microsoft Translator", m.call_args[0][0])
		finally:
			d.Destroy()
			self.plugin.configuracion.servicio_activo = "google_api_free"
		di = self.dialogos.DialogoIdiomas(self.plugin, "origen")
		try:
			di.txt_busqueda.SetValue("alem")
			self.assertEqual(di.lista_idiomas.GetCount(), 1)
			with mock.patch.object(lector, "mensaje"):
				di._on_aceptar(None)
			self.assertEqual(self.plugin.configuracion.idioma_origen, "de")
		finally:
			self.plugin.configuracion.idioma_origen = "auto"

	def test_panel_opciones(self):
		frame = self.wx.Frame(None)
		try:
			panel = self.panel_mod.PanelTraductor(frame)
			self.assertGreaterEqual(panel.lista_servicios.GetCount(), 9)
			self.assertIn("Claude", " ".join(panel.lista_servicios.GetStrings()))
			self.assertEqual(panel.lista_plugins.GetCount(), 5)
			self.assertIn("claude", panel._resumenes)
			panel.lista_plugins.Check(0, False)
			panel.onSave()
			self.assertEqual(len(conf[SECCION]["plugins_desactivados"]), 1)
			panel.resetToFactory()
			panel.onSave()
			self.assertEqual(conf[SECCION]["plugins_desactivados"], [])
		finally:
			frame.Destroy()

	def test_resultado_y_progreso(self):
		resultado = import_module(tap.__name__ + ".interfaces.resultado")
		d = resultado.DialogoResultado(None, "Hello", "Hola", self.plugin.monitor_portapapeles)
		self.assertEqual(d.txt_traducido.GetValue(), "Hola")
		d.Destroy()
		progreso = import_module(tap.__name__ + ".interfaces.progreso").DialogoProgreso(None, "P", "m")
		self.assertTrue(progreso.actualizar(50, "mitad"))
		self.assertEqual(progreso.lbl_porcentaje.GetLabel(), "50%")
		progreso.Destroy()

	def test_reproductor_carga_sin_sonar(self):
		reproductor = import_module(tap.__name__ + ".interfaces.reproductor")
		buf = io.BytesIO()
		with wave.open(buf, "wb") as w:
			w.setnchannels(1)
			w.setsampwidth(2)
			w.setframerate(8000)
			w.writeframes(b"\x00\x00" * 800)
		d = reproductor.DialogoReproductor(None, self.plugin, "Hola", buf.getvalue())
		try:
			self.assertTrue(os.path.isfile(d.player.temp_file))
			temporal = d.player.temp_file
			with mock.patch.object(lector, "mensaje") as m:
				d._cambiar_volumen(-50)
				d._cambiar_velocidad(1)
			self.assertEqual(m.call_args_list[0].args[0], f"Volumen {max(0, d.snd_vol - 50)}%")
			self.assertEqual(reproductor.formatear_tiempo(65000), "01:05")
			d._fijar_atras(3)
			d._on_close(None)
			self.assertFalse(os.path.exists(temporal))
			self.assertEqual(conf[SECCION]["salto_atras"], 3)
		finally:
			conf[SECCION]["salto_atras"] = 1
			conf[SECCION]["velocidad_audio"] = 2
			conf[SECCION]["volumen_reproductor"] = 50


class PruebasTerminar(unittest.TestCase):
	def test_terminate_lo_quita_todo(self):
		from tiresias import gui
		from tiresias.gui import settings
		from tiresias.speech import api as speechApi

		plugin = tap.GlobalPlugin()
		self.assertTrue(plugin._inicializado)
		plugin.terminate()
		self.assertNotIn(plugin._filtrar_secuencia_voz, speechApi.filter_speechSequence.handlers())
		self.assertNotIn("TraductorAvanzadoPro", settings._panels)
		self.assertNotIn("TraductorAvanzadoPro", gui._addonToolsEntries)
		self.assertTrue(plugin.traductor_async._detenido)
		plugin.terminate()


# ====================================================================== red real (solo lectura)
class PruebasRedReal(unittest.TestCase):
	"""Peticiones reales a los servicios gratuitos sin clave (se saltan sin red)."""

	def _o_saltar(self, funcion):
		try:
			resultado = funcion()
		except red.ErrorRed as e:
			self.skipTest(f"Sin red: {e}")
		return resultado

	def test_google_real(self):
		t = traductor("TraductorGoogleApiFree", "google_api_free")
		res = t.traducir("Good morning, my friend", "en", "es")
		if res is None:
			self.skipTest(f"Google no disponible: {t.ultimo_error}")
		self.assertIn("amigo", res.lower())
		self.assertEqual(t.detectar_idioma("Bonjour tout le monde"), "fr")

	def test_microsoft_real(self):
		t = traductor("TraductorMicrosoftFree", "microsoft_free")
		res = t.traducir("Good morning", "en", "es")
		if res is None:
			self.skipTest(f"Microsoft no disponible: {t.ultimo_error}")
		self.assertIn("buen", res.lower())

	def test_detector_google_real(self):
		d = import_module(tap.__name__ + ".plugins.detector_google").PluginDetectorGoogle(nuevaConfiguracion(), None)
		codigo = d.detectar("Ceci est une phrase en français")
		if codigo is None:
			self.skipTest("Google no disponible")
		self.assertEqual(codigo, "fr")

	def test_tts_google_real(self):
		g = tts_mod.GestorTTSGoogle()
		audio = g.obtener_audio("Hola", "es")
		if audio is None:
			self.skipTest(f"TTS no disponible: {g.ultimo_error}")
		self.assertGreater(len(audio), 1000)

	def test_deepl_gratuito_real(self):
		t = traductor("TraductorDeepLFree", "deepl_free")
		res = t.traducir("Good morning", "auto", "es")
		if res is None:
			self.skipTest(f"DeepL gratuito no disponible: {t.ultimo_error}")
		self.assertTrue(res.strip())

	def test_diccionario_real(self):
		c = nuevaConfiguracion()
		dic = import_module(tap.__name__ + ".plugins.diccionario").PluginDiccionario(c, None)
		r = dic.ejecutar("house")
		if r is None:
			self.skipTest(f"Diccionario no disponible: {dic.ultimo_error}")
		self.assertTrue(r["definiciones"])


if __name__ == "__main__":
	unittest.main()
