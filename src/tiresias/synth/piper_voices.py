"""Voces neuronales Piper: catálogo, descarga, instalación y borrado.

Las voces se publican en https://huggingface.co/rhasspy/piper-voices. El
catálogo (``voices.json``) se descarga cuando el usuario lo pide desde el
gestor de voces y se guarda en ``data/cache/piper/voices.json`` para poder
consultarlo sin conexión.

Cada voz instalada vive en ``data/voices/<clave>/`` con su modelo
(``<clave>.onnx``), su configuración (``<clave>.onnx.json``) y su ficha
(``MODEL_CARD``). También se reconocen voces copiadas a mano: cualquier
subcarpeta con un ``.onnx`` y su ``.onnx.json``.

Nada se descarga por sí solo: la descarga la inicia siempre el usuario.
Las funciones de red bloquean, así que deben llamarse desde un hilo propio.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

from .. import paths
from ..i18n import _
from ..log import getLogger

log = getLogger("piperVoices")

BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
CATALOG_URL = BASE_URL + "voices.json"
USER_AGENT = "Tiresias (lector de pantalla)"
TIMEOUT = 30

QUALITY_NAMES = {
	"x_low": _("muy baja"),
	"low": _("baja"),
	"medium": _("media"),
	"high": _("alta"),
}
QUALITY_ORDER = {"x_low": 0, "low": 1, "medium": 2, "high": 3}

#: Nombres en español de las variantes del español y de algunos idiomas comunes.
REGION_NAMES = {
	"es_ES": _("Español de España"),
	"es_MX": _("Español de México"),
	"es_AR": _("Español de Argentina"),
	"es_CO": _("Español de Colombia"),
	"es_CL": _("Español de Chile"),
	"es_419": _("Español de Latinoamérica"),
	"es_US": _("Español de Estados Unidos"),
	"ca_ES": _("Catalán"),
	"eu_ES": _("Euskera"),
	"gl_ES": _("Gallego"),
	"en_US": _("Inglés de Estados Unidos"),
	"en_GB": _("Inglés del Reino Unido"),
	"pt_BR": _("Portugués de Brasil"),
	"pt_PT": _("Portugués de Portugal"),
	"fr_FR": _("Francés"),
	"de_DE": _("Alemán"),
	"it_IT": _("Italiano"),
}


@dataclass
class VoiceEntry:
	"""Voz del catálogo (o instalada a mano, sin datos del catálogo)."""

	key: str
	name: str
	language: str  # es_ES
	family: str  # es
	languageName: str
	quality: str
	numSpeakers: int = 1
	speakers: dict = field(default_factory=dict)
	files: dict = field(default_factory=dict)  # ruta relativa -> {"size_bytes", "md5_digest"}

	@property
	def size(self) -> int:
		return sum(int(f.get("size_bytes", 0)) for f in self.files.values())

	@property
	def qualityName(self) -> str:
		return QUALITY_NAMES.get(self.quality, self.quality)

	@property
	def displayName(self) -> str:
		return _("{name} ({lang}, calidad {quality})").format(name=self.name.replace("_", " ").title(), lang=self.languageName, quality=self.qualityName)


def languageName(code: str, nativeName: str = "", country: str = "") -> str:
	if code in REGION_NAMES:
		return REGION_NAMES[code]
	if nativeName and country:
		return f"{nativeName} ({country})"
	return nativeName or code


def formatSize(size: int) -> str:
	if size >= 1024 * 1024:
		return _("{n} MB").format(n=round(size / (1024 * 1024), 1))
	return _("{n} KB").format(n=max(1, round(size / 1024)))


# ---------------------------------------------------------------- rutas
def voicesDir() -> str:
	return paths.voicesDir()


def catalogCachePath() -> str:
	return os.path.join(paths.cacheDir(), "piper", "voices.json")


# ---------------------------------------------------------------- catálogo
def parseCatalog(data: dict) -> list[VoiceEntry]:
	out: list[VoiceEntry] = []
	for key, v in data.items():
		try:
			lang = v.get("language", {})
			out.append(
				VoiceEntry(
					key=key,
					name=v.get("name", key),
					language=lang.get("code", ""),
					family=lang.get("family", ""),
					languageName=languageName(lang.get("code", ""), lang.get("name_native", ""), lang.get("country_english", "")),
					quality=v.get("quality", ""),
					numSpeakers=int(v.get("num_speakers", 1) or 1),
					speakers=dict(v.get("speaker_id_map") or {}),
					files=dict(v.get("files") or {}),
				)
			)
		except Exception:
			log.debug("Entrada de catálogo no válida: %s", key, exc_info=True)
	return sortVoices(out)


def sortVoices(voices: list[VoiceEntry]) -> list[VoiceEntry]:
	"""Primero el español (España y luego Latinoamérica), después el resto por idioma."""

	def key(v: VoiceEntry):
		if v.language == "es_ES":
			group = 0
		elif v.family == "es":
			group = 1
		else:
			group = 2
		return (group, v.languageName.lower(), v.name.lower(), QUALITY_ORDER.get(v.quality, 9))

	return sorted(voices, key=key)


def loadCachedCatalog() -> list[VoiceEntry]:
	try:
		with open(catalogCachePath(), encoding="utf-8") as f:
			return parseCatalog(json.load(f))
	except (OSError, ValueError):
		return []


def _open(url: str):
	req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
	return urllib.request.urlopen(req, timeout=TIMEOUT)


def fetchCatalog() -> list[VoiceEntry]:
	"""Descarga el catálogo (bloquea) y lo guarda en la caché."""
	with _open(CATALOG_URL) as resp:
		raw = resp.read()
	data = json.loads(raw.decode("utf-8"))
	if not isinstance(data, dict):
		raise ValueError("Catálogo de voces no válido")
	os.makedirs(os.path.dirname(catalogCachePath()), exist_ok=True)
	tmp = catalogCachePath() + ".tmp"
	with open(tmp, "wb") as f:
		f.write(raw)
	os.replace(tmp, catalogCachePath())
	return parseCatalog(data)


# ---------------------------------------------------------------- voces instaladas
@dataclass
class InstalledVoice:
	key: str
	folder: str
	model: str
	config: str
	language: str = ""
	quality: str = ""
	name: str = ""
	sampleRate: int = 22050
	speakers: dict = field(default_factory=dict)

	@property
	def displayName(self) -> str:
		lang = languageName(self.language) if self.language else ""
		parts = [self.name.replace("_", " ").title() or self.key]
		if lang:
			parts.append(lang)
		if self.quality:
			parts.append(_("calidad {quality}").format(quality=QUALITY_NAMES.get(self.quality, self.quality)))
		return ", ".join(parts)

	@property
	def size(self) -> int:
		total = 0
		for fn in os.listdir(self.folder):
			try:
				total += os.path.getsize(os.path.join(self.folder, fn))
			except OSError:
				pass
		return total


def _readVoiceConfig(path: str) -> dict:
	with open(path, encoding="utf-8") as f:
		return json.load(f)


def installedVoices() -> list[InstalledVoice]:
	"""Voces instaladas en ``data/voices`` (cada subcarpeta con un .onnx y su .onnx.json)."""
	base = voicesDir()
	out: list[InstalledVoice] = []
	try:
		entries = sorted(os.listdir(base))
	except OSError:
		return out
	for entry in entries:
		folder = os.path.join(base, entry)
		if not os.path.isdir(folder):
			continue
		models = [f for f in os.listdir(folder) if f.endswith(".onnx") and not f.endswith(".part")]
		for model in models:
			cfg = os.path.join(folder, model + ".json")
			if not os.path.isfile(cfg):
				continue
			try:
				data = _readVoiceConfig(cfg)
			except (OSError, ValueError):
				log.warning("Configuración de voz no válida: %s", cfg)
				continue
			key = model[: -len(".onnx")]
			lang = (data.get("language") or {}).get("code") or ""
			if not lang:
				# Las configuraciones antiguas no tienen «language»: se deduce de la clave.
				lang = key.split("-")[0] if "-" in key else ""
			parts = key.split("-")
			out.append(
				InstalledVoice(
					key=key,
					folder=folder,
					model=os.path.join(folder, model),
					config=cfg,
					language=lang,
					quality=(data.get("audio") or {}).get("quality") or (parts[2] if len(parts) > 2 else ""),
					name=parts[1] if len(parts) > 1 else key,
					sampleRate=int((data.get("audio") or {}).get("sample_rate") or 22050),
					speakers=dict(data.get("speaker_id_map") or {}),
				)
			)
	return sortInstalled(out)


def sortInstalled(voices: list[InstalledVoice]) -> list[InstalledVoice]:
	def key(v: InstalledVoice):
		group = 0 if v.language == "es_ES" else (1 if v.language.startswith("es") else 2)
		return (group, v.language, v.key)

	return sorted(voices, key=key)


def isInstalled(key: str) -> bool:
	return any(v.key == key for v in installedVoices())


def deleteVoice(key: str) -> bool:
	"""Borra una voz instalada. Devuelve ``True`` si existía."""
	for v in installedVoices():
		if v.key == key:
			shutil.rmtree(v.folder, ignore_errors=True)
			return not os.path.exists(v.model)
	return False


# ---------------------------------------------------------------- descarga
class DownloadCancelled(Exception):
	pass


def downloadVoice(
	entry: VoiceEntry,
	progress: Callable[[int, int], None] | None = None,
	cancel: threading.Event | None = None,
) -> str:
	"""Descarga e instala una voz (bloquea). Devuelve la carpeta instalada.

	``progress(descargado, total)`` se llama periódicamente. Si ``cancel`` se
	activa, la descarga se interrumpe y se borra lo descargado. Cada archivo
	se comprueba con su MD5 del catálogo.
	"""
	total = entry.size
	done = 0
	final = os.path.join(voicesDir(), entry.key)
	temp = final + ".part"
	shutil.rmtree(temp, ignore_errors=True)
	os.makedirs(temp, exist_ok=True)
	try:
		for rel, info in entry.files.items():
			fn = os.path.basename(rel)
			dest = os.path.join(temp, fn)
			md5 = hashlib.md5()
			with _open(BASE_URL + rel) as resp, open(dest, "wb") as f:
				while True:
					if cancel is not None and cancel.is_set():
						raise DownloadCancelled()
					chunk = resp.read(256 * 1024)
					if not chunk:
						break
					f.write(chunk)
					md5.update(chunk)
					done += len(chunk)
					if progress:
						progress(done, total)
			expected = info.get("md5_digest")
			if expected and md5.hexdigest() != expected:
				raise IOError(_("El archivo {name} se ha descargado dañado.").format(name=fn))
		if not any(f.endswith(".onnx") for f in os.listdir(temp)):
			raise IOError(_("La voz no contiene ningún modelo."))
		shutil.rmtree(final, ignore_errors=True)
		os.replace(temp, final)
		return final
	except BaseException:
		shutil.rmtree(temp, ignore_errors=True)
		raise
