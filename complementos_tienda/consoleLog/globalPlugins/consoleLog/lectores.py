"""Lectura del contenido de las consolas en segundo plano.

Tres lectores, según la consola:

- :class:`LectorClasico` (Console Host): lee **todo** el historial del búfer
  con la API de consola de Windows, por bloques, conectándose un momento a la
  consola del proceso (``AttachConsole``). Comparte el cerrojo del lector de
  consolas de Tiresias (``tiresias.console_reader``), así nunca hay dos
  conexiones a la vez en el mismo proceso. Si Tiresias tiene consola propia
  (ejecución de desarrollo) o la consola está elevada, se recurre a UI
  Automation y, en último caso, a las líneas visibles que lee Tiresias.
- :class:`LectorUIA` (Windows Terminal y emuladores modernos): patrón de texto
  de UI Automation del área de texto enfocada al abrir el visor o, si no, del
  mejor candidato dentro de la ventana original (nunca del foco actual: el
  foco está en el visor y se recapturaría a sí mismo).
- :class:`LectorPutty` (PuTTY y KiTTY): la orden «Copiar todo» que usa el
  módulo de PuTTY de Tiresias, que restaura el portapapeles.

:class:`GestorLectores` lanza una lectura por vez en un hilo (por visor) y
entrega el resultado en el hilo de la interfaz salvo que se cancele antes.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Any, Callable

from tiresias.log import getLogger

from . import avisos
from .deteccion import TIPO_CLASICA, TIPO_PUTTY, DestinoConsola

log = getLogger("consoleLog")


class LecturaCancelada(Exception):
	pass


class LectorNoDisponible(Exception):
	pass


class AccesoDenegado(Exception):
	pass


MENSAJE_ELEVADA = "No se puede leer una consola de administrador si Tiresias no se ejecuta como administrador. Use el mismo nivel de privilegios."


def limpiar_texto(texto: str) -> str:
	"""Quita espacios finales de cada línea y las líneas vacías del final."""
	if not texto:
		return ""
	lineas = [linea.rstrip() for linea in texto.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
	while lineas and not lineas[-1].strip():
		lineas.pop()
	return "\n".join(lineas)


# ====================================================================== consola clásica
class _COORD(ctypes.Structure):
	_fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]


class _SMALL_RECT(ctypes.Structure):
	_fields_ = [("Left", wintypes.SHORT), ("Top", wintypes.SHORT), ("Right", wintypes.SHORT), ("Bottom", wintypes.SHORT)]


class _CSBI(ctypes.Structure):
	_fields_ = [
		("dwSize", _COORD),
		("dwCursorPosition", _COORD),
		("wAttributes", wintypes.WORD),
		("srWindow", _SMALL_RECT),
		("dwMaximumWindowSize", _COORD),
	]


_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 1
_FILE_SHARE_WRITE = 2
_OPEN_EXISTING = 3
_INVALID_HANDLE = wintypes.HANDLE(-1).value
_ERROR_ACCESS_DENIED = 5
#: Celdas por bloque de lectura (evita fallos y picos de memoria en búferes grandes).
CELDAS_POR_BLOQUE = 32768


def _kernel32():
	k = ctypes.WinDLL("kernel32", use_last_error=True)
	k.AttachConsole.argtypes = [wintypes.DWORD]
	k.AttachConsole.restype = wintypes.BOOL
	k.FreeConsole.restype = wintypes.BOOL
	k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
	k.CreateFileW.restype = wintypes.HANDLE
	k.GetConsoleScreenBufferInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_CSBI)]
	k.GetConsoleScreenBufferInfo.restype = wintypes.BOOL
	k.ReadConsoleOutputCharacterW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, _COORD, ctypes.POINTER(wintypes.DWORD)]
	k.ReadConsoleOutputCharacterW.restype = wintypes.BOOL
	k.CloseHandle.argtypes = [wintypes.HANDLE]
	return k


_HandlerRoutine = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)


@_HandlerRoutine
def _manejadorCtrl(evento: int) -> bool:
	# Control+C y Control+Pausa de la consola ajena no son para Tiresias.
	return evento in (0, 1)


_manejadorInstalado = False


def _instalarManejadorCtrl(k) -> None:
	global _manejadorInstalado
	try:
		from tiresias import console_reader

		instalar = getattr(console_reader, "_installCtrlHandler", None)
		if callable(instalar):
			instalar()
			return
	except Exception:
		pass
	if not _manejadorInstalado:
		k.SetConsoleCtrlHandler.argtypes = [_HandlerRoutine, wintypes.BOOL]
		_manejadorInstalado = bool(k.SetConsoleCtrlHandler(_manejadorCtrl, True))


def leer_buffer_por_bloques(leerFilas: Callable[[int, int], list[str]], ancho: int, alto: int, senal: threading.Event | None = None) -> str:
	"""Lee ``alto`` filas de ``ancho`` celdas en bloques y une el texto.

	``leerFilas(fila_inicial, filas)`` devuelve las filas del bloque.
	"""
	if ancho <= 0 or alto <= 0:
		return ""
	filas_por_bloque = max(1, min(alto, CELDAS_POR_BLOQUE // ancho))
	lineas: list[str] = []
	for fila in range(0, alto, filas_por_bloque):
		if senal is not None and senal.is_set():
			raise LecturaCancelada()
		lineas.extend(linea.rstrip() for linea in leerFilas(fila, min(filas_por_bloque, alto - fila)))
	while lineas and not lineas[-1].strip():
		lineas.pop()
	return "\n".join(lineas)


class LectorClasico:
	"""Historial completo de Console Host con la API de consola."""

	def leer(self, destino: DestinoConsola, senal: threading.Event | None = None) -> str:
		from tiresias import console_reader

		if console_reader.hasOwnConsole() or getattr(console_reader, "_useHelper", False):
			# Este proceso no puede conectarse a otra consola.
			raise LectorNoDisponible("Tiresias tiene consola propia")
		pid = int(destino.pid or 0)
		if not pid:
			raise Exception("No se pudo identificar el proceso de la consola.")
		k = _kernel32()
		cerrojo = getattr(console_reader, "_lock", None) or threading.Lock()
		with cerrojo:
			if not k.AttachConsole(pid):
				error = ctypes.get_last_error()
				if error == _ERROR_ACCESS_DENIED:
					raise AccesoDenegado(MENSAJE_ELEVADA)
				raise Exception("No se pudo conectar con la consola del proceso (error {}).".format(error))
			try:
				_instalarManejadorCtrl(k)
				h = k.CreateFileW("CONOUT$", _GENERIC_READ | _GENERIC_WRITE, _FILE_SHARE_READ | _FILE_SHARE_WRITE, None, _OPEN_EXISTING, 0, None)
				if not h or h == _INVALID_HANDLE:
					raise Exception("No se pudo obtener el búfer de salida de la consola.")
				try:
					info = _CSBI()
					if not k.GetConsoleScreenBufferInfo(h, ctypes.byref(info)):
						raise Exception("No se pudo consultar el búfer de la consola (error {}).".format(ctypes.get_last_error()))
					ancho, alto = int(info.dwSize.X), int(info.dwSize.Y)

					def leerFilas(fila: int, filas: int) -> list[str]:
						celdas = ancho * filas
						buf = ctypes.create_unicode_buffer(celdas + 1)
						leidos = wintypes.DWORD()
						if not k.ReadConsoleOutputCharacterW(h, buf, celdas, _COORD(0, fila), ctypes.byref(leidos)):
							raise Exception("No se pudo leer la consola (error {}).".format(ctypes.get_last_error()))
						texto = buf[: leidos.value].replace("\x00", " ")
						return [texto[i:i + ancho] for i in range(0, len(texto), ancho)]

					return leer_buffer_por_bloques(leerFilas, ancho, alto, senal)
				finally:
					k.CloseHandle(h)
			finally:
				k.FreeConsole()


# ====================================================================== UI Automation
def puntuar_candidato(offscreen: bool, identidad: str, area: int, indice: int) -> tuple:
	"""Puntuación de un área de texto: visible, con pista de terminal, mayor y primera."""
	identidad = (identidad or "").lower()
	pista = any(p in identidad for p in ("terminal", "termcontrol", "console", "text area"))
	return (0 if offscreen else 1, 1 if pista else 0, max(0, int(area)), -indice)


class LectorUIA:
	"""Texto del patrón de texto de UI Automation de la terminal original."""

	def leer(self, destino: DestinoConsola, senal: threading.Event | None = None) -> str:
		from tiresias.a11y import uia_client as uc

		if uc.client is None:
			raise Exception("UI Automation no está disponible en Tiresias.")
		UIA = uc.UIA
		# 1) El área de texto que tenía el foco al abrir el visor.
		if destino.elemento is not None:
			try:
				texto = self._textoDe(destino.elemento, UIA, uc)
				if texto is not None:
					return limpiar_texto(texto)
			except Exception:
				log.debug("consoleLog: el elemento enfocado ya no responde; se buscará en la ventana", exc_info=True)
		if senal is not None and senal.is_set():
			raise LecturaCancelada()
		# 2) El mejor candidato dentro de la ventana original.
		hwnd = int(destino.hwnd or destino.hwndFoco or 0)
		if not hwnd or not ctypes.windll.user32.IsWindow(hwnd):
			raise Exception("La ventana de la terminal original ya no está disponible.")
		try:
			raiz = uc.client.ElementFromHandle(hwnd)
		except Exception as e:
			raise Exception("No se pudo conectar con la ventana de la terminal: {}".format(e)) from None
		if not raiz:
			raise Exception("No se pudo conectar con la ventana de la terminal.")
		candidatos = [raiz]
		try:
			condicion = uc.client.CreatePropertyCondition(uc.P_ISTEXTPATTERNAVAILABLE, True)
			encontrados = raiz.FindAll(uc.TreeScope_Descendants, condicion)
			if encontrados:
				candidatos.extend(encontrados.GetElement(i) for i in range(encontrados.Length))
		except Exception:
			log.debug("consoleLog: no se pudieron buscar áreas de texto", exc_info=True)
		mejor = None
		mejorPatron = None
		for indice, candidato in enumerate(candidatos):
			if senal is not None and senal.is_set():
				raise LecturaCancelada()
			try:
				patron = self._patron(candidato, UIA, uc)
				if patron is None:
					continue
				identidad = " ".join(str(getattr(candidato, n, "") or "") for n in ("CurrentClassName", "CurrentAutomationId", "CurrentName"))
				try:
					r = candidato.CurrentBoundingRectangle
					area = max(0, r.right - r.left) * max(0, r.bottom - r.top)
				except Exception:
					area = 0
				puntos = puntuar_candidato(bool(getattr(candidato, "CurrentIsOffscreen", False)), identidad, area, indice)
				if mejor is None or puntos > mejor:
					mejor = puntos
					mejorPatron = patron
			except Exception:
				continue
		if mejorPatron is None:
			raise Exception("No se pudo identificar el área de texto activa de la terminal.")
		return limpiar_texto(mejorPatron.DocumentRange.GetText(-1) or "")

	@staticmethod
	def _patron(elemento: Any, UIA: Any, uc: Any):
		try:
			bruto = elemento.GetCurrentPattern(uc.PAT_TEXT)
		except Exception:
			return None
		if not bruto:
			return None
		try:
			return bruto.QueryInterface(UIA.IUIAutomationTextPattern)
		except Exception:
			return None

	def _textoDe(self, elemento: Any, UIA: Any, uc: Any) -> str | None:
		patron = self._patron(elemento, UIA, uc)
		if patron is None:
			return None
		return patron.DocumentRange.GetText(-1) or ""


# ====================================================================== PuTTY
class LectorPutty:
	"""PuTTY y KiTTY con «Copiar todo» (el portapapeles se restaura)."""

	ESPERA = 5.0

	def leer(self, destino: DestinoConsola, senal: threading.Event | None = None) -> str:
		from tiresias import queue_handler
		from tiresias.appmodules import putty

		listo = threading.Event()
		resultado: dict = {}

		def alTerminar(texto) -> None:
			resultado["texto"] = texto
			listo.set()

		queue_handler.queueFunction(putty.readTerminal, int(destino.hwnd), alTerminar)
		esperado = 0.0
		while not listo.wait(0.1):
			esperado += 0.1
			if senal is not None and senal.is_set():
				raise LecturaCancelada()
			if esperado >= self.ESPERA:
				break
		texto = resultado.get("texto")
		if texto is None:
			raise Exception("PuTTY no copió el contenido de la terminal.")
		return limpiar_texto(texto)


# ====================================================================== gestor
def _inicializarCom() -> bool:
	try:
		import comtypes

		comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
		return True
	except Exception:
		return False


def _liberarCom() -> None:
	try:
		import comtypes

		comtypes.CoUninitialize()
	except Exception:
		pass


def leer_destino(destino: DestinoConsola, senal: threading.Event | None = None) -> str:
	"""Lee la consola con el lector adecuado y sus alternativas (en un hilo de trabajo)."""
	if destino.tipo == TIPO_PUTTY:
		return LectorPutty().leer(destino, senal)
	if destino.tipo == TIPO_CLASICA:
		errorClasico: Exception | None = None
		try:
			return LectorClasico().leer(destino, senal)
		except LecturaCancelada:
			raise
		except Exception as e:  # noqa: BLE001
			errorClasico = e
			log.debug("consoleLog: lector clásico no disponible (%s); se usará UI Automation", e)
		try:
			return LectorUIA().leer(destino, senal)
		except LecturaCancelada:
			raise
		except Exception:
			log.debug("consoleLog: UI Automation tampoco pudo leer la consola", exc_info=True)
		try:
			from tiresias import console_reader

			lineas = console_reader.readVisibleLines(int(destino.pid or 0))
			if lineas is not None:
				return limpiar_texto("\n".join(lineas))
		except Exception:
			log.debug("consoleLog: no se pudieron leer las líneas visibles", exc_info=True)
		if isinstance(errorClasico, AccesoDenegado):
			raise errorClasico
		raise Exception(str(errorClasico) if errorClasico and not isinstance(errorClasico, LectorNoDisponible) else "No se pudo leer la consola.")
	return LectorUIA().leer(destino, senal)


class GestorLectores:
	"""Una lectura por vez; cada visor tiene su propio gestor."""

	def __init__(self, entregar: Callable | None = None, leer: Callable | None = None) -> None:
		self._cerrojo = threading.Lock()
		self._activa = False
		self._senal: threading.Event | None = None
		self._permitir: threading.Event | None = None
		self._hilo: threading.Thread | None = None
		self._entregar = entregar or self._entregarEnInterfaz
		self._leer = leer or leer_destino

	@staticmethod
	def _entregarEnInterfaz(funcion: Callable, *args: Any) -> None:
		from tiresias.gui.helpers import runOnGui

		runOnGui(funcion, *args)

	@property
	def activa(self) -> bool:
		with self._cerrojo:
			return self._activa

	def leer_consola(
		self,
		destino: DestinoConsola,
		callback_exito: Callable[[str], None],
		callback_error: Callable[[str], None],
		emitir_beep: bool = True,
		procesar: Callable[[str], str] | None = None,
	) -> bool:
		"""Inicia una lectura asíncrona. ``False`` si ya hay una en curso."""
		with self._cerrojo:
			if self._activa:
				return False
			self._activa = True
			senal = threading.Event()
			permitir = threading.Event()
			permitir.set()
			self._senal = senal
			self._permitir = permitir
		hilo = threading.Thread(
			target=self._trabajo,
			args=(destino, callback_exito, callback_error, emitir_beep, procesar, senal, permitir),
			name="consoleLogLectura",
			daemon=True,
		)
		self._hilo = hilo
		hilo.start()
		return True

	def _trabajo(self, destino, callback_exito, callback_error, emitir_beep, procesar, senal, permitir) -> None:
		terminado = threading.Event()
		if emitir_beep:
			threading.Thread(target=self._pitidosProgreso, args=(terminado, senal), name="consoleLogProgreso", daemon=True).start()
		com = _inicializarCom()
		tipo, valor = "error", "No se pudo leer la consola."
		try:
			texto = self._leer(destino, senal)
			if procesar is not None and texto:
				texto = procesar(texto)
			tipo, valor = "exito", texto
		except LecturaCancelada:
			tipo, valor = "cancelada", ""
		except Exception as e:  # noqa: BLE001
			log.debug("consoleLog: error leyendo la consola", exc_info=True)
			tipo, valor = "error", str(e) or "No se pudo leer la consola."
		finally:
			terminado.set()
			if com:
				_liberarCom()
		with self._cerrojo:
			if self._senal is senal:
				self._activa = False
				self._senal = None
				self._permitir = None
				self._hilo = None
		if tipo == "cancelada" or not permitir.is_set():
			return
		destinoCallback = callback_exito if tipo == "exito" else callback_error

		def entregar() -> None:
			# Una ventana puede haberse cerrado mientras terminaba el hilo.
			if permitir.is_set():
				destinoCallback(valor)

		self._entregar(entregar)

	@staticmethod
	def _pitidosProgreso(terminado: threading.Event, senal: threading.Event) -> None:
		while not terminado.is_set() and not senal.is_set():
			avisos.pitido(1000, 100)
			terminado.wait(1.0)

	def cancelar_lectura(self) -> None:
		with self._cerrojo:
			if self._permitir is not None:
				self._permitir.clear()
			if self._senal is not None:
				self._senal.set()
