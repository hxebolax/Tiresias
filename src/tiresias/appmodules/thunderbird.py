"""Mozilla Thunderbird.

- Al abrir un mensaje (Intro o doble clic), la opción «Al abrir un mensaje»
  del panel Aplicaciones decide qué se lee: solo el cuerpo desde el principio
  (NVDA #11161), nada (NVDA #15310) o lo normal del modo exploración.
- Tiresias+Alt+Mayúsculas+H lee las cabeceras del mensaje abierto (De,
  Asunto, Fecha, Para) desde cualquier lugar del mensaje (NVDA #4912).
"""

from __future__ import annotations

from .. import api, speech
from ..baseobject import script
from ..config import conf
from ..i18n import _
from ..objects.roles import Role
from . import AppModule as BaseAppModule

CAT = _("Mozilla Thunderbird")

#: Identificadores de los contenedores del mensaje en Thunderbird 102 y posteriores.
MESSAGE_PANE_IDS = ("messagepane", "messageBrowser", "multiMessageBrowser", "messageBody")
#: Identificadores de las cabeceras del mensaje.
HEADER_IDS = ("expandedfromRow", "expandedsubjectBox", "dateLabel", "expandedtoRow", "expandedccRow", "fromRecipient0", "expandedfromBox", "expandedsubjectRow")


def isMessageDocument(obj, ancestors: list) -> bool:
	try:
		if obj.role != Role.DOCUMENT:
			return False
		return any(getattr(a, "UIAAutomationId", "") in MESSAGE_PANE_IDS for a in ancestors)
	except Exception:
		return False


class AppModule(BaseAppModule):
	scriptCategory = CAT

	def __init__(self, processID: int, appName: str | None = None) -> None:
		super().__init__(processID, appName)
		self._lastMessageDoc = None

	def event_gainFocus(self, obj, nextHandler) -> None:
		mode = conf["mail"]["openMessageReading"]
		ancestors = api.getFocusAncestors()
		if mode == "full" or not isMessageDocument(obj, ancestors):
			nextHandler()
			return
		rid = getattr(obj, "runtimeId", None)
		if rid is not None and rid == self._lastMessageDoc:
			nextHandler()
			return
		self._lastMessageDoc = rid
		# El modo exploración se prepara igualmente; luego se sustituye lo leído.
		nextHandler()
		speech.cancelSpeech()
		if mode == "body":
			from ..speech import sayall

			try:
				from .. import textinfo

				caret = api.getCaretObject()
				info = caret.makeTextInfo(textinfo.POSITION_FIRST)
				info.updateCaret()
			except Exception:
				pass
			sayall.readText(sayall.CURSOR_CARET)

	@script(description=_("Lee las cabeceras del mensaje abierto: de, asunto, fecha y para"), category=CAT, gesture="kb:tiresias+alt+shift+h", speakOnDemand=True)
	def script_readHeaders(self, gesture) -> None:
		from ..a11y import uia_client as uc

		fg = api.getForegroundObject()
		if fg is None or not hasattr(fg, "element"):
			return
		texts = []
		for aid in HEADER_IDS:
			try:
				cond = uc.createPropertyCondition(uc.P_AUTOMATIONID, aid)
				el = fg.element.FindFirstBuildCache(uc.TreeScope_Descendants, cond, uc.baseCacheRequest)
				name = " ".join((el.CachedName or "").split()) if el else ""
				if name and name not in texts:
					texts.append(name)
			except Exception:
				continue
		speech.speakText(". ".join(texts) if texts else _("No hay ningún mensaje abierto"))
