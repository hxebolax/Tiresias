"""Compila el auxiliar de 32 bits para las voces SAPI 5 de 32 bits y SAPI 4.

Necesita Visual Studio (herramientas de C++ para x86) y el SDK de Windows;
usa el mismo método que ``controller/build.py`` y ``rdp/build.py``
(vcvarsall, CRT estático: no depende del runtime de Visual C++).

Uso::

	python sapi32_host/build.py

Resultado: ``data/synthDrivers/sapi32/tiresiasSapi32.exe`` (x86). La
compilación normal (``setup_cxfreeze.py`` -> ``tools/build_data.py``) copia
``data/synthDrivers`` entera, así que basta con dejar ahí el ejecutable.

El código C está en ``sapi32_host/src``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(HERE, "src")
BUILD = os.path.join(HERE, "build")
#: Carpeta del ejecutable que se distribuye.
OUT_DIR = os.path.join(ROOT, "data", "synthDrivers", "sapi32")
EXE = "tiresiasSapi32.exe"

sys.path.insert(0, os.path.join(ROOT, "controller"))
from build import findVcvarsall  # noqa: E402  (controller/build.py)

LIBS = "ole32.lib oleaut32.lib uuid.lib sapi.lib user32.lib kernel32.lib advapi32.lib"
#: C4152: conversión de puntero a función en puntero a datos (las tablas de
#: métodos COM de SAPI 4 se declaran como punteros genéricos).
CFLAGS = "/nologo /O2 /MT /W4 /WX /wd4152 /GS /Gy /guard:cf /DUNICODE /D_UNICODE"


def build(vcvars: str) -> str:
	work = os.path.join(BUILD, "x86")
	shutil.rmtree(work, ignore_errors=True)
	os.makedirs(work, exist_ok=True)
	os.makedirs(OUT_DIR, exist_ok=True)
	out = os.path.join(OUT_DIR, EXE)
	steps = [
		f'rc /nologo /fo version.res "{os.path.join(SRC, "tiresiasSapi32.rc")}"',
		f'cl {CFLAGS} /c "{os.path.join(SRC, "tiresiasSapi32.c")}"',
		f'link /nologo /SUBSYSTEM:CONSOLE /OPT:REF /OPT:ICF /GUARD:CF /DYNAMICBASE /NXCOMPAT /OUT:"{out}" tiresiasSapi32.obj version.res {LIBS}',
	]
	script = os.path.join(work, "build.bat")
	with open(script, "w", encoding="mbcs") as f:
		f.write("@echo off\n")
		installer = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Microsoft Visual Studio", "Installer")
		f.write(f'set "PATH={installer};%PATH%"\n')
		# Compilador de 64 bits que genera código x86.
		f.write(f'call "{vcvars}" x64_x86 >nul\n')
		f.write("if errorlevel 1 exit /b 1\n")
		f.write(f'cd /d "{work}"\n')
		for s in steps:
			f.write(s + "\n")
			f.write("if errorlevel 1 exit /b 1\n")
	print("== Compilando tiresiasSapi32.exe (x86)")
	res = subprocess.run(["cmd", "/c", script], check=False)
	if res.returncode != 0:
		raise SystemExit("Error compilando el auxiliar de 32 bits")
	return out


def main(argv: list[str]) -> None:
	vcvars = findVcvarsall()
	out = build(vcvars)
	shutil.rmtree(BUILD, ignore_errors=True)
	print(f"Compilación terminada: {out}")


if __name__ == "__main__":
	main(sys.argv[1:])
