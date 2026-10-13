"""Tutorial interactivo de primeros pasos (#7242).

Una serie de pasos cortos. En cada uno se pide al usuario que pulse una
orden de verdad; cuando Tiresias la ejecuta (``input.core.post_scriptExecuted``)
el tutorial lo felicita y pasa al paso siguiente. Las teclas que se nombran
son las reales: tienen en cuenta la distribución de teclado (sobremesa o
portátil), el mapa de gestos y los cambios del usuario.

Se abre desde Ayuda > Tutorial de primeros pasos y desde el diálogo de
bienvenida.
"""

from __future__ import annotations

from dataclasses import dataclass

import wx

from .. import APP_NAME
from ..i18n import _
from ..log import getLogger
from .helpers import bringToFront, isAlive, speakMessage
from .settings import SettingsBuilder, parentWindow

log = getLogger("gui.tutorial")


@dataclass
class Step:
	title: str
	text: str
	#: Orden global que completa el paso (vacío: basta con pulsar «Siguiente»).
	script: str = ""


def gestureFor(scriptName: str) -> str:
	"""Teclas de una orden global en la distribución actual («Tiresias+T»)."""
	try:
		from ..global_commands import commands
		from ..input import keys
		from .keyref import classGestures

		gids = classGestures(type(commands), commands).get(scriptName, [])
		labels = sorted({keys.labelForGesture(g) for g in gids if g.startswith("kb")}, key=len)
		if labels:
			return labels[0]
	except Exception:
		log.debug("Sin gesto para %s", scriptName, exc_info=True)
	return _("(sin tecla asignada)")


def buildSteps() -> list[Step]:
	g = gestureFor
	return [
		Step(
			_("Bienvenida"),
			_(
				"Este tutorial le enseña lo básico de {app} practicando con el teclado. En cada paso se le pedirá que pulse unas teclas; "
				"cuando lo haga, el tutorial pasará solo al paso siguiente. Puede leer estas instrucciones con las flechas y repetirlas "
				"con el botón «Repetir». Pulse «Siguiente» para empezar."
			).format(app=APP_NAME),
		),
		Step(
			_("La tecla Tiresias"),
			_(
				"Casi todas las órdenes se usan manteniendo pulsada la tecla Tiresias, que es Insertar (la del teclado principal o la del numérico) "
				"o Bloq Mayús (salvo que lo haya desactivado). Por ejemplo, {keys} lee el título de la ventana. Pruébelo ahora."
			).format(keys=g("title")),
			"title",
		),
		Step(_("La hora"), _("Muy bien. Ahora pulse {keys} para oír la hora. Púlselo dos veces seguidas y oirá la fecha.").format(keys=g("dateTime")), "dateTime"),
		Step(
			_("Dónde está el foco"),
			_("El foco es el control que recibe lo que escribe. Pulse {keys} para saber dónde está el foco.").format(keys=g("reportCurrentFocus")),
			"reportCurrentFocus",
		),
		Step(
			_("Hacer callar la voz"),
			_(
				"Pulse Control (sola) en cualquier momento para que la voz se calle, y Mayúsculas (sola) para pausarla y reanudarla. "
				"Pruébelo mientras lee estas instrucciones y, cuando quiera, pulse «Siguiente»."
			),
		),
		Step(
			_("La ayuda de entrada"),
			_(
				"Con la ayuda de entrada puede pulsar cualquier tecla y Tiresias le dirá qué hace, sin hacerlo. Pulse {keys} para activarla, "
				"pruebe algunas teclas y vuelva a pulsar {keys} para desactivarla."
			).format(keys=g("toggleInputHelp")),
			"toggleInputHelp",
		),
		Step(
			_("Leer la línea"),
			_("En un documento o un campo de texto, {keys} lee la línea del cursor y {all} lee desde el cursor hasta el final. Pulse {keys} ahora.").format(
				keys=g("reportCurrentLine"), all=g("sayAll")
			),
			"reportCurrentLine",
		),
		Step(
			_("El modo de voz"),
			_("{keys} cambia el modo de voz: hablar, a demanda, pitidos y desactivada. Púlselo hasta volver a «hablar».").format(keys=g("speechMode")),
			"speechMode",
		),
		Step(
			_("La paleta de órdenes"),
			_("Si no recuerda una tecla, {keys} abre la paleta de órdenes: escriba lo que quiere hacer y pulse Intro. Ábrala ahora y ciérrela con Escape.").format(
				keys=g("commandPalette")
			),
			"commandPalette",
		),
		Step(
			_("El menú de Tiresias"),
			_("{keys} abre el menú de Tiresias, con las opciones, la ayuda y la salida. Ábralo y ciérrelo con Escape.").format(keys=g("showGui")),
			"showGui",
		),
		Step(
			_("Fin"),
			_(
				"¡Enhorabuena! Ya conoce lo básico. En el menú Ayuda tiene el manual de usuario, la referencia rápida con todas las órdenes y este tutorial. "
				"Pulse «Terminar» para cerrarlo."
			),
		),
	]


class TutorialDialog(wx.Dialog):
	def __init__(self) -> None:
		super().__init__(parentWindow(), title=_("Tutorial de primeros pasos"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.steps = buildSteps()
		self.index = 0
		main = wx.BoxSizer(wx.VERTICAL)
		b = SettingsBuilder(self, main)
		self.stepLabel = wx.StaticText(self, label="")
		main.Add(self.stepLabel, 0, wx.BOTTOM, 4)
		self.text = b.addText(_("&Instrucciones:"), "", style=wx.TE_MULTILINE | wx.TE_READONLY, size=(520, 150))
		row = wx.BoxSizer(wx.HORIZONTAL)
		self.prevButton = wx.Button(self, label=_("&Anterior"))
		self.repeatButton = wx.Button(self, label=_("&Repetir"))
		self.nextButton = wx.Button(self, label=_("&Siguiente"))
		closeButton = wx.Button(self, wx.ID_CLOSE, _("Sa&lir del tutorial"))
		for btn in (self.prevButton, self.repeatButton, self.nextButton, closeButton):
			row.Add(btn, 0, wx.RIGHT, 6)
		main.Add(row, 0, wx.TOP, 8)
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(main, 1, wx.EXPAND | wx.ALL, 10)
		self.SetSizerAndFit(outer)
		self.SetEscapeId(wx.ID_CLOSE)
		self.prevButton.Bind(wx.EVT_BUTTON, lambda evt: self.go(self.index - 1))
		self.nextButton.Bind(wx.EVT_BUTTON, self._onNext)
		self.repeatButton.Bind(wx.EVT_BUTTON, lambda evt: self.speakStep())
		closeButton.Bind(wx.EVT_BUTTON, lambda evt: self.close())
		self.Bind(wx.EVT_CLOSE, lambda evt: self.close())
		self.Bind(wx.EVT_ACTIVATE, self._onActivate)
		#: Paso completado mientras el usuario estaba en otra ventana (la paleta, el menú...).
		self._pendingAdvance: int | None = None
		from ..input import core as inputCore

		inputCore.post_scriptExecuted.register(self._onScript)
		self.CentreOnScreen()
		self.go(0, speak=False)
		self.text.SetFocus()

	def go(self, index: int, speak: bool = True) -> None:
		self.index = max(0, min(index, len(self.steps) - 1))
		step = self.steps[self.index]
		self.stepLabel.SetLabel(_("Paso {n} de {total}: {title}").format(n=self.index + 1, total=len(self.steps), title=step.title))
		self.text.SetValue(step.text)
		self.text.SetInsertionPoint(0)
		self.prevButton.Enable(self.index > 0)
		last = self.index == len(self.steps) - 1
		self.nextButton.SetLabel(_("&Terminar") if last else _("&Siguiente"))
		self.Layout()
		if speak:
			self.speakStep()

	def speakStep(self) -> None:
		step = self.steps[self.index]
		speakMessage(f"{step.title}. {step.text}")

	def _onNext(self, evt: wx.CommandEvent) -> None:
		if self.index == len(self.steps) - 1:
			self.close()
		else:
			self.go(self.index + 1)

	def _onScript(self, script=None, gesture=None) -> None:
		"""Hilo del núcleo: ¿la orden ejecutada completa el paso actual?"""
		name = getattr(script, "__name__", "")
		name = name[7:] if name.startswith("script_") else name
		if not self._stepDone(name):
			return
		wx.CallAfter(self._checkScript, name)

	@staticmethod
	def _stepDone(name: str) -> bool:
		"""Hilo del núcleo: algunos pasos solo se completan al dejar el estado normal.

		La ayuda de entrada se cuenta al desactivarla (activada se traga las teclas
		del paso siguiente) y el modo de voz al volver a «hablar» (si no, el
		«¡Muy bien!» y el paso siguiente no se oirían).
		"""
		try:
			if name == "toggleInputHelp":
				from ..input import core as inputCore

				return not inputCore.manager.inputHelp
			if name == "speechMode":
				from ..speech import api as speechApi

				return speechApi.getSpeechMode() == speechApi.SpeechMode.talk
		except Exception:
			log.debug("No se pudo comprobar el estado del paso %s", name, exc_info=True)
		return True

	def _checkScript(self, name: str) -> None:
		if not isAlive(self):
			return
		step = self.steps[self.index]
		if step.script and name == step.script:
			wx.CallLater(1800, self._advanceAfterSuccess, self.index)

	def _advanceAfterSuccess(self, index: int) -> None:
		if not isAlive(self) or index != self.index:
			return
		speakMessage(_("¡Muy bien!"))
		wx.CallLater(700, self._goNextIfStill, index)

	def _goNextIfStill(self, index: int) -> None:
		if not isAlive(self) or index != self.index:
			return
		if not self.IsActive():
			# No se le quita el foco a la paleta o al menú que el paso pide cerrar:
			# se avanza cuando el usuario vuelve al tutorial.
			self._pendingAdvance = index
			return
		self.go(index + 1)
		self.text.SetFocus()

	def _onActivate(self, evt: wx.ActivateEvent) -> None:
		evt.Skip()
		if evt.GetActive() and self._pendingAdvance is not None:
			index, self._pendingAdvance = self._pendingAdvance, None
			if index == self.index:
				wx.CallAfter(self._goNextIfStill, index)

	def close(self) -> None:
		global _dialog
		try:
			from ..input import core as inputCore

			inputCore.post_scriptExecuted.unregister(self._onScript)
		except Exception:
			pass
		if _dialog is self:
			_dialog = None
		self.Hide()
		self.Destroy()


_dialog: TutorialDialog | None = None


def show() -> None:
	global _dialog
	if _dialog is None or not isAlive(_dialog):
		_dialog = TutorialDialog()
		_dialog.Show()
	bringToFront(_dialog)
