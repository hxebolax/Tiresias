"""Carga del búfer en segundo plano y actualizaciones parciales.

- La primera carga y las reconstrucciones completas se hacen en un hilo
  propio (apartamento MTA, igual que el núcleo): la petición de caché de UIA
  es lo lento y no bloquea el núcleo. Mientras tanto ``isReady`` es falso y,
  solo en la primera carga, suena un indicador de carga (#16960).
- Los cambios de estructura de la página (``StructureChanged``) no
  reconstruyen todo: se vuelve a construir solo el bloque que cambió y se
  empalma en el búfer (``VirtualBuffer.spliceSubtree``). La localización del
  bloque y su construcción (llamadas entre procesos) también se hacen en
  segundo plano; el núcleo solo empalma el resultado (rev. 10.11, M2).
- Los cambios que llegan de otro documento (otra pestaña del mismo
  navegador) se descartan (rev. 10.11, C1).
"""

from __future__ import annotations

import threading
import time
from typing import Any

import comtypes

from .. import api, queue_handler, speech
from ..a11y import uia_client as uc
from ..audio import tones
from ..baseobject import ScriptableObject
from ..config import conf
from ..i18n import _
from ..log import getLogger
from ..objects.roles import Role
from .buffer import VirtualBuffer

log = getLogger("browseLoader")

#: Más cambios pendientes que estos: se reconstruye todo.
MAX_PARTIAL_UPDATES = 40
#: Bloques con más nodos que estos: se reconstruye todo en segundo plano.
MAX_PARTIAL_NODES = 1500
#: Retardo antes de aplicar los cambios de estructura (se agrupan).
UPDATE_DELAY_MS = 350
#: Separación mínima entre dos reconstrucciones completas seguidas por cambios
#: de la página (las páginas que cambian sin parar no se reconstruyen en bucle).
MIN_REBUILD_INTERVAL_MS = 1500
#: Reintentos de la primera carga si falla (tiempo agotado en páginas enormes).
LOAD_RETRIES = 2

#: Resultado de :meth:`BufferLoaderMixin._nodeForElement` para elementos de
#: otro documento (otra pestaña): el cambio no es de este documento.
OUTSIDE = object()

tones.registerSound("browseLoading", [(523, 18), (0, 30), (659, 18)])


def _comInit() -> bool:
	try:
		comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
		return True
	except OSError:
		return False


def _comUninit(initialized: bool) -> None:
	# Rev. 10.11 (B6): cada hilo de construcción se daba de alta en COM sin
	# darse de baja. Los objetos que crea siguen siendo válidos en el núcleo,
	# que también está en el apartamento multihilo.
	if initialized:
		try:
			comtypes.CoUninitialize()
		except Exception:
			pass


class BufferLoaderMixin(ScriptableObject):
	"""Carga asíncrona e incremental del búfer de :class:`BrowseModeDocument`."""

	#: Construir en segundo plano (las pruebas pueden desactivarlo).
	backgroundLoading = True

	def _loaderInit(self) -> None:
		self._building = False
		self._buildAgain = False
		self._buildGeneration = 0
		self._buildStarted = 0.0
		self._loadingTimer: int | None = None
		self._loadingSpoken = False
		self._pendingElements: list[Any] = []
		self._fullRebuildPending = False
		self._readyEvent = threading.Event()
		#: Instante de la última reconstrucción completa pedida por cambios.
		self._lastAutoRebuild = 0.0
		self._loadRetries = 0

	# ------------------------------------------------------------ fábrica
	def makeBuffer(self) -> VirtualBuffer:
		"""Búfer vacío configurado para este documento (reglas, orden...)."""
		buf = VirtualBuffer(self.rootObject.element)
		self.configureBuffer(buf)
		return buf

	def configureBuffer(self, buf: VirtualBuffer) -> None:
		try:
			from . import flexweb

			rules = flexweb.rulesFor(self._documentKey())
			buf.hiddenRules = rules if rules.hidden else None
			buf.visualOrder = rules.visualOrder
			# Orden de lectura a mano o con IA (foros 3.10).
			from .reading_order import ReadingOrder

			ops = flexweb.readingOrderOps(self._documentKey())
			buf.readingOrder = ReadingOrder(ops) if ops else None
		except Exception:
			log.debug("Sin reglas de web flexible", exc_info=True)
		try:
			# Etiquetas y textos alternativos generados con IA (foros 3.10 y 6.3).
			from ..ai import labelstore

			buf.aiLabels = labelstore.lookupFor(self._documentKey())
		except Exception:
			log.debug("Sin etiquetas de IA", exc_info=True)
		try:
			# Etiquetas personalizadas del usuario (Tiresias+Control+Mayúsculas+L).
			from .. import labels

			root = self.rootObject
			app = getattr(root, "appModule", None)
			try:
				windowClass = root.windowClassName or ""
			except Exception:
				windowClass = ""
			buf.customLabels = labels.bufferLookup(app.appName if app is not None else "global", windowClass)
		except Exception:
			log.debug("Sin etiquetas personalizadas", exc_info=True)

	def _notifyNewNodes(self, nodes: list) -> None:
		"""Contenido nuevo en el búfer: detección de CAPTCHA (foros 10.6)."""
		try:
			from ..ai import captcha

			captcha.onBufferNodes(self, nodes)
		except Exception:
			log.debug("Error revisando el contenido nuevo", exc_info=True)

	# ------------------------------------------------------------ estado
	@property
	def isReady(self) -> bool:
		return bool(self.__dict__.get("_built"))

	def waitUntilReady(self, timeout: float = 10.0) -> bool:
		"""Espera a la primera carga (para herramientas y pruebas fuera del núcleo)."""
		ev = self.__dict__.get("_readyEvent")
		if ev is None:
			return self.isReady
		ev.wait(timeout)
		return self.isReady

	# ------------------------------------------------------------ carga completa
	def requestRebuild(self, initial: bool = False) -> None:
		"""Reconstruye el búfer entero (en segundo plano si se puede)."""
		if not self.backgroundLoading:
			self._rebuild(initial=initial)
			return
		if self._building:
			self._buildAgain = True
			return
		self._building = True
		self._buildGeneration += 1
		gen = self._buildGeneration
		self._buildStarted = time.monotonic()
		buf = self.makeBuffer()
		# Rev. 10.11 (A6): el indicador de carga solo en la carga inicial; en las
		# reconstrucciones el documento sigue utilizable y pitaba sin parar.
		if not self.isReady:
			self._scheduleLoadingIndicator()
		t = threading.Thread(target=self._buildThread, args=(gen, buf, initial), name="browseBuild", daemon=True)
		t.start()

	def _buildThread(self, gen: int, buf: VirtualBuffer, initial: bool) -> None:
		inited = _comInit()
		error = None
		try:
			buf.build()
		except Exception as e:  # noqa: BLE001 - se informa en el núcleo
			error = e
		finally:
			_comUninit(inited)
		queue_handler.queueFunction(self._onBuildDone, gen, buf, error, initial)

	def _onBuildDone(self, gen: int, buf: VirtualBuffer, error: Exception | None, initial: bool) -> None:
		if gen != self._buildGeneration:
			return
		self._building = False
		self._stopLoadingIndicator()
		if self.__dict__.get("_terminated"):
			return
		if error is not None:
			if not isinstance(error, comtypes.COMError):
				log.error("Error construyendo el búfer", exc_info=error)
			else:
				log.debug("No se pudo construir el búfer: %s", error)
			firstLoad = self.buffer is None or not (self.buffer.text if self.buffer is not None else "")
			if self.buffer is None:
				self.buffer = self.makeBuffer()
			# Documento vacío (se reintentará al terminar de cargar la página).
			self._built = True
			retries = self.__dict__.get("_loadRetries", 0)
			if firstLoad and retries < LOAD_RETRIES and isinstance(error, comtypes.COMError):
				# Rev. 10.11 (A8): una página enorme puede agotar el tiempo de UIA;
				# se reintenta en lugar de dejar «documento vacío» para siempre.
				self._loadRetries = retries + 1
				queue_handler.callLater(1500 * (retries + 1), self._retryLoad)
		else:
			self._loadRetries = 0
			self._installBuffer(buf, initial, time.monotonic() - self._buildStarted)
			self._notifyNewNodes(buf.nodes)
		self._readyEvent.set()
		if self.__dict__.pop("_announceRefresh", False):
			# Tiresias+F5 (actualizar el documento) terminado.
			speech.speakMessage(_("documento actualizado"))
		# Rev. 10.11 (A6): el anuncio de la carga no espera a que la página deje
		# de cambiar (antes se aplazaba mientras hubiera otra reconstrucción).
		self._onReady()
		self._afterBuildWork()

	def _retryLoad(self) -> None:
		if self.__dict__.get("_terminated"):
			return
		buf = self.buffer
		if buf is not None and buf.text:
			return
		self.requestRebuild()

	def _afterBuildWork(self) -> None:
		"""Trabajo que llegó mientras se construía: otra reconstrucción o cambios."""
		if self._buildAgain:
			self._buildAgain = False
			self.requestRebuild()
			return
		if self._pendingElements or self._fullRebuildPending or self.__dict__.pop("_updatesAfterBuild", False):
			self.scheduleRebuild(UPDATE_DELAY_MS)

	def _onReady(self) -> None:
		"""Primera carga terminada: se anuncia si el foco está en el documento."""
		if not self.__dict__.get("_announceWhenReady"):
			return
		self._announceWhenReady = False
		focus = api.getFocusObject()
		if focus is not None and self.contains(focus) and not self._loadAnnounced:
			self._loadAnnounced = True
			self._announceLoad()

	# ------------------------------------------------------------ indicador de carga
	def _scheduleLoadingIndicator(self) -> None:
		self._loadingSpoken = False
		if self._loadingTimer is None:
			self._loadingTimer = queue_handler.callLater(600, self._loadingTick)

	def _loadingTick(self) -> None:
		self._loadingTimer = None
		if not self._building or self.isReady:
			return
		mode = conf["browseMode"]["loadingIndicator"]
		focus = api.getFocusObject()
		if focus is not None and self.contains(focus):
			if mode == "beep":
				tones.playSound("browseLoading")
			elif mode == "speech" and not self._loadingSpoken:
				self._loadingSpoken = True
				speech.speakMessage(_("cargando el documento"))
		self._loadingTimer = queue_handler.callLater(1200, self._loadingTick)

	def _stopLoadingIndicator(self) -> None:
		if self._loadingTimer is not None:
			try:
				queue_handler.cancelCallLater(self._loadingTimer)
			except Exception:
				pass
			self._loadingTimer = None

	# ------------------------------------------------------------ cambios de estructura
	def onStructureChanged(self, element: Any = None) -> None:
		"""Llamado (en el hilo del núcleo) cuando cambia el contenido."""
		if self.__dict__.get("bufferKind", "tree") not in ("tree", None):
			# Documentos de texto (Word): no se rehacen por bloques de elementos;
			# se pone al día el texto entero (barato si no cambió).
			refresh = getattr(self, "refreshTextBuffer", None)
			if refresh is not None and self.isReady:
				refresh(syncCaret=False)
			return
		if element is not None:
			# Los cambios de otros procesos no son de este documento.
			try:
				pid = element.GetCachedPropertyValue(uc.P_PROCESSID)
			except Exception:
				pid = None
			if pid and pid != self.rootObject.processID:
				return
		if element is None or len(self._pendingElements) >= MAX_PARTIAL_UPDATES:
			self._fullRebuildPending = True
			self._pendingElements = []
		elif not self._fullRebuildPending:
			self._pendingElements.append(element)
		focus = api.getFocusObject()
		if focus is not None and self.contains(focus):
			self.scheduleRebuild(UPDATE_DELAY_MS)
		else:
			# Se aplica al volver al documento.
			self._dirty = True

	def scheduleRebuild(self, delayMs: int = 600) -> None:
		if self._rebuildTimer is not None:
			return
		self._rebuildTimer = queue_handler.callLater(delayMs, self._doScheduledRebuild)

	def _doScheduledRebuild(self) -> None:
		self._rebuildTimer = None
		if self.__dict__.get("_terminated") or not self.isAlive:
			# Documento cerrado (o interceptor terminado): no se reconstruye nada.
			return
		self.applyPendingUpdates()

	def _requestAutoRebuild(self) -> None:
		"""Reconstrucción completa por cambios de la página, con un ritmo máximo."""
		wait = MIN_REBUILD_INTERVAL_MS / 1000.0 - (time.monotonic() - self.__dict__.get("_lastAutoRebuild", 0.0))
		if wait > 0 and self.isReady:
			self._fullRebuildPending = True
			self.scheduleRebuild(int(wait * 1000) + 1)
			return
		self._lastAutoRebuild = time.monotonic()
		self.requestRebuild()

	def applyPendingUpdates(self) -> None:
		"""Aplica los cambios pendientes: parciales si son pocos, si no, todo."""
		self._dirty = False
		if self._building:
			# Rev. 10.11: los cambios no se pierden; se aplican al terminar la
			# construcción en curso (antes se descartaban y se rehacía todo).
			self._updatesAfterBuild = True
			return
		pending, self._pendingElements = self._pendingElements, []
		full = self._fullRebuildPending
		self._fullRebuildPending = False
		if full or not self.isReady or self.buffer is None:
			self._requestAutoRebuild()
			return
		if not pending:
			# Petición sin elementos concretos (p. ej. tras activar un control).
			self._requestAutoRebuild()
			return
		if not self.backgroundLoading:
			result = self._computePartial(pending, self.buffer)
			self._finishPartial(self.buffer, result)
			return
		self._building = True
		self._buildGeneration += 1
		gen = self._buildGeneration
		buf = self.buffer
		t = threading.Thread(target=self._partialThread, args=(gen, buf, pending), name="browsePartial", daemon=True)
		t.start()

	def _partialThread(self, gen: int, buf: VirtualBuffer, pending: list) -> None:
		inited = _comInit()
		try:
			result = self._computePartial(pending, buf)
		except Exception:
			log.debug("Actualización parcial fallida", exc_info=True)
			result = None
		finally:
			_comUninit(inited)
		queue_handler.queueFunction(self._onPartialDone, gen, buf, result)

	def _computePartial(self, pending: list, buf: VirtualBuffer):
		"""Bloques y sus búferes nuevos (``None``: hay que rehacer todo; ``[]``: nada)."""
		try:
			blocks = self._blocksToUpdate(pending, buf)
		except comtypes.COMError:
			return None
		if blocks is None:
			return None
		out = []
		try:
			for block in blocks:
				out.append((block, self._buildBlock(block)))
		except (comtypes.COMError, ValueError):
			log.debug("Actualización parcial fallida; se reconstruye todo", exc_info=True)
			return None
		return out

	def _onPartialDone(self, gen: int, buf: VirtualBuffer, result) -> None:
		if gen != self._buildGeneration:
			return
		self._building = False
		if self.__dict__.get("_terminated"):
			return
		self._finishPartial(buf, result)
		self._afterBuildWork()

	def _finishPartial(self, buf: VirtualBuffer, result) -> None:
		if result is None or self.buffer is not buf:
			self._requestAutoRebuild()
			return
		for block, sub in result:
			# El bloque puede haber desaparecido entre tanto (otro empalme).
			if block.rid and buf.byRid.get(block.rid) is not block:
				continue
			self._spliceBlock(block, sub)
		if result:
			# La dirección puede cambiar sin recargar (aplicaciones de una página, B5).
			self.__dict__.pop("_docUrl", None)
			try:
				self._applyPendingFocus()
			except Exception:
				log.debug("No se pudo llevar el cursor al foco", exc_info=True)

	def _nodeForElement(self, element: Any, buf: VirtualBuffer | None = None):
		"""Nodo del búfer que contiene ``element``; :data:`OUTSIDE` si es de otro documento."""
		buf = buf if buf is not None else self.buffer
		rootRid = uc.runtimeIdOf(self.rootObject.element)
		el = element
		walker = uc.rawWalker
		for _i in range(40):
			if not el:
				# Se llegó a la raíz del escritorio sin pasar por este documento.
				return OUTSIDE
			rid = uc.runtimeIdOf(el)
			if rid and rid in buf.byRid:
				return buf.byRid[rid]
			if rid and rid == rootRid:
				return buf.root
			if walker is None:
				return None
			try:
				el = walker.GetParentElement(el)
			except comtypes.COMError:
				return None
		return None

	def _blocksToUpdate(self, elements: list, buf: VirtualBuffer | None = None) -> list | None:
		buf = buf if buf is not None else self.buffer
		blocks: list = []
		for el in elements:
			node = self._nodeForElement(el, buf)
			if node is OUTSIDE:
				# Rev. 10.11 (C1): cambio de otro documento (otra pestaña del mismo
				# navegador): no se rehace nada.
				continue
			if node is None:
				# Elemento desconocido: no se sabe dónde va; se rehace todo.
				return None
			block = buf.blockOf(node)
			# Las tablas se rehacen enteras (su mapa de celdas cambia).
			for a in [block] + list(block.ancestors() if block is not None else []):
				if a.role in (Role.TABLE, Role.DATAGRID):
					block = a
			if block is None or block is buf.root or block.parent is None:
				return None
			if block not in blocks:
				blocks.append(block)
		# Se quitan los bloques contenidos en otros de la lista.
		ids = {id(b) for b in blocks}
		blocks = [b for b in blocks if not any(id(a) in ids for a in b.ancestors())]
		# Si el bloque es muy grande (una región con media página), se rehace todo
		# en segundo plano.
		if sum(len(buf.subtreeOf(b)) for b in blocks) > MAX_PARTIAL_NODES:
			return None
		return blocks

	def _buildBlock(self, block) -> VirtualBuffer:
		if block.element is None:
			raise comtypes.COMError(0, "sin elemento", None)
		sub = VirtualBuffer(block.element)
		self.configureBuffer(sub)
		sub.rootParent = block.parent
		sub.build()
		return sub

	def _updateBlock(self, block) -> None:
		"""Rehace un bloque en el acto (compatibilidad: herramientas y pruebas)."""
		self._spliceBlock(block, self._buildBlock(block))

	def _spliceBlock(self, block, sub: VirtualBuffer) -> None:
		buf = self.buffer
		oldStart, oldEnd = block.start, buf.segmentEnd(block)
		caret = self.caret
		caretNode = buf.nodeAt(caret) if oldStart <= caret < oldEnd else None
		caretRid = caretNode.rid if caretNode is not None else None
		caretDelta = caret - caretNode.start if caretNode is not None else 0
		delta = buf.spliceSubtree(block, sub)
		if caret >= oldEnd:
			self.caret = caret + delta
		elif caret >= oldStart:
			n = buf.byRid.get(caretRid) if caretRid else None
			if n is not None:
				self.caret = min(n.start + caretDelta, max(n.start, n.end - 1))
			else:
				self.caret = min(oldStart, max(0, len(buf.text) - 1))
		anchor = self.selectionAnchor
		if anchor is not None:
			if anchor >= oldEnd:
				self.selectionAnchor = anchor + delta
			elif anchor >= oldStart:
				# Rev. 10.11 (B7): el extremo de la selección estaba en el bloque
				# rehecho: ya no existe; se quita la selección.
				self.selectionAnchor = None
		log.debug("Bloque actualizado (%s): %+d caracteres", block.role.name, delta)
		self._notifyNewNodes(sub.nodes)
