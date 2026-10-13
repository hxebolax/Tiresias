"""Pruebas del cliente de actualizaciones y de la tienda contra un servidor
HTTP local que sirve la estructura que genera tools/publicar.py."""

from __future__ import annotations

import functools
import http.server
import io
import json
import os
import shutil
import socket
import ssl
import sys
import tempfile
import threading
import unittest
import zipfile
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import publicar  # noqa: E402
from test_publicacion import makeAddon, makeArtifacts  # noqa: E402
from tiresias import addon_store, addons, installer, paths, updates  # noqa: E402
from tiresias.config import conf  # noqa: E402


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
	def log_message(self, *args):
		pass


class _Server6(http.server.ThreadingHTTPServer):
	address_family = socket.AF_INET6


class ServidorLocal:
	"""Servidor HTTP en 127.0.0.1 con la carpeta publicada."""

	def __init__(self, folder: str) -> None:
		handler = functools.partial(_QuietHandler, directory=folder)
		# Se prefiere ::1: en algunos equipos un filtro de red corta al azar las
		# conexiones locales por IPv4 (127.0.0.1) y las pruebas fallarían sin motivo.
		try:
			self.httpd = _Server6(("::1", 0), handler)
			self.url = f"http://[::1]:{self.httpd.server_address[1]}"
		except OSError:
			self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
			self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
		self.thread = threading.Thread(target=self.httpd.serve_forever, args=(0.05,), daemon=True)
		self.thread.start()
		self._warmUp()

	def _warmUp(self) -> None:
		# Se espera a que el servidor responda con normalidad antes de empezar.
		import time
		import urllib.request

		ok, deadline = 0, time.monotonic() + 15
		while ok < 5 and time.monotonic() < deadline:
			try:
				with urllib.request.urlopen(self.url + "/actualizacion.json", timeout=5) as r:
					r.read()
				ok += 1
			except OSError:
				ok = 0
				time.sleep(0.1)

	def close(self) -> None:
		self.httpd.shutdown()
		self.httpd.server_close()


class ClienteTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.tmp = tempfile.mkdtemp(prefix="tiresias_cli_")
		cls.web = os.path.join(cls.tmp, "web")
		work = os.path.join(cls.tmp, "work")
		pk = os.path.join(work, "pk")
		news = os.path.join(work, "novedades.html")
		os.makedirs(work)
		with open(news, "w", encoding="utf-8") as f:
			f.write("<!DOCTYPE html><title>Novedades</title>")
		cls.addonV1 = makeAddon(pk, "pruebatienda", "1.0.0")
		cls.addonV2 = makeAddon(pk, "pruebatienda", "2.0.0", extra={"minApiVersion": "99.0", "lastTestedApiVersion": "99.0"})
		cls.addonV11 = makeAddon(os.path.join(work, "pk2"), "pruebatienda", "1.1.0")
		with redirect_stdout(io.StringIO()):
			publicar.publish(cls.web, publicar.Release("9.9.0", makeArtifacts(os.path.join(work, "a"), "9.9.0"), [cls.addonV1, cls.addonV2, cls.addonV11], notes="Muchas novedades", newsHtml=news))
			publicar.publish(cls.web, publicar.Release("9.9.1b1", makeArtifacts(os.path.join(work, "b"), "9.9.1b1"), [], channel="beta", newsHtml=news))
		cls.server = ServidorLocal(cls.web)

	@classmethod
	def tearDownClass(cls):
		cls.server.close()
		shutil.rmtree(cls.tmp, ignore_errors=True)

	def setUp(self):
		self.saved = {k: conf["update"][k] for k in ("serverUrl", "checkUrl", "channel", "lastCheck")}
		self.savedCat = conf["addons"]["catalogUrl"]
		conf["update"]["serverUrl"] = self.server.url + "/"
		conf["update"]["checkUrl"] = ""
		conf["update"]["channel"] = "estable"
		conf["addons"]["catalogUrl"] = ""
		self.dl = tempfile.mkdtemp(prefix="tiresias_dl_")

	def tearDown(self):
		for k, v in self.saved.items():
			conf["update"][k] = v
		conf["addons"]["catalogUrl"] = self.savedCat
		shutil.rmtree(self.dl, ignore_errors=True)

	# --------------------------------------------------------------- direcciones
	def test_direcciones_derivadas_de_la_constante(self):
		self.assertEqual(updates.distributionUrl(), self.server.url)
		self.assertEqual(updates.updateUrl(), self.server.url + "/actualizacion.json")
		self.assertEqual(addon_store.catalogUrl(), self.server.url + "/complementos/catalogo.json")
		conf["update"]["serverUrl"] = ""
		with mock.patch.object(updates, "DISTRIBUTION_URL", "https://usuario.github.io/tiresias"):
			self.assertEqual(updates.updateUrl(), "https://usuario.github.io/tiresias/actualizacion.json")
			self.assertEqual(addon_store.catalogUrl(), "https://usuario.github.io/tiresias/complementos/catalogo.json")
		# La dirección concreta de Opciones tiene preferencia.
		conf["update"]["checkUrl"] = "https://otra/act.json"
		self.assertEqual(updates.updateUrl(), "https://otra/act.json")

	def test_resolver_relativas(self):
		self.assertEqual(updates.resolveUrl("https://x.org/Tiresias/actualizacion.json", "descargas/1.0/a.exe"), "https://x.org/Tiresias/descargas/1.0/a.exe")
		self.assertEqual(updates.resolveUrl("https://x.org/Tiresias/complementos/catalogo.json", "w/w-1.tiresias-addon"), "https://x.org/Tiresias/complementos/w/w-1.tiresias-addon")
		self.assertEqual(updates.resolveUrl("https://x.org/a.json", "https://y.org/b"), "https://y.org/b")
		self.assertEqual(updates.resolveUrl(r"C:\web\actualizacion.json", "descargas/a.exe"), os.path.normpath(r"C:\web\descargas\a.exe"))

	# --------------------------------------------------------------- actualización
	def test_comprobar_y_descargar_instalador(self):
		with mock.patch.object(updates, "copyKind", return_value="instalada"):
			info = updates.checkForUpdate()
		self.assertIsNotNone(info)
		self.assertEqual(info.version, "9.9.0")
		self.assertEqual(info.package, "installer")
		self.assertEqual(info.url, self.server.url + "/descargas/9.9.0/Tiresias-9.9.0-instalador.exe")
		self.assertEqual(info.notesUrl, self.server.url + "/novedades.html")
		self.assertEqual(info.notes, "Muchas novedades")
		self.assertTrue(info.supported)
		path = updates.download(info.url, os.path.join(self.dl, "i.exe"), info.sha256, size=info.size)
		self.assertEqual(updates.fileSha256(path), info.sha256)
		self.assertEqual(os.path.getsize(path), info.size)

	def test_descarga_rechaza_suma_o_tamano_incorrectos(self):
		with mock.patch.object(updates, "copyKind", return_value="instalada"):
			info = updates.checkForUpdate()
		dest = os.path.join(self.dl, "x.exe")
		with self.assertRaises(ValueError):
			updates.download(info.url, dest, "0" * 64, size=info.size)
		with self.assertRaises(ValueError):
			updates.download(info.url, dest, info.sha256, size=info.size + 1)
		self.assertFalse(os.path.exists(dest))
		self.assertFalse(os.path.exists(dest + ".part"))

	def test_copia_portable_elige_zip_portable(self):
		with mock.patch.object(updates, "copyKind", return_value="portable"):
			info = updates.checkForUpdate()
		self.assertEqual(info.package, "portable")
		self.assertTrue(info.url.endswith("/descargas/9.9.0/Tiresias-9.9.0-portable.zip"))
		with mock.patch.object(updates.paths, "cacheDir", return_value=self.dl):
			path = updates.downloadUpdate(info)
			self.assertEqual(os.path.basename(path), "Tiresias-9.9.0-portable.zip")
			folder = updates.extractPortable(path)
		self.assertTrue(os.path.isfile(os.path.join(folder, "Tiresias.exe")))

	def test_codigo_fuente_elige_zip_de_codigo(self):
		with mock.patch.object(updates, "copyKind", return_value="codigo"):
			info = updates.checkForUpdate()
		self.assertEqual(info.package, "source")

	def test_canal_beta(self):
		conf["update"]["channel"] = "beta"
		info = updates.checkForUpdate()
		self.assertEqual((info.version, info.channel), ("9.9.1b1", "beta"))
		conf["update"]["channel"] = "estable"
		self.assertEqual(updates.checkForUpdate().version, "9.9.0")

	def test_sin_version_nueva(self):
		data = updates.fetchJson(updates.updateUrl())
		self.assertIsNone(updates.parseUpdate(data, updates.updateUrl(), current="9.9.0"))
		self.assertIsNone(updates.parseUpdate(data, updates.updateUrl(), current="10.0"))

	def test_windows_minimo(self):
		info = updates.parseUpdate({"version": "99.0", "url": "a.exe", "minWindows": "99.0.0"}, "https://x/act.json")
		self.assertFalse(info.supported)
		self.assertTrue(updates.isWindowsSupported("6.1"))

	def test_orden_de_versiones(self):
		k = updates.versionKey
		self.assertLess(k("1.1.0b1"), k("1.1.0b2"))
		self.assertLess(k("1.1.0b2"), k("1.1.0rc1"))
		self.assertLess(k("1.1.0rc1"), k("1.1.0"))
		self.assertLess(k("1.0.9"), k("1.1.0a1"))
		self.assertEqual(updates.compareVersions("1.0.2", "1.0.2.0"), 0)

	def test_https_verifica_certificado(self):
		ctx = updates.sslContext()
		self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
		self.assertTrue(ctx.check_hostname)
		with mock.patch.object(updates.urllib.request, "urlopen") as op:
			updates.openUrl("https://ejemplo.invalid/a.json", noCache=True)
		self.assertIs(op.call_args.kwargs["context"], ctx)
		self.assertEqual(op.call_args.args[0].get_header("Cache-control"), "no-cache")

	# --------------------------------------------------------------- tienda
	def test_catalogo_y_version_compatible(self):
		entries, src = addon_store.fetchCatalog()
		self.assertEqual(src, self.server.url + "/complementos/catalogo.json")
		e = next(x for x in entries if x.id == "pruebatienda")
		# La 2.0.0 exige una API futura: se ofrece la 1.1.0, la más reciente compatible.
		self.assertEqual(e.version, "1.1.0")
		self.assertEqual(e.url, self.server.url + "/complementos/pruebatienda/pruebatienda-1.1.0.tiresias-addon")
		self.assertEqual(len(e.extra["versions"]), 3)

	def test_actualizacion_de_complementos_y_descarga(self):
		entries, _src = addon_store.fetchCatalog()
		e = next(x for x in entries if x.id == "pruebatienda")
		old = SimpleNamespace(version="1.0.0")
		with mock.patch.object(addons, "getAddon", return_value=old):
			self.assertEqual(e.status(), "update")
			self.assertEqual([x.id for x in addon_store.availableUpdates(entries)], ["pruebatienda"])
		with mock.patch.object(addon_store.paths, "cacheDir", return_value=self.dl):
			path = addon_store.downloadPackage(e)
		self.assertEqual(updates.fileSha256(path), e.sha256)
		with zipfile.ZipFile(path) as z:
			self.assertEqual(json.loads(z.read("manifest.json"))["version"], "1.1.0")

	def test_copia_local_resuelve_respecto_al_servidor(self):
		local = os.path.join(self.dl, "catalogo_complementos.json")
		shutil.copyfile(os.path.join(self.web, "complementos", "catalogo.json"), local)
		conf["addons"]["catalogUrl"] = "http://127.0.0.1:1/no-existe.json"
		with mock.patch.object(addon_store, "localCatalogPath", return_value=local), mock.patch.object(updates, "TIMEOUT", 2):
			entries, src = addon_store.fetchCatalog()
		self.assertEqual(src, local)
		e = next(x for x in entries if x.id == "pruebatienda")
		self.assertEqual(e.url, "http://127.0.0.1:1/pruebatienda/pruebatienda-1.1.0.tiresias-addon")


class PortableUpdateTests(unittest.TestCase):
	"""Aplicación de una actualización a una copia portable."""

	def setUp(self):
		self.tmp = tempfile.mkdtemp(prefix="tiresias_port_")
		self.old = os.path.join(self.tmp, "Tiresias")
		self.new = os.path.join(self.tmp, "nueva")
		self.files(self.old, {
			"Tiresias.exe": "viejo",
			"lib/viejo.pyc": "x",
			"python313.dll": "viejo",
			"policy.json": "{}",
			"data/config/config.json": '{"mio": 1}',
			"data/symbols/es.json": "viejo",
			"data/config/symbols_user.json": "mio",
			"data/speechDicts/default.json": "mio",
			"data/locale/es.mo": "viejo",
			"data/addons/eloquence/manifest.json": json.dumps({"id": "eloquence", "version": "1.0.0"}),
			"data/addons/whatsapp/manifest.json": json.dumps({"id": "whatsapp", "version": "1.0.0"}),
		})
		self.files(self.new, {
			"Tiresias.exe": "nuevo",
			"lib/nuevo.pyc": "x",
			"python313.dll": "nuevo",
			"data/symbols/es.json": "nuevo",
			"data/speechDicts/default.json": "de fábrica",
			"data/locale/es.mo": "nuevo",
			"data/addons/whatsapp/manifest.json": json.dumps({"id": "whatsapp", "version": "1.1.0"}),
		})

	def tearDown(self):
		shutil.rmtree(self.tmp, ignore_errors=True)

	def files(self, base, mapping):
		for rel, text in mapping.items():
			p = os.path.join(base, *rel.split("/"))
			os.makedirs(os.path.dirname(p), exist_ok=True)
			with open(p, "w", encoding="utf-8") as f:
				f.write(text)

	def read(self, rel):
		with open(os.path.join(self.old, *rel.split("/")), encoding="utf-8") as f:
			return f.read()

	def test_actualiza_y_conserva_lo_del_usuario(self):
		installer.applyPortableUpdate(self.new, self.old)
		self.assertEqual(self.read("Tiresias.exe"), "nuevo")
		self.assertEqual(self.read("python313.dll"), "nuevo")
		self.assertTrue(os.path.isfile(os.path.join(self.old, "lib", "nuevo.pyc")))
		self.assertFalse(os.path.exists(os.path.join(self.old, "lib", "viejo.pyc")))
		self.assertEqual(self.read("policy.json"), "{}")
		self.assertEqual(self.read("data/config/config.json"), '{"mio": 1}')
		self.assertEqual(self.read("data/symbols/es.json"), "nuevo")
		# Los símbolos del usuario están en config\symbols_user*.json.
		self.assertEqual(self.read("data/config/symbols_user.json"), "mio")
		self.assertEqual(self.read("data/speechDicts/default.json"), "mio")
		self.assertEqual(self.read("data/locale/es.mo"), "nuevo")
		# Eloquence (no viene en la versión pública) se conserva; WhatsApp se actualiza.
		self.assertIn("1.0.0", self.read("data/addons/eloquence/manifest.json"))
		self.assertIn("1.1.0", self.read("data/addons/whatsapp/manifest.json"))
		self.assertFalse(os.path.exists(os.path.join(self.old, installer.UPDATE_BACKUP_DIR)))

	def test_si_falla_restaura(self):
		real = installer.copyTree
		calls = [0]

		def failing(src, dst, *a, **kw):
			calls[0] += 1
			if calls[0] == 3:
				raise OSError("disco lleno")
			return real(src, dst, *a, **kw)

		with mock.patch.object(installer, "copyTree", side_effect=failing), self.assertRaises(OSError):
			installer.applyPortableUpdate(self.new, self.old)
		self.assertEqual(self.read("Tiresias.exe"), "viejo")
		self.assertEqual(self.read("python313.dll"), "viejo")
		self.assertTrue(os.path.isfile(os.path.join(self.old, "lib", "viejo.pyc")))
		self.assertEqual(self.read("data/locale/es.mo"), "viejo")
		self.assertFalse(os.path.exists(os.path.join(self.old, installer.UPDATE_BACKUP_DIR)))

	def test_no_toca_copias_instaladas(self):
		self.files(self.old, {paths.INSTALLED_MARKER: "{}"})
		with self.assertRaises(ValueError):
			installer.applyPortableUpdate(self.new, self.old)

	def test_orden_de_linea_de_ordenes(self):
		args = SimpleNamespace(apply_update=self.old, wait_pid=0)
		with mock.patch.object(installer.paths, "APP_DIR", self.new), mock.patch.object(installer.subprocess, "Popen") as popen:
			code = installer.runApplyUpdate(args)
		self.assertEqual(code, 0)
		popen.assert_called_once()
		self.assertEqual(popen.call_args.args[0], [os.path.join(self.old, "Tiresias.exe")])
		with open(os.path.join(self.old, "data", updates.RESULT_FILE), encoding="utf-8") as f:
			self.assertTrue(json.load(f)["ok"])
		self.assertEqual(self.read("Tiresias.exe"), "nuevo")

	def test_espera_proceso_terminado(self):
		self.assertTrue(installer.waitForProcess(0))
		self.assertTrue(installer.waitForProcess(999999, timeout=0.1))


if __name__ == "__main__":
	unittest.main()
