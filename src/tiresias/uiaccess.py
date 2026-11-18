"""Acceso a las ventanas de administrador (``uiAccess``), como NVDA instalado.

Windows aísla las ventanas de los programas que se ejecutan como
administrador (el Administrador de tareas, el Editor del Registro, un
instalador elevado...): un programa normal no puede leerlas por UI Automation
ni MSAA, ni recibir las teclas que se pulsan en ellas, ni enviarles teclas.
Por eso Tiresias, sin permisos de administrador, se quedaba callado en el
Administrador de tareas.

Los lectores de pantalla lo resuelven con el privilegio ``uiAccess`` del
manifiesto: Windows se lo concede a un ejecutable que lo pida, que esté
firmado con una firma válida y que esté en una carpeta protegida (Archivos
de programa o System32). Es lo que hace NVDA: su copia instalada usa
``nvda_uiAccess.exe`` y la portable ``nvda_noUIAccess.exe``.

Tiresias hace lo mismo:

- se compila con tres ejecutables equivalentes: ``Tiresias.exe`` (normal),
  ``Tiresias_uiAccess.exe`` (pide ``uiAccess``) y ``Tiresias_noUIAccess.exe``
  (normal, para las copias portables que se crean desde la instalada);
- al instalar para todos los usuarios en Archivos de programa (el instalador
  ya tiene permisos de administrador), :func:`enable` firma
  ``Tiresias_uiAccess.exe`` y lo pone como ``Tiresias.exe``. NVDA lleva una
  firma de una autoridad de certificación; Tiresias no la tiene, así que el
  instalador crea un certificado propio de este equipo, lo marca como de
  confianza, firma el ejecutable y **borra la clave privada** en el acto: con
  ese certificado ya no se puede firmar nada más. Al desinstalar (o al volver
  a instalar) se quita el certificado;
- si el ejecutable ya trae una firma válida (una versión firmada con un
  certificado de una autoridad), no se crea ningún certificado;
- si algo falla, la copia instalada se queda como antes (sin ``uiAccess``):
  funciona igual salvo en las ventanas de administrador.

Un ejecutable con ``uiAccess`` no se puede iniciar con ``CreateProcess``
desde un proceso normal (Windows devuelve el error 740): :func:`spawn` lo
inicia con ``ShellExecuteEx`` en ese caso.
"""

from __future__ import annotations

import base64
import ctypes
import os
import shutil
import subprocess
import sys
from ctypes import wintypes as wt

EXE_NAME = "Tiresias.exe"
#: Ejecutable compilado con ``uiAccess="true"`` en el manifiesto (sin firmar).
UIACCESS_EXE = "Tiresias_uiAccess.exe"
#: Ejecutable normal que se conserva en la copia instalada (copias portables, auxiliar COM).
NO_UIACCESS_EXE = "Tiresias_noUIAccess.exe"
#: Archivo temporal mientras se firma (nunca queda en la carpeta).
SIGNING_TMP = "Tiresias_uiAccess.firmando.exe"
#: Sujeto del certificado local con el que se firma (para encontrarlo y quitarlo).
CERT_SUBJECT = "CN=Tiresias uiAccess (certificado local de este equipo)"
CERT_FRIENDLY_NAME = "Tiresias: firma local del lector de pantalla (uiAccess)"

ERROR_ELEVATION_REQUIRED = 740
TOKEN_QUERY = 0x0008
TokenUIAccess = 26
WM_CLOSE = 0x0010
MSGFLT_ALLOW = 1
CREATE_NO_WINDOW = 0x08000000
#: Tiempo máximo de PowerShell al firmar o al quitar el certificado.
POWERSHELL_TIMEOUT = 120

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_adv = ctypes.WinDLL("advapi32", use_last_error=True)
_k32.GetCurrentProcess.restype = wt.HANDLE
_k32.CloseHandle.argtypes = [wt.HANDLE]
_k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_k32.OpenProcess.restype = wt.HANDLE
_k32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
_k32.GetExitCodeProcess.restype = wt.BOOL
_k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
_k32.WaitForSingleObject.restype = wt.DWORD
_k32.GetProcessId.argtypes = [wt.HANDLE]
_k32.GetProcessId.restype = wt.DWORD
_adv.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
_adv.OpenProcessToken.restype = wt.BOOL
_adv.GetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)]
_adv.GetTokenInformation.restype = wt.BOOL


def _log():
	from .log import getLogger

	return getLogger("uiaccess")


# ====================================================================== estado
def hasUiAccess() -> bool:
	"""``True`` si este proceso tiene el privilegio ``uiAccess``."""
	token = wt.HANDLE()
	if not _adv.OpenProcessToken(_k32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
		return False
	try:
		value = wt.DWORD()
		size = wt.DWORD()
		if not _adv.GetTokenInformation(token, TokenUIAccess, ctypes.byref(value), ctypes.sizeof(value), ctypes.byref(size)):
			return False
		return bool(value.value)
	finally:
		_k32.CloseHandle(token)


def secureLocations() -> list[str]:
	"""Carpetas protegidas donde Windows permite ``uiAccess``."""
	env = os.environ
	result = []
	for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
		value = env.get(var)
		if value:
			result.append(value)
	root = env.get("SystemRoot") or env.get("windir") or r"C:\Windows"
	result.append(os.path.join(root, "System32"))
	return result


def _isInside(path: str, folder: str) -> bool:
	path = os.path.normcase(os.path.abspath(path))
	folder = os.path.normcase(os.path.abspath(folder)).rstrip("\\/")
	return path.startswith(folder + os.sep)


def isSecureLocation(path: str, locations: list[str] | None = None) -> bool:
	"""``True`` si ``path`` está dentro de una carpeta protegida (Archivos de programa...)."""
	return any(_isInside(path, folder) for folder in (locations if locations is not None else secureLocations()))


def isAvailable(folder: str) -> bool:
	"""``True`` si la carpeta del programa trae el ejecutable con ``uiAccess``."""
	return os.path.isfile(os.path.join(folder, UIACCESS_EXE))


# ====================================================================== PowerShell
def _psQuote(text: str) -> str:
	"""Cadena literal de PowerShell (entre comillas simples)."""
	return "'" + text.replace("'", "''") + "'"


_PS_COMMON = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$subject = {subject}
function Remove-TiresiasCerts {{
	foreach ($name in 'Root', 'TrustedPublisher') {{
		$st = New-Object System.Security.Cryptography.X509Certificates.X509Store($name, 'LocalMachine')
		$st.Open('ReadWrite')
		try {{
			foreach ($c in @($st.Certificates | Where-Object {{ $_.Subject -eq $subject }})) {{ $st.Remove($c) }}
		}} finally {{ $st.Close() }}
	}}
	foreach ($c in @(Get-ChildItem -Path Cert:\LocalMachine\My | Where-Object {{ $_.Subject -eq $subject }})) {{
		Remove-Item -LiteralPath $c.PSPath -DeleteKey
	}}
}}
"""

_PS_SIGN = r"""
$exe = {exe}
$sig = Get-AuthenticodeSignature -LiteralPath $exe
if ($sig.Status -eq 'Valid' -and $sig.SignerCertificate.Subject -ne $subject) {{
	'TIRESIAS:YA_FIRMADO'
	exit 0
}}
Remove-TiresiasCerts
$cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject $subject -FriendlyName {friendly} `
	-CertStoreLocation Cert:\LocalMachine\My -KeyExportPolicy NonExportable `
	-KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 -NotAfter (Get-Date).AddYears(30)
try {{
	$pub = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2(,$cert.RawData)
	$st = New-Object System.Security.Cryptography.X509Certificates.X509Store('Root', 'LocalMachine')
	$st.Open('ReadWrite')
	try {{ $st.Add($pub) }} finally {{ $st.Close() }}
	$r = Set-AuthenticodeSignature -LiteralPath $exe -Certificate $cert -HashAlgorithm SHA256
	if ($r.Status -ne 'Valid') {{ throw ('La firma no es valida: ' + $r.Status + ' ' + $r.StatusMessage) }}
}} catch {{
	# Sin firma no se deja el certificado marcado como de confianza.
	$err = $_
	try {{ Remove-Item -LiteralPath $cert.PSPath -DeleteKey }} catch {{ }}
	try {{ Remove-TiresiasCerts }} catch {{ }}
	throw $err
}}
# La clave privada se borra: con este certificado ya no se puede firmar nada más.
Remove-Item -LiteralPath $cert.PSPath -DeleteKey
'TIRESIAS:FIRMADO'
"""

_PS_REMOVE = r"""
Remove-TiresiasCerts
'TIRESIAS:QUITADO'
"""


def signScript(exe: str) -> str:
	"""Guion de PowerShell que firma ``exe`` con un certificado local de un solo uso."""
	return _PS_COMMON.format(subject=_psQuote(CERT_SUBJECT)) + _PS_SIGN.format(exe=_psQuote(exe), friendly=_psQuote(CERT_FRIENDLY_NAME))


def removeScript() -> str:
	"""Guion de PowerShell que quita los certificados locales de Tiresias."""
	return _PS_COMMON.format(subject=_psQuote(CERT_SUBJECT)) + _PS_REMOVE


def _powershellExe() -> str:
	root = os.environ.get("SystemRoot") or r"C:\Windows"
	exe = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
	return exe if os.path.isfile(exe) else "powershell.exe"


def runPowerShell(script: str, timeout: float = POWERSHELL_TIMEOUT) -> tuple[bool, str]:
	"""Ejecuta un guion de PowerShell (``-EncodedCommand``): ``(¿bien?, salida)``."""
	encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
	cmd = [_powershellExe(), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded]
	try:
		res = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW, cwd=os.path.dirname(_powershellExe()) or None)
	except (OSError, subprocess.SubprocessError) as e:
		return False, str(e)
	out = (res.stdout or b"").decode("mbcs", "replace") + (res.stderr or b"").decode("mbcs", "replace")
	return res.returncode == 0, out.strip()


# ====================================================================== instalar y desinstalar
def enable(folder: str, locations: list[str] | None = None, runner=runPowerShell) -> bool:
	"""Activa ``uiAccess`` en la copia instalada de ``folder``. ``True`` si queda activado.

	Necesita permisos de administrador (lo llama el instalador elevado). Si no
	se puede, la copia se queda con el ejecutable normal y funciona como antes.
	"""
	log = _log()
	src = os.path.join(folder, UIACCESS_EXE)
	exe = os.path.join(folder, EXE_NAME)
	if not os.path.isfile(src) or not os.path.isfile(exe):
		log.info("Esta versión no trae %s: la copia instalada no tendrá acceso a las ventanas de administrador", UIACCESS_EXE)
		return False
	if not isSecureLocation(folder, locations):
		log.info("%s no está en una carpeta protegida: sin acceso a las ventanas de administrador", folder)
		return False
	noUi = os.path.join(folder, NO_UIACCESS_EXE)
	if not os.path.isfile(noUi):
		# Una versión que no lo trajera: el ejecutable normal se conserva igualmente.
		shutil.copy2(exe, noUi)
	tmp = os.path.join(folder, SIGNING_TMP)
	try:
		shutil.copy2(src, tmp)
		ok, out = runner(signScript(tmp))
		if not ok or "TIRESIAS:" not in out:
			log.warning("No se pudo firmar %s; la copia instalada sigue sin acceso a las ventanas de administrador: %s", UIACCESS_EXE, out[-2000:])
			return False
		os.replace(tmp, exe)
		log.info("Acceso a las ventanas de administrador activado (%s)", "firma existente" if "YA_FIRMADO" in out else "certificado local")
		return True
	except OSError:
		log.exception("No se pudo activar el acceso a las ventanas de administrador")
		return False
	finally:
		try:
			os.remove(tmp)
		except OSError:
			pass


def removeCertificates(runner=runPowerShell) -> bool:
	"""Quita los certificados locales de Tiresias (al desinstalar). Necesita administrador."""
	ok, out = runner(removeScript())
	if not ok:
		_log().warning("No se pudieron quitar los certificados de Tiresias: %s", out[-2000:])
	return ok


def portableExecutable(folder: str) -> str:
	"""Ejecutable que debe ser ``Tiresias.exe`` en una copia portable hecha desde ``folder``."""
	noUi = os.path.join(folder, NO_UIACCESS_EXE)
	return noUi if os.path.isfile(noUi) else os.path.join(folder, EXE_NAME)


# ====================================================================== iniciar procesos
class ShellProcess:
	"""Proceso iniciado con ``ShellExecuteEx`` (lo justo de ``subprocess.Popen``)."""

	def __init__(self, handle: int, pid: int) -> None:
		self._handle = handle
		self.pid = pid
		self.returncode: int | None = None

	def poll(self) -> int | None:
		if self.returncode is None and self._handle:
			code = wt.DWORD()
			if _k32.GetExitCodeProcess(self._handle, ctypes.byref(code)) and code.value != 259:  # STILL_ACTIVE
				self.returncode = int(code.value)
				self._close()
		return self.returncode

	def wait(self, timeout: float | None = None) -> int | None:
		if self.returncode is None and self._handle:
			ms = 0xFFFFFFFF if timeout is None else int(timeout * 1000)
			if _k32.WaitForSingleObject(self._handle, ms) != 0:
				raise subprocess.TimeoutExpired("ShellExecuteEx", timeout or 0)
		return self.poll()

	def _close(self) -> None:
		if self._handle:
			_k32.CloseHandle(self._handle)
			self._handle = 0

	def __del__(self) -> None:
		try:
			self._close()
		except Exception:
			pass


def shellExecute(cmd: list[str], cwd: str | None = None) -> ShellProcess:
	"""Inicia ``cmd`` con ``ShellExecuteEx`` (respeta ``uiAccess``)."""
	from .coexist import relaunch

	info = relaunch._SHELLEXECUTEINFOW()
	info.cbSize = ctypes.sizeof(info)
	info.fMask = relaunch.SEE_MASK_NOCLOSEPROCESS | relaunch.SEE_MASK_NOASYNC | relaunch.SEE_MASK_FLAG_NO_UI
	info.lpVerb = "open"
	info.lpFile = cmd[0]
	info.lpParameters = subprocess.list2cmdline([str(a) for a in cmd[1:]]) if len(cmd) > 1 else None
	info.lpDirectory = cwd or os.path.dirname(cmd[0]) or None
	info.nShow = relaunch.SW_SHOWNORMAL
	if not relaunch._shell32.ShellExecuteExW(ctypes.byref(info)):
		raise ctypes.WinError(ctypes.get_last_error())
	handle = info.hProcess or 0
	pid = int(_k32.GetProcessId(handle)) if handle else 0
	return ShellProcess(handle, pid)


def spawn(cmd: list[str], cwd: str | None = None, creationflags: int = 0):
	"""Inicia ``cmd`` como ``subprocess.Popen`` y, si Windows pide ``uiAccess``, con ``ShellExecuteEx``.

	Devuelve un objeto con ``pid`` y ``poll()``. ``CreateProcess`` no puede
	iniciar un ejecutable con ``uiAccess`` desde un proceso sin él (error 740):
	así se inicia la copia instalada desde el instalador, una copia portable o
	el código fuente.
	"""
	try:
		return subprocess.Popen(cmd, cwd=cwd, close_fds=True, creationflags=creationflags)
	except OSError as e:
		if getattr(e, "winerror", None) != ERROR_ELEVATION_REQUIRED:
			raise
	_log().info("%s pide uiAccess: se inicia con ShellExecuteEx", os.path.basename(cmd[0]))
	return shellExecute(cmd, cwd)


# ====================================================================== mensajes de procesos normales
def allowCloseFromNormalProcesses(hwnd: int) -> None:
	"""Deja que un proceso normal cierre esta ventana con ``WM_CLOSE``.

	Con ``uiAccess`` Tiresias tiene un nivel de integridad mayor y Windows
	(UIPI) descarta los mensajes de los procesos normales: una copia portable,
	la desinstalación o ``--quit`` no podrían cerrar la copia instalada.
	"""
	try:
		user32 = ctypes.WinDLL("user32", use_last_error=True)
		user32.ChangeWindowMessageFilterEx.argtypes = [wt.HWND, wt.UINT, wt.DWORD, ctypes.c_void_p]
		user32.ChangeWindowMessageFilterEx.restype = wt.BOOL
		user32.ChangeWindowMessageFilterEx(hwnd, WM_CLOSE, MSGFLT_ALLOW, None)
	except Exception:
		_log().debug("No se pudo permitir WM_CLOSE desde procesos normales", exc_info=True)


# ====================================================================== objetos COM activos
COM_HELPER_ARG = "--com-get-active-object"


def _helperExecutable() -> str | None:
	"""Ejecutable sin ``uiAccess`` de esta copia (para el auxiliar COM)."""
	if not getattr(sys, "frozen", False):
		return None
	folder = os.path.dirname(sys.executable)
	for name in (NO_UIACCESS_EXE, "Tiresias-depuracion.exe"):
		path = os.path.join(folder, name)
		if os.path.isfile(path):
			return path
	return None


def getActiveObject(progId: str, dynamic: bool = True):
	"""``comtypes.client.GetActiveObject`` que funciona también con ``uiAccess``.

	Con ``uiAccess`` la tabla de objetos en ejecución (ROT) no muestra los
	objetos de los programas normales (Outlook, Word...). Como NVDA
	(``nvda_slave``), se pide el objeto a un proceso auxiliar sin ``uiAccess``,
	que lo pasa con ``LresultFromObject``.
	"""
	import comtypes.client

	try:
		return comtypes.client.GetActiveObject(progId, dynamic=dynamic)
	except OSError:
		helper = _helperExecutable() if hasUiAccess() else None
		if helper is None:
			raise
	return _getActiveObjectFromHelper(helper, progId, dynamic)


def _getActiveObjectFromHelper(helper: str, progId: str, dynamic: bool):
	import comtypes.client
	from comtypes import IUnknown
	from comtypes.automation import IDispatch

	p = subprocess.Popen([helper, COM_HELPER_ARG, progId], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
	try:
		line = p.stdout.readline().strip() if p.stdout else b""
		try:
			lres = int(line)
		except ValueError:
			raise OSError(f"El auxiliar no obtuvo {progId}") from None
		oleacc = ctypes.oledll.oleacc
		iid = IDispatch._iid_ if dynamic else IUnknown._iid_
		ptr = ctypes.POINTER(IDispatch if dynamic else IUnknown)()
		oleacc.ObjectFromLresult(ctypes.c_ssize_t(lres), ctypes.byref(iid), 0, ctypes.byref(ptr))
		if dynamic:
			return comtypes.client.dynamic.Dispatch(ptr)
		return comtypes.client.GetBestInterface(ptr)
	finally:
		try:
			if p.stdin:
				p.stdin.close()
			p.wait(10)
		except Exception:
			p.kill()


def comHelperMain(argv: list[str] | None = None) -> int:
	"""``Tiresias_noUIAccess.exe --com-get-active-object PROGID``: el auxiliar COM.

	Escribe el ``LRESULT`` en la salida estándar y espera a que se cierre la
	entrada (así el objeto vive hasta que Tiresias lo recoge). Escribe con la
	API de Windows: en el ejecutable sin consola ``sys.stdout`` puede no existir.
	"""
	argv = sys.argv[1:] if argv is None else argv
	try:
		progId = argv[argv.index(COM_HELPER_ARG) + 1]
	except (ValueError, IndexError):
		return 2
	k32 = ctypes.WinDLL("kernel32", use_last_error=True)
	k32.GetStdHandle.restype = wt.HANDLE
	k32.WriteFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
	k32.ReadFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
	out = k32.GetStdHandle(-11)
	inp = k32.GetStdHandle(-10)

	def write(text: str) -> None:
		data = text.encode("ascii")
		n = wt.DWORD()
		k32.WriteFile(out, data, len(data), ctypes.byref(n), None)

	code = 0
	try:
		import comtypes
		import comtypes.client
		from comtypes import IUnknown

		comtypes.CoInitialize()
		obj = comtypes.client.GetActiveObject(progId, dynamic=False)
		if not isinstance(obj, IUnknown):
			obj = obj._comobj
		lres = ctypes.oledll.oleacc.LresultFromObject
		lres.restype = ctypes.c_ssize_t
		lres.argtypes = [ctypes.c_void_p, ctypes.c_ssize_t, ctypes.c_void_p]
		value = lres(ctypes.byref(IUnknown._iid_), 0, obj)
		write(f"{int(value)}\n")
	except Exception:
		write("error\n")
		code = 1
	# Se espera a que Tiresias cierre la entrada (o termine).
	buf = ctypes.create_string_buffer(64)
	n = wt.DWORD()
	for _ in range(1000):
		if not k32.ReadFile(inp, buf, 64, ctypes.byref(n), None) or n.value == 0:
			break
	return code
