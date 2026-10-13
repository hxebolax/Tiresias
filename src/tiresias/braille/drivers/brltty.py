"""BRLTTY: cualquier línea braille que maneje BRLTTY, a través de BrlAPI.

Tiresias habla el protocolo de BrlAPI directamente (sin el módulo ``brlapi``
ni su biblioteca), por una de estas dos vías:

- la tubería con nombre local de BRLTTY (``\\\\.\\pipe\\BrlAPI0``, ``BrlAPI1``...),
  que BRLTTY crea siempre en Windows;
- un socket TCP (``equipo:puerto``; por defecto ``127.0.0.1:4101``), útil si
  BRLTTY está configurado para escuchar en la red o corre en otro equipo.

El servidor se lee de ``conf["brailleDisplays"]["brlapiServer"]``. Como en
BrlAPI, un número de puerto pequeño (menor que 1024) es un número de
servidor (puerto TCP 4101 + número) y una dirección sin equipo (``:0``) es
la tubería local con ese número.

Protocolo (BrlAPI, versión 8 del protocolo): cada paquete lleva una cabecera
de 8 bytes en orden de red (tamaño de los datos, 4 bytes; tipo, 4 bytes con
el código ASCII del paquete) seguida de los datos. Al conectar, el servidor
envía su versión ('v'); el cliente responde con la suya y el servidor dice
qué métodos de autenticación acepta ('a'). Después se piden el nombre del
controlador ('n'), el tamaño de la línea ('s') y el modelo ('d'), y se entra
en modo terminal ('t') para recibir las órdenes de la línea como paquetes
'k' (un código de 64 bits). Las celdas se envían con 'w' y al salir se deja
el modo terminal con 'L'.

Gestos: cada orden de BRLTTY llega ya interpretada (BRLTTY sabe qué tecla de
cada línea hace qué) y se convierte en ``br(brltty):<orden>`` con el nombre
de la orden de BRLTTY en minúsculas (``fwinlt``, ``lnup``, ``route``...). Los
puntos que BRLTTY deja pasar (``PASSDOTS``) llegan como ``dot1``...``dot8`` y
``space`` para escribir en braille, y las teclas del PC que envía BRLTTY
(``PASSKEY``/``PASSCHAR``) se emulan directamente.
"""

from __future__ import annotations

import glob
import ipaddress
import os
import socket
import struct
import threading
from typing import Any

from ... import queue_handler
from ...config import conf
from ...i18n import _
from ...log import getLogger
from . import hwio
from .base import BrailleGesture, DeviceMatch, DisplayNotFound, HardwareDriver, buildGesture

log = getLogger("braille.brltty")

# ===================================================================== conexión
#: Servidor por defecto (TCP) y puerto base de BrlAPI (servidor 0 = 4101).
DEFAULT_SERVER = "127.0.0.1:4101"
BRLAPI_PORT = 4101
#: Las tuberías locales de BRLTTY se llaman «BrlAPI» seguido del número de servidor.
PIPE_DIR = "\\\\.\\pipe\\"
PIPE_PREFIX = "BrlAPI"
#: Versión del protocolo de BrlAPI que se habla (BRLTTY 4 y posteriores).
PROTOCOL_VERSION = 8
#: Tamaño máximo razonable de un paquete (BrlAPI usa 512 bytes como máximo;
#: algo mucho mayor indica un flujo corrupto).
MAX_PACKET_SIZE = 65536
#: Segundos de espera al conectar por TCP y para cada respuesta del servidor.
CONNECT_TIMEOUT = 2.0
REPLY_TIMEOUT = 2.0
#: Segundos para comprobar si el puerto TCP acepta conexiones (detección).
PROBE_TIMEOUT = 0.3

# ============================================================ tipos de paquete
#: Versión del protocolo (uint32).
PKT_VERSION = ord("v")
#: Autenticación: el servidor envía la lista de métodos (uint32 cada uno);
#: el cliente responde con el método elegido (uint32) y, si es una clave, la clave.
PKT_AUTH = ord("a")
#: Nombre del controlador de BRLTTY (cadena terminada en NUL).
PKT_GETDRIVERNAME = ord("n")
#: Identificador del modelo (cadena terminada en NUL).
PKT_GETMODELID = ord("d")
#: Tamaño de la línea: columnas y filas (uint32 cada uno).
PKT_GETDISPLAYSIZE = ord("s")
#: Entrar en modo terminal: número de terminales (uint32), sus números (uint32
#: cada uno), longitud del nombre de controlador (byte) y el nombre. Sin
#: terminales ni nombre de controlador: terminal raíz y órdenes de BRLTTY.
PKT_ENTERTTYMODE = ord("t")
#: Salir del modo terminal (sin datos).
PKT_LEAVETTYMODE = ord("L")
#: Tecla u orden de la línea (uint64: indicadores, tipo, bloque y argumento).
PKT_KEY = ord("k")
#: Escritura en la línea (indicadores uint32 y los campos que indican).
PKT_WRITE = ord("w")
#: Confirmación del servidor.
PKT_ACK = ord("A")
#: Error en respuesta a una petición: código (uint32), tipo del paquete que
#: lo causó (uint32) y una copia del paquete.
PKT_ERROR = ord("e")
#: Excepción (error de un paquete sin respuesta, p. ej. una escritura): mismo formato.
PKT_EXCEPTION = ord("E")

#: Métodos de autenticación.
AUTH_NONE = ord("N")
AUTH_KEY = ord("K")
AUTH_CRED = ord("C")

#: Indicadores de la escritura ('w'): qué campos siguen, en este orden.
WF_DISPLAYNUMBER = 0x01
WF_REGION = 0x02  # inicio (desde 1) y tamaño de la región (uint32 cada uno)
WF_TEXT = 0x04  # tamaño en bytes (uint32) y texto
WF_ATTR_AND = 0x08  # máscara AND (un byte por celda de la región)
WF_ATTR_OR = 0x10  # máscara OR (un byte por celda de la región)
WF_CURSOR = 0x20  # posición del cursor (uint32; 0 = sin cursor)
WF_CHARSET = 0x40  # longitud (byte) y nombre del juego de caracteres del texto
WRITE_FLAGS = WF_REGION | WF_TEXT | WF_ATTR_AND | WF_ATTR_OR | WF_CURSOR | WF_CHARSET
WRITE_CHARSET = b"UTF-8"

#: Códigos de error de BrlAPI (para el registro).
ERROR_NAMES = {
	0x01: "NOMEM",
	0x02: "TTYBUSY",
	0x03: "DEVICEBUSY",
	0x04: "UNKNOWN_INSTRUCTION",
	0x05: "ILLEGAL_INSTRUCTION",
	0x06: "INVALID_PARAMETER",
	0x07: "INVALID_PACKET",
	0x08: "CONNREFUSED",
	0x09: "OPNOTSUPP",
	0x0A: "GAIERR",
	0x0B: "LIBCERR",
	0x0C: "UNKNOWNTTY",
	0x0D: "PROTOCOL_VERSION",
	0x0E: "EOF",
	0x0F: "EMPTYKEY",
	0x10: "DRIVERERROR",
	0x11: "AUTHENTICATION",
	0x12: "READONLY_PARAMETER",
}

# ============================================================ códigos de tecla
# Código de 64 bits de un paquete 'k':
#   bits 32-63: indicadores; bits 29-31: tipo (0 = símbolo de teclado,
#   1 = orden de BRLTTY); en las órdenes, bits 16-28: bloque y bits 0-15:
#   argumento; en los símbolos, bits 0-28: el símbolo (X11 keysym).
KEY_FLAGS_SHIFT = 32
KEY_TYPE_MASK = 0xE0000000
KEY_TYPE_SYM = 0x00000000
KEY_TYPE_CMD = 0x20000000
KEY_CODE_MASK = 0x1FFFFFFF
KEY_CMD_BLK_MASK = 0x1FFF0000
KEY_CMD_BLK_SHIFT = 16
KEY_CMD_ARG_MASK = 0x0000FFFF

#: Indicadores de entrada (ya desplazados 32 bits): modificadores de la tecla.
KEY_FLG_SHIFT = 0x0100
KEY_FLG_UPPER = 0x0200
KEY_FLG_CONTROL = 0x0400
KEY_FLG_META = 0x0800
KEY_FLG_ALTGR = 0x1000
KEY_FLG_GUI = 0x2000

#: Argumento de PASSDOTS: bits 0-7 = puntos 1-8; 0x100 = con la barra espaciadora.
DOTS_SPACE = 0x0100

#: Símbolos de teclado (X11 keysyms) -> nombre de tecla de Tiresias.
SYM_UNICODE = 0x01000000
SYM_KEYS = {
	0xFF08: "backspace",
	0xFF09: "tab",
	0xFF0D: "enter",
	0xFF1B: "escape",
	0xFF50: "home",
	0xFF51: "leftArrow",
	0xFF52: "upArrow",
	0xFF53: "rightArrow",
	0xFF54: "downArrow",
	0xFF55: "pageUp",
	0xFF56: "pageDown",
	0xFF57: "end",
	0xFF63: "insert",
	0xFFFF: "delete",
}
# F1 (0xFFBE) a F24.
for _i in range(24):
	SYM_KEYS[0xFFBE + _i] = f"f{_i + 1}"

#: Órdenes simples de BRLTTY (bloque 0): argumento -> nombre del gesto.
COMMANDS = {
	0x00: "noop",
	0x01: "lnup",
	0x02: "lndn",
	0x03: "winup",
	0x04: "windn",
	0x05: "prdifln",
	0x06: "nxdifln",
	0x07: "attrup",
	0x08: "attrdn",
	0x09: "top",
	0x0A: "bot",
	0x0B: "top_left",
	0x0C: "bot_left",
	0x0D: "prpgrph",
	0x0E: "nxpgrph",
	0x0F: "prprompt",
	0x10: "nxprompt",
	0x11: "prsearch",
	0x12: "nxsearch",
	0x13: "chrlt",
	0x14: "chrrt",
	0x15: "hwinlt",
	0x16: "hwinrt",
	0x17: "fwinlt",
	0x18: "fwinrt",
	0x19: "fwinltskip",
	0x1A: "fwinrtskip",
	0x1B: "lnbeg",
	0x1C: "lnend",
	0x1D: "home",
	0x1E: "back",
	0x1F: "return",
	0x20: "freeze",
	0x21: "dispmd",
	0x22: "sixdots",
	0x23: "slidewin",
	0x24: "skpidlns",
	0x25: "skpblnkwins",
	0x26: "csrvis",
	0x27: "csrhide",
	0x28: "csrtrk",
	0x29: "csrsize",
	0x2A: "csrblink",
	0x2B: "attrvis",
	0x2C: "attrblink",
	0x2D: "capblink",
	0x2E: "tunes",
	0x2F: "autorepeat",
	0x30: "autospeak",
	0x31: "help",
	0x32: "info",
	0x33: "learn",
	0x34: "prefmenu",
	0x35: "prefsave",
	0x36: "prefload",
	0x37: "menu_first_item",
	0x38: "menu_last_item",
	0x39: "menu_prev_item",
	0x3A: "menu_next_item",
	0x3B: "menu_prev_setting",
	0x3C: "menu_next_setting",
	0x3D: "mute",
	0x3E: "spkhome",
	0x3F: "say_line",
	0x40: "say_above",
	0x41: "say_below",
	0x42: "say_slower",
	0x43: "say_faster",
	0x44: "say_softer",
	0x45: "say_louder",
	0x46: "switchvt_prev",
	0x47: "switchvt_next",
	0x48: "csrjmp_vert",
	0x49: "paste",
	0x4A: "restartbrl",
	0x4B: "restartspeech",
	0x4C: "offline",
	0x4D: "shift",
	0x4E: "upper",
	0x4F: "control",
	0x50: "meta",
	0x51: "time",
	0x52: "menu_prev_level",
	0x53: "aspk_sel_line",
	0x54: "aspk_sel_char",
	0x55: "aspk_ins_chars",
	0x56: "aspk_del_chars",
	0x57: "aspk_rep_chars",
	0x58: "aspk_cmp_words",
	0x59: "speak_curr_char",
	0x5A: "speak_prev_char",
	0x5B: "speak_next_char",
	0x5C: "speak_curr_word",
	0x5D: "speak_prev_word",
	0x5E: "speak_next_word",
	0x5F: "speak_curr_line",
	0x60: "speak_prev_line",
	0x61: "speak_next_line",
	0x62: "speak_frst_char",
	0x63: "speak_last_char",
	0x64: "speak_frst_line",
	0x65: "speak_last_line",
	0x66: "desc_curr_char",
	0x67: "spell_curr_word",
	0x68: "route_curr_locn",
	0x69: "speak_curr_locn",
	0x6A: "show_curr_locn",
	0x6B: "clip_save",
	0x6C: "clip_restore",
	0x6D: "brlucdots",
	0x6E: "brlkbd",
	0x6F: "unstick",
	0x70: "altgr",
	0x71: "gui",
	0x72: "brl_stop",
	0x73: "brl_start",
	0x74: "spk_stop",
	0x75: "spk_start",
	0x76: "scr_stop",
	0x77: "scr_start",
	0x78: "selectvt_prev",
	0x79: "selectvt_next",
	0x7A: "prnbwin",
	0x7B: "nxnbwin",
	0x7C: "touch_nav",
	0x7D: "speak_indent",
	0x7E: "aspk_indent",
	0x7F: "refresh",
	0x80: "indicators",
	0x81: "txtsel_clear",
	0x82: "txtsel_all",
	0x83: "host_copy",
	0x84: "host_cut",
	0x85: "host_paste",
	0x86: "gui_title",
	0x87: "gui_brl_actions",
	0x88: "gui_home",
	0x89: "gui_back",
	0x8A: "gui_dev_settings",
	0x8B: "gui_dev_options",
	0x8C: "gui_app_list",
	0x8D: "gui_app_menu",
	0x8E: "gui_app_alerts",
	0x8F: "gui_area_actv",
	0x90: "gui_area_prev",
	0x91: "gui_area_next",
	0x92: "gui_item_frst",
	0x93: "gui_item_prev",
	0x94: "gui_item_next",
	0x95: "gui_item_last",
	0x96: "say_lower",
	0x97: "say_higher",
	0x98: "say_all",
	0x99: "contracted",
	0x9A: "compbrl6",
	0x9B: "prefreset",
	0x9C: "aspk_emp_line",
	0x9D: "spk_punct_level",
	0x9E: "paste_altmode",
}

#: Órdenes con argumento (bloque) -> nombre del gesto.
BLK_ROUTE = 0x01
BLK_PASSDOTS = 0x22
BLOCK_COMMANDS = {
	0x01: "route",
	0x02: "clip_new",
	0x03: "clip_add",
	0x04: "copy_rect",
	0x05: "copy_line",
	0x06: "switchvt",
	0x07: "prindent",
	0x08: "nxindent",
	0x09: "descchar",
	0x0A: "setleft",
	0x0B: "setmark",
	0x0C: "gotomark",
	0x0D: "gotoline",
	0x0E: "prdifchar",
	0x0F: "nxdifchar",
	0x10: "clip_copy",
	0x11: "clip_append",
	0x12: "paste_history",
	0x13: "set_text_table",
	0x14: "set_attributes_table",
	0x15: "set_contraction_table",
	0x16: "set_keyboard_table",
	0x17: "set_language_profile",
	0x18: "route_line",
	0x19: "refresh_line",
	0x1A: "txtsel_start",
	0x1B: "txtsel_set",
	0x1C: "route_speech",
	0x1D: "paste_history_altmode",
	0x1E: "selectvt",
	0x1F: "alert",
	0x22: "passdots",
	0x23: "passat",
	0x24: "passxt",
	0x25: "passps2",
	0x26: "context",
	0x27: "touch_at",
	0x28: "macro",
	0x29: "hostcmd",
}

#: Bloques cuyo argumento es una celda de la línea (el gesto lleva el índice
#: de la celda, como los botones de enrutamiento).
CELL_BLOCKS = frozenset({0x01, 0x02, 0x03, 0x04, 0x05, 0x07, 0x08, 0x09, 0x0A, 0x0E, 0x0F, 0x10, 0x11, 0x18, 0x1A, 0x1B, 0x1C, 0x27})
#: Órdenes que no producen gesto (sin efecto o códigos de teclado en bruto).
IGNORED_COMMANDS = frozenset({"noop", "passat", "passxt", "passps2", "alert"})

#: Modificadores de las teclas emuladas: indicador -> (nombre del gesto, tecla emulada).
_MODIFIER_FLAGS = (
	(KEY_FLG_CONTROL, "key_control", "control"),
	(KEY_FLG_META, "key_alt", "alt"),
	(KEY_FLG_ALTGR, "key_altgr", "control+alt"),
	(KEY_FLG_SHIFT, "key_shift", "shift"),
	(KEY_FLG_GUI, "key_windows", "windows"),
)


def commandName(block: int, argument: int) -> str:
	"""Nombre del gesto de una orden de BRLTTY (genérico si no se conoce)."""
	if block == 0:
		return COMMANDS.get(argument, f"cmd{argument}")
	return BLOCK_COMMANDS.get(block, f"blk{block}")


def splitKeyCode(code: int) -> tuple[int, int, int, int]:
	"""(tipo, bloque, argumento, indicadores) de un código de tecla de 64 bits."""
	flags = (code >> KEY_FLAGS_SHIFT) & 0xFFFFFFFF
	low = code & 0xFFFFFFFF
	ktype = low & KEY_TYPE_MASK
	if ktype == KEY_TYPE_CMD:
		return ktype, (low & KEY_CMD_BLK_MASK) >> KEY_CMD_BLK_SHIFT, low & KEY_CMD_ARG_MASK, flags
	return ktype, 0, low & KEY_CODE_MASK, flags


# ===================================================================== paquetes
def buildPacket(ptype: int, payload: bytes = b"") -> bytes:
	"""Paquete de BrlAPI: tamaño y tipo (uint32 en orden de red) y los datos."""
	return struct.pack(">II", len(payload), ptype) + bytes(payload)


def enterTtyModePayload() -> bytes:
	"""Datos de 't': ninguna terminal concreta (la raíz) y nombre de controlador
	vacío (se reciben órdenes de BRLTTY, no códigos de tecla del controlador)."""
	return struct.pack(">I", 0) + b"\x00"


def writePayload(cells: list[int]) -> bytes:
	"""Datos de 'w' para mostrar ``cells`` en toda la línea.

	El texto son los mismos puntos como caracteres Unicode braille; la
	máscara AND a cero hace que solo cuenten los puntos de la máscara OR.
	"""
	n = len(cells)
	dots = bytes(c & 0xFF for c in cells)
	text = "".join(chr(0x2800 + c) for c in dots).encode("utf-8")
	return (
		struct.pack(">IIII", WRITE_FLAGS, 1, n, len(text))
		+ text
		+ bytes(n)
		+ dots
		+ struct.pack(">I", 0)
		+ bytes((len(WRITE_CHARSET),))
		+ WRITE_CHARSET
	)


def _cString(data: bytes) -> str:
	return data.split(b"\x00", 1)[0].decode("utf-8", "replace").strip()


class BrlapiError(DisplayNotFound):
	"""El servidor BrlAPI ha respondido con un error."""

	def __init__(self, code: int, message: str = "") -> None:
		self.code = code
		name = ERROR_NAMES.get(code, str(code))
		super().__init__(f"BrlAPI: error {name}" + (f" ({message})" if message else ""))


# ===================================================================== servidor
def configuredServer() -> str:
	"""Servidor BrlAPI de la configuración (``equipo:puerto``)."""
	try:
		value = conf["brailleDisplays"]["brlapiServer"]
	except (KeyError, TypeError):
		value = ""
	return str(value or "").strip() or DEFAULT_SERVER


def parseServer(text: str) -> tuple[str, str, int]:
	"""Interpreta la dirección del servidor.

	Devuelve ``("pipe", ruta, 0)`` para una tubería local o ``("tcp", equipo,
	puerto)``. Acepta ``equipo:puerto``, ``equipo`` (puerto 4101),
	``[ipv6]:puerto``, ``:n`` (tubería local número n) y rutas de tubería.
	Un puerto menor que 1024 es un número de servidor de BrlAPI (4101 + n).
	"""
	text = (text or "").strip() or DEFAULT_SERVER
	low = text.lower()
	if low.startswith(("\\\\.\\pipe\\", "//./pipe/")):
		return "pipe", PIPE_DIR + text[9:], 0
	host, port = text, ""
	if text.startswith("["):
		end = text.find("]")
		if end > 0:
			host, rest = text[1:end], text[end + 1 :]
			port = rest[1:] if rest.startswith(":") else ""
	elif text.count(":") == 1:
		host, port = text.split(":")
	host = host.strip()
	port = port.strip()
	if port and not port.isdigit():
		raise ValueError(f"Puerto de BrlAPI no válido: {text!r}")
	number = int(port) if port else None
	if not host:
		return "pipe", f"{PIPE_DIR}{PIPE_PREFIX}{number or 0}", 0
	if number is None:
		return "tcp", host, BRLAPI_PORT
	if number < 1024:
		return "tcp", host, BRLAPI_PORT + number
	return "tcp", host, number


def formatAddress(host: str, port: int) -> str:
	return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def _isLoopback(host: str) -> bool:
	if host.lower() == "localhost":
		return True
	try:
		return ipaddress.ip_address(host).is_loopback
	except ValueError:
		return False


def _listPipes() -> list[str]:
	"""Tuberías locales de BrlAPI abiertas (una por cada BRLTTY en marcha)."""
	try:
		names = [e.name for e in os.scandir("//./pipe/") if e.name.startswith(PIPE_PREFIX)]
	except OSError:
		return []

	def order(name: str) -> tuple[int, str]:
		num = name[len(PIPE_PREFIX) :]
		return (int(num) if num.isdigit() else 1 << 30, name)

	return [PIPE_DIR + n for n in sorted(names, key=order)]


def _brlttyExecutables() -> list[str] | None:
	"""Rutas de los ``brltty.exe`` en marcha ("" si no se puede leer la ruta);
	``None`` si no se puede saber (sin psutil)."""
	try:
		import psutil
	except ImportError:
		return None
	found: list[str] = []
	try:
		for proc in psutil.process_iter(["name"]):
			name = (proc.info.get("name") or "").lower()
			if not name.startswith("brltty"):
				continue
			try:
				found.append(proc.exe() or "")
			except Exception:
				found.append("")
	except Exception:
		log.debug("No se pudo enumerar los procesos", exc_info=True)
		return None
	return found


def _brlttyRunning() -> bool | None:
	exes = _brlttyExecutables()
	return None if exes is None else bool(exes)


def _portOpen(host: str, port: int, timeout: float = PROBE_TIMEOUT) -> bool:
	"""¿Acepta conexiones el puerto? (rápido: para la detección automática)."""
	try:
		with socket.create_connection((host, port), timeout):
			return True
	except OSError:
		return False


def _serverMatches(checkRunning: bool) -> list[DeviceMatch]:
	"""Conexiones posibles con BRLTTY.

	Con ``checkRunning`` (detección automática, #9098) el servidor TCP solo se
	incluye si BRLTTY parece estar en marcha.
	"""
	pipes = _listPipes()
	try:
		kind, host, port = parseServer(configuredServer())
	except ValueError as e:
		log.warning("%s", e)
		kind, host, port = parseServer(DEFAULT_SERVER)
	if kind == "pipe":
		# Servidor local concreto: solo esa tubería (si existe o si se ha elegido a mano).
		if host in pipes or not checkRunning:
			return [DeviceMatch("socket", "brltty", host)]
		return []
	pipeMatches = [DeviceMatch("socket", "brltty", p) for p in pipes]
	tcp = DeviceMatch("socket", "brltty", formatAddress(host, port))
	if _isLoopback(host):
		# Con la tubería local basta: es el mismo BRLTTY.
		if pipeMatches:
			return pipeMatches
		if checkRunning:
			running = _brlttyRunning()
			if not (running if running is not None else _portOpen(host, port)):
				return []
		return [tcp]
	if checkRunning and not _portOpen(host, port):
		return pipeMatches
	return [tcp] + pipeMatches


# ======================================================================= claves
def _keyFileCandidates() -> list[str]:
	"""Rutas típicas del archivo de clave de BrlAPI (``brlapi.key``) en Windows."""
	paths: list[str] = []
	auth = os.environ.get("BRLAPI_AUTH", "")
	if auth:
		paths.append(auth.split(":", 1)[1] if auth.lower().startswith("keyfile:") else auth)
	exes = _brlttyExecutables() or []
	for exe in exes:
		if not exe:
			continue
		folder = os.path.dirname(exe)
		paths += [
			os.path.join(folder, "brlapi.key"),
			os.path.join(folder, "etc", "brlapi.key"),
			os.path.join(os.path.dirname(folder), "etc", "brlapi.key"),
		]
	for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "SystemDrive"):
		base = os.environ.get(var)
		if not base:
			continue
		if var == "SystemDrive":
			base += "\\"
		for pattern in ("brltty*\\etc\\brlapi.key", "brltty*\\brlapi.key"):
			paths += sorted(glob.glob(os.path.join(base, pattern)))
	out: list[str] = []
	for p in paths:
		if p and p not in out:
			out.append(p)
	return out


def readAuthKey() -> bytes | None:
	"""Contenido del primer ``brlapi.key`` que exista (o ``None``)."""
	for path in _keyFileCandidates():
		try:
			if os.path.isfile(path):
				with open(path, "rb") as f:
					data = f.read(500)
				if data:
					return data
		except OSError:
			continue
	return None


# ==================================================================== conexiones
class SocketTransport(hwio.Transport):
	"""Conexión TCP con el servidor BrlAPI, con hilo de lectura propio."""

	kind = "socket"

	def __init__(self, host: str, port: int, onReceive, onError=None, timeout: float = CONNECT_TIMEOUT, info: dict | None = None) -> None:
		self.port = formatAddress(host, port)
		self.info = info or {}
		self._onReceive = onReceive
		self._onError = onError
		self._closed = False
		self._errorReported = False
		self._writeLock = threading.Lock()
		try:
			self._sock = socket.create_connection((host, port), timeout)
		except OSError as e:
			raise hwio.IoError(e.errno or 0, f"No se pudo conectar con {self.port}: {e}") from e
		self._sock.settimeout(None)
		try:
			self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
		except OSError:
			pass
		self._thread = threading.Thread(target=self._readLoop, name="braille-brlapi", daemon=True)
		self._thread.start()

	def _readLoop(self) -> None:
		while not self._closed:
			try:
				data = self._sock.recv(4096)
			except OSError as e:
				self._reportError(e.errno or 0)
				return
			if not data:
				# El servidor ha cerrado la conexión.
				self._reportError(0)
				return
			if self._closed:
				return
			try:
				self._onReceive(data)
			except Exception:
				log.exception("Error procesando datos de BrlAPI")

	def _reportError(self, code: int) -> None:
		if self._closed or self._errorReported:
			return
		self._errorReported = True
		log.info("Se ha cerrado la conexión con BrlAPI (%s), código %s", self.port, code)
		if self._onError is not None:
			try:
				self._onError(code)
			except Exception:
				log.exception("Error avisando de la desconexión")

	def write(self, data: bytes) -> None:
		if self._closed:
			raise hwio.IoError(0, "Conexión cerrada")
		try:
			with self._writeLock:
				self._sock.sendall(bytes(data))
		except OSError as e:
			# El aviso, fuera del cerrojo de escritura (puede cerrar la conexión).
			self._reportError(e.errno or 0)
			raise hwio.IoError(e.errno or 0, f"Error escribiendo en BrlAPI: {e}") from e

	def close(self) -> None:
		if self._closed:
			return
		self._closed = True
		try:
			self._sock.shutdown(socket.SHUT_RDWR)
		except OSError:
			pass
		try:
			self._sock.close()
		except OSError:
			pass
		if self._thread.is_alive() and self._thread is not threading.current_thread():
			self._thread.join(2)


class PipeTransport(hwio._OverlappedIo):
	"""Tubería con nombre local de BRLTTY (``\\\\.\\pipe\\BrlAPIn``)."""

	kind = "socket"

	def __init__(self, path: str, onReceive, onError=None, info: dict | None = None) -> None:
		self.port = path
		self.info = info or {}
		handle = hwio._openFile(path, hwio.GENERIC_READ | hwio.GENERIC_WRITE, 0)
		super().__init__(handle, None, 4096, onReceive, onError, "brlapi")
		self.start()


# ================================================================== controlador
class BrlttyDriver(HardwareDriver):
	name = "brltty"
	description = _("BRLTTY (cualquier línea que maneje BRLTTY)")
	supportsSerialPorts = False
	keyOrder = [
		"key_control",
		"key_alt",
		"key_altgr",
		"key_shift",
		"key_windows",
		"space",
		"dot1",
		"dot2",
		"dot3",
		"dot4",
		"dot5",
		"dot6",
		"dot7",
		"dot8",
	]
	dotKeys = {f"dot{i}": i for i in range(1, 9)}
	spaceKeys = frozenset({"space"})
	# #6483: todas las órdenes de BRLTTY llegan como gestos; este mapa asocia
	# las útiles a órdenes de Tiresias (el resto se puede asignar a mano).
	gestureMap = {
		# Desplazamiento de la línea y cambio de línea.
		"fwinlt": "braille_scrollBack",
		"fwinrt": "braille_scrollForward",
		"fwinltskip": "braille_scrollBack",
		"fwinrtskip": "braille_scrollForward",
		"hwinlt": "braille_scrollBack",
		"hwinrt": "braille_scrollForward",
		"lnup": "braille_previousLine",
		"lndn": "braille_nextLine",
		"prdifln": "braille_previousLine",
		"nxdifln": "braille_nextLine",
		"winup": "review_previousPage",
		"windn": "review_nextPage",
		"prpgrph": "kb:control+upArrow",
		"nxpgrph": "kb:control+downArrow",
		# Cursor de revisión.
		"top": "review_top",
		"bot": "review_bottom",
		"top_left": "review_top",
		"bot_left": "review_bottom",
		"lnbeg": "review_startOfLine",
		"lnend": "review_endOfLine",
		"chrlt": "review_previousCharacter",
		"chrrt": "review_nextCharacter",
		"home": "braille_toFocus",
		"back": "braille_toFocus",
		"return": "braille_toFocus",
		"route_curr_locn": "navigatorObject_moveFocus",
		# Enrutamiento.
		"route": "braille_routeTo",
		"descchar": "braille_reportFormatting",
		# Opciones de la línea.
		"csrtrk": "braille_toggleTether",
		"csrvis": "braille_toggleShowCursor",
		"csrsize": "braille_cycleCursorShape",
		# Información, menús y configuración.
		"learn": "toggleInputHelp",
		"help": "toggleInputHelp",
		"prefmenu": "showGui",
		"prefsave": "saveConfiguration",
		"prefload": "revertConfiguration",
		"time": "dateTime",
		"info": "reportStatusLine",
		"speak_curr_locn": "reportCurrentFocus",
		# Lectura con voz.
		"say_line": "review_currentLine",
		"say_below": "review_sayAll",
		"say_all": "sayAll",
		"speak_curr_char": "review_currentCharacter",
		"speak_prev_char": "review_previousCharacter",
		"speak_next_char": "review_nextCharacter",
		"speak_curr_word": "review_currentWord",
		"speak_prev_word": "review_previousWord",
		"speak_next_word": "review_nextWord",
		"speak_curr_line": "review_currentLine",
		"speak_prev_line": "review_previousLine",
		"speak_next_line": "review_nextLine",
		"speak_frst_char": "review_startOfLine",
		"speak_last_char": "review_endOfLine",
		"speak_frst_line": "review_top",
		"speak_last_line": "review_bottom",
		# Portapapeles y selección.
		"txtsel_all": "kb:control+a",
		"host_copy": "kb:control+c",
		"host_cut": "kb:control+x",
		"host_paste": "kb:control+v",
		"paste": "kb:control+v",
		# Órdenes de interfaz gráfica de BRLTTY.
		"gui_title": "title",
		"gui_brl_actions": "showGui",
		"gui_home": "kb:windows+d",
		"gui_back": "kb:escape",
		"gui_dev_settings": "kb:windows+i",
		"gui_app_list": "kb:alt+tab",
		"gui_app_menu": "kb:applications",
		"gui_app_alerts": "kb:windows+n",
		"gui_area_prev": "kb:shift+f6",
		"gui_area_next": "kb:f6",
		"gui_item_frst": "kb:control+home",
		"gui_item_prev": "kb:shift+tab",
		"gui_item_next": "kb:tab",
		"gui_item_last": "kb:control+end",
		# Barra espaciadora y puntos que BRLTTY deja pasar.
		"space+dot1": "kb:upArrow",
		"space+dot4": "kb:downArrow",
		"space+dot3": "kb:leftArrow",
		"space+dot6": "kb:rightArrow",
		"space+dot2": "kb:control+leftArrow",
		"space+dot5": "kb:control+rightArrow",
		"space+dot1+dot2": "kb:home",
		"space+dot4+dot5": "kb:end",
		"space+dot1+dot2+dot3": "kb:control+home",
		"space+dot4+dot5+dot6": "kb:control+end",
		"space+dot1+dot3": "kb:shift+tab",
		"space+dot4+dot6": "kb:tab",
		"space+dot1+dot5": "kb:escape",
		"space+dot1+dot3+dot4": "kb:alt",
		"space+dot3+dot4": "kb:windows",
		"space+dot1+dot4+dot5": "kb:windows+d",
		"space+dot2+dot3+dot4+dot5": "kb:alt+tab",
		"space+dot1+dot4": "reportCurrentLine",
		"space+dot1+dot3+dot4+dot5": "showGui",
		"space+dot1+dot2+dot3+dot4+dot5+dot6": "sayAll",
		"space+dot7": "kb:backspace",
		"space+dot8": "kb:enter",
	}
	keyDescriptions = {
		"dot1": _("punto 1 del teclado braille"),
		"dot2": _("punto 2 del teclado braille"),
		"dot3": _("punto 3 del teclado braille"),
		"dot4": _("punto 4 del teclado braille"),
		"dot5": _("punto 5 del teclado braille"),
		"dot6": _("punto 6 del teclado braille"),
		"dot7": _("punto 7 del teclado braille"),
		"dot8": _("punto 8 del teclado braille"),
		"space": _("barra espaciadora del teclado braille"),
		"key_control": _("con control (tecla que envía BRLTTY)"),
		"key_alt": _("con alt (tecla que envía BRLTTY)"),
		"key_altgr": _("con alt gr (tecla que envía BRLTTY)"),
		"key_shift": _("con mayúsculas (tecla que envía BRLTTY)"),
		"key_windows": _("con windows (tecla que envía BRLTTY)"),
		"fwinlt": _("orden de BRLTTY: desplazar la línea a la izquierda"),
		"fwinrt": _("orden de BRLTTY: desplazar la línea a la derecha"),
		"fwinltskip": _("orden de BRLTTY: desplazar a la izquierda saltando ventanas vacías"),
		"fwinrtskip": _("orden de BRLTTY: desplazar a la derecha saltando ventanas vacías"),
		"hwinlt": _("orden de BRLTTY: media ventana a la izquierda"),
		"hwinrt": _("orden de BRLTTY: media ventana a la derecha"),
		"lnup": _("orden de BRLTTY: línea anterior"),
		"lndn": _("orden de BRLTTY: línea siguiente"),
		"prdifln": _("orden de BRLTTY: línea anterior distinta"),
		"nxdifln": _("orden de BRLTTY: línea siguiente distinta"),
		"winup": _("orden de BRLTTY: varias líneas arriba"),
		"windn": _("orden de BRLTTY: varias líneas abajo"),
		"prpgrph": _("orden de BRLTTY: párrafo anterior"),
		"nxpgrph": _("orden de BRLTTY: párrafo siguiente"),
		"top": _("orden de BRLTTY: primera línea"),
		"bot": _("orden de BRLTTY: última línea"),
		"top_left": _("orden de BRLTTY: principio de la primera línea"),
		"bot_left": _("orden de BRLTTY: principio de la última línea"),
		"lnbeg": _("orden de BRLTTY: principio de la línea"),
		"lnend": _("orden de BRLTTY: final de la línea"),
		"chrlt": _("orden de BRLTTY: un carácter a la izquierda"),
		"chrrt": _("orden de BRLTTY: un carácter a la derecha"),
		"home": _("orden de BRLTTY: ir a la posición del cursor"),
		"back": _("orden de BRLTTY: volver tras seguir el cursor"),
		"return": _("orden de BRLTTY: volver o ir al cursor"),
		"route_curr_locn": _("orden de BRLTTY: llevar el cursor a la posición actual"),
		"route": _("orden de BRLTTY: enrutar el cursor a una celda"),
		"descchar": _("orden de BRLTTY: describir el carácter de una celda"),
		"csrtrk": _("orden de BRLTTY: activar o desactivar el seguimiento del cursor"),
		"csrvis": _("orden de BRLTTY: mostrar u ocultar el cursor"),
		"csrsize": _("orden de BRLTTY: forma del cursor"),
		"learn": _("orden de BRLTTY: modo de aprendizaje de teclas"),
		"help": _("orden de BRLTTY: ayuda"),
		"prefmenu": _("orden de BRLTTY: menú de preferencias"),
		"prefsave": _("orden de BRLTTY: guardar las preferencias"),
		"prefload": _("orden de BRLTTY: recuperar las preferencias"),
		"time": _("orden de BRLTTY: fecha y hora"),
		"info": _("orden de BRLTTY: línea de estado"),
		"speak_curr_locn": _("orden de BRLTTY: decir la posición actual"),
		"say_line": _("orden de BRLTTY: leer la línea"),
		"say_below": _("orden de BRLTTY: leer desde aquí hasta el final"),
		"say_all": _("orden de BRLTTY: leer todo"),
		"speak_curr_char": _("orden de BRLTTY: decir el carácter actual"),
		"speak_prev_char": _("orden de BRLTTY: decir el carácter anterior"),
		"speak_next_char": _("orden de BRLTTY: decir el carácter siguiente"),
		"speak_curr_word": _("orden de BRLTTY: decir la palabra actual"),
		"speak_prev_word": _("orden de BRLTTY: decir la palabra anterior"),
		"speak_next_word": _("orden de BRLTTY: decir la palabra siguiente"),
		"speak_curr_line": _("orden de BRLTTY: decir la línea actual"),
		"speak_prev_line": _("orden de BRLTTY: decir la línea anterior"),
		"speak_next_line": _("orden de BRLTTY: decir la línea siguiente"),
		"speak_frst_char": _("orden de BRLTTY: decir el primer carácter de la línea"),
		"speak_last_char": _("orden de BRLTTY: decir el último carácter de la línea"),
		"speak_frst_line": _("orden de BRLTTY: decir la primera línea"),
		"speak_last_line": _("orden de BRLTTY: decir la última línea"),
		"txtsel_all": _("orden de BRLTTY: seleccionar todo"),
		"host_copy": _("orden de BRLTTY: copiar"),
		"host_cut": _("orden de BRLTTY: cortar"),
		"host_paste": _("orden de BRLTTY: pegar"),
		"paste": _("orden de BRLTTY: pegar"),
		"gui_title": _("orden de BRLTTY: título"),
		"gui_brl_actions": _("orden de BRLTTY: acciones braille"),
		"gui_home": _("orden de BRLTTY: inicio"),
		"gui_back": _("orden de BRLTTY: atrás"),
		"gui_dev_settings": _("orden de BRLTTY: configuración del dispositivo"),
		"gui_app_list": _("orden de BRLTTY: lista de aplicaciones"),
		"gui_app_menu": _("orden de BRLTTY: menú de la aplicación"),
		"gui_app_alerts": _("orden de BRLTTY: notificaciones"),
		"gui_area_prev": _("orden de BRLTTY: área anterior"),
		"gui_area_next": _("orden de BRLTTY: área siguiente"),
		"gui_item_frst": _("orden de BRLTTY: primer elemento"),
		"gui_item_prev": _("orden de BRLTTY: elemento anterior"),
		"gui_item_next": _("orden de BRLTTY: elemento siguiente"),
		"gui_item_last": _("orden de BRLTTY: último elemento"),
	}

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		self._buffer = bytearray()
		self._replies: list[tuple[int, bytes]] = []
		self._connecting = False
		self._ttyMode = False
		self.driverName = ""
		self.modelId = ""
		self.numRows = 1
		#: Caracteres escritos (solo en las pruebas, cuando ``lastGestures`` no es ``None``).
		self.typedText: list[str] = []
		super().__init__(*args, **kwargs)

	# ------------------------------------------------------------ puertos
	@classmethod
	def getMatches(cls, devices: list | None = None, usb: bool = True, bluetooth: bool = True, allowGeneric: bool = True) -> list[DeviceMatch]:
		"""BRLTTY no es un dispositivo: se busca su servidor si parece en marcha (#9098)."""
		try:
			return _serverMatches(checkRunning=True)
		except Exception:
			log.debug("Error buscando BRLTTY", exc_info=True)
			return []

	@classmethod
	def candidateMatches(cls, port: str) -> list[DeviceMatch]:
		return _serverMatches(checkRunning=False)

	@classmethod
	def getPortChoices(cls) -> list[tuple[str, str]]:
		return [("auto", _("Automático"))]

	def _open(self, match: DeviceMatch, baudrate: int | None = None, **kwargs: Any) -> hwio.Transport:
		if match.type != "socket":
			raise DisplayNotFound(f"Tipo de conexión no admitido por BRLTTY: {match.type}")
		kind, host, port = parseServer(match.port)
		if kind == "pipe":
			return PipeTransport(host, self._onReceive, self._onIoError)
		return SocketTransport(host, port, self._onReceive, self._onIoError)

	# ------------------------------------------------------------ conexión
	def _connect(self, match: DeviceMatch) -> None:
		self._resetState()
		self.numCells = 0
		self._connecting = True
		try:
			try:
				self._io = self._open(match)
			except hwio.IoError as e:
				raise DisplayNotFound(str(e)) from e
			self._handshake()
			self._ttyMode = True
		finally:
			self._connecting = False

	def _handshake(self) -> None:
		# Versión: el servidor envía la suya al aceptar la conexión y espera la nuestra.
		self._sendPacket(PKT_VERSION, struct.pack(">I", PROTOCOL_VERSION))
		payload = self._expect(PKT_VERSION)
		version = struct.unpack(">I", payload[:4])[0] if len(payload) >= 4 else -1
		if version != PROTOCOL_VERSION:
			raise DisplayNotFound(f"BrlAPI: versión del protocolo {version} no admitida (se usa la {PROTOCOL_VERSION})")
		self._authenticate(self._expect(PKT_AUTH))
		self.driverName = _cString(self._request(PKT_GETDRIVERNAME, expect=PKT_GETDRIVERNAME))
		size = self._request(PKT_GETDISPLAYSIZE, expect=PKT_GETDISPLAYSIZE)
		if len(size) < 8:
			raise DisplayNotFound("BrlAPI: tamaño de la línea no válido")
		columns, rows = struct.unpack(">II", size[:8])
		try:
			self.modelId = _cString(self._request(PKT_GETMODELID, expect=PKT_GETMODELID))
		except BrlapiError as e:
			# Servidores antiguos no conocen esta petición.
			log.debug("BRLTTY no da el modelo: %s", e)
			self.modelId = ""
		cells = columns * max(1, rows)
		if cells <= 0:
			raise DisplayNotFound(f"BRLTTY ({self.driverName}) no tiene ninguna línea braille conectada")
		self._request(PKT_ENTERTTYMODE, enterTtyModePayload(), expect=PKT_ACK)
		self.numRows = max(1, rows)
		self.model = "".join(ch for ch in self.driverName if ch.isalnum())
		details = " ".join(p for p in (self.driverName, self.modelId) if p)
		self.deviceName = _("BRLTTY: {details}").format(details=details) if details else "BRLTTY"
		log.debug("BRLTTY: controlador %r, modelo %r, %dx%d celdas", self.driverName, self.modelId, columns, rows)
		self.numCells = cells

	def _authenticate(self, payload: bytes) -> None:
		methods = [struct.unpack(">I", payload[i : i + 4])[0] for i in range(0, len(payload) - len(payload) % 4, 4)]
		if not methods or AUTH_NONE in methods:
			return
		errors: list[str] = []
		for method in methods:
			if method == AUTH_KEY:
				key = readAuthKey()
				if key is None:
					errors.append("sin archivo brlapi.key")
					continue
				data = struct.pack(">I", AUTH_KEY) + key
			elif method == AUTH_CRED:
				data = struct.pack(">I", AUTH_CRED)
			else:
				continue
			try:
				self._request(PKT_AUTH, data, expect=PKT_ACK)
				return
			except BrlapiError as e:
				errors.append(str(e))
		raise DisplayNotFound("BrlAPI: no se ha podido autenticar (" + "; ".join(errors or ["método no admitido"]) + ")")

	def _sendPacket(self, ptype: int, payload: bytes = b"") -> None:
		self._write(buildPacket(ptype, payload))

	def _request(self, ptype: int, payload: bytes = b"", expect: int = PKT_ACK) -> bytes:
		self._sendPacket(ptype, payload)
		return self._expect(expect)

	def _expect(self, ptype: int) -> bytes:
		"""Espera (en el hilo que conecta) una respuesta del tipo ``ptype`` o un error."""

		def ready() -> bool:
			return any(t in (ptype, PKT_ERROR) for t, _p in self._replies)

		if not self._waitFor(ready, REPLY_TIMEOUT):
			raise DisplayNotFound(f"BrlAPI: sin respuesta (se esperaba '{chr(ptype)}')")
		with self._cond:
			for i, (t, payload) in enumerate(self._replies):
				if t in (ptype, PKT_ERROR):
					del self._replies[: i + 1]
					break
		if t == PKT_ERROR:
			code = struct.unpack(">I", payload[:4])[0] if len(payload) >= 4 else 0
			raise BrlapiError(code, f"respuesta a '{chr(ptype)}'")
		return payload

	def _resetState(self) -> None:
		self._buffer.clear()
		self._replies = []
		self._ttyMode = False

	# ------------------------------------------------------------ entrada
	def _handleData(self, data: bytes) -> None:
		buf = self._buffer
		buf.extend(data)
		while len(buf) >= 8:
			size, ptype = struct.unpack(">II", bytes(buf[:8]))
			if size > MAX_PACKET_SIZE:
				log.debug("Flujo de BrlAPI no válido (tamaño %d); se descarta", size)
				buf.clear()
				return
			if len(buf) < 8 + size:
				return
			payload = bytes(buf[8 : 8 + size])
			del buf[: 8 + size]
			self._handlePacket(ptype, payload)

	def _handlePacket(self, ptype: int, payload: bytes) -> None:
		if ptype == PKT_KEY:
			if len(payload) >= 8:
				self._handleKey(struct.unpack(">Q", payload[:8])[0])
			return
		if ptype == PKT_EXCEPTION:
			code = struct.unpack(">I", payload[:4])[0] if len(payload) >= 4 else 0
			culprit = struct.unpack(">I", payload[4:8])[0] if len(payload) >= 8 else 0
			log.debug("Excepción de BrlAPI: %s (paquete %r)", ERROR_NAMES.get(code, code), chr(culprit) if 32 <= culprit < 127 else culprit)
			return
		if self._connecting:
			self._replies.append((ptype, payload))
		elif ptype == PKT_ERROR:
			log.debug("Error de BrlAPI: %r", payload[:8])
		# Las confirmaciones de las escrituras ('A') no necesitan nada más.

	def _handleKey(self, code: int) -> None:
		ktype, block, argument, flags = splitKeyCode(code)
		if ktype == KEY_TYPE_CMD:
			self._handleCommand(block, argument, flags)
		elif ktype == KEY_TYPE_SYM:
			self._handleSymbol(argument, flags)
		else:
			log.debug("Tecla de BrlAPI de tipo desconocido: %#x", code)

	def _handleCommand(self, block: int, argument: int, flags: int) -> None:
		name = commandName(block, argument)
		if name in IGNORED_COMMANDS:
			return
		if block == BLK_PASSDOTS:
			self._handleDots(argument, flags)
			return
		gesture = BrailleGesture(
			self.name,
			[name],
			routingIndex=argument if block in CELL_BLOCKS else None,
			model=self.model,
		)
		#: Argumento de la orden (número de terminal, marca, tabla...).
		gesture.argument = argument if block else None
		self._fireGesture(gesture)

	def _handleDots(self, argument: int, flags: int) -> None:
		"""Puntos que BRLTTY deja pasar: gesto para la escritura braille."""
		dots = argument & 0xFF
		keys = [f"dot{i + 1}" for i in range(8) if dots & (1 << i)]
		if argument & DOTS_SPACE or not dots:
			keys.append("space")
		mods = [name for flag, name, _key in _MODIFIER_FLAGS if flags & flag and flag != KEY_FLG_SHIFT]
		if mods:
			# Con modificadores no se escribe: el gesto queda para asignarlo a mano.
			gesture = BrailleGesture(self.name, [k for k in self.keyOrder if k in mods] + keys, model=self.model)
		else:
			gesture = buildGesture(self.name, keys, self.keyOrder, self.dotKeys, self.spaceKeys, self.model)
		if gesture is not None:
			self._fireGesture(gesture)

	def _handleSymbol(self, sym: int, flags: int) -> None:
		"""Tecla del PC que envía BRLTTY (PASSKEY/PASSCHAR): se emula."""
		mods = [(name, key) for flag, name, key in _MODIFIER_FLAGS if flags & flag]
		keyName = SYM_KEYS.get(sym)
		char = ""
		if keyName is None:
			if sym & SYM_UNICODE:
				cp = sym & 0x00FFFFFF
			elif sym < 0x100:
				cp = sym
			else:
				log.debug("Símbolo de teclado de BRLTTY desconocido: %#x", sym)
				return
			try:
				char = chr(cp)
			except ValueError:
				return
			if flags & KEY_FLG_UPPER:
				char = char.upper()
			commandMods = [m for m in mods if m[0] != "key_shift"]
			if not commandMods:
				# Carácter normal: se escribe tal cual.
				self._typeText(char)
				return
			if not (char.isascii() and char.isalnum()):
				log.debug("Carácter %r con modificadores: no se puede emular", char)
				return
			keyName = char.lower()
		emulated = "kb:" + "+".join([key for _n, key in mods] + [keyName])
		gesture = BrailleGesture(self.name, [n for n, _k in mods] + [f"key_{keyName}"], model=self.model)
		gesture.emulatedKey = emulated
		self._fireGesture(gesture)

	def _fireGesture(self, gesture: BrailleGesture) -> None:
		if gesture.emulatedKey is None:
			for gid in gesture.identifiers:
				if gid in self._emulated:
					gesture.emulatedKey = self._emulated[gid]
					break
		self._dispatch(gesture)

	def _typeText(self, text: str) -> None:
		if self.lastGestures is not None:
			self.typedText.append(text)
			return
		queue_handler.queueFunction(_typeText, text)

	# ------------------------------------------------------------ salida
	def _writeCells(self, cells: list[int]) -> None:
		self._sendPacket(PKT_WRITE, writePayload(cells))

	def _sayGoodbye(self) -> None:
		if self._ttyMode:
			self._ttyMode = False
			self._sendPacket(PKT_LEAVETTYMODE)


def _typeText(text: str) -> None:
	"""Escribe en la aplicación los caracteres que envía BRLTTY (hilo del núcleo)."""
	from ... import winapi
	from ...input import core as inputCore

	mgr = inputCore.manager
	if getattr(mgr, "inputHelp", False):
		from ... import speech

		speech.speakMessage(_("línea braille: escribe {char}").format(char=text))
		return
	try:
		winapi.typeText(text)
	except Exception:
		log.exception("No se pudo escribir %r", text)


BrailleDisplayDriver = BrlttyDriver
