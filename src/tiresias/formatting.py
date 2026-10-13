"""Anuncio del formato del documento (opciones de «Formato de documento»).

Al mover el cursor por un documento se anuncian solo los **cambios** de
formato respecto a la posición anterior (fuente, tamaño, negrita, color,
estilo, alineación, sangría, página, comentarios, revisiones, errores...).
Con Tiresias+F se anuncia el formato completo.
"""

from __future__ import annotations

from typing import Any

from .config import conf
from .i18n import _
from .log import getLogger

log = getLogger("formatting")

#: Último formato anunciado por control (clave: :func:`_stateKey`).
_lastFormat: dict[Any, dict] = {}


def _stateKey(obj: Any) -> Any:
	"""Clave estable de un control para recordar su último formato y sangría.

	No sirve ``id(obj)``: los objetos se recrean en cada foco y Python reutiliza
	los identificadores, así que un control podría heredar el estado de otro.
	"""
	if obj is None:
		return None
	try:
		rid = getattr(obj, "runtimeId", None)
		if rid:
			return ("uia", tuple(rid))
	except Exception:
		pass
	try:
		hwnd = getattr(obj, "windowHandle", None)
		if hwnd:
			return ("hwnd", hwnd, getattr(obj, "IAccessibleChildID", 0))
	except Exception:
		pass
	return ("id", id(obj))

_ALIGNMENTS = {0: _("alineado a la izquierda"), 1: _("centrado"), 2: _("alineado a la derecha"), 3: _("justificado")}

# Paleta propia para nombrar colores (RGB -> nombre).
_COLORS = [
	((0, 0, 0), _("negro")),
	((255, 255, 255), _("blanco")),
	((128, 128, 128), _("gris")),
	((192, 192, 192), _("gris claro")),
	((64, 64, 64), _("gris oscuro")),
	((255, 0, 0), _("rojo")),
	((139, 0, 0), _("rojo oscuro")),
	((128, 0, 32), _("granate")),
	((255, 192, 203), _("rosa")),
	((255, 105, 180), _("rosa intenso")),
	((255, 165, 0), _("naranja")),
	((255, 255, 0), _("amarillo")),
	((255, 255, 224), _("amarillo claro")),
	((255, 215, 0), _("dorado")),
	((165, 42, 42), _("marrón")),
	((210, 180, 140), _("beige")),
	((0, 128, 0), _("verde")),
	((144, 238, 144), _("verde claro")),
	((0, 100, 0), _("verde oscuro")),
	((128, 128, 0), _("verde oliva")),
	((0, 255, 0), _("verde lima")),
	((0, 255, 255), _("cian")),
	((64, 224, 208), _("turquesa")),
	((0, 128, 128), _("verde azulado")),
	((0, 0, 255), _("azul")),
	((173, 216, 230), _("azul claro")),
	((0, 0, 128), _("azul marino")),
	((135, 206, 235), _("azul cielo")),
	((65, 105, 225), _("azul real")),
	((128, 0, 128), _("morado")),
	((238, 130, 238), _("violeta")),
	((255, 0, 255), _("magenta")),
	((200, 162, 200), _("lila")),
	((255, 253, 208), _("crema")),
]


#: Formas de decir un color (opción ``documentFormatting.colorFormat``, #8674).
COLOR_FORMATS = [
	("name", _("Solo el nombre")),
	("nameAndRgb", _("Nombre y valores RGB")),
	("nameAndHex", _("Nombre y código hexadecimal")),
]


def colorRgb(colorref: Any) -> tuple[int, int, int] | None:
	"""(rojo, verde, azul) de un COLORREF (0x00BBGGRR); ``None`` si no es válido."""
	try:
		c = int(colorref)
	except (TypeError, ValueError):
		return None
	if c < 0 or c > 0xFFFFFF:
		return None
	return c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF


def colorBaseName(colorref: Any) -> str:
	"""Nombre del color más cercano de la paleta propia (sin valores)."""
	rgb = colorRgb(colorref)
	if rgb is None:
		return ""
	r, g, b = rgb
	best = min(_COLORS, key=lambda item: (item[0][0] - r) ** 2 + (item[0][1] - g) ** 2 + (item[0][2] - b) ** 2)
	return best[1]


def colorValuesText(colorref: Any, fmt: str) -> str:
	"""Valores del color según ``fmt`` («rojo 31, verde 78, azul 121» o «hexadecimal 1F4E79»)."""
	rgb = colorRgb(colorref)
	if rgb is None:
		return ""
	r, g, b = rgb
	if fmt == "nameAndRgb":
		return _("rojo {r}, verde {g}, azul {b}").format(r=r, g=g, b=b)
	if fmt == "nameAndHex":
		return _("hexadecimal {code}").format(code=f"{r:02X}{g:02X}{b:02X}")
	return ""


def colorName(colorref: Any, fmt: str | None = None) -> str:
	"""Nombre de un color COLORREF (0x00BBGGRR) de UIA u Office.

	Según ``documentFormatting.colorFormat`` (o ``fmt``) añade los valores
	RGB o el código hexadecimal al nombre aproximado (#8674).
	"""
	name = colorBaseName(colorref)
	if not name:
		return ""
	if fmt is None:
		try:
			fmt = conf["documentFormatting"]["colorFormat"]
		except KeyError:
			fmt = "name"
	values = colorValuesText(colorref, fmt)
	# Sin paréntesis: con más puntuación la voz los leería.
	return f"{name}, {values}" if values else name


def _wantedKeys() -> set[str]:
	df = conf["documentFormatting"]
	keys: set[str] = set()
	if df["reportFontName"]:
		keys.add("fontName")
	if df["reportFontSize"]:
		keys.add("fontSize")
	if df["reportFontAttributes"]:
		keys |= {"fontWeight", "italic", "underline", "strikethrough"}
	if df["reportSuperscriptsAndSubscripts"]:
		keys |= {"superscript", "subscript"}
	if df["reportColor"]:
		keys |= {"color", "backgroundColor"}
	if df["reportStyle"]:
		keys.add("style")
	if df["reportAlignment"]:
		keys.add("alignment")
	if df["reportParagraphIndentation"]:
		keys |= {"indentFirstLine", "indentLeading"}
	if df["reportSpellingErrors"]:
		keys |= {"spellingError", "grammarError"}
	if df["reportComments"]:
		keys.add("comment")
	if df["reportRevisions"]:
		keys |= {"insertion", "deletion"}
	if df["reportHighlight"] or df["reportEmphasis"]:
		keys.add("highlighted")
	if df["reportLineSpacing"]:
		keys.add("lineSpacing")
	return keys


def anyFormattingEnabled() -> bool:
	df = conf["documentFormatting"]
	return bool(_wantedKeys()) or df["reportPage"] or df["reportLineNumber"]


def _points(val: Any) -> str:
	try:
		f = float(val)
	except (TypeError, ValueError):
		return str(val)
	return str(int(f)) if f.is_integer() else f"{f:.1f}"


def describe(fmt: dict, old: dict | None) -> list[str]:
	"""Texto de los cambios entre ``old`` y ``fmt`` (todo si ``old`` es None)."""
	out: list[str] = []

	def changed(key: str) -> bool:
		return key in fmt and (old is None or old.get(key) != fmt.get(key))

	def isNew(key: str) -> bool:
		return old is None or key not in old

	if changed("page"):
		out.append(_("página {n}").format(n=fmt["page"]))
	if changed("style") and fmt["style"]:
		out.append(_("estilo {name}").format(name=fmt["style"]))
	if changed("fontName") and fmt["fontName"]:
		out.append(str(fmt["fontName"]))
	if changed("fontSize") and fmt["fontSize"]:
		out.append(_("{n} puntos").format(n=_points(fmt["fontSize"])))
	if changed("fontWeight"):
		bold = (fmt.get("fontWeight") or 400) >= 600
		if isNew("fontWeight"):
			if bold:
				out.append(_("negrita"))
		elif bold != ((old.get("fontWeight") or 400) >= 600):
			out.append(_("negrita") if bold else _("sin negrita"))
	for key, on, off in (
		("italic", _("cursiva"), _("sin cursiva")),
		("underline", _("subrayado"), _("sin subrayado")),
		("strikethrough", _("tachado"), _("sin tachado")),
		("superscript", _("superíndice"), _("línea base")),
		("subscript", _("subíndice"), _("línea base")),
		("highlighted", _("resaltado"), _("sin resaltado")),
		("insertion", _("insertado"), _("fin de insertado")),
		("deletion", _("eliminado"), _("fin de eliminado")),
		("comment", _("con comentario"), ""),
	):
		if changed(key):
			val = bool(fmt.get(key))
			if isNew(key):
				if val:
					out.append(on)
			else:
				label = on if val else off
				if label:
					out.append(label)
	if changed("color"):
		name = colorName(fmt["color"])
		if name:
			out.append(_("color {name}").format(name=name))
	if changed("backgroundColor"):
		name = colorName(fmt["backgroundColor"])
		# El fondo blanco (el habitual) solo se dice al volver a él desde otro fondo.
		if name and (colorBaseName(fmt["backgroundColor"]) != _("blanco") or not isNew("backgroundColor")):
			out.append(_("fondo {name}").format(name=name))
	if changed("alignment"):
		label = _ALIGNMENTS.get(fmt.get("alignment"))
		if label:
			out.append(label)
	if changed("indentFirstLine") or changed("indentLeading"):
		first = fmt.get("indentFirstLine") or 0
		lead = fmt.get("indentLeading") or 0
		parts = []
		if lead:
			parts.append(_("sangría izquierda {n} puntos").format(n=_points(lead)))
		if first:
			parts.append(_("sangría de primera línea {n} puntos").format(n=_points(first)))
		out.append(" ".join(parts) if parts else _("sin sangría"))
	if changed("lineSpacing"):
		label = lineSpacingText(fmt.get("lineSpacing"))
		if label:
			out.append(_("interlineado {spacing}").format(spacing=label))
	if changed("spellingError") and fmt.get("spellingError"):
		out.append(_("error ortográfico"))
	if changed("grammarError") and fmt.get("grammarError"):
		out.append(_("error gramatical"))
	return out


def collect(info: Any, full: bool = False) -> dict:
	"""Formato en la posición de ``info`` según las opciones activas."""
	fmt: dict = {}
	getter = getattr(info, "getFormatInfo", None)
	keys = None if full else _wantedKeys()
	if getter is not None and (keys is None or keys):
		try:
			fmt.update(getter(keys) if keys is not None else getter())
		except TypeError:
			fmt.update(getter())
		except Exception:
			log.debug("No se pudo leer el formato", exc_info=True)
	df = conf["documentFormatting"]
	if full or df["reportPage"]:
		try:
			page = getattr(info, "pageNumber", None)
			if page and page > 1 or (page and full):
				fmt["page"] = page
		except Exception:
			pass
	if not full and keys is not None:
		fmt = {k: v for k, v in fmt.items() if k in keys or k == "page"}
	return fmt


def speechForMove(info: Any) -> list[str]:
	"""Cambios de formato que hay que anunciar al mover el cursor a ``info``."""
	if not anyFormattingEnabled():
		return []
	objKey = _stateKey(getattr(info, "obj", None))
	fmt = collect(info)
	old = _lastFormat.get(objKey)
	_lastFormat[objKey] = fmt
	if len(_lastFormat) > 50:
		_lastFormat.clear()
		_lastFormat[objKey] = fmt
	out = describe(fmt, old if old is not None else {})
	if conf["documentFormatting"]["reportLineNumber"]:
		try:
			n = info.lineNumber
			if n:
				out.insert(0, _("línea {n}").format(n=n))
		except Exception:
			pass
	return out


def fullDescription(info: Any) -> list[str]:
	"""Formato completo (orden Tiresias+F)."""
	fmt = collect(info, full=True)
	return describe(fmt, None)


def reset(obj: Any = None) -> None:
	if obj is None:
		_lastFormat.clear()
		_lastIndent.clear()
	else:
		_lastFormat.pop(_stateKey(obj), None)
		_lastIndent.pop(_stateKey(obj), None)


# ------------------------------------------------------------------ interlineado
_LINE_SPACING_RULES = {
	"single": _("sencillo"),
	"oneandahalf": _("1,5 líneas"),
	"double": _("doble"),
	"atleast": _("mínimo"),
	"exactly": _("exacto"),
	"multiple": _("múltiple"),
}


def lineSpacingText(value: Any) -> str:
	"""Texto del interlineado de UIA (``"LineSpacingRule: Single; LineSpacing: 1.0pt;"``)."""
	if value in (None, ""):
		return ""
	text = str(value)
	parts: dict[str, str] = {}
	for item in text.split(";"):
		if ":" in item:
			k, v = item.split(":", 1)
			parts[k.strip().lower()] = v.strip()
	if not parts:
		return text.strip()
	rule = parts.get("linespacingrule", "").replace(" ", "").lower()
	amount = parts.get("linespacing", "")
	label = _LINE_SPACING_RULES.get(rule, parts.get("linespacingrule", ""))
	if rule in ("atleast", "exactly"):
		num = amount.lower().removesuffix("pt").strip()
		return f"{label} {_points(num)} " + _("puntos") if num else label
	if rule == "multiple" and amount:
		return f"{label} {_points(amount.lower().removesuffix('pt').strip())}"
	return label or text.strip()


# ------------------------------------------------------------------ sangría de las líneas
#: Última sangría anunciada por control (clave: :func:`_stateKey`).
_lastIndent: dict[Any, str] = {}


def indentationText(line: str) -> str:
	"""«2 tabuladores 3 espacios» para el espacio inicial de ``line``."""
	ws = line[: len(line) - len(line.lstrip(" \t"))]
	if not ws:
		return ""
	tabs = ws.count("\t")
	spaces = ws.count(" ")
	parts = []
	if tabs:
		parts.append(_("{n} tabulador").format(n=tabs) if tabs == 1 else _("{n} tabuladores").format(n=tabs))
	if spaces:
		parts.append(_("{n} espacio").format(n=spaces) if spaces == 1 else _("{n} espacios").format(n=spaces))
	return " ".join(parts)


def lineIndentationSpeech(line: str, info: Any = None) -> list:
	"""Secuencia de voz (texto y pitidos) con la sangría de ``line``.

	Sigue ``documentFormatting.reportLineIndentation`` (voz, tonos o ambos) y
	solo habla cuando la sangría cambia. Con ``ignoreBlankLinesForRLI`` las
	líneas en blanco no cuentan; sin ella, una línea en blanco es «sin
	sangría» (y la siguiente con sangría vuelve a anunciarse).
	"""
	df = conf["documentFormatting"]
	mode = df["reportLineIndentation"]
	if mode == "off":
		return []
	stripped = line.rstrip("\r\n")
	key = _stateKey(getattr(info, "obj", None))
	blank = not stripped.strip()
	if blank and df["ignoreBlankLinesForRLI"]:
		return []
	indent = "" if blank else indentationText(stripped)
	seq: list = []
	if mode in ("speech", "both") and indent != _lastIndent.get(key, ""):
		seq.append(indent or _("sin sangría"))
	if mode in ("tones", "both") and not blank:
		from .speech.commands import BeepCommand

		level = len(stripped) - len(stripped.lstrip(" \t"))
		seq.append(BeepCommand(220 * 2 ** (min(level, 40) / 12.0), 40))
	_lastIndent[key] = indent
	if len(_lastIndent) > 100:
		_lastIndent.clear()
		_lastIndent[key] = indent
	return seq


# ------------------------------------------------------------------ enlaces
def isSamePageUrl(url: str, documentUrl: str) -> bool:
	"""``True`` si ``url`` apunta a un ancla del propio documento."""
	from urllib.parse import urlsplit

	if not url:
		return False
	url = url.strip()
	if url.startswith("#"):
		return len(url) > 1
	if not documentUrl:
		return False
	try:
		a = urlsplit(url)
		b = urlsplit(documentUrl.strip())
	except ValueError:
		return False
	if not a.fragment:
		return False
	return (a.scheme.lower(), a.netloc.lower(), a.path or "/", a.query) == (b.scheme.lower(), b.netloc.lower(), b.path or "/", b.query)


def linkTypeText(url: str, documentUrl: str) -> str:
	"""«en esta página» si el enlace es un ancla interna (opción reportLinkType)."""
	if not conf["documentFormatting"]["reportLinkType"]:
		return ""
	return _("en esta página") if isSamePageUrl(url, documentUrl) else ""


def linkTypeForElement(element: Any, documentElement: Any = None) -> str:
	"""Tipo de enlace de un elemento UIA (lee su destino y el del documento)."""
	if element is None or not conf["documentFormatting"]["reportLinkType"]:
		return ""
	try:
		from .a11y import uia_client as uc

		url = element.GetCurrentPropertyValue(uc.P_VALUEVALUE) or ""
		docUrl = ""
		if documentElement is not None:
			docUrl = documentElement.GetCurrentPropertyValue(uc.P_VALUEVALUE) or ""
	except Exception:
		return ""
	if not isinstance(url, str) or not isinstance(docUrl, str):
		return ""
	return linkTypeText(url, docUrl)


def linkTypeForObject(obj: Any) -> str:
	"""Tipo de enlace de un objeto accesible (busca el documento que lo contiene)."""
	if obj is None or not conf["documentFormatting"]["reportLinkType"]:
		return ""
	try:
		from .objects.roles import Role

		url = obj.value or ""
		doc = obj.parent
		for _i in range(30):
			if doc is None or doc.role == Role.DOCUMENT:
				break
			doc = doc.parent
		docUrl = (doc.value or "") if doc is not None else ""
	except Exception:
		return ""
	return linkTypeText(url, docUrl)


# ------------------------------------------------------------------ bordes de celdas
#: Propiedades UIA de los bordes (colores y grosores: arriba, abajo, izquierda, derecha).
_P_OUTLINECOLOR = 30161
_P_OUTLINETHICKNESS = 30164


def _thicknessLabel(value: float) -> str:
	if value <= 0:
		return ""
	if value < 1.5:
		return _("fino")
	if value < 2.5:
		return _("medio")
	return _("grueso")


def cellBordersText(obj: Any) -> str:
	"""Descripción de los bordes de una celda según ``reportCellBorders``.

	``styles`` dice el grosor de cada lado con borde; ``colorsAndStyles``
	añade el color. Sin bordes (o si la aplicación no los expone) no dice nada.
	"""
	mode = conf["documentFormatting"]["reportCellBorders"]
	if mode == "off" or obj is None or not hasattr(obj, "_prop"):
		return ""
	try:
		thickness = list(obj._prop(_P_OUTLINETHICKNESS, None) or [])
		colors = list(obj._prop(_P_OUTLINECOLOR, None) or []) if mode == "colorsAndStyles" else []
	except Exception:
		return ""
	return describeCellBorders(thickness, colors)


def describeCellBorders(thickness: list, colors: list) -> str:
	sides = (_("arriba"), _("abajo"), _("izquierda"), _("derecha"))
	if len(thickness) == 1:
		thickness = thickness * 4
	if len(colors) == 1:
		colors = colors * 4
	parts: list[str] = []
	for i, side in enumerate(sides):
		try:
			t = float(thickness[i]) if i < len(thickness) else 0.0
		except (TypeError, ValueError):
			t = 0.0
		label = _thicknessLabel(t)
		if not label:
			continue
		if i < len(colors):
			name = colorName(colors[i])
			if name:
				label = f"{label} {name}"
		parts.append(f"{side} {label}")
	if not parts:
		return ""
	# Con los valores RGB o hexadecimales (#8674) los lados se separan con «;».
	sep = "; " if any("," in p for p in parts) else ", "
	return _("bordes: {sides}").format(sides=sep.join(parts))


# ------------------------------------------------------------------ contenedores
def shouldReportContainer(role: Any, name: str = "") -> bool:
	"""¿Se anuncia la entrada o salida de un contenedor con ``role``?

	Lo usan el modo exploración y la presentación de objetos para respetar
	los conmutadores de formato (listas, tablas, regiones, citas, artículos,
	marcos, figuras y agrupaciones).
	"""
	from .objects.roles import Role

	df = conf["documentFormatting"]
	mapping = {
		Role.LIST: "reportLists",
		Role.TABLE: "reportTables",
		Role.DATAGRID: "reportTables",
		Role.LANDMARK: "reportLandmarks",
		Role.REGION: "reportLandmarks",
		Role.BLOCKQUOTE: "reportBlockQuotes",
		Role.ARTICLE: "reportArticles",
		Role.FRAME: "reportFrames",
		Role.FIGURE: "reportFigures",
		Role.GROUPING: "reportGroupings",
	}
	key = mapping.get(role)
	return True if key is None else bool(df[key])
