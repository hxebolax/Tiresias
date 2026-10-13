"""Detección de consolas y terminales, identidad de cada ventana y perfiles.

- :func:`instantanea` toma, en el hilo del núcleo, los datos de la ventana en
  primer plano y del objeto con el foco que hacen falta para leer la consola
  más tarde desde otro hilo (sin volver a preguntar por el foco: durante el
  seguimiento el foco está en el visor y se recapturaría a sí mismo).
- :class:`IdentidadConsola` identifica una ventana de consola durante su
  vida (ventana raíz y proceso): un visor por consola.
- :class:`DetectorTerminal` reconoce la terminal y aplica su perfil
  (limpieza ANSI, condensación de símbolos...).
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Any

#: Clases de ventana de la consola clásica (conhost).
CLASES_CLASICAS = ("ConsoleWindowClass",)
#: Windows Terminal.
CLASE_WINDOWS_TERMINAL = "CASCADIA_HOSTING_WINDOW_CLASS"
#: PuTTY y KiTTY no exponen su texto: se leen con su orden «Copiar todo».
CLASES_PUTTY = ("PuTTY", "KiTTY")
#: Clases UIA de las áreas de texto de terminal.
CLASES_UIA_TERMINAL = ("ConsoleWindowClass", "TermControl", "TermControl2", "WPFTermControl", "PseudoConsoleWindow")

#: Emuladores de terceros reconocidos (nombre del ejecutable sin extensión).
TERMINALES_SOPORTADAS = (
	"cmder", "conemu", "conemu64",
	"mintty",
	"putty", "kitty",
	"alacritty",
	"wezterm", "wezterm-gui",
	"hyper",
	"tabby", "terminus",
	"fluent", "fluentterminal",
	"ghostty", "rio", "wave", "waveterm",
	"contour", "cool-retro-term", "coolretroterm",
	"mobaxterm", "securecrt", "ttermpro", "teraterm",
	"mremoteng", "royalts", "royaltsv7",
	"intelligentterminal",
	"windowsterminal", "openconsole",
)

TIPO_CLASICA = "clasica"
TIPO_TERMINAL = "terminal"
TIPO_PUTTY = "putty"
TIPO_DESCONOCIDA = "desconocida"


@dataclass
class DestinoConsola:
	"""Lo necesario para leer una consola desde cualquier hilo."""

	tipo: str = TIPO_DESCONOCIDA
	#: Ventana en primer plano (la de la consola).
	hwnd: int = 0
	#: Ventana del objeto con el foco (puede ser la misma).
	hwndFoco: int = 0
	pid: int = 0
	clase: str = ""
	nombreApp: str = ""
	producto: str = ""
	titulo: str = ""
	nombreFoco: str = ""
	#: Elemento UIA del área de texto enfocada (``IUIAutomationElement``) o ``None``.
	elemento: Any = None
	#: El foco era un objeto con rol de terminal según Tiresias.
	focoEsTerminal: bool = False
	extra: dict = field(default_factory=dict)


def _atributo(obj: Any, nombre: str, defecto: Any = "") -> Any:
	try:
		valor = getattr(obj, nombre)
	except Exception:
		return defecto
	return defecto if valor is None else valor


def instantanea(primerPlano: Any, foco: Any) -> DestinoConsola:
	"""Datos de la consola actual (llamar en el hilo del núcleo)."""
	destino = DestinoConsola()
	app = _atributo(primerPlano, "appModule", None)
	destino.hwnd = int(_atributo(primerPlano, "windowHandle", 0) or 0)
	destino.pid = int(_atributo(primerPlano, "processID", 0) or 0)
	destino.clase = str(_atributo(primerPlano, "windowClassName", "") or "")
	destino.nombreApp = str(_atributo(app, "appName", "") or "") if app is not None else ""
	try:
		destino.producto = str(app.productName or "") if app is not None else ""
	except Exception:
		destino.producto = ""
	destino.titulo = str(_atributo(primerPlano, "name", "") or "")
	if foco is not None:
		destino.hwndFoco = int(_atributo(foco, "windowHandle", 0) or 0)
		destino.nombreFoco = str(_atributo(foco, "name", "") or "")
		try:
			from tiresias.objects.roles import Role

			destino.focoEsTerminal = _atributo(foco, "role", None) == Role.TERMINAL
		except Exception:
			destino.focoEsTerminal = False
		elemento = _atributo(foco, "element", None)
		if elemento is not None:
			try:
				fpid = int(_atributo(foco, "processID", 0) or 0)
			except (TypeError, ValueError):
				fpid = 0
			# Solo se guarda si el foco está dentro de la consola en primer plano.
			if not destino.pid or not fpid or fpid == destino.pid or destino.focoEsTerminal:
				destino.elemento = elemento
	if not destino.hwndFoco:
		destino.hwndFoco = destino.hwnd
	if not destino.clase and destino.hwnd:
		destino.clase = _claseVentana(destino.hwnd)
	destino.tipo = tipo_consola(destino)
	return destino


def _claseVentana(hwnd: int) -> str:
	try:
		buf = ctypes.create_unicode_buffer(256)
		ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
		return buf.value
	except Exception:
		return ""


def es_ventana_consola(destino: DestinoConsola) -> bool:
	"""¿La ventana en primer plano es una consola o una terminal reconocida?"""
	clase = destino.clase or ""
	if clase.startswith(CLASES_CLASICAS) or clase == CLASE_WINDOWS_TERMINAL or clase in CLASES_PUTTY:
		return True
	if "windowsterminal" in (destino.producto or "").lower().replace(" ", ""):
		return True
	if (destino.nombreApp or "").lower() in TERMINALES_SOPORTADAS:
		return True
	# Cualquier otra aplicación cuyo foco Tiresias trata como terminal.
	return bool(destino.focoEsTerminal)


def tipo_consola(destino: DestinoConsola) -> str:
	"""``clasica`` (API de consola), ``putty`` (Copiar todo) o ``terminal`` (UIA)."""
	clase = destino.clase or ""
	if "windowsterminal" in (destino.producto or "").lower().replace(" ", ""):
		return TIPO_TERMINAL
	if clase.startswith(CLASES_CLASICAS):
		return TIPO_CLASICA
	if clase in CLASES_PUTTY:
		return TIPO_PUTTY
	if clase == CLASE_WINDOWS_TERMINAL:
		return TIPO_TERMINAL
	if es_ventana_consola(destino):
		return TIPO_TERMINAL
	return TIPO_DESCONOCIDA


# ====================================================================== identidad
GA_ROOT = 2


@dataclass(frozen=True)
class IdentidadConsola:
	"""Clave inequívoca de una ventana de consola en la sesión de Windows."""

	tipo: str
	hwnd: int
	pid: int


def obtener_identidad(destino: DestinoConsola, user32: Any = None) -> IdentidadConsola | None:
	"""Normaliza la ventana a su raíz y obtiene su proceso."""
	if destino is None or not destino.hwnd:
		return None
	if user32 is None:
		user32 = ctypes.windll.user32
	hwndRaiz = destino.hwnd
	try:
		raiz = int(user32.GetAncestor(wintypes.HWND(destino.hwnd), GA_ROOT) or 0)
		if raiz:
			hwndRaiz = raiz
	except Exception:
		pass
	pid = wintypes.DWORD(0)
	try:
		user32.GetWindowThreadProcessId(wintypes.HWND(hwndRaiz), ctypes.byref(pid))
	except Exception:
		pass
	valorPid = int(pid.value) or int(destino.pid or 0)
	return IdentidadConsola(tipo=str(destino.tipo or TIPO_DESCONOCIDA), hwnd=int(hwndRaiz), pid=valorPid)


def etiqueta_consola(destino: DestinoConsola, identidad: IdentidadConsola) -> str:
	"""Título reconocible e inequívoco para la ventana del visor."""
	nombre = (destino.titulo or "").strip() or (destino.producto or destino.nombreApp or "Consola").strip()
	nombre = " ".join(nombre.split())
	return "{} [{}:{:X}]".format(nombre, identidad.pid, identidad.hwnd)


# ====================================================================== perfiles
@dataclass
class PerfilTerminal:
	"""Configuración específica de una terminal (``None`` = la opción general)."""

	nombre_app: str
	nombre_mostrar: str
	condensar_simbolos: bool | None = None
	simbolos_a_condensar: str | None = None
	modo_silencioso: bool | None = None
	limpiar_ansi: bool | None = None
	descripcion: str = ""
	es_terminal_moderna: bool = False
	soporta_uia: bool = False
	soporta_pestanas: bool = False

	def to_dict(self) -> dict:
		return {
			"nombre_app": self.nombre_app,
			"nombre_mostrar": self.nombre_mostrar,
			"condensar_simbolos": self.condensar_simbolos,
			"simbolos_a_condensar": self.simbolos_a_condensar,
			"modo_silencioso": self.modo_silencioso,
			"limpiar_ansi": self.limpiar_ansi,
			"descripcion": self.descripcion,
			"es_terminal_moderna": self.es_terminal_moderna,
			"soporta_uia": self.soporta_uia,
			"soporta_pestanas": self.soporta_pestanas,
		}

	@classmethod
	def from_dict(cls, datos: dict) -> "PerfilTerminal":
		return cls(
			nombre_app=datos.get("nombre_app", ""),
			nombre_mostrar=datos.get("nombre_mostrar", ""),
			condensar_simbolos=datos.get("condensar_simbolos"),
			simbolos_a_condensar=datos.get("simbolos_a_condensar"),
			modo_silencioso=datos.get("modo_silencioso"),
			limpiar_ansi=datos.get("limpiar_ansi"),
			descripcion=datos.get("descripcion", ""),
			es_terminal_moderna=datos.get("es_terminal_moderna", False),
			soporta_uia=datos.get("soporta_uia", False),
			soporta_pestanas=datos.get("soporta_pestanas", False),
		)


class DetectorTerminal:
	"""Reconoce la terminal activa y ofrece su perfil."""

	def __init__(self) -> None:
		self._perfiles: dict[str, PerfilTerminal] = {}
		self._perfil_activo: PerfilTerminal | None = None
		self._predefinidos()

	def _p(self, clave: str, nombre: str, descripcion: str, ansi: bool = True, condensar: bool = False, moderna: bool = False, uia: bool = False, pestanas: bool = False, silencioso: bool | None = None) -> PerfilTerminal:
		perfil = PerfilTerminal(clave, nombre, condensar_simbolos=condensar, limpiar_ansi=ansi, modo_silencioso=silencioso, descripcion=descripcion, es_terminal_moderna=moderna, soporta_uia=uia, soporta_pestanas=pestanas)
		self._perfiles[clave] = perfil
		return perfil

	def _predefinidos(self) -> None:
		# Terminales de Windows.
		self._p("cmd", "CMD (Símbolo del sistema)", "Consola de comandos clásica de Windows", ansi=False)
		self._p("powershell", "Windows PowerShell", "Windows PowerShell 5.1")
		self._p("pwsh", "PowerShell 7 (Core)", "Versión moderna y multiplataforma de PowerShell", moderna=True, uia=True)
		self._p("windowsterminal", "Windows Terminal", "Terminal moderna de Windows con pestañas y temas", moderna=True, uia=True, pestanas=True)
		self._p("wsl", "WSL (Linux)", "Subsistema de Windows para Linux", moderna=True, uia=True)
		# Terminales de terceros.
		self._p("cmder", "Cmder", "Emulador de consola portátil para Windows", moderna=True, pestanas=True)
		self._perfiles["conemu64"] = self._p("conemu", "ConEmu", "Emulador de consola avanzado con pestañas", moderna=True, pestanas=True)
		self._p("mintty", "Git Bash (mintty)", "Terminal de Git para Windows basada en mintty")
		self._p("putty", "PuTTY", "Cliente SSH y Telnet para Windows")
		self._p("kitty", "KiTTY", "Fork mejorado de PuTTY")
		self._perfiles["tabby"] = self._p("terminus", "Tabby (Terminus)", "Terminal moderna con autocompletado y temas", moderna=True, uia=True, pestanas=True)
		self._p("hyper", "Hyper", "Terminal basada en Electron con extensiones", moderna=True, uia=True, pestanas=True)
		self._p("alacritty", "Alacritty", "Terminal de alto rendimiento acelerada por GPU", moderna=True)
		self._perfiles["wezterm-gui"] = self._p("wezterm", "WezTerm", "Terminal multiplataforma con GPU", moderna=True, uia=True, pestanas=True)
		self._p("fluent", "Fluent Terminal", "Terminal UWP con diseño Fluent", moderna=True, uia=True, pestanas=True)
		# Aplicaciones dentro de las terminales.
		self._perfiles["nvim"] = self._p("vim", "Vim/Neovim", "Editor de texto modal", silencioso=False)
		self._p("tmux", "tmux", "Multiplexor de terminales", pestanas=True)
		self._p("htop", "htop", "Visor de procesos del sistema", condensar=True)
		self._p("nano", "GNU nano", "Editor de texto sencillo para consola")

	def detectar_aplicacion(self, destino: DestinoConsola) -> str:
		"""Clave del perfil: por el ejecutable y después por el título; ``default`` si no."""
		try:
			nombre_app = (destino.nombreApp or "").lower()
			if nombre_app:
				if nombre_app in self._perfiles:
					return nombre_app
				for clave in self._perfiles:
					if clave in nombre_app:
						return clave
			titulo = (destino.titulo or "").lower()
			if titulo:
				patrones = [
					("vim", "vim"), ("nvim", "vim"),
					("tmux", "tmux"), ("htop", "htop"),
					("nano", "nano"),
					("powershell", "powershell"),
					("windows terminal", "windowsterminal"),
					("cmd.exe", "cmd"),
					("mintty", "mintty"),
					("wsl", "wsl"), ("bash", "wsl"),
					("putty", "putty"),
					("conemu", "conemu"),
					("alacritty", "alacritty"),
					("wezterm", "wezterm"),
					("hyper", "hyper"),
				]
				for patron, perfil in patrones:
					if patron in titulo:
						return perfil
		except Exception:
			pass
		return "default"

	def obtener_perfil(self, nombre_app: str) -> PerfilTerminal | None:
		return self._perfiles.get(nombre_app)

	def establecer_perfil_activo(self, nombre_app: str) -> None:
		self._perfil_activo = self._perfiles.get(nombre_app)

	@property
	def perfil_activo(self) -> PerfilTerminal | None:
		return self._perfil_activo

	def agregar_perfil(self, perfil: PerfilTerminal) -> None:
		self._perfiles[perfil.nombre_app] = perfil

	def listar_perfiles(self) -> list[str]:
		return list(self._perfiles.keys())

	def obtener_info_perfil(self, nombre_app: str) -> str:
		perfil = self._perfiles.get(nombre_app)
		if not perfil:
			return "Perfil no encontrado: {}".format(nombre_app)

		def sino(valor) -> str:
			return "Sí" if valor else "No"

		return "\n".join(
			[
				"Terminal: {}".format(perfil.nombre_mostrar),
				"Descripción: {}".format(perfil.descripcion),
				"Terminal moderna: {}".format(sino(perfil.es_terminal_moderna)),
				"UI Automation: {}".format(sino(perfil.soporta_uia)),
				"Pestañas: {}".format(sino(perfil.soporta_pestanas)),
				"Limpiar ANSI: {}".format(sino(perfil.limpiar_ansi)),
				"Condensar símbolos: {}".format(sino(perfil.condensar_simbolos)),
			]
		)
