"""Consolas y terminales: lectura del texto nuevo, cursor y eco protegido.

- :class:`Terminal` se mezcla con los objetos de consola (conhost con UIA o
  con la API de consola, Windows Terminal, terminales de otras aplicaciones).
  Su rol es ``Role.TERMINAL``.
- Al crear el objeto **no** se lee la pantalla: la última pantalla conocida se
  guarda por ventana en :data:`_snapshots` y se toma al recibir el foco o con
  el primer cambio.
- El texto nuevo se calcula con :func:`computeNewText`: diferencias por líneas
  y, dentro de cada línea modificada, por caracteres (así una barra de
  progreso que cambia «45 %» por «46 %» solo lee lo nuevo). Las líneas solo
  con espacios cuentan como vacías (#17689). Si llega muchísimo texto de golpe
  se leen solo las últimas líneas (``terminal.maxLinesPerUpdate``) para no
  colgar la voz (#20902).
- **Cola de caracteres y contraseñas**: lo que se escribe en una consola no se
  anuncia enseguida, sino cuando aparece en pantalla. Si no aparece (una
  contraseña), no se lee nunca. Con la opción ``terminal.speakPasswords`` se
  vuelve al eco inmediato.
- :class:`ConsoleTextInfo` permite revisar y mover el cursor por el búfer
  visible de la consola clásica con la API de consola.
"""

from __future__ import annotations

import difflib
import time

from .. import queue_handler, speech, textinfo
from ..config import conf
from ..log import getLogger
from .behaviors import EditableText
from .roles import Role

log = getLogger("terminal")

#: Última pantalla conocida de cada terminal: clave -> líneas.
_snapshots: dict[tuple, list[str]] = {}
#: Caracteres escritos que todavía no han aparecido en pantalla: (instante, carácter).
_typedQueue: list[tuple[float, str]] = []
_typedQueueObj = None
_TYPED_TIMEOUT = 1.5
#: Procesos de consola que anuncian su salida con notificaciones UIA (Windows Terminal).
notifyingTerminals: set[int] = set()


# ------------------------------------------------------------------ diferencias
def _lineDiff(old: str, new: str) -> str:
	"""Parte nueva de una línea que ha cambiado."""
	if not old.strip():
		return new
	if new.startswith(old):
		return new[len(old) :]
	matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
	spans: list[list[int]] = []
	for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
		if tag not in ("insert", "replace"):
			continue
		# Se amplía a palabras completas: «45%» → «46%» se lee «46%», no «6».
		while j1 > 0 and not new[j1 - 1].isspace():
			j1 -= 1
		while j2 < len(new) and not new[j2].isspace():
			j2 += 1
		if spans and j1 <= spans[-1][1]:
			spans[-1][1] = max(spans[-1][1], j2)
		else:
			spans.append([j1, j2])
	if not spans:
		return ""
	changed = sum(e - s for s, e in spans)
	# Si cambia casi toda la línea, se lee entera (se entiende mejor).
	if changed > 0.6 * max(1, len(new.strip())):
		return new
	return " ".join(new[s:e].strip() for s, e in spans if new[s:e].strip())


def computeNewText(old: list[str], new: list[str], mode: str = "characters") -> list[str]:
	"""Líneas (o fragmentos) nuevas de ``new`` respecto a ``old``."""
	old = [line.rstrip() for line in old]
	new = [line.rstrip() for line in new]
	matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
	out: list[str] = []
	for tag, i1, i2, j1, j2 in matcher.get_opcodes():
		if tag == "insert":
			out.extend(new[j1:j2])
		elif tag == "replace":
			if mode == "characters" and i2 - i1 == j2 - j1:
				for a, b in zip(old[i1:i2], new[j1:j2], strict=False):
					out.append(_lineDiff(a, b))
			else:
				out.extend(new[j1:j2])
	return [line for line in out if line.strip()]


def limitLines(lines: list[str], maxLines: int) -> list[str]:
	"""Deja como mucho ``maxLines`` líneas (las últimas) y 20000 caracteres."""
	if maxLines > 0 and len(lines) > maxLines:
		lines = lines[-maxLines:]
	total = 0
	out: list[str] = []
	for line in reversed(lines):
		total += len(line)
		if total > 20000:
			break
		out.append(line)
	return list(reversed(out))


# ------------------------------------------------------------------ cola de caracteres
def queueTypedCharacter(obj, ch: str) -> None:
	global _typedQueueObj
	now = time.monotonic()
	_purgeTyped(now)
	_typedQueue.append((now, ch))
	_typedQueueObj = obj


def _purgeTyped(now: float) -> None:
	while _typedQueue and now - _typedQueue[0][0] > _TYPED_TIMEOUT:
		_typedQueue.pop(0)


def consumeTypedCharacters(lines: list[str]) -> list[str]:
	"""Anuncia los caracteres escritos que aparecen en ``lines`` y los quita.

	Devuelve las líneas que quedan por leer.
	"""
	from .. import typing_echo

	_purgeTyped(time.monotonic())
	if not _typedQueue or not lines:
		return lines
	typed = "".join(ch for _t, ch in _typedQueue)
	joined = "".join(line.strip() for line in lines)
	if not joined:
		return lines
	# Lo nuevo es el eco de lo escrito (en orden): se anuncia como eco de teclado.
	if not typed.startswith(joined):
		return lines
	obj = _typedQueueObj
	del _typedQueue[: len(joined)]
	for ch in joined:
		typing_echo.onTypedCharacter(obj, ch)
	return []


# ------------------------------------------------------------------ texto de la consola clásica
class ConsoleTextInfo(textinfo.OffsetsTextInfo):
	"""Texto visible de una consola clásica leído con la API de consola."""

	def _screen(self):
		cached = self.__dict__.get("_screenCache")
		if cached is None:
			from .. import console_reader

			cached = console_reader.readScreen(self.obj.processID)
			self.__dict__["_screenCache"] = cached
		return cached

	def _getStoryText(self) -> str:
		screen = self._screen()
		if screen is None:
			return ""
		return "\n".join(screen.lines) + "\n"

	def _getCaretOffset(self) -> int:
		screen = self._screen()
		if screen is None or screen.cursor[1] < 0:
			return 0
		col, row = screen.cursor
		offset = sum(len(line) + 1 for line in screen.lines[:row])
		line = screen.lines[row] if row < len(screen.lines) else ""
		return offset + min(col, len(line))


# ------------------------------------------------------------------ comportamiento
class Terminal(EditableText):
	"""Consolas: anuncia el texto nuevo y protege lo escrito que no se muestra."""

	announceNewLineText = False

	def _get_role(self) -> Role:
		return Role.TERMINAL

	def _snapshotKey(self) -> tuple:
		try:
			return (self.processID, self.windowHandle)
		except Exception:
			return (0, 0)

	def _usesConsoleAPI(self) -> bool:
		return not conf["uia"]["preferUIAForConsoles"] and self.windowClassName == "ConsoleWindowClass"

	def _visibleLines(self) -> list[str]:
		if self._usesConsoleAPI() or not hasattr(self, "textPattern"):
			from .. import console_reader

			if self.windowClassName == "ConsoleWindowClass":
				lines = console_reader.readVisibleLines(self.processID)
				if lines is not None:
					return lines
		pattern = getattr(self, "textPattern", None)
		if pattern is None:
			return []
		try:
			ranges = pattern.GetVisibleRanges()
			text = "".join(ranges.GetElement(i).GetText(-1) for i in range(ranges.Length))
		except Exception:
			return []
		return [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]

	def _get_TextInfo(self):
		if self.windowClassName == "ConsoleWindowClass" and (self._usesConsoleAPI() or not hasattr(self, "textPattern")):
			return ConsoleTextInfo
		return super()._get_TextInfo()

	def event_gainFocus(self) -> None:
		key = self._snapshotKey()
		if key not in _snapshots:
			_snapshots[key] = self._visibleLines()
		super().event_gainFocus()

	def event_textChange(self) -> None:
		timers = _pendingTimers
		key = self._snapshotKey()
		old = timers.get(key)
		if old is not None:
			# Agrupa ráfagas, pero sin esperar indefinidamente con salida continua.
			first, timerId = old
			if time.monotonic() - first < 0.3:
				queue_handler.cancelCallLater(timerId)
				timers[key] = (first, queue_handler.callLater(60, self._reportNewText))
			return
		timers[key] = (time.monotonic(), queue_handler.callLater(60, self._reportNewText))

	def _reportNewText(self) -> None:
		key = self._snapshotKey()
		_pendingTimers.pop(key, None)
		new = self._visibleLines()
		old = _snapshots.get(key)
		_snapshots[key] = new
		if len(_snapshots) > 50:
			for k in list(_snapshots)[:-25]:
				_snapshots.pop(k, None)
		if old is None:
			return
		if not conf["presentation"]["reportDynamicContentChanges"] or self.processID in notifyingTerminals:
			# Sin lectura automática, o la consola ya anuncia su salida con
			# notificaciones: solo se actualiza la referencia.
			return
		added = computeNewText(old, new, conf["terminal"]["diffAlgorithm"])
		self._speakNewText(added)

	def _speakNewText(self, added: list[str]) -> None:
		if not added:
			return
		if not conf["terminal"]["speakPasswords"]:
			added = consumeTypedCharacters(added)
		else:
			from .. import typing_echo

			if len(added) == 1 and typing_echo.recentlyTyped(added[0]):
				return
		added = limitLines(added, conf["terminal"]["maxLinesPerUpdate"])
		if added:
			speech.speakText("\n".join(added))

	def event_typedCharacter(self, ch: str) -> None:
		if conf["terminal"]["speakPasswords"] or not ch or not ch.isprintable() or ch.isspace():
			super().event_typedCharacter(ch)
			return
		# Se anuncia cuando la consola lo muestre (si no lo muestra, es una contraseña).
		queueTypedCharacter(self, ch)

	def event_notification(self, displayString: str = "", activityId: str = "", **kwargs) -> None:
		"""Windows Terminal anuncia el texto nuevo con notificaciones UIA.

		Si la consola las usa, se leen solo ellas y se deja de comparar líneas
		visibles; así el mismo texto no se lee dos veces (notificación + diff).
		"""
		from .. import api

		try:
			notifyingTerminals.add(self.processID)
		except Exception:
			pass
		focus = api.getFocusObject()
		try:
			if focus is None or focus.processID != self.processID:
				# Consolas en segundo plano: no se leen.
				return
		except Exception:
			return
		if not conf["presentation"]["reportDynamicContentChanges"] or not displayString:
			return
		lines = [line for line in displayString.splitlines() if line.strip()]
		self._speakNewText(lines)


#: Temporizadores de lectura pendientes por terminal: clave -> (primer evento, id).
_pendingTimers: dict[tuple, tuple[float, int]] = {}
