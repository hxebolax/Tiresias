"""Compila el complemento de Escritorio remoto de Tiresias.

Necesita Visual Studio (herramientas de C++) y el SDK de Windows; usa el
mismo método que ``controller/build.py`` (vcvarsall, CRT estático).

Uso::

	python rdp/build.py            (x64 y x86)
	python rdp/build.py x64

Resultado:

- ``data/rdp/x64/tiresiasRdpClient.dll``: complemento de canal virtual
  dinámico para el cliente de Escritorio remoto de 64 bits (``mstsc.exe``).
- ``data/rdp/x86/tiresiasRdpClient.dll``: el mismo para el cliente de 32 bits
  (``SysWOW64\\mstsc.exe``).
- ``rdp/test/<arq>/rdpTestHost.exe``: programa de pruebas que simula el
  cliente de Escritorio remoto con objetos COM falsos (no se distribuye, por
  eso no va a ``data``).

El código C y el .def se quedan en ``rdp/src``.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(HERE, "src")
BUILD = os.path.join(HERE, "build")
#: Carpeta de las bibliotecas que se distribuyen (``data/rdp/<arq>``).
OUT_DIR = os.path.join(ROOT, "data", "rdp")

sys.path.insert(0, os.path.join(ROOT, "controller"))
from build import findVcvarsall  # noqa: E402  (controller/build.py)

VERSION_RC = os.path.join(ROOT, "controller", "src", "version.rc")
LIBS = "ole32.lib oleaut32.lib uuid.lib advapi32.lib kernel32.lib user32.lib"
CFLAGS = "/nologo /O2 /MT /W4 /WX /GS /Gy /guard:cf /DUNICODE /D_UNICODE"


def _versionRc(folder: str, name: str, desc: str, fileName: str) -> str:
	path = os.path.join(folder, name + "_version.rc")
	with open(path, "w", encoding="utf-8") as f:
		f.write(f'#define TCC_NAME "{name}"\n#define TCC_DESC "{desc}"\n#define TCC_FILE "{fileName}"\n')
		f.write(f'#include "{VERSION_RC}"\n')
	return path


def buildArch(arch: str, vcvars: str) -> None:
	out = os.path.join(OUT_DIR, arch)
	testOut = os.path.join(HERE, "test", arch)
	work = os.path.join(BUILD, arch)
	shutil.rmtree(work, ignore_errors=True)
	os.makedirs(work, exist_ok=True)
	os.makedirs(out, exist_ok=True)
	os.makedirs(testOut, exist_ok=True)
	rc = _versionRc(work, "tiresiasRdpClient", "Tiresias: voz y braille por Escritorio remoto", "tiresiasRdpClient.dll")
	steps = [
		f'rc /nologo /fo version.res "{rc}"',
		f'cl {CFLAGS} /c "{os.path.join(SRC, "tiresiasRdpClient.c")}"',
		f'link /nologo /DLL /OPT:REF /OPT:ICF /GUARD:CF /DEF:"{os.path.join(SRC, "tiresiasRdpClient.def")}" '
		f'/OUT:"{os.path.join(out, "tiresiasRdpClient.dll")}" /IMPLIB:"{os.path.join(work, "tiresiasRdpClient.lib")}" '
		f"tiresiasRdpClient.obj version.res {LIBS}",
		f'cl {CFLAGS} /c "{os.path.join(SRC, "rdpTestHost.c")}"',
		f'link /nologo /SUBSYSTEM:CONSOLE /OPT:REF /OUT:"{os.path.join(testOut, "rdpTestHost.exe")}" rdpTestHost.obj {LIBS}',
	]
	vcArch = "x64" if arch == "x64" else "x64_x86"
	script = os.path.join(work, "build.bat")
	with open(script, "w", encoding="mbcs") as f:
		f.write("@echo off\n")
		installer = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Microsoft Visual Studio", "Installer")
		f.write(f'set "PATH={installer};%PATH%"\n')
		f.write(f'call "{vcvars}" {vcArch} >nul\n')
		f.write("if errorlevel 1 exit /b 1\n")
		f.write(f'cd /d "{work}"\n')
		for s in steps:
			f.write(s + "\n")
			f.write("if errorlevel 1 exit /b 1\n")
	print(f"== Compilando {arch}")
	res = subprocess.run(["cmd", "/c", script], check=False)
	if res.returncode != 0:
		raise SystemExit(f"Error compilando {arch}")
	for exp in glob.glob(os.path.join(out, "*.exp")) + glob.glob(os.path.join(testOut, "*.exp")):
		os.remove(exp)


def main(argv: list[str]) -> None:
	archs = argv or ["x64", "x86"]
	vcvars = findVcvarsall()
	for arch in archs:
		if arch not in ("x64", "x86"):
			raise SystemExit(f"Arquitectura desconocida: {arch}")
		buildArch(arch, vcvars)
	shutil.rmtree(BUILD, ignore_errors=True)
	print("Compilación terminada")


if __name__ == "__main__":
	main(sys.argv[1:])
