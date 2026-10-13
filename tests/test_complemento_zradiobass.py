"""Pruebas del complemento zRadio BASS (complementos_tienda/zRadioBASS).

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_complemento_zradiobass -v``

Incluye pruebas de red reales de solo lectura contra la API de Radio Browser
y una prueba de BASS que abre una emisora real unos segundos en el
dispositivo «sin sonido» de BASS (device 0) y con volumen 0: no suena nada
por los altavoces. Si no hay Internet, esas pruebas se omiten.
"""

from __future__ import annotations

import ctypes
import json
import os
import socket
import sys
import tempfile
import threading
import time
import types
import unittest
from datetime import datetime, timedelta
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_zradiobass_")
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]
else:
	_TMP = paths._dataDirForTests  # type: ignore[attr-defined]

ADDON_DIR = os.path.join(ROOT, "complementos_tienda", "zRadioBASS")
PKG_DIR = os.path.join(ADDON_DIR, "globalPlugins", "zRadioBASS")
PKG = "zradiobass_pruebas"

# Paquete del complemento sin ejecutar su __init__ (que crea el GlobalPlugin).
_pkg = types.ModuleType(PKG)
_pkg.__path__ = [PKG_DIR]  # type: ignore[attr-defined]
sys.modules.setdefault(PKG, _pkg)

from tiresias.config import conf  # noqa: E402

import importlib  # noqa: E402

app_mod = importlib.import_module(f"{PKG}.zr_core.app")
api_client = importlib.import_module(f"{PKG}.zr_core.api_client")
bassmod = importlib.import_module(f"{PKG}.zr_core.bass")
config_mod = importlib.import_module(f"{PKG}.zr_core.config")
database = importlib.import_module(f"{PKG}.zr_core.database")
events = importlib.import_module(f"{PKG}.zr_core.events")
internet = importlib.import_module(f"{PKG}.zr_core.internet")
localization = importlib.import_module(f"{PKG}.zr_core.localization")
models = importlib.import_module(f"{PKG}.zr_core.models")
net = importlib.import_module(f"{PKG}.zr_core.net")
player_mod = importlib.import_module(f"{PKG}.zr_core.player")
plugin_manager = importlib.import_module(f"{PKG}.zr_core.plugin_manager")
recording = importlib.import_module(f"{PKG}.zr_core.recording")

EventType = events.EventType
Station = models.Station
Favorite = models.Favorite
Category = models.Category


def _online() -> bool:
	try:
		with socket.create_connection(("all.api.radio-browser.info", 443), timeout=5):
			return True
	except OSError:
		return False


ONLINE = _online()


def _newDir(name: str) -> str:
	d = tempfile.mkdtemp(prefix=f"zr_{name}_", dir=_TMP)
	return d


def _wait(cond, timeout: float = 5.0) -> bool:
	end = time.time() + timeout
	while time.time() < end:
		if cond():
			return True
		time.sleep(0.02)
	return cond()


# ====================================================================== BASS simulado
class FakeBass:
	"""Imita lo que el reproductor usa de :class:`bass.Bass` (sin DLL ni sonido)."""

	def __init__(self) -> None:
		self.next = 100
		self.active: dict[int, int] = {}
		self.attrs: dict[tuple[int, int], float] = {}
		self.freed: list[int] = []
		self.encoders: dict[int, str] = {}
		self.stopped_encoders: list[int] = []
		self.title = ""
		self.fail_open = False
		self.plugins = {"basshls.dll": 1}
		self.canRecord = True
		self.hasEffects = True
		self.versionText = "2.4.16.7"
		self.fx_calls: list = []
		self.devicesCalled = 0
		self.channelDevice: dict[int, int] = {}
		self.urls: list[str] = []

	def configure(self) -> None:
		pass

	def loadPlugins(self) -> dict:
		return self.plugins

	def devices(self):
		self.devicesCalled += 1
		return [(2, "Altavoces", 3), (3, "Auriculares", 1)]

	def deviceByName(self, name: str) -> int:
		return {"Altavoces": 2, "Auriculares": 3}.get(name, -1)

	def initDevice(self, device: int, freq: int = 44100) -> int:
		return 2 if device == -1 else device

	def setThreadDevice(self, device: int) -> None:
		pass

	def streamFromUrl(self, url: str, decode: bool = False) -> int:
		self.urls.append(url)
		if self.fail_open:
			raise bassmod.BassError(32, "No se pudo abrir la emisora")
		self.next += 1
		self.active[self.next] = bassmod.BASS_ACTIVE_STOPPED
		return self.next

	def free(self, h: int) -> None:
		self.freed.append(h)
		self.active.pop(h, None)

	def play(self, h: int, restart: bool = False) -> None:
		self.active[h] = bassmod.BASS_ACTIVE_PLAYING

	def pause(self, h: int) -> None:
		self.active[h] = bassmod.BASS_ACTIVE_PAUSED

	def isActive(self, h: int) -> int:
		return self.active.get(h, bassmod.BASS_ACTIVE_STOPPED)

	def setAttribute(self, h: int, attrib: int, value: float) -> None:
		self.attrs[(h, attrib)] = value

	def getAttribute(self, h: int, attrib: int) -> float:
		return self.attrs.get((h, attrib), 0.0)

	def setChannelDevice(self, h: int, dev: int) -> None:
		self.channelDevice[h] = dev

	def formatName(self, h: int) -> str:
		return "MP3"

	def streamTitle(self, h: int) -> str:
		return self.title

	def icyHeaders(self, h: int) -> dict:
		return {"icy-name": "Prueba"}

	def channelInfo(self, h: int):
		return types.SimpleNamespace(freq=44100, chans=2)

	def bufferPercent(self, h: int) -> int:
		return 100

	def setPeakEq(self, h: int, fx: int, bands) -> int:
		self.fx_calls.append(("eq", list(bands)))
		return fx or 9

	def removeFx(self, h: int, fx: int) -> None:
		self.fx_calls.append(("remove", fx))

	def encodeToWav(self, h: int, path: str) -> int:
		with open(path, "wb") as f:
			f.write(b"RIFF")
		self.next += 1
		self.encoders[self.next] = path
		return self.next

	def encodeStop(self, enc: int) -> None:
		self.stopped_encoders.append(enc)

	def encodeActive(self, enc: int) -> bool:
		return enc in self.encoders and enc not in self.stopped_encoders

	def errorCode(self) -> int:
		return 0


# ====================================================================== modelos y localización
class ModelosPruebas(unittest.TestCase):
	def test_emisora_desde_api(self) -> None:
		st = Station.from_api_response(
			{"name": " Radio X ", "url": "http://x/listen.pls", "url_resolved": "http://x/stream", "bitrate": "128", "geo_lat": None, "lastcheckok": 0, "hls": 1, "stationuuid": "u1", "country": "Spain"}
		)
		self.assertEqual(st.name, "Radio X")
		self.assertEqual(st.play_url, "http://x/stream")
		self.assertEqual(st.bitrate, 128)
		self.assertEqual(st.geo_lat, 0.0)
		self.assertEqual(st.lastcheckok, 0)
		self.assertEqual(st.get_display_name(), "Radio X (Spain) [128 kbps]")
		st2 = Station(name="Y", url="http://y")
		self.assertEqual(st2.play_url, "http://y")

	def test_filtros_de_busqueda(self) -> None:
		f = models.SearchFilters(name="rock", country="ES", language="spanish", tag="pop", codec="MP3", min_bitrate=64, order="votes", reverse=True, limit=50, hide_broken=True)
		p = f.to_api_params()
		self.assertEqual(p["name"], "rock")
		self.assertEqual(p["countrycode"], "ES")
		self.assertEqual(p["languageExact"], "true")
		self.assertEqual(p["tagExact"], "true")
		self.assertEqual(p["bitrateMin"], 64)
		self.assertEqual(p["hidebroken"], "true")
		self.assertEqual(p["reverse"], "true")
		self.assertNotIn("nameExact", p)

	def test_favorito_y_emisora(self) -> None:
		st = Station(name="A", url="http://a", stationuuid="u")
		fav = Favorite.from_station(st, category_id=3)
		self.assertEqual((fav.name, fav.url, fav.station_uuid, fav.category_id), ("A", "http://a", "u", 3))
		self.assertEqual(fav.to_station().stationuuid, "u")

	def test_localizacion(self) -> None:
		self.assertEqual(localization.get_country_name("es"), "España")
		self.assertEqual(localization.get_country_code("españa"), "ES")
		self.assertEqual(localization.get_country_code("Mexico"), "MX")
		self.assertEqual(localization.get_country_code("ar"), "AR")
		self.assertEqual(localization.get_country_code("Narnia"), "")
		self.assertEqual(localization.get_language_name("spanish"), "Español")
		self.assertEqual(localization.get_language_name("klingon"), "Klingon")
		self.assertEqual(localization.get_language_api_name("Catalán"), "catalan")
		self.assertEqual(localization.get_language_api_name("Esperanto"), "esperanto")
		names = [n for _c, n in localization.sorted_countries()]
		self.assertLess(names.index("Alemania"), names.index("España"))
		# Todos los países comunes de la pestaña General tienen nombre.
		for code in localization.COMMON_COUNTRIES:
			self.assertIn(code, localization.COUNTRIES_ES)


# ====================================================================== eventos
class EventosPruebas(unittest.TestCase):
	def test_metodo_debil_y_lambda(self) -> None:
		bus = events.EventBus()
		got = []

		class Oyente:
			def on(self, data):
				got.append(("m", data))

		o = Oyente()
		bus.subscribe(EventType.PLAYBACK_STARTED, o.on)
		unsub = bus.subscribe(EventType.PLAYBACK_STARTED, lambda d: got.append(("l", d)), weak=False)
		self.assertEqual(bus.emit(EventType.PLAYBACK_STARTED, 1), 2)
		self.assertEqual(sorted(got), [("l", 1), ("m", 1)])
		unsub()
		del o
		import gc

		gc.collect()
		self.assertEqual(bus.emit(EventType.PLAYBACK_STARTED, 2), 0)
		self.assertEqual(bus.get_subscriber_count(EventType.PLAYBACK_STARTED), 0)

	def test_error_en_suscriptor_no_corta(self) -> None:
		bus = events.EventBus()
		got = []

		def malo(d):
			raise RuntimeError("x")

		bus.subscribe(EventType.VOLUME_CHANGED, malo, weak=False)
		bus.subscribe(EventType.VOLUME_CHANGED, got.append, weak=False)
		with self.assertLogs("tiresias.zRadioBASS.events", level="ERROR"):
			bus.emit(EventType.VOLUME_CHANGED, 7)
		self.assertEqual(got, [7])
		bus.disable()
		self.assertEqual(bus.emit(EventType.VOLUME_CHANGED, 8), 0)
		bus.enable()
		self.assertIn(EventType.VOLUME_CHANGED, bus.lastEvents)


# ====================================================================== configuración
class ConfiguracionPruebas(unittest.TestCase):
	def test_estado_persiste_y_opciones_en_conf(self) -> None:
		d = _newDir("cfg")
		c = config_mod.ConfigManager(d)
		self.assertEqual(c.volume, 50)
		c.volume = 35
		c.muted = True
		c.save()
		c2 = config_mod.ConfigManager(d)
		self.assertEqual((c2.volume, c2.muted), (35, True))
		self.assertTrue(os.path.isfile(os.path.join(d, "estado.json")))
		# Opciones: en la sección de Tiresias.
		self.assertIn("zRadioBASS", conf.defaults)
		self.assertTrue(c.cacheEnabled)
		self.assertEqual(c.cache_duration_days, conf["zRadioBASS"]["cacheDays"])
		with self.assertRaises(AttributeError):
			_ = c.noExiste

	def test_carpeta_de_grabaciones(self) -> None:
		d = _newDir("cfgrec")
		c = config_mod.ConfigManager(d)
		old = conf["zRadioBASS"]["recordingDirectory"]
		try:
			conf["zRadioBASS"]["recordingDirectory"] = d
			self.assertEqual(str(c.recordings_dir), d)
			conf["zRadioBASS"]["recordingDirectory"] = os.path.join(d, "no_existe")
			# Carpeta inexistente: Música del usuario (o la de datos).
			self.assertTrue(os.path.isdir(str(c.recordings_dir)))
		finally:
			conf["zRadioBASS"]["recordingDirectory"] = old

	def test_ultima_emisora_y_plugins(self) -> None:
		d = _newDir("cfglast")
		c = config_mod.ConfigManager(d)
		c.remember_station("Radio", "http://r", "u")
		self.assertEqual(config_mod.ConfigManager(d).last_station_name, "Radio")
		s = c.plugin_settings("p1")
		s["x"] = 1
		c.save()
		self.assertEqual(config_mod.ConfigManager(d).plugin_settings("p1"), {"x": 1})

	def test_estado_danado(self) -> None:
		d = _newDir("cfgbad")
		with open(os.path.join(d, "estado.json"), "w", encoding="utf-8") as f:
			f.write("{no es json")
		c = config_mod.ConfigManager(d)
		self.assertEqual(c.volume, 50)


# ====================================================================== base de datos
class BaseDeDatosPruebas(unittest.TestCase):
	def setUp(self) -> None:
		self.db = database.DatabaseManager(os.path.join(_newDir("db"), "z.db"))

	def tearDown(self) -> None:
		self.db.close()

	def test_categorias(self) -> None:
		cats = self.db.get_categories()
		self.assertEqual([c.name for c in cats], ["General"])
		cid = self.db.add_category(Category(name="Noticias", description="info"))
		fid = self.db.add_favorite(Favorite(name="N", url="http://n", category_id=cid))
		self.assertEqual(self.db.count_favorites_in_category(cid), 1)
		self.assertTrue(self.db.delete_category(cid))
		self.assertIsNone(self.db.get_favorite_by_id(fid).category_id)
		self.assertIsNone(self.db.category_id_by_name("Noticias"))

	def test_favoritos_orden_y_mover(self) -> None:
		ids = [self.db.add_favorite(Favorite(name=n, url=f"http://{n}")) for n in ("c", "a", "b")]
		self.assertEqual([f.name for f in self.db.get_favorites()], ["c", "a", "b"])
		self.assertEqual([f.name for f in self.db.get_favorites(sort=1)], ["a", "b", "c"])
		self.assertTrue(self.db.move_favorite(ids[2], -1))
		self.assertEqual([f.name for f in self.db.get_favorites()], ["c", "b", "a"])
		self.assertFalse(self.db.move_favorite(ids[0], -1))
		self.db.increment_play_count(ids[1])
		self.db.increment_play_count_by_url("http://a")
		self.assertEqual(self.db.get_favorites(sort=2)[0].name, "a")
		self.assertEqual(self.db.get_favorites(sort=2)[0].play_count, 2)
		self.assertIsNotNone(self.db.get_favorites(sort=2)[0].last_played)
		self.assertTrue(self.db.favorite_exists("http://a"))
		self.assertEqual([f.name for f in self.db.search_favorites("b")], ["b"])
		self.assertEqual(len(self.db.get_favorites(limit=2)), 2)

	def test_exportar_importar_compatible(self) -> None:
		cid = self.db.add_category(Category(name="Música"))
		self.db.add_favorite(Favorite(name="Uno", url="http://1", category_id=cid, notes="nota"))
		data = json.loads(self.db.export_favorites_json())
		self.assertEqual(data["favorites"][0]["category"], "Música")
		other = database.DatabaseManager(os.path.join(_newDir("db2"), "z.db"))
		try:
			self.assertEqual(other.import_favorites_json(json.dumps(data)), (1, 1))
			fav = other.get_favorites()[0]
			self.assertEqual((fav.name, fav.notes), ("Uno", "nota"))
			self.assertEqual(other.get_category(fav.category_id).name, "Música")
			# Repetir no duplica.
			self.assertEqual(other.import_favorites_json(json.dumps(data)), (0, 0))
			# Formato del complemento original (sin «category»).
			original = {"version": "1.0", "categories": [{"name": "Viejas", "description": "", "color": "#0078D4"}], "favorites": [{"name": "Dos", "url": "http://2", "station_uuid": None, "notes": ""}]}
			self.assertEqual(other.import_favorites_json(json.dumps(original)), (1, 1))
		finally:
			other.close()
		with self.assertRaises(ValueError):
			self.db.import_favorites_json("[]")

	def test_historial(self) -> None:
		hid = self.db.add_to_history(Station(name="R", url="http://r"))
		self.db.add_to_history(Station(name="S", url="http://s"))
		self.db.add_to_history(Station(name="R", url="http://r"))
		self.db.set_history_duration(hid, 90)
		h = self.db.get_history()
		self.assertEqual(h[0].station_name, "R")
		self.assertEqual(len(h), 3)
		top = self.db.get_most_played_stations()
		self.assertEqual((top[0]["name"], top[0]["play_count"], top[0]["total_seconds"]), ("R", 2, 90))
		self.assertEqual(self.db.history_totals(), {"plays": 3, "seconds": 90, "stations": 2})
		self.assertEqual(self.db.clear_history(older_than_days=1), 0)
		self.assertTrue(self.db.delete_history_entry(hid))
		self.assertEqual(self.db.clear_history(), 2)

	def test_cache_de_listas(self) -> None:
		self.assertFalse(self.db.is_cache_valid("cache_countries"))
		self.db.cache_countries([{"iso_3166_1": "ES", "name": "Spain", "stationcount": 5}, {"name": "sin código"}])
		self.assertTrue(self.db.is_cache_valid("cache_countries", 1))
		self.assertEqual(self.db.get_cached_countries()[0]["code"], "ES")
		self.db.cache_tags([{"name": "rock", "stationcount": 9}])
		self.db.cache_languages([{"name": "spanish", "stationcount": 3}])
		self.assertEqual(self.db.get_cached_tags()[0]["station_count"], 9)
		self.db.clear_caches()
		self.assertFalse(self.db.is_cache_valid("cache_tags"))
		with self.assertRaises(ValueError):
			self.db.is_cache_valid("favorites")

	def test_conexiones_de_varios_hilos(self) -> None:
		errors = []

		def worker(n):
			try:
				self.db.add_to_history(Station(name=f"h{n}", url=f"http://h{n}"))
			except Exception as e:
				errors.append(e)

		ts = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
		for t in ts:
			t.start()
		for t in ts:
			t.join()
		self.assertEqual(errors, [])
		self.assertEqual(len(self.db.get_history(limit=100)), 8)


# ====================================================================== red y API (simuladas)
class RedPruebas(unittest.TestCase):
	def test_construir_url(self) -> None:
		self.assertEqual(net.buildUrl("https://a/json/x", {"q": "a b", "n": None}), "https://a/json/x?q=a+b")
		self.assertEqual(net.buildUrl("https://a/x", None), "https://a/x")

	def test_cache_de_respuestas(self) -> None:
		c = net.ResponseCache(os.path.join(_newDir("cache"), "c.db"))
		try:
			self.assertIsNone(c.get("k", 3))
			c.put("k", [{"a": 1}])
			self.assertEqual(c.get("k", 3), [{"a": 1}])
			self.assertEqual(c.count(), 1)
			with mock.patch.object(net.time, "time", return_value=time.time() + 5 * 86400):
				self.assertIsNone(c.get("k", 3))
				self.assertEqual(c.purge(3), 1)
			c.put("j", {"b": 2})
			self.assertEqual(c.clear(), 1)
		finally:
			c.close()

	def test_descompresion(self) -> None:
		import gzip

		self.assertEqual(net._decode(gzip.compress(b"hola"), "gzip"), b"hola")
		import zlib

		self.assertEqual(net._decode(zlib.compress(b"hola"), "deflate"), b"hola")
		self.assertEqual(net._decode(b"x", ""), b"x")

	def test_contexto_tls_verifica(self) -> None:
		import ssl

		ctx = net.sslContext()
		self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
		self.assertTrue(ctx.check_hostname)
		self.assertGreater(len(ctx.get_ca_certs()) + ctx.cert_store_stats().get("x509_ca", 0), 0)

	def test_api_cambia_de_servidor_y_usa_cache(self) -> None:
		cache = net.ResponseCache(os.path.join(_newDir("apicache"), "c.db"))
		api = api_client.RadioBrowserAPI(cache=cache, cacheSettings=lambda: (True, 3))
		api._available_servers = ["https://s1", "https://s2"]
		api._base_url = "https://s1"
		calls = []

		def fake(url, timeout=10):
			calls.append(url)
			if url.startswith("https://s1"):
				raise net.HttpError("caído", 503)
			return [{"name": "Radio", "url": "http://r", "stationuuid": "u"}]

		with mock.patch.object(net, "getJson", side_effect=fake):
			res = api.search_by_name("radio", limit=5)
			self.assertEqual([s.name for s in res], ["Radio"])
			self.assertEqual(api.base_url, "https://s2")
			n = len(calls)
			# Segunda vez: de la caché, sin red.
			self.assertEqual(len(api.search_by_name("radio", limit=5)), 1)
			self.assertEqual(len(calls), n)
			# Los votos no se guardan en caché.
			api.vote_for_station("u")
			api.vote_for_station("u")
			self.assertEqual(sum(1 for u in calls if "/vote/" in u), 2)
		cache.close()

	def test_api_error_definitivo(self) -> None:
		api = api_client.RadioBrowserAPI(base_url="https://s1")

		with mock.patch.object(net, "getJson", side_effect=net.HttpError("no", 404)) as m:
			self.assertEqual(api.get_top_stations(5), [])
			self.assertEqual(m.call_count, 1)
			with self.assertRaises(net.HttpError):
				api.get_stations_by_country("ES", raise_errors=True)
		with mock.patch.object(net, "getJson", side_effect=net.HttpError("caído", 0)) as m:
			self.assertEqual(api.get_tags(), [])
			self.assertEqual(m.call_count, api.MAX_RETRIES + 1)

	def test_descubrir_servidores_sin_dns(self) -> None:
		with mock.patch.object(api_client.socket, "getaddrinfo", side_effect=OSError("sin dns")), mock.patch.object(net, "getJson", side_effect=net.HttpError("x")):
			self.assertEqual(api_client.discover_servers(), api_client.FALLBACK_SERVERS)
		with mock.patch.object(api_client.socket, "getaddrinfo", side_effect=OSError("sin dns")), mock.patch.object(
			net, "getJson", return_value=[{"name": "de9.api.radio-browser.info"}, {"name": "malo.example.com"}]
		):
			self.assertEqual(api_client.discover_servers(), ["de9.api.radio-browser.info"])

	def test_metadatos(self) -> None:
		self.assertEqual(bassmod.parseStreamTitle("StreamTitle='Artista - Canción';StreamUrl='';"), "Artista - Canción")
		self.assertEqual(bassmod.parseStreamTitle("StreamTitle='Rock';"), "Rock")
		self.assertEqual(bassmod.parseStreamTitle("nada"), "")
		self.assertEqual(bassmod.parseHlsTitle('title="Tema" artist="Grupo"'), "Grupo - Tema")
		self.assertEqual(bassmod.parseHlsTitle("Texto libre"), "Texto libre")
		self.assertEqual(bassmod.decodeText("ñ".encode("cp1252")), "ñ")
		self.assertEqual(bassmod.decodeText("ñ".encode("utf-8")), "ñ")

	def test_comprobador_de_internet(self) -> None:
		chk = internet.InternetChecker()
		with mock.patch.object(internet.InternetChecker, "_connect", return_value=False):
			self.assertFalse(chk.is_connected(force_check=True))
			self.assertFalse(chk.check_url("http://ejemplo.invalid/x"))
		with mock.patch.object(internet.InternetChecker, "_connect", return_value=True):
			self.assertFalse(chk.is_connected())  # recordado
			self.assertTrue(chk.is_connected(force_check=True))
			self.assertTrue(chk.check_url("https://a.b/c"))
		self.assertFalse(chk.check_url(""))
		self.assertFalse(chk.check_url("sin esquema"))


# ====================================================================== reproductor con BASS simulado
class ReproductorPruebas(unittest.TestCase):
	def setUp(self) -> None:
		self.fake = FakeBass()
		self.p = player_mod.AudioPlayer(loader=lambda: self.fake)
		self.events = []
		self.p.set_on_state_change(lambda s: self.events.append(s))
		self.errors = []
		self.p.set_on_error(self.errors.append)

	def tearDown(self) -> None:
		self.p.dispose()

	def test_reproducir_volumen_silencio_pausa(self) -> None:
		self.p.volume = 30
		self.assertTrue(self.p.play("http://r", async_play=False, station=Station(name="R", url="http://r")))
		h = self.p.handle
		self.assertEqual(self.p.state, player_mod.PlayerState.PLAYING)
		self.assertAlmostEqual(self.fake.attrs[(h, bassmod.BASS_ATTRIB_VOL)], 0.3)
		self.p.muted = True
		self.assertEqual(self.fake.attrs[(h, bassmod.BASS_ATTRIB_VOL)], 0.0)
		self.p.toggle_mute()
		self.assertAlmostEqual(self.fake.attrs[(h, bassmod.BASS_ATTRIB_VOL)], 0.3)
		self.assertEqual(self.p.volume_up(80), 100)
		self.assertEqual(self.p.volume_down(150), 0)
		self.p.toggle_pause()
		self.assertEqual(self.p.state, player_mod.PlayerState.PAUSED)
		self.p.toggle_pause()
		self.assertEqual(self.p.state, player_mod.PlayerState.PLAYING)
		self.p.stop()
		self.assertEqual(self.p.state, player_mod.PlayerState.STOPPED)
		self.assertIn(h, self.fake.freed)
		self.assertIsNone(self.p.current_station)

	def test_cambio_rapido_de_emisora(self) -> None:
		self.p.play("http://a", async_play=False)
		a = self.p.handle
		self.p.play("http://b", async_play=False)
		self.assertIn(a, self.fake.freed)
		self.assertNotEqual(self.p.handle, a)
		self.assertEqual(self.p.current_url, "http://b")

	def test_error_al_abrir(self) -> None:
		self.fake.fail_open = True
		self.p.auto_reconnect = False
		self.assertFalse(self.p.play("http://x", async_play=False))
		self.assertEqual(self.p.state, player_mod.PlayerState.ERROR)
		self.assertTrue(self.errors and "No se pudo abrir" in self.errors[0])
		self.assertIn("Error:", self.p.get_status_message())

	def test_titulo_y_estado(self) -> None:
		meta = []
		self.p.set_on_metadata(meta.append)
		self.p.play("http://r", async_play=False, station=Station(name="Radio Uno", url="http://r"))
		self.fake.title = "Grupo - Tema"
		self.p._check_channel()
		self.assertEqual(self.p.title, "Grupo - Tema")
		self.assertEqual(meta[0]["title"], "Grupo - Tema")
		msg = self.p.get_status_message(scheduled_count=2)
		self.assertIn("Reproduciendo: Radio Uno", msg)
		self.assertIn("Suena: Grupo - Tema", msg)
		self.assertIn("Grabaciones programadas: 2", msg)
		info = self.p.stream_info()
		self.assertEqual((info["format"], info["name"]), ("MP3", "Prueba"))

	def test_reconexion_automatica(self) -> None:
		self.p.play("http://r", async_play=False)
		h = self.p.handle
		reconnects = []
		self.p.set_on_reconnecting(reconnects.append)
		self.fake.active[h] = bassmod.BASS_ACTIVE_STOPPED
		with mock.patch.object(player_mod.time, "sleep"):
			self.p._check_channel()
			self.assertEqual(reconnects, [1])
			self.assertTrue(_wait(lambda: self.p.state == player_mod.PlayerState.PLAYING and self.p.handle != h))
		self.assertIn(h, self.fake.freed)

	def test_sin_reconexion_da_error(self) -> None:
		self.p.auto_reconnect = False
		self.p.play("http://r", async_play=False)
		self.fake.active[self.p.handle] = bassmod.BASS_ACTIVE_STOPPED
		self.p._check_channel()
		self.assertEqual(self.p.state, player_mod.PlayerState.ERROR)
		self.assertTrue(self.errors)

	def test_grabar_emisora_actual(self) -> None:
		d = _newDir("rec")
		self.assertFalse(self.p.start_recording(os.path.join(d, "a.wav")))
		self.p.play("http://r", async_play=False)
		self.assertTrue(self.p.start_recording(os.path.join(d, "a.mp3")))
		self.assertTrue(self.p.recording_file.endswith("a.wav"))
		self.assertTrue(self.p.is_recording)
		self.assertFalse(self.p.start_recording(os.path.join(d, "b.wav")))
		self.assertIsNotNone(self.p.recording_duration)
		self.assertTrue(self.p.stop_recording().endswith("a.wav"))
		self.assertFalse(self.p.is_recording)
		self.assertIsNone(self.p.stop_recording())
		# Detener la radio detiene la grabación.
		self.p.start_recording(os.path.join(d, "c.wav"))
		self.p.stop()
		self.assertFalse(self.p.is_recording)
		self.assertEqual(len(self.fake.stopped_encoders), 2)

	def test_efectos_y_dispositivo(self) -> None:
		self.p.play("http://r", async_play=False)
		h = self.p.handle
		self.p.set_effects(20, -3, 0, 150)
		self.assertEqual(self.p.effects, (12, -3, 0, 100))
		self.assertEqual(self.fake.fx_calls[-1], ("eq", [(100.0, 12), (1000.0, -3), (8000.0, 0)]))
		self.assertEqual(self.fake.attrs[(h, bassmod.BASS_ATTRIB_PAN)], 1.0)
		self.p.set_effects(0, 0, 0, 0)
		self.assertEqual(self.fake.fx_calls[-1][0], "remove")
		self.assertTrue(self.p.set_output_device("Auriculares"))
		self.assertEqual(self.fake.channelDevice[h], 3)
		self.assertEqual(self.p.list_output_devices(), ["Altavoces", "Auriculares"])

	def test_duracion(self) -> None:
		self.assertEqual(player_mod.format_duration(65), "1:05")
		self.assertEqual(player_mod.format_duration(3723), "1:02:03")
		self.assertEqual(player_mod.format_duration(None), "0:00")


# ====================================================================== grabaciones programadas
class FakeRecorder:
	instances: list = []

	def __init__(self, loader, url, path, end_time=None, on_finish=None) -> None:
		self.url, self.path, self.end_time, self.on_finish = url, path, end_time, on_finish
		self.error = ""
		self.bytes = 0
		self.started_at = None
		self._running = False
		FakeRecorder.instances.append(self)

	@property
	def running(self) -> bool:
		return self._running

	def start(self) -> None:
		self._running = True
		self.started_at = datetime.now()

	def stop(self, wait: float = 5.0) -> None:
		if self._running:
			self._running = False
			self.bytes = 1000
			if self.on_finish:
				self.on_finish(self)


class PlanificadorPruebas(unittest.TestCase):
	def setUp(self) -> None:
		FakeRecorder.instances = []
		self.dir = _newDir("sched")
		self.db = database.DatabaseManager(os.path.join(self.dir, "z.db"))
		self.got = []
		self.s = recording.RecordingScheduler(self.db, lambda: None, on_event=lambda k, r: self.got.append((k, r.station_name)), recorder_factory=FakeRecorder)

	def tearDown(self) -> None:
		self.s.stop()
		self.db.close()

	def test_programar_empezar_terminar(self) -> None:
		now = datetime.now()
		with self.assertLogs("tiresias.zRadioBASS.recording", level="ERROR"):
			self.assertIsNone(self.s.schedule("http://r", "R", now + timedelta(hours=1), now, "x.wav"))
			self.assertIsNone(self.s.schedule("http://r", "R", now - timedelta(hours=2), now - timedelta(hours=1), "x.wav"))
		rec = self.s.schedule("http://r", "R", now - timedelta(seconds=1), now + timedelta(hours=1), os.path.join(self.dir, "r.mp3"))
		self.assertTrue(rec.output_path.endswith("r.wav"))
		# Empieza enseguida (ya es la hora).
		self.assertEqual(len(FakeRecorder.instances), 1)
		self.assertEqual(self.s.running_count(), 1)
		self.assertIn(("started", "R"), self.got)
		self.assertEqual(self.db.get_scheduled_recordings()[0].status, "recording")
		# Llega la hora de fin.
		with mock.patch.object(recording, "datetime", wraps=datetime) as dt:
			dt.now.return_value = now + timedelta(hours=2)
			self.s.check_now()
		self.assertIn(("finished", "R"), self.got)
		self.assertEqual(self.db.get_scheduled_recordings(active_only=False)[0].status, "done")
		self.assertEqual(self.s.active(), [])

	def test_cancelar_y_perdidas(self) -> None:
		now = datetime.now()
		a = self.s.schedule("http://a", "A", now + timedelta(hours=1), now + timedelta(hours=2), os.path.join(self.dir, "a.wav"))
		b = self.s.schedule("http://b", "B", now + timedelta(minutes=30), now + timedelta(hours=2), os.path.join(self.dir, "b.wav"))
		self.assertEqual(len(self.s.active()), 2)
		self.assertTrue(self.s.cancel(a.id))
		self.assertFalse(self.s.cancel(a.id))
		self.assertTrue(self.s.cancel_by_index(0))
		self.assertEqual(self.s.active(), [])
		# Pendiente cuya hora de fin pasó con Tiresias cerrado: perdida.
		c = models.ScheduledRecording(station_name="C", station_url="http://c", start_time=now - timedelta(hours=3), end_time=now - timedelta(hours=2), output_path="c.wav")
		self.db.add_scheduled_recording(c)
		self.s.check_now()
		self.assertIn(("missed", "C"), self.got)
		statuses = {r.station_name: r.status for r in self.s.all()}
		self.assertEqual(statuses, {"A": "cancelled", "B": "cancelled", "C": "missed"})
		self.assertEqual(self.db.clear_finished_recordings(), 3)
		del b

	def test_persisten_al_reiniciar(self) -> None:
		now = datetime.now()
		self.s.schedule("http://a", "A", now + timedelta(hours=1), now + timedelta(hours=2), os.path.join(self.dir, "a.wav"))
		s2 = recording.RecordingScheduler(self.db, lambda: None, recorder_factory=FakeRecorder)
		self.assertEqual([r.station_name for r in s2.active()], ["A"])

	def test_nombres_de_archivo(self) -> None:
		self.assertEqual(recording.safe_filename('a<b>:c"/d\\e|f?g*'), "a_b__c__d_e_f_g_")
		self.assertEqual(recording.safe_filename("..."), "radio")
		self.assertEqual(recording.recording_filename("Radio: 1", datetime(2026, 1, 2, 3, 4, 5)), "Radio_ 1_20260102_030405.wav")
		p = os.path.join(self.dir, "x.wav")
		self.assertEqual(recording.unique_path(p), p)
		open(p, "wb").close()
		self.assertEqual(recording.unique_path(p), os.path.join(self.dir, "x (2).wav"))


# ====================================================================== plugins
USER_PLUGIN = '''
from zradiobass import PluginBase, EventType

class MiPlugin(PluginBase):
	PLUGIN_ID = "mi_plugin"
	PLUGIN_NAME = "Mi plugin"
	PLUGIN_DEPENDENCIES = ["example_plugin"]
	visto = []

	def on_load(self):
		self.subscribe(EventType.PLAYBACK_STARTED, lambda st: MiPlugin.visto.append(st.name))
		return True

	def on_unload(self):
		return True

	def get_context_menu_items(self, context):
		return [{"label": "Mío", "callback": lambda st: None}] if context == "favorite" else []
'''

BROKEN_PLUGIN = "import modulo_que_no_existe\n"


class PluginsPruebas(unittest.TestCase):
	def setUp(self) -> None:
		self.dir = _newDir("plugins")
		self.cfg = config_mod.ConfigManager(self.dir)
		self.bus = events.EventBus()
		self.app = types.SimpleNamespace(config=self.cfg, db=None, speak=lambda t: self.spoken.append(t), message=lambda *a: self.messages.append(a))
		self.spoken: list = []
		self.messages: list = []
		self.disabled: list = []
		self.pm = plugin_manager.PluginManager(self.bus, app=self.app, user_dir=self.cfg.plugins_dir, disabled=lambda: list(self.disabled), set_disabled=lambda ids: self.disabled.__init__(ids))

	def tearDown(self) -> None:
		self.pm.shutdown()

	def test_plugins_incluidos(self) -> None:
		found = self.pm.discover_plugins()
		self.assertEqual(sorted(found), ["example_plugin", "statistics_plugin"])
		self.assertEqual(self.pm.load_all_plugins(), {"example_plugin": True, "statistics_plugin": True})
		self.assertIn("zradiobass", sys.modules)
		labels = [i["label"] for i in self.pm.get_menu_items_from_plugins()]
		self.assertIn("Acerca del plugin de ejemplo...", labels)
		self.assertIn("Ver estadísticas de uso...", labels)
		ctx = self.pm.get_context_menu_items_from_plugins("station")
		self.assertEqual([i["label"] for i in ctx], ["[Ejemplo] Información adicional"])
		ctx[0]["callback"](Station(name="R", url="http://r"))
		self.assertIn("Emisora: R", self.messages[-1][0])
		self.assertTrue(self.pm.is_builtin("example_plugin"))
		self.assertEqual(self.pm.get_plugin_metadata("statistics_plugin").name, "Estadísticas de uso")

	def test_estadisticas(self) -> None:
		self.pm.discover_plugins()
		self.pm.load_all_plugins()
		stats = self.pm.get_plugin("statistics_plugin")
		self.bus.emit(EventType.PLAYBACK_STARTED, Station(name="A", url="http://a"))
		stats._session_start -= timedelta(seconds=120)
		self.bus.emit(EventType.PLAYBACK_STOPPED, None)
		self.assertEqual(stats.stations_played, 1)
		self.assertGreaterEqual(stats.total_seconds(), 120)
		with open(os.path.join(self.dir, "statistics.json"), encoding="utf-8") as f:
			self.assertEqual(json.load(f)["stations_played"], 1)
		report = stats.build_report()
		self.assertIn("Emisoras reproducidas: 1", report)
		self.assertIn("2 minutos", report)
		stats._show_statistics()
		self.assertEqual(self.messages[-1][1], "Estadísticas de uso")
		stats._reset_statistics()
		self.assertEqual(stats.stations_played, 0)
		# Al recargar, se leen las estadísticas guardadas.
		self.pm.reload_plugin("statistics_plugin")
		self.assertEqual(self.pm.get_plugin("statistics_plugin").stations_played, 0)

	def test_ejemplo_anuncia_con_opcion(self) -> None:
		self.pm.discover_plugins()
		self.pm.load_all_plugins()
		ex = self.pm.get_plugin("example_plugin")
		self.bus.emit(EventType.PLAYBACK_STARTED, Station(name="Z", url="http://z"))
		self.assertEqual(self.spoken, [])
		ex.settings["announce"] = True
		ex.save_settings()
		self.bus.emit(EventType.PLAYBACK_STARTED, Station(name="Z", url="http://z"))
		self.assertEqual(self.spoken, ["Plugin de ejemplo: empieza a sonar Z"])
		ex._show_about()
		self.assertIn("Versión: 1.0.0", self.messages[-1][0])

	def test_plugin_de_usuario_dependencias_y_desactivar(self) -> None:
		with open(os.path.join(str(self.cfg.plugins_dir), "mio.py"), "w", encoding="utf-8") as f:
			f.write(USER_PLUGIN)
		with open(os.path.join(str(self.cfg.plugins_dir), "roto.py"), "w", encoding="utf-8") as f:
			f.write(BROKEN_PLUGIN)
		self.disabled[:] = ["example_plugin"]
		with self.assertLogs("tiresias.zRadioBASS.plugins", level="ERROR"):
			found = self.pm.discover_plugins()
		self.assertIn("mi_plugin", found)
		self.assertNotIn("roto", found)
		self.assertEqual(self.pm.get_plugin_error("roto").startswith("No module named"), True)
		results = self.pm.load_all_plugins()
		self.assertTrue(results["mi_plugin"])
		# La dependencia se carga aunque esté desactivada a mano.
		self.assertTrue(self.pm.is_plugin_loaded("example_plugin"))
		self.assertFalse(self.pm.is_builtin("mi_plugin"))
		mod = sys.modules["zradiobass_plugin_mio"]
		self.bus.emit(EventType.PLAYBACK_STARTED, Station(name="Q", url="http://q"))
		self.assertEqual(mod.MiPlugin.visto, ["Q"])
		self.assertTrue(self.pm.disable_plugin("mi_plugin"))
		self.assertIn("mi_plugin", self.disabled)
		self.assertEqual(self.pm.get_plugin_state("mi_plugin"), plugin_manager.PluginState.DISABLED)
		self.bus.emit(EventType.PLAYBACK_STARTED, Station(name="R", url="http://r"))
		self.assertEqual(mod.MiPlugin.visto, ["Q"])
		self.assertTrue(self.pm.enable_plugin("mi_plugin"))
		self.assertNotIn("mi_plugin", self.disabled)
		found = self.pm.rediscover()
		self.assertIn("mi_plugin", found)
		self.assertEqual(self.pm.get_context_menu_items_from_plugins("favorite")[0]["label"], "Mío")


# ====================================================================== aplicación
class AplicacionPruebas(unittest.TestCase):
	def setUp(self) -> None:
		self.dir = _newDir("app")
		self.cfg = config_mod.ConfigManager(self.dir)
		self.fake = FakeBass()
		self.spoken: list = []
		self.player = player_mod.AudioPlayer(loader=lambda: self.fake)
		self.app = app_mod.RadioApp(self.cfg, player=self.player, bass_loader=lambda: self.fake, speak=self.spoken.append, load_plugins=True)
		self.app.internet.check_url = lambda url, timeout=None: True
		self.app.api.click_station = lambda uuid: True

	def tearDown(self) -> None:
		self.app.terminate()

	def _play(self, station: Station) -> None:
		self.app.play_station(station, check_url=True)
		self.assertTrue(_wait(lambda: self.player.state == player_mod.PlayerState.PLAYING and self.player.current_station is station))

	def test_volumen_y_silencio_persisten(self) -> None:
		self.app.set_volume(50)
		old = conf["zRadioBASS"]["volumeStep"]
		try:
			conf["zRadioBASS"]["volumeStep"] = 10
			self.assertEqual(self.app.volume_step(1), "60%")
			self.app.set_volume(100)
			self.assertEqual(self.app.volume_step(1), "Volumen al máximo")
			self.app.set_volume(0)
			self.assertEqual(self.app.volume_step(-1), "Volumen al mínimo")
		finally:
			conf["zRadioBASS"]["volumeStep"] = old
		self.assertTrue(self.app.toggle_mute())
		self.assertEqual(config_mod.ConfigManager(self.dir).muted, True)
		self.app.toggle_mute()

	def test_reproducir_historial_eventos_y_favoritos(self) -> None:
		got = []
		self.app.event_bus.subscribe(EventType.PLAYBACK_STARTED, got.append, weak=False)
		st = Station(name="Radio Prueba", url="http://p", stationuuid="u1")
		self.app.add_favorite(st)
		self.assertIsNone(self.app.add_favorite(st))
		self._play(st)
		self.assertTrue(_wait(lambda: got == [st]))
		self.assertEqual(self.app.db.get_history()[0].station_name, "Radio Prueba")
		self.assertEqual(self.cfg.last_station_url, "http://p")
		self.assertEqual(self.app.db.get_favorite_by_url("http://p").play_count, 1)
		self.assertEqual(self.app.current_station_message(), "Emisora: Radio Prueba")
		self.assertEqual(self.app.current_title_message(), "La emisora no envía el título de la canción")
		self.assertEqual(self.app.toggle_pause(), "En pausa")
		self.assertEqual(self.app.toggle_pause(), "Reanudado")
		self.app._history_started -= 30
		self.assertTrue(self.app.stop())
		self.assertFalse(self.app.stop())
		self.assertGreaterEqual(self.app.db.get_history()[0].duration_seconds, 30)
		# Estadísticas: una emisora reproducida.
		self.assertEqual(self.app.plugin_manager.get_plugin("statistics_plugin").stations_played, 1)
		self.assertEqual(self.app.current_station_message(), "No hay ninguna emisora reproduciéndose")
		self.assertIsNotNone(self.app.remove_favorite_by_url("http://p"))

	def test_favoritos_rapidos_y_navegacion(self) -> None:
		self.assertEqual(self.app.play_favorite(1), "No hay emisora favorita en la posición 1")
		self.assertEqual(self.app.next_favorite(1), "No hay favoritos guardados")
		for n in ("Uno", "Dos", "Tres"):
			self.app.add_favorite(Station(name=n, url=f"http://{n}"))
		self.assertEqual(self.app.play_favorite(2), "Dos")
		self.assertEqual(self.app.play_favorite(4), "No hay emisora favorita en la posición 4")
		self.assertEqual(self.app.next_favorite(1), "3 de 3. Tres")
		self.assertEqual(self.app.next_favorite(1), "1 de 3. Uno")
		self.assertEqual(self.app.next_favorite(-1), "3 de 3. Tres")
		self.assertTrue(_wait(lambda: self.player.current_url == "http://Tres"))

	def test_grabacion_desde_la_app(self) -> None:
		old = conf["zRadioBASS"]["recordingDirectory"]
		conf["zRadioBASS"]["recordingDirectory"] = self.dir
		try:
			self.assertEqual(self.app.start_recording_current(), (False, "No hay ninguna emisora reproduciéndose"))
			self._play(Station(name="Grabable: 1", url="http://g"))
			ok, path = self.app.start_recording_current()
			self.assertTrue(ok)
			self.assertTrue(os.path.basename(path).startswith("Grabable_ 1_"))
			self.assertEqual(os.path.dirname(path), self.dir)
			self.assertEqual(self.app.start_recording_current(), (False, "Ya hay una grabación en curso"))
			self.assertTrue(self.app.recording_status_message().startswith("Grabando - 0:0"))
			self.assertEqual(self.app.stop_recording_current(), path)
			self.assertEqual(self.app.recording_status_message(), "No hay grabación activa")
			now = datetime.now()
			self.app.schedule_recording("http://g", "G", now + timedelta(hours=1), now + timedelta(hours=2), os.path.join(self.dir, "g.wav"))
			self.assertEqual(self.app.recording_status_message(), "No grabando. 1 grabaciones programadas")
			self.assertIn("Grabaciones programadas: 1", self.app.status_message())
		finally:
			conf["zRadioBASS"]["recordingDirectory"] = old

	def test_error_de_conexion(self) -> None:
		self.app.internet.check_url = lambda url, timeout=None: False
		fails = []
		self.app.play_station(Station(name="X", url="http://x"), on_fail=fails.append)
		self.assertTrue(_wait(lambda: bool(fails)))
		self.assertIn("No se pudo conectar", fails[0])
		self.app.play_station(Station(name="X", url="http://x"))
		self.assertTrue(_wait(lambda: "No se pudo conectar con la emisora" in self.spoken))
		self.app.play_station(Station(name="Y", url=""))
		self.assertIn("La emisora no tiene dirección", self.spoken)

	def test_error_de_reproduccion_se_dice(self) -> None:
		self.fake.fail_open = True
		old = conf["zRadioBASS"]["autoReconnect"]
		conf["zRadioBASS"]["autoReconnect"] = False
		try:
			self.app.apply_options()
			self.app.play_station(Station(name="X", url="http://x"))
			self.assertTrue(_wait(lambda: any(s.startswith("Error de reproducción") for s in self.spoken)))
			self.assertEqual(self.app.db.get_history(), [])
		finally:
			conf["zRadioBASS"]["autoReconnect"] = old

	def test_listas_con_cache_en_base_de_datos(self) -> None:
		calls = []

		def fake(url, timeout=10):
			calls.append(url)
			if "/countries" in url:
				return [{"name": "Spain", "iso_3166_1": "ES", "stationcount": 10}]
			if "/languages" in url:
				return [{"name": "spanish", "stationcount": 4}]
			if "/tags" in url:
				return [{"name": "rock", "stationcount": 3}]
			return []

		self.app.api._base_url = "https://falso"
		with mock.patch.object(net, "getJson", side_effect=fake):
			c1 = self.app.list_countries()
			self.assertEqual((c1[0].code, c1[0].name_localized), ("ES", "España"))
			self.assertEqual(self.app.list_countries()[0].station_count, 10)
			self.assertEqual(self.app.list_languages()[0].name_localized, "Español")
			self.app.list_languages()
			self.assertEqual(self.app.list_tags()[0].name, "rock")
			self.app.list_tags()
		self.assertEqual(len(calls), 3)
		self.app.clear_cache()
		self.assertFalse(self.app.db.is_cache_valid("cache_countries"))

	def test_aplicar_opciones(self) -> None:
		old = {k: conf["zRadioBASS"][k] for k in ("eqBass", "balance", "outputDevice", "autoReconnect")}
		try:
			conf["zRadioBASS"]["eqBass"] = 6
			conf["zRadioBASS"]["balance"] = -50
			conf["zRadioBASS"]["outputDevice"] = "Auriculares"
			conf["zRadioBASS"]["autoReconnect"] = False
			self.app.apply_options()
			self.assertEqual(self.player.effects, (6, 0, 0, -50))
			self.assertEqual(self.player.device_name, "Auriculares")
			self.assertFalse(self.player.auto_reconnect)
		finally:
			for k, v in old.items():
				conf["zRadioBASS"][k] = v
			self.app.apply_options()

	def test_ultima_emisora(self) -> None:
		self.cfg.remember_station("Última", "http://u", "")
		self.assertTrue(self.app.play_last_station(announce=False))
		self.assertTrue(_wait(lambda: self.player.current_url == "http://u"))


# ====================================================================== interfaz (ventanas ocultas)
class InterfazPruebas(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		import wx

		cls.wx = wx
		cls.wxapp = wx.App.Get() or wx.App(False)

	def setUp(self) -> None:
		self.dir = _newDir("ui")
		self.cfg = config_mod.ConfigManager(self.dir)
		self.fake = FakeBass()
		self.app = app_mod.RadioApp(self.cfg, player=player_mod.AudioPlayer(loader=lambda: self.fake), bass_loader=lambda: self.fake, speak=lambda t: None)
		# Sin red: la pestaña General recibe una lista fija.
		self.app.general_stations = lambda code: [Station(name="Radio A", url="http://a"), Station(name="Radio B", url="http://b")]

	def tearDown(self) -> None:
		self.app.terminate()

	def _pump(self, cond=lambda: True, timeout: float = 3.0) -> None:
		end = time.time() + timeout
		while time.time() < end:
			self.wx.Yield()
			if cond():
				return
			time.sleep(0.02)

	@staticmethod
	def _accel(label: str) -> str | None:
		i = label.find("&")
		while i >= 0 and i + 1 < len(label):
			if label[i + 1] != "&":
				return label[i + 1].lower()
			i = label.find("&", i + 2)
		return None

	def _mnemonics(self, win, page) -> list[tuple[str, str]]:
		wx = self.wx
		out = []

		def walk(w):
			if isinstance(w, wx.Notebook):
				walk(page)
				return
			if isinstance(w, (wx.StaticText, wx.Button, wx.CheckBox)):
				a = self._accel(w.GetLabel())
				if a:
					out.append((a, w.GetLabel()))
			for c in w.GetChildren():
				walk(c)

		walk(win)
		return out

	def test_ventana_principal(self) -> None:
		mw_mod = importlib.import_module(f"{PKG}.zr_ui.main_window")
		win = mw_mod.MainWindow(None, self.app)
		try:
			self.assertFalse(win.IsShown())
			self._pump(lambda: win.panel_general.lst_stations.GetCount() == 2)
			self.assertEqual(win.panel_general.lst_stations.GetString(0), "Radio A")
			self.assertEqual(win.notebook.GetPageCount(), 4)
			self.assertEqual([win.notebook.GetPageText(i) for i in range(4)], ["General", "Favoritos", "Buscador", "Historial"])
			self.assertIn("Sin reproducción activa", win.status_text)
			# Teclas de acceso sin repetir en cada pestaña.
			for i in range(4):
				items = self._mnemonics(win, win.notebook.GetPage(i))
				keys = [a for a, _l in items]
				dups = sorted({a for a in keys if keys.count(a) > 1})
				self.assertEqual(dups, [], (win.notebook.GetPageText(i), items))
			# Menú de herramientas: se construye con las entradas de los plugins.
			menu, handlers = win._build_tools_menu()
			labels = []

			def collect(m):
				for it in m.GetMenuItems():
					if it.IsSubMenu():
						collect(it.GetSubMenu())
					elif not it.IsSeparator():
						labels.append(it.GetItemLabel())

			collect(menu)
			menu.Destroy()
			for wanted in ("&Grabar emisora actual", "&Programar grabación...", "&Exportar favoritos...", "&Importar favoritos...", "&Limpiar historial...", "C&onfiguración...", "Ver estadísticas de uso...", "&Administrar plugins..."):
				self.assertIn(wanted, labels)
			# Favoritos en la pestaña tras añadir uno.
			self.app.add_favorite(Station(name="Fav Uno", url="http://f1"))
			self._pump(lambda: win.panel_favorites.lst_favorites.GetString(0) == "Fav Uno")
			self.assertEqual(win.panel_favorites.selected_favorite().name, "Fav Uno")
			# Reproducir desde la ventana actualiza el estado.
			self.app.internet.check_url = lambda url, timeout=None: True
			self.app.api.click_station = lambda uuid: True
			self.app.play_station(Station(name="Radio A", url="http://a"))
			self._pump(lambda: "Reproduciendo: Radio A" in win.status_text)
			self.assertIn("Reproduciendo: Radio A", win.status_text)
			self.assertTrue(win.btn_stop.IsEnabled())
			self._pump(lambda: win.panel_history.lst_history.GetString(0).startswith("Radio A - "))
			self.assertTrue(win.panel_history.lst_history.GetString(0).startswith("Radio A - "))
		finally:
			win.destroy()

	def test_dialogos(self) -> None:
		dlg_mod = importlib.import_module(f"{PKG}.zr_ui.dialogs")
		cats = self.app.db.get_categories()
		d = dlg_mod.StationEditDialog(None, Favorite(name="N", url="http://n", category_id=cats[0].id, notes="x"), categories=cats)
		self.assertEqual(d.choice_category.GetStringSelection(), "General")
		d.Destroy()
		d = dlg_mod.ScheduleRecordingDialog(None, "Radio: X", "http://x", config=self.cfg)
		self.assertTrue(d.txt_filename.GetValue().startswith("Radio_ X_"))
		d.Destroy()
		dialogs = [
			dlg_mod.StationEditDialog(None, categories=cats),
			dlg_mod.ScheduleRecordingDialog(None, "R", "http://r", config=self.cfg, favorites=[Favorite(name="F", url="http://f")]),
			dlg_mod.CategoryEditDialog(None),
			dlg_mod.StationInfoDialog(None, station=Station(name="A", url="http://a")),
			dlg_mod.FilterListDialog(None, "T", "Fa&voritos:", [(1, "Uno")]),
		] + [cls(None, self.app) for cls in (dlg_mod.CategoriesDialog, dlg_mod.ScheduledRecordingsDialog, dlg_mod.PluginsDialog)]
		for d in dialogs:
			items = []

			def walk(w):
				if isinstance(w, (self.wx.StaticText, self.wx.Button, self.wx.CheckBox)):
					a = self._accel(w.GetLabel())
					if a:
						items.append(a)
				for c in w.GetChildren():
					walk(c)

			walk(d)
			self.assertEqual(sorted({a for a in items if items.count(a) > 1}), [], (d.GetTitle(), items))
			d.Destroy()
		d = dlg_mod.FilterListDialog(None, "T", "&Elementos:", [("ES", "España"), ("FR", "Francia")])
		d.filter.SetValue("fran")
		self.assertEqual(d.list.GetStrings(), ["Francia"])
		d.Destroy()
		text = dlg_mod.station_info_text(Station(name="A", url="http://a", country="Spain", bitrate=128, votes=3), Favorite(name="A", url="http://a", play_count=2, notes="n"), "General", {"title": "T", "format": "MP3"})
		for part in ("Nombre: A", "País: Spain", "Bitrate: 128 kbps", "Votos: 3", "Categoría: General", "Veces reproducida: 2", "Suena ahora: T", "Formato: MP3"):
			self.assertIn(part, text)
		self.assertIn("Emisoras: 10", dlg_mod.server_stats_text({"stations": 10}, "https://s"))

	def test_panel_de_opciones(self) -> None:
		sp = importlib.import_module(f"{PKG}.zr_ui.settings_panel")
		cls = sp.make_panel_class(lambda: self.app)
		keys = [f.key for f in cls.getFields(None)]
		for k in config_mod.DEFAULTS:
			self.assertIn(k, keys)
		from tiresias.gui import settings as S

		sp.register(lambda: self.app)
		try:
			self.assertIn(sp.PANEL_ID, S.getPanelIds())
			frame = self.wx.Frame(None)
			panel = cls(frame)
			self.assertEqual(panel.getControl("outputDevice").GetStrings(), ["Predeterminado de Windows", "Altavoces", "Auriculares"])
			self.assertTrue(panel.isValid())
			# Teclas de acceso: sin repetir y sin chocar con «&Categorías» y «A&plicar» del cuadro de Opciones.
			accels = []

			def walk(w):
				if isinstance(w, (self.wx.StaticText, self.wx.Button, self.wx.CheckBox)):
					a = self._accel(w.GetLabel())
					if a:
						accels.append(a)
				for c in w.GetChildren():
					walk(c)

			walk(panel)
			self.assertEqual(len(accels), len(set(accels)), accels)
			self.assertFalse({"c", "p"} & set(accels), accels)
			panel.getControl("recordingDirectory").SetValue(os.path.join(self.dir, "no_existe"))
			with mock.patch.object(S, "showError") as err:
				self.assertFalse(panel.isValid())
				err.assert_called_once()
			panel.getControl("recordingDirectory").SetValue("")
			frame.Destroy()
		finally:
			sp.unregister()
		self.assertNotIn(sp.PANEL_ID, S.getPanelIds())


# ====================================================================== complemento y archivos
class ComplementoPruebas(unittest.TestCase):
	def test_manifiesto_y_archivos(self) -> None:
		with open(os.path.join(ADDON_DIR, "manifest.json"), encoding="utf-8") as f:
			m = json.load(f)
		self.assertEqual(m["id"], "zRadioBASS")
		self.assertEqual(m["version"], "1.0.0")
		self.assertEqual(m["minApiVersion"], "1.0")
		self.assertIn("Héctor J. Benítez Corredera", m["author"])
		self.assertTrue(m["changelog"].startswith("Primera versión para Tiresias"))
		self.assertTrue(os.path.isfile(os.path.join(ADDON_DIR, "doc", "es", "readme.html")))
		dlls = sorted(f for f in os.listdir(os.path.join(PKG_DIR, "bass")) if f.endswith(".dll"))
		self.assertEqual(dlls, ["bass.dll", "bass_aac.dll", "bass_fx.dll", "bassenc.dll", "bassflac.dll", "basshls.dll", "bassopus.dll", "basswma.dll"])
		self.assertTrue(os.path.isfile(os.path.join(PKG_DIR, "bass", "LICENCIA-BASS.txt")))
		# Nada de bibliotecas de terceros ni .pyd.
		for rootDir, dirs, files in os.walk(ADDON_DIR):
			dirs[:] = [d for d in dirs if d != "__pycache__"]
			for fn in files:
				self.assertFalse(fn.endswith((".pyd", ".pyc")), fn)
			for d in dirs:
				self.assertNotIn(d, ("lib", "sound_lib", "libloader", "requests", "httpx", "pyradios", "certifi"))

	def test_complemento_global(self) -> None:
		"""Carga el paquete como Tiresias, comprueba órdenes, menú y opciones, y lo descarga."""
		import importlib.util

		from tiresias import gui, queue_handler
		from tiresias.gui import settings as S

		name = "zradiobass_global_pruebas"
		spec = importlib.util.spec_from_file_location(name, os.path.join(PKG_DIR, "__init__.py"), submodule_search_locations=[PKG_DIR])
		mod = importlib.util.module_from_spec(spec)
		sys.modules[name] = mod
		spec.loader.exec_module(mod)
		spoken = []
		with mock.patch.object(queue_handler, "queueFunction", side_effect=lambda f, *a, **k: spoken.append(a[0] if a else None)):
			gp = mod.GlobalPlugin()
			try:
				self.assertIn("zRadioBASS", gui._addonToolsEntries)
				self.assertEqual(gui._addonToolsEntries["zRadioBASS"][0], "&zRadio BASS")
				self.assertIn("zRadioBASS", S.getPanelIds())
				scripts = [n for n in dir(gp) if n.startswith("script_")]
				self.assertEqual(len(scripts), 23)
				for n in scripts:
					f = getattr(type(gp), n)
					self.assertTrue(f.__doc__, n)
					self.assertEqual(f.category, "zRadio BASS", n)
					self.assertEqual(f.gestures, [], n)
				gp._app.set_volume(50)
				gp.script_volume_up(None)
				gp.script_stop(None)
				gp.script_toggle_mute(None)
				gp.script_current_station(None)
				gp.script_recording_status(None)
				gp.script_play_favorite_1(None)
				gp.script_next_favorite(None)
				gp.script_start_recording(None)
				gp.script_stop_recording(None)
				gp.script_toggle_pause(None)
				gp.script_current_title(None)
				gp.script_reload(None)
				gp.script_player_status(None)
				self.assertEqual(
					spoken,
					[
						"55%",
						"No hay nada reproduciéndose",
						"No hay nada para silenciar",
						"No hay ninguna emisora reproduciéndose",
						"No hay grabación activa",
						"No hay emisora favorita en la posición 1",
						"No hay favoritos guardados",
						"No hay ninguna emisora reproduciéndose",
						"No hay ninguna grabación activa",
						"No hay nada reproduciéndose",
						"No hay ninguna emisora reproduciéndose",
						"No hay ninguna emisora para recargar",
						"Sin reproducción activa\nVolumen: 55%",
					],
				)
				gp._app.set_volume(50)
			finally:
				gp.terminate()
		self.assertNotIn("zRadioBASS", gui._addonToolsEntries)
		self.assertNotIn("zRadioBASS", S.getPanelIds())
		for k in [k for k in sys.modules if k == name or k.startswith(name + ".")]:
			del sys.modules[k]

	def test_modulos_existen_en_la_compilada(self) -> None:
		"""Todo lo que importa el complemento está en la versión compilada de Tiresias."""
		import ast
		import zipfile

		dist = os.path.join(ROOT, "dist", "Tiresias", "lib")
		if not os.path.isdir(dist):
			self.skipTest("No hay versión compilada")
		names = set(zipfile.ZipFile(os.path.join(dist, "library.zip")).namelist())
		available = {n.split("/")[0].removesuffix(".pyc") for n in names}
		available |= {n.removesuffix(".pyd").split(".")[0] for n in os.listdir(dist)}
		# Módulos congelados en el ejecutable o que el núcleo usa (comprobados en src).
		frozenOrCore = {"os", "sys", "abc", "io", "codecs", "stat", "ntpath", "datetime", "collections", "struct", "time", "itertools", "math", "importlib", "string", "zlib", "gc", "_thread", "builtins", "errno", "unicodedata", "__future__", "re", "pathlib", "ctypes"}
		mods = set()
		for rootDir, _dirs, files in os.walk(ADDON_DIR):
			for fn in files:
				if fn.endswith(".py"):
					with open(os.path.join(rootDir, fn), encoding="utf-8") as f:
						tree = ast.parse(f.read())
					for node in ast.walk(tree):
						if isinstance(node, ast.Import):
							mods.update(a.name.split(".")[0] for a in node.names)
						elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
							mods.add(node.module.split(".")[0])
		mods -= {"tiresias", "wx", "zradiobass"}
		missing = sorted(m for m in mods if m not in available and m not in frozenOrCore)
		self.assertEqual(missing, [])


# ====================================================================== pruebas reales (red y BASS sin sonido)
@unittest.skipUnless(ONLINE, "Sin conexión con Radio Browser")
class RedRealPruebas(unittest.TestCase):
	"""Peticiones de solo lectura a la API pública de Radio Browser."""

	@classmethod
	def setUpClass(cls) -> None:
		cls.cache = net.ResponseCache(os.path.join(_newDir("real"), "c.db"))
		cls.api = api_client.RadioBrowserAPI(cache=cls.cache, cacheSettings=lambda: (False, 3))

	@classmethod
	def tearDownClass(cls) -> None:
		cls.cache.close()

	def test_servidores_https(self) -> None:
		servers = api_client.discover_servers()
		self.assertTrue(servers)
		self.assertTrue(all(s.endswith(".api.radio-browser.info") for s in servers))
		self.assertTrue(self.api.base_url.startswith("https://"))

	def test_busquedas(self) -> None:
		top = self.api.get_top_stations(limit=5, raise_errors=True)
		self.assertEqual(len(top), 5)
		self.assertTrue(all(s.stationuuid and s.url for s in top))
		es = self.api.get_stations_by_country("ES", limit=10, raise_errors=True)
		self.assertTrue(es)
		self.assertTrue(all(s.countrycode == "ES" for s in es))
		f = models.SearchFilters(name="radio", country="ES", order="votes", reverse=True, limit=5, hide_broken=True)
		res = self.api.search_stations(f, raise_errors=True)
		self.assertTrue(res)
		self.assertTrue(all("radio" in s.name.lower() for s in res))
		uuid = top[0].stationuuid
		self.assertEqual(self.api.get_stations_by_uuid(uuid)[0].stationuuid, uuid)

	def test_listas(self) -> None:
		countries = self.api.get_countries()
		spain = [c for c in countries if c.code == "ES"]
		self.assertTrue(spain)
		self.assertEqual(spain[0].name_localized, "España")
		langs = self.api.get_languages()
		self.assertTrue(any(lang.name == "spanish" for lang in langs))
		tags = self.api.get_tags(limit=20)
		self.assertEqual(len(tags), 20)
		stats = self.api.get_stats()
		self.assertGreater(int(stats.get("stations", 0)), 1000)


@unittest.skipUnless(ONLINE, "Sin conexión a Internet")
class BassRealPruebas(unittest.TestCase):
	"""BASS de verdad con emisoras reales, sin sonido (dispositivo 0 y volumen 0)."""

	@classmethod
	def setUpClass(cls) -> None:
		cls.b = bassmod.get()
		cls.b.configure()
		cls.plugins = cls.b.loadPlugins()
		api = api_client.RadioBrowserAPI()
		cls.stations = [s for s in api.search_stations(models.SearchFilters(codec="MP3", order="votes", reverse=True, limit=15, hide_broken=True)) if s.play_url]
		if not cls.stations:
			raise unittest.SkipTest("No se obtuvieron emisoras")

	def test_bass_cargado(self) -> None:
		self.assertTrue(self.b.versionText.startswith("2.4."))
		for name in bassmod.FORMAT_PLUGINS:
			self.assertTrue(self.plugins.get(name), name)
		self.assertTrue(self.b.canRecord)
		self.assertTrue(self.b.hasEffects)
		# Enumerar dispositivos no inicializa nada ni hace sonar nada.
		self.assertIsInstance(self.b.devices(), list)

	def _first_working(self, decode: bool) -> tuple[int, Station]:
		self.b.initDevice(bassmod.NO_SOUND_DEVICE)
		self.b.setThreadDevice(bassmod.NO_SOUND_DEVICE)
		for st in self.stations:
			try:
				return self.b.streamFromUrl(st.play_url, decode=decode), st
			except bassmod.BassError:
				continue
		self.skipTest("Ninguna emisora respondió")

	def test_decodifica_emisora_real(self) -> None:
		h, st = self._first_working(decode=True)
		try:
			buf = ctypes.create_string_buffer(65536)
			total = 0
			end = time.time() + 4
			while time.time() < end:
				n = self.b.getData(h, buf, 65536)
				if n > 0:
					total += n
				else:
					time.sleep(0.05)
			self.assertGreater(total, 44100, st.name)
			self.assertEqual(self.b.formatName(h), "MP3")
		finally:
			self.b.free(h)

	def test_formatos_hls_aac_flac(self) -> None:
		"""Emisoras HLS (.m3u8, con basshls), AAC y FLAC reales decodificadas sin sonido."""
		api = api_client.RadioBrowserAPI()
		self.b.initDevice(bassmod.NO_SOUND_DEVICE)
		self.b.setThreadDevice(bassmod.NO_SOUND_DEVICE)
		buf = ctypes.create_string_buffer(65536)
		checked = {}
		for label, codec, want_hls in (("HLS", "AAC", True), ("HLS", "AAC+", True), ("AAC", "AAC", False), ("FLAC", "FLAC", False)):
			if checked.get(label):
				continue
			res = api.search_stations(models.SearchFilters(codec=codec, order="votes", reverse=True, limit=300, hide_broken=True))
			for st in [s for s in res if bool(s.hls) == want_hls][:4]:
				try:
					h = self.b.streamFromUrl(st.play_url, decode=True)
				except bassmod.BassError:
					continue
				try:
					total = 0
					end = time.time() + 4
					while time.time() < end and total < 44100 * 4:
						n = self.b.getData(h, buf, 65536)
						if n > 0:
							total += n
						else:
							time.sleep(0.05)
				finally:
					self.b.free(h)
				if total > 44100:
					checked[label] = st.name
					break
		self.assertIn("HLS", checked, "Ninguna emisora HLS se pudo decodificar")
		self.assertIn("AAC", checked)
		self.assertIn("FLAC", checked)

	def test_reproductor_sin_sonido_y_grabacion(self) -> None:
		p = player_mod.AudioPlayer(fixed_device=bassmod.NO_SOUND_DEVICE)
		p.volume = 0
		d = _newDir("realrec")
		try:
			for st in self.stations[:6]:
				p.play(st.play_url, station=st)
				if _wait(lambda: p.state == player_mod.PlayerState.PLAYING and p.handle and p.bass.positionSeconds(p.handle) > 0.5, 10):
					break
			else:
				self.skipTest("Ninguna emisora empezó a sonar")
			h = p.handle
			self.assertEqual(p.bass.getAttribute(h, bassmod.BASS_ATTRIB_VOL), 0.0)
			self.assertGreater(p.bass.positionSeconds(h), 0.5)
			self.assertTrue(p.start_recording(os.path.join(d, "real.wav")))
			time.sleep(2.5)
			path = p.stop_recording()
			self.assertGreater(os.path.getsize(path), 100000)
			with open(path, "rb") as f:
				self.assertEqual(f.read(4), b"RIFF")
			import wave

			with wave.open(path) as w:
				self.assertGreater(w.getnframes(), 44100)
			p.set_effects(3, 0, -3, 0)
			self.assertTrue(p._fx)
			info = p.stream_info()
			self.assertEqual(info.get("format"), "MP3")
		finally:
			p.dispose()

	def test_grabacion_programada_real(self) -> None:
		d = _newDir("realsched")
		st = self.stations[0]
		done = threading.Event()
		rec = recording.StreamRecorder(bassmod.get, st.play_url, os.path.join(d, "prog.wav"), datetime.now() + timedelta(seconds=4), on_finish=lambda r: done.set())
		rec.start()
		self.assertTrue(done.wait(30))
		if rec.error and not rec.bytes:
			self.skipTest(f"La emisora no respondió: {rec.error}")
		self.assertGreater(rec.bytes, 44100)
		self.assertGreater(os.path.getsize(rec.path), 44100)


if __name__ == "__main__":
	unittest.main()
