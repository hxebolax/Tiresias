"""Arreglos guardados por sitio web.

Se guardan en ``data\\addonsData\\arregloWeb\\sitios.json``::

	{"www.ejemplo.com": {"reglas": [ ... ]}}

Las reglas se describen en :mod:`arreglos`. Las lecturas son frecuentes (una
por búfer construido) y van en memoria; el archivo solo se escribe al cambiar.
"""

from __future__ import annotations

import json
import os
import threading

from tiresias.log import getLogger

from . import arreglos

log = getLogger("arregloWeb")

NOMBRE_ARCHIVO = "sitios.json"
#: Máximo de reglas por sitio (las más antiguas se descartan).
MAX_REGLAS_SITIO = 500

_lock = threading.Lock()
_datos: dict[str, dict] | None = None
_indice: dict[str, arreglos.ReglasSitio] = {}
#: Reglas solo de esta sesión (no se escriben en el archivo).
_sesion: dict[str, list[dict]] = {}
_rutaPruebas: str | None = None


def ruta() -> str:
	if _rutaPruebas:
		return _rutaPruebas
	from tiresias import paths

	return os.path.join(paths.addonDataDir("arregloWeb"), NOMBRE_ARCHIVO)


def sitioDe(documentKey: str) -> str:
	"""Sitio (dominio) de una clave de documento, como en la web flexible."""
	if not documentKey:
		return ""
	from tiresias.browse import flexweb

	return flexweb.siteKey(documentKey)


def _cargar() -> dict[str, dict]:
	global _datos
	if _datos is None:
		try:
			with open(ruta(), encoding="utf-8") as f:
				datos = json.load(f)
			_datos = datos if isinstance(datos, dict) else {}
		except (OSError, ValueError):
			_datos = {}
	return _datos


def _guardar() -> None:
	try:
		os.makedirs(os.path.dirname(ruta()), exist_ok=True)
		tmp = ruta() + ".tmp"
		with open(tmp, "w", encoding="utf-8") as f:
			json.dump(_datos or {}, f, ensure_ascii=False, indent=1)
		os.replace(tmp, ruta())
	except OSError:
		log.exception("No se pudieron guardar los arreglos web")


def reglasDe(sitio: str) -> arreglos.ReglasSitio | None:
	"""Reglas indexadas de un sitio o ``None`` si no tiene (se llama por cada búfer)."""
	if not sitio:
		return None
	with _lock:
		cached = _indice.get(sitio)
		if cached is not None:
			return cached
		lista = list((_cargar().get(sitio) or {}).get("reglas") or []) + _sesion.get(sitio, [])
		if not lista:
			return None
		rs = arreglos.ReglasSitio(sitio, lista)
		_indice[sitio] = rs
		return rs


def listaDe(sitio: str) -> list[dict]:
	with _lock:
		return json.loads(json.dumps((_cargar().get(sitio) or {}).get("reglas") or []))


def anadir(sitio: str, reglas: list[dict]) -> int:
	"""Añade reglas a un sitio (sin repetir). Devuelve cuántas son nuevas."""
	if not sitio or not reglas:
		return 0
	with _lock:
		datos = _cargar()
		entrada = datos.setdefault(sitio, {})
		lista = entrada.setdefault("reglas", [])
		claves = {arreglos.claveRegla(r) for r in lista}
		nuevas = 0
		for r in reglas:
			k = arreglos.claveRegla(r)
			if k in claves:
				# La misma huella con otro valor: se sustituye.
				for i, viejo in enumerate(lista):
					if arreglos.claveRegla(viejo) == k:
						lista[i] = r
				continue
			claves.add(k)
			lista.append(r)
			nuevas += 1
		del lista[: max(0, len(lista) - MAX_REGLAS_SITIO)]
		_indice.pop(sitio, None)
		_guardar()
		return nuevas


def anadirSesion(sitio: str, reglas: list[dict]) -> None:
	"""Añade reglas que valen solo hasta cerrar Tiresias."""
	if not sitio or not reglas:
		return
	with _lock:
		lista = _sesion.setdefault(sitio, [])
		claves = {arreglos.claveRegla(r) for r in lista}
		for r in reglas:
			if arreglos.claveRegla(r) not in claves:
				lista.append(r)
		_indice.pop(sitio, None)


def quitarSitio(sitio: str) -> list[dict]:
	"""Quita todas las reglas del sitio (guardadas y de la sesión). Devuelve las que había."""
	with _lock:
		datos = _cargar()
		entrada = datos.pop(sitio, None) or {}
		deSesion = _sesion.pop(sitio, [])
		_indice.pop(sitio, None)
		if entrada:
			_guardar()
		return list(entrada.get("reglas") or []) + deSesion


def quitarRegla(sitio: str, indice: int) -> dict | None:
	with _lock:
		datos = _cargar()
		lista = (datos.get(sitio) or {}).get("reglas") or []
		if not (0 <= indice < len(lista)):
			return None
		regla = lista.pop(indice)
		if not lista:
			datos.pop(sitio, None)
		_indice.pop(sitio, None)
		_guardar()
		return regla


def sitios() -> dict[str, int]:
	"""Sitios con arreglos y cuántos tiene cada uno."""
	with _lock:
		return {s: len(e.get("reglas") or []) for s, e in _cargar().items() if e.get("reglas")}


def _resetForTests(rutaArchivo: str | None = None) -> None:
	global _datos, _rutaPruebas
	with _lock:
		_datos = None
		_indice.clear()
		_sesion.clear()
		_rutaPruebas = rutaArchivo
