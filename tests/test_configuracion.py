"""Pruebas del área de configuración, perfiles, política, idioma, complementos e instalación.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import gettext
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from tiresias import paths  # noqa: E402
from tiresias.config import ConfigManager, domainFromUrl, migrations, normalizeDomain, schema, validation  # noqa: E402
from tiresias.config.policy import Policy  # noqa: E402


class TempData(unittest.TestCase):
	"""Carpeta de datos temporal para cada prueba (se restaura la anterior)."""

	def setUp(self) -> None:
		self._oldData = paths.DATA_DIR
		self._oldConfig = paths._configDirOverride
		self.tmp = tempfile.mkdtemp(prefix="tiresias_cfg_")
		paths.setDataDir(self.tmp)
		paths.setConfigDir(None)
		paths.ensureDataDirs()

	def tearDown(self) -> None:
		paths.setDataDir(self._oldData)
		paths.setConfigDir(self._oldConfig)
		shutil.rmtree(self.tmp, ignore_errors=True)


# ====================================================================== validación
class ValidationTests(unittest.TestCase):
	def test_coerce_types(self) -> None:
		d = schema.getDefaults()
		data = {
			"general": {"saveConfigurationOnExit": "false", "logLevel": "debug"},
			"speech": {"symbolLevel": "200", "capitalPitchChange": 500, "synthPriority": "espeak, sapi5"},
			"keyboard": {"layout": "mecanografía"},
			"braille": "no es una sección",
			"miComplemento": {"x": 1},
		}
		issues = validation.validate(data, d)
		self.assertIs(data["general"]["saveConfigurationOnExit"], False)
		self.assertEqual(data["general"]["logLevel"], "DEBUG")
		self.assertEqual(data["speech"]["symbolLevel"], 200)
		self.assertEqual(data["speech"]["capitalPitchChange"], 100)
		self.assertEqual(data["speech"]["synthPriority"], ["espeak", "sapi5"])
		self.assertNotIn("layout", data["keyboard"])
		self.assertNotIn("braille", data)
		# Las secciones desconocidas (de complementos) se conservan.
		self.assertEqual(data["miComplemento"], {"x": 1})
		self.assertGreaterEqual(len(issues), 6)

	def test_bool_is_not_int(self) -> None:
		data = {"speech": {"symbolLevel": True}}
		validation.validate(data, schema.getDefaults())
		self.assertNotIn("symbolLevel", data["speech"])

	def test_float_range(self) -> None:
		data = {"magnifier": {"level": 40}}
		validation.validate(data, schema.getDefaults())
		self.assertEqual(data["magnifier"]["level"], 16.0)


# ====================================================================== migraciones
class MigrationTests(unittest.TestCase):
	def test_v1_to_v2(self) -> None:
		data = {
			"general": {"language": "es"},
			"presentation": {"verbosity": "low"},
			"keyboard": {"passNonCommandKeysInBrowseMode": True},
			"uia": {"reportNotifications": False},
			"speech": {"outputDevice": "Altavoces"},
			"magnifier": {"followCaret": False},
			"advanced": {"debugCategories": "Events, voz, inventada"},
		}
		done = migrations.migrate(data, 2)
		self.assertEqual(done, [1])
		self.assertEqual(data["presentation"]["verbosity"], "expert")
		self.assertNotIn("keyboard", data)
		self.assertIs(data["browseMode"]["trapNonCommandGestures"], False)
		self.assertIs(data["presentation"]["reportNotifications"], False)
		self.assertNotIn("uia", data)
		self.assertEqual(data["audio"]["outputDevice"], "Altavoces")
		self.assertNotIn("speech", data)
		self.assertIs(data["magnifier"]["followReview"], False)
		self.assertEqual(data["advanced"]["debugCategories"], ["eventos", "voz"])
		self.assertNotIn("general", data)
		self.assertNotIn(migrations.VERSION_KEY, data)

	def test_current_version_untouched(self) -> None:
		data = {"schemaVersion": schema.SCHEMA_VERSION, "general": {"language": "es"}}
		self.assertEqual(migrations.migrate(data), [])
		self.assertEqual(data["general"]["language"], "es")

	def test_newer_file_kept(self) -> None:
		data = {"schemaVersion": schema.SCHEMA_VERSION + 5, "x": {"y": 1}}
		self.assertEqual(migrations.migrate(data), [])
		self.assertEqual(data["x"], {"y": 1})


# ====================================================================== disco, copias y perfiles
class ConfigFileTests(TempData):
	def test_save_writes_version_and_backup(self) -> None:
		conf = ConfigManager()
		conf.load()
		conf["speech"]["symbolLevel"] = 200
		conf.save()
		conf["speech"]["symbolLevel"] = 300
		conf.save()
		with open(conf.configFile, encoding="utf-8") as f:
			data = json.load(f)
		self.assertEqual(data["schemaVersion"], schema.SCHEMA_VERSION)
		self.assertEqual(data["speech"]["symbolLevel"], 300)
		with open(conf.configFile + ".bak", encoding="utf-8") as f:
			self.assertEqual(json.load(f)["speech"]["symbolLevel"], 200)

	def test_corrupt_file_recovers_backup(self) -> None:
		conf = ConfigManager()
		conf.load()
		conf["speech"]["symbolLevel"] = 200
		conf.save()
		conf["speech"]["symbolLevel"] = 300
		conf.save()
		with open(conf.configFile, "w", encoding="utf-8") as f:
			f.write("{ esto no es json")
		conf2 = ConfigManager()
		conf2.load()
		self.assertEqual(conf2["speech"]["symbolLevel"], 200)
		self.assertIn("config.json", conf2.recoveredFiles)
		self.assertTrue(os.path.isfile(conf.configFile + ".corrupto"))

	def test_old_file_is_migrated_on_load(self) -> None:
		conf = ConfigManager()
		os.makedirs(paths.configDir(), exist_ok=True)
		with open(conf.configFile, "w", encoding="utf-8") as f:
			json.dump({"uia": {"reportNotifications": False}, "speech": {"symbolLevel": "100"}}, f)
		conf.load()
		self.assertIs(conf["presentation"]["reportNotifications"], False)
		self.assertEqual(conf["speech"]["symbolLevel"], 100)

	def test_read_only_mode_never_writes(self) -> None:
		conf = ConfigManager()
		conf.readOnly = True
		conf.load()
		conf["speech"]["symbolLevel"] = 200
		conf.save()
		self.assertFalse(os.path.exists(conf.configFile))

	def test_config_path_override(self) -> None:
		other = os.path.join(self.tmp, "otra")
		paths.setConfigDir(other)
		conf = ConfigManager()
		conf.load()
		conf["speech"]["symbolLevel"] = 0
		conf.save()
		self.assertTrue(os.path.isfile(os.path.join(other, "config.json")))
		self.assertEqual(paths.profilesDir(), os.path.join(other, "profiles"))


class ProfileTests(TempData):
	def setUp(self) -> None:
		super().setUp()
		self.conf = ConfigManager()
		self.conf.load()

	def test_disabled_profile_not_triggered(self) -> None:
		c = self.conf
		c.createProfile("Bloc")
		c.profiles["Bloc"].data = {"speech": {"symbolLevel": 0}}
		c.setTrigger("app:notepad", "Bloc")
		c.setProfileEnabled("Bloc", False)
		c.enterTrigger("app:notepad")
		self.assertEqual(c["speech"]["symbolLevel"], 100)
		c.setProfileEnabled("Bloc", True)
		self.assertEqual(c["speech"]["symbolLevel"], 0)
		c.exitTrigger("app:notepad")
		self.assertEqual(c["speech"]["symbolLevel"], 100)
		# El estado se conserva al volver a cargar.
		c.setProfileEnabled("Bloc", False)
		c2 = ConfigManager()
		c2.load()
		self.assertFalse(c2.isProfileEnabled("Bloc"))

	def test_read_only_profile_not_saved(self) -> None:
		c = self.conf
		c.createProfile("Fijo")
		c.setProfileReadOnly("Fijo", True)
		c.setManualProfile("Fijo")
		c["speech"]["symbolLevel"] = 300
		c.save()
		with open(c.profiles["Fijo"].fileName, encoding="utf-8") as f:
			self.assertNotIn("speech", json.load(f))

	def test_domain_trigger(self) -> None:
		c = self.conf
		c.createProfile("Correo")
		c.setTrigger("dominio:ejemplo.com", "Correo")
		self.assertEqual(c.findDomainTrigger("correo.ejemplo.com"), "dominio:ejemplo.com")
		self.assertEqual(c.findDomainTrigger("ejemplo.com"), "dominio:ejemplo.com")
		self.assertIsNone(c.findDomainTrigger("otroejemplo.com"))
		self.assertEqual(domainFromUrl("https://www.Ejemplo.com:8080/a?b"), "ejemplo.com")
		self.assertIsNone(domainFromUrl("about:blank"))
		self.assertEqual(normalizeDomain(" https://www.Ejemplo.com/x "), "ejemplo.com")
		self.assertEqual(normalizeDomain("WWW.ejemplo.com/ruta"), "ejemplo.com")

	def test_clone_profile(self) -> None:
		c = self.conf
		c.createProfile("A")
		c.profiles["A"].data = {"speech": {"symbolLevel": 0}}
		c.createProfile("B", "A")
		self.assertEqual(c.profiles["B"].data, {"speech": {"symbolLevel": 0}})

	def test_undo_factory_reset(self) -> None:
		c = self.conf
		c["speech"]["symbolLevel"] = 300
		self.assertFalse(c.canUndoFactoryReset)
		c.resetToFactoryDefaults()
		self.assertEqual(c["speech"]["symbolLevel"], 100)
		self.assertTrue(c.canUndoFactoryReset)
		self.assertTrue(c.undoFactoryReset())
		self.assertEqual(c["speech"]["symbolLevel"], 300)
		self.assertFalse(c.undoFactoryReset())

	def test_shared_profile_between_triggers(self) -> None:
		c = self.conf
		c.createProfile("Web")
		c.profiles["Web"].data = {"speech": {"symbolLevel": 0}}
		c.setTrigger("app:chrome", "Web")
		c.setTrigger("dominio:ejemplo.com", "Web")
		c.enterTrigger("app:chrome")
		c.enterTrigger("dominio:ejemplo.com")
		c.exitTrigger("dominio:ejemplo.com")
		# Sigue activo porque el disparador de la aplicación también lo usa.
		self.assertEqual(c["speech"]["symbolLevel"], 0)
		c.exitTrigger("app:chrome")
		self.assertEqual(c["speech"]["symbolLevel"], 100)


# ====================================================================== política
class PolicyTests(TempData):
	def test_locked_settings(self) -> None:
		path = os.path.join(self.tmp, "policy.json")
		with open(path, "w", encoding="utf-8") as f:
			json.dump({"lockedSettings": {"speech.symbolLevel": 300, "update.autoCheck": False}, "blockedAddons": ["malo"], "allowPythonConsole": False}, f)
		pol = Policy.load(path)
		c = ConfigManager()
		c.setPolicy(pol)
		c.load()
		self.assertEqual(c["speech"]["symbolLevel"], 300)
		c["speech"]["symbolLevel"] = 0
		self.assertEqual(c["speech"]["symbolLevel"], 300)
		self.assertTrue(c.isLocked("speech", "symbolLevel"))
		self.assertFalse(c.isLocked("speech", "rate"))
		self.assertIs(c["update"]["autoCheck"], False)
		self.assertTrue(pol.isAddonBlocked("malo"))
		self.assertFalse(pol.isAllowed("pythonConsole"))
		self.assertTrue(pol.isAllowed("addonStore"))
		# El modo seguro bloquea además sus funciones.
		pol.secureMode = True
		self.assertFalse(pol.isAllowed("addonStore"))
		c.setPolicy(Policy())

	def test_invalid_policy_file(self) -> None:
		path = os.path.join(self.tmp, "policy.json")
		with open(path, "w", encoding="utf-8") as f:
			f.write("[1, 2")
		pol = Policy.load(path)
		self.assertEqual(pol.data, {})

	def test_missing_policy(self) -> None:
		self.assertFalse(Policy.load(os.path.join(self.tmp, "no.json")).active)


# ====================================================================== idioma
class I18nTests(TempData):
	def test_compile_and_load(self) -> None:
		import i18n as tool

		cat = {}
		m = tool.Message("Opciones")
		m.msgstr = ["Settings"]
		cat[m.key] = m
		p = tool.Message("{n} elemento", "{n} elementos")
		p.msgstr = ["{n} item", "{n} items"]
		cat[p.key] = p
		c = tool.Message("Abrir", ctx="menú")
		c.msgstr = ["Open"]
		cat[c.key] = c
		mo = os.path.join(self.tmp, "xx", "LC_MESSAGES", "tiresias.mo")
		self.assertEqual(tool.compileMo(cat, mo, "xx"), 3)
		t = gettext.translation("tiresias", self.tmp, languages=["xx"])
		self.assertEqual(t.gettext("Opciones"), "Settings")
		self.assertEqual(t.ngettext("{n} elemento", "{n} elementos", 2), "{n} items")
		self.assertEqual(t.pgettext("menú", "Abrir"), "Open")
		self.assertEqual(t.gettext("Sin traducir"), "Sin traducir")

	def test_po_roundtrip_and_extraction(self) -> None:
		import i18n as tool

		src = os.path.join(self.tmp, "mod.py")
		with open(src, "w", encoding="utf-8") as f:
			f.write('from x import _\na = _("Hola\\nmundo «{x}»")\nb = ngettext("uno", "varios", 2)\nc = pgettext("ctx", "texto")\nd = _(variable)\n')
		cat: dict = {}
		self.assertEqual(tool.extractFile(src, "mod.py", cat), 3)
		for m in cat.values():
			m.msgstr = ["T"] if m.plural is None else ["T1", "T2"]
		po = os.path.join(self.tmp, "x.po")
		tool.writePo(po, cat, "en")
		back = tool.readPo(po)
		self.assertEqual(set(back), set(cat))
		self.assertEqual(back[(None, "Hola\nmundo «{x}»")].msgstr, ["T"])
		self.assertEqual(back[(None, "uno")].msgstr, ["T1", "T2"])
		self.assertEqual(back[("ctx", "texto")].msgstr, ["T"])

	def test_resolve_language(self) -> None:
		from tiresias import i18n

		self.assertEqual(i18n.resolveLanguage("es"), "es")
		self.assertEqual(i18n.resolveLanguage("zz_ZZ"), "es")
		self.assertIn(i18n.resolveLanguage("auto"), i18n.availableLanguages())

	def test_english_catalog_is_consistent(self) -> None:
		"""Las traducciones conservan las variables y como mucho un acelerador."""
		import string

		import i18n as tool

		po = tool.poPath("en")
		if not os.path.isfile(po):
			self.skipTest("sin catálogo inglés")
		fmt = string.Formatter()

		def fields(s: str) -> set:
			try:
				return {f for _t, f, _s, _c in fmt.parse(s) if f is not None}
			except ValueError:
				return set()

		cat = tool.readPo(po)
		translated = [m for m in cat.values() if any(m.msgstr)]
		self.assertGreater(len(translated), 0)
		for m in translated:
			for s in m.msgstr:
				if not s:
					continue
				if "{" in m.msgid:
					self.assertEqual(fields(s), fields(m.msgid), m.msgid)
				if "&" not in m.msgid:
					self.assertNotIn("&", s.replace("&&", ""), m.msgid)
		mo = os.path.join(tool.LOCALE, "en", "LC_MESSAGES", "tiresias.mo")
		self.assertTrue(os.path.isfile(mo))


# ====================================================================== complementos
def _makeAddon(folder: str, addonId: str, version: str, lastTested: str = "1.0", minApi: str = "1.0") -> str:
	os.makedirs(folder, exist_ok=True)
	with open(os.path.join(folder, "manifest.json"), "w", encoding="utf-8") as f:
		json.dump({"id": addonId, "name": addonId, "version": version, "minApiVersion": minApi, "lastTestedApiVersion": lastTested, "changelog": "Cambios"}, f)
	return folder


class AddonTests(TempData):
	def setUp(self) -> None:
		super().setUp()
		from tiresias import addons
		from tiresias.config import conf

		self.addons = addons
		self.conf = conf
		self._oldOverride = list(conf["addons"]["overrideCompatibility"])

	def tearDown(self) -> None:
		self.conf["addons"]["overrideCompatibility"] = self._oldOverride
		super().tearDown()

	def test_compatibility(self) -> None:
		a = self.addons
		old = a.Addon(_makeAddon(os.path.join(self.tmp, "viejo"), "viejo", "1.0", lastTested="0.5"), {"id": "viejo", "lastTestedApiVersion": "0.5", "minApiVersion": "0.5"})
		self.assertTrue(old.isUntested)
		self.assertFalse(old.isCompatible)
		self.assertIsNotNone(old.incompatibilityReason())
		a.setCompatibilityOverride("viejo", True)
		self.assertTrue(old.isCompatible)
		a.setCompatibilityOverride("viejo", False)
		new = a.Addon(self.tmp, {"id": "nuevo", "minApiVersion": "99.0"})
		self.assertTrue(new.isTooNew)
		self.assertFalse(new.isCompatible)
		ok = a.Addon(self.tmp, {"id": "ok", "minApiVersion": "1.0", "lastTestedApiVersion": "1.0"})
		self.assertTrue(ok.isCompatible)
		self.assertEqual(a.compareVersions("1.2.0", "1.10"), -1)
		self.assertEqual(a.compareVersions("2.0", "2.0.0"), 0)

	def test_inspect_and_install_over(self) -> None:
		a = self.addons
		src = _makeAddon(os.path.join(self.tmp, "src", "prueba"), "prueba", "1.0.0")
		pkg = a.createPackage(src, os.path.join(self.tmp, "prueba.tiresias-addon"))
		manifest, existing = a.inspectPackage(pkg)
		self.assertEqual(manifest["id"], "prueba")
		self.assertIsNone(existing)
		installed = a.installFromFile(pkg)
		self.assertEqual(installed.version, "1.0.0")
		_makeAddon(src, "prueba", "1.1.0")
		pkg2 = a.createPackage(src, os.path.join(self.tmp, "prueba2.tiresias-addon"))
		manifest, existing = a.inspectPackage(pkg2)
		self.assertIsNotNone(existing)
		self.assertEqual(a.compareVersions(manifest["version"], existing.version), 1)
		self.assertEqual(a.installFromFile(pkg2).version, "1.1.0")
		self.assertEqual(installed.changelog if hasattr(installed, "changelog") else "Cambios", "Cambios")

	def test_store_catalog(self) -> None:
		from tiresias import addon_store

		src = _makeAddon(os.path.join(self.tmp, "src", "tienda"), "tienda", "2.0.0")
		pkgDir = os.path.join(self.tmp, "repo", "complementos")
		os.makedirs(pkgDir)
		pkg = self.addons.createPackage(src, os.path.join(pkgDir, "tienda.tiresias-addon"))
		from tiresias import updates

		catalog = {
			"format": addon_store.CATALOG_FORMAT,
			"addons": [
				{"id": "tienda", "name": "Tienda", "version": "2.0.0", "url": "complementos/tienda.tiresias-addon", "sha256": updates.fileSha256(pkg)},
				{"id": "futuro", "name": "Futuro", "version": "1.0", "minApiVersion": "50.0", "url": "x"},
				{"name": "sin id"},
			],
		}
		catPath = os.path.join(self.tmp, "repo", "catalogo.json")
		with open(catPath, "w", encoding="utf-8") as f:
			json.dump(catalog, f)
		entries, source = addon_store.fetchCatalog(catPath)
		self.assertEqual(source, catPath)
		self.assertEqual([e.id for e in entries], ["tienda", "futuro"])
		self.assertEqual(entries[1].status(), "incompatible")
		self.assertEqual(entries[0].status(), "available")
		self.assertTrue(entries[0].url.endswith(os.path.join("complementos", "tienda.tiresias-addon")))
		addon = addon_store.installEntry(entries[0])
		self.assertEqual(addon.version, "2.0.0")
		self.assertEqual(entries[0].status(), "installed")
		# Suma de comprobación incorrecta: no se instala.
		entries[0].sha256 = "0" * 64
		with self.assertRaises(ValueError):
			addon_store.installEntry(entries[0])

	def test_bundled_catalog_is_valid(self) -> None:
		from tiresias import addon_store

		path = os.path.join(ROOT, "docs", "catalogo_complementos.json")
		from tiresias import updates

		# Copia local del catálogo publicado (tools/publicar.py), con direcciones
		# relativas al catálogo en línea. Eloquence solo aparece marcado como propietario.
		online = updates.DISTRIBUTION_URL + "/" + updates.CATALOG_FILE
		with open(path, encoding="utf-8") as f:
			entries = addon_store.parseCatalog(json.load(f), online)
		self.assertIn("whatsapp", {e.id for e in entries})
		for e in entries:
			if e.id == "eloquence":
				self.assertTrue(e.extra.get("proprietary"))
		for e in entries:
			self.assertTrue(e.url.startswith(updates.DISTRIBUTION_URL + "/complementos/"), e.url)
			self.assertEqual(len(e.sha256), 64)


# ====================================================================== actualizaciones
class UpdateTests(TempData):
	def test_parse_update(self) -> None:
		from tiresias import VERSION, updates

		self.assertIsNone(updates.parseUpdate({"version": VERSION, "url": "x"}))
		self.assertIsNone(updates.parseUpdate({"version": "0.9", "url": "x"}))
		info = updates.parseUpdate({"version": "99.0.0", "url": "a/b.exe", "notes": "n"}, "https://servidor/docs/actualizacion.json")
		self.assertEqual(info.url, "https://servidor/docs/a/b.exe")
		self.assertGreater(updates.versionTuple("1.0.10"), updates.versionTuple("1.0.9"))

	def test_download_checks_hash(self) -> None:
		from tiresias import updates

		src = os.path.join(self.tmp, "origen.bin")
		with open(src, "wb") as f:
			f.write(b"x" * 200000)
		dest = os.path.join(self.tmp, "d", "copia.bin")
		seen = []
		updates.download("file:///" + src.replace(os.sep, "/"), dest, updates.fileSha256(src), lambda d, t: seen.append(d) or True)
		self.assertTrue(os.path.isfile(dest))
		self.assertEqual(seen[-1], 200000)
		with self.assertRaises(ValueError):
			updates.download(src, dest + "2", "0" * 64)
		self.assertFalse(os.path.exists(dest + "2"))


# ====================================================================== instalación y copias portables
def _fakeProgram(base: str) -> str:
	app = os.path.join(base, "programa")
	os.makedirs(os.path.join(app, "lib", "tiresias"))
	for rel in ("Tiresias.exe", "lib/tiresias/core.pyc", "LICENSE.txt", "Manual de usuario.html"):
		p = os.path.join(app, *rel.split("/"))
		with open(p, "w", encoding="utf-8") as f:
			f.write(rel)
	_makeAddon(os.path.join(app, "data", "addons", "incluido"), "incluido", "1.0.0")
	os.makedirs(os.path.join(app, "data", "symbols"))
	with open(os.path.join(app, "data", "symbols", "es.json"), "w", encoding="utf-8") as f:
		f.write("{}")
	os.makedirs(os.path.join(app, "data", "config"))
	with open(os.path.join(app, "data", "config", "config.json"), "w", encoding="utf-8") as f:
		f.write('{"privado": 1}')
	return app


class InstallerTests(TempData):
	def test_portable_copy(self) -> None:
		from tiresias import installer

		app = _fakeProgram(self.tmp)
		userData = os.path.join(self.tmp, "datosUsuario")
		os.makedirs(os.path.join(userData, "config"))
		with open(os.path.join(userData, "config", "config.json"), "w", encoding="utf-8") as f:
			f.write('{"mio": 1}')
		_makeAddon(os.path.join(userData, "addons", "propio"), "propio", "3.0")
		dest = os.path.join(self.tmp, "portable")
		installer.createPortableCopy(dest, copyConfig=True, copyAddons=True, appDir=app, dataDir=userData, programDataDir=os.path.join(app, "data"), frozen=True)
		self.assertTrue(os.path.isfile(os.path.join(dest, "Tiresias.exe")))
		self.assertTrue(os.path.isfile(os.path.join(dest, "lib", "tiresias", "core.pyc")))
		self.assertTrue(os.path.isdir(os.path.join(dest, "data", "addons", "incluido")))
		self.assertTrue(os.path.isdir(os.path.join(dest, "data", "addons", "propio")))
		with open(os.path.join(dest, "data", "config", "config.json"), encoding="utf-8") as f:
			self.assertEqual(json.load(f), {"mio": 1})
		self.assertFalse(os.path.exists(os.path.join(dest, paths.INSTALLED_MARKER)))
		# Sin configuración: no se copia la del usuario ni la del programa.
		dest2 = os.path.join(self.tmp, "portable2")
		installer.createPortableCopy(dest2, copyConfig=False, copyAddons=False, appDir=app, dataDir=userData, programDataDir=os.path.join(app, "data"), frozen=True)
		self.assertFalse(os.path.exists(os.path.join(dest2, "data", "config", "config.json")))
		self.assertFalse(os.path.exists(os.path.join(dest2, "data", "addons", "propio")))
		with self.assertRaises(ValueError):
			installer.createPortableCopy(os.path.join(app, "dentro"), appDir=app, dataDir=userData, frozen=True)

	def test_install_and_uninstall(self) -> None:
		import winreg

		from tiresias import installer

		app = _fakeProgram(self.tmp)
		target = os.path.join(self.tmp, "Archivos de programa", "Tiresias")
		menu = os.path.join(self.tmp, "menu")
		desk = os.path.join(self.tmp, "escritorio")
		os.makedirs(desk)
		key = r"Software\TiresiasPruebas\Uninstall\Tiresias"
		run = r"Software\TiresiasPruebas\Run"
		targets = installer.SystemTargets(allUsers=False, uninstallKey=key, runKey=run, startMenuDir=menu, desktopDir=desk)
		try:
			exe = installer.install(installer.InstallOptions(targetDir=target, allUsers=False, sourceDir=app, startOnLogon=True, targets=targets))
			self.assertTrue(os.path.isfile(exe))
			self.assertTrue(os.path.isfile(os.path.join(target, paths.INSTALLED_MARKER)))
			self.assertTrue(os.path.isdir(os.path.join(target, "data", "addons", "incluido")))
			self.assertFalse(os.path.exists(os.path.join(target, "data", "config")))
			for lnk in ("Tiresias.lnk", "Desinstalar Tiresias.lnk", "Manual de usuario.lnk"):
				self.assertTrue(os.path.isfile(os.path.join(menu, lnk)), lnk)
			self.assertTrue(os.path.isfile(os.path.join(desk, "Tiresias.lnk")))
			info = installer.installedInfo(targets)
			self.assertEqual(info["InstallLocation"], target)
			self.assertIn("--uninstall", info["UninstallString"])
			with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run) as k:
				self.assertIn(target, winreg.QueryValueEx(k, "Tiresias")[0])
			removed = installer.uninstall(target, targets)
			self.assertTrue(removed)
			self.assertFalse(os.path.exists(target))
			self.assertFalse(os.path.exists(menu))
			self.assertFalse(os.path.exists(os.path.join(desk, "Tiresias.lnk")))
			self.assertEqual(installer.installedInfo(targets), {})
		finally:
			for k in (key, run, r"Software\TiresiasPruebas\Uninstall", r"Software\TiresiasPruebas"):
				try:
					winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, k, winreg.KEY_WOW64_64KEY, 0)
				except OSError:
					pass

	def test_install_requires_compiled_program(self) -> None:
		from tiresias import installer

		with self.assertRaises(ValueError):
			installer.install(installer.InstallOptions(targetDir=os.path.join(self.tmp, "x"), sourceDir=self.tmp, targets=installer.SystemTargets(writeRegistry=False)))

	def test_seed_user_data(self) -> None:
		from tiresias import installer

		app = _fakeProgram(self.tmp)
		user = os.path.join(self.tmp, "appdata")
		installer.seedUserData(os.path.join(app, "data"), user)
		self.assertTrue(os.path.isfile(os.path.join(user, "symbols", "es.json")))
		self.assertTrue(os.path.isdir(os.path.join(user, "addons", "incluido")))
		# Una versión nueva incluida con el programa sustituye a la del usuario.
		_makeAddon(os.path.join(app, "data", "addons", "incluido"), "incluido", "2.0.0")
		installer.seedUserData(os.path.join(app, "data"), user)
		with open(os.path.join(user, "addons", "incluido", "manifest.json"), encoding="utf-8") as f:
			self.assertEqual(json.load(f)["version"], "2.0.0")
		# Si el usuario lo eliminó, no vuelve.
		shutil.rmtree(os.path.join(user, "addons", "incluido"))
		open(os.path.join(user, "addons", ".incluido.eliminado"), "w").close()
		installer.seedUserData(os.path.join(app, "data"), user)
		self.assertFalse(os.path.exists(os.path.join(user, "addons", "incluido")))

	def test_copy_config_to_system(self) -> None:
		from tiresias import installer

		src = os.path.join(self.tmp, "cfg")
		os.makedirs(os.path.join(src, "profiles"))
		for fn in ("config.json", "config.json.bak", "profiles/a.json"):
			with open(os.path.join(src, *fn.split("/")), "w", encoding="utf-8") as f:
				f.write("{}")
		dest = installer.copyConfigToSystem(src, os.path.join(self.tmp, "systemConfig"))
		self.assertTrue(os.path.isfile(os.path.join(dest, "config.json")))
		self.assertTrue(os.path.isfile(os.path.join(dest, "profiles", "a.json")))
		self.assertFalse(os.path.exists(os.path.join(dest, "config.json.bak")))

	def test_installer_package(self) -> None:
		"""El empaquetado del instalador excluye los datos del desarrollador."""
		import build_installer

		app = _fakeProgram(self.tmp)
		old = build_installer.PROGRAM
		build_installer.PROGRAM = app
		try:
			z = os.path.join(self.tmp, "p.zip")
			build_installer.makeZip(z)
			with zipfile.ZipFile(z) as f:
				names = set(f.namelist())
		finally:
			build_installer.PROGRAM = old
		self.assertIn("Tiresias.exe", names)
		self.assertIn("data/addons/incluido/manifest.json", names)
		self.assertNotIn("data/config/config.json", names)
		self.assertIn("--install", build_installer.SETUP_CMD)

	def test_built_installer(self) -> None:
		import build_installer

		if not os.path.isfile(build_installer.OUTPUT):
			self.skipTest("instalador no construido (Tiresias.bat instalador)")
		self.assertTrue(build_installer.verify())


# ====================================================================== varios
class MiscTests(TempData):
	def test_text_paragraph(self) -> None:
		from tiresias.browse import doc_navigation

		rx = schema.DEFAULTS["documentNavigation"]["textParagraphRegex"]
		self.assertTrue(doc_navigation.isTextParagraph("Esto es un párrafo de texto suficientemente largo.", rx, 20))
		self.assertFalse(doc_navigation.isTextParagraph("Menú principal", rx, 20))
		self.assertFalse(doc_navigation.isTextParagraph("Corto.", rx, 20))
		self.assertIsNone(doc_navigation.compileRegex("(sin cerrar"))

	def test_labels_export_import(self) -> None:
		from tiresias import labels

		labels._cache.clear()
		labels.setLabelByKey("bloc", "id:boton1|9", "Guardar")
		labels.setLabelByKey("bloc", "name:x|y|9", "Cerrar")
		self.assertEqual(labels.listApps(), ["bloc"])
		out = os.path.join(self.tmp, "etiquetas.json")
		self.assertEqual(labels.exportLabels(out), 2)
		labels.deleteApp("bloc")
		self.assertEqual(labels.listApps(), [])
		self.assertEqual(labels.importLabels(out), 2)
		self.assertEqual(labels.getAll("bloc")["id:boton1|9"], "Guardar")
		self.assertIn("boton1", labels.describeKey("id:boton1|9"))
		with open(out, "w", encoding="utf-8") as f:
			f.write("{}")
		with self.assertRaises(ValueError):
			labels.importLabels(out)
		labels._cache.clear()

	def test_gesture_map_export_import(self) -> None:
		from tiresias import gesture_layouts
		from tiresias.input import gestures

		m = gestures.userMap
		saved = m.userBindings()
		try:
			m.reset()
			m.bind("tiresias.global_commands.GlobalCommands", "kb:tiresias+shift+f9", "title")
			m.unbind("tiresias.global_commands.GlobalCommands", "kb:tiresias+t")
			out = os.path.join(self.tmp, "gestos.json")
			self.assertEqual(gesture_layouts.exportUserMap(out), 2)
			m.reset()
			self.assertEqual(gesture_layouts.importUserMap(out, merge=False), 2)
			b = m.userBindings()["tiresias.global_commands.GlobalCommands"]
			self.assertEqual(b["kb:tiresias+shift+f9"], "title")
			self.assertIsNone(b["kb:tiresias+t"])
		finally:
			m.reset()
			for cls, bindings in saved.items():
				for g, s in bindings.items():
					m.bind(cls, g, s) if s else m.unbind(cls, g)

	def test_jaws_layout_targets_exist(self) -> None:
		from tiresias import config_plugin, gesture_layouts
		from tiresias.global_commands import GlobalCommands

		for gid, (target, name) in gesture_layouts.LAYOUTS["jaws"].items():
			cls = GlobalCommands if target == "global" else config_plugin.GlobalPlugin
			self.assertTrue(hasattr(cls, "script_" + name), f"{gid} -> {target}:{name}")

	def test_layer_targets_exist(self) -> None:
		from tiresias import config_plugin, gui
		from tiresias.global_commands import GlobalCommands

		for target in config_plugin.layerTargets():
			kind, _s, name = target.partition(":")
			if kind == "gui":
				self.assertTrue(callable(getattr(gui, name, None)), target)
			else:
				cls = GlobalCommands if kind == "global" else config_plugin.GlobalPlugin
				self.assertTrue(hasattr(cls, "script_" + name), target)

	def test_key_reference_has_all_sections(self) -> None:
		from tiresias.gui import keyref

		sections = keyref.collectSections()
		titles = [s.title for s in sections]
		self.assertTrue(any("globales" in t for t in titles))
		self.assertTrue(any("exploración" in t for t in titles))
		self.assertTrue(any(t.startswith("Aplicación") for t in titles))
		html = keyref.buildHtml(sections)
		self.assertIn("<h2", html)
		self.assertIn("Tiresias+F2", keyref.buildText(sections))

	def test_watchdog_cancel_without_thread(self) -> None:
		from tiresias import watchdog

		old = watchdog.coreThreadId
		watchdog.coreThreadId = 0
		try:
			self.assertFalse(watchdog.cancelPendingCall())
		finally:
			watchdog.coreThreadId = old

	def test_restart_arguments(self) -> None:
		from tiresias import core

		ns = core.parseArgs(["--secure", "--lang", "en", "--disable-addons", "--minimal", "--config-path", "x"])
		self.assertTrue(ns.secure and ns.safe_mode and ns.minimal and ns.no_sounds)
		old = core.args
		core.args = ns
		try:
			out = core.restartArguments()
		finally:
			core.args = old
		self.assertEqual(out, ["--safe-mode", "--secure", "--config-path", "x", "--lang", "en", "--minimal"])


if __name__ == "__main__":
	unittest.main()
