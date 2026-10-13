"""Pruebas de tools/publicar.py: estructura publicada, idempotencia, canales,
complementos propietarios y direcciones relativas."""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import publicar  # noqa: E402
from tiresias import updates  # noqa: E402


def makeAddon(folder: str, addonId: str, version: str, extra: dict | None = None, files: dict | None = None) -> str:
	"""Crea un paquete .tiresias-addon de prueba y devuelve su ruta."""
	os.makedirs(folder, exist_ok=True)
	path = os.path.join(folder, f"{addonId}-{version}.tiresias-addon")
	manifest = {"id": addonId, "name": addonId.capitalize(), "version": version, "description": f"Complemento {addonId}", "minApiVersion": "1.0", "lastTestedApiVersion": "1.0"}
	manifest.update(extra or {})
	with zipfile.ZipFile(path, "w") as z:
		z.writestr("manifest.json", json.dumps(manifest))
		for name, data in (files or {"__init__.py": "# vacío\n"}).items():
			z.writestr(name, data)
	return path


def makeArtifacts(folder: str, version: str, proprietary: bool = False) -> dict:
	os.makedirs(folder, exist_ok=True)
	inst = os.path.join(folder, "inst.exe")
	with open(inst, "wb") as f:
		f.write(b"MZ instalador " + version.encode() * 50)
	port = os.path.join(folder, "port.zip")
	with zipfile.ZipFile(port, "w") as z:
		z.writestr("Tiresias/Tiresias.exe", b"MZ" + version.encode())
		if proprietary:
			z.writestr("Tiresias/data/addons/eloquence/synthDrivers/eci/ECI.DLL", b"x")
	src = os.path.join(folder, "src.zip")
	with zipfile.ZipFile(src, "w") as z:
		z.writestr(f"Tiresias-{version}-codigo-fuente/README.md", "Tiresias " + version)
	return {"installer": inst, "portable": port, "source": src}


def quiet(func, *args, **kwargs):
	with redirect_stdout(io.StringIO()):
		return func(*args, **kwargs)


class PublicarTests(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.mkdtemp(prefix="tiresias_pub_")
		self.web = os.path.join(self.tmp, "web")
		self.work = os.path.join(self.tmp, "work")

	def tearDown(self):
		shutil.rmtree(self.tmp, ignore_errors=True)

	def release(self, version, channel="estable", proprietary=False, addons=None, **kw):
		files = makeArtifacts(os.path.join(self.work, version), version)
		news = os.path.join(self.work, "novedades.html")
		with open(news, "w", encoding="utf-8") as f:
			f.write("<!DOCTYPE html><title>Novedades</title>")
		return publicar.Release(version, files, addons or [], channel=channel, notes=f"Notas {version}", includeProprietary=proprietary, newsHtml=news, date="2026-10-07", **kw)

	def readJson(self, rel):
		with open(os.path.join(self.web, *rel.split("/")), encoding="utf-8") as f:
			return json.load(f)

	def test_dos_versiones_seguidas(self):
		pk = os.path.join(self.work, "pk")
		quiet(publicar.publish, self.web, self.release("1.0.2", addons=[makeAddon(pk, "whatsapp", "1.0.0")]))
		quiet(publicar.publish, self.web, self.release("1.0.3", addons=[makeAddon(pk, "whatsapp", "1.1.0")]))
		hist = self.readJson("versiones.json")
		self.assertEqual([v["version"] for v in hist["versions"]], ["1.0.3", "1.0.2"])
		man = self.readJson("actualizacion.json")
		self.assertEqual(man["format"], "tiresias-actualizacion")
		self.assertEqual(man["version"], "1.0.3")
		self.assertEqual(man["url"], "descargas/1.0.3/Tiresias-1.0.3-instalador.exe")
		self.assertEqual(man["notes"], "Notas 1.0.3")
		self.assertEqual(man["notesUrl"], "novedades.html")
		self.assertEqual(man["minWindows"], publicar.DEFAULT_MIN_WINDOWS)
		self.assertEqual(man["date"], "2026-10-07")
		self.assertNotIn("channels", man)
		inst = os.path.join(self.web, "descargas", "1.0.3", "Tiresias-1.0.3-instalador.exe")
		self.assertEqual(man["sha256"], updates.fileSha256(inst))
		self.assertEqual(man["size"], os.path.getsize(inst))
		self.assertEqual(man["portable"]["url"], "descargas/1.0.3/Tiresias-1.0.3-portable.zip")
		self.assertEqual(man["source"]["url"], "descargas/1.0.3/Tiresias-1.0.3-codigo-fuente.zip")
		# La versión anterior se conserva.
		self.assertTrue(os.path.isfile(os.path.join(self.web, "descargas", "1.0.2", "Tiresias-1.0.2-portable.zip")))
		with open(inst + ".sha256", encoding="utf-8") as f:
			self.assertEqual(f.read(), f"{man['sha256']} *Tiresias-1.0.3-instalador.exe\n")
		# Catálogo con todas las versiones del complemento, la más reciente arriba.
		cat = self.readJson("complementos/catalogo.json")
		self.assertEqual(cat["format"], "tiresias-catalogo")
		wa = cat["addons"][0]
		self.assertEqual((wa["id"], wa["version"], wa["url"]), ("whatsapp", "1.1.0", "whatsapp/whatsapp-1.1.0.tiresias-addon"))
		self.assertEqual([v["version"] for v in wa["versions"]], ["1.1.0", "1.0.0"])
		self.assertTrue(os.path.isfile(os.path.join(self.web, "complementos", "whatsapp", "whatsapp-1.0.0.tiresias-addon.sha256")))
		for page in ("index.html", "novedades.html", ".htaccess"):
			self.assertTrue(os.path.isfile(os.path.join(self.web, page)), page)

	def test_idempotente(self):
		pk = os.path.join(self.work, "pk")
		rel = self.release("1.0.2", addons=[makeAddon(pk, "whatsapp", "1.0.0")])
		quiet(publicar.publish, self.web, rel)
		w = quiet(publicar.publish, self.web, rel)
		self.assertEqual(w.actions, [], "la segunda publicación igual no debe cambiar nada")
		self.assertEqual(len(self.readJson("versiones.json")["versions"]), 1)
		self.assertEqual(len(self.readJson("complementos/catalogo.json")["addons"][0]["versions"]), 1)

	def test_sin_instalador_conserva_el_publicado(self):
		quiet(publicar.publish, self.web, self.release("1.0.2"))
		before = self.readJson("actualizacion.json")
		rel = self.release("1.0.2")
		del rel.files["installer"]
		quiet(publicar.publish, self.web, rel)
		after = self.readJson("actualizacion.json")
		self.assertEqual(after["installer"], before["installer"])
		self.assertEqual(after["url"], "descargas/1.0.2/Tiresias-1.0.2-instalador.exe")

	def test_simular_no_escribe(self):
		w = quiet(publicar.publish, self.web, self.release("1.0.2", addons=[makeAddon(os.path.join(self.work, "pk"), "whatsapp", "1.0.0")]), simulate=True)
		self.assertTrue(w.actions)
		self.assertTrue(all(a.startswith("[simulación]") for a in w.actions))
		self.assertFalse(os.path.exists(self.web))

	def test_propietario(self):
		pk = os.path.join(self.work, "pk")
		elo = makeAddon(pk, "eloquence", "1.0.0", files={"synthDrivers/eci/ECI.DLL": b"x", "synthDrivers/eci/ESP.SYN": b"y"})
		# Un complemento con otro nombre pero con ECI.DLL también es propietario.
		otro = makeAddon(pk, "voz", "1.0.0", files={"eci/eci.dll": b"x"})
		wa = makeAddon(pk, "whatsapp", "1.0.0")
		quiet(publicar.publish, self.web, self.release("1.0.2", addons=[elo, otro, wa]))
		ids = [a["id"] for a in self.readJson("complementos/catalogo.json")["addons"]]
		self.assertEqual(ids, ["whatsapp"])
		self.assertFalse(os.path.exists(os.path.join(self.web, "complementos", "eloquence")))
		self.assertFalse(self.readJson("versiones.json")["versions"][0]["proprietary"])
		# La portada no lista complementos: remite a la tienda (decisión del usuario, 9-10-2026).
		with open(os.path.join(self.web, "index.html"), encoding="utf-8") as f:
			self.assertNotIn("eloquence", f.read().lower())
		# Con --incluir-propietario sí se publica (y queda marcado).
		quiet(publicar.publish, self.web, self.release("1.0.2", proprietary=True, addons=[elo, wa]))
		cat = self.readJson("complementos/catalogo.json")
		self.assertEqual([a["id"] for a in cat["addons"]], ["eloquence", "whatsapp"])
		self.assertTrue(cat["addons"][0]["proprietary"])
		self.assertTrue(self.readJson("versiones.json")["versions"][0]["proprietary"])
		# Una publicación normal posterior lo retira.
		quiet(publicar.publish, self.web, self.release("1.0.3", addons=[wa]))
		self.assertFalse(os.path.exists(os.path.join(self.web, "complementos", "eloquence")))
		self.assertEqual([a["id"] for a in self.readJson("complementos/catalogo.json")["addons"]], ["whatsapp"])

	def test_propietarios_solo_en_la_tienda(self):
		pk = os.path.join(self.work, "pk")
		elo = makeAddon(pk, "eloquence", "1.0.0", files={"synthDrivers/eci/ECI.DLL": b"x"})
		voz = makeAddon(pk, "NeuralVoices-voz-Alvaro", "1.0.0", extra={"proprietary": True})
		wa = makeAddon(pk, "whatsapp", "1.0.0")
		quiet(publicar.publish, self.web, self.release("1.0.9", addons=[elo, voz, wa], storeProprietary=True))
		cat = self.readJson("complementos/catalogo.json")
		self.assertEqual([a["id"] for a in cat["addons"]], ["NeuralVoices-voz-Alvaro", "eloquence", "whatsapp"])
		self.assertEqual([a["proprietary"] for a in cat["addons"]], [True, True, False])
		# El programa publicado no lleva componentes propietarios.
		self.assertFalse(self.readJson("versiones.json")["versions"][0]["proprietary"])
		with open(os.path.join(self.web, "index.html"), encoding="utf-8") as f:
			page = f.read()
		# La portada no lista complementos (tampoco los propietarios): remite a la tienda.
		self.assertIn("Tienda de complementos", page)
		self.assertNotIn("complementos/eloquence/", page)
		self.assertNotIn("ya lo traen incluido", page)
		# Las versiones anteriores con Eloquence no se listan (siguen en el historial).
		quiet(publicar.publish, self.web, self.release("1.0.8", proprietary=True))
		quiet(publicar.publish, self.web, self.release("1.0.9", addons=[elo, voz, wa], storeProprietary=True))
		with open(os.path.join(self.web, "index.html"), encoding="utf-8") as f:
			page = f.read()
		self.assertNotIn("descargas/1.0.8/", page)
		self.assertNotIn('id="anteriores"', page)
		self.assertIn("1.0.8", [v["version"] for v in self.readJson("versiones.json")["versions"]])
		self.assertTrue(os.path.isdir(os.path.join(self.web, "descargas", "1.0.8")))
		# Sin la decisión, la voz con «proprietary» en el manifiesto tampoco se publica.
		quiet(publicar.publish, self.web, self.release("1.0.10", addons=[voz, wa]))
		self.assertEqual([a["id"] for a in self.readJson("complementos/catalogo.json")["addons"]], ["whatsapp"])

	def test_complementos_de_la_tienda(self):
		base = os.path.join(self.tmp, "tienda")
		for addonId, extra in (("radio", {}), ("voz", {"proprietary": True})):
			folder = os.path.join(base, addonId)
			os.makedirs(folder)
			with open(os.path.join(folder, "manifest.json"), "w", encoding="utf-8") as f:
				json.dump({"id": addonId, "version": "1.0.0", **extra}, f)
		out = os.path.join(self.tmp, "paquetes")
		pkgs = quiet(publicar.buildAddonPackages, out, False, bases=[base])
		self.assertEqual([os.path.basename(p) for p in pkgs], ["radio.tiresias-addon"])
		pkgs = quiet(publicar.buildAddonPackages, out, True, bases=[base])
		self.assertEqual(sorted(os.path.basename(p) for p in pkgs), ["radio.tiresias-addon", "voz.tiresias-addon"])
		self.assertEqual(publicar.proprietaryStoreFolders([base], root=self.tmp), ["tienda/voz"])

	def test_descarga_publica_con_eci_se_rechaza(self):
		rel = self.release("1.0.2")
		rel.files = makeArtifacts(os.path.join(self.work, "malo"), "1.0.2", proprietary=True)
		with self.assertRaises(SystemExit):
			quiet(publicar.publish, self.web, rel)

	def test_urls_relativas_y_resolubles(self):
		pk = os.path.join(self.work, "pk")
		quiet(publicar.publish, self.web, self.release("1.0.2", addons=[makeAddon(pk, "whatsapp", "1.0.0")]))
		man = self.readJson("actualizacion.json")
		cat = self.readJson("complementos/catalogo.json")
		urls = [(updates.UPDATE_MANIFEST, man["url"]), (updates.UPDATE_MANIFEST, man["notesUrl"])]
		urls += [(updates.UPDATE_MANIFEST, man[k]["url"]) for k in ("portable", "source")]
		urls += [(updates.CATALOG_FILE, a["url"]) for a in cat["addons"]]
		urls += [(updates.CATALOG_FILE, v["url"]) for a in cat["addons"] for v in a["versions"]]
		for base, url in urls:
			self.assertNotIn("://", url)
			self.assertFalse(os.path.isabs(url))
			local = updates.resolveUrl(os.path.join(self.web, *base.split("/")), url)
			self.assertTrue(os.path.isfile(local), local)
			web = updates.resolveUrl("https://ejemplo.github.io/tiresias/" + base, url)
			self.assertTrue(web.startswith("https://ejemplo.github.io/tiresias/"), web)

	def test_canal_beta(self):
		quiet(publicar.publish, self.web, self.release("1.0.2"))
		quiet(publicar.publish, self.web, self.release("1.1.0b1", channel="beta"))
		man = self.readJson("actualizacion.json")
		self.assertEqual(man["version"], "1.0.2")
		self.assertEqual(man["channels"]["beta"]["version"], "1.1.0b1")
		self.assertEqual(man["channels"]["beta"]["url"], "descargas/1.1.0b1/Tiresias-1.1.0b1-instalador.exe")
		# Al publicar la estable 1.1.0, la beta antigua deja de ofrecerse.
		quiet(publicar.publish, self.web, self.release("1.1.0"))
		man = self.readJson("actualizacion.json")
		self.assertEqual(man["version"], "1.1.0")
		self.assertNotIn("channels", man)
		self.assertEqual([v["version"] for v in self.readJson("versiones.json")["versions"]], ["1.1.0", "1.1.0b1", "1.0.2"])

	def test_portada_accesible(self):
		quiet(publicar.publish, self.web, self.release("1.0.2", addons=[makeAddon(os.path.join(self.work, "pk"), "whatsapp", "1.0.0")]))
		with open(os.path.join(self.web, "index.html"), encoding="utf-8") as f:
			page = f.read()
		self.assertIn('<html lang="es">', page)
		self.assertIn("© XeBoLaX", page)
		self.assertNotIn("<script", page)
		for text in ("<h1>Tiresias</h1>", "Descargar Tiresias 1.0.2", "descargas/1.0.2/Tiresias-1.0.2-instalador.exe", "SHA-256", "Cómo se instalan", "Tienda de complementos", "Instalar desde archivo", 'href="manual/"', 'id="requisitos"', 'href="novedades.html"'):
			self.assertIn(text, page)
		self.assertNotIn("complementos/whatsapp/whatsapp-1.0.0.tiresias-addon", page)

	def test_copia_publica_sin_eloquence(self):
		dist = os.path.join(self.tmp, "dist", "Tiresias")
		for rel, data in {
			"Tiresias.exe": b"MZ",
			"lib/a.pyc": b"x",
			"instalado.json": b"{}",
			"data/config/config.json": b"{}",
			"data/logs/tiresias.log": b"x",
			"data/symbols/es.json": b"{}",
			"data/addons/whatsapp/manifest.json": b"{}",
			"data/addons/eloquence/manifest.json": b"{}",
			"data/addons/eloquence/synthDrivers/eci/ECI.DLL": b"x",
		}.items():
			p = os.path.join(dist, *rel.split("/"))
			os.makedirs(os.path.dirname(p), exist_ok=True)
			with open(p, "wb") as f:
				f.write(data)
		out = os.path.join(self.tmp, "publica")
		publicar.stageProgram(dist, out)
		self.assertTrue(os.path.isfile(os.path.join(out, "lib", "a.pyc")))
		self.assertTrue(os.path.isfile(os.path.join(out, "data", "addons", "whatsapp", "manifest.json")))
		self.assertFalse(os.path.exists(os.path.join(out, "data", "addons", "eloquence")))
		self.assertFalse(os.path.exists(os.path.join(out, "instalado.json")))
		self.assertTrue(os.path.isdir(os.path.join(out, "data", "config")))
		self.assertEqual(os.listdir(os.path.join(out, "data", "config")), [])
		self.assertEqual(publicar.findProprietary(out), [])
		zipPath = publicar.makePortableZip(out, os.path.join(self.tmp, "p.zip"))
		with zipfile.ZipFile(zipPath) as z:
			self.assertIn("Tiresias/Tiresias.exe", z.namelist())
		full = os.path.join(self.tmp, "completa")
		publicar.stageProgram(dist, full, includeProprietary=True)
		self.assertTrue(os.path.isfile(os.path.join(full, "data", "addons", "eloquence", "synthDrivers", "eci", "ECI.DLL")))

	def test_configuracion_de_publicacion(self):
		cfg = os.path.join(self.tmp, "publicar.json")
		with open(cfg, "w", encoding="utf-8") as f:
			json.dump({"incluirPropietario": True, "destino": "X"}, f)
		self.assertEqual(publicar.loadConfig(cfg), {"incluirPropietario": True, "destino": "X"})
		self.assertEqual(publicar.loadConfig(os.path.join(self.tmp, "no.json")), {})
		# La decisión del usuario está registrada en el repositorio: el programa
		# sin Eloquence y los complementos propietarios solo en la tienda.
		cfg = publicar.loadConfig(publicar.CONFIG_FILE)
		self.assertIs(cfg.get("incluirPropietario"), False)
		self.assertIs(cfg.get("propietariosEnTienda"), True)

	def test_confirmacion_propietario(self):
		class A:
			acepto_responsabilidad = False

		import builtins
		from unittest import mock

		with mock.patch.object(builtins, "input", return_value="no"):
			self.assertFalse(quiet(publicar.confirmProprietary, A()))
		with mock.patch.object(builtins, "input", return_value="asumo la responsabilidad"):
			self.assertTrue(quiet(publicar.confirmProprietary, A()))


if __name__ == "__main__":
	unittest.main()
