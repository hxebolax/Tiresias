"""Exploración interactiva de una fórmula.

Mientras se explora, el complemento incorporado de matemáticas
(:mod:`.plugin`), que es el primer eslabón de la cadena de órdenes, pasa las
teclas a :class:`MathInteractor`. Las teclas con Tiresias, Control (salvo
las de la exploración), Alt o Windows siguen llegando al resto de la cadena
(órdenes globales, aplicación...). Las teclas que escribirían texto se
ignoran para no tocar el documento. Escape (o un cambio de foco) termina
la exploración.
"""

from __future__ import annotations

from .. import api, speech
from ..audio import tones
from ..baseobject import ScriptableObject, script
from ..config import conf
from ..i18n import _
from ..log import getLogger
from . import braille_cmu, latex, mathml, speech_es
from .navigation import MathNavigator, structureName

log = getLogger("mathpres.interaction")

CAT = _("Matemáticas")

VERBOSITY_LABELS = {"breve": _("verbosidad breve"), "normal": _("verbosidad normal"), "detallado": _("verbosidad detallada")}
STYLE_LABELS = {"natural": _("estilo natural"), "estructural": _("estilo estructural")}

_interactor: "MathInteractor | None" = None


def getInteractor() -> "MathInteractor | None":
	return _interactor


def _options() -> speech_es.SpeechOptions:
	from . import options

	return options()


def speakSequence(seq: list) -> None:
	out = speech_es.toSpeechSequence(seq, bool(conf["math"]["pauses"]))
	if out:
		speech.speak(out)


class MathInteractor(ScriptableObject):
	"""Orden activa mientras se explora una fórmula."""

	scriptCategory = CAT

	def __init__(self, mathMl: str, sourceObj=None) -> None:
		super().__init__()
		self.mathMl = mathMl
		self.root = mathml.parse(mathMl)
		self.nav = MathNavigator(self.root)
		self.sourceObj = sourceObj
		self.braille = braille_cmu.translate(self.root)

	# ------------------------------------------------------------ salida
	def speakCurrent(self, withLabel: bool = True) -> None:
		speakSequence(self.nav.speechFor(options=_options(), withLabel=withLabel))
		self.updateBraille()

	def updateBraille(self) -> None:
		if not conf["math"]["brailleMath"]:
			text = speech_es.nodeText(self.nav.top, _options())
			try:
				from .. import braille

				braille.handler.message(text)
			except Exception:
				pass
			return
		try:
			from .. import braille

			text = braille_cmu.toUnicode(self.braille.cells)
			rng = self.braille.rangeOf(self.nav.current) or (0, 0)
			handle = getattr(braille.handler, "handleCustom", None)
			if handle is not None:
				handle(text, rng[0], self, (rng[0], rng[1]) if rng[1] > rng[0] else None)
		except Exception:
			log.debug("Braille de matemáticas no disponible", exc_info=True)

	def routeTo(self, cellIndex: int) -> None:
		"""Pulsador de la línea braille: lleva el cursor al nodo de esa celda."""
		node = self.braille.nodeAt(cellIndex, self.root)
		while node is not None and node is not self.nav.top and node.tag in ("mrow",) and not node.isFenced and node.parent is not None and node.parent.tag in ("msqrt", "mtd", "menclose"):
			node = node.parent
		if node is not None and node.tag != "math":
			self.nav.moveTo(node)
			self.speakCurrent()

	def _boundary(self) -> None:
		tones.playSound("boundary")

	def _move(self, ok: bool, withLabel: bool = True) -> None:
		if ok:
			speech.cancelSpeech()
			self.speakCurrent(withLabel)
		else:
			self._boundary()

	# ------------------------------------------------------------ movimiento
	@script(gesture="kb:rightArrow", description=_("Matemáticas: elemento siguiente"))
	def script_next(self, gesture) -> None:
		self._move(self.nav.moveNext())

	@script(gesture="kb:leftArrow", description=_("Matemáticas: elemento anterior"))
	def script_previous(self, gesture) -> None:
		self._move(self.nav.movePrevious())

	@script(gesture="kb:downArrow", description=_("Matemáticas: entra en el elemento (numerador, base, radicando...)"))
	def script_zoomIn(self, gesture) -> None:
		self._move(self.nav.moveDown())

	@script(gesture="kb:upArrow", description=_("Matemáticas: sale al elemento que contiene al actual"))
	def script_zoomOut(self, gesture) -> None:
		self._move(self.nav.moveUp(), withLabel=False)

	@script(gesture="kb:home", description=_("Matemáticas: primer elemento del nivel actual"))
	def script_first(self, gesture) -> None:
		self._move(self.nav.moveFirst())

	@script(gesture="kb:end", description=_("Matemáticas: último elemento del nivel actual"))
	def script_last(self, gesture) -> None:
		self._move(self.nav.moveLast())

	@script(gesture="kb:control+home", description=_("Matemáticas: vuelve a la fórmula completa"))
	def script_top(self, gesture) -> None:
		if not self.nav.moveTop():
			self.speakCurrent(False)
			return
		self.speakCurrent(False)

	@script(gesture="kb:backspace", description=_("Matemáticas: vuelve a la posición anterior"))
	def script_back(self, gesture) -> None:
		self._move(self.nav.moveBack())

	@script(gestures=("kb:control+alt+rightArrow", "kb:control+rightArrow"), description=_("Matemáticas: celda siguiente de la matriz o tabla"))
	def script_cellNext(self, gesture) -> None:
		self._cell(0, 1)

	@script(gestures=("kb:control+alt+leftArrow", "kb:control+leftArrow"), description=_("Matemáticas: celda anterior de la matriz o tabla"))
	def script_cellPrevious(self, gesture) -> None:
		self._cell(0, -1)

	@script(gestures=("kb:control+alt+downArrow", "kb:control+downArrow"), description=_("Matemáticas: celda de abajo de la matriz o tabla"))
	def script_cellDown(self, gesture) -> None:
		self._cell(1, 0)

	@script(gestures=("kb:control+alt+upArrow", "kb:control+upArrow"), description=_("Matemáticas: celda de arriba de la matriz o tabla"))
	def script_cellUp(self, gesture) -> None:
		self._cell(-1, 0)

	def _cell(self, dRow: int, dCol: int) -> None:
		if self.nav.currentCell() is None:
			speech.speakMessage(_("no está en una matriz ni en una tabla"))
			return
		if not self.nav.moveCell(dRow, dCol):
			self._boundary()
			return
		pos = self.nav.cellPosition()
		speech.cancelSpeech()
		seq: list = []
		if pos:
			seq.append(_("fila {row} columna {col}").format(row=pos[0], col=pos[1]))
		seq.extend(self.nav.speechFor(options=_options()))
		speakSequence(seq)
		self.updateBraille()

	# ------------------------------------------------------------ lectura
	@script(gesture="kb:space", description=_("Matemáticas: lee el elemento actual"))
	def script_readCurrent(self, gesture) -> None:
		self.speakCurrent(False)

	@script(gesture="kb:shift+space", description=_("Matemáticas: describe la estructura del elemento actual"))
	def script_describe(self, gesture) -> None:
		speech.speakMessage(self.nav.describe(options=_options()))

	@script(gestures=("kb:enter", "kb:numpadEnter"), description=_("Matemáticas: dice dónde está el cursor dentro de la fórmula"))
	def script_whereAmI(self, gesture) -> None:
		speech.speakMessage(self.nav.whereAmI())

	@script(gesture="kb:shift+rightArrow", description=_("Matemáticas: lee el elemento siguiente sin moverse"))
	def script_readNext(self, gesture) -> None:
		node = self.nav.peekNext()
		if node is None:
			self._boundary()
			return
		speakSequence(self.nav.speechFor(node, _options(), withLabel=True))

	@script(gesture="kb:shift+leftArrow", description=_("Matemáticas: lee el elemento anterior sin moverse"))
	def script_readPrevious(self, gesture) -> None:
		node = self.nav.peekPrevious()
		if node is None:
			self._boundary()
			return
		speakSequence(self.nav.speechFor(node, _options(), withLabel=True))

	@script(gesture="kb:v", description=_("Matemáticas: cambia la verbosidad (breve, normal, detallada)"))
	def script_cycleVerbosity(self, gesture) -> None:
		cycleVerbosity()
		self.speakCurrent(False)

	@script(gesture="kb:s", description=_("Matemáticas: cambia el estilo de lectura (natural o estructural)"))
	def script_cycleStyle(self, gesture) -> None:
		cycleStyle()
		self.speakCurrent(False)

	# ------------------------------------------------------------ copiar
	def _textFor(self, fmt: str) -> str:
		node = self.nav.current
		if fmt == "latex":
			return latex.toLatex(node)
		if fmt == "text":
			return speech_es.nodeText(node, _options())
		if node is self.nav.top:
			return self.root.toMathML()
		wrapper = mathml.MathNode("math", children=[node.copy()])
		return wrapper.toMathML()

	def _copy(self, fmt: str) -> None:
		label = {"mathml": "MathML", "latex": "LaTeX", "text": _("texto")}[fmt]
		text = self._textFor(fmt)
		if api.copyToClip(text):
			speech.speakMessage(_("copiado como {fmt}").format(fmt=label))
		else:
			speech.speakMessage(_("No se pudo copiar"))

	@script(gesture="kb:control+c", description=_("Matemáticas: copia el elemento actual en el formato elegido en las opciones"))
	def script_copy(self, gesture) -> None:
		fmt = conf["math"]["copyFormat"]
		self._copy(fmt if fmt in ("mathml", "latex", "text") else "mathml")

	@script(gesture="kb:m", description=_("Matemáticas: copia el elemento actual como MathML"))
	def script_copyMathMl(self, gesture) -> None:
		self._copy("mathml")

	@script(gesture="kb:l", description=_("Matemáticas: copia el elemento actual como LaTeX"))
	def script_copyLatex(self, gesture) -> None:
		self._copy("latex")

	@script(gesture="kb:t", description=_("Matemáticas: copia el texto hablado del elemento actual"))
	def script_copyText(self, gesture) -> None:
		self._copy("text")

	@script(gesture="kb:f1", description=_("Matemáticas: ayuda de las teclas de exploración"))
	def script_help(self, gesture) -> None:
		speech.speakMessage(
			_(
				"Flechas izquierda y derecha: elemento anterior y siguiente. Flecha abajo: entrar. Flecha arriba: salir. "
				"Inicio y Fin: primero y último. Control más flechas: celdas de matrices. Espacio: leer. "
				"Mayúsculas más espacio: describir. Intro: dónde estoy. V: verbosidad. S: estilo. "
				"Control más C, M, L o T: copiar. Escape: terminar."
			)
		)

	@script(gesture="kb:escape", description=_("Matemáticas: termina la exploración de la fórmula"))
	def script_exit(self, gesture) -> None:
		stop()

	def script_ignore(self, gesture) -> None:
		"""Tecla de texto durante la exploración: no hace nada."""
		tones.playSound("boundary")


def cycleVerbosity() -> str:
	order = ["breve", "normal", "detallado"]
	cur = conf["math"]["verbosity"]
	nxt = order[(order.index(cur) + 1) % 3] if cur in order else "normal"
	conf["math"]["verbosity"] = nxt
	speech.speakMessage(VERBOSITY_LABELS[nxt])
	return nxt


def cycleStyle() -> str:
	cur = conf["math"]["style"]
	nxt = "estructural" if cur == "natural" else "natural"
	conf["math"]["style"] = nxt
	speech.speakMessage(STYLE_LABELS[nxt])
	return nxt


def start(mathMl: str, sourceObj=None) -> bool:
	"""Empieza a explorar ``mathMl``. Devuelve ``False`` si no se pudo."""
	global _interactor
	try:
		inter = MathInteractor(mathMl, sourceObj)
	except Exception:
		log.exception("No se pudo interpretar el MathML")
		speech.speakMessage(_("No se pudo interpretar la fórmula"))
		return False
	if _interactor is not None:
		_interactor = None
	_interactor = inter
	speech.cancelSpeech()
	seq: list = [_("explorando fórmula")]
	if conf["math"]["speakOnEnter"]:
		seq.append(speech_es.MEDIUM)
		seq.extend(inter.nav.speechFor(options=_options()))
	else:
		seq.append(structureName(inter.nav.top))
	speakSequence(seq)
	inter.updateBraille()
	return True


def stop(silent: bool = False) -> None:
	global _interactor
	if _interactor is None:
		return
	_interactor = None
	if not silent:
		speech.cancelSpeech()
		speech.speakMessage(_("fuera de la fórmula"))
	_restoreBraille()


def _restoreBraille() -> None:
	try:
		from .. import braille

		focus = api.getFocusObject()
		if focus is None:
			return
		ti = getattr(focus, "treeInterceptor", None)
		if ti is not None and not ti.passThrough and getattr(ti, "buffer", None):
			s, e = ti.buffer.lineBounds(ti.caret)
			ti._updateBraille(s, e)
		else:
			braille.handler.handleObject(focus)
	except Exception:
		log.debug("No se pudo restaurar el braille", exc_info=True)
