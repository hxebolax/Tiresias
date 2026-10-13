"""Pruebas del lector recordado y del guardián (``tiresias.coexist.relaunch`` y ``.guardian``).

- Máquina de decisiones: salida del usuario → relanzar; reinicio → esperar a
  la copia nueva (y relanzar si no llega); fallo → relanzar; lector ya en
  ejecución → nada; bloqueo del núcleo → relanzar una vez.
- Archivo del lector recordado, cómo se inicia cada lector, marcadores de
  salida y latido en memoria compartida.
- Lógica del guardián con un sistema simulado.
- Guardián de verdad (proceso ``--guardian``) con un «Tiresias» de mentira y
  un **NVDA falso**: una copia de ``pythonw.exe`` llamada ``nvda.exe`` que
  ejecuta ``tests/fake_reader.py`` con la ventana ``wxWindowClassNR``/«NVDA».
- Integración con Tiresias de verdad (``--no-input --no-replace --minimal``
  y ``TIRESIAS_COEXIST_TEST=1``): arranca en espera con el NVDA falso, se
  activa al cerrarlo y luego a) ``--quit``: el guardián inicia el NVDA falso;
  b) ``TerminateProcess`` (cierre nativo): lo inicia; c) reinicio: no lo
  inicia. Todo lo que se lanza se cierra al terminar.

El NVDA real del equipo nunca se inicia ni se cierra: sus procesos se pasan
en ``TIRESIAS_COEXIST_IGNORE_PIDS`` y el lector recordado es siempre el falso.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias.coexist import detect, guardian, relaunch  # noqa: E402
from tiresias.coexist.detect import ReaderInfo  # noqa: E402

PYTHON = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
if not os.path.isfile(PYTHON):
	PYTHON = sys.executable
ENTRY = os.path.join(ROOT, "src", "tiresias.pyw")
FAKE_READER = os.path.join(ROOT, "tests", "fake_reader.py")
#: Intérprete base (sin el lanzador del entorno virtual): su PID es el del proceso que ejecuta el código.
BASE_PYTHON = getattr(sys, "_base_executable", sys.executable)
NO_WINDOW = 0x08000000
READER_NAMES = frozenset().union(*(s.processes for s in detect.READERS))


# ====================================================================== decisiones
class DecisionTests(unittest.TestCase):
	def d(self, kind, enabled=True, hasReader=True, running=False):
		return relaunch.decideExit(kind, enabled=enabled, hasReader=hasReader, readerRunning=running)

	def test_salida_del_usuario_relanza(self):
		self.assertEqual(self.d(relaunch.EXIT_USER), relaunch.ACTION_LAUNCH)

	def test_fallo_relanza(self):
		self.assertEqual(self.d(relaunch.EXIT_ERROR), relaunch.ACTION_LAUNCH)

	def test_reinicio_espera_a_la_copia_nueva(self):
		self.assertEqual(self.d(relaunch.EXIT_RESTART), relaunch.ACTION_WAIT)
		self.assertEqual(self.d(relaunch.EXIT_REPLACED), relaunch.ACTION_WAIT)
		ok = relaunch.decideAfterWait(True, enabled=True, hasReader=True, readerRunning=False)
		self.assertEqual(ok, relaunch.ACTION_NONE)
		# La copia nueva no ha arrancado: se trata como un fallo.
		failed = relaunch.decideAfterWait(False, enabled=True, hasReader=True, readerRunning=False)
		self.assertEqual(failed, relaunch.ACTION_LAUNCH)

	def test_lector_ya_en_ejecucion(self):
		self.assertEqual(self.d(relaunch.EXIT_USER, running=True), relaunch.ACTION_NONE)
		self.assertEqual(self.d(relaunch.EXIT_ERROR, running=True), relaunch.ACTION_NONE)

	def test_opcion_desactivada_o_sin_lector(self):
		self.assertEqual(self.d(relaunch.EXIT_USER, enabled=False), relaunch.ACTION_NONE)
		self.assertEqual(self.d(relaunch.EXIT_ERROR, hasReader=False), relaunch.ACTION_NONE)
		self.assertEqual(self.d(relaunch.EXIT_RESTART, hasReader=False), relaunch.ACTION_NONE)

	def test_actualizacion_y_volver_al_lector(self):
		self.assertEqual(self.d(relaunch.EXIT_UPDATE), relaunch.ACTION_NONE)
		self.assertEqual(self.d(relaunch.EXIT_SWITCH), relaunch.ACTION_NONE)

	def test_bloqueo(self):
		def h(stale, **kw):
			args = dict(timeout=20, enabled=True, hasReader=True, readerRunning=False, alreadyLaunched=False)
			args.update(kw)
			return relaunch.decideHang(stale, **args)

		self.assertEqual(h(5), relaunch.ACTION_NONE)
		self.assertEqual(h(21), relaunch.ACTION_LAUNCH)
		self.assertEqual(h(21, readerRunning=True), relaunch.ACTION_NONE)
		self.assertEqual(h(21, alreadyLaunched=True), relaunch.ACTION_NONE)
		self.assertEqual(h(21, enabled=False), relaunch.ACTION_NONE)


# ====================================================================== archivo, rutas, marcadores, latido
class MemoryTests(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.mkdtemp(prefix="tiresias_recordado_")
		self.path = os.path.join(self.tmp, "config", relaunch.MEMORY_FILE)

	def tearDown(self):
		shutil.rmtree(self.tmp, ignore_errors=True)

	def test_recordar_olvidar_y_opciones(self):
		self.assertIsNone(relaunch.loadMemory(self.path)["reader"])
		info = ReaderInfo("nvda", "NVDA", 10, "instalado", True, r"C:\Program Files\NVDA\nvda.exe")
		self.assertTrue(relaunch.rememberReader(info, self.path))
		self.assertFalse(relaunch.rememberReader(info, self.path))
		mem = relaunch.loadMemory(self.path)
		self.assertEqual(mem["reader"]["path"], r"C:\Program Files\NVDA\nvda.exe")
		self.assertEqual(relaunch.readerLabel(mem["reader"]), "NVDA (instalado)")
		self.assertTrue(relaunch.saveOptions({"relaunchOnExit": False, "hangTimeout": 3, "readers": ["nvda"]}, self.path))
		mem = relaunch.loadMemory(self.path)
		self.assertFalse(mem["options"]["relaunchOnExit"])
		# El tiempo se recorta al mínimo permitido al leerlo.
		self.assertEqual(mem["options"]["hangTimeout"], relaunch.HANG_TIMEOUT_RANGE[0])
		self.assertEqual(mem["reader"]["id"], "nvda")
		self.assertTrue(relaunch.forgetReader(self.path))
		self.assertIsNone(relaunch.loadMemory(self.path)["reader"])
		self.assertFalse(relaunch.loadMemory(self.path)["options"]["relaunchOnExit"])

	def test_conserva_argumentos_y_ruta(self):
		exe = os.path.join(self.tmp, "nvda.exe")
		relaunch.saveMemory({"reader": {"id": "nvda", "name": "NVDA", "path": exe, "args": ["-m"]}}, self.path)
		relaunch.rememberReader(ReaderInfo("nvda", "NVDA", 1, "portable", True, exe), self.path)
		self.assertEqual(relaunch.loadMemory(self.path)["reader"]["args"], ["-m"])
		# Sin ruta (proceso protegido): se conserva la anterior.
		relaunch.rememberReader(ReaderInfo("nvda", "NVDA", 1, "", True, ""), self.path)
		self.assertEqual(relaunch.loadMemory(self.path)["reader"]["path"], exe)
		# Otro lector: se sustituye por completo.
		relaunch.rememberReader(ReaderInfo("jaws", "JAWS", 2, "", True, r"C:\JAWS\jfw.exe"), self.path)
		reader = relaunch.loadMemory(self.path)["reader"]
		self.assertEqual((reader["id"], reader["path"], reader["args"]), ("jaws", r"C:\JAWS\jfw.exe", []))

	def test_archivo_danado(self):
		os.makedirs(os.path.dirname(self.path))
		with open(self.path, "w", encoding="utf-8") as f:
			f.write("{no es json")
		mem = relaunch.loadMemory(self.path)
		self.assertIsNone(mem["reader"])
		self.assertTrue(mem["options"]["relaunchOnExit"])

	def test_candidatos_de_inicio(self):
		existing = {
			os.path.normcase(r"C:\NVDA\nvda.exe"),
			os.path.normcase(r"C:\Program Files\NVDA\nvda.exe"),
			os.path.normcase(r"C:\JAWS\jfw.exe"),
			os.path.normcase(relaunch.narratorPath()),
		}

		def exists(p):
			return os.path.normcase(p) in existing

		def cands(reader, dirs=()):
			return relaunch.launchCandidates(reader, installDirs=list(dirs), exists=exists)

		# Variante uiAccess de la copia instalada: antes, nvda.exe de la misma carpeta.
		self.assertEqual(cands({"id": "nvda", "path": r"C:\NVDA\nvda_uiAccess.exe"}), [r"C:\NVDA\nvda.exe"])
		# Copia temporal que ya no existe: el NVDA instalado.
		self.assertEqual(cands({"id": "nvda", "path": r"C:\Temp\x\nvda.exe"}, [r"C:\Program Files\NVDA"]), [r"C:\Program Files\NVDA\nvda.exe"])
		self.assertEqual(cands({"id": "jaws", "path": r"C:\JAWS\jfw.exe"}), [r"C:\JAWS\jfw.exe"])
		self.assertEqual(cands({"id": "narrator", "path": ""}), [relaunch.narratorPath()])
		self.assertEqual(cands({"id": "jaws", "path": r"C:\no\jfw.exe"}), [])
		self.assertEqual(cands(None), [])
		# La ruta recordada existe: no se ofrece ninguna otra.
		self.assertEqual(cands({"id": "nvda", "path": r"C:\NVDA\nvda.exe"}, [r"C:\Program Files\NVDA"]), [r"C:\NVDA\nvda.exe"])
		os.environ["TIRESIAS_RELAUNCH_NO_FALLBACK"] = "1"
		try:
			self.assertEqual(cands({"id": "nvda", "path": r"C:\Temp\x\nvda.exe"}, [r"C:\Program Files\NVDA"]), [])
		finally:
			del os.environ["TIRESIAS_RELAUNCH_NO_FALLBACK"]

	def test_argumentos_solo_para_su_ejecutable(self):
		from unittest import mock

		calls = []
		reader = {"id": "nvda", "name": "NVDA", "path": r"C:\Temp\x\nvda.exe", "args": ["-X"]}
		installed = r"C:\Program Files\NVDA\nvda.exe"
		with mock.patch.object(relaunch, "launchCandidates", return_value=[installed]), mock.patch.object(
			relaunch, "launchExecutable", side_effect=lambda exe, args: calls.append((exe, tuple(args))) or 77
		):
			self.assertEqual(relaunch.launchReader(reader), 77)
		self.assertEqual(calls, [(installed, ())])

	def test_marcadores(self):
		self.assertIsNone(relaunch.readMarker(1234, self.tmp))
		relaunch.writeMarker(relaunch.EXIT_RESTART, 1234, self.tmp)
		self.assertEqual(relaunch.readMarker(1234, self.tmp), relaunch.EXIT_RESTART)
		self.assertEqual(relaunch.readMarker(1234, self.tmp, remove=True), relaunch.EXIT_RESTART)
		self.assertIsNone(relaunch.readMarker(1234, self.tmp))
		relaunch.writeMarker("algo raro", 1234, self.tmp)
		self.assertEqual(relaunch.readMarker(1234, self.tmp, remove=True), relaunch.EXIT_ERROR)

	def test_latido_en_memoria_compartida(self):
		pid = 4_000_000 + os.getpid()  # nombre propio de la prueba
		reader = relaunch.HeartbeatReader(pid)
		self.assertIsNone(reader.read())
		hb = relaunch.Heartbeat(pid)
		try:
			armed, stale = reader.read()
			self.assertFalse(armed)
			hb.beat()
			armed, stale = reader.read()
			self.assertTrue(armed)
			self.assertLess(stale, 1.0)
			time.sleep(0.3)
			self.assertGreaterEqual(reader.read()[1], 0.25)
		finally:
			reader.close()
			hb.close()

	def test_objetos_con_nombre(self):
		pid = 4_100_000 + os.getpid()
		self.assertFalse(relaunch.wasReplaced(pid))
		h = relaunch.markReplacing(pid)
		try:
			self.assertTrue(relaunch.wasReplaced(pid))
		finally:
			relaunch.closeHandle(h)
		self.assertFalse(relaunch.wasReplaced(pid))
		self.assertFalse(relaunch.isGuardianRunning(pid))
		m = relaunch.createGuardianMutex(pid)
		self.assertTrue(relaunch.isGuardianRunning(pid))
		relaunch.closeHandle(m)
		self.assertTrue(relaunch.waitGuardianGone(pid, 1.0))

	def test_constantes_del_nucleo(self):
		from tiresias import core

		self.assertEqual(relaunch.INSTANCE_MUTEX, core.MUTEX_NAME)
		self.assertEqual(relaunch.MAIN_WINDOW_TITLE, core.MAIN_WINDOW_TITLE)

	def test_solo_lectores_de_la_carpeta_de_pruebas(self):
		paths_ = {10: r"C:\Program Files\NVDA\nvda.exe", 11: r"C:\pruebas\x\nvda.exe"}
		det = detect.Detector(
			processes=lambda: [detect.ProcessEntry(10, "nvda.exe", 1), detect.ProcessEntry(11, "nvda.exe", 1)],
			windows=lambda cls, title: [(1, 10), (2, 11)],
			session=lambda pid: 1,
			ownUser=lambda pid: True,
			imagePath=lambda pid: paths_[pid],
			narratorState=lambda: None,
			ownSession=1,
			excludePids=set(),
			onlyDir=r"C:\pruebas",
		)
		self.assertEqual([(r.pid, r.path) for r in det.detect(["nvda"])], [(11, paths_[11])])
		det.onlyDir = ""
		self.assertEqual(len(det.detect(["nvda"])), 1)

	def test_orden_del_guardian(self):
		cmd = guardian.guardianCommand(123, r"C:\datos")
		self.assertEqual(cmd[-4:], ["--guardian", "123", "--data", r"C:\datos"])
		self.assertEqual(guardian.parseGuardianArgs(["--guardian", "123", "--data", r"C:\datos"]), (123, os.path.abspath(r"C:\datos")))

	def test_salida_volver_al_lector(self):
		from unittest import mock

		relaunch.saveMemory({"reader": {"id": "nvda", "name": "NVDA", "path": r"C:\x\nvda.exe"}}, relaunch.memoryPath(self.tmp))
		pid = os.getpid()
		with mock.patch.object(guardian, "_started", True), mock.patch.object(guardian, "_dataDir", self.tmp), mock.patch.object(guardian, "_heartbeat", None), mock.patch.object(
			relaunch, "anyReaderRunning", return_value=[]
		), mock.patch.object(relaunch, "endHelpers"):
			for launched, expected in ((1234, relaunch.EXIT_SWITCH), (0, relaunch.EXIT_USER)):
				with mock.patch.object(relaunch, "launchReader", return_value=launched) as launch, mock.patch.object(guardian, "_exitKind", relaunch.EXIT_SWITCH):
					self.assertEqual(guardian.onProcessExit(False, True), expected)
					launch.assert_called_once()
				# Si no se pudo iniciar, el guardián lo intentará como en una salida normal.
				self.assertEqual(relaunch.readMarker(pid, self.tmp, remove=True), expected)
			# Un reinicio manda sobre todo lo demás.
			with mock.patch.object(guardian, "_exitKind", relaunch.EXIT_UPDATE):
				self.assertEqual(guardian.onProcessExit(True, True), relaunch.EXIT_RESTART)
			self.assertEqual(relaunch.readMarker(pid, self.tmp, remove=True), relaunch.EXIT_RESTART)
			# Fin inesperado: sin marcador.
			self.assertEqual(guardian.onProcessExit(False, False), relaunch.EXIT_ERROR)
			self.assertIsNone(relaunch.readMarker(pid, self.tmp))

	def test_red_de_seguridad_de_la_actualizacion(self):
		from unittest import mock

		target = self.tmp
		self.assertEqual(guardian.afterUpdateLaunch(target, timeout=5), relaunch.ACTION_NONE)  # sin lector recordado
		relaunch.saveMemory({"reader": {"id": "nvda", "name": "NVDA", "path": r"C:\x\nvda.exe"}}, relaunch.memoryPath(os.path.join(target, "data")))
		with mock.patch.object(relaunch, "anyReaderRunning", return_value=[]), mock.patch.object(relaunch, "launchReader", return_value=1) as launch:
			with mock.patch.object(relaunch, "instanceRunning", return_value=True):
				self.assertEqual(guardian.afterUpdateLaunch(target, timeout=5), relaunch.ACTION_NONE)
			launch.assert_not_called()
			# La copia actualizada no arranca: el lector recordado.
			with mock.patch.object(relaunch, "instanceRunning", return_value=False):
				self.assertEqual(guardian.afterUpdateLaunch(target, timeout=0.2), relaunch.ACTION_LAUNCH)
			launch.assert_called_once()

	def test_sin_guardian_en_pruebas_automaticas(self):
		from types import SimpleNamespace
		from unittest import mock

		names = ("TIRESIAS_GUARDIAN_TEST", "TIRESIAS_NO_GUARDIAN", "TIRESIAS_COEXIST_IGNORE_PIDS", "TIRESIAS_COEXIST_ONLY_DIR")
		clean = {k: v for k, v in os.environ.items() if k not in names}
		with mock.patch.dict(os.environ, clean, clear=True):
			self.assertFalse(guardian.shouldStart(SimpleNamespace(exit_after=5)))
			self.assertTrue(guardian.shouldStart(SimpleNamespace(exit_after=0)))
			# Pruebas con lectores falsos (otras pruebas de convivencia): sin guardián.
			os.environ["TIRESIAS_COEXIST_IGNORE_PIDS"] = "123"
			self.assertFalse(guardian.shouldStart(SimpleNamespace(exit_after=0)))
			# Salvo que se pida.
			os.environ["TIRESIAS_GUARDIAN_TEST"] = "1"
			self.assertTrue(guardian.shouldStart(SimpleNamespace(exit_after=5)))
			os.environ["TIRESIAS_NO_GUARDIAN"] = "1"
			self.assertFalse(guardian.shouldStart(SimpleNamespace(exit_after=0)))
			# Y entonces nunca se recurre a otra ruta (el NVDA real).
			installed = r"C:\Program Files\NVDA"
			reader = {"id": "nvda", "path": r"C:\no\existe\nvda.exe"}
			self.assertEqual(relaunch.launchCandidates(reader, installDirs=[installed], exists=lambda p: p.startswith(installed)), [])


# ====================================================================== guardián con sistema simulado
class FakeOps:
	def __init__(self, marker=None, reader=True, running=False, replaced=False, successorAfter=None, aliveFor=0.0, heartbeat=None, options=None):
		self.marker = marker
		self.reader = {"id": "nvda", "name": "NVDA", "path": r"C:\NVDA\nvda.exe"} if reader else None
		self.running = running
		self.replaced = replaced
		self.successorAfter = successorAfter
		self.aliveFor = aliveFor
		self.heartbeats = list(heartbeat or [])
		self.options = dict(relaunch.DEFAULT_OPTIONS, readers=["nvda"])
		self.options.update(options or {})
		self.t = 0.0
		self.launched: list[dict] = []
		self.helpersEnded = 0
		self.markerTaken = False

	def openProcess(self):
		return object()

	def waitProcess(self, handle, timeout):
		self.t += timeout
		return self.t >= self.aliveFor

	def closeProcess(self, handle):
		pass

	def peekMarker(self):
		return None if self.markerTaken else self.marker

	def takeMarker(self):
		self.markerTaken = True
		return self.marker

	def wasReplaced(self):
		return self.replaced

	def successorRunning(self):
		return self.successorAfter is not None and self.t >= self.successorAfter

	def loadMemory(self):
		return {"reader": self.reader, "options": dict(self.options)}

	def readerRunning(self, memory):
		return self.running

	def heartbeat(self):
		return self.heartbeats.pop(0) if self.heartbeats else None

	def shuttingDown(self):
		return False

	def endHelpers(self, logger):
		self.helpersEnded += 1

	def launch(self, reader, logger):
		self.launched.append(reader)
		return 4321

	def now(self):
		return self.t

	def sleep(self, seconds):
		self.t += seconds


class GuardianLogicTests(unittest.TestCase):
	def run_(self, **kw):
		ops = FakeOps(**kw)
		action = guardian.Guardian(ops).run()
		return ops, action

	def test_salida_del_usuario(self):
		ops, action = self.run_(marker=relaunch.EXIT_USER)
		self.assertEqual(action, relaunch.ACTION_LAUNCH)
		self.assertEqual(len(ops.launched), 1)
		# NVDA: antes se asegura de que el auxiliar de compatibilidad ha terminado.
		self.assertEqual(ops.helpersEnded, 1)

	def test_cierre_nativo_sin_marcador(self):
		ops, action = self.run_(marker=None)
		self.assertEqual(action, relaunch.ACTION_LAUNCH)

	def test_lector_ya_en_ejecucion(self):
		ops, action = self.run_(marker=None, running=True)
		self.assertEqual((action, ops.launched), (relaunch.ACTION_NONE, []))

	def test_reinicio_con_copia_nueva(self):
		ops, action = self.run_(marker=relaunch.EXIT_RESTART, successorAfter=1.0)
		self.assertEqual((action, ops.launched), (relaunch.ACTION_NONE, []))

	def test_reinicio_que_no_llega(self):
		ops, action = self.run_(marker=relaunch.EXIT_RESTART, successorAfter=None)
		self.assertEqual(action, relaunch.ACTION_LAUNCH)
		self.assertGreaterEqual(ops.t, guardian.SUCCESSOR_WAIT)

	def test_sustituida_por_otra_copia(self):
		# Salida pedida por otra copia de Tiresias que la sustituye (instalación encima...).
		ops, action = self.run_(marker=relaunch.EXIT_USER, replaced=True, successorAfter=0.5)
		self.assertEqual((action, ops.launched), (relaunch.ACTION_NONE, []))

	def test_actualizacion_y_volver_al_lector(self):
		for kind in (relaunch.EXIT_UPDATE, relaunch.EXIT_SWITCH):
			ops, action = self.run_(marker=kind)
			self.assertEqual((action, ops.launched), (relaunch.ACTION_NONE, []), kind)

	def test_opcion_desactivada(self):
		ops, action = self.run_(marker=relaunch.EXIT_USER, options={"relaunchOnExit": False})
		self.assertEqual((action, ops.launched), (relaunch.ACTION_NONE, []))

	def test_marcador_y_proceso_colgado(self):
		# Tiresias escribió «salida del usuario» pero su proceso no termina.
		ops, action = self.run_(marker=relaunch.EXIT_USER, aliveFor=1000)
		self.assertEqual(action, relaunch.ACTION_LAUNCH)
		self.assertLess(ops.t, guardian.EXIT_STALL + 2)

	def test_reinicio_lento_no_es_un_bloqueo(self):
		# Reinicio: Tiresias ya no late mientras termina, pero hay marcador; no se inicia nada.
		ops, action = self.run_(marker=relaunch.EXIT_RESTART, aliveFor=8.0, successorAfter=9.0, heartbeat=[(True, 99.0)] * 40, options={"hangTimeout": 5})
		self.assertEqual((action, ops.launched), (relaunch.ACTION_NONE, []))

	def test_bloqueo_una_vez_y_se_rearma(self):
		beats = [(True, 1.0)] * 2 + [(True, 25.0)] * 4 + [(True, 0.5)] * 2 + [(True, 30.0)] * 2
		ops, action = self.run_(marker=None, running=False, aliveFor=6.0, heartbeat=beats)
		# Dos bloqueos (rearmado en medio) y la salida final por fallo.
		self.assertEqual(len(ops.launched), 3)

	def test_bloqueo_desactivado_o_sin_armar(self):
		# Sin marcador mientras vive (bloqueo de verdad); al salir no se relanza (opción de salida desactivada).
		noExit = {"relaunchOnExit": False}
		ops, _a = self.run_(marker=None, aliveFor=3.0, heartbeat=[(True, 99.0)] * 6, options=dict(noExit, relaunchOnHang=False))
		self.assertEqual(ops.launched, [])
		ops, _a = self.run_(marker=None, aliveFor=3.0, heartbeat=[(False, 99.0)] * 6, options=noExit)
		self.assertEqual(ops.launched, [])
		ops, _a = self.run_(marker=None, aliveFor=3.0, heartbeat=[(True, 99.0)] * 6, options=noExit)
		self.assertEqual(len(ops.launched), 1)


# ====================================================================== procesos de verdad
def _makeFakeNvda(folder: str) -> str:
	"""Copia de ``pythonw.exe`` llamada ``nvda.exe`` que encuentra su biblioteca sin variables."""
	base = getattr(sys, "_base_executable", sys.executable)
	baseDir = os.path.dirname(base)
	pyw = os.path.join(baseDir, "pythonw.exe")
	if not os.path.isfile(pyw):
		raise OSError("no hay pythonw.exe")
	exe = os.path.join(folder, "nvda.exe")
	shutil.copy2(pyw, exe)
	for dll in os.listdir(baseDir):
		low = dll.lower()
		if low.endswith(".dll") and (low.startswith("python3") or low.startswith("vcruntime")) and "_d" not in low and "t." not in low:
			shutil.copy2(os.path.join(baseDir, dll), os.path.join(folder, dll))
	with open(os.path.join(folder, "nvda._pth"), "w", encoding="utf-8") as f:
		f.write("\n".join([os.path.join(sys.base_prefix, "Lib"), os.path.join(sys.base_prefix, "DLLs"), sys.base_prefix]) + "\n")
	return exe


def _fakeArgs(seconds: int = 120) -> list[str]:
	return ["-X", "utf8", FAKE_READER, "wxWindowClassNR", "NVDA", str(seconds)]


def _pidsOf(exe: str) -> list[int]:
	key = os.path.normcase(exe)
	return [p.pid for p in detect.listProcesses() if p.name == "nvda.exe" and os.path.normcase(detect.processImagePath(p.pid)) == key]


def _kill(pid: int) -> None:
	h = ctypes.windll.kernel32.OpenProcess(0x0001 | 0x00100000, False, pid)
	if h:
		ctypes.windll.kernel32.TerminateProcess(h, 1)
		ctypes.windll.kernel32.WaitForSingleObject(h, 3000)
		ctypes.windll.kernel32.CloseHandle(h)


def _killFakes(exe: str) -> None:
	for pid in _pidsOf(exe):
		_kill(pid)


def _killByCommandLine(fragment: str) -> None:
	"""Termina los procesos de la prueba (guardianes primero, luego Tiresias) que usan esa carpeta."""
	import psutil

	key = os.path.normcase(fragment)
	found = []
	for p in psutil.process_iter(["pid", "cmdline"]):
		if p.info["pid"] == os.getpid():
			continue
		try:
			cmd = " ".join(p.info["cmdline"] or [])
		except Exception:
			continue
		if key in os.path.normcase(cmd):
			found.append((0 if "--guardian" in cmd else 1, p.info["pid"]))
	for _order, pid in sorted(found):
		_kill(pid)


def _realReaderPids(exclude: str = "") -> list[int]:
	"""Lectores de verdad del equipo (NVDA del usuario...): las pruebas los ignoran."""
	key = os.path.normcase(exclude)
	return [p.pid for p in detect.listProcesses() if p.name in READER_NAMES and os.path.normcase(detect.processImagePath(p.pid)) != key]


def _waitFor(cond, timeout: float, step: float = 0.2) -> bool:
	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		if cond():
			return True
		time.sleep(step)
	return bool(cond())


class _RealProcessBase(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.tmp = tempfile.mkdtemp(prefix="tiresias_guardian_")
		try:
			cls.fakeExe = _makeFakeNvda(os.path.join(cls.tmp))
		except OSError as e:
			raise unittest.SkipTest(f"No se pudo preparar el NVDA falso: {e}")
		cls.env = dict(os.environ)
		cls.env.pop("PYTHONHOME", None)
		cls.env.pop("PYTHONPATH", None)
		cls.env.pop("TIRESIAS_NO_GUARDIAN", None)
		cls.env["TIRESIAS_COEXIST_IGNORE_PIDS"] = ",".join(str(p) for p in _realReaderPids(cls.fakeExe))
		# Si el NVDA falso faltara, nunca se recurre al NVDA instalado del equipo.
		cls.env["TIRESIAS_RELAUNCH_NO_FALLBACK"] = "1"
		# Solo cuenta el NVDA falso de esta prueba (ni el real ni los de otras pruebas a la vez).
		cls.env["TIRESIAS_COEXIST_ONLY_DIR"] = cls.tmp
		# Con lectores falsos el guardián solo se inicia si se pide.
		cls.env["TIRESIAS_GUARDIAN_TEST"] = "1"

	@classmethod
	def tearDownClass(cls):
		# Nada de la prueba puede quedar vivo antes de borrar el NVDA falso.
		_killByCommandLine(cls.tmp)
		_killFakes(cls.fakeExe)
		shutil.rmtree(cls.tmp, ignore_errors=True)

	def setUp(self):
		# Los lectores reales se vuelven a buscar en cada prueba (por si se han reiniciado).
		self.env = dict(type(self).env)
		self.env["TIRESIAS_COEXIST_IGNORE_PIDS"] = ",".join(str(p) for p in _realReaderPids(self.fakeExe))
		self.data = tempfile.mkdtemp(prefix="datos_", dir=self.tmp)
		self.memory = relaunch.memoryPath(self.data)
		relaunch.saveMemory(
			{"reader": {"id": "nvda", "name": "NVDA", "path": self.fakeExe, "detail": "", "args": _fakeArgs()}, "options": dict(relaunch.DEFAULT_OPTIONS, readers=["nvda"])},
			self.memory,
		)

	def tearDown(self):
		_killByCommandLine(self.data)
		_killFakes(self.fakeExe)

	def startFake(self) -> int:
		pid = relaunch.launchExecutable(self.fakeExe, _fakeArgs())
		self.assertTrue(pid > 0)
		self.assertTrue(_waitFor(lambda: self.fakeReady(), 10), "El NVDA falso no ha creado su ventana")
		return pid

	def fakeReady(self) -> bool:
		pids = set(_pidsOf(self.fakeExe))
		return any(pid in pids for _h, pid in detect.windowsOf("wxWindowClassNR", "NVDA"))

	def guardianLog(self) -> str:
		try:
			with open(os.path.join(self.data, "logs", "guardian.log"), encoding="utf-8") as f:
				return f.read()
		except OSError:
			return ""


class GuardianProcessTests(_RealProcessBase):
	"""El proceso ``--guardian`` de verdad con un «Tiresias» de mentira y el NVDA falso."""

	def startDummy(self, code: str) -> subprocess.Popen:
		return subprocess.Popen([BASE_PYTHON, "-c", code], env=self.env, creationflags=NO_WINDOW)

	def startGuardian(self, pid: int) -> subprocess.Popen:
		g = subprocess.Popen([PYTHON, ENTRY, "--guardian", str(pid), "--data", self.data], env=self.env, creationflags=NO_WINDOW)
		self.assertTrue(_waitFor(lambda: relaunch.isGuardianRunning(pid), 10), "El guardián no ha arrancado")
		return g

	def test_cierre_nativo_inicia_el_lector(self):
		dummy = self.startDummy("import time; time.sleep(60)")
		try:
			g = self.startGuardian(dummy.pid)
		finally:
			dummy.kill()
		dummy.wait(5)
		self.assertTrue(_waitFor(self.fakeReady, 15), "El guardián no ha iniciado el NVDA falso:\n" + self.guardianLog())
		g.wait(10)
		self.assertFalse(relaunch.isGuardianRunning(dummy.pid))
		self.assertIn("decisión: launch", self.guardianLog())

	def test_reinicio_no_lo_inicia(self):
		dummy = self.startDummy("import time; time.sleep(60)")
		g = self.startGuardian(dummy.pid)
		relaunch.writeMarker(relaunch.EXIT_RESTART, dummy.pid, self.data)
		# La «copia nueva» de Tiresias: el mutex de instancia.
		instance = ctypes.windll.kernel32.CreateMutexW(None, False, relaunch.INSTANCE_MUTEX)
		try:
			dummy.kill()
			dummy.wait(5)
			g.wait(15)
		finally:
			ctypes.windll.kernel32.CloseHandle(instance)
		self.assertEqual(_pidsOf(self.fakeExe), [])
		self.assertIn("La copia nueva de Tiresias está en marcha", self.guardianLog())

	def test_lector_ya_en_ejecucion_no_se_duplica(self):
		self.startFake()
		before = set(_pidsOf(self.fakeExe))
		dummy = self.startDummy("import time; time.sleep(60)")
		g = self.startGuardian(dummy.pid)
		relaunch.writeMarker(relaunch.EXIT_USER, dummy.pid, self.data)
		dummy.kill()
		dummy.wait(5)
		g.wait(15)
		self.assertEqual(set(_pidsOf(self.fakeExe)), before)
		self.assertIn("decisión: none", self.guardianLog())

	def test_bloqueo_inicia_el_lector(self):
		relaunch.saveOptions({"hangTimeout": 5}, self.memory)
		# «Tiresias» que late una vez y se queda bloqueado.
		code = (
			"import sys, time; sys.path.insert(0, {src!r}); from tiresias.coexist import relaunch; "
			"hb = relaunch.Heartbeat(); hb.beat(); print('ok', flush=True); time.sleep(60)"
		).format(src=os.path.join(ROOT, "src"))
		dummy = subprocess.Popen([BASE_PYTHON, "-c", code], env=self.env, stdout=subprocess.PIPE, creationflags=NO_WINDOW)
		try:
			self.assertEqual(dummy.stdout.readline().strip(), b"ok")
			g = self.startGuardian(dummy.pid)
			self.assertTrue(_waitFor(self.fakeReady, 20), "No se ha iniciado el lector por bloqueo:\n" + self.guardianLog())
			self.assertIn("no responde", self.guardianLog())
			_killFakes(self.fakeExe)
		finally:
			dummy.kill()
			dummy.wait(5)
			dummy.stdout.close()
		g.wait(15)
		# Al terminar (fallo) vuelve a iniciarlo: no estaba en ejecución.
		self.assertIn("Tiresias ha terminado (motivo: error)", self.guardianLog())


@unittest.skipIf(os.environ.get("TIRESIAS_SIN_INTEGRACION") == "1", "Integración desactivada")
class TiresiasIntegrationTests(_RealProcessBase):
	"""Tiresias de verdad en espera con el NVDA falso; después se cierra de tres maneras."""

	@classmethod
	def setUpClass(cls):
		from tiresias import core

		# Si ya hay una copia abierta antes de empezar (la que usa la persona del
		# equipo, por ejemplo), la de la prueba no puede arrancar (instancia única
		# con --no-replace): se salta enseguida, sin esperar ni fallar. Un breve
		# margen deja terminar una copia de otra prueba que se esté cerrando.
		if not _waitFor(lambda: not core.isRunning(), 8, 0.5):
			raise unittest.SkipTest(
				"Hay otra copia de Tiresias en ejecución en esta sesión (probablemente la del usuario): "
				"la prueba de integración no puede arrancar la suya con --no-replace"
			)
		super().setUpClass()

	def setUp(self):
		super().setUp()
		from tiresias import core

		if not _waitFor(lambda: not core.isRunning(), 60, 1.0):
			self.skipTest("Hay otra copia de Tiresias en ejecución (--no-replace no arrancaría)")
		self.procs: list[subprocess.Popen] = []

	def tearDown(self):
		for p in self.procs:
			if p.poll() is None:
				p.kill()
		super().tearDown()

	def log(self) -> str:
		try:
			with open(os.path.join(self.data, "logs", "tiresias.log"), encoding="utf-8") as f:
				return f.read()
		except OSError:
			return ""

	def runTiresias(self, *extra: str) -> int:
		env = dict(self.env)
		env["TIRESIAS_COEXIST_TEST"] = "1"
		args = [PYTHON, "-X", "utf8", ENTRY, "--no-input", "--no-replace", "--minimal", "--synth", "silence", "--data", self.data, *extra]
		p = subprocess.Popen(args, env=env, creationflags=NO_WINDOW)
		self.procs.append(p)
		import psutil

		def realPid() -> int:
			# El python.exe del entorno virtual es un lanzador: Tiresias es su hijo.
			try:
				kids = [k for k in psutil.Process(p.pid).children() if k.name().lower().startswith("python")]
			except psutil.Error:
				return 0
			return kids[0].pid if kids else 0

		self.assertTrue(_waitFor(lambda: realPid() or p.poll() is not None, 15))
		pid = realPid() or p.pid
		self.tiresiasPid = pid
		return pid

	def bringToActive(self, *extra: str) -> int:
		"""Arranca Tiresias con el NVDA falso (espera) y cierra el falso (se activa)."""
		self.startFake()
		pid = self.runTiresias(*extra)
		self.assertTrue(_waitFor(lambda: "Tiresias pasa a espera" in self.log(), 40), "No pasó a espera:\n" + self.log()[-3000:])
		self.assertTrue(_waitFor(lambda: relaunch.isGuardianRunning(pid), 10), "Sin guardián")
		mem = relaunch.loadMemory(self.memory)["reader"]
		self.assertEqual(os.path.normcase(mem["path"]), os.path.normcase(self.fakeExe))
		self.assertEqual(mem["args"], _fakeArgs())
		_killFakes(self.fakeExe)
		self.assertTrue(_waitFor(lambda: "Tiresias se activa" in self.log(), 20), "No se activó:\n" + self.log()[-3000:])
		self.assertEqual(_pidsOf(self.fakeExe), [])
		return pid

	def assertNoErrors(self):
		text = self.log()
		self.assertNotIn("Traceback", text)
		self.assertNotIn(" ERROR ", text)

	def test_a_salir_con_quit(self):
		pid = self.bringToActive()
		from tiresias import core

		# --quit cierra la copia en ejecución: tiene que ser la de esta prueba.
		self.assertEqual(core.winapi.getWindowProcessId(core._findRunningInstance()), pid)
		env = dict(self.env)
		subprocess.run([PYTHON, "-X", "utf8", ENTRY, "--quit", "--data", self.data], env=env, timeout=60, creationflags=NO_WINDOW)
		self.assertTrue(_waitFor(self.fakeReady, 20), "El guardián no ha iniciado el NVDA falso:\n" + self.guardianLog())
		self.assertIn("motivo: user", self.guardianLog())
		self.assertTrue(_waitFor(lambda: not relaunch.isGuardianRunning(pid), 10), "El guardián no ha terminado")
		self.assertNoErrors()

	def test_b_cierre_nativo(self):
		pid = self.bringToActive()
		_kill(pid)
		self.assertTrue(_waitFor(self.fakeReady, 20), "El guardián no ha iniciado el NVDA falso:\n" + self.guardianLog())
		self.assertIn("motivo: error", self.guardianLog())
		self.assertTrue(_waitFor(lambda: not relaunch.isGuardianRunning(pid), 10), "El guardián no ha terminado")
		# El auxiliar de compatibilidad con NVDA no queda vivo.
		self.assertEqual(relaunch.helperProcesses(pid), [])

	def test_c_reinicio(self):
		pid = self.bringToActive("--restart-after", "25")
		from tiresias import core

		def newInstance() -> int:
			hwnd = core._findRunningInstance()
			other = core.winapi.getWindowProcessId(hwnd) if hwnd else 0
			return other if other and other != pid else 0

		self.assertTrue(_waitFor(lambda: newInstance() != 0, 60), "No se ha reiniciado:\n" + self.log()[-3000:])
		newPid = newInstance()
		self.tiresiasPid = newPid
		self.assertTrue(_waitFor(lambda: not relaunch.isGuardianRunning(pid), 15), "El guardián antiguo no ha terminado")
		self.assertIn("motivo: restart", self.guardianLog())
		self.assertIn("La copia nueva de Tiresias está en marcha", self.guardianLog())
		time.sleep(2)
		self.assertEqual(_pidsOf(self.fakeExe), [], "Se ha iniciado el lector en un reinicio")
		# La copia nueva tiene su propio guardián. Se cierra sin relanzar (opción desactivada).
		self.assertTrue(_waitFor(lambda: relaunch.isGuardianRunning(newPid), 20), "La copia nueva no tiene guardián")
		relaunch.saveOptions({"relaunchOnExit": False}, self.memory)
		h = core.winapi.kernel32.OpenProcess(0x00100000, False, newPid)
		subprocess.run([PYTHON, "-X", "utf8", ENTRY, "--quit", "--data", self.data], env=self.env, timeout=60, creationflags=NO_WINDOW)
		if h:
			core.winapi.kernel32.WaitForSingleObject(h, 15000)
			core.winapi.kernel32.CloseHandle(h)
		self.assertTrue(_waitFor(lambda: not relaunch.isGuardianRunning(newPid), 10))
		self.assertEqual(_pidsOf(self.fakeExe), [])
		self.tiresiasPid = 0
		self.assertNoErrors()


if __name__ == "__main__":
	unittest.main()
