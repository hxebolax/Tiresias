"""Pruebas del acceso a las ventanas de administrador (``uiAccess``), versión 1.0.17.

Un usuario del foro contó que la copia instalada no leía el Administrador de
tareas (Control+Mayúsculas+Escape) si no se ejecutaba Tiresias como
administrador, mientras que NVDA instalado sí lo lee. NVDA usa en su copia
instalada un ejecutable con ``uiAccess`` firmado; Tiresias ahora también.

Estas pruebas no tocan el almacén de certificados ni Archivos de programa: el
guion de PowerShell se sustituye por uno falso y las carpetas «protegidas»
son temporales.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_uiaccess -v``
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import installer, uiaccess  # noqa: E402


class TempDir(unittest.TestCase):
	def setUp(self) -> None:
		self.tmp = tempfile.mkdtemp(prefix="tiresias_uiaccess_")
		self.addCleanup(shutil.rmtree, self.tmp, True)

	def write(self, folder: str, name: str, content: str) -> str:
		os.makedirs(folder, exist_ok=True)
		path = os.path.join(folder, name)
		with open(path, "w", encoding="utf-8") as f:
			f.write(content)
		return path

	def read(self, *parts: str) -> str:
		with open(os.path.join(*parts), encoding="utf-8") as f:
			return f.read()


class EstadoTests(unittest.TestCase):
	def test_este_proceso_no_tiene_uiaccess(self) -> None:
		# Las pruebas se ejecutan con Python normal: nunca con uiAccess.
		self.assertFalse(uiaccess.hasUiAccess())

	def test_carpetas_protegidas(self) -> None:
		locations = [r"C:\Program Files", r"C:\Windows\System32"]
		self.assertTrue(uiaccess.isSecureLocation(r"C:\Program Files\Tiresias", locations))
		self.assertTrue(uiaccess.isSecureLocation(r"c:\program files\tiresias\Tiresias.exe", locations))
		self.assertFalse(uiaccess.isSecureLocation(r"C:\Program Files", locations))
		self.assertFalse(uiaccess.isSecureLocation(r"C:\Program Files Falso\Tiresias", locations))
		self.assertFalse(uiaccess.isSecureLocation(r"D:\Portables\Tiresias", locations))

	def test_carpetas_protegidas_del_sistema(self) -> None:
		folders = [os.path.normcase(p) for p in uiaccess.secureLocations()]
		self.assertIn(os.path.normcase(os.environ["ProgramFiles"]), folders)


class GuionTests(unittest.TestCase):
	def test_guion_de_firma(self) -> None:
		script = uiaccess.signScript(r"C:\Program Files\Tiresias\Tiresias_uiAccess.firmando.exe")
		self.assertIn("New-SelfSignedCertificate", script)
		self.assertIn("Set-AuthenticodeSignature", script)
		self.assertIn("'Root', 'LocalMachine'", script)
		# La clave privada se borra siempre: nadie puede firmar nada más con ella.
		self.assertIn("-DeleteKey", script)
		self.assertIn("NonExportable", script)
		# Con una firma válida de una autoridad no se crea ningún certificado.
		self.assertIn("TIRESIAS:YA_FIRMADO", script)
		self.assertIn(uiaccess.CERT_SUBJECT, script)

	def test_comillas_en_la_ruta(self) -> None:
		script = uiaccess.signScript(r"C:\Program Files\O'Brien\Tiresias.exe")
		self.assertIn(r"'C:\Program Files\O''Brien\Tiresias.exe'", script)

	def test_guion_de_borrado(self) -> None:
		script = uiaccess.removeScript()
		self.assertIn("Remove-TiresiasCerts", script)
		self.assertNotIn("New-SelfSignedCertificate", script)

	def test_guion_valido_para_powershell(self) -> None:
		"""El guion se analiza sin errores (sin ejecutarlo)."""
		ps = uiaccess._powershellExe()
		if not os.path.isfile(ps):
			self.skipTest("PowerShell no está disponible")
		for script in (uiaccess.signScript(r"C:\x\y.exe"), uiaccess.removeScript()):
			check = "$e = $null; [void][System.Management.Automation.Language.Parser]::ParseInput($env:TIRESIAS_PS, [ref]$null, [ref]$e); if ($e.Count) { $e | ForEach-Object { $_.Message }; exit 1 }"
			res = subprocess.run(
				[ps, "-NoProfile", "-NonInteractive", "-Command", check],
				capture_output=True,
				env={**os.environ, "TIRESIAS_PS": script},
				timeout=60,
				creationflags=uiaccess.CREATE_NO_WINDOW,
			)
			self.assertEqual(res.returncode, 0, res.stdout.decode("mbcs", "replace"))


class ActivarTests(TempDir):
	def program(self) -> str:
		folder = os.path.join(self.tmp, "Archivos de programa", "Tiresias")
		self.write(folder, uiaccess.EXE_NAME, "normal")
		self.write(folder, uiaccess.UIACCESS_EXE, "uiaccess")
		self.write(folder, uiaccess.NO_UIACCESS_EXE, "normal")
		return folder

	def locations(self) -> list[str]:
		return [os.path.join(self.tmp, "Archivos de programa")]

	def test_firma_y_sustituye(self) -> None:
		folder = self.program()
		scripts = []

		def runner(script: str):
			scripts.append(script)
			# El guion firma el archivo temporal: se simula añadiéndole la firma.
			with open(os.path.join(folder, uiaccess.SIGNING_TMP), "a", encoding="utf-8") as f:
				f.write("+firma")
			return True, "TIRESIAS:FIRMADO"

		self.assertTrue(uiaccess.enable(folder, self.locations(), runner))
		self.assertEqual(self.read(folder, uiaccess.EXE_NAME), "uiaccess+firma")
		self.assertEqual(self.read(folder, uiaccess.NO_UIACCESS_EXE), "normal")
		self.assertEqual(self.read(folder, uiaccess.UIACCESS_EXE), "uiaccess")
		self.assertFalse(os.path.exists(os.path.join(folder, uiaccess.SIGNING_TMP)))
		self.assertEqual(len(scripts), 1)
		self.assertIn(os.path.join(folder, uiaccess.SIGNING_TMP).replace("'", "''"), scripts[0])

	def test_si_falla_la_firma_queda_como_antes(self) -> None:
		folder = self.program()
		self.assertFalse(uiaccess.enable(folder, self.locations(), lambda s: (False, "Acceso denegado")))
		self.assertEqual(self.read(folder, uiaccess.EXE_NAME), "normal")
		self.assertFalse(os.path.exists(os.path.join(folder, uiaccess.SIGNING_TMP)))

	def test_fuera_de_carpeta_protegida_no_se_firma(self) -> None:
		folder = self.program()
		runner = mock.Mock()
		self.assertFalse(uiaccess.enable(folder, [os.path.join(self.tmp, "otra")], runner))
		runner.assert_not_called()
		self.assertEqual(self.read(folder, uiaccess.EXE_NAME), "normal")

	def test_version_sin_ejecutable_uiaccess(self) -> None:
		folder = self.program()
		os.remove(os.path.join(folder, uiaccess.UIACCESS_EXE))
		runner = mock.Mock()
		self.assertFalse(uiaccess.enable(folder, self.locations(), runner))
		runner.assert_not_called()

	def test_conserva_el_normal_si_no_venia(self) -> None:
		folder = self.program()
		os.remove(os.path.join(folder, uiaccess.NO_UIACCESS_EXE))
		uiaccess.enable(folder, self.locations(), lambda s: (True, "TIRESIAS:YA_FIRMADO"))
		self.assertEqual(self.read(folder, uiaccess.NO_UIACCESS_EXE), "normal")
		self.assertEqual(self.read(folder, uiaccess.EXE_NAME), "uiaccess")


class InstaladorTests(TempDir):
	def test_instalar_sin_registro_no_firma(self) -> None:
		"""Las pruebas del instalador (sin registro) nunca llaman a PowerShell."""
		src = os.path.join(self.tmp, "origen")
		self.write(src, "Tiresias.exe", "normal")
		self.write(src, uiaccess.UIACCESS_EXE, "uiaccess")
		self.write(src, uiaccess.NO_UIACCESS_EXE, "normal")
		target = os.path.join(self.tmp, "destino")
		targets = installer.SystemTargets(allUsers=True, writeRegistry=False, startMenuDir=os.path.join(self.tmp, "menu"), desktopDir=os.path.join(self.tmp, "escritorio"))
		opts = installer.InstallOptions(targetDir=target, sourceDir=src, targets=targets, startMenu=False, desktopShortcut=False, launchAfter=False)
		with mock.patch.object(uiaccess, "enable") as enable:
			installer.install(opts)
		enable.assert_not_called()
		self.assertEqual(self.read(target, "Tiresias.exe"), "normal")

	def test_instalar_para_todos_activa_uiaccess(self) -> None:
		src = os.path.join(self.tmp, "origen")
		self.write(src, "Tiresias.exe", "normal")
		target = os.path.join(self.tmp, "destino")
		targets = installer.SystemTargets(allUsers=True, writeRegistry=True)
		opts = installer.InstallOptions(targetDir=target, sourceDir=src, targets=targets, startMenu=False, desktopShortcut=False, launchAfter=False)
		with mock.patch.object(uiaccess, "enable", return_value=True) as enable, mock.patch.object(installer, "_regWrite"), mock.patch.object(installer, "_regReadAll", return_value={}), mock.patch.object(installer, "removeRunAtLogonIfFrom"):
			installer.install(opts)
		enable.assert_called_once_with(target)
		import json

		with open(os.path.join(target, installer.paths.INSTALLED_MARKER), encoding="utf-8") as f:
			self.assertTrue(json.load(f)["uiAccess"])

	def test_instalar_para_un_usuario_no_activa_uiaccess(self) -> None:
		src = os.path.join(self.tmp, "origen")
		self.write(src, "Tiresias.exe", "normal")
		target = os.path.join(self.tmp, "destino")
		targets = installer.SystemTargets(allUsers=False, writeRegistry=True)
		opts = installer.InstallOptions(targetDir=target, sourceDir=src, allUsers=False, targets=targets, startMenu=False, desktopShortcut=False, launchAfter=False)
		with mock.patch.object(uiaccess, "enable") as enable, mock.patch.object(installer, "_regWrite"), mock.patch.object(installer, "_regReadAll", return_value={}), mock.patch.object(installer, "removeRunAtLogonIfFrom"):
			installer.install(opts)
		enable.assert_not_called()

	def test_copia_portable_desde_la_instalada_lleva_el_normal(self) -> None:
		app = os.path.join(self.tmp, "instalada")
		self.write(app, "Tiresias.exe", "uiaccess+firma")
		self.write(app, uiaccess.UIACCESS_EXE, "uiaccess")
		self.write(app, uiaccess.NO_UIACCESS_EXE, "normal")
		data = os.path.join(self.tmp, "datos")
		os.makedirs(data)
		dest = os.path.join(self.tmp, "portable")
		installer.createPortableCopy(dest, copyConfig=False, copyAddons=False, appDir=app, dataDir=data, programDataDir=data, frozen=True)
		self.assertEqual(self.read(dest, "Tiresias.exe"), "normal")

	def test_desinstalar_quita_el_certificado(self) -> None:
		target = os.path.join(self.tmp, "instalada")
		self.write(target, "Tiresias.exe", "uiaccess+firma")
		self.write(target, uiaccess.NO_UIACCESS_EXE, "normal")
		self.write(target, installer.paths.INSTALLED_MARKER, "{}")
		targets = installer.SystemTargets(allUsers=True, writeRegistry=True)
		with mock.patch.object(uiaccess, "removeCertificates") as remove, mock.patch.object(installer, "_regReadAll", return_value={}), mock.patch.object(installer, "_regDeleteKey"), mock.patch.object(installer, "removeRunAtLogonIfFrom"), mock.patch(
			"tiresias.remote.rdp_registration.unregisterIfFrom"
		), mock.patch("tiresias.secure_screens.unregisterIfFrom"):
			installer.uninstall(target, targets)
		remove.assert_called_once_with()


class LanzarTests(unittest.TestCase):
	def test_popen_normal(self) -> None:
		with mock.patch.object(uiaccess.subprocess, "Popen") as popen, mock.patch.object(uiaccess, "shellExecute") as shell:
			uiaccess.spawn(["a.exe", "--x"], cwd="C:\\")
		popen.assert_called_once()
		shell.assert_not_called()

	def test_error_740_usa_shellexecute(self) -> None:
		err = OSError(13, "Elevation required")
		err.winerror = uiaccess.ERROR_ELEVATION_REQUIRED
		with mock.patch.object(uiaccess.subprocess, "Popen", side_effect=err), mock.patch.object(uiaccess, "shellExecute") as shell:
			uiaccess.spawn(["C:\\Program Files\\Tiresias\\Tiresias.exe", "--data", "x"])
		shell.assert_called_once_with(["C:\\Program Files\\Tiresias\\Tiresias.exe", "--data", "x"], None)

	def test_otros_errores_se_propagan(self) -> None:
		err = OSError(2, "No existe")
		err.winerror = 2
		with mock.patch.object(uiaccess.subprocess, "Popen", side_effect=err), mock.patch.object(uiaccess, "shellExecute") as shell:
			with self.assertRaises(OSError):
				uiaccess.spawn(["no.exe"])
		shell.assert_not_called()

	def test_shellexecute_de_verdad(self) -> None:
		"""ShellExecuteEx inicia un proceso, da su PID y se puede esperar."""
		cmd = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe")
		proc = uiaccess.shellExecute([cmd, "/c", "exit", "7"])
		self.assertTrue(proc.pid)
		self.assertEqual(proc.wait(20), 7)
		self.assertEqual(proc.poll(), 7)


class ComTests(unittest.TestCase):
	def test_sin_uiaccess_no_usa_el_auxiliar(self) -> None:
		with mock.patch("comtypes.client.GetActiveObject", side_effect=OSError("MK_E_UNAVAILABLE")), mock.patch.object(uiaccess, "_getActiveObjectFromHelper") as helper:
			with self.assertRaises(OSError):
				uiaccess.getActiveObject("Outlook.Application")
		helper.assert_not_called()

	def test_con_uiaccess_usa_el_auxiliar(self) -> None:
		with mock.patch("comtypes.client.GetActiveObject", side_effect=OSError("MK_E_UNAVAILABLE")), mock.patch.object(uiaccess, "hasUiAccess", return_value=True), mock.patch.object(
			uiaccess, "_helperExecutable", return_value="C:\\x\\Tiresias_noUIAccess.exe"
		), mock.patch.object(uiaccess, "_getActiveObjectFromHelper", return_value="objeto") as helper:
			self.assertEqual(uiaccess.getActiveObject("Outlook.Application"), "objeto")
		helper.assert_called_once_with("C:\\x\\Tiresias_noUIAccess.exe", "Outlook.Application", True)

	def test_auxiliar_de_verdad(self) -> None:
		"""El auxiliar (el código fuente) pasa un objeto COM con LresultFromObject.

		Se registra un objeto en la ROT con un ProgID del sistema que siempre
		existe no es posible sin Office; se comprueba al menos que, sin el
		objeto, el auxiliar contesta «error» y termina al cerrar la entrada.
		"""
		exe = os.path.join(os.path.dirname(sys.executable), "python.exe")
		script = os.path.join(ROOT, "src", "tiresias.pyw")
		p = subprocess.Popen([exe, "-X", "utf8", script, uiaccess.COM_HELPER_ARG, "Tiresias.NoExiste.Nunca"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, creationflags=uiaccess.CREATE_NO_WINDOW)
		try:
			line = p.stdout.readline().strip()
			self.assertEqual(line, b"error")
		finally:
			p.stdin.close()
			self.assertEqual(p.wait(30), 1)
			p.stdout.close()


if __name__ == "__main__":
	unittest.main()
