"""Voz de cada idioma para las voces neuronales de Microsoft.

Equivale al complemento global del original NeuralVoices de NVDA (la entrada
«Neural Voices Settings...» del menú Preferencias): un diálogo para elegir
qué voz se usa con cada idioma cuando la voz cambia automáticamente según el
idioma del texto. En Tiresias se abre desde:

- el menú Herramientas de Tiresias («Voces neuronales: voz de cada idioma...»);
- la categoría «Voces neuronales de Microsoft» del cuadro de Opciones;
- una orden sin tecla asignada (se puede asignar en Gestos de entrada).

Solo funciona con el sintetizador «Voces neuronales de Microsoft» en uso: con
otro se avisa de que hay que elegirlo, como el original.
"""

from __future__ import annotations

from typing import Any

from tiresias.baseobject import script
from tiresias.i18n import _
from tiresias.log import getLogger
from tiresias.plugins import GlobalPlugin as _BaseGlobalPlugin

log = getLogger("neuralvoices")

#: Nombre del sintetizador del complemento.
DRIVER_NAME = "neuralvoices"
#: Identificador de la categoría de Opciones y de la entrada del menú Herramientas.
PANEL_ID = "neuralvoices"
MENU_ID = "neuralvoices.vozPorIdioma"

CATEGORY = _("Voces neuronales de Microsoft")
DIALOG_TITLE = _("Voces neuronales: voz de cada idioma")
#: Primera opción de la lista de voces: sin voz fija para ese idioma.
AUTOMATIC = _("Automática (la voz actual o la primera de ese idioma)")


def _isSecureMode() -> bool:
	try:
		from tiresias.config import policy

		return bool(policy.policy.secureMode)
	except Exception:
		return False


def languageDescription(lang: str) -> str:
	"""«Español (España) - es-ES», como el diálogo original."""
	try:
		from tiresias.i18n import languageName

		desc = languageName(lang)
	except Exception:
		desc = ""
	if desc and desc.lower() != lang.lower():
		return f"{desc[:1].upper()}{desc[1:]} - {lang}"
	return lang


# ---------------------------------------------------------------------- núcleo
def snapshot() -> dict[str, Any]:
	"""Estado del sintetizador para el diálogo (hilo del núcleo)."""
	from tiresias import synth as synthHandler

	synth = synthHandler.getSynth()
	if synth is None or synth.name != DRIVER_NAME:
		return {"active": False, "description": (synth.description or synth.name) if synth is not None else _("ninguno")}
	return {
		"active": True,
		"voices": [(v.id, v.displayName) for v in synth.availableVoices.values()],
		"langs": [(lang, languageDescription(lang)) for lang in synth.languagesForMapping()],
		"mapping": synth.getLanguageVoices(),
	}


def applyMapping(mapping: dict[str, str | None]) -> bool:
	"""Guarda la voz de cada idioma en el sintetizador y en la configuración (núcleo)."""
	from tiresias import synth as synthHandler
	from tiresias.config import conf

	synth = synthHandler.getSynth()
	if synth is None or synth.name != DRIVER_NAME:
		return False
	synth.setLanguageVoices(mapping)
	synthHandler.saveCurrentSettings()
	try:
		conf.save()
	except Exception:
		log.exception("No se pudo guardar la configuración")
	return True


def notActiveMessage(description: str) -> str:
	return _(
		"El sintetizador actual es {synth}. Elige «Voces neuronales de Microsoft» como sintetizador "
		"en las opciones de voz de Tiresias (Opciones > Voz > Cambiar sintetizador)."
	).format(synth=description)


# ---------------------------------------------------------------------- interfaz
class MappingEditor:
	"""Listas «Idioma» y «Voz» que asignan una voz a cada idioma (hilo de la interfaz)."""

	def __init__(self, parent, sizer, snap: dict[str, Any]) -> None:
		import wx

		from tiresias.gui.settings import SettingsBuilder

		self.langs: list[str] = [code for code, _label in snap["langs"]]
		self.voiceIds: list[str] = [vid for vid, _label in snap["voices"]]
		self.original: dict[str, str] = {k: v for k, v in snap["mapping"].items() if v in self.voiceIds}
		self.mapping: dict[str, str | None] = dict(self.original)
		builder = SettingsBuilder(parent, sizer)
		self.langChoice = builder.addChoice(_("&Idioma:"), [label for _code, label in snap["langs"]], 0)
		self.voiceChoice = builder.addChoice(_("&Voz:"), [AUTOMATIC] + [label for _vid, label in snap["voices"]], 0)
		self.langChoice.Bind(wx.EVT_CHOICE, self._onLangChoice)
		self.voiceChoice.Bind(wx.EVT_CHOICE, self._onVoiceChoice)
		self._showVoiceForLang()

	def _currentLang(self) -> str | None:
		i = self.langChoice.GetSelection()
		return self.langs[i] if 0 <= i < len(self.langs) else None

	def _showVoiceForLang(self) -> None:
		lang = self._currentLang()
		voiceId = self.mapping.get(lang) if lang else None
		if voiceId in self.voiceIds:
			self.voiceChoice.SetSelection(self.voiceIds.index(voiceId) + 1)
		else:
			self.voiceChoice.SetSelection(0)

	def _onLangChoice(self, evt) -> None:
		self._showVoiceForLang()
		evt.Skip()

	def _onVoiceChoice(self, evt) -> None:
		lang = self._currentLang()
		if lang:
			i = self.voiceChoice.GetSelection()
			self.mapping[lang] = self.voiceIds[i - 1] if 1 <= i <= len(self.voiceIds) else None
		evt.Skip()

	def changes(self) -> dict[str, str | None]:
		"""Idiomas cuya voz ha cambiado: {idioma: voz o None (automática)}."""
		out: dict[str, str | None] = {}
		for lang in set(self.mapping) | set(self.original):
			new = self.mapping.get(lang)
			if new != self.original.get(lang):
				out[lang] = new
		return out

	def accept(self) -> None:
		"""Los cambios guardados pasan a ser el estado original."""
		self.original = {k: v for k, v in self.mapping.items() if v}

	def resetAll(self) -> None:
		"""Todos los idiomas con la voz automática."""
		self.mapping = {lang: None for lang in set(self.mapping) | set(self.original)}
		self._showVoiceForLang()

	def focus(self) -> None:
		self.langChoice.SetFocus()


def _dialogClass():
	import wx

	from tiresias.gui import settings as S

	class NeuralVoicesDialog(wx.Dialog):
		"""Diálogo «Voces neuronales: voz de cada idioma» (no modal, único)."""

		instance: "NeuralVoicesDialog | None" = None

		def __init__(self, parent, snap: dict[str, Any]) -> None:
			super().__init__(parent, title=DIALOG_TITLE, style=wx.DEFAULT_DIALOG_STYLE)
			main = wx.BoxSizer(wx.VERTICAL)
			S.SettingsBuilder(self, main).addStaticText(
				_("Elige la voz que se usará con cada idioma cuando la voz cambie automáticamente según el idioma del texto.")
			)
			self.editor = MappingEditor(self, main, snap)
			buttons = wx.StdDialogButtonSizer()
			ok = wx.Button(self, wx.ID_OK, _("Aceptar"))
			cancel = wx.Button(self, wx.ID_CANCEL, _("Cancelar"))
			buttons.AddButton(ok)
			buttons.AddButton(cancel)
			buttons.Realize()
			main.Add(buttons, 0, wx.ALIGN_RIGHT | wx.TOP, 8)
			ok.SetDefault()
			self.SetAffirmativeId(wx.ID_OK)
			self.SetEscapeId(wx.ID_CANCEL)
			ok.Bind(wx.EVT_BUTTON, self._onOk)
			cancel.Bind(wx.EVT_BUTTON, lambda evt: self._close())
			self.Bind(wx.EVT_CLOSE, lambda evt: self._close())
			outer = wx.BoxSizer(wx.VERTICAL)
			outer.Add(main, 1, wx.EXPAND | wx.ALL, 10)
			self.SetSizer(outer)
			outer.Fit(self)
			self.CentreOnScreen()
			self.editor.focus()

		def _onOk(self, evt) -> None:
			changes = self.editor.changes()
			if changes:
				S.runOnCore(applyMapping, changes)
			self._close()

		def _close(self) -> None:
			if NeuralVoicesDialog.instance is self:
				NeuralVoicesDialog.instance = None
			self.Hide()
			self.Destroy()

	return NeuralVoicesDialog


_dialogCls = None


def _showDialog(snap: dict[str, Any] | None) -> None:
	"""Muestra el diálogo con el estado leído en el núcleo (hilo de la interfaz)."""
	global _dialogCls
	from tiresias import gui
	from tiresias.gui import settings as S

	if snap is None:
		return
	if not snap.get("active"):
		import wx

		gui.messageBox(notActiveMessage(snap.get("description", "")), _("Aviso"), wx.OK | wx.ICON_WARNING)
		return
	if _dialogCls is None:
		_dialogCls = _dialogClass()
	dlg = _dialogCls.instance
	if dlg is None or not S.isAlive(dlg):
		dlg = _dialogCls(S.parentWindow(), snap)
		_dialogCls.instance = dlg
	S.presentDialog(dlg)


def openDialog() -> None:
	"""Abre el diálogo de la voz de cada idioma (desde cualquier hilo)."""
	from tiresias.gui import settings as S
	from tiresias.gui.helpers import runOnGui

	runOnGui(lambda: S.runOnCore(snapshot, callback=_showDialog))


def _panelClass():
	from tiresias.gui import settings as S

	class NeuralVoicesPanel(S.SettingsPanel):
		"""Categoría «Voces neuronales de Microsoft» del cuadro de Opciones."""

		title = CATEGORY

		def makeSettings(self, sizer) -> None:
			self.editor: MappingEditor | None = None
			self._sizer = sizer
			self._status = S.SettingsBuilder(self, sizer).addStaticText(_("Cargando..."))
			S.runOnCore(snapshot, callback=self._onSnapshot)

		def _onSnapshot(self, snap: dict[str, Any] | None) -> None:
			if not S.isAlive(self):
				return
			if snap is None:
				self._status.SetLabel(_("No se pudo leer el estado de las voces neuronales."))
				self.relayout()
				return
			if not snap.get("active"):
				self._status.SetLabel(notActiveMessage(snap.get("description", "")))
				self._status.Wrap(450)
				self.relayout()
				return
			self._status.SetLabel(
				_(
					"Voz que se usa con cada idioma cuando la voz cambia automáticamente según el idioma del texto. "
					"La velocidad, el tono, el volumen y la detección del idioma están en la categoría Voz."
				)
			)
			self._status.Wrap(450)
			self.editor = MappingEditor(self, self._sizer, snap)
			self.relayout()

		def onSave(self) -> None:
			if self.editor is None:
				return
			changes = self.editor.changes()
			if changes:
				queueApply(changes)
				self.editor.accept()

		def resetToFactory(self) -> None:
			if self.editor is not None:
				self.editor.resetAll()

	return NeuralVoicesPanel


def queueApply(changes: dict[str, str | None]) -> None:
	from tiresias import queue_handler

	queue_handler.queueFunction(applyMapping, changes)


# ---------------------------------------------------------------------- complemento global
class GlobalPlugin(_BaseGlobalPlugin):
	def __init__(self) -> None:
		super().__init__()
		self._registered = False
		if _isSecureMode():
			# Como el original: en modo seguro no se añaden menús ni opciones.
			return
		try:
			from tiresias import gui

			gui.registerToolsMenuItem(MENU_ID, _("&Voces neuronales: voz de cada idioma..."), openDialog)
			self._registered = True
		except Exception:
			log.debug("No se pudo añadir la entrada al menú Herramientas", exc_info=True)
		try:
			from tiresias.gui import settings as S

			cls = _panelClass()
			S.registerPanel(PANEL_ID, cls.title, cls)
		except Exception:
			log.debug("No se pudo añadir la categoría de las voces neuronales a las opciones", exc_info=True)

	@script(
		description=_("Abre el diálogo de las voces neuronales de Microsoft para elegir la voz de cada idioma"),
		category=CATEGORY,
	)
	def script_vozPorIdioma(self, gesture) -> None:
		if _isSecureMode():
			from tiresias import speech

			speech.speakMessage(_("No disponible en modo seguro"))
			return
		openDialog()

	def terminate(self) -> None:
		try:
			from tiresias import gui

			gui.unregisterToolsMenuItem(MENU_ID)
		except Exception:
			pass
		try:
			from tiresias.gui import settings as S

			S.unregisterPanel(PANEL_ID)
		except Exception:
			pass
		dlg = _dialogCls.instance if _dialogCls is not None else None
		if dlg is not None:
			try:
				from tiresias.gui.helpers import runOnGui

				runOnGui(dlg._close)
			except Exception:
				pass
