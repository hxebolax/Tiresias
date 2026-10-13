"""Crea el ZIP del código fuente de Tiresias para distribuir.

Incluye el código, los complementos (WhatsApp y Eloquence), la documentación,
el manual, las pruebas, las herramientas y el ``.bat``. No incluye el entorno
virtual, las compilaciones, los adjuntos de estudio ni los datos personales
(configuración, registros, caché, etiquetas).

Uso::

	python tools/make_source_zip.py [carpeta de salida]
"""

from __future__ import annotations

import fnmatch
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import tiresias  # noqa: E402

#: Archivos y carpetas de la raíz que forman el paquete de código fuente.
INCLUDE = [
	"src",
	# data incluye los binarios ya compilados (data/controller, data/rdp).
	"data",
	# Código C de la API de control y del complemento de Escritorio remoto.
	"controller",
	"rdp",
	"tools",
	"tests",
	# Complementos que se publican solo en la tienda.
	"complementos_tienda",
	"docs",
	"manual",
	"resources",
	"Tiresias.bat",
	"requirements.txt",
	"setup_cxfreeze.py",
	"README.md",
	"LICENSE.txt",
	"LEEME.txt",
]

#: Nunca se incluyen (patrones de nombre o rutas relativas con «/»).
EXCLUDE = [
	"__pycache__",
	"*.pyc",
	"*.pyo",
	"*.tmp",
	"*.old",
	"*.log",
	"Thumbs.db",
	"desktop.ini",
	"data/config",
	"data/logs",
	"data/cache",
	"data/temp",
	"data/voices",
	"data/labels",
	"controller/build",
	"rdp/build",
	"data/speechDicts/voices",
	"data/addons/pending.json",
]


def excluded(rel: str) -> bool:
	rel = rel.replace("\\", "/")
	name = rel.rsplit("/", 1)[-1]
	for pat in EXCLUDE:
		if "/" in pat:
			if rel == pat or rel.startswith(pat + "/"):
				return True
		elif fnmatch.fnmatch(name, pat):
			return True
	return False


def main() -> None:
	build(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dist"))


def build(outDir: str, extraExclude: list[str] | None = None) -> str:
	"""Crea el ZIP en ``outDir`` y devuelve su ruta.

	``extraExclude``: rutas relativas a la raíz que se omiten (``tools/publicar.py``
	quita así los complementos propietarios de la versión pública).
	"""
	os.makedirs(outDir, exist_ok=True)
	prefix = f"Tiresias-{tiresias.VERSION}-codigo-fuente"
	out = os.path.join(outDir, prefix + ".zip")
	count = 0
	extra = [p.replace(os.sep, "/").strip("/") for p in extraExclude or []]

	def isExcluded(rel: str) -> bool:
		rel = rel.replace(os.sep, "/")
		return excluded(rel) or any(rel == p or rel.startswith(p + "/") for p in extra)

	with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
		for item in INCLUDE:
			path = os.path.join(ROOT, item)
			if os.path.isfile(path):
				z.write(path, f"{prefix}/{item}")
				count += 1
				continue
			for root, dirs, files in os.walk(path):
				relRoot = os.path.relpath(root, ROOT).replace("\\", "/")
				dirs[:] = [d for d in dirs if not isExcluded(f"{relRoot}/{d}")]
				for fn in files:
					rel = f"{relRoot}/{fn}"
					if isExcluded(rel):
						continue
					z.write(os.path.join(root, fn), f"{prefix}/{rel}")
					count += 1
		# Carpetas de datos vacías que el programa espera.
		for d in ("config", "logs", "cache", "temp", "labels", "voices", "speechDicts/voices", "sounds", "brailleTables"):
			# Fecha fija: el ZIP sale idéntico si nada cambia (publicación idempotente).
			zi = zipfile.ZipInfo(f"{prefix}/data/{d}/", date_time=(1980, 1, 1, 0, 0, 0))
			zi.external_attr = (0o40755 << 16) | 0x10
			z.writestr(zi, "")
	size = os.path.getsize(out) / (1024 * 1024)
	print(f"Código fuente empaquetado: {out} ({count} archivos, {size:.1f} MB)")
	return out


if __name__ == "__main__":
	main()
