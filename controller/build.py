"""Compila las bibliotecas nativas de la API de control de Tiresias.

Necesita Visual Studio (herramientas de C++) y el SDK de Windows (MIDL).

Uso::

	python controller/build.py            (x64 y x86)
	python controller/build.py x64

Resultado:

- ``data/controller/x64/tiresiasControllerServer.dll``: servidor RPC que
  carga Tiresias (solo 64 bits).
- ``data/controller/x64/tiresiasControllerClient.dll`` y ``.lib``: biblioteca
  cliente de 64 bits para programas y juegos.
- ``data/controller/x86/tiresiasControllerClient.dll`` y ``.lib``: la de 32 bits.
- ``data/controller/x64/tiresiasNvdaWindow.exe``: auxiliar que atiende el
  punto de conexión de NVDA (reenvía a Tiresias por ``tiresiasRelay.idl``) y
  crea la ventana oculta «NVDA» que buscan algunas bibliotecas (Tolk). Va
  aparte porque un proceso no puede soltar un punto de conexión ncalrpc sin
  terminar, y NVDA lo necesita libre al arrancar.

Si un binario está en uso (un Tiresias en ejecución), el anterior se aparta
como ``.old`` y se borra en la siguiente compilación.

Los binarios van a ``data/controller`` porque todo lo que Tiresias necesita
está en ``data``; el código C, el IDL y los .def se quedan en ``controller``.

Las bibliotecas se enlazan con el CRT estático (/MT): no necesitan los
runtimes de Visual C++ en el equipo del usuario.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
INCLUDE = os.path.join(HERE, "include")
BUILD = os.path.join(HERE, "build")
#: Carpeta de los binarios compilados (``data/controller/<arq>``).
OUT_DIR = os.path.join(os.path.dirname(HERE), "data", "controller")

LIBS = "rpcrt4.lib user32.lib advapi32.lib kernel32.lib"
CFLAGS = "/nologo /O2 /MT /W3 /GS /Gy /DUNICODE /D_UNICODE /DTIRESIAS_CONTROLLER_BUILD"


def findVcvarsall() -> str:
	env = os.environ.get("VCVARSALL")
	if env and os.path.isfile(env):
		return env
	vswhere = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Microsoft Visual Studio", "Installer", "vswhere.exe")
	if os.path.isfile(vswhere):
		try:
			out = subprocess.run(
				[vswhere, "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
				capture_output=True,
				text=True,
				check=False,
			).stdout.strip()
			if out:
				cand = os.path.join(out.splitlines()[0], "VC", "Auxiliary", "Build", "vcvarsall.bat")
				if os.path.isfile(cand):
					return cand
		except OSError:
			pass
	patterns = [
		r"C:\Program Files\Microsoft Visual Studio\*\*\VC\Auxiliary\Build\vcvarsall.bat",
		r"C:\Program Files (x86)\Microsoft Visual Studio\*\*\VC\Auxiliary\Build\vcvarsall.bat",
	]
	for pat in patterns:
		found = sorted(glob.glob(pat), reverse=True)
		if found:
			return found[0]
	raise SystemExit("No se encontró vcvarsall.bat: instala las herramientas de C++ de Visual Studio o define VCVARSALL")


def _versionRc(folder: str, name: str, desc: str, fileName: str) -> str:
	path = os.path.join(folder, name + "_version.rc")
	with open(path, "w", encoding="utf-8") as f:
		f.write(f'#define TCC_NAME "{name}"\n#define TCC_DESC "{desc}"\n#define TCC_FILE "{fileName}"\n')
		f.write(f'#include "{os.path.join(SRC, "version.rc")}"\n')
	return path


def buildArch(arch: str, vcvars: str) -> None:
	out = os.path.join(OUT_DIR, arch)
	work = os.path.join(BUILD, arch)
	shutil.rmtree(work, ignore_errors=True)
	os.makedirs(work, exist_ok=True)
	os.makedirs(out, exist_ok=True)
	midlEnv = "x64" if arch == "x64" else "win32"
	idl = os.path.join(SRC, "tiresiasController.idl")
	acf = os.path.join(SRC, "tiresiasController.acf")
	clientRc = _versionRc(work, "tiresiasControllerClient", "API de control de Tiresias (cliente)", "tiresiasControllerClient.dll")
	steps = [
		f'midl /nologo /env {midlEnv} /acf "{acf}" /prefix client "rpc_" /prefix server "srv_" '
		f'/h tiresiasController_rpc.h /cstub rpc_client.c /sstub rpc_server.c "{idl}"',
		f'rc /nologo /fo client_version.res "{clientRc}"',
		f'cl {CFLAGS} /I"{work}" /I"{INCLUDE}" /c "{os.path.join(SRC, "client.c")}" rpc_client.c',
		f'link /nologo /DLL /OPT:REF /OPT:ICF /DEF:"{os.path.join(SRC, "client.def")}" '
		f'/OUT:"{os.path.join(work, "tiresiasControllerClient.dll")}" /IMPLIB:"{os.path.join(work, "tiresiasControllerClient.lib")}" '
		f"client.obj rpc_client.obj client_version.res {LIBS}",
	]
	if arch == "x64":
		serverRc = _versionRc(work, "tiresiasControllerServer", "API de control de Tiresias (servidor)", "tiresiasControllerServer.dll")
		relayIdl = os.path.join(SRC, "tiresiasRelay.idl")
		relayAcf = os.path.join(SRC, "tiresiasRelay.acf")
		steps += [
			# Interfaz privada de reenvío entre el auxiliar del punto de conexión de NVDA y Tiresias.
			f'midl /nologo /env {midlEnv} /acf "{relayAcf}" /prefix client "rlyc_" /prefix server "rlys_" '
			f'/h tiresiasRelay_rpc.h /cstub relay_client.c /sstub relay_server.c "{relayIdl}"',
			f'rc /nologo /fo server_version.res "{serverRc}"',
			f'cl {CFLAGS} /I"{work}" /I"{INCLUDE}" /c "{os.path.join(SRC, "server.c")}" rpc_server.c relay_server.c relay_client.c',
			# El servidor incluye también los cabos cliente para hablar con NVDA (anuncios en espera).
			f'link /nologo /DLL /OPT:REF /OPT:ICF /DEF:"{os.path.join(SRC, "server.def")}" '
			f'/OUT:"{os.path.join(work, "tiresiasControllerServer.dll")}" /IMPLIB:"{os.path.join(work, "tiresiasControllerServer.lib")}" '
			f"server.obj rpc_server.obj rpc_client.obj relay_server.obj server_version.res {LIBS}",
			f'cl {CFLAGS} /I"{work}" /c "{os.path.join(SRC, "nvdaWindow.c")}"',
			f'link /nologo /SUBSYSTEM:WINDOWS /OPT:REF /OUT:"{os.path.join(work, "tiresiasNvdaWindow.exe")}" '
			f"nvdaWindow.obj rpc_server.obj relay_client.obj {LIBS} shell32.lib",
		]
	vcArch = "x64" if arch == "x64" else "x64_x86"
	script = os.path.join(work, "build.bat")
	with open(script, "w", encoding="mbcs") as f:
		f.write("@echo off\n")
		# vcvarsall busca vswhere.exe en el PATH.
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
	products = ["tiresiasControllerClient.dll", "tiresiasControllerClient.lib"]
	if arch == "x64":
		products += ["tiresiasControllerServer.dll", "tiresiasNvdaWindow.exe"]
	for name in products:
		_install(os.path.join(work, name), os.path.join(out, name))
	# Las .exp no hacen falta.
	for exp in glob.glob(os.path.join(out, "*.exp")):
		os.remove(exp)


def _install(src: str, dst: str) -> None:
	"""Copia un binario a su carpeta aunque el anterior esté en uso.

	Windows no deja sobrescribir una DLL o un .exe cargados (por ejemplo,
	si hay un Tiresias en ejecución), pero sí renombrarlos: el antiguo se
	aparta como ``.old`` y se borra en la siguiente compilación.
	"""
	for old in glob.glob(dst + ".*.old"):
		try:
			os.remove(old)
		except OSError:
			pass
	try:
		shutil.copy2(src, dst)
		return
	except PermissionError:
		pass
	import time

	aside = f"{dst}.{int(time.time())}.old"
	os.replace(dst, aside)
	shutil.copy2(src, dst)
	print(f"{os.path.basename(dst)} estaba en uso: el anterior queda como {os.path.basename(aside)}")


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
