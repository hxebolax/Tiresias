"""Pruebas de la convivencia con otros lectores de pantalla (``tiresias.coexist``).

- Detector con funciones de sistema simuladas: NVDA instalado, portable o
  temporal; la ventana de compatibilidad de Tiresias no cuenta como NVDA;
  ``nvda_slave.exe`` tampoco; copias de otro usuario (escritorio seguro);
  JAWS solo por su ventana; Narrador con su indicador del registro.
- Filtro de sondeos (``Debouncer``) y máquina de estados (``Coexistence``).
- Lectores falsos de verdad: una copia de Python llamada ``nvda.exe`` o
  ``jfw.exe`` con la ventana del lector, que la prueba abre y cierra (el
  NVDA real del equipo no se toca).
- Auxiliar del punto de conexión de NVDA (``tiresiasNvdaWindow.exe``):
  reenvío a Tiresias, marcas SSML y liberación del punto al cerrarse
  (``coexist_bridge_probe.py``, en un escritorio propio).

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias.coexist import detect, state  # noqa: E402
from tiresias.coexist.detect import Detector, ProcessEntry, ReaderInfo  # noqa: E402

OWN_SESSION = 1


def _detector(procs, windows=None, ownUser=None, sessions=None, narrator=None, paths=None):
	windows = windows or {}
	return Detector(
		processes=lambda: list(procs),
		windows=lambda cls, title: list(windows.get((cls, title), [])),
		session=lambda pid: (sessions or {}).get(pid, OWN_SESSION),
		ownUser=lambda pid: (ownUser or {}).get(pid, True),
		imagePath=lambda pid: (paths or {}).get(pid, ""),
		narratorState=lambda: narrator,
		ownSession=OWN_SESSION,
		excludePids={1},
	)


NVDA_WIN = ("wxWindowClassNR", "NVDA")
JAWS_WIN = ("JFWUI2", None)


class DetectorTests(unittest.TestCase):
	def test_nvda_proceso_y_ventana(self):
		d = _detector([ProcessEntry(100, "nvda.exe", 4)], {NVDA_WIN: [(9, 100)]}, paths={100: r"C:\Program Files\NVDA\nvda.exe"})
		readers = d.detect()
		self.assertEqual([r.id for r in readers], ["nvda"])
		self.assertTrue(readers[0].ready)
		self.assertEqual(readers[0].pid, 100)

	def test_ventana_de_tiresias_no_es_nvda(self):
		# La ventana «NVDA» del auxiliar de Tiresias no cuenta.
		d = _detector([ProcessEntry(200, "tiresiasnvdawindow.exe", 1)], {NVDA_WIN: [(9, 200)]})
		self.assertEqual(d.detect(), [])

	def test_procesos_auxiliares_de_nvda(self):
		procs = [ProcessEntry(300, "nvda_slave.exe", 4), ProcessEntry(301, "nvdahelperremoteloader.exe", 4), ProcessEntry(302, "nvda_eoaproxy.exe", 4)]
		self.assertEqual(_detector(procs).detect(), [])

	def test_nvda_arrancando_sin_ventana(self):
		d = _detector([ProcessEntry(100, "nvda.exe", 4)])
		r = d.detect()[0]
		self.assertFalse(r.ready)

	def test_copia_de_otro_usuario_o_sesion(self):
		# Copia de SYSTEM en el escritorio seguro y copia de otra sesión.
		d = _detector([ProcessEntry(100, "nvda.exe", 4), ProcessEntry(101, "nvda.exe", 4)], ownUser={100: False}, sessions={101: 2})
		self.assertEqual(d.detect(), [])

	def test_sin_acceso_al_proceso_cuenta_con_ventana(self):
		procs = [ProcessEntry(100, "jfw.exe", 4)]
		self.assertEqual(_detector(procs, ownUser={100: None}).detect(), [])
		readers = _detector(procs, {JAWS_WIN: [(5, 100)]}, ownUser={100: None}).detect()
		self.assertEqual([(r.id, r.ready) for r in readers], [("jaws", True)])

	def test_narrador_y_registro(self):
		procs = [ProcessEntry(400, "narrator.exe", 4)]
		self.assertFalse(_detector(procs, narrator=False).detect()[0].ready)
		self.assertTrue(_detector(procs, narrator=True).detect()[0].ready)
		# El indicador solo (Narrador cerrado de golpe) no cuenta.
		self.assertEqual(_detector([], narrator=True).detect(), [])

	def test_lista_de_lectores_y_orden(self):
		procs = [ProcessEntry(400, "narrator.exe", 4), ProcessEntry(100, "nvda.exe", 4), ProcessEntry(500, "jfw.exe", 4)]
		d = _detector(procs)
		self.assertEqual([r.id for r in d.detect()], ["nvda", "jaws", "narrator"])
		self.assertEqual([r.id for r in d.detect(["jaws"])], ["jaws"])
		self.assertEqual(state.primaryReader(d.detect(["narrator", "jaws"])).id, "jaws")

	def test_instalado_portable_temporal(self):
		dirs = [os.path.normcase(r"C:\Program Files\NVDA")]
		self.assertEqual(detect.classifyNvda(r"C:\Program Files\NVDA\nvda.exe", dirs), "instalado")
		self.assertEqual(detect.classifyNvda(r"D:\Portables\NVDA\nvda.exe", dirs), "portable")
		temp = os.environ.get("TEMP", r"C:\Temp")
		self.assertEqual(detect.classifyNvda(os.path.join(temp, "nvda_abc", "nvda.exe"), dirs), "copia temporal")

	def test_proceso_propio_excluido(self):
		d = _detector([ProcessEntry(1, "nvda.exe", 4)])
		self.assertEqual(d.detect(), [])


def _r(rid: str, ready: bool = False, pid: int = 100) -> ReaderInfo:
	return ReaderInfo(rid, detect.SPECS[rid].name, pid, ready=ready)


class DebouncerTests(unittest.TestCase):
	def test_aparece_y_desaparece_con_dos_sondeos(self):
		d = state.Debouncer()
		self.assertFalse(d.update([_r("nvda")]))
		self.assertTrue(d.update([_r("nvda")]))
		self.assertIn("nvda", d.stable)
		self.assertFalse(d.update([]))
		self.assertIn("nvda", d.stable)
		self.assertTrue(d.update([]))
		self.assertEqual(d.stable, {})

	def test_listo_cuenta_enseguida(self):
		d = state.Debouncer()
		self.assertTrue(d.update([_r("jaws", ready=True)]))

	def test_parpadeo_no_cambia_nada(self):
		# Un «nvda -k» de un instante o un reinicio rápido de NVDA.
		d = state.Debouncer()
		d.reset([_r("nvda", True)])
		self.assertFalse(d.update([]))
		self.assertFalse(d.update([_r("nvda", True, pid=101)]))
		self.assertEqual(d.stable["nvda"].pid, 101)
		e = state.Debouncer()
		self.assertFalse(e.update([_r("nvda")]))
		self.assertFalse(e.update([]))
		self.assertEqual(e.stable, {})


class _Actions:
	def __init__(self) -> None:
		self.calls: list = []

	def goStandby(self, reader, initial):
		self.calls.append(("standby", reader.id, initial))

	def goActive(self, reason, reader):
		self.calls.append(("active", reason, reader.id if reader else None))


class MachineTests(unittest.TestCase):
	def setUp(self):
		self.a = _Actions()
		self.m = state.Coexistence(self.a)

	def test_arranque_en_espera_y_cierre_del_lector(self):
		self.assertEqual(self.m.start([_r("nvda", True)], True), state.STANDBY)
		self.assertEqual(self.a.calls, [("standby", "nvda", True)])
		self.m.onReaders([_r("nvda", True)])
		self.assertEqual(len(self.a.calls), 1)
		self.m.onReaders([])
		self.assertEqual(self.a.calls[-1], ("active", state.REASON_READER_CLOSED, "nvda"))
		self.assertFalse(self.m.isStandby)

	def test_arranque_sin_otro_lector(self):
		self.assertEqual(self.m.start([], True), state.ACTIVE)
		self.assertEqual(self.a.calls, [])

	def test_cede_cuando_se_abre_otro_lector(self):
		self.m.start([], True)
		self.m.onReaders([_r("jaws", True)])
		self.assertEqual(self.a.calls, [("standby", "jaws", False)])
		self.assertEqual(self.m.reader.id, "jaws")

	def test_opcion_desactivada(self):
		self.assertEqual(self.m.start([_r("nvda", True)], False), state.ACTIVE)
		self.m.onReaders([_r("nvda", True)])
		self.assertEqual(self.a.calls, [])
		# Al activar la opción, cede.
		self.m.setYieldEnabled(True)
		self.assertEqual(self.a.calls, [("standby", "nvda", False)])
		# Y al desactivarla en espera, se activa.
		self.m.setYieldEnabled(False)
		self.assertEqual(self.a.calls[-1], ("active", state.REASON_OPTION_OFF, "nvda"))
		# Volver a fijar el mismo valor no hace nada.
		self.m.setYieldEnabled(False)
		self.assertEqual(len(self.a.calls), 2)

	def test_forzar_y_volver_a_ceder(self):
		self.m.start([_r("nvda", True)], True)
		self.assertTrue(self.m.force())
		self.assertEqual(self.a.calls[-1], ("active", state.REASON_FORCED, "nvda"))
		self.assertTrue(self.m.forced)
		# Forzado: aunque siga NVDA (o se abra JAWS) no cede.
		self.m.onReaders([_r("nvda", True), _r("jaws", True)])
		self.assertFalse(self.m.isStandby)
		self.assertTrue(self.m.yieldNow())
		self.assertEqual(self.a.calls[-1], ("standby", "nvda", False))
		self.assertFalse(self.m.forced)

	def test_forzado_se_olvida_al_cerrarse_el_lector(self):
		self.m.start([_r("nvda", True)], True, forced=True)
		self.assertFalse(self.m.isStandby)
		self.assertTrue(self.m.forced)
		self.m.onReaders([])
		self.assertFalse(self.m.forced)
		# La próxima vez que se abra, cede.
		self.m.onReaders([_r("nvda", True)])
		self.assertEqual(self.a.calls[-1], ("standby", "nvda", False))

	def test_ceder_sin_otro_lector(self):
		self.m.start([], True)
		self.assertFalse(self.m.yieldNow())
		self.assertFalse(self.m.force())
		self.assertEqual(self.a.calls, [])


def _makeFakeExe(folder: str, name: str) -> str:
	"""Copia del intérprete de Python con el nombre de un lector."""
	base = getattr(sys, "_base_executable", sys.executable)
	baseDir = os.path.dirname(base)
	exe = os.path.join(folder, name)
	shutil.copy2(base, exe)
	for dll in os.listdir(baseDir):
		low = dll.lower()
		if low.endswith(".dll") and (low.startswith("python3") or low.startswith("vcruntime")) and "_d" not in low and "t." not in low:
			shutil.copy2(os.path.join(baseDir, dll), os.path.join(folder, dll))
	return exe


class FakeReaderTests(unittest.TestCase):
	"""Lectores falsos de verdad (procesos y ventanas) que la prueba abre y cierra."""

	@classmethod
	def setUpClass(cls):
		cls.tmp = tempfile.mkdtemp(prefix="tiresias_lectores_")
		try:
			cls.nvdaExe = _makeFakeExe(cls.tmp, "nvda.exe")
			cls.jawsExe = _makeFakeExe(cls.tmp, "jfw.exe")
		except OSError as e:
			raise unittest.SkipTest(f"No se pudo preparar el lector falso: {e}")

	@classmethod
	def tearDownClass(cls):
		shutil.rmtree(cls.tmp, ignore_errors=True)

	def _start(self, exe: str, cls: str, title: str) -> subprocess.Popen:
		env = dict(os.environ)
		env["PYTHONHOME"] = sys.base_prefix
		env.pop("PYTHONPATH", None)
		proc = subprocess.Popen(
			[exe, "-X", "utf8", os.path.join(ROOT, "tests", "fake_reader.py"), cls, title, "60"],
			stdin=subprocess.PIPE,
			stdout=subprocess.PIPE,
			env=env,
			creationflags=0x08000000,
		)
		line = proc.stdout.readline().decode().strip()
		if line != "listo":
			proc.kill()
			self.skipTest("El lector falso no arrancó")
		return proc

	def _stop(self, proc: subprocess.Popen) -> None:
		try:
			proc.stdin.close()
			proc.wait(5)
		except Exception:
			proc.kill()
		proc.stdout.close()

	def _onlyPid(self, pid: int) -> Detector:
		# Solo el proceso falso: el NVDA real del equipo no interviene.
		return Detector(processes=lambda: [p for p in detect.listProcesses() if p.pid == pid])

	def test_nvda_falso_abrir_y_cerrar(self):
		proc = self._start(self.nvdaExe, "wxWindowClassNR", "NVDA")
		try:
			det = self._onlyPid(proc.pid)
			readers = det.detect()
			self.assertEqual([(r.id, r.pid, r.ready) for r in readers], [("nvda", proc.pid, True)])
			# Está en la carpeta temporal, como la copia que arranca el instalador de NVDA.
			self.assertEqual(readers[0].detail, "copia temporal")
			# Vigilancia + máquina de estados: arranca en espera y se activa al cerrarse.
			actions = _Actions()
			machine = state.Coexistence(actions)
			deb = state.Debouncer()
			deb.reset(readers)
			machine.start(readers, True)
			self.assertTrue(machine.isStandby)
		finally:
			self._stop(proc)
		for _i in range(2):
			if deb.update(det.detect()):
				machine.onReaders(list(deb.stable.values()))
		self.assertFalse(machine.isStandby)
		self.assertEqual(actions.calls, [("standby", "nvda", True), ("active", state.REASON_READER_CLOSED, "nvda")])

	def test_jaws_falso(self):
		proc = self._start(self.jawsExe, "JFWUI2", "JAWS")
		try:
			readers = self._onlyPid(proc.pid).detect()
			self.assertEqual([(r.id, r.ready) for r in readers], [("jaws", True)])
		finally:
			self._stop(proc)
		self.assertEqual(self._onlyPid(proc.pid).detect(), [])

	def test_ventana_nvda_de_otro_programa(self):
		# Una ventana «NVDA» de un programa que no es NVDA (como la de Tiresias) no cuenta.
		proc = self._start(self.jawsExe, "wxWindowClassNR", "NVDA")
		try:
			self.assertEqual(self._onlyPid(proc.pid).detect([detect.NVDA]), [])
		finally:
			self._stop(proc)


BRIDGE = os.path.join(ROOT, "data", "controller", "x64", "tiresiasNvdaWindow.exe")


@unittest.skipUnless(os.path.isfile(BRIDGE), "Falta tiresiasNvdaWindow.exe (python controller/build.py)")
class BridgeTests(unittest.TestCase):
	def test_reenvio_y_liberacion(self):
		out = subprocess.run(
			[sys.executable, "-X", "utf8", os.path.join(ROOT, "tests", "coexist_bridge_probe.py")],
			capture_output=True,
			text=True,
			encoding="utf-8",
			timeout=90,
		)
		lines = [ln for ln in out.stdout.splitlines() if ln.startswith("{")]
		self.assertTrue(lines, out.stdout + out.stderr)
		r = json.loads(lines[-1])
		if r.get("error") in ("CreateDesktop", "server.start", "listen"):
			self.skipTest(f"Sin entorno para la prueba: {r['error']}")
		self.assertTrue(r["ok"], r)
		own = r["ownPid"]
		self.assertEqual(r["testIfRunning"], 0)
		self.assertEqual(r["speakText"], 0)
		self.assertEqual(r["getProcessId"], [0, own])
		self.assertEqual(r["isSpeaking"], [0, 1])
		self.assertEqual(r["marks"], ["uno", "dos"])
		self.assertEqual(r["ssmlAsync"], 0)
		self.assertEqual(r["denied"], 5)  # ERROR_ACCESS_DENIED
		self.assertNotEqual(r["afterClose"], 0)
		self.assertEqual(r["window"], ["wxWindowClassNR", "NVDA"])
		self.assertEqual(r["quitExit"], 0)
		self.assertNotEqual(r["afterQuit"], 0)
		self.assertEqual(r["relisten"], 0)
		self.assertIn(["speakText", own, "hola desde el puente"], r["calls"])


class AnnouncerTests(unittest.TestCase):
	def test_notificacion_uia_para_narrador(self):
		# Un cliente UIA de otro proceso (como Narrador) recibe la notificación.
		out = subprocess.run(
			[sys.executable, "-X", "utf8", os.path.join(ROOT, "tests", "coexist_uia_probe.py")],
			capture_output=True,
			text=True,
			encoding="utf-8",
			timeout=90,
		)
		lines = [ln for ln in out.stdout.splitlines() if ln.startswith("{")]
		self.assertTrue(lines, out.stdout + out.stderr)
		r = json.loads(lines[-1])
		self.assertTrue(r["emitted"], r)
		self.assertEqual(len(r["received"]), 1, r)
		kind, processing, _text, activity, name = r["received"][0]
		self.assertEqual((kind, processing, activity, name), (4, 0, "Tiresias.Convivencia", "Tiresias"))

	def test_tono_si_no_hay_camino(self):
		from tiresias.coexist import announce

		played = []
		orig = announce.playTone
		announce.playTone = lambda: played.append(True)
		try:
			path = announce.Announcer.deliver(_r("dolphin"), "hola", lambda: True, 0.1)
		finally:
			announce.playTone = orig
		self.assertEqual(path, announce.PATH_TONE)
		self.assertEqual(played, [True])

	def test_no_anuncia_si_ya_no_vale(self):
		from tiresias.coexist import announce

		self.assertEqual(announce.Announcer.deliver(_r("nvda"), "hola", lambda: False, 0.1), announce.PATH_NONE)


if __name__ == "__main__":
	unittest.main()
