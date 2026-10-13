"""Protocolo del acceso remoto (compatible con NVDA Remote y el acceso remoto de NVDA).

Los mensajes son objetos JSON, uno por línea (separados por ``\\n``), que
viajan cifrados con TLS. Todos llevan un campo ``type``. La versión 2 del
protocolo añade el campo ``origin`` (identificador del cliente que envía el
mensaje) y la lista de clientes del canal.

Este módulo no depende de wxPython ni del resto de Tiresias: lo usan el
cliente, el servidor local y las pruebas.
"""

from __future__ import annotations

import secrets
import urllib.parse
from dataclasses import dataclass
from enum import Enum

PROTOCOL_VERSION = 2
#: Puerto estándar de los servidores de retransmisión (nvdaremote.com y otros).
SERVER_PORT = 6837
URL_PREFIX = "nvdaremote://"


class MessageType(str, Enum):
	"""Tipos de mensaje del protocolo (los valores son los del cable)."""

	# Conexión y canal
	PROTOCOL_VERSION = "protocol_version"
	JOIN = "join"
	CHANNEL_JOINED = "channel_joined"
	CLIENT_JOINED = "client_joined"
	CLIENT_LEFT = "client_left"
	GENERATE_KEY = "generate_key"
	# Control
	KEY = "key"
	SPEAK = "speak"
	CANCEL = "cancel"
	PAUSE_SPEECH = "pause_speech"
	TONE = "tone"
	WAVE = "wave"
	SEND_SAS = "send_SAS"
	INDEX = "index"
	# Braille
	DISPLAY = "display"
	BRAILLE_INPUT = "braille_input"
	SET_BRAILLE_INFO = "set_braille_info"
	SET_DISPLAY_SIZE = "set_display_size"
	# Portapapeles
	SET_CLIPBOARD_TEXT = "set_clipboard_text"
	# Sistema
	MOTD = "motd"
	VERSION_MISMATCH = "version_mismatch"
	PING = "ping"
	ERROR = "error"
	NVDA_NOT_CONNECTED = "nvda_not_connected"

	def __str__(self) -> str:
		return self.value


class ConnectionMode(str, Enum):
	"""Papel de este equipo en la sesión (valores del protocolo)."""

	#: Controla otro equipo («master» en el protocolo).
	LEADER = "master"
	#: Es controlado por otro equipo («slave» en el protocolo).
	FOLLOWER = "slave"

	def __str__(self) -> str:
		return self.value

	@property
	def opposite(self) -> "ConnectionMode":
		return ConnectionMode.FOLLOWER if self is ConnectionMode.LEADER else ConnectionMode.LEADER


def parseMode(value: str | ConnectionMode) -> ConnectionMode:
	"""Acepta ``master``/``slave`` y también ``leader``/``follower``."""
	if isinstance(value, ConnectionMode):
		return value
	v = (value or "").strip().lower()
	if v in ("leader", "controller", "control"):
		return ConnectionMode.LEADER
	if v in ("follower", "controlled"):
		return ConnectionMode.FOLLOWER
	return ConnectionMode(v)


def addressToHostPort(addr: str, defaultPort: int = SERVER_PORT) -> tuple[str, int]:
	"""``"ejemplo.com:1234"`` -> ``("ejemplo.com", 1234)``. Sin puerto, el estándar.

	Admite direcciones IPv6 entre corchetes (``[::1]:6837``).
	"""
	addr = (addr or "").strip()
	parsed = urllib.parse.urlparse("//" + addr)
	try:
		port = parsed.port
	except ValueError as e:
		raise ValueError(f"Puerto no válido en {addr!r}") from e
	host = parsed.hostname
	if not host:
		raise ValueError(f"Dirección no válida: {addr!r}")
	return host, port or defaultPort


def hostPortToAddress(hostPort: tuple[str, int]) -> str:
	"""``("ejemplo.com", 6837)`` -> ``"ejemplo.com"``; con otro puerto, ``"host:puerto"``.

	Es también la clave con la que se guardan las huellas de confianza.
	"""
	host, port = hostPort
	if ":" in host:
		host = f"[{host}]"
	if port != SERVER_PORT:
		return f"{host}:{port}"
	return host


def generateKey(length: int = 10) -> str:
	"""Clave aleatoria de cifras (fácil de dictar por teléfono)."""
	first = secrets.choice("123456789")
	return first + "".join(secrets.choice("0123456789") for _i in range(max(1, length) - 1))


class URLParsingError(ValueError):
	"""El enlace ``nvdaremote://`` no es válido."""


@dataclass
class ConnectionInfo:
	"""Datos de una conexión: servidor, puerto, clave y modo."""

	hostname: str
	mode: ConnectionMode
	key: str
	port: int = SERVER_PORT
	#: Aceptar el certificado sin validarlo (se comprueba la huella si se indica).
	insecure: bool = False
	trustedFingerprint: str | None = None

	def __post_init__(self) -> None:
		self.port = int(self.port or SERVER_PORT)
		self.mode = parseMode(self.mode)

	@classmethod
	def fromURL(cls, url: str) -> "ConnectionInfo":
		"""Lee un enlace ``nvdaremote://host[:puerto]?key=...&mode=master|slave``."""
		url = (url or "").strip()
		if not url.lower().startswith(URL_PREFIX):
			raise URLParsingError("El enlace debe empezar por nvdaremote://")
		parsed = urllib.parse.urlparse(url)
		query = urllib.parse.parse_qs(parsed.query)
		hostname = parsed.hostname
		try:
			port = parsed.port
		except ValueError as e:
			raise URLParsingError("Puerto no válido") from e
		key = query.get("key", [""])[0]
		mode = query.get("mode", [""])[0].lower()
		insecure = query.get("insecure", ["false"])[0].lower() == "true"
		if not hostname:
			raise URLParsingError("Falta el servidor")
		if not key:
			raise URLParsingError("Falta la clave")
		if not mode:
			raise URLParsingError("Falta el modo")
		try:
			parsedMode = parseMode(mode)
		except ValueError as e:
			raise URLParsingError(f"Modo no válido: {mode!r}") from e
		return cls(hostname=hostname, mode=parsedMode, key=key, port=port or SERVER_PORT, insecure=insecure)

	def getAddress(self) -> str:
		host = f"[{self.hostname}]" if ":" in self.hostname else self.hostname
		return f"{host}:{self.port}"

	def _buildURL(self, mode: ConnectionMode) -> str:
		netloc = hostPortToAddress((self.hostname, self.port))
		params = {"key": self.key, "mode": mode.value}
		if self.insecure:
			params["insecure"] = "true"
		return urllib.parse.urlunparse(("nvdaremote", netloc, "", "", urllib.parse.urlencode(params), ""))

	def getURL(self) -> str:
		"""Enlace con el modo de este equipo."""
		return self._buildURL(self.mode)

	def getURLToConnect(self) -> str:
		"""Enlace para que el otro equipo se conecte (con el modo contrario)."""
		return self._buildURL(self.mode.opposite)
