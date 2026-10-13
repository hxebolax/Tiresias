"""Etiquetado automático con IA de los elementos sin nombre (foros 6.3, NVDA #17332).

Con la opción «Etiquetar automáticamente con IA los elementos sin nombre»
(desactivada por defecto, porque envía imágenes y gasta peticiones):

- al recibir el foco un botón, enlace, gráfico, pestaña o elemento de menú
  sin nombre ni etiqueta personalizada, o
- al llegar el cursor del modo exploración a un gráfico, botón o enlace sin
  texto,

se espera un momento (si el usuario sigue de largo no se pide nada), se
captura el elemento con un margen de contexto y se pide una etiqueta en un
hilo propio. La etiqueta se anuncia si el usuario sigue allí y se guarda: en
las aplicaciones, como etiqueta personalizada (``labels``); en las páginas y
PDF, en ``labelstore``, y el búfer la usa como nombre desde ese momento.

Límites para no gastar: una petición a la vez, un máximo por hora
(``autoLabelMaxPerHour``), cada elemento se intenta una sola vez por sesión y
nunca se envía nada si el proveedor no está configurado o el usuario no ha
aceptado el aviso de privacidad de las imágenes.
"""

from __future__ import annotations

import collections
import threading
import time
from dataclasses import dataclass
from typing import Any

from .. import api, imaging, queue_handler, speech
from ..config import conf
from ..i18n import _
from ..log import getLogger
from ..objects.roles import Role, State

log = getLogger("aiAutoLabel")

#: Roles que se etiquetan al recibir el foco.
FOCUS_ROLES = {
	Role.BUTTON,
	Role.TOGGLEBUTTON,
	Role.SPLITBUTTON,
	Role.MENUBUTTON,
	Role.DROPDOWNBUTTON,
	Role.LINK,
	Role.GRAPHIC,
	Role.MENUITEM,
	Role.TAB,
	Role.LISTITEM,
	Role.TREEVIEWITEM,
}
#: Roles de botón en el búfer.
BUFFER_BUTTON_ROLES = {Role.BUTTON, Role.TOGGLEBUTTON, Role.SPLITBUTTON, Role.MENUITEM, Role.TAB}
#: Espera antes de pedir la etiqueta (si el usuario sigue de largo, no se pide).
DWELL_MS = 900
HOUR = 3600.0
#: Pausa (s) tras quedarse sin red o sin cupo del servicio.
ERROR_PAUSE = 120.0

AUTO_PROMPT_CONTROL = (
	"Esta imagen muestra, en el centro, un control de una aplicación o página web que no tiene nombre accesible "
	"(el resto es contexto). Datos: {info}. Propón una etiqueta corta (de una a cuatro palabras) que diga para qué sirve. "
	"Responde solo con la etiqueta, sin comillas ni punto final. Si no se puede saber, responde solo: ?"
)
AUTO_PROMPT_GRAPHIC = (
	"Esta imagen muestra, en el centro, un gráfico sin texto alternativo de una aplicación, página web o documento "
	"(el resto es contexto). Datos: {info}. Escribe un texto alternativo de una sola frase breve que diga qué muestra "
	"o, si es un icono, para qué sirve. Si contiene texto, transcríbelo. Responde solo con ese texto. Si no se puede saber, responde solo: ?"
)


@dataclass
class Candidate:
	"""Elemento sin nombre que se puede etiquetar."""

	key: tuple
	rect: tuple[int, int, int, int]
	hwnd: int
	isGraphic: bool
	info: str
	obj: Any = None
	doc: Any = None
	node: Any = None
	docKey: str = ""


def _roleInfo(role: Role, parentName: str = "", app: str = "") -> str:
	from ..objects.roles import roleLabel

	parts = ["tipo " + roleLabel(role)]
	if app:
		parts.append("aplicación " + app)
	if parentName:
		parts.append("dentro de «" + parentName + "»")
	return ", ".join(parts)


def unlabeledBufferTarget(buf: Any, node: Any) -> Any:
	"""Elemento sin nombre del búfer en ``node`` (gráfico, botón o enlace sin texto)."""
	if node is None:
		return None
	if node.role == Role.GRAPHIC and not node.name:
		return node
	if node.role in BUFFER_BUTTON_ROLES and not node.name.strip() and not (node.value or "").strip():
		return node
	if node.role == Role.LINK and not node.name:
		text = buf.text[node.start : node.end].strip()
		if not text or text == _("enlace"):
			return node
	return None


def needsLabel(obj: Any) -> bool:
	"""¿El objeto con foco es un control sin nombre ni etiqueta personalizada?"""
	try:
		if obj is None or obj.role not in FOCUS_ROLES:
			return False
		if (obj.name or "").strip():
			return False
		if State.INVISIBLE in obj.states or State.OFFSCREEN in obj.states:
			return False
	except Exception:
		return False
	try:
		from .. import labels

		if labels.getLabel(obj):
			return False
	except Exception:
		pass
	loc = obj.location
	return bool(loc and loc[2] > 0 and loc[3] > 0)


class AutoLabeler:
	def __init__(self) -> None:
		self._times: collections.deque[float] = collections.deque()
		self._busy = False
		self._tried: set[tuple] = set()
		#: Etiquetas de la sesión (cuando no se guardan).
		self._session: dict[tuple, str] = {}
		self._timer: int | None = None
		self._pending: Candidate | None = None
		self._privacyAsked = False
		self._warnedKey = False
		self._warnedLimit = 0.0
		self._registered = False
		#: La clave del servicio falló: no se pide nada más hasta volver a activarlo.
		self._stopped = False
		#: Tipos de error ya avisados (se avisa una vez de cada uno).
		self._warnedErrors: set[str] = set()
		#: Sin red o sin cupo: no se vuelve a pedir hasta este instante (monotónico).
		self._pausedUntil = 0.0

	# ------------------------------------------------------------ ciclo de vida
	def initialize(self) -> None:
		if not self._registered:
			api.post_focusChange.register(self.onFocus)
			api.post_reviewMove.register(self.onReviewMove)
			self._registered = True

	def terminate(self) -> None:
		if self._registered:
			api.post_focusChange.unregister(self.onFocus)
			api.post_reviewMove.unregister(self.onReviewMove)
			self._registered = False
		self._cancelTimer()

	@staticmethod
	def enabled() -> bool:
		try:
			return bool(conf["ai"]["autoLabel"])
		except KeyError:
			return False

	def resetErrors(self) -> None:
		"""Olvida los errores anteriores (se llama al guardar las opciones de IA:
		una clave corregida vuelve a poner en marcha el etiquetado automático)."""
		self._privacyAsked = False
		self._warnedKey = False
		self._stopped = False
		self._warnedErrors.clear()
		self._pausedUntil = 0.0

	def toggle(self) -> None:
		value = not self.enabled()
		conf["ai"]["autoLabel"] = value
		if value:
			self.resetErrors()
		speech.speakMessage(_("Etiquetado automático con IA activado") if value else _("Etiquetado automático con IA desactivado"))

	# ------------------------------------------------------------ candidatos
	def candidateForObject(self, obj: Any) -> Candidate | None:
		if not needsLabel(obj):
			return None
		doc = getattr(obj, "treeInterceptor", None)
		buf = getattr(doc, "buffer", None) if doc is not None else None
		rid = tuple(getattr(obj, "runtimeId", ()) or ())
		if buf is not None and rid and rid in buf.byRid:
			node = unlabeledBufferTarget(buf, buf.byRid[rid])
			if node is not None:
				return self.candidateForNode(doc, node)
		try:
			from .. import labels

			lkey = labels._key(obj)
			app = obj.appModule.appName if obj.appModule is not None else ""
		except Exception:
			lkey, app = None, ""
		if not lkey:
			return None
		key = ("obj", app, lkey)
		if key in self._session:
			# Ya se etiquetó en esta sesión (sin guardar): se repite sin pedir.
			queue_handler.queueFunction(speech.speakMessage, _("Etiqueta de IA: {label}").format(label=self._session[key]))
			return None
		parent = None
		try:
			parent = obj.parent
		except Exception:
			pass
		from .assistant import rootWindow

		return Candidate(
			key=key,
			rect=obj.location,
			hwnd=rootWindow(obj),
			isGraphic=obj.role == Role.GRAPHIC,
			info=_roleInfo(obj.role, (parent.name if parent is not None else "") or "", app),
			obj=obj,
		)

	def candidateForNode(self, doc: Any, node: Any) -> Candidate | None:
		from . import labelstore
		from .assistant import liveRect, rootWindow

		try:
			docKey = doc._documentKey()
			fp = labelstore.fingerprint(node)
		except Exception:
			return None
		key = ("node", labelstore.scopeFor(docKey, node), fp)
		if key in self._session:
			queue_handler.queueFunction(speech.speakMessage, _("Etiqueta de IA: {label}").format(label=self._session[key]))
			return None
		rect = liveRect(node.element) if node.element is not None else None
		rect = rect or node.location
		if not rect:
			return None
		parentName = next((a.name for a in node.ancestors() if a.name), "")
		return Candidate(
			key=key,
			rect=rect,
			hwnd=rootWindow(getattr(doc, "rootObject", None)),
			isGraphic=node.role == Role.GRAPHIC,
			info=_roleInfo(node.role, parentName[:60]),
			doc=doc,
			node=node,
			docKey=docKey,
		)

	def isStillCurrent(self, cand: Candidate) -> bool:
		if cand.node is not None:
			doc = cand.doc
			buf = getattr(doc, "buffer", None)
			if buf is None:
				return False
			n = buf.nodeAt(doc.caret)
			while n is not None:
				if n is cand.node or (n.rid and n.rid == cand.node.rid):
					return True
				n = n.parent
			focus = api.getFocusObject()
			return bool(focus is not None and cand.node.rid and tuple(getattr(focus, "runtimeId", ()) or ()) == cand.node.rid)
		focus = api.getFocusObject()
		try:
			return focus is not None and focus == cand.obj
		except Exception:
			return False

	# ------------------------------------------------------------ eventos
	def onFocus(self, obj: Any = None) -> None:
		if not self.enabled() or obj is None:
			return
		try:
			cand = self.candidateForObject(obj)
		except Exception:
			log.debug("Error buscando candidato a etiqueta", exc_info=True)
			return
		self._schedule(cand)

	def onReviewMove(self, info: Any = None, isCaret: bool = False) -> None:
		if not self.enabled() or not isCaret or info is None:
			return
		doc = getattr(info, "doc", None)
		buf = getattr(doc, "buffer", None) if doc is not None else None
		if buf is None:
			return
		try:
			node = unlabeledBufferTarget(buf, buf.nodeAt(info._start))
			cand = self.candidateForNode(doc, node) if node is not None else None
		except Exception:
			log.debug("Error buscando candidato a etiqueta en el búfer", exc_info=True)
			return
		self._schedule(cand)

	def _cancelTimer(self) -> None:
		if self._timer is not None:
			try:
				queue_handler.cancelCallLater(self._timer)
			except Exception:
				pass
			self._timer = None
		self._pending = None

	def _schedule(self, cand: Candidate | None) -> None:
		self._cancelTimer()
		if cand is None or cand.key in self._tried:
			return
		self._pending = cand
		self._timer = queue_handler.callLater(DWELL_MS, self._fire)

	def _fire(self) -> None:
		self._timer = None
		cand, self._pending = self._pending, None
		if cand is not None and self.enabled() and self.isStillCurrent(cand):
			self.request(cand)

	# ------------------------------------------------------------ límites
	def _withinLimit(self) -> bool:
		now = time.monotonic()
		while self._times and now - self._times[0] > HOUR:
			self._times.popleft()
		limit = max(1, int(conf["ai"]["autoLabelMaxPerHour"]))
		if len(self._times) >= limit:
			if now - self._warnedLimit > HOUR:
				self._warnedLimit = now
				speech.speakMessage(_("Etiquetado automático en pausa: se ha llegado al máximo de {n} peticiones por hora").format(n=limit))
			return False
		return True

	# ------------------------------------------------------------ petición
	def request(self, cand: Candidate) -> bool:
		"""Pide la etiqueta (en un hilo). Devuelve ``False`` si no se ha enviado nada."""
		if self._busy or cand.key in self._tried or self._stopped:
			return False
		if time.monotonic() < self._pausedUntil:
			return False
		from .assistant import checkProvider

		provider = checkProvider(quiet=True)
		if provider is None:
			if not self._warnedKey:
				self._warnedKey = True
				speech.speakMessage(_("El etiquetado automático necesita la clave del servicio de IA (Opciones, Inteligencia artificial)"))
			return False
		from .assistant import privacyAccepted

		if not privacyAccepted(provider):
			if not self._privacyAsked:
				self._privacyAsked = True
				from .assistant import withImagePrivacy

				withImagePrivacy(lambda: self.request(cand))
			return False
		if not self._withinLimit():
			return False
		from .assistant import paddedRect

		rect = paddedRect(cand.rect)
		if rect is None:
			return False
		self._busy = True
		self._tried.add(cand.key)
		sentAt = time.monotonic()
		self._times.append(sentAt)
		prompt = (AUTO_PROMPT_GRAPHIC if cand.isGraphic else AUTO_PROMPT_CONTROL).format(info=cand.info or "sin datos")

		def worker() -> None:
			from .providers import AIError, Message

			label = ""
			try:
				from .assistant import _imageToPng, cleanLabel, systemPrompt

				png = _imageToPng(imaging.captureRect(rect, cand.hwnd) if cand.hwnd else imaging.captureRect(rect))
				# Tarea corta: poco razonamiento y margen suficiente para los
				# modelos que siempre razonan (el razonamiento cuenta en el límite).
				reply = provider.chat([Message("user", prompt, [png])], systemPrompt(), maxTokens=2000, effort="low")
				label = cleanLabel(reply.text) if not cand.isGraphic else cleanAltText(reply.text)
			except AIError as e:
				log.warning("Etiquetado automático fallido: %s", e)
				queue_handler.queueFunction(self._failed, cand, e, sentAt)
				return
			except Exception:
				log.warning("Etiquetado automático fallido", exc_info=True)
			queue_handler.queueFunction(self._done, cand, label)

		threading.Thread(target=worker, name="IA-autoetiqueta", daemon=True).start()
		return True

	def _failed(self, cand: Candidate, error: Any, sentAt: float) -> None:
		"""El servicio de IA devolvió un error (hilo del núcleo)."""
		self._busy = False
		if not getattr(error, "isFatal", False):
			return
		# Clave rechazada, límite de uso o sin red: la petición no cuenta para el
		# cupo y el elemento se podrá volver a intentar.
		try:
			self._times.remove(sentAt)
		except ValueError:
			pass
		self._tried.discard(cand.key)
		kind = getattr(error, "kind", "")
		if kind in ("auth", "permission", "billing", "notfound"):
			# Con la clave, el permiso, el saldo o el modelo mal no se sigue pidiendo nada.
			self._stopped = True
			self._cancelTimer()
			speech.speakMessage(_("Etiquetado automático con IA detenido: {err}").format(err=error))
			return
		self._pausedUntil = time.monotonic() + ERROR_PAUSE
		if kind not in self._warnedErrors:
			self._warnedErrors.add(kind)
			speech.speakMessage(_("Etiquetado automático con IA en pausa: {err}").format(err=error))

	def _done(self, cand: Candidate, label: str) -> None:
		self._busy = False
		if not label or label == "?":
			return
		self.store(cand, label)
		if self.isStillCurrent(cand):
			speech.speakMessage(_("Etiqueta de IA: {label}").format(label=label))

	def store(self, cand: Candidate, label: str) -> None:
		save = conf["ai"]["autoLabelSave"]
		if not save:
			self._session[cand.key] = label
			return
		if cand.node is not None:
			from . import labelstore

			labelstore.setText(cand.docKey, cand.key[2], label, cand.key[1])
			try:
				# El búfer usa la etiqueta como nombre en cuanto se reconstruye.
				cand.doc.scheduleRebuild(1500)
			except Exception:
				pass
			return
		try:
			from .. import labels

			if not labels.setLabel(cand.obj, label):
				self._session[cand.key] = label
		except Exception:
			log.exception("No se pudo guardar la etiqueta automática")
			self._session[cand.key] = label


def cleanAltText(text: str, limit: int = 300) -> str:
	t = " ".join(text.split()).strip().strip("\"'«»“”").strip()
	return t[:limit]


autoLabeler = AutoLabeler()
