"""Documento navegable con el resultado del OCR.

El resultado se presenta en el visor del OCR (``gui/ocr_viewer.py``), pero
quien lo lee es este interceptor: un documento en modo exploración cuyo
búfer se construye con las líneas y palabras reconocidas. Así funcionan las
flechas, la navegación por palabras, la búsqueda, los marcadores, la lectura
continua, la selección y copia, y el cursor de revisión en modo documento.

Cada palabra guarda su posición en pantalla: Intro hace clic sobre ella,
Mayúsculas+F10 o la tecla Aplicaciones hacen clic derecho, Control+Intro
doble clic, y se puede preguntar su posición o llevar allí el ratón. Las
páginas de los PDF son encabezados (tecla H para saltar de página).
"""

from __future__ import annotations

from typing import Any

from . import queue_handler, speech, tree_interceptor, winapi
from .baseobject import script
from .browse.buffer import Node, VirtualBuffer
from .browse.document import BrowseModeDocument
from .config import conf
from .i18n import _
from .log import getLogger
from .objects.roles import Role

log = getLogger("ocrDocument")

CAT = _("Visión")

#: Espera antes de hacer clic, para que el foco vuelva a la ventana de debajo.
CLICK_DELAY_MS = 200


class OcrBuffer(VirtualBuffer):
	"""Búfer construido con las líneas reconocidas en lugar del árbol UIA."""

	def __init__(self, result: Any, screenCoordinates: bool = True) -> None:
		super().__init__(None)
		self.result = result
		self.screenCoordinates = screenCoordinates

	def build(self) -> None:
		parts: list[str] = []
		pos = 0
		self.nodes = []
		self.chunks = []
		self.byRid = {}
		self.tables = {}
		root = Node()
		root.role = Role.DOCUMENT
		root.name = getattr(self.result, "title", "") or ""
		self.nodes.append(root)
		self.root = root
		lastPage = None

		def add(text: str, node: Node | None) -> None:
			nonlocal pos
			start = pos
			parts.append(text)
			pos += len(text)
			if node is not None:
				self.chunks.append((start, pos, node))

		for line in getattr(self.result, "lines", []):
			page = getattr(line, "page", None)
			if page is not None and page != lastPage:
				lastPage = page
				head = Node()
				head.role = Role.HEADING
				head.level = 2
				head.parent = root
				head.start = pos
				label = _("Página {n}").format(n=page)
				head.name = label
				add(label, head)
				head.end = pos
				add("\n", None)
				root.children.append(head)
				self.nodes.append(head)
			if not line.words:
				continue
			para = Node()
			para.role = Role.PARAGRAPH
			para.parent = root
			para.start = pos
			root.children.append(para)
			self.nodes.append(para)
			for i, word in enumerate(line.words):
				if i:
					add(" ", para)
				wn = Node()
				wn.role = Role.STATICTEXT
				wn.parent = para
				wn.name = word.text
				if self.screenCoordinates:
					wn.location = (int(word.x), int(word.y), int(word.w), int(word.h))
				wn.start = pos
				add(word.text, wn)
				wn.end = pos
				para.children.append(wn)
				self.nodes.append(wn)
			para.end = pos
			add("\n", None)
		root.start = 0
		root.end = pos
		self.text = "".join(parts)
		self._chunkStarts = [c[0] for c in self.chunks]
		self.nodes.sort(key=lambda n: (n.start, -n.end))
		for i, n in enumerate(self.nodes):
			n.index = i

	def wordNodeAt(self, offset: int) -> Node | None:
		"""Palabra en ``offset`` o, si cae en un espacio, la palabra anterior de la línea."""
		node = self.nodeAt(offset)
		if node is not None and node.role == Role.STATICTEXT:
			return node
		start, _end = self.lineBounds(offset)
		best = None
		for s, _e, n in self.chunksInRange(start, offset + 1):
			if n.role == Role.STATICTEXT and s <= offset:
				best = n
		if best is None:
			for _s, _e, n in self.chunksInRange(start, _end):
				if n.role == Role.STATICTEXT:
					return n
		return best


class OcrDocument(BrowseModeDocument):
	"""Interceptor sobre la ventana del visor del OCR."""

	scriptCategory = CAT
	#: El búfer sale del resultado del OCR, no de un árbol UIA.
	fixedBufferKind = "ocr"
	#: Se construye al momento (no hay nada lento que hacer en segundo plano).
	backgroundLoading = False

	def __init__(self, result: Any, hwnd: int = 0) -> None:
		self.result = result
		self.hwnd = hwnd
		self.screenCoordinates = bool(result.source) and result.source[0] == "rect"
		self._announced = False
		#: La lectura automática (opción «autoSayAll») ya se hizo.
		self._autoReadDone = False
		self._closing = False
		self.onCaretMoved = None
		super().__init__(None)
		self._disableAutoPassThrough = False
		self._passThrough = not conf["ocr"]["browseModeResult"]

	# --------------------------------------------------------- ciclo de vida
	@property
	def isAlive(self) -> bool:
		if self._closing:
			return False
		if not self.hwnd:
			return True
		try:
			return bool(winapi.user32.IsWindow(self.hwnd))
		except Exception:
			return False

	def terminate(self) -> None:
		self._terminated = True
		self.buffer = None

	def contains(self, obj: Any, ancestors: list | None = None) -> bool:
		if obj is None or not self.hwnd:
			return False
		try:
			h = obj.windowHandle
		except Exception:
			return False
		if not h:
			return False
		try:
			return winapi.getAncestor(h, winapi.GA_ROOT) == self.hwnd
		except Exception:
			return False

	def makeBuffer(self) -> OcrBuffer:
		return OcrBuffer(self.result, self.screenCoordinates)

	def configureBuffer(self, buf) -> None:
		pass

	def _rebuild(self, initial: bool = False) -> None:
		buf = self.makeBuffer()
		buf.build()
		self.buffer = buf
		self._built = True
		self.caret = min(self.caret, max(0, len(buf.text) - 1))
		self.selectionAnchor = None
		ev = self.__dict__.get("_readyEvent")
		if ev is not None:
			ev.set()

	def _documentKey(self) -> str:
		return "ocr:" + (getattr(self.result, "title", "") or "")

	def objectForNode(self, node):
		return None

	def updateResult(self, result: Any) -> None:
		"""Nuevo resultado (actualización automática) conservando la posición."""
		self.result = result
		self._rebuild()

	def register(self, hwnd: int) -> None:
		"""Asocia el documento a la ventana del visor (en el hilo del núcleo)."""
		self.hwnd = hwnd
		if self not in tree_interceptor.runningTable:
			tree_interceptor.runningTable.append(self)
			tree_interceptor.post_treeInterceptorCreated.notify(treeInterceptor=self)

	def close(self) -> None:
		self._closing = True
		try:
			tree_interceptor.runningTable.remove(self)
		except ValueError:
			pass

	# --------------------------------------------------------- eventos
	def event_gainFocus(self, obj: Any, nextHandler) -> None:
		if not self._autoReadDone and conf["ocr"]["autoSayAll"]:
			# «Leer automáticamente con leer todo» también cuando el resultado se
			# abre en modo foco: entonces se lee el cuadro de texto desde su cursor.
			self._autoReadDone = True
			from .speech import sayall

			if self.passThrough:
				nextHandler()
			else:
				self._announced = True
				title = getattr(self.result, "title", "")
				if title:
					speech.speakMessage(title)
				self.caret = 0
			# La lectura automática usa leer todo: el cursor avanza y se puede detener.
			queue_handler.callLater(150, sayall.readText, sayall.CURSOR_CARET)
			return
		if self.passThrough:
			nextHandler()
			return
		if not self._announced:
			self._announced = True
			title = getattr(self.result, "title", "")
			if title:
				speech.speakMessage(title)
		self.speakLineAt(self.caret)
		self._afterCaretMove(self.buffer.nodeAt(self.caret) if self.buffer else None)

	def _afterCaretMove(self, node) -> None:
		super()._afterCaretMove(node)
		cb = self.onCaretMoved
		if cb is not None:
			try:
				cb(self.caret)
			except Exception:
				log.debug("Error sincronizando el visor", exc_info=True)

	# --------------------------------------------------------- palabras
	def _currentWord(self):
		if not self.buffer:
			return None
		return self.buffer.wordNodeAt(self.caret)

	def _wordCenter(self):
		node = self._currentWord()
		if node is None:
			speech.speakMessage(_("No hay ninguna palabra en el cursor"))
			return None
		if not node.location:
			speech.speakMessage(_("Este texto viene de un archivo: no tiene posición en pantalla"))
			return None
		x, y, w, h = node.location
		return x + w // 2, y + h // 2

	def _clickWord(self, button: str = "left", double: bool = False) -> None:
		pt = self._wordCenter()
		if pt is None:
			return
		from . import mouse
		from .gui import ocr_viewer

		ocr_viewer.close()
		queue_handler.callLater(CLICK_DELAY_MS, mouse.click, pt[0], pt[1], button, double)

	def activateAt(self, offset: int) -> None:
		self.caret = offset
		self._clickWord("left")

	@script(gesture="kb:shift+f10", description=_("Hace clic derecho en la palabra"), category=CAT)
	def script_contextMenu(self, gesture) -> None:
		self._clickWord("right")

	@script(gesture="kb:applications", description=_("Hace clic derecho en la palabra"), category=CAT)
	def script_applicationsKey(self, gesture) -> None:
		self._clickWord("right")

	@script(gesture="kb:control+enter", description=_("Hace doble clic en la palabra"), category=CAT)
	def script_doubleClickWord(self, gesture) -> None:
		self._clickWord("left", double=True)

	@script(gestures=("kb(desktop):tiresias+numpadDelete", "kb(laptop):tiresias+delete"), description=_("Anuncia la posición en pantalla de la palabra"), category=CAT, speakOnDemand=True)
	def script_reportWordPosition(self, gesture) -> None:
		node = self._currentWord()
		if node is None:
			speech.speakMessage(_("No hay ninguna palabra en el cursor"))
			return
		if not node.location:
			speech.speakMessage(_("Este texto viene de un archivo: no tiene posición en pantalla"))
			return
		x, y, w, h = node.location
		msg = _("{word}: x {x}, y {y}; ancho {w}, alto {h}").format(word=node.name, x=x, y=y, w=w, h=h)
		src = getattr(self.result, "source", ())
		if src and src[0] == "rect":
			rx, ry = x - src[1][0], y - src[1][1]
			msg += ". " + _("Desde la esquina de la zona reconocida: {x}, {y}").format(x=rx, y=ry)
		speech.speakMessage(msg)

	@script(gestures=("kb(desktop):tiresias+numpadDivide", "kb(laptop):tiresias+shift+m"), description=_("Lleva el ratón a la palabra (sin hacer clic)"), category=CAT)
	def script_moveMouseToWord(self, gesture) -> None:
		pt = self._wordCenter()
		if pt is None:
			return
		from . import mouse

		mouse.moveTo(*pt)
		speech.speakMessage(_("Ratón en {x}, {y}").format(x=pt[0], y=pt[1]))

	@script(gesture="kb:tiresias+f5", description=_("Vuelve a reconocer el origen del resultado del OCR"), category=CAT)
	def script_refreshBuffer(self, gesture) -> None:
		from . import ocr

		ocr.rerecognize()


def caretToLineCol(text: str, offset: int) -> tuple[int, int]:
	"""(línea, columna) de un desplazamiento, para situar el cursor del cuadro de texto."""
	offset = max(0, min(offset, len(text)))
	line = text.count("\n", 0, offset)
	start = text.rfind("\n", 0, offset) + 1
	return line, offset - start

