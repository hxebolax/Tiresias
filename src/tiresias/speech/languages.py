"""Idiomas de la voz: normalización, dialectos, soporte del sintetizador y
procesado de los cambios de idioma de una secuencia de voz.

Lo usa :func:`tiresias.speech.api.speak` para:

- insertar cambios de idioma detectados automáticamente (guion Unicode y
  n-gramas, ver :mod:`langdetect`);
- anunciar el idioma nuevo (``reportLanguage``);
- avisar si la voz no admite el idioma (``reportNotSupportedLanguage``: voz,
  pitido o nada) y, en ese caso, seguir con el idioma de la voz;
- saber en qué idioma está cada fragmento, para aplicar la tabla de símbolos
  de ese idioma.
"""

from __future__ import annotations

from ..config import conf
from ..i18n import _
from ..log import getLogger

log = getLogger("speech.languages")

#: Nombres en español de los idiomas más comunes (el resto se pide a Windows).
_NAMES = {
	"es": _("español"),
	"en": _("inglés"),
	"fr": _("francés"),
	"de": _("alemán"),
	"it": _("italiano"),
	"pt": _("portugués"),
	"ca": _("catalán"),
	"gl": _("gallego"),
	"eu": _("euskera"),
	"ru": _("ruso"),
	"uk": _("ucraniano"),
	"el": _("griego"),
	"ar": _("árabe"),
	"fa": _("persa"),
	"he": _("hebreo"),
	"zh": _("chino"),
	"ja": _("japonés"),
	"ko": _("coreano"),
	"hi": _("hindi"),
	"th": _("tailandés"),
	"nl": _("neerlandés"),
	"pl": _("polaco"),
	"tr": _("turco"),
	"sv": _("sueco"),
	"fi": _("finés"),
	"da": _("danés"),
	"nb": _("noruego"),
	"cs": _("checo"),
	"hu": _("húngaro"),
	"ro": _("rumano"),
	"bg": _("búlgaro"),
	"hy": _("armenio"),
	"ka": _("georgiano"),
	"la": _("latín"),
}


def normalize(lang: str | None) -> str | None:
	"""``en-US`` -> ``en_US``; cadena vacía -> ``None``."""
	if not lang:
		return None
	lang = str(lang).strip().replace("-", "_")
	if not lang:
		return None
	parts = lang.split("_")
	parts[0] = parts[0].lower()
	if len(parts) > 1 and len(parts[1]) == 2:
		parts[1] = parts[1].upper()
	return "_".join(parts)


def base(lang: str | None) -> str:
	return (lang or "").split("_")[0].lower()


def languageName(lang: str) -> str:
	lang = normalize(lang) or ""
	b = base(lang)
	if "_" not in lang and b in _NAMES:
		return _NAMES[b]
	try:
		from ..i18n import languageName as winName

		name = winName(lang)
		if name and name != lang:
			return name
	except Exception:
		pass
	return _NAMES.get(b, lang)


def interfaceLanguage() -> str:
	try:
		from .. import i18n

		return normalize(i18n.LANGUAGE) or "es"
	except Exception:
		return "es"


def voiceLanguage() -> str:
	"""Idioma de la voz actual (``es`` si no se sabe)."""
	try:
		from .. import synth

		s = synth.getSynth()
		lang = s.language if s is not None else None
	except Exception:
		lang = None
	return normalize(lang) or interfaceLanguage()


def supportedLanguages() -> set[str] | None:
	"""Idiomas que admite el sintetizador (en minúsculas) o ``None`` si no se sabe."""
	try:
		from .. import synth

		s = synth.getSynth()
	except Exception:
		return None
	if s is None:
		return None
	global _supportedCache
	if _supportedCache is not None and _supportedCache[0] is s:
		return _supportedCache[1]
	result: set[str] = set()
	try:
		# Dentro del try: en algunos controladores es una propiedad que puede fallar.
		langs = getattr(s, "availableLanguages", None)
		if langs:
			for lang in langs:
				n = normalize(lang)
				if n:
					result.add(n.lower())
		else:
			for v in s.availableVoices.values():
				n = normalize(getattr(v, "language", None))
				if n:
					result.add(n.lower())
	except Exception:
		log.debug("No se pudieron leer los idiomas del sintetizador", exc_info=True)
		# Se recuerda el fallo para no repetir la consulta en cada frase.
		_supportedCache = (s, None)
		return None
	_supportedCache = (s, result or None)
	return result or None


#: (sintetizador, idiomas): la lista de voces no cambia mientras el sintetizador sigue cargado.
_supportedCache: tuple | None = None


def isSupported(lang: str, supported: set[str] | None = None) -> bool:
	if supported is None:
		supported = supportedLanguages()
	if not supported:
		return True
	n = (normalize(lang) or "").lower()
	if n in supported:
		return True
	b = base(n)
	return any(s == b or s.startswith(b + "_") for s in supported)


def resolveSwitch(lang: str | None, voiceLang: str | None = None) -> str | None:
	"""Idioma al que hay que cambiar para leer un texto marcado con ``lang``.

	Aplica la opción de dialectos y devuelve ``None`` si basta con la voz
	actual. Un texto marcado con el idioma «padre» (``en``) no cambia el
	dialecto de una voz del mismo idioma (``en_GB``) (#13561).
	"""
	lang = normalize(lang)
	if not lang:
		return None
	sp = conf["speech"]
	voiceLang = normalize(voiceLang) or voiceLanguage()
	if base(lang) != base(voiceLang):
		return lang if sp["autoDialectSwitching"] else base(lang)
	if not sp["autoDialectSwitching"]:
		return None
	if "_" not in lang:
		return None
	if lang.lower() == voiceLang.lower():
		return None
	return lang


def notSupportedSequence(lang: str) -> list:
	"""Aviso de idioma no admitido según ``reportNotSupportedLanguage``."""
	from .commands import BeepCommand

	mode = conf["speech"]["reportNotSupportedLanguage"]
	if mode == "beep":
		return [BeepCommand(400, 60)]
	if mode == "speech":
		return [_("idioma no admitido: {language}").format(language=languageName(lang))]
	return []
