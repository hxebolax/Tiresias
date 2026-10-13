"""Utilidades comunes de la interfaz gráfica.

Todas las ventanas de Tiresias viven en el hilo principal (wxPython). Este
módulo ofrece lo necesario para llegar a ese hilo desde cualquier otro y
algunos ayudantes de accesibilidad compartidos por los diálogos.
"""

from __future__ import annotations

import unicodedata
from typing import Any, Callable

import wx

from .. import queue_handler, winapi
from ..log import getLogger

log = getLogger("gui")


def runOnGui(func: Callable, *args: Any, **kwargs: Any) -> None:
	"""Ejecuta ``func`` en el hilo de la interfaz (seguro desde cualquier hilo).

	Si ya estamos en el hilo de la interfaz se ejecuta inmediatamente.
	"""

	def _run() -> None:
		try:
			from ..lock_guard import allowGuiCall

			# Con la sesión bloqueada no se abren ventanas (ver lock_guard).
			if not allowGuiCall(func):
				return
			func(*args, **kwargs)
		except Exception:
			log.exception("Error en la interfaz ejecutando %r", func)

	if wx.GetApp() is None:
		log.debug("Sin aplicación wx: se descarta %r", func)
		return
	if wx.IsMainThread():
		_run()
	else:
		wx.CallAfter(_run)


def bringToFront(win: wx.TopLevelWindow) -> None:
	"""Muestra una ventana de nivel superior y la trae al primer plano."""
	try:
		if not win:
			return
		_rememberPreviousForeground(win)
		if win.IsIconized():
			win.Iconize(False)
		if not win.IsShown():
			win.Show()
		win.Raise()
		winapi.setForegroundWindow(win.GetHandle())
	except RuntimeError:
		# La ventana se destruyó entre medias.
		pass
	except Exception:
		log.debug("No se pudo traer la ventana al frente", exc_info=True)


def _rememberPreviousForeground(win: wx.TopLevelWindow) -> None:
	"""Recuerda la aplicación activa para volver a ella al cerrar ``win``.

	Al cerrarse una ventana de Tiresias, Windows activa la siguiente por orden
	Z, que puede ser otra aplicación cualquiera: el usuario debe volver a donde
	estaba (como al cerrar los diálogos de NVDA).
	"""
	import os

	fg = winapi.getForegroundWindow()
	if fg and winapi.getWindowProcessId(fg) != os.getpid():
		prev = fg
	elif getattr(win, "_prevForegroundHwnd", None) is not None:
		# Ya visible y activa (o se reactiva desde otra ventana de Tiresias).
		return
	else:
		try:
			from ..a11y import winevents

			prev = winevents.lastForeignForeground()
		except Exception:
			prev = 0
	first = getattr(win, "_prevForegroundHwnd", None) is None
	win._prevForegroundHwnd = prev or 0
	if not first:
		return

	def onShow(evt: wx.ShowEvent) -> None:
		evt.Skip()
		if not evt.IsShown():
			_restoreOnClose(win)

	hwnd = win.GetHandle()

	def onDestroy(evt: wx.WindowDestroyEvent) -> None:
		evt.Skip()
		# Durante la destrucción el objeto del evento es otro envoltorio de wx
		# («is win» era siempre falso): se compara por la ventana de Windows.
		obj = evt.GetEventObject()
		try:
			same = obj is win or (obj is not None and obj.GetHandle() == hwnd)
		except Exception:
			same = False
		if same:
			_restoreOnClose(win)

	win.Bind(wx.EVT_SHOW, onShow)
	win.Bind(wx.EVT_WINDOW_DESTROY, onDestroy)


def _otherWindowShown(win: Any) -> bool:
	"""¿Queda otro diálogo de Tiresias visible (o la ventana padre)? Windows lo activa."""
	try:
		parent = win.GetParent()
		for w in wx.GetTopLevelWindows():
			if w is win or not w.IsShown() or w.GetParent() is win:
				continue
			if w is parent or isinstance(w, wx.Dialog):
				return True
	except Exception:
		pass
	return False


def _restoreOnClose(win: Any) -> None:
	"""Al ocultarse o destruirse ``win``, activa la aplicación de antes.

	Se hace en el momento (aún con la ventana visible y activa), así Windows no
	llega a activar otra ventana por orden Z, que se anunciaría un instante.
	"""
	import os

	prev = getattr(win, "_prevForegroundHwnd", 0)
	if not prev:
		return
	win._prevForegroundHwnd = 0
	if _otherWindowShown(win):
		return
	fg = winapi.getForegroundWindow()
	if fg and winapi.getWindowProcessId(fg) != os.getpid():
		# El usuario ya está en otra aplicación: no se le quita.
		return
	restorePreviousForeground(prev, force=True)


def restorePreviousForeground(prev: int, force: bool = False) -> None:
	"""Vuelve a ``prev`` salvo que otra ventana de Tiresias esté activa (o ``force``)."""
	import os

	try:
		if not prev or not winapi.user32.IsWindow(prev) or not winapi.user32.IsWindowVisible(prev):
			return
		fg = winapi.getForegroundWindow()
		if fg == prev or (not force and fg and winapi.getWindowProcessId(fg) == os.getpid()):
			return
		winapi.setForegroundWindow(prev)
	except Exception:
		log.debug("No se pudo volver a la ventana anterior", exc_info=True)


def isAlive(win: Any) -> bool:
	"""``True`` si ``win`` es una ventana wx que no se ha destruido."""
	try:
		return win is not None and bool(win) and not win.IsBeingDeleted()
	except RuntimeError:
		return False


def speakMessage(text: str) -> None:
	"""Habla un mensaje desde el hilo de la interfaz (se encola al núcleo)."""
	from .. import speech

	queue_handler.queueFunction(speech.speakMessage, text)


def normalizeForSearch(text: str) -> str:
	"""Minúsculas y sin tildes, para búsquedas tolerantes."""
	decomposed = unicodedata.normalize("NFD", text.casefold())
	return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def matchesAll(haystack: str, query: str) -> bool:
	"""Todas las palabras de ``query`` aparecen en ``haystack`` (ya normalizado)."""
	return all(token in haystack for token in normalizeForSearch(query).split())


def _withinOneEdit(a: str, b: str) -> bool:
	"""``True`` si ``a`` y ``b`` difieren como mucho en una edición
	(sustitución, inserción, borrado o trasposición de dos letras seguidas)."""
	if a == b:
		return True
	la, lb = len(a), len(b)
	if abs(la - lb) > 1:
		return False
	if la == lb:
		diff = [i for i in range(la) if a[i] != b[i]]
		if len(diff) == 1:
			return True
		return len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]
	if la > lb:
		a, b = b, a
	# b es una letra más largo que a.
	for i in range(len(b)):
		if b[:i] + b[i + 1 :] == a:
			return True
	return False


def _isSubsequence(needle: str, haystack: str) -> bool:
	it = iter(haystack)
	return all(ch in it for ch in needle)


def _tokenScore(token: str, words: list[str], haystack: str) -> float:
	"""Puntuación de una palabra de la búsqueda (0 si no encaja)."""
	if not token:
		return 1.0
	best = 0.0
	for w in words:
		if w == token:
			return 10.0
		if w.startswith(token):
			best = max(best, 8.0)
		elif token in w:
			best = max(best, 6.0)
		elif len(token) >= 4 and len(w) >= 3 and (_withinOneEdit(token, w) or _withinOneEdit(token, w[: len(token)])):
			# Tolerancia a una errata en palabras de 4 letras o más.
			best = max(best, 4.0)
	if best:
		return best
	if token in haystack:
		return 5.0
	if len(token) >= 2:
		# Iniciales o letras salteadas (por ejemplo «tcp» para «tecla de copia»).
		initials = "".join(w[0] for w in words if w)
		if initials.startswith(token) or token in initials:
			return 3.0
		# Letras en orden dentro de una misma palabra («cnfg» para «configuración»).
		if len(token) >= 3 and any(w[0] == token[0] and _isSubsequence(token, w) for w in words if w):
			return 1.0
	return 0.0


def fuzzyScore(haystack: str, query: str) -> float:
	"""Puntuación de búsqueda difusa de ``query`` en ``haystack`` (ya normalizado).

	Cada palabra de la búsqueda tiene que encajar de alguna forma: palabra
	exacta, principio de palabra, subcadena, una errata, iniciales o letras en
	orden. Devuelve 0 si alguna no encaja; cuanto mayor, mejor coincidencia.
	"""
	tokens = normalizeForSearch(query).split()
	if not tokens:
		return 1.0
	words = [w for w in haystack.replace("(", " ").replace(")", " ").replace(",", " ").split() if w]
	total = 0.0
	for t in tokens:
		s = _tokenScore(t, words, haystack)
		if s <= 0:
			return 0.0
		total += s
	# Bonificación si la frase entera aparece tal cual.
	phrase = " ".join(tokens)
	if len(tokens) > 1 and phrase in haystack:
		total += 5.0
	return total


def addLabel(parent: wx.Window, sizer: wx.Sizer, label: str) -> wx.StaticText:
	"""Crea y añade una etiqueta.

	Debe llamarse justo antes de crear el control que etiqueta, para que los
	lectores de pantalla la asocien (la etiqueta precede al control en el
	orden de ventanas).
	"""
	st = wx.StaticText(parent, label=label)
	sizer.Add(st, 0, wx.LEFT | wx.RIGHT | wx.TOP, 6)
	return st


def bindEscapeToClose(win: wx.TopLevelWindow) -> None:
	"""Escape cierra la ventana (para marcos que no son diálogos)."""

	def onCharHook(evt: wx.KeyEvent) -> None:
		if evt.GetKeyCode() == wx.WXK_ESCAPE and not evt.HasAnyModifiers():
			win.Close()
			return
		evt.Skip()

	win.Bind(wx.EVT_CHAR_HOOK, onCharHook)


def urlProblem(value: str, allowLocal: bool = False) -> str | None:
	"""Motivo por el que ``value`` no es una dirección válida (``None`` si vale o está vacía).

	Vale ``http://`` o ``https://`` con equipo. Con ``allowLocal`` también
	``file://`` y las rutas absolutas (servidor de distribución en una carpeta
	o en la red local). Sin esta comprobación, «servidor.com/tiresias» se
	tomaría por una ruta de archivo y fallaría sin explicación.
	"""
	import os
	import urllib.parse

	from ..i18n import _

	text = (value or "").strip()
	if not text:
		return None
	if "://" not in text:
		if allowLocal and os.path.isabs(text):
			return None
		if allowLocal:
			return _("«{value}» no es una dirección: empiece por https:// (o escriba la ruta completa de una carpeta).").format(value=text)
		return _("«{value}» no es una dirección: empiece por http:// o https://.").format(value=text)
	parts = urllib.parse.urlsplit(text)
	scheme = parts.scheme.lower()
	if scheme in ("http", "https"):
		return None if parts.netloc else _("Falta el nombre del servidor en «{value}».").format(value=text)
	if scheme == "file" and allowLocal:
		return None
	return _("La dirección «{value}» no es http:// ni https://.").format(value=text)
