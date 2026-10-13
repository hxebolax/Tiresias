"""Complemento global incorporado de matemáticas.

- Orden para explorar la fórmula del cursor (modo exploración, objeto
  navegador, foco o ecuación de Word).
- Orden para leer y explorar la fórmula del portapapeles (MathML, LaTeX,
  OMML o texto lineal).
- Mientras se explora una fórmula, las teclas se pasan al
  :class:`~.interaction.MathInteractor` (este complemento es el primer
  eslabón de la cadena de órdenes).
- Clase superpuesta :class:`MathObject` para los objetos con rol
  «matemáticas» (modo foco y navegación de objetos).
"""

from __future__ import annotations

from .. import api, speech
from ..baseobject import script
from ..i18n import _
from ..log import getLogger
from ..objects.base import AccObject
from ..objects.roles import Role
from ..plugins import GlobalPlugin
from . import interaction

log = getLogger("mathpres.plugin")

CAT = _("Matemáticas")

#: Modificadores con los que las teclas siguen su camino durante la exploración.
_PASS_MODIFIERS = {"tiresias", "alt", "windows"}


class MathObject(AccObject):
	"""Superposición para objetos con rol matemáticas (UIA)."""

	def _get_mathMl(self) -> str | None:
		from . import providers

		try:
			return providers.mathMlForObject(self)
		except Exception:
			log.debug("Sin MathML", exc_info=True)
			return None

	_cache_mathMl = True

	def _get_mathSpeech(self) -> str:
		m = self.mathMl
		if not m:
			return ""
		try:
			from . import getSpeechText

			return getSpeechText(m)
		except Exception:
			log.debug("Error leyendo la fórmula", exc_info=True)
			return ""

	def _get_name(self) -> str:
		text = self.mathSpeech
		if text:
			return text
		return super()._get_name()  # type: ignore[misc]

	def _get_roleText(self) -> str | None:
		return _("matemáticas")

	def _get_value(self) -> str:
		return ""


class MathGlobalPlugin(GlobalPlugin):
	scriptCategory = CAT

	def getScript(self, gesture):
		inter = interaction.getInteractor()
		if inter is not None:
			func = inter.getScript(gesture)
			if func is not None:
				return func
			mods = set(getattr(gesture, "modifiers", ()) or ())
			ids = getattr(gesture, "identifiers", [""])
			if ids and str(ids[-1]).startswith("kb") and not (mods & _PASS_MODIFIERS) and "control" not in mods:
				# Tecla que escribiría texto o movería el cursor del documento.
				return inter.script_ignore
		return super().getScript(gesture)

	def chooseObjectClass(self, obj, clsList: list[type]) -> None:
		try:
			if obj.role == Role.MATH and hasattr(obj, "element"):
				clsList.insert(0, MathObject)
		except Exception:
			pass

	def event_gainFocus(self, obj, nextHandler) -> None:
		if interaction.getInteractor() is not None:
			interaction.stop(silent=True)
		nextHandler()

	def terminate(self) -> None:
		interaction.stop(silent=True)

	# ------------------------------------------------------------ órdenes
	@script(description=_("Explora la fórmula matemática del cursor (o la del objeto navegador)"), category=CAT, gesture="kb:tiresias+alt+e")
	def script_interactWithMath(self, gesture) -> None:
		# Aplicaciones que buscan la fórmula por su cuenta (PowerPoint, foros 3.6).
		focus = api.getFocusObject()
		hook = getattr(getattr(focus, "appModule", None), "interactWithMath", None) if focus is not None else None
		if callable(hook):
			try:
				if hook(focus):
					return
			except Exception:
				log.debug("Error buscando la fórmula en la aplicación", exc_info=True)
		mathMl, source = findMathAtCursor()
		if not mathMl:
			speech.speakMessage(_("No hay ninguna fórmula matemática aquí"))
			return
		interaction.start(mathMl, source)

	@script(description=_("Lee y explora la fórmula del portapapeles (MathML, LaTeX o texto)"), category=CAT, gesture="kb:tiresias+shift+alt+e")
	def script_mathFromClipboard(self, gesture) -> None:
		from . import providers

		mathMl, origin = providers.mathMlFromClipboard()
		if not mathMl:
			speech.speakMessage(_("El portapapeles no contiene ninguna fórmula"))
			return
		interaction.start(mathMl, None)

	@script(description=_("Cambia la verbosidad de la lectura de matemáticas"), category=CAT)
	def script_cycleMathVerbosity(self, gesture) -> None:
		interaction.cycleVerbosity()

	@script(description=_("Cambia el estilo de lectura de matemáticas (natural o estructural)"), category=CAT)
	def script_cycleMathStyle(self, gesture) -> None:
		interaction.cycleStyle()


def findMathAtCursor() -> tuple[str | None, object]:
	"""MathML de la fórmula en el cursor de exploración, el navegador o el foco."""
	from . import browse_support, providers

	focus = api.getFocusObject()
	ti = getattr(focus, "treeInterceptor", None) if focus is not None else None
	if ti is not None and not getattr(ti, "passThrough", True) and getattr(ti, "buffer", None):
		m = browse_support.mathMlAtCaret(ti)
		if m:
			return m, ti
	nav = api.getNavigatorObject()
	for obj in (nav, focus):
		if obj is None:
			continue
		try:
			m = providers.mathMlForFocus(obj) if obj is focus else providers.mathMlForObject(obj)
		except Exception:
			log.debug("Error buscando la fórmula", exc_info=True)
			m = None
		if m:
			return m, obj
	return None, None
