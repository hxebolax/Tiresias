"""Abstracción de rangos de texto (TextInfo).

Un :class:`TextInfo` representa un rango dentro del texto de un objeto
(campo de edición, documento, consola...). Se usa para leer por caracteres,
palabras, líneas y párrafos, mover el cursor, seleccionar y leer de forma
continua.

Implementaciones:

- :class:`OffsetsTextInfo`: texto en memoria basado en desplazamientos.
- ``tiresias.objects.uia_text.UIATextInfo``: patrón Text de UI Automation.
"""

from __future__ import annotations

import re
from typing import Any

UNIT_CHARACTER = "character"
UNIT_WORD = "word"
UNIT_LINE = "line"
UNIT_SENTENCE = "sentence"
UNIT_PARAGRAPH = "paragraph"
UNIT_PAGE = "page"
UNIT_STORY = "story"
UNIT_FORMAT = "format"

POSITION_FIRST = "first"
POSITION_LAST = "last"
POSITION_CARET = "caret"
POSITION_SELECTION = "selection"
POSITION_ALL = "all"


class Point:
	def __init__(self, x: int, y: int) -> None:
		self.x = x
		self.y = y


class Bookmark:
	def __init__(self, infoClass: type, data: Any) -> None:
		self.infoClass = infoClass
		self.data = data

	def __eq__(self, other: object) -> bool:
		return isinstance(other, Bookmark) and self.infoClass is other.infoClass and self.data == other.data

	def __hash__(self) -> int:
		return hash((self.infoClass, repr(self.data)))


class TextInfo:
	"""Clase base abstracta."""

	def __init__(self, obj: Any, position: Any) -> None:
		self.obj = obj
		self.basePosition = position

	# --- obligatorios ---
	def copy(self) -> "TextInfo":
		raise NotImplementedError

	@property
	def text(self) -> str:
		raise NotImplementedError

	def expand(self, unit: str) -> None:
		raise NotImplementedError

	def collapse(self, end: bool = False) -> None:
		raise NotImplementedError

	def move(self, unit: str, direction: int, endPoint: str | None = None) -> int:
		raise NotImplementedError

	def compareEndPoints(self, other: "TextInfo", which: str) -> int:
		raise NotImplementedError

	def setEndPoint(self, other: "TextInfo", which: str) -> None:
		raise NotImplementedError

	@property
	def isCollapsed(self) -> bool:
		raise NotImplementedError

	@property
	def bookmark(self) -> Bookmark:
		raise NotImplementedError

	# --- opcionales ---
	def updateCaret(self) -> None:
		raise NotImplementedError

	def updateSelection(self) -> None:
		raise NotImplementedError

	@property
	def pointAtStart(self) -> Point | None:
		return None

	@property
	def boundingRects(self) -> list[tuple[int, int, int, int]]:
		return []

	def getFormatInfo(self, keys: set[str] | None = None) -> dict:
		"""Información de formato del inicio del rango (fuente, estilo...).

		``keys`` limita los atributos pedidos (como en las subclases que lo usan)."""
		return {}

	def getControlFields(self) -> list:
		"""Objetos contenedores del rango (enlace, encabezado...)."""
		return []

	def getEnclosingObject(self) -> Any:
		return None

	def activate(self) -> None:
		"""Activa (pulsa) lo que haya en el rango."""

	def scrollIntoView(self) -> None:
		pass

	@property
	def lineNumber(self) -> int | None:
		return None

	def __eq__(self, other: object) -> bool:
		if not isinstance(other, TextInfo) or type(self) is not type(other):
			return False
		try:
			return self.compareEndPoints(other, "startToStart") == 0 and self.compareEndPoints(other, "endToEnd") == 0
		except Exception:
			return False

	__hash__ = None  # type: ignore[assignment]


_wordRe = re.compile(r"\w+|[^\w\s]+|\s+", re.UNICODE)


def findWordBoundaries(text: str, offset: int) -> tuple[int, int]:
	"""Límites de la palabra que contiene ``offset`` (incluye espacios finales)."""
	if not text:
		return 0, 0
	offset = max(0, min(offset, len(text) - 1))
	# Rev. 10.11 (A5): se empieza en el principio de la línea (con los espacios
	# que la preceden), no en el del texto: en documentos grandes cada palabra
	# recorría todo lo anterior. Los trozos que salen son los mismos.
	base = text.rfind("\n", 0, offset)
	base = 0 if base < 0 else base
	while base > 0 and text[base - 1].isspace():
		base -= 1
	pos = base
	for m in _wordRe.finditer(text, base):
		start, end = m.span()
		if start <= offset < end:
			# La palabra incluye el espacio que la sigue, como en otros lectores.
			if not m.group().isspace():
				nxt = _wordRe.match(text, end)
				if nxt and nxt.group().isspace() and "\n" not in nxt.group():
					end = nxt.end()
			else:
				# En espacios: se asocia a la palabra siguiente.
				pass
			return start, end
		pos = end
	return pos, len(text)


_sentenceEnd = re.compile(r"[.!?…]+[\"'»”)\]]*\s+|\n\s*\n")
#: Abreviaturas frecuentes que no terminan una frase.
_ABBREVIATIONS = {"sr", "sra", "srta", "dr", "dra", "ud", "uds", "etc", "pág", "págs", "p", "pp", "fig", "núm", "art", "cap", "vol", "ej", "aprox", "mr", "mrs", "ms", "e.g", "i.e", "vs", "st"}


def _isAbbreviation(text: str, dot: int) -> bool:
	"""¿El punto en ``dot`` cierra una abreviatura o una inicial?"""
	if text[dot : dot + 1] != ".":
		return False
	i = dot
	while i > 0 and (text[i - 1].isalpha() or text[i - 1] == "."):
		i -= 1
	word = text[i:dot].lower()
	if not word:
		return False
	return word in _ABBREVIATIONS or (len(word) == 1 and word.isalpha() and text[i : i + 1].isupper())


def findSentenceBoundaries(text: str, offset: int) -> tuple[int, int]:
	start = 0
	for m in _sentenceEnd.finditer(text):
		if m.group()[0] == "." and _isAbbreviation(text, m.start()):
			continue
		if m.end() <= offset:
			start = m.end()
		else:
			return start, m.end()
	return start, len(text)


_blankSeparator = re.compile(r"\n(?:[ \t]*\n)+")


def findBlankLineParagraph(text: str, offset: int) -> tuple[int, int]:
	"""Párrafo separado por líneas en blanco (estilo «varios saltos de línea»).

	Las líneas en blanco que siguen a un párrafo forman parte de él.
	"""
	start = 0
	for m in _blankSeparator.finditer(text):
		if m.end() <= offset:
			start = m.end()
		else:
			return start, m.end()
	return start, len(text)


def paragraphStyle() -> str:
	"""Estilo de párrafo configurado (``documentNavigation.paragraphStyle``)."""
	try:
		from ..config import conf

		return conf["documentNavigation"]["paragraphStyle"]
	except Exception:
		return "application"


class OffsetsTextInfo(TextInfo):
	"""TextInfo genérico basado en desplazamientos sobre una cadena.

	Las subclases solo necesitan implementar :meth:`_getStoryText` y, si
	quieren, :meth:`_getCaretOffset`, :meth:`_setCaretOffset`,
	:meth:`_getSelectionOffsets` y :meth:`_setSelectionOffsets`.
	"""

	def __init__(self, obj: Any, position: Any) -> None:
		super().__init__(obj, position)
		self._storyCache: str | None = None
		# Rev. 10.11 (A4): el texto completo solo se pide si hace falta (antes,
		# cada rango lo copiaba entero al crearse, también al vigilar el cursor).
		if position == POSITION_FIRST:
			self._start = self._end = 0
		elif position == POSITION_LAST:
			length = len(self._story())
			self._start = self._end = max(0, length - 1) if length else 0
		elif position == POSITION_CARET:
			self._start = self._end = self._clampOffset(self._getCaretOffset())
		elif position == POSITION_SELECTION:
			self._start, self._end = self._getSelectionOffsets()
		elif position == POSITION_ALL:
			self._start, self._end = 0, len(self._story())
		elif isinstance(position, Bookmark):
			self._start, self._end = position.data
		elif isinstance(position, tuple):
			self._start, self._end = position
		elif isinstance(position, Point):
			self._start = self._end = self._getOffsetFromPoint(position.x, position.y)
		else:
			raise ValueError(f"Posición no admitida: {position!r}")

	# --- para subclases ---
	#: El cursor que da la subclase puede pasar del final del texto (se recorta).
	#: Las que ya lo dan dentro del texto ponen ``False`` y no hace falta pedirlo.
	caretMayExceedText = True

	def _clampOffset(self, offset: int) -> int:
		offset = max(0, int(offset))
		if self.caretMayExceedText:
			offset = min(offset, len(self._story()))
		return offset

	def _getStoryText(self) -> str:
		raise NotImplementedError

	def _getCaretOffset(self) -> int:
		return 0

	def _setCaretOffset(self, offset: int) -> None:
		pass

	def _getSelectionOffsets(self) -> tuple[int, int]:
		o = self._getCaretOffset()
		return o, o

	def _setSelectionOffsets(self, start: int, end: int) -> None:
		pass

	def _getOffsetFromPoint(self, x: int, y: int) -> int:
		return 0

	def _getLineOffsets(self, offset: int) -> tuple[int, int]:
		text = self._story()
		n = len(text)
		start = text.rfind("\n", 0, min(offset, n)) + 1 if offset > 0 else 0
		if offset < n and text[offset] == "\n" and offset > 0:
			start = text.rfind("\n", 0, offset) + 1
		end = text.find("\n", offset)
		end = n if end == -1 else end + 1
		return start, end

	def _getParagraphOffsets(self, offset: int) -> tuple[int, int]:
		"""Párrafo según el estilo configurado.

		«application» y «singleLineBreak»: cada salto de línea real termina un
		párrafo (las subclases pueden reconocer saltos suaves). «multiLineBreak»:
		los párrafos se separan con líneas en blanco.
		"""
		if paragraphStyle() == "multiLineBreak":
			return findBlankLineParagraph(self._story(), offset)
		return self._getLineOffsets(offset)

	def _getSentenceOffsets(self, offset: int) -> tuple[int, int]:
		"""Frase real dentro de su párrafo (una frase no cruza párrafos)."""
		text = self._story()
		ps, pe = self._getParagraphOffsets(offset)
		s, e = findSentenceBoundaries(text[ps:pe], offset - ps)
		return ps + s, ps + e

	def _getPageOffsets(self, offset: int) -> tuple[int, int]:
		"""Página: entre saltos de página (``\\f``) o, si no hay, bloques de líneas."""
		text = self._story()
		n = len(text)
		if "\f" in text:
			start = text.rfind("\f", 0, offset) + 1 if offset > 0 else 0
			end = text.find("\f", offset)
			return start, (n if end == -1 else end + 1)
		try:
			from ..config import conf

			perPage = max(1, int(conf["browseMode"]["linesPerPage"]))
		except Exception:
			perPage = 25
		line = text.count("\n", 0, offset)
		first = (line // perPage) * perPage
		start = 0
		for _i in range(first):
			start = text.find("\n", start) + 1
			if start <= 0:
				return 0, n
		end = start
		for _i in range(perPage):
			nxt = text.find("\n", end)
			if nxt == -1:
				return start, n
			end = nxt + 1
		return start, end

	# --- implementación ---
	def _story(self) -> str:
		if self._storyCache is None:
			self._storyCache = self._getStoryText() or ""
		return self._storyCache

	def _unitBoundaries(self, unit: str, offset: int) -> tuple[int, int]:
		text = self._story()
		n = len(text)
		if n == 0:
			return 0, 0
		if unit == UNIT_CHARACTER:
			offset = min(offset, n - 1)
			return offset, offset + 1
		if unit == UNIT_WORD:
			return findWordBoundaries(text, offset)
		offset = min(offset, n - 1)
		if unit == UNIT_SENTENCE:
			return self._getSentenceOffsets(offset)
		if unit == UNIT_LINE:
			return self._getLineOffsets(offset)
		if unit == UNIT_PARAGRAPH:
			return self._getParagraphOffsets(offset)
		if unit == UNIT_PAGE:
			return self._getPageOffsets(offset)
		return 0, n

	def copy(self) -> "OffsetsTextInfo":
		c = object.__new__(type(self))
		c.__dict__.update(self.__dict__)
		return c

	@property
	def text(self) -> str:
		return self._story()[self._start : self._end]

	def expand(self, unit: str) -> None:
		if unit in (UNIT_STORY,):
			self._start, self._end = 0, len(self._story())
			return
		n = len(self._story())
		if unit in (UNIT_CHARACTER, UNIT_WORD) and self._start == self._end and self._start >= n:
			# Cursor tras el último carácter: no hay carácter ni palabra («en blanco»).
			self._start = self._end = n
			return
		self._start, self._end = self._unitBoundaries(unit, self._start)

	def collapse(self, end: bool = False) -> None:
		if end:
			self._start = self._end
		else:
			self._end = self._start

	def move(self, unit: str, direction: int, endPoint: str | None = None) -> int:
		text = self._story()
		n = len(text)
		if endPoint == "end":
			offset = self._end
		else:
			offset = self._start
		moved = 0
		if unit == UNIT_STORY:
			newOffset = 0 if direction < 0 else n
			moved = direction if newOffset != offset else 0
			offset = newOffset
		else:
			step = 1 if direction > 0 else -1
			while moved != direction:
				if step > 0:
					if offset >= n:
						break
					_s, e = self._unitBoundaries(unit, offset)
					if e >= n:
						# No hay unidad siguiente: no se mueve.
						if endPoint:
							offset = n
							moved += step
						break
					offset = e
				else:
					if offset <= 0:
						break
					s, e = self._unitBoundaries(unit, offset - 1)
					if unit == UNIT_WORD and s > 0 and not text[s:e].strip():
						# Rev. 10.11 (A5): hacia atrás, los espacios entre palabras no
						# son una parada (Control+Izquierda se detenía en cada uno).
						s = self._unitBoundaries(unit, s - 1)[0]
					offset = s
				moved += step
		if endPoint == "start":
			self._start = offset
			self._end = max(self._end, offset)
		elif endPoint == "end":
			self._end = offset
			self._start = min(self._start, offset)
		else:
			self._start = self._end = offset
		return moved

	def compareEndPoints(self, other: "TextInfo", which: str) -> int:
		assert isinstance(other, OffsetsTextInfo)
		mine = self._start if which.startswith("start") else self._end
		theirs = other._start if which.endswith("Start") else other._end
		return (mine > theirs) - (mine < theirs)

	def setEndPoint(self, other: "TextInfo", which: str) -> None:
		assert isinstance(other, OffsetsTextInfo)
		val = other._start if which.endswith("Start") else other._end
		if which.startswith("start"):
			self._start = val
			if self._end < val:
				self._end = val
		else:
			self._end = val
			if self._start > val:
				self._start = val

	@property
	def isCollapsed(self) -> bool:
		return self._start == self._end

	@property
	def bookmark(self) -> Bookmark:
		return Bookmark(type(self), (self._start, self._end))

	@property
	def offsets(self) -> tuple[int, int]:
		return self._start, self._end

	def updateCaret(self) -> None:
		self._setCaretOffset(self._start)

	def updateSelection(self) -> None:
		self._setSelectionOffsets(self._start, self._end)

	@property
	def lineNumber(self) -> int | None:
		return self._story().count("\n", 0, self._start) + 1


class StaticTextInfo(OffsetsTextInfo):
	"""TextInfo de un texto fijo (p. ej. nombre y valor de un objeto)."""

	def __init__(self, obj: Any, position: Any, text: str = "") -> None:
		self._staticText = text
		self._caret = 0
		super().__init__(obj, position)

	def _getStoryText(self) -> str:
		return self._staticText

	def _getCaretOffset(self) -> int:
		return self._caret

	def _setCaretOffset(self, offset: int) -> None:
		self._caret = offset


# ====================================================================== desplazamientos UTF-16
#: Caracteres fuera del plano básico (emojis...): dos unidades en UTF-16.
_ASTRAL_RE = re.compile("[\U00010000-\U0010ffff]")


class Utf16Converter:
	"""Convierte desplazamientos UTF-16 (Windows, IA2, Java) en índices de Python y al revés.

	Rev. 10.11 (C2): Python cuenta un emoji como un carácter y Windows como
	dos; sin convertir, cada emoji desplazaba una posición el cursor, las
	palabras y las líneas leídas. Equivale a ``textUtils.WideStringOffsetConverter``
	de NVDA.
	"""

	__slots__ = ("text", "_astral", "_astralU16")

	def __init__(self, text: str) -> None:
		self.text = text
		self._astral = [m.start() for m in _ASTRAL_RE.finditer(text)] if text and not text.isascii() else []
		self._astralU16 = [p + k for k, p in enumerate(self._astral)]

	@property
	def isTrivial(self) -> bool:
		return not self._astral

	@property
	def utf16Length(self) -> int:
		return len(self.text) + len(self._astral)

	def strToUtf16(self, offset: int) -> int:
		if not self._astral:
			return offset
		import bisect

		return offset + bisect.bisect_left(self._astral, offset)

	def utf16ToStr(self, offset: int) -> int:
		"""Índice de Python (la mitad de un par sustituto cuenta como su carácter)."""
		if not self._astral:
			return offset
		import bisect

		return offset - bisect.bisect_left(self._astralU16, offset)


class Utf16OffsetsTextInfo(OffsetsTextInfo):
	"""``OffsetsTextInfo`` de una fuente que cuenta en unidades UTF-16.

	Las subclases devuelven los desplazamientos de la aplicación convertidos
	con :meth:`_toStr` y convierten los suyos con :meth:`_toUtf16` antes de
	pasárselos.
	"""

	def _converter(self) -> Utf16Converter:
		story = self._story()
		conv = self.__dict__.get("_u16conv")
		if conv is None or conv.text is not story:
			conv = Utf16Converter(story)
			self.__dict__["_u16conv"] = conv
		return conv

	def _toStr(self, offset: int) -> int:
		return self._converter().utf16ToStr(int(offset))

	def _toUtf16(self, offset: int) -> int:
		return self._converter().strToUtf16(int(offset))
