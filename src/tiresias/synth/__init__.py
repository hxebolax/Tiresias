"""Gestión de sintetizadores: registro, carga, cambio y ajustes.

Los complementos pueden aportar sintetizadores colocando módulos en su
carpeta ``synthDrivers``; el gestor de complementos los registra con
:func:`registerDriverModule`.
"""

from __future__ import annotations

import importlib
import types
from typing import Any

from ..config import conf
from ..extension_points import Action
from ..i18n import _
from ..log import getLogger
from .base import SynthDriver, SynthSetting, VoiceInfo, synthFailed  # noqa: F401 (reexportación)

log = getLogger("synthHandler")

#: Orden de la lista y del modo automático (tras ``synthPriority``). Las voces
#: de 32 bits (``sapi5_32`` y ``sapi4``, con un proceso auxiliar) van detrás de
#: todos: solo se eligen solas si no funciona ningún otro.
BUILTIN_DRIVERS = ("espeak", "onecore", "sapi5", "piper", "sapi5_32", "sapi4", "silence")

conf.registerDefaults(
	"speech",
	{
		# Quitar el silencio del principio de cada enunciado (menos latencia).
		"trimLeadingSilence": True,
		# Si el sintetizador falla en plena sesión, cambiar a otro disponible.
		"synthFallback": True,
	},
)

#: Segundos sintetizando un mismo bloque a partir de los que se considera colgado.
STALL_TIMEOUT = 20.0
_watchdogTimer: int | None = None

_externalModules: dict[str, types.ModuleType] = {}
_current: SynthDriver | None = None

#: Se notifica tras cambiar de sintetizador: ``synth``.
synthChanged = Action()
#: Se notifica al entrar o salir de la espera ante otro lector: ``standby``.
standbyChanged = Action()


def registerDriverModule(name: str, module: types.ModuleType) -> None:
	_externalModules[name] = module


def unregisterDriverModule(name: str) -> None:
	_externalModules.pop(name, None)


def _getDriverClass(name: str) -> type[SynthDriver]:
	if name in _externalModules:
		return _externalModules[name].SynthDriver
	if name in BUILTIN_DRIVERS:
		mod = importlib.import_module(f"{__name__}.{name}")
		return mod.SynthDriver
	raise LookupError(f"Sintetizador desconocido: {name}")


def getDriverNames() -> list[str]:
	names = list(_externalModules) + [n for n in BUILTIN_DRIVERS if n not in _externalModules]
	return names


def getSynthList() -> list[tuple[str, str]]:
	"""Sintetizadores disponibles en este equipo: [(nombre, descripción)]."""
	result = []
	for name in getDriverNames():
		try:
			cls = _getDriverClass(name)
			if cls.check():
				result.append((name, cls.description or name))
		except Exception:
			log.debug("Sintetizador %s no disponible", name, exc_info=True)
	return result


def getSynth() -> SynthDriver | None:
	return _current


# ------------------------------------------------------------------ espera (convivencia con otros lectores)
#: Tiresias está en espera ante otro lector (:mod:`tiresias.coexist`).
_standby = False


def isStandby() -> bool:
	return _standby


def setStandby(value: bool) -> None:
	"""Reposo del sintetizador mientras Tiresias está en espera (hilo del núcleo).

	En espera no se habla, así que los sintetizadores que lo admiten
	(``releaseResources``/``restoreResources``, p. ej. Eloquence con su
	proceso de 32 bits) sueltan sus recursos; al activarse se recuperan antes
	del anuncio. Si la recuperación falla se cambia a otro sintetizador.
	"""
	global _standby
	value = bool(value)
	if value == _standby:
		return
	_standby = value
	try:
		# La atenuación y la división del sonido se retiran en espera (no se
		# toca el audio del otro lector) y se vuelven a aplicar al activarse.
		standbyChanged.notify(standby=value)
	except Exception:
		log.exception("Error avisando del cambio de espera")
	cur = _current
	if cur is None:
		return
	if value:
		_releaseForStandby(cur)
		return
	restore = getattr(cur, "restoreResources", None)
	if restore is None:
		return
	try:
		restore()
	except Exception as e:
		log.exception("No se pudo reanudar el sintetizador %s", cur.name)
		if conf["speech"]["synthFallback"]:
			fallbackFrom(cur.name, str(e) or type(e).__name__)


def _releaseForStandby(synth: SynthDriver) -> None:
	release = getattr(synth, "releaseResources", None)
	if release is None:
		return
	try:
		synth.cancel()
		release()
	except Exception:
		log.exception("No se pudieron liberar los recursos de %s", synth.name)


def _settingsSection(name: str) -> dict:
	synths = conf["speech"]["synths"]
	try:
		section = synths[name]
		return section.dict() if hasattr(section, "dict") else dict(section)
	except KeyError:
		return {}


def saveCurrentSettings() -> None:
	if not _current:
		return
	settings = _current.saveableSettings()
	try:
		# Si suena la voz de un contexto (foros 2.3), se guarda la voz normal.
		from ..speech import api as speechApi

		settings = speechApi.savedSynthSettings(_current, settings)
	except Exception:
		log.debug("No se pudo comprobar la voz de contexto", exc_info=True)
	conf["speech"]["synths"][_current.name] = settings


def _instantiate(name: str) -> SynthDriver:
	cls = _getDriverClass(name)
	if not cls.check():
		raise RuntimeError(f"{name} no está disponible")
	synth = cls()
	synth.loadSettings(_settingsSection(name))
	return synth


def setSynth(name: str | None, isFallback: bool = False) -> bool:
	"""Carga el sintetizador indicado (``"auto"`` elige el mejor)."""
	global _current
	if name in (None, "", "auto"):
		order = list(conf["speech"]["synthPriority"]) + [n for n in getDriverNames() if n != "silence"]
		seen: list[str] = []
		for candidate in order:
			if candidate in seen:
				continue
			seen.append(candidate)
			if _trySet(candidate):
				return True
		return _trySet("silence")
	if _trySet(name):
		return True
	if not isFallback:
		log.warning("No se pudo cargar %s; se usará la selección automática", name)
		return setSynth("auto", isFallback=True)
	return False


def _trySet(name: str) -> bool:
	global _current
	old = _current
	if old is not None and old.name == name:
		# El mismo controlador otra vez (al aplicar una configuración importada o
		# volver a elegirlo): eSpeak, Eloquence... usan una biblioteca con estado
		# global en el proceso. Si se crea el nuevo antes de cerrar el viejo, el
		# cierre del viejo destruye el estado del nuevo y la síntesis falla con
		# una violación de acceso. Primero se cierra el anterior.
		try:
			saveCurrentSettings()
			old.cancel()
			old.terminate()
		except Exception:
			log.exception("Error cerrando el sintetizador anterior")
		_current = old = None
	try:
		newSynth = _instantiate(name)
	except Exception:
		log.info("No se pudo cargar el sintetizador %s", name, exc_info=True)
		return False
	if old:
		try:
			saveCurrentSettings()
			old.cancel()
			old.terminate()
		except Exception:
			log.exception("Error cerrando el sintetizador anterior")
	_current = newSynth
	if _standby:
		# Cargado en espera: sin recursos hasta que Tiresias se active.
		_releaseForStandby(newSynth)
	log.info("Sintetizador cargado: %s", name)
	synthChanged.notify(synth=newSynth)
	_startWatchdog()
	return True


# ------------------------------------------------------------------ fallos en plena sesión
def _fallbackOrder(failed: str) -> list[str]:
	order = list(conf["speech"]["synthPriority"]) + getDriverNames()
	out: list[str] = []
	for n in order:
		if n not in out and n not in (failed, "silence"):
			out.append(n)
	return out


def fallbackFrom(failedName: str, reason: str = "") -> str | None:
	"""Cambia a otro sintetizador porque ``failedName`` ha dejado de funcionar.

	No cambia la opción guardada (al reiniciar se volverá a intentar el
	elegido). Devuelve el nombre del sintetizador cargado o ``None``.
	"""
	cur = _current
	if cur is None or cur.name != failedName:
		return None
	log.warning("El sintetizador %s ha fallado (%s); se busca otro", failedName, reason or "error")
	failedDesc = cur.description or failedName
	for candidate in _fallbackOrder(failedName):
		if _trySet(candidate):
			break
	else:
		_trySet("silence")
	new = _current
	if new is None or new.name == failedName:
		return None
	try:
		from .. import speech

		# Con prioridad «ahora»: se oye antes que lo que quedó a medias con el
		# sintetizador anterior (el gestor de voz lo reanuda después).
		speech.speakMessage(
			_("El sintetizador {old} ha fallado. Se usa {new}.").format(old=failedDesc, new=new.description or new.name),
			priority=speech.Priority.NOW,
		)
	except Exception:
		log.debug("No se pudo anunciar el cambio de sintetizador", exc_info=True)
	return new.name


def _onSynthFailed(synth=None, error=None) -> None:
	"""Llega desde el hilo de síntesis: el cambio se hace en el núcleo."""
	if synth is None or not conf["speech"]["synthFallback"]:
		return
	from .. import queue_handler

	queue_handler.queueFunction(fallbackFrom, synth.name, str(error or ""))


synthFailed.register(_onSynthFailed)


def _startWatchdog() -> None:
	global _watchdogTimer
	if _watchdogTimer is not None:
		return
	try:
		from .. import queue_handler
	except Exception:
		return
	_watchdogTimer = queue_handler.callLater(3000, _watchdog)


def _watchdog() -> None:
	"""Comprueba cada 3 s que el sintetizador actual no esté colgado."""
	global _watchdogTimer
	_watchdogTimer = None
	cur = _current
	if cur is None:
		return
	isStalled = getattr(cur, "isStalled", None)
	if isStalled is not None and conf["speech"]["synthFallback"] and cur.name != "silence":
		try:
			if isStalled(STALL_TIMEOUT):
				fallbackFrom(cur.name, _("no responde"))
		except Exception:
			log.exception("Error vigilando el sintetizador")
	_startWatchdog()


def changeSetting(settingId: str, value: Any) -> None:
	if not _current:
		return
	_current.setSetting(settingId, value)
	saveCurrentSettings()
	if settingId == "voice":
		# El diccionario de voz depende de la voz (también al cambiarla desde el anillo).
		try:
			from .. import core

			reload = getattr(core, "_loadVoiceDict", None)
			if reload:
				reload()
		except Exception:
			log.debug("No se pudo recargar el diccionario de voz", exc_info=True)


def terminate() -> None:
	global _current, _watchdogTimer
	if _watchdogTimer is not None:
		try:
			from .. import queue_handler

			queue_handler.cancelCallLater(_watchdogTimer)
		except Exception:
			pass
		_watchdogTimer = None
	if _current:
		try:
			saveCurrentSettings()
			_current.cancel()
			_current.terminate()
		except Exception:
			log.exception("Error terminando el sintetizador")
		_current = None


# ------------------------------------------------------------------ anillo
class SettingsRing:
	"""Anillo de ajustes de voz (tecla Tiresias+Control+flechas)."""

	def __init__(self) -> None:
		self._index = 0

	def _settings(self) -> list[SynthSetting]:
		if not _current:
			return []
		return [s for s in _current.supportedSettings if s.availableInRing]

	@property
	def current(self) -> SynthSetting | None:
		settings = self._settings()
		if not settings:
			return None
		self._index %= len(settings)
		return settings[self._index]

	def move(self, direction: int) -> SynthSetting | None:
		settings = self._settings()
		if not settings:
			return None
		self._index = (self._index + direction) % len(settings)
		return settings[self._index]

	def describe(self) -> str:
		s = self.current
		if not s or not _current:
			return _("Sin ajustes")
		return f"{s.displayName} {self.valueText(s)}"

	def valueText(self, s: SynthSetting) -> str:
		assert _current
		value = _current.getSetting(s.id)
		if s.kind == "boolean":
			return _("activado") if value else _("desactivado")
		if s.kind == "choice":
			choices = _current.getChoices(s.id)
			item = choices.get(value)
			if isinstance(item, VoiceInfo):
				return item.displayName
			return str(item) if item is not None else str(value)
		return str(value)

	def change(self, steps: int, large: bool = False) -> str:
		s = self.current
		if not s or not _current:
			return _("Sin ajustes")
		if s.kind == "numeric":
			step = s.largeStep if large else s.normalStep
			value = _current.getSetting(s.id) or 0
			changeSetting(s.id, value + steps * step)
		elif s.kind == "boolean":
			changeSetting(s.id, not _current.getSetting(s.id))
		elif s.kind == "choice":
			keys = list(_current.getChoices(s.id).keys())
			if keys:
				cur = _current.getSetting(s.id)
				i = keys.index(cur) if cur in keys else 0
				i = max(0, min(len(keys) - 1, i + steps * (5 if large else 1)))
				changeSetting(s.id, keys[i])
		return self.valueText(s)


ring = SettingsRing()
