"""Análisis de accesibilidad de un documento del modo exploración.

Recorre el búfer virtual (``tiresias.browse.buffer.VirtualBuffer``) y
devuelve una lista de :class:`Problema`, cada uno con el arreglo que se le
puede aplicar sobre la presentación (una regla de :mod:`arreglos`) o sin
arreglo si solo se puede informar.

Las heurísticas vienen de lo que hacen NVDA, JAWS, Web Access for NVDA, axe
y Sa11y (ver ``docs/investigacion/arreglo_web.md``): nombre de enlaces en
cascada (``title``, texto alternativo o nombre de archivo de la imagen,
texto cercano, último tramo de la dirección), etiqueta de los campos por el
texto anterior o la cabecera de columna, genérico pulsable → botón, texto
corto grande o en negrita → encabezado, superposiciones de cookies, tablas
de maquetación y región principal deducida.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

from tiresias.objects.roles import HEADING_ROLES, Role

from . import arreglos

#: Máximo de problemas que se listan.
MAX_PROBLEMAS = 300
#: Longitud mínima del texto para echar en falta encabezados o regiones.
TEXTO_MINIMO_ESTRUCTURA = 800
#: Longitud máxima del contexto que se añade a un enlace («leer más: Título»).
MAX_CONTEXTO = 80

#: Textos de enlace o botón que no dicen nada fuera de contexto.
NOMBRES_INUTILES = {
	"clic aquí", "click aquí", "haz clic aquí", "haga clic aquí", "pulsa aquí", "pulse aquí", "pincha aquí", "pinche aquí", "aquí",
	"leer más", "leer mas", "lee más", "más", "mas", "ver más", "ver mas", "ver", "ver todo", "ver todos", "más información", "mas informacion",
	"más info", "saber más", "seguir leyendo", "continuar leyendo", "continuar", "siguiente", "anterior", "enlace", "link", "detalles", "info",
	"click here", "click", "here", "read more", "more", "learn more", "details", "go", "ir", "abrir", "open", "descargar", "download",
	"+", "»", "«", ">", "<", "→", "←", "...", "…",
}
#: Palabras en identificadores y clases de las superposiciones de cookies y publicidad.
PALABRAS_SUPERPOSICION = ("cookie", "consent", "gdpr", "cmp", "onetrust", "didomi", "privacy", "privacidad", "overlay", "modal", "popup", "pop-up", "lightbox", "interstitial", "banner", "newsletter", "paywall")
#: Botones de un aviso de cookies.
BOTONES_AVISO = ("aceptar", "rechazar", "acepto", "permitir", "configurar", "accept", "reject", "allow", "agree")
#: Palabras en el texto de una superposición de cookies.
TEXTO_SUPERPOSICION = ("cookie", "cookies", "consentimiento", "privacidad", "política de privacidad", "aceptar todas", "rechazar todas", "aceptar y continuar", "accept all", "reject all", "suscríbete", "subscribe")

ROLES_CAMPO = {Role.EDITABLETEXT, Role.PASSWORDEDIT, Role.COMBOBOX, Role.CHECKBOX, Role.RADIOBUTTON, Role.SPINBUTTON, Role.SLIDER, Role.SWITCH}
ROLES_BOTON = {Role.BUTTON, Role.TOGGLEBUTTON, Role.SPLITBUTTON, Role.MENUBUTTON}
ROLES_BLOQUE_GENERICO = {Role.GROUPING, Role.SECTION, Role.PANE, Role.CUSTOM, Role.UNKNOWN, Role.PARAGRAPH, Role.REGION, Role.ARTICLE, Role.LANDMARK, Role.DIALOG}

#: Etiquetas de cada tipo de problema (singular, plural).
TIPOS = {
	"enlaceSinNombre": ("enlace sin nombre", "enlaces sin nombre"),
	"botonSinNombre": ("botón sin nombre", "botones sin nombre"),
	"nombreInutil": ("enlace o botón con nombre poco útil", "enlaces o botones con nombre poco útil"),
	"nombreRepetido": ("enlace con nombre repetido y distinto destino", "enlaces con nombre repetido y distinto destino"),
	"imagenSinAlt": ("imagen sin texto alternativo", "imágenes sin texto alternativo"),
	"campoSinEtiqueta": ("campo de formulario sin etiqueta", "campos de formulario sin etiqueta"),
	"pulsable": ("elemento pulsable que no es botón ni enlace", "elementos pulsables que no son botones ni enlaces"),
	"pareceEncabezado": ("texto que parece un encabezado", "textos que parecen encabezados"),
	"sinEncabezados": ("página sin encabezados", "páginas sin encabezados"),
	"sinRegiones": ("página sin regiones", "páginas sin regiones"),
	"tablaMaquetacion": ("tabla de maquetación", "tablas de maquetación"),
	"superposicion": ("superposición que tapa el contenido", "superposiciones que tapan el contenido"),
}
ORDEN_TIPOS = list(TIPOS)


@dataclass
class Problema:
	tipo: str
	descripcion: str
	node: Any = None
	offset: int = 0
	#: Regla de :mod:`arreglos` que lo arregla, o ``None`` si solo se informa.
	regla: dict | None = None
	#: Explicación del arreglo («nombre deducido de la dirección»).
	arreglo: str = ""
	extra: dict = field(default_factory=dict)

	@property
	def tieneArreglo(self) -> bool:
		return self.regla is not None

	def texto(self) -> str:
		t = TIPOS.get(self.tipo, (self.tipo, self.tipo))[0]
		t = t[0].upper() + t[1:]
		partes = [t]
		if self.descripcion:
			partes.append(": " + self.descripcion)
		if self.arreglo:
			partes.append(" → " + self.arreglo)
		elif self.tipo == "imagenSinAlt":
			partes.append(" (sin arreglo automático: se puede describir con IA)")
		else:
			partes.append(" (sin arreglo automático)")
		return "".join(partes)


# ====================================================================== utilidades de texto
def normalizar(texto: str) -> str:
	t = " ".join((texto or "").split()).lower()
	return t.strip(" .:;,!¡¿?…»«>→<←+-–—*|()[]\"'")


def esUrlCruda(texto: str) -> bool:
	t = (texto or "").strip()
	return bool(re.match(r"^(https?://|www\.|[a-z0-9.-]+\.(com|org|net|es|edu|gov|info|io)(/|$))", t, re.I))


def esNombreInutil(texto: str) -> bool:
	t = normalizar(texto)
	if not t:
		# Solo signos («>>», «»»): no dice nada.
		return bool((texto or "").strip())
	if t in NOMBRES_INUTILES:
		return True
	if esUrlCruda(texto):
		return True
	# Solo números o signos («1», «>>»).
	return not any(ch.isalpha() for ch in t) and len(t) <= 4


_EXTENSIONES = re.compile(r"\.(html?|php|aspx?|jsp|cfm|shtml|xhtml|do|action|cgi|pl|py)$", re.I)
_EXT_DOC = re.compile(r"\.(pdf|docx?|xlsx?|pptx?|odt|ods|zip|rar|7z|mp3|mp4|txt|csv|epub|jpe?g|png|gif|svg|webp)$", re.I)


def tramoUrl(url: str) -> str:
	"""Nombre legible sacado de la dirección de un enlace (último tramo con sentido).

	``https://x.com/noticias/informe-anual-2026.pdf`` → «informe anual 2026 (pdf)».
	Si la ruta no dice nada («/», «/index.html», «/123»), el dominio.
	"""
	if not url:
		return ""
	try:
		u = urlsplit(url.strip())
	except ValueError:
		return ""
	if u.scheme in ("javascript", "mailto", "tel", "data", "blob"):
		if u.scheme == "mailto":
			return "correo a " + unquote(u.path)
		if u.scheme == "tel":
			return "teléfono " + unquote(u.path)
		return ""
	tramos = [unquote(t) for t in u.path.split("/") if t]
	host = (u.netloc or "").lower()
	if host.startswith("www."):
		host = host[4:]
	for tramo in reversed(tramos):
		ext = ""
		m = _EXT_DOC.search(tramo)
		if m:
			ext = m.group(1).lower()
			tramo = tramo[: m.start()]
		tramo = _EXTENSIONES.sub("", tramo)
		if tramo.lower() in ("index", "default", "home", "main", "page", "view", "node", "item", "p", "id"):
			continue
		legible = re.sub(r"[-_+.]+", " ", tramo).strip()
		legible = re.sub(r"\s+", " ", legible)
		if not any(ch.isalpha() for ch in legible):
			# Un número de artículo: se intenta con el tramo anterior.
			continue
		if len(legible) < 3:
			continue
		return f"{legible} ({ext})" if ext else legible
	if u.fragment:
		frag = re.sub(r"[-_+.]+", " ", unquote(u.fragment)).strip()
		if any(ch.isalpha() for ch in frag):
			return frag
	if u.query and not tramos:
		return host
	return host


def textoNodo(buf: Any, node: Any, limite: int = 200) -> str:
	if node is None or node.end <= node.start:
		return ""
	return " ".join(buf.plainText(node.start, node.end).split())[:limite]


def controlType(node: Any) -> int:
	"""Tipo de control UIA de un nodo (lo mismo que hace la web flexible)."""
	try:
		from tiresias.a11y import uia_client as uc

		el = node.element
		return int(el.GetCachedPropertyValue(uc.P_CONTROLTYPE) or 0) if el is not None else 0
	except Exception:
		return 0


def _dentroDe(node: Any, roles: set) -> bool:
	return any(a.role in roles for a in node.ancestors())


def _esTextoSuelto(node: Any) -> bool:
	"""Trozo de texto normal (no dentro de un enlace, botón o encabezado)."""
	return node.role == Role.STATICTEXT and not _dentroDe(node, {Role.LINK} | ROLES_BOTON | HEADING_ROLES)


#: Nodos cuyo texto puede servir de etiqueta de un control cercano.
ROLES_TEXTO_ETIQUETA = {Role.STATICTEXT, Role.GROUPING, Role.SECTION, Role.PARAGRAPH, Role.UNKNOWN, Role.CUSTOM, Role.PANE, Role.LISTITEM, Role.TABLECELL, Role.DATAITEM}
#: Controles cuya etiqueta visual suele ir detrás («[x] Acepto las condiciones»).
ROLES_ETIQUETA_DETRAS = {Role.CHECKBOX, Role.RADIOBUTTON, Role.SWITCH}


def _esControl(n: Any) -> bool:
	return n.role in ROLES_CAMPO or n.role in ROLES_BOTON or n.role == Role.LINK or _dentroDe(n, {Role.LINK} | ROLES_BOTON)


def _esTextoEtiqueta(n: Any) -> bool:
	if n.role not in ROLES_TEXTO_ETIQUETA or _esControl(n):
		return False
	return not n.clickable and not any(a.clickable for a in n.ancestors())


def _lineaTerminaEnCasilla(buf: Any, posicion: int) -> bool:
	"""¿La línea anterior a ``posicion`` (principio de línea) acaba en una casilla o botón de opción?"""
	if posicion <= 0:
		return False
	inicio = buf.text.rfind("\n", 0, posicion - 1) + 1
	for cs, ce, n in reversed(buf.chunksInRange(inicio, posicion)):
		if n.role in ROLES_ETIQUETA_DETRAS:
			# (Una casilla sin nombre ocupa solo un espacio en el búfer.)
			return True
		if buf.text[cs:ce].strip():
			return False
	return False


def textoAnterior(buf: Any, node: Any, maxLen: int = 60) -> str:
	"""Texto inmediatamente anterior a un elemento (su etiqueta visual probable)."""
	s = node.start
	lineaInicio = buf.text.rfind("\n", 0, s) + 1
	# Se admite la línea anterior (la etiqueta encima del campo).
	limite = buf.text.rfind("\n", 0, max(0, lineaInicio - 1)) + 1 if lineaInicio > 0 else 0
	for cs, ce, n in reversed(buf.chunksInRange(limite, s)):
		if ce > s:
			continue
		if _esControl(n):
			# Otro control por medio: su etiqueta no es esta.
			return ""
		if not _esTextoEtiqueta(n):
			continue
		t = " ".join(buf.text[cs:ce].split())
		if not t:
			continue
		lineaTexto = buf.text.rfind("\n", 0, cs) + 1
		if lineaTexto != lineaInicio and _lineaTerminaEnCasilla(buf, lineaTexto):
			# Es la etiqueta de la casilla anterior, no la de este campo.
			return ""
		return t.rstrip(" :*")[:maxLen]
	return ""


def textoSiguiente(buf: Any, node: Any, maxLen: int = 60) -> str:
	"""Texto inmediatamente posterior (etiqueta a la derecha de una casilla).

	Se admite la línea siguiente: sin disposición en pantalla, lo que sigue a
	un control va en otra línea del búfer.
	"""
	e = node.end
	lineaFin = buf.text.find("\n", e)
	lineaFin = len(buf.text) if lineaFin == -1 else lineaFin
	siguiente = buf.text.find("\n", lineaFin + 1)
	limite = len(buf.text) if siguiente == -1 else siguiente
	for cs, ce, n in buf.chunksInRange(e, limite):
		if cs < e:
			continue
		if _esControl(n):
			return ""
		if not _esTextoEtiqueta(n):
			continue
		t = " ".join(buf.text[cs:ce].split())
		if t:
			return t.strip(" :*")[:maxLen]
	return ""


def cabeceraColumna(buf: Any, node: Any) -> str:
	"""Texto de la cabecera de la columna de un campo que está en una celda."""
	celda = node if node.rowCol else next((a for a in node.ancestors() if a.rowCol), None)
	if celda is None:
		return ""
	tabla = next((a for a in celda.ancestors() if a.role in (Role.TABLE, Role.DATAGRID)), None)
	if tabla is None:
		return ""
	celdas = buf.tables.get(id(tabla)) or {}
	fila, col = celda.rowCol
	# Solo encabezados de verdad: en una tabla de maquetación la primera fila es texto cualquiera.
	for r in range(fila - 1, 0, -1):
		c = celdas.get((r, col))
		if c is not None and c is not celda and c.role in (Role.TABLECOLUMNHEADER, Role.HEADERITEM):
			t = textoNodo(buf, c, 60)
			if t:
				return t
	return ""


def contexto(buf: Any, node: Any) -> str:
	"""Encabezado anterior más cercano o, si no hay, el párrafo anterior."""
	for n in buf.iterNodes(lambda n: n.role in HEADING_ROLES, node.start, -1):
		if n.end <= node.start:
			t = textoNodo(buf, n, MAX_CONTEXTO)
			if t:
				return t
		break
	bloque = buf.textUnitOf(node)
	inicio = bloque.start if bloque is not None else node.start
	for cs, ce, n in reversed(buf.chunksInRange(max(0, inicio - 2000), inicio)):
		if ce > inicio or not _esTextoSuelto(n):
			continue
		t = " ".join(buf.text[cs:ce].split())
		if len(t) >= 12:
			return t[:MAX_CONTEXTO]
	return ""


def pareceIdentificador(nombre: str) -> bool:
	"""Nombre de archivo sin palabras («AA13Q6AL», «img_8f3a2c»): no ayuda a nadie."""
	palabras = re.findall(r"[^\W\d_]{3,}", nombre)
	palabras = [p for p in palabras if p.lower() not in ("img", "dsc", "pic", "pict", "image", "imagen", "photo", "foto")]
	return not any(re.search(r"[aeiouáéíóú]", p, re.I) and re.search(r"[^aeiouáéíóú]", p, re.I) for p in palabras)


def nombreDeArchivoImagen(buf: Any, node: Any) -> str:
	try:
		from tiresias.browse import html_details

		nombre = html_details.graphicFileName(buf, node) or ""
	except Exception:
		return ""
	return "" if pareceIdentificador(nombre) else nombre


def humanizarIdentificador(texto: str) -> str:
	"""``btnBuscarAvanzada`` / ``icon-search`` → «Buscar Avanzada» / «search»."""
	t = re.sub(r"([a-z])([A-Z])", r"\1 \2", texto or "")
	t = re.sub(r"[-_.:]+", " ", t)
	palabras = [p for p in t.split() if p.lower() not in ("btn", "button", "icon", "ico", "img", "link", "lnk", "div", "span", "wrapper", "container", "item", "el", "js", "ui")]
	t = " ".join(palabras).strip()
	return t if len(t) >= 3 and any(ch.isalpha() for ch in t) else ""


# ====================================================================== análisis
class Analizador:
	def __init__(self, buf: Any, doc: Any = None, opciones: dict | None = None, estiloBloque: Callable[[Any], bool] | None = None, nivelBloque: Callable[[Any], int] | None = None) -> None:
		self.buf = buf
		self.doc = doc
		o = dict(opciones or {})
		self.encabezadosDeducidos = o.get("encabezadosDeducidos", True)
		self.pulsables = o.get("pulsablesComoBotones", True)
		#: Función ``bloque -> destaca`` (por defecto, ``browse.style.isProminent`` con el documento).
		self.estiloBloque = estiloBloque
		self.nivelBloque = nivelBloque
		self.problemas: list[Problema] = []
		self._ct: dict[int, int] = {}

	# ------------------------------------------------------------ ayudas
	def ct(self, node: Any) -> int:
		k = id(node)
		if k not in self._ct:
			self._ct[k] = controlType(node)
		return self._ct[k]

	def huella(self, node: Any) -> dict:
		return arreglos.huella(node, self.ct(node))

	def _add(self, tipo: str, node: Any, descripcion: str, regla: dict | None = None, arreglo: str = "", **extra) -> Problema:
		p = Problema(tipo, descripcion, node, node.start if node is not None else 0, regla, arreglo, dict(extra))
		self.problemas.append(p)
		return p

	def _reglaNombre(self, node: Any, nombre: str) -> dict:
		return {"tipo": "nombre", "huella": self.huella(node), "nombre": nombre}

	# ------------------------------------------------------------ recorrido
	def analizar(self) -> list[Problema]:
		buf = self.buf
		self.problemas = []
		nodos = [n for n in buf.nodes if n is not buf.root]
		for n in nodos:
			if len(self.problemas) >= MAX_PROBLEMAS:
				break
			if n.role == Role.LINK:
				self._enlace(n)
			elif n.role in ROLES_BOTON:
				self._boton(n)
			elif n.role == Role.GRAPHIC:
				self._imagen(n)
			elif n.role in ROLES_CAMPO:
				self._campo(n)
			elif n.clickable and self.pulsables:
				self._pulsable(n)
			elif n.role in (Role.TABLE, Role.DATAGRID):
				self._tabla(n)
		self._repetidos()
		self._superposiciones()
		self._estructura()
		if self.encabezadosDeducidos:
			self._encabezados()
		orden = {t: i for i, t in enumerate(ORDEN_TIPOS)}
		self.problemas.sort(key=lambda p: (orden.get(p.tipo, 99), p.offset))
		return self.problemas[:MAX_PROBLEMAS]

	# ------------------------------------------------------------ enlaces y botones
	def _nombreDeducido(self, node: Any, conUrl: bool = True) -> tuple[str, str]:
		"""(nombre, de dónde sale) para un enlace o botón sin nombre."""
		buf = self.buf
		desc = " ".join((node.description or "").split())
		if desc and not esNombreInutil(desc):
			return desc[:120], "título (atributo title o descripción)"
		# aria-label o alt de los hijos (si el navegador no los subió al enlace).
		for h in buf.subtreeOf(node):
			if h is node:
				continue
			nombre = " ".join((h.name or "").split())
			if nombre and h.role != Role.STATICTEXT and not esNombreInutil(nombre):
				return nombre[:120], "etiqueta de un elemento interior"
		for h in buf.subtreeOf(node):
			if h.role == Role.GRAPHIC:
				archivo = nombreDeArchivoImagen(buf, h)
				if archivo and len(archivo) >= 3 and not re.fullmatch(r"[\d\s]+|img|image|imagen|pic|photo|foto|icon|icono|spacer|blank|pixel|logo\d*", archivo, re.I):
					return archivo[:120], "nombre del archivo de la imagen"
		aid = humanizarIdentificador(node.automationId)
		if aid:
			return aid[:120], "identificador del elemento"
		cls = humanizarIdentificador(node.className) if len(node.className or "") < 60 else ""
		if cls:
			return cls[:120], "clase del elemento"
		if conUrl and node.url:
			# En los enlaces, la dirección antes que el texto de al lado (que suele
			# ser otro enlace o un pie que no describe el destino).
			tramo = tramoUrl(node.url)
			if tramo:
				return tramo[:120], "último tramo de la dirección"
		cercano = textoAnterior(buf, node, 80) or textoSiguiente(buf, node, 80)
		if cercano and len(cercano) >= 3:
			return cercano[:120], "texto cercano"
		return "", ""

	def _enlace(self, node: Any) -> None:
		buf = self.buf
		texto = textoNodo(buf, node)
		sinNombre = not node.name.strip() and (not texto or texto in ("enlace", "gráfico", "gráfico sin descripción") or texto.startswith("gráfico sin descripción") or texto.startswith("gráfico "))
		if sinNombre:
			nombre, origen = self._nombreDeducido(node)
			regla = self._reglaNombre(node, nombre) if nombre else None
			self._add("enlaceSinNombre", node, f"destino {node.url}" if node.url else "sin destino", regla, f"nombre «{nombre}» ({origen})" if nombre else "")
			return
		if esNombreInutil(node.name or texto):
			nombre = ""
			origen = ""
			if esUrlCruda(node.name or texto):
				tramo = tramoUrl(node.url or node.name or texto)
				if tramo:
					nombre, origen = tramo, "último tramo de la dirección"
			else:
				ctx = contexto(buf, node)
				if ctx and normalizar(ctx) != normalizar(texto):
					nombre, origen = f"{texto}: {ctx}", "texto más el encabezado o párrafo anterior"
				else:
					desc = " ".join((node.description or "").split())
					if desc and normalizar(desc) != normalizar(texto):
						nombre, origen = desc[:120], "título (atributo title)"
					elif node.url:
						tramo = tramoUrl(node.url)
						if tramo and normalizar(tramo) != normalizar(texto):
							nombre, origen = f"{texto}: {tramo}", "texto más el último tramo de la dirección"
			regla = self._reglaNombre(node, nombre) if nombre else None
			self._add("nombreInutil", node, f"«{texto}»", regla, f"nombre «{nombre}» ({origen})" if nombre else "")

	def _boton(self, node: Any) -> None:
		if (node.name or "").strip() or (node.value or "").strip():
			if esNombreInutil(node.name):
				desc = " ".join((node.description or "").split())
				nombre = desc if desc and normalizar(desc) != normalizar(node.name) else ""
				regla = self._reglaNombre(node, nombre) if nombre else None
				self._add("nombreInutil", node, f"botón «{node.name}»", regla, f"nombre «{nombre}» (título)" if nombre else "")
			return
		nombre, origen = self._nombreDeducido(node, conUrl=False)
		regla = self._reglaNombre(node, nombre) if nombre else None
		self._add("botonSinNombre", node, "", regla, f"nombre «{nombre}» ({origen})" if nombre else "")

	def _repetidos(self) -> None:
		"""Enlaces con el mismo texto y distinto destino («Ver», «Ver», «Ver»)."""
		buf = self.buf
		ya = {id(p.node) for p in self.problemas}
		grupos: dict[str, list] = {}
		for n in buf.nodes:
			if n.role != Role.LINK or id(n) in ya or not n.url:
				continue
			t = normalizar(n.name or textoNodo(buf, n))
			if t and len(t) <= 40:
				grupos.setdefault(t, []).append(n)
		for t, enlaces in grupos.items():
			destinos = {e.url.split("#")[0] for e in enlaces}
			if len(enlaces) < 2 or len(destinos) < 2:
				continue
			for e in enlaces:
				if len(self.problemas) >= MAX_PROBLEMAS:
					return
				texto = e.name or textoNodo(buf, e)
				ctx = contexto(buf, e)
				nombre = f"{texto}: {ctx}" if ctx and normalizar(ctx) != t else ""
				if not nombre:
					tramo = tramoUrl(e.url)
					if tramo and normalizar(tramo) != t:
						nombre = f"{texto}: {tramo}"
				regla = self._reglaNombre(e, nombre) if nombre else None
				self._add("nombreRepetido", e, f"«{texto}» ({len(enlaces)} enlaces, {len(destinos)} destinos)", regla, f"nombre «{nombre}»" if nombre else "")

	# ------------------------------------------------------------ imágenes
	def _imagen(self, node: Any) -> None:
		if node.name.strip() and not node.unlabeled:
			return
		if _dentroDe(node, {Role.LINK} | ROLES_BOTON):
			# La cubre el enlace o el botón que la contiene.
			return
		loc = node.location
		if loc and loc[2] > 0 and loc[3] > 0 and (loc[2] < 12 or loc[3] < 12):
			# Separadores y píxeles de seguimiento: decorativos.
			return
		archivo = nombreDeArchivoImagen(self.buf, node)
		regla = None
		arreglo = ""
		if archivo and len(archivo) >= 3 and not re.fullmatch(r"[\d\s]+|img|image|imagen|pic|photo|foto|icon|icono|spacer|blank|pixel", archivo, re.I):
			regla = self._reglaNombre(node, archivo)
			arreglo = f"nombre «{archivo}» (nombre del archivo)"
		desc = f"{loc[2]}×{loc[3]} píxeles" if loc and loc[2] > 0 else ""
		self._add("imagenSinAlt", node, desc, regla, arreglo, archivo=archivo)

	# ------------------------------------------------------------ campos
	def _campo(self, node: Any) -> None:
		if (node.name or "").strip():
			return
		buf = self.buf
		etiqueta = ""
		origen = ""
		desc = " ".join((node.description or "").split())
		if desc:
			etiqueta, origen = desc, "título o descripción"
		if not etiqueta and node.role in ROLES_ETIQUETA_DETRAS:
			etiqueta, origen = textoSiguiente(buf, node), "texto siguiente"
		if not etiqueta:
			etiqueta, origen = cabeceraColumna(buf, node), "cabecera de la columna"
		if not etiqueta:
			etiqueta, origen = textoAnterior(buf, node), "texto anterior"
		if not etiqueta:
			etiqueta, origen = humanizarIdentificador(node.automationId), "identificador del campo"
		if not etiqueta and node.role not in ROLES_ETIQUETA_DETRAS:
			etiqueta, origen = textoSiguiente(buf, node), "texto siguiente"
		etiqueta = (etiqueta or "")[:80]
		regla = {"tipo": "etiqueta", "huella": self.huella(node), "nombre": etiqueta} if etiqueta else None
		from tiresias.objects.roles import roleLabel

		self._add("campoSinEtiqueta", node, roleLabel(node.role), regla, f"etiqueta «{etiqueta}» ({origen})" if etiqueta else "")

	# ------------------------------------------------------------ pulsables
	def _pulsable(self, node: Any) -> None:
		if node.role in ROLES_BOTON or node.role == Role.LINK or _dentroDe(node, {Role.LINK} | ROLES_BOTON):
			return
		texto = textoNodo(self.buf, node, 80)
		nombre = texto or " ".join((node.name or "").split()) or " ".join((node.description or "").split()) or humanizarIdentificador(node.automationId)
		regla = {"tipo": "boton", "huella": self.huella(node), "nombre": nombre} if nombre else None
		self._add("pulsable", node, f"«{texto}»" if texto else "sin texto", regla, f"botón «{nombre}»" if nombre else "")

	# ------------------------------------------------------------ tablas
	def _tabla(self, node: Any) -> None:
		if node.layoutTable or node.ariaRole in ("grid", "treegrid"):
			return
		buf = self.buf
		celdas = buf.tables.get(id(node)) or {}
		if not celdas:
			return
		unicas = {id(c): c for c in celdas.values()}.values()
		if any(c.role in (Role.TABLECOLUMNHEADER, Role.TABLEROWHEADER, Role.HEADERITEM) for c in unicas):
			return
		filas, cols = node.tableSize or (0, 0)
		anidada = any(n.role in (Role.TABLE, Role.DATAGRID) for n in buf.subtreeOf(node) if n is not node)
		longitudes = [c.end - c.start for c in unicas]
		media = sum(longitudes) / len(longitudes) if longitudes else 0
		if anidada or media > 120 or filas <= 2 or cols <= 1:
			motivo = "contiene otras tablas" if anidada else ("celdas con párrafos largos" if media > 120 else f"{filas} filas y {cols} columnas sin encabezados")
			regla = {"tipo": "maquetacion", "huella": self.huella(node)}
			self._add("tablaMaquetacion", node, f"{filas}×{cols}, {motivo}", regla, "se presenta como maquetación (sin anuncios de tabla ni de celdas)")

	# ------------------------------------------------------------ superposiciones
	def _superposiciones(self) -> None:
		buf = self.buf
		if not buf.text:
			return
		vistos: set[int] = set()
		for n in buf.nodes:
			if n is buf.root or n.parent is None or n.role not in ROLES_BLOQUE_GENERICO or n.end <= n.start:
				continue
			if any(id(a) in vistos for a in n.ancestors()):
				continue
			ident = f"{n.automationId} {n.className}".lower()
			porIdent = any(p in ident for p in PALABRAS_SUPERPOSICION)
			esDialogo = n.role == Role.DIALOG or n.aria.get("modal") == "true"
			if not porIdent and not esDialogo:
				continue
			texto = textoNodo(buf, n, 600).lower()
			porTexto = any(p in texto for p in TEXTO_SUPERPOSICION)
			if not porTexto and not esDialogo:
				continue
			if not porTexto and esDialogo and not porIdent:
				# Un diálogo cualquiera (un formulario de inicio de sesión) no es una superposición de cookies.
				continue
			fraccion = (n.end - n.start) / len(buf.text)
			if fraccion > 0.5:
				continue
			vistos.add(id(n))
			regla = None
			arreglo = ""
			try:
				from tiresias.browse import flexweb

				flex = flexweb.ruleForNode(n)
				if flex is not None and flexweb.hiddenFraction(flex, buf) <= flexweb.MAX_HIDDEN_FRACTION:
					regla = {"tipo": "ocultar", "flex": flex}
					arreglo = f"se oculta en este sitio con la web flexible ({flexweb.describeRule(flex)})"
			except Exception:
				regla = None
			self._add("superposicion", n, textoNodo(buf, n, 60) or (n.automationId or n.className), regla, arreglo)
		if not vistos:
			self._avisoCookiesSinContenedor()

	def _avisoCookiesSinContenedor(self) -> None:
		"""Aviso de cookies dentro de un ``div`` que Chromium no publica.

		Sin contenedor no hay identificador ni clase: se reconoce por su texto
		seguido de un botón de aceptar o rechazar, y se ocultan los dos. El botón
		es lo que evita confundirlo con un artículo que hable de las cookies.
		"""
		from tiresias.browse import flexweb

		buf = self.buf
		for i, n in enumerate(buf.nodes):
			nombre = n.name.strip()
			if n.role != Role.STATICTEXT or not nombre or len(nombre) > 400 or not any(p in nombre.lower() for p in ("cookie", "consentimiento")):
				continue
			botones = [b for b in buf.nodes[i + 1 : i + 10] if b.role == Role.BUTTON and any(p in b.name.lower() for p in BOTONES_AVISO)]
			if not botones:
				continue
			for m in (n, *botones):
				flex = {"ct": flexweb._nodeControlType(m), "id": "", "name": m.name[:80], "cls": ""}
				regla = {"tipo": "ocultar", "flex": flex} if flexweb.hiddenFraction(flex, buf) <= flexweb.MAX_HIDDEN_FRACTION else None
				self._add("superposicion", m, m.name[:60], regla, f"se oculta en este sitio con la web flexible ({flexweb.describeRule(flex)})" if regla else "")
			return

	# ------------------------------------------------------------ estructura
	def _estructura(self) -> None:
		buf = self.buf
		if len(buf.text) < TEXTO_MINIMO_ESTRUCTURA:
			return
		if not any(n.role in HEADING_ROLES and n.end > n.start for n in buf.nodes):
			self._add("sinEncabezados", None, f"{len(buf.text)} caracteres sin ningún encabezado", None, "")
		if not any(n.role == Role.LANDMARK for n in buf.nodes):
			bloque = self._regionPrincipal()
			regla = {"tipo": "region", "huella": self.huella(bloque), "landmark": "principal"} if bloque is not None else None
			self._add("sinRegiones", bloque, "ningún punto de referencia", regla, "el bloque con más texto se presenta como región principal" if bloque is not None else "")

	def _regionPrincipal(self) -> Any:
		"""Bloque que parece el contenido principal: el que más texto tiene fuera de enlaces."""
		buf = self.buf
		total = len(buf.text)
		mejor = None
		mejorPuntos = 0
		for n in buf.nodes:
			if n is buf.root or n.parent is None or n.role not in ROLES_BLOQUE_GENERICO or n.end <= n.start:
				continue
			if n.parent is not buf.root and (n.parent.parent is not buf.root):
				continue
			enEnlaces = sum(max(0, min(l.end, n.end) - max(l.start, n.start)) for l in buf.nodes if l.role == Role.LINK and l.start >= n.start and l.start < n.end)
			puntos = (n.end - n.start) - enEnlaces
			if puntos > mejorPuntos:
				mejor, mejorPuntos = n, puntos
		if mejor is None or mejorPuntos < total * 0.3:
			return None
		return mejor

	def _encabezados(self) -> None:
		buf = self.buf
		destaca = self.estiloBloque
		nivelDe = self.nivelBloque
		if destaca is None:
			if self.doc is None:
				return
			from tiresias.browse import style

			doc = self.doc

			def destaca(b, _doc=doc, _style=style):
				return _style.isProminent(_doc, b)

			def nivelDe(b, _doc=doc, _style=style):
				st = _style.blockStyle(_doc, b)
				return float(st[1] or 0) if st else 0.0

		try:
			from tiresias.browse import style

			bloques = style.textBlocks(buf)[:400]
		except Exception:
			return
		prominentes = []
		for b in bloques:
			try:
				if b.role in HEADING_ROLES or any(a.role in HEADING_ROLES for a in b.ancestors()):
					continue
				if destaca(b):
					prominentes.append(b)
			except Exception:
				continue
		if not prominentes:
			return
		tamanos = sorted({float(nivelDe(b) or 0) for b in prominentes if nivelDe is not None}, reverse=True)
		hayH1 = any(n.role == Role.HEADING1 for n in buf.nodes)
		base = 2 if hayH1 else 1
		for b in prominentes:
			if len(self.problemas) >= MAX_PROBLEMAS:
				return
			tam = float(nivelDe(b) or 0) if nivelDe is not None else 0.0
			nivel = base + (tamanos.index(tam) if tam in tamanos else len(tamanos))
			nivel = max(1, min(6, nivel))
			texto = textoNodo(buf, b, 80)
			objetivo = self._objetivoEncabezado(b)
			regla = {"tipo": "encabezado", "huella": self.huella(objetivo), "nivel": nivel}
			self._add("pareceEncabezado", b, f"«{texto}»", regla, f"encabezado de nivel {nivel}")

	def _objetivoEncabezado(self, bloque: Any) -> Any:
		"""Nodo al que se aplica la regla: el trozo de texto si es lo único que hay en el bloque.

		Un bloque genérico sin nombre solo se reconoce por su posición; su
		texto, por su contenido, que es más estable.
		"""
		if bloque.role == Role.STATICTEXT:
			return bloque
		otros = [n for n in self.buf.subtreeOf(bloque) if n is not bloque and n.end > n.start and n.role != Role.STATICTEXT and not n.children]
		hojas = [n for n in self.buf.subtreeOf(bloque) if n.role == Role.STATICTEXT and n.name.strip()]
		if len(hojas) == 1 and not otros:
			return hojas[0]
		return bloque


def analizar(buf: Any, doc: Any = None, opciones: dict | None = None, **kw) -> list[Problema]:
	return Analizador(buf, doc, opciones, **kw).analizar()


# ====================================================================== informe
def resumen(problemas: list[Problema], sitio: str = "") -> str:
	"""Frase para la voz: «Arreglo web: 6 problemas en x.com: 2 enlaces sin nombre...; 5 con arreglo»."""
	if sitio.startswith("file:"):
		# Una carpeta del disco no es un nombre que se pueda oír.
		sitio = "esta carpeta"
	if not problemas:
		return f"Arreglo web: no se han encontrado problemas en {sitio}." if sitio else "Arreglo web: no se han encontrado problemas."
	cuenta = Counter(p.tipo for p in problemas)
	partes = []
	for tipo in ORDEN_TIPOS:
		n = cuenta.get(tipo, 0)
		if n:
			partes.append(f"{n} {TIPOS[tipo][0 if n == 1 else 1]}")
	conArreglo = sum(1 for p in problemas if p.tieneArreglo)
	total = len(problemas)
	donde = f" en {sitio}" if sitio else ""
	cabeza = f"Arreglo web: {total} problema{'' if total == 1 else 's'}{donde}: " + ", ".join(partes) + "."
	if conArreglo == total:
		cola = " Todos tienen arreglo." if total > 1 else " Tiene arreglo."
	elif conArreglo:
		cola = f" {conArreglo} con arreglo."
	else:
		cola = " Ninguno tiene arreglo automático."
	return cabeza + cola


def informeTexto(problemas: list[Problema], sitio: str = "") -> str:
	lineas = [resumen(problemas, sitio), ""]
	for i, p in enumerate(problemas, 1):
		lineas.append(f"{i}. {p.texto()}")
	return "\n".join(lineas)
