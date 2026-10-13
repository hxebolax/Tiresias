"""Explorador de Windows: escritorio, barra de tareas, bandeja, Alt+Tab y carpetas.

- El panel vacío del escritorio («Program Manager») no se anuncia.
- Los iconos de la bandeja del sistema se leen sin saltos de línea ni marcas
  de dirección invisibles (el reloj, la red, el volumen...).
- En la vista de tareas (Alt+Tab y Windows+Tab) se lee la ventana
  seleccionada aunque no reciba el foco. Con Alt pulsada (Alt+Tab) solo se
  dice la ventana elegida, como NVDA, y el foco vacío que Windows 11 da al
  panel de la isla XAML no corta su lectura.
- En las carpetas, opción «Leer las columnas de detalles» (panel
  Aplicaciones) y Tiresias+Alt+Mayúsculas+D para leerlas a demanda:
  fecha de modificación, tipo, tamaño...
- Los avisos emergentes (flyouts) de volumen, brillo y modo avión se leen
  cuando aparecen.
"""

from __future__ import annotations

import time

from .. import api, presentation, speech
from ..baseobject import script
from ..config import conf
from ..i18n import _
from ..objects.base import AccObject
from ..objects.roles import Role
from . import AppModule as BaseAppModule

CAT = _("Explorador de Windows")

#: Marcas invisibles de dirección de texto que Windows mete en fechas y horas.
_INVISIBLE = dict.fromkeys(map(ord, "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u200b"), None)
#: Clases de los elementos de la vista de tareas (Alt+Tab) en Windows 10 y 11.
TASK_SWITCHER_CLASSES = ("MultitaskingViewFrame", "XamlExplorerHostIslandWindow", "TaskSwitcherWnd", "ForegroundStaging")
#: Panel de entrada de las islas XAML de Windows 11: recibe un foco vacío al
#: abrir Alt+Tab, justo después del foco en la ventana elegida.
INPUT_SITE_CLASS = "Windows.UI.Input.InputSite.WindowClass"


def cleanText(text: str) -> str:
	"""Quita marcas invisibles y une las líneas."""
	if not text:
		return ""
	return " ".join(text.translate(_INVISIBLE).split())


def detailColumns(item) -> list[tuple[str, str]]:
	"""(columna, valor) de un elemento de la vista de detalles, sin la columna Nombre."""
	out = []
	try:
		for c in item.children:
			if getattr(c, "UIAAutomationId", "") == "System.ItemNameDisplay":
				continue
			if getattr(c, "UIAClassName", "") != "UIProperty":
				continue
			value = cleanText(c.value)
			if value:
				out.append((c.name, value))
	except Exception:
		pass
	return out


def isFileItem(obj) -> bool:
	try:
		return getattr(obj, "UIAClassName", "") == "UIItem" and obj.role in (Role.LISTITEM, Role.DATAITEM)
	except Exception:
		return False


class FileListItem(AccObject):
	"""Elemento de la lista de archivos de una carpeta.

	Con «Leer las columnas de detalles», las columnas van como valor del
	elemento: «alfa, Fecha de modificación …, Tipo …, Tamaño …, 1 de 5» (el
	nombre, los detalles y la posición, en ese orden y en un solo anuncio).
	"""

	def _get_value(self) -> str:
		if conf["explorer"]["reportDetailsColumns"]:
			cols = detailColumns(self)
			if cols:
				return ", ".join(f"{name} {value}" for name, value in cols)
		return super()._get_value()


def inTaskSwitcher(obj) -> bool:
	"""``True`` si ``obj`` está en la vista de tareas (Alt+Tab, Windows+Tab)."""
	from .. import winapi

	try:
		hwnd = obj.windowHandle
		if not hwnd:
			return False
		return winapi.getClassName(hwnd) in TASK_SWITCHER_CLASSES or winapi.getClassName(winapi.getAncestor(hwnd, winapi.GA_ROOT)) in TASK_SWITCHER_CLASSES
	except Exception:
		return False


def altHeld() -> bool:
	"""Alt pulsada: el conmutador es el de Alt+Tab (no Windows+Tab ni Control+Alt+Tab)."""
	from .. import winapi

	try:
		return winapi.isKeyDown(winapi.VK_MENU)
	except Exception:
		return False


def isTaskSwitcherInputSite(obj) -> bool:
	"""Panel sin nombre que toma el foco al abrirse Alt+Tab en Windows 11."""
	try:
		if obj.role != Role.PANE or obj.name:
			return False
		if INPUT_SITE_CLASS in (getattr(obj, "UIAClassName", ""), getattr(obj, "windowClassName", "")):
			return True
		return inTaskSwitcher(obj)
	except Exception:
		return False


class TaskSwitcherInputSite(AccObject):
	"""Foco falso del conmutador de tareas de Windows 11.

	Llega unos 150 ms después del foco en la ventana elegida y, sin nombre ni
	contenido, solo cortaba su lectura (el primer Alt+Tab no decía nada útil).
	NVDA tampoco acepta este foco.
	"""

	isPresentableFocusAncestor = False

	def _get_shouldAllowFocusEvent(self) -> bool:
		return False


class AppModule(BaseAppModule):
	scriptCategory = CAT

	def __init__(self, processID: int, appName: str | None = None) -> None:
		super().__init__(processID, appName)
		self._lastSelection = ("", 0.0)

	def chooseObjectClass(self, obj, clsList: list[type]) -> None:
		if isFileItem(obj):
			clsList.insert(0, FileListItem)
		elif isTaskSwitcherInputSite(obj):
			clsList.insert(0, TaskSwitcherInputSite)

	def event_NVDAObject_init(self, obj) -> None:
		# Bandeja del sistema: «Reloj 16:22\n\u200e06/\u200e10/\u200e2026», «Red X\nAcceso a Internet»...
		try:
			if getattr(obj, "UIAAutomationId", "") in ("NotifyItemIcon", "SystemTrayIcon"):
				name = obj.name
				clean = cleanText(name)
				if clean != name:
					obj.name = clean
		except Exception:
			pass

	def event_gainFocus(self, obj, nextHandler) -> None:
		# El panel del escritorio («Program Manager») no aporta nada al leerse.
		try:
			if obj.role == Role.PANE and obj.windowClassName in ("Progman", "WorkerW") and not obj.name:
				return
		except Exception:
			pass
		try:
			if obj.role in (Role.LISTITEM, Role.BUTTON, Role.DATAITEM) and self._inTaskSwitcher(obj):
				# La selección que llegue justo después no la repite.
				self._lastSelection = (cleanText(obj.name), time.monotonic())
		except Exception:
			pass
		nextHandler()

	def _inTaskSwitcher(self, obj) -> bool:
		return inTaskSwitcher(obj)

	def _isAltTabSwitcher(self, obj) -> bool:
		return altHeld() and self._inTaskSwitcher(obj)

	def event_foreground(self, obj, nextHandler) -> None:
		# Alt+Tab (Alt pulsada): como NVDA, solo se dice la ventana elegida; ni
		# «Conmutación de tareas» ni «Aplicaciones en ejecución lista».
		if self._isAltTabSwitcher(obj):
			return
		nextHandler()

	def event_focusEntered(self, obj, nextHandler) -> None:
		if self._isAltTabSwitcher(obj):
			return
		nextHandler()

	def event_selection(self, obj, nextHandler) -> None:
		# Alt+Tab: la ventana elegida se selecciona sin recibir el foco.
		if obj.role in (Role.LISTITEM, Role.BUTTON, Role.DATAITEM) and self._inTaskSwitcher(obj):
			name = cleanText(obj.name)
			now = time.monotonic()
			try:
				isFocus = obj == api.getFocusObject()
			except Exception:
				isFocus = False
			if name and not isFocus and not (name == self._lastSelection[0] and now - self._lastSelection[1] < 0.4):
				self._lastSelection = (name, now)
				speech.cancelSpeech()
				presentation.speakObject(obj, reason=presentation.Reason.FOCUS)
			return
		nextHandler()

	def event_windowOpened(self, obj, nextHandler) -> None:
		# Avisos emergentes del sistema (volumen, brillo, modo avión).
		try:
			if obj.role in (Role.WINDOW, Role.PANE, Role.DIALOG) and getattr(obj, "UIAAutomationId", "") in ("FlyoutContentHost", "VolumeFlyout", "BrightnessFlyout"):
				text = cleanText(obj.name or " ".join(c.name for c in obj.children if c.name))
				if text:
					speech.speakText(text)
		except Exception:
			pass
		nextHandler()

	@script(description=_("Lee las columnas de detalles del archivo seleccionado (fecha, tipo, tamaño...)"), category=CAT, gesture="kb:tiresias+alt+shift+d", speakOnDemand=True)
	def script_readDetails(self, gesture) -> None:
		focus = api.getFocusObject()
		if focus is None or not isFileItem(focus):
			speech.speakMessage(_("No hay ningún archivo seleccionado"))
			return
		cols = detailColumns(focus)
		if not cols:
			speech.speakMessage(_("Sin detalles: usa la vista Detalles de la carpeta"))
			return
		speech.speakText(", ".join(f"{name} {value}" for name, value in cols))
