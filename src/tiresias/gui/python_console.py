"""Consola de Python para desarrolladores.

Las órdenes se ejecutan en el hilo del núcleo, el mismo en el que se
obtuvieron ``focus`` y ``nav`` (objetos COM del apartamento MTA). El código
que toque ventanas de wx debe usar ``gui.runOnGui``.
"""

from __future__ import annotations

import code
import sys
from typing import Any

import wx

from .. import queue_handler
from ..i18n import _
from ..log import getLogger
from .helpers import addLabel, bringToFront, isAlive, runOnGui

log = getLogger("gui.pythonConsole")

PROMPT = ">>> "
PROMPT_MORE = "... "


class _Writer:
	"""Sustituto de ``sys.stdout``/``sys.stderr`` que acumula el texto."""

	def __init__(self) -> None:
		self.parts: list[str] = []

	def write(self, data: str) -> int:
		self.parts.append(str(data))
		return len(data)

	def flush(self) -> None:
		pass

	def isatty(self) -> bool:
		return False


def _buildNamespace(focus: Any, nav: Any) -> dict[str, Any]:
	"""Espacio de nombres inicial con los módulos más útiles de Tiresias."""
	import tiresias
	from .. import api, braille, core, queue_handler as qh, speech, winapi
	from .. import gui
	from ..config import conf

	ns: dict[str, Any] = {
		"__name__": "__console__",
		"__doc__": None,
		"tiresias": tiresias,
		"api": api,
		"speech": speech,
		"conf": conf,
		"core": core,
		"braille": braille,
		"queue_handler": qh,
		"winapi": winapi,
		"gui": gui,
		"wx": wx,
		"focus": focus,
		"nav": nav,
	}
	return ns


class PythonConsoleFrame(wx.Frame):
	def __init__(self, focus: Any, nav: Any) -> None:
		super().__init__(None, title=_("Consola de Python"), size=(760, 520))
		self.namespace = _buildNamespace(focus, nav)
		self.console = code.InteractiveConsole(self.namespace)
		self.history: list[str] = []
		self.historyPos = 0
		self.more = False
		panel = wx.Panel(self)
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(panel, sizer, _("&Salida:"))
		self.output = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.TE_DONTWRAP)
		self.output.SetFont(wx.Font(10, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
		sizer.Add(self.output, 1, wx.EXPAND | wx.ALL, 6)
		self.promptLabel = addLabel(panel, sizer, _("&Entrada:"))
		self.input = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
		self.input.SetFont(self.output.GetFont())
		self.input.Bind(wx.EVT_TEXT_ENTER, self.onEnter)
		self.input.Bind(wx.EVT_KEY_DOWN, self.onInputKey)
		sizer.Add(self.input, 0, wx.EXPAND | wx.ALL, 6)
		panel.SetSizer(sizer)
		self.Bind(wx.EVT_CLOSE, self.onClose)
		self.Bind(wx.EVT_CHAR_HOOK, self.onCharHook)
		self._write(_("Consola de Python de Tiresias. Variables: api, speech, conf, core, braille, queue_handler, winapi, gui, wx, focus, nav.\n"))
		self.input.SetFocus()

	def updateObjects(self, focus: Any, nav: Any) -> None:
		self.namespace["focus"] = focus
		self.namespace["nav"] = nav

	def _write(self, text: str) -> None:
		if text:
			self.output.AppendText(text)

	def execute(self, line: str) -> None:
		"""Ejecuta ``line`` en el hilo del núcleo (como los objetos ``focus`` y ``nav``).

		Esos objetos COM se obtuvieron en el núcleo (MTA): usarlos desde el hilo
		de la interfaz (STA) sin serializarlos falla con algunos proxies (MSAA).
		El resultado vuelve a la ventana con ``wx.CallAfter``.
		"""
		queue_handler.queueFunction(self._executeOnCore, line)

	def _executeOnCore(self, line: str) -> None:
		prompt = PROMPT_MORE if self.more else PROMPT
		writer = _Writer()
		oldOut, oldErr = sys.stdout, sys.stderr
		sys.stdout = sys.stderr = writer
		try:
			more = self.console.push(line)
		except SystemExit:
			writer.write(_("No se puede salir de Tiresias desde la consola.\n"))
			more = False
		except BaseException as e:  # noqa: BLE001
			writer.write(f"{type(e).__name__}: {e}\n")
			more = False
		finally:
			sys.stdout, sys.stderr = oldOut, oldErr
		self.more = more
		result = "".join(writer.parts)
		if result.strip():
			from .. import speech

			speech.speakText(result)
		wx.CallAfter(self._showResult, prompt + line + "\n" + result, more)

	def _showResult(self, text: str, more: bool) -> None:
		if not isAlive(self):
			return
		self._write(text)
		self.promptLabel.SetLabel(_("&Entrada (continuación):") if more else _("&Entrada:"))

	def onEnter(self, evt: wx.CommandEvent) -> None:
		line = self.input.GetValue()
		self.input.SetValue("")
		if line.strip():
			if not self.history or self.history[-1] != line:
				self.history.append(line)
		self.historyPos = len(self.history)
		self.execute(line)

	def onInputKey(self, evt: wx.KeyEvent) -> None:
		key = evt.GetKeyCode()
		if evt.HasAnyModifiers() or key not in (wx.WXK_UP, wx.WXK_DOWN, wx.WXK_NUMPAD_UP, wx.WXK_NUMPAD_DOWN):
			evt.Skip()
			return
		if not self.history:
			return
		if key in (wx.WXK_UP, wx.WXK_NUMPAD_UP):
			self.historyPos = max(0, self.historyPos - 1)
		else:
			self.historyPos = min(len(self.history), self.historyPos + 1)
		value = self.history[self.historyPos] if self.historyPos < len(self.history) else ""
		self.input.SetValue(value)
		self.input.SetInsertionPointEnd()

	def onCharHook(self, evt: wx.KeyEvent) -> None:
		if evt.GetKeyCode() == wx.WXK_ESCAPE and not evt.HasAnyModifiers():
			self.Hide()
			return
		if evt.GetKeyCode() == wx.WXK_F6 and not evt.HasAnyModifiers():
			(self.output if self.FindFocus() is self.input else self.input).SetFocus()
			return
		evt.Skip()

	def onClose(self, evt: wx.CloseEvent) -> None:
		# Se oculta para conservar el estado de la sesión.
		if evt.CanVeto():
			evt.Veto()
			self.Hide()
			return
		global _frame
		_frame = None
		self.Destroy()


_frame: PythonConsoleFrame | None = None


def show(focus: Any = None, nav: Any = None) -> None:
	"""Abre la consola (seguro desde cualquier hilo).

	``focus`` y ``nav`` son los objetos que se ofrecen en el espacio de
	nombres; conviene obtenerlos en el hilo del núcleo antes de llamar.
	"""

	from ..config import policy as _pol

	if not _pol.isAllowed("pythonConsole"):
		# Modo seguro o política del equipo: ni el menú, ni Tiresias+Control+Z, ni la paleta.
		from .helpers import speakMessage

		speakMessage(_pol.blockedMessage())
		return

	def _show() -> None:
		global _frame
		if isAlive(_frame):
			_frame.updateObjects(focus, nav)
		else:
			_frame = PythonConsoleFrame(focus, nav)
		_frame.Show()
		bringToFront(_frame)
		_frame.input.SetFocus()

	runOnGui(_show)
