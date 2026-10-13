"""Exploración de la pantalla con el dedo: qué hay en un punto y leerlo.

Mientras la superposición táctil tapa la pantalla, ``ElementFromPoint`` de UI
Automation devolvería la propia superposición. En ese caso se busca a mano la
ventana visible que hay debajo (recorriendo las ventanas de arriba abajo y
saltando la superposición), se baja por sus ventanas hijas y, dentro de la
última, por el árbol UIA eligiendo en cada nivel el hijo más pequeño que
contiene el punto.

Todo esto se ejecuta en el hilo del núcleo.
"""

from __future__ import annotations

import ctypes
from typing import Any

from . import win32 as W

log = W.log

GW_HWNDNEXT = 2
GA_ROOT = 2
CWP_SKIPINVISIBLE = 0x0001
CWP_SKIPTRANSPARENT = 0x0004
_MAX_DEPTH = 40


def _rectOf(hwnd: int) -> tuple[int, int, int, int]:
	r = W.RECT()
	W.user32.GetWindowRect(hwnd, ctypes.byref(r))
	return r.left, r.top, r.right, r.bottom


def _contains(rect: tuple[int, int, int, int], x: int, y: int) -> bool:
	left, top, right, bottom = rect
	return left <= x < right and top <= y < bottom


def topWindowAt(x: int, y: int, exclude: set[int]) -> int:
	"""Primera ventana de nivel superior visible bajo el punto, sin ``exclude``."""
	hwnd = W.user32.GetTopWindow(None)
	guard = 0
	while hwnd and guard < 5000:
		guard += 1
		h = int(hwnd)
		if h not in exclude and W.user32.IsWindowVisible(h) and not W.user32.IsIconic(h):
			ex = int(W.user32.GetWindowLongPtrW(h, W.GWL_EXSTYLE))
			clickThrough = (ex & W.WS_EX_TRANSPARENT) and (ex & W.WS_EX_LAYERED)
			if not clickThrough and _contains(_rectOf(h), x, y) and not W.isWindowCloaked(h):
				return h
		hwnd = W.user32.GetWindow(hwnd, GW_HWNDNEXT)
	return 0


def deepestChildAt(hwnd: int, x: int, y: int) -> int:
	cur = hwnd
	for _i in range(_MAX_DEPTH):
		pt = W.POINT(x, y)
		W.user32.ScreenToClient(cur, ctypes.byref(pt))
		child = W.user32.ChildWindowFromPointEx(cur, pt, CWP_SKIPINVISIBLE | CWP_SKIPTRANSPARENT)
		if not child or int(child) == cur:
			break
		cur = int(child)
	return cur


def _descendUia(element: Any, x: int, y: int) -> Any:
	"""Baja por el árbol UIA hasta el elemento más pequeño que contiene el punto."""
	from ..a11y import uia_client as uc

	cache = uc.makeCacheRequest([uc.P_BOUNDINGRECT])
	best = element
	for _i in range(_MAX_DEPTH):
		try:
			arr = best.FindAllBuildCache(uc.TreeScope_Children, uc.trueCondition, cache)
		except Exception:
			break
		if not arr:
			break
		chosen = None
		chosenArea = None
		try:
			n = arr.Length
		except Exception:
			break
		for i in range(n):
			try:
				el = arr.GetElement(i)
				rect = el.CachedBoundingRectangle
				left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
			except Exception:
				continue
			if right <= left or bottom <= top or not (left <= x < right and top <= y < bottom):
				continue
			area = (right - left) * (bottom - top)
			if chosenArea is None or area <= chosenArea:
				chosen, chosenArea = el, area
		if chosen is None:
			break
		best = chosen
	return best


def objectAtPoint(x: int, y: int, overlayHwnd: int = 0) -> Any:
	"""Objeto accesible en el punto, sin contar la superposición táctil."""
	from ..objects.uia import UIAObject, getObjectFromPoint

	if overlayHwnd:
		under = W.user32.WindowFromPoint(W.POINT(x, y))
		root = int(W.user32.GetAncestor(under, GA_ROOT) or 0) if under else 0
		if root != overlayHwnd and int(under or 0) != overlayHwnd:
			return getObjectFromPoint(x, y)
	else:
		return getObjectFromPoint(x, y)
	from ..a11y import uia_client as uc

	top = topWindowAt(x, y, {overlayHwnd})
	if not top:
		return None
	child = deepestChildAt(top, x, y)
	element = uc.elementFromHandle(child) or uc.elementFromHandle(top)
	if element is None:
		return None
	try:
		element = _descendUia(element, x, y)
	except Exception:
		log.debug("Error bajando por el árbol UIA", exc_info=True)
	try:
		element = element.BuildUpdatedCache(uc.baseCacheRequest)
	except Exception:
		pass
	return UIAObject.fromElement(element)


class ScreenExplorer:
	"""Lee lo que hay bajo el dedo (hilo del núcleo)."""

	def __init__(self) -> None:
		self._lastObj: Any = None
		self._lastText = ""

	def reset(self) -> None:
		self._lastObj = None
		self._lastText = ""

	def moveTo(self, x: int, y: int, new: bool = False, overlayHwnd: int = 0) -> None:
		from .. import api, presentation, speech, textinfo
		from ..config import conf

		obj = objectAtPoint(x, y, overlayHwnd)
		if obj is None:
			if new:
				speech.speakMessage(_nothingMessage())
			return
		text = ""
		info = None
		unit = conf["touch"]["textUnit"]
		try:
			if obj.hasText:
				info = obj.makeTextInfo(textinfo.Point(x, y))
				info.expand(unit)
				text = info.text.strip()
		except Exception:
			info = None
			text = ""
		sameObj = self._lastObj is not None and obj == self._lastObj
		if not new and sameObj and text == self._lastText:
			return
		api.setNavigatorObject(obj)
		api.setMouseObject(obj)
		if info is not None:
			try:
				start = info.copy()
				start.collapse()
				api.setReviewPosition(start)
			except Exception:
				pass
		speech.cancelSpeech()
		if sameObj and not new:
			# Mismo objeto, otro fragmento de texto bajo el dedo.
			speech.speakText(text)
		else:
			presentation.speakObject(obj, reason=presentation.Reason.MOUSE)
			if text and text != (obj.name or "").strip():
				speech.speakText(text)
		self._lastObj = obj
		self._lastText = text


def _nothingMessage() -> str:
	from ..i18n import _

	return _("nada")
