"""Archivos bloqueados por el Control de aplicaciones de Windows.

Smart App Control (Windows 11) y las directivas WDAC pueden impedir que se
carguen DLL sin firmar que vienen de Internet (con la «marca de la web»). En
ese caso Python lanza, por ejemplo::

	ImportError: DLL load failed while importing _core: Una directiva de
	Control de aplicaciones bloqueó este archivo.

(error de Windows 4551, ``ERROR_SYSTEM_INTEGRITY_POLICY_VIOLATION``). Este
módulo lo reconoce y lo explica en español con un cuadro de mensaje nativo
(``MessageBoxW``: wxPython puede ser justo la DLL bloqueada) y en el registro.
No usa nada que pueda estar bloqueado: solo ``ctypes`` y la biblioteca estándar.
"""

from __future__ import annotations

import ctypes
import os
import sys

#: ERROR_SYSTEM_INTEGRITY_POLICY_VIOLATION (Smart App Control / WDAC).
WINERROR_POLICY_BLOCK = 4551
#: Otros códigos con el mismo origen: 1260 (bloqueado por directiva de grupo)
#: y 0x800711C7 / 0xC0E90002 (HRESULT y NTSTATUS de la integridad de código).
_OTHER_CODES = {1260, 0x800711C7, -2147020345, 0xC0E90002}
#: Textos del error en español e inglés.
_TEXTS = (
	"directiva de control de aplicaciones",
	"application control policy",
	"smart app control",
	"code integrity",
	"integridad de código",
)

TITLE = "Tiresias: Windows ha bloqueado archivos del programa"


def isBlockedError(exc: BaseException | None) -> bool:
	"""``True`` si ``exc`` (o su causa) es un bloqueo del Control de aplicaciones."""
	seen = 0
	while exc is not None and seen < 5:
		seen += 1
		code = getattr(exc, "winerror", None)
		if code == WINERROR_POLICY_BLOCK or code in _OTHER_CODES:
			return True
		text = str(exc).lower()
		if "4551" in text or any(t in text for t in _TEXTS):
			return True
		exc = exc.__cause__ or exc.__context__
	return False


def programFolder() -> str:
	"""Carpeta del programa (la del ejecutable compilado o la del código)."""
	if getattr(sys, "frozen", False):
		return os.path.dirname(os.path.abspath(sys.executable))
	return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def explanation(exc: BaseException | None = None) -> str:
	"""Explicación en español para el usuario (cuadro de mensaje y registro)."""
	folder = programFolder()
	lines = [
		"Windows no ha dejado cargar una parte de Tiresias (una biblioteca DLL).",
		"",
		"Qué pasa: el Control de aplicaciones de Windows (Smart App Control o una "
		"directiva de la empresa) bloquea los archivos sin firma digital que se han "
		"descargado de Internet. Tiresias todavía no está firmado y su ZIP llega con "
		"la «marca de la web».",
		"",
		"Cómo solucionarlo:",
		"1. Cierre este mensaje.",
		"2. Desbloquee los archivos de la carpeta del programa:",
		"   " + folder,
		"   - Con PowerShell: Get-ChildItem -LiteralPath '" + folder + "' -Recurse | Unblock-File",
		"   - O con Tiresias.bat (código fuente): Tiresias.bat desbloquear",
		"   - O antes de descomprimir: botón derecho sobre el ZIP > Propiedades > marque «Desbloquear» > Aceptar, y vuelva a descomprimir.",
		"3. Vuelva a iniciar Tiresias.",
		"",
		"Si Smart App Control está en modo «Activado», puede seguir bloqueando "
		"programas sin firma aunque se desbloqueen: lo ideal es usar una versión "
		"firmada digitalmente de Tiresias. Desactivar Smart App Control "
		"(Seguridad de Windows > Control de aplicaciones y navegador) no se "
		"recomienda: en muchas versiones de Windows no se puede volver a activar "
		"sin reinstalar el sistema.",
	]
	if exc is not None:
		lines += ["", "Detalle técnico: " + str(exc)]
	return "\n".join(lines)


def report(exc: BaseException | None = None, log=None, show: bool = True) -> None:
	"""Escribe la explicación en el registro (si se puede) y la muestra con MessageBoxW."""
	text = explanation(exc)
	try:
		if log is None:
			from .log import getLogger

			log = getLogger("appControl")
		log.error("Archivo bloqueado por el Control de aplicaciones de Windows.\n%s", text)
	except Exception:
		pass
	if not show:
		return
	try:
		# MB_OK | MB_ICONWARNING | MB_SETFOREGROUND | MB_TOPMOST
		ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x0 | 0x30 | 0x10000 | 0x40000)
	except Exception:
		pass
