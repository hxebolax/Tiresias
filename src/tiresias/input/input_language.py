"""Anuncio de los cambios de idioma o de distribución del teclado.

Como NVDA (``nvdaControllerInternal_inputLangChangeNotify``): al cambiar el
idioma de entrada o la distribución (Alt+Mayúsculas, Windows+Espacio,
Control+Mayúsculas, el selector de la barra de tareas con el ratón...) se dice
el idioma, si ha cambiado, y la distribución o el método de entrada:
«Español (España), Español», «Inglés (Estados Unidos), Estados Unidos».

NVDA lo sabe desde dentro de cada aplicación (inyecta código y recibe
``WM_INPUTLANGCHANGE``). Tiresias no inyecta código: un hilo propio
(:class:`LayoutWatcher`) mira varias veces por segundo la distribución del hilo
con el foco del teclado (``GetKeyboardLayout``; son llamadas locales e
instantáneas, sin mensajes a otras aplicaciones) y, si cambia, encola el
anuncio en el hilo del núcleo, donde se buscan los nombres (registro y
``GetLocaleInfoEx``, con caché). El hilo de los ganchos no hace nada nuevo.

Un cambio se anuncia una sola vez (:class:`LayoutTracker`):

- Con la distribución común a todas las ventanas (lo normal en Windows 8 y
  posteriores), solo cuando la distribución del foco difiere de la última
  anunciada. Al cambiar de ventana no se repite aunque la ventana nueva aún
  muestre un momento la distribución antigua.
- Con «Permitirme usar un método de entrada diferente para cada ventana de
  aplicación» (``SPI_GETTHREADLOCALINPUTSETTINGS``), cuando cambia la de la
  propia ventana; pasar a otra ventana que ya tenía otra distribución no se
  anuncia.

Opción ``keyboard.announceInputLanguageChanges`` (activada; NVDA #1676 pide
poder desactivarlo). Como NVDA, no se anuncia durante la lectura continua ni
en las aplicaciones en modo dormir.

Métodos de entrada (IME) de Text Services Framework: el ``HKL`` no dice qué
método está activo. Si el idioma solo tiene un método de entrada instalado
(``HKCU\\Control Panel\\International\\User Profile``), se dice su nombre
(«Microsoft IME»); si tiene varios, solo el idioma.
"""

from __future__ import annotations

import ctypes
import re
import threading
import time
import winreg
from collections.abc import Callable
from ctypes import wintypes

from ..i18n import _
from ..log import getLogger

log = getLogger("inputLanguage")

#: Segundos entre comprobaciones de la distribución del foco.
POLL_INTERVAL = 0.15
#: Hilos recordados como máximo (los más antiguos se olvidan).
MAX_THREADS = 128
#: Con distribuciones por ventana: segundos en los que la misma distribución
#: que acaba de anunciarse, vista en otro hilo, no se repite (el selector de la
#: barra de tareas cambia su propio hilo y luego el de la ventana).
DUPLICATE_WINDOW = 2.0

KEYBOARD_LAYOUTS_KEY = r"SYSTEM\CurrentControlSet\Control\Keyboard Layouts"
USER_PROFILE_KEY = r"Control Panel\International\User Profile"
TIP_KEY = r"SOFTWARE\Microsoft\CTF\TIP"

LOCALE_SLOCALIZEDDISPLAYNAME = 0x02
LOCALE_SLOCALIZEDCOUNTRYNAME = 0x06
LOCALE_SLOCALIZEDLANGUAGENAME = 0x6F
SPI_GETTHREADLOCALINPUTSETTINGS = 0x104E

# Instancias propias: los argtypes no afectan a los demás usuarios de ctypes.windll.
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.LCIDToLocaleName.argtypes = [wintypes.DWORD, wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD]
_kernel32.LCIDToLocaleName.restype = ctypes.c_int
_kernel32.GetLocaleInfoEx.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPWSTR, ctypes.c_int]
_kernel32.GetLocaleInfoEx.restype = ctypes.c_int
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
_user32.GetKeyboardLayout.restype = ctypes.c_void_p
_user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
_user32.SystemParametersInfoW.restype = wintypes.BOOL
try:
	_shlwapi = ctypes.WinDLL("shlwapi")
	_shlwapi.SHLoadIndirectString.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.UINT, ctypes.c_void_p]
	_shlwapi.SHLoadIndirectString.restype = ctypes.c_long
except (OSError, AttributeError):  # pragma: no cover
	_shlwapi = None


# ====================================================================== nombres (funciones puras)
def langIdOf(hkl: int) -> int:
	"""Idioma (palabra baja) de un ``HKL``."""
	return int(hkl) & 0xFFFF


def klidFromHkl(hkl: int, layoutIds: dict[int, str] | None = None) -> str:
	"""Identificador de la distribución (``0000040A``) de un ``HKL``.

	La palabra alta del ``HKL`` es la distribución: ``E0xx`` es un IME antiguo
	(el ``HKL`` entero es su identificador), ``Fxxx`` una variante con
	«Layout Id» (``layoutIds``: id -> identificador) y si no, la distribución
	principal de ese idioma.
	"""
	hkl = int(hkl) & 0xFFFFFFFF
	hi = (hkl >> 16) & 0xFFFF
	lo = hkl & 0xFFFF
	if hi & 0xF000 == 0xE000:
		return f"{hkl:08X}"
	if hi & 0xF000 == 0xF000:
		klid = (layoutIds or {}).get(hi & 0x0FFF)
		return klid.upper() if klid else f"0000{lo:04X}"
	return f"0000{(hi or lo):04X}"


def composeLanguageName(language: str, country: str, display: str = "") -> str:
	"""«Español (España)»: idioma y país (o el nombre completo si el idioma ya
	lleva paréntesis, como «Chino (simplificado)»)."""
	language = (language or "").strip()
	country = (country or "").strip()
	if language and country and "(" not in language:
		return f"{language} ({country})"
	return (display or language).strip()


def stripLanguagePrefix(layoutName: str, languageNames: tuple[str, ...]) -> str:
	"""Quita «Idioma - » del principio del nombre de la distribución.

	NVDA lo quita siempre que hay « - »; aquí solo si lo de delante es el
	idioma, para no dejar «Estados Unidos - Internacional» en «Internacional».
	"""
	if " - " not in layoutName:
		return layoutName
	head, tail = layoutName.split(" - ", 1)
	low = head.strip().casefold()
	if tail.strip() and any(low == (n or "").strip().casefold() for n in languageNames if n):
		return tail.strip()
	return layoutName


def formatAnnouncement(language: str, layout: str, includeLanguage: bool) -> str:
	"""Texto del anuncio: «Idioma, distribución» o solo lo que haga falta."""
	language = (language or "").strip()
	layout = (layout or "").strip()
	if not includeLanguage and layout:
		return layout
	if not language:
		language = _("idioma desconocido")
	if layout and layout.casefold() != language.casefold():
		return f"{language}, {layout}"
	return language


_PROFILE_VALUE = re.compile(r"^([0-9A-Fa-f]{4}):(?:([0-9A-Fa-f]{8})|(\{[0-9A-Fa-f-]{36}\})(\{[0-9A-Fa-f-]{36}\}))$")


def parseProfileValue(name: str) -> tuple[int, str, str, str] | None:
	"""Un valor de ``User Profile\\<idioma>``: ``(idioma, klid, clsid, perfil)``.

	``0C0A:0000040A`` es una distribución (``klid``); ``0411:{CLSID}{PERFIL}`` un
	método de entrada de Text Services Framework (``clsid`` y ``perfil``).
	"""
	m = _PROFILE_VALUE.match((name or "").strip())
	if not m:
		return None
	lang = int(m.group(1), 16)
	return (lang, (m.group(2) or "").upper(), (m.group(3) or "").upper(), (m.group(4) or "").upper())


def chooseInputMethod(klid: str, entries: list[tuple[int, str, str, str]], langId: int) -> tuple[str, str, str]:
	"""Qué buscar para nombrar el método de entrada.

	Devuelve ``("layout", klid, "")``, ``("tip", clsid, perfil)`` o
	``("none", "", "")`` (varios métodos de entrada y no se sabe cuál).
	"""
	layouts = [e[1] for e in entries if e[0] == langId and e[1]]
	tips = [(e[2], e[3]) for e in entries if e[0] == langId and e[2]]
	if not tips or klid.upper() in layouts or klid.upper().startswith("E"):
		return ("layout", klid, "")
	if len(tips) == 1:
		return ("tip", tips[0][0], tips[0][1])
	return ("none", "", "")


# ====================================================================== nombres (sistema)
def localeNameFromLangId(langId: int) -> str:
	buf = ctypes.create_unicode_buffer(85)
	try:
		if _kernel32.LCIDToLocaleName(int(langId), buf, 85, 0):
			return buf.value
	except Exception:
		log.debug("LCIDToLocaleName falló", exc_info=True)
	return ""


def _localeInfo(locale: str, lctype: int) -> str:
	buf = ctypes.create_unicode_buffer(256)
	try:
		if _kernel32.GetLocaleInfoEx(locale, lctype, buf, 256):
			return buf.value
	except Exception:
		log.debug("GetLocaleInfoEx falló", exc_info=True)
	return ""


_languageCache: dict[int, tuple[str, str]] = {}


def languageNames(langId: int) -> tuple[str, str]:
	"""``(«Español (España)», «Español»)`` en el idioma de Windows."""
	cached = _languageCache.get(langId)
	if cached is not None:
		return cached
	loc = localeNameFromLangId(langId)
	if loc:
		lang = _localeInfo(loc, LOCALE_SLOCALIZEDLANGUAGENAME)
		full = composeLanguageName(lang, _localeInfo(loc, LOCALE_SLOCALIZEDCOUNTRYNAME), _localeInfo(loc, LOCALE_SLOCALIZEDDISPLAYNAME))
		result = (full, lang)
	else:
		result = ("", "")
	_languageCache[langId] = result
	return result


def loadIndirectString(value: str) -> str:
	"""Resuelve ``@%SystemRoot%\\system32\\input.dll,-5020`` (en el idioma de Windows)."""
	if not value or not value.startswith("@") or _shlwapi is None:
		return value or ""
	buf = ctypes.create_unicode_buffer(512)
	try:
		if _shlwapi.SHLoadIndirectString(value, buf, 512, None) == 0:
			return buf.value
	except Exception:
		log.debug("SHLoadIndirectString falló", exc_info=True)
	return ""


def _queryValue(key, name: str) -> str:
	try:
		value = winreg.QueryValueEx(key, name)[0]
	except OSError:
		return ""
	return value if isinstance(value, str) else ""


_layoutIdMap: dict[int, str] | None = None


def layoutIdMap() -> dict[int, str]:
	"""«Layout Id» -> identificador de las variantes de distribución (una vez)."""
	global _layoutIdMap
	if _layoutIdMap is not None:
		return _layoutIdMap
	out: dict[int, str] = {}
	try:
		with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, KEYBOARD_LAYOUTS_KEY) as root:
			i = 0
			while True:
				try:
					sub = winreg.EnumKey(root, i)
				except OSError:
					break
				i += 1
				try:
					with winreg.OpenKey(root, sub) as k:
						lid = _queryValue(k, "Layout Id")
				except OSError:
					continue
				if lid:
					try:
						out.setdefault(int(lid, 16), sub.upper())
					except ValueError:
						pass
	except OSError:
		log.debug("No se pudo leer la lista de distribuciones", exc_info=True)
	_layoutIdMap = out
	return out


_layoutNameCache: dict[str, str] = {}


def layoutDisplayName(klid: str) -> str:
	"""Nombre localizado de una distribución («Español», «Estados Unidos»)."""
	klid = klid.upper()
	if klid in _layoutNameCache:
		return _layoutNameCache[klid]
	name = ""
	try:
		with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, KEYBOARD_LAYOUTS_KEY + "\\" + klid) as k:
			name = loadIndirectString(_queryValue(k, "Layout Display Name")) or _queryValue(k, "Layout Text")
	except OSError:
		name = ""
	_layoutNameCache[klid] = name
	return name


def tipDisplayName(clsid: str, profile: str, langId: int) -> str:
	"""Nombre de un método de entrada de Text Services Framework («Microsoft IME»)."""
	path = f"{TIP_KEY}\\{clsid}\\LanguageProfile\\0x{langId:08x}\\{profile}"
	try:
		with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
			return loadIndirectString(_queryValue(k, "Display Description")) or _queryValue(k, "Description")
	except OSError:
		return ""


def userProfileEntries() -> list[tuple[int, str, str, str]]:
	"""Métodos de entrada instalados por el usuario (configuración de idioma)."""
	out: list[tuple[int, str, str, str]] = []
	try:
		with winreg.OpenKey(winreg.HKEY_CURRENT_USER, USER_PROFILE_KEY) as root:
			i = 0
			while True:
				try:
					sub = winreg.EnumKey(root, i)
				except OSError:
					break
				i += 1
				try:
					with winreg.OpenKey(root, sub) as k:
						j = 0
						while True:
							try:
								name = winreg.EnumValue(k, j)[0]
							except OSError:
								break
							j += 1
							parsed = parseProfileValue(name)
							if parsed is not None:
								out.append(parsed)
				except OSError:
					continue
	except OSError:
		pass
	return out


def inputMethodName(hkl: int) -> str:
	"""Nombre de la distribución o del método de entrada de un ``HKL``."""
	langId = langIdOf(hkl)
	klid = klidFromHkl(hkl, layoutIdMap())
	kind, a, b = chooseInputMethod(klid, userProfileEntries(), langId)
	if kind == "tip":
		name = tipDisplayName(a, b, langId)
		if name:
			return name
	elif kind == "none":
		return ""
	# Como NVDA: si no se encuentra, se prueba la distribución principal del idioma.
	name = layoutDisplayName(klid) or layoutDisplayName(f"0000{langId:04X}")
	return name


def describe(hkl: int, previous: int | None) -> str:
	"""Texto que se anuncia al pasar de ``previous`` a ``hkl``."""
	langId = langIdOf(hkl)
	full, short = languageNames(langId)
	layout = stripLanguagePrefix(inputMethodName(hkl), (full, short))
	includeLanguage = previous is None or langIdOf(previous) != langId
	return formatAnnouncement(full, layout, includeLanguage)


# ====================================================================== seguimiento (puro)
def threadLocalInputSettings() -> bool:
	"""``True`` si cada ventana tiene su propio método de entrada (opción de Windows)."""
	value = wintypes.BOOL(0)
	try:
		if _user32.SystemParametersInfoW(SPI_GETTHREADLOCALINPUTSETTINGS, 0, ctypes.byref(value), 0):
			return bool(value.value)
	except Exception:
		pass
	return False


class LayoutTracker:
	"""Decide si una distribución vista en el foco es un cambio que se anuncia.

	:meth:`observe` recibe el hilo con el foco y su ``HKL`` y devuelve la
	distribución anterior si hay que anunciar el cambio (o ``None``).
	"""

	def __init__(self, perThread: Callable[[], bool] = threadLocalInputSettings, clock: Callable[[], float] = time.monotonic) -> None:
		self._perThread = perThread
		self._clock = clock
		self._byThread: dict[int, int] = {}
		#: Última distribución anunciada (o la del arranque).
		self._current: int | None = None
		self._lastThread = 0
		self._lastTime = 0.0

	def reset(self) -> None:
		self._byThread.clear()
		self._current = None
		self._lastThread = 0
		self._lastTime = 0.0

	@property
	def current(self) -> int | None:
		return self._current

	def _remember(self, threadId: int, hkl: int) -> None:
		if threadId not in self._byThread and len(self._byThread) >= MAX_THREADS:
			# Se olvida el más antiguo (los diccionarios conservan el orden).
			self._byThread.pop(next(iter(self._byThread)))
		self._byThread[threadId] = hkl

	def observe(self, threadId: int, hkl: int) -> int | None:
		hkl = int(hkl) & 0xFFFFFFFF
		prev = self._byThread.get(threadId)
		self._remember(threadId, hkl)
		if self._current is None:
			# Primera vez: es la distribución de partida, no un cambio.
			self._current = hkl
			return None
		if prev is None or hkl == prev:
			# Ventana nueva para Tiresias o sin cambios en su hilo: no se anuncia
			# (al cambiar de ventana, cada una puede tener la suya o tardar un
			# momento en tomar la común).
			return None
		try:
			perThread = bool(self._perThread())
		except Exception:
			perThread = False
		now = self._clock()
		if perThread:
			if hkl == self._current and threadId != self._lastThread and now - self._lastTime < DUPLICATE_WINDOW:
				return None
			before = prev
		else:
			if hkl == self._current:
				return None
			before = self._current
		self._current = hkl
		self._lastThread = threadId
		self._lastTime = now
		return before


# ====================================================================== hilo de vigilancia
def sampleForeground() -> tuple[int, int] | None:
	"""``(hilo, HKL)`` del foco del teclado; solo llamadas locales sin mensajes."""
	from .. import winapi

	fg = winapi.getForegroundWindow()
	if not fg:
		return None
	thread = winapi.getWindowThreadId(fg)
	if not thread:
		return None
	info = winapi.getGUIThreadInfo(thread)
	focus = int(info.hwndFocus or 0) if info is not None else 0
	if focus:
		# Aplicaciones de la Tienda: el foco está en la CoreWindow, de otro hilo.
		thread = winapi.getWindowThreadId(focus) or thread
	hkl = _user32.GetKeyboardLayout(thread)
	if not hkl:
		return None
	return thread, int(hkl) & 0xFFFFFFFF


def _queueAnnouncement(hkl: int, previous: int | None) -> None:
	from .. import queue_handler

	queue_handler.queueFunction(announce, hkl, previous)


class LayoutWatcher:
	"""Hilo que mira la distribución del foco y avisa de los cambios."""

	def __init__(
		self,
		sample: Callable[[], tuple[int, int] | None] = sampleForeground,
		onChange: Callable[[int, int | None], None] = _queueAnnouncement,
		interval: float = POLL_INTERVAL,
		tracker: LayoutTracker | None = None,
	) -> None:
		self._sample = sample
		self._onChange = onChange
		self.interval = interval
		self.tracker = tracker or LayoutTracker()
		self._stop = threading.Event()
		self._thread: threading.Thread | None = None
		self._lock = threading.Lock()

	@property
	def isRunning(self) -> bool:
		return self._thread is not None and self._thread.is_alive()

	def checkOnce(self) -> bool:
		"""Una comprobación; ``True`` si se ha avisado de un cambio."""
		try:
			sample = self._sample()
		except Exception:
			log.debug("No se pudo leer la distribución del foco", exc_info=True)
			return False
		if sample is None:
			return False
		thread, hkl = sample
		previous = self.tracker.observe(thread, hkl)
		if previous is None:
			return False
		try:
			self._onChange(hkl, previous)
		except Exception:
			log.exception("Error avisando del cambio de distribución")
		return True

	def start(self) -> None:
		with self._lock:
			if self.isRunning:
				return
			self._stop = threading.Event()
			self.tracker.reset()
			self._thread = threading.Thread(target=self._run, args=(self._stop,), name="IdiomaTeclado", daemon=True)
			self._thread.start()

	def stop(self) -> None:
		with self._lock:
			thread, self._thread = self._thread, None
			self._stop.set()
		if thread is not None and thread is not threading.current_thread():
			thread.join(1)

	def _run(self, stopEvent: threading.Event) -> None:
		self.checkOnce()
		while not stopEvent.wait(self.interval):
			self.checkOnce()


watcher = LayoutWatcher()


def start() -> None:
	"""Arranca la vigilancia (con los ganchos de Windows, ver ``input.hooks``)."""
	try:
		watcher.start()
	except Exception:
		log.exception("No se pudo vigilar el idioma del teclado")


def stop() -> None:
	try:
		watcher.stop()
	except Exception:
		log.exception("Error parando la vigilancia del idioma del teclado")


# ====================================================================== anuncio (hilo del núcleo)
def isEnabled() -> bool:
	from ..config import conf

	try:
		return bool(conf["keyboard"]["announceInputLanguageChanges"])
	except Exception:
		return True


def _shouldStaySilent() -> bool:
	"""Lectura continua (NVDA #1676) o aplicación en modo dormir."""
	try:
		from ..speech import sayall

		if sayall.isRunning():
			return True
	except Exception:
		pass
	try:
		from .. import api

		focus = api.getFocusObject()
		app = getattr(focus, "appModule", None) if focus is not None else None
		if app is not None and getattr(app, "sleepMode", False):
			return True
	except Exception:
		pass
	return False


def announce(hkl: int, previous: int | None) -> None:
	"""Dice el idioma o la distribución nuevos (hilo del núcleo)."""
	if not isEnabled() or _shouldStaySilent():
		return
	try:
		text = describe(hkl, previous)
	except Exception:
		log.exception("No se pudo nombrar la distribución %08x", hkl)
		return
	if not text:
		return
	from .. import speech

	speech.speakMessage(text)
