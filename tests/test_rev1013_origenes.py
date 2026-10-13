"""Revisión 1.0.13: varios orígenes de distribución (servidor del proyecto y GitHub).

- Cliente (updates y addon_store) contra servidores HTTP locales falsos (en
  ``::1`` o, sin IPv6, en 127.0.0.1): el «servidor del proyecto» y un «GitHub»
  que redirige cada descarga a otro host (como hace GitHub con
  *.githubusercontent.com; aquí, de la dirección numérica a «localhost»).
  Elección de versión, origen caído o que no responde, descarga que falla y
  se reintenta en el otro origen, SHA-256 obligatorio, fusión de catálogos,
  complementos propietarios solo en el servidor.
- Opción ``update.origin``: compatibilidad con configuraciones antiguas
  (``update.serverUrl``), política de empresa y panel de Opciones.
- ``tools/publicar.py``: publicación en GitHub con un ``gh`` simulado
  (``subprocess.run``), idempotencia, exclusión de propietarios, ``--simular``
  sin llamar a ``gh`` y errores claros si ``gh`` falta o no tiene sesión.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev1013_origenes``
"""

from __future__ import annotations

import copy
import http.server
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_rev1013_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()

import publicar  # noqa: E402
from test_publicacion import makeAddon, makeArtifacts  # noqa: E402
from tiresias import addon_store, updates  # noqa: E402
from tiresias.config import conf, migrations, validation  # noqa: E402
from tiresias.config import policy as policyModule  # noqa: E402

REPO = "hxebolax/Tiresias"
NEWS = """<!DOCTYPE html><html lang="es"><body><h1>Novedades</h1>
<h2 id="v9-9-0">Versión 9.9.0</h2>
<p>Versión de <strong>prueba</strong> con <kbd>Control+T</kbd> y un <a href="https://ejemplo.org/x">enlace</a>.</p>
<h3>Voz</h3>
<ul><li>Primera novedad.</li><li>Segunda &amp; última.</li></ul>
<h2 id="v9-8-0">Versión 9.8.0</h2><p>Lo anterior.</p>
</body></html>"""


def quiet(func, *args, **kwargs):
	with redirect_stdout(io.StringIO()):
		return func(*args, **kwargs)


# ====================================================================== servidores HTTP falsos
class _Handler(http.server.BaseHTTPRequestHandler):
	def log_message(self, *args):
		pass

	def _send(self, status: int, body: bytes, headers: dict | None = None) -> None:
		self.send_response(status)
		for k, v in (headers or {}).items():
			self.send_header(k, v)
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		if self.command != "HEAD":
			self.wfile.write(body)

	def do_GET(self):  # noqa: N802
		srv = self.server
		path = urllib.parse.unquote(self.path.split("?", 1)[0])
		srv.hits.append(path)
		override = srv.overrides.get(path)
		if override is not None:
			status, body = override
			if status == "colgado":
				time.sleep(6)
				return
			self._send(status, body)
			return
		if srv.redirectTo:
			# Como GitHub: /<repo>/releases/download/<etiqueta>/<archivo> -> otro host.
			prefix = f"/{REPO}/releases/download/"
			if path.startswith(prefix):
				self._send(302, b"", {"Location": srv.redirectTo + "/" + urllib.parse.quote(path[len(prefix) :])})
				return
			self._send(404, b"no")
			return
		file = os.path.join(srv.root, *[p for p in path.split("/") if p and p not in (".", "..")])
		if os.path.isfile(file):
			with open(file, "rb") as f:
				self._send(200, f.read())
		else:
			self._send(404, b"no")


class _Server6(http.server.ThreadingHTTPServer):
	address_family = socket.AF_INET6


class FakeHost:
	"""Servidor HTTP local que sirve ``root`` o redirige a ``redirectTo``.

	Como en test_actualizaciones, se prefiere ``::1``: en algunos equipos un
	filtro de red corta al azar las conexiones locales por IPv4 (127.0.0.1,
	WinError 10054). Si no hay IPv6, se usa 127.0.0.1. ``hostUrl`` es la misma
	dirección con otro nombre de host («localhost»), para las redirecciones.
	"""

	def __init__(self, root: str = "", redirectTo: str = "") -> None:
		try:
			self.httpd = _Server6(("::1", 0), _Handler)
			self.url = f"http://[::1]:{self.httpd.server_address[1]}"
		except OSError:
			self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
			self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
		self.httpd.root = root
		self.httpd.redirectTo = redirectTo
		self.httpd.overrides = {}
		self.httpd.hits = []
		self.port = self.httpd.server_address[1]
		self.hostUrl = f"http://localhost:{self.port}"
		threading.Thread(target=self.httpd.serve_forever, args=(0.05,), daemon=True).start()

	@property
	def overrides(self) -> dict:
		return self.httpd.overrides

	@property
	def hits(self) -> list:
		return self.httpd.hits

	def warmUp(self, path: str) -> None:
		ok, deadline = 0, time.monotonic() + 15
		while ok < 3 and time.monotonic() < deadline:
			try:
				with urllib.request.urlopen(self.url + path, timeout=5) as r:
					r.read()
				ok += 1
			except OSError:
				ok = 0
				time.sleep(0.1)

	def close(self) -> None:
		self.httpd.shutdown()
		self.httpd.server_close()


# ====================================================================== gh simulado
class FakeGh:
	"""``gh`` de mentira: las versiones de GitHub son carpetas ``root/<etiqueta>``."""

	def __init__(self, root: str) -> None:
		self.root = root
		self.calls: list[list[str]] = []
		self.creates: dict[str, list[str]] = {}
		self.edits: list[tuple[str, list[str]]] = []
		self.uploads: list[tuple[str, list[str]]] = []
		self.notes: dict[str, str] = {}
		self.authOk = True
		self.repoOk = True

	def __call__(self, cmd, **kw):
		args = list(cmd[1:])
		self.calls.append(args)

		def done(rc=0, out="", err=""):
			return subprocess.CompletedProcess(cmd, rc, out, err)

		if args[:1] == ["--version"]:
			return done(0, "gh version 2.80.0 (simulado)")
		if args[:2] == ["auth", "status"]:
			return done(0) if self.authOk else done(1, "", "You are not logged into any GitHub hosts. To log in, run: gh auth login")
		if args[:2] == ["repo", "view"]:
			return done(0, '{"name":"Tiresias"}') if self.repoOk else done(1, "", "GraphQL: Could not resolve to a Repository")
		if args[0] != "release":
			return done(1, "", "orden desconocida")
		sub, tag, rest = args[1], args[2], args[3:]
		files = []
		while rest and not rest[0].startswith("--"):
			files.append(rest.pop(0))
		opts = rest
		folder = os.path.join(self.root, tag)

		def opt(name):
			return opts[opts.index(name) + 1] if name in opts else None

		if sub == "view":
			if not os.path.isdir(folder):
				return done(1, "", "release not found")
			assets = [{"name": n, "size": os.path.getsize(os.path.join(folder, n))} for n in sorted(os.listdir(folder))]
			return done(0, json.dumps({"assets": assets}))
		if sub == "create":
			if os.path.isdir(folder):
				return done(1, "", "a release with the same tag name already exists")
			os.makedirs(folder)
			for f in files:
				shutil.copyfile(f, os.path.join(folder, os.path.basename(f)))
			self.creates[tag] = opts
			with open(opt("--notes-file"), encoding="utf-8") as fh:
				self.notes[tag] = fh.read()
			return done(0)
		if sub == "edit":
			if not os.path.isdir(folder):
				return done(1, "", "release not found")
			self.edits.append((tag, opts))
			with open(opt("--notes-file"), encoding="utf-8") as fh:
				self.notes[tag] = fh.read()
			return done(0)
		if sub == "upload":
			if not os.path.isdir(folder):
				return done(1, "", "release not found")
			for f in files:
				target = os.path.join(folder, os.path.basename(f))
				if os.path.exists(target) and "--clobber" not in opts:
					return done(1, "", "asset already exists")
				shutil.copyfile(f, target)
			self.uploads.append((tag, [os.path.basename(f) for f in files]))
			return done(0)
		if sub == "download":
			name, dest = opt("--pattern"), opt("--dir")
			src = os.path.join(folder, name)
			if not os.path.isfile(src):
				return done(1, "", "no assets match the file pattern")
			os.makedirs(dest, exist_ok=True)
			shutil.copyfile(src, os.path.join(dest, name))
			return done(0)
		return done(1, "", "orden desconocida")


def _noGh(*args, **kwargs):
	raise AssertionError("no se debe llamar a gh")


# ====================================================================== publicación en GitHub
class PublicarGithubTests(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.mkdtemp(prefix="tiresias_pubgh_")
		self.work = os.path.join(self.tmp, "work")
		self.ghroot = os.path.join(self.tmp, "github")
		os.makedirs(self.ghroot)
		self.news = os.path.join(self.tmp, "novedades.html")
		with open(self.news, "w", encoding="utf-8") as f:
			f.write(NEWS)
		pk = os.path.join(self.work, "pk")
		self.wa = makeAddon(pk, "whatsapp", "1.0.0")
		self.elo = makeAddon(pk, "eloquence", "1.0.0", files={"synthDrivers/eci/ECI.DLL": b"x"})
		self.alvaro = makeAddon(pk, "NeuralVoices-voz-Alvaro", "1.0.0", extra={"proprietary": True})
		self.neural = makeAddon(pk, "NeuralVoices", "1.0.0")
		self.fake = FakeGh(self.ghroot)
		self.patch = mock.patch.object(publicar.subprocess, "run", side_effect=self.fake)
		self.patch.start()

	def tearDown(self):
		self.patch.stop()
		shutil.rmtree(self.tmp, ignore_errors=True)

	def release(self, version="9.9.0", channel="estable", files=None, packages=None, **kw):
		files = files or makeArtifacts(os.path.join(self.work, version), version)
		pk = [self.wa, self.elo, self.alvaro, self.neural] if packages is None else packages
		return publicar.Release(version, files, pk, channel=channel, notes=f"Notas {version}", newsHtml=self.news, date="2026-10-13", storeProprietary=True, **kw)

	def readAsset(self, tag, name):
		with open(os.path.join(self.ghroot, tag, name), encoding="utf-8") as f:
			return json.load(f)

	def test_publica_version_distribucion_y_complementos(self):
		gh = quiet(publicar.publishGithub, self.release(), REPO)
		self.assertTrue(gh.actions)
		self.assertEqual(
			sorted(os.listdir(os.path.join(self.ghroot, "v9.9.0"))),
			sorted(n + s for n in ("Tiresias-9.9.0-instalador.exe", "Tiresias-9.9.0-portable.zip", "Tiresias-9.9.0-codigo-fuente.zip") for s in ("", ".sha256")),
		)
		# Complementos: nunca los propietarios (Eloquence y la voz Álvaro); el motor NeuralVoices sí.
		addonsDir = sorted(os.listdir(os.path.join(self.ghroot, "complementos")))
		self.assertEqual(addonsDir, ["NeuralVoices-1.0.0.tiresias-addon", "NeuralVoices-1.0.0.tiresias-addon.sha256", "whatsapp-1.0.0.tiresias-addon", "whatsapp-1.0.0.tiresias-addon.sha256"])
		self.assertEqual(sorted(os.listdir(os.path.join(self.ghroot, "distribucion"))), ["actualizacion.json", "catalogo.json", "versiones.json"])
		man = self.readAsset("distribucion", "actualizacion.json")
		base = f"https://github.com/{REPO}/releases/download/v9.9.0/"
		self.assertEqual(man["version"], "9.9.0")
		self.assertEqual(man["url"], base + "Tiresias-9.9.0-instalador.exe")
		self.assertEqual(man["portable"]["url"], base + "Tiresias-9.9.0-portable.zip")
		self.assertEqual(man["source"]["url"], base + "Tiresias-9.9.0-codigo-fuente.zip")
		self.assertEqual(man["notesUrl"], f"https://github.com/{REPO}/releases/tag/v9.9.0")
		self.assertEqual(man["sha256"], updates.fileSha256(os.path.join(self.ghroot, "v9.9.0", "Tiresias-9.9.0-instalador.exe")))
		with open(os.path.join(self.ghroot, "v9.9.0", "Tiresias-9.9.0-portable.zip.sha256"), encoding="utf-8") as f:
			self.assertEqual(f.read(), f"{man['portable']['sha256']} *Tiresias-9.9.0-portable.zip\n")
		cat = self.readAsset("distribucion", "catalogo.json")
		self.assertEqual([a["id"] for a in cat["addons"]], ["NeuralVoices", "whatsapp"])
		wa = cat["addons"][1]
		self.assertEqual(wa["url"], f"https://github.com/{REPO}/releases/download/complementos/whatsapp-1.0.0.tiresias-addon")
		self.assertEqual(wa["sha256"], updates.fileSha256(self.wa))
		self.assertTrue(all("://" in v["url"] for v in wa["versions"]))
		self.assertFalse(any(a.get("proprietary") for a in cat["addons"]))
		# Lo que lee el cliente: las URL absolutas de GitHub se aceptan.
		info = updates.parseUpdate(man, updates.githubAssetUrl("distribucion", "actualizacion.json"), channel="estable", kind="instalada", current="1.0")
		self.assertEqual(info.url, man["url"])
		entries = addon_store.parseCatalog(cat, updates.githubAssetUrl("distribucion", "catalogo.json"))
		self.assertEqual({e.id for e in entries}, {"NeuralVoices", "whatsapp"})
		# Las versiones fijas no compiten por «la última»; la del programa sí.
		self.assertIn("--prerelease", self.fake.creates["distribucion"])
		self.assertIn("--prerelease", self.fake.creates["complementos"])
		self.assertIn("--latest", self.fake.creates["v9.9.0"])
		self.assertNotIn("--prerelease", self.fake.creates["v9.9.0"])
		# Notas: las novedades de esa versión en Markdown y las descargas con su SHA-256.
		notes = self.fake.notes["v9.9.0"]
		self.assertIn("Versión de **prueba** con Control+T y un [enlace](https://ejemplo.org/x).", notes)
		self.assertIn("### Voz", notes)
		self.assertIn("- Segunda & última.", notes)
		self.assertNotIn("Lo anterior", notes)
		self.assertIn(man["sha256"], notes)
		# El orden: la distribución se sube lo último (el manifiesto nunca apunta a recursos ausentes).
		created = [c[2] for c in self.fake.calls if c[:2] == ["release", "create"]]
		self.assertEqual(created, ["v9.9.0", "complementos", "distribucion"])

	def test_idempotente_y_sustituye_recursos(self):
		rel = self.release()
		quiet(publicar.publishGithub, rel, REPO)
		self.fake.uploads.clear()
		self.fake.edits.clear()
		quiet(publicar.publishGithub, rel, REPO)
		# Nada nuevo: solo se actualizan las notas y se sustituyen los JSON de «distribucion».
		self.assertEqual([t for t, _f in self.fake.uploads], ["distribucion"])
		self.assertEqual([t for t, _o in self.fake.edits], ["v9.9.0"])
		self.assertEqual(len(self.readAsset("distribucion", "versiones.json")["versions"]), 1)
		self.assertEqual(len(self.readAsset("distribucion", "catalogo.json")["addons"][1]["versions"]), 1)
		# La misma versión con otro instalador: se sustituye solo ese recurso (--clobber).
		self.fake.uploads.clear()
		with open(rel.files["installer"], "ab") as f:
			f.write(b"cambio")
		quiet(publicar.publishGithub, rel, REPO)
		self.assertEqual(self.fake.uploads[0], ("v9.9.0", ["Tiresias-9.9.0-instalador.exe", "Tiresias-9.9.0-instalador.exe.sha256"]))
		man = self.readAsset("distribucion", "actualizacion.json")
		self.assertEqual(man["sha256"], updates.fileSha256(rel.files["installer"]))
		self.assertEqual(updates.fileSha256(os.path.join(self.ghroot, "v9.9.0", "Tiresias-9.9.0-instalador.exe")), man["sha256"])

	def test_dos_versiones_y_beta(self):
		quiet(publicar.publishGithub, self.release("9.9.0"), REPO)
		wa2 = makeAddon(os.path.join(self.work, "pk2"), "whatsapp", "1.1.0")
		quiet(publicar.publishGithub, self.release("9.9.1", packages=[wa2]), REPO)
		quiet(publicar.publishGithub, self.release("9.10.0b1", channel="beta", packages=[]), REPO)
		man = self.readAsset("distribucion", "actualizacion.json")
		self.assertEqual(man["version"], "9.9.1")
		self.assertEqual(man["channels"]["beta"]["version"], "9.10.0b1")
		self.assertIn("--prerelease", self.fake.creates["v9.10.0b1"])
		self.assertEqual([v["version"] for v in self.readAsset("distribucion", "versiones.json")["versions"]], ["9.10.0b1", "9.9.1", "9.9.0"])
		# Las versiones de complementos que ya estaban en GitHub se conservan en el catálogo.
		wa = next(a for a in self.readAsset("distribucion", "catalogo.json")["addons"] if a["id"] == "whatsapp")
		self.assertEqual(wa["version"], "1.1.0")
		self.assertEqual([v["version"] for v in wa["versions"]], ["1.1.0", "1.0.0"])
		self.assertTrue(os.path.isfile(os.path.join(self.ghroot, "complementos", "whatsapp-1.0.0.tiresias-addon")))

	def test_historial_del_servidor_sin_propietarios(self):
		web = os.path.join(self.tmp, "web")
		old = makeAddon(os.path.join(self.work, "viejo"), "whatsapp", "0.9.0")
		quiet(publicar.publish, web, publicar.Release("9.8.0", makeArtifacts(os.path.join(self.work, "a"), "9.8.0"), [old, self.elo], storeProprietary=True, date="2026-10-01"))
		self.assertTrue(os.path.isdir(os.path.join(web, "complementos", "eloquence")))
		quiet(publicar.publishGithub, self.release(), REPO, serverDest=web)
		names = os.listdir(os.path.join(self.ghroot, "complementos"))
		self.assertIn("whatsapp-0.9.0.tiresias-addon", names)
		self.assertFalse([n for n in names if n.lower().startswith(("eloquence", "neuralvoices-voz"))])
		wa = next(a for a in self.readAsset("distribucion", "catalogo.json")["addons"] if a["id"] == "whatsapp")
		self.assertEqual([v["version"] for v in wa["versions"]], ["1.0.0", "0.9.0"])

	def test_simular_no_llama_a_gh(self):
		with mock.patch.object(publicar.subprocess, "run", side_effect=_noGh):
			gh = quiet(publicar.publishGithub, self.release(), REPO, simulate=True)
		self.assertTrue(gh.actions)
		self.assertTrue(all(a.startswith("[simulación]") for a in gh.actions))
		text = "\n".join(gh.actions)
		self.assertIn("gh release create v9.9.0", text)
		self.assertIn("Tiresias-9.9.0-instalador.exe", text)
		self.assertIn("gh release create complementos", text)
		self.assertIn("gh release create distribucion", text)
		self.assertNotIn("eloquence", text.lower())
		self.assertNotIn("alvaro", text.lower())
		self.assertEqual(os.listdir(self.ghroot), [])
		self.assertEqual(gh.lastManifest["version"], "9.9.0")

	def test_gh_ausente_o_sin_sesion(self):
		with mock.patch.object(publicar.subprocess, "run", side_effect=FileNotFoundError("gh")):
			with self.assertRaises(SystemExit) as cm:
				quiet(publicar.publishGithub, self.release(), REPO)
		self.assertIn("No se encuentra la herramienta gh", str(cm.exception))
		self.fake.authOk = False
		with self.assertRaises(SystemExit) as cm:
			quiet(publicar.publishGithub, self.release(), REPO)
		self.assertIn("gh auth login", str(cm.exception))
		self.fake.authOk, self.fake.repoOk = True, False
		with self.assertRaises(SystemExit) as cm:
			quiet(publicar.publishGithub, self.release(), REPO)
		self.assertIn(f"No se encuentra el repositorio {REPO}", str(cm.exception))
		self.assertEqual(os.listdir(self.ghroot), [])

	def test_variante_propietaria_nunca_va_a_github(self):
		with self.assertRaises(SystemExit) as cm:
			quiet(publicar.publishGithub, self.release(includeProprietary=True), REPO)
		self.assertIn("no se publica nunca en GitHub", str(cm.exception))
		rel = self.release()
		rel.files = makeArtifacts(os.path.join(self.work, "malo"), "9.9.0", proprietary=True)
		with self.assertRaises(SystemExit):
			quiet(publicar.publishGithub, rel, REPO)
		self.assertFalse(os.path.isdir(os.path.join(self.ghroot, "distribucion")))

	def test_destinos_segun_opciones_y_configuracion(self):
		def args(**kw):
			base = {"solo_servidor": False, "sin_github": False, "solo_github": False, "repositorio": ""}
			base.update(kw)
			return mock.Mock(**base)

		on = {"github": {"repo": "otro/Repo", "publicar": True}}
		self.assertEqual(publicar.publicationTargets(args(), {}), (True, False, REPO))
		self.assertEqual(publicar.publicationTargets(args(), on), (True, True, "otro/Repo"))
		self.assertEqual(publicar.publicationTargets(args(solo_servidor=True), on), (True, False, "otro/Repo"))
		self.assertEqual(publicar.publicationTargets(args(sin_github=True), on), (True, False, "otro/Repo"))
		self.assertEqual(publicar.publicationTargets(args(solo_github=True), {}), (False, True, REPO))
		self.assertEqual(publicar.publicationTargets(args(solo_github=True, repositorio="a/b"), on), (False, True, "a/b"))
		with self.assertRaises(SystemExit):
			publicar.publicationTargets(args(solo_github=True, repositorio="malo"), {})
		# La configuración del repositorio: publica en el servidor y en GitHub (hxebolax/Tiresias).
		cfg = publicar.loadConfig(publicar.CONFIG_FILE)
		self.assertEqual(cfg.get("github"), {"repo": REPO, "publicar": True})
		self.assertIs(cfg.get("incluirPropietario"), False)

	def test_main_falla_antes_de_compilar_sin_gh(self):
		cfg = os.path.join(self.tmp, "publicar.json")
		with open(cfg, "w", encoding="utf-8") as f:
			json.dump({"github": {"repo": REPO, "publicar": True}}, f)
		with (
			mock.patch.object(publicar.subprocess, "run", side_effect=FileNotFoundError("gh")),
			mock.patch.object(publicar, "buildAddonPackages") as build,
			mock.patch.object(publicar, "stageProgram") as stage,
		):
			with self.assertRaises(SystemExit) as cm:
				quiet(publicar.main, ["--config", cfg, "--destino", os.path.join(self.tmp, "web")])
			self.assertIn("gh", str(cm.exception))
			with self.assertRaises(SystemExit):
				quiet(publicar.main, ["--config", cfg, "--solo-github", "--destino", os.path.join(self.tmp, "web")])
		build.assert_not_called()
		stage.assert_not_called()
		# Opciones incompatibles.
		with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
			quiet(publicar.main, ["--solo-github", "--solo-servidor"])

	def test_notas_en_markdown(self):
		self.assertEqual(publicar.newsMarkdown(self.news, "1.2.3"), "")
		self.assertEqual(publicar.newsMarkdown(os.path.join(self.tmp, "no.html"), "9.9.0"), "")
		md = publicar.newsMarkdown(self.news, "9.9.0")
		self.assertTrue(md.startswith("Versión de **prueba**"))
		self.assertIn("\n\n### Voz\n\n- Primera novedad.\n- Segunda & última.", md)
		# Las novedades reales de la versión actual se convierten (si ya están escritas).
		real = publicar.newsMarkdown(os.path.join(ROOT, "docs", "novedades.html"), "1.0.12")
		self.assertIn("- ", real)
		self.assertNotIn("<", real.replace("&lt;", ""))


# ====================================================================== cliente con dos orígenes
class ClienteOrigenesTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.tmp = tempfile.mkdtemp(prefix="tiresias_origenes_")
		cls.web = os.path.join(cls.tmp, "web")
		cls.ghroot = os.path.join(cls.tmp, "github")
		os.makedirs(cls.ghroot)
		work = os.path.join(cls.tmp, "work")
		news = os.path.join(work, "novedades.html")
		os.makedirs(work)
		with open(news, "w", encoding="utf-8") as f:
			f.write(NEWS)
		pk = os.path.join(work, "pk")
		cls.wa = makeAddon(pk, "whatsapp", "1.0.0")
		cls.elo = makeAddon(pk, "eloquence", "1.0.0", files={"synthDrivers/eci/ECI.DLL": b"x"})
		cls.alvaro = makeAddon(pk, "NeuralVoices-voz-Alvaro", "1.0.0", extra={"proprietary": True})
		cls.neural = makeAddon(pk, "NeuralVoices", "1.0.0")
		files = makeArtifacts(os.path.join(work, "a"), "9.9.0")
		packages = [cls.wa, cls.elo, cls.alvaro, cls.neural]
		cls.assets = FakeHost(cls.ghroot)
		# GitHub redirige a otro host (aquí «localhost» en lugar de la dirección numérica).
		cls.github = FakeHost(redirectTo=cls.assets.hostUrl)
		cls.server = FakeHost(cls.web)
		rel = publicar.Release("9.9.0", files, packages, notes="Muchas novedades", newsHtml=news, storeProprietary=True, date="2026-10-13")
		with redirect_stdout(io.StringIO()), mock.patch.object(updates, "GITHUB_URL", cls.github.url), mock.patch.object(publicar.subprocess, "run", side_effect=FakeGh(cls.ghroot)):
			publicar.publish(cls.web, rel)
			publicar.publishGithub(rel, REPO, serverDest=cls.web)
		cls.server.warmUp("/actualizacion.json")
		cls.assets.warmUp("/distribucion/actualizacion.json")
		cls.github.warmUp(f"/{REPO}/releases/download/distribucion/actualizacion.json")

	@classmethod
	def tearDownClass(cls):
		for s in (cls.server, cls.github, cls.assets):
			s.close()
		shutil.rmtree(cls.tmp, ignore_errors=True)

	def setUp(self):
		self.saved = {k: conf["update"][k] for k in ("origin", "serverUrl", "checkUrl", "channel", "lastCheck")}
		self.savedCat = conf["addons"]["catalogUrl"]
		conf["update"]["origin"] = "ambos"
		conf["update"]["serverUrl"] = ""
		conf["update"]["checkUrl"] = ""
		conf["update"]["channel"] = "estable"
		conf["addons"]["catalogUrl"] = ""
		self.patches = [
			mock.patch.object(updates, "DISTRIBUTION_URL", self.server.url),
			mock.patch.object(updates, "GITHUB_URL", self.github.url),
			mock.patch.object(updates, "ORIGIN_TIMEOUT", 1),
			mock.patch.object(updates, "copyKind", return_value="instalada"),
		]
		for p in self.patches:
			p.start()
		self.dl = tempfile.mkdtemp(prefix="tiresias_origenes_dl_")
		self.cache = mock.patch.object(paths, "cacheDir", return_value=self.dl)
		self.cache.start()
		for s in (self.server, self.github, self.assets):
			s.overrides.clear()
			s.hits.clear()

	def tearDown(self):
		self.cache.stop()
		for p in self.patches:
			p.stop()
		for k, v in self.saved.items():
			conf["update"][k] = v
		conf["addons"]["catalogUrl"] = self.savedCat
		shutil.rmtree(self.dl, ignore_errors=True)

	def ghJson(self, name):
		with open(os.path.join(self.ghroot, "distribucion", name), encoding="utf-8") as f:
			return json.load(f)

	def override(self, host, path, obj, status=200):
		host.overrides[path] = (status, json.dumps(obj).encode("utf-8") if not isinstance(obj, bytes) else obj)

	# --------------------------------------------------------------- actualizaciones
	def test_misma_version_prefiere_el_servidor_con_replica_en_github(self):
		info = updates.checkForUpdate()
		self.assertEqual((info.version, info.origin), ("9.9.0", "servidor"))
		self.assertEqual(info.url, self.server.url + "/descargas/9.9.0/Tiresias-9.9.0-instalador.exe")
		self.assertEqual(info.notesUrl, self.server.url + "/novedades.html")
		self.assertEqual(len(info.mirrors), 1)
		mirror = info.mirrors[0]
		self.assertEqual(mirror.origin, "github")
		self.assertEqual(mirror.url, f"{self.github.url}/{REPO}/releases/download/v9.9.0/Tiresias-9.9.0-instalador.exe")
		self.assertEqual(mirror.notesUrl, f"{self.github.url}/{REPO}/releases/tag/v9.9.0")
		self.assertEqual(mirror.sha256, info.sha256)
		# Se consultaron los dos orígenes (GitHub, a través de la redirección).
		self.assertIn("/actualizacion.json", self.server.hits)
		self.assertIn("/distribucion/actualizacion.json", self.assets.hits)

	def test_version_mas_alta_en_github_y_descarga_con_redireccion(self):
		man = self.ghJson("actualizacion.json")
		man["version"] = "9.9.1"
		self.override(self.assets, "/distribucion/actualizacion.json", man)
		info = updates.checkForUpdate()
		self.assertEqual((info.version, info.origin, info.mirrors), ("9.9.1", "github", []))
		path = updates.downloadUpdate(info)
		self.assertEqual(updates.fileSha256(path), info.sha256)
		self.assertIn("/v9.9.0/Tiresias-9.9.0-instalador.exe", self.assets.hits)
		self.assertEqual(self.server.hits, ["/actualizacion.json"])

	def test_version_mas_alta_en_el_servidor(self):
		with open(os.path.join(self.web, "actualizacion.json"), encoding="utf-8") as f:
			man = json.load(f)
		man["version"] = "9.9.2"
		self.override(self.server, "/actualizacion.json", man)
		info = updates.checkForUpdate()
		self.assertEqual((info.version, info.origin, info.mirrors), ("9.9.2", "servidor", []))

	def test_un_origen_caido_usa_el_otro_sin_error(self):
		self.override(self.server, "/actualizacion.json", b"error", status=500)
		info = updates.checkForUpdate()
		self.assertEqual((info.version, info.origin), ("9.9.0", "github"))
		# Y al revés.
		self.server.overrides.clear()
		self.override(self.assets, "/distribucion/actualizacion.json", b"{roto", status=200)
		self.assertEqual(updates.checkForUpdate().origin, "servidor")

	def test_origen_que_no_responde(self):
		self.server.overrides["/actualizacion.json"] = ("colgado", b"")
		start = time.monotonic()
		# Sin reintentos: ningún intento rezagado llega a las pruebas siguientes.
		with mock.patch.object(updates, "RETRIES", 1):
			info = updates.checkForUpdate()
		self.assertEqual(info.origin, "github")
		self.assertLess(time.monotonic() - start, 5.5)

	def test_los_dos_caidos(self):
		self.override(self.server, "/actualizacion.json", b"error", status=500)
		self.override(self.assets, "/distribucion/actualizacion.json", b"error", status=503)
		with self.assertRaises(ConnectionError) as cm:
			updates.checkForUpdate()
		msg = str(cm.exception)
		self.assertIn("el servidor del proyecto", msg)
		self.assertIn("GitHub", msg)

	def test_sin_version_nueva(self):
		for host, path, name in ((self.server, "/actualizacion.json", None), (self.assets, "/distribucion/actualizacion.json", "actualizacion.json")):
			if name:
				man = self.ghJson(name)
			else:
				with open(os.path.join(self.web, "actualizacion.json"), encoding="utf-8") as f:
					man = json.load(f)
			man["version"] = "0.0.1"
			self.override(host, path, man)
		self.assertIsNone(updates.checkForUpdate())
		# Uno sin versión nueva y el otro caído: tampoco es un error.
		self.override(self.server, "/actualizacion.json", b"error", status=500)
		self.assertIsNone(updates.checkForUpdate())

	def test_descarga_falla_y_se_reintenta_en_github(self):
		info = updates.checkForUpdate()
		self.override(self.server, "/descargas/9.9.0/Tiresias-9.9.0-instalador.exe", b"no", status=404)
		path = updates.downloadUpdate(info)
		self.assertEqual(updates.fileSha256(path), info.sha256)
		self.assertIn("/v9.9.0/Tiresias-9.9.0-instalador.exe", self.assets.hits)

	def test_paquete_danado_en_el_servidor_se_descarga_de_github(self):
		info = updates.checkForUpdate()
		self.override(self.server, "/descargas/9.9.0/Tiresias-9.9.0-instalador.exe", b"x" * info.size)
		path = updates.downloadUpdate(info)
		self.assertEqual(updates.fileSha256(path), info.sha256)

	def test_nunca_sin_sha256_valido(self):
		man = self.ghJson("actualizacion.json")
		man["version"] = "9.9.1"
		man["sha256"] = ""
		man["installer"]["sha256"] = ""
		self.override(self.assets, "/distribucion/actualizacion.json", man)
		info = updates.checkForUpdate()
		self.assertEqual(info.origin, "github")
		with self.assertRaises(ValueError) as cm:
			updates.downloadUpdate(info)
		self.assertIn("SHA-256", str(cm.exception))
		# Las dos copias dañadas: se rechaza (con el error del origen preferido).
		self.assets.overrides.clear()
		info = updates.checkForUpdate()
		self.override(self.server, "/descargas/9.9.0/Tiresias-9.9.0-instalador.exe", b"x" * info.size)
		self.override(self.assets, "/v9.9.0/Tiresias-9.9.0-instalador.exe", b"y" * info.size)
		with self.assertRaises(ValueError):
			updates.downloadUpdate(info)
		self.assertEqual(os.listdir(os.path.join(self.dl, "actualizaciones")), [])

	def test_cancelar_no_reintenta(self):
		info = updates.checkForUpdate()
		with self.assertRaises(InterruptedError):
			updates.downloadUpdate(info, lambda done, total: False)
		self.assertNotIn("/v9.9.0/Tiresias-9.9.0-instalador.exe", self.assets.hits)

	def test_solo_un_origen(self):
		conf["update"]["origin"] = "github"
		info = updates.checkForUpdate()
		self.assertEqual((info.origin, info.mirrors), ("github", []))
		self.assertEqual(self.server.hits, [])
		conf["update"]["origin"] = "servidor"
		self.server.hits.clear()
		self.assets.hits.clear()
		self.assertEqual(updates.checkForUpdate().origin, "servidor")
		self.assertEqual(self.assets.hits, [])
		# Con un solo origen, su error llega tal cual (como antes).
		self.override(self.server, "/actualizacion.json", b"error", status=500)
		with self.assertRaises(urllib.error.HTTPError):
			updates.checkForUpdate()

	# --------------------------------------------------------------- tienda
	def test_tienda_combina_los_dos_catalogos(self):
		entries, src = addon_store.fetchCatalog()
		self.assertIn(self.server.url, src)
		self.assertIn(self.github.url, src)
		by = {e.id: e for e in entries}
		# Los propietarios solo están en el servidor, pero siguen apareciendo.
		self.assertEqual(set(by), {"whatsapp", "NeuralVoices", "eloquence", "NeuralVoices-voz-Alvaro"})
		self.assertEqual(by["eloquence"].origin, "servidor")
		self.assertEqual(by["eloquence"].mirrors, [])
		self.assertTrue(by["eloquence"].extra.get("proprietary"))
		wa = by["whatsapp"]
		self.assertEqual(wa.origin, "servidor")
		self.assertEqual(wa.url, self.server.url + "/complementos/whatsapp/whatsapp-1.0.0.tiresias-addon")
		self.assertEqual([m["origin"] for m in wa.mirrors], ["github"])
		self.assertEqual(wa.mirrors[0]["url"], f"{self.github.url}/{REPO}/releases/download/complementos/whatsapp-1.0.0.tiresias-addon")

	def test_tienda_version_mas_alta_en_github(self):
		pkg = makeAddon(os.path.join(self.tmp, "nuevo"), "whatsapp", "1.1.0")
		name = "whatsapp-1.1.0.tiresias-addon"
		shutil.copyfile(pkg, os.path.join(self.ghroot, "complementos", name))
		try:
			cat = copy.deepcopy(self.ghJson("catalogo.json"))
			wa = next(a for a in cat["addons"] if a["id"] == "whatsapp")
			new = {"version": "1.1.0", "url": f"{self.github.url}/{REPO}/releases/download/complementos/{name}", "sha256": updates.fileSha256(pkg), "size": os.path.getsize(pkg), "minApiVersion": "1.0", "lastTestedApiVersion": "1.0"}
			wa.update(new)
			wa["versions"] = [new] + wa["versions"]
			self.override(self.assets, "/distribucion/catalogo.json", cat)
			entries, _src = addon_store.fetchCatalog()
			e = next(x for x in entries if x.id == "whatsapp")
			self.assertEqual((e.version, e.origin, e.mirrors), ("1.1.0", "github", []))
			path = addon_store.downloadPackage(e)
			with zipfile.ZipFile(path) as z:
				self.assertEqual(json.loads(z.read("manifest.json"))["version"], "1.1.0")
		finally:
			os.remove(os.path.join(self.ghroot, "complementos", name))

	def test_tienda_descarga_falla_y_usa_el_mismo_paquete_de_github(self):
		entries, _src = addon_store.fetchCatalog()
		wa = next(x for x in entries if x.id == "whatsapp")
		self.override(self.server, "/complementos/whatsapp/whatsapp-1.0.0.tiresias-addon", b"no", status=404)
		path = addon_store.downloadPackage(wa)
		self.assertEqual(updates.fileSha256(path), wa.sha256)
		self.assertIn("/complementos/whatsapp-1.0.0.tiresias-addon", self.assets.hits)
		# Una réplica con otro SHA-256 no es el mismo paquete: no se usa.
		wa.mirrors = [dict(wa.mirrors[0], sha256="0" * 64)]
		self.assets.hits.clear()
		with self.assertRaises(urllib.error.HTTPError):
			addon_store.downloadPackage(wa)
		self.assertEqual(self.assets.hits, [])

	def test_tienda_con_un_origen_caido(self):
		self.override(self.assets, "/distribucion/catalogo.json", b"error", status=500)
		entries, src = addon_store.fetchCatalog()
		self.assertEqual(src, self.server.url + "/complementos/catalogo.json")
		self.assertIn("eloquence", {e.id for e in entries})
		self.assets.overrides.clear()
		self.override(self.server, "/complementos/catalogo.json", b"error", status=500)
		entries, src = addon_store.fetchCatalog()
		self.assertEqual({e.id for e in entries}, {"whatsapp", "NeuralVoices"})
		self.assertTrue(all(e.origin == "github" for e in entries))

	def test_tienda_solo_github_sin_propietarios(self):
		conf["update"]["origin"] = "github"
		entries, src = addon_store.fetchCatalog()
		self.assertEqual(src, f"{self.github.url}/{REPO}/releases/download/distribucion/catalogo.json")
		self.assertEqual({e.id for e in entries}, {"whatsapp", "NeuralVoices"})
		self.assertEqual(self.server.hits, [])

	def test_copia_local_vista_desde_github(self):
		local = os.path.join(self.dl, "catalogo_complementos.json")
		shutil.copyfile(os.path.join(self.web, "complementos", "catalogo.json"), local)
		conf["update"]["origin"] = "github"
		self.override(self.assets, "/distribucion/catalogo.json", b"error", status=500)
		with mock.patch.object(addon_store, "localCatalogPath", return_value=local):
			entries, src = addon_store.fetchCatalog()
		self.assertEqual(src, local)
		self.assertEqual({e.id for e in entries}, {"whatsapp", "NeuralVoices"})
		wa = next(e for e in entries if e.id == "whatsapp")
		self.assertEqual(wa.url, f"{self.github.url}/{REPO}/releases/download/complementos/whatsapp-1.0.0.tiresias-addon")


# ====================================================================== opción, compatibilidad y política
class OrigenOpcionTests(unittest.TestCase):
	def setUp(self):
		self.saved = {k: conf["update"][k] for k in ("origin", "serverUrl", "checkUrl")}
		self.savedCat = conf["addons"]["catalogUrl"]
		conf["update"]["origin"] = "ambos"
		conf["update"]["serverUrl"] = ""
		conf["update"]["checkUrl"] = ""
		conf["addons"]["catalogUrl"] = ""
		self.p = mock.patch.object(updates, "DISTRIBUTION_URL", "https://xebolax.synology.me/Tiresias")
		self.p.start()

	def tearDown(self):
		self.p.stop()
		for k, v in self.saved.items():
			conf["update"][k] = v
		conf["addons"]["catalogUrl"] = self.savedCat

	def kinds(self):
		return [o.kind for o in updates.distributionOrigins()]

	def test_valores_de_la_opcion(self):
		self.assertEqual(conf.defaults["update"]["origin"], "ambos")
		self.assertEqual(validation.CHOICES[("update", "origin")], updates.ORIGINS)
		self.assertEqual(self.kinds(), ["servidor", "github"])
		self.assertEqual(updates.updateUrl(), "https://xebolax.synology.me/Tiresias/actualizacion.json")
		self.assertEqual(addon_store.catalogUrl(), "https://xebolax.synology.me/Tiresias/complementos/catalogo.json")
		self.assertEqual(
			[o.manifestUrl for o in updates.updateOrigins()][1], "https://github.com/hxebolax/Tiresias/releases/download/distribucion/actualizacion.json"
		)
		self.assertEqual([o.catalogUrl for o in updates.catalogOrigins()][1], "https://github.com/hxebolax/Tiresias/releases/download/distribucion/catalogo.json")
		conf["update"]["origin"] = "servidor"
		self.assertEqual(self.kinds(), ["servidor"])
		conf["update"]["origin"] = "github"
		self.assertEqual(self.kinds(), ["github"])
		self.assertEqual(updates.updateUrl(), "https://github.com/hxebolax/Tiresias/releases/download/distribucion/actualizacion.json")
		self.assertEqual(updates.projectPageUrl(), "https://github.com/hxebolax/Tiresias")
		# «Servidor propio» sin dirección: el del proyecto (como la dirección vacía de antes).
		conf["update"]["origin"] = "propio"
		self.assertEqual(self.kinds(), ["servidor"])
		conf["update"]["serverUrl"] = "https://empresa.local/tiresias/"
		self.assertEqual(self.kinds(), ["propio"])
		self.assertEqual(updates.updateUrl(), "https://empresa.local/tiresias/actualizacion.json")
		# Un valor desconocido vale lo de por defecto.
		conf["update"]["origin"] = "otro"
		conf["update"]["serverUrl"] = ""
		self.assertEqual(updates.originSetting(), "ambos")
		self.assertTrue(updates.describeOrigins().startswith("Se consultan el servidor del proyecto"))

	def test_compatibilidad_con_configuracion_antigua(self):
		# Antes de la 1.0.13, escribir un servidor era usar solo ese servidor.
		conf["update"]["serverUrl"] = "https://empresa.local/tiresias"
		self.assertEqual(updates.currentOrigin(), "propio")
		self.assertEqual(self.kinds(), ["propio"])
		self.assertEqual(updates.distributionUrl(), "https://empresa.local/tiresias")
		# Con «Solo GitHub» o «Solo el servidor del proyecto» elegidos, la dirección no cuenta.
		conf["update"]["origin"] = "github"
		self.assertEqual(self.kinds(), ["github"])
		conf["update"]["origin"] = "servidor"
		self.assertEqual(updates.distributionUrl(), "https://xebolax.synology.me/Tiresias")
		# El archivo de configuración antiguo pasa a «Servidor propio» al cargarlo.
		data = {"update": {"serverUrl": "https://empresa.local/tiresias"}}
		migrations.migrate(data)
		self.assertEqual(data["update"]["origin"], "propio")
		data = {"update": {"serverUrl": "x", "origin": "github"}}
		migrations.migrate(data)
		self.assertEqual(data["update"]["origin"], "github")
		data = {"update": {"serverUrl": ""}, "speech": {"rate": 50}}
		migrations.migrate(data)
		self.assertNotIn("origin", data["update"])
		# Las direcciones concretas de antes siguen mandando para su archivo.
		conf["update"]["serverUrl"] = ""
		conf["update"]["origin"] = "ambos"
		conf["update"]["checkUrl"] = "https://otra/act.json"
		conf["addons"]["catalogUrl"] = "https://otra/cat.json"
		self.assertEqual([(o.kind, o.manifestUrl) for o in updates.updateOrigins()], [("propio", "https://otra/act.json")])
		self.assertEqual([(o.kind, o.catalogUrl) for o in updates.catalogOrigins()], [("propio", "https://otra/cat.json")])

	def test_politica_de_empresa(self):
		with mock.patch.object(policyModule.policy, "data", {"distributionUrl": "https://intranet/tiresias"}):
			conf["update"]["origin"] = "github"
			self.assertEqual(updates.currentOrigin(), "propio")
			self.assertEqual([(o.kind, o.base) for o in updates.distributionOrigins()], [("propio", "https://intranet/tiresias")])
			self.assertEqual(addon_store.catalogUrl(), "https://intranet/tiresias/complementos/catalogo.json")
		with mock.patch.object(policyModule.policy, "data", {"updateUrl": "https://intranet/act.json"}):
			conf["update"]["origin"] = "ambos"
			self.assertEqual([o.manifestUrl for o in updates.updateOrigins()], ["https://intranet/act.json"])
			# La tienda sigue usando los dos orígenes.
			self.assertEqual([o.kind for o in updates.catalogOrigins()], ["servidor", "github"])
		with mock.patch.object(policyModule.policy, "data", {"addonCatalogUrl": "https://intranet/cat.json"}):
			self.assertEqual([o.catalogUrl for o in updates.catalogOrigins()], ["https://intranet/cat.json"])

	def test_compilacion_sin_distribucion_oficial(self):
		with mock.patch.object(updates, "DISTRIBUTION_URL", ""):
			self.assertEqual(updates.distributionOrigins(), [])
			self.assertFalse(updates.hasOfficialRepository())
			self.assertEqual(updates.updateUrl(), "")
			self.assertEqual(addon_store.catalogUrl(), "")

	def test_direcciones_de_github(self):
		man = "https://github.com/hxebolax/Tiresias/releases/download/distribucion/actualizacion.json"
		asset = "https://github.com/hxebolax/Tiresias/releases/download/v1.0.13/Tiresias-1.0.13-instalador.exe"
		self.assertEqual(updates.githubAssetUrl("v1.0.13", "Tiresias-1.0.13-instalador.exe"), asset)
		self.assertEqual(updates.resolveUrl(man, asset), asset)
		self.assertEqual(updates.resolveUrl(man, "catalogo.json"), "https://github.com/hxebolax/Tiresias/releases/download/distribucion/catalogo.json")
		for bad in ("http://github.com/x.exe", r"\\servidor\x.exe", "file:///C:/x.exe"):
			with self.assertRaises(updates.UnsafeUrlError):
				updates.resolveUrl(man, bad)

	def test_redireccion_de_https_a_http_se_rechaza(self):
		class Resp:
			closed = False

			def __init__(self, final):
				self.final = final

			def geturl(self):
				return self.final

			def close(self):
				self.closed = True

		bad = Resp("http://objects.githubusercontent.com/x")
		with mock.patch.object(updates.urllib.request, "urlopen", return_value=bad):
			with self.assertRaises(updates.UnsafeUrlError):
				updates.openUrl("https://github.com/hxebolax/Tiresias/releases/download/v1/x.exe")
		self.assertTrue(bad.closed)
		good = Resp("https://release-assets.githubusercontent.com/x?firma=1")
		with mock.patch.object(updates.urllib.request, "urlopen", return_value=good):
			self.assertIs(updates.openUrl("https://github.com/hxebolax/Tiresias/releases/download/v1/x.exe"), good)

	def test_fusion_de_catalogos(self):
		O = updates.Origin
		E = addon_store.CatalogEntry
		srv = [E("a", "A", "1.0", url="https://s/a", sha256="aa"), E("b", "B", "2.0", url="https://s/b", sha256="bb"), E("p", "P", "1.0", url="https://s/p", sha256="pp")]
		gh = [E("a", "A", "1.0", url="https://g/a", sha256="AA"), E("b", "B", "2.1", url="https://g/b", sha256="b2"), E("c", "C", "1.0", url="https://g/c", sha256="cc")]
		merged = addon_store.mergeCatalogs([(O("servidor"), srv), (O("github"), gh)])
		by = {e.id: e for e in merged}
		self.assertEqual([e.id for e in merged], ["a", "b", "p", "c"])
		self.assertEqual((by["a"].origin, by["a"].url, [m["url"] for m in by["a"].mirrors]), ("servidor", "https://s/a", ["https://g/a"]))
		self.assertEqual((by["b"].origin, by["b"].version, by["b"].mirrors), ("github", "2.1", []))
		self.assertEqual(by["p"].origin, "servidor")
		self.assertEqual(by["c"].origin, "github")
		# Misma versión con otro paquete: sin réplica.
		merged = addon_store.mergeCatalogs([(O("servidor"), [E("x", "X", "1.0", url="https://s/x", sha256="11")]), (O("github"), [E("x", "X", "1.0", url="https://g/x", sha256="22")])])
		self.assertEqual(merged[0].mirrors, [])


# ====================================================================== panel de Opciones
class PanelOrigenTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		try:
			import wx
		except ImportError:
			raise unittest.SkipTest("sin wxPython")
		cls.app = wx.App.Get() or wx.App(False)

	def setUp(self):
		self.saved = {k: conf["update"][k] for k in ("origin", "serverUrl")}

	def tearDown(self):
		for k, v in self.saved.items():
			conf["update"][k] = v

	def panel(self):
		from tiresias.gui import config_panels  # noqa: F401 - registra la categoría
		from tiresias.gui import settings as S

		dlg = S.SettingsDialog(None, "updates")
		self.addCleanup(dlg.Destroy)
		return dlg.getPanel("updates")

	def test_origen_y_servidor_propio(self):
		from tiresias.gui import settings as S

		conf["update"]["origin"] = "ambos"
		conf["update"]["serverUrl"] = ""
		panel = self.panel()
		self.assertEqual(panel.getValue("origin"), "ambos")
		self.assertFalse(panel.getControl("serverUrl").IsEnabled())
		panel.setControlValue("origin", "propio")
		panel._syncOrigin()
		self.assertTrue(panel.getControl("serverUrl").IsEnabled())
		with mock.patch.object(S, "showError") as err:
			# «Servidor propio» sin dirección no se acepta.
			self.assertFalse(panel.isValid())
			self.assertTrue(err.called)
			panel.setControlValue("serverUrl", "https://empresa.local/tiresias")
			self.assertTrue(panel.isValid())
		panel.onSave()
		self.assertEqual((conf["update"]["origin"], conf["update"]["serverUrl"]), ("propio", "https://empresa.local/tiresias"))
		# Al elegir otro origen, la dirección se borra para que no siga contando como servidor propio.
		panel.setControlValue("origin", "ambos")
		panel._syncOrigin()
		panel.onSave()
		self.assertEqual((conf["update"]["origin"], conf["update"]["serverUrl"]), ("ambos", ""))
		self.assertEqual(updates.currentOrigin(), "ambos")

	def test_politica_desactiva_el_origen(self):
		with mock.patch.object(policyModule.policy, "data", {"distributionUrl": "https://empresa/tiresias"}):
			panel = self.panel()
			self.assertFalse(panel.getControl("origin").IsEnabled())
			self.assertFalse(panel.getControl("serverUrl", "update").IsEnabled())


if __name__ == "__main__":
	unittest.main()
