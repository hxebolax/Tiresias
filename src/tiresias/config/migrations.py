"""Migraciones de la configuración entre versiones del esquema.

Cada archivo de configuración (``config.json`` y cada perfil) guarda la
versión del esquema con la que se escribió en ``schemaVersion``. Los archivos
sin esa clave son de la versión 1 (Tiresias 1.0.0).

Para cambiar el esquema de forma incompatible:

1. sube :data:`tiresias.config.schema.SCHEMA_VERSION`;
2. añade aquí una función ``_vN_a_vN+1(data)`` que transforme un diccionario
   de la versión anterior y regístrala en :data:`MIGRATIONS`.

Las funciones reciben solo lo que hay en el archivo (no los valores por
defecto) y lo modifican en el sitio.
"""

from __future__ import annotations

from typing import Callable

from . import schema

VERSION_KEY = "schemaVersion"


def _pop(data: dict, section: str, key: str, default=None):
	sec = data.get(section)
	if not isinstance(sec, dict) or key not in sec:
		return default
	value = sec.pop(key)
	if not sec:
		data.pop(section, None)
	return value


def _setIfMissing(data: dict, section: str, key: str, value) -> None:
	sec = data.setdefault(section, {})
	if isinstance(sec, dict) and key not in sec:
		sec[key] = value


def _v1_to_v2(data: dict) -> None:
	"""1.0.0 -> 1.0.1: se quitan las opciones duplicadas o confusas."""
	# presentation.verbosity = "low" pasa a ser el nivel «experto».
	pres = data.get("presentation")
	if isinstance(pres, dict) and pres.get("verbosity") == "low":
		pres["verbosity"] = "expert"
	# keyboard.passNonCommandKeysInBrowseMode duplicaba (invertida) browseMode.trapNonCommandGestures.
	if _pop(data, "keyboard", "passNonCommandKeysInBrowseMode") is True:
		_setIfMissing(data, "browseMode", "trapNonCommandGestures", False)
	# Las dos opciones de notificaciones se unen en presentation.reportNotifications.
	if _pop(data, "uia", "reportNotifications") is False:
		_setIfMissing(data, "presentation", "reportNotifications", False)
	# speech.outputDevice no se usaba: el dispositivo es audio.outputDevice.
	device = _pop(data, "speech", "outputDevice")
	if device:
		_setIfMissing(data, "audio", "outputDevice", device)
	# magnifier.followCaret seguía también al cursor de revisión: ahora son dos opciones.
	mag = data.get("magnifier")
	if isinstance(mag, dict) and "followCaret" in mag:
		mag.setdefault("followReview", mag["followCaret"])
	# Las categorías de depuración eran texto libre: se normalizan.
	adv = data.get("advanced")
	if isinstance(adv, dict) and "debugCategories" in adv:
		cats = adv["debugCategories"]
		if isinstance(cats, str):
			cats = [c for c in cats.split(",")]
		if isinstance(cats, list):
			adv["debugCategories"] = _normalizeCategories(cats)
	# El idioma «es» era el único posible: se pasa a automático.
	gen = data.get("general")
	if isinstance(gen, dict) and gen.get("language") == "es":
		gen.pop("language")
		if not gen:
			data.pop("general")


def _v2_to_v3(data: dict) -> None:
	"""1.0.5 -> 1.0.6: revisión del cuadro de Opciones (opciones repetidas)."""
	# Word repetía las opciones de Formato de documento (páginas, comentarios y
	# revisiones, listas y títulos de las tablas), y Excel la de los títulos.
	# Ahora usan las de Formato de documento, como en NVDA.
	for key in ("reportListItems", "reportCommentsAndRevisions", "reportPageChanges", "reportTableHeaders"):
		_pop(data, "officeWord", key)
	_pop(data, "officeExcel", "reportHeaders")
	# «Anunciar los elementos en los que se puede hacer clic» (Presentación de
	# objetos) y «Elementos en los que se puede hacer clic» (Formato de documento)
	# son ahora una sola opción.
	if _pop(data, "presentation", "reportClickable") is False:
		_setIfMissing(data, "documentFormatting", "reportClickable", False)
	# speech.reportNumbersAsDigits era la forma antigua de speech.numberReading.
	if _pop(data, "speech", "reportNumbersAsDigits") is True:
		sp = data.setdefault("speech", {})
		if isinstance(sp, dict) and sp.get("numberReading", "full") == "full":
			sp["numberReading"] = "digits"


def _normalizeCategories(cats: list) -> list[str]:
	from ..log import DEBUG_CATEGORIES, _ALIASES

	out: list[str] = []
	for c in cats:
		if not isinstance(c, str):
			continue
		key = c.strip().lower()
		key = _ALIASES.get(key, key)
		if key in DEBUG_CATEGORIES and key not in out:
			out.append(key)
	return out


def _brailleWordWrap(data: dict) -> None:
	"""«Evitar dividir palabras» (``braille.wordWrap``) pasó a ser «Ajuste del texto»
	(``braille.textWrap``). Se arregla en cada archivo (también en los perfiles)."""
	b = data.get("braille")
	if not isinstance(b, dict) or "wordWrap" not in b:
		return
	old = b.pop("wordWrap")
	if old is False and b.get("textWrap", "wordBoundaries") == "wordBoundaries":
		b["textWrap"] = "none"
	if not b:
		data.pop("braille", None)


def _updateOrigin(data: dict) -> None:
	"""1.0.13: «Origen de las actualizaciones y de la tienda» (``update.origin``).
	Quien había escrito un servidor de distribución (``update.serverUrl``)
	sigue usando solo ese servidor: «Servidor propio»."""
	upd = data.get("update")
	if isinstance(upd, dict) and str(upd.get("serverUrl") or "").strip() and "origin" not in upd:
		upd["origin"] = "propio"


#: {versión de origen: función que pasa a la versión siguiente}
MIGRATIONS: dict[int, Callable[[dict], None]] = {
	1: _v1_to_v2,
	2: _v2_to_v3,
}

#: Arreglos de claves retiradas que no subieron la versión del esquema. Son
#: idempotentes y se aplican a todo archivo que no sea de una versión posterior.
FIXUPS: list[Callable[[dict], None]] = [
	_brailleWordWrap,
	_updateOrigin,
]


def getVersion(data: dict) -> int:
	v = data.get(VERSION_KEY, 1)
	try:
		return max(1, int(v))
	except (TypeError, ValueError):
		return 1


def migrate(data: dict, target: int | None = None) -> list[int]:
	"""Lleva ``data`` hasta la versión ``target`` (la actual por defecto).

	Devuelve las versiones de origen que se han migrado (vacía si no había
	nada que hacer). Un archivo de una versión más reciente que la del
	programa se deja como está.
	"""
	target = schema.SCHEMA_VERSION if target is None else target
	version = getVersion(data)
	done: list[int] = []
	while version < target:
		func = MIGRATIONS.get(version)
		if func is not None:
			func(data)
		done.append(version)
		version += 1
	if version <= schema.SCHEMA_VERSION:
		for fix in FIXUPS:
			fix(data)
	data.pop(VERSION_KEY, None)
	return done
