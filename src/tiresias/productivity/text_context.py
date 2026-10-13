"""Acceso uniforme al texto «donde está el cursor» (hilo del núcleo).

Lo usan el analizador de texto y los marcadores de texto. Hay dos casos:

- Modo exploración: el texto del búfer virtual y su cursor.
- Campo editable o documento con patrón Text (Bloc de notas, Word,
  WordPad, campos de los navegadores en modo foco, editores de código...):
  el texto completo del objeto con el foco y la posición del cursor del
  sistema, calculada en caracteres desde el principio.
"""

from __future__ import annotations

import re

from .. import api, textinfo
from ..log import getLogger
from ..objects.roles import Role, State

log = getLogger("productivity")

#: Máximo de caracteres que se leen de un documento.
MAX_CHARS = 400_000

_TEXT_ROLES = {Role.EDITABLETEXT, Role.DOCUMENT, Role.RICHEDIT, Role.TERMINAL, Role.EDITBAR}


def appNameOf(obj) -> str:
	try:
		app = obj.appModule
		return (app.appName or "") if app is not None else ""
	except Exception:
		return ""


def documentName() -> str:
	"""Título de la ventana en primer plano sin marcas de «modificado»."""
	fg = api.getForegroundObject()
	try:
		name = (fg.name or "") if fg is not None else ""
	except Exception:
		name = ""
	return normalizeTitle(name)


def normalizeTitle(name: str) -> str:
	"""Quita asteriscos y puntos de «sin guardar» que añaden los editores."""
	name = name.strip()
	name = re.sub(r"^[*•●]\s*", "", name)
	name = re.sub(r"\s*[*•●]$", "", name)
	name = re.sub(r"^\(\s*\*?\s*\)\s*", "", name)
	return name.strip()


class TextContext:
	"""Texto, cursor y forma de mover el cursor en el contexto actual."""

	kind = ""

	def __init__(self, obj, text: str, caret: int, appName: str, docName: str) -> None:
		self.obj = obj
		self.text = text
		self.caret = max(0, min(caret, len(text)))
		self.appName = appName
		self.docName = docName

	@property
	def key(self) -> str:
		"""Clave del documento para guardar marcadores."""
		return f"{self.appName}|{self.docName}"

	def lineBounds(self, offset: int) -> tuple[int, int]:
		text = self.text
		offset = max(0, min(offset, len(text)))
		start = text.rfind("\n", 0, offset) + 1
		end = text.find("\n", offset)
		return start, len(text) if end == -1 else end

	def moveTo(self, offset: int, speakLine: bool = True) -> None:
		raise NotImplementedError

	def formatRuns(self, limit: int = 3000) -> list:
		"""Tramos de formato (solo si el texto los expone)."""
		return []


class BrowseContext(TextContext):
	kind = "browse"

	def __init__(self, ti) -> None:
		buf = ti.buffer
		text = buf.text if buf is not None else ""
		super().__init__(ti, text[:MAX_CHARS], ti.caret, appNameOf(ti.rootObject) if getattr(ti, "rootObject", None) else "", "")
		try:
			self.docName = str(ti._documentKey())
		except Exception:
			self.docName = documentName()

	@property
	def key(self) -> str:
		return f"{self.appName}|web|{self.docName}"

	def moveTo(self, offset: int, speakLine: bool = True) -> None:
		from ..textinfo import UNIT_LINE

		self.obj._moveCaret(offset, UNIT_LINE if speakLine else None)


class EditContext(TextContext):
	kind = "edit"

	def moveTo(self, offset: int, speakLine: bool = True) -> None:
		from .. import presentation, review, speech

		info = self.obj.makeTextInfo(textinfo.POSITION_FIRST)
		if offset > 0:
			info.move(textinfo.UNIT_CHARACTER, offset)
		info.updateCaret()
		try:
			review.handleCaretMove(self.obj, info)
		except Exception:
			log.debug("No se pudo actualizar la revisión", exc_info=True)
		if speakLine:
			speech.cancelSpeech()
			line = info.copy()
			line.expand(textinfo.UNIT_LINE)
			presentation.speakTextInfo(line, textinfo.UNIT_LINE, reason=presentation.Reason.CARET)

	def formatRuns(self, limit: int = 3000) -> list:
		"""Tramos de formato con fuente y tamaño (patrón Text de UIA)."""
		from .text_analyzer import FormatRun

		info = self.obj.makeTextInfo(textinfo.POSITION_FIRST)
		if not hasattr(info, "getFormatInfo") or type(info).__name__ != "UIATextInfo":
			return []
		runs: list = []
		pos = 0
		for _i in range(limit):
			run = info.copy()
			run.expand(textinfo.UNIT_FORMAT)
			chunk = run.text
			if not chunk:
				break
			fmt = run.getFormatInfo({"fontName", "fontSize"})
			runs.append(FormatRun(pos, pos + len(chunk), fmt.get("fontName"), fmt.get("fontSize")))
			pos += len(chunk)
			if pos >= len(self.text):
				break
			nxt = run.copy()
			nxt.collapse(end=True)
			if nxt.compareEndPoints(info, "startToStart") <= 0:
				# Sin avance: el proveedor no separa bien los tramos.
				break
			info = nxt
		return runs


def isTextObject(obj) -> bool:
	if obj is None or getattr(obj, "TextInfo", None) is None:
		return False
	try:
		states = obj.states
		if State.PROTECTED in states:
			return False
		return obj.role in _TEXT_ROLES or State.EDITABLE in states or State.MULTILINE in states
	except Exception:
		return False


def get() -> TextContext | None:
	"""Contexto del cursor actual o ``None`` si no hay texto."""
	caretObj = api.getCaretObject()
	focus = api.getFocusObject()
	if caretObj is not None and caretObj is not focus and getattr(caretObj, "buffer", None) is not None:
		try:
			return BrowseContext(caretObj)
		except Exception:
			log.debug("Sin contexto de modo exploración", exc_info=True)
			return None
	if not isTextObject(focus):
		return None
	try:
		allInfo = focus.makeTextInfo(textinfo.POSITION_ALL)
		text = allInfo.text or ""
		caretInfo = focus.makeTextInfo(textinfo.POSITION_CARET)
		before = focus.makeTextInfo(textinfo.POSITION_FIRST)
		before.setEndPoint(caretInfo, "endToStart")
		caret = len(before.text or "")
	except Exception:
		log.debug("No se pudo leer el texto del foco", exc_info=True)
		return None
	return EditContext(focus, text[:MAX_CHARS], caret, appNameOf(focus), documentName())
