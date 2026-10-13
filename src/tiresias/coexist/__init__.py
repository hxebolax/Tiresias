"""Convivencia con otros lectores de pantalla (NVDA, JAWS, Narrador...).

Tiresias es para cuando no hay ningún lector de pantalla profesional activo:
si NVDA, JAWS o Narrador (o los que el usuario marque) están en ejecución,
tienen preferencia y Tiresias pasa a **espera**:

- sin ganchos de teclado ni ratón (ni WinEvents), sin eventos UIA, sin voz
  propia, sin braille (la línea queda libre), sin superposición táctil, sin
  indicador ``SPI_SETSCREENREADER`` y sin el punto de conexión de NVDA;
- siguen la interfaz (icono y menú), la API de control propia (que responde
  «no activo» para que los programas usen el otro lector), el acceso remoto
  ya conectado y los servicios que no hablan.

Al pasar a espera se avisa a través del lector activo (:mod:`.announce`).
Una vigilancia en un hilo propio sondea cada segundo (:mod:`.detect`, unos
milisegundos por sondeo) y, cuando el otro lector se cierra, Tiresias se
activa por completo y lo anuncia con su voz. Si el otro lector se abre con
Tiresias activo, Tiresias cede de forma limpia. La lógica de estados está en
:mod:`.state` (probada con detectores simulados).

El usuario puede forzar la activación (con advertencia) desde el menú del
icono, con Control+Alt+Mayúsculas+T mientras está en espera o con
``--force-active``.

Para que el usuario nunca se quede sin lector, Tiresias recuerda el lector
profesional activo (:mod:`.relaunch`) y un proceso guardián aparte
(:mod:`.guardian`) lo vuelve a iniciar si Tiresias se cierra, falla o deja
de responder. «Volver a <lector>» cierra Tiresias e inicia ese lector.
"""

from __future__ import annotations

import threading

from .. import queue_handler
from ..i18n import _
from ..log import getLogger
from . import detect
from .announce import Announcer
from .detect import READERS, ReaderInfo
from .state import REASON_FORCED, REASON_OPTION_OFF, Coexistence, Debouncer

log = getLogger("coexist")

DEFAULTS = {
	# Ceder ante otros lectores de pantalla (Tiresias pasa a espera).
	"yieldToOtherReaders": True,
	# Lectores ante los que se cede.
	"readers": [s.id for s in READERS if s.defaultEnabled],
	# Al cerrar Tiresias o si falla, iniciar el lector que estaba activo (guardian.py).
	"relaunchOnExit": True,
	# Iniciarlo también si Tiresias deja de responder durante hangTimeout segundos.
	"relaunchOnHang": True,
	"hangTimeout": 20,
}

#: Intervalo de la vigilancia (s): rápido para soltar a tiempo el punto de conexión de NVDA.
POLL_INTERVAL = 1.0

_machine: Coexistence | None = None
_debouncer = Debouncer()
#: Protege ``_debouncer`` y ``_enabled``: los usan a la vez la vigilancia y el núcleo.
_readersLock = threading.Lock()
_announcer = Announcer()
_monitor: threading.Thread | None = None
_stopEvent = threading.Event()
_initialized = False
_started = False
#: Copia de las opciones para el hilo de vigilancia.
_enabled: frozenset = frozenset(DEFAULTS["readers"])
#: El último sondeo vio NVDA (para soltar su punto de conexión en cuanto aparece).
_nvdaSeen = False


# ------------------------------------------------------------------ consultas
def isStandby() -> bool:
	"""``True`` si Tiresias está en espera porque otro lector tiene preferencia."""
	return _machine is not None and _machine.isStandby


def isForced() -> bool:
	return _machine is not None and _machine.forced


def activeReader() -> ReaderInfo | None:
	"""Lector ante el que se cede (o que está en ejecución al forzar)."""
	return _machine.reader if _machine is not None else None


def runningReaders() -> list[ReaderInfo]:
	with _readersLock:
		return list(_debouncer.stable.values())


def readerChoices() -> list[tuple[str, str]]:
	"""(identificador, nombre) de los lectores conocidos para el panel de opciones."""
	labels = {
		detect.ZOOMTEXT: _("ZoomText o Fusion (solo si usas su voz)"),
		detect.SYSTEM_ACCESS: _("System Access"),
		detect.NARRATOR: _("Narrador de Windows"),
	}
	return [(s.id, labels.get(s.id, s.name)) for s in READERS]


def _conf():
	from ..config import conf

	return conf["coexist"]


def registerDefaults() -> None:
	from ..config import conf

	conf.registerDefaults("coexist", DEFAULTS)


def _readOptions() -> tuple[bool, frozenset]:
	try:
		c = _conf()
		return bool(c["yieldToOtherReaders"]), frozenset(str(r) for r in c["readers"])
	except Exception:
		return True, frozenset(DEFAULTS["readers"])


# ------------------------------------------------------------------ lector recordado (relaunch.py, guardian.py)
def _relaunchOptions() -> dict:
	from .relaunch import DEFAULT_OPTIONS, HANG_TIMEOUT_RANGE

	out = dict(DEFAULT_OPTIONS)
	try:
		c = _conf()
		out["relaunchOnExit"] = bool(c["relaunchOnExit"])
		out["relaunchOnHang"] = bool(c["relaunchOnHang"])
		out["hangTimeout"] = max(HANG_TIMEOUT_RANGE[0], min(HANG_TIMEOUT_RANGE[1], int(c["hangTimeout"])))
	except Exception:
		pass
	out["readers"] = sorted(_enabled)
	return out


def _syncRelaunchOptions() -> None:
	"""Copia las opciones que necesita el guardián al archivo del lector recordado."""
	from . import relaunch

	try:
		relaunch.saveOptions(_relaunchOptions())
	except OSError:
		log.debug("No se pudieron guardar las opciones del lector recordado", exc_info=True)


def _rememberReaders(readers: list[ReaderInfo]) -> None:
	"""Recuerda el lector profesional activo (al arrancar o durante la sesión)."""
	from . import relaunch
	from .state import primaryReader

	primary = primaryReader(readers)
	if primary is None:
		return
	try:
		if relaunch.rememberReader(primary):
			log.info("Lector de pantalla recordado: %s (%s)", primary.label, relaunch.loadMemory()["reader"].get("path") or "sin ruta")
	except OSError:
		log.debug("No se pudo recordar el lector de pantalla", exc_info=True)


def rememberedReader() -> dict | None:
	"""El lector recordado (``{"id", "name", "path", "detail"...}``) o ``None``."""
	from . import relaunch

	return relaunch.loadMemory()["reader"]


def rememberedReaderLabel() -> str:
	from . import relaunch

	return relaunch.readerLabel(rememberedReader())


def forgetReader() -> bool:
	"""Olvida el lector recordado (botón «Olvidar» de Opciones)."""
	from . import relaunch

	try:
		done = relaunch.forgetReader()
	except OSError:
		log.exception("No se pudo olvidar el lector recordado")
		return False
	if done:
		log.info("Lector de pantalla recordado olvidado")
	return done


def _launchAllowed() -> bool:
	try:
		from ..config import policy

		return policy.isAllowed("launchReaders")
	except Exception:
		return True


def canSwitchToRememberedReader() -> bool:
	"""¿Tiene sentido «Volver a <lector>»? (hay lector recordado, Tiresias activo y ese lector cerrado)."""
	if not _launchAllowed():
		return False
	reader = rememberedReader()
	if reader is None or isStandby():
		return False
	from . import relaunch

	if not relaunch.launchCandidates(reader):
		return False
	return not any(r.id == reader["id"] for r in runningReaders())


def switchToRememberedReader() -> bool:
	"""«Volver a <lector>»: cierra Tiresias e inicia el lector recordado (hilo del núcleo)."""
	from .. import core, speech
	from . import guardian, relaunch

	if not _launchAllowed():
		# Modo seguro (escritorio seguro, SYSTEM): no se inician otros programas.
		from ..config import policy

		speech.speakMessage(policy.blockedMessage())
		return False
	reader = rememberedReader()
	if reader is None:
		speech.speakMessage(_("No hay ningún lector de pantalla recordado"))
		return False
	if any(r.id == reader["id"] for r in runningReaders()):
		speech.speakMessage(_("{reader} ya está en ejecución").format(reader=reader.get("name", "")))
		return False
	if not relaunch.launchCandidates(reader):
		speech.speakMessage(_("No se encuentra el programa de {reader}").format(reader=relaunch.readerLabel(reader)))
		return False
	log.info("Volver a %s: se cierra Tiresias", relaunch.readerLabel(reader))
	speech.speakMessage(_("Cerrando Tiresias e iniciando {reader}").format(reader=reader.get("name", "")))
	guardian.setExitKind(relaunch.EXIT_SWITCH)
	# El lector se inicia al final de la salida, cuando Tiresias ya ha soltado todo.
	speech.whenDoneSpeaking(core.requestQuit)
	# Por si se corta la voz antes de terminar el mensaje.
	queue_handler.callLater(4000, core.requestQuit)
	return True


# ------------------------------------------------------------------ acciones (hilo del núcleo)
class _Actions:
	def goStandby(self, reader: ReaderInfo, initial: bool) -> None:
		global _activation
		# Una activación a medias se abandona (sus pasos pendientes no se ejecutan).
		_activation += 1
		log.info("Tiresias pasa a espera: %s en ejecución (PID %d%s)", reader.name, reader.pid, f", {reader.detail}" if reader.detail else "")
		if not initial:
			_suspendAll()
		_updateGui()
		if initial and not _started:
			# El anuncio se hace al terminar de arrancar (afterCoreStarted).
			return
		_announceStandby(reader)

	def goActive(self, reason: str, reader: ReaderInfo | None) -> None:
		global _activation
		log.info("Tiresias se activa (%s)", reason)
		_activation += 1
		# Primero solo la voz, para anunciar la activación cuanto antes.
		_resumeSpeech()
		from .. import speech

		if reason == REASON_FORCED and reader is not None:
			msg = _("Tiresias activado aunque {reader} sigue en ejecución: los dos lectores pueden hablar a la vez.").format(reader=reader.name)
		elif reason == REASON_OPTION_OFF:
			msg = _("Tiresias se activa: ya no cede ante otros lectores de pantalla.")
		else:
			msg = _("No hay ningún otro lector activo: Tiresias se activa.")
		speech.speakMessage(msg)
		_updateGui()
		# Lo demás (ganchos, eventos UIA, braille, indicador...), un paso por
		# ciclo del núcleo: el núcleo sigue atendiendo entre paso y paso.
		queue_handler.callLater(0, _runResumeSteps, _activation, _resumeSteps())


def _announceStandby(reader: ReaderInfo) -> None:
	text = _("Tiresias está en espera: hay otro lector de pantalla activo ({reader}), que tiene preferencia.").format(reader=reader.name)
	rid = reader.id

	def valid() -> bool:
		# Si entretanto Tiresias se ha activado, el lector ha cambiado o Tiresias
		# se está cerrando, no se anuncia (y deja de esperar a ese lector).
		r = activeReader()
		return _initialized and isStandby() and r is not None and r.id == rid

	_announcer.announce(reader, text, valid)


def _reportFocus() -> None:
	from .. import api, events
	from ..a11y import uia_handler
	from ..objects.uia import getFocusObject

	try:
		obj = getFocusObject()
	except Exception:
		log.debug("No se pudo obtener el foco", exc_info=True)
		return
	if obj is None:
		return
	api.setFocusObject(None)
	events.executeEvent("gainFocus", obj)
	try:
		uia_handler._registerLocalHandlers(obj)
	except Exception:
		log.debug("No se pudieron registrar los eventos locales", exc_info=True)


def _step(name: str, func, *args) -> None:
	try:
		func(*args)
	except Exception:
		log.exception("Error en la convivencia (%s)", name)


def _suspendAll() -> None:
	"""Cede de forma limpia: suelta todo lo que pueda molestar al otro lector."""
	from .. import core, speech
	from ..speech import api as speechApi

	_step("voz", speech.cancelSpeech)
	_step("voz en espera", speechApi.setSuspended, True)
	_step("sintetizador en reposo", _synthStandby, True)
	_step("entrada", core.stopInput)
	_step("táctil", _setTouchAllowed, False)
	_step("eventos UIA", _uiaSuspend, True)
	_step("braille", _releaseBraille)
	_step("indicador de lector de pantalla", _releaseScreenReaderFlag)
	_step("punto de conexión de NVDA", _applyController)


def _resumeSpeech() -> None:
	"""Lo imprescindible para anunciar la activación: la voz y el sintetizador."""
	from ..speech import api as speechApi

	_step("voz", speechApi.setSuspended, False)
	# El sintetizador se reanuda ya (antes del anuncio de activación); si
	# falla, se cambia a otro y se anuncia con la voz nueva.
	_step("sintetizador", _synthStandby, False)


def _resumeSteps() -> list[tuple]:
	"""Lo que se reanuda tras el anuncio, en orden: ``(nombre, función, argumentos)``."""
	from .. import core
	from ..input import core as inputCore

	return [
		# Las teclas, lo primero.
		("entrada", core.startInput, ()),
		("táctil", _setTouchAllowed, (True,)),
		("eventos UIA", _uiaSuspend, (False,)),
		("braille", _restoreBraille, ()),
		# Avisa a todas las ventanas (WM_SETTINGCHANGE): puede tardar.
		("indicador de lector de pantalla", _applyScreenReaderFlag, ()),
		("punto de conexión de NVDA", _applyController, ()),
		("cadena de órdenes", inputCore.manager.updateChain, ()),
	]


#: Activación en curso (cada paso comprueba que sigue siendo la misma).
_activation = 0


def _runResumeSteps(activation: int, steps: list[tuple]) -> None:
	"""Un paso de la reanudación por ciclo del núcleo (hilo del núcleo).

	Si entretanto Tiresias ha vuelto a ceder (o se cierra), se abandona: lo
	ya hecho lo deshace :func:`_suspendAll`.
	"""
	if activation != _activation or isStandby():
		return
	if not steps:
		from .. import speech

		# El foco actual, después del mensaje de activación (y con los eventos UIA ya puestos).
		speech.whenDoneSpeaking(lambda: queue_handler.queueFunction(_reportFocus))
		_runPendingOnActive()
		return
	name, func, args = steps[0]
	_step(name, func, *args)
	# callLater (no queueFunction): el siguiente paso va en otro ciclo del núcleo.
	queue_handler.callLater(0, _runResumeSteps, activation, steps[1:])


def _synthStandby(standby: bool) -> None:
	"""En espera, el sintetizador suelta sus recursos (Eloquence cierra su puente)."""
	from .. import synth

	synth.setStandby(standby)


def _setTouchAllowed(allowed: bool) -> None:
	from .. import core
	from ..touch import handler as touchHandler

	h = touchHandler.handler
	h.inputAllowed = bool(allowed) and not (core.args is not None and core.args.no_input)
	h.apply()


def _uiaSuspend(suspend: bool) -> None:
	from ..a11y import uia_handler

	if suspend:
		uia_handler.suspend()
	else:
		uia_handler.resume()


def _releaseBraille() -> None:
	from .. import braille

	if braille.handler.display.name != "noBraille":
		# Sin guardar: la línea elegida se recupera al activarse.
		braille.handler.setDisplay("noBraille", persist=False)


def _restoreBraille() -> None:
	from .. import braille
	from ..config import conf

	name = conf["braille"]["display"]
	if name and name != "noBraille" and braille.handler.display.name == "noBraille":
		if not braille.handler.setDisplay(name, persist=False):
			braille.handler.setDisplay("noBraille", persist=False)


def _releaseScreenReaderFlag() -> None:
	from ..a11y import system as a11ySystem

	a11ySystem.releaseScreenReaderFlag()


def _applyScreenReaderFlag() -> None:
	from ..a11y import system as a11ySystem

	a11ySystem.applyScreenReaderFlag()


def _applyController() -> None:
	from .. import controller

	controller.applyConfiguration()


# ------------------------------------------------------------------ interfaz
def _updateGui() -> None:
	try:
		from .. import gui
		from . import ui

		gui.runOnGui(ui.updateState)
	except Exception:
		log.debug("No se pudo actualizar el icono", exc_info=True)


#: Tareas aplazadas hasta que Tiresias se active (diálogos de arranque...).
_pendingOnActive: list = []


def runWhenActive(func) -> None:
	"""Ejecuta ``func`` ahora o, si Tiresias está en espera, al activarse.

	Para lo que no debe aparecer mientras otro lector tiene preferencia, como
	la pregunta de importar NVDA y la bienvenida (:mod:`tiresias.first_run`).
	Al activarse, ``func`` se llama en el hilo del núcleo.
	"""
	if isStandby():
		_pendingOnActive.append(func)
	else:
		func()


def _runPendingOnActive() -> None:
	pending = list(_pendingOnActive)
	_pendingOnActive.clear()
	for func in pending:
		_step("tarea aplazada", func)


# ------------------------------------------------------------------ órdenes del usuario (hilo del núcleo)
def forceActivate() -> bool:
	"""Activa Tiresias aunque haya otro lector (tras la advertencia)."""
	if _machine is None:
		return False
	return _machine.force()


def yieldNow() -> bool:
	"""Deja de forzar y cede ante el lector activo; ``False`` si no hay ninguno."""
	if _machine is None:
		return False
	return _machine.yieldNow()


def statusText() -> str:
	readers = runningReaders()
	names = ", ".join(r.label for r in readers)
	yieldOn, _enabledIds = _readOptions()
	if isStandby():
		r = activeReader()
		return _("Tiresias está en espera: {reader} tiene preferencia.").format(reader=r.label if r else names)
	if not readers:
		text = _("No hay ningún otro lector de pantalla activo.")
	elif isForced():
		text = _("Tiresias está activo por decisión tuya aunque hay otro lector de pantalla en ejecución: {names}.").format(names=names)
	else:
		text = _("Hay otro lector de pantalla en ejecución: {names}.").format(names=names)
	if not yieldOn:
		text += " " + _("Tiresias no cede ante otros lectores (opción desactivada).")
	label = rememberedReaderLabel()
	if label:
		text += " " + _("Lector recordado: {reader}.").format(reader=label)
	return text


# ------------------------------------------------------------------ configuración
def applyConfiguration() -> None:
	"""Relee las opciones (hilo del núcleo)."""
	global _enabled
	if _machine is None:
		return
	yieldOn, enabled = _readOptions()
	changedList = enabled != _enabled
	if changedList:
		# Lectores que ya no cuentan (o que ahora sí): se recalcula sin esperar.
		readers = list(detect.detectReaders(enabled))
		with _readersLock:
			# Junto con el reinicio del filtro: un sondeo en curso con la lista
			# anterior no puede volver a meter un lector que ya no cuenta.
			_enabled = enabled
			_debouncer.reset(readers)
		_machine.onReaders(readers)
	_machine.setYieldEnabled(yieldOn)
	_syncRelaunchOptions()
	_updateGui()


def _onConfigChanged(*args, **kwargs) -> None:
	queue_handler.queueFunction(applyConfiguration)


# ------------------------------------------------------------------ vigilancia
def _onStableReaders(readers: list[ReaderInfo] | None = None) -> None:
	if _machine is None:
		return
	# El conjunto actual, no el del sondeo que lo encoló: entretanto
	# applyConfiguration puede haber cambiado la lista de lectores.
	readers = runningReaders()
	names = ", ".join(r.label for r in readers) or "ninguno"
	log.info("Lectores de pantalla en ejecución: %s", names)
	_rememberReaders(readers)
	_machine.onReaders(readers)
	_updateGui()


def _poll(detector: detect.Detector) -> None:
	"""Un sondeo de la vigilancia (hilo de vigilancia)."""
	global _nvdaSeen
	if detect.isSecureDesktopActive():
		# UAC o Ctrl+Alt+Supr: el escritorio de entrada no es este; nada cambia.
		return
	enabled = _enabled
	readers = detector.detect(set(enabled) | {detect.NVDA})
	nvda = any(r.id == detect.NVDA for r in readers)
	if nvda and not _nvdaSeen:
		# NVDA arranca: su punto de conexión tiene que estar libre ya.
		try:
			from .. import controller

			controller.releaseNvdaEndpoint("NVDA arranca")
		except Exception:
			log.exception("No se pudo soltar el punto de conexión de NVDA")
	elif not nvda and _nvdaSeen:
		# NVDA se ha cerrado: se recupera el punto de conexión (si Tiresias está activo).
		queue_handler.queueFunction(_applyController)
	_nvdaSeen = nvda
	with _readersLock:
		# La lista vigente (applyConfiguration puede haberla cambiado durante el sondeo).
		filtered = [r for r in readers if r.id in _enabled]
		changed = _debouncer.update(filtered)
	if changed:
		queue_handler.queueFunction(_onStableReaders)


def _monitorLoop() -> None:
	detector = detect.Detector()
	count = 0
	while not _stopEvent.wait(POLL_INTERVAL):
		try:
			_poll(detector)
		except Exception:
			log.exception("Error vigilando otros lectores de pantalla")
		count += 1
		if count % 15 == 0:
			# Si alguien ha cerrado el guardián, se vuelve a iniciar.
			try:
				from . import guardian

				guardian.ensureRunning()
			except Exception:
				log.debug("No se pudo comprobar el guardián", exc_info=True)


# ------------------------------------------------------------------ ciclo de vida
def initialize(forceActive: bool = False) -> None:
	"""Decide el estado inicial (hilo del núcleo, al principio del arranque)."""
	global _machine, _initialized, _enabled, _nvdaSeen
	if _initialized:
		return
	registerDefaults()
	yieldOn, _enabled = _readOptions()
	try:
		readers = detect.detectReaders(set(_enabled) | {detect.NVDA})
	except Exception:
		log.exception("No se pudieron detectar otros lectores de pantalla")
		readers = []
	_nvdaSeen = any(r.id == detect.NVDA for r in readers)
	readers = [r for r in readers if r.id in _enabled]
	_debouncer.reset(readers)
	# El lector profesional activo al arrancar se recuerda (y las opciones, para el guardián).
	_rememberReaders(readers)
	_syncRelaunchOptions()
	_machine = Coexistence(_Actions())
	state = _machine.start(readers, yieldOn, forced=forceActive)
	if readers:
		log.info("Lectores de pantalla en ejecución al iniciar: %s", ", ".join(f"{r.label} (PID {r.pid})" for r in readers))
	if _machine.isStandby:
		from ..speech import api as speechApi

		speechApi.setSuspended(True)
		# El sintetizador se carga después en reposo (sin el puente de Eloquence).
		_step("sintetizador en reposo", _synthStandby, True)
	elif _machine.forced:
		log.info("Activación forzada con otro lector en ejecución")
	log.info("Estado de convivencia al iniciar: %s", state)
	from ..plugins import handler as pluginHandler
	from .plugin import CoexistGlobalPlugin

	pluginHandler.registerBuiltin(CoexistGlobalPlugin)
	from ..config import post_configProfileSwitch, post_configReset, post_configSave

	for action in (post_configSave, post_configProfileSwitch, post_configReset):
		try:
			action.register(_onConfigChanged)
		except Exception:
			pass
	_initialized = True


def afterCoreStarted() -> None:
	"""Al terminar de arrancar el núcleo: vigilancia y anuncio inicial."""
	global _monitor, _started
	if not _initialized or _started:
		return
	_started = True
	if isStandby():
		# Los eventos UIA se registraron al iniciar: se quitan mientras se espera.
		_step("eventos UIA", _uiaSuspend, True)
		r = activeReader()
		if r is not None:
			_announceStandby(r)
	_updateGui()
	_stopEvent.clear()
	_monitor = threading.Thread(target=_monitorLoop, name="Vigilancia de lectores", daemon=True)
	_monitor.start()


def terminate() -> None:
	global _monitor, _initialized, _started, _activation
	# Una activación a medias no sigue durante el cierre; los anuncios pendientes tampoco.
	_activation += 1
	_initialized = False
	_stopEvent.set()
	if _monitor is not None:
		_monitor.join(3)
		_monitor = None
	_announcer.stop()
	try:
		from . import ui

		ui.terminate()
	except Exception:
		pass
	from ..config import post_configProfileSwitch, post_configReset, post_configSave

	for action in (post_configSave, post_configProfileSwitch, post_configReset):
		try:
			action.unregister(_onConfigChanged)
		except Exception:
			pass
	_initialized = False
	_started = False
