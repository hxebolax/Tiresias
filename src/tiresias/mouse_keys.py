"""Ratón por teclado (al estilo de Golden Cursor).

Con el modo «ratón por teclado» activado las flechas mueven el puntero:

- Flechas: un paso (configurable). Mayúsculas+flechas: cinco pasos.
  Control+flechas: un píxel.
- Intro: clic izquierdo. Mayúsculas+Intro o tecla Aplicaciones: clic derecho.
  Control+Intro: doble clic.
- C: dice las coordenadas. Más y menos: cambian el paso.
- G: guarda la posición actual con un nombre (por aplicación).
- J: lista de posiciones guardadas para saltar a ellas (y hacer clic o borrarlas).
- Escape: sale del modo.

Las posiciones se guardan por aplicación en ``data/config/mousePositions.json``,
relativas a la ventana en primer plano (así sirven aunque la ventana se mueva).
El resto de teclas siguen llegando a la aplicación.
"""

from __future__ import annotations

import json
import os
import threading

from . import api, paths, speech, winapi
from .baseobject import script
from .config import conf, registerDefaults
from .i18n import _
from .log import getLogger
from .plugins import GlobalPlugin

log = getLogger("mouseKeys")

registerDefaults(
	"mouseKeys",
	{
		"step": 10,
		"announceCoordinates": True,
		#: Coordenadas «screen» (pantalla) o «window» (ventana en primer plano).
		"coordinates": "screen",
		"relativePositions": True,
		"audioCoordinates": False,
	},
)

STEPS = (1, 2, 5, 10, 20, 50, 100)
CAT = _("Ratón por teclado")

_lock = threading.Lock()


# ====================================================================== coordenadas
def screenSize() -> tuple[int, int, int, int]:
	x = winapi.user32.GetSystemMetrics(76)
	y = winapi.user32.GetSystemMetrics(77)
	w = winapi.user32.GetSystemMetrics(78) or winapi.user32.GetSystemMetrics(0)
	h = winapi.user32.GetSystemMetrics(79) or winapi.user32.GetSystemMetrics(1)
	return x, y, w, h


def clampToScreen(x: int, y: int, screen: tuple[int, int, int, int]) -> tuple[int, int, list[str]]:
	"""Limita el punto a la pantalla y dice qué bordes se han tocado."""
	sx, sy, sw, sh = screen
	edges = []
	if x <= sx:
		x = sx
		edges.append(_("borde izquierdo"))
	elif x >= sx + sw - 1:
		x = sx + sw - 1
		edges.append(_("borde derecho"))
	if y <= sy:
		y = sy
		edges.append(_("borde superior"))
	elif y >= sy + sh - 1:
		y = sy + sh - 1
		edges.append(_("borde inferior"))
	return x, y, edges


def foregroundOrigin() -> tuple[int, int]:
	hwnd = winapi.getForegroundWindow()
	if not hwnd:
		return 0, 0
	x, y, _w, _h = winapi.getWindowRect(hwnd)
	return x, y


def coordinatesText(x: int, y: int) -> str:
	if conf["mouseKeys"]["coordinates"] == "window":
		ox, oy = foregroundOrigin()
		return _("{x}, {y} en la ventana").format(x=x - ox, y=y - oy)
	return _("{x}, {y}").format(x=x, y=y)


def move(dx: int, dy: int) -> None:
	x, y = winapi.getCursorPos()
	nx, ny, edges = clampToScreen(x + dx, y + dy, screenSize())
	from . import mouse

	mouse.moveTo(nx, ny)
	from .magnifier import magnifier

	magnifier.onMouse(nx, ny)
	if conf["mouseKeys"]["audioCoordinates"]:
		try:
			mouse._audioCoordinates(nx, ny)
		except Exception:
			pass
	if edges:
		speech.speakMessage(" ".join(edges))
	elif conf["mouseKeys"]["announceCoordinates"]:
		speech.cancelSpeech()
		speech.speakMessage(coordinatesText(nx, ny))


def reportCoordinates() -> None:
	x, y = winapi.getCursorPos()
	speech.speakMessage(coordinatesText(x, y))


def changeStep(direction: int) -> None:
	cur = int(conf["mouseKeys"]["step"])
	steps = list(STEPS)
	if cur not in steps:
		steps.append(cur)
		steps.sort()
	i = steps.index(cur) + direction
	i = max(0, min(len(steps) - 1, i))
	conf["mouseKeys"]["step"] = steps[i]
	speech.speakMessage(_("Paso de {n} píxeles").format(n=steps[i]))


# ====================================================================== posiciones guardadas
def _file() -> str:
	return os.path.join(paths.configDir(), "mousePositions.json")


def loadPositions() -> dict[str, dict[str, list]]:
	try:
		with open(_file(), encoding="utf-8") as f:
			data = json.load(f)
		return data if isinstance(data, dict) else {}
	except FileNotFoundError:
		return {}
	except (OSError, ValueError):
		log.exception("Posiciones del ratón no válidas")
		return {}


def _savePositions(data: dict) -> None:
	os.makedirs(paths.configDir(), exist_ok=True)
	with open(_file(), "w", encoding="utf-8") as f:
		json.dump(data, f, ensure_ascii=False, indent="\t")


def currentApp() -> str:
	try:
		fg = api.getForegroundObject()
		app = fg.appModule if fg is not None else None
		if app is not None:
			return app.appName
	except Exception:
		pass
	return "global"


def savePosition(name: str, app: str | None = None, point: tuple[int, int] | None = None) -> None:
	app = app or currentApp()
	x, y = point or winapi.getCursorPos()
	relative = bool(conf["mouseKeys"]["relativePositions"])
	if relative:
		ox, oy = foregroundOrigin()
		x, y = x - ox, y - oy
	with _lock:
		data = loadPositions()
		data.setdefault(app, {})[name] = [int(x), int(y), relative]
		_savePositions(data)


def deletePosition(name: str, app: str | None = None) -> None:
	app = app or currentApp()
	with _lock:
		data = loadPositions()
		if name in data.get(app, {}):
			del data[app][name]
			if not data[app]:
				del data[app]
			_savePositions(data)


def positionsFor(app: str | None = None) -> dict[str, list]:
	return dict(loadPositions().get(app or currentApp(), {}))


def resolve(entry: list) -> tuple[int, int]:
	x, y = int(entry[0]), int(entry[1])
	relative = bool(entry[2]) if len(entry) > 2 else False
	if relative:
		ox, oy = foregroundOrigin()
		x, y = x + ox, y + oy
	return x, y


def jumpTo(name: str, click: str | None = None, app: str | None = None) -> bool:
	pos = positionsFor(app).get(name)
	if pos is None:
		speech.speakMessage(_("No existe la posición {name}").format(name=name))
		return False
	x, y = resolve(pos)
	from . import mouse

	if click:
		mouse.click(x, y, "right" if click == "right" else "left", click == "double")
	else:
		mouse.moveTo(x, y)
	speech.speakMessage(_("{name}: {coords}").format(name=name, coords=coordinatesText(x, y)))
	return True


def askSavePosition() -> None:
	from . import gui, queue_handler

	app = currentApp()
	point = winapi.getCursorPos()

	def onText(name: str) -> None:
		name = name.strip()
		if not name:
			return

		def save() -> None:
			savePosition(name, app, point)
			speech.speakMessage(_("Posición {name} guardada para {app}").format(name=name, app=app))

		queue_handler.queueFunction(save)

	gui.askText(_("Guardar posición del ratón"), _("Nombre de la posición ({x}, {y}) en {app}:").format(x=point[0], y=point[1], app=app), "", onText)


def showPositions() -> None:
	app = currentApp()
	positions = positionsFor(app)
	if not positions:
		speech.speakMessage(_("No hay posiciones guardadas para {app}").format(app=app))
		return
	from .gui import mouse_positions

	mouse_positions.show(app, sorted(positions))


# ====================================================================== modo
class MouseKeysPlugin(GlobalPlugin):
	"""Complemento incorporado: solo atiende teclas mientras el modo está activo."""

	scriptCategory = CAT
	active = False

	def getScript(self, gesture):
		if not MouseKeysPlugin.active:
			return None
		return super().getScript(gesture)

	def _step(self) -> int:
		return max(1, int(conf["mouseKeys"]["step"]))

	@script(gesture="kb:leftArrow", description=_("Ratón por teclado: mueve el puntero a la izquierda"), category=CAT)
	def script_left(self, gesture) -> None:
		move(-self._step(), 0)

	@script(gesture="kb:rightArrow", description=_("Ratón por teclado: mueve el puntero a la derecha"), category=CAT)
	def script_right(self, gesture) -> None:
		move(self._step(), 0)

	@script(gesture="kb:upArrow", description=_("Ratón por teclado: mueve el puntero hacia arriba"), category=CAT)
	def script_up(self, gesture) -> None:
		move(0, -self._step())

	@script(gesture="kb:downArrow", description=_("Ratón por teclado: mueve el puntero hacia abajo"), category=CAT)
	def script_down(self, gesture) -> None:
		move(0, self._step())

	@script(gesture="kb:shift+leftArrow", description=_("Ratón por teclado: mueve el puntero cinco pasos a la izquierda"), category=CAT)
	def script_bigLeft(self, gesture) -> None:
		move(-5 * self._step(), 0)

	@script(gesture="kb:shift+rightArrow", description=_("Ratón por teclado: mueve el puntero cinco pasos a la derecha"), category=CAT)
	def script_bigRight(self, gesture) -> None:
		move(5 * self._step(), 0)

	@script(gesture="kb:shift+upArrow", description=_("Ratón por teclado: mueve el puntero cinco pasos hacia arriba"), category=CAT)
	def script_bigUp(self, gesture) -> None:
		move(0, -5 * self._step())

	@script(gesture="kb:shift+downArrow", description=_("Ratón por teclado: mueve el puntero cinco pasos hacia abajo"), category=CAT)
	def script_bigDown(self, gesture) -> None:
		move(0, 5 * self._step())

	@script(gesture="kb:control+leftArrow", description=_("Ratón por teclado: mueve el puntero un píxel a la izquierda"), category=CAT)
	def script_pixelLeft(self, gesture) -> None:
		move(-1, 0)

	@script(gesture="kb:control+rightArrow", description=_("Ratón por teclado: mueve el puntero un píxel a la derecha"), category=CAT)
	def script_pixelRight(self, gesture) -> None:
		move(1, 0)

	@script(gesture="kb:control+upArrow", description=_("Ratón por teclado: mueve el puntero un píxel hacia arriba"), category=CAT)
	def script_pixelUp(self, gesture) -> None:
		move(0, -1)

	@script(gesture="kb:control+downArrow", description=_("Ratón por teclado: mueve el puntero un píxel hacia abajo"), category=CAT)
	def script_pixelDown(self, gesture) -> None:
		move(0, 1)

	@script(gesture="kb:enter", description=_("Ratón por teclado: clic izquierdo"), category=CAT)
	def script_leftClick(self, gesture) -> None:
		from . import mouse

		mouse.click()
		speech.speakMessage(_("clic"))

	@script(gestures=("kb:shift+enter", "kb:applications"), description=_("Ratón por teclado: clic derecho"), category=CAT)
	def script_rightClick(self, gesture) -> None:
		from . import mouse

		mouse.click(button="right")
		speech.speakMessage(_("clic derecho"))

	@script(gesture="kb:control+enter", description=_("Ratón por teclado: doble clic"), category=CAT)
	def script_doubleClick(self, gesture) -> None:
		from . import mouse

		mouse.click(double=True)
		speech.speakMessage(_("doble clic"))

	@script(gesture="kb:c", description=_("Ratón por teclado: dice las coordenadas del puntero"), category=CAT)
	def script_coordinates(self, gesture) -> None:
		reportCoordinates()

	@script(gestures=("kb:plus", "kb:numpadPlus"), description=_("Ratón por teclado: aumenta el paso"), category=CAT)
	def script_stepUp(self, gesture) -> None:
		changeStep(1)

	@script(gestures=("kb:-", "kb:numpadMinus"), description=_("Ratón por teclado: reduce el paso"), category=CAT)
	def script_stepDown(self, gesture) -> None:
		changeStep(-1)

	@script(gesture="kb:g", description=_("Ratón por teclado: guarda la posición del puntero"), category=CAT)
	def script_save(self, gesture) -> None:
		askSavePosition()

	@script(gesture="kb:j", description=_("Ratón por teclado: lista de posiciones guardadas"), category=CAT)
	def script_jump(self, gesture) -> None:
		showPositions()

	@script(gesture="kb:escape", description=_("Ratón por teclado: sale del modo"), category=CAT)
	def script_exit(self, gesture) -> None:
		setMode(False)


def setMode(on: bool) -> None:
	MouseKeysPlugin.active = on
	speech.speakMessage(_("Ratón por teclado activado. Flechas para mover, Intro para hacer clic, Escape para salir.") if on else _("Ratón por teclado desactivado"))


def toggleMode() -> None:
	setMode(not MouseKeysPlugin.active)


def initialize() -> None:
	"""Registra el complemento incorporado (antes de iniciar los complementos)."""
	from .plugins import handler as pluginHandler

	pluginHandler.registerBuiltin(MouseKeysPlugin)
