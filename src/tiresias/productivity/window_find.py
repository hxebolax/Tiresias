"""Buscar texto en cualquier ventana (no solo en documentos), como la búsqueda en pantalla de TalkBack.

Recorre con una sola petición de UI Automation (``FindAllBuildCache``) los
elementos de la ventana en primer plano, busca el texto en su nombre, su
valor y su texto de ayuda, y lleva el objeto navegador (y, si se puede y
está activado, el foco) al resultado. «Siguiente» y «anterior» continúan
desde el objeto navegador.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..log import getLogger

log = getLogger("productivity")

#: Máximo de elementos que se examinan (ventanas enormes).
MAX_ELEMENTS = 20000


@dataclass
class Candidate:
	element: object
	text: str
	runtimeId: tuple
	offscreen: bool = False


def matches(text: str, query: str, caseSensitive: bool = False) -> bool:
	if not query:
		return False
	if caseSensitive:
		return query in text
	return _fold(query) in _fold(text)


def _fold(s: str) -> str:
	"""Minúsculas sin tildes (para que «menu» encuentre «Menú»)."""
	import unicodedata

	s = unicodedata.normalize("NFD", s.casefold())
	return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")


def pickNext(candidates: list, currentIndex: int, query: str, direction: int, caseSensitive: bool = False, wrap: bool = True) -> tuple[int, bool]:
	"""Índice de la siguiente coincidencia y si se ha dado la vuelta.

	``currentIndex`` es la posición del objeto actual en ``candidates`` (-1 si
	no está). Devuelve ``(-1, False)`` si no hay ninguna coincidencia.
	"""
	n = len(candidates)
	if n == 0:
		return -1, False
	if not 0 <= currentIndex < n:
		currentIndex = -1 if direction > 0 else n
	if direction > 0:
		first = list(range(currentIndex + 1, n))
		second = list(range(0, min(currentIndex + 1, n)))
	else:
		first = list(range(currentIndex - 1, -1, -1))
		second = list(range(n - 1, max(currentIndex - 1, -1), -1))
	for i in first:
		if matches(candidates[i].text, query, caseSensitive):
			return i, False
	if wrap:
		for i in second:
			if matches(candidates[i].text, query, caseSensitive):
				return i, True
	return -1, False


def collect(rootElement, includeOffscreen: bool = True) -> list[Candidate]:
	"""Elementos de la vista de control bajo ``rootElement`` con su texto."""
	from ..a11y import uia_client as uc

	props = (uc.P_NAME, uc.P_VALUEVALUE, uc.P_HELPTEXT, uc.P_ISOFFSCREEN, uc.P_RUNTIMEID, uc.P_CONTROLTYPE, uc.P_BOUNDINGRECT)
	cr = uc.makeCacheRequest(props)
	try:
		cond = uc.client.ControlViewCondition
		arr = rootElement.FindAllBuildCache(uc.TreeScope_Descendants, cond, cr)
	except Exception:
		log.debug("No se pudo recorrer la ventana", exc_info=True)
		return []
	out: list[Candidate] = []
	try:
		count = min(arr.Length, MAX_ELEMENTS) if arr else 0
	except Exception:
		count = 0
	for i in range(count):
		try:
			el = arr.GetElement(i)
		except Exception:
			continue
		texts = []
		offscreen = False
		for pid in (uc.P_NAME, uc.P_VALUEVALUE, uc.P_HELPTEXT):
			try:
				v = el.GetCachedPropertyValue(pid)
			except Exception:
				v = None
			if isinstance(v, str) and v and v not in texts:
				texts.append(v)
		try:
			offscreen = bool(el.GetCachedPropertyValue(uc.P_ISOFFSCREEN))
		except Exception:
			offscreen = False
		if offscreen and not includeOffscreen:
			continue
		if not texts:
			continue
		out.append(Candidate(el, " ".join(texts), uc.runtimeIdOf(el), offscreen))
	return out


def _isAlive(obj) -> bool:
	"""Vale para objetos UIA y también MSAA o Java (ver :func:`.watch.isAlive`)."""
	from .watch import isAlive

	return isAlive(obj)


def rootElementOf(obj):
	"""Elemento UIA desde el que buscar: el del objeto o, si no es UIA (una
	ventana MSAA, por ejemplo), el de su ventana."""
	if obj is None:
		return None
	root = getattr(obj, "element", None)
	if root is not None:
		return root
	try:
		hwnd = int(getattr(obj, "windowHandle", 0) or 0)
	except Exception:
		hwnd = 0
	if not hwnd:
		return None
	from ..a11y import uia_client as uc

	try:
		return uc.elementFromHandle(hwnd)
	except Exception:
		log.debug("No se pudo obtener el elemento UIA de la ventana %#x", hwnd, exc_info=True)
		return None


class WindowFinder:
	"""Estado de la búsqueda (último texto buscado)."""

	def __init__(self) -> None:
		self.lastQuery = ""
		self.history: list[str] = []

	def remember(self, query: str) -> None:
		self.lastQuery = query
		if query in self.history:
			self.history.remove(query)
		self.history.insert(0, query)
		del self.history[20:]

	def find(self, query: str, direction: int = 1, window=None) -> None:
		"""Busca en ``window`` (o en la ventana en primer plano) y anuncia el resultado.

		Hilo del núcleo.
		"""
		from .. import api, presentation, speech
		from ..audio import tones
		from ..config import conf
		from ..i18n import _
		from ..objects.uia import UIAObject

		if not query:
			return
		c = conf["windowFind"]
		fg = window if window is not None and _isAlive(window) else api.getForegroundObject()
		root = rootElementOf(fg)
		if root is None:
			speech.speakMessage(_("No hay ninguna ventana en primer plano"))
			return
		cands = collect(root, c["includeOffscreen"])
		nav = api.getNavigatorObject()
		current = -1
		navRid = tuple(getattr(nav, "runtimeId", ()) or ()) if nav is not None else ()
		if navRid:
			for i, cand in enumerate(cands):
				if cand.runtimeId == navRid:
					current = i
					break
		idx, wrapped = pickNext(cands, current, query, direction, c["caseSensitive"])
		if idx < 0:
			speech.speakMessage(_("No se encontró «{text}» en esta ventana").format(text=query))
			return
		obj = UIAObject.fromElement(cands[idx].element)
		if obj is None:
			speech.speakMessage(_("El resultado ya no está disponible"))
			return
		if wrapped:
			tones.playSound("wrap")
		if cands[idx].offscreen:
			try:
				obj.scrollIntoView()
			except Exception:
				pass
		api.setNavigatorObject(obj)
		movedFocus = False
		if c["moveFocus"]:
			try:
				if obj.isFocusable and not obj.hasFocus:
					obj.setFocus()
					movedFocus = True
			except Exception:
				log.debug("No se pudo mover el foco al resultado", exc_info=True)
		speech.cancelSpeech()
		if not movedFocus:
			# Si el foco se ha movido, el evento de foco ya lo anuncia.
			presentation.speakObject(obj, reason=presentation.Reason.QUERY)
