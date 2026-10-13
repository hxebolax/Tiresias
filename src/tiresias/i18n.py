"""Internacionalización.

Tiresias está escrito en español: el texto original de cada cadena es el
español y no necesita catálogo. Las demás lenguas se traducen con catálogos
gettext en ``data/locale/<idioma>/LC_MESSAGES/tiresias.mo`` (``paths.localeDir``;
igual en la versión compilada, que solo lleva los ``.mo``).

- ``tools/i18n.py extraer`` genera ``data/locale/tiresias.pot`` con todas las
  cadenas de ``_()``, ``ngettext()`` y ``pgettext()``;
- ``tools/i18n.py actualizar`` lo fusiona con cada ``tiresias.po``;
- ``tools/i18n.py compilar`` crea los ``.mo``.

El idioma se elige en Opciones > Generales (``general.language``): «auto»
usa el idioma de la interfaz de Windows si hay traducción y, si no, español.
Cambiarlo requiere reiniciar, porque muchas cadenas se traducen al importar
los módulos.
"""

from __future__ import annotations

import gettext
import os

from . import paths

DOMAIN = "tiresias"
#: Idioma original de las cadenas.
SOURCE_LANGUAGE = "es"

_translation: gettext.NullTranslations = gettext.NullTranslations()
LANGUAGE = SOURCE_LANGUAGE


def windowsLanguage() -> str:
	"""Idioma de la interfaz de Windows (``es_ES``, ``en_US``...)."""
	import ctypes

	try:
		lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
		lang = lcidToLanguage(lcid)
		if lang:
			return lang
	except Exception:
		pass
	return SOURCE_LANGUAGE


def availableLanguages() -> list[str]:
	"""Idiomas con catálogo compilado, más el español original."""
	langs = {SOURCE_LANGUAGE}
	base = paths.localeDir()
	try:
		for entry in os.listdir(base):
			if os.path.isfile(os.path.join(base, entry, "LC_MESSAGES", DOMAIN + ".mo")):
				langs.add(entry)
	except OSError:
		pass
	return sorted(langs)


def resolveLanguage(language: str | None) -> str:
	"""Convierte «auto» o un código regional en un idioma disponible."""
	language = (language or "auto").strip() or "auto"
	if language.lower() in ("auto", "windows"):
		language = windowsLanguage()
	available = availableLanguages()
	candidates = [language, language.split("_")[0]]
	for c in candidates:
		if c in available:
			return c
	return SOURCE_LANGUAGE


def initialize(language: str = "auto") -> None:
	global _translation, LANGUAGE
	LANGUAGE = resolveLanguage(language)
	if LANGUAGE == SOURCE_LANGUAGE:
		_translation = gettext.NullTranslations()
		return
	try:
		_translation = gettext.translation(DOMAIN, paths.localeDir(), languages=[LANGUAGE])
	except Exception:
		# Catálogo ausente (OSError) o dañado (un .mo truncado da struct.error,
		# UnicodeDecodeError...): se arranca en español en lugar de no arrancar.
		_translation = gettext.NullTranslations()
		LANGUAGE = SOURCE_LANGUAGE


def _(message: str) -> str:
	return _translation.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
	return _translation.ngettext(singular, plural, n)


def pgettext(context: str, message: str) -> str:
	return _translation.pgettext(context, message)


def lcidToLanguage(lcid: int) -> str | None:
	"""Convierte un identificador de configuración regional (LCID) en ``es_ES``."""
	import ctypes

	buf = ctypes.create_unicode_buffer(85)
	try:
		if ctypes.windll.kernel32.LCIDToLocaleName(int(lcid), buf, 85, 0):
			return buf.value.replace("-", "_") or None
	except Exception:
		pass
	return None


def languageName(lang: str) -> str:
	"""Nombre de un idioma en el idioma de Windows (``en_US`` -> «inglés (Estados Unidos)»)."""
	import ctypes

	tag = lang.replace("_", "-")
	buf = ctypes.create_unicode_buffer(128)
	try:
		# LOCALE_SLOCALIZEDDISPLAYNAME = 0x02: nombre en el idioma de Windows.
		if ctypes.windll.kernel32.GetLocaleInfoEx(tag, 0x02, buf, 128):
			return buf.value
	except Exception:
		pass
	return lang


def languageNativeName(lang: str) -> str:
	"""Nombre de un idioma en ese mismo idioma («English», «español»)."""
	import ctypes

	tag = lang.replace("_", "-")
	buf = ctypes.create_unicode_buffer(128)
	try:
		# LOCALE_SNATIVELANGUAGENAME = 0x04
		if ctypes.windll.kernel32.GetLocaleInfoEx(tag, 0x04, buf, 128):
			name = buf.value
			return name[:1].upper() + name[1:]
	except Exception:
		pass
	return lang
