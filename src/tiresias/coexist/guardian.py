"""Proceso guardián: el usuario nunca se queda sin lector de pantalla.

Tiresias inicia, nada más arrancar, una copia ligera de sí mismo en modo
guardián (``Tiresias.exe --guardian <pid> --data <carpeta>``; desde código,
``pythonw tiresias.pyw --guardian ...``). El guardián no carga wx ni el
núcleo: arranca en unas décimas de segundo y ocupa poca memoria.

El guardián:

1. Espera a que termine el proceso de Tiresias (``WaitForSingleObject`` cada
   medio segundo).
2. Mientras tanto, si la opción está activa, vigila el **latido** del núcleo
   (memoria compartida que anota el vigilante de Tiresias, ver
   :class:`.relaunch.Heartbeat`): si el núcleo lleva más de N segundos sin
   responder, inicia el lector recordado (una vez por bloqueo). Tiresias, al
   recuperarse, detecta ese lector y pasa a espera.
3. Al terminar Tiresias lee el **marcador de salida** (``data\\temp\\salida_<pid>.txt``)
   y decide con :func:`.relaunch.decideExit`:

   - salida del usuario o fallo (sin marcador: excepción, cierre nativo,
     proceso terminado): inicia el lector recordado si no hay ya un lector
     en ejecución;
   - reinicio o sustitución por otra copia: espera a que arranque la copia
     nueva y, si no llega en un minuto, inicia el lector;
   - actualización o «Volver a <lector>»: nada.

   Antes de iniciar NVDA se asegura de que el auxiliar
   ``tiresiasNvdaWindow.exe`` de esa copia ha terminado, para que NVDA tenga
   libre su punto de conexión.
4. Termina. Nunca deja procesos huérfanos: su vida está atada a la de
   Tiresias.

Si Tiresias escribió el marcador pero su proceso no termina (se quedó
colgado al cerrarse), el guardián actúa igualmente pasados unos segundos.

La parte de Tiresias (:func:`start`, :func:`beat`, :func:`onProcessExit`...)
también está aquí.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

from .. import paths
from . import relaunch

#: Intervalo de espera del guardián (s).
POLL = 0.5
#: Marcador escrito y proceso aún vivo: pasados estos segundos se actúa igual.
EXIT_STALL = 10.0
#: Espera máxima a la copia nueva tras un reinicio o una sustitución (s).
SUCCESSOR_WAIT = 60.0
#: Espera máxima a la copia actualizada tras --apply-update (s).
UPDATE_SUCCESSOR_WAIT = 90.0
#: Cada cuánto se relee el archivo del lector recordado (s).
MEMORY_REFRESH = 2.0

CREATE_NO_WINDOW = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


# ====================================================================== lado de Tiresias
_heartbeat: relaunch.Heartbeat | None = None
_proc: subprocess.Popen | None = None
_dataDir: str = ""
_exitKind: str | None = None
_lock = threading.Lock()
_started = False


def _log():
	from ..log import getLogger

	return getLogger("coexist.guardian")


def shouldStart(args) -> bool:
	"""¿Se inicia el guardián en esta sesión?

	En las pruebas no se inicia salvo que se pida (``TIRESIAS_GUARDIAN_TEST=1``):

	- con ``--exit-after`` (pruebas automáticas, a menudo con el NVDA real
	  del usuario como lector recordado);
	- con lectores falsos (``TIRESIAS_COEXIST_IGNORE_PIDS`` o
	  ``TIRESIAS_COEXIST_ONLY_DIR``): el guardián volvería a abrir el lector
	  falso de esa prueba al cerrarse Tiresias.

	``TIRESIAS_NO_GUARDIAN=1`` lo desactiva siempre, y nunca se inicia en la
	copia del escritorio seguro.
	"""
	env = os.environ
	if env.get("TIRESIAS_NO_GUARDIAN") == "1":
		return False
	if args is not None and getattr(args, "secure_desktop", False):
		# Copia del escritorio seguro (SYSTEM): nunca inicia otros lectores ni deja
		# procesos al volver al escritorio del usuario (ver secure_screens).
		return False
	if env.get("TIRESIAS_GUARDIAN_TEST") == "1":
		return True
	if args is not None and getattr(args, "exit_after", 0):
		return False
	if env.get("TIRESIAS_COEXIST_IGNORE_PIDS") or env.get("TIRESIAS_COEXIST_ONLY_DIR"):
		return False
	return True


def guardianCommand(pid: int, dataDir: str) -> list[str]:
	if paths.FROZEN:
		base = [sys.executable]
	else:
		exe = sys.executable
		pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
		base = [pyw if os.path.isfile(pyw) else exe, os.path.join(paths.SOURCE_DIR, "tiresias.pyw")]
	return base + ["--guardian", str(int(pid)), "--data", dataDir]


def _spawn(cmd: list[str]) -> subprocess.Popen:
	try:
		# Fuera del trabajo (job) del proceso padre: si quien lanzó Tiresias
		# cierra su trabajo, el guardián tiene que seguir vivo.
		return subprocess.Popen(cmd, close_fds=True, creationflags=CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB)
	except OSError:
		return subprocess.Popen(cmd, close_fds=True, creationflags=CREATE_NO_WINDOW)


def start(args=None) -> bool:
	"""Crea el latido e inicia el guardián (lo llama ``core.main`` al principio)."""
	global _heartbeat, _proc, _dataDir, _started
	if not shouldStart(args):
		_log().info("Guardián desactivado en esta sesión (pruebas)")
		return False
	_dataDir = paths.DATA_DIR
	# Un marcador de salida con este PID es de un proceso anterior que tuvo el
	# mismo número (su guardián no llegó a recogerlo): el guardián nuevo lo
	# tomaría por la salida de esta sesión y actuaría con Tiresias en marcha.
	clearStaleMarker(os.getpid(), _dataDir)
	with _lock:
		if _heartbeat is None:
			try:
				_heartbeat = relaunch.Heartbeat()
			except OSError:
				_log().exception("No se pudo crear el latido para el guardián")
		_started = True
	return ensureRunning()


def clearStaleMarker(pid: int, dataDir: str) -> bool:
	"""Borra el marcador de salida de ``pid`` si existe. ``True`` si había uno."""
	path = relaunch.markerPath(pid, dataDir)
	try:
		os.remove(path)
	except FileNotFoundError:
		return False
	except OSError:
		_log().debug("No se pudo borrar el marcador antiguo %s", path, exc_info=True)
		return False
	_log().info("Marcador de salida antiguo con el mismo PID borrado: %s", path)
	return True


def ensureRunning() -> bool:
	"""Inicia el guardián si no está en marcha (también si alguien lo cerró)."""
	global _proc
	if not _started:
		return False
	with _lock:
		if _proc is not None and _proc.poll() is None:
			return True
		if relaunch.isGuardianRunning(os.getpid()):
			return True
		cmd = guardianCommand(os.getpid(), _dataDir or paths.DATA_DIR)
		try:
			_proc = _spawn(cmd)
		except OSError:
			_log().exception("No se pudo iniciar el guardián")
			_proc = None
			return False
	_log().info("Guardián iniciado (PID %d)", _proc.pid)
	return True


def beat() -> None:
	"""El núcleo responde (lo llama el vigilante cada segundo)."""
	hb = _heartbeat
	if hb is not None:
		hb.beat()


def setExitKind(kind: str) -> None:
	"""Motivo de la salida que se avecina (actualización, «Volver a <lector>»)."""
	global _exitKind
	_exitKind = kind


def exitKind() -> str | None:
	return _exitKind


def writeMarkerNow(kind: str) -> None:
	"""Escribe el marcador ya (reinicio de emergencia, que termina con ``os._exit``)."""
	if not _started:
		# Sin guardián (pruebas) nadie lo leería.
		return
	try:
		relaunch.writeMarker(kind, dataDir=_dataDir or paths.DATA_DIR)
	except OSError:
		pass


def onProcessExit(restart: bool, quitRequested: bool) -> str:
	"""Al final de ``core.main``: marcador de salida y, si se pidió, «Volver a <lector>».

	Devuelve el motivo anotado.
	"""
	global _heartbeat
	kind = _exitKind
	if restart:
		kind = relaunch.EXIT_RESTART
	elif kind is None:
		kind = relaunch.EXIT_USER if quitRequested else relaunch.EXIT_ERROR
	if kind == relaunch.EXIT_SWITCH:
		kind = relaunch.EXIT_SWITCH if _launchRememberedNow() else relaunch.EXIT_USER
	if kind != relaunch.EXIT_ERROR:
		writeMarkerNow(kind)
	log = _log()
	log.info("Motivo de la salida para el guardián: %s", kind)
	hb, _heartbeat = _heartbeat, None
	if hb is not None:
		hb.close()
	return kind


def _launchRememberedNow() -> bool:
	"""«Volver a <lector>»: Tiresias ya ha cerrado su núcleo (y el auxiliar de NVDA)."""
	log = _log()
	memory = relaunch.loadMemory(relaunch.memoryPath(_dataDir or None))
	reader = memory["reader"]
	if reader is None:
		return False
	try:
		if relaunch.anyReaderRunning(relaunch.readerIds(memory)):
			log.info("%s ya está en ejecución", relaunch.readerLabel(reader))
			return True
		relaunch.endHelpers(os.getpid(), 3.0, log.info)
	except Exception:
		log.debug("No se pudo comprobar los lectores en ejecución", exc_info=True)
	return bool(relaunch.launchReader(reader, log.info))


def afterUpdateLaunch(targetDir: str, timeout: float = UPDATE_SUCCESSOR_WAIT) -> str:
	"""Red de seguridad de ``--apply-update``: si la copia actualizada no arranca, el lector.

	Lo ejecuta la copia nueva que actualiza la carpeta portable (el guardián
	de la copia antigua termina al ver el marcador de actualización para no
	bloquear los archivos). Devuelve la decisión tomada.
	"""
	memoryFile = relaunch.memoryPath(os.path.join(targetDir, "data"))
	memory = relaunch.loadMemory(memoryFile)
	if memory["reader"] is None or not memory["options"]["relaunchOnExit"]:
		return relaunch.ACTION_NONE
	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		if relaunch.instanceRunning():
			return relaunch.ACTION_NONE
		time.sleep(POLL)
	memory = relaunch.loadMemory(memoryFile)
	running = bool(memory["reader"]) and bool(relaunch.anyReaderRunning(relaunch.readerIds(memory)))
	action = relaunch.decideAfterWait(
		relaunch.instanceRunning(),
		enabled=memory["options"]["relaunchOnExit"],
		hasReader=memory["reader"] is not None,
		readerRunning=running,
	)
	if action == relaunch.ACTION_LAUNCH and not relaunch.isShuttingDown():
		relaunch.launchReader(memory["reader"])
	return action


# ====================================================================== proceso guardián
class SystemOps:
	"""Acceso al sistema del guardián (las pruebas lo sustituyen por uno simulado)."""

	def __init__(self, pid: int, dataDir: str) -> None:
		self.pid = pid
		self.dataDir = dataDir
		self.memoryFile = relaunch.memoryPath(dataDir)
		self._heartbeat = relaunch.HeartbeatReader(pid)

	def openProcess(self):
		return relaunch.openProcess(self.pid)

	def waitProcess(self, handle, timeout: float) -> bool:
		if handle is None:
			return True
		return relaunch.waitHandle(handle, timeout)

	def closeProcess(self, handle) -> None:
		relaunch.closeHandle(handle)

	def peekMarker(self) -> str | None:
		return relaunch.readMarker(self.pid, self.dataDir)

	def takeMarker(self) -> str | None:
		return relaunch.readMarker(self.pid, self.dataDir, remove=True)

	def wasReplaced(self) -> bool:
		return relaunch.wasReplaced(self.pid)

	def successorRunning(self) -> bool:
		return relaunch.instanceRunning()

	def loadMemory(self) -> dict:
		return relaunch.loadMemory(self.memoryFile)

	def readerRunning(self, memory: dict) -> bool:
		return bool(relaunch.anyReaderRunning(relaunch.readerIds(memory)))

	def heartbeat(self) -> tuple[bool, float] | None:
		return self._heartbeat.read()

	def shuttingDown(self) -> bool:
		return relaunch.isShuttingDown()

	def endHelpers(self, logger) -> None:
		relaunch.endHelpers(self.pid, 3.0, logger)

	def launch(self, reader: dict, logger) -> int:
		return relaunch.launchReader(reader, logger)

	def now(self) -> float:
		return time.monotonic()

	def sleep(self, seconds: float) -> None:
		time.sleep(seconds)

	def close(self) -> None:
		self._heartbeat.close()


class Guardian:
	"""Lógica del guardián (independiente del sistema gracias a :class:`SystemOps`)."""

	def __init__(self, ops: SystemOps, logger=None) -> None:
		self.ops = ops
		self.log = logger or (lambda msg: None)
		self._memory: dict | None = None
		self._memoryAt = -1e9
		self.hangLaunched = False
		#: Decisiones tomadas (para el registro y las pruebas).
		self.actions: list[tuple[str, str]] = []

	def memory(self, fresh: bool = False) -> dict:
		now = self.ops.now()
		if fresh or self._memory is None or now - self._memoryAt >= MEMORY_REFRESH:
			self._memory = self.ops.loadMemory()
			self._memoryAt = now
		return self._memory

	# --------------------------------------------------- mientras Tiresias vive
	def checkHang(self) -> None:
		hb = self.ops.heartbeat()
		if hb is None:
			return
		armed, stale = hb
		if not armed:
			return
		memory = self.memory()
		opts = memory["options"]
		timeout = float(opts["hangTimeout"])
		if stale < timeout:
			if self.hangLaunched:
				self.log("Tiresias vuelve a responder")
			self.hangLaunched = False
			return
		if self.hangLaunched or not opts["relaunchOnHang"] or memory["reader"] is None:
			return
		running = self.ops.readerRunning(memory)
		action = relaunch.decideHang(stale, timeout=timeout, enabled=opts["relaunchOnHang"], hasReader=True, readerRunning=running, alreadyLaunched=False)
		# Una sola vez por bloqueo, se inicie o no (si ya había otro lector, no hace falta).
		self.hangLaunched = True
		self.log(f"Tiresias no responde desde hace {stale:.0f} s; decisión: {action}")
		if action == relaunch.ACTION_LAUNCH:
			self._launch(memory, "bloqueo", endHelpers=False)

	# --------------------------------------------------- al terminar Tiresias
	def onExit(self) -> str:
		kind = self.ops.takeMarker() or relaunch.EXIT_ERROR
		if kind in (relaunch.EXIT_USER, relaunch.EXIT_ERROR) and self.ops.wasReplaced():
			kind = relaunch.EXIT_REPLACED
		memory = self.memory(fresh=True)
		opts = memory["options"]
		hasReader = memory["reader"] is not None
		running = hasReader and kind in (relaunch.EXIT_USER, relaunch.EXIT_ERROR) and self.ops.readerRunning(memory)
		action = relaunch.decideExit(kind, enabled=opts["relaunchOnExit"], hasReader=hasReader, readerRunning=running)
		self.log(f"Tiresias ha terminado (motivo: {kind}); decisión: {action}")
		if action == relaunch.ACTION_WAIT:
			deadline = self.ops.now() + SUCCESSOR_WAIT
			successor = False
			while True:
				if self.ops.successorRunning():
					successor = True
					break
				if self.ops.now() >= deadline:
					break
				self.ops.sleep(POLL)
			memory = self.memory(fresh=True)
			opts = memory["options"]
			hasReader = memory["reader"] is not None
			running = hasReader and not successor and self.ops.readerRunning(memory)
			action = relaunch.decideAfterWait(successor, enabled=opts["relaunchOnExit"], hasReader=hasReader, readerRunning=running)
			self.log("La copia nueva de Tiresias está en marcha" if successor else f"La copia nueva de Tiresias no ha arrancado; decisión: {action}")
		if action == relaunch.ACTION_LAUNCH:
			if self.ops.shuttingDown():
				self.log("Windows se está cerrando: no se inicia el lector")
				action = relaunch.ACTION_NONE
			else:
				self._launch(memory, kind, endHelpers=True)
		return action

	def _launch(self, memory: dict, reason: str, endHelpers: bool) -> int:
		reader = memory["reader"]
		if endHelpers and reader and reader.get("id") == "nvda":
			self.ops.endHelpers(self.log)
		pid = self.ops.launch(reader, self.log)
		self.actions.append((reason, relaunch.readerLabel(reader)))
		return pid

	# --------------------------------------------------- bucle
	def run(self) -> str:
		handle = self.ops.openProcess()
		stallSince: float | None = None
		try:
			while not self.ops.waitProcess(handle, POLL):
				if self.ops.peekMarker():
					# Tiresias está terminando por sí mismo (ya no late): no es un bloqueo.
					now = self.ops.now()
					if stallSince is None:
						stallSince = now
					elif now - stallSince >= EXIT_STALL:
						self.log("Tiresias escribió su marcador de salida pero su proceso no termina: se actúa igualmente")
						break
					continue
				try:
					self.checkHang()
				except Exception as e:  # nunca debe tumbar al guardián
					self.log(f"Error vigilando el latido: {e!r}")
		finally:
			self.ops.closeProcess(handle)
		return self.onExit()


def _setupLog(dataDir: str):
	"""Registro propio del guardián (``data\\logs\\guardian.log``), sin el sistema de registro del núcleo."""
	path = os.path.join(dataDir, "logs", "guardian.log")
	try:
		os.makedirs(os.path.dirname(path), exist_ok=True)
		if os.path.getsize(path) > 512 * 1024:
			os.replace(path, path + ".1")
	except OSError:
		pass

	def write(msg: str) -> None:
		line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{os.getpid()}] {msg}\n"
		try:
			with open(path, "a", encoding="utf-8") as f:
				f.write(line)
		except OSError:
			pass

	return write


def parseGuardianArgs(argv: list[str]) -> tuple[int, str]:
	pid = 0
	dataDir = ""
	for i, a in enumerate(argv):
		if a == "--guardian" and i + 1 < len(argv):
			try:
				pid = int(argv[i + 1])
			except ValueError:
				pid = 0
		elif a == "--data" and i + 1 < len(argv):
			dataDir = argv[i + 1]
	return pid, os.path.abspath(dataDir) if dataDir else paths.DATA_DIR


def main(argv: list[str] | None = None) -> int:
	"""Punto de entrada de ``--guardian <pid> --data <carpeta>``."""
	pid, dataDir = parseGuardianArgs(list(sys.argv[1:] if argv is None else argv))
	if pid <= 0:
		return 2
	log = _setupLog(dataDir)
	mutex = relaunch.createGuardianMutex(pid)
	try:
		import ctypes

		# ShellExecuteEx necesita COM en el hilo que lo llama.
		ctypes.windll.ole32.CoInitializeEx(None, 0x2 | 0x4)  # COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE
	except Exception:
		pass
	ops = SystemOps(pid, dataDir)
	log(f"Guardián de Tiresias (PID {pid}) en marcha")
	try:
		action = Guardian(ops, log).run()
	except Exception as e:
		log(f"Error en el guardián: {e!r}")
		action = "error"
	finally:
		ops.close()
		relaunch.closeHandle(mutex)
	log(f"Guardián terminado ({action})")
	return 0
