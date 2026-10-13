"""Publica una versión de Tiresias en el servidor de distribución y en GitHub.

Uso (lo hace ``Tiresias.bat publicar``)::

	python tools/publicar.py [--destino CARPETA] [--simular] [--canal estable|beta]
	                         [--notas "texto corto"] [--min-windows 10.0.10240]
	                         [--incluir-propietario [--acepto-responsabilidad]]
	                         [--sin-propietario] [--sin-instalador] [--sin-docs]
	                         [--programa CARPETA] [--config tools/publicar.json]
	                         [--solo-servidor | --solo-github | --sin-github]
	                         [--repositorio PROPIETARIO/NOMBRE]

GitHub (desde la 1.0.13): con ``"github": {"repo": "hxebolax/Tiresias",
"publicar": true}`` en ``tools/publicar.json`` publica también, con la
herramienta ``gh``, en las versiones (releases) del repositorio (ver
:func:`publishGithub`):

	v<versión>      instalador, portable, código fuente y sus .sha256; notas
	                sacadas de docs/novedades.html
	distribucion    actualizacion.json, versiones.json y catalogo.json (URL absolutas)
	complementos    <id>-<versión>.tiresias-addon y .sha256, SIN los propietarios

``--solo-servidor`` (o ``--sin-github``) y ``--solo-github`` eligen un solo
destino. Con ``--simular`` no se llama a ``gh``: solo se lista lo que haría.

Genera o actualiza en ``--destino`` (por defecto, la variable ``TIRESIAS_WEB``
o el valor «destino» de ``tools/publicar.local.json``, que no se sube al
repositorio porque es una ruta de este equipo)::

	index.html                       portada accesible
	actualizacion.json               manifiesto que lee el actualizador
	versiones.json                   historial de versiones publicadas
	novedades.html                   copia de docs/novedades.html
	manual/index.html                manual de usuario
	descargas/<versión>/...          instalador, ZIP portable, ZIP del código y sus .sha256
	complementos/catalogo.json       catálogo de la tienda (todas las versiones)
	complementos/<id>/<id>-<versión>.tiresias-addon (y .sha256)
	.htaccess                        tipos MIME y sin caché en los JSON (solo Apache)

Las direcciones de los JSON son relativas al propio JSON: la carpeta se puede
servir desde cualquier dirección (Synology, GitHub Pages...) sin regenerarla.

Es idempotente: el historial y el catálogo se reconstruyen a partir de lo que
ya hay publicado más lo nuevo, sin duplicar versiones y conservando las
anteriores; los archivos iguales no se vuelven a escribir.

AVISO LEGAL: el complemento Eloquence contiene bibliotecas propietarias de
IBM/Nuance (ECI.DLL y los .SYN). Sin configuración NO se publica, y las
descargas públicas (instalador, portable y código fuente) se generan desde una
copia sin él. Se incluye, bajo la responsabilidad de quien publica, con
``--incluir-propietario`` (pide confirmación) o con ``"incluirPropietario": true``
en ``tools/publicar.json`` (decisión ya registrada: no pregunta);
``--sin-propietario`` publica la variante sin él en cualquier caso. Ver
``docs/publicacion.md``.
"""

from __future__ import annotations

import argparse
import datetime
import fnmatch
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tiresias  # noqa: E402
from tiresias import addon_store, addons, updates  # noqa: E402

#: Carpeta del servidor: variable TIRESIAS_WEB o «destino» de tools/publicar.local.json
#: (archivo de este equipo, fuera del repositorio) o de tools/publicar.json.
DEFAULT_DEST = os.environ.get("TIRESIAS_WEB") or ""
DIST = os.path.join(ROOT, "dist")
PROGRAM = os.path.join(DIST, "Tiresias")
WORK = os.path.join(DIST, "publicacion")
DEFAULT_MIN_WINDOWS = "10.0.10240"
SIGNATURE = "© XeBoLaX"

#: Complementos con componentes propietarios: nunca se publican sin --incluir-propietario.
#: También lo es cualquier complemento con ``"proprietary": true`` en su manifiesto
#: (p. ej. las voces neuronales de Microsoft).
PROPRIETARY_ADDONS = {"eloquence"}
#: Complementos que solo se publican en la tienda (no van dentro del programa).
STORE_ADDONS_DIR = os.path.join(ROOT, "complementos_tienda")
#: Archivos que delatan componentes propietarios (Eloquence/IBMTTS de IBM/Nuance).
PROPRIETARY_PATTERNS = ["eci.dll", "*.syn"]
#: Partes de data de dist que nunca se publican (datos del desarrollador).
PRIVATE_DATA = ["config", "logs", "cache", "temp", "labels", "voices", "addonsData", "speechDicts/voices", "addons/pending.json"]
PRIVATE_TOP = ["instalado.json", "systemConfig"]

#: Tipos de archivo publicados para cada versión.
FILE_KINDS = ("installer", "portable", "source")
KIND_NAMES = {
	"installer": "Tiresias-{v}-instalador.exe",
	"portable": "Tiresias-{v}-portable.zip",
	"source": "Tiresias-{v}-codigo-fuente.zip",
}
KIND_LABELS = {
	"installer": "Instalador (recomendado)",
	"portable": "Copia portable (ZIP, sin instalar)",
	"source": "Código fuente (ZIP)",
}

HTACCESS = """# Tiresias: servidor de distribución. Solo lo lee Apache (nginx y GitHub Pages lo ignoran).
<IfModule mod_mime.c>
	AddType application/json .json
	AddType application/octet-stream .tiresias-addon
	AddType text/plain .sha256
	AddCharset utf-8 .json .html .sha256
</IfModule>
<IfModule mod_headers.c>
	# Los JSON cambian con cada publicación: siempre se revalidan.
	<FilesMatch "\\.json$">
		Header set Cache-Control "no-cache, must-revalidate"
	</FilesMatch>
</IfModule>
"""


# ====================================================================== utilidades
def sha256(path: str) -> str:
	h = hashlib.sha256()
	with open(path, "rb") as f:
		for chunk in iter(lambda: f.read(1 << 20), b""):
			h.update(chunk)
	return h.hexdigest()


def shaLine(digest: str, name: str) -> str:
	"""Formato de ``sha256sum`` en modo binario (como en el resto de la web)."""
	return f"{digest} *{name}\n"


def dumpJson(obj) -> str:
	return json.dumps(obj, ensure_ascii=False, indent="\t") + "\n"


def isProprietaryName(name: str) -> bool:
	low = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
	return any(fnmatch.fnmatch(low, p) for p in PROPRIETARY_PATTERNS)


def findProprietary(folder: str) -> list[str]:
	"""Archivos propietarios dentro de ``folder`` (rutas relativas)."""
	out = []
	for root, _dirs, files in os.walk(folder):
		for fn in files:
			if isProprietaryName(fn):
				out.append(os.path.relpath(os.path.join(root, fn), folder))
	return out


def packageManifest(path: str) -> dict:
	with zipfile.ZipFile(path) as z:
		return json.loads(z.read("manifest.json").decode("utf-8-sig"))


def isProprietaryManifest(m: dict) -> bool:
	return str(m.get("id")) in PROPRIETARY_ADDONS or m.get("proprietary") is True


def isProprietaryPackage(path: str) -> bool:
	m = packageManifest(path)
	if isProprietaryManifest(m):
		return True
	with zipfile.ZipFile(path) as z:
		return any(isProprietaryName(n) for n in z.namelist())


def readJson(path: str, default):
	try:
		with open(path, encoding="utf-8-sig") as f:
			return json.load(f)
	except (OSError, ValueError):
		return default


# ====================================================================== escritura (con simulación)
@dataclass
class Writer:
	"""Escribe en la carpeta de destino o, con ``simulate``, solo cuenta lo que haría."""

	dest: str
	simulate: bool = False
	actions: list[str] = field(default_factory=list)

	def _log(self, verb: str, rel: str) -> None:
		line = f"{'[simulación] ' if self.simulate else ''}{verb}: {rel}"
		self.actions.append(line)
		print(line)

	def path(self, rel: str) -> str:
		return os.path.join(self.dest, *rel.split("/"))

	def writeText(self, rel: str, text: str) -> bool:
		p = self.path(rel)
		data = text.encode("utf-8")
		try:
			with open(p, "rb") as f:
				if f.read() == data:
					return False
		except OSError:
			pass
		self._log("escribir", rel)
		if not self.simulate:
			os.makedirs(os.path.dirname(p), exist_ok=True)
			tmp = p + ".tmp"
			with open(tmp, "wb") as f:
				f.write(data)
			os.replace(tmp, p)
		return True

	def copyFile(self, src: str, rel: str, digest: str | None = None) -> bool:
		p = self.path(rel)
		if os.path.isfile(p) and os.path.getsize(p) == os.path.getsize(src) and sha256(p) == (digest or sha256(src)):
			return False
		self._log("copiar", f"{rel} ({os.path.getsize(src)} bytes)")
		if not self.simulate:
			os.makedirs(os.path.dirname(p), exist_ok=True)
			tmp = p + ".tmp"
			shutil.copyfile(src, tmp)
			os.replace(tmp, p)
		return True

	def removeTree(self, rel: str) -> None:
		p = self.path(rel)
		if not os.path.exists(p):
			return
		self._log("borrar", rel)
		if not self.simulate:
			if os.path.isdir(p):
				shutil.rmtree(p)
			else:
				os.remove(p)


# ====================================================================== copia pública del programa
def stageProgram(source: str, dest: str, includeProprietary: bool = False) -> list[str]:
	"""Copia ``source`` (dist/Tiresias) en ``dest`` sin datos del desarrollador.

	Sin ``includeProprietary`` omite los complementos propietarios y comprueba
	que no quede ningún archivo propietario. Devuelve lo omitido.
	"""
	if not os.path.isfile(os.path.join(source, "Tiresias.exe")):
		raise SystemExit(f"No se encuentra {os.path.join(source, 'Tiresias.exe')}: compile antes (Tiresias.bat compilar)")
	shutil.rmtree(dest, ignore_errors=True)
	skipped: list[str] = []
	skip = {p.lower() for p in PRIVATE_TOP}
	skip |= {f"data/{p}".lower() for p in PRIVATE_DATA}
	if not includeProprietary:
		skip |= {f"data/addons/{a}".lower() for a in PROPRIETARY_ADDONS}
	for root, dirs, files in os.walk(source):
		rel = os.path.relpath(root, source).replace("\\", "/")
		rel = "" if rel == "." else rel
		keep = []
		for d in dirs:
			r = f"{rel}/{d}" if rel else d
			if d == "__pycache__":
				continue
			if r.lower() in skip:
				skipped.append(r)
				# Las carpetas de datos se dejan vacías (el programa las espera).
				if r.lower().startswith("data/") and not r.lower().startswith("data/addons/"):
					os.makedirs(os.path.join(dest, *r.split("/")), exist_ok=True)
				continue
			keep.append(d)
		dirs[:] = keep
		os.makedirs(os.path.join(dest, *rel.split("/")) if rel else dest, exist_ok=True)
		for fn in files:
			r = f"{rel}/{fn}" if rel else fn
			if r.lower() in skip or fn.endswith((".pyc", ".tmp", ".part")) and "lib/" not in r:
				skipped.append(r)
				continue
			shutil.copy2(os.path.join(root, fn), os.path.join(dest, *r.split("/")))
	if not includeProprietary:
		found = findProprietary(dest)
		if found:
			raise SystemExit("La copia pública contiene archivos propietarios; no se publica:\n  " + "\n  ".join(found))
	return skipped


def dirEntry(name: str) -> zipfile.ZipInfo:
	"""Entrada de carpeta vacía con fecha fija (el ZIP sale idéntico si nada cambia)."""
	zi = zipfile.ZipInfo(name.rstrip("/") + "/", date_time=(1980, 1, 1, 0, 0, 0))
	zi.external_attr = (0o40755 << 16) | 0x10
	return zi


def makePortableZip(programDir: str, out: str) -> str:
	"""ZIP portable con la carpeta ``Tiresias`` dentro (orden estable)."""
	os.makedirs(os.path.dirname(out), exist_ok=True)
	tmp = out + ".tmp"
	with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
		for root, dirs, files in os.walk(programDir):
			dirs.sort()
			rel = os.path.relpath(root, programDir)
			arcRoot = "Tiresias" if rel == "." else "Tiresias/" + rel.replace("\\", "/")
			if not files and not dirs:
				z.writestr(dirEntry(arcRoot), "")
			for fn in sorted(files):
				z.write(os.path.join(root, fn), f"{arcRoot}/{fn}")
	os.replace(tmp, out)
	return out


def addonFolders(bases: list[str] | None = None) -> list[str]:
	"""Carpetas de complementos: los incluidos (data/addons) y los de la tienda (complementos_tienda)."""
	out = []
	for base in bases or [os.path.join(ROOT, "data", "addons"), STORE_ADDONS_DIR]:
		if not os.path.isdir(base):
			continue
		for entry in sorted(os.listdir(base)):
			folder = os.path.join(base, entry)
			if os.path.isdir(folder) and not entry.startswith(("_", ".")):
				out.append(folder)
	return out


def proprietaryStoreFolders(bases: list[str] | None = None, root: str = ROOT) -> list[str]:
	"""Rutas relativas a ``root`` de los complementos de la tienda con componentes propietarios."""
	out = []
	for folder in addonFolders(bases or [STORE_ADDONS_DIR]):
		m = addons._readManifest(folder) or {}
		if isProprietaryManifest(m) or os.path.basename(folder) in PROPRIETARY_ADDONS or findProprietary(folder):
			out.append(os.path.relpath(folder, root).replace(os.sep, "/"))
	return out


def buildAddonPackages(outDir: str, includeProprietary: bool, bases: list[str] | None = None) -> list[str]:
	"""Empaqueta los complementos incluidos y los de la tienda (sin los propietarios si no se piden)."""
	os.makedirs(outDir, exist_ok=True)
	out = []
	for folder in addonFolders(bases):
		entry = os.path.basename(folder)
		m = addons._readManifest(folder)
		if not m:
			continue
		if not includeProprietary and (entry in PROPRIETARY_ADDONS or isProprietaryManifest(m) or findProprietary(folder)):
			print(f"Complemento propietario omitido: {entry}")
			continue
		out.append(addons.createPackage(folder, os.path.join(outDir, f"{m.get('id') or entry}{addons.ADDON_EXTENSION}")))
	return out


# ====================================================================== catálogo
def catalogEntryFor(manifest: dict, rel: str, digest: str, size: int, previous: dict | None, date: str) -> dict:
	previous = previous or {}
	return {
		"version": str(manifest.get("version", "0")),
		"url": rel,
		"sha256": digest,
		"size": size,
		"minApiVersion": str(manifest.get("minApiVersion", "1.0")),
		"lastTestedApiVersion": str(manifest.get("lastTestedApiVersion", "1.0")),
		"changelog": manifest.get("changelog") or previous.get("changelog", ""),
		"date": previous.get("date") or date,
	}


def buildCatalog(addonsRoot: str, previous: dict, date: str, includeProprietary: bool) -> dict:
	"""Catálogo con todas las versiones publicadas en ``complementos/<id>/``."""
	prevVersions: dict[tuple[str, str], dict] = {}
	for item in previous.get("addons") or []:
		for v in item.get("versions") or [item]:
			prevVersions[(str(item.get("id")), str(v.get("version")))] = v
	result = []
	if os.path.isdir(addonsRoot):
		for addonId in sorted(os.listdir(addonsRoot)):
			folder = os.path.join(addonsRoot, addonId)
			if not os.path.isdir(folder):
				continue
			versions, latest = [], None
			for fn in sorted(os.listdir(folder)):
				if not fn.endswith(addons.ADDON_EXTENSION):
					continue
				path = os.path.join(folder, fn)
				m = packageManifest(path)
				if not includeProprietary and isProprietaryPackage(path):
					continue
				v = catalogEntryFor(m, f"{addonId}/{fn}", sha256(path), os.path.getsize(path), prevVersions.get((addonId, str(m.get("version")))), date)
				versions.append(v)
				if latest is None or updates.versionKey(v["version"]) > updates.versionKey(latest[0]["version"]):
					latest = (v, m)
			if not versions:
				continue
			versions.sort(key=lambda v: updates.versionKey(v["version"]), reverse=True)
			v, m = latest
			result.append(
				{
					"id": addonId,
					"name": m.get("name", addonId),
					"version": v["version"],
					"author": m.get("author", ""),
					"description": m.get("description", ""),
					"minApiVersion": v["minApiVersion"],
					"lastTestedApiVersion": v["lastTestedApiVersion"],
					"url": v["url"],
					"sha256": v["sha256"],
					"size": v["size"],
					"homepage": m.get("url", ""),
					"changelog": v["changelog"],
					"date": v["date"],
					"proprietary": isProprietaryManifest(m) or addonId in PROPRIETARY_ADDONS,
					"versions": versions,
				}
			)
	return {"format": addon_store.CATALOG_FORMAT, "version": 1, "addons": result}


# ====================================================================== versiones y manifiesto
def fileEntry(path: str, rel: str) -> dict:
	return {"name": os.path.basename(path), "url": rel, "sha256": sha256(path), "size": os.path.getsize(path)}


def updateHistory(history: dict, entry: dict) -> dict:
	versions = [v for v in history.get("versions") or [] if isinstance(v, dict) and v.get("version") != entry["version"]]
	versions.append(entry)
	versions.sort(key=lambda v: updates.versionKey(v["version"]), reverse=True)
	return {"format": "tiresias-versiones", "formatVersion": 1, "versions": versions}


def _channelEntry(v: dict) -> dict:
	files = v.get("files") or {}
	main = files.get("installer") or files.get("portable") or files.get("source") or {}
	out = {
		"version": v["version"],
		"date": v.get("date", ""),
		"url": main.get("url", ""),
		"sha256": main.get("sha256", ""),
		"size": main.get("size", 0),
		"minWindows": v.get("minWindows", DEFAULT_MIN_WINDOWS),
		"notes": v.get("notes", ""),
		"notesUrl": v.get("notesUrl", updates.NEWS_FILE),
	}
	for kind in FILE_KINDS:
		f = files.get(kind)
		if f:
			out[kind] = {"url": f["url"], "sha256": f["sha256"], "size": f["size"]}
	return out


def buildManifest(history: dict) -> dict:
	"""Manifiesto: el estable más reciente arriba; el beta solo si es más nuevo."""
	versions = history.get("versions") or []
	stable = [v for v in versions if v.get("channel", "estable") == "estable"]
	beta = [v for v in versions if v.get("channel") == "beta"]
	key = lambda v: updates.versionKey(v["version"])  # noqa: E731
	manifest: dict = {"format": updates.MANIFEST_FORMAT, "formatVersion": 1}
	top = max(stable, key=key) if stable else None
	if top:
		manifest.update(_channelEntry(top))
	if beta:
		b = max(beta, key=key)
		if top is None or key(b) > key(top):
			manifest["channels"] = {"beta": _channelEntry(b)}
	return manifest


# ====================================================================== portada
def _mb(size: int) -> str:
	return f"{size / (1024 * 1024):.1f} MB".replace(".", ",")


def _e(text) -> str:
	return html.escape(str(text or ""), quote=True)


def _downloadList(entry: dict) -> str:
	items = []
	for kind in FILE_KINDS:
		f = (entry.get("files") or {}).get(kind)
		if not f:
			continue
		items.append(
			f'<li><a href="{_e(f["url"])}">{_e(KIND_LABELS[kind])}</a>: <span class="nombre">{_e(f["name"])}</span>, {_mb(f["size"])}.'
			f'<br>SHA-256: <code>{_e(f["sha256"])}</code> (<a href="{_e(f["url"])}.sha256">archivo .sha256</a>)</li>'
		)
	return "<ul>\n" + "\n".join(items) + "\n</ul>"


def buildIndex(history: dict, catalog: dict, includesProprietary: bool) -> str:
	"""Portada. ``includesProprietary``: las descargas del programa llevan Eloquence."""
	versions = history.get("versions") or []
	stable = [v for v in versions if v.get("channel", "estable") == "estable"]
	beta = [v for v in versions if v.get("channel") == "beta"]
	latest = stable[0] if stable else (versions[0] if versions else None)
	parts: list[str] = []
	if latest:
		parts.append(f'<section aria-labelledby="descargas"><h2 id="descargas">Descargar Tiresias {_e(latest["version"])}</h2>')
		parts.append(f'<p>Publicada el {_e(latest.get("date", ""))}. Si no sabe cuál elegir, descargue el instalador.</p>')
		parts.append(_downloadList(latest))
		parts.append(
			"<p>Para comprobar una descarga, compare su SHA-256 con el de esta página; por ejemplo, en PowerShell: "
			"<code>Get-FileHash .\\archivo -Algorithm SHA256</code>.</p>"
		)
		if beta and (not stable or updates.versionKey(beta[0]["version"]) > updates.versionKey(stable[0]["version"])):
			b = beta[0]
			parts.append(f'<h3>Versión de prueba {_e(b["version"])}</h3><p>Solo para quien quiera probar novedades antes que nadie; puede tener errores.</p>')
			parts.append(_downloadList(b))
		parts.append("</section>")
		parts.append('<section aria-labelledby="novedades"><h2 id="novedades">Novedades</h2>')
		if latest.get("notes"):
			parts.append(f"<p>{_e(latest['notes'])}</p>")
		parts.append(f'<p><a href="{updates.NEWS_FILE}">Todas las novedades de la versión {_e(latest["version"])}</a>.</p></section>')
	else:
		parts.append('<section aria-labelledby="descargas"><h2 id="descargas">Descargas</h2><p>Todavía no hay ninguna versión publicada.</p></section>')
	# Solo cómo se instalan: el catálogo se consulta en la tienda incorporada.
	parts.append('<section aria-labelledby="complementos"><h2 id="complementos">Complementos</h2>')
	parts.append(
		"<p>Los complementos amplían Tiresias con voces nuevas, mejoras para aplicaciones concretas y otras funciones. "
		"Se distribuyen como archivos con la extensión <code>.tiresias-addon</code>.</p>"
		"<h3>Buscar complementos</h3>"
		"<p>Todos los complementos disponibles están en la tienda de complementos incorporada en Tiresias: "
		"menú de Tiresias (<kbd>Tiresias+M</kbd>), Complementos, «Tienda de complementos...». "
		"En ella puedes buscarlos por nombre, leer qué hace cada uno, instalarlos y saber cuándo hay actualizaciones.</p>"
		"<h3>Cómo se instalan</h3><ul>"
		"<li><strong>Desde la tienda</strong>: elige el complemento en la lista y pulsa «Instalar».</li>"
		"<li><strong>Desde un archivo</strong>: si tienes un archivo <code>.tiresias-addon</code>, abre el menú de Tiresias, "
		"Complementos, «Administrador de complementos...», pulsa «Instalar desde archivo...» y elige el archivo.</li>"
		"</ul>"
		"<p>Los complementos nuevos se cargan al reiniciar Tiresias; al terminar, Tiresias te pregunta si quieres reiniciarlo ahora. "
		'Instala solo complementos de fuentes de confianza. Encontrarás más detalles en el capítulo «Complementos» del <a href="manual/#complementos">manual</a>.</p>'
	)
	parts.append("</section>")
	parts.append(
		'<section aria-labelledby="manual"><h2 id="manual">Manual de usuario</h2>'
		'<p><a href="manual/">Manual de usuario de Tiresias</a>: instalación, primeros pasos, todas las órdenes y opciones. '
		"También está en el propio Tiresias, en el menú Ayuda.</p></section>"
	)
	parts.append(
		'<section aria-labelledby="requisitos"><h2 id="requisitos">Requisitos</h2><ul>'
		"<li>Windows 10 o Windows 11 de 64 bits.</li>"
		"<li>Unos 250 MB de espacio libre.</li>"
		"<li>No necesita nada más: Python, las bibliotecas y la voz eSpeak NG vienen incluidos.</li>"
		"<li>Si Windows avisa de que el archivo no es habitual (SmartScreen) o lo bloquea Control inteligente de aplicaciones, "
		"consulte el apartado de instalación del manual.</li>"
		"</ul></section>"
	)
	# Si las descargas actuales son libres, las versiones anteriores con
	# componentes propietarios (Eloquence) no se listan: los archivos siguen en
	# el servidor y en versiones.json (decisión del usuario, 8-10-2026).
	older = [v for v in versions if v is not latest and (includesProprietary or not v.get("proprietary"))]
	if older:
		parts.append('<section aria-labelledby="anteriores"><h2 id="anteriores">Versiones anteriores</h2><ul>')
		for v in older:
			f = (v.get("files") or {})
			links = ", ".join(f'<a href="{_e(x["url"])}">{_e(KIND_LABELS[k].split(" (")[0].lower())}</a>' for k, x in f.items() if k in KIND_LABELS)
			canal = " (prueba)" if v.get("channel") == "beta" else ""
			parts.append(f"<li>Tiresias {_e(v['version'])}{canal}, {_e(v.get('date', ''))}: {links}.</li>")
		parts.append("</ul></section>")
	parts.append(
		'<section aria-labelledby="tecnico"><h2 id="tecnico">Para administradores</h2>'
		f'<p>Tiresias consulta <a href="{updates.UPDATE_MANIFEST}">{updates.UPDATE_MANIFEST}</a> para las actualizaciones y '
		f'<a href="{updates.CATALOG_FILE}">{updates.CATALOG_FILE}</a> para la tienda. El historial está en '
		f'<a href="{updates.VERSIONS_FILE}">{updates.VERSIONS_FILE}</a>.</p></section>'
	)
	body = "\n".join(parts)
	return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tiresias: lector de pantalla para Windows</title>
<meta name="description" content="Tiresias, lector de pantalla libre para Windows en español: descargas, novedades, complementos y manual.">
<style>
html {{ font-size: 112.5%; }}
body {{ background: #000; color: #fff; font-family: "Segoe UI", Verdana, Arial, sans-serif; line-height: 1.6; margin: 0 auto; max-width: 50em; padding: 0 1em 2em; }}
a {{ color: #ffe066; }}
a:focus, a:hover {{ outline: 3px solid #fff; outline-offset: 2px; }}
h1 {{ font-size: 2.2em; margin: 0.6em 0 0.2em; }}
h2 {{ border-bottom: 2px solid #666; margin-top: 1.6em; }}
h3 {{ margin-bottom: 0.2em; }}
code {{ word-break: break-all; font-size: 0.9em; }}
ul {{ padding-left: 1.3em; }}
li {{ margin-bottom: 0.6em; }}
.saltar {{ position: absolute; left: -999em; }}
.saltar:focus {{ position: static; }}
footer {{ border-top: 1px solid #666; margin-top: 2em; padding-top: 1em; text-align: center; }}
</style>
</head>
<body>
<a class="saltar" href="#contenido">Saltar al contenido</a>
<header>
<h1>Tiresias</h1>
<p>Lector de pantalla libre para Windows, en español.</p>
<nav aria-label="Secciones"><ul>
<li><a href="#descargas">Descargas</a></li>
<li><a href="#novedades">Novedades</a></li>
<li><a href="#complementos">Complementos</a></li>
<li><a href="#manual">Manual</a></li>
<li><a href="#requisitos">Requisitos</a></li>
</ul></nav>
</header>
<main id="contenido">
<section aria-labelledby="que-es"><h2 id="que-es">Qué es Tiresias</h2>
<p>Tiresias lee en voz alta y en braille lo que hay en la pantalla para que las personas ciegas o con baja visión puedan usar Windows y sus programas con el teclado: navegadores, correo, documentos, mensajería y mucho más. Se actualiza solo y tiene una tienda de complementos.</p>
</section>
{body}
</main>
<footer><p>{SIGNATURE}</p></footer>
</body>
</html>
"""


# ====================================================================== publicación
@dataclass
class Release:
	version: str
	files: dict  # tipo -> ruta local (installer, portable, source)
	addonPackages: list = field(default_factory=list)
	channel: str = "estable"
	notes: str = ""
	minWindows: str = DEFAULT_MIN_WINDOWS
	date: str = ""
	includeProprietary: bool = False
	newsHtml: str = ""
	#: Publicar en la tienda los complementos propietarios aunque el programa
	#: no los lleve (``None``: lo mismo que ``includeProprietary``).
	storeProprietary: bool | None = None
	manualHtml: str = ""


def publish(dest: str, rel: Release, simulate: bool = False, repoDocs: str | None = None) -> Writer:
	"""Publica ``rel`` en ``dest``. Devuelve el :class:`Writer` con las acciones."""
	w = Writer(dest, simulate)
	date = rel.date or datetime.date.today().isoformat()
	store = rel.includeProprietary if rel.storeProprietary is None else rel.storeProprietary
	if not simulate:
		os.makedirs(dest, exist_ok=True)
	# Descargas de la versión.
	history = readJson(w.path(updates.VERSIONS_FILE), {})
	previous = next((v for v in history.get("versions") or [] if v.get("version") == rel.version), {})
	# Los paquetes que no se vuelven a generar (por ejemplo, con --sin-instalador)
	# conservan los ya publicados de esta versión.
	files = {k: v for k, v in (previous.get("files") or {}).items() if os.path.isfile(w.path(v.get("url", "")))}
	for kind in FILE_KINDS:
		src = rel.files.get(kind)
		if not src:
			continue
		if not os.path.isfile(src):
			raise SystemExit(f"No existe {src}")
		if not rel.includeProprietary and kind != "installer":
			with zipfile.ZipFile(src) as z:
				bad = [n for n in z.namelist() if isProprietaryName(n)]
			if bad:
				raise SystemExit(f"{src} contiene archivos propietarios: {', '.join(bad[:5])}")
		name = KIND_NAMES[kind].format(v=rel.version)
		relPath = f"{updates.DOWNLOADS_DIR}/{rel.version}/{name}"
		digest = sha256(src)
		w.copyFile(src, relPath, digest)
		w.writeText(relPath + ".sha256", shaLine(digest, name))
		files[kind] = {"name": name, "url": relPath, "sha256": digest, "size": os.path.getsize(src)}
	files = {k: files[k] for k in FILE_KINDS if k in files}
	entry = {
		"version": rel.version,
		"channel": rel.channel,
		"date": previous.get("date") if previous.get("files") == files and previous.get("date") else date,
		"minWindows": rel.minWindows,
		"notes": rel.notes or previous.get("notes") or f"Tiresias {rel.version}: consulte las novedades.",
		"notesUrl": updates.NEWS_FILE,
		"proprietary": bool(rel.includeProprietary),
		"files": files,
	}
	history = updateHistory(history, entry)
	w.writeText(updates.VERSIONS_FILE, dumpJson(history))
	w.writeText(updates.UPDATE_MANIFEST, dumpJson(buildManifest(history)))
	# Complementos.
	addonsRoot = w.path("complementos")
	if not store:
		for addonId in sorted(PROPRIETARY_ADDONS):
			if os.path.isdir(os.path.join(addonsRoot, addonId)):
				print(f"AVISO: se retira el complemento propietario «{addonId}» de la web (publique con --incluir-propietario para mantenerlo).")
				w.removeTree(f"complementos/{addonId}")
	for pkg in rel.addonPackages:
		if not store and isProprietaryPackage(pkg):
			print(f"Complemento propietario omitido: {os.path.basename(pkg)}")
			continue
		m = packageManifest(pkg)
		addonId, version = str(m["id"]), str(m.get("version", "0"))
		name = f"{addonId}-{version}{addons.ADDON_EXTENSION}"
		relPath = f"complementos/{addonId}/{name}"
		digest = sha256(pkg)
		w.copyFile(pkg, relPath, digest)
		w.writeText(relPath + ".sha256", shaLine(digest, name))
	previousCatalog = readJson(w.path(updates.CATALOG_FILE), {})
	if simulate:
		# En simulación los paquetes nuevos no están en el destino: se calcula con una copia temporal.
		catalog = _simulatedCatalog(addonsRoot, rel, previousCatalog, date)
	else:
		catalog = buildCatalog(addonsRoot, previousCatalog, date, store)
	w.writeText(updates.CATALOG_FILE, dumpJson(catalog))
	# Páginas.
	if rel.newsHtml and os.path.isfile(rel.newsHtml):
		with open(rel.newsHtml, encoding="utf-8") as f:
			w.writeText(updates.NEWS_FILE, f.read())
	if rel.manualHtml and os.path.isfile(rel.manualHtml):
		with open(rel.manualHtml, encoding="utf-8") as f:
			w.writeText("manual/index.html", f.read())
	anyProprietary = rel.includeProprietary or any(v.get("proprietary") for v in history["versions"])
	w.writeText("index.html", buildIndex(history, catalog, includesProprietary=rel.includeProprietary))
	w.writeText(".htaccess", HTACCESS)
	if anyProprietary and not rel.includeProprietary:
		olds = [v["version"] for v in history["versions"] if v.get("proprietary")]
		print(f"AVISO: estas versiones publicadas antes incluyen componentes propietarios: {', '.join(olds)}")
	# Copias de referencia en docs (el catálogo local que acompaña al programa).
	if repoDocs and not simulate:
		_writeIfChanged(os.path.join(repoDocs, "catalogo_complementos.json"), dumpJson(catalog))
		_writeIfChanged(os.path.join(repoDocs, "actualizacion.json"), dumpJson(buildManifest(history)))
	return w


def _simulatedCatalog(addonsRoot: str, rel: Release, previous: dict, date: str) -> dict:
	import tempfile

	tmp = tempfile.mkdtemp(prefix="tiresias_publicar_")
	try:
		root = os.path.join(tmp, "complementos")
		if os.path.isdir(addonsRoot):
			shutil.copytree(addonsRoot, root)
		store = rel.includeProprietary if rel.storeProprietary is None else rel.storeProprietary
		for pkg in rel.addonPackages:
			if not store and isProprietaryPackage(pkg):
				continue
			m = packageManifest(pkg)
			folder = os.path.join(root, str(m["id"]))
			os.makedirs(folder, exist_ok=True)
			shutil.copyfile(pkg, os.path.join(folder, f"{m['id']}-{m.get('version', '0')}{addons.ADDON_EXTENSION}"))
		return buildCatalog(root, previous, date, store)
	finally:
		shutil.rmtree(tmp, ignore_errors=True)


def _writeIfChanged(path: str, text: str) -> None:
	try:
		with open(path, encoding="utf-8") as f:
			if f.read() == text:
				return
	except OSError:
		pass
	with open(path, "w", encoding="utf-8", newline="\n") as f:
		f.write(text)
	print(f"Actualizado {os.path.relpath(path, ROOT)}")


def tree(folder: str, prefix: str = "") -> list[str]:
	"""Árbol de la carpeta publicada (para el informe final)."""
	lines = []
	try:
		names = sorted(os.listdir(folder), key=lambda n: (not os.path.isdir(os.path.join(folder, n)), n.lower()))
	except OSError:
		return lines
	for i, name in enumerate(names):
		p = os.path.join(folder, name)
		last = i == len(names) - 1
		size = "" if os.path.isdir(p) else f" ({os.path.getsize(p)} bytes)"
		lines.append(f"{prefix}{'└── ' if last else '├── '}{name}{size}")
		if os.path.isdir(p):
			lines.extend(tree(p, prefix + ("    " if last else "│   ")))
	return lines


# ====================================================================== GitHub
#: Versiones fijas de GitHub (las mismas etiquetas que lee el cliente).
GITHUB_DIST_TAG = updates.GITHUB_DIST_TAG
GITHUB_ADDONS_TAG = updates.GITHUB_ADDONS_TAG
GITHUB_CATALOG = updates.GITHUB_CATALOG_FILE

GH_MISSING = (
	"No se encuentra la herramienta gh (GitHub CLI), necesaria para publicar en GitHub.\n"
	"Instálela (https://cli.github.com/ o «winget install GitHub.cli»), inicie sesión con «gh auth login»\n"
	"o publique solo en el servidor con --solo-servidor."
)
GH_NO_SESSION = (
	"gh (GitHub CLI) no tiene ninguna sesión iniciada en github.com: ejecute «gh auth login»\n"
	"(con permiso «repo») o publique solo en el servidor con --solo-servidor."
)

DIST_NOTES = (
	"Archivos que usa Tiresias para buscar actualizaciones y para la tienda de complementos: "
	"`actualizacion.json` (la última versión publicada), `versiones.json` (el historial) y `catalogo.json` "
	"(el catálogo de la tienda). Se sustituyen en cada publicación.\n\n"
	"No hace falta descargarlos: para instalar Tiresias, descargue el instalador de la última versión."
)
ADDONS_NOTES = (
	"Paquetes de los complementos de la tienda de Tiresias, con su suma SHA-256 (archivos `.sha256`).\n\n"
	"Se instalan desde la tienda incorporada en Tiresias (menú de Tiresias, Complementos, «Tienda de complementos...») "
	"o, con un paquete descargado, desde el administrador de complementos, «Instalar desde archivo...».\n\n"
	"Los complementos con componentes propietarios no se publican aquí."
)


def githubUrl(repo: str, tag: str, name: str) -> str:
	return updates.githubAssetUrl(tag, name, repo)


def _quoteArg(a: str) -> str:
	return f'"{a}"' if (" " in a or not a) else a


@dataclass
class GitHub:
	"""Publica con ``gh`` en las versiones de un repositorio o, con ``simulate``,
	solo cuenta lo que haría (sin llamar nunca a ``gh``)."""

	repo: str
	simulate: bool = False
	exe: str = "gh"
	actions: list[str] = field(default_factory=list)
	_assets: dict = field(default_factory=dict)
	#: Lo último publicado en «distribucion» (para el informe y las pruebas).
	lastManifest: dict = field(default_factory=dict)
	lastCatalog: dict = field(default_factory=dict)

	def run(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
		try:
			proc = subprocess.run([self.exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
		except FileNotFoundError:
			raise SystemExit(GH_MISSING) from None
		if check and proc.returncode != 0:
			detail = (proc.stderr or proc.stdout or "").strip()
			raise SystemExit(f"Error de gh al ejecutar «gh {' '.join(args[:3])}»: {detail or f'código {proc.returncode}'}")
		return proc

	def _log(self, text: str) -> None:
		line = f"{'[simulación] ' if self.simulate else ''}{text}"
		self.actions.append(line)
		print(line)

	def change(self, args: list[str], description: str) -> None:
		"""Una orden que cambia GitHub: en simulación solo se lista."""
		self._log(f"{description}: gh {' '.join(_quoteArg(os.path.basename(a) if os.path.isabs(a) else a) for a in args)}")
		if not self.simulate:
			self.run(args)

	def checkReady(self) -> None:
		"""Comprueba que ``gh`` está, tiene sesión y ve el repositorio (no en simulación)."""
		if self.simulate:
			return
		self.run(["--version"])
		auth = self.run(["auth", "status", "--hostname", "github.com"], check=False)
		if auth.returncode != 0:
			raise SystemExit(GH_NO_SESSION)
		repo = self.run(["repo", "view", self.repo, "--json", "name"], check=False)
		if repo.returncode != 0:
			detail = (repo.stderr or repo.stdout or "").strip()
			raise SystemExit(
				f"No se encuentra el repositorio {self.repo} en GitHub o la sesión de gh no tiene acceso a él ({detail}).\n"
				f"Créelo primero (por ejemplo «gh repo create {self.repo} --public --source . --push») o corrija «github.repo» en tools/publicar.json."
			)

	def releaseAssets(self, tag: str) -> dict[str, int] | None:
		"""Recursos de la versión ``tag`` (``{nombre: tamaño}``); ``None`` si no existe (o en simulación)."""
		if self.simulate:
			return None
		if tag in self._assets:
			return self._assets[tag]
		proc = self.run(["release", "view", tag, "--repo", self.repo, "--json", "assets"], check=False)
		if proc.returncode != 0:
			detail = (proc.stderr or proc.stdout or "").strip()
			if "not found" in detail.lower():
				self._assets[tag] = None
				return None
			raise SystemExit(f"Error de gh al leer la versión {tag} de {self.repo}: {detail}")
		try:
			data = json.loads(proc.stdout or "{}")
		except ValueError:
			data = {}
		assets = {str(a.get("name")): int(a.get("size") or 0) for a in data.get("assets") or [] if isinstance(a, dict)}
		self._assets[tag] = assets
		return assets

	def downloadAsset(self, tag: str, name: str, folder: str) -> str | None:
		"""Descarga un recurso publicado (``None`` si no está). En simulación no se lee nada."""
		if self.simulate:
			self._log(f"se leería {name} de la versión «{tag}» (en la simulación se parte de cero)")
			return None
		assets = self.releaseAssets(tag)
		if not assets or name not in assets:
			return None
		os.makedirs(folder, exist_ok=True)
		self.run(["release", "download", tag, "--repo", self.repo, "--pattern", name, "--dir", folder, "--clobber"])
		path = os.path.join(folder, name)
		return path if os.path.isfile(path) else None

	def ensureRelease(
		self,
		tag: str,
		title: str,
		notesFile: str,
		files: list[str],
		prerelease: bool,
		latest: bool | None = None,
		editIfExists: bool = True,
	) -> None:
		"""Crea la versión con ``files`` o, si ya existe, actualiza sus notas y sustituye los recursos."""
		assets = self.releaseAssets(tag)
		latestArgs = [] if latest is None or prerelease else (["--latest"] if latest else ["--latest=false"])
		if assets is None:
			args = ["release", "create", tag, *files, "--repo", self.repo, "--title", title, "--notes-file", notesFile]
			args += ["--prerelease"] if prerelease else latestArgs
			self.change(args, f"crear la versión «{tag}»" + (" (o actualizarla si ya existe)" if self.simulate else ""))
			if not self.simulate:
				self._assets[tag] = {os.path.basename(f): os.path.getsize(f) for f in files}
			return
		if editIfExists:
			args = ["release", "edit", tag, "--repo", self.repo, "--title", title, "--notes-file", notesFile, f"--prerelease={'true' if prerelease else 'false'}"]
			self.change(args + latestArgs, f"actualizar el título y las notas de la versión «{tag}»")
		self.upload(tag, files)

	def upload(self, tag: str, files: list[str]) -> None:
		if not files:
			return
		names = ", ".join(os.path.basename(f) for f in files)
		self.change(["release", "upload", tag, *files, "--repo", self.repo, "--clobber"], f"subir a la versión «{tag}» ({names})")
		if not self.simulate and self._assets.get(tag) is not None:
			self._assets[tag].update({os.path.basename(f): os.path.getsize(f) for f in files})


class _NewsToMarkdown(HTMLParser):
	"""Convierte a Markdown el apartado ``<h2 id="v1-0-13">`` de docs/novedades.html."""

	def __init__(self, anchor: str) -> None:
		super().__init__(convert_charrefs=True)
		self.anchor = anchor
		self.inside = False
		self.done = False
		self.out: list[str] = []
		self.lists = 0
		self.href: list[str | None] = []
		self.skipTitle = False

	def handle_starttag(self, tag: str, attrs) -> None:
		a = dict(attrs)
		if tag == "h2":
			if self.inside:
				self.inside, self.done = False, True
			elif not self.done and a.get("id") == self.anchor:
				self.inside, self.skipTitle = True, True
			return
		if not self.inside:
			return
		if tag in ("h3", "h4"):
			self.out.append("\n\n" + "#" * (3 if tag == "h3" else 4) + " ")
		elif tag == "p":
			self.out.append("\n\n")
		elif tag in ("ul", "ol"):
			self.lists += 1
			if self.lists == 1:
				self.out.append("\n")
		elif tag == "li":
			self.out.append("\n" + "  " * (self.lists - 1) + "- ")
		elif tag in ("strong", "b"):
			self.out.append("**")
		elif tag in ("em", "i"):
			self.out.append("*")
		elif tag == "code":
			self.out.append("`")
		elif tag == "br":
			self.out.append("  \n")
		elif tag == "a":
			href = a.get("href") or ""
			self.href.append(href if href.lower().startswith(("http://", "https://")) else None)
			if self.href[-1]:
				self.out.append("[")

	def handle_endtag(self, tag: str) -> None:
		if tag == "h2":
			self.skipTitle = False
			return
		if not self.inside:
			return
		if tag in ("ul", "ol"):
			self.lists = max(0, self.lists - 1)
			if not self.lists:
				self.out.append("\n")
		elif tag in ("strong", "b"):
			self.out.append("**")
		elif tag in ("em", "i"):
			self.out.append("*")
		elif tag == "code":
			self.out.append("`")
		elif tag == "a" and self.href:
			href = self.href.pop()
			if href:
				self.out.append(f"]({href})")

	def handle_data(self, data: str) -> None:
		if not self.inside or self.skipTitle:
			return
		text = re.sub(r"\s+", " ", data).replace("<", "&lt;")
		if self.out and self.out[-1].endswith(("\n", "- ", "# ")):
			text = text.lstrip()
		self.out.append(text)

	def markdown(self) -> str:
		text = "".join(self.out)
		text = re.sub(r"[ \t]+\n", "\n", text)
		text = re.sub(r"\n{3,}", "\n\n", text)
		return text.strip()


def newsMarkdown(newsHtml: str, version: str) -> str:
	"""Novedades de ``version`` en docs/novedades.html, en Markdown ("" si no están)."""
	if not newsHtml or not os.path.isfile(newsHtml):
		return ""
	with open(newsHtml, encoding="utf-8") as f:
		text = f.read()
	parser = _NewsToMarkdown("v" + version.replace(".", "-"))
	parser.feed(text)
	parser.close()
	return parser.markdown()


def releaseNotes(rel: "Release", files: dict) -> str:
	"""Notas de la versión de GitHub: novedades y lista de descargas con su SHA-256."""
	body = newsMarkdown(rel.newsHtml, rel.version) or rel.notes or f"Tiresias {rel.version}."
	lines = [body, "", "## Descargas", ""]
	for kind in FILE_KINDS:
		f = files.get(kind)
		if f:
			lines.append(f"- {KIND_LABELS[kind]}: `{f['name']}` ({_mb(f['size'])}). SHA-256: `{f['sha256']}`")
	lines += ["", "Tiresias se actualiza solo desde el menú Ayuda, «Buscar actualización...». Junto a cada archivo está su `.sha256` para comprobar la descarga."]
	return "\n".join(lines) + "\n"


def githubAddonPackages(addonPackages: list[str], serverDest: str | None = None) -> dict[tuple[str, str], str]:
	"""Paquetes de complementos para GitHub, SIN los propietarios: ``{(id, versión): ruta}``.

	Además de los de esta publicación, las versiones anteriores ya publicadas en
	el servidor (``<destino>/complementos/<id>/``), para que GitHub tenga el
	mismo historial. Con la misma versión manda el paquete de esta publicación.
	"""
	found: dict[tuple[str, str], str] = {}
	root = os.path.join(serverDest, "complementos") if serverDest else ""
	if root and os.path.isdir(root):
		for addonId in sorted(os.listdir(root)):
			folder = os.path.join(root, addonId)
			if not os.path.isdir(folder):
				continue
			for fn in sorted(os.listdir(folder)):
				if fn.endswith(addons.ADDON_EXTENSION):
					path = os.path.join(folder, fn)
					try:
						m = packageManifest(path)
					except (OSError, ValueError, KeyError, zipfile.BadZipFile):
						continue
					found[(str(m.get("id") or addonId), str(m.get("version", "0")))] = path
	for pkg in addonPackages:
		m = packageManifest(pkg)
		found[(str(m["id"]), str(m.get("version", "0")))] = pkg
	out = {}
	for key, path in sorted(found.items()):
		if key[0] in PROPRIETARY_ADDONS or isProprietaryPackage(path):
			continue
		out[key] = path
	return out


_VERSION_FIELDS = ("version", "url", "sha256", "size", "minApiVersion", "lastTestedApiVersion", "changelog", "date")


def buildGithubCatalog(packages: dict[tuple[str, str], str], previous: dict, date: str, repo: str, work: str) -> dict:
	"""Catálogo de GitHub: los paquetes de ``packages`` (sin propietarios) con URL
	absolutas a la versión «complementos», más las versiones que ya estaban en
	GitHub (``previous``) aunque no estén aquí."""
	root = os.path.join(work, "catalogo")
	shutil.rmtree(root, ignore_errors=True)
	for (addonId, version), path in packages.items():
		if addonId in PROPRIETARY_ADDONS or isProprietaryPackage(path):
			continue
		folder = os.path.join(root, addonId)
		os.makedirs(folder, exist_ok=True)
		shutil.copyfile(path, os.path.join(folder, f"{addonId}-{version}{addons.ADDON_EXTENSION}"))
	catalog = buildCatalog(root, previous, date, False)

	def absolute(item: dict) -> None:
		url = str(item.get("url") or "")
		if url and "://" not in url:
			item["url"] = githubUrl(repo, GITHUB_ADDONS_TAG, url.rsplit("/", 1)[-1])

	for item in catalog["addons"]:
		absolute(item)
		for v in item.get("versions") or []:
			absolute(v)
	byId = {a["id"]: a for a in catalog["addons"]}
	for prev in previous.get("addons") or []:
		if not isinstance(prev, dict) or not prev.get("id") or prev.get("proprietary") or str(prev["id"]) in PROPRIETARY_ADDONS:
			continue
		versions = [v for v in prev.get("versions") or [] if isinstance(v, dict) and "://" in str(v.get("url") or "")]
		current = byId.get(str(prev["id"]))
		if current is None:
			if "://" in str(prev.get("url") or ""):
				catalog["addons"].append(prev)
				byId[str(prev["id"])] = prev
			continue
		known = {str(v.get("version")) for v in current["versions"]}
		extra = [v for v in versions if str(v.get("version")) not in known]
		if not extra:
			continue
		current["versions"] = sorted(current["versions"] + extra, key=lambda v: updates.versionKey(str(v["version"])), reverse=True)
		top = current["versions"][0]
		if str(top["version"]) != str(current["version"]):
			current.update({k: top[k] for k in _VERSION_FIELDS if k in top})
	catalog["addons"].sort(key=lambda a: str(a["id"]))
	return catalog


def _stageAsset(src: str, folder: str, name: str, digest: str, simulate: bool = False) -> list[str]:
	"""Copia ``src`` como ``name`` (el nombre del recurso en GitHub) con su .sha256."""
	dest = os.path.join(folder, name)
	if simulate:
		return [dest, dest + ".sha256"]
	os.makedirs(folder, exist_ok=True)
	shutil.copyfile(src, dest)
	with open(dest + ".sha256", "w", encoding="utf-8", newline="\n") as f:
		f.write(shaLine(digest, name))
	return [dest, dest + ".sha256"]


def _hasAsset(assets: dict | None, name: str, size: int) -> bool:
	return bool(assets) and assets.get(name) == size and (name + ".sha256") in assets


def publishGithub(rel: "Release", repo: str, simulate: bool = False, serverDest: str | None = None, gh: GitHub | None = None) -> GitHub:
	"""Publica ``rel`` en las versiones de GitHub de ``repo`` (idempotente).

	1. ``v<versión>``: instalador, portable, código fuente y sus .sha256, con
	   las novedades de esa versión como notas. Los recursos que ya están
	   iguales no se vuelven a subir; los que cambian se sustituyen.
	2. ``complementos``: los paquetes no propietarios nuevos o cambiados.
	3. ``distribucion`` (lo último, para que el manifiesto nunca apunte a
	   recursos que aún no están): ``actualizacion.json``, ``versiones.json``
	   y ``catalogo.json`` con URL absolutas.

	Los complementos propietarios (Eloquence, la voz Álvaro...) y la variante
	del programa con Eloquence no se publican nunca en GitHub.
	"""
	if rel.includeProprietary:
		raise SystemExit(
			"La variante con componentes propietarios (Eloquence) no se publica nunca en GitHub.\n"
			"Publique con --sin-propietario o solo en el servidor con --solo-servidor."
		)
	gh = gh or GitHub(repo, simulate)
	gh.checkReady()
	date = rel.date or datetime.date.today().isoformat()
	work = tempfile.mkdtemp(prefix="tiresias_github_")
	try:
		# 0. Lo ya publicado en GitHub: historial y catálogo.
		prevDir = os.path.join(work, "anterior")
		history = readJson(gh.downloadAsset(GITHUB_DIST_TAG, updates.VERSIONS_FILE, prevDir) or "", {})
		prevCatalog = readJson(gh.downloadAsset(GITHUB_DIST_TAG, GITHUB_CATALOG, prevDir) or "", {})
		history = history if isinstance(history, dict) else {}
		prevCatalog = prevCatalog if isinstance(prevCatalog, dict) else {}
		# 1. La versión del programa.
		tag = f"v{rel.version}"
		assets = gh.releaseAssets(tag)
		previous = next((v for v in history.get("versions") or [] if isinstance(v, dict) and v.get("version") == rel.version), {})
		files = {k: v for k, v in (previous.get("files") or {}).items() if k in FILE_KINDS and assets and v.get("name") in assets}
		upload: list[str] = []
		for kind in FILE_KINDS:
			src = rel.files.get(kind)
			if not src:
				continue
			if not os.path.isfile(src):
				raise SystemExit(f"No existe {src}")
			if kind != "installer":
				with zipfile.ZipFile(src) as z:
					bad = [n for n in z.namelist() if isProprietaryName(n)]
				if bad:
					raise SystemExit(f"{src} contiene archivos propietarios; no se publica en GitHub: {', '.join(bad[:5])}")
			name = KIND_NAMES[kind].format(v=rel.version)
			digest, size = sha256(src), os.path.getsize(src)
			if not ((previous.get("files") or {}).get(kind, {}).get("sha256") == digest and _hasAsset(assets, name, size)):
				upload += _stageAsset(src, os.path.join(work, tag), name, digest, gh.simulate)
			files[kind] = {"name": name, "url": githubUrl(repo, tag, name), "sha256": digest, "size": size}
		files = {k: files[k] for k in FILE_KINDS if k in files}
		if not files:
			raise SystemExit(f"No hay ningún paquete de Tiresias {rel.version} que publicar en GitHub")
		entry = {
			"version": rel.version,
			"channel": rel.channel,
			"date": previous.get("date") if previous.get("files") == files and previous.get("date") else date,
			"minWindows": rel.minWindows,
			"notes": rel.notes or previous.get("notes") or f"Tiresias {rel.version}: consulte las novedades.",
			"notesUrl": updates.githubReleasePageUrl(tag, repo),
			"proprietary": False,
			"files": files,
		}
		history = updateHistory(history, entry)
		stable = [v for v in history["versions"] if v.get("channel", "estable") == "estable"]
		isLatest = rel.channel == "estable" and bool(stable) and stable[0]["version"] == rel.version
		notesPath = os.path.join(work, f"notas-{tag}.md")
		notes = releaseNotes(rel, files)
		with open(notesPath, "w", encoding="utf-8", newline="\n") as f:
			f.write(notes)
		if gh.simulate:
			print(f"[simulación] notas de la versión «{tag}»:\n" + "\n".join("    " + line for line in notes.splitlines()))
		gh.ensureRelease(tag, f"Tiresias {rel.version}", notesPath, upload, prerelease=rel.channel == "beta", latest=isLatest)
		# 2. Complementos (nunca los propietarios).
		packages = githubAddonPackages(rel.addonPackages, serverDest)
		catalog = buildGithubCatalog(packages, prevCatalog, date, repo, work)
		addonAssets = gh.releaseAssets(GITHUB_ADDONS_TAG)
		prevSha = {
			(str(a.get("id")), str(v.get("version"))): str(v.get("sha256") or "")
			for a in prevCatalog.get("addons") or []
			if isinstance(a, dict)
			for v in (a.get("versions") or [a])
			if isinstance(v, dict)
		}
		upload = []
		for (addonId, version), path in packages.items():
			name = f"{addonId}-{version}{addons.ADDON_EXTENSION}"
			digest = sha256(path)
			if prevSha.get((addonId, version)) == digest and _hasAsset(addonAssets, name, os.path.getsize(path)):
				continue
			upload += _stageAsset(path, os.path.join(work, GITHUB_ADDONS_TAG), name, digest, gh.simulate)
		addonsNotes = os.path.join(work, "notas-complementos.md")
		with open(addonsNotes, "w", encoding="utf-8", newline="\n") as f:
			f.write(ADDONS_NOTES + "\n")
		gh.ensureRelease(GITHUB_ADDONS_TAG, "Complementos de la tienda de Tiresias", addonsNotes, upload, prerelease=True, editIfExists=False)
		# 3. Distribución: manifiesto, historial y catálogo (siempre se sustituyen).
		distDir = os.path.join(work, GITHUB_DIST_TAG)
		os.makedirs(distDir, exist_ok=True)
		dist = []
		for name, obj in ((updates.UPDATE_MANIFEST, buildManifest(history)), (updates.VERSIONS_FILE, history), (GITHUB_CATALOG, catalog)):
			path = os.path.join(distDir, name)
			with open(path, "w", encoding="utf-8", newline="\n") as f:
				f.write(dumpJson(obj))
			dist.append(path)
		distNotes = os.path.join(work, "notas-distribucion.md")
		with open(distNotes, "w", encoding="utf-8", newline="\n") as f:
			f.write(DIST_NOTES + "\n")
		gh.ensureRelease(GITHUB_DIST_TAG, "Distribución de Tiresias (archivos del actualizador)", distNotes, dist, prerelease=True, editIfExists=False)
		gh.lastManifest = buildManifest(history)
		gh.lastCatalog = catalog
	finally:
		shutil.rmtree(work, ignore_errors=True)
	return gh


# ====================================================================== línea de órdenes
#: Configuración de la publicación: ``incluirPropietario`` (decisión del usuario
#: sobre Eloquence, que evita la confirmación de cada vez), ``destino`` y
#: ``github`` (``{"repo": "propietario/nombre", "publicar": true}``).
CONFIG_FILE = os.path.join(ROOT, "tools", "publicar.json")
#: Ajustes de este equipo (por ejemplo «destino»): no se suben al repositorio.
LOCAL_CONFIG_FILE = os.path.join(ROOT, "tools", "publicar.local.json")


def loadConfig(path: str) -> dict:
	data = readJson(path, {})
	return data if isinstance(data, dict) else {}


def confirmProprietary(args) -> bool:
	print(
		"\nAVISO LEGAL: el complemento Eloquence contiene bibliotecas propietarias de IBM/Nuance\n"
		"(ECI.DLL y los archivos .SYN). Publicarlas en una web pública es redistribuir software\n"
		"propietario sin licencia. Si continúa, usted asume toda la responsabilidad.\n"
	)
	if args.acepto_responsabilidad:
		print("Confirmado con --acepto-responsabilidad.")
		return True
	try:
		answer = input("Escriba ASUMO LA RESPONSABILIDAD para continuar: ")
	except EOFError:
		return False
	return answer.strip().upper() == "ASUMO LA RESPONSABILIDAD"


def main(argv: list[str] | None = None) -> int:
	p = argparse.ArgumentParser(description="Publica Tiresias en la carpeta del servidor de distribución y en GitHub")
	p.add_argument("--destino", default=DEFAULT_DEST, help=f"Carpeta publicada (por defecto {DEFAULT_DEST})")
	p.add_argument("--simular", action="store_true", help="Muestra lo que haría sin escribir nada en el destino")
	p.add_argument("--canal", choices=updates.CHANNELS, default="estable", help="Canal de la versión (estable o beta)")
	p.add_argument("--notas", default="", help="Novedades en pocas palabras (para el aviso de actualización)")
	p.add_argument("--min-windows", default=DEFAULT_MIN_WINDOWS, help="Versión mínima de Windows (por ejemplo 10.0.10240)")
	p.add_argument("--programa", default=PROGRAM, help="Carpeta del programa compilado (por defecto dist\\Tiresias)")
	p.add_argument("--incluir-propietario", action="store_true", help="Publicar también Eloquence (componentes propietarios): pide confirmación")
	p.add_argument("--acepto-responsabilidad", action="store_true", help="Con --incluir-propietario: no preguntar")
	p.add_argument("--sin-instalador", action="store_true", help="No generar el instalador (solo portable y código fuente)")
	p.add_argument("--sin-docs", action="store_true", help="No actualizar docs/catalogo_complementos.json ni docs/actualizacion.json")
	p.add_argument("--sin-propietario", action="store_true", help="Publicar la variante pública sin Eloquence aunque tools/publicar.json diga lo contrario")
	p.add_argument("--config", default=CONFIG_FILE, help="Archivo de configuración de la publicación (por defecto tools/publicar.json)")
	dest = p.add_mutually_exclusive_group()
	dest.add_argument("--solo-servidor", action="store_true", help="Publicar solo en el servidor (no en GitHub)")
	dest.add_argument("--sin-github", action="store_true", help="Lo mismo que --solo-servidor")
	dest.add_argument("--solo-github", action="store_true", help="Publicar solo en GitHub (no en el servidor)")
	p.add_argument("--repositorio", default="", help="Repositorio de GitHub (propietario/nombre); por defecto «github.repo» de tools/publicar.json")
	args = p.parse_args(argv)
	config = loadConfig(args.config)
	if args.config == CONFIG_FILE:
		config.update(loadConfig(LOCAL_CONFIG_FILE))
	if config.get("destino") and args.destino == DEFAULT_DEST:
		args.destino = config["destino"]
	toServer, toGithub, repo = publicationTargets(args, config)
	include = False
	if args.sin_propietario:
		include = False
	elif config.get("incluirPropietario") is True:
		# Decisión ya tomada y registrada por el usuario en tools/publicar.json.
		print(f"AVISO: se incluyen componentes propietarios (Eloquence) por decisión registrada en {args.config}.")
		include = True
	elif args.incluir_propietario:
		if not confirmProprietary(args):
			print("Cancelado: no se publica nada.")
			return 1
		include = True
	# Complementos propietarios (Eloquence, voces de Microsoft) solo en la tienda:
	# decisión registrada por el usuario en tools/publicar.json.
	store = include or (not args.sin_propietario and config.get("propietariosEnTienda") is True)
	if store and not include:
		print(f"AVISO: los complementos propietarios se publican en la tienda (no en el programa) por decisión registrada en {args.config}.")
	version = tiresias.VERSION
	variant = "completa" if include else "publica"
	work = os.path.join(WORK, variant)
	gh = None
	if toGithub:
		if include:
			print("La variante con componentes propietarios (Eloquence) no se publica nunca en GitHub: use --sin-propietario o --solo-servidor.")
			return 1
		# Antes de compilar nada: gh tiene que estar, con sesión y con acceso al repositorio.
		gh = GitHub(repo, args.simular)
		gh.checkReady()
	where = " y ".join(([args.destino] if toServer else []) + ([f"GitHub ({repo})"] if toGithub else []))
	print(f"Publicando Tiresias {version} (canal {args.canal}, variante {variant}) en {where}")
	if args.simular:
		print("Modo simulación: no se escribe nada en el destino" + (" ni se llama a gh." if toGithub else "."))
	# 1. Complementos.
	packages = buildAddonPackages(os.path.join(work, "complementos"), store)
	# 2. Copia del programa (pública: sin Eloquence) con el catálogo local al día.
	staged = os.path.join(work, "Tiresias")
	skipped = stageProgram(args.programa, staged, include)
	print(f"Copia del programa en {staged} ({len(skipped)} elementos privados o propietarios omitidos)")
	previousCatalog = readJson(os.path.join(args.destino, *updates.CATALOG_FILE.split("/")), {})
	localCatalog = _simulatedCatalog(os.path.join(args.destino, "complementos"), Release(version, {}, packages, includeProprietary=include, storeProprietary=store), previousCatalog, datetime.date.today().isoformat())
	docsDir = os.path.join(staged, "data", "docs")
	os.makedirs(docsDir, exist_ok=True)
	localPath = os.path.join(docsDir, "catalogo_complementos.json")
	with open(localPath, "w", encoding="utf-8", newline="\n") as f:
		f.write(dumpJson(localCatalog))
	# Fecha fija (la del ejecutable): el ZIP portable sale idéntico si nada cambia.
	stamp = os.path.getmtime(os.path.join(args.programa, "Tiresias.exe"))
	os.utime(localPath, (stamp, stamp))
	# 3. Paquetes: portable, instalador y código fuente.
	files = {}
	files["portable"] = makePortableZip(staged, os.path.join(work, KIND_NAMES["portable"].format(v=version)))
	if not args.sin_instalador:
		import build_installer

		files["installer"] = build_installer.build(program=staged, output=os.path.join(work, KIND_NAMES["installer"].format(v=version)), staging=os.path.join(work, "instalador_tmp"))
		if not build_installer.verify(files["installer"]):
			print("El instalador no ha pasado la verificación")
			return 1
	import make_source_zip

	extra = [] if include else [f"data/addons/{a}" for a in PROPRIETARY_ADDONS] + proprietaryStoreFolders()
	# La copia del manifiesto contiene la suma de este mismo ZIP: no puede ir dentro.
	extra.append("docs/actualizacion.json")
	files["source"] = make_source_zip.build(work, extraExclude=extra)
	rel = Release(
		version=version,
		files=files,
		addonPackages=packages,
		channel=args.canal,
		notes=args.notas,
		minWindows=args.min_windows,
		includeProprietary=include,
		storeProprietary=store,
		newsHtml=os.path.join(ROOT, "docs", "novedades.html"),
		manualHtml=os.path.join(ROOT, "manual", "manual_usuario.html"),
	)
	if toServer:
		w = publish(args.destino, rel, simulate=args.simular, repoDocs=None if args.sin_docs else os.path.join(ROOT, "docs"))
		print(f"\nServidor: {len(w.actions)} cambios{' (simulados)' if args.simular else ''}.")
		if not args.simular:
			print(f"\n{args.destino}")
			print("\n".join(tree(args.destino)))
	if toGithub:
		print(f"\nGitHub ({repo}):")
		# El historial de complementos del servidor también va a GitHub (sin los propietarios).
		gh = publishGithub(rel, repo, simulate=args.simular, serverDest=args.destino, gh=gh)
		print(f"\nGitHub: {len(gh.actions)} acciones{' (simuladas)' if args.simular else ''}.")
		if not args.simular:
			print(f"Manifiesto: {updates.githubAssetUrl(GITHUB_DIST_TAG, updates.UPDATE_MANIFEST, repo)}")
	return 0


def publicationTargets(args, config: dict) -> tuple[bool, bool, str]:
	"""``(servidor, github, repositorio)`` según las opciones y ``tools/publicar.json``.

	Sin la sección ``github`` (o con ``"publicar": false``) se publica solo en
	el servidor, como antes de la 1.0.13; ``--solo-github`` publica en GitHub
	aunque la configuración no lo pida.
	"""
	gh = config.get("github") if isinstance(config.get("github"), dict) else {}
	repo = (getattr(args, "repositorio", "") or str(gh.get("repo") or "") or updates.GITHUB_REPO).strip().strip("/")
	if getattr(args, "solo_github", False):
		toServer, toGithub = False, True
	elif getattr(args, "solo_servidor", False) or getattr(args, "sin_github", False):
		toServer, toGithub = True, False
	else:
		toServer, toGithub = True, gh.get("publicar") is True
	if toGithub and not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
		raise SystemExit(f"Repositorio de GitHub no válido: «{repo}» (debe ser propietario/nombre)")
	return toServer, toGithub, repo


if __name__ == "__main__":
	sys.exit(main())
