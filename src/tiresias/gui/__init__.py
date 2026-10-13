"""Interfaz gráfica de Tiresias (wxPython).

Este paquete es la fachada pública de la interfaz. Todas las funciones de
este módulo pueden llamarse desde cualquier hilo: se encargan de pasar el
trabajo al hilo de la interfaz con ``wx.CallAfter``.

Estructura:

- Ventana principal oculta (:class:`MainFrame`): la encuentra otra instancia
  por su título para cerrarla y sirve de dueña del menú de Tiresias.
- Icono en el área de notificación.
- Diálogos y visores en módulos propios (``dialogs``, ``speech_viewer``,
  ``braille_viewer``, ``highlighter``, ``ocr_viewer``, ``browse_dialogs``,
  ``command_palette``, ``history_dialogs``, ``log_viewer``,
  ``python_console``, ``settings`` y ``config_dialogs``).
"""

from __future__ import annotations

import os
from typing import Any, Callable

import wx
import wx.adv

from .. import APP_NAME, paths, queue_handler, winapi
from ..config import conf
from ..i18n import _
from ..log import getLogger
from .helpers import bringToFront, isAlive, runOnGui, speakMessage

log = getLogger("gui")

#: Ventana principal oculta (``None`` hasta :func:`initialize`).
mainFrame: "MainFrame | None" = None
#: Ventana de Windows (HWND) de la principal: la leen otros hilos sin tocar wx.
mainFrameHwnd = 0
#: Icono del área de notificación.
trayIcon: "TrayIcon | None" = None
#: Identificadores de los elementos de menú de verificación (los lee
#: ``objects/iaccessible.py`` en el hilo de la interfaz).
checkableMenuIds: set[int] = set()

__all__ = [
	"initialize",
	"speakMessage",
	"exitMainLoop",
	"runOnGui",
	"mainFrame",
	"showMenu",
	"askQuit",
	"showSettings",
	"showSynthSelection",
	"showProfiles",
	"showAddonsManager",
	"showInputGestures",
	"showSpeechDictionary",
	"showSymbols",
	"showWelcome",
	"showAbout",
	"showPythonConsole",
	"showCommandPalette",
	"showClipboardHistory",
	"showSpeechHistory",
	"showBrowseableMessage",
	"askText",
	"showLogViewer",
	"toggleSpeechViewer",
	"toggleBrailleViewer",
	"showUserManual",
	"showKeyCommandsReference",
	"messageBox",
	"registerToolsMenuItem",
	"unregisterToolsMenuItem",
]


# ====================================================================== ventana principal
class MainFrame(wx.Frame):
	"""Ventana oculta de Tiresias.

	Su título permite a otra instancia encontrarla con ``FindWindow`` y
	enviarle ``WM_CLOSE`` para cerrar esta. También es la dueña del menú
	emergente y de los cuadros de mensaje.
	"""

	def __init__(self, title: str) -> None:
		super().__init__(None, title=title, size=(1, 1), style=wx.FRAME_NO_TASKBAR | wx.BORDER_NONE)
		self._menuActions: dict[int, Callable[[], None]] = {}
		self._popupDepth = 0
		self._inMenu = False
		self.Bind(wx.EVT_CLOSE, self.onClose)
		self.Bind(wx.EVT_MENU, self.onMenu)

	def onClose(self, evt: wx.CloseEvent) -> None:
		# Llega, por ejemplo, cuando otra instancia pide cerrar esta.
		if evt.CanVeto():
			evt.Veto()
		from .. import core

		# Directamente (es seguro desde cualquier hilo): encolado no se atendía
		# con el núcleo bloqueado, y entonces sí actúa el plazo de cierre del
		# vigilante (core._watchdog).
		core.requestQuit()

	# ------------------------------------------------------------------ emergentes
	def prePopup(self) -> None:
		"""Hace visible (1×1 píxel) la ventana y la pone en primer plano.

		Así el menú o el cuadro de mensaje que se abra a continuación recibe el
		foco del teclado aunque Tiresias no fuera la aplicación activa.
		"""
		self._popupDepth += 1
		if self._popupDepth > 1:
			return
		# Ventana a la que se vuelve al cerrar el menú o el mensaje.
		prev = winapi.getForegroundWindow()
		self._prevForeground = prev if prev and winapi.getWindowProcessId(prev) != os.getpid() else 0
		try:
			area = wx.Display(0).GetClientArea()
			self.SetSize(area.x + area.width // 2, area.y + area.height // 2, 1, 1)
		except Exception:
			pass
		self.Show()
		self.Raise()
		winapi.setForegroundWindow(self.GetHandle())

	def postPopup(self) -> None:
		self._popupDepth = max(0, self._popupDepth - 1)
		if self._popupDepth == 0 and self.IsShown():
			# Antes de ocultarse: así Windows no activa otra ventana por orden Z
			# (otra aplicación) que se anunciaría un instante.
			self._restorePrevForeground()
			self.Hide()

	def _restorePrevForeground(self) -> None:
		"""Vuelve a la ventana que estaba activa antes del menú o del mensaje."""
		prev, self._prevForeground = getattr(self, "_prevForeground", 0), 0
		if not prev or not winapi.user32.IsWindow(prev) or not winapi.user32.IsWindowVisible(prev):
			return
		fg = winapi.getForegroundWindow()
		if fg == prev or (fg and fg != self.GetHandle()):
			# Ya está, el usuario está en otra ventana o un diálogo de Tiresias está activo.
			return
		winapi.setForegroundWindow(prev)

	# ------------------------------------------------------------------ menú
	def showMenu(self) -> None:
		if self._inMenu:
			return
		self._inMenu = True
		menu = None
		prepared = False
		try:
			# Todo dentro del try: una excepción al construir el menú dejaba
			# _inMenu en True y el menú no volvía a abrirse hasta reiniciar.
			self._menuActions = {}
			checkableMenuIds.clear()
			menu = _buildMainMenu(self)
			self.prePopup()
			prepared = True
			self.PopupMenu(menu, (0, 0))
		finally:
			if prepared:
				self.postPopup()
			if menu is not None:
				menu.Destroy()
			self._inMenu = False

	def addMenuItem(self, menu: wx.Menu, label: str, action: Callable[[], None], kind: int = wx.ITEM_NORMAL, checked: bool = False) -> wx.MenuItem:
		item = menu.Append(wx.ID_ANY, label, kind=kind)
		if kind == wx.ITEM_CHECK:
			item.Check(checked)
			# Windows no guarda si un elemento es «de verificación» cuando no está
			# marcado: MSAA lo pregunta aquí para decir «no marcado».
			# (Windows guarda el identificador en 16 bits; wx usa negativos.)
			checkableMenuIds.add(item.GetId() & 0xFFFF)
		self._menuActions[item.GetId()] = action
		return item

	def onMenu(self, evt: wx.CommandEvent) -> None:
		action = self._menuActions.get(evt.GetId())
		if action is None:
			evt.Skip()
			return
		# Tras cerrarse el menú y ocultarse la ventana.
		wx.CallAfter(_safeCall, action)


def _safeCall(func: Callable, *args: Any) -> None:
	try:
		func(*args)
	except Exception:
		log.exception("Error ejecutando la acción del menú %r", func)


# ====================================================================== icono de notificación
def _findIconFile() -> str | None:
	# Compilado: data\images\tiresias.ico; desde el código: resources\tiresias.ico.
	for base in (paths.PROGRAM_DATA_DIR, paths.APP_DIR, paths.SOURCE_DIR):
		for rel in (("images", "tiresias.ico"), ("tiresias.ico",), ("resources", "tiresias.ico")):
			p = os.path.join(base, *rel)
			if os.path.isfile(p):
				return p
	return None


def _makeIcon() -> wx.Icon:
	"""Icono del programa (archivo ``tiresias.ico`` o uno dibujado)."""
	path = _findIconFile()
	if path:
		icon = wx.Icon(path, wx.BITMAP_TYPE_ICO)
		if icon.IsOk():
			return icon
	size = 32
	bmp = wx.Bitmap(size, size, 32)
	dc = wx.MemoryDC(bmp)
	dc.SetBackground(wx.Brush(wx.Colour(0, 0, 0)))
	dc.Clear()
	dc.SetBrush(wx.Brush(wx.Colour(30, 70, 140)))
	dc.SetPen(wx.Pen(wx.Colour(255, 255, 255), 2))
	dc.DrawEllipse(1, 1, size - 2, size - 2)
	dc.SetTextForeground(wx.Colour(255, 255, 255))
	dc.SetFont(wx.Font(16, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
	tw, th = dc.GetTextExtent("T")
	dc.DrawText("T", (size - tw) // 2, (size - th) // 2)
	dc.SelectObject(wx.NullBitmap)
	bmp.SetMaskColour(wx.Colour(0, 0, 0))
	icon = wx.Icon()
	icon.CopyFromBitmap(bmp)
	return icon


class TrayIcon(wx.adv.TaskBarIcon):
	def __init__(self) -> None:
		super().__init__()
		self.SetIcon(_makeIcon(), APP_NAME)
		self.Bind(wx.adv.EVT_TASKBAR_LEFT_UP, self.onActivate)
		self.Bind(wx.adv.EVT_TASKBAR_RIGHT_UP, self.onActivate)

	def onActivate(self, evt: wx.Event) -> None:
		wx.CallAfter(showMenu)


# ====================================================================== menú principal
#: Entradas que los complementos añaden al menú Herramientas:
#: identificador → (etiqueta, acción o constructor del submenú, ¿es submenú?).
_addonToolsEntries: dict[str, tuple[str, Callable, bool]] = {}


def registerToolsMenuItem(itemId: str, label: str, action: Callable, submenu: bool = False) -> None:
	"""Añade (o sustituye) una entrada de un complemento al menú Herramientas.

	``action`` se llama en el hilo de la interfaz al elegir la entrada. Con
	``submenu=True``, ``action`` se llama al abrir el menú de Tiresias y
	devuelve la lista de entradas del submenú: tuplas ``(etiqueta, función)``,
	``(etiqueta, lista)`` para un submenú anidado o ``None`` para un separador.
	Las entradas se ordenan por etiqueta, entre las de productividad y el
	visor de registro. Se puede llamar desde cualquier hilo.
	"""
	_addonToolsEntries[itemId] = (label, action, submenu)


def unregisterToolsMenuItem(itemId: str) -> None:
	"""Quita la entrada ``itemId`` del menú Herramientas (en ``terminate``)."""
	_addonToolsEntries.pop(itemId, None)


def _buildAddonSubMenu(frame: MainFrame, entries: list) -> wx.Menu:
	sub = wx.Menu()
	for entry in entries or []:
		if entry is None:
			sub.AppendSeparator()
			continue
		label, target = entry
		if isinstance(target, (list, tuple)):
			sub.AppendSubMenu(_buildAddonSubMenu(frame, list(target)), label)
		else:
			frame.addMenuItem(sub, label, target)
	return sub


def _buildMainMenu(frame: MainFrame) -> wx.Menu:
	add = frame.addMenuItem
	menu = wx.Menu()
	try:
		# Estado frente a otros lectores de pantalla (en espera, activar, ceder).
		from ..coexist import ui as coexistUi

		coexistUi.appendMenuItems(frame, menu)
	except Exception:
		log.exception("No se pudieron añadir las entradas de convivencia")

	from ..config import policy as _policy

	prefs = wx.Menu()
	add(prefs, _("&Opciones..."), lambda: showSettings())
	add(prefs, _("Ajustes &rápidos..."), showQuickSettings)
	add(prefs, _("Seleccionar &sintetizador..."), showSynthSelection)
	add(prefs, _("Gestor de voces &neuronales Piper..."), _showPiperVoiceManager)
	add(prefs, _("Seleccionar &línea braille..."), showBrailleDisplaySelection)
	add(prefs, _("&Perfiles de configuración..."), showProfiles)
	dicts = wx.Menu()
	add(dicts, _("Diccionario &por defecto..."), lambda: showSpeechDictionary("default"))
	add(dicts, _("Diccionario de la &voz actual..."), lambda: showSpeechDictionary("voice"))
	add(dicts, _("Diccionario &temporal..."), lambda: showSpeechDictionary("temp"))
	add(dicts, _("Diccionario del p&erfil activo..."), lambda: showSpeechDictionary("profile"))
	prefs.AppendSubMenu(dicts, _("Diccionarios de &voz"))
	add(prefs, _("Puntuación y &símbolos..."), showSymbols)
	add(prefs, _("Alfabeto &fonético..."), lambda: _speechDialog("showPhoneticAlphabet"))
	add(prefs, _("&Esquemas de voz y sonido..."), lambda: _speechDialog("showVoiceSchemes"))
	add(prefs, _("Plantillas de &anuncio de controles..."), lambda: _speechDialog("showRoleTemplates"))
	add(prefs, _("&Gestos de entrada..."), showInputGestures)
	add(prefs, _("&Interacción táctil..."), lambda: showSettings("touch"))
	add(prefs, _("&Tecla del menú de Tiresias..."), showMenuKeyDialog)
	add(prefs, _("&Etiquetas personalizadas..."), showLabelsManager)
	prefs.AppendSeparator()
	if _policy.isAllowed("factoryReset"):
		add(prefs, _("Restablecer valores de &fábrica..."), askFactoryReset)
	if conf.canUndoFactoryReset:
		add(prefs, _("&Deshacer el restablecimiento de fábrica"), undoFactoryReset)
	menu.AppendSubMenu(prefs, _("&Preferencias"))

	tools = wx.Menu()
	from . import speech_viewer

	add(tools, _("&Visor de voz"), toggleSpeechViewer, wx.ITEM_CHECK, speech_viewer.isActive())
	add(tools, _("Visor &braille"), toggleBrailleViewer, wx.ITEM_CHECK, _isBrailleViewerActive())
	add(tools, _("&Historial de voz..."), showSpeechHistory)
	add(tools, _("Historial del &portapapeles..."), showClipboardHistory)
	add(tools, _("Paleta de ó&rdenes..."), _commandPaletteFromMenu)
	add(tools, _("&Mezclador de audio..."), _showAudioMixer)
	try:
		from . import productivity_dialogs

		productivity_dialogs.appendToolsMenu(frame, tools)
	except Exception:
		log.exception("No se pudieron añadir las entradas de productividad")
	if _addonToolsEntries:
		tools.AppendSeparator()
		for label, action, submenu in sorted(_addonToolsEntries.values(), key=lambda e: e[0].replace("&", "").lower()):
			try:
				if submenu:
					tools.AppendSubMenu(_buildAddonSubMenu(frame, action()), label)
				else:
					add(tools, label, action)
			except Exception:
				log.exception("No se pudo añadir la entrada de complemento %r", label)
		tools.AppendSeparator()
	add(tools, _("Visor de &registro..."), showLogViewer)
	if _policy.isAllowed("pythonConsole"):
		add(tools, _("Consola de P&ython..."), showPythonConsole)
	add(tools, _("&Recargar complementos"), _reloadPlugins)
	if _policy.isAllowed("openDataFolder"):
		add(tools, _("Abrir carpeta de &datos"), _openDataFolder)
	tools.AppendSeparator()
	if _policy.isAllowed("createPortable"):
		add(tools, _("Crear copia por&table..."), showCreatePortable)
	if paths.FROZEN and not paths.isInstalledCopy() and _policy.isAllowed("install"):
		add(tools, _("&Instalar Tiresias en este equipo..."), showInstaller)
	add(tools, _("Reparar los registros &COM de accesibilidad..."), runComRepair)
	if not conf.readOnly:
		add(tools, _("Importar configuración de &NVDA..."), showNvdaImport)
	menu.AppendSubMenu(tools, _("&Herramientas"))

	try:
		from .. import vision_commands

		menu.AppendSubMenu(vision_commands.buildMenu(frame), _("&Visión e IA"))
	except Exception:
		log.exception("No se pudo crear el submenú de visión e IA")

	try:
		from . import remote_dialogs

		menu.AppendSubMenu(remote_dialogs.buildMenu(frame), _("&Acceso remoto"))
	except Exception:
		log.exception("No se pudo crear el submenú de acceso remoto")

	addonsMenu = wx.Menu()
	add(addonsMenu, _("&Administrador de complementos..."), showAddonsManager)
	if _policy.isAllowed("addonStore"):
		add(addonsMenu, _("&Tienda de complementos..."), showAddonStore)
	menu.AppendSubMenu(addonsMenu, _("&Complementos"))

	helpMenu = wx.Menu()
	add(helpMenu, _("&Manual de usuario"), showUserManual)
	add(helpMenu, _("&Referencia rápida de órdenes"), showKeyCommandsReference)
	add(helpMenu, _("&Novedades"), showNews)
	add(helpMenu, _("&Tutorial de primeros pasos..."), showTutorial)
	add(helpMenu, _("Diálogo de &bienvenida..."), showWelcome)
	add(helpMenu, _("&Licencia"), showLicense)
	if _policy.isAllowed("updateCheck"):
		from .. import updates

		add(helpMenu, _("Buscar a&ctualización..."), lambda: queue_handler.queueFunction(updates.checkNow, True))
		if updates.pendingUpdate is not None:
			info = updates.pendingUpdate
			add(helpMenu, _("&Instalar la actualización {version}...").format(version=info.version), lambda: showUpdateDialog(info))
	add(helpMenu, _("&Acerca de..."), showAbout)
	menu.AppendSubMenu(helpMenu, _("Ay&uda"))

	menu.AppendSeparator()
	add(menu, _("&Guardar configuración"), _saveConfiguration)
	add(menu, _("&Restablecer configuración guardada"), _revertConfiguration)
	menu.AppendSeparator()
	add(menu, _("&Salir"), askQuit)
	return menu


def _showPiperVoiceManager() -> None:
	from . import piper_dialog

	piper_dialog.showVoiceManager()


def _showAudioMixer() -> None:
	from . import audio_dialogs

	audio_dialogs.showMixer()


def _isBrailleViewerActive() -> bool:
	try:
		from .. import braille

		return braille.handler.viewerActive
	except Exception:
		return False


def _commandPaletteFromMenu() -> None:
	"""Desde el menú: las órdenes se reúnen en el hilo del núcleo."""

	def collect() -> None:
		from . import command_palette

		showCommandPalette(command_palette.collectEntries())

	queue_handler.queueFunction(collect)


def _reloadPlugins() -> None:
	from .. import core, speech

	def reload() -> None:
		core.reloadPlugins()
		speech.speakMessage(_("Complementos recargados"))

	queue_handler.queueFunction(reload)


def _openDataFolder() -> None:
	try:
		os.startfile(paths.DATA_DIR)
	except OSError:
		log.exception("No se pudo abrir la carpeta de datos")
		messageBox(_("No se pudo abrir la carpeta de datos:\n{path}").format(path=paths.DATA_DIR), _("Error"), wx.OK | wx.ICON_ERROR)


def saveBlockedMessage() -> str | None:
	"""Por qué no se puede guardar la configuración ahora (``None`` si se puede).

	En modo seguro o con la configuración de solo lectura ``conf.save()`` no
	escribe nada: no se dice «Configuración guardada».
	"""
	from ..config import policy as _pol

	if not _pol.isAllowed("saveConfiguration"):
		return _pol.blockedMessage()
	if conf.readOnly:
		return _("La configuración es de solo lectura: no se ha guardado.")
	return None


def _saveConfiguration() -> None:
	def save() -> None:
		from .. import speech, synth

		problem = saveBlockedMessage()
		if problem:
			speech.speakMessage(problem)
			return
		try:
			synth.saveCurrentSettings()
			conf.save()
			speech.speakMessage(_("Configuración guardada"))
		except OSError:
			speech.speakMessage(_("No se pudo guardar la configuración"))

	queue_handler.queueFunction(save)


def _revertConfiguration() -> None:
	def revert() -> None:
		from .. import core, speech

		conf.revertToSaved()
		core.applyConfiguration()
		speech.speakMessage(_("Configuración restaurada a la última guardada"))

	queue_handler.queueFunction(revert)


# ====================================================================== salir
QUIT_ACTIONS: list[tuple[str, str]] = [
	("quit", _("Salir")),
	("restart", _("Reiniciar")),
	("restartSafe", _("Reiniciar sin complementos")),
	("restartDebug", _("Reiniciar con el registro de depuración activado")),
	("restartSafeDebug", _("Reiniciar sin complementos y con el registro de depuración")),
	("restartAdmin", _("Reiniciar como administrador (para leer programas elevados)")),
]


class QuitDialog(wx.Dialog):
	"""Confirmación de salida con opción de reiniciar."""

	def __init__(self) -> None:
		super().__init__(None, title=_("Salir de Tiresias"))
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(wx.StaticText(self, label=_("¿Seguro que quieres salir de Tiresias?")), 0, wx.ALL, 8)
		sizer.Add(wx.StaticText(self, label=_("&Qué hacer:")), 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
		self.choice = wx.Choice(self, choices=[label for _k, label in QUIT_ACTIONS])
		self.choice.SetSelection(0)
		sizer.Add(self.choice, 0, wx.EXPAND | wx.ALL, 8)
		buttons = wx.BoxSizer(wx.HORIZONTAL)
		ok = wx.Button(self, wx.ID_OK, _("Aceptar"))
		ok.SetDefault()
		cancel = wx.Button(self, wx.ID_CANCEL, _("Cancelar"))
		buttons.Add(ok, 0, wx.ALL, 4)
		buttons.Add(cancel, 0, wx.ALL, 4)
		sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_BUTTON, self.onOk, id=wx.ID_OK)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.Close(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, self.onClose)
		self.CentreOnScreen()
		self.choice.SetFocus()

	def onOk(self, evt: wx.CommandEvent) -> None:
		action = QUIT_ACTIONS[max(0, self.choice.GetSelection())][0]
		self.Close()
		_doQuit(action)

	def onClose(self, evt: wx.CloseEvent) -> None:
		global _quitDialog
		_quitDialog = None
		self.Destroy()


_quitDialog: QuitDialog | None = None


def _doQuit(action: str = "quit") -> None:
	from .. import core

	if action == "restart":
		queue_handler.queueFunction(core.restart)
	elif action == "restartSafe":
		queue_handler.queueFunction(core.restart, True)
	elif action == "restartDebug":
		queue_handler.queueFunction(core.restart, False, True)
	elif action == "restartSafeDebug":
		queue_handler.queueFunction(core.restart, True, True)
	elif action == "restartAdmin":
		queue_handler.queueFunction(core.restartAsAdmin)
	else:
		queue_handler.queueFunction(core.requestQuit)


def askQuit() -> None:
	"""Pregunta si salir (o reiniciar) según ``general.askToExit``."""

	def _ask() -> None:
		global _quitDialog
		if not conf["general"]["askToExit"]:
			_doQuit("quit")
			return
		if not isAlive(_quitDialog):
			_quitDialog = QuitDialog()
			_quitDialog.Show()
		bringToFront(_quitDialog)
		_quitDialog.choice.SetFocus()

	runOnGui(_ask)


# ====================================================================== inicio y cierre
def initialize(app: wx.App, mainWindowTitle: str) -> None:
	"""Crea la ventana principal oculta y el icono de notificación.

	Se llama en el hilo de la interfaz antes de ``app.MainLoop()``.
	"""
	global mainFrame, mainFrameHwnd, trayIcon
	from ..a11y import own_windows

	# MSAA de las ventanas propias: se lee en este hilo (ver a11y/own_windows.py).
	own_windows.initialize()
	mainFrame = MainFrame(mainWindowTitle)
	mainFrameHwnd = int(mainFrame.GetHandle())
	app.SetTopWindow(mainFrame)
	try:
		# Pantalla de bloqueo: ocultar los visores al bloquear (y guardas del modo seguro).
		from .. import lock_guard

		lock_guard.startMonitor()
	except Exception:
		log.exception("No se pudo vigilar la pantalla de bloqueo")
	from .. import core

	try:
		# --minimal: sin icono en el área de notificación.
		trayIcon = None if (core.args is not None and core.args.minimal) else TrayIcon()
	except Exception:
		log.exception("No se pudo crear el icono de notificación")
		trayIcon = None


def _closeModalDialogs() -> bool:
	"""Cierra los diálogos modales abiertos; ``True`` si había alguno.

	Un diálogo modal tiene su propio bucle de mensajes: mientras sigue
	abierto, el bucle principal no termina (y destruirlo dentro de
	``ShowModal`` falla). Se cierran con ``EndModal`` (los de wx) o con
	Cancelar (los nativos de Windows: mensajes, abrir y guardar archivos).
	"""
	found = False
	for win in list(wx.GetTopLevelWindows()):
		try:
			if isinstance(win, wx.Dialog) and win.IsModal():
				found = True
				win.EndModal(wx.ID_CANCEL)
		except Exception:
			log.debug("No se pudo cerrar un diálogo modal", exc_info=True)
	try:
		import ctypes
		import ctypes.wintypes as wt

		u32 = ctypes.WinDLL("user32")
		proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
		natives: list[int] = []

		def _collect(hwnd, lParam):
			buf = ctypes.create_unicode_buffer(16)
			u32.GetClassNameW(hwnd, buf, 16)
			if buf.value == "#32770" and u32.IsWindowVisible(hwnd):
				natives.append(hwnd)
			return True

		u32.EnumThreadWindows(ctypes.windll.kernel32.GetCurrentThreadId(), proc(_collect), 0)
		for hwnd in natives:
			found = True
			u32.PostMessageW(wt.HWND(hwnd), 0x0111, 2, 0)  # WM_COMMAND, IDCANCEL
			u32.PostMessageW(wt.HWND(hwnd), 0x0010, 0, 0)  # WM_CLOSE
	except Exception:
		log.debug("No se pudieron cerrar los diálogos nativos", exc_info=True)
	return found


def exitMainLoop() -> None:
	"""Cierra los diálogos modales, destruye el icono y las ventanas y termina el bucle de la interfaz."""
	attempts = [0]

	def _exit() -> None:
		global mainFrame, trayIcon
		# Primero, los diálogos modales (también si al cerrar uno se abre otro).
		if attempts[0] < 50 and _closeModalDialogs():
			attempts[0] += 1
			wx.CallLater(50, _exit)
			return
		if trayIcon is not None:
			try:
				trayIcon.RemoveIcon()
				trayIcon.Destroy()
			except Exception:
				log.debug("Error eliminando el icono de notificación", exc_info=True)
			trayIcon = None
		for win in list(wx.GetTopLevelWindows()):
			try:
				win.Destroy()
			except Exception:
				pass
		mainFrame = None
		app = wx.GetApp()
		if app is not None:
			app.ExitMainLoop()

	runOnGui(_exit)


def showMenu() -> None:
	"""Muestra el menú de Tiresias."""

	def _show() -> None:
		if isAlive(mainFrame):
			mainFrame.showMenu()

	runOnGui(_show)


def messageBox(text: str, title: str = APP_NAME, style: int = wx.OK | wx.ICON_INFORMATION, parent: wx.Window | None = None) -> int | None:
	"""Muestra un cuadro de mensaje modal.

	En el hilo de la interfaz devuelve el botón pulsado (``wx.OK``,
	``wx.YES``, ``wx.NO``, ``wx.CANCEL``). Desde otro hilo se programa y
	devuelve ``None``.
	"""
	if not wx.IsMainThread():
		runOnGui(messageBox, text, title, style, parent)
		return None
	useFrame = parent is None and isAlive(mainFrame)
	if useFrame:
		mainFrame.prePopup()
	try:
		# Cuadro propio con el texto en un campo de solo lectura recorrible (#258).
		from .message_dialog import messageBox as _tiresiasMessageBox

		return _tiresiasMessageBox(text, title, style, parent or (mainFrame if useFrame else None))
	finally:
		if useFrame:
			mainFrame.postPopup()


# ====================================================================== diálogos de configuración
def showSettings(category: str | None = None) -> None:
	"""Abre las opciones (``category``: "general", "speech", "braille"...)."""

	def _show() -> None:
		from . import settings

		settings.showSettings(category)

	runOnGui(_show)


def showSynthSelection() -> None:
	def _show() -> None:
		from . import settings

		settings.showSynthSelection()

	runOnGui(_show)


def showBrailleDisplaySelection() -> None:
	def _show() -> None:
		from . import braille_display_dialog

		braille_display_dialog.showDialog()

	runOnGui(_show)


def _configDialog(name: str, *args: Any) -> None:
	def _show() -> None:
		from . import config_dialogs

		getattr(config_dialogs, name)(*args)

	runOnGui(_show)


def _speechDialog(name: str, *args: Any) -> None:
	"""Diálogos del núcleo de voz (alfabeto fonético, esquemas, plantillas)."""

	def _show() -> None:
		from . import speech_dialogs

		getattr(speech_dialogs, name)(*args)

	runOnGui(_show)


def showProfiles() -> None:
	_configDialog("showProfiles")


def showAddonsManager() -> None:
	_configDialog("showAddonsManager")


def showInputGestures() -> None:
	_configDialog("showInputGestures")


def showMenuKeyDialog() -> None:
	"""Configurar la combinación que abre el menú de Tiresias."""

	def _show() -> None:
		from . import gesture_tools

		gesture_tools.showMenuKeyDialog()

	runOnGui(_show)


def showSpeechDictionary(kind: str = "default") -> None:
	"""``kind``: "default", "voice" o "temp"."""
	_configDialog("showSpeechDictionary", kind)


def showSymbols() -> None:
	_configDialog("showSymbols")


def showWelcome() -> None:
	_configDialog("showWelcome")


def showAbout() -> None:
	_configDialog("showAbout")


# ====================================================================== herramientas
def showPythonConsole() -> None:
	"""Abre la consola de Python con ``focus`` y ``nav`` del momento."""
	focus = nav = None
	try:
		from .. import api

		focus = api.getFocusObject()
		nav = api.getNavigatorObject()
	except Exception:
		log.debug("No se pudieron obtener los objetos para la consola", exc_info=True)
	from . import python_console

	python_console.show(focus, nav)


def showCommandPalette(entries: list) -> None:
	"""Muestra la paleta con entradas de ``command_palette.collectEntries()``."""
	from . import command_palette

	command_palette.showCommandPalette(entries)


def showClipboardHistory() -> None:
	from . import history_dialogs

	history_dialogs.showClipboardHistory()


def showSpeechHistory() -> None:
	from . import history_dialogs

	history_dialogs.showSpeechHistory()


def showBrowseableMessage(text: str, title: str = "", isHtml: bool = False) -> None:
	from . import dialogs

	dialogs.showBrowseableMessage(text, title, isHtml)


def chooseFromList(title: str, prompt: str, items: list[str], callback: Callable[[str], None]) -> None:
	"""Lista con filtro para elegir un elemento; ``callback`` se llama en el hilo de la interfaz."""
	from . import dialogs

	runOnGui(dialogs.chooseFromList, title, prompt, items, callback)


def askText(title: str, prompt: str, default: str, callback: Callable[[str], None], onCancel: Callable[[], None] | None = None) -> None:
	"""Pide un texto; ``callback(texto)`` se llama en el hilo de la interfaz si se acepta
	y ``onCancel()`` si se cancela."""
	from . import dialogs

	dialogs.askText(title, prompt, default, callback, onCancel)


def showLogViewer() -> None:
	from . import log_viewer

	log_viewer.show()


def toggleSpeechViewer() -> None:
	from . import speech_viewer

	speech_viewer.toggle()


def toggleBrailleViewer() -> None:
	"""Abre o cierra el visor braille (espejo de la línea real si hay una)."""
	from .. import braille

	queue_handler.queueFunction(braille.handler.setViewer, not _isBrailleViewerActive())


def showUserManual() -> None:
	def _show() -> None:
		path = paths.manualPath()
		if os.path.isfile(path):
			try:
				os.startfile(path)
				return
			except OSError:
				log.exception("No se pudo abrir el manual")
		messageBox(_("No se encontró el manual de usuario:\n{path}").format(path=path), _("Manual de usuario"), wx.OK | wx.ICON_WARNING)

	runOnGui(_show)


def buildKeyCommandsReference() -> str:
	"""Texto con todas las órdenes (globales, modo exploración, aplicaciones y complementos)."""
	from . import keyref

	return keyref.buildText()


def showKeyCommandsReference() -> None:
	"""Referencia rápida de órdenes en HTML navegable con todas las órdenes."""

	def _show() -> None:
		from . import keyref

		try:
			# Documento HTML con encabezados por sección: se recorre con la tecla H.
			os.startfile(keyref.writeHtml())
		except Exception:
			log.exception("No se pudo generar la referencia en HTML")
			text = buildKeyCommandsReference()
			runOnGui(showBrowseableMessage, text, _("Referencia rápida de órdenes"))

	# Generarla importa todos los módulos de aplicación (también los de los
	# complementos): en un hilo propio, ni en la interfaz ni en el núcleo.
	import threading

	threading.Thread(target=_show, name="Referencia de órdenes", daemon=True).start()


# ====================================================================== área de configuración e instalación
def _system(name: str, *args: Any) -> None:
	"""Llama a una función de :mod:`.system_dialogs` en el hilo de la interfaz."""

	def _show() -> None:
		from . import system_dialogs

		getattr(system_dialogs, name)(*args)

	runOnGui(_show)


def showQuickSettings() -> None:
	"""Ajustes rápidos: buscar y cambiar cualquier opción."""
	_system("showQuickSettings")


def showLabelsManager() -> None:
	_system("showLabelsManager")


def showAddonStore() -> None:
	_system("showAddonStore")


def showUpdateDialog(info: Any) -> None:
	_system("showUpdateDialog", info)


def showCreatePortable() -> None:
	_system("showCreatePortable")


def showNvdaImport(folder: str | None = None) -> None:
	"""Diálogo «Importar configuración de NVDA»."""

	def _show() -> None:
		from . import nvda_import_dialog

		nvda_import_dialog.show(folder)

	runOnGui(_show)


def showInstaller() -> None:
	def _show() -> None:
		from . import installer_dialogs

		installer_dialogs.showInstallDialog()

	runOnGui(_show)


def runComRepair() -> None:
	_system("runComRepair")


def showNews() -> None:
	_system("showNews")


def showLicense() -> None:
	_system("showLicense")


def showTutorial() -> None:
	def _show() -> None:
		from . import tutorial

		tutorial.show()

	runOnGui(_show)


def askFactoryReset() -> None:
	_system("askFactoryReset")


def undoFactoryReset() -> None:
	_system("undoFactoryReset")


def showTrayNotification(title: str, text: str) -> None:
	"""Globo discreto en el área de notificación (sin robar el foco)."""

	def _show() -> None:
		if trayIcon is None:
			return
		try:
			trayIcon.ShowBalloon(title, text, 10000)
		except Exception:
			log.debug("No se pudo mostrar el globo", exc_info=True)

	runOnGui(_show)
