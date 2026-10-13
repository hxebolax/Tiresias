"""Interfaz de la convivencia con otros lectores (hilo de la interfaz).

- Icono del área de notificación: atenuado y con «en espera» en la
  descripción mientras otro lector tiene preferencia.
- Entradas al principio del menú de Tiresias: el estado, «Activar Tiresias
  aunque haya otro lector...» (en espera) o «Ceder el paso a...» (activo
  con otro lector en ejecución).
- Tecla rápida global Control+Alt+Mayúsculas+T, solo en espera (no hay
  ganchos de teclado): pregunta si se activa Tiresias. Se registra con
  ``RegisterHotKey``, que no necesita ganchos, y se quita al activarse.
"""

from __future__ import annotations

import wx

from .. import APP_NAME, queue_handler
from ..i18n import _
from ..log import getLogger

log = getLogger("coexist")

HOTKEY_ID = 0x7A51
#: Descripción de la tecla rápida para el manual y los mensajes.
HOTKEY_LABEL = "Control+Alt+Mayúsculas+T"

_hotkeyRegistered = False
_hotkeyFrame = None
_normalIcon = None
_standbyIcon = None
_asking = False


def _coexist():
	from .. import coexist

	return coexist


def _icons() -> tuple:
	global _normalIcon, _standbyIcon
	if _normalIcon is None:
		from .. import gui

		_normalIcon = gui._makeIcon()
		try:
			bmp = wx.Bitmap()
			bmp.CopyFromIcon(_normalIcon)
			grey = bmp.ConvertToDisabled()
			icon = wx.Icon()
			icon.CopyFromBitmap(grey)
			_standbyIcon = icon if icon.IsOk() else _normalIcon
		except Exception:
			log.debug("No se pudo crear el icono atenuado", exc_info=True)
			_standbyIcon = _normalIcon
	return _normalIcon, _standbyIcon


def tooltip() -> str:
	c = _coexist()
	if c.isStandby():
		r = c.activeReader()
		return _("{app}: en espera ({reader} tiene preferencia)").format(app=APP_NAME, reader=r.name if r else _("otro lector"))
	if c.isForced():
		return _("{app}: activo junto a otro lector de pantalla").format(app=APP_NAME)
	return APP_NAME


def updateState() -> None:
	"""Icono, descripción y tecla rápida según el estado (hilo de la interfaz)."""
	from .. import gui

	c = _coexist()
	standby = c.isStandby()
	tray = gui.trayIcon
	if tray is not None:
		try:
			normal, grey = _icons()
			tray.SetIcon(grey if standby else normal, tooltip())
		except Exception:
			log.debug("No se pudo cambiar el icono", exc_info=True)
	_setHotkey(standby)


def _setHotkey(on: bool) -> None:
	global _hotkeyRegistered, _hotkeyFrame
	from .. import gui

	frame = gui.mainFrame
	if on and not _hotkeyRegistered and frame is not None:
		try:
			if frame.RegisterHotKey(HOTKEY_ID, wx.MOD_CONTROL | wx.MOD_ALT | wx.MOD_SHIFT, ord("T")):
				frame.Bind(wx.EVT_HOTKEY, _onHotkey, id=HOTKEY_ID)
				_hotkeyRegistered = True
				_hotkeyFrame = frame
				log.debug("Tecla rápida de activación registrada")
			else:
				log.info("No se pudo registrar %s (la usa otro programa)", HOTKEY_LABEL)
		except Exception:
			log.debug("No se pudo registrar la tecla rápida", exc_info=True)
	elif not on and _hotkeyRegistered:
		_unregisterHotkey()


def _unregisterHotkey() -> None:
	global _hotkeyRegistered, _hotkeyFrame
	frame, _hotkeyFrame = _hotkeyFrame, None
	_hotkeyRegistered = False
	if frame is None:
		return
	try:
		frame.UnregisterHotKey(HOTKEY_ID)
		frame.Unbind(wx.EVT_HOTKEY, id=HOTKEY_ID)
	except Exception:
		log.debug("No se pudo quitar la tecla rápida", exc_info=True)


def _onHotkey(evt) -> None:
	wx.CallAfter(askForceActivate)


def askForceActivate() -> None:
	"""Advierte y, si el usuario acepta, activa Tiresias aunque haya otro lector."""
	global _asking
	from .. import gui

	c = _coexist()
	if _asking or not c.isStandby():
		return
	r = c.activeReader()
	name = r.name if r else _("otro lector de pantalla")
	_asking = True
	try:
		res = gui.messageBox(
			_(
				"{reader} está en ejecución y tiene preferencia, por eso Tiresias está en espera.\n\n"
				"Si activas Tiresias ahora, los dos lectores leerán a la vez: oirás las dos voces, "
				"las teclas de los dos pueden chocar y la línea braille solo la puede usar uno. "
				"Lo recomendable es cerrar {reader} antes.\n\n"
				"¿Activar Tiresias de todos modos?"
			).format(reader=name),
			_("Activar Tiresias con otro lector en ejecución"),
			wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
		)
	finally:
		_asking = False
	if res == wx.YES:
		queue_handler.queueFunction(c.forceActivate)


def appendMenuItems(frame, menu: wx.Menu) -> None:
	"""Entradas de estado al principio del menú de Tiresias."""
	c = _coexist()
	r = c.activeReader()
	readers = c.runningReaders()
	if c.isStandby():
		info = menu.Append(wx.ID_ANY, _("Tiresias en espera: {reader} tiene preferencia").format(reader=r.name if r else _("otro lector")))
		info.Enable(False)
		frame.addMenuItem(menu, _("&Activar Tiresias aunque haya otro lector ({key})...").format(key=HOTKEY_LABEL), askForceActivate)
		menu.AppendSeparator()
	elif readers:
		name = (r or readers[0]).name
		frame.addMenuItem(menu, _("&Ceder el paso a {reader} (Tiresias en espera)").format(reader=name), lambda: queue_handler.queueFunction(c.yieldNow))
		menu.AppendSeparator()
	else:
		try:
			remembered = c.rememberedReader() if c.canSwitchToRememberedReader() else None
		except Exception:
			log.debug("No se pudo leer el lector recordado", exc_info=True)
			remembered = None
		if remembered is not None:
			# Cierra Tiresias e inicia el lector profesional que se usaba antes.
			frame.addMenuItem(
				menu,
				_("&Volver a {reader} (cierra Tiresias)").format(reader=remembered.get("name", "")),
				lambda: queue_handler.queueFunction(c.switchToRememberedReader),
			)
			menu.AppendSeparator()


def terminate() -> None:
	try:
		wx.CallAfter(_unregisterHotkey)
	except Exception:
		pass
