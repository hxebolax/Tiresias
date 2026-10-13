"""Copia limpia de la carpeta ``data`` para la versión compilada.

Solo se copia lo que Tiresias necesita para funcionar: símbolos, sonidos,
tablas braille, complementos incluidos y los binarios y documentos que
acompañan al programa (``controller``, ``rdp``, ``synthDrivers``, ``louis``,
``locale``, ``docs`` e ``images``). No se copian la configuración del desarrollador, los registros,
la caché, los temporales, las etiquetas ni los diccionarios personales.

Todo lo que el programa necesita está dentro de ``data``; fuera solo quedan
los ejecutables, ``lib`` y las DLL de Python y del runtime de Visual C++
(cx_Freeze las necesita junto al ejecutable), las licencias, el LEEME y el
manual.

Uso::

	python tools/build_data.py <carpeta destino del programa>
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

#: Rutas (relativas a data) que se copian completas.
INCLUDE = [
	"symbols",
	"sounds",
	"brailleTables",
	"addons",
	"speechDicts/default.json",
	# API de control (x64/x86) y complemento de Escritorio remoto (x64/x86):
	# los dejan aquí controller/build.py y rdp/build.py.
	"controller",
	"rdp",
	# eSpeak NG (si no está, se toma del paquete espeakng_loader) y el auxiliar
	# de 32 bits para SAPI 5 de 32 bits y SAPI 4 (synthDrivers/sapi32, lo deja
	# aquí sapi32_host/build.py).
	"synthDrivers",
	# liblouis: biblioteca, tablas y licencia.
	"louis",
	# (data/locale se copia aparte con copyLocale: solo los .mo.)
	"docs",
	"images",
]

#: Archivos de la raíz del proyecto que van a ``data`` (origen, destino en data).
PROJECT_FILES = [
	("controller/include", "controller/include"),
	("controller/examples", "controller/examples"),
	("docs/api_control.md", "docs/api_control.md"),
	("docs/desarrollo_complementos.md", "docs/desarrollo_complementos.md"),
	("docs/novedades.html", "docs/novedades.html"),
	("docs/catalogo_complementos.json", "docs/catalogo_complementos.json"),
	("resources/tiresias.ico", "images/tiresias.ico"),
]

#: Binarios imprescindibles: se avisa si faltan.
REQUIRED = [
	("controller/x64/tiresiasControllerServer.dll", "la API de control no estará disponible (python controller/build.py)"),
	("controller/x64/tiresiasNvdaWindow.exe", "no habrá ventana ni punto de conexión de compatibilidad con NVDA (python controller/build.py)"),
	("controller/x86/tiresiasControllerClient.dll", "faltará el cliente de 32 bits de la API de control"),
	("rdp/x64/tiresiasRdpClient.dll", "no se recibirá la voz por Escritorio remoto con mstsc de 64 bits (python rdp/build.py)"),
	("rdp/x86/tiresiasRdpClient.dll", "no se recibirá la voz por Escritorio remoto con mstsc de 32 bits (python rdp/build.py)"),
	("synthDrivers/espeak/espeak-ng.dll", "la versión compilada no tendrá eSpeak NG (pip install espeakng-loader)"),
	("synthDrivers/sapi32/tiresiasSapi32.exe", "no habrá voces SAPI 5 de 32 bits ni SAPI 4 (python sapi32_host/build.py)"),
	("louis/liblouis.dll", "la versión compilada usará solo las tablas braille propias"),
	("locale/en/LC_MESSAGES/tiresias.mo", "la interfaz solo estará en español (python tools/i18n.py compilar)"),
]

#: Patrones que nunca se copian.
EXCLUDE = [
	"__pycache__",
	"*.pyc",
	"*.pyo",
	"*.tmp",
	"*.old.tmp",
	"pending.json",
	"_install.tmp",
	"*.log",
	"*.exp",
	"*.old",
	"*.ilk",
	"*.pdb",
	"Thumbs.db",
	"desktop.ini",
]

#: Carpetas vacías que deben existir en la copia limpia.
EMPTY_DIRS = [
	"config",
	"config/profiles",
	"logs",
	"cache",
	"temp",
	"labels",
	"speechDicts",
	"speechDicts/voices",
	"sounds",
	"brailleTables",
	"addons",
	# Voces Piper: se descargan desde el gestor de voces (no se distribuyen).
	"voices",
]


def _excluded(name: str) -> bool:
	return any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE)


def copyTree(src: str, dst: str) -> int:
	count = 0
	if os.path.isfile(src):
		os.makedirs(os.path.dirname(dst), exist_ok=True)
		shutil.copy2(src, dst)
		return 1
	for root, dirs, files in os.walk(src):
		dirs[:] = [d for d in dirs if not _excluded(d)]
		rel = os.path.relpath(root, src)
		target = os.path.join(dst, rel) if rel != "." else dst
		os.makedirs(target, exist_ok=True)
		for fn in files:
			if _excluded(fn):
				continue
			shutil.copy2(os.path.join(root, fn), os.path.join(target, fn))
			count += 1
	return count


def buildCleanData(appDir: str) -> None:
	dest = os.path.join(appDir, "data")
	if os.path.isdir(dest):
		shutil.rmtree(dest)
	os.makedirs(dest)
	total = 0
	for rel in INCLUDE:
		src = os.path.join(DATA, rel)
		if os.path.exists(src):
			total += copyTree(src, os.path.join(dest, rel))
	for srcRel, dstRel in PROJECT_FILES:
		src = os.path.join(ROOT, *srcRel.split("/"))
		if os.path.exists(src):
			total += copyTree(src, os.path.join(dest, *dstRel.split("/")))
		else:
			print(f"AVISO: falta {srcRel}")
	total += copyEspeak(dest)
	total += copyLocale(dest)
	for rel, consequence in REQUIRED:
		if not os.path.isfile(os.path.join(dest, *rel.split("/"))):
			print(f"AVISO: falta data/{rel}; {consequence}")
	for rel in EMPTY_DIRS:
		os.makedirs(os.path.join(dest, rel), exist_ok=True)
	with open(os.path.join(dest, "LEEME.txt"), "w", encoding="utf-8") as f:
		f.write(
			"Carpeta de datos de Tiresias.\n\n"
			"Aquí se guarda todo lo que el lector necesita o genera: configuración (config),\n"
			"perfiles, registros (logs), caché (cache), temporales (temp), complementos\n"
			"(addons), voces descargadas (voices), diccionarios de voz, símbolos, sonidos,\n"
			"tablas braille y etiquetas personalizadas.\n\n"
			"También están los componentes del programa: la API de control para juegos y\n"
			"programas (controller), el complemento de Escritorio remoto (rdp), eSpeak NG\n"
			"y el auxiliar de las voces SAPI de 32 bits (synthDrivers), liblouis y sus\n"
			"tablas braille (louis), las traducciones de la\n"
			"interfaz (locale), la documentación para desarrolladores (docs) y el icono (images).\n"
			"No los borres ni los muevas.\n\n"
			"Para hacer una copia de seguridad de tu configuración, copia esta carpeta.\n"
			"Para volver a la configuración de fábrica, borra la carpeta config.\n"
		)
	print(f"Datos limpios copiados en {dest} ({total} archivos)")


def copyLocale(dest: str) -> int:
	"""Catálogos de traducción: solo los ``.mo`` (los ``.po`` y el ``.pot`` son para traductores)."""
	src = os.path.join(DATA, "locale")
	count = 0
	if not os.path.isdir(src):
		return 0
	for lang in sorted(os.listdir(src)):
		mo = os.path.join(src, lang, "LC_MESSAGES", "tiresias.mo")
		if os.path.isfile(mo):
			count += copyTree(mo, os.path.join(dest, "locale", lang, "LC_MESSAGES", "tiresias.mo"))
	return count


def copyEspeak(dest: str) -> int:
	"""eSpeak NG del paquete ``espeakng_loader`` si ``data/synthDrivers/espeak`` no lo trae."""
	target = os.path.join(dest, "synthDrivers", "espeak")
	if os.path.isfile(os.path.join(target, "espeak-ng.dll")):
		return 0
	try:
		import espeakng_loader  # type: ignore
	except ImportError:
		return 0
	src = os.path.dirname(espeakng_loader.__file__)
	count = copyTree(os.path.join(src, "espeak-ng.dll"), os.path.join(target, "espeak-ng.dll"))
	count += copyTree(os.path.join(src, "espeak-ng-data"), os.path.join(target, "espeak-ng-data"))
	return count


def copyManual(appDir: str) -> None:
	src = os.path.join(ROOT, "manual", "manual_usuario.html")
	if os.path.isfile(src):
		shutil.copy2(src, os.path.join(appDir, "Manual de usuario.html"))
		print("Manual de usuario copiado")
	else:
		print("AVISO: no se encontró manual/manual_usuario.html")


if __name__ == "__main__":
	if len(sys.argv) != 2:
		print(__doc__)
		sys.exit(1)
	buildCleanData(sys.argv[1])
	copyManual(sys.argv[1])
