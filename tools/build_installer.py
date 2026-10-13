"""Construye el instalador de Tiresias: ``dist/Tiresias-<versión>-instalador.exe``.

Uso (lo hace ``Tiresias.bat instalador``)::

	python tools/build_installer.py [--compilar]

Pasos:

1. (con ``--compilar`` o si no existe) compila el programa con cx_Freeze en
   ``dist/Tiresias``;
2. empaqueta esa carpeta en ``Tiresias.zip`` (sin comprimir: lo comprime el
   paquete autoextraíble);
3. crea con IExpress (incluido en Windows) un ejecutable autoextraíble que
   descomprime el programa en una carpeta temporal y ejecuta
   ``Tiresias.exe --install``. Tiresias arranca hablando y muestra su diálogo
   de instalación, así que la instalación es accesible desde el principio.

Para comprobar el resultado sin instalar nada::

	python tools/build_installer.py --verificar
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import tiresias  # noqa: E402

DIST = os.path.join(ROOT, "dist")
PROGRAM = os.path.join(DIST, "Tiresias")
STAGING = os.path.join(DIST, "instalador_tmp")
OUTPUT = os.path.join(DIST, f"Tiresias-{tiresias.VERSION}-instalador.exe")
#: Carpeta temporal donde el instalador descomprime el programa.
TEMP_FOLDER = "TiresiasInstalador"

SETUP_CMD = """@echo off
rem Instalador de Tiresias: descomprime el programa y abre el diálogo de instalación.
set "D=%TEMP%\\{folder}"
if exist "%D%" rmdir /s /q "%D%"
mkdir "%D%"
tar -xf "%~dp0Tiresias.zip" -C "%D%"
if errorlevel 1 powershell -NoProfile -Command "Expand-Archive -LiteralPath '%~dp0Tiresias.zip' -DestinationPath '%D%' -Force"
start "" "%D%\\Tiresias.exe" --install
"""

SED = """[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=1
HideExtractAnimation=1
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=%InstallPrompt%
DisplayLicense=%DisplayLicense%
FinishMessage=%FinishMessage%
TargetName=%TargetName%
FriendlyName=%FriendlyName%
AppLaunched=%AppLaunched%
PostInstallCmd=%PostInstallCmd%
AdminQuietInstCmd=%AdminQuietInstCmd%
UserQuietInstCmd=%UserQuietInstCmd%
SourceFiles=SourceFiles
[Strings]
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName={target}
FriendlyName=Tiresias {version}
AppLaunched=cmd /c setup.cmd
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
FILE0="Tiresias.zip"
FILE1="setup.cmd"
[SourceFiles]
SourceFiles0={staging}\\
[SourceFiles0]
%FILE0%=
%FILE1%=
"""


def compileProgram() -> None:
	py = sys.executable
	subprocess.run([py, os.path.join(ROOT, "tools", "pregenerate_comtypes.py")], cwd=ROOT, check=True)
	subprocess.run([py, os.path.join(ROOT, "setup_cxfreeze.py"), "build_exe"], cwd=ROOT, check=True)


def makeZip(zipPath: str, program: str | None = None) -> int:
	# Nunca se distribuyen datos del desarrollador ni la marca de instalación: la
	# misma lista que la publicación (voces Piper descargadas, configuración...).
	toolsDir = os.path.dirname(os.path.abspath(__file__))
	if toolsDir not in sys.path:
		sys.path.insert(0, toolsDir)
	from publicar import PRIVATE_DATA, PRIVATE_TOP

	skip = {p.lower() for p in PRIVATE_TOP} | {f"data/{p}".lower() for p in PRIVATE_DATA}
	program = program or PROGRAM
	count = 0
	with zipfile.ZipFile(zipPath, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
		for root, dirs, files in os.walk(program):
			dirs[:] = [d for d in dirs if d != "__pycache__"]
			for fn in files:
				full = os.path.join(root, fn)
				rel = os.path.relpath(full, program)
				low = rel.replace("\\", "/").lower()
				if any(low == s or low.startswith(s + "/") for s in skip):
					continue
				z.write(full, rel)
				count += 1
	return count


def build(compile: bool = False, program: str | None = None, output: str | None = None, staging: str | None = None) -> str:
	"""Crea el instalador de la carpeta ``program`` en ``output``.

	``tools/publicar.py`` lo usa con la copia pública (sin complementos
	propietarios) y su propia carpeta de salida.
	"""
	program, output, staging = program or PROGRAM, output or OUTPUT, staging or STAGING
	if compile or (program == PROGRAM and not os.path.isfile(os.path.join(PROGRAM, "Tiresias.exe"))):
		compileProgram()
	if not os.path.isfile(os.path.join(program, "Tiresias.exe")):
		raise SystemExit(f"No se encuentra {os.path.join(program, 'Tiresias.exe')}")
	shutil.rmtree(staging, ignore_errors=True)
	os.makedirs(staging)
	n = makeZip(os.path.join(staging, "Tiresias.zip"), program)
	print(f"Programa empaquetado: {n} archivos")
	with open(os.path.join(staging, "setup.cmd"), "w", encoding="mbcs", newline="\r\n") as f:
		f.write(SETUP_CMD.format(folder=TEMP_FOLDER))
	sed = os.path.join(staging, "tiresias.sed")
	with open(sed, "w", encoding="mbcs", newline="\r\n") as f:
		f.write(SED.format(target=output, version=tiresias.VERSION, staging=staging))
	if os.path.isfile(output):
		os.remove(output)
	iexpress = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "iexpress.exe")
	print("Creando el autoextraíble con IExpress (puede tardar unos minutos)...")
	subprocess.run([iexpress, "/N", "/Q", sed], check=True)
	if not os.path.isfile(output):
		raise SystemExit("IExpress no ha generado el instalador")
	shutil.rmtree(staging, ignore_errors=True)
	print(f"Instalador creado: {output} ({os.path.getsize(output) // (1024 * 1024)} MB)")
	return output


def verify(path: str = OUTPUT) -> bool:
	"""Extrae el autoextraíble (sin ejecutarlo) y comprueba su contenido."""
	if not os.path.isfile(path):
		print(f"No existe {path}")
		return False
	tmp = tempfile.mkdtemp(prefix="tiresias_verif_")
	try:
		# /C extrae sin ejecutar; /T indica la carpeta; /Q sin preguntas.
		subprocess.run([path, "/C", f"/T:{tmp}", "/Q"], check=True, timeout=600)
		zipPath = os.path.join(tmp, "Tiresias.zip")
		ok = os.path.isfile(zipPath) and os.path.isfile(os.path.join(tmp, "setup.cmd"))
		if ok:
			with zipfile.ZipFile(zipPath) as z:
				names = set(z.namelist())
			ok = "Tiresias.exe" in names and any(n.startswith("lib/") for n in names)
			print(f"Contenido: {len(names)} archivos; Tiresias.exe: {'sí' if 'Tiresias.exe' in names else 'no'}")
		print("Verificación correcta" if ok else "Verificación FALLIDA")
		return ok
	finally:
		shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
	if "--verificar" in sys.argv:
		sys.exit(0 if verify() else 1)
	build(compile="--compilar" in sys.argv)
	sys.exit(0 if verify() else 1)
