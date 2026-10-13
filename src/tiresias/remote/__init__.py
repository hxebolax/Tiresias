"""Acceso remoto: controlar otro equipo o dejar que lo controlen.

Compatible con el acceso remoto de NVDA (NVDA 2025.1 y posteriores) y con el
complemento NVDA Remote: mismo protocolo (JSON por líneas sobre TLS, versión
2), mismos servidores de retransmisión (por ejemplo ``nvdaremote.com``,
puerto 6837) y conexión directa alojando un servidor local.

Módulos:

- :mod:`.protocol`: tipos de mensaje, direcciones, enlaces ``nvdaremote://``.
- :mod:`.serializer`: JSON y traducción de las órdenes de voz.
- :mod:`.connection`, :mod:`.transport`: TLS, hilos de red y reconexión.
- :mod:`.server`, :mod:`.certs`: servidor local y su certificado autofirmado.
- :mod:`.session`: qué hace cada papel con cada mensaje.
- :mod:`.local_machine`: efectos en Tiresias (voz, braille, teclas...).
- :mod:`.client`: orquesta todo (conexión, teclado, avisos).
- :mod:`.store`: preajustes, huellas de confianza y servidores recientes.
- :mod:`.plugin`: órdenes (categoría «Acceso remoto»).
- ``gui/remote_dialogs.py``: diálogos, submenú y panel de opciones.
- :mod:`.rdp`, :mod:`.rdp_io`, :mod:`.rdp_registration`: voz y braille por
  Escritorio remoto (canal virtual «TiresiasRdp», ``rdp/`` en la raíz y
  ``gui/rdp_panel.py``).
"""

from __future__ import annotations

import os

from ..log import getLogger

log = getLogger("remote")

DEFAULTS = {
	"playSounds": True,
	"muteOnLocalControl": False,
	"confirmDisconnectAsFollower": True,
	"connectTimeout": 10,
	"reconnectDelay": 5,
}

_client = None
_initialized = False


def remoteDir() -> str:
	from .. import paths

	return os.path.join(paths.configDir(), "remote")


def registerDefaults() -> None:
	from ..config import conf

	conf.registerDefaults("remote", DEFAULTS)


def getClient():
	"""El cliente de acceso remoto (``None`` si no se ha iniciado)."""
	return _client


def initialize() -> None:
	"""Prepara el acceso remoto (hilo del núcleo, antes de cargar los complementos)."""
	global _client, _initialized
	if _initialized:
		return
	from ..config import policy as _pol

	if not _pol.isAllowed("remoteAccess"):
		# Modo seguro (escritorio seguro): nadie controla el inicio de sesión desde fuera.
		log.info("Acceso remoto desactivado en modo seguro")
		return
	from .. import queue_handler
	from ..plugins import handler as pluginHandler
	from . import cues
	from .certs import CertificateManager
	from .client import RemoteClient
	from .plugin import RemoteGlobalPlugin
	from .store import RemoteStore

	registerDefaults()
	cues.registerSounds()
	folder = remoteDir()
	_client = RemoteClient(RemoteStore(os.path.join(folder, "remoto.json")), CertificateManager(folder))
	pluginHandler.registerBuiltin(RemoteGlobalPlugin)
	try:
		from ..gui import remote_dialogs

		remote_dialogs.registerSettingsPanel()
	except Exception:
		log.exception("No se pudo registrar el panel de acceso remoto")
	try:
		# Voz y braille por Escritorio remoto (canal virtual «TiresiasRdp»).
		from . import rdp
		from ..gui import rdp_panel

		rdp_panel.register()
		rdp.initialize()
	except Exception:
		log.exception("No se pudo iniciar la voz por Escritorio remoto")
	_initialized = True
	# Conexión automática cuando el resto del núcleo ya está listo.
	queue_handler.callLater(1500, _autoconnect)


def _autoconnect() -> None:
	if _client is not None:
		try:
			_client.performAutoconnect()
		except Exception:
			log.exception("Error en la conexión automática")


def terminate() -> None:
	global _client, _initialized
	try:
		from . import rdp

		rdp.terminate()
	except Exception:
		log.exception("Error cerrando la voz por Escritorio remoto")
	if _client is not None:
		try:
			_client.terminate()
		except Exception:
			log.exception("Error cerrando el acceso remoto")
	_client = None
	_initialized = False
