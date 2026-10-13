"""PDF y documentos desordenados con IA (foros 3.10).

- :func:`suggestReadingOrder`: manda a la IA los bloques del contenedor del
  cursor (texto y posición), le pide el orden de lectura natural, enseña el
  orden propuesto y, si el usuario lo acepta, lo guarda como una operación de
  orden más (``browse/reading_order.py``; se deshace como las manuales).
- :func:`describeUnlabeledImages`: genera texto alternativo para las imágenes
  sin descripción del documento, una a una (las desplaza a la vista, las
  captura y las describe), y lo guarda en ``labelstore``: el búfer lo usa
  como nombre de la imagen. La misma orden otra vez la detiene.
"""

from __future__ import annotations

import re
import threading
from typing import Any

from .. import imaging, queue_handler, speech
from ..config import conf
from ..i18n import _
from ..log import getLogger
from ..objects.roles import Role

log = getLogger("aiReading")

#: Máximo de bloques que se envían para ordenar.
MAX_BLOCKS = 250
#: Caracteres de cada bloque que se envían.
BLOCK_CHARS = 220

ORDER_SYSTEM = (
	"Ordenas los bloques de texto de un documento (a menudo un PDF sin etiquetar, con columnas, notas, cabeceras "
	"y pies) en el orden en que los leería una persona."
)
ORDER_PROMPT = (
	"Estos son los bloques de un documento en el orden en que salen ahora, con su posición en la página "
	"(x, y en píxeles desde arriba a la izquierda, ancho y alto):\n\n{blocks}\n\n"
	"Responde SOLO con los números de los bloques en el orden de lectura correcto, separados por comas, "
	"sin ningún otro texto. Incluye todos los números una sola vez."
)
ALT_PROMPT = (
	"Esta imagen está en un documento (un PDF o una página web) y no tiene texto alternativo. {context}"
	"Escribe un texto alternativo de una o dos frases para una persona ciega: qué muestra y, si es un gráfico o un "
	"diagrama, qué datos o idea transmite. Si contiene texto, transcríbelo. Si es solo decorativa, responde: imagen decorativa. "
	"Responde solo con el texto alternativo."
)


# ====================================================================== orden con IA
def chooseContainer(buf: Any, node: Any) -> Any:
	"""Contenedor del cursor con al menos tres bloques con texto (o la raíz)."""
	n = buf.textUnitOf(node) if node is not None else None
	while n is not None:
		if len(textBlocks(buf, n)) >= 3:
			return n
		n = n.parent
	return buf.root


def textBlocks(buf: Any, container: Any) -> list[Any]:
	return [c for c in container.children if buf.text[c.start : c.end].strip()]


def describeBlocks(buf: Any, blocks: list[Any]) -> str:
	lines = []
	for i, b in enumerate(blocks, 1):
		loc = b.location
		pos = f" (x={loc[0]}, y={loc[1]}, {loc[2]}×{loc[3]})" if loc else ""
		text = " ".join(buf.text[b.start : b.end].split())[:BLOCK_CHARS]
		lines.append(f"[{i}]{pos} {text}")
	return "\n".join(lines)


def parseOrder(reply: str, count: int, complete: bool = False) -> list[int] | None:
	"""Permutación (índices desde 0) a partir de la respuesta, o ``None`` si no sirve.

	Con ``complete`` (la respuesta se cortó por la longitud) hacen falta todos
	los números: si faltan, el orden propuesto no es fiable.
	"""
	seen: list[int] = []
	for m in re.finditer(r"\d+", reply or ""):
		i = int(m.group()) - 1
		if 0 <= i < count and i not in seen:
			seen.append(i)
	if len(seen) < max(2, count // 2):
		return None
	if complete and len(seen) < count:
		return None
	# Los que falten se quedan al final en su orden.
	seen.extend(i for i in range(count) if i not in seen)
	return seen


def previewText(buf: Any, blocks: list[Any], perm: list[int]) -> str:
	lines = []
	for pos, i in enumerate(perm, 1):
		b = blocks[i]
		lines.append(f"{pos}. {' '.join(buf.text[b.start : b.end].split())[:90]}")
	return "\n".join(lines)


def suggestReadingOrder() -> None:
	from . import assistant
	from .providers import AIError, Message

	doc = assistant.currentBrowseDocument()
	if doc is None:
		speech.speakMessage(_("No hay ningún documento en modo exploración"))
		return
	buf = doc.buffer
	container = chooseContainer(buf, buf.nodeAt(doc.caret))
	blocks = textBlocks(buf, container) if container is not None else []
	if len(blocks) < 2:
		speech.speakMessage(_("No hay bloques que ordenar aquí"))
		return
	blocks = blocks[:MAX_BLOCKS]
	provider = assistant.checkProvider()
	if provider is None:
		return
	prompt = ORDER_PROMPT.format(blocks=describeBlocks(buf, blocks))
	speech.speakMessage(_("Pidiendo a {name} el orden de lectura de {n} bloques").format(name=provider.name, n=len(blocks)))

	def worker() -> None:
		try:
			reply = provider.chat([Message("user", prompt)], assistant.systemPrompt(ORDER_SYSTEM), maxTokens=16000)
		except AIError as e:
			queue_handler.queueFunction(speech.speakMessage, str(e))
			return
		except Exception as e:
			log.exception("Error pidiendo el orden de lectura")
			queue_handler.queueFunction(speech.speakMessage, _("Error inesperado de la inteligencia artificial ({kind}). El detalle está en el registro.").format(kind=type(e).__name__))
			return
		truncated = bool(getattr(reply, "truncated", False))
		perm = parseOrder(reply.text, len(blocks), complete=truncated)
		if perm is None and truncated:
			queue_handler.queueFunction(speech.speakMessage, _("La respuesta de la IA se cortó antes de dar el orden completo. Prueba en una parte más pequeña del documento."))
			return
		queue_handler.queueFunction(_confirmOrder, doc, buf, container, blocks, perm)

	threading.Thread(target=worker, name="IA-orden", daemon=True).start()


def _confirmOrder(doc: Any, buf: Any, container: Any, blocks: list[Any], perm: list[int] | None) -> None:
	if perm is None:
		speech.speakMessage(_("La respuesta de la IA no es un orden válido"))
		return
	if perm == list(range(len(blocks))):
		speech.speakMessage(_("La IA no cambiaría el orden de lectura"))
		return
	from ..browse import reading_order

	op = reading_order.planOrder(buf, container, [blocks[i] for i in perm])
	if op is None:
		speech.speakMessage(_("No se puede cambiar el orden de este documento"))
		return
	op["desc"] = _("orden propuesto por la IA")
	preview = previewText(buf, blocks, perm)
	speech.speakMessage(_("Orden propuesto. Revísalo y elige si lo aplicas."))

	def accept() -> None:
		queue_handler.queueFunction(applyOp, doc, op, _("Orden de lectura de la IA aplicado"))

	from ..gui import ai_dialogs

	ai_dialogs.showOrderConfirm(_("Orden de lectura propuesto por la IA"), preview, accept)


def applyOp(doc: Any, op: dict, message: str) -> None:
	from ..browse import flexweb

	flexweb.addReadingOrderOp(doc._documentKey(), op)
	speech.speakMessage(message)
	doc.requestRebuild()


# ====================================================================== texto alternativo
class AltTextJob:
	"""Describe una a una las imágenes sin texto alternativo de un documento."""

	def __init__(self, doc: Any, items: list[tuple[str, str, Any]]) -> None:
		self.doc = doc
		self.docKey = doc._documentKey()
		#: (huella, ámbito, nodo)
		self.items = items
		self.index = 0
		self.done = 0
		self.skipped = 0
		self.cancelled = False
		self.provider = None
		#: Motivo por el que se detuvo el trabajo (clave rechazada, sin cupo, sin red).
		self.stopReason = ""

	def start(self, provider: Any) -> None:
		self.provider = provider
		speech.speakMessage(_("Describiendo {n} imágenes sin descripción. Repite la orden para detenerlo.").format(n=len(self.items)))
		self._next()

	def cancel(self) -> None:
		self.cancelled = True

	def _next(self) -> None:
		global _job
		if self.cancelled or self.index >= len(self.items):
			_job = None
			self._finish()
			return
		_fp, _scope, node = self.items[self.index]
		try:
			pat = node.element.GetCurrentPattern(_scrollItemPattern())
			if pat:
				from ..a11y import uia_client as uc

				pat.QueryInterface(uc.UIA.IUIAutomationScrollItemPattern).ScrollIntoView()
		except Exception:
			pass
		# Se deja que la página termine de desplazarse antes de capturar.
		queue_handler.callLater(450, self._capture)

	def _capture(self) -> None:
		if self.cancelled:
			self._next()
			return
		from . import assistant

		fp, scope, node = self.items[self.index]
		rect = assistant.liveRect(node.element) if node.element is not None else None
		vx, vy, vw, vh = imaging.virtualScreenRect()
		if rect is None or rect[0] + rect[2] <= vx or rect[1] + rect[3] <= vy or rect[0] >= vx + vw or rect[1] >= vy + vh:
			self.skipped += 1
			self.index += 1
			self._next()
			return
		hwnd = assistant.rootWindow(getattr(self.doc, "rootObject", None))
		context = ""
		near = next((a.name for a in node.ancestors() if a.name), "")
		if near:
			context = f"Está dentro de «{near[:80]}». "
		prompt = ALT_PROMPT.format(context=context)
		provider = self.provider

		def worker() -> None:
			from .autolabel import cleanAltText
			from .providers import AIError, Message

			text = ""
			error = None
			try:
				png = assistant._imageToPng(imaging.captureRect(rect, hwnd) if hwnd else imaging.captureRect(rect))
				# Tarea corta: poco razonamiento y margen para los modelos que
				# siempre razonan (el razonamiento cuenta en el límite).
				reply = provider.chat([Message("user", prompt, [png])], assistant.systemPrompt(), maxTokens=2000, effort="low")
				text = cleanAltText(reply.text)
			except AIError as e:
				log.warning("No se pudo describir la imagen: %s", e)
				error = e
			except Exception as e:
				log.warning("No se pudo describir la imagen", exc_info=True)
				error = e
			queue_handler.queueFunction(self._described, fp, scope, text, error)

		threading.Thread(target=worker, name="IA-alt", daemon=True).start()

	def _described(self, fp: str, scope: str, text: str, error: Exception | None = None) -> None:
		from . import labelstore

		self.index += 1
		if text:
			labelstore.setText(self.docKey, fp, text, scope)
			self.done += 1
			speech.speakMessage(_("Imagen {i} de {n}: {text}").format(i=self.index, n=len(self.items), text=text))
		else:
			self.skipped += 1
			if error is not None:
				if getattr(error, "isFatal", False):
					# Clave rechazada, límite de uso o sin red: las demás también fallarían.
					self.stopReason = str(error)
					self.cancelled = True
				else:
					speech.speakMessage(_("Imagen {i} de {n} sin describir: {err}").format(i=self.index, n=len(self.items), err=error))
		self._next()

	def _finish(self) -> None:
		if self.stopReason:
			msg = _("Descripción de imágenes detenida: {reason}. {done} descritas").format(reason=self.stopReason.rstrip("."), done=self.done)
		elif self.cancelled:
			msg = _("Descripción de imágenes detenida: {done} descritas").format(done=self.done)
		else:
			msg = _("Texto alternativo listo: {done} imágenes descritas, {skipped} sin describir").format(done=self.done, skipped=self.skipped)
		speech.speakMessage(msg)
		if self.done:
			try:
				self.doc.requestRebuild()
			except Exception:
				pass


def _scrollItemPattern() -> int:
	from ..a11y import uia_client as uc

	return uc.PAT_SCROLLITEM


_job: AltTextJob | None = None


def unlabeledImages(buf: Any) -> list[Any]:
	return [n for n in buf.nodes if n.role == Role.GRAPHIC and not n.name and n.element is not None]


def describeUnlabeledImages() -> None:
	"""Orden: texto alternativo con IA para las imágenes sin descripción (otra vez: detiene)."""
	global _job
	from . import assistant, labelstore

	if _job is not None:
		_job.cancel()
		speech.speakMessage(_("Deteniendo la descripción de imágenes"))
		return
	doc = assistant.currentBrowseDocument()
	if doc is None:
		speech.speakMessage(_("No hay ningún documento en modo exploración"))
		return
	images = unlabeledImages(doc.buffer)
	if not images:
		speech.speakMessage(_("No hay imágenes sin descripción en este documento"))
		return
	limit = max(1, int(conf["ai"]["altTextMaxImages"]))
	docKey = doc._documentKey()
	items = [(labelstore.fingerprint(n), labelstore.scopeFor(docKey, n), n) for n in images[:limit]]
	provider = assistant.checkProvider()
	if provider is None:
		return

	def go() -> None:
		global _job
		if _job is not None:
			return
		_job = AltTextJob(doc, items)
		_job.start(provider)

	assistant.withImagePrivacy(go)
