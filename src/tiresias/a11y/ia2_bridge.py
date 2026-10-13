"""Puente de UI Automation a MSAA/IAccessible2 para datos que UIA no expone.

Tiresias lee las páginas web con UIA, pero algunos datos solo están en
IAccessible2 (comprobado con Chrome y Edge 2026, apartado 19 de
``docs/arquitectura.md``):

- ``src`` de las imágenes (nombre de archivo de las que no tienen texto
  alternativo, #7412) y ``maxlength`` de los campos de texto;
- el idioma (``IAccessible2::locale``) en Firefox, que no rellena
  ``UIA_CulturePropertyId``;
- ``abbr`` de los encabezados de tabla en Firefox (#3566; Chrome y Edge no lo
  exponen por ninguna API).

:func:`iaccessibleForElement` busca el ``IAccessible`` que corresponde a un
elemento UIA probando, de más barato a más caro: el patrón LegacyIAccessible,
el identificador del RuntimeId, el foco del documento, el punto central del
elemento y, por último, el mismo camino de hijos desde el documento (Chromium
publica los mismos hijos en los dos árboles). Cada candidato se comprueba
(rol y nombre) antes de darlo por bueno.
"""

from __future__ import annotations

import ctypes
import re
import time
import urllib.parse
from typing import Any

import comtypes
from comtypes.automation import VARIANT

from ..log import getLogger
from . import msaa
from . import uia_client as uc

log = getLogger("ia2bridge")

ROLE_SYSTEM_DOCUMENT = 15
ROLE_SYSTEM_COLUMNHEADER = 25
ROLE_SYSTEM_ROWHEADER = 26
ROLE_SYSTEM_CELL = 29
ROLE_SYSTEM_GRAPHIC = 40
ROLE_SYSTEM_TEXT = 42

#: Roles MSAA aceptables para cada tipo de control UIA (para comprobar el candidato).
_ROLES_FOR_CT = {
	uc.CT_IMAGE: {ROLE_SYSTEM_GRAPHIC},
	uc.CT_EDIT: {ROLE_SYSTEM_TEXT},
	50029: {ROLE_SYSTEM_COLUMNHEADER, ROLE_SYSTEM_ROWHEADER, ROLE_SYSTEM_CELL},  # DataItem
	50034: {ROLE_SYSTEM_COLUMNHEADER, ROLE_SYSTEM_ROWHEADER},  # HeaderItem
	50035: {ROLE_SYSTEM_COLUMNHEADER, ROLE_SYSTEM_ROWHEADER},  # Header
}

#: Marcos web en los que vale la pena buscar el objeto IA2.
WEB_FRAMEWORKS = ("Chrome", "Gecko", "MicrosoftEdge")

#: LCID que no indican un idioma real (invariante, «del usuario», «del sistema»).
_NO_LANGUAGE_LCIDS = {0, 0x7F, 0x400, 0x800, 0x1000}


# ====================================================================== locale
class _IA2Locale(ctypes.Structure):
	_fields_ = [("language", ctypes.c_void_p), ("country", ctypes.c_void_p), ("variant", ctypes.c_void_p)]


def _takeBstr(ptr: int | None) -> str:
	if not ptr:
		return ""
	try:
		return ctypes.wstring_at(ptr)
	finally:
		try:
			ctypes.windll.oleaut32.SysFreeString(ctypes.c_void_p(ptr))
		except Exception:
			pass


def getLocale(ia2) -> str | None:
	"""Idioma de un objeto IAccessible2 (``es_ES``, ``en``…) o ``None``."""
	if ia2 is None:
		return None
	loc = _IA2Locale()
	try:
		ia2._IAccessible2__com__get_locale(ctypes.byref(loc))
	except (comtypes.COMError, OSError, AttributeError, ValueError, TypeError):
		return None
	lang = _takeBstr(loc.language).strip()
	country = _takeBstr(loc.country).strip()
	_takeBstr(loc.variant)
	if not lang:
		return None
	return f"{lang}_{country}" if country else lang


def languageFromLcid(lcid: Any) -> str | None:
	"""Idioma de un LCID de UIA (``UIA_CulturePropertyId``) o ``None`` si no es real."""
	try:
		lcid = int(lcid or 0)
	except (TypeError, ValueError):
		return None
	if lcid in _NO_LANGUAGE_LCIDS:
		return None
	from ..i18n import lcidToLanguage

	return lcidToLanguage(lcid)


# ====================================================================== nombres de archivo
_EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,5}$")


def fileNameFromURL(url: str) -> str:
	"""Nombre legible del archivo de una URL (``.../foto_de_la_playa.png`` → «foto de la playa»).

	Las imágenes incrustadas (``data:``, ``blob:``) no tienen nombre de archivo.
	"""
	if not url:
		return ""
	url = url.strip()
	# Con 8 caracteres nunca coincidía «javascript» (10).
	low = url[:11].lower()
	if low.startswith(("data:", "blob:", "javascript:")):
		return ""
	try:
		path = urllib.parse.urlsplit(url).path
	except ValueError:
		path = url
	last = path.rstrip("/").rsplit("/", 1)[-1]
	last = last.rsplit("\\", 1)[-1]
	try:
		last = urllib.parse.unquote(last)
	except Exception:
		pass
	last = _EXT_RE.sub("", last) if _EXT_RE.sub("", last) else last
	last = re.sub(r"[_+]+", " ", last)
	last = " ".join(last.split())
	return last[:80]


# ====================================================================== UIA -> IAccessible
def _verify(acc, ct: int, name: str | None) -> bool:
	"""¿El objeto MSAA ``acc`` es el del elemento (rol compatible y mismo nombre)?

	``name=None``: solo se comprueba el rol.
	"""
	if acc is None:
		return False
	try:
		role = acc.accRole(0)
	except (comtypes.COMError, OSError, ValueError, TypeError):
		return False
	allowed = _ROLES_FOR_CT.get(ct)
	if allowed is not None and isinstance(role, int) and role not in allowed:
		return False
	if name is None:
		return True
	try:
		accName = acc.accName(0) or ""
	except (comtypes.COMError, OSError, ValueError, TypeError):
		accName = ""
	return " ".join(str(accName).split()) == " ".join((name or "").split())


def _legacyIAccessible(element):
	try:
		punk = element.GetCurrentPattern(uc.PAT_LEGACYIACCESSIBLE)
		if not punk:
			return None
		pat = punk.QueryInterface(uc.UIA.IUIAutomationLegacyIAccessiblePattern)
		if pat.CurrentChildId:
			return None
		acc = pat.GetIAccessible()
		return msaa.normalizeIAccessible(acc)
	except (comtypes.COMError, ValueError, AttributeError, OSError):
		return None


def hostWindow(element) -> int:
	"""Ventana que aloja un elemento (la del RuntimeId de los proveedores nativos)."""
	rid = uc.runtimeIdOf(element)
	if len(rid) >= 2 and rid[0] == 42:
		return int(rid[1])
	try:
		return int(element.CurrentNativeWindowHandle or 0)
	except (comtypes.COMError, ValueError):
		return 0


def _childFromId(hwnd: int, childId: int):
	res = msaa.accessibleObjectFromEvent(hwnd, msaa.OBJID_CLIENT, childId)
	if not res:
		return None
	pacc, cid = res
	if cid == 0:
		return pacc
	try:
		return msaa.normalizeIAccessible(pacc.accChild(cid))
	except (comtypes.COMError, OSError, ValueError, TypeError):
		return None


def _fromRuntimeId(element, hwnd: int):
	rid = uc.runtimeIdOf(element)
	if len(rid) < 3 or not hwnd:
		return []
	last = int(rid[-1])
	out = []
	for cid in (-last, last):
		if cid:
			acc = _childFromId(hwnd, cid)
			if acc is not None:
				out.append(acc)
	return out


def _fromFocus(hwnd: int):
	doc = msaa.accessibleObjectFromWindow(hwnd)
	if doc is None:
		return None
	try:
		return msaa.normalizeIAccessible(doc.accFocus)
	except (comtypes.COMError, OSError, ValueError, TypeError):
		return None


def _fromPoint(element):
	try:
		r = element.CurrentBoundingRectangle
		x, y = (r.left + r.right) // 2, (r.top + r.bottom) // 2
		if r.right <= r.left or r.bottom <= r.top:
			return None
	except (comtypes.COMError, ValueError, AttributeError):
		return None
	res = msaa.accessibleObjectFromPoint(x, y)
	if not res:
		return None
	pacc, cid = res
	if cid:
		try:
			return msaa.normalizeIAccessible(pacc.accChild(cid))
		except (comtypes.COMError, OSError, ValueError, TypeError):
			return None
	return pacc


def documentIAccessible(hwnd: int):
	"""``IAccessible`` del documento web de una ventana de contenido (o ``None``)."""
	doc = msaa.accessibleObjectFromWindow(hwnd)
	if doc is None:
		return None
	try:
		if doc.accRole(0) != ROLE_SYSTEM_DOCUMENT:
			return None
	except (comtypes.COMError, OSError, ValueError, TypeError):
		return None
	return doc


_ridRequest = None
CT_DOCUMENT = 50030


def _liveChildRids(element) -> list[tuple[tuple, int]] | None:
	"""(RuntimeId, tipo de control) de todos los hijos (vista sin filtrar) en una sola llamada."""
	global _ridRequest
	try:
		if _ridRequest is None:
			_ridRequest = uc.makeCacheRequest([uc.P_RUNTIMEID, uc.P_CONTROLTYPE], condition=uc.trueCondition)
		arr = element.FindAllBuildCache(uc.TreeScope_Children, uc.trueCondition, _ridRequest)
	except (comtypes.COMError, ValueError, AttributeError):
		return None
	out = []
	for i in range(arr.Length if arr else 0):
		el = arr.GetElement(i)
		try:
			rid = el.GetCachedPropertyValue(uc.P_RUNTIMEID)
			ct = int(el.GetCachedPropertyValue(uc.P_CONTROLTYPE) or 0)
		except (comtypes.COMError, ValueError, TypeError):
			rid, ct = None, 0
		out.append((tuple(rid) if rid else (), ct))
	return out


def livePath(element, maxDepth: int = 60, maxSiblings: int = 2000, cache: dict | None = None) -> tuple[list[int], list[int]] | None:
	"""Camino de índices (y número de hermanos) desde el documento web hasta ``element``.

	Sube por el árbol completo (vista sin filtrar, la que coincide con IA2; la
	vista de control de Chrome omite los contenedores genéricos) mientras los
	antecesores sean de la misma ventana de contenido (mismo prefijo de
	RuntimeId) y se queda con el camino desde el documento más alto (el que
	devuelve ``AccessibleObjectFromWindow``; los marcos son documentos
	intermedios). ``cache`` guarda los hijos de cada padre ya visto (útil al
	buscar muchas imágenes de una página).
	"""
	rid = uc.runtimeIdOf(element)
	if len(rid) < 3:
		return None
	prefix = tuple(rid[:2])
	path: list[int] = []
	counts: list[int] = []
	docCut: int | None = None
	cur = element
	curRid = rid
	walker = uc.rawWalker
	for _i in range(maxDepth):
		try:
			parent = walker.GetParentElement(cur)
		except (comtypes.COMError, ValueError):
			return None
		pRid = uc.runtimeIdOf(parent) if parent else ()
		if len(pRid) <= 2 or tuple(pRid[:2]) != prefix:
			try:
				if int(cur.CurrentControlType or 0) == CT_DOCUMENT:
					docCut = len(path)
			except (comtypes.COMError, ValueError, TypeError):
				pass
			break
		kids = cache.get(pRid) if cache is not None else None
		if kids is None:
			kids = _liveChildRids(parent)
			if kids is None or len(kids) > maxSiblings:
				return None
			if cache is not None:
				if len(cache) > 2000:
					cache.clear()
				cache[pRid] = kids
		idx = next((i for i, k in enumerate(kids) if k[0] == curRid), -1)
		if idx < 0:
			return None
		if kids[idx][1] == CT_DOCUMENT:
			# ``cur`` es un documento: el camino útil empieza en el más alto.
			docCut = len(path)
		path.append(idx)
		counts.append(len(kids))
		cur, curRid = parent, pRid
	else:
		return None
	if docCut is None:
		return None
	path = path[:docCut]
	counts = counts[:docCut]
	path.reverse()
	counts.reverse()
	return path, counts


_VT_DISPATCH = 9


def childAt(acc, index: int):
	"""Hijo ``index`` (objeto completo) de ``acc`` con una sola llamada a
	``AccessibleChildren`` y sin convertir el VARIANT con información de tipos
	(que en comtypes cuesta otra llamada entre procesos por hijo)."""
	var = VARIANT()
	obtained = ctypes.c_long()
	try:
		msaa.oleacc.AccessibleChildren(acc, index, 1, ctypes.byref(var), ctypes.byref(obtained))
	except (OSError, comtypes.COMError, ctypes.ArgumentError):
		return None
	if obtained.value != 1 or var.vt != _VT_DISPATCH:
		return None
	ptr = var._.c_void_p
	# El puntero pasa a ser de ``disp`` (lo libera él), no del VARIANT.
	var.vt = 0
	if not ptr:
		return None
	disp = ctypes.cast(ctypes.c_void_p(ptr), ctypes.POINTER(comtypes.IUnknown))
	try:
		return disp.QueryInterface(msaa.IAccessible)
	except (comtypes.COMError, ValueError):
		return None


class PathResolver:
	"""Desciende por IA2 siguiendo un camino de hijos, con caché de prefijos.

	La caché caduca a los pocos segundos (la página cambia) y cada uso tiene
	un presupuesto de tiempo para no retrasar la construcción del búfer.
	"""

	def __init__(self, lifetime: float = 3.0) -> None:
		self._lifetime = lifetime
		self._created = time.monotonic()
		self._cache: dict[tuple, Any] = {}
		self._docs: dict[int, Any] = {}
		#: Hijos (RuntimeId) de cada padre UIA ya visto, para :func:`livePath`.
		self.uiaChildren: dict[tuple, list] = {}
		#: Árbol completo de un documento: {RuntimeId: (RuntimeId del padre, índice, hermanos)}.
		self._rawMap: dict[tuple, tuple[tuple, int, int]] | None = None
		self._rawRoot: tuple = ()
		self.spent = 0.0

	def _fresh(self) -> None:
		if time.monotonic() - self._created > self._lifetime:
			self._cache.clear()
			self._docs.clear()
			self.uiaChildren.clear()
			self._rawMap = None
			self._created = time.monotonic()
			self.spent = 0.0

	def _buildRawMap(self, root) -> None:
		"""Pide de una vez el árbol completo (sin filtrar) con solo el RuntimeId."""
		self._rawMap = {}
		self._rawRoot = uc.runtimeIdOf(root)
		cr = uc.makeCacheRequest([uc.P_RUNTIMEID], scope=uc.TreeScope_Subtree, condition=uc.trueCondition)
		try:
			cached = root.BuildUpdatedCache(cr)
		except (comtypes.COMError, ValueError):
			return
		rawMap = self._rawMap
		stack = [(cached, self._rawRoot, 0)]
		while stack:
			el, rid, depth = stack.pop()
			if depth > 200:
				continue
			try:
				kids = el.GetCachedChildren()
				n = kids.Length if kids else 0
			except (comtypes.COMError, ValueError):
				continue
			for i in range(n):
				k = kids.GetElement(i)
				try:
					kr = k.GetCachedPropertyValue(uc.P_RUNTIMEID)
				except (comtypes.COMError, ValueError):
					kr = None
				kr = tuple(kr) if kr else ()
				if kr:
					rawMap[kr] = (rid, i, n)
					stack.append((k, kr, depth + 1))

	def rawPath(self, root, rid: tuple) -> tuple[list[int], list[int]] | None:
		"""Camino de ``rid`` desde ``root`` (el documento) en el árbol completo.

		El árbol se pide una sola vez (una llamada) y los caminos se calculan sin
		más llamadas entre procesos.
		"""
		self._fresh()
		start = time.monotonic()
		try:
			if self._rawMap is None or uc.runtimeIdOf(root) != self._rawRoot:
				self._buildRawMap(root)
			path: list[int] = []
			counts: list[int] = []
			cur = tuple(rid)
			for _i in range(300):
				if cur == self._rawRoot:
					path.reverse()
					counts.reverse()
					return path, counts
				entry = self._rawMap.get(cur)
				if entry is None:
					return None
				cur, idx, n = entry
				path.append(idx)
				counts.append(n)
			return None
		finally:
			self.spent += time.monotonic() - start

	def resolve(self, hwnd: int, path: list[int], counts: list[int] | None = None):
		self._fresh()
		start = time.monotonic()
		try:
			doc = self._docs.get(hwnd)
			if doc is None:
				doc = documentIAccessible(hwnd)
				if doc is None:
					return None
				self._docs[hwnd] = doc
			cur = doc
			for depth, idx in enumerate(path):
				key = (hwnd, tuple(path[: depth + 1]))
				nxt = self._cache.get(key)
				if nxt is None:
					if counts is not None and depth < len(counts):
						try:
							n = int(cur.accChildCount)
						except (comtypes.COMError, OSError, ValueError, TypeError):
							return None
						if counts[depth] != n:
							# Los dos árboles no coinciden en este nivel: no se arriesga.
							return None
					nxt = childAt(cur, idx)
					if nxt is None:
						return None
					self._cache[key] = nxt
				cur = nxt
			return cur
		finally:
			self.spent += time.monotonic() - start


_liveResolver = PathResolver()


#: Marcos en los que ni el patrón LegacyIAccessible ni el RuntimeId llevan al
#: objeto IA2 (comprobado en Chrome y Edge): se pasa directamente al camino.
_CHROMIUM = ("Chrome", "MicrosoftEdge")


def _cachedOrCurrent(element, propId: int, default: Any) -> Any:
	try:
		val = element.GetCachedPropertyValueEx(propId, True)
		if val is not None and not uc.isNotSupported(val):
			return val
	except (comtypes.COMError, ValueError):
		pass
	try:
		val = element.GetCurrentPropertyValue(propId)
	except (comtypes.COMError, ValueError):
		return default
	return default if val is None or uc.isNotSupported(val) else val


def iaccessibleForElement(element, path: tuple[list[int], list[int]] | None = None, resolver: PathResolver | None = None, usePoint: bool = True, frameworkId: str | None = None, live: bool = True, allowPath: bool = True):
	"""``IAccessible`` del elemento UIA ``element`` (o ``None`` si no se encuentra con seguridad).

	``path``: camino ya calculado (búfer del modo exploración); si falta, se
	calcula en vivo. ``frameworkId``: marco del elemento si ya se conoce.
	``live=False`` (búfer): sin las búsquedas por foco ni por punto.
	``allowPath=False``: sin calcular el camino en vivo (consultas frecuentes,
	como el idioma de cada objeto anunciado).
	"""
	try:
		ct = int(_cachedOrCurrent(element, uc.P_CONTROLTYPE, 0) or 0)
		name = _cachedOrCurrent(element, uc.P_NAME, "") or ""
		if frameworkId is None:
			frameworkId = element.CurrentFrameworkId or ""
	except (comtypes.COMError, ValueError, AttributeError):
		return None
	hwnd = hostWindow(element)
	if frameworkId not in _CHROMIUM:
		acc = _legacyIAccessible(element)
		if _verify(acc, ct, name):
			return acc
		for acc in _fromRuntimeId(element, hwnd):
			if _verify(acc, ct, name):
				return acc
	try:
		focused = live and bool(element.CurrentHasKeyboardFocus)
	except (comtypes.COMError, ValueError):
		focused = False
	if focused and hwnd:
		acc = _fromFocus(hwnd)
		if _verify(acc, ct, name):
			return acc
	if usePoint and live:
		acc = _fromPoint(element)
		if _verify(acc, ct, name):
			return acc
	if hwnd and (path is not None or allowPath):
		if path is None:
			res = resolver or _liveResolver
			start = time.monotonic()
			path = livePath(element, cache=res.uiaChildren)
			res.spent += time.monotonic() - start
		if path is not None:
			acc = (resolver or _liveResolver).resolve(hwnd, path[0], path[1])
			# El camino ya se comprobó nivel a nivel (mismo número de hijos): basta el rol.
			if _verify(acc, ct, None):
				return acc
	return None


def ia2Attributes(acc) -> dict[str, str]:
	"""Atributos IA2 de un ``IAccessible`` (vacío si no es IA2)."""
	ia2 = msaa.queryIAccessible2(acc)
	if ia2 is None:
		return {}
	try:
		return msaa.parseIA2Attributes(ia2.attributes)
	except (comtypes.COMError, OSError, ValueError):
		return {}


def attributesForElement(element, **kwargs) -> dict[str, str]:
	"""Atributos IA2 del objeto que corresponde a un elemento UIA web."""
	try:
		acc = iaccessibleForElement(element, **kwargs)
	except Exception:
		log.debug("No se pudo enlazar el elemento UIA con IA2", exc_info=True)
		return {}
	return ia2Attributes(acc) if acc is not None else {}


def localeForElement(element, **kwargs) -> str | None:
	"""Idioma (IA2 ``locale``) del objeto de un elemento UIA; solo con las
	búsquedas baratas, porque se pide para cada objeto que se anuncia."""
	kwargs.setdefault("usePoint", False)
	kwargs.setdefault("allowPath", False)
	try:
		acc = iaccessibleForElement(element, **kwargs)
	except Exception:
		return None
	return getLocale(msaa.queryIAccessible2(acc)) if acc is not None else None
