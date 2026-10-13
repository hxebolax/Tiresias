"""Visor de voz: ventana que muestra todo lo que Tiresias dice.

Útil para personas videntes que ayudan al usuario o para desarrollar. No
roba el foco al abrirse.
"""

from __future__ import annotations

import wx

from ..config import conf
from ..i18n import _
from ..log import getLogger
from .helpers import addLabel, bindEscapeToClose, isAlive, runOnGui

log = getLogger("gui.speechViewer")

#: Máximo de caracteres conservados en el visor.
MAX_CHARS = 200_000


class SpeechViewerFrame(wx.Frame):
	def __init__(self) -> None:
		super().__init__(None, title=_("Visor de voz"), size=(560, 380), style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_TOOL_WINDOW)
		panel = wx.Panel(self)
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(panel, sizer, _("&Texto hablado:"))
		self.text = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.TE_DONTWRAP)
		sizer.Add(self.text, 1, wx.EXPAND | wx.ALL, 6)
		self.showAtStartup = wx.CheckBox(panel, label=_("&Mostrar el visor de voz al iniciar"))
		self.showAtStartup.SetValue(bool(conf["speechViewer"]["showAtStartup"]))
		self.showAtStartup.Bind(wx.EVT_CHECKBOX, self.onShowAtStartup)
		sizer.Add(self.showAtStartup, 0, wx.ALL, 6)
		panel.SetSizer(sizer)
		self.Bind(wx.EVT_CLOSE, self.onClose)
		bindEscapeToClose(self)
		self._lines = 0

	def append(self, text: str) -> None:
		if not isAlive(self):
			return
		if self.text.GetLastPosition() > MAX_CHARS:
			self.text.Remove(0, MAX_CHARS // 4)
		self.text.AppendText(("\n" if self._lines else "") + text)
		self._lines += 1

	def onShowAtStartup(self, evt: wx.CommandEvent) -> None:
		conf["speechViewer"]["showAtStartup"] = self.showAtStartup.GetValue()

	def onClose(self, evt: wx.CloseEvent) -> None:
		global _frame
		try:
			if conf["speechViewer"]["rememberPosition"] and not self.IsIconized():
				x, y = self.GetPosition()
				w, h = self.GetSize()
				conf["speechViewer"]["position"] = [int(x), int(y), int(w), int(h)]
		except Exception:
			log.debug("No se pudo guardar la posición del visor de voz", exc_info=True)
		_unregister()
		_frame = None
		self.Destroy()


_frame: SpeechViewerFrame | None = None


def _onPreSpeech(sequence: list | None = None) -> None:
	"""Manejador de ``pre_speech`` (se ejecuta en el hilo del núcleo)."""
	if not sequence:
		return
	text = " ".join(s.strip() for s in sequence if isinstance(s, str) and s.strip())
	if text:
		wx.CallAfter(_append, text)


def _append(text: str) -> None:
	if isAlive(_frame):
		_frame.append(text)


def _register() -> None:
	from ..speech import api

	api.pre_speech.register(_onPreSpeech)


def _unregister() -> None:
	from ..speech import api

	api.pre_speech.unregister(_onPreSpeech)


def isActive() -> bool:
	return isAlive(_frame)


def _restorePosition(frame: wx.Frame) -> None:
	"""Posición y tamaño guardados (si siguen dentro de alguna pantalla)."""
	try:
		if not conf["speechViewer"]["rememberPosition"]:
			return
		pos = list(conf["speechViewer"]["position"] or [])
	except Exception:
		return
	if len(pos) != 4:
		return
	x, y, w, h = (int(v) for v in pos)
	for i in range(wx.Display.GetCount()):
		if wx.Display(i).GetGeometry().Contains(wx.Point(x + 20, y + 20)):
			frame.SetSize(x, y, max(200, w), max(120, h))
			return


def _open() -> None:
	global _frame
	if isAlive(_frame):
		return
	_frame = SpeechViewerFrame()
	_restorePosition(_frame)
	_register()
	# Se muestra sin activarlo para no quitar el foco a la aplicación.
	_frame.ShowWithoutActivating()


def _close() -> None:
	if isAlive(_frame):
		_frame.Close()


def toggle() -> None:
	"""Abre o cierra el visor de voz (seguro desde cualquier hilo)."""
	runOnGui(lambda: _close() if isActive() else _open())


def show() -> None:
	runOnGui(_open)


def close() -> None:
	runOnGui(_close)
