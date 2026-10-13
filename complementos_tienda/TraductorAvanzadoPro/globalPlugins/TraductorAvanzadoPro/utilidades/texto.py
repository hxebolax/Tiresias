"""Obtención y manipulación de texto."""

from __future__ import annotations

import re
from typing import Any

_SUSTITUTOS = re.compile(r"[\ud800-\udfff]")
_FIN_ORACION = re.compile(r"[.!?。！？]+\s*")


def obtener_texto_seleccionado(objeto: Any = None) -> dict[str, Any]:
	"""Texto seleccionado en ``objeto`` (o en el que tiene el cursor del sistema).

	Devuelve ``{'exito': bool, 'texto': str}``. Debe llamarse en el hilo del
	núcleo (las órdenes ya se ejecutan en él).
	"""
	from tiresias import textinfo

	resultado = {"exito": False, "texto": ""}
	if objeto is None:
		from . import lector

		objeto = lector.objeto_cursor()
	if objeto is None:
		return resultado
	try:
		ti = objeto.makeTextInfo(textinfo.POSITION_SELECTION)
		texto = getattr(ti, "text", "") or ""
	except Exception:
		texto = ""
	if not texto.strip() and objeto is not None:
		# En modo exploración la selección está en el documento virtual.
		ti_obj = getattr(objeto, "treeInterceptor", None)
		if ti_obj is not None and ti_obj is not objeto:
			try:
				texto = ti_obj.makeTextInfo(textinfo.POSITION_SELECTION).text or ""
			except Exception:
				texto = ""
	if texto.strip():
		resultado["texto"] = texto.strip()
		resultado["exito"] = True
	return resultado


def texto_de_objeto(obj: Any) -> str:
	"""Nombre del objeto o, si no tiene, todo su texto."""
	if obj is None:
		return ""
	texto = ""
	try:
		texto = obj.name or ""
	except Exception:
		texto = ""
	if not texto.strip():
		try:
			from tiresias import textinfo

			texto = obj.makeTextInfo(textinfo.POSITION_ALL).text or ""
		except Exception:
			texto = ""
	if not texto.strip():
		try:
			texto = obj.value or ""
		except Exception:
			pass
	return texto.strip()


def limpiar_sustitutos(texto: str) -> str:
	"""Quita los caracteres sustitutos sueltos de Unicode."""
	return _SUSTITUTOS.sub("", texto or "")


def limpiar_texto(texto: str) -> str:
	"""Quita sustitutos, normaliza los espacios y recorta."""
	if not texto:
		return texto
	texto = limpiar_sustitutos(texto)
	texto = re.sub(r"\s+", " ", texto)
	return texto.strip()


def dividir_oraciones(texto: str) -> list[str]:
	if not texto:
		return []
	oraciones = []
	inicio = 0
	for m in _FIN_ORACION.finditer(texto):
		trozo = texto[inicio:m.end()].strip()
		if trozo:
			oraciones.append(trozo)
		inicio = m.end()
	resto = texto[inicio:].strip()
	if resto:
		oraciones.append(resto)
	return oraciones


def contar_palabras(texto: str) -> int:
	return len(texto.split()) if texto else 0


def truncar_texto(texto: str, longitud_maxima: int = 100, sufijo: str = "...") -> str:
	if not texto or len(texto) <= longitud_maxima:
		return texto
	return texto[: longitud_maxima - len(sufijo)] + sufijo


def es_texto_traducible(texto: str) -> bool:
	"""``True`` si el texto tiene al menos una letra o un número."""
	return bool(texto) and any(c.isalnum() for c in texto.strip())


def dividir_por_longitud(texto: str, tamano_max: int, patron: re.Pattern | None = None) -> list[str]:
	"""Divide ``texto`` en trozos de como mucho ``tamano_max`` caracteres.

	Corta preferentemente tras signos de puntuación (``patron``), si no tras un
	espacio y, en último caso, en seco. Unir los trozos devuelve el texto.
	"""
	if len(texto) <= tamano_max:
		return [texto]
	patron = patron or re.compile(r"[.,!?;:،؛؟。！？、]")
	trozos: list[str] = []
	resto = texto
	while len(resto) > tamano_max:
		ventana = resto[:tamano_max]
		corte = -1
		for m in patron.finditer(ventana):
			corte = m.end()
		if corte <= 0:
			corte = ventana.rfind(" ") + 1
		if corte <= 0:
			corte = tamano_max
		trozos.append(resto[:corte])
		resto = resto[corte:]
	if resto:
		trozos.append(resto)
	return trozos
