"""Diálogo «Mezclador de audio» y categoría de opciones «Sonidos».

El diálogo es no modal y accesible: cada control tiene su etiqueta delante y
los cambios se aplican al momento (en el hilo del núcleo, que es el que usa
Core Audio). La lista de aplicaciones se puede actualizar con su botón o con
F5.
"""

from __future__ import annotations

import os
from typing import Any

import wx

from . import message_dialog
from .. import paths, queue_handler
from ..config import conf
from ..i18n import _
from ..log import getLogger
from . import settings as S

log = getLogger("gui.audio")


# ====================================================================== mezclador
def _snapshot() -> dict:
	"""Estado del audio del sistema (hilo del núcleo)."""
	from ..audio import core_audio, mixer

	snap: dict[str, Any] = {}
	snap["outputs"] = [(d.id, d.name, d.isDefault) for d in mixer.outputDevices()]
	snap["inputs"] = [(d.id, d.name, d.isDefault) for d in mixer.inputDevices()]
	try:
		snap["master"] = mixer.getMasterVolume()
	except Exception:
		snap["master"] = None
	try:
		snap["mic"] = mixer.getMicState() if snap["inputs"] else None
	except Exception:
		snap["mic"] = None
	snap["tiresias"] = mixer.tiresiasOutputChoices()
	snap["tiresiasCurrent"] = conf["audio"]["outputDevice"]
	apps = []
	for app in mixer.listApps():
		apps.append((app.key, app.name, app.volume(), app.muted(), app.isOwn))
	snap["apps"] = apps
	snap["ownPid"] = core_audio.OWN_PID
	return snap


class MixerDialog(wx.Dialog):
	def __init__(self, parent: wx.Window | None) -> None:
		super().__init__(parent, title=_("Mezclador de audio"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._snap: dict | None = None
		self._apps: list[tuple] = []
		main = wx.BoxSizer(wx.VERTICAL)
		root = S.SettingsBuilder(self, main)

		g = root.group(_("Sonido del sistema"))
		self.outputChoice = g.addChoice(_("Dispositivo de &salida predeterminado de Windows:"), [_("Cargando...")])
		self.setOutputBtn = g.addButton(_("Usar como salida &predeterminada"))
		self.masterSlider = g.addSlider(_("&Volumen general:"), 0, 100, 0, 1, 10)
		self.masterMute = g.addCheckBox(_("Silenciar el s&onido del sistema"))

		g = root.group(_("Micrófono"))
		self.inputChoice = g.addChoice(_("&Micrófono predeterminado:"), [_("Cargando...")])
		self.setInputBtn = g.addButton(_("Usar como micrófono pre&determinado"))
		self.micSlider = g.addSlider(_("Volumen del mi&crófono:"), 0, 100, 0, 1, 10)
		self.micMute = g.addCheckBox(_("Micrófono si&lenciado"))

		g = root.group(_("Tiresias"))
		self.tiresiasChoice = g.addChoice(_("Dispositivo de salida de &Tiresias:"), [_("Cargando...")])

		g = root.group(_("Aplicaciones"))
		self.appList = g.addLabeledControl(
			_("&Aplicaciones con sonido:"),
			lambda p: wx.ListBox(p, choices=[], style=wx.LB_SINGLE, size=(420, 160)),
			vertical=True,
			proportion=1,
		)
		self.appSlider = g.addSlider(_("Volumen de la aplicación seleccio&nada:"), 0, 100, 0, 1, 10)
		self.appMute = g.addCheckBox(_("Silenciar la apl&icación seleccionada"))
		self.refreshBtn = g.addButton(_("Act&ualizar (F5)"))

		buttons = wx.StdDialogButtonSizer()
		close = wx.Button(self, wx.ID_CLOSE, _("Cerrar"))
		buttons.AddButton(close)
		buttons.Realize()
		main.Add(buttons, 0, wx.ALIGN_RIGHT | wx.TOP, 8)
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(main, 1, wx.EXPAND | wx.ALL, 10)
		self.SetSizer(outer)
		outer.Fit(self)
		self.SetEscapeId(wx.ID_CLOSE)

		close.Bind(wx.EVT_BUTTON, lambda evt: self._close())
		self.Bind(wx.EVT_CLOSE, lambda evt: self._close())
		self.setOutputBtn.Bind(wx.EVT_BUTTON, self._onSetOutput)
		self.setInputBtn.Bind(wx.EVT_BUTTON, self._onSetInput)
		self.masterSlider.Bind(wx.EVT_SLIDER, lambda evt: self._core(self._applyMaster, self.masterSlider.GetValue()))
		self.masterMute.Bind(wx.EVT_CHECKBOX, lambda evt: self._core(self._applyMasterMute, self.masterMute.GetValue()))
		self.micSlider.Bind(wx.EVT_SLIDER, lambda evt: self._core(self._applyMic, self.micSlider.GetValue()))
		self.micMute.Bind(wx.EVT_CHECKBOX, lambda evt: self._core(self._applyMicMute, self.micMute.GetValue()))
		self.tiresiasChoice.Bind(wx.EVT_CHOICE, self._onTiresiasDevice)
		self.appList.Bind(wx.EVT_LISTBOX, lambda evt: self._showApp())
		self.appSlider.Bind(wx.EVT_SLIDER, self._onAppVolume)
		self.appMute.Bind(wx.EVT_CHECKBOX, self._onAppMute)
		self.refreshBtn.Bind(wx.EVT_BUTTON, lambda evt: self.refresh())
		self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)
		self.CentreOnScreen()
		self.masterSlider.SetFocus()
		self.refresh()

	# ------------------------------------------------------------ datos
	def refresh(self) -> None:
		S.runOnCore(_snapshot, callback=self._onSnapshot)

	def _onSnapshot(self, snap: dict | None) -> None:
		if not S.isAlive(self) or snap is None:
			return
		self._snap = snap
		self._fillChoice(self.outputChoice, snap["outputs"], _("No hay dispositivos de salida"))
		self._fillChoice(self.inputChoice, snap["inputs"], _("No hay micrófonos"))
		self.setOutputBtn.Enable(bool(snap["outputs"]))
		self.setInputBtn.Enable(bool(snap["inputs"]))
		if snap["master"] is not None:
			self.masterSlider.SetValue(snap["master"][0])
			self.masterMute.SetValue(snap["master"][1])
		hasMic = snap["mic"] is not None
		self.micSlider.Enable(hasMic)
		self.micMute.Enable(hasMic)
		if hasMic:
			self.micSlider.SetValue(snap["mic"][0])
			self.micMute.SetValue(snap["mic"][1])
		values = [v for v, _n in snap["tiresias"]]
		labels = [n for _v, n in snap["tiresias"]]
		cur = snap["tiresiasCurrent"]
		if cur not in values:
			values.append(cur)
			labels.append(cur)
		self._tiresiasValues = values
		self.tiresiasChoice.Set(labels)
		self.tiresiasChoice.SetSelection(values.index(cur))
		prevKey = self._selectedAppKey()
		self._apps = snap["apps"]
		self.appList.Set([self._appLabel(a) for a in self._apps])
		keys = [a[0] for a in self._apps]
		if self._apps:
			self.appList.SetSelection(keys.index(prevKey) if prevKey in keys else 0)
		self._showApp()

	@staticmethod
	def _fillChoice(ctrl: wx.Choice, devices: list, empty: str) -> None:
		if not devices:
			ctrl.Set([empty])
			ctrl.SetSelection(0)
			return
		ctrl.Set([name + (" " + _("(predeterminado)") if isDefault else "") for _id, name, isDefault in devices])
		sel = next((i for i, d in enumerate(devices) if d[2]), 0)
		ctrl.SetSelection(sel)

	@staticmethod
	def _appLabel(app: tuple) -> str:
		key, name, vol, muted, _own = app
		text = _("{name}: {vol} %").format(name=name, vol=vol)
		return text + (", " + _("silenciada") if muted else "")

	def _selectedAppKey(self) -> str | None:
		i = self.appList.GetSelection()
		return self._apps[i][0] if 0 <= i < len(self._apps) else None

	def _showApp(self) -> None:
		i = self.appList.GetSelection()
		has = 0 <= i < len(self._apps)
		self.appSlider.Enable(has)
		self.appMute.Enable(has)
		if has:
			self.appSlider.SetValue(self._apps[i][2])
			self.appMute.SetValue(self._apps[i][3])

	# ------------------------------------------------------------ cambios
	@staticmethod
	def _core(func, *args) -> None:
		queue_handler.queueFunction(func, *args)

	@staticmethod
	def _applyMaster(value: int) -> None:
		from ..audio import mixer

		mixer.setMasterVolume(value)

	@staticmethod
	def _applyMasterMute(mute: bool) -> None:
		from ..audio import mixer

		mixer.setMasterMute(mute)

	@staticmethod
	def _applyMic(value: int) -> None:
		from ..audio import mixer

		mixer.setMicVolume(value)

	@staticmethod
	def _applyMicMute(mute: bool) -> None:
		from ..audio import mixer, tones

		mixer.setMicMute(mute)
		if conf["audio"]["micMuteSounds"]:
			tones.playSound("micMuted" if mute else "micUnmuted")

	def _onSetOutput(self, evt) -> None:
		devices = (self._snap or {}).get("outputs") or []
		i = self.outputChoice.GetSelection()
		if not 0 <= i < len(devices):
			return
		devId, name = devices[i][0], devices[i][1]

		def apply() -> None:
			from ..audio import mixer, tones

			mixer.setDefaultOutput(devId)
			tones.playSound("deviceChange")

		S.runOnCore(apply, callback=lambda _r: (S.speakMessageOnCore(_("{name} es ahora la salida predeterminada").format(name=name)), self.refresh()))

	def _onSetInput(self, evt) -> None:
		devices = (self._snap or {}).get("inputs") or []
		i = self.inputChoice.GetSelection()
		if not 0 <= i < len(devices):
			return
		devId, name = devices[i][0], devices[i][1]

		def apply() -> None:
			from ..audio import mixer

			mixer.setDefaultInput(devId)

		S.runOnCore(apply, callback=lambda _r: (S.speakMessageOnCore(_("{name} es ahora el micrófono predeterminado").format(name=name)), self.refresh()))

	def _onTiresiasDevice(self, evt) -> None:
		i = self.tiresiasChoice.GetSelection()
		values = getattr(self, "_tiresiasValues", [])
		if not 0 <= i < len(values):
			return
		value = values[i]

		def apply() -> None:
			from ..audio import mixer, tones

			mixer.setTiresiasOutput(value)
			tones.playSound("deviceChange")

		queue_handler.queueFunction(apply)

	def _onAppVolume(self, evt) -> None:
		key = self._selectedAppKey()
		if key is None:
			return
		value = self.appSlider.GetValue()

		def apply() -> None:
			from ..audio import mixer

			app = mixer.findApp(key)
			if app is not None:
				app.setVolume(value)

		queue_handler.queueFunction(apply)
		i = self.appList.GetSelection()
		k, name, _v, muted, own = self._apps[i]
		self._apps[i] = (k, name, value, muted, own)
		self.appList.SetString(i, self._appLabel(self._apps[i]))

	def _onAppMute(self, evt) -> None:
		key = self._selectedAppKey()
		if key is None:
			return
		mute = self.appMute.GetValue()

		def apply() -> None:
			from ..audio import mixer

			app = mixer.findApp(key)
			if app is not None:
				app.setMute(mute)

		queue_handler.queueFunction(apply)
		i = self.appList.GetSelection()
		k, name, vol, _m, own = self._apps[i]
		self._apps[i] = (k, name, vol, mute, own)
		self.appList.SetString(i, self._appLabel(self._apps[i]))

	def _onCharHook(self, evt: wx.KeyEvent) -> None:
		if evt.GetKeyCode() == wx.WXK_F5 and not evt.HasAnyModifiers():
			self.refresh()
			S.speakMessageOnCore(_("Actualizado"))
			return
		evt.Skip()

	def _close(self) -> None:
		global _mixerDialog
		if _mixerDialog is self:
			_mixerDialog = None
		self.Hide()
		self.Destroy()


_mixerDialog: MixerDialog | None = None


def showMixer() -> None:
	"""Abre (o trae al frente) el mezclador de audio (hilo de la interfaz)."""
	global _mixerDialog
	if _mixerDialog is None or not S.isAlive(_mixerDialog):
		_mixerDialog = MixerDialog(S.parentWindow())
	S.presentDialog(_mixerDialog)


# Las opciones del mezclador están en la categoría «Audio» (grupo «Volumen del sistema y mezclador»).


# ====================================================================== opciones: sonidos
_EARCON_MODES = [
	("off", _("Desactivados")),
	("withSpeech", _("Sonido y voz")),
	("insteadOfSpeech", _("Sonido en lugar del rol y el estado")),
]


def _themeChoices() -> S.ChoiceList:
	from ..audio import tones

	return [(t, _("Predeterminado (generado)") if t == "default" else t) for t in tones.availableThemes()]


_RESERVED_NAMES = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}


def isValidThemeName(name: str) -> bool:
	"""Nombre de carpeta válido en Windows para un tema de sonidos.

	Se rechazan los caracteres prohibidos, los nombres formados solo por puntos
	o espacios, los que acaban en punto o espacio (Windows los recorta y la
	carpeta sería otra) y los nombres reservados de dispositivos."""
	if not name or name.lower() == "default":
		return False
	if any(c in '<>:"/\\|?*' or ord(c) < 32 for c in name):
		return False
	if not name.strip(". ") or name[-1] in ". ":
		return False
	return name.split(".")[0].strip().lower() not in _RESERVED_NAMES


class SoundsPanel(S.ConfigPanel):
	title = _("Sonidos")
	section = "earcons"

	def getFields(self) -> list[S.Field]:
		return [
			S.Bool("playSounds", _("Reproducir los sonidos de Tiresias"), section="audio"),
			S.Slider("soundVolume", _("Volumen de los sonidos de Tiresias:"), 0, 100, lineSize=5, pageSize=10, section="audio"),
			S.Bool("soundVolumeFollowsVoice", _("El volumen de los sonidos sigue al volumen de la voz"), section="audio"),
			S.Choice("soundTheme", _("&Tema de sonidos:"), _themeChoices, section="audio"),
			S.Choice("mode", _("Sonidos de &los controles:"), _EARCON_MODES),
			S.Bool("roles", _("Sonido para el t&ipo de control (rol)")),
			S.Bool("states", _("Sonido para los &estados (marcado, expandido, no disponible...)")),
			S.Bool("positional", _("&Audio posicional: el sonido se oye a la izquierda o a la derecha según la posición del control")),
		]

	def makeExtraSettings(self, builder: S.SettingsBuilder) -> None:
		from ..audio import earcons

		self._sounds = earcons.soundDescriptions()
		self.soundList = builder.addLabeledControl(
			_("Escuchar un &sonido:"),
			lambda p: wx.ListBox(p, choices=[d for _n, d in self._sounds], style=wx.LB_SINGLE, size=(320, 120)),
			vertical=True,
		)
		if self._sounds:
			self.soundList.SetSelection(0)
		play = builder.addButton(_("&Reproducir"))
		play.Bind(wx.EVT_BUTTON, self._onPlay)
		self.soundList.Bind(wx.EVT_LISTBOX_DCLICK, self._onPlay)
		export = builder.addButton(_("Crear un tema &nuevo a partir del predeterminado..."))
		export.Bind(wx.EVT_BUTTON, self._onExport)
		openBtn = builder.addButton(_("Abrir la carpeta &de temas"))
		openBtn.Bind(wx.EVT_BUTTON, self._onOpenFolder)

	def _onPlay(self, evt) -> None:
		i = self.soundList.GetSelection()
		if 0 <= i < len(self._sounds):
			name = self._sounds[i][0]

			def play() -> None:
				from ..audio import tones

				tones.playSound(name)

			queue_handler.queueFunction(play)

	def _onExport(self, evt) -> None:
		dlg = wx.TextEntryDialog(self, _("Nombre del tema nuevo (se creará una carpeta en data\\sounds con todos los sonidos en formato WAV, que puedes sustituir por los tuyos):"), _("Nuevo tema de sonidos"), _("personalizado"))
		try:
			if dlg.ShowModal() != wx.ID_OK:
				return
			name = dlg.GetValue().strip()
		finally:
			dlg.Destroy()
		if not isValidThemeName(name):
			S.showError(_("El nombre no es válido."), self)
			return
		folder = os.path.join(paths.soundsDir(), name)

		def export() -> int:
			from ..audio import tones

			return tones.exportTheme(folder)

		def done(count: int | None, error: BaseException | None) -> None:
			if not S.isAlive(self):
				return
			if count is None:
				S.showError(_("No se pudo crear el tema.") + (f" {error}" if error else ""), self)
				return
			message_dialog.messageBox(
				_("Se han creado {n} sonidos en {folder}. Elige el tema «{name}» en esta categoría para usarlo.").format(n=count, folder=folder, name=name),
				_("Nuevo tema de sonidos"),
				wx.OK | wx.ICON_INFORMATION,
				self,
			)
			ctrl = self.getControl("soundTheme", "audio")
			if ctrl is not None:
				b = self._bound[("audio", "soundTheme")]
				if name not in b.values:
					b.values.append(name)
					ctrl.Append(name)

		# Generar y escribir los WAV no es trabajo del núcleo: hilo propio.
		S.runInThread(export, callback=done, name="TiresiasTemaSonidos")

	def _onOpenFolder(self, evt) -> None:
		folder = paths.soundsDir()
		try:
			os.makedirs(folder, exist_ok=True)
			os.startfile(folder)
		except OSError:
			S.showError(_("No se pudo abrir la carpeta."), self)


# ====================================================================== registro
def register() -> None:
	"""Añade la categoría «Sonidos» (su sitio en la lista lo da ``settings.getPanelIds``)."""
	S.registerPanel("sounds", SoundsPanel.title, SoundsPanel)
