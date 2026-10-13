"""Agente de IA que realiza tareas en la pantalla con supervisión humana.

El usuario describe una tarea («abre el menú Archivo y guarda como PDF»). En
cada paso se envía al modelo una captura de la ventana activa y el
historial de acciones; el modelo responde con UNA acción en JSON. Antes de
cualquier acción que cambie algo (clic, escribir, teclas, rueda) Tiresias la
explica y pide confirmación: Sí, No (se le dice al modelo que no) o Detener.
La orden de parada de emergencia detiene el agente en cualquier momento.

Cada paso es una petición independiente (con un resumen de lo hecho), así
no se reenvían capturas antiguas.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field

from .. import imaging, queue_handler, speech
from ..config import conf
from ..i18n import _
from ..log import getLogger
from .providers import AIError, Message, configMessage, getProvider

log = getLogger("ai.agent")

AGENT_SYSTEM = (
	"Controlas el ordenador de una persona ciega a través de su lector de pantalla para completar la tarea que te pide. "
	"En cada paso recibes una captura de la ventana activa (con su tamaño en píxeles) y lo que ya se ha hecho. "
	"Responde SOLO con un objeto JSON, sin texto alrededor, con una de estas acciones:\n"
	'{"action": "click", "x": 10, "y": 20, "button": "left|right", "double": false, "explanation": "..."}\n'
	'{"action": "type", "text": "texto a escribir", "explanation": "..."}\n'
	'{"action": "key", "keys": "control+s", "explanation": "..."}\n'
	'{"action": "scroll", "x": 10, "y": 20, "amount": -3, "explanation": "..."}\n'
	'{"action": "wait", "explanation": "..."}\n'
	'{"action": "ask", "question": "pregunta para la persona"}\n'
	'{"action": "done", "message": "resumen de lo conseguido"}\n'
	"Las coordenadas son píxeles de la captura. La explicación va en español y dice qué vas a hacer y por qué. "
	"Nunca escribas contraseñas, datos de pago ni aceptes compras: si hacen falta, usa ask o done. "
	"Si la tarea es imposible o peligrosa, usa done y explícalo."
)

#: Acciones que cambian algo y necesitan confirmación.
CHANGING_ACTIONS = {"click", "type", "key", "scroll"}
#: Espera (ms) entre la confirmación y la acción, para que el diálogo se cierre.
ACTION_DELAY_MS = 300
_KEY_RE = re.compile(r"^[a-zA-Z0-9+]+$")


@dataclass
class Action:
	kind: str
	data: dict = field(default_factory=dict)

	@property
	def explanation(self) -> str:
		return str(self.data.get("explanation") or self.data.get("message") or self.data.get("question") or "")


def parseAction(text: str) -> Action:
	"""Extrae la acción JSON de la respuesta del modelo."""
	start = text.find("{")
	end = text.rfind("}")
	if start < 0 or end <= start:
		raise ValueError("La respuesta no contiene JSON")
	data = json.loads(text[start : end + 1])
	if not isinstance(data, dict):
		raise ValueError("JSON no válido")
	kind = str(data.get("action", "")).lower()
	if kind not in CHANGING_ACTIONS | {"wait", "ask", "done"}:
		raise ValueError(f"Acción desconocida: {kind}")
	if kind in ("click", "scroll"):
		data["x"] = int(data["x"])
		data["y"] = int(data["y"])
	if kind == "type" and not isinstance(data.get("text"), str):
		raise ValueError("Falta el texto")
	if kind == "key" and not _KEY_RE.match(str(data.get("keys", ""))):
		raise ValueError("Teclas no válidas")
	return Action(kind, data)


def describeAction(action: Action) -> str:
	d = action.data
	if action.kind == "click":
		what = _("doble clic") if d.get("double") else (_("clic derecho") if d.get("button") == "right" else _("clic"))
		base = _("{what} en {x}, {y}").format(what=what, x=d["x"], y=d["y"])
	elif action.kind == "type":
		base = _("escribir «{text}»").format(text=d["text"])
	elif action.kind == "key":
		base = _("pulsar {keys}").format(keys=d["keys"])
	elif action.kind == "scroll":
		base = _("mover la rueda {n} pasos").format(n=d.get("amount", 0))
	else:
		base = action.kind
	expl = action.explanation
	return f"{base}. {expl}" if expl else base


class ScreenAgent:
	def __init__(self) -> None:
		self.running = False
		self.task = ""
		self.steps: list[str] = []
		self.stepCount = 0
		self._stop = threading.Event()
		self._geom: tuple[tuple[int, int, int, int], int, int] | None = None
		#: Ventana (raíz) sobre la que trabaja el agente; se fija al iniciar.
		self.targetHwnd = 0
		#: Ejecutor de acciones (se sustituye en las pruebas).
		self.executor = executeAction
		#: Generación de la tarea: sube al iniciar y al detener. Las respuestas,
		#: confirmaciones y pasos programados de una tarea anterior se descartan.
		self._gen = 0

	# --------------------------------------------------------- ventana de destino
	@staticmethod
	def _isOwnWindow(hwnd: int) -> bool:
		"""``True`` si la ventana es de Tiresias (sus diálogos no son el destino)."""
		from .. import winapi

		try:
			return bool(hwnd) and winapi.getWindowProcessId(hwnd) == os.getpid()
		except Exception:
			return False

	@staticmethod
	def _rootOf(hwnd: int) -> int:
		from .. import winapi

		if not hwnd:
			return 0
		try:
			return winapi.getAncestor(hwnd, winapi.GA_ROOT) or hwnd
		except Exception:
			return hwnd

	@staticmethod
	def _isWindow(hwnd: int) -> bool:
		from .. import winapi

		try:
			return bool(hwnd) and bool(winapi.user32.IsWindow(hwnd))
		except Exception:
			return False

	def _currentTarget(self) -> int:
		"""Ventana sobre la que trabaja el agente.

		Es la que estaba en primer plano al iniciarlo, nunca un diálogo de
		Tiresias. Si esa aplicación abre otra ventana (un cuadro «Guardar
		como»), el destino pasa a ser esa ventana nueva del mismo proceso.
		"""
		from .. import winapi

		fg = self._rootOf(winapi.getForegroundWindow())
		target = self.targetHwnd
		if fg and fg != target and not self._isOwnWindow(fg):
			try:
				sameProcess = bool(target) and winapi.getWindowProcessId(fg) == winapi.getWindowProcessId(target)
			except Exception:
				sameProcess = False
			if sameProcess or not self._isWindow(target):
				target = fg
		if not self._isWindow(target):
			return 0
		self.targetHwnd = target
		return target

	def _focusTarget(self) -> None:
		"""Devuelve el primer plano a la ventana de destino antes de actuar."""
		from .. import winapi

		hwnd = self.targetHwnd
		if not self._isWindow(hwnd):
			return
		try:
			winapi.setForegroundWindow(hwnd)
		except Exception:
			log.debug("No se pudo devolver el primer plano a la ventana del agente", exc_info=True)

	# --------------------------------------------------------- control
	def start(self, task: str, targetHwnd: int = 0) -> None:
		if self.running:
			speech.speakMessage(_("El agente ya está trabajando. Usa la orden de parada para detenerlo."))
			return
		provider = getProvider()
		problem = configMessage(provider)
		if problem:
			speech.speakMessage(problem)
			return
		# La ventana de destino se fija al iniciar: después el primer plano puede
		# ser el diálogo de confirmación de Tiresias.
		from .. import winapi

		target = self._rootOf(targetHwnd)
		if not target or self._isOwnWindow(target):
			fg = self._rootOf(winapi.getForegroundWindow())
			target = 0 if self._isOwnWindow(fg) else fg
		if not target:
			speech.speakMessage(_("No hay ninguna ventana sobre la que trabajar"))
			return
		self.targetHwnd = target
		self.task = task.strip()
		self.steps = []
		self.stepCount = 0
		self._stop.clear()
		self._gen += 1
		self._geom = None
		self.running = True
		speech.speakMessage(_("Agente iniciado. Te pediré confirmación antes de cada acción."))
		self._nextStep()

	def stop(self, reason: str = "") -> None:
		if not self.running:
			speech.speakMessage(_("El agente no está trabajando"))
			return
		self._stop.set()
		self._gen += 1
		self.running = False
		from ..gui import ai_dialogs

		ai_dialogs.closeAgentConfirm()
		speech.cancelSpeech()
		speech.speakMessage(reason or _("Agente detenido"))

	def _current(self, gen: int | None) -> bool:
		"""¿Sigue en marcha la tarea de la generación ``gen``? (``None``: la actual)."""
		if gen is not None and gen != self._gen:
			return False
		return self.running and not self._stop.is_set()

	def _finish(self, message: str, gen: int | None = None) -> None:
		if gen is not None and gen != self._gen:
			# Respuesta tardía de una tarea ya detenida: no toca la actual.
			return
		self.running = False
		speech.speakMessage(message)

	# --------------------------------------------------------- pasos
	def _prompt(self, imgW: int, imgH: int, title: str) -> str:
		done = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(self.steps)) or "(nada todavía)"
		return f"Tarea: {self.task}\nVentana activa: {title}\nCaptura de {imgW}x{imgH} píxeles.\nLo hecho hasta ahora:\n{done}\nPaso {self.stepCount + 1}: responde con la siguiente acción en JSON."

	def _continue(self, gen: int | None) -> None:
		"""Paso siguiente programado (con ``callLater``) si la tarea sigue siendo la misma."""
		if self._current(gen):
			self._nextStep()

	def _nextStep(self, gen: int | None = None) -> None:
		if not self._current(gen):
			return
		gen = self._gen
		if self.stepCount >= max(1, int(conf["ai"]["agentMaxSteps"])):
			self._finish(_("El agente ha llegado al máximo de pasos sin terminar la tarea"))
			return
		from .. import winapi

		# Siempre se captura la ventana de destino, aunque el primer plano sea
		# un diálogo de Tiresias.
		hwnd = self._currentTarget()
		if not hwnd:
			self._finish(_("La ventana sobre la que trabajaba el agente se ha cerrado. Agente detenido."))
			return
		rect = winapi.getWindowRect(hwnd)
		title = winapi.getWindowText(hwnd)
		provider = getProvider()

		def worker() -> None:
			try:
				img = imaging.captureRect(rect, hwnd)
				small = imaging.scaleDown(img, imaging.AI_MAX_SIDE)
				geom = (rect, small.width, small.height)
				reply = provider.chat([Message("user", self._prompt(small.width, small.height, title), [imaging.encodePng(small)])], AGENT_SYSTEM, maxTokens=8000)
				action = parseAction(reply.text)
			except AIError as e:
				queue_handler.queueFunction(self._finish, str(e), gen)
				return
			except (ValueError, KeyError, TypeError) as e:
				log.warning("Respuesta del agente no válida: %s", e)
				queue_handler.queueFunction(self._finish, _("El modelo no devolvió una acción válida. Agente detenido."), gen)
				return
			except Exception as e:
				log.exception("Error del agente")
				queue_handler.queueFunction(self._finish, _("Error inesperado del agente ({kind}). El detalle está en el registro.").format(kind=type(e).__name__), gen)
				return
			if gen == self._gen and not self._stop.is_set():
				queue_handler.queueFunction(self._handle, action, gen, geom)

		threading.Thread(target=worker, name="IA-agente", daemon=True).start()

	def _handle(self, action: Action, gen: int | None = None, geom=None) -> None:
		if not self._current(gen):
			return
		gen = self._gen
		if geom is not None:
			self._geom = geom
		self.stepCount += 1
		if action.kind == "done":
			self._finish(_("Agente terminado: {msg}").format(msg=action.explanation or _("tarea completada")))
			return
		if action.kind == "wait":
			self.steps.append("esperar")
			queue_handler.callLater(1500, self._continue, gen)
			return
		if action.kind == "ask":
			self._ask(action.explanation, gen)
			return
		if action.kind == "type" and focusIsProtected():
			self._refuseProtected(gen)
			return
		desc = describeAction(action)
		from ..gui import ai_dialogs

		speech.speakMessage(desc)
		ai_dialogs.showAgentConfirm(desc, lambda choice: queue_handler.queueFunction(self._onChoice, action, desc, choice, gen))

	def _refuseProtected(self, gen: int | None) -> None:
		"""El modelo quiere escribir en un campo de contraseña: Tiresias no lo hace."""
		speech.speakMessage(_("El agente quería escribir en un campo de contraseña. Tiresias no lo permite: escríbela tú si hace falta."))
		self.steps.append("propuse escribir en un campo de contraseña y Tiresias lo impidió: nunca escribas contraseñas; usa ask o done")
		self._nextStep()

	def _ask(self, question: str, gen: int | None = None) -> None:
		from .. import gui

		gen = self._gen if gen is None else gen
		speech.speakMessage(question)

		def onText(answer: str) -> None:
			def go() -> None:
				if not self._current(gen):
					return
				self.steps.append(f"pregunté «{question}» y la persona respondió «{answer}»")
				self._nextStep()

			queue_handler.queueFunction(go)

		def onCancel() -> None:
			# Sin respuesta el agente no puede seguir: se detiene en lugar de quedarse «trabajando».
			queue_handler.queueFunction(lambda: self.stop() if self.running and gen == self._gen else None)

		gui.askText(_("El agente pregunta"), question, "", onText, onCancel)

	def _onChoice(self, action: Action, desc: str, choice: str, gen: int | None = None) -> None:
		if not self._current(gen):
			return
		gen = self._gen
		if choice == "stop":
			self.stop()
			return
		if choice == "no":
			self.steps.append(f"propuse {desc}, pero la persona NO lo aceptó")
			self._nextStep()
			return
		# La respuesta llega mientras el diálogo de confirmación aún tiene el
		# foco: se espera a que se cierre y se devuelve el primer plano a la
		# ventana de destino antes de actuar.
		queue_handler.callLater(ACTION_DELAY_MS, self._perform, action, desc, gen)

	def _perform(self, action: Action, desc: str, gen: int | None = None) -> None:
		if not self._current(gen):
			return
		gen = self._gen
		self._focusTarget()
		if action.kind == "type" and focusIsProtected():
			self._refuseProtected(gen)
			return
		try:
			self.executor(action, self._geom)
		except Exception as e:
			log.exception("No se pudo ejecutar la acción")
			self._finish(_("No se pudo ejecutar la acción ({kind}). El detalle está en el registro.").format(kind=type(e).__name__))
			return
		self.steps.append(f"hecho: {desc}")
		queue_handler.callLater(900, self._continue, gen)


def focusIsProtected() -> bool:
	"""¿El foco está en un campo de contraseña? (el agente nunca escribe en él)."""
	from .. import api
	from ..objects.roles import Role, State

	try:
		obj = api.getFocusObject()
		if obj is None:
			return False
		if obj.role == Role.PASSWORDEDIT:
			return True
		return State.PROTECTED in (obj.states or ())
	except Exception:
		log.debug("No se pudo comprobar si el foco es una contraseña", exc_info=True)
		return False


def toScreen(geom, x: int, y: int) -> tuple[int, int]:
	"""Convierte coordenadas de la captura reducida a coordenadas de pantalla."""
	(rx, ry, rw, rh), iw, ih = geom
	return int(rx + x * rw / max(1, iw)), int(ry + y * rh / max(1, ih))


def executeAction(action: Action, geom) -> None:
	"""Ejecuta una acción aceptada por el usuario (hilo del núcleo)."""
	from .. import mouse, winapi

	d = action.data
	if action.kind == "click":
		x, y = toScreen(geom, d["x"], d["y"])
		mouse.click(x, y, "right" if d.get("button") == "right" else "left", bool(d.get("double")))
	elif action.kind == "scroll":
		x, y = toScreen(geom, d["x"], d["y"])
		mouse.moveTo(x, y)
		mouse.scroll(int(d.get("amount", -3)))
	elif action.kind == "type":
		winapi.typeText(d["text"])
	elif action.kind == "key":
		from ..input.gestures import sendKey

		sendKey(d["keys"])


agent = ScreenAgent()


def startDialog() -> None:
	from .. import gui

	if agent.running:
		speech.speakMessage(_("El agente ya está trabajando"))
		return
	from .. import winapi

	# Destino: la ventana en primer plano antes de abrir el cuadro de la tarea.
	target = winapi.getForegroundWindow()

	def onText(task: str) -> None:
		if task.strip():
			def go() -> None:
				from .assistant import withImagePrivacy

				withImagePrivacy(lambda: agent.start(task, target))

			queue_handler.queueFunction(go)

	gui.askText(_("Agente de IA"), _("¿Qué quieres que haga el agente? Te pedirá confirmación antes de cada acción:"), "", onText)
