"""Longitud máxima y caracteres restantes de los campos de edición (foros 1.17, #7910).

- :func:`reportRemaining`: orden que dice cuántos caracteres hay escritos y
  cuántos quedan en el campo con el foco.
- :func:`scheduleCheck`: tras cada carácter escrito, avisa al acercarse al
  límite (``objects.maxLengthWarningThreshold``) y al llegar a él, según
  ``objects.maxLengthWarning``.

La longitud máxima la da el objeto (``maxLength``: ``maxlength`` de ARIA o de
IA2, ``EM_GETLIMITTEXT``); en Chrome y Edge se lee del atributo IA2
``maxlength`` porque UIA no lo publica.
"""

from __future__ import annotations

from typing import Any

from .. import queue_handler, speech, textinfo
from ..config import conf
from ..i18n import _, ngettext
from ..log import getLogger

log = getLogger("textLimits")

#: Retraso (ms) para leer el campo tras escribir (la aplicación tiene que procesar la tecla).
CHECK_DELAY_MS = 60

#: Últimos caracteres restantes avisados por campo: {clave: restantes}.
_lastWarned: dict[Any, int] = {}
_pendingTimer: int | None = None


def _key(obj: Any) -> Any:
	try:
		rid = getattr(obj, "runtimeId", None)
		if rid:
			return tuple(rid)
	except Exception:
		pass
	try:
		return (obj.processID, obj.windowHandle, obj.role)
	except Exception:
		return id(obj)


def textLength(obj: Any) -> int | None:
	"""Número de caracteres escritos en el campo (``None`` si no se puede saber)."""
	text = None
	try:
		if hasattr(obj, "_getCaretInfo"):
			# Campos con cursor (patrón Text, mensajes EM_* o IA2): el texto completo.
			info = obj.makeTextInfo(textinfo.POSITION_ALL)
			# Chrome devuelve U+FFFC en los campos vacíos: no es texto escrito.
			text = info.text.replace("￼", "")
	except Exception:
		text = None
	if text is None:
		try:
			text = obj.value
		except Exception:
			text = None
	if text is None:
		return None
	# El salto de línea final que añaden algunos controles no es texto escrito.
	if text.endswith("\r\n"):
		text = text[:-2]
	elif text.endswith(("\n", "\r")):
		text = text[:-1]
	return len(text)


def maxLengthOf(obj: Any) -> int | None:
	try:
		val = obj.maxLength
	except Exception:
		return None
	return int(val) if val else None


def remainingText(typed: int | None, maxLen: int | None) -> str:
	"""Mensaje de la orden: escritos, máximo y restantes."""
	if typed is None:
		return _("No se puede saber cuánto texto tiene el campo")
	written = ngettext("{n} carácter escrito", "{n} caracteres escritos", typed).format(n=typed)
	if not maxLen:
		return _("{written}, sin límite de longitud").format(written=written)
	left = max(0, maxLen - typed)
	remaining = ngettext("queda {n}", "quedan {n}", left).format(n=left) if left else _("límite alcanzado")
	return _("{written} de {max}, {remaining}").format(written=written, max=maxLen, remaining=remaining)


def isEditable(obj: Any) -> bool:
	from .roles import Role, State

	try:
		role = obj.role
		states = obj.states
	except Exception:
		return False
	if role in (Role.EDITABLETEXT, Role.PASSWORDEDIT, Role.RICHEDIT):
		return True
	if role in (Role.COMBOBOX, Role.DOCUMENT) and State.EDITABLE in states:
		return True
	return False


def reportRemaining(obj: Any) -> None:
	"""Dice los caracteres escritos y los que quedan en ``obj`` (foros 1.17)."""
	if obj is None or not isEditable(obj):
		speech.speakMessage(_("No hay ningún campo de edición con el foco"))
		return
	speech.speakMessage(remainingText(textLength(obj), maxLengthOf(obj)))


def warningFor(remaining: int, last: int | None, mode: str, threshold: int) -> str | None:
	"""Aviso automático (o ``None``) para ``remaining`` caracteres restantes.

	``last`` es lo que quedaba en el aviso anterior de ese campo.
	"""
	if mode == "off" or remaining > threshold:
		return None
	if remaining <= 0:
		# Cada intento de escribir con el campo lleno se avisa (la tecla no entró).
		return _("límite de caracteres alcanzado")
	if mode == "countdown":
		return ngettext("queda {n}", "quedan {n}", remaining).format(n=remaining) if remaining != last else None
	# «threshold»: solo al cruzar el umbral (o al volver a cruzarlo tras borrar).
	if last is None or last > threshold:
		return ngettext("queda {n} carácter", "quedan {n} caracteres", remaining).format(n=remaining)
	return None


def _check(obj: Any) -> None:
	global _pendingTimer
	_pendingTimer = None
	o = conf["objects"]
	mode = o["maxLengthWarning"]
	if mode == "off":
		return
	maxLen = maxLengthOf(obj)
	if not maxLen:
		return
	typed = textLength(obj)
	if typed is None:
		return
	remaining = maxLen - typed
	key = _key(obj)
	last = _lastWarned.get(key)
	msg = warningFor(remaining, last, mode, max(1, int(o["maxLengthWarningThreshold"])))
	if len(_lastWarned) > 50:
		_lastWarned.clear()
	_lastWarned[key] = remaining
	if msg:
		speech.speakMessage(msg)


def scheduleCheck(obj: Any) -> None:
	"""Comprueba el límite poco después de escribir un carácter."""
	global _pendingTimer
	if conf["objects"]["maxLengthWarning"] == "off":
		return
	if _pendingTimer is not None:
		queue_handler.cancelCallLater(_pendingTimer)
	_pendingTimer = queue_handler.callLater(CHECK_DELAY_MS, _check, obj)


def forget(obj: Any) -> None:
	"""Olvida el último aviso de un campo (al recibir el foco se empieza de cero)."""
	_lastWarned.pop(_key(obj), None)
