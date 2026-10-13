"""Datos persistentes del acceso remoto (``data/config/remote/remoto.json``).

Se guardan aparte de la configuración general porque no dependen del perfil
activo y contienen claves de conexión:

- ``presets``: preajustes de conexión (nombre, modo, tipo, servidor, puerto, clave).
- ``trustedCertificates``: huellas SHA-256 de confianza por servidor.
- ``lastConnected``: últimos servidores usados.
- ``autoconnect``: nombre del preajuste con el que conectar al iniciar.
- ``autoconnectCustom`` y ``autoconnectData``: conectar al iniciar con unos datos
  propios (modo, tipo, servidor, puerto y clave) sin crear un preajuste.
- ``seenMOTDs``: mensajes de servidor ya mostrados.
"""

from __future__ import annotations

import copy
import json
import os
import threading
from dataclasses import asdict, dataclass, field

from ..log import getLogger
from . import dpapi
from .protocol import SERVER_PORT, ConnectionMode, parseMode

log = getLogger("remote")

#: Tipos de conexión de un preajuste.
KIND_RELAY = "relay"  # servidor de retransmisión u otro equipo que aloja el servidor
KIND_HOST = "host"  # este equipo aloja el servidor (conexión directa)
MAX_RECENT = 10
#: Nombre interno de los datos propios de la conexión automática.
AUTOCONNECT_DATA_NAME = "conexión automática"


@dataclass
class Preset:
	name: str
	mode: str = ConnectionMode.FOLLOWER.value
	kind: str = KIND_RELAY
	host: str = ""
	port: int = SERVER_PORT
	key: str = ""

	@classmethod
	def fromDict(cls, d: dict) -> "Preset | None":
		try:
			name = str(d.get("name", "")).strip()
			if not name:
				return None
			mode = parseMode(d.get("mode", ConnectionMode.FOLLOWER.value)).value
			kind = d.get("kind", KIND_RELAY)
			if kind not in (KIND_RELAY, KIND_HOST):
				kind = KIND_RELAY
			port = int(d.get("port") or SERVER_PORT)
			return cls(name=name, mode=mode, kind=kind, host=str(d.get("host", "")), port=port, key=str(d.get("key", "")))
		except (TypeError, ValueError):
			return None


@dataclass
class _Data:
	presets: list[Preset] = field(default_factory=list)
	trustedCertificates: dict[str, str] = field(default_factory=dict)
	lastConnected: list[str] = field(default_factory=list)
	autoconnect: str = ""
	autoconnectCustom: bool = False
	autoconnectData: Preset | None = None
	seenMOTDs: dict[str, str] = field(default_factory=dict)


class RemoteStore:
	def __init__(self, path: str) -> None:
		self.path = path
		self._lock = threading.RLock()
		self._data = _Data()
		self.load()

	# ------------------------------------------------------------------ disco
	def load(self) -> None:
		with self._lock:
			raw: dict = {}
			try:
				with open(self.path, encoding="utf-8") as f:
					raw = json.load(f)
				if not isinstance(raw, dict):
					raw = {}
			except FileNotFoundError:
				pass
			except (OSError, ValueError):
				log.exception("No se pudo leer %s", self.path)
			data = _Data()
			for p in raw.get("presets", []) or []:
				if isinstance(p, dict):
					preset = Preset.fromDict(p)
					if preset is not None:
						data.presets.append(preset)
			tc = raw.get("trustedCertificates", {})
			if isinstance(tc, dict):
				data.trustedCertificates = {str(k): str(v).lower() for k, v in tc.items()}
			lc = raw.get("lastConnected", [])
			if isinstance(lc, list):
				data.lastConnected = [str(h) for h in lc if h][-MAX_RECENT:]
			data.autoconnect = str(raw.get("autoconnect", "") or "")
			data.autoconnectCustom = raw.get("autoconnectCustom") is True
			ad = raw.get("autoconnectData")
			rawAutoKey = ""
			if isinstance(ad, dict):
				data.autoconnectData = Preset.fromDict({**ad, "name": AUTOCONNECT_DATA_NAME})
				rawAutoKey = ad.get("key", "") or ""
			motd = raw.get("seenMOTDs", {})
			if isinstance(motd, dict):
				data.seenMOTDs = {str(k): str(v) for k, v in motd.items()}
			# Claves: en disco van cifradas con DPAPI; las antiguas en claro se migran.
			needsMigration = False
			self._undecryptable = {}
			rawKeys = {str(p.get("name", "")).strip().lower(): p.get("key", "") for p in raw.get("presets", []) or [] if isinstance(p, dict)}
			for preset in data.presets:
				stored = rawKeys.get(preset.name.lower(), "")
				if dpapi.isProtected(stored):
					try:
						preset.key = dpapi.unprotect(stored)
					except (OSError, ValueError):
						log.warning("No se pudo descifrar la clave del preajuste %s (¿otro usuario u otro equipo?)", preset.name)
						preset.key = ""
						self._undecryptable[preset.name.lower()] = stored
				elif stored:
					needsMigration = True
			self._autoKeyUndecryptable = ""
			if data.autoconnectData is not None and rawAutoKey:
				if dpapi.isProtected(rawAutoKey):
					try:
						data.autoconnectData.key = dpapi.unprotect(rawAutoKey)
					except (OSError, ValueError):
						log.warning("No se pudo descifrar la clave de la conexión automática (¿otro usuario u otro equipo?)")
						data.autoconnectData.key = ""
						self._autoKeyUndecryptable = rawAutoKey
				else:
					needsMigration = True
			self._data = data
		if needsMigration:
			log.info("Se cifran las claves de los preajustes de acceso remoto")
			self.save()

	def save(self) -> None:
		with self._lock:
			obj = asdict(self._data)
			undecryptable = dict(getattr(self, "_undecryptable", {}))
			autoUndecryptable = getattr(self, "_autoKeyUndecryptable", "")
		for p in obj.get("presets", []):
			key = p.get("key", "")
			if key:
				try:
					p["key"] = dpapi.protect(key)
				except OSError:
					# Nunca en claro en el disco: la clave queda solo en memoria (esta sesión).
					log.warning("No se pudo cifrar la clave del preajuste %s: no se guarda", p.get("name"))
					p["key"] = ""
			elif p.get("name", "").lower() in undecryptable:
				# Clave cifrada por otro usuario o equipo: se conserva tal cual.
				p["key"] = undecryptable[p["name"].lower()]
		ad = obj.get("autoconnectData")
		if isinstance(ad, dict):
			ad.pop("name", None)
			if ad.get("key"):
				try:
					ad["key"] = dpapi.protect(ad["key"])
				except OSError:
					log.warning("No se pudo cifrar la clave de la conexión automática: no se guarda")
					ad["key"] = ""
			elif autoUndecryptable:
				ad["key"] = autoUndecryptable
		try:
			os.makedirs(os.path.dirname(self.path), exist_ok=True)
			tmp = self.path + ".tmp"
			with open(tmp, "w", encoding="utf-8") as f:
				json.dump(obj, f, ensure_ascii=False, indent="\t")
			os.replace(tmp, self.path)
		except OSError:
			log.exception("No se pudo guardar %s", self.path)

	# ------------------------------------------------------------------ preajustes
	def getPresets(self) -> list[Preset]:
		with self._lock:
			return [copy.copy(p) for p in self._data.presets]

	def getPreset(self, name: str) -> Preset | None:
		with self._lock:
			for p in self._data.presets:
				if p.name.lower() == (name or "").lower():
					return copy.copy(p)
		return None

	def keyUnavailable(self, name: str) -> bool:
		"""``True`` si la clave del preajuste está cifrada por otro usuario o equipo
		y no se ha podido descifrar (el preajuste se ve sin clave)."""
		with self._lock:
			return (name or "").lower() in getattr(self, "_undecryptable", {})

	def savePreset(self, preset: Preset) -> None:
		with self._lock:
			self._data.presets = [p for p in self._data.presets if p.name.lower() != preset.name.lower()]
			self._data.presets.append(copy.copy(preset))
			self._data.presets.sort(key=lambda p: p.name.lower())
		self.save()

	def deletePreset(self, name: str) -> bool:
		with self._lock:
			before = len(self._data.presets)
			self._data.presets = [p for p in self._data.presets if p.name.lower() != (name or "").lower()]
			removed = len(self._data.presets) != before
			if removed and self._data.autoconnect.lower() == (name or "").lower():
				self._data.autoconnect = ""
		if removed:
			self.save()
		return removed

	@property
	def autoconnect(self) -> str:
		with self._lock:
			return self._data.autoconnect

	@autoconnect.setter
	def autoconnect(self, name: str) -> None:
		with self._lock:
			self._data.autoconnect = name or ""
			if name:
				self._data.autoconnectCustom = False
		self.save()

	@property
	def autoconnectCustom(self) -> bool:
		"""``True`` si al iniciar se conecta con los datos propios (:attr:`autoconnectData`)."""
		with self._lock:
			return self._data.autoconnectCustom and self._data.autoconnectData is not None

	@property
	def autoconnectData(self) -> Preset | None:
		"""Datos propios de la conexión automática (se conservan aunque esté desactivada)."""
		with self._lock:
			d = self._data.autoconnectData
			return copy.copy(d) if d is not None else None

	def autoconnectKeyUnavailable(self) -> bool:
		"""``True`` si la clave de la conexión automática no se pudo descifrar."""
		with self._lock:
			return bool(getattr(self, "_autoKeyUndecryptable", "")) and not (self._data.autoconnectData and self._data.autoconnectData.key)

	def setAutoconnect(self, name: str = "", data: Preset | None = None, custom: bool = False) -> None:
		"""Conexión automática al iniciar: con los datos propios (``custom``), con
		el preajuste ``name`` o, sin ninguno de los dos, desactivada.

		Los datos propios se guardan siempre que se indiquen, aunque luego se
		elija un preajuste o no conectar, para no tener que escribirlos otra vez.
		"""
		with self._lock:
			if data is not None:
				d = copy.copy(data)
				d.name = AUTOCONNECT_DATA_NAME
				if d.key:
					self._autoKeyUndecryptable = ""
				self._data.autoconnectData = d
			self._data.autoconnectCustom = bool(custom) and self._data.autoconnectData is not None
			self._data.autoconnect = "" if self._data.autoconnectCustom else (name or "")
		self.save()

	# ------------------------------------------------------------------ certificados
	def isTrusted(self, address: str, fingerprint: str) -> bool:
		with self._lock:
			return bool(fingerprint) and self._data.trustedCertificates.get(address) == fingerprint.lower()

	def trust(self, address: str, fingerprint: str) -> None:
		with self._lock:
			self._data.trustedCertificates[address] = fingerprint.lower()
		self.save()

	def trustedCertificates(self) -> dict[str, str]:
		with self._lock:
			return dict(self._data.trustedCertificates)

	def clearTrusted(self) -> None:
		with self._lock:
			self._data.trustedCertificates = {}
		self.save()

	# ------------------------------------------------------------------ otros
	def addRecent(self, host: str) -> None:
		if not host:
			return
		with self._lock:
			recent = [h for h in self._data.lastConnected if h.lower() != host.lower()]
			recent.append(host)
			self._data.lastConnected = recent[-MAX_RECENT:]
		self.save()

	def recentHosts(self) -> list[str]:
		"""Servidores usados, del más reciente al más antiguo."""
		with self._lock:
			return list(reversed(self._data.lastConnected))

	def shouldShowMotd(self, address: str, digest: str) -> bool:
		"""``True`` si el mensaje es nuevo (y lo marca como visto)."""
		with self._lock:
			if self._data.seenMOTDs.get(address) == digest:
				return False
			self._data.seenMOTDs[address] = digest
		self.save()
		return True
