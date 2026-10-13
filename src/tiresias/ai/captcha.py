"""Ayuda con los CAPTCHA (foros 10.6): detectar, ir al reto de audio y bajar la voz.

Tiresias nunca resuelve el CAPTCHA. Lo que hace:

- **Detectarlo y anunciarlo** (opción ``captchaDetect``, activada): al cargar
  o cambiar una página se buscan en el búfer los marcos y controles de
  reCAPTCHA, hCaptcha y Cloudflare Turnstile y las imágenes o campos
  «captcha»; también se mira el objeto que recibe el foco (y sus
  antecesores). Se anuncia una vez por página y tipo, con la tecla para ir
  al reto de audio. No envía nada a ningún servicio.
- **Ir al reto de audio** (:func:`jumpToAudio`): lleva el cursor al botón de
  reproducir; si aún no está, al botón «reto de audio»; si tampoco, a la
  casilla «No soy un robot». Con el cursor ya en el botón de reproducir, lo
  pulsa y baja la voz del lector.
- **Bajar o silenciar la voz** (:func:`duck`) mientras suena el audio:
  durante ``captchaDuckSeconds`` segundos la voz baja al ``captchaDuckVolume``
  por ciento (o se calla, según ``captchaDuckMode``) y vuelve sola.
"""

from __future__ import annotations

import re
import time
from typing import Any, Iterable

from .. import api, queue_handler, speech
from ..config import conf
from ..i18n import _
from ..log import getLogger
from ..objects.roles import Role

log = getLogger("captcha")

KIND_LABELS = {
	"recaptcha": "reCAPTCHA",
	"hcaptcha": "hCaptcha",
	"turnstile": "Cloudflare Turnstile",
	"generic": "CAPTCHA",
}

_RX_KIND = [
	("recaptcha", re.compile(r"recaptcha|no soy un robot|i'?m not a robot|je ne suis pas un robot|non sono un robot|ich bin kein roboter|não sou um robô", re.I)),
	("hcaptcha", re.compile(r"hcaptcha", re.I)),
	("turnstile", re.compile(r"turnstile|challenges\.cloudflare|cloudflare security challenge|desaf[ií]o de seguridad de cloudflare|verify you are human|verifica que eres (un )?(ser )?humano|confirme que es (un )?(ser )?humano", re.I)),
	("generic", re.compile(r"captcha", re.I)),
]
#: Botón que abre el reto de audio.
RX_AUDIO = re.compile(r"audio|sonido|escuchar el reto|listen", re.I)
#: Botón que reproduce el audio del reto.
RX_PLAY = re.compile(r"^\s*(play|reproducir|reproduce|escuchar|reproducir audio|play audio)\b|\bpress play\b|pulsa reproducir", re.I)
#: Roles que se miran al detectar (el texto normal de la página no cuenta).
_DETECT_ROLES = {Role.FRAME, Role.DOCUMENT, Role.GRAPHIC, Role.EDITABLETEXT, Role.CHECKBOX, Role.BUTTON, Role.LINK, Role.GROUPING, Role.SECTION, Role.PANE, Role.CUSTOM, Role.UNKNOWN, Role.FORM, Role.REGION, Role.LANDMARK}
_BUTTON_ROLES = {Role.BUTTON, Role.TOGGLEBUTTON, Role.LINK, Role.GRAPHIC}

#: Anuncios hechos: (documento, tipo) -> momento.
_announced: dict[tuple[str, str], float] = {}
#: Silencio o volumen bajo en curso.
_duck: dict[str, Any] = {}


def _enabled() -> bool:
	try:
		return bool(conf["ai"]["captchaDetect"])
	except KeyError:
		return False


def classify(texts: Iterable[str]) -> str | None:
	"""Tipo de CAPTCHA que mencionan los textos (o ``None``)."""
	joined = " ".join(t for t in texts if t)
	if not joined:
		return None
	for kind, rx in _RX_KIND:
		if rx.search(joined):
			return kind
	return None


def nodeTexts(node: Any) -> list[str]:
	out = [node.automationId or "", node.className or "", node.description or ""]
	if node.role in (Role.FRAME, Role.DOCUMENT, Role.LINK, Role.GRAPHIC, Role.EDITABLETEXT, Role.CHECKBOX, Role.BUTTON):
		out.append(node.name or "")
		out.append(getattr(node, "url", "") or "")
	return out


def captchaNodes(nodes: Iterable[Any]) -> list[tuple[str, Any]]:
	"""(tipo, nodo) de los elementos que pertenecen a un CAPTCHA."""
	out = []
	for n in nodes:
		if n.role not in _DETECT_ROLES:
			continue
		kind = classify(nodeTexts(n))
		if kind and not _isPassiveBadge(n):
			out.append((kind, n))
	return out


def _isPassiveBadge(node: Any) -> bool:
	"""Distintivo de reCAPTCHA invisible (v3): está en muchas páginas y no pide nada."""
	n = node
	for _i in range(6):
		if n is None:
			return False
		if "grecaptcha-badge" in (n.className or ""):
			return True
		n = n.parent
	return False


def detect(nodes: Iterable[Any]) -> str | None:
	found = captchaNodes(nodes)
	if not found:
		return None
	# El tipo concreto gana a «captcha» a secas.
	kinds = [k for k, _n in found]
	for kind, _rx in _RX_KIND:
		if kind in kinds:
			return kind
	return None


def _audioGesture() -> str:
	from ..global_commands import GlobalCommands
	from .assistant import gestureLabel

	return gestureLabel(GlobalCommands, "captchaAudio")


def announcement(kind: str) -> str:
	label = KIND_LABELS.get(kind, "CAPTCHA")
	keys = ""
	try:
		keys = _audioGesture()
	except Exception:
		pass
	if kind == "hcaptcha":
		return _("CAPTCHA en la página: {kind}. No tiene reto de audio; puedes usar su cookie de accesibilidad o pedir a la IA que lo describa.").format(kind=label)
	if keys:
		return _("CAPTCHA en la página: {kind}. {keys}: ir al reto de audio.").format(kind=label, keys=keys)
	return _("CAPTCHA en la página: {kind}.").format(kind=label)


def _announceOnce(scope: str, kind: str) -> bool:
	now = time.monotonic()
	k = (scope, kind)
	if now - _announced.get(k, -1e9) < 600:
		return False
	_announced[k] = now
	speech.speakMessage(announcement(kind))
	return True


def onBufferNodes(doc: Any, nodes: list) -> None:
	"""Contenido nuevo en el modo exploración (llamado desde ``browse/loader``)."""
	if not _enabled() or not nodes:
		return
	kind = detect(nodes)
	if kind is None:
		return
	focus = api.getFocusObject()
	try:
		if focus is None or not doc.contains(focus):
			return
		scope = doc._documentKey()
	except Exception:
		return
	_announceOnce(scope, kind)


def onFocus(obj: Any = None) -> None:
	if not _enabled() or obj is None:
		return
	try:
		texts = [obj.name or "", getattr(obj, "UIAAutomationId", "") or "", getattr(obj, "UIAClassName", "") or ""]
		for a in api.getFocusAncestors()[-4:]:
			if a is not None and a.role in (Role.FRAME, Role.DOCUMENT, Role.PANE, Role.GROUPING):
				texts.append(a.name or "")
	except Exception:
		return
	kind = classify(texts)
	if kind is None:
		return
	try:
		fg = api.getForegroundObject()
		scope = f"ventana:{fg.windowHandle if fg is not None else 0}"
	except Exception:
		scope = "ventana"
	doc = getattr(obj, "treeInterceptor", None)
	if doc is not None:
		try:
			scope = doc._documentKey()
		except Exception:
			pass
	_announceOnce(scope, kind)


def initialize() -> None:
	api.post_focusChange.register(onFocus)


def terminate() -> None:
	api.post_focusChange.unregister(onFocus)
	restoreVoice()


# ====================================================================== reto de audio
def _insideCaptcha(node: Any, kinds: set[int]) -> bool:
	n = node
	while n is not None:
		if id(n) in kinds:
			return True
		n = n.parent
	return False


def findTargets(nodes: list) -> dict[str, Any]:
	"""Botones del reto: ``play``, ``audio`` y ``checkbox`` (el primero de cada uno)."""
	found = captchaNodes(nodes)
	containers = {id(n) for _k, n in found}
	out: dict[str, Any] = {"kind": detect(nodes)}
	if not found:
		return out
	# Primero lo que está dentro del CAPTCHA; si no, lo que lo menciona o, para
	# el botón de reproducir, cualquiera de la página (hay un CAPTCHA).
	loose: dict[str, Any] = {}
	for n in nodes:
		if n.end <= n.start:
			continue
		inside = _insideCaptcha(n, containers)
		label = " ".join(p for p in (n.name, n.description) if p)
		slot = out if inside else loose
		if n.role in _BUTTON_ROLES and label:
			if RX_PLAY.search(label):
				slot.setdefault("play", n)
			elif RX_AUDIO.search(label) and (inside or classify([label])):
				slot.setdefault("audio", n)
		if n.role == Role.CHECKBOX and (inside or classify([label])):
			slot.setdefault("checkbox", n)
	for k, v in loose.items():
		out.setdefault(k, v)
	return out


def jumpToAudio() -> None:
	"""Orden: ir al reto de audio (o reproducirlo con la voz baja)."""
	from .assistant import currentBrowseDocument

	doc = currentBrowseDocument()
	if doc is None:
		speech.speakMessage(_("No hay ninguna página en modo exploración"))
		return
	buf = doc.buffer
	targets = findTargets(buf.nodes)
	play, audio, box = targets.get("play"), targets.get("audio"), targets.get("checkbox")
	kind = targets.get("kind")
	caretNode = buf.nodeAt(doc.caret)
	if play is not None:
		atPlay = caretNode is not None and (caretNode is play or play in list(caretNode.ancestors()))
		if atPlay:
			# Segunda pulsación: se reproduce el audio con la voz baja.
			doc.activateAt(play.start)
			queue_handler.callLater(300, duck)
			return
		_goTo(doc, play)
		speech.speakMessage(_("Botón de reproducir el audio del reto. Pulsa otra vez la orden para reproducirlo con la voz del lector baja."))
		return
	if audio is not None:
		_goTo(doc, audio)
		speech.speakMessage(_("Pulsa Intro para pedir el reto de audio y después vuelve a usar la orden para ir al botón de reproducir."))
		return
	if kind == "hcaptcha":
		speech.speakMessage(_("hCaptcha no tiene reto de audio. Puedes usar su cookie de accesibilidad (regístrate en hcaptcha.com/accessibility) o pedir a la IA que describa el reto."))
		if box is not None:
			_goTo(doc, box)
		return
	if box is not None:
		_goTo(doc, box)
		speech.speakMessage(_("Marca la casilla; si aparece un reto, vuelve a usar la orden para ir al reto de audio."))
		return
	if kind:
		speech.speakMessage(_("Hay un CAPTCHA pero no se encuentra el botón de audio"))
	else:
		speech.speakMessage(_("No se encuentra ningún CAPTCHA en la página"))


def _goTo(doc: Any, node: Any) -> None:
	doc._moveCaret(node.start, node=node)
	if node.isFocusable and node.element is not None:
		try:
			node.element.SetFocus()
		except Exception:
			pass


# ====================================================================== voz baja
def _player() -> Any:
	from .. import synth

	s = synth.getSynth()
	return getattr(s, "_player", None) if s is not None else None


def _muteFilter(value: Any = None) -> list:
	return []


def isDucked() -> bool:
	return bool(_duck)


def duck(seconds: int | None = None) -> None:
	"""Baja o silencia la voz unos segundos (vuelve sola)."""
	mode = conf["ai"]["captchaDuckMode"]
	if mode == "off":
		return
	seconds = int(seconds if seconds is not None else conf["ai"]["captchaDuckSeconds"])
	restoreVoice(quiet=True)
	player = _player() if mode == "lower" else None
	if player is not None:
		_duck["volume"] = player.volume
		player.volume = player.volume * max(0, min(100, int(conf["ai"]["captchaDuckVolume"]))) / 100.0
	else:
		# Sin reproductor propio (o modo silencio): no se habla nada.
		speech.cancelSpeech()
		speech.api.filter_speechSequence.register(_muteFilter)
		_duck["muted"] = True
	_duck["timer"] = queue_handler.callLater(max(1, seconds) * 1000, restoreVoice)


def restoreVoice(quiet: bool = False) -> bool:
	"""Devuelve la voz a la normalidad. ``True`` si estaba baja o silenciada."""
	if not _duck:
		return False
	timer = _duck.pop("timer", None)
	if timer is not None:
		try:
			queue_handler.cancelCallLater(timer)
		except Exception:
			pass
	if "volume" in _duck:
		player = _player()
		if player is not None:
			player.volume = _duck["volume"]
	if _duck.pop("muted", False):
		speech.api.filter_speechSequence.unregister(_muteFilter)
	_duck.clear()
	if not quiet:
		from ..audio import tones

		tones.beep(880, 40)
	return True


def toggleDuck() -> None:
	"""Orden: baja la voz para escuchar el audio del reto (otra vez: la recupera)."""
	if restoreVoice(quiet=True):
		speech.speakMessage(_("Voz normal"))
		return
	if conf["ai"]["captchaDuckMode"] == "off":
		speech.speakMessage(_("Bajar la voz durante el audio del CAPTCHA está desactivado en las opciones"))
		return
	seconds = int(conf["ai"]["captchaDuckSeconds"])
	speech.speakMessage(_("Voz baja durante {n} segundos").format(n=seconds))
	# Se deja decir el aviso antes de bajarla.
	queue_handler.callLater(900, duck)
