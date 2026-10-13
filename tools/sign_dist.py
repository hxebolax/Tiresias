"""Firma digital de la versión compilada (``dist\\Tiresias``) con signtool.

Smart App Control y las directivas WDAC bloquean los EXE y DLL sin firmar que
llegan de Internet. La solución definitiva es firmar con un certificado de
firma de código de una autoridad de confianza (o Azure Trusted Signing). Un
certificado de prueba autofirmado NO sirve en otros equipos: Smart App Control
solo confía en certificados de autoridades reconocidas por Microsoft; solo
vale para comprobar el proceso en el propio equipo.

Esta herramienta NUNCA crea certificados ni toca los almacenes del sistema:
usa el que se le indique con variables de entorno:

- ``TIRESIAS_CERT_PFX`` (archivo .pfx) y, si hace falta, ``TIRESIAS_CERT_PASSWORD``;
- o ``TIRESIAS_CERT_THUMBPRINT`` (huella SHA-1 de un certificado ya instalado
  en el almacén personal del usuario).

Opcional: ``TIRESIAS_TIMESTAMP_URL`` (por defecto, el servidor de DigiCert) y
``SIGNTOOL`` (ruta de signtool.exe; si no, se busca en el PATH y en el SDK de
Windows).

Uso::

	python tools/sign_dist.py [carpeta]   (por defecto dist\\Tiresias)
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DIR = os.path.join(ROOT, "dist", "Tiresias")
SIGNABLE = (".exe", ".dll", ".pyd")
TIMESTAMP = os.environ.get("TIRESIAS_TIMESTAMP_URL", "http://timestamp.digicert.com")
#: Archivos por llamada a signtool (la línea de órdenes tiene límite).
BATCH = 40


def findSigntool() -> str | None:
	explicit = os.environ.get("SIGNTOOL")
	if explicit and os.path.isfile(explicit):
		return explicit
	found = shutil.which("signtool")
	if found:
		return found
	bases = [os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Windows Kits", "10", "bin")]
	candidates: list[str] = []
	for base in bases:
		candidates += glob.glob(os.path.join(base, "10.*", "x64", "signtool.exe"))
		candidates += glob.glob(os.path.join(base, "x64", "signtool.exe"))
	# La versión del SDK más reciente primero.
	candidates.sort(reverse=True)
	return candidates[0] if candidates else None


def certificateArgs() -> list[str] | None:
	pfx = os.environ.get("TIRESIAS_CERT_PFX")
	if pfx:
		if not os.path.isfile(pfx):
			print("No existe el certificado indicado en TIRESIAS_CERT_PFX:", pfx)
			return None
		args = ["/f", pfx]
		password = os.environ.get("TIRESIAS_CERT_PASSWORD")
		if password:
			args += ["/p", password]
		return args
	thumb = (os.environ.get("TIRESIAS_CERT_THUMBPRINT") or "").replace(" ", "")
	if thumb:
		return ["/sha1", thumb]
	return None


def isSigned(signtool: str, path: str) -> bool:
	r = subprocess.run([signtool, "verify", "/pa", "/q", path], capture_output=True)
	return r.returncode == 0


def filesToSign(folder: str) -> list[str]:
	out = []
	for dirpath, _dirs, files in os.walk(folder):
		for name in files:
			if name.lower().endswith(SIGNABLE):
				out.append(os.path.join(dirpath, name))
	return sorted(out)


def main(argv: list[str]) -> int:
	folder = os.path.abspath(argv[0]) if argv else DEFAULT_DIR
	if not os.path.isdir(folder):
		print("No existe la carpeta", folder, "(compila primero).")
		return 1
	signtool = findSigntool()
	if not signtool:
		print("No se encontró signtool.exe. Instala el SDK de Windows (componente «Signing Tools»)")
		print("o indica su ruta en la variable SIGNTOOL.")
		return 1
	cert = certificateArgs()
	if cert is None:
		print("No hay certificado de firma configurado. Indica uno con TIRESIAS_CERT_PFX")
		print("(y TIRESIAS_CERT_PASSWORD) o con TIRESIAS_CERT_THUMBPRINT.")
		print("Esta herramienta no crea certificados ni modifica los del sistema.")
		return 1
	pending = [p for p in filesToSign(folder) if not isSigned(signtool, p)]
	if not pending:
		print("Todo está ya firmado.")
		return 0
	print("Firmando %d archivos con %s ..." % (len(pending), signtool))
	for i in range(0, len(pending), BATCH):
		chunk = pending[i : i + BATCH]
		cmd = [signtool, "sign", "/fd", "SHA256", "/tr", TIMESTAMP, "/td", "SHA256"] + cert + chunk
		r = subprocess.run(cmd)
		if r.returncode != 0:
			print("ERROR: signtool falló (código %d)." % r.returncode)
			return r.returncode
	print("Firma terminada.")
	return 0


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
