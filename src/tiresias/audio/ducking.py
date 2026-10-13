"""Atenuación (ducking): baja el volumen de otras aplicaciones mientras se habla.

- Mientras dura la atenuación, las aplicaciones que empiezan a sonar después
  también se atenúan (se revisan las sesiones nuevas cada segundo).
- Con ``duckForSounds`` los sonidos y pitidos de Tiresias también atenúan
  (salvo si los sonidos están desactivados o su volumen es 0).
- Nunca se atenúa el mezclador de volumen de Windows (sndvol.exe, #5752) ni
  los sonidos del sistema.
- Al callar la voz (Control, cambio de foco...) también se quita la
  atenuación «mientras se habla».

Recorrer las sesiones de audio se hace en el hilo de sesiones de
:mod:`core_audio`, nunca en el núcleo: :func:`duck` y :func:`unduck` solo
cambian el estado pedido y encargan el trabajo a ese hilo, que lo hace en
orden.

Los volúmenes originales se guardan en ``data/cache/ducking.json`` para poder
restaurarlos aunque Tiresias se cierre de forma inesperada. El mezclador usa
:func:`sessionVolume` y :func:`setSessionVolume` para que sus cambios se
hagan sobre el volumen original y la atenuación no los deshaga.
"""

from __future__ import annotations

import json
import os
import threading

from .. import paths, queue_handler
from ..config import conf
from ..i18n import _
from ..log import getLogger
from . import core_audio

log = getLogger("ducking")

MODES = {
	"off": _("Sin atenuación de otras aplicaciones"),
	"speaking": _("Atenuar otras aplicaciones mientras se habla"),
	"always": _("Atenuar siempre otras aplicaciones"),
}
ORDER = list(MODES)

#: Procesos que nunca se atenúan: el mezclador de Windows y los lectores de
#: pantalla (atenuar a NVDA o a JAWS dejaría al usuario sin su otro lector, y
#: Windows recuerda ese volumen aunque se reinicien).
NEVER_DUCK = {
	"sndvol.exe",
	"nvda.exe",
	"nvda_slave.exe",
	"nvda_noUIAccess.exe".lower(),
	"nvda_uiaccess.exe",
	"jfw.exe",
	"narrator.exe",
	"zt.exe",
	"ztmag32.exe",
	"supernova.exe",
	"dolphin.exe",
}
#: Tolerancia al comparar volúmenes (Windows los guarda como float).
_EPS = 0.02
#: Cada cuánto se buscan sesiones nuevas mientras hay atenuación (ms).
RESCAN_MS = 1000
#: Tras un sonido sin voz, cuánto se espera para restaurar el volumen (ms).
SOUND_HOLD_MS = 900
#: Tras callar o terminar la voz, cuánto se espera para restaurar el volumen (ms).
SPEECH_HOLD_MS = 400

#: Volumen original de cada aplicación atenuada, por el identificador
#: **estable** de su sesión (sin PID): Windows recuerda el volumen de cada
#: aplicación con esa clave, así que es la que sirve para restaurarlo aunque
#: la aplicación se haya cerrado y vuelto a abrir. Se guarda en disco. Lo usan
#: el hilo de sesiones y el mezclador, siempre con ``_lock``.
_saved: dict[str, float] = {}
#: Instancias de sesión atenuadas ahora (identificador de instancia ->
#: identificador estable), para no atenuar dos veces la misma.
_duckedInstances: dict[str, str] = {}
#: Hay un trabajo de atenuación encolado (no se encolan más hasta que empiece).
_duckJobQueued = False
#: Estado pedido (lo cambia el núcleo; el hilo de sesiones lo hace realidad).
_ducked = False
#: Factor aplicado a las sesiones atenuadas (``duckingLevel`` / 100).
_level = 1.0
_lock = threading.RLock()
_unduckTimer: int | None = None
_rescanTimer: int | None = None
_names: dict[int, str] = {}


def _stateFile() -> str:
	return os.path.join(paths.cacheDir(), "ducking.json")


def _persist() -> None:
	"""Guarda los volúmenes originales (ver :func:`_persistPending`)."""
	_persistPending()


def _loadStateFile() -> dict[str, float]:
	try:
		with open(_stateFile(), encoding="utf-8") as f:
			data = json.load(f)
	except (OSError, ValueError):
		return {}
	out: dict[str, float] = {}
	if isinstance(data, dict):
		for k, v in data.items():
			try:
				out[str(_stableKey(str(k)))] = max(0.0, min(1.0, float(v)))
			except (TypeError, ValueError):
				continue
	return out


def _stableKey(identifier: str) -> str:
	"""Identificador estable a partir de uno de instancia (archivos de versiones anteriores).

	El de instancia acaba en ``|<n>%b<PID>``; el estable no lleva esa parte.
	"""
	if "|" in identifier and identifier.rsplit("%b", 1)[-1].isdigit():
		return identifier.rsplit("|", 1)[0]
	return identifier


def _removeStateFile() -> None:
	try:
		os.remove(_stateFile())
	except OSError:
		pass


def _confLevel() -> float:
	try:
		return max(0, min(100, int(conf["audio"]["duckingLevel"]))) / 100.0
	except (KeyError, TypeError, ValueError):
		return 0.25


def _processName(pid: int) -> str:
	name = _names.get(pid)
	if name is None:
		try:
			import psutil

			name = psutil.Process(pid).name().lower()
		except Exception:
			name = ""
		if len(_names) > 500:
			_names.clear()
		_names[pid] = name
	return name


def shouldDuck(pid: int) -> bool:
	"""``True`` si la sesión del proceso ``pid`` debe atenuarse."""
	if pid in (core_audio.OWN_PID, 0):
		return False
	return _processName(pid) not in NEVER_DUCK


def _sessionKey(s) -> str:
	return getattr(s, "sessionIdentifier", "") or _stableKey(s.identifier or "")


def _isStandby() -> bool:
	"""Tiresias está en espera ante otro lector: no se toca el audio de nadie."""
	try:
		from .. import synth

		return synth.isStandby()
	except Exception:
		return False


# ---------------------------------------------------------------- hilo de sesiones
def _restoreSession(s, original: float, applied: float | None) -> bool:
	"""Devuelve una sesión a su volumen ``original``.

	Si ``applied`` (el volumen que puso Tiresias) ya no coincide con el actual,
	el usuario lo ha cambiado mientras estaba atenuada: se respeta el suyo.
	"""
	try:
		sv = s.simpleVolume()
		if applied is not None and abs(sv.GetMasterVolume() - applied) > _EPS:
			return True
		sv.SetMasterVolume(original, None)
		return True
	except Exception:
		return False


def _restoreFromCrashJob() -> None:
	"""Restaura los volúmenes que una sesión anterior de Tiresias dejó bajados.

	Se busca por el identificador estable: sirve aunque la aplicación se haya
	reiniciado (otro PID). Las aplicaciones que no están abiertas ahora se
	quedan en el archivo y se restauran cuando vuelvan a sonar.
	"""
	data = _loadStateFile()
	if not data:
		_removeStateFile()
		return
	level = _confLevel()
	restored: set[str] = set()
	for s in core_audio.getSessions(allDevices=True):
		key = _sessionKey(s)
		if key in data and key not in restored:
			if _restoreSession(s, data[key], data[key] * level):
				restored.add(key)
	with _lock:
		for key, vol in data.items():
			if key not in restored:
				_pendingRestore[key] = vol
	_persistPending()


#: Volúmenes de una sesión anterior aún sin restaurar (aplicación cerrada).
_pendingRestore: dict[str, float] = {}


def _persistPending() -> None:
	with _lock:
		merged = dict(_pendingRestore)
		merged.update(_saved)
	try:
		if not merged:
			_removeStateFile()
			return
		os.makedirs(paths.cacheDir(), exist_ok=True)
		tmp = _stateFile() + ".tmp"
		with open(tmp, "w", encoding="utf-8") as f:
			json.dump(merged, f)
		os.replace(tmp, _stateFile())
	except OSError:
		pass


def _restorePendingFor(sessions: list) -> bool:
	"""Restaura las aplicaciones de una sesión anterior que han vuelto a sonar."""
	if not _pendingRestore:
		return False
	level = _confLevel()
	changed = False
	for s in sessions:
		key = _sessionKey(s)
		with _lock:
			vol = _pendingRestore.get(key)
		if vol is None:
			continue
		if _restoreSession(s, vol, vol * level):
			with _lock:
				_pendingRestore.pop(key, None)
			changed = True
	return changed


def restoreFromCrash() -> None:
	"""Restaura volúmenes que quedaron bajados en una sesión anterior."""
	core_audio.runInSessionThread(_restoreFromCrashJob)


def _duckSessions(sessions: list | None = None) -> int:
	"""Atenúa las sesiones activas que aún no lo están. Devuelve cuántas se atenuaron.

	La enumeración se hace sin ``_lock`` (puede tardar con un controlador
	lento y el mezclador, en el núcleo, también lo toma); el cerrojo solo
	protege los diccionarios.
	"""
	if sessions is None:
		sessions = core_audio.getSessions(allDevices=True)
	_restorePendingFor(sessions)
	count = 0
	for s in sessions:
		inst = s.identifier
		if not inst or not shouldDuck(s.pid):
			continue
		with _lock:
			if not _ducked or inst in _duckedInstances:
				continue
			level = _level
		# Las sesiones inactivas no se tocan (no suenan; Windows recordaría el
		# volumen bajado): se atenúan cuando empiezan a sonar (revisión cada segundo).
		if s.state() != 1:
			continue
		if getattr(s, "isSystemSounds", lambda: False)():
			continue
		key = _sessionKey(s)
		try:
			sv = s.simpleVolume()
			cur = sv.GetMasterVolume()
			with _lock:
				if not _ducked:
					break
				# Otra instancia de la misma aplicación ya guardó el original.
				original = _saved.setdefault(key, cur)
				_duckedInstances[inst] = key
			sv.SetMasterVolume(original * level, None)
			count += 1
		except Exception:
			continue
	return count


def _duckJob() -> None:
	global _duckJobQueued
	_duckJobQueued = False
	if not _ducked or _isStandby():
		return
	if _duckSessions():
		_persistPending()


def _queueDuckJob() -> None:
	"""Encola un trabajo de atenuación si no hay ya uno esperando."""
	global _duckJobQueued
	if _duckJobQueued:
		return
	_duckJobQueued = True
	core_audio.runInSessionThread(_duckJob)


def _restoreSessions() -> None:
	with _lock:
		instances = dict(_duckedInstances)
		saved = dict(_saved)
		level = _level
	if not instances and not saved:
		_persistPending()
		return
	restoredKeys: set[str] = set()
	sessions = core_audio.getSessions(allDevices=True)
	_restorePendingFor(sessions)
	for s in sessions:
		key = instances.get(s.identifier)
		if key is None:
			continue
		vol = saved.get(key)
		if vol is not None and _restoreSession(s, vol, vol * level):
			restoredKeys.add(key)
	with _lock:
		if _ducked:
			# Se volvió a atenuar mientras se restauraba: se deja como está.
			return
		# Las aplicaciones atenuadas que se cerraron mientras tanto pasan a
		# «pendientes»: Windows recuerda su volumen bajado y se les devolverá
		# el original en cuanto vuelvan a sonar (o en el próximo arranque).
		for key, vol in saved.items():
			if key not in restoredKeys:
				_pendingRestore[key] = vol
		_saved.clear()
		_duckedInstances.clear()
	_persistPending()


def _unduckJob() -> None:
	if _ducked:
		# Se volvió a pedir la atenuación antes de llegar aquí.
		return
	_restoreSessions()


def _relevelJob() -> None:
	"""Aplica el nuevo volumen de atenuación a las sesiones ya atenuadas."""
	if not _ducked:
		return
	sessions = core_audio.getSessions(allDevices=True)
	with _lock:
		instances = dict(_duckedInstances)
		saved = dict(_saved)
		level = _level
	for s in sessions:
		key = instances.get(s.identifier)
		vol = saved.get(key) if key else None
		if vol is None:
			continue
		try:
			s.simpleVolume().SetMasterVolume(vol * level, None)
		except Exception:
			continue
	if _duckSessions(sessions):
		_persistPending()


# ---------------------------------------------------------------- mezclador
def sessionVolume(session) -> float:
	"""Volumen de una sesión sin la atenuación (el que tendrá al restaurarla)."""
	with _lock:
		key = _duckedInstances.get(session.identifier)
		saved = _saved.get(key) if key else None
	if saved is not None:
		return saved
	return session.simpleVolume().GetMasterVolume()


def setSessionVolume(session, level: float, context=None) -> None:
	"""Cambia el volumen de una sesión respetando la atenuación.

	Si la sesión está atenuada, ``level`` pasa a ser su volumen original (el
	que se restaurará) y la sesión queda con ese volumen atenuado.
	"""
	with _lock:
		key = _duckedInstances.get(session.identifier)
		if key is not None and key in _saved:
			_saved[key] = level
			level = level * _level
			changed = True
		else:
			changed = False
	if changed:
		_persistPending()
	session.simpleVolume().SetMasterVolume(level, context)


# ---------------------------------------------------------------- núcleo
def duck() -> None:
	global _ducked, _level
	if _ducked:
		return
	if _isStandby():
		# En espera habla el otro lector: Tiresias no toca el volumen de nadie.
		return
	_level = _confLevel()
	_ducked = True
	_queueDuckJob()
	_scheduleRescan()


def _scheduleRescan() -> None:
	global _rescanTimer
	if _rescanTimer is None:
		_rescanTimer = queue_handler.callLater(RESCAN_MS, _rescan)


def _rescan() -> None:
	"""Atenúa las aplicaciones que han empezado a sonar durante la atenuación."""
	global _rescanTimer
	_rescanTimer = None
	if not _ducked:
		return
	if _isStandby():
		# Tiresias ha pasado a espera con la atenuación puesta: se quita.
		unduck()
		return
	if conf["audio"]["duckingMode"] == "speaking" and not _isSpeaking() and _unduckTimer is None:
		# Atenuado sin voz y sin restauración programada (se perdió el aviso
		# de fin): no se deja atenuado para siempre.
		_scheduleUnduck(SPEECH_HOLD_MS)
	_queueDuckJob()
	_scheduleRescan()


def unduck() -> None:
	global _ducked, _rescanTimer
	if _rescanTimer is not None:
		queue_handler.cancelCallLater(_rescanTimer)
		_rescanTimer = None
	if not _ducked:
		return
	_ducked = False
	core_audio.runInSessionThread(_unduckJob)


def isDucked() -> bool:
	return _ducked


def _cancelUnduck() -> None:
	global _unduckTimer
	if _unduckTimer is not None:
		queue_handler.cancelCallLater(_unduckTimer)
		_unduckTimer = None


def _isSpeaking() -> bool:
	try:
		from .. import synth

		s = synth.getSynth()
	except Exception:
		return False
	if s is None or not getattr(s, "_speaking", False):
		return False
	# La marca del sintetizador puede quedarse puesta si se pierde su aviso
	# de fin (sintetizador colgado, reproductor caído): solo cuenta si de
	# verdad suena algo o el gestor de voz tiene algo pendiente.
	player = getattr(s, "_player", None)
	try:
		if player is not None and player.isPlaying():
			return True
	except Exception:
		return True
	try:
		from ..speech import api as speechApi

		return speechApi.isSpeaking()
	except Exception:
		return True


def _scheduleUnduck(delay: int) -> None:
	global _unduckTimer

	def later() -> None:
		global _unduckTimer
		_unduckTimer = None
		# Si mientras tanto ha empezado otro enunciado, se espera a su final
		# (synthDoneSpeaking vuelve a programar la restauración).
		if conf["audio"]["duckingMode"] == "speaking" and not _isSpeaking():
			unduck()

	_cancelUnduck()
	_unduckTimer = queue_handler.callLater(delay, later)


def _onSpeech(sequence=None) -> None:
	if conf["audio"]["duckingMode"] != "speaking":
		return
	_cancelUnduck()
	duck()


def _onDone(synth=None) -> None:
	if conf["audio"]["duckingMode"] != "speaking":
		return
	queue_handler.queueFunction(_scheduleUnduck, SPEECH_HOLD_MS)


def _onSpeechCanceled() -> None:
	"""Se ha callado la voz: el sintetizador no avisará del final, se restaura aquí."""
	if conf["audio"]["duckingMode"] != "speaking" or not _ducked:
		return
	queue_handler.queueFunction(_scheduleUnduck, SPEECH_HOLD_MS)


def _onSound(**kwargs) -> None:
	"""Un sonido o pitido de Tiresias: atenúa un momento (si está configurado)."""
	if conf["audio"]["duckingMode"] != "speaking" or not conf["audio"]["duckForSounds"]:
		return
	from . import tones

	# Un sonido que no se va a oír (sonidos desactivados o a volumen 0) no atenúa.
	if tones._soundVolume() <= 0:
		return

	def run() -> None:
		duck()
		if not _isSpeaking():
			_scheduleUnduck(SOUND_HOLD_MS)

	queue_handler.queueFunction(run)


def apply() -> None:
	"""Aplica el modo y el volumen de atenuación configurados (al arrancar, al guardar y al cambiar de perfil)."""
	global _level
	mode = conf["audio"]["duckingMode"]
	if mode == "always":
		level = _confLevel()
		if _ducked and abs(level - _level) > 0.001:
			# Cambió el «Volumen de las aplicaciones atenuadas»: se aplica ya.
			_level = level
			core_audio.runInSessionThread(_relevelJob)
		duck()
	else:
		unduck()


def cycle() -> str:
	cur = conf["audio"]["duckingMode"]
	nxt = ORDER[(ORDER.index(cur) + 1) % len(ORDER) if cur in ORDER else 0]
	conf["audio"]["duckingMode"] = nxt
	apply()
	return MODES[nxt]


def _onStandby(standby: bool = False, **kwargs) -> None:
	if standby:
		_cancelUnduck()
		unduck()
	else:
		apply()


def initialize() -> None:
	from .. import speech, synth
	from ..synth import base
	from . import tones

	restoreFromCrash()
	synth.standbyChanged.register(_onStandby)
	speech.pre_speech.register(_onSpeech)
	speech.pre_speechCanceled.register(_onSpeechCanceled)
	base.synthDoneSpeaking.register(_onDone)
	tones.pre_playSound.register(_onSound)
	tones.pre_beep.register(_onSound)
	apply()


def terminate() -> None:
	from .. import speech, synth
	from ..synth import base
	from . import tones

	try:
		synth.standbyChanged.unregister(_onStandby)
	except Exception:
		pass
	for action, handler in (
		(tones.pre_playSound, _onSound),
		(tones.pre_beep, _onSound),
		(speech.pre_speech, _onSpeech),
		(speech.pre_speechCanceled, _onSpeechCanceled),
		(base.synthDoneSpeaking, _onDone),
	):
		try:
			action.unregister(handler)
		except Exception:
			pass
	_cancelUnduck()
	unduck()
	# Los volúmenes tienen que quedar restaurados antes de cerrar.
	core_audio.waitSessionThread(3.0)
