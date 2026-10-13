"""Funciones de inteligencia artificial de Tiresias.

- Describir el objeto navegador, la ventana, la pantalla, un archivo de
  imagen o la imagen del portapapeles, con chat de seguimiento.
- Resumir el documento o la página y hacer preguntas sobre ella.
- Sugerir una etiqueta para un control sin nombre y guardarla.
- Ayuda sobre Tiresias (con el manual como contexto).
- Describir un CAPTCHA para que el usuario decida (no se resuelve solo).

Las peticiones se hacen en hilos propios; los resultados vuelven al hilo del
núcleo y se muestran en el diálogo de chat o se leen en voz alta.
"""

from __future__ import annotations

import collections
import math
import os
import re
import threading
import time
import unicodedata
from typing import Any, Callable

from .. import api, imaging, queue_handler, speech, textinfo
from ..config import conf, registerDefaults
from ..i18n import _
from ..log import getLogger
from .providers import TRUNCATED_NOTE, AIError, Message, Provider, configMessage, getProvider

log = getLogger("ai")

registerDefaults(
	"ai",
	{
		"provider": "anthropic",
		"anthropicModel": "claude-opus-5-5",
		#: Identificador libre de un modelo de Claude (vacío: el de la lista).
		"anthropicCustomModel": "",
		"openaiModel": "gpt-4.1-mini",
		"geminiModel": "gemini-3.8-flash",
		"localUrl": "http://localhost:11434/v1",
		"localModel": "gemma3",
		#: Máximo de caracteres de documento para el servidor local (contexto pequeño).
		"localMaxContextChars": 12000,
		"responseLanguage": "español",
		"timeout": 90,
		#: El aviso de privacidad de imágenes ya se aceptó (desmarcado: se vuelve a preguntar).
		"imagePrivacyAccepted": False,
		#: Destinos (proveedor o servidor) para los que se aceptó el aviso.
		"imagePrivacyProviders": [],
		#: Abrir el diálogo de chat con cada resultado (si no, solo se lee).
		"resultInDialog": True,
		"maxContextChars": 200000,
		"translateTo": "es",
		"translateSpeech": False,
		"agentMaxSteps": 15,
		#: Etiquetado automático de los elementos sin nombre (foros 6.3). Desactivado
		#: por defecto: envía imágenes y gasta peticiones.
		"autoLabel": False,
		"autoLabelMaxPerHour": 20,
		#: Guardar las etiquetas automáticas (etiquetas personalizadas o textos del búfer).
		"autoLabelSave": True,
		#: Explorar la página: enviar también una captura de la ventana (foros 6.6).
		"exploreWithScreenshot": True,
		#: Máximo de imágenes por petición de texto alternativo (foros 3.10).
		"altTextMaxImages": 20,
		#: CAPTCHA (foros 10.6): detectarlo y anunciarlo, y voz durante el reto de audio.
		"captchaDetect": True,
		"captchaDuckMode": "lower",
		"captchaDuckVolume": 25,
		"captchaDuckSeconds": 15,
	},
)


def systemPrompt(extra: str = "") -> str:
	lang = conf["ai"]["responseLanguage"] or "español"
	base = (
		"Eres el asistente del lector de pantalla Tiresias y hablas con una persona ciega o con baja visión. "
		f"Responde siempre en {lang}, con frases claras, sin Markdown, sin tablas ni emojis, porque la respuesta se leerá con voz o en braille. "
		"Si no estás seguro de algo, dilo."
	)
	return base + (" " + extra if extra else "")


# ====================================================================== sesiones
class ChatSession:
	"""Conversación con el modelo (con imágenes opcionales en el primer mensaje)."""

	def __init__(self, title: str, system: str, provider: Provider | None = None) -> None:
		self.title = title
		self.system = system
		self.provider = provider or getProvider()
		self.messages: list[Message] = []
		self.busy = False
		#: Para el diálogo: (papel, texto) de lo que se ha mostrado.
		self.transcript: list[tuple[str, str]] = []

	def ask(self, text: str, images: list[bytes] | None = None, onAnswer: Callable[[str], None] | None = None, onError: Callable[[str], None] | None = None, shownText: str | None = None) -> None:
		"""Envía una pregunta en un hilo; las respuestas llegan al hilo del núcleo."""
		if self.busy:
			speech.speakMessage(_("Espera: todavía no ha llegado la respuesta anterior"))
			return
		self.busy = True
		msg = Message("user", text, list(images or []))
		self.messages.append(msg)
		self.transcript.append(("user", shownText if shownText is not None else text))

		def worker() -> None:
			try:
				reply = self.provider.chat(list(self.messages), self.system)
			except AIError as e:
				self._finishError(msg, str(e), onError)
				return
			except Exception as e:
				log.exception("Error de IA")
				self._finishError(msg, _("Error inesperado de la inteligencia artificial ({kind}). El detalle está en el registro.").format(kind=type(e).__name__), onError)
				return
			# Si la respuesta se cortó por la longitud, se dice y se ve.
			shown = withTruncatedNote(reply)
			self.messages.append(reply)
			self.transcript.append(("assistant", shown))
			self.busy = False
			queue_handler.queueFunction(onAnswer or _speakAnswer, shown)

		threading.Thread(target=worker, name="IA", daemon=True).start()

	def _finishError(self, msg: Message, error: str, onError) -> None:
		# La pregunta fallida se quita para poder repetirla.
		try:
			self.messages.remove(msg)
		except ValueError:
			pass
		if self.transcript and self.transcript[-1][0] == "user":
			self.transcript.pop()
		self.busy = False
		queue_handler.queueFunction(onError or speech.speakMessage, error)


def withTruncatedNote(reply: Message) -> str:
	"""Texto de la respuesta con el aviso de que está incompleta, si lo está."""
	if getattr(reply, "truncated", False):
		return f"{reply.text}\n\n{TRUNCATED_NOTE}"
	return reply.text


def _speakAnswer(text: str) -> None:
	speech.speakText(text)


def _present(session: ChatSession, first: str) -> None:
	"""Muestra la primera respuesta (diálogo de chat o voz)."""
	if conf["ai"]["resultInDialog"]:
		from ..gui import ai_dialogs

		ai_dialogs.showChat(session)
	speech.speakText(first)


def startSession(title: str, prompt: str, images: list[bytes] | None = None, system: str = "", shownText: str | None = None) -> ChatSession | None:
	"""Crea una sesión, envía la primera pregunta y presenta la respuesta."""
	provider = getProvider()
	problem = configMessage(provider)
	if problem:
		speech.speakMessage(problem)
		return None
	session = ChatSession(title, system or systemPrompt(), provider)
	speech.speakMessage(_("Consultando a {name}").format(name=provider.name))
	session.ask(prompt, images, onAnswer=lambda text: _present(session, text), shownText=shownText)
	return session


# ====================================================================== privacidad
def _privacyKey(provider: Any) -> str:
	fn = getattr(provider, "privacyKey", None)
	return fn() if callable(fn) else str(getattr(provider, "id", "") or getattr(provider, "name", ""))


def privacyAccepted(provider: Any) -> bool:
	"""¿Se puede enviar una imagen a ``provider`` sin volver a preguntar?

	El permiso es de cada destino (proveedor o servidor): aceptar el aviso
	para un servicio no vale para otro. ``imagePrivacyAccepted`` desmarcada
	anula todos. Las configuraciones anteriores (un único permiso, sin lista)
	lo conservan para el primer proveedor con el que se usen.
	"""
	if not getattr(provider, "isRemote", True):
		return True
	if not conf["ai"]["imagePrivacyAccepted"]:
		return False
	accepted = list(conf["ai"].get("imagePrivacyProviders", []) or [])
	key = _privacyKey(provider)
	if not accepted:
		conf["ai"]["imagePrivacyProviders"] = [key]
		return True
	return key in accepted


def markPrivacyAccepted(provider: Any) -> None:
	key = _privacyKey(provider)
	accepted = list(conf["ai"].get("imagePrivacyProviders", []) or []) if conf["ai"]["imagePrivacyAccepted"] else []
	if key not in accepted:
		accepted.append(key)
	conf["ai"]["imagePrivacyProviders"] = accepted
	conf["ai"]["imagePrivacyAccepted"] = True


def withImagePrivacy(callback: Callable[[], None]) -> None:
	"""Ejecuta ``callback`` (en el núcleo) si el usuario acepta enviar imágenes.

	La primera vez que se envía una imagen a cada servicio externo (o a un
	servidor «local» que en realidad está en otro equipo) se explica qué se
	envía y a quién; si se acepta, no se vuelve a preguntar para ese destino.
	"""
	provider = getProvider()
	if privacyAccepted(provider):
		callback()
		return
	from ..gui import ai_dialogs

	def accepted() -> None:
		def go() -> None:
			markPrivacyAccepted(provider)
			callback()

		queue_handler.queueFunction(go)

	nameFn = getattr(provider, "privacyName", None)
	name = nameFn() if callable(nameFn) else provider.name
	ai_dialogs.showPrivacyNotice(name, accepted, bool(getattr(provider, "insecure", False)))


# ====================================================================== imágenes
def _imageToPng(img: imaging.Image) -> bytes:
	return imaging.encodePng(imaging.scaleDown(img, imaging.AI_MAX_SIDE))


DESCRIBE_PROMPT = (
	"Describe esta imagen para una persona ciega. Empieza por lo más importante en una frase; "
	"después detalla el contenido, el texto visible tal cual aparece y la disposición de los elementos. "
	"Si es una interfaz, nombra los controles y su estado. Indica tu grado de seguridad cuando algo no se vea claro."
)


def _describeImage(title: str, capture: Callable[[], imaging.Image], prompt: str = DESCRIBE_PROMPT) -> None:
	def go() -> None:
		speech.speakMessage(_("Capturando"))

		def worker() -> None:
			try:
				png = _imageToPng(capture())
			except Exception as e:
				log.exception("No se pudo capturar la imagen")
				queue_handler.queueFunction(speech.speakMessage, _("No se pudo obtener la imagen: {err}").format(err=e))
				return
			queue_handler.queueFunction(startSession, title, prompt, [png], "", _("[Imagen] ") + title)

		threading.Thread(target=worker, name="IA-captura", daemon=True).start()

	withImagePrivacy(go)


def describeNavigatorObject() -> None:
	obj = api.getNavigatorObject()
	loc = obj.location if obj is not None else None
	if not loc or loc[2] <= 0 or loc[3] <= 0:
		speech.speakMessage(_("El objeto navegador no tiene ubicación en pantalla"))
		return
	from .. import winapi

	hwnd = 0
	try:
		hwnd = winapi.getAncestor(obj.windowHandle, winapi.GA_ROOT) if obj.windowHandle else 0
	except Exception:
		pass
	name = obj.name or _("objeto navegador")
	_describeImage(_("Descripción de {name}").format(name=name), lambda: imaging.captureRect(loc, hwnd))


def _foregroundRect() -> tuple[tuple[int, int, int, int], int] | None:
	from .. import winapi

	hwnd = winapi.getForegroundWindow()
	if not hwnd:
		return None
	x, y, w, h = winapi.getWindowRect(hwnd)
	vx, vy, vw, vh = imaging.virtualScreenRect()
	left, top = max(x, vx), max(y, vy)
	right, bottom = min(x + w, vx + vw), min(y + h, vy + vh)
	if right <= left or bottom <= top:
		return None
	return (left, top, right - left, bottom - top), hwnd


def describeForegroundWindow() -> None:
	r = _foregroundRect()
	if r is None:
		speech.speakMessage(_("No hay ventana en primer plano"))
		return
	rect, hwnd = r
	fg = api.getForegroundObject()
	name = fg.name if fg is not None and fg.name else _("la ventana")
	_describeImage(_("Descripción de {name}").format(name=name), lambda: imaging.captureRect(rect, hwnd))


def describeScreen() -> None:
	_describeImage(_("Descripción de la pantalla"), lambda: imaging.captureRect(imaging.virtualScreenRect()))


def describeFile(path: str) -> None:
	if not path or not os.path.isfile(path):
		speech.speakMessage(_("No se encuentra el archivo"))
		return
	_describeImage(_("Descripción de {name}").format(name=os.path.basename(path)), lambda: imaging.loadImageFile(path))


def describeFileDialog() -> None:
	from ..gui import helpers

	def ask() -> None:
		import wx

		wildcard = _("Imágenes") + " (*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.tif;*.tiff;*.webp)|*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.tif;*.tiff;*.webp|" + _("Todos los archivos") + " (*.*)|*.*"
		with wx.FileDialog(None, _("Elige una imagen para describir"), wildcard=wildcard, style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
			if dlg.ShowModal() == wx.ID_OK:
				queue_handler.queueFunction(describeFile, dlg.GetPath())

	helpers.runOnGui(ask)


def describeClipboardImage() -> None:
	files = [f for f in imaging.getClipboardFiles() if f.lower().endswith(imaging.IMAGE_EXTENSIONS)]
	if files:
		describeFile(files[0])
		return
	if not imaging.clipboardHasImage():
		speech.speakMessage(_("El portapapeles no contiene ninguna imagen"))
		return

	def capture() -> imaging.Image:
		# La lectura del portapapeles y la conversión del DIB (un bucle por filas)
		# se hacen en el hilo de trabajo de ``_describeImage``.
		try:
			img = imaging.getClipboardImage()
		except ValueError as e:
			raise ValueError(_("la imagen del portapapeles no se puede leer: {err}").format(err=e)) from e
		if img is None:
			raise ValueError(_("el portapapeles no contiene ninguna imagen"))
		return img

	_describeImage(_("Imagen del portapapeles"), capture)


CAPTCHA_PROMPT = (
	"La persona que te escribe es ciega y se ha encontrado esta prueba de verificación (CAPTCHA) en una página. "
	"No la resuelvas ni des la respuesta final: describe con detalle lo que se ve (instrucciones, imágenes de cada casilla con su posición, "
	"caracteres que aparecen y cualquier opción accesible como un reto de audio o un enlace alternativo) para que sea ella quien decida qué contestar."
)


def describeCaptcha() -> None:
	"""Describe el CAPTCHA del objeto navegador (o de la ventana) sin resolverlo."""
	obj = api.getNavigatorObject()
	loc = obj.location if obj is not None else None
	if loc and loc[2] > 0 and loc[3] > 0:
		_describeImage(_("Descripción del CAPTCHA"), lambda: imaging.captureRect(loc), CAPTCHA_PROMPT)
		return
	r = _foregroundRect()
	if r is None:
		speech.speakMessage(_("No hay nada que describir"))
		return
	rect, hwnd = r
	_describeImage(_("Descripción del CAPTCHA"), lambda: imaging.captureRect(rect, hwnd), CAPTCHA_PROMPT)


# ====================================================================== utilidades
def currentBrowseDocument() -> Any:
	"""Documento del modo exploración del foco (aunque esté en modo foco) o ``None``."""
	focus = api.getFocusObject()
	doc = getattr(focus, "treeInterceptor", None) if focus is not None else None
	if doc is not None and getattr(doc, "buffer", None) is not None:
		return doc
	caret = api.getCaretObject()
	return caret if getattr(caret, "buffer", None) is not None else None


def gestureLabel(cls: type, scriptName: str) -> str:
	"""Teclas actuales de una orden (con las del usuario) o cadena vacía."""
	try:
		from ..gui.gesture_tools import gesturesFor
		from ..input import gestures
		from ..input.keys import labelForGesture

		class _Info:
			pass

		info = _Info()
		info.cls = cls  # type: ignore[attr-defined]
		info.name = scriptName  # type: ignore[attr-defined]
		info.classGestures = dict(cls.iterClassGestures())  # type: ignore[attr-defined]
		gids = sorted(g for g in gesturesFor(gestures.userMap.userBindings(), info) if g.startswith("kb"))
		return ", ".join(labelForGesture(g) for g in gids)
	except Exception:
		log.debug("No se pudieron obtener las teclas de %s", scriptName, exc_info=True)
		return ""


def liveRect(element: Any) -> tuple[int, int, int, int] | None:
	"""Rectángulo actual de un elemento UIA (el de la caché puede estar desfasado)."""
	from ..a11y import uia_client as uc

	for getter in ("GetCurrentPropertyValueEx", "GetCachedPropertyValueEx"):
		try:
			r = getattr(element, getter)(uc.P_BOUNDINGRECT, True)
		except Exception:
			continue
		if r and not uc.isNotSupported(r) and len(r) >= 4 and r[2] > 0 and r[3] > 0:
			return int(r[0]), int(r[1]), int(r[2]), int(r[3])
	return None


def paddedRect(rect: tuple[int, int, int, int], pad: int = 40) -> tuple[int, int, int, int] | None:
	"""``rect`` ampliado ``pad`` píxeles (contexto) y recortado a la pantalla."""
	x, y, w, h = rect
	vx, vy, vw, vh = imaging.virtualScreenRect()
	left, top = max(vx, x - pad), max(vy, y - pad)
	right, bottom = min(vx + vw, x + w + pad), min(vy + vh, y + h + pad)
	if right <= left or bottom <= top:
		return None
	return left, top, right - left, bottom - top


def rootWindow(obj: Any) -> int:
	from .. import winapi

	try:
		return winapi.getAncestor(obj.windowHandle, winapi.GA_ROOT) if obj is not None and obj.windowHandle else 0
	except Exception:
		return 0


def checkProvider(quiet: bool = False) -> Provider | None:
	"""Proveedor configurado o ``None`` (avisa de lo que falta: clave, dirección...)."""
	provider = getProvider()
	problem = configMessage(provider)
	if problem:
		if not quiet:
			speech.speakMessage(problem)
		return None
	return provider


def contextLimit(provider: Any = None) -> int:
	"""Máximo de caracteres de documento que se envían al proveedor.

	Es la opción «Máximo de caracteres de un documento que se envían»; con el
	servidor local, además, la del contexto de ese servidor (Ollama recorta sin
	avisar lo que no cabe).
	"""
	provider = provider or getProvider()
	fn = getattr(provider, "contextChars", None)
	if callable(fn):
		try:
			return max(1000, int(fn()))
		except Exception:
			pass
	return max(1000, int(conf["ai"]["maxContextChars"]))


# ====================================================================== documentos
def currentDocumentText() -> tuple[str, str]:
	"""(título, texto) del documento actual: modo exploración o texto del foco."""
	caret = api.getCaretObject()
	buf = getattr(caret, "buffer", None)
	if buf is not None and getattr(buf, "text", ""):
		title = ""
		try:
			title = caret.rootObject.name or ""
		except Exception:
			title = getattr(getattr(caret, "result", None), "title", "") or ""
		return title or _("Documento"), buf.text
	focus = api.getFocusObject()
	if focus is None:
		return "", ""
	text = ""
	try:
		if focus.hasText:
			text = focus.makeTextInfo(textinfo.POSITION_ALL).text
	except Exception:
		text = ""
	fg = api.getForegroundObject()
	if not text.strip():
		try:
			text = "\n".join(_iterTexts(fg, deadline=time.monotonic() + WALK_SECONDS))
		except Exception:
			text = ""
	return (fg.name if fg is not None and fg.name else _("Documento")), text


#: Límites al recorrer los objetos de una ventana en el hilo del núcleo (cada
#: objeto es una llamada a otra aplicación): número de objetos y segundos.
WALK_MAX_OBJECTS = 3000
WALK_SECONDS = 2.0


def _iterTexts(obj: Any, depth: int = 0, limit: list[int] | None = None, deadline: float | None = None):
	"""Nombres y valores de los objetos de una ventana (para ventanas sin documento).

	Se detiene al llegar a ``WALK_MAX_OBJECTS`` objetos o al instante
	``deadline`` (``time.monotonic()``), para no bloquear el hilo del núcleo.
	"""
	if obj is None or depth > 30:
		return
	limit = limit if limit is not None else [0]
	if deadline is not None and time.monotonic() > deadline:
		return
	try:
		children = list(obj.children)
	except Exception:
		children = []
	for child in children:
		limit[0] += 1
		if limit[0] > WALK_MAX_OBJECTS:
			return
		if deadline is not None and time.monotonic() > deadline:
			return
		try:
			parts = [p for p in (child.name, child.value) if p]
		except Exception:
			parts = []
		if parts:
			yield " ".join(parts)
		yield from _iterTexts(child, depth + 1, limit, deadline)


def _limitedText(text: str) -> tuple[str, bool]:
	limit = contextLimit()
	if len(text) <= limit:
		return text, False
	return text[:limit], True


def _documentSession(title: str, instruction: str, question: str | None = None) -> None:
	docTitle, text = currentDocumentText()
	if not text.strip():
		speech.speakMessage(_("No hay texto en el documento actual"))
		return
	text, cut = _limitedText(text)
	if cut:
		speech.speakMessage(_("El documento es muy largo: se envían solo los primeros {n} caracteres. Puedes cambiar el límite en las opciones.").format(n=len(text)))
	system = systemPrompt("Te paso el texto de un documento o página web entre etiquetas <documento>. Basa tus respuestas en ese texto.")
	prompt = f"<documento titulo=\"{docTitle}\">\n{text}\n</documento>\n\n{instruction}"
	shown = f"{instruction}" if question is None else question
	startSession(title.format(name=docTitle), prompt, system=system, shownText=shown)


def summarizeDocument() -> None:
	_documentSession(_("Resumen de {name}"), "Resume este documento: primero la idea principal en una frase y después los puntos clave. Indica también qué secciones tiene.")


def askAboutDocument() -> None:
	from .. import gui

	def onText(question: str) -> None:
		if question.strip():
			queue_handler.queueFunction(_documentSession, _("Preguntas sobre {name}"), question.strip(), question.strip())

	gui.askText(_("Preguntar sobre la página"), _("Pregunta sobre el documento o la página:"), "", onText)


# ====================================================================== etiquetas
LABEL_PROMPT = (
	"Esta imagen es un control de una aplicación que no tiene nombre accesible. Datos: {info}. "
	"Propón una etiqueta corta (de una a cuatro palabras) que diga para qué sirve el control. "
	"Responde solo con la etiqueta, sin comillas ni punto final."
)


def suggestLabel() -> None:
	"""Pide a la IA una etiqueta para el objeto navegador y la guarda si el usuario la acepta."""
	obj = api.getNavigatorObject()
	if obj is None:
		speech.speakMessage(_("No hay objeto navegador"))
		return
	loc = obj.location
	if not loc or loc[2] <= 0 or loc[3] <= 0:
		speech.speakMessage(_("El objeto navegador no tiene ubicación en pantalla"))
		return
	from ..objects.roles import roleLabel

	info = []
	try:
		info.append("tipo " + roleLabel(obj.role))
		app = obj.appModule
		if app is not None:
			info.append("aplicación " + app.appName)
		parent = obj.parent
		if parent is not None and parent.name:
			info.append("dentro de «" + parent.name + "»")
		desc = getattr(obj, "description", "")
		if desc:
			info.append("descripción «" + desc + "»")
	except Exception:
		pass
	# Se captura un poco más grande para dar contexto.
	x, y, w, h = loc
	pad = 40
	vx, vy, vw, vh = imaging.virtualScreenRect()
	rect = (max(vx, x - pad), max(vy, y - pad), 0, 0)
	rect = (rect[0], rect[1], min(vx + vw, x + w + pad) - rect[0], min(vy + vh, y + h + pad) - rect[1])
	prompt = LABEL_PROMPT.format(info=", ".join(info) or "sin datos")

	def go() -> None:
		provider = getProvider()
		problem = configMessage(provider)
		if problem:
			speech.speakMessage(problem)
			return
		speech.speakMessage(_("Buscando una etiqueta"))

		def worker() -> None:
			try:
				png = _imageToPng(imaging.captureRect(rect))
				# Tarea corta: poco razonamiento y margen para los modelos que siempre
				# razonan (el razonamiento cuenta en el límite de salida).
				reply = provider.chat([Message("user", prompt, [png])], systemPrompt(), maxTokens=2000, effort="low")
			except AIError as e:
				queue_handler.queueFunction(speech.speakMessage, str(e))
				return
			except Exception as e:
				log.exception("Error sugiriendo etiqueta")
				queue_handler.queueFunction(speech.speakMessage, _("Error inesperado de la inteligencia artificial ({kind}). El detalle está en el registro.").format(kind=type(e).__name__))
				return
			label = cleanLabel(reply.text)
			queue_handler.queueFunction(_confirmLabel, obj, label)

		threading.Thread(target=worker, name="IA-etiqueta", daemon=True).start()

	withImagePrivacy(go)


def cleanLabel(text: str) -> str:
	t = text.strip().splitlines()[0] if text.strip() else ""
	t = t.strip().strip("\"'«»“”.").strip()
	return t[:60]


def _confirmLabel(obj: Any, label: str) -> None:
	if not label:
		speech.speakMessage(_("No se obtuvo ninguna etiqueta"))
		return
	speech.speakMessage(_("Etiqueta propuesta: {label}").format(label=label))
	from .. import gui, labels

	def onText(text: str) -> None:
		def save() -> None:
			if labels.setLabel(obj, text.strip() or None):
				speech.speakMessage(_("Etiqueta guardada") if text.strip() else _("Etiqueta eliminada"))
			else:
				speech.speakMessage(_("No se puede etiquetar este objeto"))

		queue_handler.queueFunction(save)

	gui.askText(_("Etiqueta sugerida"), _("Etiqueta para este control (puedes corregirla antes de guardarla):"), label, onText)


# ====================================================================== ayuda
class ManualSection:
	"""Apartado del manual (un ``h3``, o el principio de un capítulo ``h2``)."""

	__slots__ = ("title", "text", "order", "counts", "titleTerms", "length")

	def __init__(self, title: str, text: str, order: int) -> None:
		self.title = title
		self.text = text
		self.order = order
		terms = searchTerms(text)
		self.counts = collections.Counter(terms)
		self.titleTerms = set(searchTerms(title))
		self.length = max(1, len(terms))


_HEADING_RE = re.compile(r"<h([23])\b[^>]*>(.*?)</h\1>", re.S | re.I)
_NAV_RE = re.compile(r"<nav\b.*?</nav>", re.S | re.I)
_WORD_RE = re.compile(r"\w+", re.U)
#: Palabras vacías que no sirven para buscar.
_STOPWORDS = {
	"que", "qué", "como", "cómo", "para", "por", "con", "sin", "los", "las", "del", "una", "uno", "unos", "unas", "este", "esta",
	"esto", "ese", "esa", "eso", "hay", "puedo", "puede", "pueden", "quiero", "hacer", "hace", "cuando", "donde", "dónde", "cual",
	"cuál", "más", "mas", "pero", "tiresias", "sus", "son", "está", "estar", "tengo", "tiene", "the", "and", "how", "what",
	"sobre", "entre", "desde", "hasta", "también", "muy", "ser", "eres", "soy", "algo", "alguna", "alguno", "todo", "toda", "todos",
}

_manualCache: dict[str, Any] = {}
_manualLock = threading.Lock()


def _fold(word: str) -> str:
	"""Minúsculas y sin tildes."""
	return "".join(c for c in unicodedata.normalize("NFD", word.lower()) if unicodedata.category(c) != "Mn")


def searchTerms(text: str) -> list[str]:
	"""Palabras de búsqueda: sin tildes ni palabras vacías y recortadas a su raíz
	aproximada (los seis primeros caracteres: «configurar» y «configuración»
	coinciden)."""
	out = []
	for w in _WORD_RE.findall(text.lower()):
		if len(w) < 3 or w in _STOPWORDS:
			continue
		f = _fold(w)
		if f in _STOPWORDS:
			continue
		out.append(f[:6])
	return out


def parseManual(html: str, toText: Callable[[str], str]) -> dict[str, Any]:
	"""Texto completo, índice y apartados del manual en HTML."""
	text = toText(html)
	nav = _NAV_RE.search(html)
	index = toText(nav.group(0)).strip() if nav else ""
	body = html[nav.end() :] if nav else html
	heads = list(_HEADING_RE.finditer(body))
	sections: list[ManualSection] = []
	chapter = ""
	for i, m in enumerate(heads):
		end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
		title = " ".join(toText(m.group(2)).split())
		if m.group(1) == "2":
			chapter = title
			fullTitle = title
		else:
			fullTitle = f"{chapter} > {title}" if chapter else title
		chunk = toText(body[m.start() : end]).strip()
		if chunk:
			sections.append(ManualSection(fullTitle, chunk, len(sections)))
	return {"text": text, "index": index, "sections": sections}


def manualData() -> dict[str, Any]:
	"""Manual en texto y troceado (se guarda en caché hasta que cambie el archivo).

	La primera vez convierte el HTML (más de medio millón de caracteres): mejor
	llamarla desde un hilo de trabajo.
	"""
	from .. import paths
	from ..gui import dialogs

	path = paths.manualPath()
	try:
		key = (path, os.path.getmtime(path))
	except OSError:
		return {"text": "", "index": "", "sections": []}
	with _manualLock:
		if _manualCache.get("key") == key:
			return dict(_manualCache)
	try:
		with open(path, encoding="utf-8") as f:
			html = f.read()
	except OSError:
		return {"text": "", "index": "", "sections": []}
	data = parseManual(html, dialogs.htmlToText)
	data["key"] = key
	with _manualLock:
		_manualCache.clear()
		_manualCache.update(data)
	return data


def manualText() -> str:
	return manualData()["text"]


def selectManualContext(question: str, limit: int, data: dict[str, Any]) -> tuple[str, bool]:
	"""Texto del manual que se envía con la pregunta y si se ha recortado.

	Si el manual cabe en ``limit`` caracteres va entero. Si no, se envía el
	índice y los apartados que más se parecen a la pregunta (puntuación BM25,
	como un buscador sencillo, con más peso para las palabras del título), en
	el orden del manual, hasta llenar el límite.
	"""
	full = data.get("text", "")
	if len(full) <= limit:
		return full, False
	sections: list[ManualSection] = data.get("sections") or []
	index = data.get("index", "")
	if len(index) > limit // 4:
		index = index[: limit // 4]
	budget = limit - len(index) - 100
	terms = set(searchTerms(question))
	n = len(sections)
	scores = [0.0] * n
	if terms and n:
		avg = sum(sec.length for sec in sections) / n
		k1, b = 1.2, 0.75
		for t in terms:
			df = sum(1 for sec in sections if t in sec.counts or t in sec.titleTerms)
			if not df:
				continue
			idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
			for i, sec in enumerate(sections):
				tf = sec.counts.get(t, 0)
				if tf:
					scores[i] += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * sec.length / avg))
				if t in sec.titleTerms:
					scores[i] += 2 * idf
	ranked = sorted(range(n), key=lambda i: -scores[i])
	chosen: list[int] = []
	used = 0
	for i in ranked:
		if scores[i] <= 0:
			break
		size = len(sections[i].text) + 2
		if used + size > budget:
			continue
		chosen.append(i)
		used += size
	if not chosen:
		# Ninguna palabra coincide: el principio del manual, como antes.
		for i in range(n):
			size = len(sections[i].text) + 2
			if used + size > budget:
				break
			chosen.append(i)
			used += size
	chosen.sort()
	parts = []
	if index:
		parts.append("Índice del manual:\n" + index)
	parts.extend(sections[i].text for i in chosen)
	return "\n\n".join(parts), True


def askHelp(question: str | None = None) -> None:
	"""Responde dudas sobre Tiresias usando el manual como contexto."""
	if question is None:
		from .. import gui

		def onText(q: str) -> None:
			if q.strip():
				queue_handler.queueFunction(askHelp, q.strip())

		gui.askText(_("Ayuda de Tiresias"), _("¿Qué quieres saber de Tiresias?"), "", onText)
		return
	provider = checkProvider()
	if provider is None:
		return
	limit = contextLimit(provider)

	def worker() -> None:
		# Leer y trocear el manual es lento: fuera del hilo del núcleo.
		try:
			data = manualData()
			manual, cut = selectManualContext(question, limit, data) if data["text"] else ("", False)
		except Exception:
			log.exception("No se pudo preparar el manual")
			manual, cut = "", False
		queue_handler.queueFunction(_askHelpWithManual, question, manual, cut)

	threading.Thread(target=worker, name="IA-manual", daemon=True).start()


def _askHelpWithManual(question: str, manual: str, cut: bool) -> None:
	if not manual:
		speech.speakMessage(_("No se encuentra el manual de usuario"))
		return
	if cut:
		speech.speakMessage(_("El manual no cabe entero en el límite de contexto: se envían el índice y los apartados más relacionados con tu pregunta."))
	system = systemPrompt(
		"Respondes dudas sobre el lector de pantalla Tiresias. Usa solo el manual que va entre etiquetas <manual>; "
		"si la respuesta no está en el manual, dilo. Cuando cites una orden, da la combinación de teclas exacta."
		+ (" Del manual solo tienes el índice y algunos apartados: si la respuesta no está en ellos, di en qué apartado del índice puede estar." if cut else "")
	)
	prompt = f"<manual>\n{manual}\n</manual>\n\nPregunta: {question}"
	startSession(_("Ayuda de Tiresias"), prompt, system=system, shownText=question)
