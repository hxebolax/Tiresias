"""Base común de las aplicaciones de chat y reuniones (Teams, Zoom, Discord, Telegram, Slack).

- **Alt+1 a Alt+0** leen el último mensaje, el penúltimo... hasta el décimo
  sin mover el foco (como los scripts de Doug Lee para JAWS). Dos
  pulsaciones lo copian al portapapeles. Los mensajes se toman de la lista de
  mensajes visible y, si no se encuentra, del historial de avisos recibidos.
- **Modos de aviso** (Tiresias+Alt+Mayúsculas+A): todos, solo un sonido o
  ninguno, y en el panel Aplicaciones qué tipos se anuncian (entradas y
  salidas, chat, manos levantadas, silenciar, grabación, compartir pantalla).
- **Sin lecturas dobles** (NVDA #14448): el mismo aviso repetido en poco
  tiempo (notificación + región viva) se lee una sola vez, y las
  descripciones iguales al nombre se descartan.
- **Sin atascos** (NVDA #18507): las ráfagas de eventos de regiones vivas y
  de texto se limitan.
- **Tiresias+Alt+H** muestra el historial de avisos.
"""

from __future__ import annotations

import collections
import time
import unicodedata

from .. import api, speech
from ..baseobject import script
from ..config import conf
from ..i18n import _
from ..log import getLogger
from ..objects.roles import Role
from . import AppModule as BaseAppModule

log = getLogger("chatApps")

CAT = _("Aplicaciones de chat")

ALERT_MODES = [("all", _("todos los avisos")), ("beep", _("solo un sonido")), ("off", _("sin avisos"))]

#: Tipo de aviso -> clave de la configuración que lo activa.
CATEGORY_KEYS = {
	"joinLeave": "alertJoinLeave",
	"chat": "alertChat",
	"hands": "alertHands",
	"mute": "alertMute",
	"recording": "alertRecording",
	"sharing": "alertSharing",
	"other": "alertOther",
}

#: Palabras clave (sin tildes, en minúsculas) para clasificar avisos.
_KEYWORDS = (
	("hands", ("levanto la mano", "levantado la mano", "bajo la mano", "raised hand", "raised their hand", "lowered hand", "mano levantada", "hand raised")),
	("recording", ("grabacion", "grabando", "recording", "transcripcion", "transcription")),
	("sharing", ("comparti", "compartiendo", "is sharing", "started sharing", "stopped sharing", "screen share", "presentando")),
	("mute", ("silencia", "silencio", "muted", "unmuted", "microfono", "microphone")),
	("joinLeave", ("se unio", "se ha unido", "ha salido", "salio de", "abandono", "joined", "has left", "left the", "entered the", "sala de espera", "waiting room", "admitted", "admitido")),
	("chat", ("mensaje", "message", "dijo", "said", "escribio", "wrote", "chat", "respondio", "replied", "menciono", "mentioned")),
)

#: Nombres típicos de las listas de mensajes (sin tildes, en minúsculas).
MESSAGE_LIST_HINTS = ("mensaje", "message", "chat", "conversacion", "conversation", "historial", "history")


def normalize(text: str) -> str:
	decomposed = unicodedata.normalize("NFD", (text or "").casefold())
	return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def classify(text: str) -> str:
	norm = normalize(text)
	for category, words in _KEYWORDS:
		if any(w in norm for w in words):
			return category
	return "other"


class AlertFilter:
	"""Decide qué hacer con cada aviso: ``speak``, ``beep`` o ``ignore``.

	También elimina los repetidos en ``dedupeSeconds`` (NVDA #14448).
	"""

	def __init__(self, dedupeSeconds: float = 2.0) -> None:
		self.dedupeSeconds = dedupeSeconds
		self._recent: dict[str, float] = {}

	def isDuplicate(self, text: str, now: float | None = None) -> bool:
		now = time.monotonic() if now is None else now
		key = normalize(" ".join(text.split()))
		for k, t in list(self._recent.items()):
			if now - t > self.dedupeSeconds:
				del self._recent[k]
		if not key:
			return True
		# También cuenta como repetido un aviso contenido en otro reciente.
		for k in self._recent:
			if key == k or (len(key) > 12 and (key in k or k in key)):
				self._recent[k] = now
				return True
		self._recent[key] = now
		return False

	@staticmethod
	def action(category: str, settings) -> str:
		mode = settings["alertMode"]
		if mode == "off":
			return "ignore"
		key = CATEGORY_KEYS.get(category, "alertOther")
		if not settings[key]:
			return "ignore"
		return "beep" if mode == "beep" else "speak"


class RateLimiter:
	"""Deja pasar como mucho ``limit`` eventos de cada tipo por segundo."""

	def __init__(self, limit: int = 15) -> None:
		self.limit = limit
		self._window: dict[str, collections.deque] = {}

	def allow(self, key: str, now: float | None = None) -> bool:
		now = time.monotonic() if now is None else now
		q = self._window.setdefault(key, collections.deque())
		while q and now - q[0] > 1.0:
			q.popleft()
		if len(q) >= self.limit:
			return False
		q.append(now)
		return True


class ChatAppModule(BaseAppModule):
	"""Módulo base de las aplicaciones de chat."""

	scriptCategory = CAT
	#: Nombres (sin tildes) que identifican la lista de mensajes de la aplicación.
	messageListHints: tuple[str, ...] = MESSAGE_LIST_HINTS
	#: Eventos que se limitan por segundo (ráfagas al desplazarse).
	rateLimitedEvents = ("liveRegionChange", "textChange", "nameChange", "descriptionChange")

	def __init__(self, processID: int, appName: str | None = None) -> None:
		super().__init__(processID, appName)
		self.history: collections.deque[tuple[float, str, str]] = collections.deque(maxlen=max(10, int(conf["chatApps"]["historySize"])))
		self.alertFilter = AlertFilter()
		self.rateLimiter = RateLimiter()
		self._messageListRid: tuple | None = None
		self._lastRead: tuple[int, str] | None = None

	# ------------------------------------------------------------ filtros
	def shouldProcessEvent(self, eventName: str, obj, **kwargs) -> bool:
		if eventName in self.rateLimitedEvents:
			return self.rateLimiter.allow(eventName)
		return True

	def event_NVDAObject_init(self, obj) -> None:
		# Tarjetas y elementos con la descripción igual al nombre: se leían dos veces.
		try:
			if obj.role in (Role.LISTITEM, Role.GROUPING, Role.CUSTOM, Role.SECTION, Role.DATAITEM, Role.BUTTON, Role.ARTICLE):
				desc = obj.description
				name = obj.name
				if desc and name and (normalize(desc) == normalize(name) or normalize(name).endswith(normalize(desc))):
					obj.description = ""
		except Exception:
			pass

	# ------------------------------------------------------------ avisos
	def handleIncoming(self, text: str, source: str = "") -> bool:
		"""Procesa un aviso de la aplicación. ``True`` si se ha encargado de él."""
		text = " ".join((text or "").split())
		if not text:
			return True
		if self.alertFilter.isDuplicate(text):
			return True
		category = classify(text)
		self.history.append((time.time(), text, category))
		action = AlertFilter.action(category, conf["chatApps"])
		if action == "speak":
			speech.speakText(text)
		elif action == "beep":
			from ..audio import tones

			tones.playSound("notification")
		return True

	def event_notification(self, obj, nextHandler, displayString: str = "", **kwargs) -> None:
		if not conf["presentation"]["reportNotifications"]:
			return
		self.handleIncoming(displayString, "notification")

	def event_liveRegionChange(self, obj, nextHandler) -> None:
		if not conf["presentation"]["reportDynamicContentChanges"]:
			return
		try:
			text = obj.name or obj.value
		except Exception:
			text = ""
		self.handleIncoming(text, "liveRegion")

	def event_alert(self, obj, nextHandler) -> None:
		try:
			text = obj.name or ""
			if not text:
				text = " ".join(c.name for c in obj.children if c.name)
		except Exception:
			text = ""
		self.handleIncoming(text, "alert")

	# ------------------------------------------------------------ lista de mensajes
	def findMessageList(self):
		"""La lista de mensajes de la ventana activa (o ``None``)."""
		from ..a11y import uia_client as uc
		from ..objects.uia import UIAObject

		fg = api.getForegroundObject()
		if fg is None or not hasattr(fg, "element"):
			return None
		try:
			cond = uc.createOrCondition([uc.createPropertyCondition(uc.P_CONTROLTYPE, uc.CT_LIST), uc.createPropertyCondition(uc.P_CONTROLTYPE, uc.CT_DATAGRID), uc.createPropertyCondition(uc.P_CONTROLTYPE, uc.CT_TABLE)])
			arr = fg.element.FindAllBuildCache(uc.TreeScope_Descendants, cond, uc.baseCacheRequest)
		except Exception:
			log.debug("No se pudieron buscar listas", exc_info=True)
			return None
		candidates = []
		for i in range(arr.Length if arr else 0):
			o = UIAObject.fromElement(arr.GetElement(i))
			if o is None:
				continue
			candidates.append(o)
		return self.chooseMessageList(candidates)

	def chooseMessageList(self, candidates: list):
		"""Elige la lista de mensajes: primero por nombre y si no, la más larga."""
		best = None
		bestScore = -1
		for o in candidates:
			try:
				name = normalize(o.name)
				score = 0
				if any(h in name for h in self.messageListHints):
					score += 1000
				count = o.childCount
				if count == 0:
					continue
				score += min(count, 999)
			except Exception:
				continue
			if score > bestScore:
				best, bestScore = o, score
		return best

	def messageText(self, item) -> str:
		"""Texto de un mensaje de la lista."""
		try:
			name = item.name
			if name:
				return name
			parts = [c.name for c in item.children if c.name]
			return " ".join(parts)
		except Exception:
			return ""

	def lastMessages(self, n: int) -> list[str]:
		"""Los ``n`` últimos mensajes (el último primero)."""
		lst = self.findMessageList()
		out: list[str] = []
		if lst is not None:
			item = lst.lastChild
			guard = 0
			while item is not None and len(out) < n and guard < n * 4:
				guard += 1
				text = self.messageText(item)
				if text:
					out.append(text)
				item = item.previous
		if not out:
			out = [t for _ts, t, cat in reversed(self.history) if cat in ("chat", "other")][:n]
		return out

	def readNthLast(self, n: int) -> None:
		from ..input import core as inputCore

		msgs = self.lastMessages(n)
		if len(msgs) < n:
			speech.speakMessage(_("No hay {n} mensajes").format(n=n) if n > 1 else _("No hay mensajes"))
			return
		text = msgs[n - 1]
		if inputCore.getLastScriptRepeatCount() >= 1 and self._lastRead == (n, text):
			api.copyToClip(text, notify=True)
			return
		self._lastRead = (n, text)
		speech.cancelSpeech()
		speech.speakText(text)

	# ------------------------------------------------------------ órdenes
	@script(description=_("Cambia el modo de avisos: todos, solo un sonido o ninguno"), category=CAT, gesture="kb:tiresias+alt+shift+a")
	def script_cycleAlertMode(self, gesture) -> None:
		modes = [m for m, _l in ALERT_MODES]
		cur = conf["chatApps"]["alertMode"]
		new = modes[(modes.index(cur) + 1) % len(modes)] if cur in modes else modes[0]
		conf["chatApps"]["alertMode"] = new
		speech.speakMessage(dict(ALERT_MODES)[new])

	@script(description=_("Muestra el historial de avisos y mensajes recibidos"), category=CAT, gesture="kb:tiresias+alt+h")
	def script_alertHistory(self, gesture) -> None:
		from ..gui import app_dialogs

		items = [(f"{time.strftime('%H:%M', time.localtime(ts))} {text}", text) for ts, text, _c in reversed(self.history)]
		if not items:
			speech.speakMessage(_("No se ha recibido ningún aviso"))
			return

		def copy(text: str) -> None:
			from .. import queue_handler

			queue_handler.queueFunction(api.copyToClip, text, True)

		app_dialogs.showItemList("chatHistory", _("Historial de avisos de {app}").format(app=self.appName), [(_("Avisos"), lambda: items)], [app_dialogs.Action(_("&Copiar"), copy, default=True)])


def _addReadScripts() -> None:
	"""Alt+1 a Alt+0: mensaje N contando desde el final (Alt+0 = el décimo)."""
	for n in range(1, 11):
		key = str(n % 10)

		def scriptFunc(self, gesture, _n=n):
			self.readNthLast(_n)

		scriptFunc.__name__ = f"script_readLastMessage{n}"
		desc = _("Lee el último mensaje (dos veces: lo copia)") if n == 1 else _("Lee el mensaje {n} contando desde el final (dos veces: lo copia)").format(n=n)
		decorated = script(description=desc, gesture=f"kb:alt+{key}", category=CAT, speakOnDemand=True)(scriptFunc)
		setattr(ChatAppModule, scriptFunc.__name__, decorated)
		ChatAppModule._classGestures[f"kb:alt+{key}"] = f"readLastMessage{n}"  # type: ignore[attr-defined]


_addReadScripts()
