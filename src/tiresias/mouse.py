"""Ratón: clics simulados, seguimiento del puntero y coordenadas por sonido."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from . import api, winapi
from .config import conf
from .log import getLogger

log = getLogger("mouse")

_leftLocked = False
_rightLocked = False
_lastObj = None
_lastText = ""
_lastPos = (-1, -1)
_lastMoveTime = 0.0


def moveTo(x: int, y: int) -> None:
	winapi.user32.SetCursorPos(int(x), int(y))


def _beforeMouseInput() -> None:
	"""Si la superposición táctil tapa la pantalla, deja pasar el ratón."""
	try:
		from .touch import handler as touchHandler

		touchHandler.allowMouseThrough()
	except Exception:
		log.debug("No se pudo apartar la superposición táctil", exc_info=True)


def click(x: int | None = None, y: int | None = None, button: str = "left", double: bool = False) -> None:
	_beforeMouseInput()
	if x is not None and y is not None:
		moveTo(x, y)
		time.sleep(0.02)
	down, up = {
		"left": (winapi.MOUSEEVENTF_LEFTDOWN, winapi.MOUSEEVENTF_LEFTUP),
		"right": (winapi.MOUSEEVENTF_RIGHTDOWN, winapi.MOUSEEVENTF_RIGHTUP),
		"middle": (winapi.MOUSEEVENTF_MIDDLEDOWN, winapi.MOUSEEVENTF_MIDDLEUP),
	}[button]
	for _i in range(2 if double else 1):
		winapi.mouseEvent(down)
		winapi.mouseEvent(up)


def toggleLock(button: str) -> bool:
	"""Bloquea o desbloquea un botón. Devuelve el nuevo estado."""
	global _leftLocked, _rightLocked
	_beforeMouseInput()
	if button == "left":
		_leftLocked = not _leftLocked
		winapi.mouseEvent(winapi.MOUSEEVENTF_LEFTDOWN if _leftLocked else winapi.MOUSEEVENTF_LEFTUP)
		return _leftLocked
	_rightLocked = not _rightLocked
	winapi.mouseEvent(winapi.MOUSEEVENTF_RIGHTDOWN if _rightLocked else winapi.MOUSEEVENTF_RIGHTUP)
	return _rightLocked


#: Rueda horizontal (MOUSEEVENTF_HWHEEL).
MOUSEEVENTF_HWHEEL = 0x1000


def scroll(amount: int, horizontal: bool = False) -> None:
	"""Gira la rueda ``amount`` muescas en la posición del puntero.

	Vertical: positivo hacia arriba. Horizontal: positivo hacia la derecha.
	"""
	_beforeMouseInput()
	flag = MOUSEEVENTF_HWHEEL if horizontal else winapi.MOUSEEVENTF_WHEEL
	# mouseData es un DWORD: los valores negativos van en complemento a dos.
	winapi.mouseEvent(flag, data=(amount * 120) & 0xFFFFFFFF)


def coordinateTone(x: float, y: float, screen: tuple[int, int, int, int], minPitch: float, maxPitch: float) -> tuple[float, int]:
	"""Tono y volumen derecho (0-100) de un punto en ``screen`` (x, y, ancho, alto).

	Arriba suena agudo y abajo grave; el paneo indica la posición horizontal.
	Los puntos fuera de la pantalla se ajustan al borde.
	"""
	sx, sy, w, h = screen
	w = w or 1
	h = h or 1
	fx = max(0.0, min(1.0, (x - sx) / w))
	fy = max(0.0, min(1.0, (y - sy) / h))
	return maxPitch - (maxPitch - minPitch) * fy, int(round(100 * fx))


def _virtualScreen() -> tuple[int, int, int, int]:
	"""Rectángulo (x, y, ancho, alto) del escritorio virtual (todos los monitores)."""
	gsm = winapi.user32.GetSystemMetrics
	w, h = gsm(78), gsm(79)
	if w <= 0 or h <= 0:
		return 0, 0, gsm(0) or 1, gsm(1) or 1
	return gsm(76), gsm(77), w, h


def _audioCoordinates(x: int, y: int, duration: int = 40) -> None:
	from .audio import tones

	m = conf["mouse"]
	pitch, right = coordinateTone(x, y, _virtualScreen(), m["audioCoordinatesMinPitch"], m["audioCoordinatesMaxPitch"])
	tones.beep(pitch, duration, left=100 - right, right=right)


def audioCoordinatesForRect(location) -> bool:
	"""Tono de coordenadas en el centro de ``location`` (izq., arriba, ancho, alto).

	Devuelve ``False`` si el rectángulo no es válido (objeto sin posición).
	"""
	if not location:
		return False
	try:
		left, top, width, height = location
	except (TypeError, ValueError):
		return False
	if width <= 0 and height <= 0:
		return False
	_audioCoordinates(int(left + width / 2), int(top + height / 2))
	return True


def navigatorAudioCoordinates(obj) -> None:
	"""Tono de coordenadas del objeto navegador (#2559), si la opción está activada."""
	if obj is None or not conf["reviewCursor"]["audioCoordinatesOnNavigatorMove"]:
		return
	try:
		audioCoordinatesForRect(obj.location)
	except Exception:
		log.debug("Sin posición para las coordenadas del navegador", exc_info=True)


def reviewAudioCoordinates(info) -> None:
	"""Tono de coordenadas del cursor de revisión (#2559), si la opción está activada."""
	if info is None or not conf["reviewCursor"]["audioCoordinatesOnReviewMove"]:
		return
	try:
		from . import textinfo

		# La posición de revisión suele estar contraída: se mide su carácter.
		try:
			c = info.copy()
			c.expand(textinfo.UNIT_CHARACTER)
			rects = c.boundingRects
		except Exception:
			rects = info.boundingRects
		if rects and audioCoordinatesForRect(rects[0]):
			return
		pt = info.pointAtStart
		if pt is not None:
			_audioCoordinates(int(pt.x), int(pt.y))
			return
		# Sin posición del texto: la del objeto que lo contiene.
		obj = getattr(info, "obj", None)
		if obj is not None:
			audioCoordinatesForRect(obj.location)
	except Exception:
		log.debug("Sin posición para las coordenadas de la revisión", exc_info=True)


class _CURSORINFO(ctypes.Structure):
	_fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD), ("hCursor", wintypes.HANDLE), ("ptScreenPos", winapi.POINT)]


# Cursores estándar de Windows -> nombre en español.
_CURSOR_NAMES = {
	32512: "flecha",
	32513: "edición",
	32514: "ocupado",
	32515: "cruz",
	32516: "flecha arriba",
	32642: "cambiar tamaño noroeste sureste",
	32643: "cambiar tamaño noreste suroeste",
	32644: "cambiar tamaño horizontal",
	32645: "cambiar tamaño vertical",
	32646: "mover",
	32648: "no disponible",
	32649: "mano",
	32650: "flecha con reloj de arena",
	32651: "ayuda",
}
_cursorHandles: dict[int, str] = {}
_lastShape = ""


def _cursorShape() -> str:
	if not _cursorHandles:
		winapi.user32.LoadCursorW.restype = wintypes.HANDLE
		winapi.user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
		for cid, name in _CURSOR_NAMES.items():
			h = winapi.user32.LoadCursorW(None, ctypes.c_void_p(cid))
			if h:
				_cursorHandles[int(h)] = name
	info = _CURSORINFO()
	info.cbSize = ctypes.sizeof(_CURSORINFO)
	winapi.user32.GetCursorInfo.argtypes = [ctypes.POINTER(_CURSORINFO)]
	if not winapi.user32.GetCursorInfo(ctypes.byref(info)) or not info.hCursor:
		return ""
	return _cursorHandles.get(int(info.hCursor), "")


def _reportShape() -> None:
	global _lastShape
	if not conf["mouse"]["reportMouseShapeChanges"]:
		return
	shape = _cursorShape()
	if shape and shape != _lastShape:
		_lastShape = shape
		from . import speech

		speech.speakMessage(shape)


def _inSleepMode(obj) -> bool:
	"""``True`` si ``obj`` es de una aplicación en modo dormir (Tiresias calla en ella)."""
	try:
		app = obj.appModule if obj is not None else None
		return bool(app is not None and app.sleepMode)
	except Exception:
		return False


def handleMouseMove(x: int, y: int) -> None:
	"""Llamado (limitado en frecuencia) desde el gancho del ratón."""
	global _lastPos
	# Sobre una aplicación en modo dormir no se anuncia nada (como NVDA).
	quiet = _inSleepMode(api.getMouseObject())
	if not quiet:
		_reportShape()
	from .magnifier import magnifier

	magnifier.onMouse(x, y)
	if not conf["mouse"]["enableMouseTracking"]:
		return
	if (x, y) == _lastPos:
		return
	_lastPos = (x, y)
	if conf["mouse"]["audioCoordinatesOnMouseMove"] and not quiet:
		_audioCoordinates(x, y)
	delay = conf["mouse"]["reportDelay"]
	if delay > 0:
		# #11898: se espera a que el puntero se quede quieto ``delay`` ms antes
		# de leer. El temporizador va en el hilo del núcleo: el gancho no espera.
		_scheduleDelayedReport(delay)
		return
	_cancelDelayedReport()
	_reportAt(x, y)


_delayTimer: int | None = None


def _scheduleDelayedReport(delay: int) -> None:
	global _lastMoveTime, _delayTimer
	from . import queue_handler

	_lastMoveTime = time.monotonic()
	if _delayTimer is None:
		_delayTimer = queue_handler.callLater(delay, _onReportDelayElapsed)


def _cancelDelayedReport() -> None:
	global _delayTimer
	if _delayTimer is not None:
		from . import queue_handler

		queue_handler.cancelCallLater(_delayTimer)
		_delayTimer = None


def _remainingDelay(now: float, lastMove: float, delay: int) -> int:
	"""Milisegundos que faltan para que el puntero lleve ``delay`` ms quieto."""
	return max(0, int(round(delay - (now - lastMove) * 1000)))


def _onReportDelayElapsed() -> None:
	global _delayTimer
	from . import queue_handler

	_delayTimer = None
	m = conf["mouse"]
	if not m["enableMouseTracking"]:
		return
	remaining = _remainingDelay(time.monotonic(), _lastMoveTime, m["reportDelay"])
	# El puntero se movió durante la espera: se vuelve a esperar lo que falta.
	if remaining > 10:
		_delayTimer = queue_handler.callLater(remaining, _onReportDelayElapsed)
		return
	x, y = _lastPos
	try:
		_reportAt(x, y)
	except Exception:
		log.debug("Error leyendo lo que hay bajo el ratón", exc_info=True)


def _reportAt(x: int, y: int) -> None:
	"""Lee el objeto o el texto que hay en ``(x, y)``."""
	global _lastObj, _lastText
	from . import presentation, speech, textinfo
	from .objects.uia import getObjectFromPoint

	obj = getObjectFromPoint(x, y)
	if obj is None:
		return
	api.setMouseObject(obj)
	if _inSleepMode(obj):
		_lastObj, _lastText = obj, ""
		return
	if conf["reviewCursor"]["followMouse"]:
		api.setNavigatorObject(obj)
	text = ""
	unit = conf["mouse"]["mouseTextUnit"]
	if obj.hasText:
		try:
			info = obj.makeTextInfo(textinfo.Point(x, y))
			info.expand(unit)
			text = info.text.strip()
		except Exception:
			text = ""
	if text:
		if text != _lastText:
			_lastText = text
			speech.cancelSpeech()
			speech.speakText(text)
		_lastObj = obj
		return
	if obj == _lastObj:
		return
	_lastObj = obj
	_lastText = ""
	speech.cancelSpeech()
	if conf["mouse"]["reportObjectRoleOnMouseEnter"]:
		presentation.speakObject(obj, reason=presentation.Reason.MOUSE)
	else:
		name = obj.name or obj.value
		if name:
			speech.speakText(name)
