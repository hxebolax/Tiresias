"""Interfaz de la inteligencia artificial: chat, aviso de privacidad, confirmación
del agente y panel de opciones «Inteligencia artificial».
"""

from __future__ import annotations

from typing import Any, Callable

import wx

from . import message_dialog
from .. import queue_handler
from ..i18n import _
from ..log import getLogger
from . import settings
from .helpers import addLabel, bringToFront, isAlive, runOnGui

log = getLogger("gui.ai")


# ====================================================================== chat
class ChatDialog(wx.Dialog):
	"""Conversación accesible: historial de solo lectura y campo de pregunta."""

	def __init__(self, session: Any) -> None:
		super().__init__(None, title=session.title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
		self.session = session
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, _("&Conversación:"))
		self.history = wx.TextCtrl(self, size=(640, 360), style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
		sizer.Add(self.history, 1, wx.EXPAND | wx.ALL, 6)
		addLabel(self, sizer, _("&Pregunta (Intro para enviar):"))
		self.question = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER, size=(640, -1))
		sizer.Add(self.question, 0, wx.EXPAND | wx.ALL, 6)
		buttons = wx.BoxSizer(wx.HORIZONTAL)
		self.send = wx.Button(self, label=_("&Enviar"))
		self.copy = wx.Button(self, label=_("Copiar la última respues&ta"))
		close = wx.Button(self, wx.ID_CANCEL, _("Ce&rrar"))
		for b in (self.send, self.copy, close):
			buttons.Add(b, 0, wx.RIGHT, 6)
		sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 6)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.send.Bind(wx.EVT_BUTTON, lambda evt: self.onSend())
		self.question.Bind(wx.EVT_TEXT_ENTER, lambda evt: self.onSend())
		self.copy.Bind(wx.EVT_BUTTON, lambda evt: self.onCopy())
		self.Bind(wx.EVT_BUTTON, lambda evt: self.Close(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, self.onClose)
		self.refresh()
		self.CentreOnScreen()

	@staticmethod
	def formatTranscript(transcript: list[tuple[str, str]]) -> str:
		parts = []
		for role, text in transcript:
			who = _("Tú") if role == "user" else _("Asistente")
			parts.append(f"{who}: {text}")
		return "\n\n".join(parts)

	def refresh(self) -> None:
		text = self.formatTranscript(self.session.transcript)
		self.history.SetValue(text)
		# El cursor queda al principio de la última respuesta.
		lastStart = text.rfind(_("Asistente") + ":")
		pos = max(0, lastStart)
		self.history.SetInsertionPoint(pos)
		self.history.ShowPosition(pos)

	def onSend(self) -> None:
		q = self.question.GetValue().strip()
		if not q:
			wx.Bell()
			return
		if self.session.busy:
			from .helpers import speakMessage

			speakMessage(_("Espera: todavía no ha llegado la respuesta anterior"))
			return
		self.question.SetValue("")
		session = self.session

		def ask() -> None:
			from .. import speech

			if session.busy:
				# Otra pregunta se envió entretanto: ask() ya lo dice y no envía nada.
				session.ask(q, onAnswer=self._answered, onError=self._failed)
				return
			speech.speakMessage(_("Enviado"))
			session.ask(q, onAnswer=self._answered, onError=self._failed)
			runOnGui(self._afterAnswer)

		queue_handler.queueFunction(ask)

	def _answered(self, text: str) -> None:
		from .. import speech

		runOnGui(self._afterAnswer)
		speech.speakText(text)

	def _afterAnswer(self) -> None:
		if isAlive(self):
			self.refresh()

	def _failed(self, error: str) -> None:
		from .. import speech

		speech.speakMessage(error)
		runOnGui(self._afterAnswer)

	def onCopy(self) -> None:
		answers = [t for r, t in self.session.transcript if r == "assistant"]
		if not answers:
			wx.Bell()
			return
		from .. import api

		queue_handler.queueFunction(api.copyToClip, answers[-1], True)

	def onClose(self, evt: wx.CloseEvent) -> None:
		global _chat
		if _chat is self:
			_chat = None
		self.Destroy()


_chat: ChatDialog | None = None


def showChat(session: Any) -> None:
	"""Abre (o reutiliza) el diálogo de chat con la sesión indicada (seguro desde cualquier hilo)."""

	def _show() -> None:
		global _chat
		if isAlive(_chat):
			_chat.Destroy()
		_chat = ChatDialog(session)
		_chat.Show()
		bringToFront(_chat)
		_chat.history.SetFocus()

	runOnGui(_show)


# ====================================================================== privacidad
def privacyText(providerName: str, insecure: bool = False) -> str:
	if insecure:
		return _(
			"Vas a enviar una imagen de tu pantalla a {name}, que está en otro equipo, para que la describa. La imagen puede "
			"contener datos personales (mensajes, nombres, documentos abiertos). La dirección empieza por http://, así que se "
			"envía SIN CIFRAR: cualquiera en la red podría verla. Tiresias no guarda copia. Para no enviar nada fuera del "
			"equipo, usa un servidor en este mismo equipo (localhost) en Opciones, Inteligencia artificial.\n\n¿Quieres continuar?"
		).format(name=providerName)
	return _(
		"Vas a enviar una imagen de tu pantalla a {name} para que la describa. La imagen puede contener datos personales "
		"(mensajes, nombres, documentos abiertos). Se envía directamente desde tu equipo y se rige por la política de "
		"privacidad de {name}; Tiresias no guarda copia. Para no enviar nada fuera del equipo puedes usar un servidor "
		"local (Ollama o LM Studio) en este mismo equipo, en Opciones, Inteligencia artificial.\n\n¿Quieres continuar?"
	).format(name=providerName)


def showPrivacyNotice(providerName: str, onAccept: Callable[[], None], insecure: bool = False) -> None:
	"""Aviso de privacidad la primera vez que se envía una imagen a cada destino."""

	def _show() -> None:
		dlg = message_dialog.MessageDialog(None, privacyText(providerName, insecure), _("Privacidad: envío de imágenes"), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_INFORMATION)
		dlg.SetYesNoLabels(_("&Enviar"), _("&Cancelar"))
		res = dlg.ShowModal()
		dlg.Destroy()
		if res == wx.ID_YES:
			onAccept()
		else:
			from .helpers import speakMessage

			speakMessage(_("No se ha enviado nada"))

	runOnGui(_show)


# ====================================================================== orden de lectura
class OrderConfirmDialog(wx.Dialog):
	"""Orden de lectura propuesto por la IA: se revisa y se aplica o no (foros 3.10)."""

	def __init__(self, title: str, preview: str, onAccept: Callable[[], None]) -> None:
		super().__init__(None, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.onAccept = onAccept
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, _("&Nuevo orden de lectura (principio de cada bloque):"))
		self.preview = wx.TextCtrl(self, value=preview, size=(560, 300), style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
		sizer.Add(self.preview, 1, wx.EXPAND | wx.ALL, 6)
		sizer.Add(wx.StaticText(self, label=_("Si lo aplicas, puedes deshacerlo con la orden «deshacer el último cambio del orden de lectura».")), 0, wx.ALL, 6)
		row = wx.BoxSizer(wx.HORIZONTAL)
		apply = wx.Button(self, wx.ID_OK, _("&Aplicar este orden"))
		cancel = wx.Button(self, wx.ID_CANCEL, _("&Cancelar"))
		row.Add(apply, 0, wx.RIGHT, 6)
		row.Add(cancel, 0)
		sizer.Add(row, 0, wx.ALIGN_RIGHT | wx.ALL, 6)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		apply.Bind(wx.EVT_BUTTON, lambda evt: self.finish(True))
		cancel.Bind(wx.EVT_BUTTON, lambda evt: self.finish(False))
		self.Bind(wx.EVT_CLOSE, lambda evt: self.finish(False))
		self.CentreOnScreen()

	def finish(self, accepted: bool) -> None:
		callback, self.onAccept = self.onAccept, None
		self.Destroy()
		if accepted and callback is not None:
			callback()
		elif not accepted and callback is not None:
			from .helpers import speakMessage

			speakMessage(_("Orden de lectura sin cambios"))


def showOrderConfirm(title: str, preview: str, onAccept: Callable[[], None]) -> None:
	def _show() -> None:
		dlg = OrderConfirmDialog(title, preview, onAccept)
		dlg.Show()
		bringToFront(dlg)
		dlg.preview.SetFocus()

	runOnGui(_show)


# ====================================================================== agente
class AgentConfirmDialog(wx.Dialog):
	def __init__(self, description: str, callback: Callable[[str], None]) -> None:
		super().__init__(None, title=_("El agente quiere actuar"))
		self.callback = callback
		self._answered = False
		sizer = wx.BoxSizer(wx.VERTICAL)
		text = wx.TextCtrl(self, value=description, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(480, 90))
		addLabel(self, sizer, _("&Acción propuesta:"))
		sizer.Add(text, 1, wx.EXPAND | wx.ALL, 6)
		row = wx.BoxSizer(wx.HORIZONTAL)
		yes = wx.Button(self, wx.ID_YES, _("&Sí, hazlo"))
		no = wx.Button(self, wx.ID_NO, _("&No, busca otra forma"))
		stop = wx.Button(self, wx.ID_STOP, _("&Detener el agente"))
		for b in (yes, no, stop):
			row.Add(b, 0, wx.RIGHT, 6)
		sizer.Add(row, 0, wx.ALL, 6)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_STOP)
		yes.Bind(wx.EVT_BUTTON, lambda evt: self.answer("yes"))
		no.Bind(wx.EVT_BUTTON, lambda evt: self.answer("no"))
		stop.Bind(wx.EVT_BUTTON, lambda evt: self.answer("stop"))
		self.Bind(wx.EVT_CLOSE, lambda evt: self.answer("stop"))
		no.SetDefault()
		self.CentreOnScreen()

	def answer(self, choice: str) -> None:
		global _agentDialog
		# Primero se cierra el diálogo y después se responde (el agente además
		# espera un momento y devuelve el primer plano a su ventana).
		first = not self._answered
		callback = self.callback
		self._answered = True
		if _agentDialog is self:
			_agentDialog = None
		self.Destroy()
		if first:
			callback(choice)


_agentDialog: AgentConfirmDialog | None = None


def showAgentConfirm(description: str, callback: Callable[[str], None]) -> None:
	def _show() -> None:
		global _agentDialog
		if isAlive(_agentDialog):
			_agentDialog.Destroy()
		_agentDialog = AgentConfirmDialog(description, callback)
		_agentDialog.Show()
		bringToFront(_agentDialog)

	runOnGui(_show)


def closeAgentConfirm() -> None:
	def _close() -> None:
		global _agentDialog
		if isAlive(_agentDialog):
			_agentDialog._answered = True
			_agentDialog.Destroy()
		_agentDialog = None

	runOnGui(_close)


# ====================================================================== opciones
def _providerChoices():
	from ..ai.providers import PROVIDERS

	return [(pid, p.name) for pid, p in PROVIDERS.items()]


def _anthropicModels():
	from ..ai.providers import ANTHROPIC_MODELS

	return [(mid, f"{label}, {mid}") for mid, label in ANTHROPIC_MODELS]


def keyStateLabel(pid: str) -> str:
	"""Estado de la clave de un proveedor para la etiqueta de su cuadro."""
	from ..ai import keys

	if keys.hasStoredKey(pid):
		return _("hay una guardada")
	var = keys.envKeyVariable(pid)
	if var:
		return _("se usa la de la variable de entorno {var}").format(var=var)
	return _("no hay ninguna guardada")


def _languageChoices():
	from ..ai.translate import LANGUAGES

	return list(LANGUAGES)


def _duckChoices():
	return [("lower", _("Bajarla")), ("mute", _("Silenciarla")), ("off", _("No cambiarla"))]


class AiPanel(settings.ConfigPanel):
	title = _("Inteligencia artificial")
	section = "ai"

	def getFields(self) -> list[settings.Field]:
		from ..ai import assistant  # noqa: F401  (registra los valores por defecto)

		F = settings
		return [
			F.Choice("provider", _("P&roveedor:"), _providerChoices),
			F.Choice("anthropicModel", _("Modelo de Claude:"), _anthropicModels, group=_("Modelos")),
			F.Text("anthropicCustomModel", _("Otro modelo de Claude (identificador; vacío: el de la lista):"), group=_("Modelos")),
			F.Text("openaiModel", _("Modelo de OpenAI:"), group=_("Modelos")),
			F.Text("geminiModel", _("Modelo de Gemini:"), group=_("Modelos")),
			F.Text("localUrl", _("Dirección del servidor local (compatible con OpenAI):"), group=_("Modelos")),
			F.Text("localModel", _("Modelo del servidor local:"), group=_("Modelos")),
			F.Int("localMaxContextChars", _("Máximo de caracteres de un documento para el servidor local:"), 1000, 2000000, group=_("Modelos")),
			F.Text("responseLanguage", _("Idioma de las respuestas:")),
			F.Bool("resultInDialog", _("Mostrar las respuestas en la ventana de conversación (si no, solo se leen)")),
			F.Int("timeout", _("Tiempo máximo de espera de una respuesta (segundos):"), 10, 600),
			F.Int("maxContextChars", _("Máximo de caracteres de un documento que se envían:"), 1000, 2000000),
			F.Bool("imagePrivacyAccepted", _("Ya he leído el aviso de privacidad del envío de imágenes")),
			F.Choice("translateTo", _("Traducir al idioma:"), _languageChoices, group=_("Traducción")),
			F.Bool("translateSpeech", _("Traducir todo lo que dice Tiresias"), group=_("Traducción")),
			F.Int("agentMaxSteps", _("Máximo de pasos del agente de IA:"), 1, 100),
			# Etiquetado automático (foros 6.3).
			F.Bool("autoLabel", _("Etiquetar automáticamente con IA los elementos sin nombre (envía imágenes y gasta peticiones)"), group=_("Etiquetado automático")),
			F.Int("autoLabelMaxPerHour", _("Máximo de etiquetas automáticas por hora:"), 1, 500, group=_("Etiquetado automático")),
			F.Bool("autoLabelSave", _("Guardar las etiquetas automáticas para las próximas veces"), group=_("Etiquetado automático")),
			# Explorar la página (foros 6.6) y PDF (foros 3.10).
			F.Bool("exploreWithScreenshot", _("Al explorar la página, enviar también una captura de la ventana (diseño visual)"), group=_("Páginas y documentos")),
			F.Int("altTextMaxImages", _("Máximo de imágenes que se describen de una vez:"), 1, 200, group=_("Páginas y documentos")),
			# CAPTCHA (foros 10.6).
			F.Bool("captchaDetect", _("Detectar y anunciar los CAPTCHA"), group=_("CAPTCHA")),
			F.Choice("captchaDuckMode", _("Voz del lector mientras suena el audio del reto:"), _duckChoices, group=_("CAPTCHA")),
			F.Int("captchaDuckVolume", _("Volumen de la voz baja (por ciento):"), 0, 100, group=_("CAPTCHA")),
			F.Int("captchaDuckSeconds", _("Segundos con la voz baja o en silencio:"), 3, 120, group=_("CAPTCHA")),
		]

	def makeExtraSettings(self, builder: settings.SettingsBuilder) -> None:
		from ..ai import keys
		from ..ai.providers import PROVIDERS

		grp = builder.group(_("Claves (se guardan cifradas para tu usuario de Windows)"))
		self._keyCtrls: dict[str, wx.TextCtrl] = {}
		self._keyClear: dict[str, wx.CheckBox] = {}
		for pid, p in PROVIDERS.items():
			if not p.needsKey:
				continue
			stored = keys.hasStoredKey(pid)
			label = _("Clave de {name} ({state}):").format(name=p.name, state=keyStateLabel(pid))
			self._keyCtrls[pid] = grp.addText(label, "", style=wx.TE_PASSWORD)
			self._keyClear[pid] = grp.addCheckBox(_("Borrar la clave guardada de {name}").format(name=p.name), False)
			if not stored:
				self._keyClear[pid].Disable()
		grp.addStaticText(_("Deja el cuadro vacío para conservar la clave actual."))

	def isValid(self) -> bool:
		from .helpers import urlProblem

		for key in ("localUrl",):
			problem = urlProblem(self.getValue(key) or "")
			if problem:
				settings.showError(problem, self)
				ctrl = self.getControl(key)
				if ctrl:
					ctrl.SetFocus()
				return False
		return True

	def onSave(self) -> None:
		super().onSave()
		from .. import queue_handler as qh
		from ..ai import keys
		from ..ai.providers import PROVIDERS, configMessage, getProvider
		from ..config import conf

		for pid, ctrl in getattr(self, "_keyCtrls", {}).items():
			value = ctrl.GetValue().strip()
			try:
				if value:
					keys.setKey(pid, value)
					ctrl.SetValue("")
					self._keyClear[pid].Enable()
				elif self._keyClear[pid].GetValue():
					keys.setKey(pid, None)
					self._keyClear[pid].SetValue(False)
					self._keyClear[pid].Disable()
			except keys.InvalidKeyError:
				# El mensaje nunca incluye la clave.
				settings.showError(
					_("La clave de {name} tiene caracteres que no pueden formar parte de una clave (letras con tilde, símbolos o caracteres especiales). Cópiala de nuevo desde la web del servicio. No se ha guardado.").format(name=PROVIDERS[pid].name),
					self,
				)
			except OSError:
				log.exception("No se pudo guardar la clave")
				settings.showError(_("No se pudo guardar la clave cifrada."), self)
		# «Traducir todo lo que dice Tiresias» sin un servicio listo fallaría con cada frase.
		if conf["ai"]["translateSpeech"]:
			problem = configMessage(getProvider())
			if problem:
				conf["ai"]["translateSpeech"] = False
				self.setControlValue("translateSpeech", False)
				b = getattr(self, "_bound", {}).get(("ai", "translateSpeech"))
				if b is not None:
					b.original = False
				settings.showError(problem + " " + _("La traducción de todo lo que se dice queda desactivada."), self)

		def resetAutoLabel() -> None:
			try:
				from ..ai.autolabel import autoLabeler

				autoLabeler.resetErrors()
			except Exception:
				log.debug("No se pudo reiniciar el etiquetado automático", exc_info=True)

		# Una clave o un modelo corregidos vuelven a poner en marcha el etiquetado automático.
		qh.queueFunction(resetAutoLabel)
