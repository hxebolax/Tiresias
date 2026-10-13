"""Markdown a HTML semántico y seguro, sin dependencias.

Pensado para las respuestas de la IA: conserva la estructura útil para
navegar con un lector de pantalla (encabezados, listas, tablas, citas,
enlaces y bloques de código) y escapa siempre el HTML recibido. Solo se
aceptan enlaces http y https: el modelo no puede insertar scripts ni enlaces
con protocolos ejecutables.
"""

from __future__ import annotations

import html
import re
from urllib.parse import urlparse

_RE_TABLA = re.compile(r"^\s*\|?.+\|.+\|?\s*$")
_RE_SEPARADOR_TABLA = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_RE_LISTA = re.compile(r"^\s*[-+*]\s+(.+)$")
_RE_NUMERADA = re.compile(r"^\s*\d+[.)]\s+(.+)$")


def _inline(texto: str) -> str:
	"""Marcado en línea después de neutralizar el HTML."""
	fragmento = html.escape(texto, quote=True)
	codigos: list[str] = []

	def guardar_codigo(m: re.Match) -> str:
		codigos.append("<code>{}</code>".format(m.group(1)))
		return "\x00CODIGO{}\x00".format(len(codigos) - 1)

	fragmento = re.sub(r"`([^`\n]+)`", guardar_codigo, fragmento)

	def enlace(m: re.Match) -> str:
		etiqueta, destino = m.group(1), html.unescape(m.group(2))
		esquema = urlparse(destino).scheme.lower()
		if esquema not in ("http", "https"):
			return "{} ({})".format(etiqueta, html.escape(destino, quote=True))
		return '<a href="{}">{}</a>'.format(html.escape(destino, quote=True), etiqueta)

	fragmento = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", enlace, fragmento)
	fragmento = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", fragmento)
	fragmento = re.sub(r"__([^_\n]+)__", r"<strong>\1</strong>", fragmento)
	fragmento = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", fragmento)
	for indice, codigo in enumerate(codigos):
		fragmento = fragmento.replace("\x00CODIGO{}\x00".format(indice), codigo)
	return fragmento


def _celdas_tabla(linea: str) -> list[str]:
	return [celda.strip() for celda in linea.strip().strip("|").split("|")]


def markdown_a_html(markdown: str) -> str:
	"""Convierte el subconjunto habitual de Markdown a HTML semántico seguro."""
	lineas = (markdown or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
	salida: list[str] = []
	parrafo: list[str] = []
	indice = 0

	def cerrar_parrafo() -> None:
		if parrafo:
			salida.append("<p>" + "<br>".join(_inline(linea) for linea in parrafo) + "</p>")
			parrafo.clear()

	while indice < len(lineas):
		linea = lineas[indice]
		if linea.lstrip().startswith("```"):
			cerrar_parrafo()
			lenguaje = linea.lstrip()[3:].strip()
			indice += 1
			bloque = []
			while indice < len(lineas) and not lineas[indice].lstrip().startswith("```"):
				bloque.append(lineas[indice])
				indice += 1
			clase = ""
			if lenguaje and re.fullmatch(r"[A-Za-z0-9_+#.-]+", lenguaje):
				clase = ' class="language-{}"'.format(html.escape(lenguaje, quote=True))
			salida.append("<pre><code{}>{}</code></pre>".format(clase, html.escape("\n".join(bloque))))
			indice += 1
			continue
		if not linea.strip():
			cerrar_parrafo()
			indice += 1
			continue
		encabezado = re.match(r"^\s*(#{1,6})\s+(.+?)\s*#*\s*$", linea)
		if encabezado:
			cerrar_parrafo()
			nivel = len(encabezado.group(1))
			salida.append("<h{n}>{t}</h{n}>".format(n=nivel, t=_inline(encabezado.group(2))))
			indice += 1
			continue
		if indice + 1 < len(lineas) and _RE_TABLA.match(linea) and _RE_SEPARADOR_TABLA.match(lineas[indice + 1]):
			cerrar_parrafo()
			cabeceras = _celdas_tabla(linea)
			indice += 2
			filas = []
			while indice < len(lineas) and _RE_TABLA.match(lineas[indice]):
				filas.append(_celdas_tabla(lineas[indice]))
				indice += 1
			partes = ["<table><thead><tr>"]
			partes += ['<th scope="col">{}</th>'.format(_inline(c)) for c in cabeceras]
			partes.append("</tr></thead><tbody>")
			for fila in filas:
				partes.append("<tr>")
				partes += ["<td>{}</td>".format(_inline(c)) for c in fila]
				partes.append("</tr>")
			partes.append("</tbody></table>")
			salida.append("".join(partes))
			continue
		lista = _RE_LISTA.match(linea)
		numerada = _RE_NUMERADA.match(linea)
		if lista or numerada:
			cerrar_parrafo()
			etiqueta = "ul" if lista else "ol"
			patron = _RE_LISTA if lista else _RE_NUMERADA
			elementos = []
			while indice < len(lineas):
				actual = patron.match(lineas[indice])
				if not actual:
					break
				elementos.append(actual.group(1))
				indice += 1
			salida.append("<{e}>{items}</{e}>".format(e=etiqueta, items="".join("<li>{}</li>".format(_inline(i)) for i in elementos)))
			continue
		if linea.lstrip().startswith(">"):
			cerrar_parrafo()
			cita = []
			while indice < len(lineas) and lineas[indice].lstrip().startswith(">"):
				cita.append(lineas[indice].lstrip()[1:].lstrip())
				indice += 1
			salida.append("<blockquote><p>" + "<br>".join(map(_inline, cita)) + "</p></blockquote>")
			continue
		if re.match(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$", linea):
			cerrar_parrafo()
			salida.append("<hr>")
			indice += 1
			continue
		parrafo.append(linea)
		indice += 1
	cerrar_parrafo()
	return "\n".join(salida)


def html_a_texto(fragmento: str) -> str:
	"""Texto plano de un fragmento HTML (para el cuadro de texto alternativo)."""
	texto = re.sub(r"(?i)<br\s*/?>", "\n", fragmento or "")
	texto = re.sub(r"(?i)</(p|h[1-6]|li|tr|pre|blockquote|article|table|ul|ol)>", "\n", texto)
	texto = re.sub(r"(?i)</t[hd]>", "\t", texto)
	texto = re.sub(r"<[^>]+>", "", texto)
	texto = html.unescape(texto)
	return re.sub(r"\n{3,}", "\n\n", texto).strip()


def documento_html(titulo: str, cuerpo: str) -> str:
	"""Página HTML completa e independiente (para abrirla en el navegador)."""
	estilos = (
		"body{font-family:system-ui,Segoe UI,Arial,sans-serif;line-height:1.6;max-width:60em;margin:0 auto;padding:1em}"
		"article{margin:0 0 14px;padding:10px 12px;border:1px solid GrayText;border-radius:8px}"
		"article h2{font-size:1rem;margin:0 0 6px}"
		"pre{padding:10px;overflow-x:auto;white-space:pre-wrap;word-break:break-word;border:1px solid GrayText}"
		"code{font-family:ui-monospace,Consolas,monospace}"
		"table{border-collapse:collapse}th,td{border:1px solid GrayText;padding:.4rem .6rem;text-align:left}"
	)
	return (
		'<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
		"<title>{t}</title><style>{s}</style></head><body><main><h1>{t}</h1>{c}</main></body></html>"
	).format(t=html.escape(titulo), s=estilos, c=cuerpo)
