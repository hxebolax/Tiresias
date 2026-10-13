"""Módulos de aplicación.

Un módulo de aplicación adapta Tiresias a un programa concreto. Se carga
automáticamente cuando el programa tiene el foco. El archivo debe llamarse
como el ejecutable en minúsculas, sin extensión y con los puntos cambiados
por guiones bajos (``WhatsApp.Root.exe`` → ``whatsapp_root.py``), y definir
una clase ``AppModule`` que herede de :class:`AppModule`::

	from tiresias.appmodules import AppModule as BaseAppModule
	from tiresias.baseobject import script

	class AppModule(BaseAppModule):
		@script(description="Saluda", gesture="kb:tiresias+h")
		def script_saludar(self, gesture):
			from tiresias import speech
			speech.speakMessage("Hola desde " + self.appName)

		def event_gainFocus(self, obj, nextHandler):
			nextHandler()

Los ejecutables cuyo nombre no sirve como módulo de Python (``notepad++``) o
que comparten módulo (``code - insiders`` → ``code``) se asocian en
:data:`tiresias.appmodules.handler.EXECUTABLE_ALIASES`; los complementos
pueden añadir alias con :func:`tiresias.appmodules.handler.registerExecutableAlias`.

Puntos de extensión de cada módulo:

- ``chooseObjectClass(obj, clsList)``: clases superpuestas para sus objetos.
- ``event_NVDAObject_init(obj)``: se llama al crear cada objeto de la
  aplicación; puede corregir propiedades asignándolas (``obj.name = "..."``).
- ``shouldProcessEvent(eventName, obj, **kwargs)``: filtro de eventos de la
  aplicación (``False`` descarta el evento antes de toda la cadena).
- ``getStatusBar()`` y ``getStatusBarText()``: barra de estado propia para la
  orden «leer la barra de estado».
- ``sleepMode``: la aplicación se autoverbaliza y Tiresias calla en ella.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from .. import winapi
from ..baseobject import ScriptableObject
from ..config import conf
from ..log import getLogger

log = getLogger("appModule")

# Opciones de los módulos de aplicación incorporados (panel «Aplicaciones»).
conf.registerDefaults(
	"appModules",
	{
		# Aplicaciones con el modo dormir activado de forma permanente.
		"sleepApps": [],
	},
)
# Las páginas, los comentarios, las revisiones, las listas y los títulos de las
# tablas de Word y Excel siguen la sección documentFormatting (como en NVDA).
conf.registerDefaults(
	"officeWord",
	{
		"reportFormattingShortcuts": True,
	},
)
conf.registerDefaults(
	"officeExcel",
	{
		"reportCoordinates": True,
		"reportCellDetails": True,
		"reportSelection": True,
		"watchedCellsInterval": 1000,
		# Lectura de la fila o columna entera (NVDA #901): desde el principio
		# ("start") o desde la celda actual ("current"), sin las celdas vacías y
		# con el título de cada celda.
		"readLineFrom": "start",
		"readLineSkipBlank": True,
		"readLineHeaders": True,
	},
)
conf.registerDefaults(
	"mail",
	{
		# Al abrir un mensaje (Outlook y Thunderbird): "body" (solo el cuerpo,
		# NVDA #11161), "none" (nada, NVDA #15310) o "full" (lo normal).
		"openMessageReading": "body",
	},
)
conf.registerDefaults("media", {"announceTrackChanges": True})
conf.registerDefaults("charts", {"pointTones": True, "toneDuration": 120})
conf.registerDefaults("explorer", {"reportDetailsColumns": False})
conf.registerDefaults(
	"officePowerPoint",
	{
		"reportNotesIndicator": True,
		"reportHiddenSlides": True,
		"readSlideOnShow": True,
		# Leer las ecuaciones con el motor de matemáticas (si no, solo «ecuación»).
		"readEquations": True,
	},
)
conf.registerDefaults(
	"chatApps",
	{
		# Qué se anuncia automáticamente: "all", "beep" (solo un sonido) u "off".
		"alertMode": "all",
		"alertJoinLeave": True,
		"alertChat": True,
		"alertHands": True,
		"alertMute": True,
		"alertRecording": True,
		"alertSharing": True,
		"alertOther": True,
		"historySize": 50,
	},
)


_SYNCHRONIZE = 0x00100000
_WAIT_TIMEOUT = 0x102
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.OpenProcess.restype = wintypes.HANDLE
_k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_k32.WaitForSingleObject.restype = wintypes.DWORD


def _openProcessHandle(pid: int):
	"""Manejador del proceso para saber si sigue vivo (``None`` si no se puede abrir)."""
	if not pid:
		return None
	try:
		return _k32.OpenProcess(_SYNCHRONIZE | winapi.PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)) or None
	except Exception:
		return None


def _waitForSingleObject(handle, ms: int) -> int:
	return int(_k32.WaitForSingleObject(handle, ms))


class AppModule(ScriptableObject):
	#: Si es ``True``, Tiresias no lee nada en esta aplicación.
	sleepMode = False
	#: Desactiva el modo exploración automático en esta aplicación.
	disableBrowseModeByDefault = False

	def __init__(self, processID: int, appName: str | None = None) -> None:
		super().__init__()
		self.processID = processID
		self.appPath = winapi.getProcessImagePath(processID)
		self.appName = appName or winapi.getProcessName(processID)
		#: Nombre del ejecutable real (distinto de ``appName`` en javaw o wwahost).
		self.executableName = winapi.getProcessName(processID)
		self._productInfo: tuple[str, str] | None = None
		# Manejador del proceso abierto al crear el módulo: si el proceso termina y
		# Windows reutiliza su número para otro, el manejador sigue diciendo que
		# este terminó (con solo el número parecería vivo con otro programa).
		self._processHandle = _openProcessHandle(processID)
		if self.appName.lower() in {n.lower() for n in conf["appModules"]["sleepApps"] or []}:
			self.sleepMode = True

	def __del__(self) -> None:
		h = self.__dict__.get("_processHandle")
		if h:
			self.__dict__["_processHandle"] = None
			try:
				winapi.kernel32.CloseHandle(h)
			except Exception:
				pass

	def __repr__(self) -> str:
		return f"<AppModule {self.appName} pid={self.processID}>"

	# ------------------------------------------------------------ información
	def _getProductInfo(self) -> tuple[str, str]:
		if self._productInfo is not None:
			return self._productInfo
		name = version = ""
		path = self.appPath
		if path and os.path.isfile(path):
			try:
				version_dll = ctypes.WinDLL("version")
				size = version_dll.GetFileVersionInfoSizeW(path, None)
				if size:
					buf = ctypes.create_string_buffer(size)
					version_dll.GetFileVersionInfoW(path, 0, size, buf)
					ptr = ctypes.c_void_p()
					length = wintypes.UINT()
					if version_dll.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(length)) and length.value:
						lang, cp = ctypes.cast(ptr, ctypes.POINTER(wintypes.WORD * 2)).contents
						prefix = f"\\StringFileInfo\\{lang:04x}{cp:04x}\\"
						for key in ("ProductName", "ProductVersion"):
							if version_dll.VerQueryValueW(buf, prefix + key, ctypes.byref(ptr), ctypes.byref(length)) and length.value:
								val = ctypes.wstring_at(ptr, length.value - 1)
								if key == "ProductName":
									name = val
								else:
									version = val
			except Exception:
				log.debug("No se pudo leer la versión de %s", path, exc_info=True)
		self._productInfo = (name, version)
		return self._productInfo

	@property
	def productName(self) -> str:
		return self._getProductInfo()[0] or self.appName

	@property
	def productVersion(self) -> str:
		return self._getProductInfo()[1]

	@property
	def isAlive(self) -> bool:
		own = self.__dict__.get("_processHandle")
		if own:
			# WAIT_TIMEOUT: el proceso de este módulo sigue en marcha.
			return _waitForSingleObject(own, 0) == _WAIT_TIMEOUT
		h = winapi.kernel32.OpenProcess(0x00100000 | winapi.PROCESS_QUERY_LIMITED_INFORMATION, False, self.processID)
		if not h:
			return False
		try:
			code = wintypes.DWORD()
			ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
			return code.value == 259  # STILL_ACTIVE
		finally:
			winapi.kernel32.CloseHandle(h)

	def isForeground(self) -> bool:
		"""``True`` si la ventana en primer plano pertenece a esta aplicación."""
		from .. import api

		fg = api.getForegroundObject()
		try:
			if fg is not None and fg.processID == self.processID:
				return True
		except Exception:
			pass
		hwnd = winapi.getForegroundWindow()
		return bool(hwnd) and winapi.getWindowProcessId(hwnd) == self.processID

	# ------------------------------------------------------------ extensión
	def chooseObjectClass(self, obj, clsList: list[type]) -> None:
		"""Permite añadir clases superpuestas a los objetos de la aplicación."""

	def event_NVDAObject_init(self, obj) -> None:
		"""Se llama al crear cada objeto de la aplicación (tras las superposiciones).

		Puede corregir propiedades asignándolas: ``obj.name = "Enviar"``.
		"""

	def shouldProcessEvent(self, eventName: str, obj, **kwargs) -> bool:
		"""Filtro de eventos por aplicación: ``False`` descarta el evento."""
		return True

	def getStatusBar(self):
		"""Barra de estado propia de la aplicación (``None``: búsqueda genérica)."""
		return None

	def getStatusBarText(self) -> str | None:
		"""Texto de la barra de estado (``None``: se lee el objeto de la barra)."""
		return None

	def terminate(self) -> None:
		"""Se llama al descargar el módulo (la aplicación se cerró)."""

	def event_appModule_gainFocus(self) -> None:
		"""La aplicación pasa a primer plano."""

	def event_appModule_loseFocus(self) -> None:
		"""La aplicación deja el primer plano."""


# Alias compatible con el estilo de NVDA.
AppModuleBase = AppModule
