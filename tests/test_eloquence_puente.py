"""Puente de 32 bits de Eloquence: tubería propia, reconexión y reposo.

Tiresias arranca siempre su propio proceso del puente con una tubería única
y nunca se conecta a ``\\\\.\\pipe\\ibmtts_host32`` (la del puente original,
que usa, por ejemplo, el complemento IBMTTS de NVDA). Las pruebas con el
puente real se saltan si falta la DLL, ``ECI.DLL`` o el ``rundll32`` de 32
bits. Ninguna prueba crea ni toca la tubería del puente original.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import time
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
	sys.path.insert(0, SRC)
SYNTH_DIR = os.path.join(ROOT, "data", "addons", "eloquence", "synthDrivers")
HOST_DLL = os.path.join(SYNTH_DIR, "eci", "ibmtts_host32.dll")
ECI_DLL = os.path.join(SYNTH_DIR, "eci", "ECI.DLL")
RUNDLL32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "SysWOW64", "rundll32.exe")
PKG = "tiresias_test_eloquence"


def _loadPackage():
	if PKG not in sys.modules:
		pkg = types.ModuleType(PKG)
		pkg.__path__ = [SYNTH_DIR]
		sys.modules[PKG] = pkg
	return importlib.import_module(f"{PKG}._eci_bridge")


#: Eloquence es propietario: no está en el repositorio público (se distribuye
#: aparte en la tienda). Sin él, las pruebas del puente se saltan.
HAS_ELOQUENCE = os.path.isfile(os.path.join(SYNTH_DIR, "_eci_bridge.py"))
NO_ELOQUENCE = "Falta el complemento Eloquence (data/addons/eloquence): no se incluye en el repositorio"
bridge = _loadPackage() if HAS_ELOQUENCE else None
REAL_BRIDGE = HAS_ELOQUENCE and os.path.isfile(HOST_DLL) and os.path.isfile(ECI_DLL) and os.path.isfile(RUNDLL32)


def _waitExit(proc, timeout: float) -> bool:
	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		if proc.poll() is not None:
			return True
		time.sleep(0.05)
	return False


@unittest.skipUnless(HAS_ELOQUENCE, NO_ELOQUENCE)
class NombresTests(unittest.TestCase):
	def test_tuberia_propia_y_unica(self) -> None:
		a = bridge.makePipeName(1234)
		b = bridge.makePipeName(1234)
		self.assertNotEqual(a, b)
		for name in (a, b):
			self.assertTrue(name.startswith("\\\\.\\pipe\\tiresias_eci_1234_"), name)
			self.assertNotEqual(name.lower(), bridge.LEGACY_PIPE_NAME.lower())
		self.assertEqual(bridge.makePipeName(7, 3), "\\\\.\\pipe\\tiresias_eci_7_3")
		self.assertIn(f"tiresias_eci_{os.getpid()}_", bridge.makePipeName())

	def test_orden_del_puente(self) -> None:
		cmd = bridge.hostCommand(r"C:\W\SysWOW64\rundll32.exe", r"D:\a b\ibmtts_host32.dll", 42, "\\\\.\\pipe\\tiresias_eci_42_1")
		self.assertEqual(cmd, '"C:\\W\\SysWOW64\\rundll32.exe" "D:\\a b\\ibmtts_host32.dll",StartHost 42 tiresias_eci_42_1')

	def test_nombres_de_memoria_y_eventos(self) -> None:
		resp = "SHM:Local\\tiresias_eci_1_2_shm_ab;EVT:Local\\tiresias_eci_1_2_ready_ab;PROC:Local\\tiresias_eci_1_2_proc_ab"
		self.assertEqual(
			bridge.bufferObjectNames(resp, 0xAB),
			("Local\\tiresias_eci_1_2_shm_ab", "Local\\tiresias_eci_1_2_ready_ab", "Local\\tiresias_eci_1_2_proc_ab"),
		)
		# Puente sin PROC en la respuesta: se deduce del evento «listo».
		self.assertEqual(
			bridge.bufferObjectNames("SHM:Local\\x_shm_1;EVT:Local\\x_ready_1", 1),
			("Local\\x_shm_1", "Local\\x_ready_1", "Local\\x_proc_1"),
		)
		# Puente original o respuesta desconocida: nombres de siempre.
		self.assertEqual(bridge.bufferObjectNames(None, 0x1F), ("Local\\eci_shm_1f", "Local\\eci_ready_1f", "Local\\eci_proc_1f"))
		self.assertEqual(bridge.bufferObjectNames(b"SHM:Local\\s;EVT:Local\\r_ready_2;PROC:Local\\p", 2), ("Local\\s", "Local\\r_ready_2", "Local\\p"))

	def test_no_se_conecta_a_la_tuberia_original(self) -> None:
		with self.assertRaises(bridge.BridgeError):
			bridge.PipeClient().connect(bridge.LEGACY_PIPE_NAME, timeout=0.1)
		with self.assertRaises(bridge.BridgeError):
			bridge.PipeClient().connect("\\\\.\\PIPE\\IBMTTS_HOST32", timeout=0.1)


class _FakeProcess:
	def __init__(self, exitCode=None) -> None:
		self.pid = 999999
		self.code = exitCode
		self.terminated = False

	def poll(self):
		return self.code

	def terminate(self) -> None:
		self.terminated = True
		self.code = 1

	def wait(self, timeout=None):
		return self.code

	def kill(self) -> None:
		self.code = 1


@unittest.skipUnless(HAS_ELOQUENCE, NO_ELOQUENCE)
class HostFalsoTests(unittest.TestCase):
	def setUp(self) -> None:
		self.dll = os.path.abspath(__file__)  # cualquier archivo que exista

	def test_proceso_que_termina_al_arrancar(self) -> None:
		cmds = []

		def launcher(cmd, **kw):
			cmds.append(cmd)
			return _FakeProcess(exitCode=3)

		host = bridge.BridgeHost(self.dll, ownerPid=55, launcher=launcher)
		with self.assertRaises(bridge.BridgeError) as cm:
			host.start(timeout=1)
		self.assertIn("código 3", str(cm.exception))
		self.assertFalse(host.isRunning())
		self.assertIn(",StartHost 55 tiresias_eci_55_", cmds[0])

	def test_sin_respuesta_se_detiene(self) -> None:
		procs = []

		def launcher(cmd, **kw):
			procs.append(_FakeProcess())
			return procs[-1]

		host = bridge.BridgeHost(self.dll, ownerPid=56, launcher=launcher)
		with self.assertRaises(bridge.BridgeError):
			host.start(timeout=0.2)
		self.assertTrue(procs[0].terminated)
		self.assertIsNone(host.pipeName)

	def test_falta_la_dll(self) -> None:
		host = bridge.BridgeHost(os.path.join(ROOT, "no_existe.dll"), launcher=lambda *a, **k: self.fail("no debe lanzarse"))
		with self.assertRaises(bridge.BridgeError):
			host.start(timeout=0.2)


@unittest.skipUnless(REAL_BRIDGE, "Falta el puente de 32 bits, ECI.DLL o rundll32 de 32 bits")
class PuenteRealTests(unittest.TestCase):
	def test_puente_propio_reconexion_y_cierre_con_el_padre(self) -> None:
		# 1) Puente propio con tubería única; la tubería es de ese proceso.
		host = bridge.BridgeHost(HOST_DLL)
		client = bridge.PipeClient()
		try:
			name1 = host.start()
			self.assertTrue(name1.startswith(f"\\\\.\\pipe\\tiresias_eci_{os.getpid()}_"))
			client.connect(name1, serverPid=host.pid)
			self.assertEqual(client.call(bridge.LOAD_LIBRARY, ECI_DLL), 1)
			h = client.call(bridge.ECI_NEW_EX, 0x00020000)
			self.assertTrue(h)
			resp = client.call(bridge.SET_BUFFER, h, 3300)
			shm, ready, proc = bridge.bufferObjectNames(resp, h)
			base = bridge.pipeBaseName(name1)
			for objName in (shm, ready, proc):
				self.assertTrue(objName.startswith(f"Local\\{base}_"), objName)
			# 2) El proceso muere: la llamada falla y un puente nuevo funciona.
			pid1 = host.pid
			host._process.kill()
			self.assertTrue(_waitExit(host._process, 5))
			with self.assertRaises(bridge.BridgeError):
				client.call(bridge.ECI_VERSION)
			name2 = host.start()
			self.assertNotEqual(name1, name2)
			self.assertNotEqual(pid1, host.pid)
			client.connect(name2, serverPid=host.pid)
			self.assertEqual(client.call(bridge.LOAD_LIBRARY, ECI_DLL), 1)
			self.assertIn(b"6.", client.call(bridge.ECI_VERSION))
			# Con otro PID esperado, la conexión se rechaza.
			other = bridge.PipeClient()
			with self.assertRaises(bridge.BridgeError):
				other.connect(name2, serverPid=1)
		finally:
			client.close()
			host.stop()
		self.assertFalse(host.isRunning())

	def test_el_puente_se_cierra_si_muere_el_padre(self) -> None:
		parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], creationflags=0x08000000)
		host = bridge.BridgeHost(HOST_DLL, ownerPid=parent.pid)
		try:
			host.start()
			proc = host._process
			self.assertIsNone(proc.poll())
			parent.kill()
			parent.wait(5)
			self.assertTrue(_waitExit(proc, 3), "el puente sigue vivo tras morir el proceso padre")
		finally:
			if parent.poll() is None:
				parent.kill()
			host.stop()


@unittest.skipUnless(REAL_BRIDGE, "Falta el puente de 32 bits, ECI.DLL o rundll32 de 32 bits")
class DriverTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		cls.mod = importlib.import_module(f"{PKG}.ibmtts")

	def _speak(self, d, text: str = "hola, esto es una prueba") -> bytes:
		out = []
		d._synthesizeSegment([text], out.append, lambda: False)
		return b"".join(out)

	def test_sintesis_reconexion_y_reposo(self) -> None:
		from tiresias import synth as synthHandler

		self.assertFalse(synthHandler.isStandby())
		d = self.mod.SynthDriver()
		try:
			name1 = d._client.pipeName
			self.assertTrue(name1.startswith(f"\\\\.\\pipe\\tiresias_eci_{os.getpid()}_"))
			self.assertGreater(len(self._speak(d)), 1000)
			# El puente muere (como el de NVDA al cerrarse): se reconecta solo.
			d._host._process.kill()
			self.assertTrue(_waitExit(d._host._process, 5))
			d.setSetting("rate", 60)  # con el puente caído no falla
			self.assertGreater(len(self._speak(d)), 1000)
			self.assertNotEqual(d._client.pipeName, name1)
			self.assertTrue(d._host.isRunning())
			# Reposo: sin proceso; los ajustes se guardan y se aplican al reanudar.
			proc = d._host._process
			d.releaseResources()
			self.assertTrue(d._dormant)
			self.assertFalse(d._host.isRunning())
			self.assertTrue(_waitExit(proc, 3))
			d.setSetting("pitch", 70)
			d.restoreResources()
			self.assertFalse(d._dormant)
			self.assertTrue(d._host.isRunning())
			self.assertEqual(int(d._client.call(self.mod.bridge.ECI_GET_VOICE_PARAM, d._handle, 0, self.mod.V_PITCH)), 70)
			self.assertGreater(len(self._speak(d)), 1000)
		finally:
			d.terminate()
		self.assertFalse(d._host.isRunning())

	def test_cargado_en_espera_no_arranca_el_puente(self) -> None:
		from tiresias import synth as synthHandler

		synthHandler._standby = True
		try:
			d = self.mod.SynthDriver()
		finally:
			synthHandler._standby = False
		try:
			self.assertTrue(d._dormant)
			self.assertFalse(d._host.isRunning())
			self.assertIsNone(d._client.pipeName)
			# Si algo pide voz, el motor arranca en ese momento.
			self.assertGreater(len(self._speak(d)), 1000)
			self.assertFalse(d._dormant)
		finally:
			d.terminate()


class SynthHandlerStandbyTests(unittest.TestCase):
	def test_reposo_y_reanudacion(self) -> None:
		from tiresias import synth as synthHandler

		calls = []

		class Fake:
			name = "falso"

			def cancel(self):
				calls.append("cancel")

			def releaseResources(self):
				calls.append("release")

			def restoreResources(self):
				calls.append("restore")

		old = synthHandler._current
		synthHandler._current = Fake()
		try:
			synthHandler.setStandby(True)
			synthHandler.setStandby(True)  # sin efecto la segunda vez
			self.assertTrue(synthHandler.isStandby())
			synthHandler.setStandby(False)
			self.assertFalse(synthHandler.isStandby())
		finally:
			synthHandler._current = old
			synthHandler._standby = False
		self.assertEqual(calls, ["cancel", "release", "restore"])

	def test_fallo_al_reanudar_cambia_de_sintetizador(self) -> None:
		from tiresias import synth as synthHandler

		class Fake:
			name = "falso"

			def cancel(self):
				pass

			def releaseResources(self):
				pass

			def restoreResources(self):
				raise RuntimeError("sin puente")

		fallbacks = []
		old, oldFallback = synthHandler._current, synthHandler.fallbackFrom
		synthHandler._current = Fake()
		synthHandler.fallbackFrom = lambda name, reason="": fallbacks.append((name, reason))
		try:
			synthHandler.setStandby(True)
			synthHandler.setStandby(False)
		finally:
			synthHandler._current = old
			synthHandler.fallbackFrom = oldFallback
			synthHandler._standby = False
		self.assertEqual(fallbacks, [("falso", "sin puente")])


if __name__ == "__main__":
	unittest.main()
