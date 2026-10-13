"""Presentación de objetos y texto por voz (y braille).

Decide qué se dice de un objeto según el motivo (foco, consulta, cambio...)
y la configuración de verbosidad.
"""

from __future__ import annotations

import enum
import re
from typing import Any

from . import speech, textinfo
from .audio import earcons
from .config import conf
from .i18n import _
from .speech import verbosity
from .log import getLogger
from .objects.roles import (
	HEADING_ROLES,
	NEGATIVE_STATE_LABELS,
	ROLE_LABELS,
	SILENT_ROLES,
	Role,
	State,
	roleLabel,
	stateLabel,
)

log = getLogger("presentation")


class Reason(enum.Enum):
	FOCUS = "focus"
	FOCUSENTERED = "focusEntered"
	FOREGROUND = "foreground"
	QUERY = "query"
	CHANGE = "change"
	MOUSE = "mouse"
	CARET = "caret"
	SAYALL = "sayAll"
	REVIEW = "review"
	MESSAGE = "message"


#: Estados que no se anuncian nunca de forma general.
_NEVER_STATES = {
	State.FOCUSED,
	State.FOCUSABLE,
	State.SELECTABLE,
	State.OFFSCREEN,
	State.CHECKABLE,
	State.CLICKABLE,
	State.EDITABLE,
	State.LINKED,
	State.INVISIBLE,
	State.MULTISELECTABLE,
	State.DRAGGABLE,
}

#: Contenedores en los que se anuncia «selección múltiple» (presentation.reportMultiSelect).
#: Solo la lista, no sus elementos: con los elementos, cada archivo del
#: Explorador se leía «alfa selección múltiple 1 de 5».
_MULTISELECT_ROLES = {Role.LIST, Role.TREEVIEW, Role.TABLE, Role.DATAGRID}

#: Roles en los que «seleccionado» es implícito cuando tienen el foco.
_SELECTION_IMPLIED_ROLES = {
	Role.LISTITEM,
	Role.TREEVIEWITEM,
	Role.TAB,
	Role.MENUITEM,
	Role.DATAITEM,
	Role.TABLECELL,
	Role.TABLEROW,
	Role.RADIOBUTTON,
	Role.CHECKMENUITEM,
	Role.RADIOMENUITEM,
}

#: Roles que no se anuncian al recibir el foco (se sobrentienden).
SILENT_ROLES_ON_FOCUS = {
	Role.LISTITEM,
	Role.MENUITEM,
	Role.TREEVIEWITEM,
	Role.TABLECELL,
	Role.DATAITEM,
	Role.CHECKMENUITEM,
	Role.RADIOMENUITEM,
	Role.PANE,
	Role.FRAME,
	Role.BORDER,
}

_lastStates: dict[Any, set[State]] = {}


def headingLevel(role: Role) -> int | None:
	if role in HEADING_ROLES and role != Role.HEADING:
		return int(role) - int(Role.HEADING1) + 1
	return None


def getRoleText(obj: Any, role: Role | None = None) -> str:
	custom = None
	try:
		custom = obj.roleText
	except Exception:
		pass
	if custom:
		return custom
	role = role if role is not None else obj.role
	level = headingLevel(role)
	if not level and role == Role.HEADING:
		level = getattr(obj, "level", None) or None
	if verbosity.isExpert():
		# Nivel experto: nombres de rol cortos (#46, #17483).
		short = verbosity.shortRoleText(role, level)
		if short is not None:
			return short
	if level:
		return _("encabezado de nivel {level}").format(level=level)
	return roleLabel(role)


def _roleHandled(role: Role) -> bool:
	"""El rol no se dice si ya suena su sonido (earcons o esquema de voz, #4089)."""
	from .speech import voice_schemes

	return earcons.roleHandled(role) or voice_schemes.roleReplaced(role)


def _stateHandled(state: State, negative: bool = False) -> bool:
	"""El estado no se dice si ya suena su sonido (earcons o esquema de voz)."""
	from .speech import voice_schemes

	return earcons.stateHandled(state, negative) or voice_schemes.stateReplaced(state, negative)


def getStatesText(obj: Any, states: set[State], role: Role, reason: Reason, changedOnly: set[State] | None = None, removed: set[State] | None = None) -> list[str]:
	out: list[str] = []
	consider = changedOnly if changedOnly is not None else states
	for st in sorted(consider):
		if st == State.MULTISELECTABLE and changedOnly is None and role in _MULTISELECT_ROLES and conf["presentation"]["reportMultiSelect"]:
			# Listas, árboles y tablas en las que se pueden seleccionar varios elementos.
			out.append(stateLabel(st))
			continue
		if st in _NEVER_STATES:
			continue
		if st == State.SELECTED and reason in (Reason.FOCUS, Reason.FOCUSENTERED) and role in _SELECTION_IMPLIED_ROLES:
			continue
		if st == State.SELECTED and role == Role.RADIOBUTTON and State.CHECKED in states:
			# Botón de opción UIA: «seleccionado» es lo mismo que «marcado».
			continue
		if st == State.READONLY and role not in (Role.EDITABLETEXT, Role.PASSWORDEDIT, Role.COMBOBOX, Role.DOCUMENT):
			continue
		if st == State.READONLY and role == Role.DOCUMENT:
			continue
		if st == State.PROTECTED and role == Role.PASSWORDEDIT:
			continue
		if st == State.MULTILINE and reason != Reason.QUERY:
			# Al llegar al campo va junto al rol («edición multilínea»): ver getObjectSpeech.
			continue
		if st == State.MODAL and reason != Reason.QUERY:
			continue
		if st == State.HASPOPUP and role in (Role.COMBOBOX,):
			continue
		label = stateLabel(st)
		if label and not _stateHandled(st):
			out.append(label)
	# Estados negativos relevantes.
	if changedOnly is None:
		if role in (Role.CHECKBOX, Role.CHECKMENUITEM) and State.CHECKED not in states and State.HALFCHECKED not in states:
			if not _stateHandled(State.CHECKED, negative=True):
				out.append(NEGATIVE_STATE_LABELS[State.CHECKED])
		if role == Role.SWITCH and State.ON not in states:
			if not _stateHandled(State.ON, negative=True):
				out.append(NEGATIVE_STATE_LABELS[State.ON])
		if role == Role.TOGGLEBUTTON and State.PRESSED not in states and reason == Reason.QUERY:
			if not _stateHandled(State.PRESSED, negative=True):
				out.append(NEGATIVE_STATE_LABELS[State.PRESSED])
	elif removed:
		for st in removed:
			if st in NEGATIVE_STATE_LABELS and st not in states:
				if st == State.SELECTED and role in _SELECTION_IMPLIED_ROLES and reason != Reason.CHANGE:
					continue
				if st == State.SELECTED and role == Role.RADIOBUTTON and State.CHECKED in removed:
					continue
				if not _stateHandled(st, negative=True):
					out.append(NEGATIVE_STATE_LABELS[st])
	return out


_GUESSABLE_ROLES = {Role.LISTITEM, Role.TREEVIEWITEM, Role.MENUITEM, Role.TAB, Role.RADIOBUTTON, Role.CHECKMENUITEM, Role.RADIOMENUITEM, Role.DATAITEM}


def _guessPosition(obj: Any) -> dict:
	"""Calcula «N de M» contando los hermanos con el mismo rol."""
	try:
		role = obj.role
		if role not in _GUESSABLE_ROLES:
			return {}
		parent = obj.parent
		if parent is None:
			return {}
		siblings = [c for c in parent.children if c.role == role]
		for i, c in enumerate(siblings):
			if c == obj:
				return {"indexInGroup": i + 1, "similarItemsInGroup": len(siblings)}
	except Exception:
		pass
	return {}


def getPositionText(obj: Any) -> str:
	try:
		info = obj.positionInfo
	except Exception:
		return ""
	if not info.get("indexInGroup") and conf["presentation"]["guessObjectPositionInformationWhenUnavailable"]:
		info = dict(info)
		info.update(_guessPosition(obj))
	parts = []
	if "indexInGroup" in info and "similarItemsInGroup" in info:
		parts.append(_("{index} de {total}").format(index=info["indexInGroup"], total=info["similarItemsInGroup"]))
	if "level" in info and obj.role in (Role.TREEVIEWITEM, Role.LISTITEM, Role.DATAITEM):
		parts.append(_("nivel {level}").format(level=info["level"]))
	return " ".join(parts)


def getObjectSpeech(obj: Any, reason: Reason = Reason.QUERY) -> list[str]:
	"""Lista de fragmentos que describen un objeto."""
	pres = conf["presentation"]
	try:
		name = obj.name or ""
		role = obj.role
		states = obj.states
	except Exception:
		log.debug("Objeto no disponible", exc_info=True)
		return []
	label = _labelFor(obj)
	if label:
		name = label
	unlabeledGraphic = False
	if role == Role.GRAPHIC and not label and reason != Reason.FOCUSENTERED:
		name, unlabeledGraphic = _graphicName(obj, name)
	parts: list[str] = []
	roleText = getRoleText(obj, role)
	silent = (role in SILENT_ROLES or (reason in (Reason.FOCUS, Reason.MOUSE) and role in SILENT_ROLES_ON_FOCUS)) and not obj.roleText
	asCell = _presentAsCell(obj)
	if asCell:
		# Celda de una fila presentada con otro rol (columnas de la vista Detalles
		# del Explorador: campos de solo lectura): «Tipo: Excel.CSV», como NVDA.
		roleText = getRoleText(obj, Role.TABLECELL) if reason == Reason.QUERY else ""
		silent = not roleText
	if reason in (Reason.FOCUSENTERED, Reason.FOREGROUND):
		# Antecesores y ventanas en primer plano: nombre y rol (sin valor ni estados casi siempre).
		if name:
			parts.append(name)
		if not silent and roleText:
			parts.append(roleText)
		if reason == Reason.FOCUSENTERED and role in _MULTISELECT_ROLES and State.MULTISELECTABLE in states and pres["reportMultiSelect"]:
			# «selección múltiple» se dice al entrar en la lista, no en cada elemento.
			parts.append(stateLabel(State.MULTISELECTABLE))
		if role == Role.DIALOG:
			text = getattr(obj, "dialogText", "")
			if text:
				parts.append(text)
		else:
			desc = containerDescription(obj, name)
			if desc:
				parts.append(desc)
		return parts
	# Cada propiedad se guarda por separado y al final se ordena según la
	# plantilla del rol o el orden configurado (#7232).
	props: dict[str, list[str]] = {p: [] for p in verbosity.PROPERTIES}
	level = verbosity.level()
	onFocus = reason in (Reason.FOCUS, Reason.MOUSE)
	expertFocus = level == verbosity.LEVEL_EXPERT and onFocus
	if level == verbosity.LEVEL_BEGINNER and role in SILENT_ROLES_ON_FOCUS and role not in SILENT_ROLES:
		# Principiante: se dice siempre el tipo de control.
		silent = False
	if name:
		props["name"].append(name)
	if not silent and roleText and not (role == Role.STATICTEXT) and not _roleHandled(role):
		props["role"].append(roleText)
		if role == Role.EDITABLETEXT and State.MULTILINE in states and reason in (Reason.FOCUS, Reason.MOUSE):
			# «edición multilínea», como NVDA (en la consulta va con los estados).
			props["role"].append(stateLabel(State.MULTILINE))
	parts = props["value"]
	value = ""
	caretText = _caretContext(obj, role, states, reason)
	if caretText is not None:
		# Campos con cursor: se lee la selección o la línea, no todo el texto.
		if caretText:
			parts.append(caretText)
	else:
		try:
			value = obj.value or ""
		except Exception:
			value = ""
		if len(value) > 1000:
			value = value[:1000] + "…"
		if asCell and value:
			value = " ".join(value.translate(_BIDI_MARKS).split())
			if value and name and props["name"]:
				props["name"][-1] = f"{name}:"
		if value and value != name:
			parts.append(value)
	stateReason = Reason.QUERY if level == verbosity.LEVEL_BEGINNER and reason == Reason.FOCUS and role == Role.TOGGLEBUTTON else reason
	props["states"].extend(getStatesText(obj, states - {State.READONLY} if asCell else states, role, stateReason))
	if unlabeledGraphic:
		# Imagen sin texto alternativo fuera del modo exploración (#7412, foros 1.18).
		props["states"].append(_("sin descripción"))
	current = ariaCurrentText(obj)
	if current:
		# aria-current («página actual»...), igual que en el modo exploración.
		props["states"].append(current)
	if role in (Role.EDITABLETEXT, Role.PASSWORDEDIT) and not value and reason in (Reason.FOCUS, Reason.QUERY):
		ph = getattr(obj, "placeholder", "")
		if ph and ph != name:
			parts.append(ph)
	parts = props["description"]
	if (pres["reportObjectDescriptions"] and not expertFocus) or reason == Reason.QUERY:
		try:
			desc = obj.description
		except Exception:
			desc = ""
		if desc and desc != name and desc != value:
			parts.append(desc)
	# Una sola opción para todo: «Elementos en los que se puede hacer clic» (Formato de documento).
	if conf["documentFormatting"]["reportClickable"] and reason in (Reason.FOCUS, Reason.QUERY, Reason.MOUSE) and role in (Role.STATICTEXT, Role.GROUPING, Role.SECTION, Role.GRAPHIC, Role.PANE, Role.CUSTOM, Role.UNKNOWN):
		try:
			from .a11y import uia_client as uc

			if getattr(obj, "_prop", None) and obj._prop(uc.P_ISINVOKEPATTERNAVAILABLE, False):
				props["states"].append(_("pulsable"))
		except Exception:
			pass
	if pres["reportKeyboardShortcuts"] and reason in (Reason.FOCUS, Reason.QUERY) and not expertFocus:
		try:
			ks = obj.keyboardShortcut
		except Exception:
			ks = ""
		if ks:
			# Las letras se dicen por su nombre (#15301).
			props["shortcut"].append(verbosity.formatShortcut(ks))
	parts = props["position"]
	if pres["reportObjectPositionInformation"] and reason in (Reason.FOCUS, Reason.QUERY, Reason.MOUSE) and not expertFocus:
		pos = getPositionText(obj)
		if pos:
			parts.append(pos)
	coords = None
	try:
		coords = getattr(obj, "tableCellCoords", None)
	except Exception:
		coords = None
	if coords and role in (Role.TABLECELL, Role.DATAITEM) and conf["documentFormatting"]["reportTableCellCoords"]:
		parts.append(_("fila {row} columna {col}").format(row=coords[0], col=coords[1]))
	if reason in (Reason.FOCUS, Reason.QUERY):
		try:
			from . import formatting

			if role == Role.LINK:
				# Opción «tipo de enlace»: anclas de la misma página.
				props["role"].append(formatting.linkTypeForObject(obj))
			elif role in (Role.TABLECELL, Role.DATAITEM):
				props["description"].append(formatting.cellBordersText(obj))
		except Exception:
			log.debug("Error leyendo el tipo de enlace o los bordes", exc_info=True)
	_rememberStates(obj, states)
	joined = {k: " ".join(p for p in v if p) for k, v in props.items()}
	lvl = None
	if "{level}" in verbosity.getTemplates().get(verbosity.roleKey(role), ""):
		# Solo se calcula si la plantilla del rol lo usa.
		lvl = headingLevel(role) or (getattr(obj, "level", None) if role == Role.HEADING else None)
		if not lvl:
			try:
				lvl = obj.positionInfo.get("level")
			except Exception:
				lvl = None
	joined["level"] = str(lvl) if lvl else ""
	return [p for p in verbosity.compose(joined, role) if p]


#: Marcas invisibles de dirección del texto (fechas del Explorador).
_BIDI_MARKS = dict.fromkeys(map(ord, "\u200e\u200f\u202a\u202b\u202c\u202d\u202e"), None)


def _presentAsCell(obj: Any) -> bool:
	"""El objeto es la celda de una fila aunque su rol sea otro (``presentAsCell``)."""
	try:
		return bool(getattr(obj, "presentAsCell", False))
	except Exception:
		return False


def _caretContext(obj: Any, role: Role, states: set[State], reason: Reason) -> str | None:
	"""Texto de la selección o de la línea del cursor en campos editables.

	Devuelve ``None`` si el objeto no es un campo con cursor (se usará su
	valor normal) y una cadena (posiblemente vacía) si lo es.
	"""
	if reason not in (Reason.FOCUS, Reason.QUERY):
		return None
	if role not in (Role.EDITABLETEXT, Role.DOCUMENT, Role.RICHEDIT, Role.TERMINAL) or role == Role.PASSWORDEDIT:
		return None
	try:
		if not obj.hasText:
			return None
		sel = obj.makeTextInfo(textinfo.POSITION_SELECTION)
		if not sel.isCollapsed:
			text = sel.text
			return _("{text} seleccionado").format(text=_truncate(text, 500)) if text.strip() else ""
		info = obj.makeTextInfo(textinfo.POSITION_CARET)
		info.expand(textinfo.UNIT_LINE)
		line = info.text.rstrip("\r\n")
		return line if line.strip() else _("en blanco")
	except Exception:
		return None


def _labelFor(obj: Any) -> str | None:
	try:
		from . import labels

		return labels.getLabel(obj)
	except Exception:
		return None


#: Contenedores cuya descripción (aria-describedby) se dice al entrar en ellos (#12718).
DESCRIBED_CONTAINER_ROLES = {
	Role.GROUPING,
	Role.SECTION,
	Role.LANDMARK,
	Role.REGION,
	Role.ARTICLE,
	Role.FIGURE,
	Role.FORM,
	Role.LIST,
	Role.TABLE,
	Role.DATAGRID,
	Role.TREEVIEW,
	Role.TOOLBAR,
	Role.PANEL,
	Role.PROPERTYPAGE,
	Role.TABCONTROL,
	Role.BLOCKQUOTE,
}


def containerDescription(obj: Any, name: str = "") -> str:
	"""Descripción de un grupo o región que contiene al foco (foros 1.20, #12718)."""
	if not conf["presentation"]["reportGroupDescriptions"]:
		return ""
	try:
		if obj.role not in DESCRIBED_CONTAINER_ROLES:
			return ""
		desc = " ".join((obj.description or "").split())
	except Exception:
		return ""
	if not desc or desc == name:
		return ""
	return desc


def _graphicName(obj: Any, name: str) -> tuple[str, bool]:
	"""Nombre de una imagen y si no tiene texto alternativo (#7412, foros 1.18).

	Sin texto alternativo, el nombre pasa a ser el de su archivo (si se conoce
	y la opción está activa). Edge y Chrome ponen como nombre una invitación
	a describir la imagen, que se descarta como en el modo exploración.
	"""
	from .browse import aria as ariaSem

	lct = ""
	try:
		lct = getattr(obj, "UIALocalizedControlType", "") or ""
	except Exception:
		lct = ""
	if name and not ariaSem.isUnlabeledGraphicLct(lct):
		return name, False
	bm = conf["browseMode"]
	fileName = ""
	if bm["reportGraphicFileNames"]:
		try:
			fileName = getattr(obj, "graphicFileName", "") or ""
		except Exception:
			fileName = ""
	return fileName, bool(bm["reportUnlabeledGraphics"])


def objectLanguage(obj: Any) -> str | None:
	"""Idioma del objeto para leer su nombre (``None`` si es el de la voz o no se sabe).

	Solo con el cambio automático de idioma y la opción
	``presentation.reportObjectLanguage`` (foros 1.19).
	"""
	if not conf["speech"]["autoLanguageSwitching"] or not conf["presentation"]["reportObjectLanguage"]:
		return None
	try:
		lang = getattr(obj, "language", None)
	except Exception:
		lang = None
	if not lang:
		return None
	return normalizeLanguage(lang)


def _safeName(obj: Any) -> str:
	try:
		return obj.name or ""
	except Exception:
		return ""


def withNameLanguage(text: str, name: str, lang: str | None) -> list:
	"""Secuencia de voz con el nombre del objeto en su idioma y el resto en el de la voz."""
	if not lang or not name or not text:
		return [text]
	idx = text.find(name)
	if idx < 0:
		return [text]
	from .speech.commands import LangChangeCommand

	seq: list = []
	before = text[:idx].strip()
	after = text[idx + len(name) :].strip()
	if before:
		seq.append(before)
	seq.extend([LangChangeCommand(lang), name, LangChangeCommand(None)])
	if after:
		seq.append(after)
	return seq


def _rememberStates(obj: Any, states: set[State]) -> None:
	if len(_lastStates) > 200:
		_lastStates.clear()
	try:
		_lastStates[obj] = set(states)
	except TypeError:
		pass


def speakObject(obj: Any, reason: Reason = Reason.QUERY, isValid: Any = None) -> None:
	"""Lee un objeto. ``isValid`` sustituye al validador del foco (voz de un
	objeto que no es el foco, p. ej. el elemento seleccionado de una lista)."""
	# Sonidos de los controles (#4089): suenan aquí y pueden sustituir al rol y los estados.
	from .speech import voice_schemes

	# Esquema de voz y sonido fuera del modo exploración (foros 2.4): tipo de
	# control y estados con su voz y su sonido.
	with earcons.objectContext(obj, reason), voice_schemes.objectContext(obj, reason) as style:
		parts = getObjectSpeech(obj, reason)
	if parts:
		# El nombre se lee en el idioma del objeto (lang, UIA Culture, IA2 locale; foros 1.19).
		seq = style.wrap(withNameLanguage(" ".join(parts), _safeName(obj), objectLanguage(obj)))
		# Voz de los menús y los diálogos (voces por contexto, foros 2.3).
		ctx = voice_schemes.objectVoiceContext(obj, reason)
		if ctx:
			seq = speech.contextSequence(ctx, seq)
		if reason in (Reason.FOCUS, Reason.FOCUSENTERED):
			# Voz del foco: se descarta si el foco cambia antes de decirse.
			speech.speak(seq, origin=speech.ORIGIN_FOCUS, isValid=isValid if isValid is not None else _focusValidator(obj, reason))
		elif reason == Reason.CHANGE:
			speech.speak(seq, origin=speech.ORIGIN_CHANGE)
		else:
			speech.speak(seq)
	if reason == Reason.FOCUS:
		try:
			verbosity.scheduleTutor(obj, obj.role)
		except Exception:
			log.debug("No se pudo programar el mensaje de tutor", exc_info=True)
	from . import braille

	if reason in (Reason.FOCUS, Reason.QUERY, Reason.FOREGROUND):
		braille.handler.handleObject(obj, reason)


def _focusValidator(obj: Any, reason: Reason):
	"""Validador de la voz del foco (``None`` si la opción está desactivada)."""
	if not conf["speech"]["cancelExpiredFocusSpeech"]:
		return None
	from . import api

	if reason == Reason.FOCUS:
		if _isCurrentFocus(obj):
			return speech.focusValidator(obj)
		# Objeto que no es el foco leído «como el foco» (alertas, elemento
		# elegido de una lista de sugerencias, panel de emojis...): con el
		# validador del foco se descartaba siempre sin decirse. Vale mientras
		# el foco no cambie.
		return focusUnchangedValidator()

	def _valid() -> bool:
		# Un antecesor anunciado sigue siendo válido mientras contenga al foco.
		try:
			focus = api.getFocusObject()
			return focus is not None and (focus == obj or obj in api.getFocusAncestors())
		except Exception:
			return True

	return _valid


def ariaCurrentText(obj: Any) -> str:
	"""Texto de ``aria-current`` del objeto («página actual», «actual»...) o ``""``."""
	try:
		value = getattr(obj, "ariaCurrent", "")
	except Exception:
		return ""
	if not value or not isinstance(value, str):
		return ""
	from .browse import aria as ariaSem

	return ariaSem.currentLabel(value)


def _isCurrentFocus(obj: Any) -> bool:
	from . import api

	try:
		focus = api.getFocusObject()
		return focus is not None and (focus is obj or focus == obj)
	except Exception:
		return True


def focusUnchangedValidator():
	"""Validador «el foco no ha cambiado desde ahora» (voz de objetos que no son el foco)."""
	from . import api

	start = api.getFocusObject()

	def _valid() -> bool:
		return api.getFocusObject() is start

	return _valid


def speakObjectProperties(obj: Any, name: bool = False, role: bool = False, value: bool = False, states: bool = False, description: bool = False, reason: Reason = Reason.QUERY) -> None:
	from .speech import voice_schemes

	parts: list[str] = []
	style = None
	if name and obj.name:
		parts.append(obj.name)
	if role:
		parts.append(getRoleText(obj))
	if value:
		v = obj.value
		if v:
			parts.append(v)
	if states:
		current = obj.states
		old = _lastStates.get(obj)
		if old is not None and reason == Reason.CHANGE:
			added = current - old
			removed = old - current
			# El esquema de voz da su voz y su sonido a los estados que cambian (foros 2.4).
			with earcons.statesContext(obj, added, removed), voice_schemes.statesContext(obj, added, removed) as style:
				parts.extend(getStatesText(obj, current, obj.role, reason, changedOnly=added, removed=removed))
		else:
			parts.extend(getStatesText(obj, current, obj.role, reason))
		_rememberStates(obj, current)
	if description and obj.description:
		parts.append(obj.description)
	seq: list = withNameLanguage(" ".join(parts), obj.name if name else "", objectLanguage(obj) if name else None) if parts else []
	if style:
		# Aunque el sonido sustituya a la única palabra («marcado»), suena.
		seq = style.wrap(seq)
	if seq:
		ctx = voice_schemes.objectVoiceContext(obj, reason)
		if ctx:
			seq = speech.contextSequence(ctx, seq)
		speech.speak(seq, origin=speech.ORIGIN_CHANGE)
	from . import braille

	braille.handler.handleUpdate(obj)


# ------------------------------------------------------------------ texto
_leadingWs = re.compile(r"^[ \t]+")


def indentationText(line: str) -> str:
	from . import formatting

	return formatting.indentationText(line)


def speakLineText(text: str, info: Any = None, reason: Reason = Reason.CARET) -> None:
	from . import formatting

	stripped = text.rstrip("\r\n")
	# Sangría de las líneas (opciones de formato de documento).
	seq: list = formatting.lineIndentationSpeech(stripped, info)
	if not stripped.strip():
		seq.append(_("en blanco"))
		speech.speak(seq)
		return
	if info is not None and reason in (Reason.CARET, Reason.REVIEW):
		try:
			from . import formatting

			seq.extend(formatting.speechForMove(info))
		except Exception:
			log.debug("Error leyendo el formato", exc_info=True)
	lang = _languageOf(info)
	textSeq: list = [stripped]
	if lang:
		from .speech.commands import LangChangeCommand

		textSeq = [LangChangeCommand(lang), stripped, LangChangeCommand(None)]
	# Esquema de voz y sonido en el texto editable (énfasis, revisiones, color; foros 2.4).
	from .speech import voice_schemes

	seq.extend(voice_schemes.decorateTextInfo(info, textSeq))
	_speakInContext(seq, reason)


def _speakInContext(seq: list, reason: Reason) -> None:
	"""Habla con la voz del contexto (cursor del sistema o de revisión)."""
	if reason == Reason.REVIEW:
		speech.speak(speech.contextSequence("review", seq), origin=speech.ORIGIN_REVIEW)
	elif reason == Reason.CARET:
		speech.speak(speech.contextSequence("caret", seq), origin=speech.ORIGIN_CARET)
	else:
		speech.speak(seq)


def _languageOf(info: Any) -> str | None:
	"""Idioma del texto si difiere del de la voz (cambio automático de idioma)."""
	sp = conf["speech"]
	if info is None or not sp["autoLanguageSwitching"]:
		return None
	getter = getattr(info, "getLanguage", None)
	if getter is None:
		return None
	try:
		lang = getter()
	except Exception:
		return None
	if not lang:
		return None
	return normalizeLanguage(lang)


def normalizeLanguage(lang: str) -> str | None:
	"""Aplica la opción de dialectos y descarta el idioma de la propia voz."""
	from .speech import languages

	return languages.resolveSwitch(lang)


def speakTextInfo(info: textinfo.TextInfo, unit: str, reason: Reason = Reason.CARET) -> None:
	"""Lee la unidad (carácter, palabra, línea...) en la posición de ``info``."""
	from . import braille

	c = info.copy()
	try:
		c.expand(unit)
		text = c.text
	except Exception:
		log.debug("No se pudo expandir el texto", exc_info=True)
		text = ""
	if unit in (textinfo.UNIT_CHARACTER, textinfo.UNIT_WORD) and reason in (Reason.CARET, Reason.REVIEW):
		try:
			from . import formatting

			fmtSpeech = formatting.speechForMove(c)
			if fmtSpeech:
				speech.speak([" ".join(fmtSpeech)])
		except Exception:
			log.debug("Error leyendo el formato", exc_info=True)
	if unit == textinfo.UNIT_CHARACTER:
		if text in ("", "\r", "\n", "\r\n"):
			# Final del texto o final de línea: «en blanco», como NVDA en los
			# campos de edición (el salto de línea no es un carácter visible).
			speech.speak([_("en blanco")])
		else:
			# Cambio de idioma también por carácter: nombre y descripción en su idioma.
			speech.speakCharacter(text[0] if len(text) > 0 else text, language=_languageOf(c))
	elif unit == textinfo.UNIT_WORD:
		if not text.strip():
			speech.speakCharacter(text[:1]) if text else speech.speak([_("en blanco")])
		else:
			from .speech import voice_schemes

			lang = _languageOf(c)
			if lang:
				from .speech.commands import LangChangeCommand

				_speakInContext(voice_schemes.decorateTextInfo(c, [LangChangeCommand(lang), text, LangChangeCommand(None)]), reason)
			else:
				_speakInContext(voice_schemes.decorateTextInfo(c, [text]), reason)
	else:
		speakLineText(text, c, reason)
	# Los movimientos de la revisión llegan al braille por api.post_reviewMove
	# (respetando el seguimiento); aquí solo se trata el cursor del sistema.
	if reason != Reason.REVIEW:
		braille.handler.handleCaretMove(info)


def _truncate(text: str, limit: int = 1000) -> str:
	if len(text) > limit:
		return text[:limit] + " " + _("y {n} caracteres más").format(n=len(text) - limit)
	return text


def speakSelectionChange(old: textinfo.TextInfo, new: textinfo.TextInfo) -> None:
	selected: list[str] = []
	unselected: list[str] = []
	try:
		if new.isCollapsed and old.isCollapsed:
			# Sin selección: se lee el carácter o la línea donde quedó el cursor.
			speakTextInfo(new, textinfo.UNIT_CHARACTER)
			return
		# Inicio
		cmpStart = new.compareEndPoints(old, "startToStart")
		cmpEnd = new.compareEndPoints(old, "endToEnd")
		if cmpStart < 0:
			r = new.copy()
			r.setEndPoint(old, "endToStart")
			selected.append(r.text)
		elif cmpStart > 0:
			r = old.copy()
			r.setEndPoint(new, "endToStart")
			unselected.append(r.text)
		if cmpEnd > 0:
			r = new.copy()
			r.setEndPoint(old, "startToEnd")
			selected.append(r.text)
		elif cmpEnd < 0:
			r = old.copy()
			r.setEndPoint(new, "startToEnd")
			unselected.append(r.text)
	except Exception:
		log.debug("Error calculando cambio de selección", exc_info=True)
		selected = [new.text]
	seq: list[str] = []
	sel = "".join(selected)
	unsel = "".join(unselected)
	if sel:
		seq.append(_("{text} seleccionado").format(text=_truncate(sel)) if len(sel.strip()) else _("espacio seleccionado"))
	if unsel:
		seq.append(_("{text} deseleccionado").format(text=_truncate(unsel)))
	if not seq and new.isCollapsed:
		seq.append(_("sin selección"))
	if seq:
		speech.speak([" ".join(seq)])
	# La selección (puntos 7 y 8) se actualiza en la línea braille.
	from . import braille

	try:
		caret = new.obj.makeTextInfo(textinfo.POSITION_CARET)
	except Exception:
		caret = new
	braille.handler.handleCaretMove(caret)


def roleLabels() -> dict:
	return dict(ROLE_LABELS)
