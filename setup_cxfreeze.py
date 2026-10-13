"""Compilación de Tiresias con cx_Freeze.

Uso (lo hace Tiresias.bat, opción «Compilar»)::

	python setup_cxfreeze.py build_exe

Resultado: ``dist\\Tiresias`` con ``Tiresias.exe``, las bibliotecas de
Python (``lib``), los runtimes de Visual C++, la carpeta ``data`` limpia y el
manual de usuario.

Todo lo que Tiresias necesita va dentro de ``data`` (lo prepara
``tools/build_data.py``): la API de control (``data\\controller``), el
complemento de Escritorio remoto (``data\\rdp``), eSpeak NG
(``data\\synthDrivers\\espeak``), el auxiliar de 32 bits para SAPI 5 de 32 bits
y SAPI 4 (``data\\synthDrivers\\sapi32``, lo compila ``sapi32_host/build.py``),
liblouis (``data\\louis``), los catálogos de
traducción (``data\\locale``), los documentos (``data\\docs``) y el icono
(``data\\images``). Fuera de ``data`` solo queda lo que cx_Freeze necesita
junto al ejecutable: ``lib``, ``python3*.dll`` y las DLL del runtime de
Visual C++ (Windows las carga al arrancar el proceso, antes de que Python
pueda buscar en otra carpeta), además de las licencias, el LEEME y el manual.
"""

from __future__ import annotations

import glob
import os
import shutil
import sys

from cx_Freeze import Executable, setup

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tiresias  # noqa: E402

DIST = os.path.join(ROOT, "dist", "Tiresias")

# ------------------------------------------------------------------ archivos extra
includeFiles: list[tuple[str, str]] = []

# eSpeak NG, liblouis, los catálogos de traducción, la API de control, el
# complemento de Escritorio remoto, los documentos y el icono van a data: los
# copia tools/build_data.py al final. En lib solo queda código.

# Runtimes de Visual C++ (por si el equipo de destino no los tiene).
system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
for dll in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "concrt140.dll", "vccorlib140.dll"):
	path = os.path.join(system32, dll)
	if os.path.isfile(path):
		includeFiles.append((path, dll))

# Licencia y archivos informativos.
for fn in ("LICENSE.txt", "LEEME.txt"):
	p = os.path.join(ROOT, fn)
	if os.path.isfile(p):
		includeFiles.append((p, fn))

icon = os.path.join(ROOT, "resources", "tiresias.ico")

buildOptions = {
	"build_exe": DIST,
	"packages": [
		"tiresias",
		"comtypes",
		"wx",
		"winrt",
		"encodings",
		"asyncio",
		"json",
		"xml",
		"ctypes",
		"sqlite3",
		"code",
		"difflib",
		"wave",
		"zipfile",
		"importlib",
		"logging",
		"psutil",
		# Acceso remoto (TLS y certificado del servidor local).
		"ssl",
		"cryptography",
		"cffi",
		# Voces neuronales Piper (inferencia ONNX) y procesado de audio.
		"onnxruntime",
		"numpy",
	],
	"includes": ["comtypes.gen", "comtypes.client", "comtypes.server"],
	# espeakng_loader: su eSpeak NG ya va en data\synthDrivers\espeak (no se duplica en lib).
	"excludes": ["tkinter", "unittest", "pydoc_data", "test", "lib2to3", "idlelib", "distutils", "setuptools", "pip", "cx_Freeze", "espeakng_loader"],
	"include_files": includeFiles,
	"include_msvcr": True,
	"zip_include_packages": [],
	"zip_exclude_packages": ["*"],
	"optimize": 1,
	"silent_level": 1,
}

# Incluye todos los módulos generados de comtypes (UIA, SAPI...).
genDir = os.path.join(os.path.dirname(__import__("comtypes").__file__), "gen")
buildOptions["includes"] += ["comtypes.gen." + os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(genDir, "*.py")) if not p.endswith("__init__.py")]

executables = [
	Executable(
		os.path.join(SRC, "tiresias.pyw"),
		base="gui",
		target_name="Tiresias.exe",
		icon=icon if os.path.isfile(icon) else None,
		copyright=tiresias.COPYRIGHT,
		shortcut_name="Tiresias",
	),
	Executable(
		os.path.join(SRC, "tiresias.pyw"),
		base="console",
		target_name="Tiresias-depuracion.exe",
		icon=icon if os.path.isfile(icon) else None,
	),
]

def _flattenLicenses(dist: str) -> None:
	"""cx_Freeze deja la licencia del runtime de Visual C++ en ``share\\licenses\\vc_redist``.

	Es solo un texto de licencia: se deja junto al ejecutable como
	``LICENSE-vc_redist.txt`` (con las demás licencias) y se quita ``share``.
	"""
	share = os.path.join(dist, "share")
	src = os.path.join(share, "licenses", "vc_redist", "LICENSE.txt")
	if os.path.isfile(src):
		shutil.copy2(src, os.path.join(dist, "LICENSE-vc_redist.txt"))
		shutil.rmtree(share, ignore_errors=True)


def _fileVersion(path: str) -> tuple[int, ...]:
	"""Versión de archivo de una DLL de Windows (``()`` si no tiene)."""
	import ctypes
	from ctypes import wintypes

	ver = ctypes.windll.version
	size = ver.GetFileVersionInfoSizeW(path, None)
	if not size:
		return ()
	buf = ctypes.create_string_buffer(size)
	if not ver.GetFileVersionInfoW(path, 0, size, buf):
		return ()
	ptr, length = ctypes.c_void_p(), wintypes.UINT()
	if not ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)) or not length.value:
		return ()
	info = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint32 * 13)).contents
	ms, ls = info[2], info[3]
	return (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)


def _newestVcRuntime(dist: str) -> list[str]:
	"""Deja junto al ejecutable la versión más nueva de cada DLL del runtime de Visual C++.

	cx_Freeze (``include_msvcr``) copia su propio runtime, que puede ser más
	antiguo que el del sistema. Un proceso solo carga una copia de cada DLL (la
	de la carpeta del ejecutable), así que un complemento con bibliotecas
	compiladas con un Visual C++ más reciente (por ejemplo, el Speech SDK de las
	voces neuronales de Microsoft) fallaría con el runtime antiguo. El runtime
	de Visual C++ es compatible hacia atrás: se usa el más nuevo.
	"""
	updated = []
	for fn in sorted(os.listdir(dist)):
		low = fn.lower()
		if not (low.endswith(".dll") and "140" in low and low.startswith(("vcruntime", "msvcp", "concrt", "vccorlib", "vcomp", "vcamp"))):
			continue
		mine, system = os.path.join(dist, fn), os.path.join(system32, fn)
		if os.path.isfile(system) and _fileVersion(system) > _fileVersion(mine):
			shutil.copy2(system, mine)
			updated.append(fn)
	return updated


def runningFromDist(dist: str = DIST) -> list[int]:
	"""PID de los procesos que se ejecutan desde ``dist`` (no se puede compilar encima)."""
	try:
		import psutil
	except ImportError:
		return []
	base = os.path.normcase(os.path.abspath(dist)) + os.sep
	pids = []
	for p in psutil.process_iter(["exe"]):
		exe = p.info.get("exe") or ""
		if exe and os.path.normcase(os.path.abspath(exe)).startswith(base):
			pids.append(p.pid)
	return pids


if __name__ == "__main__":
	if os.path.isdir(DIST) and "build_exe" in sys.argv:
		busy = runningFromDist()
		if busy:
			# Borrar o sobrescribir la copia en uso dejaría una compilación a medias
			# (y al usuario sin lector si es el que está usando).
			print(f"ERROR: Tiresias se está ejecutando desde {DIST} (PID {', '.join(map(str, busy))}). Ciérralo antes de compilar.")
			sys.exit(1)
		shutil.rmtree(DIST, ignore_errors=True)
	setup(
		name="Tiresias",
		version=tiresias.VERSION,
		description="Tiresias, lector de pantalla para Windows",
		options={"build_exe": buildOptions},
		executables=executables,
	)
	if "build_exe" in sys.argv:
		import build_data

		build_data.buildCleanData(DIST)
		build_data.copyManual(DIST)
		_flattenLicenses(DIST)
		newer = _newestVcRuntime(DIST)
		if newer:
			print("Runtime de Visual C++ actualizado al del sistema: " + ", ".join(newer))
		print(f"\nCompilación terminada en {DIST}")
