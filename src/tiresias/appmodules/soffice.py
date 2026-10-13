"""LibreOffice y OpenOffice (``soffice.bin``).

- Los documentos de Writer, Calc e Impress no entran en modo exploración por
  sí solos: se editan en modo foco.
- Confirma los atajos de formato de Writer (NVDA #6915): negrita, cursiva,
  subrayado y alineación, leyendo el estado de los botones de la barra de
  formato después de pulsarlos.
- Tiresias+Fin lee la barra de estado (página, palabras, estilo, idioma...).
"""

from __future__ import annotations

from .. import api, queue_handler, speech
from ..baseobject import normalizeGestureId
from ..i18n import _
from ..objects.roles import Role, State
from . import AppModule as BaseAppModule

CAT = _("LibreOffice")

#: Atajo -> (nombres posibles del botón en la barra de formato, texto del estado).
FORMAT_BUTTONS = {
	"kb:control+b": (("negrita", "bold"), _("negrita")),
	"kb:control+i": (("cursiva", "italic"), _("cursiva")),
	"kb:control+u": (("subrayado", "underline"), _("subrayado")),
	"kb:control+e": (("centrar", "centrado", "center", "centered"), _("centrado")),
	"kb:control+l": (("alinear a la izquierda", "align left", "izquierda"), _("alineado a la izquierda")),
	"kb:control+r": (("alinear a la derecha", "align right", "derecha"), _("alineado a la derecha")),
	"kb:control+j": (("justificado", "justified", "justify"), _("justificado")),
	# Rev. 10.11: LibreOffice en español usa otros aceleradores (N, K, S). Como
	# solo se anuncia un cambio real del botón, en inglés (Control+N nuevo,
	# Control+S guardar) no se dice nada falso.
	"kb:control+n": (("negrita", "bold"), _("negrita")),
	"kb:control+k": (("cursiva", "italic"), _("cursiva")),
	"kb:control+s": (("subrayado", "underline"), _("subrayado")),
}


ALIGNMENT_LABELS = {v[1] for k, v in FORMAT_BUTTONS.items() if k in ("kb:control+e", "kb:control+l", "kb:control+r", "kb:control+j")}


def findToggle(root, names: tuple[str, ...]):
	"""Botón conmutable de la barra de herramientas cuyo nombre empieza por uno de ``names``."""
	from ..a11y import uia_client as uc
	from ..objects.uia import UIAObject

	if root is None or not hasattr(root, "element"):
		return None
	try:
		cond = uc.createPropertyCondition(uc.P_CONTROLTYPE, uc.CT_BUTTON)
		arr = root.element.FindAllBuildCache(uc.TreeScope_Descendants, cond, uc.baseCacheRequest)
	except Exception:
		return None
	for i in range(arr.Length if arr else 0):
		el = arr.GetElement(i)
		try:
			name = (el.CachedName or "").lower()
		except Exception:
			continue
		if any(name.startswith(n) for n in names):
			return UIAObject.fromElement(el)
	return None


#: Atajos cuyo significado cambia con el idioma de LibreOffice.
LANGUAGE_DEPENDENT = {"kb:control+e", "kb:control+n", "kb:control+k", "kb:control+s"}


def _toggleState(btn) -> bool | None:
	if btn is None:
		return None
	try:
		states = btn.states
	except Exception:
		return None
	return State.PRESSED in states or State.CHECKED in states


class AppModule(BaseAppModule):
	disableBrowseModeByDefault = True
	scriptCategory = CAT

	def script_formatShortcut(self, gesture) -> None:
		focus = api.getFocusObject()
		if focus is None or focus.role not in (Role.DOCUMENT, Role.EDITABLETEXT, Role.PARAGRAPH):
			gesture.send()
			return
		entry = None
		key = None
		for g, value in FORMAT_BUTTONS.items():
			if normalizeGestureId(g) in [normalizeGestureId(i) for i in gesture.identifiers]:
				entry = value
				key = g
				break
		if entry is None:
			gesture.send()
			return
		names, label = entry
		# Atajos que dependen del idioma de LibreOffice: solo se anuncia si el
		# botón cambia (Control+E es «centrar» en inglés y «seleccionar todo» en
		# español; Control+N, K y S son negrita, cursiva y subrayado en español).
		requireChange = key in LANGUAGE_DEPENDENT
		before = _toggleState(findToggle(api.getForegroundObject(), names)) if requireChange else None
		gesture.send()

		def report() -> None:
			btn = findToggle(api.getForegroundObject(), names)
			if btn is None:
				return
			on = _toggleState(btn)
			if on is None or (requireChange and on == before):
				return
			if label in ALIGNMENT_LABELS:
				# La alineación no se «desactiva»: solo se dice la nueva.
				if on:
					speech.speakMessage(label)
				return
			speech.speakMessage(_("{fmt} activado").format(fmt=label) if on else _("{fmt} desactivado").format(fmt=label))

		queue_handler.callLater(120, report)

	script_formatShortcut.__doc__ = _("Confirma el efecto de los atajos de formato de LibreOffice Writer")
	script_formatShortcut.category = CAT  # type: ignore[attr-defined]


for _g in FORMAT_BUTTONS:
	AppModule._classGestures[normalizeGestureId(_g)] = "formatShortcut"  # type: ignore[attr-defined]
