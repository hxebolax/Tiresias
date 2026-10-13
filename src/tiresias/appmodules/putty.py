"""PuTTY y KiTTY.

La ventana de PuTTY no expone su texto a ninguna API de accesibilidad. Para
leerlo, Tiresias usa la orden «Copiar todo al portapapeles» del menú de
sistema de PuTTY, guarda el texto y devuelve el portapapeles a como estaba:

- Tiresias+Alt+Mayúsculas+V muestra todo el contenido de la terminal en una
  ventana navegable (para leerlo con las flechas, buscar y copiar).
- Tiresias+Alt+1 a Tiresias+Alt+0 leen la última línea, la penúltima...
  (hasta la décima) de la terminal sin mover nada (Alt+número queda para el
  intérprete de órdenes remoto).
- Tiresias+Alt+Mayúsculas+N lee las líneas nuevas desde la última lectura.

Limitación: el historial del portapapeles de Windows (Windows+V) puede
guardar estas copias; Tiresias no las añade a su propio historial.
"""

from __future__ import annotations

from .. import clipboard, speech, winapi
from ..baseobject import script
from ..i18n import _
from ..log import getLogger
from . import AppModule as BaseAppModule

log = getLogger("putty")

CAT = _("PuTTY")
WM_SYSCOMMAND = 0x0112
#: «Copy All to Clipboard» del menú de sistema de PuTTY (window.c).
IDM_COPYALL = 0x0170
TERMINAL_CLASSES = ("PuTTY", "KiTTY")


def terminalWindow() -> int:
	hwnd = winapi.getForegroundWindow()
	return hwnd if winapi.getClassName(hwnd) in TERMINAL_CLASSES else 0


def readTerminal(hwnd: int, callback, attempts: int = 25) -> None:
	"""Lee todo el texto de la terminal sin bloquear: ``callback(texto | None)``.

	Pide a PuTTY que copie todo, espera con temporizadores del núcleo a que
	cambie el portapapeles, guarda el texto y restaura el portapapeles.
	"""
	from .. import queue_handler

	# Rev. 10.11: si el portapapeles no tiene texto (una imagen, archivos
	# copiados...), se guarda con todos sus formatos; antes se perdía.
	previous = winapi.getClipboardText()
	snapshot = snapshotClipboard() if previous is None else None
	seq = winapi.user32.GetClipboardSequenceNumber()
	clipboard.ignoreNextChange()
	winapi.user32.PostMessageW(hwnd, WM_SYSCOMMAND, IDM_COPYALL, 0)
	state = {"left": attempts}

	def poll() -> None:
		if winapi.user32.GetClipboardSequenceNumber() == seq:
			state["left"] -= 1
			if state["left"] > 0:
				queue_handler.callLater(40, poll)
			else:
				# PuTTY no copió nada: la próxima copia del usuario sí se anuncia
				# y entra en el historial del portapapeles.
				clipboard.cancelIgnore()
				callback(None)
			return
		text = winapi.getClipboardText()
		if snapshot is not None:
			clipboard.ignoreNextChange()
			if not restoreClipboard(snapshot):
				clipboard.cancelIgnore()
		elif previous is not None:
			clipboard.ignoreNextChange()
			winapi.setClipboardText(previous)
		callback(text)

	queue_handler.callLater(40, poll)


#: Formatos que no son memoria global (mapas de bits GDI, metarchivos...): no
#: se copian; Windows vuelve a crearlos a partir de los equivalentes (CF_DIB).
_GDI_FORMATS = {2, 3, 9, 14, 0x80, 0x82, 0x83, 0x8E}
#: Más que esto no se guarda (solo el texto, como antes).
MAX_CLIPBOARD_BYTES = 64 * 1024 * 1024


def _clipboardApi():
	import ctypes
	from ctypes import wintypes

	u, k = winapi.user32, winapi.kernel32
	u.EnumClipboardFormats.argtypes = [wintypes.UINT]
	u.EnumClipboardFormats.restype = wintypes.UINT
	u.EmptyClipboard.restype = wintypes.BOOL
	u.CloseClipboard.restype = wintypes.BOOL
	k.GlobalFree.argtypes = [wintypes.HGLOBAL]
	k.GlobalFree.restype = wintypes.HGLOBAL
	return ctypes, u, k


def _openClipboard(u, k) -> bool:
	for _i in range(5):
		if u.OpenClipboard(None):
			return True
		k.Sleep(20)
	return False


def snapshotClipboard() -> list[tuple[int, bytes]] | None:
	"""Todos los formatos de memoria del portapapeles (``None`` si no se puede)."""
	try:
		ctypes, u, k = _clipboardApi()
		if not _openClipboard(u, k):
			return None
	except Exception:
		return None
	try:
		out: list[tuple[int, bytes]] = []
		total = 0
		fmt = 0
		while True:
			fmt = u.EnumClipboardFormats(fmt)
			if not fmt:
				break
			if fmt in _GDI_FORMATS:
				continue
			h = u.GetClipboardData(fmt)
			if not h:
				continue
			size = k.GlobalSize(h)
			total += size
			if total > MAX_CLIPBOARD_BYTES:
				return None
			p = k.GlobalLock(h)
			if not p:
				continue
			try:
				out.append((fmt, ctypes.string_at(p, size)))
			finally:
				k.GlobalUnlock(h)
		return out
	except Exception:
		log.debug("No se pudo guardar el portapapeles", exc_info=True)
		return None
	finally:
		u.CloseClipboard()


def restoreClipboard(items: list[tuple[int, bytes]]) -> bool:
	"""Devuelve al portapapeles lo guardado con :func:`snapshotClipboard`."""
	try:
		ctypes, u, k = _clipboardApi()
		if not _openClipboard(u, k):
			return False
	except Exception:
		return False
	try:
		u.EmptyClipboard()
		for fmt, data in items:
			h = k.GlobalAlloc(0x0002, max(1, len(data)))  # GMEM_MOVEABLE
			if not h:
				continue
			p = k.GlobalLock(h)
			if not p:
				k.GlobalFree(h)
				continue
			ctypes.memmove(p, data, len(data))
			k.GlobalUnlock(h)
			if not u.SetClipboardData(fmt, h):
				k.GlobalFree(h)
		return True
	except Exception:
		log.debug("No se pudo restaurar el portapapeles", exc_info=True)
		return False
	finally:
		u.CloseClipboard()


def lastLines(text: str, n: int) -> list[str]:
	"""Las ``n`` últimas líneas no vacías (la última primero)."""
	lines = [line.rstrip() for line in (text or "").replace("\r\n", "\n").split("\n")]
	out = [line for line in reversed(lines) if line.strip()]
	return out[:n]


def newLines(old: str, new: str) -> list[str]:
	"""Líneas añadidas al final respecto a la lectura anterior."""
	oldLines = [line.rstrip() for line in (old or "").replace("\r\n", "\n").split("\n") if line.strip()]
	newLines_ = [line.rstrip() for line in (new or "").replace("\r\n", "\n").split("\n") if line.strip()]
	# Busca el final de la lectura anterior dentro de la nueva.
	if not oldLines:
		return newLines_
	# La última línea anterior suele ser el indicador, que luego crece con la orden escrita.
	tail = oldLines[-3:-1] if len(oldLines) >= 2 else oldLines
	for i in range(len(newLines_) - len(tail), -1, -1):
		if newLines_[i : i + len(tail)] == tail:
			return newLines_[i + len(tail) :]
	return newLines_[-20:]


class AppModule(BaseAppModule):
	scriptCategory = CAT

	def __init__(self, processID: int, appName: str | None = None) -> None:
		super().__init__(processID, appName)
		self._lastText = ""

	def _read(self, then) -> None:
		hwnd = terminalWindow()
		if not hwnd:
			speech.speakMessage(_("No hay ninguna terminal en primer plano"))
			return

		def done(text) -> None:
			if text is None:
				speech.speakMessage(_("No se pudo leer la terminal"))
				return
			then(text)

		readTerminal(hwnd, done)

	@script(description=_("Muestra todo el contenido de la terminal en una ventana navegable"), category=CAT, gesture="kb:tiresias+alt+shift+v")
	def script_viewTerminal(self, gesture) -> None:
		def show(text: str) -> None:
			self._lastText = text
			from .. import gui

			gui.showBrowseableMessage(text.rstrip(), _("Terminal"))

		self._read(show)

	@script(description=_("Lee las líneas nuevas de la terminal desde la última lectura"), category=CAT, gesture="kb:tiresias+alt+shift+n", speakOnDemand=True)
	def script_readNew(self, gesture) -> None:
		def speak(text: str) -> None:
			lines = newLines(self._lastText, text)
			self._lastText = text
			speech.speakText("\n".join(lines) if lines else _("Sin líneas nuevas"))

		self._read(speak)

	def readNthLast(self, n: int) -> None:
		def speak(text: str) -> None:
			self._lastText = text
			lines = lastLines(text, n)
			if len(lines) < n:
				speech.speakMessage(_("No hay tantas líneas"))
				return
			speech.cancelSpeech()
			speech.speakText(lines[n - 1])

		self._read(speak)


def _addLineScripts() -> None:
	for n in range(1, 11):
		key = str(n % 10)

		def scriptFunc(self, gesture, _n=n):
			self.readNthLast(_n)

		scriptFunc.__name__ = f"script_readLastLine{n}"
		desc = _("Lee la última línea de la terminal") if n == 1 else _("Lee la línea {n} contando desde el final de la terminal").format(n=n)
		decorated = script(description=desc, gesture=f"kb:tiresias+alt+{key}", category=CAT, speakOnDemand=True)(scriptFunc)
		setattr(AppModule, scriptFunc.__name__, decorated)
		AppModule._classGestures[f"kb:tiresias+alt+{key}"] = f"readLastLine{n}"  # type: ignore[attr-defined]


_addLineScripts()
