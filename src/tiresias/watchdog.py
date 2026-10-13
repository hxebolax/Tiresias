"""Recuperación del núcleo bloqueado.

El vigilante (``core._watchdog``) comprueba cada segundo si el hilo del
núcleo lleva más de ``advanced.watchdogTimeout`` segundos en la misma tarea
(o en el mismo paso del arranque o del cierre). Casi siempre la causa es una
llamada COM entre procesos que no vuelve (una aplicación colgada que no
responde a UI Automation).

Según ``advanced.watchdogRecovery``:

- ``off``: solo se registra el bloqueo;
- ``cancel``: se cancelan las llamadas COM pendientes del núcleo con
  ``CoCancelCall`` (el núcleo habilita la cancelación al arrancar con
  ``CoEnableCallCancellation``). La llamada bloqueada falla con un error
  que el código ya trata y el núcleo sigue funcionando;
- ``restart``: además, si tras ``advanced.watchdogRestartTimeout`` segundos
  el núcleo sigue bloqueado, se guarda la configuración (si se puede), se
  inicia una copia nueva de Tiresias y se termina esta. Un hilo de Python no
  se puede matar desde fuera, así que el reinicio controlado del proceso es la
  única forma segura de recuperar el lector en ese caso.

Los reinicios de emergencia tienen un límite (:data:`MAX_EMERGENCY_RESTARTS`
en :data:`RESTART_WINDOW` segundos, anotados en ``data\\temp``): si el bloqueo
se repite en cada arranque, Tiresias no se reinicia sin fin cada medio minuto;
deja de reiniciarse y lo avisa.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import threading
import time

from .config import conf
from .log import getLogger

log = getLogger("watchdog")

_ole32 = ctypes.WinDLL("ole32")
_ole32.CoCancelCall.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
_ole32.CoCancelCall.restype = ctypes.c_long
_ole32.CoEnableCallCancellation.argtypes = [ctypes.c_void_p]
_ole32.CoEnableCallCancellation.restype = ctypes.c_long

#: Identificador nativo del hilo del núcleo.
coreThreadId: int = 0
#: Instante del último intento de cancelación (para no repetirlo en exceso).
_lastCancel = 0.0
_restarting = False
#: Número de cancelaciones hechas en esta sesión (diagnóstico).
cancelCount = 0

#: Reinicios de emergencia permitidos dentro de :data:`RESTART_WINDOW` segundos.
MAX_EMERGENCY_RESTARTS = 2
RESTART_WINDOW = 600.0
#: Archivo (en ``data\\temp``) con los instantes de los últimos reinicios de emergencia.
RESTART_HISTORY_FILE = "reinicios_emergencia.json"
#: Se alcanzó el límite: en esta sesión ya no se reinicia (hasta que el núcleo se recupere).
_restartSuppressed = False


def registerCoreThread() -> None:
	"""Se llama desde el hilo del núcleo tras inicializar COM."""
	global coreThreadId
	coreThreadId = threading.get_native_id()
	try:
		hr = _ole32.CoEnableCallCancellation(None)
		if hr < 0:
			log.debug("CoEnableCallCancellation devolvió 0x%08X", hr & 0xFFFFFFFF)
	except Exception:
		log.debug("No se pudo habilitar la cancelación de llamadas COM", exc_info=True)


def cancelPendingCall() -> bool:
	"""Cancela la llamada COM saliente del núcleo, si hay alguna."""
	global cancelCount
	if not coreThreadId:
		return False
	hr = _ole32.CoCancelCall(coreThreadId, 0)
	if hr >= 0:
		cancelCount += 1
		log.warning("Se ha cancelado una llamada COM que bloqueaba el núcleo")
		return True
	return False


# ---------------------------------------------------------------------- historial de reinicios
def restartHistoryPath() -> str:
	from . import paths

	return os.path.join(paths.tempDir(), RESTART_HISTORY_FILE)


def loadRestartHistory(now: float | None = None) -> list[float]:
	"""Instantes (``time.time()``) de los reinicios de emergencia recientes."""
	now = time.time() if now is None else now
	try:
		with open(restartHistoryPath(), encoding="utf-8") as f:
			data = json.load(f)
	except (OSError, ValueError):
		return []
	if not isinstance(data, list):
		return []
	out = []
	for t in data:
		if isinstance(t, (int, float)) and not isinstance(t, bool) and 0 <= now - t <= RESTART_WINDOW:
			out.append(float(t))
	return out


def _recordRestart(now: float | None = None) -> None:
	now = time.time() if now is None else now
	times = loadRestartHistory(now) + [now]
	path = restartHistoryPath()
	try:
		os.makedirs(os.path.dirname(path), exist_ok=True)
		with open(path, "w", encoding="utf-8") as f:
			json.dump(times[-10:], f)
	except OSError:
		log.debug("No se pudo anotar el reinicio de emergencia", exc_info=True)


def restartAllowed(now: float | None = None) -> bool:
	"""``False`` si ya hubo :data:`MAX_EMERGENCY_RESTARTS` reinicios en la ventana."""
	return len(loadRestartHistory(now)) < MAX_EMERGENCY_RESTARTS


def onRecovered() -> None:
	"""El núcleo vuelve a responder: si vuelve a bloquearse se podrá reiniciar (con límite)."""
	global _restartSuppressed
	_restartSuppressed = False


# ---------------------------------------------------------------------- recuperación
def recover(frozenFor: float, allowRestart: bool = True) -> None:
	"""Intenta recuperar el núcleo (se llama desde el hilo del vigilante).

	``allowRestart=False`` durante el cierre: allí no se reinicia (el núcleo
	fuerza la salida por su cuenta, ver ``core._watchdog``).
	"""
	global _lastCancel
	try:
		mode = conf["advanced"]["watchdogRecovery"]
		restartAfter = conf["advanced"]["watchdogRestartTimeout"]
	except KeyError:
		mode, restartAfter = "restart", 30
	if mode == "off":
		return
	now = time.monotonic()
	if now - _lastCancel >= 1.0:
		_lastCancel = now
		try:
			cancelPendingCall()
		except Exception:
			log.debug("CoCancelCall falló", exc_info=True)
	if mode == "restart" and allowRestart and frozenFor >= restartAfter and not _restartSuppressed:
		if restartAllowed():
			emergencyRestart(frozenFor)
		else:
			_suppressRestarts(frozenFor)


def restartLimitMessage() -> str:
	from .i18n import _

	return _(
		"Tiresias sigue bloqueado y ya se ha reiniciado {count} veces en pocos minutos, así que no se reiniciará más. "
		"Cierre la aplicación que no responde o reinicie Tiresias sin complementos."
	).format(count=MAX_EMERGENCY_RESTARTS)


def _suppressRestarts(frozenFor: float) -> None:
	"""Límite alcanzado: no se reinicia más en esta sesión y se avisa al usuario."""
	global _restartSuppressed
	_restartSuppressed = True
	log.error(
		"El núcleo lleva %.0f s bloqueado, pero ya hubo %d reinicios de emergencia en %d minutos: no se reinicia más",
		frozenFor,
		MAX_EMERGENCY_RESTARTS,
		int(RESTART_WINDOW // 60),
	)
	text = restartLimitMessage()
	try:
		# Tres pitidos graves: el núcleo (y con él la voz normal) está bloqueado.
		for hz in (440, 330, 220):
			ctypes.windll.kernel32.Beep(hz, 150)
	except Exception:
		pass
	try:
		# Directamente al sintetizador: su hilo propio sigue vivo aunque el núcleo no.
		from . import synth

		s = synth.getSynth()
		if s is not None:
			s.speak([text])
	except Exception:
		log.debug("No se pudo anunciar el límite de reinicios", exc_info=True)
	try:
		from . import APP_NAME, gui

		gui.showTrayNotification(APP_NAME, text)
	except Exception:
		pass


def emergencyRestart(frozenFor: float) -> None:
	"""Reinicio controlado del proceso cuando el núcleo no se recupera."""
	global _restarting
	if _restarting:
		return
	_restarting = True
	log.error("El núcleo lleva %.0f s bloqueado: reinicio controlado de Tiresias", frozenFor)
	_recordRestart()
	try:
		ctypes.windll.kernel32.Beep(330, 120)
		ctypes.windll.kernel32.Beep(220, 160)
	except Exception:
		pass
	# La configuración se guarda solo si nadie la tiene bloqueada.
	if conf._lock.acquire(timeout=2):
		try:
			if conf["general"]["saveConfigurationOnExit"]:
				conf.save()
		except Exception:
			log.exception("No se pudo guardar la configuración antes del reinicio")
		finally:
			conf._lock.release()
	from . import core, paths

	cmd = core._launchCommand() + ["--data", paths.DATA_DIR] + core.restartArguments()
	try:
		subprocess.Popen(cmd, close_fds=True)
		# Para el guardián: es un reinicio (espera a la copia nueva). Si no se
		# pudo iniciar, no hay marcador y el guardián lo trata como un fallo.
		from .coexist import guardian

		guardian.writeMarkerNow("restart")
	except OSError:
		log.exception("No se pudo iniciar la copia nueva")
	flushAndExit(3)


def flushAndExit(code: int) -> None:
	"""Vuelca el registro (con plazo) y termina el proceso sin esperar al núcleo.

	No se usa ``logging.shutdown``: toma el cerrojo de cada manejador sin plazo
	y, si el núcleo bloqueado tenía uno, el vigilante se quedaría también
	bloqueado y el proceso no terminaría nunca.
	"""
	try:
		from . import log as logModule

		logModule.flush(2.0)
	except Exception:
		pass
	try:
		from . import crash_log

		crash_log.uninstall()
	except Exception:
		pass
	# Los ganchos y los demás recursos del sistema se liberan al terminar el proceso.
	os._exit(code)
