"""Voces por contexto y esquemas de voz y sonido.

**Voces por contexto** (foros 2.3). El cursor del sistema, el cursor de
revisión, el eco de teclado, los mensajes de Tiresias, los menús y los
diálogos pueden tener su propia velocidad, tono y volumen, expresados como
cambio relativo (porcentaje) respecto a la voz normal (opciones
``speech/context<Contexto><Rate|Pitch|Volume>``), además de **otra voz del
mismo sintetizador** (``context<Contexto>Voice``, "" = la misma) y **otro
nivel de puntuación** (``context<Contexto>SymbolLevel``, -1 = el general).
Todo se activa con ``speech/voiceContexts``. La velocidad del eco de teclado
es la «velocidad propia del eco de teclado» y se aplica siempre.

:func:`wrapContext` añade al principio de la secuencia un
:class:`~.commands.VoiceCommand` (el gestor de voz cambia de voz entre
enunciados, ver ``SpeechManager``) y un :class:`~.commands.SymbolLevelCommand`
(``_processSequence`` lo aplica a las cadenas que siguen).

**Esquemas de voz y sonido** (foros 2.4, #4089). Un esquema con nombre
asigna a ciertos atributos un cambio de voz y, opcionalmente, un sonido que
puede sustituir a la palabra («enlace», «botón», «marcado»):

- del texto: enlaces, encabezados, citas, énfasis, resaltado, inserciones,
  eliminaciones, mayúsculas y **colores** (por familias: rojo, naranja...);
- **tipos de control**: botones, casillas, botones de opción, campos de
  edición, cuadros combinados, elementos de lista y de menú, pestañas...;
- **estados**: marcado, no marcado, no disponible, expandido, contraído,
  obligatorio, no válido...

Se aplica en el modo exploración (``browse/document.py`` ``getRangeSpeech``
con :func:`textDecoration` y :func:`filterSuffix`) y, con
``speech/voiceSchemeEverywhere``, también fuera de él: al anunciar los
controles (:func:`objectContext`, :func:`statesContext`, usados por
``presentation``) y al leer texto editable (:func:`decorateTextInfo`, que
mira el formato del texto). Hay esquemas de fábrica y el usuario puede crear
los suyos (``data/config/voiceSchemes.json``).
"""

from __future__ import annotations

import colorsys
import contextlib
import copy
import json
import os
import re
import threading
from typing import Any, Iterator

from .. import paths
from ..config import conf
from ..i18n import _
from ..log import getLogger
from .commands import PitchCommand, RateCommand, SymbolLevelCommand, VoiceCommand, VolumeCommand, WaveFileCommand

log = getLogger("speech.voiceSchemes")

# ------------------------------------------------------------------ contextos
CONTEXTS = ("caret", "review", "typing", "message", "menu", "dialog")
CONTEXT_LABELS = {
	"caret": _("Cursor del sistema"),
	"review": _("Cursor de revisión"),
	"typing": _("Eco de teclado"),
	"message": _("Mensajes de Tiresias"),
	"menu": _("Menús"),
	"dialog": _("Diálogos"),
}
_CONTEXT_KEYS = {"caret": "Caret", "review": "Review", "typing": "Typing", "message": "Message", "menu": "Menu", "dialog": "Dialog"}


def contextKey(context: str, prop: str) -> str:
	"""Nombre de la opción: ``contextTypingRate``, ``contextMenuVoice``..."""
	return f"context{_CONTEXT_KEYS[context]}{prop}"


def contextOffsets(context: str) -> tuple[int, int, int]:
	"""(velocidad, tono, volumen) relativos del contexto."""
	sp = conf["speech"]
	if context not in _CONTEXT_KEYS:
		return 0, 0, 0
	vals = []
	for prop in ("Rate", "Pitch", "Volume"):
		try:
			vals.append(int(sp[contextKey(context, prop)]))
		except (KeyError, TypeError, ValueError):
			vals.append(0)
	if not sp["voiceContexts"] and context != "typing":
		return 0, 0, 0
	if not sp["voiceContexts"]:
		# La velocidad propia del eco de teclado se aplica siempre que no sea 0.
		return vals[0], 0, 0
	return vals[0], vals[1], vals[2]


def contextVoice(context: str) -> str:
	"""Voz propia del contexto ("" = la voz normal). Solo con las voces por contexto."""
	sp = conf["speech"]
	if context not in _CONTEXT_KEYS or not sp["voiceContexts"]:
		return ""
	try:
		return str(sp[contextKey(context, "Voice")] or "")
	except KeyError:
		return ""


def contextSymbolLevel(context: str) -> int | None:
	"""Nivel de puntuación propio del contexto (``None`` = el general)."""
	sp = conf["speech"]
	if context not in _CONTEXT_KEYS or not sp["voiceContexts"]:
		return None
	try:
		level = int(sp[contextKey(context, "SymbolLevel")])
	except (KeyError, TypeError, ValueError):
		return None
	return level if level >= 0 else None


def contextVoiceChoices() -> list[tuple[str, str]]:
	"""[(id, nombre)] de las voces del sintetizador actual para la interfaz."""
	out = [("", _("La misma voz"))]
	try:
		from .. import synth

		s = synth.getSynth()
		if s is not None and s.isSupported("voice"):
			for vid, info in s.availableVoices.items():
				out.append((vid, getattr(info, "displayName", None) or str(info)))
	except Exception:
		log.debug("No se pudieron leer las voces del sintetizador", exc_info=True)
	return out


def contextSymbolLevelChoices() -> list[tuple[int, str]]:
	from .symbols import LEVEL_NAMES, SPEECH_LEVELS

	return [(-1, _("El nivel general"))] + [(lvl, LEVEL_NAMES[lvl]) for lvl in SPEECH_LEVELS]


def prosody(rate: int = 0, pitch: int = 0, volume: int = 0) -> tuple[list, list]:
	"""Órdenes para aplicar y deshacer un cambio relativo de voz."""
	before: list = []
	after: list = []
	if rate:
		before.append(RateCommand(offset=rate))
		after.append(RateCommand(0))
	if pitch:
		before.append(PitchCommand(offset=pitch))
		after.append(PitchCommand(0))
	if volume:
		before.append(VolumeCommand(offset=volume))
		after.append(VolumeCommand(0))
	return before, after


def wrapContext(context: str, items: list) -> list:
	"""Secuencia con la voz, la puntuación y la prosodia del contexto."""
	rate, pitch, volume = contextOffsets(context)
	voice = contextVoice(context)
	level = contextSymbolLevel(context)
	if not (rate or pitch or volume or voice or level is not None):
		return list(items)
	before, after = prosody(rate, pitch, volume)
	if level is not None:
		before.insert(0, SymbolLevelCommand(level))
		after.append(SymbolLevelCommand(None))
	if voice:
		before.insert(0, VoiceCommand(voice))
	return before + list(items) + after


_MENU_ROLES: set | None = None


def objectVoiceContext(obj: Any, reason: Any = None) -> str | None:
	"""Contexto de voz de un objeto anunciado: ``menu``, ``dialog`` o ``None``.

	Menús: elementos de menú, menús y barras de menú (o lo que está dentro de
	un menú). Diálogos: el propio diálogo o lo que tiene el foco dentro de uno.
	Solo se calcula si las voces por contexto están activadas y alguno de los
	dos contextos tiene ajustes propios.
	"""
	global _MENU_ROLES
	try:
		if not conf["speech"]["voiceContexts"]:
			return None
		wanted = [c for c in ("menu", "dialog") if _contextConfigured(c)]
		if not wanted or obj is None:
			return None
		from ..objects.roles import Role

		if _MENU_ROLES is None:
			_MENU_ROLES = {Role.MENUITEM, Role.CHECKMENUITEM, Role.RADIOMENUITEM, Role.MENU, Role.POPUPMENU, Role.MENUBAR}
		role = getattr(obj, "role", None)
		if "menu" in wanted and role in _MENU_ROLES:
			return "menu"
		if role == Role.DIALOG:
			return "dialog" if "dialog" in wanted else None
		from .. import api

		focus = api.getFocusObject()
		if focus is None or not (focus is obj or focus == obj):
			return None
		ancestors = api.getFocusAncestors()
		roles = [getattr(a, "role", None) for a in ancestors]
		if "menu" in wanted and any(r in (Role.MENU, Role.POPUPMENU) for r in roles):
			return "menu"
		if "dialog" in wanted and Role.DIALOG in roles:
			return "dialog"
	except Exception:
		log.debug("No se pudo calcular el contexto de voz", exc_info=True)
	return None


def _contextConfigured(context: str) -> bool:
	return any(contextOffsets(context)) or bool(contextVoice(context)) or contextSymbolLevel(context) is not None


# ------------------------------------------------------------------ atributos de los esquemas
#: Atributos del texto (modo exploración y texto editable).
TEXT_ATTRIBUTES = ("link", "visitedLink", "heading", "quote", "emphasis", "highlight", "deletion", "insertion", "clickable", "capital")
#: Familias de color del texto (foros 2.4).
COLOR_ATTRIBUTES = (
	"color_red",
	"color_orange",
	"color_yellow",
	"color_green",
	"color_cyan",
	"color_blue",
	"color_purple",
	"color_pink",
	"color_brown",
	"color_gray",
)
#: Tipos de control (#4089).
ROLE_ATTRIBUTES = (
	"role_button",
	"role_checkBox",
	"role_radioButton",
	"role_edit",
	"role_comboBox",
	"role_listItem",
	"role_menuItem",
	"role_tab",
	"role_slider",
	"role_graphic",
)
#: Estados (#4089).
STATE_ATTRIBUTES = (
	"state_checked",
	"state_notChecked",
	"state_halfChecked",
	"state_unavailable",
	"state_expanded",
	"state_collapsed",
	"state_required",
	"state_invalid",
)
ATTRIBUTES = TEXT_ATTRIBUTES + COLOR_ATTRIBUTES + ROLE_ATTRIBUTES + STATE_ATTRIBUTES
ATTRIBUTE_LABELS = {
	"link": _("Enlaces"),
	"visitedLink": _("Enlaces visitados"),
	"heading": _("Encabezados"),
	"quote": _("Citas"),
	"emphasis": _("Énfasis"),
	"highlight": _("Texto resaltado"),
	"deletion": _("Texto eliminado"),
	"insertion": _("Texto insertado"),
	"clickable": _("Elementos pulsables"),
	"capital": _("Palabras en mayúsculas"),
	"color_red": _("Color: rojo"),
	"color_orange": _("Color: naranja"),
	"color_yellow": _("Color: amarillo"),
	"color_green": _("Color: verde"),
	"color_cyan": _("Color: cian y turquesa"),
	"color_blue": _("Color: azul"),
	"color_purple": _("Color: morado y violeta"),
	"color_pink": _("Color: rosa y magenta"),
	"color_brown": _("Color: marrón"),
	"color_gray": _("Color: gris"),
	"role_button": _("Control: botones"),
	"role_checkBox": _("Control: casillas e interruptores"),
	"role_radioButton": _("Control: botones de opción"),
	"role_edit": _("Control: campos de edición"),
	"role_comboBox": _("Control: cuadros combinados"),
	"role_listItem": _("Control: elementos de lista y de árbol"),
	"role_menuItem": _("Control: elementos de menú"),
	"role_tab": _("Control: pestañas"),
	"role_slider": _("Control: deslizantes y botones de número"),
	"role_graphic": _("Control: gráficos"),
	"state_checked": _("Estado: marcado o pulsado"),
	"state_notChecked": _("Estado: no marcado"),
	"state_halfChecked": _("Estado: parcialmente marcado"),
	"state_unavailable": _("Estado: no disponible"),
	"state_expanded": _("Estado: expandido"),
	"state_collapsed": _("Estado: contraído"),
	"state_required": _("Estado: obligatorio"),
	"state_invalid": _("Estado: entrada no válida"),
}

#: {"pitch": int, "rate": int, "volume": int, "sound": str, "replaceLabel": bool}
BUILTIN_SCHEMES: dict[str, dict[str, dict]] = {
	"subtle": {
		"link": {"pitch": 15},
		"visitedLink": {"pitch": 8},
		"heading": {"pitch": -10, "rate": -10},
		"quote": {"pitch": -5},
		"emphasis": {"volume": 10},
		"capital": {"pitch": 15},
		"state_unavailable": {"volume": -25},
	},
	"sounds": {
		"link": {"sound": "link", "replaceLabel": True},
		"visitedLink": {"sound": "link", "pitch": -8},
		"heading": {"sound": "enterContainer", "pitch": -10},
		"clickable": {"sound": "clickable", "replaceLabel": True},
		"quote": {"sound": "enterContainer"},
		"role_button": {"sound": "role_button", "replaceLabel": True},
		"role_checkBox": {"sound": "role_checkBox", "replaceLabel": True},
		"role_radioButton": {"sound": "role_radioButton", "replaceLabel": True},
		"role_comboBox": {"sound": "role_comboBox", "replaceLabel": True},
		"role_edit": {"sound": "role_edit", "replaceLabel": True},
		"role_tab": {"sound": "role_tab", "replaceLabel": True},
		"state_checked": {"sound": "state_checked", "replaceLabel": True},
		"state_notChecked": {"sound": "state_notChecked", "replaceLabel": True},
		"state_halfChecked": {"sound": "state_halfChecked", "replaceLabel": True},
		"state_unavailable": {"sound": "state_unavailable", "replaceLabel": True},
		"state_expanded": {"sound": "state_expanded", "replaceLabel": True},
		"state_collapsed": {"sound": "state_collapsed", "replaceLabel": True},
	},
	"expressive": {
		"link": {"pitch": 25, "sound": "link", "replaceLabel": True},
		"visitedLink": {"pitch": 10, "sound": "link"},
		"heading": {"pitch": -20, "rate": -15, "volume": 10},
		"quote": {"pitch": -10, "rate": -10},
		"emphasis": {"pitch": 10, "volume": 15},
		"highlight": {"volume": 10, "pitch": 5},
		"deletion": {"pitch": -25},
		"insertion": {"pitch": 20},
		"clickable": {"sound": "clickable"},
		"capital": {"pitch": 25},
		"color_red": {"pitch": 15},
		"color_blue": {"pitch": -10},
		"role_button": {"pitch": -8},
		"role_edit": {"pitch": 5},
		"state_checked": {"pitch": 10, "sound": "state_checked"},
		"state_notChecked": {"pitch": -5, "sound": "state_notChecked"},
		"state_unavailable": {"pitch": -15, "volume": -30},
		"state_invalid": {"pitch": -20, "sound": "state_invalidEntry"},
	},
	# Como el esquema «Proofreading» de JAWS: atributos y colores del texto.
	"proofreading": {
		"emphasis": {"volume": 15, "rate": -10},
		"highlight": {"pitch": 10, "volume": 10},
		"deletion": {"pitch": 30},
		"insertion": {"pitch": -25},
		"capital": {"pitch": 20},
		"color_red": {"pitch": 20},
		"color_orange": {"pitch": 12},
		"color_yellow": {"pitch": 6},
		"color_green": {"pitch": -6},
		"color_cyan": {"pitch": -10},
		"color_blue": {"pitch": -15},
		"color_purple": {"pitch": -20},
		"color_pink": {"pitch": 16},
		"color_brown": {"pitch": -25},
		"color_gray": {"volume": -20},
	},
}
BUILTIN_LABELS = {
	"subtle": _("Sutil (solo cambios de tono)"),
	"sounds": _("Sonidos en lugar de palabras"),
	"expressive": _("Expresivo (tono, velocidad y sonidos)"),
	"proofreading": _("Corrección (atributos y colores del texto)"),
}

_lock = threading.Lock()
_userSchemes: dict[str, dict[str, dict]] | None = None


def _userFile() -> str:
	return os.path.join(paths.configDir(), "voiceSchemes.json")


def userSchemes() -> dict[str, dict[str, dict]]:
	global _userSchemes
	with _lock:
		if _userSchemes is None:
			data: dict = {}
			try:
				with open(_userFile(), encoding="utf-8") as f:
					raw = json.load(f)
				if isinstance(raw, dict):
					data = {str(k): v for k, v in raw.items() if isinstance(v, dict)}
			except FileNotFoundError:
				pass
			except (OSError, ValueError):
				log.exception("Esquemas de voz del usuario no válidos")
			_userSchemes = data
		return _userSchemes


def saveUserSchemes(schemes: dict[str, dict[str, dict]]) -> None:
	global _userSchemes
	os.makedirs(paths.configDir(), exist_ok=True)
	with open(_userFile(), "w", encoding="utf-8") as f:
		json.dump(schemes, f, ensure_ascii=False, indent="\t", sort_keys=True)
	with _lock:
		_userSchemes = copy.deepcopy(schemes)


def schemeChoices() -> list[tuple[str, str]]:
	out = [("", _("Ninguno"))]
	out += [(k, BUILTIN_LABELS[k]) for k in BUILTIN_SCHEMES]
	out += [(k, k) for k in sorted(userSchemes())]
	return out


def getScheme(name: str | None) -> dict[str, dict] | None:
	if not name:
		return None
	if name in userSchemes():
		return userSchemes()[name]
	return BUILTIN_SCHEMES.get(name)


def activeScheme() -> dict[str, dict] | None:
	try:
		return getScheme(conf["speech"]["voiceScheme"])
	except KeyError:
		return None


def schemeEverywhere() -> bool:
	"""``True`` si el esquema se aplica también fuera del modo exploración."""
	try:
		return bool(conf["speech"]["voiceSchemeEverywhere"])
	except KeyError:
		return False


def attributeStyle(attribute: str) -> dict | None:
	scheme = activeScheme()
	if not scheme:
		return None
	style = scheme.get(attribute)
	return style if isinstance(style, dict) and style else None


def _int(style: dict, key: str) -> int:
	try:
		return int(style.get(key, 0) or 0)
	except (TypeError, ValueError):
		return 0


def decorate(attribute: str, text, label: str = "") -> tuple[list, list, str]:
	"""Aplica el estilo de ``attribute``.

	Devuelve ``(antes, después, etiqueta)``: órdenes que van antes y después
	del texto y la etiqueta que hay que decir («» si el sonido la sustituye).
	"""
	style = attributeStyle(attribute)
	if not style:
		return [], [], label
	before, after = prosody(_int(style, "rate"), _int(style, "pitch"), _int(style, "volume"))
	sound = style.get("sound") or ""
	if sound:
		before.insert(0, WaveFileCommand(sound))
		if style.get("replaceLabel"):
			label = ""
	return before, after, label


class Style:
	"""Estilo combinado de varios atributos: prosodia sumada y sonidos."""

	def __init__(self, attributes: list[str] | None = None, scheme: dict | None = None) -> None:
		self.attributes: list[str] = []
		self.rate = self.pitch = self.volume = 0
		self.sounds: list[str] = []
		#: Atributos cuyo sonido sustituye a la palabra.
		self.replaced: set[str] = set()
		if scheme is None:
			scheme = activeScheme()
		for a in attributes or []:
			style = scheme.get(a) if scheme else None
			if not isinstance(style, dict) or not style or a in self.attributes:
				continue
			self.attributes.append(a)
			self.rate += _int(style, "rate")
			self.pitch += _int(style, "pitch")
			self.volume += _int(style, "volume")
			sound = style.get("sound") or ""
			if sound:
				if sound not in self.sounds:
					self.sounds.append(sound)
				if style.get("replaceLabel"):
					self.replaced.add(a)
		self.rate = max(-80, min(200, self.rate))
		self.pitch = max(-80, min(80, self.pitch))
		self.volume = max(-90, min(0, self.volume)) if self.volume < 0 else min(self.volume, 100)

	def __bool__(self) -> bool:
		return bool(self.attributes)

	def prosody(self) -> tuple[list, list]:
		return prosody(self.rate, self.pitch, self.volume)

	def wrap(self, seq: list, sounds: bool = True) -> list:
		"""``seq`` con los sonidos delante y el cambio de voz alrededor."""
		if not self.attributes:
			return list(seq)
		before, after = self.prosody()
		head: list = [WaveFileCommand(s) for s in self.sounds] if sounds else []
		return head + before + list(seq) + after


# ------------------------------------------------------------------ colores
def colorFamily(colorref: Any) -> str | None:
	"""Atributo de familia de color de un COLORREF (0x00BBGGRR); ``None`` para
	negro, blanco y casi negro (el color normal del texto)."""
	try:
		c = int(colorref)
	except (TypeError, ValueError):
		return None
	if c < 0 or c > 0xFFFFFF:
		return None
	r, g, b = (c & 0xFF) / 255.0, ((c >> 8) & 0xFF) / 255.0, ((c >> 16) & 0xFF) / 255.0
	h, s, v = colorsys.rgb_to_hsv(r, g, b)
	if v < 0.22:
		return None
	if s < 0.18:
		if v > 0.92:
			return None
		return "color_gray"
	deg = h * 360.0
	if 12 <= deg < 45 and v < 0.62:
		return "color_brown"
	if deg < 12 or deg >= 345:
		return "color_red"
	if deg < 42:
		return "color_orange"
	if deg < 70:
		return "color_yellow"
	if deg < 165:
		return "color_green"
	if deg < 200:
		return "color_cyan"
	if deg < 255:
		return "color_blue"
	if deg < 290:
		return "color_purple"
	return "color_pink"


def _schemeUses(scheme: dict | None, attrs: tuple[str, ...]) -> bool:
	return bool(scheme) and any(isinstance(scheme.get(a), dict) and scheme.get(a) for a in attrs)


def formatAttributes(fmt: dict) -> list[str]:
	"""Atributos del esquema que corresponden a un formato de texto."""
	out: list[str] = []
	if not fmt:
		return out
	if fmt.get("deletion"):
		out.append("deletion")
	if fmt.get("insertion"):
		out.append("insertion")
	if fmt.get("highlighted"):
		out.append("highlight")
	try:
		bold = int(fmt.get("fontWeight") or 400) >= 600
	except (TypeError, ValueError):
		bold = False
	if bold or fmt.get("italic"):
		out.append("emphasis")
	fam = colorFamily(fmt.get("color")) if "color" in fmt else None
	if fam:
		out.append(fam)
	return out


_TEXT_FORMAT_KEYS = {
	"deletion": {"deletion"},
	"insertion": {"insertion"},
	"highlight": {"highlighted"},
	"emphasis": {"fontWeight", "italic"},
}


def _formatKeys(scheme: dict | None) -> set[str]:
	keys: set[str] = set()
	if not scheme:
		return keys
	for attr, k in _TEXT_FORMAT_KEYS.items():
		if _schemeUses(scheme, (attr,)):
			keys |= k
	if _schemeUses(scheme, COLOR_ATTRIBUTES):
		keys.add("color")
	return keys


def _formatInfo(info: Any, keys: set[str]) -> dict:
	getter = getattr(info, "getFormatInfo", None)
	if getter is None:
		return {}
	try:
		return dict(getter(keys) or {})
	except TypeError:
		return dict(getter() or {})
	except Exception:
		log.debug("No se pudo leer el formato para el esquema", exc_info=True)
		return {}


def decorateTextInfo(info: Any, seq: list) -> list:
	"""Texto editable fuera del modo exploración: aplica los atributos del
	formato (énfasis, revisiones, resaltado, color) si el esquema los usa.

	Para no teñir una línea entera por una palabra, el atributo tiene que
	estar al principio y al final del texto.
	"""
	if info is None or not schemeEverywhere() or hasattr(info, "doc"):
		return seq
	scheme = activeScheme()
	keys = _formatKeys(scheme)
	if not keys:
		return seq
	start = info.copy()
	start.collapse()
	attrs = formatAttributes(_formatInfo(start, keys))
	if not attrs:
		return seq
	try:
		text = info.text
	except Exception:
		text = ""
	stripped = text.rstrip()
	if len(stripped) > 1:
		from .. import textinfo

		end = info.copy()
		try:
			end.collapse(end=True)
			end.move(textinfo.UNIT_CHARACTER, -(1 + len(text) - len(stripped)))
			endAttrs = formatAttributes(_formatInfo(end, keys))
			attrs = [a for a in attrs if a in endAttrs]
		except Exception:
			log.debug("No se pudo leer el formato del final", exc_info=True)
	return Style(attrs, scheme).wrap(seq)


# ------------------------------------------------------------------ tipos de control y estados
_ROLE_MAP: dict | None = None


def _roleMap() -> dict:
	global _ROLE_MAP
	if _ROLE_MAP is None:
		from ..objects.roles import Role

		groups = {
			"role_button": ("BUTTON", "TOGGLEBUTTON", "MENUBUTTON", "SPLITBUTTON", "DROPDOWNBUTTON"),
			"role_checkBox": ("CHECKBOX", "SWITCH"),
			"role_radioButton": ("RADIOBUTTON",),
			"role_edit": ("EDITABLETEXT", "PASSWORDEDIT"),
			"role_comboBox": ("COMBOBOX",),
			"role_listItem": ("LISTITEM", "TREEVIEWITEM", "DATAITEM"),
			"role_menuItem": ("MENUITEM", "CHECKMENUITEM", "RADIOMENUITEM"),
			"role_tab": ("TAB",),
			"role_slider": ("SLIDER", "SPINBUTTON"),
			"role_graphic": ("GRAPHIC",),
		}
		_ROLE_MAP = {}
		for attr, names in groups.items():
			for n in names:
				role = getattr(Role, n, None)
				if role is not None:
					_ROLE_MAP[role] = attr
	return _ROLE_MAP


def roleAttribute(role: Any) -> str | None:
	"""Atributo de tipo de control (``role_button``...) o, para enlaces y
	encabezados, el atributo de texto correspondiente."""
	from ..objects.roles import HEADING_ROLES, Role

	if role == Role.LINK:
		return "link"
	if role in HEADING_ROLES:
		return "heading"
	return _roleMap().get(role)


def stateAttributes(role: Any, states: set) -> list[tuple[str, Any, bool]]:
	"""[(atributo, estado, negativo)] de los estados de un control."""
	from ..objects.roles import Role, State

	out: list[tuple[str, Any, bool]] = []
	states = set(states or ())
	if State.UNAVAILABLE in states:
		out.append(("state_unavailable", State.UNAVAILABLE, False))
	if State.INVALID_ENTRY in states:
		out.append(("state_invalid", State.INVALID_ENTRY, False))
	if State.HALFCHECKED in states:
		out.append(("state_halfChecked", State.HALFCHECKED, False))
	elif State.CHECKED in states:
		out.append(("state_checked", State.CHECKED, False))
	elif State.PRESSED in states and role == Role.TOGGLEBUTTON:
		out.append(("state_checked", State.PRESSED, False))
	elif State.ON in states and role == Role.SWITCH:
		out.append(("state_checked", State.ON, False))
	elif role in (Role.CHECKBOX, Role.CHECKMENUITEM):
		out.append(("state_notChecked", State.CHECKED, True))
	elif role == Role.SWITCH:
		out.append(("state_notChecked", State.ON, True))
	if State.EXPANDED in states:
		out.append(("state_expanded", State.EXPANDED, False))
	elif State.COLLAPSED in states:
		out.append(("state_collapsed", State.COLLAPSED, False))
	if State.REQUIRED in states:
		out.append(("state_required", State.REQUIRED, False))
	if role == Role.LINK and State.VISITED in states:
		out.append(("visitedLink", State.VISITED, False))
	return out


class ObjectStyle(Style):
	"""Estilo de un control: además, qué rol y qué estados no se dicen."""

	def __init__(self, role: Any = None, states: set | None = None, scheme: dict | None = None, roleToo: bool = True) -> None:
		stAttrs = stateAttributes(role, states or set())
		roleAttr = roleAttribute(role) if roleToo else None
		# Enlace visitado: su estilo sustituye al de enlace.
		if roleAttr == "link" and any(a == "visitedLink" for a, _s, _n in stAttrs):
			scheme = scheme if scheme is not None else activeScheme()
			if scheme and isinstance(scheme.get("visitedLink"), dict) and scheme.get("visitedLink"):
				roleAttr = None
		attrs = ([roleAttr] if roleAttr else []) + [a for a, _s, _n in stAttrs]
		super().__init__(attrs, scheme)
		self.role = role
		self.replacedRole = bool(roleAttr) and roleAttr in self.replaced
		self.replacedStates: set = set()
		self.replacedNegative: set = set()
		for a, st, negative in stAttrs:
			if a in self.replaced:
				(self.replacedNegative if negative else self.replacedStates).add(st)


_stack: list[ObjectStyle] = []
_OBJECT_REASONS = {"focus", "focusEntered", "query", "mouse", "change"}


def _empty() -> ObjectStyle:
	return ObjectStyle(None, set(), {})


@contextlib.contextmanager
def objectContext(obj: Any, reason: Any = None) -> Iterator[ObjectStyle]:
	"""Estilo del esquema para un control fuera del modo exploración.

	Dentro del bloque, :func:`roleReplaced` y :func:`stateReplaced` dicen a
	``presentation`` qué palabras omitir porque las sustituye un sonido.
	"""
	style = _empty()
	reasonValue = getattr(reason, "value", reason)
	if schemeEverywhere() and (reasonValue is None or reasonValue in _OBJECT_REASONS):
		scheme = activeScheme()
		if scheme:
			try:
				style = ObjectStyle(obj.role, set(obj.states), scheme)
			except Exception:
				log.debug("No se pudo calcular el estilo del control", exc_info=True)
				style = _empty()
	_stack.append(style)
	try:
		yield style
	finally:
		_stack.pop()


@contextlib.contextmanager
def statesContext(obj: Any, added: set, removed: set) -> Iterator[ObjectStyle]:
	"""Cambios de estado: estilo de los estados añadidos (y de «no marcado»)."""
	style = _empty()
	if schemeEverywhere():
		scheme = activeScheme()
		if scheme:
			try:
				role = obj.role
				current = set(obj.states)
				# Solo cuentan los estados que han cambiado.
				changed = set(added) | set(removed)
				keep = [a for a, st, _n in stateAttributes(role, current) if st in changed]
				style = ObjectStyle(role, current, {k: v for k, v in scheme.items() if k in keep}, roleToo=False)
			except Exception:
				log.debug("No se pudo calcular el estilo del cambio de estado", exc_info=True)
				style = _empty()
	_stack.append(style)
	try:
		yield style
	finally:
		_stack.pop()


def roleReplaced(role: Any) -> bool:
	"""``True`` si el nombre del tipo de control lo sustituye un sonido del esquema."""
	return bool(_stack) and _stack[-1].replacedRole and _stack[-1].role == role


def stateReplaced(state: Any, negative: bool = False) -> bool:
	"""``True`` si la palabra del estado (o de su negativo) la sustituye un sonido."""
	if not _stack:
		return False
	st = _stack[-1]
	return state in (st.replacedNegative if negative else st.replacedStates)


# ------------------------------------------------------------------ modo exploración
def nodeAttribute(node) -> str | None:
	"""Atributo de esquema de un nodo del modo exploración."""
	from ..objects.roles import HEADING_ROLES, Role, State

	role = getattr(node, "role", None)
	if role == Role.LINK:
		return "visitedLink" if State.VISITED in getattr(node, "states", set()) else "link"
	if role in HEADING_ROLES:
		return "heading"
	if role == Role.BLOCKQUOTE:
		return "quote"
	fmt = getattr(node, "fmt", None)
	if fmt in ("emphasis", "strong"):
		return "emphasis"
	if fmt in ("deletion", "insertion"):
		return fmt
	if fmt == "mark":
		return "highlight"
	if getattr(node, "clickable", False):
		return "clickable"
	return None


def nodeAttributes(node, maxDepth: int = 6) -> list[str]:
	"""Atributos del nodo y sus antecesores cercanos (el texto de un enlace
	suele estar en un hijo del enlace)."""
	out: list[str] = []
	n = node
	depth = 0
	while n is not None and depth < maxDepth:
		a = nodeAttribute(n)
		if a and a not in out:
			out.append(a)
		n = getattr(n, "parent", None)
		depth += 1
	return out


def controlNode(node, maxDepth: int = 3):
	"""Nodo de control (botón, casilla...) que contiene el texto de ``node``."""
	n = node
	depth = 0
	while n is not None and depth < maxDepth:
		if getattr(n, "role", None) in _roleMap():
			return n
		n = getattr(n, "parent", None)
		depth += 1
	return None


def _colorAttribute(doc: Any, node: Any, offset: int) -> str | None:
	"""Familia de color del texto en ``offset`` (con caché por trozo)."""
	buf = getattr(doc, "buffer", None)
	if buf is None:
		return None
	cache = buf.__dict__.setdefault("_schemeColorCache", {}) if hasattr(buf, "__dict__") else {}
	key = (id(node), offset)
	if key in cache:
		return cache[key]
	fam = None
	try:
		from ..browse import style as browseStyle

		fmt = browseStyle.formatAt(doc, offset, {"color"})
		fam = colorFamily(fmt.get("color")) if "color" in fmt else None
	except Exception:
		log.debug("No se pudo leer el color del texto", exc_info=True)
	if len(cache) > 5000:
		cache.clear()
	cache[key] = fam
	return fam


def textDecoration(doc: Any, node: Any, offset: int, state: dict) -> tuple[list, list]:
	"""Modo exploración: órdenes antes y después del texto de un trozo.

	- atributo del texto (enlace, encabezado, énfasis...): su cambio de voz
	  (el sonido ya sonó con la etiqueta);
	- tipo de control y estados del control que contiene el texto: cambio de
	  voz y sonido (una vez por control);
	- familia de color del texto si el esquema usa colores (el sonido suena
	  al cambiar de color).

	``state`` es un diccionario que se conserva durante un mismo rango.
	"""
	scheme = activeScheme()
	if not scheme:
		return [], []
	attrs = nodeAttributes(node)
	textAttrs = attrs[:1]
	sounds: list[str] = []
	extra: list[str] = []
	ctrl = controlNode(node)
	if ctrl is not None:
		cs = ObjectStyle(ctrl.role, set(getattr(ctrl, "states", set()) or ()), scheme)
		extra += [a for a in cs.attributes if a not in textAttrs]
		done = state.setdefault("controls", set())
		if id(ctrl) not in done:
			done.add(id(ctrl))
			sounds += [s for s in cs.sounds]
	if _schemeUses(scheme, COLOR_ATTRIBUTES):
		fam = _colorAttribute(doc, node, offset)
		if fam:
			extra.append(fam)
			if state.get("color") != fam:
				sounds += Style([fam], scheme).sounds
		state["color"] = fam
	style = Style(textAttrs + extra, scheme)
	before, after = style.prosody()
	head = [WaveFileCommand(s) for s in dict.fromkeys(sounds)]
	return head + before, after


def controlSounds(node: Any, state: dict) -> list:
	"""Sonidos del tipo de control y los estados de ``node`` si aún no han
	sonado en este rango (controles sin texto propio)."""
	if getattr(node, "role", None) not in _roleMap():
		return []
	done = state.setdefault("controls", set())
	if id(node) in done:
		return []
	done.add(id(node))
	scheme = activeScheme()
	if not scheme:
		return []
	style = ObjectStyle(node.role, set(getattr(node, "states", set()) or ()), scheme)
	return [WaveFileCommand(s) for s in style.sounds]


def filterSuffix(node: Any, suffix: str) -> str:
	"""Quita del sufijo de un control del modo exploración («botón», «no
	marcado»...) las palabras que sustituye un sonido del esquema."""
	if not suffix:
		return suffix
	scheme = activeScheme()
	if not scheme:
		return suffix
	from ..objects.roles import NEGATIVE_STATE_LABELS, roleLabel, stateLabel

	style = ObjectStyle(getattr(node, "role", None), set(getattr(node, "states", set()) or ()), scheme)
	labels: list[str] = []
	if style.replacedRole:
		labels.append(roleLabel(style.role))
	for st in style.replacedStates:
		labels.append(stateLabel(st))
	for st in style.replacedNegative:
		labels.append(NEGATIVE_STATE_LABELS.get(st, ""))
	for label in sorted((l for l in labels if l), key=len, reverse=True):
		suffix = re.sub(r"(^|\s)" + re.escape(label) + r"(?=\s|$)", " ", suffix, count=1)
	return " ".join(suffix.split())
