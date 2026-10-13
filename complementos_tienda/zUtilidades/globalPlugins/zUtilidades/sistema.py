"""Funciones de sistema de zUtilidades: ejecutar acciones, aplicaciones
instaladas, portapapeles, pegar en el foco, texto seleccionado, URL y título.

No usa wx. Lo que toca objetos accesibles debe llamarse en el hilo del núcleo.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import threading
from ctypes import wintypes
from typing import Callable

from . import datos

#: Errores de ShellExecute (devuelve un valor <= 32 si algo falla).
SE_ERR_ACCESSDENIED = 5  # También cuando el usuario cancela el control de cuentas.
SW_SHOWDEFAULT = 10
CREATE_NO_WINDOW = 0x08000000

ERRORES_SHELL = {
	0: "sin memoria o recursos",
	2: "archivo no encontrado",
	3: "ruta no encontrada",
	5: "acceso denegado",
	8: "memoria insuficiente",
	11: "formato de archivo no válido",
	26: "infracción de uso compartido",
	27: "asociación de archivo incompleta",
	28: "tiempo de espera de DDE agotado",
	29: "error de DDE",
	30: "DDE ocupado",
	31: "no hay ninguna aplicación asociada",
	32: "no se encontró una biblioteca (DLL)",
}

MSG_ERROR_EJECUTAR = "Compruebe que los datos introducidos son correctos.\n\nSe produjo el error: {}\n\nPuede buscar información del error en:\n\nhttps://tinyurl.com/yhel7t8c"


# ====================================================================== ejecutar
class ParametrosEjecucion:
	"""Lo necesario para llamar a ShellExecute con un elemento del lanzador."""

	def __init__(self, verbo: str, archivo: str, parametros: str | None, carpeta: str | None) -> None:
		self.verbo = verbo
		self.archivo = archivo
		self.parametros = parametros
		self.carpeta = carpeta

	def __eq__(self, other) -> bool:
		return isinstance(other, ParametrosEjecucion) and (self.verbo, self.archivo, self.parametros, self.carpeta) == (other.verbo, other.archivo, other.parametros, other.carpeta)

	def __repr__(self) -> str:
		return f"ParametrosEjecucion({self.verbo!r}, {self.archivo!r}, {self.parametros!r}, {self.carpeta!r})"


def parametrosEjecucion(elemento: list) -> ParametrosEjecucion:
	"""Traduce un elemento del lanzador a la llamada de ShellExecute (como el original)."""
	tipo = elemento[0]
	if tipo == datos.TIPO_APP:
		ruta = elemento[2]
		verbo = "runas" if elemento[5] else "open"
		params = elemento[4] if elemento[3] else None
		return ParametrosEjecucion(verbo, ruta, params or None, os.path.dirname(ruta) or None)
	if tipo == datos.TIPO_CMD:
		verbo = "runas" if elemento[4] else "open"
		orden = "/c" + elemento[2] + ("&pause" if elemento[3] else "")
		return ParametrosEjecucion(verbo, "cmd.exe", orden, None)
	if tipo == datos.TIPO_CARPETA:
		return ParametrosEjecucion("explore", elemento[2], None, None)
	if tipo == datos.TIPO_ACCESO:
		return ParametrosEjecucion("runas" if elemento[3] else "open", elemento[2], None, None)
	if tipo == datos.TIPO_INSTALADA:
		return ParametrosEjecucion("runas" if elemento[3] else "open", "explorer.exe", "shell:appsfolder\\" + elemento[2], None)
	raise ValueError(f"Tipo de acción desconocido: {tipo}")


def rutaNoEncontrada(elemento: list) -> bool:
	"""¿Falta el archivo o la carpeta de la acción? (aplicaciones, carpetas y accesos)."""
	tipo = elemento[0]
	if tipo in (datos.TIPO_APP, datos.TIPO_ACCESO):
		return not os.path.isfile(elemento[2])
	if tipo == datos.TIPO_CARPETA:
		return not os.path.isdir(elemento[2])
	return False


def mensajeRutaNoEncontrada(elemento: list, grafico: bool) -> str:
	"""Texto del aviso cuando falta la ruta (``grafico``: desde la ventana, con pregunta)."""
	tipo = elemento[0]
	final = "¿Desea editar la entrada de la aplicación para corregir el problema?" if grafico else "Ejecute el lanzador de aplicaciones en modo grafico para editar la acción."
	if tipo == datos.TIPO_APP:
		return "La ruta a la aplicación {}, no se encontró.\n\n{}".format(elemento[1], final)
	if tipo == datos.TIPO_CARPETA:
		return "La ruta a la carpeta no se encontró.\n\n{}\n\n{}".format(elemento[2], final)
	return "La ruta al acceso directo no se encontró.\n\n{}\n\n{}".format(elemento[2], final)


_shell32 = None
_ole32 = None


def _shellExecute(p: ParametrosEjecucion) -> int:
	global _shell32, _ole32
	if _shell32 is None:
		# Instancias propias: no se cambian los argtypes compartidos de ctypes.windll.
		_shell32 = ctypes.WinDLL("shell32")
		_shell32.ShellExecuteW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int]
		_shell32.ShellExecuteW.restype = ctypes.c_void_p
		_ole32 = ctypes.WinDLL("ole32")
	# ShellExecute necesita COM en el hilo (apartamento de un solo hilo).
	hr = _ole32.CoInitializeEx(None, 0x2 | 0x4)
	try:
		res = _shell32.ShellExecuteW(None, p.verbo, p.archivo, p.parametros, p.carpeta, SW_SHOWDEFAULT)
		return int(res or 0)
	finally:
		if hr in (0, 1):
			_ole32.CoUninitialize()


#: Se puede sustituir en las pruebas (no se ejecuta nada real).
shellExecute: Callable[[ParametrosEjecucion], int] = _shellExecute


def ejecutar(elemento: list, alError: Callable[[str], None] | None = None) -> threading.Thread:
	"""Ejecuta un elemento del lanzador en un hilo propio (el control de cuentas
	puede tardar). Si falla y se indica ``alError``, se llama con el mensaje
	(desde ese hilo). Si el usuario cancela la elevación no se avisa.
	"""
	p = parametrosEjecucion(elemento)

	def trabajo() -> None:
		try:
			res = shellExecute(p)
		except Exception as e:  # pragma: no cover - errores de ctypes
			res = 0
			if alError:
				alError(MSG_ERROR_EJECUTAR.format(e))
			return
		if res <= 32 and res != SE_ERR_ACCESSDENIED and alError is not None:
			alError(MSG_ERROR_EJECUTAR.format(f"{res} ({ERRORES_SHELL.get(res, 'desconocido')})"))

	t = threading.Thread(target=trabajo, name="zUtilidadesEjecutar", daemon=True)
	t.start()
	return t


# ====================================================================== aplicaciones instaladas
_PS = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"


def analizarStartApps(salida: str) -> list[tuple[str, str]]:
	"""Convierte la salida JSON de ``Get-StartApps`` en pares (nombre, id)."""
	salida = (salida or "").strip().lstrip("\ufeff")
	if not salida:
		return []
	datosJson = json.loads(salida)
	if isinstance(datosJson, dict):
		datosJson = [datosJson]
	res = []
	for d in datosJson or []:
		if not isinstance(d, dict):
			continue
		nombre = str(d.get("Name") or "").strip()
		appId = str(d.get("AppID") or "").strip()
		if nombre and appId:
			res.append((nombre, appId))
	return res


def obtenerAplicaciones() -> list[tuple[str, str]]:
	"""Aplicaciones del menú Inicio (incluidas las de la tienda) con PowerShell.

	Tarda un poco: llámese desde un hilo propio.
	"""
	si = subprocess.STARTUPINFO()
	si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
	ps = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
	if not os.path.isfile(ps):
		ps = "powershell.exe"
	proc = subprocess.run(
		[ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _PS],
		stdin=subprocess.DEVNULL,
		capture_output=True,
		startupinfo=si,
		creationflags=CREATE_NO_WINDOW,
		timeout=120,
	)
	return analizarStartApps(proc.stdout.decode("utf-8", "replace"))


# ====================================================================== mensajes
def mensaje(texto: str) -> None:
	"""Habla y muestra en braille un mensaje (desde cualquier hilo)."""
	from tiresias import queue_handler, speech

	queue_handler.queueFunction(speech.speakMessage, texto)


def pitido(hz: int, ms: int) -> None:
	from tiresias import queue_handler
	from tiresias.audio import tones

	queue_handler.queueFunction(tones.beep, hz, ms)


def sonidoAviso(error: bool = False) -> None:
	"""Sonido de Windows de información o de error (como ``winsound.MessageBeep``)."""
	try:
		ctypes.WinDLL("user32").MessageBeep(0x10 if error else 0x0)
	except Exception:
		pass


# ====================================================================== portapapeles
def copiarAlPortapapeles(texto: str) -> bool:
	"""Copia un texto (con el sonido de copia de Tiresias)."""
	from tiresias import api

	return api.copyToClip(texto)


def _ponerPortapapelesSilencioso(texto: str) -> bool:
	from tiresias import clipboard, winapi

	clipboard.ignoreNextChange()
	ok = winapi.setClipboardText(texto)
	if not ok:
		clipboard.cancelIgnore()
	return ok


def pegarEnFoco(texto: str, retraso: int = 100, anunciar: bool = True) -> None:
	"""Pega ``texto`` donde esté el foco y luego deja el portapapeles como estaba.

	Igual que el original: se copia, se pulsa Control+V (o, en la consola
	clásica, la orden Pegar de su menú) y a los 300 ms se restaura el
	portapapeles. Llamar en el hilo del núcleo.
	"""
	from tiresias import queue_handler, winapi

	try:
		copia = winapi.getClipboardText()
	except Exception:
		copia = None
	_ponerPortapapelesSilencioso(texto)

	def pegar() -> None:
		hwnd = winapi.getForegroundWindow()
		try:
			clase = winapi.getClassName(hwnd)
		except Exception:
			clase = ""
		if clase == "ConsoleWindowClass":
			# Consola de Windows: Control+V no funciona en las antiguas.
			WM_COMMAND = 0x0111
			winapi.user32.SendMessageTimeoutW(hwnd, WM_COMMAND, 0xFFF1, 0, 0x0002, 2000, None)
		else:
			from tiresias.input.gestures import sendKey

			try:
				sendKey("control+v")
			except Exception:
				# Teclados que no tienen la V (cirílicos...).
				sendKey("shift+insert")
		if anunciar:
			mensaje("Nota pegada en el foco")
		if copia is not None:
			queue_handler.callLater(300, _ponerPortapapelesSilencioso, copia)

	queue_handler.callLater(retraso, pegar)


# ====================================================================== objetos
def textoSeleccionado() -> str | None:
	"""Texto seleccionado en el foco o en el modo exploración (``None`` si no hay)."""
	from tiresias import api, textinfo

	obj = api.getCaretObject()
	if obj is None:
		return None
	try:
		info = obj.makeTextInfo(textinfo.POSITION_SELECTION)
	except Exception:
		return None
	try:
		if info is None or info.isCollapsed:
			return None
		texto = info.text
	except Exception:
		return None
	return texto or None


def urlDocumento() -> str | None:
	"""Dirección de la página web donde está el foco, si la hay."""
	from tiresias import api
	from tiresias.objects.roles import Role

	focus = api.getFocusObject()
	if focus is None:
		return None
	ti = getattr(focus, "treeInterceptor", None)
	if ti is not None:
		try:
			url = ti.documentUrl() if hasattr(ti, "documentUrl") else ""
			if url and "://" in url:
				return url
		except Exception:
			pass
	obj = focus
	for _i in range(60):
		if obj is None:
			break
		try:
			if obj.role == Role.DOCUMENT:
				v = obj.value or ""
				if "://" in v:
					return v.strip()
		except Exception:
			pass
		try:
			obj = obj.parent
		except Exception:
			break
	return None


def tituloVentana() -> str | None:
	"""Título de la ventana en primer plano (``None`` si no se puede saber)."""
	from tiresias import api

	try:
		fg = api.getForegroundObject()
		nombre = fg.name if fg is not None else None
		return nombre or None
	except Exception:
		return None


def unirTextoYUrl(texto: str, url: str | None) -> str:
	"""Texto seleccionado más la URL detrás (como el original)."""
	return "\n\n".join([texto, url]) if url else texto
