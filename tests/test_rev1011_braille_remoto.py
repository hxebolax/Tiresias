"""Revisión 10.11: braille, acceso remoto, convivencia, actualizaciones y complementos.

Pruebas de las correcciones de la auditoría:

- Direcciones de los JSON publicados en la red (sin rutas locales, carpetas
  compartidas, ``file://`` ni bajadas a ``http``).
- Copias portables sin paquete portable y límite del ZIP descomprimido.
- Complementos: identificador comprobado con el manifiesto extraído,
  identificadores válidos, sustitución segura, complementos incluidos
  eliminados y límite de tamaño.
- Guardián: marcador de salida antiguo con el mismo PID.
- Mensajes braille que dejan paso al contenido nuevo al pulsar teclas y
  aviso de tabla de liblouis rota.
- Acceso remoto: prosodia acotada, sonidos solo locales y límites del
  servidor local (solo en 127.0.0.1).

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev1011_braille_remoto``
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import ssl
import sys
import tempfile
import time
import types
import unittest
import zipfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
	sys.path.insert(0, HERE)

import braille_sim  # noqa: E402,F401  (carpeta de datos temporal)

from tiresias import addon_store, addons, api, paths, updates  # noqa: E402
from tiresias.braille import presenter, tables  # noqa: E402
from tiresias.coexist import guardian, relaunch  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.objects.roles import Role  # noqa: E402
from tiresias.remote import local_machine, serializer, server as serverModule  # noqa: E402
from tiresias.remote.certs import CertificateManager  # noqa: E402
from tiresias.remote.server import RelayServer  # noqa: E402
from tiresias.speech import commands as cmds  # noqa: E402

from test_braille import FakeObj, _BrailleCase  # noqa: E402


def waitFor(pred, timeout: float = 5.0) -> bool:
	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		if pred():
			return True
		time.sleep(0.02)
	return pred()


# ====================================================================== direcciones
class ResolveUrlTests(unittest.TestCase):
	BASE = "https://x.org/Tiresias/actualizacion.json"

	def test_relativas_y_https_siguen_valiendo(self) -> None:
		self.assertEqual(updates.resolveUrl(self.BASE, "descargas/1.0/a.exe"), "https://x.org/Tiresias/descargas/1.0/a.exe")
		self.assertEqual(updates.resolveUrl(self.BASE, "/otra/a.exe"), "https://x.org/otra/a.exe")
		self.assertEqual(updates.resolveUrl(self.BASE, "https://y.org/b.zip"), "https://y.org/b.zip")
		self.assertEqual(updates.resolveUrl(self.BASE, ""), "")

	def test_rutas_locales_y_compartidas_rechazadas(self) -> None:
		for ref in (
			"\\\\servidor\\compartida\\a.exe",
			"//servidor/compartida/a.exe".replace("//", "\\\\", 1),
			"C:\\Windows\\a.exe",
			"C:/Windows/a.exe",
			"file:///C:/a.exe",
			"file://servidor/compartida/a.exe",
			"ftp://x.org/a.exe",
			"javascript:alert(1)",
			"descargas\\a.exe",
			"a\n.exe",
		):
			with self.subTest(ref=ref), self.assertRaises(updates.UnsafeUrlError):
				updates.resolveUrl(self.BASE, ref)

	def test_sin_bajar_a_http(self) -> None:
		with self.assertRaises(updates.UnsafeUrlError):
			updates.resolveUrl(self.BASE, "http://x.org/a.exe")
		# Si el propio JSON llegó por http (red local), http sigue valiendo.
		self.assertEqual(updates.resolveUrl("http://192.168.1.2/t/a.json", "http://192.168.1.2/t/b.exe"), "http://192.168.1.2/t/b.exe")

	def test_doble_barra_rechazada(self) -> None:
		# «//host/x» es ambigua (en Windows, una carpeta compartida): no se admite.
		with self.assertRaises(updates.UnsafeUrlError):
			updates.resolveUrl(self.BASE, "//y.org/a.exe")

	def test_servidor_propio_local_admite_rutas(self) -> None:
		self.assertEqual(updates.resolveUrl(r"C:\web\actualizacion.json", "descargas/a.exe"), os.path.normpath(r"C:\web\descargas\a.exe"))
		self.assertEqual(updates.resolveUrl(r"\\servidor\web\actualizacion.json", r"\\otro\x\a.exe"), r"\\otro\x\a.exe")
		self.assertEqual(updates.resolveUrl("file://servidor/web/a.json", "b.exe"), "file://servidor/web/b.exe")

	def test_manifiesto_con_ruta_compartida_falla(self) -> None:
		data = {"version": "99.0", "url": "\\\\evil\\s\\a.exe"}
		with self.assertRaises(updates.UnsafeUrlError):
			updates.parseUpdate(data, self.BASE, channel="estable", kind="instalada")

	def test_novedades_no_permitidas_se_ignoran(self) -> None:
		data = {"version": "99.0", "url": "a.exe", "sha256": "0" * 64, "notesUrl": "file:///C:/x.html"}
		info = updates.parseUpdate(data, self.BASE, channel="estable", kind="instalada")
		self.assertEqual(info.url, "https://x.org/Tiresias/a.exe")
		self.assertEqual(info.notesUrl, "")

	def test_catalogo_descarta_entradas_no_permitidas(self) -> None:
		data = {
			"format": "tiresias-catalogo",
			"addons": [
				{"id": "bueno", "version": "1.0", "url": "complementos/bueno.tiresias-addon", "sha256": "0" * 64},
				{"id": "malo", "version": "1.0", "url": "\\\\evil\\s\\malo.tiresias-addon"},
				{"id": "malo2", "version": "1.0", "url": "file:///C:/malo.tiresias-addon"},
			],
		}
		entries = addon_store.parseCatalog(data, "https://x.org/Tiresias/complementos/catalogo.json")
		self.assertEqual([e.id for e in entries], ["bueno"])
		self.assertEqual(entries[0].url, "https://x.org/Tiresias/complementos/complementos/bueno.tiresias-addon")


# ====================================================================== paquetes de actualización
class PortablePackageTests(unittest.TestCase):
	BASE = "https://x.org/Tiresias/actualizacion.json"

	def test_portable_sin_paquete_portable_no_usa_el_instalador(self) -> None:
		data = {"version": "99.0", "url": "descargas/99.0/Tiresias-99.0-instalador.exe", "sha256": "0" * 64}
		info = updates.parseUpdate(data, self.BASE, channel="estable", kind="portable")
		self.assertIsNotNone(info)
		self.assertEqual(info.package, "portable")
		self.assertEqual(info.url, "")
		with self.assertRaises(ValueError) as cm:
			updates.downloadUpdate(info)
		self.assertIn("portables", str(cm.exception))

	def test_portable_con_paquete_portable(self) -> None:
		data = {"version": "99.0", "url": "i.exe", "portable": {"url": "p.zip", "sha256": "1" * 64}}
		info = updates.parseUpdate(data, self.BASE, channel="estable", kind="portable")
		self.assertEqual((info.package, info.url), ("portable", "https://x.org/Tiresias/p.zip"))

	def test_instalada_y_codigo_sin_cambios(self) -> None:
		data = {"version": "99.0", "url": "i.exe"}
		self.assertEqual(updates.parseUpdate(data, self.BASE, channel="estable", kind="instalada").package, "installer")
		self.assertEqual(updates.parseUpdate(data, self.BASE, channel="estable", kind="codigo").package, "installer")

	def test_zip_portable_demasiado_grande(self) -> None:
		tmp = tempfile.mkdtemp(prefix="tiresias_rev1011_")
		try:
			zp = os.path.join(tmp, "p.zip")
			with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
				z.writestr("Tiresias.exe", b"exe")
				z.writestr("relleno.bin", b"\0" * 4096)
			with mock.patch.object(updates, "MAX_PORTABLE_UNCOMPRESSED", 1024):
				with self.assertRaises(ValueError):
					updates.extractPortable(zp)
			self.assertTrue(os.path.isfile(os.path.join(updates.extractPortable(zp), "Tiresias.exe")))
		finally:
			shutil.rmtree(tmp, ignore_errors=True)


# ====================================================================== complementos
def _makeAddonZip(folder: str, name: str, files: dict[str, str | bytes]) -> str:
	path = os.path.join(folder, name)
	with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
		for arc, data in files.items():
			z.writestr(arc, data)
	return path


def _manifest(addonId: str, version: str = "1.0") -> str:
	return json.dumps({"id": addonId, "name": addonId, "version": version, "minApiVersion": "1.0", "lastTestedApiVersion": "1.0"})


class AddonInstallTests(unittest.TestCase):
	def setUp(self) -> None:
		self.tmp = tempfile.mkdtemp(prefix="tiresias_rev1011_addons_")
		self.addonsDir = os.path.join(self.tmp, "addons")
		os.makedirs(self.addonsDir)
		self._p = mock.patch.object(paths, "addonsDir", return_value=self.addonsDir)
		self._p.start()
		self._saved = dict(addons._addons)

	def tearDown(self) -> None:
		self._p.stop()
		addons._addons.clear()
		addons._addons.update(self._saved)
		shutil.rmtree(self.tmp, ignore_errors=True)

	def test_id_esperado_se_comprueba_con_lo_extraido(self) -> None:
		# inspectPackage vería «x/manifest.json» (id correcto), pero se instalaría manifest.ini (otro id).
		pkg = _makeAddonZip(self.tmp, "a.tiresias-addon", {"manifest.ini": 'id = "otro"\nversion = "1.0"\n', "x/manifest.json": _manifest("anunciado")})
		manifest, _inst = addons.inspectPackage(pkg)
		self.assertEqual(manifest["id"], "anunciado")
		with self.assertRaises(ValueError):
			addons.installFromFile(pkg, expectedId="anunciado")
		self.assertFalse(os.path.exists(os.path.join(self.addonsDir, "otro")))
		self.assertEqual([e for e in os.listdir(self.addonsDir) if not e.startswith(".")], [])

	def test_tienda_pasa_el_id_esperado(self) -> None:
		entry = addon_store.CatalogEntry(id="w", name="W", version="1.0", url="x", sha256="0" * 64)
		with (
			mock.patch.object(addon_store.policyModule, "isAllowed", return_value=True),
			mock.patch.object(addon_store, "downloadPackage", return_value=os.path.join(self.tmp, "p")),
			mock.patch.object(addons, "inspectPackage", return_value=({"id": "w"}, None)),
			mock.patch.object(addons, "installFromFile") as inst,
		):
			addon_store.installEntry(entry)
		inst.assert_called_once()
		self.assertEqual(inst.call_args.kwargs.get("expectedId"), "w")

	def test_ids_no_validos(self) -> None:
		for bad in ("", ".", "..", "_oculto", ".oculto", "con espacio", "a/b", "x.tmp", "ñandú"):
			with self.subTest(id=bad):
				self.assertFalse(addons.isValidAddonId(bad))
		for good in ("whatsapp", "NeuralVoices-voz-Alvaro", "zRadioBASS", "a.b_c-1"):
			self.assertTrue(addons.isValidAddonId(good))
		pkg = _makeAddonZip(self.tmp, "o.tiresias-addon", {"manifest.json": _manifest("_oculto")})
		with self.assertRaises(ValueError):
			addons.installFromFile(pkg)

	def test_sustitucion_conserva_la_anterior_si_falla(self) -> None:
		v1 = _makeAddonZip(self.tmp, "v1.tiresias-addon", {"manifest.json": _manifest("prueba", "1.0"), "installTasks.py": "def onUninstall():\n\topen(__file__ + '.desinstalado', 'w').close()\n"})
		addons.installFromFile(v1)
		final = os.path.join(self.addonsDir, "prueba")
		v2 = _makeAddonZip(self.tmp, "v2.tiresias-addon", {"manifest.json": _manifest("prueba", "2.0")})
		real = os.replace

		def failNew(src, dst):
			if os.path.basename(src).startswith("_install"):
				raise PermissionError("simulado")
			return real(src, dst)

		with mock.patch.object(addons.os, "replace", side_effect=failNew), self.assertRaises(PermissionError):
			addons.installFromFile(v2)
		# La versión anterior sigue en su sitio y su onUninstall no se ha ejecutado.
		self.assertEqual(addons._readManifest(final)["version"], "1.0")
		self.assertFalse(os.path.exists(os.path.join(final, "installTasks.py.desinstalado")))
		self.assertFalse(any(e.endswith(".tmp") for e in os.listdir(self.addonsDir)))
		# Sin fallos: se sustituye y el onUninstall de la anterior se ejecuta (desde su copia apartada).
		calls = []
		with mock.patch.object(addons, "_runInstallTask", side_effect=lambda folder, func: calls.append((os.path.basename(folder), func))):
			addons.installFromFile(v2)
		self.assertEqual(addons._readManifest(final)["version"], "2.0")
		self.assertIn(("prueba.old.tmp", "onUninstall"), calls)
		self.assertIn(("prueba", "onInstall"), calls)
		self.assertFalse(os.path.exists(final + ".old.tmp"))

	def test_complemento_demasiado_grande(self) -> None:
		pkg = _makeAddonZip(self.tmp, "g.tiresias-addon", {"manifest.json": _manifest("grande"), "datos.bin": b"\0" * 8192})
		with mock.patch.object(addons, "MAX_ADDON_UNCOMPRESSED", 1024), self.assertRaises(ValueError):
			addons.installFromFile(pkg)
		self.assertFalse(os.path.exists(os.path.join(self.addonsDir, "grande")))

	def test_eliminado_en_portable_deja_marcador(self) -> None:
		folder = os.path.join(self.addonsDir, "incluido")
		os.makedirs(folder)
		with open(os.path.join(folder, "manifest.json"), "w", encoding="utf-8") as f:
			f.write(_manifest("incluido"))
		addons._writePending({"remove": ["incluido"]})
		with mock.patch.object(paths, "isInstalledCopy", return_value=False):
			addons._processPending()
		self.assertFalse(os.path.exists(folder))
		self.assertTrue(os.path.exists(os.path.join(self.addonsDir, ".incluido.eliminado")))
		# La actualización de la portable no lo vuelve a copiar.
		from tiresias import installer

		src = os.path.join(self.tmp, "nuevo", "addons", "incluido")
		os.makedirs(src)
		with open(os.path.join(src, "manifest.json"), "w", encoding="utf-8") as f:
			f.write(_manifest("incluido", "9.0"))
		installer.updateBundledAddons(os.path.dirname(src), self.addonsDir)
		self.assertFalse(os.path.exists(folder))

	def test_eliminacion_pendiente_no_sale_de_la_carpeta(self) -> None:
		victim = os.path.join(self.tmp, "fuera")
		os.makedirs(victim)
		addons._writePending({"remove": ["..", "", "../fuera", "."]})
		addons._processPending()
		self.assertTrue(os.path.isdir(victim))
		self.assertTrue(os.path.isdir(self.addonsDir))


# ====================================================================== guardián
class GuardianMarkerTests(unittest.TestCase):
	def setUp(self) -> None:
		self.tmp = tempfile.mkdtemp(prefix="tiresias_rev1011_guard_")

	def tearDown(self) -> None:
		shutil.rmtree(self.tmp, ignore_errors=True)

	def test_borra_marcador_antiguo(self) -> None:
		relaunch.writeMarker(relaunch.EXIT_USER, pid=4242, dataDir=self.tmp)
		self.assertTrue(guardian.clearStaleMarker(4242, self.tmp))
		self.assertIsNone(relaunch.readMarker(4242, self.tmp))
		self.assertFalse(guardian.clearStaleMarker(4242, self.tmp))

	def test_start_borra_el_marcador_de_su_pid(self) -> None:
		relaunch.writeMarker(relaunch.EXIT_USER, pid=os.getpid(), dataDir=self.tmp)
		saved = (guardian._heartbeat, guardian._started, guardian._dataDir)
		try:
			with (
				mock.patch.object(guardian, "shouldStart", return_value=True),
				mock.patch.object(guardian, "ensureRunning", return_value=True),
				mock.patch.object(relaunch, "Heartbeat", return_value=mock.Mock()),
				mock.patch.object(guardian.paths, "DATA_DIR", self.tmp),
			):
				guardian._heartbeat = None
				self.assertTrue(guardian.start())
			self.assertIsNone(relaunch.readMarker(os.getpid(), self.tmp))
		finally:
			guardian._heartbeat, guardian._started, guardian._dataDir = saved


# ====================================================================== braille
class BrailleMessageKeyTests(_BrailleCase):
	def test_tecla_pulsada_quita_el_mensaje_al_cambiar_el_foco(self) -> None:
		obj = FakeObj("Aceptar", Role.BUTTON)
		api.setFocusObject(obj, [])
		self.h.handleObject(obj, "focus")
		conf["braille"]["showMessages"] = "always"
		self.h.message("hola")
		self.assertTrue(self.h.messageActive)
		# Sin teclas: el foco nuevo no quita el mensaje (como antes).
		other = FakeObj("Cancelar", Role.BUTTON)
		api.setFocusObject(other, [])
		self.h.handleObject(other, "focus")
		self.assertTrue(self.h.messageActive)
		# Una tecla real (no inyectada) y otro cambio: el contenido nuevo sustituye al mensaje.
		self.assertTrue(presenter.countKey(vk=0x41, pressed=True, injected=False))
		third = FakeObj("Ayuda", Role.BUTTON)
		api.setFocusObject(third, [])
		self.h.handleObject(third, "focus")
		self.assertFalse(self.h.messageActive)
		self.assertEqual(self.display.shown[:9], self._cellsFor("Ayuda btn"))

	def test_teclas_inyectadas_o_soltadas_no_cuentan(self) -> None:
		before = presenter.keyCounter
		presenter.countKey(vk=0x41, pressed=False)
		presenter.countKey(vk=0x41, pressed=True, injected=True)
		self.assertEqual(presenter.keyCounter, before)

	def _cellsFor(self, text: str) -> list[int]:
		return tables.getTable("es-comp8").translate(text).cells


class BrokenTableTests(unittest.TestCase):
	def test_aviso_una_sola_vez(self) -> None:
		table = types.SimpleNamespace(name="x.utb", displayName="Tabla X", _broken=False)
		with mock.patch.object(tables, "_announceBroken") as ann:
			tables.markBroken(table)
			tables.markBroken(table)
		ann.assert_called_once_with(table)
		self.assertTrue(table._broken)

	def test_aviso_por_voz(self) -> None:
		from tiresias import queue_handler

		table = types.SimpleNamespace(name="x.utb", displayName="Tabla X", _broken=False)
		with mock.patch.object(queue_handler, "queueFunction") as qf:
			tables.markBroken(table)
		qf.assert_called_once()
		self.assertIn("Tabla X", qf.call_args.args[1])


# ====================================================================== acceso remoto
class RemoteProsodyTests(unittest.TestCase):
	def _decode(self, name: str, values) -> object:
		return serializer.decodeSpeechItem([name, values])

	def test_valores_no_validos_se_descartan(self) -> None:
		self.assertIsNone(self._decode("PitchCommand", {"_offset": "x", "_multiplier": 1}))
		self.assertIsNone(self._decode("RateCommand", {"_offset": 0, "_multiplier": float("nan")}))
		self.assertIsNone(self._decode("VolumeCommand", {"_offset": 0, "_multiplier": float("inf")}))
		self.assertIsNone(self._decode("PitchCommand", {"_offset": True}))
		obj = serializer.deserialize(b'{"type":"speak","sequence":[["RateCommand",{"_offset":0,"_multiplier":NaN}],"hola"]}')
		self.assertEqual(obj["sequence"], ["hola"])

	def test_valores_acotados_y_aplicables(self) -> None:
		cmd = self._decode("PitchCommand", {"_offset": 1e300, "_multiplier": 1e300})
		self.assertIsInstance(cmd, cmds.PitchCommand)
		self.assertLessEqual(cmd.offset, serializer.MAX_PROSODY_OFFSET)
		self.assertLessEqual(cmd.multiplier, serializer.MAX_PROSODY_MULTIPLIER)
		self.assertEqual(cmd.applyTo(50), 100)
		normal = self._decode("PitchCommand", {"_offset": 30, "_multiplier": 1, "isDefault": False})
		self.assertEqual((normal.offset, normal.multiplier), (30, 1.0))
		brk = self._decode("BreakCommand", {"time": 10**9})
		self.assertEqual(brk.time, serializer.MAX_BREAK_MS)


class RemoteWaveTests(unittest.TestCase):
	def test_solo_wav_de_discos_locales(self) -> None:
		local = lambda root: 3  # noqa: E731  (DRIVE_FIXED)
		self.assertTrue(local_machine.isLocalWavePath(r"C:\Program Files\NVDA\waves\x.wav", local))
		for bad in (r"\\servidor\c\x.wav", "//servidor/c/x.wav", r"\x.wav", "x.wav", r"C:\x.exe", "", r"C:x.wav"):
			with self.subTest(path=bad):
				self.assertFalse(local_machine.isLocalWavePath(bad, local))
		self.assertFalse(local_machine.isLocalWavePath(r"Z:\x.wav", lambda root: local_machine.DRIVE_REMOTE))

	def test_play_wave_no_abre_rutas_de_red(self) -> None:
		machine = local_machine.TiresiasMachine(client=None)
		from tiresias.audio import tones

		with mock.patch.object(local_machine.os.path, "isfile") as isfile, mock.patch.object(tones, "playWaveFile") as play:
			machine.playWave(fileName=r"\\servidor\c\raro.wav")
		isfile.assert_not_called()
		play.assert_not_called()


class _TlsClient:
	"""Cliente TLS mínimo (sin validar: es nuestro servidor de prueba en 127.0.0.1)."""

	def __init__(self, port: int) -> None:
		ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
		ctx.check_hostname = False
		ctx.verify_mode = ssl.CERT_NONE
		raw = socket.create_connection(("127.0.0.1", port), timeout=5)
		self.sock = ctx.wrap_socket(raw, server_hostname="127.0.0.1")
		self.sock.settimeout(5)

	def send(self, obj: dict) -> None:
		self.sock.sendall(json.dumps(obj).encode() + b"\n")

	def closedByServer(self, timeout: float = 5.0) -> bool:
		self.sock.settimeout(timeout)
		try:
			while True:
				data = self.sock.recv(4096)
				if not data:
					return True
		except (ConnectionError, ssl.SSLError, OSError) as e:
			return not isinstance(e, socket.timeout)

	def close(self) -> None:
		try:
			self.sock.close()
		except OSError:
			pass


class RelayServerLimitTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		cls.certDir = tempfile.mkdtemp(prefix="tiresias_rev1011_certs_")
		cls.certs = CertificateManager(cls.certDir)

	@classmethod
	def tearDownClass(cls) -> None:
		shutil.rmtree(cls.certDir, ignore_errors=True)

	def _server(self) -> RelayServer:
		s = RelayServer(0, "clave-buena", self.certs, bindHosts=("127.0.0.1",))
		s.start()
		self.addCleanup(s.close)
		return s

	def test_sin_unirse_se_desconecta(self) -> None:
		with mock.patch.object(serverModule, "JOIN_TIMEOUT", 0.5):
			s = self._server()
			c = _TlsClient(s.port)
			self.addCleanup(c.close)
			c.send({"type": "protocol_version", "version": 2})
			self.assertTrue(c.closedByServer(6.0))
			self.assertTrue(waitFor(lambda: not s._clients))

	def test_claves_incorrectas_hacen_esperar(self) -> None:
		s = self._server()
		for _i in range(serverModule.FAIL_THRESHOLD):
			c = _TlsClient(s.port)
			c.send({"type": "join", "channel": "mala", "connection_type": "slave"})
			self.assertTrue(c.closedByServer())
			c.close()
		self.assertTrue(waitFor(lambda: s.blockedFor("127.0.0.1") > 0))
		# Mientras dura la espera, las conexiones nuevas se cierran sin saludo TLS.
		with self.assertRaises((ConnectionError, ssl.SSLError, OSError)):
			c = _TlsClient(s.port)
			try:
				c.send({"type": "join", "channel": "clave-buena", "connection_type": "slave"})
				c.sock.recv(1)
				raise ConnectionError("cerrada")
			finally:
				c.close()

	def test_clave_correcta_borra_los_fallos(self) -> None:
		s = self._server()
		c = _TlsClient(s.port)
		c.send({"type": "join", "channel": "mala", "connection_type": "slave"})
		self.assertTrue(c.closedByServer())
		c.close()
		self.assertIn("127.0.0.1", s._failures)
		good = _TlsClient(s.port)
		self.addCleanup(good.close)
		good.send({"type": "join", "channel": "clave-buena", "connection_type": "slave"})
		self.assertTrue(waitFor(lambda: s.clientCount == 1))
		self.assertNotIn("127.0.0.1", s._failures)

	def test_limite_de_conexiones(self) -> None:
		s = self._server()
		with mock.patch.object(serverModule, "MAX_CLIENTS", 1):
			first = _TlsClient(s.port)
			self.addCleanup(first.close)
			self.assertTrue(waitFor(lambda: len(s._clients) == 1))
			self.assertEqual(s._refusal("127.0.0.2"), "demasiadas conexiones")


if __name__ == "__main__":
	unittest.main()
