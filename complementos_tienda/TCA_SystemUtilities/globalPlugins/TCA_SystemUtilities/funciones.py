"""Las acciones de TCA SystemUtilities.

Cada acción es una función ``accion(ctx)`` que se llama en el hilo de la
interfaz (algunas preguntan o muestran un diálogo) con el :class:`Contexto`
de la ventana activa cuando se pidió. Lo que tarda (o espera el permiso de
administrador) se hace en un hilo propio con :func:`ejecutor.enHilo`.

:data:`ACCIONES` es el catálogo: identificador, etiqueta del menú,
descripción de la orden y submenú.
"""

from __future__ import annotations

import os
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass

from . import consolas, dialogos, ejecutor, explorador, procesos
from .explorador import Contexto

SECCION = "TCA_SystemUtilities"
DEFECTOS = {"preguntarPerfilLimpieza": True}

MSG_CANCELADO = "No se concedió el permiso de administrador: no se ha hecho nada."
MSG_NO_ABRE = "No se pudo abrir {}."
TITULO_ATENCION_REINICIO = "Atención: reinicio necesario"

#: Clave de registro que devuelve el menú contextual clásico en Windows 11.
CLAVE_MENU_CLASICO = r"Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}"
CLAVE_UAC = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
#: Valores de ConsentPromptBehaviorAdmin: 0 = elevar sin preguntar (UAC desactivado);
#: 5 = preguntar por los programas que no son de Windows (el valor de fábrica).
UAC_DESACTIVADO = 0
UAC_ACTIVADO = 5


# ====================================================================== avisos
def mensaje(texto: str) -> None:
	"""Habla (y muestra en braille) un mensaje desde cualquier hilo."""
	from tiresias import queue_handler, speech

	def hablar() -> None:
		# Responde a una orden del usuario: se oye también con la voz «a demanda».
		with speech.allowOnDemand():
			speech.speakMessage(texto)

	queue_handler.queueFunction(hablar)


def pitido(hz: int = 950, ms: int = 50) -> None:
	from tiresias import queue_handler
	from tiresias.audio import tones

	queue_handler.queueFunction(tones.beep, hz, ms)


def copiar(texto: str) -> bool:
	from tiresias import api

	return bool(api.copyToClip(texto))


def opcion(clave: str):
	try:
		from tiresias.config import conf

		return conf[SECCION][clave]
	except Exception:
		return DEFECTOS.get(clave)


def ponerOpcion(clave: str, valor) -> None:
	from tiresias.config import conf

	conf[SECCION][clave] = valor


def registrarOpciones() -> None:
	from tiresias.config import conf

	conf.registerDefaults(SECCION, DEFECTOS)


def _hilo(func: Callable, *args) -> None:
	ejecutor.enHilo(_protegido, func, *args)


def _protegido(func: Callable, *args) -> None:
	"""Ejecuta el trabajo y avisa de los errores (permiso denegado incluido)."""
	try:
		func(*args)
	except ejecutor.Cancelado:
		mensaje(MSG_CANCELADO)
	except Exception as e:
		from tiresias.log import getLogger

		getLogger("TCA_SystemUtilities").debug("Error en una acción", exc_info=True)
		mensaje(f"Se produjo un error: {e}")


def _elevadoCmd(orden: str, esperar: bool = True, visible: bool = False, pausa: bool = False) -> int:
	return ejecutor.elevado(ejecutor.CMD, ejecutor.cmdParametros(orden, pausa=pausa), esperar=esperar, mostrar=ejecutor.SW_SHOWNORMAL if visible else ejecutor.SW_HIDE)


def _elevadoPs(script: str) -> int:
	return ejecutor.elevado(ejecutor.powershell(), ejecutor.psParametros(script), esperar=True)


def _abrirPrograma(nombre: str, archivo: str, parametros: str | None = None, carpeta: str | None = None) -> None:
	def trabajo() -> None:
		if not ejecutor.abrir(archivo, parametros, carpeta):
			mensaje(MSG_NO_ABRE.format(nombre))

	_hilo(trabajo)


# ====================================================================== sonido de apagado
def duracionWav(ruta: str) -> float:
	"""Duración en segundos de un archivo WAV (0 si no se puede leer)."""
	try:
		with open(ruta, "rb") as f:
			cab = f.read(12)
			if len(cab) < 12 or cab[:4] != b"RIFF" or cab[8:12] != b"WAVE":
				return 0.0
			bytesPorSegundo = 0
			while True:
				trozo = f.read(8)
				if len(trozo) < 8:
					return 0.0
				ident, tam = trozo[:4], struct.unpack("<I", trozo[4:])[0]
				if ident == b"fmt ":
					fmt = f.read(tam)
					bytesPorSegundo = struct.unpack("<I", fmt[8:12])[0] if len(fmt) >= 12 else 0
					if tam % 2:
						f.read(1)
				elif ident == b"data":
					return tam / bytesPorSegundo if bytesPorSegundo else 0.0
				else:
					f.seek(tam + (tam % 2), 1)
	except Exception:
		return 0.0


def rutaSonidoApagado() -> str:
	return ejecutor.windows("Media", "Windows Shutdown.wav")


def sonidoApagado(maximo: float = 6.0) -> None:
	"""Reproduce el sonido clásico de cierre de Windows y espera a que termine (en un hilo)."""
	ruta = rutaSonidoApagado()
	if not os.path.isfile(ruta):
		return
	from tiresias.audio import tones

	tones.playWaveFile(ruta)
	time.sleep(min(duracionWav(ruta), maximo))


# ====================================================================== apagado del sistema
def _apagarOReiniciar(aviso: str, modo: str, fallo: str) -> None:
	mensaje(aviso)

	def trabajo() -> None:
		sonidoApagado()
		codigo, _s = ejecutor.oculto([ejecutor.SHUTDOWN, modo, "/t", "3"])
		if codigo != 0:
			mensaje(fallo)

	_hilo(trabajo)


def apagar(ctx: Contexto) -> None:
	_apagarOReiniciar("Apagando el PC. Tiene 3 segundos para anularlo.", "/s", "No se pudo apagar el PC.")


def reiniciar(ctx: Contexto) -> None:
	_apagarOReiniciar("Reiniciando el PC. Tiene 3 segundos para anularlo.", "/r", "No se pudo reiniciar el PC.")


#: shutdown /a cuando no hay ningún apagado en curso.
ERROR_NO_SHUTDOWN_IN_PROGRESS = 1116


def anularApagado(ctx: Contexto) -> None:
	def trabajo() -> None:
		codigo, _s = ejecutor.oculto([ejecutor.SHUTDOWN, "/a"])
		if codigo == 0:
			mensaje("Anulando el apagado o reinicio del PC.")
		elif codigo == ERROR_NO_SHUTDOWN_IN_PROGRESS:
			mensaje("No hay ningún apagado ni reinicio en curso.")
		else:
			mensaje("No se pudo anular el apagado o reinicio del PC.")

	_hilo(trabajo)


def hibernar(ctx: Contexto) -> None:
	mensaje("Hibernando el sistema")

	def trabajo() -> None:
		time.sleep(1)
		codigo, _s = ejecutor.oculto([ejecutor.SHUTDOWN, "/h"])
		if codigo != 0:
			mensaje("No se pudo hibernar el sistema. Puede que la hibernación esté desactivada en este equipo.")

	_hilo(trabajo)


def _setSuspendState() -> bool:
	import ctypes

	powrprof = ctypes.WinDLL("powrprof")
	powrprof.SetSuspendState.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_ubyte]
	powrprof.SetSuspendState.restype = ctypes.c_ubyte
	# Suspender (no hibernar), sin forzar y sin desactivar los eventos de activación.
	return bool(powrprof.SetSuspendState(0, 0, 0))


#: Se sustituye en las pruebas.
suspenderSistema: Callable[[], bool] = _setSuspendState


def suspender(ctx: Contexto) -> None:
	mensaje("Suspendiendo el sistema")

	def trabajo() -> None:
		time.sleep(1)
		if not suspenderSistema():
			mensaje("No se pudo suspender el sistema.")

	_hilo(trabajo)


def entrarBios(ctx: Contexto) -> None:
	texto = (
		"Está a punto de activar la entrada a la BIOS-UEFI.\n"
		"El PC se va a reiniciar en unos segundos.\n"
		"Recuerde que en la BIOS-UEFI no podrá utilizar un lector de pantalla: tendrá que pedir ayuda visual. "
		"Para volver a Windows sin cambiar nada puede pulsar Control+Alt+Supr.\n"
		"¿Está seguro de que desea continuar?"
	)
	if not dialogos.preguntar(texto, "Atención: se intentará entrar en la BIOS-UEFI"):
		return

	def trabajo() -> None:
		codigo = ejecutor.elevado(ejecutor.SHUTDOWN, "/r /fw /t 3", esperar=True)
		if codigo == 0:
			mensaje("El PC se reinicia y entrará en la BIOS-UEFI.")
		else:
			mensaje("No se pudo reiniciar en la BIOS-UEFI. Puede que el equipo no tenga firmware UEFI.")

	_hilo(trabajo)


def _reiniciarConSonido() -> None:
	sonidoApagado()
	ejecutor.oculto([ejecutor.SHUTDOWN, "/r", "/t", "3"])


def modoSeguro(ctx: Contexto) -> None:
	texto = (
		"Está a punto de reiniciar el sistema y activar el Modo seguro con funciones de red.\n"
		"En este modo, los sistemas Windows anteriores al 10 puede que no tengan sonido y, por tanto, el lector de pantalla no tendrá voz.\n"
		"Deberá deshabilitar este modo desde la configuración del sistema (msconfig) o con TCA SystemUtilities, en el apartado «Apagado del sistema», opción «Reiniciar en Modo normal».\n"
		"¿Está seguro de que desea continuar?"
	)
	if not dialogos.preguntar(texto, "Atención: activación del Modo seguro"):
		return

	def trabajo() -> None:
		codigo = _elevadoCmd("bcdedit /set {default} safeboot network")
		if codigo != 0:
			mensaje(f"No se pudo activar el Modo seguro (código {codigo}).")
			return
		mensaje("Modo seguro activado, se va a reiniciar el PC")
		_reiniciarConSonido()

	_hilo(trabajo)


def modoNormal(ctx: Contexto) -> None:
	def trabajo() -> None:
		# safebootalternateshell también, por si lo dejó puesto el complemento de NVDA.
		codigo = _elevadoCmd("bcdedit /deletevalue {default} safebootalternateshell >nul 2>&1 & bcdedit /deletevalue {default} safeboot")
		if codigo != 0:
			mensaje("No se pudo desactivar el Modo seguro. Puede que no estuviera activado.")
			return
		mensaje("Modo normal, reiniciando el PC")
		_reiniciarConSonido()

	_hilo(trabajo)


# ====================================================================== explorador y procesos
def _reiniciarExploradorAhora() -> None:
	"""Cierra el Explorador y lo vuelve a iniciar si Windows no lo hace solo."""
	ejecutor.oculto([ejecutor.TASKKILL, "/f", "/im", "explorer.exe"])
	for _i in range(6):
		time.sleep(0.5)
		if _exploradorEnMarcha():
			return
	ejecutor.abrir(ejecutor.windows("explorer.exe"))


def _exploradorEnMarcha() -> bool:
	try:
		import psutil

		return any((p.info.get("name") or "").lower() == "explorer.exe" for p in psutil.process_iter(["name"]))
	except Exception:
		return False


def reiniciarExplorador(ctx: Contexto) -> None:
	mensaje("Reiniciando el Explorador de Windows")

	def trabajo() -> None:
		_reiniciarExploradorAhora()
		pitido()

	_hilo(trabajo)


def _vaciarPortapapeles() -> bool:
	from tiresias import clipboard, winapi

	for _i in range(5):
		if winapi.user32.OpenClipboard(None):
			break
		time.sleep(0.05)
	else:
		return False
	try:
		clipboard.ignoreNextChange()
		return bool(winapi.user32.EmptyClipboard())
	finally:
		winapi.user32.CloseClipboard()


PS_BORRAR_HISTORIAL = """$ErrorActionPreference = 'Stop'
try {
	Add-Type -AssemblyName System.Runtime.WindowsRuntime
	$null = [Windows.ApplicationModel.DataTransfer.Clipboard, Windows.ApplicationModel.DataTransfer, ContentType = WindowsRuntime]
	if ([Windows.ApplicationModel.DataTransfer.Clipboard]::ClearHistory()) { exit 0 } else { exit 1 }
} catch { exit 2 }
"""
PS_REINICIAR_SERVICIO_PORTAPAPELES = """$ErrorActionPreference = 'Stop'
try { Get-Service -Name 'cbdhsvc*' | Restart-Service -Force; exit 0 } catch { exit 1 }
"""


def borrarPortapapeles(ctx: Contexto) -> None:
	def trabajo() -> None:
		vacio = _vaciarPortapapeles()
		codigo, _s = ejecutor.oculto(ejecutor.psArgumentos(PS_BORRAR_HISTORIAL), 30)
		historial = codigo == 0
		if not historial:
			# Como el original: reiniciar el servicio del portapapeles (necesita permisos).
			try:
				historial = _elevadoPs(PS_REINICIAR_SERVICIO_PORTAPAPELES) == 0
			except (ejecutor.Cancelado, OSError):
				historial = False
		if vacio and historial:
			mensaje("Se limpió correctamente el portapapeles y su historial")
		elif vacio:
			mensaje("Se vació el portapapeles, pero no se pudo borrar su historial")
		elif historial:
			mensaje("Se borró el historial del portapapeles, pero no se pudo vaciar el portapapeles")
		else:
			mensaje("No fue posible borrar el portapapeles")

	_hilo(trabajo)


def _textoResultado(res: procesos.Resultado, ninguno: str, hechos: str) -> str:
	if not res.terminados and not res.fallidos:
		return ninguno
	partes = []
	if res.terminados:
		partes.append(hechos.format(n=len(res.terminados), nombres=", ".join(sorted(set(res.terminados), key=str.casefold))))
	if res.fallidos:
		partes.append("No se pudieron cerrar {}: {}.".format(len(res.fallidos), ", ".join(sorted(set(res.fallidos), key=str.casefold))))
	if res.cancelado:
		partes.append("No se concedió el permiso de administrador.")
	return " ".join(partes)


def cerrarTodas(ctx: Contexto) -> None:
	texto = (
		"Se van a cerrar a la fuerza todas las aplicaciones abiertas (también las que están en segundo plano), excepto Tiresias, "
		"los lectores de pantalla y los componentes de Windows.\n"
		"No se podrán guardar los documentos ni los proyectos abiertos.\n"
		"¿Está seguro de que desea continuar?"
	)
	if not dialogos.preguntar(texto, "Atención: cerrar todas las aplicaciones"):
		return

	def trabajo() -> None:
		res = procesos.cerrarTodas()
		mensaje(_textoResultado(res, "No hay aplicaciones que cerrar.", "Se cerraron {n} procesos: {nombres}."))

	_hilo(trabajo)


def cerrarNoResponden(ctx: Contexto) -> None:
	def trabajo() -> None:
		res = procesos.cerrarNoResponden()
		mensaje(_textoResultado(res, "No hay tareas que no respondan.", "Se cerraron {n} tareas que no respondían: {nombres}."))

	_hilo(trabajo)


def matarProcesos(ctx: Contexto) -> None:
	nombre = dialogos.pedirTexto("Escriba aquí el nombre de la aplicación", "Ingrese el nombre:")
	if nombre is None:
		return
	nombre = nombre.strip()
	if not nombre:
		mensaje("Debe escribir el nombre de una aplicación")
		return

	def trabajo() -> None:
		res = procesos.terminarPorNombre(nombre)
		if not res.terminados and not res.fallidos:
			mensaje(f"No se encontró ningún proceso de: {nombre}")
		elif not res.fallidos:
			mensaje(f"Se terminaron todos los procesos de: {nombre} de forma correcta")
		else:
			mensaje(_textoResultado(res, "", "Se terminaron {n} procesos: {nombres}."))

	_hilo(trabajo)


def _menuContexto(clasico: bool) -> None:
	import winreg

	if clasico:
		with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, CLAVE_MENU_CLASICO + r"\InprocServer32", 0, winreg.KEY_SET_VALUE) as k:
			winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "")
		return
	for sub in (CLAVE_MENU_CLASICO + r"\InprocServer32", CLAVE_MENU_CLASICO):
		try:
			winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
		except FileNotFoundError:
			pass


def menuContextoClasico(ctx: Contexto) -> None:
	def trabajo() -> None:
		try:
			_menuContexto(True)
		except OSError:
			mensaje("No se pudo modificar el menú de contexto")
			return
		mensaje("Menú de contexto clásico habilitado. Se reinicia el Explorador.")
		_reiniciarExploradorAhora()

	_hilo(trabajo)


def menuContexto11(ctx: Contexto) -> None:
	def trabajo() -> None:
		try:
			_menuContexto(False)
		except OSError:
			mensaje("No se pudo modificar el menú de contexto")
			return
		mensaje("Menú de contexto tipo Windows 11 habilitado. Se reinicia el Explorador.")
		_reiniciarExploradorAhora()

	_hilo(trabajo)


def monitorRecursos(ctx: Contexto) -> None:
	_abrirPrograma("el Monitor de recursos", ejecutor.system32("resmon.exe"))


# ====================================================================== reparación y optimización
def _almacenamientoReservado(activar: bool) -> None:
	estado = "Enabled" if activar else "Disabled"

	def trabajo() -> None:
		codigo = _elevadoCmd(f"DISM.exe /Online /Set-ReservedStorageState /State:{estado}")
		if codigo == 0:
			mensaje("Se activó el almacenamiento reservado" if activar else "Se desactivó el almacenamiento reservado")
		else:
			mensaje(f"No fue posible cambiar el almacenamiento reservado (código {codigo}). Si hay actualizaciones pendientes, reinicie e inténtelo de nuevo.")

	_hilo(trabajo)


def activarReservado(ctx: Contexto) -> None:
	_almacenamientoReservado(True)


def desactivarReservado(ctx: Contexto) -> None:
	_almacenamientoReservado(False)


def _planEnergia(esquema: str, nombre: str) -> None:
	def trabajo() -> None:
		codigo, _s = ejecutor.oculto([ejecutor.system32("powercfg.exe"), "/setactive", esquema])
		if codigo == 0:
			mensaje(f"Plan {nombre} activado")
		else:
			mensaje(f"No fue posible activar el plan {nombre}. Puede que este equipo no lo tenga.")

	_hilo(trabajo)


def planAltoRendimiento(ctx: Contexto) -> None:
	_planEnergia("SCHEME_MIN", "alto rendimiento")


def planEquilibrado(ctx: Contexto) -> None:
	_planEnergia("SCHEME_BALANCED", "equilibrado")


def analisisSfc(ctx: Contexto) -> None:
	_hilo(_elevadoCmd, "sfc /scannow", False, True, True)


def repararDism(ctx: Contexto) -> None:
	_hilo(_elevadoCmd, "DISM /Online /Cleanup-Image /RestoreHealth", False, True, True)


def limpiarDns(ctx: Contexto) -> None:
	def trabajo() -> None:
		codigo, _s = ejecutor.oculto([ejecutor.system32("ipconfig.exe"), "/flushdns"])
		if codigo != 0:
			codigo = _elevadoCmd("ipconfig /flushdns")
		mensaje("Se limpió la caché DNS" if codigo == 0 else "No se pudo limpiar la caché DNS")

	_hilo(trabajo)


def carpetaConfigSistema() -> str:
	from tiresias import paths

	return paths.SYSTEM_CONFIG_DIR


def _quitarConfigSistema() -> None:
	from tiresias import installer

	installer.removeSystemConfig()


def limpiarPantallasSeguras(ctx: Contexto) -> None:
	if not os.path.isdir(carpetaConfigSistema()):
		mensaje("No existen configuraciones guardadas en pantallas seguras")
		return
	texto = (
		"Este proceso eliminará la configuración de Tiresias que se copió para usarla en las pantallas seguras "
		"(inicio de sesión, Control de cuentas de usuario, Control+Alt+Supr): en ellas Tiresias volverá a funcionar con la configuración de fábrica.\n"
		"Si Tiresias está instalado en Archivos de programa, tendrá que darle permiso de administrador.\n"
		"¿Está seguro de que desea continuar?"
	)
	if not dialogos.preguntar(texto, "Atención: borrando la configuración de las pantallas seguras"):
		return

	def trabajo() -> None:
		try:
			_quitarConfigSistema()
		except OSError:
			mensaje("No se pudo limpiar la configuración en pantallas seguras")
			return
		pitido()
		mensaje("Se limpió la configuración en pantallas seguras")

	_hilo(trabajo)


def limpiarDisco(ctx: Contexto) -> None:
	cleanmgr = ejecutor.system32("cleanmgr.exe")
	crear = False
	if opcion("preguntarPerfilLimpieza"):
		respuesta, noMostrar = dialogos.perfilLimpieza()
		if noMostrar:
			ponerOpcion("preguntarPerfilLimpieza", False)
		if respuesta is None:
			return
		crear = respuesta == dialogos.CREAR_PERFIL

	def trabajo() -> None:
		if crear:
			# Se espera a que se cierre el perfil antes de limpiar (el original
			# lanzaba las dos cosas a la vez y el limpiador podía cerrarse).
			ejecutor.elevado(cleanmgr, "/sageset:1", esperar=True, mostrar=ejecutor.SW_SHOWNORMAL)
		ejecutor.elevado(cleanmgr, "/sagerun:1", esperar=False, mostrar=ejecutor.SW_SHOWNORMAL)

	_hilo(trabajo)


def optimizarUnidades(ctx: Contexto) -> None:
	_abrirPrograma("Optimizar las unidades", ejecutor.system32("dfrgui.exe"))


def restablecerPC(ctx: Contexto) -> None:
	_abrirPrograma("Restablecer este PC", "ms-settings:recovery")


# ====================================================================== seguridad de Windows
def leerUac() -> tuple[int | None, int | None]:
	"""(ConsentPromptBehaviorAdmin, EnableLUA) actuales."""
	import winreg

	valores: list[int | None] = []
	for nombre in ("ConsentPromptBehaviorAdmin", "EnableLUA"):
		try:
			with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, CLAVE_UAC, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
				valores.append(int(winreg.QueryValueEx(k, nombre)[0]))
		except OSError:
			valores.append(None)
	return valores[0], valores[1]


def ordenUac(nivel: int) -> str:
	clave = "HKLM\\" + CLAVE_UAC
	return f'reg add "{clave}" /v ConsentPromptBehaviorAdmin /t REG_DWORD /d {nivel} /f && reg add "{clave}" /v EnableLUA /t REG_DWORD /d 1 /f'


def _cambiarUac(activar: bool) -> None:
	nombre = "activado" if activar else "desactivado"
	_nivel, luaAntes = leerUac()

	def trabajo() -> None:
		codigo = _elevadoCmd(ordenUac(UAC_ACTIVADO if activar else UAC_DESACTIVADO))
		if codigo != 0:
			mensaje("No fue posible {} el control de cuentas de usuario (código {}).".format("activar" if activar else "desactivar", codigo))
			return
		if luaAntes == 1:
			mensaje(f"Se ha {nombre} el control de cuentas de usuario (uac). El cambio ya está en vigor.")
			return
		from tiresias.gui.helpers import runOnGui

		runOnGui(_preguntarReinicioUac, nombre)

	_hilo(trabajo)


def _preguntarReinicioUac(nombre: str) -> None:
	texto = f"Se ha {nombre} el control de cuentas de usuario (uac).\nEs necesario reiniciar el sistema para que surtan efecto los cambios.\n¿Desea hacerlo ahora?"
	if dialogos.preguntar(texto, TITULO_ATENCION_REINICIO):
		_hilo(_reiniciarConSonido)


def activarUac(ctx: Contexto) -> None:
	_cambiarUac(True)


def desactivarUac(ctx: Contexto) -> None:
	_cambiarUac(False)


def rutaMpCmdRun() -> str:
	base = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles") or r"C:\Program Files"
	return os.path.join(base, "Windows Defender", "MpCmdRun.exe")


def _defender(argumentos: str, nombre: str) -> None:
	exe = rutaMpCmdRun()
	if not os.path.isfile(exe):
		mensaje("No se encontró el antivirus de Windows (Microsoft Defender).")
		return
	mensaje(f"{nombre}: se abre una ventana de consola con el progreso.")
	_hilo(_elevadoCmd, f'"{exe}" {argumentos}', False, True, True)


def analisisRapido(ctx: Contexto) -> None:
	_defender("-Scan -ScanType 1", "Análisis rápido")


def analisisCompleto(ctx: Contexto) -> None:
	_defender("-Scan -ScanType 2", "Análisis completo")


def analisisArranque(ctx: Contexto) -> None:
	# El análisis del sector de arranque solo vale en un análisis personalizado:
	# se analiza el arranque y la carpeta Boot de Windows.
	carpeta = ejecutor.windows("Boot")
	if not os.path.isdir(carpeta):
		carpeta = os.environ.get("SystemDrive", "C:") + "\\"
	_defender(f'-Scan -ScanType 3 -File "{carpeta}" -BootSectorScan', "Análisis del sector de arranque")


def _archivosComprimidos(escanear: bool) -> None:
	script = "$ErrorActionPreference = 'Stop'\ntry {{ Set-MpPreference -DisableArchiveScanning ${}; exit 0 }} catch {{ exit 1 }}\n".format("false" if escanear else "true")

	def trabajo() -> None:
		codigo = _elevadoPs(script)
		if codigo == 0:
			mensaje("Se activó el escaneo de archivos comprimidos" if escanear else "Se desactivó el escaneo de archivos comprimidos")
		else:
			mensaje("No fue posible cambiar el escaneo de archivos comprimidos.")

	_hilo(trabajo)


def escanearComprimidos(ctx: Contexto) -> None:
	_archivosComprimidos(True)


def noEscanearComprimidos(ctx: Contexto) -> None:
	_archivosComprimidos(False)


def _archivoTemporal(nombre: str) -> str:
	from tiresias import paths

	return os.path.join(paths.addonDataDir(SECCION), nombre)


def cuarentena(ctx: Contexto) -> None:
	exe = rutaMpCmdRun()
	if not os.path.isfile(exe):
		mensaje("No se encontró el antivirus de Windows (Microsoft Defender).")
		return

	def trabajo() -> None:
		salida = _archivoTemporal("cuarentena.txt")
		try:
			os.remove(salida)
		except OSError:
			pass
		codigo = _elevadoCmd(f'"{exe}" -Restore -ListAll > "{salida}" 2>&1')
		try:
			with open(salida, "rb") as f:
				texto = ejecutor.decodificar(f.read()).strip()
		except OSError:
			texto = ""
		finally:
			try:
				os.remove(salida)
			except OSError:
				pass
		if not texto:
			mensaje(f"No se pudo obtener la lista de archivos en cuarentena (código {codigo}).")
			return
		if copiar(texto):
			mensaje("Lista de archivos en cuarentena copiada al portapapeles")
		else:
			mensaje("No se pudo copiar la lista al portapapeles")

	_hilo(trabajo)


# ====================================================================== voz y multimedia
#: Cámaras: la clase «Camera» o un nombre que lo diga (las antiguas son de la clase «Image»).
_PS_CAMARAS = "@(Get-PnpDevice -PresentOnly | Where-Object { $_.Class -eq 'Camera' -or $_.FriendlyName -like '*webcam*' -or $_.FriendlyName -like '*camera*' -or $_.FriendlyName -like '*cámara*' })"


def scriptWebcam(activar: bool) -> str:
	orden = "Enable-PnpDevice" if activar else "Disable-PnpDevice"
	return (
		"$ErrorActionPreference = 'Stop'\n"
		"try {\n"
		f"\t$d = {_PS_CAMARAS}\n"
		"\tif ($d.Count -eq 0) { exit 3 }\n"
		f"\t$d | {orden} -Confirm:$false\n"
		"\texit 0\n"
		"} catch { exit 1 }\n"
	)


def _webcam(activar: bool) -> None:
	def trabajo() -> None:
		codigo = _elevadoPs(scriptWebcam(activar))
		if codigo == 0:
			mensaje("Se activó la Webcam" if activar else "Se desactivó la Webcam")
		elif codigo == 3:
			mensaje("No se encontró ninguna webcam en el equipo")
		else:
			mensaje("No se pudo {} la Webcam".format("activar" if activar else "desactivar"))

	_hilo(trabajo)


def activarWebcam(ctx: Contexto) -> None:
	_webcam(True)


def desactivarWebcam(ctx: Contexto) -> None:
	_webcam(False)


def opcionesSonido(ctx: Contexto) -> None:
	_abrirPrograma("el panel de sonido", ejecutor.system32("control.exe"), "mmsys.cpl")


def opcionesVoz(ctx: Contexto) -> None:
	_abrirPrograma("las opciones de voz", ejecutor.system32("Speech", "SpeechUX", "sapi.cpl"))


# ====================================================================== utilidades del sistema
def asistenteCredenciales(ctx: Contexto) -> None:
	_abrirPrograma("el asistente para guardar contraseñas de usuarios", ejecutor.system32("credwiz.exe"))


def bluetooth(ctx: Contexto) -> None:
	_abrirPrograma("el asistente de transferencia de archivos por Bluetooth", ejecutor.system32("fsquirt.exe"))


def carpetaRoaming(ctx: Contexto) -> None:
	ruta = os.environ.get("APPDATA") or os.path.join(os.environ.get("USERPROFILE", ""), "AppData", "Roaming")
	_abrirPrograma("la carpeta Roaming", ruta)


def asistenteContrasena(ctx: Contexto) -> None:
	mensaje("Abriendo el asistente para restablecer contraseñas de Windows")
	_abrirPrograma("el asistente para guardar la contraseña del sistema", ejecutor.system32("rundll32.exe"), "keymgr.dll,PRShowSaveWizardExW")


def mapaCaracteres(ctx: Contexto) -> None:
	_abrirPrograma("el mapa de caracteres", ejecutor.system32("charmap.exe"))


# ====================================================================== archivos y carpetas (Explorador)
#: Se sustituye en las pruebas (usa COM del Shell).
obtenerRutas: Callable[[Contexto], tuple[str | None, str | None]] = explorador.rutas


def _rutasDelExplorador(ctx: Contexto) -> tuple[str | None, str | None] | None:
	"""(foco, carpeta) o ``None`` (ya avisado) si la ventana no es del Explorador."""
	if not ctx.esExplorador:
		mensaje(explorador.MSG_ACTIVE_EXPLORADOR)
		return None
	try:
		return obtenerRutas(ctx)
	except Exception:
		return None, None


def copiarRuta(ctx: Contexto) -> None:
	r = _rutasDelExplorador(ctx)
	if r is None:
		return
	ruta = r[0] or r[1]
	if ruta and copiar(f'"{ruta}"'):
		mensaje("Ruta copiada")
	else:
		mensaje("No se pudo copiar la ruta")


def copiarListado(ctx: Contexto) -> None:
	r = _rutasDelExplorador(ctx)
	if r is None:
		return
	carpeta = explorador.carpetaDe(r[0] or r[1])
	if not carpeta:
		mensaje("No se pudo copiar la lista al portapapeles")
		return

	def trabajo() -> None:
		try:
			nombres = explorador.listarCarpeta(carpeta)
		except OSError:
			mensaje("No se pudo copiar la lista al portapapeles")
			return
		if not nombres:
			mensaje("La carpeta no tiene elementos visibles")
			return
		if copiar("\r\n".join(nombres)):
			mensaje("Copiada la lista al portapapeles")
		else:
			mensaje("No se pudo copiar la lista al portapapeles")

	_hilo(trabajo)


def abrirCmd(ctx: Contexto) -> None:
	r = _rutasDelExplorador(ctx)
	if r is None:
		return
	carpeta = explorador.carpetaDe(r[0] or r[1])
	if not carpeta:
		mensaje("No se pudo obtener la ruta del elemento con foco")
		return
	_abrirPrograma("el CMD", ejecutor.CMD, None, carpeta)


def abrirCmdAdmin(ctx: Contexto) -> None:
	r = _rutasDelExplorador(ctx)
	if r is None:
		return
	carpeta = explorador.carpetaDe(r[0] or r[1])
	if not carpeta:
		mensaje("No se pudo obtener la ruta para ejecutar el CMD")
		return
	# Como administrador no se respeta la carpeta de trabajo: se cambia con cd.
	_hilo(ejecutor.elevado, ejecutor.CMD, f'/k cd /d "{carpeta}"', False, ejecutor.SW_SHOWNORMAL)


def ocultar(ctx: Contexto) -> None:
	r = _rutasDelExplorador(ctx)
	if r is None:
		return
	ruta = r[0]
	if not ruta:
		mensaje("No se pudo obtener la ruta del elemento. Seleccione un archivo o carpeta")
		return
	nombre = os.path.basename(ruta.rstrip("\\/")) or ruta

	def trabajo() -> None:
		if explorador.estaOculto(ruta):
			mensaje(f'El elemento "{nombre}" ya está oculto')
			return
		try:
			explorador.cambiarOculto(ruta, True)
		except OSError as e:
			mensaje(f"Error al ocultar el elemento: {e}")
			return
		pitido(900, 50)
		mensaje(f'Elemento "{nombre}" oculto correctamente. Si aún lo ve, desactive la vista de elementos ocultos')

	_hilo(trabajo)


def mostrarOcultos(ctx: Contexto) -> None:
	r = _rutasDelExplorador(ctx)
	if r is None:
		return
	foco, carpetaAbierta = r
	if not (foco or carpetaAbierta):
		mensaje("No se pudo obtener la ruta del elemento con foco")
		return

	def trabajo() -> None:
		try:
			if foco and explorador.estaOculto(foco):
				# El elemento con el foco está oculto: se muestra él.
				explorador.cambiarOculto(foco, False)
				pitido()
				mensaje('Elemento "{}" mostrado'.format(os.path.basename(foco.rstrip("\\/")) or foco))
				return
			carpeta = explorador.carpetaDe(foco or carpetaAbierta)
			if not carpeta:
				mensaje("No se pudo obtener la ruta del elemento con foco")
				return
			ocultos = explorador.ocultosEn(carpeta)
			nombreCarpeta = os.path.basename(carpeta.rstrip("\\/")) or carpeta
			if not ocultos:
				mensaje(f"No hay archivos ni carpetas ocultos en: {nombreCarpeta}")
				return
			fallos = 0
			for ruta in ocultos:
				try:
					explorador.cambiarOculto(ruta, False)
				except ejecutor.Cancelado:
					raise
				except OSError:
					fallos += 1
		except ejecutor.Cancelado:
			raise
		except OSError as e:
			mensaje(f"Error al mostrar archivos ocultos: {e}")
			return
		pitido()
		hechos = len(ocultos) - fallos
		texto = f"Se mostraron {hechos} elementos ocultos en: {nombreCarpeta}"
		if fallos:
			texto += f". No se pudieron mostrar {fallos}"
		mensaje(texto)

	_hilo(trabajo)


def lanzadorConsolas(ctx: Contexto) -> None:
	r = _rutasDelExplorador(ctx)
	if r is None:
		return
	carpeta = explorador.carpetaDe(r[0] or r[1])
	if not carpeta:
		mensaje("No se encontró una selección válida.")
		return
	elegida = dialogos.elegirConsola(consolas.opciones(), carpeta)
	if elegida is None:
		return

	def trabajo() -> None:
		if not consolas.abrir(elegida, carpeta):
			mensaje(MSG_NO_ABRE.format(elegida.etiqueta.replace("Abrir ", "").replace(" aquí", "")))

	_hilo(trabajo)


# ====================================================================== información al portapapeles
def _copiarSalida(aviso: str, args: list[str], copiado: str, fallo: str, timeout: float = 180) -> None:
	mensaje(aviso)

	def trabajo() -> None:
		codigo, salida = ejecutor.oculto(args, timeout)
		salida = salida.strip()
		if codigo != 0 or not salida:
			mensaje(fallo)
		elif copiar(salida):
			mensaje(copiado)
		else:
			mensaje("No se pudo copiar la información al portapapeles")

	_hilo(trabajo)


def copiarInfoSistema(ctx: Contexto) -> None:
	_copiarSalida("Obteniendo la información del sistema...", [ejecutor.system32("systeminfo.exe")], "Información del sistema copiada al portapapeles", "No se pudo obtener la información del sistema")


PS_SONIDO = (
	"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
	"Get-CimInstance Win32_SoundDevice | Format-List Name, Manufacturer, ProductName, Status, StatusInfo, DeviceID | Out-String -Width 400\n"
)


def copiarInfoSonido(ctx: Contexto) -> None:
	_copiarSalida("Obteniendo la información de las tarjetas de sonido...", ejecutor.psArgumentos(PS_SONIDO), "Copiada la info del sonido al portapapeles", "No se pudo obtener la información de las tarjetas de sonido", 60)


# ====================================================================== catálogo
@dataclass(frozen=True)
class Accion:
	id: str
	etiqueta: str
	descripcion: str
	grupo: str
	funcion: Callable[[Contexto], None]


#: Submenús, en el orden del original más los dos de las órdenes del Explorador
#: y del portapapeles (que en el original solo tenían orden de teclado).
GRUPOS = (
	("apagado", "&Apagado del sistema"),
	("explorador", "&Explorador y Procesos"),
	("reparacion", "&Reparación y optimización"),
	("seguridad", "&Seguridad de Windows"),
	("multimedia", "&Voz y multimedia"),
	("utilidades", "&Utilidades del sistema"),
	("archivos", "Archivos y &carpetas (Explorador)"),
	("informacion", "&Información al portapapeles"),
)

ACCIONES: tuple[Accion, ...] = (
	# Apagado del sistema
	Accion("apagar", "Apagar", "Apagar el sistema", "apagado", apagar),
	Accion("anularApagado", "Anular el apagado o reinicio", "Anular apagado", "apagado", anularApagado),
	Accion("entrarBios", "Entrar a la BIOS-UEFI", "Reiniciar el sistema y entrar en la BIOS-UEFI", "apagado", entrarBios),
	Accion("hibernar", "Hibernar", "Hibernar el sistema", "apagado", hibernar),
	Accion("reiniciar", "Reiniciar", "Reinicio del sistema", "apagado", reiniciar),
	Accion("modoSeguro", "Reiniciar y entrar en Modo seguro con funciones de red", "Reiniciar el sistema y entrar en Modo seguro con funciones de red", "apagado", modoSeguro),
	Accion("modoNormal", "Reiniciar en Modo normal", "Deshabilitar el Modo seguro y reiniciar el sistema", "apagado", modoNormal),
	Accion("suspender", "Suspender", "Suspender el sistema", "apagado", suspender),
	# Explorador y procesos
	Accion("borrarPortapapeles", "Borrar el portapapeles", "Borrar el portapapeles y su historial", "explorador", borrarPortapapeles),
	Accion("cerrarTodas", "Cerrar todas las aplicaciones", "Cerrar todas las aplicaciones", "explorador", cerrarTodas),
	Accion("cerrarNoResponden", "Cerrar tareas que no responden", "Cerrar tareas que no responden", "explorador", cerrarNoResponden),
	Accion("menuContextoClasico", "Habilitar menú de contexto clásico", "Habilitar menú de contexto clásico de Windows", "explorador", menuContextoClasico),
	Accion("menuContexto11", "Habilitar menú de contexto tipo: Windows 11", "Habilitar menú de contexto tipo: Windows 11", "explorador", menuContexto11),
	Accion("matarProcesos", "Matar procesos...", "Terminar los procesos de cualquier aplicación activa", "explorador", matarProcesos),
	Accion("monitorRecursos", "Monitor de recursos de Windows", "Abrir monitor de recursos", "explorador", monitorRecursos),
	Accion("reiniciarExplorador", "Reiniciar Explorador", "Reiniciar Explorador", "explorador", reiniciarExplorador),
	# Reparación y optimización
	Accion("activarReservado", "Activar almacenamiento reservado", "Activar el espacio reservado", "reparacion", activarReservado),
	Accion("desactivarReservado", "Desactivar almacenamiento reservado", "Desactivar el espacio reservado", "reparacion", desactivarReservado),
	Accion("planAltoRendimiento", "Activar el plan alto rendimiento", "Activar el Plan alto rendimiento de Windows", "reparacion", planAltoRendimiento),
	Accion("planEquilibrado", "Activar el plan equilibrado", "Activar el Plan Equilibrado de Windows", "reparacion", planEquilibrado),
	Accion("analisisSfc", "Análisis del sistema con SFC", "Hacer análisis del sistema con SFC", "reparacion", analisisSfc),
	Accion("limpiarDns", "Limpiar caché DNS", "Limpiar caché DNS", "reparacion", limpiarDns),
	Accion("limpiarPantallasSeguras", "Limpiar configuración guardada en pantallas seguras", "Limpiar configuración guardada para ejecutarse en pantallas seguras", "reparacion", limpiarPantallasSeguras),
	Accion("limpiarDisco", "Limpiar disco", "Limpiar disco", "reparacion", limpiarDisco),
	Accion("optimizarUnidades", "Optimizar las unidades", "Abrir Optimizar las unidades", "reparacion", optimizarUnidades),
	Accion("restablecerPC", "Restablecer PC", "Abrir Restablecer este PC", "reparacion", restablecerPC),
	Accion("repararDism", "Reparar sistema con Dism", "Reparar sistema con Dism", "reparacion", repararDism),
	# Seguridad de Windows
	Accion("activarUac", "Activar el control de cuentas de usuario (uac)", "Activar el Control de cuentas de usuario (uac)", "seguridad", activarUac),
	Accion("analisisArranque", "Analizar arranque del sistema", "Análisis del sector de arranque", "seguridad", analisisArranque),
	Accion("analisisCompleto", "Análisis completo", "Análisis completo", "seguridad", analisisCompleto),
	Accion("analisisRapido", "Análisis rápido", "Análisis rápido", "seguridad", analisisRapido),
	Accion("escanearComprimidos", "Escanear archivos comprimidos", "Activar escaneo de archivos comprimidos", "seguridad", escanearComprimidos),
	Accion("noEscanearComprimidos", "No escanear archivos comprimidos", "Desactivar escaneo de archivos comprimidos", "seguridad", noEscanearComprimidos),
	Accion("desactivarUac", "Desactivar el control de cuentas de usuario (uac)", "Desactivar el Control de cuentas de usuario (uac)", "seguridad", desactivarUac),
	Accion("cuarentena", "Listado de archivos en cuarentena al portapapeles", "Copiar al portapapeles la lista de archivos en cuarentena", "seguridad", cuarentena),
	# Voz y multimedia
	Accion("activarWebcam", "Activar Webcam", "Activar la Webcam", "multimedia", activarWebcam),
	Accion("desactivarWebcam", "Desactivar Webcam", "Desactivar la Webcam", "multimedia", desactivarWebcam),
	Accion("opcionesSonido", "Opciones de sonido", "Abrir opciones de sonido", "multimedia", opcionesSonido),
	Accion("opcionesVoz", "Opciones de voz", "Abrir opciones de voz", "multimedia", opcionesVoz),
	# Utilidades del sistema
	Accion("asistenteCredenciales", "Asistente guardar contraseñas de usuarios", "Abrir Asistente guardar contraseñas de usuarios", "utilidades", asistenteCredenciales),
	Accion("bluetooth", "Asistente transferir archivos por Bluetooth", "Abrir Asistente transferir archivos por Bluetooth", "utilidades", bluetooth),
	Accion("carpetaRoaming", "Carpeta Roaming", "Abrir carpeta Roaming", "utilidades", carpetaRoaming),
	Accion("asistenteContrasena", "Asistente para guardar la contraseña del sistema", "Abrir el asistente para guardar la contraseña del sistema", "utilidades", asistenteContrasena),
	Accion("mapaCaracteres", "Mapa de caracteres", "Abrir mapa de caracteres", "utilidades", mapaCaracteres),
	# Archivos y carpetas (necesitan una ventana del Explorador)
	Accion("copiarRuta", "Copiar la ruta", "Copiar al portapapeles la ruta del archivo o carpeta con el foco en el Explorador", "archivos", copiarRuta),
	Accion("copiarListado", "Copiar la lista de carpetas y archivos", "Copiar al portapapeles la lista de carpetas y archivos de la ruta actual del Explorador", "archivos", copiarListado),
	Accion("abrirCmd", "Abrir CMD en la ruta actual", "Abrir consola CMD en la ruta actual del Explorador", "archivos", abrirCmd),
	Accion("abrirCmdAdmin", "Abrir CMD como administrador en la ruta actual", "Abrir consola CMD como administrador en la ruta actual del Explorador", "archivos", abrirCmdAdmin),
	Accion("lanzadorConsolas", "Lanzador de consolas...", "Abrir el lanzador de consolas de Windows en la ruta actual del Explorador", "archivos", lanzadorConsolas),
	Accion("ocultar", "Ocultar el archivo o carpeta con el foco", "Ocultar el archivo o carpeta con el foco en el Explorador", "archivos", ocultar),
	Accion("mostrarOcultos", "Mostrar archivos o carpetas ocultos", "Mostrar el archivo o carpeta oculto con el foco en el Explorador, o los ocultos de su carpeta", "archivos", mostrarOcultos),
	# Información al portapapeles
	Accion("copiarInfoSistema", "Copiar información de todo el sistema", "Copiar información de todo el sistema al portapapeles", "informacion", copiarInfoSistema),
	Accion("copiarInfoSonido", "Copiar información de las tarjetas de sonido", "Copiar al portapapeles la información sobre las tarjetas de sonido", "informacion", copiarInfoSonido),
)

POR_ID = {a.id: a for a in ACCIONES}
