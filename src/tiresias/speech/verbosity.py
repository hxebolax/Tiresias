"""Niveles de verbosidad, plantillas de anuncio por rol y mensajes de tutor.

**Niveles** (``presentation/verbosity``, #46):

- ``beginner`` (principiante): todo, con nombres de rol completos.
- ``normal`` (intermedio): el comportamiento habitual.
- ``expert`` (experto): nombres de rol cortos («encabezado 2», «casilla»,
  «combo»...), sin descripciones, teclas de acceso ni posición al recibir el
  foco (se siguen diciendo al consultar el objeto). El antiguo valor ``low``
  equivale a ``expert``.

**Orden de las propiedades** (``presentation/propertyOrder``, #7232) y
**plantillas por rol** (``presentation/roleTemplates``, #17483): una
plantilla es un texto con marcadores ``{name}``, ``{role}``, ``{value}``,
``{states}``, ``{description}``, ``{shortcut}``, ``{position}`` y
``{level}``. Las propiedades que no aparecen en la plantilla no se dicen.
Ejemplo para encabezados: ``{name} e{level}``.

**Mensajes de tutor**: pistas de uso («Pulse espacio para marcar o
desmarcar») que se dicen tras un retardo si el foco sigue en el control
(``presentation/tutorMessages``: ``off``, ``complex`` o ``all``).
"""

from __future__ import annotations

import re
import string
from typing import Any

from ..config import conf
from ..i18n import _
from ..log import getLogger

log = getLogger("speech.verbosity")

LEVEL_BEGINNER = "beginner"
LEVEL_NORMAL = "normal"
LEVEL_EXPERT = "expert"
LEVEL_CHOICES = [
	(LEVEL_BEGINNER, _("Principiante")),
	(LEVEL_NORMAL, _("Intermedio")),
	(LEVEL_EXPERT, _("Experto")),
]

PROPERTIES = ("name", "role", "value", "states", "description", "shortcut", "position")
PROPERTY_LABELS = {
	"name": _("Nombre"),
	"role": _("Tipo (rol)"),
	"value": _("Valor"),
	"states": _("Estados"),
	"description": _("Descripción"),
	"shortcut": _("Tecla de acceso"),
	"position": _("Posición («2 de 5»)"),
	"level": _("Nivel (encabezados y árboles)"),
}
DEFAULT_ORDER = list(PROPERTIES)


def level() -> str:
	try:
		v = conf["presentation"]["verbosity"]
	except KeyError:
		return LEVEL_NORMAL
	if v == "low":
		return LEVEL_EXPERT
	return v if v in (LEVEL_BEGINNER, LEVEL_NORMAL, LEVEL_EXPERT) else LEVEL_NORMAL


def isExpert() -> bool:
	return level() == LEVEL_EXPERT


def isBeginner() -> bool:
	return level() == LEVEL_BEGINNER


def roleKey(role: Any) -> str:
	"""Identificador de plantilla de un rol: ``button``, ``checkbox``..."""
	name = getattr(role, "name", None)
	return name.lower() if name else str(role)


def _shortRoles() -> dict:
	from ..objects.roles import Role

	return {
		Role.CHECKBOX: _("casilla"),
		Role.RADIOBUTTON: _("opción"),
		Role.COMBOBOX: _("combo"),
		Role.MENUITEM: _("menú"),
		Role.LISTITEM: "",
		Role.TREEVIEWITEM: "",
		Role.TABCONTROL: _("pestañas"),
		Role.SLIDER: _("deslizador"),
		Role.PROGRESSBAR: _("progreso"),
		Role.TOOLBAR: _("herramientas"),
		Role.DROPDOWNBUTTON: _("botón"),
		Role.TOGGLEBUTTON: _("alternar"),
		Role.SPLITBUTTON: _("botón"),
		Role.MENUBUTTON: _("botón de menú"),
		Role.SPINBUTTON: _("número"),
		Role.MENUBAR: _("menús"),
		Role.TABLECELL: "",
		Role.DOCUMENT: _("doc"),
	}


def shortRoleText(role: Any, headingLevel: int | None) -> str | None:
	"""Nombre de rol corto para el nivel experto (``None`` = usar el normal)."""
	if headingLevel:
		return _("encabezado {level}").format(level=headingLevel)
	return _shortRoles().get(role)


# ------------------------------------------------------------------ teclas de acceso
_shortcutSplit = re.compile(r"(\s*[+,]\s*|\s+)")


def formatShortcut(text: str, language: str | None = None) -> str:
	"""Dice las letras de las teclas de acceso por su nombre (#15301).

	«Alt+F» se convierte en «Alt+ efe» para que el sintetizador no lo lea
	como si fuera parte de una frase.
	"""
	if not text or not conf["speech"]["spellAccessKeys"]:
		return text
	from .symbols import getProcessor, processor

	proc = getProcessor(language) or processor
	out: list[str] = []
	for tok in _shortcutSplit.split(text):
		if len(tok) == 1 and (tok.isalnum() or tok in string.punctuation) and tok not in "+,":
			out.append(" " + proc.characterName(tok) + " ")
		else:
			out.append(tok)
	return re.sub(r"\s{2,}", " ", "".join(out)).strip()


# ------------------------------------------------------------------ plantillas
class _SafeDict(dict):
	def __missing__(self, key: str) -> str:
		return ""


def getOrder() -> list[str]:
	try:
		order = list(conf["presentation"]["propertyOrder"])
	except KeyError:
		order = []
	order = [p for p in order if p in PROPERTIES]
	# Las propiedades que falten se añaden al final en su orden normal.
	return order + [p for p in DEFAULT_ORDER if p not in order]


def getTemplates() -> dict[str, str]:
	try:
		raw = conf["presentation"]["roleTemplates"]
	except KeyError:
		return {}
	data = raw.dict() if hasattr(raw, "dict") else dict(raw or {})
	return {str(k): str(v) for k, v in data.items() if isinstance(v, str) and v.strip()}


def validateTemplate(template: str) -> str | None:
	"""Mensaje de error si la plantilla no es válida; ``None`` si lo es."""
	try:
		fields = [f for _t, f, _s, _c in string.Formatter().parse(template) if f is not None]
	except ValueError as e:
		return _("La plantilla no es válida: {error}").format(error=e)
	allowed = set(PROPERTIES) | {"level"}
	for f in fields:
		if f not in allowed:
			return _("Marcador desconocido: {{{name}}}").format(name=f)
	return None


def templateFor(role: Any) -> str | None:
	"""Plantilla válida del rol o ``None`` si se usa el orden general."""
	template = getTemplates().get(roleKey(role))
	if template and validateTemplate(template) is None:
		return template
	return None


def compose(props: dict[str, str], role: Any) -> list[str]:
	"""Ordena las propiedades según la plantilla del rol o el orden general."""
	template = getTemplates().get(roleKey(role))
	if template and validateTemplate(template) is None:
		text = template.format_map(_SafeDict({k: v or "" for k, v in props.items()}))
		text = re.sub(r"\s{2,}", " ", text).strip()
		return [text] if text else []
	return [props[p] for p in getOrder() if props.get(p)]


# ------------------------------------------------------------------ tutor
def _tutorHints() -> dict:
	from ..objects.roles import Role

	return {
		Role.CHECKBOX: (False, _("Pulse espacio para marcar o desmarcar.")),
		Role.RADIOBUTTON: (False, _("Use las flechas para elegir otra opción del grupo.")),
		Role.BUTTON: (False, _("Pulse espacio o intro para activarlo.")),
		Role.TOGGLEBUTTON: (False, _("Pulse espacio para activarlo o desactivarlo.")),
		Role.SWITCH: (False, _("Pulse espacio para activarlo o desactivarlo.")),
		Role.LINK: (False, _("Pulse intro para seguir el enlace.")),
		Role.EDITABLETEXT: (False, _("Escriba el texto. Use las flechas para revisar lo escrito.")),
		Role.PASSWORDEDIT: (False, _("Escriba la contraseña; no se anuncian los caracteres.")),
		Role.LISTITEM: (False, _("Use las flechas arriba y abajo para moverse por la lista.")),
		Role.MENUITEM: (False, _("Pulse intro para elegirlo o escape para cerrar el menú.")),
		Role.COMBOBOX: (True, _("Use las flechas arriba y abajo para cambiar la opción, o Alt+flecha abajo para abrir la lista.")),
		Role.TREEVIEWITEM: (True, _("Use las flechas arriba y abajo para moverse, y derecha o izquierda para expandir o contraer.")),
		Role.SLIDER: (True, _("Use las flechas para cambiar el valor; Re Pág y Av Pág lo cambian más deprisa.")),
		Role.SPINBUTTON: (True, _("Use las flechas arriba y abajo para cambiar el número, o escríbalo.")),
		Role.TAB: (True, _("Use las flechas izquierda y derecha, o Control+Tab, para cambiar de pestaña.")),
		Role.DATAITEM: (True, _("Use las flechas para moverse por las celdas.")),
		Role.TABLECELL: (True, _("Use las flechas para moverse por las celdas.")),
		Role.MENUBAR: (True, _("Use las flechas izquierda y derecha para recorrer los menús e intro para abrirlos.")),
		Role.SPLITBUTTON: (True, _("Pulse espacio para activarlo o Alt+flecha abajo para ver más opciones.")),
		Role.MENUBUTTON: (True, _("Pulse espacio o intro para abrir el menú.")),
		Role.DROPDOWNBUTTON: (True, _("Pulse espacio o intro para abrir la lista.")),
	}


def tutorHint(role: Any) -> str | None:
	try:
		mode = conf["presentation"]["tutorMessages"]
	except KeyError:
		mode = "off"
	if mode == "off":
		return None
	entry = _tutorHints().get(role)
	if not entry:
		return None
	complex_, text = entry
	if mode == "complex" and not complex_:
		return None
	return text


_tutorTimer: int | None = None


def cancelTutor() -> None:
	global _tutorTimer
	if _tutorTimer is not None:
		from .. import queue_handler

		try:
			queue_handler.cancelCallLater(_tutorTimer)
		except Exception:
			pass
		_tutorTimer = None


def scheduleTutor(obj: Any, role: Any) -> None:
	"""Programa la pista de uso de ``obj`` (se descarta si el foco cambia)."""
	global _tutorTimer
	cancelTutor()
	hint = tutorHint(role)
	if not hint:
		return
	from .. import queue_handler

	delay = int(conf["presentation"]["tutorMessagesDelay"])
	_tutorTimer = queue_handler.callLater(max(0, delay), _speakTutor, obj, hint)


def _speakTutor(obj: Any, hint: str) -> None:
	global _tutorTimer
	_tutorTimer = None
	from .. import api
	from . import api as speech

	try:
		if api.getFocusObject() != obj:
			return
	except Exception:
		return
	if speech.isSpeaking():
		# Se espera a que termine de hablar para no interrumpir.
		speech.whenDoneSpeaking(lambda: _speakTutorNow(obj, hint))
		return
	_speakTutorNow(obj, hint)


def _speakTutorNow(obj: Any, hint: str) -> None:
	from .. import api
	from . import api as speech

	try:
		if api.getFocusObject() != obj:
			return
	except Exception:
		return
	speech.speakMessage(hint)
