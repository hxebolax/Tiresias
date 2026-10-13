"""Cuadro de mensaje propio de Tiresias (#258).

Sustituye al cuadro de mensaje nativo de Windows (``wx.MessageBox`` y
``wx.MessageDialog``) en los avisos de Tiresias. El texto va en un campo de
solo lectura: se puede recorrer con las flechas (carácter, palabra, línea),
seleccionar y copiar.

Comportamiento (decisión de diseño):

- El foco empieza en el texto, para que se lea el aviso entero y se pueda
  revisar en el acto.
- Intro (también desde el texto) pulsa el botón por defecto: el mismo que
  tendría el cuadro nativo (``wx.NO_DEFAULT`` y ``wx.CANCEL_DEFAULT`` se
  respetan). Si hay más de un botón, una línea bajo el texto dice qué
  responde Intro y qué responde Escape; Tiresias la lee como texto del
  diálogo al abrirse.
- Escape responde Cancelar si hay ese botón; si no, No (en los de Sí/No) o
  Aceptar.
- Desde el texto, la letra subrayada de un botón lo pulsa sin Alt, igual
  que en el cuadro nativo (S = Sí, N = No...). Con Alt funciona siempre.

Es compatible con wx: :func:`messageBox` devuelve ``wx.OK``, ``wx.YES``,
``wx.NO`` o ``wx.CANCEL`` como ``wx.MessageBox`` y :class:`MessageDialog`
devuelve ``wx.ID_*`` en ``ShowModal`` como ``wx.MessageDialog``, con
``SetYesNoLabels``, ``SetOKCancelLabels``, ``ShowCheckBox``... (lo que se usa
de ``wx.RichMessageDialog``).
"""

from __future__ import annotations

import wx

from ..i18n import _
from ..log import getLogger

log = getLogger("gui.message")

# Sonidos del sistema de MessageBeep (los mismos que el cuadro nativo).
_MB_ICONHAND = 0x10
_MB_ICONQUESTION = 0x20
_MB_ICONEXCLAMATION = 0x30
_MB_ICONASTERISK = 0x40

#: Conversión del botón pulsado (``wx.ID_*``) al valor de ``wx.MessageBox``.
_ID_TO_RESULT = {
	wx.ID_OK: wx.OK,
	wx.ID_YES: wx.YES,
	wx.ID_NO: wx.NO,
	wx.ID_CANCEL: wx.CANCEL,
	wx.ID_HELP: wx.HELP,
}


# ---------------------------------------------------------------------- lógica pura
def buttonIds(style: int) -> list[int]:
	"""Botones (``wx.ID_*``) del estilo, en el orden de Windows."""
	ids: list[int] = []
	if style & wx.YES_NO == wx.YES_NO or style & wx.YES:
		ids += [wx.ID_YES, wx.ID_NO]
	elif style & wx.OK or not style & wx.CANCEL:
		ids.append(wx.ID_OK)
	if style & wx.CANCEL:
		ids.append(wx.ID_CANCEL)
	if style & wx.HELP:
		ids.append(wx.ID_HELP)
	return ids


def defaultId(style: int) -> int:
	"""Botón que responde a Intro."""
	ids = buttonIds(style)
	if style & wx.CANCEL_DEFAULT and wx.ID_CANCEL in ids:
		return wx.ID_CANCEL
	if style & wx.NO_DEFAULT and wx.ID_NO in ids:
		return wx.ID_NO
	return ids[0]


def escapeId(style: int) -> int:
	"""Botón que responde a Escape (y a cerrar la ventana)."""
	ids = buttonIds(style)
	for candidate in (wx.ID_CANCEL, wx.ID_NO, wx.ID_OK):
		if candidate in ids:
			return candidate
	return ids[0]


def iconKind(style: int) -> str:
	"""``error``, ``warning``, ``question``, ``information`` o ``""`` (sin icono)."""
	if style & wx.ICON_NONE:
		return ""
	if style & wx.ICON_ERROR:
		return "error"
	if style & wx.ICON_WARNING:
		return "warning"
	if style & wx.ICON_QUESTION:
		return "question"
	if style & wx.ICON_INFORMATION:
		return "information"
	# Como wx: pregunta si hay Sí/No; si no, información.
	return "question" if wx.ID_YES in buttonIds(style) else "information"


def resultFromId(buttonId: int) -> int:
	"""Valor que devolvería ``wx.MessageBox`` para el botón pulsado."""
	return _ID_TO_RESULT.get(buttonId, wx.CANCEL)


def mnemonic(label: str) -> str:
	"""Letra subrayada (tras ``&``) de una etiqueta, en minúscula; ``""`` si no hay."""
	i = 0
	while i < len(label) - 1:
		if label[i] == "&":
			if label[i + 1] != "&":
				return label[i + 1].lower()
			i += 1
		i += 1
	return ""


def _stripMnemonic(label: str) -> str:
	return label.replace("&&", "\0").replace("&", "").replace("\0", "&")


# ---------------------------------------------------------------------- diálogo
class MessageDialog(wx.Dialog):
	"""Cuadro de mensaje con el texto en un campo de solo lectura recorrible."""

	def __init__(self, parent: wx.Window | None, message: str, caption: str = "", style: int = wx.OK | wx.CENTRE, pos: wx.Point = wx.DefaultPosition) -> None:
		from .. import APP_NAME

		dlgStyle = wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
		if style & wx.STAY_ON_TOP:
			dlgStyle |= wx.STAY_ON_TOP
		super().__init__(parent, title=caption or APP_NAME, pos=pos, style=dlgStyle)
		self._message = str(message or "")
		self._msgStyle = style
		self._labels: dict[int, str] = {
			wx.ID_OK: _("Aceptar"),
			wx.ID_CANCEL: _("&Cancelar"),
			wx.ID_YES: _("&Sí"),
			wx.ID_NO: _("&No"),
			wx.ID_HELP: _("A&yuda"),
		}
		self._extendedMessage = ""
		self._checkLabel: str | None = None
		self._checkValue = False
		self.checkBox: wx.CheckBox | None = None
		self.text: wx.TextCtrl | None = None
		self.buttons: dict[int, wx.Button] = {}
		self._built = False

	# --- API compatible con wx.MessageDialog / wx.RichMessageDialog ---
	def SetYesNoLabels(self, yes: str, no: str) -> bool:
		self._labels[wx.ID_YES] = str(yes)
		self._labels[wx.ID_NO] = str(no)
		return True

	def SetYesNoCancelLabels(self, yes: str, no: str, cancel: str) -> bool:
		self.SetYesNoLabels(yes, no)
		self._labels[wx.ID_CANCEL] = str(cancel)
		return True

	def SetOKLabel(self, ok: str) -> bool:
		self._labels[wx.ID_OK] = str(ok)
		return True

	def SetOKCancelLabels(self, ok: str, cancel: str) -> bool:
		self._labels[wx.ID_OK] = str(ok)
		self._labels[wx.ID_CANCEL] = str(cancel)
		return True

	def SetHelpLabel(self, label: str) -> bool:
		self._labels[wx.ID_HELP] = str(label)
		return True

	def SetMessage(self, message: str) -> None:
		self._message = str(message or "")
		if self.text is not None:
			self.text.SetValue(self._fullText())

	def GetMessage(self) -> str:
		return self._message

	def SetExtendedMessage(self, extended: str) -> None:
		self._extendedMessage = str(extended or "")
		if self.text is not None:
			self.text.SetValue(self._fullText())

	def GetExtendedMessage(self) -> str:
		return self._extendedMessage

	def ShowCheckBox(self, label: str, checked: bool = False) -> None:
		self._checkLabel = str(label)
		self._checkValue = bool(checked)

	def IsCheckBoxChecked(self) -> bool:
		if self.checkBox is not None:
			return self.checkBox.GetValue()
		return self._checkValue

	def GetCheckBoxText(self) -> str:
		return self._checkLabel or ""

	# --- construcción ---
	def _fullText(self) -> str:
		text = self._message
		if self._extendedMessage:
			text = f"{text}\n\n{self._extendedMessage}" if text else self._extendedMessage
		# El campo de texto de Windows necesita CRLF para separar líneas.
		return text.replace("\r\n", "\n").replace("\n", "\r\n")

	def build(self) -> None:
		"""Crea los controles (se hace al mostrarlo, tras cambiar etiquetas)."""
		if self._built:
			return
		self._built = True
		style = self._msgStyle
		main = wx.BoxSizer(wx.VERTICAL)
		row = wx.BoxSizer(wx.HORIZONTAL)
		art = {"error": wx.ART_ERROR, "warning": wx.ART_WARNING, "question": wx.ART_QUESTION, "information": wx.ART_INFORMATION}.get(iconKind(style))
		if art:
			bmp = wx.ArtProvider.GetBitmap(art, wx.ART_MESSAGE_BOX)
			if bmp.IsOk():
				row.Add(wx.StaticBitmap(self, bitmap=bmp), 0, wx.ALL | wx.ALIGN_TOP, 10)
		col = wx.BoxSizer(wx.VERTICAL)
		# La etiqueta va justo antes del campo (así se asocian).
		col.Add(wx.StaticText(self, label=_("&Mensaje:")), 0, wx.TOP, 6)
		text = self._fullText()
		self.text = wx.TextCtrl(self, value=text, size=self._textSize(text), style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.TE_NOHIDESEL)
		col.Add(self.text, 1, wx.EXPAND | wx.TOP, 4)
		ids = buttonIds(style)
		self._defaultId = defaultId(style)
		self._escapeId = escapeId(style)
		if len(ids) > 1:
			hint = _("Intro responde «{default}» y Escape, «{escape}».").format(
				default=_stripMnemonic(self._labels[self._defaultId]), escape=_stripMnemonic(self._labels[self._escapeId])
			)
			col.Add(wx.StaticText(self, label=hint), 0, wx.TOP, 6)
		if self._checkLabel is not None:
			self.checkBox = wx.CheckBox(self, label=self._checkLabel)
			self.checkBox.SetValue(self._checkValue)
			col.Add(self.checkBox, 0, wx.TOP, 8)
		row.Add(col, 1, wx.EXPAND | wx.ALL, 6)
		main.Add(row, 1, wx.EXPAND)
		btnRow = wx.BoxSizer(wx.HORIZONTAL)
		for bid in ids:
			btn = wx.Button(self, bid, self._labels[bid])
			btn.Bind(wx.EVT_BUTTON, self._onButton)
			btnRow.Add(btn, 0, wx.ALL, 4)
			self.buttons[bid] = btn
		main.Add(btnRow, 0, wx.ALIGN_RIGHT | wx.ALL, 6)
		self.buttons[self._defaultId].SetDefault()
		self.SetEscapeId(self._escapeId)
		self.SetAffirmativeId(self._defaultId)
		self.SetSizerAndFit(main)
		self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)
		self.Bind(wx.EVT_CLOSE, self._onClose)
		if self.GetPosition() == wx.DefaultPosition or self._msgStyle & wx.CENTRE:
			if self.GetParent() is None:
				self.CentreOnScreen()
			else:
				self.CentreOnParent()

	def _textSize(self, text: str) -> tuple[int, int]:
		"""Tamaño del campo según la longitud del texto (entre 3 y 15 líneas)."""
		charW = max(6, self.GetCharWidth())
		charH = max(12, self.GetCharHeight())
		cols = 64
		lines = 0
		for line in text.split("\r\n"):
			lines += max(1, -(-len(line) // cols))
		lines = max(3, min(15, lines))
		return charW * (cols + 4), charH * (lines + 1) + 8

	# --- eventos ---
	def _finish(self, buttonId: int) -> None:
		if self.IsModal():
			self.EndModal(buttonId)
		else:
			self.SetReturnCode(buttonId)
			self.Hide()

	def _onButton(self, evt: wx.CommandEvent) -> None:
		self._finish(evt.GetId())

	def _onClose(self, evt: wx.CloseEvent) -> None:
		if self.IsModal() or self.IsShown():
			self._finish(self._escapeId)
		else:
			evt.Skip()

	def _onCharHook(self, evt: wx.KeyEvent) -> None:
		key = evt.GetKeyCode()
		mods = evt.GetModifiers()
		if key == wx.WXK_ESCAPE and mods == wx.MOD_NONE:
			self._finish(self._escapeId)
			return
		focus = self.FindFocus()
		if focus is self.text and self.text is not None:
			if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and mods == wx.MOD_NONE:
				self._finish(self._defaultId)
				return
			if mods == wx.MOD_CONTROL and key in (ord("A"), ord("a")):
				self.text.SelectAll()
				return
			# Letra subrayada de un botón, sin Alt (como en el cuadro nativo).
			uni = evt.GetUnicodeKey()
			if mods == wx.MOD_NONE and uni not in (wx.WXK_NONE, 0) and 32 < uni < 0x110000:
				bid = self._buttonForKey(chr(uni))
				if bid is not None:
					self._finish(bid)
					return
		evt.Skip()

	def _buttonForKey(self, ch: str) -> int | None:
		ch = ch.lower()
		for bid in self.buttons:
			if ch and mnemonic(self._labels[bid]) == ch:
				return bid
		return None

	# --- mostrar ---
	def _toFront(self) -> None:
		from .helpers import bringToFront

		try:
			bringToFront(self)
			if self.text is not None:
				self.text.SetInsertionPoint(0)
				self.text.ShowPosition(0)
				self.text.SetFocus()
		except RuntimeError:
			pass

	def _beep(self) -> None:
		kind = iconKind(self._msgStyle)
		sound = {"error": _MB_ICONHAND, "warning": _MB_ICONEXCLAMATION, "information": _MB_ICONASTERISK, "question": _MB_ICONQUESTION}.get(kind)
		if sound is None:
			return
		try:
			from .. import winapi

			winapi.user32.MessageBeep(sound)
		except Exception:
			log.debug("No se pudo reproducir el sonido del mensaje", exc_info=True)

	def ShowModal(self) -> int:
		self.build()
		self._beep()
		wx.CallAfter(self._toFront)
		return super().ShowModal()

	def Show(self, show: bool = True) -> bool:
		if show:
			self.build()
			res = super().Show(True)
			self._beep()
			self._toFront()
			return res
		return super().Show(False)


def messageBox(message: str, caption: str = "", style: int = wx.OK | wx.CENTRE, parent: wx.Window | None = None, x: int = -1, y: int = -1) -> int:
	"""Igual que ``wx.MessageBox`` pero con el cuadro de Tiresias (hilo de la interfaz).

	Devuelve ``wx.OK``, ``wx.YES``, ``wx.NO`` o ``wx.CANCEL``.
	"""
	pos = wx.Point(x, y) if x != -1 or y != -1 else wx.DefaultPosition
	dlg = MessageDialog(parent, message, caption, style, pos)
	try:
		return resultFromId(dlg.ShowModal())
	finally:
		dlg.Destroy()
