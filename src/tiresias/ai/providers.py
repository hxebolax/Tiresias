"""Proveedores de IA: Anthropic (Claude), OpenAI, Google Gemini y servidores
locales compatibles con la API de OpenAI.

Todas las peticiones son HTTP con ``urllib`` (sin dependencias) y se hacen
siempre en hilos de trabajo, nunca en el hilo del núcleo ni en el de la
interfaz.

Formato interno de una conversación: lista de ``Message`` con el papel
(``user`` o ``assistant``), el texto y, opcionalmente, imágenes PNG. Cada
proveedor la traduce a su API.

Errores (revisión 1.0.11): los fallos pasajeros (429, 5xx, 529, conexión
cortada) se reintentan dos veces con espera creciente (respetando
``retry-after``); todos los mensajes al usuario están en español y el detalle
que devuelve el servicio solo va al registro, sin la clave.
"""

from __future__ import annotations

import base64
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from ..config import conf
from ..i18n import _
from ..log import getLogger
from . import keys

log = getLogger("ai.providers")

#: Modelos de Claude que se ofrecen en la lista (identificador, nombre). En
#: «Otro modelo de Claude» se puede escribir cualquier otro identificador.
ANTHROPIC_MODELS = [
	("claude-opus-5-5", "Claude Opus 5.5"),
	("claude-sonnet-5-5", "Claude Sonnet 5.5"),
	("claude-haiku-5-5", "Claude Haiku 5.5 (el más rápido y barato)"),
	("claude-fable-5-1", "Claude Fable 5.1 (el más capaz y el más caro)"),
	# Generación anterior: se conserva para las configuraciones guardadas.
	("claude-haiku-4-5-20251001", "Claude Haiku 4.5 (generación anterior)"),
]
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"
#: Gemini 3.8 Flash: modelo estable recomendado para proyectos nuevos
#: (https://ai.google.dev/gemini-api/docs/models). El acceso a los 2.5 está
#: limitado a quien ya los usaba.
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"

#: Límite de salida por defecto (incluye el razonamiento de los modelos que
#: razonan siempre): con menos, los resúmenes largos se cortaban.
DEFAULT_MAX_TOKENS = 16000

#: Modelos de Claude con reintento en el servidor ante un rechazo de seguridad
#: (``fallbacks: "default"``). Claude Haiku 5.5 no lo tiene.
ANTHROPIC_FALLBACK_MODELS = ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")
#: Familias de Claude que admiten ``output_config.effort``.
ANTHROPIC_EFFORT_PREFIXES = ("claude-opus-5", "claude-sonnet-5", "claude-fable-5", "claude-haiku-5", "claude-mythos-5")

#: Reintentos de los fallos pasajeros y espera máxima que se acepta.
MAX_RETRIES = 2
RETRY_BASE_SECONDS = 1.0
MAX_RETRY_WAIT = 20.0
#: Se sustituye en las pruebas para no esperar.
_sleep = time.sleep

#: Motivos de bloqueo de Gemini, en español.
_GEMINI_BLOCK_REASONS = {
	"SAFETY": _("por motivos de seguridad"),
	"IMAGE_SAFETY": _("por motivos de seguridad"),
	"RECITATION": _("porque reproduciría contenido protegido"),
	"IMAGE_RECITATION": _("porque reproduciría contenido protegido"),
	"PROHIBITED_CONTENT": _("por contenido prohibido"),
	"IMAGE_PROHIBITED_CONTENT": _("por contenido prohibido"),
	"BLOCKLIST": _("porque contiene términos bloqueados"),
	"SPII": _("porque podría contener datos personales sensibles"),
	"LANGUAGE": _("porque el idioma no está admitido"),
	"OTHER": _("por un motivo que no indica"),
	"IMAGE_OTHER": _("por un motivo que no indica"),
}

TRUNCATED_NOTE = _("[Respuesta incompleta: se cortó porque superó la longitud máxima.]")


@dataclass
class Message:
	role: str
	text: str = ""
	#: Imágenes PNG (bytes) que acompañan al texto.
	images: list[bytes] = field(default_factory=list)
	#: Contenido original devuelto por el proveedor (se reenvía tal cual).
	raw: Any = None
	#: La respuesta se cortó por el límite de longitud (el texto está incompleto).
	truncated: bool = False


class AIError(Exception):
	"""Error comprensible para el usuario (siempre en español y sin la clave).

	``status`` es el código HTTP cuando lo hay y ``kind`` resume la causa:
	``"auth"`` (clave rechazada o no válida), ``"permission"`` (la clave no da
	acceso al modelo o al servicio), ``"billing"`` (sin saldo o pago
	pendiente), ``"quota"`` (límite de uso), ``"overloaded"`` (servicio
	saturado), ``"server"`` (error del servicio), ``"timeout"`` (no respondió
	a tiempo), ``"network"`` (sin conexión), ``"notfound"`` (modelo
	inexistente), ``"refusal"`` (el modelo rechazó la petición),
	``"truncated"`` (la respuesta se cortó) u otra.
	"""

	def __init__(self, message: str = "", status: int = 0, kind: str = "", retryable: bool = False, retryAfter: float | None = None) -> None:
		super().__init__(message)
		self.status = status
		self.kind = kind
		#: Se puede repetir la petición (fallo pasajero).
		self.retryable = retryable
		#: Segundos que pide esperar el servicio (cabecera ``retry-after``).
		self.retryAfter = retryAfter

	@property
	def isFatal(self) -> bool:
		"""``True`` si no tiene sentido seguir con más peticiones ahora mismo."""
		return self.kind in ("auth", "permission", "billing", "quota", "network", "timeout", "overloaded", "notfound")

	@property
	def isAccountProblem(self) -> bool:
		"""Clave, permisos, saldo o modelo: no se arregla esperando."""
		return self.kind in ("auth", "permission", "billing", "notfound")


def truncatedError() -> AIError:
	return AIError(_("La respuesta se cortó porque superó la longitud máxima permitida. Vuelve a intentarlo o haz una pregunta más concreta."), kind="truncated")


def isLocalUrl(url: str) -> bool:
	"""``True`` si la dirección es de este mismo equipo (nada sale de él)."""
	try:
		host = (urllib.parse.urlsplit((url or "").strip()).hostname or "").lower()
	except ValueError:
		return False
	if not host:
		return False
	if host == "localhost" or host.endswith(".localhost"):
		return True
	try:
		return ipaddress.ip_address(host).is_loopback
	except ValueError:
		return False


def _hostOf(url: str) -> str:
	try:
		return urllib.parse.urlsplit((url or "").strip()).hostname or ""
	except ValueError:
		return ""


_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-*]{4,}|AIza[0-9A-Za-z_\-]{10,})")


def scrub(text: str, secret: str = "") -> str:
	"""Quita claves de un texto que va al registro."""
	if secret:
		text = text.replace(secret, "***")
	return _SECRET_RE.sub("***", text)


def _validHeaderValue(value: str) -> bool:
	return value.isascii() and value.isprintable()


class Provider:
	id = ""
	name = ""
	needsKey = True
	#: El contenido sale del equipo (para el aviso de privacidad).
	isRemote = True
	baseUrl = ""

	def model(self) -> str:
		raise NotImplementedError

	def key(self) -> str:
		return keys.getKey(self.id)

	def isConfigured(self) -> bool:
		return not self.configProblem()

	def configProblem(self) -> str:
		"""Qué falta para poder usar el proveedor (cadena vacía si nada)."""
		if self.needsKey and not self.key():
			return _("Falta la clave de {name}. Escríbela en Opciones, Inteligencia artificial.").format(name=self.name)
		return ""

	def contextChars(self) -> int:
		"""Máximo de caracteres de documento que se envían."""
		return max(1000, int(conf["ai"]["maxContextChars"]))

	def privacyKey(self) -> str:
		"""Identificador del destino para el aviso de privacidad."""
		return self.id

	def privacyName(self) -> str:
		return self.name

	@property
	def insecure(self) -> bool:
		"""Envía a otro equipo sin cifrar (http)."""
		return False

	# --------------------------------------------------------- HTTP
	def _post(self, url: str, body: dict, headers: dict[str, str], timeout: float | None = None, retries: int | None = None) -> dict:
		"""POST con reintentos de los fallos pasajeros. Lanza :class:`AIError`."""
		for v in headers.values():
			if not _validHeaderValue(str(v)):
				# Una clave con saltos de línea, letras con tilde o caracteres
				# invisibles: nunca se manda ni se dice.
				raise AIError(
					_("La clave de {name} contiene caracteres que no pueden formar parte de una clave (espacios, saltos de línea, letras con tilde o caracteres invisibles). Vuelve a copiarla y escríbela en Opciones, Inteligencia artificial.").format(name=self.name),
					kind="auth",
				)
		data = json.dumps(body).encode("utf-8")
		limit = max(5.0, float(conf["ai"]["timeout"])) if timeout is None else max(1.0, float(timeout))
		attempts = 1 + (MAX_RETRIES if retries is None else max(0, int(retries)))
		for attempt in range(attempts):
			try:
				return self._postOnce(url, data, headers, limit)
			except AIError as e:
				if not e.retryable or attempt + 1 >= attempts:
					raise
				wait = e.retryAfter if e.retryAfter is not None else RETRY_BASE_SECONDS * (2**attempt)
				if wait > MAX_RETRY_WAIT:
					raise
				log.info("%s: fallo pasajero (%s); reintento %d dentro de %.1f s", self.name, e.kind or e.status, attempt + 1, wait)
				_sleep(max(0.0, wait))
		raise AIError(_("No se pudo conectar con {name}.").format(name=self.name), kind="network")  # pragma: no cover

	def _postOnce(self, url: str, data: bytes, headers: dict[str, str], limit: float) -> dict:
		req = urllib.request.Request(url, data=data, method="POST")
		req.add_header("Content-Type", "application/json")
		for k, v in headers.items():
			req.add_header(k, v)
		name = self.name
		try:
			with urllib.request.urlopen(req, timeout=limit) as resp:
				payload = resp.read()
		except urllib.error.HTTPError as e:
			raise self._httpError(e) from None
		except urllib.error.URLError as e:
			raise self._networkError(e.reason, limit) from None
		except (TimeoutError, socket.timeout) as e:
			raise self._networkError(e, limit) from None
		except (ConnectionError, http.client.HTTPException, ssl.SSLError) as e:
			raise self._networkError(e, limit) from None
		except UnicodeError:
			# Cabeceras con caracteres no válidos (no debería pasar: se comprueban antes).
			raise AIError(_("La clave de {name} no es válida. Vuelve a escribirla en Opciones, Inteligencia artificial.").format(name=name), kind="auth") from None
		except ValueError as e:
			if "header" in str(e).lower():
				raise AIError(_("La clave de {name} no es válida. Vuelve a escribirla en Opciones, Inteligencia artificial.").format(name=name), kind="auth") from None
			log.warning("Dirección no válida para %s: %s", name, e)
			raise AIError(_("La dirección de {name} no es válida. Revísala en Opciones, Inteligencia artificial.").format(name=name), kind="network") from None
		except OSError as e:
			raise self._networkError(e, limit) from None
		try:
			return json.loads(payload.decode("utf-8"))
		except ValueError:
			log.warning("Respuesta no JSON de %s: %r", name, payload[:200])
			raise AIError(_("{name} devolvió una respuesta que no se entiende (¿un proxy o un portal de inicio de sesión de la red?).").format(name=name)) from None

	def _networkError(self, reason: Any, limit: float) -> AIError:
		name = self.name
		log.warning("Error de red con %s: %r", name, reason)
		if isinstance(reason, (TimeoutError, socket.timeout)):
			return AIError(
				_("{name} no respondió en {n} segundos. Inténtalo de nuevo o aumenta el tiempo máximo de espera en Opciones, Inteligencia artificial.").format(name=name, n=int(limit)),
				kind="timeout",
			)
		if isinstance(reason, socket.gaierror):
			return AIError(_("No se encuentra el servidor de {name}. Comprueba la conexión a Internet y la dirección del servicio.").format(name=name), kind="network")
		if isinstance(reason, ConnectionRefusedError):
			return AIError(_("{name} no acepta conexiones. Si es un servidor de tu equipo o de tu red, comprueba que está en marcha y que la dirección es correcta.").format(name=name), kind="network")
		if isinstance(reason, (ssl.SSLError, ssl.CertificateError)):
			return AIError(_("Falló la conexión segura con {name}: el certificado no es válido o un proxy o un antivirus intercepta la conexión.").format(name=name), kind="network")
		if isinstance(reason, (ConnectionResetError, ConnectionAbortedError, http.client.HTTPException)):
			# Conexión cortada a mitad: se puede reintentar.
			return AIError(_("Se cortó la conexión con {name}. Comprueba la conexión a Internet o el proxy.").format(name=name), kind="network", retryable=True)
		return AIError(_("No se pudo conectar con {name}. Comprueba la conexión a Internet o el proxy.").format(name=name), kind="network")

	def _httpError(self, e: urllib.error.HTTPError) -> AIError:
		code = e.code
		raw = ""
		try:
			raw = e.read().decode("utf-8", "replace")
		except Exception:
			pass
		finally:
			try:
				e.close()
			except Exception:
				pass
		data: Any = None
		try:
			data = json.loads(raw) if raw else None
		except ValueError:
			data = None
		detail = self._errorMessage(data) or raw[:300]
		etype = ""
		if isinstance(data, dict) and isinstance(data.get("error"), dict):
			err = data["error"]
			etype = str(err.get("type") or err.get("code") or err.get("status") or "")
		retryAfter = None
		try:
			ra = e.headers.get("retry-after") if e.headers is not None else None
			retryAfter = float(ra) if ra not in (None, "") else None
		except (TypeError, ValueError):
			retryAfter = None
		try:
			secret = self.key()
		except Exception:
			secret = ""
		log.warning("Error HTTP %s de %s (%s): %s", code, self.name, etype, scrub(detail, secret))
		name = self.name
		model = self.model()
		if code == 401 or (code == 400 and self._isInvalidKey(data, raw)):
			return AIError(_("{name} rechazó la clave. Revisa la clave en Opciones, Inteligencia artificial.").format(name=name), code, "auth")
		if code == 402 or etype in ("billing_error", "insufficient_quota"):
			return AIError(_("{name} indica un problema de saldo o de pago en tu cuenta. Revísalo en la web del servicio.").format(name=name), code, "billing")
		if code == 403:
			return AIError(
				_("{name} no permite esta petición con tu clave: puede que tu cuenta no tenga acceso al modelo {model} o al servicio. Revisa la clave y el modelo en Opciones, Inteligencia artificial.").format(name=name, model=model),
				code,
				"permission",
			)
		if code == 404:
			return AIError(_("{name} no encuentra el modelo {model} o no está disponible para tu cuenta. Revisa el modelo en Opciones, Inteligencia artificial.").format(name=name, model=model), code, "notfound")
		if code == 408:
			return AIError(_("{name} tardó demasiado en responder. Inténtalo de nuevo.").format(name=name), code, "timeout", retryable=True, retryAfter=retryAfter)
		if code == 413:
			return AIError(_("La petición es demasiado grande para {name} (imagen o documento muy grandes). Prueba con menos texto o una imagen más pequeña.").format(name=name), code, "toolarge")
		if code == 429:
			return AIError(_("{name} indica que se ha superado el límite de uso. Inténtalo más tarde.").format(name=name), code, "quota", retryable=True, retryAfter=retryAfter)
		if code == 529 or etype == "overloaded_error":
			return AIError(_("{name} está saturado en este momento. Inténtalo dentro de un rato.").format(name=name), code, "overloaded", retryable=True, retryAfter=retryAfter)
		if code >= 500:
			return AIError(_("{name} tiene un problema temporal (error {code}). Inténtalo dentro de un rato.").format(name=name, code=code), code, "server", retryable=True, retryAfter=retryAfter)
		return AIError(_("{name} no aceptó la petición (error {code}). El detalle está en el registro de Tiresias.").format(name=name, code=code), code)

	@staticmethod
	def _isInvalidKey(data: Any, raw: str) -> bool:
		"""Gemini responde 400 (``API_KEY_INVALID``) a una clave no válida."""
		if "API_KEY_INVALID" in raw or "API key not valid" in raw or "API key expired" in raw:
			return True
		return False

	@staticmethod
	def _errorMessage(data: Any) -> str:
		if isinstance(data, dict):
			err = data.get("error")
			if isinstance(err, dict):
				return str(err.get("message") or "")
			if isinstance(err, str):
				return err
			return str(data.get("message") or "")
		return ""

	def chat(
		self,
		messages: list[Message],
		system: str = "",
		maxTokens: int = DEFAULT_MAX_TOKENS,
		effort: str = "",
		timeout: float | None = None,
		retries: int | None = None,
	) -> Message:
		"""Envía la conversación y devuelve el mensaje de respuesta.

		``effort`` («low», «medium», «high») pide menos o más razonamiento a
		los modelos que lo admiten; las tareas cortas (etiquetas, texto
		alternativo, traducciones) usan «low». ``timeout`` (segundos) y
		``retries`` sustituyen a los de las opciones (la traducción de la voz
		usa una espera corta y ningún reintento). Si la respuesta se cortó por
		la longitud, ``truncated`` del mensaje es ``True``.
		"""
		problem = self.configProblem()
		if problem:
			raise AIError(problem, kind="auth")
		return self._chat(messages, system, maxTokens, effort, timeout, retries)

	def _chat(self, messages: list[Message], system: str, maxTokens: int, effort: str = "", timeout: float | None = None, retries: int | None = None) -> Message:
		raise NotImplementedError


def configMessage(provider: Any) -> str:
	"""Qué falta para usar ``provider`` (cadena vacía si está listo)."""
	fn = getattr(provider, "configProblem", None)
	if callable(fn):
		return fn()
	if provider.isConfigured():
		return ""
	return _("Falta la clave de {name}. Escríbela en Opciones, Inteligencia artificial.").format(name=getattr(provider, "name", ""))


def _b64(data: bytes) -> str:
	return base64.b64encode(data).decode("ascii")


class AnthropicProvider(Provider):
	id = "anthropic"
	name = "Anthropic Claude"
	baseUrl = "https://api.anthropic.com"

	def model(self) -> str:
		custom = (conf["ai"].get("anthropicCustomModel", "") or "").strip()
		return custom or conf["ai"]["anthropicModel"] or DEFAULT_ANTHROPIC_MODEL

	@staticmethod
	def traits(model: str) -> tuple[bool, bool]:
		"""(admite esfuerzo, admite reintento en el servidor) del modelo."""
		return model.startswith(ANTHROPIC_EFFORT_PREFIXES), model in ANTHROPIC_FALLBACK_MODELS

	def buildBody(self, messages: list[Message], system: str, maxTokens: int, effort: str = "") -> tuple[dict, dict[str, str]]:
		model = self.model()
		out = []
		for m in messages:
			if m.role == "assistant" and m.raw is not None:
				# Se reenvía la respuesta completa (con sus bloques de razonamiento).
				out.append({"role": "assistant", "content": m.raw})
				continue
			content: list[dict] = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _b64(img)}} for img in m.images]
			if m.text:
				content.append({"type": "text", "text": m.text})
			out.append({"role": m.role, "content": content})
		body: dict[str, Any] = {"model": model, "max_tokens": maxTokens, "messages": out}
		if system:
			body["system"] = system
		headers = {"x-api-key": self.key(), "anthropic-version": "2023-06-01"}
		withEffort, withFallback = self.traits(model)
		if withEffort:
			# Estos modelos razonan siempre. Esfuerzo explícito: medio por
			# defecto (buena calidad sin hacer esperar demasiado; en Fable 5.1 el
			# del servicio es alto y caro); las tareas cortas piden «low».
			body["output_config"] = {"effort": effort if effort in ("low", "medium", "high") else "medium"}
		if withFallback:
			# Si el modelo rechaza la petición por seguridad, el servicio la reintenta con otro.
			body["fallbacks"] = "default"
			headers["anthropic-beta"] = "server-side-fallback-2026-07-01"
		return body, headers

	def _chat(self, messages: list[Message], system: str, maxTokens: int, effort: str = "", timeout: float | None = None, retries: int | None = None) -> Message:
		body, headers = self.buildBody(messages, system, maxTokens, effort)
		data = self._post(self.baseUrl.rstrip("/") + "/v1/messages", body, headers, timeout, retries)
		content = data.get("content") or []
		text = "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text").strip()
		stop = data.get("stop_reason")
		if stop == "refusal":
			details = data.get("stop_details") or {}
			log.info("Rechazo de %s: %s", self.name, details)
			raise AIError(_("El modelo ha rechazado la petición por sus normas de seguridad. Prueba a plantearla de otra forma."), kind="refusal")
		truncated = stop in ("max_tokens", "model_context_window_exceeded")
		if truncated:
			# El razonamiento cuenta para el límite: sin texto no hay nada que mostrar.
			log.warning("Respuesta de %s cortada (%s, límite %d)", self.name, stop, maxTokens)
			if not text:
				raise truncatedError()
		if not text:
			raise AIError(_("{name} no devolvió texto.").format(name=self.name))
		return Message("assistant", text, raw=content, truncated=truncated)


def _isReasoningModel(model: str) -> bool:
	m = (model or "").lower()
	return m.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4"))


class OpenAICompatibleProvider(Provider):
	"""API de chat de OpenAI (también la usan Ollama, LM Studio y otros servicios)."""

	id = "openai"
	name = "OpenAI"
	baseUrl = "https://api.openai.com/v1"
	#: Manda ``reasoning_effort`` a los modelos que razonan (solo OpenAI).
	supportsReasoningEffort = True

	def model(self) -> str:
		return conf["ai"]["openaiModel"] or DEFAULT_OPENAI_MODEL

	def url(self) -> str:
		return self.baseUrl.rstrip("/") + "/chat/completions"

	#: Nombre del límite de salida en el cuerpo de la petición.
	maxTokensField = "max_completion_tokens"

	def buildBody(self, messages: list[Message], system: str, maxTokens: int, effort: str = "") -> tuple[dict, dict[str, str]]:
		out: list[dict] = []
		if system:
			out.append({"role": "system", "content": system})
		for m in messages:
			if m.images:
				parts: list[dict] = [{"type": "text", "text": m.text}] if m.text else []
				parts += [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + _b64(img)}} for img in m.images]
				out.append({"role": m.role, "content": parts})
			else:
				out.append({"role": m.role, "content": m.text})
		model = self.model()
		body: dict[str, Any] = {"model": model, "messages": out}
		if maxTokens:
			# OpenAI usa «max_completion_tokens» (incluye el razonamiento); los
			# servidores locales y compatibles, el clásico «max_tokens».
			body[self.maxTokensField] = int(maxTokens)
		if self.supportsReasoningEffort and effort == "low" and _isReasoningModel(model):
			# Tareas cortas: poco razonamiento (los modelos sin razonamiento
			# rechazarían el parámetro, por eso solo va a los que razonan).
			body["reasoning_effort"] = "low"
		headers = {}
		key = self.key()
		if key:
			headers["Authorization"] = "Bearer " + key
		return body, headers

	def _chat(self, messages: list[Message], system: str, maxTokens: int, effort: str = "", timeout: float | None = None, retries: int | None = None) -> Message:
		body, headers = self.buildBody(messages, system, maxTokens, effort)
		data = self._post(self.url(), body, headers, timeout, retries)
		try:
			choice = data["choices"][0]
			msg = choice["message"]
		except (KeyError, IndexError, TypeError):
			log.warning("Respuesta inesperada de %s: %s", self.name, str(data)[:300])
			raise AIError(_("{name} devolvió una respuesta que no se entiende.").format(name=self.name)) from None
		content = msg.get("content")
		if isinstance(content, list):
			content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
		text = (content or "").strip()
		truncated = choice.get("finish_reason") == "length"
		if not text and truncated:
			raise truncatedError()
		if not text:
			if msg.get("refusal"):
				log.info("Rechazo de %s: %s", self.name, msg.get("refusal"))
				raise AIError(_("El modelo ha rechazado la petición por sus normas de seguridad. Prueba a plantearla de otra forma."), kind="refusal")
			raise AIError(_("{name} no devolvió texto.").format(name=self.name))
		if truncated:
			log.warning("Respuesta de %s cortada por la longitud (%d)", self.name, maxTokens)
		return Message("assistant", text, truncated=truncated)


class LocalProvider(OpenAICompatibleProvider):
	"""Ollama, LM Studio u otro servidor compatible con OpenAI en este equipo o en la red."""

	id = "local"
	name = _("Servidor local (Ollama o LM Studio)")
	needsKey = False
	maxTokensField = "max_tokens"
	supportsReasoningEffort = False

	@property
	def baseUrl(self) -> str:  # type: ignore[override]
		return conf["ai"]["localUrl"] or "http://localhost:11434/v1"

	@property
	def isRemote(self) -> bool:  # type: ignore[override]
		# Solo es «local» si la dirección es de este equipo: en la red o en
		# Internet las imágenes salen del equipo y hay que avisar.
		return not isLocalUrl(self.baseUrl)

	@property
	def insecure(self) -> bool:
		return self.isRemote and self.baseUrl.strip().lower().startswith("http://")

	def model(self) -> str:
		return conf["ai"]["localModel"] or "gemma3"

	def contextChars(self) -> int:
		# Ollama usa por defecto un contexto pequeño (4k tokens con menos de
		# 24 GiB de memoria de vídeo) y recorta sin avisar lo que no cabe.
		return max(1000, min(int(conf["ai"]["maxContextChars"]), int(conf["ai"].get("localMaxContextChars", 12000))))

	def privacyKey(self) -> str:
		return f"{self.id}:{_hostOf(self.baseUrl)}"

	def privacyName(self) -> str:
		host = _hostOf(self.baseUrl)
		return f"{self.name} ({host})" if host else self.name


class GeminiProvider(Provider):
	id = "gemini"
	name = "Google Gemini"
	baseUrl = "https://generativelanguage.googleapis.com/v1beta"

	def model(self) -> str:
		return conf["ai"]["geminiModel"] or DEFAULT_GEMINI_MODEL

	def buildBody(self, messages: list[Message], system: str, maxTokens: int, effort: str = "") -> tuple[dict, dict[str, str]]:
		contents = []
		for m in messages:
			if m.role == "assistant" and isinstance(m.raw, dict) and m.raw.get("parts"):
				# Respuesta completa, con sus firmas de razonamiento (thoughtSignature):
				# sin ellas los modelos 3.x pierden el hilo en el seguimiento.
				contents.append({"role": "model", "parts": m.raw["parts"]})
				continue
			parts: list[dict] = [{"inline_data": {"mime_type": "image/png", "data": _b64(img)}} for img in m.images]
			if m.text:
				parts.append({"text": m.text})
			contents.append({"role": "model" if m.role == "assistant" else "user", "parts": parts})
		body: dict[str, Any] = {"contents": contents, "generationConfig": {"maxOutputTokens": maxTokens}}
		if system:
			body["systemInstruction"] = {"parts": [{"text": system}]}
		# La clave va en una cabecera, nunca en la dirección.
		return body, {"x-goog-api-key": self.key()}

	@staticmethod
	def _blockReason(reason: str) -> str:
		return _GEMINI_BLOCK_REASONS.get(reason, _("por un motivo que no indica ({reason})").format(reason=reason))

	def _chat(self, messages: list[Message], system: str, maxTokens: int, effort: str = "", timeout: float | None = None, retries: int | None = None) -> Message:
		body, headers = self.buildBody(messages, system, maxTokens, effort)
		url = f"{self.baseUrl.rstrip('/')}/models/{self.model()}:generateContent"
		data = self._post(url, body, headers, timeout, retries)
		cands = data.get("candidates") if isinstance(data, dict) else None
		if not cands or not isinstance(cands, list) or not isinstance(cands[0], dict):
			block = ((data.get("promptFeedback") or {}) if isinstance(data, dict) else {}).get("blockReason")
			if block:
				raise AIError(_("Google Gemini ha rechazado la petición {why}.").format(why=self._blockReason(str(block))), kind="refusal")
			raise AIError(_("{name} devolvió una respuesta que no se entiende.").format(name=self.name))
		cand = cands[0]
		content = cand.get("content") if isinstance(cand.get("content"), dict) else {}
		parts = [p for p in content.get("parts", []) if isinstance(p, dict)]
		text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
		reason = str(cand.get("finishReason") or "")
		truncated = reason == "MAX_TOKENS"
		if not text and truncated:
			# Gemini cuenta el razonamiento dentro de maxOutputTokens.
			raise truncatedError()
		if not text and reason in _GEMINI_BLOCK_REASONS:
			raise AIError(_("Google Gemini ha bloqueado la respuesta {why}.").format(why=self._blockReason(reason)), kind="refusal")
		if not text:
			raise AIError(_("{name} no devolvió texto.").format(name=self.name))
		return Message("assistant", text, raw={"role": "model", "parts": parts} if parts else None, truncated=truncated)


PROVIDERS: dict[str, Provider] = {
	"anthropic": AnthropicProvider(),
	"openai": OpenAICompatibleProvider(),
	"gemini": GeminiProvider(),
	"local": LocalProvider(),
}


def getProvider(providerId: str | None = None) -> Provider:
	return PROVIDERS.get(providerId or conf["ai"]["provider"]) or PROVIDERS["anthropic"]
