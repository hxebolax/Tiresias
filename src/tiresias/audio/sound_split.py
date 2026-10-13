"""División del sonido: Tiresias por un canal y el resto de aplicaciones por otro."""

from __future__ import annotations

import json
import os
import threading

from .. import paths, queue_handler
from ..config import conf
from ..i18n import _
from ..log import getLogger
from . import core_audio
from .wave_player import OutputSettings

log = getLogger("soundSplit")

# modo -> (ganancias de Tiresias (izq, der), ganancias de las demás aplicaciones, etiqueta)
MODES: dict[str, tuple[tuple[float, float], tuple[float, float], str]] = {
	"off": ((1.0, 1.0), (1.0, 1.0), _("División de sonido desactivada")),
	"leftRight": ((1.0, 0.0), (0.0, 1.0), _("Tiresias a la izquierda y aplicaciones a la derecha")),
	"rightLeft": ((0.0, 1.0), (1.0, 0.0), _("Tiresias a la derecha y aplicaciones a la izquierda")),
	"leftBoth": ((1.0, 0.0), (1.0, 1.0), _("Tiresias a la izquierda y aplicaciones en ambos canales")),
	"rightBoth": ((0.0, 1.0), (1.0, 1.0), _("Tiresias a la derecha y aplicaciones en ambos canales")),
	"bothLeft": ((1.0, 1.0), (1.0, 0.0), _("Tiresias en ambos canales y aplicaciones a la izquierda")),
	"bothRight": ((1.0, 1.0), (0.0, 1.0), _("Tiresias en ambos canales y aplicaciones a la derecha")),
}
ORDER = list(MODES)

_timer: int | None = None
#: ``True`` si Tiresias ha cambiado el balance de las demás aplicaciones (y,
#: por tanto, tiene que devolverlo al centro al desactivar la división).
_appliedApps = False
#: Identificadores estables de las sesiones cuyo balance ha cambiado
#: Tiresias. Windows recuerda el balance de cada aplicación aunque se cierre:
#: se guardan en disco para devolverlas al centro también tras un cierre
#: inesperado o cuando vuelvan a abrirse (hilo de sesiones, con ``_lock``).
_touched: set[str] = set()
_lock = threading.Lock()
_applyQueued = False
_standbyRegistered = False
_STATE_FILE = "soundsplit.json"


def _stateFile() -> str:
	return os.path.join(paths.cacheDir(), _STATE_FILE)


def _loadTouched() -> set[str]:
	try:
		with open(_stateFile(), encoding="utf-8") as f:
			data = json.load(f)
		return {str(x) for x in data} if isinstance(data, list) else set()
	except (OSError, ValueError):
		return set()


def _saveTouched() -> None:
	with _lock:
		data = sorted(_touched)
	try:
		if not data:
			os.remove(_stateFile())
			return
		os.makedirs(paths.cacheDir(), exist_ok=True)
		tmp = _stateFile() + ".tmp"
		with open(tmp, "w", encoding="utf-8") as f:
			json.dump(data, f)
		os.replace(tmp, _stateFile())
	except OSError:
		pass


def _isStandby() -> bool:
	try:
		from .. import synth

		return synth.isStandby()
	except Exception:
		return False


def _registerStandby() -> None:
	global _standbyRegistered
	if _standbyRegistered:
		return
	try:
		from .. import synth

		synth.standbyChanged.register(_onStandby)
		_standbyRegistered = True
	except Exception:
		log.debug("No se pudo registrar el aviso de espera", exc_info=True)


def _onStandby(standby: bool = False, **kwargs) -> None:
	apply()


def apply(mode: str | None = None) -> None:
	"""Aplica el modo de división (al arrancar, al guardar las opciones y al cambiar de perfil)."""
	global _timer, _appliedApps
	_registerStandby()
	mode = mode or conf["audio"]["soundSplitMode"]
	if mode not in MODES:
		mode = "off"
	own, apps, _label = MODES[mode]
	OutputSettings.channelGains = own
	# En espera ante otro lector no se toca el balance de nadie (el del otro
	# lector menos que nadie: con su propia división, cada uno anulaba al otro).
	toApps = bool(conf["audio"]["soundSplitApplyToOtherApps"]) and mode != "off" and not _isStandby()
	if toApps:
		_queueApply(apps)
		_appliedApps = True
	else:
		# Se devuelven al centro las que cambió Tiresias (también las de una
		# sesión anterior que terminó de forma inesperada).
		_queueApply((1.0, 1.0))
		_appliedApps = False
	if _timer is not None:
		queue_handler.cancelCallLater(_timer)
		_timer = None
	if toApps:
		# Las aplicaciones que empiezan a sonar más tarde también se dividen.
		_timer = queue_handler.callLater(3000, apply)
	elif _touched or os.path.exists(_stateFile()):
		# Quedan aplicaciones con el balance cambiado que ahora no suenan: se
		# centran cuando vuelvan a abrirse.
		_timer = queue_handler.callLater(10000, apply)


def _queueApply(gains: tuple[float, float]) -> None:
	global _applyQueued
	if _applyQueued and gains != (1.0, 1.0):
		# Ya hay una aplicación pendiente en el hilo de sesiones.
		return
	_applyQueued = True
	core_audio.runInSessionThread(_applyToApps, gains)


def _shouldSplit(s) -> bool:
	if s.pid in (core_audio.OWN_PID, 0):
		return False
	if getattr(s, "isSystemSounds", lambda: False)():
		return False
	from .ducking import NEVER_DUCK, _processName

	# Ni el mezclador de Windows ni otros lectores de pantalla.
	return _processName(s.pid) not in NEVER_DUCK


def _applyToApps(gains: tuple[float, float]) -> None:
	"""Pone el balance de las demás aplicaciones (hilo de sesiones de audio).

	Solo en sesiones estéreo (como NVDA): en una sesión mono, «solo derecha»
	ponía a cero su único canal (la aplicación quedaba muda) y en 5.1 se
	quitaba el canal central (los diálogos). Con ``(1, 1)`` se devuelven al
	centro las sesiones que había cambiado Tiresias, también las de una
	ejecución anterior (por su identificador estable).
	"""
	global _applyQueued
	_applyQueued = False
	center = gains == (1.0, 1.0)
	with _lock:
		if not _touched:
			_touched.update(_loadTouched())
		touched = set(_touched)
	if center and not touched:
		return
	changed = False
	# Todas las salidas activas, no solo la predeterminada.
	for s in core_audio.getSessions(allDevices=True):
		key = getattr(s, "sessionIdentifier", "") or s.identifier
		if center:
			if key not in touched:
				continue
		elif not _shouldSplit(s):
			continue
		try:
			cv = s.channelVolume()
			n = cv.GetChannelCount()
			if n != 2:
				if center:
					with _lock:
						_touched.discard(key)
				continue
			for ch in range(2):
				level = gains[ch]
				if abs(cv.GetChannelVolume(ch) - level) > 0.001:
					cv.SetChannelVolume(ch, level, None)
			with _lock:
				if center:
					_touched.discard(key)
				elif key not in _touched:
					_touched.add(key)
				else:
					continue
			changed = True
		except Exception:
			log.debug("No se pudo dividir la sesión de %d", s.pid, exc_info=True)
	if changed or center:
		_saveTouched()


def includedModes() -> list[str]:
	"""Modos que recorre :func:`cycle` (``includedSoundSplitModes``), en orden."""
	try:
		wanted = set(conf["audio"]["includedSoundSplitModes"])
	except (KeyError, TypeError):
		wanted = set(ORDER)
	modes = [m for m in ORDER if m in wanted]
	return modes or ["off"]


def nextMode(current: str, included: list[str]) -> str:
	"""Modo siguiente a ``current`` entre ``included`` (en el orden de :data:`ORDER`)."""
	if current in included:
		return included[(included.index(current) + 1) % len(included)]
	# El modo actual no está incluido: el siguiente incluido según ORDER.
	i = ORDER.index(current) if current in ORDER else -1
	for m in ORDER[i + 1 :] + ORDER[: i + 1]:
		if m in included:
			return m
	return included[0]


def cycle() -> str:
	cur = conf["audio"]["soundSplitMode"]
	nxt = nextMode(cur, includedModes())
	conf["audio"]["soundSplitMode"] = nxt
	apply(nxt)
	return MODES[nxt][2]


def terminate() -> None:
	global _timer, _appliedApps
	if _timer is not None:
		queue_handler.cancelCallLater(_timer)
		_timer = None
	if _appliedApps or _touched:
		_appliedApps = False
		core_audio.runInSessionThread(_applyToApps, (1.0, 1.0))
		core_audio.waitSessionThread(3.0)
	if _standbyRegistered:
		try:
			from .. import synth

			synth.standbyChanged.unregister(_onStandby)
		except Exception:
			pass
		globals()["_standbyRegistered"] = False
