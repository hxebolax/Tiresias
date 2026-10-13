"""Diálogos del arranque: importar la configuración de NVDA y bienvenida.

Orden, siempre de uno en uno (nunca dos a la vez ni uno tapando al otro):

1. **Primer arranque** (no había ``config.json``): si se encuentra la
   configuración de NVDA instalado, se pregunta si se quieren usar sus
   ajustes. Con «Sí» se importan, se aplican en caliente (la voz incluida), se
   anuncia y se muestra el resumen; con «No» no se toca nada. La respuesta se
   recuerda en ``general.firstRunStep`` y la pregunta no vuelve a salir.
2. Después sale la **bienvenida**, que en el primer arranque es la pantalla de
   configuración inicial: sale aunque su casilla «Mostrar este diálogo al
   iniciar» esté desmarcada (la importación pone el valor que tenía NVDA) y sus
   controles muestran ya lo importado (distribución, teclas Tiresias...), para
   que el usuario lo confirme o lo cambie.
3. **Arranques siguientes**: la bienvenida sale solo si su casilla está marcada.

Con otro lector de pantalla activo (Tiresias en espera) todo se aplaza hasta
que Tiresias se active, en el mismo orden (:func:`tiresias.coexist.runWhenActive`).
Si Tiresias pasa a espera entre un paso y el siguiente, lo que falta también
se aplaza.

La decisión (:func:`planSteps`) y la secuencia (:class:`StartupSequence`) no
dependen de wx: se prueban con diálogos simulados (``tests/test_primer_arranque.py``).
"""

from __future__ import annotations

from typing import Callable

from .log import getLogger

log = getLogger("firstRun")

#: Valores de ``general.firstRunStep``.
STEP_NVDA = "nvda"  # falta la pregunta de importar la configuración de NVDA
STEP_WELCOME = "welcome"  # falta la bienvenida del primer arranque
STEP_DONE = ""

#: Pasos de la secuencia.
ASK_IMPORT = "askImport"
WELCOME = "welcome"


# ====================================================================== decisión
def planSteps(step: str, nvdaFolder: str | None, showWelcomeAtStartup: bool, *, readOnly: bool = False, suppressed: bool = False) -> list[str]:
	"""Pasos de este arranque, en orden.

	- ``step``: valor guardado de ``general.firstRunStep``.
	- ``nvdaFolder``: carpeta de la configuración de NVDA encontrada (o ``None``).
	- ``showWelcomeAtStartup``: casilla «Mostrar el diálogo de bienvenida al iniciar».
	- ``readOnly``: configuración de solo lectura (modo seguro): no se importa.
	- ``suppressed``: ``--minimal`` o ``--install``: ningún diálogo.
	"""
	if suppressed:
		return []
	if step == STEP_NVDA:
		steps = [ASK_IMPORT] if nvdaFolder and not readOnly else []
		return steps + [WELCOME]
	if step == STEP_WELCOME:
		return [WELCOME]
	return [WELCOME] if showWelcomeAtStartup else []


class StartupSequence:
	"""Ejecuta los pasos de uno en uno (hilo de la interfaz).

	Las acciones se reciben como funciones para poder probarlas sin wx:

	- ``ask(folder, onAnswer, then)``: hace la pregunta de NVDA; llama a
	  ``onAnswer(importar)`` en cuanto se responde y a ``then()`` cuando ha
	  terminado todo (importación aplicada y resumen cerrado).
	- ``welcome(imported)``: muestra la bienvenida.
	- ``setStep(valor, save)``: recuerda el paso del primer arranque.
	- ``isStandby()`` y ``defer(func)``: espera ante otro lector.
	"""

	def __init__(
		self,
		steps: list[str],
		folder: str | None,
		*,
		firstRun: bool,
		ask: Callable[[str, Callable[[bool], None], Callable[[], None]], None],
		welcome: Callable[[bool], None],
		setStep: Callable[[str, bool], None],
		isStandby: Callable[[], bool] = lambda: False,
		defer: Callable[[Callable[[], None]], None] | None = None,
	) -> None:
		self.steps = list(steps)
		self.folder = folder
		self.firstRun = firstRun
		self._ask = ask
		self._welcome = welcome
		self._setStep = setStep
		self._isStandby = isStandby
		self._defer = defer
		#: Se importó la configuración de NVDA en esta secuencia.
		self.imported = False
		#: Pasos ya ejecutados (para el registro y las pruebas).
		self.done: list[str] = []

	def start(self) -> None:
		self._next()

	def _next(self) -> None:
		if not self.steps:
			return
		if self._defer is not None and self._isStandby():
			# Otro lector tiene preferencia: se sigue cuando Tiresias se active.
			log.info("Diálogos de arranque aplazados hasta que Tiresias se active: %s", ", ".join(self.steps))
			self._defer(self._next)
			return
		step = self.steps.pop(0)
		self.done.append(step)
		log.info("Diálogo de arranque: %s", step)
		if step == ASK_IMPORT:
			self._ask(self.folder or "", self._onAnswer, self._next)
		elif step == WELCOME:
			if self.firstRun:
				# Sin NVDA (o tras responder): la pregunta ya no saldrá.
				self._setStep(STEP_WELCOME, True)
			self._welcome(self.imported)
			self._next()

	def _onAnswer(self, importIt: bool) -> None:
		log.info("Importar la configuración de NVDA en el primer arranque: %s", "sí" if importIt else "no")
		self.imported = bool(importIt)
		# Al importar no se guarda aquí: la importación guarda la configuración
		# (con este paso incluido) antes de hacer la copia de seguridad.
		self._setStep(STEP_WELCOME, not importIt)


# ====================================================================== estado guardado
def currentStep() -> str:
	from .config import conf

	try:
		value = conf["general"]["firstRunStep"]
	except KeyError:
		return STEP_DONE
	return value if value in (STEP_NVDA, STEP_WELCOME) else STEP_DONE


def setStep(value: str, save: bool = True) -> None:
	"""Recuerda el paso del primer arranque en la configuración normal (no en un perfil)."""
	from . import queue_handler
	from .config import conf

	if conf.readOnly:
		return
	with conf._lock:
		general = conf.base.setdefault("general", {})
		if general.get("firstRunStep", STEP_DONE) == value:
			return
		general["firstRunStep"] = value
		conf.baseDirty = True
	if save:
		queue_handler.queueFunction(_save)


def _save() -> None:
	from .config import conf

	try:
		conf.save()
	except Exception:
		log.exception("No se pudo guardar la configuración del primer arranque")


def markFirstRun() -> None:
	"""No había configuración: queda pendiente la pregunta de NVDA y la bienvenida."""
	setStep(STEP_NVDA, save=False)


def welcomeAccepted() -> None:
	"""La bienvenida se ha aceptado: el primer arranque ha terminado (la guarda quien llama)."""
	if currentStep() != STEP_DONE:
		setStep(STEP_DONE, save=False)


# ====================================================================== arranque real
def start(args=None) -> StartupSequence | None:
	"""Decide y lanza los diálogos de este arranque (hilo del núcleo)."""
	from . import coexist, gui
	from .config import conf

	suppressed = bool(args and (getattr(args, "minimal", False) or getattr(args, "install", False)))
	step = currentStep()
	folder = None
	if step == STEP_NVDA and not suppressed and not conf.readOnly:
		try:
			from . import nvda_import

			folder = nvda_import.findNvdaConfig()
		except Exception:
			log.exception("No se pudo buscar la configuración de NVDA")
	steps = planSteps(step, folder, bool(conf["general"]["showWelcomeDialogAtStartup"]), readOnly=conf.readOnly, suppressed=suppressed)
	if not steps:
		return None
	log.info("Diálogos de arranque: %s (primer arranque: %s)", ", ".join(steps), step or "no")
	seq = StartupSequence(
		steps,
		folder,
		firstRun=step != STEP_DONE,
		ask=_askImport,
		welcome=_showWelcome,
		setStep=setStep,
		isStandby=coexist.isStandby,
		defer=lambda func: coexist.runWhenActive(lambda: gui.runOnGui(func)),
	)
	gui.runOnGui(seq.start)
	return seq


def _askImport(folder: str, onAnswer: Callable[[bool], None], then: Callable[[], None]) -> None:
	from .gui import nvda_import_dialog

	nvda_import_dialog.askOnFirstRun(folder, onAnswer=onAnswer, then=then)


def _showWelcome(imported: bool) -> None:
	from .gui import config_dialogs

	config_dialogs.showWelcome(imported=imported)
