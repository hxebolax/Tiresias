"""Historial del portapapeles y avisos al cortar, copiar y pegar.

- Cada cambio del portapapeles se guarda en el historial y, si la opción
  ``clipboard.announceCopy`` está activa, se anuncia con un extracto.
- Con ``clipboard.announceCutCopyPaste`` (#19042) se distingue la tecla que
  lo provocó: Control+X (o Mayúsculas+Suprimir) dice «Cortado», Control+C (o
  Control+Insertar) «Copiado» y Control+V (o Mayúsculas+Insertar) «Pegado» en
  los campos de edición. Con ``clipboard.announcePastedText`` (#10709) se lee
  además el texto pegado.
"""

from __future__ import annotations

import json
import os
import time

from . import paths, queue_handler, speech, winapi
from .config import conf, registerDefaults
from .i18n import _
from .log import getLogger

log = getLogger("clipboard")

# Separador al añadir texto al portapapeles: newline, blankLine, space o none.
registerDefaults("clipboard", {"appendSeparator": "newline"})

history: list[tuple[float, str]] = []
_lastSeq = 0
_ignoreSeq: set[int] = set()
_timer: int | None = None

#: Última tecla de cortar o copiar pulsada: (acción, instante).
_pendingAction: tuple[str, float] | None = None
#: Tiempo durante el que un cambio del portapapeles se atribuye a la tecla.
ACTION_WINDOW = 1.5
#: Caracteres del texto pegado que se leen como máximo.
PASTE_READ_LIMIT = 500

#: Códigos de tecla virtual.
_VK_C = 0x43
_VK_V = 0x56
_VK_X = 0x58
_VK_INSERT = 0x2D
_VK_DELETE = 0x2E


def _file() -> str:
	return os.path.join(paths.cacheDir(), "clipboard_history.json")


# ------------------------------------------------------------------ contenido protegido
#: Formatos con los que los gestores de contraseñas (KeePass, Bitwarden,
#: 1Password...) piden que nadie guarde ni muestre lo copiado.
SENSITIVE_FORMATS = ("ExcludeClipboardContentFromMonitorProcessing", "Clipboard Viewer Ignore")
#: Formato con un DWORD: 0 = no incluir en el historial del portapapeles.
HISTORY_FORMAT = "CanIncludeInClipboardHistory"
_formatIds: dict[str, int] = {}
_u32 = None


def _user32():
	global _u32
	if _u32 is None:
		import ctypes
		from ctypes import wintypes

		u = ctypes.WinDLL("user32", use_last_error=True)
		u.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
		u.RegisterClipboardFormatW.restype = wintypes.UINT
		u.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
		u.IsClipboardFormatAvailable.restype = wintypes.BOOL
		u.OpenClipboard.argtypes = [wintypes.HWND]
		u.OpenClipboard.restype = wintypes.BOOL
		u.GetClipboardData.argtypes = [wintypes.UINT]
		u.GetClipboardData.restype = wintypes.HANDLE
		_u32 = u
	return _u32


def _formatId(name: str) -> int:
	fid = _formatIds.get(name)
	if fid is None:
		fid = int(_user32().RegisterClipboardFormatW(name) or 0)
		_formatIds[name] = fid
	return fid


def _readDword(fid: int) -> int | None:
	import ctypes

	u = _user32()
	for _attempt in range(5):
		if u.OpenClipboard(None):
			break
		winapi.kernel32.Sleep(20)
	else:
		return None
	try:
		h = u.GetClipboardData(fid)
		if not h:
			return None
		p = winapi.kernel32.GlobalLock(h)
		if not p:
			return None
		try:
			return ctypes.c_uint32.from_address(p).value
		finally:
			winapi.kernel32.GlobalUnlock(h)
	finally:
		winapi.user32.CloseClipboard()


def isSensitiveContent() -> bool:
	"""``True`` si lo copiado pide no guardarse ni mostrarse (contraseñas)."""
	try:
		u = _user32()
		for name in SENSITIVE_FORMATS:
			fid = _formatId(name)
			if fid and u.IsClipboardFormatAvailable(fid):
				return True
		fid = _formatId(HISTORY_FORMAT)
		if fid and u.IsClipboardFormatAvailable(fid):
			# Si no se puede leer el valor, ante la duda se trata como protegido.
			return _readDword(fid) != 1
	except Exception:
		log.debug("No se pudo comprobar si el portapapeles está protegido", exc_info=True)
	return False


def load() -> None:
	if not conf["clipboard"]["persistHistory"]:
		return
	try:
		with open(_file(), encoding="utf-8") as f:
			data = json.load(f)
		history[:] = [(float(t), str(s)) for t, s in data][-conf["clipboard"]["historySize"] :]
	except (OSError, ValueError):
		pass


def save() -> None:
	if not conf["clipboard"]["persistHistory"]:
		try:
			os.remove(_file())
		except OSError:
			pass
		return
	try:
		with open(_file(), "w", encoding="utf-8") as f:
			json.dump(history, f, ensure_ascii=False)
	except OSError:
		pass


def ignoreNextChange() -> None:
	"""Tiresias va a escribir en el portapapeles: no anunciarlo."""
	_ignoreSeq.add(winapi.user32.GetClipboardSequenceNumber() + 1)


def cancelIgnore() -> None:
	"""La escritura de Tiresias falló: el próximo cambio sí se anuncia."""
	_ignoreSeq.clear()


# ------------------------------------------------------------------ teclas
def classifyKey(vk: int, modifiers: frozenset | set) -> str | None:
	"""Acción de portapapeles de una combinación: ``cut``, ``copy``, ``paste`` o ``None``."""
	mods = set(modifiers)
	if mods == {"control"}:
		return {_VK_X: "cut", _VK_C: "copy", _VK_V: "paste", _VK_INSERT: "copy"}.get(vk)
	if mods == {"shift"}:
		return {_VK_DELETE: "cut", _VK_INSERT: "paste"}.get(vk)
	return None


def _onGesture(gesture) -> bool:
	"""Se llama en el hilo de ganchos para cada tecla: debe ser muy rápido."""
	try:
		action = classifyKey(getattr(gesture, "vk", 0), getattr(gesture, "modifiers", frozenset()))
	except Exception:
		action = None
	if action is not None:
		queue_handler.queueFunction(_onClipboardKey, action)
	return True


def _focusIsEditable() -> bool:
	from . import api
	from .objects.roles import Role, State

	focus = api.getFocusObject()
	if focus is None:
		return False
	try:
		role = focus.role
		states = focus.states
	except Exception:
		return False
	return role in (Role.EDITABLETEXT, Role.RICHEDIT, Role.TERMINAL, Role.COMBOBOX) or (role == Role.DOCUMENT and State.EDITABLE in states) or State.EDITABLE in states


def _onClipboardKey(action: str) -> None:
	global _pendingAction
	if not conf["clipboard"]["announceCutCopyPaste"] and not (action == "paste" and conf["clipboard"]["announcePastedText"]):
		return
	if action == "paste":
		queue_handler.callLater(120, _announcePaste)
		return
	_pendingAction = (action, time.monotonic())
	# Se comprueba enseguida (sin esperar al sondeo) para que el aviso sea inmediato.
	queue_handler.callLater(150, _checkNow)


def _announcePaste() -> None:
	cb = conf["clipboard"]
	if not _focusIsEditable():
		return
	# Contraseña de un gestor: se dice «Pegado», nunca el texto.
	text = "" if isSensitiveContent() else (winapi.getClipboardText() or "")
	parts: list[str] = []
	if cb["announceCutCopyPaste"]:
		parts.append(_("Pegado"))
	if cb["announcePastedText"] and text.strip():
		snippet = " ".join(text.split())
		if len(snippet) > PASTE_READ_LIMIT:
			snippet = snippet[:PASTE_READ_LIMIT] + " " + _("y {n} caracteres más").format(n=len(snippet) - PASTE_READ_LIMIT)
		parts.append(snippet)
	if len(parts) > 1 or (parts and not cb["announceCutCopyPaste"]):
		speech.speakText(" ".join(parts))
	elif parts:
		speech.speakMessage(parts[0])


def _takeAction() -> str | None:
	global _pendingAction
	pending = _pendingAction
	_pendingAction = None
	if pending is None or time.monotonic() - pending[1] > ACTION_WINDOW:
		return None
	return pending[0]


def changeMessage(action: str | None, text: str) -> str:
	"""Mensaje para un cambio del portapapeles provocado por ``action``."""
	preview = " ".join(text.split())[:60]
	if action == "cut":
		return _("Cortado: {text}").format(text=preview)
	return _("Copiado: {text}").format(text=preview)


def _checkNow() -> None:
	try:
		_check()
	except Exception:
		log.debug("Error leyendo el portapapeles", exc_info=True)


def _check() -> None:
	global _lastSeq
	seq = winapi.user32.GetClipboardSequenceNumber()
	if seq == _lastSeq:
		return
	previous, _lastSeq = _lastSeq, seq
	# Lo que un gestor de contraseñas marca como protegido no se lee, ni se
	# guarda en el historial, ni se anuncia (solo «Copiado» si fue con la tecla).
	text = None if isSensitiveContent() else winapi.getClipboardText()
	# Cambio hecho por Tiresias: el número de secuencia puede avanzar más de
	# uno por escritura (vaciar y escribir) y, si la escritura falló, la marca
	# no debe quedarse para siempre tapando un cambio posterior.
	ours = any(previous < s <= seq for s in _ignoreSeq)
	_ignoreSeq.difference_update({s for s in _ignoreSeq if s <= seq})
	if ours:
		_clearPendingAction()
		if text and conf["clipboard"]["historyEnabled"] and (not history or history[-1][1] != text):
			history.append((time.time(), text))
			del history[: -conf["clipboard"]["historySize"]]
		return
	action = _takeAction() if conf["clipboard"]["announceCutCopyPaste"] else None
	if not text:
		if action is not None and conf["clipboard"]["announceCopy"]:
			# Se copió algo que no es texto (archivos, imágenes...).
			speech.speakMessage(_("Cortado") if action == "cut" else _("Copiado"))
		return
	isNew = not history or history[-1][1] != text
	if isNew and conf["clipboard"]["historyEnabled"]:
		history.append((time.time(), text))
		del history[: -conf["clipboard"]["historySize"]]
	if conf["clipboard"]["announceCopy"] and (isNew or action is not None):
		speech.speakMessage(changeMessage(action, text))


def _clearPendingAction() -> None:
	global _pendingAction
	_pendingAction = None


def _poll() -> None:
	global _timer
	_timer = None
	try:
		_check()
	except Exception:
		log.debug("Error leyendo el portapapeles", exc_info=True)
	_timer = queue_handler.callLater(400, _poll)


def copyEntry(index: int) -> None:
	if 0 <= index < len(history):
		ignoreNextChange()
		winapi.setClipboardText(history[index][1])


# ------------------------------------------------------------------ añadir y contenido
APPEND_SEPARATORS = {"newline": "\r\n", "blankLine": "\r\n\r\n", "space": " ", "none": ""}


def joinForAppend(current: str, text: str, separator: str) -> str:
	"""Texto resultante de añadir ``text`` al final de ``current``."""
	if not current:
		return text
	return current + APPEND_SEPARATORS.get(separator, "\r\n") + text


def appendText(text: str) -> bool:
	"""Añade ``text`` al final del texto del portapapeles (acumulativo)."""
	if not text:
		speech.speakMessage(_("No hay texto que añadir"))
		return False
	current = winapi.getClipboardText() or ""
	ignoreNextChange()
	if not winapi.setClipboardText(joinForAppend(current, text, conf["clipboard"]["appendSeparator"])):
		speech.speakMessage(_("No se pudo escribir en el portapapeles"))
		return False
	preview = " ".join(text.split())[:60]
	speech.speakMessage(_("Añadido al portapapeles: {text}").format(text=preview))
	return True


def describeContents() -> str:
	"""Qué hay en el portapapeles: texto, imagen o archivos (#7414)."""
	from . import imaging

	files = imaging.getClipboardFiles()
	if files:
		names = ", ".join(os.path.basename(f) for f in files[:5])
		more = len(files) - 5
		msg = _("{n} archivos: {names}").format(n=len(files), names=names) if len(files) > 1 else _("Archivo: {names}").format(names=names)
		if more > 0:
			msg += " " + _("y {n} más").format(n=more)
		return msg
	if isSensitiveContent():
		return _("Texto protegido (por ejemplo, una contraseña copiada desde un gestor de contraseñas)")
	text = winapi.getClipboardText()
	if text:
		return _("Texto de {n} caracteres: {preview}").format(n=len(text), preview=" ".join(text.split())[:200])
	if winapi.user32.IsClipboardFormatAvailable(imaging.CF_DIB):
		# Solo la cabecera: convertir la imagen entera bloquearía el hilo del núcleo.
		size = imaging.clipboardImageSize()
		if size is not None:
			return _("Imagen de {w} por {h} píxeles").format(w=size[0], h=size[1])
		return _("Imagen")
	return _("El portapapeles está vacío")


def initialize() -> None:
	global _lastSeq
	load()
	_lastSeq = winapi.user32.GetClipboardSequenceNumber()
	queue_handler.callLater(400, _poll)
	from .input import core as inputCore

	inputCore.decide_executeGesture.register(_onGesture)


def terminate() -> None:
	from .input import core as inputCore

	inputCore.decide_executeGesture.unregister(_onGesture)
	if _timer is not None:
		queue_handler.cancelCallLater(_timer)
	save()


winapi.user32.GetClipboardSequenceNumber.restype = winapi.wintypes.DWORD
