"""Controles Scintilla (Notepad++, SciTE, editores de código antiguos).

Scintilla no ofrece texto por UI Automation: el proxy MSAA solo da todo el
texto como nombre de un panel. Aquí se lee con los mensajes ``SCI_*``
(texto, cursor, selección, líneas) usando un búfer en el proceso del editor
(:mod:`._procmem`), y se presenta como un campo de edición normal con cursor:
flechas, selección, eco, lectura continua, revisión...
"""

from __future__ import annotations

from .. import baseobject, textinfo
from ..log import getLogger
from ..objects.base import AccObject
from ..objects.roles import Role, State
from . import _procmem

log = getLogger("scintilla")

SCI_GETTEXT = 2182
SCI_GETTEXTLENGTH = 2183
SCI_GETCURRENTPOS = 2008
SCI_GETANCHOR = 2009
SCI_GOTOPOS = 2025
SCI_SETSEL = 2160
SCI_GETSELECTIONSTART = 2143
SCI_GETSELECTIONEND = 2145
SCI_GETCODEPAGE = 2137
SCI_LINEFROMPOSITION = 2166
SCI_GETCOLUMN = 2129
SCI_GETREADONLY = 2140
SCI_POINTXFROMPOSITION = 2164
SCI_POINTYFROMPOSITION = 2165
SCI_POSITIONFROMPOINT = 2022

#: Tamaño máximo que se lee (bytes). Más allá se trunca para no bloquear.
MAX_BYTES = 8 * 1024 * 1024


class ScintillaDocument:
	"""Texto y conversiones entre posiciones en bytes (Scintilla) y caracteres."""

	def __init__(self, raw: bytes, codepage: int) -> None:
		self.raw = raw
		self.encoding = "utf-8" if codepage == 65001 else ("mbcs" if codepage else "latin-1")
		self.text = raw.decode(self.encoding, errors="replace")
		self._ascii = len(self.text) == len(raw)

	def charOffset(self, bytePos: int) -> int:
		bytePos = max(0, min(bytePos, len(self.raw)))
		if self._ascii:
			return bytePos
		return len(self.raw[:bytePos].decode(self.encoding, errors="replace"))

	def byteOffset(self, charPos: int) -> int:
		charPos = max(0, min(charPos, len(self.text)))
		if self._ascii:
			return charPos
		return len(self.text[:charPos].encode(self.encoding, errors="replace"))


def readDocument(hwnd: int) -> ScintillaDocument:
	length = _procmem.sendMessage(hwnd, SCI_GETTEXTLENGTH)
	length = max(0, min(length, MAX_BYTES))
	codepage = _procmem.sendMessage(hwnd, SCI_GETCODEPAGE)
	if length == 0:
		return ScintillaDocument(b"", codepage)
	with _procmem.RemoteBuffer(hwnd, length + 1) as buf:
		_procmem.sendMessage(hwnd, SCI_GETTEXT, length + 1, buf.address, timeout=2000)
		raw = buf.read(length + 1)
	return ScintillaDocument(raw.split(b"\0", 1)[0], codepage)


class ScintillaTextInfo(textinfo.OffsetsTextInfo):
	def _doc(self) -> ScintillaDocument:
		return self.obj.scintillaDocument()

	def _getStoryText(self) -> str:
		try:
			text = self._doc().text
		except _procmem.ProcessMemoryError:
			return ""
		# Los saltos de línea de Windows cuentan como un solo carácter para la unidad línea.
		return text

	def _getCaretOffset(self) -> int:
		try:
			return self._doc().charOffset(_procmem.sendMessage(self.obj.windowHandle, SCI_GETCURRENTPOS))
		except _procmem.ProcessMemoryError:
			return 0

	def _setCaretOffset(self, offset: int) -> None:
		try:
			_procmem.sendMessage(self.obj.windowHandle, SCI_GOTOPOS, self._doc().byteOffset(offset))
		except _procmem.ProcessMemoryError:
			pass

	def _getSelectionOffsets(self) -> tuple[int, int]:
		hwnd = self.obj.windowHandle
		try:
			doc = self._doc()
			start = doc.charOffset(_procmem.sendMessage(hwnd, SCI_GETSELECTIONSTART))
			end = doc.charOffset(_procmem.sendMessage(hwnd, SCI_GETSELECTIONEND))
			return start, end
		except _procmem.ProcessMemoryError:
			return 0, 0

	def _setSelectionOffsets(self, start: int, end: int) -> None:
		try:
			doc = self._doc()
			_procmem.sendMessage(self.obj.windowHandle, SCI_SETSEL, doc.byteOffset(start), doc.byteOffset(end))
		except _procmem.ProcessMemoryError:
			pass

	def _getOffsetFromPoint(self, x: int, y: int) -> int:
		import ctypes

		from .. import winapi

		hwnd = self.obj.windowHandle
		pt = winapi.POINT(x, y)
		ctypes.windll.user32.ScreenToClient(hwnd, ctypes.byref(pt))
		try:
			pos = _procmem.sendMessage(hwnd, SCI_POSITIONFROMPOINT, pt.x, pt.y)
			return self._doc().charOffset(pos)
		except _procmem.ProcessMemoryError:
			return 0

	@property
	def pointAtStart(self):
		import ctypes

		from .. import winapi

		hwnd = self.obj.windowHandle
		try:
			pos = self._doc().byteOffset(self._start)
			x = _procmem.sendMessage(hwnd, SCI_POINTXFROMPOSITION, 0, pos)
			y = _procmem.sendMessage(hwnd, SCI_POINTYFROMPOSITION, 0, pos)
		except _procmem.ProcessMemoryError:
			return None
		pt = winapi.POINT(x, y)
		ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt))
		return textinfo.Point(pt.x, pt.y)


class ScintillaEdit(AccObject):
	"""Superposición para la ventana ``Scintilla``."""

	TextInfo = ScintillaTextInfo

	def scintillaDocument(self) -> ScintillaDocument:
		"""Texto del editor (se lee una vez por ciclo del núcleo)."""
		cached = self.__dict__.get("_sciDoc")
		gen = baseobject._cacheGeneration
		if cached is not None and cached[0] == gen:
			return cached[1]
		doc = readDocument(self.windowHandle)
		self.__dict__["_sciDoc"] = (gen, doc)
		return doc

	def _get_name(self) -> str:
		# El proxy MSAA pone todo el texto como nombre: no sirve como nombre.
		return ""

	def _get_role(self) -> Role:
		return Role.EDITABLETEXT

	def _get_value(self) -> str:
		return ""

	def _get_states(self) -> set[State]:
		states = {State.FOCUSABLE, State.MULTILINE}
		try:
			readOnly = bool(_procmem.sendMessage(self.windowHandle, SCI_GETREADONLY))
		except _procmem.ProcessMemoryError:
			readOnly = False
		states.add(State.READONLY if readOnly else State.EDITABLE)
		if self._uiaHasFocus():
			states.add(State.FOCUSED)
		return states

	def _uiaHasFocus(self) -> bool:
		try:
			return bool(super()._get_hasFocus())  # type: ignore[misc]
		except Exception:
			return False

	def _get_basicText(self) -> str:
		try:
			return self.scintillaDocument().text
		except _procmem.ProcessMemoryError:
			return ""

	def lineAndColumn(self) -> tuple[int, int]:
		hwnd = self.windowHandle
		pos = _procmem.sendMessage(hwnd, SCI_GETCURRENTPOS)
		line = _procmem.sendMessage(hwnd, SCI_LINEFROMPOSITION, pos)
		col = _procmem.sendMessage(hwnd, SCI_GETCOLUMN, pos)
		return line + 1, col + 1


def isScintilla(obj) -> bool:
	try:
		from .. import winapi

		hwnd = obj.windowHandle
		if not hwnd or winapi.getClassName(hwnd) != "Scintilla":
			return False
		# Solo el propio control (no objetos hijos que compartan ventana).
		return obj.role in (Role.PANE, Role.EDITABLETEXT, Role.DOCUMENT, Role.WINDOW) and not getattr(obj, "TextInfo", None)
	except Exception:
		return False


def overlayClasses() -> list[type]:
	"""Clases que se añaden a un control Scintilla (con el comportamiento de edición)."""
	from ..objects import behaviors

	return [ScintillaEdit, behaviors.EditableTextWithCaret]
