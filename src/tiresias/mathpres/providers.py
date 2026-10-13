"""Obtención del MathML de las aplicaciones.

- **Chromium / Edge / WebView2**: UI Automation expone la estructura de
  ``<math>`` (grupos con rol ARIA «math») pero no las etiquetas MathML. El
  MathML se obtiene por IAccessible2: Chromium publica el contenido de cada
  ``<math>`` en el atributo IA2 ``math``. El elemento IA2 se localiza en el
  árbol MSAA de la ventana del documento comparando su rectángulo con el
  del elemento UIA (búsqueda guiada por rectángulos, varias fórmulas a la
  vez para el modo exploración). El proxy IA2 viene con Windows
  (``ia2comproxy.dll``).
- **Firefox**: ``ISimpleDOMNode.innerHTML`` del elemento ``math`` (requiere
  el proxy ``AccessibleMarshal.dll`` que instala Firefox).
- **MathJax y similares**: atributo ``data-mathml`` (por ISimpleDOMNode),
  texto alternativo en LaTeX (Wikipedia: ``{\\displaystyle ...}``) o etiqueta
  ARIA.
- **Word**: propiedad UIA personalizada «Word.MathML»; si no está, el modelo
  de objetos de Word (``OMaths``) y la conversión propia OMML → MathML.
- **MathType** (opcional): biblioteca de MathType si está instalada (64 bits).
- **Portapapeles**: formatos «MathML», «MathML Presentation» y texto (MathML,
  LaTeX o texto lineal).
"""

from __future__ import annotations

import ctypes
import re
import time
from ctypes import POINTER, byref, c_long, c_short, c_ushort, c_void_p, c_wchar_p
from typing import Any

import comtypes
from comtypes import BSTR, COMMETHOD, GUID, HRESULT, IUnknown

from ..log import getLogger

log = getLogger("mathpres.providers")

# ====================================================================== COM
_oleacc = None


def _oleaccModule():
	global _oleacc
	if _oleacc is None:
		import comtypes.client

		_oleacc = comtypes.client.GetModule("oleacc.dll")
	return _oleacc


def _IAccessible():
	return _oleaccModule().IAccessible


class IServiceProvider(IUnknown):
	_iid_ = GUID("{6D5140C1-7436-11CE-8034-00AA006009FA}")
	_methods_ = [
		COMMETHOD([], HRESULT, "QueryService", (["in"], POINTER(GUID), "guidService"), (["in"], POINTER(GUID), "riid"), (["out"], POINTER(c_void_p), "ppvObject")),
	]


_IA2 = None


def _IAccessible2():
	"""Interfaz IAccessible2 (solo se usan las propiedades necesarias)."""
	global _IA2
	if _IA2 is not None:
		return _IA2
	IAccessible = _IAccessible()

	class IAccessible2(IAccessible):
		_iid_ = GUID("{E89F726E-C4F4-4c19-BB19-B647D7FA8478}")
		_methods_ = [
			COMMETHOD(["propget"], HRESULT, "nRelations", (["out", "retval"], POINTER(c_long))),
			COMMETHOD(["propget"], HRESULT, "relation", (["in"], c_long), (["out", "retval"], POINTER(c_void_p))),
			COMMETHOD(["propget"], HRESULT, "relations", (["in"], c_long), (["in"], c_void_p), (["out", "retval"], POINTER(c_long))),
			COMMETHOD([], HRESULT, "role", (["out", "retval"], POINTER(c_long))),
			COMMETHOD([], HRESULT, "scrollTo", (["in"], c_long)),
			COMMETHOD([], HRESULT, "scrollToPoint", (["in"], c_long), (["in"], c_long), (["in"], c_long)),
			COMMETHOD(["propget"], HRESULT, "groupPosition", (["in"], c_void_p), (["in"], c_void_p), (["out", "retval"], POINTER(c_long))),
			COMMETHOD(["propget"], HRESULT, "states", (["out", "retval"], POINTER(c_long))),
			COMMETHOD(["propget"], HRESULT, "extendedRole", (["out", "retval"], POINTER(BSTR))),
			COMMETHOD(["propget"], HRESULT, "localizedExtendedRole", (["out", "retval"], POINTER(BSTR))),
			COMMETHOD(["propget"], HRESULT, "nExtendedStates", (["out", "retval"], POINTER(c_long))),
			COMMETHOD(["propget"], HRESULT, "extendedStates", (["in"], c_long), (["in"], c_void_p), (["out", "retval"], POINTER(c_long))),
			COMMETHOD(["propget"], HRESULT, "localizedExtendedStates", (["in"], c_long), (["in"], c_void_p), (["out", "retval"], POINTER(c_long))),
			COMMETHOD(["propget"], HRESULT, "uniqueID", (["out", "retval"], POINTER(c_long))),
			COMMETHOD(["propget"], HRESULT, "windowHandle", (["out", "retval"], POINTER(c_void_p))),
			COMMETHOD(["propget"], HRESULT, "indexInParent", (["out", "retval"], POINTER(c_long))),
			COMMETHOD(["propget"], HRESULT, "locale", (["out", "retval"], POINTER(c_void_p * 3))),
			COMMETHOD(["propget"], HRESULT, "attributes", (["out", "retval"], POINTER(BSTR))),
		]

	_IA2 = IAccessible2
	return _IA2


class ISimpleDOMNode(IUnknown):
	_iid_ = GUID("{1814ceeb-49e2-407f-af99-fa755a7d2607}")
	_methods_ = [
		COMMETHOD(["propget"], HRESULT, "nodeInfo", (["out"], POINTER(BSTR)), (["out"], POINTER(c_short)), (["out"], POINTER(BSTR)), (["out"], POINTER(ctypes.c_uint)), (["out"], POINTER(ctypes.c_uint)), (["out", "retval"], POINTER(c_ushort))),
		COMMETHOD(["propget"], HRESULT, "attributes", (["in"], c_ushort), (["in"], c_void_p), (["in"], c_void_p), (["in"], c_void_p), (["out", "retval"], POINTER(c_ushort))),
		COMMETHOD(["propget"], HRESULT, "attributesForNames", (["in"], c_ushort), (["in"], POINTER(BSTR)), (["in"], POINTER(c_short)), (["in"], POINTER(BSTR))),
		COMMETHOD(["propget"], HRESULT, "computedStyle", (["in"], c_ushort), (["in"], ctypes.c_bool), (["in"], c_void_p), (["in"], c_void_p), (["out", "retval"], POINTER(c_ushort))),
		COMMETHOD(["propget"], HRESULT, "computedStyleForProperties", (["in"], c_ushort), (["in"], ctypes.c_bool), (["in"], c_void_p), (["in"], c_void_p)),
		COMMETHOD([], HRESULT, "scrollTo", (["in"], ctypes.c_bool)),
		COMMETHOD(["propget"], HRESULT, "parentNode", (["out", "retval"], POINTER(c_void_p))),
		COMMETHOD(["propget"], HRESULT, "firstChild", (["out", "retval"], POINTER(c_void_p))),
		COMMETHOD(["propget"], HRESULT, "lastChild", (["out", "retval"], POINTER(c_void_p))),
		COMMETHOD(["propget"], HRESULT, "previousSibling", (["out", "retval"], POINTER(c_void_p))),
		COMMETHOD(["propget"], HRESULT, "nextSibling", (["out", "retval"], POINTER(c_void_p))),
		COMMETHOD(["propget"], HRESULT, "childAt", (["in"], ctypes.c_uint), (["out", "retval"], POINTER(c_void_p))),
		COMMETHOD(["propget"], HRESULT, "innerHTML", (["out", "retval"], POINTER(BSTR))),
		COMMETHOD(["propget"], HRESULT, "localInterface", (["out", "retval"], POINTER(c_void_p))),
		COMMETHOD(["propget"], HRESULT, "language", (["out", "retval"], POINTER(BSTR))),
	]


OBJID_CLIENT = -4
ROLE_SYSTEM_EQUATION = 0x37


def _variant(i: int):
	from comtypes.automation import VARIANT

	return VARIANT(i)


def accessibleObjectFromWindow(hwnd: int):
	# Con tiempo máximo y sin esperar a ventanas que no responden (ver ``msaa``).
	from ..a11y import msaa

	return msaa.accessibleObjectFromWindow(hwnd, msaa.OBJID_CLIENT)


def accChildren(acc) -> list:
	from comtypes.automation import VARIANT

	IAccessible = _IAccessible()
	try:
		n = acc.accChildCount
	except comtypes.COMError:
		return []
	if not n:
		return []
	arr = (VARIANT * n)()
	got = c_long()
	try:
		ctypes.oledll.oleacc.AccessibleChildren(acc, 0, n, arr, byref(got))
	except OSError:
		return []
	out = []
	for i in range(got.value):
		v = arr[i].value
		if hasattr(v, "QueryInterface"):
			try:
				out.append(v.QueryInterface(IAccessible))
			except comtypes.COMError:
				pass
	return out


def accLocation(acc) -> tuple[int, int, int, int] | None:
	try:
		loc = acc.accLocation(_variant(0))
		return tuple(int(v) for v in loc)  # type: ignore[return-value]
	except (comtypes.COMError, ValueError, TypeError):
		return None


def ia2Of(acc):
	IAccessible = _IAccessible()
	IAccessible2 = _IAccessible2()
	try:
		sp = acc.QueryInterface(IServiceProvider)
		p = sp.QueryService(byref(IAccessible._iid_), byref(IAccessible2._iid_))
		return ctypes.cast(p, POINTER(IAccessible2)) if p else None
	except (comtypes.COMError, OSError):
		try:
			return acc.QueryInterface(IAccessible2)
		except comtypes.COMError:
			return None


def parseIA2Attributes(text: str) -> dict[str, str]:
	"""``tag:math;math:<mi>x</mi>\\=...`` -> dict (con los escapes de IA2)."""
	out: dict[str, str] = {}
	key: list[str] = []
	val: list[str] = []
	cur = key
	i = 0
	while i < len(text):
		ch = text[i]
		if ch == "\\" and i + 1 < len(text):
			cur.append(text[i + 1])
			i += 2
			continue
		if ch == ":" and cur is key:
			cur = val
		elif ch == ";":
			if key:
				out["".join(key)] = "".join(val)
			key, val = [], []
			cur = key
		else:
			cur.append(ch)
		i += 1
	if key:
		out["".join(key)] = "".join(val)
	return out


def ia2Attributes(acc) -> dict[str, str]:
	ia2 = ia2Of(acc)
	if ia2 is None:
		return {}
	try:
		return parseIA2Attributes(ia2.attributes or "")
	except comtypes.COMError:
		return {}


def simpleDomInnerHtml(acc) -> str | None:
	try:
		node = acc.QueryInterface(ISimpleDOMNode)
		return node.innerHTML
	except (comtypes.COMError, AttributeError):
		return None


def simpleDomAttribute(acc, name: str) -> str | None:
	try:
		node = acc.QueryInterface(ISimpleDOMNode)
	except comtypes.COMError:
		return None
	names = (BSTR * 1)(name)
	ns = (c_short * 1)(0)
	vals = (BSTR * 1)()
	try:
		node._ISimpleDOMNode__com__get_attributesForNames(1, names, ns, vals)
		return vals[0] or None
	except (comtypes.COMError, AttributeError, OSError):
		return None


_RE_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _mathMlFromIA2(acc, attrs: dict[str, str], lang: str = "") -> str | None:
	"""MathML de un nodo IA2 con ``tag:math`` (Chromium o Firefox)."""
	m = attrs.get("math")
	langAttr = f' xml:lang="{lang}"' if lang else ""
	if m:
		m = _RE_COMMENT.sub("", m)
		return f"<math{langAttr}>{m}</math>"
	data = simpleDomAttribute(acc, "data-mathml")
	if data:
		return data
	inner = simpleDomInnerHtml(acc)
	if inner:
		return f"<math{langAttr}>{inner}</math>"
	return None


# ====================================================================== búsqueda IA2
def _contains(outer: tuple[int, int, int, int], inner: tuple[float, float, float, float], tol: int = 3) -> bool:
	ox, oy, ow, oh = outer
	ix, iy, iw, ih = inner
	return ix >= ox - tol and iy >= oy - tol and ix + iw <= ox + ow + tol and iy + ih <= oy + oh + tol


def _sameRect(a: tuple, b: tuple, tol: int = 3) -> bool:
	return all(abs(float(x) - float(y)) <= tol for x, y in zip(a, b, strict=False))


def findMathInWindow(hwnd: int, targets: list[tuple[Any, tuple[float, float, float, float] | None]], timeout: float = 4.0) -> dict[Any, str]:
	"""Busca en el árbol IA2 de ``hwnd`` los nodos ``math`` de los rectángulos dados.

	``targets`` es una lista de (clave, rectángulo UIA). Devuelve {clave: MathML}.
	Los objetivos sin rectángulo se asignan por orden de aparición.
	"""
	result: dict[Any, str] = {}
	root = accessibleObjectFromWindow(hwnd)
	if root is None:
		return result
	withRect = [(k, r) for k, r in targets if r and r[2] > 0 and r[3] > 0]
	noRect = [k for k, r in targets if not (r and r[2] > 0 and r[3] > 0)]
	remaining = list(withRect)
	foundInOrder: list[tuple[tuple, str]] = []
	deadline = time.monotonic() + timeout
	fullWalk = bool(noRect)
	stack = [root]
	visited = 0
	while stack and time.monotonic() < deadline and (remaining or (fullWalk and len(foundInOrder) < len(targets) * 2)):
		acc = stack.pop()
		visited += 1
		loc = accLocation(acc)
		if not fullWalk and loc is not None and not any(_contains(loc, r) for _k, r in remaining):
			continue
		role = None
		try:
			role = acc.accRole(_variant(0))
		except comtypes.COMError:
			pass
		isEquation = role == ROLE_SYSTEM_EQUATION
		match = next((t for t in remaining if loc is not None and _sameRect(loc, t[1])), None)
		if isEquation or match is not None or fullWalk:
			attrs = ia2Attributes(acc) if (isEquation or match is not None or role in (None, ROLE_SYSTEM_EQUATION)) else {}
			mathMl = None
			if attrs.get("tag") == "math":
				mathMl = _mathMlFromIA2(acc, attrs)
			elif match is not None:
				# Imagen o elemento con role="math" y el MathML en data-mathml.
				mathMl = simpleDomAttribute(acc, "data-mathml")
			if mathMl:
				if match is not None:
					result[match[0]] = mathMl
					remaining.remove(match)
				foundInOrder.append((loc or (0, 0, 0, 0), mathMl))
				continue
		kids = accChildren(acc)
		stack.extend(reversed(kids))
	if noRect and foundInOrder:
		used = set(result.values())
		free = [m for _loc, m in foundInOrder if m not in used]
		for k, m in zip(noRect, free, strict=False):
			result[k] = m
	log.debug("IA2: %d nodos visitados, %d fórmulas encontradas de %d", visited, len(result), len(targets))
	return result


# ====================================================================== UIA
def _uia():
	from ..a11y import uia_client as uc

	return uc


def windowForElement(el) -> int:
	uc = _uia()
	walker = uc.rawWalker
	e = el
	guard = 0
	while e and guard < 80:
		try:
			h = e.CurrentNativeWindowHandle
		except comtypes.COMError:
			h = 0
		if h:
			return int(h)
		try:
			e = walker.GetParentElement(e)
		except comtypes.COMError:
			break
		guard += 1
	return 0


def elementRect(el, cached: bool = False) -> tuple[float, float, float, float] | None:
	uc = _uia()
	try:
		val = el.GetCachedPropertyValueEx(uc.P_BOUNDINGRECT, True) if cached else el.GetCurrentPropertyValue(uc.P_BOUNDINGRECT)
	except comtypes.COMError:
		return None
	if not val or uc.isNotSupported(val) or len(val) < 4:
		return None
	return tuple(float(v) for v in val[:4])  # type: ignore[return-value]


def _currentProp(el, prop: int, default: Any = None) -> Any:
	uc = _uia()
	try:
		v = el.GetCurrentPropertyValue(prop)
	except comtypes.COMError:
		return default
	if v is None or uc.isNotSupported(v):
		return default
	return v


def isMathElement(el) -> bool:
	uc = _uia()
	return (_currentProp(el, uc.P_ARIAROLE, "") or "").lower() == "math"


def topMathElement(el):
	"""El elemento ``math`` exterior que contiene a ``el`` (o el propio ``el``)."""
	uc = _uia()
	walker = uc.rawWalker
	best = el if isMathElement(el) else None
	e = el
	guard = 0
	while e and guard < 40:
		try:
			p = walker.GetParentElement(e)
		except comtypes.COMError:
			break
		if not p or not isMathElement(p):
			break
		best = p
		e = p
		guard += 1
	return best


#: Caché de MathML por (ventana, RuntimeId).
_cache: dict[tuple, str] = {}


def _cacheKey(hwnd: int, el) -> tuple | None:
	uc = _uia()
	rid = uc.runtimeIdOf(el)
	return (hwnd, rid) if rid else None


def cacheGet(key: tuple | None) -> str | None:
	return _cache.get(key) if key else None


def cachePut(key: tuple | None, mathMl: str) -> None:
	if not key:
		return
	if len(_cache) > 2000:
		_cache.clear()
	_cache[key] = mathMl


_RE_TEX_ALT = re.compile(r"^\s*\{?\\(?:displaystyle|textstyle)")


def mathMlFromText(text: str) -> str | None:
	"""MathML a partir de un texto alternativo (LaTeX de Wikipedia, MathML...)."""
	from . import latex, mathml

	t = (text or "").strip()
	if not t:
		return None
	if mathml.looksLikeMathML(t):
		return t
	if _RE_TEX_ALT.match(t) or (latex.looksLikeLatex(t) and "\\" in t):
		try:
			return latex.latexToMathML(t)
		except Exception:
			log.debug("LaTeX no válido: %r", t, exc_info=True)
	return None


def mathMlForUIAElement(el, cachedRect: tuple | None = None) -> str | None:
	"""MathML del elemento UIA de una fórmula (o de un elemento dentro de ella)."""
	uc = _uia()
	top = topMathElement(el) or el
	hwnd = windowForElement(top)
	key = _cacheKey(hwnd, top)
	cached = cacheGet(key)
	if cached:
		return cached
	name = (_currentProp(top, uc.P_NAME, "") or "").strip()
	fromName = mathMlFromText(name)
	if fromName:
		cachePut(key, fromName)
		return fromName
	rect = cachedRect or elementRect(top)
	mathMl = None
	if hwnd:
		res = findMathInWindow(hwnd, [("x", rect)])
		mathMl = res.get("x")
	if not mathMl:
		mathMl = _mathMlFromLegacy(top)
	if mathMl:
		cachePut(key, mathMl)
	return mathMl


def _mathMlFromLegacy(el) -> str | None:
	"""Firefox (proxy MSAA): IAccessible del patrón LegacyIAccessible."""
	uc = _uia()
	try:
		pat = el.GetCurrentPattern(uc.PAT_LEGACYIACCESSIBLE)
		if not pat:
			return None
		pat = pat.QueryInterface(uc.UIA.IUIAutomationLegacyIAccessiblePattern)
		acc = pat.GetIAccessible()
	except (comtypes.COMError, AttributeError):
		return None
	if not acc:
		return None
	try:
		acc = acc.QueryInterface(_IAccessible())
	except comtypes.COMError:
		return None
	attrs = ia2Attributes(acc)
	if attrs.get("tag") == "math" or simpleDomInnerHtml(acc):
		return _mathMlFromIA2(acc, attrs)
	return None


def prefetchForDocument(hwnd: int, targets: list[tuple[Any, tuple | None]], timeout: float = 4.0) -> dict[Any, str]:
	"""Varias fórmulas de un documento a la vez (modo exploración)."""
	if not hwnd or not targets:
		return {}
	try:
		return findMathInWindow(hwnd, targets, timeout)
	except Exception:
		log.debug("Error buscando fórmulas por IA2", exc_info=True)
		return {}


# ====================================================================== Word
_WORD_MATHML_GUID = GUID("{FA170AB3-3229-4E7C-827F-DD05EE0481D9}")
_wordMathMlPropId: int | None = None


class UIAutomationPropertyInfo(ctypes.Structure):
	_fields_ = [("guid", GUID), ("pProgrammaticName", c_wchar_p), ("type", ctypes.c_int)]


class IUIAutomationRegistrar(IUnknown):
	_iid_ = GUID("{8609C4EC-4A1A-4D88-A357-5A66E060E1CF}")
	_methods_ = [
		COMMETHOD([], HRESULT, "RegisterProperty", (["in"], POINTER(UIAutomationPropertyInfo), "property"), (["out"], POINTER(ctypes.c_int), "propertyId")),
		COMMETHOD([], HRESULT, "RegisterEvent", (["in"], c_void_p), (["out"], POINTER(ctypes.c_int))),
		COMMETHOD([], HRESULT, "RegisterPattern", (["in"], c_void_p), (["out"], POINTER(ctypes.c_int)), (["out"], POINTER(ctypes.c_int)), (["in"], ctypes.c_uint), (["out"], c_void_p), (["out"], POINTER(ctypes.c_int))),
	]


def wordMathMlPropertyId() -> int:
	"""Registra (o recupera) la propiedad UIA personalizada «Word.MathML»."""
	global _wordMathMlPropId
	if _wordMathMlPropId is not None:
		return _wordMathMlPropId
	_wordMathMlPropId = 0
	try:
		import comtypes.client

		reg = comtypes.client.CreateObject(GUID("{6E29FABF-9977-42D1-8D0E-CA7E61AD87E6}"), interface=IUIAutomationRegistrar)
		info = UIAutomationPropertyInfo(_WORD_MATHML_GUID, "Word.MathML", 3)
		_wordMathMlPropId = int(reg.RegisterProperty(byref(info)))
	except Exception:
		log.debug("No se pudo registrar la propiedad Word.MathML", exc_info=True)
	return _wordMathMlPropId


def wordMathMlFromElement(el) -> str | None:
	pid = wordMathMlPropertyId()
	if not pid:
		return None
	e = el
	uc = _uia()
	for _i in range(6):
		v = _currentProp(e, pid, None)
		if v:
			return str(v)
		try:
			e = uc.rawWalker.GetParentElement(e)
		except comtypes.COMError:
			break
		if not e:
			break
	return None


def wordMathMlAtCaret(obj) -> str | None:
	"""Ecuación de Word en el cursor (UIA o modelo de objetos)."""
	el = getattr(obj, "element", None)
	if el is not None:
		try:
			pat = obj.textPattern
			if pat is not None:
				sel = pat.GetSelection()
				if sel and sel.Length:
					rng = sel.GetElement(0)
					enc = rng.GetEnclosingElement()
					m = wordMathMlFromElement(enc)
					if m:
						return m
					children = rng.GetChildren()
					for i in range(children.Length if children else 0):
						m = wordMathMlFromElement(children.GetElement(i))
						if m:
							return m
		except Exception:
			log.debug("Word: sin MathML por UIA", exc_info=True)
	hwnd = 0
	try:
		hwnd = int(obj.windowHandle or 0)
	except Exception:
		pass
	return wordMathMlFromObjectModel(hwnd)


OBJID_NATIVEOM = -16


def wordWindowFromHwnd(hwnd: int):
	"""Objeto «Window» de Word de la ventana ``_WwG`` (la del documento con el foco)."""
	from comtypes.automation import IDispatch
	from comtypes.client.dynamic import Dispatch

	p = POINTER(IDispatch)()
	try:
		ctypes.oledll.oleacc.AccessibleObjectFromWindow(hwnd, c_long(OBJID_NATIVEOM), byref(IDispatch._iid_), byref(p))
	except OSError:
		return None
	return Dispatch(p) if p else None


def wordMathMlFromObjectModel(hwnd: int = 0) -> str | None:
	"""Modelo de objetos de Word: OMaths de la selección o del párrafo actual.

	Se usa la ventana del documento (``OBJID_NATIVEOM``), así se trabaja con
	la instancia de Word que tiene el foco y no con otra.
	"""
	win = wordWindowFromHwnd(hwnd) if hwnd else None
	if win is None:
		return None
	try:
		sel = win.Selection
		maths = sel.OMaths
		target = None
		if maths.Count:
			target = maths.Item(1)
		else:
			para = sel.Range.Paragraphs.Item(1).Range
			if para.OMaths.Count:
				target = para.OMaths.Item(1)
		if target is not None:
			xml = target.Range.WordOpenXML
			from . import omml

			res = omml.ommlToMathML(xml)
			if res:
				return res[0]
		mt = _mathTypeFromSelection(sel)
		if mt:
			return mt
	except Exception:
		log.debug("Word: error en el modelo de objetos", exc_info=True)
	return None


def _mathTypeFromSelection(sel) -> str | None:
	"""Ecuación MathType (objeto OLE) en la selección, si MathType está instalado."""
	try:
		shapes = sel.InlineShapes
		for i in range(1, shapes.Count + 1):
			shape = shapes.Item(i)
			ole = shape.OLEFormat
			if ole is not None and str(ole.ProgID).startswith("Equation.DSMT"):
				return mathTypeMathMl(ole)
	except Exception:
		return None
	return None


def mathTypeMathMl(oleFormat) -> str | None:
	"""MathML de un objeto MathType (biblioteca de 64 bits de MathType 7)."""
	import winreg

	path = None
	for keyName in (r"SOFTWARE\Design Science\DSMT7\Directories", r"SOFTWARE\Design Science\DSMT6\Directories"):
		for valueName in ("AppSystemDir64", "AppSystemDir"):
			try:
				with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, keyName) as key:
					base = winreg.QueryValueEx(key, valueName)[0]
					import os

					for dll in ("MT6.dll", "MT7.dll"):
						cand = os.path.join(base, dll)
						if os.path.isfile(cand):
							path = cand
							break
			except OSError:
				continue
			if path:
				break
		if path:
			break
	if not path:
		return None
	try:
		lib = ctypes.WinDLL(path)
		oleFormat.DoVerb(2)
		mt = oleFormat.Object._comobj
		length = c_long()
		if lib.MTGetLangStrFromEqn(mt, 2, None, byref(length)) != 0:
			return None
		buf = (ctypes.c_char * length.value)()
		if lib.MTGetLangStrFromEqn(mt, 2, byref(buf), byref(length)) != 0:
			return None
		lib.MTCloseOleObject(1, mt)
		from .mathml import stripExtraneousXml

		return stripExtraneousXml(buf.value.decode("utf-8", "replace"))
	except Exception:
		log.debug("MathType no disponible", exc_info=True)
		return None


# ====================================================================== portapapeles
_CLIPBOARD_FORMATS = ("MathML Presentation", "MathML", "application/mathml-presentation+xml", "application/mathml+xml", "MathML-Content")


def _clipboardRaw() -> str | None:
	user32 = ctypes.windll.user32
	kernel32 = ctypes.windll.kernel32
	user32.GetClipboardData.restype = c_void_p
	kernel32.GlobalLock.restype = c_void_p
	kernel32.GlobalLock.argtypes = [c_void_p]
	kernel32.GlobalUnlock.argtypes = [c_void_p]
	kernel32.GlobalSize.restype = ctypes.c_size_t
	kernel32.GlobalSize.argtypes = [c_void_p]
	for name in _CLIPBOARD_FORMATS:
		fmt = user32.RegisterClipboardFormatW(name)
		if not fmt or not user32.IsClipboardFormatAvailable(fmt):
			continue
		if not user32.OpenClipboard(0):
			return None
		try:
			h = user32.GetClipboardData(fmt)
			if not h:
				continue
			p = kernel32.GlobalLock(h)
			if not p:
				continue
			try:
				size = kernel32.GlobalSize(h)
				data = ctypes.string_at(p, size)
			finally:
				kernel32.GlobalUnlock(h)
		finally:
			user32.CloseClipboard()
		if data.startswith(b"\xff\xfe") or (len(data) > 1 and data[1:2] == b"\x00"):
			text = data.decode("utf-16-le", "replace")
		else:
			text = data.decode("utf-8", "replace")
		text = text.rstrip("\x00").strip()
		if text:
			return text
	return None


def mathMlFromClipboard() -> tuple[str | None, str]:
	"""(MathML, origen) del portapapeles. Origen: mathml, latex, texto o ''."""
	from .. import api
	from . import mathml

	raw = None
	try:
		raw = _clipboardRaw()
	except Exception:
		log.debug("Error leyendo formatos MathML del portapapeles", exc_info=True)
	if raw and mathml.looksLikeMathML(raw):
		return raw, "mathml"
	text = (api.getClipData() or "").strip()
	return mathMlFromAnyText(text)


def mathMlFromAnyText(text: str) -> tuple[str | None, str]:
	from . import latex, mathml

	text = (text or "").strip()
	if not text:
		return None, ""
	if mathml.looksLikeMathML(text):
		return text, "mathml"
	if "<m:oMath" in text or "<m:oMathPara" in text:
		from . import omml

		res = omml.ommlToMathML(text)
		if res:
			return res[0], "omml"
	if latex.looksLikeLatex(text):
		try:
			return latex.latexToMathML(text), "latex"
		except Exception:
			log.debug("LaTeX no válido", exc_info=True)
	if len(text) <= 500 and re.search(r"[=+\-−×÷^²³√∑∫≤≥≠<>/]|\d", text):
		try:
			return latex.linearTextToMathML(text), "texto"
		except Exception:
			pass
	return None, ""


# ====================================================================== objetos
def mathMlForObject(obj) -> str | None:
	"""MathML del objeto (fórmula de un navegador, Word...)."""
	if obj is None:
		return None
	cached = obj.__dict__.get("_mathMlCache") if hasattr(obj, "__dict__") else None
	if cached:
		return cached
	el = getattr(obj, "element", None)
	mathMl = None
	if el is not None:
		try:
			if isMathElement(el) or topMathElement(el) is not None:
				mathMl = mathMlForUIAElement(el)
		except Exception:
			log.debug("Sin MathML para el objeto", exc_info=True)
		if not mathMl:
			mathMl = wordMathMlFromElement(el) if _isWord(obj) else None
	if mathMl and hasattr(obj, "__dict__"):
		obj.__dict__["_mathMlCache"] = mathMl
	return mathMl


def _isWord(obj) -> bool:
	try:
		app = obj.appModule
		return bool(app) and app.appName.lower() in ("winword", "outlook")
	except Exception:
		return False


def mathMlForFocus(obj) -> str | None:
	"""Fórmula en el foco: objeto matemático o ecuación de Word en el cursor."""
	m = mathMlForObject(obj)
	if m:
		return m
	if _isWord(obj):
		return wordMathMlAtCaret(obj)
	return None
